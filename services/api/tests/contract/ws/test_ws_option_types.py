"""#3469: a `ctl` or a `sub` entry whose option value has the wrong JSON type is refused with
`invalid_options` naming the option (§5.1, §5.4, §10.2). It used to raise inside the option check,
and the gateway answers a raise by closing the connection `internal_error` (1011).

The frames that carry the bad value are sent unvalidated: §13.5 and §13.6 do not allow them, which
is the point. Every other frame sent here is validated before it goes out, and the harness validates
every frame the server sends on receipt. The module runs under both subprotocols (`conftest.py`),
each with the backpressure flag off and on: with it on, the replies are queued on the §8.4 lanes.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.ws.backpressure_config import BackpressureConfig
from tests.contract.ws._harness import World, connect, json_only

HEATMAP = "heatmap.BTCUSDT"
_FLAGS = pytest.mark.parametrize("flag", [None, BackpressureConfig()], ids=["flag-off", "flag-on"])


@_FLAGS
@pytest.mark.parametrize(("key", "value"), [("depth", []), ("time_bucket_ms", {})])
def test_contract_a_ctl_option_of_the_wrong_type_is_refused_and_the_socket_is_served(
    key: str, value: Any, flag: BackpressureConfig | None
) -> None:
    with connect(World(backpressure=flag)) as c:
        c.sub(HEATMAP)
        c.send({"t": "ctl", "id": "k", "ch": HEATMAP, "p": {key: value}}, conform=False)
        err = c.next_of("err")  # frames read on the way are validated too
        assert (err["id"], err["ch"]) == ("k", HEATMAP)
        assert (err["p"]["code"], err["p"]["field"], err["p"]["close"]) == (
            ("invalid_options", key, False)
        )
        assert err["p"]["message"] == f"Option '{key}' is out of range."
        c.send({"t": "ping", "id": "p"})
        assert c.next_of("pong")["id"] == "p"  # no `bye`, no close: the connection is open
        c.send({"t": "ctl", "id": "k2", "ch": HEATMAP, "p": {"throttle_ms": 500}})
        ok = c.next_of("ctl_ok")  # and the subscription is still there, as it was
        assert (ok["id"], ok["p"]["effective"]["throttle_ms"]) == ("k2", 500)
        assert "resnapshot" not in ok["p"]


@json_only
@_FLAGS
def test_contract_a_ctl_option_of_nan_on_the_json_wire_is_refused_and_the_socket_is_served(
    flag: BackpressureConfig | None,
) -> None:
    """`NaN` is no JSON, but the JSON path decodes it to a float (`json.loads`); MessagePack refuses
    it before any option is read, so only this wire carries it to the check."""
    with connect(World(backpressure=flag)) as c:
        c.sub(HEATMAP)
        c.send_text('{"t":"ctl","id":"k","ch":"heatmap.BTCUSDT","p":{"depth":NaN}}')
        err = c.next_of("err")
        assert (err["id"], err["ch"]) == ("k", HEATMAP)
        assert (err["p"]["code"], err["p"]["field"], err["p"]["close"]) == (
            ("invalid_options", "depth", False)
        )
        c.send({"t": "ping", "id": "p"})
        assert c.next_of("pong")["id"] == "p"  # no `bye`, no close: the connection is open


@_FLAGS
@pytest.mark.parametrize(
    ("bad", "key"),
    [
        ({"ch": "trades.BTCUSDT", "opts": {"encoding": {}}}, "encoding"),
        ({"ch": HEATMAP, "opts": {"time_bucket_ms": []}}, "time_bucket_ms"),
    ],
)
def test_contract_a_sub_entry_with_an_option_of_the_wrong_type_is_refused_alone(
    bad: dict[str, Any], key: str, flag: BackpressureConfig | None
) -> None:
    with connect(World(backpressure=flag)) as c:
        results = c.sub("book.BTCUSDT.50", bad, "ticker.BTCUSDT", conform=False)["p"]["results"]
        assert [(r["ch"], r["ok"]) for r in results] == [
            ("book.BTCUSDT.50", True),
            (bad["ch"], False),
            ("ticker.BTCUSDT", True),
        ]
        error = results[1]["error"]
        assert (error["code"], error["field"], error["retryable"]) == (
            ("invalid_options", key, False)
        )
        assert error["message"] == f"Option '{key}' is out of range."
        # The other two entries are served: the first two `snap`s are theirs. They are read before
        # the `ping`: with the flag on, a `pong` may overtake a `snap` (§8.4 Lanes).
        snapped = {c.next_of("snap")["ch"] for _ in range(2)}
        assert snapped == {"book.BTCUSDT.50", "ticker.BTCUSDT"}
        c.send({"t": "ping", "id": "p"})
        assert c.next_of("pong")["id"] == "p"  # the connection is open
        assert c.sub(bad["ch"])["p"]["results"][0]["ok"]  # nothing was held: no duplicate
