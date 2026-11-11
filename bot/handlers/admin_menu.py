"""Админ-меню и листы заявок."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.db import repo
from bot.keyboards.admin import admin_list_kb, admin_menu

router = Router(name="admin_menu")
logger = logging.getLogger(__name__)

TAB_LABELS = {
    "waiting": "🆕 Ожидают",
    "in_progress": "🔧 В работе",
    "all": "📜 Все",
}

ADMIN_MENU_TEXT = "<b>Админ-панель</b>\n\nВыберите раздел:"


async def _edit(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            logger.warning("Не удалось обновить админ-сообщение: %s", exc)
    except TelegramAPIError:
        logger.warning("Ошибка Telegram при обновлении админ-сообщения", exc_info=True)


@router.callback_query(F.data == "a:menu")
async def admin_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit(callback, ADMIN_MENU_TEXT, admin_menu())
    await callback.answer()


@router.callback_query(F.data == "a:exit")
async def admin_exit(callback: CallbackQuery, state: FSMContext) -> None:
    """«Выход» закрывает панель: меню убирается, /start открывает снова."""
    await state.clear()
    if callback.message is not None:
        try:
            await callback.message.edit_text("Админ-панель закрыта.\n/start — открыть снова.")
        except TelegramBadRequest:
            pass
        except TelegramAPIError:
            logger.warning("Не удалось закрыть админ-панель", exc_info=True)
    await callback.answer()


@router.callback_query(F.data.startswith("a:list:"))
async def admin_list(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":") if callback.data else []
    if len(parts) != 4 or parts[2] not in TAB_LABELS:
        await callback.answer("Некорректный раздел", show_alert=True)
        return

    tab = parts[2]
    page = int(parts[3]) if parts[3].isdigit() else 1
    page = max(1, page)

    result = await repo.list_by_tab(tab, page=page)
    if result.items and page > result.pages:
        page = result.pages
        result = await repo.list_by_tab(tab, page=page)

    await state.update_data(admin_tab=tab, admin_page=page)

    if not result.items:
        await _edit(callback, f"{TAB_LABELS[tab]}\n\nЗаявок нет.", admin_menu())
        await callback.answer()
        return

    text = (
        f"{TAB_LABELS[tab]} · стр. {page}/{result.pages}\n"
        f"Всего: {result.total}\n\n"
        "Выберите заявку:"
    )
    await _edit(callback, text, admin_list_kb(tab, result.items, page, result.pages))
    await callback.answer()
