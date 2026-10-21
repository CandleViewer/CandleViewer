"""Alert delivery dispatcher: the `alert.deliver` outbox poller (E40-T04, PR 1 of 2).

Each firing already committed one `alert_deliveries` row per channel plus one outbox row per
queued delivery (E40-T03, `ux_outbox_dedup`). This poller leases ready outbox rows
(`FOR UPDATE SKIP LOCKED` + `locked_until`, so several workers are safe), runs the channel
adapter, and settles delivery + outbox row in one store call:

- adapters are only invoked for a delivery still in `queued`; `queued -> sent` is a
  conditional update, so a replay after restart is a no-op (exactly-once on the record);
- retry: `min(2**attempts, 300)` s with jitter in [0.5, 1.0], up to the row's `max_attempts`;
  `attempt` is mirrored onto `alert_deliveries.attempt`;
- terminal failure: delivery `failed` + `error_message`, outbox `dead_at`, and ONE in-app
  channel-failure notice in the same transaction. The alert record and the other channels'
  rows are never touched (US-ALRT-005: no channel is the source of truth);
- email is at-least-once for the external effect: a crash between the relay accepting the
  message and the settle commit re-sends it after the lease (60 s) expires. The outbox lease
  is the `sending` marker; the transport receives `idempotency_key` (stable per delivery
  id) and the E04 relay MUST dedupe on it. The record itself stays exactly-once;
- adapter errors pass through the C-12.6 redaction filter before they are stored; an
  adapter raising anything else is a retryable `adapter_error`, so a poison row
  dead-letters after `max_attempts` instead of looping once per lease;
- `stop()` lets the in-flight send finish (bounded by `grace_s`) before cancelling;
- the poll loop also samples the topic's backlog onto `cv_outbox_depth{topic}` (at most every
  `DEPTH_EVERY_S`, even while a backlog keeps every poll full); a read that fails or outlasts
  `DEPTH_TIMEOUT_S` is logged and never stops dispatching. `AlertOutboxBacklog` (over 100 for
  5 min) reads that gauge and `AlertOutboxDeadLettered` reads `cv_outbox_dead_total`
  (infra/prometheus/alerts);
- `suppressed` rows carry a bounded reason code (`SUPPRESSION_REASONS`) in
  `error_message` and `context.suppression_reason`;
- the owner gate (#3349, UL-F8) runs before any adapter, on a fresh read: a delivery whose owner is
  not active is settled `suppressed` / `owner_inactive` (`recipient_deleted` once the owner row is
  gone), final and not announced on the `alerts` topic; an owner whose status cannot be read leaves
  the row leased (read again after the lease, never dead-lettered). Both are counted;
- `webhook` (flag `alerts_webhook_enabled`, E40-S03) and `push` (out of scope) are
  registered but disabled -> `suppressed`. `desktop` awaits the Electron shell's outcome
  (report-back lands with the `alerts` WS topic, PR 2) and stays `queued` until then.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import structlog

from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER
from candleviewer.alerts.owners import OwnerGate, SkipReason
from candleviewer.observability import spawn
from candleviewer.observability.redaction import redact_text


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


MAX_BACKOFF_S = 300.0
#: `alert_deliveries.attempt` CHECK (0..10).
MAX_ATTEMPT_COLUMN = 10
CHANNELS: tuple[str, ...] = ("in_app", "desktop", "email", "webhook", "push")
MAX_ERROR_LEN = 200
#: `cv_outbox_depth` is read at most this often (monotonic seconds): a backlog gauge, not a
#: per-poll cost, since the loop polls every second.
DEPTH_EVERY_S = 15.0
#: A depth read that outlasts this is abandoned and logged like a failed one: the poll loop waits
#: on it, so a stalled read (a lock wait, a busy server) must not hold up the claims behind it.
DEPTH_TIMEOUT_S = 5.0

#: Bounded `suppressed` reason codes (stored in `error_message` and `context`).
SUPPRESSION_REASONS: frozenset[str] = frozenset(
    {"email_relay_off", "webhook_disabled", "push_unavailable", "recipient_deleted",
     "unknown_channel", "owner_inactive"}
)  # fmt: skip


def idempotency_key(delivery_id: int) -> str:
    """Stable per delivery: a re-send after a crash carries the same key."""
    return f"alert-delivery-{delivery_id}"


class IllegalTransition(ValueError):
    """A delivery status change outside `queued -> sent|failed|suppressed`, `sent -> acked`."""


_LEGAL: frozenset[tuple[str, str]] = frozenset(
    {("queued", "sent"), ("queued", "failed"), ("queued", "suppressed"), ("sent", "acked")}
)


def check_transition(old: str, new: str) -> None:
    if (old, new) not in _LEGAL:
        raise IllegalTransition(f"{old} -> {new}")


def backoff_seconds(attempts: int, rng: Callable[[], float]) -> float:
    """Exponential backoff (21-database-schema.md §3.10.4) with jitter in [0.5, 1.0]."""
    base = min(2.0 ** max(attempts, 0), MAX_BACKOFF_S)
    return base * (0.5 + 0.5 * rng())


class OutboxJob(Protocol):
    """A leased `outbox` row of topic `alert.deliver` (M10 supplies it structurally)."""

    @property
    def id(self) -> int: ...
    @property
    def delivery_id(self) -> int: ...
    @property
    def attempts(self) -> int: ...
    @property
    def max_attempts(self) -> int: ...


class Delivery(Protocol):
    """The `alert_deliveries` columns the dispatcher reads (satisfied by `DeliveryRow`)."""

    @property
    def id(self) -> int: ...
    @property
    def user_id(self) -> str | None: ...
    @property
    def channel(self) -> str: ...
    @property
    def status(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def body(self) -> str: ...
    @property
    def queued_at(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class Outcome:
    """`sent`; `retry` (transient, error kept); `pending` (client-side channel: the record
    stays `queued` until the shell reports back); `disabled` (-> `suppressed`)."""

    kind: str
    error: str | None = None
    http_status: int | None = None


SENT = Outcome("sent")
PENDING = Outcome("pending")


class ChannelAdapter(Protocol):
    async def deliver(self, d: Delivery) -> Outcome: ...


class DispatchStore(Protocol):
    async def claim(
        self, *, topic: str, worker: str, lease_s: float, limit: int
    ) -> Sequence[OutboxJob]:
        """`FOR UPDATE SKIP LOCKED` lease of ready rows (`available_at <= now()`)."""
        ...

    async def load(self, delivery_id: int) -> Delivery | None: ...

    async def depth(self, topic: str) -> int:
        """Rows of *topic* neither processed nor dead: the backlog (`cv_outbox_depth`)."""
        ...

    async def settle_sent(self, job: OutboxJob, *, attempt: int, http_status: int | None) -> bool:
        """Conditional `queued -> sent` + outbox `processed_at`, one transaction."""
        ...

    async def settle_processed(self, job: OutboxJob) -> None:
        """Outbox `processed_at` only (delivery already settled, or awaiting the client)."""
        ...

    async def settle_suppressed(self, job: OutboxJob, *, reason: str) -> bool: ...

    async def settle_retry(
        self, job: OutboxJob, *, attempt: int, error: str, delay_s: float
    ) -> None:
        """`attempts`, `available_at = now() + delay`, lease released; delivery stays queued
        with `attempt` mirrored."""
        ...

    async def settle_failed(
        self,
        job: OutboxJob,
        *,
        attempt: int,
        error: str,
        http_status: int | None,
        notice_title: str,
    ) -> bool:
        """Conditional `queued -> failed`, outbox `dead_at`, and (only if the update won) one
        `in_app` channel-failure notice row for the same alert/user — one transaction."""
        ...


class InAppAdapter:
    """The record itself: visible over the `alerts` WS topic as soon as it is `sent`."""

    async def deliver(self, d: Delivery) -> Outcome:
        return SENT


class DesktopAdapter:
    """Client-side instruction to the Electron shell; the outcome is reported back."""

    async def deliver(self, d: Delivery) -> Outcome:
        return PENDING


class DisabledAdapter:
    def __init__(self, reason: str) -> None:
        if reason not in SUPPRESSION_REASONS:
            raise ValueError(f"unknown suppression reason: {reason}")
        self.reason = reason

    async def deliver(self, d: Delivery) -> Outcome:
        return Outcome("disabled", self.reason)


class EmailTransport(Protocol):
    """The E04 relay. Raises `EmailError` on failure; never returns secrets."""

    async def send(
        self, *, user_id: str, subject: str, body: str, idempotency_key: str
    ) -> None: ...


class EmailError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class EmailAdapter:
    def __init__(self, transport: EmailTransport, timeout_s: float = 10.0) -> None:
        self._transport, self._timeout = transport, timeout_s

    async def deliver(self, d: Delivery) -> Outcome:
        if d.user_id is None:
            return Outcome("disabled", "recipient_deleted")
        try:
            async with asyncio.timeout(self._timeout):
                await self._transport.send(
                    user_id=d.user_id, subject=d.title, body=d.body,
                    idempotency_key=idempotency_key(d.id),
                )  # fmt: skip
        except TimeoutError:
            return Outcome("retry", "email relay timeout")
        except EmailError as exc:
            return Outcome("retry", str(exc), exc.status)
        return SENT


Metric = Callable[[str, tuple[str, ...]], Any]
Now = Callable[[], datetime]


class _Null:
    def inc(self, amount: float = 1) -> None: ...
    def set(self, value: float) -> None: ...
    def observe(self, amount: float) -> None: ...


def _no_metric(_name: str, _labels: tuple[str, ...]) -> Any:
    return _Null()


def default_adapters(
    email: EmailTransport | None, *, webhook_enabled: bool = False
) -> dict[str, ChannelAdapter]:
    """Every channel is registered; `webhook` stays disabled until E40-S03 (its egress
    allow-list), `push` is out of scope (owner decision 2026-09-14)."""
    if webhook_enabled:
        raise ValueError("webhook delivery lands with E40-S03; alerts.webhook_enabled must be off")
    return {
        "in_app": InAppAdapter(),
        "desktop": DesktopAdapter(),
        "email": EmailAdapter(email) if email is not None else DisabledAdapter("email_relay_off"),
        "webhook": DisabledAdapter("webhook_disabled"),
        "push": DisabledAdapter("push_unavailable"),
    }


class AlertDispatcher:
    """Outbox poller for `alert.deliver`. `run_once` is the unit of work (tests drive it);
    `start` runs it in a tracked task, woken by `notify()` or every `interval_s`, and samples the
    backlog's depth from there (`monotonic` is the clock of that throttle, `depth_timeout_s` the
    bound on each read)."""

    def __init__(
        self,
        store: DispatchStore,
        adapters: dict[str, ChannelAdapter],
        *,
        worker: str,
        now: Now,
        owners: OwnerGate,
        rng: Callable[[], float] = random.random,
        metric: Metric = _no_metric,
        on_change: Callable[[Sequence[int]], Awaitable[None]] | None = None,
        batch: int = 64,
        lease_s: float = 60.0,
        interval_s: float = 1.0,
        depth_every_s: float = DEPTH_EVERY_S,
        depth_timeout_s: float = DEPTH_TIMEOUT_S,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        missing = set(CHANNELS) - adapters.keys()
        if missing:
            raise ValueError(f"unregistered channels: {sorted(missing)}")
        self._store, self._adapters, self._worker, self._owners = store, adapters, worker, owners
        self._now, self._rng, self._metric, self._on_change = now, rng, metric, on_change
        self._batch, self._lease, self._interval = batch, lease_s, interval_s
        self._depth_every, self._monotonic = depth_every_s, monotonic
        self._depth_timeout = depth_timeout_s
        self._depth_due: float | None = None  # monotonic time of the next sample; None: at once
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def run_once(self) -> int:
        jobs = await self._store.claim(
            topic=TOPIC_ALERT_DELIVER, worker=self._worker, lease_s=self._lease, limit=self._batch
        )
        changed: list[int] = []
        for job in jobs:
            if self._stopping:  # draining: the rest stay leased and are replayed later
                break
            try:
                if await self._handle(job):
                    changed.append(job.delivery_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # one bad row must not stall the poller; its lease expires
                _log().exception("alert_dispatch_failed", outbox_id=job.id)
        if changed and self._on_change is not None:
            await self._on_change(changed)
        return len(jobs)

    async def _handle(self, job: OutboxJob) -> bool:
        d = await self._store.load(job.delivery_id)
        if d is None or d.status != "queued":  # replay after restart: already settled
            await self._store.settle_processed(job)
            return False
        if (why := await self._owner_skip(d)) is not None:
            self._metric("cv_alert_owner_skipped_total", ("dispatch", why)).inc()
            if why == "inactive":  # `unreadable`: fail closed, the lease runs out and it is re-read
                reason = "recipient_deleted" if d.user_id is None else "owner_inactive"
                if await self._store.settle_suppressed(job, reason=reason):
                    self._count(d.channel, "suppressed")
            return False  # final, and not announced on the `alerts` topic
        adapter = self._adapters.get(d.channel)
        out = await self._deliver(adapter, d)
        attempt = min(job.attempts + 1, MAX_ATTEMPT_COLUMN)
        if out.kind == "sent":
            won = await self._store.settle_sent(job, attempt=attempt, http_status=out.http_status)
            if won:
                self._count(d.channel, "sent")
                self._metric("cv_alert_delivery_attempts", ()).observe(job.attempts + 1)
                lat = max((self._now() - d.queued_at).total_seconds(), 0.0)
                self._metric("cv_alert_delivery_latency_seconds", (d.channel,)).observe(lat)
            return won
        if out.kind == "pending":
            await self._store.settle_processed(job)
            return True
        if out.kind == "disabled":
            reason = out.error if out.error in SUPPRESSION_REASONS else "unknown_channel"
            won = await self._store.settle_suppressed(job, reason=reason)
            if won:
                self._count(d.channel, "suppressed")
            return won
        return await self._retry_or_fail(job, d, out, attempt)

    async def _owner_skip(self, d: Delivery) -> SkipReason | None:
        """Why the delivery's owner is skipped, if it is, asked fresh: nothing starts leaving for a
        user disabled before this read. No owner row (`user_id IS NULL`) is no active one."""
        if d.user_id is None:
            return "inactive"
        return (await self._owners.skipped({d.user_id}, fresh=True)).get(d.user_id)

    async def _deliver(self, adapter: ChannelAdapter | None, d: Delivery) -> Outcome:
        if adapter is None:
            return Outcome("disabled", "unknown_channel")
        try:
            return await adapter.deliver(d)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # poison row: count the attempt, dead-letter at the cap
            _log().warning("alert_adapter_error", delivery_id=d.id, error=type(exc).__name__)
            return Outcome("retry", f"adapter_error: {type(exc).__name__}")

    async def _retry_or_fail(self, job: OutboxJob, d: Delivery, out: Outcome, attempt: int) -> bool:
        error = redact_text(out.error or "delivery failed")[:MAX_ERROR_LEN]
        if job.attempts + 1 < job.max_attempts:
            delay = backoff_seconds(job.attempts, self._rng)
            await self._store.settle_retry(job, attempt=attempt, error=error, delay_s=delay)
            return False
        won = await self._store.settle_failed(
            job, attempt=attempt, error=error, http_status=out.http_status,
            notice_title=f"{d.channel} delivery failed: {d.title}"[:200],
        )  # fmt: skip
        if won:
            self._count(d.channel, "failed")
            self._metric("cv_alert_delivery_attempts", ()).observe(job.attempts + 1)
            self._metric("cv_outbox_dead_total", (TOPIC_ALERT_DELIVER,)).inc()
        return won

    def _count(self, channel: str, status: str) -> None:
        self._metric("cv_alert_delivery_total", (channel, status)).inc()

    def notify(self) -> None:
        """A firing committed: poll now rather than at the next interval."""
        self._wake.set()

    def start(self) -> None:
        if self._task is None:
            self._task = spawn(self._run(), name="alert-dispatcher")

    async def _sample_depth(self) -> None:
        """`cv_outbox_depth{topic="alert.deliver"}`, the gauge `AlertOutboxBacklog` reads, at most
        once per `depth_every_s`. A failed read, or one that outlasts `depth_timeout_s`, is logged
        by type and keeps the last value: the gauge is a signal, never a reason to stop
        dispatching (a database that is down is PostgresDown's, and the poll logs it)."""
        now = self._monotonic()
        if self._depth_due is not None and now < self._depth_due:
            return
        self._depth_due = now + self._depth_every  # also after a failure: no retry per poll
        try:
            async with asyncio.timeout(self._depth_timeout):
                depth = await self._store.depth(TOPIC_ALERT_DELIVER)
            self._metric("cv_outbox_depth", (TOPIC_ALERT_DELIVER,)).set(depth)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log().warning("alert_outbox_depth_failed", error=type(exc).__name__)

    async def _run(self) -> None:
        while not self._stopping:
            self._wake.clear()  # before the poll: a firing that commits during it polls again
            try:
                n = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # storage blip: keep polling
                _log().exception("alert_dispatch_poll_failed")
                n = 0
            if not self._stopping:
                await self._sample_depth()  # before the `continue`: a backlog is sampled too
            if n >= self._batch or self._stopping:
                continue
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(self._interval):
                    await self._wake.wait()

    async def stop(self, grace_s: float = 5.0) -> None:
        """Drain: the in-flight send finishes (bounded by `grace_s`), then the loop ends;
        on timeout the task is cancelled and the leased row is replayed after its lease."""
        task, self._task = self._task, None
        if task is None:
            return
        self._stopping = True
        self._wake.set()
        try:
            async with asyncio.timeout(grace_s):
                await asyncio.shield(task)
        except TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        finally:
            self._stopping = False
