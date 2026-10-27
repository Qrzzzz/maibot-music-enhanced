# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Qrzzzz
"""Validate with the installed MaiBot loader in an isolated temporary instance; sends no messages."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def check() -> dict:
    from maibot_sdk.context import PluginContext, PluginPaths
    from src.plugin_runtime import detect_host_application_version
    from src.plugin_runtime.runner.manifest_validator import ManifestValidator
    from src.plugin_runtime.runner.plugin_loader import PluginLoader

    host_version = detect_host_application_version()
    validator = ManifestValidator(host_version=host_version)
    manifest = validator.load_from_plugin_path(ROOT)
    assert manifest is not None, validator.errors
    loader = PluginLoader(host_version=host_version)
    metadata = loader.load_candidate(manifest.id, (ROOT, manifest, ROOT / "plugin.py"))
    assert metadata is not None, "Official plugin loader failed"
    plugin = metadata.instance
    instance = Path(os.environ["MAIBOT_INSTANCE_DIR"])
    data_dir = instance / "data" / "plugins" / manifest.id
    runtime_dir = instance / "temp" / "plugins" / manifest.id
    data_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    rpc_calls = []

    async def block_rpc(*args, **kwargs):
        rpc_calls.append((args, kwargs))
        raise AssertionError("Host smoke check must not call host RPC")

    plugin._set_context(PluginContext(manifest.id, rpc_call=block_rpc, paths=PluginPaths(data_dir, runtime_dir)))
    plugin.set_plugin_config(plugin.get_default_config())
    components = plugin.get_components()
    assert any(c.get("name") == "search_and_play_music" for c in components)
    try:
        await plugin.on_load()
        assert plugin._audio_cache.storage_dir == data_dir / "audio_cache"
        plugin._get_api()  # Create clients without making network requests; reload must close them.
        await plugin.on_config_update("self", plugin.get_default_config(), "smoke")
        assert plugin._audio_cache.storage_dir == data_dir / "audio_cache"
    finally:
        await plugin.on_unload()
    assert plugin._audio_cache is None and plugin._api is None and not rpc_calls
    return {"status": "passed", "plugin_id": manifest.id, "version": manifest.version, "host_version": host_version,
            "manifest_validated_by_host": True, "official_loader_passed": True,
            "isolated_load_reload_unload": True, "components": len(components), "host_rpc_calls": len(rpc_calls), "qq_message_sent": False}


def main() -> None:
    if "--worker" in sys.argv:
        print("HOST_CHECK_JSON=" + json.dumps(asyncio.run(check()), ensure_ascii=False))
        return
    with tempfile.TemporaryDirectory(prefix="maibot-music-enhanced-check-") as temporary:
        env = dict(os.environ, MAIBOT_INSTANCE_DIR=temporary, PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker"], cwd=temporary,
                                env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        if result.returncode:
            print((result.stdout + result.stderr)[-8000:])
            raise SystemExit(result.returncode)
        line = next(line for line in result.stdout.splitlines() if line.startswith("HOST_CHECK_JSON="))
        print(json.dumps(json.loads(line.split("=", 1)[1]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
