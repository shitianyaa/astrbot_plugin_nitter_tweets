from __future__ import annotations

from types import SimpleNamespace

import pytest
from astrbot.api.all import MessageChain
from astrbot.api.message_components import Plain

from delivery.telegram import (
    TelegramDeliveryAdapter,
    _TelegramClientWithoutLinkPreview,
)


class _Client:
    def __init__(self):
        self.message_kwargs = None

    async def send_message(self, **kwargs):
        self.message_kwargs = kwargs


class _Event:
    def __init__(self, client):
        self.client = client
        self.message_obj = SimpleNamespace(group_id="chat-1")

    @classmethod
    async def send_with_client(cls, client, chain, target):
        await client.send_message(chat_id=target, text="[tweet](https://x.com/status)")


@pytest.mark.asyncio
async def test_telegram_client_proxy_disables_link_preview():
    client = _Client()
    proxy = _TelegramClientWithoutLinkPreview(client)

    await proxy.send_message(chat_id="chat-1", text="tweet")

    options = client.message_kwargs["link_preview_options"]
    assert options.is_disabled is True


@pytest.mark.asyncio
async def test_telegram_adapter_event_chain_uses_preview_disabled_client():
    client = _Client()
    sender = SimpleNamespace(
        _event_target=lambda event: "telegram:GroupMessage:chat-1",
        _adapter_flood_control_attempt=lambda *args, **kwargs: None,
        _send_exception_attempt=lambda *args, **kwargs: None,
    )
    adapter = TelegramDeliveryAdapter(sender, SimpleNamespace())

    result = await adapter.send_event_chain(_Event(client), object(), "test")

    assert result.success is True
    assert client.message_kwargs["link_preview_options"].is_disabled is True


@pytest.mark.asyncio
async def test_telegram_adapter_context_chain_uses_platform_client():
    client = _Client()
    sender = SimpleNamespace(
        _adapter_flood_control_attempt=lambda *args, **kwargs: None,
        _send_exception_attempt=lambda *args, **kwargs: None,
    )
    profile = SimpleNamespace(
        platform=SimpleNamespace(client=client),
        session_id="chat-1",
    )
    adapter = TelegramDeliveryAdapter(sender, profile)
    chain = MessageChain([Plain("[tweet](https://x.com/status)")])
    chain.use_markdown(True)

    result = await adapter.send_context_chain(
        SimpleNamespace(), "telegram:GroupMessage:chat-1", chain, "test"
    )

    assert result.success is True
    assert client.message_kwargs["link_preview_options"].is_disabled is True
