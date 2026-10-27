# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Qrzzzz
"""Cover portable deployment defaults and full-audio send integration."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import tomllib
import types
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
NAME = "music_enhanced_distribution_tests"
package = types.ModuleType(NAME)
package.__path__ = [str(ROOT)]
sys.modules[NAME] = package
spec = importlib.util.spec_from_file_location(NAME + ".plugin", ROOT / "plugin.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def plugin_for(tmp_path):
    plugin = module.create_plugin()
    plugin.set_plugin_config(plugin.get_default_config())
    plugin._ctx = types.SimpleNamespace(paths=types.SimpleNamespace(data_dir=tmp_path),
        logger=types.SimpleNamespace(info=Mock(), warning=Mock(), exception=Mock()),
        send=types.SimpleNamespace(custom=AsyncMock(return_value=True), text=AsyncMock()))
    return plugin


def test_example_config_matches_generated_defaults():
    template = tomllib.loads((ROOT / "config.example.toml").read_text(encoding="utf-8"))
    assert template == module.create_plugin().get_default_config()


@pytest.mark.asyncio
async def test_default_cache_uses_sdk_data_dir_and_survives_config_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda name: "/tools/" + name)
    plugin = plugin_for(tmp_path)
    await plugin.on_load()
    try:
        expected = tmp_path / "audio_cache"
        assert plugin._audio_cache.storage_dir == expected
        media = expected / "full_qq_test.mp3"
        assert Path(plugin._audio_cache.adapter_path(media)) == media
        await plugin.on_config_update("self", {}, "changed")
        assert plugin._audio_cache.storage_dir == expected
    finally:
        await plugin.on_unload()
    assert plugin._cache_cleanup_task is None and plugin._audio_cache is None


@pytest.mark.asyncio
async def test_explicit_adapter_cache_mapping_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda name: "/tools/" + name)
    plugin = plugin_for(tmp_path)
    config = plugin.get_default_config()
    config["music"].update(cache_storage_dir=str(tmp_path / "shared"), cache_reader_dir="/app/music-cache")
    plugin.set_plugin_config(config)
    await plugin.on_load()
    try:
        media = plugin._audio_cache.storage_dir / "test.mp3"
        assert plugin._audio_cache.adapter_path(media) == "/app/music-cache/test.mp3"
    finally:
        await plugin.on_unload()


@pytest.mark.asyncio
async def test_missing_ffmpeg_gives_actionable_startup_error(tmp_path, monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    plugin = plugin_for(tmp_path)
    with pytest.raises(module.AudioCacheError, match="FFmpeg.*PATH"):
        await plugin.on_load()
    assert plugin._audio_cache is None and plugin._error_log is None


@pytest.mark.asyncio
async def test_full_audio_send_releases_pinned_file_after_adapter_failure(tmp_path):
    plugin = plugin_for(tmp_path)
    media = tmp_path / "full_qq_test.mp3"
    cache = types.SimpleNamespace(adapter_path=lambda path: str(path), release=AsyncMock())
    plugin._audio_cache = cache
    api = types.SimpleNamespace(prepare_local_audio=AsyncMock(return_value=media))
    plugin._get_api = lambda: api
    plugin.ctx.send.custom.side_effect = RuntimeError("adapter failed")
    song = module.SongInfo("test", "Song", "Artist", "", "qq")
    assert not await plugin._send_song(song, "stream", silent=True)
    api.prepare_local_audio.assert_awaited_once_with(song, cache)
    cache.release.assert_awaited_once_with(media)
    assert plugin._active_voice_sends == 0
