from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from pydantic import ValidationError

from bot.config import get_settings
from bot.db.repo import init_db
from bot.handlers import build_root_router

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="help", description="Помощь"),
    BotCommand(command="cancel", description="Отменить действие"),
]


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def build_dispatcher(settings) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(
        build_root_router(
            rate_limit=settings.rate_limit,
            album_window=settings.album_window,
            state_ttl=settings.state_ttl,
        )
    )
    return dispatcher


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    logger.info(
        "Маршрутизация: заявки → чат %s, топик %s; логи → чат %s, топик %s",
        settings.tickets_chat_id,
        settings.tickets_thread_id or "General",
        settings.log_chat,
        settings.log_thread_id or "General",
    )

    await init_db()

    dispatcher = build_dispatcher(settings)
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    try:
        me = await bot.get_me()
        logger.info("Запуск бота @%s (id=%s)", me.username, me.id)
        await bot.set_my_commands(COMMANDS)
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        await bot.session.close()
        logger.info("Бот остановлен")


def run() -> None:
    try:
        asyncio.run(main())
    except ValidationError as exc:
        missing = ", ".join(str(error["loc"][0]).upper() for error in exc.errors())
        print(
            f"Ошибка конфигурации: не заданы переменные: {missing}.\n"
            "Проверьте .env рядом с docker-compose.yml. Для `docker run` нужен флаг "
            "--env-file .env — без него .env не виден контейнеру.",
            file=sys.stderr,
        )
        sys.exit(2)
    except TelegramUnauthorizedError:
        logger.error("Telegram отклонил BOT_TOKEN — проверьте значение в .env")
        sys.exit(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Получен сигнал остановки")


if __name__ == "__main__":
    run()
