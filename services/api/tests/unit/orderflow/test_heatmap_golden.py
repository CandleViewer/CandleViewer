"""E21-T02 (#605) golden-file suite (`03-testing-strategy.md` "golden-file", the DOM heatmap): the
recorded BTCUSDT depth-200 capture (`packages/fixtures/bybit/2026-10-05`, C-13.5) through the
production `BookEngine` and `HeatmapTopic`, one delta per 100 ms, serialised column by column
(§14.5 form plus `estimated` and `samples`) and compared with the committed golden, floats to a
relative 1e-9. `CV_REGEN_GOLDEN=1` rewrites it (`packages/fixtures/golden/heatmap/README.md`)."""

from __future__ import annotations

import json
import math
import os
from typing import Any

from candleviewer.book.models import BookPhase
from candleviewer.orderflow.heatmap import COLUMN_MS, HeatmapSpec, wire_column
from tests._corpus import CORPUS_ROOT
from tests.chaos.ws._book import _recorded
from tests.unit.book._builders import delta, snap
from tests.unit.orderflow.test_heatmap import STEPS, SYM, World, _level, ring

GOLDEN = CORPUS_ROOT.parent / "golden" / "heatmap" / "columns_BTCUSDT.json"
#: Grouping 5 keeps the file small (a 512-row window of 5-tick rows) and exercises re-gridding.
SPEC = HeatmapSpec(SYM, depth=200, price_grouping=5, time_bucket_ms=COLUMN_MS)
COLUMNS = 30
REL = 1e-9


async def _columns() -> list[dict[str, Any]]:
    w = World()
    eng = await w.engine()
    w.hold(SPEC)
    first, deltas = _recorded()
    tick = STEPS[SYM][0]

    def side(levels: list[list[str]]) -> list[Any]:
        return [_level(p, q, tick) for p, q in levels]

    await eng.on_event(snap(first["u"], side(first["b"]), side(first["a"])))
    w.at(0)
    prev = first["u"]
    for k, data in enumerate(deltas[:COLUMNS], start=1):
        await eng.on_event(delta(data["u"], prev, side(data["b"]), side(data["a"])))
        prev = data["u"]
        w.at(k * COLUMN_MS)
    assert eng.phase is BookPhase.LIVE
    out = []
    for column in w.topic._symbols[SYM].specs[SPEC].ring:
        wire = wire_column(column, tick)
        out.append({**wire, "estimated": column.estimated,
                    "samples_held": column.samples})  # fmt: skip
    assert len(out) == len(ring(w, SPEC)) == COLUMNS
    return out


def _close(got: Any, want: Any, path: str = "$") -> None:
    if isinstance(want, float) or isinstance(got, float):
        assert math.isclose(got, want, rel_tol=REL, abs_tol=0.0), f"{path}: {got} != {want}"
    elif isinstance(want, dict):
        assert set(got) == set(want), f"{path}: keys {sorted(got)} != {sorted(want)}"
        for key in want:
            _close(got[key], want[key], f"{path}.{key}")
    elif isinstance(want, list):
        assert len(got) == len(want), f"{path}: {len(got)} items != {len(want)}"
        for i, (g, x) in enumerate(zip(got, want, strict=True)):
            _close(g, x, f"{path}[{i}]")
    else:
        assert got == want, f"{path}: {got!r} != {want!r}"


async def test_the_recorded_btc_columns_match_the_golden() -> None:
    columns = await _columns()
    if os.environ.get("CV_REGEN_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(columns, indent=1) + "\n", encoding="utf-8", newline="\n")
    _close(columns, json.loads(GOLDEN.read_text(encoding="utf-8")))
