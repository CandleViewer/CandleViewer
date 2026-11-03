#!/usr/bin/env python3
"""E47-Q05: motion/flash audit decisions (WCAG 2.3.1) on top of the G005 counter.

The Playwright collector (apps/web/e2e/a11y/motion-audit.collect.ts) captures the frames of each
DECLARED region and reduces them to one relative-luminance sample per frame, with the shared
tools/contrast/color-math.mjs implementation. Every decision lives here, unit-testable without a
browser. Frames are never written to a report: only the measured rate per region (the ticket's
"record the measured rate, not merely a pass verdict" and its security note on captures).

Two checks:
  flash   per-region flashes/s against the surface budget (E47-D08 FR-3 / FR-6: at most 2 per 1 s
          window; the G005 limit of 3 stays the hard gate). A surface that is not built is a
          `pending <ticket>` row (motion-exception register) and becomes required the day its
          status is flipped to "built" here.
  reduce  reduced motion removes WORK, not only visuals: no running animation, and script, paint and
          rAF work below a fraction of the motion-safe run. An opacity-only mutation must fail.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from tools.a11y.gates import (
    EXIT_INFRA,
    EXIT_OK,
    EXIT_VIOLATION,
    MAX_FLASHES_PER_SECOND,
    InfraError,
    _load,
    count_flashes,
)

# D08 FR-2: the flashing region is a sliding 341 x 256 CSS px rectangle (10 degrees of the field).
DEFAULT_REGION = (341, 256)
# D08 FR-3 (combined starts in one region per 1 s window) and FR-6 (heatmap cell crossings).
REGION_BUDGET = 2
# PROPOSED (BQ-05): reduced-motion work must be below this fraction of the motion-safe run. The
# figure is a placeholder until the three-run variance derivation is committed with its runs; it is
# not accepted until QA signs the derivation.
REDUCE_WORK_FRACTION = 0.5
_WORK_KEYS = ("script_ms", "paint_ms", "raf_callbacks")


@dataclass(frozen=True)
class Surface:
    id: str
    scr: str
    budget: int
    status: str  # "built" (a capture is required) | "pending" | "fixture"
    ref: str  # pending ticket, register row or the fixture's expected verdict


SURFACES: tuple[Surface, ...] = (
    Surface("heatmap-live-cell", "SCR-050", REGION_BUDGET, "pending", "E21-S01 #648 (FR-6)"),
    Surface("price-flash-ladder", "SCR-050", REGION_BUDGET, "pending", "E08-S08 #4702 (MX-10)"),
    Surface(
        "big-trade-bubbles", "SCR-053", REGION_BUDGET, "pending", "E22-S01 #714 (MX-12, MX-14)"
    ),
    Surface("price-flash-positions", "SCR-063", REGION_BUDGET, "pending", "#5440"),
    Surface("alert-toast", "SCR-092", REGION_BUDGET, "pending", "E40-S02 #1130"),
    Surface("connection-banner", "SCR-152", REGION_BUDGET, "pending", "E29-S07 #1028"),
    # Known-bad / known-good synthetic components: the analyser's own validation (ticket test plan).
    Surface("synthetic-6hz", "-", REGION_BUDGET, "fixture", "FAIL"),
    Surface("synthetic-1hz", "-", REGION_BUDGET, "fixture", "pass"),
)
_BY_ID = {s.id: s for s in SURFACES}


def synthetic_luminance(hz: float, fps: int = 60, seconds: int = 5) -> list[float]:
    """Seeded-free square wave: `hz` full black/white cycles per second, one sample per frame."""
    half = fps / hz / 2
    return [1.0 if int(i // half) % 2 else 0.0 for i in range(fps * seconds)]


def _region(name: str, region: dict, viewport: object) -> None:
    rect = region.get("rect")
    if not (isinstance(rect, list) and len(rect) == 4 and rect[2] > 0 and rect[3] > 0):
        raise InfraError(f"A11Y-INFRA region {name} has no declared rect [x, y, w, h]")
    vw, vh = viewport if isinstance(viewport, list) and len(viewport) == 2 else (None, None)
    if vw is not None and rect[2] >= vw and rect[3] >= vh:
        # Whole-viewport averaging is how a flash is averaged away on a mostly static screen.
        raise InfraError(f"A11Y-INFRA region {name} spans the whole viewport")
    if not region.get("luminance"):
        raise InfraError(f"A11Y-INFRA region {name} has no luminance samples")


def audit(capture: dict) -> tuple[list[dict], list[str]]:
    """Return (rows, violations). A row always carries the measured rate when one exists."""
    fps = float(capture.get("fps") or 0)
    regions = capture.get("regions")
    if fps <= 0 or not isinstance(regions, dict) or not regions:
        raise InfraError("A11Y-INFRA motion capture is empty")
    unknown = sorted(set(regions) - set(_BY_ID))
    if unknown:
        raise InfraError(f"A11Y-INFRA region {unknown[0]} is not a registered surface")
    rows: list[dict] = []
    violations: list[str] = []
    for s in SURFACES:
        region = regions.get(s.id)
        if region is None:
            if s.status == "built":
                raise InfraError(f"A11Y-INFRA built surface {s.id} ({s.scr}) was not captured")
            rows.append(_row(s, None, f"pending {s.ref}" if s.status == "pending" else "absent"))
            continue
        _region(s.id, region, capture.get("viewport"))
        rate = count_flashes(region["luminance"], fps)
        over = rate > s.budget or rate >= MAX_FLASHES_PER_SECOND
        verdict = "FAIL" if over else "pass"
        if s.status == "fixture":
            if verdict != s.ref:  # the analyser is broken, not the product
                raise InfraError(f"A11Y-INFRA fixture {s.id} read {verdict}, expected {s.ref}")
            verdict = f"{verdict} (fixture)"
        elif over:
            violations.append(
                f"A11Y-Q05 surface={s.id} {s.scr} {rate} flashes/s (budget <= {s.budget}, "
                f"G005 limit < {MAX_FLASHES_PER_SECOND})"
            )
        rows.append(_row(s, rate, verdict))
    return rows, violations


def _row(s: Surface, rate: int | None, verdict: str) -> dict:
    return {"surface": s.id, "scr": s.scr, "measured": rate, "budget": s.budget, "result": verdict}


def table(rows: list[dict]) -> str:
    out = ["| surface | SCR | measured flashes/s | budget | result |", "|---|---|---|---|---|"]
    for r in rows:
        m = "-" if r["measured"] is None else r["measured"]
        out.append(f"| {r['surface']} | {r['scr']} | {m} | <= {r['budget']} | {r['result']} |")
    return "\n".join(out)


def check_reduced_work(
    safe: dict, reduced: dict, fraction: float = REDUCE_WORK_FRACTION
) -> list[str]:
    """Profiles: {"running_animations": n, "script_ms": x, "paint_ms": x, "raf_callbacks": n}."""
    if not safe.get("running_animations") or not all(safe.get(k) for k in _WORK_KEYS):
        # A motion-safe run with no animation would let any reduced run pass vacuously.
        raise InfraError("A11Y-INFRA motion-safe profile shows no animation work")
    msgs = []
    if reduced.get("running_animations", 0) != 0:
        msgs.append(
            f"A11Y-Q05 reduced run still has {reduced['running_animations']} running animations"
        )
    for k in _WORK_KEYS:
        got, base = float(reduced.get(k, 0)), float(safe[k])
        if got > base * fraction:
            msgs.append(f"A11Y-Q05 reduced {k} {got:g} > {fraction:g} x motion-safe {base:g}")
    return msgs


def _emit(msgs: list[str]) -> int:
    print("\n".join(msgs) if msgs else "motion audit: pass")
    return EXIT_VIOLATION if msgs else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("flash").add_argument("capture")
    sub.add_parser("reduce").add_argument("profiles")
    args = p.parse_args(argv)
    try:
        if args.cmd == "flash":
            rows, msgs = audit(_load(args.capture))
            print(table(rows))
            return _emit(msgs)
        prof = _load(args.profiles)
        return _emit(check_reduced_work(prof.get("safe", {}), prof.get("reduced", {})))
    except InfraError as exc:
        print(exc, file=sys.stderr)
        return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(main())
