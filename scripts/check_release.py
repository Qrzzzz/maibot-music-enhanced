# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Qrzzzz
"""Validate release sources or a release ZIP without contacting external services."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SLUG = "maibot-music-enhanced"
PLUGIN_ID = "github.qrzzzz.music-enhanced"
REQUIRED = (
    "_manifest.json", "plugin.py", "source_bridge.py", "music_api.py", "audio_cache.py",
    "url_parser.py", "error_log.py", "__init__.py", "LICENSE", "NOTICE.md", "README.md",
    "CHANGELOG.md", "UPSTREAM.json", "config.example.toml", "requirements.txt",
    "requirements-dev.txt", "pyproject.toml", "licenses/maibot-music-MIT.txt",
    "licenses/astrbot_plugin_music-GPL-3.0.txt", "docs/RELEASING.md", "docs/VALIDATION.md",
    "scripts/check_release.py", "scripts/build_release.py", "scripts/check_host.py",
    "tests/test_source_bridge.py", "tests/test_distribution.py",
    "scripts/release.py", "scripts/prepare_release.py", ".github/workflows/release.yml",
    "media_urls.py",
    "tests/test_host_routing.py", "tests/fixtures/adapters/provenance.json",
    "tests/fixtures/adapters/napcat_encoder.py", "tests/fixtures/adapters/unified_encoder.py",
    "docs/COMPATIBILITY.md",
)
FORBIDDEN_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "data", "logs", "dist", "build"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3", ".mp3", ".m4a", ".flac", ".part", ".pem", ".key"}


def check_file_names(names: list[str]) -> None:
    for name in names:
        path = PurePosixPath(name)
        assert not path.is_absolute() and ".." not in path.parts and "\\" not in name, f"Unsafe path: {name}"
        assert not FORBIDDEN_PARTS.intersection(path.parts), f"Runtime data in release: {name}"
        assert path.suffix.lower() not in FORBIDDEN_SUFFIXES, f"Private/generated file: {name}"
        assert path.name not in {"config.toml", ".env", "credentials.json"} and not path.name.startswith(".env."), f"Private config: {name}"


def check_tree(root: Path) -> dict:
    for name in REQUIRED:
        assert (root / name).is_file(), f"Missing release file: {name}"
    manifest = json.loads((root / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 2 and manifest["id"] == PLUGIN_ID
    assert manifest["license"] == "GPL-3.0-only" and manifest["author"]["name"] == "Qrzzzz"
    for value in (manifest["version"], *(v for key in ("host_application", "sdk") for v in manifest[key].values())):
        assert re.fullmatch(r"\d+\.\d+\.\d+", value), f"Invalid version: {value}"
        assert not {"99", "999"}.intersection(value.split(".")[:2]), f"Unsupported compatibility wildcard: {value}"
    assert manifest["urls"]["repository"] == "https://github.com/Qrzzzz/" + SLUG
    assert set(manifest["capabilities"]) == {"send.text", "send.custom"}
    config = tomllib.loads((root / "config.example.toml").read_text(encoding="utf-8"))
    assert config["plugin"]["config_version"] == manifest["version"]
    module = ast.parse((root / "plugin.py").read_text(encoding="utf-8"))
    versions = [ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "PLUGIN_VERSION" for target in node.targets)]
    assert versions == [manifest["version"]], "plugin.py PLUGIN_VERSION differs from manifest"
    assert re.search(r"^## " + re.escape(manifest["version"]) + r" — \d{4}-\d{2}-\d{2}$",
                     (root / "CHANGELOG.md").read_text(encoding="utf-8"), re.MULTILINE), "Missing versioned changelog"
    assert config["source_bridge"]["enabled"] and config["music"]["play_mode"] == "voice"
    assert config["music"]["voice_source"] == "local"
    assert config["music"]["cache_storage_dir"] == config["music"]["cache_reader_dir"] == ""
    assert "napcat" not in config, "Obsolete client HTTP configuration must not be distributed"
    for section, fields in {"netease": ("MUSIC_U", "csrf_token"), "qq": ("uin", "qqmusic_key",)}.items():
        assert all(config[section][field] == "" for field in fields), f"Credential in template: {section}"
    notice = (root / "NOTICE.md").read_text(encoding="utf-8")
    assert "基于磐冰的 maibot-music 增强，音源接入参考 Zhalslar 的 AstrBot 插件" in notice
    assert "GNU GENERAL PUBLIC LICENSE" in (root / "LICENSE").read_text(encoding="utf-8")
    provenance = json.loads((root / "UPSTREAM.json").read_text(encoding="utf-8"))
    original_license = next(item for item in provenance["base"]["files"] if item["path"] == "LICENSE")
    assert hashlib.sha256((root / "licenses/maibot-music-MIT.txt").read_bytes()).hexdigest() == original_license["sha256"]
    assert (root / "LICENSE").read_bytes() == (root / "licenses/astrbot_plugin_music-GPL-3.0.txt").read_bytes()
    return {"status": "passed", "plugin_id": manifest["id"], "version": manifest["version"], "required_files": len(REQUIRED), "credentials_in_template": False}


def check_archive(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as package, tempfile.TemporaryDirectory() as temporary:
        entries = package.infolist()
        assert entries and len(entries) <= 300, "Unexpected archive entry count"
        assert sum(item.file_size for item in entries) < 20 * 1024 * 1024, "Unexpected archive size"
        prefix = SLUG + "/"
        assert len({item.filename for item in entries}) == len(entries), "Duplicate ZIP paths"
        assert all(item.filename.startswith(prefix) and not item.is_dir() for item in entries), "Invalid package layout"
        names = [item.filename[len(prefix):] for item in entries]
        check_file_names(names)
        for entry, name in zip(entries, names):
            target = Path(temporary) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(entry))
        report = check_tree(Path(temporary))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksums = archive.with_name("SHA256SUMS")
    assert checksums.is_file(), "Missing SHA256SUMS"
    assert f"{digest}  {archive.name}" in checksums.read_text(encoding="utf-8").splitlines(), "SHA256 mismatch"
    report.update(archive=archive.name, sha256=digest, files=len(entries))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--built", action="store_true", help="Check the ZIP named by dist/release-manifest.json")
    args = parser.parse_args()
    if args.built:
        assert not args.archive, "Choose --archive or --built"
        report = json.loads((ROOT / "dist/release-manifest.json").read_text(encoding="utf-8"))
        args.archive = ROOT / "dist" / report["archive"]
    report = check_archive(args.archive.resolve()) if args.archive else check_tree(ROOT)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
