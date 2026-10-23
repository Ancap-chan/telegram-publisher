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
    assert '<img src="tg://photo?id=publication_photo" alt="Изображение">' in payload["html"]



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
    assert '<img src="tg://photo?id=publication_media_1" alt="Изображение">' in payload["html"]
    assert '<video controls src="tg://video?id=publication_media_2"></video>' in payload["html"]
    assert payload["html"].count("</video>") == 1


def test_plain_html_preserves_telegram_supported_formatting_and_removes_media() -> None:
    from telegram_publisher.publishing import _sanitize_plain_html

    result = _sanitize_plain_html(
        '<p><strong>жирный</strong> и <a href="https://example.org">ссылка</a></p>'
        '<img src="https://example.org/image.jpg"><blockquote>цитата</blockquote>'
    )
    assert "<strong>жирный</strong>" in result
    assert '<a href="https://example.org">ссылка</a>' in result
    assert "<blockquote>цитата</blockquote>" in result
    assert "<img" not in result
    assert "<br" not in result


def test_plain_text_length_ignores_markup() -> None:
    from telegram_publisher.publishing import _plain_text_from_html

    assert len(_plain_text_from_html("<p><strong>текст</strong></p>")) == 5


def test_rich_payload_ignores_non_public_media_urls() -> None:
    from telegram_publisher.publishing import _rich_payload

    payload = _rich_payload('<img src="file:///private/photo.png">', None, rich_formatting=True)
    assert "media" not in payload
    assert payload["html"] == ""


def test_plain_media_payload_uses_invisible_link_to_public_image_url() -> None:
    from telegram_publisher.publishing import _plain_media_payload

    payload = _plain_media_payload(
        '<p><strong>Текст</strong></p><img src="https://example.org/image.jpg">'
    )
    assert payload is not None
    assert "media" not in payload
    assert '<strong>Текст</strong>' in payload["html"]
    assert '<a href="https://example.org/image.jpg">\u2063</a>' in payload["html"]
    assert "<img" not in payload["html"]


def test_plain_media_payload_rejects_multiple_media() -> None:
    from telegram_publisher.publishing import _plain_media_payload

    with pytest.raises(ValueError, match="только одно"):
        _plain_media_payload(
            '<img src="https://example.org/a.jpg"><video src="https://example.org/b.mp4"></video>'
        )


def test_plain_media_payload_supports_video_url() -> None:
    from telegram_publisher.publishing import _plain_media_payload

    payload = _plain_media_payload('<p>Текст</p><video controls src="https://example.org/movie.mp4"></video>')
    assert payload is not None
    assert "media" not in payload
    assert '<a href="https://example.org/movie.mp4">\u2063</a>' in payload["html"]


def test_plain_media_payload_rejects_data_uri_without_public_url() -> None:
    from telegram_publisher.publishing import _plain_media_payload

    with pytest.raises(ValueError, match="публичный URL"):
        _plain_media_payload('<img src="data:image/png;base64,aGVsbG8=">')


def test_plain_html_removes_html_comments() -> None:
    from telegram_publisher.publishing import _sanitize_plain_html

    result = _sanitize_plain_html('<p>Текст</p><!-- wp:paragraph --><p>Продолжение</p>')
    assert '<!--' not in result
    assert 'Продолжение' in result


def test_rich_payload_uploads_pasted_data_uri_image() -> None:
    from telegram_publisher.publishing import _rich_payload

    payload = _rich_payload(
        '<p>Текст</p><img src="data:image/png;base64,aGVsbG8=">',
        None,
        rich_formatting=True,
    )
    assert payload['media'][0]['media']['media'] == 'attach://inline_media_1'
    assert payload['_upload_files'][0]['field'] == 'inline_media_1'
    assert payload['_upload_files'][0]['data'] == b'hello'
    assert 'tg://photo?id=publication_media_1' in payload['html']


def test_plain_media_payload_keeps_image_outside_inline_formatting() -> None:
    from telegram_publisher.publishing import _plain_media_payload

    payload = _plain_media_payload(
        '<p><strong>До <img src="https://example.org/image.jpg"> после</strong></p>'
    )
    assert payload is not None
    assert "<strong>До </strong>" in payload["html"]
    assert '<a href="https://example.org/image.jpg">\u2063</a>' in payload["html"]
    assert "<strong> после</strong>" in payload["html"]
    assert "<strong>До <a " not in payload["html"]


def test_plain_media_payload_splits_formatting_around_media_reference() -> None:
    from telegram_publisher.publishing import _plain_media_payload

    payload = _plain_media_payload(
        '<p><strong>Жирный</strong> и <em>курсив <img src="https://example.org/image.jpg"> продолжение</em></p>'
    )
    assert payload is not None
    assert "<strong>Жирный</strong>" in payload["html"]
    assert "<em>курсив </em>" in payload["html"]
    assert '<a href="https://example.org/image.jpg">\u2063</a>' in payload["html"]
    assert "<em> продолжение</em>" in payload["html"]
    assert "<em>курсив <a " not in payload["html"]
    assert "data-publication-media-ref" not in payload["html"]


def test_plain_publication_sends_media_via_send_message(monkeypatch) -> None:
    import asyncio
    from telegram_publisher import publishing

    sent_messages = []

    class FakeBot:
        def __init__(self, token):
            self.token = token

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def send_message(self, **kwargs):
            sent_messages.append(kwargs)

    monkeypatch.setattr(publishing, "Bot", FakeBot)

    sent = asyncio.run(
        publishing.send_publication(
            "test-token",
            "@test-channel",
            '<p><strong>Текст</strong></p><img src="https://example.org/image.jpg">',
            mode="plain",
        )
    )

    assert sent == 1
    assert len(sent_messages) == 1
    assert sent_messages[0]["parse_mode"] == "HTML"
    assert '<strong>Текст</strong>' in sent_messages[0]["text"]
    assert '<a href="https://example.org/image.jpg">\u2063</a>' in sent_messages[0]["text"]
    assert "tg://photo" not in sent_messages[0]["text"]
