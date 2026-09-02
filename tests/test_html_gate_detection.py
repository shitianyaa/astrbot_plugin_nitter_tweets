from __future__ import annotations

from media_support.html_backend.modes import classify_page


def test_classify_page_accepts_timeline_content():
    html = (
        b"<!DOCTYPE html><html><body>"
        b'<div class="timeline-item"><div class="tweet-content">ok</div></div>'
        b"</body></html>"
    )
    assert classify_page(html) == "ok"


def test_classify_page_accepts_empty_nitter_timeline():
    html = b'<html><body><div class="timeline">No items found</div></body></html>'
    assert classify_page(html) == "ok"


def test_classify_page_rejects_login_and_maintenance_titles():
    assert (
        classify_page(b"<html><head><title>Login - Nitter</title></head></html>")
        == "error"
    )
    assert (
        classify_page(b"<html><head><title>Maintenance</title></head></html>")
        == "error"
    )
    assert (
        classify_page(b"<html><head><title>Access Denied</title></head></html>")
        == "error"
    )


def test_classify_page_rejects_nitter_error_panel():
    html = b'<html><body><div class="error-panel">User not found</div></body></html>'
    assert classify_page(html) == "error"


def test_classify_page_marks_generic_html_as_other():
    assert classify_page(b"<html><body>unexpected page</body></html>") == "other"


def test_classify_page_marks_blank_body_as_empty():
    assert classify_page(b"  ") == "empty"


def test_tweet_text_with_error_phrases_stays_ok():
    """通用英文短语出现在推文正文里完全正常，不能据此判定实例故障。"""
    for phrase in (
        b"Access Denied",
        b"just a moment",
        b"this site is under maintenance",
        b"service unavailable",
    ):
        html = (
            b'<html><body><div class="timeline">'
            b'<div class="timeline-item"><div class="tweet-content">'
            + phrase
            + b" happens when the API key expires</div></div>"
            b"</div></body></html>"
        )
        assert classify_page(html) == "ok", phrase


def test_cloudflare_beacon_does_not_fail_a_healthy_page():
    """CF 会往正常 200 响应里注入 beacon 脚本；这不是挑战页。

    仅支持自建实例后不再检测第三方挑战页，真实时间线内容说了算。
    """
    html = (
        b"<!DOCTYPE html><html><body>"
        b'<div class="timeline-item"><div class="tweet-content">normal</div></div>'
        b'<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
        b"</body></html>"
    )
    assert classify_page(html) == "ok"


def test_cloudflare_interstitial_without_timeline_is_not_ok():
    """挑战页没有时间线内容，仍然不会被当作可用页面。"""
    html = (
        b"<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
        b'<body><script src="/cdn-cgi/challenge-platform/x.js"></script></body></html>'
    )
    assert classify_page(html) in {"error", "other"}


def test_error_panel_still_wins_over_timeline_markup():
    html = (
        b'<html><body><div class="timeline"></div>'
        b'<div class="error-panel">blocked</div></body></html>'
    )
    assert classify_page(html) == "error"
