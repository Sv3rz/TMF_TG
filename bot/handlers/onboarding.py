from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.db import repo
from bot.keyboards.user import main_menu
from bot.states import Onb

router = Router(name="onboarding")


@router.message(Onb.place, F.text)
async def onb_place(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user is None or message.text is None:
        return

    place = " ".join(message.text.split())[:255]
    if len(place) < 2:
        await message.answer("Слишком коротко. Укажите место (минимум 2 символа):")
        return

    await repo.set_user_place(user.id, place)
    await state.clear()
    await message.answer(
        f"Спасибо! Записал: <b>{html.escape(place)}</b>.",
        reply_markup=main_menu(),
    )


@router.message(Onb.place)
async def onb_place_invalid(message: Message) -> None:
    await message.answer("Пришлите место текстом, пожалуйста.")
