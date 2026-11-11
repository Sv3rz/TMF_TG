from __future__ import annotations

from bot.db import repo
from bot.db.models import Priority, TicketStatus
from bot.services.board import (
    admin_card_text,
    board_text,
    preview_text,
    ticket_brief,
    ticket_header,
    user_card_text,
)


async def _ticket(description: str = "Не включается монитор"):
    user = await repo.get_or_create_user(1001)
    await repo.set_user_place(1001, "Офис 3, каб. 214")
    return await repo.create_ticket(
        user_id=user.id,
        author_name="Иван",
        author_username="ivan",
        description=description,
        priority=Priority.HIGH,
        place="Офис 3, каб. 214",
    )


async def test_ticket_line_and_header():
    ticket = await _ticket()

    assert ticket_brief(ticket) == "#0001 · 🔴 · Ожидает"
    assert ticket_header(ticket) == "#0001 · 🔴 Высокий · 🟠 Ожидает"


async def test_board_text_links_author_and_escapes_description():
    ticket = await _ticket("<b>не HTML</b>")
    text = board_text(ticket)

    assert 'href="tg://user?id=1001"' in text
    assert "&lt;b&gt;не HTML&lt;/b&gt;" in text
    assert "<b>не HTML</b>" not in text


async def test_board_text_actor_line_only_for_changed_status():
    ticket = await _ticket()
    actor = repo.ActorInfo(111, ticket.created_at, "Пётр")

    assert "Изменил" not in board_text(ticket, actor=actor)

    await repo.set_status(ticket.id, TicketStatus.IN_PROGRESS)
    updated = await repo.get_ticket(ticket.id)
    changed_actor = repo.ActorInfo(111, updated.created_at, "Пётр")
    text = board_text(updated, actor=changed_actor)

    assert "Изменил" in text
    assert ">Пётр</a>" in text
    assert 'href="tg://user?id=111"' in text


async def test_board_text_actor_without_name_falls_back():
    ticket = await _ticket()
    await repo.set_status(ticket.id, TicketStatus.IN_PROGRESS)
    updated = await repo.get_ticket(ticket.id)

    text = board_text(updated, actor=repo.ActorInfo(111, updated.created_at))

    assert "администратор" in text


async def test_user_and_admin_cards():
    ticket = await _ticket()
    await repo.add_attachment(ticket.id, file_id="p", file_type="photo", kind="ticket")
    fresh = await repo.get_ticket(ticket.id)

    user_text = user_card_text(fresh)
    admin_text = admin_card_text(fresh)

    assert "Заявка #0001" in user_text and "Файлов: 1" in user_text
    assert "tg://user?id=1001" in admin_text
    assert "Ответы админа: —" in admin_text


async def test_preview_text():
    text = preview_text(
        description="Не включается монитор",
        priority=Priority.MEDIUM,
        place="Офис 3",
        files=2,
    )
    assert "Проверьте заявку" in text
    assert "🟡 Средний" in text and "Файлов: 2" in text
