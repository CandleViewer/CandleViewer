# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The summary's tables and the decision rule agreed up front in #856 (p99 of arm (b) above
1.5 s means attach-only), at its edge, below the floors and offline."""

from __future__ import annotations

import pytest

from spike.sl_attach.decision import decide
from spike.sl_attach.results import Sample
from spike.sl_attach.summary import summarise

SYMBOLS = ("BTCUSDT", "ETHUSDT", "THINUSDT")


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


def test_an_offline_run_is_never_evidence() -> None:
    assert decide(summarise(_run(100.0)), offline=True)["evidence"] is False


def test_the_tables() -> None:
    rows = [
        *_run(1600.0),
        _row("b", 900, 0.0, outcome="discarded", discard_reason="skew"),
        _row("b", 901, 0.0, outcome="discarded", discard_reason="incomplete"),
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
    assert b["outcomes"] == {"ok": 200, "rejected": 1}
    assert b["success_rate"] == round(200 / 201, 4)
    assert b["measured"] == 200 and b["measured_symbols"] == sorted(SYMBOLS)
    assert b["latency_ms"]["p50"] == 100.0 and b["latency_ms"]["max"] == 1600.0
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
