"""测试"仅图片"模式：下载 xdown 标记为 image 的条目，看看是不是视频封面缩略图"""
import base64
import json
import sys
import types
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

astrbot_mod = types.ModuleType("astrbot")
api_mod = types.ModuleType("astrbot.api")
class _L:
    info = warning = error = debug = lambda *a, **kw: None
api_mod.logger = _L()
sys.modules["astrbot"] = astrbot_mod
sys.modules["astrbot.api"] = api_mod

from media import XdownMediaParser  # noqa: E402


class P2(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cover_url = ""
        self.items: list[tuple[str, str, str]] = []
        self._href = ""
        self._classes: set[str] = set()
        self._text_parts: list[str] = []

    def handle_starttag(self, t, a):
        d = dict(a)
        if t == "img" and not self.cover_url:
            self.cover_url = str(d.get("src") or "")
            return
        if t != "a":
            return
        cs = set(str(d.get("class") or "").split())
        if cs.intersection({"tw-button-dl", "abutton"}):
            self._href = str(d.get("href") or "")
            self._classes = cs
            self._text_parts = []

    def handle_data(self, d):
        if self._href:
            self._text_parts.append(d)

    def handle_endtag(self, t):
        if t != "a" or not self._href:
            return
        text = "".join(self._text_parts).strip()
        k = XdownMediaParser._detect_kind(text, self._href)
        if k:
            self.items.append((k, self._href, text))
        self._href = ""
        self._classes = set()
        self._text_parts = []


def main():
    TWEET_URL = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://x.com/JuanEgg18/status/2064692617242448015"
    )

    print(f"Tweet: {TWEET_URL}")
    print("=" * 70)

    data = urlencode({"q": TWEET_URL, "lang": "zh-cn"}).encode()
    req = Request(
        "https://xdown.app/api/ajaxSearch",
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0",
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

    parser = P2()
    parser.feed(str(html))

    print(f'Cover (from <img>): {parser.cover_url or "(none)"}')
    print(f"Total items: {len(parser.items)}")

    images = [(u, t) for k, u, t in parser.items if k == "image"]
    videos = [(u, t) for k, u, t in parser.items if k == "video"]

    print(f"\nImages: {len(images)}, Videos: {len(videos)}")
    print(f"Has video -> skip all images: {bool(videos)}")

    if not images:
        print("\nNo images to download. This is a pure video tweet.")
        return

    base = "https://xdown.app"
    out_dir = Path(__file__).resolve().parent / "downloads"
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, (u, t) in enumerate(images):
        fu = urljoin(base, u)

        # decode JWT to see inner URL
        parsed = urlparse(fu)
        token = ""
        for p in parsed.query.split("&"):
            if p.startswith("token="):
                token = p[6:]
                break
        inner_url = ""
        if token:
            try:
                b64 = token.split(".")[1]
                b64 += "=" * (-len(b64) % 4)
                inner_url = json.loads(base64.urlsafe_b64decode(b64)).get("url", "")
            except Exception:
                pass

        print(f"\nImage #{i}:")
        print(f'  xdown label: "{t}"')
        print(f"  real URL   : {inner_url}")

        # download it
        fname = f"cover_thumbnail_{i}.jpg"
        dest = out_dir / fname
        req2 = Request(
            fu,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://xdown.app/",
            },
        )
        try:
            with urlopen(req2, timeout=60) as r2:
                img_data = r2.read()
            dest.write_bytes(img_data)
            print(f"  Downloaded : {fname} ({len(img_data)/1024:.0f} KB)")
        except Exception as e:
            print(f"  Download FAIL: {e}")

    print(f"\n{'='*70}")
    print("Conclusion:")
    print(
        "  The 'image' entry in a video tweet is the video cover thumbnail,"
    )
    print(
        "  NOT an actual photo. Sending it as a 'picture attachment' is misleading."
    )
    print(
        "  New logic: has_video -> skip ALL images -> no misleading thumbnail sent."
    )


if __name__ == "__main__":
    main()
