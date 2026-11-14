"""E42-Q03 scenario 4, server half: an audit-chain break, its signals and its alert chain (#1216).

AUDIT-CORRUPT (Q01, #962) in this module's own database, never beside a load set. A verify over
the full range through the shipped route answers `200 {verified: false, first_bad_id}` (never an
error status); the scrape shows `audit_chain_verification_failures_total` up by one and
`cv_audit_chain_verified_state` at 0, which a passing partial range leaves at 0; the critical
`audit_chain_break` system event has opened its incident; the break halt is engaged
(`cv_audit_break_halt_state` 1). [BQ-6] The scraped values are then written as a promtool suite
that must fire `AuditChainVerificationFailed` and `AuditBreakHaltEngaged` over the real rule file;
the nightly runs promtool on it. The banner (`D04` §481-520) is part 3's. Marked `harness`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from candleviewer.admin.wiring import build_audit_break_halt, system_event_redactor
from candleviewer.api.audit import make_audit_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.health_wiring import PgSystemEventWriter
from candleviewer.storage.repositories.incident_grouping import incident_occurrence
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.admin import _alerts
from tests.chaos.admin._relay import Relay
from tests.chaos.admin._server import FixedPrincipal, app_of, audit_module, client, relational
from tests.fixtures.admin.corrupt_chain import seed_corrupted_chain

pytestmark = [pytest.mark.chaos, pytest.mark.harness]

FAILURES = "audit_chain_verification_failures_total"
CHAIN = "cv_audit_chain_verified_state"
HALT = "cv_audit_break_halt_state"


def _read_one(dsn: str, query: str, *params: Any) -> tuple[Any, ...] | None:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql")) as conn:
        return conn.execute(query, params).fetchone()


async def _one(dsn: str, query: str, *params: Any) -> tuple[Any, ...] | None:
    """A single-row read off the event loop, which also runs the relay."""
    return await asyncio.to_thread(_read_one, dsn, query, *params)


@pytest.fixture
async def events(relay: Relay, pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    made = relational(relay.through(pg_dsn), "health")
    yield made
    await made.dispose()


async def _noop(_reason: str | None) -> None:
    return None


async def test_s4_a_verified_break_counts_pages_opens_its_incident_and_halts(
    relay: Relay,
    pg_dsn: str,
    owner: AuditPrincipal,
    events: SqlAlchemyRelationalRepository,
    tmp_path: Path,
) -> None:
    (tmp_path / "seed").mkdir()
    victim = await seed_corrupted_chain(pg_dsn, tmp_path / "seed")  # before any other entry
    failures_before = _alerts.scrape(FAILURES) or 0.0
    async with audit_module(relay.through(pg_dsn), tmp_path) as audit:
        halt = build_audit_break_halt(audit, unread=False, on_change=_noop)
        router = make_audit_router(
            audit,
            FixedPrincipal(owner),
            verify_events=PgSystemEventWriter(events, redact_details=system_event_redactor()),
            break_halt=halt,
        )
        async with client(app_of(router)) as http:
            full = await http.post("/admin/audit/verify", json={})
            assert full.status_code == 200, full.text
            assert (full.json()["verified"], full.json()["first_bad_id"]) == (False, victim)
            failures, halted = _alerts.scrape(FAILURES), _alerts.scrape(HALT)
            assert failures == failures_before + 1
            assert _alerts.scrape(CHAIN) == 0.0
            assert halt.halt.engaged
            assert halted == 1.0
            first = await _one(pg_dsn, "SELECT min(id) FROM audit_log")
            assert first is not None
            partial = await http.post(
                "/admin/audit/verify", json={"from_id": first[0], "to_id": victim - 1}
            )
            assert partial.status_code == 200, partial.text
            assert partial.json()["verified"] is True
            assert _alerts.scrape(CHAIN) == 0.0, "a partial pass cleared a known break"
        signature = incident_occurrence(
            component="db",
            kind="audit_chain_break",
            severity="critical",
            message=f"audit chain break at id {victim}",
        ).signature
        row = await _one(
            pg_dsn, "SELECT severity, status FROM incidents WHERE signature = %s", signature
        )
        assert row == ("critical", "open")
        env = {"env": "testnet"}
        suite = [
            _alerts.case(
                "AuditChainVerificationFailed",
                {_alerts.series(FAILURES, env): f"{failures_before:g}+0x5 {failures:g}+0x20"},
                eval_time="10m",
                labels=env,
            ),
            _alerts.case(
                "AuditBreakHaltEngaged",
                {_alerts.series(HALT, env): f"{halted:g}+0x10"},
                eval_time="5m",
                labels=env,
            ),
        ]
        _alerts.write_suite("s4_audit_chain", suite, _alerts.out_dir(tmp_path / "alerts"))
    await relay.ensure_up()
