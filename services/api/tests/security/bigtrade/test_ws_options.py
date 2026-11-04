"""E22-X02 (#756) ticket cases 2, 3 and 6 on `trades.{symbol}` (model AC8, AC4, AC16; D15, D16,
D26; SR-E22-03/04): out-of-range cluster options and a `min_size` that is negative, not finite or
below the floor are refused per topic with `invalid_options` naming the field, with no
subscription created and nothing held, while a live subscription on the same symbol keeps
receiving the recorded tape; a session without `marketdata:read` cannot subscribe at all.
Real `ConnectionAuthz`, `SequencingHub` and `TradesTopic` (`tests/_bigtrades.World`), recorded
`publicTrade` batches, fake clocks; no network."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws.permissions import ConnectionAuthz
from tests._bigtrades import CH, World, recorded_batches
from tests.unit.ws._seq_support import PERMS


def _trades(frames: list[dict[str, Any]]) -> list[str]:
    return [t["id"] for f in frames if f["t"] == "d" for t in f["p"]["trades"]]


@pytest.mark.parametrize(
    ("opts", "field"),
    [
        ({"cluster_window_ms": -1}, "cluster_window_ms"),
        ({"cluster_window_ms": 2.5}, "cluster_window_ms"),
        ({"cluster_window_ms": "2000"}, "cluster_window_ms"),
        ({"cluster_tolerance_ticks": 999}, "cluster_tolerance_ticks"),
        ({"cluster_tolerance_ticks": -1}, "cluster_tolerance_ticks"),
        ({"min_size": "-1"}, "min_size"),
        ({"min_size": "NaN"}, "min_size"),
        ({"min_size": "1e-30"}, "min_size"),
    ],
)
def test_ac4_ac8_a_refused_option_creates_nothing_and_a_live_subscription_is_unaffected(
    opts: dict[str, Any], field: str
) -> None:
    batches = recorded_batches()
    w = World()
    live = w.conn()
    _, kept = w.sub(live, {"encoding": "structured"})
    assert kept is not None
    live.take()
    hostile = w.conn(user=uuid.UUID(int=0x200))
    result, sub = w.sub(hostile, opts)
    assert sub is None and result["ok"] is False
    assert (result["error"]["code"], result["error"]["field"]) == ("invalid_options", field)
    assert hostile.authz.by_id == {}  # no subscription, nothing held, nothing clamped
    for batch in batches[:20]:  # the recorded tape keeps reaching the live subscription
        w.now_us = batch[-1].ts_event
        w.window(batch)
    assert _trades(live.take()) == [e.trade_id for batch in batches[:20] for e in batch]


def test_ac16_a_session_without_marketdata_read_cannot_subscribe_to_trades() -> None:
    w = World()
    perms = PERMS - {Permission.MARKETDATA_READ}
    authz = ConnectionAuthz(
        PrincipalSnapshot(uuid.UUID(int=0x300), frozenset({"viewer"}), perms, ()),
        w.services,
        clock=w.clock,
    )
    result, sub = authz.admit({"ch": CH, "opts": {}})
    assert sub is None and result["ok"] is False
    assert result["error"]["code"] == "forbidden"
    assert authz.by_id == {} and w.topic._symbols == {}  # no lease, no tape demand
