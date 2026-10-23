"""Подготовка и отправка публикаций в Telegram."""

from __future__ import annotations

import asyncio
import html
import json
import mimetypes
import re
import uuid
from pathlib import Path

from bs4 import BeautifulSoup, Tag
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


def _plain_text_from_html(content: str) -> str:
    """Извлечь текст для проверки лимитов, не считая HTML-разметку."""
    soup = BeautifulSoup(content, "html.parser")
    for node in soup.find_all(["img", "video", "table", "script", "style"]):
        node.decompose()
    for node in soup.find_all("br"):
        node.replace_with("\n")
    for node in soup.find_all(["p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"]):
        node.insert_after("\n")
    return soup.get_text().strip()


def _sanitize_plain_html(content: str) -> str:
    """Оставить только форматирование, поддерживаемое обычными сообщениями Telegram."""
    soup = BeautifulSoup(content, "html.parser")
    for node in soup.find_all(["script", "style", "img", "video", "table", "iframe"]):
        node.decompose()
    for node in list(soup.find_all(["ul", "ol"])):
        node.unwrap()
    for node in list(soup.find_all("li")):
        node.insert_before("• ")
        node.insert_after(soup.new_tag("br"))
        node.unwrap()
    for node in list(soup.find_all("br")):
        node.replace_with("\n")
    for node in list(soup.find_all(["p", "div"])):
        node.insert_before("\n")
        node.insert_after("\n")
        node.unwrap()
    for node in list(soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])):
        node.name = "b"
        node.insert_after("\n")
    allowed = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre", "blockquote"}
    for node in list(soup.find_all(True)):
        if node.name not in allowed:
            node.unwrap()
            continue
        if node.name == "a":
            href = str(node.get("href", "")).strip()
            if not href.lower().startswith(("https://", "http://", "tg://", "mailto:")):
                node.unwrap()
            else:
                node.attrs = {"href": href}
        else:
            node.attrs = {}
    return soup.decode_contents().strip()


def _rich_payload(
    text: str,
    image_path: str | None,
    *,
    rich_formatting: bool,
    invisible_media_link: bool = False,
) -> dict:
    """Сформировать HTML и список медиа для рич-сообщения."""
    body = text if rich_formatting else html.escape(text, quote=False)
    media: list[dict] = []

    def replace_media(match: re.Match[str]) -> str:
        tag = match.group(0)
        source = re.search(r"""\bsrc\s*=\s*(['"])(.*?)\1""", tag, re.IGNORECASE | re.DOTALL)
        if not source:
            return ""
        url = html.unescape(source.group(2)).strip()
        if not url.lower().startswith(("https://", "http://")):
            return ""
        media_type = "video" if tag.lower().startswith("<video") else "photo"
        media_id = f"publication_media_{len(media) + 1}"
        media.append({"id": media_id, "media": {"type": media_type, "media": url}})
        if invisible_media_link:
            target = "video" if media_type == "video" else "photo"
            return f'<a href="tg://{target}?id={media_id}">\u2063</a>'
        label = "Видео" if media_type == "video" else "Изображение"
        if media_type == "photo":
            return f'<img src="tg://photo?id={media_id}" alt="{label}">'
        return f'<video controls src="tg://video?id={media_id}">'

    if rich_formatting:
        body = re.sub(
            r"<img\b[^>]*>|<video\b[^>]*>.*?</video\s*>",
            replace_media,
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
    rich_message: dict = {"html": body}
    if image_path:
        media.append(
            {
                "id": "publication_photo",
                "media": {"type": "photo", "media": "attach://photo"},
            }
        )
        if invisible_media_link:
            rich_message["html"] += '\n\n<a href="tg://photo?id=publication_photo">\u2063</a>'
        else:
            rich_message["html"] += '\n\n<img src="tg://photo?id=publication_photo" alt="Изображение">'
    if media:
        rich_message["media"] = media
    return rich_message



def _plain_media_payload(content: str, image_path: str | None = None) -> dict | None:
    """Подготовить обычное сообщение с не более чем одним медиа через невидимую ссылку."""
    soup = BeautifulSoup(content, "html.parser")
    media_nodes = list(soup.find_all(["img", "video"]))
    if len(media_nodes) > 1:
        raise ValueError("В одном обычном сообщении допускается только одно изображение или видео.")
    if media_nodes and image_path:
        raise ValueError("В одном обычном сообщении допускается только одно медиа. Удали встроенное изображение или отдельный файл.")
    media_markup = ""
    if media_nodes:
        media_node = media_nodes[0]
        source = str(media_node.get("src", "")).strip()
        if not source.lower().startswith(("https://", "http://")):
            raise ValueError("Для медиа в обычном сообщении укажи публичный URL, начинающийся с http:// или https://.")
        media_markup = str(media_node)
        media_node.decompose()
    if not media_markup and not image_path:
        return None
    safe_text = _sanitize_plain_html(soup.decode_contents())
    payload = _rich_payload(
        safe_text + media_markup,
        image_path,
        rich_formatting=True,
        invisible_media_link=True,
    )
    if not payload.get("media"):
        raise ValueError("Не удалось подготовить изображение или видео для публикации.")
    return payload

async def _send_rich(
    token: str,
    chat_id: str,
    text: str,
    image_path: str | None = None,
    *,
    rich_formatting: bool = True,
) -> None:
    """Отправить одно рич-сообщение; сетевой запрос выполняется вне цикла asyncio."""
    if len(_plain_text_from_html(text)) > RICH_TEXT_LIMIT:
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
    parts: list[str] | None = None,
) -> int:
    """Отправить публикацию выбранным способом и вернуть число сообщений."""
    text = text.strip()
    requested_mode = mode
    parts = [part.strip() for part in parts or [] if part.strip()]
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
            remaining = text[CAPTION_LIMIT:].strip()
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
        is_html = bool(re.search(r"</?(?:p|div|b|strong|i|em|u|s|strike|del|a|code|pre|blockquote|ul|ol|li|h[1-6]|img|video)\b", text, re.IGNORECASE))
        markup = text if is_html else html.escape(text, quote=False)
        visible_text = _plain_text_from_html(_sanitize_plain_html(markup))
        if len(visible_text) > TEXT_LIMIT and not series:
            raise ValueError("Обычное сообщение ограничено 4096 символами. Включи серию публикаций.")
        if parts:
            prepared_parts = [
                part if re.search(r"</?(?:p|div|b|strong|i|em|u|s|strike|del|a|code|pre|blockquote|ul|ol|li|h[1-6]|img|video)\b", part, re.IGNORECASE)
                else html.escape(part, quote=False)
                for part in parts
            ]
        elif len(visible_text) <= TEXT_LIMIT:
            prepared_parts = [markup]
        elif series:
            prepared_parts = [html.escape(part, quote=False) for part in split_text(visible_text, TEXT_LIMIT)]
        else:
            prepared_parts = [markup]
        for index, part in enumerate(prepared_parts, start=1):
            safe_part = _sanitize_plain_html(part)
            part_length = len(_plain_text_from_html(safe_part))
            if part_length > TEXT_LIMIT:
                raise ValueError(f"Пост {index} превышает лимит обычного сообщения Telegram ({TEXT_LIMIT} символов).")
            media_nodes = BeautifulSoup(part, "html.parser").find_all(["img", "video"])
            if len(media_nodes) > 1:
                raise ValueError(f"Пост {index}: в обычном сообщении допускается только одно изображение или видео.")
        async with Bot(token=token) as bot:
            for index, part in enumerate(prepared_parts):
                payload = _plain_media_payload(part, image_path if index == 0 else None)
                if payload:
                    await asyncio.to_thread(_multipart_request, token, chat_id, payload, image_path if index == 0 else None)
                else:
                    await bot.send_message(chat_id=chat_id, text=_sanitize_plain_html(part), parse_mode="HTML")
        return len(prepared_parts)

    if mode == "media_text":
        if not image_path:
            mode = "rich"
        elif len(text) > RICH_TEXT_LIMIT and not series:
            raise ValueError("Рич-сообщение ограничено 32768 символами. Включи серию публикаций.")
        elif len(text) <= RICH_TEXT_LIMIT:
            await _send_rich(token, chat_id, text, image_path, rich_formatting=True)
            return 1
        else:
            parts = split_text(text, RICH_TEXT_LIMIT)
            await _send_rich(token, chat_id, parts[0], image_path, rich_formatting=True)
            for part in parts[1:]:
                await _send_rich(token, chat_id, part, rich_formatting=False)
            return len(parts)

    if mode == "rich":
        visible_length = len(_plain_text_from_html(text))
        if requested_mode == "rich_series" and parts:
            for index, part in enumerate(parts):
                part_length = len(_plain_text_from_html(part))
                if part_length > RICH_TEXT_LIMIT:
                    raise ValueError(f"Пост {index + 1} превышает лимит рич-текста Telegram ({RICH_TEXT_LIMIT} символов).")
            for index, part in enumerate(parts):
                await _send_rich(token, chat_id, part, image_path if index == 0 else None, rich_formatting=True)
            return len(parts)
        if visible_length <= RICH_TEXT_LIMIT and not (series and parts):
            await _send_rich(token, chat_id, text, image_path, rich_formatting=True)
            return 1
        if not series:
            raise ValueError("Рич-сообщение ограничено 32768 символами. Включи серию публикаций.")
        prepared_parts = parts or split_text(text, RICH_TEXT_LIMIT)
        for index, part in enumerate(prepared_parts):
            await _send_rich(
                token, chat_id, part, image_path if index == 0 else None, rich_formatting=True
            )
        return len(prepared_parts)

    raise ValueError(f"Неизвестный режим публикации: {mode}")


def publish_sync(
    token: str,
    chat_id: str,
    text: str,
    image_path: str | None = None,
    mode: str = "auto",
    series: bool = False,
    parts: list[str] | None = None,
) -> int:
    """Синхронная точка вызова для графического интерфейса."""
    return asyncio.run(send_publication(token, chat_id, text, image_path, mode, series, parts))
