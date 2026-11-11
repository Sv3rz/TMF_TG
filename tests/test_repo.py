from __future__ import annotations

from bot.db import repo
from bot.db.models import Priority, TicketStatus


async def _user(tg_id: int = 1001):
    user = await repo.get_or_create_user(tg_id)
    await repo.set_user_place(tg_id, "Офис 3")
    return user


async def _ticket(user, **kwargs):
    params = {
        "user_id": user.id,
        "author_name": "Иван",
        "author_username": "ivan",
        "description": "Не включается монитор",
        "priority": Priority.MEDIUM,
        "place": "Офис 3, каб. 214",
    }
    params.update(kwargs)
    return await repo.create_ticket(**params)


async def test_numbering_snapshot_and_defaults():
    user = await _user()
    first = await _ticket(user)
    second = await _ticket(user, description=None)

    assert (first.number, second.number) == (1, 2)
    assert first.status is TicketStatus.WAITING
    assert first.author_name == "Иван" and first.author_username == "ivan"
    assert second.description is None


async def test_user_list_hides_final_statuses():
    user = await _user()
    waiting = await _ticket(user)
    closed = await _ticket(user)
    cancelled = await _ticket(user)
    await repo.set_status(closed.id, TicketStatus.CLOSED)
    await repo.set_status(cancelled.id, TicketStatus.CANCELLED)

    page = await repo.list_user_active(1001)
    assert page.total == 1 and page.items[0].id == waiting.id

    all_page = await repo.list_by_tab("all")
    assert all_page.total == 3


async def test_pagination():
    user = await _user()
    for index in range(3):
        await _ticket(user, description=f"T{index}")

    first = await repo.list_user_active(1001, page=1, per_page=2)
    second = await repo.list_user_active(1001, page=2, per_page=2)

    assert first.total == 3 and first.pages == 2 and len(first.items) == 2
    assert len(second.items) == 1


async def test_attachments_and_replies_by_kind():
    user = await _user()
    ticket = await _ticket(user)

    await repo.add_attachment(ticket.id, file_id="photo_1", file_type="photo", kind="ticket")
    await repo.add_attachment(ticket.id, file_id="video_1", file_type="video", kind="ticket")
    await repo.add_attachment(ticket.id, file_id="reply_1", file_type="photo", kind="admin_reply")
    await repo.add_admin_reply(ticket.id, admin_tg_id=111, text="Смотрю")

    assert len(await repo.list_attachments(ticket.id, kind="ticket")) == 2
    assert len(await repo.list_attachments(ticket.id, kind="admin_reply")) == 1
    replies = await repo.list_admin_replies(ticket.id)
    assert len(replies) == 1 and replies[0].text == "Смотрю"


async def test_last_actor_from_logs():
    user = await _user()
    ticket = await _ticket(user)

    assert await repo.get_last_actor(ticket.id, ("ticket_taken",)) is None

    await repo.add_log(
        action="ticket_taken",
        actor_tg_id=111,
        ticket_id=ticket.id,
        payload={"admin_name": "Пётр"},
    )
    actor = await repo.get_last_actor(ticket.id, ("ticket_taken", "ticket_closed"))
    assert actor is not None
    assert actor.tg_id == 111
    assert actor.name == "Пётр"
