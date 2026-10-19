"""E17-R-10 (#415): a client's §13 `epochMs` fields, `hello.clock_ms` and `ping.client_ms`, count
only as an int, not a bool, from 0 to 2**53 - 1 (`MAX_EPOCH_MS`), on both subprotocols. Any other
value is ignored as if absent: the `welcome` has no `clock_skew_ms`, the `pong` no `rtt_hint_ms`,
nothing is observed, and the socket goes on, never closed `internal_error`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest

from candleviewer.ws.lifecycle import MAX_EPOCH_MS, clamp_ms, client_epoch_ms
from candleviewer.ws.metrics import cv_ws_clock_skew_ms
from tests.unit.ws.test_lifecycle_socket import BASE_MS, JSON, MSGPACK, _hello, _recv, _send, _World

REPO: Final = Path(__file__).resolve().parents[5]
#: Out of range, or not an int, per subprotocol: a JSON number may be any integer, a msgpack one
#: what fits in 64 bits.
_NOT_EPOCH_MS: Final[dict[str, list[Any]]] = {
    "json": [
        -1,
        MAX_EPOCH_MS + 1,
        2**63 + BASE_MS,
        2**64 - 1,
        10**306,
        10**400,
        -(10**4300 - 1),
        True,
        float(BASE_MS),
    ],
    "msgpack": [-1, MAX_EPOCH_MS + 1, 2**63, 2**64 - 1, -(2**63), True, float(BASE_MS)],
}
_SUBPROTOCOLS: Final = {"json": JSON, "msgpack": MSGPACK}
_IGNORED: Final = [
    pytest.param(_SUBPROTOCOLS[name], value, id=f"{name}-{i}")
    for name, values in _NOT_EPOCH_MS.items()
    for i, value in enumerate(values)
]
_EDGES: Final = [
    pytest.param(_SUBPROTOCOLS[name], value, id=f"{name}-{value}")
    for name in _SUBPROTOCOLS
    for value in (0, MAX_EPOCH_MS)
]


def _skew_sum() -> float:
    """`cv_ws_clock_skew_ms`'s running sum (the process-wide histogram)."""
    (family,) = cv_ws_clock_skew_ms.collect()
    return next(s.value for s in family.samples if s.name.endswith("_sum"))


def _ping(ws: Any, fid: str, client_ms: Any) -> dict[str, Any]:
    _send(ws, {"t": "ping", "id": fid, "p": {"client_ms": client_ms}})
    return _recv(ws)


@pytest.mark.parametrize(("subprotocol", "value"), _IGNORED)
def test_an_epoch_ms_out_of_range_is_ignored_and_the_socket_goes_on(
    subprotocol: list[str], value: Any
) -> None:
    before = _skew_sum()
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=subprotocol) as ws:
        welcome = _hello(ws, clock_ms=value)
        assert welcome["t"] == "welcome" and "clock_skew_ms" not in welcome["p"]
        pong = _ping(ws, "p1", value)
        assert (pong["t"], pong["id"], "rtt_hint_ms" in pong["p"]) == ("pong", "p1", False)
        assert _ping(ws, "p2", BASE_MS)["p"]["rtt_hint_ms"] == 0  # the socket is still served
    assert _skew_sum() == before


@pytest.mark.parametrize(("subprotocol", "value"), _EDGES)
def test_an_epoch_ms_at_either_end_of_the_range_is_read(subprotocol: list[str], value: int) -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=subprotocol) as ws:
        assert _hello(ws, clock_ms=value)["p"]["clock_skew_ms"] == BASE_MS - value
        assert _ping(ws, "p1", value)["p"]["rtt_hint_ms"] == max(0, BASE_MS - value)


@pytest.mark.parametrize(
    ("value", "read"),
    [
        *[(0, 0), (MAX_EPOCH_MS, MAX_EPOCH_MS), (-1, None), (MAX_EPOCH_MS + 1, None)],
        *[(True, None), (False, None), (1.0, None), ("1", None), (None, None)],
    ],
)
def test_client_epoch_ms_reads_an_int_in_range_and_nothing_else(value: Any, read: Any) -> None:
    assert client_epoch_ms(value) == read


@pytest.mark.parametrize(
    ("value", "held"),
    [(10**20, MAX_EPOCH_MS), (-(10**20), -MAX_EPOCH_MS), (-5, -5), (MAX_EPOCH_MS, MAX_EPOCH_MS)],
)
def test_clamp_ms_holds_a_difference_to_the_epoch_ms_range(value: int, held: int) -> None:
    assert clamp_ms(value) == held


def test_the_contract_states_the_maximum_the_gateway_reads() -> None:
    """23 §13 `epochMs` (bundled in `docs/plan/ws-schema.json`) carries the same `maximum`."""
    bundle = json.loads((REPO / "docs/plan/ws-schema.json").read_text(encoding="utf-8"))
    common = bundle["schemas"]["cv://ws/v1/common.schema.json"]["$defs"]["epochMs"]
    assert (common["minimum"], common["maximum"]) == (0, MAX_EPOCH_MS)
