"""E12-Q02 conformance bank: manifest integrity, parser safety, golden match through the live
`BarBuilderSet` fan-out (reports bars compared per pair), and the failure-message contract.

Light tapes run in the PR lane; the dense and gap tapes carry the `harness` marker (nightly,
`-m harness`). Goldens are never regenerated here (see `regen_goldens --suite conformance`).
"""

from __future__ import annotations

import gzip
import json
import os
import tomllib
from collections.abc import Callable
from decimal import Decimal
from functools import cache
from pathlib import Path

import pytest

from bench.bar_conformance import runner as cf
from bench.bar_determinism import tapes
from candleviewer.bars.models import Bar
from candleviewer.bars.rows import BUILD_VERSIONS
from candleviewer.exchange.base.models import TradeEvent

HEAVY = {n for n, d in tapes.TAPES.items() if d.heavy}
LIGHT = [n for n in tapes.TAPES if n not in HEAVY]


def _mark(name: str) -> list[pytest.MarkDecorator]:
    return [pytest.mark.harness] if name in HEAVY else []


def tape_params() -> list[object]:
    return [pytest.param(n, marks=_mark(n)) for n in tapes.TAPES]


@cache
def tape_of(name: str) -> tuple[TradeEvent, ...]:
    return tuple(tapes.read_tape(name))


@cache
def results_of(name: str) -> dict[str, list[Bar]]:
    return cf.run(list(tape_of(name)), tapes.TAPES[name].symbol)


def manifest() -> dict[str, object]:
    return tomllib.loads(cf.MANIFEST.read_text(encoding="utf-8"))


def test_manifest_pins_every_tape_and_golden() -> None:
    m = manifest()
    assert m["public_market_data_only"] is True
    assert m["build_versions"] == BUILD_VERSIONS, "BUILD_VERSIONS moved without regenerating"
    rows = {str(t["name"]): t for t in m["tape"]}  # type: ignore[attr-defined]
    assert set(rows) == set(tapes.TAPES)
    for name, row in rows.items():
        assert row["synthetic"] is True and "E16" in str(row["replace_with"])
        assert row["sha256"] == tapes.sha256_of(name), f"{name}: tape file changed"
        assert row["print_count"] == len(tape_of(name)) if name in LIGHT else True
        pairs = {g["pair"] for g in row["goldens"]}
        assert pairs == set(cf.live_cases()), name
        for g in row["goldens"]:
            ls = cf.read_golden(name, g["pair"])
            assert (len(ls), cf.digest(ls)) == (g["bars"], g["sha256"]), f"{name}/{g['pair']}"


def test_every_matrix_pair_is_accounted_for_in_the_manifest() -> None:
    rej = {str(r["pair"]): r for r in manifest()["rejected_pair"]}  # type: ignore[attr-defined]
    assert set(rej) == {"renko:atr:14", "heikin_ashi:5"}
    assert "ATR" in str(rej["renko:atr:14"]["message"])
    assert "BarSpecError" in str(rej["renko:atr:14"]["outcome"])
    assert "not shipped" in str(rej["heikin_ashi:5"]["note"])
    assert set(cf.live_cases()) | set(rej) == {c.label for c in cf.CASES}


def test_no_account_scoped_fields_in_any_tape() -> None:
    for name in tapes.TAPES:
        with gzip.open(tapes.tape_path(name), "rt") as fh:
            first = json.loads(fh.readline())
        assert set(first) == {"ts", "price", "size", "side", "trade_id"}


@pytest.mark.parametrize("name", LIGHT)
def test_light_tape_matches_every_golden_through_the_fanout(name: str) -> None:
    d, got, total = tapes.TAPES[name], results_of(name), 0
    for label, spec in cf.live_cases().items():
        actual = cf.lines(got[label])
        msg = cf.explain(spec, d.symbol, tape_of(name), cf.read_golden(name, label), actual)
        assert not msg, f"{name} {label} (build_version {BUILD_VERSIONS[spec.kind]}): {msg}"
        total += len(actual)
    assert total > 0
    print(f"{name}: compared {total} bars over {len(got)} pairs")


@pytest.mark.harness
@pytest.mark.parametrize("name", sorted(HEAVY))
def test_heavy_tape_matches_every_golden_through_the_fanout(name: str) -> None:
    d, got = tapes.TAPES[name], results_of(name)
    summary: dict[str, int] = {}
    for label, spec in cf.live_cases().items():
        actual = cf.lines(got[label])
        msg = cf.explain(spec, d.symbol, tape_of(name), cf.read_golden(name, label), actual)
        assert not msg, f"{name} {label} (build_version {BUILD_VERSIONS[spec.kind]}): {msg}"
        summary[label] = len(actual)
    out = os.environ.get("CV_CONFORMANCE_SUMMARY")
    if out:  # nightly uploads this per-run artefact
        path = Path(out)
        merged = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        merged[name] = summary  # one entry per heavy tape; later tapes must not clobber earlier
        path.write_text(json.dumps(merged, sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize(
    "blob",
    [b"", b"\x1f\x8b\x08garbage", gzip.compress(b'{"ts":1,"price":"x"}\n'), gzip.compress(b"{")],
)
def test_garbage_or_truncated_tape_raises_typed_error(blob: bytes) -> None:
    with pytest.raises(tapes.TapeFormatError):
        tapes.parse(blob + b"" if blob else b"not gzip", "BTCUSDT")


def test_truncated_gzip_raises_typed_error() -> None:
    data = tapes.tape_path("edge-ticks").read_bytes()
    with pytest.raises(tapes.TapeFormatError):
        tapes.parse(data[: len(data) // 2], "BTCUSDT")


def test_oversized_line_is_refused_without_unbounded_allocation() -> None:
    with pytest.raises(tapes.TapeFormatError):
        tapes.parse(gzip.compress(b"x" * 10_000_000 + b"\n"), "BTCUSDT")


def test_corrupted_golden_gives_a_readable_first_divergence() -> None:
    tape = tape_of("edge-ticks")
    spec = cf.live_cases()["vol:50"]
    good = cf.read_golden("edge-ticks", "vol:50")
    bad = list(good)
    row = json.loads(bad[3])
    row["high"] = "999999"
    bad[3] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    msg = cf.explain(spec, "BTCUSDT", tape, bad, good)
    assert "bar 3" in msg and "field high" in msg and "expected 999999" in msg
    assert "triggering trade #" in msg


Mutate = Callable[[], None]


def _golden_vs_reference(name: str) -> None:
    d, tape = tapes.TAPES[name], list(tape_of(name))
    for label, spec in cf.live_cases().items():
        want = [json.loads(x) for x in cf.read_golden(name, label)]
        ref = cf.reference.build(spec, d.symbol, tape, cf.TICK).bars
        assert len(want) == len(ref), f"{name}/{label}: {len(want)} golden vs {len(ref)} reference"
        for g, r in zip(want, ref, strict=True):
            row = cf.comparator.row(r)
            if spec.kind == "time" and g["index"] == str(len(ref) - 1):
                g, row = dict(g), dict(row)
                g.pop("closed"), row.pop("closed")  # reference flushes the tail; documented
            assert g == row, f"{name}/{label} bar {g['index']}: golden != independent reference"


@pytest.mark.parametrize("name", LIGHT)
def test_every_golden_matches_reference(name: str) -> None:
    _golden_vs_reference(name)


@pytest.mark.harness
@pytest.mark.parametrize("name", sorted(HEAVY))
def test_every_heavy_golden_matches_reference(name: str) -> None:
    _golden_vs_reference(name)


def _rows(name: str, label: str) -> list[dict[str, str]]:
    return [json.loads(x) for x in cf.read_golden(name, label)]


def test_thin_tape_has_empty_intervals() -> None:
    rows = _rows("ethusdt-2026-09-03-thin", "time:1")
    assert sum(r["gap_before"] == "true" for r in rows) >= 100


def test_newlist_first_bar_is_partial_and_opens_at_the_listing_minute() -> None:
    first = _rows("newlist-2026-09-04", "time:1")[0]
    assert first["partial"] == "true"
    assert int(first["open_time"]) == tapes.day_us("2026-09-04", "11:17:00")


def test_edge_ticks_keep_one_exact_boundary_hit_per_builder_kind() -> None:
    n = "edge-ticks"
    assert any(r["volume"] == "50.000" and r["closed"] == "true" for r in _rows(n, "vol:50"))
    assert any(
        Decimal(r["high"]) - Decimal(r["low"]) == Decimal("2.0") for r in _rows(n, "range:20")
    )
    ranged = _rows(n, "range:20")
    # a closing trade at exactly 2 x width (2 x 2.0) is a jump: the next bar carries gap_before
    jump = next(i for i, r in enumerate(ranged) if Decimal(r["high"]) - Decimal(r["low"]) == 4)
    assert ranged[jump]["closed"] == "true"
    assert ranged[jump + 1]["gap_before"] == "true"
    assert any(Decimal(r["high"]) - Decimal(r["low"]) == Decimal(3) for r in _rows(n, "renko:30"))
    assert any(Decimal(r["delta"]) == Decimal(500) for r in _rows(n, "delta:500"))
    assert any(r["trade_count"] == "100" for r in _rows(n, "tick:100"))
    assert any(int(r["open_time"]) % 60_000_000 == 0 for r in _rows(n, "time:1"))
