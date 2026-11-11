"""Клавиатуры пользователя."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Ticket, TicketStatus
from bot.services.board import ticket_brief


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Создать заявку", callback_data="u:new")
    kb.button(text="📋 Мои заявки", callback_data="u:list:1")
    kb.button(text="ℹ️ Помощь", callback_data="u:help")
    kb.adjust(1)
    return kb.as_markup()


def cancel_row() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data="u:cancel")
    return kb.as_markup()


def priority_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Низкий", callback_data="prio:low")
    kb.button(text="🟡 Средний", callback_data="prio:medium")
    kb.button(text="🔴 Высокий", callback_data="prio:high")
    kb.button(text="❌ Отмена", callback_data="u:cancel")
    kb.adjust(3, 1)
    return kb.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Отправить", callback_data="u:send")
    kb.button(text="❌ Отмена", callback_data="u:cancel")
    kb.adjust(2)
    return kb.as_markup()


def place_kb(default_place: str | None) -> InlineKeyboardMarkup:
    """Место заявки: можно оставить как в профиле."""
    kb = InlineKeyboardBuilder()
    if default_place:
        label = default_place if len(default_place) <= 40 else default_place[:39] + "…"
        kb.button(text=f"🏢 {label}", callback_data="u:place:default")
    kb.button(text="❌ Отмена", callback_data="u:cancel")
    kb.adjust(1)
    return kb.as_markup()


def after_create_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Мои заявки", callback_data="u:list:1")
    return kb.as_markup()


def cancelled_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Мои заявки", callback_data="u:list:1")
    kb.button(text="⬅️ В меню", callback_data="u:menu")
    kb.adjust(1)
    return kb.as_markup()


def user_list_kb(items: Sequence[Ticket], page: int, pages: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ticket in items:
        kb.button(text=ticket_brief(ticket), callback_data=f"t:{ticket.id}:card")

    nav = 0
    if page > 1:
        kb.button(text="⬅️", callback_data=f"u:list:{page - 1}")
        nav += 1
    if page < pages:
        kb.button(text="➡️", callback_data=f"u:list:{page + 1}")
        nav += 1
    kb.button(text="⬅️ В меню", callback_data="u:menu")
    nav += 1

    kb.adjust(*([1] * len(items)), nav)
    return kb.as_markup()


def ticket_card_kb(ticket: Ticket, page: int = 1) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if ticket.status is TicketStatus.WAITING:
        kb.button(text="❌ Отменить", callback_data=f"t:{ticket.id}:cancel")
    kb.button(text="⬅️ К списку", callback_data=f"t:{ticket.id}:back")
    kb.adjust(1)
    return kb.as_markup()
