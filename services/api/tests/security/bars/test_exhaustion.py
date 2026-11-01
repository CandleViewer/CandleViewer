"""E12-X02 resource exhaustion (#452; X01 AC-04, AC-05, BR-31, BR-36): what one caller can make the
bars read path spend, measured in storage reads, rebuilds scheduled and series held.

- Stampede (BR-36): 50 identical requests in flight at once each make their own bar read: no
  single-flight on the REST routes (#452 findings row F3, a strict xfail on `NotCoalesced`). The
  sequential half, 60 maximal pages meeting no 429, is `test_caps_and_cost`'s F3 case.
- Rebuild flap (AC-05, BR-31): 50 requests flapping spec and window over stale rows schedule one
  rebuild per series, whatever their order and concurrency, and every request is still served.
  The registry's bucket, TTL and global caps are pinned by `tests/unit/bars/
  test_bars_persistence.py`; the WS rebuild budget (SR-193, K = 4 per user) by `tests/contract/ws/
  test_ws_rebuild_budget.py`. The per-user rebuild limits of ADR-0033 Decision 2 are NOT RUN
  (`test_rebuild_blocked.py`, #535).
- Spec explosion (AC-04): a ninth distinct `bars.*` series on one user's socket is refused
  `subscription_limit` through the real `/ws` router and the real `SpecLeases`, and holds nothing.
  The per-symbol and process-wide caps, the race and the metric: `tests/unit/bars/
  test_builder_set.py`, `test_builder_set_security.py`.

A slow `bars.*` consumer beside a healthy one (AC-06, BR-32) is X01's E12-Q05/Q06 row and is cited,
not rerun: the share's shedding and re-snapshot (`tests/unit/ws/test_bars_share.py`) and the
transport's isolation (`tests/security/ws/test_flood_isolation.py`).

In process, no socket, recorded data only (C-13.5). Concurrency is on the event loop: a gated store
call waits on an `asyncio.Event`, released once every request has reached it (no sleep).
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Final

import httpx
import pytest

from candleviewer.bars import reader, rows
from candleviewer.bars.leases import DEFAULT_CAPS, SpecCaps, SpecLeases
from candleviewer.bars.models import BarSpec
from candleviewer.bars.spec import from_wire
from tests.contract import _market_world as mw
from tests.contract._market_world import NOW, READER, T0, operation
from tests.contract.test_market_bars_contract import _iso
from tests.security.bars.conftest import BAR_READ, Stores

N: Final = 50
#: Loop turns a gate waits for every request to reach it before it opens anyway.
_TURNS: Final = 10_000
F3: Final = "#452 findings row F3: no single-flight on identical REST bar reads (BR-36)"


class NotCoalesced(AssertionError):
    """Identical concurrent bar reads each reached the store."""


def _query(param: str = "1", **over: object) -> dict[str, str]:
    q = {"symbol": "BTCUSDT", "bar_type": "time", "param": param, "limit": "5000",
         "from": _iso(T0), "to": _iso(NOW)}  # fmt: skip
    return {**q, **{k: str(v) for k, v in over.items()}}


async def _gather(stores: Stores, queries: list[dict[str, str]]) -> list[httpx.Response]:
    """`queries` in flight at once through one in-process client."""
    path = operation("getBars")[0]
    async with stores.asgi() as client:
        calls = (client.get(path, params=q, headers=dict(READER)) for q in queries)
        return list(await asyncio.gather(*calls))


@pytest.mark.xfail(strict=True, raises=NotCoalesced, reason=F3)
async def test_exhaustion_identical_concurrent_reads_are_coalesced(stores: Stores) -> None:
    """BR-36: 50 identical maximal requests in flight at once should share one bar read. Today
    each makes its own (measured: 50 of 50), so a caller multiplies the store's work by the
    requests it keeps in flight; on QuestDB they queue on the one `bars` pgwire lock."""
    arrived, gate = Counter[str](), asyncio.Event()

    async def held() -> list[dict[str, object]]:
        arrived["n"] += 1
        await gate.wait()
        return []

    stores.faults[BAR_READ] = held
    flight = asyncio.ensure_future(_gather(stores, [_query()] * N))
    for _ in range(_TURNS):  # every request that will read reaches the gate first
        if arrived["n"] == N:
            break
        await asyncio.sleep(0)
    gate.set()
    responses = await flight
    assert [r.status_code for r in responses] == [200] * N
    if (reads := stores.calls[BAR_READ]) > 1:
        raise NotCoalesced(
            f"{N} identical concurrent requests made {reads} bar reads ({arrived['n']} in flight)"
        )


class RebuildsMultiplied(AssertionError):
    """The flap scheduled other than one rebuild per series."""


class SeriesCapMissed(AssertionError):
    """The ninth distinct series of one user was taken."""


async def check_rebuild_flap(stores: Stores, monkeypatch: pytest.MonkeyPatch) -> None:
    """The defended outcome: every stored time row is stale (the builder's version is one ahead
    of the rows'), and 50 requests flapping between two specs and 25 windows each, all in flight
    at once, are each served the stale rows and schedule exactly one rebuild per series."""
    mw.stored_rows()  # the rows are built at the current version first, then the version moves
    monkeypatch.setitem(rows.BUILD_VERSIONS, "time", rows.BUILD_VERSIONS["time"] + 1)
    scheduled: list[tuple[str, str]] = []

    async def schedule(symbol: str, spec_hash: str, lo: int, hi: int) -> None:
        await asyncio.sleep(0)  # in flight across a loop turn: the single-flight is exercised
        scheduled.append((symbol, spec_hash))

    monkeypatch.setattr(mw, "_no_rebuild", schedule)  # read when the world is built, below
    before = reader.bars_rebuild_scheduled_total._value.get()
    flap = [_query(param, **{"from": _iso(T0 + k * 60_000_000)})
            for k in range(N // 2) for param in ("1", "5")]  # fmt: skip
    responses = await _gather(stores, flap)
    assert [r.status_code for r in responses] == [200] * N
    assert all(r.json()["bars"] for r in responses)  # stale rows are served, never refused
    assert stores.calls[BAR_READ] == N  # the flap is not refused: each request reads
    hashes = {from_wire("time", p).spec_hash for p in ("1", "5")}
    if sorted(scheduled) != sorted(("BTCUSDT", h) for h in hashes):
        raise RebuildsMultiplied(f"{len(scheduled)} rebuilds for {len(hashes)} series")
    assert reader.bars_rebuild_scheduled_total._value.get() == before + len(hashes)


async def test_exhaustion_rebuild_flap_schedules_one_rebuild_per_series(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X01 AC-05 / BR-31 over `/market/bars`, through the reader's `RebuildRegistry`."""
    await check_rebuild_flap(stores, monkeypatch)


async def test_exhaustion_control_without_single_flight_the_flap_multiplies_rebuilds(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: a registry that schedules on every stale read lets each request start
    its own rebuild."""

    async def every(self: reader.RebuildRegistry, symbol: str, h: str, lo: int, hi: int) -> bool:
        await self._schedule(symbol, h, lo, hi)
        return True

    monkeypatch.setattr(reader.RebuildRegistry, "request", every)
    with pytest.raises(RebuildsMultiplied, match=f"^{N} rebuilds for 2 series$"):
        await check_rebuild_flap(stores, monkeypatch)


class _CappedBars:
    """The WS gateway's bar-lease port over the real `SpecLeases` (SR-E12-04): the check and the
    lease are the production ones, the builder is not built."""

    def __init__(self, caps: SpecCaps = DEFAULT_CAPS) -> None:
        self.leases = SpecLeases(caps)

    def check(self, spec: BarSpec, symbol: str, user: str | None = None) -> None:
        self.leases.check((symbol, spec.spec_hash), user)

    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None:
        self.leases.acquire((symbol, spec.spec_hash), consumer, user)

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        self.leases.release((symbol, spec_hash), consumer, 0)


def check_ninth_series_refused(caps: SpecCaps = DEFAULT_CAPS) -> None:
    """The defended outcome: eight distinct `tick` series are taken on one user's socket, the
    ninth is refused `subscription_limit`, and it leaves no series hold and no lease."""
    from tests.contract.ws import _harness as h
    from tests.contract.ws.test_ws_bars_contract import _Rig

    rig, bars, cap = _Rig({}), _CappedBars(caps), DEFAULT_CAPS.per_user
    rig.w.registry.services.bars = bars
    topics = [f"bars.BTCUSDT.tick.{100 + i}" for i in range(cap + 1)]
    with h.connect(rig.w) as c:
        results = c.sub(*topics)["p"]["results"]
    if results[-1]["ok"]:
        raise SeriesCapMissed(f"series {cap + 1} of one user was taken")
    assert [r["ok"] for r in results] == [True] * cap + [False]
    assert results[-1]["error"]["code"] == "subscription_limit"
    assert rig.store.series_count() == cap
    assert len(bars.leases.keys()) == cap


def test_exhaustion_ninth_bars_series_of_one_user_is_refused_and_holds_nothing(wire: str) -> None:
    """X01 AC-04 through the real `/ws` router, under both subprotocols."""
    check_ninth_series_refused()


def test_exhaustion_control_without_the_per_user_cap_the_ninth_series_is_taken(wire: str) -> None:
    """Negative control: with the per-user cap lifted, the ninth series is held."""
    with pytest.raises(SeriesCapMissed, match=r"^series 9 of one user was taken$"):
        check_ninth_series_refused(SpecCaps(per_user=10**6))
