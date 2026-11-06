"""HTML重要日志与DEBUG过程分流，回调兼容和会话加载抑制。"""

from media_support.html_backend.logging_util import QuietHtmlLog


def test_process_goes_to_debug_and_session_load_is_suppressed():
    main, debug = [], []
    log = QuietHtmlLog(main.append, debug_emit=debug.append)
    log("session load nitter.example keys=['a']")
    processes = [
        "search try 1/3 query='#x' kind=tag",
        "user try 1/2 user=nasa",
        "list try 1/2 list_id=123",
        "search empty, rotate next (1/3)",
        "user empty, rotate next (1/3)",
        "defer cooling remain=30s",
        "defer cooling remain=10s",
        "search global retry 1/2: all cooling",
    ]
    for text in processes:
        log(text)
    assert main == []
    assert debug == processes


def test_important_failures_and_rotation_summaries_stay_visible():
    main, debug = [], []
    log = QuietHtmlLog(main.append, debug_emit=debug.append)
    messages = [
        "search fail, rotate next (1/2): HTTP 503",
        "search ok after rotate tried=2/2",
        "search empty after rotate hosts=2",
        "punish host http=429 cooldown=30s",
        "search fail, rotate next (2/2): invalid page",
    ]
    for text in messages:
        log(text)
    assert main == messages
    assert debug == []


def test_custom_single_callback_keeps_process_without_new_protocol():
    messages = []
    log = QuietHtmlLog(messages.append)
    log("session load host keys=[]")
    log("user try 1/2 user=nasa")
    log("defer cooling remain=5s")
    assert messages == ["user try 1/2 user=nasa", "defer cooling remain=5s"]


def test_service_wraps_callbacks_and_keeps_both_routes():
    from media_support.html_backend.service import HtmlBackendConfig, HtmlNitterService

    main, debug = [], []
    service = HtmlNitterService(
        HtmlBackendConfig(), log=main.append, debug_log=debug.append
    )
    service.log("session load host keys=[]")
    service.log("search try 1/1 query='q' kind=phrase")
    service.log("punish host http=429 cooldown=30s")
    assert main == ["punish host http=429 cooldown=30s"]
    assert debug == ["search try 1/1 query='q' kind=phrase"]


def test_search_process_does_not_include_raw_query(monkeypatch):
    from unittest.mock import MagicMock
    from media_support.html_backend.pool import (
        HtmlNitterPool,
        PoolConfig,
        HtmlSearchResult,
    )

    log = MagicMock()
    pool = HtmlNitterPool(PoolConfig(instances=[]), log=log)
    monkeypatch.setattr(
        pool, "_hosts_for_rotation", lambda instance: ["http://test.example"]
    )
    monkeypatch.setattr(pool, "_paginate_search", lambda *a, **kw: HtmlSearchResult([]))
    pool.search("private query token=secret", limit=1)
    lines = [call.args[0] for call in log.call_args_list]
    assert any("query_chars=" in line for line in lines)
    assert all(
        "private query" not in line and "token=secret" not in line for line in lines
    )


def test_production_service_records_debug_even_with_default_config(monkeypatch):
    from unittest.mock import MagicMock
    from media_support.nitter import NitterService
    from shared import log_buffer

    monkeypatch.setattr("shared.observability.logger", MagicMock())
    log_buffer.clear()
    service = NitterService({})
    service.html.log("search try 1/1 query='q' kind=phrase")
    service.html.log("search fail, rotate next: timeout")
    assert len(log_buffer.snapshot(ring="debug")) == 1
    assert len(log_buffer.snapshot()) == 1
    log_buffer.clear()
