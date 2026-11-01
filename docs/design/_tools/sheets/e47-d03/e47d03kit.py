"""E47-D03 (#1302) board kit: the themes, the CVD-safe chart palette, the non-colour encodings and SCR-116, ten
boards as cvsheet JSON sheets for the per-set Penpot file "E47-D03 boards", page "E47-D03 themes and SCR-116".

Offline only. Spec (binding; every string, number, token and frame comes from it): docs/design/E47/E47-D03.md and
E47-D03-handoff.md as this checkout commits them (read by repo-relative path; md5-pinned in SPEC_MD5: the kit refuses
drifted bytes; re-read, re-check the cites, re-pin).
Registry: §0's board table (BOARDS) and the hand-off's §G frame plan (FRAMES) are parsed; every measured figure is
read from the spec's anchored tool values (VAL: `value<!--=KIND:key-->`, written by e47_d03_theme_audit.py --fill),
never typed here.

Pipeline (one generator per board, gen/gen_NN.py):
    frames = [...]                                    # one 1280 x 800 frame per §G entry, in order
    ann = annotations(nn, [(frame id, lines), ...])  # the ONE 400 px column
    p = write_sheet(nn, frames, ann)                  # build/NN-<slug>.json (untracked), validator exit 0 or raises
    write_md(nn, p)                                   # NN-<slug>.md here and in build/, line 3 = the render line
    pack_sheet(p)                                     # v4/NN-<slug>.json, compactOf.file = the bare name + its sha256
Twins: board 04 calls board 01's frame builder with theme="light"; board 10 calls board 09's with theme="light".
Self-test: python3 -I -B e47d03kit.py selftest   (one sample frame into build/selftest/, validated, packed)
Rebuild all ten: BUILD.md in this folder.

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (the spec's "/" in frame names is drawn as
U+2215); no local path, host or agent name anywhere in a sheet (BANNED); packed sections <= 9 KB; table cells carry
8 px inner padding a side.
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
SPEC = REPO / "docs/design/E47/E47-D03.md"
HANDOFF = REPO / "docs/design/E47/E47-D03-handoff.md"
# re-pinned at the boards commit: §0's Status cells and As built, the DoD and the version line, the hand-off's §A row,
# §G heading and §H line were extended in place, so every L<n> / §G cite on the ten boards reads the same text
SPEC_MD5 = {SPEC.name: "a79ee8972d1636d41c19d3287d9e80a7", HANDOFF.name: "9115b70824595e8c72db3d3111ad43f5"}

REV = "r1"
PITCH_X, PITCH_Y = 6000, 3200  # grid: x = ((NN-1) mod 5) * 6000, y = floor((NN-1)/5) * 3200
MARGIN = 80
ANN_W = 400
ANN_TEXT_W = ANN_W - 32
FRAME_W, FRAME_H = 1280, 800
MAX_PER_ROW = 3
SECTION_RAW_BUDGET = 9000
PACKED_MAX = 9216
SLASH = "∕"  # DIVISION SLASH: "/" is cvsheet's path separator
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465", "2f746d70")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode()
                    + r"\b", re.I)


def _read(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").split("\n")


def spec_md5_ok() -> dict[str, bool]:
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() == SPEC_MD5[p.name] for p in (SPEC, HANDOFF)}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:
    raise SystemExit(f"e47d03kit: spec text drifted from SPEC_MD5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
SPEC_LINES = _read(SPEC)
HANDOFF_LINES = _read(HANDOFF)
_ANCHOR = re.compile(r"([^\s|`(]+?)<!--=([A-Z]+):([^>]+?)-->", re.DOTALL)
_COMMENT = re.compile(r"<!--=[^>]*-->", re.DOTALL)


def plain(s: str) -> str:
    """A spec cell without anchors, backticks or bold marks."""
    s = _COMMENT.sub("", s)
    return re.sub(r"\*\*|`", "", s).strip()


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def find_line(needle: str, lines: list[str] | None = None, start: int = 1) -> int:
    ls = SPEC_LINES if lines is None else lines
    for i in range(start - 1, len(ls)):
        if needle in ls[i]:
            return i + 1
    raise LookupError(f"not found: {needle!r}")


def L(needle: str, start: int = 1) -> int:
    """The spec line a board cites: looked up, never typed."""
    return find_line(needle, start=start)


def HL(needle: str, start: int = 1) -> int:
    return find_line(needle, HANDOFF_LINES, start)


def table_after(head: str, lines: list[str] | None = None) -> list[tuple[int, list[str]]]:
    """(line, cells) of the first markdown table after the heading line `head` (header and rule rows dropped)."""
    ls = SPEC_LINES if lines is None else lines
    i = find_line(head, ls)
    while not ls[i].startswith("|"):
        i += 1
    out = []
    j = i + 2
    while j < len(ls) and ls[j].startswith("|"):
        out.append((j + 1, _cells(ls[j])))
        j += 1
    return out


def _parse_values() -> dict[str, str]:
    vals: dict[str, str] = {}
    for ln in SPEC_LINES + HANDOFF_LINES:
        for v, kind, key in _ANCHOR.findall(ln):
            k = f"{kind}:{key}"
            if vals.get(k, v) != v:
                raise SystemExit(f"e47d03kit: anchor {k} carries two values ({vals[k]} / {v})")
            vals[k] = v
    return vals


VAL = _parse_values()


def val(kind: str, key: str) -> str:
    """A measured figure from the spec's tool output (KeyError when the spec has none: never invent one)."""
    return VAL[f"{kind}:{key}"]


def cr(theme: str, fg: str, bg: str) -> str:
    return val("CR", f"{theme}/{fg}/{bg}")


# --- §0: the boards; the hand-off's §G: their frames
_P0 = L("## 0. Status, artefacts and the boards")
_PAGE_M = re.search(r"Penpot file `([^`]+)`, page `([^`]+)`", SPEC_LINES[_P0 + 1])
if not _PAGE_M:
    raise SystemExit("e47d03kit: §0 names no Penpot file and page")
FILE_NAME, PAGE = _PAGE_M.group(1), _PAGE_M.group(2)
_EXPORT_PAT = re.search(r"Exports go to `([^`]+)`", SPEC_LINES[_P0 + 1]).group(1)  # .../E47-D03-NN-<slug>.png


@dataclass(frozen=True)
class Board:
    nn: int
    name: str
    slug: str
    draws: str
    theme: str  # dark | light | hc | mixed
    line: int
    twin: int | None
    frames: tuple[str, ...]  # the §G frame ids, "/" as written in the spec

    @property
    def export(self) -> str:
        return _EXPORT_PAT.replace("NN", f"{self.nn:02d}").replace("<slug>", self.slug)

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"

    @property
    def render_theme(self) -> str:
        """The set the drivers export under (line 3): a mixed board renders under dark (frames re-exported, notes)."""
        return "dark" if self.theme == "mixed" else self.theme


def _parse_frames() -> dict[int, tuple[tuple[str, ...], int]]:
    out = {}
    for ln, c in table_after("## §G Board plan", HANDOFF_LINES):
        out[int(c[0])] = (tuple(re.findall(r"`([^`]+)`", c[1])), ln)
    return out


FRAME_LINES = _parse_frames()


def _parse_boards() -> dict[int, Board]:
    out = {}
    for ln, c in table_after("## 0. Status, artefacts and the boards"):
        m = re.fullmatch(r"`(E47-D03 / (\d{2}) ([a-z0-9-]+))`", c[1])
        if not m:
            raise SystemExit(f"e47d03kit: §0 row L{ln} unreadable")
        nn = int(m.group(2))
        tw = re.match(r"light twin of (\d{2})", plain(c[2]))
        out[nn] = Board(nn, m.group(1), m.group(3), plain(c[2]), c[3], ln, int(tw.group(1)) if tw else None,
                        FRAME_LINES[nn][0])
    return out


BOARDS = _parse_boards()


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


def frame_name(fid: str) -> str:
    """The §G frame id as a node name: the spec's "/" drawn as U+2215 (cvsheet's path separator is "/")."""
    return fid.replace("/", SLASH)


# --- §13 copy deck, §8.1 controls, §8.2 presets, §8.3 variants, §5 encodings
@dataclass(frozen=True)
class Copy:
    key: str
    s: str
    source: str
    status: str
    line: int


COPY = {c[0]: Copy(c[0], plain(c[1]).strip('"'), plain(c[2]), plain(c[3]), ln)
        for ln, c in table_after("## 13. Copy deck")}


def w(key: str) -> str:
    """A W-n string exactly as §13 gives it (NOTES records the key)."""
    NOTES.add("copy_keys", f"{key} (§13 L{COPY[key].line}, {COPY[key].status.split(';')[0]}): {COPY[key].s}")
    return COPY[key].s


def w_label(key: str) -> str:
    """The label part of a "Label: a · b · c" string (W-9 … W-11)."""
    return w(key).split(": ", 1)[0]


def w_options(key: str) -> list[str]:
    return w(key).split(": ", 1)[1].split(" · ")


CONTROLS = {plain(c[0]): dict(component=plain(c[1]), values=plain(c[2]), default=plain(c[3]), keys=plain(c[4]),
                              line=ln) for ln, c in table_after("### 8.1 Layout, controls and keyboard")}
PRESET_ROWS = {plain(c[0]).split(" ")[0]: (c, ln) for ln, c in table_after("### 8.2 The accent presets")}
PRESETS = tuple(PRESET_ROWS)  # Blue, Cyan, Amber, Purple (W-9's order)
VARIANTS = {}
for _ln, _c in table_after("### 8.3 Variants"):
    VARIANTS[_c[0]] = dict(zip(("v", "variant", "surface", "copy", "tokens", "roles", "keyboard", "announce",
                                "analytics", "confidence", "board"), [plain(x) for x in _c]), line=_ln)
ENCODINGS = [(ln, [plain(x) for x in c]) for ln, c in table_after("## 5. The non-colour encoding set")]


def acc(theme: str, preset: str) -> str:
    """§8.2's measured cell for a preset in a theme (ACC anchor)."""
    c, _ln = PRESET_ROWS[preset]
    col = {"dark": 1, "light": 2, "hc": 3}[theme]
    m = _ANCHOR.search(c[col])
    if not m:
        raise LookupError(f"§8.2 {preset} {theme}: no anchored value")
    return m.group(1)


def acc_primitive(theme: str, preset: str) -> str:
    c, _ln = PRESET_ROWS[preset]
    m = _ANCHOR.search(c[{"dark": 1, "light": 2, "hc": 3}[theme]])
    return m.group(3).split("/", 1)[1]


def acc_bar(theme: str) -> float:
    return 7.0 if theme == "hc" else 4.5


def acc_warns(theme: str, preset: str) -> bool:
    """§8.2 "Warning in" names the theme (cross-checked against the figure and the bar)."""
    c, _ln = PRESET_ROWS[preset]
    word = {"dark": "dark", "light": "light", "hc": "high contrast"}[theme]
    named = word in plain(c[5])
    if named != (float(acc(theme, preset)) < acc_bar(theme)):
        raise SystemExit(f"e47d03kit: §8.2 {preset} {theme}: Warning-in disagrees with the figure")
    return named


# --- tokens (exact names in token-sync.json; the self-test checks every one)
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_INV, TEXT_ON_ACTION, TEXT_LINK = "color.text.inverse", "color.text.on-action", "color.text.link"
BORDER, BORDER_SUBTLE, BORDER_STRONG, BORDER_SEL = ("color.border.default", "color.border.subtle",
                                                   "color.border.strong", "color.border.selected")
RING = "color.focus.ring"
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
WARN_STRONG, OK_STRONG, DANGER_STRONG = ("color.status.warning.strong", "color.status.success.strong",
                                         "color.status.danger.strong")
ENV_LIVE, ENV_DEMO = "color.env.live", "color.env.demo"
GRID = "color.grid.line"
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD, HEADING_LG, DISPLAY = ("type.ui.heading-sm", "type.ui.heading-md", "type.ui.heading-lg",
                                               "type.ui.display")
NUM, NUM_SM, NUM_MD = "type.num.base", "type.num.sm", "type.num.md"
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
BUTTON_PADX = "space.button.paddingX"
ICON, ICON_SM = "size.icon", "size.icon.sm"
R_CONTROL, R_CARD, R_BADGE = "radius.control", "radius.card", "radius.badge"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, BUTTON_PADX: 12, ICON: 16, ICON_SM: 12}


def ink(palette: str) -> dict[str, str]:
    """The data-ink slots per chart palette (§2.3: the CVD-safe palette remaps buy/sell, candles, footprint, the
    heatmap ramps and the imbalance flag; the profile ink is not remapped)."""
    if palette == "default":
        d = {"buy": "color.buy.default", "sell": "color.sell.default", "up": "color.candle.up",
             "down": "color.candle.down", "bid": "color.footprint.bid", "ask": "color.footprint.ask",
             "imbalance": "color.footprint.imbalance"}
        d.update({f"hm.bid.{i}": f"color.heatmap.bid.{i}" for i in range(1, 6)})
        d.update({f"hm.ask.{i}": f"color.heatmap.ask.{i}" for i in range(1, 6)})
    elif palette == "cvd-safe":
        d = {k: "color.cvd.buy" for k in ("buy", "up", "bid")} | {k: "color.cvd.sell" for k in ("sell", "down", "ask")}
        d["imbalance"] = "color.cvd.imbalance"
        d.update({f"hm.bid.{i}": f"color.cvd.heatmap.bid.{i}" for i in range(1, 6)})
        d.update({f"hm.ask.{i}": f"color.cvd.heatmap.ask.{i}" for i in range(1, 6)})
    else:
        raise ValueError(palette)
    d.update({"hm.zero": "color.heatmap.zero", "bar": "color.profile.bar", "poc": "color.profile.poc",
              "va": "color.profile.valuearea", "wick": "color.candle.wick", "axis": "color.axis.text"})
    return d


# the token sets the validator reads (theme resolution follows R-4: light and hc overlay dark)
_TS: dict[str, dict[str, str]] = {}
for _s, _n, _t, _v in json.loads(TOKENS_FILE.read_text(encoding="utf-8")):
    _TS.setdefault(_s, {})[_n] = str(_v)


def resolves_to(theme: str, token: str) -> str:
    """The primitive a semantic colour token resolves to in a theme (overlay on semantic-dark)."""
    seen = 0
    cur = token
    while seen < 12:
        v = None
        for s in ([f"semantic-{theme}"] if theme != "dark" else []) + ["semantic-dark"]:
            if cur in _TS.get(s, {}):
                v = _TS[s][cur]
                break
        if v is None:
            return cur
        cur = v.strip("{}")
        if cur.startswith("palette."):
            return cur
        seen += 1
    raise ValueError(token)


_HUE_STANDIN = {"Blue": TEXT_LINK, "Cyan": "color.status.info.strong", "Amber": WARN_STRONG,
                "Purple": "color.node.logic"}


def swatch_token(theme: str, preset: str) -> tuple[str, bool]:
    """(token, exact): a semantic alias resolving to the preset's §8.2 primitive in that theme, else the same-hue
    stand-in (exact False: the live drawer rebinds the fill to the primitive; the validator refuses primitives)."""
    prim = acc_primitive("hc" if theme == "hc" else theme, preset)
    names = sorted({n for s in ("semantic-dark", f"semantic-{theme}") for n in _TS.get(s, {}) if n.startswith("color.")})
    exact = [n for n in names if resolves_to(theme, n) == prim]
    if exact:
        pick = _HUE_STANDIN[preset] if _HUE_STANDIN[preset] in exact else exact[0]
        return pick, True
    return _HUE_STANDIN[preset], False



_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}


# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "spec_gaps", "fallbacks", "tokens", "live_checks",
              "deviations", "ambiguities")


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
    """A string the copy deck lacks, drawn from the spec's prose (cite the line)."""
    NOTES.add("copy_gaps", line)


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
    """A node of type t (None values dropped). Refuses inst nodes, unknown keys, "/" in the name, a non-string
    o.wrap, and a banned string in the name, note or chars. Records bound tokens."""
    if t not in _KEYS:
        raise ValueError(f"node type {t!r} not allowed (no inst nodes in the per-set file)")
    name = name.replace("/", SLASH)  # a label carrying "/" (W-4, W-12 …) names its node with U+2215
    if not name:
        raise ValueError(f"{t} name is empty")
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
         HEADING_SM: (14, 1.2, False), HEADING_MD: (16, 1.2, False), HEADING_LG: (20, 1.2, False),
         DISPLAY: (24, 1.2, False), NUM: (13, 1.2, True), NUM_SM: (11, 1.2, True), NUM_MD: (14, 1.2, True)}


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




FALLBACKS = {
    "chrome": "kit choice: the shell chrome (TopBar, NavRail, StatusBar) and CMP-086's settings list drawn as neutral "
              "placeholders; only SCR-116's content, the PreviewTile and the env badges of board 08 are drawn",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)",
    "hatch": "fallback: pattern.hatch (§5 imbalance) drawn as 1 px vertical stripes in the imbalance ink over an 8 px "
             "strip at the cell's outer edge (no pattern primitive in cvsheet)",
    "line": "fallback: the CVD pane's line drawn as 4 x 4 px marks, one per sample (no path primitive in cvsheet)",
    "env-glyph": "fallback: icon/env-live (filled dot in a ring) and icon/env-demo (outline dot) drawn as ellipses: "
                 "neither is in the local icon set",
    "tri": "fallback: the direction glyphs ▲ / ▼ drawn as text characters (§5's own glyphs)",
    "projection": "kit choice (E15-D04 precedent): the grey and dichromacy frames bind the true ink tokens; the "
                  "simulation is the export's projection (§7.1), never a painted hex; each frame lists §7.4's expected "
                  "hexes to read back",
    "type-150": "fallback: no type token at 150 %: each role is drawn with the token nearest 1.5 x its size "
                "(caption 11 -> heading-md 16, label 12 / body 13 -> heading-lg 20, heading-sm 14 / heading-md 16 -> "
                "display 24); the weight steps up with it",
    "zoom-200": "kit choice: the 200 % frame draws the 640 CSS px page at 1:1 in two 640 px strips (CSS y 0-800 and "
                "800-1600); the device shows it at 2 x. The 640 x 400 CSS viewport is outlined on the first strip",
    "weight": "fallback: CMP-074's font.weight.bold has no 13 px type token: LIVE and DEMO both bind type.ui.body-strong "
              "(the word and the glyph carry the environment, §9)",
    "border-control": "fallback: border.control (D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries "
                      "bind its values directly, border.hairline in dark and light, border.thick in high contrast",
    "swatch": "fallback: where no semantic alias resolves to a preset's §8.2 primitive in the board's theme, the swatch "
              "binds the same-hue stand-in and the live drawer rebinds it to the primitive (the validator refuses "
              "primitive colour binds)",
}


def ambiguity(line: str) -> None:
    NOTES.add("ambiguities", line)


# --- the illustrative world: a seeded synthetic stream (seed SEED), declared on every board. Every figure on a frame
# is derived from it (delta = ask - bid, POC = the largest level, VA = 70 % around it, CVD = the running delta sum).
SEED = 1302
SYMBOL = "BTCUSDT"
TICK = 0.5
LAST = 64250.0
DATA_LINE = (f"Data: seeded synthetic stream (seed {SEED}, {SYMBOL}, tick {TICK}); sample data, not a market capture "
             "(§8.4: synthetic sample data only)")


def px_(p: float) -> str:
    return f"{p:,.1f}".replace(",", " ")


def signed(v: float, nd: int = 0) -> str:
    s = f"{abs(v):,.{nd}f}".replace(",", " ")
    return ("+" if v > 0 else "−" if v < 0 else "") + s


@dataclass(frozen=True)
class World:
    fp: tuple[tuple[float, int, int], ...]  # footprint levels (price, bid, ask), top = highest price
    dom: tuple[tuple[float, int, int], ...]  # ladder levels (price, bid size, ask size)
    hm: tuple[tuple[int, ...], ...]  # heatmap stops by row (top first) x column; 0 = zero, 1..5 the ramp
    hm_mid: tuple[int, ...]  # per column: the row index of the price line (rows above: asks, below: bids)
    prof: tuple[tuple[float, int], ...]  # profile (price, volume), top = highest
    cvd: tuple[int, ...]  # running delta per sample
    trades: tuple[tuple[int, float, int, str], ...]  # (sample, price, size, side)
    candles: tuple[tuple[float, float, float, float], ...]  # (open, high, low, close)


def make_world() -> World:
    r = random.Random(SEED)
    fp = tuple((LAST + TICK * (4 - i), r.randint(2, 48), r.randint(2, 48)) for i in range(10))
    fp = tuple((p, b, a * 4 if i == 2 else a) for i, (p, b, a) in enumerate(fp))  # one ask-side imbalance
    fp = tuple((p, b * 4 if i == 7 else b, a) for i, (p, b, a) in enumerate(fp))  # one bid-side imbalance
    dom = tuple((LAST + TICK * (6 - i), r.randint(1, 90) if i >= 6 else 0, r.randint(1, 90) if i < 6 else 0)
                for i in range(12))
    rows, cols = 14, 16
    mid, hm, mids = rows // 2, [], []
    for c in range(cols):
        mid = max(4, min(rows - 5, mid + r.choice((-1, 0, 0, 1))))
        mids.append(mid)
    for ri in range(rows):
        hm.append(tuple(0 if r.random() < 0.18 else max(1, min(5, 5 - abs(ri - mids[c]) // 2 + r.choice((-1, 0, 0))))
                        for c in range(cols)))
    vols = [int(400 * math.exp(-((i - 6.5) ** 2) / 14.0)) + r.randint(5, 60) for i in range(16)]
    prof = tuple((LAST + TICK * (8 - i), v) for i, v in enumerate(vols))
    run, cvd = 0, []
    for _ in range(40):
        run += r.randint(-30, 34)
        cvd.append(run)
    trades = tuple((r.randint(1, 38), LAST + TICK * r.randint(-6, 6), r.choice((3, 8, 15, 30, 60)),
                    r.choice(("buy", "sell"))) for _ in range(10))
    o, cs = LAST - 6.0, []
    for _ in range(12):
        c = o + TICK * r.randint(-6, 6)
        cs.append((o, max(o, c) + TICK * r.randint(0, 3), min(o, c) - TICK * r.randint(0, 3), c))
        o = c
    return World(fp, dom, tuple(hm), tuple(mids), prof, tuple(cvd), trades, tuple(cs))


WORLD = make_world()


def value_area(prof: tuple[tuple[float, int], ...], share: float = 0.7) -> tuple[int, int, int]:
    """(poc index, va top index, va bottom index): grow from the POC by the larger neighbour until share of volume."""
    vols = [v for _p, v in prof]
    poc = vols.index(max(vols))
    lo = hi = poc
    acc_ = vols[poc]
    while acc_ < share * sum(vols):
        up = vols[lo - 1] if lo > 0 else -1
        dn = vols[hi + 1] if hi + 1 < len(vols) else -1
        if up >= dn:
            lo -= 1
            acc_ += up
        else:
            hi += 1
            acc_ += dn
    return poc, lo, hi


def nodes_hvn_lvn(prof: tuple[tuple[float, int], ...]) -> tuple[list[int], list[int]]:
    """Local maxima other than the POC (HVN) and local minima (LVN), by bar length (BQ-4: no new hue)."""
    v = [x for _p, x in prof]
    poc = v.index(max(v))
    hv = [i for i in range(1, len(v) - 1) if v[i] > v[i - 1] and v[i] > v[i + 1] and i != poc]
    lv = [i for i in range(1, len(v) - 1) if v[i] < v[i - 1] and v[i] < v[i + 1]]
    return hv, lv


IMB_RATIO = 3.0  # kit choice: a footprint cell is flagged when one side is >= 3.0 x the other (illustrative)


def imbalance(bid: int, ask: int) -> str | None:
    if ask >= IMB_RATIO * bid:
        return "ask"
    if bid >= IMB_RATIO * ask:
        return "bid"
    return None


# --- the window: SCR-116 inside the shell at 1280 x 800 (§0, §8.1): TopBar 48 | NavRail 64 · CMP-086 settings list
# 208 · content | StatusBar 48. Compact density is the default (§8.1), so controls and rows are 24 px.
TOP_H, STATUS_H, NAV_W, SET_NAV_W = 48, 48, 64, 208
BODY_H = FRAME_H - TOP_H - STATUS_H  # 704
CONTENT_W = FRAME_W - NAV_W - SET_NAV_W  # 1008
CONTENT_PAD = 24
CONTROLS_W, TILE_W, COL_GAP = 560, 360, 24  # COL_GAP = space.inset.xl
CONTROL_H, ROW_H = 24, 24


def border_w(theme: str) -> str:
    """border.control's value per theme (D03-D5 / D03-D6, PROPOSED; FALLBACKS['border-control'])."""
    fallback("border-control")
    return THICK if theme == "hc" else HAIR


def placeholder(name: str, w_: int, h: int = 12) -> Node:
    fallback("chrome")
    return rect(f"placeholder · {name}", w_, h, HOVER, {"radius": R_CONTROL})


def topbar(badge: Node | None = None) -> Node:
    left = hbox("left", [placeholder("wordmark", 88), badge or placeholder("env badge", 56, 20),
                         placeholder("account picker", 136)], {"gap": INSET_MD}, h=TOP_H)
    right = hbox("right", [placeholder("health chip", 120), placeholder("user menu", 72)], {"gap": INSET_MD}, h=TOP_H)
    return hbox("TopBar (placeholder)", [left, right, rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=TOP_H - 1,
                                                          abs=True)],
                {"padX": INSET_LG, "justify": "space-between", "fill": APP}, w=FRAME_W, h=TOP_H,
                note="the shell's TopBar, not this spec's: placeholders only (CMP-075 badge drawn on board 08)")


def navrail() -> Node:
    rows = [hbox(f"entry-{i}", [placeholder("glyph", 16, 16)], {"justify": "center"}, w=48, h=32) for i in range(1, 7)]
    return vbox("NavRail (placeholder)", [*rows, rect("divider", 1, BODY_H, BORDER_SUBTLE, x=NAV_W - 1, y=0, abs=True)],
                {"gap": INSET_XS, "align": "center", "padY": INSET_SM, "fill": APP}, w=NAV_W, h=BODY_H)


def statusbar(kids: Iterable[Node] = ()) -> Node:
    ks = list(kids) or [placeholder("connection chip", 120), placeholder("env word", 56)]
    return hbox("StatusBar (placeholder)", [*ks, rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"padX": INSET_LG, "gap": INSET_LG, "fill": APP}, w=FRAME_W, h=STATUS_H)


def settings_nav(theme: str) -> Node:
    """CMP-086's settings list: placeholder entries and the current one, "Appearance" (SCR-116), its selected label
    in the accent's text use (color.text.link, §8.2) with the selected-tab underline in color.border.selected."""
    copy_gap(f'"Appearance": the current settings entry and the h1, from §0 L{L("**SCR-116 is part-built.**")} '
             f'(the shipped AppearanceScreen) and §8.4 L{L("Appearance holds no secret")}; §13 has no title string')
    cur = vbox("entry · Appearance (current)", [
        text("label", "Appearance", BODY_STRONG, TEXT_LINK),
        rect("selected underline", 80, 2, BORDER_SEL)], {"gap": STACK_XS, "padX": INSET_MD, "padY": INSET_XS},
        w=SET_NAV_W - 16, note='aria-current="page"; the accent drives the selected label and underline (§8.2)')
    ents = [hbox(f"entry-{i}", [placeholder("label", 96 + 8 * (i % 3))], {"padX": INSET_MD}, w=SET_NAV_W - 16, h=28)
            for i in range(1, 5)]
    return vbox("CMP-086 settings list", [*ents[:2], cur, *ents[2:],
                                          rect("divider", 1, BODY_H, BORDER_SUBTLE, x=SET_NAV_W - 1, y=0, abs=True)],
                {"gap": INSET_XS, "pad": INSET_SM, "fill": RAISED}, w=SET_NAV_W, h=BODY_H)


def window(name: str, theme: str, content: Node, *, badge: Node | None = None, status: Iterable[Node] = (),
           note: str | None = None, settings: bool = True) -> Node:
    """One 1280 x 800 frame: TopBar | NavRail · (settings list) · content | StatusBar."""
    if theme not in ("dark", "light", "hc"):
        raise ValueError(theme)
    main_w = CONTENT_W if settings else FRAME_W - NAV_W
    main = box("main", [dict(content, x=0, y=0)], {"fill": APP, "clip": True}, w=main_w, h=BODY_H)
    body = hbox("body", [navrail(), settings_nav(theme) if settings else None, main], {"align": "start"}, w=FRAME_W,
                h=BODY_H)
    return vbox(name, [topbar(badge), body, statusbar(status)], {"fill": APP, "clip": True}, w=FRAME_W, h=FRAME_H,
                note=note)


# --- controls (compact). Every control boundary binds color.border.strong (R-6) at border.control's weight.
def ring(control: Node, radius: str = R_CONTROL) -> Node:
    """Focus-visible: a wrapper with a 4 px offset and a 2 px color.focus.ring inner stroke; the ring sits over
    the surface, never touching an action fill (§3.1)."""
    size = {k_: control[k_] + 8 for k_ in ("w", "h") if control.get(k_)}
    return hbox("focus-ring", [control], {"pad": INSET_XS, "radius": radius, "stroke": RING, "strokeWidth": FOCUS_W,
                                          "strokeAlign": "inner"}, note="focus-visible", **size)


def segmented(name: str, options: Iterable[str], selected: str, theme: str, *, focused: bool = False,
              typo: str = BODY_STRONG, seg_h: int = 20) -> Node:
    segs = [hbox(f"segment · {o}", [text("label", o, typo, TEXT_1 if o == selected else TEXT_2)],
                 {"padX": INSET_MD, "radius": R_CONTROL, **({"fill": SELECTED} if o == selected else {})}, h=seg_h,
                 note='role="radio" aria-checked="true"' if o == selected else 'role="radio"') for o in options]
    s = hbox(name, segs, {"pad": INSET_XS, "gap": INSET_XS, "radius": R_CONTROL, "fill": SUNKEN, "stroke": BORDER_STRONG,
                          "strokeWidth": border_w(theme), "strokeAlign": "inner"}, h=seg_h + 8,
             note="radiogroup; arrows move, selection follows focus (J16)")
    return ring(s) if focused else s


def radio(label_: str, checked: bool, theme: str, typo: str = BODY) -> Node:
    dot = [ellipse("dot", 8, 8, {"fill": ACTION_PRIMARY}, x=4, y=4, abs=True)] if checked else []
    circle = box("circle", [ellipse("outline", 16, 16, {"fill": CANVAS, "stroke": BORDER_STRONG,
                                                       "strokeWidth": border_w(theme), "strokeAlign": "inner"},
                                    x=0, y=0, abs=True), *dot], w=16, h=16)
    return hbox(f"radio · {label_}", [circle, text("label", label_, typo, TEXT_1)], {"gap": INSET_SM}, h=CONTROL_H,
                note=f'role="radio" aria-checked="{str(checked).lower()}"')


def checkbox(label_: str, checked: bool, theme: str, typo: str = BODY) -> Node:
    boxk = hbox("box", [icon("check", "check", TEXT_ON_ACTION, ICON_SM)] if checked else [],
                {"justify": "center", "radius": R_CONTROL, "fill": ACTION_PRIMARY if checked else CANVAS,
                 "stroke": BORDER_STRONG, "strokeWidth": border_w(theme), "strokeAlign": "inner"}, w=16, h=16)
    return hbox(f"checkbox · {label_}", [boxk, text("label", label_, typo, TEXT_1)], {"gap": INSET_SM}, h=CONTROL_H,
                note=f'aria-checked="{str(checked).lower()}"; Space toggles')


def toggle(label_: str, on: bool, theme: str, typo: str = BODY) -> Node:
    knob = ellipse("knob", 12, 12, {"fill": TEXT_ON_ACTION if on else TEXT_2}, x=14 if on else 2, y=2, abs=True)
    track = box("track", [knob], {"radius": R_BADGE, "fill": ACTION_PRIMARY if on else SUNKEN, "stroke": BORDER_STRONG,
                                  "strokeWidth": border_w(theme), "strokeAlign": "inner"}, w=28, h=16)
    return hbox(f"toggle · {label_}", [track, text("label", label_, typo, TEXT_1)], {"gap": INSET_SM}, h=CONTROL_H,
                note=f'role="switch" aria-checked="{str(on).lower()}"; Space toggles')


def button(chars: str, theme: str, *, typo: str = BODY_STRONG, focused: bool = False) -> Node:
    t = text("label", chars, typo, TEXT_1)
    wd = round(text_w(chars, typo) + 2 * PX[BUTTON_PADX] + 2)
    b = hbox(f"button · {chars}", [t], {"padX": BUTTON_PADX, "radius": R_CONTROL, "justify": "center",
                                        "fill": ACTION_SECONDARY, "stroke": BORDER_STRONG,
                                        "strokeWidth": border_w(theme), "strokeAlign": "inner"},
             w=wd, h=max(CONTROL_H + 4, round(text_h(typo)) + 8), note="CMP-001 Button (secondary)")
    return ring(b) if focused else b


# --- type scale (V-5): 1.0 = the tokens as named; 1.5 = FALLBACKS['type-150']
_T150 = {CAPTION: HEADING_MD, LABEL: HEADING_LG, BODY: HEADING_LG, BODY_STRONG: HEADING_LG, HEADING_SM: DISPLAY,
         HEADING_MD: DISPLAY, NUM: HEADING_LG, NUM_SM: HEADING_MD}


class Scale:
    def __init__(self, factor: float = 1.0) -> None:
        self.f = factor

    def __call__(self, typo: str) -> str:
        if self.f == 1.0:
            return typo
        fallback("type-150")
        return _T150[typo]


S1 = Scale(1.0)


# --- CMP-031 accent picker, the V-2 warning, the PreviewTile (CMP-228 kind "theme")
THEME_WORD = {"dark": "Dark", "light": "Light", "hc": "High contrast"}  # §8.1 Theme values


def theme_values() -> list[str]:
    vals = CONTROLS["Theme"]["values"].split(" · ")
    if [THEME_WORD[t] for t in ("dark", "light", "hc")] != vals:
        raise SystemExit(f"e47d03kit: §8.1 Theme values changed: {vals}")
    return vals


def swatch(preset: str, theme: str, *, chosen: bool, focused: bool = False) -> Node:
    """One preset: a 24 x 24 swatch (2.5.8) filled with the preset's colour, its boundary at border.control; the chosen
    one carries the check glyph in color.text.inverse (§3.6) and a 2 px color.border.selected ring (never a ring
    alone); then its visible name."""
    tok, exact = swatch_token(theme, preset)
    if not exact:
        fallback("swatch")
        live(f"swatch '{preset}' ({theme}): rebind its fill from {tok} to {acc_primitive(theme, preset)} (§8.2's "
             f"primitive, BQ-8); read back that the check glyph stays color.text.inverse")
    kids = [icon("check", "check", TEXT_INV, ICON)] if chosen else []
    sw = hbox("swatch", kids, {"justify": "center", "radius": R_CONTROL, "fill": tok, "stroke": BORDER_STRONG,
                               "strokeWidth": border_w(theme), "strokeAlign": "inner"}, w=24, h=24,
              note=f"fill {tok}{'' if exact else ' (stand-in; live rebind)'} = {acc_primitive(theme, preset)}")
    if chosen:
        sw = hbox("selected", [sw], {"pad": INSET_XS, "radius": R_CONTROL, "stroke": BORDER_SEL,
                                     "strokeWidth": THICK, "strokeAlign": "inner"}, w=32, h=32)
    if focused:
        sw = ring(sw)
    return hbox(f"preset · {preset}", [sw, text("name", preset, BODY, TEXT_1)], {"gap": INSET_SM},
                note=f'role="radio" aria-checked="{str(chosen).lower()}" named "{preset}"')


def accent_picker(theme: str, chosen: str, *, focused: str | None = None) -> Node:
    opts = w_options("W-9")
    if tuple(opts) != PRESETS:
        raise SystemExit(f"e47d03kit: W-9 {opts} != §8.2 presets {PRESETS}")
    return hbox("CMP-031 accent picker", [swatch(p, theme, chosen=p == chosen, focused=p == focused) for p in opts],
                {"gap": INSET_LG}, note=f'radiogroup "{w_label("W-9")}"; closed preset set, no free colour entry')


def w21_for(preset: str) -> str:
    """W-21 with its preset name (§13: "the preset name and verb vary")."""
    s = w("W-21")
    if not s.startswith("Purple "):
        raise SystemExit("e47d03kit: W-21's preset slot moved")
    return preset + s[len("Purple"):]


def accent_warning(preset: str, sc: Scale = S1) -> Node:
    """V-2: a warning glyph (color.status.warning.strong) before W-1, W-21 under it; text in color.text.primary;
    a polite live region announcing W-1 once on selection."""
    words = vbox("words", [text("W-1", w("W-1"), sc(BODY_STRONG), TEXT_1, w=CONTROLS_W - 40),
                           text("W-21", w21_for(preset), sc(BODY), TEXT_1, w=CONTROLS_W - 40)], {"gap": STACK_XS})
    return hbox("V-2 warning", [icon("glyph", "warning", WARN_STRONG, ICON), words],
                {"gap": INSET_SM, "align": "start"}, w=CONTROLS_W,
                note='role="status" aria-live="polite": W-1 announced once on selection; focus stays on the swatch')


def preview_name(theme: str, preset: str, palette: str = "default", density: str = "compact") -> str:
    """W-19 is the tile's name pattern (§13): its theme and accent words follow the current choice."""
    s = w("W-19")
    base = "Preview: dark theme, Blue accent, default chart palette, compact"
    if s != base:
        raise SystemExit("e47d03kit: W-19 changed")
    tw = {"dark": "dark", "light": "light", "hc": "high contrast"}[theme]
    return f"Preview: {tw} theme, {preset} accent, {palette} chart palette, {density}"


def tcell(name: str, chars: str, w_: int, *, typo: str = NUM, color: str = TEXT_1, numeric: bool = True,
          lead: Node | None = None, h: int = ROW_H) -> Node:
    """A table cell: 8 px inner padding a side, end-aligned numbers."""
    kids = ([lead] if lead else []) + ([text("value", chars, typo, color)] if chars.strip() else [])
    return hbox(name, kids, {"padX": INSET_SM, "gap": INSET_XS, "justify": "end" if numeric else "start"}, w=w_, h=h)


def trow(name: str, cells: list[Node], *, fill: str | None = None, o: dict[str, Any] | None = None,
         h: int = ROW_H) -> Node:
    return hbox(name, cells, {**({"fill": fill} if fill else {}), **(o or {})}, w=sum(c["w"] for c in cells), h=h)


def side_bar(tok: str) -> Node:
    return rect("ink", 3, 14, tok, {"radius": R_CONTROL})


TILE_COLS = (("Price", 96), ("Bid", 72), ("Ask", 72), ("Delta", 88))  # 328 = TILE_W - 2 x 16
LADDER_COLS = (("Bid", 104), ("Price", 120), ("Ask", 104))
POS_COLS = (("Symbol", 88), ("Size", 72), ("Entry", 88), ("PnL", 80))


def _hdr(cols: tuple[tuple[str, int], ...], sc: Scale) -> Node:
    return trow("header row", [tcell(f"th · {c}", c, wd, typo=sc(CAPTION), color=TEXT_2, numeric=c != "Symbol")
                               for c, wd in cols], h=ROW_H if sc.f == 1.0 else 32)


def preview_tile(theme: str, preset: str, palette: str = "default", *, selected_row: bool = False,
                 sc: Scale = S1) -> Node:
    """CMP-228 kind "theme" (§8.1): a footprint cell, a ladder row and a positions row under the current choice;
    role="img" named in words (W-19), its caption W-20; synthetic sample data (§8.4)."""
    for c in ("Price", "Bid", "Ask", "Delta", "Symbol", "Size", "Entry", "PnL"):
        copy_gap(f'"{c}": a PreviewTile column header (§5 names the surfaces and sides, §13 gives no header)')
    ik, rh = ink(palette), ROW_H if sc.f == 1.0 else 32
    p, b, a = next(x for x in WORLD.fp if x[0] == LAST)
    fp = trow("row · footprint", [tcell("price", px_(p), 96, typo=sc(NUM), h=rh),
                                  tcell("bid", str(b), 72, typo=sc(NUM), lead=side_bar(ik["bid"]), h=rh),
                                  tcell("ask", str(a), 72, typo=sc(NUM), lead=side_bar(ik["ask"]), h=rh),
                                  tcell("delta", signed(a - b), 88, typo=sc(NUM), h=rh)], fill=RAISED, h=rh)
    lp, lb, _la = next(x for x in WORLD.dom if x[1])
    lad = trow("row · ladder", [tcell("bid", str(lb), 104, typo=sc(NUM), lead=side_bar(ik["bid"]), h=rh),
                                tcell("price", px_(lp), 120, typo=sc(NUM), h=rh),
                                tcell("ask", "", 104, typo=sc(NUM), h=rh)], fill=RAISED, h=rh)
    size, entry = 0.1, LAST - 13.0
    pnl = round(size * (LAST - entry), 2)
    pos_o: dict[str, Any] = {}
    if selected_row:
        tok, _ex = swatch_token(theme, preset)
        if not _ex:
            live(f"PreviewTile positions row ({theme}): rebind its 2 px selected-row stroke from {tok} to "
                 f"{acc_primitive(theme, preset)} (the {preset} accent on non-text emphasis, §8.2)")
        pos_o = {"stroke": tok, "strokeWidth": THICK, "strokeAlign": "inner"}
    pos = trow("row · positions", [tcell("symbol", SYMBOL, 88, typo=sc(BODY), numeric=False, h=rh),
                                   tcell("size", f"+{size:.3f}", 72, typo=sc(NUM), h=rh),
                                   tcell("entry", px_(entry), 88, typo=sc(NUM), h=rh),
                                   tcell("pnl", signed(pnl, 2), 80, typo=sc(NUM), h=rh)],
               fill=SELECTED if selected_row else RAISED, o=pos_o, h=rh)
    blocks = [vbox("footprint cell", [_hdr(TILE_COLS, sc), fp], None, w=328),
              vbox("ladder row", [_hdr(LADDER_COLS, sc), lad], None, w=328),
              vbox("positions row", [_hdr(POS_COLS, sc), pos], None, w=328)]
    return vbox("CMP-228 PreviewTile", [text("caption · W-20", w("W-20"), sc(CAPTION), TEXT_2), *blocks],
                {"gap": STACK_MD, "pad": INSET_LG, "fill": CANVAS, "radius": R_CARD, "stroke": BORDER_SUBTLE,
                 "strokeWidth": HAIR, "strokeAlign": "inner"}, w=TILE_W,
                note=f'role="img" aria-label="{preview_name(theme, preset, palette)}"; not focusable; '
                     f'delta = ask - bid ({a} - {b}); PnL = size x (mark - entry) = {size} x {LAST - entry}')


# --- the SCR-116 page (§8.1): one h1, one FormSection per control, the PreviewTile docked right (stacked below at
# 640 CSS px), Reset last in the column.
@dataclass
class Choice:
    theme: str = "dark"
    preset: str = "Blue"
    palette: str = "default"
    invert: bool = False
    density: str = "Compact"
    text_size: str = "100 %"
    grid: str = "Subtle"
    match_system: bool = False
    focus: str | None = "Theme"  # the control holding focus (V-1: the first control on entry)
    warning: bool = False  # V-2
    selected_row: bool = False


def form_section(heading: str, kids: Iterable[Node | None], sc: Scale, w_: int) -> Node:
    return vbox(f"FormSection · {heading}", [text("heading", heading, sc(HEADING_SM), TEXT_1), *kids],
                {"gap": STACK_SM}, w=w_, note=f'role="group" aria-labelledby its heading "{heading}"')


def scr116_controls(ch: Choice, sc: Scale = S1, w_: int = CONTROLS_W) -> list[Node]:
    """The FormSections in Tab order (§8.1's table order), then Reset."""
    th = ch.theme
    pal_opts = [w("W-4"), w("W-5")]
    secs = [
        form_section("Theme", [segmented("CMP-062 theme", theme_values(), THEME_WORD[th], th, focused=ch.focus == "Theme",
                                         typo=sc(BODY_STRONG), seg_h=20 if sc.f == 1.0 else 28),
                               toggle(w("W-22"), ch.match_system, th, sc(BODY))], sc, w_),
        form_section(w_label("W-9"), [accent_picker(th, ch.preset, focused=ch.preset if ch.focus == "Accent" else None),
                                      accent_warning(ch.preset, sc) if ch.warning else None], sc, w_),
        form_section("Chart palette", [radio(pal_opts[0], ch.palette == "default", th, sc(BODY)),
                                       radio(pal_opts[1], ch.palette == "cvd-safe", th, sc(BODY))], sc, w_),
        form_section("Convention", [checkbox(w("W-6"), ch.invert, th, sc(BODY))], sc, w_),
        form_section("Density", [segmented("CMP-063 density", CONTROLS["Density"]["values"].split(" (")[0].split(" · "),
                                           ch.density, th, typo=sc(BODY_STRONG), seg_h=20 if sc.f == 1.0 else 28)],
                     sc, w_),
        form_section(w_label("W-11"), [segmented("text size", w_options("W-11"), ch.text_size, th,
                                                 typo=sc(BODY_STRONG), seg_h=20 if sc.f == 1.0 else 28)], sc, w_),
        form_section(w_label("W-10"), [segmented("grid lines", w_options("W-10"), ch.grid, th, typo=sc(BODY_STRONG),
                                                 seg_h=20 if sc.f == 1.0 else 28)], sc, w_),
    ]
    return secs


def scr116_page(ch: Choice, sc: Scale = S1, *, stacked: bool = False, w_: int | None = None) -> Node:
    """The content column: h1, the controls and the tile side by side (stacked: controls, tile, Reset)."""
    th = ch.theme
    h1 = text("h1", "Appearance", sc(HEADING_MD), TEXT_1, note="the one h1")
    tile = preview_tile(th, ch.preset, ch.palette, selected_row=ch.selected_row)  # §8.5: it keeps its last frame
    reset = button(w("W-18"), th, typo=sc(BODY_STRONG), focused=ch.focus == "Reset")
    if stacked:
        cw = (w_ or 640) - 2 * 16
        col = vbox("column", [h1, *scr116_controls(ch, sc, cw), tile, reset], {"gap": STACK_LG}, w=cw,
                   note="DOM order = visual order: controls, then the tile, then Reset (§8.5)")
        return vbox("SCR-116 content", [col], {"pad": INSET_LG, "fill": APP}, w=w_ or 640)
    controls = vbox("controls", [*scr116_controls(ch, sc), reset], {"gap": STACK_LG if sc.f == 1.0 and not ch.warning else STACK_MD},
                    w=CONTROLS_W)
    row = hbox("columns", [controls, tile], {"gap": INSET_XL, "align": "start"}, w=CONTROLS_W + COL_GAP + TILE_W)
    return vbox("SCR-116 content", [h1, row], {"gap": STACK_LG, "pad": INSET_XL, "fill": APP}, w=CONTENT_W)


# --- ink surfaces (§5, §6): panels on color.surface.canvas, each with its CMP-037 legend
PANEL_W, CANVAS_H = 384, 200
SIM_WORD = {"none": "colour", "grey": "greyscale", "deut": "deuteranopia", "prot": "protanopia", "trit": "tritanopia"}


def colour_words(palette: str) -> tuple[str, str]:
    """("Green", "Red") from W-4's parenthesis, ("Blue", "Orange") from W-5's."""
    m = re.search(r"\(([a-z]+) / ([a-z]+)\)", w("W-4" if palette == "default" else "W-5"))
    return m.group(1).capitalize(), m.group(2).capitalize()


def tri(name: str, up: bool, color: str = TEXT_1, typo: str = CAPTION, **kw: Any) -> Node:
    fallback("tri")
    return text(name, "▲" if up else "▼", typo, color, **kw)


def hatch(name: str, h: int, tok: str, w_: int = 8) -> Node:
    """pattern.hatch: 1 px stripes every 3 px over a w_ px strip (FALLBACKS['hatch'])."""
    fallback("hatch")
    return box(name, [rect(f"stripe-{i}", 1, h, tok, x=i * 3, y=0) for i in range(w_ // 3 + 1)], {"clip": True},
               w=w_, h=h)


def legend_row(label_: str, tok: str | None, *, glyph_up: bool | None = None, hatched: str | None = None) -> Node:
    """CMP-037 SwatchLegendItem: a size.icon swatch with the 1 px color.border.strong outline, the glyph when the
    colour encodes direction, the label in type.ui.caption, color.text.secondary. Swatch and glyph aria-hidden."""
    if hatched:
        sw = box("swatch", [hatch("hatch", 16, hatched, 16)], {"stroke": BORDER_STRONG, "strokeWidth": HAIR,
                                                               "strokeAlign": "inner", "clip": True}, w=16, h=16)
    else:
        sw = rect("swatch", 16, 16, tok, {"stroke": BORDER_STRONG, "strokeWidth": HAIR, "strokeAlign": "inner"})
    kids = [sw] + ([tri("glyph", glyph_up, TEXT_1)] if glyph_up is not None else []) + [
        text("label", label_, CAPTION, TEXT_2)]
    return hbox(f"legend · {label_}", kids, {"gap": INSET_SM}, h=20, note="li; swatch and glyph aria-hidden")


def legend(name: str, rows: list[Node], room: int = PANEL_W - 16) -> Node:
    """The legend's items packed into lines of at most `room` px (est.), in order."""
    lines: list[list[Node]] = [[]]
    used = 0.0
    for r in rows:
        wd = est_width(r)
        if lines[-1] and used + 12 + wd > room:
            lines.append([])
            used = 0.0
        used += (12 if lines[-1] else 0) + wd
        lines[-1].append(r)
    return vbox(f"CMP-037 legend · {name}", [hbox(f"line {i}", ln, {"gap": INSET_MD}, h=20)
                                             for i, ln in enumerate(lines, 1)], None,
                note=f'ul role="group" aria-label="{name} legend"')


def sign_row() -> Node:
    """W-16: the sign is the channel (no swatch: the row states the encoding in words)."""
    return hbox("legend · W-16", [text("label", w("W-16"), CAPTION, TEXT_2)], {"gap": INSET_SM}, h=20)


def side_rows(palette: str) -> list[Node]:
    ik, (cu, cd) = ink(palette), colour_words(palette)
    return [legend_row(f"{cu} {w('W-12')}", ik["buy"], glyph_up=True),
            legend_row(f"{cd} {w('W-13')}", ik["sell"], glyph_up=False)]


def panel(title: str, canvas_kids: list[Node], legend_node: Node | None, *, canvas_h: int = CANVAS_H,
          readout: str | None = None, w_: int = PANEL_W) -> Node:
    cv = box("canvas", canvas_kids, {"fill": CANVAS, "clip": True}, w=w_ - 16, h=canvas_h)
    kids = [text("title", title, LABEL, TEXT_2), cv]
    if readout:
        kids.append(text("readout", readout, NUM_SM, TEXT_1))
    if legend_node:
        kids.append(legend_node)
    return vbox(f"panel · {title}", kids, {"gap": STACK_SM, "pad": INSET_SM, "fill": RAISED, "radius": R_CARD},
                w=w_)


def footprint_panel(palette: str) -> Node:
    ik = ink(palette)
    cols = (("price", 96), ("bid", 96), ("ask", 96), ("delta", 72))
    hdr = [hbox(f"th · {c}", [text("value", c.capitalize(), CAPTION, TEXT_2)],
                {"padX": INSET_SM, "justify": "start" if c == "price" else "end"}, w=wd, h=20) for c, wd in cols]
    kids: list[Node] = [hbox("header row", hdr, None, w=360, h=20, x=0, y=0)]
    for i, (p, b, a) in enumerate(WORLD.fp):
        side = imbalance(b, a)
        cells = []
        for c, wd in cols:
            if c == "price":
                cells.append(tcell(c, px_(p), wd, typo=NUM_SM, color=ik["axis"], numeric=False, h=18))
                continue
            if c == "delta":
                cells.append(tcell(c, signed(a - b), wd, typo=NUM_SM, h=18))
                continue
            v = b if c == "bid" else a
            o: dict[str, Any] = {"padX": INSET_SM, "gap": INSET_XS, "justify": "end"}
            extra: list[Node] = []
            if side == c:
                o.update(stroke=ik["imbalance"], strokeWidth=THICK, strokeAlign="inner")
                extra = [hatch("hatch", 18, ik["imbalance"])]
            cells.append(hbox(c, [*extra, side_bar(ik[c]), text("value", str(v), NUM_SM, TEXT_1)], o, w=wd, h=18,
                              note=f"imbalance {max(a, b) / min(a, b):.1f} x" if side == c else None))
        kids.append(hbox(f"row {i + 1:02d}", cells, None, w=360, h=18, x=0, y=20 + i * 18))
    leg = legend("footprint", [*side_rows(palette), legend_row(w("W-15"), None, hatched=ik["imbalance"]),
                               sign_row()])
    copy_gap('"Price", "Bid", "Ask", "Delta": the footprint column headers at Compact (§5: "the column header at '
             'Compact"; §13 gives none)')
    return panel("Footprint cells", kids, leg)


def dom_panel(palette: str) -> Node:
    ik = ink(palette)
    cols = (("bid", 120), ("price", 120), ("ask", 120))
    hdr = [hbox(f"th · {c}", [text("value", c.capitalize(), CAPTION, TEXT_2)], {"padX": INSET_SM, "justify": "center"},
                w=wd, h=20) for c, wd in cols]
    kids: list[Node] = [hbox("header row", hdr, None, w=360, h=20, x=0, y=0)]
    vmax = max(max(b, a) for _p, b, a in WORLD.dom)
    for i, (p, b, a) in enumerate(WORLD.dom):
        cells = []
        for c, wd in cols:
            if c == "price":
                cells.append(hbox(c, [text("value", px_(p), NUM_SM, ik["axis"])], {"padX": INSET_SM,
                                                                                   "justify": "center"}, w=wd, h=15))
                continue
            v = b if c == "bid" else a
            bar = [rect("depth", max(2, round(56 * v / vmax)), 10, ik[c])] if v else []
            cells.append(hbox(c, [*bar, text("value", str(v), NUM_SM, TEXT_1)] if v else [],
                              {"padX": INSET_SM, "gap": INSET_XS, "justify": "end" if c == "bid" else "start"},
                              w=wd, h=15))
        kids.append(hbox(f"row {i + 1:02d}", cells, None, w=360, h=15, x=0, y=20 + i * 15))
    bp, bs, _ = next(x for x in WORLD.dom if x[1])
    copy_gap('the DOM readout "Bid · <price> · <size>": §5 asks for the side word in the readout; §13 gives no '
             'pattern (kit wording)')
    return panel("DOM ladder", kids, legend("DOM ladder", side_rows(palette)),
                 readout=f"Bid · {px_(bp)} · {bs}")


def heatmap_panel(palette: str) -> Node:
    """Bids below the price, asks above (W-14): each column's price line splits the rows; a cell's stop is its size
    bucket 1..5; zero cells are the canvas (color.heatmap.zero resolves to the canvas's primitive in dark and
    light)."""
    ik = ink(palette)
    cw, rh, x0 = 18, 13, 48
    kids: list[Node] = []
    rows = len(WORLD.hm)
    for ri in range(rows):
        cells = []
        for ci, stop in enumerate(WORLD.hm[ri]):
            mid = WORLD.hm_mid[ci]
            if ri == mid:
                cells.append(rect(f"price {ci:02d}", cw, 2, TEXT_1, x=ci * cw, y=rh // 2 - 1))
                continue
            if stop == 0:
                continue
            side = "ask" if ri < mid else "bid"
            cells.append(rect(f"c{ci:02d}", cw, rh, ik[f"hm.{side}.{stop}"], x=ci * cw, y=0))
        kids.append(box(f"hm row {ri:02d}", cells, None, w=len(WORLD.hm[ri]) * cw, h=rh, x=x0, y=8 + ri * rh))
    kids += [text("axis · asks", "asks", CAPTION, ik["axis"], x=4, y=8),
             text("axis · bids", "bids", CAPTION, ik["axis"], x=4, y=8 + (rows - 1) * rh)]
    ramp = []
    for side in ("bid", "ask"):
        sw = [rect(f"stop {i}", 20, 12, ik[f"hm.{side}.{i}"], {"stroke": BORDER_STRONG, "strokeWidth": HAIR,
                                                              "strokeAlign": "inner"}) for i in range(1, 6)]
        ramp.append(hbox(f"ramp · {side}", [text("side", side.capitalize(), CAPTION, TEXT_2, w=28), *sw,
                                            text("more", "1 → 5: more size", CAPTION, TEXT_2)],
                         {"gap": INSET_XS}, h=20))
    copy_gap('"asks" / "bids" (axis side words) and "1 → 5: more size" (the CMP-113 ramp row): §5 / §7.3 give the '
             'rule ("bids below the price, asks above"; "twice as bright reads as more size"), §13 no string')
    leg = legend("heatmap", [hbox("legend · W-14", [text("label", w("W-14"), CAPTION, TEXT_2)], h=20), *ramp])
    return panel("Heatmap", kids, leg, canvas_h=8 + rows * rh + 8)


def profile_panel(palette: str) -> Node:
    ik = ink(palette)
    poc, va_top, va_bot = value_area(WORLD.prof)
    hv, lv = nodes_hvn_lvn(WORLD.prof)
    vmax = max(v for _p, v in WORLD.prof)
    kids: list[Node] = []
    for i, (p, v) in enumerate(WORLD.prof):
        tok = ik["poc"] if i == poc else ik["va"] if va_top <= i <= va_bot else ik["bar"]
        y = 6 + i * 12
        kids.append(text(f"price {i:02d}", px_(p), NUM_SM, ik["axis"], x=4, y=y))
        kids.append(rect(f"bar {i:02d}", max(4, round(200 * v / vmax)), 9, tok, x=88, y=y + 1))
        tag = "POC" if i == poc else "HVN" if i in hv else "LVN" if i in lv else None
        if tag:
            kids.append(text(f"label {i:02d}", tag, CAPTION, TEXT_1, x=88 + round(200 * v / vmax) + 6, y=y))
    kids.append(rect("VA bracket", 2, (va_bot - va_top + 1) * 12, TEXT_2, x=344, y=6 + va_top * 12))
    kids.append(text("VA label", "VA", CAPTION, TEXT_1, x=328, y=6 + va_top * 12))
    leg = legend("profile", [hbox("legend · W-17", [text("label", w("W-17"), CAPTION, TEXT_2)], h=20),
                             legend_row("POC", ik["poc"]), legend_row("VA", ik["va"]), legend_row("Volume", ik["bar"])])
    copy_gap('"Volume": the profile bar\'s legend row (§3.2 "profile bar (HVN / LVN by length)"; §13 has W-17 only)')
    return panel("Profile", kids, leg, canvas_h=6 + len(WORLD.prof) * 12 + 6,
                 readout=f"POC {px_(WORLD.prof[poc][0])} · VA {px_(WORLD.prof[va_bot][0])}-{px_(WORLD.prof[va_top][0])}")


def cvd_panel(palette: str) -> Node:
    """The CVD pane: the running delta above or below its zero; a mark is buy ink when the line rises, sell ink when
    it falls (§3.2 "CVD line up / down"); signed readout (§5)."""
    ik = ink(palette)
    fallback("line")
    vals = WORLD.cvd
    lo, hi = min(min(vals), 0), max(max(vals), 0)
    h = 160
    yz = round(8 + (hi - 0) / (hi - lo) * (h - 16))
    kids: list[Node] = [rect("zero", 340, 1, BORDER_STRONG, x=8, y=yz),
                        text("zero label", "0", NUM_SM, ik["axis"], x=8, y=yz - 14)]
    prev, marks = 0, []
    for i, v in enumerate(vals):
        y = round(8 + (hi - v) / (hi - lo) * (h - 16))
        marks.append(rect(f"m{i:02d}", 4, 4, ik["buy"] if v >= prev else ik["sell"], x=24 + i * 8, y=y - 2))
        prev = v
    kids.append(box("line", marks, None, w=340, h=h, x=0, y=0))
    leg = legend("CVD pane", [*side_rows(palette), sign_row()])
    return panel("CVD pane", kids, leg, canvas_h=h, readout=f"CVD {signed(vals[-1])}")


# live-check fold: bubble 04 and its glyph move up 24 px, as drawn on 06, 07 (x 3) and 08's cvd-safe frame
BUBBLE_LIFT = (4, 24)


def bubbles_panel(palette: str) -> Node:
    """Candles with hollow up / filled down bodies, ▲ below the bar for a buy marker and ▼ above for a sell (§5), and
    the trade bubbles with ▲ / ▼ inside, sized by trade size."""
    ik = ink(palette)
    cs = WORLD.candles
    pmin, pmax = min(c[2] for c in cs) - 2, max(c[1] for c in cs) + 2
    h = 180

    def y(p: float) -> int:
        return round(8 + (pmax - p) / (pmax - pmin) * (h - 16))

    kids: list[Node] = []
    for i, (o, hi, lo, c) in enumerate(cs):
        x = 16 + i * 28
        up = c >= o
        kids.append(rect(f"wick {i:02d}", 1, max(1, y(lo) - y(hi)), ik["wick"], x=x + 5, y=y(hi)))
        body_o = {"stroke": ik["up"], "strokeWidth": HAIR, "strokeAlign": "inner"} if up else {"fill": ik["down"]}
        kids.append(rect(f"body {i:02d}", 11, max(2, abs(y(o) - y(c))), None, body_o, x=x, y=min(y(o), y(c))))
    for j, (si, p, sz, side) in enumerate(WORLD.trades[:6]):
        ci = min(len(cs) - 1, si * len(cs) // 40)
        d = {3: 12, 8: 16, 15: 20, 30: 26, 60: 32}[sz]
        bx, by = 16 + ci * 28 + 5 - d // 2, max(0, min(h - d, y(cs[ci][3]) - d // 2))
        if j == BUBBLE_LIFT[0]:  # the live check's fold: the seeded bubble 04 sat on 03 and hid its sign (§5)
            by -= BUBBLE_LIFT[1]
        kids.append(ellipse(f"bubble {j:02d}", d, d, {"fill": ik["buy" if side == "buy" else "sell"]}, x=bx, y=by))
        kids.append(tri(f"bubble glyph {j:02d}", side == "buy", TEXT_INV, x=bx + d // 2 - 4, y=by + d // 2 - 7))
    for j, (si, side) in enumerate(((3, "buy"), (8, "sell"))):
        o, hi, lo, c = cs[si]
        kids.append(tri(f"marker {j}", side == "buy", ik["buy" if side == "buy" else "sell"], CAPTION,
                        x=16 + si * 28 + 1, y=y(lo) + 4 if side == "buy" else y(hi) - 16))
    return panel("Bubbles and chart trade markers", kids, legend("bubbles", side_rows(palette)), canvas_h=h)


# --- §7.2 rows, §7.3 rows and the hand-off's token diff (§C.2)
DE_ROWS = {(plain(c[0]), plain(c[1])): (c, ln) for ln, c in table_after("### 7.2 Discriminability per pair")}
RAMP_ROWS = {(plain(c[0]), plain(c[1])): (c, ln) for ln, c in table_after("### 7.3 Ramp order")}
DIFF = {plain(c[0]): dict(set=plain(c[1]), token=plain(c[2]), old=plain(c[3]), new=plain(c[4]), line=ln)
        for ln, c in table_after("### §C.2 The token diff", HANDOFF_LINES)}
_SIM_COL = {"none": 2, "deut": 3, "prot": 4, "trit": 5, "grey": 6}


def de_line(pair: str, theme: str, sim: str) -> str:
    c, ln = DE_ROWS[(pair, theme)]
    return f"{pair}, {theme}: ΔE {plain(c[_SIM_COL[sim]])} in {SIM_WORD[sim]} ({plain(c[7])}; §7.2 L{ln})"


def ramp_line(ramp: str, theme: str) -> str:
    c, ln = RAMP_ROWS[(ramp, theme)]
    sims = ", ".join(f"{s} {plain(c[_SIM_COL[s]])}" for s in ("none", "deut", "prot", "trit", "grey"))
    return f"{ramp} ({theme}): {sims}; smallest L* step {plain(c[7])}; {plain(c[8])} (§7.3 L{ln})"


def sim_hex(sim: str, token: str) -> str:
    return val("SIM", f"dark/{sim}/{token}")


def hex_key(sim: str, tokens: Iterable[str]) -> list[str]:
    """§7.4's expected hexes after the export projection (dark), for the tokens the frame binds."""
    out = []
    for t in tokens:
        try:
            out.append(f"{t} → {sim_hex(sim, t)} (none {sim_hex('none', t)})")
        except KeyError:
            continue
    return out


SIM74_DEFAULT = ("color.buy.default", "color.sell.default", "color.footprint.imbalance", "color.heatmap.bid.5",
                 "color.heatmap.ask.5")
SIM74_CVD = ("color.cvd.buy", "color.cvd.sell", "color.cvd.imbalance", "color.cvd.heatmap.bid.5",
             "color.cvd.heatmap.ask.5")


def light_plus_stop(side: str, stop: int) -> str:
    """Board 10 (after D03-D7 … D03-D14): the base light token that holds, today, the primitive the diff assigns to
    stop `stop`; .3 maps to itself (§C.2's footnote)."""
    tok = f"color.cvd.heatmap.{side}.{stop}"
    row = next((r for r in DIFF.values() if r["token"] == tok and r["set"] == "semantic-light"), None)
    if row is None:
        return tok
    want = row["new"].strip("{}")
    hits = [f"color.cvd.heatmap.{side}.{j}" for j in range(1, 6)
            if resolves_to("light", f"color.cvd.heatmap.{side}.{j}") == want]
    if len(hits) != 1:
        raise SystemExit(f"e47d03kit: {tok}: {want} held by {hits}")
    return hits[0]


# --- frame bodies for the ink boards
def ink_header(title: str, sim: str, palette: str, *, extra: str | None = None) -> Node:
    lines = [text("title", title, HEADING_SM, TEXT_1), text("data", DATA_LINE, CAPTION, TEXT_2)]
    if sim != "none":
        fallback("projection")
        lines.append(text("projection", f"Export projection: {SIM_WORD[sim]} (§7.1); the frame binds the "
                                        f"{'CVD-safe' if palette == 'cvd-safe' else 'default'} palette's tokens",
                          CAPTION, TEXT_2))
    if extra:
        lines.append(text("extra", extra, CAPTION, TEXT_2))
    return vbox("frame header", lines, {"gap": STACK_XS}, w=FRAME_W - NAV_W - 32)


def evidence(title: str, lines: list[str], w_: int = PANEL_W) -> Node:
    return vbox(f"evidence · {title}", [text("title", title, LABEL, TEXT_2, w=w_ - 24),
                                        *[text(f"line {i}", ln, CAPTION, TEXT_1, w=w_ - 24)
                                          for i, ln in enumerate(lines, 1)]],
                {"gap": STACK_XS, "pad": INSET_MD, "fill": RAISED, "radius": R_CARD}, w=w_)


def ink_frame(fid: str, theme: str, header: Node, items: list[Node], per_row: int = 3) -> Node:
    rows = [hbox(f"band {i // per_row + 1}", items[i:i + per_row], {"gap": INSET_LG, "align": "start"})
            for i in range(0, len(items), per_row)]
    content = vbox("workspace", [header, *rows], {"gap": STACK_SM, "pad": INSET_LG, "fill": APP},
                   w=FRAME_W - NAV_W)
    need = est_height(content)
    if need > BODY_H:
        raise ValueError(f"{fid}: workspace about {need:.0f} px > {BODY_H}")
    return window(frame_name(fid), theme, content, settings=False)


# --- board 08: CMP-074 / CMP-075 (§9)
def env_glyph(env: str) -> Node:
    """icon/env-live: a filled dot in a ring; icon/env-demo: an outline dot (E11-D02 CR-7; FALLBACKS['env-glyph'])."""
    fallback("env-glyph")
    tok = ENV_LIVE if env == "live" else ENV_DEMO
    if env == "live":
        kids = [ellipse("ring", 14, 14, {"stroke": tok, "strokeWidth": HAIR, "strokeAlign": "inner"}, x=1, y=1),
                ellipse("dot", 8, 8, {"fill": tok}, x=4, y=4)]
    else:
        kids = [ellipse("outline dot", 10, 10, {"stroke": tok, "strokeWidth": THICK, "strokeAlign": "inner"}, x=3, y=3)]
    return box(f"glyph · {env}", kids, w=16, h=16, note=f"icon/env-{env}; aria-hidden")


def env_badge(env: str, *, banner: bool = False, w_: int | None = None) -> Node:
    """CMP-075 (badge) or CMP-074 (banner): the word in color.text.primary on color.surface.raised, the glyph, the
    2 px env border (§9; E11-D02 L415). Named "Trading environment: Live" (W-3) / its DEMO form."""
    fallback("weight")
    word = "LIVE" if env == "live" else "DEMO"
    tok = ENV_LIVE if env == "live" else ENV_DEMO
    name_ = w("W-3") if env == "live" else w("W-3").replace("Live", "Demo")
    kids = [env_glyph(env), text("word", word, BODY_STRONG, TEXT_1)]
    o = {"gap": INSET_SM, "padX": INSET_MD if banner else INSET_SM, "fill": RAISED, "stroke": tok, "strokeWidth": THICK,
         "strokeAlign": "inner", "radius": R_CONTROL if banner else R_BADGE}
    cmp = "CMP-074 EnvBanner" if banner else "CMP-075 EnvBadgeLocal"
    return hbox(f"{cmp} · {word}", kids, o, w=w_, h=40 if banner else 24,
                note=f'{"role=status" if banner else "role=img"} aria-label="{name_}"')


# --- boards 09 / 10: the data-ink ramps (§3.2, §3.3, §3.4, §7.3)
def ink_chip(label_: str, tok: str, ratio: str | None, *, w_: int = 88, sub: str | None = None) -> Node:
    kids = [rect("chip", w_, 40, tok, {"stroke": BORDER_STRONG, "strokeWidth": HAIR, "strokeAlign": "inner"}),
            text("label", label_, CAPTION, TEXT_1, w=w_)]
    if ratio:
        kids.append(text("ratio", ratio, NUM_SM, TEXT_1, w=w_))
    if sub:
        kids.append(text("sub", sub, CAPTION, TEXT_2, w=w_))
    return vbox(f"chip · {label_}", kids, {"gap": STACK_XS}, w=w_, note=tok)


def ratio_s(theme: str, fg: str, bar: str = "3") -> str:
    return f"{cr(theme, fg, CANVAS)}:1 on the canvas (bar {bar})"


def ramp_group(title: str, chips: list[Node], verdict: str, w_: int) -> Node:
    return vbox(f"group · {title}", [text("title", title, LABEL, TEXT_2),
                                     hbox("chips", chips, {"gap": INSET_SM, "align": "start"}),
                                     text("verdict", verdict, CAPTION, TEXT_1, w=w_ - 24)],
                {"gap": STACK_SM, "pad": INSET_MD, "fill": RAISED, "radius": R_CARD}, w=w_)


# --- sections (<= SECTION_RAW_BUDGET raw bytes each; the E08-D09 kit's packer, copied), lint, write, pack
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


def validate(path: Path) -> tuple[int, str]:
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(path), "--components", str(COMPONENTS),
                          "--tokens", str(TOKENS_FILE)], capture_output=True, text=True, timeout=120, check=False)
    lines = (res.stdout + res.stderr).strip().splitlines()
    return res.returncode, "\n".join(lines)



# --- the annotation column, the board, the sheet
def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    """The ONE 400 px column: title, a "Board" block (§0's Draws, theme, twin, export, the data line), one block per
    frame, footer "page <PAGE> · board NN · r1"."""
    b = BOARDS[nn]
    head = [f"§0 L{b.line}: {b.draws}",
            f"Theme: {b.theme}" + (f" (light twin of board {b.twin:02d}: same frames and words)" if b.twin else ""),
            f"Frames (hand-off §G L{FRAME_LINES[nn][1]}): " + "; ".join(b.frames),
            f"Export: {b.export}", DATA_LINE, *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


def layout(frames: list[Node], per_row: int | None = None) -> list[Node]:
    k = per_row or (2 if len(frames) in (2, 4) else MAX_PER_ROW)
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


# the live check's root heights: the annotation end + MARGIN as Penpot measured them (build-notes, "Live-check fold");
# the estimate above is the floor a board without a measurement keeps
MEASURED_H = {1: 1039, 6: 1901, 7: 1448}


def board(nn: int, frames: list[Node], ann: Node, *, per_row: int | None = None) -> tuple[dict[str, Any], list[Node]]:
    """The sheet's root (board name, grid x/y, color.surface.app, clip) hugging its frames + the ONE annotation column
    + MARGIN; a "state: <frame id>" caption 28 px above each frame; the data line under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f) for f in b.frames]
    got = [f["name"] for f in frames]
    if got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != §G {want}")
    if any(f["w"] != FRAME_W or f["h"] != FRAME_H for f in frames):
        raise ValueError(f"board {nn:02d}: every frame is a {FRAME_W} x {FRAME_H} window (§0)")
    if "/" in b.name[len(f"E47-D03 / {nn:02d} "):]:
        raise ValueError(f"board {nn:02d}: '/' after the prefix in {b.name!r}")
    placed = layout(frames, per_row)
    fid = dict(zip(want, b.frames))
    caps = [text(f"caption {i:02d}", f"state: {fid[f['name']]}", CAPTION, TEXT_3, x=f["x"], y=f["y"] - 28)
            for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · data", DATA_LINE, CAPTION, TEXT_2, x=MARGIN, y=bottom + 24)]
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    h = int(math.ceil((max(bottom + 24 + 16, MARGIN + ah) + MARGIN) / 8) * 8)
    if nn in MEASURED_H:  # the live-measured annotation end + MARGIN (it must still clear the frames and the footer)
        if MEASURED_H[nn] < bottom + 24 + 14 + MARGIN:
            raise ValueError(f"board {nn:02d}: measured h {MEASURED_H[nn]} < footer end {bottom + 24 + 14} + {MARGIN}")
        h = MEASURED_H[nn]
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch: trim the annotations")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root (h {h}); "
         f"raise the root's h to its end + {MARGIN} if not")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


def write_sheet(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
                per_row: int | None = None, out_dir: Path = CAP_DIR, name: str | None = None) -> Path:
    """Assemble board nn, split into sections, merge notes, write out_dir/NN-<slug>.json, run the validator (tokens +
    components); RuntimeError unless it exits 0 and the kit lint and the banned scan are clean. Clears NOTES."""
    b = BOARDS[nn]
    out_dir = out_dir.resolve()
    if out_dir not in (CAP_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    root, nodes = board(nn, frames, ann, per_row=per_row)
    if b.theme == "mixed":
        live(f"theme: board {nn:02d} is mixed (§0): export each frame under the set its name ends with (dark; light; "
             f"high contrast = dark + semantic-hc; cvd-safe = dark) and composite them in place into {b.export}; read "
             f"back color.surface.raised behind each LIVE word as that set's value")
    elif b.theme != "dark":
        live(f"theme: activate the {b.theme} token set before exporting board {nn:02d}; read back one bound fill "
             f"(color.surface.canvas) as the {b.theme} value")
    live(f"export {b.export}: every frame is {FRAME_W} x {FRAME_H}; record the board id and the PNG size in §0")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {SPEC.name} md5 {SPEC_MD5[SPEC.name][:8]} and hand-off {HANDOFF.name} md5 "
                         f"{SPEC_MD5[HANDOFF.name][:8]} (§0 L{b.line}; hand-off §G L{FRAME_LINES[nn][1]})")
    sheet = {"board": root, "sections": sections_for(nodes), "export": b.export,
             "notes": {k: list(v) for k, v in NOTES.d.items()}}
    NOTES.reset()
    banned = _scan_banned(sheet)
    if bad or banned:
        raise RuntimeError(f"board {nn:02d}: lint {bad[:8]} banned {banned}")
    if not sheet["notes"]["live_checks"]:
        raise RuntimeError(f"board {nn:02d}: notes.live_checks is empty")
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
            f"theme {b.render_theme}.")


def write_md(nn: int, sheet_path: Path, *, summary: str = "") -> Path:
    b = BOARDS[nn]
    sp = Path(sheet_path).resolve()
    sh = json.loads(sp.read_text(encoding="utf-8"))
    rc, msg = validate(sp)
    x, y = grid_xy(nn)
    out = [f"# {b.name}", "", md_line3(nn), "",
           summary or f"Board {nn:02d} of {len(BOARDS)} (§0 L{b.line}: {b.draws}). Grid ({x}, {y}); "
                      f"{sh['board']['w']} x {sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".",
           "", "## Frames", ""]
    out += [f"- `{frame_name(f)}` (§G: `{f}`)" for f in b.frames]
    out += ["", "## Validator and size", "", f"- `{msg.splitlines()[-1] if msg else ''}` (exit {rc})",
            f"- {len(sh['sections'])} sections, {len(json.dumps(sh))} bytes", ""]
    for kd in ("live_checks", "ambiguities", "spec_gaps", "deviations", "copy_keys", "copy_gaps", "fallbacks",
               "sources", "tokens"):
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


def build(nn: int, frames: list[Node], blocks: list[tuple[str, list[str]]], *, board_lines: Iterable[str] = (),
          per_row: int | None = None, notes: dict[str, Iterable[str]] | None = None) -> tuple[Path, Path, Path]:
    """The generators' one call: annotations, sheet, md, packed sheet."""
    ann = annotations(nn, blocks, board_lines=board_lines)
    p = write_sheet(nn, frames, ann, per_row=per_row, notes=notes)
    return p, write_md(nn, p), pack_sheet(p)


# --- annotation helpers shared by the generators
def variant_lines(v: str) -> list[str]:
    r = VARIANTS[v]
    return [f"{v} {r['variant']} (§8.3 L{r['line']}): {r['surface']}",
            f"Copy: {r['copy']}. Tokens: {r['tokens']}. Roles: {r['roles']}",
            f"Keyboard / focus: {r['keyboard']}. Announcement: {r['announce']}. Analytics: {r['analytics']}. "
            f"Data confidence: {r['confidence']}"]


def cr_line(role: str, section: str, themes: Iterable[str]) -> str:
    """One §3.x row: its role, pair and the figures for the given themes, verdict, cited by line."""
    for ln, c in table_after(section):
        if plain(c[0]) == role:
            fg, bg = plain(c[1]), plain(c[2])
            cols = {"dark": 4, "light": 5, "hc": 6, "dark+": 4, "light+": 5, "hc+": 6}
            figs = ", ".join(f"{t} {plain(c[cols[t]])}" for t in themes)
            return f"{role}: {fg} on {bg}, {figs} (bar {plain(c[3])}; {plain(c[7])}; §{section.split(' ', 2)[1]} L{ln})"
    raise LookupError(role)


def keys_line() -> str:
    rows = [f"{k}: {v['keys']}" for k, v in CONTROLS.items()]
    return f"Keyboard (§8.1 L{CONTROLS['Theme']['line']}…): Tab order top to bottom; " + "; ".join(rows)


# --- self-test: python3 -I -B e47d03kit.py selftest
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), "spec md5 pins")
    check(len(BOARDS) == 10 and int(VAL["COUNT:boards"]) == len(BOARDS), "§0 board count = COUNT:boards")
    check(sum(b.theme == "light" for b in BOARDS.values()) == int(VAL["COUNT:boards.light"]), "light boards count")
    check(all(BOARDS[n].frames for n in BOARDS), "§G frames for every board")
    check(all("/" not in b.name[len(f"E47-D03 / {n:02d} "):] for n, b in BOARDS.items()), "no '/' after the prefix")
    check(len(COPY) == int(re.search(r"(\d+) strings", plain("\n".join(SPEC_LINES))).group(1)), "§13 string count")
    toks = set(_TS.get("semantic-dark", {})) | set(_TS.get("primitives", {}))
    used = [v for k_, v in globals().items() if k_.isupper() and isinstance(v, str) and re.match(r"(color|type|space|"
                                                                                               r"size|radius|border)\.", v)]
    check(all(t in toks for t in used), f"kit tokens exist: {[t for t in used if t not in toks]}")
    check(all(t in toks for pal in ("default", "cvd-safe") for t in ink(pal).values()), "ink tokens exist")
    check(not BANNED.search(json.dumps([b.name for b in BOARDS.values()])), "banned scan")
    for th in ("dark", "light", "hc"):
        for p in PRESETS:
            acc_warns(th, p)
    check([light_plus_stop("bid", i) for i in range(1, 6)] == [f"color.cvd.heatmap.bid.{6 - i}" for i in range(1, 6)],
          "the light+ CVD ramp reverses the base mapping")
    check(cr("light+", "color.cvd.heatmap.bid.1", CANVAS) == cr("light", "color.cvd.heatmap.bid.5", CANVAS),
          "light+ stop 1 = light stop 5")
    # a sample sheet end to end (board 04's frame), validated, md, packed, counted
    SELFTEST_DIR.mkdir(parents=True, exist_ok=True)
    ch = Choice(theme="light")
    fr = window(frame_name(BOARDS[4].frames[0]), "light", scr116_page(ch))
    ann = annotations(4, [(BOARDS[4].frames[0], variant_lines("V-4"))])
    try:
        p = write_sheet(4, [fr], ann, out_dir=SELFTEST_DIR, name="00-selftest.json")
        pk = pack_sheet(p, SELFTEST_DIR)
        check(json.loads(pk.read_text())["compactOf"]["file"] == p.name, "packed source is the bare name")
        sh = json.loads(p.read_text())
        check('"t": "inst"' not in json.dumps(sh), "no inst")
    except Exception as e:  # noqa: BLE001 - reported as a failure
        fails.append(f"sample sheet: {e}")
    for f in fails:
        print("FAIL", f)
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
