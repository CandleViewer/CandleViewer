"""The replay anchor's answers (E29-T04 #913; 21-database-schema.md Sec.3.3.10 "Repeats", 24
Sec.8.4): what a `placeOrder` request is answered when its principal sent its key before, read
from the permanent anchor (SR-E29-07) before anything is written or sent.

`AnchorService.lookup(created_by, client_ref, request_sha256)` answers one of four:

* `Fresh`: the principal holds no `placeOrder` anchor of the key, so the request is a first
  submission; another principal's key reads as one never seen;
* `KeyReuse`: the anchor's fingerprint is another request's: `409 idempotency_key_reuse`;
* `Replay(anchor)`: the anchor is decided, and the repeat gets its recorded outcome and sends
  nothing: a `202` with the rows it names in their current state, or the `429` or `502` it
  recorded, with no `Retry-After` (22 `placeOrder`: a recorded `429` is not retryable under its
  key);
* `InFlight(retry_after_s)`: undecided within `stuck_after_s` of its creation
  (`CV_OMS_INFLIGHT_STUCK_S`, 30 s): `409 idempotency_in_flight` with `Retry-After`.

Past `stuck_after_s` an undecided anchor's request ended without recording its answer (a crash,
or a store failure after the send): the repeat decides it `202`, by compare-and-set from none, and
replays it; when another repeat decided it first, it reads and replays that one's outcome. A repeat
never sends (24 Sec.8.4): only the first request starts its order's send.

`after_taken` answers a first persist that met the key held (`AnchorTaken`): it reads the anchor
as `lookup` does, and when the principal holds no `placeOrder` anchor of the key, the key the
persist met is a `createTradeGroup` group's (`ux_tg_creator_ref`, the group's twin of the key), so
the request is `KeyReuse` (21 Sec.3.3.10), read off the constraint with no trade-group read.
`record` records the first answer of a request by compare-and-set.

Every store call is bounded by `timeout_s`; one past it, or a store failure, is `StoreUnavailable`,
nothing having been sent. No log line carries the key or the fingerprint (21 Sec.12, C-12.6).
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, cast
from uuid import UUID

import structlog

from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.idempotency_anchors import (
    AnchorOperation,
    AnchorOutcome,
    AnchorRow,
)
from candleviewer.storage.repositories.orders import OrderStoreError
from candleviewer.storage.repositories.submissions import UX_TG_CREATOR_REF, AnchorConstraint

from .errors import IdempotencyInFlight, IdempotencyKeyReuse, StoreUnavailable
from .repository import IdempotencyAnchorRepository

__all__ = [
    "IN_FLIGHT_RETRY_S", "STUCK_AFTER_S", "AnchorService", "Fresh", "InFlight", "KeyReuse",
    "Lookup", "Replay",
]  # fmt: skip

#: `CV_OMS_INFLIGHT_STUCK_S`'s default (21 Sec.3.3.10): longer than the submission's own bounds,
#: so an anchor still undecided past it belongs to a request that ended.
STUCK_AFTER_S: Final = 30.0
#: The `Retry-After` of an anchor in flight: its request answers within its own bounds, so a
#: repeat a second later most likely meets the outcome it recorded.
IN_FLIGHT_RETRY_S: Final = 1


@dataclass(frozen=True, slots=True)
class Fresh:
    """No `placeOrder` anchor of the key for the principal: a first submission."""


@dataclass(frozen=True, slots=True)
class Replay:
    """The key's anchor, decided: the repeat answers its outcome, and sends nothing."""

    anchor: AnchorRow


@dataclass(frozen=True, slots=True)
class InFlight:
    """The key's first request is still being processed."""

    retry_after_s: int

    def refusal(self) -> IdempotencyInFlight:
        return IdempotencyInFlight(retry_after_s=self.retry_after_s)


@dataclass(frozen=True, slots=True)
class KeyReuse:
    """The key was first used with another request, or for a trade group."""

    def refusal(self) -> IdempotencyKeyReuse:
        return IdempotencyKeyReuse()


type Lookup = Fresh | Replay | InFlight | KeyReuse


def _log() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


def _seconds(name: str, value: float) -> float:
    """A bound in seconds: finite and above zero, as NaN or infinity bounds nothing (C-2.18)."""
    if isinstance(value, bool) or not (
        isinstance(value, int | float) and math.isfinite(value) and value > 0
    ):
        raise ValueError(f"{name} must be a finite number of seconds above zero")
    return float(value)


class AnchorService:
    """The anchor's reads and its decisions (module docstring), over the M14 repository."""

    def __init__(
        self,
        anchors: IdempotencyAnchorRepository,
        *,
        clock: Callable[[], datetime],
        timeout_s: float,
        stuck_after_s: float = STUCK_AFTER_S,
    ) -> None:
        self._anchors = anchors
        self._clock = clock
        self._timeout_s = _seconds("timeout_s", timeout_s)
        self._stuck_after_s = _seconds("stuck_after_s", stuck_after_s)

    @property
    def stuck_after_s(self) -> float:
        """`CV_OMS_INFLIGHT_STUCK_S` as this service applies it: past it, a repeat decides an
        undecided anchor (module docstring). The pipeline's bounds after the anchor must total
        under it (`OrderSubmission`, D-2B2-01)."""
        return self._stuck_after_s

    async def lookup(
        self,
        created_by: UUID,
        client_ref: UUID,
        request_sha256: str,
        *,
        operation: AnchorOperation = "placeOrder",
    ) -> Lookup:
        """The answer of a request whose key `created_by` may have sent before, on `operation`
        (`placeOrder`, or E29-T07's `closePosition` and `reversePosition`, 21 Sec.3.3.10)."""
        find = self._anchors.find(created_by, client_ref, request_sha256, operation=operation)
        found = await self._bounded(find)
        if found is None:
            return Fresh()
        return await self._answer(found, created_by, client_ref, request_sha256, operation)

    async def after_taken(
        self,
        constraint: AnchorConstraint,
        created_by: UUID,
        client_ref: UUID,
        request_sha256: str,
        *,
        operation: AnchorOperation = "placeOrder",
    ) -> Lookup:
        """The answer of a first persist refused because the key is held (`AnchorTaken`)."""
        find = self._anchors.find(created_by, client_ref, request_sha256, operation=operation)
        found = await self._bounded(find)
        if found is not None:
            return await self._answer(found, created_by, client_ref, request_sha256, operation)
        if constraint == UX_TG_CREATOR_REF:
            _log().info("oms_idempotency_key_reuse", user_id=str(created_by), held_by="trade_group")
            return KeyReuse()
        # The anchor's own index refused the key, yet no read finds it: the store is not serving
        # what it holds, and nothing has been sent.
        _log().error("oms_anchor_taken_unread", user_id=str(created_by), constraint=constraint)
        raise StoreUnavailable

    async def record(self, anchor_id: UUID, outcome: AnchorOutcome) -> bool:
        """Record the request's first answer by compare-and-set: False when one is recorded."""
        return await self._bounded(self._anchors.record_outcome(anchor_id, outcome))

    async def _answer(
        self,
        anchor: AnchorRow,
        created_by: UUID,
        client_ref: UUID,
        request_sha256: str,
        operation: AnchorOperation,
    ) -> Lookup:
        ids = {"anchor_id": str(anchor.id), "user_id": str(created_by)}
        if not anchor.body_matches:
            _log().info("oms_idempotency_key_reuse", **ids, held_by="place_order")
            return KeyReuse()
        if anchor.outcome_status is not None:
            _log().info("oms_anchor_replayed", **ids, status=anchor.outcome_status)
            return Replay(anchor)
        now = self._clock()
        if (now - anchor.created_at).total_seconds() < self._stuck_after_s:
            _log().info("oms_anchor_in_flight", **ids)
            return InFlight(IN_FLIGHT_RETRY_S)
        decided = AnchorOutcome(status=202, decided_at=now)
        if await self.record(anchor.id, decided):
            _log().warning("oms_anchor_decided_stale", **ids)
            return Replay(replace(anchor, outcome_status=202, decided_at=now))
        find = self._anchors.find(created_by, client_ref, request_sha256, operation=operation)
        winner = await self._bounded(find)
        if winner is None or winner.outcome_status is None:  # the compare-and-set said decided
            _log().error("oms_anchor_decision_unread", **ids)
            raise StoreUnavailable
        _log().info("oms_anchor_replayed", **ids, status=winner.outcome_status)
        return Replay(winner)

    async def _bounded[T](self, call: Awaitable[T]) -> T:
        """`call` within `timeout_s`; past it, or failed in the store, `StoreUnavailable`."""
        try:
            async with asyncio.timeout(self._timeout_s):
                return await call
        except (TimeoutError, StorageError, OrderStoreError) as exc:
            _log().warning("oms_anchor_store_unavailable", failure=type(exc).__name__)
            raise StoreUnavailable from None
