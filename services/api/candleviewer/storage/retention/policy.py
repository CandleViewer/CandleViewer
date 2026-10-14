"""Retention policy resolution (E07-T05, `21-database-schema.md` Sec.7).

Most-specific-first: a per-symbol rule beats the global default. Defaults are
seeded from `backend/db/seeds/retention_defaults.yaml`. Policy *changes* are a
dangerous action gated by `retention.change` at the service boundary.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from candleviewer.storage.models import StreamKind

RETENTION_CHANGE_PERMISSION = "retention.change"


class RetentionPermissionDenied(PermissionError):
    """Caller lacks `retention.change`."""


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
