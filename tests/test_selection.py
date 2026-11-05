# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Qrzzzz
"""User-visible interaction, concurrency and failure-path coverage; no QQ messages."""
import asyncio
import time
import types
from unittest.mock import AsyncMock, Mock

import pytest

from test_host_routing import module, plugin


def setup(count=3):
    p = plugin()
    p.ctx.logger.error = Mock()
    p._error_log = types.SimpleNamespace(error=Mock(), exception=Mock())
    songs = [module.SongInfo(str(i + 100), f"Song {i}", "Artist", "Album", "qq") for i in range(count)]
    api = types.SimpleNamespace(search=AsyncMock(return_value=songs))
    p._get_api = lambda: api
    p._send_song = AsyncMock(return_value=True)
    return p, api, songs


async def search(p, user="alice", stream="group", **kw):
    return await p._do_search_and_send("Song", "qq", stream, user_id=user, **kw)


@pytest.mark.asyncio
async def test_default_waits_and_includes_metadata_and_controls():
    p, api, songs = setup()
    ok, message = await search(p)
    assert ok and "等待用户选择" in message
    menu = p.ctx.send.text.await_args.args[0]
    assert "[QQ]" in menu and "Artist" in menu and "Album" in menu
    assert "发起人 alice" in menu
    assert "/换源" in menu and "/取消选歌" in menu
    p._send_song.assert_not_awaited()


@pytest.mark.asyncio
async def test_commands_and_tool_share_user_state_and_override_mode():
    p, api, songs = setup()
    result = await p.handle_search_music(query="Song", music_platform="qq", stream_id="group", user_id="alice", platform="qq")
    assert result["status"] == "success"
    result = await p.handle_select_command(stream_id="group", user_id="alice", text="/选歌 2 卡片")
    assert result[0]
    p._send_song.assert_awaited_once_with(songs[1], "group", mode="card", silent=True)
    assert not p._pending_choices


@pytest.mark.asyncio
async def test_tool_platform_does_not_collide_with_host_transport_platform():
    p, api, _ = setup()
    await p.handle_search_music(query="Song", music_platform="163", stream_id="group", user_id="alice", platform="qq")
    api.search.assert_awaited_once_with("Song", "163", limit=10)


@pytest.mark.asyncio
async def test_two_users_and_two_chats_do_not_share_selection():
    p, api, _ = setup()
    await search(p)
    await search(p, "bob")
    assert not (await p._selection_action("private", "alice", "select", index=1))[0]
    assert not (await p._selection_action("group", "eve", "select", index=1))[0]
    assert (await p._selection_action("group", "alice", "cancel"))[0]
    assert ("group", "bob") in p._pending_choices


@pytest.mark.asyncio
async def test_missing_host_identity_fails_closed_without_search():
    p, api, _ = setup()
    assert not (await search(p, user=""))[0]
    api.search.assert_not_awaited()
    assert not p._pending_choices


@pytest.mark.asyncio
async def test_pagination_preserves_global_numbering_and_rejects_bounds():
    p, api, _ = setup(12)
    await search(p)
    assert not (await p._selection_action("group", "alice", "previous"))[0]
    assert (await p._selection_action("group", "alice", "next"))[0]
    menu = p.ctx.send.text.await_args.args[0]
    assert "6. [QQ]" in menu and "第 2/3 页" in menu
    assert not (await p._selection_action("group", "alice", "select", index=13))[0]
    assert not (await p._selection_action("group", "alice", "select", index=0))[0]
    assert ("group", "alice") in p._pending_choices


@pytest.mark.asyncio
async def test_expiration_removes_only_idle_state():
    p, api, _ = setup()
    await search(p)
    p._pending_choices[("group", "alice")].created = time.monotonic() - 301
    assert not (await p._selection_action("group", "alice", "select", index=1))[0]
    assert not p._pending_choices


@pytest.mark.asyncio
async def test_send_failure_retains_selection_for_retry():
    p, api, songs = setup()
    await search(p)
    p._send_song.return_value = False
    ok, message = await p._selection_action("group", "alice", "select", index=2)
    assert not ok and "保留候选" in message
    p._send_song.return_value = True
    assert (await p._selection_action("group", "alice", "select", index=2, send_mode="链接"))[0]
    assert p._send_song.await_args.kwargs["mode"] == "link"


@pytest.mark.asyncio
async def test_concurrent_selection_is_sent_once_and_cannot_be_overwritten():
    p, api, songs = setup()
    await search(p)
    started, release = asyncio.Event(), asyncio.Event()

    async def send(*args, **kwargs):
        started.set()
        await release.wait()
        return True

    p._send_song.side_effect = send
    task = asyncio.create_task(p._selection_action("group", "alice", "select", index=1))
    await started.wait()
    assert not (await p._selection_action("group", "alice", "select", index=1))[0]
    assert not (await search(p))[0]
    assert not (await p._selection_action("group", "alice", "cancel"))[0]
    release.set()
    assert (await task)[0]
    p._send_song.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_search_discards_late_results():
    p, api, songs = setup()
    started, release = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await release.wait()
        return songs

    api.search.side_effect = slow
    task = asyncio.create_task(search(p))
    await started.wait()
    assert (await p._selection_action("group", "alice", "cancel"))[0]
    release.set()
    assert not (await task)[0]
    assert not p._pending_choices
    p.ctx.send.text.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_search_round_robin_and_partial_failure():
    p, api, songs = setup()
    netease = module.SongInfo("300", "Other", "Artist", "", "163")
    api.search.side_effect = [songs, [netease]]
    assert (await p._do_search_and_send("Song", "全部", "group", user_id="alice"))[0]
    assert [s.platform for s in p._pending_choices[("group", "alice")].results][:3] == ["qq", "163", "qq"]
    api.search.side_effect = [songs, module.MusicAPIResponseError("unavailable")]
    ok, text = await p._do_search_and_send("Song", "auto", "group", user_id="alice")
    assert ok and "部分音源" in text
    p.ctx.logger.exception.assert_not_called()
    p._error_log.error.assert_called_once()


@pytest.mark.asyncio
async def test_errors_log_protocol_diagnostics_and_unexpected_tracebacks():
    p, api, _ = setup()
    api.search.side_effect = module.MusicAPIResponseError("code=2001")
    assert not (await search(p))[0]
    p.ctx.logger.error.assert_called_once()
    p._error_log.error.assert_called_once()
    p.ctx.logger.exception.assert_not_called()
    api.search.side_effect = RuntimeError("unexpected")
    assert not (await search(p))[0]
    p.ctx.logger.exception.assert_called_once()
    p._error_log.exception.assert_called_once()


@pytest.mark.asyncio
async def test_explicit_source_does_not_switch_platform_and_keeps_query():
    p, api, _ = setup()
    await search(p, send_mode="card")
    assert (await p._selection_action("group", "alice", "source", music_platform="网易"))[0]
    api.search.assert_awaited_with("Song", "163", limit=10)
    assert p._pending_choices[("group", "alice")].mode == "card"
    api.search.side_effect = module.MusicAPIResponseError("down")
    assert not (await search(p))[0]
    assert api.search.await_args.args[1] == "qq"


@pytest.mark.asyncio
async def test_invalid_mode_and_platform_do_not_search_or_consume_selection():
    p, api, _ = setup()
    assert not (await search(p, send_mode="invalid"))[0]
    assert not (await p._do_search_and_send("Song", "invalid", "group", user_id="alice"))[0]
    api.search.assert_not_awaited()
    await search(p)
    assert not (await p._selection_action("group", "alice", "select", index=1, send_mode="invalid"))[0]
    assert ("group", "alice") in p._pending_choices


@pytest.mark.asyncio
async def test_menu_send_failure_does_not_leave_invisible_selection():
    p, api, _ = setup()
    p.ctx.send.text.return_value = False
    assert not (await search(p))[0]
    assert not p._pending_choices


@pytest.mark.asyncio
async def test_explicit_auto_select_setting_is_preserved_and_shared_by_tools():
    p, api, songs = setup()
    config = p.get_default_config(); config["music"]["auto_select_first"] = True
    p.set_plugin_config(config)
    result = await p.handle_search_music(query="Song", music_platform="qq", stream_id="group", user_id="alice")
    assert result["status"] == "success"
    p._send_song.assert_awaited_once_with(songs[0], "group", mode="voice", silent=True)


@pytest.mark.asyncio
async def test_command_mode_flag_and_custom_prefix():
    p, api, _ = setup()
    config = p.get_default_config(); config["music"]["command_prefix"] = "#"
    p.set_plugin_config(config)
    assert not (await p.handle_music_command(stream_id="group", user_id="alice", text="/点歌 QQ Song"))[0]
    assert (await p.handle_music_command(stream_id="group", user_id="alice", text="#点歌 QQ Song --模式 卡片"))[0]
    assert p._pending_choices[("group", "alice")].mode == "卡片"
    result = await p.handle_select_music(action="select", index=1, send_mode="link", stream_id="group", user_id="alice")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_qq_card_resolves_numeric_id_via_platform_metadata():
    p = plugin()
    song = module.SongInfo("mid", "Song", "Artist", "", "qq")
    detail = module.SongInfo("mid", "Song", "Artist", "", "qq", numeric_id="123")
    api = types.SimpleNamespace(get_qq_song_detail=AsyncMock(return_value=detail))
    p._get_api = lambda: api
    assert await p._send_music_card(song, "group")
    p.ctx.send.custom.assert_awaited_once_with("music", {"type": "qq", "id": "123"}, "group")


@pytest.mark.asyncio
async def test_card_resolution_rejects_wrong_identity_and_uses_explicit_link_fallback():
    p = plugin()
    song = module.SongInfo("mid", "Song", "Artist", "", "qq")
    detail = module.SongInfo("different", "Other", "Artist", "", "qq", numeric_id="123")
    p._get_api = lambda: types.SimpleNamespace(get_qq_song_detail=AsyncMock(return_value=detail))
    assert await p._send_music_card(song, "group")
    p.ctx.send.custom.assert_not_awaited()
    assert "标准音乐卡片不可用" in p.ctx.send.text.await_args.args[0]


@pytest.mark.asyncio
async def test_failed_card_and_link_are_not_reported_as_success():
    p = plugin()
    p.ctx.send.custom.return_value = False
    p.ctx.send.text.return_value = False
    song = module.SongInfo("123", "Song", "Artist", "", "163")
    assert not await p._send_song(song, "group", mode="card")
    assert not await p._send_song(song, "group", mode="link")


@pytest.mark.asyncio
async def test_link_override_does_not_mutate_config_or_prepare_audio():
    p = plugin()
    p._get_api = Mock(side_effect=AssertionError("Link must not download audio"))
    assert await p._send_song(module.SongInfo("123", "Song", "", "", "163"), "group", mode="link")
    assert p.config.music.play_mode == "voice"
    p.ctx.send.custom.assert_not_awaited()


@pytest.mark.asyncio
async def test_state_capacity_is_bounded():
    p, api, _ = setup()
    for i in range(256):
        p._pending_choices[("group", str(i))] = module.PendingSelection("Song", "qq")
    assert not (await search(p))[0]
    api.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_deadline_cancels_provider_and_cleans_state(monkeypatch):
    p, api, _ = setup()
    cancelled = asyncio.Event()
    original = asyncio.wait_for

    async def slow(*args, **kwargs):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    api.search.side_effect = slow
    monkeypatch.setattr(module.asyncio, "wait_for", lambda coro, timeout: original(coro, .01))
    assert not (await search(p))[0]
    assert cancelled.is_set() and not p._pending_choices


@pytest.mark.asyncio
async def test_new_search_supersedes_old_result_without_overwriting_menu():
    p, api, songs = setup()
    started, release = asyncio.Event(), asyncio.Event()

    async def query(text, *args, **kwargs):
        if text == "Old":
            started.set()
            await release.wait()
        return songs

    api.search.side_effect = query
    old = asyncio.create_task(p._do_search_and_send("Old", "qq", "group", user_id="alice"))
    await started.wait()
    assert (await search(p))[0]
    release.set()
    assert not (await old)[0]
    assert p._pending_choices[("group", "alice")].query == "Song"
    p.ctx.send.text.assert_awaited_once()


def test_legacy_migration_keeps_explicit_preferences():
    p = plugin()
    config, _ = p.normalize_plugin_config({"plugin": {"config_version": "1.1.1"},
        "music": {"auto_select_first": True, "default_platform": "163", "play_mode": "card"}})
    assert config["music"]["auto_select_first"] is True
    assert config["music"]["default_platform"] == "163"
    assert config["music"]["play_mode"] == "card"
    assert config["plugin"]["config_version"] == "1.2.0"


@pytest.mark.asyncio
async def test_card_default_initializes_cache_for_per_request_voice(tmp_path, monkeypatch):
    p = plugin()
    p._ctx.paths = types.SimpleNamespace(data_dir=tmp_path)
    config = p.get_default_config(); config["music"]["play_mode"] = "card"
    p.set_plugin_config(config)
    monkeypatch.setattr(module.shutil, "which", lambda _: "/tools/ffmpeg")
    await p.on_load()
    try:
        assert p._audio_cache is not None
        p._send_voice_audio = AsyncMock(return_value=True)
        song = module.SongInfo("123", "Song", "", "", "163")
        assert await p._send_song(song, "group", mode="voice")
        p._send_voice_audio.assert_awaited_once_with(song, "group", silent=False)
        assert p.config.music.play_mode == "card"
    finally:
        await p.on_unload()


@pytest.mark.asyncio
async def test_link_only_install_does_not_require_ffmpeg(tmp_path, monkeypatch):
    p = plugin()
    p._ctx.paths = types.SimpleNamespace(data_dir=tmp_path)
    config = p.get_default_config(); config["music"]["play_mode"] = "link"
    p.set_plugin_config(config)
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    await p.on_load()
    await p.on_unload()
