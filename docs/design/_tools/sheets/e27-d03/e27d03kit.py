"""e27d03kit: the shared sheet kit for the E27-D03 (#816) accounts and key-vault hi-fi boards. Python 3.12+, stdlib only.

Every builder returns cvsheet node dicts (schema: ../lib/cvsheet-v4.3.js header; the v1 node keys), so the board generators
(gen/gen_NN.py, written by the board authors) draw the ten §0 boards the same way: per board a grid of CELLS, each cell
one E27-D02 frame nested under its exact name (`SCR-nnn / <state>`, `Pattern / …`, `CMP-087 / …`) with its caption row
(the frame name and its PROPOSED stamp) and its ANNOTATION LAYER row under it ("not yet served — {gap}, {owner}"
strips, never inside a frame), beside the board's ANNOTATION COLUMN (sources, stamps, not-yet-served list, not drawn,
kit choices, notes). Board 10 holds specimen cells (no inventory frame); boards 02 and 05 are the light twins of 01 and
04 (the same frames, drawn again; semantic-light applied through the file's light theme at export).
Sources: the MERGED docs/design/E27/E27-D03.md, its handoff E27-D03-handoff.md and E27-D02.md (the frame inventory,
its "## 7. State inventory") as of commit 1983363fa (a frozen copy in spec/ beside this file if present, else read
with `git show 1983363fa:<path>`; DOCS pins each md5).

BINDING (per-set file "E27-D03 boards"): no library component; the kit draws NO inst node; every component is composed
from board / rect / text / ellipse with token binds. Icons (t:"icon") only for the file's local `icon / locked`,
`arrow-up`, `arrow-down`, `close`, `drag-handle` (ICONS); every other glyph (CMP-175's check, octagon, triangle, clock,
dash, info; the slashed circle; plus, chevron, more, copy) is a text glyph (NOTATION) or primitives (glyph()).
Lessons (live, 2026-10-27) enforced by write_sheet(): text sits only in flex rows / columns (a hug board holding text
inside a non-flex board is refused); a text-free board carries an explicit h; every node in a non-flex parent carries
x / y (renderer v4.3 places a missing x/y at the parent origin); a row is sized to the sum of its children (fit_row());
sections <= ~9 KB compacted.

Registries parsed from the frozen specs at import (never retyped): BOARDS (§0: name, frames, theme, export, twin),
INVENTORY (E27-D02 §7: number, frame, "shows T2"), HIFI (the hi-fi rows of §2.6 and §3-§8: frame -> its cells by header),
DECK (§12.1: id -> its strings), REASONS (§12.2 T2 reason keys), CMP175 (§2.1's variant set: facet, class, glyph, deck
key), VERDICT (the aggregate forms), SLOT (§2.2's state words), FIXTURES (L62-65), DECISION_IDS (BQ, HD, D03-x), GAPS.
Copy: inside a frame (a board whose name is a §0 frame) every text comes from copy(key, **fills) (the deck),
reason(key, **fills) (§12.2), say(chars) (found in the pinned text of E27-D03 / its handoff / E27-D02) or fixture(v)
(L62-65), or NOTATION; write_sheet() refuses the rest (invented copy = BLOCKER). Fills take fixture values, digits,
UTC times and dates only. Captions, stamps, strips and the annotation column are board chrome.
Use from a generator (python3 -I keeps the kit's folder off sys.path):
    import sys; sys.dont_write_bytecode = True
    sys.path.insert(0, "<this folder>")
    import e27d03kit as k
    def f6() -> dict: return {"content": [k.accounts_stub()], "verdict": k.verdict_line("dated", n=4, hh_mm="14:02")}
    c6 = k.frame("SCR-125 / ok", f6, strips=[("G-1, #895 / #896", "per-key facets")], proposed=["HD3"])
    bd = k.board(4, [c6, ...], source="E27-D03 §3 L946-1124, §6 L1305-1388")
    k.write_sheet(k.KIT_DIR / f"{k.stem(4)}.json", bd); k.compact_sheet(k.KIT_DIR / f"{k.stem(4)}.json")
    k.write_board_md(4, bd, checks=[...], live=[...])
CLI: python3 -I -B e27d03kit.py selftest        (checks, builds every piece, writes 00-selftest.json, validates, compacts)
     python3 -I -B e27d03kit.py boards [NN]      (board -> frames, theme, export, the hi-fi row line of each frame)
     python3 -I -B e27d03kit.py frame '<name>'   (one frame's hi-fi row, condensed, and its inventory line)
     python3 -I -B e27d03kit.py deck <prefix>    (the deck ids under a prefix and their strings)
     python3 -I -B e27d03kit.py report <sheet.json>...   (the shape-count report)
     python3 -I -B e27d03kit.py compact <sheet.json>...  (compact.py into v4/, compactOf checked)
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
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
RENDERER = SHEETS_DIR / "lib" / "cvsheet-v4.3.js"
TOKENS_FILE = TOOLS_DIR / "token-sync.json"
WT = KIT_DIR.parents[4]  # the repository root (a WARN when a doc differs from its frozen copy)
SPEC_HEAD = "1983363fa"  # origin/main when the kit froze the three docs (2026-10-27)
DOCS = {  # key -> (frozen copy, repo path, md5, label)
    "d03": (
        KIT_DIR / "spec" / "E27-D03@1983363fa.md",
        "docs/design/E27/E27-D03.md",
        "f386f58eeeb8aaadc18696c0ceba3e81",
        "E27-D03",
    ),
    "handoff": (
        KIT_DIR / "spec" / "E27-D03-handoff@1983363fa.md",
        "docs/design/E27/E27-D03-handoff.md",
        "4036e46f59e34d55af53cfa4480bdc15",
        "E27-D03 handoff",
    ),
    "d02": (
        KIT_DIR / "spec" / "E27-D02@1983363fa.md",
        "docs/design/E27/E27-D02.md",
        "ec56733e286dd5cf2f7d0282d24ba9b2",
        "E27-D02",
    ),
}
SET = "E27-D03"
FILE = "E27-D03 boards"  # the per-set Penpot file (not the shared DS file)
PAGE = "E27-D03 Accounts and key vault hi-fi"  # §0 L194 (36 characters); every board sits on it
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
    "secondary": "color.action.secondary.default",
    "secondary.hover": "color.action.secondary.hover",
    "selected": "color.action.selected",
}
STATUS = {
    f"{t}.{s}": f"color.status.{t}.{s}"
    for t in ("info", "success", "warning", "danger")
    for s in ("default", "strong", "subtle")
}
NEUTRAL_SUBTLE = "color.neutral.subtle"  # CMP-175's unknown class fill (§2.1 L417)
ENV_LIVE, ENV_DEMO = "color.env.live", "color.env.demo"  # CMP-075's border and dot (§3.1 block I)
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
NUM_SM, NUM_BASE, NUM_MD = "type.num.sm", "type.num.base", "type.num.md"
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
BTN_PADX, FIELD_GAP = "space.button.paddingX", "space.field.gap"
DIALOG_PAD, PANEL_PAD = "space.dialog.padding", "space.panel.padding"
CONTROL_COMPACT, CONTROL_COMFORTABLE = (
    "size.control.compact",
    "size.control.comfortable",
)  # Tier-1 (FALLBACKS DENSITY)
ICON = "size.icon"
R_CONTROL, R_CARD, R_BADGE, R_DIALOG = (
    "radius.control",
    "radius.card",
    "radius.badge",
    "radius.dialog",
)
R_PILL, R_RING = (
    "radius.pill",
    "radius.md",
)  # Tier-1 primitives (validator WARN; FALLBACKS PILL, RING)
E_POPOVER, E_DIALOG, E_CARD = "elevation.popover", "elevation.dialog", "elevation.card"
OP_DISABLED, OP_SCRIM = "opacity.disabled", "opacity.scrim"
HAIRLINE, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
NEVER_T2 = (
    TEXT_DISABLED,
    OP_DISABLED,
)  # §10.1: never on a T2 label, glyph or reason; never in a disabled row
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
    FIELD_GAP: 8,
    DIALOG_PAD: 24,
    PANEL_PAD: 12,
    ICON: 16,
    CONTROL_COMPACT: 24,
    CONTROL_COMFORTABLE: 32,
}


class Density(NamedTuple):
    """A density mode (BQ-4, HD12): control / row height in px, its size token, the badge padding and the stack step."""

    name: str
    control: int
    control_tok: str
    pad: str
    step: str


DENSITIES = {
    "comfortable": Density(
        "comfortable", 32, CONTROL_COMFORTABLE, INSET_MD, STACK_MD
    ),  # SCR-125..129, 016
    "compact": Density("compact", 24, CONTROL_COMPACT, INSET_SM, STACK_SM),
}  # SCR-079's host (§8)
_DENSITY: list[Density] = [DENSITIES["comfortable"]]


@contextmanager
def density(name: str) -> Iterator[Density]:
    """with k.density("compact"): … — the density every control built inside uses (comfortable outside)."""
    if name not in DENSITIES:
        raise ValueError(f"density {name!r}: one of {sorted(DENSITIES)}")
    _DENSITY.append(DENSITIES[name])
    try:
        yield DENSITIES[name]
    finally:
        _DENSITY.pop()


def dens() -> Density:
    """The density in force."""
    return _DENSITY[-1]


# --- Geometry (raw px only in w, h, x, y). §3.1's frame 6 (E42-D03's shell); kit choices marked.
FRAME_W, FRAME_H = 1280, 800
TOP_H, STATUS_H = 48, 48  # TopBar and StatusBar (§3.1 block A)
NAV_W, RIGHT_W = 64, 240  # NavRail collapsed, RightRail (§3.1 block A)
MAIN_W = FRAME_W - NAV_W - RIGHT_W  # 976: the content, space.inset.lg padding
INNER_W = MAIN_W - 2 * 16  # 944 inside
BODY_H = FRAME_H - TOP_H - STATUS_H  # 704 (y 48-752)
BAND_H, RULE_H, STRIP_H = 32, 4, 32  # §3.1 block C
DRAWER_W = 480  # SCR-079's CMP-046 drawer (§8 anatomy L1497)
DIALOG_W = 640  # CMP-043 Large (§2.4 CMP-044 sizes; no source gives px: kit choice "dialog")
WIZARD_W = 720  # SCR-127's wizard (kit choice "dialog")
INSET_CARD_W = 800  # SCR-016 step 3's card inset (kit choice "inset")
DOC_W = 1280  # the Pattern frames' documentation surface (kit choice "doc")
COLS = (240, 240, 272, 192)  # §3.1 block H: the four table columns
PITCH_X, PITCH_Y = (
    6400,
    6400,
)  # page grid: the ten boards side by side in NN order, PITCH_X apart (grid_xy)
GRID_MAX_W = (
    PITCH_X - 240 - 440
)  # the frame grid's widest (the annotation column and its gap take the rest)
ROOT_PAD = 16  # space.inset.lg
GRID_GAP = INSET_XL  # between cells (24 px)
ANN_W, ANN_TEXT_W = 400, 368  # the annotation column (space.inset.lg padding)
SPLIT_STANDIN = "∕"  # U+2215: a frame too big for one section carries it for "/" until renamed live

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
    "not_served",
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


FALLBACKS = {  # "fallback: ..." / "token: ..." lines, printed under Tokens in the board .md
    "LOCK": (
        'fallback: CMP-019 `lock` (decorative=false, named "Not available") is the file\'s local '
        "'icon / locked'"
    ),
    "GLYPHS": (
        "fallback: the per-set file holds only the local icons locked, arrow-up, arrow-down, close and "
        "drag-handle; CMP-175's class glyphs are drawn so each class keeps its own SHAPE (BQ-6: the shape is "
        "the carrier): check = text glyph ✓, triangle = text glyph ⚠, octagon = a 16 px square with clipped "
        "look (radius.control) filled in the class token holding a '!' (cvsheet has no polygon), clock = a "
        "stroked ring with two hands, dash = a 10 x 2 bar, info = a stroked ring holding 'i', slashed circle = "
        "text glyph ⊘; plus, chevron, more and copy are text glyphs (+ ▾ ⋮ ⧉)"
    ),
    "BOLD": (
        "fallback: no typography token carries font.weight.bold at caption / body size; the critical word "
        "(BQ-6) binds type.ui.label (medium) and keeps its other carriers — 'BLOCKED' first, the octagon and the "
        "2 px border.thick color.status.danger.strong border; the LIVE pill's bold word likewise (§3.1 block I)"
    ),
    "DENSITY": (
        "token: control heights bind the Tier-1 size.control.compact (24) / size.control.comfortable (32) "
        "(BQ-4, HD12: the admin screens comfortable, SCR-079 compact; the semantic size.control.height "
        "resolves through the active density set, so the boards bind the mode's own primitive; validator WARN)"
    ),
    "PILL": "token: CMP-075's radius.pill is a Tier-1 primitive (§3.1 block I names it; validator WARN)",
    "RING": (
        "token: the CMP-039 ring (2 px color.focus.ring, its offset) binds radius.md (6 px) on a wrapper 2 px "
        "outside the control (validator WARN)"
    ),
    "OPACITY": "token: opacity.scrim is a Tier-1 primitive (validator WARN): the modal scrim under CMP-046 / CMP-043",
    "RULE4": (
        "fallback: the blocked record's 4 px inline-start rule (§2.2; 4 px is space.1, no border.* width is 4) "
        "is a 4 px rect in color.status.danger.strong at the row's start edge"
    ),
    "SKELETON": "fallback: CMP-015's skeleton is a static bar in color.surface.hover (reduced-motion form, §2.5)",
}
KIT_CHOICES = {  # each one is recorded in the sheet's deviations where it is used
    "cell": (
        "Each frame is a CELL: a caption row (the frame's exact §0 name in type.ui.heading-sm, then its "
        "PROPOSED stamp), the frame nested under its E27-D02 name, then its annotation-layer row (the 'not yet "
        "served' strips and notes; never inside the frame, never product UI)"
    ),
    "chrome": (
        "The consumed chrome (CMP-072 TopBar, CMP-071 NavRail, CMP-209 RightRail, CMP-208 StatusBar; §3.1 "
        "block A) is drawn as placeholders at its redline geometry with the environment badges; it is "
        "consumed and never redrawn (§2.6)"
    ),
    "dialog": "CMP-043 Large dialogs are 640 px and SCR-127's wizard 720 px (no source gives px)",
    "inset": "SCR-016 step 3 rides as 800 px card insets on board 06 (BQ-1); its CMP-097 chrome is E09's",
    "doc": "The Pattern frames (§2.6) are 1280 px documentation surfaces on color.surface.canvas, height hugging",
    "glyphs": "glyphs other than the five local icons are text glyphs (NOTATION) or primitives (FALLBACKS GLYPHS)",
    "light": (
        "Boards 02 and 05 are the light twins of 01 and 04: the same frames drawn again with the same token "
        "names; semantic-light is applied through the file's light theme at export (§0 L227-228; HD13)"
    ),
    "t2": (
        "T2 per §10.1: 2a inline everywhere; CMP-079 wraps the control; the CMP-019 lock LEADS the full label; "
        "label and lock color.text.tertiary, the reason under it in type.ui.caption color.text.secondary; a "
        "filled control loses its fill (color.surface.raised + 1 px color.border.default); never "
        "color.text.disabled, never opacity.disabled"
    ),
    "validity": (
        "A confirm that is not yet valid is E42-D03's validity form (§2.4 CMP-044): color.surface.raised, "
        "a color.border.default hairline, the label color.text.tertiary, NO lock (form validity, not T2)"
    ),
    "focus": "A focus ring is CMP-039's 2 px color.focus.ring stroke on a wrapper 2 px outside the control",
    "strip": (
        "A 'not yet served — {gap}, {owner}' strip is board annotation (§0 L199-200): a warning-stroked pill "
        "on the cell's annotation layer, never inside the frame"
    ),
    "split": (
        "A frame whose JSON exceeds the section budget is split across sections under its name with '∕' "
        "(U+2215) for '/' (cvsheet splits section paths on '/'); the drawer renames it after the board's last "
        "section (live check)"
    ),
    "page": (
        "mkcall4.py derives a page from the board name ('E27-D03 / NN …' -> 'E27-D03'); the sheet carries its "
        "page in sheet['page'] and the renderer passes --page 'E27-D03 Accounts and key vault hi-fi'"
    ),
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
_FRAME_OK: set[str] = (
    set()
)  # names allowed to carry "/" (the §0 frames; filled once BOARDS is parsed)


def node(t: str, name: str, **kw: Any) -> Node:
    """A cvsheet node of type t (None values dropped). Raises on keys cvsheet rejects, an empty name or a "/" in a
    name other than a §0 frame's (section paths split on "/"); records every token it binds under LOG "tokens".
    """
    if not name:
        raise ValueError(f"{t} node without a name")
    if "/" in name and not (t == "board" and name in _FRAME_OK):
        raise ValueError(
            f"{t} {name!r}: '/' splits cvsheet section paths; only a §0 frame name may carry it"
        )
    n: Node = {"t": t, "name": name}
    n.update({k: v for k, v in kw.items() if v is not None})
    if isinstance(n.get("o"), dict):
        n["o"] = {k: v for k, v in n["o"].items() if v is not None} or None
        if n["o"] is None:
            del n["o"]
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


def icon(name: str, glyph_: str, color: str, size: str = ICON, **kw: Any) -> Node:
    """One of the file's local icons (ICONS) with its stroke bound to color."""
    if glyph_ not in ICONS:
        raise ValueError(
            f"icon {glyph_!r} is not in the per-set file ({sorted(ICONS)}): use glyph() / tglyph()"
        )
    return node("icon", name, icon=glyph_, color=color, size=size, **kw)


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


def at(n: Node, x: float, y: float) -> Node:
    """n at x, y inside a NON-flex parent (renderer v4.3 places a node without x / y at the parent's origin)."""
    return dict(n, x=round(x), y=round(y))


# --- Text metrics (estimates for widths, wraps and heights; Inter / JetBrains Mono), as e05d02kit.
_FONT = {
    CAPTION: (11, 1.2, 1.0, False),
    BODY: (13, 1.4, 1.0, False),
    BODY_STRONG: (13, 1.4, 1.04, False),
    LABEL: (12, 1.2, 1.03, False),
    HEADING_SM: (14, 1.2, 1.06, False),
    HEADING_MD: (16, 1.2, 1.06, False),
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
        "○": 0.60,
        "⋮": 0.30,
        "▸": 0.60,
        "↑": 0.60,
        "↓": 0.60,
        "←": 0.80,
        "✓": 0.65,
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
        "⊘": 0.80,
        "⧉": 0.80,
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


def fit_row(n: Node, w: float | None = None) -> Node:
    """Raise when a fixed-width flex row is narrower than the sum of its children and gaps (a footer row whose
    money-moving / full-intent button label would clip); returns n. w= checks against that width instead.
    """
    o = n.get("o") or {}
    width = w or n.get("w")
    if o.get("dir") != "row" or not width or o.get("wrap") == "wrap":
        return n
    need = est_width(dict(n, w=None))
    if need > width + 0.5:
        raise ValueError(
            f"row {n['name']!r}: its children need about {need:.0f} px, it is {width} px wide (a label "
            "would clip): widen the card or wrap the row"
        )
    return n


def walk(n: Node, path: str = "") -> Iterable[tuple[str, Node]]:
    """Yield (path, node) for n and every descendant."""
    p = f"{path}/{n['name']}" if path else n["name"]
    yield p, n
    for k in n.get("kids") or []:
        yield from walk(k, p)


# --- Reading the frozen docs: raw lines, cleaned text, table rows.
_LINES: dict[str, list[str]] = {}
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
TOKEN_RE = re.compile(
    r"\b(?:color|space|size|radius|type|opacity|elevation|border)\.[a-z0-9]+(?:[.-][a-z0-9]+)*\b"
)


def spec_bytes(doc: str) -> bytes:
    """Doc ("d03", "handoff", "d02") as of SPEC_HEAD: the frozen copy in spec/ if present, else `git show`."""
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


def doc_lines(doc: str = "d03") -> list[str]:
    """The frozen copy of doc ("d03", "handoff", "d02") as raw lines (index 0 = line 1)."""
    if doc not in _LINES:
        _LINES[doc] = spec_bytes(doc).decode("utf-8").splitlines()
    return _LINES[doc]


def clean(s: str) -> str:
    """s without Markdown markers (comments, `**`, backticks, escaped pipes) and with whitespace collapsed."""
    s = _COMMENT.sub("", s).replace("**", "").replace("`", "").replace("\\|", "|")
    return re.sub(r"\s+", " ", s).strip()


_SPAN: dict[tuple[str, int, int], str] = {}


def span_text(doc: str, a: int, b: int) -> str:
    """Lines a..b (1-based, inclusive) of doc, cleaned and joined with spaces (memoised)."""
    key = (doc, a, b)
    if key not in _SPAN:
        _SPAN[key] = clean(" ".join(doc_lines(doc)[a - 1 : b]))
    return _SPAN[key]


def all_text(doc: str) -> str:
    """The whole of doc, cleaned."""
    return span_text(doc, 1, len(doc_lines(doc)))


def cite(a: int, b: int | None = None, doc: str = "d03") -> str:
    """'E27-D03 Lnnn' or 'E27-D03 Lnnn-mmm' (doc's label)."""
    return f"{DOCS[doc][3]} L{a}" + (f"-{b}" if b and b != a else "")


def cells_of(raw: str) -> list[str]:
    """The raw cells of one Markdown table line (escaped pipes kept inside their cell)."""
    parts = re.split(r"(?<!\\)\|", raw.strip())
    return [p.strip() for p in parts[1:-1]]


def table_at(doc: str, line: int) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """The table whose header is at line: (cleaned header cells, [(line, raw cells)] of its body rows)."""
    lines = doc_lines(doc)
    hdr = [clean(c) for c in cells_of(lines[line - 1])]
    rows, i = [], line + 1
    while i <= len(lines) and lines[i - 1].lstrip().startswith("|"):
        if not re.fullmatch(r"[\s|:-]+", lines[i - 1]):
            rows.append((i, cells_of(lines[i - 1])))
        i += 1
    return hdr, rows


def heading_line(pattern: str, doc: str = "d03") -> int:
    """The line of the first heading matching pattern (a regex on the whole line)."""
    for i, ln in enumerate(doc_lines(doc), 1):
        if ln.startswith("#") and re.search(pattern, ln):
            return i
    raise ValueError(f"no heading matching {pattern!r} in {DOCS[doc][3]}")


def next_table(after: int, header0: str, doc: str = "d03") -> int:
    """The line of the first table header at or after line after whose first cell is header0."""
    for i in range(after, len(doc_lines(doc)) + 1):
        ln = doc_lines(doc)[i - 1]
        if (
            ln.lstrip().startswith("|")
            and clean(cells_of(ln)[0] if cells_of(ln) else "") == header0
        ):
            return i
    raise ValueError(f"no table with first header {header0!r} after {DOCS[doc][3]} L{after}")


def quoted(cell: str) -> list[str]:
    """The double-quoted strings of a cell, in order ('"a" · "b"' -> ['a', 'b'])."""
    return [clean(q) for q in re.findall(r'"([^"]*)"', cell)]


# --- The registries.
class Bd(NamedTuple):
    """One §0 board: NN, slug, name, its frames (a twin: its dark board's), draws, theme, export, twin-of, line."""

    nn: int
    slug: str
    name: str
    frames: tuple[str, ...]
    draws: str
    theme: str
    export: str
    twin_of: int
    line: int


def _parse_boards() -> dict[int, Bd]:
    """§0's board table (L216-227): the ten boards; a twin's frames are its dark board's."""
    a = heading_line(r"^## 0\. The boards")
    hdr, rows = table_at("d03", next_table(a, "#"))
    if hdr[:3] != ["#", "Board", "Frames (E27-D02 §7)"]:
        raise ValueError(f"§0 board table header changed: {hdr}")
    out: dict[int, Bd] = {}
    for ln, c in rows:
        nn = int(c[0])
        m = re.fullmatch(rf"`{SET} / (\d\d) ([a-z0-9-]+)`", c[1])
        if not m or int(m.group(1)) != nn:
            raise ValueError(f"§0 L{ln}: board cell {c[1]!r}")
        twin = re.fullmatch(r"twin of (\d\d)", clean(c[2]))
        frames = tuple(re.findall(r"`([^`]+)`", c[2]))
        theme = clean(c[4])
        export = clean(c[6])
        tw = int(twin.group(1)) if twin else 0
        out[nn] = Bd(
            nn,
            m.group(2),
            f"{SET} / {nn:02d} {m.group(2)}",
            frames,
            clean(c[3]),
            theme,
            export,
            tw,
            ln,
        )
    for nn, b in out.items():
        if b.twin_of:
            out[nn] = b._replace(frames=out[b.twin_of].frames)
    return out


class Inv(NamedTuple):
    """One E27-D02 §7 frame: its number, name, state cell, line and whether it shows T2."""

    num: int
    name: str
    state: str
    line: int
    t2: bool


def _parse_inventory() -> dict[str, Inv]:
    """E27-D02 §7 (the 78 frames)."""
    a = heading_line(r"^## 7\. State inventory", "d02")
    _hdr, rows = table_at("d02", next_table(a, "#", "d02"))
    out = {}
    for ln, c in rows:
        nm = clean(c[1])
        out[nm] = Inv(int(c[0]), nm, clean(c[2]), ln, "shows T2" in clean(c[2]))
    return out


class HiFi(NamedTuple):
    """One frame's hi-fi row: its number, line, section heading, and its cells by (cleaned) header."""

    num: int
    line: int
    section: str
    cells: dict[str, str]

    def board_cell(self) -> str:
        """The row's Board cell, cleaned."""
        return clean(self.cells.get("Board", ""))


def _parse_hifi() -> dict[str, HiFi]:
    """Every table whose second header is "Frame (E27-D02 §7)" (§2.6, §3.4, §4.3, §4.4, §5, §6, §7, §8)."""
    out: dict[str, HiFi] = {}
    lines = doc_lines("d03")
    sec = ""
    for i, ln in enumerate(lines, 1):
        if ln.startswith("#"):
            sec = ln.lstrip("#").strip()
        if (
            ln.lstrip().startswith("|")
            and len(cells_of(ln)) > 2
            and clean(cells_of(ln)[1]) == "Frame (E27-D02 §7)"
        ):
            hdr, rows = table_at("d03", i)
            for rl, c in rows:
                nm = clean(c[1])
                out[nm] = HiFi(
                    int(c[0]), rl, sec, {h: c[j] for j, h in enumerate(hdr) if j < len(c)}
                )
    return out


class Deck(NamedTuple):
    """One §12.1 deck row: its id, strings, where, status · source and line."""

    id: str
    strings: tuple[str, ...]
    where: str
    status: str
    line: int


def _parse_deck() -> dict[str, Deck]:
    """§12.1's rows (`e27.*` ids; 327)."""
    a, b = heading_line(r"^### 12\.1 "), heading_line(r"^### 12\.2 ")
    out = {}
    for i in range(a, b):
        ln = doc_lines("d03")[i - 1]
        m = re.match(r"\| `(e27\.[^`]+)` *\|", ln)
        if m:
            c = cells_of(ln)
            out[m.group(1)] = Deck(m.group(1), tuple(quoted(c[2])), clean(c[1]), clean(c[3]), i)
    return out


def _parse_reasons() -> dict[str, tuple[str, int]]:
    """§12.2's T2 reason keys: key -> (string, line)."""
    a, b = heading_line(r"^### 12\.2 "), heading_line(r"^### 12\.3 ")
    out = {}
    for i in range(a, b):
        ln = doc_lines("d03")[i - 1]
        m = re.match(r"\| `([a-z_]+\.[a-z_.]+)` *\|", ln)
        if m:
            q = quoted(cells_of(ln)[1])
            out[m.group(1)] = (q[0], i)
    return out


class V175(NamedTuple):
    """One CMP-175 variant (§2.1): facet, class, glyph kind, word (deck string), deck key, line."""

    variant: str
    facet: str
    cls: str
    glyph: str
    word: str
    key: str
    line: int


GLYPH_OF = {
    "check": "check",
    "octagon": "octagon",
    "triangle": "triangle",
    "clock": "clock",
    "dash": "dash",
    "info": "info",
}


def _parse_cmp175() -> dict[str, V175]:
    """§2.1's variant table (13 states), each word matched to its `e27.cmp175.*` deck key."""
    a = heading_line(r"^### 2\.1 CMP-175")
    hdr, rows = table_at("d03", next_table(a, "Variant"))
    out = {}
    for ln, c in rows:
        d = {h: c[j] for j, h in enumerate(hdr)}
        var = clean(d["Variant"])
        g = clean(d["Glyph"]).split(" ")[0]
        word = quoted(d["Word"])[0]
        keys = [k for k, v in DECK.items() if k.startswith("e27.cmp175.") and word in v.strings]
        out[var] = V175(
            var,
            clean(d["Facet"]),
            clean(d["Class"]),
            GLYPH_OF.get(g, g),
            word,
            keys[0] if keys else "",
            ln,
        )
    return out


def _parse_verdict() -> dict[str, tuple[str, str, int]]:
    """§2.1's aggregate forms (CMP-175 `aggregate`): form -> (class, glyph kind, line)."""
    a = heading_line(r"^#### CMP-175: scopes, forms")
    _hdr, rows = table_at("d03", next_table(a, "Form"))
    out = {}
    for ln, c in rows:
        cg = clean(c[2])
        cls, _, g = cg.partition(" · ")
        out[clean(c[0])] = (cls.strip(), GLYPH_OF.get(g.strip(), "none"), ln)
    return out


class Slot(NamedTuple):
    """One §2.2 state-slot word: the word, its component, class or tone, glyph kind and line."""

    word: str
    cmp: str
    tone: str
    glyph: str
    line: int


def _parse_slot() -> list[Slot]:
    """§2.2's state words (CMP-176's slot, in precedence order)."""
    a = heading_line(r"^#### CMP-176: the state slot")
    _hdr, rows = table_at("d03", next_table(a, "State word"))
    out = []
    for ln, c in rows:
        g = clean(c[3])
        kind = (
            "octagon"
            if "octagon" in g
            else (
                "clock"
                if "clock" in g
                else (
                    "triangle"
                    if "triangle" in g
                    else (
                        "dash"
                        if "dash" in g
                        else (
                            "check"
                            if g.startswith("check")
                            else "slashed" if "slashed" in g else "none"
                        )
                    )
                )
            )
        )
        for w in quoted(c[0]):
            out.append(Slot(w, clean(c[1]), clean(c[2]), kind, ln))
    return out


FIXTURE_LINES = (62, 65)


def _parse_fixtures() -> dict[str, str]:
    """L62-65's fixture values: value -> kind (label, uid, user, key, ip, env)."""
    txt = span_text("d03", *FIXTURE_LINES)
    out: dict[str, str] = {}
    for lab, uid in re.findall(r"(Main|sub_\d{3}|demo-1) \(?(?:UID )?(\d{7})\)?", txt):
        out[lab], out[uid] = "label", "uid"
    for u in ("alex", "bea"):
        if f"{u}" in txt:
            out[u] = "user"
    for kid in re.findall(r"\.\.\.[a-z0-9]{4}", txt):
        out[kid] = "key"
    for ip in re.findall(r"\d{3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", txt):
        out[ip] = "ip"
    out.update({"LIVE": "env", "DEMO": "env"})
    return out


def _parse_decision_ids() -> dict[str, int]:
    """Every id a PROPOSED / RULED stamp may name: BQ-1..16 (the questions table), HD1..17 (§1.2) and the §14 rows
    (D03-A / C / G / H / D / Q): id -> line."""
    out: dict[str, int] = {}
    for i, ln in enumerate(doc_lines("d03"), 1):
        m = re.match(r"\| (BQ-\d+|HD\d+|D03-[ACGHDQ]\d+) +\|", ln)
        if m and m.group(1) not in out:
            out[m.group(1)] = i
    return out


def _parse_gaps() -> dict[str, int]:
    """Every "not yet served — {gap}, {owner}" the spec writes: "{gap}, {owner}" -> first line."""
    out: dict[str, int] = {}
    for i, ln in enumerate(doc_lines("d03"), 1):
        for m in re.finditer(r"not yet served — ((?:G-\d+|D03-G\d+), #\d+(?: / #\d+)?)", clean(ln)):
            out.setdefault(m.group(1), i)
    return out


def _parse_pairs() -> dict[str, tuple[str, str, int]]:
    """§9's measured matrix: the tool's pair id -> (fg token, bg token, line) (e.g. c175-danger-word)."""
    out: dict[str, tuple[str, str, int]] = {}
    for i, ln in enumerate(doc_lines("d03"), 1):
        m = re.match(r"\| *\d+ *\| `([a-z0-9.-]+)` on `([a-z0-9.-]+)` · `([a-z0-9-]+)`", ln)
        if m:
            out.setdefault(m.group(3), (m.group(1), m.group(2), i))
    return out


BOARDS = _parse_boards()
PAIRS9 = _parse_pairs()
INVENTORY = _parse_inventory()
HIFI = _parse_hifi()
DECK = _parse_deck()
REASONS = _parse_reasons()
CMP175 = _parse_cmp175()
VERDICT = _parse_verdict()
SLOT = _parse_slot()
FIXTURES = _parse_fixtures()
DECISION_IDS = _parse_decision_ids()
GAPS = _parse_gaps()
FRAMES = {
    f: b.nn for b in BOARDS.values() if not b.twin_of for f in b.frames
}  # frame -> its dark board
_FRAME_OK.update(INVENTORY)
PAIRS = (
    ("01", "02"),
    ("03", "10"),
    ("04", "05"),
    ("06", "07"),
    ("08", "09"),
)  # the parallel board authors


def board_name(nn: int) -> str:
    """The board's name, "E27-D03 / NN slug" (nn=0: the kit's self-test board)."""
    return f"{SET} / 00 selftest" if nn == 0 else BOARDS[nn].name


def stem(nn: int) -> str:
    """The sheet's file stem, NN-<slug>."""
    return f"{nn:02d}-{BOARDS[nn].slug}" if nn else "00-selftest"


def grid_xy(nn: int) -> tuple[int, int]:
    """Board NN's page position: the ten side by side, x = (NN - 1) x PITCH_X, y = 0; the self-test above the grid at
    y = -PITCH_Y (never drawn)."""
    return (0, -PITCH_Y) if nn == 0 else ((nn - 1) * PITCH_X, 0)


def export_path(nn: int) -> str:
    """§0's planned export (the self-test's is the kit's own)."""
    return f"docs/design/E27/img/{SET}-00-selftest.png" if nn == 0 else BOARDS[nn].export


def theme_of(nn: int) -> str:
    """The board's theme (dark, or light for the twins)."""
    return BOARDS[nn].theme if nn else "dark"


def surface(frame_name: str) -> str:
    """The frame's surface prefix: "SCR-125", "Pattern", "CMP-087", …"""
    return frame_name.split(" / ", 1)[0]


def hifi_tokens(frame_name: str) -> list[str]:
    """The token names a frame's hi-fi row cites (its Tokens cell, else the whole row) — named directly or through a
    §9 pair id (PAIRS9: fg and bg) — in order, that token-sync holds. A row that reads "as §3.1" / "as frame N"
    inherits that anatomy's tokens (read it)."""
    hf = hifi(frame_name)
    cell_ = clean(
        next(
            (v for k, v in hf.cells.items() if k.startswith("Tokens")), " ".join(hf.cells.values())
        )
    )
    have = token_table()
    out: list[str] = []
    named = TOKEN_RE.findall(cell_)
    for pid in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)+", cell_):
        if pid in PAIRS9:
            named += PAIRS9[pid][:2]
    for tk in named:
        if tk in have and tk not in out:
            out.append(tk)
    return out


def hifi_copy_keys(frame_name: str) -> list[str]:
    """The §12.1 deck ids a frame's hi-fi row cites (its Copy keys cell; a `e27.x.*` wildcard expands to the deck's
    ids under it), in order."""
    hf = hifi(frame_name)
    cell_ = next((v for k, v in hf.cells.items() if k.startswith("Copy keys")), "")
    out: list[str] = []
    for ref in re.findall(r"`(e27\.[a-z0-9_.*]+)`", cell_):
        ids = (
            [k for k in DECK if k.startswith(ref[:-1])]
            if ref.endswith("*")
            else [ref] if ref in DECK else []
        )
        out += [i for i in ids if i not in out]
    return out


def hifi_t2(frame_name: str) -> bool:
    """True when the frame shows T2: E27-D02 §7's "shows T2" (the authority cell() checks) or its hi-fi row saying
    "T2 per §10.1"."""
    return INVENTORY[frame_name].t2 or "T2 per §10.1" in clean(
        " ".join(hifi(frame_name).cells.values())
    )


def hifi(frame_name: str) -> HiFi:
    """The frame's hi-fi row (raises for a name §2-§8 does not hold)."""
    if frame_name not in HIFI:
        raise KeyError(f"{frame_name!r} has no hi-fi row (E27-D03 §2.6, §3-§8)")
    return HIFI[frame_name]


# --- Copy: the deck (§12.1), the reason keys (§12.2), the pinned text and the fixtures. Never an invented string.
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
    "⊘",
    "⧉",
    "?",
    "!",
    "i",
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
}  # text glyphs and lone digits a frame may draw without a source line
_ISSUED: set[str] = set()
_FILL_RE = re.compile(r"\{([^{}]+)\}")
_FILL_OK = re.compile(
    r"^(?:[+−-]?\d[\d,]*(?:\.\d+)?(?: ?(?:%|x|ms|s|d|h|USDT|BTC))?|\d{2}:\d{2}(?::\d{2})?|"
    r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?)$"
)


def reset_notes() -> None:
    """Clear the collector, the issued-copy set and the cell facts (write_sheet() does this after writing)."""
    LOG.reset()
    _ISSUED.clear()
    _META.clear()


def _issue(s: str) -> str:
    """Mark s (and its " · " parts) as issued copy."""
    _ISSUED.add(s)
    for part in s.split(" · "):
        _ISSUED.add(part)
    return s


def found(chars: str, doc: str | None = None) -> str | None:
    """The doc key ("d03", "handoff", "d02") whose pinned text holds chars (whitespace-normalised, Markdown markers
    dropped), first d03; None when no doc holds it."""
    c = clean(chars)
    for d in [doc] if doc else list(DOCS):
        if c and c in all_text(d):
            return d
    return None


def _fill_value_ok(v: str) -> bool:
    """A fill value is a fixture, a number / time / date, or a string already issued or in the pinned text."""
    return v in FIXTURES or bool(_FILL_OK.match(v)) or v in _ISSUED or found(v) is not None


def fill(template: str, **fills: Any) -> str:
    """template with every {name} replaced (a kwarg name writes ':' as '_': hh_mm -> {hh:mm}); raises on a missing
    fill, an unused one or a value that is not a fixture, number, UTC time, date or issued / pinned string.
    """
    want = {m.group(1) for m in _FILL_RE.finditer(template)}
    got = {
        k.replace("_", ":") if k.replace("_", ":") in want else k: str(v) for k, v in fills.items()
    }
    miss, extra = want - set(got), set(got) - want
    if miss or extra:
        raise KeyError(f"fill({template!r}): missing {sorted(miss)}, unused {sorted(extra)}")
    for k, v in got.items():
        if not _fill_value_ok(v):
            raise ValueError(
                f"fill {k}={v!r}: not a fixture (L62-65), number, time, date or pinned string"
            )
    return _FILL_RE.sub(lambda m: got[m.group(1)], template)


def copy(key: str, i: int = 0, **fills: Any) -> str:
    """The deck string key (§12.1; i picks one of a row's several strings), filled; recorded under copy_keys."""
    if key not in DECK:
        raise KeyError(f"copy({key!r}): no such deck id (§12.1)")
    d = DECK[key]
    s = fill(d.strings[i], **fills)
    LOG.add("copy_keys", f"{key}[{i}] — {cite(d.line)} ({d.status.split(' ·')[0]})")
    return _issue(s)


def copies(key: str, **fills: Any) -> list[str]:
    """Every string of a deck row (table headers, menu items, stepper labels, …), each filled with fills it uses."""
    out = []
    for i, s in enumerate(DECK[key].strings):
        mine = {
            k: v
            for k, v in fills.items()
            if "{" + k.replace("_", ":") + "}" in s or "{" + k + "}" in s
        }
        out.append(copy(key, i, **mine))
    return out


def reason(key: str, **fills: Any) -> str:
    """A §12.2 T2 reason string (E27's PROPOSED keys and the consumed rbac.* rows), filled."""
    if key not in REASONS:
        raise KeyError(f"reason({key!r}): not a §12.2 key ({sorted(REASONS)})")
    s, ln = REASONS[key]
    LOG.add("copy_keys", f"{key} — {cite(ln)} (T2 reason key)")
    return _issue(fill(s, **fills))


def say(chars: str, doc: str | None = None) -> str:
    """chars, checked against the pinned text (E27-D03, then its handoff, then E27-D02; doc= one of them): a
    string a hi-fi row quotes outside the deck. Raises when no pinned doc holds it (invented copy is a BLOCKER).
    """
    if chars in NOTATION or chars in FIXTURES:
        return _issue(chars)
    d = found(chars, doc)
    if d is None:
        raise ValueError(
            f"say({chars!r}): not in the pinned text of {doc or 'E27-D03 / handoff / E27-D02'}"
        )
    LOG.add("copy_keys", f"{chars!r} — {DOCS[d][3]} (quoted)")
    return _issue(chars)


def fixture(v: str) -> str:
    """A fixture value (L62-65: labels, UIDs, users, key ids, documentation addresses, LIVE / DEMO)."""
    if v not in FIXTURES:
        raise ValueError(f"fixture({v!r}): not one of L62-65's values ({sorted(FIXTURES)})")
    return _issue(v)


def gap(line: str) -> None:
    """Record a copy gap (a string the frame needs and no pinned doc gives: never drawn invented)."""
    LOG.add("copy_gaps", line)


# --- Glyphs (FALLBACKS GLYPHS: the shape carries the class; BQ-6).
CLASS_TOK = {
    "pass": (STATUS["success.subtle"], STATUS["success.strong"]),
    "failed": (STATUS["danger.subtle"], STATUS["danger.strong"]),
    "critical": (STATUS["danger.subtle"], STATUS["danger.strong"]),
    "warning": (STATUS["warning.subtle"], STATUS["warning.strong"]),
    "time warning": (STATUS["warning.subtle"], STATUS["warning.strong"]),
    "unknown": (NEUTRAL_SUBTLE, TEXT_2),
    "info": (STATUS["info.subtle"], STATUS["info.strong"]),
}  # §2.1 L412-421
GLYPH_KINDS = (
    "check",
    "octagon",
    "triangle",
    "clock",
    "dash",
    "info",
    "slashed",
    "lock",
    "plus",
    "chevron",
    "more",
    "copy",
)


def tglyph(
    ch: str, color: str = TEXT_2, typo: str = BODY, name: str | None = None, **kw: Any
) -> Node:
    """A text glyph from NOTATION, named 'glyph <ch>' unless name= says the CMP-019 icon it stands for."""
    if ch not in NOTATION:
        raise ValueError(f"text glyph {ch!r} is not in NOTATION")
    _choice("glyphs")
    return text(name or f"glyph {ch}", _issue(ch), typo, color, **kw)


def lock(color: str = TEXT_3, name: str = "CMP-019 lock · Not available") -> Node:
    """CMP-019 `lock` (decorative=false, "Not available"): the file's local icon / locked (T2: color.text.tertiary)."""
    _fallback("LOCK")
    return icon(name, "locked", color)


def glyph(kind: str, color: str, name: str | None = None) -> Node:
    """A 16 px class glyph by the spec's word (GLYPH_KINDS), aria-hidden beside its word: text glyphs or primitives
    (FALLBACKS GLYPHS); lock is the local icon."""
    nm = name or f"CMP-019 {kind}"
    if kind == "lock":
        return lock(color, nm)
    _fallback("GLYPHS")
    _choice("glyphs")
    tg = {
        "check": "✓",
        "triangle": "⚠",
        "slashed": "⊘",
        "plus": "+",
        "chevron": "▾",
        "more": "⋮",
        "copy": "⧉",
    }
    if kind in tg:
        return hbox(
            nm, [text("glyph", _issue(tg[kind]), BODY, color)], {"justify": "center"}, w=16, h=16
        )
    if kind == "octagon":
        return hbox(
            nm,
            [text("mark", _issue("!"), CAPTION, TEXT_INVERSE)],
            {"justify": "center", "fill": color, "radius": R_CONTROL},
            w=16,
            h=16,
        )
    if kind == "info":
        ring = place(ellipse("ring", 14, 14, {"stroke": color, "strokeWidth": HAIRLINE}), 1, 1)
        return hbox(
            nm, [ring, text("mark", _issue("i"), CAPTION, color)], {"justify": "center"}, w=16, h=16
        )
    if kind == "clock":
        return box(
            nm,
            [
                at(ellipse("ring", 14, 14, {"stroke": color, "strokeWidth": HAIRLINE}), 1, 1),
                at(rect("hand-h", 2, 5, color), 7, 3),
                at(rect("hand-m", 4, 2, color), 7, 7),
            ],
            w=16,
            h=16,
        )
    if kind == "dash":
        return hbox(nm, [rect("bar", 10, 2, color)], {"justify": "center"}, w=16, h=16)
    raise ValueError(f"glyph {kind!r}: one of {GLYPH_KINDS}")


def caption(
    chars: str,
    w: int | None = None,
    *,
    color: str = TEXT_2,
    typo: str = CAPTION,
    name: str = "caption",
) -> Node:
    """Board chrome: a caption (fixed width w wraps it; a long caption must get one)."""
    if w is None and text_w(chars, typo) > 360:
        raise ValueError(
            f"caption {chars[:40]!r}…: give a long caption a fixed width (it wraps only then)"
        )
    return text(name, chars, typo, color, w=w)


def focus_ring(n: Node, *, name: str = "focus-ring") -> Node:
    """n with CMP-039's ring: a flex wrapper 4 px larger than n holding an abs rect stroked 2 px color.focus.ring
    (border.focus), i.e. 2 px outside n (KIT_CHOICES focus; FALLBACKS RING)."""
    _choice("focus")
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
                "radius": R_RING,
                "strokeAlign": "inner",
            },
        ),
        0,
        0,
    )
    return hbox(name, [n, ring], {"justify": "center"}, w=w, h=h)


# --- CMP-175 KeyPermissionBadge (§2.1), CMP-011 chips, the record's state slot (§2.2), CMP-075, CMP-034.
def cmp175(
    variant: str, form: str = "badge", *, lead: bool = True, w: int | None = None, **fills: Any
) -> Node:
    """A CMP-175 `key` facet in the variant's own word (its deck key; §2.1 L306-320): form "badge" (the class's
    subtle fill, glyph and word in type.ui.caption, min-height the density's control, radius.badge) or "inline"
    (glyph and word in type.ui.body on the host's surface). The critical variant is always the badge, its word in
    the BOLD fallback inside a 2 px border.thick color.status.danger.strong border. lead=False drops an allowlist
    word's "IP allowlist: " lead under a header that names the facet (§2.1 L376-377)."""
    if variant not in CMP175:
        raise KeyError(f"cmp175({variant!r}): one of {sorted(CMP175)}")
    v = CMP175[variant]
    word = copy(v.key, **fills) if v.key else _issue(fill(v.word, **fills))
    if not lead:
        if v.facet != "allowlist":
            raise ValueError("lead=False is for the allowlist facet only (§2.1 L376)")
        word = say(word.split(": ", 1)[1])
    fill_, ink = CLASS_TOK[v.cls]
    crit = v.cls == "critical"
    if crit:
        form = "badge"
        _fallback("BOLD")
    nm = f"CMP-175 {variant.split(' (')[0]} · {form}"
    LOG.add("sources", f"CMP-175 {variant}: {cite(v.line)}")
    if form == "inline":
        return hbox(
            nm,
            [glyph(v.glyph, ink), text("word", word, BODY, TEXT_1, w=w)],
            {"gap": INSET_XS, "align": "start"},
        )
    if form != "badge":
        raise ValueError(f"cmp175 form {form!r}: badge or inline")
    o: dict[str, Any] = {
        "fill": fill_,
        "radius": R_BADGE,
        "padX": dens().pad,
        "padY": INSET_XS,
        "gap": INSET_XS,
        "minH": dens().control_tok,
    }
    _fallback("DENSITY")
    if crit:
        o.update(stroke=ink, strokeWidth=THICK)
    return hbox(
        nm, [glyph(v.glyph, ink), text("word", word, LABEL if crit else CAPTION, TEXT_1, w=w)], o
    )


# Derived from the state names; "cleared" reads the dated line. (A literal mapping trips the secret
# scanners on the no-keys entry.)
VERDICT_KEY = {
    v: "e27.scr125.verdict." + v.replace(" ", "_")
    for v in ("dated", "overdue", "failed", "unavailable", "read failed", "no keys", "loading")
}
VERDICT_KEY["cleared"] = VERDICT_KEY["dated"]


def verdict_line(form: str, *, w: int = INNER_W, **fills: Any) -> Node:
    """CMP-175 `aggregate` (§2.1 L380-393; §3.1 block E): one 32 px line under the h1, no fill, never dismissible:
    the class glyph, the words type.ui.body-strong color.text.primary, the basis and time (the part after the last
    " · ") color.text.secondary; loading is a static skeleton bar and its words, never OFF."""
    if form not in VERDICT:
        raise KeyError(f"verdict_line({form!r}): one of {sorted(VERDICT)}")
    cls, kind, ln = VERDICT[form]
    s = copy(VERDICT_KEY[form], **fills)
    LOG.add("sources", f"CMP-175 aggregate {form}: {cite(ln)}")
    kids: list[Node | None] = []
    if kind == "none":
        _fallback("SKELETON")
        kids += [
            rect("CMP-015 skeleton", 16, 12, HOVER, o={"radius": R_CONTROL}),
            text("words", s, BODY_STRONG, TEXT_2),
        ]
    else:
        kids.append(glyph(kind, CLASS_TOK[cls][1]))
        head, sep, tail = (
            s.rpartition(" · ") if " · " in s and form in ("dated", "cleared") else (s, "", "")
        )
        room = w - 24
        if sep:
            kids += [
                text("words", _issue(head), BODY_STRONG, TEXT_1),
                text("basis and time", _issue("· " + tail), BODY, TEXT_2),
            ]
        else:
            kids.append(
                text(
                    "words",
                    s,
                    BODY_STRONG,
                    TEXT_1,
                    w=room if text_w(s, BODY_STRONG) > room else None,
                )
            )
    return hbox(
        f"CMP-175 aggregate · {form}",
        kids,
        {"gap": INSET_XS, "wrap": "wrap", "minH": CONTROL_COMFORTABLE},
        w=w,
    )


CHIP_TONE = {
    "neutral": (NEUTRAL_SUBTLE, TEXT_2, TEXT_2),
    "warning": (STATUS["warning.subtle"], TEXT_1, STATUS["warning.strong"]),
    "danger": (STATUS["danger.subtle"], TEXT_1, STATUS["danger.strong"]),
}  # fill, label, glyph (§9 rows)


def chip(word: str, tone: str, kind: str | None = None, *, name: str | None = None) -> Node:
    """A CMP-011 Tag / Chip (§2.2; §2.5): its tone's fill, a 1 px color.border.default stroke, the glyph and the word
    (type.ui.caption); word must be issued by the caller (copy / say)."""
    fill_, ink, g = CHIP_TONE[tone]
    kids = [glyph(kind, g) if kind and kind != "none" else None, text("word", word, CAPTION, ink)]
    return hbox(
        name or f"CMP-011 chip · {tone}",
        kids,
        {
            "fill": fill_,
            "stroke": BORDER_DEFAULT,
            "strokeWidth": HAIRLINE,
            "radius": R_BADGE,
            "padX": dens().pad,
            "padY": INSET_XS,
            "gap": INSET_XS,
            "minH": dens().control_tok,
        },
    )


def state_badge(word: str, **fills: Any) -> Node:
    """The record's state slot (§2.2 L499-528; HD3): the slot word's own component — a CMP-175 badge for a
    key-verification word, a CMP-011 chip (its tone and glyph) for every other — filled with fills.
    """
    hits = [s for s in SLOT if s.word == word]
    if not hits:
        raise KeyError(f"state_badge({word!r}): not a §2.2 state word ({[s.word for s in SLOT]})")
    s = hits[0]
    LOG.add("sources", f"CMP-176 state slot {word!r}: {cite(s.line)}")
    if s.cmp == "CMP-175":
        var = next(v.variant for v in CMP175.values() if v.word == word)
        return cmp175(var, "badge", **fills)
    tone = "warning" if s.tone.startswith("warning") else s.tone
    return chip(
        _issue(fill(word, **fills)), tone, s.glyph, name=f"CMP-011 chip · {word.split(' ')[0]}"
    )


def env_pill(env: str, *, name: str | None = None) -> Node:
    """CMP-075 (§3.1 block I; §3.5): the word color.text.primary, a 1 px border and a dot in color.env.live /
    color.env.demo, radius.pill; LIVE in the BOLD fallback with a filled dot, DEMO regular with an outline dot.
    """
    if env not in ("LIVE", "DEMO"):
        raise ValueError("env_pill: LIVE or DEMO")
    col = ENV_LIVE if env == "LIVE" else ENV_DEMO
    _fallback("PILL")
    if env == "LIVE":
        _fallback("BOLD")
    dot = ellipse(
        "dot", 8, 8, {"fill": col} if env == "LIVE" else {"stroke": col, "strokeWidth": HAIRLINE}
    )
    return hbox(
        name or f"CMP-075 env · {env}",
        [dot, text("word", fixture(env), LABEL if env == "LIVE" else CAPTION, TEXT_1)],
        {
            "stroke": col,
            "strokeWidth": HAIRLINE,
            "radius": R_PILL,
            "padX": INSET_SM,
            "padY": INSET_XS,
            "gap": INSET_XS,
        },
    )


def masked_id(key_id: str, *, typo: str = NUM_BASE, color: str = TEXT_1) -> Node:
    """CMP-034 MaskedValue, permanently masked (§2.3, BQ-8, HD5): the served `...{last4}` as text only — no box, no
    control, no timer — type.num.base color.text.primary on its host's surface."""
    if FIXTURES.get(key_id) != "key":
        raise ValueError(f"masked_id({key_id!r}): a fixture key id (L63-64)")
    return text(
        "CMP-034 MaskedValue",
        fixture(key_id),
        typo,
        color,
        note=f'accessible name "{fill(DECK["e27.cmp034.name"].strings[0], label="API key", last4=key_id[3:])}"'
        "; aria-describedby the page's one description node",
    )


# --- Buttons, T2 and the validity form (§10.1; §2.4 CMP-044).
BUTTON_LOOK = {
    "primary": (ACTION["primary"], TEXT_ON_ACTION, None),
    "secondary": (ACTION["secondary"], TEXT_1, None),
    "ghost": (None, TEXT_2, None),
    "destructive": (STATUS["danger.subtle"], TEXT_1, STATUS["danger.strong"]),
}  # §2.4 CMP-044 tokens
T2_SHAPE = {
    "fill": RAISED,
    "stroke": BORDER_DEFAULT,
    "strokeWidth": HAIRLINE,
}  # §10.1: the enabled fill goes


def button(
    label: str,
    variant: str = "secondary",
    state: str = "default",
    *,
    lead: str | None = None,
    name: str | None = None,
) -> Node:
    """A CMP-001 Button from primitives at the density's height: variants primary / secondary / ghost / destructive
    (the rung-3 confirm: color.status.danger.subtle with a 1 px color.status.danger.strong border); states default,
    hover, focus (CMP-039 ring), busy (a static CMP-015 bar after the label), t2 (§10.1: lock leading, the stripped
    shape; use t2_button() for the reason) and validity (E42-D03's form: the stripped shape, no lock). label must be
    issued (copy / say); lead= a glyph kind before it ("plus")."""
    fill_, ink, edge = BUTTON_LOOK[variant]
    o: dict[str, Any] = {
        "padX": BTN_PADX,
        "gap": INSET_XS,
        "radius": R_CONTROL,
        "justify": "center",
    }
    kids: list[Node | None] = []
    if state in ("t2", "validity"):
        o.update(T2_SHAPE)
        ink = TEXT_3
        if state == "t2":
            _choice("t2")
            kids.append(lock())
        else:
            _choice("validity")
    else:
        if state == "hover" and variant in ("primary", "secondary"):
            fill_ = ACTION[f"{variant}.hover"]
        elif state == "hover":
            fill_ = HOVER
        if fill_:
            o["fill"] = fill_
        if edge:
            o.update(stroke=edge, strokeWidth=HAIRLINE)
    if lead:
        kids.append(glyph(lead, ink))
    kids.append(text("label", label, BODY_STRONG, ink))
    if state == "busy":
        _fallback("SKELETON")
        kids.append(rect("CMP-015 progress", 16, 4, ink, o={"radius": R_CONTROL}))
    _fallback("DENSITY")
    b = hbox(
        name or f"CMP-001 button · {variant} · {state}" + (" · T2" if state == "t2" else ""),
        kids,
        o,
        h=dens().control,
    )
    return focus_ring(b) if state == "focus" else b


def t2_reason(chars: str, *, w: int | None = None, name: str = "T2 reason") -> Node:
    """The 2a inline reason (§10.1): type.ui.caption color.text.secondary, never dimmed; chars from reason()."""
    _choice("t2")
    return text(name, chars, CAPTION, TEXT_2, w=w)


def t2_button(
    label: str, reason_key: str, variant: str = "secondary", *, w: int | None = None, **fills: Any
) -> Node:
    """A gated button inside CMP-079 RbacGate (§10.1): the T2 shape with the lock leading the full label, its
    §12.2 reason under it (2a inline, stack.xs apart)."""
    return vbox(
        f"T2 · CMP-079 RbacGate · {label}",
        [button(label, variant, "t2"), t2_reason(reason(reason_key, **fills), w=w)],
        {"gap": STACK_XS},
        note='aria-disabled="true"; the reason node is in the DOM at mount, linked by aria-describedby',
    )


def t2_label(label: str, *, typo: str = BODY, name: str = "T2 label") -> Node:
    """The T2 label row: the CMP-019 lock LEADING the full label, both color.text.tertiary (§10.1)."""
    _choice("t2")
    return hbox(name, [lock(), text("label", label, typo, TEXT_3)], {"gap": INSET_XS})


def menu_item(
    label: str,
    *,
    second: str | None = None,
    reason_key: str | None = None,
    focused: bool = False,
    w: int = 280,
    **fills: Any,
) -> Node:
    """A CMP-041 menu item: its label (type.ui.body), the ask line or the T2 reason as its second line (§2.2 `menu`;
    §10.1: a gated item keeps its label whole, the lock leading, the reason its second line)."""
    kids: list[Node | None]
    if reason_key:
        kids = [t2_label(label), t2_reason(reason(reason_key, **fills), w=w - 2 * PX[INSET_SM])]
        nm = f"T2 · menu item · {label}"
    else:
        kids = [
            text("label", label, BODY, TEXT_1),
            text("second", second, CAPTION, TEXT_2, w=w - 16) if second else None,
        ]
        nm = f"menu item · {label}"
    it = vbox(
        nm,
        kids,
        {"padX": INSET_SM, "padY": INSET_XS, "gap": STACK_XS, "fill": HOVER if focused else None},
        w=w,
    )
    return focus_ring(it) if focused else it


def menu(items: Iterable[Node], *, w: int = 296, name: str = "CMP-041 Menu") -> Node:
    """A CMP-041 menu surface: color.surface.overlay, a 1 px color.border.default edge, radius.card, elevation.popover."""
    return vbox(
        name,
        list(items),
        {
            "fill": OVERLAY,
            "stroke": BORDER_DEFAULT,
            "strokeWidth": HAIRLINE,
            "radius": R_CARD,
            "padY": INSET_XS,
            "shadow": E_POPOVER,
        },
        w=w,
    )


# --- Fields (CMP-007 well, CMP-201 writeOnly; HD11), the check list (CMP-203), the KEK notice (CMP-028).
def field(
    label: str,
    value: str | None = None,
    *,
    w: int = 320,
    hint: str | None = None,
    write_only: bool = False,
    focused: bool = False,
    name: str | None = None,
) -> Node:
    """A labelled CMP-007 well (HD11: color.surface.app with a 1 px color.text.tertiary boundary, pages and dialogs
    alike) at the density's height: label (type.ui.label), the well (value type.num.base, or empty), the hint
    (type.ui.caption color.text.secondary). write_only=True is CMP-201's writeOnly variant (§2.3: no toggle, no
    value ever shown back; the well stays empty). Strings must be issued."""
    if write_only and value:
        raise ValueError("a write-only field never shows its value (CMP-201 writeOnly, §2.3)")
    well = hbox(
        "well",
        [text("value", value, NUM_BASE, TEXT_1) if value else None],
        {
            "fill": APP,
            "stroke": TEXT_3,
            "strokeWidth": HAIRLINE,
            "radius": R_CONTROL,
            "padX": INSET_SM,
        },
        w=w,
        h=dens().control,
    )
    if focused:
        well = focus_ring(well)
    kids = [
        text("label", label, LABEL, TEXT_1),
        well,
        text("hint", hint, CAPTION, TEXT_2, w=w) if hint else None,
    ]
    nm = name or (f"CMP-201 writeOnly · {label}" if write_only else f"CMP-007 field · {label}")
    return vbox(nm, kids, {"gap": STACK_XS})


CHECK_OUTCOME = {
    "passed": ("check", STATUS["success.strong"]),
    "warning": ("triangle", STATUS["warning.strong"]),
    "failed": ("octagon", STATUS["danger.strong"]),
    "not checked": ("dash", TEXT_2),
}  # §2.5 L915-920


def check_row(check: str, outcome: str, words: str, *, w: int = 560) -> Node:
    """One CMP-203 row (§2.5 L909-932): the outcome glyph then "{check}: {outcome}" (e27.checks.row); check and
    words must be issued (copies("e27.checks.names"), copy("e27.checks.<row>.<outcome>")); "not checked" words are
    color.text.secondary."""
    if outcome not in CHECK_OUTCOME:
        raise KeyError(f"check_row outcome {outcome!r}: one of {sorted(CHECK_OUTCOME)}")
    kind, col = CHECK_OUTCOME[outcome]
    s = copy("e27.checks.row", check=check, outcome=words)
    return hbox(
        f"check · {check}",
        [
            glyph(kind, col),
            text("words", s, BODY, TEXT_2 if outcome == "not checked" else TEXT_1, w=w - 20),
        ],
        {"gap": INSET_XS, "align": "start"},
        w=w,
    )


def check_list(
    rows: Iterable[tuple[str, str, str]],
    *,
    w: int = 560,
    name: str = "CMP-203 RequirementChecklist",
) -> Node:
    """CMP-203 extended (live={false}): one row per (check, outcome, words), in the pipeline's order."""
    _src_line("CMP-203", heading_line(r"^#### CMP-203 RequirementChecklist"))
    return vbox(
        name,
        [check_row(c, o, wd, w=w) for c, o, wd in rows],
        {"gap": STACK_XS},
        w=w,
        note="a list, no control, no live region of its own (§2.5 L929-932)",
    )


def kek_notice(*, w: int = INNER_W) -> Node:
    """CMP-028's blocking KEK notice (§2.4 L705-734; HD6): color.status.danger.subtle, a 2 px border.thick
    color.status.danger.strong border, the octagon; sentence 1 the keys.kek_unavailable reason (type.ui.body-strong,
    the id every blocked key control points at), sentence 2 e27.shared.kek_notice (type.ui.body); silent.
    """
    s1, s2 = reason("keys.kek_unavailable"), copy("e27.shared.kek_notice")
    tw = w - 2 * PX[dens().pad] - 20
    body = vbox(
        "sentences",
        [
            text("sentence 1", s1, BODY_STRONG, TEXT_1, w=tw),
            text("sentence 2", s2, BODY, TEXT_1, w=tw),
        ],
        {"gap": STACK_XS},
    )
    _src_line("CMP-028 KEK notice", heading_line(r"^#### CMP-028 — the KEK"))
    return hbox(
        "CMP-028 notice · blocking · KEK",
        [glyph("octagon", STATUS["danger.strong"]), body],
        {
            "fill": STATUS["danger.subtle"],
            "stroke": STATUS["danger.strong"],
            "strokeWidth": THICK,
            "radius": R_CARD,
            "pad": dens().pad,
            "gap": INSET_XS,
            "align": "start",
        },
        w=w,
        note="no live role; not dismissible; sentence 1 carries the stable id (G-T2.5)",
    )


def notice(
    lines: Iterable[str], *, tone: str = "neutral", w: int = INNER_W, name: str = "CMP-028 notice"
) -> Node:
    """A CMP-028 notice: tone neutral (color.surface.raised, 1 px color.border.default) or danger (as kek_notice's
    fill and 2 px border, the octagon); lines issued; the first line type.ui.body-strong."""
    ls = list(lines)
    tw = w - 2 * PX[dens().pad] - (20 if tone == "danger" else 0)
    txt = vbox(
        "sentences",
        [
            text(f"line {i}", s, BODY_STRONG if i == 1 else BODY, TEXT_1, w=tw)
            for i, s in enumerate(ls, 1)
        ],
        {"gap": STACK_XS},
    )
    o: dict[str, Any] = {"radius": R_CARD, "pad": dens().pad, "gap": INSET_XS, "align": "start"}
    if tone == "danger":
        o.update(fill=STATUS["danger.subtle"], stroke=STATUS["danger.strong"], strokeWidth=THICK)
        kids: list[Node | None] = [glyph("octagon", STATUS["danger.strong"]), txt]
    else:
        o.update(fill=RAISED, stroke=BORDER_DEFAULT, strokeWidth=HAIRLINE)
        kids = [txt]
    return hbox(name, kids, o, w=w)


def banner(key: str, *, w: int = FRAME_W) -> Node:
    """CMP-092's blocking row (§3.1 block B): one 32 px row across the frame, color.status.danger.subtle,
    color.text.primary, the octagon in color.status.danger.strong; key an e27.shell.banner.* id (the server's
    sentence, consumed)."""
    if not key.startswith("e27.shell.banner."):
        raise ValueError("banner(): an e27.shell.banner.* deck id")
    return hbox(
        "CMP-092 DegradedModeBanner · blocking",
        [glyph("octagon", STATUS["danger.strong"]), text("sentence", copy(key), BODY, TEXT_1)],
        {"fill": STATUS["danger.subtle"], "padX": INSET_LG, "gap": INSET_SM},
        w=w,
        h=32,
        note="the one announcement for the condition (15:935)",
    )


# --- Dialogs (CMP-043 / CMP-044 rungs, §2.4 L761-807) and the overlay layer.
def rung_dialog(
    title: str,
    consequences: Iterable[str | Node],
    *,
    rung: int,
    confirm: Node,
    choices: Node | None = None,
    typed: Node | None = None,
    ask: bool = True,
    marker: str | None = "e27.scr129.marker",
    error: Node | None = None,
    lead_in: str | None = None,
    cancel_focused: bool = True,
    w: int = DIALOG_W,
) -> Node:
    """A CMP-044 confirm dialog (rung 1 or 3) in E42-D02 §4.1's anatomy: title (type.ui.heading-md), the lead-in,
    the consequences as a list (type.ui.body color.text.primary), [the two choices], [the typed field], the ask line
    (e27.shared.ask, color.text.secondary), the marker (a deck id, color.text.tertiary), the exchange error, then
    the footer [Cancel] [confirm] (Cancel first, initial focus). confirm: a button() (destructive, validity or t2).
    Rung 3 needs typed=; strings issued by the caller. Tokens: color.surface.overlay, elevation.dialog,
    radius.dialog, space.dialog.padding."""
    if rung not in (1, 3):
        raise ValueError("rung_dialog: rung 1 or 3 (§2.4)")
    if rung == 3 and typed is None and not any("loading" in str(c) for c in consequences):
        _live(
            "rung 3 drawn without its typed field: confirm the frame is the loading or outcome form"
        )
    iw = w - 2 * PX[DIALOG_PAD]
    items: list[Node | None] = [text("title", title, HEADING_MD, TEXT_1, w=iw)]
    if lead_in:
        items.append(text("lead-in", lead_in, BODY, TEXT_2, w=iw))
    cons = [
        c if isinstance(c, dict) else text(f"consequence {i}", c, BODY, TEXT_1, w=iw - 12)
        for i, c in enumerate(consequences, 1)
    ]
    if cons:
        items.append(vbox("consequences", cons, {"gap": STACK_XS}, note="a list, read in order"))
    items += [choices, typed, error]
    if ask:
        items.append(text("ask line", copy("e27.shared.ask"), BODY, TEXT_2, w=iw))
    if marker:
        items.append(text("marker", copy(marker), CAPTION, TEXT_3, w=iw))
    cancel = button(
        copy("e27.shared.cancel"), "secondary", "focus" if cancel_focused else "default"
    )
    foot = fit_row(hbox("footer", [cancel, confirm], {"justify": "end", "gap": INSET_SM}, w=iw))
    items.append(foot)
    _src_line("CMP-044 rungs", heading_line(r"^#### CMP-044 — the rungs"))
    return vbox(
        f"CMP-044 ConfirmDialog · rung {rung}",
        items,
        {
            "fill": OVERLAY,
            "shadow": E_DIALOG,
            "radius": R_DIALOG,
            "pad": DIALOG_PAD,
            "gap": STACK_MD,
        },
        w=w,
        note='role="alertdialog", described by its first consequence; Esc = Cancel',
    )


def two_choices(options: Iterable[Node], *, name: str = "CMP-006 RadioGroup · two choices") -> Node:
    """CMP-006, none checked at mount (§2.4): options are radio() rows (a gated one t2_radio())."""
    return vbox(name, list(options), {"gap": STACK_SM})


def radio(label: str, *, second: str | None = None, checked: bool = False, w: int = 560) -> Node:
    """A CMP-006 radio row: the ring (16 px, 1 px color.text.tertiary; checked: the dot color.action.primary.default),
    its label (type.ui.body) and an optional second line (type.ui.caption color.text.secondary)."""
    ring = box(
        "ring",
        [
            at(ellipse("outer", 16, 16, {"stroke": TEXT_3, "strokeWidth": HAIRLINE}), 0, 0),
            at(ellipse("dot", 8, 8, {"fill": ACTION["primary"]}), 4, 4) if checked else None,
        ],
        w=16,
        h=16,
    )
    lab = vbox(
        "text",
        [
            text("label", label, BODY, TEXT_1, w=w - 24),
            text("second", second, CAPTION, TEXT_2, w=w - 24) if second else None,
        ],
        {"gap": STACK_XS},
    )
    return hbox(f"radio · {label[:40]}", [ring, lab], {"gap": INSET_SM, "align": "start"}, w=w)


def t2_radio(label: str, reason_key: str, *, w: int = 560, **fills: Any) -> Node:
    """A gated CMP-006 option inside CMP-079 (§2.4 two choices; §10.1): role kept, the lock leading the label, the
    reason its description line; an arrow onto it checks nothing."""
    ring = box(
        "ring",
        [at(ellipse("outer", 16, 16, {"stroke": TEXT_3, "strokeWidth": HAIRLINE}), 0, 0)],
        w=16,
        h=16,
    )
    lab = vbox(
        "text",
        [t2_label(label), t2_reason(reason(reason_key, **fills), w=w - 24)],
        {"gap": STACK_XS},
    )
    return hbox(
        f"T2 · CMP-079 RbacGate · radio · {label[:32]}",
        [ring, lab],
        {"gap": INSET_SM, "align": "start"},
        w=w,
    )


def overlay(
    panel: Node,
    *,
    x: int | None = None,
    y: int | None = None,
    w: int = FRAME_W,
    h: int = FRAME_H,
    scrim: bool = True,
    scrim_y: int = 0,
    name: str = "overlay",
) -> Node:
    """The overlay layer a frame places over its content (abs at 0, 0): a scrim (color.surface.app at opacity.scrim)
    and the panel at x, y (centred when None). The panel gets a fixed h (a hug board holding text inside this
    non-flex layer renders blank, live lesson 2026-10-27)."""
    pw, ph = round(est_width(panel)), round(est_height(panel))
    p = dict(panel, w=panel.get("w") or pw, h=panel.get("h") or ph)
    px_ = (w - p["w"]) // 2 if x is None else x
    py_ = (h - p["h"]) // 2 if y is None else y
    kids: list[Node | None] = []
    if scrim:
        _fallback("OPACITY")
        kids.append(at(rect("scrim", w, h - scrim_y, APP, o={"opacity": OP_SCRIM}), 0, scrim_y))
    kids.append(at(p, px_, py_))
    return place(box(name, kids, w=w, h=h), 0, 0)


def _src_line(label: str, line: int, doc: str = "d03") -> None:
    """Record a source line."""
    LOG.add("sources", f"{label}: {cite(line, doc=doc)}")


# --- The shells: CMP-087 admin route (§3.1), SCR-010's trading host with SCR-079's drawer (§8), the Pattern
#     documentation surface (§2.6), SCR-016 step 3's inset (§4.4). Chrome is consumed (KIT_CHOICES chrome).
def placeholder(name: str, w: int, h: int = 12, *, fill_: str = HOVER) -> Node:
    """A consumed element drawn as a bar (chrome, unchanged)."""
    return rect(name, w, h, fill_, o={"radius": R_CONTROL})


def topbar(envs: Iterable[str] = ("DEMO", "LIVE"), w: int = FRAME_W) -> Node:
    """CMP-072 TopBar, consumed (§3.1 block A, y 0-48): placeholders and its CMP-074 environment badges, DEMO then
    LIVE for the two-environment session."""
    _choice("chrome")
    left = hbox(
        "left",
        [
            placeholder("wordmark", 32, 16),
            *[env_pill(e, name=f"CMP-074 env badge · {e}") for e in envs],
            placeholder("CMP-105 account picker", 120),
        ],
        {"gap": INSET_MD},
    )
    right = hbox(
        "right",
        [placeholder("CMP-210 HealthChips", 160), placeholder("CMP-211 PanicButtons", 120, 24)],
        {"gap": INSET_MD},
        h=24,
    )
    return hbox(
        "CMP-072 TopBar",
        [left, right, place(rect("divider", w, 1, BORDER_SUBTLE), 0, TOP_H - 1)],
        {"padX": INSET_LG, "justify": "space-between", "fill": APP},
        w=w,
        h=TOP_H,
        note="consumed (§3.1 A)",
    )


def navrail(h: int = BODY_H) -> Node:
    """CMP-071 NavRail collapsed to 64 px, consumed (§3.1 block A)."""
    rows = [
        hbox(f"entry-{i}", [placeholder("glyph", 16, 16)], {"justify": "center"}, w=48, h=32)
        for i in range(1, 6)
    ]
    return vbox(
        "CMP-071 NavRail",
        [*rows, place(rect("divider", 1, h, BORDER_SUBTLE), NAV_W - 1, 0)],
        {"align": "center", "padY": INSET_SM, "gap": INSET_XS, "fill": APP},
        w=NAV_W,
        h=h,
    )


def rightrail(h: int = BODY_H) -> Node:
    """CMP-209 RightRail (240 px) with CMP-211 at its top, consumed (§3.1 block A)."""
    rows = [placeholder("CMP-211 PanicButtons", RIGHT_W - 24, 24)] + [
        placeholder(f"row-{i}", RIGHT_W - 24) for i in range(1, 4)
    ]
    return vbox(
        "CMP-209 RightRail",
        [*rows, place(rect("divider", 1, h, BORDER_SUBTLE), 0, 0)],
        {"gap": INSET_MD, "pad": INSET_MD, "fill": APP},
        w=RIGHT_W,
        h=h,
    )


def statusbar(env: str = "LIVE", w: int = FRAME_W) -> Node:
    """CMP-208 StatusBar, consumed (§3.1 block A, y 752-800)."""
    return hbox(
        "CMP-208 StatusBar",
        [
            placeholder("connection chip", 120),
            env_pill(env, name="env"),
            place(rect("divider", w, 1, BORDER_SUBTLE), 0, 0),
        ],
        {"padX": INSET_LG, "justify": "space-between", "fill": APP},
        w=w,
        h=STATUS_H,
    )


def band(grace: str | None = None) -> Node:
    """CMP-087's band (§3.1 block C, consumed): "Admin area · Accounts" on color.surface.raised, 32 px; grace= the
    `keys` grace line's m:ss ("02:14") at its right end (e27.shell.grace.keys); never focusable."""
    kids = [
        text("label", copy("e27.shell.band"), BODY_STRONG, TEXT_1),
        text("grace", copy("e27.shell.grace.keys", m_ss=grace), CAPTION, TEXT_2) if grace else None,
    ]
    return hbox(
        "CMP-087 band",
        kids,
        {"padX": INSET_LG, "justify": "space-between", "fill": RAISED},
        w=INNER_W,
        h=BAND_H,
        note='role="region" "Admin area"; holds no control',
    )


def strip_item(key: str, env: str = "LIVE", **fills: Any) -> Node:
    """One "Needs your action" item: its words as a CMP-021 link (color.text.link), its CMP-075 pill after it;
    "Attention:" leads its accessible name (§3.4 frame 1)."""
    return hbox(
        f"strip item · {key.rsplit('.', 1)[1]}",
        [text("CMP-021 link", copy(key, **fills), BODY, TEXT_LINK), env_pill(env)],
        {"gap": INSET_SM},
    )


def strip(items: Iterable[Node] = ()) -> Node:
    """CMP-087's strip region (§3.1 block C, 32 px a row): "Needs your action ({n})" and its items, or the empty
    line e27.shell.strip.none."""
    its = list(items)
    kids = (
        [text("title", copy("e27.shell.strip.title", n=len(its)), LABEL, TEXT_2), *its]
        if its
        else [text("none", copy("e27.shell.strip.none"), BODY, TEXT_2)]
    )
    return hbox(
        "CMP-087 strip",
        kids,
        {"wrap": "wrap", "gap": INSET_SM, "minH": CONTROL_COMFORTABLE},
        w=INNER_W,
        note='role="region" "Needs your action"; a list; not live',
    )


def page_header(
    *, h1: str | None = None, meta: str | None = None, primary: Node | None = None
) -> Node:
    """CMP-088 PageHeader (§3.1 block D): the h1 (type.ui.heading-md; default e27.shell.h1), the meta
    (type.ui.caption color.text.tertiary; e.g. copy("e27.shell.meta", hh_mm_ss=…)) and the primary at its end.
    """
    right = hbox(
        "end", [text("meta", meta, CAPTION, TEXT_3) if meta else None, primary], {"gap": INSET_MD}
    )
    return hbox(
        "CMP-088 PageHeader",
        [text("h1", h1 or copy("e27.shell.h1"), HEADING_MD, TEXT_1), right],
        {"justify": "space-between"},
        w=INNER_W,
        h=32,
        note="one h1, the skip link's target",
    )


def add_account(state: str = "default") -> Node:
    """The page header's primary "+ Add account" (e27.shell.cta.add)."""
    return button(copy("e27.shell.cta.add"), "primary", state)


def section_heading(key: str, level: int = 2) -> Node:
    """A region heading: h2 type.ui.heading-sm (e27.shell.region.*), h3 type.ui.label."""
    return text(f"h{level}", copy(key), HEADING_SM if level == 2 else LABEL, TEXT_1)


def footer_marker() -> Node:
    """Block L: e27.shell.footer, type.ui.caption color.text.tertiary."""
    return text("footer marker", copy("e27.shell.footer"), CAPTION, TEXT_3)


def _fit(name: str, kids: list[Node], room: float) -> None:
    """Record a live check when kids' estimated height exceeds room (the route scrolls; the frame clips)."""
    used = (
        sum(est_height(k) for k in kids)
        + PX[dens().step] * max(len(kids) - 1, 0)
        + 2 * PX[INSET_LG]
    )
    if used > room:
        _live(
            f"fit: {name}: content about {used:.0f} px for {room:.0f} px — the frame clips (a page scroll, §3.1: the "
            "board may draw the continuation under the viewport line); check the export"
        )


def admin_frame(
    name: str,
    *,
    content: Iterable[Node | None] = (),
    verdict: Node | None = None,
    notices: Iterable[Node | None] = (),
    banners: Iterable[Node] = (),
    strip_items: Iterable[Node] = (),
    grace: str | None = None,
    h1: str | None = None,
    meta: str | None = None,
    primary: Node | str | None = "add",
    overlays: Iterable[Node] = (),
    footer: bool = True,
    env: str = "LIVE",
    h: int = FRAME_H,
) -> Node:
    """A frame in CMP-087 at 1280 x h, comfortable (§3.1): TopBar → [CMP-092 banners] → NavRail | the content:
    band → 4 px rule → strip → PageHeader → the verdict line → notices → content → footer marker | RightRail →
    StatusBar, then overlays (overlay(…)). h > 800 draws the page's continuation under the viewport line (§3.1).
    """
    if dens().name != "comfortable":
        raise ValueError(
            "an admin frame is comfortable (BQ-4): build it outside k.density('compact')"
        )
    above = [topbar(), *banners]
    body_h = int(h - STATUS_H - sum(est_height(n) for n in above))
    prim = add_account() if primary == "add" else primary
    mk = [
        k
        for k in [
            band(grace),
            rect("CMP-087 rule", INNER_W, RULE_H, TEXT_3),
            strip(strip_items),
            page_header(h1=h1, meta=meta, primary=prim if isinstance(prim, dict) else None),
            verdict,
            *notices,
            *content,
            footer_marker() if footer else None,
        ]
        if k
    ]
    _fit(name, mk, body_h)
    main = vbox(
        "content",
        mk,
        {"pad": INSET_LG, "gap": dens().step, "fill": APP, "clip": True},
        w=MAIN_W,
        h=body_h,
    )
    body = hbox(
        "body", [navrail(body_h), main, rightrail(body_h)], {"align": "start"}, w=FRAME_W, h=body_h
    )
    kids = [*above, body, statusbar(env), *overlays]
    if h > FRAME_H:
        kids.append(
            place(rect("viewport line (800)", FRAME_W, 1, STATUS["warning.strong"]), 0, FRAME_H)
        )
    return vbox(
        name,
        kids,
        {"fill": APP, "clip": True},
        w=FRAME_W,
        h=h,
        note="CMP-087 AdminLayout, 1280 x 800, comfortable (§3.1)",
    )


def trading_frame(name: str, *, overlays: Iterable[Node] = (), env: str = "LIVE") -> Node:
    """A frame on SCR-010's trading host, compact (§8): TopBar → NavRail | the workspace (a placeholder canvas) |
    RightRail → StatusBar → overlays (overlay(drawer(…), x=FRAME_W - DRAWER_W, y=TOP_H))."""
    canvas = placeholder("E10-D02 workspace canvas", MAIN_W - 32, BODY_H - 32, fill_=CANVAS)
    main = vbox("workspace", [canvas], {"pad": INSET_LG, "fill": APP}, w=MAIN_W, h=BODY_H)
    body = hbox("body", [navrail(), main, rightrail()], {"align": "start"}, w=FRAME_W, h=BODY_H)
    _choice("chrome")
    return vbox(
        name,
        [topbar(), body, statusbar(env), *overlays],
        {"fill": APP, "clip": True},
        w=FRAME_W,
        h=FRAME_H,
        note="SCR-010 trading shell (host), 1280 x 800",
    )


def drawer(
    title: str, blocks: Iterable[Node | None], *, close_focused: bool = False, w: int = DRAWER_W
) -> Node:
    """SCR-079's CMP-046 modal drawer (§8 anatomy): color.surface.overlay, elevation.dialog, a 1 px inline-start edge
    (color.border.default), the header row (the h2 type.ui.heading-sm, [Close] — CMP-002 with the local close icon,
    name "Close"), then the blocks at the density's step; full height under the TopBar. Returns the overlay layer
    at the frame's right edge."""
    iw = w - 2 * PX[dens().pad if dens().name == "compact" else INSET_MD] - 8
    close = hbox(
        "CMP-002 Close",
        [icon("close icon", "close", TEXT_2)],
        {"justify": "center", "radius": R_CONTROL},
        w=dens().control,
        h=dens().control,
        note='accessible name "Close" (e27.shared.close)',
    )
    if close_focused:
        close = focus_ring(close)
    head = hbox(
        "header",
        [text("h2", title, HEADING_SM, TEXT_1, w=iw - dens().control - 8), close],
        {"justify": "space-between", "align": "start"},
        w=iw,
    )
    panel = vbox(
        "CMP-046 Drawer",
        [head, *blocks],
        {"fill": OVERLAY, "shadow": E_DIALOG, "pad": INSET_MD, "gap": dens().step, "clip": True},
        w=w,
        h=BODY_H,
        note='role="dialog", aria-modal="true", labelled by the h2',
    )
    edge = place(rect("inline-start edge", 1, BODY_H, BORDER_DEFAULT), 0, 0)
    panel["kids"] = unique_names([edge, *panel["kids"]])
    _src_line("SCR-079 drawer anatomy", heading_line(r"^## 8\. SCR-079"))
    return overlay(panel, x=FRAME_W - w, y=TOP_H, h=FRAME_H, scrim_y=TOP_H, name="overlay · drawer")


def doc_frame(name: str, kids: Iterable[Node | None], *, w: int = DOC_W) -> Node:
    """A Pattern frame (§2.6): a 1280 px documentation surface on color.surface.canvas, height hugging."""
    _choice("doc")
    return vbox(
        name, list(kids), {"fill": CANVAS, "pad": INSET_XL, "gap": STACK_LG, "radius": R_CARD}, w=w
    )


def inset_frame(name: str, kids: Iterable[Node | None], *, w: int = INSET_CARD_W) -> Node:
    """SCR-016 step 3 as a card inset (§4.4; BQ-1): color.surface.raised, radius.card, space.inset.xl, comfortable."""
    _choice("inset")
    return vbox(
        name,
        list(kids),
        {
            "fill": RAISED,
            "pad": INSET_XL,
            "gap": STACK_MD,
            "radius": R_CARD,
            "stroke": BORDER_SUBTLE,
            "strokeWidth": HAIRLINE,
        },
        w=w,
    )


# --- The annotation layer (§0 L199-200: stamps and strips are board annotations, never product UI).
def pill(
    chars: str,
    *,
    ink: str = TEXT_2,
    stroke: str | None = BORDER_DEFAULT,
    fill_: str | None = None,
    typo: str = LABEL,
    name: str = "pill",
    w: int | None = None,
) -> Node:
    """An outlined (or filled) radius.badge pill holding one line (board chrome)."""
    o: dict[str, Any] = {"radius": R_BADGE, "padX": INSET_SM, "padY": INSET_XS}
    if stroke:
        o.update(stroke=stroke, strokeWidth=HAIRLINE)
    if fill_:
        o["fill"] = fill_
    return hbox(name, [text("label", chars, typo, ink, w=w)], o)


def not_served(gap_owner: str, what: str | None = None, *, w: int | None = None) -> Node:
    """A "not yet served — {gap}, {owner}" strip (§0 L199-200) for the cell's annotation layer: gap_owner exactly as
    the spec writes it (GAPS: "G-1, #895 / #896", "G-8, #895 / #898", "G-12, #3657", "D03-G1, #896", "G-4, #897",
    "G-7, #898"); what= names the target state it stamps (board chrome)."""
    if gap_owner not in GAPS:
        raise KeyError(f"not_served({gap_owner!r}): the spec writes {sorted(GAPS)}")
    _choice("strip")
    chars = f"not yet served — {gap_owner}" + (f" · {what}" if what else "")
    LOG.add("not_served", f"{chars} ({cite(GAPS[gap_owner])})")
    return pill(
        chars,
        ink=TEXT_1,
        stroke=STATUS["warning.strong"],
        fill_=STATUS["warning.subtle"],
        name="strip · not yet served",
        w=w,
    )


def proposed_stamp(ids: Iterable[str], *, note: str = "owner approval pending") -> Node:
    """A PROPOSED stamp naming its decision ids (HD1-HD17, BQ-n riders, D03-A / C / G / H / D / Q rows; each must be
    a row id of the spec, DECISION_IDS)."""
    xs = list(ids)
    bad = [x for x in xs if x not in DECISION_IDS]
    if bad or not xs:
        raise KeyError(f"proposed_stamp({xs}): unknown ids {bad} (one of BQ-n, HDn, D03-xn)")
    for x in xs:
        LOG.add("decisions", f"PROPOSED · {x} ({cite(DECISION_IDS[x])})")
    return pill(
        f"PROPOSED · {', '.join(xs)} ({note})",
        ink=STATUS["warning.strong"],
        stroke=STATUS["warning.strong"],
        name="stamp PROPOSED",
    )


# --- Cells: one frame (or, on board 10, one specimen) with its caption row and annotation layer.
_META: dict[str, dict[str, Any]] = (
    {}
)  # cell name -> its facts (board() reads them; reset by write_sheet)


def cell_name(frame_name: str) -> str:
    """The "/"-free name of a frame's cell: "cell · SCR-125 · ok"."""
    return "cell · " + re.sub(r"\s*/\s*", " · ", frame_name)


def _has_t2(n: Node) -> bool:
    """True when n draws a T2 control (a node named "T2 …")."""
    return any(str(x.get("name", "")).startswith("T2") for _p, x in walk(n))


def _annotation_layer(strips: Iterable[Node], notes: Iterable[str], w: int) -> Node | None:
    """The cell's annotation-layer row (strips, then notes as captions), or None."""
    kids: list[Node | None] = [*strips, *(caption(x, w, name="note") for x in notes)]
    if not [k for k in kids if k]:
        return None
    return vbox("annotation layer", kids, {"gap": STACK_XS}, w=w)


def cell(
    frame_node: Node,
    *,
    strips: Iterable[tuple[str, str | None]] = (),
    notes: Iterable[str] = (),
    proposed: Iterable[str] = (),
) -> Node:
    """A frame's CELL: the caption row (the frame's exact name, type.ui.heading-sm, then its PROPOSED stamp), the frame,
    then the annotation layer (not_served(gap, what) for each (gap, what) in strips; notes as captions). Checks the
    name is an E27-D02 frame and that the frame draws T2 exactly where E27-D02 §7 says ("shows T2").
    """
    nm = frame_node["name"]
    if nm not in INVENTORY:
        raise ValueError(f"cell(): {nm!r} is not an E27-D02 §7 frame name")
    inv = INVENTORY[nm]
    if inv.t2 != _has_t2(frame_node):
        raise ValueError(
            f"cell({nm!r}): E27-D02 §7 says {'it shows' if inv.t2 else 'no'} T2 ({cite(inv.line, doc='d02')})"
            f" but the frame draws {'none' if inv.t2 else 'a T2 control'}"
        )
    ids = list(proposed)
    _choice("cell")
    w = round(est_width(frame_node))
    cap = hbox(
        "caption row",
        [text("caption", nm, HEADING_SM, TEXT_1), proposed_stamp(ids) if ids else None],
        {"gap": INSET_MD, "wrap": "wrap"},
        w=w,
    )
    sts = [not_served(g, what) for g, what in strips]
    layer = _annotation_layer(sts, notes, w)
    if nm in HIFI:
        hf = HIFI[nm]
        LOG.add(
            "sources",
            f"{nm}: hi-fi row {cite(hf.line)} ({hf.section.split(' (')[0]}); E27-D02 §7 "
            f"{cite(inv.line, doc='d02')}",
        )
    out = vbox(cell_name(nm), [cap, frame_node, layer], {"gap": STACK_MD})
    _META[out["name"]] = {
        "frame": nm,
        "proposed": ids,
        "strips": [s["kids"][0]["chars"] for s in sts],
        "t2": inv.t2,
    }
    return out


def frame(
    name: str,
    build: Callable[[], dict[str, Any] | Node] | None = None,
    *,
    strips: Iterable[tuple[str, str | None]] = (),
    notes: Iterable[str] = (),
    proposed: Iterable[str] = (),
    density_: str | None = None,
) -> Node:
    """One frame's CELL, built by its surface inside its density (BQ-4 / HD12: SCR-079 compact, the rest
    comfortable; density_= overrides, e.g. SCR-079's one comfortable inset): build() returns either the frame node
    itself (named exactly name) or the keyword arguments of the surface's builder — admin_frame (CMP-087 and
    SCR-125..129: content=, verdict=, notices=, banners=, strip_items=, grace=, meta=, primary=, overlays=, h=),
    trading_frame (SCR-079: overlays=[drawer(…)]), inset_frame (SCR-016: kids=), doc_frame (Pattern: kids=).
    """
    sf = surface(name)
    dn = density_ or ("compact" if sf == "SCR-079" else "comfortable")
    with density(dn):
        got = build() if build else {}
        if isinstance(got, dict) and got.get("t") == "board":
            fr = got
            if fr["name"] != name:
                raise ValueError(f"frame({name!r}): build() returned a frame named {fr['name']!r}")
        else:
            kw = dict(got)
            if sf == "Pattern":
                fr = doc_frame(name, kw.pop("kids"), **kw)
            elif sf == "SCR-016":
                fr = inset_frame(name, kw.pop("kids"), **kw)
            elif sf == "SCR-079":
                fr = trading_frame(name, **kw)
            else:
                fr = admin_frame(name, **kw)
    return cell(fr, strips=strips, notes=notes, proposed=proposed)


def specimen(
    title: str,
    kids: Iterable[Node | None],
    *,
    notes: Iterable[str] = (),
    proposed: Iterable[str] = (),
    w: int | None = None,
) -> Node:
    """A board-10 SPECIMEN cell (no inventory frame, §0 L227): the caption row (title, PROPOSED stamp) and a
    color.surface.canvas card holding kids (focus orders, landmarks, live regions, 125 % / 200 % / 150 %-text
    specimens, the forced-colours strip), then notes. Texts inside the card follow the frame copy rule (issued).
    """
    ids = list(proposed)
    body = vbox(
        "specimen",
        list(kids),
        {
            "fill": CANVAS,
            "pad": INSET_LG,
            "gap": STACK_MD,
            "radius": R_CARD,
            "stroke": BORDER_SUBTLE,
            "strokeWidth": HAIRLINE,
        },
        w=w,
    )
    cw = round(est_width(body))
    cap = hbox(
        "caption row",
        [text("caption", title, HEADING_SM, TEXT_1), proposed_stamp(ids) if ids else None],
        {"gap": INSET_MD, "wrap": "wrap"},
        w=cw,
    )
    nm = "specimen cell · " + re.sub(r"\s*/\s*", " · ", title)
    out = vbox(nm, [cap, body, _annotation_layer([], notes, cw)], {"gap": STACK_MD})
    _META[out["name"]] = {
        "frame": None,
        "specimen": title,
        "proposed": ids,
        "strips": [],
        "t2": False,
    }
    return out


# --- The annotation column and the board.
ANN_ORDER = (
    "Sources",
    "PROPOSED stamps",
    "Not yet served",
    "Not drawn — the text is binding",
    "Kit choices",
    "Notes",
)
ROOT_O = {"dir": "column", "align": "start", "fill": APP, "pad": INSET_LG, "gap": INSET_LG}
NOT_DRAWN_SET = (
    "SCR-019's three frames (content-only rows in §8, CMP-097 chrome is E09's, BQ-1); the light twins of "
    "boards 03 and 06-10; every high-contrast board (§9's matrix, BQ-3); per-state sheets; SCR-079's "
    "comfortable frames beyond board 09's inset (BQ-4) — §0 L229-235"
)


def annotation(
    metas: list[dict[str, Any]],
    nn: int,
    *,
    sources: Iterable[str] = (),
    notes: Iterable[str] = (),
    not_drawn: Iterable[str] = (),
) -> Node:
    """The board's 400 px annotation column (color.surface.canvas card): Sources (the spec at its head, §0, the frames'
    hi-fi row lines, then sources=), PROPOSED stamps (per cell), Not yet served (every strip on the board), Not drawn
    (§0's set, then not_drawn=), Kit choices (the keys used), Notes (notes=)."""
    src = [
        (
            f"{DOCS['d03'][1]} @ {SPEC_HEAD} (frozen, md5 {DOCS['d03'][2][:8]}); §0 board row {cite(BOARDS[nn].line)}"
            if nn
            else f"{DOCS['d03'][1]} @ {SPEC_HEAD}"
        )
    ]
    rows = sorted({HIFI[m["frame"]].line for m in metas if m.get("frame") in HIFI})
    if rows:
        src.append(
            "hi-fi rows "
            + ", ".join(f"L{x}" for x in rows)
            + "; E27-D02 §7 frame names; §9 contrast matrix; "
            "§10.1 T2; §12 copy deck"
        )
    src += list(sources)
    st = [
        f"{m['frame'] or m.get('specimen')}: PROPOSED · {', '.join(m['proposed'])}"
        for m in metas
        if m["proposed"]
    ]
    ns = [f"{m['frame']}: {s}" for m in metas for s in m["strips"]]
    used = sorted(
        {
            ln.split("(", 1)[1].split(")", 1)[0]
            for ln in LOG.notes["deviations"]
            if ln.startswith("kit choice (")
        }
    )
    vals = {
        "Sources": src,
        "PROPOSED stamps": st or ["— none on this board"],
        "Not yet served": ns or ["— none"],
        "Not drawn — the text is binding": [NOT_DRAWN_SET, *not_drawn],
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


def _grid_width(cells: list[Node], cols: int | None) -> tuple[int, int]:
    """(grid width, cells per row): cols per row, else as many as fit in GRID_MAX_W."""
    ws = [round(est_width(c)) for c in cells]
    gap = PX[GRID_GAP]
    rows: list[list[int]] = [[]]
    for wd in ws:
        cur = rows[-1]
        full = (cols is not None and len(cur) >= cols) or (
            cols is None and bool(cur) and sum(cur) + gap * len(cur) + wd > GRID_MAX_W
        )
        if full:
            rows.append([])
        rows[-1].append(wd)
    width = max(sum(r) + gap * (len(r) - 1) for r in rows)
    if width > GRID_MAX_W:
        raise ValueError(f"grid {width} px wider than {GRID_MAX_W}: fewer cells per row")
    return width, max(len(r) for r in rows)


def board(
    nn: int,
    cells: Iterable[Node],
    *,
    source: str,
    cols: int | None = None,
    notes: Iterable[str] = (),
    not_drawn: Iterable[str] = (),
    sources: Iterable[str] = (),
) -> dict[str, Any]:
    """A board: the root ("E27-D03 / NN slug" at grid_xy(nn), ROOT_O, w from the grid, h hugging) holding the head
    (name, "Source: …", the theme line, the file and page line), the body (the cells in a wrapping grid — cols per row
    or as many as fit — beside the annotation column) and §0's stamp "page E27-D03 · board NN · r1". The cells'
    frames must be exactly §0's for NN (a twin: its dark board's; board 10: specimen cells only); nn=0 is the
    self-test."""
    cs = list(cells)
    metas = []
    for c in cs:
        m = _META.get(re.sub(r" · \d+$", "", c["name"]))
        if m is None:
            raise ValueError(
                f"board {nn:02d}: {c['name']!r} was not built by cell() / frame() / specimen()"
            )
        metas.append(m)
    names = [m["frame"] for m in metas if m["frame"]]
    if nn:
        want = list(BOARDS[nn].frames)
        if sorted(names) != sorted(want):
            raise ValueError(
                f"board {nn:02d} frames differ from §0 {cite(BOARDS[nn].line)}: missing "
                f"{sorted(set(want) - set(names))}, extra {sorted(set(names) - set(want))}"
            )
        if nn == 10 and not any(m.get("specimen") for m in metas):
            raise ValueError("board 10 holds specimen cells (§0: no inventory frame)")
        if names != want:
            LOG.add(
                "deviations",
                f"board {nn:02d} orders its frames differently from §0 {cite(BOARDS[nn].line)}",
            )
        if BOARDS[nn].twin_of:
            _choice("light")
    theme = theme_of(nn)
    gw, per_row = _grid_width(cs, cols)
    grid = hbox(
        "grid", cs, {"wrap": "wrap", "colGap": GRID_GAP, "rowGap": GRID_GAP, "align": "start"}, w=gw
    )
    ann = annotation(metas, nn, sources=sources, notes=notes, not_drawn=not_drawn)
    body = hbox("body", [grid, ann], {"align": "start", "gap": INSET_LG})
    bw = gw + PX[INSET_LG] + ANN_W
    twin = (
        f"the light twin of board {BOARDS[nn].twin_of:02d}: the same frames, semantic-light applied through the "
        "file's light theme at export"
        if nn and BOARDS[nn].twin_of
        else "tokens by name"
    )
    head = vbox(
        "head",
        [
            text("title", board_name(nn), HEADING_MD, TEXT_1),
            text("source", f"Source: {source}", CAPTION, TEXT_2, w=bw),
            text(
                "theme",
                f"Theme: {theme} ({twin}); densities per BQ-4 (SCR-125..129 and SCR-016 comfortable, SCR-079 "
                "compact); fixture values only; every time UTC",
                CAPTION,
                TEXT_2,
                w=bw,
            ),
            text("page", f"File {FILE} · page {PAGE}", CAPTION, TEXT_2, w=bw),
        ],
        {"gap": STACK_XS},
    )
    foot = text("footer", f"page {SET} · board {nn:02d} · {REV}", CAPTION, TEXT_3)
    kids = [head, body, foot]
    h = est_height(box("probe", kids, ROOT_O))
    if h > PITCH_Y - 40:
        raise ValueError(
            f"board {nn:02d} is about {h:.0f} px tall (> {PITCH_Y - 40}): more cells per row"
        )
    _choice("page")
    _live(f"render on page '{PAGE}' (mkcall4.py … --page '{PAGE}'; its default would be '{SET}')")
    _live(
        f"root '{board_name(nn)}': hugs its content (about {bw + 2 * ROOT_PAD} x {h:.0f} px estimated, "
        f"{per_row} cells per row)"
    )
    x, y = grid_xy(nn)
    root = {"name": board_name(nn), "w": bw + 2 * ROOT_PAD, "x": x, "y": y, "o": dict(ROOT_O)}
    return {
        "board": root,
        "kids": kids,
        "export": export_path(nn),
        "nn": nn,
        "page": PAGE,
        "frames": names,
        "theme": theme,
        "est_h": round(h),
        "metas": metas,
    }


# --- Sections (the E27-D02 / E05-D02 packer; a §0 frame name holds "/" so it is atomic unless split).
def _size(section: dict[str, Any]) -> int:
    """A section's size in bytes as the validator measures it (json.dumps defaults)."""
    return len(json.dumps(section))


def _atomic(n: Node) -> bool:
    """A node no section can address inside: a board whose name carries "/" (a §0 frame not split)."""
    return n.get("t") == "board" and "/" in str(n.get("name"))


def _split_frames(n: Node, budget: int) -> Node:
    """A copy of n in which every frame whose own section would exceed budget is renamed with SPLIT_STANDIN for "/"
    (so sections can address inside it), each rename recorded as a live check (KIT_CHOICES split).
    """
    if n.get("t") != "board":
        return n
    out = dict(n)
    if (
        _atomic(n) and _size({"into": "", "node": n}) > budget - 300
    ):  # 300 bytes: room for the into path
        out["name"] = str(n["name"]).replace("/", SPLIT_STANDIN)
        _choice("split")
        _live(
            f"rename frame {out['name']!r} to {n['name']!r} after the board's last section (split across sections)"
        )
    if n.get("kids"):
        out["kids"] = [_split_frames(k, budget) for k in n["kids"]]
    return out


_MEMO: dict[tuple[int, str, int], list[dict[str, Any]]] = {}


def _pack(n: Node, path: str, room: int, budget: int) -> tuple[Node | None, list[tuple[str, Node]]]:
    """n pruned to at most room bytes (the bare board, its longest prefix of whole kids, and the next kid packed the
    same way when that needs fewer sections), plus the cut parts as (parent path, node) in render order.
    """
    if len(json.dumps(n)) <= room:
        return n, []
    if n["t"] != "board" or _atomic(n):
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
    """The sections that render n under into, in render order; a leaf or an atomic frame is one section."""
    key = (id(n), into, budget)
    if key not in _MEMO:
        if n["t"] != "board" or _atomic(n):  # _split_frames left only frames that fit a section
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
    """Split a board (board()'s dict) into sections under budget bytes with correct into paths: frames too big for a
    section are renamed with '∕' first (_split_frames); the head, the body (cells, then the annotation column), the
    footer. Raises over SECTION_HARD."""
    out: list[dict[str, Any]] = []
    kids = [_split_frames(n, budget) for n in bd["kids"]]  # kept alive: _MEMO is keyed by id()
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
                f"section {s['node']['name']!r} is {z} bytes (> the {budget}-byte budget): an atomic frame or leaf"
            )
    return out


# --- Guards write_sheet() applies (the live lessons of 2026-10-27, the copy rule, T2 and the per-set-file rules).
def _is_frame(n: Node) -> bool:
    """True for a §0 frame board (its name, or its split stand-in) or a board-10 specimen card."""
    nm = str(n.get("name", "")).replace(SPLIT_STANDIN, "/")
    return n.get("t") == "board" and (nm in INVENTORY or nm == "specimen")


def unissued(nodes: Iterable[Node]) -> list[str]:
    """Every text inside a frame (or a specimen card) whose chars copy() / reason() / say() / fixture() did not issue
    (nor NOTATION)."""
    bad: list[str] = []

    def go(n: Node, inside: bool) -> None:
        here = inside or _is_frame(n)
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


def annotation_in_frame(nodes: Iterable[Node]) -> list[str]:
    """Paths of stamps or 'not yet served' strips drawn INSIDE a frame (§0: the annotation layer, never product UI)."""
    bad: list[str] = []
    for n in nodes:
        for p, x in walk(n):
            if _is_frame(x):
                bad += [
                    q
                    for q, y in walk(x)
                    if str(y.get("name")).startswith(("strip · not yet served", "stamp PROPOSED"))
                ]
    return bad


def _has_text(x: Node) -> bool:
    """True when x is or holds a text."""
    return x.get("t") == "text" or any(_has_text(k) for k in x.get("kids") or [])


def no_h(n: Node) -> list[str]:
    """Paths of boards that hold no text and carry no explicit h (Penpot would give them its 100 px default)."""
    return [p for p, x in walk(n) if x.get("t") == "board" and not x.get("h") and not _has_text(x)]


def hug_in_static(n: Node) -> list[str]:
    """Paths of hug boards (no fixed w and h) holding text directly inside a NON-flex board (they hug to 0 before the
    text is measured and render blank)."""
    bad = []
    for p, x in walk(n):
        if x.get("t") == "board" and not (x.get("o") or {}).get("dir"):
            for k in x.get("kids") or []:
                if k.get("t") == "board" and _has_text(k) and not (k.get("w") and k.get("h")):
                    bad.append(f"{p}/{k['name']}")
    return bad


def missing_xy(n: Node) -> list[str]:
    """Paths of nodes inside a NON-flex board without x and y (renderer v4.3 places them at the parent's origin)."""
    bad = []
    for p, x in walk(n):
        if x.get("t") == "board" and not (x.get("o") or {}).get("dir"):
            bad += [f"{p}/{k['name']}" for k in x.get("kids") or [] if "x" not in k or "y" not in k]
    return bad


def dimmed(nodes: Iterable[Node]) -> list[str]:
    """Paths binding color.text.disabled / opacity.disabled (§10.1 and §2.2: never on T2, never in a disabled row;
    the dimmed look is the rejected t2-dimmed row)."""
    bad = []
    for n in nodes:
        for p, x in walk(n):
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
    """Write the sheet JSON for board()'s dict bd into KIT_DIR: {board, page, sections, export, notes} (page = PAGE,
    which the renderer passes as --page). Refuses: a frame text not issued (invented copy); a stamp or strip inside a
    frame; a text-free board without h; a hug board holding text inside a non-flex board; a node in a non-flex board
    without x / y; an inst node or an icon outside ICONS; color.text.disabled / opacity.disabled anywhere; a section
    over SECTION_HARD. Packs the sections, writes, runs the validator with the component inventory (raises on exit
    != 0), keeps the notes in LAST_NOTES and clears the collector. Returns the validator's summary line.
    """
    out = Path(path).resolve()
    if out.parent != KIT_DIR:
        raise ValueError(f"sheets are written only into {KIT_DIR}")
    unknown = set(notes or {}) - set(NOTE_KINDS)
    if unknown:
        raise KeyError(f"notes keys {sorted(unknown)}; allowed {NOTE_KINDS}")
    checks = (
        (
            "a frame draws only the pinned copy (copy / reason / say / fixture): these texts were not issued",
            unissued(bd["kids"]),
        ),
        (
            "stamps and 'not yet served' strips sit on the annotation layer, never inside a frame",
            annotation_in_frame(bd["kids"]),
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
            "nodes inside a non-flex board need x and y (renderer v4.3 puts them at the parent origin)",
            [p for n in bd["kids"] for p in missing_xy(n)],
        ),
        (
            "color.text.disabled / opacity.disabled are never drawn (§10.1, §2.2)",
            dimmed(bd["kids"]),
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
    merged["sources"][:0] = [
        f"spec {DOCS[d][1]} at {SPEC_HEAD} md5 {DOCS[d][2]} (frozen copy {DOCS[d][0].name})"
        for d in DOCS
    ]
    merged["sources"].insert(
        len(DOCS),
        f"Penpot file {FILE!r}, page {PAGE!r}; kit e27d03kit.py md5 "
        f"{_md5(Path(__file__))}; renderer {RENDERER.name}",
    )
    sheet = {
        "board": bd["board"],
        "page": PAGE,
        "sections": secs,
        "export": bd["export"],
        "notes": merged,
    }
    out.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    LAST_NOTES.clear()
    LAST_NOTES.update(merged)
    reset_notes()
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
    if c.get("page") != PAGE:
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
    """NN-<slug>.md beside the sheet (after write_sheet()). Line 3 is the drivers' line: "File `E27-D03 boards`, page
    `E27-D03 Accounts and key vault hi-fi` (render with `--page`); export …; sheet … (validated); theme dark|light."
    Then every frame with its hi-fi row, the content checks, the live checks, LAST_NOTES and the shape count.
    """
    path = KIT_DIR / f"{stem(nn)}.md"
    sheet = KIT_DIR / f"{stem(nn)}.json"
    rep = shape_report(sheet)
    out = [
        f"# {board_name(nn)}",
        "",
        (
            f"File `{FILE}`, page `{PAGE}` (render with `--page`); export "
            f"`{export_path(nn)}`; sheet `{sheet.name}` (validated); theme {theme_of(nn)}."
        ),
        "",
    ]
    if summary:
        out += [summary, ""]
    out += ["## Frames", ""]
    for m in bd.get("metas", []):
        if m.get("frame"):
            hf = HIFI.get(m["frame"])
            out.append(
                f"- `{m['frame']}` — hi-fi row {cite(hf.line) if hf else '—'}; E27-D02 §7 "
                f"{cite(INVENTORY[m['frame']].line, doc='d02')}"
                + (" · shows T2" if m["t2"] else "")
                + (f" · PROPOSED {', '.join(m['proposed'])}" if m["proposed"] else "")
            )
        else:
            out.append(f"- specimen `{m.get('specimen')}`")
    out += ["", "## Content checks", ""] + ([f"- {x}" for x in checks] or ["- (none given)"])
    out += ["", "## Live checks for the drawer", ""] + [f"- {x}" for x in live]
    out += [f"- {x}" for x in LAST_NOTES.get("live_checks", [])]
    for kind, head in (
        ("not_served", "Not yet served (annotation layer)"),
        ("decisions", "PROPOSED stamps"),
        ("not_drawn", "Not drawn — the text is binding"),
        ("copy_keys", "Strings used"),
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
BRIEF_BOARDS = (
    "01 cmp-175-key-states",
    "02 cmp-175-key-states-light",
    "03 components-and-looks",
    "04 scr-125-128-accounts",
    "05 scr-125-128-accounts-light",
    "06 scr-126-add-key",
    "07 scr-127-rotate",
    "08 scr-129-confirm",
    "09 scr-079-drawer",
    "10 keyboard-zoom-forced-colours",
)  # the lane brief


def _token_slots() -> list[tuple[str, str]]:
    """(constant name, token) for every kit token constant (str constants and the token tables)."""
    out = []
    for k, v in globals().items():
        if not k.isupper() or k.startswith("_"):
            continue
        vals = (
            list(v.values())
            if isinstance(v, dict) and k in ("ACTION", "STATUS")
            else (
                [x for pair in v.values() for x in pair]
                if k in ("CLASS_TOK", "CHIP_TONE")
                else [x for x in v.values() if isinstance(x, str)] if k == "T2_SHAPE" else [v]
            )
        )
        for x in vals:
            if isinstance(x, str) and TOKEN_RE.fullmatch(x):
                out.append((k, x))
    return out


_TOKENS: dict[str, set[tuple[str, str]]] = {}


def token_table() -> dict[str, set[tuple[str, str]]]:
    """token-sync.json as {name: {(set, type)}}."""
    if not _TOKENS:
        for s, n, t, _v in json.loads(TOKENS_FILE.read_text(encoding="utf-8")):
            _TOKENS.setdefault(n, set()).add((s, t))
    return _TOKENS


def _exercise() -> list[Node]:
    """One cell per surface and shared piece, on real frames and deck strings (the self-test board)."""
    menu_items = copies("e27.scr125.menu.items")

    # Pattern frame 2: the aggregate forms and the CMP-175 variant set in both forms.
    def f2() -> dict[str, Any]:
        forms = [
            verdict_line("dated", n=4, hh_mm="14:02", w=1200),
            verdict_line("overdue", hh_mm="13:47", w=1200),
            verdict_line("loading", w=1200),
        ]
        badges = hbox(
            "badges",
            [
                cmp175(
                    v,
                    "badge",
                    **(
                        {"hh_mm": "14:02"}
                        if "{hh:mm}" in CMP175[v].word
                        else {"n": 12} if "{n}" in CMP175[v].word else {}
                    ),
                )
                for v in (
                    "verified",
                    "withdrawal-detected (critical)",
                    "IP-mismatch",
                    "expiring",
                    "not checked",
                    "check overdue",
                    "read-only (stored; BQ-5 rider, OWNER-LEVEL)",
                )
            ],
            {"gap": INSET_SM, "wrap": "wrap"},
            w=1200,
        )
        inline = hbox(
            "inline",
            [
                cmp175("allowlist matches", "inline", lead=False),
                cmp175("trade-only", "inline"),
                state_badge("Rotation due in {n} d", n=12),
                state_badge("OK"),
                state_badge("Disabled"),
                env_pill("LIVE"),
                env_pill("DEMO"),
                masked_id("...a1b2"),
            ],
            {"gap": INSET_SM, "wrap": "wrap"},
            w=1200,
        )
        return {"kids": [*forms, badges, inline]}

    c2 = frame(
        "Pattern / withdrawal verdict: dated, overdue, failed, unavailable, no keys",
        f2,
        proposed=["HD1", "BQ-6"],
    )

    # Pattern frame 4: T2 anatomy (button, menu item, radio) beside the validity form.
    def f4() -> dict[str, Any]:
        return {
            "kids": [
                hbox(
                    "controls",
                    [
                        t2_button(menu_items[2], "keys.kek_unavailable", w=280),
                        button(copy("e27.scr129.revoke.confirm_leave"), "secondary", "validity"),
                        button(copy("e27.shell.cta.add"), "primary", "focus"),
                    ],
                    {"gap": INSET_LG, "align": "start"},
                ),
                menu(
                    [
                        menu_item(menu_items[0]),
                        menu_item(menu_items[3], reason_key="keys.not_signable"),
                        menu_item(menu_items[2], second=copy("e27.shared.ask"), focused=True),
                    ]
                ),
                t2_radio(copy("e27.scr129.revoke.confirm_leave"), "accounts.stop_missing"),
            ]
        }

    c4 = frame("Pattern / T2 anatomy with the E27 state keys", f4)

    # SCR-125 / KEK unavailable: the admin shell, the banner, the KEK notice and a T2 primary.
    def f17() -> dict[str, Any]:
        return {
            "banners": [banner("e27.shell.banner.kek")],
            "verdict": verdict_line("unavailable"),
            "notices": [kek_notice()],
            "grace": "02:14",
            "meta": copy("e27.shell.meta", hh_mm_ss="14:02:11"),
            "strip_items": [strip_item("e27.shell.strip.rotation_due", label="sub_002", n=12)],
            "content": [
                section_heading("e27.shell.region.accounts"),
                t2_button(menu_items[1], "keys.kek_unavailable", w=320),
            ],
        }

    c17 = frame(
        "SCR-125 / KEK unavailable",
        f17,
        strips=[("G-1, #895 / #896", "the per-key facets")],
        notes=["the KEK notice is the one many-pointer node (BQ-9)"],
        proposed=["HD6"],
    )

    # SCR-129 rung 1 over the route.
    def f49() -> dict[str, Any]:
        dlg = rung_dialog(
            copy("e27.scr129.revoke.title", key_id_masked="...c3d4", label="sub_001", ENV="LIVE"),
            [copy("e27.scr129.revoke.not_last", label="sub_001", new="...e5f6")],
            rung=1,
            confirm=button(
                copy("e27.scr129.revoke.confirm", key_id_masked="...c3d4"), "destructive"
            ),
            marker="e27.scr129.marker.revoke",
        )
        return {"verdict": verdict_line("dated", n=4, hh_mm="14:02"), "overlays": [overlay(dlg)]}

    c49 = frame("SCR-129 / revoke a key that is not the last: rung 1", f49, proposed=["HD8"])

    # SCR-079's drawer, compact, with a gated write.
    def f62() -> dict[str, Any]:
        h2 = copy("e27.scr079.h2", label="sub_001", ENV="LIVE", kind=say("Sub-account"))
        blocks = [
            text(
                "caption", copy("e27.scr079.balances.caption", hh_mm_ss="14:02:11"), CAPTION, TEXT_2
            ),
            section_heading("e27.scr079.key.h3", 3),
            masked_id("...c3d4"),
            cmp175("withdrawal-detected (critical)"),
            t2_button(copy("e27.scr079.leverage"), "rbac.view_as", w=440, user="bea"),
        ]
        return {"overlays": [drawer(h2, blocks, close_focused=True)]}

    c62 = frame(
        "SCR-079 / healthy (owner)",
        f62,
        strips=[("G-1, #895 / #896", "the rights and allowlist statements")],
    )

    # SCR-016 step 3 as an inset with the check list.
    def f73() -> dict[str, Any]:
        names = copies("e27.checks.names")
        rows = [
            (names[0], "passed", copy("e27.checks.env.passed", ENV="DEMO")),
            (names[1], "passed", copy("e27.checks.withdrawal.passed", hh_mm="14:02")),
            (names[7], "warning", copy("e27.checks.expiry.expiring", date="2026-11-03", n=7)),
            (names[6], "not checked", copy("e27.checks.not_checked")),
        ]
        foot = fit_row(
            hbox(
                "buttons",
                [
                    button(b, "primary" if i == 2 else "ghost")
                    for i, b in enumerate(copies("e27.scr016.buttons"))
                ],
                {"gap": INSET_SM, "justify": "end"},
                w=INSET_CARD_W - 48,
            )
        )
        return {
            "kids": [text("h1", copy("e27.scr016.h1"), HEADING_MD, TEXT_1), check_list(rows), foot]
        }

    c73 = frame("SCR-016 / step 3 valid: verified and stored", f73)
    sp = specimen(
        "focus order · SCR-125",
        [
            text("order", say("Skip link → TopBar → NavRail"), BODY, TEXT_1),
            focus_ring(env_pill("LIVE")),
        ],
        notes=["board 10 specimen cell"],
        w=480,
    )
    return [c2, c4, c17, c49, c62, c73, sp]


def _negative(check: Callable[[bool, str], None]) -> None:
    """Every refusal the kit promises."""

    def raises(fn: Callable[[], Any], what: str) -> None:
        try:
            fn()
        except (ValueError, KeyError):
            check(True, f"refuses {what}")
            return
        check(False, f"refuses {what}")

    fr = "SCR-125 / ok"
    raises(lambda: say("a string no pinned doc holds, 4f1c"), "an invented string (say)")
    raises(lambda: copy("e27.nope"), "an unknown deck id")
    raises(
        lambda: copy("e27.shell.strip.rotation_due", label="sub_009", n=3),
        "a fill that is not a fixture",
    )
    raises(lambda: copy("e27.shell.strip.rotation_due", label="sub_002"), "a missing fill")
    raises(lambda: reason("keys.made_up"), "an unknown T2 reason key")
    raises(lambda: icon("x", "check", TEXT_1), "an icon the per-set file does not hold")
    raises(lambda: proposed_stamp(["HD99"]), "a PROPOSED id the spec does not hold")
    raises(lambda: not_served("G-99, #1"), "a 'not yet served' gap the spec does not write")
    raises(lambda: node("board", "a/b"), "a '/' in a non-frame name")
    raises(lambda: masked_id("...zzzz"), "a masked id that is not a fixture")
    raises(lambda: field("API key", "abc", write_only=True), "a write-only field showing a value")
    raises(lambda: cmp175("trade-only", lead=False), "lead=False outside the allowlist facet")
    raises(
        lambda: fit_row(hbox("row", [text("a", "x" * 80, BODY, TEXT_1)], w=40)),
        "a row narrower than its children",
    )
    raises(
        lambda: frame(
            fr, lambda: {"content": [t2_button(copy("e27.shell.cta.add"), "keys.kek_unavailable")]}
        ),
        "a frame drawing T2 where E27-D02 §7 shows none",
    )
    raises(lambda: board(4, [frame(fr)], source="t"), "a board whose frames are not §0's")
    probe = {"board": {}, "export": "", "page": PAGE}
    wr = KIT_DIR / "00-neg.json"
    raises(
        lambda: write_sheet(
            wr, dict(probe, kids=[vbox(fr, [text("t", "invented words", BODY, TEXT_1)])])
        ),
        "an unissued text inside a frame",
    )
    raises(
        lambda: write_sheet(wr, dict(probe, kids=[vbox(fr, [not_served("G-1, #895 / #896")])])),
        "a 'not yet served' strip inside a frame",
    )
    raises(
        lambda: write_sheet(
            wr,
            dict(
                probe,
                kids=[
                    box(
                        "static",
                        [at(hbox("hug", [text("t", "x", BODY, TEXT_1)]), 0, 0)],
                        h=40,
                        w=40,
                    )
                ],
            ),
        ),
        "a hug text row in a non-flex board",
    )
    raises(
        lambda: write_sheet(
            wr, dict(probe, kids=[box("static", [rect("r", 4, 4, TEXT_1)], h=40, w=40)])
        ),
        "a node without x / y in a non-flex board",
    )
    raises(
        lambda: write_sheet(
            wr, dict(probe, kids=[hbox("row", [text("label", "x", BODY, TEXT_DISABLED)])])
        ),
        "color.text.disabled anywhere",
    )
    raises(
        lambda: write_sheet(wr, dict(probe, kids=[hbox("empty", [])])),
        "a text-free board without h",
    )
    if wr.exists():
        wr.unlink()
    reset_notes()


def selftest() -> int:
    """Re-check the frozen docs, the registries and every token; exercise the refusals; build, write, validate and
    compact 00-selftest.json; write 00-selftest.md. Prints one line per check; returns the number failing.
    """
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("ok   " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    for _d, (copy_, repo, md5, lab) in DOCS.items():
        check(
            hashlib.md5(spec_bytes(_d)).hexdigest() == md5,
            f"{lab}: frozen copy {copy_.name} md5 {md5}",
        )
        live = WT / repo
        if live.exists() and _md5(live) != md5:
            print(
                f"WARN {lab}: {repo} in this checkout differs from the frozen copy (re-freeze and re-run the boards)"
            )
    check(
        [f"{b.nn:02d} {b.slug}" for b in BOARDS.values()] == list(BRIEF_BOARDS),
        "BOARDS = §0's ten = the brief's",
    )
    check(
        PAGE == "E27-D03 Accounts and key vault hi-fi"
        and f"Page **`{PAGE}`**" in "\n".join(doc_lines()[193:196]),
        f"page {PAGE!r} as §0 L194",
    )
    check(
        [(b.nn, b.twin_of, b.theme) for b in BOARDS.values() if b.theme == "light"]
        == [(2, 1, "light"), (5, 4, "light")],
        "boards 02 and 05 are the light twins of 01 and 04; every other board dark",
    )
    dark = [f for b in BOARDS.values() if not b.twin_of for f in b.frames]
    check(
        len(dark) == 75 and len(set(dark)) == 75,
        f"75 frames on the dark boards, none twice ({len(dark)})",
    )
    check(not BOARDS[10].frames, "board 10 holds no inventory frame (specimens)")
    check(
        len(INVENTORY) == 78 and set(dark) <= set(INVENTORY),
        "E27-D02 §7: 78 frames; every §0 frame is one",
    )
    undrawn = sorted(set(INVENTORY) - set(dark))
    check(
        undrawn == sorted(f for f in INVENTORY if f.startswith("SCR-019")),
        f"not drawn = SCR-019's three: {undrawn}",
    )
    check(
        len(HIFI) == 78 and set(HIFI) == set(INVENTORY),
        f"78 hi-fi rows, one per inventory frame ({len(HIFI)})",
    )
    for f, nn in FRAMES.items():
        bc = HIFI[f].board_cell()
        tw = [t.nn for t in BOARDS.values() if t.twin_of == nn]
        ok = bc.startswith(f"{nn:02d}") and all(f"light {t:02d}" in bc for t in tw)
        if not ok:
            check(
                False,
                f"{f}: hi-fi Board cell {bc!r} names board {nn:02d}"
                + (f" · light {tw}" if tw else ""),
            )
    check(
        all(HIFI[f].board_cell().startswith(f"{FRAMES[f]:02d}") for f in FRAMES),
        "every drawn frame's hi-fi Board cell names its board (and its twin)",
    )
    check(
        all(HIFI[f].board_cell().startswith("not drawn") for f in undrawn),
        "SCR-019 rows say 'not drawn'",
    )
    check(
        sum(i.t2 for i in INVENTORY.values()) == 20,
        f"E27-D02 §7 'shows T2' frames: 20 " f"({sum(i.t2 for i in INVENTORY.values())})",
    )
    check(len(DECK) == 327, f"deck rows 327 (§12.1 audit number): {len(DECK)}")
    e27r = [k for k in REASONS if k.split(".")[0] in ("keys", "accounts", "rbac")]
    check(
        len(e27r) == 15 and all(len(REASONS[k][0]) <= 60 for k in e27r),
        f"§12.2 reason keys: 15 (E27's ten + rbac.*), each <= 60 characters; also {sorted(set(REASONS) - set(e27r))}",
    )
    check(
        len(CMP175) == 13 and all(v.key for k, v in CMP175.items() if k != "read-only (import)"),
        "CMP-175: 13 variants, every stored state on its e27.cmp175.* deck key (the import refusal is CMP-027's)",
    )
    check(
        {v.cls for v in CMP175.values()} <= set(CLASS_TOK),
        "every CMP-175 class has its tokens (§2.1 L412-421)",
    )
    check(
        len(VERDICT) == 8 and set(VERDICT) == set(VERDICT_KEY), "the aggregate line's eight forms"
    )
    check(
        len(SLOT) == 16 and SLOT[0].word.startswith("BLOCKED"),
        "CMP-176's 16 state words, BLOCKED first",
    )
    check(
        len([v for v in FIXTURES.values() if v == "key"]) == 5 and FIXTURES.get("1234567") == "uid",
        f"fixtures L62-65: {len(FIXTURES)} values",
    )
    check(
        all(f"HD{i}" in DECISION_IDS for i in range(1, 18))
        and all(f"BQ-{i}" in DECISION_IDS for i in range(1, 17)),
        f"decision ids: HD1-17, BQ-1..16, D03 rows ({len(DECISION_IDS)})",
    )
    check(len(GAPS) == 6, f"'not yet served' gaps: {sorted(GAPS)}")
    check(
        sorted(x for p in PAIRS for x in p) == [f"{i:02d}" for i in range(1, 11)],
        "PAIRS cover the ten boards once",
    )
    check(RENDERER.exists(), f"renderer {RENDERER.name} present")
    check(len(PAIRS9) == 60, f"§9 matrix pair ids: {len(PAIRS9)}")
    nt = [f for f in FRAMES if not hifi_tokens(f)]
    check(
        len(nt) == 13,
        f"hi-fi rows resolving to tokens: {len(FRAMES) - len(nt)} of {len(FRAMES)} (the rest read "
        f"'as §3.1' / 'as frame N': {nt})",
    )
    nk = [f for f in FRAMES if not hifi_copy_keys(f)]
    check(
        len(nk) == 5,
        f"hi-fi rows citing deck ids: {len(FRAMES) - len(nk)} of {len(FRAMES)} (none: {nk})",
    )
    check(
        all(hifi_t2(f) for f in FRAMES if INVENTORY[f].t2),
        "every 'shows T2' frame reads T2 in hifi_t2()",
    )
    have = token_table()
    for k, tk in _token_slots():
        check(tk in have, f"token {k} = {tk} exists")
    _negative(check)
    cells = _exercise()
    bd = board(
        0,
        cells,
        source="kit self-test: Pattern frames 2 and 4, SCR-125 / KEK, SCR-129 rung 1, SCR-079, "
        "SCR-016 step 3, one board-10 specimen (never drawn)",
        notes=["the self-test board exercises every shared piece once"],
    )
    sheet = KIT_DIR / "00-selftest.json"
    summary = write_sheet(sheet, bd)
    check(True, f"00-selftest.json validated: {summary}")
    rep = compact_sheet(sheet)
    check(rep["largest_compacted"] <= COMPACT_MAX, f"compacted into v4/: {json.dumps(rep)}")
    js = json.loads(sheet.read_text(encoding="utf-8"))
    check(
        js["page"] == PAGE and js["board"]["name"] == board_name(0),
        "the sheet carries its page and name",
    )
    md = write_board_md(
        0, bd, checks=["every shared piece built once"], summary="The kit's self-test board."
    )
    l3 = md.read_text(encoding="utf-8").splitlines()[2]
    check(
        l3.startswith(f"File `{FILE}`, page `{PAGE}`") and l3.endswith("theme dark."),
        f"00-selftest.md line 3 is the drivers' line: {l3[:80]}…",
    )
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failing check(s)")
    return len(fails)


def main(argv: list[str]) -> int:
    """The CLI (see the module docstring)."""
    if not argv or argv[0] not in ("selftest", "boards", "frame", "deck", "report", "compact"):
        print(__doc__.split("CLI:", 1)[1])
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "selftest":
        return 1 if selftest() else 0
    if cmd == "boards":
        for nn, b in BOARDS.items():
            if rest and int(rest[0]) != nn:
                continue
            print(
                f"{b.name} — theme {b.theme}{f' (twin of {b.twin_of:02d})' if b.twin_of else ''}, export {b.export}"
            )
            print(f"  draws: {b.draws}")
            for f in b.frames:
                inv = INVENTORY[f]
                print(
                    f"  [{inv.num:2d}] {f} — hi-fi {cite(HIFI[f].line)}"
                    + (" · shows T2" if inv.t2 else "")
                )
        return 0
    if cmd == "frame":
        hf = hifi(rest[0])
        inv = INVENTORY[rest[0]]
        print(
            f"{rest[0]} — frame {inv.num}, {cite(hf.line)} ({hf.section}); E27-D02 §7 {cite(inv.line, doc='d02')}"
            + (" · shows T2" if inv.t2 else "")
        )
        for h, c in hf.cells.items():
            if h not in ("#", "Frame (E27-D02 §7)"):
                print(f"  {h}: {clean(c)[:600]}")
        return 0
    if cmd == "deck":
        for k, d in DECK.items():
            if k.startswith(rest[0] if rest else "e27."):
                print(f"{k} L{d.line} [{d.status.split(' ·')[0]}]: " + " · ".join(d.strings))
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
