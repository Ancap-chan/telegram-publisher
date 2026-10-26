"""Проверки API визуального редактора."""

import json

import pytest

import telegram_publisher.editor as editor_module
from telegram_publisher.editor import EditorApi
from telegram_publisher.profiles import ChannelProfile
from telegram_publisher.publishing import PartialPublicationError


class FakeWindow:
    """Минимальная заглушка окна для проверки API редактора."""


def test_editor_api_returns_profiles_without_tokens(tmp_path, monkeypatch):
    profiles = [
        ChannelProfile("profile-1", "Основной канал", "@main", "секретный-токен"),
    ]
    monkeypatch.setattr(editor_module, "load_profiles", lambda: profiles)
    api = EditorApi(FakeWindow())

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
    api = EditorApi(FakeWindow())

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
    api = EditorApi(FakeWindow())

    with pytest.raises(ValueError, match="нужно указать токен"):
        api.save_channel_profile("Канал", "@channel", "", "profile-1")


def test_editor_api_deletes_profile_and_returns_remaining_profiles(tmp_path, monkeypatch):
    deleted = []
    monkeypatch.setattr(editor_module, "delete_profile", lambda profile_id: deleted.append(profile_id))
    monkeypatch.setattr(editor_module, "load_profiles", lambda: [])

    api = EditorApi(FakeWindow())

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
    api = EditorApi(FakeWindow())

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


@pytest.mark.parametrize("mode", ["plain", "plain_series"])
def test_editor_api_publishes_plain_content_without_review_flow(monkeypatch, mode):
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
    api = EditorApi(FakeWindow())

    api.publish({
        "action": "publish",
        "html": "<p>Текст</p>",
        "parts": ["<p>Часть 1</p>", "<p>Часть 2</p>"] if mode == "plain_series" else [],
        "mode": mode,
        "profile_id": "profile-1",
        "series": mode == "plain_series",
    })

    assert captured["request"].profile == profile
    assert captured["request"].content == "<p>Текст</p>"
    assert captured["request"].mode == mode
    assert captured["request"].parts == (["<p>Часть 1</p>", "<p>Часть 2</p>"] if mode == "plain_series" else [])
    assert api.get_status() == {"message": "Опубликовано. Отправлено сообщений: 2", "clear": True}


def test_editor_api_rejects_publish_when_profile_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(editor_module, "load_profiles", lambda: [])
    api = EditorApi(FakeWindow())

    with pytest.raises(ValueError, match="Настройки выбранного канала"):
        api.publish({"mode": "rich", "html": "<p>Текст</p>", "profile_id": "missing"})



def test_editor_api_stores_partial_publication_and_exposes_retry(tmp_path, monkeypatch):
    profile = ChannelProfile("profile-1", "Канал", "@channel", "token")
    monkeypatch.setattr(editor_module, "load_profiles", lambda: [profile])
    requests = []

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()

    class FakeController:
        def publish(self, request):
            requests.append(request)
            if len(requests) == 1:
                raise PartialPublicationError(2, ["<p>Остаток 1</p>", "<p>Остаток 2</p>"], 4)
            return len(request.parts)

    monkeypatch.setattr(editor_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(editor_module, "PublicationController", FakeController)
    api = EditorApi(FakeWindow())

    api.publish({
        "action": "publish",
        "html": "<p>Полный текст</p>",
        "parts": ["<p>Часть 1</p>", "<p>Часть 2</p>", "<p>Часть 3</p>", "<p>Часть 4</p>"],
        "mode": "plain_series",
        "profile_id": "profile-1",
        "series": True,
    })

    status = api.get_status()
    assert status["can_retry"] is True
    assert "Осталось сообщений: 2" in status["message"]
    assert api._pending_sent_count == 2
    assert api._pending_messages == ["<p>Остаток 1</p>", "<p>Остаток 2</p>"]

    api.retry_pending()

    assert requests[1].mode == "plain_prepared"
    assert requests[1].parts == ["<p>Остаток 1</p>", "<p>Остаток 2</p>"]
    assert requests[1].initial_delay == 5
    assert api.get_status() == {
        "message": "Опубликовано. Отправлено сообщений: 4",
        "clear": True,
    }
    assert api._pending_messages == []


def test_editor_api_accumulates_sent_count_when_retry_is_partial(tmp_path, monkeypatch):
    profile = ChannelProfile("profile-1", "Канал", "@channel", "token")
    monkeypatch.setattr(editor_module, "load_profiles", lambda: [profile])

    class ImmediateThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            self.target()

    class FakeController:
        def publish(self, request):
            raise PartialPublicationError(1, ["<p>Последнее сообщение</p>"], 3)

    monkeypatch.setattr(editor_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(editor_module, "PublicationController", FakeController)
    api = EditorApi(FakeWindow())
    api._pending_profile = profile
    api._pending_messages = ["<p>Остаток 1</p>", "<p>Остаток 2</p>"]
    api._pending_sent_count = 2
    api._pending_retry_after = 1

    api.retry_pending()

    assert api._pending_sent_count == 3
    assert api._pending_messages == ["<p>Последнее сообщение</p>"]
    status = api.get_status()
    assert status["can_retry"] is True
    assert "Часть публикации отправлена: 3" in status["message"]


def test_editor_api_rejects_retry_without_pending_messages(tmp_path):
    api = EditorApi(FakeWindow())

    with pytest.raises(ValueError, match="Нет сообщений"):
        api.retry_pending()
