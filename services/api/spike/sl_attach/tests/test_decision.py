# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The summary's tables and the decision rule agreed up front in #856 (p99 of arm (b) above
1.5 s means attach-only), at its edge, below the floors and offline; a failed stop write as
+inf exposure, and the stop-write success bar at its edge (D2); a filled opener whose stop
write was never sent as a failure (E1); the skew-discard share and its bound (Nit); arm (b)'s
p99 read again with its skew discards at +inf (E5)."""

from __future__ import annotations

import math

import pytest

from spike.sl_attach.config import MAX_SKEW_DISCARD_SHARE, MIN_STOP_SUCCESS_RATE
from spike.sl_attach.decision import decide
from spike.sl_attach.results import Sample
from spike.sl_attach.summary import summarise

SYMBOLS = ("BTCUSDT", "ETHUSDT", "THINUSDT")
ACCEPTED = "trading-stop-window-accepted"


def _row(arm: str, i: int, value: float, **fields: object) -> Sample:
    metric = "ack_ms" if arm == "a" else "exposure_ms"
    base: dict[str, object] = {
        "run_id": "run#1",
        "sample_id": i,
        "arm": arm,
        "symbol": SYMBOLS[i % 3],
        "side": "buy",
        "position_idx": 0,
        "qty": "0.002",
        "order_ref": f"link#{i}",
        "outcome": "ok",
        metric: value,
        "requests_order_class": 1,
        "requests_position_class": 0 if arm == "a" else 1,
    }
    if arm == "b":
        base["stop_landed"] = fields.get("outcome", "ok") == "ok"
    return Sample.model_validate(base | fields)


def _run(b_p99: float, *, n: int = 200) -> list[Sample]:
    """`n` samples per arm; arm (b)'s nearest-rank p99 is `b_p99`."""
    a = [_row("a", i, 40.0) for i in range(n)]
    b = [_row("b", i, 100.0) for i in range(n - 3)] + [_row("b", n + i, b_p99) for i in range(3)]
    return a + b


@pytest.mark.parametrize(
    ("p99", "verdict"),
    [
        (1499.0, "trading-stop-window-accepted"),
        (1500.0, "trading-stop-window-accepted"),
        (1501.0, "attach-only"),
    ],
)
def test_the_rule_at_its_edge(p99: float, verdict: str) -> None:
    summary = summarise(_run(p99))
    decision = decide(summary, offline=False)
    assert decision["verdict"] == verdict and decision["arm_b_p99_ms"] == p99
    assert decision["evidence"] is True and decision["deadline_met"] is True
    assert "modify" in str(decision["measured"])


def test_below_the_floors_is_insufficient_never_a_verdict() -> None:
    assert decide(summarise(_run(3000.0, n=199)), offline=False)["verdict"] == "insufficient"
    two_symbols = [s.model_copy(update={"symbol": "BTCUSDT"}) for s in _run(100.0)]
    assert decide(summarise(two_symbols), offline=False)["verdict"] == "insufficient"


def _refused(i: int) -> Sample:
    return _row(
        "b",
        i,
        0.0,
        outcome="rejected",
        exposure_ms=None,
        stage="trading_stop",
        ret_code=110017,
        s86_code="REDUCE_ONLY_VIOLATION",
        stop_landed=False,
    )


def test_failed_samples_never_fill_the_floors() -> None:
    """M3: 190 refused stop writes and 10 successes is 200 kept, but 10 measured: no verdict."""
    a = [_row("a", i, 40.0) for i in range(200)]
    b = [_refused(i) for i in range(190)] + [_row("b", 190 + i, 150.0) for i in range(10)]
    summary = summarise(a + b)
    arms = summary["arms"]
    assert isinstance(arms, dict) and arms["b"]["kept"] == 200 and arms["b"]["measured"] == 10
    decision = decide(summary, offline=False)
    assert decision["verdict"] == "insufficient" and decision["arm_b_measured"] == 10
    assert decision["arm_b_success_rate"] == 0.05


def test_the_symbol_floor_counts_measured_samples_only() -> None:
    """Three symbols kept, but every success on one: no verdict."""
    a = [_row("a", i, 40.0) for i in range(200)]
    ok = [_row("b", i, 100.0).model_copy(update={"symbol": "BTCUSDT"}) for i in range(200)]
    summary = summarise(a + ok + [_refused(301), _refused(302)])
    assert decide(summary, offline=False)["verdict"] == "insufficient"


def test_failed_stop_writes_are_unbounded_exposure() -> None:
    """D2: 200 successes and 1,800 refused stop writes are attach-only, never accepted."""
    a = [_row("a", i, 40.0) for i in range(200)]
    b = [_row("b", i, 150.0) for i in range(200)] + [_refused(200 + i) for i in range(1800)]
    summary = summarise(a + b)
    arms = summary["arms"]
    assert isinstance(arms, dict) and arms["b"]["unbounded"] == 1800
    assert arms["b"]["measured"] == 200 and arms["b"]["latency_ms"]["n"] == 2000
    decision = decide(summary, offline=False)
    assert decision["verdict"] == "attach-only" and decision["arm_b_p99_ms"] == math.inf
    assert decision["arm_b_stop_success_rate"] == 0.1 and decision["deadline_met"] is False


@pytest.mark.parametrize(("failed", "p99"), [(2, 150.0), (3, math.inf)])
def test_the_p99_counts_each_failed_stop_as_inf(failed: int, p99: float) -> None:
    """Nearest-rank p99 over 200 + `failed`: two failures stay under rank 200, three reach it."""
    b = [_row("b", i, 150.0) for i in range(200)] + [_refused(200 + i) for i in range(failed)]
    arms = summarise(b)["arms"]
    assert isinstance(arms, dict) and arms["b"]["latency_ms"]["p99"] == p99


def test_a_stop_that_never_landed_is_unbounded_even_when_discarded() -> None:
    lost = _row("b", 900, 0.0, outcome="discarded", discard_reason="incomplete", stop_landed=False)
    arms = summarise([_row("b", 0, 150.0), lost])["arms"]
    assert isinstance(arms, dict) and arms["b"]["unbounded"] == 1
    assert arms["b"]["latency_ms"]["max"] == math.inf and arms["b"]["stop_success_rate"] == 0.5


@pytest.mark.parametrize(
    ("failed", "verdict"), [(1, "trading-stop-window-accepted"), (2, "attach-only")]
)
def test_the_stop_success_bar_at_its_edge(failed: int, verdict: str) -> None:
    """200 landed and one failure is 0.99502 (at or over 0.995); two is 0.990099 (under), and
    the p99 is still finite there: the bar alone decides."""
    a = [_row("a", i, 40.0) for i in range(200)]
    b = [_row("b", i, 150.0) for i in range(200)] + [_refused(200 + i) for i in range(failed)]
    decision = decide(summarise(a + b), offline=False)
    assert decision["arm_b_p99_ms"] == 150.0 and decision["verdict"] == verdict
    assert decision["min_stop_success_rate"] == MIN_STOP_SUCCESS_RATE


def _unsent(i: int) -> Sample:
    """E1: an arm (b) opener that filled, its execution push lost: no stop write was sent."""
    return _row(
        "b",
        i,
        0.0,
        outcome="discarded",
        discard_reason="no_fill",
        exposure_ms=None,
        stage="create",
        ret_code=0,
        stop_landed=False,
    )


def test_a_filled_opener_without_its_stop_write_is_a_failure() -> None:
    """E1: 200 successes and 100 filled openers whose stop write was never sent: attach-only."""
    a = [_row("a", i, 40.0) for i in range(200)]
    b = [_row("b", i, 150.0) for i in range(200)] + [_unsent(200 + i) for i in range(100)]
    summary = summarise(a + b)
    arms = summary["arms"]
    assert isinstance(arms, dict) and arms["b"]["unbounded"] == 100
    assert arms["b"]["measured"] == 200 and arms["b"]["latency_ms"]["n"] == 300
    decision = decide(summary, offline=False)
    assert decision["verdict"] == "attach-only" and decision["arm_b_p99_ms"] == math.inf
    assert decision["arm_b_stop_success_rate"] == round(200 / 300, 6)


def _skewed(arm: str, i: int) -> Sample:
    landed = True if arm == "b" else None  # a skewed arm (b) sample's stop did land
    return _row(arm, i, 0.0, outcome="discarded", discard_reason="skew", stop_landed=landed)


@pytest.mark.parametrize(
    ("kept_a", "skewed", "verdict"),
    [(0, 10, ACCEPTED), (9, 11, ACCEPTED), (0, 11, "insufficient"), (9, 12, "insufficient")],
)
def test_the_skew_discard_share_is_bounded(kept_a: int, skewed: int, verdict: str) -> None:
    """Nit: 10 of 210 (under 5 %), 11 of 220 (exactly 5 %: X3) pass; 11 of 211 and 12 of 221
    (over) give no verdict, and say the share. Arm (a): arm (b)'s skew discards meet E5 first."""
    extra = [_row("a", 300 + i, 40.0) for i in range(kept_a)]
    rows = _run(100.0) + extra + [_skewed("a", 500 + i) for i in range(skewed)]
    decision = decide(summarise(rows), offline=False)
    share = decision["skew_discard_share"]
    assert isinstance(share, dict) and share["a"] == round(skewed / (200 + kept_a + skewed), 6)
    assert decision["verdict"] == verdict
    assert decision["max_skew_discard_share"] == MAX_SKEW_DISCARD_SHARE


@pytest.mark.parametrize(
    ("b_p99", "skewed", "worst", "verdict"),
    [
        (100.0, 2, 100.0, ACCEPTED),
        (100.0, 3, math.inf, "insufficient"),
        (100.0, 10, math.inf, "insufficient"),
        (1600.0, 10, math.inf, "attach-only"),
    ],
)
def test_arm_b_p99_is_read_again_with_its_skew_discards_at_inf(
    b_p99: float, skewed: int, worst: float, verdict: str
) -> None:
    """E5: a one-sided stall skews the stop write, so the discards can be the whole tail. 200 at
    100 ms + 10 skew discards (under the 5 % share) is not accepted; + 2 is (nearest rank 200 of
    202), + 3 is not (rank 201 of 203). A kept p99 over 1.5 s stays attach-only. Both p99s are
    in the answer."""
    rows = _run(b_p99) + [_skewed("b", 500 + i) for i in range(skewed)]
    summary = summarise(rows)
    arms = summary["arms"]
    assert isinstance(arms, dict) and arms["b"]["p99_skew_inf_ms"] == worst
    decision = decide(summary, offline=False)
    assert decision["arm_b_p99_ms"] == b_p99 and decision["arm_b_p99_skew_inf_ms"] == worst
    assert decision["verdict"] == verdict


def test_an_unknown_stop_success_rate_is_attach_only() -> None:
    """Above the floors but no stop write recorded as landed: no proof, so attach-only."""
    rows = [s.model_copy(update={"stop_landed": None}) for s in _run(100.0)]
    assert decide(summarise(rows), offline=False)["verdict"] == "attach-only"


def test_an_offline_run_is_never_evidence() -> None:
    assert decide(summarise(_run(100.0)), offline=True)["evidence"] is False


def test_the_tables() -> None:
    rows = [
        *_run(1600.0),
        _row("b", 900, 0.0, outcome="discarded", discard_reason="skew", stop_landed=True),
        _row("b", 901, 0.0, outcome="discarded", discard_reason="incomplete", stop_landed=False),
        _row(
            "b",
            902,
            0.0,
            outcome="rejected",
            stage="trading_stop",
            ret_code=34040,
            adapter_error_code="UNKNOWN_STATE",
            s86_code="EXCHANGE_UNKNOWN",
            taxonomy_divergent=True,
        ),
    ]
    arms = summarise(rows)["arms"]
    assert isinstance(arms, dict)
    b = arms["b"]
    assert b["n"] == 203 and b["kept"] == 201
    assert b["discarded"] == {"incomplete": 1, "skew": 1}
    assert b["skew_discard_share"] == round(1 / 203, 6) and arms["a"]["skew_discard_share"] == 0.0
    assert b["outcomes"] == {"ok": 200, "rejected": 1}
    assert b["success_rate"] == round(200 / 201, 4)
    assert b["measured"] == 200 and b["measured_symbols"] == sorted(SYMBOLS)
    assert b["latency_ms"]["p50"] == 100.0 and b["latency_ms"]["max"] == math.inf
    assert b["unbounded"] == 2 and b["stop_success_rate"] == round(201 / 203, 6)
    assert b["deadline_headroom_ms"] == 400.0
    assert b["ret_codes"] == [
        {
            "stage": "trading_stop",
            "ret_code": 34040,
            "adapter_error_code": "UNKNOWN_STATE",
            "s86_code": "EXCHANGE_UNKNOWN",
            "divergent": True,
            "n": 1,
        }
    ]
    assert b["requests_per_protected_position"] == {
        "order_class": 1.0,
        "position_class": 1.0,
        "reads": 0.0,
    }
    assert set(b["by_symbol"]) == set(SYMBOLS) and arms["a"]["metric"] == "ack_ms"
    assert "deadline_headroom_ms" not in arms["a"]
