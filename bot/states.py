from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Onb(StatesGroup):
    """Онбординг: место пользователя."""

    place = State()


class New(StatesGroup):
    """Создание заявки."""

    description = State()
    priority = State()
    place = State()
    confirm = State()


class AdminReply(StatesGroup):
    """Ответ администратора по заявке."""

    content = State()
