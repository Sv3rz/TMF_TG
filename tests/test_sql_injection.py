"""Проверка устойчивости к SQL-инъекциям.

Все запросы идут через SQLAlchemy с bind-параметрами, поэтому payload'ы должны
сохраняться как данные и не менять схему/количество строк.
"""

from __future__ import annotations

import sqlite3

from sqlalchemy import select
from sqlalchemy.dialects import sqlite

from bot.config import get_settings
from bot.db import repo
from bot.db.models import Priority, Ticket
from helpers import cb_update, last_answer, msg_update

USER = 1001
ADMIN = 111

PAYLOADS = [
    "'; DROP TABLE tickets;--",
    "' OR '1'='1",
    "1'; UPDATE tickets SET status='closed';--",
    '" OR 1=1 --',
    "\\'; DELETE FROM users;--",
    "%' OR 1=1 --",
    "'; ATTACH DATABASE '/tmp/evil.db' AS evil;--",
]


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(str(get_settings().db_path), timeout=10)


def _tables() -> set[str]:
    with _connect() as connection:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}


_COUNT_QUERIES = {
    "users": "SELECT count(*) FROM users",
    "tickets": "SELECT count(*) FROM tickets",
}


def _count(table: str) -> int:
    with _connect() as connection:
        return int(connection.execute(_COUNT_QUERIES[table]).fetchone()[0])


async def test_payloads_are_stored_as_data():
    user = await repo.get_or_create_user(USER)
    await repo.set_user_place(USER, PAYLOADS[0])

    ticket = await repo.create_ticket(
        user_id=user.id,
        author_name=PAYLOADS[1],
        author_username=PAYLOADS[2],
        description=PAYLOADS[3],
        priority=Priority.MEDIUM,
        place=PAYLOADS[0],
    )
    fresh = await repo.get_ticket(ticket.id)

    assert fresh is not None
    assert fresh.description == PAYLOADS[3]
    assert fresh.author_name == PAYLOADS[1]
    assert fresh.author_username == PAYLOADS[2]
    assert fresh.place == PAYLOADS[0]
    assert (await repo.get_user(USER)).place == PAYLOADS[0]

    assert {"users", "tickets", "attachments", "admin_replies", "logs"} <= _tables()
    assert _count("tickets") == 1
    assert _count("users") == 1


async def test_all_payloads_survive_crud_and_reads():
    user = await repo.get_or_create_user(USER)
    for index, payload in enumerate(PAYLOADS):
        await repo.create_ticket(
            user_id=user.id,
            author_name=f"Иван {index}",
            author_username="ivan",
            description=payload,
            priority=Priority.LOW,
            place=payload,
        )

    page = await repo.list_user_active(USER, page=1, per_page=50)

    assert page.total == len(PAYLOADS)
    assert sorted(ticket.description for ticket in page.items) == sorted(PAYLOADS)
    assert _count("tickets") == len(PAYLOADS)
    assert {"users", "tickets", "attachments", "admin_replies", "logs"} <= _tables()


async def test_payload_through_ticket_flow(app):
    payload = "Отчёт '); DROP TABLE users;--"

    await app.dp.feed_raw_update(app.bot, msg_update(USER, "/start"))
    await app.dp.feed_raw_update(app.bot, msg_update(USER, "Офис 3"))
    await app.dp.feed_raw_update(app.bot, cb_update(USER, "u:new"))
    await app.dp.feed_raw_update(app.bot, msg_update(USER, payload))
    await app.dp.feed_raw_update(app.bot, cb_update(USER, "prio:medium"))
    await app.dp.feed_raw_update(app.bot, msg_update(USER, "Офис 3"))
    await app.dp.feed_raw_update(app.bot, cb_update(USER, "u:send"))

    ticket = await repo.get_ticket(1)
    assert ticket is not None
    assert ticket.description == payload
    assert _count("tickets") == 1
    assert "users" in _tables()

    # Запись с кавычками не ломает последующие выборки.
    await app.dp.feed_raw_update(app.bot, cb_update(USER, "u:list:1"))
    assert "t:1:card" in str(app.session.edits(USER)[-1].reply_markup)


async def test_malicious_priority_is_rejected(app):
    await app.dp.feed_raw_update(app.bot, msg_update(USER, "/start"))
    await app.dp.feed_raw_update(app.bot, msg_update(USER, "Офис 3"))
    await app.dp.feed_raw_update(app.bot, cb_update(USER, "u:new"))
    await app.dp.feed_raw_update(app.bot, msg_update(USER, "Монитор"))

    await app.dp.feed_raw_update(app.bot, cb_update(USER, "prio:'; DROP TABLE users;--"))

    assert last_answer(app.session) == "Неизвестный приоритет"
    assert "users" in _tables()
    assert _count("users") == 1


async def test_callback_data_cannot_inject_sql(app):
    await repo.get_or_create_user(USER)

    await app.dp.feed_raw_update(app.bot, cb_update(USER, "t:1; DROP TABLE users:card"))
    assert last_answer(app.session) == "Некорректная кнопка"

    await app.dp.feed_raw_update(app.bot, cb_update(ADMIN, "a:list:'; DROP TABLE users:1"))
    assert last_answer(app.session) == "Некорректный раздел"

    await app.dp.feed_raw_update(app.bot, cb_update(USER, "u:list:1; DROP TABLE users"))

    assert {"users", "tickets", "attachments", "admin_replies", "logs"} <= _tables()
    assert _count("users") == 1


async def test_queries_are_parameterized_not_inlined():
    payload = "'; DROP TABLE tickets;--"
    statement = select(Ticket).where(Ticket.description == payload)
    compiled = statement.compile(dialect=sqlite.dialect())

    sql = str(compiled)
    assert "DROP TABLE" not in sql
    assert payload not in sql
    assert "= ?" in sql
    assert payload in compiled.construct_params().values()
