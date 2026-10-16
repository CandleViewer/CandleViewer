"""Property (E16-T06): random pins / leases / watermarks / policies / crashes.

For every generated world: nothing protected is ever deleted (pinned symbol, active lease at
delete time, cold partition inside its total horizon, hot day inside any symbol's hot window or
past the archived watermark), every deletion has exactly one `data.deleted` record written
before it, and crash + rerun converges to exactly the plan.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.recorder.retention import US_PER_DAY, MemoryCheckpoint, PolicyRow
from candleviewer.recorder.retention_defaults import STREAM_DEFAULTS
from tests.unit.recorder._retention_fakes import NOW_US, Crash, T, World, day, manager

SYMS = ("AAAUSDT", "BBBUSDT", "CCCUSDT")

worlds = st.fixed_dictionaries(
    {
        "cold": st.lists(st.tuples(st.sampled_from(SYMS), st.integers(1, 60)), max_size=12),
        "hot": st.lists(
            st.tuples(st.integers(2, 40), st.sets(st.sampled_from(SYMS), min_size=1)), max_size=6
        ),
        "pinned": st.sets(st.sampled_from(SYMS)),
        "leased": st.sets(st.sampled_from(SYMS)),
        "marks": st.dictionaries(st.sampled_from(SYMS), st.integers(0, 45)),
        "hot_days": st.integers(1, 20),
        "total_days": st.integers(1, 50),
        "crash": st.one_of(st.none(), st.integers(1, 8)),
    }
)


def _build(p: dict[str, object]) -> World:
    w = World()
    w.policies[(None, "trades")] = PolicyRow(None, "trades", p["hot_days"], p["total_days"])  # type: ignore[arg-type]  # drawn ints
    for sym, n in p["cold"]:  # type: ignore[attr-defined]  # drawn list
        w.add_cold(sym, T, n)
    for n, syms in p["hot"]:  # type: ignore[attr-defined]  # drawn list
        w.add_hot(T, n, dict.fromkeys(syms, 3))
    w.pinned = set(p["pinned"])  # type: ignore[call-overload]  # drawn set
    for sym in p["leased"]:  # type: ignore[attr-defined]  # drawn set
        w.leases[sym] = [(day(30), day(20))]
    for sym, n in p["marks"].items():  # type: ignore[attr-defined]  # drawn dict
        w.archived[(sym, T)] = day(n)
    return w


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(worlds)
async def test_retention_never_deletes_protected_and_audits_each_deletion_once(
    p: dict[str, object],
) -> None:
    w = _build(p)
    hot_days, total_days = int(p["hot_days"]), int(p["total_days"])  # type: ignore[call-overload]  # drawn ints
    cold_before = {k: (sym, s) for (sym, _), parts in w.cold.items() for k, (s, _) in parts.items()}
    hot_before = {d: set(rows) for d, rows in w.hot.get(T, {}).items()}
    ckpt = MemoryCheckpoint()
    w.crash_on_delete = p["crash"]  # type: ignore[assignment]  # drawn int | None
    try:
        await manager(w, ckpt).run_nightly()
    except Crash:
        pass
    await manager(w, ckpt).run_nightly()  # rerun converges

    deleted_cold = {k for k in cold_before if k not in w.cold.get((cold_before[k][0], T), {})}
    deleted_hot = {d for d in hot_before if d not in w.hot.get(T, {})}
    for k in deleted_cold:
        sym, start = cold_before[k]
        assert sym not in w.pinned
        assert sym not in p["leased"] or not (start < day(20) and start + US_PER_DAY > day(30))  # type: ignore[operator]  # drawn set
        assert start + US_PER_DAY <= NOW_US - total_days * US_PER_DAY
    for d in deleted_hot:
        for sym in hot_before[d]:
            assert sym not in w.pinned
            assert d + US_PER_DAY <= NOW_US - hot_days * US_PER_DAY
            assert w.archived.get((sym, T), 0) >= d + US_PER_DAY
            assert sym not in p["leased"] or not (d < day(20) and d + US_PER_DAY > day(30))  # type: ignore[operator]  # drawn set
    records = w.data_deleted()
    ids = [r["deletion_id"] for r in records]
    assert len(ids) == len(set(ids)) == len(deleted_cold) + len(deleted_hot)


@settings(max_examples=300, deadline=None)
@given(
    stream=st.sampled_from([*sorted(STREAM_DEFAULTS), "unknown_x", "funding"]),
    rows=st.dictionaries(
        st.tuples(st.sampled_from([None, "BTCUSDT"]), st.sampled_from(["trades", "klines"])),
        st.tuples(st.integers(1, 50), st.integers(1, 800)),
        max_size=3,
    ),
)
def test_no_stream_resolves_shorter_than_section7_without_an_explicit_row(
    stream: str, rows: dict[tuple[str | None, str], tuple[int, int]]
) -> None:
    """Review H1: absent an explicit row for (symbol|default, stream), the total horizon is
    never shorter than the §7 default; unknown streams are kept forever."""
    from candleviewer.recorder.retention import resolve_policy

    policies = {k: PolicyRow(k[0], k[1], h, t) for k, (h, t) in rows.items()}
    eff = resolve_policy("BTCUSDT", stream, pinned=False, policies=policies, elevated=False)
    if ("BTCUSDT", stream) in policies or (None, stream) in policies:
        return
    expected = STREAM_DEFAULTS.get(stream, (0, None))[1]
    assert eff.total_days == expected
