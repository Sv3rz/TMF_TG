"""Один форум-чат с топиками: «Заявки» для доски и «Log» для логов."""

from __future__ import annotations

from bot.db import repo
from bot.db.models import Priority
from bot.services.board import publish_ticket
from bot.services.log import log_action
from helpers import cb_update

TICKETS_CHAT = -1001234567890
TOPIC_TICKETS = 10
TOPIC_LOG = 20
ADMIN = 111
USER = 1001


async def _ticket(message_id: int | None = None):
    user = await repo.get_or_create_user(USER)
    await repo.set_user_place(USER, "Офис 3")
    ticket = await repo.create_ticket(
        user_id=user.id,
        author_name="Иван",
        author_username="ivan",
        description="Не включается монитор",
        priority=Priority.MEDIUM,
        place="Офис 3",
    )
    if message_id is not None:
        await repo.set_tg_message(ticket.id, message_id)
    return ticket


async def test_board_goes_to_tickets_topic(app):
    ticket = await _ticket()

    await publish_ticket(app.bot, ticket.id)

    topic_sends = [
        m
        for m in app.session.sends(TICKETS_CHAT)
        if getattr(m, "message_thread_id", None) == TOPIC_TICKETS
    ]
    assert topic_sends
    assert "#0001" in topic_sends[-1].text


async def test_logs_go_to_log_topic_of_same_chat(app):
    await log_action(app.bot, "ticket_created", actor_tg_id=USER, payload={"number": 1})

    log_sends = [
        m
        for m in app.session.sends(TICKETS_CHAT)
        if getattr(m, "message_thread_id", None) == TOPIC_LOG
    ]
    assert log_sends
    assert "ticket_created" in log_sends[-1].text


async def test_cancel_notice_goes_to_tickets_topic(app):
    ticket = await _ticket(message_id=900)

    await app.dp.feed_raw_update(app.bot, cb_update(USER, f"t:{ticket.id}:cancel"))

    notices = [m for m in app.session.sends(TICKETS_CHAT) if "отменена" in (m.text or "")]
    assert notices
    assert notices[-1].message_thread_id == TOPIC_TICKETS


async def test_fallback_resend_keeps_tickets_topic(app):
    ticket = await _ticket(message_id=901)
    app.session.edit_error = "not_found"

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"b:{ticket.id}:take"))
    app.session.edit_error = None

    fresh = await repo.get_ticket(ticket.id)
    assert fresh is not None
    board_sends = [
        m
        for m in app.session.sends(TICKETS_CHAT)
        if getattr(m, "message_thread_id", None) == TOPIC_TICKETS
    ]
    assert board_sends
    assert fresh.tg_message_id == app.session._msg_id
