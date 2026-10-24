"""Integration: the complete read's writes to the recorded stops on Postgres 16 (E29-T04 #913,
S3-H; 21 Sec.3.3.11). `tests/unit/oms/recorded_stop_contract.py` runs here as `cv_app`, on the
submission contract's database, so `trg_rs_guard` (`ENABLE ALWAYS`) admits each of its moves and
every column is compared after a failed hook; the case below races two writers on one key."""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.oms.repository import RecordedStopRepository
from candleviewer.storage.repositories.recorded_stops import InForce, StaleRecordedStop
from tests.integration.storage.test_order_submission_contract_pg import (
    _sql,
    h,  # noqa: F401 -- pytest fixture re-export
    pg_dsn,  # noqa: F401 -- pytest fixture re-export
)
from tests.unit.oms.recorded_stop_contract import AT, RecordedStopContract, request
from tests.unit.oms.submission_contract import Harness

pytestmark = pytest.mark.integration


_KINDS = "SELECT status FROM recorded_stops WHERE exchange_account_id = %s AND kind = 'stop_loss'"


class TestRecordedStopResolutionOnPostgres(RecordedStopContract):
    async def test_every_move_above_ran_under_the_guard(
        self,
        pg_dsn: str,  # noqa: F811 -- fixture injection
    ) -> None:
        """The contract's cases make every move the complete read makes (in flight or answered to
        `in_force`, `replaced` and `void`; `in_force` to `replaced`; an answer's stamp), each
        admitted by `trg_rs_guard`, which no role can switch off for them."""
        assert _sql(pg_dsn, "SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_rs_guard'") == [
            ("A",)
        ]

    async def test_two_reads_racing_on_one_key_leave_one_row_in_force(
        self,
        h: Harness,  # noqa: F811 -- fixture injection
        pg_dsn: str,  # noqa: F811 -- fixture injection
    ) -> None:
        """The key lock serialises two reads: the second replaces the first's row or finds its own
        replaced (`StaleRecordedStop`); `ux_rs_in_force` is never met."""
        account, profile = h.new_account()
        stops = RecordedStopRepository(h.stops)
        older, newer = await request(h, account, profile), await request(h, account, profile)
        got = await asyncio.gather(
            stops.put_in_force(account, older[:1], at=AT),
            stops.put_in_force(account, newer[:1], at=AT),
            return_exceptions=True,
        )
        assert all(isinstance(r, InForce | StaleRecordedStop) for r in got)
        assert sorted(_sql(pg_dsn, _KINDS, account)) == [("in_force",), ("replaced",)]
