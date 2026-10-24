"""Integration: the complete read's writes to the recorded stops on Postgres 16 (E29-T04 #913,
S3-H; 21 Sec.3.3.11). `tests/unit/oms/recorded_stop_contract.py` runs here as `cv_app` on the
submission contract's database: `trg_rs_guard` (`ENABLE ALWAYS`, pinned by the 0043 suites) admits
each move it makes, replace-then-set holds under `ux_rs_in_force` with two reads racing on one key,
a lost compare-and-set writes nothing, and a failed hook leaves every column of every row; and H3's
gate end to end (`StopGateContract`): a waiting entry's rows put in force, a void audited ahead.
And the lock order (the 06:38Z ruling): an order step settling an entry's rows and a read writing
them, raced, never deadlock (40P01), as both lock the rows in id order."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from candleviewer.storage.repositories.recorded_stops import StaleRecordedStop
from tests.integration.storage.test_order_submission_contract_pg import (
    h,  # noqa: F401 -- pytest fixture re-export
    pg_dsn,  # noqa: F401 -- pytest fixture re-export
)
from tests.unit.oms import submission_contract as sc
from tests.unit.oms.recorded_stop_contract import (
    AT,
    AUDITED,
    RecordedStopContract,
    StopGateContract,
    now_of,
    repo,
    request,
)
from tests.unit.oms.submission_contract import Harness

pytestmark = pytest.mark.integration


class TestRecordedStopResolutionOnPostgres(RecordedStopContract):
    """S3-H's writes on real row locks, real rollbacks and the real guard."""


class TestStopGateOnPostgres(StopGateContract):
    """H3's gate (21 Sec.3.3.11) on real row locks and the audit hook's real transaction."""


#: Rounds of the race, each on a fresh entry: its step and a read started together.
ROUNDS = 30


async def test_an_order_step_and_a_read_racing_on_an_entrys_rows_never_deadlock(
    h: Harness,  # noqa: F811 -- fixture injection
) -> None:
    """The 06:38Z ruling: a step settling its entry's rows (`answered`, or `void`) and a read
    voiding them or putting them in force meet on the same two pending, unanswered rows. Each
    locks them in id order, so neither ever waits on the other in a cycle: no 40P01. Each round
    ends with both rows alike, in a state the guard admits, written whole by one transaction; the
    other wrote nothing (the read's lost compare-and-set) or found nothing left to settle."""
    for n in range(ROUNDS):
        account, profile = h.new_account()
        rows = await request(h, account, profile, moves=(sc.SEND,))  # in flight, its entry sent
        order = cast(Any, SimpleNamespace(exchange_account_id=account, id=rows[0].order_id))
        settle = (sc.ACK, sc.REFUSED)[n % 2]  # entry_stops "answered", then "void"
        read = (
            repo(h).resolve(account, rows, "in_flight_resolved", at=AT, write_ahead=AUDITED)
            if n // 2 % 2 == 0
            else repo(h).put_in_force(account, rows, at=AT)
        )
        done = await asyncio.gather(settle(h, order), read, return_exceptions=True)
        failed = [e for e in done if isinstance(e, BaseException)]
        assert all(isinstance(e, StaleRecordedStop) for e in failed), (n, failed)  # never 40P01
        assert len(failed) <= 1
        ends = {(r.status, r.answered_at is None) for r in await now_of(h, rows)}
        assert len(ends) == 1 and ends <= {("pending", False), ("void", True), ("in_force", False)}
