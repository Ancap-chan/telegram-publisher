"""Графический интерфейс Telegram Publisher."""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from dotenv import load_dotenv

from telegram_publisher.profiles import (
    ChannelProfile,
    delete_profile,
    load_profiles,
    save_profile,
)
from telegram_publisher.publishing import TEXT_LIMIT, publish_sync, split_text


def _load_environment() -> None:
    """Искать .env рядом с приложением и проектом, а не только в cwd."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / ".env")
    candidates.append(Path.cwd() / ".env")
    if not getattr(sys, "frozen", False):
        candidates.append(Path(__file__).resolve().parents[2] / ".env")
    for path in dict.fromkeys(candidates):
        if path.is_file():
            load_dotenv(path, override=False)
            break


class PublisherWindow:
    """Главное окно приложения."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Telegram Publisher")
        self.root.geometry("820x680")
        self.root.minsize(620, 480)
        self.image_path: str | None = None
        self.send_in_progress = False

        _load_environment()
        self.profiles = self._load_profiles_with_environment()
        self.selected_profile_id: str | None = None

        self._build_interface()
        self._refresh_profiles()
        self._update_counter()

    def _load_profiles_with_environment(self) -> list[ChannelProfile]:
        try:
            profiles = load_profiles()
        except Exception as error:
            messagebox.showerror(
                "Настройки каналов",
                f"Не удалось загрузить сохранённые профили: {error}",
                parent=self.root,
            )
            profiles = []
        if profiles:
            return profiles

        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if token and chat_id:
            try:
                return [save_profile("Канал из .env", token, chat_id)]
            except Exception as error:
                messagebox.showwarning(
                    "Не удалось сохранить профиль",
                    "Настройки из .env доступны только до закрытия приложения, "
                    "поскольку не удалось сохранить токен в системном хранилище секретов.\n\n"
                    f"Подробности: {error}",
                    parent=self.root,
                )
                return [ChannelProfile("env-session", "Канал из .env", chat_id, token)]
        return []

    def _build_interface(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(container)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Канал:").pack(side=tk.LEFT, padx=(0, 6))
        self.profile_combo = ttk.Combobox(header, state="readonly", width=42)
        self.profile_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)
        ttk.Button(header, text="Настроить каналы…", command=self._manage_profiles).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(header, text="Вставить из буфера", command=self._paste_clipboard).pack(
            side=tk.RIGHT, padx=(8, 0)
        )

        ttk.Label(container, text="Текст публикации").pack(anchor=tk.W, pady=(14, 4))
        self.text = tk.Text(container, wrap=tk.WORD, undo=True, font=("Segoe UI", 11), height=18)
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.bind("<<Modified>>", self._on_text_modified)
        self.text.bind("<Control-v>", self._paste_clipboard_event)
        self.text.bind("<Control-V>", self._paste_clipboard_event)
        self.text.bind("<Shift-Insert>", self._paste_clipboard_event)
        self.text.edit_modified(False)

        controls = ttk.Frame(container)
        controls.pack(fill=tk.X, pady=(8, 0))
        self.counter = ttk.Label(controls, text="")
        self.counter.pack(side=tk.LEFT)
        ttk.Button(controls, text="Выбрать изображение…", command=self._choose_image).pack(
            side=tk.RIGHT
        )
        self.image_label = ttk.Label(container, text="Изображение не выбрано")
        self.image_label.pack(anchor=tk.W, pady=(6, 0))

        bottom = ttk.Frame(container)
        bottom.pack(fill=tk.X, pady=(14, 0))
        self.status = ttk.Label(bottom, text="Готово к работе")
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.send_button = ttk.Button(bottom, text="Опубликовать", command=self._send)
        self.send_button.pack(side=tk.RIGHT)

    def _refresh_profiles(self, select_id: str | None = None) -> None:
        try:
            stored_profiles = load_profiles()
        except Exception as error:
            messagebox.showerror("Настройки каналов", str(error), parent=self.root)
            stored_profiles = []
        if stored_profiles:
            self.profiles = stored_profiles
        elif not self.profiles or all(profile.profile_id != "env-session" for profile in self.profiles):
            self.profiles = []

        self.profile_combo["values"] = [
            f"{profile.name} — {profile.chat_id}" for profile in self.profiles
        ]
        chosen = next(
            (i for i, profile in enumerate(self.profiles) if profile.profile_id == select_id),
            0 if self.profiles else -1,
        )
        if chosen >= 0:
            self.profile_combo.current(chosen)
            self.selected_profile_id = self.profiles[chosen].profile_id
        else:
            self.profile_combo.set("")
            self.selected_profile_id = None

    def _on_profile_selected(self, _event: tk.Event | None = None) -> None:
        index = self.profile_combo.current()
        self.selected_profile_id = self.profiles[index].profile_id if index >= 0 else None
        self.status.configure(text="Готово к работе")

    def _manage_profiles(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Профили каналов")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("620x330")
        dialog.minsize(560, 300)

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Сохранённые каналы").grid(row=0, column=0, sticky=tk.W)
        listing = tk.Listbox(frame, height=8, exportselection=False)
        listing.grid(row=1, column=0, rowspan=5, sticky="nsew", padx=(0, 12), pady=(4, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(frame, text="Название профиля").grid(row=0, column=1, sticky=tk.W)
        name_var = tk.StringVar()
        name_entry = ttk.Entry(frame, textvariable=name_var, width=36)
        name_entry.grid(row=1, column=1, sticky=tk.EW, pady=(4, 8))
        ttk.Label(frame, text="Токен бота").grid(row=2, column=1, sticky=tk.W)
        token_var = tk.StringVar()
        ttk.Entry(frame, textvariable=token_var, show="•", width=36).grid(
            row=3, column=1, sticky=tk.EW, pady=(4, 8)
        )
        ttk.Label(frame, text="Имя или ID канала").grid(row=4, column=1, sticky=tk.W)
        chat_var = tk.StringVar()
        ttk.Entry(frame, textvariable=chat_var, width=36).grid(
            row=5, column=1, sticky=tk.EW, pady=(4, 8)
        )
        frame.columnconfigure(1, weight=1)

        selected_id: str | None = None
        working_profiles = list(self.profiles)

        def populate(index: int) -> None:
            nonlocal selected_id
            if index < 0 or index >= len(working_profiles):
                selected_id = None
                name_var.set("")
                token_var.set("")
                chat_var.set("")
                return
            profile = working_profiles[index]
            selected_id = profile.profile_id
            name_var.set(profile.name)
            token_var.set(profile.token)
            chat_var.set(profile.chat_id)

        def refill(select_id: str | None = None) -> None:
            listing.delete(0, tk.END)
            for profile in working_profiles:
                listing.insert(tk.END, f"{profile.name} — {profile.chat_id}")
            index = next(
                (i for i, profile in enumerate(working_profiles) if profile.profile_id == select_id),
                0 if working_profiles else -1,
            )
            if index >= 0:
                listing.selection_set(index)
                listing.activate(index)
                populate(index)
            else:
                populate(-1)

        def on_select(_event: tk.Event | None = None) -> None:
            selection = listing.curselection()
            populate(selection[0] if selection else -1)

        def save_current() -> None:
            nonlocal selected_id
            try:
                profile = save_profile(
                    name_var.get(),
                    token_var.get(),
                    chat_var.get(),
                    selected_id if selected_id != "env-session" else None,
                )
                working_profiles[:] = load_profiles()
            except Exception as error:
                messagebox.showerror("Не удалось сохранить профиль", str(error), parent=dialog)
                return
            refill(profile.profile_id)
            self._refresh_profiles(profile.profile_id)

        def add_new() -> None:
            listing.selection_clear(0, tk.END)
            populate(-1)
            name_entry.focus_set()

        def remove_current() -> None:
            selection = listing.curselection()
            if not selection:
                return
            profile = working_profiles[selection[0]]
            if not messagebox.askyesno(
                "Удаление профиля",
                f"Удалить профиль «{profile.name}»?",
                parent=dialog,
            ):
                return
            if profile.profile_id != "env-session":
                try:
                    delete_profile(profile.profile_id)
                except Exception as error:
                    messagebox.showerror("Не удалось удалить профиль", str(error), parent=dialog)
                    return
            working_profiles[:] = [
                item for item in working_profiles if item.profile_id != profile.profile_id
            ]
            refill(None)
            self._refresh_profiles()

        listing.bind("<<ListboxSelect>>", on_select)
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky=tk.EW, pady=(12, 0))
        ttk.Button(buttons, text="Новый профиль", command=add_new).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Сохранить профиль", command=save_current).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(buttons, text="Удалить профиль", command=remove_current).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(buttons, text="Закрыть", command=dialog.destroy).pack(side=tk.RIGHT)
        refill(self.selected_profile_id)
        name_entry.focus_set()

    def _paste_clipboard_event(self, _event: tk.Event) -> str:
        self._paste_clipboard()
        return "break"

    def _paste_clipboard(self) -> None:
        try:
            content = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Буфер обмена", "В буфере обмена нет доступного текста.")
            return
        try:
            self.text.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
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
            self._update_counter()

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
        profile = next(
            (item for item in self.profiles if item.profile_id == self.selected_profile_id),
            None,
        )
        if profile is None or not profile.token or not profile.chat_id:
            messagebox.showerror(
                "Настройки не заполнены",
                "Добавь профиль канала через кнопку «Настроить каналы…».",
                parent=self.root,
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
            f"Опубликовать в канале «{profile.name}» ({profile.chat_id})?\n"
            f"Будет отправлено сообщений: {message_count}.",
            parent=self.root,
        ):
            return

        self.send_in_progress = True
        self.send_button.configure(state=tk.DISABLED)
        self.status.configure(text="Отправка…")
        thread = threading.Thread(
            target=self._send_in_background,
            args=(profile, content, self.image_path),
            daemon=True,
        )
        thread.start()

    def _send_in_background(
        self, profile: ChannelProfile, content: str, image_path: str | None
    ) -> None:
        try:
            count = publish_sync(profile.token, profile.chat_id, content, image_path)
        except Exception as error:
            self.root.after(0, self._send_failed, str(error))
            return
        self.root.after(0, self._send_succeeded, count)

    def _send_failed(self, error: str) -> None:
        self.send_in_progress = False
        self.send_button.configure(state=tk.NORMAL)
        self.status.configure(text="Не удалось отправить публикацию")
        messagebox.showerror("Ошибка публикации", error, parent=self.root)

    def _send_succeeded(self, count: int) -> None:
        self.send_in_progress = False
        self.send_button.configure(state=tk.NORMAL)
        self.status.configure(text=f"Опубликовано. Отправлено сообщений: {count}")
        messagebox.showinfo("Публикация завершена", f"Отправлено сообщений: {count}", parent=self.root)


def run_app() -> None:
    """Создать и запустить главное окно."""
    root = tk.Tk()
    PublisherWindow(root)
    root.mainloop()
