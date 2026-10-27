"""Trade-group member readiness (E28-T05 S2a, #909; US-PROF-005 "2 of 3 ready"; 22's
`TradeGroupReadiness`, which S0 adds): whether each member's account can trade now and, if not,
why. Derived on every read from in-memory state (C-2.21), synchronous, one `ReadinessSource.reason`
ask per enabled member; the sources are the composition root's (`trade_groups_wiring`), `accounts`
imports none. Fail closed (KV-T12): ready only when the source answers exactly `None`; a source
that raises, or answers outside the closed set, leaves the member `trading_disabled`, logged by
account and error class alone (C-12.6). A member switched off in the definition is listed as
`member_disabled`, never asked and never counted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, get_args
from uuid import UUID

import structlog

from candleviewer.domain.primitives import Environment

#: The reasons of 22's `TradeGroupReadiness.members[]` (added by S0), closed.
ReadinessReason = Literal[
    "member_disabled",
    "account_disabled",
    "key_invalid",
    "account_unhealthy",
    "account_locked",
    "kill_switch_engaged",
    "trading_disabled",
]
_REASONS = get_args(ReadinessReason)


class ReadinessSource(Protocol):
    """The first reason an account cannot trade now, or `None`. `account_enabled` is the account
    row's switch, which the caller holds (as `AccountStatusReader.status` takes it)."""

    def reason(
        self, account_id: UUID, environment: Environment, *, account_enabled: bool
    ) -> ReadinessReason | None: ...


@dataclass(frozen=True, slots=True)
class ReadinessMember:
    """A member as the read takes it: its account, its switch in the definition, the row's."""

    account_id: UUID
    enabled: bool
    account_enabled: bool


@dataclass(frozen=True, slots=True)
class MemberReadiness:
    account_id: UUID
    ready: bool
    reason: ReadinessReason | None


@dataclass(frozen=True, slots=True)
class Readiness:
    """`ready` of `total` enabled members, and every member in the definition's order."""

    ready: int
    total: int
    members: tuple[MemberReadiness, ...]


def readiness(
    members: Iterable[ReadinessMember], source: ReadinessSource, environment: Environment
) -> Readiness:
    rows: list[MemberReadiness] = []
    ready = total = 0
    for member in members:
        if member.enabled is not True:
            rows.append(MemberReadiness(member.account_id, False, "member_disabled"))
            continue
        total += 1
        reason = member_reason(source, member, environment)
        ready += reason is None
        rows.append(MemberReadiness(member.account_id, reason is None, reason))
    return Readiness(ready, total, tuple(rows))


def member_reason(
    source: ReadinessSource, member: ReadinessMember, environment: Environment
) -> ReadinessReason | None:
    """One member's reason, `None` when ready: what `readiness` asks of each enabled member. Whoever
    needs one account's reason asks here, never the source direct, so a faulting source fails
    closed the same way."""
    try:
        reason = source.reason(
            member.account_id, environment, account_enabled=member.account_enabled
        )
    except Exception as exc:  # fail closed: one account's fault never blanks the read
        error = type(exc).__name__
    else:
        if reason is None or reason in _REASONS:
            return reason
        error = "UnknownReason"
    structlog.get_logger(__name__).error(
        "trade_group_readiness_failed", account_id=str(member.account_id), error=error
    )
    return "trading_disabled"
