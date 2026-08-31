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


def test_classify_page_rejects_login_maintenance_and_challenge_pages():
    assert (
        classify_page(b"<html><head><title>Login - Nitter</title></head></html>")
        == "error"
    )
    assert (
        classify_page(b"<html><body>This site is under maintenance</body></html>")
        == "error"
    )
    assert (
        classify_page(b"<html><head><title>Just a moment...</title></head></html>")
        == "error"
    )


def test_classify_page_marks_generic_html_as_other():
    assert classify_page(b"<html><body>unexpected page</body></html>") == "other"


def test_classify_page_marks_blank_body_as_empty():
    assert classify_page(b"  ") == "empty"


def test_classify_page_challenge_wins_over_timeline_markers():
    """A challenge interstitial that still contains timeline markup must be
    classified as an error, not a legitimate timeline."""
    html = (
        b"<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
        b'<body><div class="timeline-item"><div class="tweet-content">'
        b"placeholder</div></div></body></html>"
    )
    assert classify_page(html) == "error"
