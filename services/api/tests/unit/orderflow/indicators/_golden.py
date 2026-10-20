"""Golden-vector harness for the indicator kernels (E13-T02, #426; 24-internal-schemas §7.4).

`packages/fixtures/golden/indicators/` holds, per input set, the densified input bars
(`inputs_<set>.jsonl`) and one line per case (`vectors_<set>.jsonl`) with the kernel's float64
outputs (shortest round-trip strings) and the reference values (decimal strings, 20 significant
digits), plus `spec_hash_vectors.json` and `manifest.json`. The TS worker mirror (E13-T01) and
the parity pack (E13-Q05) read the same files. `test_golden_vectors.py` derives and checks them;
`CV_REGEN_GOLDEN=1` rewrites them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Final

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.series import BarSeries
from candleviewer.orderflow.indicators import (
    INDICATOR_SPEC_VERSION,
    KERNELS,
    STATE_VERSION,
    BarInput,
    KernelContext,
    bar_input,
    compute,
)
from candleviewer.orderflow.indicators.identity import (
    BAR_SOURCE,
    canonical_json,
    canonical_value,
    compute_spec_hash,
)
from candleviewer.orderflow.indicators.types import ParamValue
from tests._corpus import CORPUS_ROOT
from tests.unit.orderflow.indicators.reference import reference

GOLDEN: Final = CORPUS_ROOT.parent / "golden" / "indicators"
INPUT_SETS: Final = ("kline_gap", "tape_1m", "synthetic_day")
#: Klines carry no aggressor split, so the delta-based cases (`cvd`, `delta`) skip that set.
HAS_DELTA: Final = {"kline_gap": False, "tape_1m": True, "synthetic_day": True}
FIELDS: Final = ("t", "open", "high", "low", "close", "volume", "delta", "synthetic")
REF_DIGITS: Final = 20
REGEN_COMMAND: Final = (
    "cd services/api && CV_REGEN_GOLDEN=1 pytest "
    "tests/unit/orderflow/indicators/test_golden_vectors.py"
)
TOLERANCE: Final = "abs(kernel - reference) <= 1e-8 * max(1, abs(reference)); None positions equal"


@dataclass(frozen=True)
class Case:
    indicator: str
    params: Mapping[str, ParamValue]
    source: str | None
    needs_delta: bool = False

    @property
    def case_id(self) -> str:
        args = ",".join(f"{k}={canonical_value(k, v)}" for k, v in sorted(self.params.items()))
        return f"{self.indicator}({args})"


CASES: Final = (
    Case("sma", {"n": 20}, "close"),
    Case("ema", {"n": 21}, "close"),
    Case("rsi", {"n": 14}, "close"),
    Case("atr", {"n": 14}, None),
    Case("adx", {"n": 14}, None),
    Case("vwap", {"anchor": "session"}, "hlc3"),
    Case("cvd", {"anchor": "session"}, None, needs_delta=True),
    Case("cvd", {"anchor": "utc_day"}, None, needs_delta=True),
    Case("volume", {}, None),
    Case("delta", {}, None, needs_delta=True),
    Case("zigzag", {"depth": 5, "deviation_pct": 0}, None),
    Case("zigzag", {"depth": 3, "deviation_pct": 0.05}, None),
)


def cases_for(name: str) -> tuple[Case, ...]:
    return tuple(c for c in CASES if HAS_DELTA[name] or not c.needs_delta)


@dataclass(frozen=True)
class InputSet:
    """One densified input series and what it covers."""

    name: str
    provenance: str
    session_anchor_utc_min: int
    bars: tuple[Bar, ...] = field(repr=False)

    def cases(self) -> tuple[Case, ...]:
        return cases_for(self.name)


@dataclass(frozen=True, slots=True)
class RowBar:
    """A golden input row as the `BarLike` the production boundary converts."""

    open_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    delta: Decimal
    synthetic: bool


def _dump_line(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _input_row(b: Bar) -> list[object]:
    values = (b.open, b.high, b.low, b.close, b.volume, b.delta)
    return [b.open_time, *(str(x) for x in values), b.synthetic]


def render_inputs(inputs: InputSet) -> str:
    rows = [_input_row(b) for b in inputs.bars]
    header = {
        "bars": len(rows),
        "fields": list(FIELDS),
        "input": inputs.name,
        "interval_ms": 60_000,
        "provenance": inputs.provenance,
        "session_anchor_utc_min": inputs.session_anchor_utc_min,
        "synthetic_bars": sum(1 for b in inputs.bars if b.synthetic),
    }
    return "\n".join([_dump_line(header), *(_dump_line(r) for r in rows)]) + "\n"


def parse_inputs(text: str) -> tuple[dict[str, object], list[BarInput]]:
    lines = text.splitlines()
    header = json.loads(lines[0])
    bars = []
    for line in lines[1:]:
        t, o, h, lo, c, v, d, synthetic = json.loads(line)
        o, h, lo, c, v, d = (Decimal(x) for x in (o, h, lo, c, v, d))
        bars.append(bar_input(RowBar(t, o, h, lo, c, v, d, synthetic)))
    return header, bars


def load_inputs(name: str) -> tuple[KernelContext, list[BarInput]]:
    header, bars = parse_inputs((GOLDEN / f"inputs_{name}.jsonl").read_text(encoding="utf-8"))
    anchor = header["session_anchor_utc_min"]
    assert isinstance(anchor, int)
    return KernelContext(anchor), bars


def kernel_text(x: float | None) -> str | None:
    return None if x is None else repr(x)


def reference_text(x: Fraction | Decimal | None) -> str | None:
    if x is None:
        return None
    with localcontext() as ctx:
        ctx.prec = REF_DIGITS
        d = Decimal(x.numerator) / Decimal(x.denominator) if isinstance(x, Fraction) else +x
    return format(d, "f")


def columns[T](rows: Sequence[tuple[T, ...]], width: int) -> list[list[T]]:
    return [[row[i] for row in rows] for i in range(width)]


def kernel_columns(
    case: Case, bars: Sequence[BarInput], ctx: KernelContext
) -> list[list[str | None]]:
    rows = compute(case.indicator, bars, case.params, source=case.source, context=ctx)
    width = len(KERNELS[case.indicator].outputs)
    return [[kernel_text(x) for x in col] for col in columns(rows, width)]


def reference_columns(
    case: Case, bars: Sequence[BarInput], ctx: KernelContext
) -> list[list[str | None]]:
    rows = reference(case.indicator, bars, dict(case.params), ctx)
    width = len(KERNELS[case.indicator].outputs)
    return [[reference_text(x) for x in col] for col in columns(rows, width)]


def render_vectors(inputs: InputSet) -> str:
    ctx = KernelContext(inputs.session_anchor_utc_min)
    bars = [bar_input(b) for b in inputs.bars]
    lines = []
    for case in inputs.cases():
        kernel = KERNELS[case.indicator]
        lines.append(
            _dump_line(
                {
                    "build_version": kernel.build_version,
                    "case": case.case_id,
                    "indicator": case.indicator,
                    "kernel": kernel_columns(case, bars, ctx),
                    "outputs": list(kernel.outputs),
                    "params": dict(case.params),
                    "reference": reference_columns(case, bars, ctx),
                    "source": case.source,
                    "warmup_bars": kernel.warmup_bars(case.params),
                }
            )
        )
    return "\n".join(lines) + "\n"


def load_vectors(name: str) -> list[dict[str, object]]:
    text = (GOLDEN / f"vectors_{name}.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


ONE_MINUTE: Final = BarSpec(kind="time", interval_ms=60_000)
FIVE_MINUTES: Final = BarSpec(kind="time", interval_ms=300_000)
#: (note, indicator, params, bar spec): every identity hashes the bar source `tape` (24 §7.4).
SPEC_HASH_CASES: Final[tuple[tuple[str, str, dict[str, ParamValue], BarSpec], ...]] = (
    ("ema(21) on 1m", "ema", {"n": 21}, ONE_MINUTE),
    ("ema(21.0): the same identity as ema(21)", "ema", {"n": 21.0}, ONE_MINUTE),
    ("ema(21) on 5m: another bar spec", "ema", {"n": 21}, FIVE_MINUTES),
    ("sma(20)", "sma", {"n": 20}, ONE_MINUTE),
    ("rsi(14)", "rsi", {"n": 14}, ONE_MINUTE),
    ("atr(14)", "atr", {"n": 14}, ONE_MINUTE),
    ("adx(14)", "adx", {"n": 14}, ONE_MINUTE),
    ("vwap(session)", "vwap", {"anchor": "session"}, ONE_MINUTE),
    ("cvd(session)", "cvd", {"anchor": "session"}, ONE_MINUTE),
    ("cvd(utc_day)", "cvd", {"anchor": "utc_day"}, ONE_MINUTE),
    ("volume: no params", "volume", {}, ONE_MINUTE),
    ("delta: no params", "delta", {}, ONE_MINUTE),
    ("zigzag(5, 0)", "zigzag", {"depth": 5, "deviation_pct": 0}, ONE_MINUTE),
    ("zigzag, keys in another order", "zigzag", {"deviation_pct": 0, "depth": 5}, ONE_MINUTE),
    ("zigzag(5, 0.1)", "zigzag", {"depth": 5, "deviation_pct": 0.1}, ONE_MINUTE),
    ("zigzag(5, 1e-7): no exponent", "zigzag", {"depth": 5, "deviation_pct": 1e-07}, ONE_MINUTE),
    ("zigzag(5, -0.0): -0 is 0", "zigzag", {"depth": 5, "deviation_pct": -0.0}, ONE_MINUTE),
    ("bollinger(20, 2.5): client_worker", "bollinger", {"n": 20, "mult": 2.5}, ONE_MINUTE),
)  # fmt: skip


def render_spec_hash_vectors() -> str:
    vectors = []
    for note, indicator, params, spec in SPEC_HASH_CASES:
        bar_spec_hash = spec.spec_hash
        vectors.append(
            {
                "bar_spec_hash": bar_spec_hash,
                "canonical_json": canonical_json(indicator, params, bar_spec_hash=bar_spec_hash),
                "indicator": indicator,
                "note": note,
                "params": params,
                "spec_hash": compute_spec_hash(indicator, params, bar_spec_hash=bar_spec_hash),
            }
        )
    doc = {
        "$note": f"GENERATED - do not hand-edit. Regenerate with `{REGEN_COMMAND}`. A diff here "
        "moves every indicator instance, cache and metric key: bump INDICATOR_SPEC_VERSION.",
        "indicator_spec_version": INDICATOR_SPEC_VERSION,
        "source": BAR_SOURCE,
        "vectors": vectors,
    }
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def render_manifest(files: Mapping[str, str], inputs: Sequence[InputSet]) -> str:
    doc = {
        "$note": "GENERATED - do not hand-edit. A kernel diff means its operation order changed: "
        "bump that kernel's build_version and regenerate.",
        "build_versions": {name: k.build_version for name, k in sorted(KERNELS.items())},
        "files": {
            name: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for name, text in sorted(files.items())
        },
        "indicator_spec_version": INDICATOR_SPEC_VERSION,
        "inputs": {i.name: i.provenance for i in inputs},
        "kernel_values": "binary64 shortest round-trip strings (Python repr); compare after "
        "parsing to binary64, bit for bit, -0 distinct from 0",
        "reference_values": f"exact reference (tests/unit/orderflow/indicators/reference.py) "
        f"rounded to {REF_DIGITS} significant digits",
        "regenerate": REGEN_COMMAND,
        "state_version": STATE_VERSION,
        "tolerance": TOLERANCE,
    }
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


SYNTHETIC_SEED: Final = 20261019
SYNTHETIC_SPEC: Final = BarSpec(kind="time", interval_ms=60_000, session_anchor_utc_min=480)
SYNTHETIC_START_US: Final = int(datetime(2026, 10, 5, 12, tzinfo=UTC).timestamp()) * 1_000_000
SYNTHETIC_GAPS: Final = ((300, 1), (700, 7), (1000, 30))
SYNTHETIC_FLAT_RUNS: Final = ((0, 20), (500, 40))
SYNTHETIC_ZERO_VOLUME: Final = (150, 151, 820, 1300)
SYNTHETIC_OUTSIDE_BAR: Final = 900
_TICK = Decimal("0.1")
_LOT = Decimal("0.001")


def _draw(slot: int, name: str, lo: int, hi: int) -> int:
    """A deterministic integer in `[lo, hi]`: sha256-based, so the day never depends on the
    `random` module's stream."""
    digest = hashlib.sha256(f"{SYNTHETIC_SEED}:{slot}:{name}".encode()).digest()
    return lo + int.from_bytes(digest[:8], "big") % (hi - lo + 1)


def synthetic_day() -> list[Bar]:
    """A seeded 1m day from 12:00 UTC (crossing 00:00 UTC and the 08:00 session anchor) with
    flat runs, zero-volume bars, an outside bar and three gaps; offline and deterministic."""
    flat = {i for start, length in SYNTHETIC_FLAT_RUNS for i in range(start, start + length)}
    gaps = {i for start, length in SYNTHETIC_GAPS for i in range(start, start + length)}
    bars: list[Bar] = []
    close = Decimal("60000.0")
    gap_before = False
    for slot in range(1440):
        o = close
        if slot in flat or slot in SYNTHETIC_ZERO_VOLUME:
            c = h = lo = o
        else:
            c = o + _draw(slot, "move", -300, 300) * _TICK
            spread = 600 if slot == SYNTHETIC_OUTSIDE_BAR else 80
            h = max(o, c) + _draw(slot, "up", 0, spread) * _TICK
            lo = min(o, c) - _draw(slot, "down", 0, spread) * _TICK
        if slot in SYNTHETIC_ZERO_VOLUME:
            buy = sell = Decimal(0)
        else:
            buy = _draw(slot, "buy", 0, 40_000) * _LOT
            sell = _draw(slot, "sell", 0, 40_000) * _LOT
        close = c
        if slot in gaps:
            gap_before = True
            continue
        t = SYNTHETIC_START_US + slot * 60_000_000
        bars.append(_bar(SYNTHETIC_SPEC, len(bars), t, (o, h, lo, c), (buy, sell), gap_before))
        gap_before = False
    return list(BarSeries(SYNTHETIC_SPEC, bars).densify())


def _bar(
    spec: BarSpec,
    index: int,
    open_time: int,
    ohlc: tuple[Decimal, Decimal, Decimal, Decimal],
    sides: tuple[Decimal, Decimal],
    gap_before: bool,
) -> Bar:
    """A closed 1m bar; `sides` are the aggressor buy and sell volumes."""
    o, h, lo, c = ohlc
    buy, sell = sides
    return Bar(
        spec_hash=spec.spec_hash,
        symbol="BTCUSDT",
        index=index,
        open_time=open_time,
        close_time=open_time + 60_000_000,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=buy + sell,
        buy_volume=buy,
        sell_volume=sell,
        delta=buy - sell,
        min_delta=min(Decimal(0), buy - sell),
        max_delta=max(Decimal(0), buy - sell),
        trade_count=0 if buy + sell == 0 else 1 + index % 7,
        turnover=(buy + sell) * c,
        vwap=c,
        closed=True,
        partial=False,
        gap_before=gap_before,
    )


def kline_bars(
    rows: Sequence[tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal]],
    punch: range,
) -> list[Bar]:
    """1m bars from `(open_time, o, h, l, c, volume)` rows (no aggressor split: delta 0), with
    the bars at positions `punch` removed and refilled by `densify()`."""
    bars: list[Bar] = []
    for pos, (t, o, h, lo, c, v) in enumerate(rows):
        if pos in punch:
            continue
        bar = _bar(ONE_MINUTE, len(bars), t, (o, h, lo, c), (v / 2, v / 2), pos == punch.stop)
        bars.append(bar.model_copy(update={"volume": v, "delta": Decimal(0)}))
    return list(BarSeries(ONE_MINUTE, bars).densify())
