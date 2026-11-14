"""E22-X02 (#756) ticket case 8 (model AC12, AC13; D9, D10; SR-E22-15): two users replay the
recorded `publicTrade` tape on `trades.BTCUSDT` with different options and read it over
`GET /market/trades`. Each ack and `effective` holds the caller's options only; no frame, REST
body, log line or big-trade metric label carries a user, account or key identifier. The
`tape.*` analytics events do not exist on `main` (catalogue AC12). No network."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import pytest
from prometheus_client import REGISTRY

from tests._bigtrades import World, recorded_batches
from tests.security.bigtrade._app import Principal, client, recorded_tape

U1, U2 = uuid.UUID(int=0x1001), uuid.UUID(int=0x1002)
_IDENTITY_KEYS = {"user", "user_id", "account", "account_id", "uid", "api_key", "key_id"}
_FAMILIES = ("cv_ws_trades", "cv_ws_tape", "bigtrade")


def _identities() -> list[str]:
    return [str(U1), str(U2), U1.hex, U2.hex, "u1", "u2"]


def _keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


def test_ac13_each_user_sees_only_their_own_options() -> None:
    w = World()
    a, b = w.conn(user=U1), w.conn(user=U2)
    ack_a, _ = w.sub(a, {"min_size": "0.002", "encoding": "structured"})
    ack_b, _ = w.sub(b, {"cluster_window_ms": 250, "encoding": "structured"})
    eff_a, eff_b = ack_a["effective"], ack_b["effective"]  # the threshold is the symbol's
    assert (eff_a["min_size"], eff_a["cluster_window_ms"]) == ("0.002", 0)
    assert "min_size" not in eff_b and eff_b["cluster_window_ms"] == 250
    assert eff_a["big_trade_threshold"] == eff_b["big_trade_threshold"]
    assert "0.002" not in json.dumps(ack_b) and "250" not in json.dumps(ack_a)


def test_ac12_no_identifier_in_frames_bodies_logs_or_metric_labels(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    batches = recorded_batches()
    w = World()
    a, b = w.conn(user=U1), w.conn(user=U2)
    w.sub(a, {"encoding": "structured"})
    w.sub(b, {"min_size": "0.002", "cluster_window_ms": 250, "encoding": "structured"})
    for batch in batches[:50]:
        w.now_us = batch[-1].ts_event
        w.window(batch)
    w.now_us = batches[49][-1].ts_event + 10_000_000  # every cluster closes
    w.window()
    frames = a.take() + b.take()
    assert any(f["t"] == "d" for f in frames)
    tape = recorded_tape()
    bodies = [
        client(tape, Principal(user)).get("/market/trades", params=params).json()
        for user in ("u1", "u2")
        for params in ({"symbol": "BTCUSDT"}, {"symbol": "BTCUSDT", "limit": 0})
    ]
    text = json.dumps(frames) + json.dumps(bodies) + caplog.text
    assert not [i for i in _identities() if i in text]
    assert not _keys(frames) & _IDENTITY_KEYS and not _keys(bodies) & _IDENTITY_KEYS
    families = [f for f in REGISTRY.collect() if f.name.startswith(_FAMILIES)]
    assert families  # the big-trade and tape counters are registered, so the scan is not empty
    for family in families:
        for sample in family.samples:
            assert not set(sample.labels) & _IDENTITY_KEYS, family.name
            assert not [i for i in _identities() if i in sample.labels.values()], family.name
