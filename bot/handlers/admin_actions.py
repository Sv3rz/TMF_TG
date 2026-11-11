"""Действия администратора: в работу, ответить, закрыть, вложения."""

from __future__ import annotations

import logging
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.db import repo
from bot.db.models import ACTIVE_STATUSES, Ticket, TicketStatus
from bot.handlers.user_new import collect_files, extract_text
from bot.keyboards.admin import admin_cancel_kb, admin_card_kb, admin_menu
from bot.services.board import (
    ActionResult,
    admin_card_text,
    close_ticket,
    refresh_board_message,
    take_ticket,
)
from bot.services.log import log_action
from bot.states import AdminReply

router = Router(name="admin_actions")
logger = logging.getLogger(__name__)

ADMIN_MENU_TEXT = "<b>Админ-панель</b>\n\nВыберите раздел:"


def _parse_act(data: str | None) -> tuple[int, str] | None:
    if not data:
        return None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "act" or not parts[1].isdigit():
        return None
    return int(parts[1]), parts[2]


async def _render_card(
    callback: CallbackQuery, state: FSMContext, ticket: Ticket
) -> None:
    if callback.message is None:
        return
    data = await state.get_data()
    tab = data.get("admin_tab", "all")
    page = data.get("admin_page", 1)
    try:
        await callback.message.edit_text(
            admin_card_text(ticket), reply_markup=admin_card_kb(ticket, tab, page)
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Не удалось обновить админ-карточку: %s", exc)
    except TelegramAPIError:
        logger.warning("Ошибка Telegram при обновлении админ-карточки", exc_info=True)


async def _take(bot: Bot, callback: CallbackQuery, state: FSMContext, ticket_id: int) -> None:
    result, ticket = await take_ticket(
        bot, ticket_id, callback.from_user.id, callback.from_user.full_name
    )
    if result is ActionResult.NOT_FOUND or ticket is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if result is ActionResult.WRONG_STATUS:
        message = (
            "Заявка уже в работе"
            if ticket.status is TicketStatus.IN_PROGRESS
            else "Заявка уже закрыта или отменена"
        )
        await callback.answer(message, show_alert=True)
        return

    await _render_card(callback, state, ticket)
    await callback.answer("Взято в работу")


async def _close(bot: Bot, callback: CallbackQuery, state: FSMContext, ticket_id: int) -> None:
    result, ticket = await close_ticket(
        bot, ticket_id, callback.from_user.id, callback.from_user.full_name
    )
    if result is ActionResult.NOT_FOUND or ticket is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if result is ActionResult.WRONG_STATUS:
        await callback.answer("Заявка уже закрыта или отменена", show_alert=True)
        return

    await _render_card(callback, state, ticket)
    await callback.answer("Заявка закрыта")


async def _start_reply(callback: CallbackQuery, state: FSMContext, ticket_id: int) -> None:
    ticket = await repo.get_ticket(ticket_id)
    if ticket is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if ticket.status not in ACTIVE_STATUSES:
        await callback.answer("Ответить можно только по активной заявке", show_alert=True)
        return

    await state.set_state(AdminReply.content)
    await state.update_data(reply_ticket_id=ticket.id)

    if callback.message is not None:
        await callback.message.answer(
            f"✉️ Ответ по заявке <b>#{ticket.number:04d}</b>.\n"
            "Отправьте текст и/или фото, видео одним сообщением.",
            reply_markup=admin_cancel_kb(),
        )
    await callback.answer()


async def _send_files(callback: CallbackQuery, ticket_id: int) -> None:
    attachments = await repo.list_attachments(ticket_id, kind="ticket")
    if not attachments:
        await callback.answer("Вложений нет", show_alert=True)
        return

    sent = 0
    for item in attachments:
        try:
            if item.file_type == "photo":
                await callback.bot.send_photo(callback.from_user.id, item.file_id)
            else:
                await callback.bot.send_video(callback.from_user.id, item.file_id)
            sent += 1
        except TelegramAPIError:
            logger.warning("Не удалось переслать вложение %s", item.file_id, exc_info=True)

    await callback.answer(f"Переслано файлов: {sent}")


@router.callback_query(F.data.startswith("act:"))
async def act(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    parsed = _parse_act(callback.data)
    if parsed is None:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return

    ticket_id, action = parsed
    if action == "take":
        await _take(bot, callback, state, ticket_id)
    elif action == "close":
        await _close(bot, callback, state, ticket_id)
    elif action == "reply":
        await _start_reply(callback, state, ticket_id)
    elif action == "files":
        await _send_files(callback, ticket_id)
    else:
        await callback.answer()


@router.callback_query(F.data == "a:cancel")
async def cancel_reply(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message is not None:
        await callback.message.answer(ADMIN_MENU_TEXT, reply_markup=admin_menu())
    await callback.answer("Отменено")


@router.message(AdminReply.content)
async def on_reply(
    message: Message, state: FSMContext, bot: Bot, album: list[Message] | None = None
) -> None:
    data = await state.get_data()
    ticket_id = data.get("reply_ticket_id")
    if not isinstance(ticket_id, int):
        await state.clear()
        await message.answer("Сессия истекла. Откройте заявку заново.")
        return

    ticket = await repo.get_ticket(ticket_id)
    if ticket is None or ticket.status not in ACTIVE_STATUSES:
        await state.clear()
        await message.answer("Заявка недоступна для ответа.")
        return

    sources = album or [message]
    files = collect_files(sources)
    text = extract_text(sources)
    if not text and not files:
        await message.answer("Отправьте текст, фото или видео.")
        return

    tab = data.get("admin_tab", "all")
    page = data.get("admin_page", 1)

    try:
        if len(sources) > 1:
            await bot.copy_messages(
                chat_id=ticket.user.tg_id,
                from_chat_id=message.chat.id,
                message_ids=[item.message_id for item in sources],
            )
        else:
            await bot.copy_message(
                chat_id=ticket.user.tg_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
    except TelegramAPIError:
        logger.exception("Не удалось доставить ответ по заявке #%s", ticket.number)
        await message.answer(
            "❌ Не удалось отправить: возможно, пользователь заблокировал бота."
        )
        return

    await repo.add_admin_reply(ticket.id, message.from_user.id, text)
    if files:
        await repo.add_attachments(ticket.id, files, kind="admin_reply")

    with suppress(TelegramAPIError):
        await refresh_board_message(bot, ticket.id)

    await log_action(
        bot,
        "admin_reply",
        actor_tg_id=message.from_user.id,
        ticket_id=ticket.id,
        payload={"number": ticket.number, "files": len(files)},
    )

    await state.clear()
    refreshed = await repo.get_ticket(ticket.id)
    if refreshed is None:
        return

    await message.answer(f"✅ Ответ отправлен в заявку <b>#{refreshed.number:04d}</b>.")
    await message.answer(
        admin_card_text(refreshed), reply_markup=admin_card_kb(refreshed, tab, page)
    )
