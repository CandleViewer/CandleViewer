"""#3479: a `sub` entry whose `opts` holds a key the server does not know is refused alone (§5.2),
and the refusal names no client text: `field` is the key if it is an option name the server knows,
else `opts`, and the message is fixed (§5.1). Unit twin: `tests/unit/ws/test_sub_option_field.py`.

The harness bounds a `field` at 64 characters (§13 sets no `maxLength`, #572). `Client.recv` held an
`err` to it since #3370; a `sub` refusal travels in a `sub_ok` result, so the bound covers each
result's `error` and `warning` too, and the stub-frame tests below show that it bites."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.contract.ws._harness import Client, World, connect, validate_frame


@pytest.mark.parametrize(
    ("key", "field"),
    [
        pytest.param("Q" * 500, "opts", id="500-chars"),
        pytest.param("throttel_ms", "opts", id="typo"),
        pytest.param("params", "opts", id="params"),  # §13.5 declares it; no topic takes it (#658)
        pytest.param("depth", "depth", id="known-name-the-topic-lacks"),
        pytest.param("paused", "paused", id="a-ctl-key"),
    ],
)
def test_contract_a_sub_option_key_is_named_only_when_the_server_knows_it(
    key: str, field: str
) -> None:
    """§5.1 (#3479): `field` is the key if it is an option name, else `opts`; the message is fixed.
    The entry is refused alone: its neighbours are accepted and nothing is held for it."""
    entries = ["book.BTCUSDT.50", {"ch": "trades.BTCUSDT", "opts": {key: 1}}, "ticker.BTCUSDT"]
    with connect(World()) as c:
        results = c.sub(*entries, conform=False)["p"]["results"]  # `sub_ok` is validated on receipt
        assert [(r["ch"], r["ok"]) for r in results] == [
            ("book.BTCUSDT.50", True),
            ("trades.BTCUSDT", False),
            ("ticker.BTCUSDT", True),
        ]
        refused = results[1]
        assert refused["error"] == {
            "code": "invalid_options",
            "message": "Unknown option.",
            "field": field,
            "retryable": False,
        }
        assert len(refused["error"]["field"]) <= 64 and len(json.dumps(refused)) < 400
        assert field == key or key not in json.dumps(refused)
        again = c.sub("trades.BTCUSDT")["p"]["results"][0]
        assert again["ok"] is True  # the refused entry left nothing behind: no duplicate


class _Stub:
    """A socket that hands `Client.recv` one frame, as a `cv.v1.json` socket would."""

    accepted_subprotocol = "cv.v1.json"

    def __init__(self, frame: dict[str, Any]) -> None:
        self.frame = frame

    def receive_json(self) -> dict[str, Any]:
        return self.frame


def _sub_ok(key: str, kinds: list[str], field: str) -> dict[str, Any]:
    """A `sub_ok` of one result per kind: `plain` (accepted), `nofield` (a refusal or warning that
    names no field) or `field` (one that names `field`); `key` is `error` or `warning`."""
    shapes: dict[str, dict[str, Any]] = {
        "plain": {"ok": True},
        "nofield": {"ok": False, key: {"code": "forbidden", "message": "m"}},
        "field": {"ok": False, key: {"code": "invalid_options", "message": "m", "field": field}},
    }
    results = [{"ch": f"trades.S{i}", **shapes[kind]} for i, kind in enumerate(kinds)]
    return {"t": "sub_ok", "id": "s", "p": {"results": results}}


@pytest.mark.parametrize("key", ["error", "warning"])
@pytest.mark.parametrize("at", [0, 1, 2], ids=["first-result", "middle-result", "last-result"])
def test_contract_the_harness_bounds_the_field_of_every_sub_ok_result(key: str, at: int) -> None:
    """A stub `sub_ok` with 64 characters in one result's `field` is received; 65 fails, wherever
    that result is among others that name none. Both are valid §13 frames: the bound is ours."""
    others = ["plain", "nofield"]
    kinds = [*others[:at], "field", *others[at:]]
    at_bound = _sub_ok(key, kinds, "f" * 64)
    validate_frame(at_bound)
    assert Client(_Stub(at_bound)).recv() == at_bound
    over = _sub_ok(key, kinds, "f" * 65)
    validate_frame(over)
    with pytest.raises(AssertionError) as caught:
        Client(_Stub(over)).recv()
    assert "f" * 65 in str(caught.value)  # the bound's own failure, and it shows the frame
