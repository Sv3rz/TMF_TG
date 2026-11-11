"""Кнопки на сообщении доски в TICKETS_CHAT_ID."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Ticket, TicketStatus


def board_kb(ticket: Ticket) -> InlineKeyboardMarkup | None:
    """None — сообщение финальное, кнопки убираются."""
    if ticket.status in (TicketStatus.CLOSED, TicketStatus.CANCELLED):
        return None

    kb = InlineKeyboardBuilder()
    if ticket.status is TicketStatus.WAITING:
        kb.button(text="▶️ В работу", callback_data=f"b:{ticket.id}:take")
    kb.button(text="✅ Закрыть", callback_data=f"b:{ticket.id}:close")
    kb.adjust(2)
    return kb.as_markup()
