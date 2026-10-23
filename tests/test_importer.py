"""Проверки импорта веб-страниц и локальных документов."""

from pathlib import Path

import pytest

from telegram_publisher.importer import (
    convert_html,
    convert_markdown,
    convert_text,
    import_from_file,
    _validate_public_url,
)


def test_plain_text_becomes_paragraphs() -> None:
    assert convert_text("Первый абзац\n\nВторой <текст>") == (
        "<p>Первый абзац</p><p>Второй &lt;текст&gt;</p>"
    )


def test_markdown_preserves_formatting_and_lists() -> None:
    result = convert_markdown("# Заголовок\n\n**жирный**\n\n- один\n- два")
    assert "<h1>Заголовок</h1>" in result
    assert "<strong>жирный</strong>" in result
    assert "<li>один</li>" in result
    assert "<li>два</li>" in result


def test_html_removes_scripts_and_keeps_absolute_media() -> None:
    result = convert_html(
        '<script>alert(1)</script><p>Текст</p><img src="/media/pic.jpg">',
        "https://example.org/article/",
    )
    assert "alert(1)" not in result
    assert '<img src="https://example.org/media/pic.jpg">' in result
    assert "<p>Текст</p>" in result


def test_text_file_import(tmp_path: Path) -> None:
    path = tmp_path / "post.txt"
    path.write_text("Первая строка\n\nВторая строка", encoding="utf-8")
    assert import_from_file(path) == "<p>Первая строка</p><p>Вторая строка</p>"


def test_markdown_file_import(tmp_path: Path) -> None:
    path = tmp_path / "post.md"
    path.write_text("**важно**", encoding="utf-8")
    assert "<strong>важно</strong>" in import_from_file(path)


def test_unsupported_file_type_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "post.pdf"
    path.write_text("не поддерживается", encoding="utf-8")
    with pytest.raises(ValueError, match="не поддерживается"):
        import_from_file(path)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://localhost/page", "https://"])
def test_non_public_or_invalid_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        _validate_public_url(url)
