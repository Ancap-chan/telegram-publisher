"""Графический интерфейс Telegram Publisher."""

from __future__ import annotations

import html
import json
import math
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

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
    prepare_plain_messages,
    PartialPublicationError,
)
from telegram_publisher.controller import PublicationController, PublicationRequest, PublicationSession


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


class PublisherWindow:
    """Главное окно приложения."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.session = PublicationSession()
        self.image_path: str | None = None
        self.html_content = ""
        self.session.editor_parts: list[str] | None = None
        self.editor_mode = "rich"
        self.editor_status = ""
        self.session.publishing_from_editor = False
        self._updating_preview = False
        self.editor_process: subprocess.Popen | None = None
        self.editor_tempdir: tempfile.TemporaryDirectory | None = None
        self.editor_status_path: Path | None = None
        self.session.send_in_progress = False
        self.session.finalized_plain_parts = None
        self.session.pending_messages = []
        self.session.pending_sent_count = 0
        self.session.pending_retry_after = 0.0
        self.session.resuming_pending = False

        self.profiles = self._load_profiles()
        self.selected_profile_id: str | None = None

        self._build_backend_state()
        self._refresh_profiles()
        self._update_counter()
        self.root.bind("<Control-e>", lambda _event: self._open_editor())
        self.root.after(150, self._open_editor)

    def _load_profiles(self) -> list[ChannelProfile]:
        """Загрузить профили каналов из постоянного хранилища."""
        try:
            return load_profiles()
        except Exception as error:
            messagebox.showerror(
                "Настройки каналов",
                f"Не удалось загрузить сохранённые профили: {error}",
                parent=self.root,
            )
            return []

    def _build_backend_state(self) -> None:
        """Создать только невидимое состояние для логики публикации.

        Главное окно Tkinter не содержит пользовательского интерфейса: его
        корневой объект нужен для цикла событий и дополнительных диалогов.
        Все элементы ниже остаются неупакованными и не отображаются.
        """
        self.profile_combo = ttk.Combobox(self.root, state="readonly")
        self.series_var = tk.BooleanVar(master=self.root, value=False)
        self.mode_combo = ttk.Combobox(self.root, state="readonly")
        self.mode_hint = ttk.Label(self.root, text="")
        self.text = tk.Text(self.root)
        self.counter = ttk.Label(self.root, text="")
        self.status = ttk.Label(self.root, text="")
        self.resend_button = ttk.Button(self.root)
        self.send_button = ttk.Button(self.root)

    def _refresh_profiles(self, select_id: str | None = None) -> None:
        try:
            stored_profiles = load_profiles()
        except Exception as error:
            messagebox.showerror("Настройки каналов", str(error), parent=self.root)
            stored_profiles = []
        if stored_profiles:
            self.profiles = stored_profiles
        else:
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
        # Скрытый корневой объект Tkinter нужен только для дополнительных
        # диалогов. Окно настроек не должно зависеть от видимости его владельца.
        dialog = tk.Toplevel(self.root)
        dialog.title("Профили каналов")
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
                    selected_id,
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
        def after_close(event: tk.Event) -> None:
            if event.widget is not dialog:
                return
            if reopen_editor:
                self.root.after(100, self._open_editor)
                return
            self._write_editor_status(
                "Настройки каналов обновлены.",
                profiles=[
                    {
                        "profile_id": profile.profile_id,
                        "name": profile.name,
                        "chat_id": profile.chat_id,
                    }
                    for profile in self.profiles
                ],
                selected_profile_id=self.selected_profile_id,
            )

        dialog.bind("<Destroy>", after_close)

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
                self.session.publishing_from_editor = True
                self.status.configure(text="Подготовка публикации")
                self._send()
            elif running and action == "manage_profiles":
                result_path.unlink(missing_ok=True)
                self._apply_editor_result(result)
                self._manage_profiles(reopen_editor=False)
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
            # Защитный путь для старой версии редактора, завершившейся
            # после запроса настроек.
            self._apply_editor_result(result)
            self._manage_profiles(reopen_editor=False)
            return
        if action == "publish":
            # Защитный путь на случай, если процесс завершился до обработки запроса.
            self._apply_editor_result(result)
            self.session.publishing_from_editor = True
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
        # Главное окно скрыто, пока открыт визуальный редактор. Не связываем
        # диалог с ним через transient: некоторые оконные менеджеры скрывают
        # такой диалог вместе с владельцем.
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
        # Явно показываем и поднимаем диалог: главное окно приложения
        # в этот момент скрыто методом withdraw().
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
        dialog.grab_set()
        if editors:
            editors[0].focus_set()
        self._write_editor_status("Отправка: ожидается финальная правка текста…")
        self.root.wait_window(dialog)

        if not outcome["send"]:
            self._write_editor_status("Публикация отменена. Текст остался в визуальном редакторе.")
            return

        self._apply_editor_result(result)
        self.session.finalized_plain_parts = [str(part) for part in outcome["messages"]]
        self.session.publishing_from_editor = True
        self.status.configure(text="Подготовка публикации после финальной правки")
        self._send()

    def _apply_editor_result(self, result: dict) -> None:
        if "html" not in result:
            return
        self.html_content = str(result.get("html", ""))
        raw_parts = result.get("parts")
        self.session.editor_parts = [str(part) for part in raw_parts] if isinstance(raw_parts, list) and raw_parts else None
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

    def _write_editor_status(
        self,
        message: str,
        clear: bool = False,
        profiles: list[dict[str, str]] | None = None,
        selected_profile_id: str | None = None,
    ) -> None:
        if self.editor_status_path is None:
            return
        payload: dict[str, object] = {"message": message, "clear": clear}
        if profiles is not None:
            payload["profiles"] = profiles
            payload["selected_profile_id"] = selected_profile_id
        try:
            self.editor_status_path.write_text(
                json.dumps(payload, ensure_ascii=False),
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
                    ("Картинка + подпись", "caption"),
                    ("Обычное сообщение + изображение", "media_text"),
                    ("Рич-текст", "rich"),
                    ("Серия обычных сообщений", "plain_series"),
                    ("Серия рич-сообщений", "rich_series"),
                ]
            return [
                ("Обычные сообщения", "plain_series"),
                ("Рич-сообщение", "rich"),
                ("Серия рич-сообщений", "rich_series"),
            ]

        if self.image_path:
            if length <= CAPTION_LIMIT:
                return [
                    ("Подпись к изображению", "caption"),
                    ("Обычное сообщение + изображение", "media_text"),
                    ("Рич-сообщение", "rich"),
                ]
            if length <= TEXT_LIMIT:
                return [
                    ("Обычное сообщение + изображение", "media_text"),
                    ("Рич-сообщение", "rich"),
                ]
            return [("Рич-сообщение", "rich")]

        if length <= TEXT_LIMIT:
            return [("Обычное сообщение", "plain"), ("Рич-сообщение", "rich")]
        return [("Рич-сообщение", "rich")]

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
                "Текст превышает 32768 символов. Используйте публикацию в виде серии постов, "
                "чтобы разбить его на несколько сообщений."
            )
        elif self.mode_values.get(self.mode_combo.get()) in {"rich", "rich_series"}:
            hint = (
                "Визуальный редактор сохраняет форматирование для режима рич-сообщения. "
                "Для обычного текста оформление преобразуется в текст с минимальным форматированием."
            )
        elif self.image_path and len(content) <= CAPTION_LIMIT:
            hint = "По умолчанию текст станет подписью к изображению."
        elif self.image_path and len(content) <= TEXT_LIMIT:
            hint = (
                "По умолчанию изображение и обычный текст отправятся одним сообщением "
                "через встроенное медиа рич-сообщения."
            )
        else:
            hint = "Обычные сообщения ограничены 4096 символами, подпись к изображению — 1024."
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
        if self.session.send_in_progress:
            return
        from_editor = self.session.publishing_from_editor
        profile = next(
            (item for item in self.profiles if item.profile_id == self.selected_profile_id),
            None,
        )
        if profile is None or not profile.token or not profile.chat_id:
            if from_editor:
                self._write_editor_status("Настройки канала не заполнены. Проверьте профиль и токен.")
                self.session.publishing_from_editor = False
                self.session.finalized_plain_parts = None
            else:
                messagebox.showerror(
                    "Настройки не заполнены",
                    "Добавьте профиль канала через кнопку «Настроить каналы…».",
                    parent=self.root,
                )
            return

        plain_content = self.text.get("1.0", "end-1c").strip()
        mode = (
            "plain_prepared"
            if from_editor and self.session.finalized_plain_parts is not None
            else self.editor_mode
            if from_editor
            else self.mode_values.get(self.mode_combo.get(), "auto")
        )
        content = self.html_content if from_editor or mode in {"rich", "rich_series", "media_text", "plain_prepared"} else plain_content
        if not plain_content and not self.image_path and not content.strip():
            if from_editor:
                self._write_editor_status("Добавьте текст, изображение или видео перед публикацией.")
                self.session.publishing_from_editor = False
                self.session.finalized_plain_parts = None
            else:
                messagebox.showwarning("Пустая публикация", "Добавьте текст или выберите изображение.")
            return

        series = self.series_var.get()
        if len(plain_content) > RICH_TEXT_LIMIT and not series:
            warning = "Для текста длиннее 32768 символов используйте публикацию в виде серии постов."
            if from_editor:
                self._write_editor_status(warning)
                self.session.publishing_from_editor = False
                self.session.finalized_plain_parts = None
            else:
                messagebox.showwarning("Слишком длинный текст", warning, parent=self.root)
            return

        message_count = estimate_message_count(
            content if mode in {"album", "album_series"} else plain_content,
            self.image_path,
            mode,
            series,
        )
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

        self.session.send_in_progress = True
        self.send_button.configure(state=tk.DISABLED)
        self.status.configure(text="Отправка…")
        self._write_editor_status("Отправка публикации…")
        initial_delay = self.session.pending_retry_after
        self.session.pending_retry_after = 0.0
        thread = threading.Thread(
            target=self._send_in_background,
            args=(
                profile,
                content,
                self.image_path,
                mode,
                series,
                self.session.finalized_plain_parts
                if from_editor and self.session.finalized_plain_parts is not None
                else self.session.editor_parts if from_editor and series else None,
                initial_delay,
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
        initial_delay: float = 0,
    ) -> None:
        """Выполнить запрос через прикладной контроллер вне главного потока."""
        request = PublicationRequest(
            profile=profile,
            content=content,
            image_path=image_path,
            mode=mode,
            series=series,
            parts=parts,
            initial_delay=initial_delay,
        )
        try:
            count = PublicationController().publish(request)
        except PartialPublicationError as error:
            self.root.after(0, self._handle_partial_publication, error)
            return
        except Exception as error:
            self.root.after(0, self._send_failed, str(error))
            return
        self.root.after(0, self._send_succeeded, count)

    def _handle_partial_publication(self, error: PartialPublicationError) -> None:
        """Сохранить остаток серии после подтверждённого отказа Telegram по flood control."""
        total_sent = self.session.record_partial(error)
        self.send_button.configure(state=tk.NORMAL)
        self.resend_button.configure(state=tk.NORMAL)
        self.status.configure(
            text=f"Отправлено: {total_sent}; ожидают отправки: {len(error.pending_messages)}"
        )
        self._write_editor_status(
            f"Telegram ограничил частоту публикаций. Подтверждённо отправлено: {total_sent}. "
            f"Не отправлено: {len(error.pending_messages)}. Можно исправить и дослать остаток."
        )
        dialog = tk.Toplevel(self.root)
        dialog.title("Публикация приостановлена")
        dialog.geometry("520x210")
        dialog.resizable(False, False)
        ttk.Label(
            dialog,
            text=(
                f"Telegram ограничил частоту публикаций. Подтверждённо отправлено: {total_sent}.\n"
                f"Не отправлено: {len(error.pending_messages)} сообщений.\n"
                f"Перед повторной отправкой приложение подождёт около {math.ceil(error.retry_after + 1)} сек."
            ),
            wraplength=480,
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=18, pady=(22, 18))
        buttons = ttk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=18, pady=(0, 16))
        ttk.Button(
            buttons,
            text="Дослать неопубликованное",
            command=lambda: (dialog.destroy(), self._review_pending_messages()),
        ).pack(side=tk.RIGHT)
        ttk.Button(
            buttons,
            text="Позже",
            command=dialog.destroy,
        ).pack(side=tk.RIGHT, padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
        dialog.grab_set()

    def _review_pending_messages(self) -> None:
        """Показать остаток серии, разрешить правку и удаление отдельных сообщений."""
        if not self.session.pending_messages:
            messagebox.showinfo("Нет сообщений для отправки", "Не осталось сообщений для досылки.", parent=self.root)
            self.resend_button.configure(state=tk.DISABLED)
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Досылка неопубликованных сообщений")
        dialog.geometry("900x620")
        dialog.minsize(620, 420)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            frame,
            text=(
                f"Успешно отправлено ранее: {self.session.pending_sent_count}. Ниже — оставшиеся сообщения. "
                "Выберите вкладку, исправьте текст или удалите сообщение. Перед повторной отправкой "
                f"будет выдержана пауза не менее {math.ceil(self.session.pending_retry_after)} сек."
            ),
            wraplength=850,
        ).pack(anchor=tk.W, pady=(0, 8))
        notebook = ttk.Notebook(frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        editors: list[tk.Text] = []
        for index, message in enumerate(self.session.pending_messages, start=self.session.pending_sent_count + 1):
            tab = ttk.Frame(notebook, padding=6)
            text_box = tk.Text(tab, wrap=tk.WORD, undo=True, font=("Consolas", 10))
            scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=text_box.yview)
            text_box.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            text_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            text_box.insert("1.0", message)
            notebook.add(tab, text=f"Сообщение {index}")
            editors.append(text_box)

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(10, 0))

        def delete_selected() -> None:
            selected = notebook.select()
            if not selected:
                return
            index = notebook.index(selected)
            notebook.forget(index)
            editors.pop(index)
            if not editors:
                self.session.pending_messages = []
                self.resend_button.configure(state=tk.DISABLED)
                messagebox.showinfo(
                    "Список пуст",
                    "Все неопубликованные сообщения удалены из очереди.",
                    parent=dialog,
                )
                dialog.destroy()

        def send_pending() -> None:
            messages = [box.get("1.0", "end-1c") for box in editors]
            messages = [message for message in messages if message.strip()]
            if not messages:
                messagebox.showwarning("Пустая очередь", "Добавьте текст или удалите окно досылки.", parent=dialog)
                return
            self.session.prepare_retry(messages)
            self.resend_button.configure(state=tk.DISABLED)
            dialog.destroy()
            self._send()

        ttk.Button(buttons, text="Удалить выбранное сообщение", command=delete_selected).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Отмена", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Дослать неопубликованное", command=send_pending).pack(
            side=tk.RIGHT, padx=(0, 8)
        )
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
        dialog.grab_set()

    def _send_failed(self, error: str) -> None:
        self.session.mark_failed()
        self.send_button.configure(state=tk.NORMAL)
        self.status.configure(text="Не удалось отправить публикацию")
        if self.session.publishing_from_editor:
            self._write_editor_status(f"Ошибка публикации: {error}")
            self.session.publishing_from_editor = False
            self.session.finalized_plain_parts = None
            return
        messagebox.showerror("Ошибка публикации", error, parent=self.root)

    def _send_succeeded(self, count: int) -> None:
        count = self.session.complete(count)
        self.resend_button.configure(state=tk.DISABLED)
        self.send_button.configure(state=tk.NORMAL)
        self.status.configure(text=f"Опубликовано. Всего отправлено сообщений: {count}")
        if self.session.publishing_from_editor:
            self._write_editor_status(
                f"Опубликовано. Отправлено сообщений: {count}",
            )
            self.session.publishing_from_editor = False
            self.session.finalized_plain_parts = None
            return
        messagebox.showinfo("Публикация завершена", f"Отправлено сообщений: {count}", parent=self.root)


def run_app() -> None:
    """Создать и запустить главное окно."""
    root = tk.Tk()
    root.withdraw()
    PublisherWindow(root)
    root.mainloop()
