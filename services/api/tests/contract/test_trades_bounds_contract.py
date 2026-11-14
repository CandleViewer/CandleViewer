"""E22-X02 (#756) ticket case 2, the permanent contract half (model AC8, D16; SR-E22-02/04): the
`getTrades` bounds in `22-api-openapi.yaml` and the `trades.{symbol}` option ranges in
`23-ws-protocol.md` §6.1 equal `orderflow/limits.py`, so the contract, the REST validator and the
WS option validator cannot drift apart silently (the model's §7 test 2)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.orderflow import limits as L

_WS = Path(__file__).resolve().parents[4] / "docs/plan/23-ws-protocol.md"


def _get_trades_params() -> dict[str, dict[str, Any]]:
    spec: Any = load_openapi_spec()
    op = spec["paths"]["/market/trades"]["get"]
    out: dict[str, dict[str, Any]] = {}
    for p in op["parameters"]:
        if "$ref" in p:
            p = spec["components"]["parameters"][p["$ref"].rsplit("/", 1)[-1]]
        out[p["name"]] = p["schema"]
    return out


def test_get_trades_bounds_equal_the_limits_module() -> None:
    p = _get_trades_params()
    assert (p["limit"]["minimum"], p["limit"]["maximum"]) == (1, L.TRADES_MAX_LIMIT)
    window = p["cluster_window_ms"]
    assert (window["minimum"], window["maximum"]) == (0, L.CLUSTER_WINDOW_MS_MAX_REST)
    ticks = p["cluster_tolerance_ticks"]
    assert (ticks["minimum"], ticks["maximum"]) == (0, L.CLUSTER_TOLERANCE_TICKS_MAX)
    assert p["cursor"]["maxLength"] == 512


def test_trades_topic_option_ranges_equal_the_limits_module() -> None:
    doc = _WS.read_text(encoding="utf-8")
    window = re.search(r"`cluster_window_ms` is 0\u2013(\d+) on WS", doc)
    ticks = re.search(r"`cluster_tolerance_ticks` is 0\u2013(\d+) and defaults to 0", doc)
    assert window is not None and ticks is not None
    assert int(window.group(1)) == L.CLUSTER_WINDOW_MS_MAX_WS
    assert int(ticks.group(1)) == L.CLUSTER_TOLERANCE_TICKS_MAX
