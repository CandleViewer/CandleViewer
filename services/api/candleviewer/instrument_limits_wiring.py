"""Composition-root binding (not a module) of the profile save's exchange limits (E28-T02, #906
slice B2c).

`CatalogueLimits` is the accounts module's `InstrumentLimitsPort` over the process's one instrument
catalogue, `ctx.ingestion.instruments` (M6's `InstrumentsRefreshScheduler`: attached late, and
absent on the fake backend). A process serves one environment (arch P9), so the port's is the
settings' (C-2.11). `ensure_fresh` coalesces concurrent saves onto one refresh and bounds the wait
itself: this adds no task and no timeout, and catches only M6's two refresh errors, so a
cancellation propagates. D2 builds it: `CatalogueLimits(ctx.settings.environment.value,
lambda: ctx.ingestion.instruments)`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from candleviewer.accounts.profile_validator import InstrumentLimitsUnavailable
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import Environment
from candleviewer.ingestion.instruments import CatalogueSnapshot
from candleviewer.ingestion.instruments_refresh import (
    InstrumentRefreshError,
    InstrumentRefreshPendingError,
)

__all__ = ["CatalogueLimits", "FreshCatalogue"]


class FreshCatalogue(Protocol):
    """`InstrumentsRefreshScheduler.ensure_fresh` (#906 slice C), or a fake."""

    async def ensure_fresh(
        self, max_age_s: float, deadline_s: float
    ) -> CatalogueSnapshot | None: ...


@dataclass(frozen=True, slots=True)
class CatalogueLimits:
    """`InstrumentLimitsPort` over the catalogue of the process's environment."""

    environment: Environment
    catalogue: Callable[[], FreshCatalogue | None]  # read per call: it is attached late

    async def listed(self, *, max_age_s: float, deadline_s: float) -> Mapping[str, Instrument]:
        """The catalogue's instruments by symbol, from a fetch at most `max_age_s` old;
        `InstrumentLimitsUnavailable` when none is wired, the refresh misses `deadline_s` or
        fails, or what is loaded is no confirmed fetch's (`None`, or marked stale)."""
        scheduler = self.catalogue()
        if scheduler is None:
            raise InstrumentLimitsUnavailable("no instrument catalogue is wired")
        try:
            snapshot = await scheduler.ensure_fresh(max_age_s, deadline_s)
        except (InstrumentRefreshPendingError, InstrumentRefreshError) as exc:
            raise InstrumentLimitsUnavailable(
                "the instrument catalogue was not refreshed in time"
            ) from exc
        if snapshot is None or snapshot.stale_since_us is not None:
            raise InstrumentLimitsUnavailable("no fetch has confirmed the instrument catalogue")
        return snapshot.by_symbol
