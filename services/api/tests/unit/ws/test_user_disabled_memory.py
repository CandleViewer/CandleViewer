"""#3413 (SR-029, UL1-E2): the registry remembers a disabled user for one access-token lifetime.

The per-user close (`ConnectionRegistry.user_disabled`) ends the sockets registered at that
instant. A socket whose `auth` read its principal before it, and registers after it, must read
its principal again (SR-189) and be refused when its access token was issued at or before the
disable. The memory is bounded (C-2.18). Fake clocks only: the disable instant is the registry's
`clock_ms`, the expiry its `monotonic`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from candleviewer.ws.permissions import DISABLED_MEMORY_S, ConnectionAuthz, ConnectionRegistry

M, OTHER = uuid.UUID(int=0x3413), uuid.UUID(int=0x3414)
D_MS = 1_789_132_262_000  # the disable instant, on the registry's wall clock
LIFETIME_MS = int(DISABLED_MEMORY_S * 1000)


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


async def _deny_all(uid: uuid.UUID) -> PrincipalSnapshot:
    return PrincipalSnapshot(uid, frozenset(), frozenset())


async def _noop(_frame: dict[str, Any]) -> None:
    return None


def _registry(clock: _Clock | None = None, **memory: Any) -> ConnectionRegistry:
    return ConnectionRegistry(_deny_all, lambda: D_MS, monotonic=clock or _Clock(), **memory)


def _expiry(issued_ms: int) -> int:
    """The expiry of an access token issued at `issued_ms` (`access_token_expires_at`)."""
    return issued_ms + LIFETIME_MS


async def test_a_recheck_after_the_per_user_close_reads_the_principal_again() -> None:
    """AC2: the close ran after the socket read its principal and before it registered, so
    SR-189's re-check reads it again: the store's deny-all for a user who is not active."""
    reads: list[uuid.UUID] = []
    full = PrincipalSnapshot(M, frozenset({"manager"}), frozenset({Permission.POSITIONS_READ}))

    async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
        reads.append(uid)
        return full if len(reads) == 1 else await _deny_all(uid)

    reg = ConnectionRegistry(resolve, lambda: D_MS)
    snap = await reg.resolve(M)  # the socket's read, before the disable
    assert await reg.user_disabled(M) == 0  # nothing registered yet: it closes none
    authz = ConnectionAuthz(snap.principal, reg.services, version=snap.version)
    reg.register(authz, _noop)
    await reg.recheck(authz)
    assert (reads, authz.principal.permissions) == ([M, M], frozenset())


@pytest.mark.parametrize(
    ("issued_ms", "refused"),
    [(D_MS - 1, True), (D_MS, True), (D_MS + 1, False)],
    ids=["before", "at", "after"],
)
async def test_a_token_issued_at_or_before_the_disable_is_refused(
    issued_ms: int, refused: bool
) -> None:
    """AC4: a token issued after the disable (the user re-enabled, signed in again) is not."""
    reg = _registry()
    await reg.user_disabled(M)
    assert reg.issued_before_disable(M, _expiry(issued_ms)) is refused


async def test_only_a_disabled_user_is_remembered() -> None:
    reg = _registry()
    assert not reg.issued_before_disable(M, _expiry(D_MS))  # not disabled yet
    await reg.user_disabled(M)
    assert not reg.issued_before_disable(OTHER, _expiry(D_MS))


async def test_the_user_is_remembered_before_any_socket_is_closed() -> None:
    """A socket that registers while a close is in flight is not in the list being closed, so
    the memory must already hold the user then."""
    reg = _registry()
    seen: list[bool] = []

    async def closer(_bye: dict[str, Any], _code: int) -> None:
        seen.append(reg.issued_before_disable(M, _expiry(D_MS)))

    reg.register(ConnectionAuthz(await _deny_all(M), reg.services), _noop, None, closer)
    assert await reg.user_disabled(M) == 1
    assert seen == [True]


async def test_a_disable_is_forgotten_once_one_access_token_lifetime_has_passed() -> None:
    """AC3: every token issued before the disable has expired by then."""
    clock = _Clock()
    reg = _registry(clock)
    await reg.user_disabled(M)
    clock.now += DISABLED_MEMORY_S - 0.001
    assert reg.issued_before_disable(M, _expiry(D_MS))
    clock.now += 0.001  # exactly one lifetime after the disable
    assert not reg.issued_before_disable(M, _expiry(D_MS))
    assert reg._disabled == {}  # the entry is gone, not only ignored


async def test_a_repeat_disable_renews_the_instant_and_the_lifetime() -> None:
    """A user re-enabled, signed in, then disabled again: a token issued between the two
    disables is refused, and the renewed entry outlives one that is now older."""
    clock, wall = _Clock(), [D_MS]
    reg = ConnectionRegistry(_deny_all, lambda: wall[0], monotonic=clock)
    await reg.user_disabled(M)
    await reg.user_disabled(OTHER)
    clock.now += 600.0
    wall[0] += 600_000
    await reg.user_disabled(M)
    clock.now += 120.0  # OTHER's lifetime is over; M's, renewed 120 s ago, is not
    assert reg.issued_before_disable(M, _expiry(D_MS + 1))
    assert not reg.issued_before_disable(OTHER, _expiry(D_MS))


async def test_past_the_cap_the_oldest_is_forgotten_first_with_one_throttled_warning() -> None:
    """AC3, C-2.18: forgetting a live entry reopens the race for that user only."""
    reg = _registry(max_disabled=2)
    users = [uuid.UUID(int=n) for n in range(1, 5)]
    with capture_logs() as logs:
        for user in users:  # the 3rd forgets the 1st (logged), the 4th the 2nd (counted)
            await reg.user_disabled(user)
    warnings = [e for e in logs if e["log_level"] == "warning"]
    remembered = [reg.issued_before_disable(u, _expiry(D_MS)) for u in users]
    assert remembered == [False, False, True, True]
    assert [(e["evicted_total"], e["max_disabled"]) for e in warnings] == [(1, 2)]


@pytest.mark.parametrize(
    "memory",
    [
        {"disabled_memory_s": 0.0},
        {"disabled_memory_s": float("nan")},
        {"disabled_memory_s": float("inf")},
        {"max_disabled": 0},
    ],
)
def test_the_memory_bounds_must_be_finite_and_positive(memory: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="must be finite and > 0"):
        _registry(**memory)


def test_the_default_memory_is_one_access_token_lifetime() -> None:
    assert DISABLED_MEMORY_S == ACCESS_TOKEN_TTL.total_seconds()
