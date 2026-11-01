"""E16-Q04 ingest load: the mix at 50 000 msg/s for 10 minutes through the real `StreamWriter`.

Asserts (exit 1 on any): p95 flush < 50 ms, process RSS <= 512 MiB, the rate reached (>= 95 % of
the target), zero dropped rows and produced == written + gap-accounted rows. The run is on wall
time; `--ilp 127.0.0.1:9009` writes to a local QuestDB (the CI pipeline's container), without it a
counting in-memory sink stands in. `smoke` is the PR-cheap scale (200 msg/s for 3 s).

    uv run python -m bench.recorder.ingest_load --profile smoke
    uv run python -m bench.recorder.ingest_load --profile full --ilp 127.0.0.1:9009 \\
        --out bench/reports/recorder_ingest.json
    uv run python -m bench.recorder.ingest_load --msgs-per-s 1000 --duration-s 5   # ad hoc
    uv run python -m bench.recorder.ingest_load --msgs-per-s 5000 --duration-s 20 \\
        --max-queue-rows 2000 --wal-max-bytes 4000000   # forced overflow: drops, gaps, a replay

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
from bench.recorder.budgets import ingest_verdict
from bench.recorder.harness import LoadConfig, finish, load_baseline, record_baseline, run

#: (msgs/s, seconds, symbols). Full = the ticket's 50k msg/s for 10 minutes.
PROFILES: Final[dict[str, tuple[float, float, tuple[str, ...]]]] = {
    "smoke": (200.0, 3.0, ("BTCUSDT", "ETHUSDT")),
    "full": (50_000.0, 600.0, ("BTCUSDT", "ETHUSDT", "SOLUSDT")),
}
BASELINE: Final = "recorder_ingest"


def parse(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    ap.add_argument("--msgs-per-s", type=float, default=None, help="overrides the profile's rate")
    ap.add_argument("--duration-s", type=float, default=None, help="overrides its duration")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max-queue-rows", type=int, default=None, help="per-lane queue bound")
    ap.add_argument("--wal-max-bytes", type=int, default=None, help="the WAL budget")
    ap.add_argument("--ilp", default=None, help="host:port of a loopback QuestDB ILP port")
    ap.add_argument("--out", type=Path, default=None, help="the JSON report")
    ap.add_argument("--record-baseline", action="store_true", help="local only; refused in CI")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(argv)
    rate, duration, symbols = PROFILES[args.profile]
    knobs = (args.msgs_per_s, args.duration_s, args.max_queue_rows, args.wal_max_bytes)
    custom = any(k is not None for k in knobs)
    profile = "custom" if custom else args.profile
    with tempfile.TemporaryDirectory(prefix="cv-recorder-ingest-") as tmp:
        cfg = LoadConfig(
            profile=profile,
            msgs_per_s=args.msgs_per_s if args.msgs_per_s is not None else rate,
            duration_s=args.duration_s if args.duration_s is not None else duration,
            symbols=symbols, wal_dir=Path(tmp) / "wal", clock="real", seed=args.seed,
            ilp=args.ilp, max_queue_rows=args.max_queue_rows, wal_max_bytes=args.wal_max_bytes,
        )  # fmt: skip
        result = asyncio.run(run(cfg))
    verdict = ingest_verdict(result)
    baseline = load_baseline(BASELINE)
    if args.record_baseline:
        record_baseline(verdict, baseline, profile)
    return finish(
        verdict, result, out=args.out, baseline=baseline, machine_profile=machine_profile()
    )


if __name__ == "__main__":
    sys.exit(main())
