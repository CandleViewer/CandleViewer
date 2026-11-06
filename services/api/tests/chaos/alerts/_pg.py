"""Postgres helpers for the alert chaos scenarios that need the compose stack (1, 2, 6b).

They run in the CI `integration` job's chaos step (`-m "chaos and integration"`) against the
compose Postgres, migrated, as the other `tests/chaos` scenarios do. Exactly-once is read from the
rows: one `outbox` row per queued delivery (`ux_outbox_dedup`), one settle per delivery.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

from candleviewer.alerts.dispatcher import AlertDispatcher, default_adapters
from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER, alert_deliver_dedup_key
from candleviewer.alerts.owners import OwnerGate
from candleviewer.storage.repositories.alert_dispatch_sqlalchemy import (
    SqlAlchemyAlertDispatchStore,
)
from candleviewer.storage.repositories.alert_firing_sqlalchemy import SqlAlchemyAlertFiringStore
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.storage import _stack as st

API_DIR = Path(__file__).resolve().parents[3]  # services/api, the child's working directory
WAIT_S = 120.0


async def fetch(query: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(st.pg_dsn().replace("+asyncpg", "", 1), timeout=10)
    try:
        rows: list[asyncpg.Record] = await conn.fetch(query, *args, timeout=30)
        return rows
    finally:
        await conn.close()


async def seeded(channels: str = "{in_app,email}") -> tuple[str, str]:
    """An active user and one armed `every_time` alert of theirs: `(user, alert)`."""
    user, alert = uuid.uuid4(), uuid.uuid4()
    await fetch(
        "INSERT INTO users (id, email, username, display_name, password_hash, status) "
        "VALUES ($1, $2, $3, 'u', '$argon2id$x', 'active')",
        user, f"{user}@example.test", f"u{user.hex[:12]}",
    )  # fmt: skip
    await fetch(
        "INSERT INTO alerts (id, owner_user_id, name, condition_ir, condition_hash, trigger_mode, "
        "cooldown_seconds, channels) VALUES ($1, $2, $3, '{\"conditions\": {}}'::jsonb, $4, "
        "'every_time', 0, $5::alert_channel[])",
        alert, user, f"chaos-{alert.hex[:8]}", "a" * 64, channels,
    )  # fmt: skip
    return str(user), str(alert)


def firing_store(repo: SqlAlchemyRelationalRepository) -> SqlAlchemyAlertFiringStore:
    return SqlAlchemyAlertFiringStore(repo, topic=TOPIC_ALERT_DELIVER,
                                      dedup_key=alert_deliver_dedup_key)  # fmt: skip


async def fire(store: Any, user: str, alert: str, channels: tuple[str, ...]) -> list[int] | None:
    """One firing through the production transaction (deliveries + outbox + `fire_count`)."""
    ids: list[int] | None = await store.record_firing(
        alert_id=alert, user_id=user, channels=channels, status="queued", title="BTC 64k",
        body="", context={}, fired_at=datetime.now(UTC), once=False, bump=True,
    )  # fmt: skip
    return ids


def dispatcher(repo: SqlAlchemyRelationalRepository, relay: Any, **kw: Any) -> AlertDispatcher:
    return AlertDispatcher(
        SqlAlchemyAlertDispatchStore(repo), default_adapters(relay), now=lambda: datetime.now(UTC),
        owners=OwnerGate(SqlAlchemyIdentityProvider(repo)), **kw,
    )  # fmt: skip


async def ledger(alert: str) -> dict[str, Any]:
    """The rows exactly-once is read from, for one alert."""
    rows = await fetch(
        "SELECT d.id, d.status::text AS status, d.channel::text AS channel, "
        "(SELECT count(*) FROM outbox o WHERE o.topic = $2 AND o.dedup_key = d.id::text) AS ob, "
        "(SELECT bool_and(o.processed_at IS NOT NULL) FROM outbox o WHERE o.topic = $2 "
        " AND o.dedup_key = d.id::text) AS done "
        "FROM alert_deliveries d WHERE d.alert_id = $1::uuid "
        "AND NOT (d.context ? 'channel_failure') ORDER BY d.id",
        alert, TOPIC_ALERT_DELIVER,
    )  # fmt: skip
    (fc,) = await fetch("SELECT fire_count FROM alerts WHERE id = $1::uuid", alert)
    return {"rows": [dict(r) for r in rows], "fire_count": int(fc[0])}


async def depth(alert: str) -> int:
    """Unsettled outbox rows of one alert's deliveries (not the whole topic: siblings' rows)."""
    (row,) = await fetch(
        "SELECT count(*) FROM outbox o WHERE o.topic = $1 AND o.processed_at IS NULL "
        "AND o.dead_at IS NULL AND EXISTS (SELECT 1 FROM alert_deliveries d "
        "WHERE d.alert_id = $2::uuid AND d.id::text = o.dedup_key)", TOPIC_ALERT_DELIVER, alert,
    )  # fmt: skip
    return int(row[0])


class Child:
    """`_child` in a subprocess: the order goes on stdin, its `@@` lines come back on stdout."""

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc, self.seen = proc, list[str]()

    @classmethod
    async def spawn(cls, order: dict[str, Any]) -> Child:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "tests.chaos.alerts._child", cwd=API_DIR,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )  # fmt: skip
        child = cls(proc)
        try:
            await child.say(json.dumps(order | {"dsn": st.pg_dsn()}))
        except BaseException:
            await child.kill()
            raise
        return child

    async def say(self, line: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(line.encode() + b"\n")
        await self.proc.stdin.drain()

    async def until(self, prefix: str) -> str:
        """The child's next `@@ <prefix>...` line (bounded); everything it said is kept."""
        assert self.proc.stdout is not None
        try:
            async with asyncio.timeout(WAIT_S):
                while line := (await self.proc.stdout.readline()).decode():
                    self.seen.append(line)
                    if line.startswith(f"@@ {prefix}"):
                        return line.removeprefix("@@ ").strip()
        except TimeoutError:
            pass
        raise AssertionError(f"the child never said {prefix!r}:\n" + "".join(self.seen[-40:]))

    async def kill(self) -> int | None:
        with contextlib.suppress(ProcessLookupError):
            self.proc.kill()
        return await self.proc.wait()
