"""Базовые проверки структуры проекта."""

from importlib.metadata import version

from telegram_publisher import __version__


def test_package_version_matches_distribution_metadata() -> None:
    """Версия пакета должна совпадать с метаданными проекта."""
    assert __version__ == version("telegram-publisher")
