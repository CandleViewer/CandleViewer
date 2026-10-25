"""The harness's run settings, the demo allow-list it pins and its command line (#843 A4)."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast
from uuid import UUID

#: The one contract the spike trades (#843: "minimum BTCUSDT sizes").
SYMBOL: Final = "BTCUSDT"
#: The demo allow-list, pinned here and checked against the adapter's own tables at start
#: (`safety.check_venue_urls`), then at every request and dial (`recorder.py`).
DEMO_REST_BASE: Final = "https://api-demo.bybit.com"
DEMO_REST_HOST: Final = "api-demo.bybit.com"
DEMO_PRIVATE_WS: Final = "wss://stream-demo.bybit.com/v5/private"
#: What the operator types before an online run sends anything.
CONFIRMATION: Final = "PLACE DEMO ORDERS"
#: The ticket's floors for an online run (#843 Scope): >=200 cycles over >=4 h, a 24 h soak.
MIN_CYCLES: Final = 200
MIN_HOURS: Final = 4.0
SOAK_HOURS: Final = 24.0
#: `retention` reads orders older than 7 days, so it runs on day 8 or later (24 §8.3 rule 6).
RETENTION_MIN_DAYS: Final = 8
#: The most any request may size, in minimum quantities, whatever `--max-qty-multiple` says.
QTY_MULTIPLE_CEILING: Final = 10
#: The stack's audit WAL and volume (`infra/compose/docker-compose.yml`): never the harness's.
STACK_AUDIT_WAL: Final = "/var/lib/candleviewer/audit/audit.wal"
STACK_AUDIT_VOLUME: Final = "cv-audit-data"
#: The governor's bucket label for the account (`AccountRef.uid` is never sent): the harness
#: needs no UID, so none is asked for, held or written.
BUCKET_UID: Final = "spike"

type Mode = Literal["cycles", "soak", "shapes", "retention", "report"]
MODES: Final[tuple[Mode, ...]] = ("cycles", "soak", "shapes", "retention", "report")


@dataclass(frozen=True, slots=True)
class RunConfig:
    """One run. `online` is set only by `--demo`; everything else defaults to the offline run."""

    mode: Mode
    out: Path
    online: bool = False
    understood: bool = False
    account_id: UUID | None = None
    key_ref: str | None = None
    cycles: int = MIN_CYCLES
    min_hours: float = MIN_HOURS
    hours: float = SOAK_HOURS
    qty_multiple: int = 2
    max_qty_multiple: int = 2
    away_bps: int = 100
    sl_bps: int = 300
    cross_bps: int = 10
    fill_wait_s: float = 20.0
    side: Literal["buy", "sell", "alternate"] = "alternate"
    fill_mode: Literal["join", "cross", "alternate"] = "alternate"
    offset_every: int = 25
    since_ms: int | None = None
    run_dir: Path | None = None
    corpus: Path | None = None
    stack_audit_wal: str = STACK_AUDIT_WAL
    stack_volume: str = STACK_AUDIT_VOLUME
    #: Offline only: the corpus venue withholds every Nth fill from the stream, or pushes every
    #: Nth fill's order update before its execution, so the counters are seen to count.
    drop_every: int = 0
    reorder_every: int = 0

    @property
    def places_orders(self) -> bool:
        return self.mode in ("cycles", "shapes")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m spike.oms_demo_path",
        description="E29-K01 demo order-path spike (offline by default; --demo dials the venue).",
    )
    p.add_argument("mode", choices=MODES)
    p.add_argument("--out", type=Path, required=True, help="the run's output directory")
    venue = p.add_mutually_exclusive_group()
    venue.add_argument("--offline", action="store_true", help="the corpus venue (default)")
    venue.add_argument("--demo", action="store_true", help="the exchange's demo host")
    p.add_argument("--i-understand-this-places-demo-orders", dest="understood", action="store_true")
    p.add_argument("--account-id", type=UUID, help="exchange_accounts.id of the demo account")
    p.add_argument("--key-ref", help="api_keys.id of its active key (M2 signs; never the key)")
    p.add_argument("--cycles", type=int, default=MIN_CYCLES)
    p.add_argument("--min-hours", type=float, default=MIN_HOURS)
    p.add_argument("--hours", type=float, default=SOAK_HOURS)
    p.add_argument("--qty-multiple", type=int, default=2)
    p.add_argument("--max-qty-multiple", type=int, default=2)
    p.add_argument("--away-bps", type=int, default=100)
    p.add_argument("--sl-bps", type=int, default=300)
    p.add_argument("--cross-bps", type=int, default=10)
    p.add_argument("--fill-wait-s", type=float, default=20.0)
    p.add_argument("--side", choices=("buy", "sell", "alternate"), default="alternate")
    p.add_argument("--fill-mode", choices=("join", "cross", "alternate"), default="alternate")
    p.add_argument("--offset-every", type=int, default=25)
    p.add_argument("--since-ms", type=int, help="retention: the earlier run's started_at_ms")
    p.add_argument("--run-dir", type=Path, help="report: a run's output directory")
    p.add_argument("--corpus", type=Path, help="offline: the recorded corpus directory")
    p.add_argument("--stack-audit-wal", default=STACK_AUDIT_WAL)
    p.add_argument("--stack-volume", default=STACK_AUDIT_VOLUME)
    p.add_argument("--offline-drop-every", dest="drop_every", type=int, default=0)
    p.add_argument("--offline-reorder-every", dest="reorder_every", type=int, default=0)
    return p


def parse(argv: Sequence[str]) -> RunConfig:
    """The run the command line names; `argparse` exits 2 on a malformed one."""
    a = _parser().parse_args(list(argv))
    key_ref: str | None = a.key_ref
    return RunConfig(
        mode=cast("Mode", a.mode),
        out=a.out,
        online=bool(a.demo),
        understood=bool(a.understood),
        account_id=a.account_id,
        key_ref=key_ref,
        cycles=a.cycles,
        min_hours=a.min_hours,
        hours=a.hours,
        qty_multiple=a.qty_multiple,
        max_qty_multiple=a.max_qty_multiple,
        away_bps=a.away_bps,
        sl_bps=a.sl_bps,
        cross_bps=a.cross_bps,
        fill_wait_s=a.fill_wait_s,
        side=a.side,
        fill_mode=a.fill_mode,
        offset_every=a.offset_every,
        since_ms=a.since_ms,
        run_dir=a.run_dir,
        corpus=a.corpus,
        stack_audit_wal=a.stack_audit_wal,
        stack_volume=a.stack_volume,
        drop_every=a.drop_every,
        reorder_every=a.reorder_every,
    )
