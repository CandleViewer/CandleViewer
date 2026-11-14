# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""No row, no order (#843 A4 fold 3; the coordinator's ruling of 2026-10-25 11:46Z): each create's
scrubbed intent is in the run's ledger before the create is sent, a row not written sends no
create, and a kill between the two leaves the row and no order. The ledger is the run's own state
for the scoped flatten (ruling R1C-02 (b)): an order it does not list survives the flatten, as a
foreign order and a foreign position do, and `flatten` adopts a failed run's from its ledger.

Fold 4 (the coordinator's ruling 3): each row is fsynced before its create is sent, the run
directory once when the file is created, and a failed fsync is a failed write; the row's write
and fsync both fall before the create's measured window opens. Fold 5 (R3-01): each fsync comes
after its row's write, so it covers the row's bytes."""

from __future__ import annotations

import functools
import json
import os
import re
import stat
from decimal import Decimal
from itertools import accumulate
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import OrderAck, PlaceOrderRequest
from spike.oms_demo_path import cycles, harness, run
from spike.oms_demo_path.config import RunConfig
from spike.oms_demo_path.harness import Harness
from spike.oms_demo_path.ledger import LEDGER, IntentLedger
from spike.oms_demo_path.measure import Timings
from spike.oms_demo_path.offline import Corpus, CorpusVenue, VenueOrder, default_corpus
from spike.oms_demo_path.safety import GuardedPort, QtyLimits, Refused, digest
from spike.oms_demo_path.scrub import Scrubber
from spike.oms_demo_path.tests.test_modes import _Rig
from spike.oms_demo_path.tests.test_safety import LIMITS, guarded, opener
from spike.oms_demo_path.tests.test_scope import _failed_run, _refused_and_untouched

FOREIGN = Decimal("0.003")
CREATE = "/v5/order/create"


class _Killed(BaseException):
    """The process dying where it stands (SIGKILL, the OOM killer): nothing after it runs."""


def _venue() -> CorpusVenue:
    return CorpusVenue(Corpus(default_corpus()))


def _cfg(out: Path, **fields: Any) -> RunConfig:
    base: dict[str, Any] = {"mode": "cycles", "out": out, "cycles": 2, "min_hours": 0.0}
    return RunConfig(**(base | {"fill_wait_s": 0.2} | fields))


def _rows(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / LEDGER
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _refusing(_data: bytes) -> None:
    raise OSError("no space left on device")


async def test_each_create_is_in_the_ledger_scrubbed_before_the_venue_sees_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, out = _venue(), tmp_path / "out"
    create = venue._order_create
    listed_first: list[bool] = []

    def seen(body: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        handles = {row["link_digest"] for row in _rows(out)}
        listed_first.append(digest(str(body["orderLinkId"])) in handles)
        return create(body, params)

    monkeypatch.setattr(venue, "_order_create", seen)
    assert await run.run(_cfg(out), venue=venue) == 0
    assert len(venue.creates) == 4 and listed_first == [True] * 4  # 2 openers, 2 closes
    rows = _rows(out)
    for row, body in zip(rows, venue.creates, strict=True):
        assert row["link_digest"] == digest(body["orderLinkId"])
        assert re.fullmatch(r"link#\d+", row["order_link_id"])
        assert (row["side"], row["reduce_only"]) == (body["side"].lower(), body["reduceOnly"])
        assert Decimal(row["qty"]) == Decimal(body["qty"])
        if body["reduceOnly"]:
            assert row["price"] is None and row["stop_loss"] is None
        else:
            assert Decimal(row["price"]) == Decimal(body["price"])
            assert Decimal(row["stop_loss"]) == Decimal(body["stopLoss"])
    text = (out / LEDGER).read_text(encoding="utf-8")
    assert not [b["orderLinkId"] for b in venue.creates if b["orderLinkId"] in text]
    assert oct((out / LEDGER).stat().st_mode & 0o777) == "0o600"
    summary = dict(run.summary_of(out))
    assert summary["ledger"] == {"file": LEDGER, "intents": 4, "adopted": 0, "orders": 4}


async def test_a_kill_between_the_intent_and_the_send_leaves_the_intent_and_no_order(
    tmp_path: Path,
) -> None:
    """The real port over the corpus venue: the row is written, then the process dies."""
    rig = _Rig(tmp_path, _venue())
    h = rig.harness
    h.port.limits, qty = QtyLimits.of(await h.public.instrument(), multiple=2, max_multiple=2)

    durable = h.ledger.write

    def written_then_killed(data: bytes) -> None:
        durable(data)  # the row is down (written and fsynced), then the process dies
        raise _Killed

    h.ledger.write = written_then_killed
    link = h.links.new()
    ref = rig.venue.ref
    req = PlaceOrderRequest(
        account=h.account,
        symbol="BTCUSDT",
        side="buy",
        order_type="limit",
        qty=qty,
        price=ref - 600,
        order_link_id=link,
        stop_loss=ref - 1800,
    )
    with pytest.raises(_Killed):
        await h.port.place_order(req)
    assert rig.venue.creates == [] and CREATE not in rig.venue.paths  # no order
    [row] = _rows(tmp_path / "out")  # and its intent
    assert (row["order_link_id"], row["link_digest"]) == ("link#1", digest(link))
    assert (row["side"], row["qty"], row["reduce_only"]) == ("buy", "0.002", False)
    assert Decimal(row["stop_loss"]) == ref - 1800 and link not in json.dumps(row)


async def test_a_failed_intent_write_sends_no_create() -> None:
    guard, fake = guarded()
    assert guard.ledger is not None
    guard.ledger.write = _refusing
    with pytest.raises(Refused, match="no row, no order"):
        await guard.place_order(opener())
    assert fake.calls == [] and guard.openers == 0 and guard.ledger.intents == 0
    guard.ledger = None
    with pytest.raises(Refused, match="no intent ledger"):
        await guard.place_order(opener())
    assert fake.calls == []


async def test_a_run_whose_intent_write_fails_sends_no_create_and_ends_flat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = _venue()
    original = cycles.one_cycle

    async def disk_full(h: Harness, *args: Any, **kwargs: Any) -> str:
        h.ledger.write = _refusing  # the disk refuses the first intent
        return await original(h, *args, **kwargs)

    monkeypatch.setattr(cycles, "one_cycle", disk_full)
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 1
    s = dict(run.summary_of(tmp_path / "out"))
    assert s["error"] == "Refused" and s["outcome"] == "error"
    assert venue.creates == [] and CREATE not in venue.paths
    assert (s["shutdown"]["cancelled"], s["shutdown"]["flat"]) == (0, True)
    assert s["ledger"]["intents"] == 0 and not (tmp_path / "out" / LEDGER).exists()


async def test_the_shutdown_flatten_owns_what_the_ledger_lists_and_the_rest_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue = _venue()
    seeded: list[VenueOrder] = []

    async def boom(h: Harness, link: str) -> None:
        unlisted = venue.rest_foreign_order()
        unlisted.link = h.links.new()  # the run's own prefix, never sent by it: no row
        seeded.extend([venue.rest_foreign_order(), unlisted])  # and a manual order
        venue.fill_foreign(FOREIGN)  # a manual fill inside the run's window (R2-11)
        raise RuntimeError("mid-cycle")

    monkeypatch.setattr(cycles, "read_order", boom)
    assert await run.run(_cfg(tmp_path / "out"), venue=venue) == 1
    shutdown = dict(run.summary_of(tmp_path / "out"))["shutdown"]
    assert (shutdown["cancelled"], shutdown["closed_qty"], shutdown["flat"]) == (1, "0.001", True)
    assert shutdown["not_ours_left"] == {"open_orders": 2, "venue_position_less_own_net": "0.003"}
    assert shutdown["fills_not_ours_in_window"] == {"trade": 1}
    assert [(o.status, o.filled) for o in seeded] == [("New", Decimal(0))] * 2
    assert venue.size == FOREIGN
    own = [o for o in venue.orders.values() if o not in seeded]
    assert own and all(o.status not in ("New", "PartiallyFilled") for o in own)


async def test_flatten_refuses_a_failed_run_whose_ledger_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, account = _venue(), uuid4()
    failed = await _failed_run(tmp_path, venue, account, monkeypatch)
    (failed / LEDGER).unlink()
    venue.paths.clear()
    venue.creates.clear()
    out = tmp_path / "flatten"
    cfg = RunConfig(mode="flatten", out=out, run_dir=failed, account_id=account)
    assert await run.run(cfg, venue=venue) == 2
    _refused_and_untouched(out, venue, "no readable intent ledger")
    assert venue.paths == [] and venue.size == Decimal("0.001")


# -- fold 4, ruling 3: each row fsynced before its create, outside the measured window ---------


class _Syncs:
    """`os.fsync`, each call kept by what it synced (`file` or `directory`), and a file's size as
    each of its fsyncs found it (`sizes`, R3-01: an fsync covers only the bytes written before
    it, so one that ran before the row's write would cover none of the row); `fail` makes the
    calls on that kind raise, as a disk that cannot sync would."""

    def __init__(self, fail: str | None = None) -> None:
        self.fail = fail
        self.calls: list[str] = []
        self.sizes: list[int] = []

    def __call__(self, fd: int) -> None:
        found = os.fstat(fd)
        kind = "directory" if stat.S_ISDIR(found.st_mode) else "file"
        if kind == self.fail:
            raise OSError("fsync: input/output error")
        os.fsync(fd)
        self.calls.append(kind)
        if kind == "file":
            self.sizes.append(found.st_size)


def _row_end(path: Path, link: str) -> int:
    """Where the ledger row of `link`'s create ends in the file, in bytes (its newline in)."""
    end = 0
    for line in path.read_bytes().splitlines(keepends=True):
        end += len(line)
        if json.loads(line)["link_digest"] == digest(link):
            return end
    raise AssertionError("the ledger has no row for this create")


async def test_each_row_is_fsynced_once_and_the_directory_once_when_the_file_is_created(
    tmp_path: Path,
) -> None:
    (tmp_path / "failed").mkdir()
    failed = IntentLedger(tmp_path / "failed", Scrubber(), elapsed=lambda: 0.0)
    for _ in range(2):  # a failed run's two orders, for `flatten` mode to adopt
        await failed.record(opener())
    syncs = _Syncs()
    ledger = IntentLedger(tmp_path, Scrubber(), elapsed=lambda: 0.0, fsync=syncs)
    for n in range(1, 4):
        await ledger.record(opener())
        assert syncs.calls == ["file", "directory"] + ["file"] * (n - 1)  # the file made: once
    assert await ledger.adopt(tmp_path / "failed" / LEDGER) == 2  # `adopted` rows: each fsynced
    assert syncs.calls.count("file") == 5 and syncs.calls.count("directory") == 1
    assert len(_rows(tmp_path)) == 5 and ledger.summary()["adopted"] == 2
    lines = (tmp_path / LEDGER).read_bytes().splitlines(keepends=True)
    assert syncs.sizes == list(accumulate(map(len, lines)))  # each fsync after its row's write


@pytest.mark.parametrize("fails", ["file", "directory"])
async def test_a_failing_fsync_sends_no_create(tmp_path: Path, fails: str) -> None:
    """A failed fsync is a failed write: refused, and nothing is sent (the row's own, or the
    directory's when the row created the file, whose entry would not survive a crash)."""
    fake = FakeTradingPort()
    guard = GuardedPort(fake)
    guard.limits = LIMITS
    guard.ledger = IntentLedger(tmp_path, Scrubber(), elapsed=lambda: 0.0, fsync=_Syncs(fails))
    with pytest.raises(Refused, match="no row, no order"):
        await guard.place_order(opener())
    assert fake.calls == [] and guard.openers == 0 and guard.ledger.intents == 0
    assert guard.ledger.digests == set()


async def test_each_row_is_fsynced_before_the_venue_sees_its_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venue, out, syncs = _venue(), tmp_path / "out", _Syncs()
    monkeypatch.setattr(harness, "IntentLedger", functools.partial(IntentLedger, fsync=syncs))
    create = venue._order_create
    seen: list[tuple[int, int, bool]] = []

    def at_the_venue(body: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        end = _row_end(out / LEDGER, str(body["orderLinkId"]))
        covered = bool(syncs.sizes) and syncs.sizes[-1] >= end  # R3-01: its row's bytes synced
        seen.append((syncs.calls.count("file"), len(_rows(out)), covered))  # fsyncs, rows
        return create(body, params)

    monkeypatch.setattr(venue, "_order_create", at_the_venue)
    assert await run.run(_cfg(out), venue=venue) == 0
    # 2 openers, 2 closes: each row on disk, and covered by its fsync, before its create
    assert seen == [(1, 1, True), (2, 2, True), (3, 3, True), (4, 4, True)]
    assert syncs.calls.count("directory") == 1


class _Clock:
    """The test's monotonic clock: moved by the venue below and by a slow disk."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _TimedVenue(FakeTradingPort):
    """A create that costs M2's signing 3 ms, 2 ms more of ours and the venue's 20 ms round trip
    at the seam, all on the test's clock."""

    def __init__(self, clock: _Clock, timings: Timings) -> None:
        super().__init__()
        self.clock, self.timings = clock, timings

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        async with self.timings.signing("sign_rest"):
            self.clock.now += 0.003
        self.clock.now += 0.002
        self.timings.exchanged(CREATE, 20.0)
        self.clock.now += 0.020
        return await super().place_order(req)


async def _create_timed(directory: Path, fsync_s: float) -> Timings:
    clock = _Clock()
    timings = Timings(monotonic=clock)

    def disk(_fd: int) -> None:  # each fsync, the row's and its directory's, takes `fsync_s`
        clock.now += fsync_s

    guard = GuardedPort(_TimedVenue(clock, timings), timings)
    guard.limits = LIMITS
    guard.ledger = IntentLedger(directory, Scrubber(), elapsed=lambda: 0.0, fsync=disk)
    assert (await guard.place_order(opener())).ok
    assert clock.now == pytest.approx(0.025 + 2 * fsync_s)  # the slow disk did take its time
    return timings


async def test_a_slow_fsync_leaves_the_measured_create_unchanged(tmp_path: Path) -> None:
    """The row's write and fsync happen before the measured window opens: a 50 ms fsync leaves
    the RTT, our overhead, the signing share and end to end as they are."""
    for name in ("fast", "slow"):
        (tmp_path / name).mkdir()
    fast = await _create_timed(tmp_path / "fast", 0.0)
    slow = await _create_timed(tmp_path / "slow", 0.050)
    for kind in ("rtt_ms", "overhead_ms", "signing_ms", "port_ms"):
        assert getattr(slow, kind)["create"] == pytest.approx(getattr(fast, kind)["create"]), kind
    assert slow.port_ms["create"] == [pytest.approx(25.0)]  # end to end: 25 ms, no fsync in it
    assert slow.overhead_ms["create"] == [pytest.approx(5.0)]  # our overhead: 25 - 20
