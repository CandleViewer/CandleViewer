"""The submission contract on the in-memory stores (E29-T04 #913), and the fakes' own calls: a
fault at the commit, a write that waits while another holds its rows over its hook, the sweep
over every account, the hooks' default bounds, which the adapters share, and every CHECK the
schema declares on the four tables, met by name or left to the row's own refusals. The pairing
reads' contract (`store_reads_contract.py`, E29-T05) runs here too."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from datetime import timedelta
from itertools import count
from typing import Any, Final, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import CheckConstraint

from candleviewer.db import models
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import AccountRef
from candleviewer.oms import fakes
from candleviewer.oms.fakes import InMemoryOrderStore as Fake
from candleviewer.oms.fakes import InMemoryRecordedStopStore, InMemorySubmissionStore
from candleviewer.oms.repository import RecordedStopRepository
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import recorded_stops, user_roles_sqlalchemy
from candleviewer.storage.repositories.orders import NewOrder
from candleviewer.storage.repositories.recorded_stops import (
    EVERY_ACCOUNT,
    RecordedStopStore,
    StopStatus,
    SweptStop,
)
from candleviewer.storage.repositories.recorded_stops_sqlalchemy import (
    SqlAlchemyRecordedStopStore,
)
from candleviewer.storage.repositories.submissions import (
    AnchorTakenError,
    FirstPersist,
    FirstPersisted,
)
from candleviewer.storage.repositories.submissions_sqlalchemy import SqlAlchemySubmissionStore
from tests.unit.oms.recorded_stop_contract import RecordedStopContract, StopGateContract
from tests.unit.oms.store_reads_contract import StoreReadsContract
from tests.unit.oms.submission_contract import (
    EVENT,
    NOTHING,
    T0,
    TICK,
    Bounded,
    Harness,
    SubmissionContract,
    entry,
    reduce_only,
)


def held(fake: Fake, first: FirstPersist, order: NewOrder) -> tuple[int, ...]:
    """How many of the persist's anchor, group, leg, order and stop rows the fake holds."""
    legs = [leg.id for record in fake._groups.values() for leg in record.legs]
    return (
        int(first.anchor.id in fake._anchors),
        int(first.group is not None and first.group.id in fake._groups),
        sum(leg.id in legs for leg in first.legs),
        int(order.id in fake._orders),
        sum(stop.id in fake._stops for stop in first.recorded_stops),
    )


def accounts() -> tuple[UUID, UUID]:
    """An account and its profile: the fake holds neither, only their ids."""
    return uuid4(), uuid4()


def demo_account(fake: Fake) -> tuple[UUID, UUID]:
    """A demo account, as the Postgres harness makes one, its environment seeded from its
    `AccountRef` (`trg_tgl_env`, SEC-2B1-03), and its profile, of which the fake holds the id."""
    account, profile = accounts()
    ref = AccountRef(
        account_id=AccountId(account), uid="100001", environment="demo", key_ref=str(uuid4())
    )
    fake.submissions.seed_account(ref)
    return account, profile


def move_stop(fake: Fake, record_id: UUID, status: str) -> None:
    """A lifecycle move no store writes yet, as `trg_rs_guard` and `rs_times` admit it."""
    row = fake._stops[record_id]
    stamps: dict[str, Any] = ({"in_force_at": T0, "answered_at": row.answered_at or T0}
                              if status == "in_force" else {"closed_at": T0})  # fmt: skip
    fake._stops[record_id] = replace(row, status=cast(StopStatus, status), **stamps)


def bind_stop(fake: Fake, record_id: UUID, exchange_order_id: str) -> None:
    """An exchange order id no store binds yet, as `trg_rs_guard` admits the one bind."""
    fake._stops[record_id] = replace(fake._stops[record_id], exchange_order_id=exchange_order_id)


def twin_stop(fake: Fake, record_id: UUID, twin_id: UUID) -> None:
    """A row of `record_id`'s request values and age under another id, unbound."""
    fake._stops[twin_id] = replace(fake._stops[record_id], id=twin_id, exchange_order_id=None)


def tick(fake: Fake) -> None:
    """The next row the fake writes is a microsecond younger."""
    now = fake._clock() + TICK
    fake._clock = lambda: now


class TestInMemorySubmissionStores(SubmissionContract, StoreReadsContract):
    @pytest.fixture
    def fake(self) -> Fake:
        return Fake(clock=lambda: T0)

    @pytest.fixture
    def h(self, fake: Fake) -> Harness:
        def bounded(seconds: float) -> Bounded:
            return Bounded(
                InMemorySubmissionStore(fake, audit_timeout_s=seconds),
                InMemoryRecordedStopStore(fake, audit_timeout_s=seconds),
            )

        return Harness(
            submissions=fake.submissions, anchors=fake.anchors, stops=fake.stops, orders=fake,
            executions=fake.executions, new_user=uuid4, new_account=lambda: demo_account(fake),
            refuse=fake.submissions.refuse, bounded=bounded,
            held=lambda first, order: held(fake, first, order),
            move_stop=lambda record_id, status: move_stop(fake, record_id, status),
            bind_stop=lambda record_id, xid: bind_stop(fake, record_id, xid),
            twin_stop=lambda record_id, twin_id: twin_stop(fake, record_id, twin_id),
            tick=lambda: tick(fake),
        )  # fmt: skip

    async def test_a_leg_on_an_account_never_seeded_passes_the_environment_trigger(
        self, fake: Fake
    ) -> None:
        """The fake holds no account rows, so a leg on an account no `AccountRef` seeded passes
        `trg_tgl_env` here; Postgres never reaches the trigger for such an account, as
        `require_live` refuses it first (D-2B1-02). A rig that persists groups seeds them."""
        first, order = entry(uuid4(), *accounts(), group={"env": "live"})
        await fake.submissions.create_first(first, order, EVENT)
        assert held(fake, first, order) == (1, 1, 1, 1, 1)

    @pytest.mark.parametrize("committed", [False, True])
    async def test_a_fault_at_the_commit(self, fake: Fake, committed: bool) -> None:
        """`fail_next`: an outage before the commit leaves nothing; a commit whose answer was cut
        off leaves every row, so its retry meets the key it holds, as on Postgres."""
        first, order = entry(uuid4(), *accounts())
        fake.fail_next(
            StorageTierUnavailable("postgres unreachable (OSError)"), committed=committed
        )
        with pytest.raises(StorageTierUnavailable):
            await fake.submissions.create_first(first, order, EVENT)
        assert held(fake, first, order) == ((1, 1, 1, 1, 1) if committed else NOTHING)
        if committed:
            with pytest.raises(AnchorTakenError, match="ux_tg_creator_ref"):
                await fake.submissions.create_first(first, order, EVENT)
        else:
            await fake.submissions.create_first(first, order, EVENT)

    async def test_a_write_waits_while_another_holds_its_rows_over_its_hook(
        self, fake: Fake
    ) -> None:
        """Postgres holds a transaction's rows until it ends: a write waits for it (here any write
        does), and a read never sees them."""
        release = asyncio.Event()

        async def audit(persisted: FirstPersisted) -> None:
            await release.wait()

        first, order = entry(uuid4(), *accounts(), write_ahead=audit)
        persisting = asyncio.ensure_future(fake.submissions.create_first(first, order, EVENT))
        _, plain = reduce_only(uuid4(), uuid4())
        creating = asyncio.ensure_future(fake.create(plain, EVENT))
        for _ in range(5):
            await asyncio.sleep(0)
        assert not (persisting.done() or creating.done())
        assert await fake.get(order.exchange_account_id, order.id) is None
        release.set()
        await asyncio.gather(persisting, creating)
        assert held(fake, first, order) == (1, 1, 1, 1, 1)

    async def test_the_startup_sweep_covers_every_account_by_name(self, fake: Fake) -> None:
        user = uuid4()
        persists = [entry(user, *accounts()) for _ in "ab"]
        for persist in persists:
            await fake.submissions.create_first(*persist, EVENT)
        audited: list[SweptStop] = []

        async def audit(swept: tuple[SweptStop, ...]) -> None:
            audited.extend(swept)

        with pytest.raises(TypeError, match="EVERY_ACCOUNT"):
            await fake.stops.void_orphans(cast(Any, None), at=T0, write_ahead=audit)
        swept = await fake.stops.void_orphans(EVERY_ACCOUNT, at=T0, write_ahead=audit)
        expected = {stop.id for first, _ in persists for stop in first.recorded_stops}
        assert {stop.id for stop in swept} == expected and list(swept) == audited


class TestInMemoryRecordedStopResolution(RecordedStopContract):
    """S3-H's complete-read contract on the fakes, on a clock that moves a microsecond per write,
    as Postgres stamps each transaction's rows apart."""

    h = TestInMemorySubmissionStores.h

    @pytest.fixture
    def fake(self) -> Fake:
        ticks = count()
        return Fake(clock=lambda: T0 + timedelta(microseconds=next(ticks)))


class TestInMemoryStopGate(StopGateContract):
    """H3's gate end to end on the fakes, on the same ticking clock."""

    h = TestInMemorySubmissionStores.h
    fake = TestInMemoryRecordedStopResolution.fake


@pytest.mark.parametrize(
    "store",
    [
        RecordedStopStore,
        SqlAlchemyRecordedStopStore,
        InMemoryRecordedStopStore,
        RecordedStopRepository,
    ],
    ids=lambda store: store.__name__,
)
def test_no_recorded_stop_store_binds_on_its_own(store: type) -> None:
    """24 Sec.8.3 rule 7: a first holder binds in the transaction that materialises its order, a
    successor in `release_and_bind`. A bind of its own would leave a record unbound for good when
    a crash falls between the order's insert and the bind."""
    assert not hasattr(store, "bind")


def test_the_hooks_default_bounds_are_the_adapters() -> None:
    """The fakes cannot import the drivers' modules (ADR-0003), so they keep their own copy of the
    submissions' bound; the recorded stops' bound lives driver-free in `recorded_stops`, every
    store's default, and stays the drivers' shared write-ahead bound."""

    def default(store: type) -> object:
        return inspect.signature(store).parameters["audit_timeout_s"].default

    assert default(SqlAlchemySubmissionStore) == fakes.SUBMISSION_AUDIT_TIMEOUT_S
    assert default(InMemorySubmissionStore) == fakes.SUBMISSION_AUDIT_TIMEOUT_S
    assert default(SqlAlchemyRecordedStopStore) == recorded_stops.STOP_AUDIT_TIMEOUT_S
    assert default(InMemoryRecordedStopStore) == recorded_stops.STOP_AUDIT_TIMEOUT_S
    assert recorded_stops.STOP_AUDIT_TIMEOUT_S == user_roles_sqlalchemy.WRITE_AHEAD_TIMEOUT_S


#: The CHECKs the fakes do not meet themselves, by the name Postgres reports: a value outside its
#: column's `Literal`; one the row refuses when it is built (`NewTradeGroup`, `NewTradeGroupLeg`,
#: `NewRecordedStop`, `NewAnchor`, `AnchorOutcome`), or `FirstPersist.check` before any statement;
#: one only the store writes (a time, a status, a default); and `tgl_profile_version`, which the
#: share-locked re-check meets first (`profile_changed`: no live profile is below version 1).
_LEFT: Final = {
    "trade_groups": {
        "tg_side", "tg_origin", "tg_policy", "tg_entrytype", "tg_trigby", "tg_finite", "tg_times",
    },
    "trade_group_legs": {
        "tgl_finite", "tgl_snapshot", "tgl_sl_conf", "tgl_fees_nonneg", "tgl_profile_version",
    },
    "recorded_stops": {
        "rs_posidx", "rs_side", "rs_kind", "rs_source", "rs_mode", "rs_entry", "rs_restore",
        "rs_px", "rs_size", "rs_trail", "rs_finite", "rs_marker", "rs_status", "rs_times",
        "rs_release",
    },
    "idempotency_anchors": {
        "ia_operation", "ia_ref_fmt", "ia_target", "ia_decided", "ia_code", "ia_ret_code",
    },
}  # fmt: skip
_MET: Final = {
    "trade_groups": set(fakes._GROUP_CHECKS),
    "trade_group_legs": set(fakes._LEG_CHECKS),
    "recorded_stops": set[str](),
    "idempotency_anchors": set[str](),
}


@pytest.mark.parametrize("table", sorted(_LEFT))
def test_the_fakes_meet_every_check_the_schema_declares(table: str) -> None:
    """A revision that adds a CHECK fails here until the fake meets it or a row refuses it."""
    constraints = models.metadata.tables[table].constraints
    declared = {str(c.name) for c in constraints if isinstance(c, CheckConstraint)}
    head = f"ck_{table}_"
    assert {name.removeprefix(head) for name in declared} == _MET[table] | _LEFT[table]
    assert not _MET[table] & _LEFT[table]
