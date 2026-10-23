"""#906 (B2c): `CatalogueLimits`, the profile save's exchange limits over the process environment's
instrument catalogue (C-2.11). It answers the instruments of a snapshot a fetch confirmed lately
(`ensure_fresh`), and is unavailable, the save's 503, when the refresh runs on past the deadline,
failed, confirmed nothing, or no catalogue is wired. A fake catalogue over the recorded instrument
page (C-13.5); no I/O, no clock."""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from candleviewer.accounts.profile_validator import (
    INSTRUMENT_DEADLINE_S,
    INSTRUMENT_MAX_AGE_S,
    InstrumentLimitsPort,
    InstrumentLimitsUnavailable,
)
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.ingestion.instruments import CatalogueSnapshot
from candleviewer.ingestion.instruments_refresh import (
    InstrumentRefreshError,
    InstrumentRefreshPendingError,
    InstrumentsRefreshScheduler,
)
from candleviewer.instrument_limits_wiring import CatalogueLimits
from candleviewer.settings import Environment as ProcessEnvironment
from tests._corpus import rest

_PAGE = parse_instruments(rest("rest/instruments_before.json")["result"]["list"], fetched_at_us=0)
_UNCONFIRMED = "no fetch has confirmed the instrument catalogue"
_LATE = "the instrument catalogue was not refreshed in time"


def _snapshot(*, stale: bool = False) -> CatalogueSnapshot:
    by_symbol = {i.symbol: i for i in _PAGE.instruments}
    return CatalogueSnapshot(by_symbol, fetched_at_us=0, stale_since_us=1 if stale else None)


class _Catalogue:
    """`FreshCatalogue` double: records each call's bounds, then answers `answer` or raises it."""

    def __init__(self, answer: CatalogueSnapshot | BaseException | None) -> None:
        self.answer = answer
        self.calls: list[tuple[float, float]] = []

    async def ensure_fresh(self, max_age_s: float, deadline_s: float) -> CatalogueSnapshot | None:
        self.calls.append((max_age_s, deadline_s))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


@pytest.mark.parametrize("member", ["environment", "catalogue"])
def test_the_binding_is_frozen(member: str) -> None:
    """Spec B2 section 2.4 (#906, B2c code lens R1C-02): nothing re-binds the environment or the
    catalogue once the composition root has built the binding."""
    limits = CatalogueLimits("demo", lambda: None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(limits, member, None)


async def test_a_fresh_catalogue_is_every_instrument_by_symbol() -> None:
    """The snapshot's own mapping, from one call with the save's bounds in order, on a port of the
    process's environment (D2 passes `ctx.settings.environment.value`)."""
    snapshot = _snapshot()
    catalogue = _Catalogue(snapshot)
    port: InstrumentLimitsPort = CatalogueLimits(ProcessEnvironment.DEMO.value, lambda: catalogue)
    listed = await port.listed(max_age_s=INSTRUMENT_MAX_AGE_S, deadline_s=INSTRUMENT_DEADLINE_S)
    assert listed is snapshot.by_symbol and catalogue.calls == [(900.0, 1.5)]
    assert port.environment == "demo"


_PENDING = InstrumentRefreshPendingError("catalogue refresh still running after 1.5 s")
_FAILED = InstrumentRefreshError("instrument catalogue refresh failed")


@pytest.mark.parametrize(
    ("answer", "cause", "message"),
    [
        pytest.param(_PENDING, _PENDING, _LATE, id="pending"),
        pytest.param(_FAILED, _FAILED, _LATE, id="failed"),
        pytest.param(None, None, _UNCONFIRMED, id="none"),
        pytest.param(_snapshot(stale=True), None, _UNCONFIRMED, id="marked_stale"),
    ],
)
async def test_a_catalogue_no_fetch_confirmed_in_time_is_unavailable(
    answer: CatalogueSnapshot | BaseException | None, cause: BaseException | None, message: str
) -> None:
    """The refresh missed the deadline or failed, or what is loaded is no fetch's (a stale-marked
    copy kept from a failed refresh): the save is unavailable, with a constant message."""
    limits = CatalogueLimits("demo", lambda: _Catalogue(answer))
    with pytest.raises(InstrumentLimitsUnavailable) as caught:
        await limits.listed(max_age_s=900.0, deadline_s=1.5)
    assert caught.value.__cause__ is cause and str(caught.value) == message


async def test_no_catalogue_wired_is_unavailable() -> None:
    """The fake backend attaches no scheduler: unavailable, never judged on an empty listing.
    Typed as the real scheduler, so mypy checks that it is a `FreshCatalogue`."""
    scheduler: InstrumentsRefreshScheduler | None = None
    limits = CatalogueLimits("demo", lambda: scheduler)
    with pytest.raises(InstrumentLimitsUnavailable, match=r"^no instrument catalogue is wired$"):
        await limits.listed(max_age_s=900.0, deadline_s=1.5)


@pytest.mark.parametrize(
    "failure", [asyncio.CancelledError(), RuntimeError("bug")], ids=["cancelled", "a_defect"]
)
async def test_any_other_failure_passes_through(failure: BaseException) -> None:
    """Only M6's two refresh errors are the save's 503: a cancellation (the client went away, or
    shutdown) and a defect propagate as they are."""
    limits = CatalogueLimits("demo", lambda: _Catalogue(failure))
    with pytest.raises(type(failure)) as caught:
        await limits.listed(max_age_s=900.0, deadline_s=1.5)
    assert caught.value is failure
