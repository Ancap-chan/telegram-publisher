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
