"""Проверки прикладного контроллера и состояния публикации."""

from __future__ import annotations

import pytest

from telegram_publisher.controller import (
    PublicationController,
    PublicationRequest,
    PublicationSession,
)
from telegram_publisher.profiles import ChannelProfile
from telegram_publisher.publishing import PartialPublicationError


@pytest.fixture
def profile() -> ChannelProfile:
    return ChannelProfile("profile-1", "Тестовый канал", "@test_channel", "секрет")


def test_controller_passes_publication_arguments(profile: ChannelProfile) -> None:
    received = {}

    def publisher(*args, **kwargs):
        received["args"] = args
        received["kwargs"] = kwargs
        return 3

    request = PublicationRequest(
        profile=profile,
        content="<p>Текст</p>",
        image_path="image.png",
        mode="rich_series",
        series=True,
        parts=["Часть 1", "Часть 2"],
        initial_delay=2.5,
    )

    assert PublicationController(publisher).publish(request) == 3
    assert received["args"] == (
        "секрет",
        "@test_channel",
        "<p>Текст</p>",
        "image.png",
        "rich_series",
        True,
    )
    assert received["kwargs"] == {
        "parts": ["Часть 1", "Часть 2"],
        "initial_delay": 2.5,
    }


def test_controller_propagates_publication_errors(profile: ChannelProfile) -> None:
    error = RuntimeError("Ошибка Telegram")

    def publisher(*_args, **_kwargs):
        raise error

    with pytest.raises(RuntimeError, match="Ошибка Telegram") as raised:
        PublicationController(publisher).publish(
            PublicationRequest(profile, "Текст", None, "plain", False)
        )

    assert raised.value is error


def test_controller_preserves_partial_publication_error(profile: ChannelProfile) -> None:
    error = PartialPublicationError(2, ["третье сообщение"], 4.0)

    def publisher(*_args, **_kwargs):
        raise error

    with pytest.raises(PartialPublicationError) as raised:
        PublicationController(publisher).publish(
            PublicationRequest(profile, "Текст", None, "plain_series", True)
        )

    assert raised.value is error


def test_session_records_partial_publication() -> None:
    session = PublicationSession()
    error = PartialPublicationError(2, ["часть 3"], 4.0)

    assert session.record_partial(error) == 2
    assert session.pending_messages == ["часть 3"]
    assert session.pending_sent_count == 2
    assert session.pending_retry_after == 5.0
    assert not session.send_in_progress


def test_session_accumulates_count_when_retry_is_interrupted() -> None:
    session = PublicationSession(
        pending_messages=["часть 3"],
        pending_sent_count=2,
        resuming_pending=True,
    )

    assert session.record_partial(PartialPublicationError(1, ["часть 4"], 6.0)) == 3
    assert session.pending_messages == ["часть 4"]
    assert session.pending_sent_count == 3
    assert not session.resuming_pending


def test_session_prepares_retry_without_mutating_input() -> None:
    session = PublicationSession(pending_messages=["старое сообщение"])
    messages = ["исправленная часть 1", "исправленная часть 2"]

    session.prepare_retry(messages)
    messages.clear()

    assert session.pending_messages == []
    assert session.finalized_plain_parts == [
        "исправленная часть 1",
        "исправленная часть 2",
    ]
    assert session.publishing_from_editor
    assert session.resuming_pending


def test_session_completes_retry_and_resets_queue() -> None:
    session = PublicationSession(
        pending_messages=["остаток"],
        pending_sent_count=4,
        pending_retry_after=7.0,
        resuming_pending=True,
        send_in_progress=True,
    )

    assert session.complete(2) == 6
    assert not session.send_in_progress
    assert not session.resuming_pending
    assert session.pending_messages == []
    assert session.pending_sent_count == 0
    assert session.pending_retry_after == 0.0


def test_session_failure_keeps_pending_queue() -> None:
    session = PublicationSession(
        pending_messages=["остаток"],
        pending_sent_count=2,
        send_in_progress=True,
    )

    session.mark_failed()

    assert not session.send_in_progress
    assert session.pending_messages == ["остаток"]
    assert session.pending_sent_count == 2
