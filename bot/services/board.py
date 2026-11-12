"""Форматирование текстов заявок: карточки, строки списков, сообщение доски."""

from __future__ import annotations

import enum
import html
import logging
from contextlib import suppress
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

from bot.config import get_settings
from bot.db import repo
from bot.db.models import (
    ACTIVE_STATUSES,
    AdminReply,
    Attachment,
    Priority,
    Ticket,
    TicketStatus,
)
from bot.keyboards.board import board_kb
from bot.services.log import log_action

logger = logging.getLogger(__name__)

PRIORITY_EMOJI = {
    Priority.LOW: "🟢",
    Priority.MEDIUM: "🟡",
    Priority.HIGH: "🔴",
}
PRIORITY_LABELS = {
    Priority.LOW: "Низкий",
    Priority.MEDIUM: "Средний",
    Priority.HIGH: "Высокий",
}
STATUS_EMOJI = {
    TicketStatus.WAITING: "🟠",
    TicketStatus.IN_PROGRESS: "🔧",
    TicketStatus.CLOSED: "✅",
    TicketStatus.CANCELLED: "❌",
}
STATUS_LABELS = {
    TicketStatus.WAITING: "Ожидает",
    TicketStatus.IN_PROGRESS: "В работе",
    TicketStatus.CLOSED: "Закрыта",
    TicketStatus.CANCELLED: "Отменена",
}


def ticket_brief(ticket: Ticket) -> str:
    """Строка списка: «#0001 · 🟡 · Ожидает»."""
    return (
        f"#{ticket.number:04d} · {PRIORITY_EMOJI[ticket.priority]} · "
        f"{STATUS_LABELS[ticket.status]}"
    )


def ticket_header(ticket: Ticket) -> str:
    """Заголовок карточки: «#0001 · 🟡 Средний · 🟠 Ожидает»."""
    return (
        f"#{ticket.number:04d} · {PRIORITY_EMOJI[ticket.priority]} "
        f"{PRIORITY_LABELS[ticket.priority]} · "
        f"{STATUS_EMOJI[ticket.status]} {STATUS_LABELS[ticket.status]}"
    )


def author_link(ticket: Ticket) -> str:
    name = html.escape(ticket.author_name)
    username = f" (@{html.escape(ticket.author_username)})" if ticket.author_username else ""
    return f'<a href="tg://user?id={ticket.user.tg_id}">{name}</a>{username}'


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else "—"


def _ticket_files(attachments: list[Attachment]) -> list[Attachment]:
    return [a for a in attachments if a.kind == "ticket"]


def _description(description: str | None) -> str:
    return f"📝 «{html.escape(description)}»" if description else "📝 Без описания (только медиа)"


def _replies_block(replies: list[AdminReply]) -> str:
    if not replies:
        return "💬 Ответы админа: —"
    lines = [f"💬 Ответы админа ({len(replies)}):"]
    for reply in replies[-3:]:
        body = html.escape(reply.text) if reply.text else "медиа"
        lines.append(f"• {_fmt_dt(reply.created_at)}: {body}")
    return "\n".join(lines)


def board_text(ticket: Ticket, *, actor: repo.ActorInfo | None = None) -> str:
    """Сообщение на доске в TICKETS_CHAT_ID.

    ``actor`` — кто и когда последним менял статус (из таблицы logs).
    """
    files = _ticket_files(ticket.attachments)
    lines = [
        ticket_header(ticket),
        f"📍 {html.escape(ticket.place)}",
        f"👤 {author_link(ticket)}",
        _description(ticket.description),
    ]
    if files:
        lines.append(f"📎 Вложений: {len(files)}")
    if actor is not None and ticket.status in (TicketStatus.IN_PROGRESS, TicketStatus.CLOSED):
        name = html.escape(actor.name) if actor.name else "администратор"
        lines.append(
            f'🛠 Изменил: <a href="tg://user?id={actor.tg_id}">{name}</a>'
            f" · {_fmt_dt(actor.at)}"
        )
    lines.append(_replies_block(ticket.replies))
    return "\n".join(lines)


def user_card_text(ticket: Ticket) -> str:
    """Карточка заявки для автора."""
    files = _ticket_files(ticket.attachments)
    lines = [
        f"<b>Заявка #{ticket.number:04d}</b>",
        f"{PRIORITY_EMOJI[ticket.priority]} {PRIORITY_LABELS[ticket.priority]} · "
        f"{STATUS_EMOJI[ticket.status]} {STATUS_LABELS[ticket.status]}",
        f"📍 {html.escape(ticket.place)}",
        f"📅 {_fmt_dt(ticket.created_at)}",
        _description(ticket.description),
    ]
    if files:
        lines.append(f"📎 Файлов: {len(files)}")
    return "\n".join(lines)


def preview_text(
    *, description: str | None, priority: Priority, place: str, files: int
) -> str:
    """Предпросмотр перед отправкой заявки."""
    lines = [
        "<b>Проверьте заявку</b>",
        f"{PRIORITY_EMOJI[priority]} {PRIORITY_LABELS[priority]}",
        f"📍 {html.escape(place)}",
        _description(description),
    ]
    if files:
        lines.append(f"📎 Файлов: {files}")
    lines.append("\nВсё верно? Нажмите «✅ Отправить».")
    return "\n".join(lines)


async def refresh_board_message(bot: Bot, ticket_id: int, *, note: str | None = None) -> int | None:
    """Перерисовывает карточку на доске. Возвращает актуальный message_id.

    Если сообщение изменить нельзя (удалено, старое, «not modified») — отправляет
    новое и обновляет ``tg_message_id``. Пустая клавиатура снимает кнопки.
    """
    ticket = await repo.get_ticket(ticket_id)
    if ticket is None:
        return None

    actor = await repo.get_last_actor(ticket.id, ("ticket_taken", "ticket_closed"))
    text = board_text(ticket, actor=actor)
    if note:
        text = f"{text}\n\n{note}"

    keyboard = board_kb(ticket)
    markup = keyboard if keyboard is not None else InlineKeyboardMarkup(inline_keyboard=[])
    chat_id = get_settings().tickets_chat_id

    if ticket.tg_message_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=ticket.tg_message_id,
                text=text,
                reply_markup=markup,
            )
            return ticket.tg_message_id
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return ticket.tg_message_id
            logger.warning("Доска: не удалось изменить #%s: %s", ticket.number, exc)
        except TelegramAPIError:
            logger.warning("Доска: ошибка Telegram при обновлении #%s", ticket.number, exc_info=True)

    message = await bot.send_message(
        chat_id=chat_id, text=text, reply_markup=markup,
        message_thread_id=get_settings().tickets_thread_id,
    )
    await repo.set_tg_message(ticket.id, message.message_id)
    return message.message_id


async def publish_ticket(bot: Bot, ticket_id: int) -> int:
    """Отправляет карточку на доску и сохраняет tg_message_id.

    Ошибки Telegram пробрасываются: вызывающий код решает, что делать.
    """
    ticket = await repo.get_ticket(ticket_id)
    if ticket is None:
        raise ValueError(f"Заявка {ticket_id} не найдена")

    message = await bot.send_message(
        chat_id=get_settings().tickets_chat_id,
        text=board_text(ticket),
        reply_markup=board_kb(ticket),
        message_thread_id=get_settings().tickets_thread_id,
    )
    await repo.set_tg_message(ticket.id, message.message_id)
    return message.message_id


class ActionResult(str, enum.Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    WRONG_STATUS = "wrong_status"


async def take_ticket(
    bot: Bot, ticket_id: int, actor_id: int, actor_name: str | None = None
) -> tuple[ActionResult, Ticket | None]:
    """waiting -> in_progress. Обновляет доску и пишет лог."""
    ticket = await repo.get_ticket(ticket_id)
    if ticket is None:
        return ActionResult.NOT_FOUND, None
    if ticket.status is not TicketStatus.WAITING:
        return ActionResult.WRONG_STATUS, ticket

    await repo.set_status(ticket.id, TicketStatus.IN_PROGRESS)
    updated = await repo.get_ticket(ticket.id)
    if updated is None:
        return ActionResult.NOT_FOUND, None

    payload: dict[str, object] = {"number": updated.number}
    if actor_name:
        payload["admin_name"] = actor_name

    await log_action(
        bot,
        "ticket_taken",
        actor_tg_id=actor_id,
        ticket_id=updated.id,
        payload=payload,
    )

    with suppress(TelegramAPIError):
        await refresh_board_message(bot, updated.id)

    return ActionResult.OK, updated


async def close_ticket(
    bot: Bot, ticket_id: int, actor_id: int, actor_name: str | None = None
) -> tuple[ActionResult, Ticket | None]:
    """waiting|in_progress -> closed. Доска, уведомление автору, лог."""
    ticket = await repo.get_ticket(ticket_id)
    if ticket is None:
        return ActionResult.NOT_FOUND, None
    if ticket.status not in ACTIVE_STATUSES:
        return ActionResult.WRONG_STATUS, ticket

    await repo.set_status(ticket.id, TicketStatus.CLOSED)
    updated = await repo.get_ticket(ticket.id)
    if updated is None:
        return ActionResult.NOT_FOUND, None

    payload: dict[str, object] = {"number": updated.number}
    if actor_name:
        payload["admin_name"] = actor_name

    await log_action(
        bot,
        "ticket_closed",
        actor_tg_id=actor_id,
        ticket_id=updated.id,
        payload=payload,
    )

    with suppress(TelegramAPIError):
        await refresh_board_message(bot, updated.id)

    with suppress(TelegramAPIError):
        await bot.send_message(
            updated.user.tg_id, f"✅ Заявка <b>#{updated.number:04d}</b> закрыта."
        )

    return ActionResult.OK, updated


def admin_card_caption(ticket: Ticket, *, limit: int = 1000) -> str:
    """Подпись к медиа: карточка, обрезанная под лимит caption (1024)."""
    text = admin_card_text(ticket)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def admin_card_text(ticket: Ticket) -> str:
    """Карточка заявки для администратора."""
    files = _ticket_files(ticket.attachments)
    lines = [
        ticket_header(ticket),
        f"📍 {html.escape(ticket.place)}",
        f"👤 {author_link(ticket)} · <code>{ticket.user.tg_id}</code>",
        _description(ticket.description),
    ]
    if files:
        lines.append(f"📎 Вложений: {len(files)}")
    lines.append(_replies_block(ticket.replies))
    return "\n".join(lines)
