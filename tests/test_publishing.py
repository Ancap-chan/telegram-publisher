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
    assert '<a href="tg://video?id=publication_media_2">\u200b\u200b\u200b</a>' in payload["html"]
    assert "<video" not in payload["html"]


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
    payload = _plain_media_payload('<p><strong>Текст</strong></p><img src="https://example.org/image.jpg">')
    assert payload is not None
    assert "media" not in payload
    assert '<strong>Текст</strong>' in payload["html"]
    assert payload["html"].endswith('<a href="https://example.org/image.jpg">\u200b\u200b\u200b</a>')
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
    assert payload["html"].endswith('<a href="https://example.org/movie.mp4">\u200b\u200b\u200b</a>')

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
    payload = _plain_media_payload('<p><strong>До <img src="https://example.org/image.jpg"> после</strong></p>')
    assert payload is not None
    assert "<strong>До  после</strong>" in payload["html"]
    assert payload["html"].endswith('<a href="https://example.org/image.jpg">\u200b\u200b\u200b</a>')
    assert "<img" not in payload["html"]

def test_plain_media_payload_moves_media_reference_after_formatted_text() -> None:
    from telegram_publisher.publishing import _plain_media_payload
    payload = _plain_media_payload('<p><strong>Жирный</strong> и <em>курсив <img src="https://example.org/image.jpg"> продолжение</em></p>')
    assert payload is not None
    assert "<strong>Жирный</strong>" in payload["html"]
    assert "<em>курсив  продолжение</em>" in payload["html"]
    assert payload["html"].endswith('<a href="https://example.org/image.jpg">\u200b\u200b\u200b</a>')
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
    assert sent_messages[0]["text"].endswith('<a href="https://example.org/image.jpg">\u200b\u200b\u200b</a>')
    assert sent_messages[0]["link_preview_options"].url == "https://example.org/image.jpg"
    assert "tg://photo" not in sent_messages[0]["text"]



def test_prepare_plain_messages_returns_exact_send_message_text() -> None:
    from telegram_publisher.publishing import prepare_plain_messages

    payloads = prepare_plain_messages(
        '<p><strong>Текст</strong></p><img src="https://example.org/image.jpg">'
    )

    assert payloads == [
        '<strong>Текст</strong>\n\n<a href="https://example.org/image.jpg">\u200b\u200b\u200b</a>'
    ]


def test_plain_prepared_publication_sends_reviewed_text_unchanged(monkeypatch) -> None:
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
    reviewed_text = '<strong>Финальный текст</strong><a href="https://example.org/image.jpg">\u200b\u200b\u200b</a>'

    sent = asyncio.run(
        publishing.send_publication(
            "test-token",
            "@test-channel",
            "исходный текст",
            mode="plain_prepared",
            parts=[reviewed_text],
        )
    )

    assert sent == 1
    assert sent_messages == [
        {
            "chat_id": "@test-channel",
            "text": reviewed_text,
            "parse_mode": "HTML",
            "read_timeout": 60,
            "write_timeout": 60,
            "connect_timeout": 15,
            "pool_timeout": 15,
            "link_preview_options": __import__("telegram").LinkPreviewOptions(url="https://example.org/image.jpg"),
        }
    ]



def test_plain_paragraphs_are_separated_by_one_blank_line() -> None:
    from telegram_publisher.publishing import _sanitize_plain_html
    result = _sanitize_plain_html("<p>Абзац 1</p><div><p>Абзац 2</p></div><p>Абзац 3</p>")
    assert result == "Абзац 1\n\nАбзац 2\n\nАбзац 3"


def test_plain_send_options_select_the_media_url_even_when_other_links_precede_it() -> None:
    from telegram_publisher.publishing import _plain_send_options
    options = _plain_send_options(
        '<a href="https://example.org/article">Ссылка на статью</a>\n\n'
        '<a href="https://example.org/image.jpg">\u200b\u200b\u200b</a>'
    )
    assert options["link_preview_options"].url == "https://example.org/image.jpg"


def test_split_prefers_sentence_boundaries_for_oversized_paragraph() -> None:
    text = "Первое предложение. Второе предложение. Третье предложение."
    parts = split_text(text, limit=32)
    assert parts == ["Первое предложение.", "Второе предложение.", "Третье предложение."]
    assert all(len(part) <= 32 for part in parts)


def test_split_long_list_text_at_item_boundaries() -> None:
    text = "• Первый пункт\n• Второй пункт\n• Третий пункт"
    assert split_text(text, limit=20) == [
        "• Первый пункт",
        "• Второй пункт",
        "• Третий пункт",
    ]


def test_plain_html_converts_tables_to_text_rows() -> None:
    from telegram_publisher.publishing import _sanitize_plain_html

    result = _sanitize_plain_html(
        "<table><tr><th>Имя</th><th>Роль</th></tr>"
        "<tr><td>Анна</td><td>Автор</td></tr></table>"
    )
    assert "Имя | Роль" in result
    assert "Анна | Автор" in result
    assert "<table" not in result

def test_plain_text_length_counts_table_cells() -> None:
    from telegram_publisher.publishing import _plain_text_from_html

    assert _plain_text_from_html("<table><tr><td>Имя</td><td>Роль</td></tr></table>") == "ИмяРоль"

def test_plain_media_payload_converts_video_site_link_to_hidden_preview_link() -> None:
    from telegram_publisher.publishing import _plain_media_payload, _plain_send_options

    payload = _plain_media_payload(
        '<p>Текст публикации</p><p><a href="https://youtu.be/example" '
        'data-publication-media-preview="video">https://youtu.be/example</a></p>'
    )
    assert payload is not None
    assert "https://youtu.be/example</a>" not in payload["html"]
    assert payload["html"].endswith(
        '<a href="https://youtu.be/example">\u200b\u200b\u200b</a>'
    )
    assert _plain_send_options(payload["html"])["link_preview_options"].url == "https://youtu.be/example"




def test_series_sends_messages_sequentially_with_extended_timeouts() -> None:
    import asyncio
    from telegram_publisher.publishing import (
        SEND_CONNECT_TIMEOUT,
        SEND_POOL_TIMEOUT,
        SEND_READ_TIMEOUT,
        SEND_WRITE_TIMEOUT,
        _send_plain_messages_sequentially,
    )

    calls = []

    class FakeBot:
        async def send_message(self, **kwargs):
            calls.append(kwargs)

    sent = asyncio.run(
        _send_plain_messages_sequentially(
            FakeBot(),
            "@test-channel",
            ["Первый пост", "Второй пост", "Третий пост"],
        )
    )

    assert sent == 3
    assert [call["text"] for call in calls] == [
        "Первый пост",
        "Второй пост",
        "Третий пост",
    ]
    assert all(call["read_timeout"] == SEND_READ_TIMEOUT == 60 for call in calls)
    assert all(call["write_timeout"] == SEND_WRITE_TIMEOUT == 60 for call in calls)
    assert all(call["connect_timeout"] == SEND_CONNECT_TIMEOUT == 15 for call in calls)
    assert all(call["pool_timeout"] == SEND_POOL_TIMEOUT == 15 for call in calls)


def test_series_stops_after_unconfirmed_message_and_reports_partial_progress() -> None:
    import asyncio
    from telegram_publisher.publishing import _send_plain_messages_sequentially

    calls = []

    class FakeBot:
        async def send_message(self, **kwargs):
            calls.append(kwargs["text"])
            if kwargs["text"] == "Второй пост":
                raise TimeoutError("ожидание ответа истекло")

    with pytest.raises(RuntimeError, match="Подтверждённо отправлено предыдущих сообщений: 1"):
        asyncio.run(
            _send_plain_messages_sequentially(
                FakeBot(),
                "@test-channel",
                ["Первый пост", "Второй пост", "Третий пост"],
            )
        )

    assert calls == ["Первый пост", "Второй пост"]

def test_plain_series_waits_between_messages_and_returns_pending_after_flood(monkeypatch) -> None:
    import asyncio

    from telegram.error import RetryAfter

    from telegram_publisher import publishing

    messages = ["Первый пост", "Второй пост", "Третий пост"]
    attempts: list[str] = []
    delays: list[float] = []

    class FakeBot:
        def __init__(self, token):
            self.token = token

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def send_message(self, **kwargs):
            attempts.append(kwargs["text"])
            if kwargs["text"] == messages[1]:
                raise RetryAfter(36)

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(publishing, "Bot", FakeBot)
    monkeypatch.setattr(publishing.asyncio, "sleep", fake_sleep)

    with pytest.raises(publishing.PartialPublicationError) as caught:
        asyncio.run(
            publishing.send_publication(
                "test-token",
                "@test-channel",
                messages[0],
                mode="plain_prepared",
                parts=messages,
            )
        )

    error = caught.value
    assert error.sent_count == 1
    assert error.pending_messages == messages[1:]
    assert error.retry_after == 36
    assert attempts == messages[:2]
    assert delays == [publishing.SERIES_SEND_INTERVAL]



def test_album_media_uses_photo_video_and_shared_formatted_caption() -> None:
    from telegram import InputMediaPhoto, InputMediaVideo

    from telegram_publisher.publishing import _prepare_album_media

    media = _prepare_album_media(
        '<p><strong>Общая подпись</strong></p>'
        '<img src="https://example.org/one.jpg">'
        '<video src="https://example.org/two.mp4"></video>'
    )

    assert len(media) == 2
    assert isinstance(media[0], InputMediaPhoto)
    assert isinstance(media[1], InputMediaVideo)
    assert media[0].media == "https://example.org/one.jpg"
    assert media[1].media == "https://example.org/two.mp4"
    assert media[0].caption == "<strong>Общая подпись</strong>"
    assert media[0].parse_mode == "HTML"
    assert media[1].caption is None


@pytest.mark.parametrize(
    "content, message",
    [
        ('<img src="https://example.org/one.jpg">', "от 2 до 10"),
        (
            '<img src="https://example.org/one.jpg">'
            + "".join(
                f'<img src="https://example.org/{index}.jpg">'
                for index in range(10)
            ),
            "от 2 до 10",
        ),
        (
            '<p>' + ("а" * 1025) + '</p>'
            '<img src="https://example.org/one.jpg">'
            '<img src="https://example.org/two.jpg">',
            "1024 символ",
        ),
        (
            '<img src="data:image/png;base64,aGVsbG8;">'
            '<img src="https://example.org/two.jpg">',
            "прямого публичного HTTP",
        ),
    ],
)
def test_album_rejects_invalid_media_or_caption(content: str, message: str) -> None:
    from telegram_publisher.publishing import _prepare_album_media

    with pytest.raises(ValueError, match=message):
        _prepare_album_media(content)


def test_album_publication_sends_media_group(monkeypatch) -> None:
    import asyncio

    from telegram import InputMediaPhoto, InputMediaVideo

    from telegram_publisher import publishing

    calls = []

    class FakeBot:
        def __init__(self, token):
            self.token = token

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def send_media_group(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(publishing, "Bot", FakeBot)
    sent = asyncio.run(
        publishing.send_publication(
            "test-token",
            "@test-channel",
            '<p>Подпись</p>'
            '<img src="https://example.org/one.jpg">'
            '<video src="https://example.org/two.mp4"></video>',
            mode="album",
        )
    )

    assert sent == 2
    assert len(calls) == 1
    assert calls[0]["chat_id"] == "@test-channel"
    assert len(calls[0]["media"]) == 2
    assert isinstance(calls[0]["media"][0], InputMediaPhoto)
    assert isinstance(calls[0]["media"][1], InputMediaVideo)


def test_album_message_count_matches_number_of_media_items() -> None:
    from telegram_publisher.publishing import estimate_message_count

    content = (
        '<p>Подпись</p>'
        '<img src="https://example.org/one.jpg">'
        '<video src="https://example.org/two.mp4"></video>'
    )
    assert estimate_message_count(content, None, "album") == 2
