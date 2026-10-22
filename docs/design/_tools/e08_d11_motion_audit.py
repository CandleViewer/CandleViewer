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

The flap replay follows section 3 as folded after the lens rounds: the title swaps at 0 ms on the
first change, then at most once per second and, once a tier trips, latches on "Connection
unstable" until the stable window completes; the glyph, the CMP-076 chip and the panel header's
words take those slots and latch with the title (the header in its own wording, with a cut where
the title reads "Reconnected"), never the transport; the banner fill is debounced on the clearing
side; the panel scrim appears once per episode and cuts in the frame the fresh snapshot applies (a
tradable book is never dimmed; the 15 % hold is reported for the C-row to E11-D06); `role="alert"`
fires on every Disconnected entry that follows an announced recovery, until the slow-flap tier (3
entries in 60 s) collapses further entries into one polite "Connection unstable" and lengthens the
stable window to 30 s. The stale chip and dim clear after a window of continuous freshness (the
quiet-symbol scenario shows why).

Usage: python3 -I docs/design/_tools/e08_d11_motion_audit.py          (Markdown; exit 1 on a FAIL)
       python3 -I docs/design/_tools/e08_d11_motion_audit.py --json   (the boards' numbers)

Gated rows are the composites this spec introduces (dimmed text and glyphs, the scrim label, the
stale panel dim's text); the banner pairs E08-D03 already bound are reported, never gated here.
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
UNSTABLE_ENTRIES, UNSTABLE_WINDOW_S = 3, 60.0  # the slow-flap tier: Disconnected entries per window
UNSTABLE_STABLE_S = 30.0  # the stable window once the slow-flap tier has tripped
DEGRADED_CLEAR_S = 5.0  # the focused symbol's topics fresh for this long before `degraded` clears
STALE_HOLD_S = 5.0  # the stale chip and dim clear after this long of continuous freshness (T3)
DIM_ALPHA = 0.85  # stale text at 85 % over `stale.surface` (E17-D01 15 %, E11-D06 D13)
PANEL_DIM_ALPHA = 0.15  # the Stale panel dim: `stale.surface` at 15 % over the panel (E17-D01 5)
WORD_SLOT_S = 1.0  # title swaps after the first: at most one per second (D2); the glyph, the chip
# and the panel header's words take the same slots and latch (D10, D25)
EMPHASIS_ALPHA, EMPHASIS_MIN_MS, EMPHASIS_MAX_CELLS = 0.25, 500, 20
EMPHASIS_BUSY_S = 10.0  # a cell emphasising at >= 1 Hz for this long stops until it quiets (D15)
# element|width|height in CSS px (E08-D03's 1280 px boards; compact density). The title line is
# E08-D03 section 3's "Disconnected — reconnecting (attempt 3, next in 4 s)" (52 characters) in
# `type.ui.body-strong` = `font.size.base` 13 px at `font.lineheight.normal` 1.4: 52 x 13 x 0.56 em.
# The CMP-076 chip is its 20 px icon plus "Reconnecting (3)" (16 characters) at `font.size.sm`
# 12 px: 16 x 12 x 0.56 em = 108, so 128 x 20. The T2 header strip is the panel's 480 px width by a
# 24 px row (the watchlist row height).
AREAS = (
    "banner fill|1280|96;banner title line|379|19;banner icon|20|20;connection chip|128|20;"
    "stale chip|64|18;one row|1280|24;rendered rows 60|76800|24;emphasis cell|96|20;"
    "emphasis cells 20|1920|20;panel scrim|480|600;panel header|480|24;T2 header strip|480|24;"
    "progress bar|400|4"
)
# element|changes per second, worst case under the table|kind|changes in the worst 1 s window
# (a WCAG flash is a pair of opposing changes: 2 changes = 1 flash; the sustained rate is the
# second column, the 1 s window the fourth). The fill's and the scrim's worst second is a recovery
# followed by a drop 100 ms later; the emphasis's is two starts and two decays of one cell.
FLASH = (
    f"banner fill|{2 / STABLE_WINDOW_S}|luminance|2;"
    f"banner fill, unstable tier|{2 / UNSTABLE_STABLE_S}|luminance|2;"
    f"banner title and body|{1 / WORD_SLOT_S}|text|1;"
    f"banner glyph|{1 / WORD_SLOT_S}|text|1;"
    f"connection chip|{1 / WORD_SLOT_S}|text|1;"
    f"panel header words|{1 / WORD_SLOT_S}|text|1;"
    f"stale chip, book|{2 / (T1_S['book'] + STALE_HOLD_S)}|luminance|1;"
    f"watchlist row settle, ticker|{2 / (T1_S['ticker'] + STALE_HOLD_S)}|luminance|1;"
    f"stale panel dim, book|{2 / (T1_S['book'] + STALE_HOLD_S)}|luminance|1;"
    f"T2 header strip, book|{2 / (3 * T1_S['book'] + STALE_HOLD_S)}|luminance|1;"
    f"degraded banner|{2 / (T1_S['book'] + DEGRADED_CLEAR_S)}|luminance|2;"
    f"resync scrim|{2 * RESYNC_PER_MIN / 60}|luminance|2;"
    f"disconnected scrim|{2 / STABLE_WINDOW_S}|luminance|2;"
    f"value-change emphasis, per cell|{1000 / EMPHASIS_MIN_MS}|luminance|4;"
    f"backfill bar step|1.0|luminance|1;delayed chip|{1 / DELAYED_MIN_S}|luminance|1;"
    f"long-outage escalation|{1 / 300}|luminance|1"
)
ALIAS = {"dc.": "color.data-confidence.", "st.": "color.status.", "tx.": "color.text."}
# role|row|fg|bg; `dim:` = fg at 85 % over the stale surface; `scrim:` = overlay at 0.6 over raised;
# `pdim:` = the stale surface at 15 % over raised (the Stale panel dim; also the 15 % hold C-14
# proposes to E11-D06, reported under that name)
ROWS = """\
text|dimmed value text (text.primary at 85 %) on stale.surface|dim:tx.primary|dc.stale.surface
text|dimmed secondary text (stale.text at 85 %) on stale.surface|dim:dc.stale.text|dc.stale.surface
non-text|dimmed buy arrow glyph on stale.surface|dim:color.buy.default|dc.stale.surface
non-text|dimmed sell arrow glyph on stale.surface|dim:color.sell.default|dc.stale.surface
text|stale chip text (undimmed) on stale.surface|dc.stale.text|dc.stale.surface
non-text|stale indicator dot on stale.surface|dc.stale.indicator|dc.stale.surface
text|scrim label on the scrim (surface.overlay at 0.6 over surface.raised)|tx.primary|scrim:
text|stale panel text on the panel dim (stale.surface at 0.15 over surface.raised)|tx.primary|pdim:
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
WORDS = {
    "down": "Disconnected — reconnecting",
    "up": "Reconnected — reconciling",
    "unstable": "Connection unstable — last data Ns ago",
    "recovered": "Reconnected",
}
HEADER = {  # the panel header's words: the title's slots and latch (D10); "" is the cut
    "down": "Disconnected — last data Ns ago",
    "up": "Reconnected — verifying · last data Ns ago",
    "unstable": "Connection unstable — verifying · last data Ns ago",
    "recovered": "",
}
SCRIM_BLOCK = 0.6  # the scrim's one level; 0 = off (a cut in the frame the fresh snapshot applies)
QUIET_PERIOD_S, QUIET_DURATION_S = 5.5, 60.0  # the quiet symbol: one print every 5.5 s for a minute


def table(src: str, sep: str = ";") -> list[list[str]]:
    return [line.split("|") for line in src.strip().split(sep)]


def max_per_second(times: list[float]) -> int:
    return max((sum(1 for u in times if t <= u < t + 1.0) for t in times), default=0)


def flap(drops: Drops) -> dict[str, Any]:
    """Replay a drop/recover timeline against the hysteresis table (section 3, D2-D4, H1, H8)."""
    changes = sorted([(d, "down") for d, _ in drops] + [(u, "up") for _, u in drops])
    fill: list[tuple[float, str]] = []
    words: list[tuple[float, str]] = []  # title swaps: the first at 0 ms, then <= 1 per second
    header: list[tuple[float, str]] = []  # the panel header's words, in the title's slots (D10)
    scrim: list[tuple[float, float]] = []  # the panel scrim's large-area level (H8)
    ann: list[tuple[float, str]] = []
    entries: list[float] = []  # Disconnected entries (the first drop, and drops after a recovery)
    appearances, collapse, occupied, down = 0, math.inf, False, False
    unstable = latched = episode = slow = False

    def swap(t: float, kind: str) -> None:  # a pending swap takes the latest wording (latest wins)
        applied = [w for w in words if w[0] <= t]
        slot = max(t, applied[-1][0] + WORD_SLOT_S) if applied else t
        if words and words[-1][0] > t:  # the header's words ride the same slot (D10)
            words[-1] = (words[-1][0], WORDS[kind])
            header[-1] = (header[-1][0], HEADER[kind])
        else:
            words.append((slot, WORDS[kind]))
            header.append((slot, HEADER[kind]))

    for t, kind in changes:
        if occupied and t >= collapse:  # dismissed at the earliest moment: the worst case
            occupied = False
        recovered = bool(fill) and fill[-1][1] == "success"
        recent = sum(1 for c in changes if t - FLAP_WINDOW_S < c[0] <= t)
        trip = recent >= FLAP_CHANGES and not unstable  # T5: the fast tier
        if kind == "down":
            entry = not occupied or recovered
            if entry:
                entries.append(t)
                recent_entries = sum(1 for e in entries if t - UNSTABLE_WINDOW_S < e <= t)
                if recent_entries >= UNSTABLE_ENTRIES:  # the slow-flap tier: no new alert
                    slow, trip = True, not unstable
                else:
                    ann.append((t, "alert: Disconnected"))
            if not occupied:
                appearances, occupied = appearances + 1, True
            if not fill or recovered:
                fill.append((t, "danger"))
            if not episode:  # the first drop of an episode: the 0.6 scrim + block, once per episode
                scrim.append((t, SCRIM_BLOCK))
                episode = True
            down, collapse = True, math.inf
        else:
            down = False
            if scrim and scrim[-1][1] == SCRIM_BLOCK:  # the fresh snapshot: the scrim cuts to 0
                scrim.append((t, 0.0))
        if trip:
            unstable = latched = True
            swap(t, "unstable")
            ann.append((words[-1][0], "polite: Connection unstable"))  # with the title (D20)
        elif not latched:
            swap(t, kind)
        if kind == "up":
            nxt = [c for c in changes if c[0] > t]
            step = t + (UNSTABLE_STABLE_S if slow else STABLE_WINDOW_S)  # the stable window
            if not nxt or nxt[0][0] >= step:
                fill.append((step, "success"))
                ann.append((step, "assertive: Reconnected"))
                swap(step, "recovered")
                latched = unstable = episode = slow = False  # the next drop opens a new episode
                collapse = step + RECOVERED_HOLD_S  # earliest; dismissal still required
    out: dict[str, Any] = {"changes": len(changes), "appearances": appearances}
    out["suppressed"] = len(drops) - appearances
    out["fill"] = [f"{t:g} s {w}" for t, w in fill]
    out["fill_changes"], out["fill_max_per_s"] = len(fill), max_per_second([f[0] for f in fill])
    out["words"] = [f"{t:g} s {w}" for t, w in words]
    out["word_swaps"], out["text_max_per_s"] = len(words), max_per_second([w[0] for w in words])
    out["glyph_max_per_s"] = out["text_max_per_s"]  # the glyph and the chip follow the words (M1)
    out["header"] = [f"{t:g} s {w or 'cut'}" for t, w in header]  # the panel header's words (D10)
    out["header_changes"] = len(header)
    out["header_max_per_s"] = max_per_second([h[0] for h in header])
    out["transport_max_per_s"] = max_per_second([c[0] for c in changes])  # the block's rate
    out["scrim"] = [f"{t:g} s {lvl:g}" for t, lvl in scrim]
    out["scrim_changes"] = len(scrim)
    out["scrim_max_per_s"] = max_per_second([s[0] for s in scrim])
    out["announcements"] = [f"{t:g} s {w}" for t, w in sorted(ann)]
    out["alerts"] = sum(1 for _, w in ann if w.startswith("alert"))
    out["entries"] = len(entries)
    out["unstable_at_s"] = next((t for t, w in ann if w.endswith("unstable")), None)
    out["slow_tier"] = len(entries) >= UNSTABLE_ENTRIES
    out["recovery_at_s"] = next((t for t, w in fill if w == "success"), None)
    out["last_recovery_at_s"] = next((t for t, w in reversed(fill) if w == "success"), None)
    out["earliest_collapse_s"] = None if down else collapse
    out["min_visible_s"] = None if down else collapse - changes[0][0]
    return out


def quiet(period_s: float, duration_s: float, t1_s: float) -> dict[str, Any]:
    """A quiet symbol printing every `period_s` for `duration_s`: the stale chip's flips and the
    dim's settles per minute, with the first-fresh-frame exit (r2) and with the clearing window
    of continuous freshness (r3, STALE_HOLD_S); a clear that coincides with the next T1 crossing
    is no flip (the chip stays)."""
    ticks = [k * period_s for k in range(int(duration_s // period_s) + 1)]
    out: dict[str, Any] = {"period_s": period_s, "duration_s": duration_s, "t1_s": t1_s}
    for name, hold in (("first fresh frame (r2)", 0.0), ("clearing window (r3)", STALE_HOLD_S)):
        on = clears = visible = 0.0
        shown = False
        for k, tk in enumerate(ticks):
            enter = tk + t1_s
            if enter >= duration_s or period_s <= t1_s:
                break
            if not shown:
                on += 1
                shown = True
            fresh = ticks[k + 1] if k + 1 < len(ticks) else duration_s
            ready = fresh + hold  # the earliest clear
            nxt = fresh + t1_s  # the next T1 crossing
            if ready < min(nxt, duration_s):
                clears += 1
                shown = False
                visible += ready - enter
            else:
                visible += min(nxt, duration_s) - enter
        per_min = 60.0 / duration_s
        out[name] = {
            "appearances_per_min": round(on * per_min, 1),
            "clears_per_min": round(clears * per_min, 1),
            "chip_flips_per_min": round((on + clears) * per_min, 1),
            # r2 settled the dim on both sides; r3 settles on entry only (the un-dim is a cut)
            "settles_per_min": round((2 * on if hold == 0 else on) * per_min, 1),
            "visible_s_per_min": round(visible * per_min, 1),
        }
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
    raised = T[theme]["color.surface.raised"]
    if name == "scrim:":
        return cast(str, verify.over(T[theme]["color.surface.overlay"], raised, SCRIM_BLOCK))
    if name == "pdim:":
        stale = T[theme]["color.data-confidence.stale.surface"]
        return cast(str, verify.over(stale, raised, PANEL_DIM_ALPHA))
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
    "stale panel dim (stale.surface at 0.15 vs surface.raised)": ("pdim:", "color.surface.raised"),
    "scrim to the 15 % hold (C-14's proposal to E11-D06)": ("scrim:", "pdim:"),
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
    n["panel_dim_alpha"], n["word_slot_s"], n["stale_hold_s"] = (
        PANEL_DIM_ALPHA,
        WORD_SLOT_S,
        STALE_HOLD_S,
    )
    n["unstable"] = {
        "entries": UNSTABLE_ENTRIES,
        "window_s": UNSTABLE_WINDOW_S,
        "stable_s": UNSTABLE_STABLE_S,
        "cooldown_s": UNSTABLE_STABLE_S + RECOVERED_HOLD_S,
    }
    n["resync_per_min"], n["safe_area_px2"] = RESYNC_PER_MIN, SAFE_AREA_PX2
    n["emphasis"] = {"peak_alpha": EMPHASIS_ALPHA, "min_interval_ms": EMPHASIS_MIN_MS}
    n["emphasis"]["max_cells"], n["emphasis"]["rate_per_s"] = (
        EMPHASIS_MAX_CELLS,
        1000 / EMPHASIS_MIN_MS,
    )
    n["emphasis"]["busy_s"] = EMPHASIS_BUSY_S
    n["emphasis"]["delta_l"] = {th: {s: delta_l(th, s) for s in ("buy", "sell")} for th in THEMES}
    n["luminance_steps"] = {k: {th: step(th, a, b) for th in THEMES} for k, (a, b) in STEPS.items()}
    n["scenarios"] = {k: flap(v) for k, v in SCENARIOS.items()}
    n["quiet"] = quiet(QUIET_PERIOD_S, QUIET_DURATION_S, T1_S["ticker"])
    n["areas"] = {
        e: {"px2": int(w) * int(h), "small": int(w) * int(h) < SAFE_AREA_PX2}
        for e, w, h in table(AREAS)
    }
    n["flash"] = {
        e: {
            "rate_per_s": round(float(r), 3),
            "kind": k,
            "window_1s_changes": int(w1),
            "ok": k == "text" or float(r) < FLASH_PER_S,
        }
        for e, r, k, w1 in table(FLASH)
    }
    n["settle"] = {
        "frames": {
            d: {str(f): round(DUR[d] * f / 1000, 1) for f in fps} for d in ("fast", "normal")
        }
    }
    n["settle"]["first_frame_fraction_standard_normal"] = {
        str(f): round(bezier_y(STANDARD, 1000 / f / DUR["normal"]), 3) for f in fps
    }
    # restyled rows . running animations per arm; the per-row arm transitions six `td.v` cells per
    # row (1 200); the "container 200" arm keeps all 200 rows in the DOM and restyles every one (an
    # upper bound) — production renders 60 (the next arm)
    arms = {"per-row 200": (200, 1200), "container 200": (200, 1), "container 60": (60, 1)}
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
    print(f"\nThe quiet symbol (the stale chip's clearing window): {json.dumps(n['quiet'])}")
    print("\n## 2. Worst-case changes per second per element (3/s; text swaps are not flashes)\n")
    for k, v in n["flash"].items():
        verdict = "text swap" if v["kind"] == "text" else "below" if v["ok"] else "ABOVE"
        print(f"- {k}: {v['rate_per_s']} /s; worst 1 s window {v['window_1s_changes']} — {verdict}")
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
