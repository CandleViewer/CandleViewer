"""Domain models for the book module (M7)."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import ConfigDict

from candleviewer.domain.events import DomainEvent, MarketEvent
from candleviewer.domain.primitives import Px, Qty


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


class BestQuoteEvent(MarketEvent):
    """24 §2.8 (E21-T01): the top of the live tier, published on `{env}.md.{symbol}.quote` only
    when a field changes (`book/quote.py`), so an unchanged book publishes none."""

    bid: Px
    bid_qty: Qty
    ask: Px
    ask_qty: Qty
    spread_ticks: int
    spread_bps: Decimal
    mid: Px


class BookDesyncEvent(MarketEvent):
    """24 §2.8 (E21-T01): one per resync incident, on `{env}.health.{symbol}.book_desync`.
    `got_update_id` is the `u` that broke the sequence, `None` when the cause is no sequence."""

    depth: int
    prev_update_id: int
    got_update_id: int | None
    resync_count: int
    reason: str
