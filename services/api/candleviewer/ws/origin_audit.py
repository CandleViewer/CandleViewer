"""Bounded `auth.ws_origin_refused` audit for refused WS upgrades (#2269, `23-ws-protocol.md` §2.5).

An upgrade refused by the SR-042 / SR-183 `Origin` check is closed `4403` before `accept`. Each
refusal also writes one `auth.ws_origin_refused` record (C-2.9): `actor_ip` is the source address
MeshOnly admitted, `reason` the bounded check (`OriginRefusal`), `object_kind` `ws_upgrade`,
outcome `failure`, severity `warning`. It never carries a header value.

The writes are bounded as the REST CSRF refusals are (C-2.18, `api/csrf.py`):

- per source address, `REFUSAL_AUDITS_PER_WINDOW` records per `REFUSAL_AUDIT_WINDOW_S`; past that
  the upgrade is still refused and counted (`cv_ws_closes_total{reason="origin_forbidden"}`), and no
  record is written;
- the app's shared refusal-audit tracker (`api.csrf.RefusalAuditTracker`, injected because `ws`
  may not import `api`): one global cap on refusal audits in flight, REST and WS together, and one
  bounded drain at shutdown;
- the write is a tracked task under `asyncio.shield`, awaited for at most `timeout_s`: a slow write
  is left to finish (never cancelled mid-append) and a failed one is logged. Either way the caller
  closes `4403` next, so the upgrade is never admitted. Each is counted once, when the wait ends,
  in `cv_ws_audit_failures_total` (`timeout` or `error`; SR-E17-04, #2174).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, Final, Protocol

import structlog

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.ws.lifecycle import OriginRefusal
from candleviewer.ws.metrics import count_audit_failure
from candleviewer.ws.permissions import AuditSink

OBJECT_KIND: Final = "ws_upgrade"
#: Audited refusals per source address per window (the REST CSRF per-IP budget).
REFUSAL_AUDITS_PER_WINDOW: Final = 20
REFUSAL_AUDIT_WINDOW_S: Final = 60.0
#: Longest a refusal waits for its record before the close (the REST refusal-audit bound).
REFUSAL_AUDIT_TIMEOUT_S: Final = 2.0
#: The actor label (no user is known before `auth`), and the budget key when no source address is.
_UNKNOWN: Final = "(unknown)"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class RefusalAudits(Protocol):
    """The app's in-flight refusal-audit tracker (`api.csrf.RefusalAuditTracker`)."""

    @property
    def full(self) -> bool: ...

    def track(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]: ...

    def mark_timed_out(self, task: asyncio.Task[None]) -> None: ...


class OriginRefusalAudit:
    """Writes one `auth.ws_origin_refused` record per refused upgrade, within the bounds above."""

    def __init__(
        self,
        audit: AuditSink,
        *,
        tracker: RefusalAudits,
        budget: PerIpLoginThrottle | None = None,
        timeout_s: float = REFUSAL_AUDIT_TIMEOUT_S,
    ) -> None:
        self._audit = audit
        self._tracker = tracker
        self._budget = budget or PerIpLoginThrottle(
            max_attempts=REFUSAL_AUDITS_PER_WINDOW, window_s=REFUSAL_AUDIT_WINDOW_S
        )
        self._timeout_s = timeout_s

    def _admit(self, key: str) -> bool:
        """True when a write may start: the in-flight cap has room and *key* has budget left,
        which this spends."""
        if self._tracker.full or self._budget.is_blocked(key):
            return False
        self._budget.record_failure(key)
        return True

    async def record(self, check: OriginRefusal, source_ip: str | None) -> bool:
        """Audit one refusal; True when its write started. Waits at most `timeout_s` and never
        raises a write's failure, so the caller's `4403` follows within that bound."""
        if not self._admit(source_ip or _UNKNOWN):
            return False
        task = self._tracker.track(
            self._audit.emit(
                "auth.ws_origin_refused",
                actor_label=_UNKNOWN,
                actor_ip=source_ip,
                object_kind=OBJECT_KIND,
                outcome=AuditOutcome.FAILURE,
                severity=Severity.WARNING,
                reason=check.value,
            )
        )
        try:
            await asyncio.wait_for(asyncio.shield(task), self._timeout_s)
        except TimeoutError:
            self._tracker.mark_timed_out(task)  # left to finish; the tracker reports a late failure
            count_audit_failure(reason="timeout")
            _log().warning("auth.ws_origin_refused.audit_slow", check=check.value)
        except asyncio.CancelledError:
            self._tracker.mark_timed_out(task)  # nobody awaits it now; the cancel still propagates
            raise
        except Exception as exc:
            count_audit_failure(reason="error")
            _log().error(
                "auth.ws_origin_refused.audit_unavailable",
                check=check.value,
                error=type(exc).__name__,
            )
        return True
