from __future__ import annotations

from types import SimpleNamespace

import pytest

from delivery.default import DefaultDeliveryAdapter
from delivery.onebot import OneBotDeliveryAdapter
from delivery.platforms import PlatformDeliveryRegistry, PlatformResolver
from delivery.qq_official import QQOfficialDeliveryAdapter


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


@pytest.mark.parametrize(
    "platform_type",
    ["aiocqhttp", "onebot", "onebot_v11", "napcat"],
)
def test_private_qq_platform_types_use_onebot_delivery(platform_type):
    profile = PlatformResolver().from_umo(None, f"{platform_type}:GroupMessage:123")

    adapter = PlatformDeliveryRegistry().adapter_for(None, profile)

    assert profile.is_onebot is True
    assert profile.is_qq_official is False
    assert isinstance(adapter, OneBotDeliveryAdapter)
    assert adapter.supports_merged_forward is True
    assert adapter.should_split_direct_images is True
    assert adapter.should_split_direct_videos is True


@pytest.mark.parametrize("platform_type", ["qq_official", "qq_official_webhook"])
def test_qq_official_event_stays_out_of_onebot_even_with_call_action(platform_type):
    event = SimpleNamespace(
        get_platform_id=lambda: "official-bot",
        get_platform_name=lambda: platform_type,
        platform_meta=SimpleNamespace(
            id="official-bot",
            name=platform_type,
            type=platform_type,
        ),
        platform=None,
        platform_inst=None,
        bot=SimpleNamespace(call_action=lambda *args, **kwargs: None),
    )

    profile = PlatformResolver().from_event(event)
    adapter = PlatformDeliveryRegistry().adapter_for(None, profile)

    assert profile.is_qq_official is True
    assert profile.is_onebot is False
    assert isinstance(adapter, QQOfficialDeliveryAdapter)
    assert isinstance(adapter, DefaultDeliveryAdapter)
    assert adapter.supports_merged_forward is False
    assert adapter.should_split_direct_images is True
    assert adapter.should_split_direct_videos is True


@pytest.mark.parametrize("platform_type", ["qq_official", "qq_official_webhook"])
def test_qq_official_umo_uses_official_adapter(platform_type):
    profile = PlatformResolver().from_umo(
        None,
        f"{platform_type}:GroupMessage:group-openid",
    )

    adapter = PlatformDeliveryRegistry().adapter_for(None, profile)

    assert profile.is_qq_official is True
    assert profile.is_onebot is False
    assert isinstance(adapter, QQOfficialDeliveryAdapter)


@pytest.mark.parametrize("instance_id", ["qq", "qq_official", "qqofficial"])
def test_resolved_onebot_metadata_takes_priority_over_instance_id(instance_id):
    platform = SimpleNamespace(
        meta=lambda: SimpleNamespace(
            id=instance_id,
            name="aiocqhttp",
            type="aiocqhttp",
        ),
        config={"type": "qq_official"},
    )
    context = SimpleNamespace(
        get_platform_inst=lambda platform_id: (
            platform if platform_id == instance_id else None
        )
    )

    profile = PlatformResolver().from_umo(
        context,
        f"{instance_id}:GroupMessage:123",
    )
    adapter = PlatformDeliveryRegistry().adapter_for(None, profile)

    assert profile.normalized_types == {"aiocqhttp"}
    assert profile.is_onebot is True
    assert profile.is_qq_official is False
    assert isinstance(adapter, OneBotDeliveryAdapter)


def test_legacy_qq_instance_id_is_not_treated_as_qq_official():
    profile = PlatformResolver().from_umo(None, "qq:GroupMessage:123")
    adapter = PlatformDeliveryRegistry().adapter_for(None, profile)

    assert profile.is_qq_official is False
    assert profile.is_onebot is False
    assert profile.should_split_qq_direct_images is True
    assert profile.should_split_qq_direct_videos is True
    assert isinstance(adapter, DefaultDeliveryAdapter)
