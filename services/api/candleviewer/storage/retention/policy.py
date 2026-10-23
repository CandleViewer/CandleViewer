"""Retention policy resolution (E07-T05, `21-database-schema.md` Sec.7).

Most-specific-first: a per-symbol rule beats the global default. Defaults are
seeded from `backend/db/seeds/retention_defaults.yaml`. Policy *changes* are a
dangerous action gated by `recording:write` at the service boundary; step-up (SR-025) must be
enforced at the route, which the step-up registry does not cover yet (#2738).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from candleviewer.storage.models import StreamKind

#: The seeded RBAC code the contract gates retention changes with (`setRetentionPolicies`,
#: 04 §7.2.2 row 9, #1778 decision Z: Owner and Manager; step-up belongs to the route, #2738).
#: `retention.change` is the audit action for such a change, not a permission (#2699). `storage`
#: may not import `auth`; tests/unit/auth/test_permission_literals.py checks this literal against
#: `rbac_seed.json`.
RETENTION_CHANGE_PERMISSION = "recording:write"


class RetentionPermissionDenied(PermissionError):
    """Caller lacks `recording:write`."""


def require_retention_change(permissions: Iterable[str]) -> None:
    """Server-side permission check for policy changes (SR-099, C-12.4)."""
    if RETENTION_CHANGE_PERMISSION not in set(permissions):
        raise RetentionPermissionDenied(RETENTION_CHANGE_PERMISSION)


@dataclass(frozen=True, slots=True)
class RetentionRule:
    stream: StreamKind
    hot_days: int
    cold_days: int | None
    action: str = "archive_parquet"
    symbol: str | None = None  # None = global default


@dataclass(frozen=True, slots=True)
class RowReading:
    """A `retention_policies` row read by its `action` (#2188). `hot_days`: the window before the
    roll-off moves a day to Parquet (and the klines hot boundary); `total_days`: the delete horizon
    the row states, `None` = none, so the stream's §7 default governs."""

    hot_days: int
    total_days: int | None


def read_policy_row(action: str, retain_days: int) -> RowReading:
    """The one reading of a row, taken by the roll-off and the klines boundary
    (`SqlAlchemyRecorderRepository`) and by the reaper's facts (`PgRetentionFacts`), so they cannot
    disagree on it (21 §3.6.3). `drop`: `retain_days` is the TOTAL horizon, and the hot window too,
    so the day still leaves QuestDB through the verified roll-off (21 §5.3) and the reaper then
    deletes it at `retain_days`, not at the §7 total. `archive_parquet`: the hot window; the §7
    total stays, and the row never causes a delete. Any other action reads as `archive_parquet`
    (fail closed: today's reading). A pinned symbol is outside it: each reader checks the pin."""
    if action == "drop":
        return RowReading(retain_days, retain_days)
    return RowReading(retain_days, None)


def default_seed_path() -> Path:
    return (
        Path(__file__).resolve().parents[5] / "backend" / "db" / "seeds" / "retention_defaults.yaml"
    )


_LINE = re.compile(r"^\s*-\s*\{(?P<body>[^}]*)\}\s*$")


def load_defaults(path: Path | None = None) -> list[RetentionRule]:
    """Parse the seed (flow-mapping list; avoids a runtime PyYAML dependency)."""
    rules: list[RetentionRule] = []
    for line in (path or default_seed_path()).read_text("utf-8").splitlines():
        match = _LINE.match(line)
        if not match:
            continue
        kv = dict(p.strip().split(":", 1) for p in match.group("body").split(","))
        kv = {k.strip(): v.strip() for k, v in kv.items()}
        rules.append(
            RetentionRule(
                stream=StreamKind(kv["stream"]),
                hot_days=int(kv["hot_days"]),
                cold_days=None if kv["cold_days"] == "null" else int(kv["cold_days"]),
                action=kv["action"],
            )
        )
    return rules


class RetentionPolicy:
    """Resolved rule set; `rules` are DB rows (per-symbol/global) over defaults."""

    def __init__(self, rules: Iterable[RetentionRule], defaults: Iterable[RetentionRule]) -> None:
        self._by_symbol: dict[tuple[str, StreamKind], RetentionRule] = {}
        self._global: dict[StreamKind, RetentionRule] = {r.stream: r for r in defaults}
        for rule in rules:
            if rule.symbol is None:
                self._global[rule.stream] = rule
            else:
                self._by_symbol[(rule.symbol, rule.stream)] = rule

    @property
    def streams(self) -> list[StreamKind]:
        return list(self._global)

    def resolve(self, symbol: str, stream: StreamKind) -> RetentionRule | None:
        return self._by_symbol.get((symbol, stream)) or self._global.get(stream)


#: `alert_deliveries` (PG) retention per docs/plan/21-database-schema.md retention table (E40-T01).
ALERT_DELIVERIES_HOT_DAYS = 180
ALERT_DELIVERIES_COLD_MONTHS = 24
ALERT_DELIVERIES_ACTION = "archive_parquet"

#: Soft-deleted drawings are hard-purged after this many days (E14-T01, 21-database-schema.md).
DRAWINGS_SOFT_DELETE_DAYS = 90
#: Soft-deleted workspaces and layouts are hard-purged after this many days (E15-T01, §3.8.1).
WORKSPACES_SOFT_DELETE_DAYS = 90
#: `incidents` (21 Sec.7): a `resolved` row is dropped this many months after its `last_seen_at`
#: (the `system_events` total horizon); open and acknowledged rows are kept (E42-T05).
INCIDENTS_RESOLVED_MONTHS = 24
#: A user deleted with `?purge=true` is anonymised this many days after the delete (E42-T10,
#: US-ADMIN-001, #965 O6): `users.purge_after` is the delete's time plus this window.
USERS_PURGE_AFTER_DAYS = 90
