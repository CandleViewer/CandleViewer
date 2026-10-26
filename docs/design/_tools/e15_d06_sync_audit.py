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
2. Popover geometry (D-3, D-4): the 440 px popover's row stack per density from the label fit
   of every switch (the label at 13 px and its consequence line at 11 px measured against the
   column or full-width box with the pill-label rule; a label never wraps, a consequence line
   may and the row grows), its height, the 1280x800 canvas it must fit (E15-D02 section 3:
   1168x672) and the 200 % zoom viewport (640x400 CSS px) where it becomes a modal inside the
   272 px body between the 80 px TopBar and the 48 px StatusBar, capped at it less 16 px a side
   (E15-D02 D-7 and :632; never over the bars or the banner band), with one column, a sticky
   footer and a scrolling body; the in-app text scale at 125 % and 150 %,
   measured the same way (the rule is the measurement, not the zoom level).
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
   conflict grammar on every conflict frame; the badge density pair; exits never gated; a DOM or
   ticket in a symbol-sharing group never without its provenance; an armed state never drawn
   surviving a sync symbol change (the disarm or the held alternative beside it); section 5.1
   quotes the computed heights.
9. The counts (``--json``) the boards and the PR quote.
10. Frame-keyed gates (8b; the A2 list): each element is required on the state-inventory rows
    that draw it, by frame id -- the letter and the `link` glyph beside every group colour; the
    full conflict sentence and the `warning` glyph on every conflict frame; the one T2's anatomy
    (lock, full label, reason, key, ``aria-disabled``) on its three frames and the T2 form on no
    other row (A1); PROPOSED after every drawn chord that ``keymap.json`` lacks; the disarm on
    every symbol-switch frame, with no armed state surviving (BQ-16) -- neither a "stays armed"
    phrase nor the arm-state tag (`ARMED` bare, ``Armed`` bare, backticked in any case, or "reads /
    is / held: armed"), the one form allowed being the hold inset's own "BTCUSDT · held: armed ("
    line, exactly and only on the hold frame; the Gate-class cell scanned for every T2 form
    except the ``T2`` word itself (the t2-frames check's); a needle counts only un-negated ("no
    lock glyph" is not the lock glyph), and PROPOSED qualifies a chord only with no other control
    or "or" between; each frame's exits in the inventory's Exits column, all T1 and never paired
    with a gate (A3).
11. Numbers (8c): the ``audit:`` block at the end of the spec equals ``--json``'s markers; the
    registered prose contexts, the section 4.1 and section 12 tables and the CVD paragraph are
    re-derived; every two-decimal ratio and ratio triple in the spec and the hand-off is one
    the tool derives.

Usage: python3 -I docs/design/_tools/e15_d06_sync_audit.py [--json] [--check] [--table] [--self-test]
A plain run prints every section and exits 0; ``--check`` exits 1 on any gated FAIL; ``--self-test``
mutates the spec in memory and proves that every gate fails on its mutation, and runs the frame-level
``MUTATIONS`` table: each mutation trips its own FAIL message exactly once and no other FAIL (every
inline mutation too: its gate's FAIL is the only one), the files untouched;
``--table`` prints section 3 as a Markdown table. UTF-8 stdout. No network; no URL literal
anywhere in this file.
"""

from __future__ import annotations

import argparse
import functools
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

# ---- popover geometry (spec D-3, D-4). The fixed rows per density (name, compact px,
# comfortable px); the switch rows are COMPUTED from the label fit below (the pre-PR lens round
# 1, F-3: a switch label or its consequence line is measured against its box with the pill-label
# rule, never assumed to fit). ----
POPOVER_W = 440  # E15-D02 D-25: 440 px wide at both widths
POPOVER_PAD = 16  # space.inset.md
POPOVER_FIXED_TOP: tuple[tuple[str, int, int], ...] = (
    ("title row: This panel · Group radio", 24, 32),
    ("gap", 8, 12),
    ("heading: Group A shares", 16, 20),
)
POPOVER_FIXED_BOTTOM: tuple[tuple[str, int, int], ...] = (
    ("gap", 8, 8),
    ("members line: Panels in group A", 16, 20),
    ("conflict notice (two caption lines)", 36, 40),
    ("rule + gaps", 17, 17),
    ("heading: Price scale, per panel", 16, 20),
    ("scale select rows (x2)", 56, 72),
)
# A switch row = the CMP-004 track row + the consequence line(s) + a gap. The label is
# `type.ui.body` (13 px, `font.size.base`), the consequence line `type.ui.caption` (11 px,
# `font.size.xs`); the caption's line box is 16 px (11 x 1.38 rounded up) in compact and 18 in
# comfortable (2 px of leading). The track row (24 / 32, `size.control.height`), the gap and the
# padding are spacing tokens and do not scale with the in-app text scale; the text sizes and the
# line boxes do.
SWITCH_H = {"compact": 24, "comfortable": 32}
SWITCH_TEXT = {"label": 13, "consequence": 11}
CAPTION_LINE = {"compact": 16, "comfortable": 18}
SWITCH_ROW_GAP = 4
SWITCH_TRACK_W = 36  # the 28 px track + the 8 px gap before the label
# (label, consequence line as drawn on the AD-4 default frame, placement). "column" switches
# pair up in the two columns; "full" switches take the full inner width — Drawings (same symbol
# only) and the account row, whose labels (219 / 186 px at 13 px) never fit a 160 px column box
# (D-4).
SWITCHES: tuple[tuple[str, str, str], ...] = (
    ("Symbol", "2 panels will follow this panel's symbol.", "column"),
    ("Crosshair", "Crosshair aligns by timestamp on 2 panels.", "column"),
    ("Interval", "Each panel keeps its own interval.", "column"),
    ("Time range", "Pan and zoom move 2 panels together.", "column"),
    ("Drawings (same symbol only)", "Only panels on BTCUSDT share drawings (1 of 2).", "full"),
    ("Account and trade group", "Can't sync yet; a layout never stores an account.", "full"),
)
CANVAS_1280 = (1168, 672)  # E15-D02 section 3: the canvas at 1280x800
CANVAS_1920 = (1808, 952)
ZOOM200 = (640, 400)  # 1280x800 at 200 %: the CSS viewport
# E15-D02 section 3 (:85, :171): the 80 px TopBar (ENV badge, Safety cluster) and the 48 px
# StatusBar (ENV repeat). CSS px do not scale with zoom, so at 200 % they keep 80 + 48 of the
# 400 px viewport; E15-D02 D-7 (:125) keeps both, and the banner band, out of any scrim or modal.
TOPBAR_H = 80
STATUSBAR_H = 48
MODAL_MARGIN = 16  # kept around a popover before it becomes a modal (E15-D02 :632, a side)
MODAL_HEADER = 32
MODAL_FOOTER = 40
TEXT_SCALES = (125, 150)  # the in-app text scale steps the spec measures

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


def label_w(label: str, size: float) -> int:
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
Switches = tuple[tuple[str, str, str], ...]


def popover_layout(
    dens: str,
    scale: int = 100,
    width: int = POPOVER_W,
    columns: int = 2,
    switches: Switches = SWITCHES,
) -> dict[str, Any]:
    """The row stack at a density, an in-app text scale (%), a width and a column count.

    Every switch row is sized from the fit of its label and its consequence line in their boxes
    (the pill-label rule); a label that needs more than one line is a FAIL the gate reports; a
    consequence line may wrap and the row grows with it. One column (the 200 % modal) gives
    every switch the full width.
    """
    k = scale / 100
    label_px, cons_px = SWITCH_TEXT["label"] * k, SWITCH_TEXT["consequence"] * k
    inner = width - 2 * POPOVER_PAD
    col_w = (inner - POPOVER_PAD) // 2 if columns == 2 else inner
    boxes = {"column": col_w - SWITCH_TRACK_W, "full": inner - SWITCH_TRACK_W}
    line_h = math.ceil(CAPTION_LINE[dens] * k)
    fits: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    # the row's top is the track row, or the label's own line box (+ 6 px) once a scaled label
    # outgrows it
    top = max(SWITCH_H[dens], math.ceil(label_px * 1.38) + 6)

    def push(items: list[dict[str, Any]]) -> None:
        lines = max(it["cons_lines"] for it in items)
        rows.append(
            {
                "row": "switch row: " + " | ".join(it["label"] for it in items),
                "px": top + lines * line_h + SWITCH_ROW_GAP,
                "lines": lines,
                "top": top,
            }
        )

    for label, cons, place in switches:
        kind = place if columns == 2 else "full"
        box = boxes[kind]
        lw, cw = label_w(label, label_px), label_w(cons, cons_px)
        it = {
            "label": label,
            "place": kind,
            "box": box,
            "label_w": lw,
            "label_lines": max(1, math.ceil(lw / box)),
            "cons_w": cw,
            "cons_lines": max(1, math.ceil(cw / box)),
        }
        fits.append(it)
        if kind == "column":
            pending.append(it)
            if len(pending) == 2:
                push(pending)
                pending = []
        else:
            if pending:
                push(pending)
                pending = []
            push([it])
    if pending:
        push(pending)

    def fixed(rows_: tuple[tuple[str, int, int], ...]) -> list[dict[str, Any]]:
        return [
            {"row": n, "px": math.ceil((c if dens == "compact" else f) * k)} for n, c, f in rows_
        ]

    fixed_top, fixed_bottom = fixed(POPOVER_FIXED_TOP), fixed(POPOVER_FIXED_BOTTOM)
    all_rows = fixed_top + rows + fixed_bottom
    height = 2 * POPOVER_PAD + sum(int(r["px"]) for r in all_rows)
    # the modal body: everything under the title row (which the 32 px modal header replaces) and
    # its gap
    body = 2 * POPOVER_PAD + sum(int(r["px"]) for r in all_rows[2:])
    return {
        "density": dens,
        "scale": scale,
        "width": width,
        "columns": columns,
        "column_w": col_w,
        "boxes": boxes,
        "fits": fits,
        "rows": all_rows,
        "switch_rows": rows,
        "height": height,
        "body": body,
        "label_overflows": [f for f in fits if f["label_lines"] > 1],
    }


def popover_report(switches: Switches = SWITCHES) -> dict[str, Any]:
    out: dict[str, Any] = {"width": POPOVER_W, "pad": POPOVER_PAD, "rows": [], "layouts": {}}
    lay = {d: popover_layout(d, switches=switches) for d in ("compact", "comfortable")}
    for r_c, r_f in zip(lay["compact"]["rows"], lay["comfortable"]["rows"], strict=True):
        out["rows"].append({"row": r_c["row"], "compact": r_c["px"], "comfortable": r_f["px"]})
    hc, hf = lay["compact"]["height"], lay["comfortable"]["height"]
    out["height"] = {"compact": hc, "comfortable": hf}
    out["column_w"] = lay["compact"]["column_w"]
    out["boxes"] = lay["compact"]["boxes"]
    out["switch_rows"] = {
        d: {
            "column": next(r["px"] for r in lay[d]["switch_rows"] if "|" in r["row"]),
            "full": next(r["px"] for r in lay[d]["switch_rows"] if "|" not in r["row"]),
        }
        for d in lay
    }
    out["fits"] = {d: lay[d]["fits"] for d in lay}
    out["fits_1280"] = {
        "compact": hc + 2 * MODAL_MARGIN <= CANVAS_1280[1],
        "comfortable": hf + 2 * MODAL_MARGIN <= CANVAS_1280[1],
    }
    out["fits_1920"] = {
        "compact": hc + 2 * MODAL_MARGIN <= CANVAS_1920[1],
        "comfortable": hf + 2 * MODAL_MARGIN <= CANVAS_1920[1],
    }
    # 200 %: the CSS viewport is 640x400 and the TopBar (80) and the StatusBar (48) stay, so the
    # body between them is 272 px (E15-D02 D-7: no scrim or modal covers the bars or the banner
    # band); the popover (437 + 2 x 16 margin) cannot fit it -> a modal inside that body, capped
    # at it less 16 px a side (E15-D02 :632); one column (every switch full width, every line
    # single), a sticky footer, the body scrolls.
    between = ZOOM200[1] - TOPBAR_H - STATUSBAR_H
    modal_w, modal_h = ZOOM200[0] - 2 * MODAL_MARGIN, between - 2 * MODAL_MARGIN
    modal = {d: popover_layout(d, 100, modal_w, 1, switches=switches) for d in lay}
    visible = modal_h - MODAL_HEADER - MODAL_FOOTER
    out["zoom200"] = {
        "viewport": list(ZOOM200),
        "topbar": TOPBAR_H,
        "statusbar": STATUSBAR_H,
        "between_bars": between,
        "modal_w": modal_w,
        "modal_h": modal_h,
        "modal": hc + 2 * MODAL_MARGIN > between or POPOVER_W + 2 * MODAL_MARGIN > ZOOM200[0],
        "body_h": {d: modal[d]["body"] for d in modal},
        "visible_body": visible,
        "scrolls": {d: modal[d]["body"] > visible for d in modal},
        "header": MODAL_HEADER,
        "footer": MODAL_FOOTER,
        "switch_row": modal["compact"]["switch_rows"][0]["px"],
    }
    # the in-app text scale: the boxes stay, the text grows, the lines wrap more; a popover while it
    # fits the 1280x800 canvas
    for pct in TEXT_SCALES:
        at = popover_layout("compact", pct, switches=switches)
        h = at["height"]
        out[f"text_scale_{pct}"] = {
            "compact_h": h,
            "fits_1280": h + 2 * MODAL_MARGIN <= CANVAS_1280[1],
            "popover": h + 2 * MODAL_MARGIN <= CANVAS_1280[1],
            # when it cannot, the modal takes the canvas between the bars less 16 px a side
            "modal_h": CANVAS_1280[1] - 2 * MODAL_MARGIN,
            "max_cons_lines": max(int(f["cons_lines"]) for f in at["fits"]),
            "label_overflows": [f["label"] for f in at["label_overflows"]],
        }
    out["label_overflows"] = {
        f"{d} {pct} %": [
            f["label"] for f in popover_layout(d, pct, switches=switches)["label_overflows"]
        ]
        for d in lay
        for pct in (100, *TEXT_SCALES)
    }
    out["label_overflows"]["modal 200 %"] = [
        f["label"] for f in modal["compact"]["label_overflows"]
    ]
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
        d, lt, h = ths["dark"], ths["light"], ths["high-contrast"]
        gate = (
            (
                "reported"
                + (
                    ""
                    if d["bar"] is None
                    else (" — PASS" if all(x["pass"] for x in (d, lt, h)) else " — below the bar")
                )
            )
            if d["gate"] == "report" or d["bar"] is None
            else ("PASS" if all(x["pass"] for x in (d, lt, h)) else "FAIL")
        )
        lines.append(
            f"| {element}: `{d['fg']}` on `{d['bg']}` | {d['role']} | {_cell(d)} | {_cell(lt)} | {_cell(h)} | {gate} |"
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
        d, lt, h = ths["dark"], ths["light"], ths["high-contrast"]
        tt = f"{fmt(d['best_of_two_tone'])} / {fmt(lt['best_of_two_tone'])} / {fmt(h['best_of_two_tone'])}; {fmt(d['dash_vs_halo'])} / {fmt(lt['dash_vs_halo'])} / {fmt(h['dash_vs_halo'])}"
        gate = (
            "PASS"
            if d["gate"] == "gated" and all(x["pass"] for x in (d, lt, h))
            else (
                "reported; two-tone "
                + ("PASS" if all(x["two_tone_pass"] for x in (d, lt, h)) else "FAIL")
            )
        )
        lines.append(
            f"| `{bg}` | {fmt(d['ratio'])} | {fmt(lt['ratio'])} | {fmt(h['ratio'])} | {tt} | {gate} |"
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


# -------------------------------------------------------- 8b. frame-keyed gates (A1-A3) --------
# Every A2 gate reads the frame rows that draw its element, never a ruling sentence anywhere in the
# file: removing the element from one frame row fails that frame by name.
SENTENCE = "Chart 15m has a different interval: crosshair sync aligns by timestamp."
# frame -> the group letters it draws beside their hues (each needs "letter X" and the `link` glyph)
BADGE_FRAMES: dict[str, str] = {
    "CMP-082/badge-a-compact": "A",
    "CMP-082/badge-b-compact": "B",
    "CMP-082/badge-c-compact": "C",
    "CMP-082/badge-a-comfortable": "A",
    "CMP-082/badge-narrow-steps": "A",
    "CMP-082/badge-forced-colors": "A",
    "CMP-082/badge-greyscale": "ABC",
    "CMP-082/chart-toolbar-badge": "A",
    "SCR-023/light-badges": "ABC",
    "SCR-023/join-after": "A",
}
HUE_LETTER = {"cyan": "A", "amber": "B", "purple": "C"}
NO_SYNC_CARRIERS = (("the `unlink` glyph", "`unlink`"), ("the words", '"No sync"'))
CONFLICT_FRAMES: dict[str, tuple[tuple[str, str], ...]] = {
    "SCR-023/conflict-interval": (("its polite announcement", "AN-5"),),
    "CMP-082/conflict-header": (("its never-a-toast clause", "never a toast alone"),),
    "SCR-023/light-conflict": (("its polite announcement", "AN-5"),),
}
_T2_LINK = (
    ("the lock glyph", "lock glyph"),
    ("the full label", "full label"),
    ("the reason", '"Join a sync group to link its scale."'),
    ("the state key", "`scale.link.no_group`"),
    ("aria-disabled", "`aria-disabled`"),
    ("the second line", "as the second line"),
    ("the re-shown reason", "AN-11"),
)
T2_ANATOMY: dict[str, tuple[tuple[str, str], ...]] = {
    "SCR-043/link-no-group": (
        *_T2_LINK,
        ("arrow reach", "arrow-reachable"),
        ("the state path", "`disabledReason`"),
        ("the label token", "`color.text.tertiary`"),
        ("the reason token", "`color.text.secondary`"),
    ),
    "SCR-043/light-link-no-group": _T2_LINK,
    "SCR-023/dirty-save-view-as": (
        ("the lock glyph", "lock glyph"),
        ("the full label", 'full label "Save"'),
        ("aria-disabled", "`aria-disabled`"),
        ("the label token", "`color.text.tertiary`"),
        ("the raised fill", "`color.surface.raised` fill"),
        ("the view-as key", "`rbac.view_as`"),
        ("the banner's notice", "banner"),
        ("CMP-079 on the role leg", "CMP-079 on the role leg"),
        ("the nothing-sent key", "nothing sent"),
    ),
}
DISARM: dict[str, tuple[tuple[str, str], ...]] = {
    "SCR-023/symbol-switch-disarm": (
        ("the DOM's disarm", '"ETHUSDT · symbol set by sync group A" and `LOCKED`'),
        ("the chart's disarm", "CMP-221 arm reads `LOCKED`"),
        ("the drawn-outcome clause", "the disarm is the drawn outcome"),
        ("the assertive disarm", "assertive the disarm (AN-3, AN-4)"),
    ),
    "SCR-023/symbol-switch-hold": (
        ("the disarm on [Follow group]", "[Follow group], which disarms and follows"),
        ("the follow announcement", "[Follow group] → AN-4's disarm"),
        ("the inset", "as an inset"),
    ),
}
ARMED_SURVIVES = re.compile(
    r"\b(?:still|stays|remains?|kept|left|keeps(?: it)?) `?armed\b|\barmed`? and follow|\bre-arm",
    re.IGNORECASE,
)
# M-1 (text round 1, BQ-16): the spec family's arm-state tag (`ARMED` / `LOCKED`, E15-D02 :186;
# the board script's arm: "ARMED") on a symbol-switch frame is an armed state surviving the sync
# change: bare `ARMED` or `Armed`, backticked in any case, or a short phrase ("reads armed", "is
# armed", "held: armed"; m-6). M-1r: the one form allowed is the hold inset's own old-symbol line,
# exact and case-sensitive, once, on the hold frame only.
ARMED_TAG = re.compile(
    r"(?i:`armed`)|\bARMED\b|\bArmed\b|(?i:\b(?:reads?|is|are|shows?|now|held:)\s+`?armed\b)"
)
HOLD_INSET = ("SCR-023/symbol-switch-hold", "BTCUSDT · held: armed (")
# m-2: a gate needle counts only where it is not negated ("no lock glyph" is not the lock glyph)
NEGATED = re.compile(r"(?:\bno|\bnot|\bwithout|\bnever)\W+(?:\w+\W+)?$", re.IGNORECASE)


def present(text: str, needle: str) -> str:
    """'yes' if the needle occurs un-negated, 'negated' if only negated, 'no' if absent."""
    hits = [m.start() for m in re.finditer(re.escape(needle), text)]
    if not hits:
        return "no"
    if any(not NEGATED.search(text[max(0, i - 16) : i]) for i in hits):
        return "yes"
    return "negated"


def clause_at(text: str, i: int) -> str:
    """The clause around offset i (between ';', '|' or '—'), for a FAIL message."""
    a = max(text.rfind(c, 0, i) for c in ";|\u2014") + 1
    ends = [j for j in (text.find(c, i) for c in ";|\u2014") if j >= 0]
    return text[a : min(ends) if ends else len(text)].strip()


DIALOG_CARRIERS: dict[str, tuple[tuple[str, str], ...]] = {
    "SCR-043/link-refused": (
        ("the focused primary", "`[[ Use percentage scale ]]` focused"),
        ("the Cancel exit", "`[ Cancel ]`"),
    ),
}
# A3: each frame's exits (the inventory's last column), by surface kind; every one T1
EXIT_NEEDLES: dict[str, tuple[str, ...]] = {
    "panel": ("No sync", "`Esc`"),
    "panel-none": ("`Esc`",),
    "popover": ("\u00d7", "`Esc`", "No sync", "Independent"),
    "popover-none": ("\u00d7", "`Esc`"),
    "modal": ("Close", "`Esc`", "No sync", "Independent"),
    "axis-linked": ("Independent", "No sync", "`Esc`"),
    "menu-checked": ("Independent", "`Esc`"),
    "menu": ("`Esc`",),
    "dialog": ("Cancel", "`Esc`"),
    "view-as": ("No sync", "Independent", "\u00d7", "`Esc`"),
}
EXIT_KIND: dict[str, str] = {
    "CMP-082/badge-none-compact": "panel-none",
    **{
        f"CMP-082/{n}": "panel"
        for n in (
            "badge-a-compact",
            "badge-b-compact",
            "badge-c-compact",
            "badge-a-comfortable",
            "badge-narrow-steps",
            "badge-forced-colors",
            "badge-greyscale",
            "chart-toolbar-badge",
            "conflict-header",
        )
    },
    **{
        f"SCR-023/{n}": "popover"
        for n in (
            "popover-1920",
            "popover-1280",
            "popover-text-scale-125",
            "conflict-interval",
            "drawings-cross-symbol",
            "account-env-refused",
            "light-conflict",
        )
    },
    "SCR-023/popover-no-sync": "popover-none",
    "SCR-023/modal-200pct": "modal",
    **{
        f"SCR-043/{n}": "axis-linked"
        for n in ("axis-linked", "axis-linked-locked", "linked-zoom-before", "linked-zoom-after")
    },
    "SCR-043/percent-result": "axis-linked",
    "SCR-043/axis-independent": "panel",
    "SCR-043/menu-link-checked": "menu-checked",
    "SCR-043/menu-link-unchecked": "menu",
    "SCR-043/link-no-group": "menu",
    "SCR-043/light-link-no-group": "menu",
    "SCR-043/link-refused": "dialog",
    "SCR-043/link-refused-btc-eth": "dialog",
    "SCR-043/light-link-refused": "dialog",
    "SCR-023/join-before": "panel-none",
    "SCR-023/leave-after": "panel",
    **{
        f"SCR-023/{n}": "panel"
        for n in (
            "join-after",
            "symbol-switch-disarm",
            "symbol-switch-hold",
            "crosshair-remote-compact",
            "crosshair-remote-comfortable",
            "crosshair-remote-dense",
            "crosshair-remote-footprint",
            "crosshair-readout-engine",
            "light-badges",
            "light-crosshair-footprint",
        )
    },
    "SCR-023/dirty-save-view-as": "view-as",
}
EXIT_GATED = re.compile(
    r"lock|aria-disabled|\bT2\b|CMP-079|rbac\.|disabledReason|\bblocked\b|\bdisabled\b|"
    r"(?<!never )\bgated\b",
    re.IGNORECASE,
)
EXIT_NEAR_GATE = re.compile(
    r"(?:\u00d7|`Esc`|No sync|Independent|Cancel|Close)[^;.|]{0,40}?"
    r"\b(?:locked|lock glyph|aria-disabled|disabled|blocked|(?<!never )gated)\b"
)
# A1: the T2 form only on the three T2 frames (and the account absence's aria-disabled)
T2_FORM = re.compile(
    r"lock glyph|`lock`|\bpadlock\b|CMP-079|disabledReason|rbac\.[a-z_]+|\bT2\b|aria-disabled"
)
T2_FORM_ALLOWED = ("not a T2", "no lock", "no CMP-079")
CHORD = re.compile(
    r"(?:Ctrl|Alt|Shift|Meta|Cmd)\+[A-Za-z0-9←→↑↓]+(?:\+[A-Za-z0-9←→↑↓]+)*(?:\.\.\d)?"
)


def chords_in(text: str) -> list[tuple[str, int, list[str]]]:
    """Each chord with its end offset and its expansion (``Ctrl+Shift+1..3`` -> three chords)."""
    out: list[tuple[str, int, list[str]]] = []
    for m in CHORD.finditer(text):
        c = m.group(0)
        r = re.fullmatch(r"(.*\+)(\d)\.\.(\d)", c)
        exp = (
            [f"{r.group(1)}{k}" for k in range(int(r.group(2)), int(r.group(3)) + 1)] if r else [c]
        )
        out.append((c, m.end(), exp))
    return out


def letter_drawn(text: str, x: str) -> bool:
    return re.search(rf"\bletters? (?:[ABC](?: / |, | and ))*{x}\b", text) is not None


def frame_gates(spec: str, bindings: set[str]) -> list[str]:
    fails: list[str] = []
    inv = inventory_rows(spec)
    by = {r[0].strip("`"): r for r in inv}
    for name, r in by.items():
        text = " | ".join(r)
        # A2-1: the letter and the glyph beside every group colour, per frame
        need = set(BADGE_FRAMES.get(name, ""))
        need |= {HUE_LETTER[h] for h in HUE_LETTER if re.search(rf"\b{h}\b", text)}
        need |= set(re.findall(r"\btile ([ABC])\b", text))
        need |= set(re.findall(r'"([ABC]) · ', text))
        for x in sorted(need):
            if not letter_drawn(text, x):
                fails.append(f"badge: frame {name} draws group {x}'s colour without its letter")
        if need and "`link`" not in text:
            fails.append(f"badge: frame {name} draws a group colour without the `link` glyph")
        # A2-2: the conflict grammar, the glyph and the frame's own carrier, per conflict frame
        if (
            name in CONFLICT_FRAMES
            or "conflict" in name
            or re.search(r"different interval|aligns by timestamp", text)
        ):
            if SENTENCE not in text:
                fails.append(f"conflict: frame {name} lacks the full notice sentence")
            if "`warning` glyph" not in text:
                fails.append(f"conflict: frame {name} lacks the `warning` glyph")
            for label, needle in CONFLICT_FRAMES.get(name, ()):
                if needle not in text:
                    fails.append(f"conflict: frame {name} lacks {label}")
        # A2-3: the one T2's anatomy on each T2 frame; A1: the T2 form nowhere else
        for label, needle in T2_ANATOMY.get(name, ()):
            seen_ = present(text, needle)
            if seen_ == "no":
                fails.append(f"t2-anatomy: frame {name} lacks {label}")
            elif seen_ == "negated":
                fails.append(f"t2-anatomy: frame {name} negates {label} ('{needle}')")
        if name not in T2_ANATOMY:
            # the Gate-class cell's `T2` word is gated exactly by the t2-frames check, and a lock
            # glyph or CMP-079 by the over-conversion check: neither is reported twice here; every
            # other T2 form in the Gate-class cell is (m-5)
            body = " | ".join(re.sub(r"\bT2\b", "", c) if i == 3 else c for i, c in enumerate(r))
            for ok in T2_FORM_ALLOWED:
                body = body.replace(ok, "")
            for m in T2_FORM.finditer(body):
                tok_ = m.group(0)
                if tok_ == "aria-disabled" and "account row" in body:
                    continue  # the account axis: an absence, aria-disabled without a lock (D-9)
                if tok_ in ("lock glyph", "CMP-079"):
                    continue  # the over-conversion check's (one FAIL per element)
                fails.append(f"t2-form: frame {name} draws '{tok_}' outside the three T2 frames")
        # A2-5 (BQ-16): the disarm on every symbol-switch frame; no armed state survives
        for label, needle in DISARM.get(name, ()):
            if needle not in text:
                fails.append(f"disarm: frame {name} lacks {label}")
        surviving = (
            name in DISARM
            or "symbol-switch" in name
            or "ETHUSDT · symbol set by sync group" in text
        )
        if "symbol-switch" in name and name not in DISARM:
            fails.append(f"disarm: frame {name} is a symbol-switch frame the tool does not key")
        scan = text.replace(HOLD_INSET[1], "", 1) if name == HOLD_INSET[0] else text
        tag = ARMED_TAG.search(scan) if surviving else None
        if tag:
            snip = clause_at(scan, tag.start())
            fails.append(
                f"armed-tag: frame {name} draws an armed tag after the sync change ('{snip}')"
            )
        elif surviving and ARMED_SURVIVES.search(scan):
            fails.append(f"armed: frame {name} draws an armed state surviving the sync change")
        for label, needle in DIALOG_CARRIERS.get(name, ()):
            if needle not in text:
                fails.append(f"dialog: frame {name} lacks {label}")
        # A3: every frame names its exits, all T1; no exit is paired with a gate anywhere in the row
        kind = EXIT_KIND.get(name)
        exits = r[-1] if len(r) > 5 else ""
        if kind is None:
            fails.append(f"exits: frame {name} has no exit kind in the tool")
        else:
            for needle in EXIT_NEEDLES[kind]:
                if needle not in exits:
                    fails.append(f"exits: frame {name} does not draw its exit {needle}")
        if "T1" not in exits:
            fails.append(f"exits: frame {name} does not class its exits T1")
        if EXIT_GATED.search(exits):
            fails.append(f"exits: frame {name} gates an exit in its Exits cell")
        hit = EXIT_NEAR_GATE.search(text)
        if hit:
            fails.append(f"exits: frame {name} gates an exit ('{hit.group(0)}')")
    for name in sorted(set(EXIT_KIND) - set(by)):
        fails.append(f"exits: the tool names frame {name}, the inventory does not")
    # A1: the switch table — only the account row is aria-disabled, and never with a lock
    for r in rows_of(section(spec, "### 5.2 ", "### 5.3 ")):
        if r[0] == "Account":
            continue  # the storage check gates the Account row (aria-disabled, no T2 form)
        body = " | ".join(r)
        for ok in T2_FORM_ALLOWED:
            body = body.replace(ok, "")
        for m in T2_FORM.finditer(body):
            fails.append(f"t2-form: the {r[0]} switch row draws '{m.group(0)}'")
    # A2-4: every drawn chord is in keymap.json, a component key, or marked PROPOSED after it
    component = {
        e
        for r in rows_of(section(spec, "### 9.1 ", "### 9.2 "))
        if len(r) > 4 and r[4].startswith("component key")
        for _c, _e, exp in chords_in(r[1])
        for e in exp
    }
    surfaces: list[tuple[str, str]] = [(f"frame {n}", " | ".join(r)) for n, r in by.items()]
    surfaces += [
        (f"board {r[0]}", " | ".join(r))
        for r in rows_of(section(spec, "## 0. ", "## 1. "))
        if r and re.fullmatch(r"\d\d", r[0])
    ]
    hint = section(spec, "### 9.4 ", "## 10. ").split("with the two defects")[0]
    surfaces += [("the §9.4 board-09 hint", q) for q in re.findall(r'"([^"]*)"', hint)]
    surfaces += [
        (f"copy deck {r[0]}", r[1])
        for r in rows_of(section(spec, "## 11. ", "## 12. "))
        if len(r) > 1
    ]
    for where, text in surfaces:
        for cell in text.split("|"):
            for clause in cell.split(";"):
                for c, end, exp in chords_in(clause):
                    if all(e in bindings or e in component for e in exp):
                        continue
                    # PROPOSED qualifies the chord: after it, with no other control or screen
                    # named (and no "or") between them
                    pm = re.search(r"proposed", clause[end:], re.IGNORECASE)
                    gap = clause[end : end + pm.start()] if pm else ""
                    if not pm or re.search(r"\b(?:SCR|CMP)-\d|\bor\b", gap):
                        fails.append(f"keys: {where} draws {c} without PROPOSED after it")
    return fails


def gates(
    spec: str, handoff: str, tool: str, bindings: set[str], switches: Switches = SWITCHES
) -> list[str]:
    """Each returned string is a failed gate. The order and wording are stable (the self-test keys on them)."""
    fails: list[str] = []
    # the popover's label fit (F-3): no switch label needs a second line in its box at either
    # density, at the in-app text scales or in the 200 % modal (one FAIL per label); section 5.1
    # quotes the computed heights (the popover-1920 row's height is the number context's)
    pop = popover_report(switches)
    over: dict[str, list[str]] = {}
    for where, labels in pop["label_overflows"].items():
        for label in labels:
            over.setdefault(label, []).append(where)
    for label, wheres in over.items():
        fails.append(
            f"fit: the switch label '{label}' needs a second line in its box ({', '.join(wheres)})"
        )
    hc, hf = pop["height"]["compact"], pop["height"]["comfortable"]
    anatomy = section(spec, "### 5.1 ", "### 5.2 ")
    if not re.search(rf"\b{hc} px compact / {hf} comfortable\b", anatomy):
        fails.append(f"popover: section 5.1 does not quote the computed heights {hc} / {hf}")
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
    for r in inv:
        name = r[0].strip("`")
        if "account" in name and (
            not re.search(r"absence|unavailable", r[3]) or "aria-disabled" not in " ".join(r)
        ):
            fails.append(
                "over-conversion: the account-axis frame is not a plain unavailable row with aria-disabled"
            )
        if "refus" in name and "outcome" not in r[3]:
            fails.append("over-conversion: a refusal frame is not classed as an outcome")
        if "conflict" in name and "status" not in r[3] and "T2" not in r[3]:
            fails.append("over-conversion: a conflict frame is not classed as a status")
        text = " ".join(r)
        # F-2: a DOM or ticket in a symbol-sharing group shows where its symbol came from
        # (E15-D02 D-26)
        if (
            len(r) > 2
            and re.search(r"(?<!, )\b(?:DOMs?|tickets?)\b", r[2])
            and re.search(r"\b(?:tile [ABC]|group [ABC]|in [ABC]\b|[ABC] · symbol)", r[2])
            and not re.search(r"provenance|symbol set by sync group|via [ABC]\b|held: armed", text)
        ):
            fails.append(
                f"provenance: frame {name} shows a DOM or ticket in a group without its provenance"
            )
        # F-5 / BQ-16: no frame keeps an ARMED state after a symbol change made by sync — armed
        # appears only beside the disarm it leads to, or as the held alternative that keeps its own
        # symbol
        if re.search(r"(?<!dis)\barmed\b", text, re.IGNORECASE) and not (
            re.search(r"disarm", text, re.IGNORECASE)
            or re.search(r"held: armed \((?:BTC|ETH|SOL)USDT|held", text)
        ):
            fails.append(f"armed: frame {name} names an armed state without the disarm or the hold")
    # the badge density pair (section 4)
    # (the section 4.1 compact / comfortable pair is number_gates' row-by-row check)
    # m-2: the hand-off's Density table carries the same CMP-082 pair
    dens = {
        r[1] for r in rows_of(section(handoff, "### Density", "### Essential")) if r[0] == "CMP-082"
    }
    for mode in ("compact", "comfortable"):
        if mode not in dens:
            fails.append(f"badge: the hand-off's Density table lacks the CMP-082 {mode} row")
    if "no validity-disabled control" not in spec:
        fails.append("validity: the spec does not state that no validity-disabled control exists")
    if "unsync is not a reset" not in spec:
        fails.append("retention: 'unsync is not a reset' is not stated verbatim")
    # storage pending on every un-stored switch and on percent
    switch_sec = section(spec, "### 5.2 ", "### 5.3 ")
    for ax in ("Interval", "Time range"):
        row = re.search(r"^\| " + ax + r" .*$", switch_sec, MULTI)
        if not row or "storage pending" not in row.group(0):
            fails.append(f"storage: the {ax} switch row lacks 'storage pending'")
    acct = re.search(r"^\| Account .*$", switch_sec, MULTI)
    if (
        not acct
        or "aria-disabled" not in acct.group(0)
        or re.search(r"lock|CMP-079|\bT2\b|disabledReason|rbac\.", acct.group(0))
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
    unmarked = [
        t
        for t in PROPOSED_TOKENS
        if not re.search(re.escape(t) + r"[^\n]*PROPOSED|PROPOSED[^\n]*" + re.escape(t), spec)
    ]
    if unmarked:
        fails.append(f"tokens: {', '.join(unmarked)} not marked PROPOSED on their rows")
    fails.extend(frame_gates(spec, bindings))
    fails.extend(number_gates(spec, handoff))
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
        "t2_frames": sum(
            1
            for r in inv
            if len(r) > 3 and re.search(r"\bT2\b", r[3]) and r[0].strip("`") in T2_FRAMES
        ),
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


@functools.lru_cache(maxsize=1)
def _matrix() -> dict[str, Any]:
    return matrix_report([])


@functools.lru_cache(maxsize=1)
def _cvd() -> dict[str, Any]:
    return cvd_report()


@functools.lru_cache(maxsize=1)
def _pop() -> dict[str, Any]:
    return popover_report()


def bound_missing() -> list[str]:
    dark = theme("dark")
    return [n for n in BOUND if n not in dark]


def build_markers(spec: str, handoff: str) -> dict[str, Any]:
    """The values the spec's `audit:` markers carry (also printed under ``--json``)."""
    badge, pop, refusal = badge_report(), _pop(), refusal_report()
    matrix, cvd_rows = _matrix(), _cvd()
    missing = bound_missing()
    c = counts(spec, handoff)
    cb, cf = badge["densities"]["compact"], badge["densities"]["comfortable"]
    at125 = popover_layout("compact", 125)
    markers: dict[str, Any] = {
        "popover_w": POPOVER_W,
        "popover_h_compact": pop["height"]["compact"],
        "popover_h_comfortable": pop["height"]["comfortable"],
        "popover_column_w": pop["column_w"],
        "zoom200_w": ZOOM200[0],
        "zoom200_h": ZOOM200[1],
        "zoom200_body_h_compact": pop["zoom200"]["body_h"]["compact"],
        "zoom200_visible_body": pop["zoom200"]["visible_body"],
        "zoom200_topbar": pop["zoom200"]["topbar"],
        "zoom200_statusbar": pop["zoom200"]["statusbar"],
        "zoom200_between_bars": pop["zoom200"]["between_bars"],
        "zoom200_modal_w": pop["zoom200"]["modal_w"],
        "zoom200_modal_h": pop["zoom200"]["modal_h"],
        "zoom200_switch_row": pop["zoom200"]["switch_row"],
        "switch_row_column_compact": pop["switch_rows"]["compact"]["column"],
        "switch_row_full_compact": pop["switch_rows"]["compact"]["full"],
        "switch_row_column_comfortable": pop["switch_rows"]["comfortable"]["column"],
        "switch_row_full_comfortable": pop["switch_rows"]["comfortable"]["full"],
        "switch_box_column": pop["boxes"]["column"],
        "switch_box_full": pop["boxes"]["full"],
        "switch_label_px": SWITCH_TEXT["label"],
        "switch_consequence_px": SWITCH_TEXT["consequence"],
        "label_w_drawings": label_w("Drawings (same symbol only)", SWITCH_TEXT["label"]),
        "label_w_account": label_w("Account and trade group", SWITCH_TEXT["label"]),
        "text_scale_125_max_lines": pop["text_scale_125"]["max_cons_lines"],
        "text_scale_125_row_symbol_crosshair": at125["switch_rows"][0]["px"],
        "text_scale_125_row_other": at125["switch_rows"][1]["px"],
        "text_scale_125_row_top": at125["switch_rows"][0]["top"],
        "text_scale_150_max_lines": pop["text_scale_150"]["max_cons_lines"],
        "modal_header": MODAL_HEADER,
        "modal_footer": MODAL_FOOTER,
        "text_scale_125_h": pop["text_scale_125"]["compact_h"],
        "text_scale_150_h": pop["text_scale_150"]["compact_h"],
        "text_scale_150_modal_h": pop["text_scale_150"]["modal_h"],
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
        "btc_decade": math.floor(math.log10(PRICES["BTCUSDT"])),
        "sol_decade": math.floor(math.log10(PRICES["SOLUSDT"])),
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
    return markers


# -------------------------------------------------------- 8c. every number from --json (M-3) ---
# Three checks, each failing by name: (1) the `audit:` block at the end of the spec equals
# ``--json``'s markers (every key once, no unknown key); (2) every registered prose context
# re-derives its numbers (a context that vanishes is a FAIL); (3) the section 4.1 and section 12
# tables equal the tool's, and every
# two-decimal ratio and ratio triple in the spec and the hand-off is one the tool derives.
MARKER = re.compile(r"<!--\s*audit:([A-Za-z0-9_.-]+)=([^\s>]+)\s*-->")
WORD_NUM = {"three": 3, "ten": 10}
_N = r"(\d[\d,]*(?:\.\d+)?)"
_R = r"(\d+\.\d\d)"
_T = rf"{_R} / {_R} / {_R}"
# fmt: off
CONTEXTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "fixture prices",
        rf"Fixture content is E15-D02 §0's: BTCUSDT {_N}, ETHUSDT {_N}, SOLUSDT {_N}",
        ("btc", "eth", "sol"),
    ),
    ("the popover width", r"the (\d+) px popover", ("popover_w",)),
    ("the 200 % viewport", r"(\d+)\u00d7(\d+) CSS px", ("zoom200_w", "zoom200_h")),
    ("the text-scale strip", r"the (\d+) % in-app text-scale strip", ("text_scale_low",)),
    (
        "tokens bound",
        r"\((\d+) bound, (\d+) missing — the tool\)",
        ("tokens_bound", "tokens_missing"),
    ),
    (
        "token sets",
        r"\((\d+) dark · (\d+) light · (\d+) high-contrast\)",
        ("tokens_dark", "tokens_light", "tokens_hc"),
    ),
    (
        "E15-D02 minimums",
        r'the badge minimums (\d+) / (\d+) / (\d+) px at compact, "via A" (\d+)',
        ("d02_min_count", "d02_min_one", "d02_min_full", "d02_min_via"),
    ),
    ("the minimum delta", r"\+(\d+) px at the letter-and-glyph minimum", ("kind_minimum_delta",)),
    (
        "BTC / ETH decades",
        rf"BTC(?:USDT)? ?/? ?(?:against )?ETH[^.;|]*?{_R} decades",
        ("btc_eth_decades",),
    ),
    ("the tile sizes", r"a (\d+) / (\d+) px letter tile", ("tile_compact", "tile_comfortable")),
    (
        "the badge heights",
        r"Compact (\d+) px tall in the (\d+) px row, comfortable (\d+) in (\d+)",
        ("badge_h_compact", "row_compact", "badge_h_comfortable", "row_comfortable"),
    ),
    (
        "D-1's minimum",
        r"the minimum is (\d+) / (\d+) px",
        ("badge_w_min_compact", "badge_w_min_comfortable"),
    ),
    ("the rejected tint", rf"the rejected tint measures {_R}:1 in light", ("tint_purple_light",)),
    ("the modal margin", r"with a (\d+) px margin", ("modal_margin",)),
    (
        "D-3's 200 % case",
        r"the viewport is (\d+)\u00d7(\d+) and the popover is (\d+) px tall in compact",
        ("zoom200_w", "zoom200_h", "popover_h_compact"),
    ),
    (
        "D-3's 125 % case",
        r"\((\d+) px inside the (\d+) px canvas, a consequence line on up to (\w+) lines",
        ("text_scale_125_h", "canvas_1280_h", "text_scale_125_lines"),
    ),
    ("the 150 % height", r"150 % it measures (\d+) px", ("text_scale_150_h",)),
    ("D-4's columns", r"in two (\d+) px columns", ("popover_column_w",)),
    (
        "D-4's Drawings fit",
        r"its (\d+) px label never fits a (\d+) px column box",
        ("label_w_drawings", "switch_box_column"),
    ),
    (
        "D-4's row heights",
        r"\((\d+) px for a two-line consequence in a column, (\d+) full width, compact\)",
        ("switch_row_column_compact", "switch_row_full_compact"),
    ),
    (
        "the refusal sentence",
        (
            r"BTCUSDT\}? trades near \{?([\d,]+)\}? and \{?SOLUSDT\}? near \{?([\d.]+)\}?: "
            r"about \{?(\d+)\}? times"
        ),
        ("btc", "sol", "btc_sol_about"),
    ),
    ("about N times", r"about (\d+) times", ("btc_sol_about",)),
    ("badge none width", r"no tile; (\d+) px", ("badge_w_none_compact",)),
    ("badge one width", r'\+ "symbol"; (\d+) px', ("badge_w_one_compact",)),
    ("badge B width", r"three axes in words; (\d+) px", ("badge_w_full_compact",)),
    (
        "the compact redlines",
        r"redlines: tile (\d+), glyph (\d+), gap (\d+), pad (\d+), text (\d+)",
        ("tile_compact", "glyph_compact", "badge_gap", "badge_pad_compact", "badge_text_compact"),
    ),
    (
        "the comfortable frame",
        (
            r"the (\d+) px row: tile A [^;]*; badge (\d+), tile (\d+), glyph (\d+), pad (\d+), "
            r"text (\d+); (\d+) px for three axes"
        ),
        (
            "row_comfortable", "badge_h_comfortable", "tile_comfortable", "glyph_comfortable",
            "badge_pad_comfortable", "badge_text_comfortable", "badge_w_full_comfortable",
        ),
    ),
    (
        "the narrow steps",
        r'words → "3" \((\d+) px\) → tile \+ glyph only \((\d+) px',
        ("badge_w_count_compact", "badge_w_min_compact"),
    ),
    (
        "the greyscale strip",
        r"greys of ΔE (\d+\.\d) \(dark\) and (\d+\.\d) \(light\)",
        ("cvd_min_de_dark", "cvd_min_de_light"),
    ),
    ("the 1920 frame", r"the (\d+) \u00d7 (\d+) px popover", ("popover_w", "popover_h_compact")),
    ("the 1280 canvas", r"inside the (\d+)\u00d7(\d+) canvas", ("canvas_1280_w", "canvas_1280_h")),
    (
        "the 1920 canvas",
        r"the (\d+)\u00d7(\d+) canvas at 1920\u00d71080",
        ("canvas_1920_w", "canvas_1920_h"),
    ),
    (
        "the modal frame",
        (
            r"(\d+)\u00d7(\d+) CSS px: the TopBar \((\d+)\) with its ENV badge and Safety "
            r"cluster and the StatusBar \((\d+)\) drawn, never scrimmed; the scrim covers the "
            r"(\d+) px body between them and the CMP-043 modal takes it less (\d+) px a side "
            r"\((\d+) \u00d7 (\d+)\), header (\d+), "
            r"sticky footer (\d+), one column of six single-line switch rows \((\d+) px each\), "
            r"the body \((\d+) px\) "
            r"scrolling inside (\d+) px"
        ),
        (
            "zoom200_w", "zoom200_h", "zoom200_topbar", "zoom200_statusbar",
            "zoom200_between_bars", "modal_margin", "zoom200_modal_w", "zoom200_modal_h",
            "modal_header", "modal_footer", "zoom200_switch_row",
            "zoom200_body_h_compact", "zoom200_visible_body",
        ),
    ),
    (
        "the 125 % frame",
        r"the popover at (\d+) px, still a popover inside the (\d+) px canvas",
        ("text_scale_125_h", "canvas_1280_h"),
    ),
    (
        "the BTC / ETH inset",
        rf"BTCUSDT {_N} against ETHUSDT {_N}, about (\d+\.\d) times, {_R} decades",
        ("btc", "eth", "btc_eth_about", "btc_eth_decades"),
    ),
    (
        "the footprint frame (dark)",
        rf"callouts {_T} without and {_T} with the halo \(dark\)",
        ("rf.bid.dark", "rf.ask.dark", "rf.imb.dark", "bt.bid.dark", "bt.ask.dark", "bt.imb.dark"),
    ),
    (
        "the light edges",
        rf"edges {_T} on the header",
        ("edge.a.light", "edge.b.light", "edge.c.light"),
    ),
    ("the light conflict glyph", rf"glyph {_R}:1", ("conflict_glyph_light",)),
    (
        "the light T2 item",
        rf"label {_R}, reason {_R}, lock {_R}",
        ("t2_label_light", "t2_reason_light", "t2_lock_light"),
    ),
    ("the light primary", rf"primary action label {_R}:1", ("primary_light",)),
    (
        "the footprint frame (light)",
        rf"{_T} without, {_T} with the halo",
        (
            "rf.bid.light", "rf.ask.light", "rf.imb.light", "bt.bid.light", "bt.ask.light",
            "bt.imb.light",
        ),
    ),
    (
        "the focus ring on the header",
        rf"outside the chip \({_T}:1 on the header\)",
        ("focus_header.dark", "focus_header.light", "focus_header.hc"),
    ),
    (
        "the badge minimum (4.2)",
        (
            r"\*\*(\d+) px compact / (\d+) px comfortable\*\*, against E15-D02 §3's text-only "
            r'"A · 1" at '
            r"(\d+) px — \*\*\+(\d+) px\*\*"
        ),
        ("badge_w_min_compact", "badge_w_min_comfortable", "d02_min_count", "kind_minimum_delta"),
    ),
    (
        "the kind minimums",
        r"\(chart (\d+), DOM (\d+), tape (\d+)\) to (\d+) / (\d+) / (\d+) at compact",
        (
            "min_w_chart_d02", "min_w_dom_d02", "min_w_tape_d02", "min_w_chart", "min_w_dom",
            "min_w_tape",
        ),
    ),
    (
        "the header edges (4.3)",
        rf"A {_T}, B {_T}, C {_T} — every edge",
        (
            "edge.a.dark", "edge.a.light", "edge.a.hc", "edge.b.dark", "edge.b.light", "edge.b.hc",
            "edge.c.dark", "edge.c.light", "edge.c.hc",
        ),
    ),
    (
        "the CVD minimum (4.3)",
        r"ΔE76 ≥ (\d+\.\d) in dark, ≥ (\d+\.\d) in light",
        ("cvd_min_cvd_dark", "cvd_min_cvd_light"),
    ),
    (
        "the greyscale collapse (4.3)",
        r"collapse \(ΔE (\d+\.\d) dark, (\d+\.\d) light\)",
        ("cvd_min_de_dark", "cvd_min_de_light"),
    ),
    ("the tint (4.3)", rf"purple tint in light: {_R}:1", ("tint_purple_light",)),
    (
        "the switch area (5.1)",
        r"two (\d+) px columns \(a (\d+) px label box beside the (\d+) px track\)",
        ("popover_column_w", "switch_box_column", "switch_track_w"),
    ),
    (
        "the full width (5.1)",
        r"the full (\d+) px width \(a (\d+) px box\)",
        ("inner_w", "switch_box_full"),
    ),
    ("the label size", r"\(`type\.ui\.body`, (\d+) px\)", ("switch_label_px",)),
    (
        "the label widths",
        r"Drawings needs (\d+) px, Account (\d+)",
        ("label_w_drawings", "label_w_account"),
    ),
    ("the consequence size", r"\(`type\.ui\.caption`, (\d+) px\)", ("switch_consequence_px",)),
    (
        "the row stack (5.1)",
        (
            r"title row (\d+) / (\d+) — .*?\"Group A shares:\" (\d+) / (\d+); "
            r"two column rows (\d+) / (\d+) each \(switch (\d+) / (\d+) \+ a two-line "
            r"consequence\); the Drawings row (\d+) / (\d+) \(one line\); the account row "
            r"(\d+) / (\d+); .*?DOM\" (\d+) / (\d+); the conflict "
            r"notice (\d+) / (\d+) when present; .*?\(not a group setting\)\" (\d+) / (\d+) "
            r"and .*? per "
            r"chart member \(the two charts; the DOM has no price scale\), (\d+) / (\d+) each"
        ),
        (
            "row_title_compact", "row_title_comfortable", "row_shares_compact",
            "row_shares_comfortable", "switch_row_column_compact", "switch_row_column_comfortable",
            "switch_h_compact", "switch_h_comfortable", "switch_row_full_compact",
            "switch_row_full_comfortable", "switch_row_full_compact", "switch_row_full_comfortable",
            "row_members_compact", "row_members_comfortable", "row_conflict_compact",
            "row_conflict_comfortable", "row_heading_compact", "row_heading_comfortable",
            "row_select_compact", "row_select_comfortable",
        ),
    ),
    (
        "the canvases (5.1)",
        (
            r"inside the (\d+)\u00d7(\d+) canvas at 1280\u00d7800 "
            r"\(and the (\d+)\u00d7(\d+) canvas at 1920\u00d71080\) "
            r"with a (\d+) px margin"
        ),
        ("canvas_1280_w", "canvas_1280_h", "canvas_1920_w", "canvas_1920_h", "modal_margin"),
    ),
    (
        "the 200 % modal (5.3)",
        (
            r"the CSS viewport is (\d+)\u00d7(\d+), .*?the TopBar keeps (\d+) px and the "
            r"StatusBar (\d+) .*?the body between them is (\d+) px\. "
            r"The popover \((\d+) px \+ (\d+) margin\) "
            r"cannot fit it, .*?less (\d+) px a side .*?: (\d+) \u00d7 (\d+) px — "
            r"header (\d+) px \(title and \u00d7\), .*?the modal's (\d+) px box, "
            r"(\d+) px each\), .*?a body of "
            r"(\d+) px that scrolls inside (\d+) px, and a sticky (\d+) px footer"
        ),
        (
            "zoom200_w", "zoom200_h", "zoom200_topbar", "zoom200_statusbar",
            "zoom200_between_bars", "popover_h_compact", "modal_margin_x2", "modal_margin",
            "zoom200_modal_w", "zoom200_modal_h", "modal_header",
            "modal_box", "zoom200_switch_row", "zoom200_body_h_compact", "zoom200_visible_body",
            "modal_footer",
        ),
    ),
    (
        "D-3's 200 % modal",
        (
            r"inside the body between the TopBar and the StatusBar \((\d+) px at 200 %\), "
            r"capped at it less (\d+) px a side \((\d+) \u00d7 (\d+);"
        ),
        ("zoom200_between_bars", "modal_margin", "zoom200_modal_w", "zoom200_modal_h"),
    ),
    (
        "the 150 % modal (5.3)",
        (
            r"opens as the modal, again between the bars: at most (\d+) px tall "
            r"\(the (\d+) px canvas less (\d+) px a side\)"
        ),
        ("text_scale_150_modal_h", "canvas_1280_h", "modal_margin"),
    ),
    (
        "the refusal payload (14)",
        r"the integer part of log10 of each mid price: (\d+) and (\d+) for the fixture's",
        ("btc_decade", "sol_decade"),
    ),
    (
        "the 125 % stack (5.3)",
        (
            r"the popover measures (\d+) px \(the boxes stay, the text grows: the label's "
            r"(\d+\.\d+) px "
            r"line box lifts every row's top to (\d+) px, the Symbol \| Crosshair row is "
            r"(\d+) px with three-line consequences, the other switch rows (\d+)\) and stays "
            r"a popover inside the "
            r"(\d+) px canvas"
        ),
        (
            "text_scale_125_h", "label_line_125", "text_scale_125_row_top",
            "text_scale_125_row_symbol_crosshair", "text_scale_125_row_other", "canvas_1280_h",
        ),
    ),
    ("the canvas margins (5.3)", r"less its (\d+) px margins", ("modal_margin",)),
    (
        "the axis text (7.2)",
        rf"\({_T}:1 on the canvas — CMP-188's own",
        ("axis_text.dark", "axis_text.light", "axis_text.hc"),
    ),
    (
        "the T2 label and reason (7.3)",
        rf"\({_T}:1 on the menu\), the reason .*? \({_T}:1\)",
        (
            "t2_label.dark", "t2_label.light", "t2_label.hc", "t2_reason.dark", "t2_reason.light",
            "t2_reason.hc",
        ),
    ),
    (
        "the reason length",
        r'"Join a sync group to link its scale\." \| (\d+) \|',
        ("reason_chars",),
    ),
    ("the reason length (copy)", r"\((\d+) characters\)", ("reason_chars",)),
    (
        "the refusal arithmetic (7.4)",
        rf"BTCUSDT {_N} against SOLUSDT {_N} is {_R} times — \"about (\d+)\" — or {_R} decades",
        ("btc", "sol", "btc_sol_ratio", "btc_sol_about", "btc_sol_decades"),
    ),
    (
        "the threshold (7.5)",
        (
            rf"BTCUSDT against ETHUSDT \({_N}\) is {_R} times, {_R} decades — refused; "
            r"ETHUSDT against "
            rf"SOLUSDT, {_R} times, {_R} decades"
        ),
        ("eth", "btc_eth_ratio", "btc_eth_decades", "eth_sol_ratio", "eth_sol_decades"),
    ),
    (
        "the blended dash (7.6)",
        rf"— {_T}:1 over the canvas when blended",
        ("rf.canvas.dark", "rf.canvas.light", "rf.canvas.hc"),
    ),
    (
        "the dash over cells (7.6)",
        rf"the dash alone measures {_T}:1 \(dark\)",
        ("rf.bid.dark", "rf.ask.dark", "rf.imb.dark"),
    ),
    (
        "the two-tone (7.6)",
        rf"against the cell {_T}, the dash against its halo {_T}",
        ("bt.bid.dark", "bt.ask.dark", "bt.imb.dark", "dh.bid.dark", "dh.ask.dark", "dh.imb.dark"),
    ),
    ("the dash range (D-14)", rf"the dash alone measures {_R}\u2013{_R}:1", ("rf_min", "rf_max")),
    (
        "the gated pairs",
        r"\*\*(\d+) gated pairs, (\d+) FAIL\*\*",
        ("matrix_gated", "matrix_failed"),
    ),
    (
        "the footprint edges (12)",
        rf"would measure {_R}\u2013{_R}:1",
        ("edge_fp_min", "edge_fp_max"),
    ),
    ("opacity.muted (12)", r"`opacity\.muted` \((\d+\.\d+)\)", ("opacity_muted",)),
    (
        "tokens (12)",
        r"\*\*Tokens bound:\*\* (\d+), (\d+) missing",
        ("tokens_bound", "tokens_missing"),
    ),
    (
        "the CVD minimum (12)",
        r"The minimum ΔE is (\d+\.\d) in dark and (\d+\.\d) in light",
        ("cvd_min_de_dark", "cvd_min_de_light"),
    ),
    (
        "A-10",
        r'the badge "A · 1" (\d+) px; chart (\d+), DOM (\d+), tape (\d+)',
        ("d02_min_count", "min_w_chart_d02", "min_w_dom_d02", "min_w_tape_d02"),
    ),
    (
        "A-10 proposed",
        r"tile \+ glyph minimum (\d+) px \(\+(\d+)\): chart (\d+), DOM (\d+), tape (\d+)",
        ("badge_w_min_compact", "kind_minimum_delta", "min_w_chart", "min_w_dom", "min_w_tape"),
    ),
    (
        "OQ-4",
        (
            r"the \+(\d+) px badge minimum raising the kind minimums "
            r"\(chart (\d+), DOM (\d+), tape (\d+)\)"
        ),
        ("kind_minimum_delta", "min_w_chart", "min_w_dom", "min_w_tape"),
    ),
    ("the account row cost (16)", r"the account row costs (\d+) px", ("switch_row_full_compact",)),
    (
        "the summary badge (19)",
        r"(\d+) / (\d+) px minimum, \+(\d+) on",
        ("badge_w_min_compact", "badge_w_min_comfortable", "kind_minimum_delta"),
    ),
    (
        "the summary popover (19)",
        r"The (\d+) px popover \((\d+) / (\d+) px\)",
        ("popover_w", "popover_h_compact", "popover_h_comfortable"),
    ),
    (
        "the summary refusal (19)",
        rf"about (\d+) times, {_R} decades\)",
        ("btc_sol_about", "btc_sol_decades"),
    ),
    (
        "the summary halo (19)",
        rf"\({_R}\u2013{_R}:1 without, {_R}\u2013{_R} with\)",
        ("rf_min", "rf_max", "bt_min", "bt_max"),
    ),
    (
        "the summary counts (19)",
        (
            r"(\d+) named frames on (\w+) PENDING boards; (\d+) gated pairs, (\d+) FAIL; "
            r"(\d+) A-rows, "
            r"(\d+) C-rows, (\d+) G-rows, (\d+) OQs"
        ),
        (
            "count_frames_named", "count_boards", "matrix_gated", "matrix_failed", "count_a_rows",
            "count_c_rows", "count_g_rows", "count_oq_rows",
        ),
    ),
)
HANDOFF_CONTEXTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "hand-off: the popover densities",
        r"title (\d+), column rows (\d+), full rows (\d+), selects (\d+); height (\d+)",
        (
            "row_title_compact", "switch_row_column_compact", "switch_row_full_compact",
            "row_select_compact", "popover_h_compact",
        ),
    ),
    (
        "hand-off: the comfortable popover",
        r"\| (\d+) / (\d+) / (\d+) / (\d+); height (\d+) ",
        (
            "row_title_comfortable", "switch_row_column_comfortable", "switch_row_full_comfortable",
            "row_select_comfortable", "popover_h_comfortable",
        ),
    ),
    (
        "hand-off: the compact badge widths",
        r"text (\d+), widths (\d+) / (\d+) / (\d+) / (\d+) / (\d+); comfortable",
        (
            "badge_text_compact", "badge_w_full_compact", "badge_w_one_compact",
            "badge_w_count_compact", "badge_w_none_compact", "badge_w_min_compact",
        ),
    ),
    (
        "hand-off: the comfortable badge widths",
        r"text (\d+), widths (\d+) / (\d+) / (\d+) / (\d+) / (\d+) \(spec",
        (
            "badge_text_comfortable", "badge_w_full_comfortable", "badge_w_one_comfortable",
            "badge_w_count_comfortable", "badge_w_none_comfortable", "badge_w_min_comfortable",
        ),
    ),
    (
        "hand-off: the modal",
        (
            r"between the TopBar and the StatusBar \((\d+)\), (\d+) \u00d7 (\d+), "
            r"header (\d+), footer (\d+), single-line rows (\d+), body (\d+) scrolling in (\d+)"
            r"[^;]*; "
            r"the text "
            r"scale 125 % (\d+) \(popover\), 150 % (\d+) \(modal\)"
        ),
        (
            "zoom200_between_bars", "zoom200_modal_w", "zoom200_modal_h",
            "modal_header", "modal_footer", "zoom200_switch_row", "zoom200_body_h_compact",
            "zoom200_visible_body", "text_scale_125_h", "text_scale_150_h",
        ),
    ),
    (
        "hand-off: the gated pairs",
        r"(\d+) gated pairs, (\d+) FAIL",
        ("matrix_gated", "matrix_failed"),
    ),
)

# fmt: on


def number_values(spec: str, handoff: str) -> dict[str, Any]:
    """The markers plus the derived values the registered contexts quote (never typed)."""
    v: dict[str, Any] = dict(build_markers(spec, handoff))
    pop = _pop()
    m = _matrix()
    th3 = {"dark": "dark", "light": "light", "high-contrast": "hc"}

    def mrow(prefix: str, th: str) -> float:
        return float(
            next(
                r["ratio"]
                for r in m["rows"]
                if r["element"].startswith(prefix) and r["theme"] == th
            )
        )

    for th, short in th3.items():
        for k in ("a", "b", "c"):
            v[f"edge.{k}.{short}"] = mrow(f"tile edge {k.upper()} on the header", th)
        v[f"focus_header.{short}"] = mrow("focus ring on the header", th)
        v[f"axis_text.{short}"] = mrow("axis text Linked", th)
        v[f"t2_label.{short}"] = mrow("T2 label", th)
        v[f"t2_reason.{short}"] = mrow("T2 reason", th)
    v["conflict_glyph_light"] = mrow("conflict glyph", "light")
    v["t2_label_light"], v["t2_reason_light"] = (
        mrow("T2 label", "light"),
        mrow("T2 reason", "light"),
    )
    v["t2_lock_light"] = mrow("T2 lock glyph", "light")
    v["primary_light"] = mrow("refusal primary action label", "light")
    v["tint_purple_light"] = mrow("rejected tint: letter on a purple", "light")
    fp = [r["ratio"] for r in m["rows"] if "on a footprint" in r["element"]]
    v["edge_fp_min"], v["edge_fp_max"] = min(fp), max(fp)
    short_bg = {
        "color.surface.canvas": "canvas",
        "color.footprint.bid": "bid",
        "color.footprint.ask": "ask",
        "color.footprint.imbalance": "imb",
    }
    for r in m["remote"]:
        k = f"{short_bg[r['bg']]}.{th3[r['theme']]}"
        v[f"rf.{k}"], v[f"bt.{k}"], v[f"dh.{k}"] = (
            r["ratio"],
            r["best_of_two_tone"],
            r["dash_vs_halo"],
        )
    cells = [r for r in m["remote"] if r["bg"] != "color.surface.canvas"]
    v["rf_min"], v["rf_max"] = min(r["ratio"] for r in cells), max(r["ratio"] for r in cells)
    v["bt_min"], v["bt_max"] = (
        min(r["best_of_two_tone"] for r in cells),
        max(r["best_of_two_tone"] for r in cells),
    )
    cv = _cvd()
    for th, short in (("dark", "dark"), ("light", "light")):
        v[f"cvd_min_cvd_{short}"] = min(
            p[k]
            for kind, p in cv["pairs"][th].items()
            if kind != "greyscale"
            for k in ("a-b", "a-c", "b-c")
        )
    for th, name in (
        ("dark", "tokens_dark"),
        ("light", "tokens_light"),
        ("high-contrast", "tokens_hc"),
    ):
        v[name] = len(verify.merged_set([verify.THEMES[th][-1]]))
    v["btc_eth_about"] = refusal_report()["btc_eth"]["about"]
    v["text_scale_low"], v["text_scale_125_lines"] = (
        TEXT_SCALES[0],
        pop["text_scale_125"]["max_cons_lines"],
    )
    v["modal_margin"], v["modal_margin_x2"] = MODAL_MARGIN, 2 * MODAL_MARGIN
    v["switch_track_w"], v["inner_w"] = SWITCH_TRACK_W, POPOVER_W - 2 * POPOVER_PAD
    v["modal_box"] = popover_layout("compact", 100, ZOOM200[0] - 2 * MODAL_MARGIN, 1)["boxes"][
        "full"
    ]
    v["label_line_125"] = SWITCH_TEXT["label"] * TEXT_SCALES[0] / 100
    v["switch_h_compact"], v["switch_h_comfortable"] = SWITCH_H["compact"], SWITCH_H["comfortable"]
    fixed = {
        n.split(":")[0].split(" ")[0]: (c, f)
        for n, c, f in POPOVER_FIXED_TOP + POPOVER_FIXED_BOTTOM
    }
    for key, name in (
        ("title", "row_title"),
        ("heading", "row_shares"),
        ("members", "row_members"),
        ("conflict", "row_conflict"),
    ):
        v[f"{name}_compact"], v[f"{name}_comfortable"] = fixed[key]
    head = [r for n, c, f in POPOVER_FIXED_BOTTOM for r in [(n, c, f)] if n.startswith("heading")]
    v["row_heading_compact"], v["row_heading_comfortable"] = head[0][1], head[0][2]
    sel = next((c, f) for n, c, f in POPOVER_FIXED_BOTTOM if n.startswith("scale select"))
    v["row_select_compact"], v["row_select_comfortable"] = sel[0] // 2, sel[1] // 2
    v["reason_chars"] = len("Join a sync group to link its scale.")
    return v


def same_number(text: str, value: Any) -> bool:
    t = text.replace(",", "").strip("{}")
    if t in WORD_NUM:
        return bool(WORD_NUM[t] == value)
    if isinstance(value, str):
        return t == value
    try:
        f = float(t)
    except ValueError:
        return False
    nd = len(t.split(".")[1]) if "." in t else 0
    return bool(round(float(value), nd) == f)


def edge_ratio(m: dict[str, Any], x: str, th: str) -> str:
    return fmt(
        next(
            r["ratio"]
            for r in m["rows"]
            if r["element"] == f"tile edge {x} on the header" and r["theme"] == th
        )
    )


@functools.lru_cache(maxsize=1)
def allowed_ratios() -> tuple[set[str], set[tuple[str, str, str]]]:
    m = _matrix()
    singles: set[str] = set()
    triples: set[tuple[str, str, str]] = set()
    by: dict[str, dict[str, dict[str, Any]]] = {}
    for r in m["rows"]:
        singles |= {fmt(r["ratio"]), fmt(r["grey"])}
        by.setdefault(r["element"], {})[r["theme"]] = r
    for ths in by.values():
        for k in ("ratio", "grey"):
            triples.add(tuple(fmt(ths[t][k]) for t in THEMES))  # type: ignore[arg-type]
    rem: dict[str, dict[str, dict[str, Any]]] = {}
    for r in m["remote"]:
        singles |= {fmt(r[k]) for k in ("ratio", "grey", "best_of_two_tone", "dash_vs_halo")}
        rem.setdefault(r["bg"], {})[r["theme"]] = r
    keys = ("ratio", "best_of_two_tone", "dash_vs_halo")
    for ths in rem.values():
        for k in keys:
            triples.add(tuple(fmt(ths[t][k]) for t in THEMES))  # type: ignore[arg-type]
    for th in THEMES:
        cells = [rem[b][th] for b in REMOTE_BGS[1:]]
        for k in keys:
            triples.add(tuple(fmt(c[k]) for c in cells))  # type: ignore[arg-type]
        edges = [edge_ratio(m, x, th) for x in "ABC"]
        triples.add((edges[0], edges[1], edges[2]))
    ref = refusal_report()
    for k in ("btc_sol", "btc_eth", "eth_sol"):
        singles |= {fmt(ref[k]["ratio"]), fmt(ref[k]["decades"])}
    singles |= {fmt(PRICES["SOLUSDT"]), fmt(SWITCH_TEXT["label"] * TEXT_SCALES[0] / 100)}
    return singles, triples


def number_gates(spec: str, handoff: str) -> list[str]:
    fails: list[str] = []
    v = number_values(spec, handoff)
    marks = build_markers(spec, handoff)
    seen: dict[str, int] = {}
    for hit in MARKER.finditer(spec):
        name, value = hit.group(1), hit.group(2)
        seen[name] = seen.get(name, 0) + 1
        if name not in marks:
            fails.append(f"marker: audit:{name} is not a key the tool prints")
        elif str(marks[name]) != value:
            fails.append(f"marker: audit:{name}={value} but --json prints {marks[name]}")
    for name in sorted(marks):
        if seen.get(name, 0) != 1:
            fails.append(f"marker: audit:{name} appears {seen.get(name, 0)} times (once expected)")
    prose = "\n".join(ln for ln in spec.split("\n") if not ln.startswith("<!--"))
    # spans a registered context or the section 12 table already gates: the derived-ratio scan
    # below skips them, so one wrong number is one FAIL (the self-test's exactly-one rule, m-1)
    covered: dict[str, list[tuple[int, int]]] = {"spec": [], "hand-off": []}
    for where, text, ctx in (("spec", prose, CONTEXTS), ("hand-off", handoff, HANDOFF_CONTEXTS)):
        for label, pattern, names in ctx:
            hits = list(re.finditer(pattern, text))
            if not hits:
                fails.append(f"number: the {where} context '{label}' vanished")
            for hit in hits:
                for i, name in enumerate(names, start=1):
                    got = hit.group(i)
                    if got is None:
                        continue
                    covered[where].append(hit.span(i))
                    if not same_number(got, v[name]):
                        fails.append(f"number: {label}: the {where} says {got}, the tool {v[name]}")
    i12 = prose.find("## 12. ")
    j12 = prose.find("**CVD and greyscale", i12)
    for m12 in re.finditer(r"^\|.*$", prose[i12:j12], MULTI):
        covered["spec"].append((i12 + m12.start(), i12 + m12.end()))

    def free(where: str, a: int, b: int) -> bool:
        return not any(x <= a and b <= y for x, y in covered[where])

    # the section 4.1 density pair, cell by cell
    cols = ("row", "badge_h", "tile", "glyph", "gap", "pad_x", "text")
    wcols = ("full", "one", "count", "none", "letter_glyph")
    rows = {r[0]: r for r in rows_of(section(spec, "### 4.1 ", "### 4.2 ")) if r}
    for dens, g in badge_report()["densities"].items():
        r = rows.get(dens)
        if r is None or len(r) != 1 + len(cols) + len(wcols):
            fails.append(f"badge: the §4.1 table lacks its {dens} row")
            continue
        want = [str(g[c]) for c in cols] + [f"{g['width'][c]} px" for c in wcols]
        for head, got, exp in zip((*cols, *wcols), r[1:], want, strict=True):
            if got != exp:
                fails.append(f"badge: the §4.1 {dens} {head} cell reads {got}, the tool {exp}")
    # the section 12 tables, row by row, against the tool's own table
    want_rows = rows_of(matrix_table(_matrix()))
    have = rows_of(section(spec, "## 12. ", "**CVD and greyscale"))
    want_by = {r[0]: r for r in want_rows}
    have_by = {r[0]: r for r in have}
    for key, r in want_by.items():
        if have_by.get(key) != r:
            fails.append(f"matrix: the §12 row '{key[:48]}' differs from the tool's")
    for key in set(have_by) - set(want_by):
        fails.append(f"matrix: the §12 row '{key[:48]}' is not a tool row")
    # the CVD paragraph: every simulated pair and both hue sets, from the tool
    cvd_p = section(spec, "**CVD and greyscale", "**Tokens bound")
    cv = _cvd()
    for th in ("dark", "light"):
        for kind, p in cv["pairs"][th].items():
            s = f"{kind} {p['a-b']:.1f} / {p['a-c']:.1f} / {p['b-c']:.1f}"
            if s not in cvd_p:
                fails.append(f"cvd: the {th} {kind} row is not the tool's ({s})")
        for k in ("a", "b", "c"):
            if f"`{cv['hues'][th][k]}`" not in cvd_p:
                fails.append(f"cvd: the {th} hue {k} is not the tool's")
    # every two-decimal ratio and every ratio triple in the spec and the hand-off is the tool's
    singles, triples = allowed_ratios()
    for where, text in (("spec", prose), ("hand-off", handoff)):
        for hit in re.finditer(r"(?<![\d.\-])(\d+\.\d\d)(?![\d.])", text):
            if hit.group(1) not in singles and free(where, *hit.span(1)):
                fails.append(
                    f"number: the {where}'s ratio {hit.group(1)} is not one the tool derives"
                )
        for hit in re.finditer(rf"(?<![\d.]){_T}(?![\d.])", text):
            if hit.groups() not in triples and any(free(where, *hit.span(k)) for k in (1, 2, 3)):
                fails.append(
                    f"number: the {where}'s triple {' / '.join(hit.groups())} is not the tool's"
                )
    return fails


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


# The frame-level mutation table (the pre-READY audit): each edits ONE element in ONE named row
# (or one table cell / marker) and must trip its own FAIL message exactly once. Targets:
# "frame:<id>" (the state-inventory row), "line:<prefix>" (the one spec line starting so),
# "hand:<prefix>" (the hand-off).
Edit = tuple[str, str, str]
# fmt: off
MUTATIONS: tuple[tuple[str, str, tuple[Edit, ...]], ...] = (
    ("M01", "frame CMP-082/badge-a-compact draws group A's colour without its letter",
     (("frame:CMP-082/badge-a-compact", "tile A (cyan edge, letter A)", "a cyan-edged tile"),)),
    ("M02", "frame CMP-082/badge-a-compact draws a group colour without the `link` glyph",
     (("frame:CMP-082/badge-a-compact", " + `link` + ", " + "),)),
    ("M03", "frame CMP-082/badge-b-compact draws group B's colour without its letter",
     (("frame:CMP-082/badge-b-compact", "tile B (amber edge, letter B)", "an amber-edged tile"),)),
    ("M04", "frame CMP-082/badge-c-compact draws group C's colour without its letter",
     (("frame:CMP-082/badge-c-compact", "tile C (purple edge, letter C)", "a purple-edged tile"),)),
    ("M05", "frame CMP-082/badge-narrow-steps draws group A's colour without its letter",
     (("frame:CMP-082/badge-narrow-steps",
       "(44 px: tile A, letter A, `link`)",
       "(44 px: the hue edge and `link`)"),)),
    ("M06", "frame SCR-023/light-badges draws group A's colour without its letter",
     (("frame:SCR-023/light-badges",
       "(letters A / B / C, each with `link`)",
       "(letters B / C and a cyan edge, each with `link`)"),)),
    ("M07", "frame CMP-082/chart-toolbar-badge draws group A's colour without its letter",
     (("frame:CMP-082/chart-toolbar-badge",
       "(tile A, letter A, `link`)",
       "(a cyan chip, `link`)"),)),
    ("M08", "conflict: frame SCR-023/conflict-interval lacks the full notice sentence",
     (("frame:SCR-023/conflict-interval",
       "Chart 15m has a different interval: crosshair",
       "Chart 15m differs: crosshair"),)),
    ("M09", "conflict: frame CMP-082/conflict-header lacks the `warning` glyph",
     (("frame:CMP-082/conflict-header",
       "the `warning` glyph beside the badge;",
       "a tint on the badge;"),)),
    ("M10", "conflict: frame CMP-082/conflict-header lacks its never-a-toast clause",
     (("frame:CMP-082/conflict-header",
       "the same sentence, never a toast alone",
       "a toast only"),)),
    ("M11", "conflict: frame SCR-023/light-conflict lacks the `warning` glyph",
     (("frame:SCR-023/light-conflict", "in light, `warning` glyph:", "in light:"),)),
    ("M12", "conflict: frame CMP-082/conflict-header lacks the full notice sentence",
     (("frame:CMP-082/conflict-header",
       '"Chart 15m has a different interval: crosshair sync aligns by timestamp." in',
       '"Chart 15m differs." in'),)),
    ("M13", "t2-anatomy: frame SCR-043/link-no-group lacks the lock glyph",
     (("frame:SCR-043/link-no-group", "lock glyph leading in", "leading in"),
      ("frame:SCR-043/link-no-group", "; lock glyph;", ";"))),
    ("M14", "t2-anatomy: frame SCR-043/link-no-group lacks the reason",
     (("frame:SCR-043/link-no-group", '"Join a sync group to link its scale." (', "("),)),
    ("M15", "t2-anatomy: frame SCR-043/link-no-group lacks aria-disabled",
     (("frame:SCR-043/link-no-group", "`aria-disabled`, arrow-reachable", "arrow-reachable"),)),
    ("M16", "t2-anatomy: frame SCR-043/link-no-group lacks the state key",
     (("frame:SCR-043/link-no-group", " (`scale.link.no_group`) as", " as"),)),
    ("M17", "t2-anatomy: frame SCR-043/light-link-no-group lacks the lock glyph",
     (("frame:SCR-043/light-link-no-group",
       "in light: lock glyph, full label",
       "in light: full label"),
      ("frame:SCR-043/light-link-no-group", "; lock glyph)", ")"))),
    ("M18", "t2-anatomy: frame SCR-023/dirty-save-view-as lacks the lock glyph",
     (("frame:SCR-023/dirty-save-view-as", "lock glyph, full label", "full label"),)),
    ("M19", "t2-anatomy: frame SCR-023/dirty-save-view-as lacks the view-as key",
     (("frame:SCR-023/dirty-save-view-as", "the banner's `rbac.view_as` node", "the banner"),)),
    ("M20", "t2-form: frame SCR-023/leave-after draws 'aria-disabled'",
     (("frame:SCR-023/leave-after",
       "nothing re-fetched",
       "nothing re-fetched; its EMA row `aria-disabled`"),)),
    ("M21", "t2-form: frame SCR-023/popover-1280 draws '`lock`'",
     (("frame:SCR-023/popover-1280",
       "note at full opacity",
       "note at full opacity, the CMP-019 `lock` leading"),)),
    ("M22", "t2-form: the Interval switch row draws 'T2'",
     (("line:| Interval ",
       "the frame annotates it",
       "the frame annotates it; T2"),)),
    ("M23", "over-conversion: frame SCR-023/popover-1280 draws a lock glyph",
     (("frame:SCR-023/popover-1280", "note at full opacity", "note at full opacity, lock glyph"),)),
    ("M24", "keys: frame SCR-023/join-after draws Ctrl+Shift+1 without PROPOSED",
     (("frame:SCR-023/join-after",
       "the layout tab shows the dirty `*`",
       "joined with `Ctrl+Shift+1`; the layout tab shows the dirty `*`"),)),
    ("M25", "keys: the §9.4 board-09 hint draws Ctrl+Shift+1..3 without PROPOSED",
     (("line:The chords are drawn with CMP-022",
       "join A / B / C · Ctrl",
       "join A / B / C; Ctrl"),)),
    ("M26", "keys: copy deck `sync.hotkeys.note` draws Ctrl+Shift+1..3 without PROPOSED",
     (("line:| `sync.hotkeys.note`", "join A / B / C · Ctrl", "join A / B / C; Ctrl"),)),
    ("M27", "keys: board 05 draws Ctrl+Shift+L without PROPOSED",
     (("line:| 05 ",
       "checkbox checked, unchecked",
       "checkbox (`Ctrl+Shift+L`) checked, unchecked"),)),
    ("M28", "disarm: frame SCR-023/symbol-switch-disarm lacks the DOM's disarm",
     (("frame:SCR-023/symbol-switch-disarm",
       'sync group A" and `LOCKED`',
       'sync group A"'),)),
    ("M29", "disarm: frame SCR-023/symbol-switch-disarm lacks the chart's disarm",
     (("frame:SCR-023/symbol-switch-disarm",
       "the armed chart's CMP-221 arm reads `LOCKED` too",
       "the chart's CMP-221 arm too"),)),
    ("M30", "disarm: frame SCR-023/symbol-switch-hold lacks the disarm on [Follow group]",
     (("frame:SCR-023/symbol-switch-hold", ", which disarms and follows", ""),)),
    ("M31", "disarm: frame SCR-023/symbol-switch-disarm lacks the assertive disarm",
     (("frame:SCR-023/symbol-switch-disarm",
       " then assertive the disarm (AN-3, AN-4)",
       " (AN-3)"),)),
    ("M32", "disarm: frame SCR-023/symbol-switch-disarm lacks the drawn-outcome clause",
     (("frame:SCR-023/symbol-switch-disarm",
       "— the disarm is the drawn outcome (the default, OQ-1)",
       "— the default (OQ-1)"),)),
    ("M33", "badge: the §4.1 comfortable letter_glyph cell reads 52 px",
     (("line:| comfortable | 32 ", "| 54 px ", "| 52 px "),)),
    ("M34", "number: the comfortable frame: the spec says 14",
     (("frame:CMP-082/badge-a-comfortable", "glyph 16", "glyph 14"),)),
    ("M35", "badge: the §4.1 compact text cell reads 12",
     (("line:| compact     | 24 ", "| 11   |", "| 12   |"),)),
    ("M36", "exits: frame SCR-023/dirty-save-view-as gates an exit ('",
     (("frame:SCR-023/dirty-save-view-as",
       "every pointer shares",
       "every pointer shares; \u00d7 and `Esc` locked"),)),
    ("M37", "exits: frame SCR-043/link-refused does not draw its exit Cancel",
     (("frame:SCR-043/link-refused", "Cancel; `Esc` (= Cancel)", "`Esc`"),)),
    ("M38", "exits: frame SCR-023/leave-after gates an exit ('",
     (("frame:SCR-023/leave-after",
       'Chart 15m back to "No sync"',
       "Chart 15m kept in A (No sync blocked under view-as)"),)),
    ("M39", "exits: frame SCR-023/modal-200pct does not draw its exit Close",
     (("frame:SCR-023/modal-200pct", "Close (\u00d7's twin); ", ""),)),
    ("M40", "number: the 125 % frame: the spec says 590",
     (("frame:SCR-023/popover-text-scale-125", "the popover at 591 px", "the popover at 590 px"),)),
    ("M41", "number: the BTC / ETH inset: the spec says 1.43",
     (("frame:SCR-043/link-refused-btc-eth", "1.42 decades", "1.43 decades"),)),
    ("M42", "number: the footprint frame (dark): the spec says 7.54",
     (("frame:SCR-023/crosshair-remote-footprint", "7.45 / 4.68", "7.54 / 4.68"),)),
    ("M43", "number: the gated pairs: the spec says 82",
     (("line:Two UI densities for the badge", "**81 gated pairs", "**82 gated pairs"),)),
    ("M44", "matrix: the §12 row 'tile edge C on the header",
     (("line:| tile edge C on the header",
       "4.09 (grey 4.17)   | 5.21",
       "4.90 (grey 4.17)   | 5.21"),)),
    ("M45", "number: the summary popover (19): the spec says 526",
     (("line:SCR-023 in colour on E15-D02", "(437 / 525 px)", "(437 / 526 px)"),)),
    ("M46", "frames: the hand-off's named-frame count differs",
     (("hand:Three blocks", "45 named frames", "46 named frames"),)),
    ("M47", "number: the CVD minimum (4.3): the spec says 45.9",
     (("line:`color.sync.a` / `.b` / `.c` are PROPOSED", "ΔE76 ≥ 49.5", "ΔE76 ≥ 45.9"),)),
    ("M48", "number: the refusal arithmetic (7.4): the spec says 449.38",
     (("line:Linking across magnitudes", "449.83 times", "449.38 times"),)),
    ("M49", "t2-anatomy: frame SCR-043/link-no-group lacks the state path",
     (("frame:SCR-043/link-no-group", "`disabledReason`, state-gated", "state-gated"),)),
    ("M50", "armed: frame SCR-023/symbol-switch-hold draws an armed state surviving",
     (("frame:SCR-023/symbol-switch-hold",
       "which disarms and follows",
       "which disarms and follows; the DOM keeps it armed on ETHUSDT"),)),
    ("M51", "dialog: frame SCR-043/link-refused lacks the Cancel exit",
     (("frame:SCR-043/link-refused", ", `[ Cancel ]`", ""),)),
    ("M52", "marker: audit:popover_h_compact=438",
     (("line:<!-- audit:popover_w=",
       "audit:popover_h_compact=437",
       "audit:popover_h_compact=438"),)),
    ("M53", "number: the axis text (7.2): the spec says 6.63",
     (("line:The axis says it in text", "5.96 / 6.36 / 11.87", "5.96 / 6.63 / 11.87"),)),
    ("M54", "cvd: the dark tritanopia row",
     (("line:**CVD and greyscale",
       "tritanopia 71.8 / 51.5 / 49.5",
       "tritanopia 71.8 / 55.1 / 49.5"),)),
    ("M55", "exits: frame SCR-023/popover-1920 does not draw its exit \u00d7",
     (("frame:SCR-023/popover-1920", "\u00d7; `Esc`; the radio", "`Esc`; the radio"),)),
    ("M56", "conflict: frame SCR-023/light-conflict lacks the full notice sentence",
     (("frame:SCR-023/light-conflict",
       '"Chart 15m has a different interval: crosshair sync',
       '"… crosshair sync'),)),
    # text round 1, M-1: the record's five `ARMED`-tag forms (four on the disarm frame, one on
    # the hold frame); each trips the armed-tag gate once, its clause quoted
    ("M57", ("armed-tag: frame SCR-023/symbol-switch-disarm draws an armed tag after the sync "
            "change ('a second DOM in A reads \"ETHUSDT · symbol set by sync group A\" "
            "and `ARMED`')"),
     (("frame:SCR-023/symbol-switch-disarm",
       "`LOCKED` too",
       ('`LOCKED` too; a second DOM in A reads "ETHUSDT · symbol set by sync group A" '
        "and `ARMED`")),)),
    ("M58", ("armed-tag: frame SCR-023/symbol-switch-disarm draws an armed tag after the sync "
            "change ('a second DOM stays `ARMED`')"),
     (("frame:SCR-023/symbol-switch-disarm",
       "`LOCKED` too",
       "`LOCKED` too; a second DOM stays `ARMED`"),)),
    ("M59", ("armed-tag: frame SCR-023/symbol-switch-disarm draws an armed tag after the sync "
            "change ('the order ticket on ETHUSDT reads ARMED')"),
     (("frame:SCR-023/symbol-switch-disarm",
       "`LOCKED` too",
       "`LOCKED` too; the order ticket on ETHUSDT reads ARMED"),)),
    ("M60", ("armed-tag: frame SCR-023/symbol-switch-disarm draws an armed tag after the sync "
            "change ('an order ticket on ETHUSDT stays `ARMED`')"),
     (("frame:SCR-023/symbol-switch-disarm",
       "`LOCKED` too",
       "`LOCKED` too; an order ticket on ETHUSDT stays `ARMED`"),)),
    ("M61", ("armed-tag: frame SCR-023/symbol-switch-hold draws an armed tag after the sync "
            "change ('the ticket follows to ETHUSDT `ARMED`')"),
     (("frame:SCR-023/symbol-switch-hold",
       "which disarms and follows",
       "which disarms and follows; the ticket follows to ETHUSDT `ARMED`"),)),
    # text round 1, m-2: the four wording gaps
    ("M62", "t2-form: frame SCR-023/popover-1280 draws 'padlock'",
     (("frame:SCR-023/popover-1280",
       "note at full opacity",
       "note at full opacity, a padlock before its label"),)),
    ("M63", "t2-anatomy: frame SCR-043/link-no-group negates the lock glyph",
     (("frame:SCR-043/link-no-group", "lock glyph leading in", "no lock glyph, the label in"),
      ("frame:SCR-043/link-no-group", "; lock glyph;", "; no lock glyph;"))),
    ("M64", "keys: frame SCR-043/menu-link-checked draws Ctrl+Shift+1 without PROPOSED",
     (("frame:SCR-043/menu-link-checked",
       "SCR-043's SCALE group with",
       "`Ctrl+Shift+1` or SCR-043's SCALE group with"),)),
    ("M65", "badge: the hand-off's Density table lacks the CMP-082 comfortable row",
     (("hand:| CMP-082   | comfortable", "| comfortable |", "| roomy       |"),)),
    # fold delta, M-1r: the held: exemption scoped to the hold inset (the backticked form off the
    # hold frame; a ticket line outside the inset)
    ("M66", ("armed-tag: frame SCR-023/symbol-switch-disarm draws an armed tag after the sync "
            "change ('a second DOM in A reads \"ETHUSDT · symbol set by sync group A\", "
            "held: `ARMED`')"),
     (("frame:SCR-023/symbol-switch-disarm",
       "`LOCKED` too",
       ('`LOCKED` too; a second DOM in A reads "ETHUSDT · symbol set by sync group A", '
        "held: `ARMED`")),)),
    ("M67", ("armed-tag: frame SCR-023/symbol-switch-hold draws an armed tag after the sync "
            "change ('the ticket reads \"ETHUSDT · symbol set by sync group A\", held: ARMED')"),
     (("frame:SCR-023/symbol-switch-hold",
       "which disarms and follows",
       ('which disarms and follows; the ticket reads "ETHUSDT · symbol set by sync group A", '
        "held: ARMED")),)),
    # fold delta, m-6: the case and prose variants, each class on a symbol-switch frame
    ("M68", ("armed-tag: frame SCR-023/symbol-switch-disarm draws an armed tag after the sync "
            "change ('the order ticket on ETHUSDT reads `Armed`')"),
     (("frame:SCR-023/symbol-switch-disarm",
       "`LOCKED` too",
       "`LOCKED` too; the order ticket on ETHUSDT reads `Armed`"),)),
    ("M69", ("armed-tag: frame SCR-023/symbol-switch-hold draws an armed tag after the sync "
            "change ('the ticket on ETHUSDT: Armed')"),
     (("frame:SCR-023/symbol-switch-hold",
       "which disarms and follows",
       "which disarms and follows; the ticket on ETHUSDT: Armed"),)),
    ("M70", ("armed-tag: frame SCR-023/symbol-switch-disarm draws an armed tag after the sync "
            "change ('the ticket reads armed')"),
     (("frame:SCR-023/symbol-switch-disarm",
       "`LOCKED` too",
       "`LOCKED` too; the ticket reads armed"),)),
    ("M71", ("armed-tag: frame SCR-023/symbol-switch-hold draws an armed tag after the sync "
            "change ('the ticket is armed on ETHUSDT')"),
     (("frame:SCR-023/symbol-switch-hold",
       "which disarms and follows",
       "which disarms and follows; the ticket is armed on ETHUSDT"),)),
    ("M72", ("armed-tag: frame SCR-023/symbol-switch-disarm draws an armed tag after the sync "
            "change ('the ticket on ETHUSDT, held: armed')"),
     (("frame:SCR-023/symbol-switch-disarm",
       "`LOCKED` too",
       "`LOCKED` too; the ticket on ETHUSDT, held: armed"),)),
    ("M73", ("armed-tag: frame SCR-023/symbol-switch-hold draws an armed tag after the sync "
            "change ('the ticket is ETHUSDT, held: armed')"),
     (("frame:SCR-023/symbol-switch-hold",
       "which disarms and follows",
       "which disarms and follows; the ticket is ETHUSDT, held: armed"),)),
    # fold delta, m-5: a T2 form in a non-T2 frame's Gate-class cell (the T2 word aside)
    ("M74", "t2-form: frame SCR-023/popover-1920 draws '`lock`'",
     (("frame:SCR-023/popover-1920", "| T1 ", "| T1 (`lock`) "),)),
    ("M75", "t2-form: frame SCR-023/popover-1280 draws 'disabledReason'",
     (("frame:SCR-023/popover-1280", "| T1 ", "| T1 (`disabledReason`) "),)),
    ("M76", "t2-form: frame SCR-023/leave-after draws 'rbac.view_as'",
     (("frame:SCR-023/leave-after", "| T1 ", "| T1 (`rbac.view_as`) "),)),
    ("M77", "t2-form: frame SCR-043/axis-independent draws 'padlock'",
     (("frame:SCR-043/axis-independent", "| T1 ", "| T1 (a padlock) "),)),
)
# fmt: on


def apply_mutation(spec: str, handoff: str, edits: tuple[Edit, ...]) -> tuple[str, str]:
    """Apply each edit to the one line its target names; raise if a target or text is missing."""
    docs = {"spec": spec.split("\n"), "hand": handoff.split("\n")}
    for target, old, new in edits:
        kind, _, key = target.partition(":")
        doc = docs["hand" if kind == "hand" else "spec"]
        prefix = f"| `{key}` " if kind == "frame" else key
        idx = [i for i, ln in enumerate(doc) if ln.startswith(prefix)]
        if len(idx) != 1 or old not in doc[idx[0]]:
            raise ValueError(f"mutation target {target!r} / {old!r} not found exactly once")
        doc[idx[0]] = doc[idx[0]].replace(old, new, 1)
    return "\n".join(docs["spec"]), "\n".join(docs["hand"])


SELF_TEST_RUNS: dict[str, int] = {"inline": 0, "table": 0, "one_fail": 0}


def self_test(spec: str, handoff: str, tool: str, bindings: set[str]) -> list[str]:
    """Mutate the spec, the hand-off or the switch table in memory; every mutation trips a gate."""
    problems: list[str] = []
    base = gates(spec, handoff, tool, bindings)
    if base:
        return ["self-test needs a passing baseline; gates failing: " + "; ".join(base)]

    def expect(
        name: str, mutated: str, needle: str, hand: str = handoff, switches: Switches = SWITCHES
    ) -> None:
        got = gates(mutated, hand, tool, bindings, switches)
        SELF_TEST_RUNS["inline"] += 1
        SELF_TEST_RUNS["one_fail"] += len(got) == 1 and needle in got[0]
        if not any(needle in g for g in got):
            problems.append(f"self-test: mutation '{name}' did not trip its gate ({needle})")
        elif len(got) != 1:
            problems.append(
                f"self-test: mutation '{name}' gave {len(got)} FAILs (only its own expected): "
                + " / ".join(got)
            )

    inv = ("### 3.2 ", "## 4. ")
    # the fit gate: put Drawings (same symbol only) back into a 160 px column box
    longer = "Drawings (same symbol only) and every overlay annotation across the group"
    expect(
        "lengthen the Drawings label past its full-width box",
        spec,
        "fit: the switch label",
        switches=tuple(
            (longer if lb.startswith("Drawings") else lb, cs, pl) for lb, cs, pl in SWITCHES
        ),
    )
    hc = popover_report()["height"]["compact"]
    expect(
        "mis-quote the popover height in 5.1",
        in_section(
            spec,
            "### 5.1 ",
            "### 5.2 ",
            lambda t: t.replace(f"{hc} px compact", f"{hc + 1} px compact"),
        ),
        "popover: section 5.1",
    )
    expect(
        "mis-quote the popover height on the popover-1920 row",
        in_section(
            spec,
            *inv,
            lambda t: edit_row(
                t,
                r"^\| `SCR-023/popover-1920` .*$",
                lambda ln: ln.replace(f"{hc} px", f"{hc + 1} px"),
            ),
        ),
        "number: the 1920 frame",
    )
    expect(
        "drop the provenance from the environment frame",
        in_section(
            spec,
            *inv,
            lambda t: edit_row(
                t,
                r"^\| `SCR-023/account-env-refused` .*$",
                lambda ln: ln.replace(
                    'each with its provenance line "BTCUSDT · symbol set by sync group A"', ""
                ),
            ),
        ),
        "provenance: frame SCR-023/account-env-refused",
    )
    expect(
        "keep the held DOM armed and following",
        in_section(
            spec,
            *inv,
            lambda t: edit_row(
                t,
                r"^\| `SCR-023/symbol-switch-hold` .*$",
                lambda ln: ln.replace(
                    "held: armed (group A is on ETHUSDT)",
                    "held: armed (group A is on ETHUSDT), the ticket armed and following group A",
                ),
            ),
        ),
        "armed: frame SCR-023/symbol-switch-hold",
    )
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
                lambda ln: set_cell(ln, 3, "T2 (unavailable row) + outcome notice"),
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
                t,
                r"^\| `SCR-023/popover-1280` .*$",
                lambda ln: set_cell(ln, 4, "none on open; lock glyph"),
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
        "conflict: frame SCR-023/conflict-interval lacks the full notice sentence",
    )
    expect(
        "keep the ticket armed after a sync symbol switch",
        in_section(
            spec,
            *inv,
            lambda t: edit_row(
                t,
                r"^\| `SCR-023/symbol-switch-disarm` .*$",
                lambda ln: ln.replace(
                    "`LOCKED` too", "`LOCKED` too; the order ticket on ETHUSDT keeps it armed"
                ),
            ),
        ),
        "armed: frame SCR-023/symbol-switch-disarm draws an armed state surviving",
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
        "badge: the §4.1 table lacks its comfortable row",
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
    # the frame-level mutation table: each mutation trips its own message exactly once
    expects = [e for _m, e, _ed in MUTATIONS]
    if len(set(expects)) != len(expects):
        problems.append("self-test: two mutations share a FAIL message")
    for mid, want, edits in MUTATIONS:
        try:
            s2, h2 = apply_mutation(spec, handoff, edits)
        except ValueError as exc:
            problems.append(f"self-test: {mid} cannot be applied ({exc})")
            continue
        got = gates(s2, h2, tool, bindings)
        SELF_TEST_RUNS["table"] += 1
        SELF_TEST_RUNS["one_fail"] += len(got) == 1 and want in got[0]
        hits = sum(want in g for g in got)
        if hits != 1:
            problems.append(f"self-test: {mid} tripped '{want}' {hits} times (once expected)")
        elif len(got) != 1:
            problems.append(
                f"self-test: {mid} gave {len(got)} FAILs (only its own expected): "
                + " / ".join(got)
            )
    # the in-memory mutations never touch the files: both are byte-identical after the run
    if (SPEC.exists() and read(SPEC) != spec) or (HANDOFF.exists() and read(HANDOFF) != handoff):
        problems.append("self-test: the spec or the hand-off on disk changed during the run")
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
    markers = build_markers(spec, handoff) if spec else {}
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
        for d, fits in pop["fits"].items():
            for ft in fits:
                p(
                    f"  fit {d:12s} {ft['place']:6s} box {ft['box']:3d}: label '{ft['label']}' "
                    f"{ft['label_w']} px ({ft['label_lines']} line), consequence {ft['cons_w']} px "
                    f"({ft['cons_lines']} line(s))"
                )
        p(f"  switch rows: {pop['switch_rows']}; label overflows: {pop['label_overflows']}")
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
            r_ = SELF_TEST_RUNS
            p(
                "SELF-TEST: "
                + (
                    f"{r_['inline'] + r_['table']} mutations ({r_['inline']} inline + "
                    f"{r_['table']} table), {r_['one_fail']} with their own FAIL as the only one"
                    if not st
                    else "; ".join(st)
                )
            )
        p("RESULT: " + ("PASS" if not fails else "FAIL — " + "; ".join(fails)))
    return 1 if (a.check or a.self_test) and fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
