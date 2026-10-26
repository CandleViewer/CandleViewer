"""Instrument catalogue refresh scheduler (E08-S01-2).

Owns the periodic (12 h TTL) + on-demand refresh of the E08-S01 in-memory
`InstrumentCatalogueCache`, persisting each fetch through a storage
repository and publishing `InstrumentUpdatedEvent` on the E08-T03 bus when a
refresh detects a metadata change (ticket "Tick size changes" scenario).

Kept in `ingestion` (M6) per the ticket's own scope line, and — per C-3.1 —
M6 may not import `candleviewer.storage` or `candleviewer.api` directly. The
repository and bus dependencies are therefore narrow, locally-declared
`Protocol`s (mirrors `ingestion/clock.py`'s `ServerTimeFetcher` pattern):
the composition root (`candleviewer.app`) wires the concrete
`SqlAlchemyInstrumentsRepository` (M10) and `Bus.publish` (M5) in, without
this module ever importing either package.

Design notes tying back to the ticket's Gherkin:
- "Catalogue loaded at startup": `refresh_now()` is awaited once, inline,
  before `start()` returns, so `GET /instruments` never serves an empty
  catalogue after boot. #2599: under `start_timeout_s`, so boot never waits
  longer on the exchange; the schedule then retries soon. #2702: an abandoned
  fetch counts `instruments_refresh_total{result="timeout"}` and serves a warm
  (persisted) snapshot stale until a refresh loads.
- "Refresh without restart": `start()` schedules a periodic task at
  `ttl_seconds`; `ensure_symbol()` serves the "unknown symbol" on-demand path
  (the router calls it). #2702: one shared refresh task that callers join and
  wait on for at most `on_demand_timeout_s` (the route then answers 503);
  `stop()` cancels it. #906: `ensure_fresh()` serves the profile save: the same shared task behind
  a freshness check (fetched within `max_age_s`, and never a snapshot marked stale), awaited for
  at most the caller's `deadline_s`.
- "Refresh fails": a failed fetch marks the existing snapshot stale via
  `InstrumentCatalogueCache.mark_stale` rather than clearing it, increments
  `instruments_refresh_total{result="error"}`, and logs a warning — the
  previous snapshot keeps serving. #2599: the next attempt follows
  `retry_backoff_s` (seconds, doubling to minutes), not the TTL, so a failed
  cold start (nothing to serve) recovers without a restart. #2715: a refresh
  that fails while the schedule waits out the TTL (an on-demand one) ends
  that wait too, so `catalogue_stale` lasts minutes, not up to the TTL.
- "Refresh does not stall readers": the fetch + parse + diff work all
  happens before the single atomic `cache.swap()` call; nothing here ever
  blocks a concurrent `cache.current()` read.
- S-RL (#913), the risk-limit tiers: held in memory beside the instruments, in the same
  snapshot, and never persisted (no migration). A symbol's tiers are first fetched on demand
  (`ensure_risk_limits`, the detail route), then re-fetched by every catalogue refresh and
  swapped with it, so they share its staleness (`stale_since`). A symbol whose tier fetch fails
  has no tiers in the new snapshot (`None`, unknown) until a later fetch succeeds: deliberately
  fail closed, the previous ladder is not kept. After a restart no symbol has tiers until its
  first fetch: the window fails closed, as a reader of `None` must (the sizer's
  `figure_unknown`), and is never served a guessed ladder. Bounds: a refresh spends at most
  `RISK_LIMITS_REFRESH_BUDGET_S` on all the tier fetches together (the symbols it does not reach
  stay unknown), so the catalogue swap never waits on the tiers longer; after a failed fetch the
  on-demand path waits `on_demand_cooldown_s` before it calls the venue for that symbol again.
- S4-S-c (#913): each refresh seeds the refreshed set from `order_path_symbols`, so the order
  path's symbols get tiers without a detail-route visit, after a restart too (`_tier_set`).
- S4-S-d (#913): `request_tiers` is the order path's ask for a symbol's tiers, from a
  `figure_unknown` caused by missing ones (a wildcard profile's symbol, which no seed names): it
  joins the refreshed set at once and gets one on-demand fetch (`ensure_risk_limits`, so its
  bounds) per `TIER_REQUEST_WINDOW_S`, at most `TIER_REQUESTS_MAX` in a window. Its caller, the
  OMS's bridge, never awaits it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import math
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Literal, Protocol
from uuid import uuid4

from candleviewer.domain.events import Instrument
from candleviewer.exchange.base.instruments import InstrumentsFetcher, RiskLimitsFetcher
from candleviewer.exchange.base.models import RiskLimitTier
from candleviewer.ingestion._logging import get_logger
from candleviewer.ingestion.errors import IngestionError
from candleviewer.ingestion.instruments import (
    CatalogueSnapshot,
    InstrumentCatalogueCache,
    build_updated_event,
    next_version,
    utc_now_us,
)
from candleviewer.ingestion.metrics import (
    instruments_cache_age_seconds,
    instruments_catalogue_size,
    instruments_refresh_total,
)
from candleviewer.observability import spawn, spawn_child

_MIN_BACKOFF_S = 1.0
_MAX_BACKOFF_S = 30.0
#: #2599: after a failed (or abandoned) refresh the schedule retries on this doubling,
#: jittered backoff, capped at five minutes, instead of waiting the 12 h TTL.
RETRY_BACKOFF_MIN_S = 5.0
RETRY_BACKOFF_MAX_S = 300.0
#: #2599: `start()` waits at most this long for the startup fetch (boot never waits longer
#: on the exchange); the schedule then retries on the backoff above.
START_TIMEOUT_S = 10.0
#: #2702: `ensure_symbol` (the `GET /instruments/{symbol}` on-demand refresh) holds a caller at
#: most this long, well under the 10 s HTTP client timeouts (the web shell's per request, the
#: exchange REST client's per attempt); the route then answers 503 and the refresh runs on.
ON_DEMAND_TIMEOUT_S = 3.0
#: S-RL (#913): one symbol's risk-limit fetch inside a catalogue refresh, at most this long.
RISK_LIMITS_FETCH_TIMEOUT_S = 10.0
#: S-RL: all of one catalogue refresh's tier fetches together, at most this long, so the catalogue
#: swap never waits on the tiers longer; the symbols the loop does not reach stay unknown.
RISK_LIMITS_REFRESH_BUDGET_S = 15.0
#: S4-S-c (#913): the refreshed set holds at most this many symbols; the seed read asks no more.
TIER_SYMBOLS_MAX = 100
#: S4-S-c: the tier fetches of one refresh run this many at a time, so 100 symbols fit the budget.
TIER_FETCH_CONCURRENCY = 4
#: S4-S-c: after a refresh that left tiers unknown (budget spent, fetches failed), the next one
#: comes after this long, doubling per such refresh in a row up to the TTL, not after the TTL.
TIERS_RETRY_S = 60.0
#: S4-S-c: a symbol with an order created this recently is seeded into the refresh (24 h).
ORDER_PATH_WINDOW_S = 86_400
#: S4-S-c: the seed read, at most this long; a late or failed read seeds nothing that tick.
ORDER_PATH_SEED_TIMEOUT_S = 2.0
#: S4-S-d (#913): a requested symbol gets at most one on-demand tier fetch in this many seconds.
TIER_REQUEST_WINDOW_S = 60.0
#: S4-S-d: at most this many symbols requested in one window; a request past it is `full`.
TIER_REQUESTS_MAX = 100

#: S4-S-d: why `request_tiers` dropped a request: its window is full, or the scheduler stopped.
TierRequestDrop = Literal["full", "stopped"]


def retry_backoff_s(failures: int, rand: float) -> float:
    """Delay before the next refresh after `failures` (>= 1) consecutive failed ones:
    `RETRY_BACKOFF_MIN_S` doubling per failure up to `RETRY_BACKOFF_MAX_S`, with equal jitter
    (half fixed, half `rand` in [0, 1)), so a retry never comes sooner than half the step. The
    exponent is clamped, so an outage of any length never overflows the float."""
    step = min(RETRY_BACKOFF_MAX_S, RETRY_BACKOFF_MIN_S * 2.0 ** min(max(failures, 1) - 1, 16))
    return step / 2 + step / 2 * rand


#: Neutral fetcher port (`exchange.base.instruments.InstrumentsFetcher`):
#: returns already-normalised `Instrument`s plus rejected rows. The concrete
#: exchange adapter's fetcher is injected by the composition root, so this
#: module never sees a raw exchange payload, the parser or the transport.
InstrumentsInfoFetcher = InstrumentsFetcher


class InstrumentsRepositoryLike(Protocol):
    """Structural type for `candleviewer.storage.repositories.
    instruments_sqlalchemy.SqlAlchemyInstrumentsRepository` (M10). Rows cross
    the boundary as plain JSON-mode mappings (`Instrument.model_dump(mode=
    "json")`) because M10 may depend on M1 only (C-3.1) and so cannot import
    the domain model; this module re-validates them on load."""

    async def upsert_snapshot(self, rows: Sequence[Mapping[str, Any]]) -> None: ...

    async def record_version(
        self,
        row: Mapping[str, Any],
        *,
        changed_fields: Sequence[str],
    ) -> None: ...

    async def mark_stale(self, *, stale_since_us: int) -> None: ...

    async def load_all(self) -> Sequence[Mapping[str, Any]]: ...


class OrderPathSymbols(Protocol):
    """S4-S-c (#913): the symbols the order path needs tiers for: those of open positions and
    open orders, and those with an order created at or after `since_us`, at most `limit`, the
    first two kinds ahead of the third. The composition root binds it over the order and position
    tables (M10), which this module never imports (C-3.1)."""

    async def __call__(self, *, since_us: int, limit: int) -> Sequence[str]: ...


class BusPublisherLike(Protocol):
    """Structural type for `Bus.publish`, bound to the `{env}.instruments.
    {symbol}.updated` topic by the composition root — this module only ever
    calls the injected callable, never constructs a `Topic` itself, so it
    stays free of the `candleviewer.bus` import edge (C-3.1)."""

    async def __call__(self, event: Any) -> None: ...


class InstrumentRefreshError(IngestionError):
    """A refresh attempt failed after every retry (fetch, parse, or
    persistence), or (#906) an on-demand refresh (`ensure_fresh`) ended with no catalogue
    fitting the caller's bound. The previous snapshot is left serving; see this module's
    docstring, "Refresh fails" scenario."""


class InstrumentRefreshPendingError(IngestionError):
    """#2702, #906: an on-demand refresh (`ensure_symbol`, `ensure_fresh`) missed the caller's
    deadline (it runs on, shared), or the scheduler is stopped: there is no answer yet. The HTTP
    edge maps it to 503."""


class InstrumentsRefreshScheduler:
    """Owns the instrument catalogue: fetch -> parse -> version-diff ->
    persist -> publish -> atomic cache swap, on a 12 h TTL schedule plus
    on-demand triggers.

    Every dependency is injected (clock, sleep, jitter source, fetcher,
    repository, publisher) so this class is unit-testable without a network
    call, a database, or a real bus (C-13.2)."""

    def __init__(
        self,
        *,
        fetch_instruments_info: InstrumentsInfoFetcher,
        repository: InstrumentsRepositoryLike,
        publish: BusPublisherLike | None = None,
        cache: InstrumentCatalogueCache | None = None,
        ttl_seconds: float = 43_200.0,  # 12 h, ticket acceptance criterion
        max_retries: int = 3,
        now_us: Callable[[], int] = utc_now_us,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fn: Callable[[], float] = random.random,
        on_demand_cooldown_s: float = 60.0,
        start_timeout_s: float = START_TIMEOUT_S,
        on_demand_timeout_s: float = ON_DEMAND_TIMEOUT_S,
        fetch_risk_limits: RiskLimitsFetcher | None = None,
        risk_limits_budget_s: float = RISK_LIMITS_REFRESH_BUDGET_S,
        order_path_symbols: OrderPathSymbols | None = None,
    ) -> None:
        self._fetch_instruments_info = fetch_instruments_info
        self._fetch_risk_limits = fetch_risk_limits
        self._risk_limits_budget_s = risk_limits_budget_s
        self._order_path_symbols = order_path_symbols
        #: S-RL: the symbols each refresh re-fetches tiers for: the order path's (S4-S-c) and
        #: those fetched once on demand; catalogue symbols only, at most `TIER_SYMBOLS_MAX`.
        self._tier_symbols: set[str] = set()
        #: S4-S-c: the last refresh fetched fewer tiers than it had symbols for; and how often so.
        self._tiers_incomplete, self._tiers_streak = False, 0
        #: S4-S-c: `start()`'s refresh spends at most a quarter of its timeout on the tiers.
        self._starting = False
        #: S-RL: when a symbol's last tier fetch failed (the on-demand cooldown's start).
        self._tier_failed_us: dict[str, int] = {}
        #: S4-S-d: when each requested symbol's fetch was last kicked, within the last window.
        self._tier_kicked_us: dict[str, int] = {}
        #: S4-S-d: the kicked fetches still running, which `stop()` cancels.
        self._tier_kicks: set[asyncio.Task[Any]] = set()
        self._repository = repository
        self._publish = publish
        self.cache = (
            cache if cache is not None else InstrumentCatalogueCache(ttl_seconds=ttl_seconds)
        )
        self._ttl_seconds = ttl_seconds
        self._max_retries = max(1, max_retries)
        self._now_us = now_us
        self._sleep = sleep
        self._random = random_fn
        self._start_timeout_s = start_timeout_s

        self._on_demand_cooldown_s = on_demand_cooldown_s
        self._on_demand_timeout_s = on_demand_timeout_s
        self._last_on_demand_us: int | None = None
        self._task: asyncio.Task[None] | None = None
        #: #2702: the shared on-demand refresh (`ensure_symbol`), if one was started.
        self._on_demand: asyncio.Task[None] | None = None
        self._stopping = False
        self._refresh_lock = asyncio.Lock()
        #: #2715: set by a failed refresh (the snapshot is marked stale), cleared by a swap.
        self._failed = asyncio.Event()
        self._listeners: list[Callable[[], Awaitable[None]]] = []

    # -- lifecycle (M6 `ingestion` conventions, 20-architecture.md §3) ------

    async def start(self) -> None:
        """Load whatever is already persisted (so a restart is never a
        cold, empty catalogue — belt-and-braces alongside the immediate
        `refresh_now()` below), then perform the startup fetch, then
        schedule the periodic TTL refresh task.

        #2599: the startup fetch gets at most `start_timeout_s` (the
        supervisor awaits `start()`, so boot never waits longer on the
        exchange); a fetch still running then is abandoned, and the schedule
        retries it on the short backoff, as after any failed refresh. #2702:
        it counts `result="timeout"` and a warm snapshot it never replaced is
        served stale (no further await: boot stays bounded)."""
        try:
            persisted = [
                Instrument.model_validate(row) for row in await self._repository.load_all()
            ]
        except Exception:  # storage tier down or a row fails validation
            get_logger(__name__).warning("instruments_startup_load_failed")
            persisted = []
        if persisted:
            self.cache.swap(
                CatalogueSnapshot(
                    by_symbol={i.symbol: i for i in persisted}, fetched_at_us=self._now_us()
                )
            )
        warm = self.cache.current()
        loaded, self._starting = False, True
        try:
            async with asyncio.timeout(self._start_timeout_s):
                await self.refresh_now()
            loaded = True
        except InstrumentRefreshError:
            # "Catalogue loaded at startup" still wants *some* snapshot to
            # serve; the persisted load above already covered that. A
            # startup fetch failure is not fatal — the periodic task retries
            # it on the short backoff (#2599).
            get_logger(__name__).warning("instruments_startup_refresh_failed")
        except TimeoutError:
            instruments_refresh_total.labels(result="timeout").inc()
            # Never re-validated: serve the warm (persisted) snapshot stale until a refresh
            # loads; the schedule's retry, if it fails, persists the same mark.
            if warm is not None and warm.stale_since_us is None and self.cache.current() is warm:
                self.cache.mark_stale(stale_since_us=self._now_us())
            get_logger(__name__).warning(
                "instruments_startup_refresh_timeout", timeout_s=self._start_timeout_s
            )
        finally:
            self._starting = False
        self._stopping = False
        self._task = spawn(self._run_periodic(startup_ok=loaded), name="instruments-refresh")

    async def stop(self, grace_s: float = 5.0) -> None:
        """Cancel the schedule and the shared on-demand refresh (#2702), awaiting both for up
        to `grace_s`. A cancellation of the caller of `stop()` propagates."""
        self._stopping = True
        tasks = [task for task in (self._task, self._on_demand) if task is not None]
        tasks += self._tier_kicks
        self._task = self._on_demand = None
        self._tier_kicks = set()
        for task in tasks:
            task.cancel()
        try:
            # The shield keeps `wait_for` from cancelling them twice; `gather` returns their
            # cancellations as results, so only this caller's own cancellation is raised.
            await asyncio.wait_for(
                asyncio.shield(asyncio.gather(*tasks, return_exceptions=True)), timeout=grace_s
            )
        except TimeoutError:
            pass

    # -- on-demand refresh (ticket "unknown symbol" + "Refresh does not ----
    # -- stall readers" scenarios) -------------------------------------------

    def add_listener(self, listener: Callable[[], Awaitable[None]]) -> None:
        """Awaited after every successful catalogue swap (#1913: delist teardown)."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def snapshot(self) -> CatalogueSnapshot | None:
        """Current snapshot (O(1), no I/O) for readers such as the API."""
        return self.cache.current()

    async def ensure_symbol(self, symbol: str) -> Instrument | None:
        """ "Refresh without restart" on-demand path: if `symbol` is not in
        the current snapshot, force one refresh and re-check. Returns the
        (possibly newly-fetched) instrument, or `None` if it still is not
        found after the refresh (unknown to the exchange, not just stale).

        #2702: the refresh is one shared task that a concurrent caller joins
        (one upstream fetch). A caller waits on it through `asyncio.shield`
        for at most `on_demand_timeout_s`, so neither its deadline nor its
        cancellation cancels the refresh, then raises
        `InstrumentRefreshPendingError` (the route answers 503); the refresh
        runs on until it ends or `stop()` cancels it."""
        current = self.cache.current()
        if current is not None and current.get(symbol) is not None:
            return current.get(symbol)
        refresh = self._on_demand
        if refresh is None or refresh.done():
            if self._stopping:
                raise InstrumentRefreshPendingError("instrument catalogue scheduler stopped")
            # Unknown-symbol lookups are caller-controlled: throttle the upstream
            # fetch so a burst of bogus symbols cannot exhaust the REST budget.
            now = self._now_us()
            if (
                self._last_on_demand_us is not None
                and now - self._last_on_demand_us < self._on_demand_cooldown_s * 1_000_000
            ):
                instruments_refresh_total.labels(result="throttled").inc()
                return None
            self._last_on_demand_us = now
            refresh = self._on_demand = spawn(
                self._refresh_on_demand(seen=current), name="instruments-refresh-on-demand"
            )
        await self._join(refresh, self._on_demand_timeout_s)
        refreshed = self.cache.current()
        return refreshed.get(symbol) if refreshed is not None else None

    async def ensure_risk_limits(self, symbol: str) -> tuple[RiskLimitTier, ...] | None:
        """S-RL (#913): `symbol`'s risk-limit tiers, fetched on first demand and kept in the
        snapshot (then refreshed with the catalogue). `None` when they are unknown: no fetcher
        wired, no catalogue, a symbol outside it (no upstream call for it), or a fetch that failed
        or missed `on_demand_timeout_s`, or a symbol whose last fetch failed less than
        `on_demand_cooldown_s` ago (no upstream call: a failing venue is not hit per request); the
        caller fails closed. The fetch runs under the refresh lock, so it never races a refresh's
        swap, and a concurrent caller re-checks after it. A symbol joins the refreshed set only
        once a fetch succeeded.
        """
        current = self.cache.current()
        if self._fetch_risk_limits is None or current is None or current.get(symbol) is None:
            return None
        known = current.risk_limit_tiers(symbol)
        if known is not None or self._tier_cooling(symbol):
            return known
        fetched = False
        try:
            async with asyncio.timeout(self._on_demand_timeout_s), self._refresh_lock:
                snap = self.cache.current() or current  # a loaded cache is never unloaded
                known = snap.risk_limit_tiers(symbol)
                if known is not None or self._tier_cooling(symbol):
                    return known
                fetched = True
                tiers = tuple(await self._fetch_risk_limits(symbol))
                if len(self._tier_symbols) < TIER_SYMBOLS_MAX:
                    self._tier_symbols.add(symbol)
                self._tier_failed_us.pop(symbol, None)
                self.cache.swap(
                    dataclasses.replace(snap, risk_limits={**snap.risk_limits, symbol: tiers})
                )
                return tiers
        except Exception as exc:  # a timeout too: unknown, and the caller fails closed
            if fetched:  # a wait on the lock alone never called the venue
                self._tier_failed_us[symbol] = self._now_us()
            get_logger(__name__).warning(
                "risk_limits_fetch_failed", symbol=symbol, error=type(exc).__name__
            )
            return None

    def request_tiers(self, symbol: str) -> TierRequestDrop | None:
        """S4-S-d (#913): the order path asks for `symbol`'s tiers, never waiting: a listed,
        not `closed` symbol with no tiers joins the refreshed set (within `TIER_SYMBOLS_MAX`) and
        its fetch is kicked as a task here, through `ensure_risk_limits` (its timeout, cooldown and
        the adapter's `MARKET_DATA` bucket), at most once per `TIER_REQUEST_WINDOW_S`. Answers why
        it dropped the request: `full`, `TIER_REQUESTS_MAX` symbols already kicked in the window,
        or `stopped`; None otherwise, a request with nothing to do (known tiers, an unlisted
        symbol, a kick in the window) included."""
        if self._stopping:
            return "stopped"
        current = self.cache.current()
        if self._fetch_risk_limits is None or current is None:
            return None
        listed = current.get(symbol)
        if listed is None or listed.status == "closed":
            return None
        if current.risk_limit_tiers(symbol) is not None:
            return None
        now = self._now_us()
        window_us = TIER_REQUEST_WINDOW_S * 1_000_000
        kicked = {s: at for s, at in self._tier_kicked_us.items() if now - at < window_us}
        self._tier_kicked_us = kicked
        if symbol in kicked:
            return None
        if len(kicked) >= TIER_REQUESTS_MAX:
            return "full"
        kicked[symbol] = now
        if len(self._tier_symbols) < TIER_SYMBOLS_MAX:
            self._tier_symbols.add(symbol)
        task = spawn(self.ensure_risk_limits(symbol), name="instruments-tier-request")
        self._tier_kicks.add(task)
        task.add_done_callback(self._tier_kicks.discard)
        return None

    def _tier_cooling(self, symbol: str) -> bool:
        """S-RL: `symbol`'s last tier fetch failed less than `on_demand_cooldown_s` ago."""
        failed_us = self._tier_failed_us.get(symbol)
        return (
            failed_us is not None
            and self._now_us() - failed_us < self._on_demand_cooldown_s * 1_000_000
        )

    async def _refresh_risk_limits(
        self, parsed: Mapping[str, Instrument]
    ) -> dict[str, tuple[RiskLimitTier, ...]]:
        """S-RL: re-fetch every refreshed symbol, seeded first (S4-S-c, `_tier_set`), within one
        overall `risk_limits_budget_s` (a quarter of `start_timeout_s` at most in `start()`). A
        symbol whose fetch fails, or that the budget does not reach, is left out (unknown, fail
        closed; the previous ladder is not kept), stays in the set for the next refresh, and does
        not fail the catalogue refresh.
        """
        fetch = self._fetch_risk_limits
        tiers: dict[str, tuple[RiskLimitTier, ...]] = {}
        if fetch is None:
            return tiers
        seed, seed_ok = await self._order_path_seed()
        pending = self._tier_set(parsed, seed)
        self._tier_symbols = set(pending)
        budget_s = self._risk_limits_budget_s
        if self._starting:
            budget_s = min(budget_s, self._start_timeout_s / 4)
        gate = asyncio.Semaphore(TIER_FETCH_CONCURRENCY)

        async def one(symbol: str) -> None:
            async with gate:  # FIFO: the seeded symbols, first in `pending`, are fetched first
                try:
                    async with asyncio.timeout(RISK_LIMITS_FETCH_TIMEOUT_S):
                        tiers[symbol] = tuple(await fetch(symbol))
                except Exception as exc:  # the budget's cancellation is not an Exception
                    self._tier_failed_us[symbol] = self._now_us()
                    get_logger(__name__).warning(
                        "risk_limits_fetch_failed", symbol=symbol, error=type(exc).__name__
                    )

        try:
            async with asyncio.timeout(budget_s):
                async with asyncio.TaskGroup() as group:
                    for symbol in pending:
                        spawn_child(group, one(symbol), name="instruments-risk-limits-fetch")
        except TimeoutError:
            get_logger(__name__).warning(
                "risk_limits_refresh_budget_spent",
                budget_s=budget_s,
                unknown=len(pending) - len(tiers),
            )
        self._tiers_incomplete = len(tiers) < len(pending) or not seed_ok
        self._tiers_streak = self._tiers_streak + 1 if self._tiers_incomplete else 0
        return tiers

    async def _order_path_seed(self) -> tuple[list[str], bool]:
        """S4-S-c: the order path's symbols (`order_path_symbols`) in its rank order, within
        `ORDER_PATH_SEED_TIMEOUT_S`, and whether the read succeeded. Empty and ok when none is
        wired; empty and not ok when the read fails (logged by the error's type only), which
        makes the tier refresh incomplete so the short retry applies."""
        read = self._order_path_symbols
        if read is None:
            return [], True
        since_us = self._now_us() - ORDER_PATH_WINDOW_S * 1_000_000
        try:
            async with asyncio.timeout(ORDER_PATH_SEED_TIMEOUT_S):
                ranked = await read(since_us=since_us, limit=TIER_SYMBOLS_MAX)
                return list(dict.fromkeys(ranked)), True
        except Exception as exc:  # a timeout too: this tick refreshes the symbols already held
            get_logger(__name__).warning("risk_limits_seed_failed", error=type(exc).__name__)
            return [], False

    def _tier_set(self, parsed: Mapping[str, Instrument], seed: list[str]) -> list[str]:
        """S4-S-c: the seed in its rank order, then the symbols already held, at most
        `TIER_SYMBOLS_MAX`, and only those the catalogue lists and not `closed`: a delisted
        symbol leaves, a failed one stays. (A `closed` symbol that re-enters on demand is
        dropped again at the next refresh.)"""
        listed = {symbol for symbol, i in parsed.items() if i.status != "closed"}
        held = sorted((self._tier_symbols - set(seed)) & listed)
        return [*(s for s in seed if s in listed), *held][:TIER_SYMBOLS_MAX]

    async def ensure_fresh(self, max_age_s: float, deadline_s: float) -> CatalogueSnapshot | None:
        """#906 (B8): the catalogue, fetched at most `max_age_s` ago and not marked stale, so the
        exchange limits a profile save is judged against were confirmed lately. A snapshot that
        fits returns at once, with no fetch. Otherwise the refresh is `ensure_symbol`'s shared task
        (#2702), started if none runs and joined if one does: concurrent callers cost one upstream
        fetch. A caller waits on it through `asyncio.shield` for at most `deadline_s`, so neither
        its deadline nor its cancellation cancels the refresh, then raises
        `InstrumentRefreshPendingError` (the HTTP edge maps it to 503); the refresh runs on for
        the next caller until it ends or `stop()` cancels it. A refresh that ends with no fitting
        catalogue (it failed, or nothing is loaded) raises `InstrumentRefreshError`. `ValueError`
        for a bound that is not positive and finite.
        No cooldown, unlike `ensure_symbol`, by design: callers must be authenticated and
        rate-bounded (today the Owner's profile save), and a failing call costs up to
        `max_retries` fetches.

        `None` is part of the type but never the answer: no fresh catalogue is an error."""
        if not (0 < max_age_s < math.inf and 0 < deadline_s < math.inf):
            raise ValueError(
                f"max_age_s and deadline_s must be positive and finite, got {max_age_s!r} "
                f"and {deadline_s!r}"
            )
        current = self.cache.current()
        if self._is_fresh(current, max_age_s):
            return current
        refresh = self._on_demand
        if refresh is None or refresh.done():
            if self._stopping:
                raise InstrumentRefreshPendingError("instrument catalogue scheduler stopped")
            refresh = self._on_demand = spawn(
                self._refresh_on_demand(seen=current), name="instruments-refresh-on-demand"
            )
        await self._join(refresh, deadline_s)
        refreshed = self.cache.current()
        if not self._is_fresh(refreshed, max_age_s):
            raise InstrumentRefreshError("instrument catalogue refresh failed")
        return refreshed

    async def refresh_now(self) -> None:
        """One refresh attempt, retried with full jitter up to
        `max_retries` times. Never lets two concurrent callers (the
        periodic task and an on-demand trigger) race each other's fetch —
        guarded by `self._refresh_lock`."""
        async with self._refresh_lock:
            await self._refresh_with_retry()

    # -- internals -----------------------------------------------------------

    async def _join(self, refresh: asyncio.Task[None], deadline_s: float) -> None:
        """Wait on the shared refresh (#2702) for at most `deadline_s` through `asyncio.shield`,
        so neither the deadline nor this caller's cancellation cancels it; at the deadline raise
        `InstrumentRefreshPendingError`, as when `stop()` cancels the refresh under this caller."""
        try:
            async with asyncio.timeout(deadline_s):
                await asyncio.shield(refresh)
        except TimeoutError as exc:
            raise InstrumentRefreshPendingError(
                f"catalogue refresh still running after {deadline_s} s"
            ) from exc
        except asyncio.CancelledError:
            # The shield passes on `stop()` cancelling the refresh: no answer, as at the
            # deadline. A cancellation of this caller itself always propagates.
            caller = asyncio.current_task()
            if not refresh.cancelled() or (caller is not None and caller.cancelling()):
                raise
            raise InstrumentRefreshPendingError("instrument catalogue scheduler stopped") from None

    def _is_fresh(self, snapshot: CatalogueSnapshot | None, max_age_s: float) -> bool:
        """#906: loaded, fetched at most `max_age_s` ago, and not marked stale. The mark counts on
        its own, as in `InstrumentCatalogueCache.is_stale`: `start()` stamps a persisted copy with
        the boot time, so after a failed startup fetch an old copy is young by its age alone."""
        return (
            snapshot is not None
            and snapshot.stale_since_us is None
            and snapshot.age_seconds(now_us=self._now_us()) <= max_age_s
        )

    async def _refresh_on_demand(self, *, seen: CatalogueSnapshot | None) -> None:
        """The shared on-demand refresh task (#2702); `seen` is the snapshot its first caller
        could not use (it lacked the symbol, or `ensure_fresh` found it too old or stale).
        Re-checked after the lock: a refresh it queued behind (the schedule's) that loaded a
        catalogue makes this fetch moot. A failure is logged (and counted) like any refresh's; each
        caller judges what is loaded (`ensure_symbol` answers from it, `ensure_fresh` raises
        unless it is fresh)."""
        try:
            async with self._refresh_lock:
                current = self.cache.current()
                # A load swaps in a new, unmarked snapshot; a failure only marks a copy stale.
                if current is not None and current is not seen and current.stale_since_us is None:
                    return
                await self._refresh_with_retry()
        except InstrumentRefreshError:
            pass  # logged and counted by `_refresh_with_retry`
        except Exception:
            get_logger(__name__).exception("instruments_on_demand_refresh_unexpected_error")

    async def _refresh_with_retry(self) -> None:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                await self._refresh_once()
                instruments_refresh_total.labels(result="ok").inc()
                return
            except Exception as exc:
                last_error = exc
                if attempt < self._max_retries - 1:
                    backoff = min(_MAX_BACKOFF_S, _MIN_BACKOFF_S * (2**attempt))
                    jitter = backoff * self._random()
                    await self._sleep(jitter)
        instruments_refresh_total.labels(result="error").inc()
        # Keep the *first* failure time: `stale_since` means "since when",
        # so consecutive failures must not keep pushing it forward.
        snap = self.cache.current()
        prior = snap.stale_since_us if snap is not None else None
        stale_since_us = prior if prior is not None else self._now_us()
        self.cache.mark_stale(stale_since_us=stale_since_us)
        self._failed.set()
        try:
            await self._repository.mark_stale(stale_since_us=stale_since_us)
        except Exception:
            get_logger(__name__).warning("instruments_mark_stale_persist_failed")
        get_logger(__name__).warning("instruments_refresh_failed", error=str(last_error))
        raise InstrumentRefreshError(
            f"instrument catalogue refresh failed after {self._max_retries} attempts"
        ) from last_error

    async def _refresh_once(self) -> None:
        result = await self._fetch_instruments_info(self._now_us)
        fetched_at_us = max((i.fetched_at for i in result.instruments), default=self._now_us())
        current = self.cache.current()

        for rejected in result.rejected:
            get_logger(__name__).warning(
                "instruments_refresh_skipped_row",
                symbol=rejected.symbol,
                error=rejected.reason,
            )

        parsed: dict[str, Instrument] = {}
        for item in result.instruments:
            previous = current.get(item.symbol) if current is not None else None
            versioned, changed_fields = next_version(previous, item)
            parsed[versioned.symbol] = versioned
            if changed_fields:
                await self._repository.record_version(
                    versioned.model_dump(mode="json"), changed_fields=changed_fields
                )
                if self._publish is not None:
                    event = build_updated_event(
                        event_id=uuid4(),
                        symbol=versioned.symbol,
                        metadata_version=versioned.metadata_version,
                        changed_fields=changed_fields,
                        ts_now_us=fetched_at_us,
                    )
                    await self._publish(event)

        if not parsed:
            raise InstrumentRefreshError("instrument fetch returned zero parseable rows")

        # Symbols the cache already had that did not reappear in this fetch
        # keep their last-known record (never silently dropped mid-refresh —
        # a transient short page must not make a symbol vanish); the exchange
        # normally only *adds* symbols or flips `status` to `Closed`, so this is a
        # defensive merge, not the normal path.
        if current is not None:
            for symbol, instrument in current.by_symbol.items():
                parsed.setdefault(symbol, instrument)

        risk_limits = await self._refresh_risk_limits(parsed)
        await self._repository.upsert_snapshot([i.model_dump(mode="json") for i in parsed.values()])
        self.cache.swap(
            CatalogueSnapshot(
                by_symbol=parsed, fetched_at_us=fetched_at_us, risk_limits=risk_limits
            )
        )
        self._failed.clear()
        instruments_cache_age_seconds.set(0.0)
        instruments_catalogue_size.set(len(parsed))
        for listener in self._listeners:
            try:
                await listener()
            except Exception:  # a consumer fault must not fail the refresh
                get_logger(__name__).exception("instruments_listener_failed")

    async def _run_periodic(self, *, startup_ok: bool) -> None:
        """The refresh schedule: the TTL (+ up to 5 % jitter) after a successful refresh, and
        `retry_backoff_s` after a failed or abandoned one (#2599: a failed cold start used to
        wait the TTL, serving nothing; #2715: so after a failure during the TTL wait, too).
        An on-demand refresh does not change this wait. `stop()` cancels it; the cancellation
        propagates."""
        ok, failures = startup_ok, 0
        while not self._stopping:
            if ok:
                failures = 0
                delay = self._ttl_seconds + self._ttl_seconds * 0.05 * self._random()
                if self._tiers_incomplete:  # S4-S-c: seeded tiers still unknown: retry soon
                    delay = min(delay, TIERS_RETRY_S * 2.0 ** min(self._tiers_streak - 1, 16))
                if not await self._ttl_wait(delay):
                    ok = False  # an (on-demand) refresh failed meanwhile: retry soon
                    continue
            else:
                failures += 1
                await self._sleep(retry_backoff_s(failures, self._random()))
            if self._stopping:
                return
            ok = await self._scheduled_refresh()
            current = self.cache.current()
            if current is not None:
                instruments_cache_age_seconds.set(current.age_seconds(now_us=self._now_us()))

    async def _ttl_wait(self, delay: float) -> bool:
        """Sleep `delay`; `False` if a refresh fails first (#2715). Both waiters are owned
        here: cancelled and awaited on the way out, on `stop()` too."""

        async def ttl() -> None:
            await self._sleep(delay)

        sleeper = spawn(ttl(), name="instruments-refresh-ttl")
        failure = spawn(self._failed.wait(), name="instruments-refresh-failure")
        try:
            done, _ = await asyncio.wait((sleeper, failure), return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeper.cancel()
            failure.cancel()
            await asyncio.gather(sleeper, failure, return_exceptions=True)
        return sleeper in done

    async def _scheduled_refresh(self) -> bool:
        """One scheduled refresh; `True` if it loaded. A failure is already logged and counted
        in `_refresh_with_retry`; anything unexpected is logged and never ends the schedule."""
        try:
            await self.refresh_now()
        except InstrumentRefreshError:
            return False
        except Exception:
            get_logger(__name__).exception("instruments_periodic_refresh_unexpected_error")
            return False
        return True
