"""Логирование: таблица logs + плоский поток в LOG_CHAT_ID."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.config import get_settings
from bot.db import repo

logger = logging.getLogger(__name__)


async def log_action(
    bot: Bot,
    action: str,
    *,
    actor_tg_id: int | None = None,
    ticket_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Пишет событие в БД и дублирует в служебный чат (если задан)."""
    await repo.add_log(
        action=action, actor_tg_id=actor_tg_id, ticket_id=ticket_id, payload=payload
    )

    settings = get_settings()
    if not settings.log_chat:
        return

    parts = [f"<b>{action}</b>"]
    if ticket_id is not None:
        parts.append(f"#{ticket_id:04d}")
    if actor_tg_id is not None:
        parts.append(f"actor <code>{actor_tg_id}</code>")
    if payload:
        parts.append(" ".join(f"{k}={v}" for k, v in payload.items()))
    text = " · ".join(parts)

    with suppress(TelegramAPIError):
        await bot.send_message(
            settings.log_chat,
            text[:4000],
            message_thread_id=settings.log_thread_id,
        )
