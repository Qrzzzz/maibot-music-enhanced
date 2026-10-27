# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 Qrzzzz
"""Exercise version preparation and release refusal/resume boundaries without publishing."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prepare_release
import release as release_tools


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture(scope="module")
def base_repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("release-base")
    for path in ROOT.iterdir():
        if path.is_dir() and path.name in {"scripts", "tests", "docs", "licenses", ".github"}:
            shutil.copytree(path, root / path.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        elif path.is_file() and path.name not in {"config.toml", ".env"}:
            shutil.copyfile(path, root / path.name)
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Release Test")
    git(root, "config", "user.email", "release-test@example.invalid")
    git(root, "add", "--all")
    git(root, "commit", "-m", "test source")
    return root


@pytest.fixture
def repo(base_repo, tmp_path, monkeypatch):
    target = tmp_path / "repo"
    subprocess.run(["git", "clone", "--quiet", "--local", str(base_repo), str(target)], check=True, capture_output=True)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    return target


def test_prepare_next_version_updates_all_runtime_and_document_fields(repo):
    current = json.loads((repo / "_manifest.json").read_text(encoding="utf-8"))["version"]
    major, minor, patch = map(int, current.split("."))
    next_version = f"{major}.{minor}.{patch + 1}"
    prepare_release.prepare(repo, next_version, ["修复一个点歌问题", "完善发布流程"])
    assert release_tools.check_tree(repo)["version"] == next_version
    assert tomllib.loads((repo / "config.example.toml").read_text(encoding="utf-8"))["plugin"]["config_version"] == next_version
    notes = release_tools.release_notes(repo, next_version)
    assert "修复一个点歌问题" in notes and "完善发布流程" in notes
    assert "建立独立维护版本" not in notes  # Previous version's changelog must not leak in.


@pytest.mark.parametrize("version", ["1.0", "v1.0.1", "1.0.01", "99.0.0", "999.0.0", "0.0.0"])
def test_invalid_or_older_versions_do_not_write_files(repo, version):
    before = (repo / "_manifest.json").read_bytes()
    with pytest.raises(ValueError):
        prepare_release.prepare(repo, version, ["A change"])
    assert (repo / "_manifest.json").read_bytes() == before
    assert not git(repo, "status", "--porcelain")


def test_version_field_failure_leaves_all_files_unmodified(repo):
    (repo / "plugin.py").write_text("# broken version field\n", encoding="utf-8")
    before = (repo / "_manifest.json").read_bytes()
    current = json.loads(before)["version"]
    parts = list(map(int, current.split("."))); parts[-1] += 1
    with pytest.raises(ValueError, match="no files were written"):
        prepare_release.prepare(repo, ".".join(map(str, parts)), ["Change"])
    assert (repo / "_manifest.json").read_bytes() == before


def test_plan_binds_version_tag_sha_and_refuses_dirty_sources(repo):
    version = json.loads((repo / "_manifest.json").read_text(encoding="utf-8"))["version"]
    with pytest.raises(ValueError, match="version"):
        release_tools.plan(repo, dry_run=True, expected_version="999.999.999")
    with pytest.raises(ValueError, match="Tag"):
        release_tools.plan(repo, dry_run=False, event_tag="v0.0.0")
    with pytest.raises(ValueError, match="SHA"):
        release_tools.plan(repo, dry_run=True, expected_sha="0" * 40)
    context = release_tools.plan(repo, dry_run=True, event_tag="v" + version)
    assert context["dry_run"] is True and context["source_commit"] == git(repo, "rev-parse", "HEAD")
    (repo / "untracked.txt").write_text("must not be omitted", encoding="utf-8")
    with pytest.raises(ValueError, match="Commit"):
        release_tools.plan(repo, dry_run=True)


def test_dry_run_cannot_reach_any_github_mutation(repo, monkeypatch):
    api = Mock(side_effect=AssertionError("Must not call GitHub"))
    monkeypatch.setattr(release_tools, "api", api)
    context = release_tools.plan(repo, dry_run=True)
    with pytest.raises(ValueError, match="Dry run"):
        release_tools.publish(repo, repo / "dist", context)
    api.assert_not_called()


def test_bundle_matches_commit_and_rejects_forged_source_or_manifest(repo):
    context = release_tools.plan(repo, dry_run=True)
    subprocess.run([sys.executable, "scripts/build_release.py"], cwd=repo, check=True, capture_output=True)
    assert len(release_tools.verify_bundle(repo, repo / "dist", context)) == 3
    forged = dict(context, source_commit="0" * 40)
    with pytest.raises(ValueError, match="source"):
        release_tools.verify_bundle(repo, repo / "dist", forged)
    path = repo / "dist/release-manifest.json"
    metadata = json.loads(path.read_text(encoding="utf-8")); metadata["sha256"] = "0" * 64
    path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        release_tools.verify_bundle(repo, repo / "dist", context)


def fake_assets(tmp_path):
    paths = [tmp_path / name for name in ("plugin.zip", "SHA256SUMS", "release-manifest.json")]
    for path in paths:
        path.write_bytes(path.name.encode())
    assets = [{"name": path.name, "size": path.stat().st_size,
               "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]
    return paths, assets


def test_existing_tag_cannot_move_and_assets_cannot_be_replaced(repo, tmp_path, monkeypatch):
    files, assets = fake_assets(tmp_path)
    context = {"dry_run": False, "repository": "Qrzzzz/maibot-music-enhanced", "tag": "v1.0.0", "source_commit": "a" * 40}
    monkeypatch.setattr(release_tools, "verify_bundle", lambda *args: files)
    monkeypatch.setattr(release_tools, "tag_commit", lambda *args: "b" * 40)
    api = Mock(); monkeypatch.setattr(release_tools, "api", api)
    with pytest.raises(ValueError, match="another source commit"):
        release_tools.publish(repo, tmp_path, context)
    api.assert_not_called()
    assets[0]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="refusing to overwrite"):
        release_tools.verify_assets({"assets": assets}, files)


def test_completed_release_rerun_verifies_without_editing(repo, tmp_path, monkeypatch):
    files, assets = fake_assets(tmp_path)
    context = {"dry_run": False, "repository": "Qrzzzz/maibot-music-enhanced", "tag": "v1.0.0", "source_commit": "a" * 40}
    monkeypatch.setattr(release_tools, "verify_bundle", lambda *args: files)
    monkeypatch.setattr(release_tools, "tag_commit", lambda *args: context["source_commit"])
    public = {"assets": assets, "draft": False, "prerelease": False, "html_url": "https://github.com/release"}
    api = Mock(return_value=public); monkeypatch.setattr(release_tools, "api", api)
    command = Mock(side_effect=AssertionError("Must not mutate a completed release")); monkeypatch.setattr(release_tools, "command", command)
    assert release_tools.publish(repo, tmp_path, context)["status"] == "already_published"
    assert all(call.args[0] == "GET" for call in api.call_args_list)
    command.assert_not_called()


@pytest.mark.parametrize("bad_download", [False, True])
def test_draft_is_public_only_after_downloaded_assets_pass(repo, tmp_path, monkeypatch, bad_download):
    files, assets = fake_assets(tmp_path)
    context = {"dry_run": False, "repository": "Qrzzzz/maibot-music-enhanced", "tag": "v1.0.1", "version": "1.0.1", "source_commit": "a" * 40}
    verified = Mock(side_effect=[files, ValueError("downloaded bundle mismatch") if bad_download else files])
    monkeypatch.setattr(release_tools, "verify_bundle", verified)
    monkeypatch.setattr(release_tools, "tag_commit", Mock(side_effect=[None, context["source_commit"]]))
    draft = {"assets": assets, "draft": True, "prerelease": False, "html_url": "https://github.com/release"}
    public = dict(draft, draft=False)
    replies = iter([None, {"ref": "created"}, draft, public])
    monkeypatch.setattr(release_tools, "api", Mock(side_effect=lambda *args, **kwargs: next(replies)))
    command = Mock(return_value=""); monkeypatch.setattr(release_tools, "command", command)
    if bad_download:
        with pytest.raises(ValueError, match="downloaded bundle"):
            release_tools.publish(repo, tmp_path, context)
        assert not any(call.args[0][1:3] == ["release", "edit"] for call in command.call_args_list)
    else:
        report = release_tools.publish(repo, tmp_path, context)
        assert report["downloaded_assets_verified"] and report["status"] == "published"
        assert [call.args[0][2] for call in command.call_args_list] == ["create", "download", "edit"]
