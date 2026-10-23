"""Импорт публикаций из веб-страниц и локальных документов."""

from __future__ import annotations

import codecs
import html
import json
import ipaddress
import re
import socket
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

import markdown
from bs4 import BeautifulSoup, Tag
from charset_normalizer import from_bytes


MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
USER_AGENT = "TelegramPublisher/0.1 (+local post importer)"
ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "caption", "code", "del", "div", "em",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "li", "ol",
    "p", "pre", "s", "strike", "strong", "sub", "sup", "table", "tbody",
    "td", "th", "thead", "tr", "u", "ul", "video",
}
DROP_TAGS = {
    "script", "style", "noscript", "iframe", "svg", "canvas", "form",
    "button", "input", "select", "textarea", "nav", "footer", "header",
    "aside", "dialog", "template",
}


def _validate_public_url(url: str) -> str:
    """Проверить URL, не разрешая локальные и служебные адреса."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Укажи полный публичный URL, начинающийся с http:// или https://.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise ValueError("Локальные адреса не поддерживаются.")
    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            }
        except OSError as error:
            raise ValueError(f"Не удалось определить адрес сайта: {error}") from error
    if any(not address.is_global for address in addresses):
        raise ValueError("Импорт разрешён только с публичных веб-сайтов.")
    return parsed.geturl()


def _download(url: str) -> tuple[str, str]:
    """Загрузить веб-страницу с ограничением размера и времени ожидания."""
    url = _validate_public_url(url)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.5"})
    try:
        with urlopen(request, timeout=20) as response:
            final_url = _validate_public_url(response.geturl())
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
            content_type = response.headers.get_content_type()
    except (HTTPError, URLError, OSError, TimeoutError) as error:
        raise ValueError(f"Не удалось загрузить страницу: {error}") from error
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Страница слишком велика для импорта (лимит 12 МБ).")
    charset = response.headers.get_content_charset() if "response" in locals() else None
    try:
        content = data.decode(charset or "utf-8", errors="replace")
    except LookupError:
        content = data.decode("utf-8", errors="replace")
    return content, final_url


def _sanitize_html(content: str, base_url: str | None = None) -> str:
    """Оставить безопасное форматирование и превратить относительные ссылки в абсолютные."""
    soup = BeautifulSoup(content, "html.parser")
    for selector in (
        ".sharedaddy", ".sd-sharing", ".jp-share-print",
        ".wp-block-jetpack-sharing-buttons", ".wp-block-social-links",
        ".addtoany_share_save_container", ".heateor_sss_sharing_container",
        ".heateor_sss_sharing", ".post-share", ".post-sharing",
        ".social-share", ".social-sharing",
        "[class*='share-buttons']", "[class*='sharing-buttons']",
    ):
        for node in list(soup.select(selector)):
            node.decompose()
    for node in list(soup.find_all(DROP_TAGS)):
        node.decompose()
    for node in list(soup.find_all(True)):
        if not isinstance(node, Tag):
            continue
        if node.name == "img" and not node.get("src"):
            lazy_src = node.get("data-src") or node.get("data-lazy-src")
            if lazy_src:
                node["src"] = lazy_src
        if node.name not in ALLOWED_TAGS:
            node.unwrap()
            continue
        clean_attrs: dict[str, str] = {}
        for attr in ("href", "src", "alt", "title", "controls", "colspan", "rowspan"):
            value = node.get(attr)
            if value is None:
                continue
            if isinstance(value, list):
                value = " ".join(str(item) for item in value)
            value = str(value).strip()
            if attr in {"href", "src"}:
                if value.lower().startswith(("javascript:", "data:", "file:", "vbscript:")):
                    continue
                if base_url and attr in {"href", "src"}:
                    value = urljoin(base_url, value)
                if attr == "src" and not value.lower().startswith(("https://", "http://")):
                    continue
            clean_attrs[attr] = value
        node.attrs = clean_attrs
    for image in soup.find_all("img"):
        if not image.get("src"):
            lazy_src = image.get("data-src") or image.get("data-lazy-src")
            if lazy_src and base_url:
                image["src"] = urljoin(base_url, lazy_src)
        if not image.get("src"):
            image.decompose()
    return str(soup)


def convert_html(content: str, base_url: str | None = None) -> str:
    """Очистить HTML, сохранив разметку и публичные ссылки на медиа."""
    return _sanitize_html(content, base_url)


def convert_text(content: str) -> str:
    """Преобразовать обычный текст в абзацы."""
    paragraphs = re.split(r"\n\s*\n", content.replace("\r\n", "\n").replace("\r", "\n").strip())
    return "".join(f"<p>{html.escape(part).replace(chr(10), '<br>')}</p>" for part in paragraphs if part.strip())


def convert_markdown(content: str) -> str:
    """Преобразовать Markdown в HTML с поддержкой таблиц и списков."""
    rendered = markdown.markdown(content, extensions=["extra", "sane_lists"])
    return _sanitize_html(rendered)


def _page_title(content: str) -> str:
    """Извлечь заголовок публикации из HTML и метаданных страницы."""
    soup = BeautifulSoup(content, "html.parser")
    for selector in (
        ("meta", {"property": "og:title"}),
        ("meta", {"name": "twitter:title"}),
        ("meta", {"name": "title"}),
        ("h1", {}),
        ("title", {}),
    ):
        node = soup.find(selector[0], attrs=selector[1]) if selector[1] else soup.find(selector[0])
        if not node:
            continue
        value = node.get("content", "") if node.name == "meta" else node.get_text(" ", strip=True)
        title = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
        title = re.sub(r"\s+", " ", title).strip()
        if title:
            return title
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            if isinstance(entry, dict):
                title = str(entry.get("headline") or entry.get("name") or "").strip()
                if title:
                    return html.unescape(title)
    return ""


def _wordpress_content(url: str) -> str | None:
    """Получить содержимое записи WordPress вместе с заголовком."""
    parsed = urlparse(url)
    slug = unquote(parsed.path.rstrip("/").split("/")[-1])
    if not slug:
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}"
    for endpoint in ("posts", "pages"):
        api_url = f"{origin}/wp-json/wp/v2/{endpoint}?slug={quote(slug)}&context=view"
        try:
            payload, _ = _download(api_url)
            items = json.loads(payload)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(items, list) or not items:
            continue
        item = items[0]
        content = item.get("content", {}).get("rendered")
        if not content:
            continue
        title_data = item.get("title") or {}
        title = BeautifulSoup(
            str(title_data.get("rendered") or title_data.get("raw") or ""),
            "html.parser",
        ).get_text(" ", strip=True)
        if not title:
            seo = item.get("yoast_head_json") or item.get("rank_math_title") or {}
            if isinstance(seo, dict):
                title = str(seo.get("title") or seo.get("og_title") or "").strip()
        if not title:
            try:
                page_html, _ = _download(url)
                title = _page_title(page_html)
            except ValueError:
                pass
        if not title:
            title = re.sub(r"[-_]+", " ", unquote(str(item.get("slug") or slug))).strip().capitalize()
        title_html = f"<h1>{html.escape(title)}</h1>" if title else ""
        cleaned_content = _sanitize_html(content, url)
        if title and re.search(r"<h1\b[^>]*>\s*"+re.escape(html.escape(title))+r"\s*</h1\s*>", cleaned_content, re.I):
            title_html = ""
        return title_html + cleaned_content
    return None

def _extract_article(content: str, base_url: str) -> str:
    """Выделить основное содержимое HTML-страницы вместе с заголовком."""
    title = _page_title(content)
    soup = BeautifulSoup(content, "html.parser")
    for node in list(soup.find_all(DROP_TAGS)):
        node.decompose()
    candidates = [
        soup.find("article"),
        soup.find("main"),
        soup.find(attrs={"itemprop": "articleBody"}),
        soup.find(attrs={"class": re.compile(r"(post-content|entry-content|article-content|article-body|post-body|content__body)", re.I)}),
    ]
    source = next((candidate for candidate in candidates if candidate and candidate.get_text(" ", strip=True)), soup.body or soup)
    extracted = _sanitize_html(str(source), base_url)
    if title:
        escaped_title = html.escape(title)
        if not re.search(r"<h1\b[^>]*>\s*"+re.escape(escaped_title)+r"\s*</h1\s*>", extracted, re.I):
            extracted = f"<h1>{escaped_title}</h1>" + extracted
    return extracted


def import_from_url(url: str) -> str:
    """Импортировать WordPress-публикацию или содержимое обычной веб-страницы."""
    checked_url = _validate_public_url(url)
    wordpress = _wordpress_content(checked_url)
    if wordpress:
        return wordpress
    content, final_url = _download(checked_url)
    content_type = content.lower()
    if "<html" not in content_type and "<body" not in content_type:
        raise ValueError("По этой ссылке не обнаружена HTML-страница.")
    return _extract_article(content, final_url)


def _docx_html(path: Path) -> str:
    """Преобразовать текст DOCX, сохраняя абзацы и базовое форматирование."""
    from docx import Document
    from docx.oxml.ns import qn

    document = Document(path)
    output: list[str] = []
    for paragraph in document.paragraphs:
        text_parts: list[str] = []
        for run in paragraph.runs:
            value = html.escape(run.text).replace("\n", "<br>")
            if run.bold:
                value = f"<strong>{value}</strong>"
            if run.italic:
                value = f"<em>{value}</em>"
            if run.underline:
                value = f"<u>{value}</u>"
            text_parts.append(value)
        content = "".join(text_parts)
        for hyperlink in paragraph._p.xpath(".//w:hyperlink"):
            relation_id = hyperlink.get(qn("r:id"))
            if not relation_id or relation_id not in document.part.rels:
                continue
            target = document.part.rels[relation_id].target_ref
            label = "".join(node.text or "" for node in hyperlink.xpath(".//w:t"))
            if label and target:
                escaped_label = html.escape(label)
                link = f'<a href="{html.escape(target, quote=True)}">{escaped_label}</a>'
                if escaped_label in content:
                    content = content.replace(escaped_label, link, 1)
                else:
                    content += link
        if not content:
            continue
        style = paragraph.style.name.lower() if paragraph.style else ""
        if style.startswith("heading"):
            match = re.search(r"([1-6])", style)
            level = match.group(1) if match else "2"
            output.append(f"<h{level}>{content}</h{level}>")
        elif "list" in style:
            output.append(f"<p>• {content}</p>")
        else:
            output.append(f"<p>{content}</p>")
    return "".join(output)


def _odt_html(path: Path) -> str:
    """Преобразовать абзацы и заголовки ODT в HTML в исходном порядке."""
    from odf import teletype
    from odf.opendocument import load
    from odf.text import H, List, ListItem, P

    document = load(str(path))
    output: list[str] = []

    def walk(node: object) -> None:
        for child in getattr(node, "childNodes", []):
            qname = getattr(child, "qname", None)
            if qname in {H.qname, P.qname}:
                content = html.escape(teletype.extractText(child)).replace("\n", "<br>")
                if not content.strip():
                    continue
                if qname == H.qname:
                    level = getattr(child, "getAttribute")("outlinelevel") or "2"
                    level = str(max(1, min(6, int(level))))
                    output.append(f"<h{level}>{content}</h{level}>")
                else:
                    output.append(f"<p>{content}</p>")
            elif qname in {List.qname, ListItem.qname} or getattr(child, "childNodes", None):
                walk(child)

    walk(document.text)
    return "".join(output)

def _decode_text_file(path: Path) -> str:
    """Определить распространённую кодировку текстового файла."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass

    if data.startswith(codecs.BOM_UTF32_LE) or data.startswith(codecs.BOM_UTF32_BE):
        return data.decode("utf-32")
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return data.decode("utf-16")

    detected_text = None
    detected_coherence = 0.0
    try:
        detected = from_bytes(data).best()
        if detected is not None:
            detected_text = str(detected)
            detected_coherence = float(detected.coherence or 0.0)
    except (LookupError, ValueError):
        pass

    # Для коротких русскоязычных файлов детектор часто путает Windows-1251
    # с похожими однобайтовыми кодировками.
    try:
        cyrillic = data.decode("cp1251")
        cyrillic_score = sum("\u0400" <= char <= "\u04ff" for char in cyrillic) / max(len(cyrillic), 1)
        detected_score = (
            sum("\u0400" <= char <= "\u04ff" for char in detected_text) / max(len(detected_text), 1)
            if detected_text
            else 0.0
        )
        if cyrillic_score > 0.2 and cyrillic_score > detected_score + 0.03:
            return cyrillic
    except UnicodeDecodeError:
        pass

    if detected_text is not None and "\ufffd" not in detected_text and detected_coherence > 0:
        return detected_text

    for encoding in ("cp1250", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    if detected_text is not None:
        return detected_text
    raise ValueError("Не удалось определить кодировку текстового файла.")


def import_from_file(path: Path) -> str:
    """Импортировать текстовый, HTML, Markdown, DOCX или ODT-файл."""
    if not path.is_file():
        raise ValueError("Выбранный файл не найден.")
    if path.stat().st_size > MAX_DOWNLOAD_BYTES:
        raise ValueError("Файл слишком велик для импорта (лимит 12 МБ).")
    suffix = path.suffix.lower()
    if suffix in {".txt", ".text"}:
        return convert_text(_decode_text_file(path))
    if suffix in {".html", ".htm"}:
        return convert_html(_decode_text_file(path), path.resolve().as_uri())
    if suffix in {".md", ".markdown"}:
        return convert_markdown(_decode_text_file(path))
    if suffix == ".docx":
        return _docx_html(path)
    if suffix == ".odt":
        return _odt_html(path)
    raise ValueError(f"Формат файла {suffix or '(без расширения)'} не поддерживается.")
