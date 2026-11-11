"""«Мои заявки»: листы с пагинацией, карточка, отмена пользователем."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.config import get_settings
from bot.db import repo
from bot.db.models import ACTIVE_STATUSES, TicketStatus
from bot.keyboards.admin import admin_card_kb
from bot.keyboards.user import cancelled_kb, main_menu, ticket_card_kb, user_list_kb
from bot.services.board import admin_card_text, refresh_board_message, user_card_text
from bot.services.log import log_action

router = Router(name="user_list")
logger = logging.getLogger(__name__)


def _parse_ticket_cb(data: str | None) -> tuple[int, str] | None:
    """t:<id>:<action> -> (id, action)."""
    if not data:
        return None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "t" or not parts[1].isdigit():
        return None
    return int(parts[1]), parts[2]


async def _edit(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Не удалось обновить карточку: %s", exc)
    except TelegramAPIError:
        logger.warning("Ошибка Telegram при обновлении сообщения", exc_info=True)


async def _show_list(callback: CallbackQuery, state: FSMContext, page: int) -> None:
    page = max(1, page)
    result = await repo.list_user_active(callback.from_user.id, page=page)
    if result.items and page > result.pages:
        page = result.pages
        result = await repo.list_user_active(callback.from_user.id, page=page)

    await state.update_data(list_page=page)

    if not result.items:
        await _edit(
            callback,
            "📋 <b>Мои заявки</b>\n\nАктивных заявок нет.",
            main_menu(),
        )
        return

    text = (
        f"📋 <b>Мои заявки</b> · стр. {page}/{result.pages}\n"
        f"Активных: {result.total}\n\n"
        "Выберите заявку:"
    )
    await _edit(callback, text, user_list_kb(result.items, page, result.pages))


async def _show_card(callback: CallbackQuery, state: FSMContext, ticket_id: int) -> None:
    # Админу карточка показывается с действиями; пользователю — его собственная.
    if get_settings().is_admin(callback.from_user.id):
        ticket = await repo.get_ticket(ticket_id)
        if ticket is None:
            await callback.answer("Заявка не найдена", show_alert=True)
            return
        data = await state.get_data()
        tab = data.get("admin_tab", "all")
        page = data.get("admin_page", 1)
        await _edit(callback, admin_card_text(ticket), admin_card_kb(ticket, tab, page))
        await callback.answer()
        return

    ticket = await repo.get_user_ticket(callback.from_user.id, ticket_id)
    if ticket is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    page = (await state.get_data()).get("list_page", 1)
    if ticket.status not in ACTIVE_STATUSES:
        await callback.answer("Заявка больше не активна", show_alert=True)
        await _show_list(callback, state, page)
        return

    await _edit(callback, user_card_text(ticket), ticket_card_kb(ticket, page))
    await callback.answer()


async def _cancel_ticket(
    callback: CallbackQuery, state: FSMContext, bot: Bot, ticket_id: int
) -> None:
    tg_id = callback.from_user.id
    ticket = await repo.get_user_ticket(tg_id, ticket_id)
    if ticket is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    if ticket.status is not TicketStatus.WAITING:
        await callback.answer(
            "Отменить можно только заявку в статусе «Ожидает»", show_alert=True
        )
        return

    await repo.set_status(ticket.id, TicketStatus.CANCELLED)
    updated = await repo.get_ticket(ticket.id)
    if updated is None:  # pragma: no cover - заявка не могла исчезнуть
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    ticket = updated

    try:
        await refresh_board_message(bot, ticket.id, note="❌ Отменена пользователем")
    except TelegramAPIError:
        logger.exception("Не удалось обновить доску по заявке #%s", ticket.number)

    try:
        settings = get_settings()
        await bot.send_message(
            settings.tickets_chat_id,
            f"❌ Заявка <b>#{ticket.number:04d}</b> отменена пользователем "
            f"(<code>{tg_id}</code>).",
            message_thread_id=settings.tickets_thread_id,
        )
    except TelegramAPIError:
        logger.warning("Не удалось уведомить чат заявок об отмене #%s", ticket.number)

    await log_action(
        bot,
        "ticket_cancelled",
        actor_tg_id=tg_id,
        ticket_id=ticket.id,
        payload={"number": ticket.number},
    )

    await _edit(callback, f"❌ Заявка <b>#{ticket.number:04d}</b> отменена.", cancelled_kb())
    await callback.answer("Заявка отменена")


@router.callback_query(F.data.startswith("u:list:"))
async def list_page(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.rsplit(":", 1)[-1] if callback.data else ""
    page = int(raw) if raw.isdigit() else 1
    await _show_list(callback, state, page)
    await callback.answer()


@router.callback_query(F.data.startswith("t:"))
async def ticket_callback(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    parsed = _parse_ticket_cb(callback.data)
    if parsed is None:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return

    ticket_id, action = parsed
    if action == "card":
        await _show_card(callback, state, ticket_id)
    elif action == "cancel":
        await _cancel_ticket(callback, state, bot, ticket_id)
    elif action == "back":
        page = (await state.get_data()).get("list_page", 1)
        await _show_list(callback, state, page)
        await callback.answer()
    else:
        await callback.answer()
