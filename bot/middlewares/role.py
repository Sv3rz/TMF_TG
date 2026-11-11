from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import get_settings

logger = logging.getLogger(__name__)


class AdminMiddleware(BaseMiddleware):
    """Пускает в админ-роутер только ID из ADMIN_IDS.

    Пользователю админка невидима: сообщения игнорируются, на callback — короткий отказ.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or not get_settings().is_admin(user.id):
            if isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=False)
            return None
        return await handler(event, data)
