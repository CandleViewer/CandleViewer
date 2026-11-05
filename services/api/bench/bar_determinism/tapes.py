"""The five E12-Q02 conformance tapes (deterministic SYNTHETIC stand-ins, exception #1778 A).

Real exchange symbol-day recordings do not exist yet (recorder E16 not shipped), so each named tape
is built from the E12-T04 seeded generator (`generator.iter_trades`) with the characteristics the
test plan (`qa/plans/e12-bars-and-series-test-plan.md` §8.2) names. They are committed as
gzip'd JSONL under `packages/fixtures/golden/bars/conformance/tapes/` and MUST be replaced by
recorder captures when E16 lands (epic #42). Pure functions of their definitions; no I/O except
`write_tape` / `read_tape`.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from candleviewer.exchange.base.models import TradeEvent

from .generator import LOT, SYMBOL, TICK, GenConfig, iter_trades

REPO = Path(__file__).resolve().parents[4]
BANK_DIR = REPO / "packages" / "fixtures" / "golden" / "bars" / "conformance"
TAPES_DIR = BANK_DIR / "tapes"
_EID = uuid.UUID(int=0xE12A02)
_DAY_US = 86_400_000_000
MAX_LINES = 1_000_000  # parser bounds: a garbage tape raises, never allocates without limit
MAX_LINE_BYTES = 512


class TapeFormatError(ValueError):
    """A tape file is truncated, oversized, or not a valid trade record stream."""


def day_us(iso_day: str, hms: str = "00:00:00") -> int:
    from datetime import UTC, datetime

    dt = datetime.fromisoformat(f"{iso_day}T{hms}").replace(tzinfo=UTC)
    return int(dt.timestamp()) * 1_000_000


def event(
    seq: int, ts: int, price: Decimal, qty: Decimal, side: str, symbol: str, tid: str
) -> TradeEvent:
    return TradeEvent.model_construct(
        schema_version=1,
        event_id=_EID,
        ts_event=ts,
        ts_ingest=ts,
        source="replay",
        category="linear",
        symbol=symbol,
        trade_id=tid,
        price=price,
        qty=qty,
        side=side,
        is_block_trade=False,
        price_ticks=int(price / TICK),
        notional=price * qty,
        seq=seq,
    )


@dataclass(frozen=True)
class TapeDef:
    name: str
    symbol: str
    source_symbol_day: str
    description: str
    build: Callable[[], tuple[list[TradeEvent], dict[str, Any]]]
    heavy: bool = False  # golden comparison runs in the `harness` lane only
    notes: dict[str, Any] = field(default_factory=dict)


def _shifted(cfg: GenConfig, symbol: str, t0: int) -> list[TradeEvent]:
    off = t0 - 1_700_000_000_000_000
    return [
        t.model_copy(
            update={"ts_event": t.ts_event + off, "ts_ingest": t.ts_event + off, "symbol": symbol}
        )
        for t in iter_trades(cfg)
    ]


def _dense() -> tuple[list[TradeEvent], dict[str, Any]]:
    # Real day ~1.2M prints; capped at 200k to keep the repo small (same shape, 1/6 the count).
    cfg = GenConfig(
        seed=20260901,
        n=200_000,
        mean_dt_us=432_000,
        size_scale_lots=400,
        threshold_lots=50_000,
        buy_skew=0.08,
        p_duplicate=0.0,
    )
    return _shifted(cfg, "BTCUSDT", day_us("2026-09-01")), {"seed": cfg.seed}


def _gap() -> tuple[list[TradeEvent], dict[str, Any]]:
    cfg = GenConfig(
        seed=20260902,
        n=40_000,
        mean_dt_us=2_160_000,
        size_scale_lots=400,
        threshold_lots=50_000,
        buy_skew=0.05,
        p_duplicate=0.0,
    )
    ts = _shifted(cfg, "BTCUSDT", day_us("2026-09-02"))
    start, length = 20_000, 150  # seqs [20000, 20150) never arrive live ...
    gap, rest = ts[start : start + length], ts[:start] + ts[start + length :]
    backfill = gap[:80]  # ... 80 of them are recovered by REST backfill 300 prints later
    out = rest[: start + 300] + backfill + rest[start + 300 :]
    meta = {"seed": cfg.seed, "gap_first_seq": start, "gap_len": length, "backfilled": 80}
    return out, meta


def _thin() -> tuple[list[TradeEvent], dict[str, Any]]:
    cfg = GenConfig(
        seed=20260903,
        n=3_000,
        mean_dt_us=28_800_000,
        size_scale_lots=40,
        threshold_lots=50_000,
        start_px_ticks=32_000,
        p_duplicate=0.0,
        p_silence=0.002,
    )
    return _shifted(cfg, "ETHUSDT", day_us("2026-09-03")), {"seed": cfg.seed}


def _newlist() -> tuple[list[TradeEvent], dict[str, Any]]:
    cfg = GenConfig(
        seed=20260904,
        n=20_000,
        mean_dt_us=2_000_000,
        size_scale_lots=400,
        threshold_lots=50_000,
        start_px_ticks=5_000,
        p_duplicate=0.0,
    )
    t0 = day_us("2026-09-04", "11:17:00")
    meta = {
        "seed": cfg.seed,
        "listed_at_utc": "2026-09-04T11:17:00Z",
        "recording_started_at": "2026-09-04T11:17:00Z",
    }
    return _shifted(cfg, "NEWCOINUSDT", t0), meta


def _edge() -> tuple[list[TradeEvent], dict[str, Any]]:
    """Hand-sequenced exact-boundary prints for vol:50, range:20, renko:30, delta:500, tick:100,
    plus prints exactly on 1 m boundaries. Prices in ticks of 0.1; sizes in BTC."""
    out: list[TradeEvent] = []
    t = day_us("2026-09-05", "00:00:00")

    def add(px_ticks: int, qty: str, side: str = "buy", dt_us: int = 1_000_000) -> None:
        nonlocal t
        t += dt_us
        out.append(
            event(
                len(out),
                t,
                Decimal(px_ticks) * TICK,
                Decimal(qty),
                side,
                SYMBOL,
                f"edge-{len(out):x}",
            )
        )

    base = 600_000
    for _ in range(3):  # (a) a print that exactly fills a 50 volume bar, then 3x overshoot
        add(base, "20")
        add(base, "30")  # 20 + 30 == 50 exactly -> closes, no empty successor
        add(base + 1, "150.003")  # overshoots 50 by 3x + 0.003: split across 4 bars
        add(base + 1, "49.997")  # tops the open remainder to exactly 50
    for k in range(4):  # (b) exact range: span exactly 20 ticks (2.0), then 19 ticks, then 21
        top = base + 100 * k
        add(top, "1")
        add(top + 19, "1")  # span 19 ticks: stays open (range:20)
        add(top + 20, "1")  # span exactly 20: closes (inclusive)
        add(top + 20, "1")
        add(top + 41, "1")  # jump of 21 ticks beyond the new open: closes again
    px = base + 1000
    for _ in range(3):  # (c) renko:30 -- exactly one brick (30 ticks), then 29, then two bricks
        add(px, "1")
        add(px + 29, "1")
        add(px + 30, "1")  # exactly one brick up
        add(px + 60, "1")  # exactly one more brick
        add(px + 30 - 30 * 2, "1")  # back down two bricks: reversal needs 2 bricks
        px += 500
    for _ in range(3):  # (d) delta:500: +499, then +1 -> exactly 500; then -500 in one print
        add(base + 2000, "499", "buy")
        add(base + 2000, "1", "buy")
        add(base + 2000, "500", "sell")
    for k in range(4):  # (e) prints exactly on / one µs around a 1 m boundary
        edge = -(-t // 60_000_000) * 60_000_000 + 60_000_000
        t = edge - 1
        add(base + 3000 + k, "1", dt_us=0)
        add(base + 3000 + k, "1", dt_us=1)  # exactly on the boundary
        add(base + 3000 + k, "1", dt_us=1)
    for i in range(1200):  # (f) tick-count padding: crosses tick:100 and tick:1000 exactly
        add(base + 4000 + (i % 7), "0.5", "buy" if i % 2 else "sell", dt_us=500_000)
    # (g) range:20 jump boundary: the closing trade lands exactly 2 x width (40 ticks) above the
    # pinned open. The padding keeps the open bar within 6 ticks, so 30 ticks up closes it without
    # a jump (span 24..30 < 40), pinning the next open at base+4030; +40 ticks from there is
    # span == 2 * width exactly (the `>=` in the jump check); the print after it shows gap_before.
    add(base + 4030, "1")
    add(base + 4070, "1")
    add(base + 4070, "1")
    return out, {
        "sections": "vol-exact+3x, range-exact, renko-exact, delta-exact, boundary, ticks, "
        "range-2x-jump"
    }


TAPES: dict[str, TapeDef] = {
    "btcusdt-2026-09-01": TapeDef(
        "btcusdt-2026-09-01",
        "BTCUSDT",
        "BTCUSDT 2026-09-01 (dense day, ~1.2M prints real)",
        "dense; 200k prints (capped from ~1.2M for repo size)",
        _dense,
        heavy=True,
    ),
    "btcusdt-2026-09-02-gap": TapeDef(
        "btcusdt-2026-09-02-gap",
        "BTCUSDT",
        "BTCUSDT 2026-09-02 (deliberate WS sequence gap)",
        (
            "hole + late backfill: 150 prints never arrive live; 80 arrive ~650 s late, outside "
            "the 60 s amend window, so dropped as late_window"
        ),
        _gap,
        heavy=True,
    ),
    "ethusdt-2026-09-03-thin": TapeDef(
        "ethusdt-2026-09-03-thin",
        "ETHUSDT",
        "ETHUSDT 2026-09-03 (thin tape)",
        "thin: most 1 m intervals empty",
        _thin,
    ),
    "newlist-2026-09-04": TapeDef(
        "newlist-2026-09-04",
        "NEWCOINUSDT",
        "NEWCOINUSDT 2026-09-04 (listed 11:17Z)",
        "mid-day listing; recording_started_at 11:17Z",
        _newlist,
    ),
    "edge-ticks": TapeDef(
        "edge-ticks",
        "BTCUSDT",
        "synthetic (no symbol-day)",
        "exact-threshold / exact-range / exact-brick / boundary prints",
        _edge,
    ),
}


def tape_path(name: str) -> Path:
    return TAPES_DIR / f"{name}.jsonl.gz"


def serialise(tape: Iterable[TradeEvent]) -> bytes:
    """Deterministic gzip'd JSONL (mtime 0, fixed key order, Decimal strings, no floats)."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as gz:
        for t in tape:
            rec = {
                "ts": t.ts_event,
                "price": str(t.price),
                "size": str(t.qty),
                "side": t.side,
                "trade_id": t.trade_id,
            }
            gz.write(json.dumps(rec, separators=(",", ":")).encode() + b"\n")
    return buf.getvalue()


def parse(data: bytes, symbol: str) -> list[TradeEvent]:
    """Decode a tape; a truncated / garbage / oversized stream raises `TapeFormatError`."""
    out: list[TradeEvent] = []
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as gz:
            while True:
                line = gz.readline(MAX_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                    raise TapeFormatError(f"line {len(out)}: oversized or unterminated")
                if len(out) >= MAX_LINES:
                    raise TapeFormatError(f"more than {MAX_LINES} records")
                r = json.loads(line)
                out.append(
                    event(
                        len(out),
                        int(r["ts"]),
                        Decimal(r["price"]),
                        Decimal(r["size"]),
                        r["side"],
                        symbol,
                        str(r["trade_id"]),
                    )
                )
    except (OSError, EOFError, ValueError, KeyError, TypeError, InvalidOperation) as e:
        if isinstance(e, TapeFormatError):
            raise
        raise TapeFormatError(f"record {len(out)}: {type(e).__name__}: {e}") from e
    for t in out:
        if t.side not in ("buy", "sell") or t.qty <= 0 or t.price <= 0:
            raise TapeFormatError(f"record {t.seq}: invalid side/size/price")
    return out


def read_tape(name: str) -> list[TradeEvent]:
    return parse(tape_path(name).read_bytes(), TAPES[name].symbol)


def sha256_of(name: str) -> str:
    return hashlib.sha256(tape_path(name).read_bytes()).hexdigest()


__all__ = ["LOT", "TAPES", "TapeDef", "TapeFormatError", "parse", "read_tape", "serialise"]
