"""Release contracts, deterministic packaging and fail-closed GitHub publication."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = "astrbot_plugin_nitter_tweets"
PACKAGE_ITEMS = (
    ".astrbot-plugin",
    "_conf_schema.json",
    "__init__.py",
    "ai",
    "command_handlers",
    "config",
    "delivery",
    "LICENSE",
    "logo.png",
    "main.py",
    "media_support",
    "metadata.yaml",
    "pages",
    "plugin_api",
    "rendering",
    "requirements.txt",
    "scheduler",
    "shared",
    "storage",
)
_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\](?: - (\d{4}-\d{2}-\d{2}))?$")
_FORBIDDEN = {
    "__pycache__",
    "tests",
    "testignore",
    "docs",
    "scripts",
    "Progress",
    "PLAN",
    "Lesson",
    ".github",
}


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    notes: str
    published_date: date | None

    @property
    def tag(self) -> str:
        return f"v{self.version}"

    @property
    def archive_name(self) -> str:
        return f"{PLUGIN}-{self.tag}.zip"


def _match(text: str, pattern: str, label: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError(f"Missing or invalid {label}")
    return match.group(1)


def release_info(root: Path, *, publishing: bool = False) -> ReleaseInfo:
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    lines = changelog.splitlines()
    headings = [(i, line) for i, line in enumerate(lines) if line.startswith("## ")]
    if not headings:
        raise ValueError("Missing changelog version heading")
    start, heading = headings[0]
    match = _HEADING.fullmatch(heading)
    if not match:
        raise ValueError(
            "First changelog heading must be ## [X.Y.Z] with optional ISO date"
        )
    if re.search(r"^##\s+\[?(?:unreleased|未发布)\]?", changelog, re.I | re.M):
        raise ValueError("Unreleased headings are not allowed")
    version, raw_date = match.groups()
    published_date = date.fromisoformat(raw_date) if raw_date else None
    if publishing and not published_date:
        raise ValueError("Publication requires a changelog date")
    if published_date and published_date > date.today():
        raise ValueError("Changelog date cannot be in the future")
    end = headings[1][0] if len(headings) > 1 else len(lines)
    notes = "\n".join(lines[start:end]).strip() + "\n"
    if not re.search(r"^[-*]\s+\S", "\n".join(lines[start + 1 : end]), re.M):
        raise ValueError("Release notes require at least one change item")
    tree = ast.parse((root / "main.py").read_text(encoding="utf-8"))
    registered = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Name)
                    and decorator.func.id == "register"
                    and len(decorator.args) >= 4
                    and isinstance(decorator.args[3], ast.Constant)
                ):
                    registered.append(str(decorator.args[3].value))
    versions = {
        "changelog": version,
        "metadata": _match(
            (root / "metadata.yaml").read_text(encoding="utf-8"),
            r"^version:\s*([\d.]+)\s*$",
            "metadata version",
        ),
        "readme": _match(
            (root / "README.md").read_text(encoding="utf-8"),
            r"img\.shields\.io/badge/version-(\d+\.\d+\.\d+)-",
            "README version",
        ),
        "register": registered[0] if len(registered) == 1 else "invalid",
    }
    if len(set(versions.values())) != 1:
        raise ValueError(f"Version mismatch: {versions}")
    return ReleaseInfo(version, notes, published_date)


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def _package_files(root: Path, ref: str | None) -> dict[str, bytes]:
    files = {}
    if ref:
        entries = git(root, "ls-tree", "-r", "-z", ref).split(b"\0")
        candidates = []
        for entry in filter(None, entries):
            meta, raw_path = entry.split(b"\t", 1)
            mode, kind, blob = meta.decode().split()
            candidates.append((raw_path.decode("utf-8"), mode, kind, blob))
    else:
        entries = git(root, "ls-files", "-s", "-z").split(b"\0")
        candidates = []
        for entry in filter(None, entries):
            meta, raw_path = entry.split(b"\t", 1)
            mode, blob, _stage = meta.decode().split()
            candidates.append((raw_path.decode("utf-8"), mode, "blob", blob))
    for name, mode, kind, blob in candidates:
        if not any(
            name == item or name.startswith(item + "/") for item in PACKAGE_ITEMS
        ):
            continue
        path = PurePosixPath(name)
        if (
            mode not in {"100644", "100755"}
            or kind != "blob"
            or ".." in path.parts
            or set(path.parts) & _FORBIDDEN
            or path.suffix in {".pyc", ".pyo", ".db", ".md"}
            or name.endswith((".db-wal", ".db-shm"))
        ):
            raise ValueError(f"Forbidden package entry: {name}")
        if not ref and (root / name).is_symlink():
            raise ValueError(f"Symlink in package: {name}")
        files[name] = (
            git(root, "cat-file", "blob", blob) if ref else (root / name).read_bytes()
        )
    for item in PACKAGE_ITEMS:
        if not any(name == item or name.startswith(item + "/") for name in files):
            raise ValueError(f"Missing package item: {item}")
    return files


def _validate_resources(files: dict[str, bytes]) -> None:
    for name, content in files.items():
        if name.endswith(".py"):
            ast.parse(content.decode("utf-8"), filename=name)
        if name.endswith(".json"):
            json.loads(content)
        if name.endswith((".html", ".css")):
            text = content.decode("utf-8")
            refs = re.findall(
                r"""(?:src|href)=["'](\./[^"']+)["']|url\(["']?(\./[^)"']+)""", text
            )
            for pair in refs:
                relative = next(x for x in pair if x)
                target = (
                    PurePosixPath(name).parent
                    / relative.split("?", 1)[0].split("#", 1)[0]
                ).as_posix()
                if target not in files:
                    raise ValueError(f"Missing local asset: {name} -> {target}")


def build_archive(root: Path, output: Path, *, ref: str | None = None) -> Path:
    info = release_info(root)
    files = _package_files(root, ref)
    _validate_resources(files)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / info.archive_name
    if archive.exists():
        raise ValueError("Archive output already exists; use a fresh output directory")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo(f"{PLUGIN}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            target.writestr(entry, content)
    with zipfile.ZipFile(archive) as target:
        if target.testzip() is not None:
            raise ValueError("Corrupt plugin archive")
    if archive.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Plugin archive exceeds 32 MiB")
    return archive


def package_smoke(archive: Path, output: Path) -> None:
    destination = output / "smoke"
    destination.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts or path.parts[0] != PLUGIN:
                raise ValueError("Unsafe ZIP path")
        source.extractall(destination)
    code = """
import importlib, pathlib, socket, sys, urllib.request
root = pathlib.Path(sys.argv[1]).resolve()
def denied(*a, **k): raise RuntimeError('Network forbidden during package smoke')
socket.socket.connect = denied
socket.socket.connect_ex = denied
urllib.request.urlopen = denied
sys.path.insert(0, str(root))
module = importlib.import_module('astrbot_plugin_nitter_tweets.main')
assert hasattr(module, 'NitterTweetsPlugin')
for name, mod in list(sys.modules.items()):
    if name.startswith('astrbot_plugin_nitter_tweets') and getattr(mod, '__file__', None):
        pathlib.Path(mod.__file__).resolve().relative_to(root)
print('Package-only import passed')
"""
    subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(destination)],
        cwd=destination,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=True,
        timeout=90,
    )


class GitHub:
    """Only HTTP 404 is absence; other failures preserve state and stop."""

    def __init__(self, repository: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        self.repository = repository
        self.prefix = f"repos/{repository}"

    def call(self, *args: str, missing: bool = False, binary: bool = False):
        result = subprocess.run(["gh", *args], capture_output=True, timeout=180)
        if result.returncode:
            stderr = result.stderr.decode(errors="replace")
            if missing and re.search(r"\(HTTP 404\)", stderr):
                return None
            status = re.search(r"HTTP (\d{3})", stderr)
            raise RuntimeError(
                f"GitHub operation failed{': HTTP ' + status[1] if status else ''}"
            )
        if binary:
            return result.stdout
        return json.loads(result.stdout) if result.stdout.strip() else None

    def api(self, path: str, *, missing: bool = False):
        return self.call("api", f"{self.prefix}/{path}", missing=missing)

    def tag_commit(self, tag: str) -> str | None:
        ref = self.api(f"git/ref/tags/{tag}", missing=True)
        if ref is None:
            return None
        obj = ref["object"]
        for _ in range(8):
            if obj["type"] == "commit":
                return obj["sha"]
            if obj["type"] != "tag":
                break
            obj = self.api(f"git/tags/{obj['sha']}")["object"]
        raise ValueError("Tag does not resolve to a commit")

    def download_asset(self, tag: str, name: str, destination: Path) -> Path:
        """Fetch exact published bytes; never hash a possibly re-encoded stdout."""
        self.call(
            "release",
            "download",
            tag,
            "--repo",
            self.repository,
            "--pattern",
            name,
            "--output",
            str(destination),
            binary=True,
        )
        if not destination.is_file():
            raise ValueError("Release asset download produced no file")
        return destination


def _verify_asset(remote: GitHub, release: dict, archive: Path, workdir: Path) -> None:
    assets = [
        asset for asset in release.get("assets", []) if asset["name"] == archive.name
    ]
    if len(assets) != 1:
        raise ValueError("Release attachment is missing or ambiguous")
    workdir.mkdir(parents=True, exist_ok=True)
    downloaded = remote.download_asset(
        release["tag_name"], archive.name, workdir / f"remote-{archive.name}"
    )
    if (
        hashlib.sha256(downloaded.read_bytes()).digest()
        != hashlib.sha256(archive.read_bytes()).digest()
    ):
        raise ValueError("Release attachment differs; refusing to overwrite")


def _verify_release(
    remote: GitHub, release: dict, archive: Path, notes: str, workdir: Path
) -> None:
    if release.get("body", "").strip() != notes.strip():
        raise ValueError(
            "Existing release notes differ; public releases are never overwritten"
        )
    _verify_asset(remote, release, archive, workdir)


def publish(
    remote: GitHub,
    info: ReleaseInfo,
    archive: Path,
    sha: str,
    notes_file: Path,
    workdir: Path,
) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Candidate must be a full commit SHA")
    notes = notes_file.read_text(encoding="utf-8")
    tag_sha = remote.tag_commit(info.tag)
    release = remote.api(f"releases/tags/{info.tag}", missing=True)
    if tag_sha is not None and tag_sha != sha:
        raise ValueError("Existing tag points to a different commit")
    if release and tag_sha is None:
        raise ValueError("Release exists without verifiable tag")
    if release and not release.get("draft"):
        _verify_release(remote, release, archive, notes, workdir)
        return "already-published"
    if release is None:
        # Create and verify the lightweight ref before drafting; drafts alone may
        # defer tag creation until publication, which cannot prove source identity.
        if tag_sha is None:
            remote.call(
                "api",
                f"{remote.prefix}/git/refs",
                "-X",
                "POST",
                "-f",
                f"ref=refs/tags/{info.tag}",
                "-f",
                f"sha={sha}",
            )
            if remote.tag_commit(info.tag) != sha:
                raise ValueError("New tag differs from candidate commit")
        remote.call(
            "release",
            "create",
            info.tag,
            "--repo",
            remote.repository,
            "--draft",
            "--title",
            info.tag,
            "--notes-file",
            str(notes_file),
            "--verify-tag",
            binary=True,
        )
        release = remote.api(f"releases/tags/{info.tag}")
    if not release or not release.get("draft"):
        raise ValueError("Expected a draft release")
    if remote.tag_commit(info.tag) != sha:
        raise ValueError("Draft tag differs from candidate commit")
    assets = [
        asset for asset in release.get("assets", []) if asset["name"] == archive.name
    ]
    if assets:
        _verify_asset(remote, release, archive, workdir)
    else:
        remote.call(
            "release",
            "upload",
            info.tag,
            str(archive),
            "--repo",
            remote.repository,
            binary=True,
        )
    # Only drafts may have their notes corrected after a partial attempt.
    remote.call(
        "release",
        "edit",
        info.tag,
        "--repo",
        remote.repository,
        "--title",
        info.tag,
        "--notes-file",
        str(notes_file),
        binary=True,
    )
    _verify_release(
        remote, remote.api(f"releases/tags/{info.tag}"), archive, notes, workdir
    )
    remote.call(
        "release",
        "edit",
        info.tag,
        "--repo",
        remote.repository,
        "--draft=false",
        binary=True,
    )
    if remote.tag_commit(info.tag) != sha:
        raise ValueError("Published tag differs from candidate commit")
    final = remote.api(f"releases/tags/{info.tag}")
    if final.get("draft"):
        raise ValueError("Release remained draft")
    _verify_release(remote, final, archive, notes, workdir)
    return "published"


def contributor_notes(root: Path, info: ReleaseInfo, sha: str) -> str:
    previous = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "describe",
            "--tags",
            "--abbrev=0",
            "--match",
            "v[0-9]*",
            f"{sha}^",
        ],
        capture_output=True,
        text=True,
    )
    commit_range = (
        f"{previous.stdout.strip()}..{sha}" if previous.returncode == 0 else sha
    )
    authors = dict.fromkeys(
        git(root, "log", "--format=%aN", commit_range).decode("utf-8").splitlines()
    )
    authors = [
        author for author in authors if author and author != "github-actions[bot]"
    ]
    return info.notes + (
        "\n## Contributors\n\n" + "\n".join(f"- {author}" for author in authors) + "\n"
        if authors
        else ""
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("package", "publish"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.action == "publish":
        if os.environ.get("GITHUB_REF") != "refs/heads/main":
            raise ValueError("Publication is restricted to main")
        sha = git(root, "rev-parse", "HEAD").decode().strip()
        if os.environ.get("GITHUB_SHA") != sha:
            raise ValueError("Checkout SHA differs from event SHA")
        if git(root, "status", "--porcelain", "--untracked-files=no").strip():
            raise ValueError("Tracked publication files must be clean")
        info = release_info(root, publishing=True)
        archive = build_archive(root, args.output, ref=sha)
        package_smoke(archive, args.output)
        notes_file = args.output / "release-notes.md"
        notes_file.write_text(contributor_notes(root, info, sha), encoding="utf-8")
        result = publish(
            GitHub(os.environ["GITHUB_REPOSITORY"]),
            info,
            archive,
            sha,
            notes_file,
            args.output / "remote-check",
        )
        print(f"{info.tag}: {result}")
    else:
        archive = build_archive(root, args.output)
        package_smoke(archive, args.output)
        print(f"Validated {archive.name} ({archive.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
