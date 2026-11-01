"""E12-X02 authorization (#452 AC4; X01 AC-11; BR-21): `/market/bars` and `/market/klines` refuse
a caller with no session (401) and one without `marketdata:read` (403) before any storage call,
and a `bars.*` subscription that loses `marketdata:read` mid-stream is revoked in order, audited,
and gets no frame after.

Cited, not repeated: E12-Q04's RBAC matrix (`tests/contract/test_market_e12_q04_contract.py`) and
the refused-subscribe case (`tests/contract/ws/test_ws_bars_contract.py`).
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from tests.contract._market_world import KLINES_NOW_US, NO_SESSION, NOW, OTHER, T0
from tests.contract.test_market_bars_contract import _SERIES
from tests.contract.ws import _harness as h
from tests.contract.ws.test_ws_bars_contract import _MINUTE, CH, _closed, _Rig, _up
from tests.security.bars.conftest import Stores
from tests.security.bars.test_caps_and_cost import assert_problem, bars, klines
from tests.unit.ws._seq_support import USER

_QUERIES = {
    "getBars": bars("tick", "1", T0, NOW),  # a request that is also hostile: authz comes first
    "getKlines": klines(KLINES_NOW_US - 86_400_000_000, KLINES_NOW_US),
}


def check_unauthenticated(stores: Stores, op: str) -> None:
    assert_problem(stores.get(op, _QUERIES[op], NO_SESSION), 401, "unauthenticated")
    assert stores.total() == 0


def check_forbidden(stores: Stores, op: str) -> None:
    resp = stores.get(op, _QUERIES[op], OTHER)
    assert_problem(resp, 403, "forbidden")
    assert "marketdata:read" in resp.json()["detail"]
    assert stores.total() == 0


@pytest.mark.parametrize("op", ["getBars", "getKlines"])
def test_authz_no_session_is_401_before_any_storage_call(stores: Stores, op: str) -> None:
    check_unauthenticated(stores, op)


@pytest.mark.parametrize("op", ["getBars", "getKlines"])
def test_authz_without_marketdata_read_is_403_before_any_storage_call(
    stores: Stores, op: str
) -> None:
    check_forbidden(stores, op)


class _Audit:
    """The WS audit sink (`ws.permissions.AuditSink`): every row, in order."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.rows.append({"action": action, **fields})


def test_authz_revoked_bars_subscription_is_announced_audited_and_silent(wire: str) -> None:
    """23-ws §9.5: `permission_change` first, then `revoked{reason: permission_revoked, sub_id}`;
    no `snap` or `d` after it, though the series keeps publishing; one `ws.subscription.revoked`
    row naming the subscription, the socket and the session; the series lease released."""
    rig, spec, bar = _Rig({}), _SERIES[_MINUTE], _closed(*_MINUTE)[0]
    audit = _Audit()
    rig.w.registry.services.audit = audit
    with h.connect(rig.w) as c:
        c.sub(CH)
        c.next_of("snap")
        rig.emit(spec, _up("open", bar))
        c.next_of("d")
        rig.w.perms = h.ALL_PERMS - {Permission.MARKETDATA_READ}
        rig.w.call(rig.w.registry.roles_changed, USER)
        c.recv_permission_change()
        revoked = c.recv()
        assert revoked["t"] == "revoked", revoked
        assert (revoked["ch"], revoked["p"]["reason"]) == (CH, "permission_revoked")
        rig.emit(spec, _up("update", bar))
        c.send({"t": "ping", "id": "p"})
        after = []
        while (frame := c.recv())["t"] != "pong":
            after.append(frame["t"])
        assert [t for t in after if t in {"snap", "d"}] == []
    rows = [r for r in audit.rows if r["action"] == "ws.subscription.revoked"]
    assert len(rows) == 1, audit.rows
    (row,) = rows
    assert (row["object_id"], row["reason"]) == (CH, "permission_revoked")
    assert row["after_state"]["sub_id"] == revoked["p"]["sub_id"]
    assert row["after_state"]["connection_id"]
    assert row["session_id"] == rig.w.session
    assert len(rig.leases.released) == len(rig.leases.registered) == 1
