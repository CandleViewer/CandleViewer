"""Shared fakes for the audit unit tests: an in-memory `AuditRepository`
that emulates the `audit_chain()` trigger (same concatenation, same casts),
a controllable outage switch, and a fixed clock. No database, no network."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

GENESIS = "0" * 64
#: A page row's columns, as `SqlAlchemyAuditRepository`'s page select returns them: every
#: view's, then those only the Owner's raw view adds. No row ever carries a state.
_PAGE_COLUMNS = (
    "id", "event_ts", "actor_user_id", "actor_label", "action", "object_kind", "object_id",
    "outcome", "severity", "request_id", "entry_hash", "prev_hash",
)  # fmt: skip
_RAW_COLUMNS = ("actor_ip", "session_id", "object_label", "reason", "env")
_STATE_COLUMNS = ("before_state", "after_state")


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
        self.over_cap: set[int] = set()
        self._up = asyncio.Event()
        self._up.set()
        self.insert_attempts = 0

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
            "id": len(self.rows) + 1,
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

    async def query_page(self, **kw: Any) -> list[dict[str, Any]]:
        """As `SqlAlchemyAuditRepository.query_page`: AND-ed filters, newest first by
        `(event_ts, id)`, `after` exclusive, `to_ts` exclusive, a set `restrict_to_actor`
        replacing `actor_user_id`, `q` as every term in the document, and each row with
        the columns of its view (`raw`)."""
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
        return [self._page_row(r, raw=kw["raw"]) for r in out[: kw["limit"]]]

    def _page_row(self, row: dict[str, Any], *, raw: bool) -> dict[str, Any]:
        """The selected columns only: an Owner-only column a non-raw read touched would be a
        `KeyError`. A state never comes back, only (raw) whether it is null."""
        out = {name: row[name] for name in _PAGE_COLUMNS}
        out["event_ts"] = _ts(row)
        if raw:
            out |= {name: row[name] for name in _RAW_COLUMNS}
            out |= {f"{name}_is_null": row[name] is None for name in _STATE_COLUMNS}
        out["chain"] = self._chain(row)
        return out

    def _chain(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """The stored renderings and the chain predecessor's hash; `None` for an id in
        `over_cap` (a rendering over the repository's caps). Strict like a jsonb column:
        state text that is not JSON (a test tampering with it) is refused, never passed on."""
        for name in _STATE_COLUMNS:
            if row[name] is not None:
                try:
                    json.loads(row[name])
                except ValueError as exc:
                    raise ValueError(f"{name} of id {row['id']} is not jsonb text") from exc
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

    async def fetch_verify_batch(
        self, *, after_id: int, to_id: int | None, limit: int
    ) -> list[dict[str, Any]]:
        sel = [r for r in self.rows if r["id"] > after_id and (to_id is None or r["id"] <= to_id)]
        return [dict(r) for r in sel[:limit]]

    async def read_head(self) -> tuple[int, str] | None:
        return (self.rows[-1]["id"], self.rows[-1]["entry_hash"]) if self.rows else None

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
