"""Проверки протокола обмена визуального редактора с управляющей частью."""

import json

from telegram_publisher.editor import EditorApi


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
