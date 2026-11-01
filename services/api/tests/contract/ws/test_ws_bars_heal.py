"""#2787 (E12-T06 D2-H1, P4b-2): the heal chain end to end, through `create_app`'s own composition
behind its real `/ws` router, on both wires. A series whose first read failed is
served live-only; a later read, started by another holder's `ensure` or by the heal driver's tick,
finds its stored bars. The store's repair hook, set by `create_app`, then sends the `history_repair`
`snap` (23 §7.4): as the very next frame, with `previous_seq` and no `d`, to the subscriber whose
`history` reaches the repaired depth (the forming bar counted, §6.1), and to none shallower. Only
the reader, the store's clock and the lease service are the test's; the bars come from the recorded
BTCUSDT tape (C-13.5), built by the real builder. A read that repairs nothing sends none, though a
live close landed while it was in flight: the hook follows the read's own fold, not the series."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.bars.models import BarSpec, BarUpdate
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series_store import RETRY_AFTER_S, SeriesStore, TailRead
from candleviewer.settings import Environment, Settings
from tests.contract.ws import _harness as h
from tests.contract.ws._support import ORIGIN
from tests.contract.ws.test_ws_bars_cold_series import (
    GEN,
    SPEC,
    _data,
    _fails,
    _keys,
    _next,
    _prints,
    _stored,
    _sub,
)
from tests.unit.bars.test_series_store import Clock
from tests.unit.ws.test_subscriptions import _Bars

USER = uuid.uuid4()


async def _authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
    if not token.startswith("good"):
        raise PermissionError("bad token")
    return "sess-1", USER, datetime(2100, 1, 1, tzinfo=UTC)


async def _load(uid: uuid.UUID) -> PrincipalSnapshot:
    perms = frozenset({Permission.MARKETDATA_READ})
    return PrincipalSnapshot(uid, frozenset({"manager"}), perms, ())


class _Stack:
    """`create_app`, its store reading through `reads` (one result per read)
    on the test's clock; the lease service is a fake, since a real `register` would replay the
    tape. Emissions go through the composed set's own router: store, publisher and writer."""

    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reads: list[TailRead]
    ) -> None:
        self.clock, results = Clock(), iter(reads)

        async def read(symbol: str, spec: BarSpec, limit: int) -> BarTail:
            return await next(results)(symbol, spec, limit)

        monkeypatch.setattr(
            "candleviewer.app.SeriesStore",
            lambda _tail: SeriesStore(read, clock=self.clock, release_grace_s=0.0, timeout_s=60.0),
        )
        settings = Settings(
            environment=Environment.DEMO, allowed_origins=ORIGIN, git_sha="heal", version="1.0.0",
            bars_state_root=str(tmp_path / "bars"), metrics_enabled=False,
            ws_shutdown_grace_ms=0,
        )  # fmt: skip
        app = create_app(settings, snapshot_loader=_load, ws_authenticate=_authenticate)
        self.client = TestClient(app, client=("127.0.0.1", 50000), headers={"origin": ORIGIN})
        services = app.state.ws_registry.services
        self.store, self.router = services.series, services.bars._router
        self.heal = app.state.bars_runtime.heal
        services.bars = _Bars()

    def call(self, fn: Any, *args: Any) -> Any:
        assert self.client.portal is not None  # set while the client context is open
        return self.client.portal.call(fn, *args)

    def emit(self, *updates: BarUpdate) -> None:
        self.call(self.router.emit, SPEC, updates, GEN)

    @contextmanager
    def connect(self, offer: list[str]) -> Iterator[h.Client]:
        with self.client.websocket_connect("/ws", subprotocols=offer) as ws:
            wire = "cv.v1.msgpack" if "cv.v1.msgpack" in offer else "cv.v1.json"
            assert ws.accepted_subprotocol == wire  # §2.2: the row runs on the wire it names
            c = h.Client(ws)
            c.open()  # §12.1 (#4992): through the `system` snap, the flags folded in
            assert c.system_snap is not None and "feature_flags" in c.system_snap["p"]
            yield c


def refreshed(result: str) -> float:
    """`bars_heal_refresh_total{result}`: what the heal driver's ticks have counted."""
    return REGISTRY.get_sample_value("bars_heal_refresh_total", {"result": result}) or 0.0


@pytest.mark.parametrize("offer", h.OFFERS.values(), ids=h.OFFERS.keys())
@pytest.mark.parametrize("trigger", ["ensure", "heal-driver"])
def test_contract_bars_a_healed_series_sends_history_repair_to_the_subscriber_it_reaches_only(
    trigger: str, offer: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first read fails, so the series is live-only: its close 3 and forming bar 4 arrive as
    `d`s. The next read finds bars 0 to 2, the newest 3rd from the newest bar served (the forming
    bar counted), so `history: 3` gets a `snap` of bars 2 to 4 as its very next frame, and
    `history: 2`, which holds the bars it held, gets none: its next frame is the next `d`. Whoever
    starts the read, the store's hook sends it once: a `d` follows each subscriber's frames in
    order, so a missed or a doubled repair shows as the wrong frame. `ensure` is a subscriber's
    read, which only the hook can follow; the driver's tick is the other, `due` then `refresh`."""
    stack, before = _Stack(tmp_path, monkeypatch, [_fails, _stored(12)]), refreshed("repaired")
    with stack.client, stack.connect(offer) as deep, stack.connect(offer) as shallow:
        for c, history in ((deep, 3), (shallow, 2)):
            _sub(c, {"encoding": "structured", "history": history})
        stack.emit(*_prints(13)[12])  # live: the close of bar 3 and the forming bar 4
        live = [_next(c, "d") for c in (deep, shallow)]
        stack.clock.t += RETRY_AFTER_S  # the failed read is due again
        if trigger == "ensure":
            stack.call(stack.store.ensure, h.SYM, SPEC)  # another holder's: the read runs now
        else:
            stack.call(stack.heal.tick)
        stack.emit(*_prints(14)[13])
        snap, later = _data(deep, "snap", "structured"), _next(deep, "d")
        after = _next(shallow, "d")
        assert (stack.store.hydrated(h.SYM, SPEC.spec_hash), later["s"], after["s"]) == (True, 4, 3)
    assert [f["s"] for f in live] == [2, 2] and snap["s"] == 3
    assert (snap["meta"]["reason"], snap["meta"]["previous_seq"]) == ("history_repair", 2)
    assert _keys(snap) == [(GEN, 2, True), (GEN, 3, True), (GEN, 4, False)]  # bar 2 it lacked
    assert refreshed("repaired") - before == (trigger == "heal-driver")


@pytest.mark.parametrize("offer", h.OFFERS.values(), ids=h.OFFERS.keys())
def test_contract_bars_a_read_that_repairs_nothing_sends_no_snap_though_a_close_landed_in_flight(
    offer: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first read withholds a row, so the series is not complete; the driver's re-read finds
    the same bars, and a live close lands while it is in flight. The read changed nothing, so the
    hook sends no `snap`: the very next frame is the next `d`. A task that diffed the series
    across the read's `await` would see the live close and send one."""
    entered, release = threading.Event(), asyncio.Event()

    async def withheld(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        return BarTail((await _stored(12)(symbol, spec, limit)).bars, dropped=1)

    async def parked(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        entered.set()
        await release.wait()
        return await _stored(12)(symbol, spec, limit)

    stack, before = _Stack(tmp_path, monkeypatch, [withheld, parked]), refreshed("unchanged")
    with stack.client, stack.connect(offer) as c:
        _sub(c, {"encoding": "structured", "history": 3})
        stack.clock.t += RETRY_AFTER_S  # the degraded read is due again
        assert stack.client.portal is not None
        ticking = stack.client.portal.start_task_soon(stack.heal.tick)
        assert entered.wait(5.0)  # the driver's read is in flight
        stack.emit(*_prints(13)[12])  # live: the close of bar 3 and the forming bar 4
        live = _next(c, "d")
        stack.call(release.set)
        ticking.result(5.0)  # a bound, not a delay
        stack.emit(*_prints(14)[13])
        later = _next(c, "d")
    assert (live["s"], later["s"]) == (2, 3)
    assert stack.store.hydrated(h.SYM, SPEC.spec_hash) and refreshed("unchanged") - before == 1
