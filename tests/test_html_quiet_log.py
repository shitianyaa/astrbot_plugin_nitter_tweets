# -*- coding: utf-8 -*-
"""QuietHtmlLog filters HTML backend chatter under brief_log_enabled."""

from __future__ import annotations

from media_support.html_backend.logging_util import QuietHtmlLog


def test_brief_drops_session_try_empty_and_cooling():
    out: list[str] = []
    log = QuietHtmlLog(out.append, brief=True)

    log("session load nitter.example keys=['a']")
    log("search try 1/3 host=nitter.example query='#x' kind=tag")
    log("user try 1/2 host=nitter.example user=nasa")
    log("search empty host=nitter.example, rotate next (1/3)")
    log("defer cooling nitter.example remain=30s")
    log("skip cooling nitter.example remain=10s")
    log("ensure soft-fail nitter.example, trying path anyway")
    log("anubis: solved difficulty=4 nonce=12")
    log("poast: solved token_len=40")
    log("gate nitter.example mode=plain http=200 detect=ok")

    assert out == []


def test_brief_keeps_failures_and_summaries():
    out: list[str] = []
    log = QuietHtmlLog(out.append, brief=True)

    log("search fail host=a.example, rotate next (1/2): boom")
    log("search ok after rotate host=b.example tried=2/2")
    log("search empty after rotate hosts=2, query='#x' kind=tag, last_empty=a.example")
    log("punish a.example http=429 cooldown=30s")
    log("gate a.example: cloudflare unsupported")
    log("anubis: no challenge json")

    assert out == [
        "search fail host=a.example, rotate next (1/2): boom",
        "search ok after rotate host=b.example tried=2/2",
        "search empty after rotate hosts=2, query='#x' kind=tag, last_empty=a.example",
        "punish a.example http=429 cooldown=30s",
        "gate a.example: cloudflare unsupported",
        "anubis: no challenge json",
    ]


def test_gate_lines_deduped_by_host_code_detect():
    out: list[str] = []
    log = QuietHtmlLog(out.append, brief=False)

    log("gate h1 mode=anubis http=200 detect=anubis")
    log("gate h1 mode=anubis http=200 detect=anubis")  # dup
    log("gate h1 mode=anubis http=200 detect=ok")  # different detect
    log("gate h1 mode=plain http=200 detect=ok")  # same detect+code, mode ignored
    log("gate h2 mode=plain http=200 detect=ok")

    assert out == [
        "gate h1 mode=anubis http=200 detect=anubis",
        "gate h1 mode=anubis http=200 detect=ok",
        "gate h2 mode=plain http=200 detect=ok",
    ]


def test_verbose_keeps_try_lines_but_still_drops_session_load():
    out: list[str] = []
    log = QuietHtmlLog(out.append, brief=False)

    log("session load h1 keys=['c']")
    log("search try 1/1 host=h1 query='x' kind=phrase")
    log("defer cooling h1 remain=5s")
    log("defer cooling h1 remain=4s")  # once per host in verbose

    assert out == [
        "search try 1/1 host=h1 query='x' kind=phrase",
        "defer cooling h1 remain=5s",
    ]


def test_service_wraps_plain_log_with_quiet():
    from media_support.html_backend.service import HtmlBackendConfig, HtmlNitterService

    out: list[str] = []
    svc = HtmlNitterService(
        HtmlBackendConfig(search_instances=["https://a.example"]),
        log=out.append,
        brief_log=True,
    )
    svc.log("session load a.example keys=[]")
    svc.log("search try 1/1 host=a.example query='q' kind=phrase")
    svc.log("punish a.example http=429 cooldown=30s")
    assert out == ["punish a.example http=429 cooldown=30s"]
