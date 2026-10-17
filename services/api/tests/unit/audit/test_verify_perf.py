"""Verify's hashing throughput (ticket "Performance notes": verify processes at least
100k rows/s). Only the CPU step a batch takes on the hasher's thread, on a synthetic valid
chain; the end-to-end rate against Postgres belongs to the 10 M-row bench, not to this test.
"""

from __future__ import annotations

import json
import time
import uuid
import warnings

import pytest

from candleviewer.audit.query import _canonical_digest, _walk_batch

_GENESIS = "0" * 64
#: The ticket's target. A shared CI runner only enforces the hard fail (a quarter of it:
#: runner noise stays above that, a per-row regression such as a lookup in the loop does not)
#: and reports a run under the target as a warning, as #2423 does for the re-snapshot budget.
_TARGET_ROWS_PER_S = 100_000
_HARD_ROWS_PER_S = 25_000


def _chain(n: int) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    prev = _GENESIS
    for i in range(n):
        state = json.dumps({"price": "64000.5", "qty": "0.01", "symbol": "BTCUSDT", "n": i})
        renderings = (
            *(str(uuid.UUID(int=i)), "owner", "192.0.2.7", str(uuid.UUID(int=i + 7))),
            *("orders.submit", "order", f"ord-{i}", "success", "info", None, None, state),
            *(str(uuid.UUID(int=i + 9)), "demo", f"2026-10-14T12:00:00.{i:06d}+00"),
        )
        entry = _canonical_digest(prev, renderings)
        rows.append((i + 1, prev, entry, *renderings))
        prev = entry
    return rows


@pytest.mark.perf
def test_verify_hashes_a_batch_above_the_hard_fail_rate() -> None:
    batch = _chain(20_000)
    best = float("inf")
    for _ in range(5):  # best-of-5 damps scheduler noise
        started = time.perf_counter()
        walk = _walk_batch(_GENESIS, batch)
        best = min(best, time.perf_counter() - started)
    assert walk.bad_id is None and walk.checked == len(batch)
    rate = len(batch) / best
    if rate < _TARGET_ROWS_PER_S:
        warnings.warn(
            f"verify hashing {rate:,.0f} rows/s is under the {_TARGET_ROWS_PER_S:,} rows/s "
            "ticket target on this runner (hard fail 25,000 rows/s)",
            stacklevel=1,
        )
    assert rate > _HARD_ROWS_PER_S
