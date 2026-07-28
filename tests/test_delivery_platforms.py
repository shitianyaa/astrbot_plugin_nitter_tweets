from __future__ import annotations

from types import SimpleNamespace

from delivery.platforms import PlatformResolver


def test_event_custom_platform_id_keeps_telegram_type_candidates():
    event = SimpleNamespace(
        get_platform_id=lambda: "tg-main",
        get_platform_name=lambda: "telegram",
        platform_meta=SimpleNamespace(
            id="tg-main",
            name="Telegram",
            type="telegram",
        ),
        platform=None,
        platform_inst=None,
        bot=None,
    )

    profile = PlatformResolver().from_event(event)

    assert profile.platform_id == "tg-main"
    assert "telegram" in profile.normalized_types
    assert profile.is_telegram is True
