"""Render tweet help as a 256-color PNG. Edit POSTER and GROUPS for copy."""

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
# 文案只在 POSTER、GROUPS 中修改；CSS 和渲染函数只负责布局与输出。
POSTER = {
    "title": "推文指令帮助",
    "subtitle": "查询搜索 · 订阅管理 · 状态维护",
    "tips_title": "使用提示",
    "help_command": "/推文帮助",
    "tips": [
        "<参数> 为必填，[参数] 为可选；实际输入不带括号。",
        "批量导入或删除订阅时，多项用英文逗号分隔。List 订阅通过面板或插件配置维护。",
    ],
}

# entries 按列表顺序显示。id 是唯一标识；title、usage 是显示文案；
# note、warning 可选，分别显示普通说明和醒目提醒。分组 note 是该组公共提示。
GROUPS = [
    {
        "title": "查询与搜索",
        "permission": "所有用户可用",
        "entries": [
            {
                "id": "推文",
                "title": "查看用户推文",
                "usage": "/推文 <用户名> [数量]",
                "note": "查看指定用户最近发布的推文",
            },
            {
                "id": "推图",
                "title": "查看用户媒体推文",
                "usage": "/推图 <用户名> [数量] [图片/视频]",
                "note": "查看指定用户的图片或视频推文",
            },
            {
                "id": "推文搜索",
                "title": "搜索推文",
                "usage": "/推文搜索 <关键词或标签> [-数量] [-top/-last]",
                "note": "按关键词或标签搜索推文",
            },
            {
                "id": "推文搜图",
                "title": "搜索媒体推文",
                "usage": "/推文搜图 <关键词或标签> [-数量] [-top/-last]",
                "note": "按关键词或标签查找包含图片或视频的推文",
            },
            {
                "id": "推特热搜",
                "title": "查看热门话题",
                "usage": "/推特热搜",
            },
        ],
        "note": "标签带 #，关键词直接写；-数量 指定条数，-top 热门，-last 最新。不填数量和排序时使用默认设置。",
    },
    {
        "title": "博主订阅",
        "permission": "仅 AstrBot 管理员",
        "entries": [
            {
                "id": "订阅列表",
                "title": "查看订阅",
                "usage": "/订阅列表",
                "note": "查看各分组的订阅内容和推送目标数量",
            },
            {
                "id": "订阅导出",
                "title": "导出订阅",
                "usage": "/订阅导出 [分组名]",
                "note": "导出博主、关键词和 List ID；不填分组名时导出全部",
            },
            {
                "id": "订阅导入",
                "title": "添加博主",
                "usage": "/订阅导入 <用户名列表> [分组名]",
                "note": "将指定博主添加到指定分组",
            },
            {
                "id": "订阅删除",
                "title": "移除博主",
                "usage": "/订阅删除 <用户名列表> [分组名]",
                "note": "从指定分组移除指定博主",
            },
            {
                "id": "订阅去重",
                "title": "整理重复订阅",
                "usage": "/订阅去重",
                "note": "清除默认分组中重复和无效的用户名",
            },
        ],
        "note": "导入和删除不填分组名时，使用默认分组。其他博主分组请先在面板创建。",
    },
    {
        "title": "标签与黑名单",
        "permission": "仅 AstrBot 管理员",
        "entries": [
            {
                "id": "标签导入",
                "title": "添加标签或关键词",
                "usage": "/标签导入 <标签或关键词列表> <分组名>",
                "note": "先在面板创建标签分组，再填写分组名添加订阅",
            },
            {
                "id": "标签删除",
                "title": "移除标签或关键词",
                "usage": "/标签删除 <标签或关键词列表> <分组名>",
                "note": "从指定分组移除指定标签或关键词",
            },
            {
                "id": "推文黑名单 添加",
                "title": "屏蔽作者",
                "usage": "/推文黑名单 添加 <用户名列表>",
                "note": "订阅推送时跳过指定博主",
            },
            {
                "id": "推文黑名单 删除",
                "title": "解除屏蔽",
                "usage": "/推文黑名单 删除 <用户名列表>",
                "note": "恢复指定博主的订阅推送",
            },
            {
                "id": "推文黑名单 查看",
                "title": "查看黑名单",
                "usage": "/推文黑名单 查看",
            },
        ],
        "note": "黑名单用于当前会话。",
    },
    {
        "title": "状态与维护",
        "permission": "仅 AstrBot 管理员",
        "entries": [
            {
                "id": "推文状态",
                "title": "查看运行状态",
                "usage": "/推文状态",
                "note": "查看定时推送状态、订阅内容和推送目标",
            },
            {
                "id": "推文检查",
                "title": "立即检查更新",
                "usage": "/推文检查 [分组名]",
                "note": "立即检查并推送新内容；当前会话有多个分组时填写分组名",
                "warning": "先在面板启用分组并添加当前会话为推送目标；首次检查不发送已有推文",
            },
            {
                "id": "镜像测试",
                "title": "测试自建实例",
                "usage": "/镜像测试 [用户名] [数量] <实例URL>",
                "note": "用指定实例获取推文，检查是否可用",
            },
            {
                "id": "推文缓存清理",
                "title": "清理媒体缓存",
                "usage": "/推文缓存清理",
                "note": "删除下载的图片和视频，保留订阅和推送历史",
            },
            {
                "id": "推文记录清理",
                "title": "重置推送进度",
                "usage": "/推文记录清理 [分组名]",
                "note": "不填分组名时重置全部分组，面板推送历史保留",
                "warning": "下次检查只记录当前推文，不发送；之后继续推送新内容",
            },
        ],
    },
]

# Layout only: fit the complete logo within the header.
CSS = """
    *{box-sizing:border-box}html,body{margin:0;width:__WIDTH__px}body{font-family:MiSans,sans-serif;color:#2f353d;background:#f8f1e7}
    header{height:130px;background:#f1c779;border-bottom:6px solid #dfaa52;padding:20px 44px;display:flex;align-items:center;color:#363129;position:relative;overflow:hidden}
    .header-copy{position:relative;z-index:1}.header-art{position:absolute;right:38px;top:7px;width:110px;height:110px;mix-blend-mode:multiply;pointer-events:none}.header-art img{display:block;width:100%;height:100%;object-fit:contain}
    h1{font-size:48px;line-height:1.2;margin:0 0 10px}.subtitle{font-size:23px;margin:0;color:#5b462c}
    main{padding:20px 36px 24px}.section{--ink:#965036;--tint:#fff1e9;--rule:#e9ddd2;background:#fffdf9;border:1px solid #dfd3c2;border-radius:12px;margin-bottom:16px;overflow:hidden}
    .section-1{--ink:#3a6757;--tint:#edf5ee}.section-2{--ink:#775087;--tint:#f5eef8}.section-3{--ink:#875c22;--tint:#faf1df}
    .section-head{display:flex;justify-content:space-between;align-items:center;padding:12px 25px;background:var(--tint);border-bottom:1px solid var(--rule);border-left:7px solid var(--ink)}
    h2{margin:0;color:var(--ink);font-size:32px;line-height:1.3}.permission{font-size:21px;color:var(--ink)}
    .entries{padding:0 24px}
    .entry{min-width:0;padding:13px 0;border-bottom:1px solid var(--rule)}
    .entry:last-child{border-bottom:0}.entry-body{min-width:0;display:grid;grid-template-columns:240px minmax(0,1fr);gap:0 20px;align-items:baseline}
    h3{font-size:27px;line-height:1.4;margin:0;color:#363129}.usage{font-size:24px;font-weight:700;line-height:1.45;margin:0;color:var(--ink);overflow-wrap:normal;word-break:normal;max-width:100%;flex:0 1 auto}.note{font-size:22px;line-height:1.5;margin:0;color:#5c5c58}
    .entry-content{min-width:0;display:flex;flex-wrap:wrap;gap:5px 28px;align-items:baseline}.description{flex:1 1 340px;min-width:0}
    .section-note{font-size:22px;color:#67594c;line-height:1.55;padding:11px 24px;background:#fcf8f1;border-top:1px solid var(--rule)}
    .warning{font-size:22px;font-weight:700;line-height:1.45;margin:0;color:#975b15}
    .usage-tips{background:#fff8e9;border:2px solid #dfaa52;border-radius:12px;padding:17px 24px;margin-bottom:16px;display:grid;grid-template-columns:170px 1fr;align-items:center;gap:20px;font-size:22px;line-height:1.55;color:#67594c}.usage-tips h2{font-size:27px;color:#965036}.usage-tips p{margin:0}.usage-tips .help-command{font-size:23px;font-weight:700;color:#965036;margin-top:8px}.tips-notes p:first-child{font-weight:700;color:#483d2c}
    """


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def build_html() -> str:
    fonts = ""
    for weight, filename in [(400, "MiSans-Regular.woff2"), (700, "MiSans-Bold.woff2")]:
        data = base64.b64encode(
            (ROOT / "pages/dashboard/fonts" / filename).read_bytes()
        ).decode("ascii")
        fonts += f"@font-face{{font-family:MiSans;src:url(data:font/woff2;base64,{data});font-weight:{weight};font-display:block}}"
    logo_data = base64.b64encode((ROOT / "logo.png").read_bytes()).decode("ascii")
    sections = []
    for index, group in enumerate(GROUPS):
        entries = []
        for entry in group["entries"]:
            details = "".join(
                f'<p class="{field}">{esc(entry[field])}</p>'
                for field in ("note", "warning")
                if entry.get(field)
            )
            description = f'<div class="description">{details}</div>' if details else ""
            entries.append(
                f'<article class="entry" data-command="{esc(entry["id"])}">'
                f'<div class="entry-body"><h3>{esc(entry["title"])}</h3>'
                f'<div class="entry-content"><p class="usage">{esc(entry["usage"])}</p>'
                f"{description}</div></div></article>"
            )
        note = (
            f'<div class="section-note">{esc(group["note"])}</div>'
            if group.get("note")
            else ""
        )
        sections.append(
            f'<section class="section section-{index}"><div class="section-head">'
            f'<h2>{esc(group["title"])}</h2><span class="permission">{esc(group["permission"])}</span>'
            f'</div><div class="entries">{"".join(entries)}</div>{note}</section>'
        )
    tips_notes = "".join(f"<p>{esc(note)}</p>" for note in POSTER["tips"])
    styles = fonts + CSS.replace("__WIDTH__", str(WIDTH))
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{esc(POSTER['title'])}</title><style>{styles}</style></head><body>"
        f'<header><div class="header-copy"><h1>{esc(POSTER["title"])}</h1>'
        f'<p class="subtitle">{esc(POSTER["subtitle"])}</p></div>'
        f'<div class="header-art" aria-hidden="true"><img src="data:image/png;base64,{logo_data}" alt=""></div></header>'
        f'<main><section class="usage-tips"><div data-command="推文帮助">'
        f'<h2>{esc(POSTER["tips_title"])}</h2><p class="help-command">{esc(POSTER["help_command"])}</p></div>'
        f'<div class="tips-notes">{tips_notes}</div></section>{"".join(sections)}</main></body></html>'
    )


async def main(output_dir: Path, browser_executable: str | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    document = build_html()
    (output_dir / "tweet_help.html").write_text(document, encoding="utf-8")
    async with async_playwright() as playwright:
        options = {"executable_path": browser_executable} if browser_executable else {}
        browser = await playwright.chromium.launch(**options)
        try:
            page = await browser.new_page(
                viewport={"width": WIDTH, "height": 1200}, device_scale_factor=1
            )
            await page.route("**/*", lambda route: route.abort())
            await page.set_content(document, wait_until="load")
            await page.evaluate("document.fonts.ready")
            await page.evaluate(
                "Promise.all([...document.images].map(img => img.decode()))"
            )
            evidence = await page.evaluate("""() => ({
                commands: [...document.querySelectorAll('[data-command]')].map(e => e.dataset.command),
                width: document.documentElement.scrollWidth,
                height: document.documentElement.scrollHeight,
                overflow: [...document.querySelectorAll('h3, .usage, .note, .section-note, .permission, .warning, .tips-notes p')]
                    .filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent),
                fontsLoaded: document.fonts.check('22px MiSans')
            })""")
            expected_commands = ["推文帮助"] + [
                entry["id"] for group in GROUPS for entry in group["entries"]
            ]
            assert evidence["commands"] == expected_commands, evidence
            assert len(expected_commands) == len(set(expected_commands)), evidence
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
    with Image.open(output_dir / "tweet_help.png") as saved:
        assert saved.mode == "P" and saved.format == "PNG"
        assert len(saved.getpalette()) == 768
        colors = saved.getcolors(maxcolors=256)
        assert colors is not None
        evidence.update(mode=saved.mode, paletteColors=256, usedColors=len(colors))
    (output_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--browser-executable", help="Optional installed Chromium or Edge executable"
    )
    args = parser.parse_args()
    asyncio.run(main(args.output_dir, args.browser_executable))
