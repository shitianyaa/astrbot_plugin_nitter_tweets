"""Build the bundled tweet help poster with local Chromium and inlined fonts."""

from __future__ import annotations

import argparse
import asyncio
import base64
import html
import json
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
WIDTH = 1440
WARM_CSS = """
body { color:#2f353d; background:#f8f1e7; }
header { background:#f1c779; color:#363129; border-bottom:6px solid #dfaa52; }
.subtitle, .header-note { color:#5b462c; }
.header-note strong { color:#363129; }
.legend { color:#67594c; }
.legend strong { color:#363129; }
.section { --section-ink:#965036; --section-tint:#fff1e9; background:#fffdf9; border-color:#dfd3c2; }
.section:nth-child(2) { --section-ink:#3a6757; --section-tint:#edf5ee; }
.section:nth-child(3) { --section-ink:#775087; --section-tint:#f5eef8; }
.section:nth-child(4) { --section-ink:#875c22; --section-tint:#faf1df; }
.section-head { border-bottom:2px solid var(--section-ink); }
.section-head h2, h3 { color:var(--section-ink); }
.permission { color:var(--section-ink); background:var(--section-tint); padding:4px 9px; border-radius:5px; }
.command { border-color:#e7dfd4; }
.field-label, dt { color:#6d6054; }
.usage { color:#3f3934; background:var(--section-tint); }
.example { color:var(--section-ink); }
footer { background:#fffdf9; border-color:#dfd3c2; }
.help-entry { border-color:#e7dfd4; }
.help-entry h2 { color:#965036; }
.help-entry .example { color:#965036; }
.notes { color:#67594c; }
.notes strong { color:#3f3934; }
.prefix { color:#6d6054; }
"""
GROUPS = [
    (
        "查询与搜索",
        "所有用户可用",
        [
            (
                "推文",
                "/推文 用户名 [数量]",
                "/推文 nasa 3",
                "查询公开账号最近的推文，按当前设置发送正文、翻译和媒体。",
            ),
            (
                "推图",
                "/推图 用户名 [数量] [视频/图片]",
                "/推图 nasa 3 图片",
                "查询账号的媒体推文，正文照常显示；指定“视频”可临时发送视频。",
            ),
            (
                "推文搜索",
                "/推文搜索 关键词或标签 [-数量] [-top/-last]",
                "/推文搜索 #AI -3 -top",
                "搜索公开推文。-top 热门，-last 最新；标签以 # 开头。",
            ),
            (
                "推文搜图",
                "/推文搜图 关键词或标签 [-数量] [-top/-last]",
                "/推文搜图 风景 -5 -last",
                "只搜索带图片或视频的推文，正文照常显示。",
            ),
            ("推特热搜", "/推特热搜", "/推特热搜", "查看 Twitter/X 当前的趋势热搜榜。"),
        ],
    ),
    (
        "博主订阅",
        "仅 AstrBot 管理员",
        [
            (
                "订阅列表",
                "/订阅列表",
                "/订阅列表",
                "查看全部分组的订阅源概览及推送目标数量。",
            ),
            (
                "订阅导入",
                "/订阅导入 用户名[,用户名] [分组名]",
                "/订阅导入 nasa,SpaceX 科技",
                "批量添加博主订阅；省略分组名时添加到默认分组。",
            ),
            (
                "订阅删除",
                "/订阅删除 用户名[,用户名] [分组名]",
                "/订阅删除 nasa,SpaceX 科技",
                "移除指定博主订阅；省略分组名时操作默认分组。",
            ),
            (
                "订阅导出",
                "/订阅导出 [分组名]",
                "/订阅导出 科技",
                "以文本导出博主、搜索词和 List ID；省略分组名时导出全部分组。",
            ),
            (
                "订阅去重",
                "/订阅去重",
                "/订阅去重",
                "规范化默认分组的博主账号，清除重复项和无效项并保存。",
            ),
        ],
    ),
    (
        "标签与黑名单",
        "仅 AstrBot 管理员",
        [
            (
                "标签导入",
                "/标签导入 标签或短语[,标签或短语] 分组名",
                "/标签导入 #AI,python programming 技术",
                "向已有标签分组添加搜索订阅。带 # 为标签，否则为短语；必须指定分组。",
            ),
            (
                "标签删除",
                "/标签删除 标签或短语[,标签或短语] 分组名",
                "/标签删除 #AI 技术",
                "从指定标签分组移除搜索订阅，不影响其他分组。",
            ),
            (
                "推文黑名单 添加",
                "/推文黑名单 添加 [目标UMO] 用户名[,用户名]",
                "/推文黑名单 添加 nasa,SpaceX",
                "屏蔽作者的后台推送；省略目标时使用当前会话，同一目标跨分组生效。",
            ),
            (
                "推文黑名单 删除",
                "/推文黑名单 删除 [目标UMO] 用户名[,用户名]",
                "/推文黑名单 删除 nasa",
                "解除作者的后台推送屏蔽；省略目标时使用当前会话。",
            ),
            (
                "推文黑名单 查看",
                "/推文黑名单 查看 [目标UMO]",
                "/推文黑名单 查看",
                "查看当前或指定推送目标的作者黑名单。",
            ),
        ],
    ),
    (
        "状态与维护",
        "仅 AstrBot 管理员",
        [
            (
                "推文状态",
                "/推文状态",
                "/推文状态",
                "查看调度运行状态、订阅源、推送目标和分组设置。",
            ),
            (
                "推文检查",
                "/推文检查 [分组名]",
                "/推文检查 科技",
                "立即检查并向当前会话推送；当前会话必须在该组推送目标中。",
            ),
            (
                "镜像测试",
                "/镜像测试 [用户名] [数量] 实例URL",
                "/镜像测试 nasa 3 http://nitter:8080",
                "临时测试自建 Nitter 并查询推文，不修改已配置的实例列表。",
            ),
            (
                "推文缓存清理",
                "/推文缓存清理",
                "/推文缓存清理",
                "删除普通图片、视频缓存，不删除订阅和推送记录。",
            ),
            (
                "推文记录清理",
                "/推文记录清理 [分组名] 确认",
                "/推文记录清理 科技 确认",
                "清理防重复推送记录；省略分组名时清理全部。必须带“确认”，可能导致重复推送。",
            ),
        ],
    ),
]


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def font_css(name: str, filename: str, weight: int) -> str:
    data = base64.b64encode(
        (ROOT / "pages/dashboard/fonts" / filename).read_bytes()
    ).decode("ascii")
    return f'@font-face{{font-family:{name};src:url(data:font/woff2;base64,{data}) format("woff2");font-weight:{weight};font-display:block;}}'


def build_html() -> str:
    fonts = font_css("MiSans", "MiSans-Regular.woff2", 400) + font_css(
        "MiSans", "MiSans-Bold.woff2", 700
    )
    panels = []
    for title, permission, commands in GROUPS:
        entries = []
        for command, usage, example, purpose in commands:
            entries.append(f'''<article class="command" data-command="{esc(command)}">
                <h3><span class="field-label">指令</span><span>/{esc(command)}</span></h3>
                <dl><div><dt>用法</dt><dd class="usage">{esc(usage)}</dd></div>
                <div><dt>示例</dt><dd class="example">{esc(example)}</dd></div>
                <div><dt>作用</dt><dd>{esc(purpose)}</dd></div></dl>
            </article>''')
        panels.append(
            f'<section class="section"><div class="section-head"><h2>{esc(title)}</h2><span class="permission">{esc(permission)}</span></div>{"".join(entries)}</section>'
        )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>推文指令帮助</title><style>
    {fonts}
    *{{box-sizing:border-box}}html,body{{margin:0;width:{WIDTH}px}}body{{font-family:MiSans,sans-serif;color:#172d42;background:#edf3f7}}
    .poster{{padding:0 44px 36px}}header{{margin:0 -44px;padding:36px 48px 32px;background:#0d526e;color:white;display:flex;justify-content:space-between;align-items:center}}
    h1{{margin:0 0 10px;font-size:54px;line-height:1.2;font-weight:700}}.subtitle{{margin:0;font-size:23px;color:#d3e9f2;line-height:1.5}}.header-note{{text-align:right;font-size:22px;line-height:1.7;color:#e5f2f7}}.header-note strong{{display:block;font-size:27px;color:white}}
    .legend{{display:flex;justify-content:space-between;gap:24px;padding:20px 2px 22px;font-size:21px;color:#465b6b;line-height:1.5}}.legend strong{{color:#172d42}}
    .grid{{display:grid;grid-template-columns:1fr 1fr;align-items:start;gap:24px}}.section{{min-width:0;background:white;padding:22px 24px 8px;border:1px solid #cbd8e2;border-radius:12px}}
    .section-head{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:2px 0 17px;border-bottom:2px solid #1d718f}}h2{{font-size:32px;line-height:1.3;margin:0;font-weight:700}}.permission{{font-size:19px;white-space:nowrap;color:#36586b}}
    .command{{padding:19px 0 20px;border-bottom:1px solid #dce5ec;min-width:0}}.command:last-child{{border-bottom:0}}h3{{display:flex;align-items:baseline;gap:12px;margin:0 0 12px;font-size:28px;line-height:1.25;font-weight:700;color:#133d55}}.field-label{{font-size:20px;font-weight:400;color:#516675;flex:0 0 44px}}
    dl{{margin:0;font-size:22px;line-height:1.55}}dl>div{{display:grid;grid-template-columns:44px minmax(0,1fr);gap:12px;margin-top:6px}}dt{{color:#516675;font-size:20px;padding-top:2px}}dd{{margin:0;overflow-wrap:anywhere}}.usage{{color:#1c425c;background:#f1f6f9;border-radius:5px;padding:5px 9px;font-weight:700;font-size:21px;line-height:1.55}}.example{{color:#19607a;font-size:21px}}dl>div:last-child{{margin-top:9px}}
    footer{{margin-top:24px;padding:24px;background:white;border:1px solid #cbd8e2;border-radius:12px}}.help-entry{{display:grid;grid-template-columns:220px 1fr;gap:24px;align-items:start;padding-bottom:20px;border-bottom:1px solid #dce5ec}}.help-entry h2{{font-size:28px;color:#133d55}}.help-entry dl{{display:grid;grid-template-columns:1fr 1fr;gap:6px 26px}}.help-entry dl>div{{margin:0}}.help-entry dl>div:last-child{{grid-column:1/-1;margin-top:4px}}.notes{{display:grid;grid-template-columns:1fr 1fr;gap:22px;padding-top:18px;font-size:20px;line-height:1.65;color:#435a6b}}.notes p{{margin:0}}.notes strong{{color:#183d54}}.prefix{{font-size:19px;color:#516675;line-height:1.5;margin-top:16px}}
    {WARM_CSS}</style></head><body><main class="poster">
    <header><div><h1>推文指令帮助</h1><p class="subtitle">查推文 · 订阅更新 · 管理推送</p></div><div class="header-note"><strong>全部指令，一张查阅</strong>指令 / 用法 / 示例 / 作用</div></header>
    <div class="legend"><span>未加方括号的参数为<strong>必填</strong>，<strong>[参数]</strong> 为可选；多个账号或搜索词用逗号分隔。</span><span>管理指令需要 AstrBot 管理员权限</span></div>
    <div class="grid">{"".join(panels)}</div>
    <footer><div class="help-entry" data-command="推文帮助"><h2>指令 /推文帮助</h2><dl><div><dt>用法</dt><dd>/推文帮助</dd></div><div><dt>示例</dt><dd class="example">/推文帮助</dd></div><div><dt>作用</dt><dd>查看全部指令的用法、示例与作用。</dd></div></dl></div>
    <div class="notes"><p><strong>分组与目标</strong><br>博主订阅可使用默认分组；标签订阅须指定已有标签分组。List 订阅通过 Pages 或插件配置维护。目标 UMO 请复制 /sid 返回的完整值，不只填写群号。</p><p><strong>发送与首次检查</strong><br>“推图 / 搜图”筛选媒体推文，不代表隐藏正文。首次检查只建立推送基准，不推历史；记录清理可能造成重复发送。</p></div>
    <div class="prefix">斜杠为默认命令前缀示例；如修改了 AstrBot 的命令前缀，请替换为实际前缀。镜像示例地址需替换为自己的可信实例。</div>
    </footer></main></body></html>"""


async def main(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    document = build_html()
    (output_dir / "tweet_help.html").write_text(document, encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page(
                viewport={"width": WIDTH, "height": 1200}, device_scale_factor=1
            )
            await page.route("**/*", lambda route: route.abort())
            await page.set_content(document, wait_until="load")
            await page.evaluate("document.fonts.ready")
            evidence = await page.evaluate("""() => ({
                commands: [...document.querySelectorAll('[data-command]')].map(e => e.dataset.command),
                width: document.documentElement.scrollWidth,
                height: document.documentElement.scrollHeight,
                overflow: [...document.querySelectorAll('h3, dd, dt, .permission, .legend')]
                    .filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent),
                fontsLoaded: document.fonts.check('22px MiSans')
            })""")
            assert len(evidence["commands"]) == 21, evidence
            assert not evidence["overflow"], evidence
            assert evidence["width"] == WIDTH and evidence["fontsLoaded"], evidence
            png = await page.screenshot(full_page=True, animations="disabled")
        finally:
            await browser.close()
    with Image.open(BytesIO(png)) as image:
        assert image.size == (WIDTH, evidence["height"])
        gray = image.convert("L")
        assert ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0] > 1
        image.convert("RGB").quantize(colors=256).save(
            output_dir / "tweet_help.png", optimize=True, compress_level=9
        )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    asyncio.run(main(parser.parse_args().output_dir))
