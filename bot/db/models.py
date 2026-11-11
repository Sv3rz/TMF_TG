from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Priority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TicketStatus(str, enum.Enum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = (TicketStatus.WAITING, TicketStatus.IN_PROGRESS)


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    place: Mapped[str | None] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    tickets: Mapped[list["Ticket"]] = relationship(back_populates="user")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # Снапшот автора на момент создания заявки.
    author_name: Mapped[str] = mapped_column(String(255))
    author_username: Mapped[str | None] = mapped_column(String(64))

    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[Priority] = mapped_column(
        SAEnum(Priority, native_enum=False, values_callable=_enum_values, length=16),
        default=Priority.MEDIUM,
        index=True,
    )
    place: Mapped[str] = mapped_column(String(255))
    status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, native_enum=False, values_callable=_enum_values, length=16),
        default=TicketStatus.WAITING,
        index=True,
    )
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="tickets", lazy="selectin")
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", lazy="selectin"
    )
    replies: Mapped[list["AdminReply"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", lazy="selectin"
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))  # photo | video
    kind: Mapped[str] = mapped_column(String(16), default="ticket")  # ticket | admin_reply

    ticket: Mapped[Ticket] = relationship(back_populates="attachments")


class AdminReply(Base):
    __tablename__ = "admin_replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    admin_tg_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ticket: Mapped[Ticket] = relationship(back_populates="replies")


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_tg_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    ticket_id: Mapped[int | None] = mapped_column(index=True)
    payload_json: Mapped[str | None] = mapped_column(Text)
