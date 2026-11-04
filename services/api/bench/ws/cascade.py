"""E24-Q03 (#773) slice 1: the seeded liquidation-cascade generator and its pure judge.

No I/O beyond an optional template file, no clock, no network: a profile and a seed give the same
prints every time, and the judge reads numbers a run measured.

The prints are synthetic, from recorded shapes, and every result says so (`SYNTHETIC_NOTE`): no
recorded cascade day exists (E24-K01, BQ 2 of the #773 plan). A print takes the price, size and side
of a template and gets a fresh timestamp. The upstream frame is Bybit's `allLiquidation.{symbol}`
push, `{"topic", "type": "snapshot", "ts", "data": [{"T", "s", "S", "v", "p"}]}`, mapped by
24 section 4, line ~371 (`T` event ms, `s` symbol, `S` the order's side, `v` qty, `p` price); 23
section 14.9 is the downstream `LiquidationBatch` and only backs the 500 ms note. Templates come
from `packages/fixtures/bybit/<capture>/ws/allLiquidation_BTCUSDT_burst.jsonl` once #5273 merges
it; until then `FALLBACK_TEMPLATES` carry the same fields with prices and sizes taken from the
recorded BTCUSDT `publicTrade` capture (2026-10-05, each a recorded price and size pair), as the
E16-Q04 generator does for a cascade.

Bybit pushes at most one `allLiquidation` frame per symbol per 500 ms (23 section 14.9 note), so a
profile's prints are grouped into `PUSH_MS` windows: 500 prints/s is about 250 per push.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from bench.ingestion.budgets import Check, Verdict, percentile

#: Every result carries it: a cascade here is never called "recorded".
FALLBACK_SOURCE: Final = "fallback"
SYNTHETIC_NOTE: Final = "synthetic, from recorded shapes (no recorded cascade exists, E24-K01)"
TOPIC: Final = "allLiquidation.{s}"
#: 23 section 14.9 note: at most one push per symbol per 500 ms.
PUSH_MS: Final = 500

#: SCR-054 Performance bullet (14-screens-catalogue): at 500 prints/s for 10 s, the panel spends
#: at most 2 ms scripting per frame and drops no frame.
SCR054_SCRIPT_MS: Final = 2.0
SCR054_DROPPED_FRAMES: Final = 0
#: E24-D04 section 13 Q-3: at most 2 cascade summaries, at most 1 emphasis start a second.
Q3_SUMMARIES: Final = 2
Q3_EMPHASIS_PER_S: Final = 1.0
#: 06 ids, restated (a test pins them to `budgets` and `profiles.json`).
B3_P95_MS: Final = 100.0  # #3 WS tick to screen, "under"
B3_P99_MS: Final = 250.0
B6_FANOUT_P95_MS: Final = 20.0  # #6 backend fan-out
B13_REST_P95_MS: Final = 150.0  # #13 REST read, "under"
B1_FRAME_P95_MS: Final = 16.6  # #1 engine frame time, reported not measured in slice 1
#: 06 section 7.4 and C-13.9: a headline moving more than 5 % against the baseline fails the gate.
REGRESSION_FRAC: Final = 0.05
ABS_FLOOR_MS: Final = 0.5
FRAME_MS: Final = 1000.0 / 60.0
#: The injected regression the self-check adds to every frame's scripting (BQ 4).
SELFCHECK_INJECT_MS: Final = 5.0

#: (side, price, size): the fields of a print template. Values from the recorded BTCUSDT
#: `publicTrade` capture 2026-10-05, in the `allLiquidation` frame's field shape.
Template = tuple[str, str, str]
FALLBACK_TEMPLATES: Final[tuple[Template, ...]] = (
    ("Buy", "63120.60", "0.131"),
    ("Sell", "63120.60", "0.242"),
    ("Buy", "63120.90", "0.049"),
    ("Buy", "63122.10", "0.087"),
)


@dataclass(frozen=True, slots=True)
class CascadeProfile:
    """`shape` is `ramp` (rate rises linearly from 0 to `rate_per_s`), `sustained` or `burst`
    (both flat at `rate_per_s`; they differ only in the numbers)."""

    name: str
    shape: str
    rate_per_s: int
    duration_s: float

    @property
    def duration_ms(self) -> int:
        return round(self.duration_s * 1000)

    @property
    def total(self) -> int:
        """Prints in the whole run, exact: the area under the rate curve, rounded down."""
        area = self.rate_per_s * self.duration_ms // 1000
        return area // 2 if self.shape == "ramp" else area


def profile(table: Mapping[str, Any], name: str) -> CascadeProfile:
    """A profile of the `cascade` section of `tests/load/ws/profiles.json`."""
    raw = table["cascade"]["profiles"][name]
    if raw["shape"] not in ("ramp", "sustained", "burst"):
        raise ValueError(f"cascade profile {name!r}: unknown shape {raw['shape']!r}")
    return CascadeProfile(name, raw["shape"], int(raw["rate_per_s"]), float(raw["duration_s"]))


def load_templates(path: Path | None = None) -> tuple[Template, ...]:
    """The templates of a recorded `allLiquidation` JSONL file, or `FALLBACK_TEMPLATES` while the
    file (#5273's `allLiquidation_BTCUSDT_burst.jsonl`) is absent."""
    if path is None or not path.is_file():
        return FALLBACK_TEMPLATES
    out: list[Template] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        for item in json.loads(line).get("data", ()):
            out.append((str(item["S"]), str(item["p"]), str(item["v"])))
    return tuple(out) or FALLBACK_TEMPLATES


def offsets_ms(prof: CascadeProfile) -> list[int]:
    """When each print happens, whole ms from the start: the inverse of the cumulative count, in
    integer arithmetic so that no float error can move a print across a window edge."""
    out: list[int] = []
    for k in range(1, prof.total + 1):
        if prof.shape == "ramp":
            out.append(math.isqrt(2 * prof.duration_ms * k * 1000 // prof.rate_per_s))
        else:
            out.append(-(-k * 1000 // prof.rate_per_s))
    return out


def frames(
    prof: CascadeProfile,
    *,
    seed: int,
    symbol: str = "BTCUSDT",
    start_ms: int = 1_700_000_000_000,
    templates: Sequence[Template] = FALLBACK_TEMPLATES,
) -> list[dict[str, Any]]:
    """The profile as upstream `allLiquidation` pushes, one per non-empty `PUSH_MS` window, the
    window's end as the frame's `ts`. Template choice is the seed's; time is the profile's."""
    if not templates:
        raise ValueError("no templates")
    rng = random.Random(seed)  # noqa: S311 - seeded, reproducible cascade; not crypto
    windows: dict[int, list[dict[str, str | int]]] = {}
    for off in offsets_ms(prof):
        w = max(0, -(-off // PUSH_MS) - 1)  # a print on a window edge closes that window
        side, price, size = templates[rng.randrange(len(templates))]
        windows.setdefault(w, []).append(
            {"T": start_ms + off, "s": symbol, "S": side, "v": size, "p": price}
        )
    return [
        {
            "topic": TOPIC.replace("{s}", symbol),
            "type": "snapshot",
            "ts": start_ms + (w + 1) * PUSH_MS,
            "data": windows[w],
        }
        for w in sorted(windows)
    ]


def notional_usd(item: Mapping[str, Any]) -> Decimal:
    return Decimal(str(item["p"])) * Decimal(str(item["v"]))


# --- the judge -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Run:
    """What one cascade run measured; a field left `None` was not measured and is named in the
    verdict's `not_judged`, never passed. `frame_script_ms` is the panel's scripting for each
    frame, `frame_gaps_ms` the gap between consecutive frames (a gap over 1.5 frames is dropped)."""

    profile: str
    frame_script_ms: Sequence[float] = ()
    frame_gaps_ms: Sequence[float] = ()
    tick_p95_ms: float | None = None
    tick_p99_ms: float | None = None
    fanout_p95_ms: float | None = None
    rest_p95_ms: float | None = None
    summaries: int | None = None
    emphasis_starts_per_s: float | None = None
    inject_ms: float = 0.0
    note: str = SYNTHETIC_NOTE
    #: `FALLBACK_SOURCE` or the template file's path: a run on the fallback says so.
    template_source: str = FALLBACK_SOURCE


def dropped_frames(gaps_ms: Sequence[float]) -> int:
    return sum(1 for g in gaps_ms if g > 1.5 * FRAME_MS)


def _line(name: str, budget: str, value: float, limit: float, unit: str, *, strict: bool) -> Check:
    ok = value < limit if strict else value <= limit
    return Check(name, budget, value, limit, unit, ok)


def evaluate(run: Run) -> tuple[Verdict, list[str]]:
    """The verdict of one run and the budgets it did not measure. `inject_ms` models the self-check
    regression: it is added to every frame's scripting before the budget reads it."""
    v = Verdict(f"cascade.{run.profile}")
    v.metrics["run"] = {"template_fallback": float(run.template_source == FALLBACK_SOURCE)}
    skipped: list[str] = []
    if run.frame_script_ms:
        script = [s + run.inject_ms for s in run.frame_script_ms]
        p95 = percentile(script, 0.95)
        v.add(_line("scr054.script_ms.p95", "SCR-054", p95, SCR054_SCRIPT_MS, "ms", strict=False))
        v.metrics["scr054"] = {"script_p95_ms": p95, "frames": float(len(script))}
    else:
        skipped.append("scr054.script_ms.p95")
    if run.frame_gaps_ms:
        n = dropped_frames(run.frame_gaps_ms)
        v.add(
            _line(
                "scr054.dropped_frames", "SCR-054", n, SCR054_DROPPED_FRAMES, "frames", strict=False
            )
        )
    else:
        skipped.append("scr054.dropped_frames")
    rows: tuple[tuple[str, str, float | None, float, str, bool], ...] = (
        ("budget3.tick_to_screen.p95", "#3", run.tick_p95_ms, B3_P95_MS, "ms", True),
        ("budget3.tick_to_screen.p99", "#3", run.tick_p99_ms, B3_P99_MS, "ms", True),
        ("budget6.fanout.p95", "#6", run.fanout_p95_ms, B6_FANOUT_P95_MS, "ms", False),
        ("budget13.rest.p95", "#13", run.rest_p95_ms, B13_REST_P95_MS, "ms", True),
        ("q3.summaries", "E24-D04 Q-3", run.summaries, float(Q3_SUMMARIES), "summaries", False),
        (
            "q3.emphasis_per_s",
            "E24-D04 Q-3",
            run.emphasis_starts_per_s,
            Q3_EMPHASIS_PER_S,
            "/s",
            False,
        ),
    )
    for name, budget, got, limit, unit, strict in rows:
        if got is None:
            skipped.append(name)
        else:
            v.add(_line(name, budget, float(got), limit, unit, strict=strict))
    skipped.append("budget1.engine_frame_p95: not measured in slice 1 (BQ 5)")
    return v, skipped


def regression(
    baseline: Mapping[str, float], current: Mapping[str, float]
) -> tuple[list[tuple[str, float, float]], list[str]]:
    """`(regressed, lost)`: headlines over the baseline by more than `REGRESSION_FRAC`, beyond the
    absolute floor that keeps a sub-millisecond wobble from failing the gate, as `(name, base,
    now)`; and baseline headlines the run did not report. A lost headline is a failed gate for
    the caller to handle, never a silent pass. No name filter is applied."""
    bad: list[tuple[str, float, float]] = []
    lost: list[str] = []
    for name, base in sorted(baseline.items()):
        now = current.get(name)
        if now is None:
            lost.append(name)
        elif now > base * (1.0 + REGRESSION_FRAC) and now - base > ABS_FLOOR_MS:
            bad.append((name, base, now))
    return bad, lost
