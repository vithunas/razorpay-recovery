import base64
import json
from pathlib import Path

import pytest

from tests.fakes import FakeGateway, InMemoryDB

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def mem_db(monkeypatch) -> InMemoryDB:
    """Route db.* through one in-memory store. Every app module accesses these
    as attributes on the `db` module object, so patching here covers all."""
    store = InMemoryDB()
    import app.db as _db
    monkeypatch.setattr(_db, "insert", store.insert)
    monkeypatch.setattr(_db, "update", store.update)
    monkeypatch.setattr(_db, "select", store.select)
    monkeypatch.setattr(_db, "health", store.health)
    return store


@pytest.fixture
def fake_gateway(monkeypatch) -> FakeGateway:
    gw = FakeGateway()
    import app.razorpay_client as rc
    monkeypatch.setattr(rc, "get_gateway", lambda: gw)
    return gw


@pytest.fixture
def razorpay_captured_webhook() -> dict:
    """A real Razorpay Test Mode webhook (payment.captured), signed with 'Vithu@1106'."""
    fx = json.loads((FIXTURES / "razorpay_webhook_payment_captured.json").read_text())
    fx["body"] = base64.b64decode(fx["body_b64"])
    return fx
