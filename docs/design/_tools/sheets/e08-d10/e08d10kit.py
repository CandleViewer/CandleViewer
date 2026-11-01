"""E08-D10 (#178) board kit: SCR-151's E08 empty and backfill states, nine boards as cvsheet JSON sheets for the
per-set Penpot file "E08-D10 boards", page "E08-D10 SCR-151 empty and backfill states" (spec §0).

Offline only. Spec (binding; every string comes from it): docs/design/E08/E08-D10.md and E08-D10-handoff.md as this
checkout commits them (read by repo-relative path; md5-pinned in DOCS: the kit refuses drifted bytes; re-read, re-pin).
Cited siblings (read-only, md5-pinned): E11-D04 (the table's header labels, the band row, the "bars loaded" caption),
E22-D02 / E22-D03 (SCR-053's title and columns), E08-D02 (the two superseded strings), E08-D04 (the chip words), and
the recorded instrument fixture (BTCUSDT's tick size only; every other number is a seeded synthetic history).
Registry: §0's board table (BOARDS) and the hand-off's §H frame lists (FRAME_PLAN) are parsed, never typed.

Pipeline (one generator per board, gen/gen_NN.py; a twin's generator calls its bases' frame builders):
    frames = [window(fid, theme, panel), ...]          # one 1280 x 800 window per §H frame, in order
    ann = annotations(nn, [frame_block(fid, ...), ...]) # the ONE 400 px column
    p = write_sheet(nn, frames, ann)                   # build/NN-<slug>.json (untracked), validator exit 0 or raises
    write_md(nn, p)                                    # NN-<slug>.md here and in build/, line 3 = the render line
    pack_sheet(p)                                      # v4/NN-<slug>.json, compactOf.file = the bare name + its sha256
Self-test: python3 -I -B e08d10kit.py selftest   (one sample frame into build/selftest/, validated, packed)
Rebuild all nine: BUILD.md in this folder.

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (frame ids use U+2215 "∕"); no local path, host
or agent name anywhere in a sheet (BANNED); packed sections <= 9 KB; table cells carry 8 px inner padding a side.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KIT_DIR = Path(__file__).resolve().parent
SHEETS_DIR = KIT_DIR.parent
CAP_DIR = KIT_DIR / "build"  # the raw sheets + a copy of each .md (untracked: .gitignore); the .md also go to KIT_DIR
SELFTEST_DIR = CAP_DIR / "selftest"  # the self-test's sheet, md and packed sheet
V4_DIR = KIT_DIR / "v4"  # packed sheets (the renderer's input, committed; compactOf.file = the bare name)
VALIDATOR = SHEETS_DIR / "tools" / "validate_sheet.py"
PACKER = SHEETS_DIR / "tools" / "compact.py"
MKCALL = SHEETS_DIR / "tools" / "mkcall4.py"
COMPONENTS = SHEETS_DIR / "tools" / "components.offline.json"
TOKENS_FILE = SHEETS_DIR / "tools" / "token-sync.json"
REPO = KIT_DIR.parents[4]  # the checkout's root: every source read is REPO / <repo-relative path>, md5-pinned below
DOCS = {  # key -> (repo-relative path, md5): every read is md5-checked
    # spec and hand-off re-pinned at the design-read fold: lines extended in place or added after the last cited
    # line (spec L371, hand-off L105), so every L<n> / §H cite on the nine boards reads the same text
    "spec": ("docs/design/E08/E08-D10.md", "6edf1ad0f42c75e9b5d56574cb48bdd3"),
    "handoff": ("docs/design/E08/E08-D10-handoff.md", "d1e97ea31bc194a0d5903df11736a6b8"),
    "D04E11": ("docs/design/E11/E11-D04.md", "02f3ff690f4c840aebb734889d0a17c6"),
    "D02E22": ("docs/design/E22/E22-D02.md", "9acb071a5f887a00b0de9f384b4685f8"),
    "D03E22": ("docs/design/E22/E22-D03.md", "858221c5367167df2af72b460517d19c"),
    "D02": ("docs/design/E08/E08-D02.md", "35c1af948a6e662417adeddc7f7c6466"),
    "D04": ("docs/design/E08/E08-D04.md", "ceff97750e686be2cdcc0a194d330825"),
    "fixture": ("packages/fixtures/bybit/2026-10-05/rest/instruments_before.json", "edd9dd2a060c51bd4bd1450307728ddf"),
}

FILE_NAME = "E08-D10 boards"
REV = "r1"
PITCH_X, PITCH_Y = 6000, 3200  # grid: x = ((NN-1) mod 5) * 6000, y = floor((NN-1)/5) * 3200
MARGIN = 80  # root margin and frame gutters
ANN_W = 400  # the one annotation column, outside the frames
ANN_TEXT_W = ANN_W - 32
FRAME_W, FRAME_H = 1280, 800
MAX_PER_ROW = 3
SECTION_RAW_BUDGET = 9000
PACKED_MAX = 9216
SLASH = "∕"  # U+2215: stands for "/" in every node name (Penpot splits names on "/")
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode() + r"\b", re.I)


def _doc_bytes(key: str) -> bytes:
    return (REPO / DOCS[key][0]).read_bytes()


def spec_md5_ok() -> dict[str, bool]:
    return {k: hashlib.md5(_doc_bytes(k)).hexdigest() == m for k, (_p, m) in DOCS.items()}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:  # every L<n> cite and every parsed string assumes the pinned bytes
    raise SystemExit(f"e08d10kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
LINES = {k: _COMMENT.sub("", _doc_bytes(k).decode("utf-8")).split("\n") for k in DOCS if k != "fixture"}
SPEC_LINES, HANDOFF_LINES = LINES["spec"], LINES["handoff"]


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def find_line(needle: str, doc: str = "spec", start: int = 1) -> int:
    """1-based number of the first line of doc at or after start containing needle (raises if absent)."""
    ls = LINES[doc]
    for i in range(start - 1, len(ls)):
        if needle in ls[i]:
            return i + 1
    raise LookupError(f"{doc}: not found: {needle!r}")


def L(needle: str, start: int = 1) -> int:
    """The spec line a board cites: looked up, never typed as a number."""
    return find_line(needle, "spec", start)


def HL(needle: str, start: int = 1) -> int:
    return find_line(needle, "handoff", start)


def quote(chars: str, doc: str, a: int | None = None) -> tuple[str, int]:
    """chars must occur verbatim in doc (after line a when given); returns (chars, its line)."""
    return chars, find_line(chars, doc, a or 1)


def _rows(head: str, stop: str, first: str, doc: str = "spec") -> list[tuple[int, list[str]]]:
    """(line, cells) of the table rows between the line containing `head` and the next line containing `stop`,
    keeping rows whose first cell matches the regex `first`."""
    a = find_line(head, doc)
    b = find_line(stop, doc, a + 1)
    return [(i, c) for i in range(a + 1, b) if LINES[doc][i - 1].startswith("|")
            and (c := _cells(LINES[doc][i - 1])) and re.fullmatch(first, c[0])]


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "")).strip()


def unquote(s: str) -> str:
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


# --- §0: the nine boards and the hand-off's §H frame lists (parsed)
PAGE = re.search(r"Penpot: page `([^`]+)`", SPEC_LINES[L("Penpot: page `") - 1]).group(1)  # type: ignore[union-attr]


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E08-D10 / 01 backfill-in-progress"
    slug: str
    draws: str
    theme: str  # dark | light | hc
    line: int  # §0 line
    frames: tuple[str, ...]  # §H: "backfill/known-target · dark", ...
    hline: int  # §H line

    @property
    def export(self) -> str:
        return f"docs/design/E08/img/E08-D10-{self.nn:02d}-{self.slug}.png"

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"

    @property
    def twin(self) -> bool:
        return self.theme != "dark"


_B_ROW = re.compile(r"^\|\s*(\d{2})\s*\|\s*`(E08-D10 / (\d{2}) ([a-z0-9-]+))`\s*\|(.*?)\|\s*(dark|light|hc)\s*\|")
_FID = re.compile(r"`([a-z0-9/-]+ · (?:dark|light|hc))`")


def _parse_boards() -> dict[int, Board]:
    s0 = L("## 0. Status, artefacts and the boards")
    s1 = L("## 1. Purpose", s0)
    plan = {int(c[0]): (i, tuple(_FID.findall(LINES["handoff"][i - 1])))
            for i, c in _rows("## §H The board plan", "## §I", r"\d{2}", "handoff")}
    out: dict[int, Board] = {}
    for i in range(s0, s1):
        m = _B_ROW.match(SPEC_LINES[i - 1])
        if not m:
            continue
        nn = int(m.group(1))
        if int(m.group(3)) != nn:
            raise ValueError(f"§0 L{i}: row {nn} names board {m.group(3)}")
        hl, fr = plan[nn]
        if any(not f.endswith(" · " + m.group(6)) for f in fr):
            raise ValueError(f"§H L{hl}: a frame's theme is not board {nn:02d}'s {m.group(6)}")
        out[nn] = Board(nn, m.group(2), m.group(4), plain(m.group(5)), m.group(6), i, fr, hl)
    return out


BOARDS = _parse_boards()


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


def frame_id(fid: str) -> str:
    """The §H frame id as spoken: "SCR-151/<variant>/<state> · <theme>" (§H naming)."""
    return f"SCR-151/{fid}"


def frame_name(fid: str) -> str:
    """The Penpot frame name: the §H id with U+2215 for every "/" (names split on "/")."""
    return frame_id(fid).replace("/", SLASH)


def base_of(fid: str) -> str:
    """"gap/hole-row · light" -> "gap/hole-row"."""
    return fid.rsplit(" · ", 1)[0]


def theme_of(fid: str) -> str:
    return fid.rsplit(" · ", 1)[1]


# --- §13 the copy deck (W-n) and its placeholder keys
@dataclass(frozen=True)
class Copy:
    wid: str
    key: str
    text: str
    source: str
    status: str
    line: int


COPY = {c[0]: Copy(c[0], plain(c[1]), unquote(c[2]), plain(c[3]), plain(c[4]), i)
        for i, c in _rows("## 13. Copy deck", "## 14. Heuristic", r"W-\d+")}
_TPL_LINE = L("the keys carry placeholders")
_SLOT = re.compile(r"\{[^{}]+\}")


def _templates() -> dict[str, str]:
    """W-n -> its placeholder form. W-3, W-4 and W-7 are quoted on §13's prose line; W-13 / W-14 name their slots
    there ({from}, {to}, {duration}, {short cause}) and W-10 its {ts}: their forms are the deck strings with the
    illustrative values replaced by those slots (selftest: refilling with the illustrative values gives the deck)."""
    t = dict(re.findall(r'(W-\d+) "([^"]+)"', SPEC_LINES[_TPL_LINE - 1]))
    t["W-10"] = COPY["W-10"].text.replace("<ts>", "{ts}")
    t["W-13"] = COPY["W-13"].text.replace("17:02", "{from}").replace("09:14", "{to}")
    t["W-14"] = (COPY["W-14"].text.replace("02:11", "{from}").replace("02:23", "{to}").replace("12 min", "{duration}")
                 .replace("connection lost", "{short cause}"))
    line = SPEC_LINES[_TPL_LINE - 1]
    for k in ("{ts}", "{from}", "{to}", "{duration}", "{short cause}"):
        if k not in line:
            raise ValueError(f"§13 L{_TPL_LINE}: slot {k} not named")
    return t


TEMPLATES = _templates()
ILLUSTRATIVE = {"W-3": ("3 200", "5 000"), "W-4": ("3 200", "2026-08-12"), "W-7": ("3 200", "2026-08-12"),
                "W-10": ("<ts>",), "W-13": ("17:02", "09:14"), "W-14": ("02:11", "02:23", "12 min", "connection lost")}


# --- §7 timing, §10.2 announcements, §11 tokens, §2 / §2.1 maps, §3 / §4 / §5.1 / §6 variant tables, §12 events
TIMING = {c[0]: (plain(c[1]), plain(c[2]), plain(c[3]), plain(c[4]), i)
          for i, c in _rows("## 7. Timing", "**Cuts.**", r"T-\d")}  # T -> (constant, value, source, rule, line)
ANNOUNCE = [(i, [plain(x) for x in c]) for i, c in _rows("### 10.2 The announcement rows", "**Coalescing.**", r"[a-z].*")]
CONTRAST = {plain(c[0]): (plain(c[1]), plain(c[2]), c[3], plain(c[4]), plain(c[5]), plain(c[6]), i)
            for i, c in _rows("## 11. Tokens and contrast", "Every pair passes", r"(?!Element|-).+")}
VARIANT_MAP = [(i, [plain(x) for x in c]) for i, c in _rows("## 2. The variant map", "### 2.1", r"(?!Ticket|-).+")]
COVERAGE_MAP = [(i, [plain(x) for x in c]) for i, c in _rows("### 2.1 Coverage state", "## 3.", r"(?!Cache|-).+")]
EVENTS = {plain(c[0]): (plain(c[1]), plain(c[2]), i)
          for i, c in _rows("The backfill events,", "The backfill events' `surface`", r"`history\.[a-z_]+`")}
CLASSES = [(i, [plain(x) for x in c]) for i, c in _rows("### 5.2 The three classes", "## 6.", r"(?!Class|-).+")]


def _variant_table(head: str, stop: str) -> dict[str, tuple[str, str, int]]:
    return {plain(c[0]): (plain(c[1]), plain(c[2]), i) for i, c in _rows(head, stop, r"(?!Row|-).+")}


V3 = _variant_table("## 3. `backfill-in-progress`", "`aria-valuetext` equals")
V4 = _variant_table("## 4. `backfill-throttled`", "**The long wait.**")
V51 = _variant_table("### 5.1 `recording-not-started`", "### 5.2")
V6 = _variant_table("## 6. `coverage-gap` in context", "Where `gapped` meets")
VCOLS = {"V3": ("full panel", "in context"), "V4": ("full panel", "in context"), "V51": ("full panel", "in context"),
         "V6": ("gapped", "hole")}


# --- tokens (exact names in token-sync.json; the self-test checks every one). §11 is the binding pair table.
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_ON_ACTION, TEXT_LINK = "color.text.on-action", "color.text.link"
BORDER, BORDER_SUBTLE, BORDER_STRONG, RING = ("color.border.default", "color.border.subtle", "color.border.strong",
                                              "color.focus.ring")
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
INFO_SUBTLE, INFO_STRONG = "color.status.info.subtle", "color.status.info.strong"
BF_TEXT, BF_IND = "color.data-confidence.backfilling.text", "color.data-confidence.backfilling.indicator"
GAP_TEXT, GAP_IND = "color.data-confidence.gapped.text", "color.data-confidence.gapped.indicator"
BUY, SELL = "color.buy.default", "color.sell.default"
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD = "type.ui.heading-sm", "type.ui.heading-md"
NUM, NUM_SM = "type.num.base", "type.num.sm"  # NUM_SM: font.family.mono at the compact size (W-10's timestamp, §5.1)
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
BUTTON_PADX = "space.button.paddingX"
ICON_SM, ICON, ICON_LG = "size.icon.sm", "size.icon", "size.icon.lg"
R_CONTROL, R_CARD, R_BADGE = "radius.control", "radius.card", "radius.badge"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, BUTTON_PADX: 12, ICON_SM: 12, ICON: 16, ICON_LG: 20}
NEVER = ("color.text.disabled", "opacity.disabled")  # no control here is disabled (R-5): never bound
FALLBACKS = {
    "chrome": "kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders, the "
              "E08-D09 kit's geometry; only the host panel is this spec's (§0: one host panel per window)",
    "spinner": "fallback: CMP-038's spinner (no spinner icon in the local set) drawn as a 12 px ellipse outline in "
               "color.text.secondary, border.thick; static (reduced motion, §10.1)",
    "gapped-dot": "kit choice: the gapped chip's glyph is the 8 px indicator dot (E16-D05's CMP-239 composition)",
    "pending": "kit choice: the backfilling chip's glyph is the local icon 'pending', §3's block glyph",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)",
    "hidden": "kit choice: a visually hidden string drawn for the board as caption text in a dashed outline (the "
              "words a screen reader hears; not on screen in the product)",
    "badge": "kit choice: focus-order numbers drawn as 20 px numbered markers in color.focus.ring (board markers, "
             "not product UI)",
    "redline": "kit choice: redline callouts drawn as caption text joined to the specimen by a 1 px "
               "color.border.strong leader (board markers, not product UI)",
}
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}


# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "g_rows", "spec_gaps", "fallbacks", "tokens", "live_checks",
              "deviations", "derivations")


class _Notes:
    def __init__(self) -> None:
        self.d: dict[str, list[str]] = {k: [] for k in NOTE_KINDS}

    def add(self, kind: str, line: str) -> None:
        if kind not in self.d:
            raise KeyError(kind)
        if line not in self.d[kind]:
            self.d[kind].append(line)

    def reset(self) -> None:
        self.d = {k: [] for k in NOTE_KINDS}


NOTES = _Notes()


def live(line: str) -> None:
    """A live_checks line: a measurable ACTION for the live drawer (read back X, expect Y)."""
    NOTES.add("live_checks", line)


def spec_gap(line: str) -> None:
    NOTES.add("spec_gaps", line)


def copy_gap(line: str) -> None:
    """A string the copy deck lacks, drawn from the spec's prose or a cited sibling (cite the line)."""
    NOTES.add("copy_gaps", line)


def deviate(line: str) -> None:
    NOTES.add("deviations", line)


def derive(line: str) -> None:
    NOTES.add("derivations", line)


def fallback(key: str) -> None:
    NOTES.add("fallbacks", FALLBACKS[key])


# --- node primitives (cvsheet v4.2 schema; no inst nodes)
_KEYS = {
    "board": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "kids", "note"},
    "text": {"t", "name", "chars", "typo", "color", "w", "align", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "rect": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "ellipse": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "icon": {"t", "name", "icon", "color", "size", "x", "y", "abs", "alignSelf", "note"},
}


def node(t: str, name: str, **kw: Any) -> Node:
    """A node of type t (None values dropped). Refuses inst nodes, unknown keys, "/" in the name, a non-string
    o.wrap, and a banned string in the name, note or chars. Records bound tokens."""
    if t not in _KEYS:
        raise ValueError(f"node type {t!r} not allowed (no inst nodes in the per-set file)")
    if not name or "/" in name:
        raise ValueError(f"{t} name {name!r}: empty or contains '/'")
    n: Node = {"t": t, "name": name}
    n.update({k: v for k, v in kw.items() if v is not None})
    extra = set(n) - _KEYS[t]
    if extra:
        raise KeyError(f"{t} {name!r}: keys cvsheet rejects: {sorted(extra)}")
    o = n.get("o") or {}
    if "wrap" in o and o["wrap"] not in ("wrap", "nowrap"):
        raise ValueError(f"{name!r}: o.wrap must be 'wrap' or 'nowrap', not {o['wrap']!r}")
    for s in (name, n.get("note") or "", n.get("chars") or ""):
        if BANNED.search(s):
            raise ValueError(f"{name!r}: banned string in {s[:60]!r}")
    for tk in [n.get(k) for k in ("typo", "color", "size")] + [v for k, v in o.items() if k in _TOKEN_OPTS]:
        if isinstance(tk, str):
            NOTES.add("tokens", tk)
    return n


def text(name: str, chars: str, typo: str = BODY, color: str = TEXT_1, **kw: Any) -> Node:
    if not str(chars).strip():
        raise ValueError(f"text {name!r} is empty")
    return node("text", name, chars=str(chars), typo=typo, color=color, **kw)


def icon(name: str, glyph_: str, color: str = TEXT_2, size: str = ICON, **kw: Any) -> Node:
    if glyph_ not in ICONS_OK:
        raise ValueError(f"icon {glyph_!r} not in the local set {sorted(ICONS_OK)}")
    if size == ICON_SM:
        fallback("icon-sm")
    return node("icon", name, icon=glyph_, color=color, size=size, **kw)


def rect(name: str, w_: float, h: float, fill: str | None = None, o: dict[str, Any] | None = None, **kw: Any) -> Node:
    opts = dict(o or {})
    if fill:
        opts["fill"] = fill
    return node("rect", name, w=w_, h=h, o=opts or None, **kw)


def ellipse(name: str, w_: float, h: float, o: dict[str, Any] | None = None, **kw: Any) -> Node:
    return node("ellipse", name, w=w_, h=h, o=dict(o) if o else None, **kw)


def unique_names(kids: Iterable[Node | None]) -> list[Node]:
    seen: dict[str, int] = {}
    out = []
    for k in kids:
        if not k:
            continue
        seen[k["name"]] = seen.get(k["name"], 0) + 1
        out.append(k if seen[k["name"]] == 1 else dict(k, name=f"{k['name']} · {seen[k['name']]}"))
    return out


def box(name: str, kids: Iterable[Node | None] = (), o: dict[str, Any] | None = None, **kw: Any) -> Node:
    return node("board", name, o=dict(o) if o else None, kids=unique_names(kids) or None, **kw)


def hbox(name: str, kids: Iterable[Node | None] = (), o: dict[str, Any] | None = None, **kw: Any) -> Node:
    return box(name, kids, {"dir": "row", "align": "center", **(o or {})}, **kw)


def vbox(name: str, kids: Iterable[Node | None] = (), o: dict[str, Any] | None = None, **kw: Any) -> Node:
    return box(name, kids, {"dir": "column", "align": "start", **(o or {})}, **kw)


def walk(n: Node, path: str = "") -> Iterable[tuple[str, Node]]:
    p = f"{path}/{n['name']}" if path else n["name"]
    yield p, n
    for k in n.get("kids") or []:
        yield from walk(k, p)


# --- text metrics (estimates; Inter / JetBrains Mono)
_FONT = {CAPTION: (11, 1.2, False), BODY: (13, 1.4, False), BODY_STRONG: (13, 1.4, False), LABEL: (12, 1.2, False),
         HEADING_SM: (14, 1.2, False), HEADING_MD: (16, 1.2, False), NUM: (13, 1.2, True),
         NUM_SM: (11, 1.2, True)}


def text_w(chars: str, typo: str) -> float:
    size, _lh, mono = _FONT.get(typo, _FONT[BODY])
    return round(len(chars) * (0.6 if mono else 0.56) * size, 1)


def text_lines(chars: str, typo: str, width: float) -> int:
    lines, cur = 1, ""
    for word in str(chars).split():
        trial = f"{cur} {word}" if cur else word
        if cur and text_w(trial, typo) > width:
            lines, cur = lines + 1, word
        else:
            cur = trial
    return lines


def text_h(typo: str, lines: int = 1) -> float:
    size, lh, _m = _FONT.get(typo, _FONT[BODY])
    return round(size * lh * lines, 1)


def _px(v: Any) -> int:
    return PX.get(v, 0) if isinstance(v, str) else 0


def est_width(n: Node) -> float:
    if n.get("w"):
        return float(n["w"])
    if n["t"] == "text":
        return text_w(n["chars"], n["typo"])
    if n["t"] == "icon":
        return float(PX.get(n.get("size", ICON), 16))
    if n["t"] != "board":
        return 16.0
    o, kids = n.get("o") or {}, [k for k in n.get("kids") or [] if not k.get("abs")]
    pad = 2 * _px(o.get("pad")) + 2 * _px(o.get("padX")) + _px(o.get("padL")) + _px(o.get("padR"))
    if o.get("dir") == "row":
        return pad + sum(est_width(k) for k in kids) + _px(o.get("gap")) * max(len(kids) - 1, 0)
    if o.get("dir") == "column":
        return pad + max((est_width(k) for k in kids), default=0.0)
    return max((float(k.get("x", 0)) + est_width(k) for k in n.get("kids") or []), default=0.0)


def est_height(n: Node) -> float:
    if n.get("h"):
        return float(n["h"])
    if n["t"] == "text":
        return text_h(n["typo"], text_lines(n["chars"], n["typo"], n["w"]) if n.get("w") else 1)
    if n["t"] == "icon":
        return float(PX.get(n.get("size", ICON), 16))
    if n["t"] != "board":
        return 16.0
    o, kids = n.get("o") or {}, [k for k in n.get("kids") or [] if not k.get("abs")]
    pad = 2 * _px(o.get("pad")) + 2 * _px(o.get("padY")) + _px(o.get("padT")) + _px(o.get("padB"))
    if o.get("dir") == "column":
        return pad + sum(est_height(k) for k in kids) + _px(o.get("gap")) * max(len(kids) - 1, 0)
    if o.get("dir") == "row" and o.get("wrap") == "wrap" and n.get("w"):
        room = float(n["w"]) - 2 * _px(o.get("pad")) - 2 * _px(o.get("padX")) - _px(o.get("padL")) - _px(o.get("padR"))
        gap, total, line_w, line_h = _px(o.get("gap")), 0.0, 0.0, 0.0
        for k in kids:
            kw, kh = est_width(k), est_height(k)
            if line_w and line_w + gap + kw > room:
                total, line_w, line_h = total + line_h + gap, 0.0, 0.0
            line_w, line_h = line_w + (gap if line_w else 0) + kw, max(line_h, kh)
        return pad + total + line_h
    if o.get("dir") == "row":
        return pad + max((est_height(k) for k in kids), default=0.0)
    return max((float(k.get("y", 0)) + est_height(k) for k in n.get("kids") or []), default=0.0)


# --- the synthetic world (§H: "a seeded synthetic history (seed 178), not recorded"; only the tick size is recorded)
from decimal import Decimal  # noqa: E402

SEED = 178
SYMBOL = "BTCUSDT"
INTERVAL_MIN = 5  # the history panel's interval: §10.1's naming example "Bars BTCUSDT 5 minutes"
BARS_PER_DAY = 24 * 60 // INTERVAL_MIN  # 288
DAYS_TO_LOAD = 17  # the configured days-to-load (kit choice): the target in bars is days over the interval (§3)
TARGET = DAYS_TO_LOAD * BARS_PER_DAY  # 4 896: W-3's {m}
NOW_OPEN = datetime(2026, 8, 23, 10, 35, tzinfo=timezone.utc)  # the latest bar's open (one clock for every frame)
STEP = timedelta(minutes=INTERVAL_MIN)
N_FULL = 1600  # bars the episode has loaded when the full panel is drawn (kit reading, build-notes ambiguity 1)
N_CONTEXT = 3200  # bars loaded on the in-context and throttled frames (= the deck's illustrative 3 200)


def _tick() -> Decimal:
    inst = json.loads(_doc_bytes("fixture"))["result"]["list"]
    return Decimal(next(i for i in inst if i["symbol"] == SYMBOL)["priceFilter"]["tickSize"])


TICK = _tick()  # 0.10 from the recorded instrument fixture
PRICE_DP = max(0, -TICK.normalize().as_tuple().exponent)  # 1: the tick's digits (E11-D04: tick-precision prices)


@dataclass(frozen=True)
class Bar:
    i: int  # 0 = the oldest bar of the target range
    t: datetime  # open time, UTC
    o: Decimal
    h: Decimal
    lo: Decimal
    c: Decimal
    v: Decimal  # BTC


def _series() -> list[Bar]:
    rng = random.Random(SEED)
    out, prev = [], Decimal("64000.0")
    for i in range(TARGET):
        o = prev
        c = (o + Decimal(rng.randint(-120, 120)) * TICK).quantize(TICK)
        h = (max(o, c) + Decimal(rng.randint(0, 60)) * TICK).quantize(TICK)
        lo = (min(o, c) - Decimal(rng.randint(0, 60)) * TICK).quantize(TICK)
        v = Decimal(rng.randint(8000, 160000)) / 1000
        out.append(Bar(i, NOW_OPEN - (TARGET - 1 - i) * STEP, o, h, lo, c, v))
        prev = c
    return out


SERIES = _series()


def grp(n: int | Decimal, dp: int = 0) -> str:
    """Thousands grouped with a space, as the deck writes them ("3 200", "10 000")."""
    return f"{n:,.{dp}f}".replace(",", " ")


def price(x: Decimal) -> str:
    return grp(x, PRICE_DP)


def qty(x: Decimal) -> str:
    return f"{x:.3f}"


def hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


def day(t: datetime) -> str:
    return t.strftime("%Y-%m-%d")


def ts(t: datetime) -> str:
    """W-10's {ts}: the date, time and zone (E11-D04's own form, "2026-09-01 08:00 UTC")."""
    return t.strftime("%Y-%m-%d %H:%M UTC")


def oldest(n: int) -> Bar:
    """The oldest of the newest n bars (the backfill pages from the latest bar back)."""
    return SERIES[TARGET - n]


def back_to(n: int) -> str:
    return day(oldest(n).t)


def latest(k: int, *, skip: Iterable[int] = ()) -> list[Bar]:
    """The newest k bars on screen, oldest first; skip = bar indices missing (a hole)."""
    s = set(skip)
    rows = [b for b in SERIES if b.i not in s]
    return rows[-k:]


def hole(first_open: str, n_bars: int) -> tuple[list[int], str, str, str]:
    """A hole of n_bars bars on NOW_OPEN's day starting at the bar opening first_open ("09:30"): (indices, from, to,
    duration) with from = the first missing bar's open and to = the next present bar's open (W-13's {from}-{to})."""
    hh, mm = map(int, first_open.split(":"))
    t0 = NOW_OPEN.replace(hour=hh, minute=mm)
    i0 = next(b.i for b in SERIES if b.t == t0)
    idx = list(range(i0, i0 + n_bars))
    t1 = t0 + n_bars * STEP
    derive(f"hole {hhmm(t0)}–{hhmm(t1)} UTC: {n_bars} bars of {INTERVAL_MIN} min missing = {n_bars * INTERVAL_MIN} min; "
           f"the rows around it open {hhmm(t0 - STEP)} and {hhmm(t1)}")
    return idx, hhmm(t0), hhmm(t1), f"{n_bars * INTERVAL_MIN} min"


def w(wid: str, **slots: str) -> str:
    """A §13 string. With slots, the placeholder form filled from the frame's own data (every slot required); without,
    the deck string verbatim (refused when the string has illustrative numbers: derive them)."""
    c = COPY[wid]
    NOTES.add("copy_keys", f"{wid} {c.key} (§13 L{c.line}; {c.status[:40]})")
    if not slots:
        if wid in TEMPLATES:
            raise ValueError(f"{wid}: illustrative values in {c.text!r}: pass the frame's slots")
        return c.text
    tpl = TEMPLATES[wid]
    want = [s[1:-1] for s in _SLOT.findall(tpl)]
    got = {k.replace("_", " "): v for k, v in slots.items()}
    if sorted(want) != sorted(got):
        raise ValueError(f"{wid}: slots {want}, given {sorted(got)}")
    return _SLOT.sub(lambda m: str(got[m.group(0)[1:-1]]), tpl)


def piece(s: str, i: int) -> str:
    """Piece i of a " · "-separated string (W-8's line and its control)."""
    return s.split(" · ")[i]


def w3(n: int) -> str:
    derive(f"W-3: {grp(n)} loaded of {grp(TARGET)} = {DAYS_TO_LOAD} days × {BARS_PER_DAY} bars a day "
           f"({INTERVAL_MIN} min bars; 'about': the target is days over the interval, §3)")
    return w("W-3", n=grp(n), m=grp(TARGET))


def w4(n: int) -> str:
    derive(f"W-4 / W-7: {grp(n)} bars back from the {hhmm(NOW_OPEN)} UTC bar of {day(NOW_OPEN)} reach "
           f"{ts(oldest(n).t)} ({grp(n)} × {INTERVAL_MIN} min)")
    return w("W-4", n=grp(n), date=back_to(n))


def w7(n: int) -> str:
    w4(n)
    return w("W-7", n=grp(n), date=back_to(n))


def loaded_caption(n: int) -> str:
    """The table caption's count, E11-D04's "0 bars loaded" form (its empty-state row) with the frame's n."""
    s, ln = quote("0 bars loaded", "D04E11")
    copy_gap(f'"{{n}} bars loaded": E11-D04 L{ln}\'s caption form "{s}" with the frame\'s count')
    return f"{grp(n)} bars loaded"


# --- the window: one host panel at compact density in a 1280 x 800 frame (§0). Chrome geometry follows the E08-D09
# kit (TopBar 48, NavRail 64, main 976 x 704, RightRail 240, StatusBar 48), drawn as neutral placeholders.
TOP_H, STATUS_H, NAV_W, RIGHT_W = 48, 48, 64, 240
MAIN_W = FRAME_W - NAV_W - RIGHT_W  # 976
BODY_H = FRAME_H - TOP_H - STATUS_H  # 704
PANEL_W, PANEL_H = MAIN_W - 32, BODY_H - 32  # 944 x 672: the host panel, inset 16 in main
ROW_H, CONTROL_H = 24, 24  # compact density: rows and controls 24 px (§0 "compact density")
BLOCK_W = 480  # the CMP-026 column (§10.1: "The 480 px block")


def placeholder(name: str, w_: int, h: int = 12) -> Node:
    fallback("chrome")
    return rect(f"placeholder · {name}", w_, h, HOVER, {"radius": R_CONTROL})


def topbar() -> Node:
    left = hbox("left", [placeholder("wordmark", 88), placeholder("env badge", 40, 16),
                         placeholder("workspace switcher", 136)], {"gap": INSET_MD}, h=TOP_H)
    right = hbox("right", [placeholder("health chips", 160), placeholder("search", 16, 16),
                           placeholder("user menu", 72)], {"gap": INSET_MD}, h=TOP_H)
    return hbox("TopBar (placeholder)", [left, right, rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=TOP_H - 1,
                                                          abs=True)],
                {"padX": INSET_LG, "justify": "space-between", "fill": APP}, w=FRAME_W, h=TOP_H,
                note="E10's TopBar, not this spec's: placeholders only")


def navrail() -> Node:
    rows = [hbox(f"entry-{i}", [placeholder("glyph", 16, 16)], {"justify": "center"}, w=48, h=32) for i in range(1, 7)]
    return vbox("NavRail (placeholder)", [vbox("entries", rows, {"gap": INSET_XS, "align": "center"}, w=48,
                                               h=6 * 32 + 5 * 4),
                                          rect("divider", 1, BODY_H, BORDER_SUBTLE, x=NAV_W - 1, y=0, abs=True)],
                {"align": "center", "padY": INSET_SM, "fill": APP}, w=NAV_W, h=BODY_H)


def rightrail() -> Node:
    rows = [placeholder(f"row-{i}", RIGHT_W - 24) for i in range(1, 4)]
    return vbox("RightRail (placeholder)", [placeholder("panic buttons", RIGHT_W - 24, 40), *rows,
                                            rect("divider", 1, BODY_H, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"gap": INSET_MD, "pad": INSET_MD, "fill": APP}, w=RIGHT_W, h=BODY_H)


def proposed_tag() -> Node:
    """R-7's mark on the frame's face: the frame is built on D10-G1's PROPOSED backfill fields."""
    ln = L("- **R-7 PROPOSED fields.**")
    copy_gap(f'"PROPOSED fields (D10-G1), not shipped": R-7 L{ln} ("say so on their face and are never shown as '
             f'shipped"); no deck string')
    return hbox("board marker · PROPOSED fields (R-7)", [icon("glyph", "info", INFO_STRONG, ICON_SM),
                                                         text("words", "PROPOSED fields (D10-G1), not shipped",
                                                              CAPTION, TEXT_1)],
                {"fill": INFO_SUBTLE, "radius": R_BADGE, "padX": INSET_SM, "gap": INSET_XS}, h=20,
                note="a board marker on the frame's face (R-7, §H), not product UI")


def statusbar(proposed: bool) -> Node:
    kids = [placeholder("connection chip", 120), proposed_tag() if proposed else placeholder("env badge", 40, 16),
            rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=0, abs=True)]
    return hbox("StatusBar (placeholder)", kids, {"padX": INSET_LG, "justify": "space-between", "fill": APP},
                w=FRAME_W, h=STATUS_H)


def window(fid: str, content: Node | list[Node], *, proposed: bool = False, note: str | None = None) -> Node:
    """One 1280 x 800 window (§0): TopBar | NavRail · main · RightRail | StatusBar; main (976 x 704, clip) holds the
    content at (16, 16): one host panel (PANEL_W x PANEL_H), or a list of nodes already placed (x, y set).
    proposed=True puts R-7's mark in the StatusBar (boards 01, 02, 05, 08 per §H)."""
    if theme_of(fid) not in ("dark", "light", "hc"):
        raise ValueError(fid)
    kids = content if isinstance(content, list) else [dict(content, x=16, y=16)]
    for k in kids:
        if "x" not in k or k.get("x", 0) + k.get("w", 0) > MAIN_W - 16 or k.get("y", 0) + est_height(k) > BODY_H - 15:
            raise ValueError(f"{fid}: {k['name']!r} does not fit main ({k.get('x')}, {k.get('y')}, {k.get('w')} x "
                             f"{est_height(k):.0f})")
    main = box("main", kids, {"fill": APP, "clip": True}, w=MAIN_W, h=BODY_H,
               note="the workspace: one host panel at compact density (§0)")
    body = hbox("body", [navrail(), main, rightrail()], {"align": "start"}, w=FRAME_W, h=BODY_H)
    return vbox(frame_name(fid), [topbar(), body, statusbar(proposed)], {"fill": APP, "clip": True},
                w=FRAME_W, h=FRAME_H, note=note or f"frame {frame_id(fid)}")


# --- focus, controls (CMP-001 secondary, CMP-021 link) at compact 24 px
def ring(control: Node, radius: str = R_CONTROL, name: str = "focus-ring") -> Node:
    """CMP-039 focus-visible: a 2 px color.focus.ring inner stroke on a wrapper padded 2 px (compact)."""
    return hbox(name, [control], {"padX": INSET_XS, "radius": radius, "stroke": RING, "strokeWidth": FOCUS_W,
                                  "strokeAlign": "inner"}, h=round(est_height(control)) + 8, note="focus-visible")


def button(chars: str, *, focused: bool = False, name: str | None = None) -> Node:
    """CMP-001 secondary (§4: `Retry` after give-up): label color.text.primary on color.action.secondary.default."""
    lab = text("label", chars, BODY_STRONG, TEXT_1)
    b = hbox(name or f"CMP-001 Button · secondary · {chars}", [lab],
             {"fill": ACTION_SECONDARY, "padX": BUTTON_PADX, "radius": R_CONTROL, "justify": "center"},
             w=round(text_w(chars, BODY_STRONG)) + 2 * PX[BUTTON_PADX] + 2, h=CONTROL_H)
    return ring(b) if focused else b


def link(chars: str, *, focused: bool = False, name: str | None = None) -> Node:
    """CMP-021 Link: the words in color.text.link, no fill; >= 24 x 24 (§10.1 target sizes)."""
    b = hbox(name or f"CMP-021 Link · {chars}", [text("label", chars, BODY, TEXT_LINK)], {"justify": "center"},
             w=max(24, round(text_w(chars, BODY)) + 2), h=CONTROL_H)
    return ring(b) if focused else b


def show_coverage(focused: bool = False) -> Node:
    s, ln = quote("Show coverage", "spec")
    copy_gap(f'"{s}": the link\'s words, spec L{ln} (CMP-021 → SCR-103; no W-id)')
    return link(s, focused=focused)


def owner_link(focused: bool = False) -> Node:
    return link(w("W-9"), focused=focused, name="CMP-021 Link · Owner only (W-9 → SCR-147)")


def retry(focused: bool = False) -> Node:
    return button(piece(w("W-8"), 1), focused=focused, name="CMP-001 Button · secondary · Retry (W-8)")


# --- chips and status-slot words (§3, §4, §6; tokens §11)
def chip(name: str, lead: Node, words: str, color: str, fill: str = RAISED, *, note: str | None = None) -> Node:
    return hbox(name, [lead, text("words", words, CAPTION, color)],
                {"fill": fill, "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner", "radius": R_BADGE,
                 "padX": INSET_SM, "gap": INSET_XS}, h=20, note=note)


def bf_chip() -> Node:
    """The `backfilling` chip: glyph `pending` in .backfilling.indicator, W-1 in .backfilling.text; static, not a
    stop (§4 "Chips as stops")."""
    fallback("pending")
    return chip("CMP-011 chip · backfilling", icon("glyph", "pending", BF_IND, ICON_SM), w("W-1"), BF_TEXT,
                note="static; its words are in the panel's accessible description (§4)")


def gapped_chip() -> Node:
    fallback("gapped-dot")
    dot = ellipse("glyph · indicator dot", 8, 8, {"fill": GAP_IND})
    return chip("CMP-011 chip · gapped", dot, w("W-12"), GAP_TEXT, note="static, not a stop; never announced (§6)")


def partial_chip(n: int, *, focused: bool = False) -> Node:
    """The Partial chip: CMP-011 `info`, W-7 in color.text.primary on color.status.info.subtle; role="note",
    tabindex="0", the missing range in its description (§4, KB-19)."""
    c = hbox("CMP-011 chip · info · Partial", [icon("glyph", "info", INFO_STRONG, ICON_SM),
                                               text("words", w7(n), CAPTION, TEXT_1)],
             {"fill": INFO_SUBTLE, "radius": R_BADGE, "padX": INSET_SM, "gap": INSET_XS}, h=20,
             note='role="note" tabindex="0"; aria-describedby: the missing range (KB-19)')
    return ring(c, R_BADGE, "focus-ring · Partial chip") if focused else c


def words(name: str, chars: str) -> Node:
    """Status-slot words: type.ui.caption, color.text.secondary (§3 / §4 Tokens)."""
    return text(name, chars, CAPTION, TEXT_2)


def gave_up_line(*, focused_retry: bool = False) -> Node:
    """W-8 in context: the words, then `Retry` (CMP-001 secondary), one line (§4 Copy, in context)."""
    return hbox("give-up line (W-8)", [words("words", piece(w("W-8"), 0)), retry(focused_retry)], {"gap": INSET_SM},
                h=CONTROL_H + (8 if focused_retry else 0))


# --- CMP-026 block, CMP-023 bar, CMP-038 words (§3, §4, §5.1)
def bar(n: int, *, w_: int = BLOCK_W - 48, frozen: bool = False) -> Node:
    """CMP-023 determinate: track color.surface.hover, fill color.action.primary.default; width n / TARGET."""
    fw = round(w_ * n / TARGET)
    derive(f"bar fill {fw} of {w_} px = {grp(n)} / {grp(TARGET)} bars" + (" (frozen at its last sample, §4)"
                                                                          if frozen else ""))
    kids = [rect("track", w_, 8, HOVER, {"radius": R_BADGE}, x=0, y=0),
            rect("fill", fw, 8, ACTION_PRIMARY, {"radius": R_BADGE}, x=0, y=0)]
    return box("CMP-023 ProgressBar" + (" · frozen" if frozen else ""), kids, None, w=w_, h=8,
               note=f'role="progressbar" name "History loaded so far"; aria-valuetext "{w3(n)}"; never a live region')


def spinner_words(chars: str) -> Node:
    """CMP-038 kind="load": the spinner (fallback ellipse) + the words; one role="status" (§3, unknown target)."""
    fallback("spinner")
    sp = hbox("spinner", [ellipse("ring", 12, 12, {"stroke": TEXT_2, "strokeWidth": THICK})], {"justify": "center"},
              w=16, h=16)
    return hbox("CMP-038 InlineSpinnerText · load", [sp, text("words", chars, CAPTION, TEXT_2)], {"gap": INSET_XS},
                h=16, note="no progressbar exists (D10-C5)")


def ts_heading(heading: str, stamp: str, inner: int) -> Node:
    """W-10 with its timestamp in font.family.mono (type.num.sm), the words in type.ui.heading-sm (§5.1)."""
    a, b = heading.split(stamp, 1)
    kids = [text("words", a.strip(), HEADING_SM, TEXT_1), text("timestamp (mono)", stamp, NUM_SM, TEXT_1),
            text("words · 2", b.strip(), HEADING_SM, TEXT_1)]
    return hbox("heading (h3)", kids, {"gap": INSET_XS, "justify": "center", "wrap": "wrap"}, w=inner)


def block(heading: str | Node, causes: Iterable[str] = (), *, glyph_: str | None = "pending",
          progress: Node | None = None, value: str | None = None, actions: Iterable[Node | None] = (),
          heading_focused: bool = False, name: str = "CMP-026 EmptyState") -> Node:
    """The CMP-026 block (E16-D05's anatomy): glyph → heading (h3) → cause(s) → the progress? slot → actions; 480 px,
    padded space.inset.xl, centred."""
    inner = BLOCK_W - 2 * PX[INSET_XL]
    h = heading if isinstance(heading, dict) else text("heading (h3)", heading, HEADING_SM, TEXT_1, w=inner,
                                                         align="center")
    if heading_focused:
        h = ring(h, R_CONTROL, "focus-ring · heading (tabindex -1)")
    top = [icon("glyph", glyph_, TEXT_3, ICON_LG) if glyph_ else None, h]
    top += [text("cause", c, BODY, TEXT_2, w=inner, align="center") for c in causes]
    if progress:
        top.append(vbox("progress slot", [progress, text("value text", value, CAPTION, TEXT_2) if value else None],
                        {"gap": STACK_XS, "align": "center"}, w=inner))
    col = [vbox("text", top, {"gap": STACK_SM, "align": "center"}, w=inner)]
    acts = [a for a in actions if a]
    if acts:
        col.append(hbox("actions", acts, {"gap": INSET_SM, "justify": "center"}, w=inner,
                        h=max(round(est_height(a)) for a in acts)))
    return vbox(name, col, {"gap": STACK_MD, "align": "center", "pad": INSET_XL}, w=BLOCK_W)


# --- the host panel: header (title + status slot), hairline, body
def title(text_: str, *, focused: bool = False) -> Node:
    t = text("title", text_, LABEL, TEXT_1)
    return ring(t, R_CONTROL, "focus-ring · title (tabindex -1)") if focused else t


def history_title() -> str:
    s, ln = quote("Bars BTCUSDT 5 minutes", "spec")
    copy_gap(f'panel title "{s}": §10.1 L{ln}\'s naming example (kind · symbol · interval spelled out)')
    return s


def tape_title() -> str:
    s, ln = quote("Tape BTCUSDT", "D03E22")
    copy_gap(f'tape title "{s}": E22-D03 L{ln} (SCR-053 header row)')
    return s


def panel(name: str, title_node: Node, status: Iterable[Node | None], body: list[Node], *, w_: int = PANEL_W,
          h: int = PANEL_H, footer: str | None = None, center_last: bool = False) -> Node:
    """A host panel on color.surface.raised: header (title, then the status slot in reading order; wraps to a second
    line before anything truncates, §10.1), hairline, body (rows or the centred block), the caption footer."""
    slot_w = w_ - 24 - round(est_width(title_node)) - 8
    st = [dict(s, w=slot_w) if s["t"] == "text" and est_width(s) > slot_w else s for s in status if s]
    for s in st:
        if est_width(s) > slot_w:
            raise ValueError(f"{name}: status item {s['name']!r} ({est_width(s):.0f} px) wider than the slot {slot_w}")
    slot = hbox("status slot", st, {"gap": INSET_SM, "wrap": "wrap"}, w=slot_w) if st else None
    head = hbox("header", [title_node, slot], {"gap": INSET_SM, "padX": INSET_MD, "padY": INSET_SM,
                                               "align": "start"}, w=w_)
    hh = max(40, round(est_height(head)))
    head["h"] = hh
    foot = (hbox("footer · caption", [text("caption", footer, CAPTION, TEXT_2)], {"padX": INSET_MD}, w=w_, h=ROW_H,
                 note="<caption>, not a live region") if footer else None)
    room = h - hh - 1 - (ROW_H if foot else 0)
    body = list(body)
    if center_last:  # the CMP-026 block centred in what the fixed rows above it leave
        rest = room - round(sum(est_height(b) for b in body[:-1]))
        body[-1] = vbox("block area", [body[-1]], {"align": "center", "justify": "center"}, w=w_, h=rest)
    bd = vbox("body", body, None, w=w_, h=room)
    if sum(est_height(b) for b in body) > room + 0.5:
        raise ValueError(f"{name}: body {sum(est_height(b) for b in body):.0f} px > room {room}")
    return vbox(name, [head, rect("header rule", w_, 1, BORDER), bd, foot],
                {"fill": RAISED, "radius": R_CARD, "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner",
                 "clip": True}, w=w_, h=h)


# --- tables: every cell is a box padded space.inset.sm (8 px) a side, so adjacent texts sit >= 16 px apart
@dataclass(frozen=True)
class Col:
    key: str
    label: str
    w: int
    numeric: bool = False


def cell(name: str, content: str | Node | list[Node] | None, w_: int, *, numeric: bool = False, h: int = ROW_H,
         typo: str | None = None, color: str = TEXT_1) -> Node:
    inner = w_ - 2 * PX[INSET_SM]
    ty = typo or (NUM_SM if numeric else CAPTION)
    if content is None or content == "":
        kids: list[Node] = []
    elif isinstance(content, str):
        kids = [text("value", content, ty, color, **({"w": inner} if text_w(content, ty) > inner else {}))]
    elif isinstance(content, list):
        kids = content
    else:
        kids = [content]
    return hbox(name, kids, {"padX": INSET_SM, "justify": "end" if numeric else "start", "gap": INSET_XS}, w=w_, h=h)


def header_row(cols: Iterable[Col]) -> Node:
    cs = list(cols)
    return hbox("header row", [cell(f"th · {c.key}", c.label, c.w, numeric=c.numeric, typo=NUM_SM if c.numeric
                                    else CAPTION, color=TEXT_3) for c in cs], {"fill": RAISED},
                w=sum(c.w for c in cs), h=ROW_H, note='column headers, scope="col"')


def table_row(cols: Iterable[Col], cells: dict[str, str | Node | list[Node] | None], name: str, *,
              h: int | None = None, fill: str = RAISED, colors: dict[str, str] | None = None,
              typo: str | None = None) -> Node:
    """One row; h=None: the tallest cell's content + 4 px a side, at least ROW_H, rounded up to 4 px. Raises when a
    cell's content would not fit (no clipped or overlapping text)."""
    cs = list(cols)
    unknown = set(cells) - {c.key for c in cs}
    if unknown:
        raise KeyError(f"{name}: cells for unknown columns {sorted(unknown)}")
    if h is None:
        probe = [cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=1, typo=typo) for c in cs]
        need = max((est_height(dict(k, h=None)) for k in probe), default=0.0) + 8
        h = max(ROW_H, int(math.ceil(need / 4) * 4))
    kids = [cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=h, typo=typo,
                 color=(colors or {}).get(c.key, TEXT_1)) for c in cs]
    for k in kids:
        if est_height(dict(k, h=None)) > h:
            raise ValueError(f"{name}: cell {k['name']!r} needs about {est_height(dict(k, h=None)):.0f} px > h {h}")
    return hbox(name, kids, {"fill": fill}, w=sum(c.w for c in cs), h=h)


def _header_labels(doc: str, needle: str, want: tuple[str, ...]) -> tuple[str, ...]:
    ln = find_line(needle, doc)
    s = LINES[doc][ln - 1]
    for x in want:
        if x not in s:
            raise LookupError(f"{doc} L{ln}: {x!r}")
    copy_gap(f"column headers {' · '.join(want)}: {doc} L{ln}")
    return want


HIST_LABELS = ("time", "open", "high", "low", "close", "volume")  # E11-D04 §"Header labels" (checked at use)
HIST_W = (104, 160, 160, 160, 160, 200)
TAPE_LABELS = ("Time", "Price", "Size", "Notional", "Side (taker)")  # E22-D02's column header row (checked at use)
TAPE_W = (176, 192, 160, 192, 224)
assert sum(HIST_W) == PANEL_W and sum(TAPE_W) == PANEL_W


def hist_cols(total: int = PANEL_W) -> list[Col]:
    labs = _header_labels("D04E11", "**Header labels.**", HIST_LABELS)
    ws = [round(x * total / PANEL_W) for x in HIST_W]
    ws[-1] = total - sum(ws[:-1])
    return [Col(k, k, wd, k != "time") for k, wd in zip(labs, ws)]


def bar_row(b: Bar, cols: list[Col]) -> Node:
    return table_row(cols, {"time": hhmm(b.t), "open": price(b.o), "high": price(b.h), "low": price(b.lo),
                            "close": price(b.c), "volume": qty(b.v)}, f"row · {hhmm(b.t)}", h=ROW_H,
                     typo=None)


def hole_row(chars: str, *, w_: int = PANEL_W, link_focused: bool = False, name: str = "row · hole separator") -> Node:
    """The hole separator row (§6): E11-D04's band-row form, W-13 / W-14 in color.text.secondary on
    color.surface.hover, `Show coverage` a cell of the row (a read, R-5); never announced."""
    lk = show_coverage(link_focused)
    lw = round(est_width(lk)) + 2 * PX[INSET_SM]
    h = ROW_H + (8 if link_focused else 0)
    return hbox(name, [cell("words", chars, w_ - lw, h=h, color=TEXT_2),
                       hbox("link cell", [lk], {"padX": INSET_SM}, w=lw, h=h)],
                {"fill": HOVER}, w=w_, h=h, note="a row of the grid: arrows stop on it; its name is its text (§6)")


def rows_block(rows: list[Node], name: str = "rows") -> Node:
    return vbox(name, rows, None, w=rows[0]["w"], h=round(sum(est_height(r) for r in rows)))


def history_body(bars: list[Bar], *, hole_at: int | None = None, hole_node: Node | None = None,
                 room: int, total: int = PANEL_W) -> list[Node]:
    """Column header row + bar rows (oldest first, the newest at the bottom); a hole row after bar index hole_at.
    Rows are cut from the top so the body fits room."""
    cols = hist_cols(total)
    rows = [bar_row(b, cols) for b in bars]
    if hole_node is not None and hole_at is not None:
        k = next(j for j, b in enumerate(bars) if b.i == hole_at) + 1
        rows.insert(k, hole_node)
    while sum(est_height(r) for r in rows) + ROW_H > room:
        rows.pop(0)
    return [header_row(cols), rows_block(rows)]


def tape_rows(k: int) -> list[tuple[str, str, str, str, str]]:
    """k synthetic prints in the last bar (seed 178), newest first: time, price, size, notional, side."""
    rng = random.Random(SEED + 53)
    last = SERIES[-1]
    out, t, p = [], NOW_OPEN + STEP - timedelta(seconds=1), last.c
    for _ in range(k):
        p = (p + Decimal(rng.randint(-6, 6)) * TICK).quantize(TICK)
        size = Decimal(rng.randint(1, 900)) / 1000
        out.append((t.strftime("%H:%M:%S"), price(p), qty(size), grp(int(p * size)), rng.choice(("Buy", "Sell"))))
        t -= timedelta(seconds=rng.randint(1, 4))
    return out


def tape_body(room: int) -> list[Node]:
    labs = _header_labels("D02E22", "Time · Price · Size · Notional · Side (taker)", TAPE_LABELS)
    cols = [Col(f"c{i}", lab, wd, i in (1, 2, 3)) for i, (lab, wd) in enumerate(zip(labs, TAPE_W))]
    n = (room - ROW_H) // ROW_H
    sw, sl = quote("Buy / Sell, left-aligned", "D02E22")
    copy_gap(f"side words Buy / Sell: E22-D02 L{sl} (\"{sw}\")")
    rows = []
    for tm, p, s, nt, side in tape_rows(n):
        sd = hbox("side", [icon("glyph", "arrow-up" if side == "Buy" else "arrow-down", BUY if side == "Buy" else SELL,
                                ICON_SM), text("word", side, CAPTION, TEXT_1)], {"gap": INSET_XS}, h=16)
        rows.append(table_row(cols, {"c0": tm, "c1": p, "c2": s, "c3": nt, "c4": sd}, f"row · print {tm}", h=ROW_H))
    derive(f"tape: {n} synthetic prints in the {hhmm(NOW_OPEN)} UTC bar, newest first; notional = price × size, "
           f"rounded down to whole USDT")
    return [header_row(cols), rows_block(rows, "prints")]


# --- board markers: visually hidden strings, focus-order numbers, the timeline, spec tables, redline callouts
def hidden(chars: str, *, w_: int = 400, name: str = "visually hidden (drawn for the board)") -> Node:
    """A string a screen reader hears but the screen does not show, drawn for the board (FALLBACKS["hidden"])."""
    fallback("hidden")
    copy_gap('"visually hidden": the hidden-string marker label (E16-D05 kit form; no deck string)')
    return vbox(name, [text("marker", "visually hidden", CAPTION, TEXT_3),
                       text("words", chars, CAPTION, TEXT_2, w=w_ - 16)],
                {"gap": STACK_XS, "pad": INSET_SM, "stroke": BORDER_STRONG, "strokeWidth": HAIR,
                 "strokeAlign": "inner", "radius": R_CONTROL, "fill": SUNKEN}, w=w_,
                note="board marker: not on screen in the product")


def order_marker(n: int, x: int, y: int) -> Node:
    """Focus-order stop n as a 20 px numbered marker (FALLBACKS["badge"]); placed absolutely."""
    fallback("badge")
    return hbox(f"focus order marker {n}", [text("number", str(n), CAPTION, TEXT_ON_ACTION)],
                {"fill": RING, "radius": R_BADGE, "justify": "center"}, w=20, h=20, x=x, y=y,
                note="board marker, not product UI")


def timeline(name: str, max_ms: int, marks: list[tuple[int | None, str, list[str]]], *, w_: int = PANEL_W,
             h: int = 196) -> Node:
    """A horizontal time axis 0 … max_ms on color.surface.raised with one tick per mark (ms; None = off the time
    scale, drawn at the right edge as a verdict) and its label lines under it (type.ui.caption). Labels are spec text."""
    pad, lab_w = 16, 200
    usable = w_ - 2 * pad - lab_w
    kids: list[Node] = [rect("axis", w_ - 2 * pad, 2, BORDER_STRONG, x=pad, y=40)]
    for j, (ms, head, lines) in enumerate(marks):
        x = pad + (usable if ms is None else round(usable * ms / max_ms))
        kids.append(rect(f"tick {j + 1}", 2, 20, TEXT_1 if ms is not None else TEXT_3, x=x, y=31))
        kids.append(text(f"tick label {j + 1}", head, NUM_SM, TEXT_1, x=x, y=12))
        if lines:
            body = vbox(f"mark {j + 1} · lines", [text(f"line {i + 1}", s, CAPTION, TEXT_2, w=lab_w - 8)
                                                  for i, s in enumerate(lines)], {"gap": STACK_XS}, w=lab_w - 8)
            kids.append(dict(body, x=x, y=58))
    starts = sorted(k["x"] for k in kids if k["name"].endswith("· lines"))
    if any(b - a < lab_w for a, b in zip(starts, starts[1:])) or (starts and starts[-1] + lab_w - 8 > w_ - pad):
        raise ValueError(f"{name}: mark labels overlap or overrun ({starts}, label {lab_w} px)")
    for k in kids:
        if k.get("y", 0) + est_height(k) > h:
            raise ValueError(f"{name}: {k['name']!r} ends at {k['y'] + est_height(k):.0f} > {h}")
    return box(name, kids, {"fill": RAISED, "radius": R_CARD, "stroke": BORDER, "strokeWidth": HAIR,
                            "strokeAlign": "inner", "clip": True}, w=w_, h=h,
               note="board diagram of §7's constants (not product UI)")


def spec_table(name: str, cols: list[Col], rows: list[dict[str, str]], *, cap: str, w_: int = PANEL_W) -> Node:
    """A spec table drawn as a CMP-049-style grid on the panel surface (caption, header row, rows); cell strings are
    the spec's own."""
    if sum(c.w for c in cols) != w_:
        raise ValueError(f"{name}: columns {sum(c.w for c in cols)} != {w_}")
    body = [table_row(cols, r, f"row · {j + 1:02d}", fill=RAISED if j % 2 else CANVAS) for j, r in enumerate(rows)]
    return vbox(name, [text("caption", cap, CAPTION, TEXT_2, w=w_ - 16), header_row(cols),
                       rect("header rule", w_, 1, BORDER), rows_block(body)], {"gap": STACK_XS}, w=w_)


def callout(lines: list[str], *, w_: int = 400, name: str = "redline callout") -> Node:
    """A redline: a 24 px leader (1 px color.border.strong) then the token lines (FALLBACKS["redline"])."""
    fallback("redline")
    return hbox(name, [rect("leader", 24, 1, BORDER_STRONG),
                       vbox("lines", [text(f"line {i + 1}", s, CAPTION, TEXT_1, w=w_ - 32) for i, s in enumerate(lines)],
                            {"gap": STACK_XS}, w=w_ - 32)], {"gap": INSET_SM, "align": "center"}, w=w_,
                note="board marker, not product UI")


def ratio_line(element: str, theme: str = "dark") -> str:
    """'<fg> on <bg> · <role> · <ratio>:1 (<theme>)' from §11's row (CONTRAST)."""
    fg, bg, role, dk, lt, hc, ln = CONTRAST[element]
    r = {"dark": dk, "light": lt, "hc": hc}[theme]
    floor = "4.5" if plain(role) == "text" else "3"
    return f"{fg} on {bg} · {plain(role)} · {r}:1 {theme} (bar {floor}:1; §11 L{ln})"


# --- sections (<= SECTION_RAW_BUDGET raw bytes each; the E08-D09 kit's packer, copied), lint
def _size(section_: dict[str, Any]) -> int:
    return len(json.dumps(section_))


_MEMO: dict[tuple[int, str, int], list[dict[str, Any]]] = {}


def _pack(n: Node, path: str, room: int, budget: int) -> tuple[Node | None, list[tuple[str, Node]]]:
    if len(json.dumps(n)) <= room:
        return n, []
    bare = {k: v for k, v in n.items() if k != "kids"}
    if n["t"] != "board" or len(json.dumps(bare)) > room:
        return None, []
    me = f"{path}/{n['name']}" if path else n["name"]
    kids = list(n.get("kids") or [])
    kept: list[Node] = []
    while len(kept) < len(kids) and len(json.dumps(dict(bare, kids=[*kept, kids[len(kept)]]))) <= room:
        kept.append(kids[len(kept)])
    j = len(kept)
    if j == len(kids):
        return dict(bare, kids=kept), []
    shallow = [(me, k) for k in kids[j:]]
    used = len(json.dumps(dict(bare, kids=[*kept, {}]))) - 2
    part, rest = _pack(kids[j], me, room - used, budget)
    if part is not None:
        deep = rest + [(me, k) for k in kids[j + 1:]]
        if sum(len(_emit(k, p, budget)) for p, k in deep) < sum(len(_emit(k, p, budget)) for p, k in shallow):
            return dict(bare, kids=[*kept, part]), deep
    return (dict(bare, kids=kept) if kept else bare), shallow


def _emit(n: Node, into: str, budget: int) -> list[dict[str, Any]]:
    key = (id(n), into, budget)
    if key not in _MEMO:
        part, cut = _pack(n, into, budget - (_size({"into": into, "node": {}}) - 2), budget)
        if part is None:
            raise ValueError(f"node {n['name']!r}: not even its bare board fits {budget} bytes")
        out = [{"into": into, "node": part}]
        for parent, kid in cut:
            out += _emit(kid, parent, budget)
        _MEMO[key] = out
    return _MEMO[key]


def sections_for(nodes: Iterable[Node], budget: int = SECTION_RAW_BUDGET) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        for n in nodes:
            out += _emit(n, "", budget)
    finally:
        _MEMO.clear()
    return out


def lint(nodes: Iterable[Node]) -> list[str]:
    """Kit rules the validator does not check: no inst; icons in the local set; o.wrap a string; flex children without
    text carry h; no '/' in names; table cells padded 8 px a side (cells are named by their column key)."""
    bad = []

    def has_text(n: Node) -> bool:
        return any(x["t"] == "text" for _p, x in walk(n))

    def rec(n: Node, parent_flex: bool, path: str) -> None:
        p = f"{path}/{n.get('name')}"
        if n["t"] not in _KEYS:
            bad.append(f"{p}: type {n['t']}")
        if "/" in n.get("name", ""):
            bad.append(f"{p}: '/' in name")
        if n["t"] == "icon" and n.get("icon") not in ICONS_OK:
            bad.append(f"{p}: icon {n.get('icon')}")
        o = n.get("o") or {}
        if "wrap" in o and o["wrap"] not in ("wrap", "nowrap"):
            bad.append(f"{p}: wrap {o['wrap']!r}")
        if parent_flex and n["t"] in ("board", "rect", "ellipse") and not n.get("h") and not has_text(n):
            bad.append(f"{p}: flex child without text and without h")
        for k in n.get("kids") or []:
            rec(k, bool(o.get("dir")), p)

    for n in nodes:
        rec(n, False, "")
    for n in nodes:
        for p, x in walk(n):
            if (x["t"] == "board" and re.search(r"/(header row|row[^/]*)/[^/]+$", p) and "padX" in (x.get("o") or {})
                    and (x["o"]["padX"] != INSET_SM)):
                bad.append(f"{p}: cell padX {x['o']['padX']} (8 px a side required)")
    return bad


def _scan_banned(obj: Any) -> list[str]:
    s = json.dumps(obj, ensure_ascii=False)
    return sorted({m.group(0) for m in BANNED.finditer(s)})



# --- the annotation column (ONE, 400 px, outside the frames) and the board
_TABLES = {"V3": V3, "V4": V4, "V51": V51, "V6": V6}


def cite(table: str, row: str, col: int) -> str:
    """A §3 / §4 / §5.1 / §6 cell as an annotation line: '<row> (<column>, L<n>): <cell>'."""
    t = _TABLES[table]
    full, ctx, ln = t[row]
    return f"{row} ({VCOLS[table][col]}, L{ln}): {(full, ctx)[col]}"


def frame_block(fid: str, *, cites: Iterable[tuple[str, str, int]] = (), lines: Iterable[str] = (),
                keyboard: str | None = None) -> tuple[str, list[str]]:
    """One frame's annotation block: the §H id, the spec cells it draws (cites = (table, row, column)), the keyboard
    path and the author's lines (derivations, readings)."""
    if not any(fid in b.frames for b in BOARDS.values()):
        raise KeyError(f"{fid!r} is not a §H frame")
    out = [cite(t, r, c) for t, r, c in cites]
    if keyboard:
        out.append(f"Keyboard: {keyboard}")
    out += [x for x in lines if x]
    return frame_id(fid), out


def data_statement() -> str:
    s, ln = quote("a seeded synthetic history (seed 178), not recorded", "handoff")
    copy_gap(f'board footer "Data: {s}": hand-off §H L{ln} ("declared synthetic on every board\'s face")')
    return f"Data: {s}"


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    b = BOARDS[nn]
    head = [f"§0 L{b.line}: {b.draws}", f"§H L{b.hline}: {', '.join(b.frames)}", f"Theme: {b.theme}" +
            (" (twin: every frame drawn by its base board's builder; theme set at export)" if b.twin else ""),
            f"Export: {b.export}", f"Board footer: {data_statement()}; tick size {TICK} from the recorded instrument "
            f"fixture", *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


def layout(frames: list[Node]) -> list[Node]:
    k = 2 if len(frames) in (2, 4) else MAX_PER_ROW
    out, y, i = [], MARGIN, 0
    while i < len(frames):
        x = MARGIN
        for f in frames[i:i + k]:
            out.append(dict(f, x=x, y=y))
            x += f["w"] + MARGIN
        y += max(f["h"] for f in frames[i:i + k]) + MARGIN
        i += k
    return out


# the live check's root heights: max(annotation end, footer end) + MARGIN as Penpot measured them (build-notes, "Live
# check fold"); the estimate above is the floor a board without a measurement keeps
MEASURED_H = {1: 1878, 2: 1878, 3: 1878, 4: 998, 5: 998, 6: 998, 7: 998, 8: 1129, 9: 998}


def board(nn: int, frames: list[Node], ann: Node, *, strict: bool = True) -> tuple[dict[str, Any], list[Node]]:
    """The root (§0's name, grid x/y, color.surface.app, clip) hugging the frames + ONE annotation column + 80; a
    "state: <id>" caption 28 px above each frame; the data statement 24 px under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f) for f in b.frames]
    got = [f["name"] for f in frames]
    if strict and got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != §H {want}")
    if any(f["w"] != FRAME_W or f["h"] != FRAME_H for f in frames):
        raise ValueError(f"board {nn:02d}: every frame is a {FRAME_W} x {FRAME_H} window (§0)")
    if "/" in b.name.split(f"E08-D10 / {nn:02d} ", 1)[1]:
        raise ValueError(f"board {nn:02d}: '/' after the prefix in {b.name!r}")
    placed = layout(frames)
    ids = {frame_name(f): frame_id(f) for f in b.frames}
    caps = [text(f"caption {i:02d}", f"state: {ids.get(f['name'], f['name'])}", CAPTION, TEXT_3, x=f["x"],
                 y=f["y"] - 28) for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · data statement", data_statement(), CAPTION, TEXT_2, x=MARGIN, y=bottom + 24)]
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    h = int(math.ceil((max(bottom + 24 + 14, MARGIN + ah) + MARGIN) / 8) * 8)
    if strict and nn in MEASURED_H:  # the live-measured end + MARGIN (it must still clear the frames and the footer)
        if MEASURED_H[nn] < bottom + 24 + 14 + MARGIN:
            raise ValueError(f"board {nn:02d}: measured h {MEASURED_H[nn]} < footer end {bottom + 24 + 14} + {MARGIN}")
        h = MEASURED_H[nn]
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch: trim the annotations")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root (h {h}); "
         f"raise the root's h to max(annotation end, footer end) + {MARGIN} if not")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


def validate(path: Path) -> tuple[int, str]:
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(path), "--components", str(COMPONENTS),
                          "--tokens", str(TOKENS_FILE)], capture_output=True, text=True, timeout=120, check=False)
    return res.returncode, "\n".join((res.stdout + res.stderr).strip().splitlines())


def write_sheet(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
                out_dir: Path = CAP_DIR, name: str | None = None, strict: bool = True) -> Path:
    """Assemble board nn, split into sections, merge notes, write out_dir/NN-<slug>.json, run the validator and raise
    RuntimeError unless it exits 0 and the kit lint and the banned scan are clean. Clears NOTES."""
    b = BOARDS[nn]
    out_dir = out_dir.resolve()
    if out_dir not in (CAP_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    root, nodes = board(nn, frames, ann, strict=strict)
    if b.theme != "dark":
        live(f"theme: activate the {b.theme} token set before exporting board {nn:02d}; read back one bound fill "
             f"(color.surface.raised) as the {b.theme} value")
    live(f"export {b.export}: every frame is {FRAME_W} x {FRAME_H}; record the board id and the PNG size")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {DOCS['spec'][0].rsplit('/', 1)[1]} md5 {DOCS['spec'][1][:8]} and hand-off md5 "
                         f"{DOCS['handoff'][1][:8]} (§0 L{b.line}, §H L{b.hline}, §3-§7, §10-§13)")
    for k in ("D04E11", "D02E22", "D03E22", "D02", "D04", "fixture"):
        NOTES.add("sources", f"{DOCS[k][0]} md5 {DOCS[k][1][:8]}")
    used = sorted(NOTES.d["tokens"])
    if any(t in NEVER for t in used):
        raise RuntimeError(f"board {nn:02d}: a NEVER token is bound")
    sheet = {"board": root, "sections": sections_for(nodes), "export": b.export,
             "notes": {k: list(v) for k, v in NOTES.d.items()}}
    NOTES.reset()
    banned = _scan_banned(sheet)
    if bad or banned:
        raise RuntimeError(f"board {nn:02d}: lint {bad[:8]} banned {banned}")
    out = out_dir / (name or b.sheet)
    out.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rc, msg = validate(out)
    if rc != 0:
        errs = [ln for ln in msg.splitlines() if "ERROR" in ln.upper()]
        raise RuntimeError(f"{out.name}: validator exit {rc}\n" + "\n".join(errs[:20] or msg.splitlines()[-20:]))
    return out


def md_line3(nn: int) -> str:
    b = BOARDS[nn]
    return (f"File `{FILE_NAME}`, page `{PAGE}`; export `{b.export}`; sheet `{b.sheet}` (validated); "
            f"theme {b.theme}.")


def write_md(nn: int, sheet_path: Path, *, summary: str = "") -> Path:
    """The sheet's .md beside it: line 1 "# <board name>", line 3 md_line3(nn), then the summary, frames, the
    validator line and the notes (live checks first). Refuses a banned string."""
    b = BOARDS[nn]
    sp = Path(sheet_path).resolve()
    sh = json.loads(sp.read_text(encoding="utf-8"))
    rc, msg = validate(sp)
    x, y = grid_xy(nn)
    out = [f"# {b.name}", "", md_line3(nn), "",
           summary or f"Board {nn:02d} of nine (§0 L{b.line}: {b.draws}). Grid ({x}, {y}); {sh['board']['w']} x "
                      f"{sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".", "", "## Frames", ""]
    out += [f"- `{frame_name(f)}` (§H `{frame_id(f)}`)" for f in b.frames]
    out += ["", "## Validator and size", "", f"- `{msg.splitlines()[-1] if msg else ''}` (exit {rc})",
            f"- {len(sh['sections'])} sections, {len(json.dumps(sh))} bytes", ""]
    for kd in ("live_checks", "derivations", "spec_gaps", "deviations", "copy_keys", "copy_gaps", "g_rows",
               "fallbacks", "sources", "tokens"):
        lines = sh["notes"].get(kd) or []
        out += [f"## {kd.replace('_', ' ').capitalize()} ({len(lines)})", ""] + [f"- {ln}" for ln in lines] + [""]
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    m = BANNED.search(s)
    if m:
        raise RuntimeError(f"md for board {nn:02d}: banned string {m.group(0)!r}")
    p = sp.parent / (sp.stem + ".md")
    p.write_text(s, encoding="utf-8")
    if sp.parent == CAP_DIR.resolve():  # the committed copy beside the kit
        (KIT_DIR / p.name).write_text(s, encoding="utf-8")
    return p


def pack_sheet(sheet_path: Path, out_dir: Path = V4_DIR) -> Path:
    """Pack with compact.py into out_dir/<same name>; the packer writes the source's absolute path into compactOf.file,
    which is then rewritten to the bare file name (the sha256 beside it is the source's, unchanged); check that, every
    packed section <= PACKED_MAX bytes, and that mkcall4.py's `count` agrees."""
    src = Path(sheet_path).resolve()
    out_dir = out_dir.resolve()
    if out_dir not in (V4_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"packed sheets go to {V4_DIR}")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (src.name if out_dir == V4_DIR.resolve() else src.stem + ".packed.json")
    res = subprocess.run([sys.executable, "-I", str(PACKER), str(src), str(dst)], capture_output=True, text=True,
                         timeout=300, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"packer exit {res.returncode}: {(res.stdout + res.stderr).strip()[-600:]}")
    raw = dst.read_text(encoding="utf-8")
    pf = (json.loads(raw).get("compactOf") or {}).get("file")
    if not pf or not Path(pf).is_absolute() or Path(pf) != src:
        raise RuntimeError(f"{dst.name}: compactOf.file {pf!r} is not the absolute source path")
    n_sec = len(json.loads(raw)["sections"])  # mkcall4 reads the pack source, so count before the name is made bare
    cnt = subprocess.run([sys.executable, "-I", "-B", str(MKCALL), str(dst), "count"], capture_output=True, text=True,
                         timeout=120, check=False)
    if cnt.returncode != 0 or cnt.stdout.strip() != str(n_sec):
        raise RuntimeError(f"{dst.name}: mkcall4 count {cnt.stdout.strip()!r} rc {cnt.returncode} "
                           f"!= {n_sec}: {cnt.stderr.strip()[-300:]}")
    abs_field = json.dumps(pf, ensure_ascii=False)
    if raw.count(abs_field) != 1:
        raise RuntimeError(f"{dst.name}: the pack source path occurs {raw.count(abs_field)} times")
    dst.write_text(raw.replace(abs_field, json.dumps(src.name, ensure_ascii=False)), encoding="utf-8")
    sh = json.loads(dst.read_text(encoding="utf-8"))
    if sh["compactOf"] != {"file": src.name, "sha256": hashlib.sha256(src.read_bytes()).hexdigest()}:
        raise RuntimeError(f"{dst.name}: compactOf {sh['compactOf']!r} is not the bare name and sha256 of {src.name}")
    big = [(s["node"]["name"], n) for s in sh["sections"]
           if (n := len(json.dumps(s, ensure_ascii=False, separators=(",", ":")).encode())) > PACKED_MAX]
    if big:
        raise RuntimeError(f"{dst.name}: packed sections over {PACKED_MAX} B: {big[:5]}")
    return dst


def build(nn: int, frames: list[Node], blocks: list[tuple[str, list[str]]], *,
          board_lines: Iterable[str] = (), summary: str = "") -> tuple[Path, Path, Path]:
    """write_sheet + write_md + pack_sheet for one board (the generators' last step)."""
    ann = annotations(nn, blocks, board_lines=board_lines)
    p = write_sheet(nn, frames, ann)
    return p, write_md(nn, p, summary=summary), pack_sheet(p)


# --- self-test: python3 -I -B e08d10kit.py selftest
def sample_frame() -> tuple[Node, tuple[str, list[str]]]:
    """Board 01's in-context frame as the sample: rows loaded, the backfilling chip and W-3 in the status slot."""
    fid = BOARDS[1].frames[2]
    t = history_title()
    room = PANEL_H - 41 - 1 - ROW_H
    p = panel("history panel", title(t), [bf_chip(), words("progress words", w3(N_CONTEXT))],
              history_body(latest(40), room=room), footer=loaded_caption(N_CONTEXT))
    return window(fid, p, proposed=True), frame_block(fid, cites=[("V3", "Surface", 1)])


def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), f"pinned md5s ({len(DOCS)} sources)")
    check(sorted(BOARDS) == list(range(1, 10)), "§0: nine boards 01-09")
    th = [b.theme for b in BOARDS.values()]
    check((th.count("dark"), th.count("light"), th.count("hc")) == (7, 1, 1), "§0 themes 7 dark / 1 light / 1 hc")
    check(sum(b.twin for b in BOARDS.values()) * 3 <= len(BOARDS), "twins <= one third")
    nf = [len(b.frames) for b in BOARDS.values()]
    check(nf == [4, 4, 4, 2, 3, 3, 1, 3, 2], f"§H frames per board {nf}")
    bases = {base_of(f) for b in BOARDS.values() if not b.twin for f in b.frames}
    check(all(base_of(f) in bases for b in BOARDS.values() if b.twin for f in b.frames), "every twin frame has a base")
    check(all("/" not in frame_name(f) and SLASH in frame_name(f) for b in BOARDS.values() for f in b.frames),
          "frame names carry U+2215, never '/'")
    check(sorted(COPY, key=lambda x: int(x[2:])) == [f"W-{i}" for i in range(1, 19)], f"§13: {len(COPY)} strings")
    refill = all(_SLOT.sub(lambda m, it=iter(ILLUSTRATIVE[k]): next(it), TEMPLATES[k]) == COPY[k].text
                 for k in TEMPLATES)
    check(refill, "templates refilled with the illustrative values give the deck strings")
    check(w3(3200).startswith("Loaded 3 200 of about") and back_to(N_CONTEXT) == "2026-08-12",
          f"world: W-3 {w3(N_CONTEXT)!r}; 3 200 bars back reach {back_to(N_CONTEXT)} (the deck's date)")
    check(TARGET == 4896 and str(TICK) == "0.10" and PRICE_DP == 1, f"target {TARGET}, tick {TICK}")
    check(len(TIMING) == 7 and len(ANNOUNCE) == 7 and len(CONTRAST) == 11 and len(EVENTS) == 3 and len(CLASSES) == 4,
          "§7 seven T rows, §10.2 seven rows, §11 eleven pairs, §12 three events, §5.2 four classes")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for k, v in globals().items() if k.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border|opacity)\.", v)]
    used += [x for fg, bg, *_r in CONTRAST.values() for x in (fg, bg)]
    check(all(u in toks for u in used if u not in NEVER), f"kit and §11 tokens exist (missing "
          f"{sorted(set(u for u in used if u not in toks and u not in NEVER))})")
    try:
        w("W-3")
        check(False, "w(): illustrative numbers refused without slots")
    except ValueError:
        check(True, "w(): illustrative numbers refused without slots")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError):
            pass
    check(True, "inst, unknown icon, boolean wrap and '/' refused")
    NOTES.reset()
    fr, blk = sample_frame()
    ann = annotations(1, [blk], board_lines=["Self-test sheet: one sample frame, not a board of the set"])
    path = write_sheet(1, [fr], ann, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False,
                       notes={"live_checks": ["self-test sheet: not for rendering"]})
    check(path.exists(), f"validator exit 0: {path.name}")
    md = write_md(1, path, summary="Self-test sheet (one sample frame); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    mp = re.search(r"page `([^`]+)`", l3)
    check(bool(mp) and mp.group(1) == PAGE and l3.endswith("theme dark."), f"md line 3 parses: {l3}")  # type: ignore
    check(md_line3(8).endswith("theme light.") and md_line3(9).endswith("theme hc."), "md line 3: light and hc")
    packed = pack_sheet(path, SELFTEST_DIR)
    sh = json.loads(packed.read_text(encoding="utf-8"))
    check(sh["compactOf"]["file"] == path.name, f"packed {packed.name}: bare pack source name, sha256 ok, "
          f"{len(sh['sections'])} sections, mkcall4 count agrees")
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
    raise SystemExit(2)
