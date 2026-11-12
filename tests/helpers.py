from __future__ import annotations

import itertools
import time
from datetime import datetime, timezone

from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Chat, Message, MessageId, User

BOT_USER = User(id=42, is_bot=True, first_name="TestBot", username="test_bot")

_counter = itertools.count(1)


class MockSession(BaseSession):
    """Подменяет HTTP-сессию Telegram: запоминает методы и возвращает заглушки."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[object] = []
        self.edit_error: str | None = None
        self._msg_id = 100

    async def close(self) -> None:
        return None

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def _message(self, chat_id: int) -> Message:
        self._msg_id += 1
        return Message(
            message_id=self._msg_id,
            date=datetime.now(timezone.utc),
            chat=Chat(id=chat_id, type="private"),
            from_user=BOT_USER,
        )

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        name = type(method).__name__

        if name == "EditMessageText":
            if self.edit_error == "not_found":
                raise TelegramBadRequest(
                    method=method, message="Bad Request: message to edit not found"
                )
            if self.edit_error == "not_modified":
                raise TelegramBadRequest(
                    method=method,
                    message="Bad Request: message is not modified: content is the same",
                )
            return self._message(method.chat_id)

        if name == "SendMessage":
            message = self._message(method.chat_id)
            return message.model_copy(update={"text": getattr(method, "text", None)})
        if name in ("SendPhoto", "SendVideo"):
            return self._message(method.chat_id)
        if name == "CopyMessage":
            return MessageId(message_id=2000)
        if name == "CopyMessages":
            return [MessageId(message_id=2000 + i) for i in range(len(method.message_ids))]
        if name == "GetMe":
            return BOT_USER
        return True

    # --- выборки для ассертов -------------------------------------------

    def edits(self, chat_id: int | None = None):
        return [
            m
            for m in self.sent
            if type(m).__name__ == "EditMessageText"
            and (chat_id is None or m.chat_id == chat_id)
        ]

    def sends(self, chat_id: int | None = None):
        return [
            m
            for m in self.sent
            if type(m).__name__ == "SendMessage"
            and (chat_id is None or m.chat_id == chat_id)
        ]

    def method(self, name: str):
        return [m for m in self.sent if type(m).__name__ == name]


def person(tg_id: int) -> dict:
    return {"id": tg_id, "is_bot": False, "first_name": "Иван", "username": "ivan"}


def msg_update(
    tg_id: int,
    text: str | None = None,
    *,
    caption: str | None = None,
    photo: tuple[str, ...] = (),
    document: str | None = None,
    media_group_id: str | None = None,
    chat_id: int | None = None,
    chat_type: str = "private",
) -> dict:
    seq = next(_counter)
    message: dict = {
        "message_id": seq,
        "date": int(time.time()),
        "chat": {"id": tg_id if chat_id is None else chat_id, "type": chat_type},
        "from": person(tg_id),
    }
    if text is not None:
        message["text"] = text
    if caption is not None:
        message["caption"] = caption
    if photo:
        message["photo"] = [
            {"file_id": item, "file_unique_id": f"{item}u", "width": 800, "height": 600}
            for item in photo
        ]
    if document is not None:
        message["document"] = {
            "file_id": document,
            "file_unique_id": f"{document}u",
            "file_name": "doc.pdf",
        }
    if media_group_id is not None:
        message["media_group_id"] = media_group_id
    return {"update_id": seq, "message": message}


def cb_update(tg_id: int, data: str) -> dict:
    seq = next(_counter)
    return {
        "update_id": seq,
        "callback_query": {
            "id": f"cb{seq}",
            "from": person(tg_id),
            "chat_instance": "ci",
            "data": data,
            "message": {
                "message_id": seq,
                "date": int(time.time()),
                "chat": {"id": tg_id, "type": "private"},
                "from": BOT_USER,
                "text": "menu",
            },
        },
    }


def kb_of(method) -> list[str]:
    if getattr(method, "reply_markup", None) is None:
        return []
    return [b.callback_data for row in method.reply_markup.inline_keyboard for b in row]


def last_answer(session: MockSession) -> str:
    answers = session.method("AnswerCallbackQuery")
    return answers[-1].text if answers else ""
