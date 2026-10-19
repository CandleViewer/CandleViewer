"""`python -m spikes.oms_demo_path {orders,soak}` (run from `services/api/`; see README.md).

The demo key pair comes from the process environment only and is popped from it at once; the
environment variable `CV_SPIKE_BYBIT_ENV` must say `demo`. Every refusal names its rule only.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import structlog

from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS, SIGNED_REST_BASES
from candleviewer.observability import configure_logging

from .runner import Config, run
from .safety import (
    ENV_VAR,
    MAX_ORDER_NOTIONAL,
    MAX_RUN_EXPOSURE,
    SafetyRefusal,
    check_target,
    load_credentials,
)

_HERE = Path(__file__).resolve().parent


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m spikes.oms_demo_path", description=__doc__)
    p.add_argument("mode", choices=("orders", "soak"))
    p.add_argument("--symbol", default="ETHUSDT", help="BTCUSDT, ETHUSDT or SOLUSDT")
    p.add_argument("--hours", type=float, help="run length; default 4 (orders) or 24 (soak)")
    p.add_argument("--orders", type=int, default=200, help="order cycles in the run")
    p.add_argument("--lots", type=int, default=5, help="order size in qty steps (>= 2)")
    p.add_argument("--max-order-usdt", type=Decimal, default=MAX_ORDER_NOTIONAL)
    p.add_argument("--max-exposure-usdt", type=Decimal, default=MAX_RUN_EXPOSURE)
    p.add_argument("--sl-pct", type=Decimal, default=Decimal(2), help="native SL distance, %%")
    p.add_argument("--fill-wait-s", type=float, default=30.0, help="wait for a passive fill")
    p.add_argument("--taker-every", type=int, default=5, help="every Nth order crosses; 0: never")
    p.add_argument("--capture-10002", action="store_true", help="one read stamped 30 s behind")
    p.add_argument("--capture-10018", action="store_true", help="one bounded burst, at the end")
    p.add_argument("--burst-max", type=int, default=700, help="requests in that burst (<= 1000)")
    p.add_argument("--retention-probe", type=Path, metavar="ORDERS_CSV", help="earlier run's")
    p.add_argument("--metrics-port", type=int, default=0, help="serve /metrics on 127.0.0.1")
    p.add_argument("--out", type=Path, default=_HERE / "runs")
    p.add_argument("--staging", type=Path, default=_HERE / "staging")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    stamp = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{args.mode}"
    try:
        env = os.environ.get(ENV_VAR, "")
        check_target(env, SIGNED_REST_BASES.get(env, ""), PRIVATE_WS_URLS.get(env, ""))
        cfg = Config(
            mode=args.mode,
            symbol=args.symbol,
            out=args.out / stamp,
            staging=args.staging / stamp,
            hours=args.hours or (4.0 if args.mode == "orders" else 24.0),
            orders=args.orders,
            lots=args.lots,
            max_order_usdt=args.max_order_usdt,
            max_exposure_usdt=args.max_exposure_usdt,
            sl_pct=args.sl_pct / 100,
            fill_wait_s=args.fill_wait_s,
            taker_every=args.taker_every,
            capture_10002=args.capture_10002,
            capture_10018=args.capture_10018,
            burst_max=args.burst_max,
            retention_probe=args.retention_probe,
            metrics_port=args.metrics_port,
        )
        creds = load_credentials(os.environ)
    except SafetyRefusal as exc:
        parser.exit(2, f"refused: {exc}\n")
    configure_logging(env="demo", level="info", fmt="json")
    log = structlog.get_logger(__name__)
    try:
        report = asyncio.run(run(cfg, creds))
    except SafetyRefusal as exc:
        log.error("refused", rule=str(exc))
        return 2
    except Exception as exc:  # through the redacting logger, never a bare traceback
        log.error("run_failed", error=type(exc).__name__, detail=str(exc))
        return 1
    log.info("run_written", out=str(cfg.out), outcome=report["outcome"])
    return 0 if report["outcome"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
