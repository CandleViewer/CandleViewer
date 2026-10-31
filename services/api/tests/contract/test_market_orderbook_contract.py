"""E21-T03 (#606) BQ-7: `GET /market/orderbook` is unchanged; its `u` / `seq` and resync
behaviour are pinned here, against the committed OpenAPI and the provider (no network)."""

from __future__ import annotations

from typing import Any

from candleviewer.api._generated.openapi_models import OrderbookSnapshot
from candleviewer.api.contract_conformance import load_openapi_spec
from tests.unit.api.test_orderbook_api import Reader, _client

_SPEC: dict[str, Any] = load_openapi_spec()
_OP: dict[str, Any] = _SPEC["paths"]["/market/orderbook"]["get"]


def test_orderbook_snapshot_requires_u_and_seq() -> None:
    schema = _SPEC["components"]["schemas"]["OrderbookSnapshot"]
    assert {"u", "seq"} <= set(schema["required"]) <= set(schema["properties"])


def test_get_orderbook_declares_the_resync_503() -> None:
    assert _OP["operationId"] == "getOrderbookSnapshot"
    assert _OP["responses"]["503"] == {"$ref": "#/components/responses/ServiceUnavailable"}
    assert "at" not in {p.get("name") for p in _OP.get("parameters", [])}  # BQ-7: no history read


def test_resync_response_carries_update_id_and_seq() -> None:
    """503 while resynchronising, then the rebuilt book's `u` and `seq` (the snapshot it was
    rebuilt from) on the next read, never the pre-resync values."""
    reader = Reader(live=False)
    client = _client(reader=reader)
    resyncing = client.get("/market/orderbook", params={"symbol": "BTCUSDT"})
    assert resyncing.status_code == 503 and "u" not in resyncing.json()
    reader.live = True
    body = client.get("/market/orderbook", params={"symbol": "BTCUSDT"}).json()
    OrderbookSnapshot.model_validate(body)
    assert (body["u"], body["seq"]) == (7, 7)
