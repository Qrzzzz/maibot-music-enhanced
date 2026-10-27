# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Qrzzzz
"""Host RPC routing, migration and frozen upstream encoder contract coverage."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from maibot_sdk.context import PluginContext, PluginPaths

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = types.ModuleType("music_host_route_tests")
PACKAGE.__path__ = [str(ROOT)]
sys.modules[PACKAGE.__name__] = PACKAGE
spec = importlib.util.spec_from_file_location(PACKAGE.__name__ + ".plugin", ROOT / "plugin.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def encoder(name):
    folder = ROOT / "tests/fixtures/adapters"
    metadata = next(item for item in json.loads((folder / "provenance.json").read_text(encoding="utf-8")) if item["name"] == name)
    path = folder / (name + "_encoder.py")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata["fixture_sha256"]
    spec = importlib.util.spec_from_file_location("contract_" + name, path)
    target = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(target)
    return target.AdapterEncoder()


def plugin():
    instance = module.create_plugin()
    instance.set_plugin_config(instance.get_default_config())
    instance._ctx = types.SimpleNamespace(
        logger=types.SimpleNamespace(warning=Mock(), info=Mock(), exception=Mock()),
        send=types.SimpleNamespace(custom=AsyncMock(return_value=True), text=AsyncMock(return_value=True)))
    return instance


@pytest.mark.parametrize("name", ["napcat", "unified"])
@pytest.mark.parametrize("stream", ["qq-group-session", "qq-private-session"])
@pytest.mark.asyncio
async def test_voice_uses_sdk_capability_and_both_upstream_record_encoders(tmp_path, name, stream):
    instance = module.create_plugin()
    instance.set_plugin_config(instance.get_default_config())
    calls = []

    async def rpc(method, plugin_id, payload):
        calls.append((method, plugin_id, payload))
        return True

    instance._set_context(PluginContext("github.qrzzzz.music-enhanced", rpc_call=rpc,
        paths=PluginPaths(tmp_path, tmp_path / "runtime")))
    media = tmp_path / "full_qq_song.mp3"
    cache = types.SimpleNamespace(adapter_path=lambda path: "/shared/music/" + path.name, release=AsyncMock())
    instance._audio_cache = cache
    api = types.SimpleNamespace(prepare_local_audio=AsyncMock(return_value=media))
    instance._get_api = lambda: api
    song = module.SongInfo("song-mid", "Song", "Artist", "", "qq")
    assert await instance._send_song(song, stream)
    assert len(calls) == 1 and calls[0][0] == "cap.call"
    payload = calls[0][2]
    assert payload["capability"] == "send.custom"
    args = payload["args"]
    assert args["stream_id"] == stream and args["custom_type"] == "voiceurl"
    segments = encoder(name)._build_voiceurl_segments({"data": args["data"]})
    assert segments == [{"type": "record", "data": {"file": "file:///shared/music/full_qq_song.mp3"}}]
    cache.release.assert_awaited_once_with(media)


@pytest.mark.parametrize("name", ["napcat", "unified"])
@pytest.mark.parametrize("platform", ["qq", "163"])
@pytest.mark.asyncio
async def test_standard_card_uses_host_and_supported_upstream_shape(name, platform):
    instance = plugin()
    song = module.SongInfo("12345", "Song", "Artist", "", platform)
    assert await instance._send_music_card(song, "stream")
    args = instance.ctx.send.custom.await_args.args
    assert args == ("music", {"type": platform, "id": "12345"}, "stream")
    assert encoder(name)._build_music_segments({"data": args[1]}) == [{"type": "music", "data": args[1]}]


@pytest.mark.asyncio
async def test_qq_mid_card_sends_public_link_without_client_calls():
    instance = plugin()
    instance._get_api = Mock(side_effect=AssertionError("Cards must not use a client API"))
    song = module.SongInfo("song-mid", "Song", "Artist", "", "qq")
    assert await instance._send_music_card(song, "stream")
    instance.ctx.send.custom.assert_not_awaited()
    assert "https://y.qq.com/n/ryqq/songDetail/song-mid" in instance.ctx.send.text.await_args.args[0]


@pytest.mark.asyncio
async def test_unsupported_card_falls_back_to_host_link_and_reports_text_failure():
    instance = plugin()
    instance.ctx.send.custom.return_value = False
    instance.ctx.send.text.return_value = False
    song = module.SongInfo("123", "Song", "Artist", "", "163")
    assert not await instance._send_music_card(song, "stream")
    assert "https://music.163.com/song?id=123" in instance.ctx.send.text.await_args.args[0]


def test_config_migration_removes_client_credentials_and_keeps_explicit_reader_paths():
    instance = module.create_plugin()
    original = {"plugin": {"enabled": True, "config_version": "1.0.0"},
                "napcat": {"http_url": "http://127.0.0.1:9999", "http_token": "migration-secret"},
                "music": {"cache_napcat_dir": "/app/old-cache"}}
    normalized, changed = instance.normalize_plugin_config(original)
    assert changed and normalized["plugin"]["config_version"] == module.PLUGIN_VERSION
    assert normalized["music"]["cache_reader_dir"] == "/app/old-cache"
    assert "cache_napcat_dir" not in normalized["music"] and "napcat" not in normalized
    assert "migration-secret" not in json.dumps(normalized)
    assert original["music"]["cache_napcat_dir"] == "/app/old-cache"
    original["music"]["cache_reader_dir"] = "/app/new-cache"
    assert instance.normalize_plugin_config(original)[0]["music"]["cache_reader_dir"] == "/app/new-cache"


@pytest.mark.asyncio
async def test_share_link_uses_host_text_and_canonical_platform_metadata():
    instance = plugin()
    config = instance.get_default_config(); config["music"]["auto_parse_card"] = True
    instance.set_plugin_config(config)
    song = module.SongInfo("123", "Canonical Song", "Canonical Artist", "", "163")
    api = types.SimpleNamespace(get_song_detail=AsyncMock(return_value=song))
    instance._get_api = lambda: api
    instance._send_song = AsyncMock(return_value=True)
    result = await instance.handle_music_url_parse(message={"session_id": "stream",
        "processed_plain_text": "[网易云音乐] Song - Artist 链接: https://music.163.com/song?id=123"})
    assert result == {"action": "abort"}
    api.get_song_detail.assert_awaited_once_with("123", "163")
    instance._send_song.assert_awaited_once_with(song, "stream")


@pytest.mark.asyncio
async def test_missing_share_link_prompts_instead_of_fetching_client_or_searching():
    instance = plugin()
    config = instance.get_default_config(); config["music"]["auto_parse_card"] = True
    instance.set_plugin_config(config)
    instance._get_api = Mock(side_effect=AssertionError("No raw-message or search lookup"))
    assert await instance.handle_music_url_parse(message={"session_id": "stream",
        "processed_plain_text": "[QQ音乐] Song - Artist"}) == {"action": "abort"}
    assert "请补发" in instance.ctx.send.text.await_args.args[0]


@pytest.mark.asyncio
async def test_native_download_rejects_redirect_to_localhost_even_with_redirecting_client(tmp_path):
    cache_module = sys.modules[PACKAGE.__name__ + ".audio_cache"]
    seen = []

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/internal"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True)
    cache = cache_module.MusicAudioCache(str(tmp_path), str(tmp_path), max_size_bytes=1024,
        expire_seconds=86400, max_file_size_bytes=1024, download_timeout_seconds=10, client=client)
    try:
        with pytest.raises(cache_module.AudioCacheError, match="域名"):
            await cache.get_or_download("qq", "id", "https://aqqmusic.tc.qq.com/song.mp3")
        assert len(seen) == 1 and not list(tmp_path.iterdir()) and not cache._active_paths
    finally:
        await client.aclose()


def test_no_client_api_or_undeclared_chat_lookup_remains():
    source = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in ("plugin.py", "music_api.py"))
    for forbidden in ("get_all_streams", "/send_group_msg", "/send_private_msg", "/get_msg", "napcat_send_message", "get_raw_message"):
        assert forbidden not in source


@pytest.mark.asyncio
async def test_tool_link_fallback_does_not_claim_audio_was_played():
    instance = plugin()
    config = instance.get_default_config(); config["music"]["play_mode"] = "card"
    instance.set_plugin_config(config)
    song = module.SongInfo("song-mid", "Song", "Artist", "", "qq")
    instance._get_api = lambda: types.SimpleNamespace(search=AsyncMock(return_value=[song]))
    result = await instance.handle_search_music(query="Song Artist", stream_id="stream")
    assert "已发送歌曲卡片或链接" in result["content"] and "已播放" not in result["content"]
    instance.ctx.send.custom.assert_not_awaited()
