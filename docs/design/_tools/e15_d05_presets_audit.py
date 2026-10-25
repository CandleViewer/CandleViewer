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
    id, never on a ruling sentence, and read clause by clause rather than by one keyword: the spine word per
    surface (a saved-layout frame names the saved layout); no key chip on a preset card; the dirty marker in the
    row name on every dirty frame; no prompt on the dirty switch; the footer carriers on every gallery frame; the
    one T2's anatomy on every T2 frame and the T2 form on no other row; no CTA, button or bracketed action in the
    sentence form; no lock token in an availability clause; no one-click delete in any wording; every exit T1 and
    never paired with a gate (one gate for the exit class); every "N px" or count a frame draws is a value the
    tool prints; every chord outside the keymap marked PROPOSED; the inventory's order, counts, cut preset and
    card notes.
11. Numbers: the ``audit:`` block at the end of the spec equals ``--json``'s markers; every W x H and two-decimal
    ratio in the spec and the hand-off is one the tool derives; the section 13 table rows equal the tool's.

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
    "the 2026 checklist names map there) [ ] user presets with rename/delete [ ] 'applying replaces your current layout' "
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
    # the `14` write-back: the added lines present, the kept lines unchanged
    if catalogue:
        for label, line in (
            ("the SCR-022 Type line", CAT_TYPE_LINE),
            ("the SCR-022 checklist pointer", CAT_CHECKLIST_LINE),
            ("the SCR-022 hi-fi pointer", CAT_POINTER_022),
            ("the SCR-011 hi-fi pointer", CAT_POINTER_011),
        ):
            if line not in catalogue:
                fails.append(f"catalogue: {label} is not in `14`")
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
    r"lock|aria-disabled|\bT2\b|CMP-079|rbac\.|disabledReason|\bblocked\b|\bdisabled\b|(?<!never )\bgated\b",
    re.IGNORECASE,
)
EXIT_NEAR_GATE = re.compile(
    r"(?:×|`Esc`|Cancel|Close|Discard changes|Browse presets…|Apply|Keep current symbols|\bOpen\b|Back)[^;.|]{0,40}?"
    r"\b(?:locked|lock glyph|`lock`|lock|padlock|aria-disabled|disabled|blocked|(?<!never )gated|T2|CMP-079"
    r"|rbac\.[a-z_]+|disabledReason)\b"
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
    r"(?<![\d.×+:])(\d+(?:,\d{3})?) (px|rows|columns|card skeletons|workspaces|layouts|cards)\b"
)
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
    r"(?:Ctrl|Alt|Shift|Meta|Cmd)\+[A-Za-z0-9←→↑↓\\]+(?:\+[A-Za-z0-9←→↑↓\\]+)*(?:\.\.\d)?"
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
        ("the key chip", "Ctrl+1"),
    )
    needs["CMP-217/menu-default"] = (
        ("Browse presets… last", "Browse presets…"),
        ("the saved layouts first", "Layout 1"),
    )
    needs["CMP-217/menu-twelve"] = (
        (f"{keyed} keyed", f"{keyed} keyed"),
        ("the first scrolling count", f"from {nums['menu_first_scroll_1280_compact']} layouts"),
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
    for f in DIRTY_FRAMES:
        needs[f] = needs.get(f, ()) + (
            ("the dirty marker in the row name", "unsaved changes"),
            ("the asterisk", "\\*"),
        )
    needs["SCR-011/light-rail"] += (("semantic-light", "semantic-light"),)
    needs["SCR-011/empty"] = (
        ("the failed-create explanation", "failed"),
        ("[New workspace] T1", "[New workspace] T1"),
    )
    needs["SCR-011/loading"] = (("skeleton rows", "skeleton"), ("`aria-busy`", "`aria-busy`"))
    needs["SCR-011/error"] = (
        ("the load failure copy", "Workspaces didn't load."),
        ("[Retry]", "[Retry]"),
    )
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
    allowed_nums = {
        str(int(v))
        for v in nums.values()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer()
    } | set(STROKE_PX)
    for name, r in by.items():
        text = " | ".join(r)
        prefix = name.split("/")[0]
        if len(r) < 7:
            fails.append(f"inventory: frame {name} has fewer than seven cells")
            continue
        # A2: the spine word per surface, in the Spine cell (a saved-layout frame names the saved layout)
        noun = "saved layout" if name in SAVED_LAYOUT_FRAMES else SPINE_WORD.get(prefix, "")
        if noun not in r[4]:
            fails.append(f"spine: frame {name} does not name its noun ({noun})")
        if prefix == "SCR-022" and re.search(
            r"(?:Rename|Delete|Duplicate) workspace|Set as default|Move up", text
        ):
            fails.append(f"spine: frame {name} offers a workspace action in the gallery")
        if prefix == "SCR-011" and re.search(r"Ctrl\+[1-9]", text):
            fails.append(f"spine: frame {name} shows layout keys in the switcher")
        if prefix == "SCR-022":
            for m in re.finditer(r"Ctrl\+(?:[1-9]|1\.\.9)", text):
                cl = clause_at(text, m.start())
                if re.search(r"\bcards?\b|\bpreset\b", cl) and not re.search(
                    r"\bno\b|\bnever\b|\bnot\b", cl
                ):
                    fails.append(
                        f"spine: frame {name} puts a hotkey on a preset card ('{cl[:60]}')"
                    )
                    break
        # A2: the per-frame carriers
        for label, needle in needs.get(name, ()):
            seen = present(text, needle)
            if seen == "no":
                fails.append(f"carrier: frame {name} lacks {label}")
            elif seen == "negated" and label not in ("no prompt",):
                fails.append(f"carrier: frame {name} negates {label}")
        # A2: every "N px" / count in the drawn state is a value the tool prints (lens round 1 F-5)
        for m in UNIT_NUM.finditer(r[2]):
            if m.group(1).replace(",", "") not in allowed_nums:
                fails.append(
                    f"number: frame {name} draws {m.group(1)} {m.group(2)}, not a value the tool derives"
                )
                break
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
        if name == "SCR-011/switch-dirty" and (
            present(text, "SCR-029") == "yes" or present(text, "prompt") != "negated"
        ):
            fails.append("switch: the dirty switch frame prompts or omits the no-prompt rule (D-9)")
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
            for m in T2_FORM.finditer(body):
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
        if EXIT_GATED.search(exits):
            fails.append(f"exits: frame {name} gates an exit in its Exits cell")
        elif "T1" not in exits:
            fails.append(f"exits: frame {name} does not class its exits T1")
        hit = EXIT_NEAR_GATE.search(r[2] + " | " + r[5])
        if hit:
            fails.append(f"exits: frame {name} gates an exit ('{hit.group(0)}')")
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
    for where, text in surfaces:
        for cell in text.split("|"):
            for clause in cell.split(";"):
                for m in CHORD.finditer(clause):
                    c = m.group(0)
                    if all(e in bindings or e in COMPONENT_KEYS for e in expand_chord(c)):
                        continue
                    pm = re.search(r"proposed", clause[m.end() :], re.IGNORECASE)
                    gap = clause[m.end() : m.end() + pm.start()] if pm else ""
                    if not pm or re.search(r"\b(?:SCR|CMP)-\d|\bor\b", gap):
                        fails.append(f"keys: {where} draws {c} without PROPOSED after it")
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
        "count_frames_named": len(inv),
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
)


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


def number_gates(spec: str, handoff: str) -> list[str]:
    fails: list[str] = []
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
    for where, text, ctx in (("spec", prose, CONTEXTS), ("hand-off", hand_prose, HANDOFF_CONTEXTS)):
        for label, pattern, names in ctx:
            hits = list(re.finditer(pattern, text))
            if not hits:
                fails.append(f"number: the {where} context '{label}' vanished")
            for hit in hits:
                for i, name in enumerate(names, start=1):
                    if not same_number(hit.group(i), mk[name]):
                        fails.append(
                            f"number: {label}: the {where} says {hit.group(i)}, the tool {mk[name]}"
                        )
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
    fails += frame_gates(spec, bindings, mk)
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
    ("M17", "exits: frame SCR-022/apply-dirty-viewer gates an exit ('Discard changes is locked')",
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
    ("M37", "switch: the dirty switch frame prompts or omits the no-prompt rule (D-9)",
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
    ("M45", "t2-form: frame SCR-022/apply-clean draws '`lock`'",
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
    ("M57", "carrier: frame CMP-217/menu-twelve lacks the first scrolling count",
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
    ("M64", "exits: frame SCR-022/apply-dirty-viewer gates an exit ('Discard changes takes the lock')",
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
)
# fmt: on


def apply_mutation(spec: str, handoff: str, edits: tuple[Edit, ...]) -> tuple[str, str]:
    """Apply each edit to the one line its target names; raise if a target or text is missing."""
    docs = {"spec": spec.split("\n"), "hand": handoff.split("\n")}
    for target, old, new in edits:
        kind, _, key = target.partition(":")
        doc = docs["hand" if kind == "hand" else "spec"]
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
    return "\n".join(docs["spec"]), "\n".join(docs["hand"])


SELF_TEST_RUNS: dict[str, int] = {"inline": 0, "table": 0, "one_fail": 0}


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
        "state the T2 rule twice",
        spec.replace("The rule, once.", "The rule, once. The rule, once.", 1),
        "t2: the one T2 rule",
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
        "the catalogue loses the Type line",
        spec,
        "catalogue: the SCR-022 Type line",
        cat=catalogue.replace("3+1 cut, AM-2", "3+1 kept, AM-2", 1),
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
    expects = [e for _m, e, _ed in MUTATIONS]
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
    for mid, want, edits in MUTATIONS:
        try:
            s2, h2 = apply_mutation(spec, handoff, edits)
        except ValueError as exc:
            problems.append(f"self-test: {mid} cannot be applied ({exc})")
            continue
        got = gates(s2, h2, tool, bindings, catalogue=catalogue)
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
                    f"{r_['inline'] + r_['table']} mutations ({r_['inline']} inline + {r_['table']} table), {r_['one_fail']} with their own FAIL as the only one"
                    if not st
                    else "; ".join(st)
                )
            )
        p("RESULT: " + ("PASS" if not fails else "FAIL — " + "; ".join(fails)))
    return 1 if (a.check or a.self_test) and fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
