"""#913 L1d-1 (rulings Q5 and Q10; C-2.7, C-2.9, C-3.2): the order lane's own credential store lives
inside M2. The lane's binder (`SecretsBundle.lane_signing`) takes the lane's own audit writer and
has M2 build the store on the lane's loop, over a small pool of its own that M2 alone holds,
counts and releases after the signing closes; the start-up self-check proves the binding with
nothing read, recorded, decrypted or counted as a borrow. On L3b's two-loop rig: bounded waits,
no sleeps, fixed vectors."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest

from candleviewer import app
from candleviewer.admin.wiring import build_audit_service, build_secrets_service, secrets_bundle
from candleviewer.audit.service import AuditService
from candleviewer.secrets import _metrics as m
from candleviewer.secrets.errors import CredentialUnavailable, SigningLoopMismatch
from candleviewer.secrets.service import LOOP_STORE_CONNECTIONS
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Settings
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.unit.credentials_m2.test_broker_two_loops import BORROWED, MSG, _Rig, rig
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
    """The root's lane store factory: hands out the rig's lane side as the store, noting the
    bound M2 asks for and the thread, and each release of the pool and its thread."""

    def __init__(self, store: Any) -> None:
        self.store, self.built = store, list[tuple[int, threading.Thread]]()
        self.released = list[threading.Thread]()

    def __call__(self, connections: int) -> tuple[Any, Release]:
        self.built.append((connections, threading.current_thread()))

        async def release() -> None:
            self.released.append(threading.current_thread())

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


def test_the_lane_binding_builds_its_own_bounded_store_on_the_lane_and_counts_it(rig: _Rig) -> None:
    """Q10: the store is built by M2 on the lane's loop, only there (never off a loop), at M2's
    bound, counted while M2 holds it; a lane signing reads it there and writes its record ahead
    through the lane's own writer with M2's columns (C-2.9)."""
    pools, writer, before = _Pools(rig.sides["lane"]), _Writer(), _pools_in_use()
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
    rig.lane.run(signing.release())
    assert (pools.released, _pools_in_use()) == ([on_lane], before)


def test_its_pool_is_released_once_after_the_close_and_only_on_its_loop(rig: _Rig) -> None:
    """Q10: the release closes the signing first, so no signing reads a freed store, then frees
    the pool once, on the lane; from another loop it is refused with nothing closed or freed."""
    pools, before = _Pools(rig.sides["lane"]), _pools_in_use()
    signing = _bound(rig, pools, _Writer())
    with pytest.raises(SigningLoopMismatch, match=r"^signing_loop_mismatch$"):
        rig.serving.run(signing.release())
    assert pools.released == [] and not rig.ios[-1].closed
    for _ in range(2):  # idempotent
        rig.lane.run(signing.release())
    on_lane = rig.lane.run(_on(threading.current_thread))
    assert (pools.released, _pools_in_use(), rig.ios[-1].closed) == ([on_lane], before, True)
    with pytest.raises(SigningLoopMismatch):
        rig.lane.run(signing.borrower.sign(rig.key_id, MSG, purpose="sign_rest"))


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
    rig.lane.run(signing.release())


def test_the_self_check_does_nothing_on_its_loop_and_refuses_off_it_or_once_closed(
    rig: _Rig,
) -> None:
    """Q5: on its own loop the start-up self-check reads, records, decrypts and counts nothing (a
    nil key borrowed would count `cv_credential_borrow_total{result="error"}`, an operator's
    error rate); on another loop, or once closed, it is `signing_loop_mismatch`, as a signing
    there would be, before anything is read."""
    logged, borrows = len(rig.log), _borrows()
    rig.lane.run(_on(rig.signing.self_check))
    for refused_on in ("serving", "closed"):
        if refused_on == "closed":
            rig.lane.run(rig.signing.aclose())
        on = rig.serving if refused_on == "serving" else rig.lane
        with pytest.raises(SigningLoopMismatch, match=r"^signing_loop_mismatch$"):
            on.run(_on(rig.signing.self_check))
    assert (rig.log[logged:], _borrows()) == ([], borrows)


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
    await signing.release()
    assert (lane.disposed, serving.disposed) == (True, False)
