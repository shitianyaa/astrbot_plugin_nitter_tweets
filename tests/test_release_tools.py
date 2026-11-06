"""Release safety tests never call GitHub or mutate real release state."""

from __future__ import annotations

import subprocess
import zipfile
from datetime import date
from pathlib import Path

import pytest

from scripts.check import runtime_contracts
from scripts.release import (
    GitHub,
    ReleaseInfo,
    build_archive,
    package_smoke,
    publish,
    release_info,
)

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def candidate(tmp_path):
    for name in (
        "README.md",
        "metadata.yaml",
        "main.py",
        "CHANGELOG.md",
        "_conf_schema.json",
    ):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    return tmp_path


@pytest.mark.parametrize(
    "heading", ["## [Unreleased]", "## [未发布]", "## 1.8.0", "## [1.8.0] - invalid"]
)
def test_first_heading_cannot_be_skipped(tmp_path, heading):
    root = candidate(tmp_path)
    path = root / "CHANGELOG.md"
    path.write_text(
        heading + "\n- pending\n" + path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        release_info(root)


def test_publication_requires_date_and_consistent_versions(tmp_path):
    root = candidate(tmp_path)
    path = root / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    heading = next(line for line in text.splitlines() if line.startswith("## "))
    path.write_text(
        text.replace(heading, heading.split(" - ", 1)[0], 1), encoding="utf-8"
    )
    info = release_info(root)
    with pytest.raises(ValueError, match="requires a changelog date"):
        release_info(root, publishing=True)
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            f"## [{info.version}]",
            f"## [{info.version}] - {date.today().isoformat()}",
            1,
        ),
        encoding="utf-8",
    )
    assert release_info(root, publishing=True).version == info.version
    (root / "metadata.yaml").write_text("version: 9.9.9\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Version mismatch"):
        release_info(root)


def test_empty_notes_rejected(tmp_path):
    root = candidate(tmp_path)
    info = release_info(root)
    (root / "CHANGELOG.md").write_text(
        f"## [{info.version}]\n\n### Fixed\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="change item"):
        release_info(root)


def test_package_is_deterministic_and_excludes_untracked_cache(tmp_path):
    first = build_archive(ROOT, tmp_path / "first")
    second = build_archive(ROOT, tmp_path / "second")
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert any(name.endswith("/main.py") for name in names)
        assert any(name.endswith("/pages/dashboard/boot.js") for name in names)
        assert not any(
            "__pycache__" in name or "/tests/" in name or name.endswith(".pyc")
            for name in names
        )
    package_smoke(first, tmp_path / "first")


def test_packaged_tree_uses_ref_not_dirty_working_bytes(tmp_path):
    ref = (
        subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
        .decode()
        .strip()
    )
    archive = build_archive(ROOT, tmp_path, ref=ref)
    with zipfile.ZipFile(archive) as source:
        assert source.read(
            "astrbot_plugin_nitter_tweets/main.py"
        ) == subprocess.check_output(["git", "-C", str(ROOT), "show", f"{ref}:main.py"])


class FakeGitHub:
    repository = "example/plugin"
    prefix = "repos/example/plugin"

    def __init__(
        self, archive, notes, *, tag=None, draft=None, asset=False, fail_upload=False
    ):
        self.tag = tag
        self.release = (
            None
            if draft is None
            else {"tag_name": "v1.8.0", "draft": draft, "body": notes, "assets": []}
        )
        self.data = archive.read_bytes()
        self.archive = archive
        self.notes = notes
        self.fail_upload = fail_upload
        self.writes = []
        self.download_paths = []
        if asset:
            self.release["assets"] = [{"name": archive.name, "id": 1}]

    def tag_commit(self, tag):
        return self.tag

    def api(self, path, **kwargs):
        return self.release

    def download_asset(self, tag, name, destination):
        self.download_paths.append(destination)
        with destination.open("xb") as target:
            target.write(self.data)
        return destination

    def call(self, *args, **kwargs):
        self.writes.append(args)
        if args[0] == "api":
            self.tag = SHA
        elif args[1] == "create":
            assert "--draft" in args and "--verify-tag" in args
            self.release = {
                "tag_name": "v1.8.0",
                "draft": True,
                "body": self.notes,
                "assets": [],
            }
        elif args[1] == "upload":
            assert "--clobber" not in args
            if self.fail_upload:
                raise RuntimeError("upload failure")
            self.release["assets"] = [{"name": self.archive.name, "id": 1}]
        elif args[1] == "edit":
            if "--draft=false" in args:
                self.release["draft"] = False
            else:
                self.release["body"] = self.notes


@pytest.fixture
def publication(tmp_path):
    info = ReleaseInfo("1.8.0", "## [1.8.0]\n- Changes\n", date.today())
    archive = tmp_path / info.archive_name
    archive.write_bytes(b"zip fixture")
    notes = tmp_path / "notes.txt"
    notes.write_text(info.notes, encoding="utf-8")
    return info, archive, notes


def test_new_publication_verifies_draft_before_visibility(publication):
    info, archive, notes = publication
    remote = FakeGitHub(archive, info.notes)
    assert (
        publish(remote, info, archive, SHA, notes, archive.parent / "work")
        == "published"
    )
    assert [args[:2] for args in remote.writes] == [
        ("api", "repos/example/plugin/git/refs"),
        ("release", "create"),
        ("release", "upload"),
        ("release", "edit"),
        ("release", "edit"),
    ]
    assert remote.release["draft"] is False
    assert len(remote.download_paths) == len(set(remote.download_paths)) == 2


def test_tag_mismatch_never_writes(publication):
    info, archive, notes = publication
    remote = FakeGitHub(archive, info.notes, tag="b" * 40, draft=False, asset=True)
    with pytest.raises(ValueError, match="different commit"):
        publish(remote, info, archive, SHA, notes, archive.parent / "work")
    assert remote.writes == []


def test_published_identical_release_is_noop(publication):
    info, archive, notes = publication
    remote = FakeGitHub(archive, info.notes, tag=SHA, draft=False, asset=True)
    assert (
        publish(remote, info, archive, SHA, notes, archive.parent / "work")
        == "already-published"
    )
    assert remote.writes == []


@pytest.mark.parametrize("damage", ["missing", "digest", "notes"])
def test_public_release_damage_never_overwrites(publication, damage):
    info, archive, notes = publication
    remote = FakeGitHub(
        archive, info.notes, tag=SHA, draft=False, asset=damage != "missing"
    )
    if damage == "digest":
        remote.data = b"other"
    if damage == "notes":
        remote.release["body"] = "old notes"
    with pytest.raises(ValueError):
        publish(remote, info, archive, SHA, notes, archive.parent / "work")
    assert remote.writes == []


def test_upload_failure_preserves_draft(publication):
    info, archive, notes = publication
    remote = FakeGitHub(archive, info.notes, fail_upload=True)
    with pytest.raises(RuntimeError, match="upload failure"):
        publish(remote, info, archive, SHA, notes, archive.parent / "work")
    assert remote.release["draft"] is True
    assert not any("--draft=false" in args for args in remote.writes)
    remote.fail_upload = False
    assert (
        publish(remote, info, archive, SHA, notes, archive.parent / "work")
        == "published"
    )


def test_resume_draft_checks_existing_asset(publication):
    info, archive, notes = publication
    remote = FakeGitHub(archive, info.notes, tag=SHA, draft=True, asset=True)
    assert (
        publish(remote, info, archive, SHA, notes, archive.parent / "work")
        == "published"
    )
    assert not any(args[1] == "upload" for args in remote.writes)
    assert len(remote.download_paths) == len(set(remote.download_paths)) == 3


@pytest.mark.parametrize("status", [403, 429, 500])
def test_api_errors_are_not_absence(monkeypatch, status):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a, 1, b"", f"gh: error (HTTP {status})".encode()
        ),
    )
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        GitHub("example/plugin").api("releases/tags/v1.8.0", missing=True)


def test_only_http_404_is_absent(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a, 1, b"", b"gh: Not Found (HTTP 404)"
        ),
    )
    assert GitHub("example/plugin").api("releases/tags/v1.8.0", missing=True) is None


def test_annotated_tag_resolves_commit(monkeypatch):
    remote = GitHub("example/plugin")
    values = iter(
        [
            {"object": {"type": "tag", "sha": "b" * 40}},
            {"object": {"type": "commit", "sha": SHA}},
        ]
    )
    monkeypatch.setattr(remote, "api", lambda *a, **k: next(values))
    assert remote.tag_commit("v1.8.0") == SHA


def test_runtime_ast_checks_absolute_logging_not_relative(monkeypatch, tmp_path):
    root = candidate(tmp_path)
    (root / "shared").mkdir()
    module = root / "shared/example.py"
    monkeypatch.setattr(
        subprocess, "check_output", lambda *a, **kw: b"shared/example.py\0"
    )
    module.write_text("from .logging_util import helper\n", encoding="utf-8")
    runtime_contracts(root)
    module.write_text("from logging import INFO\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Forbidden runtime logging"):
        runtime_contracts(root)


def test_gate_rejects_missing_node(monkeypatch):
    import shutil

    from scripts.check import prerequisites

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="Node"):
        prerequisites()


def test_gate_rejects_stub_sdk(monkeypatch):
    import importlib

    from scripts.check import prerequisites

    class _Stub:
        __file__ = None

    monkeypatch.setattr(importlib, "import_module", lambda name: _Stub())
    with pytest.raises(RuntimeError, match="Real AstrBot SDK"):
        prerequisites()


def test_gate_rejects_unpinned_ruff(monkeypatch):
    from scripts import check

    monkeypatch.setattr(
        check,
        "ruff_command",
        lambda: ["ruff"],
    )
    monkeypatch.setattr(
        check.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, "ruff 0.0.1\n", ""),
    )
    with pytest.raises(RuntimeError, match="pinned 0.15.22"):
        check.prerequisites()


def test_gate_requires_git_checkout(tmp_path):
    from scripts.check import _require_git

    with pytest.raises(RuntimeError, match="git checkout"):
        _require_git(tmp_path)


def test_missing_local_dashboard_asset_is_rejected():
    from scripts.release import _validate_resources

    with pytest.raises(ValueError, match="Missing local asset"):
        _validate_resources(
            {"pages/dashboard/index.html": b'<script src="./gone.js"></script>'}
        )


def test_archive_refuses_to_overwrite_output(tmp_path):
    build_archive(ROOT, tmp_path)
    with pytest.raises(ValueError, match="already exists"):
        build_archive(ROOT, tmp_path)


def test_pytest_config_makes_repository_importable_without_python_m():
    """Contributors often run bare `pytest`; scripts/ and top-level modules must resolve."""
    config = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "pythonpath = ." in config
