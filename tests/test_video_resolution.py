"""
测试视频分辨率选择 & 有视频跳过图片的逻辑。

覆盖:
- XdownMediaParser (带 text 字段)
- _decode_jwt_payload / _extract_video_id
- _parse_resolution / _select_resolution
- _resolve_media_urls 端到端
- 真实 xdown API 集成测试 (需提供推文 URL)

用法:
    pytest tests/test_video_resolution.py -v                          # 全部单元测试
    pytest tests/test_video_resolution.py -v -k "test_live"           # 仅集成测试
    python -m tests.test_video_resolution                             # 手动跑
"""
from __future__ import annotations

import base64
import json
import re
import sys
import types
import unittest
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse

# --------------- mock astrbot ---------------
if "astrbot.api" not in sys.modules:
    astrbot_mod = types.ModuleType("astrbot")
    api_mod = types.ModuleType("astrbot.api")
    class _Logger:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
    api_mod.logger = _Logger()
    sys.modules["astrbot"] = astrbot_mod
    sys.modules["astrbot.api"] = api_mod

# --------------- 真实模块 ---------------
from media import XdownMediaParser


# ================================================================
# 工具函数（从 media.py 独立复制，测试目标）
# ================================================================

def _decode_jwt_payload(url: str) -> dict:
    """从 xdown 代理 URL 的 JWT 中解码 payload"""
    parsed = urlparse(url)
    token = ""
    for part in parsed.query.split("&"):
        if part.startswith("token="):
            token = part[len("token="):]
            break
    if not token:
        return {}
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}


def _extract_video_id(url: str) -> str:
    """
    从 xdown 代理 URL 中提取推文视频唯一标识。
    路径格式: /<type>_video/<tweet_id>/pu/vid/.../<file>.mp4
    支持 ext_tw_video, amplify_video 等。
    """
    payload = _decode_jwt_payload(url)
    inner_url = payload.get("url", "")
    if not inner_url:
        return ""
    inner_path = urlparse(inner_url).path
    parts = inner_path.split("/")
    for i, part in enumerate(parts):
        if part.endswith("_video") and i + 1 < len(parts):
            return parts[i + 1]
    return inner_path


def _parse_resolution(text: str) -> int:
    """从链接文字提取分辨率，如 '下载 MP4 (720p)' -> 720"""
    m = re.search(r"(\d+)p", text)
    return int(m.group(1)) if m else 0


def _select_resolution(
    candidates: list[tuple[int, str]], pref: str
) -> str:
    """
    按偏好选择分辨率。
    candidates: [(resolution_int, url), ...] 已降序排列。
    """
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
    lower = [(res, url) for res, url in candidates if res < target]
    if lower:
        return lower[0][1]
    return candidates[-1][1]


# ================================================================
# 模拟 xdown HTML (基于常见返回结构)
# ================================================================

# 纯图片推文
HTML_IMAGE_ONLY = """
<div>
  <img src="/img/cover_thumb.jpg" />
  <a class="tw-button-dl" href="/dl?token=img1">图片</a>
  <a class="tw-button-dl" href="/dl?token=img2">图片</a>
  <a class="tw-button-dl" href="/dl?token=img3">图片</a>
</div>
"""

# 视频推文（多分辨率 + 封面缩略图）
HTML_VIDEO_MULTI_RES = """
<div>
  <img src="/img/video_cover.jpg" />
  <a class="tw-button-dl" href="/dl?token=cover_img">图片</a>
  <a class="tw-button-dl" href="/dl?token=vid_720">下载 MP4 (720p)</a>
  <a class="tw-button-dl" href="/dl?token=vid_540">下载 MP4 (540p)</a>
  <a class="tw-button-dl" href="/dl?token=vid_320">下载 MP4 (320p)</a>
</div>
"""

# GIF 推文
HTML_GIF = """
<div>
  <img src="/img/gif_cover.jpg" />
  <a class="tw-button-dl" href="/dl?token=gif">下载 GIF</a>
  <a class="tw-button-dl" href="/dl?token=cover_img">图片</a>
</div>
"""

# 单视频、单分辨率
HTML_VIDEO_SINGLE = """
<div>
  <a class="tw-button-dl" href="/dl?token=vid">下载 MP4 (highest)</a>
</div>
"""

# 无封面图片的视频
HTML_VIDEO_NO_COVER = """
<div>
  <a class="tw-button-dl" href="/dl?token=vid_720">下载 MP4 (720p)</a>
  <a class="tw-button-dl" href="/dl?token=vid_540">下载 MP4 (540p)</a>
</div>
"""


# ================================================================
# 改进版 Parser（带 text 字段）
# ================================================================

class XdownMediaParserV2(HTMLParser):
    """与 media.py 中 XdownMediaParser 一致，items 增加 text 字段"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cover_url = ""
        self.items: list[tuple[str, str, str]] = []  # (kind, url, text)
        self._href = ""
        self._classes: set[str] = set()
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        attrs_dict = dict(attrs)
        if tag == "img" and not self.cover_url:
            self.cover_url = str(attrs_dict.get("src") or "")
            return
        if tag != "a":
            return
        classes = set(str(attrs_dict.get("class") or "").split())
        if classes.intersection({"tw-button-dl", "abutton"}):
            self._href = str(attrs_dict.get("href") or "")
            self._classes = classes
            self._text_parts = []

    def handle_data(self, data: str):
        if self._href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag != "a" or not self._href:
            return
        text = "".join(self._text_parts).strip()
        kind = XdownMediaParser._detect_kind(text, self._href)
        if kind:
            self.items.append((kind, self._href, text))
        self._href = ""
        self._classes = set()
        self._text_parts = []


# ================================================================
# 测试
# ================================================================

class TestXdownMediaParserV2(unittest.TestCase):
    """测试改进版 Parser：带 text 字段"""

    def test_parse_image_only(self):
        parser = XdownMediaParserV2()
        parser.feed(HTML_IMAGE_ONLY)
        self.assertEqual(parser.cover_url, "/img/cover_thumb.jpg")
        self.assertEqual(len(parser.items), 3)
        for kind, url, text in parser.items:
            self.assertEqual(kind, "image")
            self.assertIn("图片", text)

    def test_parse_video_multi_res_has_text(self):
        parser = XdownMediaParserV2()
        parser.feed(HTML_VIDEO_MULTI_RES)
        texts = {text for _, _, text in parser.items}
        self.assertIn("下载 MP4 (720p)", texts)
        self.assertIn("下载 MP4 (540p)", texts)
        self.assertIn("下载 MP4 (320p)", texts)
        self.assertIn("图片", texts)

    def test_parse_video_multi_res_item_count(self):
        parser = XdownMediaParserV2()
        parser.feed(HTML_VIDEO_MULTI_RES)
        videos = [(k, t) for k, _, t in parser.items if k == "video"]
        images = [(k, t) for k, _, t in parser.items if k == "image"]
        self.assertEqual(len(videos), 3)
        self.assertEqual(len(images), 1)


class TestParseResolution(unittest.TestCase):
    """测试分辨率提取"""

    def test_standard(self):
        self.assertEqual(_parse_resolution("下载 MP4 (720p)"), 720)
        self.assertEqual(_parse_resolution("下载 MP4 (540p)"), 540)
        self.assertEqual(_parse_resolution("下载 MP4 (320p)"), 320)

    def test_different_formats(self):
        self.assertEqual(_parse_resolution("Download Video (1080p)"), 1080)
        self.assertEqual(_parse_resolution("MP4 480p"), 480)
        self.assertEqual(_parse_resolution("(2160p)"), 2160)

    def test_no_resolution(self):
        self.assertEqual(_parse_resolution("下载 MP4"), 0)
        self.assertEqual(_parse_resolution("图片"), 0)
        self.assertEqual(_parse_resolution(""), 0)

    def test_highest_label(self):
        self.assertEqual(_parse_resolution("下载 MP4 (highest)"), 0)


class TestSelectResolution(unittest.TestCase):
    """测试分辨率选择逻辑"""

    def setUp(self):
        self.candidates_720_540_320 = [
            (720, "url720"),
            (540, "url540"),
            (320, "url320"),
        ]

    def test_highest(self):
        result = _select_resolution(self.candidates_720_540_320, "highest")
        self.assertEqual(result, "url720")

    def test_empty_pref(self):
        result = _select_resolution(self.candidates_720_540_320, "")
        self.assertEqual(result, "url720")

    def test_exact_match_540(self):
        result = _select_resolution(self.candidates_720_540_320, "540p")
        self.assertEqual(result, "url540")

    def test_exact_match_320(self):
        result = _select_resolution(self.candidates_720_540_320, "320p")
        self.assertEqual(result, "url320")

    def test_fallback_to_lower_1080p(self):
        """指定的 1080p 不存在，候选是 [720, 540, 320]，回退到最近的较低分辨率 720"""
        result = _select_resolution(self.candidates_720_540_320, "1080p")
        self.assertEqual(result, "url720")

    def test_fallback_to_lowest(self):
        """指定的 480p 不存在，候选是 [720, 540, 320]，回退到 320（唯一低于 480 的）"""
        result = _select_resolution(self.candidates_720_540_320, "480p")
        self.assertEqual(result, "url320")

    def test_no_lower_fallback_to_minimum(self):
        """指定的分辨率低于所有候选，无更低者，选最低"""
        candidates = [(720, "u720"), (540, "u540")]
        result = _select_resolution(candidates, "240p")
        self.assertEqual(result, "u540")

    def test_empty_candidates(self):
        self.assertEqual(_select_resolution([], "720p"), "")

    def test_single_candidate(self):
        result = _select_resolution([(720, "only")], "540p")
        self.assertEqual(result, "only")

    def test_unsorted_input_still_works(self):
        """select_resolution 假设输入已排序，unsorted 也按原样处理（first match wins）"""
        candidates = [(320, "u320"), (720, "u720"), (540, "u540")]
        result = _select_resolution(candidates, "540p")
        self.assertEqual(result, "u540")


class TestJwtDecode(unittest.TestCase):
    """测试 JWT 解码"""

    def test_decode_valid(self):
        # 手工构造一个简单 JWT
        header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
        payload = base64.urlsafe_b64encode(
            b'{"url":"https://video.twimg.com/ext_tw_video/12345/pu/vid/avc1/720x1280/abc.mp4"}'
        ).decode().rstrip("=")
        token = f"{header}.{payload}.sig"
        url = f"https://xdown.app/dl?token={token}"
        result = _decode_jwt_payload(url)
        self.assertIn("url", result)

    def test_decode_no_token(self):
        result = _decode_jwt_payload("https://example.com/video.mp4")
        self.assertEqual(result, {})

    def test_decode_invalid_base64(self):
        result = _decode_jwt_payload("https://xdown.app/dl?token=xxx.NOT_BASE64!!!.sig")
        self.assertEqual(result, {})

    def test_extract_video_id_ext_tw(self):
        header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
        payload = base64.urlsafe_b64encode(
            b'{"url":"https://video.twimg.com/ext_tw_video/1234567890/pu/vid/720x1280/vid.mp4"}'
        ).decode().rstrip("=")
        token = f"{header}.{payload}.sig"
        url = f"https://xdown.app/dl?token={token}"
        vid = _extract_video_id(url)
        self.assertEqual(vid, "1234567890")

    def test_extract_video_id_amplify(self):
        header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
        payload = base64.urlsafe_b64encode(
            b'{"url":"https://video.twimg.com/amplify_video/9876543210/pu/vid/1080x1920/vid.mp4"}'
        ).decode().rstrip("=")
        token = f"{header}.{payload}.sig"
        url = f"https://xdown.app/dl?token={token}"
        vid = _extract_video_id(url)
        self.assertEqual(vid, "9876543210")

    def test_extract_video_id_no_match_returns_path(self):
        result = _extract_video_id("https://example.com/just/a/video.mp4")
        self.assertEqual(result, "")

    def test_same_tweet_different_resolutions_same_id(self):
        """同一条推文不同分辨率的 video_id 应该相同"""
        tweet_id = "1111222233334444"
        header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
        payload_720 = base64.urlsafe_b64encode(
            f'{{"url":"https://video.twimg.com/ext_tw_video/{tweet_id}/pu/vid/720x1280/vid.mp4"}}'.encode()
        ).decode().rstrip("=")
        payload_320 = base64.urlsafe_b64encode(
            f'{{"url":"https://video.twimg.com/ext_tw_video/{tweet_id}/pu/vid/320x568/vid.mp4"}}'.encode()
        ).decode().rstrip("=")
        id_720 = _extract_video_id(
            f"https://xdown.app/dl?token={header}.{payload_720}.sig"
        )
        id_320 = _extract_video_id(
            f"https://xdown.app/dl?token={header}.{payload_320}.sig"
        )
        self.assertEqual(id_720, id_320)


class TestVideoSkipImages(unittest.TestCase):
    """测试有视频时跳过图片的逻辑"""

    def _resolve_mock(self, html: str, pref: str = "highest") -> list[tuple[str, str]]:
        """模拟 _resolve_media_urls 的核心逻辑"""
        parser = XdownMediaParserV2()
        parser.feed(html)

        has_video = any(
            kind in {"video", "dynamic"} for kind, _, _ in parser.items
        )
        result: list[tuple[str, str]] = []
        video_candidates: dict[str, list[tuple[int, str]]] = {}

        base_url = "https://xdown.app"
        for kind, url, text in parser.items:
            full_url = urljoin(base_url, url)
            if kind == "image" and has_video:
                continue  # 有视频跳过所有图片
            if kind == "video":
                vid = _extract_video_id(full_url)
                res = _parse_resolution(text)
                video_candidates.setdefault(vid, []).append((res, full_url))
            else:
                result.append((kind, full_url))

        for vid, candidates in video_candidates.items():
            candidates.sort(key=lambda x: x[0], reverse=True)
            chosen = _select_resolution(candidates, pref)
            result.append(("video", chosen))

        return result

    def test_image_only_no_skip(self):
        result = self._resolve_mock(HTML_IMAGE_ONLY)
        kinds = {k for k, _ in result}
        self.assertEqual(kinds, {"image"})
        self.assertEqual(len(result), 3)

    def test_video_skips_all_images(self):
        result = self._resolve_mock(HTML_VIDEO_MULTI_RES)
        kinds = {k for k, _ in result}
        self.assertNotIn("image", kinds)
        self.assertIn("video", kinds)

    def test_video_skips_cover_image(self):
        result = self._resolve_mock(HTML_VIDEO_MULTI_RES)
        # 没有 image 结果
        image_urls = [u for k, u in result if k == "image"]
        self.assertEqual(len(image_urls), 0)

    def test_video_only_one_downloaded_highest(self):
        result = self._resolve_mock(HTML_VIDEO_MULTI_RES, pref="highest")
        videos = [u for k, u in result if k == "video"]
        self.assertEqual(len(videos), 1)

    def test_video_select_540p(self):
        result = self._resolve_mock(HTML_VIDEO_MULTI_RES, pref="540p")
        videos = [u for k, u in result if k == "video"]
        self.assertEqual(len(videos), 1)
        self.assertIn("token=vid_540", videos[0])

    def test_video_select_320p(self):
        result = self._resolve_mock(HTML_VIDEO_MULTI_RES, pref="320p")
        videos = [u for k, u in result if k == "video"]
        self.assertEqual(len(videos), 1)
        self.assertIn("token=vid_320", videos[0])

    def test_gif_skips_cover_image(self):
        result = self._resolve_mock(HTML_GIF)
        kinds = {k for k, _ in result}
        self.assertNotIn("image", kinds)
        self.assertIn("dynamic", kinds)

    def test_single_video_single_res(self):
        result = self._resolve_mock(HTML_VIDEO_SINGLE)
        videos = [u for k, u in result if k == "video"]
        self.assertEqual(len(videos), 1)

    def test_video_no_cover_image(self):
        result = self._resolve_mock(HTML_VIDEO_NO_COVER)
        kinds = {k for k, _ in result}
        self.assertEqual(kinds, {"video"})
        self.assertEqual(len(result), 1)


class TestLiveXdownApi(unittest.TestCase):
    """真实 xdown API 集成测试 — 需提供推文 URL"""

    TWEET_URL = None  # 运行时设置，如 "https://x.com/NASA/status/123456789"

    def test_live_fetch_and_parse(self):
        """用真实推文 URL 测试完整解析链路"""
        tweet_url = self.TWEET_URL or getattr(self, "_tweet_url", None)
        if not tweet_url:
            self.skipTest("未设置推文 URL，跳过集成测试。用法：TEST_URL='https://x.com/...' pytest ...")
            return

        from urllib.request import Request, urlopen

        xdown_api = "https://xdown.app/api/ajaxSearch"
        data = urlencode({"q": tweet_url, "lang": "zh-cn"}).encode("utf-8")
        req = Request(
            xdown_api,
            data=data,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://xdown.app",
                "Referer": "https://xdown.app/",
            },
        )
        with urlopen(req, timeout=30) as resp:
            raw = resp.read(2_000_000)

        payload = json.loads(raw.decode("utf-8", errors="replace"))
        self.assertEqual(payload.get("status"), "ok", f"xdown 返回非 ok: {payload}")

        html = payload.get("data") or ""
        parser = XdownMediaParserV2()
        parser.feed(str(html))

        # ========== 打印解析详情 ==========
        print(f"\n{'='*60}")
        print(f"推文 URL: {tweet_url}")
        print(f"封面图片: {parser.cover_url or '(无)'}")
        print(f"媒体条目: {len(parser.items)}")
        for i, (kind, url, text) in enumerate(parser.items):
            print(f"  [{i}] kind={kind:<7} text={text:<25} url={url[:80]}")
        print(f"{'='*60}")

        # ========== 分类统计 ==========
        images = [(k, u, t) for k, u, t in parser.items if k == "image"]
        videos = [(k, u, t) for k, u, t in parser.items if k == "video"]
        dynamics = [(k, u, t) for k, u, t in parser.items if k == "dynamic"]
        print(f"图片: {len(images)}, 视频: {len(videos)}, GIF: {len(dynamics)}")

        # ========== 模拟新逻辑 ==========
        has_video = bool(videos) or bool(dynamics)
        print(f"\n有视频/GIF: {has_video}")

        if has_video:
            print("  → 跳过所有图片")
            skipped = len(images)
            print(f"    跳过 {skipped} 张缩略图")

        if videos:
            video_candidates: dict[str, list[tuple[int, str]]] = {}
            for kind, url, text in videos:
                full_url = urljoin("https://xdown.app", url)
                vid = _extract_video_id(full_url)
                res = _parse_resolution(text)
                video_candidates.setdefault(vid, []).append((res, full_url))

            print(f"\n  视频组数: {len(video_candidates)}")
            for vid, cands in video_candidates.items():
                cands.sort(key=lambda x: x[0], reverse=True)
                print(f"    video_id={vid[:20]}...")
                for res, u in cands:
                    print(f"      {res}p -> {u[:80]}")
                for pref in ["highest", "720p", "540p", "320p"]:
                    chosen = _select_resolution(cands, pref)
                    chosen_short = chosen.rsplit("token=", 1)[-1] if "token=" in chosen else chosen[:40]
                    print(f"      偏好={pref:<8} 选择={chosen_short}")
            self.assertGreaterEqual(len(video_candidates), 1, "至少应有一个视频组")


# ================================================================
# 运行入口
# ================================================================
if __name__ == "__main__":
    import os

    tweet_url = os.environ.get("TEST_URL")
    if tweet_url:
        # 注入到 test_live 类
        TestLiveXdownApi.TWEET_URL = tweet_url

    unittest.main()
