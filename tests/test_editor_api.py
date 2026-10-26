"""Проверки протокола обмена визуального редактора с управляющей частью."""

import json

import pytest

import telegram_publisher.editor as editor_module
from telegram_publisher.editor import EditorApi
from telegram_publisher.profiles import ChannelProfile


class FakeWindow:
    """Минимальная заглушка окна для проверки протокола обмена."""


def test_editor_api_writes_publish_request(tmp_path):
    output_path = tmp_path / "result.json"
    api = EditorApi(output_path, tmp_path / "status.json", FakeWindow())
    request = {
        "action": "publish",
        "html": "<p>Текст публикации</p>",
        "mode": "rich",
        "profile_id": "profile-1",
    }

    api.publish(request)

    assert json.loads(output_path.read_text(encoding="utf-8")) == request


def test_editor_api_finish_writes_request_without_closing_editor(tmp_path):
    output_path = tmp_path / "result.json"
    api = EditorApi(output_path, tmp_path / "status.json", FakeWindow())

    api.finish({"action": "manage_profiles", "profile_id": "profile-1"})

    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "action": "manage_profiles",
        "profile_id": "profile-1",
    }


def test_editor_api_reads_status_once(tmp_path):
    status_path = tmp_path / "status.json"
    api = EditorApi(tmp_path / "result.json", status_path, FakeWindow())
    status_path.write_text(
        json.dumps({"message": "Публикация завершена", "clear": False}, ensure_ascii=False),
        encoding="utf-8",
    )

    assert api.get_status() == {"message": "Публикация завершена", "clear": False}
    assert not status_path.exists()
    assert api.get_status() is None


def test_editor_api_ignores_invalid_status_json(tmp_path):
    status_path = tmp_path / "status.json"
    api = EditorApi(tmp_path / "result.json", status_path, FakeWindow())
    status_path.write_text("{", encoding="utf-8")

    assert api.get_status() is None


def test_editor_api_returns_profiles_without_tokens(tmp_path, monkeypatch):
    profiles = [
        ChannelProfile("profile-1", "Основной канал", "@main", "секретный-токен"),
    ]
    monkeypatch.setattr(editor_module, "load_profiles", lambda: profiles)
    api = EditorApi(tmp_path / "result.json", tmp_path / "status.json", FakeWindow())

    assert api.get_profiles() == [
        {"profile_id": "profile-1", "name": "Основной канал", "chat_id": "@main"}
    ]


def test_editor_api_keeps_existing_token_when_editing_profile(tmp_path, monkeypatch):
    profiles = [
        ChannelProfile("profile-1", "Старое название", "@old", "секретный-токен"),
    ]
    saved = {}
    monkeypatch.setattr(editor_module, "load_profiles", lambda: profiles)

    def save_profile(name, token, chat_id, profile_id=None):
        saved.update(name=name, token=token, chat_id=chat_id, profile_id=profile_id)

    monkeypatch.setattr(editor_module, "save_profile", save_profile)
    api = EditorApi(tmp_path / "result.json", tmp_path / "status.json", FakeWindow())

    api.save_channel_profile("Новое название", "@new", "", "profile-1")

    assert saved == {
        "name": "Новое название",
        "token": "секретный-токен",
        "chat_id": "@new",
        "profile_id": "profile-1",
    }


def test_editor_api_requires_token_when_editing_profile_without_saved_secret(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        editor_module,
        "load_profiles",
        lambda: [ChannelProfile("profile-1", "Канал", "@channel", "")],
    )
    api = EditorApi(tmp_path / "result.json", tmp_path / "status.json", FakeWindow())

    with pytest.raises(ValueError, match="нужно указать токен"):
        api.save_channel_profile("Канал", "@channel", "", "profile-1")


def test_editor_api_deletes_profile_and_returns_remaining_profiles(tmp_path, monkeypatch):
    deleted = []
    monkeypatch.setattr(editor_module, "delete_profile", lambda profile_id: deleted.append(profile_id))
    monkeypatch.setattr(editor_module, "load_profiles", lambda: [])

    api = EditorApi(tmp_path / "result.json", tmp_path / "status.json", FakeWindow())

    assert api.delete_channel_profile("profile-1") == []
    assert deleted == ["profile-1"]

def test_editor_api_publishes_rich_content_in_background(tmp_path, monkeypatch):
    profile = ChannelProfile("profile-1", "Канал", "@channel", "token")
    captured = {}
    monkeypatch.setattr(editor_module, "load_profiles", lambda: [profile])

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()

    class FakeController:
        def publish(self, request):
            captured["request"] = request
            return 2

    monkeypatch.setattr(editor_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(editor_module, "PublicationController", FakeController)
    api = EditorApi(tmp_path / "result.json", tmp_path / "status.json", FakeWindow())

    api.publish({
        "action": "publish",
        "html": "<p>Текст</p>",
        "mode": "rich",
        "profile_id": "profile-1",
        "series": False,
    })

    assert captured["request"].profile == profile
    assert captured["request"].content == "<p>Текст</p>"
    assert api.get_status() == {"message": "Опубликовано. Отправлено сообщений: 2", "clear": True}


def test_editor_api_keeps_plain_messages_on_legacy_review_flow(tmp_path):
    output_path = tmp_path / "result.json"
    api = EditorApi(output_path, tmp_path / "status.json", FakeWindow())
    request = {"action": "review_publish", "html": "<p>Текст</p>", "mode": "plain"}

    api.publish(request)

    assert json.loads(output_path.read_text(encoding="utf-8")) == request


def test_editor_api_rejects_publish_when_profile_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(editor_module, "load_profiles", lambda: [])
    api = EditorApi(tmp_path / "result.json", tmp_path / "status.json", FakeWindow())

    with pytest.raises(ValueError, match="Настройки выбранного канала"):
        api.publish({"mode": "rich", "html": "<p>Текст</p>", "profile_id": "missing"})
