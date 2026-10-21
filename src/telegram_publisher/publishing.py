"""Подготовка и отправка публикаций в Telegram."""

from __future__ import annotations

import asyncio
import html
import json
import mimetypes
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from telegram import Bot


TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
RICH_TEXT_LIMIT = 32768

PUBLICATION_MODES = {
    "plain": "Обычный текст",
    "caption": "Подпись к изображению",
    "media_text": "Обычный текст + изображение",
    "rich": "Рич-текст",
    "plain_series": "Серия обычных сообщений",
    "rich_series": "Серия рич-сообщений",
}


def split_text(text: str, limit: int = TEXT_LIMIT) -> list[str]:
    """Разбить текст на части не длиннее лимита, по возможности по абзацам и словам."""
    text = text.strip()
    if not text:
        return []
    if limit < 1:
        raise ValueError("Лимит длины должен быть положительным.")

    parts: list[str] = []
    remaining = text

    while len(remaining) > limit:
        boundary = remaining.rfind("\n\n", 0, limit + 1)
        if boundary <= 0:
            boundary = remaining.rfind("\n", 0, limit + 1)
        if boundary <= 0:
            boundary = remaining.rfind(" ", 0, limit + 1)
        if boundary <= 0:
            boundary = limit

        part = remaining[:boundary].strip()
        if not part:
            part = remaining[:limit].strip()
            boundary = limit
        parts.append(part)
        remaining = remaining[boundary:].strip()

    if remaining:
        parts.append(remaining)
    return parts


def estimate_message_count(
    text: str,
    image_path: str | None,
    mode: str,
    series: bool = False,
) -> int:
    """Оценить число сообщений для подтверждения публикации."""
    text = text.strip()
    if mode == "caption" or (mode == "plain_series" and image_path):
        return (1 if image_path else 0) + (
            len(split_text(text[CAPTION_LIMIT:], TEXT_LIMIT))
            if image_path and len(text) > CAPTION_LIMIT
            else 0
        )
    if mode == "plain_series":
        return len(split_text(text, TEXT_LIMIT))
    if mode == "rich_series" or (series and mode in {"rich", "media_text"}):
        return max(1, len(split_text(text, RICH_TEXT_LIMIT))) if text or image_path else 0
    return 1 if text or image_path else 0


def _multipart_request(token: str, chat_id: str, rich_message: dict, image_path: str | None) -> None:
    """Отправить рич-сообщение через Bot API с необязательной локальной фотографией."""
    boundary = "----TelegramPublisher" + uuid.uuid4().hex
    body = bytearray()

    def add_field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"))
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    add_field("chat_id", chat_id)
    add_field("rich_message", json.dumps(rich_message, ensure_ascii=False))

    if image_path:
        path = Path(image_path)
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(
            f'Content-Disposition: form-data; name="photo"; filename="{path.name}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("ascii"))
        body.extend(path.read_bytes())
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("ascii"))
    request = Request(
        f"https://api.telegram.org/bot{token}/sendRichMessage",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Не удалось отправить рич-сообщение: {error}") from error
    if not result.get("ok"):
        raise RuntimeError(
            "Telegram отклонил рич-сообщение: "
            + str(result.get("description", "неизвестная ошибка"))
        )


def _rich_payload(text: str, image_path: str | None, *, rich_formatting: bool) -> dict:
    """Сформировать содержимое рич-сообщения и привязать локальную фотографию."""
    if rich_formatting:
        body = text
    else:
        body = html.escape(text, quote=False)
    rich_message: dict = {"html": body}
    if image_path:
        rich_message["media"] = [
            {
                "id": "publication_photo",
                "media": {"type": "photo", "media": "attach://photo"},
            }
        ]
        rich_message["html"] = (
            rich_message["html"]
            + '\n\n<a href="tg://photo?id=publication_photo">Изображение</a>'
        )
    return rich_message


async def _send_rich(
    token: str,
    chat_id: str,
    text: str,
    image_path: str | None = None,
    *,
    rich_formatting: bool = True,
) -> None:
    """Отправить одно рич-сообщение; сетевой запрос выполняется вне цикла asyncio."""
    if len(text) > RICH_TEXT_LIMIT:
        raise ValueError(
            f"Рич-текст не может превышать {RICH_TEXT_LIMIT} символов за одно сообщение."
        )
    if not text and not image_path:
        raise ValueError("Добавь текст или выбери изображение для публикации.")
    payload = _rich_payload(text, image_path, rich_formatting=rich_formatting)
    await asyncio.to_thread(_multipart_request, token, chat_id, payload, image_path)


async def send_publication(
    token: str,
    chat_id: str,
    text: str,
    image_path: str | None = None,
    mode: str = "auto",
    series: bool = False,
) -> int:
    """Отправить публикацию выбранным способом и вернуть число сообщений."""
    text = text.strip()
    if not text and not image_path:
        raise ValueError("Добавь текст или выбери изображение для публикации.")

    if mode == "auto":
        if image_path and len(text) <= CAPTION_LIMIT:
            mode = "caption"
        elif image_path and len(text) <= TEXT_LIMIT:
            mode = "media_text"
        elif len(text) <= TEXT_LIMIT and not image_path:
            mode = "plain"
        else:
            mode = "rich"

    if mode in {"plain_series", "rich_series"}:
        series = True
        if mode == "plain_series":
            mode = "caption" if image_path else "plain"
        else:
            mode = "rich"

    if mode == "caption":
        if image_path and len(text) > CAPTION_LIMIT and not series:
            raise ValueError("Для подписи к изображению доступно не более 1024 символов. Включи серию публикаций.")
        if not image_path:
            mode = "plain" if len(text) <= TEXT_LIMIT else "rich"
        elif len(text) > CAPTION_LIMIT:
            first = text[:CAPTION_LIMIT].rstrip()
            remaining = text[len(first):].strip()
            sent = 0
            async with Bot(token=token) as bot:
                path = Path(image_path)
                with path.open("rb") as image:
                    await bot.send_photo(chat_id=chat_id, photo=image, caption=first or None)
                sent += 1
                for part in split_text(remaining, TEXT_LIMIT):
                    await bot.send_message(chat_id=chat_id, text=part)
                    sent += 1
            return sent
        else:
            async with Bot(token=token) as bot:
                if image_path:
                    path = Path(image_path)
                    with path.open("rb") as image:
                        await bot.send_photo(chat_id=chat_id, photo=image, caption=text or None)
                else:
                    await bot.send_message(chat_id=chat_id, text=text)
            return 1

    if mode == "plain":
        if len(text) <= TEXT_LIMIT:
            async with Bot(token=token) as bot:
                await bot.send_message(chat_id=chat_id, text=text)
            return 1
        if not series:
            raise ValueError("Обычное сообщение ограничено 4096 символами. Включи серию или выбери рич-текст.")
        async with Bot(token=token) as bot:
            parts = split_text(text, TEXT_LIMIT)
            for part in parts:
                await bot.send_message(chat_id=chat_id, text=part)
        return len(parts)

    if mode == "media_text":
        if not image_path:
            mode = "rich"
        elif len(text) > RICH_TEXT_LIMIT and not series:
            raise ValueError("Рич-сообщение ограничено 32768 символами. Включи серию публикаций.")
        elif len(text) <= RICH_TEXT_LIMIT:
            await _send_rich(token, chat_id, text, image_path, rich_formatting=False)
            return 1
        else:
            parts = split_text(text, RICH_TEXT_LIMIT)
            await _send_rich(token, chat_id, parts[0], image_path, rich_formatting=False)
            for part in parts[1:]:
                await _send_rich(token, chat_id, part, rich_formatting=False)
            return len(parts)

    if mode == "rich":
        if len(text) <= RICH_TEXT_LIMIT:
            await _send_rich(token, chat_id, text, image_path, rich_formatting=True)
            return 1
        if not series:
            raise ValueError("Рич-сообщение ограничено 32768 символами. Включи серию публикаций.")
        parts = split_text(text, RICH_TEXT_LIMIT)
        for index, part in enumerate(parts):
            await _send_rich(
                token, chat_id, part, image_path if index == 0 else None, rich_formatting=True
            )
        return len(parts)

    raise ValueError(f"Неизвестный режим публикации: {mode}")


def publish_sync(
    token: str,
    chat_id: str,
    text: str,
    image_path: str | None = None,
    mode: str = "auto",
    series: bool = False,
) -> int:
    """Синхронная точка вызова для графического интерфейса."""
    return asyncio.run(send_publication(token, chat_id, text, image_path, mode, series))
