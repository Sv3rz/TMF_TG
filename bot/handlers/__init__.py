"""Роутеры: пользовательский и админский, взаимно изолированные."""

from __future__ import annotations

from aiogram import Router

from bot.handlers import (
    admin_actions,
    admin_menu,
    board_callbacks,
    common,
    onboarding,
    user_list,
    user_new,
)
from bot.middlewares.album import AlbumMiddleware
from bot.middlewares.role import AdminMiddleware
from bot.middlewares.throttle import ThrottleMiddleware
from bot.middlewares.ttl import StateTTLMiddleware


def build_root_router(
    rate_limit: float, album_window: float, state_ttl: int = 900
) -> Router:
    root = Router(name="root")

    user_router = Router(name="user")
    user_router.include_router(common.router)
    user_router.include_router(onboarding.router)
    user_router.include_router(user_new.router)
    user_router.include_router(user_list.router)
    user_router.message.middleware(StateTTLMiddleware(state_ttl))
    user_router.callback_query.middleware(StateTTLMiddleware(state_ttl))
    user_router.message.middleware(ThrottleMiddleware(rate_limit))
    user_router.message.middleware(AlbumMiddleware(album_window))

    admin_router = Router(name="admin")
    admin_router.include_router(admin_menu.router)
    admin_router.include_router(admin_actions.router)
    admin_router.include_router(board_callbacks.router)
    admin_router.message.middleware(AdminMiddleware())
    admin_router.callback_query.middleware(AdminMiddleware())
    admin_router.message.middleware(StateTTLMiddleware(state_ttl))
    admin_router.callback_query.middleware(StateTTLMiddleware(state_ttl))
    admin_router.message.middleware(AlbumMiddleware(album_window))

    root.include_router(user_router)
    root.include_router(admin_router)
    return root
