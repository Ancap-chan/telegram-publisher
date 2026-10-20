"""Подготовка и отправка публикаций в Telegram."""

from __future__ import annotations

import asyncio
from pathlib import Path

from telegram import Bot


TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024


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


async def send_publication(
    token: str,
    chat_id: str,
    text: str,
    image_path: str | None = None,
) -> int:
    """Отправить текст и необязательное изображение; вернуть число сообщений."""
    text_parts = split_text(text, CAPTION_LIMIT if image_path else TEXT_LIMIT)
    if not text_parts and not image_path:
        raise ValueError("Добавь текст или выбери изображение для публикации.")

    sent = 0
    async with Bot(token=token) as bot:
        if image_path:
            path = Path(image_path)
            with path.open("rb") as image:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=image,
                    caption=text_parts[0] if text_parts else None,
                )
            sent += 1
            text_parts = text_parts[1:] if text_parts else []
        for part in text_parts:
            await bot.send_message(chat_id=chat_id, text=part)
            sent += 1
    return sent


def publish_sync(token: str, chat_id: str, text: str, image_path: str | None = None) -> int:
    """Синхронная точка вызова для графического интерфейса."""
    return asyncio.run(send_publication(token, chat_id, text, image_path))
