from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class AlbumMiddleware(BaseMiddleware):
    """Собирает медиагруппу в один список.

    Telegram присылает альбом несколькими сообщениями с общим media_group_id.
    Первое ждёт ``latency`` секунд, копит остальные и вызывает хендлер один раз
    со списком в аргументе ``album``. Описание берётся из caption первого сообщения.
    """

    def __init__(self, latency: float = 1.2) -> None:
        self.latency = latency
        self._albums: dict[str, list[Message]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        media_group_id = event.media_group_id
        if media_group_id is None:
            return await handler(event, data)

        if media_group_id in self._albums:
            self._albums[media_group_id].append(event)
            return None

        self._albums[media_group_id] = [event]
        await asyncio.sleep(self.latency)
        album = self._albums.pop(media_group_id, [event])
        data["album"] = album
        data["album_caption"] = next((m.caption for m in album if m.caption), None)
        return await handler(event, data)
