"""exchange.base module (M3).

ExchangeAdapter interface, normalised domain events, error taxonomy
(E08-T01, `docs/plan/24-internal-schemas.md` Sec.14).

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1.

`Trade`/`Ticker`/`TradeSide` (E02-T12) are the synthetic-feed normalised
domain event shapes; the full `ExchangeAdapter` interface, capability
record, `FakeExchange` and error taxonomy land with E08-T01.
"""

from __future__ import annotations

from .boundary import translate_exchange_error
from .errors import (
    AmbiguousResultError,
    AuthError,
    ClockDriftError,
    DuplicateClientIdError,
    ExchangeError,
    InstrumentFilterError,
    InsufficientMarginError,
    NotFoundError,
    OmsErrorCode,
    RateLimitError,
    TransportError,
    UnknownStateError,
)
from .fakes import FakeExchange
from .models import ExchangeCapabilities, Ticker, Trade, TradeSide
from .ports import MarketDataPort, TradingPort

__all__ = [
    "AmbiguousResultError",
    "AuthError",
    "ClockDriftError",
    "DuplicateClientIdError",
    "ExchangeCapabilities",
    "ExchangeError",
    "FakeExchange",
    "InstrumentFilterError",
    "InsufficientMarginError",
    "MarketDataPort",
    "NotFoundError",
    "OmsErrorCode",
    "RateLimitError",
    "Ticker",
    "Trade",
    "TradeSide",
    "TradingPort",
    "TransportError",
    "UnknownStateError",
    "translate_exchange_error",
]
