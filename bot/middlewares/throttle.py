from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class ThrottleMiddleware(BaseMiddleware):
    """Антифлуд: не чаще одного апдейта в ``rate`` секунд на пользователя."""

    def __init__(self, rate: float = 0.7, max_users: int = 10_000) -> None:
        self.rate = rate
        self.max_users = max_users
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self.rate <= 0:
            return await handler(event, data)

        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        now = monotonic()
        last = self._last_seen.get(user.id, 0.0)
        if now - last < self.rate:
            if isinstance(event, CallbackQuery):
                await event.answer("Слишком часто, подождите секунду")
            return None

        self._last_seen[user.id] = now
        if len(self._last_seen) > self.max_users:
            cutoff = now - 300
            self._last_seen = {uid: ts for uid, ts in self._last_seen.items() if ts > cutoff}

        return await handler(event, data)
