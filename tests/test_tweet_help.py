from __future__ import annotations

import ast
import base64
import html
from html.parser import HTMLParser
from pathlib import Path

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def help_source():
    """Load the poster's pure builders without requiring a browser installation."""
    tree = ast.parse(
        (ROOT / "scripts/render_tweet_help.py").read_text(encoding="utf-8")
    )
    constants = {"ROOT", "WIDTH", "POSTER", "GROUPS", "CSS"}
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in constants
                for target in node.targets
            )
        )
        or (isinstance(node, ast.FunctionDef) and node.name in {"esc", "build_html"})
    ]
    namespace = {
        "__file__": str(ROOT / "scripts/render_tweet_help.py"),
        "Path": Path,
        "base64": base64,
        "html": html,
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), "tweet_help", "exec"),
        namespace,
    )
    return namespace


def test_help_commands_match_registered_handlers(help_source):
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    groups = {}
    commands = []
    for method in plugin.body:
        if not isinstance(method, ast.AsyncFunctionDef):
            continue
        for decorator in method.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(
                decorator.func, ast.Attribute
            ):
                continue
            if decorator.func.attr == "command_group":
                groups[method.name] = ast.literal_eval(decorator.args[0])
            elif decorator.func.attr == "command":
                command = ast.literal_eval(decorator.args[0])
                parent = decorator.func.value
                if isinstance(parent, ast.Name) and parent.id in groups:
                    command = f"{groups[parent.id]} {command}"
                commands.append(command)

    entries = [entry for group in help_source["GROUPS"] for entry in group["entries"]]
    displayed = [help_source["POSTER"]["help_command"].removeprefix("/")] + [
        entry["id"] for entry in entries
    ]
    assert len(displayed) == len(set(displayed)) == len(commands)
    assert set(displayed) == set(commands)
    assert all("example" not in entry for entry in entries)


@pytest.mark.parametrize(
    ("command", "arguments"),
    [
        ("推文", "<用户名> [数量]"),
        ("推图", "<用户名> [数量] [图片/视频]"),
        ("推文搜索", "<关键词或标签> [-数量] [-top/-last]"),
        ("推文搜图", "<关键词或标签> [-数量] [-top/-last]"),
        ("订阅导出", "[分组名]"),
        ("订阅导入", "<用户名列表> [分组名]"),
        ("订阅删除", "<用户名列表> [分组名]"),
        ("标签导入", "<标签或关键词列表> <分组名>"),
        ("标签删除", "<标签或关键词列表> <分组名>"),
        ("推文黑名单 添加", "<用户名列表>"),
        ("推文黑名单 删除", "<用户名列表>"),
        ("推文黑名单 查看", ""),
        ("推文检查", "[分组名]"),
        ("镜像测试", "[用户名] [数量] <实例URL>"),
        ("推文记录清理", "[分组名]"),
        ("推特热搜", ""),
        ("订阅列表", ""),
        ("订阅去重", ""),
        ("推文状态", ""),
        ("推文缓存清理", ""),
    ],
)
def test_help_parameter_contract(help_source, command, arguments):
    usages = {
        entry["id"]: entry["usage"]
        for group in help_source["GROUPS"]
        for entry in group["entries"]
    }
    assert usages[command] == f"/{command} {arguments}".rstrip()


class _UsageReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_usage = False
        self.usages = []

    def handle_starttag(self, tag, attrs):
        if tag == "p" and dict(attrs).get("class") == "usage":
            self.in_usage = True

    def handle_endtag(self, tag):
        if tag == "p":
            self.in_usage = False

    def handle_data(self, data):
        if self.in_usage:
            self.usages.append(data)


def test_help_html_preserves_literal_parameter_brackets(help_source):
    document = help_source["build_html"]()
    reader = _UsageReader()
    reader.feed(document)
    expected = [
        entry["usage"] for group in help_source["GROUPS"] for entry in group["entries"]
    ]
    assert reader.usages == expected
    assert "&lt;用户名&gt;" in document
    assert "<用户名>" not in document
    assert "MiSans" in document
    assert "data:font/woff2;base64," in document
    assert "data:image/png;base64," in document


def test_bundled_help_is_fixed_width_palette_png(help_source):
    with Image.open(ROOT / "rendering/assets/tweet_help.png") as image:
        assert image.format == "PNG"
        assert image.mode == "P"
        assert image.width == help_source["WIDTH"] == 1440
        assert image.height > 0
        assert len(image.getpalette()) == 768
        assert image.getcolors(maxcolors=256) is not None
    with Image.open(ROOT / "rendering/assets/tweet_help.png") as image:
        image.verify()
