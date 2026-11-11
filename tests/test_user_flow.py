from __future__ import annotations

import asyncio

from bot.db import repo
from bot.db.models import Priority, TicketStatus
from helpers import cb_update, kb_of, msg_update

USER = 1001
TICKETS_CHAT = -1001234567890


def _ctx(app, tg_id: int = USER):
    return app.dp.fsm.get_context(bot=app.bot, chat_id=tg_id, user_id=tg_id)


async def _onboard(app, tg_id: int = USER, place: str = "Офис 3, каб. 214") -> None:
    await app.dp.feed_raw_update(app.bot, msg_update(tg_id, "/start"))


async def test_start_shows_menu_without_onboarding(app):
    await app.dp.feed_raw_update(app.bot, msg_update(USER, "/start"))

    assert await _ctx(app).get_state() is None
    assert await repo.get_user(USER) is not None
    assert "u:new" in kb_of(app.session.sends(USER)[-1])


async def test_create_ticket_flow(app):
    await _onboard(app)

    await app.dp.feed_raw_update(app.bot, cb_update(USER, "u:new"))
    assert await _ctx(app).get_state() == "New:description"

    await app.dp.feed_raw_update(app.bot, msg_update(USER, "Не включается монитор"))
    assert await _ctx(app).get_state() == "New:priority"

    await app.dp.feed_raw_update(app.bot, cb_update(USER, "prio:high"))
    assert await _ctx(app).get_state() == "New:place"

    await app.dp.feed_raw_update(app.bot, msg_update(USER, "Офис 3, каб. 214"))
    assert await _ctx(app).get_state() == "New:confirm"

    await app.dp.feed_raw_update(app.bot, cb_update(USER, "u:send"))
    assert await _ctx(app).get_state() is None

    ticket = await repo.get_ticket(1)
    assert ticket is not None
    assert ticket.number == 1 and ticket.priority is Priority.HIGH
    assert ticket.place == "Офис 3, каб. 214"
    assert ticket.tg_message_id is not None

    # Место из первой заявки сохранилось в профиле.
    assert (await repo.get_user(USER)).place == "Офис 3, каб. 214"

    board = [m for m in app.session.sends() if m.chat_id == TICKETS_CHAT]
    assert board and "#0001" in board[0].text


async def test_place_updates_from_latest_ticket(app):
    await _onboard(app)

    for place in ("Офис 1", "Офис 2"):
        await app.dp.feed_raw_update(app.bot, cb_update(USER, "u:new"))
        await app.dp.feed_raw_update(app.bot, msg_update(USER, "Проблема"))
        await app.dp.feed_raw_update(app.bot, cb_update(USER, "prio:low"))
        await app.dp.feed_raw_update(app.bot, msg_update(USER, place))
        await app.dp.feed_raw_update(app.bot, cb_update(USER, "u:send"))

        assert (await repo.get_user(USER)).place == place


async def test_description_album_collects_files(app):
    await _onboard(app)
    await app.dp.feed_raw_update(app.bot, cb_update(USER, "u:new"))

    first = msg_update(USER, caption="Монитор", photo=("a", "b"), media_group_id="g1")
    second = msg_update(USER, photo=("c",), media_group_id="g1")
    await asyncio.gather(
        app.dp.feed_raw_update(app.bot, first),
        app.dp.feed_raw_update(app.bot, second),
    )

    data = await _ctx(app).get_data()
    assert data["description"] == "Монитор"
    assert len(data["files"]) == 2


async def test_user_cancels_waiting_ticket(app):
    user = await repo.get_or_create_user(USER)
    await repo.set_user_place(USER, "Офис 3")
    ticket = await repo.create_ticket(
        user_id=user.id,
        author_name="Иван",
        author_username="ivan",
        description="Монитор",
        priority=Priority.MEDIUM,
        place="Офис 3",
    )
    await repo.set_tg_message(ticket.id, 900)

    await app.dp.feed_raw_update(app.bot, cb_update(USER, "u:list:1"))
    assert f"t:{ticket.id}:card" in kb_of(app.session.edits(USER)[-1])

    await app.dp.feed_raw_update(app.bot, cb_update(USER, f"t:{ticket.id}:card"))
    assert f"t:{ticket.id}:cancel" in kb_of(app.session.edits(USER)[-1])

    await app.dp.feed_raw_update(app.bot, cb_update(USER, f"t:{ticket.id}:cancel"))

    assert (await repo.get_ticket(ticket.id)).status is TicketStatus.CANCELLED
    board_edit = app.session.edits(TICKETS_CHAT)[-1]
    assert board_edit.reply_markup.inline_keyboard == []
    assert [m for m in app.session.sends(TICKETS_CHAT) if "отменена" in (m.text or "")]


async def test_foreign_ticket_is_not_cancelled(app):
    owner = await repo.get_or_create_user(USER)
    await repo.get_or_create_user(1002)
    ticket = await repo.create_ticket(
        user_id=owner.id,
        author_name="Иван",
        author_username="ivan",
        description="Монитор",
        priority=Priority.MEDIUM,
        place="Офис 3",
    )
    await repo.set_tg_message(ticket.id, 901)

    await app.dp.feed_raw_update(app.bot, cb_update(1002, f"t:{ticket.id}:cancel"))

    assert (await repo.get_ticket(ticket.id)).status is TicketStatus.WAITING
