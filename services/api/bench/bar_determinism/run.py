"""Determinism-harness runner: rebuild throughput per builder + full BI-1..BI-6 sweep (E12-T04).

    cd services/api
    uv run python -m bench.bar_determinism.run --n 1000000 --out bar-determinism.json
    uv run python -m bench.bar_determinism.run --n 1000000 --update-baseline   # deliberate only

Exit codes: 0 green; 1 an invariant violation or a throughput drop > 25 % vs the committed
baseline (`baseline.json`); a drop > 10 % prints a `::warning::` line. Seeded and offline.
Throughput is the production builder alone (`on_trade` + `on_clock` for time bars) over an
in-memory tape, through `invariants.count`, which retains no emission (#2022: the timing is the
builder's, not a list of a million updates); tape generation is excluded. The invariant sweep
keeps the full feed. The E12-K01 prototype figures
(`docs/research/e12/renko-rebuild-results.json`, `bench/renko_rebuild`) are reported alongside
for continuity; they are integer-tick prototypes, so they are context, not the gate.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

import structlog

from . import generator, invariants

HERE = Path(__file__).resolve().parent
BASELINE = HERE / "baseline.json"
K01 = HERE.parents[3] / "docs" / "research" / "e12" / "renko-rebuild-results.json"
WARN_DROP, FAIL_DROP = 0.10, 0.25


def throughput(spec_label: str, tape: list[Any], repeats: int = 1) -> float:
    """Best-of-`repeats` trades/s for one production builder."""
    spec = invariants.STANDARD_SPECS[spec_label]
    best = 0.0
    for _ in range(repeats):
        b = invariants.make_builder(spec)
        t0 = time.perf_counter()
        invariants.count(b, tape)
        best = max(best, len(tape) / (time.perf_counter() - t0))
    return best


def k01_rows_per_s() -> dict[str, float]:
    if not K01.exists():
        return {}
    doc = json.loads(K01.read_text(encoding="utf-8"))
    return {b["kind"]: float(b["rows_per_s"]) for b in doc.get("builders", [])}


def compare(current: dict[str, float], baseline: dict[str, float]) -> tuple[list[str], list[str]]:
    """(warnings, failures) for drops vs baseline, per spec label."""
    warns, fails = [], []
    for label, now in current.items():
        base = baseline.get(label)
        if not base:
            continue
        drop = 1 - now / base
        msg = f"{label}: {now:,.0f}/s vs baseline {base:,.0f}/s ({drop:+.1%} drop)"
        if drop > FAIL_DROP:
            fails.append(msg)
        elif drop > WARN_DROP:
            warns.append(msg)
    return warns, fails


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=1_000_000)
    ap.add_argument("--seed", type=int, default=generator.GenConfig().seed)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--skip-invariants", action="store_true")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args(argv)
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR))

    t_start = time.perf_counter()
    tape = generator.generate(generator.GenConfig(seed=args.seed, n=args.n))
    rates = {lbl: throughput(lbl, tape, args.repeats) for lbl in invariants.STANDARD_SPECS}
    violations: list[invariants.Violation] = []
    inv_s: dict[str, float] = {}
    if not args.skip_invariants:
        for lbl, spec in invariants.STANDARD_SPECS.items():
            t0 = time.perf_counter()
            violations += invariants.check(lbl, spec, tape, seed=args.seed)
            inv_s[lbl] = round(time.perf_counter() - t0, 1)
            print(f"{lbl}: invariants checked in {inv_s[lbl]} s", flush=True)

    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    warns, fails = compare(rates, baseline.get("rows_per_s", {}))
    if baseline and baseline.get("system") != platform.system():
        # A baseline from another OS/hardware class is not comparable: report, do not gate.
        print(
            f"::warning::baseline recorded on {baseline.get('system')}, running on "
            f"{platform.system()}: throughput reported, not gated; re-record it on this runner"
        )
        warns, fails = warns + fails, []
    k01 = k01_rows_per_s()
    print(f"{'spec':<20}{'rows/s':>12}{'baseline':>12}{'K01 proto':>12}  1M rebuild")
    for lbl, r in rates.items():
        base = baseline.get("rows_per_s", {}).get(lbl, 0.0)
        proto = k01.get(invariants.STANDARD_SPECS[lbl].kind, 0.0)
        print(f"{lbl:<20}{r:>12,.0f}{base:>12,.0f}{proto:>12,.0f}  {1e6 / r:6.2f} s")
    for w in warns:
        print(f"::warning::throughput regression >10%: {w}")
    for f in fails:
        print(f"::error::throughput regression >25%: {f}")
    for v in violations:
        print(f"::error::{v}")

    doc = {
        "n": args.n,
        "seed": args.seed,
        "python": platform.python_version(),
        "machine": platform.platform(),
        "system": platform.system(),
        "rows_per_s": {k: round(v) for k, v in rates.items()},
        "invariant_seconds": inv_s,
        "invariants": {
            lbl: sorted({v.invariant for v in violations if v.spec == lbl}) or "pass"
            for lbl in invariants.STANDARD_SPECS
        },
        "wall_s": round(time.perf_counter() - t_start, 1),
    }
    if args.out:
        args.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    if args.update_baseline:
        if os.environ.get("CI"):
            print("refused: the baseline is never rewritten by CI", file=sys.stderr)
            return 2
        base_doc = {k: doc[k] for k in ("n", "seed", "python", "machine", "system", "rows_per_s")}
        BASELINE.write_text(json.dumps(base_doc, indent=2) + "\n", encoding="utf-8")
    return 1 if violations or fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
