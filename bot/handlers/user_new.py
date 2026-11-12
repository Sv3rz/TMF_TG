"""Создание заявки: New.description -> New.priority -> New.place -> New.confirm."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.db import repo
from bot.db.models import Priority
from bot.keyboards.user import after_create_kb, cancel_row, confirm_kb, place_kb, priority_kb
from bot.services.board import preview_text, publish_ticket
from bot.services.log import log_action
from bot.states import New

router = Router(name="user_new")
logger = logging.getLogger(__name__)

MAX_DESCRIPTION = 4000


def collect_files(messages: list[Message]) -> list[dict[str, str]]:
    """Только photo/video; документы и прочее игнорируются."""
    files: list[dict[str, str]] = []
    for msg in messages:
        if msg.photo:
            files.append({"file_id": msg.photo[-1].file_id, "file_type": "photo"})
        elif msg.video:
            files.append({"file_id": msg.video.file_id, "file_type": "video"})
    return files


def extract_text(messages: list[Message]) -> str | None:
    for msg in messages:
        caption = (msg.caption or "").strip()
        if caption:
            return caption[:MAX_DESCRIPTION]
    for msg in messages:
        text = (msg.text or "").strip()
        if text:
            return text[:MAX_DESCRIPTION]
    return None


@router.callback_query(F.data == "u:new")
async def new_start(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        await callback.answer("Откройте диалог с ботом", show_alert=True)
        return

    await state.clear()
    await state.set_state(New.description)
    await callback.message.answer(
        "<b>Новая заявка</b>\n\n"
        "Опишите проблему <b>одним сообщением</b>: текст и/или фото, видео.\n"
        "Медиа без текста тоже подойдёт.",
        reply_markup=cancel_row(),
    )
    await callback.answer()


@router.message(New.description)
async def on_description(
    message: Message, state: FSMContext, album: list[Message] | None = None
) -> None:
    sources = album or [message]
    files = collect_files(sources)
    description = extract_text(sources)

    if not description and not files:
        await message.answer(
            "Нужно описание текстом или фото/видео. Поддерживаются только photo и video.",
            reply_markup=cancel_row(),
        )
        return

    await state.update_data(description=description, files=files)
    await state.set_state(New.priority)
    await message.answer("Выберите приоритет заявки:", reply_markup=priority_kb())


@router.callback_query(New.priority, F.data.startswith("prio:"))
async def on_priority(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.split(":", 1)[1] if callback.data else ""
    try:
        priority = Priority(raw)
    except ValueError:
        await callback.answer("Неизвестный приоритет", show_alert=True)
        return

    await state.update_data(priority=priority.value)
    user = await repo.get_user(callback.from_user.id)
    default_place = user.place if user else None

    await state.set_state(New.place)
    if callback.message is not None:
        await callback.message.answer(
            "Укажите место заявки.\n" \
            "Выберите предыдущее место или напишите новое сообщением.\n" \
            "Пример: '1 этаж студия'",
            reply_markup=place_kb(default_place),
        )
    await callback.answer()


@router.callback_query(New.place, F.data == "u:place:default")
async def on_place_default(callback: CallbackQuery, state: FSMContext) -> None:
    user = await repo.get_user(callback.from_user.id)
    place = user.place if user and user.place else None
    if not place:
        await callback.answer("Укажите место текстом", show_alert=True)
        return
    if callback.message is not None:
        await _ask_confirm(callback.message, state, place)
    await callback.answer()


@router.message(New.place, F.text)
async def on_place(message: Message, state: FSMContext) -> None:
    if message.text is None:
        return
    place = " ".join(message.text.split())[:255]
    if len(place) < 2:
        await message.answer("Слишком коротко: минимум 2 символа. Укажите место ещё раз:")
        return
    await _ask_confirm(message, state, place)


@router.message(New.place)
async def on_place_invalid(message: Message) -> None:
    await message.answer("Пришлите место текстом.")


async def _ask_confirm(message: Message, state: FSMContext, place: str) -> None:
    data = await state.get_data()
    await state.update_data(place=place)
    await state.set_state(New.confirm)
    await message.answer(
        preview_text(
            description=data.get("description"),
            priority=Priority(data["priority"]),
            place=place,
            files=len(data.get("files") or []),
        ),
        reply_markup=confirm_kb(),
    )


@router.callback_query(New.confirm, F.data == "u:send")
async def on_send(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if not data.get("priority") or not data.get("place"):
        await state.clear()
        await callback.answer("Сессия истекла, начните заново", show_alert=True)
        return

    user = await repo.get_or_create_user(
        callback.from_user.id, is_admin=get_settings().is_admin(callback.from_user.id)
    )

    # Снимаем состояние заранее: повторный клик не создаст дубль.
    await state.clear()
    await callback.answer("Создаю заявку…")

    tg_user = callback.from_user
    files = data.get("files") or []

    try:
        ticket = await repo.create_ticket(
            user_id=user.id,
            author_name=tg_user.full_name,
            author_username=tg_user.username,
            description=data.get("description"),
            priority=Priority(data["priority"]),
            place=data["place"],
        )
        await repo.add_attachments(ticket.id, files)
        # Место запоминаем из каждой новой заявки: в следующий раз кнопка
        # «🏢 место из профиля» предложит последнее использованное.
        if ticket.place:
            await repo.set_user_place(tg_user.id, ticket.place)
    except Exception:
        logger.exception("Не удалось создать заявку для user_id=%s", tg_user.id)
        await callback.bot.send_message(
            tg_user.id, "Не получилось создать заявку. Попробуйте ещё раз."
        )
        return

    board_ok = True
    try:
        await publish_ticket(bot, ticket.id)
    except TelegramAPIError:
        board_ok = False
        logger.exception("Не удалось опубликовать заявку #%s на доске", ticket.number)

    await log_action(
        bot,
        "ticket_created",
        actor_tg_id=tg_user.id,
        ticket_id=ticket.id,
        payload={
            "number": ticket.number,
            "priority": ticket.priority.value,
            "place": ticket.place,
            "files": len(files),
            "board": board_ok,
        },
    )

    text = f"✅ Заявка <b>#{ticket.number:04d}</b> создана."
    if not board_ok:
        text += "\n\n⚠️ На доску её отправить не удалось — администратор увидит её в списке."
    text += "\n\nСтатус можно отслеживать в «Мои заявки»."

    if callback.message is not None:
        try:
            await callback.message.edit_text(text, reply_markup=after_create_kb())
            return
        except TelegramAPIError:
            logger.warning("Не удалось отредактировать предпросмотр заявки #%s", ticket.number)
    await callback.bot.send_message(tg_user.id, text, reply_markup=after_create_kb())


@router.message(New.priority)
async def priority_hint(message: Message) -> None:
    await message.answer("Выберите приоритет кнопкой ниже или нажмите «❌ Отмена».")


@router.message(New.confirm)
async def confirm_hint(message: Message) -> None:
    await message.answer("Нажмите «✅ Отправить» или «❌ Отмена».")


@router.callback_query(F.data == "u:send")
async def send_stale(callback: CallbackQuery) -> None:
    # Состояние уже сброшено: например, повторный клик по «Отправить».
    await callback.answer("Сессия истекла, начните заново", show_alert=True)


@router.callback_query(F.data.startswith("prio:"))
async def priority_stale(callback: CallbackQuery) -> None:
    await callback.answer("Сессия истекла, начните заново", show_alert=True)


@router.callback_query(F.data == "u:place:default")
async def place_stale(callback: CallbackQuery) -> None:
    await callback.answer("Сессия истекла, начните заново", show_alert=True)


@router.message(StateFilter(None), F.chat.type == "private")
async def quick_ticket(
    message: Message, state: FSMContext, album: list[Message] | None = None
) -> None:
    """Заявка сразу сообщением — без нажатия «📝 Создать заявку».

    Сообщение вне какого-либо FSM-состояния считаем описанием: сразу переходим
    к выбору приоритета. Так ничего не теряется, если человек пишет боту как в чат.
    """
    user = message.from_user
    if user is None:
        return

    sources = album or [message]
    files = collect_files(sources)
    description = extract_text(sources)

    if description and description.startswith("/") and not files:
        await message.answer("Неизвестная команда. /start — главное меню.")
        return

    # Админам заявки не создаём: у них своя панель по /start.
    if get_settings().is_admin(user.id):
        return

    if not description and not files:
        await message.answer(
            "Не понял сообщение. Нажмите «📝 Создать заявку» "
            "или пришлите текст, фото или видео."
        )
        return

    await state.update_data(description=description, files=files)
    await state.set_state(New.priority)
    await message.answer(
        "📝 Описание принято. Выберите приоритет заявки:",
        reply_markup=priority_kb(),
    )
