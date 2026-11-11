from __future__ import annotations

from bot.db import repo
from bot.db.models import Priority, TicketStatus
from helpers import cb_update, kb_of

ADMIN = 111
USER = 1001
TICKETS_CHAT = -1001234567890


async def _ticket(message_id: int, description: str = "Сеть"):
    user = await repo.get_or_create_user(USER)
    await repo.set_user_place(USER, "Офис 3")
    ticket = await repo.create_ticket(
        user_id=user.id,
        author_name="Иван",
        author_username="ivan",
        description=description,
        priority=Priority.HIGH,
        place="Серверная",
    )
    await repo.set_tg_message(ticket.id, message_id)
    return ticket


async def test_board_take_and_close(app):
    ticket = await _ticket(901)

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"b:{ticket.id}:take"))
    assert (await repo.get_ticket(ticket.id)).status is TicketStatus.IN_PROGRESS

    board = app.session.edits(TICKETS_CHAT)[-1]
    assert board.message_id == 901
    assert "В работе" in board.text and "Изменил" in board.text
    assert ">Иван</a>" in board.text
    assert kb_of(board) == [f"b:{ticket.id}:close"]

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"b:{ticket.id}:close"))
    assert (await repo.get_ticket(ticket.id)).status is TicketStatus.CLOSED
    assert app.session.edits(TICKETS_CHAT)[-1].reply_markup.inline_keyboard == []


async def test_repeated_take_is_ignored(app):
    ticket = await _ticket(902)
    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"b:{ticket.id}:take"))

    edits_before = len(app.session.edits(TICKETS_CHAT))
    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"b:{ticket.id}:take"))

    assert len(app.session.edits(TICKETS_CHAT)) == edits_before
    assert (await repo.get_ticket(ticket.id)).status is TicketStatus.IN_PROGRESS


async def test_fallback_resends_when_message_is_broken(app):
    ticket = await _ticket(903)
    app.session.edit_error = "not_found"

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"b:{ticket.id}:take"))
    app.session.edit_error = None

    fresh = await repo.get_ticket(ticket.id)
    assert fresh.status is TicketStatus.IN_PROGRESS
    assert fresh.tg_message_id != 903
    assert fresh.tg_message_id == app.session._msg_id


async def test_not_modified_does_not_resend(app):
    ticket = await _ticket(904)
    board_sends_before = [
        m
        for m in app.session.sends(TICKETS_CHAT)
        if getattr(m, "message_thread_id", None) == 10
    ]
    app.session.edit_error = "not_modified"

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"b:{ticket.id}:take"))
    app.session.edit_error = None

    board_sends_after = [
        m
        for m in app.session.sends(TICKETS_CHAT)
        if getattr(m, "message_thread_id", None) == 10
    ]
    assert len(board_sends_after) == len(board_sends_before)
    assert (await repo.get_ticket(ticket.id)).tg_message_id == 904
