"""exchange.base module (M3).

ExchangeAdapter interface, normalised domain events, error taxonomy
(E08-T01, `docs/plan/24-internal-schemas.md` Sec.14).

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1.

`Trade`/`Ticker`/`TradeSide` (E02-T12) are the synthetic-feed normalised
domain event shapes; the full `ExchangeAdapter` interface, capability
record, `FakeExchange` and error taxonomy land with E08-T01, and
`FakeTradingPort` with G-8 (#2877).
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
    RateBudgetExceededError,
    RateLimitError,
    TransportError,
    UnknownStateError,
)
from .fakes import FakeExchange, FakeTradingPort
from .models import ExchangeCapabilities, Ticker, Trade, TradeSide
from .ports import MarketDataPort, RateHeadroomPort, TradingPort

__all__ = [
    "AmbiguousResultError",
    "AuthError",
    "ClockDriftError",
    "DuplicateClientIdError",
    "ExchangeCapabilities",
    "ExchangeError",
    "FakeExchange",
    "FakeTradingPort",
    "InstrumentFilterError",
    "InsufficientMarginError",
    "MarketDataPort",
    "NotFoundError",
    "OmsErrorCode",
    "RateBudgetExceededError",
    "RateHeadroomPort",
    "RateLimitError",
    "Ticker",
    "Trade",
    "TradeSide",
    "TradingPort",
    "TransportError",
    "UnknownStateError",
    "translate_exchange_error",
]
