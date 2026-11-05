"""The closed-PnL comparison (E29-S06 #981 slice 5c; 24 Sec.8.13 "Divergent" and "The divergence
record"), on the orchestrator's rulings Q2, Q3 and Q6: the pure verdict at its bounds, then the
comparer over a recording writer and flag store, which proves the order (the pair decided, the
record durable, the count, then the flag), the volume bounds and the strain deferral. No I/O."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms import closed_pnl_compare as cmp
from candleviewer.oms import closed_pnl_sync as sync_mod
from candleviewer.oms.closed_pnl_compare import (
    DIVERGENCE_TOTAL,
    WITHHELD_TOTAL,
    ClosedPnlComparer,
    DivergenceRecord,
    Tolerance,
    compared,
)
from candleviewer.oms.closed_pnl_compose import Composed
from candleviewer.storage.repositories.closed_pnl import ClosedPnlRecordRow, record_id
from tests.unit.audit.audit_waits import virtual
from tests.unit.exchange.bybit._trading import ACCOUNT_A
from tests.unit.oms.test_closed_pnl_sync import REACH, XID, Store, _composable, _record
from tests.unit.oms.test_closed_pnl_sync import rig as sync_rig

T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
ACCOUNT = UUID(int=0xA1)
TOL = Tolerance(Decimal("1e-8"), Decimal("0.01"))
FINE = Tolerance(Decimal("1e-8"), Decimal("1e-18"))  # the relative bound alone decides
D = Decimal


def row(xid: str = "x1", **over: Any) -> ClosedPnlRecordRow:
    """A settled record of 3 at an entry of 1195, the venue's figure -47.4065323."""
    base = ClosedPnlRecordRow(
        id=record_id(ACCOUNT, xid), exchange_account_id=ACCOUNT, exchange_order_id=xid,
        symbol="ETHUSDT", side="long", position_idx=0, trade_group_id=None, qty=D(3),
        avg_entry_price=D(1195), avg_exit_price=D(1180), leverage=D(10),
        closed_pnl=D("-47.4065323"), gross_pnl=D(-45), fee_pnl=D("-4.275"), funding_pnl=D(0),
        opened_at=T0, closed_at=T0,
        venue_created_at=T0, settled_at=T0, final_at=None, divergent=False, audited_local_net=None,
        audited_closed_pnl=None, updated_at=T0,
    )  # fmt: skip
    return replace(base, **over)


def item(r: ClosedPnlRecordRow, local: str | None = "-49.275", entry: str = "1195") -> Composed:
    return Composed(row=r, local_net=None if local is None else D(local), avg_entry=D(entry),
                    closed=r.qty, final=False)  # fmt: skip


# --- the verdict ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("over", "local", "entry", "closed"),
    [
        ({"settled_at": None, "closed_pnl": None, "leverage": None}, "-49.275", "1195", "3"),
        ({}, None, "1195", "3"),  # no local figure
        ({}, "-49.275", "1195", "2"),  # the closes do not close the record's qty
        ({}, "-49.275", "1195.0000120", "3"),  # the entry gate: just past 1e-8 x 1195
    ],
)
def test_an_item_is_compared_only_when_both_figures_exist_and_the_gates_hold(
    over: dict[str, Any], local: str | None, entry: str, closed: str
) -> None:
    """Q2 (C19, D4): otherwise the stored fills do not account for the record."""
    r = row(**over)
    assert compared(r, None if local is None else D(local), D(entry), D(closed), TOL) is None


def test_the_entry_gate_holds_at_its_bound_and_the_difference_is_signed_local_minus_venue() -> None:
    at_bound = compared(row(), D("-49.275"), D("1195.00001195"), D(3), TOL)
    assert at_bound is not None and at_bound.divergent
    assert at_bound.difference == D("-1.8684677") and at_bound.pair == (
        D("-49.275"),
        row().closed_pnl,
    )


def test_a_difference_at_the_bound_is_not_divergent_and_one_just_past_it_is() -> None:
    """Strictly greater (D1), relative to the venue's figure (D2): 1e-6 is the bound on 100, and a
    bound relative to the local figure (99.999999) would call it divergent."""
    venue = row(closed_pnl=D(-100))
    at = compared(venue, D("-99.999999"), D(1195), D(3), FINE)
    past = compared(venue, D("-99.9999989"), D(1195), D(3), FINE)
    assert at is not None and not at.divergent
    assert past is not None and past.divergent


def divergent(r: ClosedPnlRecordRow, local: str, tolerance: Tolerance = TOL) -> bool:
    verdict = compared(r, D(local), D(1195), D(3), tolerance)
    assert verdict is not None
    return verdict.divergent


def test_against_a_venue_figure_of_0_any_difference_past_the_floor_is_divergent() -> None:
    """D3: no special case for 0; the floor alone stands between them."""
    zero = row(closed_pnl=D(0))
    assert not divergent(zero, "0") and not divergent(zero, "0.01")
    assert divergent(zero, "0.0100001") and divergent(zero, "1e-17", FINE)


def test_a_sub_cent_close_is_not_divergent_under_the_floor() -> None:
    """Q6's absolute floor: half a cent on a record under 1 USDT passes the relative bound only."""
    small = row(closed_pnl=D("-0.5"))
    assert not divergent(small, "-0.505") and divergent(small, "-0.505", FINE)


@given(
    st.decimals(min_value=D("0.01"), max_value=D(10_000), places=8),
    st.decimals(min_value=D(-50), max_value=D(50), places=8),
    st.integers(min_value=-4, max_value=4),
)
def test_property_the_relative_verdict_is_scale_invariant(
    venue: Decimal, change: Decimal, power: int
) -> None:
    k = D(10) ** power
    one = compared(row(closed_pnl=venue), venue + change, D(1195), D(3), FINE)
    scaled = compared(row(closed_pnl=venue * k), (venue + change) * k, D(1195), D(3), FINE)
    assert one is not None and scaled is not None and one.divergent == scaled.divergent


def test_the_tolerance_takes_its_maxima_as_the_settings_do() -> None:
    assert (cmp.REL_MAX, cmp.FLOOR_MAX) == (D("0.001"), D(1))
    assert Tolerance(D("0.001"), D(1)).rel == D("0.001")


@pytest.mark.parametrize(
    ("rel", "floor"),
    [
        (D(0), D("0.01")), (D("0.0011"), D("0.01")), (D("1e-8"), D(0)), (D("1e-8"), D("1.01")),
        (D("NaN"), D("0.01")), (D("1e-8"), D("Infinity")), (1e-8, D("0.01")),
    ],
)  # fmt: skip
def test_the_tolerance_refuses_values_outside_its_bounds(rel: Any, floor: Any) -> None:
    with pytest.raises(ValueError, match="tolerance"):
        Tolerance(rel, floor)


# --- the comparer --------------------------------------------------------------------------------


@dataclass
class Writer:
    """The record writer: each write recorded in `events`, refused while `fails` names one; it
    checks that no store call is open across it (private point 8)."""

    events: list[tuple[str, Any]]
    flags: Flags | None = None
    fails: list[Exception] = field(default_factory=list)
    strain: bool = False
    records: list[DivergenceRecord] = field(default_factory=list)

    def strained(self) -> bool:
        return self.strain

    async def write(self, record: DivergenceRecord) -> None:
        assert self.flags is None or not self.flags.open, "a record written inside a store call"
        await asyncio.sleep(0)
        if self.fails:
            raise self.fails.pop(0)
        self.records.append(record)
        self.events.append(("write", record.reason))


@dataclass
class Flags:
    """The flag store over `rows`, as the table's `cpr_pair` takes it; each call recorded with the
    count the comparer had made by then, and open while it runs."""

    rows: dict[UUID, ClosedPnlRecordRow]
    events: list[tuple[str, Any]]
    counted: Any = None
    open: bool = False
    fails: list[Exception] = field(default_factory=list)
    met: bool = True

    async def mark_divergent(
        self, account_id: UUID, rid: UUID, local: Decimal, venue: Decimal
    ) -> bool:
        self.open = True
        await asyncio.sleep(0)
        self.open = False
        if self.fails:
            raise self.fails.pop(0)
        assert self.rows[rid].settled_at is not None  # cpr_pair
        self.rows[rid] = replace(self.rows[rid], divergent=True, audited_local_net=local,
                                 audited_closed_pnl=venue)  # fmt: skip
        self.events.append(("flag", (local, venue, self.counted())))
        return self.met

    async def clear_divergent(self, account_id: UUID, rid: UUID) -> bool:
        self.rows[rid] = replace(self.rows[rid], divergent=False)
        self.events.append(("clear", rid))
        return True


@dataclass
class Rig:
    comparer: ClosedPnlComparer
    writer: Writer
    flags: Flags
    metrics: Metrics
    events: list[tuple[str, Any]]

    def total(self) -> float:
        return self.metrics.registry.get_sample_value(DIVERGENCE_TOTAL, {"env": "demo"}) or 0.0

    def withheld(self, reason: str) -> float:
        labels = {"env": "demo", "reason": reason}
        return self.metrics.registry.get_sample_value(WITHHELD_TOTAL, labels) or 0.0

    async def compare(self, *items: Composed, missing: tuple[ClosedPnlRecordRow, ...] = ()) -> Any:
        for i in items:
            self.flags.rows.setdefault(i.row.id, i.row)
        fresh = [replace(i, row=self.flags.rows[i.row.id]) for i in items]
        return await self.comparer.compare(ACCOUNT, fresh, missing)


def rig(tolerance: Tolerance = TOL) -> Rig:
    events: list[tuple[str, Any]] = []
    flags, metrics = Flags({}, events), Metrics("demo")
    writer = Writer(events, flags)
    r = Rig(ClosedPnlComparer(marks=flags, writer=writer, tolerance=tolerance, metrics=metrics),
            writer, flags, metrics, events)  # fmt: skip
    flags.counted = r.total
    return r


@virtual
async def test_a_new_pair_is_recorded_durable_then_counted_then_flagged() -> None:
    """24 Sec.8.13 (C-2.9, D5, D11): the record ahead of the flag, never inside a store call; the
    count between them; the flag with the pair the record names."""
    r = rig()
    assert await r.compare(item(row())) == {}
    pair = (D("-49.275"), D("-47.4065323"))
    assert r.events == [("write", "closed_pnl_divergence"), ("flag", (*pair, 1.0))]
    [record] = r.writer.records
    assert record.record_id == row().id and record.after_state["difference"] == "-1.8684677"
    assert r.total() == 1.0


@virtual
async def test_the_same_pair_writes_nothing_and_a_new_pair_writes_a_new_record() -> None:
    """D6, D7: the item keeps the pair it recorded; a clear keeps it, and diverging again with it
    flags without a second record."""
    r = rig()
    await r.compare(item(row()))
    await r.compare(item(row()))
    assert [e for e, _ in r.events] == ["write", "flag"]
    await r.compare(item(row(), local="-47.4065323"))  # within the bound: cleared, pair kept
    cleared = r.flags.rows[row().id]
    assert not cleared.divergent and cleared.audited_local_net == D("-49.275")
    await r.compare(item(row()))  # the recorded pair again: flagged, no record
    await r.compare(item(row(), local="-50"))  # a new pair: recorded
    assert [e for e, _ in r.events] == ["write", "flag", "clear", "flag", "write", "flag"]
    assert r.total() == 2.0


@virtual
async def test_a_composition_that_compares_nothing_leaves_the_flag_and_its_pair() -> None:
    """D8: no local figure, so nothing is compared and nothing written."""
    r = rig()
    await r.compare(item(row()))
    await r.compare(item(row(), local=None))
    flagged = r.flags.rows[row().id]
    assert flagged.divergent and flagged.audited_closed_pnl == D("-47.4065323")
    assert len(r.events) == 2


@virtual
async def test_a_failed_write_leaves_the_item_unflagged_counts_nothing_and_is_owed() -> None:
    """D5, D9: a record that cannot be written leaves the item unflagged until the next
    comparison, which the owed set keeps; logged at ERROR by kind, with no figure."""
    r = rig()
    r.writer.fails.append(OSError("full"))
    with capture_logs() as logs:
        owed = await r.compare(item(row()))
    assert owed == {"x1": None} and r.events == [] and r.total() == 0.0
    assert not r.flags.rows[row().id].divergent
    [error] = [e for e in logs if e["event"] == "closed_pnl_divergence_unwritten"]
    assert error["log_level"] == "error" and error["kind"] == "OSError"
    assert await r.compare(item(row())) == {} and r.total() == 1.0


@virtual
async def test_a_failed_flag_after_its_record_is_owed_and_retried_without_a_second_record() -> None:
    """The pair written last counts as recorded: the retry flags it and writes no second record."""
    r = rig()
    r.flags.fails.append(TimeoutError())
    assert await r.compare(item(row())) == {"x1": None}
    assert r.total() == 1.0 and not r.flags.rows[row().id].divergent
    assert await r.compare(item(row())) == {}
    assert len(r.writer.records) == 1 and r.total() == 1.0
    flagged = r.flags.rows[row().id]
    assert flagged.divergent and flagged.audited_local_net == D("-49.275")
    assert [e for e, _ in r.events] == ["write", "flag"]


@virtual
async def test_a_flag_that_meets_no_row_is_logged_with_its_ids_and_not_owed() -> None:
    r = rig()
    r.flags.met = False  # the store met no settled row of the account's
    with capture_logs() as logs:
        assert await r.compare(item(row())) == {}
    [warning] = [e for e in logs if e["event"] == "closed_pnl_flag_unmet"]
    assert warning == {
        "event": "closed_pnl_flag_unmet", "log_level": "warning",
        "account_id": str(ACCOUNT), "record_id": str(row().id),
    }  # fmt: skip


@virtual
async def test_nothing_is_written_into_a_strained_writer_and_the_record_is_owed() -> None:
    """Q6: the order audit has priority; the deferral is counted."""
    r = rig()
    r.writer.strain = True
    assert await r.compare(item(row())) == {"x1": None}
    assert r.events == [] and r.withheld("backpressure") == 1.0
    r.writer.strain = False
    assert await r.compare(item(row())) == {} and r.total() == 1.0


@virtual
async def test_a_pass_writes_at_most_its_cap_and_owes_the_rest() -> None:
    r = rig()
    items = [item(row(f"x{n}")) for n in range(cmp.EMIT_LIMIT + 3)]
    with capture_logs() as logs:
        owed = await r.compare(*items)
    assert len(r.writer.records) == cmp.EMIT_LIMIT and r.total() == cmp.EMIT_LIMIT
    assert set(owed) == {f"x{n}" for n in range(cmp.EMIT_LIMIT, cmp.EMIT_LIMIT + 3)}
    assert r.withheld("pass_cap") == 3.0
    [held] = [e for e in logs if e["event"] == "closed_pnl_divergence_withheld"]
    assert (held["reason"], held["records"]) == ("pass_cap", 3)


@virtual
async def test_a_record_id_writes_at_most_its_limit_of_records_and_then_nothing() -> None:
    """The limit counts the records written for one record id in the process, whatever their
    pairs (24 Sec.8.13 "The volume is bounded")."""
    r = rig()
    for n in range(cmp.PAIR_LIMIT + 2):
        await r.compare(item(row(), local=str(D(-50) - n)))
    assert len(r.writer.records) == cmp.PAIR_LIMIT and r.withheld("pair_limit") == 2.0


@virtual
async def test_the_owed_set_is_bounded_and_what_it_drops_is_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cmp, "RETRY_LIMIT", 2)
    r = rig()
    r.writer.strain = True
    owed = await r.compare(*(item(row(f"x{n}")) for n in range(4)))
    assert set(owed) == {"x0", "x1"} and r.withheld("retry_dropped") == 2.0


@virtual
async def test_a_venue_figure_missing_at_the_end_of_the_reach_is_recorded_never_flagged() -> None:
    """Q2: the same action with its own reason, the venue's figure and the difference null; a row
    settled meanwhile is not missing."""
    r = rig()
    missing = row(settled_at=None, closed_pnl=None, leverage=None, venue_created_at=None)
    await r.compare(missing=(missing, row("x2")))
    [record] = r.writer.records
    assert record.reason == "closed_pnl_venue_missing" and r.total() == 1.0
    assert (record.after_state["closed_pnl"], record.after_state["difference"]) == (None, None)
    assert record.after_state["local_net_pnl"] == "-49.275"
    assert [e for e, _ in r.events] == ["write"]
    r.writer.strain = True
    assert await r.compare(missing=(missing,)) == {"x1": missing}


@virtual
async def test_an_oscillating_pair_spends_the_limit_by_records_written() -> None:
    """A to B to A writes three records: the limit is on records, not on distinct pairs."""
    r = rig()
    for local in ("-50", "-51", "-50"):
        await r.compare(item(row(), local=local))
    assert len(r.writer.records) == 3 and r.comparer._pairs[row().id][0] == 3


@virtual
async def test_the_logs_name_the_account_and_the_record_never_a_figure() -> None:
    """C-12.6: the WARNING names the account and the record; no log line carries money."""
    r = rig()
    with capture_logs() as logs:
        await r.compare(item(row()))
    [warning] = [e for e in logs if e["event"] == "closed_pnl_divergence_recorded"]
    assert warning == {
        "event": "closed_pnl_divergence_recorded", "log_level": "warning",
        "account_id": str(ACCOUNT), "record_id": str(row().id), "reason": "closed_pnl_divergence",
    }  # fmt: skip
    text = repr(logs)
    for figure in ("49.275", "47.4065323", "1.8684677", "4.275"):
        assert figure not in text


def test_the_effective_tolerance_is_logged_once_when_built() -> None:
    with capture_logs() as logs:
        rig()
    assert [(e["rel"], e["floor"]) for e in logs if e["event"] == "closed_pnl_tolerance"] == [
        ("1E-8", "0.01")
    ]


def test_the_counter_is_unlabelled_and_the_withheld_one_bounded_by_its_reasons() -> None:
    """20 Sec.12.1: no account label (SR-125); the ticket's `{account}` is superseded."""
    specs = {s.name: s for s in CATALOGUE}
    total, held = specs[DIVERGENCE_TOTAL], specs[WITHHELD_TOTAL]
    assert (total.kind, total.labels, total.max_series) == ("counter", (), 1)
    assert (held.kind, held.labels, held.max_series) == ("counter", ("reason",), len(cmp.WITHHELD))
    assert "OmsClosedPnlDivergence" in total.alert


# --- in the sync's pass (24 Sec.8.13 "The sync"; Q2, Q3) ------------------------------------------


def comparing(writer: Writer) -> Any:
    def build(store: Store, metrics: Metrics) -> ClosedPnlComparer:
        return ClosedPnlComparer(marks=store, writer=writer, tolerance=TOL, metrics=metrics)

    return build


def priced(r: Any) -> Any:
    """`_composable`'s long opened at the record's own entry, so the entry gate holds: the local
    net -49.275 against the venue's -47.4065323."""
    named = _composable(r)
    symbol, opener = r.store.fills[0]
    r.store.fills[0] = (symbol, replace(opener, exec_price=_record().avg_entry_price))
    r.venue.records = [_record()]
    return named


@virtual
async def test_the_sync_compares_what_the_delta_set_composed_and_records_a_divergence() -> None:
    writer = Writer([])
    r = sync_rig(composed=True, comparer=comparing(writer))
    priced(r)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(10)
    held = r.store.rows[record_id(ACCOUNT_A, XID)]
    assert [rec.reason for rec in writer.records] == ["closed_pnl_divergence"]
    assert (held.divergent, held.audited_local_net, held.audited_closed_pnl) == (
        True, D("-49.275"), D("-47.4065323"),
    )  # fmt: skip
    assert held.final_at is not None and r.sync._state[ACCOUNT_A].owed == {}
    await r.sync.stop()


@virtual
async def test_a_comparison_owed_keeps_the_poll_until_its_record_is_written() -> None:
    """The record final, nothing else polled: the owed comparison alone asks for the next pass,
    which composes the order again and writes the record."""
    writer = Writer([], fails=[OSError("full")])
    r = sync_rig(composed=True, comparer=comparing(writer))
    priced(r)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(10)
    rid = record_id(ACCOUNT_A, XID)
    assert r.sync._state[ACCOUNT_A].owed == {XID: None} and not r.store.rows[rid].divergent
    assert r.store.rows[rid].final_at is not None and r.sync._state[ACCOUNT_A].due is not None
    await asyncio.sleep(61)
    assert len(writer.records) == 1 and r.store.rows[rid].divergent
    assert r.sync._state[ACCOUNT_A].owed == {} and r.sync._state[ACCOUNT_A].due is None
    await r.sync.stop()


def provisional(xid: str, closed_at: datetime, store: Store) -> ClosedPnlRecordRow:
    held = row(xid, exchange_account_id=ACCOUNT_A, id=record_id(ACCOUNT_A, xid),
               closed_at=closed_at, settled_at=None, closed_pnl=None, leverage=None,
               venue_created_at=None)  # fmt: skip
    store.rows[held.id], store.orders[xid] = held, (UUID(int=len(store.orders) + 0x100), "filled")
    return held


@virtual
async def test_a_venue_figure_missing_when_its_item_leaves_the_reach_is_recorded_once() -> None:
    """Q2: the first pass looks from MISSING_SPAN before the reach; a later one from where the
    last one's reach was, so the item is recorded once, and one older than the span is not."""
    writer = Writer([])
    r = sync_rig(composed=True, comparer=comparing(writer))
    gone = provisional("x-gone", REACH - timedelta(hours=1), r.store)
    provisional("x-old", REACH - sync_mod.MISSING_SPAN - timedelta(hours=1), r.store)
    provisional("x-due", REACH + timedelta(hours=1), r.store)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(10)
    r.sync.reconnected(ACCOUNT_A)
    await asyncio.sleep(10)
    assert [(rec.record_id, rec.reason) for rec in writer.records] == [
        (gone.id, "closed_pnl_venue_missing")
    ]
    assert not r.store.rows[gone.id].divergent
    await r.sync.stop()


@virtual
async def test_a_venue_figure_missing_held_back_is_recorded_at_the_next_pass_once() -> None:
    """Q2, Q3: a strained writer holds the record back; the next pass's look has moved past the
    item, so only the owed row brings it back, and it is written once."""
    writer = Writer([], strain=True)
    r = sync_rig(composed=True, comparer=comparing(writer))
    gone = provisional("x-gone", REACH - timedelta(hours=1), r.store)
    r.sync.start([ACCOUNT_A])
    await asyncio.sleep(10)
    assert writer.records == [] and r.sync._state[ACCOUNT_A].owed == {"x-gone": gone}
    assert r.sync._state[ACCOUNT_A].due is not None
    writer.strain = False
    await asyncio.sleep(61)
    r.sync.reconnected(ACCOUNT_A)
    await asyncio.sleep(10)
    assert [(rec.record_id, rec.reason) for rec in writer.records] == [
        (gone.id, "closed_pnl_venue_missing")
    ]
    assert r.sync._state[ACCOUNT_A].owed == {}
    await r.sync.stop()


@virtual
async def test_a_failed_look_for_the_missing_is_made_again_from_where_it_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = Writer([])
    r = sync_rig(composed=True, comparer=comparing(writer))
    gone = provisional("x-gone", REACH - timedelta(hours=1), r.store)
    pending, failed = r.store.pending, list[datetime]()

    async def failing_once(account_id: UUID, since: datetime, limit: int) -> Any:
        if since < REACH and not failed:
            failed.append(since)
            raise OSError("down")
        return await pending(account_id, since, limit)

    monkeypatch.setattr(r.store, "pending", failing_once)
    with capture_logs() as logs:
        r.sync.start([ACCOUNT_A])
        await asyncio.sleep(10)
    assert writer.records == [] and r.sync._state[ACCOUNT_A].due is not None
    assert any(e["event"] == "closed_pnl_missing_read_failed" for e in logs)
    await asyncio.sleep(61)
    assert [rec.record_id for rec in writer.records] == [gone.id]
    await r.sync.stop()


@virtual
async def test_a_full_page_of_the_missing_moves_the_look_only_to_its_last_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.18: row 56's page bounds the look; the rest of that time waits for the next pass."""
    monkeypatch.setattr(sync_mod, "PENDING_LIMIT", 2)
    writer = Writer([])
    r = sync_rig(composed=True, comparer=comparing(writer))
    rows = [provisional(f"x{n}", REACH - timedelta(hours=3 - n), r.store) for n in range(3)]
    r.sync.start([ACCOUNT_A])
    seen = []
    for _ in range(3):
        await asyncio.sleep(10)
        seen.append([rec.record_id for rec in writer.records])
        r.sync.reconnected(ACCOUNT_A)
    assert seen == [[rows[0].id], [rows[0].id, rows[1].id], [row.id for row in rows]]
    await r.sync.stop()
