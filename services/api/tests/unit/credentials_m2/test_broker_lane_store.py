"""#913 L1d-0 (rulings Q5 and Q10; C-2.7, C-2.9, C-3.2): the order lane's own credential store lives
inside M2. The lane's binder (`SecretsBundle.lane_signing`) takes the lane's own audit writer and
has M2 build the store on the lane's loop, over a small pool of its own that M2 alone holds and
counts, and frees when the signing closes; the start-up self-check proves the binding and reads
the lane's store once, with nothing recorded, decrypted or counted as a borrow. On L3b's two-loop
rig: bounded waits, no sleeps, fixed vectors."""

from __future__ import annotations

import asyncio
import dataclasses
import threading
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest

from candleviewer import app
from candleviewer.admin import wiring
from candleviewer.admin.wiring import (
    SecretsBundle,
    build_audit_service,
    build_secrets_service,
    secrets_bundle,
)
from candleviewer.audit.service import AuditService
from candleviewer.secrets import _metrics as m
from candleviewer.secrets.errors import CredentialUnavailable, SigningLoopMismatch
from candleviewer.secrets.service import LOOP_STORE_CONNECTIONS, SecretsService
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Settings
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.unit.credentials_m2.test_broker_two_loops import BORROWED, FAILED, MSG, _Rig, rig
from tests.unit.exchange.bybit.test_rate_limit_two_loops import JOIN_S, _on

__all__ = ["rig"]

Release = Callable[[], Awaitable[None]]


class _Writer:
    """The lane's own audit writer (`LaneAuditWriter`): each durable append, noted."""

    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **columns: Any) -> None:
        self.emitted.append((action, columns))

    async def emit_keyed(self, action: str, name: str, **columns: Any) -> None:
        raise AssertionError("M2 writes no keyed record")


class _Pools:
    """The root's lane store factory: hands out a store (the rig's lane side), noting the bound
    M2 asks for and the thread, and each dispose of the pool: its thread, and whether the lane's
    I/O (the last of `ios`) was closed by then. Each of `faults` spoils one dispose: "raise"
    fails it, "stall" parks it until cancelled."""

    def __init__(self, store: Any, ios: list[Any] | None = None) -> None:
        self.store, self.ios, self.faults = store, ios, list[str]()
        self.built = list[tuple[int, threading.Thread]]()
        self.released = list[tuple[threading.Thread, bool | None]]()

    def __call__(self, connections: int) -> tuple[Any, Release]:
        self.built.append((connections, threading.current_thread()))

        async def release() -> None:
            closed = self.ios[-1].closed if self.ios else None
            fault = self.faults.pop(0) if self.faults else ""
            if fault == "raise":
                raise RuntimeError("the pool's dispose failed")
            if fault == "stall":
                await asyncio.Event().wait()  # never set: only a bound ends it
            self.released.append((threading.current_thread(), closed))

        return self.store, release


def _pools_in_use() -> float:
    return float(m.credential_loop_pools._value.get())  # the gauge's only read in a test


def _borrows() -> float:
    counted = m.credential_borrow_total.labels
    return float(
        sum(counted(stage="exchange_adapter", result=r)._value.get() for r in ("ok", "error"))
    )


def _bound(rig: _Rig, pools: _Pools, writer: _Writer) -> Any:
    bind = secrets_bundle(rig.svc, loop_store=pools).lane_signing
    return rig.lane.run(_on(lambda: bind(audit=writer)))


class _Down:
    """A lane store over a pool that cannot connect: each read raises, as a refused dial does."""

    def __init__(self) -> None:
        self.reads = 0

    async def get(self, key_id: Any, env: str) -> None:
        self.reads += 1
        raise ConnectionRefusedError("the lane's pool cannot connect")


def _mark(rig: _Rig) -> tuple[int, float]:
    return len(rig.log), _borrows()


def _since(rig: _Rig, writer: _Writer, mark: tuple[int, float]) -> tuple[Any, ...]:
    """What happened since `mark`: the lane's store and sink calls and any decrypt the rig
    logged, the records the lane's writer appended, and the borrows counted."""
    logged, borrows = mark
    return rig.log[logged:], writer.emitted, _borrows() - borrows


def test_the_lane_binding_builds_its_own_bounded_store_on_the_lane_and_counts_it(rig: _Rig) -> None:
    """Q10: the store is built by M2 on the lane's loop, only there (never off a loop), at M2's
    bound, counted while M2 holds it; a lane signing reads it there and writes its record ahead
    through the lane's own writer with M2's columns (C-2.9)."""
    pools, writer, before = _Pools(rig.sides["lane"], rig.ios), _Writer(), _pools_in_use()
    bind = secrets_bundle(rig.svc, loop_store=pools).lane_signing
    with pytest.raises(RuntimeError, match="no running event loop"):
        bind(audit=writer)
    assert (pools.built, _pools_in_use()) == ([], before)
    signing = rig.lane.run(_on(lambda: bind(audit=writer)))
    on_lane = rig.lane.run(_on(threading.current_thread))
    assert (pools.built, _pools_in_use()) == ([(LOOP_STORE_CONNECTIONS, on_lane)], before + 1)
    assert LOOP_STORE_CONNECTIONS <= 4  # small: one read per signing
    logged = len(rig.log)
    rig.lane.run(signing.borrower.sign(rig.key_id, MSG, purpose="sign_rest"))
    assert rig.log[logged] == ("lane", "get")
    ((action, columns),) = writer.emitted
    assert (action, columns["actor_label"], columns["object_id"]) == (
        BORROWED, "system:exchange_adapter", str(rig.key_id)
    )  # fmt: skip
    rig.lane.run(signing.aclose())
    assert (pools.released, _pools_in_use()) == ([(on_lane, True)], before)


def test_aclose_alone_frees_the_pool_on_the_lane_once_closed_and_the_gauge_falls(
    rig: _Rig,
) -> None:
    """M-1 (Q10): the one close frees the pool M2 built: the signing is closed first, so no
    signing reads a freed store, then the pool is disposed of on the lane, and counted no more."""
    pools, before = _Pools(rig.sides["lane"], rig.ios), _pools_in_use()
    signing = _bound(rig, pools, _Writer())
    assert _pools_in_use() == before + 1
    rig.lane.run(signing.aclose())
    on_lane = rig.lane.run(_on(threading.current_thread))
    assert (pools.released, _pools_in_use()) == ([(on_lane, True)], before)


def test_a_second_aclose_frees_nothing_more(rig: _Rig) -> None:
    """M-1: `aclose` is idempotent: the pool is disposed of once and counted down once."""
    pools, before = _Pools(rig.sides["lane"], rig.ios), _pools_in_use()
    signing = _bound(rig, pools, _Writer())
    for _ in range(2):
        rig.lane.run(signing.aclose())
    assert (len(pools.released), _pools_in_use()) == (1, before)


def test_a_signing_after_aclose_is_refused_with_nothing_read(rig: _Rig) -> None:
    """M-1: once closed, the binding signs nothing: `signing_loop_mismatch`, before any read."""
    signing = _bound(rig, _Pools(rig.sides["lane"], rig.ios), _Writer())
    rig.lane.run(signing.aclose())
    logged = len(rig.log)
    with pytest.raises(SigningLoopMismatch, match=r"^signing_loop_mismatch$"):
        rig.lane.run(signing.borrower.sign(rig.key_id, MSG, purpose="sign_rest"))
    assert rig.log[logged:] == []


def test_a_signing_parked_in_its_read_while_aclose_runs_is_refused_at_the_fence(
    rig: _Rig,
) -> None:
    """L-1 (C-2.9): a signing past its loop check whose binding closes, and its pool is freed,
    while it reads is refused at the fence after its record, `signing_loop_mismatch`: the record
    is closed as failed, nothing is decrypted, and no MAC is returned."""
    writer, lane = _Writer(), rig.sides["lane"]
    signing = _bound(rig, _Pools(lane, rig.ios), writer)
    parked = lane.park("get")
    pending = rig.lane.start(signing.borrower.sign(rig.key_id, MSG, purpose="sign_rest"))
    assert parked.wait(JOIN_S)
    rig.lane.run(signing.aclose())
    lane.release("get")
    with pytest.raises(SigningLoopMismatch, match=r"^signing_loop_mismatch$"):
        pending.result(JOIN_S)
    assert [action for action, _ in writer.emitted] == [BORROWED, FAILED]
    assert writer.emitted[1][1]["after_state"]["reason"] == "signing_loop_mismatch"
    assert ("lane", "open") not in rig.log


def test_an_aclose_from_another_loop_closes_and_frees_nothing(rig: _Rig) -> None:
    """Q10: from another loop the close is refused before anything is closed or freed."""
    pools, before = _Pools(rig.sides["lane"], rig.ios), _pools_in_use()
    signing = _bound(rig, pools, _Writer())
    with pytest.raises(SigningLoopMismatch, match=r"^signing_loop_mismatch$"):
        rig.serving.run(signing.aclose())
    assert (pools.released, rig.ios[-1].closed, _pools_in_use()) == ([], False, before + 1)
    rig.lane.run(signing.aclose())


def test_a_failed_dispose_raises_and_keeps_the_pool_counted_for_the_next_aclose(
    rig: _Rig,
) -> None:
    """Minor 5: the gauge falls only once the pool is disposed of; a dispose that fails raises
    from `aclose` and leaves the pool held and counted, and the next `aclose` frees it."""
    pools, before = _Pools(rig.sides["lane"], rig.ios), _pools_in_use()
    signing, pools.faults[:] = _bound(rig, pools, _Writer()), ["raise"]
    with pytest.raises(RuntimeError, match="dispose failed"):
        rig.lane.run(signing.aclose())
    assert (pools.released, _pools_in_use()) == ([], before + 1)
    rig.lane.run(signing.aclose())
    assert (len(pools.released), _pools_in_use()) == (1, before)


def test_a_stalled_dispose_ends_at_m2s_bound_and_the_next_aclose_frees_the_pool(
    rig: _Rig,
) -> None:
    """Nit 14: the dispose is bounded as the close's own waits are (M2's `io_timeout_s`; 0 here,
    so a dispose that waits at all is past it, with no time passing); past it, as a failed one.
    The `TimeoutError` is caught on the lane, so it is M2's bound's, never this test's wait."""
    pools, before = _Pools(rig.sides["lane"], rig.ios), _pools_in_use()
    signing, pools.faults[:] = _bound(rig, pools, _Writer()), ["stall"]
    rig.broker._timeout = 0.0

    async def closing() -> str:
        try:
            await signing.aclose()
        except TimeoutError:
            return "timed out"
        return "closed"

    assert rig.lane.run(closing()) == "timed out"
    assert (pools.released, _pools_in_use()) == ([], before + 1)
    rig.lane.run(signing.aclose())
    assert (len(pools.released), _pools_in_use()) == (1, before)


def test_a_destroy_on_the_serving_loop_fences_the_lanes_own_store_binding(rig: _Rig) -> None:
    """Q10's revoke: the store M2 built for the lane joins every fence as any loop's I/O does, so
    a destroy on the serving loop refuses its next signing and cancels its pending write."""
    lane = rig.sides["lane"]
    signing = _bound(rig, _Pools(lane), _Writer())
    lane.park("touch")  # its write of the key stalls in flight
    rig.lane.run(signing.borrower.sign(rig.key_id, MSG, purpose="sign_rest"))
    (write,) = rig.ios[-1].touches.values()
    rig.serving.run(rig.broker.destroy(rig.key_id))
    with pytest.raises(CredentialUnavailable, match=r"^credential_unavailable$"):
        rig.lane.run(signing.borrower.sign(rig.key_id, MSG, purpose="sign_rest"))
    rig.lane.run(asyncio.wait([write], timeout=JOIN_S))
    assert write.cancelled()
    rig.lane.run(signing.aclose())


def test_the_self_check_reads_one_absent_row_through_the_lanes_store_and_nothing_more(
    rig: _Rig,
) -> None:
    """M-2 (Q5): with M2 up, the start-up self-check reads a key no row holds, once, through the
    lane's own store, so its pool must connect for the lane to start; the missing row passes, and
    nothing is recorded, decrypted or counted as a borrow (a nil key borrowed would count
    `cv_credential_borrow_total{result="error"}`, an operator's error rate)."""
    writer = _Writer()
    signing, mark = _bound(rig, _Pools(rig.sides["lane"]), writer), _mark(rig)
    rig.lane.run(signing.self_check())
    assert _since(rig, writer, mark) == ([("lane", "get")], [], 0)


def test_the_self_check_on_another_loop_is_refused_before_anything_is_read(rig: _Rig) -> None:
    """M-2: off its loop, `signing_loop_mismatch`, as a signing there would be: nothing done."""
    writer = _Writer()
    signing, mark = _bound(rig, _Pools(rig.sides["lane"]), writer), _mark(rig)
    with pytest.raises(SigningLoopMismatch, match=r"^signing_loop_mismatch$"):
        rig.serving.run(signing.self_check())
    assert _since(rig, writer, mark) == ([], [], 0)


def test_the_self_check_after_aclose_is_refused_before_anything_is_read(rig: _Rig) -> None:
    """M-2: once closed, `signing_loop_mismatch`, as a signing would be: nothing done."""
    writer = _Writer()
    signing = _bound(rig, _Pools(rig.sides["lane"]), writer)
    rig.lane.run(signing.aclose())
    mark = _mark(rig)
    with pytest.raises(SigningLoopMismatch, match=r"^signing_loop_mismatch$"):
        rig.lane.run(signing.self_check())
    assert _since(rig, writer, mark) == ([], [], 0)


def _degraded(rig: _Rig, writer: _Writer) -> Any:
    """A lane binding of an M2 with no broker (degraded: every signing is `kek_unavailable`)."""
    bind = secrets_bundle(SecretsService(), loop_store=_Pools(rig.sides["lane"])).lane_signing
    return rig.lane.run(_on(lambda: bind(audit=writer)))


def test_the_self_check_while_m2_is_degraded_still_refuses_another_loop(rig: _Rig) -> None:
    """M-2 (a): the loop check needs no broker, so a mis-wired lane fails its start while M2 is
    degraded too, from the binding's own I/O, with nothing done."""
    writer = _Writer()
    signing, mark = _degraded(rig, writer), _mark(rig)
    with pytest.raises(SigningLoopMismatch, match=r"^signing_loop_mismatch$"):
        rig.serving.run(signing.self_check())
    assert _since(rig, writer, mark) == ([], [], 0)


def test_the_self_check_while_m2_is_degraded_reads_nothing_on_its_loop(rig: _Rig) -> None:
    """M-2 (b), degraded: nothing signs until the restart that binds the lane again (M2 starts
    before the OMS and publishes its broker only in `start()`), so there is no read to prove."""
    writer = _Writer()
    signing, mark = _degraded(rig, writer), _mark(rig)
    rig.lane.run(signing.self_check())
    assert _since(rig, writer, mark) == ([], [], 0)


def test_a_lane_store_that_raises_fails_the_self_check_store_unavailable(rig: _Rig) -> None:
    """M-2 (b): a read that fails is M2's store outage, `store_unavailable`, as on a signing."""
    store, writer = _Down(), _Writer()
    signing, mark = _bound(rig, _Pools(store), writer), _mark(rig)
    with pytest.raises(CredentialUnavailable, match=r"^store_unavailable$"):
        rig.lane.run(signing.self_check())
    assert (store.reads, _since(rig, writer, mark)) == (1, ([], [], 0))


def test_a_lane_store_that_stalls_past_the_bound_fails_the_self_check_store_unavailable(
    rig: _Rig,
) -> None:
    """M-2 (b): the read is bounded as every lane read is (M2's `io_timeout_s`; 0 here, so a read
    that waits at all is past it, with no time passing): a stall is `store_unavailable`."""
    writer, lane = _Writer(), rig.sides["lane"]
    signing = _bound(rig, _Pools(lane), writer)
    lane.park("get")  # never released: only the bound ends the read
    rig.broker._timeout = 0.0
    mark = _mark(rig)
    with pytest.raises(CredentialUnavailable, match=r"^store_unavailable$"):
        rig.lane.run(signing.self_check())
    assert _since(rig, writer, mark) == ([("lane", "get")], [], 0)


@pytest.mark.parametrize("given", ["service", "writer"])
def test_a_lane_bound_to_the_serving_loops_audit_writer_is_refused(given: str) -> None:
    """L3b's identity refusal, kept: the lane's writer is never the serving loop's, the service or
    its writer, so the binding is refused before any store is built."""
    served, pools = AuditService(None), _Pools(InMemoryCredentialStore())
    cast(Any, served)._writer = writer = _Writer()  # started: it has a writer
    store = InMemoryCredentialStore()
    bind = build_secrets_service(store, store, served, loop_store=pools).lane_signing
    with pytest.raises(ValueError, match="never the serving loop's"):
        bind(audit=cast(Any, served if given == "service" else writer))
    assert pools.built == []


def test_the_bundle_binds_the_lane_through_lane_signing_alone() -> None:
    """L-3 (C-3.2, Q10): M2 builds the lane's store, so the bundle offers no binder that takes one
    (L3b's `loop_signing` is retired): its one lane binder takes the lane's audit writer alone."""
    binders = [f.name for f in dataclasses.fields(SecretsBundle) if f.name.endswith("_signing")]
    assert (binders, hasattr(wiring, "LoopSigningBinder")) == (["lane_signing"], False)


async def test_m2_refuses_a_lane_store_that_is_the_serving_loops() -> None:
    """Minor 2 (Q10), as L3b's identity refusals: a factory that hands M2 the serving loop's own
    store is a wiring fault, refused at the bind, before the store is counted, read or used."""
    store, before = InMemoryCredentialStore(), _pools_in_use()
    bind = build_secrets_service(store, store, loop_store=_Pools(store)).lane_signing
    with pytest.raises(ValueError, match="never the serving loop's"):
        bind(audit=_Writer())
    assert _pools_in_use() == before


def test_a_lane_binding_with_no_store_factory_wired_is_refused(rig: _Rig) -> None:
    """With no lane store wired (a bundle a test builds), nothing is bound and nothing counted."""
    before, bind = _pools_in_use(), secrets_bundle(rig.svc).lane_signing
    with pytest.raises(RuntimeError, match="no loop credential store is wired"):
        rig.lane.run(_on(lambda: bind(audit=_Writer())))
    assert _pools_in_use() == before


async def test_the_root_hands_m2_a_factory_of_a_small_pool_of_the_lanes_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Q10 at the root: on the real backend, `_build_secrets` hands M2 the lane store's factory,
    never a store; M2 builds it when it binds, on that loop: a pool of its own (`oms-secrets` in
    `pg_stat_activity`), apart from the serving store's, bounded at M2's ask with no overflow,
    lazy (nothing connects), and disposed of by its release, never the serving one."""
    pools: list[Any] = []

    class Noted(SqlAlchemyRelationalRepository):
        def __init__(self, dsn: str, suffix: str = "api", **bound: int) -> None:
            super().__init__(dsn, suffix, **bound)
            self.suffix, self.bound, self.disposed = suffix, bound, False
            pools.append(self)

        async def dispose(self) -> None:
            self.disposed = True
            await super().dispose()

    monkeypatch.setattr(app, "SqlAlchemyRelationalRepository", Noted)
    bundle = app._build_secrets(Settings(storage_backend="real"), build_audit_service())
    assert [pool.suffix for pool in pools] == ["secrets"]  # the serving store's alone
    signing = bundle.lane_signing(audit=_Writer())  # bound on this loop, as the lane binds
    serving, lane = pools
    bound = {"pool_size": LOOP_STORE_CONNECTIONS, "max_overflow": 0}
    assert (lane.suffix, lane.bound, serving.bound) == ("oms-secrets", bound, {})
    await signing.aclose()
    assert (lane.disposed, serving.disposed) == (True, False)
