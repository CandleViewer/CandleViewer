"""E12-X02 rebuild cases that need ADR-0033 Decision 2 (#452 BQ-6): NOT RUN placeholders.

The user-driven rebuild, its generation swap, cancellation token and per-user limits are E12-S12
(#535, contract first in #2127); `22-api-openapi.yaml` says the swap is not implemented. The
coordinator ruled (6554826610, BQ-6) that these cases are skipped here, reported NOT RUN in
`docs/security/abuse-cases/e12-bars.md`, and carried as an explicit row on #535, whose PR runs
them. Each skip names the X01 seed and the SR it would hold. What does exist today, the reader's
`RebuildRegistry` and the WS rebuild budget, runs in `test_exhaustion.py`.
"""

from __future__ import annotations

from typing import Final

import pytest

BLOCKED: Final = "blocked by #535 (E12-S12, ADR-0033 Decision 2 not built): NOT RUN, a row on #535"

#: (case id, X01 seed and rows, the requirement it would hold).
CASES: Final = [
    ("per_user_one_concurrent", "AC-05, BR-31", "SR-E12-05: a second rebuild cancels or refuses"),
    ("per_user_six_per_ten_minutes", "AC-05, BR-31", "SR-E12-05: the 7th start in 10 min refused"),
    ("process_wide_two", "AC-05, BR-31", "SR-E12-05: a 3rd concurrent rebuild refused"),
    ("disconnect_mid_rebuild", "AC-05, BR-04", "SR-E12-06: the disconnect cancels the rebuild"),
    ("cancel_by_another_user", "AC-05, BR-04", "SR-E12-06: cancel bound to the requester"),
    ("rebuild_id_idor", "AC-11, BR-23", "SR-E12-06: progress of another's rebuild refused"),
    ("rebuild_audited", "AC-05, BR-18", "SR-E12-06: start, cancel and finish audited"),
    ("interrupted_swap", "AC-08, BR-09", "SR-E12-13: an incomplete generation never served"),
    ("stale_over_newer_generation", "AC-08, BR-09", "SR-E12-13: a stale swap refused"),
    ("mutated_builder_same_version", "AC-08, BR-09", "SR-E12-13: the generation discarded"),
]


@pytest.mark.parametrize(("case", "seed", "holds"), CASES, ids=[c[0] for c in CASES])
def test_rebuild_blocked_decision_2_case_is_not_run(case: str, seed: str, holds: str) -> None:
    pytest.skip(f"{BLOCKED}; {seed}; {holds}")
