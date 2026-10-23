"""Revoking a session closes its sockets with 4401 (US-ONB-009, QA #1634); a disabled user's
sockets get `bye user_disabled` and close 4403, no reconnect (23-ws-protocol.md §9.5, #2493). A
close that fails, in the hub or in the per-user close, is counted on one series and the closes
after it still run (#3497, #3635)."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any, cast, get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from prometheus_client import CollectorRegistry
from structlog.testing import capture_logs

from candleviewer.auth.metrics import export_auth_metrics
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from candleviewer.ws.gateway import _Connection
from candleviewer.ws.permissions import ConnectionAuthz, ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import (
    CLOSE_FAILURE_LOG_EVERY_S,
    CLOSE_TOKEN_EXPIRED,
    CLOSE_USER_DISABLED,
    EVICTION_LOG_EVERY_S,
    MAX_CLOSE_TASKS,
    REVOKED_MEMORY_S,
    Closer,
    RevocationHub,
    RevokedReason,
    bye_frame,
    user_disabled_bye,
    ws_revocation_close_failures_total,
    ws_revoked_total,
)
from tests.unit.ws._auth_rig import BASE_MS, Sock

_NOW_MS = 1_789_133_600_000
#: Every §9.5 reason except a disabled user keeps the session-revocation close (4401).
_NOT_DISABLED = [reason for reason in get_args(RevokedReason) if reason != "user_disabled"]


class _Socket:
    def __init__(self) -> None:
        self.closes: list[tuple[dict[str, Any], int]] = []

    async def close(self, frame: dict[str, Any], code: int) -> None:
        self.closes.append((frame, code))


def _dead_log_sink(
    monkeypatch: pytest.MonkeyPatch,
    exc: type[BaseException] = RuntimeError,
    module: str = "candleviewer.ws.revocation",
) -> None:
    """Make every log call of `module` (the hub's by default) raise `exc`, as a broken processor
    chain would."""

    class _Dead:
        def warning(self, *args: object, **kwargs: object) -> None:
            raise exc("log sink down")

        def error(self, *args: object, **kwargs: object) -> None:
            raise exc("log sink down")

    monkeypatch.setattr(f"{module}._log", lambda: _Dead())


async def test_revoke_user_disabled_sends_user_disabled_bye_and_closes_4403() -> None:
    hub = RevocationHub(wall_ms=lambda: _NOW_MS)
    sock = _Socket()
    hub.register("s1", sock.close)
    assert await hub.revoke("s1", "user_disabled") == 1
    assert sock.closes == [(user_disabled_bye(_NOW_MS), CLOSE_USER_DISABLED)]
    frame, code = sock.closes[0]
    assert (frame["p"]["code"], frame["p"]["reconnect"], code) == (4403, False, 4403)


@pytest.mark.parametrize("reason", _NOT_DISABLED)
async def test_revoke_other_reason_keeps_bye_and_close_4401(reason: str) -> None:
    hub = RevocationHub(wall_ms=lambda: _NOW_MS)
    sock = _Socket()
    hub.register("s1", sock.close)
    assert await hub.revoke("s1", reason) == 1
    assert sock.closes == [(bye_frame(reason), CLOSE_TOKEN_EXPIRED)]
    frame, code = sock.closes[0]
    assert (frame["p"]["code"], frame["p"]["reason"], code) == (4401, reason, 4401)


async def test_revoke_sends_bye_and_closes_4401_only_for_that_session() -> None:
    hub = RevocationHub()
    got: list[tuple[dict[str, Any], int]] = []
    other: list[int] = []

    async def closer(frame: dict[str, Any], code: int) -> None:
        got.append((frame, code))

    async def other_closer(frame: dict[str, Any], code: int) -> None:
        other.append(code)

    hub.register("s1", closer)
    hub.register("s2", other_closer)
    assert await hub.revoke("s1", "session_revoked") == 1
    assert got[0][1] == CLOSE_TOKEN_EXPIRED == 4401
    assert got[0][0]["t"] == "bye"
    assert got[0][0]["p"]["reconnect"] is False
    assert other == []


async def test_a_failing_socket_does_not_block_the_rest() -> None:
    hub = RevocationHub()
    closed: list[int] = []

    async def bad(frame: dict[str, Any], code: int) -> None:
        raise RuntimeError("socket gone")

    async def good(frame: dict[str, Any], code: int) -> None:
        closed.append(code)

    hub.register("s", bad)
    hub.register("s", good)
    with capture_logs() as logs:
        await hub.revoke("s")
    assert closed == [4401]
    assert [(e["log_level"], e["session_id"]) for e in logs] == [("error", "s")]  # and logged


async def test_unregistered_session_is_a_noop() -> None:
    assert await RevocationHub().revoke("nope") == 0


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


async def test_revoke_remembers_the_session_and_its_reason_with_no_socket_open() -> None:
    """#2739: a revocation that closes nothing is still remembered for an in-flight `auth`."""
    hub = RevocationHub()
    assert await hub.revoke("s1") == 0
    await hub.revoke("s2", "user_disabled")
    assert (hub.revoked_reason("s1"), hub.revoked_reason("s2")) == (
        "session_revoked",
        "user_disabled",
    )
    assert (hub.was_revoked("s1"), hub.was_revoked("other")) == (True, False)


async def test_a_revoked_id_is_remembered_until_remember_s_has_passed() -> None:
    clock = _Clock()
    hub = RevocationHub(remember_s=720.0, monotonic=clock)
    await hub.revoke("s1")
    clock.now += 719.999
    assert hub.was_revoked("s1")
    clock.now += 0.001  # exactly remember_s after the revocation
    assert not hub.was_revoked("s1")


async def test_a_repeat_revocation_renews_the_entry_and_its_reason() -> None:
    clock = _Clock()
    hub = RevocationHub(remember_s=10.0, max_remembered=2, monotonic=clock)
    await hub.revoke("a")
    await hub.revoke("b")
    clock.now += 5
    await hub.revoke("a", "user_disabled")  # now the newest entry
    await hub.revoke("c")  # over the cap: "b" is the oldest
    assert (hub.was_revoked("b"), hub.revoked_reason("a"), hub.was_revoked("c")) == (
        False,
        "user_disabled",
        True,
    )
    clock.now += 9.5  # 14.5 s after the first "a", 9.5 s after its renewal
    assert hub.was_revoked("a")


async def test_the_memory_forgets_the_oldest_past_its_cap() -> None:
    hub = RevocationHub(max_remembered=3, monotonic=_Clock())
    for session_id in ("a", "b", "c", "d"):
        await hub.revoke(session_id)
    assert [hub.was_revoked(s) for s in ("a", "b", "c", "d")] == [False, True, True, True]


async def test_revoke_remembers_before_it_closes_the_sockets() -> None:
    hub = RevocationHub()
    seen: list[bool] = []

    async def closer(frame: dict[str, Any], code: int) -> None:
        seen.append(hub.was_revoked("s1"))

    hub.register("s1", closer)
    assert await hub.revoke("s1") == 1
    assert seen == [True]


def test_the_default_memory_is_one_access_token_lifetime() -> None:
    assert REVOKED_MEMORY_S == ACCESS_TOKEN_TTL.total_seconds()


@pytest.mark.parametrize(
    "kwargs",
    [{"remember_s": 0.0}, {"remember_s": float("nan")}, {"remember_s": float("inf")},
     {"max_remembered": 0}, {"close_timeout_s": 0.0}, {"close_timeout_s": float("nan")}],
)  # fmt: skip
def test_the_memory_bounds_must_be_finite_and_positive(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="must be finite and > 0"):
        RevocationHub(**kwargs)  # type: ignore[arg-type]  # float/int kwargs by name


@settings(max_examples=200, deadline=None)
@given(
    steps=st.lists(
        st.tuples(st.sampled_from("abcdef"), st.integers(0, 6)), min_size=1, max_size=40
    ),
    cap=st.integers(1, 4),
)
async def test_the_memory_matches_a_bounded_ttl_model(
    steps: list[tuple[str, int]], cap: int
) -> None:
    """Never more than `cap` ids; an id is remembered exactly while its newest revocation is
    younger than `remember_s` and fewer than `cap` other ids were revoked after it."""
    clock = _Clock()
    hub = RevocationHub(remember_s=5.0, max_remembered=cap, monotonic=clock)
    model: dict[str, float] = {}  # id -> time of its newest revocation, oldest first
    for session_id, advance in steps:
        clock.now += advance
        await hub.revoke(session_id)
        model.pop(session_id, None)
        model[session_id] = clock.now
        model = {s: at for s, at in model.items() if at + 5.0 > clock.now}
        while len(model) > cap:
            model.pop(next(iter(model)))
        assert len(hub._revoked) <= cap
        assert {s for s in "abcdef" if hub.was_revoked(s)} == set(model)


async def test_a_later_revocation_never_downgrades_a_remembered_user_disabled() -> None:
    """§9.5: the disabled user's close is 4403; a repeat revocation must not turn it into 4401."""
    hub = RevocationHub(monotonic=_Clock())
    await hub.revoke("s1", "user_disabled")
    await hub.revoke("s1", "session_revoked")
    assert hub.revoked_reason("s1") == "user_disabled"
    await hub.revoke("s2", "session_revoked")
    await hub.revoke("s2", "user_disabled")  # an upgrade still lands
    assert hub.revoked_reason("s2") == "user_disabled"


def test_close_for_builds_the_bye_and_code_of_a_remembered_reason() -> None:
    hub = RevocationHub(wall_ms=lambda: _NOW_MS)
    assert hub.close_for("user_disabled") == (user_disabled_bye(_NOW_MS), CLOSE_USER_DISABLED)
    assert hub.close_for("session_revoked") == (bye_frame("session_revoked"), CLOSE_TOKEN_EXPIRED)


async def test_forgetting_a_live_id_at_the_cap_is_logged_at_most_once_a_minute() -> None:
    clock = _Clock()
    hub = RevocationHub(max_remembered=1, monotonic=clock)
    ids = ("sess-alpha-1", "sess-bravo-2", "sess-charlie-3", "sess-delta-4")
    with capture_logs() as logs:
        await hub.revoke(ids[0])
        await hub.revoke(ids[1])  # forgets the live first id: logged
        await hub.revoke(ids[2])  # forgets the second inside the minute: counted, not logged
        clock.now += EVICTION_LOG_EVERY_S
        await hub.revoke(ids[3])  # a minute later: logged again, with the running count
    warnings = [e for e in logs if e["log_level"] == "warning"]
    assert [e["evicted_total"] for e in warnings] == [1, 3]
    assert all(e["max_remembered"] == 1 for e in warnings)
    assert not any(i in repr(warnings) for i in ids)  # no session id in any key or value


async def test_a_default_hub_forgets_the_oldest_id_at_the_4097th_revocation() -> None:
    """The cap `create_app` runs with, since it passes none: 4096 ids, the oldest forgotten first.
    The literals are the point, so a smaller default or constant is a deliberate edit here."""
    hub = RevocationHub(monotonic=_Clock())
    ids = [f"s{n}" for n in range(4097)]
    for session_id in ids:
        await hub.revoke(session_id)
    assert (hub.was_revoked("s0"), hub.was_revoked("s1"), hub.was_revoked("s4096")) == (
        False,
        True,
        True,
    )
    assert sum(hub.was_revoked(session_id) for session_id in ids) == 4096


async def test_a_failing_log_sink_never_skips_the_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-2.12: the eviction warning runs before the closes; a raising sink must not skip them."""
    _dead_log_sink(monkeypatch)
    hub = RevocationHub(max_remembered=1, monotonic=_Clock())
    socket = _Socket()
    await hub.revoke("s0")
    hub.register("s1", socket.close)
    assert await hub.revoke("s1") == 1  # evicts the live "s0": the warning raises, the close runs
    assert [code for _, code in socket.closes] == [CLOSE_TOKEN_EXPIRED]


async def test_a_failed_close_whose_log_also_fails_never_skips_the_remaining_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.12: a double fault (a socket's close raises, then the log sink does too) must not leave
    the session's other sockets open on a revoked session. The failure is still counted."""
    attempts: list[str] = []
    survivor = _Socket()

    async def gone(frame: dict[str, Any], code: int) -> None:
        attempts.append("gone")
        raise RuntimeError("socket gone")

    async def alive(frame: dict[str, Any], code: int) -> None:
        attempts.append("alive")
        await survivor.close(frame, code)

    _dead_log_sink(monkeypatch)
    hub = RevocationHub()
    hub.register("s1", gone)
    hub.register("s1", alive)
    failures_before = ws_revocation_close_failures_total._value.get()
    assert await hub.revoke("s1") == 2  # both closes were attempted
    assert attempts == ["gone", "alive"]
    assert survivor.closes == [(bye_frame("session_revoked"), CLOSE_TOKEN_EXPIRED)]
    assert ws_revocation_close_failures_total._value.get() == failures_before + 1


@pytest.mark.parametrize("raised_by", ["closer", "failure_log"])
async def test_revoke_never_swallows_a_cancellation(
    raised_by: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CancelledError is a BaseException: neither the close handler nor the guard around the
    failure log may swallow it, whether the closer or the log sink raises it."""

    async def cancelled(frame: dict[str, Any], code: int) -> None:
        raise asyncio.CancelledError

    async def gone(frame: dict[str, Any], code: int) -> None:
        raise RuntimeError("socket gone")

    hub = RevocationHub()
    if raised_by == "closer":
        hub.register("s1", cancelled)
    else:
        _dead_log_sink(monkeypatch, asyncio.CancelledError)
        hub.register("s1", gone)  # its failure is logged, and the log sink raises the cancellation
    with pytest.raises(asyncio.CancelledError):
        await hub.revoke("s1")


async def test_a_repeat_revocation_of_a_disabled_user_still_closes_4403() -> None:
    """The sticky reason applies to the close a repeat revocation sends, not only to the memory."""
    hub = RevocationHub(wall_ms=lambda: _NOW_MS, monotonic=_Clock())
    await hub.revoke("s1", "user_disabled")
    socket = _Socket()
    hub.register("s1", socket.close)  # e.g. a socket that authenticated in the window
    assert await hub.revoke("s1", "session_revoked") == 1
    assert socket.closes == [(user_disabled_bye(_NOW_MS), CLOSE_USER_DISABLED)]


async def test_cancelling_revoke_mid_loop_still_closes_every_socket() -> None:
    """Fail closed (C-2.12): the close loop is a task the hub owns, so a cancelled caller sees
    its CancelledError while the revoked session's other sockets still get their close."""
    hub = RevocationHub()
    blocked, release = asyncio.Event(), asyncio.Event()
    survivor = _Socket()

    async def stalled(frame: dict[str, Any], code: int) -> None:
        blocked.set()
        await release.wait()

    hub.register("s1", stalled)
    hub.register("s1", survivor.close)
    caller = asyncio.create_task(hub.revoke("s1"))
    await blocked.wait()  # the first close is in flight, the second not yet attempted
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    tasks = set(hub._closing)
    assert (len(tasks), survivor.closes) == (1, [])  # still running, owned by the hub
    release.set()
    await asyncio.gather(*tasks)
    assert survivor.closes == [(bye_frame("session_revoked"), CLOSE_TOKEN_EXPIRED)]
    assert not hub._closing


async def test_a_close_that_never_returns_is_cut_off_and_the_next_one_runs() -> None:
    hub = RevocationHub(close_timeout_s=0.01)
    alive = _Socket()

    async def hung(frame: dict[str, Any], code: int) -> None:
        await asyncio.Event().wait()

    hub.register("s1", hung)
    hub.register("s1", alive.close)
    async with asyncio.timeout(5):  # fail fast, not hang, if the per-close bound regresses
        assert await hub.revoke("s1") == 2
    assert len(alive.closes) == 1
    assert not hub._closing


async def test_a_failed_close_task_is_logged_and_released() -> None:
    hub = RevocationHub()

    async def boom() -> None:
        raise RuntimeError("close task failed")

    task = asyncio.ensure_future(boom())
    hub._closing.add(task)
    await asyncio.wait([task])
    with capture_logs() as logs:
        hub._close_task_done(task)
    assert ([e["log_level"] for e in logs], hub._closing) == (["error"], set())


async def test_revoke_finishes_without_yielding_when_no_close_suspends() -> None:
    """A sealed close stays atomic with the revoke: closers that never suspend (the gateway's)
    have all run when revoke() is first driven, so no writer turn can flush the backlog first."""
    hub = RevocationHub()
    sock = _Socket()
    hub.register("s1", sock.close)
    with pytest.raises(StopIteration) as done:
        hub.revoke("s1").send(None)
    assert (done.value.value, len(sock.closes), len(hub._closing)) == (1, 1, 0)


async def test_closes_past_the_task_cap_run_inline_and_none_is_dropped() -> None:
    hub = RevocationHub(max_close_tasks=1)
    blocked, release = asyncio.Event(), asyncio.Event()
    inline = _Socket()
    tracked: list[int] = []

    async def stalled(frame: dict[str, Any], code: int) -> None:
        blocked.set()
        await release.wait()

    async def second(frame: dict[str, Any], code: int) -> None:
        await asyncio.sleep(0)  # suspends, so a task spawned for this close would be tracked now
        tracked.append(len(hub._closing))
        await inline.close(frame, code)

    hub.register("s1", stalled)
    hub.register("s2", second)
    first = asyncio.create_task(hub.revoke("s1"))
    await blocked.wait()
    assert await hub.revoke("s2") == 1  # the cap is reached: closed inline, in this caller
    assert (len(inline.closes), tracked) == (1, [1])  # only the first task was ever owned
    release.set()
    assert await first == 1
    assert not hub._closing


def test_the_defaults_bound_the_close_tasks_and_each_close() -> None:
    hub = RevocationHub()
    assert (hub._max_close_tasks, hub._close_timeout_s) == (256, 2.0)


#: A sample of the revoke-to-close latency (`count`, `sum`, `bucket`), read where Prometheus reads
#: it: a registry that serves `export_auth_metrics`. Before/after deltas: the series is global.
Scraped = Callable[..., float]


@pytest.fixture
def scraped() -> Iterator[Scraped]:
    registry = CollectorRegistry()
    collector = export_auth_metrics(registry, env="demo")

    def read(sample: str, **labels: str) -> float:
        name = f"auth_revocation_latency_seconds_{sample}"
        value = registry.get_sample_value(name, {"env": "demo", **labels})
        assert value is not None, f"{name} is not served"
        return value

    try:
        yield read
    finally:
        collector.close()


@pytest.mark.parametrize("max_close_tasks", [MAX_CLOSE_TASKS, 0])  # owned task; inline past cap
async def test_a_revoke_that_closes_sockets_is_one_scraped_latency_observation(
    scraped: Scraped, max_close_tasks: int
) -> None:
    """#3415 (SR-029): one observation per revocation that closes sockets, however many."""
    hub = RevocationHub(max_close_tasks=max_close_tasks)
    hub.register("s1", _Socket().close)
    hub.register("s1", _Socket().close)
    before = scraped("count")
    assert await hub.revoke("s1", "user_disabled") == 2
    assert scraped("count") == before + 1


async def test_the_latency_runs_from_the_revoke_to_the_last_close_on_the_hub_clock(
    scraped: Scraped,
) -> None:
    """Two closes of 3 s on the hub's clock are one 6 s observation, past SR-029's 5 s edge."""
    clock = _Clock()

    async def slow(frame: dict[str, Any], code: int) -> None:
        clock.now += 3.0

    hub = RevocationHub(monotonic=clock)
    hub.register("s1", slow)
    hub.register("s1", slow)
    before = [scraped("sum"), scraped("bucket", le="5.0"), scraped("bucket", le="10.0")]
    await hub.revoke("s1", "user_disabled")
    after = [scraped("sum"), scraped("bucket", le="5.0"), scraped("bucket", le="10.0")]
    # `sum` is a float on a series every test shares: approximately, not to the last bit.
    assert [a - b for a, b in zip(after, before, strict=True)] == pytest.approx([6.0, 0.0, 1.0])


async def test_a_revoke_that_closes_no_socket_observes_no_latency(scraped: Scraped) -> None:
    before = scraped("count")
    assert await RevocationHub().revoke("s1", "user_disabled") == 0
    assert scraped("count") == before


async def test_an_inline_batch_cut_off_by_its_cancelled_caller_is_still_one_observation(
    scraped: Scraped,
) -> None:
    """Past the task cap a batch closes in its caller, which the cascade bounds (2 s a publish):
    a cancel mid-batch still records the batch once, up to the cut-off (#3415)."""
    clock, entered = _Clock(), asyncio.Event()

    async def stalled(frame: dict[str, Any], code: int) -> None:
        clock.now += 3.0
        entered.set()
        await asyncio.Event().wait()  # never set: only the cancel ends it

    hub = RevocationHub(max_close_tasks=0, close_timeout_s=60.0, monotonic=clock)
    hub.register("s1", stalled)
    hub.register("s1", _Socket().close)
    before = [scraped("count"), scraped("sum")]
    caller = asyncio.create_task(hub.revoke("s1", "user_disabled"))
    await entered.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert [scraped("count") - before[0], scraped("sum") - before[1]] == [1.0, 3.0]


async def test_the_gateway_close_is_observed_once_sealed_before_its_socket_is_closed(
    scraped: Scraped,
) -> None:
    """What the series measures (#3415): the closer the gateway registers queues the `bye` and
    seals the connection without suspending, so the revoke is observed before the writer (not
    running here) closes the socket. The transport close is not in the series."""
    sock = Sock()
    conn = _Connection(
        cast(Any, sock),
        encoding="cv.v1.json",
        clock=lambda: 0.0,
        wall_ms=lambda: BASE_MS,
        auth_timeout_s=10.0,
    )
    hub = RevocationHub()
    hub.register("s1", conn.closer)
    before = scraped("count")
    with pytest.raises(StopIteration):
        hub.revoke("s1", "user_disabled").send(None)
    assert (conn.sealed, sock.codes, scraped("count")) == (True, [], before + 1)


def _observed(scraped: Scraped) -> list[float]:
    """`count` and `sum` of the series now, for a before/after delta: the series is global."""
    return [scraped("count"), scraped("sum")]


def _grew(scraped: Scraped, before: list[float]) -> list[float]:
    """How far `count` and `sum` have moved since `before`; compare `sum` with `pytest.approx`."""
    return [now - then for now, then in zip(_observed(scraped), before, strict=True)]


@pytest.mark.parametrize("reason", ["user_disabled", "session_revoked"])
async def test_a_revoke_is_one_scraped_latency_observation_whatever_its_reason(
    scraped: Scraped, reason: str
) -> None:
    """07 §9: a disable, a sign-out and a session or family revoke are all timed. The composition
    root's publisher narrows every revocation reason to these two (`app._hub_publisher`)."""
    hub = RevocationHub()
    hub.register("s1", _Socket().close)
    before = scraped("count")
    assert await hub.revoke("s1", reason) == 1
    assert scraped("count") == before + 1


async def test_a_close_that_raises_is_still_one_scraped_latency_observation(
    scraped: Scraped,
) -> None:
    """07 §9, the series' HELP and the hub's docstring: a failed close is timed too. This one
    raises after 3 s of the hub's clock, so the observation is those 3 s, not none."""
    clock = _Clock()

    async def fails(frame: dict[str, Any], code: int) -> None:
        clock.now += 3.0
        raise RuntimeError("socket gone")

    hub = RevocationHub(monotonic=clock)
    hub.register("s1", fails)
    before = _observed(scraped)
    with capture_logs():  # the failure is logged, as `test_a_failing_socket_does_not_block...`
        assert await hub.revoke("s1", "user_disabled") == 1
    assert _grew(scraped, before) == pytest.approx([1.0, 3.0])


async def test_a_close_cut_off_at_its_bound_is_still_one_scraped_latency_observation(
    scraped: Scraped,
) -> None:
    """The same for a close that reaches its bound: this one has used 2 s of the hub's clock and
    never returns, so the bound ends it and the observation is those 2 s."""
    clock = _Clock()

    async def hung(frame: dict[str, Any], code: int) -> None:
        clock.now += 2.0
        await asyncio.Event().wait()  # never set: only the bound ends it

    hub = RevocationHub(close_timeout_s=0.01, monotonic=clock)
    hub.register("s1", hung)
    before = _observed(scraped)
    with capture_logs():
        async with asyncio.timeout(5):  # fail fast, not hang, if the per-close bound regresses
            assert await hub.revoke("s1", "user_disabled") == 1
    assert _grew(scraped, before) == pytest.approx([1.0, 2.0])


# -- the disable's per-user close, `ConnectionRegistry.user_disabled` (#965 slice 7, #3440) ------

_USER = uuid.UUID(int=0x5701)
_OTHER_USER = uuid.UUID(int=0x5702)


def _user_registry(
    clock: Callable[[], float], *, monotonic: Callable[[], float] = time.monotonic
) -> ConnectionRegistry:
    """A registry whose services run on `clock` and whose memory and failure log run on
    `monotonic`. Its per-user close reads no principal."""

    async def resolve(user_id: uuid.UUID) -> PrincipalSnapshot:
        raise AssertionError("the per-user close resolves no principal")

    return ConnectionRegistry(
        resolve, lambda: _NOW_MS, SubscriptionServices(clock=clock), monotonic=monotonic
    )


def _connect(
    registry: ConnectionRegistry,
    closer: Closer,
    user: uuid.UUID = _USER,
    *,
    viewer: uuid.UUID | None = None,
) -> ConnectionAuthz:
    """A live socket of `user` that the per-user close ends through `closer`; with `viewer`,
    another user's socket viewing as `user` (#3085 S11)."""
    principal = PrincipalSnapshot(user, frozenset({"manager"}), frozenset())

    async def send(frame: dict[str, Any]) -> None:
        return None

    authz = ConnectionAuthz(principal, registry.services, viewer_user_id=viewer)
    registry.register(authz, send, None, closer)
    return authz


async def test_the_per_user_close_is_one_scraped_latency_observation_for_all_its_sockets(
    scraped: Scraped,
) -> None:
    """#3415, #965 slice 7: the per-user close is one observation on the series, however many
    sockets the user has: from its start to the last close, here two of 3 s on the registry's
    clock (`services.clock`)."""
    clock = _Clock()

    async def slow(frame: dict[str, Any], code: int) -> None:
        clock.now += 3.0

    registry = _user_registry(clock)
    _connect(registry, slow)
    _connect(registry, slow)
    before = _observed(scraped)
    assert await registry.user_disabled(_USER) == 2
    assert _grew(scraped, before) == pytest.approx([1.0, 6.0])


async def test_a_per_user_close_with_no_socket_observes_no_latency(scraped: Scraped) -> None:
    registry = _user_registry(_Clock())
    before = scraped("count")
    assert await registry.user_disabled(_USER) == 0
    assert scraped("count") == before


async def test_a_per_user_close_that_raises_is_still_one_scraped_latency_observation(
    scraped: Scraped,
) -> None:
    """A failed close is timed too, here after 3 s of the registry's clock."""
    clock = _Clock()

    async def fails(frame: dict[str, Any], code: int) -> None:
        clock.now += 3.0
        raise RuntimeError("socket gone")

    registry = _user_registry(clock)
    _connect(registry, fails)
    before = _observed(scraped)
    with capture_logs():  # the failure is logged (#3635)
        assert await registry.user_disabled(_USER) == 1
    assert _grew(scraped, before) == pytest.approx([1.0, 3.0])


async def test_a_per_user_close_cut_off_at_its_bound_is_still_one_scraped_latency_observation(
    scraped: Scraped,
) -> None:
    """A close that has used 2 s of the registry's clock and never returns is ended by its bound
    (`send_timeout_s`), and those 2 s are the observation."""
    clock = _Clock()

    async def hung(frame: dict[str, Any], code: int) -> None:
        clock.now += 2.0
        await asyncio.Event().wait()  # never set: only the bound ends it

    registry = _user_registry(clock)
    registry.send_timeout_s = 0.01
    _connect(registry, hung)
    before = _observed(scraped)
    with capture_logs():  # the cut-off is logged (#3635)
        async with asyncio.timeout(5):  # fail fast, not hang, if the per-close bound regresses
            assert await registry.user_disabled(_USER) == 1
    assert _grew(scraped, before) == pytest.approx([1.0, 2.0])


async def test_a_per_user_close_cut_off_by_its_caller_is_still_one_observation(
    scraped: Scraped,
) -> None:
    """The disable cascade bounds this step at 2 s and does not shield it: a cancel mid-batch
    still records the batch once, up to the cut-off."""
    clock, entered = _Clock(), asyncio.Event()

    async def stalled(frame: dict[str, Any], code: int) -> None:
        clock.now += 3.0
        entered.set()
        await asyncio.Event().wait()  # never set: only the cancel ends it

    registry = _user_registry(clock)
    registry.send_timeout_s = 60.0
    _connect(registry, stalled)
    _connect(registry, _Socket().close)
    before = _observed(scraped)
    caller = asyncio.create_task(registry.user_disabled(_USER))
    await entered.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert _grew(scraped, before) == pytest.approx([1.0, 3.0])


# -- a close that fails: one count, from the hub and from the per-user close (#3497, #3635) -----

#: The error line of a failed per-user close; the runbook's `ws revocation close failed` search
#: finds it beside the hub's own line.
_USER_CLOSE_FAILED = "ws revocation close failed; disabled user's socket may remain open"
_FAILURES = "ws_session_revocation_close_failures_total"


@pytest.fixture
def close_failures() -> Iterator[Callable[[], float]]:
    """The failed-close count read where Prometheus reads it, with `env` as its only label: a
    registry that serves `export_auth_metrics`. Before/after deltas: the counter is global."""
    registry = CollectorRegistry()
    collector = export_auth_metrics(registry, env="demo")

    def read() -> float:
        value = registry.get_sample_value(_FAILURES, {"env": "demo"})
        assert value is not None, f"{_FAILURES} is not served"
        return value

    try:
        yield read
    finally:
        collector.close()


async def _gone(frame: dict[str, Any], code: int) -> None:
    """A closer that raises, as one whose transport died under it would."""
    raise ConnectionResetError("the peer is gone")


def _record_releases(
    monkeypatch: pytest.MonkeyPatch, *authzs: ConnectionAuthz
) -> list[ConnectionAuthz]:
    """Each of `authzs` as the per-user close releases it, in order: `release_all` still runs."""
    released: list[ConnectionAuthz] = []

    def watch(authz: ConnectionAuthz) -> None:
        release_all = authz.release_all

        def spy() -> None:
            released.append(authz)
            release_all()

        monkeypatch.setattr(authz, "release_all", spy)

    for authz in authzs:
        watch(authz)
    return released


async def test_revoke_failed_and_cut_off_closes_each_count_one_failure(
    close_failures: Callable[[], float],
) -> None:
    """The hub feeds the series the per-user close feeds: a closer that raised and one cut off at
    `close_timeout_s` count one each, a close that went through counts none, and the closes after
    a failure still run."""
    hub = RevocationHub(close_timeout_s=0.01)
    alive = _Socket()

    async def hung(frame: dict[str, Any], code: int) -> None:
        await asyncio.Event().wait()  # never set: only the bound ends it

    hub.register("s1", _gone)
    hub.register("s1", hung)
    hub.register("s1", alive.close)
    before = close_failures()
    with capture_logs():  # each failure is logged
        async with asyncio.timeout(5):  # fail fast, not hang, if the per-close bound regresses
            assert await hub.revoke("s1") == 3
    assert (close_failures(), len(alive.closes)) == (before + 2, 1)


async def test_user_disabled_first_closer_raises_second_socket_closed_and_one_failure_counted(
    close_failures: Callable[[], float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pin (#3635): a per-user close that raises goes on to the user's other sockets. The
    second gets `bye user_disabled` and 4403, both connections are released, and the count rises
    by exactly one. The hub's counterpart is `test_a_failing_socket_does_not_block_the_rest`."""
    survivor = _Socket()
    registry = _user_registry(_Clock())
    first, second = _connect(registry, _gone), _connect(registry, survivor.close)
    released = _record_releases(monkeypatch, first, second)
    before = close_failures()
    with capture_logs():  # the failure is logged: see the log tests below
        assert await registry.user_disabled(_USER) == 2
    assert survivor.closes == [(user_disabled_bye(_NOW_MS), CLOSE_USER_DISABLED)]
    assert released == [first, second]
    assert close_failures() == before + 1


@pytest.mark.parametrize("viewer", [None, uuid.uuid4()], ids=["own", "viewing"])
async def test_user_disabled_whose_bye_cannot_be_built_still_closes_the_other_sockets(
    close_failures: Callable[[], float], monkeypatch: pytest.MonkeyPatch, viewer: uuid.UUID | None
) -> None:
    """Each socket's `bye` is built inside its own guard (#3635): a fault there is that
    close's failure, counted, and the user's next socket is still closed. The first is the
    user's own socket, or one viewing as the user, whose `bye` is built on its own branch
    (#3085 S11; the S11 re-check's R2-L1 pins both)."""
    first, survivor = _Socket(), _Socket()
    registry = _user_registry(_Clock())
    _connect(registry, first.close, viewer=viewer)
    _connect(registry, survivor.close)
    reads = iter([_NOW_MS, None, _NOW_MS])  # the memory's instant, then one per socket

    def clock_ms() -> int:
        if (now := next(reads)) is None:
            raise OverflowError("the wall clock failed")
        return now

    monkeypatch.setattr(registry, "_clock_ms", clock_ms)
    before = close_failures()
    with capture_logs():
        assert await registry.user_disabled(_USER) == 2
    assert (first.closes, len(survivor.closes)) == ([], 1)
    assert close_failures() == before + 1


async def test_user_disabled_closer_cut_off_at_bound_counts_one_failure(
    close_failures: Callable[[], float],
) -> None:
    """A close that never returns is ended by `send_timeout_s` and counts one failure, and the
    user's next socket is still closed."""

    async def hung(frame: dict[str, Any], code: int) -> None:
        await asyncio.Event().wait()  # never set: only the bound ends it

    survivor = _Socket()
    registry = _user_registry(_Clock())
    registry.send_timeout_s = 0.01
    _connect(registry, hung)
    _connect(registry, survivor.close)
    before = close_failures()
    with capture_logs():  # the cut-off is logged
        async with asyncio.timeout(5):  # fail fast, not hang, if the per-close bound regresses
            assert await registry.user_disabled(_USER) == 2
    assert (close_failures(), len(survivor.closes)) == (before + 1, 1)


async def test_user_disabled_all_closes_ok_counts_no_failure(
    close_failures: Callable[[], float],
) -> None:
    registry = _user_registry(_Clock())
    sockets = [_Socket(), _Socket()]
    for socket in sockets:
        _connect(registry, socket.close)
    before = close_failures()
    with capture_logs() as logs:
        assert await registry.user_disabled(_USER) == 2
    assert [len(socket.closes) for socket in sockets] == [1, 1]
    assert (close_failures(), [e for e in logs if e["log_level"] == "error"]) == (before, [])


async def test_user_disabled_failures_within_window_log_once(
    close_failures: Callable[[], float],
) -> None:
    """A failed per-user close is logged at most once per `CLOSE_FAILURE_LOG_EVERY_S` on the
    registry's monotonic clock, whichever user it was, with the registry's running total; every
    failure is counted. The window runs from the last line logged, not from the last failure."""
    clock = _Clock()
    registry = _user_registry(_Clock(), monotonic=clock)
    opened = clock.now
    before = close_failures()
    with capture_logs() as logs:
        _connect(registry, _gone)
        _connect(registry, _gone)
        await registry.user_disabled(_USER)  # two failures: the first is logged
        clock.now = opened + CLOSE_FAILURE_LOG_EVERY_S - 0.5
        _connect(registry, _gone, _OTHER_USER)
        await registry.user_disabled(_OTHER_USER)  # inside the window: counted, not logged
        clock.now = opened + CLOSE_FAILURE_LOG_EVERY_S
        _connect(registry, _gone, _OTHER_USER)
        await registry.user_disabled(_OTHER_USER)  # a window after the first line: logged again
    lines = [e for e in logs if e["event"] == _USER_CLOSE_FAILED]
    assert [(e["user_id"], e["failed_total"]) for e in lines] == [
        (str(_USER), 1),
        (str(_OTHER_USER), 4),
    ]
    assert [(e["log_level"], e["exc_info"]) for e in lines] == [("error", True)] * 2
    assert close_failures() == before + 4


async def test_user_disabled_dead_log_sink_still_closes_remaining_sockets(
    close_failures: Callable[[], float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.12: a double fault (a socket's close raises, then the log sink does too) must not leave
    the disabled user's other sockets open. The failure is still counted."""
    _dead_log_sink(monkeypatch, module="candleviewer.ws.permissions")
    survivor = _Socket()
    registry = _user_registry(_Clock())
    _connect(registry, _gone)
    _connect(registry, survivor.close)
    before = close_failures()
    assert await registry.user_disabled(_USER) == 2
    assert survivor.closes == [(user_disabled_bye(_NOW_MS), CLOSE_USER_DISABLED)]
    assert close_failures() == before + 1


async def test_user_disabled_cancellation_from_the_log_sink_propagates_after_the_count(
    close_failures: Callable[[], float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard around the failed-close log swallows a broken sink, never a cancellation: one the
    log sink raises propagates, and the failure it was logging is already counted. The hub's twin
    is `test_revoke_never_swallows_a_cancellation[failure_log]`."""
    _dead_log_sink(monkeypatch, asyncio.CancelledError, module="candleviewer.ws.permissions")
    registry = _user_registry(_Clock())
    _connect(registry, _gone)
    before = close_failures()
    with pytest.raises(asyncio.CancelledError):
        await registry.user_disabled(_USER)
    assert close_failures() == before + 1


async def test_user_disabled_cancelled_close_propagates_and_counts_nothing(
    close_failures: Callable[[], float],
) -> None:
    """The disable cascade bounds this step at 2 s and does not shield it. That cut is a
    cancellation, the step's failure and not a failed close: it propagates, uncounted and
    unlogged."""
    entered = asyncio.Event()

    async def stalled(frame: dict[str, Any], code: int) -> None:
        entered.set()
        await asyncio.Event().wait()  # never set: only the cancel ends it

    registry = _user_registry(_Clock())
    registry.send_timeout_s = 60.0
    _connect(registry, stalled)
    before = close_failures()
    with capture_logs() as logs:
        caller = asyncio.create_task(registry.user_disabled(_USER))
        await entered.wait()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
    assert close_failures() == before
    assert [e for e in logs if e["event"] == _USER_CLOSE_FAILED] == []


# -- a disabled viewer's viewing sockets, which the registry holds under their targets (#3085) ---

_VIEWER = uuid.UUID(int=0x5703)
_BYSTANDER = uuid.UUID(int=0x5704)  # another viewer of the same target


async def test_a_disabled_viewers_viewing_socket_gets_user_disabled_and_4403() -> None:
    """§9.5: a disabled user's every socket is closed, and the viewer is the user here. Its viewing
    socket is registered under its target (`register`), so the per-user close finds it by its
    viewer."""
    registry, viewing = _user_registry(_Clock()), _Socket()
    _connect(registry, viewing.close, _USER, viewer=_VIEWER)
    assert await registry.user_disabled(_VIEWER) == 1
    assert viewing.closes == [(user_disabled_bye(_NOW_MS), CLOSE_USER_DISABLED)]


async def test_a_disabled_viewers_sockets_on_two_targets_are_both_closed() -> None:
    registry, on_user, on_other = _user_registry(_Clock()), _Socket(), _Socket()
    _connect(registry, on_user.close, _USER, viewer=_VIEWER)
    _connect(registry, on_other.close, _OTHER_USER, viewer=_VIEWER)
    await registry.user_disabled(_VIEWER)
    assert (len(on_user.closes), len(on_other.closes)) == (1, 1)


async def test_a_disabled_viewers_viewing_socket_counts_as_a_user_disabled_revocation() -> None:
    """As the user's own sockets do: read before and after, as the counter is global."""
    registry = _user_registry(_Clock())
    _connect(registry, _Socket().close, _USER, viewer=_VIEWER)
    revoked = ws_revoked_total.labels(reason="user_disabled")
    before = revoked._value.get()
    await registry.user_disabled(_VIEWER)
    assert revoked._value.get() == before + 1


async def test_a_disabled_viewers_viewing_socket_leaves_the_registry() -> None:
    registry = _user_registry(_Clock())
    _connect(registry, _Socket().close, _USER, viewer=_VIEWER)
    await registry.user_disabled(_VIEWER)
    assert registry._conns == {}


async def test_a_disabled_viewers_viewing_socket_drops_its_closer() -> None:
    registry = _user_registry(_Clock())
    _connect(registry, _Socket().close, _USER, viewer=_VIEWER)
    await registry.user_disabled(_VIEWER)
    assert registry._closers == {}


async def test_a_disabled_viewers_close_leaves_the_targets_own_socket_open() -> None:
    """The target is not disabled: its own socket, registered under the same id, stays open and
    registered."""
    registry, own = _user_registry(_Clock()), _Socket()
    own_authz = _connect(registry, own.close, _USER)
    _connect(registry, _Socket().close, _USER, viewer=_VIEWER)
    await registry.user_disabled(_VIEWER)
    assert (own.closes, [entry[0] for entry in registry._conns[_USER]]) == ([], [own_authz])


async def test_a_disabled_viewers_close_leaves_another_viewers_socket_open() -> None:
    registry, bystander = _user_registry(_Clock()), _Socket()
    bystander_authz = _connect(registry, bystander.close, _USER, viewer=_BYSTANDER)
    _connect(registry, _Socket().close, _USER, viewer=_VIEWER)
    await registry.user_disabled(_VIEWER)
    assert (bystander.closes, [e[0] for e in registry._conns[_USER]]) == ([], [bystander_authz])


async def test_a_disabled_viewers_own_and_viewing_sockets_are_one_scraped_latency_observation(
    scraped: Scraped,
) -> None:
    """The one observation of the per-user close covers both kinds: here two closes of 3 s on the
    registry's clock, the viewer's own socket and the one viewing as another user."""
    clock = _Clock()

    async def slow(frame: dict[str, Any], code: int) -> None:
        clock.now += 3.0

    registry = _user_registry(clock)
    _connect(registry, slow, _VIEWER)
    _connect(registry, slow, _USER, viewer=_VIEWER)
    before = _observed(scraped)
    assert await registry.user_disabled(_VIEWER) == 2
    assert _grew(scraped, before) == pytest.approx([1.0, 6.0])


async def test_a_failed_close_of_a_disabled_viewers_viewing_socket_is_counted(
    close_failures: Callable[[], float],
) -> None:
    registry = _user_registry(_Clock())
    _connect(registry, _gone, _USER, viewer=_VIEWER)
    before = close_failures()
    with capture_logs():  # the failure is logged (#3635)
        assert await registry.user_disabled(_VIEWER) == 1
    assert close_failures() == before + 1


async def test_a_failed_close_of_a_viewing_socket_is_logged_for_the_disabled_viewer() -> None:
    """The line names the user that was disabled, the viewer, not the target the socket held."""
    registry = _user_registry(_Clock())
    _connect(registry, _gone, _USER, viewer=_VIEWER)
    with capture_logs() as logs:
        await registry.user_disabled(_VIEWER)
    (line,) = [e for e in logs if e["event"] == _USER_CLOSE_FAILED]
    assert line["user_id"] == str(_VIEWER)
