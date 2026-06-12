"""
测试 xdown 视频解析 + 实际下载不同分辨率

用法:
    python tests/test_live_xdown.py              # 默认推文, 下载所有分辨率
    python tests/test_live_xdown.py <tweet_url>  # 指定推文

所有视频下载到 tests/downloads/ 目录
"""
import base64
import hashlib
import json
import re
import sys
import types
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

# add parent to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# mock astrbot
astrbot_mod = types.ModuleType("astrbot")
api_mod = types.ModuleType("astrbot.api")
class _L:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
api_mod.logger = _L()
sys.modules["astrbot"] = astrbot_mod
sys.modules["astrbot.api"] = api_mod

from media import XdownMediaParser  # noqa: E402

DOWNLOADS_DIR = Path(__file__).resolve().parent / "downloads"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class XdownMediaParserV2(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cover_url = ""
        self.items: list[tuple[str, str, str]] = []  # (kind, url, text)
        self._href = ""
        self._classes: set[str] = set()
        self._text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "img" and not self.cover_url:
            self.cover_url = str(d.get("src") or "")
            return
        if tag != "a":
            return
        classes = set(str(d.get("class") or "").split())
        if classes.intersection({"tw-button-dl", "abutton"}):
            self._href = str(d.get("href") or "")
            self._classes = classes
            self._text_parts = []

    def handle_data(self, data):
        if self._href:
            self._text_parts.append(data)

    def handle_endtag(self, tag):
        if tag != "a" or not self._href:
            return
        text = "".join(self._text_parts).strip()
        kind = XdownMediaParser._detect_kind(text, self._href)
        if kind:
            self.items.append((kind, self._href, text))
        self._href = ""
        self._classes = set()
        self._text_parts = []


def decode_jwt(url):
    parsed = urlparse(url)
    token = ""
    for p in parsed.query.split("&"):
        if p.startswith("token="):
            token = p[6:]
            break
    if not token:
        return {}
    try:
        b64 = token.split(".")[1]
        b64 += "=" * (-len(b64) % 4)
        return json.loads(base64.urlsafe_b64decode(b64))
    except Exception:
        return {}


def extract_video_id(url):
    p = decode_jwt(url)
    inner = p.get("url", "")
    if not inner:
        return ""
    path = urlparse(inner).path
    parts = path.split("/")
    for i, part in enumerate(parts):
        if part.endswith("_video") and i + 1 < len(parts):
            return parts[i + 1]
    return path


def parse_res(text):
    m = re.search(r"(\d+)p", text)
    return int(m.group(1)) if m else 0


def select_res(candidates, pref):
    if not candidates:
        return ""
    if pref == "highest" or not pref:
        return candidates[0][1]
    m = re.search(r"(\d+)p", pref)
    if not m:
        return candidates[0][1]
    target = int(m.group(1))
    for res, url in candidates:
        if res == target:
            return url
    lower = [(r, u) for r, u in candidates if r < target]
    if lower:
        return lower[0][1]
    return candidates[-1][1]


def download(url, dest: Path, label: str = "") -> bool:
    """下载文件到 dest，返回是否成功"""
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://xdown.app/",
        },
    )
    try:
        with urlopen(req, timeout=120) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  [FAIL] {label}: {e}")
        return False

    if len(data) == 0:
        print(f"  [FAIL] {label}: empty response")
        return False

    dest.write_bytes(data)
    size_mb = len(data) / (1024 * 1024)
    print(f"  [OK] {label}: {dest.name} ({size_mb:.1f} MB)")
    return True


def main():
    TWEET_URL = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://x.com/JuanEgg18/status/2064692617242448015"
    )

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Tweet: {TWEET_URL}")
    print(f"Download dir: {DOWNLOADS_DIR}")
    print("=" * 70)

    # 1. 请求 xdown
    data = urlencode({"q": TWEET_URL, "lang": "zh-cn"}).encode()
    req = Request(
        "https://xdown.app/api/ajaxSearch",
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://xdown.app",
            "Referer": "https://xdown.app/",
        },
    )
    with urlopen(req, timeout=30) as resp:
        raw = resp.read(2_000_000)

    payload = json.loads(raw.decode("utf-8", errors="replace"))
    assert payload.get("status") == "ok", f"xdown error: {payload}"
    html = payload.get("data") or ""

    # 2. 解析
    parser = XdownMediaParserV2()
    parser.feed(str(html))

    print(f"Cover: {parser.cover_url or '(none)'}")
    print(f"Total items: {len(parser.items)}")
    print()

    # 3. 分类
    images = []
    videos = []
    dynamics = []
    for k, u, t in parser.items:
        if k == "image":
            images.append((u, t))
        elif k == "video":
            videos.append((u, t))
        elif k == "dynamic":
            dynamics.append((u, t))

    print(f"Images: {len(images)}, Videos: {len(videos)}, GIFs: {len(dynamics)}")

    # 4. 打印所有解析结果
    if images:
        print("\n--- Images ---")
        for u, t in images:
            print(f'  text="{t}"  url={urljoin("https://xdown.app", u)[:80]}')
    if videos:
        print("\n--- Videos ---")
        for u, t in videos:
            fu = urljoin("https://xdown.app", u)
            vid = extract_video_id(fu)
            res = parse_res(t)
            print(f'  res={res}p  id={vid}  text="{t}"')
    if dynamics:
        print("\n--- GIFs ---")
        for u, t in dynamics:
            print(f'  text="{t}"')

    # 5. 有视频 → 跳过所有图片
    has_video = bool(videos or dynamics)
    print(f"\n{'='*70}")
    print(f"Has video/GIF -> skip ALL images: {has_video}")

    if has_video and images:
        print(f"  (would skip {len(images)} cover thumbnail(s))")

    # 6. 视频按 video_id 分组
    if videos:
        vc = {}
        for u, t in videos:
            fu = urljoin("https://xdown.app", u)
            vid = extract_video_id(fu)
            res = parse_res(t)
            vc.setdefault(vid, []).append((res, fu))

        print(f"\nVideo groups: {len(vc)}")

        for vid, cands in vc.items():
            cands.sort(key=lambda x: x[0], reverse=True)
            print(f"\n  video_id = {vid}")
            for res, url in cands:
                print(f"    {res}p  (full URL in JWT)")

            # 7. 下载不同分辨率
            print("\n  Downloading each resolution:")
            results = {}
            for res, url in cands:
                label = f"{res}p"
                fname = f"{vid}_{res}p.mp4"
                dest = DOWNLOADS_DIR / fname
                ok = download(url, dest, label)
                results[res] = {"url": url, "path": dest, "ok": ok}

            # 8. 模拟 select_res 选择结果
            print("\n  Resolution selection (simulated):")
            for pref in ["highest", "720p", "540p", "320p"]:
                chosen = select_res(cands, pref)
                # 从 url 中找到对应的分辨率
                chosen_res = next(
                    (r for r, u in cands if u == chosen), "?"
                )
                status = (
                    f"matched {chosen_res}p"
                    if chosen_res != "?"
                    else "fallback"
                )
                print(f"    pref={pref:<8} -> {chosen_res}p ({status})")

    # 9. 如果有 GIF 也下载
    if dynamics:
        print("\n--- Downloading GIFs ---")
        for u, t in dynamics:
            fu = urljoin("https://xdown.app", u)
            name_hash = hashlib.md5(fu.encode()).hexdigest()[:12]
            fname = f"gif_{name_hash}.gif"
            dest = DOWNLOADS_DIR / fname
            download(fu, dest, f"GIF ({t})")

    # 10. 汇总
    print(f"\n{'='*70}")
    print("All files in download dir:")
    for f in sorted(DOWNLOADS_DIR.iterdir()):
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
