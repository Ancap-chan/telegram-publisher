"""Импорт публикаций из веб-страниц и локальных документов."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

import markdown
from bs4 import BeautifulSoup, Tag


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
    for node in list(soup.find_all(DROP_TAGS)):
        node.decompose()
    for node in list(soup.find_all(True)):
        if not isinstance(node, Tag):
            continue
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


def _wordpress_content(url: str) -> str | None:
    """Попробовать получить содержимое записи или страницы через WordPress REST API."""
    parsed = urlparse(url)
    slug = unquote(parsed.path.rstrip("/").split("/")[-1])
    if not slug:
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}"
    for endpoint in ("posts", "pages"):
        api_url = f"{origin}/wp-json/wp/v2/{endpoint}?slug={quote(slug)}&context=view"
        try:
            payload, _ = _download(api_url)
            import json
            items = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if isinstance(items, list) and items:
            content = items[0].get("content", {}).get("rendered")
            if content:
                return _sanitize_html(content, url)
    return None


def _extract_article(content: str, base_url: str) -> str:
    """Выделить основное содержимое обычной HTML-страницы."""
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
    return _sanitize_html(str(source), base_url)


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
    # Гиперссылки Word хранятся в XML отдельно от обычных runs.
    for paragraph, block in zip(document.paragraphs, output):
        for hyperlink in paragraph._p.xpath(".//w:hyperlink"):
            relation_id = hyperlink.get(qn("r:id"))
            if not relation_id or relation_id not in document.part.rels:
                continue
            target = document.part.rels[relation_id].target_ref
            label = "".join(node.text or "" for node in hyperlink.xpath(".//w:t"))
            if label and target:
                block = block.replace(html.escape(label), f'<a href="{html.escape(target, quote=True)}">{html.escape(label)}</a>', 1)
        output[output.index(output[output.index(block)])] = block if block in output else block
    return "".join(output)


def _odt_html(path: Path) -> str:
    """Преобразовать абзацы и заголовки ODT в HTML."""
    from odf import teletype
    from odf.opendocument import load
    from odf.text import H, P

    document = load(str(path))
    output: list[str] = []
    for node in document.getElementsByType(H) + document.getElementsByType(P):
        content = html.escape(teletype.extractText(node)).replace("\n", "<br>")
        if not content.strip():
            continue
        if node.qname[1] == "h":
            level = node.getAttribute("outlinelevel") or "2"
            level = str(max(1, min(6, int(level))))
            output.append(f"<h{level}>{content}</h{level}>")
        else:
            output.append(f"<p>{content}</p>")
    return "".join(output)


def import_from_file(path: Path) -> str:
    """Импортировать текстовый, HTML, Markdown, DOCX или ODT-файл."""
    if not path.is_file():
        raise ValueError("Выбранный файл не найден.")
    if path.stat().st_size > MAX_DOWNLOAD_BYTES:
        raise ValueError("Файл слишком велик для импорта (лимит 12 МБ).")
    suffix = path.suffix.lower()
    if suffix in {".txt", ".text"}:
        return convert_text(path.read_text(encoding="utf-8-sig"))
    if suffix in {".html", ".htm"}:
        return convert_html(path.read_text(encoding="utf-8-sig"), path.resolve().as_uri())
    if suffix in {".md", ".markdown"}:
        return convert_markdown(path.read_text(encoding="utf-8-sig"))
    if suffix == ".docx":
        return _docx_html(path)
    if suffix == ".odt":
        return _odt_html(path)
    raise ValueError(f"Формат файла {suffix or '(без расширения)'} не поддерживается.")
