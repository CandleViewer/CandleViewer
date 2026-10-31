"""E16-Q04 soak: continuous recording of 2 symbols at depth 200 on a virtual clock.

Asserts (exit 1 on any): zero dropped rows, a backlog p95 of 0 at flush boundaries, zero spill
bytes, produced == written + gap-accounted rows, p95 flush < 50 ms, RSS <= 512 MiB, and GB/day per
symbol within 20 % of the E16-K01 figure (`bench/baselines/e16/recorder_soak.json`, provisional
until the live re-measure, #1778). The feed is the recorded corpus re-issued by `generator.Mix` at
the 21 §11.1 reference rates (E16-K01's rows/day), the rate the E16-K01 figure is defined on.
`--hours` is scenario time; the writer's clock is virtual, so a run takes as long as the CPU needs.
`smoke` scales the rate to 200 msg/s for 3 s: GB/day is then reported, never gated.

    uv run python -m bench.recorder.soak --profile smoke
    uv run python -m bench.recorder.soak --profile full --hours 24 \\
        --out bench/reports/recorder_soak.json

Never run the full profile on a shared host (an agent VPS or the bench runner during a soak).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from bench.ingestion.config import machine_profile
from bench.recorder.budgets import RunResult, soak_verdict
from bench.recorder.generator import Mix, reference_phase
from bench.recorder.harness import LoadConfig, finish, load_baseline, record_baseline, run
from bench.storage_measure import REFERENCE_ROWS_DAY

SYMBOLS: Final = ("BTCUSDT", "ETHUSDT")
SMOKE_MSGS_PER_S: Final = 200.0
SMOKE_S: Final = 3.0
BASELINE: Final = "recorder_soak"


def parse(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    ap.add_argument("--hours", type=float, default=24.0, help="full profile: scenario hours")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=None, help="the JSON report")
    ap.add_argument("--record-baseline", action="store_true", help="local only; refused in CI")
    return ap.parse_args(argv)


async def soak(profile: str, hours: float, seed: int, wal_dir: Path) -> RunResult:
    weights, per_symbol = reference_phase(REFERENCE_ROWS_DAY)
    full = profile == "full"
    cfg = LoadConfig(
        profile=profile,
        msgs_per_s=per_symbol * len(SYMBOLS) if full else SMOKE_MSGS_PER_S,
        duration_s=hours * 3600 if full else SMOKE_S,
        symbols=SYMBOLS, wal_dir=wal_dir, clock="virtual", seed=seed, depth=200,
    )  # fmt: skip
    mix = Mix(
        SYMBOLS, seed=seed, depth=200,
        phases={"reference": (weights["trades"], weights["orderbook_deltas"], 0.0)},
        odds=(("reference", 1.0),),
    )  # fmt: skip
    return await run(cfg, mix=mix)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(argv)
    if args.profile == "full" and args.hours <= 0:
        raise SystemExit("--hours must be positive")
    with tempfile.TemporaryDirectory(prefix="cv-recorder-soak-") as tmp:
        result = asyncio.run(soak(args.profile, args.hours, args.seed, Path(tmp) / "wal"))
    baseline = load_baseline(BASELINE)
    reference = float(baseline["gb_per_day_per_symbol"]["value"])
    verdict = soak_verdict(result, reference, gate_gb=args.profile == "full")
    if args.record_baseline:
        record_baseline(verdict, baseline, args.profile)
    return finish(
        verdict, result, out=args.out, baseline=baseline, machine_profile=machine_profile()
    )


if __name__ == "__main__":
    sys.exit(main())
