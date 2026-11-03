"""E12-Q05 slice 4 (#528): the backfill plan, the k6 summary verdicts and the fan-out helpers.
Pure helpers only; no k6 run, no stack. Built on the BQ defaults; rulings pending."""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from bench.bars import backfill_plan as bp
from bench.bars import fanout

END = 1_700_000_000_000_000
REPO = Path(__file__).resolve().parents[5]


def test_plan_covers_thirty_days_in_order_without_gaps() -> None:
    plan = bp.build_plan("BTCUSDT", END)
    pages = plan["pages"]
    assert len(pages) == 44  # 30 d of 1-minute candles at 1 000 a page
    assert pages[0]["params"]["from"] == bp._iso(END - 30 * bp.DAY_US)
    assert pages[-1]["params"]["to"] == bp._iso(END)
    for a, b in itertools.pairwise(pages):
        assert a["params"]["to"] == b["params"]["from"]
    assert {p["path"] for p in pages} == {"/market/klines"}


def test_plan_page_size_and_interval_are_respected() -> None:
    plan = bp.build_plan("ETHUSDT", END, days=1, interval_min=5, limit=100)
    assert len(plan["pages"]) == 3  # 288 candles at 100 a page
    assert plan["pages"][0]["params"] == {
        "symbol": "ETHUSDT", "interval": "5", "limit": 100,
        "from": bp._iso(END - bp.DAY_US), "to": bp._iso(END - bp.DAY_US + 100 * 5 * bp.MIN_US),
    }  # fmt: skip
    assert plan["other"]["params"]["to"] == bp._iso(END)


@pytest.mark.parametrize("kw", [{"days": 0}, {"interval_min": 0}, {"limit": 0}, {"limit": 1_001}])
def test_plan_refuses_bad_shapes(kw: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        bp.build_plan("BTCUSDT", END, **kw)


def _summary(page: float, other: float, nested: bool = True) -> dict[str, Any]:
    def m(v: float) -> dict[str, Any]:
        vals = {"p(95)": v, "count": 10}
        return {"values": vals} if nested else vals

    return {"metrics": {"backfill_page_ms": m(page), "other_route_ms": m(other)}}


@pytest.mark.parametrize("nested", [True, False])
def test_judge_passes_under_budget_13_in_both_summary_shapes(nested: bool) -> None:
    assert all(c.passed for c in bp.judge(_summary(149.9, 50.0, nested)))


def test_judge_flags_a_stalled_other_route_by_name() -> None:
    checks = {c.name: c for c in bp.judge(_summary(80.0, 150.0))}  # boundary is a failure
    assert checks["backfill_page_ms"].passed and not checks["other_route_ms"].passed


def test_judge_missing_samples_is_an_error() -> None:
    with pytest.raises(ValueError, match="other_route_ms"):
        bp.judge({"metrics": {"backfill_page_ms": {"p(95)": 1, "count": 3}}})


def test_main_writes_the_plan(tmp_path: Path) -> None:
    out = tmp_path / "plan.json"
    assert bp.main([str(END), str(out)]) == 0
    assert len(json.loads(out.read_text())["pages"]) == 44
    assert bp.main([]) == 2


def test_fanout_env_is_the_bars_only_w5_overrides() -> None:
    assert fanout.env() == {"PROFILE": "W5", "FAMILIES": "bars"}
    assert fanout.env(lagging_rtt_ms=700)["RTT_DELAY_MS"] == "700"
    with pytest.raises(ValueError):
        fanout.env(lagging_rtt_ms=-1)


def test_fanout_judge_flags_loss_errors_and_lag() -> None:
    ok = {"cv_seq_gaps": 0, "cv_unplanned_closes": 0, "cv_errors": 0}
    assert all(c.passed for c in fanout.judge(ok, 19.9))
    bad = fanout.judge({**ok, "cv_seq_gaps": 2}, 20.0)
    assert [c.name for c in bad if not c.passed] == ["cv_seq_gaps", "client_lag_p95_ms"]
    with pytest.raises(KeyError):
        fanout.judge({"cv_seq_gaps": 0}, 1.0)


def test_fanout_pending_rows_name_every_missing_metric_and_the_slow_reader() -> None:
    rows = "\n".join(fanout.pending())
    for name in ("ws_client_queue_depth", "ws_client_disconnect_overflow_total",
                 "bars_build_duration_seconds", "bars_rebuild_duration_seconds"):  # fmt: skip
        assert name in rows
    assert "#535" in rows and "slow consumer" in rows


def test_the_k6_script_is_loopback_guarded_and_gates_budget_13() -> None:
    src = (REPO / "tests" / "load" / "k6" / "bars" / "backfill.js").read_text(encoding="utf-8")
    assert "refusing non-loopback target" in src and "127\\.0\\.0\\.1|localhost" in src
    assert 'backfill_page_ms: ["p(95)<150"]' in src and "bybit" not in src.lower()
