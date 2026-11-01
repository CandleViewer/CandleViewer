"""E29-T08's stuck-order detector (#916; 24-internal-schemas.md Sec.8.13): each kind's predicate at
its boundary (just under and just over its threshold), the dedupe and the 300 s cool-down, the
incident's schema, the sinks in their order, one scan and the loop's cadence. No network, no
sleeps: a manual clock, the in-memory reads and recording doubles (`stuck_rig`)."""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from prometheus_client import generate_latest
from pydantic import ValidationError

from candleviewer.domain.primitives import AccountId
from candleviewer.oms import reconcile_job
from candleviewer.oms.incidents import (
    DETAILS,
    KINDS,
    SEVERITY,
    OmsIncident,
    audit_state,
    event_details,
    event_kind,
    incident,
)
from candleviewer.oms.reconcile_standing import ReconcileStanding
from candleviewer.oms.stuck_detector import (
    COOLDOWN_S,
    SCAN_JITTER_S,
    UNKNOWN_CYCLE_S,
    Dedupe,
    Thresholds,
    order_kind,
)
from candleviewer.storage.repositories.stuck import InMemoryStuckReads, StuckOrderRow
from tests.unit.oms.stuck_rig import (
    ACCOUNT,
    OTHER,
    T0,
    Clock,
    Standing,
    build,
    link,
    order,
    position,
)

#: 24 Sec.8.13's defaults: in flight 30 s, unknown one cycle (30 s), pending 15 s, naked 3 s.
DEFAULTS = Thresholds()


def test_the_unknown_threshold_is_one_reconciliation_cycle() -> None:
    """BQ-3: a cycle is `reconcile_interval_s`, the driver's own cadence."""
    assert UNKNOWN_CYCLE_S == reconcile_job.INTERVAL_S == DEFAULTS.unknown_s == 30.0


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_thresholds_refuse_a_bound_that_is_not_a_finite_positive_number(bad: float) -> None:
    with pytest.raises(ValueError, match="finite number of seconds above 0"):
        Thresholds(pending_s=bad)


def test_thresholds_refuse_a_bool() -> None:
    with pytest.raises(TypeError, match="number of seconds"):
        Thresholds(naked_s=True)


@pytest.mark.parametrize(
    ("row", "kind"),
    [
        (order(state="submitted", age_s=30.0), None),  # in flight 30 s: at the bound, not over
        (order(state="submitted", age_s=30.001), "in_flight"),
        (order(state="quarantined", age_s=30.001), "in_flight"),
        (order(state="unknown", age_s=30.0), None),  # one cycle exactly: not more than one
        (order(state="unknown", age_s=30.001), "unknown"),
        (order(state="pending_cancel", in_flight=False, age_s=15.0), None),
        (order(state="pending_cancel", in_flight=False, age_s=15.001), "pending"),
        (order(state="pending_amend", in_flight=False, age_s=15.001), "pending"),
        (order(state="accepted", in_flight=False, age_s=9_999.0), None),  # live and answered
        (order(state="killed", age_s=9_999.0), None),  # a KILLed row keeps in_flight: final
        (order(state="cancelled", age_s=9_999.0), None),
    ],
)
def test_order_kind_judges_each_kind_strictly_above_its_threshold(row: Any, kind: Any) -> None:
    assert order_kind(row, DEFAULTS) == kind


def test_an_unknown_row_is_only_ever_unknown_though_its_create_is_in_flight() -> None:
    """`unknown` outranks `in_flight`: with a shorter in-flight bound, an `unknown` row past it but
    inside one cycle is not stuck at all."""
    short = Thresholds(in_flight_s=20.0)
    assert order_kind(order(state="unknown", age_s=25.0), short) is None
    assert order_kind(order(state="submitted", age_s=25.0), short) == "in_flight"


# --- The dedupe and the cool-down -------------------------------------------------------------


def _orders(dedupe: Dedupe, *rows: Any, now: float, complete: bool = True) -> list[str]:
    due, _ = dedupe.orders(rows, complete=complete, now=now, at=T0)
    for found in due:
        dedupe.raised(found, now)
    return [found.incident.kind for found in due]


def test_an_order_raises_once_then_again_only_after_the_cool_down() -> None:
    dedupe = Dedupe(DEFAULTS)
    assert _orders(dedupe, order(), now=0.0) == ["in_flight"]
    assert _orders(dedupe, order(), now=COOLDOWN_S - 0.001) == []
    assert _orders(dedupe, order(), now=COOLDOWN_S) == ["in_flight"]


def test_a_kind_that_outranks_the_one_raised_is_raised_at_once() -> None:
    """A create in flight that lands in `unknown` escalates from `error` to `critical`."""
    dedupe = Dedupe(DEFAULTS)
    assert _orders(dedupe, order(), now=0.0) == ["in_flight"]
    assert _orders(dedupe, order(state="unknown", age_s=31.0), now=5.0) == ["unknown"]
    assert _orders(dedupe, order(state="unknown", age_s=36.0), now=10.0) == []


def test_a_cleared_order_is_forgotten_and_its_next_episode_raises_at_once() -> None:
    dedupe = Dedupe(DEFAULTS)
    assert _orders(dedupe, order(), now=0.0) == ["in_flight"]
    assert _orders(dedupe, now=5.0) == []  # a complete scan no longer finds it
    assert _orders(dedupe, order(), now=10.0) == ["in_flight"]


def test_a_scan_cut_at_its_limit_forgets_nothing() -> None:
    dedupe = Dedupe(DEFAULTS)
    assert _orders(dedupe, order(), now=0.0) == ["in_flight"]
    assert _orders(dedupe, order(2), now=5.0, complete=False) == ["in_flight"]
    assert _orders(dedupe, order(), now=10.0) == []  # still raised: the cut read kept it


def test_an_order_under_its_threshold_is_cleared_too() -> None:
    """An order that stepped (its age restarted) is no longer stuck: it is forgotten."""
    dedupe = Dedupe(DEFAULTS)
    assert _orders(dedupe, order(), now=0.0) == ["in_flight"]
    assert _orders(dedupe, order(age_s=1.0), now=5.0) == []
    assert _orders(dedupe, order(), now=40.0) == ["in_flight"]


def test_the_stuck_counts_are_per_kind_of_each_order_once() -> None:
    dedupe = Dedupe(DEFAULTS)
    rows = (order(1), order(2, state="unknown"), order(3, state="pending_cancel", in_flight=False))
    _due, counts = dedupe.orders(rows, complete=True, now=0.0, at=T0)
    assert dict(counts) == {"in_flight": 1, "unknown": 1, "pending": 1}


def _naked(dedupe: Dedupe, *rows: Any, now: float, complete: bool = True) -> list[float]:
    due = dedupe.naked(rows, complete=complete, now=now, at=T0)
    for found in due:
        dedupe.raised(found, now)
    return [found.incident.age_s for found in due]


def test_a_naked_position_raises_once_per_episode_strictly_after_its_deadline() -> None:
    """BQ-4: the first scan starts the episode; 3 s is not past 3 s; 3.001 s is; once only."""
    dedupe = Dedupe(DEFAULTS)
    assert _naked(dedupe, position(), now=0.0) == []
    assert _naked(dedupe, position(), now=3.0) == []
    assert _naked(dedupe, position(), now=3.001) == [3.001]
    assert _naked(dedupe, position(), now=COOLDOWN_S * 3) == []  # no reminder within an episode


def test_a_position_read_protected_or_flat_ends_its_episode() -> None:
    dedupe = Dedupe(DEFAULTS)
    _naked(dedupe, position(), now=0.0)
    assert _naked(dedupe, position(), now=5.0) == [5.0]
    assert _naked(dedupe, now=10.0) == []  # protected or flat: the episode ends
    assert _naked(dedupe, position(), now=15.0) == []  # a new episode starts its own clock
    assert _naked(dedupe, position(), now=18.5) == [3.5]


def test_a_failed_or_cut_position_read_keeps_the_episode() -> None:
    dedupe = Dedupe(DEFAULTS)
    _naked(dedupe, position(), now=0.0)
    assert _naked(dedupe, now=1.0, complete=False) == []
    assert _naked(dedupe, position(), now=4.0) == [4.0]


def _stale(dedupe: Dedupe, *accounts: UUID, now: float) -> list[float]:
    due = dedupe.stale(accounts, now=now, at=T0)
    for found in due:
        dedupe.raised(found, now)
    return [found.incident.age_s for found in due]


def test_a_stale_account_raises_at_once_then_each_cool_down() -> None:
    """BQ-2: the standing has waited out its window, so the first stale scan raises."""
    dedupe = Dedupe(DEFAULTS)
    assert _stale(dedupe, ACCOUNT, now=0.0) == [0.0]
    assert _stale(dedupe, ACCOUNT, now=COOLDOWN_S - 1) == []
    assert _stale(dedupe, ACCOUNT, now=COOLDOWN_S) == [COOLDOWN_S]
    assert _stale(dedupe, now=COOLDOWN_S + 5) == []  # resolved: forgotten
    assert _stale(dedupe, ACCOUNT, now=COOLDOWN_S + 10) == [0.0]


def test_the_order_map_forgets_its_oldest_order_past_its_cap() -> None:
    """C-2.18: a forgotten order raises once more, never less."""
    dedupe = Dedupe(DEFAULTS, max_tracked=2)
    assert (
        _orders(dedupe, order(1), order(2), order(3), now=0.0, complete=False) == ["in_flight"] * 3
    )
    assert _orders(dedupe, order(1), now=5.0, complete=False) == ["in_flight"]  # evicted


def test_the_episode_map_forgets_its_oldest_position_past_its_cap() -> None:
    """C-2.18: a forgotten episode begins again at the next scan that finds its position naked."""
    dedupe = Dedupe(DEFAULTS, max_tracked=2)
    _naked(dedupe, position("BTCUSDT"), position("ETHUSDT"), now=0.0, complete=False)
    _naked(dedupe, position("SOLUSDT"), now=1.0, complete=False)  # BTCUSDT's, the oldest, goes
    assert _naked(dedupe, position("ETHUSDT"), now=3.5, complete=False) == [3.5]  # kept
    assert _naked(dedupe, position("BTCUSDT"), now=3.5, complete=False) == []  # begun again


def test_the_account_map_forgets_its_oldest_account_past_its_cap() -> None:
    """C-2.18: a forgotten account raises once more, never less."""
    dedupe = Dedupe(DEFAULTS, max_tracked=2)
    first, second, third = UUID(int=1), UUID(int=2), UUID(int=3)
    assert _stale(dedupe, first, second, third, now=0.0) == [0.0] * 3  # the first is forgotten
    assert _stale(dedupe, first, second, now=5.0) == [0.0]  # so raised again; the second cools


def test_the_standings_accessor_is_a_copy_of_its_stale_accounts() -> None:
    """BQ-2: the real standing's `stale_accounts`, which the scan reads: a copy, so a mark or a
    clear after the read never changes what the read returned."""
    standing = ReconcileStanding()
    standing.mark_stale(AccountId(ACCOUNT))
    read = standing.stale_accounts()
    assert read == frozenset({ACCOUNT})
    standing.mark_stale(AccountId(OTHER))
    standing.clear(AccountId(ACCOUNT))
    assert read == frozenset({ACCOUNT})
    assert standing.stale_accounts() == frozenset({OTHER})


def test_a_row_the_incident_refuses_is_skipped_and_logged() -> None:
    dedupe = Dedupe(DEFAULTS)
    bad = order()
    bad = type(bad)(bad.order_id, bad.account_id, "not-an-id", "BTCUSDT", "submitted", True, 40.0)
    assert _orders(dedupe, bad, order(2), now=0.0) == ["in_flight"]


# --- The incident's schema ----------------------------------------------------------------------


def _incident(**over: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "kind": "in_flight", "severity": "error", "order_link_id": link(1),
        "account_id": ACCOUNT, "symbol": "BTCUSDT", "age_s": 31.0, "detected_at": T0,
        "detail": DETAILS["in_flight"],
    }  # fmt: skip
    return fields | over


def test_every_kind_has_its_severity_and_only_error_and_critical_form_incidents() -> None:
    assert set(SEVERITY) == set(KINDS) == set(DETAILS)
    assert set(SEVERITY.values()) == {"error", "critical"}
    assert [k for k in KINDS if SEVERITY[k] == "critical"] == ["unknown", "naked", "account_stale"]


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"severity": "critical"}, "severity is its kind's"),
        ({"detail": "free text"}, "fixed sentence"),
        ({"order_link_id": None}, "names its order_link_id"),
        ({"order_link_id": "x-1"}, "24 Sec.8.3's form"),
        ({"kind": "naked", "severity": "critical", "detail": DETAILS["naked"]}, "only an order"),
        (
            {"kind": "account_stale", "severity": "critical", "detail": DETAILS["account_stale"],
             "order_link_id": None},
            "an account none",
        ),
        ({"age_s": -0.001}, "at least 0"),
        ({"age_s": math.nan}, "at least 0"),
        ({"detected_at": T0.replace(tzinfo=None)}, "UTC time"),
        ({"detected_at": T0.astimezone(timezone(timedelta(hours=2)))}, "UTC time"),
        ({"symbol": "btc usdt"}, "pattern"),
        ({"price": "63000"}, "Extra inputs"),
    ],
)  # fmt: skip
def test_the_incident_refuses_a_shape_off_its_contract(over: dict[str, Any], why: str) -> None:
    with pytest.raises(ValidationError, match=why):
        OmsIncident(**_incident(**over))


def test_the_incident_is_frozen_closed_and_rounds_its_age_to_the_millisecond() -> None:
    found = incident("in_flight", account_id=ACCOUNT, age_s=31.12345, detected_at=T0,
                     order_link_id=link(1), symbol="BTCUSDT")  # fmt: skip
    assert found.age_s == 31.123
    config = OmsIncident.model_config
    assert (config.get("frozen"), config.get("extra")) == (True, "forbid")


def test_an_ext_key_names_an_adopted_order() -> None:
    found = incident("unknown", account_id=ACCOUNT, age_s=31, detected_at=T0,
                     order_link_id="ext-" + "a" * 32, symbol="ETHUSDT")  # fmt: skip
    assert found.severity == "critical"


def test_the_records_hold_ids_and_fixed_text_only() -> None:
    found = incident("naked", account_id=OTHER, age_s=4.5, detected_at=T0, symbol="ETHUSDT")
    assert audit_state(found) == {
        "kind": "naked", "severity": "critical", "order_link_id": None,
        "account_id": str(OTHER), "symbol": "ETHUSDT", "age_s": "4.500",
        "detected_at": T0.isoformat(), "detail": DETAILS["naked"],
    }  # fmt: skip
    assert event_details(found) == {
        "kind": "naked",
        "account_id": str(OTHER),
        "age_s": "4.500",
        "symbol": "ETHUSDT",
    }
    assert event_kind("account_stale") == "incident_account_stale"


# --- The sinks, in their order ------------------------------------------------------------------


async def test_the_record_is_written_ahead_of_the_row_and_the_bus() -> None:
    rig = build()
    calls: list[str] = []
    rig.records.calls, rig.events.calls, rig.bus.calls = calls, calls, calls
    rig.reads.orders["demo"] = [order()]
    assert await rig.detector.scan() == "ok"
    assert calls == ["record", "event", "bus"]
    assert rig.pager.severities == ["alert"]  # an `error` incident alerts
    assert rig.count("oms_incidents_total", kind="in_flight") == 1


async def test_an_unrecorded_incident_is_still_paged_and_counted_but_never_published() -> None:
    rig = build()
    rig.records.refuse = True
    rig.reads.orders["demo"] = [order(state="unknown")]
    await rig.detector.scan()
    assert rig.pager.calls == ["oms_incident_unrecorded", "oms_incident_unknown"]
    assert rig.pager.severities == ["page", "page"]
    assert rig.count("oms_incidents_total", kind="unknown") == 1
    assert rig.events.rows == [] and rig.bus.offered == []


async def test_a_failed_row_still_reaches_the_bus() -> None:
    rig = build()
    rig.events.refuse = True
    rig.reads.orders["demo"] = [order()]
    await rig.detector.scan()
    assert [found.kind for found in rig.bus.offered] == ["in_flight"]


async def test_a_pager_that_raises_ends_nothing() -> None:
    rig = build()
    rig.pager.refuse = True
    rig.reads.orders["demo"] = [order()]
    assert await rig.detector.scan() == "ok"
    assert rig.kinds() == ["in_flight"]


async def test_a_record_that_does_not_answer_is_cut_at_its_bound_and_paged() -> None:
    rig = build(sink_timeout_s=0.01)
    rig.records.free = 0  # every write waits for an answer that does not come
    rig.reads.orders["demo"] = [order()]
    await rig.detector.scan()
    assert rig.pager.calls == ["oms_incident_unrecorded", "oms_incident_in_flight"]
    assert rig.bus.offered == []


async def test_a_bus_that_refuses_the_hop_ends_nothing() -> None:
    rig = build()
    rig.bus.refuse = True
    rig.reads.orders["demo"] = [order()]
    assert await rig.detector.scan() == "ok"
    assert rig.kinds() == ["in_flight"] and len(rig.events.rows) == 1


def test_the_maps_refuse_a_cap_under_one() -> None:
    with pytest.raises(ValueError, match="max_tracked"):
        Dedupe(DEFAULTS, max_tracked=0)


@pytest.mark.parametrize(
    ("scan", "why"),
    [({"timeout_s": 5.0}, "under its interval"), ({"limit": 0}, "limit is an int")],
)
def test_the_scan_refuses_a_bound_past_its_interval_or_no_limit(
    scan: dict[str, Any], why: str
) -> None:
    with pytest.raises(ValueError, match=why):
        build(**scan)


class _HangingReads(InMemoryStuckReads):
    """A read that never answers."""

    async def stuck_orders(
        self, environment: Any, *, limit: int
    ) -> tuple[tuple[StuckOrderRow, ...], bool]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


async def test_a_scan_its_bound_cuts_is_failed_and_its_chores_still_run() -> None:
    """The loop counts a cut scan `failed`, logs it, then runs each chore, one that raises
    logged and the loop going on."""
    ran: list[str] = []

    async def chore() -> None:
        ran.append("chore")
        raise RuntimeError("the account read failed")

    async def stop(_seconds: float) -> None:
        raise asyncio.CancelledError

    rig = build(reads=_HangingReads(), sleep=stop, timeout_s=0.01, chores=(chore,))
    with pytest.raises(asyncio.CancelledError):
        await rig.detector.run()
    assert rig.count("oms_detector_scans_total", result="failed") == 1
    assert ran == ["chore"]


# --- One scan -----------------------------------------------------------------------------------


async def test_a_scan_reads_judges_and_raises_every_kind() -> None:
    standing = Standing({OTHER})
    rig = build(standing=standing)
    rig.reads.orders["demo"] = [order(1), order(2, state="unknown"),
                                order(3, state="pending_amend", in_flight=False)]  # fmt: skip
    rig.reads.positions["demo"] = [position()]
    assert await rig.detector.scan() == "ok"
    assert rig.kinds() == ["in_flight", "unknown", "pending", "account_stale"]
    rig.clock.advance(3.5)
    await rig.detector.scan()
    assert rig.kinds()[-1] == "naked"
    assert rig.count("naked_position_alerts_total") == 1
    assert rig.count("oms_stuck_orders", kind="unknown") == 1


async def test_the_audit_object_is_the_order_or_the_account() -> None:
    rig = build()
    rig.reads.orders["demo"] = [order(7)]
    rig.reads.positions["demo"] = [position()]
    await rig.detector.scan()
    rig.clock.advance(3.5)
    await rig.detector.scan()
    assert [(kind, oid) for _f, kind, oid in rig.records.written] == [
        ("order", str(UUID(int=7))),
        ("exchange_account", str(ACCOUNT)),
    ]


async def test_a_failed_read_fails_the_scan_and_judges_what_was_read() -> None:
    rig = build(standing=Standing({ACCOUNT}))
    rig.reads.fail = RuntimeError("the store is down")
    assert await rig.detector.scan() == "failed"
    assert rig.kinds() == ["account_stale"]  # in memory, read whatever the store does


class _OneReadFails(InMemoryStuckReads):
    """The orders read or the positions read raises, the other answers."""

    def __init__(self, failing: str) -> None:
        super().__init__()
        self.failing = failing

    async def stuck_orders(
        self, environment: Any, *, limit: int
    ) -> tuple[tuple[StuckOrderRow, ...], bool]:
        if self.failing == "orders":
            raise RuntimeError("the orders read failed")
        return await super().stuck_orders(environment, limit=limit)

    async def naked_positions(self, environment: Any, *, limit: int) -> tuple[Any, bool]:
        if self.failing == "positions":
            raise RuntimeError("the positions read failed")
        return await super().naked_positions(environment, limit=limit)


@pytest.mark.parametrize("failing", ["orders", "positions"])
async def test_either_read_failing_alone_fails_the_scan(failing: str) -> None:
    """Each read's failure is the scan's: the other read is still judged."""
    reads = _OneReadFails(failing)
    rig = build(reads=reads)
    reads.orders["demo"], reads.positions["demo"] = [order()], [position()]
    assert await rig.detector.scan() == "failed"
    assert rig.kinds() == ([] if failing == "orders" else ["in_flight"])


async def test_an_incident_whose_sinks_were_cut_is_raised_by_the_next_scan() -> None:
    """A scan the bound cuts marks raised only the incidents whose sinks ran."""
    rig = build()
    rig.reads.orders["demo"] = [order(1), order(2)]
    rig.records.free = 1  # the second record waits
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await rig.detector.scan()
    rig.records.gate.set()
    await rig.detector.scan()
    assert [f.order_link_id for f, _k, _o in rig.records.written] == [link(1), link(2)]
    await rig.detector.scan()  # both raised now: nothing until the cool-down
    assert len(rig.records.written) == 2


# --- The loop -----------------------------------------------------------------------------------


async def test_the_loop_scans_nothing_until_ready_then_every_interval() -> None:
    ready = False
    waits: list[float] = []
    rig: Any = None

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        rig.clock.advance(seconds)
        if len(waits) == 3:
            nonlocal ready
            ready = True
        if rig.reads.reads >= 6:
            raise asyncio.CancelledError

    rig = build(ready=lambda: ready, sleep=sleep)
    with pytest.raises(asyncio.CancelledError):
        await rig.detector.run()
    assert waits[:3] == [0.5, 0.5, 0.5]  # it polls for `ready` and reads nothing meanwhile
    assert waits[3:] == [5.0, 5.0, 5.0]  # then one scan at once and one each 5 s
    assert rig.count("oms_detector_scans_total", result="ok") == 3
    assert rig.detector.stalled()  # its loop ended


@pytest.mark.parametrize(
    ("jitter", "waits"),
    [(0.4, [0.4, 5.0]), (9.0, [SCAN_JITTER_S, 5.0]), (-1.0, [5.0])],
)
async def test_each_ticks_phase_waits_its_jitter_cut_to_half_a_second(
    jitter: float, waits: list[float]
) -> None:
    """BQ-5: a tick's phase is jittered by up to `SCAN_JITTER_S`: a jitter above it waits it, and
    one under 0 waits nothing, so the first scan runs at once."""
    waited: list[float] = []
    rig: Any = None

    async def sleep(seconds: float) -> None:
        waited.append(seconds)
        rig.clock.advance(seconds)
        if rig.reads.reads >= 2:  # the first scan read both: the loop ends at its next tick
            raise asyncio.CancelledError

    rig = build(sleep=sleep, jitter=lambda: jitter)
    with pytest.raises(asyncio.CancelledError):
        await rig.detector.run()
    assert waited == pytest.approx(waits)


async def test_a_scan_that_ends_restarts_the_stall_clock() -> None:
    """20 Sec.6.2: the stall runs from the last scan's end, not from `ready`: 29 s after the scan
    that ended 5 s after `ready`, the detector is not stalled, and at 30 s it is."""
    rig: Any = None
    parked = asyncio.Event()

    async def sleep(seconds: float) -> None:
        if rig.count("oms_detector_scans_total", result="ok") >= 2:
            parked.set()
            await asyncio.Event().wait()  # the next tick never comes in this test
        rig.clock.advance(seconds)

    rig = build(sleep=sleep)
    loop = asyncio.ensure_future(rig.detector.run())
    await asyncio.wait_for(parked.wait(), 2)  # a bound on the test: the scans at 0 s and 5 s
    rig.clock.advance(29.0)
    assert not rig.detector.stalled()
    rig.clock.advance(1.0)
    assert rig.detector.stalled()
    loop.cancel()
    await asyncio.gather(loop, return_exceptions=True)


class _SlowReads(InMemoryStuckReads):
    """A read that runs past two more ticks of the scan's clock."""

    def __init__(self) -> None:
        super().__init__()
        self.clock = Clock()

    async def stuck_orders(
        self, environment: Any, *, limit: int
    ) -> tuple[tuple[StuckOrderRow, ...], bool]:
        self.clock.advance(12.0)
        return await super().stuck_orders(environment, limit=limit)


async def test_a_tick_due_while_a_scan_ran_is_skipped_never_queued() -> None:
    rig: Any = None

    async def sleep(seconds: float) -> None:
        rig.clock.advance(seconds)
        raise asyncio.CancelledError

    slow = _SlowReads()
    rig = build(sleep=sleep, reads=slow)
    slow.clock = rig.clock  # the read runs on the scan's own clock
    with pytest.raises(asyncio.CancelledError):
        await rig.detector.run()
    assert rig.count("oms_detector_scans_total", result="skipped") == 2


def test_the_stall_reads_the_last_scan_age_once_ready() -> None:
    rig = build()
    assert (rig.detector.last_scan_age(), rig.detector.stalled()) == (0.0, False)
    rig.detector._since = rig.clock.monotonic()
    rig.clock.advance(29.9)
    assert not rig.detector.stalled()
    rig.clock.advance(0.1)
    assert rig.detector.stalled()
    assert rig.count("oms_detector_last_scan_age_seconds") == pytest.approx(30.0)


def test_every_labelled_series_exists_at_zero_before_any_scan() -> None:
    rig = build()
    for kind in ("in_flight", "unknown", "pending"):
        assert f'oms_stuck_orders{{env="dev",kind="{kind}"}} 0.0' in _exposed(rig)
    for result in ("ok", "failed", "skipped"):
        assert f'oms_detector_scans_total{{env="dev",result="{result}"}} 0.0' in _exposed(rig)
    for kind in KINDS:
        assert f'oms_incidents_total{{env="dev",kind="{kind}"}} 0.0' in _exposed(rig)


def _exposed(rig: Any) -> str:
    return str(generate_latest(rig.metrics.registry).decode())


def test_the_rig_clock_is_utc() -> None:
    assert Clock().now().tzinfo is not None
    assert isinstance(Clock().now(), datetime)
