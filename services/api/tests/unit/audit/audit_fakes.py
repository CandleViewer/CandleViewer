"""Shared fakes for the audit unit tests: an in-memory `AuditRepository`
that emulates the `audit_chain()` trigger (same concatenation, same casts),
a controllable outage switch, and a fixed clock. No database, no network."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

GENESIS = "0" * 64


def _pg_ts(raw: str) -> str:
    ts = datetime.fromisoformat(raw).astimezone(UTC)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00"


def _ts(row: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(row["event_ts"][:-3] + "+00:00")


def _doc(row: dict[str, Any]) -> str:
    parts = (row["before_state"], row["after_state"], row["object_label"])
    return " ".join(p for p in parts if p is not None).lower()


class FakeAuditRepository:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.checkpoints: dict[int, dict[str, Any]] = {}
        self.page_calls: list[dict[str, Any]] = []
        self.verify_calls: list[tuple[int, int, int]] = []  # (after_id, to_id, limit)
        self.over_cap: set[int] = set()
        self._up = asyncio.Event()
        self._up.set()
        self.insert_attempts = 0
        self._next_id = 1

    def burn_ids(self, n: int) -> None:
        """Consume `n` sequence values without a row, as a WAL-replay duplicate
        (`ON CONFLICT DO NOTHING`) or a rolled-back insert does: ids have gaps."""
        self._next_id += n

    @property
    def down(self) -> bool:
        return not self._up.is_set()

    @down.setter
    def down(self, value: bool) -> None:
        if value:
            self._up.clear()
        else:
            self._up.set()

    async def retry_sleep(self, _delay: float) -> None:
        """Deterministic stand-in for the writer's backoff sleep: parks until
        the fake Postgres is back up (no wall-clock sleeping, no busy spin)."""
        await asyncio.sleep(0)
        await self._up.wait()

    async def insert(self, record: dict[str, Any]) -> None:
        self.insert_attempts += 1
        if self.down:
            raise ConnectionError("postgres unavailable")
        if any(r["record_id"] == record["record_id"] for r in self.rows):
            return  # ON CONFLICT (record_id) DO NOTHING
        prev = self.rows[-1]["entry_hash"] if self.rows else GENESIS

        def js(v: Any) -> str | None:
            return None if v is None else json.dumps(v, sort_keys=True)

        row: dict[str, Any] = {
            "id": self._next_id,
            "record_id": record["record_id"],
            "prev_hash": prev,
            "actor_user_id": record.get("actor_user_id"),
            "actor_label": record["actor_label"],
            "actor_ip": record.get("actor_ip"),
            "session_id": record.get("session_id"),
            "action": record["action"],
            "object_kind": record.get("object_kind"),
            "object_id": record.get("object_id"),
            "object_label": record.get("object_label"),
            "outcome": record["outcome"],
            "severity": record["severity"],
            "reason": record.get("reason"),
            "before_state": js(record.get("before_state")),
            "after_state": js(record.get("after_state")),
            "request_id": record.get("request_id"),
            "env": record.get("env"),
            "event_ts": _pg_ts(record["event_ts"]),
        }
        from candleviewer.audit.query import _canonical_hash

        row["entry_hash"] = _canonical_hash(prev, row)
        self.rows.append(row)
        self._next_id += 1

    async def query_page(self, **kw: Any) -> list[dict[str, Any]]:
        """As `SqlAlchemyAuditRepository.query_page`: AND-ed filters, newest first by
        `(event_ts, id)`, `after` exclusive, `to_ts` exclusive, a set `restrict_to_actor`
        replacing `actor_user_id`, and `q` as every term in the document."""
        self.page_calls.append(kw)
        restrict = kw["restrict_to_actor"]
        exact = {
            "actor_user_id": restrict if restrict is not None else kw["actor_user_id"],
            "object_kind": kw["subject_type"],
            "object_id": kw["subject_id"],
            "actor_ip": kw["ip"],
            "severity": kw["severity"],
            "outcome": kw["outcome"],
        }
        out = sorted(self.rows, key=lambda r: (_ts(r), r["id"]), reverse=True)
        for column, want in exact.items():
            if want is not None:
                out = [r for r in out if r[column] is not None and str(r[column]) == want]
        if kw["actions"]:
            out = [r for r in out if r["action"] in kw["actions"]]
        if kw["from_ts"] is not None:
            out = [r for r in out if _ts(r) >= kw["from_ts"]]
        if kw["to_ts"] is not None:
            out = [r for r in out if _ts(r) < kw["to_ts"]]
        if kw["q"] is not None:
            out = [r for r in out if all(t.lower() in _doc(r) for t in kw["q"].split())]
        if kw["after"] is not None:
            out = [r for r in out if (_ts(r), r["id"]) < kw["after"]]
        return [{**r, "event_ts": _ts(r), "chain": self._chain(r)} for r in out[: kw["limit"]]]

    def _chain(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """The stored renderings and the chain predecessor's hash; `None` for an id in
        `over_cap` (a rendering over the repository's caps)."""
        if row["id"] in self.over_cap:
            return None
        earlier = [r for r in self.rows if r["id"] < row["id"]]
        prev = max(earlier, key=lambda r: r["id"])["entry_hash"] if earlier else None
        return {**row, "chain_prev_hash": prev}

    async def fetch_entry_hash(self, entry_id: int) -> str | None:
        for r in self.rows:
            if r["id"] == entry_id:
                return str(r["entry_hash"])
        return None

    async def fetch_anchor_hash(self, before_id: int) -> str | None:
        earlier = [r for r in self.rows if r["id"] < before_id]
        return str(max(earlier, key=lambda r: r["id"])["entry_hash"]) if earlier else None

    async def fetch_verify_batch(
        self, *, after_id: int, to_id: int, limit: int
    ) -> list[tuple[Any, ...]]:
        """As the repository: keyset `after_id < id <= to_id` in id order, as tuples
        `(id, prev_hash, entry_hash, *renderings)` in `HASHED_FIELDS` order."""
        from candleviewer.audit.query import HASHED_FIELDS

        self.verify_calls.append((after_id, to_id, limit))
        sel = sorted((r for r in self.rows if after_id < r["id"] <= to_id), key=lambda r: r["id"])
        head = ("id", "prev_hash", "entry_hash")
        return [tuple(r[k] for k in (*head, *HASHED_FIELDS)) for r in sel[:limit]]

    async def read_head(self) -> tuple[int, str] | None:
        return (self.rows[-1]["id"], self.rows[-1]["entry_hash"]) if self.rows else None

    async def read_bounds(self) -> tuple[int, int] | None:
        ids = [r["id"] for r in self.rows]
        return (min(ids), max(ids)) if ids else None

    async def fetch_checkpoint_above(self, head_id: int) -> int | None:
        stored = {r["id"]: r["entry_hash"] for r in self.rows}
        differs = [  # as the SQL: the entry is missing or has another hash
            h
            for h, cp in self.checkpoints.items()
            if h > head_id and (h not in stored or stored[h] != cp.get("head_hash"))
        ]
        return min(differs, default=None)

    async def count(self) -> int:
        return len(self.rows)

    async def write_checkpoint(self, **kw: Any) -> None:
        self.checkpoints.setdefault(kw["head_id"], kw)


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 29, 12, 0, 0, 123456, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(microseconds=1)
        return self.now


class PgTextRefusedError(Exception):
    """What asyncpg raises for text Postgres 16 cannot store: U+0000 is SQLSTATE 22021 in a
    `text` column and 22P05 in `jsonb`; a lone surrogate is 22000 in `text` (refused before
    it is sent) and 22P02 in `jsonb`. `jsonb` also refuses NaN and the infinities (22P02).
    `model_dump_json` refuses a lone surrogate and writes a non-finite number as `null`, so
    only a stored frame can carry either this far."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"SQLSTATE {sqlstate}")
        self.sqlstate = sqlstate


def _texts(value: Any) -> list[str]:
    """Every string in a record value: itself, or dict keys, values and items at any depth."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for pair in value.items() for part in pair for text in _texts(part)]
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    return []


def _non_finite(value: Any) -> bool:
    """True if a JSON value holds NaN or an infinity, at any depth."""
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_non_finite(item) for item in value.values())
    if isinstance(value, list):
        return any(_non_finite(item) for item in value)
    return False


def _refusal(text: str, *, jsonb: bool) -> str | None:
    if "\x00" in text:
        return "22P05" if jsonb else "22021"
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "22P02" if jsonb else "22000"
    return None


class PgTextAuditRepository(FakeAuditRepository):
    """`FakeAuditRepository` that refuses, as Postgres does, a record holding text it cannot
    store or, in `jsonb`, a non-finite number; `refused` lists the SQLSTATE of each refusal."""

    def __init__(self) -> None:
        super().__init__()
        self.refused: list[str] = []

    async def retry_sleep(self, _delay: float) -> None:
        """A short real pause before each retry, so a record that stays refused is retried at
        a bounded rate instead of in a busy loop."""
        await asyncio.sleep(0.01)
        await super().retry_sleep(_delay)

    async def insert(self, record: dict[str, Any]) -> None:
        for column, value in record.items():
            jsonb = column in ("before_state", "after_state")
            for text in _texts(value):
                sqlstate = _refusal(text, jsonb=jsonb)
                if sqlstate is not None:
                    self.refused.append(sqlstate)
                    raise PgTextRefusedError(sqlstate)
            if jsonb and _non_finite(value):
                self.refused.append("22P02")
                raise PgTextRefusedError("22P02")
        await super().insert(record)
