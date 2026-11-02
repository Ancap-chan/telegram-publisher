"""Проверки импорта веб-страниц и локальных документов."""

from pathlib import Path

import json

import pytest

import telegram_publisher.importer as importer
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
    assert 'src="https://example.org/media/pic.jpg"' in result
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



def test_cp1251_text_file_import(tmp_path: Path) -> None:
    path = tmp_path / "post.txt"
    path.write_bytes("Привет, мир!".encode("cp1251"))
    assert import_from_file(path) == "<p>Привет, мир!</p>"


def test_wordpress_title_falls_back_to_page_heading(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_download(url: str) -> tuple[str, str]:
        if "/wp-json/wp/v2/posts?" in url:
            return (json.dumps([{
                "title": {"rendered": ""},
                "content": {"rendered": "<p>Основной текст</p>"},
            }], ensure_ascii=False), url)
        if url == "https://example.org/post/":
            return ('<html><head><title>Заголовок со страницы</title></head><body><h1>Заголовок со страницы</h1></body></html>', url)
        return "[]", url

    monkeypatch.setattr(importer, "_validate_public_url", lambda url: url)
    monkeypatch.setattr(importer, "_download", fake_download)
    result = importer._wordpress_content("https://example.org/post/")
    assert "<h1>Заголовок со страницы</h1>" in result


def test_wordpress_import_includes_title_and_removes_social_sharing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_download(url: str) -> tuple[str, str]:
        if "/wp-json/wp/v2/posts?" in url:
            return (
                json.dumps([{
                    "title": {"rendered": "Заголовок публикации"},
                    "content": {"rendered": "<p>Основной текст</p><div class='sharedaddy'><a href='#'>Поделиться</a></div>"},
                }], ensure_ascii=False),
                url,
            )
        return "[]", url

    monkeypatch.setattr(importer, "_validate_public_url", lambda url: url)
    monkeypatch.setattr(importer, "_download", fake_download)
    result = importer._wordpress_content("https://example.org/post/")

    assert "<h1>Заголовок публикации</h1>" in result
    assert "<p>Основной текст</p>" in result
    assert "Поделиться" not in result


def test_wordpress_title_falls_back_to_slug_when_page_has_no_title(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_download(url: str) -> tuple[str, str]:
        if "/wp-json/wp/v2/posts?" in url:
            return (json.dumps([{
                "slug": "testovaya-zapis",
                "title": {"rendered": ""},
                "content": {"rendered": "<p>Основной текст</p>"},
            }], ensure_ascii=False), url)
        return "<html><body><article><p>Основной текст</p></article></body></html>", url

    monkeypatch.setattr(importer, "_validate_public_url", lambda url: url)
    monkeypatch.setattr(importer, "_download", fake_download)
    result = importer._wordpress_content("https://example.org/testovaya-zapis/")
    assert "<h1>Testovaya zapis</h1>" in result


def test_html_import_removes_unsupported_presentation_but_keeps_text_and_supported_formatting() -> None:
    result = convert_html(
        '<p style="font-family: Papyrus; color: red; text-align: center">'
        '<span style="font-size: 32px">Обычный </span><strong>жирный</strong>'
        '<font face="Comic Sans"> текст</font></p>'
    )
    assert "Обычный" in result
    assert "<strong>жирный</strong>" in result
    assert "текст" in result
    assert "Papyrus" not in result
    assert "Comic Sans" not in result
    assert "style=" not in result
    assert "<font" not in result
    assert "<span" not in result


def test_html_import_preserves_rich_html_features_and_supported_attributes() -> None:
    result = convert_html(
        '<blockquote expandable>Цитата</blockquote>'
        '<table bordered striped compact><tr><th>Заголовок</th>'
        '<td align="right" valign="middle" colspan="2">Значение</td></tr></table>'
        '<details open><summary>Подробнее</summary><p>Текст</p></details>'
        '<p><tg-spoiler>Секрет</tg-spoiler><tg-math-block>x^2</tg-math-block></p>'
    )
    assert '<blockquote expandable>' in result
    assert '<table bordered striped compact>' in result
    assert 'align="right"' in result
    assert 'valign="middle"' in result
    assert 'colspan="2"' in result
    assert '<details open>' in result
    assert '<tg-spoiler>Секрет</tg-spoiler>' in result
    assert '<tg-math-block>x^2</tg-math-block>' in result


def test_html_import_removes_unsupported_tags_without_losing_their_text() -> None:
    result = convert_html(
        '<div class="layout"><p>До</p><custom-widget>Содержимое</custom-widget><p>После</p></div>'
        '<script>опасный код</script>'
    )
    assert '<p>До</p>' in result
    assert 'Содержимое' in result
    assert '<custom-widget' not in result
    assert 'layout' not in result
    assert 'опасный код' not in result


def test_html_import_rejects_unsupported_attribute_values() -> None:
    result = convert_html(
        '<a href="javascript:alert(1)">Опасная ссылка</a>'
        '<table><tr><td align="justify" valign="baseline">Ячейка</td></tr></table>'
    )
    assert 'javascript:' not in result
    assert 'align="justify"' not in result
    assert 'valign="baseline"' not in result
