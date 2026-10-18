"""`23-ws-protocol.md` §8.5 from the first `auth_ok`, both wires, flag off and on: a `pong` past 256
bytes closes `protocol_violation` (1002); past their budget, `pong`s count toward the rate."""

from __future__ import annotations

import uuid

import pytest

from candleviewer.ws.backpressure_config import BackpressureConfig
from tests.contract.ws._harness import World, connect

_FLAGS = pytest.mark.parametrize("flag", [None, BackpressureConfig()], ids=["flag-off", "flag-on"])
_MOST = 2**53 - 1  # no maximum in the schema: the largest integer a JS client keeps


@_FLAGS
def test_contract_an_oversized_pong_after_auth_ok_gets_bye_protocol_violation_1002(
    flag: BackpressureConfig | None,
) -> None:
    """A `pong` the §13 schemas accept (it is validated before it is sent), with `id`, `ch` and
    `rs` at their bounds and every heartbeat field, is over 256 bytes on either wire."""
    heartbeat = {"client_ms": _MOST, "server_ms": _MOST, "rtt_hint_ms": _MOST}
    pong = {"t": "pong", "id": "i" * 64, "ch": "a" + ".b" * 59, "rs": str(uuid.UUID(int=1))}
    with connect(World(backpressure=flag)) as c:
        c.send({**pong, "ts": _MOST, "p": heartbeat})
        c.send({"t": "ping", "id": "fence"})  # never answered: the close comes first
        bye, code = c.bye_then_close()
    assert (bye["p"]["reason"], code) == ("protocol_violation", 1002)


@_FLAGS
def test_contract_pongs_past_their_budget_count_toward_the_inbound_rate(
    flag: BackpressureConfig | None,
) -> None:
    """`hello` and `auth` are 2 of this second's 30 frames: past the 8 of the budget, 28 `pong`s
    are counted, the next one is refused, and the fence is the second refusal."""
    with connect(World(backpressure=flag)) as c:
        for _ in range(8 + 30 - 1):
            c.send({"t": "pong", "id": "s-hb-1"})
        c.send({"t": "ping", "id": "fence"})
        assert c.recv_err()["p"]["code"] == "client_rate_limited"
        bye, code = c.bye_then_close()
    assert (bye["p"]["reason"], code) == ("client_rate_limited", 4429)
