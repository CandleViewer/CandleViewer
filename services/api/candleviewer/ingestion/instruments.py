"""Instrument catalogue core: version-change detection and an in-memory,
atomically-swapped cache over the neutral `Instrument` domain model.

`E08-S01` scope: version-track (`docs/plan/24-internal-schemas.md` §2
`Instrument`, `21-database-schema.md` §3.3.9 `instruments`/
`instrument_versions`), cache with TTL, and publish `InstrumentUpdatedEvent`
on a metadata change. Exchange-specific parsing of the raw
`instruments-info` payload lives in the adapter package under
`candleviewer.exchange` (C-2.2: no exchange-native vocabulary outside that
boundary) — this module only ever sees the already-normalised `Instrument`
model its caller constructed. REST router
wiring and the Postgres-backed repository implementation are kept in
`candleviewer.storage`/`candleviewer.api`; this module has no I/O of its own,
so it is unit-testable without a DB or network (C-13.2).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from candleviewer.domain.events import Instrument, InstrumentUpdatedEvent

#: Fields compared between consecutive `metadata_version`s to build
#: `InstrumentUpdatedEvent.changed_fields` (ticket "Tick size changes"
#: scenario). Deliberately excludes `fetched_at`/`metadata_version`
#: themselves — those always differ on a refresh and are not "metadata".
_VERSIONED_FIELDS: tuple[str, ...] = (
    "status",
    "tick_size",
    "price_scale",
    "min_price",
    "max_price",
    "qty_step",
    "min_order_qty",
    "max_order_qty",
    "max_mkt_order_qty",
    "min_notional",
    "max_leverage",
    "min_leverage",
    "leverage_step",
    "funding_interval_min",
    "upper_funding_rate",
    "lower_funding_rate",
)


def diff_changed_fields(previous: Instrument, current: Instrument) -> tuple[str, ...]:
    """Return the `_VERSIONED_FIELDS` names that differ between `previous`
    and `current`, in stable field-declaration order (ticket "Tick size
    changes" scenario: `changed_fields` on `InstrumentUpdatedEvent`)."""
    changed = []
    for name in _VERSIONED_FIELDS:
        if getattr(previous, name) != getattr(current, name):
            changed.append(name)
    return tuple(changed)


def next_version(
    previous: Instrument | None, parsed: Instrument
) -> tuple[Instrument, tuple[str, ...]]:
    """Given the previously cached `Instrument` (or `None` for a new symbol)
    and a freshly parsed one (always `metadata_version=1`), return the
    version-stamped `Instrument` to store plus the changed field names.

    No-op case: if `previous` exists and nothing in `_VERSIONED_FIELDS`
    differs, `parsed` is returned with `previous.metadata_version` unchanged
    (no new `instrument_versions` row, no event) — the ticket's "no-op when
    unchanged" requirement.
    """
    if previous is None:
        return parsed.model_copy(update={"metadata_version": 1}), ()

    changed = diff_changed_fields(previous, parsed)
    if not changed:
        return parsed.model_copy(update={"metadata_version": previous.metadata_version}), ()

    return parsed.model_copy(update={"metadata_version": previous.metadata_version + 1}), changed


def build_updated_event(
    *,
    event_id: Any,
    symbol: str,
    metadata_version: int,
    changed_fields: tuple[str, ...],
    ts_now_us: int,
) -> InstrumentUpdatedEvent:
    """Build the `InstrumentUpdatedEvent` for a detected metadata change
    (ticket "Tick size changes" scenario). Callers only construct this when
    `changed_fields` is non-empty."""
    return InstrumentUpdatedEvent(
        event_id=event_id,
        ts_event=ts_now_us,
        ts_ingest=ts_now_us,
        source="live",
        symbol=symbol,
        metadata_version=metadata_version,
        changed_fields=changed_fields,
    )


@dataclass(frozen=True)
class CatalogueSnapshot:
    """One immutable, atomically-swappable view of the catalogue (ticket
    "Technical notes": readers never see a half-updated catalogue). `stale`
    is set when a scheduled refresh failed and this snapshot is being served
    past its TTL (ticket "Refresh fails" scenario)."""

    by_symbol: Mapping[str, Instrument]
    fetched_at_us: int
    stale_since_us: int | None = None

    def get(self, symbol: str) -> Instrument | None:
        return self.by_symbol.get(symbol)

    def listing(self, *, include_delisted: bool = False) -> Sequence[Instrument]:
        """Symbols for the search-facing listing (ticket "Delisted symbol"
        scenario): excludes non-`trading` status unless explicitly asked
        for."""
        if include_delisted:
            return tuple(self.by_symbol.values())
        return tuple(v for v in self.by_symbol.values() if v.status == "trading")

    def age_seconds(self, *, now_us: int) -> float:
        return max(0.0, (now_us - self.fetched_at_us) / 1_000_000)


@dataclass
class InstrumentCatalogueCache:
    """In-memory O(1)-lookup cache with an atomically swapped snapshot
    (ticket "Technical notes"). `refresh()` never blocks a concurrent
    `current()` read (ticket "Refresh does not stall readers" scenario) —
    the old snapshot stays fully readable until the new one is assigned in
    one attribute write.
    """

    ttl_seconds: float
    _snapshot: CatalogueSnapshot | None = field(default=None, repr=False)

    def current(self) -> CatalogueSnapshot | None:
        return self._snapshot

    def is_stale(self, *, now_us: int) -> bool:
        """Nothing loaded, the last refresh failed (`mark_stale`; the next successful
        refresh swaps in an unmarked snapshot, #2715), or older than the TTL."""
        snap = self._snapshot
        if snap is None or snap.stale_since_us is not None:
            return True
        return snap.age_seconds(now_us=now_us) > self.ttl_seconds

    def swap(self, snapshot: CatalogueSnapshot) -> None:
        """Atomically install a new snapshot (single attribute assignment —
        no reader ever observes a partially built `by_symbol` mapping)."""
        self._snapshot = snapshot

    def mark_stale(self, *, stale_since_us: int) -> None:
        """Refresh failed (ticket "Refresh fails" scenario): keep serving the
        previous snapshot but stamp `stale_since` for the endpoint to expose,
        rather than clearing the cache."""
        if self._snapshot is None:
            return
        self._snapshot = CatalogueSnapshot(
            by_symbol=self._snapshot.by_symbol,
            fetched_at_us=self._snapshot.fetched_at_us,
            stale_since_us=stale_since_us,
        )


def utc_now_us() -> int:
    return int(datetime.now(UTC).timestamp() * 1_000_000)
