"""Contract (E27-T04 W4b, #837): the `wallet` frames the accounts module serves validate against
23-ws-protocol.md §15.4 as `packages/protocol` bundles it, as their provider (C-6.2): a snapshot,
a health-only delta, a balance delta and a turn to stale, each in its envelope."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from tests.contract.ws._harness import REPO
from tests.unit.accounts._fakes import ACC, ACC_B
from tests.unit.accounts._wallet_ws import WalletWorld, owner

_PROTOCOL = REPO / "packages" / "protocol" / "ws-schemas.json"
_WS: dict[str, Any] = json.loads(_PROTOCOL.read_text(encoding="utf-8"))["schemas"]
_REGISTRY: Registry[Any] = Registry().with_resources(
    (sid, Resource.from_contents(body)) for sid, body in _WS.items()
)
_ACC_C = UUID(int=3)


def _violations(schema_id: str, doc: Any) -> list[str]:
    validator = Draft202012Validator(_WS[schema_id], registry=_REGISTRY)
    return [error.message for error in validator.iter_errors(doc)]


def test_the_served_wallet_frames_validate_against_the_protocol_package_schemas() -> None:
    world = WalletWorld()
    world.monitor.track(_ACC_C)
    world.wallets.track(_ACC_C)  # monitored, never connected: no heartbeat age, no balance
    conn = world.conn(owner())
    conn.sub(ACC, ACC_B, _ACC_C)
    world.monitor.ws_dropped(ACC_B)
    world.monitor.rest_ok(ACC_B)
    world.topic.health_changed(ACC_B)
    world.topic.balance_refreshed(ACC)
    world.clock.advance(11)
    world.topic.stale_check()
    frames = conn.frames
    assert [(frame["t"], sorted(frame["p"])) for frame in frames] == [
        ("snap", ["balances", "health"]),
        ("d", ["balances", "health"]),
        ("d", ["balances"]),
        ("d", ["balances"]),
    ]
    for frame in frames:
        assert _violations("cv://ws/v1/envelope.schema.json", frame) == []
        assert _violations("cv://ws/v1/wallet.schema.json", frame["p"]) == []
