"""Golden vectors for the server indicator kernels (E13-T02 AC "Values match a reference
implementation"; plan §3.9, D6, D7).

Inputs, in `packages/fixtures/golden/indicators/` (no recorded symbol-day exists yet, exception
#1778 A; E13-Q05 swaps one in when E16 records it):

- `kline_gap`: the 450 recorded BTCUSDT 1m klines of `bybit/2026-10-05/rest/`, read by the
  production page parser, with bars 200-214 removed and refilled by `densify()` (ADR-0034's
  parity window). Klines carry no aggressor split, so delta-based cases skip this set.
- `tape_1m`: the 180 tape-built 1m bars of `golden/bars/time_bars_BTCUSDT.jsonl` (E12-S01).
- `synthetic_day`: the seeded day of `_golden.synthetic_day()` (gaps, zero volume, flat runs).

Checks: every server kernel matches the exact reference within
`1e-8 * max(1, |reference|)` with identical `None` positions; its float64 outputs are
bit-identical to the stored strings the TS mirror is held to; the reference reproduces its
stored values; the manifest pins every file and kernel `build_version`. Set
`CV_REGEN_GOLDEN=1` to rewrite the files, then review the diff.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from decimal import Decimal, localcontext

import pytest

from candleviewer.bars.models import Bar
from candleviewer.exchange.base.models import KlineEvent
from candleviewer.exchange.bybit.klines import parse_kline_page
from candleviewer.orderflow.indicators import KERNELS
from tests._corpus import rest
from tests.unit.orderflow.indicators._golden import (
    GOLDEN,
    HAS_DELTA,
    INPUT_SETS,
    Case,
    InputSet,
    cases_for,
    kernel_columns,
    kline_bars,
    load_inputs,
    load_vectors,
    render_inputs,
    render_manifest,
    render_spec_hash_vectors,
    render_vectors,
    synthetic_day,
)

REGEN = os.environ.get("CV_REGEN_GOLDEN") == "1"
KLINE_PAGES = tuple(f"rest/kline_BTCUSDT_1_page{k}.json" for k in range(3))
KLINE_NOW_MS = 1_800_000_000_000  # every recorded kline is confirmed by then
PUNCH = range(200, 215)
TICK = Decimal("0.1")
TAPE_GOLDEN = GOLDEN.parent / "bars" / "time_bars_BTCUSDT.jsonl"
PROVENANCE = {
    "kline_gap": "packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page{0,1,2}.json: 450 "
    "BTCUSDT 1m klines (public market data, documented-shape capture, exception #1778 A), read "
    "by the production page parser; bars 200-214 removed and refilled by BarSeries.densify() "
    "(15 synthetic bars). No aggressor split: delta is 0.",
    "tape_1m": "packages/fixtures/golden/bars/time_bars_BTCUSDT.jsonl, spec 1m: 180 tape-built "
    "BTCUSDT bars with aggressor delta (E12-S01 golden; no gap).",
    "synthetic_day": "tests/unit/orderflow/indicators/_golden.py synthetic_day(), seed 20261019: "
    "1,440 1m slots from 2026-10-05T12:00Z, session anchor 08:00 UTC, gaps of 1, 7 and 30 bars "
    "refilled by densify(), zero-volume bars, flat runs, an outside bar.",
}
PAIRS = [(name, case) for name in INPUT_SETS for case in cases_for(name)]
PAIR_IDS = [f"{case.case_id}@{name}" for name, case in PAIRS]


def _kline_input() -> list[Bar]:
    events: dict[int, KlineEvent] = {}
    for page in KLINE_PAGES:
        parsed = parse_kline_page(
            rest(page), symbol="BTCUSDT", interval="1", tick_size=TICK, now_ms=KLINE_NOW_MS
        )
        events |= {e.start: e for e in parsed}
    rows = [(e.start, e.open, e.high, e.low, e.close, e.volume) for _, e in sorted(events.items())]
    return kline_bars(rows, PUNCH)


def _tape_input() -> list[Bar]:
    out = []
    for line in TAPE_GOLDEN.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.pop("spec") == "1m":
            out.append(Bar.model_validate(row))
    return out


def _derive() -> dict[str, InputSet]:
    bars = {"kline_gap": _kline_input(), "tape_1m": _tape_input(), "synthetic_day": synthetic_day()}
    anchors = {"kline_gap": 0, "tape_1m": 0, "synthetic_day": 480}
    return {
        name: InputSet(name, PROVENANCE[name], anchors[name], tuple(bars[name]))
        for name in INPUT_SETS
    }


@pytest.fixture(scope="module")
def derived() -> dict[str, InputSet]:
    return _derive()


@pytest.fixture(scope="module", autouse=True)
def _regenerate(derived: dict[str, InputSet]) -> Iterator[None]:
    if REGEN:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        files = {f"inputs_{n}.jsonl": render_inputs(i) for n, i in derived.items()}
        files |= {f"vectors_{n}.jsonl": render_vectors(i) for n, i in derived.items()}
        files["spec_hash_vectors.json"] = render_spec_hash_vectors()
        for name, text in files.items():
            (GOLDEN / name).write_text(text, encoding="utf-8", newline="\n")
        manifest = render_manifest(files, list(derived.values()))
        (GOLDEN / "manifest.json").write_text(manifest, encoding="utf-8", newline="\n")
    yield


def _vector(name: str, case: Case) -> dict[str, object]:
    found = [v for v in load_vectors(name) if v["case"] == case.case_id]
    assert len(found) == 1, f"{case.case_id} is not in vectors_{name}.jsonl exactly once"
    return found[0]


def _within(kernel: str | None, ref: str | None) -> bool:
    if kernel is None or ref is None:
        return kernel is None and ref is None
    with localcontext() as ctx:
        ctx.prec = 60
        k, r = Decimal(float(kernel)), Decimal(ref)
        return abs(k - r) <= Decimal("1e-8") * max(Decimal(1), abs(r))


@pytest.mark.parametrize("name", INPUT_SETS)
def test_golden_inputs_match_their_sources(name: str, derived: dict[str, InputSet]) -> None:
    stored = (GOLDEN / f"inputs_{name}.jsonl").read_text(encoding="utf-8")
    assert stored == render_inputs(derived[name])


def test_golden_inputs_hold_the_documented_shape(derived: dict[str, InputSet]) -> None:
    kline, tape = derived["kline_gap"].bars, derived["tape_1m"].bars
    day = derived["synthetic_day"].bars
    assert (len(kline), sum(b.synthetic for b in kline)) == (450, 15)
    assert [b.synthetic for b in kline[200:215]] == [True] * 15
    assert (len(tape), sum(b.synthetic for b in tape)) == (180, 0)
    assert (len(day), sum(b.synthetic for b in day)) == (1440, 38)
    assert sum(1 for b in day if not b.synthetic and b.volume == 0) == 4


@pytest.mark.parametrize(("name", "case"), PAIRS, ids=PAIR_IDS)
def test_indicator_matches_reference_to_1e8(name: str, case: Case) -> None:
    ctx, bars = load_inputs(name)
    vector = _vector(name, case)
    live = kernel_columns(case, bars, ctx)
    stored_ref = vector["reference"]
    assert isinstance(stored_ref, list)
    outputs = KERNELS[case.indicator].outputs
    for out, got, want in zip(outputs, live, stored_ref, strict=True):
        bad = [i for i, (k, r) in enumerate(zip(got, want, strict=True)) if not _within(k, r)]
        assert not bad, f"{case.case_id}.{out} differs from the reference at bars {bad[:5]}"


@pytest.mark.parametrize(("name", "case"), PAIRS, ids=PAIR_IDS)
def test_kernel_outputs_are_bit_exact_with_golden(name: str, case: Case) -> None:
    ctx, bars = load_inputs(name)
    vector = _vector(name, case)
    assert kernel_columns(case, bars, ctx) == vector["kernel"]
    assert vector["build_version"] == KERNELS[case.indicator].build_version
    assert vector["warmup_bars"] == KERNELS[case.indicator].warmup_bars(case.params)


@pytest.mark.parametrize("name", INPUT_SETS)
def test_vectors_file_matches_a_fresh_render(name: str, derived: dict[str, InputSet]) -> None:
    """Byte for byte: the reference reproduces its stored values, and no case is missing,
    extra or reordered."""
    stored = (GOLDEN / f"vectors_{name}.jsonl").read_text(encoding="utf-8")
    assert stored == render_vectors(derived[name])


def test_every_server_kernel_has_golden_vectors_on_every_input() -> None:
    for name in INPUT_SETS:
        covered = {v["indicator"] for v in load_vectors(name)}
        assert covered == set(KERNELS) - (set() if HAS_DELTA[name] else {"cvd", "delta"})


def test_manifest_pins_every_file_and_build_version(derived: dict[str, InputSet]) -> None:
    names = [f"{kind}_{n}.jsonl" for kind in ("inputs", "vectors") for n in INPUT_SETS]
    files = {
        n: (GOLDEN / n).read_text(encoding="utf-8") for n in [*names, "spec_hash_vectors.json"]
    }
    expected = render_manifest(files, list(derived.values()))
    assert (GOLDEN / "manifest.json").read_text(encoding="utf-8") == expected
