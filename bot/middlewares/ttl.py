from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject


class StateTTLMiddleware(BaseMiddleware):
    """Сбрасывает FSM-состояние после ``ttl`` секунд без активности.

    TTL считается от последнего апдейта пользователя: пока он отвечает,
    состояние живёт. Просроченное состояние очищается перед обработкой
    текущего апдейта, поэтому хендлеры с фильтром состояния уже не сработают.
    """

    def __init__(self, ttl: int, max_users: int = 10_000) -> None:
        self.ttl = ttl
        self.max_users = max_users
        self._last_seen: dict[tuple[int, int], float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        if user is None or chat is None or self.ttl <= 0:
            return await handler(event, data)

        key = (chat.id, user.id)
        now = monotonic()
        last_seen = self._last_seen.get(key)
        self._last_seen[key] = now

        if last_seen is not None and now - last_seen > self.ttl:
            state: FSMContext | None = data.get("state")
            if state is not None:
                await state.clear()

        if len(self._last_seen) > self.max_users:
            cutoff = now - self.ttl * 2
            self._last_seen = {k: v for k, v in self._last_seen.items() if v >= cutoff}

        return await handler(event, data)
