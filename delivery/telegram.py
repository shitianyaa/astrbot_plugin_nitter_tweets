from __future__ import annotations

from .default import DefaultDeliveryAdapter


class TelegramDeliveryAdapter(DefaultDeliveryAdapter):
    name = "telegram"
    is_telegram = True
