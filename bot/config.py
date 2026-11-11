from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения: .env + переменные окружения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram ---
    bot_token: SecretStr = Field(..., description="Токен от @BotFather")
    admin_ids: str = Field("", description="Telegram ID админов через запятую")
    tickets_chat_id: int = Field(..., description="Чат-доска заявок (форум или обычный чат)")
    tickets_thread_id: int | None = Field(
        None, description="Топик «Заявки»: message_thread_id форума"
    )
    log_chat_id: int | None = Field(
        None, description="Чат логов; если пусто — используется чат заявок"
    )
    log_thread_id: int | None = Field(
        None, description="Топик «Log»: message_thread_id форума"
    )

    # --- Приложение ---
    log_level: str = Field("INFO")
    db_path: Path = Field(Path("data/bot.sqlite3"))
    page_size: int = Field(8, ge=1, le=20, description="Заявок на страницу")
    rate_limit: float = Field(0.7, ge=0.0, le=10.0, description="Антифлуд, сек")
    album_window: float = Field(1.2, ge=0.2, le=5.0, description="Окно сборки альбома")
    state_ttl: int = Field(900, ge=60, description="TTL FSM, сек (15 мин)")

    @field_validator("admin_ids")
    @classmethod
    def _validate_admin_ids(cls, value: str) -> str:
        for part in _split_ids(value):
            if not part.lstrip("-").isdigit():
                raise ValueError(f"ADMIN_IDS: ожидается Telegram ID, получено {part!r}")
        return value

    @field_validator("log_chat_id", "tickets_thread_id", "log_thread_id", mode="before")
    @classmethod
    def _empty_optional_int(cls, value: object) -> object:
        if value in ("", None):
            return None
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"LOG_LEVEL: неизвестный уровень {value!r}")
        return level

    @property
    def admins(self) -> frozenset[int]:
        return frozenset(int(part) for part in _split_ids(self.admin_ids))

    @property
    def log_chat(self) -> int:
        """Чат логов: отдельный или общий с заявками."""
        return self.log_chat_id or self.tickets_chat_id

    def is_admin(self, tg_id: int) -> bool:
        return tg_id in self.admins


def _split_ids(raw: str) -> list[str]:
    chunks = raw.replace(";", ",").replace(" ", ",").split(",")
    return [chunk.strip() for chunk in chunks if chunk.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
