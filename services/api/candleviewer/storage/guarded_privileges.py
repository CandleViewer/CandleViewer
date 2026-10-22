"""The privileges the runtime role must not hold, pinned, and their boot check (#3998).

Revisions narrow `cv_app`'s grants inside a role-existence guard (`IF EXISTS (SELECT FROM pg_roles
WHERE rolname = 'cv_app')`, 0003's pattern), so on a cluster where the runtime role is missing or
named otherwise each REVOKE is a silent no-op (CR-2758-01). `GUARDED_PRIVILEGES` pins, per table,
what the revisions' upgrades revoke from `cv_app`. The tripwire
`tests/unit/migrations/test_guarded_privileges_tripwire.py` parses every revision and fails when
the two differ: a REVOKE with no entry, an entry with no REVOKE, or one that a later upgrade
grants back. A column grant (`GRANT UPDATE (replayed_at)`, 0033) gives no table privilege back.

`check_guarded_privileges` runs once at start-up, from `StorageService.start()` on the real
backend once the tiers answer, on the storage tier's own connection, so it reads the role the app
runs as. One statement asks `has_table_privilege(current_user, ...)` for every pinned pair, each
table looked up in schema `public` whatever the login's `search_path`
(`repositories.guarded_privileges_sqlalchemy`). In `live`, a held pair, a pinned table missing
from `public` (its pairs cannot be checked) or a check that cannot run refuses the start
(`GuardedPrivilegesHeld`: fail closed). Elsewhere each is logged at ERROR and counted in
`cv_db_guarded_privileges_held`, where a pair that could not be checked counts as held, the
counts go to `StorageService.tier_health()` (`/readyz` is degraded while either is above 0) and
the start goes on. A superuser, or the owner of a table (the dev compose `cv` login, a test
container's superuser, `cv_owner`), holds every privilege there: outside `live` that is logged
once with `exempt=True` and is not a violation. The log lines and the error name tables and
privileges, never the role, the DSN or a driver's message (C-12.6); `login_kind` says only
whether the login is a superuser, an owner or the runtime role. No driver import: the tripwire
and the check read this module without a database.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import structlog

from candleviewer.storage.errors import GuardedPrivilegesHeld
from candleviewer.storage.health import GuardedPrivilegesHealth

if TYPE_CHECKING:
    from candleviewer.observability.metrics import MetricChild

#: Table -> the privileges the revisions revoke from `cv_app` there (the revision is named).
GUARDED_PRIVILEGES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "account_profile_revisions": frozenset({"DELETE", "INSERT", "TRUNCATE", "UPDATE"}),  # 0037
        "account_profiles": frozenset({"DELETE"}),  # 0037
        "api_keys": frozenset({"DELETE"}),  # 0024
        "audit_checkpoints": frozenset({"DELETE", "TRUNCATE", "UPDATE"}),  # 0003
        "audit_log": frozenset({"DELETE", "TRUNCATE", "UPDATE"}),  # 0003
        "audit_signing_keys": frozenset({"DELETE"}),  # 0046
        "auth_keys": frozenset({"DELETE"}),  # 0030
        "backups": frozenset({"DELETE"}),  # 0032
        "exchange_accounts": frozenset({"DELETE"}),  # 0044
        "executions": frozenset({"DELETE", "TRUNCATE", "UPDATE"}),  # 0029
        "kill_switch_state": frozenset({"DELETE"}),  # 0038
        "machine_drain_journal": frozenset({"DELETE", "TRUNCATE", "UPDATE"}),  # 0033
        "machine_events": frozenset({"DELETE", "TRUNCATE", "UPDATE"}),  # 0033
        "machine_snapshots": frozenset({"DELETE", "TRUNCATE"}),  # 0033
        "order_events": frozenset({"DELETE", "TRUNCATE", "UPDATE"}),  # 0029
        "recording_gaps": frozenset({"DELETE", "TRUNCATE"}),  # 0011
        "recording_sessions": frozenset({"DELETE", "TRUNCATE"}),  # 0011
        "risk_lockouts": frozenset({"DELETE"}),  # 0038
        "risk_policy": frozenset({"DELETE"}),  # 0038
        "trade_group_definitions": frozenset({"DELETE"}),  # 0039
        "trade_group_legs": frozenset({"DELETE"}),  # 0039
        "trade_groups": frozenset({"DELETE"}),  # 0039
    }
)
#: Every pinned (table, privilege) pair, sorted: the order the check asks for them.
GUARDED_PAIRS: Final = tuple(sorted((t, p) for t, ps in GUARDED_PRIVILEGES.items() for p in ps))


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class HeldPrivilege:
    """A pinned pair the role holds. `via_owner`: the role owns the table or has its owner's
    privileges (a superuser has every role's)."""

    table: str
    privilege: str
    via_owner: bool


@dataclass(frozen=True, slots=True)
class PrivilegeReport:
    """What one read found: whether the role is a superuser, the pinned pairs it holds, and the
    pinned tables missing from schema `public`, whose pairs it could not check."""

    superuser: bool
    held: tuple[HeldPrivilege, ...]
    missing: tuple[str, ...]

    @property
    def tables_present(self) -> int:
        """How many pinned tables the read found in `public`."""
        return len(GUARDED_PRIVILEGES) - len(self.missing)


async def check_guarded_privileges(
    read: Callable[[], Awaitable[PrivilegeReport]],
    *,
    live: bool,
    gauge: MetricChild | None,
    timeout_s: float,
) -> GuardedPrivilegesHealth:
    """Read once within `timeout_s` and judge (see the module docstring); return what it counted.
    Raises `GuardedPrivilegesHeld` in `live` only; a cancellation propagates."""
    try:
        async with asyncio.timeout(timeout_s):
            report = await read()
    except Exception as exc:  # TimeoutError too; by type only: a driver's text can name a host
        _log().error("storage_guarded_privileges_unchecked", error=type(exc).__name__, refused=live)
        unchecked = "the guarded privileges could not be checked"
        return _judged(gauge, len(GUARDED_PAIRS), 0, live=live, problem=unchecked)
    owned = any(h.via_owner for h in report.held)
    login_kind = "superuser" if report.superuser else "owner" if owned else "runtime"
    exempt = (report.superuser or owned) and not live  # a dev or test cluster: no violation
    present = report.tables_present
    if exempt:
        _log().warning(
            "storage_guarded_privileges_privileged_role",
            login_kind=login_kind,
            exempt=True,
            tables_present=present,
        )
    found = report.held if live else tuple(h for h in report.held if not h.via_owner)
    problems: list[str] = []
    if found:
        names = [f"{h.table}.{h.privilege}" for h in found]
        _log().error(
            "storage_guarded_privileges_held", held=names, login_kind=login_kind, refused=live
        )
        problems.append("the runtime role holds guarded privileges: " + ", ".join(names))
    if report.missing:
        missing = list(report.missing)
        _log().error(
            "storage_guarded_privileges_tables_missing",
            missing=missing,
            tables_present=present,
            refused=live,
        )
        problems.append("pinned tables missing from schema public: " + ", ".join(missing))
    if not (exempt or problems):
        _log().info(
            "storage_guarded_privileges_checked", pairs=len(GUARDED_PAIRS), tables_present=present
        )
    unchecked_pairs = sum(len(GUARDED_PRIVILEGES.get(t, frozenset())) for t in report.missing)
    held = len(found) + unchecked_pairs
    return _judged(gauge, held, len(report.missing), live=live, problem="; ".join(problems))


def _judged(
    gauge: MetricChild | None, held: int, missing: int, *, live: bool, problem: str
) -> GuardedPrivilegesHealth:
    """Publish `held`; in `live` refuse when there is a `problem`; else return the counts. The
    refusal drops the context a failed read would chain to it: a driver's text can name a host."""
    if gauge is not None:
        gauge.set(held)
    if live and problem:
        raise GuardedPrivilegesHeld(problem) from None
    return GuardedPrivilegesHealth(held=held, missing=missing)
