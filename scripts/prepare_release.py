# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Qrzzzz
"""Synchronize the next version and create its changelog entry; never commits or publishes."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(root: Path, version: str, notes: list[str]) -> list[str]:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError("Use a three-part version such as 1.0.1")
    if {"99", "999"}.intersection(version.split(".")[:2]):
        raise ValueError("MaiBot does not accept 99/999 as major/minor version components")
    manifest = json.loads((root / "_manifest.json").read_text(encoding="utf-8"))
    previous = manifest["version"]
    if tuple(map(int, version.split("."))) <= tuple(map(int, previous.split("."))):
        raise ValueError(f"New version must be greater than {previous}")
    if not notes or any(not note.strip() or "\n" in note or "\r" in note for note in notes):
        raise ValueError("Provide at least one non-empty, single-line --note")
    manifest["version"] = version
    changes = {"_manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"}
    patterns = {
        "plugin.py": (r'(?m)^PLUGIN_VERSION = "' + re.escape(previous) + r'"$', f'PLUGIN_VERSION = "{version}"'),
        "config.example.toml": (r'(?m)^config_version = "' + re.escape(previous) + r'"$', f'config_version = "{version}"'),
        "README.md": (r'(?m)^\| 独立版本 \| `' + re.escape(previous) + r'` \|$', f'| 独立版本 | `{version}` |'),
    }
    for name, (pattern, replacement) in patterns.items():
        text = (root / name).read_text(encoding="utf-8")
        updated, count = re.subn(pattern, lambda match: replacement, text)
        if count != 1:
            raise ValueError(f"Expected one version field in {name}; no files were written")
        changes[name] = updated
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if re.search(r"(?m)^## " + re.escape(version) + r"(?: |$)", changelog):
        raise ValueError("Changelog entry already exists")
    title, separator, history = changelog.partition("\n")
    if not separator:
        raise ValueError("Invalid changelog")
    date = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    changes["CHANGELOG.md"] = title + f"\n\n## {version} — {date}\n\n" + "".join(f"- {note.strip()}\n" for note in notes) + "\n" + history.lstrip("\n")
    for name, text in changes.items():
        (root / name).write_text(text, encoding="utf-8", newline="\n")
    return list(changes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--note", action="append", required=True)
    args = parser.parse_args()
    print(json.dumps({"version": args.version, "updated": prepare(ROOT, args.version, args.note), "published": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
