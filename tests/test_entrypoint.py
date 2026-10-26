"""Проверки точки входа приложения."""

from telegram_publisher import __main__ as entrypoint


def test_main_starts_visual_editor(monkeypatch):
    calls = []
    monkeypatch.setattr(entrypoint, "run_editor", lambda: calls.append("запуск"))

    entrypoint.main()

    assert calls == ["запуск"]
