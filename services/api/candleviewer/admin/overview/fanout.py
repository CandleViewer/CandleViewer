"""Partial-result fan-out core of the admin read models (E42-T01, module M21).

SCR-120 must "never block on the slowest subsystem", so each slice is read from its own source
through `SliceFanOut.read`: under its own `asyncio.timeout` budget (300 ms); with every failure
contained (a timeout or exception becomes an `error` slice, `SourceUnavailable` an `unavailable`
one, and only cancellation propagates); and through a per-slice 5 s TTL cache on an injected
monotonic clock. Every outcome is cached, errors too, so reloads never hammer a struggling
source; kill-switch and flag reads opt out (`cached=False`). Concurrent reads of one slice share
a single in-flight source call; `invalidate` makes the next read refetch (read-after-write).
Callers fan out with `asyncio.gather(fan.read(...), ...)`, which owns the reads and cancels
them with the request; a stray `CancelledError` from a source only fails its own slice.
A degraded run logs `source`, `reason` and `request_id`; every run is timed, errors counted.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, cast

import structlog

from candleviewer.admin.overview.metrics import source_duration_seconds, source_errors_total
from candleviewer.admin.overview.slices import AdminSlice
from candleviewer.observability.context import current_request_id

SliceStatus = Literal["ok", "error", "unavailable"]

DEFAULT_BUDGET_S: Final = 0.3
DEFAULT_TTL_S: Final = 5.0
#: The only `detail` for an exception: its message may carry a DSN or a key, so it never leaves.
FAILED_DETAIL: Final = "source failed"
#: A seatbelt only: the real protection is that every `detail` is a fixed literal in code. This
#: rejects anything empty, over 200 chars or outside a charset that no DSN or key fits.
_DETAIL_RE: Final = re.compile(r"[A-Za-z0-9 _:.-]{1,200}")


def _checked(detail: str) -> str:
    """A violation raises inside the source, so the slice becomes `error` / "source failed"."""
    if not _DETAIL_RE.fullmatch(detail):
        raise ValueError("slice detail must be 1-200 chars of [A-Za-z0-9 _:.-]")
    return detail


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


def utc_now() -> datetime:
    """The one UTC clock of the admin read models (tz-aware)."""
    return datetime.now(UTC)


def _cancelling() -> bool:
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


@dataclass(frozen=True, slots=True)
class SliceResult[T]:
    """One slice: its value (absent when it could not be read), status, detail and read time."""

    status: SliceStatus
    generated_at: datetime
    value: T | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Degraded[T]:
    """What a source returns when it read only part of its slice: the part plus why."""

    value: T
    status: Literal["error", "unavailable"]
    detail: str
    #: Logged, never sent: the failed part and the exception class, e.g. `open_positions:OSError`.
    reason: str = "partial"

    def __post_init__(self) -> None:
        _checked(self.detail)


class SourceUnavailable(Exception):
    """Raised by a source whose provider is not wired yet: its slice is `unavailable`."""

    def __init__(self, detail: str) -> None:
        super().__init__(_checked(detail))
        self.detail = detail


class SliceFanOut:
    """Guarded, cached reads of named slices. One slice name always maps to one source."""

    def __init__(
        self,
        *,
        budget_s: float = DEFAULT_BUDGET_S,
        ttl_s: float = DEFAULT_TTL_S,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._budget_s, self._ttl_s = budget_s, ttl_s
        self._monotonic, self._now = monotonic, now
        self._timeout_detail = f"timed out after {round(budget_s * 1000)} ms"
        #: Both bounded by `AdminSlice`: (expires_at, result) and the one in-flight read.
        self._cache: dict[AdminSlice, tuple[float, SliceResult[object]]] = {}
        self._inflight: dict[AdminSlice, asyncio.Future[SliceResult[object]]] = {}

    async def read[T](
        self,
        name: AdminSlice,
        load: Callable[[], Awaitable[T | Degraded[T]]],
        *,
        cached: bool = True,
    ) -> SliceResult[T]:
        """The slice `name`: from the cache while fresh, else from `load` under the budget.

        A live read (`cached=False`) never joins a read already in flight: it would return a
        value captured before a kill-switch flip."""
        name = AdminSlice(name)  # runtime guard: the metric label stays bounded
        if not cached:
            return await self._run(name, load)
        hit = self._cache.get(name)
        if hit is not None and self._monotonic() < hit[0]:
            return cast(SliceResult[T], hit[1])
        if (shared := self._inflight.get(name)) is not None:
            try:
                return cast(SliceResult[T], await asyncio.shield(shared))
            except asyncio.CancelledError:
                if _cancelling():
                    raise
                return await self.read(name, load)  # the leader was cancelled
        fut: asyncio.Future[SliceResult[object]] = asyncio.get_running_loop().create_future()
        self._inflight[name] = fut
        try:
            result = await self._run(name, load)
            if self._inflight.get(name) is fut:  # not invalidated meanwhile
                self._cache[name] = (
                    self._monotonic() + self._ttl_s,
                    cast(SliceResult[object], result),
                )
            fut.set_result(cast(SliceResult[object], result))
            return result
        except BaseException:
            fut.cancel()
            raise
        finally:
            if self._inflight.get(name) is fut:
                del self._inflight[name]

    @property
    def budget_s(self) -> float:
        """The per-source budget; a source's own sub-budgets must stay below it."""
        return self._budget_s

    def invalidate(self, name: AdminSlice) -> None:
        """Drop the cached slice and detach a read already running (it may predate a write)."""
        self._cache.pop(name, None)
        self._inflight.pop(name, None)

    async def _run[T](
        self, name: AdminSlice, load: Callable[[], Awaitable[T | Degraded[T]]]
    ) -> SliceResult[T]:
        started = self._monotonic()
        result: SliceResult[T]
        budget = asyncio.timeout(self._budget_s)
        try:
            async with budget:
                got = await load()
        except TimeoutError:  # our budget expired, or the source raised its own TimeoutError
            expired = budget.expired()
            detail = self._timeout_detail if expired else FAILED_DETAIL
            result = self._degraded(
                name, "error", detail, "timeout" if expired else "TimeoutError", None
            )
        except asyncio.CancelledError:
            if _cancelling():  # the request itself is being cancelled: never swallow it
                raise
            result = self._degraded(name, "error", FAILED_DETAIL, "CancelledError", None)
        except SourceUnavailable as exc:
            result = self._degraded(name, "unavailable", exc.detail, "unavailable", None)
        except Exception as exc:  # contained by design (E42-T01): never all-or-nothing
            result = self._degraded(name, "error", FAILED_DETAIL, type(exc).__name__, None)
        else:
            if isinstance(got, Degraded):
                result = self._degraded(name, got.status, got.detail, got.reason, got.value)
            else:
                result = SliceResult("ok", self._now(), got)
        finally:
            source_duration_seconds.labels(name).observe(max(self._monotonic() - started, 0.0))
        return result

    def _degraded[T](
        self,
        name: AdminSlice,
        status: Literal["error", "unavailable"],
        detail: str,
        reason: str,
        value: T | None,
    ) -> SliceResult[T]:
        if status == "error":
            source_errors_total.labels(name).inc()
        log = logger().warning if status == "error" else logger().info
        log(
            "admin_overview.slice_degraded",
            source=name,
            status=status,
            reason=reason,
            request_id=current_request_id(),
        )
        return SliceResult(status, self._now(), value, detail)
