"""Integration: the stuck-order detector's reads on real Postgres 16 (E29-T08 #916; 24 Sec.8.13;
21 Sec.3.3.4, Sec.3.3.5, Sec.3.3.7, Sec.3.10.2; the ruling of record on #916, BQ-3, BQ-4, BQ-6).

Each condition the ticket names is forced in the tables as the OMS leaves it: a create killed
mid-submit (its row `submitting`, its create `in_flight`, no answer), a dropped stream (a row left
`unknown`, a cancel left pending) and a suppressed stop attach (an open position with no stop). The
reads answer each with its age from its latest `order_events.recv_ts` on the database's clock,
leave out what is final, paper, protected or another environment's, use the partial index each
predicate names (`EXPLAIN`, sequential scans off) and fit the scan's bound; the detector then
raises each kind, and one incident's `system_events` row keeps its ids through the redaction.
`testcontainers` in CI; run on the VPS only when its load allows and no perf runner is active.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from sqlalchemy.dialects import postgresql
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.wiring import system_event_redactor
from candleviewer.health_wiring import PgSystemEventWriter
from candleviewer.oms.incidents import incident
from candleviewer.oms.stuck_detector import SCAN_LIMIT, SCAN_TIMEOUT_S
from candleviewer.oms_detect_wiring import IncidentEventRows
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.stuck_sqlalchemy import (
    SqlAlchemyStuckReads,
    in_flight_statement,
    naked_statement,
    open_stuck_statement,
)
from tests.unit.oms.stuck_rig import build

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#916)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True, text=True, check=False, timeout=180,
    )  # fmt: skip


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _account(c: Conn, env: str = "demo") -> UUID:
    aid, uid = uuid.uuid4(), str(uuid.uuid4().int % 10**15)
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', %s, 'main', %s, %s)",
        (str(aid), env, uid, f"acct {uid}"),
    )
    return aid


def _link(n: int) -> str:
    """24 Sec.8.3's example id, its order segment numbered, so each order's id is its own."""
    return f"cvd-0TLr6mSAQFGvyfsJ0nLDCh-{n:04d}-01en"


def _order(
    c: Conn, account: UUID, n: int, *, state: str, lifecycle: str, idem: str, age_s: float,
    side: str = "Buy", provenance: str = "placed", exchange_order_id: str | None = None,
    symbol: str = "BTCUSDT",
) -> UUID:  # fmt: skip
    """One order row and two events, the latest received `age_s` ago on the database's clock."""
    oid = uuid.uuid4()
    c.execute(
        "INSERT INTO orders (id, exchange_account_id, order_link_id, exchange_order_id, symbol, "
        "side, intent, order_type, qty, state, lifecycle_state, idempotency_state, provenance, "
        "reduce_only) VALUES (%s, %s, %s, %s, %s, %s, %s, 'Market', 1, %s, %s, %s, %s, %s)",
        (str(oid), str(account), _link(n), exchange_order_id, symbol, side,
         "stop_loss" if provenance == "recorded_stop" else "entry", state, lifecycle, idem,
         provenance, provenance == "recorded_stop"),
    )  # fmt: skip
    for seq, ago in ((0, age_s + 30.0), (1, age_s)):
        c.execute(
            "INSERT INTO order_events (order_id, seq, kind, source, event_ts, recv_ts) VALUES "
            "(%s, %s, 'submit_attempt', 'local', now(), now() - make_interval(secs => %s))",
            (str(oid), seq, ago),
        )
    return oid


def _position(
    c: Conn, account: UUID, symbol: str, *, stop: str | None = None, paper: bool = False
) -> None:
    c.execute(
        "INSERT INTO positions (id, exchange_account_id, symbol, position_idx, side, size, "
        "stop_loss, is_paper) VALUES (%s, %s, %s, 0, 'Buy', 1, %s, %s)",
        (str(uuid.uuid4()), str(account), symbol, stop, paper),
    )


def _plan(c: Conn, stmt: Any) -> str:
    sql = str(stmt.compile(dialect=postgresql.psycopg.dialect(),
                           compile_kwargs={"literal_binds": True}))  # fmt: skip
    c.execute("SET enable_seqscan = off")
    try:
        return "\n".join(row[0] for row in c.execute(f"EXPLAIN {sql}").fetchall())
    finally:
        c.execute("RESET enable_seqscan")


async def test_each_condition_reads_with_its_age_and_the_detector_raises_it(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        mine, other_env = _account(c), _account(c, "testnet")
        # a create killed mid-submit: sent, never answered
        _order(c, mine, 1, state="submitted", lifecycle="submitting", idem="in_flight", age_s=31)
        # what is final leaves the scan: a KILLed row keeps `in_flight`
        _order(c, mine, 2, state="killed", lifecycle="killed", idem="in_flight", age_s=90)
        # a dropped stream: an order left unknown, a cancel left pending
        _order(c, mine, 3, state="unknown", lifecycle="unknown", idem="in_flight", age_s=61)
        _order(c, mine, 4, state="pending_cancel", lifecycle="cancel_pending", idem="acked",
               age_s=16)  # fmt: skip
        # another environment's stuck create is never this process's (C-2.11)
        _order(c, other_env, 5, state="unknown", lifecycle="unknown", idem="in_flight", age_s=61)
        # a suppressed stop attach: open with no stop; the others protected, paper or elsewhere
        _position(c, mine, "BTCUSDT")
        _position(c, mine, "ETHUSDT", stop="1500")
        _position(c, mine, "SOLUSDT")
        _position(c, mine, "XRPUSDT", paper=True)
        _order(c, mine, 6, state="accepted", lifecycle="submitted", idem="acked", age_s=1,
               side="Sell", provenance="recorded_stop", exchange_order_id="x6",
               symbol="SOLUSDT")  # fmt: skip
        _position(c, other_env, "BTCUSDT")
    rel = SqlAlchemyRelationalRepository(pg_dsn, "oms-detect", pool_size=2, max_overflow=0)
    store = SqlAlchemyStuckReads(rel, statement_timeout_ms=2000)
    try:
        rows, complete = await store.stuck_orders("demo", limit=SCAN_LIMIT)
        naked, whole = await store.naked_positions("demo", limit=SCAN_LIMIT)
    finally:
        await rel.dispose()
    by_link = {row.order_link_id: row for row in rows}
    assert complete and whole
    assert sorted(by_link) == [_link(1), _link(3), _link(4)]
    assert 30.5 < by_link[_link(1)].age_s < 45 and by_link[_link(1)].in_flight
    assert 60.5 < by_link[_link(3)].age_s < 75 and by_link[_link(3)].state == "unknown"
    assert 15.5 < by_link[_link(4)].age_s < 30 and not by_link[_link(4)].in_flight
    assert [(p.symbol, p.account_id) for p in naked] == [("BTCUSDT", mine)]
    detect = build()
    detect.reads.orders["demo"], detect.reads.positions["demo"] = list(rows), list(naked)
    await detect.detector.scan()
    detect.clock.advance(3.001)
    await detect.detector.scan()
    assert sorted(detect.kinds()) == ["in_flight", "naked", "pending", "unknown"]


async def test_each_read_uses_the_partial_index_its_predicate_names(pg_dsn: str) -> None:
    """BQ-3: candidates from the partial indexes, never a sequential scan of `orders` or
    `positions`; with sequential scans off, each plan names its index."""
    with _conn(pg_dsn) as c:
        assert "ix_orders_inflight" in _plan(c, in_flight_statement("demo", SCAN_LIMIT))
        assert "ix_orders_open" in _plan(c, open_stuck_statement("demo", SCAN_LIMIT))
        assert "ix_pos_no_sl" in _plan(c, naked_statement("demo", SCAN_LIMIT))


async def test_a_full_scan_of_a_busy_environment_fits_the_scans_bound(pg_dsn: str) -> None:
    """The scan's reads, `SCAN_LIMIT` rows each, well inside `SCAN_TIMEOUT_S` (4 s)."""
    with _conn(pg_dsn) as c:
        busy = _account(c, "live")  # an environment of its own: the other tests read `demo`
        for n in range(SCAN_LIMIT + 20):
            _order(c, busy, 1000 + n, state="unknown", lifecycle="unknown", idem="in_flight",
                   age_s=61)  # fmt: skip
    rel = SqlAlchemyRelationalRepository(pg_dsn, "oms-detect", pool_size=2, max_overflow=0)
    store = SqlAlchemyStuckReads(rel, statement_timeout_ms=2000)
    try:
        began = time.monotonic()
        rows, complete = await store.stuck_orders("live", limit=SCAN_LIMIT)
        await store.naked_positions("live", limit=SCAN_LIMIT)
        took = time.monotonic() - began
    finally:
        await rel.dispose()
    assert not complete  # cut at its limit: the scan forgets nothing it did not read
    assert len(rows) <= 2 * SCAN_LIMIT
    assert took < SCAN_TIMEOUT_S / 2, took


async def test_an_incidents_row_keeps_its_ids_through_the_redaction(pg_dsn: str) -> None:
    """BQ-6, 21 Sec.3.10.2: component `oms`, kind `incident_<kind>`, the ids in `details`, and
    an incident materialised for E42's read model."""
    with _conn(pg_dsn) as c:
        account = _account(c)
    rel = SqlAlchemyRelationalRepository(pg_dsn, "oms-detect", pool_size=2, max_overflow=0)
    found = incident(
        "unknown", account_id=account, age_s=61.25, detected_at=datetime.now(UTC),
        order_link_id=_link(7), symbol="BTCUSDT",
    )  # fmt: skip
    try:
        writer = PgSystemEventWriter(rel, redact_details=system_event_redactor())
        await IncidentEventRows(writer).write(found)
    finally:
        await rel.dispose()
    with _conn(pg_dsn) as c:
        component, kind, severity, details = c.execute(
            "SELECT component, kind, severity::text, details FROM system_events "
            "WHERE kind = 'incident_unknown' ORDER BY id DESC LIMIT 1"
        ).fetchone() or (None, None, None, None)
        grouped = c.execute(
            "SELECT count(*) FROM incidents WHERE component = 'oms' AND severity = 'critical'"
        ).fetchone()
    assert (component, kind, severity) == ("oms", "incident_unknown", "critical")
    assert details == {"kind": "unknown", "account_id": str(account), "age_s": "61.250",
                       "order_link_id": _link(7), "symbol": "BTCUSDT"}  # fmt: skip
    assert grouped is not None and grouped[0] >= 1
