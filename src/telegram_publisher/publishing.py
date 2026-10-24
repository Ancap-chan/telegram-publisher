"""Подготовка и отправка публикаций в Telegram."""

from __future__ import annotations

import asyncio
import base64
from copy import copy
import html
import json
import mimetypes
import re
import uuid
from pathlib import Path

from bs4 import BeautifulSoup, Comment, Tag
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from telegram import Bot, LinkPreviewOptions


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
    """Разбить текст по абзацам, затем по предложениям и словам, не превышая лимит."""
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
            candidate = remaining[: limit + 1]
            line_boundary = remaining.rfind("\n", 0, limit + 1)
            contains_list_items = bool(
                re.search(r"(?:^|\n)[ \t]*(?:[•*-]|\d+[.)])[ \t]+", candidate)
            )
            if line_boundary > 0 and contains_list_items:
                boundary = line_boundary
        if boundary <= 0:
            candidate = remaining[: limit + 1]
            sentence_matches = list(
                re.finditer(r"""[.!?…]+(?:["'»”’)}\]]*)\s+""", candidate)
            )
            if sentence_matches:
                sentence_boundary = sentence_matches[-1].start()
                if sentence_boundary >= int(limit * 0.5):
                    boundary = sentence_boundary + len(
                        sentence_matches[-1].group(0).rstrip()
                    )
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


def _multipart_request(
    token: str,
    chat_id: str,
    message: dict,
    image_path: str | None,
    *,
    method: str = "sendRichMessage",
) -> None:
    """Отправить сообщение выбранным методом Bot API с необязательными вложениями."""
    if method not in {"sendMessage", "sendRichMessage"}:
        raise ValueError(f"Неподдерживаемый метод публикации: {method}")

    boundary = "----TelegramPublisher" + uuid.uuid4().hex
    body = bytearray()

    def add_field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"))
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    add_field("chat_id", chat_id)
    upload_files = message.pop("_upload_files", [])
    if method == "sendMessage":
        if message.get("media"):
            raise ValueError("Метод sendMessage не поддерживает поле media. Для обычного сообщения используй невидимую ссылку на публичный URL.")
        add_field("text", str(message.get("html", "")))
        add_field("parse_mode", "HTML")
    else:
        add_field("rich_message", json.dumps(message, ensure_ascii=False))

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

    for upload in upload_files:
        field = str(upload["field"])
        filename = str(upload["filename"])
        mime_type = str(upload["mime_type"])
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("ascii"))
        body.extend(upload["data"])
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("ascii"))
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Не удалось отправить сообщение методом {method}: {error}") from error
    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram отклонил сообщение методом {method}: "
            + str(result.get("description", "неизвестная ошибка"))
        )


def _plain_text_from_html(content: str) -> str:
    """Извлечь текст для проверки лимитов, не считая HTML-разметку."""
    soup = BeautifulSoup(content, "html.parser")
    for node in soup.find_all(["img", "video", "script", "style"]):
        node.decompose()
    for node in soup.find_all("br"):
        node.replace_with("\n")
    for node in soup.find_all(["p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"]):
        node.insert_after("\n")
    return soup.get_text().strip()


def _sanitize_plain_html(content: str, *, preserve_media: bool = False) -> str:
    """Оставить поддерживаемое Telegram форматирование и при необходимости медиа."""
    soup = BeautifulSoup(content, "html.parser")
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    # Таблицы переводятся в обычные текстовые строки вместо полной потери данных.
    for table in soup.find_all("table"):
        rows = soup.new_tag("div")
        for row in table.find_all("tr"):
            cells = [
                " ".join(cell.stripped_strings)
                for cell in row.find_all(["th", "td"], recursive=False)
            ]
            if cells:
                paragraph = soup.new_tag("p")
                paragraph.string = " | ".join(cells)
                rows.append(paragraph)
        if rows.contents:
            table.replace_with(rows)
        else:
            table.decompose()

    blocked_nodes = ["script", "style", "iframe"]
    if not preserve_media:
        blocked_nodes.extend(["img", "video"])
    for node in soup.find_all(blocked_nodes):
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
    if preserve_media:
        allowed.update({"img", "video"})
    for node in list(soup.find_all(True)):
        if node.name not in allowed:
            node.unwrap()
            continue
        if node.name in {"img", "video"}:
            source = str(node.get("src", "")).strip()
            if not source.lower().startswith(("https://", "http://", "data:image/")):
                node.decompose()
            else:
                node.attrs = {"src": source}
        elif node.name == "a":
            href = str(node.get("href", "")).strip()
            if not href.lower().startswith(("https://", "http://", "tg://", "mailto:")):
                node.unwrap()
            else:
                node.attrs = {"href": href}
        else:
            node.attrs = {}
    cleaned = soup.decode_contents().replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _rich_payload(
    text: str,
    image_path: str | None,
    *,
    rich_formatting: bool,
    invisible_media_link: bool = False,
) -> dict:
    """Сформировать HTML и список медиа для рич-сообщения."""
    body = text if rich_formatting else html.escape(text, quote=False)
    if rich_formatting:
        body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
        # Вспомогательная метка нужна редактору для обычного предпросмотра, но не Telegram.
        body = re.sub(
            r'\s+data-publication-media-preview=(["\'])video\1',
            "",
            body,
            flags=re.IGNORECASE,
        )
    media: list[dict] = []
    upload_files: list[dict] = []

    def replace_media(match: re.Match[str]) -> str:
        tag = match.group(0)
        source = re.search(r"""\bsrc\s*=\s*(['"])(.*?)\1""", tag, re.IGNORECASE | re.DOTALL)
        if not source:
            return ""
        url = html.unescape(source.group(2)).strip()
        media_type = "video" if tag.lower().startswith("<video") else "photo"
        media_id = f"publication_media_{len(media) + 1}"
        if url.lower().startswith(("https://", "http://")):
            media.append({"id": media_id, "media": {"type": media_type, "media": url}})
        elif media_type == "photo" and re.match(r"^data:image/(png|jpeg|jpg|gif|webp);base64,", url, re.I):
            header, encoded = url.split(",", 1)
            try:
                image_bytes = base64.b64decode(encoded, validate=True)
            except (ValueError, base64.binascii.Error):
                return ""
            subtype_match = re.match(r"^data:image/([^;]+)", header, re.I)
            if not subtype_match:
                return ""
            subtype = subtype_match.group(1).lower()
            mime_type = "image/jpeg" if subtype in {"jpg", "jpeg"} else f"image/{subtype}"
            extension = "jpg" if subtype in {"jpg", "jpeg"} else subtype
            field = f"inline_media_{len(upload_files) + 1}"
            upload_files.append({
                "field": field,
                "filename": f"{field}.{extension}",
                "mime_type": mime_type,
                "data": image_bytes,
            })
            media.append({"id": media_id, "media": {"type": "photo", "media": f"attach://{field}"}})
        else:
            return ""
        if invisible_media_link:
            target = "video" if media_type == "video" else "photo"
            return f'<a href="tg://{target}?id={media_id}">\u2063</a>'
        if media_type == "video":
            # В рич-сообщении видео должно ссылаться на зарегистрированное медиа через tg://.
            return f'<a href="tg://video?id={media_id}">\u200b\u200b\u200b</a>'
        return f'<img src="tg://photo?id={media_id}" alt="Изображение">'

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
    if upload_files:
        rich_message["_upload_files"] = upload_files
    return rich_message



def _plain_media_payload(content: str, image_path: str | None = None) -> dict | None:
    """Подготовить обычное сообщение с невидимой ссылкой на публичное медиа в конце."""
    soup = BeautifulSoup(content, "html.parser")
    media_nodes = list(soup.find_all(["img", "video"]))
    preview_anchors = list(soup.find_all("a", attrs={"data-publication-media-preview": "video"}))
    if len(media_nodes) + len(preview_anchors) > 1:
        raise ValueError("В одном обычном сообщении допускается только одно изображение или видео.")
    if (media_nodes or preview_anchors) and image_path:
        raise ValueError("В одном обычном сообщении допускается только одно медиа. Удали встроенное изображение или отдельный файл.")
    if not media_nodes and not preview_anchors and not image_path:
        return None
    if image_path and not media_nodes and not preview_anchors:
        raise ValueError(
            "Для обычного сообщения изображение или видео должно иметь публичный URL. "
            "Локальный файл можно отправить в режиме «Подпись к изображению» или «Рич-текст»."
        )
    if preview_anchors:
        source = str(preview_anchors[0].get("href", "")).strip()
        preview_anchors[0].decompose()
    else:
        source = str(media_nodes[0].get("src", "")).strip()
    if not source.lower().startswith(("https://", "http://")):
        raise ValueError(
            "Для обычного сообщения ссылка на медиа должна вести на публичный URL. "
            "Медиа без публичного HTTP(S)-адреса нельзя использовать для предпросмотра."
        )
    safe_html = _sanitize_plain_html(soup.decode_contents())
    result = BeautifulSoup(safe_html, "html.parser")
    media_anchor = result.new_tag("a", href=source)
    # Три символа нулевой ширины U+200B нужны для надёжного предпросмотра Telegram.
    media_anchor.string = "\u200B\u200B\u200B"
    if result.contents:
        result.append(result.new_string("\n\n"))
    result.append(media_anchor)
    return {"html": result.decode_contents()}


def _plain_send_options(message_html: str) -> dict:
    """Явно выбрать URL медиа для превью, не полагаясь на порядок ссылок в тексте."""
    soup = BeautifulSoup(message_html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        if anchor.get_text() != "\u200B\u200B\u200B":
            continue
        source = str(anchor.get("href", "")).strip()
        if source.lower().startswith(("https://", "http://")):
            return {"link_preview_options": LinkPreviewOptions(url=source)}
    return {}

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


def prepare_plain_messages(text: str, parts: list[str] | None = None) -> list[str]:
    """Подготовить точные значения поля text для обычных сообщений sendMessage."""
    text = text.strip()
    is_html = bool(re.search(r"</?(?:p|div|b|strong|i|em|u|s|strike|del|a|code|pre|blockquote|ul|ol|li|h[1-6]|img|video)\b", text, re.IGNORECASE))
    markup = text if is_html else html.escape(text, quote=False)
    visible_text = _plain_text_from_html(_sanitize_plain_html(markup))
    if parts:
        prepared_parts = [
            part if re.search(r"</?(?:p|div|b|strong|i|em|u|s|strike|del|a|code|pre|blockquote|ul|ol|li|h[1-6]|img|video)\b", part, re.IGNORECASE)
            else html.escape(part, quote=False)
            for part in parts
        ]
    elif len(visible_text) <= TEXT_LIMIT:
        prepared_parts = [markup]
    else:
        prepared_parts = [html.escape(part, quote=False) for part in split_text(visible_text, TEXT_LIMIT)]
    outgoing: list[str] = []
    for index, part in enumerate(prepared_parts, start=1):
        safe_part = _sanitize_plain_html(part)
        part_length = len(_plain_text_from_html(safe_part))
        if part_length > TEXT_LIMIT:
            raise ValueError(f"Пост {index} превышает лимит обычного сообщения Telegram ({TEXT_LIMIT} символов).")
        media_nodes = BeautifulSoup(part, "html.parser").find_all(["img", "video"])
        if len(media_nodes) > 1:
            raise ValueError(f"Пост {index}: в обычном сообщении допускается только одно изображение или видео.")
        payload = _plain_media_payload(part)
        outgoing.append(payload["html"] if payload else safe_part)
    return outgoing


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
        markup = text if re.search(
            r"</?(?:p|div|b|strong|i|em|u|s|strike|del|a|code|pre|blockquote|ul|ol|li|h[1-6]|img|video)\b",
            text,
            re.IGNORECASE,
        ) else html.escape(text, quote=False)
        visible_text = _plain_text_from_html(_sanitize_plain_html(markup))
        if len(visible_text) > TEXT_LIMIT and not series and not parts:
            raise ValueError("Обычное сообщение ограничено 4096 символами. Включи серию публикаций.")
        prepared_messages = prepare_plain_messages(text, parts or None)
        async with Bot(token=token) as bot:
            for message_html in prepared_messages:
                await bot.send_message(
                    chat_id=chat_id,
                    text=message_html,
                    parse_mode="HTML",
                    **_plain_send_options(message_html),
                )
        return len(prepared_messages)

    if mode == "plain_prepared":
        prepared_messages = [part for part in (parts or [text]) if part.strip()]
        if not prepared_messages:
            raise ValueError("Добавь текст перед отправкой.")
        for index, message_html in enumerate(prepared_messages, start=1):
            if len(_plain_text_from_html(message_html)) > TEXT_LIMIT:
                raise ValueError(f"Сообщение {index} превышает лимит обычного сообщения Telegram ({TEXT_LIMIT} символов).")
        async with Bot(token=token) as bot:
            for message_html in prepared_messages:
                await bot.send_message(
                    chat_id=chat_id,
                    text=message_html,
                    parse_mode="HTML",
                    **_plain_send_options(message_html),
                )
        return len(prepared_messages)

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
