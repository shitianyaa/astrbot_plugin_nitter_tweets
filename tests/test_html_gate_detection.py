from __future__ import annotations

from media_support.html_backend.modes import detect_gate


def test_detect_gate_recognizes_real_timeline_content_even_with_just_a_moment_text():
    html = (
        b"<!DOCTYPE html><html><body>"
        b'<div class="timeline-item">'
        b'<a class="tweet-link" href="/user/status/123"></a>'
        b'<div class="tweet-content media-body">give me just a moment to catch my breath please... \xe2\x99\xa1</div>'
        b"</div></body></html>"
    )
    assert detect_gate(html) == "ok"


def test_detect_gate_recognizes_real_timeline_content_with_cf_challenge_platform_beacon():
    html = (
        b"<!DOCTYPE html><html><body>"
        b'<div class="timeline-item">'
        b'<a class="tweet-link" href="/user/status/123"></a>'
        b'<div class="tweet-content">Normal tweet content</div>'
        b"</div>"
        b'<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
        b"</body></html>"
    )
    assert detect_gate(html) == "ok"


def test_detect_gate_recognizes_empty_timeline_with_cf_beacon():
    html = (
        b"<!DOCTYPE html><html><head><title>nitter</title></head><body>"
        b'<div class="site-name">nitter</div><div class="timeline-none">No items found</div>'
        b'<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
        b"</body></html>"
    )
    assert detect_gate(html) == "ok"


def test_detect_gate_recognizes_genuine_cloudflare_interstitial():
    html = (
        b"<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>"
        b'<div id="cf-turnstile"></div>'
        b'<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>'
        b"</body></html>"
    )
    assert detect_gate(html) == "cf"


def test_detect_gate_recognizes_anubis_challenge():
    html = (
        b"<!doctype html><html><head><title>Making sure you're not a bot!</title></head><body>"
        b'<script id="anubis_challenge" type="application/json">{"challenge":{}}</script>'
        b"</body></html>"
    )
    assert detect_gate(html) == "anubis"


def test_detect_gate_recognizes_poast_sha1_challenge():
    html = (
        b"<html><head><title>Verifying your browser...</title></head><body>"
        b"<script>const a0_0x2a54 = ['a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2'];</script>"
        b"</body></html>"
    )
    assert detect_gate(html) == "poast_sha1"


def test_explicit_anubis_challenge_wins_over_placeholder_timeline_nodes():
    html = (
        b"<html><body>"
        b'<div class="timeline-item"><div class="tweet-content">loading</div></div>'
        b'<script id="anubis_challenge" type="application/json">'
        b'{"challenge":{}}</script>'
        b"</body></html>"
    )

    assert detect_gate(html) == "anubis"


def test_explicit_poast_challenge_wins_over_placeholder_timeline_nodes():
    html = (
        b"<html><head><title>Verifying your browser...</title></head><body>"
        b'<div class="timeline-item"><div class="tweet-content">loading</div></div>'
        b"<script>const a0_0x2a54 = ['sha1']; const res='';</script>"
        b"</body></html>"
    )

    assert detect_gate(html) == "poast_sha1"


def test_explicit_error_panel_wins_over_placeholder_timeline_nodes():
    html = (
        b"<html><body>"
        b'<div class="error-panel">User not found</div>'
        b'<div class="timeline-item"><div class="tweet-content">dummy template</div></div>'
        b"</body></html>"
    )

    assert detect_gate(html) == "error"
