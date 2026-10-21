"""E08-D11 motion audit: the hysteresis arithmetic (the flap scenarios replayed against the table),
the worst-case changes per second per element, the settle timings, the mass-transition model and
the contrast of every colour a motion state leaves on screen.

Standalone, offline, stdlib only. Themes resolve exactly as `packages/ui/tokens/tests/`
`verify_tokens.py` does (its loader, alias resolution, theme layering and `over()` for a
translucent layer); the ratio is `contrast_ratio()` from `docs/design/_tools/contrast_check.py`,
imported, so the numbers agree with E08-D03's and E11-D06's. Fixed constants are the plan's
(E17-D01 T1-T6, the `23` section 9.2
ladder, E08-D03's `recovered` hold, the `23` section 7.5 resync budget); PROPOSED ones are
`docs/design/E08/E08-D11.md` section 2's and change only when the owner's run (section 11) changes
them. The mass-transition measurements are read from `E08-D11-proto/proto-results.json` if present.

Usage: python3 -I docs/design/_tools/e08_d11_motion_audit.py          (Markdown; exit 1 on a FAIL)
       python3 -I docs/design/_tools/e08_d11_motion_audit.py --json   (the boards' numbers)

Gated rows are the composites this spec introduces (dimmed text and glyphs, the scrim label); the
banner pairs E08-D03 already bound are reported, never gated here.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"
PROTO = ROOT / "docs" / "design" / "E08" / "E08-D11-proto" / "proto-results.json"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
THEMES = ("dark", "light", "high-contrast")
# ---- fixed by the plan -------------------------------------------------------------------------
DUR = {"instant": 0, "fast": 100, "normal": 200, "slow": 400}  # motion.duration.* (ms)
STANDARD = (0.2, 0.0, 0.0, 1.0)  # motion.easing.standard
T1_S = {"book": 2.0, "ticker": 5.0, "trades": 10.0}  # E17-D01 T1 (ruled A2); T2 = 3x
LADDER_MS = (500, 1000, 2000, 5000, 10000, 30000)  # 23 section 9.2 (first attempt +-250 ms)
FLAP_WINDOW_S, FLAP_CHANGES = 5.0, 3  # E17-D01 T5, CMP-028
RECOVERED_HOLD_S = 10.0  # E08-D03 section 3 `recovered`
RESYNC_PER_MIN, DELAYED_MIN_S = 5, 5.0  # 23 section 7.5 / resyncGuard.ts; E17-D01 T3
FLASH_PER_S, SAFE_AREA_PX2 = 3, 341 * 256  # WCAG 2.3.1 threshold and small safe area
# ---- PROPOSED (spec section 2; heuristic until the owner's run) --------------------------------
STABLE_WINDOW_S = 5.0  # continuous `up` before the fill steps down and recovery is announced
DEGRADED_CLEAR_S = 5.0  # every topic fresh for this long before the `degraded` banner clears
DIM_ALPHA = 0.85  # stale text at 85 % over `stale.surface` (E17-D01 15 %, E11-D06 D13)
EMPHASIS_ALPHA, EMPHASIS_MIN_MS, EMPHASIS_MAX_CELLS = 0.25, 500, 20
AREAS = (  # element|width|height in CSS px (E08-D03's 1280 px boards; compact density)
    "banner fill|1280|96;banner icon|20|20;stale chip|64|18;one row|1280|24;"
    "rendered rows 60|76800|24;emphasis cell|96|20;emphasis cells 20|1920|20;"
    "panel scrim|480|600;progress bar|400|4"
)
FLASH = (  # element|changes per second, worst case under the table|kind
    f"banner fill|{2 / STABLE_WINDOW_S}|luminance;"
    f"banner title and body|{1000 / (LADDER_MS[0] - 250)}|text;"
    f"stale chip, book|{1 / T1_S['book']}|luminance;"
    f"watchlist row settle, ticker|{1 / T1_S['ticker']}|luminance;"
    f"degraded banner|{2 / (T1_S['book'] + DEGRADED_CLEAR_S)}|luminance;"
    f"resync scrim|{2 * RESYNC_PER_MIN / 60}|luminance;"
    f"value-change emphasis, per cell|{1000 / EMPHASIS_MIN_MS}|luminance;"
    f"backfill bar step|1.0|luminance;delayed chip|{1 / DELAYED_MIN_S}|luminance;"
    f"long-outage escalation|{1 / 300}|luminance"
)
ALIAS = {"dc.": "color.data-confidence.", "st.": "color.status.", "tx.": "color.text."}
# role|row|fg|bg; `dim:` = fg at 85 % over the stale surface; `scrim:` = overlay at 0.6 over raised
ROWS = """\
text|dimmed value text (text.primary at 85 %) on stale.surface|dim:tx.primary|dc.stale.surface
text|dimmed secondary text (stale.text at 85 %) on stale.surface|dim:dc.stale.text|dc.stale.surface
non-text|dimmed buy arrow glyph on stale.surface|dim:color.buy.default|dc.stale.surface
non-text|dimmed sell arrow glyph on stale.surface|dim:color.sell.default|dc.stale.surface
text|stale chip text (undimmed) on stale.surface|dc.stale.text|dc.stale.surface
non-text|stale indicator dot on stale.surface|dc.stale.indicator|dc.stale.surface
text|scrim label on the scrim (surface.overlay at 0.6 over surface.raised)|tx.primary|scrim:
inherited|banner title on danger.subtle|tx.primary|st.danger.subtle
inherited|banner body on danger.subtle|tx.secondary|st.danger.subtle
inherited|banner icon on danger.subtle|st.danger.strong|st.danger.subtle
inherited|degraded title on warning.subtle|tx.primary|st.warning.subtle
inherited|backfilling title on info.subtle|tx.primary|st.info.subtle
inherited|recovered title on success.subtle|tx.primary|st.success.subtle
inherited|long-outage title (text.inverse) on danger.strong|tx.inverse|st.danger.strong
inherited|Retry now label on action.primary.default|tx.on-action|color.action.primary.default
inherited|CMP-023 bar on info.subtle|color.action.primary.default|st.info.subtle"""
Drops = list[tuple[float, float]]
SCENARIOS: dict[str, Drops] = {
    "ac1 (5 drops in 10 s)": [(2.0 * k, 2.0 * k + 1.0) for k in range(5)],
    "flap 2/s for 30 s": [(0.5 * k, 0.5 * k + 0.25) for k in range(60)],
    "slow flap (every 12 s)": [(12.0 * k, 12.0 * k + 1.0) for k in range(3)],
}


def table(src: str, sep: str = ";") -> list[list[str]]:
    return [line.split("|") for line in src.strip().split(sep)]


def max_per_second(times: list[float]) -> int:
    return max((sum(1 for u in times if t <= u < t + 1.0) for t in times), default=0)


def flap(drops: Drops) -> dict[str, Any]:
    """Replay a drop/recover timeline against the hysteresis table (spec section 3, D2-D4)."""
    changes = sorted([(d, "down") for d, _ in drops] + [(u, "up") for _, u in drops])
    fill: list[tuple[float, str]] = []
    ann: list[tuple[float, str]] = []
    appearances, collapse, occupied, unstable, down = 0, math.inf, False, False, False
    for t, kind in changes:
        if occupied and t >= collapse:  # dismissed at the earliest moment: the worst case
            occupied, unstable = False, False
        if kind == "down":
            if not occupied:  # the slot was empty: an appearance, `role="alert"` once
                appearances, occupied = appearances + 1, True
                ann.append((t, "alert: Disconnected"))
            if not fill or fill[-1][1] != "danger":
                fill.append((t, "danger"))
            down, collapse = True, math.inf
        else:
            down, nxt = False, [c for c in changes if c[0] > t]
            step = t + STABLE_WINDOW_S  # the fill steps down only after a stable window
            if not nxt or nxt[0][0] >= step:
                fill.append((step, "success"))
                ann.append((step, "assertive: Reconnected"))
                collapse = step + RECOVERED_HOLD_S  # earliest; dismissal still required
        recent = [c for c in changes if t - FLAP_WINDOW_S < c[0] <= t]
        if len(recent) >= FLAP_CHANGES and not unstable:
            unstable = True
            ann.append((t, "polite: Connection unstable"))
    out: dict[str, Any] = {"changes": len(changes), "appearances": appearances}
    out["suppressed"] = len(drops) - appearances
    out["fill"] = [f"{t:g} s {w}" for t, w in fill]
    out["fill_changes"], out["fill_max_per_s"] = len(fill), max_per_second([f[0] for f in fill])
    out["text_max_per_s"] = max_per_second([c[0] for c in changes])
    out["announcements"] = [f"{t:g} s {w}" for t, w in sorted(ann)]
    out["unstable_at_s"] = next((t for t, w in ann if w.endswith("unstable")), None)
    out["recovery_at_s"] = next((t for t, w in fill if w == "success"), None)
    out["earliest_collapse_s"] = None if down else collapse
    out["min_visible_s"] = None if down else collapse - changes[0][0]
    return out


def bezier_y(curve: tuple[float, float, float, float], x: float) -> float:
    x1, y1, x2, y2 = curve
    lo, hi = 0.0, 1.0
    for _ in range(40):
        t = (lo + hi) / 2
        bx = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t**2 * x2 + t**3
        lo, hi = (t, hi) if bx < x else (lo, t)
    t = (lo + hi) / 2
    return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t**2 * y2 + t**3


def resolve_theme(name: str) -> dict[str, str]:
    allt = dict(verify.load(verify.PRIMITIVES))
    allt.update(verify.merged_set(verify.THEMES[name]))
    colours = {k: v for k, v in allt.items() if v.get("$type") == "color"}
    return {k: verify.resolve(v["$value"], allt) for k, v in colours.items()}


T = {n: resolve_theme(n) for n in THEMES}


def col(theme: str, name: str) -> str:
    for short, full in ALIAS.items():
        name = name.replace(short, full)
    if name.startswith("dim:"):
        surface = T[theme]["color.data-confidence.stale.surface"]
        return cast(str, verify.over(col(theme, name[4:]), surface, DIM_ALPHA))
    if name == "scrim:":
        return cast(
            str,
            verify.over(T[theme]["color.surface.overlay"], T[theme]["color.surface.raised"], 0.6),
        )
    return T[theme][name]


def ratio(theme: str, fg: str, bg: str) -> float:
    a, b = verify.hex_to_rgb(col(theme, fg)), verify.hex_to_rgb(col(theme, bg))
    return cast(float, contrast_check.contrast_ratio(a, b))


def bar_for(role: str, theme: str) -> float:
    return (7.0 if theme == "high-contrast" else 4.5) if role == "text" else 3.0


def delta_l(theme: str, side: str) -> float:
    lum, rgb, bg = verify.relative_luminance, verify.hex_to_rgb, T[theme]["color.surface.raised"]
    tinted = verify.over(T[theme][f"color.{side}.default"], bg, EMPHASIS_ALPHA)
    return round(float(abs(lum(rgb(tinted)) - lum(rgb(bg)))), 3)


def step(theme: str, after: str, before: str) -> float:
    """Luminance step of a large-area flip (a WCAG 2.3.1 flash needs a step of 0.1 or more)."""
    lum, rgb = verify.relative_luminance, verify.hex_to_rgb
    return round(float(abs(lum(rgb(col(theme, after))) - lum(rgb(col(theme, before))))), 3)


STEPS = {  # the large-area flips: what the fill becomes | what it was
    "banner fill (danger.subtle over surface.app)": ("st.danger.subtle", "color.surface.app"),
    "stale row (stale.surface vs surface.raised)": ("dc.stale.surface", "color.surface.raised"),
    "resync scrim (overlay at 0.6 vs surface.raised)": ("scrim:", "color.surface.raised"),
}


def numbers() -> dict[str, Any]:
    fps = (30, 60, 144)
    n: dict[str, Any] = {"dur_ms": DUR, "t1_s": T1_S, "t2_s": {k: 3 * v for k, v in T1_S.items()}}
    n["ladder_ms"], n["stable_window_s"] = list(LADDER_MS), STABLE_WINDOW_S
    n["recovered_hold_s"], n["cooldown_s"] = RECOVERED_HOLD_S, STABLE_WINDOW_S + RECOVERED_HOLD_S
    n["degraded_clear_s"], n["dim_alpha"], n["flap_window_s"] = (
        DEGRADED_CLEAR_S,
        DIM_ALPHA,
        FLAP_WINDOW_S,
    )
    n["resync_per_min"], n["safe_area_px2"] = RESYNC_PER_MIN, SAFE_AREA_PX2
    n["emphasis"] = {"peak_alpha": EMPHASIS_ALPHA, "min_interval_ms": EMPHASIS_MIN_MS}
    n["emphasis"]["max_cells"], n["emphasis"]["rate_per_s"] = (
        EMPHASIS_MAX_CELLS,
        1000 / EMPHASIS_MIN_MS,
    )
    n["emphasis"]["delta_l"] = {th: {s: delta_l(th, s) for s in ("buy", "sell")} for th in THEMES}
    n["luminance_steps"] = {k: {th: step(th, a, b) for th in THEMES} for k, (a, b) in STEPS.items()}
    n["scenarios"] = {k: flap(v) for k, v in SCENARIOS.items()}
    n["areas"] = {
        e: {"px2": int(w) * int(h), "small": int(w) * int(h) < SAFE_AREA_PX2}
        for e, w, h in table(AREAS)
    }
    n["flash"] = {
        e: {
            "rate_per_s": round(float(r), 3),
            "kind": k,
            "ok": k == "text" or float(r) < FLASH_PER_S,
        }
        for e, r, k in table(FLASH)
    }
    n["settle"] = {
        "frames": {
            d: {str(f): round(DUR[d] * f / 1000, 1) for f in fps} for d in ("fast", "normal")
        }
    }
    n["settle"]["first_frame_fraction_standard_normal"] = {
        str(f): round(bezier_y(STANDARD, 1000 / f / DUR["normal"]), 3) for f in fps
    }
    arms = {"per-row 200": (200, 200), "container 200": (60, 1), "container 60": (60, 1)}
    n["mass"] = {"arms": {k: {"restyled": a, "animations": b} for k, (a, b) in arms.items()}}
    n["mass"]["measured"] = (
        json.loads(PROTO.read_text(encoding="utf-8")) if PROTO.exists() else None
    )
    n["contrast"] = {
        row: {th: round(ratio(th, fg, bg), 2) for th in THEMES}
        for _, row, fg, bg in table(ROWS, "\n")
    }
    return n


def md(*cells: object) -> None:
    print("| " + " | ".join(str(c) for c in cells) + " |")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="print the numbers as JSON")
    n = numbers()
    if ap.parse_args(argv).json:
        print(json.dumps(n, indent=1, sort_keys=True))
        return 0
    print("# E08-D11 motion audit\n\n## 1. The flap scenarios against the hysteresis table\n")
    for k, s in n["scenarios"].items():
        print(f"- **{k}** — {json.dumps(s)}")
    print("\n## 2. Worst-case changes per second per element (3/s; text swaps are not flashes)\n")
    for k, v in n["flash"].items():
        verdict = "text swap" if v["kind"] == "text" else "below" if v["ok"] else "ABOVE"
        print(f"- {k}: {v['rate_per_s']} /s — {verdict}")
    print(f"\nSmall safe area {SAFE_AREA_PX2} px²: {json.dumps(n['areas'])}")
    print(
        f"\nEmphasis luminance step at alpha {EMPHASIS_ALPHA} (a flash is a step of 0.1 or more):"
    )
    print(json.dumps(n["emphasis"]["delta_l"]))
    print(f"\nLuminance steps of the large-area flips: {json.dumps(n['luminance_steps'])}")
    print(f"\n## 3. Settle timings\n\n{json.dumps(n['settle'])}")
    print("\n## 4. Contrast of the motion states (ratio per theme; bar per role)\n")
    md("pair", "role", "dark", "light", "hc", "verdict")
    md(*["---"] * 6)
    fails = 0
    for role, row, _, _ in table(ROWS, "\n"):
        v = n["contrast"][row]
        ok = role == "inherited" or all(v[th] >= bar_for(role, th) for th in THEMES)
        fails += 0 if ok else 1
        verdict = "reported" if role == "inherited" else "PASS" if ok else "FAIL"
        md(row, role, v["dark"], v["light"], v["high-contrast"], verdict)
    gated = sum(1 for r in table(ROWS, "\n") if r[0] != "inherited")
    print(f"\nTally: {gated} gated rows, {fails} FAIL; {len(ROWS.splitlines()) - gated} inherited")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
