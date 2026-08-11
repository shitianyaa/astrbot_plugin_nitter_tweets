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


def test_qq_official_requires_supported_astrbot_version():
    minimum = _match(
        "metadata.yaml",
        r'^astrbot_version:\s*["\']?>=([0-9]+\.[0-9]+\.[0-9]+)',
    )

    assert tuple(int(part) for part in minimum.split(".")) >= (4, 26, 0)


def test_metadata_lists_only_canonical_platform_names():
    text = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
    section = text.split("support_platforms:", 1)[1].split("keywords:", 1)[0]
    platforms = re.findall(r"^  - ([a-z0-9_]+)\s*$", section, re.MULTILINE)

    assert platforms == ["aiocqhttp", "qq_official", "telegram", "lark", "weixin_oc"]


def test_readme_includes_qq_official_screenshot():
    asset = ROOT / "docs" / "assets" / "readme" / "qq-official-markdown.png"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert asset.is_file()
    assert "./docs/assets/readme/qq-official-markdown.png" in readme


def test_readme_includes_cat_visitor_counter():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "https://count.getloli.com/@astrbot-plugin-nitter-tweets?"
        "name=astrbot-plugin-nitter-tweets"
    ) in readme
    assert "theme=booru-jaypee" in readme
    assert "[count.getloli.com](https://count.getloli.com/)" in readme
