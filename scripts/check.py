"""Shared local/CI quality gate. Checks never format or publish files."""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Keep the repository clean when this script is run directly.
sys.dont_write_bytecode = True

try:
    from .release import PACKAGE_ITEMS, build_archive, package_smoke, release_info
except ImportError:
    from release import PACKAGE_ITEMS, build_archive, package_smoke, release_info

ROOT = Path(__file__).resolve().parents[1]
PINNED_RUFF = "0.15.22"


def _require_git(root: Path) -> None:
    if not (root / ".git").exists():
        raise RuntimeError(
            "This gate needs a git checkout (clone the repository instead of downloading an archive)"
        )


def ruff_command() -> list[str]:
    """Prefer an installed ruff binary; fall back to the pinned Python package."""
    executable = shutil.which("ruff")
    return [executable] if executable else [sys.executable, "-m", "ruff"]


def _installed_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            f"Missing development dependency {distribution!r}; install requirements-dev.txt"
        ) from exc


def prerequisites() -> None:
    if sys.version_info < (3, 12):
        raise RuntimeError(
            f"Python >=3.12 is required (running {sys.version.split()[0]})"
        )
    for module in (
        "astrbot.api",
        "astrbot.api.all",
        "astrbot.api.event",
        "astrbot.core.message.components",
    ):
        try:
            imported = importlib.import_module(module)
        except ImportError as exc:
            raise RuntimeError(
                f"Real AstrBot SDK required ({module}); install requirements-dev.txt"
            ) from exc
        if not getattr(imported, "__file__", None):
            raise RuntimeError(f"Real AstrBot SDK required: {module}")
    _installed_version("astrbot")
    if not shutil.which("node"):
        raise RuntimeError("Node is required; frontend tests must not silently skip")
    result = subprocess.run(
        [*ruff_command(), "--version"], capture_output=True, text=True
    )
    if result.returncode:
        raise RuntimeError("Ruff is required; install requirements-dev.txt")
    if PINNED_RUFF not in result.stdout:
        raise RuntimeError(
            f"Ruff must match the pinned {PINNED_RUFF} development version (found {result.stdout.strip()})"
        )


def runtime_contracts(root: Path) -> None:
    json.loads((root / "_conf_schema.json").read_text(encoding="utf-8"))
    release_info(root)
    paths = (
        subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
        .decode("utf-8")
        .split("\0")
    )
    for name in filter(None, paths):
        if not name.endswith(".py") or not any(
            name == item or name.startswith(item + "/") for item in PACKAGE_ITEMS
        ):
            continue
        tree = ast.parse((root / name).read_text(encoding="utf-8"), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name.split(".")[0] == "logging" for alias in node.names
            ):
                raise ValueError(
                    f"Forbidden runtime logging import: {name}:{node.lineno}"
                )
            if (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and node.module.split(".")[0] == "logging"
            ):
                raise ValueError(
                    f"Forbidden runtime logging import: {name}:{node.lineno}"
                )


def run_gate(root: Path, artifacts: Path) -> None:
    _require_git(root)
    prerequisites()
    runtime_contracts(root)
    ruff = ruff_command()
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "TEMP": str(artifacts),
        "TMP": str(artifacts),
    }
    commands = [
        [*ruff, "check", "--no-cache", "."],
        [*ruff, "format", "--check", "--no-cache", "."],
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(artifacts / "pytest"),
        ],
        ["git", "diff", "--check"],
        ["git", "diff", "--cached", "--check"],
    ]
    js_files = sorted((root / "pages/dashboard").glob("*.js"))
    if not js_files:
        raise ValueError("Dashboard scripts are missing")
    commands.extend(["node", "--check", str(path)] for path in js_files)
    for command in commands:
        print("+ " + " ".join(command), flush=True)
        subprocess.run(command, cwd=root, env=env, check=True)
    archive = build_archive(root, artifacts / "package")
    package_smoke(archive, artifacts / "package")
    print(f"Quality gate passed; artifacts: {artifacts}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--temp-root",
        type=Path,
        help="Optional parent for isolated artifacts; defaults to the system temp directory",
    )
    args = parser.parse_args()
    if args.temp_root:
        args.temp_root.mkdir(parents=True, exist_ok=True)
    artifacts = Path(tempfile.mkdtemp(prefix="quality-gate-", dir=args.temp_root))
    run_gate(args.root.resolve(), artifacts)


if __name__ == "__main__":
    main()
