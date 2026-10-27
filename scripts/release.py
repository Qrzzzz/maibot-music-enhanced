# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Qrzzzz
"""Plan, verify and publish one immutable GitHub Release from the tested source commit."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from check_release import ROOT, SLUG, check_archive, check_tree


def command(args: list[str], *, cwd: Path = ROOT, input_text: str | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, input=input_text, capture_output=True, text=True,
                            encoding="utf-8", timeout=120)
    if result.returncode:
        raise RuntimeError(f"{args[0]} {args[1]} failed: {(result.stderr or result.stdout)[-3000:]}")
    return result.stdout


def git(root: Path, *args: str) -> str:
    return command(["git", *args], cwd=root).strip()


def api(method: str, route: str, data: dict | None = None, *, missing_ok: bool = False):
    args = ["gh", "api", "--method", method, route]
    if data is not None:
        args.extend(["--input", "-"])
    result = subprocess.run(args, input=json.dumps(data) if data is not None else None,
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    if result.returncode:
        if missing_ok and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError(f"GitHub API {method} failed: {result.stderr[-3000:]}")
    return json.loads(result.stdout)


def release_notes(root: Path, version: str) -> str:
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"(?m)^## " + re.escape(version) + r" — \d{4}-\d{2}-\d{2}\s*\n", text)
    if not match:
        raise ValueError("Missing versioned changelog entry")
    body = re.split(r"(?m)^## ", text[match.end():], maxsplit=1)[0].strip()
    if not body:
        raise ValueError("Release notes must not be empty")
    return f"# 麦麦点歌增强 {version}\n\n{body}\n\n" + (
        "基于磐冰的 maibot-music 增强，音源接入参考 Zhalslar 的 AstrBot 插件。"
        "维护者及新增代码作者：Qrzzzz。整体 GPL-3.0-only，保留原 MIT 声明，详见 NOTICE.md。\n\n"
        "ZIP 解压到 MaiBot/plugins/；迁移前停用原 github.pan-ice.music。"
        "本地语音模式需要 FFmpeg / ffprobe，兼容范围与验证边界见该版本 README.md。\n"
    )


def plan(root: Path, *, dry_run: bool, expected_version: str = "", event_tag: str = "", expected_sha: str = "") -> dict:
    info = check_tree(root)
    version = info["version"]
    tag = "v" + version
    if expected_version and expected_version != version:
        raise ValueError("Requested version differs from manifest")
    if event_tag and event_tag != tag:
        raise ValueError("Tag must exactly match v + manifest version")
    sha = git(root, "rev-parse", "HEAD")
    if expected_sha and sha != expected_sha:
        raise ValueError("Checkout differs from workflow source SHA")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Commit release sources before planning")
    repository = "Qrzzzz/" + SLUG
    if os.environ.get("GITHUB_REPOSITORY", repository) != repository:
        raise ValueError("Workflow repository differs from plugin repository")
    context = {"version": version, "tag": tag, "source_commit": sha, "repository": repository,
               "archive": f"{SLUG}-{version}.zip", "dry_run": dry_run}
    destination = root / "dist"
    destination.mkdir(exist_ok=True)
    notes = release_notes(root, version) + f"\n源提交：`{sha}`。\n"
    if os.environ.get("GITHUB_RUN_ID"):
        notes += f"工作流验证：[Release run](https://github.com/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']})。\n"
    (destination / "release-notes.md").write_text(notes, encoding="utf-8", newline="\n")
    (destination / "release-context.json").write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            for key, value in context.items():
                output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
    return context


def verify_bundle(root: Path, directory: Path, context: dict) -> list[Path]:
    info = check_tree(root)
    if context["version"] != info["version"] or context["tag"] != "v" + info["version"]:
        raise ValueError("Release context version mismatch")
    if context["repository"] != "Qrzzzz/" + SLUG or context["source_commit"] != git(root, "rev-parse", "HEAD"):
        raise ValueError("Release context source mismatch")
    expected_name = f"{SLUG}-{info['version']}.zip"
    if context["archive"] != expected_name:
        raise ValueError("Unexpected archive name")
    archive = directory / expected_name
    report = check_archive(archive)
    metadata = json.loads((directory / "release-manifest.json").read_text(encoding="utf-8"))
    for key in ("version", "archive", "sha256", "files", "plugin_id"):
        if metadata[key] != report[key]:
            raise ValueError(f"Build manifest mismatch: {key}")
    if metadata["source_commit"] != context["source_commit"] or metadata["archive_bytes"] != archive.stat().st_size:
        raise ValueError("Build manifest source or size mismatch")
    tracked = git(root, "ls-files", "-z").rstrip("\0").split("\0")
    with zipfile.ZipFile(archive) as package:
        prefix = SLUG + "/"
        if {item.filename for item in package.infolist()} != {prefix + name for name in tracked}:
            raise ValueError("Archive files differ from the tested Git tree")
        for name in tracked:
            original = subprocess.run(["git", "show", "HEAD:" + name], cwd=root, check=True, capture_output=True).stdout
            if package.read(prefix + name) != original:
                raise ValueError(f"Archive differs from source commit: {name}")
    return [archive, directory / "SHA256SUMS", directory / "release-manifest.json"]


def tag_commit(repository: str, tag: str) -> str | None:
    ref = api("GET", f"repos/{repository}/git/ref/tags/{tag}", missing_ok=True)
    if ref is None:
        return None
    obj = ref["object"]
    for _ in range(10):
        if obj["type"] == "commit":
            return obj["sha"]
        if obj["type"] != "tag":
            break
        obj = api("GET", f"repos/{repository}/git/tags/{obj['sha']}")["object"]
    raise ValueError("Tag does not resolve to a commit")


def verify_assets(release: dict, files: list[Path]) -> None:
    assets = release["assets"]
    if len(assets) != len(files) or {item["name"] for item in assets} != {path.name for path in files}:
        raise ValueError("Existing release assets differ; refusing to replace them")
    for path in files:
        asset = next(item for item in assets if item["name"] == path.name)
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if asset.get("digest") != digest or asset["size"] != path.stat().st_size:
            raise ValueError(f"Remote asset mismatch: {path.name}; refusing to overwrite")


def find_release(repository: str, tag: str) -> dict | None:
    """List releases with authenticated access so drafts are visible as well as public versions."""
    for page in range(1, 101):
        releases = api("GET", f"repos/{repository}/releases?per_page=100&page={page}")
        matches = [release for release in releases if release["tag_name"] == tag]
        if len(matches) > 1:
            raise ValueError("Multiple releases share the same tag; refusing an ambiguous publication")
        if matches:
            return matches[0]
        if len(releases) < 100:
            return None
    raise ValueError("Release lookup pagination limit reached; refusing to create a duplicate")


def publish(root: Path, directory: Path, context: dict) -> dict:
    if context["dry_run"] is not False:
        raise ValueError("Dry run cannot create tags or publish a release")
    files = verify_bundle(root, directory, context)
    repository, tag, sha = context["repository"], context["tag"], context["source_commit"]
    remote_commit = tag_commit(repository, tag)
    if remote_commit is not None and remote_commit != sha:
        raise ValueError("Existing tag points at another source commit; publish a new version")
    existing = find_release(repository, tag)
    if existing:
        if remote_commit != sha:
            raise ValueError("Existing release has no matching source tag")
        verify_assets(existing, files)
        if not existing["draft"]:
            if existing["prerelease"]:
                raise ValueError("Existing release is a prerelease; refusing to alter it")
            return {"status": "already_published", "url": existing["html_url"], "source_commit": sha}
    else:
        if remote_commit is None:
            api("POST", f"repos/{repository}/git/refs", {"ref": "refs/tags/" + tag, "sha": sha})
        command(["gh", "release", "create", tag, *map(str, files), "--repo", repository,
                 "--verify-tag", "--draft", "--title", "麦麦点歌增强 " + context["version"],
                 "--notes-file", str(directory / "release-notes.md")], cwd=root)
    draft = find_release(repository, tag)
    if draft is None:
        raise ValueError("Created draft was not found; inspect the existing release before retrying")
    verify_assets(draft, files)
    with tempfile.TemporaryDirectory(prefix="music-release-readback-") as temporary:
        args = ["gh", "release", "download", tag, "--repo", repository, "--dir", temporary]
        for path in files:
            args.extend(["--pattern", path.name])
        command(args, cwd=root)
        verify_bundle(root, Path(temporary), context)
    if tag_commit(repository, tag) != sha:
        raise ValueError("Remote tag changed before publication")
    command(["gh", "release", "edit", tag, "--repo", repository, "--draft=false", "--latest"], cwd=root)
    released = find_release(repository, tag)
    if released is None:
        raise ValueError("Published release was not found")
    verify_assets(released, files)
    if released["draft"] or released["prerelease"]:
        raise ValueError("Release is not public and stable")
    return {"status": "published", "url": released["html_url"], "source_commit": sha,
            "downloaded_assets_verified": True, "asset_digests_verified": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "verify", "publish"])
    parser.add_argument("--dry-run", choices=["true", "false"], default="true")
    parser.add_argument("--expected-version", default="")
    parser.add_argument("--tag", default="")
    parser.add_argument("--expected-sha", default="")
    args = parser.parse_args()
    directory = ROOT / "dist"
    if args.action == "plan":
        report = plan(ROOT, dry_run=args.dry_run == "true", expected_version=args.expected_version,
                      event_tag=args.tag, expected_sha=args.expected_sha)
    else:
        context = json.loads((directory / "release-context.json").read_text(encoding="utf-8"))
        if args.action == "verify":
            report = {"status": "passed", "files": [path.name for path in verify_bundle(ROOT, directory, context)], **context}
        else:
            report = publish(ROOT, directory, context)
            (directory / "publication.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            summary.write("```json\n" + json.dumps(report, ensure_ascii=False, indent=2) + "\n```\n")


if __name__ == "__main__":
    main()
