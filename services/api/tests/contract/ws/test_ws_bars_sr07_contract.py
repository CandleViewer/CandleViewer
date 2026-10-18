"""#399 (E12-T06) D7, SR-E12-07 part 2: a connection's `bars.*` subscribe rate is SR-193's rebuild
budget (#2293; `23-ws-protocol.md` §6.1, §7.5, §16.2), on the bars conformance rig
(`test_ws_bars_contract._Rig`) through the real `/ws` router, under `cv.v1.json` and
`cv.v1.msgpack`. A start the budget refuses takes no lease, no series hold and no snapshot build,
whatever its options."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from candleviewer.bars.models import BarSpec
from candleviewer.bars.series_store import Hold, Latest
from tests.contract.test_market_bars_contract import _STORE
from tests.contract.ws import _harness as h
from tests.contract.ws.test_ws_bars_contract import CH, _Rig
from tests.contract.ws.test_ws_rebuild_budget import _until_pong

#: 160 `book` topics, four depths on each of 40 symbols, by symbol: their snapshots stay pending
#: (the rig serves `bars` only), so a start sends no `snap`.
_BOOKS = [f"book.S{i // 4:02d}USDT.{(1, 50, 200, 500)[i % 4]}" for i in range(160)]
#: (fake time, topics, `unsub` them after): 160, 320, then 399 starts, the last 79 on 20 symbols.
_ROUNDS = ((0.0, _BOOKS, True), (1.0, _BOOKS, True), (2.0, _BOOKS[:79], False))


def _refused(cause: str) -> float:
    labels = {"kind": "sub", "cause": cause}
    return REGISTRY.get_sample_value("cv_ws_rebuild_refused_total", labels) or 0.0


def _spy(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each series hold the rig's store gives (`ensure`) and each `bars` snapshot built from it
    (`latest`), in order."""
    calls: list[str] = []
    ensure, latest = rig.store.ensure, rig.store.latest

    async def hold(symbol: str, spec: BarSpec) -> Hold:
        calls.append("hold")
        return await ensure(symbol, spec)

    def build(symbol: str, spec_hash: str, history: int) -> Latest | None:
        calls.append("build")
        return latest(symbol, spec_hash, history)

    monkeypatch.setattr(rig.store, "ensure", hold)
    monkeypatch.setattr(rig.store, "latest", build)
    return calls


def _start(c: h.Client, topics: list[str], *, unsub: bool) -> None:
    """`sub` `topics`, 50 to a frame (§13.5), each one started; then `unsub` them if asked."""
    for i in range(0, len(topics), 50):
        assert all(r["ok"] for r in c.sub(*topics[i : i + 50])["p"]["results"])
    if unsub:
        for i in range(0, len(topics), 50):
            c.send({"t": "unsub", "id": f"u{i}", "p": {"topics": topics[i : i + 50]}})
            c.next_of("unsub_ok")


def test_contract_bars_a_sixth_resubscribe_within_60_s_is_refused_whatever_its_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7.5: `unsub` and `sub` of one `bars` topic every 2 s, `history` 1 000 and 0 in turn. The
    first start and five re-subscribes each take a lease, a hold and a build; the sixth
    re-subscribe, with options none of them had, is refused `resync_rate_limited` (the topic's 5
    a minute: its key has no options), takes none of them and gets no `snap`. Once the first
    re-subscribe is a window old, the topic starts again."""
    rig = _Rig({"1m": _STORE["1m"][:3]})
    calls, before = _spy(rig, monkeypatch), _refused("topic")
    with h.connect(rig.w) as c:
        for n in range(6):
            rig.w.clock.now = 2.0 * n
            if n:
                c.send({"t": "unsub", "id": f"u{n}", "p": {"topics": [CH]}})
            history = (1000, 0)[n % 2]
            (ok,) = c.sub({"ch": CH, "opts": {"history": history}})["p"]["results"]
            assert ok["ok"] and ok["effective"]["history"] == history
            assert c.next_of("snap")["meta"]["reason"] == "initial"
        rig.w.clock.now = 12.0
        c.send({"t": "unsub", "id": "u6", "p": {"topics": [CH]}})
        new = {"history": 1, "include_delta": True}  # options none of the six had
        (refused,) = c.sub({"ch": CH, "opts": new})["p"]["results"]
        assert _until_pong(c) == []  # no `snap` follows it
        took = (len(rig.leases.registered), list(calls), _refused("topic"))
        rig.w.advance(c, 62.0)  # the re-subscribe of t = 2 is a full window old
        assert c.sub({"ch": CH, "opts": {"history": 1}})["p"]["results"][0]["ok"]
        assert c.next_of("snap")["meta"]["reason"] == "initial"
    err = refused["error"]
    assert (refused["ok"], err["code"], err["retryable"]) == (False, "resync_rate_limited", True)
    assert err["message"] == "Rebuild budget spent (5 a minute per topic); not subscribed."
    assert took == (6, ["hold", "build"] * 6, before + 1)
    assert (len(rig.leases.registered), calls) == (7, ["hold", "build"] * 7)


def test_contract_bars_a_start_past_the_connection_budget_is_refused_and_takes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7.5, §16.2: every start draws on the connection's 400 a minute, a `bars.*` one too. After
    399 `book` starts, a `bars` start is the 400th; a start of another `bars` topic is refused
    `resync_rate_limited` for the connection and takes no lease, hold or build. Once those starts
    are a window old, it starts."""
    rig, five = _Rig({}), "bars.BTCUSDT.time.5"
    calls, before = _spy(rig, monkeypatch), _refused("connection")
    with h.connect(rig.w) as c:
        for t, topics, unsub in _ROUNDS:
            rig.w.clock.now = t  # one round a second: under 30 frames a second (§8.5)
            _start(c, topics, unsub=unsub)
        assert c.sub(CH)["p"]["results"][0]["ok"]  # the 400th, on a 21st symbol
        c.next_of("snap")
        (refused,) = c.sub(five)["p"]["results"]
        assert _until_pong(c) == []
        took = (len(rig.leases.registered), list(calls), _refused("connection"))
        rig.w.advance(c, 63.0)
        assert c.sub(five)["p"]["results"][0]["ok"]
        c.next_of("snap")
    err = refused["error"]
    assert (refused["ok"], err["code"]) == (False, "resync_rate_limited")
    assert err["message"] == "Rebuild budget spent (400 a minute per connection); not subscribed."
    assert took == (1, ["hold", "build"], before + 1)
    assert (len(rig.leases.registered), calls) == (2, ["hold", "build"] * 2)
