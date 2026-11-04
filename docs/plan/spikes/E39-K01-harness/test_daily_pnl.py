"""THROWAWAY spike tests for E39-K01: pin the synthetic table and the hybrid's safety direction.

No network, no clock reads in the table, Decimal money. Run from this directory:
    python -m pytest -q test_daily_pnl.py
"""

from __future__ import annotations

from decimal import Decimal

import daily_pnl as d


def test_report_is_byte_identical_across_runs() -> None:
    assert d.dump(d.report()) == d.dump(d.report())


def test_committed_table_matches_the_seed() -> None:
    assert d.RESULTS.read_bytes() == d.dump(d.report())


def test_another_seed_changes_the_table() -> None:
    assert d.dump(d.report(d.SEED + 1)) != d.dump(d.report())


def test_unconfirmed_backfilled_loss_blocks_where_the_stored_rows_do_not() -> None:
    """The backfilled close is a LOSS whose record is late: while it is unconfirmed the hybrid
    books strictly more loss than the venue's eventual figure (it is not handed the exact
    figure), and the stored rows (NULL closed_pnl) book strictly less: the fail-open case."""
    rep = d.report()
    assert all(Decimal(r["exact"]) < 0 for r in rep["backfilled_closes"])
    held = [r for r in rep["hours"] if r["unconfirmed_closes"]]
    assert len(held) == rep["unconfirmed_hours"] > 0
    for row in held:
        settled = Decimal(row["settled"])
        assert Decimal(row["hybrid"]) < settled < Decimal(row["local"]), row
    # In this seed the backfilled loss is what takes the day past the cap.
    assert any(Decimal(r["settled"]) <= -d.CAP < Decimal(r["local"]) for r in held)
    assert all(Decimal(r["hybrid"]) <= -d.CAP for r in held if Decimal(r["settled"]) <= -d.CAP)


def test_causes_sum_to_each_divergence() -> None:
    for row in d.report()["hours"]:
        for src in ("local", "wallet", "hybrid"):
            total = sum((Decimal(v) for v in row[f"causes_{src}"].values()), Decimal(0))
            assert total == Decimal(row[f"div_{src}"]), (src, row)


def test_offset_change_never_shortens_the_key_in_progress() -> None:
    """For each offset, negative and positive, the key in progress at the change keeps its start,
    ends on the new offset's grid at or after its old end (24 h to < 48 h), and the keys after it
    are whole days on the new grid."""
    req = d.OFFSET_CHANGE[0]
    old_start, old_end = req // d.DAY * d.DAY, (req // d.DAY + 1) * d.DAY
    expected = {-720: 36, -60: 25, 60: 47, 840: 34}
    for off in d.OFFSET_CASES:
        keys = d.windows(off, req, req + 5 * d.DAY)
        cur = next(k for k in keys if k[1] <= req < k[2])
        assert cur[1] == old_start and cur[2] >= old_end, (off, cur)
        assert (cur[2] + off * 60) % d.DAY == 0, (off, cur)
        assert d.DAY <= cur[2] - cur[1] < 2 * d.DAY, (off, cur)
        assert (cur[2] - cur[1]) // d.H == d.transitional_hours(off) == expected[off]
        later = keys[keys.index(cur) + 1 : -1]
        assert later and all(k[2] - k[1] == d.DAY for k in later), (off, later)
