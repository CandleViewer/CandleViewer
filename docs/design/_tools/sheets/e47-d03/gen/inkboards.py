"""Shared ink-frame builders for boards 06 and 07 (§5, §6, §7)."""
from __future__ import annotations

import sys
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e47d03kit as k  # noqa: E402

PANELS = {"footprint": k.footprint_panel, "dom": k.dom_panel, "heatmap": k.heatmap_panel,
          "profile": k.profile_panel, "cvd-pane": k.cvd_panel, "bubbles": k.bubbles_panel}
# the §7.2 pairs each surface proves, by palette
PAIRS = {
    ("default", "footprint"): ["buy / sell (default)", "footprint bid / ask (default)"],
    ("default", "dom"): ["buy / sell (default)"],
    ("default", "heatmap"): ["heatmap bid / ask, stop 3 (default)", "heatmap bid / ask, stop 5 (default)"],
    ("default", "profile"): ["POC / value area"],
    ("default", "cvd-pane"): ["buy / sell (default)"],
    ("default", "bubbles"): ["buy / sell (default)"],
    ("cvd-safe", "footprint"): ["buy / sell (CVD-safe)", "imbalance vs buy (CVD-safe)", "imbalance vs sell (CVD-safe)"],
    ("cvd-safe", "heatmap"): ["heatmap bid / ask, stop 3 (CVD-safe)", "heatmap bid / ask, stop 5 (CVD-safe)"],
}


def enc_lines(surfaces: list[str]) -> list[str]:
    """The §5 rows whose surface the frame draws."""
    want = {"footprint": ["footprint cells"], "dom": ["DOM ladder"], "heatmap": ["heatmap"], "profile": ["profile"],
            "cvd-pane": ["CVD pane"], "bubbles": ["bubbles", "chart trade markers", "SCR-031 chart candles"]}
    names = {n for s in surfaces for n in want[s]}
    return [f"{c[0]} · {c[1]}: designed {c[3]} — {c[4]} (§5 L{ln})" for ln, c in k.ENCODINGS if c[1] in names]


def pair_lines(palette: str, surfaces: list[str], sim: str, theme: str = "dark") -> list[str]:
    seen, out = set(), []
    for s in surfaces:
        for pr in PAIRS.get((palette, s), []):
            if pr not in seen and (pr, theme) in k.DE_ROWS:
                seen.add(pr)
                out.append(k.de_line(pr, theme, sim))
    return out
