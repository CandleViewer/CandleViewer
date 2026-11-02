"""Scenario 7 - the process is killed in the middle of a renko rebuild. C-13.6 #12 (extension).

E12-Q06 AC5: a rebuild killed halfway leaves the old series served, never a half-built one, and
the restart resumes or restarts it cleanly. Not runnable: the rebuild executor (E12-S12, #535,
ADR-0033) does not exist yet (`_no_rebuild_executor` in the composition root, "not implemented"
in `builder_set` / `series_store`), so there is no job to kill. The placeholder keeps the scenario
in the catalogue and the report; #535 replaces the skip with the real scenario (kill the job at
each step, assert the old `build_version` stays served, the restart finishes it exactly once).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.chaos

BLOCKED_BY = "#535"


def test_s07_kill_mid_renko_rebuild_serves_the_old_series_and_resumes_cleanly() -> None:
    pytest.skip(
        f"blocked by {BLOCKED_BY}: the bars rebuild executor (E12-S12, ADR-0033) is not built"
    )
