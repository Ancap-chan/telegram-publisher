"""Точка входа приложения."""

from telegram_publisher.editor import main as run_editor


def main() -> None:
    """Запустить визуальный редактор как главное окно приложения."""
    run_editor()


if __name__ == "__main__":
    main()
