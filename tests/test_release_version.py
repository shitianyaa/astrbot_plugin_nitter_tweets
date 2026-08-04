from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _registered_version() -> str:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "register"
                and len(decorator.args) >= 4
                and isinstance(decorator.args[3], ast.Constant)
            ):
                return str(decorator.args[3].value)
    raise AssertionError("main.py register version not found")


def _match(path: str, pattern: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(pattern, text, re.MULTILINE)
    assert match is not None, f"version not found in {path}"
    return match.group(1)


def test_release_version_is_consistent():
    versions = {
        "metadata": _match("metadata.yaml", r"^version:\s*([^\s]+)\s*$"),
        "plugin": _registered_version(),
        "readme": _match(
            "README.md",
            r"img\.shields\.io/badge/version-([0-9]+\.[0-9]+\.[0-9]+)-",
        ),
        "changelog": _match(
            "CHANGELOG.md",
            r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\]",
        ),
    }

    assert len(set(versions.values())) == 1, versions
