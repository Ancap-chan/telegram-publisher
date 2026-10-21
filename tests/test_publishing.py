"""Проверки подготовки текста публикации."""

import pytest

from telegram_publisher.publishing import split_text


def test_empty_text_returns_no_parts() -> None:
    assert split_text("") == []
    assert split_text("   \n ") == []


def test_short_text_stays_in_one_part() -> None:
    assert split_text("Тестовая публикация") == ["Тестовая публикация"]


def test_long_text_is_split_without_losing_content() -> None:
    text = "абвг " * 30
    parts = split_text(text, limit=20)
    assert len(parts) > 1
    assert all(len(part) <= 20 for part in parts)
    assert " ".join(parts).replace("  ", " ").strip() == text.strip()


def test_split_prefers_paragraph_boundaries() -> None:
    text = "Первый абзац.\n\nВторой абзац."
    assert split_text(text, limit=20) == ["Первый абзац.", "Второй абзац."]


def test_non_positive_limit_is_rejected() -> None:
    with pytest.raises(ValueError):
        split_text("текст", limit=0)



def test_rich_message_limit_is_explicit() -> None:
    from telegram_publisher.publishing import RICH_TEXT_LIMIT

    assert RICH_TEXT_LIMIT == 32768


def test_estimate_caption_and_series_counts() -> None:
    from telegram_publisher.publishing import estimate_message_count

    assert estimate_message_count("коротко", "photo.png", "caption") == 1
    assert estimate_message_count("а" * 1500, "photo.png", "caption", True) == 2
    assert estimate_message_count("а" * 5000, None, "plain_series", True) == 2


def test_plain_rich_payload_escapes_html() -> None:
    from telegram_publisher.publishing import _rich_payload

    payload = _rich_payload("<текст> & данные", None, rich_formatting=False)
    assert payload["html"] == "&lt;текст&gt; &amp; данные"


def test_rich_payload_references_uploaded_image() -> None:
    from telegram_publisher.publishing import _rich_payload

    payload = _rich_payload("Текст", "photo.png", rich_formatting=False)
    assert payload["media"][0]["media"]["media"] == "attach://photo"
    assert "tg://photo?id=publication_photo" in payload["html"]



def test_rich_payload_converts_public_media_urls() -> None:
    from telegram_publisher.publishing import _rich_payload

    payload = _rich_payload(
        '<p>Текст</p><img src="https://example.org/picture.jpg">'
        '<video controls src="https://example.org/movie.mp4"></video>',
        None,
        rich_formatting=True,
    )
    assert payload["media"][0]["media"] == {
        "type": "photo",
        "media": "https://example.org/picture.jpg",
    }
    assert payload["media"][1]["media"] == {
        "type": "video",
        "media": "https://example.org/movie.mp4",
    }
    assert "tg://photo?id=publication_media_1" in payload["html"]
    assert "tg://video?id=publication_media_2" in payload["html"]


def test_rich_payload_ignores_non_public_media_urls() -> None:
    from telegram_publisher.publishing import _rich_payload

    payload = _rich_payload('<img src="file:///private/photo.png">', None, rich_formatting=True)
    assert "media" not in payload
    assert payload["html"] == ""
