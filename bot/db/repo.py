"""CRUD-слой. Только работа с БД, без Telegram-логики."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from bot.config import get_settings
from bot.db.models import (
    ACTIVE_STATUSES,
    AdminReply,
    Attachment,
    Base,
    LogEntry,
    Priority,
    Ticket,
    TicketStatus,
    User,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


@dataclass(frozen=True)
class Page:
    """Страница списка заявок."""

    items: list[Ticket]
    total: int
    page: int
    per_page: int

    @property
    def pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))


@dataclass(frozen=True)
class ActorInfo:
    """Кто и когда менял статус заявки (из logs)."""

    tg_id: int
    at: Any
    name: str | None = None


def _engine_instance() -> AsyncEngine:
    global _engine
    if _engine is None:
        db_path = get_settings().db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(_engine_instance(), expire_on_commit=False)
    return _session_factory


async def init_db() -> None:
    async with _engine_instance().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def reset_db() -> None:
    """Пересоздаёт схему. Только для тестов."""
    async with _engine_instance().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


# --- users -----------------------------------------------------------------


async def get_or_create_user(tg_id: int, *, is_admin: bool = False) -> User:
    async with session_factory()() as session:
        user = await session.scalar(select(User).where(User.tg_id == tg_id))
        if user is None:
            user = User(tg_id=tg_id, is_admin=is_admin)
            session.add(user)
        else:
            user.is_admin = is_admin
        await session.commit()
        return user


async def get_user(tg_id: int) -> User | None:
    async with session_factory()() as session:
        return await session.scalar(select(User).where(User.tg_id == tg_id))


async def set_user_place(tg_id: int, place: str) -> None:
    async with session_factory()() as session:
        await session.execute(update(User).where(User.tg_id == tg_id).values(place=place))
        await session.commit()


# --- tickets ---------------------------------------------------------------


async def _load_ticket(session: AsyncSession, ticket_id: int) -> Ticket | None:
    return await session.scalar(
        select(Ticket).where(Ticket.id == ticket_id).execution_options(populate_existing=True)
    )


async def create_ticket(
    *,
    user_id: int,
    author_name: str,
    author_username: str | None,
    description: str | None,
    priority: Priority,
    place: str,
) -> Ticket:
    """Создаёт заявку, присваивая следующий номер (#0001, #0002, ...)."""
    async with session_factory()() as session:
        last_number = await session.scalar(select(func.coalesce(func.max(Ticket.number), 0)))
        ticket = Ticket(
            number=int(last_number or 0) + 1,
            user_id=user_id,
            author_name=author_name,
            author_username=author_username,
            description=description,
            priority=priority,
            place=place,
            status=TicketStatus.WAITING,
        )
        session.add(ticket)
        await session.commit()
        loaded = await _load_ticket(session, ticket.id)
        if loaded is None:  # pragma: no cover - защита от рассогласования
            raise RuntimeError(f"Созданная заявка {ticket.id} не читается")
        return loaded


async def get_ticket(ticket_id: int) -> Ticket | None:
    async with session_factory()() as session:
        return await _load_ticket(session, ticket_id)


async def get_ticket_by_number(number: int) -> Ticket | None:
    async with session_factory()() as session:
        return await session.scalar(select(Ticket).where(Ticket.number == number))


async def get_user_ticket(tg_id: int, ticket_id: int) -> Ticket | None:
    """Заявка только если принадлежит пользователю."""
    async with session_factory()() as session:
        return await session.scalar(
            select(Ticket)
            .join(User, User.id == Ticket.user_id)
            .where(Ticket.id == ticket_id, User.tg_id == tg_id)
        )


async def list_user_active(
    tg_id: int, page: int = 1, per_page: int | None = None
) -> Page:
    """Активные заявки пользователя (waiting / in_progress)."""
    per_page = per_page or get_settings().page_size
    offset = max(0, page - 1) * per_page
    async with session_factory()() as session:
        conditions = [User.tg_id == tg_id, Ticket.status.in_(ACTIVE_STATUSES)]
        total = (
            await session.scalar(
                select(func.count(Ticket.id)).join(User, User.id == Ticket.user_id).where(*conditions)
            )
            or 0
        )
        items = list(
            (
                await session.scalars(
                    select(Ticket)
                    .join(User, User.id == Ticket.user_id)
                    .where(*conditions)
                    .order_by(Ticket.number.asc())
                    .offset(offset)
                    .limit(per_page)
                )
            ).all()
        )
    return Page(items=items, total=total, page=page, per_page=per_page)


async def list_by_tab(tab: str, page: int = 1, per_page: int | None = None) -> Page:
    """Админ-список: waiting | in_progress | all."""
    if tab not in {"waiting", "in_progress", "all"}:
        raise ValueError(f"Неизвестная вкладка: {tab!r}")

    per_page = per_page or get_settings().page_size
    offset = max(0, page - 1) * per_page
    conditions = [] if tab == "all" else [Ticket.status == TicketStatus(tab)]

    async with session_factory()() as session:
        total = await session.scalar(select(func.count(Ticket.id)).where(*conditions)) or 0
        items = list(
            (
                await session.scalars(
                    select(Ticket)
                    .where(*conditions)
                    .order_by(Ticket.number.asc())
                    .offset(offset)
                    .limit(per_page)
                )
            ).all()
        )
    return Page(items=items, total=total, page=page, per_page=per_page)


async def set_status(ticket_id: int, status: TicketStatus) -> None:
    async with session_factory()() as session:
        await session.execute(
            update(Ticket)
            .where(Ticket.id == ticket_id)
            .values(status=status, updated_at=func.now())
        )
        await session.commit()


async def set_tg_message(ticket_id: int, message_id: int) -> None:
    async with session_factory()() as session:
        await session.execute(
            update(Ticket).where(Ticket.id == ticket_id).values(tg_message_id=message_id)
        )
        await session.commit()


# --- attachments -----------------------------------------------------------


async def add_attachment(
    ticket_id: int, *, file_id: str, file_type: str, kind: str = "ticket"
) -> None:
    async with session_factory()() as session:
        session.add(
            Attachment(ticket_id=ticket_id, file_id=file_id, file_type=file_type, kind=kind)
        )
        await session.commit()


async def add_attachments(
    ticket_id: int, files: Sequence[dict[str, str]], kind: str = "ticket"
) -> None:
    """Пакетное сохранение вложений: [{"file_id": ..., "file_type": ...}, ...]."""
    if not files:
        return
    async with session_factory()() as session:
        session.add_all(
            [
                Attachment(
                    ticket_id=ticket_id,
                    file_id=item["file_id"],
                    file_type=item["file_type"],
                    kind=kind,
                )
                for item in files
            ]
        )
        await session.commit()


async def list_attachments(ticket_id: int, kind: str | None = None) -> list[Attachment]:
    async with session_factory()() as session:
        conditions = [Attachment.ticket_id == ticket_id]
        if kind is not None:
            conditions.append(Attachment.kind == kind)
        result = await session.scalars(
            select(Attachment).where(*conditions).order_by(Attachment.id.asc())
        )
        return list(result.all())


# --- admin replies ---------------------------------------------------------


async def add_admin_reply(ticket_id: int, admin_tg_id: int, text: str | None) -> AdminReply:
    async with session_factory()() as session:
        reply = AdminReply(ticket_id=ticket_id, admin_tg_id=admin_tg_id, text=text)
        session.add(reply)
        await session.commit()
        return reply


async def list_admin_replies(ticket_id: int) -> list[AdminReply]:
    async with session_factory()() as session:
        result = await session.scalars(
            select(AdminReply)
            .where(AdminReply.ticket_id == ticket_id)
            .order_by(AdminReply.id.asc())
        )
        return list(result.all())


# --- logs ------------------------------------------------------------------


async def get_last_actor(
    ticket_id: int, actions: Sequence[str]
) -> ActorInfo | None:
    """Последний автор одного из действий: id, время, имя из payload лога."""
    if not actions:
        return None
    async with session_factory()() as session:
        row = (
            await session.execute(
                select(LogEntry.actor_tg_id, LogEntry.ts, LogEntry.payload_json)
                .where(LogEntry.ticket_id == ticket_id, LogEntry.action.in_(list(actions)))
                .order_by(LogEntry.id.desc())
                .limit(1)
            )
        ).first()
    if row is None or row[0] is None:
        return None

    payload: dict[str, Any] = {}
    if row[2]:
        try:
            parsed = json.loads(row[2])
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed

    name = payload.get("admin_name")
    return ActorInfo(
        tg_id=int(row[0]),
        at=row[1],
        name=name if isinstance(name, str) and name.strip() else None,
    )


async def add_log(
    *,
    action: str,
    actor_tg_id: int | None = None,
    ticket_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    async with session_factory()() as session:
        session.add(
            LogEntry(
                action=action,
                actor_tg_id=actor_tg_id,
                ticket_id=ticket_id,
                payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
            )
        )
        await session.commit()
