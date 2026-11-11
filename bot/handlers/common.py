from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.config import get_settings
from bot.db import repo
from bot.keyboards.admin import admin_menu
from bot.keyboards.user import main_menu

router = Router(name="common")


def _welcome() -> str:
    return (
        "👋 Добро пожаловать!\n\n"
        "Здесь можно оставить заявку системному администратору: опишите проблему, "
        "приложите фото или видео.\n\n"
        "Выберите действие:"
    )


async def menu_for(tg_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Главный экран с учётом роли."""
    if get_settings().is_admin(tg_id):
        return "<b>Админ-панель</b>\n\nВыберите раздел:", admin_menu()
    return _welcome(), main_menu()


async def send_menu(message: Message, tg_id: int) -> None:
    text, keyboard = await menu_for(tg_id)
    await message.answer(text, reply_markup=keyboard)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None:
        return

    await state.clear()
    is_admin = get_settings().is_admin(user.id)
    await repo.get_or_create_user(user.id, is_admin=is_admin)

    if is_admin:
        await message.answer(
            "<b>Админ-панель</b>\n\nВыберите раздел:", reply_markup=admin_menu()
        )
        return

    await message.answer(_welcome(), reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Помощь</b>\n\n"
        "/start — главное меню\n"
        "/help — эта справка\n"
        "/cancel — отменить текущее действие\n\n"
        "Заявка создаётся кнопкой «📝 Создать заявку»: опишите проблему, "
        "приложите фото или видео, выберите приоритет и место.",
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    await state.clear()
    await message.answer("Действие отменено.")
    await send_menu(message, message.from_user.id)


@router.callback_query(F.data == "u:menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message is None:
        await callback.answer()
        return
    text, keyboard = await menu_for(callback.from_user.id)
    await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "u:help")
async def cb_help(callback: CallbackQuery) -> None:
    await callback.answer(
        "Создайте заявку кнопкой «📝 Создать заявку» — ответ придёт в этот чат.",
        show_alert=True,
    )


@router.callback_query(F.data == "u:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message is None:
        await callback.answer()
        return
    text, keyboard = await menu_for(callback.from_user.id)
    await callback.message.answer("Действие отменено.\n\n" + text, reply_markup=keyboard)
    await callback.answer()
