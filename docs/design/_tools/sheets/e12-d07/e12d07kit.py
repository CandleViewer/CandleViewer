"""E12-D07 (#242) board kit: SCR-045, the per-bar-mode data table, PR 2's ten boards as cvsheet JSON sheets.

Offline only. Spec (binding; every string comes from it): docs/design/E12/E12-D07.md and E12-D07-handoff.md as
this checkout commits them (read by repo-relative path; md5s pinned in SPEC_MD5: the kit refuses drifted bytes). The
SCR-045 shell is E11-D04's (consumed, never redrawn differently); the window chrome and the chart panel geometry
follow the committed E12-D04 board kit (docs/design/_tools/sheets/e12-d04: TopBar 80, NavRail 64, RightRail strip 48,
StatusBar 48, tab strip 32, panel focus inset 2, compact controls 24).

Pipeline: a generator per board builds frames with this kit, then
    sheet = write_sheet(nn, frames, ann)      # build/NN-<slug>.json (untracked), validated (exit 0) or RuntimeError
    write_md(nn, sheet_path, frames_info)     # NN-<slug>.md in this folder, line 3 = the render script's line
    pack_sheet(sheet_path)                    # v4/NN-<slug>.json, compactOf.file = the bare name, sections <= 9 KB
Self-test: python3 -I e12d07kit.py selftest   (builds one sample frame into build/selftest/, validates, packs, exits 0)
Rebuild all ten: BUILD.md in this folder.

Penpot lessons kept as hard checks: no "inst" node (the per-set file has no library components); icons only from
ICONS_OK; o.wrap only "wrap"/"nowrap"; every flex child without text carries an explicit h; no "/" in a node name
(section paths split on it; spec frame ids are drawn with U+2215 in place of "/"); no local path, host or agent name in
any text, note or name (BANNED); packed sections <= 9 KB.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import subprocess
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KIT_DIR = Path(__file__).resolve().parent
SHEETS_DIR = KIT_DIR.parent
CAP_DIR = KIT_DIR / "build"  # the raw sheets of the ten boards (untracked: .gitignore); their .md go to KIT_DIR
SELFTEST_DIR = CAP_DIR / "selftest"  # the self-test's sheet, md and packed sheet
V4_DIR = KIT_DIR / "v4"  # packed sheets (the renderer's input, committed)
VALIDATOR = SHEETS_DIR / "tools" / "validate_sheet.py"
PACKER = SHEETS_DIR / "tools" / "compact.py"
COMPONENTS = SHEETS_DIR / "tools" / "components.offline.json"
TOKENS_FILE = SHEETS_DIR / "tools" / "token-sync.json"
REPO = KIT_DIR.parents[4]  # the checkout's root: every spec read is REPO / <repo-relative path>, md5-pinned below


def _repo(rel: str) -> Path:
    """A repo-relative path in this checkout (the committed text; SPEC_MD5 refuses drifted bytes)."""
    return REPO / rel


SPEC = _repo("docs/design/E12/E12-D07.md")
HANDOFF = _repo("docs/design/E12/E12-D07-handoff.md")
SHELL = _repo("docs/design/E11/E11-D04.md")
D06 = _repo("docs/design/E12/E12-D06.md")
SPEC_MD5 = {SPEC.name: "561a7fee320d3d728e5ab74c1448497e", HANDOFF.name: "5f7f9099d51cd9182539b94221f8b627",
            SHELL.name: "02f3ff690f4c840aebb734889d0a17c6", D06.name: "b9a9bc5790d48a240c24e915d4d046a6"}

FILE_NAME = "E12-D07 boards"
PAGE = "E12-D07 SCR-045 data table"
REV = "r1"
PITCH_X, PITCH_Y = 6000, 3200  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80  # root margin and frame gutters (no 80 px spacing token: positions, not a flex gap)
ANN_W = 400  # the one annotation column, outside the frames
FRAME_W, FRAME_H = 1280, 800
MAX_PER_ROW = 3  # frames per row on a board (4 frames: 2 x 2)
SECTION_RAW_BUDGET = 9000  # raw section JSON (json.dumps defaults); the packed section is smaller
PACKED_MAX = 9216  # "each packed section <= ~9 KB"
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode() + r"\b", re.I)


def _read(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").split("\n")


def spec_md5_ok() -> dict[str, bool]:
    """Each pinned doc's md5 against SPEC_MD5 (a drift means line citations and parsed strings must be re-read)."""
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() == SPEC_MD5[p.name] for p in (SPEC, HANDOFF, SHELL, D06)}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:  # fail loudly: every L<n> cite and every parsed string assumes the pinned bytes
    raise SystemExit(f"e12d07kit: spec text drifted from SPEC_MD5 ({', '.join(_DRIFT)}): re-check the cites, re-pin")
SPEC_LINES = _read(SPEC)
HANDOFF_LINES = _read(HANDOFF)


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def find_line(needle: str, lines: list[str] | None = None, start: int = 1) -> int:
    """1-based number of the first line at or after start containing needle (raises if absent)."""
    ls = SPEC_LINES if lines is None else lines
    for i in range(start - 1, len(ls)):
        if needle in ls[i]:
            return i + 1
    raise LookupError(f"not found: {needle!r}")


def L(needle: str, start: int = 1) -> int:
    """The spec line a board cites (find_line on E12-D07.md): cites are looked up, never typed as numbers."""
    return find_line(needle, start=start)


def HL(needle: str, start: int = 1) -> int:
    """The hand-off line a board cites (find_line on E12-D07-handoff.md)."""
    return find_line(needle, HANDOFF_LINES, start)


# --- §0: the ten boards (registry parsed from the spec) and §H: their frames (parsed from the hand-off)
@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E12-D07 / 01 time-bars"
    slug: str
    draws: str
    theme: str  # dark | light
    line: int  # §0 line
    frames: tuple[str, ...] = ()  # hand-off §H frame ids, "time/default · dark"
    twin: int | None = None  # light twin of board N

    @property
    def export(self) -> str:
        return f"docs/design/E12/img/E12-D07-{self.nn:02d}-{self.slug}.png"

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"


_B_ROW = re.compile(r"^\|\s*(\d{2})\s*\|\s*`(E12-D07 / (\d{2}) ([a-z0-9-]+))`\s*\|(.*)\|\s*(dark|light)\s*\|(.*)\|\s*$")
_F_ROW = re.compile(r"^\|\s*(\d{2})\s*\|\s*(`.*`)\s*\|\s*$")
_TWIN = re.compile(r"light twin of (\d{2})")


def _parse_boards() -> dict[int, Board]:
    s0 = find_line("## 0. Status, artefacts and the boards")
    s1 = find_line("## 1. Purpose", start=s0)
    frames: dict[int, tuple[str, ...]] = {}
    h0 = find_line("## §H The board plan", HANDOFF_LINES)
    for ln in HANDOFF_LINES[h0:]:
        if ln.startswith("## "):
            break
        m = _F_ROW.match(ln)
        if m:
            frames[int(m.group(1))] = tuple(re.findall(r"`([^`]+)`", m.group(2)))
    out: dict[int, Board] = {}
    for i in range(s0, s1):
        m = _B_ROW.match(SPEC_LINES[i - 1])
        if not m:
            continue
        nn = int(m.group(1))
        if int(m.group(3)) != nn:
            raise ValueError(f"§0 L{i}: row {nn} names board {m.group(3)}")
        draws = m.group(5).strip()
        tw = _TWIN.search(draws)
        out[nn] = Board(nn, m.group(2), m.group(4), draws, m.group(6), i, frames.get(nn, ()),
                        int(tw.group(1)) if tw else None)
    return out


BOARDS = _parse_boards()
LIGHT_TWINS = {nn: b.twin for nn, b in BOARDS.items() if b.twin}  # {9: 4, 10: 5}
PAIRS = ((1, 6), (2, 8), (3, 7), (4, 9), (5, 10))  # five parallel authors; a light twin pairs with its base board


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


def frame_name(fid: str) -> str:
    """The Penpot frame name for a hand-off frame id: "SCR-045/" + id, every "/" drawn as U+2215 (section paths split
    on "/"; the layer reads the same). frame_name("time/default · dark") == "SCR-045∕time∕default · dark"."""
    return ("SCR-045/" + fid).replace("/", "∕")


# --- §13 the copy deck (W-n, verbatim), §3.1 the columns, §6 the state words, §7.1 the separator kinds
def _parse_copy() -> dict[str, tuple[str, int, str]]:
    a = find_line("## 13. Copy deck")
    out: dict[str, tuple[str, int, str]] = {}
    for i in range(a, find_line("## 14. Tokens", start=a)):
        c = _cells(SPEC_LINES[i - 1])
        if c and re.fullmatch(r"W-\d+", c[0]):
            out[c[0]] = (c[1].strip('"'), i, c[3])
    return out


COPY = _parse_copy()  # "W-1" -> (string, spec line, status)
MODES = ("time", "tick", "volume", "range", "delta", "renko")


@dataclass(frozen=True)
class Column:
    name: str
    chars: tuple[int, int]  # (time, non-time)
    tiers: dict[str, str]  # mode -> "P" | "A" | "E" | "—"
    kind: str  # field | derived | —
    rest: str
    ws: str
    note: str
    line: int

    def width(self, mode: str) -> int:
        """Cell width in CSS px: chars x 6.6 (11 px mono, 0.6 em) + 16 (8 px padding a side), §5's arithmetic."""
        ch = self.chars[0] if mode == "time" else self.chars[1]
        return round(ch * 6.6 + 16)


def _parse_columns() -> dict[str, Column]:
    a = find_line("### 3.1 The column table")
    out: dict[str, Column] = {}
    for i in range(a, find_line("### 3.2", start=a)):
        c = _cells(SPEC_LINES[i - 1])
        if len(c) != 11 or c[0] in ("Column",) or set(c[0]) <= {"-", " "}:
            continue
        nm = "time" if c[0].startswith("time") else c[0]
        ch = [int(x) for x in re.findall(r"\d+", c[1])]
        tiers, kinds = {}, set()
        for m, cell in zip(MODES, c[2:8], strict=True):
            t = cell.split()
            tiers[m] = t[0]
            if len(t) > 1:
                kinds.add(t[1])
        out[nm] = Column(nm, (ch[0], ch[-1]), tiers, "/".join(sorted(kinds)) or "—", c[8].replace("`", ""),
                         c[9].replace("`", ""),
                         c[10], i)
    return out


COLUMNS = _parse_columns()  # 17 columns (§3.1 COUNT:columns)
COL_ORDER = ("time", "open", "high", "low", "close", "volume", "delta", "trades", "buy", "sell", "range", "brick",
             "state", "close time", "duration", "CVD", "change")
EXTRA_COLS = {  # chart-type cells (§4) and E11-D04's extended slots; widths are kit choices where §3.1/§5 give none
    "vs base": Column("vs base", (9, 9), {m: "A" for m in MODES}, "derived", "c", "c", "c − B (§4)", 0),
}
STATE_ORDER = ("forming", "stale", "corrected", "width capped", "no range", "Est.", "POC")  # §6 precedence


def state_word(words: Iterable[str]) -> str:
    """The `state` cell (§6): the first applicable word in STATE_ORDER, E11-D04's joined "Est.·POC" kept, "—" when none."""
    ws = set(words)
    bad = ws - set(STATE_ORDER)
    if bad:
        raise ValueError(f"not a §6 state word: {sorted(bad)}")
    if ws == {"Est.", "POC"}:
        return "Est.·POC"
    for w in STATE_ORDER:
        if w in ws:
            return w
    return "—"


SEPARATORS = {  # §7.1 kind -> (copy key or E11-D04 band, action label or None)
    "seam": ("W-1", None),
    "gap-non-time": ("W-2", None),
    "gap-time": ("W-3", None),
    "kline-hole": ("W-4", None),
    "partial-history": ("W-5", None),
    "built-start": ("W-6", "Build earlier bars"),
    "lookback": ("W-7", "Load more"),
    "before-history": ("D04E11:326", "Show coverage"),
    "loading-older": ("D04E11:325", None),
}
SEP_ORDER = ("before-history", "lookback", "built-start", "partial-history", "gap-non-time", "gap-time",
             "kline-hole", "seam")  # §7.1: top to bottom where two meet ("before recorded history or lookback" first)
E11_BANDS = {"before-history": "History starts 2026-09-01 08:00 UTC — recording began then",  # D04E11 §10 (L326)
             "loading-older": "Loading older bars…"}  # D04E11 §10 (L325)


def copy(key: str, **fills: str) -> str:
    """A §13 string verbatim; "<ts>" is the only fill slot (W-5, W-6). Records the key."""
    s = COPY[key][0]
    if "<ts>" in s:
        if "ts" not in fills:
            raise KeyError(f"{key} needs ts=")
        s = s.replace("<ts>", fills["ts"])
    NOTES.add("copy_keys", f"{key} (§13 L{COPY[key][1]}, {COPY[key][2].split(';')[0]})")
    return s


# --- §5 the width table, re-derived (the self-test compares with the spec's numbers)
def set_width(mode: str, tiers: str = "P", *, equi: bool = False) -> float:
    """Table width in CSS px for a mode's columns of the given tiers ("P" or "PA"): 633 + 6.6/char + 16/col beyond
    E11-D04's 65 chars in 8 columns (§5)."""
    cols = [c for c in COLUMNS.values() if c.tiers[mode] in tiers]
    ch = sum((c.chars[0] if mode == "time" else c.chars[1]) for c in cols) + (3 if equi else 0)
    return round(633 + (ch - 65) * 6.6 + (len(cols) - 8) * 16, 1)


def shown_columns(mode: str, *, auto: bool = False, extended: Iterable[str] = (), chart: str = "candle") -> list[str]:
    """The visible header words in order: the mode's P columns, its A columns when auto, the chart type's cells (§4),
    then any extended ones asked for."""
    tiers = "PA" if auto else "P"
    out = [n for n in COL_ORDER if COLUMNS[n].tiers[mode] in tiers]
    if chart == "delta-volume" and mode != "delta" and auto:
        out += [n for n in ("buy", "sell") if n not in out]
    if chart == "baseline" and auto:
        out.append("vs base")
    out += [n for n in extended if n not in out]
    order = list(COL_ORDER) + ["vs base"]
    return sorted(out, key=order.index)


def column(name: str) -> Column:
    return COLUMNS.get(name) or EXTRA_COLS[name]


def col_px(name: str, mode: str, *, equi: bool = False) -> int:
    if name == "state" and equi:
        return round(12 * 6.6 + 16)  # §5: equi-volume widens `state` to 12 characters for `width capped`
    return column(name).width(mode)


# --- tokens (exact names in token-sync.json; the self-test checks every one)
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
BORDER, BORDER_STRONG, RING = "color.border.default", "color.border.strong", "color.focus.ring"
BUY_TEXT, SELL_TEXT = "color.buy.default", "color.sell.default"  # FALLBACKS["buy-sell"]
UP, DOWN, WICK, AXIS = "color.candle.up", "color.candle.down", "color.candle.wick", "color.axis.text"
WARN_SUBTLE, WARN_STRONG = "color.status.warning.subtle", "color.status.warning.strong"
ENV_DEMO, ENV_LIVE = "color.env.demo", "color.env.live"
NUM, CAPTION, LABEL, BODY = "type.num.sm", "type.ui.caption", "type.ui.label", "type.ui.body"
BODY_STRONG, HEADING_SM = "type.ui.body-strong", "type.ui.heading-sm"
INSET_XS, INSET_SM, INSET_MD, INSET_LG = "space.inset.xs", "space.inset.sm", "space.inset.md", "space.inset.lg"
STACK_XS, STACK_SM = "space.stack.xs", "space.stack.sm"
ICON_SM, ICON = "size.icon.sm", "size.icon"  # 12 px (Tier-1, validator WARN) / 16 px
R_CONTROL, R_CARD, R_BADGE = "radius.control", "radius.card", "radius.badge"
HAIR, FOCUS_W = "border.hairline", "border.focus"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, STACK_XS: 4, STACK_SM: 8, ICON_SM: 12, ICON: 16}
FALLBACKS = {
    "buy-sell": "fallback: color.text.buy / color.text.sell (E11-D04 CR-D04-2 = E11-D02 CR-5, unregistered) drawn as "
                "color.buy.default / color.sell.default; the sign (+ / −) is the carrier (D04E11 §5.4)",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the expander, check and sort glyphs",
}
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}


# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "spec_gaps", "fallbacks", "tokens", "live_checks", "deviations")


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


def deviate(line: str) -> None:
    NOTES.add("deviations", line)


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
    """A node of type t (None values dropped). Refuses inst nodes, unknown keys, "/" in the name, a boolean or other
    o.wrap, and a banned string (local path, host, agent name) in the name or note. Records bound tokens."""
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


def icon(name: str, glyph: str, color: str = TEXT_2, size: str = ICON, **kw: Any) -> Node:
    if glyph not in ICONS_OK:
        raise ValueError(f"icon {glyph!r} not in the local set {sorted(ICONS_OK)}")
    if size == ICON_SM:
        fallback("icon-sm")
    return node("icon", name, icon=glyph, color=color, size=size, **kw)


def rect(name: str, w: float, h: float, fill: str | None = None, o: dict[str, Any] | None = None, **kw: Any) -> Node:
    opts = dict(o or {})
    if fill:
        opts["fill"] = fill
    return node("rect", name, w=w, h=h, o=opts or None, **kw)


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


# --- text metrics (estimates; Inter / JetBrains Mono at 0.6 em)
_FONT = {CAPTION: (11, 1.2, False), BODY: (13, 1.4, False), BODY_STRONG: (13, 1.4, False), LABEL: (12, 1.2, False),
         HEADING_SM: (14, 1.2, False), NUM: (11, 1.2, True), "type.num.base": (13, 1.2, True)}


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
    if o.get("dir") == "row":
        return pad + max((est_height(k) for k in kids), default=0.0)
    return max((float(k.get("y", 0)) + est_height(k) for k in n.get("kids") or []), default=0.0)


# --- data: one seeded trade stream (random.Random(SEED)) and honest bar builders. The world: generation 1 records
# 2026-10-19 16:40-17:02 UTC; a recording gap 17:02-09:14 (W-2's placeholder times); generation 2 restarts 09:15 (W-1)
# and runs to the last good time 13:42:05 (§6.2's "values as of 13:42:05"), its last bar forming; a buy sweep of
# SWEEP_N prints at 2026-10-20 10:22:11.412 (§2.2's example time) makes several non-time bars share one open time.
# Time-axis kline rows (no delta, no trades): 16:00-16:39 before order flow starts (W-5) and 17:02-09:14 (W-3 / W-4).
SEED = 242
TICK = 0.1  # BTCUSDT tickSize 0.10, qtyStep 0.001 (packages/fixtures/bybit/2026-10-05/rest/instruments_before.json)
P0_TICKS = 640000  # 64,000.0 (E11-D04's caption example's level)
RATE_MS = 125  # mean inter-arrival (8 prints / s)
SWEEP_N = 4600
PARAMS = {"tick": 1000, "volume": 50.0, "range": 40, "delta": 25.0, "renko": 30}  # D09 first-use defaults (W-11..W-15)
SHORT = {"time": "1m", "tick": "Tick 1,000", "volume": "Vol 50 BTC", "range": "Range 40", "delta": "Delta 25 BTC",
         "renko": "Renko 30"}  # D09:150-155 short labels (the toolbar trigger); time: the chart's own interval


def utc_ms(s: str) -> int:
    """"2026-10-20 10:22:11.412" (UTC) -> epoch ms."""
    fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in s else "%Y-%m-%d %H:%M:%S"
    return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)


GEN1 = (utc_ms("2026-10-19 16:40:00"), utc_ms("2026-10-19 17:02:00"))
GEN2 = (utc_ms("2026-10-20 09:15:00"), utc_ms("2026-10-20 13:42:05"))
SWEEP_AT = utc_ms("2026-10-20 10:22:11.412")
SEAM_AT = utc_ms("2026-10-20 11:30:00")  # a builder cold start with no recording gap: non-time generation 3 (W-1 row)
QUIET_MIN = utc_ms("2026-10-20 13:33:00")  # one print in this minute: a flat 1m bar (`no range`)
LAST_GOOD = "13:42:05"


@dataclass(frozen=True)
class Trade:
    t: int
    p: int  # price in ticks
    q: int  # qty in thousandths (qtyStep 0.001)
    buy: bool


def _stream(a: int, b: int, rng: random.Random, p: int) -> list[Trade]:
    out: list[Trade] = []
    t = a
    while True:
        t += int(rng.expovariate(1 / RATE_MS))
        if t >= b:
            return out
        pb = 0.5 + 0.35 * math.sin(2 * math.pi * t / 600000.0)
        buy = rng.random() < pb
        r = rng.random()
        p += (1 if r < 0.22 else -1 if r > 0.78 else 0) + (1 if buy and r < 0.05 else 0) - (1 if not buy and r < 0.05 else 0)
        q = max(1, int(rng.expovariate(1 / 50)))
        if rng.random() < 0.01:
            q *= 20
        out.append(Trade(t, p, q, buy))


_CACHE: dict[str, Any] = {}


def trades() -> dict[int, list[Trade]]:
    """{generation: trades}, deterministic (SEED). Generation 2 carries the sweep at SWEEP_AT, inserted at a tick-bar
    boundary so the sweep's first print opens bar 1 of its open time."""
    if "trades" in _CACHE:
        return _CACHE["trades"]
    rng = random.Random(SEED)
    g1 = _stream(GEN1[0], GEN1[1], rng, P0_TICKS - 40)
    g2 = _stream(GEN2[0], GEN2[1], rng, (g1[-1].p if g1 else P0_TICKS) + 25)
    k = max(i for i, tr in enumerate(g2) if tr.t < SWEEP_AT and i % PARAMS["tick"] == 0)  # a quiet run before it
    j = next(i for i, tr in enumerate(g2) if tr.t > SWEEP_AT)
    p = g2[k - 1].p
    sweep = [Trade(SWEEP_AT, p + i // 40, 40 + (i * 37) % 90, True) for i in range(SWEEP_N)]
    g2 = g2[:k] + sweep + [replace(tr, p=tr.p + SWEEP_N // 40) for tr in g2[j:]]
    quiet = [i for i, tr in enumerate(g2) if QUIET_MIN <= tr.t < QUIET_MIN + 60000]
    g2 = g2[:quiet[0] + 1] + g2[quiet[-1] + 1:]  # keep the minute's first print only
    _CACHE["trades"] = {1: g1, 2: g2}
    return _CACHE["trades"]


@dataclass
class Bar:
    """One row's source: `22` Bar / `23` bars item fields (t, o, h, l, c, v, delta, trades, close_time, confirm,
    amended) plus generation/index (R-4) and the flags the `state` cell and the separators read."""
    gen: int
    index: int
    t: int  # open time, ms
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: float
    delta: float | None  # None: kline-backfilled or not sent ("—")
    trades: int | None
    close_t: int | None = None  # non-time bars only; None on the forming row
    confirm: bool = True
    words: set[str] = field(default_factory=set)  # extra §6 words: stale, corrected, width capped, Est., POC
    kline: bool = False
    k: int = 1  # "bar k of n" (non-time; restarts per generation, §2.2)
    n: int = 1

    @property
    def state(self) -> str:
        ws = set(self.words)
        if not self.confirm:
            ws.add("forming")
        if self.o == self.h == self.l == self.c:
            ws.add("no range")
        return state_word(ws)


def _bar(gen: int, idx: int, run: list[Trade], *, close: bool = True) -> Bar:
    ps = [x.p for x in run]
    v = sum(x.q for x in run) / 1000
    d = sum(x.q if x.buy else -x.q for x in run) / 1000
    return Bar(gen, idx, run[0].t, ps[0] * TICK, max(ps) * TICK, min(ps) * TICK, ps[-1] * TICK, v, d, len(run),
               run[-1].t if close else None, close)


def _closes(mode: str, acc: dict[str, int]) -> bool:
    """Does the open bar close at this print? acc: running n, q (thousandths), d (signed thousandths), hi, lo, last,
    base (renko's last brick close), all in ticks (D03 §2 rules at the PARAMS sizes)."""
    if mode == "tick":
        return acc["n"] >= PARAMS["tick"]
    if mode == "volume":
        return acc["q"] >= PARAMS["volume"] * 1000
    if mode == "range":
        return acc["hi"] - acc["lo"] >= PARAMS["range"]
    if mode == "delta":
        return abs(acc["d"]) >= PARAMS["delta"] * 1000
    if mode == "renko":
        return abs(acc["last"] - acc["base"]) >= PARAMS["renko"]
    raise ValueError(mode)


def _number(bars: list[Bar]) -> None:
    """bar k of n: bars of one generation sharing one open time, in served order (§2.2)."""
    i = 0
    while i < len(bars):
        j = i
        while j + 1 < len(bars) and bars[j + 1].gen == bars[i].gen and bars[j + 1].t == bars[i].t:
            j += 1
        for m in range(i, j + 1):
            bars[m].k, bars[m].n = m - i + 1, j - i + 1
        i = j + 1


def series(mode: str, *, hole: bool = False) -> list[Bar]:
    """The loaded series of a mode, served order (t, generation, index); deterministic. time: 1m bars of the two
    generations plus the kline rows (kline=True, delta and trades None). Non-time: built per generation; the open bar at
    generation 1's end is dropped (recording stopped), generation 2's last bar is forming (confirm False)."""
    key = mode + (":hole" if hole else "")
    if key in _CACHE:
        return _CACHE[key]
    tr = dict(trades())
    if mode != "time":  # generation 3: the builder cold-starts at SEAM_AT (the bar open then is lost, §7.1 seam)
        g2 = tr[2]
        cut = next(i for i, x in enumerate(g2) if x.t >= SEAM_AT)
        tr = {1: tr[1], 2: g2[:cut], 3: g2[cut:]}
    out: list[Bar] = []
    if mode == "time":
        out = _klines(utc_ms("2026-10-19 16:00:00"), GEN1[0], P0_TICKS - 40, 0)
        for g in (1, 2):
            mins: dict[int, list[Trade]] = {}
            for x in tr[g]:
                mins.setdefault(x.t // 60000 * 60000, []).append(x)
            for i, (m, run) in enumerate(sorted(mins.items())):
                b = _bar(g, i, run)
                b.t, b.close_t = m, None
                out.append(b)
            if g == 1 and not hole:  # hole=True: no kline coverage 17:02-09:14 (the W-4 row's case)
                out += _klines(GEN1[1], GEN2[0], tr[1][-1].p, 1)
        out[-1].confirm = False
    else:
        for g in sorted(tr):
            run: list[Trade] = []
            ref = {"base": tr[g][0].p}
            idx = 0
            acc: dict[str, int] = {}
            for x in tr[g]:
                if not run:
                    acc = {"n": 0, "q": 0, "d": 0, "hi": x.p, "lo": x.p, "last": x.p, "base": ref["base"]}
                run.append(x)
                acc["n"] += 1
                acc["q"] += x.q
                acc["d"] += x.q if x.buy else -x.q
                acc["hi"], acc["lo"], acc["last"] = max(acc["hi"], x.p), min(acc["lo"], x.p), x.p
                if _closes(mode, acc):
                    b = _bar(g, idx, run)
                    if mode == "renko":  # a brick: open at the last brick close, close one brick away
                        up = run[-1].p > ref["base"]
                        b.o = ref["base"] * TICK
                        ref["base"] += PARAMS["renko"] if up else -PARAMS["renko"]
                        b.c = ref["base"] * TICK
                    out.append(b)
                    idx += 1
                    run = []
            if g == max(tr) and run:
                out.append(_bar(g, idx, run, close=False))
    _number(out)
    _CACHE[key] = out
    return out


def tag(b: Bar, *words: str) -> Bar:
    """A copy of b carrying extra §6 words (stale, corrected, width capped, Est., POC): the row-state specimens."""
    bad = set(words) - {"stale", "corrected", "width capped", "Est.", "POC"}
    if bad:
        raise ValueError(f"tag(): {sorted(bad)} are derived, not tagged (forming: confirm; no range: o=h=l=c)")
    return replace(b, words=set(b.words) | set(words))


def at(mode: str, hhmm_s: str, *, day: str = "2026-10-20", hole: bool = False) -> int:
    """Index of the first row of series(mode) opening at or after day hh:mm[:ss[.mmm]] UTC."""
    t = utc_ms(f"{day} {hhmm_s}" + (":00" if hhmm_s.count(":") == 1 else ""))
    return next(i for i, b in enumerate(series(mode, hole=hole)) if b.t >= t)


def _klines(a: int, b: int, p: int, gen: int) -> list[Bar]:
    """1m exchange-kline rows from a to b (kline=True: no delta, no trades), a seeded walk from p ticks."""
    rng = random.Random(SEED + a // 60000)
    out = []
    for i, m in enumerate(range(a, b, 60000)):
        o = p
        path = [o + rng.randint(-12, 12) for _ in range(4)]
        p = path[-1]
        out.append(Bar(gen, i, m, o * TICK, max(path + [o]) * TICK, min(path + [o]) * TICK, p * TICK,
                       round(rng.uniform(8, 40), 3), None, None, kline=True))
    return out


# --- formatting (D04E11 §5.4: tick precision, qty_step, signs as text with U+2212)
MINUS = "−"


def f_price(x: float) -> str:
    return f"{x:,.1f}"


def f_qty(x: float) -> str:
    return f"{x:,.3f}"


def f_signed(x: float | None, fmt: str = "{:,.3f}") -> str:
    if x is None:
        return "—"
    if round(x, 6) == 0:
        return fmt.format(0.0)
    return ("+" if x > 0 else MINUS) + fmt.format(abs(x))


def _dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def hhmm(ms: int) -> str:
    return _dt(ms).strftime("%H:%M")


def hms_ms(ms: int) -> str:
    """hh:mm:ss.mmm (the non-time row header and `close time`)."""
    return _dt(ms).strftime("%H:%M:%S.") + f"{ms % 1000:03d}"


def date_of(ms: int) -> str:
    return _dt(ms).strftime("%Y-%m-%d")


def f_duration(ms: int) -> str:
    """close − open as m:ss.s, h:mm:ss from an hour (§3.1 `duration`)."""
    s = ms / 1000
    if s >= 3600:
        return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{int(s % 60):02d}"
    return f"{int(s // 60)}:{s % 60:04.1f}"


def row_header(b: Bar, mode: str) -> str:
    """§2: time bars hh:mm (D04E11:179); non-time "10:22:11.412 bar 3 of 5" (§2.2)."""
    return hhmm(b.t) if mode == "time" else f"{hms_ms(b.t)} bar {b.k} of {b.n}"


def row_name(b: Bar, mode: str) -> str:
    """The row header's accessible name (§2.2; time bars D04E11:179) — drawn in annotations only."""
    if mode == "time":
        return f"{date_of(b.t)} {hhmm(b.t)}:00 UTC"
    head = f"bar {b.k} of {b.n}, opened {date_of(b.t)} {hms_ms(b.t)} UTC"
    if not b.confirm:
        return head + ", forming, not closed yet"
    if b.close_t is None:
        return head + ", " + copy("W-20")
    return head + f", closed {hms_ms(b.close_t)} UTC after {f_duration(b.close_t - b.t)}"


def cell(name: str, b: Bar, mode: str, *, base: float | None = None, cvd: float | None = None) -> str:
    """One cell's text for column name (§3.1 field / derived / "—"; R-6 never a silent blank)."""
    if name == "time":
        return row_header(b, mode)
    if name in ("open", "high", "low", "close"):
        return f_price(getattr(b, name[0]))
    if name == "volume":
        return f_qty(b.v)
    if name == "delta":
        return f_signed(b.delta)
    if name == "trades":
        return "—" if b.trades is None else f"{b.trades:,}"
    if name in ("buy", "sell"):
        if b.delta is None:
            return "—"
        return f_qty((b.v + b.delta) / 2 if name == "buy" else (b.v - b.delta) / 2)
    if name == "range":
        return f"{round((b.h - b.l) / TICK):,}"
    if name == "brick":
        return "up" if b.c > b.o else "down"
    if name == "state":
        return b.state
    if name == "close time":
        return "—" if (not b.confirm or b.close_t is None) else hms_ms(b.close_t)
    if name == "duration":
        return "—" if (not b.confirm or b.close_t is None) else f_duration(b.close_t - b.t)
    if name == "CVD":
        return f_signed(cvd)
    if name == "change":
        return f_signed(b.c - b.o, "{:,.1f}")
    if name == "vs base":
        if base is None:
            raise ValueError("vs base needs base=")
        return f_signed(b.c - base, "{:,.1f}")
    raise KeyError(name)


def cvd_of(rows: list[Bar], upto: Bar) -> float | None:
    """CVD at upto's close: the running sum of delta over its generation (None when a delta in the run is absent)."""
    tot = 0.0
    for b in rows:
        if b.gen != upto.gen:
            continue
        if b.delta is None:
            return None
        tot += b.delta
        if b is upto:
            return tot
    return None


# --- the window (1280 x 800) and the chart panel (E12-D04's chrome geometry; E11-D04 §2's panel rows)
TOPBAR_H, STATUSBAR_H, NAVRAIL_W, STRIP_W, RAIL_OPEN_W, TABSTRIP_H = 80, 48, 64, 48, 240, 32
ROW_H = 24  # size.row.compact: every row, separator rows included (§5 "Fixed rows")
PANEL_ROWS = 2 * ROW_H  # CMP-221 toolbar + status row (size.control.compact each)
FIXED_COLS = 24 + 24  # expander + actions (D04E11 §5.1)
WORDMARK = "CandleViewer"  # E10-D03 §2.1 (as the E12-D04 kit draws it)


def control(name: str, chars: str, *, caret: bool = False, pressed: bool = False, fill: str = RAISED) -> Node:
    """A compact 24 px control: label (type.ui.label) + optional chevron-down; pressed = selected fill + check glyph."""
    kids = [icon("check", "check", TEXT_1, ICON_SM) if pressed else None, text("label", chars, LABEL, TEXT_1),
            icon("caret", "chevron-down", TEXT_2, ICON_SM) if caret else None]
    return hbox(name, kids, {"fill": SELECTED if pressed else fill, "stroke": BORDER, "strokeWidth": HAIR,
                             "radius": R_CONTROL, "padX": INSET_SM, "gap": INSET_XS}, h=ROW_H)


def badge(name: str, chars: str, color: str = ENV_DEMO, *, glyph: str | None = None, gcolor: str = TEXT_2) -> Node:
    """A 20 px chip (status row): optional glyph + caption text, pill radius, hairline in color."""
    return hbox(name, [icon("glyph", glyph, gcolor, ICON_SM) if glyph else None, text("label", chars, CAPTION, TEXT_1)],
                {"stroke": color, "strokeWidth": HAIR, "radius": R_BADGE, "padX": INSET_SM, "gap": INSET_XS}, h=20)


def toolbar(mode: str, *, chart: str = "Candle", w: int) -> Node:
    """CMP-221 (D04E11 §2): symbol, the mode's trigger (D09 short label), the chart type, the `Chart │ Table` switch with
    Table pressed (D1), FP, Ind, Draw, the more button."""
    sw = hbox("CMP-003 SegmentedControl (composition) · Chart │ Table",
              [control("segment · Chart", "Chart"), control("segment · Table", "Table", pressed=True)], None,
              h=ROW_H, note="Alt+T toggles (D04E11 D1); manual activation; Table pressed")
    kids = [control("symbol", "BTCUSDT", caret=True), control("bar mode", SHORT[mode], caret=True),
            control("chart type", chart, caret=True), sw, control("FP", "FP"), control("Ind", "Ind"),
            control("Draw", "Draw"),
            hbox("more", [icon("glyph", "more-horizontal", TEXT_2)], {"justify": "center"}, w=24, h=24)]
    return hbox("CMP-221 toolbar (composition)", kids, {"padX": INSET_SM, "gap": INSET_SM}, w=w, h=ROW_H)


def status_row(*, w: int, chips: Iterable[Node] = (), env: str = "DEMO") -> Node:
    """The kept status row (E11-D02 D16): the env badge, then the given chips (feed, aggregation)."""
    return hbox("status row", [badge("CMP-075 env badge (composition)", env, ENV_DEMO if env == "DEMO" else ENV_LIVE),
                               *chips], {"padX": INSET_SM, "gap": INSET_SM}, w=w, h=ROW_H)


def stale_chip(age: str = "7s") -> Node:
    """E11-D02 LD-1 `Stale 7s · last 13:42:05` (D04E11:59)."""
    return badge("feed chip · stale", f"Stale {age} · last {LAST_GOOD}", WARN_STRONG, glyph="warning", gcolor=WARN_STRONG)


def window(fid: str, panel_node: Node | list[Node], *, rail: str = "strip", w: int = FRAME_W,
           h: int = FRAME_H) -> Node:
    """A frame: the 1280 x 800 window (TopBar, NavRail, the tab strip and the dock holding one chart panel, the
    RightRail as a 48 px strip or 240 px open, the StatusBar) named frame_name(fid). panel_node comes from panel()
    with w = dock_w(rail). The chrome is context (E10-D02 / E10-D03 own it): no copy beyond the wordmark and the env
    badge."""
    bw = w - NAVRAIL_W - (STRIP_W if rail == "strip" else RAIL_OPEN_W)
    bh = h - TOPBAR_H - STATUSBAR_H
    top = hbox("CMP-206 TopBar (composition)", [text("wordmark", WORDMARK, HEADING_SM, TEXT_1),
                                                badge("CMP-074 env badge (composition)", "DEMO")],
               {"fill": RAISED, "padX": INSET_LG, "gap": INSET_MD}, w=w, h=TOPBAR_H)
    nav = vbox("CMP-207 NavRail (composition)", [rect(f"nav item {i}", 24, 24, HOVER, {"radius": R_CONTROL})
                                                 for i in range(1, 6)],
               {"fill": RAISED, "align": "center", "padY": INSET_MD, "gap": INSET_MD}, w=NAVRAIL_W, h=bh)
    tabs = hbox("tab strip", [hbox("tab · active", [rect("tab mark", 40, 8, HOVER, {"radius": R_CONTROL})],
                                   {"fill": CANVAS, "padX": INSET_SM}, h=TABSTRIP_H)],
                {"fill": APP, "padX": INSET_SM}, w=bw, h=TABSTRIP_H)
    panels = panel_node if isinstance(panel_node, list) else [panel_node]
    if any(p.get("w") != bw for p in panels):
        raise ValueError(f"panel w {[p.get('w') for p in panels]} != dock w {bw} (rail={rail})")
    dock: list[Node] = []
    for i, p in enumerate(panels):  # several panels: stacked, CMP-081's 4 px gutter (color.surface.app) between
        dock += [rect(f"CMP-081 gutter {i}", bw, GUTTER_PX, APP)] if i else []
        dock.append(p)
    if sum(p["h"] for p in panels) + GUTTER_PX * (len(panels) - 1) != bh - TABSTRIP_H:
        raise ValueError(f"panel heights {[p['h'] for p in panels]} do not fill the dock ({bh - TABSTRIP_H}): use "
                         f"split_h({len(panels)})")
    canvas = vbox("canvas", [tabs, *dock], {"fill": APP}, w=bw, h=bh)
    rrail = vbox("CMP-209 RightRail (composition)", [], {"fill": RAISED}, w=STRIP_W if rail == "strip" else RAIL_OPEN_W,
                 h=bh)
    body = hbox("body", [nav, canvas, rrail], {"align": "start"}, w=w, h=bh)
    sbar = hbox("CMP-208 StatusBar (composition)", [], {"fill": SUNKEN}, w=w, h=STATUSBAR_H)
    return vbox(frame_name(fid), [top, body, sbar], {"fill": APP, "clip": True}, w=w, h=h)


ZOOM_W, ZOOM_H = 640, 400  # the 1280 x 800 window at 200 % text zoom, in CSS px (§5's 640 CSS px panel)


def window_maximised(fid: str, panel_node: Node, *, w: int = ZOOM_W, h: int = ZOOM_H) -> Node:
    """Board 08's frame: the 1280 x 800 window at 200 % = 640 x 400 CSS px, drawn in CSS px, the chart panel
    maximised (F11) so it takes the whole window (D04E11 §5.2: "the 640 CSS px of panel width a maximised panel
    has"). Export the board at 2x so the frame's PNG is 1280 x 800 device px (a live check)."""
    if panel_node.get("w") != w or panel_node.get("h") != h:
        raise ValueError(f"maximised panel must be {w} x {h}")
    live(f"frame {frame_name(fid)!r} is drawn in CSS px ({w} x {h}): export the board at scale 2 and read back a "
         f"{2 * w} x {2 * h} frame in the PNG")
    deviate("board 08's frame is 640 x 400 CSS px (the 1280 x 800 window at 200 %), exported at 2x; no token scales "
            "type by 2, so the CSS-px drawing at 2x export is the only token-bound way to show 200 %")
    return vbox(frame_name(fid), [panel_node], {"fill": APP, "clip": True}, w=w, h=h)


def dock_w(rail: str = "strip", w: int = FRAME_W) -> int:
    return w - NAVRAIL_W - (STRIP_W if rail == "strip" else RAIL_OPEN_W)


DOCK_H = FRAME_H - TOPBAR_H - STATUSBAR_H - TABSTRIP_H  # 640
GUTTER_PX = 4  # CMP-081 gutter (E12-D04's h.gutter)


def split_h(n: int, h: int = DOCK_H) -> list[int]:
    """Panel heights for n panels stacked in the dock with 4 px gutters (the last takes the remainder)."""
    each = (h - GUTTER_PX * (n - 1)) // n
    return [each] * (n - 1) + [h - GUTTER_PX * (n - 1) - each * (n - 1)]


def panel(mode: str, table_node: Node, *, w: int, h: int = DOCK_H, chart: str = "Candle",
          chips: Iterable[Node] = (), name: str = "CMP-080 DockPanel (composition) · chart") -> Node:
    """The chart panel with the table open in place (D04E11 D2): toolbar, status row, then table_node (from table())
    in place of the pane stack, which is hidden off-layout."""
    return vbox(name, [toolbar(mode, chart=chart, w=w), status_row(w=w, chips=chips), table_node],
                {"fill": CANVAS, "stroke": BORDER, "strokeWidth": HAIR, "radius": R_CARD, "clip": True}, w=w, h=h)


def table_room(h: int = DOCK_H) -> int:
    """The height left for the table under the panel's toolbar and status row."""
    return h - PANEL_ROWS


# --- the SCR-045 table (E11-D04 §2 / §5 shell; E12-D07 §2-§7 content)
NUMERIC = {"open", "high", "low", "close", "volume", "delta", "trades", "buy", "sell", "range", "close time", "duration",
           "CVD", "change", "vs base"}
SIGNED = {"delta", "CVD", "change", "vs base"}


def caption_text(rows: list[Bar], mode: str, *, loaded: int, extra: Iterable[str] = (), durations: bool = False,
                 feed_stale: bool = False, aggregation: str | None = None, rebuild: str | None = None) -> str:
    """The <caption>: E11-D04's summariseRange() form (D04E11 §6.2) from rows, then §7.4's clauses in order: W-10
    (non-time), the closing rule W-11..W-15, "durations as h:mm:ss", the aggregation clause, the rebuild or
    cache-loading clause (rebuild = "W-8" | "W-9"), the feed clause "values as of 13:42:05"."""
    closed = [b for b in rows if b.v is not None]
    a, z = closed[0], closed[-1]
    label = "1 m" if mode == "time" else SHORT[mode]
    pct = (z.c - a.o) / a.o * 100
    deltas = [b.delta for b in closed]
    parts = [f"BTCUSDT {label} — {len(rows)} bars visible on the chart ({date_of(a.t)} {hhmm(a.t)}–{hhmm(z.t)} UTC) "
             f"of {loaded:,} loaded", f"open {f_price(a.o)}", f"close {f_price(z.c)} ({f_signed(pct, '{:.2f}')} %)",
             f"high {f_price(max(b.h for b in closed))}", f"low {f_price(min(b.l for b in closed))}",
             f"volume {f_qty(sum(b.v for b in closed))}",
             "delta " + (f_signed(sum(d for d in deltas if d is not None)) if any(d is not None for d in deltas) else "—"),
             "prices in USDT, volume in BTC"]
    if mode != "time":
        parts.append(copy("W-10"))
        parts.append(copy({"tick": "W-11", "volume": "W-12", "range": "W-13", "delta": "W-14", "renko": "W-15"}[mode]))
    if durations:
        parts.append("durations as h:mm:ss")
    if aggregation:
        parts.append(aggregation)
    if rebuild:
        parts.append(copy(rebuild))
    parts += list(extra)
    if feed_stale:
        parts.append(f"values as of {LAST_GOOD}")
    return " · ".join(parts)


def caption(chars: str, w: int) -> Node:
    return text("caption", chars, CAPTION, TEXT_2, w=w, note="<caption>: summariseRange() + §7.4 clauses; not a live region")


def chip_row(w: int, *, sort: str | None = None, desc: bool = True, separators_hidden: bool = False,
             extra: Iterable[Node] = ()) -> Node | None:
    """The filter/sort line (D04E11 D8): the sort-status chip "Sorted by delta ↓ — not in time order" + Reset, and
    W-17 "separators hidden while sorted" when separator rows exist under a value sort (§7.2)."""
    kids: list[Node | None] = list(extra)
    if sort:
        chip = f"Sorted by {sort} {'↓' if desc else '↑'} — not in time order"
        if separators_hidden:
            chip += " · " + copy("W-17")
        kids.append(hbox("sort chip", [text("label", chip, CAPTION, TEXT_1), control("Reset", "Reset")],
                         {"fill": RAISED, "radius": R_BADGE, "padX": INSET_SM, "gap": INSET_SM}, h=ROW_H))
    if not any(kids):
        return None
    return hbox("filter and sort line", kids, {"gap": INSET_SM}, w=w, h=ROW_H)


STALE_TAIL = " — press Shift+R or Refresh to current"  # D04E11 §7 "Copy (verbatim)", after the bar


def stale_banner_text(b: Bar | None = None, mode: str = "time") -> str:
    """The stale banner's words: on a non-time series W-22 (the row header in place of E11-D04's time) + E11-D04's
    tail; on time bars E11-D04's own "Data is for bar hh:mm, no longer in view" + the tail."""
    if mode != "time":
        return copy("W-22") + STALE_TAIL
    if b is None:
        raise ValueError("time mode: pass the focused bar")
    return f"Data is for bar {hhmm(b.t)}, no longer in view" + STALE_TAIL


def stale_banner(chars: str, w: int) -> Node:
    """CMP-028 warning banner (D04E11 §7): warning.subtle fill, warning.strong glyph, primary text, the Shift+R Kbd
    and the Refresh to current button; 32 px."""
    kids = [icon("glyph", "warning", WARN_STRONG), text("text", chars, CAPTION, TEXT_1),
            hbox("CMP-022 Kbd (composition) · Shift+R", [text("label", "Shift+R", NUM, TEXT_1)],
                 {"stroke": BORDER, "strokeWidth": HAIR, "radius": R_CONTROL, "padX": INSET_XS}, h=20),
            control("Refresh to current", "Refresh to current")]
    return hbox("CMP-028 Banner (composition) · stale", kids, {"fill": WARN_SUBTLE, "padX": INSET_SM, "gap": INSET_SM},
                w=w, h=32)


def _cell_node(name: str, chars: str, w: int, color: str, typo: str = NUM, *, numeric: bool, inner: str = "value",
               note: str | None = None) -> Node:
    """One cell, w = col_px (§5: the text's characters x 6.6 plus 8 px of padding a side, inside the column): an hbox
    padded INSET_SM a side holding the auto-width text, justified to the end for a numeric column, to the start
    otherwise (a fixed text width would wrap on the 0.2 px col_px rounds away)."""
    return hbox(name, [text(inner, chars, typo, color)],
                {"padX": INSET_SM, "justify": "end" if numeric else "start"}, w=w, h=ROW_H, note=note)


def header_row(cols: list[str], mode: str, *, sort: str | None = None, desc: bool = True, equi: bool = False) -> Node:
    """<th scope="col"> words (D04E11 §5.1), lower case; the sorted column carries its arrow glyph."""
    kids: list[Node] = [box("expander", [], None, w=24, h=ROW_H)]
    for c in cols:
        wpx = col_px(c, mode, equi=equi)
        if c == sort:
            kids.append(hbox(f"th · {c}", [text("label", c, CAPTION, TEXT_1),
                                           icon("sort", "arrow-down" if desc else "arrow-up", TEXT_1, ICON_SM)],
                             {"padX": INSET_SM, "justify": "end" if c in NUMERIC else "start", "gap": INSET_XS},
                             w=wpx, h=ROW_H, note=f"aria-sort={'descending' if desc else 'ascending'}"))
        else:
            kids.append(_cell_node(f"th · {c}", c, wpx, TEXT_2, CAPTION, numeric=c in NUMERIC, inner="label"))
    kids.append(box("actions", [], None, w=24, h=ROW_H))
    return hbox("header row", kids, {"fill": CANVAS}, w=row_width(cols, mode, equi=equi), h=ROW_H)


def row_width(cols: list[str], mode: str, *, equi: bool = False) -> int:
    return FIXED_COLS + sum(col_px(c, mode, equi=equi) for c in cols)


def bar_row(b: Bar, cols: list[str], mode: str, i: int, *, focused: bool = False, selected: bool = False,
            stale: bool = False, base: float | None = None, cvd: float | None = None, equi: bool = False,
            expander: bool | None = None) -> Node:
    """One bar row: zebra (odd canvas, even raised; §14), the expander (chevron; "—" without footprint, kline rows),
    the cells, the actions button. forming / stale rows: values in color.text.secondary, the `state` word primary
    (D04E11 §6.2; §14). Delta-signed cells: buy / sell colour with the sign as text. focused: 2 px focus ring
    (aria-current); selected: color.surface.selected + check glyph (D04E11:296)."""
    dim = (not b.confirm) or stale or ("stale" in b.words)
    exp = (not b.kline) if expander is None else expander
    ek = [icon("check", "check", TEXT_1, ICON_SM) if selected else None,
          icon("chevron", "chevron-right", TEXT_2, ICON_SM) if exp else text("none", "—", NUM, TEXT_3)]
    kids: list[Node] = [hbox("expander", ek, {"justify": "center"}, w=24, h=ROW_H)]
    for c in cols:
        v = cell(c, b, mode, base=base, cvd=cvd)
        color = TEXT_2 if dim and c != "state" else TEXT_1
        if c in SIGNED and not dim and v not in ("—",) and v[0] in "+" + MINUS:
            color = BUY_TEXT if v[0] == "+" else SELL_TEXT
            fallback("buy-sell")
        if c == "time":
            kids.append(_cell_node("th · row", v, col_px(c, mode), TEXT_1 if not dim else TEXT_2, numeric=False,
                                   note=row_name(b, mode)))
        else:
            kids.append(_cell_node(c, v, col_px(c, mode, equi=equi), color, numeric=c in NUMERIC))
    kids.append(hbox("actions", [icon("glyph", "more-horizontal", TEXT_2, ICON_SM)], {"justify": "center"}, w=24, h=ROW_H))
    o: dict[str, Any] = {"fill": SELECTED if selected else (CANVAS if i % 2 else RAISED)}
    if focused:
        o.update({"stroke": RING, "strokeWidth": FOCUS_W, "strokeAlign": "inner"})
    nm = f"row {i:02d} · gen {b.gen} idx {b.index}" + (" · focused" if focused else "") + (" · selected" if selected else "")
    return hbox(nm, kids, o, w=row_width(cols, mode, equi=equi), h=ROW_H)


def sep_text(kind: str, *, ts: str | None = None, seam_too: bool = False) -> str:
    """A separator row's text (§7.1): its W-n verbatim (W-5 / W-6 take ts=), or E11-D04's band; seam_too appends the
    seam's text after "·" on a gap row ("A seam and a gap at one place show the gap row only")."""
    key, _act = SEPARATORS[kind]
    s = copy(key, **({"ts": ts} if ts else {})) if key.startswith("W-") else E11_BANDS[kind]
    if not key.startswith("W-"):
        NOTES.add("copy_keys", f"{kind}: E11-D04's band ({key}), unchanged")
    if seam_too:
        if kind not in ("gap-non-time", "gap-time", "kline-hole"):
            raise ValueError("seam_too only on a gap row")
        s += " · " + copy("W-1")
    return s


def sep_row(kind: str, cols: list[str], mode: str, *, ts: str | None = None, seam_too: bool = False,
            focused: bool = False, equi: bool = False, action_disabled: str | None = None) -> Node:
    """A separator row in the band-row form (§7.2): one 24 px row spanning every column, color.text.secondary on
    color.surface.hover, text from the row header's left edge, at most one action button at its end (CMP-053
    **Older** for lookback as "Load more"). A grid row: focusable (focused draws the ring), never selected."""
    _key, act = SEPARATORS[kind]
    chars = sep_text(kind, ts=ts, seam_too=seam_too)
    if kind == "lookback":  # W-7 carries "· Load more" as its action: the text keeps the part before it
        chars = chars.split(" · Load more")[0]
    left = hbox("band text", [box("expander slot", [], None, w=24, h=ROW_H), text("text", chars, CAPTION, TEXT_2)],
                None, h=ROW_H)
    kids: list[Node] = [left]
    if act:
        btn = control(f"action · {act}", act)
        if action_disabled:
            btn = hbox(f"action · {act} (disabled)", [icon("lock", "locked", TEXT_3, ICON_SM),
                                                     text("label", act, LABEL, TEXT_3)],
                       {"fill": RAISED, "stroke": BORDER, "strokeWidth": HAIR, "radius": R_CONTROL, "padX": INSET_SM,
                        "gap": INSET_XS}, h=ROW_H, note=f"disabled: {action_disabled}")
        kids.append(btn)
    o: dict[str, Any] = {"fill": HOVER, "justify": "space-between", "padR": INSET_SM if act else None}
    o = {k: v for k, v in o.items() if v is not None}
    if focused:
        o.update({"stroke": RING, "strokeWidth": FOCUS_W, "strokeAlign": "inner"})
    return hbox(f"separator · {kind}" + (" · focused" if focused else ""), kids, o,
                w=row_width(cols, mode, equi=equi), h=ROW_H, note=f"accessible name: {chars}")


def footer_row(w: int, *, older: bool = False, new_bars: int = 0) -> Node:
    """The footer (D04E11 §2): [Older] when a page is loading, the "N new bars ↓" pill, and CMP-099 Export CSV shown
    disabled with its reason "Export arrives with E15" (D04E11:299)."""
    kids: list[Node | None] = [control("CMP-053 Older", "Older") if older else None,
                               text("pill", f"{new_bars} new bars ↓", CAPTION, TEXT_1) if new_bars else None,
                               hbox("CMP-099 Export CSV (disabled)", [icon("lock", "locked", TEXT_3, ICON_SM),
                                                                      text("label", "Export CSV", LABEL, TEXT_3)],
                                    {"fill": RAISED, "stroke": BORDER, "strokeWidth": HAIR, "radius": R_CONTROL,
                                     "padX": INSET_SM, "gap": INSET_XS}, h=ROW_H),
                               text("reason", "Export arrives with E15", CAPTION, TEXT_2)]
    return hbox("footer", kids, {"gap": INSET_SM}, w=w, h=ROW_H)


def table(rows: list[Node], *, w: int, h: int, caption_chars: str, header: Node | None, chips: Node | None = None,
          banner: Node | None = None, footer: Node | None = None, hint: str | None = None) -> Node:
    """SCR-045 inside the panel: caption, the filter/sort line, the stale banner, the header row, the body rows (bar
    and separator rows, in order), the footer; space.inset.sm insets (D04E11 §2). Raises when the body overflows h
    (the frame must show whole rows: pass fewer rows)."""
    inner = w - 2 * PX[INSET_SM]
    cap = caption(caption_chars, inner)
    bw = header["w"] if header else inner  # header None: the stacked reflow (its blocks span the inner width)
    body = vbox("rows", rows, None, w=bw, h=round(sum(est_height(r) for r in rows))) if rows else None
    rule = rect("header rule", bw, 1, BORDER) if header else None
    kids = [cap, chips, banner, text("hint", hint, CAPTION, TEXT_2, w=inner) if hint else None, header, rule, body,
            footer]
    t = vbox("SCR-045 table", kids, {"padX": INSET_SM, "padY": INSET_SM, "gap": STACK_XS}, w=w, h=h)
    need = est_height(dict(t, h=None))
    if need > h:
        raise ValueError(f"table needs about {need:.0f} px > {h}: show fewer rows ({len(rows)} now)")
    return t


def max_rows(*, h: int, caption_lines: int = 2, chips: bool = False, banner: bool = False, footer: bool = True) -> int:
    """How many 24 px body rows fit a table of height h with the given lines above and below."""
    used = 2 * PX[INSET_SM] + text_h(CAPTION, caption_lines) + ROW_H + 1 + (ROW_H if chips else 0) + \
        (32 if banner else 0) + (ROW_H if footer else 0)
    parts = 4 + chips + banner + footer
    return int((h - used - parts * PX[STACK_XS]) // ROW_H)


def caption_lines(chars: str, w: int) -> int:
    return text_lines(chars, CAPTION, w - 2 * PX[INSET_SM])


def stacked_block(b: Bar, mode: str, i: int, *, w: int, focused: bool = False) -> Node:
    """E11-D04's stacked reflow (D04E11 §5.2 step 3) for a non-time row at 200 % (§5): heading = the row header and
    the `state` word (+ expander and actions); open / high / low / close as a 2 x 2 labelled grid; volume, delta and
    the mode's closing quantity on one line; `close time` and `duration` on one line under OHLC. One <tr> per bar."""
    dim = not b.confirm

    def pair(lab: str, val: str) -> Node:
        return hbox(f"{lab}", [text("label", lab, CAPTION, TEXT_2), text("value", val, NUM, TEXT_2 if dim else TEXT_1)],
                    {"gap": INSET_XS}, h=16)

    head = hbox("heading", [icon("chevron", "chevron-right", TEXT_2, ICON_SM),
                            node("text", "th · row", chars=row_header(b, mode), typo=NUM, color=TEXT_1,
                                 note=row_name(b, mode)),
                            text("state", b.state, NUM, TEXT_1),
                            icon("actions", "more-horizontal", TEXT_2, ICON_SM)], {"gap": INSET_SM}, h=20)
    q = {"tick": "trades", "range": "range", "renko": "brick", "delta": "delta", "volume": "volume"}[mode]
    lines = [head,
             hbox("ohlc 1", [pair("open", cell("open", b, mode)), pair("high", cell("high", b, mode))], {"gap": INSET_LG}, h=16),
             hbox("ohlc 2", [pair("low", cell("low", b, mode)), pair("close", cell("close", b, mode))], {"gap": INSET_LG}, h=16),
             hbox("times", [pair("close time", cell("close time", b, mode)), pair("duration", cell("duration", b, mode))],
                  {"gap": INSET_LG}, h=16),
             hbox("quantities", [pair(c, cell(c, b, mode)) for c in dict.fromkeys(("volume", "delta", q))],
                  {"gap": INSET_LG}, h=16)]
    o: dict[str, Any] = {"fill": CANVAS if i % 2 else RAISED, "padX": INSET_SM, "padY": INSET_XS, "gap": STACK_XS}
    if focused:
        o.update({"stroke": RING, "strokeWidth": FOCUS_W, "strokeAlign": "inner"})
    return vbox(f"block {i:02d} · gen {b.gen} idx {b.index}", lines, o, w=w)


def candles(bars: list[Bar], *, w: int, h: int, name: str = "pane stack · candles", cursor: int | None = None) -> Node:
    """A small candle pane (E12-D04's drawSeries: 1 px wick in color.candle.wick, body ~0.7 of the slot, up / down
    tokens) from bars, scaled to w x h; cursor = an index whose slot gets a 1 px color.focus.ring crosshair line.
    Absolute children in a non-flex board (no flex parent: x/y need no abs)."""
    lo, hi = min(b.l for b in bars), max(b.h for b in bars)
    m = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - m, hi + m
    slot = w / len(bars)
    bw = max(1, min(35, round(0.7 * slot)))
    if bw >= 4 and bw % 2 == 0:
        bw -= 1

    def y(p: float) -> int:
        return round((hi - p) / (hi - lo) * (h - 1))

    kids: list[Node] = []
    for i, b in enumerate(bars):
        x0 = round(i * slot)
        cx = x0 + round((slot - 1) / 2)
        kids.append(rect(f"wick {i:03d}", 1, max(1, y(b.l) - y(b.h)), WICK, x=cx, y=y(b.h)))
        top, bot = min(y(b.o), y(b.c)), max(y(b.o), y(b.c))
        kids.append(rect(f"body {i:03d}", bw, max(1, bot - top), UP if b.c >= b.o else DOWN,
                         x=x0 + round((slot - bw) / 2), y=top))
    if cursor is not None:
        kids.append(rect("crosshair", 1, h, RING, x=round(cursor * slot + slot / 2), y=0))
    return box(name, kids, {"fill": CANVAS, "clip": True}, w=w, h=h)


# --- the annotation column, the board, sections, the sheet, the md and the pack
def columns_line(cols: list[str], mode: str) -> str:
    """The columns shown, each marked [field <REST> / <WS>] or [derived] (§3.1, §4); "—" cells are named per row."""
    out = []
    for c in cols:
        col = column(c)
        kind = COLUMNS[c].tiers[mode] if c in COLUMNS else "A"  # §4's chart-type cells are auto
        k = "field" if c in COLUMNS and "field" in col.kind and "derived" not in col.kind else "derived"
        src = f"{col.rest} / {col.ws}" if k == "field" else (col.note.split(";")[0] if c not in COLUMNS else
                                                              f"from {col.rest}")
        out.append(f"{c} [{kind} {k}: {src}]")
    return " · ".join(out)


def frame_block(fid: str, *, state: str, mode: str, cols: list[str], row_header_form: str, keyboard: str,
                announcement: str, copy_keys: Iterable[str] = (), chart: str = "candle", tokens: Iterable[str] = (),
                extra: Iterable[str] = ()) -> tuple[str, list[str]]:
    """One frame's annotation block: frame name, state id, mode / chart type, columns with marks, row header form,
    keyboard path and focus, announcement, copy keys W-n, tokens (pass the frame's: frame_tokens(frame))."""
    lines = [f"Frame: {frame_name(fid)}", f"State: {state}", f"Mode: {mode} ({SHORT[mode]}) · chart type: {chart}",
             f"Columns: {columns_line(cols, mode)}", f"Row header: {row_header_form}", f"Keyboard and focus: {keyboard}",
             f"Announcement: {announcement}"]
    ks = list(copy_keys)
    if ks:
        lines.append("Copy: " + " · ".join(f"{k} “{COPY[k][0]}”" if k in COPY else k for k in ks))
    tk = sorted(set(tokens))
    if tk:
        lines.append("Tokens: " + ", ".join(tk))
    lines += list(extra)
    return (frame_name(fid), lines)


def frame_tokens(n: Node) -> list[str]:
    out: set[str] = set()
    for _p, x in walk(n):
        for k in ("typo", "color", "size"):
            if isinstance(x.get(k), str):
                out.add(x[k])
        for k, v in (x.get("o") or {}).items():
            if k in _TOKEN_OPTS and isinstance(v, str):
                out.add(v)
    return sorted(out)


# Live-check fold (2026-10-29, livecheck-report SHEET-FIX lines): the two strings drawn live on every board, and the
# measured root heights (annotation end + 80 after touchTexts + relayout; text_h over-estimates the column).
DATA_LINE = ("Data: seeded synthetic stream (seed 242), not recorded; only the instrument's tick size (0.1) and qty step "
             "(0.001) come from the recorded fixture.")
CVD_LINE = (f"CVD: not among the shown columns at 1280 (§3.1 L{L('| CVD               |')} tiers it E, extended: one "
            "click away in CMP-056).")
MEASURED_H = {1: 2574, 2: 2644, 3: 2587, 4: 2414, 5: 2676, 6: 2520, 7: 2148, 8: 1253, 9: 1609, 10: 1981}


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    """The ONE 400 px column outside the frames: title (the board name), a "Board" block (what §0 draws, theme, twin,
    export), one block per frame (frame_block()), footer "page <PAGE> · board NN · r1"."""
    b = BOARDS[nn]
    head = [f"§0 L{b.line}: {b.draws}", f"Theme: {b.theme}" + (f" (light twin of board {b.twin:02d})" if b.twin else ""),
            f"Export: {b.export}", *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_W - 32),
            text("data-line", DATA_LINE, CAPTION, TEXT_3, w=ANN_W - 32)]  # live-check P-6 (every board)
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_W - 32)] + [text(f"value-{j}", ln, BODY, TEXT_1, w=ANN_W - 32)
                                                                  for j, ln in enumerate(lines, 1) if ln.strip()]
        if i == 1:  # live-check P-1: the Board block's CVD line (every board)
            bk.append(text("value-cvd", CVD_LINE, BODY, TEXT_1, w=ANN_W - 32))
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_W - 32))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_W - 32))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


def layout(frames: list[Node], per_row: int | None = None) -> list[Node]:
    """Frames placed 1:1 in rows (<= MAX_PER_ROW; 4 frames: 2 x 2), MARGIN margin and gutters (positions)."""
    k = per_row or (2 if len(frames) == 4 else MAX_PER_ROW)
    out, y, i = [], MARGIN, 0
    while i < len(frames):
        row = frames[i:i + k]
        x = MARGIN
        for f in row:
            out.append(dict(f, x=x, y=y))
            x += f["w"] + MARGIN
        y += max(f["h"] for f in row) + MARGIN
        i += k
    return out


def board(nn: int, frames: list[Node], ann: Node, *, per_row: int | None = None,
          strict: bool = True) -> tuple[dict[str, Any], list[Node]]:
    """The sheet's board (name, grid x/y, a plain root: fill color.surface.app, clip) hugging its frames + the
    annotation column + MARGIN, and the placed nodes. Checks the frame names against §H and the pitch."""
    b = BOARDS[nn]
    want = {frame_name(f) for f in b.frames}
    got = [f["name"] for f in frames]
    if strict and (set(got) != want or len(got) != len(want)):
        raise ValueError(f"board {nn:02d}: frames {got} != §H {sorted(want)}")
    placed = layout(frames, per_row)
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    w = right + MARGIN + ANN_W + MARGIN
    h = int(math.ceil((max(bottom, MARGIN + ah) + MARGIN) / 8) * 8)
    if strict and nn in MEASURED_H:  # the live-measured annotation end + MARGIN (it must still clear the frames)
        if MEASURED_H[nn] < bottom + MARGIN:
            raise ValueError(f"board {nn:02d}: measured h {MEASURED_H[nn]} < frames bottom {bottom} + {MARGIN}")
        h = MEASURED_H[nn]
    if w > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {w} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch: widen the grid in the "
                         f"build notes or trim the annotations")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call (a mismatch makes a "
         f"duplicate root); size {w} x {h}")
    live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root (h {h}); "
         f"raise the root's h if not")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}) after relayout; no child "
             f"overflows it (clip on)")
    return {"name": b.name, "w": w, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}}, [*placed, a]


def _size(section: dict[str, Any]) -> int:
    return len(json.dumps(section))


_MEMO: dict[tuple[int, str, int], list[dict[str, Any]]] = {}


def _pack(n: Node, path: str, room: int, budget: int) -> tuple[Node | None, list[tuple[str, Node]]]:
    """n pruned to at most room bytes: the bare board, its longest prefix of whole kids and, when cheaper, the next
    kid packed the same way; plus the cut parts as (parent path, node) in render order (e42kit's packer, copied)."""
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
    """Sections under budget raw bytes each, into paths valid when used (frames first, then the annotation column)."""
    out: list[dict[str, Any]] = []
    try:
        for n in nodes:
            out += _emit(n, "", budget)
    finally:
        _MEMO.clear()
    return out


def lint(nodes: Iterable[Node]) -> list[str]:
    """Kit rules the validator does not check: no inst; icons in the local set; o.wrap a string; flex children
    without text carry h; no '/' in names; no banned string anywhere."""
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
    return bad


def _scan_banned(obj: Any) -> list[str]:
    s = json.dumps(obj, ensure_ascii=False)
    return sorted({m.group(0) for m in BANNED.finditer(s)})


def write_sheet(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
                per_row: int | None = None, out_dir: Path = CAP_DIR, name: str | None = None,
                strict: bool = True) -> Path:
    """Assemble board nn (board()), split into sections (<= SECTION_RAW_BUDGET raw), merge notes (this kit's + notes=),
    write out_dir/NN-<slug>.json, run the validator with the component inventory and raise RuntimeError unless it
    exits 0, a kit lint finding or a banned string appears. Clears NOTES. Returns the sheet path."""
    b = BOARDS[nn]
    if out_dir.resolve() not in (CAP_DIR, SELFTEST_DIR):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    board_, nodes = board(nn, frames, ann, per_row=per_row, strict=strict)
    if b.theme == "light":
        live(f"theme: activate the light token set before exporting (board {nn:02d} is the light twin of board "
             f"{b.twin:02d}); read back one bound fill (color.surface.canvas) as the light value")
    live(f"export {b.export}: the PNG's frames are each 1280 x 800 device px; record the board id and the PNG size")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {SPEC.name} md5 {SPEC_MD5[SPEC.name][:8]} (§0 L{b.line}); hand-off §H; E11-D04 §2, §5, "
                         f"§6, §10 (md5 {SPEC_MD5[SHELL.name][:8]}); E12-D04 board kit (chrome geometry)")
    sheet = {"board": board_, "sections": sections_for(nodes), "export": b.export,
             "notes": {k: list(v) for k, v in NOTES.d.items()}}
    NOTES.reset()
    banned = _scan_banned(sheet)
    if bad or banned:
        raise RuntimeError(f"board {nn:02d}: lint {bad[:8]} banned {banned}")
    out = (out_dir / (name or b.sheet)).resolve()
    out.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(out), "--components", str(COMPONENTS)],
                         capture_output=True, text=True, timeout=120, check=False)
    lines = (res.stdout + res.stderr).strip().splitlines()
    if res.returncode != 0:
        raise RuntimeError(f"{out.name}: validator exit {res.returncode}\n" + "\n".join(
            [ln for ln in lines if "ERROR" in ln.upper()][:20] or lines[-20:]))
    return out


def md_line3(nn: int) -> str:
    """The render script's line (it parses "page `...`" and "theme dark." / "theme light.")."""
    b = BOARDS[nn]
    return (f"File `{FILE_NAME}`, page `{PAGE}`; export `{b.export}`; sheet `{b.sheet}` (validated); "
            f"theme {b.theme}.")


def write_md(nn: int, sheet_path: Path, *, summary: str = "", frames_info: Iterable[str] = ()) -> Path:
    """The sheet's .md, beside it and (board sheets) in the kit folder: line 1 "# <board name>", line 3 md_line3(nn),
    then summary, frames, the validator line and the notes (live checks first). Refuses a banned string."""
    b = BOARDS[nn]
    sh = json.loads(Path(sheet_path).read_text(encoding="utf-8"))
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(sheet_path), "--components", str(COMPONENTS)],
                         capture_output=True, text=True, timeout=120, check=False)
    vline = (res.stdout + res.stderr).strip().splitlines()[-1]
    x, y = grid_xy(nn)
    out = [f"# {b.name}", "", md_line3(nn), "",
           summary or f"Board {nn:02d} of ten (§0 L{b.line}: {b.draws}). Grid ({x}, {y}); "
                      f"{sh['board']['w']} x {sh['board']['h']} px; footer \"page {PAGE} · board {nn:02d} · {REV}\".",
           "", "## Frames", ""]
    out += [f"- `{frame_name(f)}`" for f in b.frames] + [f"- {ln}" for ln in frames_info]
    out += ["", "## Validator and size", "", f"- `{vline}` (exit {res.returncode})",
            f"- {len(sh['sections'])} sections, {len(json.dumps(sh))} bytes", ""]
    notes = sh["notes"]
    for kd in ("live_checks", "spec_gaps", "deviations", "copy_keys", "copy_gaps", "fallbacks", "sources", "tokens"):
        lines = notes.get(kd) or []
        out += [f"## {kd.replace('_', ' ').capitalize()} ({len(lines)})", ""] + [f"- {ln}" for ln in lines] + [""]
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(out))  # an empty notes section leaves one blank line (prettier)
    if BANNED.search(s):
        raise RuntimeError(f"md for board {nn:02d}: banned string {BANNED.search(s).group(0)!r}")  # type: ignore[union-attr]
    sp = Path(sheet_path).resolve()
    (sp.parent / (sp.stem + ".md")).write_text(s, encoding="utf-8")  # beside the sheet (the render drivers' set)
    p = (KIT_DIR if sp.parent == CAP_DIR else sp.parent) / (sp.stem + ".md")  # the committed copy
    p.write_text(s, encoding="utf-8")
    return p


def pack_sheet(sheet_path: Path, out_dir: Path = V4_DIR) -> Path:
    """Pack with compact.py into out_dir/<same name> (default v4/); the packer writes the source's absolute path into
    compactOf.file, which is then rewritten to the bare file name (the sha256 beside it is the source's, unchanged);
    check that and every packed section is <= PACKED_MAX bytes (compact JSON). Raises RuntimeError otherwise."""
    src = Path(sheet_path).resolve()
    out_dir = out_dir.resolve()
    if out_dir not in (V4_DIR, SELFTEST_DIR):
        raise ValueError(f"packed sheets go to {V4_DIR}")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (src.name if out_dir == V4_DIR else src.stem + ".packed.json")
    res = subprocess.run([sys.executable, "-I", str(PACKER), str(src), str(dst)], capture_output=True, text=True,
                         timeout=300, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"packer exit {res.returncode}: {(res.stdout + res.stderr).strip()[-600:]}")
    raw = dst.read_text(encoding="utf-8")
    pf = (json.loads(raw).get("compactOf") or {}).get("file")
    if not pf or not Path(pf).is_absolute() or Path(pf) != src:
        raise RuntimeError(f"{dst.name}: compactOf.file {pf!r} is not the absolute source path")
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


# --- self-test: python3 -I e12d07kit.py selftest
def sample_frame() -> tuple[Node, tuple[str, list[str]]]:
    """Board 02's first frame as the sample: tick/default · dark (RightRail open, so the auto columns stay hidden),
    rows around the sweep (bar k of n), focused row bar 3 of 5, the forming row not shown."""
    mode, fid = "tick", BOARDS[2].frames[0]
    w = dock_w("open")
    rows_all = series(mode)
    i0 = next(i for i, b in enumerate(rows_all) if b.t == SWEEP_AT) - 6
    room = table_room()
    cols = shown_columns(mode, auto=row_width(shown_columns(mode, auto=True), mode) + 16 <= w)
    cap = caption_text(rows_all[i0:i0 + 18], mode, loaded=len(rows_all))
    n = max_rows(h=room, caption_lines=caption_lines(cap, w))
    sel = rows_all[i0:i0 + n]
    cap = caption_text(sel, mode, loaded=len(rows_all))
    focus = next(b for b in sel if b.t == SWEEP_AT and b.k == 3)
    rows = [bar_row(b, cols, mode, i + 1, focused=b is focus, cvd=cvd_of(rows_all, b)) for i, b in enumerate(sel)]
    t = table(rows, w=w, h=room, caption_chars=cap, header=header_row(cols, mode), footer=footer_row(w - 16))
    fr = window(fid, panel(mode, t, w=w), rail="open")
    blk = frame_block(fid, state="tick/default (§2.2 non-time row header; §3.1 tick set, auto columns hidden)",
                      mode=mode, cols=cols, row_header_form=f"{row_header(focus, mode)} — name: {row_name(focus, mode)}",
                      keyboard="Alt+T opened the table in place; focus on the cursor bar's row (D04E11 D2); ↑ / ↓ "
                               "move the row (origin table)", announcement="Data table, row k of N (D04E11 D2)",
                      copy_keys=("W-10", "W-11"), tokens=frame_tokens(fr))
    return fr, blk


def _spec_widths() -> dict[str, tuple[float, float]]:
    """§5's table read back: mode -> (primary px, with-auto px)."""
    out = {}
    for m in MODES:
        a = re.search(rf"([\d.]+)<!--=WIDTH:{m}\.px-->", "\n".join(SPEC_LINES))
        b = re.search(rf"([\d.]+)<!--=WIDTH:{m}\.auto-->", "\n".join(SPEC_LINES))
        out[m] = (float(a.group(1)), float(b.group(1)))  # type: ignore[union-attr]
    return out


def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), f"pinned md5s {spec_md5_ok()}")
    check(sorted(BOARDS) == list(range(1, 11)), "§0: ten boards 01-10")
    check(LIGHT_TWINS == {9: 4, 10: 5}, f"§0: two light twins {LIGHT_TWINS}")
    check(all(b.frames for b in BOARDS.values()), "§H: every board has its frames")
    check(all(f.endswith("· " + b.theme) for b in BOARDS.values() for f in b.frames), "§H frame themes match §0")
    check(sorted(n for p in PAIRS for n in p) == list(range(1, 11))
          and all(any(set(p) == {t, base} for p in PAIRS) for t, base in LIGHT_TWINS.items()), "five pairs, twins paired")
    check(len(COPY) == 22 and COPY["W-1"][0] == "Series restarted 09:15 UTC", "§13: 22 strings")
    check(len(COLUMNS) == 17 and set(COLUMNS) == set(COL_ORDER), "§3.1: 17 columns")
    sw = _spec_widths()
    check(all((set_width(m, "P"), set_width(m, "PA")) == sw[m] for m in MODES), f"§5 widths re-derived {sw}")
    check(set_width("time", "P", equi=True) == 659.4, "§5: equi-volume time set 659.4")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for k, v in globals().items() if k.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border)\.", v)]
    check(all(u in toks for u in used), f"kit tokens exist ({len(used)})")
    t = series("tick")
    sweep = [b for b in t if b.t == SWEEP_AT]
    check([b.k for b in sweep] == list(range(1, len(sweep) + 1)) and len(sweep) >= 3, f"bar k of n at the sweep: "
          f"{[(b.k, b.n) for b in sweep]}")
    check(all(not series(m)[-1].confirm for m in MODES), "every mode's last row is forming")
    check(state_word({"Est.", "POC"}) == "Est.·POC" and state_word({"stale", "forming"}) == "forming"
          and state_word(()) == "—", "§6 precedence")
    check(f_duration(2600) == "0:02.6" and f_duration(3725000) == "1:02:05", "duration format")
    try:
        node("inst", "x")
        check(False, "inst refused")
    except ValueError:
        check(True, "inst refused")
    fr, blk = sample_frame()
    ann = annotations(2, [blk], board_lines=["Self-test sheet: one sample frame, not a board of the set"])
    reset_extra = dict(NOTES.d)
    path = write_sheet(2, [fr], ann, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False,
                       notes={"live_checks": ["self-test sheet: not for rendering"]})
    check(path.exists() and reset_extra is not None, f"validator exit 0: {path.name}")
    md = write_md(2, path, summary="Self-test sheet (one sample frame); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    check(re.search(r"page `([^`]+)`", l3).group(1) == PAGE and l3.endswith("theme dark."),  # type: ignore[union-attr]
          f"md line 3 parses: {l3}")
    packed = pack_sheet(path, SELFTEST_DIR)
    sh = json.loads(packed.read_text(encoding="utf-8"))
    check(sh["compactOf"]["file"] == path.name, f"packed {packed.name}: bare pack source name, "
          f"{len(sh['sections'])} sections, max {max(len(json.dumps(s, separators=(',', ':'))) for s in sh['sections'])} B")
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
    raise SystemExit(2)
