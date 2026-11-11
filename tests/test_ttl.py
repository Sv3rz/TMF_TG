from __future__ import annotations

import asyncio

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, User

from bot.middlewares.ttl import StateTTLMiddleware

USER_ID = 1001
TTL_USER = User(id=USER_ID, is_bot=False, first_name="Иван")
TTL_CHAT = Chat(id=USER_ID, type="private")


async def _handler(event, data):
    return "handled"


def _context() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=42, chat_id=USER_ID, user_id=USER_ID)
    return FSMContext(storage=storage, key=key)


def _data(context: FSMContext) -> dict:
    return {
        "event_from_user": TTL_USER,
        "event_chat": TTL_CHAT,
        "state": context,
    }


async def test_state_expires_after_ttl():
    middleware = StateTTLMiddleware(ttl=0.2)
    context = _context()
    await context.set_state("Onb:place")

    await middleware(_handler, object(), _data(context))
    await asyncio.sleep(0.3)
    await middleware(_handler, object(), _data(context))

    assert await context.get_state() is None


async def test_state_survives_within_ttl():
    middleware = StateTTLMiddleware(ttl=30)
    context = _context()
    await context.set_state("Onb:place")

    await middleware(_handler, object(), _data(context))
    await middleware(_handler, object(), _data(context))

    assert await context.get_state() == "Onb:place"


async def test_zero_ttl_disables_expiry():
    middleware = StateTTLMiddleware(ttl=0)
    context = _context()
    await context.set_state("Onb:place")

    await middleware(_handler, object(), _data(context))
    await asyncio.sleep(0.05)
    await middleware(_handler, object(), _data(context))

    assert await context.get_state() == "Onb:place"
