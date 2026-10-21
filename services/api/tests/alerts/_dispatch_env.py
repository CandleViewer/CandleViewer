"""In-memory `DispatchStore` mirroring the Postgres semantics (E40-T04).

Conditional `WHERE status = 'queued'` updates, `(topic, dedup_key)` uniqueness, leases
with expiry, and a fake clock. `crash_after_adapter` simulates a process death between
the adapter call and the settle transaction (nothing of the settle is committed).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER, alert_deliver_dedup_key

T0 = datetime(2026, 10, 6, tzinfo=UTC)
USER = "00000000-0000-4000-8000-00000000000a"
ALERT = "13000000-0000-4000-8000-000000000001"


@dataclass(frozen=True)
class Row:
    id: int
    alert_id: str
    user_id: str | None
    channel: str
    status: str
    title: str
    body: str
    queued_at: datetime
    attempt: int = 0
    error_message: str | None = None
    http_status: int | None = None
    context: tuple[tuple[str, Any], ...] = ()


@dataclass
class Ob:
    id: int
    topic: str
    dedup: str
    delivery_id: int
    attempts: int = 0
    max_attempts: int = 8
    available_at: datetime = T0
    locked_until: datetime | None = None
    processed: bool = False
    dead: bool = False
    last_error: str | None = None


@dataclass(frozen=True)
class Job:
    id: int
    delivery_id: int
    attempts: int
    max_attempts: int


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> datetime:
        return self.t

    def advance(self, s: float) -> None:
        self.t += timedelta(seconds=s)


class MemStore:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.rows: dict[int, Row] = {}
        self.outbox: dict[int, Ob] = {}
        self.calls: list[str] = []

    def fire(self, channels: list[str], *, max_attempts: int = 8, user: str = USER) -> list[int]:
        """What `record_firing` commits: one delivery + one outbox row per channel."""
        ids = []
        for ch in channels:
            did = len(self.rows) + 1
            self.rows[did] = Row(did, ALERT, user, ch, "queued", "BTC 64k", "", self.clock())
            self.add_outbox(did, max_attempts)
            ids.append(did)
        return ids

    def add_outbox(self, did: int, max_attempts: int = 8) -> bool:
        key = (TOPIC_ALERT_DELIVER, alert_deliver_dedup_key(did))
        if any((o.topic, o.dedup) == key for o in self.outbox.values()):
            return False  # ux_outbox_dedup: ON CONFLICT DO NOTHING
        oid = len(self.outbox) + 1
        self.outbox[oid] = Ob(oid, key[0], key[1], did, max_attempts=max_attempts,
                              available_at=self.clock())  # fmt: skip
        return True

    async def claim(self, *, topic: str, worker: str, lease_s: float, limit: int) -> list[Job]:
        now, out = self.clock(), []
        for o in sorted(self.outbox.values(), key=lambda o: (o.available_at, o.id)):
            if len(out) >= limit:
                break
            if o.topic != topic or o.processed or o.dead or o.available_at > now:
                continue
            if o.locked_until is not None and o.locked_until >= now:
                continue
            o.locked_until = now + timedelta(seconds=lease_s)
            out.append(Job(o.id, o.delivery_id, o.attempts, o.max_attempts))
        return out

    async def load(self, delivery_id: int) -> Row | None:
        return self.rows.get(delivery_id)

    async def depth(self, topic: str) -> int:
        """`SqlAlchemyAlertDispatchStore.depth`: the topic's rows neither processed nor dead."""
        return sum(o.topic == topic and not (o.processed or o.dead) for o in self.outbox.values())

    def _cond(self, did: int, **f: Any) -> bool:
        r = self.rows[did]
        if r.status != "queued":
            return False
        self.rows[did] = replace(r, **f)
        return True

    def _ob(self, job: Job, **f: Any) -> None:
        o = self.outbox[job.id]
        for k, v in f.items():
            setattr(o, k, v)
        o.locked_until = None

    async def settle_processed(self, job: Job) -> None:
        self.calls.append("processed")
        self._ob(job, processed=True)

    async def settle_sent(self, job: Job, *, attempt: int, http_status: int | None) -> bool:
        self.calls.append("sent")
        won = self._cond(job.delivery_id, status="sent", attempt=attempt, error_message=None,
                         http_status=http_status)  # fmt: skip
        self._ob(job, processed=True, attempts=job.attempts + 1)
        return won

    async def settle_suppressed(self, job: Job, *, reason: str) -> bool:
        self.calls.append("suppressed")
        won = self._cond(job.delivery_id, status="suppressed", error_message=reason,
                         context=(("suppression_reason", reason),))  # fmt: skip
        self._ob(job, processed=True)
        return won

    async def settle_retry(self, job: Job, *, attempt: int, error: str, delay_s: float) -> None:
        self.calls.append(f"retry:{delay_s:.3f}")
        self._cond(job.delivery_id, attempt=attempt, error_message=error)
        self._ob(job, attempts=job.attempts + 1, last_error=error,
                 available_at=self.clock() + timedelta(seconds=delay_s))  # fmt: skip

    async def settle_failed(
        self, job: Job, *, attempt: int, error: str, http_status: int | None, notice_title: str
    ) -> bool:
        self.calls.append("failed")
        r = self.rows[job.delivery_id]
        won = self._cond(job.delivery_id, status="failed", attempt=attempt, error_message=error,
                         http_status=http_status)  # fmt: skip
        self._ob(job, dead=True, attempts=job.attempts + 1, last_error=error)
        if won:
            nid = len(self.rows) + 1
            self.rows[nid] = Row(nid, r.alert_id, r.user_id, "in_app", "sent", notice_title, "",
                                 self.clock(), context=(("channel_failure", True),))  # fmt: skip
        return won
