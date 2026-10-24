"""Integration: the complete read's writes to the recorded stops on Postgres 16 (E29-T04 #913,
S3-H; 21 Sec.3.3.11). `tests/unit/oms/recorded_stop_contract.py` runs here as `cv_app` on the
submission contract's database: `trg_rs_guard` (`ENABLE ALWAYS`, pinned by the 0043 suites) admits
each move it makes, replace-then-set holds under `ux_rs_in_force` with two reads racing on one key,
a lost compare-and-set writes nothing, and a failed hook leaves every column of every row; and H3's
gate end to end (`StopGateContract`): a waiting entry's rows put in force, a void audited ahead."""

from __future__ import annotations

import pytest

from tests.integration.storage.test_order_submission_contract_pg import (
    h,  # noqa: F401 -- pytest fixture re-export
    pg_dsn,  # noqa: F401 -- pytest fixture re-export
)
from tests.unit.oms.recorded_stop_contract import RecordedStopContract, StopGateContract

pytestmark = pytest.mark.integration


class TestRecordedStopResolutionOnPostgres(RecordedStopContract):
    """S3-H's writes on real row locks, real rollbacks and the real guard."""


class TestStopGateOnPostgres(StopGateContract):
    """H3's gate (21 Sec.3.3.11) on real row locks and the audit hook's real transaction."""
