"""Точка входа приложения."""

import sys

from telegram_publisher.gui import run_app


def main() -> None:
    """Запустить приложение или отдельный процесс визуального редактора."""
    if len(sys.argv) > 1 and sys.argv[1] == "--editor":
        from telegram_publisher.editor import main as editor_main

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        editor_main()
        return

    run_app()


if __name__ == "__main__":
    main()
