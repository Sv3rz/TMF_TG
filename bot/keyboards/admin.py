"""Клавиатуры администратора."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Ticket, TicketStatus
from bot.services.board import ticket_brief

ACTIVE_STATUSES = (TicketStatus.WAITING, TicketStatus.IN_PROGRESS)


def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🆕 Ожидают", callback_data="a:list:waiting:1")
    kb.button(text="🔧 В работе", callback_data="a:list:in_progress:1")
    kb.button(text="📜 Все", callback_data="a:list:all:1")
    kb.button(text="⬅️ Выход", callback_data="a:exit")
    kb.adjust(3, 1)
    return kb.as_markup()


def admin_list_kb(
    tab: str, items: Sequence[Ticket], page: int, pages: int
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ticket in items:
        kb.button(text=ticket_brief(ticket), callback_data=f"t:{ticket.id}:card")

    nav = 0
    if page > 1:
        kb.button(text="⬅️", callback_data=f"a:list:{tab}:{page - 1}")
        nav += 1
    if page < pages:
        kb.button(text="➡️", callback_data=f"a:list:{tab}:{page + 1}")
        nav += 1
    kb.button(text="⬅️ В меню", callback_data="a:menu")
    nav += 1

    kb.adjust(*([1] * len(items)), nav)
    return kb.as_markup()


def admin_card_kb(ticket: Ticket, tab: str, page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    sizes: list[int] = []
    active = ticket.status in ACTIVE_STATUSES

    if ticket.status is TicketStatus.WAITING:
        kb.button(text="▶️ В работу", callback_data=f"act:{ticket.id}:take")
        sizes.append(1)
    if active:
        kb.button(text="💬 Ответить", callback_data=f"act:{ticket.id}:reply")
        kb.button(text="✅ Закрыть", callback_data=f"act:{ticket.id}:close")
        sizes.append(2)
    if any(a.kind == "ticket" for a in ticket.attachments):
        kb.button(text="📎 Вложения", callback_data=f"act:{ticket.id}:files")
        sizes.append(1)

    kb.button(text="⬅️ К списку", callback_data=f"a:list:{tab}:{page}")
    sizes.append(1)

    kb.adjust(*sizes)
    return kb.as_markup()


def admin_cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✖️ Отмена", callback_data="a:cancel")
    return kb.as_markup()
