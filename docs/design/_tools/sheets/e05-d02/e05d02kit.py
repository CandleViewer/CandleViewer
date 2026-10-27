"""e05d02kit: the shared sheet kit for the E05-D02 (#161) component-library specimen boards. Python 3.12+, stdlib only.

Every builder returns cvsheet node dicts (schema: ../lib/cvsheet-v4.2.js header; the v1 node keys), so the ten board
generators (gen/gen_NN.py) draw their specimen sheets the same way: per component one titled SPECIMEN BLOCK (variants
x sizes x the key states the spec names), each state a CELL (the specimen on color.surface.app, its state caption),
cells grouped in STATE ROWS, each block captioned with its CMP id, spec section and tokens, and one ANNOTATION COLUMN
per board (sources, PROPOSED / RULED stamps, what is not drawn, kit choices).
Sources: the four MERGED slice specs as of commit 966f9edcd (a frozen copy in spec/ beside this file if present,
else read with `git show 966f9edcd:<path>`; DOCS pins each md5): slice 1 E05-D02.md (actions and selection), slice 2 E05-D02-data-display.md, slice 3
E05-D02-form-controls.md, slice 4 E05-D02-feedback-overlays.md.

BINDING (per-set file "E05-D02 boards"): no library component; the kit draws NO inst node; every component is composed
from board / rect / text / ellipse with token binds. Icons (t:"icon") only for the file's local `icon / locked`,
`arrow-up`, `arrow-down`, `close`, `drag-handle` (ICONS); every other glyph is a text glyph (NOTATION) or primitives.
Lessons (live, 2026-10-27) enforced by write_sheet(): text sits only in flex rows / columns (a hug board holding text
inside a non-flex board is refused); a text-free board carries an explicit h; sections <= ~9 KB compacted.

Registries parsed from the specs at import (never retyped): BOARDS (the ten boards: slug, name, CMPs, slice, page,
theme, export), CMPS (every `### CMP-0xx · Name` section: span, Penpot name, export, tables), DECISIONS (per slice,
the §6 / §5 owner-decision ids A1..H37 with their line).
Copy: inside a specimen (a board named "specimen…") every text comes from say(chars, cmp) (found in that CMP's section
or its slice), an axis value, or NOTATION; write_sheet() refuses the rest. Captions and the annotation column are
board chrome and free.
Use from a generator (python3 -I keeps the kit's folder off sys.path):
    import sys; sys.dont_write_bytecode = True
    sys.path.insert(0, "<this folder>")
    import e05d02kit as k
    row = k.state_row("primary", [k.cell("default", k.button(k.say("Save", "CMP-001"), "primary")), ...])
    blk = k.block("CMP-001", [row, ...], states=["default", ...], not_drawn=["size lg x every state ..."],
                  proposed=["D13"])
    bd = k.board(1, [blk, ...], source="slice 1 §3, §8 L621-1372")
    k.write_sheet(k.KIT_DIR / f"{k.stem(1)}.json", bd); k.compact_sheet(k.KIT_DIR / f"{k.stem(1)}.json")
    k.write_board_md(1, bd, checks=[...], live=[...])
CLI: python3 -I -B e05d02kit.py selftest       (checks, builds every piece, writes 00-selftest.json, validates, compacts)
     python3 -I -B e05d02kit.py cmps [NN]       (board -> CMPs: span, Penpot name, axes, cells, tokens)
     python3 -I -B e05d02kit.py cmp CMP-0xx     (one CMP's tables, condensed)
     python3 -I -B e05d02kit.py report <sheet.json>...   (the shape-count report)
     python3 -I -B e05d02kit.py compact <sheet.json>...  (compact.py into v4/, compactOf checked)
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

Node = dict[str, Any]

KIT_DIR = Path(__file__).resolve().parent
SHEETS_DIR = KIT_DIR.parent  # docs/design/_tools/sheets
TOOLS_DIR = SHEETS_DIR / "tools"
V4_DIR = KIT_DIR / "v4"  # the packed (compact) sheets the boards were drawn from
VALIDATOR = TOOLS_DIR / "validate_sheet.py"
COMPONENTS = TOOLS_DIR / "components.offline.json"
COMPACT = TOOLS_DIR / "compact.py"
TOKENS_FILE = TOOLS_DIR / "token-sync.json"
WT = KIT_DIR.parents[
    4
]  # the repository root (a WARN when a slice doc differs from its frozen copy)
SPEC_HEAD = "966f9edcd"  # origin/main when the kit froze the four specs (2026-10-27)
DOCS = {  # key -> (frozen copy, repo path, md5, slice label)
    "s1": (
        KIT_DIR / "spec" / "E05-D02@966f9edcd.md",
        "docs/design/E05/E05-D02.md",
        "72dc9ede4f3ce6a4620ffd50816cb935",
        "slice 1",
    ),
    "s2": (
        KIT_DIR / "spec" / "E05-D02-data-display@966f9edcd.md",
        "docs/design/E05/E05-D02-data-display.md",
        "fa72d69bce5362a9430f20a0feaf39a3",
        "slice 2",
    ),
    "s3": (
        KIT_DIR / "spec" / "E05-D02-form-controls@966f9edcd.md",
        "docs/design/E05/E05-D02-form-controls.md",
        "c768259c5a59fbf6161a52f0cb498b79",
        "slice 3",
    ),
    "s4": (
        KIT_DIR / "spec" / "E05-D02-feedback-overlays@966f9edcd.md",
        "docs/design/E05/E05-D02-feedback-overlays.md",
        "fb6e8b12d79fc6c057f0b695d495867d",
        "slice 4",
    ),
}
FILE = "E05-D02 boards"  # the per-set Penpot file (not the shared DS file)
PAGES = {
    "s1": "E05-D02 slice 1 actions and selection",
    "s2": "E05-D02 slice 2 data display and text",
    "s3": "E05-D02 slice 3 form controls",
    "s4": "E05-D02 slice 4 feedback and overlays",
}
SET = "E05-D02"
REV = "r1"
SECTION_BUDGET = 12000  # bytes per section (json.dumps): about 7-9 KB once compacted
SECTION_HARD = 24000  # the validator warns above this; write_sheet() refuses it
COMPACT_MAX = (
    9 * 1024 + 512
)  # a compacted section above ~9.5 KB fails the brief's "<= ~9 KB" (compact_sheet raises)

# --- Tokens: exact Penpot names (token-sync.json); colour and typography from the semantic sets.
APP, CANVAS, RAISED = "color.surface.app", "color.surface.canvas", "color.surface.raised"
OVERLAY, SUNKEN, SELECTED, HOVER = (
    "color.surface.overlay",
    "color.surface.sunken",
    "color.surface.selected",
    "color.surface.hover",
)
BORDER_SUBTLE, BORDER_DEFAULT, BORDER_STRONG = (
    "color.border.subtle",
    "color.border.default",
    "color.border.strong",
)
BORDER_SELECTED = "color.border.selected"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_ON_ACTION, TEXT_INVERSE, TEXT_LINK = (
    "color.text.on-action",
    "color.text.inverse",
    "color.text.link",
)
TEXT_DISABLED = "color.text.disabled"
ACTION = {
    "primary": "color.action.primary.default",
    "primary.hover": "color.action.primary.hover",
    "primary.active": "color.action.primary.active",
    "secondary": "color.action.secondary.default",
    "secondary.hover": "color.action.secondary.hover",
    "selected": "color.action.selected",
}
BUY, BUY_HOVER, SELL, SELL_HOVER = (
    "color.buy.default",
    "color.buy.hover",
    "color.sell.default",
    "color.sell.hover",
)
STATUS = {
    f"{t}.{s}": f"color.status.{t}.{s}"
    for t in ("info", "success", "warning", "danger")
    for s in ("default", "strong", "subtle")
}
FOCUS_RING = "color.focus.ring"
CAPTION, BODY, BODY_STRONG, LABEL = (
    "type.ui.caption",
    "type.ui.body",
    "type.ui.body-strong",
    "type.ui.label",
)
HEADING_SM, HEADING_MD, HEADING_LG = (
    "type.ui.heading-sm",
    "type.ui.heading-md",
    "type.ui.heading-lg",
)
NUM_XS, NUM_SM, NUM_BASE, NUM_MD = "type.num.xs", "type.num.sm", "type.num.base", "type.num.md"
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = (
    "space.inset.xs",
    "space.inset.sm",
    "space.inset.md",
    "space.inset.lg",
    "space.inset.xl",
)
STACK_XS, STACK_SM, STACK_MD, STACK_LG = (
    "space.stack.xs",
    "space.stack.sm",
    "space.stack.md",
    "space.stack.lg",
)
BTN_PADX, BTN_PADY, FIELD_GAP = "space.button.paddingX", "space.button.paddingY", "space.field.gap"
DIALOG_PAD, PANEL_PAD = "space.dialog.padding", "space.panel.padding"
CONTROL_H, ROW_H = "size.control.height", "size.row.height"
ICON, ICON_SM, ICON_LG = "size.icon", "size.icon.sm", "size.icon.lg"
R_CONTROL, R_CARD, R_BADGE, R_DIALOG = (
    "radius.control",
    "radius.card",
    "radius.badge",
    "radius.dialog",
)
R_RING = "radius.md"  # 6 px = radius.control + 2 (the CMP-039 ring's radius; a Tier-1 primitive, FALLBACKS RING)
E_POPOVER, E_DIALOG, E_CARD = "elevation.popover", "elevation.dialog", "elevation.card"
OP_DISABLED, OP_SCRIM = "opacity.disabled", "opacity.scrim"
HAIRLINE, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
NEVER_T2 = (TEXT_DISABLED, OP_DISABLED)  # E09-D09 §2.2: never on a T2 label, glyph or reason
PX = {
    INSET_XS: 4,
    INSET_SM: 8,
    INSET_MD: 12,
    INSET_LG: 16,
    INSET_XL: 24,
    STACK_XS: 4,
    STACK_SM: 8,
    STACK_MD: 12,
    STACK_LG: 16,
    BTN_PADX: 12,
    BTN_PADY: 4,
    FIELD_GAP: 8,
    DIALOG_PAD: 24,
    PANEL_PAD: 12,
    ICON: 16,
    ICON_SM: 12,
    ICON_LG: 20,
    CONTROL_H: 24,
    ROW_H: 24,
}
CONTROL_PX = 24  # size.control.height, compact (the boards draw compact unless the spec draws both densities)

# --- Geometry (kit choices): page grid, the annotation column, captions.
PITCH_X, PITCH_Y = 6400, 4400  # page grid: the boards of one page side by side, PITCH_X apart
GRID_MAX_W = (
    PITCH_X - 240 - 440
)  # the specimen grid's widest (the annotation column and its gap take the rest)
ROOT_PAD = 16  # space.inset.lg
ANN_W, ANN_TEXT_W = 400, 368  # the annotation column (space.inset.lg padding)
ROW_LABEL_W = 120  # a state row's leading label
CELL_CAPTION_W = 160  # a cell's caption wraps at this width unless the cell is wider

# --- The notes collector (write_sheet() merges it into the sheet's notes and LAST_NOTES, then clears it).
NOTE_KINDS = (
    "sources",
    "copy_keys",
    "copy_gaps",
    "live_checks",
    "deviations",
    "fallbacks",
    "tokens",
    "decisions",
    "not_drawn",
)


class _Log:
    """Notes recorded while nodes are built, deduplicated in first-seen order."""

    def __init__(self) -> None:
        """Start with no notes."""
        self.notes: dict[str, list[str]] = {k: [] for k in NOTE_KINDS}

    def add(self, kind: str, line: str) -> str:
        """Record one line under kind and return it."""
        if line not in self.notes[kind]:
            self.notes[kind].append(line)
        return line

    def reset(self) -> None:
        """Forget everything recorded so far."""
        self.notes = {k: [] for k in NOTE_KINDS}


LOG = _Log()
LAST_NOTES: dict[str, list[str]] = (
    {}
)  # the notes write_sheet() wrote last (for the generator's .md)


def reset_notes() -> None:
    """Clear the collector and the issued-copy set (write_sheet() does this after writing)."""
    LOG.reset()
    _ISSUED.clear()


FALLBACKS = {  # "fallback: ..." / "token: ..." lines, printed under Tokens in the board .md
    "LOCK": (
        'fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file\'s local '
        "'icon / locked'"
    ),
    "ICONS": (
        "fallback: the per-set file holds only the local icons locked, arrow-up, arrow-down, close and "
        "drag-handle; every other CMP-019 glyph (check, chevron-down, search, info, warning, error, …) is a "
        "text glyph from NOTATION or primitives, named 'CMP-019 <name> (text glyph)'"
    ),
    "RING": (
        "token: the CMP-039 ring's radius (radius.control + 2 = 6 px, slice 1 §5.1, no token) binds the Tier-1 "
        "primitive radius.md (6 px; validator WARN)"
    ),
    "ICON_PX": "token: size.icon.sm (12) / size.icon.lg (20) are Tier-1 primitives (slice 1 §1, validator WARN)",
    "OPACITY": "token: opacity.disabled / opacity.scrim are Tier-1 primitives (slice 1 §1 names them; validator WARN)",
    "SPINNER": (
        "fallback: CMP-014's arc has no dashed / partial stroke in cvsheet: drawn as a full ring in "
        "color.border.default with a short arc rect in the indicator colour (a static frame of the spin)"
    ),
}
KIT_CHOICES = {  # each one is recorded in the sheet's deviations where it is used
    "specimen": (
        "Each state is a cell: the specimen on a color.surface.app plate (the matrix cells of slice 1 §1.1), "
        "its state caption under it in type.ui.caption color.text.secondary; cells sit in state rows led by "
        "a 120 px row label; a block is a color.surface.canvas card with a 1 px color.border.subtle edge"
    ),
    "focus": (
        "A focus ring is CMP-039's 2 px color.focus.ring (border.focus) rect, positioned 2 px outside the "
        "control on a flex wrapper 4 px larger than it (radius.md = radius.control + 2, FALLBACKS RING)"
    ),
    "t2": (
        "T2 (E09-D09 §2.2, slices 3-4 conventions 24 / 36-37; it supersedes slice 1 §3's trailing lock): the shape "
        "loses its enabled look (color.surface.raised fill, 1 px color.border.default hairline), the CMP-019 lock "
        "LEADS the full label, label and lock color.text.tertiary, the reason under it in type.ui.caption "
        "color.text.secondary (2a inline); icon-only controls carry a size.icon.sm lock badge bottom-right and a "
        "CMP-016 echo of the reason (2b); never color.text.disabled, never opacity.disabled on label, glyph or "
        "reason"
    ),
    "glyphs": "glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS ICONS)",
    "light": (
        "Board 10 is the only light board: the same construction as the dark blocks, drawn once; the light "
        "theme (semantic-light over semantic-dark) is applied through the file's theme at export"
    ),
    "compact": (
        "Every specimen is drawn at compact density (size.control.height = 24) unless the spec draws both "
        "densities; comfortable is 'not drawn — the text is binding' where it only re-points the heights"
    ),
    "page": (
        "mkcall4.py derives a page from the board name ('E05-D02 / NN …' -> 'E05-D02'); the sheet carries its "
        "page in sheet['page'] and the renderer passes --page '<page>' (live check)"
    ),
}
SRC_SECTIONS = {  # the conventions / exceptions / decisions sections of each slice (cited in the annotation column)
    "s1": "slice 1 §3 conventions 1-14, §5 exceptions, §6 decisions A-D, §8 components",
    "s2": "slice 2 §3 conventions, §4 exceptions, §5 decisions E (A-C carried), §6 components",
    "s3": "slice 3 §3 conventions 21-29, §5 exceptions, §6 decisions G, §7 components",
    "s4": "slice 4 §3 conventions 30-39, §5 exceptions, §6 decisions H, §7 components",
}


def _fallback(key: str) -> None:
    """Record FALLBACKS[key] under fallbacks."""
    LOG.add("fallbacks", FALLBACKS[key])


def _choice(key: str) -> None:
    """Record KIT_CHOICES[key] under deviations."""
    LOG.add("deviations", f"kit choice ({key}): {KIT_CHOICES[key]}")


def _live(line: str) -> None:
    """Record one live check for the drawer."""
    LOG.add("live_checks", line)


# --- Node builders (mirror cvsheet KEYS: keys cvsheet rejects raise here, as cvsheet would throw).
_KEYS = {
    "board": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "kids", "note"},
    "text": {
        "t",
        "name",
        "chars",
        "typo",
        "color",
        "w",
        "align",
        "x",
        "y",
        "abs",
        "hs",
        "vs",
        "alignSelf",
        "note",
    },
    "rect": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "ellipse": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "icon": {"t", "name", "icon", "color", "size", "x", "y", "abs", "alignSelf", "note"},
}
_TOKEN_OPTS = {
    "fill",
    "stroke",
    "strokeWidth",
    "radius",
    "pad",
    "padX",
    "padY",
    "padT",
    "padR",
    "padB",
    "padL",
    "gap",
    "rowGap",
    "colGap",
    "height",
    "width",
    "minW",
    "minH",
    "opacity",
    "shadow",
}


def node(t: str, name: str, **kw: Any) -> Node:
    """A cvsheet node of type t (None values dropped). Raises on keys cvsheet rejects, an empty name or a "/" in a
    name (section paths split on "/"); records every token it binds under LOG "tokens"."""
    if not name:
        raise ValueError(f"{t} node without a name")
    if "/" in name:
        raise ValueError(
            f"{t} {name!r}: '/' splits cvsheet section paths; Penpot names drop it (slice 1 §1.1)"
        )
    n: Node = {"t": t, "name": name}
    n.update({k: v for k, v in kw.items() if v is not None})
    extra = set(n) - _KEYS[t]
    if extra:
        raise KeyError(f"{t} {name!r}: keys cvsheet rejects: {sorted(extra)}")
    toks = [n.get(k) for k in ("typo", "color", "size")]
    toks += [v for k, v in (n.get("o") or {}).items() if k in _TOKEN_OPTS]
    for tk in toks:
        if isinstance(tk, str):
            LOG.add("tokens", tk)
    return n


def text(name: str, chars: str, typo: str, color: str, **kw: Any) -> Node:
    """A text node bound to a typography and a colour token; w= sets a fixed wrap width (auto height)."""
    if not str(chars).strip():
        raise ValueError(f"text {name!r} is empty")
    return node("text", name, chars=str(chars), typo=typo, color=color, **kw)


ICONS = frozenset(
    {"locked", "arrow-up", "arrow-down", "close", "drag-handle"}
)  # the per-set file's local icons


def icon(name: str, glyph: str, color: str, size: str = ICON, **kw: Any) -> Node:
    """One of the file's local icons (ICONS) with its stroke bound to color."""
    if glyph not in ICONS:
        _fallback("ICONS")
        raise ValueError(
            f"icon {glyph!r} is not in the per-set file ({sorted(ICONS)}): use tglyph() or primitives"
        )
    if size in (ICON_SM, ICON_LG):
        _fallback("ICON_PX")
    return node("icon", name, icon=glyph, color=color, size=size, **kw)


def rect(
    name: str,
    w: float,
    h: float,
    fill: str | None = None,
    o: dict[str, Any] | None = None,
    **kw: Any,
) -> Node:
    """A w x h rectangle, optionally filled with a colour token; o= adds other shape options."""
    opts = dict(o or {})
    if fill:
        opts["fill"] = fill
    return node("rect", name, w=w, h=h, o=opts or None, **kw)


def ellipse(name: str, w: float, h: float, o: dict[str, Any], **kw: Any) -> Node:
    """A w x h ellipse with shape options o."""
    return node("ellipse", name, w=w, h=h, o=o, **kw)


def unique_names(kids: Iterable[Node | None]) -> list[Node]:
    """kids without None, repeated sibling names suffixed " · 2", " · 3" (the validator rejects duplicates)."""
    seen: dict[str, int] = {}
    out = []
    for k in kids:
        if not k:
            continue
        seen[k["name"]] = seen.get(k["name"], 0) + 1
        out.append(k if seen[k["name"]] == 1 else dict(k, name=f"{k['name']} · {seen[k['name']]}"))
    return out


def box(
    name: str, kids: Iterable[Node | None] = (), o: dict[str, Any] | None = None, **kw: Any
) -> Node:
    """A board with cv.board options o and children (repeated child names made unique)."""
    return node("board", name, o=dict(o) if o else None, kids=unique_names(kids) or None, **kw)


def hbox(
    name: str, kids: Iterable[Node | None] = (), o: dict[str, Any] | None = None, **kw: Any
) -> Node:
    """A flex-row board (items centred unless o says otherwise)."""
    return box(name, kids, {"dir": "row", "align": "center", **(o or {})}, **kw)


def vbox(
    name: str, kids: Iterable[Node | None] = (), o: dict[str, Any] | None = None, **kw: Any
) -> Node:
    """A flex-column board, items at the start unless o says otherwise."""
    return box(name, kids, {"dir": "column", "align": "start", **(o or {})}, **kw)


def place(n: Node, x: float, y: float) -> Node:
    """n taken out of its flex parent's flow (abs) at x, y."""
    return dict(n, x=round(x), y=round(y), abs=True)


# --- Text metrics (estimates for widths, wraps and heights; Inter / JetBrains Mono), as e15d06kit / e42kit.
_FONT = {
    CAPTION: (11, 1.2, 1.0, False),
    BODY: (13, 1.4, 1.0, False),
    BODY_STRONG: (13, 1.4, 1.04, False),
    LABEL: (12, 1.2, 1.03, False),
    HEADING_SM: (14, 1.2, 1.06, False),
    HEADING_MD: (16, 1.2, 1.06, False),
    NUM_XS: (10, 1.2, 1.0, True),
    NUM_SM: (11, 1.2, 1.0, True),
    NUM_BASE: (13, 1.2, 1.0, True),
    NUM_MD: (14, 1.2, 1.0, True),
    HEADING_LG: (20, 1.2, 1.06, False),
}
_EM = dict(
    zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        (
            0.70,
            0.66,
            0.69,
            0.72,
            0.58,
            0.56,
            0.72,
            0.74,
            0.27,
            0.51,
            0.66,
            0.54,
            0.87,
            0.74,
            0.76,
            0.63,
            0.76,
            0.64,
            0.63,
            0.62,
            0.73,
            0.70,
            0.98,
            0.67,
            0.67,
            0.63,
        ),
        strict=True,
    )
)
_EM.update(
    zip(
        "abcdefghijklmnopqrstuvwxyz",
        (
            0.55,
            0.59,
            0.54,
            0.59,
            0.56,
            0.34,
            0.59,
            0.57,
            0.24,
            0.25,
            0.52,
            0.24,
            0.87,
            0.57,
            0.58,
            0.59,
            0.59,
            0.37,
            0.51,
            0.35,
            0.57,
            0.52,
            0.78,
            0.52,
            0.52,
            0.51,
        ),
        strict=True,
    )
)
_EM.update(
    {
        " ": 0.26,
        ".": 0.27,
        ",": 0.27,
        ":": 0.27,
        ";": 0.27,
        "%": 0.83,
        "(": 0.33,
        ")": 0.33,
        "+": 0.60,
        "−": 0.60,
        "-": 0.41,
        "—": 1.0,
        "–": 0.60,
        "·": 0.27,
        "/": 0.38,
        "…": 0.80,
        "?": 0.50,
        "'": 0.23,
        "’": 0.23,
        '"': 0.40,
        "#": 0.65,
        "1": 0.40,
        "×": 0.60,
        "→": 0.80,
        "@": 0.95,
        "≤": 0.60,
        "•": 0.45,
        "[": 0.30,
        "]": 0.30,
        "_": 0.50,
        "&": 0.70,
        "!": 0.27,
        "⚠": 0.90,
        "●": 0.60,
        "⋮": 0.30,
        "▸": 0.60,
        "↑": 0.60,
        "↓": 0.60,
        "←": 0.80,
        "✕": 0.60,
        "~": 0.60,
        "|": 0.24,
        "<": 0.60,
        ">": 0.60,
        "=": 0.60,
        "*": 0.45,
        "⋯": 0.80,
        "▾": 0.60,
        "∕": 0.38,
    }
)
TEXT_MARGIN = (
    1.05  # live labels run about 5 % wider than these metrics (E32-D02 and E08-D07 renders)
)


def text_w(chars: str, typo: str) -> float:
    """Estimated advance width in px of chars set in typo (mono: 0.6 em a character)."""
    size, _lh, weight, mono = _FONT.get(typo, _FONT[BODY])
    if mono:
        return round(len(chars) * 0.6 * size, 1)
    return round(
        sum(_EM.get(ch, 0.58 if ch.isdigit() else 0.60) for ch in chars) * size * weight, 1
    )


def text_lines(chars: str, typo: str, width: float) -> int:
    """Lines chars wraps to at width (greedy word wrap on the estimated metrics, TEXT_MARGIN included)."""
    lines, cur = 1, ""
    for word in str(chars).split():
        trial = f"{cur} {word}" if cur else word
        if cur and text_w(trial, typo) * TEXT_MARGIN > width:
            lines, cur = lines + 1, word
        else:
            cur = trial
    return lines


def text_h(typo: str, lines: int = 1) -> float:
    """Height in px of lines lines of typo (size × line height)."""
    size, lh, _w, _m = _FONT.get(typo, _FONT[BODY])
    return round(size * lh * lines, 1)


def _px(v: Any) -> int:
    """The px of a spacing / size token name in PX (0 for None or an unknown name)."""
    return PX.get(v, 0) if isinstance(v, str) else 0


def est_width(n: Node) -> float:
    """Estimated rendered width (fixed w wins; rows add children and gaps, columns take the widest)."""
    if n.get("w"):
        return float(n["w"])
    if n["t"] == "text":
        return text_w(n["chars"], n["typo"]) * TEXT_MARGIN
    if n["t"] == "icon":
        return float(PX.get(n.get("size", ICON), 16))
    if n["t"] != "board":
        return 16.0
    o, kids = n.get("o") or {}, [k for k in n.get("kids") or [] if not k.get("abs")]
    pad = 2 * _px(o.get("pad")) + 2 * _px(o.get("padX")) + _px(o.get("padL")) + _px(o.get("padR"))
    if o.get("dir") == "row":
        gap = _px(o.get("colGap") or o.get("gap"))
        return pad + sum(est_width(k) for k in kids) + gap * max(len(kids) - 1, 0)
    if o.get("dir") == "column":
        return pad + max((est_width(k) for k in kids), default=0.0)
    return max((float(k.get("x", 0)) + est_width(k) for k in n.get("kids") or []), default=0.0)


def est_height(n: Node) -> float:
    """Estimated rendered height (fixed h wins; columns stack, rows take the tallest child or pack wrapped lines)."""
    if n.get("h"):
        return float(n["h"])
    if n["t"] == "text":
        lines = text_lines(n["chars"], n["typo"], n["w"]) if n.get("w") else 1
        return text_h(n["typo"], lines)
    if n["t"] == "icon":
        return float(PX.get(n.get("size", ICON), 16))
    if n["t"] != "board":
        return 16.0
    o, kids = n.get("o") or {}, [k for k in n.get("kids") or [] if not k.get("abs")]
    pad = 2 * _px(o.get("pad")) + 2 * _px(o.get("padY")) + _px(o.get("padT")) + _px(o.get("padB"))
    if o.get("dir") == "column":
        gap = _px(o.get("rowGap") or o.get("gap"))
        return pad + sum(est_height(k) for k in kids) + gap * max(len(kids) - 1, 0)
    if o.get("dir") == "row" and o.get("wrap") == "wrap" and n.get("w"):
        inner = n["w"] - 2 * _px(o.get("pad")) - 2 * _px(o.get("padX"))
        cgap, rgap = _px(o.get("colGap") or o.get("gap")), _px(o.get("rowGap") or o.get("gap"))
        rows: list[float] = []
        used = 0.0
        for k in kids:
            kw_, kh = est_width(k), est_height(k)
            if not rows or used + cgap + kw_ > inner:
                rows.append(kh)
                used = kw_
            else:
                rows[-1] = max(rows[-1], kh)
                used += cgap + kw_
        return pad + sum(rows) + rgap * max(len(rows) - 1, 0)
    if o.get("dir") == "row":
        return pad + max((est_height(k) for k in kids), default=0.0)
    return max((float(k.get("y", 0)) + est_height(k) for k in n.get("kids") or []), default=0.0)


def walk(n: Node, path: str = "") -> Iterable[tuple[str, Node]]:
    """Yield (path, node) for n and every descendant."""
    p = f"{path}/{n['name']}" if path else n["name"]
    yield p, n
    for k in n.get("kids") or []:
        yield from walk(k, p)


# --- Reading the four frozen specs: raw lines, cleaned text, tables, CMP sections.
_LINES: dict[str, list[str]] = {}
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
TOKEN_RE = re.compile(
    r"\b(?:color|space|size|radius|type|opacity|elevation|border)\.[a-z0-9]+(?:[.-][a-z0-9]+)*\b"
)


def spec_bytes(doc: str) -> bytes:
    """Slice doc ("s1".."s4") as of SPEC_HEAD: the frozen copy in spec/ if present, else `git show`."""
    copy_, repo = DOCS[doc][0], DOCS[doc][1]
    if copy_.exists():
        return copy_.read_bytes()
    res = subprocess.run(
        ["git", "-C", str(WT), "show", f"{SPEC_HEAD}:{repo}"],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return res.stdout


def doc_lines(doc: str) -> list[str]:
    """The frozen copy of slice doc ("s1".."s4") as raw lines (index 0 = line 1)."""
    if doc not in _LINES:
        _LINES[doc] = spec_bytes(doc).decode("utf-8").splitlines()
    return _LINES[doc]


def clean(s: str) -> str:
    """s without Markdown markers (comments, `**`, backticks) and with runs of whitespace collapsed."""
    s = _COMMENT.sub("", s).replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


def span_text(doc: str, a: int, b: int) -> str:
    """Lines a..b (1-based, inclusive) of doc, cleaned and joined with spaces."""
    return clean(" ".join(doc_lines(doc)[a - 1 : b]))


def cite(doc: str, a: int, b: int | None = None) -> str:
    """'slice N Lnnn' or 'slice N Lnnn-mmm'."""
    return f"{DOCS[doc][3]} L{a}" + (f"-{b}" if b and b != a else "")


class Table(NamedTuple):
    """A Markdown table: its header line, the bold label above it ('' when none), header cells and body rows."""

    line: int
    label: str
    header: list[str]
    rows: list[tuple[int, list[str]]]


def _cells(raw: str) -> list[str]:
    """The cells of one table line, cleaned."""
    return [clean(c) for c in raw.strip().strip("|").split("|")]


def tables_in(doc: str, a: int, b: int) -> list[Table]:
    """Every table between lines a and b of doc, each with the nearest bold label within the 3 lines above it."""
    lines, out, i = doc_lines(doc), [], a
    while i <= b:
        if lines[i - 1].lstrip().startswith("|"):
            start = i
            block = []
            while i <= b and lines[i - 1].lstrip().startswith("|"):
                block.append((i, lines[i - 1]))
                i += 1
            label = ""
            for j in range(start - 1, max(a, start - 6) - 1, -1):
                if lines[j - 1].lstrip().startswith("**"):
                    m = re.match(
                        r"\s*\*\*(.+?)\*\*", " ".join(x.strip() for x in lines[j - 1 : start - 1])
                    )
                    label = clean(m.group(1)).rstrip(":") if m else ""
                    break
                if not lines[j - 1].strip() and j < start - 1:
                    break
            hdr = _cells(block[0][1])
            body = [(ln, _cells(t)) for ln, t in block[1:] if not re.fullmatch(r"[\s|:-]+", t)]
            out.append(Table(start, label, hdr, body))
        else:
            i += 1
    return out


class Cmp(NamedTuple):
    """One `### CMP-0xx · Name` section of a slice spec."""

    id: str
    name: str  # the heading's name ("DatePicker / DateRangePicker")
    doc: str  # s1..s4
    a: int  # heading line
    b: int  # last line of the section
    penpot: str  # the section's Penpot board / variant-set name ("CMP-047 · DatePicker"), "/"-free
    export: str  # its PENDING export path ("img/CMP-047-datepicker.png") or ""
    tables: tuple[Table, ...]


_PENPOT = re.compile(r"`(CMP-\d{3} · [^`/]+?)(?: — doc)?`")
_EXPORT = re.compile(r"`(img/CMP-\d{3}[^`]*\.png)`")


def _parse_cmps() -> dict[str, Cmp]:
    """Every CMP section of the four slices (the heading to the line before the next ## / ### heading)."""
    out: dict[str, Cmp] = {}
    for doc in DOCS:
        lines = doc_lines(doc)
        heads = [i for i, ln in enumerate(lines, 1) if re.match(r"#{2,3} ", ln)]
        for i, ln in enumerate(lines, 1):
            m = re.match(r"### (CMP-\d{3}) · (.+?)\s*$", ln)
            if not m:
                continue
            b = next((h for h in heads if h > i), len(lines) + 1) - 1
            raw = " ".join(x.strip() for x in lines[i - 1 : b])
            at = raw.find("PENDING")
            pm = _PENPOT.search(raw, max(at - 120, 0)) if at >= 0 else None
            em = _EXPORT.search(raw, max(at - 120, 0)) if at >= 0 else None
            pen, exp = (pm.group(1) if pm else ""), (em.group(1) if em else "")
            if not pen:
                pen = f"{m.group(1)} · {m.group(2).split(' / ')[0]}"
            if m.group(1) in out:
                raise ValueError(f"{m.group(1)} has two sections ({out[m.group(1)].doc}, {doc})")
            out[m.group(1)] = Cmp(
                m.group(1), m.group(2), doc, i, b, pen, exp, tuple(tables_in(doc, i, b))
            )
    return out


CMPS = _parse_cmps()


def cmp(cid: str) -> Cmp:
    """The CMP section cid ("CMP-001" or "001")."""
    key = cid if cid.startswith("CMP-") else f"CMP-{cid}"
    if key not in CMPS:
        raise KeyError(f"{key} has no section in the four slice specs")
    return CMPS[key]


def table(cid: str, label: str = "", header0: str = "") -> Table | None:
    """The first table of cid whose bold label starts with label (or whose first header cell is header0)."""
    for t in cmp(cid).tables:
        if (label and t.label.startswith(label)) or (
            header0 and t.header and t.header[0] == header0
        ):
            return t
    return None


def axes(cid: str) -> dict[str, tuple[list[str], str]]:
    """cid's Axis table: {axis: ([values], default)} (values split on ", "; {} when the section has none)."""
    t = table(cid, header0="Axis")
    if not t:
        return {}
    return {
        r[0]: ([v.strip() for v in r[1].split(",") if v.strip()], r[2] if len(r) > 2 else "")
        for _ln, r in t.rows
        if len(r) >= 2
    }


def states(cid: str) -> list[str]:
    """cid's State axis values (in the spec's order; [] when it has none)."""
    return axes(cid).get("State", ([], ""))[0]


def cells(cid: str) -> list[tuple[int, list[str]]]:
    """The rows of cid's cell table (slices 3-4, header "Cell"): (line, [cell, axes, what it shows]); [] when the
    section states its cells in prose (variants_states())."""
    t = table(cid, header0="Cell")
    return t.rows if t else []


def para(cid: str, label: str) -> tuple[int, str]:
    """(line, cleaned text) of the paragraph of cid holding **label (from that marker to the next blank line, a table
    or a list); (0, '') when absent."""
    c = cmp(cid)
    lines = doc_lines(c.doc)
    for i in range(c.a, c.b + 1):
        k = lines[i - 1].find(f"**{label}")
        if k >= 0:
            j = i
            while (
                j < c.b and lines[j].strip() and not lines[j].lstrip().startswith(("|", "- ", "#"))
            ):
                j += 1
            return i, clean(lines[i - 1][k:] + " " + " ".join(lines[i:j]))
    return 0, ""


def variants_states(cid: str) -> str:
    """cid's "Variants × States (…)" paragraph (cleaned; slices 3-4; a table follows it or it is prose)."""
    return para(cid, "Variants × States")[1]


def not_drawn(cid: str) -> str:
    """cid's "Not drawn:" text (to the end of its paragraph) without its label ('' when the section has none)."""
    _ln, t = para(cid, "Not drawn")
    return t.split(":", 1)[1].strip() if t else ""


def drawn(cid: str) -> str:
    """cid's "Drawn:" line (slices 1-2; '' when absent)."""
    _ln, t = para(cid, "Drawn:")
    return t.split(":", 1)[1].strip() if t else ""


def tokens(cid: str) -> list[str]:
    """Every token name cid's section cites that exists in token-sync.json, in first-cited order."""
    have = token_table()
    c = cmp(cid)
    out: list[str] = []
    for tk in TOKEN_RE.findall(span_text(c.doc, c.a, c.b)):
        if tk in have and tk not in out:
            out.append(tk)
    return out


def missing_tokens(cid: str) -> list[str]:
    """Token-shaped names cid's section cites that the file does not hold (PROPOSED or catalogue names)."""
    have = token_table()
    c = cmp(cid)
    out: list[str] = []
    for tk in TOKEN_RE.findall(span_text(c.doc, c.a, c.b)):
        if tk not in have and tk not in out and not tk.endswith((".tsx", ".ts", ".md")):
            out.append(tk)
    return out


_TOKENS: dict[str, set[tuple[str, str]]] = {}


def token_table() -> dict[str, set[tuple[str, str]]]:
    """token-sync.json as {name: {(set, type)}}."""
    if not _TOKENS:
        for s, n, t, _v in json.loads(TOKENS_FILE.read_text(encoding="utf-8")):
            _TOKENS.setdefault(n, set()).add((s, t))
    return _TOKENS


# --- Owner decisions (PROPOSED: open in the slice's "Decisions for the owner" section) and copy issuance.
def _parse_decisions() -> dict[str, dict[str, int]]:
    """{slice: {id: line}}: every `- **X9 …` item inside each slice's "## N. Decisions for the owner" section."""
    out: dict[str, dict[str, int]] = {}
    for doc in DOCS:
        lines = doc_lines(doc)
        a = next(
            i for i, ln in enumerate(lines, 1) if re.match(r"## \d+\. Decisions for the owner", ln)
        )
        b = next(i for i, ln in enumerate(lines, 1) if i > a and re.match(r"## \d+\. ", ln)) - 1
        reg: dict[str, int] = {}
        for i in range(a, b + 1):
            m = re.match(r"- \*\*([A-H]\d+)\b", lines[i - 1])
            if m and m.group(1) not in reg:
                reg[m.group(1)] = i
        out[doc] = reg
    return out


DECISIONS = _parse_decisions()


def decision(ref: str, doc: str) -> tuple[str, str, int]:
    """Resolve a decision ref ("D13" in slice doc, or "s1:D13" in another slice) to (slice, id, line)."""
    d, i = ref.split(":", 1) if ":" in ref else (doc, ref)
    if d not in DECISIONS or i not in DECISIONS[d]:
        raise ValueError(
            f"decision {ref!r}: not an item of {DOCS.get(d, ('', '', '', d))[3]}'s decisions section"
        )
    return d, i, DECISIONS[d][i]


NOTATION = {
    "·",
    "—",
    "–",
    "•",
    ",",
    ".",
    ";",
    "×",
    "⚠",
    "⋮",
    "▾",
    "▴",
    "▸",
    "◂",
    "●",
    "○",
    "↑",
    "↓",
    "←",
    "→",
    "%",
    "(",
    ")",
    "+",
    "−",
    "✓",
    "✕",
    "…",
    "ⓘ",
    "⊘",
    "⧉",
    "⌕",
    "?",
    "!",
    "/",
    "|",
    "-",
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
}  # text glyphs and lone digits a specimen may draw without a source line
_ISSUED: set[str] = set()


def found(chars: str, doc: str, a: int = 1, b: int | None = None) -> bool:
    """True when chars occurs (whitespace-normalised, Markdown markers dropped) in lines a..b of doc."""
    hay = span_text(doc, a, b or len(doc_lines(doc)))
    return clean(chars) in hay


def say(chars: str, cid: str | None = None, *, doc: str | None = None) -> str:
    """chars, checked against the spec: in cid's section first, else anywhere in its slice (doc= another slice);
    recorded as issued copy (write_sheet() refuses specimen texts that were not) and under copy_keys. Raises when the
    string is not in the pinned text."""
    if chars in NOTATION:
        return chars
    if cid:
        c = cmp(cid)
        if found(chars, c.doc, c.a, c.b):
            LOG.add("copy_keys", f"{chars!r} — {c.id} {cite(c.doc, c.a, c.b)}")
            _ISSUED.add(chars)
            return chars
        doc = doc or c.doc
    docs = [doc] if doc else list(DOCS)
    for d in docs:
        if found(chars, d):
            LOG.add("copy_keys", f"{chars!r} — {DOCS[d][3]} (outside the CMP section)")
            _ISSUED.add(chars)
            return chars
    raise ValueError(
        f"say({chars!r}): not in {cid or ''} / {docs}: a specimen draws only the specs' words"
    )


def gap(line: str) -> None:
    """Record a copy gap (a string the board needs and the spec does not give: never drawn invented)."""
    LOG.add("copy_gaps", line)


# --- Shared pieces: glyphs, the lock, captions, the focus ring, T2, tooltip, pill, spinner, button.
def tglyph(
    ch: str, color: str = TEXT_2, typo: str = BODY, name: str | None = None, **kw: Any
) -> Node:
    """A text glyph from NOTATION (✓ ▾ ⚠ × ● …), named 'glyph <ch>' unless name= says the CMP-019 icon it stands for."""
    if ch not in NOTATION:
        raise ValueError(f"text glyph {ch!r} is not in NOTATION")
    _choice("glyphs")
    return text(name or f"glyph {ch}", ch, typo, color, **kw)


def lock(size: str = ICON, color: str = TEXT_3, name: str = "CMP-019 lock · Not available") -> Node:
    """CMP-019 `lock` (decorative=false, "Not available"): the file's local icon / locked (T2: color.text.tertiary)."""
    _fallback("LOCK")
    return icon(name, "locked", color, size=size)


def caption(
    chars: str,
    w: int | None = None,
    *,
    color: str = TEXT_2,
    typo: str = CAPTION,
    name: str = "caption",
) -> Node:
    """Board chrome: a caption in type.ui.caption (fixed width w wraps it; long captions must get one)."""
    if w is None and text_w(chars, typo) > 360:
        raise ValueError(
            f"caption {chars[:40]!r}…: give a long caption a fixed width (it wraps only then)"
        )
    return text(name, chars, typo, color, w=w)


def focus_ring(n: Node, *, radius: str = R_RING, name: str = "focus-ring") -> Node:
    """n with CMP-039's ring: a flex wrapper 4 px larger than n (n centred, in flow) holding an abs rect stroked 2 px
    color.focus.ring (border.focus) at its edge, i.e. 2 px outside n (slice 1 conventions 3; KIT_CHOICES focus).
    """
    _choice("focus")
    if radius == R_RING:
        _fallback("RING")
    w, h = round(est_width(n)) + 4, round(est_height(n)) + 4
    ring = place(
        rect(
            "ring",
            w,
            h,
            o={
                "stroke": FOCUS_RING,
                "strokeWidth": FOCUS_W,
                "radius": radius,
                "strokeAlign": "inner",
            },
        ),
        0,
        0,
    )
    return hbox(name, [n, ring], {"justify": "center"}, w=w, h=h)


T2_SHAPE = {
    "fill": RAISED,
    "stroke": BORDER_DEFAULT,
    "strokeWidth": HAIRLINE,
}  # E09-D09 §2.2: the stripped shape


def t2_label(
    label: str, *, typo: str = LABEL, lock_size: str = ICON, name: str = "T2 label"
) -> Node:
    """The T2 label row: the CMP-019 lock LEADING the full label, both color.text.tertiary (E09-D09 §2.2)."""
    _choice("t2")
    return hbox(name, [lock(lock_size), text("label", label, typo, TEXT_3)], {"gap": INSET_XS})


def t2_reason(reason: str, *, w: int | None = None, name: str = "T2 reason") -> Node:
    """The 2a inline reason: type.ui.caption color.text.secondary (never disabled / dimmed). reason must be a say()'d
    rbac.* or registered state string."""
    _choice("t2")
    return text(name, reason, CAPTION, TEXT_2, w=w)


def t2_inline(control: Node, reason: str, *, w: int | None = None, name: str = "T2 2a") -> Node:
    """A gated control with its 2a reason under it (stack.xs apart)."""
    return vbox(name, [control, t2_reason(reason, w=w)], {"gap": STACK_XS})


def lock_badge(control: Node, *, name: str = "T2 2b lock badge") -> Node:
    """An icon-only control (fixed w / h) with the size.icon.sm lock badge in its bottom-right corner (abs; the
    control never grows; slice 1 §5.2, conventions 24 2b)."""
    _choice("t2")
    w, h = round(est_width(control)), round(est_height(control))
    badge = place(lock(ICON_SM), w - PX[ICON_SM], h - PX[ICON_SM])
    return hbox(name, [control, badge], w=w, h=h)


def tooltip(chars: str, *, w: int | None = None, name: str = "CMP-016 tooltip") -> Node:
    """A CMP-016 bubble: color.surface.overlay, 1 px color.border.default, radius.card, space.inset.sm x inset.xs,
    type.ui.caption color.text.primary (board 09 owns CMP-016's own specimen; this is the shared echo).
    """
    return hbox(
        name,
        [text("content", chars, CAPTION, TEXT_1, w=w)],
        {
            "fill": OVERLAY,
            "stroke": BORDER_DEFAULT,
            "strokeWidth": HAIRLINE,
            "radius": R_CARD,
            "padX": INSET_SM,
            "padY": INSET_XS,
            "shadow": E_POPOVER,
        },
    )


def pill(
    chars: str,
    *,
    ink: str = TEXT_2,
    stroke: str | None = BORDER_DEFAULT,
    fill: str | None = None,
    typo: str = CAPTION,
    name: str = "pill",
    w: int | None = None,
) -> Node:
    """An outlined (or filled) radius.badge pill holding one caption."""
    o: dict[str, Any] = {"radius": R_BADGE, "padX": INSET_SM, "padY": INSET_XS}
    if stroke:
        o.update(stroke=stroke, strokeWidth=HAIRLINE)
    if fill:
        o["fill"] = fill
    return hbox(name, [text("label", chars, typo, ink, w=w)], o)


def spinner(px: int = 16, color: str = ACTION["primary"], *, name: str = "CMP-014 spinner") -> Node:
    """CMP-014 as a static frame: a ring in color.border.default (border.thick) with a short arc in color
    (FALLBACKS SPINNER)."""
    _fallback("SPINNER")
    ring = place(ellipse("track", px, px, {"stroke": BORDER_DEFAULT, "strokeWidth": THICK}), 0, 0)
    arc = place(rect("arc", max(4, px // 3), 2, color, o={"radius": R_CONTROL}), px // 3, 0)
    return hbox(name, [ring, arc], w=px, h=px)


BUTTON_LOOK = {  # variant -> (fill, ink, hover fill, active fill, arrow icon); slice 1 CMP-001 token mapping, A12
    "primary": (
        ACTION["primary"],
        TEXT_ON_ACTION,
        ACTION["primary.hover"],
        ACTION["primary.active"],
        None,
    ),
    "secondary": (ACTION["secondary"], TEXT_1, ACTION["secondary.hover"], SELECTED, None),
    "ghost": (None, TEXT_2, HOVER, SELECTED, None),
    "danger": (
        STATUS["danger.default"],
        TEXT_ON_ACTION,
        STATUS["danger.default"],
        STATUS["danger.default"],
        None,
    ),
    "buy": (BUY, TEXT_INVERSE, BUY_HOVER, BUY, "arrow-up"),
    "sell": (SELL, TEXT_INVERSE, SELL_HOVER, SELL, "arrow-down"),
}
BUTTON_SIZE = {
    "sm": (INSET_SM, INSET_XS, LABEL),
    "md": (BTN_PADX, INSET_XS, BODY_STRONG),
    "lg": (INSET_LG, INSET_SM, HEADING_SM),
}  # size -> (padX, gap, typo): slice 1 CMP-001 token mapping


def button(
    label: str,
    variant: str = "secondary",
    state: str = "default",
    *,
    size: str = "md",
    reason: str | None = None,
    name: str | None = None,
) -> Node:
    """A CMP-001 Button composed from primitives (states: default, hover, focus-visible, active, disabled,
    disabled-with-reason (T2; reason= adds the 2a line), loading). label must be say()'d by the caller.
    """
    fill, ink, hov, act, arrow = BUTTON_LOOK[variant]
    padx, gap_, typo = BUTTON_SIZE[size]
    o: dict[str, Any] = {
        "padX": padx,
        "gap": gap_,
        "radius": R_CONTROL,
        "height": CONTROL_H,
        "justify": "center",
    }
    if state == "hover":
        fill = hov
        ink = TEXT_1 if variant == "ghost" else ink
    elif state == "active":
        fill = act
        ink = TEXT_1 if variant in ("secondary", "ghost") else ink
    t2 = state == "disabled-with-reason"
    kids: list[Node | None] = []
    if t2:
        o.update(T2_SHAPE)
        kids.append(lock())
        ink = TEXT_3
    elif fill:
        o["fill"] = fill
    if arrow:
        kids.append(icon(f"CMP-019 {arrow}", arrow, ink))
    kids.append(text("label", label, typo, ink))
    if state == "loading":
        kids.append(spinner(PX[ICON], ink, name="CMP-014 spinner-inline"))
    if state == "disabled":
        o["opacity"] = OP_DISABLED
        _fallback("OPACITY")
    b = hbox(
        name or f"CMP-001 button · {variant} · {state}" + (" · T2" if t2 else ""),
        kids,
        o,
        h=CONTROL_PX,
    )
    if state == "focus-visible":
        b = focus_ring(b)
    if t2 and reason:
        b = t2_inline(b, reason)
    return b


# --- The ten boards (brief-kit.md table; orchestrator ruling 2026-10-27 08:11Z: the board cap applies).
class Bd(NamedTuple):
    """One board: NN, slug, name, its CMPs (empty for 10: any CMP of any slice), slice, page, theme, export."""

    nn: int
    slug: str
    name: str
    cmps: tuple[str, ...]
    doc: str
    page: str
    theme: str
    export: str


def _bd(nn: int, slug: str, nums: str, doc: str, theme: str = "dark") -> Bd:
    """A Bd from the brief's row (nums: the CMP numbers, space-separated)."""
    ids = tuple(f"CMP-{x}" for x in nums.split())
    return Bd(
        nn,
        slug,
        f"{SET} / {nn:02d} {slug}",
        ids,
        doc,
        PAGES[doc],
        theme,
        f"docs/design/E05/img/{SET}-{nn:02d}-{slug}.png",
    )


BOARDS = {
    b.nn: b
    for b in (
        _bd(1, "actions", "001 002 003 004", "s1"),
        _bd(2, "selection-and-primitives", "005 006 010 014 019 031 039", "s1"),
        _bd(3, "tags-badges-avatars", "011 012 013 025 032 037", "s2"),
        _bd(4, "text-and-dividers", "018 020 021 024 030 033", "s2"),
        _bd(5, "text-inputs", "007 008 034 040 054 065", "s3"),
        _bd(6, "pickers-and-gates", "009 047 048 079", "s3"),
        _bd(7, "table", "049", "s3"),
        _bd(8, "feedback-states", "015 023 026 027 028 029 038 045 089 090 091", "s4"),
        _bd(9, "overlays", "016 017 041 043 044 046", "s4"),
        _bd(10, "light-composite", "", "s4", "light"),
    )
}
PAIRS = (
    ("01", "02"),
    ("03", "04"),
    ("05", "06"),
    ("07", "10"),
    ("08", "09"),
)  # the parallel board authors
BRIEF = KIT_DIR / "brief-kit.md"


def board_name(nn: int) -> str:
    """The board's name, "E05-D02 / NN slug" (nn=0: the kit's self-test board)."""
    return f"{SET} / 00 selftest" if nn == 0 else BOARDS[nn].name


def stem(nn: int) -> str:
    """The sheet's file stem, NN-<slug>."""
    return f"{nn:02d}-{BOARDS[nn].slug}" if nn else "00-selftest"


def page_of(nn: int) -> str:
    """The page board nn is drawn on (the self-test: slice 1's page, never drawn)."""
    return BOARDS[nn].page if nn else PAGES["s1"]


def grid_xy(nn: int) -> tuple[int, int]:
    """Board NN's position on its page: the boards of one page side by side, PITCH_X apart, in NN order; the
    self-test sits above the grid at y = -PITCH_Y (never drawn)."""
    if nn == 0:
        return 0, -PITCH_Y
    same = [b.nn for b in BOARDS.values() if b.page == BOARDS[nn].page]
    return same.index(nn) * PITCH_X, 0


def export_path(nn: int) -> str:
    """The board's export path (the self-test's is the kit's own)."""
    return f"docs/design/E05/img/{SET}-00-selftest.png" if nn == 0 else BOARDS[nn].export


# --- Specimen cells, state rows, blocks, stamps.
_META: dict[str, dict[str, Any]] = (
    {}
)  # block name -> its facts (board() reads them; reset by write_sheet)


def cell(state: str, specimen: Node, *, note: str | None = None, name: str | None = None) -> Node:
    """One state cell: the specimen on a color.surface.app plate (inset.md, radius.control) and its caption (the
    state, then " — note") under it. Texts inside the plate must be say()'d (write_sheet checks)."""
    _choice("specimen")
    plate = hbox(
        "specimen",
        [specimen],
        {"fill": APP, "pad": INSET_MD, "radius": R_CONTROL},
        h=None if _has_text(specimen) else round(est_height(specimen)) + 2 * PX[INSET_MD],
    )
    w = max(round(est_width(plate)), CELL_CAPTION_W)
    cap = text("state", state + (f" — {note}" if note else ""), CAPTION, TEXT_2, w=w)
    return vbox(name or f"cell · {state}", [plate, cap], {"gap": STACK_XS})


def state_row(label: str, cells_: Iterable[Node], *, name: str | None = None) -> Node:
    """A row of cells led by a 120 px label (type.ui.label, color.text.secondary): one variant, size or axis value."""
    lab = text("row label", label, LABEL, TEXT_2, w=ROW_LABEL_W)
    return hbox(name or f"row · {label}", [lab, *cells_], {"align": "start", "gap": INSET_LG})


def stamps(doc: str, proposed: Iterable[str] = (), ruled: Iterable[str] = ()) -> list[Node]:
    """The block's stamp pills: "PROPOSED · D13, s3:G23 (owner approval pending)" (each id an item of the slice's
    decisions section; "sN:ID" for another slice) and "RULED · <ref>" (each ref a string the slice text holds, e.g.
    "E13-D04's BQ-16")."""
    p, r = list(proposed), list(ruled)
    out: list[Node] = []
    if p:
        refs = []
        for x in p:
            d, i, ln = decision(x, doc)
            refs.append(f"{i}" if d == doc else f"{DOCS[d][3]} {i}")
            LOG.add("decisions", f"PROPOSED · {DOCS[d][3]} {i} ({cite(d, ln)})")
        out.append(
            pill(
                f"PROPOSED · {', '.join(refs)} (owner approval pending)",
                ink=STATUS["warning.strong"],
                stroke=STATUS["warning.strong"],
                typo=LABEL,
                name="stamp PROPOSED",
            )
        )
    if r:
        for x in r:
            if not found(x, doc):
                raise ValueError(f"stamps(): RULED ref {x!r} is not in {DOCS[doc][3]}'s text")
            LOG.add("decisions", f"RULED · {x} ({DOCS[doc][3]})")
        out.append(pill(f"RULED · {'; '.join(r)}", ink=TEXT_2, typo=LABEL, name="stamp RULED"))
    return out


def block(
    cid: str,
    rows: Iterable[Node],
    *,
    states: Iterable[str] = (),
    not_drawn: Iterable[str] = (),
    proposed: Iterable[str] = (),
    ruled: Iterable[str] = (),
    toks: Iterable[str] | None = None,
    note: str | None = None,
    w: int | None = None,
    light: bool = False,
) -> Node:
    """A component's specimen block: a color.surface.canvas card (1 px color.border.subtle, radius.card, inset.lg)
    holding its title (the spec's Penpot name), the caption "CMP-0xx · <slice> §… Lnnn-mmm · tokens: …" (toks
    default: tokens(cid)), its stamps, then the state rows. states / not_drawn feed the annotation column ("not
    drawn — the text is binding")."""
    c = cmp(cid)
    rs = list(rows)
    if not rs:
        raise ValueError(f"block {cid}: no rows")
    inner = max([round(est_width(r)) for r in rs] + [440])
    tk = list(toks) if toks is not None else tokens(cid)
    cap = f"{c.id} · {cite(c.doc, c.a, c.b)} · tokens: {', '.join(tk)}"
    head = [
        text("title", c.penpot + (" (light)" if light else ""), HEADING_SM, TEXT_1),
        caption(cap, inner, name="source and tokens"),
    ]
    if note:
        head.append(caption(note, inner, name="note"))
    st = stamps(c.doc, proposed, ruled)
    if st:
        head.append(hbox("stamps", st, {"gap": INSET_SM, "wrap": "wrap"}, w=inner))
    o = {
        "fill": CANVAS,
        "stroke": BORDER_SUBTLE,
        "strokeWidth": HAIRLINE,
        "radius": R_CARD,
        "pad": INSET_LG,
        "gap": STACK_MD,
    }
    n = vbox(
        f"block · {c.id}" + (" · light" if light else ""),
        [*head, *rs],
        o,
        w=w or inner + 2 * PX[INSET_LG],
    )
    nd = [x for x in not_drawn if x]
    for x in nd:
        LOG.add(
            "not_drawn", f"{c.id}: {x} — not drawn, the text is binding ({cite(c.doc, c.a, c.b)})"
        )
    _META[n["name"]] = {
        "cid": c.id,
        "doc": c.doc,
        "states": list(states),
        "not_drawn": nd,
        "light": light,
        "proposed": list(proposed),
        "ruled": list(ruled),
    }
    return n


# --- The annotation column and the board.
ANN_ORDER = ("Sources", "Stamps", "Not drawn — the text is binding", "Kit choices", "Notes")
ROOT_O = {"dir": "column", "align": "start", "fill": APP, "pad": INSET_LG, "gap": INSET_LG}


def annotation(
    metas: list[dict[str, Any]],
    *,
    sources: Iterable[str] = (),
    notes: Iterable[str] = (),
    not_drawn: Iterable[str] = (),
) -> Node:
    """The board's 400 px annotation column (color.surface.canvas card): Sources (each block's CMP section and its
    slice's conventions, then sources=), Stamps (each block's PROPOSED / RULED), Not drawn (each block's list, then
    not_drawn=), Kit choices (the keys used) and Notes (notes=)."""
    src = [
        f"{m['cid']} {CMPS[m['cid']].penpot}: {cite(m['doc'], CMPS[m['cid']].a, CMPS[m['cid']].b)}"
        for m in metas
    ]
    docs = []
    for m in metas:
        if m["doc"] not in docs:
            docs.append(m["doc"])
    src += [f"{SRC_SECTIONS[d]} ({DOCS[d][1]} @ {SPEC_HEAD})" for d in docs]
    src += [
        "E09-D09 §2.2 T2 governs every gated cell (slice 1 §3 note; slices 3-4 conventions 24, 36-37)"
    ]
    src += list(sources)
    st = []
    for m in metas:
        if m["proposed"]:
            st.append(
                f"{m['cid']}: PROPOSED · " + ", ".join(m["proposed"]) + " (owner approval pending)"
            )
        if m["ruled"]:
            st.append(f"{m['cid']}: RULED · " + "; ".join(m["ruled"]))
    nd = [f"{m['cid']}: {x}" for m in metas for x in m["not_drawn"]] + list(not_drawn)
    used = sorted(
        {
            ln.split("(", 1)[1].split(")", 1)[0]
            for ln in LOG.notes["deviations"]
            if ln.startswith("kit choice (")
        }
    )
    vals = {
        "Sources": src,
        "Stamps": st or ["— none on this board"],
        "Not drawn — the text is binding": nd or ["— every state class the spec names is drawn"],
        "Kit choices": [", ".join(used)] if used else [],
        "Notes": list(notes),
    }
    kids: list[Node] = [text("title", "Annotations", HEADING_SM, TEXT_1)]
    for i, lab in enumerate(ANN_ORDER, 1):
        lines = [x for x in vals[lab] if x]
        if not lines:
            continue
        bk = [text("label", lab, LABEL, TEXT_2)] + [
            text(f"value-{j}", x, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, x in enumerate(lines, 1)
        ]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    return vbox(
        "annotation",
        kids,
        {
            "gap": STACK_MD,
            "pad": INSET_LG,
            "radius": R_CARD,
            "fill": CANVAS,
            "stroke": BORDER_SUBTLE,
            "strokeWidth": HAIRLINE,
        },
        w=ANN_W,
    )


def board(
    nn: int,
    blocks: Iterable[Node],
    *,
    source: str,
    notes: Iterable[str] = (),
    not_drawn: Iterable[str] = (),
    sources: Iterable[str] = (),
    cols: int | None = None,
) -> dict[str, Any]:
    """A board: the root (its name, its page position, ROOT_O: flex column on color.surface.app, inset.lg padding and
    gap, height hugging) holding the head (name, "Source: …", theme and page lines), the body (the blocks in a
    wrapping grid, cols per row or as many as fit, beside the annotation column) and the footer "file … · page … ·
    board NN · r1". Refuses a board whose blocks are not exactly its CMPs (board 10: at least one block of every
    slice, every block light=True)."""
    bs = list(blocks)
    metas = []
    for b in bs:
        m = _META.get(re.sub(r" · \d+$", "", b["name"]))
        if m is None:
            raise ValueError(f"board {nn:02d}: {b['name']!r} was not built by block()")
        metas.append(m)
    got = [m["cid"] for m in metas]
    if nn and BOARDS[nn].cmps:
        want = BOARDS[nn].cmps
        if sorted(set(got)) != sorted(want):
            raise ValueError(
                f"board {nn:02d} blocks differ from its CMPs: missing {sorted(set(want) - set(got))}, "
                f"extra {sorted(set(got) - set(want))}"
            )
        if got != list(want):
            LOG.add(
                "deviations",
                f"board {nn:02d} draws its blocks in another order than the brief's row",
            )
    if nn and BOARDS[nn].theme == "light":
        _choice("light")
        if {m["doc"] for m in metas} != set(DOCS) or not all(m["light"] for m in metas):
            raise ValueError(
                "board 10: every block light=True, and at least one block of each of the four slices"
            )
    theme = BOARDS[nn].theme if nn else "dark"
    gap = PX[INSET_LG]
    widths = [round(est_width(b)) for b in bs]
    per = cols or max(1, min(len(bs), (GRID_MAX_W + gap) // (max(widths, default=1) + gap)))
    rows = [widths[i : i + per] for i in range(0, len(widths), per)] or [[0]]
    gw = max(sum(r) + gap * (len(r) - 1) for r in rows)
    if gw > GRID_MAX_W:
        raise ValueError(
            f"board {nn:02d}: the grid is {gw} px wide (> {GRID_MAX_W}): fewer blocks per row"
        )
    grid = hbox(
        "grid", bs, {"wrap": "wrap", "colGap": INSET_LG, "rowGap": INSET_LG, "align": "start"}, w=gw
    )
    ann = annotation(metas, sources=sources, notes=notes, not_drawn=not_drawn)
    body = hbox("body", [grid, ann], {"align": "start", "gap": INSET_LG})
    bw = gw + gap + ANN_W
    head = vbox(
        "head",
        [
            text("title", board_name(nn), HEADING_MD, TEXT_1),
            text("source", f"Source: {source}", CAPTION, TEXT_2, w=bw),
            text(
                "theme",
                f"Theme: {theme} ("
                + (
                    "the only light board: semantic-light applied through the file's light "
                    "theme at export"
                    if theme == "light"
                    else "tokens by name"
                )
                + "); compact density unless a block says otherwise",
                CAPTION,
                TEXT_2,
                w=bw,
            ),
            text("page", f"File {FILE} · page {page_of(nn)}", CAPTION, TEXT_2, w=bw),
        ],
        {"gap": STACK_XS},
    )
    foot = text(
        "footer", f"file {FILE} · page {page_of(nn)} · board {nn:02d} · {REV}", CAPTION, TEXT_3
    )
    kids = [head, body, foot]
    h = est_height(box("probe", kids, ROOT_O))
    if h > PITCH_Y - 40:
        raise ValueError(
            f"board {nn:02d} is about {h:.0f} px tall (> {PITCH_Y - 40}): more blocks per row"
        )
    _choice("page")
    _live(
        f"render on page '{page_of(nn)}' (mkcall4.py … --page '{page_of(nn)}'; its default would be '{SET}')"
    )
    _live(
        f"root '{board_name(nn)}': hugs its content (about {bw + 2 * ROOT_PAD} x {h:.0f} px estimated)"
    )
    x, y = grid_xy(nn)
    root = {"name": board_name(nn), "w": bw + 2 * ROOT_PAD, "x": x, "y": y, "o": dict(ROOT_O)}
    return {
        "board": root,
        "kids": kids,
        "export": export_path(nn),
        "nn": nn,
        "page": page_of(nn),
        "cmps": got,
        "est_h": round(h),
    }


# --- Sections (the E27-D02 / E15-D06 packer: a board's prefix of whole kids per section, the rest under its path).
def _size(section: dict[str, Any]) -> int:
    """A section's size in bytes as the validator measures it (json.dumps defaults)."""
    return len(json.dumps(section))


_MEMO: dict[tuple[int, str, int], list[dict[str, Any]]] = {}


def _pack(n: Node, path: str, room: int, budget: int) -> tuple[Node | None, list[tuple[str, Node]]]:
    """n pruned to at most room bytes (the bare board, its longest prefix of whole kids, and the next kid packed the
    same way when that needs fewer sections), plus the cut parts as (parent path, node) in render order.
    """
    if len(json.dumps(n)) <= room:
        return n, []
    if n["t"] != "board":
        return None, []
    bare = {k: v for k, v in n.items() if k != "kids"}
    if len(json.dumps(bare)) > room:
        return None, []
    me = f"{path}/{n['name']}" if path else n["name"]
    kids = list(n.get("kids") or [])
    kept: list[Node] = []
    while (
        len(kept) < len(kids) and len(json.dumps(dict(bare, kids=[*kept, kids[len(kept)]]))) <= room
    ):
        kept.append(kids[len(kept)])
    j = len(kept)
    if j == len(kids):
        return dict(bare, kids=kept), []
    shallow = [(me, k) for k in kids[j:]]
    used = len(json.dumps(dict(bare, kids=[*kept, {}]))) - 2
    part, rest = _pack(kids[j], me, room - used, budget)
    if part is not None:
        deep = rest + [(me, k) for k in kids[j + 1 :]]
        if _cost(deep, budget) < _cost(shallow, budget):
            return dict(bare, kids=[*kept, part]), deep
    return (dict(bare, kids=kept) if kept else bare), shallow


def _cost(cut: list[tuple[str, Node]], budget: int) -> int:
    """How many sections the cut parts need."""
    return sum(len(_emit(k, parent, budget)) for parent, k in cut)


def _emit(n: Node, into: str, budget: int) -> list[dict[str, Any]]:
    """The sections that render n under into, in render order; a leaf is one section."""
    key = (id(n), into, budget)
    if key not in _MEMO:
        if n["t"] != "board":
            out = [{"into": into, "node": n}]
        else:
            part, cut = _pack(n, into, budget - (_size({"into": into, "node": {}}) - 2), budget)
            if part is None:
                raise ValueError(f"node {n['name']!r}: not even its bare board fits {budget} bytes")
            out = [{"into": into, "node": part}]
            for parent, kid in cut:
                out += _emit(kid, parent, budget)
        _MEMO[key] = out
    return _MEMO[key]


def check_paths(sections: list[dict[str, Any]]) -> None:
    """Resolve every section's into path the way cvsheet's S.at does and replay S.put; raise on one that would not
    resolve."""
    root: Node = {"t": "board", "name": "", "kids": []}
    for i, sec in enumerate(sections):
        cur = root
        for seg in [x for x in str(sec["into"]).split("/") if x]:
            nxt = next((c for c in cur.get("kids") or [] if c.get("name") == seg), None)
            if nxt is None:
                raise ValueError(
                    f"section {i}: into {sec['into']!r} does not resolve at {seg!r} (cvsheet S.at)"
                )
            cur = nxt
        kids = cur.setdefault("kids", [])
        new = json.loads(json.dumps(sec["node"]))
        idx = next((j for j, c in enumerate(kids) if c.get("name") == new["name"]), None)
        if idx is None:
            kids.append(new)
        else:
            kids[idx] = new


def sections_for_board(bd: dict[str, Any], budget: int = SECTION_BUDGET) -> list[dict[str, Any]]:
    """Split a board (board()'s dict) into sections under budget bytes with correct into paths: the head, the body
    (grid blocks, then the annotation column, packed in pre-order), the footer. Raises over SECTION_HARD.
    """
    out: list[dict[str, Any]] = []
    kids = list(bd["kids"])  # kept alive: _MEMO is keyed by id()
    try:
        for n in kids:
            out += _emit(n, "", budget)
    finally:
        _MEMO.clear()
    check_paths(out)
    for s in out:
        z = _size(s)
        if z > SECTION_HARD:
            raise ValueError(f"section {s['node']['name']!r} is {z} bytes (> {SECTION_HARD})")
        if z > budget:
            _live(
                f"section {s['node']['name']!r} is {z} bytes (> the {budget}-byte budget): a leaf that cannot be "
                "cut further"
            )
    return out


# --- Guards write_sheet() applies (the live lessons of 2026-10-27 and the T2 / per-set-file rules).
def unissued(nodes: Iterable[Node]) -> list[str]:
    """Every text inside a specimen plate whose chars say() did not issue (nor NOTATION)."""
    bad: list[str] = []

    def go(n: Node, inside: bool) -> None:
        here = inside or (n.get("t") == "board" and str(n.get("name")).startswith("specimen"))
        if (
            here
            and n.get("t") == "text"
            and n["chars"] not in _ISSUED
            and n["chars"] not in NOTATION
        ):
            bad.append(f"{n['name']}: {n['chars']!r}")
        for k in n.get("kids") or []:
            go(k, here)

    for n in nodes:
        go(n, False)
    return bad


def _has_text(x: Node) -> bool:
    """True when x is or holds a text."""
    return x.get("t") == "text" or any(_has_text(k) for k in x.get("kids") or [])


def no_h(n: Node) -> list[str]:
    """Paths of boards that hold no text and carry no explicit h (Penpot would give them its 100 px default)."""
    return [p for p, x in walk(n) if x.get("t") == "board" and not x.get("h") and not _has_text(x)]


def hug_in_static(n: Node) -> list[str]:
    """Paths of hug boards (no fixed w and h) holding text directly inside a NON-flex board: they hug to 0 before
    the text is measured and render blank (live lesson 2026-10-27)."""
    bad = []
    for p, x in walk(n):
        if x.get("t") == "board" and not (x.get("o") or {}).get("dir"):
            for k in x.get("kids") or []:
                if k.get("t") == "board" and _has_text(k) and not (k.get("w") and k.get("h")):
                    bad.append(f"{p}/{k['name']}")
    return bad


def never_t2(nodes: Iterable[Node]) -> list[str]:
    """Paths under a T2 node (name holding "T2" or "reason") that bind color.text.disabled / opacity.disabled."""
    bad = []
    for n in nodes:
        for p, x in walk(n):
            if "T2" in p or "reason" in str(x.get("name")):
                toks = [x.get("color"), *(x.get("o") or {}).values()]
                if any(t in NEVER_T2 for t in toks if isinstance(t, str)):
                    bad.append(p)
    return bad


def _md5(p: Path) -> str:
    """The md5 of a file."""
    return hashlib.md5(p.read_bytes()).hexdigest()


# --- Writing: the sheet (validated), its .md, the shape-count report and the compaction.
def write_sheet(
    path: str | Path,
    bd: dict[str, Any],
    sections: list[dict[str, Any]] | None = None,
    notes: dict[str, Any] | None = None,
) -> str:
    """Write the sheet JSON for board()'s dict bd into KIT_DIR: {board, page, sections, export, notes} (page = the
    board's page, which the renderer passes as --page). Refuses: a specimen text say() did not issue; a text-free
    board without h; a hug board holding text inside a non-flex board; an inst node or an icon outside ICONS;
    color.text.disabled / opacity.disabled on a T2 path; a section over SECTION_HARD. Packs the sections, writes,
    runs the validator with the component inventory (raises on exit != 0), keeps the notes in LAST_NOTES and clears
    the collector. Returns the validator's summary line."""
    out = Path(path).resolve()
    if out.parent != KIT_DIR:
        raise ValueError(f"sheets are written only into {KIT_DIR}")
    unknown = set(notes or {}) - set(NOTE_KINDS)
    if unknown:
        raise KeyError(f"notes keys {sorted(unknown)}; allowed {NOTE_KINDS}")
    checks = (
        (
            "a specimen draws only the specs' words: these texts did not come from say()",
            unissued(bd["kids"]),
        ),
        ("boards with no text need an explicit h", [p for n in bd["kids"] for p in no_h(n)]),
        (
            (
                "hug boards holding text inside a non-flex board render blank: make the parent a flex row / column or "
                "give the child w and h"
            ),
            [p for n in bd["kids"] for p in hug_in_static(n)],
        ),
        (
            "a T2 path binds color.text.disabled / opacity.disabled (E09-D09 §2.2)",
            never_t2(bd["kids"]),
        ),
        (
            "the per-set file holds no library component and only the icons "
            + ", ".join(sorted(ICONS)),
            [
                p
                for n in bd["kids"]
                for p, x in walk(n)
                if x.get("t") == "inst" or (x.get("t") == "icon" and x.get("icon") not in ICONS)
            ],
        ),
    )
    for msg, bad in checks:
        if bad:
            raise ValueError(f"{msg}:\n  " + "\n  ".join(bad[:30]))
    secs = sections if sections is not None else sections_for_board(bd)
    merged: dict[str, list[str]] = {k: [] for k in NOTE_KINDS}
    for src in (notes or {}, LOG.notes):
        for k, lines in src.items():
            for ln in [lines] if isinstance(lines, str) else lines:
                if ln not in merged[k]:
                    merged[k].append(ln)
    docs = sorted({m["doc"] for m in _META.values() if m["cid"] in bd.get("cmps", [])}) or ["s1"]
    merged["sources"][:0] = [
        f"spec {DOCS[d][1]} at {SPEC_HEAD} md5 {DOCS[d][2]} (frozen copy {DOCS[d][0].name})"
        for d in docs
    ]
    merged["sources"].insert(
        len(docs),
        f"Penpot file {FILE!r}, page {bd['page']!r}; kit e05d02kit.py md5 "
        f"{_md5(Path(__file__))}",
    )
    sheet = {
        "board": bd["board"],
        "page": bd["page"],
        "sections": secs,
        "export": bd["export"],
        "notes": merged,
    }
    out.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    LAST_NOTES.clear()
    LAST_NOTES.update(merged)
    reset_notes()
    _META.clear()
    res = subprocess.run(
        [sys.executable, "-I", str(VALIDATOR), str(out), "--components", str(COMPONENTS)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    lines = (res.stdout + res.stderr).strip().splitlines()
    if res.returncode != 0:
        raise RuntimeError(
            f"{out.name}: validator exit {res.returncode}\n" + "\n".join(lines[-40:])
        )
    return lines[-1] if lines else ""


def shape_report(path: str | Path) -> dict[str, Any]:
    """The shape-count report of a sheet: shapes, texts, by type, sections, bytes, the largest section's bytes and,
    when its compacted twin exists in V4_DIR, the largest compacted section's bytes."""
    p = Path(path)
    sheet = json.loads(p.read_text(encoding="utf-8"))
    by: dict[str, int] = {}
    for sec in sheet["sections"]:
        for _q, n in walk(sec["node"]):
            by[n["t"]] = by.get(n["t"], 0) + 1
    rep: dict[str, Any] = {
        "sheet": p.name,
        "shapes": sum(by.values()),
        "texts": by.get("text", 0),
        "by_type": dict(sorted(by.items())),
        "sections": len(sheet["sections"]),
        "bytes": len(json.dumps(sheet)),
        "largest_section": max(_size(s) for s in sheet["sections"]),
    }
    twin = V4_DIR / p.name
    if twin.exists():
        c = json.loads(twin.read_text(encoding="utf-8"))
        rep["largest_compacted"] = max(
            len(json.dumps(s, ensure_ascii=False, separators=(",", ":")).encode())
            for s in c["sections"]
        )
    return rep


def compact_sheet(path: str | Path) -> dict[str, Any]:
    """compact.py <sheet> v4/<same name> (exit 0 required), then the compactOf guard (file = the source's
    absolute path, sha256 = its bytes), the page carried over, and every compacted section <= COMPACT_MAX bytes;
    returns shape_report()."""
    src = Path(path).resolve()
    V4_DIR.mkdir(exist_ok=True)
    dst = V4_DIR / src.name
    res = subprocess.run(
        [sys.executable, "-I", str(COMPACT), str(src), str(dst)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"compact.py {src.name}: exit {res.returncode}\n{res.stdout}{res.stderr}"
        )
    c = json.loads(dst.read_text(encoding="utf-8"))
    guard = c.get("compactOf") or {}
    if (
        guard.get("file") != str(src)
        or guard.get("sha256") != hashlib.sha256(src.read_bytes()).hexdigest()
    ):
        raise RuntimeError(f"{dst.name}: compactOf {guard} does not match {src}")
    if c.get("page") != json.loads(src.read_text(encoding="utf-8")).get("page"):
        raise RuntimeError(f"{dst.name}: the page was not carried over")
    rep = shape_report(src)
    if rep["largest_compacted"] > COMPACT_MAX:
        raise RuntimeError(
            f"{dst.name}: a compacted section is {rep['largest_compacted']} bytes (> {COMPACT_MAX})"
        )
    return rep


def write_board_md(
    nn: int,
    bd: dict[str, Any],
    *,
    checks: Iterable[str] = (),
    live: Iterable[str] = (),
    summary: str = "",
) -> Path:
    """NN-<slug>.md beside the sheet (after write_sheet()): the board, its page and export, every block with its CMP
    section, the generator's content checks and live checks, then LAST_NOTES and the shape-count report.
    """
    path = KIT_DIR / f"{stem(nn)}.md"
    sheet = KIT_DIR / f"{stem(nn)}.json"
    rep = shape_report(sheet)
    theme = BOARDS[nn].theme if nn else "dark"
    out = [
        f"# {board_name(nn)}",
        "",
        (
            f"File `{FILE}`, page `{page_of(nn)}` (render with `--page`); export "
            f"`{export_path(nn)}`; sheet `{sheet.name}` (validated); theme {theme}."
        ),
        "",
    ]
    if summary:
        out += [summary, ""]
    out += ["## Blocks", ""]
    for cid in bd["cmps"]:
        c = CMPS[cid]
        out.append(f"- `{c.penpot}` — {cite(c.doc, c.a, c.b)}; spec export `{c.export or '—'}`")
    out += ["", "## Content checks", ""] + ([f"- {x}" for x in checks] or ["- (none given)"])
    out += ["", "## Live checks for the drawer", ""] + [f"- {x}" for x in live]
    out += [f"- {x}" for x in LAST_NOTES.get("live_checks", [])]
    for kind, head in (
        ("not_drawn", "Not drawn — the text is binding"),
        ("copy_keys", "Strings used"),
        ("decisions", "Stamps"),
        ("deviations", "Kit choices and deviations"),
        ("fallbacks", "Tokens and fallbacks"),
        ("copy_gaps", "Copy gaps"),
        ("sources", "Sources"),
    ):
        out += ["", f"## {head}", ""] + [f"- {x}" for x in LAST_NOTES.get(kind, [])]
    out += ["", "## Shape count", "", f"- {json.dumps(rep, ensure_ascii=False)}", ""]
    path.write_text("\n".join(out), encoding="utf-8")
    return path


# --- Self-test and CLI.
def _brief_rows() -> dict[int, tuple[str, tuple[str, ...]]]:
    """The brief's board table: {NN: (slug, CMP ids)} ("CMP-011, 012, 013" expanded)."""
    out: dict[int, tuple[str, tuple[str, ...]]] = {}
    if not BRIEF.exists():  # the lane brief is not committed: the registry is its own table
        return {nn: (b.slug, b.cmps) for nn, b in BOARDS.items()}
    for ln in BRIEF.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| (\d\d) \| ([a-z-]+) \| (.+?) \| (.+?) \|$", ln)
        if m:
            nums = re.findall(r"(?:CMP-)?\b(\d{3})\b", m.group(3))
            out[int(m.group(1))] = (m.group(2), tuple(f"CMP-{x}" for x in nums))
    return out


def _token_slots() -> list[tuple[str, str]]:
    """(constant name, token) for every kit token constant (str constants and the dict tables)."""
    out = []
    for k, v in globals().items():
        if not k.isupper() or k.startswith("_"):
            continue
        vals = list(v.values()) if isinstance(v, dict) and k in ("ACTION", "STATUS") else [v]
        for x in vals:
            if isinstance(x, str) and TOKEN_RE.fullmatch(x):
                out.append((k, x))
    return out


def _exercise() -> list[Node]:
    """One block per shared piece, built on real CMP sections and say()'d strings (the self-test board)."""
    save, buy = say("Save", "CMP-001"), say("Buy / Long", "CMP-001")
    reason = say("Owner only: your role can't use this action.", "CMP-001")
    rows = [
        state_row(
            v,
            [
                cell(s, button(buy if v == "buy" else save, v, s))
                for s in ("default", "hover", "focus-visible", "active", "disabled", "loading")
            ],
        )
        for v in ("primary", "secondary", "ghost", "danger", "buy", "sell")
    ]
    rows.append(
        state_row(
            "T2",
            [
                cell(
                    "disabled-with-reason",
                    button(save, "primary", "disabled-with-reason", reason=reason),
                    note="2a inline",
                ),
                cell("lock + label", t2_label(save)),
            ],
        )
    )
    b1 = block(
        "CMP-001",
        rows,
        states=states("CMP-001"),
        not_drawn=["sizes sm / lg x every state"],
        proposed=["D13", "s3:G23"],
        ruled=["#3925"],
    )
    ib = hbox(
        "CMP-002 iconbutton",
        [tglyph("⋮", TEXT_2, name="CMP-019 more (text glyph)")],
        {"justify": "center", "radius": R_CONTROL, "fill": ACTION["secondary"]},
        w=CONTROL_PX,
        h=CONTROL_PX,
    )
    b2 = block(
        "CMP-002",
        [
            state_row(
                "secondary",
                [
                    cell("default", ib),
                    cell("focus-visible", focus_ring(ib)),
                    cell(
                        "disabled-with-reason",
                        vbox("T2 2b", [lock_badge(ib), tooltip(reason)], {"gap": STACK_XS}),
                        note="2b echo",
                    ),
                ],
            )
        ],
        states=states("CMP-002"),
    )
    b3 = block(
        "CMP-014", [state_row("md", [cell("default", spinner()), cell("in a pill", pill(save))])]
    )
    b4 = block(
        "CMP-016",
        [state_row("top", [cell("short", tooltip(say("Copied", doc="s2")))])],
        not_drawn=[not_drawn("CMP-016")[:120]],
    )
    return [b1, b2, b3, b4]


def _negative(check: Any) -> None:
    """Every refusal write_sheet() / board() / stamps() / say() / icon() promises."""

    def raises(fn: Any, what: str) -> None:
        try:
            fn()
        except (ValueError, KeyError):
            check(True, f"refuses {what}")
            return
        check(False, f"refuses {what}")

    raises(lambda: say("a string no slice holds, 4f1c", "CMP-001"), "an invented specimen string")
    raises(lambda: icon("x", "check", TEXT_1), "an icon the per-set file does not hold")
    raises(lambda: stamps("s1", proposed=["Z9"]), "a PROPOSED id outside the decisions section")
    raises(
        lambda: stamps("s1", ruled=["BQ-404 never ruled"]), "a RULED ref the slice does not hold"
    )
    raises(lambda: node("board", "a/b"), "a '/' in a node name")
    raises(
        lambda: board(1, [block("CMP-001", [state_row("x", [cell("d", spinner())])])], source="t"),
        "a board whose blocks are not its CMPs",
    )
    probe = {"board": {}, "page": "", "export": "", "cmps": []}
    raises(
        lambda: write_sheet(
            KIT_DIR / "00-neg.json",
            dict(probe, kids=[cell("d", text("t", "invented words", BODY, TEXT_1))]),
        ),
        "an unissued specimen text",
    )
    raises(
        lambda: write_sheet(
            KIT_DIR / "00-neg.json",
            dict(
                probe,
                kids=[box("static", [hbox("hug", [text("t", "x", BODY, TEXT_1)])], h=40, w=40)],
            ),
        ),
        "a hug text row in a non-flex board",
    )
    raises(
        lambda: write_sheet(
            KIT_DIR / "00-neg.json",
            dict(probe, kids=[hbox("T2 bad", [text("label", "x", BODY, TEXT_DISABLED)])]),
        ),
        "color.text.disabled on a T2 path",
    )
    raises(
        lambda: write_sheet(KIT_DIR / "00-neg.json", dict(probe, kids=[hbox("empty", [])])),
        "a text-free board without h",
    )
    reset_notes()
    _META.clear()


def selftest() -> int:
    """Re-check the frozen specs, the registries and every token; exercise the refusals; build, write, validate and
    compact 00-selftest.json; write 00-selftest.md. Prints one line per check; returns the number failing.
    """
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("ok   " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    for d, (copy_, repo, md5, lab) in DOCS.items():
        check(
            hashlib.md5(spec_bytes(d)).hexdigest() == md5,
            f"{lab}: frozen copy {copy_.name} md5 {md5}",
        )
        live = WT / repo
        if live.exists() and _md5(live) != md5:
            print(
                f"WARN {lab}: {repo} in this checkout differs from the frozen copy (re-freeze and re-run the boards)"
            )
    per = {d: [c.id for c in CMPS.values() if c.doc == d] for d in DOCS}
    check(
        [len(per[d]) for d in DOCS] == [11, 12, 11, 17],
        f"CMP sections per slice 11/12/11/17: " f"{[len(per[d]) for d in DOCS]}",
    )
    on = [cid for b in BOARDS.values() for cid in b.cmps]
    check(
        sorted(on) == sorted(CMPS) and len(on) == len(set(on)),
        "boards 01-09 hold every CMP exactly once (51)",
    )
    check(
        all(CMPS[c].doc == b.doc for b in BOARDS.values() for c in b.cmps),
        "every board's CMPs are its slice's",
    )
    brief = _brief_rows()
    check(sorted(brief) == list(range(1, 11)), "the brief's table has the ten boards")
    for nn, b in BOARDS.items():
        slug, ids = brief.get(nn, ("", ()))
        check(
            slug == b.slug and ids == b.cmps,
            f"board {nn:02d} '{b.name}' on '{b.page}' = the brief's row",
        )
    check(
        len({b.page for b in BOARDS.values()}) == 4
        and [b.nn for b in BOARDS.values() if b.theme == "light"] == [10],
        "four pages; board 10 is the only light board",
    )
    for c in CMPS.values():
        check(
            bool(c.penpot)
            and "/" not in c.penpot
            and bool(c.export)
            and (bool(axes(c.id)) or c.id == "CMP-039"),
            f"{c.id}: Penpot name {c.penpot!r}, export, axes ({len(axes(c.id))}), cells {len(cells(c.id))}, "
            f"tokens {len(tokens(c.id))}",
        )
    check(
        [len(DECISIONS[d]) for d in DOCS] == [47, 37, 23, 37],
        f"decision items per slice 47/37/23/37: " f"{[len(DECISIONS[d]) for d in DOCS]}",
    )
    have = token_table()
    for k, tk in _token_slots():
        sets = {s for s, _t in have.get(tk, set())}
        check(bool(sets), f"token {k} = {tk} exists")
    _negative(check)
    blocks = _exercise()
    bd = board(
        0,
        blocks,
        source="kit self-test: slice 1 CMP-001 / 002 / 014, slice 4 CMP-016 (never drawn)",
        notes=["the self-test board exercises every shared piece once"],
    )
    sheet = KIT_DIR / "00-selftest.json"
    summary = write_sheet(sheet, bd)
    check(True, f"00-selftest.json validated: {summary}")
    rep = compact_sheet(sheet)
    check(rep["largest_compacted"] <= COMPACT_MAX, f"compacted into v4/: {json.dumps(rep)}")
    js = json.loads(sheet.read_text(encoding="utf-8"))
    check(
        js["page"] == PAGES["s1"] and js["board"]["name"] == board_name(0),
        "the sheet carries its page and name",
    )
    write_board_md(
        0, bd, checks=["every shared piece built once"], summary="The kit's self-test board."
    )
    check((KIT_DIR / "00-selftest.md").exists(), "00-selftest.md written")
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failing check(s)")
    return len(fails)


def main(argv: list[str]) -> int:
    """The CLI (see the module docstring)."""
    if not argv or argv[0] not in ("selftest", "cmps", "cmp", "report", "compact"):
        print(__doc__.split("CLI:", 1)[1])
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "selftest":
        return 1 if selftest() else 0
    if cmd == "cmps":
        for nn, b in BOARDS.items():
            if rest and int(rest[0]) != nn:
                continue
            print(f"{b.name} — page '{b.page}', theme {b.theme}, export {b.export}")
            for cid in b.cmps:
                c = CMPS[cid]
                ax = "; ".join(f"{k}: {', '.join(v[0])}" for k, v in axes(cid).items())
                print(f"  {c.penpot} {cite(c.doc, c.a, c.b)} cells {len(cells(cid))} | {ax}")
        return 0
    if cmd == "cmp":
        c = cmp(rest[0])
        print(f"{c.penpot} — {cite(c.doc, c.a, c.b)}; export {c.export}")
        for t in c.tables:
            print(f"  [{t.label or t.header[0]}] L{t.line}: {len(t.rows)} rows")
            if t.header[0] in ("Axis", "Cell"):
                for _ln, r in t.rows:
                    print("    " + " | ".join(x[:90] for x in r))
        print("  not drawn: " + (not_drawn(c.id)[:400] or "—"))
        print("  tokens: " + ", ".join(tokens(c.id)))
        print("  missing tokens: " + (", ".join(missing_tokens(c.id)) or "—"))
        return 0
    for p in rest:
        print(
            json.dumps(
                compact_sheet(p) if cmd == "compact" else shape_report(p), ensure_ascii=False
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
