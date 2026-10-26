"""Проверки разметки диалога настройки каналов."""

from telegram_publisher.editor import EDITOR_HTML


def test_channel_settings_use_a_dedicated_html_dialog():
    assert 'id="channel-dialog-backdrop"' in EDITOR_HTML
    assert 'role="dialog" aria-modal="true"' in EDITOR_HTML
    assert 'id="channel-profile-list"' in EDITOR_HTML
    assert 'id="channel-profile-name"' in EDITOR_HTML
    assert 'id="channel-profile-chat-id"' in EDITOR_HTML
    assert 'id="channel-profile-token"' in EDITOR_HTML


def test_channel_dialog_supports_profile_management_without_prompt_menu():
    assert "channel-profile-add" in EDITOR_HTML
    assert "channel-profile-save" in EDITOR_HTML
    assert "channel-profile-delete" in EDITOR_HTML
    assert "window.pywebview.api.get_profiles()" in EDITOR_HTML
    assert "window.pywebview.api.save_channel_profile(name,chatId,token,editingProfileId)" in EDITOR_HTML
    assert "window.pywebview.api.delete_channel_profile(profile.profile_id)" in EDITOR_HTML
    assert "prompt('Управление каналами:" not in EDITOR_HTML


def test_channel_dialog_does_not_render_saved_bot_tokens():
    assert "При пустом поле действующий токен останется без изменений." in EDITOR_HTML
    assert "channelProfileToken.value='';" in EDITOR_HTML
