"""Thin wrapper over the Razorpay SDK.

The SDK is synchronous; callers are async, so mutating calls are pushed to a
worker thread. This module does no policy or amount logic — it just talks to
Razorpay. Only app/executor.py is allowed to call the mutating methods here.
"""
from __future__ import annotations

import asyncio
from typing import Any

import razorpay

from app.config import settings
from app.models import utcnow


class RazorpayGateway:
    def __init__(self, key_id: str | None = None, key_secret: str | None = None) -> None:
        self._client = razorpay.Client(
            auth=(key_id or settings.razorpay_key_id, key_secret or settings.razorpay_key_secret)
        )

    async def create_payment_link(
        self,
        *,
        amount: int,
        description: str,
        reference_id: str,
        customer: dict[str, str] | None = None,
        accept_partial: bool = False,
        expire_after_hours: int = 72,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "amount": int(amount),
            "currency": "INR",
            "accept_partial": accept_partial,
            "description": description[:2048],
            "reference_id": reference_id,          # our idempotency handle
            "expire_by": int(utcnow().timestamp()) + expire_after_hours * 3600,
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
        }
        if customer:
            payload["customer"] = customer
        return await asyncio.to_thread(self._client.payment_link.create, payload)

    async def fetch_payment_link(self, plink_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._client.payment_link.fetch, plink_id)


# module-level default; tests inject a fake instead
_gateway: RazorpayGateway | None = None


def get_gateway() -> RazorpayGateway:
    global _gateway
    if _gateway is None:
        _gateway = RazorpayGateway()
    return _gateway
