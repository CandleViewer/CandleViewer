"""Scenario runner: config -> drive -> `budgets` verdict -> report (+ gate vs baseline).

    uv run python -m bench.ingestion.runner soak_steady --profile smoke
    uv run python -m bench.ingestion.runner all --profile full --out-dir bench/reports
    uv run python -m bench.ingestion.runner rest_k6 --profile full --serve   # k6 target

Exit 1 when any hard check fails or the baseline gate FAILs (never auto-updates a baseline).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from bench.ingestion import budgets
from bench.ingestion.config import REPORTS_DIR, SCENARIOS, Scenario, load, machine_profile
from bench.ingestion.engine import (
    LaneConfig,
    ProcSampler,
    PsutilProcSampler,
    run_lanes,
    symbols_for,
)
from bench.ingestion.ratelimit import run_headroom

PREFERRED = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _lane_cfg(sc: Scenario, **over: Any) -> LaneConfig:
    p = sc.params
    loads = tuple(tuple(x) for x in p.get("loads", ()))
    cfg = LaneConfig(
        symbols=symbols_for(int(p["symbols"]), PREFERRED),
        duration_s=float(p["duration_s"]),
        tick_s=float(p.get("tick_s", 0.1)),
        trades_per_s=int(p.get("trades_per_s", 50)),
        book_deltas_per_s=int(p.get("book_deltas_per_s", 10)),
        capacity_factor=int(p.get("capacity_factor", 4)),
        inbound_queue=int(p.get("inbound_queue", 64)),
        sample_every_s=float(p.get("sample_every_s", 60.0)),
        seed=int(p.get("seed", 7)),
        loads=loads,
        realtime=bool(p.get("realtime", False)),
    )
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


async def run_soak(sc: Scenario, sampler: ProcSampler, **over: Any) -> budgets.Verdict:
    cfg = _lane_cfg(sc, **over)
    res = await run_lanes(cfg, sampler, drain_ticks=int(60 / cfg.tick_s))
    v = budgets.Verdict(sc.name)
    v.add(budgets.check_loss(res.injected, res.ingested, res.detected_gap))
    base_at = float(sc.p("flatness_baseline_fraction")) * cfg.duration_s
    v.checks.extend(
        budgets.check_soak(
            res.samples, len(cfg.symbols), base_at, float(sc.p("flatness_tolerance"))
        )
    )
    lags = [x for per in res.lag_ms.values() for x in per["steady"]]
    v.metrics = {
        "ingest_lag_ms": budgets.summary(lags),
        "rss_mb_per_symbol": budgets.summary(
            budgets.rss_per_symbol_mb(res.samples, len(cfg.symbols))
        ),
        "vcpu_per_symbol": budgets.summary(budgets.vcpu_per_symbol(res.samples, len(cfg.symbols))),
        "event_loop_lag_ms": budgets.summary([s.loop_lag_ms for s in res.samples]),
        "queue_depth": budgets.summary([float(s.queue_depth) for s in res.samples]),
        "sampling_cost_ms": {
            "p50": res.sampling_cost_ms,
            "p95": res.sampling_cost_ms,
            "max": res.sampling_cost_ms,
            "count": float(len(res.samples)),
        },
    }
    v.metrics["_curve"] = {f"{s.t_s:.0f}": s.rss_bytes / 2**20 for s in res.samples}
    return v


async def run_isolation(sc: Scenario, sampler: ProcSampler) -> budgets.Verdict:
    """Scenarios 2 and 3: a loaded symbol (2: 3x sustained, 3: 5x/60 s) vs the others."""
    cfg = _lane_cfg(sc)
    res = await run_lanes(
        cfg, sampler, drain_ticks=int(float(sc.p("recovery_window_s")) * 4 / cfg.tick_s)
    )
    hot = [str(x[0]) for x in cfg.loads]
    v = budgets.Verdict(sc.name)
    v.add(budgets.check_loss(res.injected, res.ingested, res.detected_gap))
    v.add(
        budgets.check_isolation(
            {s: d["steady"] for s, d in res.lag_ms.items()},
            {s: d["loaded"] for s, d in res.lag_ms.items()},
            hot,
            float(sc.p("lag_band_floor_ms")),
            float(sc.p("lag_band_rel")),
        )
    )
    if sc.kind == "burst":
        sym = hot[0]
        v.checks.extend(
            budgets.check_burst(
                res.max_backlog[sym],
                int(sc.p("backlog_bound")),
                res.recovery_s[sym],
                float(sc.p("recovery_window_s")),
                float(res.backpressure[sym]),
            )
        )
    others = [x for s, d in res.lag_ms.items() if s not in hot for x in d["loaded"]]
    v.metrics = {
        "unaffected_lag_loaded_ms": budgets.summary(others),
        "loaded_symbol_lag_ms": budgets.summary([x for s in hot for x in res.lag_ms[s]["loaded"]]),
        "max_backlog": budgets.summary([float(res.max_backlog[s]) for s in hot]),
        "recovery_s": budgets.summary([r for s in hot if (r := res.recovery_s[s]) is not None]),
    }
    return v


async def run_latency(sc: Scenario, sampler: ProcSampler) -> budgets.Verdict:
    res = await run_lanes(_lane_cfg(sc), sampler, record_stages=True)
    v = budgets.Verdict(sc.name)
    v.add(budgets.check_latency(res.stage_ms, float(sc.p("budget_ms"))))
    v.metrics = {
        "receipt_to_publish_ms": budgets.summary(res.stage_ms),
        **{f"stage_{k}_ms": budgets.summary(x) for k, x in res.stage_parts_ms.items()},
    }
    return v


async def run_ratelimit(sc: Scenario) -> budgets.Verdict:
    p = sc.params
    res = await run_headroom(
        duration_s=float(p["duration_s"]),
        refresh_every_s=float(p["refresh_every_s"]),
        backfill_pages_per_s=float(p["backfill_pages_per_s"]),
        symbols=int(p["symbols"]),
        bucket_capacity=float(p["bucket_capacity"]),
        bucket_refill_per_s=float(p["bucket_refill_per_s"]),
    )
    v = budgets.Verdict(sc.name)
    v.checks.extend(budgets.check_headroom(res.min_uid_tokens, res.ip_holds, res.ip_limit_errors))
    v.metrics = {
        "uid_tokens": budgets.summary(res.tokens_trace),
        "ip_window_headroom_min": {
            "p50": float(res.min_ip_window_headroom),
            "p95": float(res.min_ip_window_headroom),
            "max": float(res.min_ip_window_headroom),
            "count": float(res.requests),
        },
    }
    return v


async def run_scenario(sc: Scenario, sampler: ProcSampler | None = None) -> budgets.Verdict:
    from bench.ingestion.rest_load import run_rest

    smp = sampler or PsutilProcSampler()
    if sc.kind == "soak":
        return await run_soak(sc, smp)
    if sc.kind in ("aggregate", "burst"):
        return await run_isolation(sc, smp)
    if sc.kind == "latency":
        return await run_latency(sc, smp)
    if sc.kind == "rest":
        return await run_rest(sc)
    if sc.kind == "ratelimit":
        return await run_ratelimit(sc)
    raise ValueError(f"unknown scenario kind {sc.kind!r}")


def main(argv: Sequence[str] | None = None) -> int:
    from datetime import UTC, datetime

    from bench.ingestion import gate, report

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("scenario", choices=(*SCENARIOS, "all"))
    ap.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    ap.add_argument("--out-dir", type=Path, default=REPORTS_DIR)
    ap.add_argument("--record-baseline", action="store_true", help="deliberate, local only")
    ap.add_argument("--grafana-url", default="")
    a = ap.parse_args(argv)
    names = SCENARIOS if a.scenario == "all" else (a.scenario,)
    profile = machine_profile()
    started = datetime.now(UTC)
    runs = []
    for name in names:
        sc = load(name, a.profile)
        t0 = time.perf_counter()
        v = asyncio.run(run_scenario(sc))
        g = gate.compare(v, gate.load_baseline(name), profile, sc.tolerances, a.profile)
        runs.append((sc, v, g))
        print(
            f"{name}: {'PASS' if v.passed else 'FAIL'} gate={g.status} "
            f"({time.perf_counter() - t0:.1f}s)"
        )
        for c in v.checks:
            if not c.passed:
                tag = "FAIL" if c.hard else "warn"
                print(f"  {tag} {c.name}: {c.measured:.4g} > {c.limit:.4g} {c.note}")
        for w in g.warnings:
            print(f"::warning::{name}: {w}")
        for f in g.failures:
            print(f"::error::{name}: {f}")
        if a.record_baseline:
            print(f"  baseline -> {gate.record(v, profile, sc.scaling, a.profile)}")
    finished = datetime.now(UTC)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    md = a.out_dir / f"e08-{a.profile}-{stamp}.md"
    md.write_text(report.render(runs, profile, started, finished, a.grafana_url), encoding="utf-8")
    js = a.out_dir / f"e08-{a.profile}-{stamp}.json"
    js.write_text(
        json.dumps(
            [
                {
                    "verdict": v.as_dict(),
                    "gate": {
                        "status": g.status,
                        "diff": g.diff,
                        "failures": g.failures,
                        "warnings": g.warnings,
                    },
                }
                for _, v, g in runs
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    diff = a.out_dir / "gate-diff.md"
    diff.write_text(
        "\n\n".join(f"### {sc.name} ({g.status})\n\n{gate.render_diff(g)}" for sc, _, g in runs),
        encoding="utf-8",
    )
    print(f"report: {md}")
    failed = any(not v.passed for _, v, _ in runs) or any(g.failures for _, _, g in runs)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
