"""E11-D06 chart-motion audit: the framerate-independence worked numbers, the cut-rule arithmetic,
the transition kinematics, the flash-rate check and the contrast of every motion state the spec
binds, all computed, never eyeballed.

Standalone, offline, stdlib only. Resolves every theme (`dark`, `light`, `high-contrast`) exactly
as `packages/ui/tokens/tests/verify_tokens.py` does (same loader, same alias resolution, same theme
layering from `themes.json`); the contrast formula is `contrast_ratio()` from
`docs/design/_tools/contrast_check.py` (imported, not re-implemented), so the numbers agree with
E11-D02's, E11-D04's, E30-D01's and E09-D03's. The motion constants are the PROPOSED values of
`docs/design/E11/E11-D06.md` section 2 (tau, the termination and fling thresholds, the cut
thresholds, the durations and easings) and change only when the owner's feel run changes them. Two
comparison arms are computed beside them, never as the proposal: the distance-based termination of
trial T2 (`abs(v) * tau < 0.5 px`, with its extra tail) and the Material 3 `emphasized-decelerate`
curve of trial T7 (the A-16 change request to E11-D05; not a token).

Usage: python3 -I docs/design/_tools/e11_d06_motion_audit.py   (Markdown; exit 1 on a FAIL)
       python3 -I docs/design/_tools/e11_d06_motion_audit.py --json   (the boards' numbers)

A PASS/FAIL verdict applies the role's bar (text 4.5:1, non-text 3:1, text in high-contrast 7:1 per
`05-accessibility-standard.md` section 5 item 6). Rows marked `decorative` carry no meaning (the
skeleton's two tones) and are reported, never gated. The one token that does not exist yet
(`CR:color.replay.border`, E11-D02 CR-4) is measured on the primitive it would alias, never on an
invented hex. The `dim85:` prefix is the stale-state 15 % dim: data-ink multiplied by 0.85, the
same formula as E11-D02's chassis audit (PR #3921, `e11_d02_chassis_audit.py` once merged), so the
two specs quote one number.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "packages" / "ui" / "tokens"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")

THEMES = ("dark", "light", "high-contrast")

# ---- PROPOSED motion constants (spec section 2; heuristic until the owner's feel run) -----------
TAU_MS = 120.0  # momentum time constant (`26` section 3.5)
V_TERM = 0.02  # px/ms, momentum termination (`26` section 3.5)
V_TERM_DIST_PX = 0.5  # px, the T2 alternative: terminate when the remainder abs(v)*tau < 0.5 px
V_TERM_ALT = V_TERM_DIST_PX / TAU_MS  # px/ms, the velocity at which the distance rule terminates
V_MIN_FLING = 0.3  # px/ms, below this a release starts no coast (D3)
VELOCITY_WINDOW_MS = 50  # the release velocity is estimated over the last 50 ms (E11-S04)
PLOT_W = 1200  # px, the reference plot width of the worked numbers
D_MAX_W = 1.5  # viewport widths, the maximum fling distance (D4)
CUT_W = 3.0  # viewport widths, the pan cut threshold (D6)
CUT_RATIO = 4.0  # the scale-ratio cut threshold (D6)
DUR = {"instant": 0, "fast": 100, "normal": 200, "slow": 400}  # motion.duration.* (tokens)
EASING = {
    "standard": (0.2, 0.0, 0.0, 1.0),
    "decelerate": (0.0, 0.0, 0.0, 1.0),
    "accelerate": (0.3, 0.0, 1.0, 1.0),
    # Not a token: Material 3 `easing-emphasized-decelerate` (material-web
    # tokens/versions/v0_192/_md-sys-motion.scss), the T7 third arm and the A-16 change request.
    "emphasized_decelerate": (0.05, 0.7, 0.1, 1.0),
}  # motion.easing.* (tokens) plus the one change-request candidate
KINEMATICS_EASINGS = ("standard", "decelerate", "emphasized_decelerate")
SHIMMER_PERIOD_MS = 1200  # D16: the skeleton loop period (`slow` 400 ms would be 2.5 Hz)
FPS = (30, 60, 144)
V0_SET = {"gentle": 1.0, "brisk": 3.0, "hard": 8.0}  # px/ms release velocities


# ---- momentum -----------------------------------------------------------------------------------
def x_inf(v0: float) -> float:
    """The analytic rest distance of an exponential coast: v0 * tau."""
    return v0 * TAU_MS


def t_stop(v0: float, v_term: float = V_TERM) -> float:
    """The instant the velocity first falls below the termination threshold."""
    return TAU_MS * math.log(v0 / v_term)


def integrate_exact(
    v0: float, dts: list[float], v_term: float = V_TERM
) -> tuple[float, int, float]:
    """Per-frame integration with the exact exponential (semigroup property): x += v*tau*(1-k),
    v *= k, k = exp(-dt/tau). Returns (x at the terminating frame, frames, v at termination)."""
    x, v = 0.0, v0
    for n, dt in enumerate(dts, start=1):
        k = math.exp(-dt / TAU_MS)
        x += v * TAU_MS * (1.0 - k)
        v *= k
        if v < v_term:
            return x, n, v
    raise RuntimeError("did not terminate")


def remainder_spike(fps: int) -> float:
    """The remainder the terminating frame applies (v*tau) divided by that frame's own step
    (v_prev*tau*(1-k)) with v = v_prev*k: k/(1-k). It is the one-frame velocity spike D2 trades for
    a rest with nothing moving after it."""
    k = math.exp(-(1000.0 / fps) / TAU_MS)
    return k / (1.0 - k)


def integrate_naive(v0: float, dts: list[float], k_fixed: float) -> tuple[float, int]:
    """The mistake the spec forbids: a per-frame multiplier tuned at 60 fps, applied per frame."""
    x, v = 0.0, v0
    for n, dt in enumerate(dts, start=1):
        x += v * dt
        v *= k_fixed
        if v < V_TERM:
            return x, n
    raise RuntimeError("did not terminate")


def frame_dts(fps: int, total_ms: float = 20000.0) -> list[float]:
    dt = 1000.0 / fps
    return [dt] * int(total_ms / dt)


def dropped_frame_dts(total_ms: float = 20000.0) -> list[float]:
    """60 fps with every third frame dropped: 16.7, 16.7, 33.3 ms repeating."""
    base = 1000.0 / 60
    out: list[float] = []
    while sum(out) < total_ms:
        out.extend([base, base, 2 * base])
    return out


# ---- transitions --------------------------------------------------------------------------------
def _bez(a: float, b: float, t: float) -> float:
    return 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t**2 * b + t**3


def ease(name: str, x: float) -> float:
    """y(x) of a CSS cubic-bezier, solved by bisection on the x-polynomial."""
    x1, y1, x2, y2 = EASING[name]
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _bez(x1, x2, mid) < x:
            lo = mid
        else:
            hi = mid
    return _bez(y1, y2, (lo + hi) / 2)


def first_frame_fraction(name: str, duration_ms: int, fps: int) -> float:
    return ease(name, min(1.0, (1000.0 / fps) / duration_ms))


def peak_px_per_frame(name: str, duration_ms: int, distance_px: float, fps: int) -> float:
    dt = 1000.0 / fps
    n = max(1, round(duration_ms / dt))
    prev, peak = 0.0, 0.0
    for i in range(1, n + 1):
        y = ease(name, min(1.0, i * dt / duration_ms))
        peak = max(peak, (y - prev) * distance_px)
        prev = y
    return peak


# ---- tokens and contrast ------------------------------------------------------------------------
def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    return contrast_check.contrast_ratio(hex_to_rgb(fg), hex_to_rgb(bg))


def resolve_theme(name: str) -> dict[str, str]:
    prim = verify.load(verify.PRIMITIVES)
    allt = dict(prim)
    allt.update(verify.merged_set(verify.THEMES[name]))
    return {
        k: verify.resolve(v["$value"], allt) for k, v in allt.items() if v.get("$type") == "color"
    }


T = {n: resolve_theme(n) for n in THEMES}

# E11-D02 CR-4: no replay token exists; the frame is measured on the primitive it would alias.
CR = {
    "CR:color.replay.border": {
        "dark": "palette.purple.400",
        "light": "palette.purple.600",
        "high-contrast": "palette.purple.400",
    },
}


def col(theme: str, token: str) -> str:
    if token.startswith("dim85:"):  # the stale 15 % dim: data-ink x 0.85 (a uniform, no extra pass)
        r, g, b = hex_to_rgb(col(theme, token[len("dim85:") :]))
        return f"#{round(r * 0.85):02X}{round(g * 0.85):02X}{round(b * 0.85):02X}"
    if token in CR:
        return T[theme][CR[token][theme]]
    return T[theme][token]


# (row, foreground token, background token, role)
ROWS: list[tuple[str, str, str, str]] = [
    (
        "live data-ink: candle up (before the dim)",
        "color.candle.up",
        "color.surface.canvas",
        "non-text",
    ),
    ("live data-ink: candle down", "color.candle.down", "color.surface.canvas", "non-text"),
    ("live data-ink: wick", "color.candle.wick", "color.surface.canvas", "non-text"),
    ("stale 15 % dim: candle up", "dim85:color.candle.up", "color.surface.canvas", "non-text"),
    ("stale 15 % dim: candle down", "dim85:color.candle.down", "color.surface.canvas", "non-text"),
    ("stale 15 % dim: wick", "dim85:color.candle.wick", "color.surface.canvas", "non-text"),
    (
        "stale 15 % dim: imbalance outline",
        "dim85:color.footprint.imbalance",
        "color.surface.canvas",
        "non-text",
    ),
    (
        "stale chip text (`Stale 7s · last 13:42:05`)",
        "color.data-confidence.stale.text",
        "color.data-confidence.stale.surface",
        "text",
    ),
    (
        "stale chip indicator dot",
        "color.data-confidence.stale.indicator",
        "color.data-confidence.stale.surface",
        "non-text",
    ),
    (
        "countdown normal text (`bar close 0:41`)",
        "color.text.secondary",
        "color.surface.raised",
        "text",
    ),
    (
        "countdown warn text (`0:08 closing`)",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
    ),
    (
        "countdown warn clock glyph",
        "color.status.warning.strong",
        "color.status.warning.subtle",
        "non-text",
    ),
    ("countdown closed / n/a text", "color.text.tertiary", "color.surface.raised", "text"),
    (
        "crosshair line on the canvas (full opacity)",
        "color.crosshair",
        "color.surface.canvas",
        "non-text",
    ),
    (
        "keyboard cursor column (focus ring) on the canvas",
        "color.focus.ring",
        "color.surface.canvas",
        "non-text",
    ),
    ("aggregation chip text", "color.text.primary", "color.surface.raised", "text"),
    (
        "reduced-detail badge glyph",
        "color.status.warning.strong",
        "color.surface.raised",
        "non-text",
    ),
    ("restoring strip text", "color.text.primary", "color.status.warning.subtle", "text"),
    (
        "restoring strip icon",
        "color.status.warning.strong",
        "color.status.warning.subtle",
        "non-text",
    ),
    ("collapsed stub word (`collapsed`)", "color.text.secondary", "color.surface.raised", "text"),
    ("env badge text (DEMO / LIVE)", "color.text.primary", "color.surface.raised", "text"),
    ("env badge border: demo", "color.env.demo", "color.surface.raised", "non-text"),
    ("env badge border: live", "color.env.live", "color.surface.raised", "non-text"),
    (
        "replay frame (CR:color.replay.border) on the canvas",
        "CR:color.replay.border",
        "color.surface.canvas",
        "non-text",
    ),
    (
        "go-to-date marker on the canvas",
        "color.action.primary.default",
        "color.surface.canvas",
        "non-text",
    ),
    ("splitter grip at rest", "color.text.tertiary", "color.surface.canvas", "non-text"),
    ("splitter grip on hover", "color.text.secondary", "color.surface.canvas", "non-text"),
    (
        "skeleton two-tone (the shimmer's two stops)",
        "color.surface.hover",
        "color.surface.raised",
        "decorative",
    ),
]


def bar_for(role: str, theme: str) -> float | None:
    if role == "decorative":
        return None
    if role == "text":
        return 7.0 if theme == "high-contrast" else 4.5
    return 3.0


# ---- report -------------------------------------------------------------------------------------
def numbers() -> dict[str, object]:
    out: dict[str, object] = {
        "tau_ms": TAU_MS,
        "v_term_px_per_ms": V_TERM,
        "v_min_fling_px_per_ms": V_MIN_FLING,
        "velocity_window_ms": VELOCITY_WINDOW_MS,
        "plot_w_px": PLOT_W,
        "d_max_w": D_MAX_W,
        "d_max_px": D_MAX_W * PLOT_W,
        "v_max_px_per_ms": D_MAX_W * PLOT_W / TAU_MS,
        "cut_w": CUT_W,
        "cut_ratio": CUT_RATIO,
        "dur_ms": DUR,
        "shimmer_period_ms": SHIMMER_PERIOD_MS,
        "shimmer_hz": round(1000 / SHIMMER_PERIOD_MS, 2),
        "shimmer_hz_if_slow_token": round(1000 / DUR["slow"], 2),
        "k60": round(math.exp(-(1000 / 60) / TAU_MS), 4),
        # D2's remainder: at most v_term * tau in the terminating frame; the T2 alternative
        # (abs(v) * tau < V_TERM_DIST_PX) terminates later and leaves under half a pixel.
        "remainder_max_px": round(V_TERM * TAU_MS, 2),
        "remainder_spike_ratio": {str(fps): round(remainder_spike(fps), 1) for fps in FPS},
        "alt_term_dist_px": V_TERM_DIST_PX,
        "alt_term_v_px_per_ms": round(V_TERM_ALT, 5),
        "alt_extra_tail_ms": round(TAU_MS * math.log(V_TERM / V_TERM_ALT), 1),
    }
    coast: dict[str, object] = {}
    k60 = math.exp(-(1000 / 60) / TAU_MS)
    for label, v0 in V0_SET.items():
        row: dict[str, object] = {
            "v0": v0,
            "x_inf_px": round(x_inf(v0), 1),
            "t_stop_ms": round(t_stop(v0), 1),
            "t_stop_alt_ms": round(t_stop(v0, V_TERM_ALT), 1),
        }
        for fps in FPS:
            x, n, _v = integrate_exact(v0, frame_dts(fps))
            xn, _ = integrate_naive(v0, frame_dts(fps), k60)
            short = round(x_inf(v0) - x, 2)
            row[f"exact_{fps}"] = {"frames": n, "x_px": round(x, 2), "short_px": short}
            row[f"naive_{fps}"] = round(xn, 1)
            xa, na, _va = integrate_exact(v0, frame_dts(fps), V_TERM_ALT)
            row[f"alt_{fps}"] = {
                "frames": na,
                "extra_frames": na - n,
                "short_px": round(x_inf(v0) - xa, 2),
            }
        xd, nd, _ = integrate_exact(v0, dropped_frame_dts())
        short_d = round(x_inf(v0) - xd, 2)
        row["exact_60_dropped"] = {"frames": nd, "x_px": round(xd, 2), "short_px": short_d}
        xad, nad, _ = integrate_exact(v0, dropped_frame_dts(), V_TERM_ALT)
        row["alt_60_dropped"] = {
            "frames": nad,
            "extra_frames": nad - nd,
            "short_px": round(x_inf(v0) - xad, 2),
        }
        coast[label] = row
    out["coast"] = coast
    bars_per_w = PLOT_W / 6
    out["cut_examples"] = {
        "bars_per_viewport_at_6px": bars_per_w,
        "jump_30000_bars_w": round(30000 / bars_per_w, 1),
        "jump_500_bars_w": round(500 / bars_per_w, 2),
        "jump_600_bars_w": round(600 / bars_per_w, 2),
        "jump_601_bars_w": round(601 / bars_per_w, 3),
        "fit_200_to_5000_ratio": 5000 / 200,
        "spacing_3_to_12_ratio": 12 / 3,
        "spacing_0p5_to_12_ratio": 12 / 0.5,
    }
    kin: dict[str, object] = {}
    for name in KINEMATICS_EASINGS:
        kin[name] = {
            "first_frame_fraction": {
                str(fps): round(first_frame_fraction(name, DUR["normal"], fps), 3) for fps in FPS
            },
            # T7 also tests the M3 curve at `slow` (400 ms); the first-frame fractions there.
            "first_frame_fraction_slow": {
                str(fps): round(first_frame_fraction(name, DUR["slow"], fps), 3) for fps in FPS
            },
            "peak_px_per_frame_60_1w_normal": round(
                peak_px_per_frame(name, DUR["normal"], PLOT_W, 60), 0
            ),
            "peak_px_per_frame_60_3w_slow": round(
                peak_px_per_frame(name, DUR["slow"], CUT_W * PLOT_W, 60), 0
            ),
            "peak_px_per_frame_60_3w_normal": round(
                peak_px_per_frame(name, DUR["normal"], CUT_W * PLOT_W, 60), 0
            ),
        }
    out["kinematics"] = kin
    out["easing_curves"] = {k: list(v) for k, v in EASING.items()}
    k1 = 1.0 - math.exp(-(1000 / 60) / TAU_MS)  # the exact model's first 60 fps frame (D1)
    out["hard_fling_first_frame_px_60"] = round(V0_SET["hard"] * TAU_MS * k1, 0)
    out["hard_fling_first_frame_px_60_linear"] = round(V0_SET["hard"] * (1000 / 60), 0)
    contrast: dict[str, dict[str, float]] = {}
    for row, fg, bg, _role in ROWS:
        contrast[row] = {th: round(ratio(col(th, fg), col(th, bg)), 2) for th in THEMES}
    out["contrast"] = contrast
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="print the numbers as JSON")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # TextIOWrapper on CPython
    n = numbers()
    if args.json:
        print(json.dumps(n, indent=2, ensure_ascii=False))
        return 0

    print("# E11-D06 motion audit\n")
    print(
        f"Constants (PROPOSED): tau {TAU_MS:.0f} ms · termination {V_TERM} px/ms · no coast below "
        f"{V_MIN_FLING} px/ms · release velocity over the last {VELOCITY_WINDOW_MS} ms · plot "
        f"{PLOT_W} px · max fling {D_MAX_W} W = {D_MAX_W * PLOT_W:.0f} px ⇒ v_max "
        f"{D_MAX_W * PLOT_W / TAU_MS:.0f} px/ms · cut at > {CUT_W:.0f} W or a scale ratio > "
        f"{CUT_RATIO:.0f} · k60 = exp(-16.67/120) = {n['k60']} · T2 alternative: terminate when "
        f"abs(v) x tau < {V_TERM_DIST_PX} px\n"
    )
    print("## 1. Momentum: exact per-frame integration vs the per-frame-multiplier mistake\n")
    print(
        "| release | v0 px/ms | x∞ = v0·τ | t_stop | 30 fps frames / short of x∞ | 60 fps | "
        "144 fps | 60 fps, every 3rd frame dropped | naive x∞ at 30 / 60 / 144 fps |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    coast = cast(dict[str, Any], n["coast"])
    for label, r in coast.items():
        e30, e60, e144, ed = r["exact_30"], r["exact_60"], r["exact_144"], r["exact_60_dropped"]
        print(
            f"| {label} | {r['v0']} | {r['x_inf_px']} px | {r['t_stop_ms']} ms | "
            f"{e30['frames']} / {e30['short_px']} px | {e60['frames']} / {e60['short_px']} px | "
            f"{e144['frames']} / {e144['short_px']} px | {ed['frames']} / {ed['short_px']} px | "
            f"{r['naive_30']} / {r['naive_60']} / {r['naive_144']} px |"
        )
    print(
        "\nReading: with the exact exponential the rest position is x∞ at every frame rate; the "
        "terminating frame stops short of it by the analytic remainder v x tau, which lies "
        "between v_term x e^(-dt/tau) x tau and v_term x tau (1.8-2.4 px here), and D2 applies "
        "that remainder in the terminating frame, so the rest position is identical. The naive "
        "multiplier lands at twice the distance at 30 fps and under half at 144 fps.\n"
    )
    spike = cast(dict[str, Any], n["remainder_spike_ratio"])
    print(
        f"Trade-off of D2 (T2): the applied remainder is at most v_term x tau = "
        f"{n['remainder_max_px']} px, i.e. {spike['30']} / {spike['60']} / {spike['144']} x the "
        f"terminating frame's own step at 30 / 60 / 144 fps — one frame of faster motion in "
        f"exchange for a rest with nothing moving after it. The distance-based alternative "
        f"terminates when abs(v) x tau < {V_TERM_DIST_PX} px (v < {n['alt_term_v_px_per_ms']} "
        f"px/ms): the remainder stays under half a pixel, for {n['alt_extra_tail_ms']} ms more of "
        f"sub-pixel tail at every release velocity (tau x ln(v_term / v_alt)):\n"
    )
    print(
        "| release | alt t_stop | extra tail | 30 fps frames (+ extra) / short of x∞ | 60 fps | "
        "144 fps | 60 fps, every 3rd frame dropped |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for label, r in coast.items():
        a30, a60, a144, ad = r["alt_30"], r["alt_60"], r["alt_144"], r["alt_60_dropped"]
        print(
            f"| {label} | {r['t_stop_alt_ms']} ms | "
            f"{round(r['t_stop_alt_ms'] - r['t_stop_ms'], 1)} ms | "
            f"{a30['frames']} (+{a30['extra_frames']}) / {a30['short_px']} px | "
            f"{a60['frames']} (+{a60['extra_frames']}) / {a60['short_px']} px | "
            f"{a144['frames']} (+{a144['extra_frames']}) / {a144['short_px']} px | "
            f"{ad['frames']} (+{ad['extra_frames']}) / {ad['short_px']} px |"
        )
    print()
    print("## 2. The cut rule, worked\n")
    ce = cast(dict[str, Any], n["cut_examples"])
    print(
        f"- {ce['bars_per_viewport_at_6px']:.0f} bars per viewport at 6 px/bar, {PLOT_W} px plot."
    )
    print(f"- A 30,000-bar jump = {ce['jump_30000_bars_w']} W ⇒ **cut** (> {CUT_W:.0f} W).")
    print(
        f"- 500 bars = {ce['jump_500_bars_w']} W ⇒ animate; 600 bars = {ce['jump_600_bars_w']} W ⇒ "
        f"animate (the bound is inclusive); 601 bars = {ce['jump_601_bars_w']} W ⇒ cut."
    )
    print(
        f"- `fit` from 200 visible to 5,000 loaded bars: ratio {ce['fit_200_to_5000_ratio']:.0f} "
        f"⇒ cut; `Ctrl+Home` 3 → 12 px/bar: ratio {ce['spacing_3_to_12_ratio']:.0f} ⇒ animate "
        f"(inclusive); from 0.5 to 12 px/bar: ratio {ce['spacing_0p5_to_12_ratio']:.0f} ⇒ cut.\n"
    )
    print("## 3. Transition kinematics (why `standard`, and why two durations)\n")
    print(
        "| easing | first-frame fraction of the travel at 30 / 60 / 144 fps (normal 200 ms) | "
        "peak px per 60 fps frame: 1 W in `normal` | 3 W in `slow` | 3 W in `normal` (rejected) |"
    )
    print("| --- | --- | --- | --- | --- |")
    kin = cast(dict[str, Any], n["kinematics"])
    for name, k in kin.items():
        ff = k["first_frame_fraction"]
        label = name if name in ("standard", "decelerate") else f"{name} (M3, not a token; A-16)"
        print(
            f"| {label} | {ff['30']} / {ff['60']} / {ff['144']} | "
            f"{k['peak_px_per_frame_60_1w_normal']:.0f} px | "
            f"{k['peak_px_per_frame_60_3w_slow']:.0f} px | "
            f"{k['peak_px_per_frame_60_3w_normal']:.0f} px |"
        )
    slow_parts = []
    for name, k in kin.items():
        fs = k["first_frame_fraction_slow"]
        slow_parts.append(f"{name} {fs['30']} / {fs['60']} / {fs['144']}")
    print(
        f"\nAt `slow` ({DUR['slow']} ms; T7 tests the M3 curve there too) the first-frame "
        f"fractions at 30 / 60 / 144 fps are: {'; '.join(slow_parts)}."
    )
    print(
        f"\nFor scale: the hardest momentum fling ({V0_SET['hard']} px/ms) moves "
        f"{n['hard_fling_first_frame_px_60']:.0f} px in its first 60 fps frame with the exact "
        f"model (the linear bound v0 x dt would be "
        f"{n['hard_fling_first_frame_px_60_linear']:.0f} px).\n"
    )
    print("## 4. Flash rate (WCAG 2.3.1, ≤ 3/s)\n")
    print(
        f"- Skeleton shimmer period {SHIMMER_PERIOD_MS} ms = {n['shimmer_hz']} Hz (a `slow` 400 ms "
        f"period would be {n['shimmer_hz_if_slow_token']} Hz, which also conforms: WCAG 2.3.1 and "
        f"A11Y-G005 gate on a luminance step of 0.1 or more at 3/s or more, and this sweep is "
        f"0.01; the 1,200 ms period is a margin choice, D16)."
    )
    print(
        "- Countdown: a 1 Hz text swap in one colour (0 luminance flashes); the warn flip is one "
        "change per bar. Stale dim: one luminance change per episode each way. Nothing loops.\n"
    )
    print("## 5. Contrast of the motion states (ratio per theme; bar per role)\n")
    print("| State colour pair | fg | bg | role | dark | light | hc | verdict |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    fails = 0
    contrast = cast(dict[str, Any], n["contrast"])
    for row, fg, bg, role in ROWS:
        vals = contrast[row]
        verdict = "reported"
        if role != "decorative":
            ok = all(vals[th] >= (bar_for(role, th) or 0) for th in THEMES)
            verdict = "PASS" if ok else "FAIL"
            fails += 0 if ok else 1
        print(
            f"| {row} | `{fg}` | `{bg}` | {role} | {vals['dark']:.2f} | {vals['light']:.2f} | "
            f"{vals['high-contrast']:.2f} | {verdict} |"
        )
    gated = sum(1 for r in ROWS if r[3] != "decorative")
    print(
        f"\nTally: {gated} gated rows, {fails} FAIL; {len(ROWS) - gated} decorative rows reported"
    )
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
