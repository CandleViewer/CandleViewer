"""Base event envelope and instrument metadata (§1.3, §1.4).

`DomainEvent`/`MarketEvent` are the immutable envelope every normalised
market-data event (§2) inherits from, and `uuid7` mints its `event_id`.
`Instrument` is the version-tracked instrument-metadata record referenced by
`MarketDataPort.instrument`.
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from candleviewer.domain.primitives import (
    Category,
    EventId,
    Exchange,
    Notional,
    Px,
    Qty,
    Symbol,
    TsUs,
)


class Instrument(BaseModel):
    """Instrument metadata (§1.3). `metadata_version` bumps invalidate cached
    footprint/profile aggregates keyed on the old tick size."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Default mirrors the OpenAPI Exchange contract (C-1.3).
    # nosemgrep: cv-adapter-isolation reason=B5-b owner=@CandleViewer/security review=2026-12-31
    exchange: Exchange = "bybit"
    category: Category = "linear"
    symbol: Symbol
    base_coin: str
    quote_coin: str
    settle_coin: str
    status: Literal["pre_launch", "trading", "delivering", "closed"]
    contract_type: Literal["linear_perpetual"]
    launch_time: TsUs
    tick_size: Px
    price_scale: int
    min_price: Px
    max_price: Px
    qty_step: Qty
    min_order_qty: Qty
    max_order_qty: Qty
    max_mkt_order_qty: Qty
    min_notional: Notional
    max_leverage: Decimal
    min_leverage: Decimal
    leverage_step: Decimal
    funding_interval_min: int
    upper_funding_rate: Decimal
    lower_funding_rate: Decimal
    copy_trading: bool
    metadata_version: int
    fetched_at: TsUs


def uuid7(ts_ms: int) -> uuid.UUID:
    """RFC 9562 UUIDv7 (time-sortable); `uuid.uuid7` is absent before py3.14."""
    value = (ts_ms & 0xFFFFFFFFFFFF) << 80 | int.from_bytes(os.urandom(10), "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    value = (value & ~(0x3 << 62)) | (0x2 << 62)
    return uuid.UUID(int=value)


class DomainEvent(BaseModel):
    """Base envelope for every normalised event on the bus (§1.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    event_id: EventId
    ts_event: TsUs
    ts_ingest: TsUs
    source: Literal["live", "replay", "paper", "backfill"]


class MarketEvent(DomainEvent):
    """Base envelope for market-data events; adds the exchange/category/symbol
    identity common to every §2 event family."""

    # Default mirrors the OpenAPI Exchange contract (C-1.3).
    # nosemgrep: cv-adapter-isolation reason=B5-b owner=@CandleViewer/security review=2026-12-31
    exchange: Exchange = "bybit"
    category: Category = "linear"
    symbol: Symbol


class InstrumentUpdatedEvent(DomainEvent):
    """Published when a catalogue refresh detects a metadata change for an
    existing symbol (§3.6 event table). `changed_fields` names every field
    that differed from the immediately preceding `metadata_version` so a
    consumer (E16/E18 rebuild scheduling, out of scope here) can decide
    whether the change actually invalidates its cached aggregates rather
    than rebuilding on every refresh."""

    symbol: Symbol
    metadata_version: int
    changed_fields: tuple[str, ...]
