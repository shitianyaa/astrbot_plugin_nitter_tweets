"""QuietHtmlLog 过滤 HTML 后端过程日志的行为。"""

from __future__ import annotations

from media_support.html_backend.logging_util import QuietHtmlLog


def test_drops_session_try_empty_and_cooling():
    out: list[str] = []
    log = QuietHtmlLog(out.append)

    log("session load nitter.example keys=['a']")
    log("search try 1/3 host=nitter.example query='#x' kind=tag")
    log("user try 1/2 host=nitter.example user=nasa")
    log("search empty host=nitter.example, rotate next (1/3)")
    log("defer cooling nitter.example remain=30s")
    log("skip cooling nitter.example remain=10s")
    assert out == []


def test_keeps_failures_and_summaries():
    out: list[str] = []
    log = QuietHtmlLog(out.append)

    log("search fail host=a.example, rotate next (1/2): boom")
    log("search ok after rotate host=b.example tried=2/2")
    log("search empty after rotate hosts=2, query='#x' kind=tag, last_empty=a.example")
    log("punish a.example http=429 cooldown=30s")

    assert out == [
        "search fail host=a.example, rotate next (1/2): boom",
        "search ok after rotate host=b.example tried=2/2",
        "search empty after rotate hosts=2, query='#x' kind=tag, last_empty=a.example",
        "punish a.example http=429 cooldown=30s",
    ]


def test_keeps_ordinary_response_errors():
    out: list[str] = []
    log = QuietHtmlLog(out.append)

    log("search fail host=h1, rotate next (1/2): HTTP 503")
    log("search fail host=h2, rotate next (2/2): invalid page")

    assert out == [
        "search fail host=h1, rotate next (1/2): HTTP 503",
        "search fail host=h2, rotate next (2/2): invalid page",
    ]


def test_cooling_lines_always_dropped():
    """冷却跳过是限流簿记，恒被丢弃（原先在 verbose 下按 host 保留首条）。"""
    out: list[str] = []
    log = QuietHtmlLog(out.append)

    log("defer cooling h1 remain=5s")
    log("defer cooling h1 remain=4s")
    log("skip cooling h2 remain=3s")

    assert out == []


def test_service_wraps_plain_log_with_quiet():
    from media_support.html_backend.service import HtmlBackendConfig, HtmlNitterService

    out: list[str] = []
    svc = HtmlNitterService(
        HtmlBackendConfig(instances=["https://a.example"]),
        log=out.append,
    )
    svc.log("session load a.example keys=[]")
    svc.log("search try 1/1 host=a.example query='q' kind=phrase")
    svc.log("punish a.example http=429 cooldown=30s")
    assert out == ["punish a.example http=429 cooldown=30s"]
