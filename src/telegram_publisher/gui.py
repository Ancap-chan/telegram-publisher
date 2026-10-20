"""Графический интерфейс Telegram Publisher."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from dotenv import load_dotenv

from telegram_publisher.publishing import TEXT_LIMIT, publish_sync, split_text


class PublisherWindow:
    """Главное окно приложения."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Telegram Publisher")
        self.root.geometry("820x680")
        self.root.minsize(620, 480)
        self.image_path: str | None = None
        self.send_in_progress = False

        load_dotenv(Path.cwd() / ".env")
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        self._build_interface()
        self._update_counter()

    def _build_interface(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(container)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Канал:", width=10).pack(side=tk.LEFT)
        channel_value = self.chat_id or "не указан в .env"
        ttk.Label(header, text=channel_value).pack(side=tk.LEFT)
        ttk.Button(header, text="Вставить из буфера", command=self._paste_clipboard).pack(side=tk.RIGHT)

        ttk.Label(container, text="Текст публикации").pack(anchor=tk.W, pady=(14, 4))
        self.text = tk.Text(container, wrap=tk.WORD, undo=True, font=("Segoe UI", 11), height=18)
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.bind("<<Modified>>", self._on_text_modified)
        self.text.edit_modified(False)

        controls = ttk.Frame(container)
        controls.pack(fill=tk.X, pady=(8, 0))
        self.counter = ttk.Label(controls, text="")
        self.counter.pack(side=tk.LEFT)
        ttk.Button(controls, text="Выбрать изображение…", command=self._choose_image).pack(side=tk.RIGHT)
        self.image_label = ttk.Label(container, text="Изображение не выбрано")
        self.image_label.pack(anchor=tk.W, pady=(6, 0))

        bottom = ttk.Frame(container)
        bottom.pack(fill=tk.X, pady=(14, 0))
        self.status = ttk.Label(bottom, text="Готово к работе")
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.send_button = ttk.Button(bottom, text="Опубликовать", command=self._send)
        self.send_button.pack(side=tk.RIGHT)

    def _paste_clipboard(self) -> None:
        try:
            content = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Буфер обмена", "В буфере обмена нет доступного текста.")
            return
        self.text.insert(tk.INSERT, content)
        self._update_counter()

    def _choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Выбрать изображение",
            filetypes=[
                ("Изображения", "*.png *.jpg *.jpeg *.webp"),
                ("Все файлы", "*.*"),
            ],
        )
        if path:
            self.image_path = path
            self.image_label.configure(text=Path(path).name)

    def _on_text_modified(self, _event: tk.Event) -> None:
        if self.text.edit_modified():
            self._update_counter()
            self.text.edit_modified(False)

    def _update_counter(self) -> None:
        content = self.text.get("1.0", "end-1c").strip()
        limit = 1024 if self.image_path else TEXT_LIMIT
        parts = split_text(content, limit)
        self.counter.configure(
            text=f"{len(content)} символов · частей текста: {len(parts)}"
            + (f" · подпись к изображению: до {limit}" if self.image_path else "")
        )

    def _send(self) -> None:
        if self.send_in_progress:
            return
        if not self.token or not self.chat_id:
            messagebox.showerror(
                "Настройки не заполнены",
                "Заполни TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в файле .env рядом с запуском приложения.",
            )
            return

        content = self.text.get("1.0", "end-1c").strip()
        if not content and not self.image_path:
            messagebox.showwarning("Пустая публикация", "Добавь текст или выбери изображение.")
            return

        message_count = len(split_text(content, 1024 if self.image_path else TEXT_LIMIT))
        if self.image_path:
            message_count += 1
        if not messagebox.askyesno(
            "Подтверждение публикации",
            f"Отправить публикацию в {self.chat_id}?\nБудет отправлено сообщений: {message_count}.",
        ):
            return

        self.send_in_progress = True
        self.send_button.configure(state=tk.DISABLED)
        self.status.configure(text="Отправка…")
        thread = threading.Thread(
            target=self._send_in_background,
            args=(content, self.image_path),
            daemon=True,
        )
        thread.start()

    def _send_in_background(self, content: str, image_path: str | None) -> None:
        try:
            count = publish_sync(self.token, self.chat_id, content, image_path)
        except Exception as error:
            self.root.after(0, self._send_failed, str(error))
            return
        self.root.after(0, self._send_succeeded, count)

    def _send_failed(self, error: str) -> None:
        self.send_in_progress = False
        self.send_button.configure(state=tk.NORMAL)
        self.status.configure(text="Не удалось отправить публикацию")
        messagebox.showerror("Ошибка публикации", error)

    def _send_succeeded(self, count: int) -> None:
        self.send_in_progress = False
        self.send_button.configure(state=tk.NORMAL)
        self.status.configure(text=f"Опубликовано. Отправлено сообщений: {count}")
        messagebox.showinfo("Публикация завершена", f"Отправлено сообщений: {count}")


def run_app() -> None:
    """Создать и запустить главное окно."""
    root = tk.Tk()
    PublisherWindow(root)
    root.mainloop()
