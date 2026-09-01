import base64
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def razorpay_captured_webhook() -> dict:
    """A real Razorpay Test Mode webhook (payment.captured), signed with 'Vithu@1106'."""
    fx = json.loads((FIXTURES / "razorpay_webhook_payment_captured.json").read_text())
    fx["body"] = base64.b64decode(fx["body_b64"])
    return fx
