"""Графический интерфейс Telegram Publisher."""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from dotenv import load_dotenv

from telegram_publisher.profiles import (
    ChannelProfile,
    delete_profile,
    load_profiles,
    save_profile,
)
from telegram_publisher.publishing import (
    CAPTION_LIMIT,
    RICH_TEXT_LIMIT,
    TEXT_LIMIT,
    estimate_message_count,
    publish_sync,
    prepare_plain_messages,
)


class _PreviewTextParser(__import__("html.parser", fromlist=["HTMLParser"]).HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"p", "div", "li", "blockquote", "h1", "h2", "h3", "tr", "br"} and self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li", "blockquote", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")


def _html_to_text(content: str) -> str:
    parser = _PreviewTextParser()
    parser.feed(content)
    return "".join(parser.parts).strip()


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
        self.html_content = ""
        self.editor_parts: list[str] | None = None
        self.editor_mode = "rich"
        self.editor_status = ""
        self.publishing_from_editor = False
        self._updating_preview = False
        self.editor_process: subprocess.Popen | None = None
        self.editor_tempdir: tempfile.TemporaryDirectory | None = None
        self.editor_status_path: Path | None = None
        self.send_in_progress = False
        self.finalized_plain_parts: list[str] | None = None

        _load_environment()
        self.profiles = self._load_profiles_with_environment()
        self.selected_profile_id: str | None = None

        self._build_interface()
        self._refresh_profiles()
        self._update_counter()
        self.root.bind("<Control-e>", lambda _event: self._open_editor())
        self.root.after(150, self._open_editor)

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

        publication_options = ttk.Frame(container)
        publication_options.pack(fill=tk.X, pady=(14, 0))
        ttk.Label(publication_options, text="Способ публикации:").pack(side=tk.LEFT)
        self.series_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            publication_options,
            text="Разбить на серию публикаций",
            variable=self.series_var,
            command=self._update_publication_options,
        ).pack(side=tk.RIGHT)
        self.mode_combo = ttk.Combobox(publication_options, state="readonly", width=34)
        self.mode_combo.pack(side=tk.LEFT, padx=(8, 0))
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_selected)
        self.mode_hint = ttk.Label(container, text="", wraplength=760)
        self.mode_hint.pack(anchor=tk.W, pady=(4, 0))

        editor_controls = ttk.Frame(container)
        editor_controls.pack(fill=tk.X, pady=(8, 4))
        ttk.Label(editor_controls, text="Содержимое публикации").pack(side=tk.LEFT)
        self.text = tk.Text(container, wrap=tk.WORD, undo=True, font=("Segoe UI", 11), height=18)
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.bind("<<Modified>>", self._on_text_modified)
        self.text.edit_modified(False)

        controls = ttk.Frame(container)
        controls.pack(fill=tk.X, pady=(8, 0))
        self.counter = ttk.Label(controls, text="")
        self.counter.pack(side=tk.LEFT)

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

    def _manage_profiles(self, reopen_editor: bool = False) -> None:
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
        if reopen_editor:
            dialog.bind(
                "<Destroy>",
                lambda event: self.root.after(150, self._open_editor)
                if event.widget is dialog
                else None,
            )

    def _on_text_modified(self, _event: tk.Event) -> None:
        if self.text.edit_modified():
            if not self._updating_preview:
                self.html_content = html.escape(self.text.get("1.0", "end-1c"), quote=False).replace("\n", "<br>")
            self._update_counter()
            self.text.edit_modified(False)

    def _open_editor(self) -> None:
        """Открыть основной редактор и передать ему настройки публикации."""
        if self.editor_process is not None and self.editor_process.poll() is None:
            return

        self.editor_tempdir = tempfile.TemporaryDirectory(prefix="telegram-publisher-editor-")
        folder = Path(self.editor_tempdir.name)
        initial_path = folder / "initial.html"
        result_path = folder / "result.json"
        self.editor_status_path = folder / "editor-status.json"
        config_path = folder / "editor-config.json"
        initial_path.write_text(self.html_content, encoding="utf-8")
        config_path.write_text(
            json.dumps(
                {
                    "profiles": [
                        {
                            "profile_id": profile.profile_id,
                            "name": profile.name,
                            "chat_id": profile.chat_id,
                        }
                        for profile in self.profiles
                    ],
                    "selected_profile_id": self.selected_profile_id,
                    "mode": self.editor_mode,
                    "series": self.series_var.get(),
                    "status": self.editor_status,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.root.withdraw()
        try:
            self.editor_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "telegram_publisher.editor",
                    str(initial_path),
                    str(result_path),
                    str(config_path),
                ],
                cwd=str(Path(__file__).resolve().parents[2]),
            )
        except Exception as error:
            self.editor_tempdir.cleanup()
            self.editor_tempdir = None
            messagebox.showerror(
                "Визуальный редактор",
                f"Не удалось открыть редактор: {error}",
                parent=self.root,
            )
            self.root.destroy()
            return
        self._poll_editor(result_path)

    def _poll_editor(self, result_path: Path) -> None:
        """Обрабатывать запросы редактора, пока его окно остаётся открытым."""
        process = self.editor_process
        if process is None:
            return

        running = process.poll() is None
        result: dict = {}
        if result_path.is_file():
            try:
                loaded = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    result = loaded
            except (OSError, json.JSONDecodeError) as error:
                self._write_editor_status(f"Не удалось прочитать результат редактора: {error}")
            action = result.get("action")

            if running and action == "review_publish":
                result_path.unlink(missing_ok=True)
                self._review_plain_messages(result)
            elif running and action == "publish":
                result_path.unlink(missing_ok=True)
                self._apply_editor_result(result)
                self.publishing_from_editor = True
                self.status.configure(text="Подготовка публикации")
                self._send()
            elif not running:
                result_path.unlink(missing_ok=True)

        if running:
            self.root.after(300, self._poll_editor, result_path)
            return

        self.editor_process = None
        if self.editor_tempdir is not None:
            self.editor_tempdir.cleanup()
            self.editor_tempdir = None

        action = result.get("action")
        if action == "manage_profiles":
            self._apply_editor_result(result)
            self._manage_profiles(reopen_editor=True)
            return
        if action == "publish":
            # Защитный путь на случай, если процесс завершился до обработки запроса.
            self._apply_editor_result(result)
            self.publishing_from_editor = True
            self._send()
            return

        # Закрытие окна редактора, включая кнопку «Отмена», завершает приложение.
        self.root.destroy()

    def _review_plain_messages(self, result: dict) -> None:
        """Показать точные строки sendMessage перед отправкой обычной публикации."""
        mode = str(result.get("mode", "plain"))
        raw_parts = result.get("parts")
        editor_parts = [str(part) for part in raw_parts] if isinstance(raw_parts, list) and raw_parts else None
        try:
            messages = prepare_plain_messages(
                str(result.get("html", "")),
                editor_parts if mode == "plain_series" else None,
            )
        except Exception as error:
            self._write_editor_status(f"Не удалось подготовить текст sendMessage: {error}")
            return
        if not messages:
            self._write_editor_status("После подготовки не осталось сообщений для отправки.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Финальная правка текста sendMessage")
        dialog.geometry("900x620")
        dialog.minsize(620, 420)
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            frame,
            text=(
                "Ниже показано точное содержимое поля text, которое будет передано Telegram Bot API. "
                "HTML-разметка и невидимые символы показаны как есть."
            ),
            wraplength=850,
        ).pack(anchor=tk.W, pady=(0, 8))

        editors: list[tk.Text] = []
        if len(messages) > 1:
            notebook = ttk.Notebook(frame)
            notebook.pack(fill=tk.BOTH, expand=True)
            for index, message in enumerate(messages, start=1):
                tab = ttk.Frame(notebook, padding=6)
                tab.pack(fill=tk.BOTH, expand=True)
                text_box = tk.Text(tab, wrap=tk.WORD, undo=True, font=("Consolas", 10))
                scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=text_box.yview)
                text_box.configure(yscrollcommand=scrollbar.set)
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                text_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                text_box.insert("1.0", message)
                editors.append(text_box)
                notebook.add(tab, text=f"Сообщение {index}")
        else:
            text_box = tk.Text(frame, wrap=tk.WORD, undo=True, font=("Consolas", 10))
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text_box.yview)
            text_box.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            text_box.pack(fill=tk.BOTH, expand=True)
            text_box.insert("1.0", messages[0])
            editors.append(text_box)

        outcome: dict[str, object] = {"send": False}
        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(10, 0))

        def cancel() -> None:
            dialog.destroy()

        def send() -> None:
            edited = [box.get("1.0", "end-1c") for box in editors]
            if not any(part.strip() for part in edited):
                messagebox.showwarning("Пустая публикация", "Добавь текст перед отправкой.", parent=dialog)
                return
            outcome["send"] = True
            outcome["messages"] = edited
            dialog.destroy()

        ttk.Button(buttons, text="Отмена", command=cancel).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Отправить", command=send).pack(side=tk.RIGHT, padx=(0, 8))
        if editors:
            editors[0].focus_set()
        dialog.grab_set()
        self._write_editor_status("Отправка: ожидается финальная правка текста…")
        self.root.wait_window(dialog)

        if not outcome["send"]:
            self._write_editor_status("Публикация отменена. Текст остался в визуальном редакторе.")
            return

        self._apply_editor_result(result)
        self.finalized_plain_parts = [str(part) for part in outcome["messages"]]
        self.publishing_from_editor = True
        self.status.configure(text="Подготовка публикации после финальной правки")
        self._send()

    def _apply_editor_result(self, result: dict) -> None:
        if "html" not in result:
            return
        self.html_content = str(result.get("html", ""))
        raw_parts = result.get("parts")
        self.editor_parts = [str(part) for part in raw_parts] if isinstance(raw_parts, list) and raw_parts else None
        self.editor_mode = str(result.get("mode", "rich"))
        self.selected_profile_id = result.get("profile_id") or None
        self.series_var.set(bool(result.get("series", False)))
        self._updating_preview = True
        try:
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", _html_to_text(self.html_content))
            self.text.edit_modified(False)
        finally:
            self._updating_preview = False
        self._update_counter()
        selected_label = next(
            (label for label, mode in self.mode_values.items() if mode == self.editor_mode),
            None,
        )
        if selected_label is not None:
            self.mode_combo.set(selected_label)

    def _write_editor_status(self, message: str, clear: bool = False) -> None:
        if self.editor_status_path is None:
            return
        try:
            self.editor_status_path.write_text(
                json.dumps({"message": message, "clear": clear}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _update_counter(self) -> None:
        content = self.text.get("1.0", "end-1c").strip()
        length = len(content)
        self.counter.configure(
            text=f"{length} символов"
            + (f" · предел рич-текста: {RICH_TEXT_LIMIT}" if length > TEXT_LIMIT else "")
        )
        self._update_publication_options()

    def _available_modes(self, length: int) -> list[tuple[str, str]]:
        """Определить доступные способы отправки по длине текста и наличию изображения."""
        series = self.series_var.get()
        if series:
            if self.image_path:
                return [
                    ("Подпись + продолжение", "caption"),
                    ("Обычный текст + изображение", "media_text"),
                    ("Рич-текст + изображение", "rich"),
                    ("Серия обычных сообщений", "plain_series"),
                    ("Серия рич-сообщений", "rich_series"),
                ]
            return [
                ("Обычные сообщения", "plain_series"),
                ("Рич-текст", "rich"),
                ("Серия рич-сообщений", "rich_series"),
            ]

        if self.image_path:
            if length <= CAPTION_LIMIT:
                return [
                    ("Подпись к изображению", "caption"),
                    ("Обычный текст + изображение", "media_text"),
                    ("Рич-текст + изображение", "rich"),
                ]
            if length <= TEXT_LIMIT:
                return [
                    ("Обычный текст + изображение", "media_text"),
                    ("Рич-текст + изображение", "rich"),
                ]
            return [("Рич-текст + изображение", "rich")]

        if length <= TEXT_LIMIT:
            return [("Обычный текст", "plain"), ("Рич-текст", "rich")]
        return [("Рич-текст", "rich")]

    def _update_publication_options(self) -> None:
        content = self.text.get("1.0", "end-1c").strip()
        options = self._available_modes(len(content))
        previous = self.mode_combo.get() if hasattr(self, "mode_combo") else ""
        self.mode_values = {label: mode for label, mode in options}
        labels = [label for label, _mode in options]
        self.mode_combo["values"] = labels

        if previous in self.mode_values:
            self.mode_combo.set(previous)
        else:
            default_mode = self._default_mode(len(content))
            selected = next(
                (label for label, mode in options if mode == default_mode),
                labels[0] if labels else "",
            )
            self.mode_combo.set(selected)

        if len(content) > RICH_TEXT_LIMIT and not self.series_var.get():
            hint = (
                "Текст превышает 32768 символов. Включи серию публикаций, "
                "чтобы разбить его на несколько сообщений."
            )
        elif self.mode_values.get(self.mode_combo.get()) in {"rich", "rich_series"}:
            hint = (
                "Визуальный редактор сохраняет форматирование для режима рич-текста. "
                "Для обычного текста оформление преобразуется в текст без форматирования."
            )
        elif self.image_path and len(content) <= CAPTION_LIMIT:
            hint = "По умолчанию текст станет подписью к изображению."
        elif self.image_path and len(content) <= TEXT_LIMIT:
            hint = (
                "По умолчанию изображение и обычный текст отправятся одним сообщением "
                "через встроенное медиа рич-сообщения."
            )
        else:
            hint = "Обычные сообщения ограничены 4096 символами, подпись к фото — 1024."
        self.mode_hint.configure(text=hint)

    def _default_mode(self, length: int) -> str:
        if self.image_path:
            if length <= CAPTION_LIMIT:
                return "caption"
            if length <= TEXT_LIMIT:
                return "media_text"
            return "rich"
        return "plain" if length <= TEXT_LIMIT else "rich"

    def _on_mode_selected(self, _event: tk.Event | None = None) -> None:
        self._update_publication_options()

    def _send(self) -> None:
        if self.send_in_progress:
            return
        from_editor = self.publishing_from_editor
        profile = next(
            (item for item in self.profiles if item.profile_id == self.selected_profile_id),
            None,
        )
        if profile is None or not profile.token or not profile.chat_id:
            if from_editor:
                self._write_editor_status("Настройки канала не заполнены. Проверь профиль и токен.")
                self.publishing_from_editor = False
                self.finalized_plain_parts = None
            else:
                messagebox.showerror(
                    "Настройки не заполнены",
                    "Добавь профиль канала через кнопку «Настроить каналы…».",
                    parent=self.root,
                )
            return

        plain_content = self.text.get("1.0", "end-1c").strip()
        mode = (
            "plain_prepared"
            if from_editor and self.finalized_plain_parts is not None
            else self.editor_mode
            if from_editor
            else self.mode_values.get(self.mode_combo.get(), "auto")
        )
        content = self.html_content if from_editor or mode in {"rich", "rich_series", "media_text", "plain_prepared"} else plain_content
        if not plain_content and not self.image_path and not content.strip():
            if from_editor:
                self._write_editor_status("Добавь текст, изображение или видео перед публикацией.")
                self.publishing_from_editor = False
                self.finalized_plain_parts = None
            else:
                messagebox.showwarning("Пустая публикация", "Добавь текст или выбери изображение.")
            return

        series = self.series_var.get()
        if len(plain_content) > RICH_TEXT_LIMIT and not series:
            warning = "Для текста длиннее 32768 символов включи серию публикаций."
            if from_editor:
                self._write_editor_status(warning)
                self.publishing_from_editor = False
                self.finalized_plain_parts = None
            else:
                messagebox.showwarning("Слишком длинный текст", warning, parent=self.root)
            return

        message_count = estimate_message_count(plain_content, self.image_path, mode, series)
        if mode in {"rich", "rich_series"} and re.search(
            r"<(?:img|video)\b", content, re.IGNORECASE
        ):
            message_count = max(1, message_count)
        mode_label = next(
            (label for label, value in self.mode_values.items() if value == mode),
            mode,
        )
        if not from_editor and not messagebox.askyesno(
            "Подтверждение публикации",
            f"Опубликовать в канале «{profile.name}» ({profile.chat_id})?\n"
            f"Способ: {mode_label}.\n"
            f"Будет отправлено сообщений: {message_count}.",
            parent=self.root,
        ):
            return

        self.send_in_progress = True
        self.send_button.configure(state=tk.DISABLED)
        self.status.configure(text="Отправка…")
        self._write_editor_status("Отправка публикации…")
        thread = threading.Thread(
            target=self._send_in_background,
            args=(
                profile,
                content,
                self.image_path,
                mode,
                series,
                self.finalized_plain_parts
                if from_editor and self.finalized_plain_parts is not None
                else self.editor_parts if from_editor and series else None,
            ),
            daemon=True,
        )
        thread.start()

    def _send_in_background(
        self,
        profile: ChannelProfile,
        content: str,
        image_path: str | None,
        mode: str,
        series: bool,
        parts: list[str] | None = None,
    ) -> None:
        try:
            count = publish_sync(
                profile.token, profile.chat_id, content, image_path, mode, series, parts=parts
            )
        except Exception as error:
            self.root.after(0, self._send_failed, str(error))
            return
        self.root.after(0, self._send_succeeded, count)

    def _send_failed(self, error: str) -> None:
        self.send_in_progress = False
        self.send_button.configure(state=tk.NORMAL)
        self.status.configure(text="Не удалось отправить публикацию")
        if self.publishing_from_editor:
            self._write_editor_status(f"Ошибка публикации: {error}")
            self.publishing_from_editor = False
            self.finalized_plain_parts = None
            return
        messagebox.showerror("Ошибка публикации", error, parent=self.root)

    def _send_succeeded(self, count: int) -> None:
        self.send_in_progress = False
        self.send_button.configure(state=tk.NORMAL)
        self.status.configure(text=f"Опубликовано. Отправлено сообщений: {count}")
        if self.publishing_from_editor:
            self._write_editor_status(
                f"Опубликовано. Отправлено сообщений: {count}",
            )
            self.publishing_from_editor = False
            self.finalized_plain_parts = None
            return
        messagebox.showinfo("Публикация завершена", f"Отправлено сообщений: {count}", parent=self.root)


def run_app() -> None:
    """Создать и запустить главное окно."""
    root = tk.Tk()
    root.withdraw()
    PublisherWindow(root)
    root.mainloop()
