"""Revoking a session closes its sockets with 4401 (US-ONB-009, QA #1634); a disabled user's
sockets get `bye user_disabled` and close 4403, no reconnect (23-ws-protocol.md §9.5, #2493)."""

from __future__ import annotations

import asyncio
from typing import Any, get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from candleviewer.ws.revocation import (
    CLOSE_TOKEN_EXPIRED,
    CLOSE_USER_DISABLED,
    EVICTION_LOG_EVERY_S,
    REVOKED_MEMORY_S,
    RevocationHub,
    RevokedReason,
    bye_frame,
    user_disabled_bye,
    ws_revocation_close_failures_total,
)

_NOW_MS = 1_789_133_600_000
#: Every §9.5 reason except a disabled user keeps the session-revocation close (4401).
_NOT_DISABLED = [reason for reason in get_args(RevokedReason) if reason != "user_disabled"]


class _Socket:
    def __init__(self) -> None:
        self.closes: list[tuple[dict[str, Any], int]] = []

    async def close(self, frame: dict[str, Any], code: int) -> None:
        self.closes.append((frame, code))


def _dead_log_sink(
    monkeypatch: pytest.MonkeyPatch, exc: type[BaseException] = RuntimeError
) -> None:
    """Make every log call of the hub raise `exc`, as a broken processor chain would."""
    import candleviewer.ws.revocation as revocation

    class _Dead:
        def warning(self, *args: object, **kwargs: object) -> None:
            raise exc("log sink down")

        def error(self, *args: object, **kwargs: object) -> None:
            raise exc("log sink down")

    monkeypatch.setattr(revocation, "_log", lambda: _Dead())


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
    await hub.revoke("s")
    assert closed == [4401]


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
     {"max_remembered": 0}],
)  # fmt: skip
def test_the_memory_bounds_must_be_finite_and_positive(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="remember_s must be finite and > 0"):
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
