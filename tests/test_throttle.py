from __future__ import annotations

from datetime import datetime, timezone

from aiogram.types import Chat, Message, User

from bot.middlewares.throttle import ThrottleMiddleware

USER_ID = 7


def _user() -> User:
    return User(id=USER_ID, is_bot=False, first_name="Иван")


def _message(media_group_id: str | None = None) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=USER_ID, type="private"),
        from_user=_user(),
        media_group_id=media_group_id,
    )


async def test_album_parts_bypass_throttle():
    middleware = ThrottleMiddleware(rate=10)
    calls: list[object] = []

    async def handler(event, data):
        calls.append(event)

    data = {"event_from_user": _user()}
    message = _message("album-1")

    await middleware(handler, message, data)
    await middleware(handler, message, data)

    assert len(calls) == 2


async def test_plain_messages_are_throttled():
    middleware = ThrottleMiddleware(rate=10)
    calls: list[object] = []

    async def handler(event, data):
        calls.append(event)

    data = {"event_from_user": _user()}
    message = _message()

    await middleware(handler, message, data)
    await middleware(handler, message, data)

    assert len(calls) == 1
