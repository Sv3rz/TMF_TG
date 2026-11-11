from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

_TMP_DIR = tempfile.mkdtemp(prefix="tgbot-tests-")

# Окружение должно быть задано до импорта bot.config.
os.environ["BOT_TOKEN"] = "42:TESTTOKEN"
os.environ["DB_PATH"] = str(Path(_TMP_DIR) / "test.sqlite3")
os.environ["TICKETS_CHAT_ID"] = "-1001234567890"
os.environ["TICKETS_THREAD_ID"] = "10"
os.environ["LOG_CHAT_ID"] = ""
os.environ["LOG_THREAD_ID"] = "20"
os.environ["ADMIN_IDS"] = "111"
os.environ["PAGE_SIZE"] = "2"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.db import repo
from bot.handlers import build_root_router
from helpers import MockSession

_APP: SimpleNamespace | None = None


def get_app() -> SimpleNamespace:
    """Один Dispatcher на процесс: aiogram запрещает включать роутеры дважды."""
    global _APP
    if _APP is None:
        session = MockSession()
        bot = Bot(
            token="42:TESTTOKEN",
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher.include_router(
            build_root_router(rate_limit=0, album_window=0.05, state_ttl=900)
        )
        _APP = SimpleNamespace(bot=bot, dp=dispatcher, session=session)
    return _APP


@pytest.fixture(autouse=True)
async def clean_state():
    await repo.reset_db()
    app = get_app()
    app.session.sent.clear()
    app.session.edit_error = None
    app.dp.storage.storage.clear()
    yield


@pytest.fixture
def app() -> SimpleNamespace:
    return get_app()
