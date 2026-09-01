"""Webhook signature verification.

Razorpay signs webhooks as HMAC-SHA256 over the RAW request body, keyed by the
webhook secret, hex-encoded, in the `X-Razorpay-Signature` header.

This is deterministic code and stays that way — the LLM never touches signature
verification (architectural law).
"""
from __future__ import annotations

import hashlib
import hmac


def compute_signature(raw_body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_body: bytes, signature: str | None, secret: str) -> bool:
    """Constant-time compare of the received signature against a fresh HMAC.

    Returns False (never raises) on any missing input or mismatch.
    """
    if not signature or not secret or raw_body is None:
        return False
    expected = compute_signature(raw_body, secret)
    return hmac.compare_digest(expected, signature)
