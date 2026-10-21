"""Проверки хранения профилей каналов."""

import json

import pytest

from telegram_publisher import profiles


@pytest.fixture
def profile_store(tmp_path, monkeypatch):
    credentials = {}

    monkeypatch.setattr(profiles, "CONFIG_FILE", tmp_path / "TelegramPublisher" / "profiles.json")
    monkeypatch.setattr(
        profiles.keyring,
        "set_password",
        lambda service, username, password: credentials.__setitem__((service, username), password),
    )
    monkeypatch.setattr(
        profiles.keyring,
        "get_password",
        lambda service, username: credentials.get((service, username)),
    )

    def delete_password(service, username):
        credentials.pop((service, username), None)

    monkeypatch.setattr(profiles.keyring, "delete_password", delete_password)
    return credentials


def test_profile_is_saved_without_token_in_json(profile_store):
    saved = profiles.save_profile("Тестовый канал", "секретный-токен", "@test_channel")

    raw = profiles.CONFIG_FILE.read_text(encoding="utf-8")
    assert "секретный-токен" not in raw
    assert json.loads(raw)[0]["chat_id"] == "@test_channel"
    assert profiles.load_profiles() == [saved]


def test_profile_can_be_updated(profile_store):
    saved = profiles.save_profile("Старое имя", "токен-1", "@channel", "profile-id")
    updated = profiles.save_profile("Новое имя", "токен-2", "-100123", saved.profile_id)

    assert updated.profile_id == saved.profile_id
    assert profiles.load_profiles() == [updated]


def test_profile_can_be_deleted(profile_store):
    saved = profiles.save_profile("Канал", "токен", "@channel")
    profiles.delete_profile(saved.profile_id)

    assert profiles.load_profiles() == []
    assert profile_store == {}
