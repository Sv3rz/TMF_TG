"""Кнопки на сообщении доски в TICKETS_CHAT_ID: b:<id>:take / b:<id>:close."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from bot.db.models import TicketStatus
from bot.services.board import ActionResult, close_ticket, take_ticket

router = Router(name="board_callbacks")
logger = logging.getLogger(__name__)


def _parse(data: str | None) -> tuple[int, str] | None:
    if not data:
        return None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "b" or not parts[1].isdigit():
        return None
    return int(parts[1]), parts[2]


@router.callback_query(F.data.startswith("b:"))
async def board_action(callback: CallbackQuery, bot: Bot) -> None:
    parsed = _parse(callback.data)
    if parsed is None:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return

    ticket_id, action = parsed
    if action == "take":
        result, ticket = await take_ticket(
            bot, ticket_id, callback.from_user.id, callback.from_user.full_name
        )
        if result is ActionResult.OK:
            await callback.answer("Взято в работу")
        elif result is ActionResult.WRONG_STATUS and ticket is not None:
            message = (
                "Заявка уже в работе"
                if ticket.status is TicketStatus.IN_PROGRESS
                else "Заявка уже закрыта или отменена"
            )
            await callback.answer(message, show_alert=True)
        else:
            await callback.answer("Заявка не найдена", show_alert=True)
    elif action == "close":
        result, _ticket = await close_ticket(
            bot, ticket_id, callback.from_user.id, callback.from_user.full_name
        )
        if result is ActionResult.OK:
            await callback.answer("Заявка закрыта")
        elif result is ActionResult.WRONG_STATUS:
            await callback.answer("Заявка уже закрыта или отменена", show_alert=True)
        else:
            await callback.answer("Заявка не найдена", show_alert=True)
    else:
        await callback.answer()
