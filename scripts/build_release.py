# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Qrzzzz
"""Build a reproducible source ZIP from a clean committed Git tree."""
from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from check_release import ROOT, SLUG, check_archive, check_file_names, check_tree


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def main() -> None:
    check_tree(ROOT)
    assert not git("status", "--porcelain", "--untracked-files=normal").strip(), "Commit all release sources before packaging"
    names = sorted(git("ls-files", "-z").decode("utf-8").rstrip("\0").split("\0"))
    check_file_names(names)
    commit = git("rev-parse", "HEAD").decode().strip()
    manifest = json.loads(git("show", "HEAD:_manifest.json"))
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    archive = destination / f"{SLUG}-{manifest['version']}.zip"
    # Fixed timestamps, permissions and sorted paths make identical source commits reproducible.
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for name in names:
            info = zipfile.ZipInfo(f"{SLUG}/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            package.writestr(info, git("show", f"HEAD:{name}"))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="utf-8", newline="\n")
    report = check_archive(archive)
    report.update(source_commit=commit, archive_bytes=archive.stat().st_size)
    (destination / "release-manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
