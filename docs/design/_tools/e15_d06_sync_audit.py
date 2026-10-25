#!/usr/bin/env python3
"""E15-D06 sync-groups audit: every number the hi-fi spec quotes, from the repo, plus the per-frame gates.

Standalone, offline, stdlib only (run with ``python3 -I``); it imports the repo's own measurement helpers
(``packages/ui/tokens/tests/verify_tokens.py`` for the theme layering, ``docs/design/_tools/contrast_check.py``
for the WCAG ratio, ``docs/research/_tools/cvd_simulate.py`` for the deficiency matrices and dE76) so no
formula is re-implemented here. Nine sections, each row labelled with its source so a reviewer can re-grep it:

1. Badge geometry (the spec's D-1, PROPOSED): the sync badge per UI density (``16`` section 3: compact 24 px
   rows, comfortable 32 px) -- tile, glyph, gaps, padding and the label box sized by the shared pill-label
   width rule (per glyph class, an upper bound on Inter's advance in em), so the widths of "symbol, crosshair,
   drawings", "symbol", the count "3", "No sync" and the letter-plus-glyph minimum are printed, never typed;
   E15-D02 section 3's text-only minimums (36 / 75 / 205 / 34 px, quoted) beside them with the delta.
2. Popover geometry (D-3, D-4): the 440 px popover's row stack per density, its height, the 1280x800 canvas it
   must fit (E15-D02 section 3: 1168x672) and the 200 % zoom viewport (640x400 CSS px) where it becomes a modal
   with stacked columns, a sticky footer and a scrolling body; the in-app text scale at 125 % and 150 %.
3. The measured matrix: every fg / bg pair the spec's section 12 lists x dark / light / high-contrast,
   resolved exactly as ``verify_tokens.py`` layers the themes (``themes.json``), measured with
   ``contrast_check.contrast_ratio()``, each with its Rec. 601 greyscale twin; thresholds 4.5:1 text (7:1 in
   high-contrast), 3:1 non-text; gated rows 0 FAIL, the badge over footprint cells and the remote crosshair
   over footprint cells reported with the two-tone (1 px canvas halo) rescue measured; E11-D02 D3 / D9's
   9.33 / 9.65 / 9.33 and CMP-188's 5.96 / 6.36 / 11.87 reproduced to the hundredth.
4. The CVD rows: the three PROPOSED group hues (``color.sync.a / .b / .c``, aliased to existing tokens) under
   protanopia / deuteranopia / tritanopia and greyscale, dE76 between every pair; reported, never a FAIL -- the
   letter and the glyph carry the meaning (the gate is section 8's badge-row check).
5. The refusal arithmetic: the magnitude ratio and the decades of the fixture pairs (BTCUSDT 64,011.0 against
   SOLUSDT 142.30 and against ETHUSDT 2,412.5), the one-decade threshold and which pair it refuses.
6. Keyboard parity: every pointer action in the spec's parity table has a non-empty keyboard path; every chord
   drawn is in ``apps/web/src/keymap/keymap.json`` or marked PROPOSED (the shipped file is read).
7. The announcement gate: every join / leave / conflict / refusal / disarm row has a politeness and a string;
   the join and leave strings carry their consequence clause.
8. String gates on the spec and the hand-off: the one T2 rule stated once and cited from the scale-link
   section; the view-as leg first in the Save mention; no closing keyword; no local path, user name, notes
   folder or design-tool host (generic patterns, never the words); every section-0 board row PENDING; no
   placeholder words; the frame names of section 0 = the state inventory = the hand-off's count; "unsync is
   not a reset" verbatim; "storage pending" on every un-stored switch; the events table complete; a lock
   glyph only on the three T2 frames (the scale link in no group, its light twin, Save under view-as); the
   account row, the refusal and the conflict notice never T2; the disarm on every symbol-switch frame; the
   conflict grammar on every conflict frame; the badge density pair; exits never gated.
9. The counts (``--json``) the boards and the PR quote.

Usage: python3 -I docs/design/_tools/e15_d06_sync_audit.py [--json] [--check] [--table] [--self-test]
A plain run prints every section and exits 0; ``--check`` exits 1 on any gated FAIL; ``--self-test``
mutates the spec in memory and proves that every gate fails on its mutation (the gates are mutation-tested
from the first commit); ``--table`` prints section 3 as a Markdown table. UTF-8 stdout. No network; no URL
literal anywhere in this file.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "docs" / "design" / "_tools"
TOKENS = ROOT / "packages" / "ui" / "tokens"
SPEC = ROOT / "docs" / "design" / "E15" / "E15-D06.md"
HANDOFF = ROOT / "docs" / "design" / "E15" / "E15-D06-handoff.md"
KEYMAP = ROOT / "apps" / "web" / "src" / "keymap" / "keymap.json"
MULTI = re.MULTILINE


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(TOKENS / "tests"))
verify = _load(TOKENS / "tests" / "verify_tokens.py", "verify_tokens")
contrast_check = _load(TOOLS / "contrast_check.py", "contrast_check")
cvd = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")

THEMES = ("dark", "light", "high-contrast")
BAR: dict[str, float] = {"text": 4.5, "non-text": 3.0, "hc-text": 7.0}

# ---- the PROPOSED group tokens (spec D-2; for E15-D13): each aliased to a token that exists today, so the
# boards draw them with no token-API call. Green (buy / success), red (sell / live) and blue (demo, focus) are
# excluded (`16` section 6 rule 8; E11-D02 section 10). The final hues are E15-D13's.
SYNC_ALIAS: dict[str, str] = {
    "color.sync.a": "color.status.info.strong",
    "color.sync.b": "color.status.warning.strong",
    "color.sync.c": "color.node.logic",
}
# Measured and rejected (spec section 12): a tinted tile fill. The `.subtle` tones have no purple twin and
# `palette.purple.900` is not re-aliased by the light set, so the letter would measure 1.23:1 there. The tile
# therefore carries the hue as its 2 px edge only; the letter sits on the chip's own `color.surface.raised`.
REJECTED_TINT = (
    ("color.status.info.subtle", "cyan"),
    ("color.status.warning.subtle", "amber"),
    ("palette.purple.900", "purple"),
)
SYNC_HUE_WORD = {"a": "cyan", "b": "amber", "c": "purple"}

# ---- badge geometry (spec D-1, PROPOSED) per UI density (`16` section 3) ----
DENSITY = {
    "compact": {
        "row": 24,
        "badge_h": 20,
        "tile": 16,
        "glyph": 12,
        "gap": 4,
        "pad_x": 6,
        "text": 11,
    },
    "comfortable": {
        "row": 32,
        "badge_h": 24,
        "tile": 18,
        "glyph": 16,
        "gap": 4,
        "pad_x": 8,
        "text": 12,
    },
}
# E15-D02 section 3 (merged 1044c4f602eff6ae1a2cf42201ab398f6c4234d1): the text-only header minimums at compact,
# "estimated at 12 px Inter": the sync badge "A · 1" 36, "A · symbol" 75, a chart's three axes in words 205,
# the provenance "via A" 34. Quoted here so the delta to the hi-fi badge is printed, never typed.
D02_MIN = {"A · 1": 36, "A · symbol": 75, "A · symbol, crosshair, drawings": 205, "via A": 34}
# The shared pill-label width rule (per glyph class, an upper bound on Inter's advance in em).
PILL_EM = {
    "upper": 0.84,
    "wide_lower": 0.95,
    "lower": 0.56,
    "digit": 0.68,
    "thin": 0.34,
    "symbol": 1.0,
}
BADGE_LABELS = {
    "full": "symbol, crosshair, drawings",  # a chart's three axes (AD-4 defaults)
    "one": "symbol",  # a DOM or a tape
    "count": "3",  # D-3 step 3: the words shorten to a count
    "none": "No sync",  # AD-6 / D-24: an unsynced market panel
}

# ---- popover geometry (spec D-3, D-4), rows per density: (name, compact px, comfortable px) ----
POPOVER_W = 440  # E15-D02 D-25: 440 px wide at both widths
POPOVER_PAD = 16  # space.inset.md
POPOVER_ROWS: tuple[tuple[str, int, int], ...] = (
    ("title row: This panel · Group radio", 24, 32),
    ("gap", 8, 12),
    ("heading: Group A shares", 16, 20),
    ("switch row 1 (Symbol | Crosshair): switch + consequence line", 44, 54),
    ("switch row 2 (Interval | Time range)", 44, 54),
    ("switch row 3 (Drawings, same symbol only)", 44, 54),
    ("account row (unavailable, full width) + note", 44, 54),
    ("gap", 8, 8),
    ("members line: Panels in group A", 16, 20),
    ("conflict notice (two caption lines)", 36, 40),
    ("rule + gaps", 17, 17),
    ("heading: Price scale, per panel", 16, 20),
    ("scale select rows (x2)", 56, 72),
)
CANVAS_1280 = (1168, 672)  # E15-D02 section 3: the canvas at 1280x800
CANVAS_1920 = (1808, 952)
ZOOM200 = (640, 400)  # 1280x800 at 200 %: the CSS viewport
MODAL_MARGIN = 16  # px kept around a popover before it becomes a modal
MODAL_HEADER = 32
MODAL_FOOTER = 40
SWITCH_ROWS_STACKED = 6  # five switches + the account row in one column at 200 %

# ---- fixture prices (E15-D02 section 0: BTCUSDT 64,011.0; ETHUSDT 2,412.5; SOLUSDT 142.30) ----
PRICES = {"BTCUSDT": 64011.0, "ETHUSDT": 2412.5, "SOLUSDT": 142.30}
THRESHOLD_DECADES = 1.0  # E15-S05's default: one decade on the mid prices (OQ-K keeps it)

# ---- the measured matrix (spec section 12): element | fg | bg | role | gated? ----
# role text -> 4.5 (7.0 in high-contrast), non-text -> 3.0, decorative -> reported only. "gated" rows FAIL;
# "report" rows are printed for the record (the badge never sits on a footprint cell; the remote crosshair
# over a cell takes the two-tone rescue measured in section 3b).
PAIRS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "badge letter in the tile (no tint; the chip's own fill)",
        "color.text.primary",
        "color.surface.raised",
        "text",
        "gated",
    ),
    (
        "rejected tint: letter on a cyan-tinted tile",
        "color.text.primary",
        "color.status.info.subtle",
        "text",
        "report",
    ),
    (
        "rejected tint: letter on an amber-tinted tile",
        "color.text.primary",
        "color.status.warning.subtle",
        "text",
        "report",
    ),
    (
        "rejected tint: letter on a purple-tinted tile",
        "color.text.primary",
        "palette.purple.900",
        "text",
        "report",
    ),
    ("tile edge A on the header", "color.sync.a", "color.surface.raised", "non-text", "gated"),
    ("tile edge B on the header", "color.sync.b", "color.surface.raised", "non-text", "gated"),
    ("tile edge C on the header", "color.sync.c", "color.surface.raised", "non-text", "gated"),
    (
        "tile edge A on the canvas (grid cell header)",
        "color.sync.a",
        "color.surface.canvas",
        "non-text",
        "gated",
    ),
    (
        "tile edge B on the canvas (grid cell header)",
        "color.sync.b",
        "color.surface.canvas",
        "non-text",
        "gated",
    ),
    (
        "tile edge C on the canvas (grid cell header)",
        "color.sync.c",
        "color.surface.canvas",
        "non-text",
        "gated",
    ),
    (
        "tile edge A on the focused panel bar",
        "color.sync.a",
        "color.surface.selected",
        "non-text",
        "report",
    ),
    (
        "tile edge B on the focused panel bar",
        "color.sync.b",
        "color.surface.selected",
        "non-text",
        "report",
    ),
    (
        "tile edge C on the focused panel bar",
        "color.sync.c",
        "color.surface.selected",
        "non-text",
        "report",
    ),
    (
        "tile edge A on a footprint bid cell",
        "color.sync.a",
        "color.footprint.bid",
        "non-text",
        "report",
    ),
    (
        "tile edge B on a footprint ask cell",
        "color.sync.b",
        "color.footprint.ask",
        "non-text",
        "report",
    ),
    (
        "tile edge C on a footprint imbalance cell",
        "color.sync.c",
        "color.footprint.imbalance",
        "non-text",
        "report",
    ),
    (
        "badge axes words on the header",
        "color.text.secondary",
        "color.surface.raised",
        "text",
        "gated",
    ),
    (
        "badge glyph (link / unlink) on the header",
        "color.text.secondary",
        "color.surface.raised",
        "non-text",
        "gated",
    ),
    (
        "chip hairline on the header",
        "color.border.default",
        "color.surface.raised",
        "decorative",
        "report",
    ),
    ("popover text on the overlay", "color.text.primary", "color.surface.overlay", "text", "gated"),
    (
        "consequence line on the overlay",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
        "gated",
    ),
    (
        "conflict glyph (warning) on the overlay",
        "color.status.warning.strong",
        "color.surface.overlay",
        "non-text",
        "gated",
    ),
    (
        "switch on-track on the overlay",
        "color.action.primary.default",
        "color.surface.overlay",
        "non-text",
        "gated",
    ),
    (
        "switch off-track on the overlay",
        "color.text.tertiary",
        "color.surface.overlay",
        "non-text",
        "gated",
    ),
    (
        "T2 label (Link scale, no group) on the menu",
        "color.text.tertiary",
        "color.surface.overlay",
        "text",
        "gated",
    ),
    ("T2 reason on the menu", "color.text.secondary", "color.surface.overlay", "text", "gated"),
    (
        "T2 lock glyph on the menu",
        "color.text.tertiary",
        "color.surface.overlay",
        "non-text",
        "gated",
    ),
    (
        "T2 Save label on the header fill",
        "color.text.tertiary",
        "color.surface.raised",
        "text",
        "gated",
    ),
    (
        "T2 Save reason on the header fill",
        "color.text.secondary",
        "color.surface.raised",
        "text",
        "gated",
    ),
    (
        "refusal dialog text on the overlay",
        "color.text.primary",
        "color.surface.overlay",
        "text",
        "gated",
    ),
    (
        "refusal primary action label",
        "color.text.on-action",
        "color.action.primary.default",
        "text",
        "gated",
    ),
    (
        "axis text Linked / Independent on the canvas",
        "color.text.tertiary",
        "color.surface.canvas",
        "text",
        "gated",
    ),
    (
        "local crosshair (solid) on the canvas",
        "color.crosshair",
        "color.surface.canvas",
        "non-text",
        "gated",
    ),
    ("focus ring on the header", "color.focus.ring", "color.surface.raised", "non-text", "gated"),
    ("focus ring on the overlay", "color.focus.ring", "color.surface.overlay", "non-text", "gated"),
    (
        "provenance line on the header",
        "color.text.secondary",
        "color.surface.raised",
        "text",
        "gated",
    ),
)
# 3b: the remote crosshair = color.crosshair at opacity.muted, blended over its background; over the canvas it
# is gated (E11-D02 D9); over footprint cells it is reported, with the two-tone rescue (a 1 px color.surface.canvas
# halo: PASS when the dash or its halo clears 3:1 against the cell AND the dash clears 3:1 against the halo).
REMOTE_BGS = (
    "color.surface.canvas",
    "color.footprint.bid",
    "color.footprint.ask",
    "color.footprint.imbalance",
)
# Reproductions (merged text, to the hundredth): E11-D02 D3 / D9 color.crosshair on the canvas 9.33 / 9.65 / 9.33;
# `15` CMP-188 color.chart.axis (= color.text.tertiary) on the canvas 5.96 / 6.36 / 11.87.
E11_CROSSHAIR = (9.33, 9.65, 9.33)
CMP188_AXIS = (5.96, 6.36, 11.87)

# ---- the tokens the spec binds (section 12 / the hand-off's Tokens lines); PROPOSED ones resolve via SYNC_ALIAS ----
BOUND = (
    "color.surface.canvas", "color.surface.raised", "color.surface.overlay", "color.surface.hover",
    "color.surface.selected", "color.border.default", "color.border.strong", "color.text.primary",
    "color.text.secondary", "color.text.tertiary", "color.text.inverse", "color.text.on-action",
    "color.action.primary.default", "color.status.warning.strong", "color.status.warning.subtle",
    "color.status.info.default", "color.status.info.subtle", "color.status.warning.default", "color.node.logic",
    "color.focus.ring", "color.crosshair", "color.footprint.bid", "color.footprint.ask",
    "color.footprint.imbalance", "color.env.demo", "color.env.live", "opacity.muted", "radius.badge",
    "radius.pill", "radius.card", "radius.xs", "size.icon.sm", "size.icon.md", "size.control.height",
    "space.inset.xs", "space.inset.sm", "space.inset.md", "elevation.popover", "type.ui.caption",
    "type.ui.body", "font.family.mono",
)  # fmt: skip
PROPOSED_TOKENS = tuple(SYNC_ALIAS)  # color.sync.* (E15-D13): aliased, never bound as existing
PROPOSED_GLYPHS = (
    "link",
    "unlink",
)  # CMP-019 registry names the badge needs (PROPOSED; the registry is not in the repo)
NEVER_ON_T2 = ("color.text.disabled", "opacity.disabled")

# Hygiene: generic patterns only; no personal word and no hostname, whole or split. The path literal is
# built from parts so this file never contains the string it forbids.
FORBIDDEN = (
    re.compile("/" + "(?:home|Users)" + "/[^/\\s]+/"),
    re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE),
    re.compile(r"\bwt" + r"-notes\b", re.IGNORECASE),
    re.compile(r"\b(?:hpe|hcl)-worker-\d\b", re.IGNORECASE),
)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#\d+", re.IGNORECASE)
PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|FIXME|lorem|XXX)\b")
T2_FRAMES = ("SCR-043/link-no-group", "SCR-043/light-link-no-group", "SCR-023/dirty-save-view-as")
EVENTS = (
    "sync.group_created", "sync.group_changed", "sync.axis_toggled", "sync.panel_joined_group",
    "sync.panel_left_group", "sync.conflict_shown", "scale.link_refused", "scale.percent_suggested_accepted",
)  # fmt: skip

_THEME_CACHE: dict[str, dict[str, Any]] = {}


def theme(name: str) -> dict[str, Any]:
    if name not in _THEME_CACHE:
        files = [verify.PRIMITIVES, *verify.THEMES[name]]
        _THEME_CACHE[name] = verify.merged_set(files)
    return _THEME_CACHE[name]


def tok(name: str, th: str = "dark") -> Any:
    t = theme(th)
    if name in SYNC_ALIAS:
        name = SYNC_ALIAS[name]
    if name not in t:
        raise KeyError(name)
    return verify.resolve(t[name]["$value"], t)


def hx(name: str, th: str) -> str:
    return str(tok(name, th)).upper()


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(fg: str, bg: str) -> float:
    r: float = contrast_check.contrast_ratio(rgb(fg), rgb(bg))
    return r


def blend(fg: str, bg: str, a: float) -> str:
    f, b = rgb(fg), rgb(bg)
    return "#" + "".join(f"{round(f[i] * a + b[i] * (1 - a)):02X}" for i in range(3))


def grey(h: str) -> str:
    """Rec. 601 luma, the greyscale twin (`05` section 4; the boards' greyscale strip)."""
    r, g, b = rgb(h)
    y = round(0.299 * r + 0.587 * g + 0.114 * b)
    return f"#{y:02X}{y:02X}{y:02X}"


def de(a: str, b: str) -> float:
    d: float = cvd.delta_e76(a, b)
    return d


def sim(h: str, kind: str) -> str:
    s: str = cvd.simulate(h, kind)
    return s.upper()


def fmt(x: float) -> str:
    return f"{x:.2f}"


def pill_em(label: str) -> float:
    em = 0.0
    for ch in label:
        if re.match(r"[A-Z]", ch):
            em += PILL_EM["upper"]
        elif ch in "mw":
            em += PILL_EM["wide_lower"]
        elif re.match(r"[a-z]", ch):
            em += PILL_EM["lower"]
        elif ch.isdigit():
            em += PILL_EM["digit"]
        elif ch in " .,:;·'’|-":
            em += PILL_EM["thin"]
        else:
            em += PILL_EM["symbol"]
    return em


def label_w(label: str, size: int) -> int:
    """The shared pill-label rule: never narrower than the flat 0.62 em estimate."""
    flat = math.ceil(len(label) * size * 0.62)
    return max(flat, math.ceil(pill_em(label) * size))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i : j if j > 0 else len(text)]


def count(pattern: str, body: str) -> int:
    return len(re.findall(pattern, body, MULTI))


def rows_of(block: str) -> list[list[str]]:
    out = []
    for line in block.splitlines():
        if line.startswith("|") and not re.match(r"^\|\s*-", line):
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out[1:] if out else []


# ---------------------------------------------------------------- 1. badge geometry --------------------------
def badge_report() -> dict[str, Any]:
    out: dict[str, Any] = {"densities": {}, "d02_minimums": dict(D02_MIN)}
    for dens, g in DENSITY.items():
        fixed = (
            g["pad_x"] + g["tile"] + g["gap"] + g["glyph"] + g["pad_x"]
        )  # letter tile + glyph, no words
        widths = {}
        for key, label in BADGE_LABELS.items():
            lw = label_w(label, g["text"])
            if key == "none":  # no tile: glyph + words
                widths[key] = g["pad_x"] + g["glyph"] + g["gap"] + lw + g["pad_x"]
            else:
                widths[key] = fixed + g["gap"] + lw
        widths["letter_glyph"] = fixed
        out["densities"][dens] = {
            **g,
            "label_w": {k: label_w(v, g["text"]) for k, v in BADGE_LABELS.items()},
            "width": widths,
            "inset_in_row": (g["row"] - g["badge_h"]) // 2,
        }
    c = out["densities"]["compact"]["width"]
    out["delta_vs_d02"] = {
        "letter_glyph_vs_A·1": c["letter_glyph"] - D02_MIN["A · 1"],
        "one_vs_A·symbol": c["one"] - D02_MIN["A · symbol"],
        "full_vs_three_axes": c["full"] - D02_MIN["A · symbol, crosshair, drawings"],
    }
    out["kind_minimum_delta"] = max(0, c["letter_glyph"] - D02_MIN["A · 1"])
    return out


# ---------------------------------------------------------------- 2. popover geometry ------------------------
def popover_report() -> dict[str, Any]:
    out: dict[str, Any] = {"width": POPOVER_W, "pad": POPOVER_PAD, "rows": []}
    hc = hf = 2 * POPOVER_PAD
    for name, c, f in POPOVER_ROWS:
        out["rows"].append({"row": name, "compact": c, "comfortable": f})
        hc += c
        hf += f
    out["height"] = {"compact": hc, "comfortable": hf}
    out["column_w"] = (POPOVER_W - 2 * POPOVER_PAD - POPOVER_PAD) // 2
    out["fits_1280"] = {
        "compact": hc + 2 * MODAL_MARGIN <= CANVAS_1280[1],
        "comfortable": hf + 2 * MODAL_MARGIN <= CANVAS_1280[1],
    }
    out["fits_1920"] = {
        "compact": hc + 2 * MODAL_MARGIN <= CANVAS_1920[1],
        "comfortable": hf + 2 * MODAL_MARGIN <= CANVAS_1920[1],
    }
    # 200 %: the CSS viewport is 640x400; the popover (440 + 2 x 16 margin) fits the width but not the height ->
    # modal filling the viewport; the two switch columns stack to one, the footer is one sticky row, the body scrolls.
    stacked_extra = {
        "compact": (SWITCH_ROWS_STACKED - 4) * 44,
        "comfortable": (SWITCH_ROWS_STACKED - 4) * 54,
    }
    out["zoom200"] = {
        "viewport": list(ZOOM200),
        "modal": hc + 2 * MODAL_MARGIN > ZOOM200[1] or POPOVER_W + 2 * MODAL_MARGIN > ZOOM200[0],
        "body_h": {
            "compact": hc + stacked_extra["compact"],
            "comfortable": hf + stacked_extra["comfortable"],
        },
        "visible_body": ZOOM200[1] - MODAL_HEADER - MODAL_FOOTER,
        "scrolls": {
            "compact": hc + stacked_extra["compact"] > ZOOM200[1] - MODAL_HEADER - MODAL_FOOTER,
            "comfortable": True,
        },
        "header": MODAL_HEADER,
        "footer": MODAL_FOOTER,
    }
    # the in-app text scale: 125 % and 150 % keep the popover (height scales with the text rows)
    for pct in (125, 150):
        h = math.ceil(hc * pct / 100)
        out[f"text_scale_{pct}"] = {
            "compact_h": h,
            "fits_1280": h + 2 * MODAL_MARGIN <= CANVAS_1280[1],
            "popover": h + 2 * MODAL_MARGIN <= CANVAS_1280[1],
        }
    return out


# ---------------------------------------------------------------- 3. the measured matrix ---------------------
def matrix_report(fails: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    gated = failed = 0
    for element, fg, bg, role, gate in PAIRS:
        for th in THEMES:
            f, b = hx(fg, th), hx(bg, th)
            r = ratio(f, b)
            g = ratio(grey(f), grey(b))
            bar = (
                None
                if role == "decorative"
                else BAR["hc-text" if th == "high-contrast" and role == "text" else role]
            )
            ok = (
                bar is None or r >= bar
            )  # the greyscale twin is reported (the strip), never the gate
            row = {
                "element": element,
                "theme": th,
                "fg": fg,
                "bg": bg,
                "fg_hex": f,
                "bg_hex": b,
                "ratio": round(r, 2),
                "grey": round(g, 2),
                "role": role,
                "bar": bar,
                "gate": gate,
                "pass": ok,
            }
            rows.append(row)
            if gate == "gated" and bar is not None:
                gated += 1
                if not ok:
                    failed += 1
                    fails.append(f"matrix: {element} ({th}) {fmt(r)} < {bar}")
    # 3b: the remote crosshair at opacity.muted over its backgrounds, with the two-tone rescue
    remote: list[dict[str, Any]] = []
    muted = float(tok("opacity.muted"))
    for th in THEMES:
        for bg in REMOTE_BGS:
            b = hx(bg, th)
            dash = blend(hx("color.crosshair", th), b, muted)
            halo = hx("color.surface.canvas", th)
            r = ratio(dash, b)
            best = max(r, ratio(halo, b))
            dash_vs_halo = ratio(dash, halo)
            two_tone_ok = best >= BAR["non-text"] and dash_vs_halo >= BAR["non-text"]
            gate = "gated" if bg == "color.surface.canvas" else "report"
            ok = r >= BAR["non-text"] if gate == "gated" else two_tone_ok
            remote.append(
                {
                    "theme": th,
                    "bg": bg,
                    "bg_hex": b,
                    "dash_hex": dash,
                    "opacity": muted,
                    "ratio": round(r, 2),
                    "grey": round(ratio(grey(dash), grey(b)), 2),
                    "halo_hex": halo,
                    "best_of_two_tone": round(best, 2),
                    "dash_vs_halo": round(dash_vs_halo, 2),
                    "two_tone_pass": two_tone_ok,
                    "gate": gate,
                    "pass": ok,
                }
            )
            if gate == "gated":
                gated += 1
                if not ok:
                    failed += 1
                    fails.append(f"matrix: remote crosshair over {bg} ({th}) {fmt(r)} < 3")
    # reproductions to the hundredth
    repro = {
        "e11_d02_crosshair_on_canvas": [
            round(ratio(hx("color.crosshair", th), hx("color.surface.canvas", th)), 2)
            for th in THEMES
        ],
        "e11_d02_expected": list(E11_CROSSHAIR),
        "cmp188_axis_on_canvas": [
            round(ratio(hx("color.text.tertiary", th), hx("color.surface.canvas", th)), 2)
            for th in THEMES
        ],
        "cmp188_expected": list(CMP188_AXIS),
    }
    if repro["e11_d02_crosshair_on_canvas"] != repro["e11_d02_expected"]:
        fails.append("repro: E11-D02 D3 / D9 crosshair ratios not reproduced")
    if repro["cmp188_axis_on_canvas"] != repro["cmp188_expected"]:
        fails.append("repro: CMP-188 axis ratios not reproduced")
    return {"rows": rows, "remote": remote, "gated": gated, "failed": failed, "repro": repro}


def _cell(r: dict[str, Any]) -> str:
    return f"{fmt(r['ratio'])} (grey {fmt(r['grey'])})"


def matrix_table(m: dict[str, Any]) -> str:
    lines = [
        "| Pair (fg on bg) | Role | Dark | Light | High contrast | Gate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    by: dict[str, dict[str, dict[str, Any]]] = {}
    for r in m["rows"]:
        by.setdefault(r["element"], {})[r["theme"]] = r
    for element, ths in by.items():
        d, l, h = ths["dark"], ths["light"], ths["high-contrast"]
        gate = (
            (
                "reported"
                + (
                    ""
                    if d["bar"] is None
                    else (" — PASS" if all(x["pass"] for x in (d, l, h)) else " — below the bar")
                )
            )
            if d["gate"] == "report" or d["bar"] is None
            else ("PASS" if all(x["pass"] for x in (d, l, h)) else "FAIL")
        )
        lines.append(
            f"| {element}: `{d['fg']}` on `{d['bg']}` | {d['role']} | {_cell(d)} | {_cell(l)} | {_cell(h)} | {gate} |"
        )
    lines.append("")
    lines.append(
        "| Remote crosshair (`color.crosshair` at `opacity.muted`) over | Dark | Light | High contrast | Two-tone rescue (dash or halo vs cell; dash vs halo) | Gate |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- |")
    byr: dict[str, dict[str, dict[str, Any]]] = {}
    for r in m["remote"]:
        byr.setdefault(r["bg"], {})[r["theme"]] = r
    for bg, ths in byr.items():
        d, l, h = ths["dark"], ths["light"], ths["high-contrast"]
        tt = f"{fmt(d['best_of_two_tone'])} / {fmt(l['best_of_two_tone'])} / {fmt(h['best_of_two_tone'])}; {fmt(d['dash_vs_halo'])} / {fmt(l['dash_vs_halo'])} / {fmt(h['dash_vs_halo'])}"
        gate = (
            "PASS"
            if d["gate"] == "gated" and all(x["pass"] for x in (d, l, h))
            else (
                "reported; two-tone "
                + ("PASS" if all(x["two_tone_pass"] for x in (d, l, h)) else "FAIL")
            )
        )
        lines.append(
            f"| `{bg}` | {fmt(d['ratio'])} | {fmt(l['ratio'])} | {fmt(h['ratio'])} | {tt} | {gate} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------- 4. CVD rows --------------------------------
def cvd_report() -> dict[str, Any]:
    kinds = ("protanopia", "deuteranopia", "tritanopia", "greyscale")
    out: dict[str, Any] = {"hues": {}, "pairs": {}, "min_de": {}}
    for th in THEMES:
        hues = {k: hx(f"color.sync.{k}", th) for k in ("a", "b", "c")}
        out["hues"][th] = hues
        out["pairs"][th] = {}
        for kind in kinds:
            simd = {k: (grey(v) if kind == "greyscale" else sim(v, kind)) for k, v in hues.items()}
            pairs = {
                "a-b": round(de(simd["a"], simd["b"]), 1),
                "a-c": round(de(simd["a"], simd["c"]), 1),
                "b-c": round(de(simd["b"], simd["c"]), 1),
            }
            out["pairs"][th][kind] = {"simulated": simd, **pairs}
        out["min_de"][th] = min(
            min(v for k, v in p.items() if k != "simulated") for p in out["pairs"][th].values()
        )
    return out


# ---------------------------------------------------------------- 5. refusal arithmetic ----------------------
def refusal_report() -> dict[str, Any]:
    def pair(a: str, b: str) -> dict[str, Any]:
        r = PRICES[a] / PRICES[b]
        dec = math.log10(r)
        return {
            "a": a,
            "b": b,
            "price_a": PRICES[a],
            "price_b": PRICES[b],
            "ratio": round(r, 2),
            "about": int(round(r, -1)) if r >= 100 else round(r, 1),
            "decades": round(dec, 2),
            "refused": dec > THRESHOLD_DECADES,
        }

    return {
        "threshold_decades": THRESHOLD_DECADES,
        "btc_sol": pair("BTCUSDT", "SOLUSDT"),
        "btc_eth": pair("BTCUSDT", "ETHUSDT"),
        "eth_sol": pair("ETHUSDT", "SOLUSDT"),
    }


# ---------------------------------------------------------------- 6-8. the gates -----------------------------
def keymap_bindings() -> set[str]:
    out: set[str] = set()
    try:
        data = json.loads(KEYMAP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    cmds = data.get("commands", data) if isinstance(data, dict) else data
    if isinstance(cmds, dict):
        cmds = list(cmds.values())
    for c in cmds if isinstance(cmds, list) else []:
        if not isinstance(c, dict):
            continue
        b = c.get("defaultBinding")
        if isinstance(b, str):
            out.add(b)
        elif isinstance(b, list):
            out.update(x for x in b if isinstance(x, str))
    return out


def frame_names(text: str) -> set[str]:
    return set(re.findall(r"`((?:SCR-023|SCR-043|CMP-082)/[a-z0-9-]+)`", text))


def inventory_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(section(spec, "### 3.2 ", "## 4. ")) if r and r[0].startswith("`")]


def gates(spec: str, handoff: str, tool: str, bindings: set[str]) -> list[str]:
    """Each returned string is a failed gate. The order and wording are stable (the self-test keys on them)."""
    fails: list[str] = []
    for name, text in (("spec", spec), ("handoff", handoff), ("tool", tool)):
        if any(p.search(text) for p in FORBIDDEN):
            fails.append(f"hygiene: {name} matches a forbidden pattern")
        if name != "tool" and CLOSING.search(text):
            fails.append(f"closing: {name} carries a closing keyword")
        if name != "tool" and PLACEHOLDER.search(text):
            fails.append(f"placeholder: {name} carries a placeholder word")
    # the one T2 rule, stated once, cited from the scale-link section and from the Save mention
    if spec.count("The one T2 rule") != 1:
        fails.append("t2: the one T2 rule is not stated exactly once")
    if "§10.3" not in section(spec, "## 7. ", "## 8. "):
        fails.append("t2: the scale-link section does not cite the T2 rule (§10.3)")
    if "§10.3" not in section(spec, "## 8. ", "## 9. "):
        fails.append("t2: the Save mention does not cite the T2 rule (§10.3)")
    t2 = section(spec, "### 10.3 ", "## 11. ")
    if not all(
        w in t2
        for w in (
            "aria-disabled",
            "CMP-079",
            "CMP-019",
            "E09-D09",
            "color.text.tertiary",
            "color.text.secondary",
        )
    ):
        fails.append(
            "t2: the T2 statement lacks its anatomy (aria-disabled, CMP-079, CMP-019, E09-D09, the two text tokens)"
        )
    for w in NEVER_ON_T2:
        if re.search(r"(?<!never )(?<!never `)" + re.escape(w), t2):
            fails.append(f"t2: the T2 statement binds {w}")
    # the view-as leg first on the Save mention
    save = section(spec, "## 8. ", "## 9. ")
    iv, ip = save.find("rbac.view_as"), save.find("workspaces:write")
    if iv < 0 or ip < 0 or iv > ip:
        fails.append("view-as: the Save mention does not put rbac.view_as before workspaces:write")
    # exits never gated
    if not re.search(r"Esc[^.|]*never (?:gated|locked)", spec):
        fails.append("exits: the spec does not state that Esc is never gated")
    # section 0: every board row PENDING, frames named there = the state inventory = the hand-off's count
    boards = section(spec, "## 0. ", "## 1. ")
    board_rows = [r for r in rows_of(boards) if r and re.fullmatch(r"\d\d", r[0])]
    if not board_rows:
        fails.append("boards: no board rows in section 0")
    for r in board_rows:
        if "PENDING" not in r[-1]:
            fails.append("boards: a section-0 board row is not PENDING")
            break
    f0, finv = frame_names(boards), {r[0].strip("`") for r in inventory_rows(spec)}
    if f0 != finv:
        fails.append(
            f"frames: section 0 names {len(f0)} frames, the state inventory {len(finv)}; they differ"
        )
    m = re.search(r"(\d+) named frames", handoff)
    if not m or int(m.group(1)) != len(finv):
        fails.append("frames: the hand-off's named-frame count differs from the state inventory")
    # T2 only on the three T2 frames; the account row, the refusal and the conflict notice never T2
    inv = inventory_rows(spec)
    t2_rows = {r[0].strip("`") for r in inv if len(r) > 3 and re.search(r"\bT2\b", r[3])}
    if t2_rows != set(T2_FRAMES):
        fails.append(
            f"t2-frames: the inventory marks {sorted(t2_rows)} as T2; expected exactly {list(T2_FRAMES)}"
        )
    for r in inv:
        name = r[0].strip("`")
        if name not in T2_FRAMES and re.search(r"lock glyph|CMP-079", " ".join(r)):
            fails.append(
                f"over-conversion: frame {name} draws a lock glyph or CMP-079 outside the T2 frames"
            )
            break
    for r in inv:
        name = r[0].strip("`")
        if "account" in name and (
            not re.search(r"absence|unavailable", r[3]) or "aria-disabled" not in " ".join(r)
        ):
            fails.append(
                "over-conversion: the account-axis frame is not a plain unavailable row with aria-disabled"
            )
        if "refus" in name and "account" not in name and "outcome" not in r[3]:
            fails.append("over-conversion: a refusal frame is not classed as an outcome")
        if "conflict" in name and "status" not in r[3] and "T2" not in r[3]:
            fails.append("over-conversion: a conflict frame is not classed as a status")
        if "conflict" in name and "aligns by timestamp" not in " ".join(r):
            fails.append(
                "conflict: a conflict frame row lacks the notice grammar (aligns by timestamp)"
            )
        if "symbol-switch" in name and "disarm" not in " ".join(r).lower():
            fails.append("disarm: a symbol-switch frame row does not draw the disarm")
    # the badge density pair (section 4)
    badge = section(spec, "## 4. ", "## 5. ")
    if not (
        re.search(r"^\| compact ", badge, MULTI) and re.search(r"^\| comfortable ", badge, MULTI)
    ):
        fails.append("badge: section 4 lacks the compact / comfortable row pair")
    if "no validity-disabled control" not in spec:
        fails.append("validity: the spec does not state that no validity-disabled control exists")
    if "unsync is not a reset" not in spec:
        fails.append("retention: 'unsync is not a reset' is not stated verbatim")
    # storage pending on every un-stored switch and on percent
    switches = section(spec, "### 5.2 ", "### 5.3 ")
    for ax in ("Interval", "Time range"):
        row = re.search(r"^\| " + ax + r" .*$", switches, MULTI)
        if not row or "storage pending" not in row.group(0):
            fails.append(f"storage: the {ax} switch row lacks 'storage pending'")
    acct = re.search(r"^\| Account .*$", switches, MULTI)
    if (
        not acct
        or "aria-disabled" not in acct.group(0)
        or re.search(r"lock|CMP-079|T2", acct.group(0))
    ):
        fails.append(
            "storage: the Account row is not a plain unavailable row (aria-disabled, no lock, no key)"
        )
    if "storage pending" not in section(spec, "### 7.4 ", "### 7.5 "):
        fails.append("storage: the percent suggestion lacks 'storage pending'")
    # keys: every chord in keymap.json or marked PROPOSED; parity: every pointer action has a keyboard path
    keys = rows_of(section(spec, "### 9.1 ", "### 9.2 "))
    if len(keys) < 10:
        fails.append(f"keys: expected at least 10 key rows, found {len(keys)}")
    for r in keys:
        if len(r) < 5:
            continue
        chords = re.findall(r"`([^`]+)`", r[1])
        marked = re.search(r"PROPOSED|existing|component key|by design", r[4], re.IGNORECASE)
        if chords and not marked and not all(c in bindings for c in chords):
            fails.append(
                "keys: a chord is drawn as shipped but is not in keymap.json and is not marked PROPOSED"
            )
            break
        if "existing" in r[4].lower() and any(c not in bindings for c in chords):
            fails.append("keys: an 'existing' row names a chord that keymap.json does not carry")
            break
    parity = rows_of(section(spec, "### 9.3 ", "### 9.4 "))
    if len(parity) < 10:
        fails.append(f"parity: expected at least 10 parity rows, found {len(parity)}")
    for r in parity:
        if (
            len(r) < 2
            or not r[1]
            or r[1] == "—"
            or re.search(r"pointer[- ]only", " ".join(r), re.IGNORECASE)
        ):
            fails.append("parity: a pointer action lacks a keyboard path or is pointer-only")
            break
    # announcements: a politeness and a string on every row; the consequence clause on join and leave
    ann = [
        r for r in rows_of(section(spec, "### 10.2 ", "### 10.3 ")) if r and r[0].startswith("AN-")
    ]
    if len(ann) < 8:
        fails.append(f"announcements: expected at least 8 rows, found {len(ann)}")
    for r in ann:
        if (
            len(r) < 4
            or r[2].strip() not in ("polite", "assertive", "none")
            or not re.search(r"[\"“]", r[3])
        ):
            fails.append("announcements: a row lacks its politeness or its string")
            break
        if "joined sync group" in r[3] and "shared with" not in r[3]:
            fails.append("announcements: the join string lacks its consequence clause")
        if "left sync group" in r[3] and "keeps" not in r[3]:
            fails.append("announcements: the leave string lacks its consequence clause")
    # the events table complete
    ev = section(spec, "## 14. ", "## 15. ")
    for e in EVENTS:
        if f"`{e}" not in ev:
            fails.append(f"events: {e} missing from the observability table")
    # tokens: PROPOSED ones carry the marker on their rows; T2 rows never carry the forbidden tokens
    for t in PROPOSED_TOKENS:
        if not re.search(re.escape(t) + r"[^\n]*PROPOSED|PROPOSED[^\n]*" + re.escape(t), spec):
            fails.append(f"tokens: {t} is not marked PROPOSED on its row")
    return fails


def counts(spec: str, handoff: str) -> dict[str, int]:
    inv = inventory_rows(spec)
    return {
        "boards": count(r"^\| \d\d +\| `", section(spec, "## 0. ", "## 1. ")),
        "light_boards": count(r"^\| \d\d +\| `[a-z0-9-]*light", section(spec, "## 0. ", "## 1. ")),
        "ac_rows": count(
            r"^\| (?:Sc\. \d|DoD|Test plan|Security|A11y|Performance|Observability|`14`)",
            section(spec, "### 1.2 ", "## 2. "),
        ),
        "decisions": count(r"^\| D-\d+ ", section(spec, "### 3.1 ", "### 3.2 ")),
        "frames_named": len(inv),
        "t2_frames": sum(1 for r in inv if len(r) > 3 and re.search(r"\bT2\b", r[3])),
        "switches": count(
            r"^\| (?:Symbol|Crosshair|Interval|Time range|Drawings|Account) ",
            section(spec, "### 5.2 ", "### 5.3 "),
        ),
        "key_rows": len(rows_of(section(spec, "### 9.1 ", "### 9.2 "))),
        "parity_rows": len(rows_of(section(spec, "### 9.3 ", "### 9.4 "))),
        "announcements": count(r"^\| AN-\d+ ", section(spec, "### 10.2 ", "### 10.3 ")),
        "copy_rows": count(r"^\| `[a-z._]+` ", section(spec, "## 11. ", "## 12. ")),
        "a_rows": count(r"^\| A-\d+ ", section(spec, "## 13. ", "## 14. ")),
        "c_rows": count(r"^\| C-\d+ ", section(spec, "## 17. ", "## 18. ")),
        "g_rows": count(r"^\| G-\d+ ", section(spec, "## 17. ", "## 18. ")),
        "oq_rows": count(r"^\| OQ-\d+ ", section(spec, "## 17. ", "## 18. ")),
        "events": len(EVENTS),
        "handoff_blocks": count(r"^## Handoff checklist", handoff),
        "densities_ui": 2,
        "densities_engine": 3,
        "badge_states": 4,
    }


# ---------------------------------------------------------------- self-test ----------------------------------
def in_section(text: str, start: str, end: str, fn: Callable[[str], str]) -> str:
    """Apply fn to the section slice only, so a mutation lands where its gate reads."""
    i = text.find(start)
    assert i >= 0, start
    j = text.find(end, i + len(start))
    j = j if j > 0 else len(text)
    return text[:i] + fn(text[i:j]) + text[j:]


def edit_row(sec: str, pattern: str, fn: Callable[[str], str]) -> str:
    """Rewrite the first table line of the section that matches pattern (Prettier-padded cells included)."""
    m = re.search(pattern, sec, MULTI)
    assert m is not None, pattern
    return sec[: m.start()] + fn(m.group(0)) + sec[m.end() :]


def set_cell(line: str, idx: int, value: str) -> str:
    cells = line.strip().strip("|").split("|")
    cells[idx] = f" {value} "
    return "|" + "|".join(cells) + "|"


def self_test(spec: str, handoff: str, tool: str, bindings: set[str]) -> list[str]:
    """Mutate the spec (or the hand-off) in memory; every mutation must trip its gate (A2: mutation-tested gates)."""
    problems: list[str] = []
    base = gates(spec, handoff, tool, bindings)
    if base:
        return ["self-test needs a passing baseline; gates failing: " + "; ".join(base)]

    def expect(name: str, mutated: str, needle: str, hand: str = handoff) -> None:
        got = gates(mutated, hand, tool, bindings)
        if not any(needle in g for g in got):
            problems.append(f"self-test: mutation '{name}' did not trip its gate ({needle})")

    inv = ("### 3.2 ", "## 4. ")
    expect("add a local path", spec + "\n/ho" + "me/someone/x.md\n", "hygiene: spec")
    expect(
        "add a design-tool host to the hand-off",
        spec,
        "hygiene: handoff",
        handoff + "\npenpot" + ".example" + ".com\n",
    )
    expect("add a closing keyword", spec + "\nCloses #360\n", "closing: spec")
    expect("add a placeholder word", spec + "\nTODO\n", "placeholder: spec")
    expect("state the T2 rule twice", spec + "\nThe one T2 rule\n", "not stated exactly once")
    expect(
        "drop the scale-link citation",
        in_section(spec, "## 7. ", "## 8. ", lambda t: t.replace("§10.3", "§10.4")),
        "scale-link section does not cite",
    )
    expect(
        "drop the Save citation",
        in_section(spec, "## 8. ", "## 9. ", lambda t: t.replace("§10.3", "§10.4")),
        "Save mention does not cite",
    )
    expect(
        "strip aria-disabled from the T2 statement",
        in_section(
            spec, "### 10.3 ", "## 11. ", lambda t: t.replace("aria-disabled", "aria-dis abled")
        ),
        "lacks its anatomy",
    )
    expect(
        "bind opacity.disabled on the T2 label",
        in_section(
            spec, "### 10.3 ", "## 11. ", lambda t: t + " The label takes `opacity.disabled`."
        ),
        "binds opacity.disabled",
    )
    expect(
        "swap the Save legs",
        in_section(spec, "## 8. ", "## 9. ", lambda t: t.replace("rbac.view_as", "rbac.view-as")),
        "view-as:",
    )
    expect(
        "remove the Esc sentence", re.sub(r"never (gated|locked)", r"sometimes \1", spec), "exits:"
    )
    expect(
        "un-PENDING a board row",
        in_section(
            spec,
            "## 0. ",
            "## 1. ",
            lambda t: edit_row(t, r"^\| 01 .*$", lambda ln: ln.replace("PENDING", "DRAWN")),
        ),
        "not PENDING",
    )
    first_frame = min(frame_names(section(spec, "## 0. ", "## 1. ")))
    expect(
        "drop a frame from section 0",
        in_section(
            spec,
            "## 0. ",
            "## 1. ",
            lambda t: t.replace(
                f"`{first_frame}`", "`" + first_frame.rsplit("/", 1)[0] + "/zz-gone`", 1
            ),
        ),
        "they differ",
    )
    expect(
        "change the hand-off frame count",
        spec,
        "named-frame count differs",
        re.sub(
            r"(\d+) named frames", lambda m: f"{int(m.group(1)) + 1} named frames", handoff, count=1
        ),
    )
    expect(
        "mark the account frame T2",
        in_section(
            spec,
            *inv,
            lambda t: edit_row(
                t,
                r"^\| `SCR-023/account-env-refused` .*$",
                lambda ln: ln.replace("absence", "T2 (lock glyph)"),
            ),
        ),
        "t2-frames:",
    )
    expect(
        "draw a lock on the popover frame",
        in_section(
            spec,
            *inv,
            lambda t: edit_row(
                t, r"^\| `SCR-023/popover-1280` .*$", lambda ln: ln.rstrip("| ") + " lock glyph |"
            ),
        ),
        "over-conversion: frame",
    )
    expect(
        "class the refusal as a gate",
        in_section(
            spec,
            *inv,
            lambda t: edit_row(
                t, r"^\| `SCR-043/link-refused` .*$", lambda ln: ln.replace("outcome", "gate")
            ),
        ),
        "refusal frame is not classed",
    )
    expect(
        "drop the conflict grammar",
        in_section(
            spec,
            *inv,
            lambda t: edit_row(
                t,
                r"^\| `SCR-023/conflict-interval` .*$",
                lambda ln: ln.replace("aligns by timestamp", "aligns by time"),
            ),
        ),
        "lacks the notice grammar",
    )
    expect(
        "keep the ticket armed after a sync symbol switch",
        in_section(
            spec,
            *inv,
            lambda t: edit_row(
                t,
                r"^\| `SCR-023/symbol-switch-disarm` .*$",
                lambda ln: re.sub(r"(?i)disarm", "keeps arm", ln),
            ),
        ),
        "does not draw the disarm",
    )
    expect(
        "drop the comfortable badge row",
        in_section(
            spec,
            "## 4. ",
            "## 5. ",
            lambda t: edit_row(
                t, r"^\| comfortable .*$", lambda ln: ln.replace("| comfortable ", "| roomy ", 1)
            ),
        ),
        "compact / comfortable row pair",
    )
    expect(
        "drop the validity sentence",
        spec.replace("no validity-disabled control", "no validity control"),
        "validity:",
    )
    expect(
        "drop the retention sentence",
        spec.replace("unsync is not a reset", "unsync is a reset"),
        "retention:",
    )
    expect(
        "mark Interval as stored",
        in_section(
            spec,
            "### 5.2 ",
            "### 5.3 ",
            lambda t: edit_row(
                t, r"^\| Interval .*$", lambda ln: ln.replace("storage pending", "stored")
            ),
        ),
        "Interval switch row lacks",
    )
    expect(
        "lock the account switch row",
        in_section(
            spec,
            "### 5.2 ",
            "### 5.3 ",
            lambda t: edit_row(t, r"^\| Account .*$", lambda ln: ln.rstrip("| ") + " lock glyph |"),
        ),
        "Account row is not a plain unavailable row",
    )
    expect(
        "mark percent as stored",
        in_section(spec, "### 7.4 ", "### 7.5 ", lambda t: t.replace("storage pending", "stored")),
        "percent suggestion lacks",
    )
    expect(
        "draw a PROPOSED chord as shipped",
        in_section(
            spec,
            "### 9.1 ",
            "### 9.2 ",
            lambda t: edit_row(t, r"^\| Join group .*$", lambda ln: set_cell(ln, 4, "shipped")),
        ),
        "not marked PROPOSED",
    )
    expect(
        "empty a parity keyboard cell",
        in_section(
            spec,
            "### 9.3 ",
            "### 9.4 ",
            lambda t: edit_row(t, r"^\| Click `\[Sync .*$", lambda ln: set_cell(ln, 1, "—")),
        ),
        "lacks a keyboard path",
    )
    expect(
        "drop the join consequence",
        in_section(
            spec,
            "### 10.2 ",
            "### 10.3 ",
            lambda t: edit_row(
                t,
                r"^\| AN-1 .*$",
                lambda ln: re.sub(
                    r" Symbol, crosshair and drawings are shared with 2 panels\.", "", ln
                ),
            ),
        ),
        "join string lacks",
    )
    expect(
        "drop a politeness",
        in_section(
            spec,
            "### 10.2 ",
            "### 10.3 ",
            lambda t: edit_row(t, r"^\| AN-1 .*$", lambda ln: set_cell(ln, 2, "loud")),
        ),
        "lacks its politeness",
    )
    expect(
        "drop an event",
        in_section(
            spec,
            "## 14. ",
            "## 15. ",
            lambda t: t.replace("`sync.conflict_shown", "`sync.conflict_hidden"),
        ),
        "events:",
    )
    expect(
        "un-PROPOSE a sync token",
        "\n".join(
            ln.replace("PROPOSED", "later") if "`color.sync.a`" in ln else ln
            for ln in spec.split("\n")
        ),
        "tokens:",
    )
    return problems


# ---------------------------------------------------------------- main ---------------------------------------
def p(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    fails: list[str] = []
    badge = badge_report()
    pop = popover_report()
    matrix = matrix_report(fails)
    cvd_rows = cvd_report()
    refusal = refusal_report()
    spec, handoff, tool = read(SPEC), read(HANDOFF), Path(__file__).read_text(encoding="utf-8")
    bindings = keymap_bindings()
    dark = theme("dark")
    tokens = {
        n: ("MISSING" if (n not in dark) else str(verify.resolve(dark[n]["$value"], dark)))
        for n in BOUND
    }
    missing = [n for n, v in tokens.items() if v == "MISSING"]
    if missing:
        fails.append("tokens: bound tokens missing from the dark set: " + ", ".join(missing))
    gate_fails = gates(spec, handoff, tool, bindings) if spec else ["spec missing"]
    fails.extend(gate_fails)
    c = counts(spec, handoff) if spec else {}
    st: list[str] = []
    if a.self_test and spec:
        st = self_test(spec, handoff, tool, bindings)
        fails.extend(st)
    cb, cf = badge["densities"]["compact"], badge["densities"]["comfortable"]
    markers: dict[str, Any] = {
        "popover_w": POPOVER_W,
        "popover_h_compact": pop["height"]["compact"],
        "popover_h_comfortable": pop["height"]["comfortable"],
        "popover_column_w": pop["column_w"],
        "zoom200_w": ZOOM200[0],
        "zoom200_h": ZOOM200[1],
        "zoom200_body_h_compact": pop["zoom200"]["body_h"]["compact"],
        "zoom200_visible_body": pop["zoom200"]["visible_body"],
        "modal_header": MODAL_HEADER,
        "modal_footer": MODAL_FOOTER,
        "text_scale_125_h": pop["text_scale_125"]["compact_h"],
        "text_scale_150_h": pop["text_scale_150"]["compact_h"],
        "canvas_1280_w": CANVAS_1280[0],
        "canvas_1280_h": CANVAS_1280[1],
        "canvas_1920_w": CANVAS_1920[0],
        "canvas_1920_h": CANVAS_1920[1],
        "row_compact": cb["row"],
        "row_comfortable": cf["row"],
        "badge_h_compact": cb["badge_h"],
        "badge_h_comfortable": cf["badge_h"],
        "tile_compact": cb["tile"],
        "tile_comfortable": cf["tile"],
        "glyph_compact": cb["glyph"],
        "glyph_comfortable": cf["glyph"],
        "badge_gap": cb["gap"],
        "badge_pad_compact": cb["pad_x"],
        "badge_pad_comfortable": cf["pad_x"],
        "badge_text_compact": cb["text"],
        "badge_text_comfortable": cf["text"],
        "badge_w_full_compact": cb["width"]["full"],
        "badge_w_one_compact": cb["width"]["one"],
        "badge_w_count_compact": cb["width"]["count"],
        "badge_w_none_compact": cb["width"]["none"],
        "badge_w_min_compact": cb["width"]["letter_glyph"],
        "badge_w_full_comfortable": cf["width"]["full"],
        "badge_w_one_comfortable": cf["width"]["one"],
        "badge_w_count_comfortable": cf["width"]["count"],
        "badge_w_none_comfortable": cf["width"]["none"],
        "badge_w_min_comfortable": cf["width"]["letter_glyph"],
        "d02_min_count": D02_MIN["A · 1"],
        "d02_min_one": D02_MIN["A · symbol"],
        "d02_min_full": D02_MIN["A · symbol, crosshair, drawings"],
        "d02_min_via": D02_MIN["via A"],
        "kind_minimum_delta": badge["kind_minimum_delta"],
        "min_w_chart_d02": 328,
        "min_w_dom_d02": 380,
        "min_w_tape_d02": 232,
        "min_w_chart": 328 + badge["kind_minimum_delta"],
        "min_w_dom": 380 + badge["kind_minimum_delta"],
        "min_w_tape": 232 + badge["kind_minimum_delta"],
        "btc": PRICES["BTCUSDT"],
        "eth": PRICES["ETHUSDT"],
        "sol": PRICES["SOLUSDT"],
        "btc_sol_ratio": refusal["btc_sol"]["ratio"],
        "btc_sol_about": refusal["btc_sol"]["about"],
        "btc_sol_decades": refusal["btc_sol"]["decades"],
        "btc_eth_ratio": refusal["btc_eth"]["ratio"],
        "btc_eth_decades": refusal["btc_eth"]["decades"],
        "eth_sol_ratio": refusal["eth_sol"]["ratio"],
        "eth_sol_decades": refusal["eth_sol"]["decades"],
        "threshold_decades": THRESHOLD_DECADES,
        "opacity_muted": float(tok("opacity.muted")),
        "matrix_gated": matrix["gated"],
        "matrix_failed": matrix["failed"],
        "matrix_pairs": len(PAIRS),
        "remote_bgs": len(REMOTE_BGS),
        "cvd_kinds": 4,
        "cvd_min_de_dark": cvd_rows["min_de"]["dark"],
        "cvd_min_de_light": cvd_rows["min_de"]["light"],
        "tokens_bound": len(BOUND),
        "tokens_missing": len(missing),
        "tokens_proposed": len(PROPOSED_TOKENS),
        "glyphs_proposed": len(PROPOSED_GLYPHS),
        "events": len(EVENTS),
        "t2_frames_expected": len(T2_FRAMES),
        **{f"count_{k}": v for k, v in c.items()},
    }
    out = {
        "badge": badge,
        "popover": pop,
        "matrix": matrix,
        "cvd": cvd_rows,
        "refusal": refusal,
        "tokens": tokens,
        "sync_alias": SYNC_ALIAS,
        "counts": c,
        "gates": gate_fails,
        "self_test": st,
        "fails": fails,
        "markers": markers,
    }
    if a.json:
        p(json.dumps(out, indent=2, ensure_ascii=False))
    elif a.table:
        p(matrix_table(matrix))
    else:
        p(
            "1. BADGE GEOMETRY (D-1, PROPOSED; widths from the pill-label rule; E15-D02 §3 minimums quoted)"
        )
        for dens, g in badge["densities"].items():
            p(
                f"  {dens:12s} row {g['row']} badge {g['badge_h']} tile {g['tile']} glyph {g['glyph']} gap {g['gap']} pad {g['pad_x']} text {g['text']} px; widths: full {g['width']['full']}, one axis {g['width']['one']}, count {g['width']['count']}, No sync {g['width']['none']}, letter+glyph {g['width']['letter_glyph']}"
            )
        p(
            f"  E15-D02 §3 (quoted): {badge['d02_minimums']}; delta compact vs D02: {badge['delta_vs_d02']}; kind-minimum delta {badge['kind_minimum_delta']} px"
        )
        p("2. POPOVER GEOMETRY (D-3, D-4)")
        p(
            f"  width {pop['width']} pad {pop['pad']} column {pop['column_w']}; height compact {pop['height']['compact']} comfortable {pop['height']['comfortable']}; fits 1280x800 canvas {CANVAS_1280}: {pop['fits_1280']}"
        )
        z = pop["zoom200"]
        p(
            f"  200 %: viewport {z['viewport']} -> modal {z['modal']}; stacked body {z['body_h']} vs visible {z['visible_body']} (header {z['header']}, footer {z['footer']}) -> scrolls {z['scrolls']}"
        )
        p(f"  text scale 125 %: {pop['text_scale_125']}; 150 %: {pop['text_scale_150']}")
        p(
            "3. MEASURED MATRIX (resolved as verify_tokens layers themes; contrast_check.contrast_ratio)"
        )
        p(matrix_table(matrix))
        p(f"  gated {matrix['gated']}, failed {matrix['failed']}; reproductions {matrix['repro']}")
        p("4. CVD ROWS (dE76 between the three group hues; reported, never a FAIL)")
        for th, kinds in cvd_rows["pairs"].items():
            p(f"  {th}: hues {cvd_rows['hues'][th]}")
            for kind, v in kinds.items():
                p(
                    f"    {kind:12s} a-b {v['a-b']} a-c {v['a-c']} b-c {v['b-c']}  simulated {v['simulated']}"
                )
        p(f"  minimum dE per theme: {cvd_rows['min_de']}")
        p("5. REFUSAL ARITHMETIC (fixture prices; threshold one decade)")
        for k in ("btc_sol", "btc_eth", "eth_sol"):
            r = refusal[k]
            p(
                f"  {r['a']} {r['price_a']} / {r['b']} {r['price_b']} = {r['ratio']} (about {r['about']}x), {r['decades']} decades -> {'refused' if r['refused'] else 'linked'}"
            )
        p(
            f"TOKENS: {len(BOUND)} bound, {len(missing)} missing ({', '.join(missing) or 'none'}); PROPOSED {list(PROPOSED_TOKENS)} aliased to {list(SYNC_ALIAS.values())}; PROPOSED glyphs {list(PROPOSED_GLYPHS)}"
        )
        p("COUNTS: " + (", ".join(f"{k} {v}" for k, v in c.items()) or "spec missing"))
        p("GATES: " + ("all pass" if not gate_fails else "; ".join(gate_fails)))
        if a.self_test:
            p("SELF-TEST: " + ("every mutation tripped its gate" if not st else "; ".join(st)))
        p("RESULT: " + ("PASS" if not fails else "FAIL — " + "; ".join(fails)))
    return 1 if (a.check or a.self_test) and fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
