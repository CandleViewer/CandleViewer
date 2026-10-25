#!/usr/bin/env python3
"""E15-D05 presets-and-switcher audit: every number the hi-fi spec quotes, from the repo, plus the per-frame gates.

Standalone, offline, stdlib only (run with ``python3 -I``); it imports the repo's own measurement helpers
(``packages/ui/tokens/tests/verify_tokens.py`` for the theme layering and token resolution,
``docs/design/_tools/contrast_check.py`` for the WCAG ratio, ``docs/research/_tools/cvd_simulate.py`` for the
deficiency matrices and dE76), so no formula is re-implemented here. Sections, each row labelled with its source:

1. Gallery geometry (CMP-043 ``lg``: 960x640 at 1920x1080 and 920x620 at 1280x800, E15-D02 section 5.6, carried):
   the dialog padding from the tokens, the header and footer rows per UI density (``16`` section 3: compact 24 px
   controls, comfortable 32), the card grid (columns from a minimum card width, the card and thumbnail size, the
   card height from the longest contents line measured with the shared pill-label width rule), the Your layouts
   section's visible rows (the listbox keeps a card row and a half), whether the listbox scrolls, the fit inside the
   1280x800 canvas (E15-D02 section 3: 1168x672), the 200 % zoom viewport (640x400 CSS px, the modal between the
   80 px TopBar and the 48 px StatusBar less 16 px a side, where the body is the one scroll container and a card
   is a row: the thumbnail beside its text) and the 125 / 150 % in-app text scales; a gate asserts that a whole
   card fits its scroll viewport at every step.
2. Thumbnails: the eleven inventory entries (E15-D01 section 2.2's order without 3+1), each with a geometry signature
   and a glyph set; the smallest cell and whether a 12 px glyph and the kind word (font.size.2xs) fit; the C(11,2)
   pairs with the feature that tells each pair apart (geometry first, then glyphs + label); each accessible name
   carries its geometry's arrangement words; the glyph names the thumbnails need, none of which the repo's registry
   (not shipped; E05-T06) can confirm, so each is a request, never drawn as shipped.
3. The layout menu (CMP-217): row heights per density, the menu width from its widest label and chip, its height
   for 4 / 9 / 12 / 32 saved layouts against the canvas below the tab strip at both widths, and the first layout
   count at which it scrolls.
4. The rail (SCR-011): 240 / 64 px (carried), the fixed rows, the workspace rows that fit at 24 / 32 px rows at both
   widths with and without the search field, 32 x 24 and 32 x 32 against them, the search threshold carried from
   E15-D02 D-8.
5. The measured matrix: every fg / bg pair the spec's section 13 lists x dark / light / high-contrast, resolved as
   ``verify_tokens.py`` layers ``themes.json``, measured with ``contrast_check.contrast_ratio()``, each with its
   Rec. 601 greyscale twin; thresholds 4.5:1 text (7:1 in high-contrast), 3:1 non-text; gated rows 0 FAIL; the
   availability grey, the validity look and the skeleton reported, never gated.
6. CVD rows: the selected-card ring and the current-row bar under protanopia / deuteranopia / tritanopia and
   greyscale (reported; text and weight carry the meaning).
7. Keys: every chord drawn is in ``apps/web/src/keymap/keymap.json`` (ranges expanded), a component key, or marked
   PROPOSED after it; ``Ctrl+Shift+S`` has no entry in ``reserved-keys.json`` (asserted).
8. Reasons and copy: the T2 reason strings are E15-D02 section 8.1's keys with their character counts (<= 60);
   the footer sentences fit one line; the accessible names of the inventory carry no forbidden word.
9. String gates on the spec, the hand-off and the PR body: the one T2 rule stated once and cited from every gated
   section; the view-as leg first; no closing keyword; no local path, user name, notes folder or design-tool host
   (generic patterns, never the words); every section-0 board row PENDING; no placeholder; the frame names of
   section 0 = the state inventory = the hand-off's count; ``15`` refused in ``--files``; the ``14`` write-back
   lines present and the SCR-022 sketch and Data line unchanged.
10. Frame-keyed gates (the A2 list): every element is required on the state-inventory rows that draw it, by frame
    id, never on a ruling sentence, and read clause by clause with a case-insensitive vocabulary per ruled sentence
    (text round 1): the Spine cell is exactly its surface's bare noun phrase and no other surface's noun stands in
    any other cell; no key word (a chord, "hotkey", "chip", "Kbd", a bare F-key) on a preset-card clause, in the
    rows or the section 5.2 / 6.2 prose, and on a named preset card (a preset name beside "card" or "thumbnail",
    or "preset") in any row or prose unit whatever its subject; the trigger carries no key chip inline (merged
    E15-D03 D-9); the dirty marker in the row name, never moved to a tab, tooltip or toolbar; no prompt, dialog,
    toast, confirm or "Save first?" on a switch frame or in section 10.3 unless directly negated; the footer
    carriers on every gallery frame; the one T2's anatomy on every T2 frame (C-16's four frames name their gated
    writes) and the T2 form on no other row; no lock, inert or can't-be-pressed wording on a T1 control (Apply,
    Browse presets…, Rename… outside C-16's frames, Discard changes, a switch, Open, Keep current symbols, an
    exit) or in an Exits cell; no account or environment control on these surfaces; no one-click delete in any
    wording; every number a frame draws equals a name the frame registers; every chord outside the keymap's
    Global / Workspace contexts marked PROPOSED (rows, board rows, copy deck, key rows and the prose of sections
    4-12), a bare F-key never drawn (RULED Q-22); unmerged siblings never pinned or quoted, merged E15-D08 cited
    at its merge sha and never PENDING; the inventory's order, counts, cut preset and card notes; each `14` line
    present exactly once.
    The delta fold carries every ruled sentence to the whole spec and the whole hand-off: each table row and each
    prose sentence is one unit, read clause by clause, case-insensitively (no key chip on the trigger, no key on a
    preset card, no prompt on a switch, the dirty marker in the row name, no lock wording on a T1 control, no
    account or environment control, a preset never a saved workspace, no bare F-key, every chord bound or
    PROPOSED); the load error on board 08's row, section 12 and the hand-off's section A; C-16's frame count and
    OQ-6 closed; the SCR-029 route's Tab order, focus return and D08-A22 as merged E15-D08 states them.
    The boards-PR fold closes the gate vocabulary: a sentence opening on "It" / "This" takes the previous
    sentence's subject; "not available", "no longer available" and "can't be used" are lock words; click,
    choose and select are switch verbs; a hand-off row's Variant / Element cell sets the row's subject.
11. Numbers: the ``audit:`` block at the end of the spec equals ``--json``'s markers; every counted number the prose
    types sits in a registered context bound to a marker, a token size or a carried literal of ``CONSTS`` (printed
    under ``constants``); every W x H and two-decimal ratio in the spec and the hand-off is one the tool derives;
    the section 13 table rows equal the tool's; the hand-off's typed numbers (its notes, the Density table,
    Tables 1 and 2) sit in registered contexts too.

Usage: python3 -I docs/design/_tools/e15_d05_presets_audit.py [--json] [--check] [--table] [--pairs]
       [--self-test] [--pr-body FILE] [--files PATH ...]
A plain run prints every section and exits 0; ``--check`` exits 1 on any gated FAIL; ``--self-test`` mutates the
spec in memory and proves that every frame-level ``MUTATIONS`` row trips its own FAIL message exactly once and no
other, the files untouched; ``--table`` prints section 5 as a Markdown table; ``--pairs`` prints section 2's pair
table; ``--pr-body`` runs the hygiene and closing-keyword gates on a PR body; ``--files`` refuses a path under
the component catalogue, the API contract, the WS protocol or the internal schemas. UTF-8 stdout. No network; no
URL literal anywhere in this file.
"""

from __future__ import annotations

import argparse
import copy
import functools
import importlib.util
import itertools
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
SPEC = ROOT / "docs" / "design" / "E15" / "E15-D05.md"
HANDOFF = ROOT / "docs" / "design" / "E15" / "E15-D05-handoff.md"
CATALOGUE = ROOT / "docs" / "plan" / "14-screens-catalogue.md"
KEYMAP = ROOT / "apps" / "web" / "src" / "keymap" / "keymap.json"
RESERVED = ROOT / "apps" / "web" / "src" / "keymap" / "reserved-keys.json"
PRESETS_PY = ROOT / "services" / "api" / "candleviewer" / "api" / "workspaces_presets.py"
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
_THEME_CACHE: dict[str, dict[str, Any]] = {}


def theme(name: str) -> dict[str, Any]:
    if name not in _THEME_CACHE:
        files = [verify.PRIMITIVES, *verify.THEMES[name]]
        _THEME_CACHE[name] = verify.merged_set(files)
    return _THEME_CACHE[name]


def tok(name: str, th: str = "dark") -> Any:
    t = theme(th)
    if name not in t:
        raise KeyError(name)
    return verify.resolve(t[name]["$value"], t)


def num_tok(name: str) -> int:
    return int(float(tok(name)))


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


def sim(h: str, kind: str) -> str:
    s: str = cvd.simulate(h, kind)
    return s.upper()


def fmt(x: float) -> str:
    return f"{x:.2f}"


# ---- the shared pill-label width rule (per glyph class, an upper bound on Inter's advance in em) ----
PILL_EM = {
    "upper": 0.84,
    "wide_lower": 0.95,
    "lower": 0.56,
    "digit": 0.68,
    "thin": 0.34,
    "symbol": 1.0,
}


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


def lines_for(text: str, box_w: int, size: float) -> int:
    """Greedy word wrap with the pill-label rule per word; a word never breaks."""
    words = text.split(" ")
    lines, cur = 1, 0
    space = label_w(" ", size)
    for w in words:
        ww = label_w(w, size)
        if cur == 0:
            cur = ww
        elif cur + space + ww <= box_w:
            cur += space + ww
        else:
            lines += 1
            cur = ww
    return lines


def line_h(size: float, lh: float) -> int:
    return math.ceil(size * lh)


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


# ---------------------------------------------------------------- fixtures and carried constants -----------
WIDTHS = {"1920": (1920, 1080), "1280": (1280, 800)}
TOPBAR_H, STATUSBAR_H = 80, 48  # E10-D02's shell rows as E15-D02 section 3 states them
RAIL_COLLAPSED, RIGHT_RAIL = 64, 48  # E15-D02 section 3: the canvas is the body less both rails
TAB_STRIP = {"compact": 32, "comfortable": 40}  # E15-D02 section 3, SCR-020's row
GALLERY = {
    "1920": (960, 640),
    "1280": (920, 620),
}  # E15-D02 section 5.6, carried (CMP-043 lg caps at 960)
RAIL_EXPANDED = 240  # E15-D02 section 5.2, carried
ZOOM200 = (640, 400)  # 1280x800 at 200 % browser zoom, in CSS px
MODAL_MARGIN = 16  # kept around a dialog at 200 % (E15-D02 D-7 keeps the bars unscrimmed)
TEXT_SCALES = (
    125,
    150,
)  # the in-app text-scale steps the spec measures (`16` section 3 runtime contract)
DENSITIES = ("compact", "comfortable")
SEARCH_THRESHOLD = (
    20  # E15-D02 D-8: CMP-073's combobox searches the rail above 20 workspaces (carried)
)
WORKSPACE_CAP, LAYOUT_CAP, HOTKEY_SLOTS = (
    32,
    32,
    9,
)  # `22` listWorkspaces, listLayouts, LayoutInput.hotkey_slot
TWELVE = 12  # the ticket's AC 5 fixture: twelve saved layouts
SEARCH_FIXTURE = 24  # E15-D02 :304: the search frame's fixture holds 24 workspaces (carried)
MIN_CARD_W = 160  # PROPOSED: the narrowest preset card (the thumbnail stays legible, section 2)
CARD_GUTTER = 16  # space.4 between cards (the grid gap)
THUMB_ASPECT = 0.6  # PROPOSED: thumbnail height / width
THUMB_GAP = 2  # between thumbnail cells
GLYPH_PX = 12  # size.icon.sm (`15` CMP-019)


def thumb_word_px() -> int:
    """The kind word inside a thumbnail cell: font.size.2xs, the smallest token (pre-PR lens round 1 F-9)."""
    return tokens_px()["font_2xs"]


YL_LISTBOX_PEEK = "size.row.compact"  # PROPOSED: the listbox keeps one full card row and a row-height peek of the next
LH_TIGHT, LH_NORMAL = 1.2, 1.4  # font.lineheight.tight / .normal (resolved below where bound)


def canvas(width: str) -> tuple[int, int]:
    w, h = WIDTHS[width]
    return w - RAIL_COLLAPSED - RIGHT_RAIL, h - TOPBAR_H - STATUSBAR_H


def tokens_px() -> dict[str, int]:
    """The sizes the layout binds, resolved from the tokens (never typed)."""
    return {
        "dialog_pad": num_tok("space.dialog.padding"),
        "inset_md": num_tok("space.inset.md"),
        "inset_sm": num_tok("space.inset.sm"),
        "inset_xs": num_tok("space.inset.xs"),
        "stack_sm": num_tok("space.stack.sm"),
        "control_compact": num_tok("size.control.compact"),
        "control_comfortable": num_tok("size.control.comfortable"),
        "row_compact": num_tok("size.row.compact"),
        "row_comfortable": num_tok("size.row.comfortable"),
        "icon_sm": num_tok("size.icon.sm"),
        "icon_md": num_tok("size.icon.md"),
        "font_base": num_tok("font.size.base"),
        "font_xs": num_tok("font.size.xs"),
        "font_2xs": num_tok("font.size.2xs"),
        "font_sm": num_tok("font.size.sm"),
        "font_md": num_tok("font.size.md"),
    }


# ---------------------------------------------------------------- 2. the inventory --------------------------
# Order: E15-D01 section 2.2 without 3+1 (E15-D02 AD-3, A-8; E15-D01 AM-2). Ids: the served uuid or PROPOSED (G-1).
# Composition words are the contract's PaneKind values; "footprint" is a chart pane (E15-D01 :143).
# Geometry signatures: cols3 = three equal columns; 1+2 = one large cell and two stacked; 1+3 = one large and three.
Preset = dict[str, Any]
INVENTORY: tuple[Preset, ...] = (
    {
        "label": "Scalping",
        "served": None,
        "panels": 3,
        "sig": "1+2",
        "cells": ["chart", "dom", "tape"],
        "name": "Scalping: one large chart beside the DOM ladder and tape, stacked, three panels; the order ticket opens as a drawer",
        "alt": "Scalping: chart, DOM ladder, tape",
        "line": "Chart, DOM and tape for one instrument.",
        "l1": "Scalping",
        "l2": "Scalper DOM",
        "note": "the order ticket opens as its drawer (M-001)",
    },
    {
        "label": "Order-flow",
        "served": None,
        "panels": 4,
        "sig": "2x2",
        "cells": ["footprint", "cvd", "profile", "chart"],
        "name": "Order-flow: two by two — footprint chart, CVD, profile and chart, four panels",
        "alt": "Order-flow: footprint chart, CVD, volume profile, chart",
        "line": "Footprint, CVD and profile around one chart.",
        "l1": "Order-flow",
        "l2": "Footprint focus",
        "note": "",
    },
    {
        "label": "Swing",
        "served": None,
        "panels": 3,
        "sig": "cols3",
        "cells": ["chart", "chart", "chart"],
        "name": "Swing: three charts side by side, one instrument on three timeframes, three panels",
        "alt": "Swing: chart 4h, chart 1h, chart 15m",
        "line": "Three timeframes of one instrument.",
        "l1": "Swing 3TF",
        "l2": "",
        "note": "",
    },
    {
        "label": "2×2",
        "served": "2x2",
        "panels": 4,
        "sig": "2x2",
        "cells": ["chart"] * 4,
        "name": "Two by two: four charts in a grid, four panels",
        "alt": "Two by two: chart, chart, chart, chart",
        "line": "",
        "l1": "2×2",
        "l2": "Multi-chart 2x2",
        "note": "",
    },
    {
        "label": "1+3",
        "served": "1+3",
        "panels": 4,
        "sig": "1+3",
        "cells": ["chart"] * 4,
        "name": "One plus three: one large chart beside three small ones, stacked, four panels",
        "alt": "One plus three: chart, chart, chart, chart",
        "line": "",
        "l1": "1+3",
        "l2": "",
        "note": "",
    },
    {
        "label": "Fan-out review",
        "served": None,
        "panels": 2,
        "sig": "2x1",
        "cells": ["positions", "chart"],
        "name": "Fan-out review: positions by account beside a chart, two panels; the trade-group ticket opens as its modal",
        "alt": "Fan-out review: positions by account, chart",
        "line": "Positions by account beside a chart.",
        "l1": "Fan-out review",
        "l2": "",
        "note": "the trade-group ticket opens as its modal (SCR-061)",
    },
    {
        "label": "Analyst",
        "served": None,
        "panels": 2,
        "sig": "1x2",
        "cells": ["chart", "journal"],
        "name": "Analyst: chart and journal, stacked, two panels; Replay opens on its own page",
        "alt": "Analyst: chart, journal",
        "line": "Chart and journal, read-only.",
        "l1": "Analyst",
        "l2": "Analysis/journal; Replay (a page, no pane kind)",
        "note": "Replay opens on its own page",
    },
    {
        "label": "2×1",
        "served": "2x1",
        "panels": 2,
        "sig": "2x1",
        "cells": ["chart", "chart"],
        "name": "Two by one: two charts side by side, two panels",
        "alt": "Two by one: chart, chart",
        "line": "",
        "l1": "2×1",
        "l2": "",
        "note": "",
    },
    {
        "label": "1×2",
        "served": "1x2",
        "panels": 2,
        "sig": "1x2",
        "cells": ["chart", "chart"],
        "name": "One by two: two charts stacked, two panels",
        "alt": "One by two: chart, chart",
        "line": "",
        "l1": "",
        "l2": "",
        "note": "",
    },
    {
        "label": "3×3",
        "served": "3x3",
        "panels": 9,
        "sig": "3x3",
        "cells": ["chart"] * 9,
        "name": "Three by three: nine charts in a grid, nine panels",
        "alt": "Three by three: nine charts",
        "line": "",
        "l1": "",
        "l2": "",
        "note": "Nine panels: every performance budget assumes four (US-LAY-001)",
    },
    {
        "label": "1×1",
        "served": "1x1",
        "panels": 1,
        "sig": "1x1",
        "cells": ["chart"],
        "name": "One by one: one chart, one panel",
        "alt": "One by one: chart",
        "line": "",
        "l1": "1×1",
        "l2": "",
        "note": "",
    },
)
CUT_PRESET = "3+1"  # E15-D01 AM-2 / E15-D02 AD-3: not in `22` LayoutGridPreset
FORBIDDEN_NAME_WORDS = (
    "this",
    "left",
    "right",
    "top",
    "bottom",
    "above",
    "below",
    "upper",
    "lower",
    "corner",
)
GLYPH_FOR = {
    "chart": "chart",
    "footprint": "chart",
    "dom": "dom",
    "tape": "tape",
    "cvd": "cvd",
    "profile": "profile",
    "positions": "positions",
    "journal": "journal",
}
CELL_WORD = {
    "chart": "chart",
    "footprint": "footprint",
    "dom": "DOM",
    "tape": "tape",
    "cvd": "CVD",
    "profile": "profile",
    "positions": "positions",
    "journal": "journal",
}
# the glyph names the thumbnails need: PaneKind words; the base registry (E05-T06, not in the repo) has none of
# them, so every one is a request to the registry's owner (spec G-row), never drawn as shipped
GLYPH_REQUESTS = ("chart", "dom", "tape", "cvd", "profile", "positions", "journal")
SIG_WORDS = {
    "1x1": "one cell",
    "2x1": "two columns",
    "1x2": "two rows",
    "2x2": "a two-by-two grid",
    "1+3": "one large cell and three stacked",
    "3x3": "a three-by-three grid",
    "cols3": "three columns",
    "1+2": "one large cell and two stacked",
}
# The words an accessible name must carry for its geometry (ticket Sc. 1: the arrangement AND the composition
# from text alone; pre-PR lens round 1 F-1): any one alternative per signature, matched case-insensitively.
ARRANGEMENT_WORDS: dict[str, tuple[str, ...]] = {
    "1x1": ("one chart",),
    "2x1": ("side by side", "beside"),
    "1x2": ("stacked",),
    "2x2": ("two by two",),
    "1+3": ("one large chart beside three",),
    "3x3": ("three by three",),
    "cols3": ("three charts side by side", "three columns"),
    "1+2": ("one large chart beside",),
}


def served_presets() -> dict[str, dict[str, Any]]:
    """The six built-in entries as the API serves them (the file is read, never retyped)."""
    out: dict[str, dict[str, Any]] = {}
    text = read(PRESETS_PY)
    idm = re.search(r'f"(15000000-0000-4000-8000-00000000020)\{n\}"', text)
    stem = idm.group(1) if idm else ""
    for n, name, cells, desc in re.findall(r'_entry\((\d), "([^"]+)", (\d+), "([^"]+)"\)', text):
        out[name] = {"id": f"{stem}{n}", "pane_count": int(cells), "description": desc, "n": int(n)}
    return out


def cells_of(sig: str, tw: int, th: int) -> list[tuple[int, int]]:
    """The (w, h) of every thumbnail cell for a geometry signature, with the gap taken out."""
    g = THUMB_GAP

    def grid(c: int, r: int) -> list[tuple[int, int]]:
        return [((tw - g * (c - 1)) // c, (th - g * (r - 1)) // r)] * (c * r)

    if sig in ("1x1", "2x1", "1x2", "2x2", "3x3"):
        c, r = int(sig[0]), int(sig[2])
        return grid(c, r)
    if sig == "cols3":
        return grid(3, 1)
    big = round(tw * 0.6)
    small_w = tw - big - g
    n = 3 if sig == "1+3" else 2
    small_h = (th - g * (n - 1)) // n
    return [(big, th)] + [(small_w, small_h)] * n


def inventory_report(card_thumb: dict[str, tuple[int, int]]) -> dict[str, Any]:
    served = served_presets()
    rows = []
    for i, p in enumerate(INVENTORY, start=1):
        s = served.get(p["served"] or "")
        row = {
            "order": i,
            "label": p["label"],
            "panels": p["panels"],
            "sig": p["sig"],
            "id": s["id"] if s else "PROPOSED",
            "served": bool(s),
            "served_pane_count": s["pane_count"] if s else None,
            "line": s["description"] if s else p["line"],
            "line_chars": len(s["description"] if s else p["line"]),
            "glyphs": sorted({GLYPH_FOR[c] for c in p["cells"]}),
            "name": p["name"],
            "alt": p["alt"],
            "note": p["note"],
            "l1": p["l1"],
            "l2": p["l2"],
            "name_forbidden": [
                w for w in FORBIDDEN_NAME_WORDS if re.search(rf"\b{w}\b", p["name"], re.IGNORECASE)
            ],
            "name_arrangement": any(w in p["name"].lower() for w in ARRANGEMENT_WORDS[p["sig"]]),
            "cells": {},
        }
        word_px = thumb_word_px()
        for where, (tw, th) in card_thumb.items():
            cells = cells_of(p["sig"], tw, th)
            mw, mh = min(c[0] for c in cells), min(c[1] for c in cells)
            words = [CELL_WORD[c] for c in p["cells"]]
            widest = max(label_w(w, word_px) for w in words)
            row["cells"][where] = {
                "min_w": mw,
                "min_h": mh,
                "glyph_fits": mw >= GLYPH_PX + 4 and mh >= GLYPH_PX + 4,
                "word_fits": widest <= mw - 6 and mh >= GLYPH_PX + line_h(word_px, LH_TIGHT) + 4,
                "widest_word_px": widest,
            }
        rows.append(row)
    pairs = []
    for a, b in itertools.combinations(rows, 2):
        if a["sig"] != b["sig"]:
            how, feature = "geometry", f"{SIG_WORDS[a['sig']]} vs {SIG_WORDS[b['sig']]}"
        else:
            how = "glyphs + label"
            feature = f"{', '.join(a['glyphs'])} vs {', '.join(b['glyphs'])}; the name"
        pairs.append({"a": a["label"], "b": b["label"], "how": how, "feature": feature})
    return {
        "rows": rows,
        "count": len(rows),
        "served_count": sum(1 for r in rows if r["served"]),
        "proposed_ids": sum(1 for r in rows if not r["served"]),
        "panel_total": sum(r["panels"] for r in rows),
        "cut": CUT_PRESET,
        "pairs": pairs,
        "pair_count": len(pairs),
        "pairs_by_geometry": sum(1 for q in pairs if q["how"] == "geometry"),
        "pairs_by_glyphs": sum(1 for q in pairs if q["how"] != "geometry"),
        "glyph_requests": list(GLYPH_REQUESTS),
        "glyph_request_count": len(GLYPH_REQUESTS),
        "served_api": served,
    }


def pairs_table(inv: dict[str, Any]) -> str:
    out = ["| # | Pair | Told apart by | Feature |", "| --- | --- | --- | --- |"]
    for i, q in enumerate(inv["pairs"], start=1):
        out.append(f"| {i} | {q['a']} · {q['b']} | {q['how']} | {q['feature']} |")
    return "\n".join(out)


# ---------------------------------------------------------------- 1. gallery geometry -----------------------
FOOTER_WARNING = (
    "Applying a preset replaces the current layout. Settings of surviving panels are kept."
)
FOOTER_SENTENCE = (
    "Applying a preset changes the arrangement only — never the selected account or environment."
)
EMPTY_SENTENCE = (
    "Layout 1 is this workspace's only layout. Save the current arrangement as a new layout "
    "(Ctrl+Shift+S) to switch between layouts with Ctrl+1..9."
)
YOUR_LAYOUTS_FIXTURE = (
    "Layout 1",
    "Order-flow",
    "Wide chart",
    "Swing check",
)  # E15-D02 section 5.6
YL_NAME_W = 240  # PROPOSED: the inline Rename field; a 40-character name scrolls inside it


def gallery_layout(
    width: str, dens: str = "compact", scale: int = 100, zoom200: bool = False
) -> dict[str, Any]:
    """The gallery's rows at one width x density x text scale (or the 200 % modal)."""
    t = tokens_px()
    k = scale / 100
    pad, gutter = t["dialog_pad"], CARD_GUTTER
    ctrl = t["control_compact"] if dens == "compact" else t["control_comfortable"]
    body_px, cap_px = t["font_base"] * k, t["font_xs"] * k
    body_lh, cap_lh = line_h(body_px, LH_NORMAL), line_h(cap_px, LH_TIGHT)
    if zoom200:
        vw, vh = ZOOM200
        between = vh - TOPBAR_H - STATUSBAR_H
        W, H = vw - 2 * MODAL_MARGIN, between - 2 * MODAL_MARGIN
        pad = t["inset_md"]  # the reflowed dialog keeps the inset, not the dialog padding
    else:
        W, H = GALLERY[width]
    header = (
        ctrl + 2 * t["inset_sm"] + (body_lh - ctrl if body_lh > ctrl else 0)
    )  # title row with the close button
    if (
        zoom200
    ):  # one sticky row: the checkbox, Apply and Cancel; the two sentences lead the scrolling body
        footer = 2 * t["inset_sm"] + ctrl
        sentences_block = 2 * cap_lh + t["inset_xs"] + t["inset_sm"]
    else:
        footer = (
            t["inset_md"] + max(ctrl, body_lh) + t["inset_xs"] + cap_lh + 2 + cap_lh + t["inset_md"]
        )
        sentences_block = 0
    inner_w = W - 2 * pad
    cols = max(1, (inner_w + gutter) // (MIN_CARD_W + gutter))
    card_w = (inner_w - gutter * (cols - 1)) // cols
    card_pad = t["inset_md"]
    if zoom200:
        # pre-PR lens round 1 F-2: at 200 % no card can be whole inside a nested listbox, so the body is the one
        # scroll container and a card is a ROW — the thumbnail at the left (the width the three-column grid
        # would give it: 160 CSS px, the size section 2 measures the words at), the name, contents and count
        # beside it; one column, so every card is as tall as its thumbnail and fits the scroll viewport.
        cols = 1
        card_w = inner_w
        thumb_w = (inner_w - 2 * gutter) // 3 - 2 * card_pad
    else:
        thumb_w = card_w - 2 * card_pad
    thumb_h = round(thumb_w * THUMB_ASPECT)
    text_w = card_w - 2 * card_pad - thumb_w - t["inset_md"] if zoom200 else thumb_w
    served = served_presets()
    card_lines = []
    for p in INVENTORY:
        s = served.get(p["served"] or "")
        contents = s["description"] if s else p["line"]
        n = lines_for(contents, text_w, cap_px) + (
            lines_for(p["note"], text_w, cap_px) if p["note"] else 0
        )
        card_lines.append(n)
    contents_lines = max(card_lines)
    text_h = body_lh + t["inset_xs"] + contents_lines * cap_lh + 2 + cap_lh
    if zoom200:
        card_h = card_pad + max(thumb_h, text_h) + card_pad
    else:
        card_h = card_pad + thumb_h + t["inset_sm"] + text_h + card_pad
    card_rows = math.ceil(len(INVENTORY) / cols)
    listbox_full = card_rows * card_h + (card_rows - 1) * gutter
    body = H - header - footer - 2 * pad - sentences_block
    yl_heading = cap_lh + t["inset_sm"]
    yl_row, yl_gap = ctrl, t["inset_xs"]
    peek = num_tok(YL_LISTBOX_PEEK)
    listbox_min = card_h + peek + gutter
    if zoom200:
        yl_rows_visible = 0  # the section collapses into a disclosure row
        yl_h = ctrl
        # the scroll viewport: everything between the header and the sticky footer scrolls as one
        scroll = H - header - footer
        listbox_visible = (
            listbox_full  # the listbox lays out at its full height inside the scrolling body
        )
    else:
        yl_max = body - listbox_min - t["inset_md"]
        yl_rows_visible = max(1, (yl_max - yl_heading + yl_gap) // (yl_row + yl_gap))
        yl_h = yl_heading + yl_rows_visible * yl_row + (yl_rows_visible - 1) * yl_gap
        listbox_visible = body - yl_h - t["inset_md"]
        scroll = listbox_visible  # the nested listbox is the card's scroll viewport
    rows_visible = scroll / (card_h + gutter)
    sentence_w = label_w(FOOTER_SENTENCE, cap_px)
    warning_w = label_w(FOOTER_WARNING, cap_px)
    picker_w = label_w("(no key) ▾", t["font_sm"] * k) + 2 * t["inset_sm"]
    delete_w = label_w("Delete…", body_px) + 2 * t["inset_md"]
    kinds_w = inner_w - YL_NAME_W - picker_w - delete_w - 3 * t["inset_md"]
    return {
        "width": W,
        "height": H,
        "pad": pad,
        "gutter": gutter,
        "header": header,
        "footer": footer,
        "sentences_block": sentences_block,
        "peek": peek,
        "yl_name_w": YL_NAME_W,
        "yl_picker_w": picker_w,
        "yl_delete_w": delete_w,
        "yl_kinds_w": kinds_w,
        "body": body,
        "inner_w": inner_w,
        "cols": cols,
        "card_w": card_w,
        "card_h": card_h,
        "thumb_w": thumb_w,
        "thumb_h": thumb_h,
        "card_rows": card_rows,
        "contents_lines": contents_lines,
        "listbox_full": listbox_full,
        "listbox_visible": listbox_visible,
        "scroll": scroll,
        "card_fits_scroll": card_h <= scroll,
        "listbox_scrolls": listbox_full > listbox_visible,
        "card_rows_visible": math.floor(rows_visible * 10) / 10,
        "yl_rows_visible": yl_rows_visible,
        "yl_h": yl_h,
        "yl_row": yl_row,
        "yl_fixture_scrolls": len(YOUR_LAYOUTS_FIXTURE) > yl_rows_visible,
        "twelve_scrolls": TWELVE > yl_rows_visible,
        "sentence_w": sentence_w,
        "sentence_one_line": sentence_w <= inner_w,
        "warning_w": warning_w,
        "warning_one_line": warning_w <= inner_w,
        "empty_lines": lines_for(EMPTY_SENTENCE, inner_w, body_px),
        "body_px": body_px,
        "cap_px": cap_px,
        "body_lh": body_lh,
        "cap_lh": cap_lh,
        "ctrl": ctrl,
    }


def gallery_report() -> dict[str, Any]:
    out: dict[str, Any] = {"canvas": {w: canvas(w) for w in WIDTHS}, "fits": {}, "layouts": {}}
    for w in WIDTHS:
        gw, gh = GALLERY[w]
        cw, ch = canvas(w)
        out["fits"][w] = gw <= cw and gh <= ch
        for d in DENSITIES:
            out["layouts"][f"{w}-{d}"] = gallery_layout(w, d)
    for s in TEXT_SCALES:
        out["layouts"][f"1280-compact-{s}"] = gallery_layout("1280", "compact", s)
    z = gallery_layout("1280", "compact", 100, zoom200=True)
    z["viewport"] = ZOOM200
    z["between_bars"] = ZOOM200[1] - TOPBAR_H - STATUSBAR_H
    out["zoom200"] = z
    return out


def fit_gates(g: dict[str, Any]) -> list[str]:
    """Every layout step keeps a whole card inside its scroll viewport (pre-PR lens round 1 F-2)."""
    fails: list[str] = []
    steps = dict(g["layouts"])
    steps["zoom200"] = g["zoom200"]
    for step, lay in steps.items():
        if lay["card_h"] > lay["scroll"]:
            fails.append(
                f"zoom: a card ({lay['card_h']} px) is taller than its scroll viewport "
                f"({lay['scroll']} px) at {step}"
            )
    return fails


# ---------------------------------------------------------------- 3. the layout menu (CMP-217) ---------------
MENU_LABELS = ("Save layout", "Save as new layout…", "Revert to saved…", "Browse presets…")
MENU_CHIPS = ("Ctrl+1", "Ctrl+S", "Ctrl+Shift+S", "(no key)")
MENU_FIXED_ROWS = 4  # Save layout, Save as new layout…, Revert to saved…, Browse presets…
MENU_SEPARATORS = 2
MENU_COUNTS = (4, 9, TWELVE, LAYOUT_CAP)


def menu_report() -> dict[str, Any]:
    t = tokens_px()
    sep = 1 + 2 * t["inset_xs"]
    label_px, chip_px = t["font_base"], t["font_sm"]
    widest_label = max(label_w(x, label_px) for x in MENU_LABELS + YOUR_LAYOUTS_FIXTURE)
    widest_chip = max(label_w(x, chip_px) for x in MENU_CHIPS) + 2 * t["inset_sm"]
    menu_w = t["inset_md"] + widest_label + 2 * t["inset_md"] + widest_chip + t["inset_md"]
    out: dict[str, Any] = {
        "separator": sep,
        "menu_w": menu_w,
        "widest_label": widest_label,
        "widest_chip": widest_chip,
        "heights": {},
        "available": {},
        "first_scroll": {},
    }
    for d in DENSITIES:
        row = t["row_compact"] if d == "compact" else t["row_comfortable"]
        for n in MENU_COUNTS:
            out["heights"][f"{d}-{n}"] = (
                2 * t["inset_xs"] + (n + MENU_FIXED_ROWS) * row + MENU_SEPARATORS * sep
            )
        for w in WIDTHS:
            avail = canvas(w)[1] - TAB_STRIP[d] - t["inset_xs"]
            out["available"][f"{w}-{d}"] = avail
            n_first = (
                (avail - 2 * t["inset_xs"] - MENU_SEPARATORS * sep) // row - MENU_FIXED_ROWS + 1
            )
            out["first_scroll"][f"{w}-{d}"] = int(n_first) if n_first <= LAYOUT_CAP else None
    out["twelve_keyed"] = min(TWELVE, HOTKEY_SLOTS)
    out["twelve_nokey"] = TWELVE - min(TWELVE, HOTKEY_SLOTS)
    out["reach_without_key"] = LAYOUT_CAP - HOTKEY_SLOTS
    return out


# ---------------------------------------------------------------- 4. the rail (SCR-011) ----------------------
RAIL_FIXED_ITEMS = (
    "Terminal",
    "New workspace",
    "Rules",
    "Journal",
    "Replay",
    "Alerts",
    "Settings",
    "Admin",
)


def rail_report() -> dict[str, Any]:
    t = tokens_px()
    out: dict[str, Any] = {
        "expanded": RAIL_EXPANDED,
        "collapsed": RAIL_COLLAPSED,
        "fixed_rows": len(RAIL_FIXED_ITEMS),
        "fit": {},
        "stack": {},
        "search_threshold": SEARCH_THRESHOLD,
        "cap": WORKSPACE_CAP,
    }
    for d in DENSITIES:
        row = t["row_compact"] if d == "compact" else t["row_comfortable"]
        out["stack"][d] = WORKSPACE_CAP * row
        for w in WIDTHS:
            h = canvas(w)[1] - 2 * t["inset_sm"]
            for search in (False, True):
                fixed = len(RAIL_FIXED_ITEMS) + (1 if search else 0)
                fit = (h - fixed * row) // row
                key = f"{w}-{d}{'-search' if search else ''}"
                out["fit"][key] = int(fit)
    out["cap_scrolls_everywhere"] = all(v < WORKSPACE_CAP for v in out["fit"].values())
    out["threshold_scrolls_1280_compact"] = SEARCH_THRESHOLD > out["fit"]["1280-compact-search"]
    out["row_w_name_max"] = (
        RAIL_EXPANDED - 3 - t["inset_md"] - t["inset_sm"] - t["icon_md"] - t["inset_sm"]
    )
    return out


# ---------------------------------------------------------------- 5. the measured matrix ---------------------
# (label, fg token, bg token, role, gated?) — the spec's section 13 rows, in this order
PAIRS: tuple[tuple[str, str, str, str, bool], ...] = (
    (
        "card name on the card: `color.text.primary` on `color.surface.raised`",
        "color.text.primary",
        "color.surface.raised",
        "text",
        True,
    ),
    (
        "card contents on the card: `color.text.secondary` on `color.surface.raised`",
        "color.text.secondary",
        "color.surface.raised",
        "text",
        True,
    ),
    (
        "dialog text: `color.text.primary` on `color.surface.overlay`",
        "color.text.primary",
        "color.surface.overlay",
        "text",
        True,
    ),
    (
        "warning and footer lines: `color.text.secondary` on `color.surface.overlay`",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
        True,
    ),
    (
        "selected card ring on the dialog: `color.border.selected` on `color.surface.overlay`",
        "color.border.selected",
        "color.surface.overlay",
        "non-text",
        True,
    ),
    (
        "selected card ring on the card: `color.border.selected` on `color.surface.raised`",
        "color.border.selected",
        "color.surface.raised",
        "non-text",
        True,
    ),
    (
        "focus ring on the dialog: `color.focus.ring` on `color.surface.overlay`",
        "color.focus.ring",
        "color.surface.overlay",
        "non-text",
        True,
    ),
    (
        "focus ring on the rail: `color.focus.ring` on `color.surface.raised`",
        "color.focus.ring",
        "color.surface.raised",
        "non-text",
        True,
    ),
    (
        "key chip (CMP-022): `color.text.primary` on `color.surface.raised`",
        "color.text.primary",
        "color.surface.raised",
        "text",
        True,
    ),
    (
        "T2 label and lock in a menu: `color.text.tertiary` on `color.surface.overlay`",
        "color.text.tertiary",
        "color.surface.overlay",
        "text",
        True,
    ),
    (
        "T2 label on a gated button fill: `color.text.tertiary` on `color.surface.raised`",
        "color.text.tertiary",
        "color.surface.raised",
        "text",
        True,
    ),
    (
        "T2 reason in a menu or dialog: `color.text.secondary` on `color.surface.overlay`",
        "color.text.secondary",
        "color.surface.overlay",
        "text",
        True,
    ),
    (
        "T2 reason under the rail's button: `color.text.secondary` on `color.surface.raised`",
        "color.text.secondary",
        "color.surface.raised",
        "text",
        True,
    ),
    (
        "rail row name and the dirty marker: `color.text.primary` on `color.surface.raised`",
        "color.text.primary",
        "color.surface.raised",
        "text",
        True,
    ),
    (
        "current-row bar: `color.border.selected` on `color.surface.raised`",
        "color.border.selected",
        "color.surface.raised",
        "non-text",
        True,
    ),
    (
        "current row label on its fill (E10-D03 §5.2): `color.text.primary` on `color.surface.selected`",
        "color.text.primary",
        "color.surface.selected",
        "text",
        True,
    ),
    (
        "current-row bar on its fill (E10-D03 §5.2): `color.border.selected` on `color.surface.selected`",
        "color.border.selected",
        "color.surface.selected",
        "non-text",
        True,
    ),
    (
        "open ring glyph (E10-D03 §5.2): `color.text.secondary` on `color.surface.raised`",
        "color.text.secondary",
        "color.surface.raised",
        "non-text",
        True,
    ),
    (
        "inline error glyph (CMP-027; its message is `color.text.primary`): `color.status.danger.strong` on `color.surface.overlay`",
        "color.status.danger.strong",
        "color.surface.overlay",
        "non-text",
        True,
    ),
    (
        "Apply label: `color.text.on-action` on `color.action.primary.default`",
        "color.text.on-action",
        "color.action.primary.default",
        "text",
        True,
    ),
    (
        "Delete layout label (CMP-001 `danger`, the DS pair): `color.text.on-action` on `color.status.danger.default`",
        "color.text.on-action",
        "color.status.danger.default",
        "text",
        False,
    ),
    (
        "hairline: `color.border.default` on `color.surface.overlay`",
        "color.border.default",
        "color.surface.overlay",
        "non-text",
        False,
    ),
    (
        "availability label (not T2): `color.text.disabled` on `color.surface.overlay`",
        "color.text.disabled",
        "color.surface.overlay",
        "text",
        False,
    ),
    (
        "skeleton: `color.surface.hover` on `color.surface.overlay`",
        "color.surface.hover",
        "color.surface.overlay",
        "non-text",
        False,
    ),
)
VALIDITY_ALPHA_TOKEN = "opacity.disabled"


def matrix_report(fails: list[str]) -> dict[str, Any]:
    rows = []
    gated = failed = 0
    for label, fg, bg, role, is_gated in PAIRS:
        r: dict[str, Any] = {
            "label": label,
            "fg": fg,
            "bg": bg,
            "role": role,
            "gated": is_gated,
            "themes": {},
        }
        for th in THEMES:
            f, b = hx(fg, th), hx(bg, th)
            v, g = ratio(f, b), ratio(grey(f), grey(b))
            bar = BAR["hc-text"] if (th == "high-contrast" and role == "text") else BAR[role]
            ok = v >= bar
            r["themes"][th] = {
                "fg": f,
                "bg": b,
                "ratio": fmt(v),
                "grey": fmt(g),
                "pass": ok,
                "bar": bar,
            }
            if is_gated:
                gated += 1
                if not ok:
                    failed += 1
                    fails.append(f"matrix: {label} measures {fmt(v)} in {th} (bar {bar})")
        r["gate"] = "PASS" if all(x["pass"] for x in r["themes"].values()) else "below the bar"
        if not is_gated:
            r["gate"] = "reported — " + r["gate"]
        rows.append(r)
    # the validity look: the Apply label and fill at opacity.disabled over the dialog surface (reported)
    alpha = float(tok(VALIDITY_ALPHA_TOKEN))
    validity = {}
    for th in THEMES:
        over = hx("color.surface.overlay", th)
        fill = blend(hx("color.action.primary.default", th), over, alpha)
        lab = blend(hx("color.text.on-action", th), over, alpha)
        validity[th] = {
            "fill": fill,
            "label": lab,
            "ratio": fmt(ratio(lab, fill)),
            "reason": fmt(ratio(hx("color.text.secondary", th), over)),
        }
    return {
        "rows": rows,
        "gated": gated,
        "failed": failed,
        "pairs": len(PAIRS),
        "validity": validity,
        "validity_alpha": alpha,
    }


def matrix_table(m: dict[str, Any]) -> str:
    out = [
        "| Pair (fg on bg) | Role | Dark | Light | High contrast | Gate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in m["rows"]:
        cells = [f"{r['themes'][th]['ratio']} (grey {r['themes'][th]['grey']})" for th in THEMES]
        out.append(
            f"| {r['label']} | {r['role']} | {cells[0]} | {cells[1]} | {cells[2]} | {r['gate']} |"
        )
    return "\n".join(out)


# ---------------------------------------------------------------- 6. CVD rows --------------------------------
CVD_KINDS = ("protanopia", "deuteranopia", "tritanopia")
CVD_CARRIERS = (
    ("selected ring", "color.border.selected", "color.surface.overlay"),
    ("current bar", "color.border.selected", "color.surface.raised"),
)


def cvd_report() -> dict[str, Any]:
    out: dict[str, Any] = {"kinds": list(CVD_KINDS) + ["greyscale"], "rows": {}}
    for label, fg, bg in CVD_CARRIERS:
        for th in ("dark", "light"):
            f, b = hx(fg, th), hx(bg, th)
            r: dict[str, Any] = {"fg": f, "bg": b}
            for kind in CVD_KINDS:
                sf, sb = sim(f, kind), sim(b, kind)
                r[kind] = {"fg": sf, "ratio": fmt(ratio(sf, sb))}
            r["greyscale"] = {"fg": grey(f), "ratio": fmt(ratio(grey(f), grey(b)))}
            out["rows"][f"{label} ({th})"] = r
    return out


# ---------------------------------------------------------------- 7. keys ------------------------------------
def expand_chord(c: str) -> list[str]:
    r = re.fullmatch(r"(.*\+)(\d)\.\.(\d)", c)
    return [f"{r.group(1)}{k}" for k in range(int(r.group(2)), int(r.group(3)) + 1)] if r else [c]


KEYMAP_CONTEXTS = ("Global", "Workspace")  # the contexts SCR-022, CMP-217 and SCR-011 live in


def keymap_bindings() -> set[str]:
    """Every chord bound in a context these surfaces live in (``F2`` is ``rules.rename`` in Rules: not here)."""
    out: set[str] = set()
    try:
        data = json.loads(KEYMAP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    cmds = data.get("commands", data) if isinstance(data, dict) else data
    if isinstance(cmds, dict):
        cmds = list(cmds.values())
    for c in cmds if isinstance(cmds, list) else []:
        if not isinstance(c, dict) or c.get("context") not in KEYMAP_CONTEXTS:
            continue
        b = c.get("defaultBinding")
        for x in [b] if isinstance(b, str) else (b if isinstance(b, list) else []):
            if isinstance(x, str):
                out.add(x)
                out.update(expand_chord(x))
    return out


def keymap_rows() -> dict[str, Any]:
    want = {
        "workspace.preset": "Ctrl+1..9",
        "workspace.save": "Ctrl+S",
        "workspace.save_as": "Ctrl+Shift+S",
        "global.nav_rail": "Alt+1..9",
    }
    found: dict[str, Any] = {}
    try:
        cmds = json.loads(KEYMAP.read_text(encoding="utf-8")).get("commands", [])
    except (OSError, ValueError, AttributeError):
        cmds = []
    for c in cmds if isinstance(cmds, list) else []:
        if isinstance(c, dict) and c.get("id") in want:
            found[c["id"]] = {
                "label": c.get("label"),
                "binding": c.get("defaultBinding"),
                "reservedOverride": "reservedOverride" in c,
            }
    try:
        reserved = json.loads(RESERVED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reserved = {}
    return {
        "rows": found,
        "expected": want,
        "reserved_ctrl_1_9": reserved.get("Ctrl+1..9"),
        "reserved_ctrl_s": reserved.get("Ctrl+S"),
        "ctrl_shift_s_reserved": "Ctrl+Shift+S" in reserved,
        "reserved_count": len(reserved),
    }


# ---------------------------------------------------------------- 8. reasons and copy ------------------------
REASONS: dict[str, str] = {  # E15-D02 section 8.1 (:635-:677); E09-D09 section 3.1 / 3.2
    "rbac.view_as": "Read-only while viewing as {user}.",
    "rbac.permission": "Your role can't save workspaces.",
    "layout.limit.count": "This workspace has the most layouts it can hold.",
    "workspace.limit.count": "You have the most workspaces you can have.",
    "workspace.limit.last": "You need at least one workspace.",
}
REASON_MAX = 60
AVAILABILITY = (
    "This workspace isn't saved.",
    "This layout isn't saved yet.",
)  # E15-D02 :645: not T2


def reasons_report() -> dict[str, Any]:
    return {
        k: {"string": v, "chars": len(v), "ok": len(v) <= REASON_MAX} for k, v in REASONS.items()
    }


# ---------------------------------------------------------------- 9. string gates ----------------------------
FORBIDDEN = (  # generic patterns, never the words themselves (public repo)
    re.compile(r"/(?:home|Users)/[^/\s]+/"),
    re.compile(r"penpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE),
    re.compile(r"\bwt-note" + r"s\b"),
    re.compile(r"\b[a-z]{2,4}-worker-\d\b"),
    re.compile(r"\[[A-Z]{2,}[0-9]*-[A-Z0-9]{2,}\]"),  # a lane tag in square brackets
    re.compile(r"\b(?:issuecomment-|record )\d{8,}\b"),
)
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*#\d+", re.IGNORECASE)
PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|FIXME|lorem|XXX)\b")
NEVER_ON_T2 = ("color.text.disabled", "opacity.disabled", "the `disabled` attribute")
REFUSED_PATHS = (
    "docs/plan/15-component-catalogue.md",
    "docs/plan/22-api-openapi.yaml",
    "docs/plan/23-ws-protocol.md",
    "docs/plan/24-internal-schemas.md",
)
EVENTS = (
    "layout.preset_previewed",
    "layout.preset_applied",
    "layout.preset_saved_as",
    "layout.preset_deleted",
    "workspace.switched",
)
FRAME_PREFIXES = ("SCR-022", "CMP-217", "SCR-011")
SPINE_WORD = {"SCR-022": "arrangement", "CMP-217": "saved layout", "SCR-011": "saved workspace"}
# `14` write-back: the lines this PR adds (content only) and the lines that must stay
CAT_TYPE_LINE = (
    "- **Type:** Modal. Presets: Scalping, Order-flow, Swing, 2×2, 1+3, Fan-out review, Analyst, 2×1, 1×2, 3×3, 1×1 "
    "(E15-D05 §6; E15-D01 §2.2 order; 3+1 cut, AM-2)."
)
CAT_CHECKLIST_LINE = (
    "- **Design sign-off acceptance checklist:** [ ] built-in presets drawn (the eleven built-in presets of E15-D05 §6; "
    "the legacy checklist names map there) [ ] user presets with rename/delete [ ] 'applying replaces your current layout' "
    "confirmation [ ] empty user-preset state"
)
CAT_POINTER_022 = "- **Design (wireframe → hi-fi):** [E15-D05.md](../design/E15/E15-D05.md) §5–§9 (E15-D05; PROPOSED, owner approval pending:"
CAT_POINTER_011 = "- **Design (wireframe → hi-fi):** [E15-D05.md](../design/E15/E15-D05.md) §10 (E15-D05; PROPOSED, owner approval pending:"
CAT_KEEP = (
    "- **Data:** `GET /api/v1/layout-presets`, `POST /api/v1/workspaces/{workspaceId}/layouts`.",
    "| [1x1] [2x1] [2x2] [1+3] [3+1]               |",
    '- **Warning state:** "Applying a preset replaces the current layout. Settings of surviving panels are kept."',
)


def frame_names(text: str) -> set[str]:
    return set(re.findall(r"`((?:SCR-022|CMP-217|SCR-011)/[a-z0-9-]+)`", text))


def inventory_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(section(spec, "### 3.2 ", "## 4. ")) if r and r[0].startswith("`")]


NEGATED = re.compile(r"(?:\bno|\bnot|\bwithout|\bnever|\bnor)\W+(?:\w+\W+){0,2}$", re.IGNORECASE)


def present(text: str, needle: str) -> str:
    """'yes' if the needle occurs un-negated, 'negated' if only negated, 'no' if absent."""
    hits = [m.start() for m in re.finditer(re.escape(needle), text)]
    if not hits:
        return "no"
    if any(not NEGATED.search(text[max(0, i - 24) : i]) for i in hits):
        return "yes"
    return "negated"


def clause_at(text: str, i: int) -> str:
    a = max(text.rfind(c, 0, i) for c in ";|—") + 1
    ends = [j for j in (text.find(c, i) for c in ";|—") if j >= 0]
    return text[a : min(ends) if ends else len(text)].strip()


def string_gates(
    spec: str, handoff: str, tool: str, pr_body: str, files: list[str], catalogue: str
) -> list[str]:
    fails: list[str] = []
    for name, text in (("spec", spec), ("handoff", handoff), ("tool", tool), ("pr-body", pr_body)):
        if not text:
            continue
        if any(p.search(text) for p in FORBIDDEN):
            fails.append(f"hygiene: {name} matches a forbidden pattern")
        if name != "tool" and CLOSING.search(text):
            fails.append(f"closing: {name} carries a closing keyword")
        if name != "tool" and PLACEHOLDER.search(text):
            fails.append(f"placeholder: {name} carries a placeholder word")
    for f in files:
        if any(f.replace("\\", "/").endswith(p) for p in REFUSED_PATHS):
            fails.append(f"files: {f} is a path this design PR never edits")
    if not spec:
        return fails + ["spec missing"]
    # the one T2 rule: stated once in section 12 and cited from every section with a gated control
    if spec.count("The rule, once.") != 1:
        fails.append("t2: the one T2 rule is not stated exactly once")
    for sec, nxt, label in (
        ("## 7. ", "## 8. ", "the layout menu"),
        ("## 8. ", "## 9. ", "Your layouts"),
        ("## 9. ", "## 10. ", "the SCR-029 route"),
        ("## 10. ", "## 11. ", "the rail"),
        ("## 14. ", "## 15. ", "the copy deck"),
    ):
        if "§12" not in section(spec, sec, nxt):
            fails.append(f"t2: {label} does not cite the T2 rule (§12)")
    t2 = section(spec, "## 12. ", "## 13. ")
    for w in (
        "aria-disabled",
        "CMP-079",
        "CMP-019",
        "E09-D09",
        "color.text.tertiary",
        "color.text.secondary",
        "color.surface.raised",
        "color.border.default",
        "E30-D02 D3",
        "§0.5 rule 5",
    ):
        if w not in t2:
            fails.append(f"t2: the T2 statement lacks {w}")
    for w in NEVER_ON_T2:
        rule = next((para for para in t2.split("\n\n") if "The rule, once." in para), t2)
        if re.search(r"(?<!never )(?<!never `)(?<!not )" + re.escape(w), rule):
            fails.append(f"t2: the T2 statement binds {w}")
    iv, ip = t2.find("rbac.view_as"), t2.find("workspaces:write")
    if iv < 0 or ip < 0 or iv > ip:
        fails.append("view-as: the T2 statement does not put rbac.view_as before workspaces:write")
    if not re.search(r"Esc[^.|]*never (?:gated|locked)", spec):
        fails.append("exits: the spec does not state that Esc is never gated")
    # section 0: every board row PENDING; the frames named there = the state inventory = the hand-off's count
    boards = section(spec, "## 0. ", "## 1. ")
    board_rows = [r for r in rows_of(boards) if r and re.fullmatch(r"\d\d", r[0])]
    if not board_rows:
        fails.append("boards: no board rows in section 0")
    for r in board_rows:
        if "PENDING" not in r[-1]:
            fails.append("boards: a section-0 board row is not PENDING")
            break
    f0, finv = frame_names(boards), {r[0].strip("`") for r in inventory_rows(spec)}
    listed = [r[0].strip("`") for r in inventory_rows(spec)]
    twice = sorted({n for n in listed if listed.count(n) > 1})
    if twice:
        fails.append(f"frames: the state inventory lists {twice[0]} twice")
    if f0 != finv:
        fails.append(
            f"frames: section 0 names {len(f0)} frames, the state inventory {len(finv)}; they differ"
        )
    m = re.search(r"(\d+) named frames", handoff)
    if not m or int(m.group(1)) != len(finv):
        fails.append("frames: the hand-off's named-frame count differs from the state inventory")
    # every inventory frame is named in a section 5–10 body (not only in the tables)
    body = section(spec, "## 4. ", "## 11. ")
    for name in sorted(finv):
        if f"`{name}`" not in body and "light-" not in name and "thumbnails" not in name:
            fails.append(f"frames: {name} is not named in sections 4–10")
    # events: the observability table names the five events once each
    obs = section(spec, "## 16. ", "## 17. ")
    for e in EVENTS:
        if f"`{e}" not in obs:
            fails.append(f"events: {e} is missing from the observability table")
    if re.search(r"workspace\.switched[^|]*\{[^}]*\bname\b", obs):
        fails.append("events: workspace.switched carries a name")
    # unmerged siblings are named PENDING only: never pinned by a sha or a line, never quoted
    for name, text in (("spec", spec), ("handoff", handoff)):
        for m in SIBLING_PIN.finditer(text):
            fails.append(f"siblings: the {name} pins or quotes {m.group(1)} ('{m.group(0)[:48]}')")
    # merged E15-D08: the Key paragraph and section 1.1 cite it at its merge sha; nothing calls it PENDING
    key_par = spec.split("\n## 0. ")[0]
    if D08_SHA not in key_par or D08_SHA not in section(spec, "### 1.1 ", "### 1.2 "):
        fails.append("siblings: the spec does not cite merged E15-D08 at its merge sha")
    for name, text in (("spec", spec), ("handoff", handoff)):
        m = D08_PENDING.search(text)
        if m:
            fails.append(f"siblings: the {name} calls merged E15-D08 PENDING ('{m.group(0)[:48]}')")
    # C-16 (RULED, comment 6396465673) names exactly the four frames that gate the non-save writes
    c16 = next((ln for ln in spec.split("\n") if ln.startswith("| C-16 ")), "")
    if set(re.findall(r"`((?:SCR-022|CMP-217|SCR-011)/[a-z0-9-]+)`", c16)) != set(C16_FRAMES):
        fails.append("t2: C-16 does not name its four frames")
    cw = re.search(r"\b(\w+) frames gate those writes", c16)
    if not cw or cw.group(1).lower() != NUM_WORD[len(C16_FRAMES)]:
        fails.append(
            f"t2: C-16 counts its frames as '{cw.group(1) if cw else ''}', "
            f"the tool {NUM_WORD[len(C16_FRAMES)]}"
        )
    if not re.search(r"\bOQ-6 is closed\b", c16):
        fails.append("t2: C-16 does not close OQ-6")
    oq6 = next((r for r in rows_of(section(spec, "## 19. ", "## 20. ")) if r[:1] == ["OQ-6"]), [])
    if len(oq6) < 4 or not oq6[1].startswith("Closed (RULED") or oq6[3] != "closed (orchestrator)":
        fails.append("t2: OQ-6's row is not closed")
    # merged E15-D08 §6 :564 binds the SCR-029 route's Tab order and focus return in section 11.2
    r029 = next(
        (r for r in rows_of(section(spec, "### 11.2 ", "### 11.3 ")) if r[0].startswith("SCR-029")),
        [],
    )
    if len(r029) < 5 or D08_TAB_ORDER not in r029[2]:
        fails.append("focus: §11.2's SCR-029 Tab order is not merged E15-D08 §6's")
    elif not all(w in r029[4] for w in D08_FOCUS_AFTER):
        fails.append("focus: §11.2's SCR-029 focus return is not merged E15-D08 §6's")
    # merged E15-D08 D08-A22: the dirty layout's Delete layout confirm names the loss (section 8, the copy deck)
    deck = next(
        (
            r
            for r in rows_of(section(spec, "## 14. ", "## 15. "))
            if r[:1] == ["`layout.delete.confirm`"]
        ),
        [],
    )
    for where, text in (
        ("§8", section(spec, "## 8. ", "## 9. ")),
        ("the copy deck's `layout.delete.confirm`", " | ".join(deck)),
    ):
        if D08_A22 not in text:
            fails.append(f"copy: {where} lacks merged E15-D08 D08-A22's sentence")
    # `22`'s static-asset sentence sits at :12644–:12645 at the base (:12643 is the Keep-current-symbols line)
    if spec.count(":12644–:12645") != 3 or ":12643" in spec:
        fails.append("cites: `22`'s static-asset sentence is not cited at :12644–:12645")
    # D-9 in prose: the dirty switch section never prompts, in any wording
    word = first_prompt(section(spec, "### 10.3 ", "## 11. "), SWITCH_PROSE_WORD)
    if word:
        fails.append(f"switch: §10.3 prompts on a switch ('{word}')")
    # no key on a preset card in the gallery's prose either
    for start, end, label in (("### 5.2 ", "### 5.3 ", "§5.2"), ("### 6.2 ", "## 7. ", "§6.2")):
        prose_ = " ".join(
            ln for ln in section(spec, start, end).split("\n") if not ln.startswith("|")
        )
        cl = key_on_card(re.sub(r"\.\s", ";", prose_))
        if cl:
            fails.append(f"spine: {label} puts a hotkey on a preset card ('{cl[:60]}')")
    # the `14` write-back: the added lines present, the kept lines unchanged
    if catalogue:
        for label, line in (
            ("the SCR-022 Type line", CAT_TYPE_LINE),
            ("the SCR-022 checklist pointer", CAT_CHECKLIST_LINE),
            ("the SCR-022 hi-fi pointer", CAT_POINTER_022),
            ("the SCR-011 hi-fi pointer", CAT_POINTER_011),
        ):
            n_line = catalogue.count(line)
            if n_line == 0:
                fails.append(f"catalogue: {label} is not in `14`")
            elif n_line > 1:
                fails.append(f"catalogue: {label} appears {n_line} times in `14`")
        for line in CAT_KEEP:
            if line not in catalogue:
                fails.append("catalogue: a kept SCR-022 line changed")
    return fails


# ---------------------------------------------------------------- 10. frame-keyed gates (A1–A3) ---------------
T2_FORM = re.compile(
    r"lock glyph|`lock`|\bpadlock\b|CMP-079|disabledReason|rbac\.[a-z_]+|\bT2\b|aria-disabled|limit\.(?:count|last)"
)
T2_FORM_ALLOWED = (
    "not T2",
    "never T2",
    "no lock",
    "never a lock",
    "no CMP-079",
    "no `lock`",
    "no `disabledReason`",
    "no key",
    "never `aria-disabled`",
    "not `aria-disabled`",
    "no `aria-disabled`",
)
EXIT_GATED = re.compile(
    r"lock|aria-disabled|\bT2\b|CMP-079|rbac\.|disabledReason|\bblocked\b|\bdisabled\b|(?<!never )\bgated\b"
    r"|\binert\b|can(?:'|’|no)t be (?:pressed|used|clicked|chosen|activated)|\bunavailable\b|\bgr[ae]yed\b"
    r"|\b(?:not|no longer) available\b",
    re.IGNORECASE,
)
# the lock tokens an availability clause or a sentence-form row must not carry un-negated (per clause, any wording)
LOCK_TOKEN = re.compile(
    r"lock glyph|`lock`|\block\b|\bpadlock\b|CMP-079|disabledReason|rbac\.[a-z_]+|\bT2\b"
)
CTA_TOKEN = re.compile(r"\[(?:Save as new layout…|Save)[^\]]*\]|\bbutton\b|\bCTA\b")
ONE_CLICK = re.compile(
    r"one-click|deletes? (?:at once|immediately|straight away)|without (?:a |the )?(?:typed )?confirm|no confirm"
)
UNIT_NUM = re.compile(
    r"(?<![\d.×+:–\-])(\d+(?:,\d{3})?) (px|rows?|columns|workspaces|layouts|cards|lines|at comfortable)\b"
    r"|\bthe (\d+) (that fit)\b"
)
# every number a frame row draws, bound to the --json names it may equal (M-3: no "any printed integer")
FRAME_NUMS: dict[str, tuple[str, ...]] = {
    "SCR-022/presets-listbox": ("card_w_1920",),
    "SCR-022/gallery-1280": ("card_w_1280",),
    "SCR-022/gallery-zoom200": ("zoom200_card_h", "zoom200_scroll"),
    "SCR-022/gallery-text-125": ("text125_card_h", "text125_listbox_visible", "text125_yl_rows"),
    "SCR-022/thumbnails-smallest": ("glyph_px",),
    "SCR-022/your-layouts-twelve": ("yl_rows_1920_compact", "yl_rows_1280_compact"),
    "SCR-022/save-as-limit": ("layout_cap",),
    "CMP-217/menu-default": ("menu_w",),
    "CMP-217/menu-twelve": (
        "menu_h_compact_12",
        "menu_first_scroll_1280_compact",
        "menu_first_scroll_1280_comfortable",
    ),
    "CMP-217/menu-limit": ("layout_cap",),
    "SCR-011/expanded": ("rail_expanded",),
    "SCR-011/collapsed": ("rail_collapsed",),
    "SCR-011/search": (
        "search_fixture",
        "search_threshold",
        "menu_row_compact",
        "rail_fit_1280_compact_search",
    ),
    "SCR-011/limit": ("workspace_cap",),
}
STROKE_PX = ("1", "2", "3")  # hairline, ring and bar strokes: token widths, not layout numbers
SAVED_LAYOUT_FRAMES = (  # gallery frames that act on a saved layout, not on an arrangement (lens round 1 F-10)
    "SCR-022/your-layouts-empty",
    "SCR-022/your-layouts-twelve",
    "SCR-022/your-layouts-viewer",
    "SCR-022/your-layouts-view-as",
    "SCR-022/key-picker",
    "SCR-022/rename-clash",
    "SCR-022/delete-layout-confirm",
    "SCR-022/save-as-dialog",
    "SCR-022/save-as-invalid",
    "SCR-022/save-as-limit",
)
CHORD = re.compile(
    r"(?:Ctrl|Alt|Shift|Meta|Cmd)\+[A-Za-z0-9←→↑↓\\]+(?:\+[A-Za-z0-9←→↑↓\\]+)*(?:\.\.\d)?",
    re.IGNORECASE,
)
COMPONENT_KEYS = {"Shift+Tab"}  # a widget's own key, never a keymap row
VIEW_AS_FRAMES = ("SCR-022/your-layouts-view-as", "CMP-217/menu-view-as", "SCR-011/menu-view-as")
LIMIT_FRAMES = {
    "SCR-022/save-as-limit": "layout.limit.count",
    "CMP-217/menu-limit": "layout.limit.count",
    "SCR-011/limit": "workspace.limit.count",
    "SCR-011/last-workspace": "workspace.limit.last",
}
PERMISSION_FRAMES = (
    "SCR-022/apply-dirty-viewer",
    "CMP-217/menu-saves-t2",
    "CMP-217/menu-viewer",
    "CMP-217/light-menu-t2",
    "SCR-011/menu-viewer",
)
SENTENCE_FRAMES = ("SCR-022/your-layouts-viewer",)
T2_FRAMES = tuple(VIEW_AS_FRAMES) + tuple(LIMIT_FRAMES) + PERMISSION_FRAMES + SENTENCE_FRAMES
GALLERY_FRAMES = (
    "SCR-022/gallery-1920",
    "SCR-022/gallery-1280",
    "SCR-022/gallery-loading",
    "SCR-022/gallery-error",
    "SCR-022/gallery-zoom200",
    "SCR-022/gallery-text-125",
    "SCR-022/light-gallery",
)
DIRTY_NEEDLE = "\\* + unsaved changes"  # a sentinel: both, in the State-drawn cell
DIRTY_FRAMES = (
    "SCR-011/dirty",
    "SCR-011/switch-dirty",
    "SCR-011/light-rail",
    "CMP-217/trigger",
    "SCR-011/expanded",
)
VALIDITY_FRAMES = ("SCR-022/save-as-invalid", "SCR-011/new-workspace", "SCR-011/rename-inplace")
DIALOG_EXIT = ("`Esc`", "Cancel")
MENU_EXIT = ("`Esc`",)
EXIT_KIND: dict[str, tuple[str, ...]] = {}
for _n in (
    "gallery-1920",
    "gallery-1280",
    "gallery-loading",
    "gallery-error",
    "gallery-zoom200",
    "gallery-text-125",
    "presets-listbox",
    "thumbnails",
    "thumbnails-smallest",
    "your-layouts-empty",
    "your-layouts-twelve",
    "your-layouts-viewer",
    "your-layouts-view-as",
    "key-picker",
    "rename-clash",
    "delete-layout-confirm",
    "save-as-dialog",
    "save-as-invalid",
    "save-as-limit",
    "apply-clean",
    "apply-dirty",
    "apply-dirty-viewer",
    "light-gallery",
):
    EXIT_KIND[f"SCR-022/{_n}"] = DIALOG_EXIT
for _n in (
    "trigger",
    "menu-default",
    "menu-twelve",
    "menu-saves-t2",
    "menu-viewer",
    "menu-view-as",
    "menu-limit",
    "light-menu-t2",
):
    EXIT_KIND[f"CMP-217/{_n}"] = MENU_EXIT
for _n in (
    "expanded",
    "collapsed",
    "search",
    "context-menu",
    "rename-inplace",
    "rename-clash",
    "dirty",
    "empty",
    "loading",
    "error",
    "menu-viewer",
    "menu-view-as",
    "last-workspace",
    "limit",
    "switch-dirty",
    "light-rail",
):
    EXIT_KIND[f"SCR-011/{_n}"] = MENU_EXIT
EXIT_KIND["SCR-011/new-workspace"] = DIALOG_EXIT
EDITING_FRAMES = ("SCR-011/rename-inplace", "SCR-011/rename-clash", "SCR-022/rename-clash")
# Text round 1 (M-1): every ruled sentence is read clause by clause with a case-insensitive vocabulary, never
# by one keyword. A clause is a stretch between ";", "|" and "—"; a sub-clause also stops at "," and "(".
SPINE_CELL = {
    "SCR-022": "picks an arrangement",
    "CMP-217": "switches a saved layout",
    "SCR-011": "picks a saved workspace",
}
SAVED_LAYOUT_SPINE = "manages a saved layout"
SPINE_NOUNS = {
    "arrangement": re.compile(r"\barrangements?\b", re.IGNORECASE),
    "saved layout": re.compile(r"\bsaved layouts?\b", re.IGNORECASE),
    "saved workspace": re.compile(r"\bsaved workspaces?\b", re.IGNORECASE),
}
PRESET_ROWS = ("SCR-022/presets-listbox", "SCR-022/thumbnails", "SCR-022/thumbnails-smallest")
FIXTURE_WORKSPACES = ("Swing 4H", "Fanout review")  # Scalping shares the preset's name (lens nit)
KEY_WORD = re.compile(
    r"ctrl\s*\+|\bhot\s*-?keys?\b|\bkey\s*chips?\b|\bchips?\b|\bkbd\b|CMP-022|\bshortcuts?\b"
    r"|(?<![+\w])F\d{1,2}\b|\bkey\s+\d",
    re.IGNORECASE,
)
CARD_WORD = re.compile(r"\bcards?\b|\bpresets?\b|\bthumbnails?\b|\boptions?\b", re.IGNORECASE)
NEG_WORD = re.compile(r"\b(?:no|not|never|without|nor|none)\b", re.IGNORECASE)
_PRESET_NAMES = "|".join(
    re.escape(n).replace("×", "[×x]")
    for n in sorted(
        {x for p in INVENTORY for x in (p["label"], p["l1"]) if x}, key=len, reverse=True
    )
)
# a named preset card: a preset name from the inventory next to "card" / "thumbnail", or the word "preset"
NAMED_CARD = re.compile(
    rf"(?<![.\w`-])(?:(?:{_PRESET_NAMES})\s+(?:preset\s+)?(?:cards?|thumbnails?)\b"
    rf"|(?:cards?|thumbnails?)\s+(?:for|of)\s+(?:the\s+)?(?:{_PRESET_NAMES})(?![\w+×-])"
    r"|presets?\b)",
    re.IGNORECASE,
)
DIRTY_DENY = re.compile(
    r"\b(?:not|never|no longer|without)\b[^;|,]{0,30}?\b(?:row(?:'s)? name|accessible name|the name)\b"
    r"|\b(?:tab strip|tab|toolbar|status ?bar|tooltip)\s+only\b"
    r"|\bonly\s+(?:on|in)\s+the\s+(?:tab|toolbar|tooltip|status)",
    re.IGNORECASE,
)
PROMPT_WORD = re.compile(
    r"\bprompt(?:s|ed|ing)?\b|\bdialogs?\b|\btoasts?\b|\bconfirm(?:s|ation)?\b|\bmodal\b|alertdialog"
    r"|SCR-029|\bsave first\b|\basks?\b|\bsheets?\b|\bpopovers?\b|\btitled\b|\bwaits?\b",
    re.IGNORECASE,
)
PROMPT_OK = (
    "SCR-025's typed confirm",
)  # the workspace delete's own confirm, never a switch prompt
DIRECT_NEG = re.compile(r"\b(?:no|never|without|not)\s+(?:a\s+)?$", re.IGNORECASE)
SWITCH_PROSE_WORD = re.compile(
    r"\bprompt(?:s|ed|ing)?\b|\bdialogs?\b|\btoasts?\b|\bconfirm(?:s|ation)?\b|\bmodal\b|\bsave first\b",
    re.IGNORECASE,
)
LOCK_WORD = re.compile(
    r"\block(?:ed|s)?\b|\bpadlock\b|\binert\b|can(?:'|’|no)t be (?:pressed|used|clicked|chosen|activated)"
    r"|\bdisabled\b|\bgr[ae]yed(?: out)?\b|\bunavailable\b|\bblocked\b|\bgated\b|aria-disabled|\bT2\b"
    r"|CMP-079|disabledReason|rbac\.[a-z_]+|\b(?:not|no longer) available\b",
    re.IGNORECASE,
)
LOCK_SKIP = ("`opacity.disabled`", "`color.text.disabled`")  # token names, not states
T1_SUBJECT = re.compile(
    r"\bApply\b|Browse presets…|\bRename\b…?|Discard changes|\bswitch(?:es|ing)?\b|\bOpen\b|\bCancel\b"
    r"|\bClose\b|`Esc`|Back to gallery|Keep current symbols|the search field|\bUndo\b",
    re.IGNORECASE,
)
# C-16 (RULED, #321 comment 6396465673): the writes to a saved layout or workspace stay T2 under view-as and
# for a viewer; besides the save frames, these four frames gate them, and each names its gated writes
C16_WRITES: dict[str, tuple[str, ...]] = {
    "SCR-022/your-layouts-view-as": ("Rename", "key picker", "Delete…"),
    "SCR-022/your-layouts-viewer": (),
    "SCR-011/menu-viewer": (
        "Rename…",
        "Duplicate",
        "Set as default",
        "Move up",
        "Move down",
        "Delete…",
        "New workspace",
    ),
    "SCR-011/menu-view-as": (
        "Rename…",
        "Duplicate",
        "Set as default",
        "Move up",
        "Move down",
        "Delete…",
    ),
}
C16_FRAMES = tuple(C16_WRITES)
SCOPE_WORD = re.compile(
    r"\bsub-?accounts?\b|\baccounts?\b|\benvironments?\b|\benv\b|\bDEMO\b|\btestnet\b|\blive\b|\bUID\b",
    re.IGNORECASE,
)
FKEY = re.compile(r"(?<![+\w])`?(F\d{1,2})\b", re.IGNORECASE)
SIBLING_PIN = re.compile(
    r"(E15-D07)\b[^.;|\n]{0,40}?(?:\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b|\s:\d{2,}\b|\"[^\"]{4,}\")"
)


# E15-D08 merged after the base (delta fold): cited at its merge sha, never PENDING again
D08_SHA = "fb1b48041ae0a12638beacae6a61854833c5cc4d"
D08_PENDING = re.compile(
    r"E15-D08\b[^.;\n]{0,80}?\bPENDING\b|\bPENDING\b[^.;|\n]{0,40}?\bE15-D08\b"
)
NUM_WORD = {3: "three", 4: "four", 5: "five", 6: "six"}
D08_TAB_ORDER = "Cancel → Discard changes → Save layout"
D08_FOCUS_AFTER = (
    "after Cancel the gallery's Apply",
    "after Save layout or Discard changes `[Layout ▾]`",
)
D08_A22 = '"Delete layout {name}? It has unsaved changes, and it can\'t be restored."'


D08_E3 = "merged E15-D08 draws the row in its entry-point matrix (§3.2 E3 :419 at `" + D08_SHA + "`"
D08_HANDED = re.compile(r"hand(?:ed|s)? to E15-D08's entry-point matrix|entry-point matrix \(§19\)")


def d08_switch_row_gates(spec: str) -> list[str]:
    """Re-check carry: merged E15-D08 §3.2 E3 draws the rail switch row; §19 no longer hands it over."""
    i = spec.find("### 10.3 ")
    sec = spec[i : spec.find("## 11. ", i)] if i >= 0 else ""
    fails = []
    if D08_E3 not in sec:
        fails.append("siblings: §10.3 does not cite merged E15-D08 §3.2 E3 :419 for the switch row")
    if D08_HANDED.search(spec):
        fails.append("siblings: the spec still hands the switch row to E15-D08 (§19)")
    return fails


def strip_quotes(text: str) -> str:
    """Blank every double-quoted string (copy, not drawn state), keeping the offsets."""
    return re.sub(r'"[^"\n]*"', lambda m: " " * len(m.group(0)), text)


def clauses_of(text: str) -> list[str]:
    return [c for c in re.split(r"[;|—]", text) if c.strip()]


def sub_negated(clause: str, i: int) -> bool:
    """Whether the sub-clause (from the last ',' or '(' before i) negates what stands at i."""
    a = max(clause.rfind(",", 0, i), clause.rfind("(", 0, i)) + 1
    return bool(NEG_WORD.search(clause[a:i]))


def key_on_card(text: str) -> str:
    """The first clause that puts a key on a preset card un-negated, else ''."""
    for clause in clauses_of(strip_quotes(text)):
        if not CARD_WORD.search(clause):
            continue
        for m in KEY_WORD.finditer(clause):
            if not sub_negated(clause, m.start()):
                return clause.strip()
    return ""


def first_prompt(text: str, words: re.Pattern[str] = PROMPT_WORD) -> str:
    """The first prompt / dialog / toast / confirm word not directly negated, else ''."""
    for ok in PROMPT_OK:
        text = text.replace(ok, " " * len(ok))
    for m in words.finditer(text):
        if not DIRECT_NEG.search(text[max(0, m.start() - 12) : m.start()]):
            return m.group(0)
    return ""


def locked_t1(text: str, gated: tuple[str, ...]) -> tuple[str, str]:
    """(subject, lock word) for the first clause that locks a T1 control un-negated, else ('', '')."""
    for ok in LOCK_SKIP:
        text = text.replace(ok, " " * len(ok))
    for clause in clauses_of(text):
        subs = [
            m
            for m in T1_SUBJECT.finditer(clause)
            if not any(m.group(0).lower().startswith(g.lower()) for g in gated)
        ]
        if not subs:
            continue
        for m in LOCK_WORD.finditer(clause):
            if NEGATED.search(clause[max(0, m.start() - 24) : m.start()]):
                continue
            # the subject the lock word speaks of: the nearest one before it (within 40), else after it
            before = [s for s in subs if s.end() <= m.start() and m.start() - s.end() <= 40]
            after = [s for s in subs if s.start() >= m.end()]
            subj = before[-1] if before else (after[0] if after else subs[0])
            return subj.group(0), m.group(0)
    return "", ""


def first_scope(text: str) -> str:
    text = strip_quotes(text)
    for m in SCOPE_WORD.finditer(text):
        if not NEGATED.search(text[max(0, m.start() - 24) : m.start()]):
            return m.group(0)
    return ""


def bare_fkeys(text: str, bindings: set[str]) -> list[str]:
    """Bare function keys drawn un-negated and not bound in a context these surfaces live in (RULED Q-22)."""
    low = {b.lower() for b in bindings}
    out = []
    for m in FKEY.finditer(text):
        if m.group(1).lower() in low:
            continue
        if re.search(r"\bno\s+`?$", text[max(0, m.start() - 8) : m.start()], re.IGNORECASE):
            continue
        out.append(m.group(1))
    return out


def frame_needs(nums: dict[str, Any]) -> dict[str, tuple[tuple[str, str], ...]]:
    """Per frame id, the (label, needle) carriers its row must draw; numbers come from the tool."""
    keyed, nokey = nums["twelve_keyed"], nums["twelve_nokey"]
    needs: dict[str, tuple[tuple[str, str], ...]] = {}
    for f in GALLERY_FRAMES:
        needs[f] = (
            ("the keep-symbols carrier with its default", "Keep current symbols (on)"),
            ("the warning line", FOOTER_WARNING),
            ("the arrangement-only sentence", FOOTER_SENTENCE),
        )
    for f in ("SCR-022/gallery-1920", "SCR-022/gallery-1280", "SCR-022/gallery-zoom200"):
        needs[f] += (("the initial-focus statement", "initial focus"),)
    needs["SCR-022/gallery-loading"] += (
        ("the skeleton count", f"{nums['inventory_count']} card skeletons"),
        ("`aria-busy`", "`aria-busy`"),
    )
    needs["SCR-022/gallery-error"] += (
        ("the load failure copy", "Presets didn't load."),
        ("[Retry]", "[Retry]"),
    )
    needs["SCR-022/gallery-zoom200"] += (
        ("the one sticky row", "one sticky row"),
        ("the disclosure", "disclosure"),
        ("the one scroll container", "one scroll container"),
        ("the row cards", "row card"),
    )
    needs["SCR-022/gallery-text-125"] += (("the text scale", "125 %"),)
    needs["SCR-022/light-gallery"] += (("semantic-light", "semantic-light"),)
    needs["SCR-022/presets-listbox"] = (
        ("the listbox role", "listbox"),
        ("one Tab stop", "one Tab stop"),
    )
    needs["SCR-022/thumbnails"] = (
        ("the accessible names", "accessible name"),
        ("the `alt` texts", "`alt`"),
    )
    needs["SCR-022/thumbnails-smallest"] = (
        ("the smallest size", f"{nums['thumb_w_1280']}×{nums['thumb_h_1280']}"),
        ("200 %", "200 %"),
    )
    needs["SCR-022/your-layouts-empty"] = (
        ("the create instruction", "Save the current arrangement as a new layout (Ctrl+Shift+S)"),
        ("the empty sentence", "Layout 1 is this workspace's only layout"),
    )
    needs["SCR-022/your-layouts-twelve"] = (
        (f"{keyed} keyed", f"{keyed} keyed"),
        (f'{nokey} "(no key)"', f'{nokey} "(no key)"'),
    )
    needs["SCR-022/your-layouts-viewer"] = (
        ("the sentence form", "sentence form"),
        ("the reason key", "`rbac.permission`"),
    )
    needs["SCR-022/your-layouts-view-as"] = (("the target's rows", "target's"),)
    needs["SCR-022/key-picker"] = (
        ("taken keys with their layout", "taken keys"),
        ("the 409 outcome", "`hotkey_slot_taken`"),
    )
    needs["SCR-022/rename-clash"] = (("the server's copy", "That name is already in use."),)
    needs["SCR-022/delete-layout-confirm"] = (
        ("the effect-naming label", "[Delete layout]"),
        ("the confirm copy", "It can't be restored."),
    )
    needs["SCR-022/save-as-dialog"] = (
        ("the slot select", "next free"),
        ("(no key) offered", "(no key)"),
        ("the Name field", "Name"),
    )
    needs["SCR-022/save-as-invalid"] = (
        ("the validity look", "validity look"),
        ("`opacity.disabled`", "`opacity.disabled`"),
    )
    needs["SCR-022/apply-clean"] = (
        ("the announcement", "Layout changed to Order-flow, 4 panels."),
        ("the Undo toast", "Undo"),
    )
    for f in ("SCR-022/apply-dirty", "SCR-022/apply-dirty-viewer"):
        needs[f] = (
            ("[Save layout]", "[Save layout]"),
            ("[Discard changes]", "[Discard changes]"),
            ("[Cancel]", "[Cancel]"),
            ("`alertdialog`", "`alertdialog`"),
            ("the unsaved title", "You have unsaved layout changes."),
        )
    needs["CMP-217/trigger"] = (
        ("the active layout's name", "Layout 1"),
        ("the no-inline-chip rule", "never a key chip inline (merged E15-D03 D-9)"),
    )
    needs["CMP-217/menu-default"] = (
        ("Browse presets… last", "Browse presets…"),
        ("the saved layouts first", "Layout 1"),
    )
    needs["CMP-217/menu-twelve"] = (
        (f"{keyed} keyed", f"{keyed} keyed"),
        ("the first scrolling count", "layouts at compact"),
    )
    needs["CMP-217/menu-viewer"] = (("the availability look on Revert", "availability"),)
    needs["CMP-217/light-menu-t2"] = (("semantic-light", "semantic-light"),)
    needs["SCR-011/expanded"] = (
        ('`aria-current="page"`', '`aria-current="page"`'),
        ("the 3 px bar", "3 px"),
        ("the current row's weight", "`font.weight.medium`"),
        ("the current row's fill", "`color.surface.selected`"),
        ('"default" as text', '"default" as text'),
    )
    needs["SCR-011/collapsed"] = (
        ("the tooltip on focus", "focus"),
        (f"{nums['rail_collapsed']} px", f"{nums['rail_collapsed']} px"),
    )
    needs["SCR-011/search"] = (
        (f"above {nums['search_threshold']}", f"above {nums['search_threshold']}"),
        ("the scroll region", "scroll region"),
        ("the combobox", "combobox"),
    )
    needs["SCR-011/context-menu"] = (
        ("Delete… with its ellipsis", "Delete…"),
        ("Move up / Move down", "Move up"),
        ("Rename…", "Rename…"),
    )
    needs["SCR-011/rename-inplace"] = (
        ("`Esc` reverts", "`Esc` reverts;"),
        ("`Enter` saves", "`Enter` saves"),
        ("the labelled input", "Workspace name"),
    )
    needs["SCR-011/rename-clash"] = (("the server's copy", "That name is already in use."),)
    for f in DIRTY_FRAMES:  # read on the State-drawn cell only, both together (delta M-1)
        needs[f] = needs.get(f, ()) + (("the dirty marker in the row name", DIRTY_NEEDLE),)
    needs["SCR-011/light-rail"] += (("semantic-light", "semantic-light"),)
    needs["SCR-011/empty"] = (
        ("the failed-create explanation", "failed"),
        ("[New workspace] T1", "[New workspace] T1"),
    )
    needs["SCR-011/loading"] = (("skeleton rows", "skeleton"), ("`aria-busy`", "`aria-busy`"))
    # SCR-011/error's copy and action are gated by load_error_gates (RULED M-2), cell by cell
    for f, writes in C16_WRITES.items():
        needs[f] = needs.get(f, ()) + tuple((f"the gated write {w}", w) for w in writes)
    needs["SCR-011/new-workspace"] = (
        ("Start from", "Start from"),
        ("Scalping preselected", "Scalping preselected"),
        ("the validity look", "validity look"),
        ("Layout 1 on the first slot", "Layout 1"),
    )
    return needs


def t2_anatomy(name: str) -> tuple[tuple[str, str], ...]:
    if name in SENTENCE_FRAMES:
        return (
            ("the sentence form", "sentence form"),
            ("the reason key", "`rbac.permission`"),
            ("the reason string", REASONS["rbac.permission"]),
        )
    base: tuple[tuple[str, str], ...] = (
        ("the lock glyph", "`lock`"),
        ("the full label", "full label"),
        ("`aria-disabled`", "`aria-disabled`"),
    )
    if name in VIEW_AS_FRAMES:
        return base + (
            ("the view-as key", "`rbac.view_as`"),
            ("the banner node", "the banner's `rbac.view_as` node"),
            ("CMP-079", "CMP-079"),
        )
    if name in LIMIT_FRAMES:
        return base + (
            ("the limit key", f"`{LIMIT_FRAMES[name]}`"),
            ("`disabledReason`", "`disabledReason`"),
            ("the reason string", REASONS[LIMIT_FRAMES[name]]),
        )
    return base + (
        ("the permission key", "`rbac.permission`"),
        ("CMP-079", "CMP-079"),
        ("the reason string", REASONS["rbac.permission"]),
    )


def frame_gates(spec: str, bindings: set[str], nums: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    inv = inventory_rows(spec)
    by = {r[0].strip("`"): r for r in inv}
    needs = frame_needs(nums)
    labels = [p["label"] for p in INVENTORY]
    for name, r in by.items():
        text = " | ".join(r)
        prefix = name.split("/")[0]
        if len(r) < 7:
            fails.append(f"inventory: frame {name} has fewer than seven cells")
            continue
        # A2: the Spine cell is its surface's bare noun phrase; no other surface's noun in any other cell
        noun = "saved layout" if name in SAVED_LAYOUT_FRAMES else SPINE_WORD.get(prefix, "")
        want_cell = (
            SAVED_LAYOUT_SPINE if name in SAVED_LAYOUT_FRAMES else SPINE_CELL.get(prefix, "")
        )
        if noun not in r[4]:
            fails.append(f"spine: frame {name} does not name its noun ({noun})")
        elif r[4].strip() != want_cell:
            fails.append(
                f"spine: frame {name}'s Spine cell is not the bare '{want_cell}' ('{r[4].strip()}')"
            )
        rest = strip_quotes(" | ".join(c for i, c in enumerate(r) if i != 4))
        for other, pat in SPINE_NOUNS.items():
            if other == noun:
                continue
            hit = next(
                (
                    m
                    for m in pat.finditer(rest)
                    if not NEGATED.search(rest[max(0, m.start() - 24) : m.start()])
                ),
                None,
            )
            if hit:
                fails.append(
                    f"spine: frame {name} names a {other} outside its Spine cell "
                    f"('{clause_at(rest, hit.start())[:60]}')"
                )
                break
        if name in PRESET_ROWS:
            ws = next((w for w in FIXTURE_WORKSPACES if w in text), "")
            if ws:
                fails.append(f"spine: frame {name} names the workspace {ws} in the Presets listbox")
        if prefix == "SCR-022" and re.search(
            r"(?:Rename|Delete|Duplicate) workspace|Set as default|Move up", text, re.IGNORECASE
        ):
            fails.append(f"spine: frame {name} offers a workspace action in the gallery")
        switcher_keys = prefix == "SCR-011" and re.search(r"ctrl\s*\+\s*[1-9]", text, re.IGNORECASE)
        if switcher_keys:
            fails.append(f"spine: frame {name} shows layout keys in the switcher")
        # a key on a named preset card in any frame (SCR-022's own vocabulary is wider)
        cl = key_on_card(" | ".join(r[2:])) if prefix == "SCR-022" else named_card_key(text)
        if cl and not switcher_keys:
            fails.append(f"spine: frame {name} puts a hotkey on a preset card ('{cl[:60]}')")
        # merged E15-D03 D-9: the trigger never carries a key chip inline
        if name == "CMP-217/trigger":
            for clause in clauses_of(strip_quotes(r[2])):
                hit = next(
                    (m for m in KEY_WORD.finditer(clause) if not sub_negated(clause, m.start())),
                    None,
                )
                if hit:
                    fails.append(
                        f"trigger: frame {name} draws a key chip inline ('{hit.group(0)}'; "
                        "merged E15-D03 D-9)"
                    )
                    break
        # C-2.11 made visible: no account or environment control on these surfaces
        scope = first_scope(" | ".join(r[2:]))
        if scope:
            fails.append(f"scope: frame {name} draws an account or environment control ('{scope}')")
        # A2: the per-frame carriers
        for label, needle in needs.get(name, ()):
            if needle == DIRTY_NEEDLE:  # the marker and its words in the row name, never a notice
                in_name = present(r[2], "unsaved changes") == "yes" and "\\*" in r[2]
                seen = "yes" if in_name else "no"
                if not in_name and present(text, "unsaved changes") == "yes" and "\\*" in text:
                    fails.append(
                        f"dirty: frame {name} draws the dirty marker outside its row name "
                        "(the State drawn cell)"
                    )
                    continue
            else:
                seen = present(text, needle)
            if seen == "no":
                fails.append(f"carrier: frame {name} lacks {label}")
            elif seen == "negated" and label not in ("no prompt",):
                fails.append(f"carrier: frame {name} negates {label}")
        # A2 / M-3: every "N px" / count in the drawn state equals one of the names the frame registers
        mine = {str(nums[k]) for k in FRAME_NUMS.get(name, ())}
        for m in UNIT_NUM.finditer(strip_quotes(r[2] + " | " + r[5])):
            n, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            n = n.replace(",", "")
            if n in mine or (unit == "px" and n in STROKE_PX):
                continue
            fails.append(
                f"number: frame {name} draws {n} {unit}, not a value the tool derives for it"
            )
            break
        if name in DIRTY_FRAMES:
            hit = DIRTY_DENY.search(r[2] + " | " + r[5])
            if hit:
                fails.append(
                    f"dirty: frame {name} moves the dirty marker out of the row name ('{hit.group(0)}')"
                )
        # the Presets listbox: inventory order, the cut preset
        if name == "SCR-022/presets-listbox":
            pos = [text.find(lb) for lb in labels]
            if any(p < 0 for p in pos) or pos != sorted(pos):
                fails.append(
                    "order: the listbox frame does not list the presets in the inventory's order"
                )
            if CUT_PRESET in text and present(text, CUT_PRESET) == "yes":
                fails.append("cut: the listbox frame draws the cut preset")
        if name == "CMP-217/menu-default":
            pa, pb, pc = (
                text.find("Layout 1"),
                text.find("Save layout"),
                text.find("Browse presets…"),
            )
            if not (0 <= pa < pb < pc):
                fails.append(
                    "order: the menu frame does not list saved layouts, then the saves, then Browse presets… (AD-2)"
                )
        if name == "SCR-011/context-menu":
            bare = re.search(r"\bDelete\b(?!…)(?! layout)", text)
            quick = ONE_CLICK.search(text)
            hit_tok = None
            if bare:
                hit_tok = bare.group(0)
            elif quick and not NEGATED.search(text[max(0, quick.start() - 24) : quick.start()]):
                hit_tok = quick.group(0)
            if hit_tok:
                fails.append(
                    f"delete: the context menu frame offers a one-click workspace delete ('{hit_tok}')"
                )
        if prefix in ("SCR-011", "CMP-217") and name != "SCR-011/new-workspace":
            word = first_prompt(r[2] + " | " + r[5])
            if word:
                fails.append(f"switch: frame {name} prompts on a switch ('{word}')")
            elif name == "SCR-011/switch-dirty" and present(text, "prompt") != "negated":
                fails.append("switch: the dirty switch frame omits the no-prompt rule (D-9)")
        if name == "SCR-022/delete-layout-confirm" and (
            "Cancel focused" not in text or "Delete layout focused" in text
        ):
            fails.append("confirm: the delete confirm frame does not focus Cancel")
        if name in ("SCR-022/apply-dirty", "SCR-022/apply-dirty-viewer") and (
            "Cancel focused" not in text
            or re.search(r"Discard changes focused|Save layout focused", text)
        ):
            fails.append(f"route: frame {name} does not focus Cancel")
        if "availability" in text:
            # every clause that names an availability state is read on its own, in any wording
            for clause in re.split(r"[;|]", text):
                if "availability" not in clause:
                    continue
                hit_tok = next(
                    (
                        m.group(0)
                        for m in LOCK_TOKEN.finditer(clause)
                        if not NEGATED.search(clause[max(0, m.start() - 24) : m.start()])
                    ),
                    None,
                )
                if hit_tok:
                    fails.append(
                        f"availability: frame {name} draws a lock on an availability state ('{hit_tok}')"
                    )
                    break
        # A1 / A3: no lock, inert or can't-be-pressed wording on a T1 control, in any case or form
        subj, lword = locked_t1(r[2] + " | " + r[5], ("Rename",) if name in C16_FRAMES else ())
        if subj:
            fails.append(f"lock: frame {name} locks {subj} ('{lword}')")
        # A1: the T2 anatomy on every T2 frame, the T2 form on no other frame
        if name in T2_FRAMES:
            if present(r[3], "T2") != "yes":
                fails.append(f"t2-frames: frame {name} is not classed T2")
            for label, needle in t2_anatomy(name):
                seen = present(text, needle)
                if (
                    seen == "no"
                    and needle == "`aria-disabled`"
                    and present(text, "`disabled` attribute") == "yes"
                ):
                    fails.append(f"t2-anatomy: frame {name} uses the `disabled` attribute")
                elif seen == "no":
                    fails.append(f"t2-anatomy: frame {name} lacks {label}")
                elif seen == "negated":
                    fails.append(f"t2-anatomy: frame {name} negates {label}")
            if name in VIEW_AS_FRAMES:
                iv, ip = text.find("rbac.view_as"), text.find("rbac.permission")
                if ip >= 0 and ip < iv:
                    fails.append(f"view-as: frame {name} does not put the view-as leg first")
            if name in SENTENCE_FRAMES:
                # any CTA, button or bracketed action, in any wording, breaks the sentence form
                hit_tok = next(
                    (
                        m.group(0)
                        for m in CTA_TOKEN.finditer(text)
                        if not NEGATED.search(text[max(0, m.start() - 24) : m.start()])
                    ),
                    None,
                )
                if hit_tok:
                    fails.append(
                        f"t2-anatomy: frame {name} draws a CTA in the sentence form ('{hit_tok}')"
                    )
        else:
            if present(r[3], "T2") == "yes":
                fails.append(f"t2-frames: frame {name} is classed T2 outside the T2 frames")
            body = " | ".join(re.sub(r"\bT2\b", "", c) if i == 3 else c for i, c in enumerate(r))
            for ok in T2_FORM_ALLOWED:
                body = body.replace(ok, "")
            for m in T2_FORM.finditer(body if not subj else ""):
                tok_ = m.group(0)
                if NEGATED.search(body[max(0, m.start() - 24) : m.start()]):
                    continue
                fails.append(f"t2-form: frame {name} draws '{tok_}' outside the T2 frames")
                break
        if name in VALIDITY_FRAMES and "validity" not in r[3]:
            fails.append(f"validity: frame {name} is not classed by its validity look")
        if (
            "clash" in name or "error" in name or name == "SCR-022/apply-clean"
        ) and "outcome" not in r[3]:
            fails.append(f"over-conversion: frame {name} is not classed as an outcome")
        if "loading" in name and "status" not in r[3]:
            fails.append(f"over-conversion: frame {name} is not classed as a status")
        # A3: exits named, all T1, never paired with a gate
        exits = r[6]
        kind = EXIT_KIND.get(name)
        if kind is None:
            fails.append(f"exits: frame {name} has no exit kind in the tool")
        else:
            for needle in kind:
                if needle not in exits:
                    fails.append(f"exits: frame {name} does not draw its exit {needle}")
        if name in EDITING_FRAMES and "reverts" not in exits:
            fails.append(f"exits: frame {name} does not say what `Esc` reverts")
        # one gate for the exit class: a gated exit, else a class other than T1 (lens round 1 F-5)
        gate_hit = EXIT_GATED.search(exits)
        if gate_hit:
            fails.append(
                f"exits: frame {name} gates an exit in its Exits cell ('{gate_hit.group(0)}')"
            )
        elif "T1" not in exits:
            fails.append(f"exits: frame {name} does not class its exits T1")
    for name in sorted(set(EXIT_KIND) - set(by)):
        fails.append(f"exits: the tool names frame {name}, the inventory does not")
    for name in sorted(set(by) - set(EXIT_KIND)):
        fails.append(f"exits: frame {name} is not a frame the tool keys")
    # the inventory table (section 6.1): order, panel counts, the cut preset, the notes, the forbidden words
    inv_rows = [
        r
        for r in rows_of(section(spec, "### 6.1 ", "### 6.2 "))
        if r and re.fullmatch(r"\d+", r[0])
    ]
    served = served_presets()
    if [r[2] for r in inv_rows] != labels:
        fails.append("inventory: the section 6.1 labels are not E15-D01 §2.2's order without 3+1")
    for r, p in zip(inv_rows, INVENTORY, strict=False):
        label = p["label"]
        want = served[p["served"]]["pane_count"] if p["served"] else p["panels"]
        if not re.match(rf"{want}\b", r[3]):
            fails.append(f"inventory: {label}'s panel count differs from the tool's ({want})")
        if p["note"] and p["note"].split(" (")[0] not in r[4]:
            fails.append(f"inventory: {label} does not say what opens instead (AD-3)")
        name_cell = r[6]
        bad = [w for w in FORBIDDEN_NAME_WORDS if re.search(rf"\b{w}\b", name_cell, re.IGNORECASE)]
        words = ARRANGEMENT_WORDS[p["sig"]]
        if bad:
            fails.append(f"inventory: {label}'s accessible name uses a forbidden word ({bad[0]})")
        elif not any(w in name_cell.lower() for w in words):
            fails.append(
                f"inventory: {label}'s accessible name lacks its arrangement words ({' / '.join(words)})"
            )
        elif p["name"] not in name_cell:
            fails.append(f"inventory: {label}'s accessible name differs from the tool's")
        want_id = served[p["served"]]["id"] if p["served"] else "PROPOSED"
        if want_id not in r[1]:
            fails.append(f"inventory: {label}'s id is not the served uuid or PROPOSED")
    if any(CUT_PRESET in r[2] for r in inv_rows):
        fails.append("inventory: the cut preset is drawn as a row")
    # A2-4: every drawn chord is in keymap.json, a component key, or marked PROPOSED after it
    surfaces: list[tuple[str, str]] = [(f"frame {n}", " | ".join(r)) for n, r in by.items()]
    surfaces += [
        (f"board {r[0]}", " | ".join(r))
        for r in rows_of(section(spec, "## 0. ", "## 1. "))
        if r and re.fullmatch(r"\d\d", r[0])
    ]
    surfaces += [
        (f"copy deck {r[0]}", r[1])
        for r in rows_of(section(spec, "## 14. ", "## 15. "))
        if len(r) > 1
    ]
    surfaces += [
        (f"key row {r[0]}", " | ".join(r))
        for r in rows_of(section(spec, "### 11.1 ", "### 11.2 "))
        if r
    ]
    # the prose of sections 4-12 is read too (a chord typed in a paragraph is drawn on a board)
    for sec in range(4, 13):
        body = section(spec, f"## {sec}. ", f"## {sec + 1}. ")
        surfaces += [
            (f"§{sec} prose", para)
            for para in body.split("\n")
            if para.strip() and not para.startswith(("|", "#", "<!--"))
        ]
    low = {b.lower() for b in bindings} | {k.lower() for k in COMPONENT_KEYS}
    for where, text in surfaces:
        fk = bare_fkeys(text, bindings)
        if fk:
            fails.append(
                f"keys: {where} draws {fk[0]}, a key with no row in this context (RULED Q-22)"
            )
        for cell in text.split("|"):
            for clause in cell.split(";"):
                for m in CHORD.finditer(clause):
                    c = m.group(0)
                    if all(e.lower() in low for e in expand_chord(c)):
                        continue
                    pm = re.search(r"proposed", clause[m.end() :], re.IGNORECASE)
                    gap = clause[m.end() : m.end() + pm.start()] if pm else ""
                    if not pm or re.search(r"\b(?:SCR|CMP)-\d|\bor\b", gap):
                        fails.append(f"keys: {where} draws {c} without PROPOSED after it")
    return fails


# ---------------------------------------------------------------- the switcher's load error (RULED M-2) ------
# The switcher's load error takes merged E15-D03 section 4.6's strings verbatim on every carrier; any other
# wording of it (failed / didn't / couldn't / can't load, load failed, error loading) or any other action word
# (Retry, Reload, another casing of Try again) fails. Read clause by clause, case-insensitively; a clause about
# presets only is the gallery's ("Presets didn't load." with [Retry], valid) and is skipped.
LOAD_ERROR = "Couldn't load workspaces."
LOAD_ACTION = "Try again"
_NOT = r"(?:n['\u2019]t|\s+not)"
LOAD_FAIL_WORD = re.compile(
    r"\bfail(?:ed|s|ing|ure)?\s+(?:to\s+)?load(?:ing)?\b"
    rf"|\b(?:did|does|do|could|can|ca|would|will|wo){_NOT}\s+(?:\w+\s+){{0,2}}?(?:be\s+)?load(?:ed)?\b"
    r"|\b(?:cannot|unable\s+to|not)\s+(?:be\s+)?load(?:ed)?\b"
    r"|\bload(?:ing)?\s+(?:failed|error|failure)\b|\berror\s+loading\b",
    re.IGNORECASE,
)
ACTION_WORD = re.compile(
    r"\bre-?(?:try|load)(?:ing)?\b|\btry\s+(?:it\s+|that\s+)?again\b|\btry\s+once\s+more\b",
    re.IGNORECASE,
)
PRESET_ONLY = re.compile(r"\bpresets?\b", re.IGNORECASE)
WORKSPACE_WORD = re.compile(r"\bworkspaces?\b", re.IGNORECASE)


def load_error_carriers(
    spec: str, handoff: str = ""
) -> list[tuple[str, str, tuple[tuple[str, str, str], ...]]]:
    """(where, scanned text, ((label, needle, cell), ...)) per carrier; a missing carrier has no text."""
    frame = next((r for r in inventory_rows(spec) if r[0].strip("`") == "SCR-011/error"), [])
    copy_ = next(
        (r for r in rows_of(section(spec, "## 14. ", "## 15. ")) if r and r[0] == "`rail.error`"),
        [],
    )
    an7 = next((r for r in rows_of(section(spec, "### 11.3 ", "## 12. ")) if r[:1] == ["AN-7"]), [])
    s102 = section(spec, "### 10.2 ", "### 10.3 ")
    i = s102.find("**Error** (`SCR-011/error`)")
    sentence = ""
    if i >= 0:  # from the bold lead-in to the next bold lead-in or the end of the paragraph
        rest = s102[i + len("**Error**") :]
        ends = [k for k in (rest.find("**"), rest.find("\n")) if k >= 0]
        sentence = rest[: min(ends)] if ends else rest
    err, act = f'"{LOAD_ERROR}"', f"[{LOAD_ACTION}]"
    out: list[tuple[str, str, tuple[tuple[str, str, str], ...]]] = []
    if len(frame) >= 7:
        out.append(
            (
                "frame SCR-011/error",
                " | ".join(frame),
                (
                    ("frame SCR-011/error", err, frame[2]),
                    ("frame SCR-011/error's announcement", err, frame[5]),
                    ("frame SCR-011/error", act, frame[2]),
                ),
            )
        )
    else:
        out.append(("frame SCR-011/error", "", ()))
    if len(copy_) > 1:
        out.append(
            (
                "copy deck `rail.error`",
                copy_[1],
                (
                    ("copy deck `rail.error`", err, copy_[1]),
                    ("copy deck `rail.error`", f'"{LOAD_ACTION}"', copy_[1]),
                ),
            )
        )
    else:
        out.append(("copy deck `rail.error`", "", ()))
    if len(an7) > 3:
        out.append(("AN-7's string", an7[3], (("AN-7's string", err, an7[3]),)))
    else:
        out.append(("AN-7's string", "", ()))
    out.append(
        (
            "§10.2's error sentence",
            sentence,
            (("§10.2's error sentence", err, sentence), ("§10.2's error sentence", act, sentence)),
        )
    )
    # delta carries: board 08's section-0 row, section 12's outcomes clause and the hand-off's section A line
    board = next((r for r in rows_of(section(spec, "## 0. ", "## 1. ")) if r and r[0] == "08"), [])
    s12 = next(
        (p for p in section(spec, "## 12. ", "## 13. ").split("\n") if "**outcomes**" in p), ""
    )
    i12 = s12.find("**outcomes**")
    s12 = s12[i12 : s12.find("**availability**", i12)] if i12 >= 0 else ""
    hand_a = next(
        (
            ln
            for ln in section(handoff, "## A. ", "## B. ").split("\n")
            if ln.startswith("- [") and "Loading / empty / error" in ln
        ),
        "",
    )
    for where, text in (
        ("board 08's row", " | ".join(board)),
        ("§12's outcomes", s12),
        ("the hand-off's §A error line", hand_a),
    ):
        out.append((where, text, ((where, err, text), (where, act, text)) if text else ()))
    return out


def load_error_gates(spec: str, handoff: str = "") -> list[str]:
    fails: list[str] = []
    for where, text, needs in load_error_carriers(spec, handoff):
        if not text:
            fails.append(f"load-error: {where} is missing (RULED M-2)")
            continue
        masked = text.replace(LOAD_ERROR, " " * len(LOAD_ERROR))
        bad_copy = bad_action = ""
        for clause in re.split(r"[;|—/·]", masked):
            if PRESET_ONLY.search(clause) and not WORKSPACE_WORD.search(clause):
                continue  # the gallery's own load error
            m = LOAD_FAIL_WORD.search(clause)
            if m and not bad_copy:
                bad_copy = m.group(0)
            for a in ACTION_WORD.finditer(clause):
                ok = a.group(0) == LOAD_ACTION and clause[max(0, a.start() - 1) : a.start()] in '["'
                if not ok and not bad_action:
                    bad_action = a.group(0)
        if bad_copy:
            fails.append(
                f"load-error: {where} words the switcher's load error otherwise ('{bad_copy}')"
            )
        if bad_action:
            fails.append(f"load-error: {where} names the switcher's action '{bad_action}'")
        for label, needle, cell in needs:
            is_copy = needle.startswith('"Couldn')
            if (bad_copy if is_copy else bad_action) or needle in cell:
                continue
            what = "E15-D03's " + needle if is_copy else "the action " + needle
            fails.append(f"load-error: {label} lacks {what}")
    return fails


# ---------------------------------------------------------------- whole-document clause gates (delta M-1) ----
# Every ruled sentence holds in every carrier, not only in the state inventory: each table row and each prose
# sentence of the spec and of the hand-off is one unit, read clause by clause, case-insensitively. The section 3.2
# rows stay with the frame gates above (their own vocabulary), and the section 5.2 / 6.2 / 10.3 prose with the
# section gates in string_gates, so one wrong form raises one FAIL.
TRIGGER_WORD = re.compile(r"\btrigger\b|CMP-217/trigger|\binline\b", re.IGNORECASE)
KEY_ELSEWHERE = re.compile(
    r"\bmenu (?:rows?|items?|below)\b|\btooltips?\b|\bin the menu\b", re.IGNORECASE
)
SWITCH_WORD = re.compile(
    r"\bswitch(?:es|ed|ing)?\b(?!\s+layout\b)|\bopens? (?:another|a) workspace\b|\bopens? Swing 4H\b",
    re.IGNORECASE,
)
DOC_PROMPT_WORD = re.compile(
    r"\bprompt(?:s|ed|ing)?\b|\bdialogs?\b|\btoasts?\b|\bconfirm(?:s|ation)?\b|\bmodal\b|alertdialog"
    r"|\bsave first\b|\basks?\b|\bsheets?\b|\bpopovers?\b|\btitled\b|\bwaits?\b|\bholds? (?:the|it)\b",
    re.IGNORECASE,
)
SCOPE_CONTROL = re.compile(
    r"\[[^\]\n]{0,24}\b(?:sub-?accounts?|accounts?|env(?:ironments?)?|demo|live|testnet)\b[^\]\n]{0,12}\]"
    r"|\b(?:sub-?accounts?|accounts?|env(?:ironments?)?)\s+(?:picker|switch(?:er)?|selector|select"
    r"|drop-?down|toggle|menu|control|chooser)s?\b"
    r"|\b(?:switch|change|pick|select|choose)\s+(?:the\s+)?(?:sub-?accounts?|accounts?|env(?:ironments?)?)\b"
    r"|\bEnv(?:ironment)?:\s*\w",
    re.IGNORECASE,
)
SPINE_PRESET_AS_WS = re.compile(
    r"(?<![.\w`-])(?:cards?|presets?|options?|thumbnails?)\b[^;|·,.]{0,24}?\bsaved workspaces?\b",
    re.IGNORECASE,
)
DOC_CARD_WORD = re.compile(r"(?<![.\w`-])(?:cards?|presets?|thumbnails?|options?)\b", re.IGNORECASE)
DOC_LOCK_WORD = re.compile(
    r"\block(?:ed|s)?\b|\bpadlock\b|\binert\b|can(?:'|’|no)t be (?:pressed|used|clicked|chosen|activated)"
    r"|\bdisabled\b(?! attribute)|\bgr[ae]yed(?: out)?\b|\bunavailable\b|\bblocked\b|\bgated\b"
    r"|\b(?:not|no longer) available\b",  # boards-PR carry (b): "not available" and kin are lock words
    re.IGNORECASE,
)
DOC_T1 = re.compile(
    r"\bApply\b|Browse presets…|Discard changes|\bOpen\b|\bCancel\b|\bClose\b|`Esc`|\bEsc\b|Back to gallery"
    r"|Keep current symbols|the search field|\bUndo\b|\bswitch(?:es|ing)?\b"
)
DIRTY_TOPIC = re.compile(r"dirty|marker|\\\*|unsaved changes", re.IGNORECASE)
PROMPT_OTHER = (
    "New workspace dialog",
    "the save-as dialog",
    "SCR-025's typed confirm",
    "the typed confirm",
)
FAIL_RULE = re.compile(
    r"the tool fails|\bfails? (?:if|when|any)\b|is a Major|violates it if|blurs the spine if|\bfails\b",
    re.IGNORECASE,
)


# re-check M-1: the subject a word speaks of is the nearest control named before it in the WHOLE unit (the
# row across its cells, the sentence across `;`, `—`, `(…)`), keyed by the control's full and short names;
# every preset or arrangement name is a card, the geometric ones in digits or in words
_NUM_NAME = {"1": "one", "2": "two", "3": "three", "4": "four", "9": "nine"}


def _arrangement_alt(label: str) -> str:
    m = re.fullmatch(r"(\d)([×+])(\d)", label)
    if not m:
        return re.escape(label) + (r"(?!\s+4H)" if label == "Swing" else "")
    a, op, b = m.groups()
    sep = r"\s*(?:[×x]|by)\s*" if op == "×" else r"\s*(?:\+|plus)\s*"
    return f"(?:{a}|{_NUM_NAME[a]}){sep}(?:{b}|{_NUM_NAME[b]})"


ARRANGEMENT_NAME = re.compile(
    r"(?<![\w.×+`/-])(?:"
    + "|".join(
        _arrangement_alt(n)
        for n in sorted(
            {x for p in INVENTORY for x in (p["label"], p["l1"]) if x}, key=len, reverse=True
        )
    )
    + r")(?![\w×+/-])",
    re.IGNORECASE,
)
CARD_SUBJECT = re.compile(
    ARRANGEMENT_NAME.pattern + r"|(?<![.\w`-])(?:cards?|presets?|thumbnails?|options?)\b",
    re.IGNORECASE,
)
KEY_HOME = re.compile(  # a saved layout, its menu row, its picker or the trigger: never a card
    r"\bsaved layouts?\b|\bLayout \d\b|\blayouts?\b|\bmenu(?:item\w*)?\b|\bmenu (?:rows?|items?)\b"
    r"|\bYour layouts\b|\bkey picker\b|\btrigger\b|\btooltips?\b|\bworkspaces?\b|\brows?\b|\bslot\b",
    re.IGNORECASE,
)
TRIGGER_SUBJECT = re.compile(
    r"\btrigger\b|CMP-217/trigger|\binline\b|\[Layout ▾\]|\bbadge on the trigger\b", re.IGNORECASE
)
TRIGGER_OTHER = re.compile(
    r"\bmenu(?: rows?| items?)?\b|\btooltips?\b|\bcards?\b|\bYour layouts\b|\bkey picker\b|\brows?\b"
    r"|\bitems?\b|\btab strip\b|\b(?:saved )?layouts?\b",
    re.IGNORECASE,
)
TRIGGER_KEY = re.compile(
    KEY_WORD.pattern
    + r"|\bbadges?\b|\b(?:shows?|carr(?:y|ies)|wears?|draws?|displays?|bears?)\s+(?:the|its|a|an)\s+"
    r"(?:key|hotkey|chord|slot(?: number)?)\b",
    re.IGNORECASE,
)
LOCK_T1 = re.compile(DOC_T1.pattern + r"|\bDiscard\b|\bApply\b")
LOCK_OTHER = re.compile(
    r"Save layout|Save as new layout…|\bSave as\b|\bRename\b…?|key picker|\bDelete\b…?|New workspace"
    r"|Duplicate|Set as default|Move up|Move down|Export…|Revert to saved…|\bwrites?\b|\bbutton\b"
    r"|\bitems?\b|\bthe saves\b|\bConfirm\b|\bName\b|\bcontrols?\b|\bT2\b|\bfields?\b"
)
SWITCH_SUBJECT = re.compile(  # a bare "open" after a list break or `Enter` opens a workspace (the rail)
    SWITCH_WORD.pattern
    + r"|(?:^|[;,|]\s*|\bEnter`?\s+)opens?\b(?=\s*(?:[;,.|)—]|$))|\bopens? the (?:first match|workspace)\b",
    re.IGNORECASE,
)
# delta r4: a fixture workspace (Scalping only as a rail row), or "the / a / another / the next workspace",
# opened, selected, picked or gone to is a switch too (D-9), whatever generic switch word the unit lacks
WS_SUBJECT = re.compile(
    "|".join(rf"\b{re.escape(w)}\b" for w in FIXTURE_WORKSPACES)
    + r"|\bScalping(?=\s*(?:\\\*|workspace\b|row\b|'s row\b))|\bthe Scalping (?:workspace|row)\b"
    + r"|(?<!New )\b(?:the next|the|a|another)\s+workspace\b(?!\s+(?:name|dialog|list|delete)\b)",
    re.IGNORECASE,
)
WS_VERB = re.compile(  # boards-PR carry (c): click, choose and select are switch verbs too
    r"\bopen(?:s|ed|ing)?\b|\bselect(?:s|ed|ing|ion)?\b|\bpick(?:s|ed|ing)?\b|\b(?:go(?:es)?|going|went)\s+to\b"
    r"|\bjump(?:s|ed|ing)?\s+to\b|\bclick(?:s|ed|ing)?(?:\s+on)?\b|\bchoos(?:e|es|ing)\b|\bchos(?:e|en)\b",
    re.IGNORECASE,
)

WS_OBJECT_GAP = re.compile(r"[\s,]*(?:the\s+)?")
WS_BARE_GAP = re.compile(r"[\s,]*")


def ws_switch(text: str) -> bool:
    """Whether a switch verb in the unit has a workspace as its subject (named up to 40 characters before it)
    or its object (right after it, across a comma and an article)."""
    for m in WS_VERB.finditer(text):
        gap = WS_OBJECT_GAP.match(text, m.end())
        # "the next workspace": the article stays with the subject (boards-PR carry (c))
        bare = WS_BARE_GAP.match(text, m.end())
        if any(WS_SUBJECT.match(text, g.end() if g else m.end()) for g in (gap, bare)):
            return True
        if any(w.end() >= m.start() - 40 for w in WS_SUBJECT.finditer(text, 0, m.start())):
            return True
    return False


PROMPT_HOME = re.compile(  # what may own a dialog or a confirm here: never a switch
    r"\bApply\b|SCR-029|SCR-025|\bDelete\b…?|typed (?:delete|confirm)|Save as new layout…|\bsave-as\b"
    r"|New workspace|\bRename\b…?|\bgallery\b|E15-D08|Export…|Revert to saved…",
    re.IGNORECASE,
)
# a token's usage list "(cards, chips, a gated fill)" names surfaces, never a state
TOKEN_USE = re.compile(
    r"`(?:color|space|size|type|radius|elevation|opacity|font|motion)\.[^`]*`\s*\([^)]*\)"
)
DIRTY_SUBJECT = re.compile(r"dirty|\basterisk\b|\\\*|unsaved changes", re.IGNORECASE)
DIRTY_AWAY = re.compile(
    DIRTY_DENY.pattern + r"|\boutside\s+(?:the\s+|its\s+)?(?:row(?:'s)?\s+)?name\b"
    r"|\bin\s+(?:a|the)\s+(?:separate\s+)?(?:note|notice|banner|toast|badge|caption|callout|second line)\b"
    r"|\b(?:under|below|beside|next to)\s+the\s+row\b",
    re.IGNORECASE,
)

KEY_AWAY = re.compile(r"[^|;]{0,16}?(?:" + KEY_ELSEWHERE.pattern + ")", re.IGNORECASE)

# boards-PR carry (a): a unit's subject is the first control or surface it names; a sentence that opens on
# "It" / "This" / "That" / "They" / "Its" speaks of the previous sentence's subject, put in the pronoun's place
SUBJECT_ANY: tuple[re.Pattern[str], ...] = (
    TRIGGER_SUBJECT,
    TRIGGER_OTHER,
    CARD_SUBJECT,
    KEY_HOME,
    LOCK_T1,
    LOCK_OTHER,
    SWITCH_SUBJECT,
    WS_SUBJECT,
    PROMPT_HOME,
)
SUBJECT_PRONOUN = re.compile(r"(It|Its|This|That|They)\b\s*")


def unit_subject(text: str) -> str:
    """The first control or surface the unit names (the longest at a tie), else ''."""
    bare = strip_quotes(text)
    best: re.Match[str] | None = None
    for pat in SUBJECT_ANY:
        m = pat.search(bare)
        if m and (
            best is None or (m.start(), -len(m.group(0))) < (best.start(), -len(best.group(0)))
        ):
            best = m
    return best.group(0) if best else ""


def with_subject(text: str, carried: str) -> str:
    """A pronoun-led sentence with the carried subject in the pronoun's place (unless a subject follows it)."""
    pm = SUBJECT_PRONOUN.match(text)
    if not (pm and carried) or any(p.match(text, pm.end()) for p in SUBJECT_ANY):
        return text
    return carried + ("'s " if pm.group(1) == "Its" else " ") + text[pm.end() :]


def subject_before(
    text: str, i: int, kinds: dict[str, re.Pattern[str]], window: int = 10**6
) -> str:
    """The kind of the nearest subject named before offset i in the unit, across any punctuation."""
    best, kind = -1, ""
    lo = max(0, i - window, text.rfind("·", 0, i) + 1)  # a "·" list item is its own subject
    for name, pat in kinds.items():
        for m in pat.finditer(text, lo, i):
            if m.end() <= i and m.end() > best:
                best, kind = m.end(), name
    return kind


def _neg_before(text: str, i: int) -> bool:
    a = max(text.rfind(c, 0, i) for c in ",;(|—") + 1
    return bool(NEG_WORD.search(text[a:i]) or NEGATED.search(text[max(0, i - 24) : i]))


def unit_key_on(
    text: str,
    kinds: dict[str, re.Pattern[str]],
    keys: re.Pattern[str],
    want: str,
    window: int = 80,
    default: str = "",
) -> str:
    """The first un-negated key word whose subject (the nearest named within `window` before it, across any
    punctuation, else the row's `default`, or the one it is put on) is `want`, else ''."""
    bare = TOKEN_USE.sub(lambda t: " " * len(t.group(0)), strip_quotes(text))
    for m in keys.finditer(bare):
        if _neg_before(bare, m.start()) or KEY_AWAY.match(bare, m.end()):
            continue
        tail = re.match(
            r"[^;,|()]{0,24}?\b(?:on|for|of|to)\s+(?:the\s+|each\s+|every\s+|a\s+|an\s+)?",
            bare[m.end() :],
        )
        after = ""
        if tail:
            j = m.end() + tail.end()
            after = next((k for k, pat in kinds.items() if pat.match(bare, j)), "")
        if want in (subject_before(bare, m.start(), kinds, window) or default, after):
            return bare[max(0, m.start() - 40) : m.end() + 20].strip()
    return ""


def sentences_of(line: str) -> list[str]:
    """A prose line split into sentences, never inside a double-quoted string."""
    out, start = [], 0
    for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z*\"`(\[])", line):
        if line.count('"', 0, m.start()) % 2 == 0:
            out.append(line[start : m.start()])
            start = m.end()
    out.append(line[start:])
    return [x.strip() for x in out if x.strip()]


def doc_units(spec: str, handoff: str) -> list[tuple[str, str, str]]:
    """(doc, where, text) per table row and per prose sentence of the spec and the hand-off."""
    out: list[tuple[str, str, str]] = []
    for doc, text in (("spec", spec), ("hand-off", handoff)):
        where = "Key" if doc == "spec" else "intro"
        fence = False
        for line in text.split("\n"):
            if line.startswith("```"):
                fence = not fence
                continue
            h = re.match(r"^(#{2,3}) (.*)$", line)
            if h:
                title = h.group(2)
                num = re.match(r"(\d+(?:\.\d+)?)\.? ", title)
                if doc == "spec" and num:
                    where = "§" + num.group(1)
                elif doc == "hand-off":
                    tab = re.match(r"(Table \d|Density|Essential exceptions|[AB])\b", title)
                    blk = re.search(r"CMP-\d+", title)
                    if tab:
                        where = ("§" if tab.group(1) in "AB" else "") + tab.group(1)
                    elif blk:
                        where = blk.group(0) + " block"
                continue
            if not line.strip() or line.startswith("<!--") or re.match(r"^\|\s*-", line):
                continue
            label = where if doc == "spec" else f"hand-off {where}"
            if line.startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if doc == "spec" and where == "§3.2" and cells[0].startswith("`"):
                    continue  # the frame rows: frame_gates
                if doc == "spec" and where == "§3.1" and len(cells) > 3:
                    # the frame-test column states a violation, never a drawn state
                    cells = cells[:3]
                key = (
                    cells[0]
                    if not re.fullmatch(r"\d+|CMP-\d+|—", cells[0])
                    else " ".join(cells[:2])
                )
                out.append((doc, f"{label} row '{key.strip('`*')[:28]}'", " | ".join(cells)))
                continue
            if fence:
                out.append((doc, f"{label} line", line.strip()))
                continue
            for sent in sentences_of(line):
                out.append((doc, f"{label} prose", sent))
    return out


def _unnegated(text: str, pat: re.Pattern[str]) -> re.Match[str] | None:
    return next(
        (
            m
            for m in pat.finditer(text)
            if not NEGATED.search(text[max(0, m.start() - 24) : m.start()])
        ),
        None,
    )


def doc_clauses(text: str) -> list[str]:
    return [c for c in re.split(r"[;|—·]", text) if c.strip()]


def doc_key_on_card(text: str, row_subject: bool = False) -> str:
    """The first sub-clause with an un-negated preset-card word and an un-negated key word, else ''.

    In a row whose subject is a preset (the inventory, the pair table, a gallery or listbox row) every
    un-negated key word counts."""
    for clause in doc_clauses(strip_quotes(text)):
        for sub in re.split(r"[,()]|\band\b", clause):
            if not (row_subject or _unnegated(sub, DOC_CARD_WORD)):
                continue
            if any(not NEG_WORD.search(sub[: m.start()]) for m in KEY_WORD.finditer(sub)):
                return clause.strip()
    return ""


def named_card_key(text: str) -> str:
    """The first clause with an un-negated key word and an un-negated named preset card, whatever the row's
    subject (delta r3: a key on the Scalping card in a keyboard row), else ''."""
    for clause in doc_clauses(strip_quotes(text)):
        for sub in re.split(r"[,()]|\band\b", clause):
            if not _unnegated(sub, NAMED_CARD):
                continue
            if any(not NEG_WORD.search(sub[: m.start()]) for m in KEY_WORD.finditer(sub)):
                return clause.strip()
    return ""


def doc_locked_t1(text: str) -> tuple[str, str]:
    """(subject, lock word) for the first lock word that speaks of a T1 control, else ('', '')."""
    for ok in LOCK_SKIP:
        text = text.replace(ok, " " * len(ok))
    for clause in doc_clauses(text):
        for m in DOC_LOCK_WORD.finditer(clause):
            if NEGATED.search(clause[max(0, m.start() - 24) : m.start()]):
                continue
            before = [s for s in DOC_T1.finditer(clause, 0, m.start()) if m.start() - s.end() <= 40]
            after = [s for s in DOC_T1.finditer(clause, m.end()) if s.start() - m.end() <= 12]
            subj = before[-1] if before else (after[0] if after else None)
            if subj:
                return subj.group(0), m.group(0)
    return "", ""


PRONOUN_LEAD = re.compile(r"(?:It|Its|This|That|They|Then|Both|Neither)\b")


def unit_locked_t1(text: str) -> tuple[str, str]:
    """(subject, lock word) where the nearest control before an un-negated lock word in the whole unit is a
    T1 control (full or short name), else ('', '')."""
    for ok in LOCK_SKIP:
        text = text.replace(ok, " " * len(ok))
    for m in DOC_LOCK_WORD.finditer(text):
        if NEGATED.search(text[max(0, m.start() - 24) : m.start()]):
            continue
        if subject_before(text, m.start(), {"t1": LOCK_T1, "other": LOCK_OTHER}, 60) == "t1":
            subj = [s for s in LOCK_T1.finditer(text, max(0, m.start() - 60), m.start())][-1]
            return subj.group(0), m.group(0)
    return "", ""


def document_gates(spec: str, handoff: str, bindings: set[str]) -> list[str]:
    fails: list[str] = []
    seen: set[str] = set()

    def add(msg: str) -> None:
        if msg not in seen:
            seen.add(msg)
            fails.append(msg)

    low = {b.lower() for b in bindings} | {k.lower() for k in COMPONENT_KEYS}
    unit_before = ("", "", "")
    carried = ""
    for doc, where, text in doc_units(spec, handoff):
        # a prose sentence that opens on a pronoun speaks of the previous sentence's subject (re-check M-1),
        # which takes the pronoun's place (boards-PR carry (a))
        last, unit_before = unit_before, (doc, where, text)
        same = last[:2] == (doc, where) and "prose" in where
        led = same and bool(PRONOUN_LEAD.match(text))
        own = with_subject(text, carried) if led else text
        carried = unit_subject(own) or (carried if led else "")
        if led:
            text = last[2] + " " + own
        sec0 = where.split(" ")[0]
        major = re.match(r"§(\d+)", sec0)
        keyed_already = doc == "spec" and (
            ("prose" in where and major is not None and 4 <= int(major.group(1)) <= 12)
            or (" row " in where and sec0 in ("§0", "§11.1", "§14"))
        )
        if not keyed_already:
            # RULED Q-22 and A2-4 on every other carrier: no bare F-key, every chord bound or PROPOSED
            fk = [
                k
                for k in bare_fkeys(text, bindings)
                if re.search(rf"`{k}`|\b{k} key\b", text, re.IGNORECASE)
            ]
            if fk:
                add(f"keys: {where} draws {fk[0]}, a key with no row in this context (RULED Q-22)")
            for cell in text.split("|"):
                for clause in cell.split(";"):
                    for m in CHORD.finditer(clause):
                        c = m.group(0)
                        if all(e.lower() in low for e in expand_chord(c)):
                            continue
                        pm = re.search(r"proposed", clause[m.end() :], re.IGNORECASE)
                        gap = clause[m.end() : m.end() + pm.start()] if pm else ""
                        if not pm or re.search(r"\b(?:SCR|CMP)-\d|\bor\b", gap):
                            add(f"keys: {where} draws {c} without PROPOSED after it")
        if FAIL_RULE.search(text):
            text = " | ".join(c for c in re.split(r"(?<=\.)\s|\|", text) if not FAIL_RULE.search(c))
        sec = where.split(" ")[0]
        prose = "prose" in where
        cells = text.split(" | ")
        # boards-PR carry (d): a hand-off row's Variant / Element cell sets the row's subject
        row_kinds = {"trigger": TRIGGER_SUBJECT, "other": TRIGGER_OTHER}
        row_subject = (
            subject_before(cells[1], len(cells[1]), row_kinds)
            if doc == "hand-off" and not prose and len(cells) > 1
            else ""
        )
        # merged E15-D03 D-9: the trigger never carries a key chip inline
        for clause in doc_clauses(strip_quotes(text)):
            sub_hit = next(
                (
                    m
                    for sub in re.split(r"[,()]|\band\b", clause)
                    if TRIGGER_WORD.search(sub)
                    for m in KEY_WORD.finditer(sub)
                    if not NEG_WORD.search(sub[: m.start()])
                ),
                None,
            )
            if sub_hit:
                add(
                    f"trigger: {where} draws a key chip inline on the trigger ('{sub_hit.group(0)}'; "
                    "merged E15-D03 D-9)"
                )
                break
        else:
            # the row's subject carries to its last cell: the trigger may be named a whole row earlier
            tk = unit_key_on(
                text,
                {"trigger": TRIGGER_SUBJECT, "other": TRIGGER_OTHER},
                TRIGGER_KEY,
                "trigger",
                10**6,
                row_subject,
            )
            if tk:
                add(
                    f"trigger: {where} puts the key on the trigger ('{tk[-60:]}'; merged E15-D03 D-9)"
                )
        # no key on a preset card
        if not (doc == "spec" and sec in ("§5.2", "§6.2") and prose):
            subject = (doc == "spec" and sec in ("§6.1", "§6.2") and not prose) or (
                doc == "hand-off"
                and not prose
                and bool(
                    re.search(
                        r"gallery|listbox|preset|thumbnail|\bcards?\b",
                        cells[1] if len(cells) > 1 else "",
                    )
                )
            )
            cl = doc_key_on_card(
                " | ".join(cells[2:]) if subject and doc == "hand-off" else text, subject
            ) or named_card_key(text)
            ak = (
                ""
                if cl
                else unit_key_on(text, {"card": CARD_SUBJECT, "home": KEY_HOME}, KEY_WORD, "card")
            )
            if ak:
                add(f"spine: {where} keys an arrangement as a card ('{ak[-60:]}')")
            if cl:
                add(f"spine: {where} puts a hotkey on a preset card ('{cl[:60]}')")
        # D-9: a switch never prompts (per table cell, per prose sentence)
        if not (doc == "spec" and sec == "§10.3" and prose):
            found = None
            for cell in [text] if prose else cells:
                prev = False  # a short fragment after a switch clause speaks of that switch
                for clause in doc_clauses(cell):
                    bare = strip_quotes(clause)
                    prev = bool(SWITCH_WORD.search(bare)) or (prev and len(bare.split()) <= 6)
                    if not prev:
                        continue
                    body = clause
                    for ok in PROMPT_OK + PROMPT_OTHER:
                        body = body.replace(ok, " " * len(ok))
                    found = found or _unnegated(body, DOC_PROMPT_WORD)
            bare_unit = strip_quotes(text)
            if not found and (_unnegated(bare_unit, SWITCH_SUBJECT) or ws_switch(bare_unit)):
                body = text
                for ok in PROMPT_OK + PROMPT_OTHER:
                    body = body.replace(ok, " " * len(ok))
                whole = next(
                    (
                        m
                        for m in DOC_PROMPT_WORD.finditer(body)
                        if not NEGATED.search(body[max(0, m.start() - 24) : m.start()])
                        and subject_before(
                            body,
                            m.start(),
                            {"switch": SWITCH_SUBJECT, "ws": WS_SUBJECT, "other": PROMPT_HOME},
                        )
                        != "other"
                    ),
                    None,
                )
                if whole:
                    add(
                        f"switch: {where} prompts in the row or sentence of a switch ('{whole.group(0)}')"
                    )
            if found:
                add(f"switch: {where} prompts on a switch ('{found.group(0)}')")
        # the dirty marker stays in the row name
        for clause in doc_clauses(text):
            hit = DIRTY_DENY.search(clause) if DIRTY_TOPIC.search(clause) else None
            if hit:
                add(f"dirty: {where} moves the dirty marker out of the row name ('{hit.group(0)}')")
                break
        else:
            for m in DIRTY_AWAY.finditer(text):
                if DIRTY_SUBJECT.search(text, 0, m.start()):
                    add(
                        f"dirty: {where} draws the dirty marker away from the row name ('{m.group(0)}')"
                    )
                    break
        # no lock, inert or can't-be-pressed wording on a T1 control
        subj, lword = unit_locked_t1(text)
        if not subj:
            subj, lword = doc_locked_t1(text)
        if subj:
            add(f"lock: {where} locks {subj} ('{lword}')")
        # C-2.11: no account or environment control
        ctl = _unnegated(strip_quotes(text), SCOPE_CONTROL)
        if ctl:
            add(f"scope: {where} draws an account or environment control ('{ctl.group(0)}')")
        # the spine: a preset is an arrangement, never a saved workspace
        ws = _unnegated(strip_quotes(text), SPINE_PRESET_AS_WS)
        if ws:
            add(f"spine: {where} calls a preset a saved workspace ('{ws.group(0)[:60]}')")
    return fails


# ---------------------------------------------------------------- counts, markers, numbers -------------------
def counts(spec: str, handoff: str) -> dict[str, int]:
    inv = inventory_rows(spec)
    return {
        "count_boards": count(r"^\| \d\d +\| `", section(spec, "## 0. ", "## 1. ")),
        "count_light_boards": count(
            r"^\| \d\d +\| `[a-z0-9-]*light", section(spec, "## 0. ", "## 1. ")
        ),
        "count_ac_rows": count(
            r"^\| (?:Sc\. \d|DoD|Test plan|Security|A11y|Performance|Observability|`14`)",
            section(spec, "### 1.2 ", "## 2. "),
        ),
        "count_decisions": count(r"^\| D-\d+ ", section(spec, "### 3.1 ", "### 3.2 ")),
        "count_frames_named": len({r[0] for r in inv}),
        "count_t2_frames": len(T2_FRAMES),
        "count_key_rows": len(rows_of(section(spec, "### 11.1 ", "### 11.2 "))),
        "count_announcements": count(r"^\| AN-\d+ ", section(spec, "### 11.3 ", "## 12. ")),
        "count_copy_rows": count(r"^\| `[a-z._]+` ", section(spec, "## 14. ", "## 15. ")),
        "count_a_rows": count(r"^\| A-\d+ ", section(spec, "## 15. ", "## 16. ")),
        "count_c_rows": count(r"^\| C-\d+ ", section(spec, "## 19. ", "## 20. ")),
        "count_g_rows": count(r"^\| G-\d+ ", section(spec, "## 19. ", "## 20. ")),
        "count_oq_rows": count(r"^\| OQ-\d+ ", section(spec, "## 19. ", "## 20. ")),
        "count_events": len(EVENTS),
        "count_handoff_blocks": count(r"^## Handoff checklist", handoff),
        "count_pair_rows": count(r"^\| \d+ +\| [^|]+ · ", section(spec, "### 6.2 ", "## 7. ")),
    }


@functools.lru_cache(maxsize=1)
def _gallery() -> dict[str, Any]:
    return gallery_report()


@functools.lru_cache(maxsize=1)
def _inventory() -> dict[str, Any]:
    g = _gallery()
    thumbs = {
        w: (g["layouts"][f"{w}-compact"]["thumb_w"], g["layouts"][f"{w}-compact"]["thumb_h"])
        for w in WIDTHS
    }
    thumbs["zoom200"] = (g["zoom200"]["thumb_w"], g["zoom200"]["thumb_h"])
    return inventory_report(thumbs)


@functools.lru_cache(maxsize=1)
def _matrix() -> dict[str, Any]:
    return matrix_report([])


@functools.lru_cache(maxsize=1)
def _menu() -> dict[str, Any]:
    return menu_report()


@functools.lru_cache(maxsize=1)
def _rail() -> dict[str, Any]:
    return rail_report()


def build_markers(spec: str, handoff: str) -> dict[str, Any]:
    """The values the spec's `audit:` markers carry (also printed under ``--json``)."""
    g, inv, m, menu, rail = _gallery(), _inventory(), _matrix(), _menu(), _rail()
    t = tokens_px()
    l19, l12 = g["layouts"]["1920-compact"], g["layouts"]["1280-compact"]
    l19c, l12c = g["layouts"]["1920-comfortable"], g["layouts"]["1280-comfortable"]
    t125, t150, z = g["layouts"]["1280-compact-125"], g["layouts"]["1280-compact-150"], g["zoom200"]
    rows12 = {r["label"]: r for r in inv["rows"]}
    mk: dict[str, Any] = {
        "gallery_w_1920": GALLERY["1920"][0],
        "gallery_h_1920": GALLERY["1920"][1],
        "gallery_w_1280": GALLERY["1280"][0],
        "gallery_h_1280": GALLERY["1280"][1],
        "canvas_1920_w": canvas("1920")[0],
        "canvas_1920_h": canvas("1920")[1],
        "canvas_1280_w": canvas("1280")[0],
        "canvas_1280_h": canvas("1280")[1],
        "dialog_pad": t["dialog_pad"],
        "card_gutter": CARD_GUTTER,
        "min_card_w": MIN_CARD_W,
        "header_compact": l19["header"],
        "header_comfortable": l19c["header"],
        "footer_compact": l19["footer"],
        "footer_comfortable": l19c["footer"],
        "body_1920_compact": l19["body"],
        "body_1280_compact": l12["body"],
        "cols": l19["cols"],
        "card_rows": l19["card_rows"],
        "card_w_1920": l19["card_w"],
        "card_w_1280": l12["card_w"],
        "card_h_1920": l19["card_h"],
        "card_h_1280": l12["card_h"],
        "thumb_w_1920": l19["thumb_w"],
        "thumb_h_1920": l19["thumb_h"],
        "thumb_w_1280": l12["thumb_w"],
        "thumb_h_1280": l12["thumb_h"],
        "contents_lines_1920": l19["contents_lines"],
        "contents_lines_1280": l12["contents_lines"],
        "listbox_full_1920": l19["listbox_full"],
        "listbox_full_1280": l12["listbox_full"],
        "listbox_visible_1920_compact": l19["listbox_visible"],
        "listbox_visible_1280_compact": l12["listbox_visible"],
        "listbox_visible_1280_comfortable": l12c["listbox_visible"],
        "card_rows_visible_1920": l19["card_rows_visible"],
        "card_rows_visible_1280": l12["card_rows_visible"],
        "yl_rows_1920_compact": l19["yl_rows_visible"],
        "yl_rows_1280_compact": l12["yl_rows_visible"],
        "yl_rows_1920_comfortable": l19c["yl_rows_visible"],
        "yl_rows_1280_comfortable": l12c["yl_rows_visible"],
        "yl_row_compact": l19["yl_row"],
        "yl_row_comfortable": l19c["yl_row"],
        "yl_peek": l19["peek"],
        "yl_name_w": l19["yl_name_w"],
        "yl_picker_w": l19["yl_picker_w"],
        "yl_delete_w": l19["yl_delete_w"],
        "yl_kinds_w_1280": l12["yl_kinds_w"],
        "sentence_w": l19["sentence_w"],
        "warning_w": l19["warning_w"],
        "empty_lines_1280": l12["empty_lines"],
        "body_px": t["font_base"],
        "caption_px": t["font_xs"],
        "body_lh": l19["body_lh"],
        "caption_lh": l19["cap_lh"],
        "zoom200_w": ZOOM200[0],
        "zoom200_h": ZOOM200[1],
        "zoom200_between_bars": z["between_bars"],
        "zoom200_modal_w": z["width"],
        "zoom200_modal_h": z["height"],
        "zoom200_cols": z["cols"],
        "zoom200_card_rows": z["card_rows"],
        "zoom200_card_w": z["card_w"],
        "zoom200_card_h": z["card_h"],
        "zoom200_thumb_w": z["thumb_w"],
        "zoom200_thumb_h": z["thumb_h"],
        "zoom200_footer": z["footer"],
        "zoom200_scroll": z["scroll"],
        "zoom200_listbox_full": z["listbox_full"],
        "zoom200_contents_lines": z["contents_lines"],
        "text125_card_h": t125["card_h"],
        "text125_contents_lines": t125["contents_lines"],
        "text125_listbox_visible": t125["listbox_visible"],
        "text125_yl_rows": t125["yl_rows_visible"],
        "text150_card_h": t150["card_h"],
        "text150_sentence_w": t150["sentence_w"],
        "text150_listbox_visible": t150["listbox_visible"],
        "text150_yl_rows": t150["yl_rows_visible"],
        "text150_sentence_lines": lines_for(FOOTER_SENTENCE, t150["inner_w"], t150["cap_px"]),
        "inventory_count": inv["count"],
        "served_count": inv["served_count"],
        "proposed_ids": inv["proposed_ids"],
        "panel_total": inv["panel_total"],
        "pair_count": inv["pair_count"],
        "pairs_by_geometry": inv["pairs_by_geometry"],
        "pairs_by_glyphs": inv["pairs_by_glyphs"],
        "glyph_requests": inv["glyph_request_count"],
        "glyph_px": GLYPH_PX,
        "thumb_word_px": thumb_word_px(),
        "thumb_gap": THUMB_GAP,
        "min_cell_w_1280": min(r["cells"]["1280"]["min_w"] for r in inv["rows"]),
        "min_cell_h_1280": min(r["cells"]["1280"]["min_h"] for r in inv["rows"]),
        "words_fit_1280": sum(1 for r in inv["rows"] if r["cells"]["1280"]["word_fits"]),
        "words_fit_zoom200": sum(1 for r in inv["rows"] if r["cells"]["zoom200"]["word_fits"]),
        "glyph_fits_1280": sum(1 for r in inv["rows"] if r["cells"]["1280"]["glyph_fits"]),
        "cell_3x3_w_1280": rows12["3×3"]["cells"]["1280"]["min_w"],
        "cell_3x3_h_1280": rows12["3×3"]["cells"]["1280"]["min_h"],
        "menu_w": menu["menu_w"],
        "menu_row_compact": t["row_compact"],
        "menu_row_comfortable": t["row_comfortable"],
        "menu_separator": menu["separator"],
        "menu_h_compact_4": menu["heights"]["compact-4"],
        "menu_h_compact_9": menu["heights"]["compact-9"],
        "menu_h_compact_12": menu["heights"]["compact-12"],
        "menu_h_compact_32": menu["heights"]["compact-32"],
        "menu_h_comfortable_4": menu["heights"]["comfortable-4"],
        "menu_h_comfortable_12": menu["heights"]["comfortable-12"],
        "menu_h_comfortable_32": menu["heights"]["comfortable-32"],
        "menu_avail_1280_compact": menu["available"]["1280-compact"],
        "menu_avail_1280_comfortable": menu["available"]["1280-comfortable"],
        "menu_avail_1920_compact": menu["available"]["1920-compact"],
        "menu_avail_1920_comfortable": menu["available"]["1920-comfortable"],
        "menu_first_scroll_1280_compact": menu["first_scroll"]["1280-compact"],
        "menu_first_scroll_1280_comfortable": menu["first_scroll"]["1280-comfortable"],
        "menu_first_scroll_1920_comfortable": menu["first_scroll"]["1920-comfortable"],
        "menu_first_scroll_1920_compact": menu["first_scroll"]["1920-compact"] or "never",
        "twelve_keyed": menu["twelve_keyed"],
        "twelve_nokey": menu["twelve_nokey"],
        "reach_without_key": menu["reach_without_key"],
        "hotkey_slots": HOTKEY_SLOTS,
        "layout_cap": LAYOUT_CAP,
        "workspace_cap": WORKSPACE_CAP,
        "twelve": TWELVE,
        "rail_expanded": rail["expanded"],
        "rail_collapsed": rail["collapsed"],
        "rail_fixed_rows": rail["fixed_rows"],
        "rail_fit_1280_compact": rail["fit"]["1280-compact"],
        "rail_fit_1280_compact_search": rail["fit"]["1280-compact-search"],
        "rail_fit_1280_comfortable": rail["fit"]["1280-comfortable"],
        "rail_fit_1280_comfortable_search": rail["fit"]["1280-comfortable-search"],
        "rail_fit_1920_compact_search": rail["fit"]["1920-compact-search"],
        "rail_fit_1920_comfortable_search": rail["fit"]["1920-comfortable-search"],
        "rail_stack_compact": rail["stack"]["compact"],
        "rail_stack_comfortable": rail["stack"]["comfortable"],
        "search_threshold": rail["search_threshold"],
        "rail_name_w": rail["row_w_name_max"],
        "matrix_pairs": m["pairs"],
        "matrix_gated": m["gated"],
        "matrix_failed": m["failed"],
        "validity_alpha": m["validity_alpha"],
        "validity_ratio_dark": m["validity"]["dark"]["ratio"],
        "validity_ratio_light": m["validity"]["light"]["ratio"],
        "validity_ratio_hc": m["validity"]["high-contrast"]["ratio"],
        "reason_max": REASON_MAX,
        "reason_chars_view_as": len(REASONS["rbac.view_as"]),
        "reason_chars_permission": len(REASONS["rbac.permission"]),
        "reason_chars_layout_limit": len(REASONS["layout.limit.count"]),
        "reason_chars_workspace_limit": len(REASONS["workspace.limit.count"]),
        "reason_chars_workspace_last": len(REASONS["workspace.limit.last"]),
        "reserved_count": keymap_rows()["reserved_count"],
        "keymap_rows_cited": len(keymap_rows()["rows"]),
        "tokens_bound": len(BOUND),
        "tokens_missing": len(bound_missing()),
    }
    mk.update(counts(spec, handoff))
    return mk


BOUND = (
    "color.surface.app",
    "color.surface.canvas",
    "color.surface.raised",
    "color.surface.overlay",
    "color.surface.hover",
    "color.surface.selected",
    "color.border.default",
    "color.border.selected",
    "color.text.primary",
    "color.text.secondary",
    "color.text.tertiary",
    "color.text.disabled",
    "color.text.on-action",
    "color.focus.ring",
    "color.action.primary.default",
    "color.status.danger.default",
    "color.status.danger.strong",
    "opacity.disabled",
    "radius.control",
    "radius.card",
    "radius.dialog",
    "radius.xs",
    "elevation.dialog",
    "elevation.popover",
    "space.dialog.padding",
    "space.inset.md",
    "space.inset.sm",
    "space.inset.xs",
    "space.stack.sm",
    "size.control.height",
    "size.row.height",
    "size.icon.sm",
    "size.icon.md",
    "type.ui.body",
    "type.ui.caption",
    "type.ui.heading-sm",
    "type.ui.label",
    "color.text.inverse",
    "font.size.2xs",
    "font.weight.medium",
)


def bound_missing() -> list[str]:
    dark = theme("dark")
    return [n for n in BOUND if n not in dark]


# carried literals the prose and the frames quote, each with its source; printed under --json "constants"
CONSTS: dict[str, Any] = {
    "search_fixture": SEARCH_FIXTURE,  # E15-D02 :304
    "topbar_h": TOPBAR_H,  # E15-D02 section 3
    "statusbar_h": STATUSBAR_H,  # E15-D02 section 3
    "stroke_hairline": int(STROKE_PX[0]),  # the hairline edge
    "stroke_ring": int(STROKE_PX[1]),  # the selected and focus rings
    "stroke_bar": int(STROKE_PX[2]),  # the current-row bar (E15-D02 :306)
    "registry_glyphs": 47,  # `15` CMP-019 :225: the base registry's glyph count
    "e10_cap_125": 300,  # E10-D03 :275: the rail's cap at the 125 % text scale
    "e10_row_125": 30,  # E10-D03 :275
    "e10_glyph_125": 20,  # E10-D03 :275
    "e10_row_200": 48,  # E10-D03 :275: the rail at 200 % zoom
    "e10_glyph_200": 32,  # E10-D03 :275
    "rail_motion_ms": 120,  # `14` :329: the rail's expand / collapse animates in <=120 ms
    "search_settle_ms": 500,  # `15` CMP-048 :519: the results count, 500 ms after the last keystroke
    "ws_name_min": 1,  # `22` WorkspaceInput.name minLength (:19636)
    "ws_name_max": 40,  # `22` WorkspaceInput.name maxLength (:19637)
}


def ledger(mk: dict[str, Any]) -> dict[str, Any]:
    """Every name a registered number may bind to: the carried literals, the token sizes and the markers."""
    derived = {"inner_w_1280": _gallery()["layouts"]["1280-compact"]["inner_w"]}
    return {**CONSTS, **derived, **{f"tok_{k}": v for k, v in tokens_px().items()}, **mk}


MARKER = re.compile(r"<!--\s*audit:([A-Za-z0-9_.-]+)=([^\s>]+)\s*-->")
_N = r"(\d[\d,]*(?:\.\d+)?)"
# registered prose contexts: (label, pattern, marker names per group)
CONTEXTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "gallery dims",
        rf"CMP-043 `lg`, {_N}×{_N} at 1920×1080 and {_N}×{_N} at 1280×800",
        ("gallery_w_1920", "gallery_h_1920", "gallery_w_1280", "gallery_h_1280"),
    ),
    ("canvas fit", rf"the {_N}×{_N} canvas at 1280×800", ("canvas_1280_w", "canvas_1280_h")),
    (
        "columns",
        rf"{_N} columns of {_N} px cards at 1920×1080 and {_N} px at 1280×800",
        ("cols", "card_w_1920", "card_w_1280"),
    ),
    (
        "card height",
        rf"a card is {_N} px tall at 1920×1080 and {_N} px at 1280×800",
        ("card_h_1920", "card_h_1280"),
    ),
    (
        "thumbnails",
        rf"thumbnails of {_N}×{_N} and {_N}×{_N} px",
        ("thumb_w_1920", "thumb_h_1920", "thumb_w_1280", "thumb_h_1280"),
    ),
    (
        "your layouts rows",
        rf"Your layouts shows {_N} rows at 1920×1080 and {_N} at 1280×800 in compact",
        ("yl_rows_1920_compact", "yl_rows_1280_compact"),
    ),
    (
        "listbox visible",
        rf"the listbox keeps {_N} px at 1920×1080 and {_N} px at 1280×800",
        ("listbox_visible_1920_compact", "listbox_visible_1280_compact"),
    ),
    ("zoom modal", rf"a {_N}×{_N} modal between the bars", ("zoom200_modal_w", "zoom200_modal_h")),
    (
        "zoom scroll",
        rf"the {_N} px between the header and the sticky footer scroll as one",
        ("zoom200_scroll",),
    ),
    ("zoom row card", rf"a card is a {_N} px row", ("zoom200_card_h",)),
    ("menu width", rf"the menu is {_N} px wide", ("menu_w",)),
    ("menu twelve", rf"twelve layouts stand {_N} px tall in compact", ("menu_h_compact_12",)),
    (
        "menu scroll",
        rf"scrolls inside the menu from {_N} layouts at compact and {_N} at comfortable at 1280×800",
        ("menu_first_scroll_1280_compact", "menu_first_scroll_1280_comfortable"),
    ),
    (
        "rail fit",
        rf"{_N} workspace rows fit at compact and {_N} at comfortable at 1280×800 with the search field",
        ("rail_fit_1280_compact_search", "rail_fit_1280_comfortable_search"),
    ),
    (
        "rail stack",
        rf"32 × 24 = {_N} px and 32 × 32 = {_N} px",
        ("rail_stack_compact", "rail_stack_comfortable"),
    ),
    (
        "pairs",
        rf"{_N} pairs, {_N} told apart by geometry and {_N} by glyphs and label",
        ("pair_count", "pairs_by_geometry", "pairs_by_glyphs"),
    ),
    (
        "twelve",
        rf"{_N} keyed `Ctrl\+1\.\.9` and {_N} \"\(no key\)\"",
        ("twelve_keyed", "twelve_nokey"),
    ),
    ("matrix", rf"{_N} gated rows, {_N} FAIL", ("matrix_gated", "matrix_failed")),
)
HANDOFF_CONTEXTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("handoff matrix", rf"{_N} gated pairs, {_N} FAIL", ("matrix_gated", "matrix_failed")),
    (
        "handoff tokens",
        rf"{_N} bound, {_N} missing; no new token",
        ("tokens_bound", "tokens_missing"),
    ),
)
# delta M-3: every typed number of the hand-off's prose and tables, bound to its --json name
_HANDOFF_LEDGER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "handoff menu notes",
        (
            "the menu {} px wide, rows {} compact / {} comfortable, {} px separators; twelve layouts {} px "
            "in compact; scrolls inside the menu from {} layouts at compact and {} at comfortable at 1280×800"
        ),
        (
            "menu_w",
            "menu_row_compact",
            "menu_row_comfortable",
            "menu_separator",
            "menu_h_compact_12",
            "menu_first_scroll_1280_compact",
            "menu_first_scroll_1280_comfortable",
        ),
    ),
    (
        "handoff gallery notes",
        "header {} / {}, footer {} / {}, {} columns of {} / {} px cards {} / {} px tall",
        (
            "header_compact",
            "header_comfortable",
            "footer_compact",
            "footer_comfortable",
            "cols",
            "card_w_1920",
            "card_w_1280",
            "card_h_1920",
            "card_h_1280",
        ),
    ),
    (
        "handoff your layouts notes",
        "Your layouts rows {} / {} showing {} rows (compact)",
        ("yl_row_compact", "yl_row_comfortable", "yl_rows_1920_compact"),
    ),
    ("handoff zoom notes", "each card a {} px row", ("zoom200_card_h",)),
    (
        "handoff rail notes",
        (
            "the rail {} px expanded / {} collapsed, rows {} compact / {} comfortable, the {} px current bar, "
            "the name column {} px; {} workspace rows fit at compact and {} at comfortable at 1280×800 with "
            "the search field ({} / {} without), {} / {} at 1920×1080 with it; the cap stacks to {} / {} px"
        ),
        (
            "rail_expanded",
            "rail_collapsed",
            "tok_row_compact",
            "tok_row_comfortable",
            "stroke_bar",
            "rail_name_w",
            "rail_fit_1280_compact_search",
            "rail_fit_1280_comfortable_search",
            "rail_fit_1280_compact",
            "rail_fit_1280_comfortable",
            "rail_fit_1920_compact_search",
            "rail_fit_1920_comfortable_search",
            "rail_stack_compact",
            "rail_stack_comfortable",
        ),
    ),
    (
        "handoff rail zoom notes",
        "at 125 % the rail grows to a {} px cap, at 200 % it collapses to {} px with {} px rows",
        ("e10_cap_125", "rail_collapsed", "e10_row_200"),
    ),
    ("handoff targets", "every target reaches {} px in compact", ("tok_control_compact",)),
    ("handoff search", "the search combobox above {} workspaces", ("search_threshold",)),
    (
        "handoff rail target",
        "the smallest target the {} × {} row in compact",
        ("tok_row_compact", "tok_row_compact"),
    ),
    ("handoff bar token", "`color.border.selected` (the {} px bar)", ("stroke_bar",)),
    ("handoff hit targets", "Hit targets ≥ {} px compact", ("tok_control_compact",)),
    ("handoff focus ring", "a visible {} px focus ring", ("stroke_ring",)),
    # re-check M-3: the remaining typed numbers of the prose, each bound to its --json name
    (
        "handoff key picker target",
        "the smallest target the {} × {} key picker in compact",
        ("tok_control_compact", "tok_control_compact"),
    ),
    ("handoff hotkey slots", "`LayoutInput.hotkey_slot` 1..{} unique", ("hotkey_slots",)),
    ("handoff workspace page", "`listWorkspaces` once (≤ {}, one page)", ("workspace_cap",)),
    ("handoff workspace list", "`listWorkspaces` (≤ {}, by `sort_order`", ("workspace_cap",)),
    ("handoff rail motion", "transform-only within {} ms (`14` :329)", ("rail_motion_ms",)),
    (
        "handoff name bounds",
        "`WorkspaceInput.name` {}–{} unique per user",
        ("ws_name_min", "ws_name_max"),
    ),
)
_HANDOFF_TABLE_LEDGER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "handoff density CMP-217 compact",
        "menu rows {}, separators {}; gallery header {}, footer {}, Your layouts rows {}, cards {} / {}",
        (
            "menu_row_compact",
            "menu_separator",
            "header_compact",
            "footer_compact",
            "yl_row_compact",
            "card_h_1920",
            "card_h_1280",
        ),
    ),
    (
        "handoff density CMP-217 comfortable",
        "menu rows {}; header {}, footer {}, Your layouts rows {}",
        ("menu_row_comfortable", "header_comfortable", "footer_comfortable", "yl_row_comfortable"),
    ),
    (
        "handoff density CMP-073 compact",
        "rows {}; the {} px bar; the {} px collapsed rail",
        ("tok_row_compact", "stroke_bar", "rail_collapsed"),
    ),
    (
        "handoff table 1 overflow",
        "Overflow (twelve; scrolling from {} at compact)",
        ("menu_first_scroll_1280_compact",),
    ),
    ("handoff table 1 limit", "view-as, {} layouts)", ("layout_cap",)),
    ("handoff table 2 search", "CMP-048; above {} workspaces", ("search_threshold",)),
    ("handoff table 1 search", "ManyWorkspaces (search above {})", ("search_threshold",)),
    # re-check M-3: the Density table's token values and target sizes, Tables 3 to 5 (any padding)
    (
        "handoff density CMP-217 compact pads",
        "`space.dialog.padding` {}; `space.inset.md` {} | {} × {} (the key picker, Delete…)",
        ("tok_dialog_pad", "tok_inset_md", "tok_control_compact", "tok_control_compact"),
    ),
    (
        "handoff density CMP-217 comfortable pads",
        "| `space.dialog.padding` {} | {} × {} |",
        ("tok_dialog_pad", "tok_control_comfortable", "tok_control_comfortable"),
    ),
    (
        "handoff density CMP-073 compact pads",
        "| `space.inset.sm` {}; `space.inset.md` {} | {} × {} (a row)",
        ("tok_inset_sm", "tok_inset_md", "tok_row_compact", "tok_row_compact"),
    ),
    (
        "handoff density CMP-073 comfortable",
        "| comfortable | rows {} | `space.inset.sm` {} | {} × {} |",
        ("tok_row_comfortable", "tok_inset_sm", "tok_row_comfortable", "tok_row_comfortable"),
    ),
    ("handoff table 3 name", "| {}–{}; the validity look", ("ws_name_min", "ws_name_max")),
    ("handoff table 4 rail", "transform-only within {} ms (`14` :329)", ("rail_motion_ms",)),
    ("handoff table 5 list", "| ≤ {}, one page |", ("workspace_cap",)),
    ("handoff table 5 search", "once per settled query ({} ms)", ("search_settle_ms",)),
)


def _tpl(template: str) -> str:
    """A literal stretch of the spec with {} where a number stands, as a context pattern; a run of spaces
    matches any run (a padded table cell, a re-aligned table)."""
    return _N.join(re.sub(r"(?:\\ )+", r"\\s+", re.escape(part)) for part in template.split("{}"))


# M-3: every other number the prose types, bound to its --json name (a marker, a token size or a carried
# literal of CONSTS); a counted number outside every context fails the coverage gate below
_LEDGER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("shell rows", "between the {} px TopBar and the {} px StatusBar", ("topbar_h", "statusbar_h")),
    ("dialog edge", "on a {} px `color.border.default` edge, `elevation", ("stroke_hairline",)),
    ("dialog padding", "`space.dialog.padding` {} px. Rows", ("dialog_pad",)),
    (
        "dialog rows",
        (
            "the header {} px compact / {} comfortable, the footer {} / {} (§5.3), the body {} px at "
            "1920×1080 compact and {} at 1280×800"
        ),
        (
            "header_compact",
            "header_comfortable",
            "footer_compact",
            "footer_comfortable",
            "body_1920_compact",
            "body_1280_compact",
        ),
    ),
    ("rename field", "the inline Rename field ({} px; a", ("yl_name_w",)),
    ("key picker", "the key picker ({} px,", ("yl_picker_w",)),
    (
        "your layouts row",
        (
            "kinds in words ({} px at 1280×800), Delete… ({} px) — rows {} px compact / {} comfortable "
            "with a {} px gap"
        ),
        ("yl_kinds_w_1280", "yl_delete_w", "yl_row_compact", "yl_row_comfortable", "tok_inset_xs"),
    ),
    ("peek", "one full card row and a {} px peek of the next", ("yl_peek",)),
    (
        "your layouts comfortable",
        "in compact ({} and {} in comfortable)",
        ("yl_rows_1920_comfortable", "yl_rows_1280_comfortable"),
    ),
    ("grid", "from a {} px minimum card and {} px gutters", ("min_card_w", "card_gutter")),
    ("card inset", "px at 1280×800 — {} px inset, the thumbnail", ("tok_inset_md",)),
    ("tallest card", "the tallest card sets the row: {} caption lines", ("contents_lines_1920",)),
    (
        "full grid",
        "Eleven cards make {} card rows; the full grid stands {} px at 1920×1080 and {} at 1280×800",
        ("card_rows", "listbox_full_1920", "listbox_full_1280"),
    ),
    ("selected ring", "`aria-selected`, a {} px `color.border.selected` ring", ("stroke_ring",)),
    ("focused ring", "takes the {} px `color.focus.ring` outside the ring", ("stroke_ring",)),
    (
        "footer lines",
        "the warning {} px and the sentence {} px against the {} px inner width at 1280×800",
        ("warning_w", "sentence_w", "inner_w_1280"),
    ),
    ("footer wrap", "the sentence wraps to {} lines (§5.4)", ("text150_sentence_lines",)),
    (
        "footer height",
        "Footer height {} px compact / {} comfortable",
        ("footer_compact", "footer_comfortable"),
    ),
    ("skeletons", "`SCR-022/gallery-loading`): {} card skeletons", ("inventory_count",)),
    ("zoom bars", "the body between the bars {} px", ("zoom200_between_bars",)),
    ("zoom padding", "its padding tightens to {} px", ("tok_inset_md",)),
    ("zoom contents", "the contents ({} caption lines at most)", ("zoom200_contents_lines",)),
    (
        "zoom whole",
        "A {} px row inside a {} px viewport is always whole",
        ("zoom200_card_h", "zoom200_scroll"),
    ),
    (
        "text 125",
        "at 125 % the cards grow to {} px ({} caption lines), the listbox keeps {} px and Your layouts {} rows",
        ("text125_card_h", "text125_contents_lines", "text125_listbox_visible", "text125_yl_rows"),
    ),
    (
        "text 150",
        (
            "at 150 % the cards are {} px, the footer sentence wraps to {} lines ({} px against {}), "
            "Your layouts shows {} row"
        ),
        (
            "text150_card_h",
            "text150_sentence_lines",
            "text150_sentence_w",
            "inner_w_1280",
            "text150_yl_rows",
        ),
    ),
    (
        "inventory",
        "the one inventory ({} presets, {} served, {} with PROPOSED ids, {} panels in all",
        ("inventory_count", "served_count", "proposed_ids", "panel_total"),
    ),
    ("thumbnail gaps", "with {} px gaps, each cell", ("thumb_gap",)),
    (
        "thumbnail edge",
        "with a {} px `color.border.default` edge and carrying",
        ("stroke_hairline",),
    ),
    ("thumbnail word", "`font.size.2xs` ({} px, the smallest type token)", ("thumb_word_px",)),
    ("thumbnail glyph", "beside a {} px glyph stand-in", ("glyph_px",)),
    ("glyph requests", "`journal` ({}, the `PaneKind` words)", ("glyph_requests",)),
    ("registry", "(E05-T06's {} glyphs are not shipped)", ("registry_glyphs",)),
    (
        "glyph fit",
        "the {} px glyph fits in all {} thumbnails, the kind word fits in {} of them",
        ("glyph_px", "glyph_fits_1280", "words_fit_1280"),
    ),
    ("word fit 200", "CSS px) the word fits in all {}.", ("words_fit_zoom200",)),
    (
        "menu rows",
        "with rows {} px compact / {} comfortable and {} px separators",
        ("menu_row_compact", "menu_row_comfortable", "menu_separator"),
    ),
    (
        "menu room",
        "({} px are available below the tab strip at 1280×800 compact, {} in comfortable; {} / {} at 1920×1080)",
        (
            "menu_avail_1280_compact",
            "menu_avail_1280_comfortable",
            "menu_avail_1920_compact",
            "menu_avail_1920_comfortable",
        ),
    ),
    (
        "menu scroll 1920",
        ", from {} at comfortable at 1920×1080 and never at 1920×1080 compact up to the cap of {}",
        ("menu_first_scroll_1920_comfortable", "layout_cap"),
    ),
    (
        "menu heights",
        "Four layouts stand {} px in compact ({} comfortable), nine {}, thirty-two {} ({} comfortable)",
        (
            "menu_h_compact_4",
            "menu_h_comfortable_4",
            "menu_h_compact_9",
            "menu_h_compact_32",
            "menu_h_comfortable_32",
        ),
    ),
    ("menu limit", "then at {} layouts Save as takes", ("layout_cap",)),
    ("reach", "at the cap, {} layouts are reachable without a key", ("reach_without_key",)),
    ("twelve rows", "above its {} visible rows", ("yl_rows_1920_compact",)),
    ("save-as limit", "**At {} layouts** (`SCR-022/save-as-limit`)", ("layout_cap",)),
    ("rename width", "a CMP-007 field {} px wide", ("yl_name_w",)),
    ("empty lines", "({} lines at 1280×800) with the CTA", ("empty_lines_1280",)),
    (
        "rail widths",
        "The expanded rail is {} px, the collapsed rail {} px",
        ("rail_expanded", "rail_collapsed"),
    ),
    (
        "rail row",
        (
            "rows {} px compact / {} comfortable (`size.row.height`), the name column {} px after the {} px "
            "bar, the insets and the {} px glyph"
        ),
        ("tok_row_compact", "tok_row_comfortable", "rail_name_w", "stroke_bar", "tok_icon_md"),
    ),
    ("rail search row", "and, above {} workspaces, as the search combobox", ("search_threshold",)),
    ("rail focus", "focus-visible — the {} px `color.focus.ring`", ("stroke_ring",)),
    ("rail bar", "the {} px leading bar in `color.border.selected`", ("stroke_bar",)),
    (
        "rail 125",
        "the rail grows to a cap of {} px, then labels ellipsise with a tooltip, rows {} px and the glyph {} px",
        ("e10_cap_125", "e10_row_125", "e10_glyph_125"),
    ),
    (
        "rail 200",
        "the rail collapses to {} px by default with its labels in the tooltips, rows {} px and glyphs {} px",
        ("rail_collapsed", "e10_row_200", "e10_glyph_200"),
    ),
    ("rail page", "`listWorkspaces` returns at most {} workspaces in one page", ("workspace_cap",)),
    (
        "rail canvas",
        "against the {} px canvas at 1280×800 less the {} fixed rows",
        ("canvas_1280_h", "rail_fixed_rows"),
    ),
    (
        "rail fit others",
        "({} and {} without it; {} and {} with it at 1920×1080)",
        (
            "rail_fit_1280_compact",
            "rail_fit_1280_comfortable",
            "rail_fit_1920_compact_search",
            "rail_fit_1920_comfortable_search",
        ),
    ),
    ("rail list", "(a list of {} rows needs none", ("workspace_cap",)),
    ("search threshold", "above {} workspaces CMP-073's combobox", ("search_threshold",)),
    ("workspace limit", "Duplicate and New workspace at {} workspaces take", ("workspace_cap",)),
    ("reserved", "`reserved-keys.json` ({} entries)", ("reserved_count",)),
    ("focus stop", "a visible {} px `color.focus.ring` marks every stop", ("stroke_ring",)),
    ("reason max", "one sentence of at most {} characters", ("reason_max",)),
    (
        "reason view-as",
        '"Read-only while viewing as {user}." ({} characters)',
        ("reason_chars_view_as",),
    ),
    (
        "reason permission",
        '"Your role can\'t save workspaces." ({}); then',
        ("reason_chars_permission",),
    ),
    (
        "reason layout limit",
        '"This workspace has the most layouts it can hold." ({})',
        ("reason_chars_layout_limit",),
    ),
    (
        "reason workspace limit",
        '"You have the most workspaces you can have." ({})',
        ("reason_chars_workspace_limit",),
    ),
    ("reason last", '"You need at least one workspace." ({}) —', ("reason_chars_workspace_last",)),
    ("gate layouts", "(+ `layout.limit.count` at {} layouts)", ("layout_cap",)),
    ("gate workspaces", "(+ `workspace.limit.count` at {} workspaces)", ("workspace_cap",)),
    (
        "densities",
        "compact {} px rows and controls, comfortable {})",
        ("tok_row_compact", "tok_row_comfortable"),
    ),
    ("tokens §13", "**Tokens bound:** {}, {} missing", ("tokens_bound", "tokens_missing")),
    ("checklist search", "more than {} workspaces with search", ("search_threshold",)),
    ("menu cap", "The menu lists at most {} layouts", ("layout_cap",)),
    ("menu from", "from {} layouts at compact at 1280×800", ("menu_first_scroll_1280_compact",)),
    ("rail cap", "The rail lists at most {} workspaces in one page", ("workspace_cap",)),
    (
        "rail fit §17",
        "above the {} rows that fit at compact at 1280×800",
        ("rail_fit_1280_compact_search",),
    ),
    (
        "rail stack §17",
        "{} rows at {} px are {} px",
        ("workspace_cap", "tok_row_compact", "rail_stack_compact"),
    ),
    ("tokens §18", "the tool's {} bound tokens, {} missing", ("tokens_bound", "tokens_missing")),
    ("frames §21", "{} named frames in §3.2", ("count_frames_named",)),
    ("your layouts §21", "Your layouts shows {} rows then scrolls", ("yl_rows_1920_compact",)),
    (
        "listbox §21",
        (
            "the Presets listbox — {} columns of {} / {} px cards, {} / {} px tall — scrolls at both widths "
            "with one card row and a {} px peek"
        ),
        ("cols", "card_w_1920", "card_w_1280", "card_h_1920", "card_h_1280", "yl_peek"),
    ),
    ("row card §21", "each card a {} px row", ("zoom200_card_h",)),
    ("ids §21", "({} served ids, {} PROPOSED)", ("served_count", "proposed_ids")),
    ("glyph §21", "the smallest cell 44×26 holds the {} px glyph", ("glyph_px",)),
    ("twelve §21", '(twelve layouts: {} keyed, {} "(no key)")', ("twelve_keyed", "twelve_nokey")),
    ("rail §21", "The rail: {} / {} px", ("rail_expanded", "rail_collapsed")),
    ("search §21", "search above {};", ("search_threshold",)),
    (
        "contrast §21",
        "Contrast: {} pairs in three themes with greyscale twins, {} gated rows, {} FAIL",
        ("matrix_pairs", "matrix_gated", "matrix_failed"),
    ),
    (
        "counts §21",
        "{} tokens bound, {} missing; {} announcements, {} key rows ({} existing keymap rows cited by line",
        (
            "tokens_bound",
            "tokens_missing",
            "count_announcements",
            "count_key_rows",
            "keymap_rows_cited",
        ),
    ),
    ("rows §21", "{} C-rows, {} G-rows, {} OQs", ("count_c_rows", "count_g_rows", "count_oq_rows")),
)
LEDGER_CONTEXTS = tuple((label, _tpl(tpl), names) for label, tpl, names in _LEDGER)
HANDOFF_LEDGER_CONTEXTS = tuple((label, _tpl(tpl), names) for label, tpl, names in _HANDOFF_LEDGER)
HANDOFF_TABLE_CONTEXTS = tuple(
    (label, _tpl(tpl), names) for label, tpl, names in _HANDOFF_TABLE_LEDGER
)
# numbers inside table rows the record named (the inputs, the AC trace, D-2)
TABLE_CONTEXTS: tuple[tuple[str, str, tuple[str, ...]], ...] = tuple(
    (label, _tpl(tpl), names)
    for label, tpl, names in (
        (
            "tokens §1.1",
            "the tool resolves {} bound tokens, {} missing",
            ("tokens_bound", "tokens_missing"),
        ),
        (
            "pairs §1.2",
            (
                "(the {} pairs, {} told apart by geometry and {} by glyphs and label; the smallest cell 44×26 "
                "holds the {} px glyph)"
            ),
            ("pair_count", "pairs_by_geometry", "pairs_by_glyphs", "glyph_px"),
        ),
        ("D-2 card", "five columns from a {} px minimum card", ("min_card_w",)),
        ("D-2 peek", "one card row and a {} px peek, then scrolls", ("yl_peek",)),
        ("D-2 row", "a card is a {} px row (the thumbnail", ("zoom200_card_h",)),
    )
)
COVER = re.compile(
    r"(?<![\d.×+:–\-#§])(\d+(?:,\d{3})?(?:\.\d+)?) (?:px|rows?|columns|cards?|card rows|card skeletons"
    r"|layouts|workspaces|lines?|caption lines|pairs|tokens|bound tokens|panels|presets|served|key rows"
    r"|existing|announcements|A-rows|C-rows|G-rows|OQs|gated rows|characters|entries|glyphs|named frames"
    r"|thumbnails|FAIL|missing|keyed|that fit|at comfortable|of them|with PROPOSED)\b"
)


class _UniqueList(list[str]):
    """A FAIL list that keeps one copy of each message (a spaced N × N edit is one wrong size)."""

    def append(self, msg: str) -> None:
        if msg not in self:
            super().append(msg)


def same_number(text: str, value: Any) -> bool:
    s = text.replace(",", "").replace(" ", "")
    try:
        return math.isclose(float(s), float(value), abs_tol=1e-9)
    except (TypeError, ValueError):
        return str(value) == text


def allowed_dims(mk: dict[str, Any]) -> set[tuple[str, str]]:
    g = _gallery()
    dims = {
        ("1920", "1080"),
        ("1280", "800"),
        ("24", "24"),
        ("32", "32"),
        ("640", "400"),
        ("2440", "4653"),
        ("2440", "4187"),
        ("480", "240"),
        ("3", "3"),
        ("2", "2"),
        ("2", "1"),
        ("1", "2"),
        ("1", "1"),
        ("3", "1"),
    }
    for k in (
        "gallery_w_1920",
        "gallery_w_1280",
        "canvas_1920_w",
        "canvas_1280_w",
        "thumb_w_1920",
        "thumb_w_1280",
        "zoom200_modal_w",
        "zoom200_thumb_w",
        "card_w_1920",
        "card_w_1280",
        "zoom200_card_w",
    ):
        h = k.replace("_w", "_h")
        dims.add((str(mk[k]), str(mk[h])))
    for r in _inventory()["rows"]:
        for where in r["cells"].values():
            dims.add((str(where["min_w"]), str(where["min_h"])))
    for lay in g["layouts"].values():
        dims.add((str(lay["thumb_w"]), str(lay["thumb_h"])))
        dims.add((str(lay["card_w"]), str(lay["card_h"])))
    return dims


def allowed_ratios(m: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for r in m["rows"]:
        for th in THEMES:
            out.add(r["themes"][th]["ratio"])
            out.add(r["themes"][th]["grey"])
    for v in m["validity"].values():
        out.add(v["ratio"])
        out.add(v["reason"])
    for r in cvd_report()["rows"].values():
        for v in r.values():
            if isinstance(v, dict):
                out.add(v["ratio"])
    out.update({fmt(BAR["text"]), fmt(BAR["non-text"]), fmt(BAR["hc-text"]), "0.45", "0.60"})
    return out


# re-check M-3: a typed number of the hand-off is any digit run (a range N–M / N..M and a spaced
# N × M count as one); left out, each for a stated reason: code and copy (backticks, double quotes)
# and headings; a cite or an id (`16` §12, :329, E15-D02, CMP-217, Ctrl+1, §5.4); an index (Table 2,
# row 17, the Layout 1 fixture); a key slot ("Hotkey: 1", the key gates own it); the contract's status
# codes; the two-decimal ratios and the unspaced W×H (the ratio and size gates own them)
HANDOFF_NUM = re.compile(
    r"(?<![\w.:§#+\-–/…×])\d+(?:,\d{3})*(?:\.\d+)?(?:(?:–|\.\.)\d+| × \d+| ?%)?(?![\w+…×\-]|\.\d|:\d)"
)
HANDOFF_NUM_INDEX = re.compile(  # an index, a fixture name or a key slot (the key gates own a slot)
    r"(?:\bTables?|\brow|\bLayout|\bstep|\b(?:hot-?)?keys?:?|\bslot)\s+$", re.IGNORECASE
)
HTTP_STATUS = ("409", "412")  # `22`'s refusals, named by code (never a measure)
SCALES_PCT = (*TEXT_SCALES, 200)  # the text scales and the 200 % zoom the tool measures


def handoff_numbers(text: str) -> list[tuple[str, int]]:
    """(token, offset) for every typed number of a hand-off text the coverage gate reads."""
    blank = re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), strip_quotes(text))
    blank = ARRANGEMENT_NAME.sub(lambda m: " " * len(m.group(0)), blank)  # "2 by 2" is a name
    out: list[tuple[str, int]] = []
    for hit in HANDOFF_NUM.finditer(blank):
        tok_, at = hit.group(0), hit.start()
        line_start = blank.rfind("\n", 0, at) + 1
        if blank.startswith("#", line_start) or HANDOFF_NUM_INDEX.search(blank[line_start:at]):
            continue
        if tok_ in HTTP_STATUS or re.fullmatch(r"\d+\.\d\d", tok_):
            continue
        if re.match(r"\s*§", blank[hit.end() :]) or re.match(r"×\d", blank[hit.end() :]):
            continue  # a document cite (16 §12) or an unspaced size (the size gate)
        if blank[hit.end() :].startswith(" named frames"):
            continue  # the frame-count gate in string_gates owns it
        out.append((tok_, at))
    return out


def number_gates(spec: str, handoff: str) -> list[str]:
    fails = _UniqueList()
    mk = build_markers(spec, handoff)
    seen: dict[str, int] = {}
    for hit in MARKER.finditer(spec):
        name, value = hit.group(1), hit.group(2)
        seen[name] = seen.get(name, 0) + 1
        if name not in mk:
            fails.append(f"marker: audit:{name} is not a key the tool prints")
        elif str(mk[name]) != value:
            fails.append(f"marker: audit:{name}={value} but --json prints {mk[name]}")
    for name in sorted(mk):
        if seen.get(name, 0) != 1:
            fails.append(f"marker: audit:{name} appears {seen.get(name, 0)} times (once expected)")
    # prose = the spec without its marker lines and without table rows (the frame and inventory rows are gated by
    # name; the section 13 and 6.2 tables are compared row by row), so one wrong number is one FAIL
    prose = "\n".join(
        ln for ln in spec.split("\n") if not ln.startswith("<!--") and not ln.startswith("|")
    )
    hand_prose = "\n".join(ln for ln in handoff.split("\n") if not ln.startswith("|"))
    table_lines = "\n".join(ln for ln in spec.split("\n") if ln.startswith("|"))
    hand_tables = "\n".join(ln for ln in handoff.split("\n") if ln.startswith("|"))
    led = ledger(mk)
    spans: list[tuple[int, int]] = []
    hand_spans: dict[str, list[tuple[int, int]]] = {"hand-off": [], "hand-off table": []}
    for where, text, ctx in (
        ("spec", prose, CONTEXTS + LEDGER_CONTEXTS),
        ("hand-off", hand_prose, HANDOFF_CONTEXTS + HANDOFF_LEDGER_CONTEXTS),
        ("spec table", table_lines, TABLE_CONTEXTS),
        ("hand-off table", hand_tables, HANDOFF_TABLE_CONTEXTS),
    ):
        for label, pattern, names in ctx:
            hits = list(re.finditer(pattern, text))
            if not hits:
                fails.append(f"number: the {where} context '{label}' vanished")
            for hit in hits:
                if where == "spec":
                    spans.append(hit.span())
                elif where in hand_spans:
                    hand_spans[where].append(hit.span())
                for i, name in enumerate(names, start=1):
                    if not same_number(hit.group(i), led[name]):
                        fails.append(
                            f"number: {label}: the {where} says {hit.group(i)}, the tool {led[name]}"
                        )
    # coverage: every counted number the prose types sits inside a registered context (copy and headings aside)
    blanked = strip_quotes(prose)
    for hit in COVER.finditer(blanked):
        line_start = blanked.rfind("\n", 0, hit.start()) + 1
        if blanked.startswith("#", line_start):
            continue
        if not any(a <= hit.start() < b for a, b in spans):
            fails.append(f"number: the spec types '{hit.group(0)}' outside a registered context")
    # the hand-off too: EVERY number it types, with or without a unit word, with or without spaces around ×,
    # sits inside a registered context (delta M-3, re-check M-3); handoff_numbers names the few exceptions
    for where, text in (("hand-off", hand_prose), ("hand-off table", hand_tables)):
        for tok_, at in handoff_numbers(text):
            if tok_.endswith("%"):
                if int(tok_[:-1].strip()) not in SCALES_PCT:
                    fails.append(f"number: the {where}'s {tok_} is not a scale the tool measures")
                continue
            if not any(a <= at < b for a, b in hand_spans[where]):
                fails.append(f"number: the {where} types '{tok_}' outside a registered context")
    # the section 13 matrix rows equal the tool's, row by row
    want = {r[0]: r for r in rows_of(matrix_table(_matrix()))}
    have = {
        r[0]: r
        for r in rows_of(section(spec, "## 13. ", "**Validity look"))
        if r and r[0] and not r[0].startswith("Pair")
    }
    for key, r in want.items():
        if have.get(key) != r:
            fails.append(f"matrix: the §13 row '{key[:48]}' differs from the tool's")
    for key in set(have) - set(want):
        fails.append(f"matrix: the §13 row '{key[:48]}' is not a tool row")
    # the pair table equals the tool's
    want_pairs = rows_of(pairs_table(_inventory()))
    have_pairs = [
        r for r in rows_of(section(spec, "### 6.2 ", "## 7. ")) if r and re.fullmatch(r"\d+", r[0])
    ]
    if have_pairs != want_pairs:
        fails.append("pairs: the §6.2 pair table differs from the tool's")
    # every W×H and every two-decimal ratio in the spec and the hand-off is the tool's
    dims, ratios = allowed_dims(mk), allowed_ratios(_matrix())
    tables = "\n".join(ln for ln in (spec + "\n" + handoff).split("\n") if ln.startswith("|"))
    tables = "\n".join(
        ln for ln in tables.split("\n") if "(grey " not in ln
    )  # the section 13 rows: compared above
    for where, text in (("spec", prose + "\n" + tables), ("hand-off", hand_prose)):
        for hit in re.finditer(r"(?<![\d.])(\d+)×(\d+)(?![\d.])", text):
            if (hit.group(1), hit.group(2)) not in dims:
                fails.append(f"number: the {where}'s {hit.group(0)} is not a size the tool derives")
        for hit in re.finditer(r"(?<![\d.\-])(\d+\.\d\d)(?![\d.])", text):
            if hit.group(1) not in ratios:
                fails.append(
                    f"number: the {where}'s ratio {hit.group(1)} is not one the tool derives"
                )
    return fails


def gates(
    spec: str,
    handoff: str,
    tool: str,
    bindings: set[str],
    pr_body: str = "",
    files: list[str] | None = None,
    catalogue: str = "",
) -> list[str]:
    """Each returned string is a failed gate. The order and wording are stable (the self-test keys on them)."""
    fails = string_gates(spec, handoff, tool, pr_body, files or [], catalogue)
    if not spec:
        return fails
    mk = build_markers(spec, handoff)
    fails += frame_gates(spec, bindings, ledger(mk))
    fails += load_error_gates(spec, handoff)
    fails += d08_switch_row_gates(spec)
    fails += document_gates(spec, handoff, bindings)
    fails += number_gates(spec, handoff)
    fails += fit_gates(_gallery())
    km = keymap_rows()
    if km["ctrl_shift_s_reserved"]:
        fails.append("keys: Ctrl+Shift+S has an entry in reserved-keys.json")
    for rid, chord in km["expected"].items():
        if km["rows"].get(rid, {}).get("binding") != chord:
            fails.append(f"keys: keymap row {rid} is not bound to {chord}")
    for k, v in reasons_report().items():
        if not v["ok"]:
            fails.append(f"reasons: {k} is longer than {REASON_MAX} characters")
    return fails


# ---------------------------------------------------------------- self-test ----------------------------------
def in_section(text: str, start: str, end: str, fn: Callable[[str], str]) -> str:
    i = text.find(start)
    assert i >= 0, start
    j = text.find(end, i + len(start))
    j = j if j > 0 else len(text)
    return text[:i] + fn(text[i:j]) + text[j:]


# The frame-level mutation table (the pre-READY audit): each edits ONE element in ONE named row (or one table
# cell / marker) and must trip its own FAIL message exactly once. Targets: "frame:<id>" (the state-inventory row),
# "inv:<label>" (the section 6.1 inventory row), "line:<prefix>" (the one spec line starting so), "hand:<prefix>".
Edit = tuple[str, str, str]
# fmt: off
MUTATIONS: tuple[tuple[str, str, tuple[Edit, ...]], ...] = (
    ("M01", "carrier: frame SCR-022/gallery-1920 lacks the keep-symbols carrier with its default",
     (("frame:SCR-022/gallery-1920", "footer: [x] Keep current symbols (on), the warning line", "footer: the warning line"),)),
    ("M02", "carrier: frame SCR-022/gallery-1920 lacks the warning line",
     (("frame:SCR-022/gallery-1920", "the warning line \"Applying a preset replaces the current layout. Settings of surviving panels are kept.\", ", "the warning line, "),)),
    ("M03", "carrier: frame SCR-022/gallery-1920 lacks the arrangement-only sentence",
     (("frame:SCR-022/gallery-1920", "the sentence \"Applying a preset changes the arrangement only — never the selected account or environment.\", ", ""),)),
    ("M04", "spine: frame SCR-022/gallery-1920 puts a hotkey on a preset card",
     (("frame:SCR-022/gallery-1920", "no card carries a key chip", "every card carries its `Ctrl+1` chip"),)),
    ("M05", "carrier: frame SCR-022/gallery-1280 lacks the initial-focus statement",
     (("frame:SCR-022/gallery-1280", "initial focus on the first card; ", ""),)),
    ("M06", "order: the listbox frame does not list the presets in the inventory's order",
     (("frame:SCR-022/presets-listbox", "Swing, 2×2, 1+3", "2×2, Swing, 1+3"),)),
    ("M07", "cut: the listbox frame draws the cut preset",
     (("frame:SCR-022/presets-listbox", "3×3, 1×1;", "3×3, 3+1, 1×1;"),)),
    ("M08", "inventory: Scalping does not say what opens instead (AD-3)",
     (("inv:Scalping", "; the order ticket opens as its drawer (M-001; E15-D01 OQ-7)", ""),)),
    ("M09", "inventory: Analyst's accessible name uses a forbidden word (this)",
     (("inv:Analyst", "Analyst: chart and journal, stacked, two panels; Replay opens on its own page", "Analyst: chart and journal, stacked, two panels; Replay opens on this page"),)),
    ("M10", "inventory: 2×2's panel count differs from the tool's (4)",
     (("inv:2×2", "| 2×2            | 4      |", "| 2×2            | 3      |"),)),
    ("M11", "carrier: frame SCR-022/your-layouts-twelve lacks 9 keyed",
     (("frame:SCR-022/your-layouts-twelve", "9 keyed", "8 keyed"),)),
    ("M12", "carrier: frame SCR-022/your-layouts-empty lacks the create instruction",
     (("frame:SCR-022/your-layouts-empty", " Save the current arrangement as a new layout (Ctrl+Shift+S) to switch between layouts with Ctrl+1..9.", ""),)),
    ("M13", "t2-anatomy: frame SCR-022/your-layouts-viewer draws a CTA in the sentence form ('button')",
     (("frame:SCR-022/your-layouts-viewer", "with no CTA and no button", "with no CTA and a button"),)),
    ("M14", "t2-anatomy: frame SCR-022/your-layouts-view-as lacks the lock glyph",
     (("frame:SCR-022/your-layouts-view-as", "the `lock` glyph leads the full label", "the full label"),)),
    ("M15", "route: frame SCR-022/apply-dirty does not focus Cancel",
     (("frame:SCR-022/apply-dirty", "[Cancel], Cancel focused;", "[Cancel], Discard changes focused;"),)),
    ("M16", "carrier: frame SCR-022/apply-dirty lacks [Cancel]",
     (("frame:SCR-022/apply-dirty", "[Discard changes] [Cancel], Cancel focused", "[Discard changes], Cancel focused"),)),
    ("M17", "lock: frame SCR-022/apply-dirty-viewer locks Discard changes ('locked')",
     (("frame:SCR-022/apply-dirty-viewer", "Discard changes stays T1 and applies", "Discard changes is locked and applies"),)),
    ("M18", "t2-anatomy: frame SCR-022/save-as-limit lacks the limit key",
     (("frame:SCR-022/save-as-limit", "`disabledReason` → `layout.limit.count` ", "`disabledReason` → a free sentence "),)),
    ("M19", "t2-form: frame SCR-022/save-as-invalid draws '`lock`'",
     (("frame:SCR-022/save-as-invalid", "no lock, no CMP-079, no key", "a `lock` glyph, no CMP-079, no key"),)),
    ("M20", "carrier: frame SCR-022/delete-layout-confirm lacks the effect-naming label",
     (("frame:SCR-022/delete-layout-confirm", "[Delete layout] [Cancel]", "[Confirm] [Cancel]"),)),
    ("M21", "confirm: the delete confirm frame does not focus Cancel",
     (("frame:SCR-022/delete-layout-confirm", "[Cancel], Cancel focused;", "[Cancel], Delete layout focused;"),)),
    ("M22", "order: the menu frame does not list saved layouts, then the saves, then Browse presets… (AD-2)",
     (("frame:CMP-217/menu-default", "320 px wide): ✓ Layout 1", "320 px wide): Browse presets… · ✓ Layout 1"),)),
    ("M23", "t2-anatomy: frame CMP-217/menu-saves-t2 uses the `disabled` attribute",
     (("frame:CMP-217/menu-saves-t2", "the `lock` glyph leads it, `aria-disabled`, CMP-079", "the `lock` glyph leads it, the `disabled` attribute, CMP-079"),)),
    ("M24", "availability: frame CMP-217/menu-viewer draws a lock on an availability state ('`lock`')",
     (("frame:CMP-217/menu-viewer", "no lock, no CMP-079 (E15-D02 :645)", "a `lock` glyph, no CMP-079 (E15-D02 :645)"),)),
    ("M25", "carrier: frame SCR-011/expanded lacks `aria-current=\"page\"`",
     (("frame:SCR-011/expanded", ", `aria-current=\"page\"`", ""),)),
    ("M26", "carrier: frame SCR-011/dirty lacks the dirty marker in the row name",
     (("frame:SCR-011/dirty", "\"Scalping, unsaved changes\" as the accessible name", "\"Scalping\" as the accessible name"),)),
    ("M27", "spine: frame SCR-011/expanded shows layout keys in the switcher",
     (("frame:SCR-011/expanded", "no row carries a layout key", "each row carries its `Ctrl+1` key"),)),
    ("M28", "delete: the context menu frame offers a one-click workspace delete ('Delete')",
     (("frame:SCR-011/context-menu", "Export…, Delete… (the last group", "Export…, Delete (the last group"),)),
    ("M29", "t2-anatomy: frame SCR-011/last-workspace lacks the limit key",
     (("frame:SCR-011/last-workspace", "`disabledReason` → `workspace.limit.last` ", "`disabledReason` → a free sentence "),)),
    ("M30", "carrier: frame SCR-011/search lacks above 20",
     (("frame:SCR-011/search", "above 20 workspaces", "above 24 workspaces"),)),
    ("M31", "carrier: frame SCR-011/rename-inplace lacks `Esc` reverts",
     (("frame:SCR-011/rename-inplace", "`Enter` saves via `updateWorkspace`, `Esc` reverts; a name", "`Enter` saves via `updateWorkspace`; a name"),)),
    ("M32", "carrier: frame SCR-011/empty lacks the failed-create explanation",
     (("frame:SCR-011/empty", "after a first create that failed:", "after a first create:"), ("frame:SCR-011/empty", "the error line of the failed `createWorkspace`", "the error line of `createWorkspace`"),)),
    ("M33", "boards: a section-0 board row is not PENDING",
     (("line:| 01  ", "scr-022-gallery-1920.png` PENDING", "scr-022-gallery-1920.png`"),)),
    ("M34", "closing: handoff carries a closing keyword",
     (("hand:# E15-D05", "(`16` §11.4;", ("(clo" "ses #321; `16` §11.4;")),)),
    ("M35", "spine: frame SCR-011/search does not name its noun (saved workspace)",
     (("frame:SCR-011/search", "| picks a saved workspace ", "| picks an arrangement "),)),
    ("M36", "spine: frame CMP-217/trigger does not name its noun (saved layout)",
     (("frame:CMP-217/trigger", "| switches a saved layout ", "| picks a saved workspace "),)),
    ("M37", "switch: frame SCR-011/switch-dirty prompts on a switch ('prompt')",
     (("frame:SCR-011/switch-dirty", "at once with no prompt (D-9)", "after a prompt (D-9)"),)),
    ("M38", "carrier: frame SCR-022/gallery-1280 lacks the arrangement-only sentence",
     (("frame:SCR-022/gallery-1280", "the sentence \"Applying a preset changes the arrangement only — never the selected account or environment.\", ", ""),)),
    ("M39", "carrier: frame SCR-022/light-gallery lacks the keep-symbols carrier with its default",
     (("frame:SCR-022/light-gallery", "with [x] Keep current symbols (on), ", "with "),)),
    ("M40", "exits: frame SCR-022/gallery-1920 does not draw its exit `Esc`",
     (("frame:SCR-022/gallery-1920", "| `Esc` and Cancel close the dialog, focus returns", "| Cancel closes the dialog, focus returns"),)),
    ("M41", "exits: frame CMP-217/menu-default does not class its exits T1",
     (("frame:CMP-217/menu-default", "focus returns to the trigger; T1", "focus returns to the trigger; T3"),)),
    ("M42", "exits: frame SCR-011/expanded gates an exit in its Exits cell",
     (("frame:SCR-011/expanded", "| `Esc` leaves a focused row's menu closed", "| `Esc` is gated and leaves a focused row's menu closed"),)),
    ("M43", "keys: frame SCR-011/context-menu draws Shift+F10 without PROPOSED after it",
     (("frame:SCR-011/context-menu", "`Shift+F10` PROPOSED)", "`Shift+F10` as drawn)"),)),
    ("M44", "t2-frames: frame CMP-217/menu-limit is not classed T2",
     (("frame:CMP-217/menu-limit", "| T2 ", "| T1 "),)),
    ("M45", "lock: frame SCR-022/apply-clean locks Undo ('lock')",
     (("frame:SCR-022/apply-clean", "persistent until the next change)", "persistent until the next change, a `lock` glyph on Undo)"),)),
    ("M46", "inventory: Swing's id is not the served uuid or PROPOSED",
     (("inv:Swing", "| PROPOSED (G-1)                         | Swing ", "| `15000000-0000-4000-8000-000000000207` | Swing "),)),
    ("M47", "inventory: 1×1's accessible name differs from the tool's",
     (("inv:1×1", "One by one: one chart, one panel", "One by one: one chart, a panel"),)),
    ("M48", "frames: section 0 names 47 frames, the state inventory 48; they differ",
     (("line:| 03  ", ", `SCR-022/thumbnails-smallest`", ""),)),
    ("M49", "events: workspace.switched is missing from the observability table",
     (("line:| `workspace.switched {from, to, dirty}`", "| `workspace.switched {from, to, dirty}`", "| `workspace_switched {from, to, dirty}`"),)),
    ("M50", "events: workspace.switched carries a name",
     (("line:| `workspace.switched {from, to, dirty}`", "{from, to, dirty}`", "{from, to, name, dirty}`"),)),
    ("M51", "keys: copy deck `rail.new_workspace` draws Ctrl+Shift+N without PROPOSED after it",
     (("line:| `rail.new_workspace`", "\"New workspace…\"", "\"New workspace…\" `Ctrl+Shift+N`"),)),
    ("M52", "validity: frame SCR-022/save-as-invalid is not classed by its validity look",
     (("frame:SCR-022/save-as-invalid", "| validity look (not T2) ", "| T1 "),)),
    ("M53", "over-conversion: frame SCR-022/gallery-loading is not classed as a status",
     (("frame:SCR-022/gallery-loading", "| status ", "| T1 "),)),
    ("M54", "over-conversion: frame SCR-022/rename-clash is not classed as an outcome",
     (("frame:SCR-022/rename-clash", "| outcome ", "| T1 "),)),
    ("M55", "carrier: frame SCR-022/gallery-zoom200 lacks the one sticky row",
     (("frame:SCR-022/gallery-zoom200", "the footer is one sticky row:", "the footer is one row:"),)),
    ("M56", "carrier: frame SCR-022/apply-clean lacks the announcement",
     (("frame:SCR-022/apply-clean", "\"Layout changed to Order-flow, 4 panels.\"", "\"Layout changed to Order-flow, four panels.\""), ("frame:SCR-022/apply-clean", "\"Layout changed to Order-flow, 4 panels.\"", "\"Layout changed to Order-flow, four panels.\""),)),
    ("M57", "number: frame CMP-217/menu-twelve draws 24 layouts",
     (("frame:CMP-217/menu-twelve", "from 22 layouts at compact", "from 24 layouts at compact"),)),
    ("M58", "t2-anatomy: frame SCR-011/menu-view-as lacks the banner node",
     (("frame:SCR-011/menu-view-as", "the banner's `rbac.view_as` node", "the `rbac.view_as` node"),)),
    ("M59", "t2-anatomy: frame SCR-022/apply-dirty-viewer lacks CMP-079",
     (("frame:SCR-022/apply-dirty-viewer", "`aria-disabled`, CMP-079 and the reason", "`aria-disabled` and the reason"),)),
    ("M60", "t2-anatomy: frame SCR-011/limit lacks the full label",
     (("frame:SCR-011/limit", "the `lock` glyph, the full label, `aria-disabled`, `disabledReason` → `workspace.limit.count`", "the `lock` glyph, `aria-disabled`, `disabledReason` → `workspace.limit.count`"),)),
    # the pre-PR design-review lens round 1 (F-1, F-2, F-5, F-10): independent wordings the keyword gates missed
    ("M61", "inventory: Scalping's accessible name lacks its arrangement words",
     (("inv:Scalping", "Scalping: one large chart beside the DOM ladder and tape, stacked,", "Scalping: the chart, the DOM ladder and tape, stacked,"),)),
    ("M62", "carrier: frame SCR-022/gallery-zoom200 lacks the one scroll container",
     (("frame:SCR-022/gallery-zoom200", "the body is the one scroll container", "the body scrolls"),)),
    ("M63", "t2-anatomy: frame SCR-022/your-layouts-viewer draws a CTA in the sentence form ('CTA')",
     (("frame:SCR-022/your-layouts-viewer", "with no CTA and no button", "with the CTA [Save as new layout…], no button"),)),
    ("M64", "lock: frame SCR-022/apply-dirty-viewer locks Discard changes ('lock')",
     (("frame:SCR-022/apply-dirty-viewer", "Discard changes stays T1 and applies", "Discard changes takes the lock and applies"),)),
    ("M65", "availability: frame CMP-217/menu-viewer draws a lock on an availability state ('lock glyph')",
     (("frame:CMP-217/menu-viewer", "Revert to saved… in the availability look", "Revert to saved… with the lock glyph in the availability look"),)),
    ("M66", "delete: the context menu frame offers a one-click workspace delete ('deletes at once')",
     (("frame:SCR-011/context-menu", "Delete… opens SCR-025's typed confirm — never one-click", "Delete… deletes at once — never one-click"),)),
    ("M67", "number: frame SCR-022/gallery-1280 draws 163 px",
     (("frame:SCR-022/gallery-1280", "161 px cards", "163 px cards"),)),
    ("M68", "number: frame CMP-217/menu-twelve draws 420 px",
     (("frame:CMP-217/menu-twelve", "410 px tall", "420 px tall"),)),
    ("M69", "exits: frame CMP-217/menu-view-as gates an exit in its Exits cell",
     (("frame:CMP-217/menu-view-as", "| `Esc` closes the menu; T1 ", "| `Esc` closes the menu; T2 while viewing as "),)),
    ("M70", "spine: frame SCR-022/key-picker does not name its noun (saved layout)",
     (("frame:SCR-022/key-picker", "| manages a saved layout ", "| picks an arrangement "),)),
    # RULED M-2: the switcher's load error is merged E15-D03's "Couldn't load workspaces." with [Try again] on
    # each carrier (one mutation per carrier, one per forbidden form; the gallery's [Retry] stays valid)
    ("M71", "load-error: frame SCR-011/error lacks E15-D03's \"Couldn't load workspaces.\"",
     (("frame:SCR-011/error", "| \"Couldn't load workspaces.\" with [Try again]", "| an error line with [Try again]"),)),
    ("M72", "load-error: frame SCR-011/error's announcement lacks E15-D03's \"Couldn't load workspaces.\"",
     (("frame:SCR-011/error", "| \"Couldn't load workspaces.\" polite once", "| the error line polite once"),)),
    ("M73", "load-error: frame SCR-011/error words the switcher's load error otherwise ('failed to load')",
     (("frame:SCR-011/error", "\"Couldn't load workspaces.\" with [Try again]", "\"Workspaces failed to load.\" with [Try again]"),)),
    ("M74", "load-error: copy deck `rail.error` words the switcher's load error otherwise ('didn't load')",
     (("line:| `rail.error`", "\"Couldn't load workspaces.\"", "\"Workspaces didn't load.\""),)),
    ("M75", "load-error: copy deck `rail.error` names the switcher's action 'Retry'",
     (("line:| `rail.error`", "· \"Try again\"", "· \"Retry\""),)),
    ("M76", "load-error: AN-7's string words the switcher's load error otherwise ('Could not load')",
     (("line:| AN-7 ", "/ \"Couldn't load workspaces.\"", "/ \"Could not load the workspaces.\""),)),
    ("M77", "load-error: §10.2's error sentence names the switcher's action 'Retry'",
     (("line:**Create** = the", "with [Try again] (the `503`)", "with [Retry] (the `503`)"),)),
    ("M78", "load-error: §10.2's error sentence lacks E15-D03's \"Couldn't load workspaces.\"",
     (("line:**Create** = the", "\"Couldn't load workspaces.\" with [Try again] (the", "an error line with [Try again] (the"),)),
)
# The orchestrator's text round 1 (#321 comment 6396465673): its 95 independent A2 mutations, batches 1-3,
# one row per form; 52 of them passed the keyword-keyed gates of the first commit. Each trips its own FAIL alone.
RECORD_MUTATIONS: tuple[tuple[str, str, tuple[Edit, ...]], ...] = (
    ("R01", "spine: frame SCR-022/presets-listbox puts a hotkey on a preset card ('`Ctrl+1` on the Scalping card')",
     (("frame:SCR-022/presets-listbox", "the selected card ringed and checked;", "the selected card ringed and checked; `Ctrl+1` on the Scalping card;"),)),
    ("R02", "spine: frame SCR-022/gallery-1920 puts a hotkey on a preset card ('the Scalping card carries the key chip Ctrl+1')",
     (("frame:SCR-022/gallery-1920", "no card carries a key chip", "the Scalping card carries the key chip Ctrl+1"),)),
    ("R03", "spine: frame SCR-022/gallery-1920 does not name its noun (arrangement)",
     (("frame:SCR-022/gallery-1920", "| picks an arrangement ", "| picks a saved workspace "),)),
    ("R04", "spine: frame SCR-011/expanded does not name its noun (saved workspace)",
     (("frame:SCR-011/expanded", "| picks a saved workspace ", "| picks an arrangement "),)),
    ("R05", "spine: frame CMP-217/menu-default does not name its noun (saved layout)",
     (("frame:CMP-217/menu-default", "| switches a saved layout ", "| picks an arrangement "),)),
    ("R06", "carrier: frame SCR-011/switch-dirty lacks the dirty marker in the row name",
     (("frame:SCR-011/switch-dirty", " is dirty (\"unsaved changes\" in the name) and", " is dirty and"),)),
    ("R07", "carrier: frame SCR-011/expanded lacks the dirty marker in the row name",
     (("frame:SCR-011/expanded", "dirty: \"unsaved changes\" in the name", "dirty"),)),
    ("R08", "carrier: frame SCR-011/light-rail lacks the dirty marker in the row name",
     (("frame:SCR-011/light-rail", "the dirty marker \\* with \"unsaved changes\" in the name", "the dirty marker \\*"),)),
    ("R09", "switch: frame SCR-011/switch-dirty prompts on a switch ('dialog')",
     (("frame:SCR-011/switch-dirty", "at once with no prompt (D-9)", "after a dialog opens (D-9)"),)),
    ("R10", "carrier: frame SCR-022/gallery-text-125 lacks the arrangement-only sentence",
     (("frame:SCR-022/gallery-text-125", ", \"Applying a preset changes the arrangement only — never the selected account or environment.\"", ""),)),
    ("R11", "carrier: frame SCR-022/gallery-zoom200 lacks the arrangement-only sentence",
     (("frame:SCR-022/gallery-zoom200", " and \"Applying a preset changes the arrangement only — never the selected account or environment.\"", ""),)),
    ("R12", "carrier: frame SCR-022/gallery-loading lacks the arrangement-only sentence",
     (("frame:SCR-022/gallery-loading", "changes the arrangement only — never the selected account or environment.", "changes the arrangement and keeps the account."),)),
    ("R13", "t2-anatomy: frame CMP-217/menu-view-as lacks the lock glyph",
     (("frame:CMP-217/menu-view-as", "T2 with the `lock` glyph, the full label", "T2 with the full label"),)),
    ("R14", "t2-anatomy: frame CMP-217/menu-saves-t2 lacks the lock glyph",
     (("frame:CMP-217/menu-saves-t2", "the `lock` glyph leads it, `aria-disabled`", "`aria-disabled`"),)),
    ("R15", "t2-anatomy: frame SCR-022/apply-dirty-viewer lacks the lock glyph",
     (("frame:SCR-022/apply-dirty-viewer", "with the `lock` glyph before its full label", "with its full label"),)),
    ("R16", "t2-anatomy: frame CMP-217/menu-limit lacks the lock glyph",
     (("frame:CMP-217/menu-limit", "T2 with the `lock` glyph, the full label", "T2 with the full label"),)),
    ("R17", "t2-anatomy: frame SCR-011/menu-view-as uses the `disabled` attribute",
     (("frame:SCR-011/menu-view-as", "the full label, `aria-disabled`, CMP-079", "the full label, the `disabled` attribute, CMP-079"),)),
    ("R18", "lock: frame SCR-022/gallery-1920 locks Apply ('locked')",
     (("frame:SCR-022/gallery-1920", "[Apply] [Cancel]", "[Apply] (locked) [Cancel]"),)),
    ("R19", "lock: frame CMP-217/menu-default locks Browse presets… ('aria-disabled')",
     (("frame:CMP-217/menu-default", "Browse presets… (last, AD-2)", "Browse presets… `aria-disabled` (last, AD-2)"),)),
    ("R20", "lock: frame SCR-011/context-menu locks Open ('locked')",
     (("frame:SCR-011/context-menu", ": Open, Rename…", ": Open (locked), Rename…"),)),
    ("R21", "lock: frame SCR-011/rename-inplace locks Rename… ('locked')",
     (("frame:SCR-011/rename-inplace", "Rename… turned", "Rename… (locked) turned"),)),
    ("R22", "exits: frame SCR-022/gallery-1280 gates an exit in its Exits cell ('lock')",
     (("frame:SCR-022/gallery-1280", "focus returns to `[Layout ▾]`; T1", "focus returns to `[Layout ▾]`; Close is locked; T1"),)),
    ("R23", "exits: frame SCR-022/apply-dirty gates an exit in its Exits cell ('lock')",
     (("frame:SCR-022/apply-dirty", "with nothing applied; T1", "with nothing applied; Back to gallery is locked; T1"),)),
    ("R24", "exits: frame SCR-011/menu-view-as gates an exit in its Exits cell ('lock')",
     (("frame:SCR-011/menu-view-as", "| `Esc` closes the menu; T1", "| `Esc` closes the menu (locked while viewing as); T1"),)),
    ("R25", "keys: frame SCR-011/context-menu draws Ctrl+R without PROPOSED after it",
     (("frame:SCR-011/context-menu", "Rename…, Duplicate", "Rename… `Ctrl+R`, Duplicate"),)),
    ("R26", "keys: key row Next or previous workspace draws Ctrl+PageDown without PROPOSED after it",
     (("line:| Next or previous workspace", "none yet;", "`Ctrl+PageDown`;"),)),
    ("R27", "keys: frame SCR-022/gallery-1280 draws Alt+Enter without PROPOSED after it",
     (("frame:SCR-022/gallery-1280", "[Apply] [Cancel]", "[Apply `Alt+Enter`] [Cancel]"),)),
    ("R28", "marker: audit:cols=4 but --json prints 5",
     (("line:<!-- audit:cols=5", "audit:cols=5", "audit:cols=4"),)),
    ("R29", "number: listbox visible: the spec says 310, the tool 300",
     (("line:One `role=", "the listbox keeps 300 px", "the listbox keeps 310 px"),)),
    ("R30", "number: rail fit: the spec says 17, the tool 18",
     (("line:The expanded rail is", "18 workspace rows fit", "17 workspace rows fit"),)),
    ("R31", "number: pairs: the spec says 51, the tool 52",
     (("line:**Pairwise check", "52 told apart", "51 told apart"),)),
    ("R32", "number: frame CMP-217/menu-twelve draws 411 px, not a value the tool derives for it",
     (("frame:CMP-217/menu-twelve", "410 px tall", "411 px tall"),)),
    ("R33", "number: frame SCR-022/gallery-zoom200 draws 170 px, not a value the tool derives for it",
     (("frame:SCR-022/gallery-zoom200", "the 160 px between", "the 170 px between"),)),
    ("R34", "matrix: the §13 row 'selected card ring on the dialog: `color.border.' differs from the tool's",
     (("line:| selected card ring on the dialog", "| 4.52 (grey 4.08)", "| 4.53 (grey 4.08)"),)),
    ("R35", "catalogue: the SCR-022 Type line is not in `14`",
     (("cat:- **Type:** Modal. Presets: Scalping", "- **Type:**", "- **Kind:**"),)),
    ("R36", "t2: the one T2 rule is not stated exactly once",
     (("spec:", "**The rule, once.**", "**The rule, once.** The rule, once."),)),
    ("R37", "frames: the state inventory lists SCR-011/limit twice",
     (("frame:SCR-011/limit", "| `SCR-011/limit` ", "| `SCR-011/limit`                 | 08    | 32 workspaces: New workspace T2 under the rail's button — the `lock` glyph, the full label, `aria-disabled`, `disabledReason` → `workspace.limit.count` \"You have the most workspaces you can have.\"; Duplicate takes the same key in the row menu                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | T2                                   | picks a saved workspace | the reason once, politely                                               | `Esc` does nothing; T1                                                                                                                                                                                                                                                       |\n| `SCR-011/limit` "),)),
    ("R38", "spine: frame SCR-022/presets-listbox puts a hotkey on a preset card ('`ctrl+1` on the Scalping card')",
     (("frame:SCR-022/presets-listbox", "the selected card ringed and checked;", "the selected card ringed and checked; `ctrl+1` on the Scalping card;"),)),
    ("R39", "spine: frame SCR-022/light-gallery puts a hotkey on a preset card ('`ctrl+1` on the Scalping card')",
     (("frame:SCR-022/light-gallery", "no card carries a key chip", "`ctrl+1` on the Scalping card"),)),
    ("R40", "spine: frame SCR-022/presets-listbox puts a hotkey on a preset card ('each card = thumbnail, name, contents in words, the panel co')",
     (("frame:SCR-022/presets-listbox", "the note where a panel cannot be stored;", "the note where a panel cannot be stored, its hotkey 1 shown at the corner;"),)),
    ("R41", "spine: frame SCR-022/gallery-1920 puts a hotkey on a preset card ('each card carries its key chip')",
     (("frame:SCR-022/gallery-1920", "no card carries a key chip", "each card carries its key chip"),)),
    ("R42", "spine: frame SCR-022/thumbnails puts a hotkey on a preset card ('the eleven thumbnails at 145×87 with the glyph key and each ')",
     (("frame:SCR-022/thumbnails", "with the glyph key;", "with the glyph key and each preset's hotkey 1..9 chip;"),)),
    ("R43", "spine: §5.2 puts a hotkey on a preset card ('Each card carries a hotkey chip `Ctrl+1..9` (AD-2 / AD-11, §')",
     (("line:One `role=", "No card carries a hotkey chip — presets have no keys", "Each card carries a hotkey chip `Ctrl+1..9`"),)),
    ("R44", "spine: frame SCR-022/gallery-1280 names a saved workspace outside its Spine cell ('the 920×620 dialog inside the 1168×672 canvas, same anatomy ')",
     (("frame:SCR-022/gallery-1280", "same anatomy at 161 px cards;", "same anatomy at 161 px cards, the gallery here picks a saved workspace;"),)),
    ("R45", "spine: frame SCR-011/expanded names a arrangement outside its Spine cell ('each workspace row is an arrangement')",
     (("frame:SCR-011/expanded", "no row carries a layout key", "no row carries a layout key; each workspace row is an arrangement"),)),
    ("R46", "spine: frame SCR-022/gallery-1920's Spine cell is not the bare 'picks an arrangement' ('picks an arrangement or a saved workspace')",
     (("frame:SCR-022/gallery-1920", "| picks an arrangement ", "| picks an arrangement or a saved workspace "),)),
    ("R47", "spine: frame SCR-022/presets-listbox names a saved workspace outside its Spine cell ('each card = a saved workspace, thumbnail, name, contents in ')",
     (("frame:SCR-022/presets-listbox", "each card = thumbnail", "each card = a saved workspace, thumbnail"),)),
    ("R48", "dirty: frame SCR-011/dirty moves the dirty marker out of the row name ('tab strip only')",
     (("frame:SCR-011/dirty", "the dirty marker in the row name", "the dirty marker on the tab strip only, not in the row name"),)),
    ("R49", "switch: frame SCR-011/switch-dirty prompts on a switch ('toast')",
     (("frame:SCR-011/switch-dirty", "; no SCR-029 ", "; no SCR-029; a toast \"Save first?\" asks before the switch "),)),
    ("R50", "switch: frame SCR-011/switch-dirty prompts on a switch ('confirm')",
     (("frame:SCR-011/switch-dirty", "; no SCR-029 ", "; no SCR-029; a confirm dialog asks to save first "),)),
    ("R51", "switch: frame SCR-011/switch-dirty prompts on a switch ('Save first')",
     (("frame:SCR-011/switch-dirty", "with no prompt (D-9)", "with no prompt (D-9) once the user answers the \"Save first?\" dialog"),)),
    ("R52", "switch: frame SCR-011/search prompts on a switch ('Save first')",
     (("frame:SCR-011/search", "`Enter` opens the first match", "`Enter` opens the first match after a \"Save first?\" prompt when dirty"),)),
    ("R53", "switch: §10.3 prompts on a switch ('Save first')",
     (("line:Selecting another workspace", "**switches at once and never prompts**", "**opens a \"Save first?\" dialog, then switches**"),)),
    ("R54", "lock: frame SCR-022/gallery-1920 locks Apply ('inert')",
     (("frame:SCR-022/gallery-1920", "[Apply] [Cancel]", "[Apply] (inert) [Cancel]"),)),
    ("R55", "lock: frame SCR-022/gallery-1920 locks Apply ('can't be pressed')",
     (("frame:SCR-022/gallery-1920", "[Apply] [Cancel]", "[Apply] [Cancel]; Apply can't be pressed"),)),
    ("R56", "lock: frame SCR-022/gallery-1280 locks Apply ('Locked')",
     (("frame:SCR-022/gallery-1280", "[Apply] [Cancel]", "[Apply] (Locked) [Cancel]"),)),
    ("R57", "lock: frame SCR-022/your-layouts-view-as locks Apply ('inert')",
     (("frame:SCR-022/your-layouts-view-as", "Apply stays T1", "Apply is inert"),)),
    ("R58", "lock: frame CMP-217/menu-default locks Browse presets… ('inert')",
     (("frame:CMP-217/menu-default", "Browse presets… (last, AD-2)", "Browse presets… inert (last, AD-2)"),)),
    ("R59", "lock: frame CMP-217/menu-view-as locks Browse presets… ('inert')",
     (("frame:CMP-217/menu-view-as", "and Browse presets… stay T1", "stay T1; Browse presets… is inert"),)),
    ("R60", "lock: frame SCR-011/context-menu locks Rename… ('can't be pressed')",
     (("frame:SCR-011/context-menu", ": Open, Rename…,", ": Open, Rename… (can't be pressed),"),)),
    ("R61", "lock: frame SCR-022/your-layouts-twelve locks Rename ('locked')",
     (("frame:SCR-022/your-layouts-twelve", "every row keeps Rename,", "every row keeps Rename (locked),"),)),
    ("R62", "lock: frame SCR-011/expanded locks switching ('locked')",
     (("frame:SCR-011/expanded", "no row carries a layout key", "no row carries a layout key; switching to another workspace is locked"),)),
    ("R63", "lock: frame SCR-011/switch-dirty locks switch ('locked')",
     (("frame:SCR-011/switch-dirty", "; no SCR-029 ", "; no SCR-029; under view-as the switch is locked "),)),
    ("R64", "lock: frame CMP-217/menu-default locks switching ('locked')",
     (("frame:CMP-217/menu-default", "\"Layout changed to Order-flow, 4 panels.\" on a switch", "\"Layout changed to Order-flow, 4 panels.\" on a switch; switching is locked while viewing as"),)),
    ("R65", "lock: frame SCR-022/apply-dirty-viewer locks Discard changes ('inert')",
     (("frame:SCR-022/apply-dirty-viewer", "Discard changes stays T1 and applies", "Discard changes is inert and applies"),)),
    ("R66", "exits: frame SCR-022/gallery-1920 gates an exit in its Exits cell ('inert')",
     (("frame:SCR-022/gallery-1920", "| `Esc` and Cancel close the dialog", "| `Esc` is inert, Cancel closes the dialog"),)),
    ("R67", "exits: frame CMP-217/menu-view-as gates an exit in its Exits cell ('inert')",
     (("frame:CMP-217/menu-view-as", "| `Esc` closes the menu; T1", "| `Esc` is inert while viewing as; T1"),)),
    ("R68", "exits: frame SCR-022/gallery-1280 gates an exit in its Exits cell ('can't be pressed')",
     (("frame:SCR-022/gallery-1280", "| `Esc` and Cancel close the dialog", "| `Esc` closes the dialog and Cancel can't be pressed"),)),
    ("R69", "keys: frame SCR-011/rename-inplace draws F2, a key with no row in this context (RULED Q-22)",
     (("frame:SCR-011/rename-inplace", "Rename… turned", "Rename… or `F2` as shipped turned"),)),
    ("R70", "keys: frame SCR-011/context-menu draws F2, a key with no row in this context (RULED Q-22)",
     (("frame:SCR-011/context-menu", "Rename…, Duplicate", "Rename… `F2`, Duplicate"),)),
    ("R71", "keys: key row Rename-in-place draws F2, a key with no row in this context (RULED Q-22)",
     (("line:| Rename-in-place                | `Enter`", "`Enter` (save), `Esc` (revert)", "`Enter` (save), `Esc` (revert), `F2` (existing)"),)),
    ("R72", "keys: frame SCR-011/rename-inplace draws ctrl+r without PROPOSED after it",
     (("frame:SCR-011/rename-inplace", "Rename… turned", "Rename… `ctrl+r` turned"),)),
    ("R73", "keys: §7 prose draws Ctrl+L without PROPOSED after it",
     (("line:**The trigger**", "(`aria-haspopup=\"menu\"`)", "(`aria-haspopup=\"menu\"`; `Ctrl+L` opens it)"),)),
    ("R74", "scope: frame SCR-022/gallery-1920 draws an account or environment control ('Account')",
     (("frame:SCR-022/gallery-1920", "[Apply] [Cancel]", "[Account ▾] [Apply] [Cancel]"),)),
    ("R75", "scope: frame SCR-022/gallery-1280 draws an account or environment control ('account')",
     (("frame:SCR-022/gallery-1280", "[Apply] [Cancel]", "an account picker beside [Apply] [Cancel]"),)),
    ("R76", "scope: frame SCR-011/expanded draws an account or environment control ('environment')",
     (("frame:SCR-011/expanded", "the \"+\" New workspace row;", "the \"+\" New workspace row; the environment switch [DEMO ▾];"),)),
    ("R77", "scope: frame SCR-011/context-menu draws an account or environment control ('account')",
     (("frame:SCR-011/context-menu", "Export…, Delete…", "Export…, Switch account…, Delete…"),)),
    ("R78", "number: frame SCR-022/your-layouts-twelve draws 6 rows, not a value the tool derives for it",
     (("frame:SCR-022/your-layouts-twelve", "the section shows 5 rows", "the section shows 6 rows"),)),
    ("R79", "number: frame SCR-011/search draws 17 that fit, not a value the tool derives for it",
     (("frame:SCR-011/search", "above the 18 that fit", "above the 17 that fit"),)),
    ("R80", "number: reach: the spec says 24, the tool 23",
     (("line:**The >9 rule", "at the cap, 23 layouts", "at the cap, 24 layouts"),)),
    ("R81", "number: text 125: the spec says 298, the tool 296",
     (("line:**Loading**", "grow to 296 px", "grow to 298 px"),)),
    ("R82", "number: rail fit others: the spec says 31, the tool 30",
     (("line:The expanded rail is", "30 and 20 with it", "31 and 20 with it"),)),
    ("R83", "number: tokens §1.1: the spec table says 39, the tool 40",
     (("line:| `packages/ui/tokens`", "40 bound tokens", "39 bound tokens"),)),
    ("R84", "number: counts §21: the spec says 3, the tool 4",
     (("line:9. Contrast:", "(4 existing keymap rows", "(3 existing keymap rows"),)),
    ("R85", "siblings: the spec pins or quotes E15-D07 ('E15-D07 at `abc1234f')",
     (("line:| The focused row's context menu", "the panel menu (E15-D07)", "the panel menu (E15-D07 at `abc1234f`)"),)),
    ("R86", "siblings: the spec pins or quotes E15-D07 ('E15-D07 :212')",
     (("line:**Hand-offs:**", "E15-D07 — `Shift+F10`", "E15-D07 :212 — `Shift+F10`"),)),
    ("R87", "siblings: the spec pins or quotes E15-D07 ('E15-D07 (#361) says \"the picker rows are ours\"')",
     (("line:| E15-D07 (#361)", "| E15-D07 (#361), E15-D13", "| E15-D07 (#361) says \"the picker rows are ours\", E15-D13"),)),
    ("R88", "catalogue: the SCR-022 hi-fi pointer appears 2 times in `14`",
     (("cat:- **Design (wireframe → hi-fi):** [E15-D05.md](../design/E15/E15-D05.md) §5–§9 (E15-D05; PROPOSED, owner approval pending:", "- **Design (wireframe", "- **Design (wireframe → hi-fi):** [E15-D05.md](../design/E15/E15-D05.md) §5–§9 (E15-D05; PROPOSED, owner approval pending: the gallery and thumbnails in colour, the reconciled inventory, Your layouts with rename / key / delete, the SCR-029 route, CMP-217's menu; Penpot page `E15-D05 Presets and switcher`, boards pending).\n- **Design (wireframe"),)),
    ("R89", "number: pairs: the spec says 4, the tool 3",
     (("line:**Pairwise check", "and 3 by glyphs", "and 4 by glyphs"),)),
    ("R90", "view-as: frame CMP-217/menu-view-as does not put the view-as leg first",
     (("frame:CMP-217/menu-view-as", "the banner's `rbac.view_as` node", "`rbac.permission` then the banner's `rbac.view_as` node"),)),
    ("R91", "lock: frame SCR-022/gallery-zoom200 locks Keep current symbols ('locked')",
     (("frame:SCR-022/gallery-zoom200", "[x] Keep current symbols (on) [Apply]", "[x] Keep current symbols (on) (locked) [Apply]"),)),
    ("R92", "t2-anatomy: frame SCR-011/menu-view-as lacks the full label",
     (("frame:SCR-011/menu-view-as", "the `lock` glyph, the full label, `aria-disabled`", "the `lock` glyph, `aria-disabled`"),)),
    ("R93", "carrier: frame SCR-022/light-gallery lacks the arrangement-only sentence",
     (("frame:SCR-022/light-gallery", "changes the arrangement only — never the selected account or environment.", "changes the arrangement."),)),
    ("R94", "dirty: frame SCR-011/light-rail moves the dirty marker out of the row name ('tooltip only')",
     (("frame:SCR-011/light-rail", "the dirty marker \\* with \"unsaved changes\" in the name", "the dirty marker \\* with \"unsaved changes\" in the tooltip only"),)),
    ("R95", "switch: §10.3 prompts on a switch ('toast')",
     (("line:Selecting another workspace", "**switches at once and never prompts**", "**switches once a toast confirms it**"),)),
)
# fmt: on

# Delta fold (the orchestrator's re-check of text round 1): one mutation per carrier the record listed, each
# FAIL alone — the whole-document clause gates, the dirty row-name cell, the hand-off's numbers, merged E15-D08,
# the load error on its three new carriers, C-16 / OQ-6 and the `22` cite.
# fmt: off
DELTA_MUTATIONS: tuple[tuple[str, str, tuple[Edit, ...]], ...] = (
    ("D01", "trigger: §7 prose draws a key chip inline on the trigger ('key chip'; merged E15-D03 D-9)",
     (("line:**The trigger** (", "and never carries a key chip inline", "and carries a key chip inline"),)),
    ("D02", "trigger: §3.1 row 'D-7' draws a key chip inline on the trigger ('key chip'; merged E15-D03 D-9)",
     (("line:| D-7 ", "never a key chip inline (merged E15-D03 D-9: CMP-022", "with a key chip inline (merged E15-D03 D-9: CMP-022"),)),
    ("D03", "trigger: §0 row '06 `cmp-217-layout-menu' draws a key chip inline on the trigger ('key chip'; merged E15-D03 D-9)",
     (("line:| 06 ", "no inline key chip — merged E15-D03 D-9", "an inline key chip — merged E15-D03 D-9"),)),
    ("D04", "trigger: hand-off Table 1 row 'CMP-217 trigger' draws a key chip inline on the trigger ('key chip'; merged E15-D03 D-9)",
     (("hand:| CMP-217   | trigger ", "no inline key chip: merged E15-D03 D-9", "an inline key chip: merged E15-D03 D-9"),)),
    ("D05", "trigger: hand-off Table 3 row 'CMP-217 the trigger' draws a key chip inline on the trigger ('key chip'; merged E15-D03 D-9)",
     (("hand:| CMP-217   | the trigger ", "`aria-haspopup=\"menu\"`, `aria-expanded`", "`aria-haspopup=\"menu\"`, `aria-expanded`; a key chip inline"),)),
    ("D06", "dirty: frame SCR-011/dirty draws the dirty marker outside its row name (the State drawn cell)",
     (("frame:SCR-011/dirty", "Scalping \\* — the dirty marker in the row name, \"Scalping, unsaved changes\" as the accessible name; \"Scalping · Restored \\*\"", "Scalping — the plain row name; \"Scalping · Restored\""), ("frame:SCR-011/dirty", "| none ", "| the dirty marker \\* and \"unsaved changes\" in a notice "),)),
    ("D07", "spine: hand-off Table 1 row 'CMP-217 gallery (SCR-022)' puts a hotkey on a preset card ('Hotkey: 1')",
     (("hand:| CMP-217   | gallery (SCR-022) ", "one listbox in one order (RULED Q-8)", "Hotkey: 1"),)),
    ("D08", "spine: hand-off Table 3 row 'CMP-217 the Presets listbox' puts a hotkey on a preset card ('a `Ctrl+1` chip on each option')",
     (("hand:| CMP-217   | the Presets listbox ", "`aria-selected`; `aria-activedescendant`", "`aria-selected`; a `Ctrl+1` chip on each option; `aria-activedescendant`"),)),
    ("D09", "spine: §6.1 row '1 PROPOSED (G-1)' puts a hotkey on a preset card ('hotkey Ctrl+1')",
     (("inv:Scalping", "`chart`, `dom`, `tape`; one symbol", "`chart`, `dom`, `tape`; hotkey Ctrl+1; one symbol"),)),
    ("D10", "switch: frame SCR-011/switch-dirty prompts on a switch ('sheet')",
     (("frame:SCR-011/switch-dirty", "; no SCR-029 ", "; no SCR-029; a sheet titled \"Keep your changes?\" "),)),
    ("D11", "switch: frame SCR-011/switch-dirty prompts on a switch ('waits')",
     (("frame:SCR-011/switch-dirty", "; no SCR-029 ", "; no SCR-029; the switch waits for the user "),)),
    ("D12", "keys: hand-off Table 2 row 'CMP-073 `F2`, `Enter` / `Esc' draws F2, a key with no row in this context (RULED Q-22)",
     (("hand:| CMP-073   | `Enter` / `Esc` in the rename input", "| CMP-073   | `Enter` / `Esc` in the rename input", "| CMP-073   | `F2`, `Enter` / `Esc` in the rename input"),)),
    ("D13", "switch: hand-off Table 2 row 'CMP-217 `Ctrl+1..9' prompts on a switch ('Save first')",
     (("hand:| CMP-217   | `Ctrl+1..9` ", "switch to the layout holding that slot; no prompt", "switch to the layout holding that slot; a \"Save first?\" prompt"),)),
    ("D14", "scope: hand-off Table 3 row 'CMP-217 Keep current symbols' draws an account or environment control ('account picker')",
     (("hand:| CMP-217   | Keep current symbols ", "checked by default", "checked by default; an account picker beside it"),)),
    ("D15", "spine: hand-off Table 3 row 'CMP-217 the Presets listbox' calls a preset a saved workspace ('option a saved workspace')",
     (("hand:| CMP-217   | the Presets listbox ", "\"Presets\"; the §6.1 names", "\"Presets\", each option a saved workspace; the §6.1 names"),)),
    ("D16", "lock: hand-off §B line locks Apply ('locked')",
     (("hand:    When the user opens the gallery", "from \"Browse presets…\"", "from \"Browse presets…\" and Apply is locked"),)),
    ("D17", "lock: §5.3 prose locks Apply ('locked')",
     (("line:Row 1: ", "with [Apply] (CMP-001 `primary`)", "with [Apply] (CMP-001 `primary`, locked)"),)),
    ("D18", "lock: §9 prose locks Discard changes ('locked')",
     (("line:**Dirty** (`SCR-022/apply-dirty`", "Discard changes applies over the copy", "Discard changes is locked and applies over the copy"),)),
    ("D19", "lock: §10.2 prose locks Open ('locked')",
     (("line:**Create** = ", "Open, Rename…, Duplicate, Set as default, Move up, Move down, Export…, Delete… — Delete…", "Open (locked), Rename…, Duplicate, Set as default, Move up, Move down, Export…, Delete… — Delete…"),)),
    ("D20", "lock: §11.1 row 'Cancel, close, revert' locks Cancel ('locked')",
     (("line:| Cancel, close, revert ", "| the gallery, the menus, the picker", "| Cancel is locked under view-as; the gallery, the menus, the picker"),)),
    ("D21", "scope: §5.1 prose draws an account or environment control ('[Account ▾]')",
     (("line:The gallery is a CMP-043", "Title \"Layouts\" (`type.ui.heading-sm`)", "Title \"Layouts\" (`type.ui.heading-sm`) with `[Account ▾]` beside it"),)),
    ("D22", "scope: §5.3 prose draws an account or environment control ('Env: d')",
     (("line:Row 1: ", "row 3: the arrangement-only sentence", "row 3: Env: demo beside the arrangement-only sentence"),)),
    ("D23", "load-error: board 08's row words the switcher's load error otherwise ('didn't load')",
     (("line:| 08 ", "\"Couldn't load workspaces.\" with [Try again]", "\"Workspaces didn't load.\" with [Try again]"),)),
    ("D24", "load-error: §12's outcomes lacks the action [Try again]",
     (("line:**Not T2", "\"Couldn't load workspaces.\" with [Try again]", "\"Couldn't load workspaces.\" with [Retry]"),)),
    ("D25", "load-error: the hand-off's §A error line names the switcher's action 'Reload'",
     (("hand:- [x] Loading / empty / error", "\"Couldn't load workspaces.\" with [Try again]", "\"Couldn't load workspaces.\" with [Reload]"),)),
    ("D26", "t2: C-16 counts its frames as 'three', the tool four",
     (("line:| C-16 ", "four frames gate those writes", "three frames gate those writes"),)),
    ("D27", "t2: C-16 does not close OQ-6",
     (("line:| C-16 ", "OQ-6 is closed", "OQ-6 stays open"),)),
    ("D28", "t2: OQ-6's row is not closed",
     (("line:| OQ-6 ", "| closed (orchestrator) |", "| orchestrator          |"),)),
    ("D29", "number: handoff density CMP-217 compact: the hand-off table says 243, the tool 242",
     (("hand:| CMP-217   | compact ", "cards 242 / 237", "cards 243 / 237"),)),
    ("D30", "number: handoff menu notes: the hand-off says 321, the tool 320",
     (("hand:- [x] **Density notes** — the menu", "the menu 320 px wide", "the menu 321 px wide"),)),
    ("D31", "number: handoff density CMP-217 compact: the hand-off table says 10, the tool 9",
     (("hand:| CMP-217   | compact ", "separators 9;", "separators 10;"),)),
    ("D32", "number: handoff menu notes: the hand-off says 23, the tool 22",
     (("hand:- [x] **Density notes** — the menu", "from 22 layouts at compact", "from 23 layouts at compact"),)),
    ("D33", "number: handoff menu notes: the hand-off says 411, the tool 410",
     (("hand:- [x] **Density notes** — the menu", "twelve layouts 410 px", "twelve layouts 411 px"),)),
    ("D34", "number: handoff rail notes: the hand-off says 17, the tool 18",
     (("hand:- [x] **Density notes** — the rail", "; 18 workspace rows fit", "; 17 workspace rows fit"),)),
    ("D35", "number: handoff rail notes: the hand-off says 194, the tool 193",
     (("hand:- [x] **Density notes** — the rail", "the name column 193 px", "the name column 194 px"),)),
    ("D36", "number: handoff rail notes: the hand-off says 767, the tool 768",
     (("hand:- [x] **Density notes** — the rail", "stacks to 768 / 1,024 px", "stacks to 767 / 1,024 px"),)),
    ("D37", "number: handoff table 1 overflow: the hand-off table says 21, the tool 22",
     (("hand:| CMP-217   | menu  ", "scrolling from 22 at compact", "scrolling from 21 at compact"),)),
    ("D38", "siblings: the spec calls merged E15-D08 PENDING ('E15-D08 (#362) — the merged SCR-025 / SCR-029 hi')",
     (("line:| E15-D08 (#362)", "| **merged** (`fb1b48041ae0a12638beacae6a61854833c5cc4d`", "| **PENDING** (`fb1b48041ae0a12638beacae6a61854833c5cc4d`"),)),
    ("D39", "siblings: the spec does not cite merged E15-D08 at its merge sha",
     (("line:**Key.**", "as merged (`fb1b48041ae0a12638beacae6a61854833c5cc4d`, PR #4503", "as merged (PR #4503"),)),
    ("D40", "focus: §11.2's SCR-029 Tab order is not merged E15-D08 §6's",
     (("line:| SCR-029 unsaved variant", "Cancel → Discard changes → Save layout", "Cancel → Save layout → Discard changes"),)),
    ("D41", "focus: §11.2's SCR-029 focus return is not merged E15-D08 §6's",
     (("line:| SCR-029 unsaved variant", "after Save layout or Discard changes `[Layout ▾]`", "after Save layout or Discard changes the workspace"),)),
    ("D42", "copy: §8 lacks merged E15-D08 D08-A22's sentence",
     (("line:**Rename** is inline", "\"Delete layout {name}? It has unsaved changes, and it can't be restored.\"", "\"Delete layout {name}? It can't be restored.\""),)),
    ("D43", "cites: `22`'s static-asset sentence is not cited at :12644–:12645",
     (("line:Thumbnails are static SVG in the product", ":12644–:12645", ":12643"),)),
    ("D44", "scope: §5.3 prose draws an account or environment control ('choose the account')",
     (("line:Row 1: ", "row 3: the arrangement-only sentence", "row 3: choose the account beside the arrangement-only sentence"),)),
    ("D45", "scope: §11.1 row 'Cancel, close, revert' draws an account or environment control ('select the environment')",
     (("line:| Cancel, close, revert ", "| the gallery, the menus, the picker", "| select the environment in the gallery, the menus, the picker"),)),
    ("D46", "scope: hand-off Table 3 row 'CMP-217 Keep current symbols' draws an account or environment control ('pick the sub-account')",
     (("hand:| CMP-217   | Keep current symbols ", "checked by default", "checked by default; pick the sub-account beside it"),)),
    ("D47", "scope: hand-off CMP-217 block prose draws an account or environment control ('switch the environment')",
     (("hand:- [x] **Live data** — none streams: the saved", "none streams: the saved layouts", "none streams; switch the environment in the rail; the saved layouts"),)),
    ("D48", "scope: §7 prose draws an account or environment control ('change the accounts')",
     (("line:**The trigger** (", "and never carries a key chip inline", "and never carries a key chip inline; change the accounts from it"),)),
    ("D49", "spine: §5.3 prose puts a hotkey on a preset card ('ctrl+3 applies the Scalping card and [Cancel] (`secondary`) ')",
     (("line:Row 1: ", "with [Apply] (CMP-001 `primary`)", "with [Apply] (CMP-001 `primary`); ctrl+3 applies the Scalping card"),)),
    ("D50", "spine: frame CMP-217/menu-default puts a hotkey on a preset card ('a hotkey on the 2x2 thumbnail): ✓ Layout 1 \\* `Ctrl+1`')",
     (("frame:CMP-217/menu-default", "(CMP-041, 320 px wide)", "(CMP-041, 320 px wide; a hotkey on the 2x2 thumbnail)"),)),
    ("D51", "spine: hand-off Table 2 row 'CMP-217 press ctrl+3 on the ' puts a hotkey on a preset card ('press ctrl+3 on the Scalping card')",
     (("hand:| CMP-217   | `Ctrl+S` / `Ctrl+Shift+S` ", "| `Ctrl+S` / `Ctrl+Shift+S`", "| press ctrl+3 on the Scalping card; `Ctrl+S` / `Ctrl+Shift+S`"),)),
    ("D52", "spine: hand-off CMP-217 block prose puts a hotkey on a preset card ('the Order-flow card carries a key chip')",
     (("hand:- [x] **Essential-exceptions log** — none (every", "(every target reaches 24 px in compact)", "(every target reaches 24 px in compact); the Order-flow card carries a key chip"),)),
    ("D53", "spine: §11.1 row 'Cancel, close, revert' puts a hotkey on a preset card ('a key chip on each preset, rename-in-place (reverts), the co')",
     (("line:| Cancel, close, revert ", "| the gallery, the menus, the picker", "| the gallery, the menus, the picker; a key chip on each preset"),)),
)
# fmt: on

# Re-check fold (the orchestrator's re-check of the delta): the record's probes verbatim (E01–E15) and this
# fold's own variants (E16–E32: other arrangement names, punctuation splits, the hand-off's other tables,
# prose and table, a pronoun carry across sentences), each FAIL alone; the valid twins must stay clean.
# fmt: off
RECHECK_MUTATIONS: tuple[tuple[str, str, tuple[Edit, ...]], ...] = (
    ("E01", "trigger: §3.1 row 'D-7' puts the key on the trigger ('out's name and `*` when dirty, the badge on the trigger show'; merged E15-D03 D-9)",
     (('line:| D-7 ', 'never a key chip inline (merged E15-D03 D-9: CMP-022', 'the badge on the trigger shows the key (merged E15-D03 D-9: CMP-022'),)),
    ("E02", "lock: §5.3 prose locks Apply ('inert')",
     (('line:Row 1: ', 'with [Apply] (CMP-001 `primary`)', 'with [Apply] (CMP-001 `primary`; inert until a card is chosen)'),)),
    ("E03", "lock: §5.3 prose locks Apply ('greyed out')",
     (('line:Row 1: ', 'with [Apply] (CMP-001 `primary`)', 'with [Apply] (CMP-001 `primary` — greyed out)'),)),
    ("E04", "lock: §9 prose locks Discard ('greyed out')",
     (('line:**Dirty** (`SCR-022/apply-dirty`', 'Cancel returns to the gallery with nothing applied.', 'Cancel returns to the gallery with nothing applied. For a viewer, Discard is greyed out.'),)),
    ("E05", "switch: hand-off Table 2 row 'CMP-217 `Ctrl+1..9' prompts in the row or sentence of a switch ('sheet')",
     (('hand:| CMP-217   | `Ctrl+1..9` ', 'defect H-1 (ranges never dispatch)', 'defect H-1 (ranges never dispatch); a confirmation sheet appears'),)),
    ("E06", "switch: hand-off Table 2 row 'CMP-073 arrows, `Enter`, typ' prompts in the row or sentence of a switch ('confirmation')",
     (('hand:| CMP-073   | arrows, `Enter`, type-ahead', '`role="tree"` (D-8)', '`role="tree"` (D-8); a confirmation sheet appears'),)),
    ("E07", "dirty: hand-off Table 1 row 'CMP-073 rail tree' draws the dirty marker away from the row name ('in a notice')",
     (('hand:| CMP-073   | rail tree ', 'the rail host is the tree', 'the dirty marker in a notice outside the row name; the rail host is the tree'),)),
    ("E08", "dirty: hand-off Table 1 row 'CMP-073 rail tree' draws the dirty marker away from the row name ('in a note')",
     (('hand:| CMP-073   | rail tree ', 'the rail host is the tree', 'the dirty asterisk in a note under the row only; the rail host is the tree'),)),
    ("E09", "spine: §4 prose keys an arrangement as a card ('The Two by two arrangement wears a `Ctrl+1` chip.')",
     (('line:**Three nouns, one each', '"Two by two, four panels". A **saved', '"Two by two, four panels". The Two by two arrangement wears a `Ctrl+1` chip. A **saved'),)),
    ("E10", 'number: handoff density CMP-217 compact pads: the hand-off table says 16, the tool 12',
     (('hand:| CMP-217   | compact ', '`space.inset.md` 12', '`space.inset.md` 16'),)),
    ("E11", 'number: handoff density CMP-217 compact pads: the hand-off table says 28, the tool 24',
     (('hand:| CMP-217   | compact ', '`space.dialog.padding` 24;', '`space.dialog.padding` 28;'),)),
    ("E12", 'number: handoff density CMP-217 comfortable pads: the hand-off table says 30, the tool 32',
     (('hand:| CMP-217   | comfortable ', '| 32 × 32 ', '| 30 × 30 '),)),
    ("E13", 'number: handoff density CMP-217 compact pads: the hand-off table says 20, the tool 24',
     (('hand:| CMP-217   | compact ', '24 × 24 (the key picker', '20 × 20 (the key picker'),)),
    ("E14", 'number: handoff key picker target: the hand-off says 22, the tool 24',
     (('hand:- [x] **Density notes** — the menu', 'the 24 × 24 key picker', 'the 22 × 22 key picker'),)),
    ("E15", 'number: handoff table 5 search: the hand-off table says 400, the tool 500',
     (('hand:| CMP-073   | the search results count', '(500 ms)', '(400 ms)'),)),
    ("E16", "spine: §8 prose keys an arrangement as a card (' :410): One plus three carries the `Ctrl+4` key; the name is')",
     (('line:**Rename** is inline', '(CARRIED :410): ', '(CARRIED :410): One plus three carries the `Ctrl+4` key; '),)),
    ("E17", "spine: hand-off Table 5 row 'CMP-217 the layout-changed a' keys an arrangement as a card ('r switch | n/a | AN-1 / AN-2; 2 by 2 — `Ctrl+2`')",
     (('hand:| CMP-217   | the layout-changed announcement ', '| AN-1 / AN-2 ', '| AN-1 / AN-2; 2 by 2 — `Ctrl+2` '),)),
    ("E18", "spine: hand-off §B line keys an arrangement as a card ('politely once; Order-flow (shortcut `Ctrl+2`)')",
     (('hand:    And applying announces', 'politely once', 'politely once; Order-flow (shortcut `Ctrl+2`)'),)),
    ("E19", "spine: hand-off Table 4 row 'CMP-217 the Undo toast' keys an arrangement as a card ('pair; Fan-out review returns with `Ctrl+6` | instant | CMP-0')",
     (('hand:| CMP-217   | the Undo toast ', "| CMP-045's pair ", "| CMP-045's pair; Fan-out review returns with `Ctrl+6` "),)),
    ("E20", "trigger: hand-off Table 3 row 'CMP-217 the trigger' puts the key on the trigger ('spopup=      `, `aria-expanded` — its badge carries the slot'; merged E15-D03 D-9)",
     (('hand:| CMP-217   | the trigger ', '`aria-haspopup="menu"`, `aria-expanded`', '`aria-haspopup="menu"`, `aria-expanded` — its badge carries the slot'),)),
    ("E21", "trigger: hand-off Table 2 row 'CMP-217 `Enter` / `Space` / ' puts the key on the trigger ('yout; `[Layout ▾]` (once dirty) — a `Ctrl+3` chip | none | —'; merged E15-D03 D-9)",
     (('hand:| CMP-217   | `Enter` / `Space` / `↓` on the trigger', '| the active layout ', '| the active layout; `[Layout ▾]` (once dirty) — a `Ctrl+3` chip '),)),
    ("E22", "lock: hand-off §B line locks Discard ('inert')",
     (('hand:    Then an alertdialog "You have unsaved', 'and Esc cancels', 'and Esc cancels; for a viewer Discard — inert'),)),
    ("E23", "lock: §10.2 prose locks Open ('unavailable')",
     (('line:**Create** = ', 'Open, Rename…, Duplicate', 'Open (CMP-041; unavailable for a viewer), Rename…, Duplicate'),)),
    ("E24", "switch: hand-off CMP-073 block prose prompts in the row or sentence of a switch ('popover')",
     (('hand:- [x] **Keyboard table** — the rail is one Tab stop', '`Enter` opens, type-ahead', '`Enter` opens — then a popover, type-ahead'),)),
    ("E25", "dirty: hand-off Table 5 row 'CMP-073 the dirty marker' draws the dirty marker away from the row name ('under the row')",
     (('hand:| CMP-073   | the dirty marker ', 'client state (G-3) ', 'client state (G-3); shown under the row '),)),
    ("E26", 'number: handoff table 4 rail: the hand-off table says 150, the tool 120',
     (('hand:| CMP-073   | rail expand / collapse ', 'within 120 ms', 'within 150 ms'),)),
    ("E27", "number: the hand-off table types '30 × 30' outside a registered context",
     (('hand:| CMP-217   | a thumbnail ', '| static SVG ', '| static SVG, 30 × 30 '),)),
    ("E28", "number: the hand-off's 175 % is not a scale the tool measures",
     (('hand:- [x] Hit targets', 'none logged', 'none logged; at 175 % too'),)),
    ("E29", "number: the hand-off types '7' outside a registered context",
     (('hand:- [x] Hit targets', 'none logged', '7 logged'),)),
    ("E30", "lock: §9 prose locks Cancel ('greyed')",
     (('line:**Dirty** (`SCR-022/apply-dirty`', 'Cancel returns to the gallery with nothing applied.', 'Cancel (`secondary`; greyed for a viewer) returns to the gallery with nothing applied.'),)),
    ("E31", "switch: §9 prose prompts on a switch ('waits')",
     (('line:**Dirty** (`SCR-022/apply-dirty`', 'never opens this dialog (§10.3).', 'never opens this dialog (§10.3). Switching a layout from the menu keeps the copy. It then waits on a sheet.'),)),
    ("E32", "switch: hand-off Table 2 row 'CMP-217 `Ctrl+1..9' prompts in the row or sentence of a switch ('modal')",
     (('hand:| CMP-217   | `Ctrl+1..9` ', '| unchanged ', '| unchanged — a modal first '),)),
    ("E33", "siblings: the spec still hands the switch row to E15-D08 (§19)",
     (("line:Selecting another workspace", "and merged E15-D08 draws the row in its entry-point matrix (§3.2 E3 :419 at", "and the row is handed to E15-D08's entry-point matrix (§19; merged E15-D08 draws the row in its entry-point matrix (§3.2 E3 :419 at"),)),
    ("E34", "siblings: §10.3 does not cite merged E15-D08 §3.2 E3 :419 for the switch row",
     (("line:Selecting another workspace", "(§3.2 E3 :419 at", "(§3.2 E4 :420 at"),)),
    # delta r4: a named or articled workspace opened, selected or picked is a switch with no generic switch word
    ("E35", "switch: §10.2 prose prompts in the row or sentence of a switch ('asks')",
     (("line:**Create** = ", "(E30-D02 D3; no lock).", "(E30-D02 D3; no lock). Before it opens, Swing 4H asks you to save first."),)),
    ("E36", "switch: hand-off Table 5 row 'CMP-073 the dirty marker' prompts in the row or sentence of a switch ('asks')",
     (("hand:| CMP-073   | the dirty marker ", "client state (G-3) ", "client state (G-3); before it opens, Swing 4H asks you to save first "),)),
    ("E37", "switch: §11.1 row 'Next or previous workspace' prompts in the row or sentence of a switch ('asks')",
     (("line:| Next or previous workspace ", "serve meanwhile ", "serve meanwhile; the workspace asks before opening "),)),
    ("E38", "switch: hand-off CMP-073 block prose prompts in the row or sentence of a switch ('confirm')",
     (("hand:- [x] **Live data** — none streams: `listWorkspaces`", "— none streams", "— selecting Fanout review shows a confirm; none streams"),)),
)
# fmt: on
# Boards-PR fold (the approval record's four binding carries on #4507): (a) F01–F03 a pronoun-led sentence
# takes the previous sentence's subject; (b) F04–F07 "not available", "no longer available" and "can't be used"
# are lock words; (c) F08–F11 click, choose and select are switch verbs; (d) F12–F14 a hand-off row's Variant /
# Element cell sets the row's subject. Each FAIL alone; V8–V11 are their valid twins.
# fmt: off
BOARDS_MUTATIONS: tuple[tuple[str, str, tuple[Edit, ...]], ...] = (
    ('F01', "trigger: §7 prose puts the key on the trigger ('or only (RULED Q-12). trigger shows the key beside the name.'; merged E15-D03 D-9)",
     (('line:**The trigger** (', '(RULED Q-12). It reads', '(RULED Q-12). It shows the key beside the name. It reads'),)),
    ('F02', "trigger: §7 prose puts the key on the trigger ('hrough E15-S01 (C-7). trigger shows the key beside the name.'; merged E15-D03 D-9)",
     (('line:**The trigger** (', 'follows through E15-S01 (C-7).', 'follows through E15-S01 (C-7). It shows the key beside the name.'),)),
    ('F03', "trigger: §7 prose draws a key chip inline on the trigger ('Ctrl+'; merged E15-D03 D-9)",
     (('line:**The trigger** (', 'follows through E15-S01 (C-7).', 'follows through E15-S01 (C-7). This carries the `Ctrl+1` chip.'),)),
    ('F04', "lock: hand-off Table 2 row 'CMP-217 gallery `Tab` order' locks Apply ('not available')",
     (('hand:| CMP-217   | gallery `Tab` order', 'initial focus the first card', 'initial focus the first card; Apply — not available until a card is chosen'),)),
    ('F05', "lock: §5.3 prose locks Apply ('not available')",
     (('line:Row 1: ', 'with [Apply] (CMP-001 `primary`)', 'with [Apply] (CMP-001 `primary` — not available until a card is chosen)'),)),
    ('F06', "lock: §5.3 prose locks Apply ('no longer available')",
     (('line:Row 1: ', 'view-as included (E15-D02 §8.1 :640; §12).', 'view-as included (E15-D02 §8.1 :640; §12). Apply is no longer available while presets load.'),)),
    ('F07', "lock: §5.3 prose locks Cancel ('can't be used')",
     (('line:Row 1: ', 'view-as included (E15-D02 §8.1 :640; §12).', "view-as included (E15-D02 §8.1 :640; §12). Cancel can't be used while presets load."),)),
    ('F08', "switch: §10.1 prose prompts in the row or sentence of a switch ('dialog')",
     (('line:The expanded rail is 240 px', 'remounts no panel (`14` :329).', 'remounts no panel (`14` :329). Clicking Fanout review in the rail shows a save dialog first.'),)),
    ('F09', "switch: §10.1 prose prompts in the row or sentence of a switch ('sheet')",
     (('line:The expanded rail is 240 px', 'remounts no panel (`14` :329).', 'remounts no panel (`14` :329). Choosing Fanout review in the rail shows a sheet first.'),)),
    ('F10', "switch: §10.1 prose prompts in the row or sentence of a switch ('toast')",
     (('line:The expanded rail is 240 px', 'remounts no panel (`14` :329).', 'remounts no panel (`14` :329). Clicking a workspace in the rail shows a toast first.'),)),
    ('F11', "switch: §10.1 prose prompts in the row or sentence of a switch ('popover')",
     (('line:The expanded rail is 240 px', 'remounts no panel (`14` :329).', 'remounts no panel (`14` :329). Selecting the next workspace shows a popover.'),)),
    ('F12', "trigger: hand-off Table 1 row 'CMP-217 trigger' puts the key on the trigger ('*`,                  ) · keyed (a `Ctrl+1` chip) | `CMP-217/'; merged E15-D03 D-9)",
     (('hand:| CMP-217   | trigger ', 'clean · dirty (`*`, "unsaved changes")', 'clean · dirty (`*`, "unsaved changes") · keyed (a `Ctrl+1` chip)'),)),
    ('F13', "trigger: hand-off Table 1 row 'CMP-217 trigger' puts the key on the trigger ('`*`,                  ) (it shows `Ctrl+1`) | `CMP-217/trigg'; merged E15-D03 D-9)",
     (('hand:| CMP-217   | trigger ', 'clean · dirty (`*`, "unsaved changes")', 'clean · dirty (`*`, "unsaved changes") (it shows `Ctrl+1`)'),)),
    ('F14', "trigger: hand-off Table 1 row 'CMP-217 trigger' puts the key on the trigger (' (`*`,                  ) (shows the key) | `CMP-217/trigger'; merged E15-D03 D-9)",
     (('hand:| CMP-217   | trigger ', 'clean · dirty (`*`, "unsaved changes")', 'clean · dirty (`*`, "unsaved changes") (shows the key)'),)),
)
# fmt: on
# fmt: off
VALID_TWINS: tuple[tuple[str, str, tuple[Edit, ...]], ...] = (
    ('V1', 'no key chip on any preset card',
     (('line:**Three nouns, one each', '"Two by two, four panels". A **saved', '"Two by two, four panels". There is no key chip on any preset card. A **saved'),)),
    ('V2', 'never prompts T2',
     (('hand:| CMP-217   | `Ctrl+1..9` ', 'defect H-1 (ranges never dispatch)', 'defect H-1 (ranges never dispatch); never prompts'),)),
    ('V3', 'saved layout Ctrl+1..9',
     (('hand:| CMP-217   | a saved layout item ', '`aria-checked` on the active one', '`aria-checked` on the active one; the saved layout keeps its `Ctrl+1..9` chip'),)),
    ('V4', 'Two by two no hotkey',
     (('line:**Rename** is inline', '(CARRIED :410): ', '(CARRIED :410): Two by two never carries a hotkey; '),)),
    ('V5', 'Discard never greyed',
     (('line:**Dirty** (`SCR-022/apply-dirty`', 'Cancel returns to the gallery with nothing applied.', 'Cancel returns to the gallery with nothing applied. Discard is never greyed out.'),)),
    ('V6', 'opening Swing 4H never prompts',
     (('line:**Create** = ', '(E30-D02 D3; no lock).', '(E30-D02 D3; no lock). Opening Swing 4H never prompts, and selecting another workspace shows no dialog.'),)),
    ('V7', 'the New workspace dialog is a create',
     (('line:**Create** = ', '(E30-D02 D3; no lock).', '(E30-D02 D3; no lock). Creating a workspace opens the New workspace dialog; it never opens a workspace before Create workspace.'),)),
    ('V8', 'the trigger never shows a key chip',
     (('line:**The trigger** (', 'follows through E15-S01 (C-7).', 'follows through E15-S01 (C-7). It never shows a key chip.'),)),
    ('V9', 'Save layout is not available to a viewer (T2, C-16)',
     (('line:Row 1: ', 'view-as included (E15-D02 §8.1 :640; §12).', 'view-as included (E15-D02 §8.1 :640; §12). Save layout is not available to a viewer.'),)),
    ('V10', 'selecting a preset card and Apply is no workspace switch',
     (('line:Row 1: ', 'view-as included (E15-D02 §8.1 :640; §12).', 'view-as included (E15-D02 §8.1 :640; §12). Select a preset card and Apply; on a dirty copy SCR-029 asks to save first.'),)),
    ('V11', 'the trigger row never draws a key chip',
     (('hand:| CMP-217   | trigger ', 'clean · dirty (`*`, "unsaved changes")', 'clean · dirty (`*`, "unsaved changes") · never a `Ctrl+1` chip'),)),
)
# fmt: on


def apply_mutation(
    spec: str, handoff: str, edits: tuple[Edit, ...], catalogue: str = ""
) -> tuple[str, str, str]:
    """Apply each edit to the one line its target names; raise if a target or text is missing."""
    docs = {"spec": spec.split("\n"), "hand": handoff.split("\n"), "cat": catalogue.split("\n")}
    for target, old, new in edits:
        kind, _, key = target.partition(":")
        if kind == "spec":  # one exact stretch of the whole spec
            whole = "\n".join(docs["spec"])
            if whole.count(old) != 1:
                raise ValueError(f"mutation target {target!r} / {old!r} not found exactly once")
            docs["spec"] = whole.replace(old, new, 1).split("\n")
            continue
        doc = docs[kind] if kind in ("hand", "cat") else docs["spec"]
        if kind == "frame":
            idx = [i for i, ln in enumerate(doc) if ln.startswith(f"| `{key}` ")]
        elif kind == "inv":
            idx = [
                i
                for i, ln in enumerate(doc)
                if re.match(r"^\| \d+ +\| [^|]+\| " + re.escape(key) + r" +\|", ln)
            ]
        else:
            idx = [i for i, ln in enumerate(doc) if ln.startswith(key)]
        if len(idx) != 1 or old not in doc[idx[0]]:
            raise ValueError(f"mutation target {target!r} / {old!r} not found exactly once")
        doc[idx[0]] = doc[idx[0]].replace(old, new, 1)
    return "\n".join(docs["spec"]), "\n".join(docs["hand"]), "\n".join(docs["cat"])


ALL_MUTATIONS = (
    MUTATIONS + RECORD_MUTATIONS + DELTA_MUTATIONS + RECHECK_MUTATIONS + BOARDS_MUTATIONS
)
SELF_TEST_RUNS: dict[str, int] = {"inline": 0, "table": 0, "one_fail": 0, "valid": 0}


def self_test(spec: str, handoff: str, tool: str, bindings: set[str], catalogue: str) -> list[str]:
    """Mutate the spec or the hand-off in memory; every mutation trips exactly its own gate."""
    problems: list[str] = []
    base = gates(spec, handoff, tool, bindings, catalogue=catalogue)
    if base:
        return ["self-test needs a passing baseline; gates failing: " + "; ".join(base)]

    def expect(
        name: str,
        mutated: str,
        needle: str,
        hand: str = handoff,
        body: str = "",
        cat: str = catalogue,
    ) -> None:
        got = gates(mutated, hand, tool, bindings, body, [], cat)
        SELF_TEST_RUNS["inline"] += 1
        SELF_TEST_RUNS["one_fail"] += len(got) == 1 and needle in got[0]
        if not any(needle in g for g in got):
            problems.append(f"self-test: mutation '{name}' did not trip its gate ({needle})")
        elif len(got) != 1:
            problems.append(
                f"self-test: mutation '{name}' gave {len(got)} FAILs (only its own expected): "
                + " / ".join(got)
            )

    expect(
        "drop the §12 cite from the rail section",
        in_section(spec, "## 10. ", "## 11. ", lambda t: t.replace("§12", "§ 12")),
        "t2: the rail does not cite",
    )
    expect(
        "put workspaces:write before the view-as leg in §12",
        in_section(
            spec, "## 12. ", "## 13. ", lambda t: t.replace("`rbac.view_as`", "`rbac.view-as`", 1)
        ),
        "view-as: the T2 statement",
    )
    expect("a PR body with a closing keyword", spec, "closing: pr-body", body="Clo" + "ses #321")
    expect(
        "a PR body with a local path",
        spec,
        "hygiene: pr-body",
        body="see /" + "home" + "/someone/notes",
    )
    expect(
        "a design-tool host in the hand-off",
        spec,
        "hygiene: handoff",
        hand=handoff + "\npenpot" + ".example" + ".com",
    )
    expect(
        "a marker drift",
        re.sub(
            r"(<!-- audit:cols=)(\d+)",
            lambda m: m.group(1) + str(int(m.group(2)) + 1),
            spec,
            count=1,
        ),
        "marker: audit:cols=",
    )
    expect(
        "a foreign size",
        spec.replace("## 21. ", "## 21. (a 999×777 inset) ", 1),
        "number: the spec's 999×777",
    )
    expect(
        "a foreign ratio",
        spec.replace("## 21. ", "## 21. (measures 9.99:1) ", 1),
        "number: the spec's ratio 9.99",
    )
    expect(
        "the catalogue loses the checklist pointer",
        spec,
        "catalogue: the SCR-022 checklist pointer",
        cat=catalogue.replace("the legacy checklist names", "the old checklist names", 1),
    )
    expect(
        "the catalogue's kept Data line changes",
        spec,
        "catalogue: a kept SCR-022 line changed",
        cat=catalogue.replace(
            CAT_KEEP[0], CAT_KEEP[0].replace("layout-presets", "layout-preset"), 1
        ),
    )
    expect(
        "the hand-off's frame count drifts",
        spec,
        "frames: the hand-off's named-frame count",
        hand=re.sub(
            r"(\d+) named frames", lambda m: f"{int(m.group(1)) + 1} named frames", handoff, count=1
        ),
    )
    expect(
        "a §13 matrix row drifts",
        in_section(
            spec,
            "## 13. ",
            "**Validity look",
            lambda t: t.replace("14.35 (grey 14.47)", "14.36 (grey 14.47)", 1),
        ),
        "matrix: the §13 row",
    )
    expect(
        "a pair row drifts",
        in_section(
            spec, "### 6.2 ", "## 7. ", lambda t: t.replace("| geometry ", "| glyphs + label ", 1)
        ),
        "pairs: the §6.2 pair table",
    )
    expects = [e for _m, e, _ed in ALL_MUTATIONS]
    if len(set(expects)) != len(expects):
        problems.append("self-test: two mutations share a FAIL message")
    # the fit gate is computed, not read from the spec: probe it with a card one pixel taller than its viewport
    probe = copy.deepcopy(_gallery())
    probe["zoom200"]["card_h"] = probe["zoom200"]["scroll"] + 1
    got_fit = fit_gates(probe)
    SELF_TEST_RUNS["inline"] += 1
    SELF_TEST_RUNS["one_fail"] += len(got_fit) == 1 and "zoom: a card" in got_fit[0]
    if len(got_fit) != 1 or "zoom: a card" not in got_fit[0]:
        problems.append(
            "self-test: a card taller than its scroll viewport did not trip the fit gate once"
        )
    for mid, want, edits in ALL_MUTATIONS:
        try:
            s2, h2, c2 = apply_mutation(spec, handoff, edits, catalogue)
        except ValueError as exc:
            problems.append(f"self-test: {mid} cannot be applied ({exc})")
            continue
        got = gates(s2, h2, tool, bindings, catalogue=c2)
        SELF_TEST_RUNS["table"] += 1
        SELF_TEST_RUNS["one_fail"] += len(got) == 1 and want in got[0]
        hits = sum(want in g for g in got)
        if hits != 1:
            problems.append(
                f"self-test: {mid} tripped '{want}' {hits} times (once expected): "
                + " / ".join(got)
            )
        elif len(got) != 1:
            problems.append(
                f"self-test: {mid} gave {len(got)} FAILs (only its own expected): "
                + " / ".join(got)
            )
    for vid, why, edits in VALID_TWINS:  # negated and saved-layout forms stay valid (re-check M-1)
        s2, h2, c2 = apply_mutation(spec, handoff, edits, catalogue)
        got = gates(s2, h2, tool, bindings, catalogue=c2)
        SELF_TEST_RUNS["valid"] += not got
        if got:
            problems.append(f"self-test: valid twin {vid} ({why}) raised: " + " / ".join(got))
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
    ap.add_argument("--pairs", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--pr-body", default="")
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument(
        "paths", nargs="*", help="ignored: the spec and the hand-off are found from the repo root"
    )
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    fails: list[str] = []
    g, inv, menu, rail = _gallery(), _inventory(), _menu(), _rail()
    matrix = matrix_report(fails)
    spec, handoff, tool = read(SPEC), read(HANDOFF), Path(__file__).read_text(encoding="utf-8")
    catalogue = read(CATALOGUE)
    pr_body = read(Path(a.pr_body)) if a.pr_body else ""
    bindings = keymap_bindings()
    missing = bound_missing()
    if missing:
        fails.append("tokens: bound tokens missing from the dark set: " + ", ".join(missing))
    gate_fails = (
        gates(spec, handoff, tool, bindings, pr_body, a.files, catalogue)
        if spec
        else ["spec missing"]
    )
    fails.extend(gate_fails)
    st: list[str] = []
    if a.self_test and spec:
        st = self_test(spec, handoff, tool, bindings, catalogue)
        fails.extend(st)
    markers = build_markers(spec, handoff)
    out = {
        "tokens_px": tokens_px(),
        "gallery": g,
        "inventory": {k: v for k, v in inv.items() if k != "pairs"},
        "pairs": inv["pairs"],
        "menu": menu,
        "rail": rail,
        "matrix": matrix,
        "cvd": cvd_report(),
        "keymap": keymap_rows(),
        "reasons": reasons_report(),
        "tokens": {n: ("MISSING" if n in missing else str(tok(n))) for n in BOUND},
        "gates": gate_fails,
        "self_test": st,
        "fails": fails,
        "markers": markers,
        "constants": {k: v for k, v in ledger(markers).items() if k not in markers},
    }
    if a.json:
        p(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    elif a.table:
        p(matrix_table(matrix))
    elif a.pairs:
        p(pairs_table(inv))
    else:
        l19, l12, z = g["layouts"]["1920-compact"], g["layouts"]["1280-compact"], g["zoom200"]
        p(
            "1. GALLERY (CMP-043 lg, carried sizes; rows from the tokens; the card grid from the minimum card width)"
        )
        p(
            f"  canvas {g['canvas']} fits {g['fits']}; pad {l19['pad']} header {l19['header']} footer {l19['footer']} compact"
        )
        p(
            f"  1920: body {l19['body']} cols {l19['cols']} card {l19['card_w']}x{l19['card_h']} thumb {l19['thumb_w']}x{l19['thumb_h']} rows {l19['card_rows']} listbox {l19['listbox_full']} visible {l19['listbox_visible']} ({l19['card_rows_visible']} rows) Your layouts rows {l19['yl_rows_visible']}"
        )
        p(
            f"  1280: body {l12['body']} cols {l12['cols']} card {l12['card_w']}x{l12['card_h']} thumb {l12['thumb_w']}x{l12['thumb_h']} listbox {l12['listbox_full']} visible {l12['listbox_visible']} ({l12['card_rows_visible']} rows) Your layouts rows {l12['yl_rows_visible']}"
        )
        p(
            f"  200 %: modal {z['width']}x{z['height']} between bars {z['between_bars']}; cols {z['cols']} card {z['card_w']}x{z['card_h']} (a row); footer {z['footer']} one row; scroll viewport {z['scroll']}, the listbox {z['listbox_full']} inside it"
        )
        p(
            f"  footer sentence {l19['sentence_w']} px, warning {l19['warning_w']} px (one line: {l19['sentence_one_line']} / {l19['warning_one_line']}); empty sentence {l12['empty_lines']} lines at 1280"
        )
        p("2. INVENTORY AND THUMBNAILS")
        for r in inv["rows"]:
            c = r["cells"]["1280"]
            p(
                f"  {r['order']:2d} {r['label']:15s} {r['panels']} panels  {r['sig']:5s} id {r['id'][-4:] if r['served'] else 'PROPOSED'}  min cell {c['min_w']}x{c['min_h']} glyph {c['glyph_fits']} word {c['word_fits']}  glyphs {r['glyphs']}"
            )
        p(
            f"  {inv['pair_count']} pairs: {inv['pairs_by_geometry']} by geometry, {inv['pairs_by_glyphs']} by glyphs + label; cut {inv['cut']}; glyph requests {inv['glyph_requests']}"
        )
        p("3. LAYOUT MENU (CMP-217)")
        p(
            f"  width {menu['menu_w']}; heights {menu['heights']}; available {menu['available']}; first scroll {menu['first_scroll']}; twelve: {menu['twelve_keyed']} keyed, {menu['twelve_nokey']} no key"
        )
        p("4. RAIL (SCR-011)")
        p(
            f"  fit {rail['fit']}; stack {rail['stack']}; search above {rail['search_threshold']}; cap {rail['cap']}"
        )
        p("5. MEASURED MATRIX")
        p(matrix_table(matrix))
        p(
            f"  gated {matrix['gated']}, failed {matrix['failed']}; validity look {matrix['validity']}"
        )
        p("6. CVD " + json.dumps(cvd_report()["rows"], ensure_ascii=False)[:600] + " …")
        p("7. KEYS " + json.dumps(keymap_rows(), ensure_ascii=False))
        p("8. REASONS " + json.dumps(reasons_report(), ensure_ascii=False))
        p(f"TOKENS: {len(BOUND)} bound, {len(missing)} missing ({', '.join(missing) or 'none'})")
        p(
            "COUNTS: "
            + (
                ", ".join(f"{k} {v}" for k, v in counts(spec, handoff).items())
                if spec
                else "spec missing"
            )
        )
        p("GATES: " + ("all pass" if not gate_fails else "; ".join(gate_fails)))
        if a.self_test:
            r_ = SELF_TEST_RUNS
            p(
                "SELF-TEST: "
                + (
                    f"{r_['inline'] + r_['table']} mutations ({r_['inline']} inline + {r_['table']} table), {r_['one_fail']} with their own FAIL as the only one; {r_['valid']} valid twins clean"
                    if not st
                    else "; ".join(st)
                )
            )
        p("RESULT: " + ("PASS" if not fails else "FAIL — " + "; ".join(fails)))
    return 1 if (a.check or a.self_test) and fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
