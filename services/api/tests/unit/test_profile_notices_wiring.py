"""#906 slice D3e (E28-T02; ADR-0040 Decision 3): a committed profile write tells its account's
sockets. `ProfileNotices` holds `{env}.profiles.*.changed` with `NEVER_DROP` and offers each
`ProfilesChanged` (24 Sec.9.2) to every authenticated socket as one `system` `account_notice` with
the reason `profiles.changed`, through `GatewayHub.broadcast_system`, whose `system_view` cuts it to
each socket's grants (23 Sec.15.9). The real `/ws` router and hub run on the test's loop behind fake
sockets (the SR-188 rig of `tests/unit/ws/test_system_topic_roles.py`); a frame the Owner receives,
or an offer a stand-in hub records, is the barrier, never a sleep. No network.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import structlog
from pydantic import SecretStr

from candleviewer.accounts.errors import AccountVersionConflictError
from candleviewer.accounts.profile_changes import ProfilesChanged, ProfileVersion
from candleviewer.app import create_app
from candleviewer.bus import Bus, QueuePolicy, TopicPattern
from candleviewer.main import _lifespan
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.profile_notices_wiring import (
    NOTICE_QUEUE_SIZE,
    ProfileNotices,
    SystemBroadcast,
    profiles_notice,
)
from candleviewer.profiles_wiring import BusProfileChanges, wire_profiles
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.account_profiles import (
    AccountProfileStoreStaleError,
    DefaultMove,
)
from candleviewer.storage.repositories.account_profiles_sqlalchemy import (
    SqlAlchemyAccountProfileStore,
)
from candleviewer.storage.repositories.accounts import OwnerScope
from tests.unit.accounts.test_profile_cache import _P, _row
from tests.unit.accounts.test_profile_repository import _NO
from tests.unit.test_main_lifespan_stop_order import _app, _Stops, _Task
from tests.unit.ws._seq_support import validate
from tests.unit.ws.test_system_filter import ACC_A, ACC_B
from tests.unit.ws.test_system_topic_roles import _DEADLINE_S, _as, _Rig, _Socket, _system

_PROTOCOL = Path(__file__).resolve().parents[4] / "docs" / "plan" / "23-ws-protocol.md"
_TS = 1_792_486_805_000_000  # a commit (`ts_event`), in microseconds
_SECONDS, _FAILED = "cv_profile_propagation_seconds", "cv_profile_notices_failed_total"


def _notice(account: UUID) -> dict[str, Any]:
    """ADR-0040 Decision 3's frame, written out here, never derived from the module."""
    return {
        "kind": "account_notice",
        "severity": "info",
        "reason": "profiles.changed",
        "message": "An account profile changed.",
        "exchange_account_ids": [str(account)],
    }


def _changed(account: UUID, *versions: int, ts: int = _TS) -> ProfilesChanged:
    """A write on `account`: one row, or a default move's two rows and the binding's version."""
    moved = len(versions) > 1
    return ProfilesChanged(
        exchange_account_id=account,
        change="default_moved" if moved else "updated",
        profiles=tuple(ProfileVersion(profile_id=uuid4(), version=v) for v in versions),
        binding_version=9 if moved else None,
        ts_event=ts,
    )


class _Hub:
    """A stand-in for the hub: it queues each body offered for the test to await, and answers the
    scripted number of sockets offered it (1 once the script ends), or raises."""

    def __init__(self, *answers: int | BaseException) -> None:
        self.answers = list(answers)
        self.offered: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def broadcast_system(self, body: dict[str, Any]) -> int:
        self.offered.put_nowait(body)
        answer = self.answers.pop(0) if self.answers else 1
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _bridge(hub: SystemBroadcast) -> tuple[Bus, ProfileNotices, Metrics]:
    """A started bridge on a bus of its own; its clock reads the commit + 1.25 s."""
    bus, metrics = Bus(), Metrics("demo")
    register_r0(metrics)
    notices = ProfileNotices(bus, "demo", hub, metrics, now_us=lambda: _TS + 1_250_000)
    notices.start()
    return bus, notices, metrics


async def _publish(bus: Bus, *events: ProfilesChanged) -> None:
    doorbell = BusProfileChanges(bus, "demo")  # D3a's adapter, the topics' one producer
    for event in events:
        await doorbell.changed(event)


async def _next(sock: _Socket) -> tuple[int, Any]:
    """`(s, p)` of the next `system` frame `sock` is sent; the frame passes the schema."""
    while (frame := await sock.sent.get()).get("ch") != "system":
        pass
    validate(frame)
    return frame["s"], frame["p"]


async def test_a_change_reaches_each_socket_that_may_view_its_account_and_no_other() -> None:
    """One frame per change, a move's two rows and binding included, exactly ADR-0040's: the Owner
    gets it whole, a Manager or a Viewer granted the account gets it, and a Manager granted another
    account only, or a principal with no role, gets nothing and takes no `s` (SR-188, SR-E29-10)."""
    rig = _Rig()
    bus, notices, _ = _bridge(rig.hub)
    async with asyncio.timeout(_DEADLINE_S):
        owner, manager, viewer = [
            await rig.connect(_as(uuid4(), role)) for role in ("owner", "manager", "viewer")
        ]
        other = await rig.connect(_as(uuid4(), "manager", accounts=(ACC_B,)))
        nobody = await rig.connect(_as(uuid4()))
        await _publish(bus, _changed(ACC_A, 6, 4), _changed(ACC_B, 5))  # a move, then a write
        whole = [await _next(owner) for _ in range(2)]
        cut = [await _system(sock) for sock in (owner, manager, viewer, other, nobody)]
        await notices.stop()
        await rig.close()
    assert whole == [(2, _notice(ACC_A)), (3, _notice(ACC_B))]  # `s` 1: the snap (§12.1, #4992)
    assert cut == [[], [(2, _notice(ACC_A))], [(2, _notice(ACC_A))], [(2, _notice(ACC_B))], []]


async def test_the_propagation_is_one_sample_per_change_offered_timed_from_its_commit() -> None:
    """From `ts_event` (24 Sec.9.2) to the hand-off, once per change whatever the number of sockets
    offered it; a change offered to none, or stamped after the clock's reading (a clock step), is
    no sample. Labelled `env` only, never an account."""
    hub = _Hub(0, 3, 2)
    bus, notices, metrics = _bridge(hub)
    late, exact = _changed(ACC_A, 5, ts=_TS + 1_250_001), _changed(ACC_B, 7, ts=_TS + 1_250_000)
    async with asyncio.timeout(_DEADLINE_S):
        await _publish(bus, _changed(ACC_A, 4), late, _changed(ACC_B, 6), exact)
        for _ in range(4):
            await hub.offered.get()
        await notices.stop()
    sample, env = metrics.registry.get_sample_value, {"env": "demo"}
    assert (sample(f"{_SECONDS}_count", env), sample(f"{_SECONDS}_sum", env)) == (2, 1.25)
    assert [sample(f"{_SECONDS}_bucket", env | {"le": le}) for le in ("1.0", "2.0")] == [1, 2]
    (family,) = [f for f in metrics.registry.collect() if f.name == _SECONDS]
    assert {label for s in family.samples for label in s.labels} == {"env", "le"}


async def test_an_offer_that_raises_is_logged_and_counted_and_the_next_change_still_goes() -> None:
    """After the commit, on the bridge's own task, so nothing reaches the writer: the line names the
    account and the error class, never the message (C-12.6), and the next change is offered."""
    hub = _Hub(RuntimeError("max_leverage_cap 25 on Scalper"))
    bus, notices, metrics = _bridge(hub)
    async with asyncio.timeout(_DEADLINE_S):
        with structlog.testing.capture_logs() as logs:
            await _publish(bus, _changed(ACC_A, 4), _changed(ACC_B, 5))
            offered = [await hub.offered.get() for _ in range(2)]
        await notices.stop()
    assert offered == [_notice(ACC_A), _notice(ACC_B)]
    assert logs == [
        {"event": "profile.notice_failed", "account_id": str(ACC_A), "error": "RuntimeError",
         "log_level": "warning"}
    ]  # fmt: skip
    assert metrics.registry.get_sample_value(_FAILED, {"env": "demo"}) == 1


async def test_an_item_that_is_no_change_is_counted_and_the_next_change_still_goes() -> None:
    """The topics' one producer sends `ProfilesChanged` alone; anything else on the pattern is
    counted and logged by its class, and the bridge keeps going (the security lens's R1S-01)."""
    hub = _Hub()
    bus, notices, metrics = _bridge(hub)
    async with asyncio.timeout(_DEADLINE_S):
        with structlog.testing.capture_logs() as logs:
            await bus.publish(BusProfileChanges(bus, "demo").topic(ACC_A), "not a change")
            await _publish(bus, _changed(ACC_B, 5))
            offered = await hub.offered.get()
        await notices.stop()
    assert offered == _notice(ACC_B)
    assert logs == [{"event": "profile.notice_failed", "error": "str", "log_level": "warning"}]
    assert metrics.registry.get_sample_value(_FAILED, {"env": "demo"}) == 1


async def test_a_bridge_that_stops_on_its_own_says_so_and_stop_says_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `get` that raises ends the task: it is logged by class at error, never silent; a
    cancellation by `stop` logs nothing (R1S-01), not even through the loop's exception handler,
    which asyncio calls for a done-callback that raises. The done-callback is registered at
    `start`, so it has run when `asyncio.wait` returns."""
    hub = _Hub()
    bus, notices, _ = _bridge(hub)
    assert notices._running is not None
    sub, task = notices._running

    async def broken() -> Any:
        raise RuntimeError("queue 7f3a gone")

    async with asyncio.timeout(_DEADLINE_S):
        with structlog.testing.capture_logs() as logs:
            await _publish(bus, _changed(ACC_A, 4))
            await hub.offered.get()  # the task waits in `get` again, already called
            monkeypatch.setattr(sub, "get", broken)  # so the wait after the next change raises
            await _publish(bus, _changed(ACC_B, 5))
            await asyncio.wait({task})
        await notices.stop()
    assert [(log["event"], log["error"], log["log_level"]) for log in logs] == [
        ("profile.notices_stopped", "RuntimeError", "error")
    ]
    _, calm, _ = _bridge(_Hub())
    assert calm._running is not None
    _, stopping = calm._running
    loop, raised = asyncio.get_running_loop(), list[dict[str, Any]]()
    monkeypatch.setattr(loop, "call_exception_handler", raised.append)
    async with asyncio.timeout(_DEADLINE_S):
        with structlog.testing.capture_logs() as stop_logs:
            await calm.stop()
    assert stopping.cancelled() and (stop_logs, raised) == ([], [])


async def test_a_cancellation_in_the_offer_ends_the_bridge_and_is_no_failure() -> None:
    """`except Exception`, never `BaseException`: a cancellation propagates, uncounted."""
    bus, notices, metrics = _bridge(_Hub(asyncio.CancelledError()))
    assert notices._running is not None
    _, task = notices._running
    async with asyncio.timeout(_DEADLINE_S):
        with structlog.testing.capture_logs() as logs:
            await _publish(bus, _changed(ACC_A, 4))
            await asyncio.wait({task})
        await notices.stop()
    assert task.cancelled() and logs == []
    assert metrics.registry.get_sample_value(_FAILED, {"env": "demo"}) == 0


async def test_start_holds_the_pattern_never_drop_once_and_stop_lets_go_of_it() -> None:
    """Writes are rare, so nothing is dropped: changes published while the bridge waits all go, in
    order. Stopped, it holds no queue for the bus's drain at shutdown to wait on, and hears nothing
    more."""
    hub = _Hub()
    bus, notices, _ = _bridge(hub)
    notices.start()  # a second start holds nothing more
    assert notices._running is not None
    sub, task = notices._running
    pattern = TopicPattern(env="demo", domain="profiles", symbol="*", detail="changed")
    assert (sub.pattern, sub.policy, sub.maxsize) == (
        pattern,
        QueuePolicy.NEVER_DROP,
        NOTICE_QUEUE_SIZE,
    )
    assert 0 < sub.maxsize  # a bound: asyncio reads 0 as unbounded (C-2.18)
    async with asyncio.timeout(_DEADLINE_S):
        await _publish(bus, *(_changed(a, 4) for a in (ACC_A, ACC_B, ACC_A)))  # none taken yet
        offered = [await hub.offered.get() for _ in range(3)]
        await notices.stop()
        await notices.stop()  # a second stop lets go of nothing more
        await _publish(bus, _changed(ACC_B, 5))
    assert offered == [_notice(a) for a in (ACC_A, ACC_B, ACC_A)]
    assert task.done() and hub.offered.empty() and await bus.drain(0) == {}


async def test_a_cancelled_stop_still_lets_go_of_the_pattern() -> None:
    """`stop` unsubscribes before its first await, so a `stop` cancelled while it waits for the
    task leaves no queue for the bus's drain at shutdown to wait on."""
    bus, notices, _ = _bridge(_Hub())
    stopping = asyncio.ensure_future(notices.stop())
    await asyncio.sleep(0)  # `stop` runs up to its wait for the task
    stopping.cancel()
    async with asyncio.timeout(_DEADLINE_S):
        await asyncio.wait({stopping})
    await _publish(bus, _changed(ACC_A, 4))
    assert stopping.cancelled() and await bus.drain(0) == {}


async def test_a_refused_or_idle_write_tells_no_socket_and_a_committed_one_its_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through the wired facade and the process's bus (D3a) to the hub: a stale `If-Match` and a
    move onto the profile that already is the default publish nothing (24 Sec.9.2), so the one
    notice the Owner gets is the committed write's."""

    async def update(self: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs["expected_version"] == 2:
            raise AccountProfileStoreStaleError
        return _row(version=4)

    async def move(self: Any, *args: Any, **kwargs: Any) -> Any:
        return DefaultMove(profile=_row(), previous=None, written=False, version=8)

    monkeypatch.setattr(SqlAlchemyAccountProfileStore, "update_profile", update)
    monkeypatch.setattr(SqlAlchemyAccountProfileStore, "set_default_profile", move)
    rig = _Rig()
    bus, notices, metrics = _bridge(rig.hub)
    real = Settings(environment=Environment.DEMO, storage_backend="real")
    wired = wire_profiles(real, metrics, bus)
    assert wired is not None
    repo, scope, account, pid = wired.repository, OwnerScope(uuid4()), _P.account_id, _P.profile_id
    async with asyncio.timeout(_DEADLINE_S):
        owner = await rig.connect(_as(uuid4(), "owner"))
        with pytest.raises(AccountVersionConflictError):
            await repo.update_profile(scope, account, pid, _P, expected_version=2, write_ahead=_NO)
        await repo.set_default_profile(
            scope, account, pid, expected_binding_version=8, write_ahead=_NO
        )
        await repo.update_profile(scope, account, pid, _P, expected_version=3, write_ahead=_NO)
        first, rest = await _next(owner), await _system(owner)
        await notices.stop()
        await rig.close()
    assert (first, rest) == ((2, _notice(account)), [])  # `s` 1: the snap (§12.1, #4992)


def test_the_reason_is_one_23_names_and_an_event_sent_at_info() -> None:
    """23 Sec.15.9's account notices, pinned as the OMS pins its `oms.account_*` reasons: the reason
    this producer sends is named there, and so are its event sentence and its severity (the contract
    PR's code lens, R1C-05), so neither can be dropped silently."""
    contract = _PROTOCOL.read_text(encoding="utf-8")
    paragraph = contract.split("**Account notices (SR-E29-10", 1)[1].split("\n\n", 1)[0]
    text = " ".join(paragraph.split())
    body = profiles_notice(ACC_A)
    assert body["reason"] in {w.strip("`(),.:") for w in text.split() if w.startswith("`")}
    sentence = f'A `{body["reason"]}` frame, sent with `severity: "{body["severity"]}"`'
    assert f"{sentence}, is an event and reports no state" in text


async def test_the_lifespan_starts_the_bridge_and_stops_it_before_the_bus_drains() -> None:
    """Its queue is a `NEVER_DROP` one, which the bus's drain in `stop_all` would wait on."""
    stops = _Stops()
    app = _app(stops)
    app.state.profile_notices = _Task("profile_notices", stops)
    async with _lifespan(app):
        assert stops.started.count("profile_notices") == 1
    assert stops.order.count("profile_notices") == 1
    assert stops.order.index("profile_notices") < stops.order.index("module:bus")


def test_create_app_wires_the_bridge_beside_the_profile_store_on_the_process_bus_and_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On the real backend, where profile writes publish (D3a), and on the wall clock in
    microseconds, as `ts_event` is; the fake backend has no store."""
    assert create_app(Settings()).state.profile_notices is None
    real = Settings(
        environment=Environment.TESTNET,
        storage_backend="real",
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
    )
    app = create_app(real)
    notices = app.state.profile_notices
    assert isinstance(notices, ProfileNotices)
    assert notices._bus is app.state.app_context.bus.bus and notices._hub is app.state.ws_hub
    assert notices.pattern.env == real.environment.value == "testnet"
    monkeypatch.setattr(time, "time_ns", lambda: 1_792_486_805_123_456_789)
    assert notices._now_us() == 1_792_486_805_123_456
