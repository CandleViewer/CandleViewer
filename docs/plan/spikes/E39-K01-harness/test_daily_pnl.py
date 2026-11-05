"""THROWAWAY spike tests for E39-K01: pin the synthetic table and the hybrid's safety direction.

No network, no clock reads in the table, Decimal money. Run as the README says.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import daily_pnl as d

RND = d.Q4  # one Q4 step: a record's rounding


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
        assert Decimal(row["hybrid"]) <= settled - Decimal("1.18") < Decimal(row["local"]), row
    # In this seed the backfilled loss is what takes the day past the cap.
    assert any(Decimal(r["settled"]) <= -d.CAP < Decimal(r["local"]) for r in held)
    assert all(Decimal(r["hybrid"]) <= -d.CAP for r in held if Decimal(r["settled"]) <= -d.CAP)


def test_causes_sum_to_each_divergence() -> None:
    for row in d.report()["hours"]:
        for src in ("local", "wallet", "txlog", "hybrid"):
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


def test_criterion_1_over_the_window_fails_the_stored_rows_and_passes_the_hybrid() -> None:
    """BQ-1 ruling: |div| <= 0.5 % of closed-PnL over the window is the pass/fail rule. The stored
    rows (a) fail it on both accounts (backfilled loss, no funding); the hybrid (d) passes."""
    whole = d.report()["criterion_1"]["whole_window"]
    assert [r["acct"] for r in whole] == ["A", "B"]
    assert not any(r["local"]["pass"] for r in whole)
    assert all(r["hybrid"]["pass"] for r in whole)


def test_bounds_never_lock_later_or_shorter_than_the_settled_figure() -> None:
    """BQ-3 (a) and BQ-5: the pessimistic figure locks no later than day-mark-to-market and than
    the same figure on settled records (SR-E39-11's direction: the bounds only err to blocking)."""
    lk = d.report()["lockouts"]
    hours = lk["locked_hours"]
    assert hours["pessimistic_a"] >= hours["day_mtm_b"]
    assert hours["pessimistic_a"] >= hours["settled"]
    first = {(o["acct"], o["day"]): o["from_hour"] for o in lk["lock_onsets"]["pessimistic_a"]}
    for name in ("day_mtm_b", "settled"):
        for o in lk["lock_onsets"][name]:
            assert first[(o["acct"], o["day"])] <= o["from_hour"], (name, o)


def test_hybrid_never_shows_less_loss_than_settled_and_credits_no_gain(monkeypatch: Any) -> None:
    """Per hour on five seeds: hybrid <= settled + rounding and blocking <= hybrid (a plain sum lets
    the carried gain offset); the fee bound keeps a margin; a backfilled gain is never credited."""
    for seed in range(d.SEED, d.SEED + 5):
        for r in d.report(seed)["hours"]:
            assert Decimal(r["blocking"]) <= Decimal(r["hybrid"]) <= Decimal(r["settled"]) + RND
    rep = d.report()
    assert Decimal(rep["lockouts"]["carried_at_boundary"][0]["carried_net_upnl"]) > 0
    assert Decimal(rep["max_provisional_bound_usd"]) > d.TOL
    monkeypatch.setattr(d, "GAP", (0, d.END))  # every A close backfilled
    recs = [r for r in d.build().records if r["unconfirmed"]]
    assert any(r["exact"] > 0 for r in recs) and all(r["local"] <= 0 for r in recs)


def test_restart_rebuild_reads_held_costs_back_to_each_position_open() -> None:
    """Finding 5.8 (c), restart at D1 00:30: read back to each open, blocking <= blocking_settled;
    a key-bounded read drops the carried long's 12.8539 + 1.6389 USDT; the fallback is None."""
    tr, restart, k1 = d.build(), d.DAY + 1800, d.windows()[1]
    truth = d.upnl(tr, "A", restart) - d.upnl(tr, "A", restart, net=True)
    assert d.rebuilt_held(tr, "A", restart, 0) == truth
    assert truth - d.rebuilt_held(tr, "A", restart, k1[1], bound=False) == Decimal("14.49275")
    assert d.rebuilt_held(tr, "A", restart, k1[1]) is None
    for r in (r for r in d.report()["hours"] if r["acct"] == "A" and 25 <= r["t"] <= k1[2] // d.H):
        un = d.upnl(tr, "A", r["t"] * d.H) - d.rebuilt_held(tr, "A", r["t"] * d.H, 0)
        blocking = Decimal(r["hybrid"]) + min(Decimal(0), un)
        assert blocking == Decimal(r["blocking"]) <= Decimal(r["blocking_settled"]) + RND, r
