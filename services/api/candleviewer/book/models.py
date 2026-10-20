"""Domain models for the book module (M7)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict

from candleviewer.domain.events import DomainEvent


class BookPhase(StrEnum):
    """Health phase published on B14 state entry (INV-B14-b): consumers and
    the publisher read this plain enum, never the interpreter."""

    INIT = "init"
    SNAPSHOT_PENDING = "snapshot_pending"
    LIVE = "live"
    DESYNCED = "desynced"


class BookStatus(DomainEvent):
    """Published on the book topic whenever the book leaves/enters LIVE so
    SCR-050 / SCR-152 can announce "Book resynchronising" with a text reason
    and the last-good time (accessibility note). Carries the 24 §1.4 envelope
    (C6, #3876): a local observation, so `ts_event` = `ts_ingest` = `ts_us`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    depth: int
    state: BookPhase
    reason: str
    ts_us: int
    last_good_ts_us: int | None
    resync_count: int
    degraded: bool = False
