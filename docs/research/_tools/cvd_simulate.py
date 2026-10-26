#!/usr/bin/env python3
"""CVD (colour-vision-deficiency) simulation for CandleViewer design tokens.

Pure-stdlib (no numpy/PIL — neither is available in this environment).
Implements the Brettel et al. (1997) / Vienot dichromacy simulation for
protanopia and deuteranopia (sRGB -> linear-RGB -> LMS, projecting onto the
dichromat's "missing" plane, then back to sRGB) and the Machado, Oliveira &
Fernandes (2009) matrix for tritanopia (applied to linear RGB).
Reproducible, deterministic, no network.

Usage:
    python cvd_simulate.py > docs/research/artifacts/E05-D07/cvd_simulation.md
    python cvd_simulate.py --self-test   # exit 1 if a pinned simulation drifts

Feeds E05-T05 (automated contrast/CVD check) as the seed script per the
ticket's Technical notes.
"""
from __future__ import annotations

import math

# --- sRGB <-> linear RGB -----------------------------------------------

def srgb_to_linear(c: float) -> float:
    c = c / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    if c <= 0.0031308:
        s = c * 12.92
    else:
        s = 1.055 * (c ** (1 / 2.4)) - 0.055
    return max(0.0, min(1.0, s)) * 255.0


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


# --- linear RGB -> LMS (Hunt-Pointer-Estevez, normalised for D65) -------
RGB_TO_LMS = (
    (17.8824, 43.5161, 4.11935),
    (3.45565, 27.1554, 3.86714),
    (0.0299566, 0.184309, 1.46709),
)
LMS_TO_RGB = (
    (0.0809444479, -0.130504409, 0.116721066),
    (-0.0102485335, 0.0540193266, -0.113614708),
    (-0.000365296938, -0.00412161469, 0.693511405),
)

# Brettel/Viénot (protan, deutan); Machado 2009 (tritan, below).
# Brettel (1997) dichromat projection planes for D65, separation plane
# normals for each deficiency (values from Brettel/Vienot public tables).
PROJECTIONS = {
    # protanopia: L is missing -> project onto M,S plane
    "protanopia": (0.0, 2.02344, -2.52581, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    # deuteranopia: M is missing -> project onto L,S plane
    "deuteranopia": (1.0, 0.0, 0.0, 0.494207, 0.0, 1.24827, 0.0, 0.0, 1.0),
}


def matvec(m: tuple, v: tuple[float, float, float]) -> tuple[float, float, float]:
    flat = m if isinstance(m[0], (int, float)) else tuple(x for row in m for x in row)
    return (
        flat[0] * v[0] + flat[1] * v[1] + flat[2] * v[2],
        flat[3] * v[0] + flat[4] * v[1] + flat[5] * v[2],
        flat[6] * v[0] + flat[7] * v[1] + flat[8] * v[2],
    )


# Tritanopia: Machado, Oliveira & Fernandes 2009, "A Physiologically-based Model for Simulation of
# Color Vision Deficiency" (IEEE TVCG 15(6)), the published tritanomaly matrix at severity 1.0,
# applied to linear RGB (each row sums to 1, so white and greys are preserved).
TRITAN_MACHADO = (
    1.255528,
    -0.076749,
    -0.178779,
    -0.078411,
    0.930809,
    0.147602,
    0.004733,
    0.691367,
    0.303900,
)
LINEAR_RGB_SIMS = {"tritanopia": TRITAN_MACHADO}


def _simulate(hex_colour: str, deficiency: str, projections: dict, linear_sims: dict) -> str:
    r, g, b = hex_to_rgb(hex_colour)
    lin = (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b))
    if deficiency in linear_sims:
        lin2 = matvec(linear_sims[deficiency], lin)
    else:
        lms = matvec(RGB_TO_LMS, lin)
        proj = matvec(projections[deficiency], lms)
        lin2 = matvec(LMS_TO_RGB, proj)
    srgb2 = tuple(linear_to_srgb(c) for c in lin2)
    return rgb_to_hex(srgb2)  # type: ignore[arg-type]


def simulate(hex_colour: str, deficiency: str) -> str:
    return _simulate(hex_colour, deficiency, PROJECTIONS, LINEAR_RGB_SIMS)


# --- relative luminance / contrast ratio (WCAG) -------------------------

def relative_luminance(hex_colour: str) -> float:
    r, g, b = hex_to_rgb(hex_colour)
    rl, gl, bl = srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def contrast_ratio(h1: str, h2: str) -> float:
    l1, l2 = relative_luminance(h1), relative_luminance(h2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# --- perceptual distance (CIE76 in a simplified Lab space) --------------

def srgb_to_xyz(hex_colour: str) -> tuple[float, float, float]:
    r, g, b = hex_to_rgb(hex_colour)
    rl, gl, bl = srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)
    x = rl * 0.4124 + gl * 0.3576 + bl * 0.1805
    y = rl * 0.2126 + gl * 0.7152 + bl * 0.0722
    z = rl * 0.0193 + gl * 0.1192 + bl * 0.9505
    return x, y, z


def xyz_to_lab(xyz: tuple[float, float, float]) -> tuple[float, float, float]:
    xn, yn, zn = 0.95047, 1.0, 1.08883
    x, y, z = xyz[0] / xn, xyz[1] / yn, xyz[2] / zn

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b = 200 * (fy - fz)
    return L, a, b


def delta_e76(h1: str, h2: str) -> float:
    lab1, lab2 = xyz_to_lab(srgb_to_xyz(h1)), xyz_to_lab(srgb_to_xyz(h2))
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2)))


# --- data under test (from packages/ui/tokens/*.tokens.json) -----------

SURFACE_APP = "#0B0E11"  # color.surface.app (near-black, dark theme)

BUY_SELL_PAIRS = {
    "pair-A (current tokens: color.buy.default / color.sell.default)": {
        "buy": "#2EBD59",  # palette.green.500
        "sell": "#E5484D",  # palette.red.500
    },
    "pair-B (hc variants: color.buy.hc / color.sell.hc)": {
        "buy": "#6BD48A",  # palette.green.300
        "sell": "#F08A8A",  # palette.red.300
    },
}

HEATMAP_RAMPS = {
    "heatmap.convention.green-bid-red-ask": {
        "bid": ["#0E3D1F", "#1B7539", "#23994A", "#2EBD59", "#6BD48A"],
        "ask": ["#4E1518", "#A02C30", "#C93A3F", "#E5484D", "#F08A8A"],
    },
    # red-bid-green-ask is the same 5 ramp stops, swapped sides (owner
    # decision #10 in research/24-owner-decisions.md: convention is a
    # configurable swap, not a distinct palette).
    "heatmap.convention.red-bid-green-ask": {
        "bid": ["#4E1518", "#A02C30", "#C93A3F", "#E5484D", "#F08A8A"],
        "ask": ["#0E3D1F", "#1B7539", "#23994A", "#2EBD59", "#6BD48A"],
    },
}

DEFICIENCIES = ["deuteranopia", "protanopia", "tritanopia"]

# Minimum perceptually-just-noticeable-difference threshold (CIE76 dE),
# below which two adjacent ramp stops are flagged as "indistinguishable".
# dE < 2.3 is the classically-cited JND; we use 5.0 as a conservative
# "clearly distinguishable at a glance under stress/low-vision" floor,
# consistent with the ticket's re-tuning-flag intent.
JND_FLOOR = 5.0


def report() -> str:
    lines: list[str] = []
    lines.append("# E05-D07 — CVD simulation results (programmatic, seed script)")
    lines.append("")
    lines.append(
        "Generated by `docs/research/_tools/cvd_simulate.py` — Brettel/Viénot (protan, deutan) "
        "dichromacy projection in LMS space; Machado 2009 (tritan) in linear RGB; sRGB in/out, "
        "no external deps. Deterministic; safe for CI."
    )
    lines.append("")

    lines.append("## Buy/sell pairs — WCAG contrast (normal vision) vs `surface.app`")
    lines.append("")
    lines.append("| Pair | Buy vs surface | Sell vs surface | AA 3:1 (non-text) |")
    lines.append("|---|---|---|---|")
    for name, pair in BUY_SELL_PAIRS.items():
        cb = contrast_ratio(pair["buy"], SURFACE_APP)
        cs = contrast_ratio(pair["sell"], SURFACE_APP)
        ok = "PASS" if cb >= 3.0 and cs >= 3.0 else "FAIL"
        lines.append(f"| {name} | {cb:.2f}:1 | {cs:.2f}:1 | {ok} |")
    lines.append("")

    lines.append("## Buy/sell pairs — CVD simulated buy-vs-sell separation")
    lines.append("")
    lines.append(
        "Each pair's buy and sell swatch is simulated for all 3 dichromacies, then the "
        "CIE76 `dE` distance between simulated-buy and simulated-sell is measured. A pair "
        "stays *safe* only if dE clears the JND floor (`{:.1f}`) under every deficiency — "
        "i.e. buy and sell remain visually separable by colour alone even though colour is "
        "never the sole cue in the shipped UI (shape+text triad, `05-accessibility-standard.md` §4).".format(
            JND_FLOOR
        )
    )
    lines.append("")
    lines.append("| Pair | Deficiency | Sim. buy | Sim. sell | dE76 | Verdict |")
    lines.append("|---|---|---|---|---|---|")
    pair_verdicts: dict[str, bool] = {}
    for name, pair in BUY_SELL_PAIRS.items():
        pair_ok = True
        for d in DEFICIENCIES:
            sb, ss = simulate(pair["buy"], d), simulate(pair["sell"], d)
            de = delta_e76(sb, ss)
            ok = de >= JND_FLOOR
            pair_ok = pair_ok and ok
            lines.append(
                f"| {name} | {d} | {sb} | {ss} | {de:.1f} | {'safe' if ok else 'FLAG'} |"
            )
        pair_verdicts[name] = pair_ok
    lines.append("")

    recommended = [n for n, ok in pair_verdicts.items() if ok]
    lines.append(
        f"**Recommended CVD-safe pairs ({len(recommended)}):** "
        + (", ".join(recommended) if recommended else "NONE — re-tune required")
    )
    lines.append("")

    lines.append("## Heatmap ramps — adjacent-stop separation under simulation")
    lines.append("")
    lines.append(
        "Each ramp's 5 stops (per side) are simulated; adjacent stops (1-2, 2-3, 3-4, 4-5) "
        "are compared by dE76. A stop pair below the JND floor is flagged for re-tuning."
    )
    lines.append("")
    lines.append("| Ramp | Side | Deficiency | Stops | dE76 | Verdict |")
    lines.append("|---|---|---|---|---|---|")
    flagged: list[str] = []
    for ramp_name, sides in HEATMAP_RAMPS.items():
        for side_name, stops in sides.items():
            for d in DEFICIENCIES:
                sim_stops = [simulate(s, d) for s in stops]
                for i in range(len(sim_stops) - 1):
                    de = delta_e76(sim_stops[i], sim_stops[i + 1])
                    ok = de >= JND_FLOOR
                    label = f"{i+1}-{i+2}"
                    verdict = "ok" if ok else "FLAG re-tune"
                    lines.append(
                        f"| {ramp_name} | {side_name} | {d} | {label} | {de:.1f} | {verdict} |"
                    )
                    if not ok:
                        flagged.append(f"{ramp_name}/{side_name}/{d} stops {label}")
    lines.append("")
    lines.append(
        f"**Flagged for re-tuning ({len(flagged)}):** "
        + ("; ".join(flagged) if flagged else "none — all adjacent stops separable under all 3 deficiencies")
    )
    lines.append("")
    return "\n".join(lines)


# --- self-test -----------------------------------------------------------

# Tritan sanity pins from the published Machado matrix (same values as e12_d06 TRITAN_SANITY).
TRITAN_SANITY = {
    "#FF0000": "#FF000F",
    "#00FF00": "#00F7D9",
    "#0000FF": "#006B96",
    "#FFFF00": "#FFEED9",
}
# Known inputs, (protanopia, deuteranopia, tritanopia), as e12_d06 CVD_PINNED: protan and deutan
# come from this file's Brettel/Viénot rows, so they also prove those rows did not move.
CVD_PINNED = {
    "#2EBD59": ("#B4B458", "#A3A35D", "#00B9A6"),
    "#E5484D": ("#6B6B4E", "#8F8F44", "#FB194B"),
}
# The defective LMS row this file carried before (S = -0.395913 L + 0.801109 M; red -> #BABA00).
# Test data for the mutation proof only; `simulate` never uses it.
DEFECTIVE_TRITAN_ROW = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -0.395913, 0.801109, 0.0)


def self_test_failures(projections: dict, linear_sims: dict) -> list[str]:
    def sim(h: str, d: str) -> str:
        return _simulate(h, d, projections, linear_sims)

    fails: list[str] = []
    for src, want in TRITAN_SANITY.items():
        if sim(src, "tritanopia") != want:
            fails.append(f"tritan sanity {src}: {sim(src, 'tritanopia')} != {want}")
    for src, wants in CVD_PINNED.items():
        for d, want in zip(("protanopia", "deuteranopia", "tritanopia"), wants):
            if sim(src, d) != want:
                fails.append(f"pinned {src} {d}: {sim(src, d)} != {want}")
    for src in ("#FF0000", "#00FF00", "#2EBD59", "#E5484D"):  # reds and greens
        out = sim(src, "tritanopia")
        if out[1:3] == out[3:5]:
            fails.append(f"R = G guard {src}: tritan {out} has R == G")
    for name, m in linear_sims.items():
        for i in range(3):
            if abs(sum(m[3 * i : 3 * i + 3]) - 1.0) > 1e-6:
                fails.append(f"row sum {name} row {i + 1}: {sum(m[3 * i : 3 * i + 3]):.6f} != 1")
    return fails


def self_test() -> int:
    fails = self_test_failures(PROJECTIONS, LINEAR_RGB_SIMS)
    for f in fails:
        print(f"FAIL {f}")
    # Mutation proof: the checks must reject the old row and a mistyped Machado constant.
    mutants = {
        "old LMS tritan row": (dict(PROJECTIONS, tritanopia=DEFECTIVE_TRITAN_ROW), {}),
        "mistyped Machado constant": (
            PROJECTIONS,
            {"tritanopia": TRITAN_MACHADO[:8] + (0.309300,)},
        ),
    }
    for name, (proj, lin) in mutants.items():
        caught = self_test_failures(proj, lin)
        print(f"mutation '{name}': {'caught' if caught else 'NOT CAUGHT'} ({len(caught)} failures)")
        for f in caught:
            print(f"  {f}")
        if not caught:
            fails.append(f"mutation {name} not caught")
    print(f"--self-test: {'ok' if not fails else 'FAIL'} ({len(fails)} failures)")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv[1:]:
        raise SystemExit(self_test())
    print(report())
