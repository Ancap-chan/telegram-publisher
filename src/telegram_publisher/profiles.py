"""Хранение профилей каналов и секретов."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring


KEYRING_SERVICE = "Telegram Publisher"


@dataclass(frozen=True)
class ChannelProfile:
    """Настройки одного канала публикации."""

    profile_id: str
    name: str
    chat_id: str
    token: str


def _config_file() -> Path:
    """Вернуть путь к локальному файлу настроек пользователя."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "TelegramPublisher" / "profiles.json"


CONFIG_FILE = _config_file()


def _read_records() -> list[dict[str, Any]]:
    if not CONFIG_FILE.exists():
        return []
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Не удалось прочитать настройки каналов: {error}") from error
    if not isinstance(data, list):
        raise ValueError("Файл настроек каналов имеет неверный формат.")
    return [item for item in data if isinstance(item, dict)]


def load_profiles() -> list[ChannelProfile]:
    """Загрузить профили; токены извлекаются из системного хранилища секретов."""
    profiles: list[ChannelProfile] = []
    for record in _read_records():
        profile_id = str(record.get("id", "")).strip()
        name = str(record.get("name", "")).strip()
        chat_id = str(record.get("chat_id", "")).strip()
        if not profile_id or not name or not chat_id:
            continue
        token = keyring.get_password(KEYRING_SERVICE, profile_id) or ""
        profiles.append(ChannelProfile(profile_id, name, chat_id, token))
    return profiles


def save_profile(
    name: str,
    token: str,
    chat_id: str,
    profile_id: str | None = None,
) -> ChannelProfile:
    """Создать или обновить профиль, сохранив токен в системном хранилище."""
    name = name.strip()
    token = token.strip()
    chat_id = chat_id.strip()
    if not name or not token or not chat_id:
        raise ValueError("Заполни название профиля, токен бота и идентификатор канала.")

    current_id = profile_id or str(uuid.uuid4())
    keyring.set_password(KEYRING_SERVICE, current_id, token)

    records = _read_records()
    updated = {"id": current_id, "name": name, "chat_id": chat_id}
    for index, record in enumerate(records):
        if record.get("id") == current_id:
            records[index] = updated
            break
    else:
        records.append(updated)

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = CONFIG_FILE.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_file.replace(CONFIG_FILE)
    return ChannelProfile(current_id, name, chat_id, token)


def delete_profile(profile_id: str) -> None:
    """Удалить профиль и его токен из системного хранилища."""
    records = [record for record in _read_records() if record.get("id") != profile_id]
    if CONFIG_FILE.exists() or records:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = CONFIG_FILE.with_suffix(".tmp")
        temporary_file.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_file.replace(CONFIG_FILE)
    try:
        keyring.delete_password(KEYRING_SERVICE, profile_id)
    except keyring.errors.PasswordDeleteError:
        pass
