"""#3413 (SR-029, UL1-E2): the registry remembers a disabled user for one access-token lifetime.

The per-user close (`ConnectionRegistry.user_disabled`) ends the sockets registered at that
instant. A socket whose `auth` read its principal before it, and registers after it, must read
its principal again (SR-189) and be refused when its access token was issued at or before the
disable. The memory is bounded (C-2.18). Fake clocks only: the disable instant is the registry's
`clock_ms`, the expiry its `monotonic`. A registry has two spans, the lifetime a token's expiry is
dated by and the time a disable is remembered; the second is never shorter than the first.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from candleviewer.ws.permissions import (
    ACCESS_TOKEN_TTL_S,
    DISABLED_MEMORY_S,
    ConnectionAuthz,
    ConnectionRegistry,
)

M, OTHER = uuid.UUID(int=0x3413), uuid.UUID(int=0x3414)
D_MS = 1_789_132_262_000  # the disable instant, on the registry's wall clock
LIFETIME_MS = int(ACCESS_TOKEN_TTL_S * 1000)


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


async def _deny_all(uid: uuid.UUID) -> PrincipalSnapshot:
    return PrincipalSnapshot(uid, frozenset(), frozenset())


async def _noop(_frame: dict[str, Any]) -> None:
    return None


def _registry(clock: _Clock | None = None, **spans: Any) -> ConnectionRegistry:
    return ConnectionRegistry(_deny_all, lambda: D_MS, monotonic=clock or _Clock(), **spans)


def _expiry(issued_ms: int, lifetime_ms: int = LIFETIME_MS) -> int:
    """The expiry of an access token issued at `issued_ms` (`access_token_expires_at`)."""
    return issued_ms + lifetime_ms


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


@pytest.mark.parametrize("issued_ms", [D_MS - 1, D_MS], ids=["before", "at"])
async def test_a_token_issued_at_or_before_the_disable_is_refused(issued_ms: int) -> None:
    reg = _registry()
    await reg.user_disabled(M)
    assert reg.issued_before_disable(M, _expiry(issued_ms))


async def test_a_token_issued_after_the_disable_is_not_refused() -> None:
    """AC4: the user was re-enabled and signed in again, a millisecond after the disable."""
    reg = _registry()
    await reg.user_disabled(M)
    assert not reg.issued_before_disable(M, _expiry(D_MS + 1))


async def test_a_token_is_dated_by_the_access_token_lifetime_not_the_memory_span() -> None:
    """A token expires one access-token lifetime after it was issued, however long a disable is
    remembered: here 60 s against 1 000 s. A token issued at the disable instant is refused and
    one issued a millisecond later is not, the span notwithstanding."""
    reg = _registry(disabled_memory_s=1_000.0, access_token_ttl_s=60.0)
    await reg.user_disabled(M)
    refused = [reg.issued_before_disable(M, _expiry(D_MS + n, 60_000)) for n in (0, 1)]
    assert refused == [True, False]


async def test_a_lifetime_that_is_inexact_in_floats_is_never_rounded_down() -> None:
    """1.001 s is 1000.9999999999999 ms as a float: truncated, the bound would be 1 ms short and
    a token issued at the disable instant (it expires 1 001 ms later) would be let in."""
    reg = _registry(disabled_memory_s=1.001, access_token_ttl_s=1.001)
    await reg.user_disabled(M)
    assert reg.issued_before_disable(M, _expiry(D_MS, 1_001))


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
    """AC3: every token issued before the disable has expired by then. The clock is set to
    whole and half seconds, which a float holds exactly, so the boundary is exact."""
    clock = _Clock()
    reg = _registry(clock)
    await reg.user_disabled(M)
    start = clock.now
    clock.now = start + DISABLED_MEMORY_S - 0.5
    assert reg.issued_before_disable(M, _expiry(D_MS))
    clock.now = start + DISABLED_MEMORY_S  # exactly one lifetime after the disable
    assert not reg.issued_before_disable(M, _expiry(D_MS))
    assert reg._disabled == {}  # the entry is gone, not only ignored


async def test_a_disable_is_remembered_for_the_span_the_registry_was_given() -> None:
    """The span is the registry's `disabled_memory_s`, not the default: a longer one keeps the
    entry past one lifetime, and ends exactly at its own."""
    clock = _Clock()
    reg = _registry(clock, disabled_memory_s=1_000.0)
    await reg.user_disabled(M)
    start = clock.now
    clock.now = start + 1_000.0 - 0.5
    assert reg.issued_before_disable(M, _expiry(D_MS))
    clock.now = start + 1_000.0
    assert not reg.issued_before_disable(M, _expiry(D_MS))


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
    "spans",
    [
        {"disabled_memory_s": 0.0},
        {"disabled_memory_s": float("nan")},
        {"disabled_memory_s": float("inf")},
        {"access_token_ttl_s": 0.0},
        {"access_token_ttl_s": float("nan")},
        {"access_token_ttl_s": float("inf")},
        {"max_disabled": 0},
    ],
)
def test_the_spans_and_the_cap_must_be_finite_and_positive(spans: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="must be finite and > 0"):
        _registry(**spans)


@pytest.mark.parametrize(
    "spans",
    [
        {"disabled_memory_s": ACCESS_TOKEN_TTL_S - 1.0},
        {"disabled_memory_s": 59.0, "access_token_ttl_s": 60.0},
    ],
    ids=["default_lifetime", "own_lifetime"],
)
def test_a_memory_shorter_than_the_access_token_lifetime_is_refused(
    spans: dict[str, Any],
) -> None:
    """Fail closed: a disable forgotten while a token issued before it is still live would let
    that token in, and the check that dates a token by the lifetime would not notice."""
    with pytest.raises(ValueError, match="disabled_memory_s must be at least access_token_ttl_s"):
        _registry(**spans)


def test_a_memory_as_long_as_the_access_token_lifetime_is_accepted() -> None:
    reg = _registry(disabled_memory_s=60.0, access_token_ttl_s=60.0)
    assert (reg.disabled_memory_s, reg.access_token_ttl_s) == (60.0, 60.0)


@pytest.mark.parametrize(
    "default", [ACCESS_TOKEN_TTL_S, DISABLED_MEMORY_S], ids=["token", "memory"]
)
def test_the_defaults_are_one_access_token_lifetime(default: float) -> None:
    """ADR-0020's 12 minutes, which is `auth.session_service.ACCESS_TOKEN_TTL`."""
    assert default == ACCESS_TOKEN_TTL.total_seconds()
