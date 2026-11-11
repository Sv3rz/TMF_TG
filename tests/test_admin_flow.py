from __future__ import annotations

from bot.db import repo
from bot.db.models import Priority, TicketStatus
from helpers import cb_update, kb_of, last_answer, msg_update

ADMIN = 111
USER = 1001


async def _ticket(description: str = "Принтер"):
    user = await repo.get_or_create_user(USER)
    await repo.set_user_place(USER, "Офис 3")
    ticket = await repo.create_ticket(
        user_id=user.id,
        author_name="Иван",
        author_username="ivan",
        description=description,
        priority=Priority.MEDIUM,
        place="Офис 3",
    )
    await repo.set_tg_message(ticket.id, 900)
    return ticket


def _ctx(app, tg_id: int = ADMIN):
    return app.dp.fsm.get_context(bot=app.bot, chat_id=tg_id, user_id=tg_id)


async def test_admin_menu_and_status_actions(app):
    ticket = await _ticket()

    await app.dp.feed_raw_update(app.bot, msg_update(ADMIN, "/start"))
    menu = app.session.sends(ADMIN)[-1]
    assert "a:list:waiting:1" in kb_of(menu)

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, "a:list:waiting:1"))
    assert f"t:{ticket.id}:card" in kb_of(app.session.edits(ADMIN)[-1])

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"t:{ticket.id}:card"))
    card = app.session.edits(ADMIN)[-1]
    assert "tg://user?id=1001" in card.text
    assert f"act:{ticket.id}:take" in kb_of(card)

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"act:{ticket.id}:take"))
    assert (await repo.get_ticket(ticket.id)).status is TicketStatus.IN_PROGRESS

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"act:{ticket.id}:close"))
    assert (await repo.get_ticket(ticket.id)).status is TicketStatus.CLOSED
    assert [m for m in app.session.sends(USER) if "закрыта" in (m.text or "")]


async def test_admin_reply_text_is_delivered(app):
    ticket = await _ticket()

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"act:{ticket.id}:reply"))
    assert await _ctx(app).get_state() == "AdminReply:content"

    await app.dp.feed_raw_update(app.bot, msg_update(ADMIN, "Проверьте кабель"))
    assert await _ctx(app).get_state() is None

    copies = app.session.method("CopyMessage")
    assert copies and copies[-1].chat_id == USER
    replies = await repo.list_admin_replies(ticket.id)
    assert len(replies) == 1 and replies[0].text == "Проверьте кабель"


async def test_reply_to_closed_ticket_rejected(app):
    ticket = await _ticket()
    await repo.set_status(ticket.id, TicketStatus.CLOSED)

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, f"act:{ticket.id}:reply"))
    assert await _ctx(app).get_state() is None
    assert last_answer(app.session) == "Ответить можно только по активной заявке"


async def test_non_admin_cannot_open_admin_lists(app):
    await app.dp.feed_raw_update(app.bot, cb_update(999, "a:list:waiting:1"))
    assert last_answer(app.session) == "Нет доступа"
