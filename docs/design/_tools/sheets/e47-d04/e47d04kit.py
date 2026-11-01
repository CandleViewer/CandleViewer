"""E47-D04 (#1303) board kit: the focus model (landmarks, the region ring, five archetypes, the dense-grid escape
hatch, the focus ring, retention under live data, the dialog contract), ten boards as cvsheet JSON sheets for the
per-set Penpot file "E47-D04 boards", page "E47-D04 — Focus model" (spec §0).

Offline only. Spec (binding; every string, frame and figure comes from it): docs/design/E47/E47-D04.md and
E47-D04-handoff.md as this checkout commits them (read by repo-relative path; md5-pinned in SPEC_MD5: the kit
refuses drifted bytes; after a spec edit re-check every L<n> cite, re-pin and rebuild). The one
recorded input, the instrument's tick size, is read from the recorded fixture FIXTURE (md5-pinned too; §H: "only the
instrument's tick size comes from a recorded fixture").
Registry: §0's board table (BOARDS) and §H's frame table (FRAME_PLAN) are parsed; §7.6's measured ratios
(CONTRAST, from the spec's own tool output in the <!--=CONTRAST:...--> slots), §15's copy deck (COPY) and §18.2's
G-ledger (GROWS) likewise. Nothing measured is typed here.

Pipeline (one generator per board, gen/gen_NN.py):
    frames = [...]                                    # one 1280 x 800 frame per FRAME_PLAN entry, in order
    ann = annotations(nn, [frame_block(...), ...])    # the ONE 400 px column
    p = write_sheet(nn, frames, ann)                  # build/NN-<slug>.json (untracked), validator exit 0 or raises
    write_md(nn, p)                                   # NN-<slug>.md here and in build/, line 3 = the render line
    pack_sheet(p)                                     # v4/NN-<slug>.json, compactOf.file = the bare name + its sha256
Twins: boards 09 (light) and 10 (hc) call board 08's build(theme); every fill is a token, the theme is set at export.
Self-test: python3 -I -B e47d04kit.py selftest   (one sample frame into build/selftest/, validated, packed)
Rebuild all ten: BUILD.md in this folder.

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (§H's "<archetype>/<state>" frame names are
drawn with U+2215); no local path, host or agent name anywhere in a sheet (BANNED); packed sections <= 9 KB; table
cells carry 8 px inner padding a side.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
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
SPEC = REPO / "docs/design/E47/E47-D04.md"
HANDOFF = REPO / "docs/design/E47/E47-D04-handoff.md"
FIXTURE_REL = "packages/fixtures/bybit/2026-10-05/rest/instruments_before.json"
FIXTURE = REPO / FIXTURE_REL
# spec and hand-off re-pinned at the boards' as-built record (§0, the §C and §H rows edited in place): every L<n>
# and §H cite on the ten boards reads the same text as when they were drawn
SPEC_MD5 = {SPEC.name: "8a3e30afc96f7c03eb9792dfdd730d06", HANDOFF.name: "d6454712e65839249d15ceb99f5f3ad1",
            FIXTURE.name: "edd9dd2a060c51bd4bd1450307728ddf"}

FILE_NAME = "E47-D04 boards"
REV = "r1"
PITCH_X, PITCH_Y = 6000, 3200  # grid: x = ((NN-1) mod 5) * 6000, y = floor((NN-1)/5) * 3200
MARGIN = 80  # root margin and frame gutters (positions, not a flex gap)
ANN_W = 400  # the one annotation column, outside the frames
ANN_TEXT_W = ANN_W - 32
FRAME_W, FRAME_H = 1280, 800
MAX_PER_ROW = 3
SECTION_RAW_BUDGET = 9000  # raw section JSON; the packed section is smaller
PACKED_MAX = 9216  # "each packed section <= ~9 KB"
SLASH = "∕"  # "∕": §H's "<archetype>/<state>" in a node name ("/" splits section paths)
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode() + r"\b", re.I)


def _read(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").split("\n")


def spec_md5_ok() -> dict[str, bool]:
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() == SPEC_MD5[p.name] for p in (SPEC, HANDOFF, FIXTURE)}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:  # every L<n> cite and every parsed string assumes the pinned bytes
    raise SystemExit(f"e47d04kit: spec text drifted from SPEC_MD5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
SPEC_LINES = _read(SPEC)
HANDOFF_LINES = _read(HANDOFF)
SPEC_TEXT = "\n".join(SPEC_LINES)


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
    """The spec line a board cites: looked up, never typed as a number."""
    return find_line(needle, start=start)


def HL(needle: str, start: int = 1) -> int:
    return find_line(needle, HANDOFF_LINES, start)


def _plain(s: str) -> str:
    """A table cell as words: placeholder comments dropped, backticks removed, spaces collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<!--[^>]*-->", "", s, flags=re.DOTALL).replace("`", "")).strip()


# --- the spec's tool-filled figures: "7.05<!--=CONTRAST:pair.dark-->", "10<!--=COUNT:boards-->"
CONTRAST: dict[str, str] = {k: v for v, k in re.findall(r"([0-9]+(?:\.[0-9]+)?)<!--=CONTRAST:([\w.-]+)-->",
                                                        SPEC_TEXT, re.DOTALL)}
COUNT: dict[str, str] = {k: v for v, k in re.findall(r"([0-9]+)<!--=COUNT:([\w.-]+)-->", SPEC_TEXT, re.DOTALL)}


def ratio(key: str) -> str:
    """A measured ratio as the spec's tool wrote it ("7.05"); raises when the slot is absent."""
    if key not in CONTRAST:
        raise KeyError(f"CONTRAST:{key} is not in the spec")
    return CONTRAST[key]


# --- §0: the ten boards (registry parsed from the spec); §H: their frames
PAGE = re.search(r"page `([^`]+)`", SPEC_LINES[L("Penpot: the file `E47-D04 boards`") - 1]).group(1)  # type: ignore


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E47-D04 / 01 landmarks-ring"
    slug: str
    draws: str
    theme: str  # dark | light | hc
    line: int  # §0 line
    twin: int | None = None  # light / high-contrast twin of board N

    @property
    def export(self) -> str:
        return f"docs/design/E47/img/E47-D04-{self.nn:02d}-{self.slug}.png"

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"

    @property
    def base(self) -> int:
        return self.twin or self.nn


_B_ROW = re.compile(r"^\|\s*(\d{2})\s*\|\s*`(E47-D04 / (\d{2}) ([a-z0-9-]+))`\s*\|([^|]*)\|\s*(dark|light|hc)\s*\|"
                    r"(?:[^|]*\|)?\s*$")
_TWIN = re.compile(r"^(light|high-contrast) twin of (\d{2})\b")


def _parse_boards() -> dict[int, Board]:
    s0 = L("## 0. Status, artefacts and the boards")
    s1 = L("## 1. Purpose", start=s0)
    out: dict[int, Board] = {}
    for i in range(s0, s1):
        m = _B_ROW.match(SPEC_LINES[i - 1])
        if not m:
            continue
        nn = int(m.group(1))
        if int(m.group(3)) != nn:
            raise ValueError(f"§0 L{i}: row {nn} names board {m.group(3)}")
        draws = _plain(m.group(5))
        tw = _TWIN.match(draws)
        if tw and {"light": "light", "high-contrast": "hc"}[tw.group(1)] != m.group(6):
            raise ValueError(f"§0 L{i}: twin kind {tw.group(1)} vs theme {m.group(6)}")
        out[nn] = Board(nn, m.group(2), m.group(4), draws, m.group(6), i, int(tw.group(2)) if tw else None)
    return out


BOARDS = _parse_boards()
TWINS = {nn: b.twin for nn, b in BOARDS.items() if b.twin}  # {9: 8, 10: 8}
NOT_DRAWN_LINE = L("**Not drawn (the text is binding)**")


def _parse_frames() -> dict[int, tuple[str, ...]]:
    """§H: board -> its frame names as written ("shell/landmarks · dark", ...)."""
    a = HL("## §H The board plan")
    out: dict[int, tuple[str, ...]] = {}
    for i in range(a, len(HANDOFF_LINES)):
        ln = HANDOFF_LINES[i]
        if ln.startswith("## ") and i > a:
            break
        c = _cells(ln) if ln.startswith("|") else []
        if c and re.fullmatch(r"\d{2}", c[0]):
            out[int(c[0])] = tuple(re.findall(r"`([^`]+)`", c[1]))
    return out


FRAME_PLAN = _parse_frames()
H_LINE = HL("## §H The board plan")


def frames_of(nn: int) -> tuple[str, ...]:
    return FRAME_PLAN[nn]


def frame_name(fid: str) -> str:
    """The Penpot frame name: §H's "<archetype>/<state> · <theme>" with U+2215 for the slash."""
    return fid.replace("/", SLASH)


def frame_id(fid: str) -> str:
    """"shell/landmarks · dark" -> "shell∕landmarks" (the caption's state id)."""
    return frame_name(fid).split(" · ")[0]


# --- §7.1 the ring geometry, §7.6 the 12 backgrounds (ratios: the spec's tool output, never typed)
@dataclass(frozen=True)
class Geometry:
    variant: str  # normal | inset | thick (high visibility)
    ring: str
    halo: str
    offset: str
    trigger: str
    line: int


def _parse_geometry() -> dict[str, Geometry]:
    a = L("### 7.1 Geometry")
    out: dict[str, Geometry] = {}
    for i in range(a, L("### 7.2", start=a)):
        c = _cells(SPEC_LINES[i - 1]) if SPEC_LINES[i - 1].startswith("|") else []
        if len(c) == 5 and c[0] in ("normal", "inset", "thick (high visibility)"):
            out[c[0].split(" ")[0]] = Geometry(c[0], _plain(c[1]), _plain(c[2]), _plain(c[3]), _plain(c[4]), i)
    return out


GEOMETRY = _parse_geometry()
# px per variant, as §7.1 states them (ring, halo, offset); "as normal" rows inherit normal's
GEOM_PX = {"normal": (2, 1, 2), "inset": (2, 1, 0), "thick": (3, 2, 2)}
EXTENT_LINE = L("plus the ring's outer extent (offset + halo + ring + halo")


@dataclass(frozen=True)
class Background:
    n: int
    token: str
    why: str
    keys: dict[str, str]  # "dark.ring" -> the CONTRAST key ("hm-bid5.dark.ring")
    line: int

    def r(self, theme: str, kind: str) -> str:
        return ratio(self.keys[f"{theme}.{kind}"])


def _parse_backgrounds() -> list[Background]:
    a = L("### 7.6 The ring over the 12 worst-case backgrounds")
    out = []
    for i in range(a, L("## 8.", start=a)):
        raw = SPEC_LINES[i - 1]
        c = _cells(raw) if raw.startswith("|") else []
        if c and re.fullmatch(r"\d+", c[0]):
            ks = re.findall(r"<!--=CONTRAST:([\w.-]+)-->", raw, re.DOTALL)
            keys = {".".join(k.split(".")[-2:]): k for k in ks}
            out.append(Background(int(c[0]), _plain(c[1]), _plain(c[2]), keys, i))
    return out


BACKGROUNDS = _parse_backgrounds()
THEME_WORD = {"dark": "dark", "light": "light", "hc": "high contrast"}



# --- §4 the five archetypes: ARCH[aspect][archetype] = (cell as words, line)
def _parse_arch() -> dict[str, dict[str, tuple[str, int]]]:
    a = L("## 4. The five archetypes")
    head: list[str] = []
    out: dict[str, dict[str, tuple[str, int]]] = {}
    for i in range(a, L("## 5.", start=a)):
        ln = SPEC_LINES[i - 1]
        if not ln.startswith("|") or set(ln) <= set("|- "):
            continue
        c = _cells(ln)
        if c[0] == "Aspect":
            head = c[1:]
            continue
        out[c[0]] = {h: (_plain(v), i) for h, v in zip(head, c[1:])}
    return out


ARCH = _parse_arch()


def arch(aspect: str, archetype: str) -> str:
    """'§4 L<n> <aspect> (<archetype>): <cell>'."""
    v, ln = ARCH[aspect][archetype]
    return f"§4 L{ln} {aspect} ({archetype}): {v}"


# --- §15 the copy deck (W-1 ... W-8), §18.2 the G-ledger, §1.4 the rules
@dataclass(frozen=True)
class Copy:
    key: str
    text: str  # the string, quotes removed ("{name}, focused")
    status: str
    line: int


def _parse_copy() -> dict[str, Copy]:
    a = L("## 15. Copy deck")
    out = {}
    for i in range(a, L("## 16.", start=a)):
        c = _cells(SPEC_LINES[i - 1]) if SPEC_LINES[i - 1].startswith("|") else []
        if c and re.fullmatch(r"W-\d+", c[0]):
            out[c[0]] = Copy(c[0], c[1].strip().strip('"'), _plain(c[3]), i)
    return out


COPY = _parse_copy()
_SLOT = re.compile(r"\{[^{}]*\}")


def w(key: str, *vals: Any) -> str:
    """W-n with its {slots} filled in order (every slot must be filled; a verbatim string takes none)."""
    s = COPY[key].text
    slots = _SLOT.findall(s)
    if len(vals) != len(slots):
        raise ValueError(f"{key}: {len(slots)} slots {slots}, {len(vals)} values")
    for v in vals:
        s = _SLOT.sub(str(v).replace("\\", "\\\\"), s, count=1)
    NOTES.add("copy_keys", f"{key} (§15 L{COPY[key].line}, {COPY[key].status})")
    return s


def _parse_g() -> dict[str, tuple[str, int]]:
    a = L("### 18.2 The G-ledger")
    return {c[0]: (_plain(c[1]), i) for i in range(a, L("### 18.3", start=a))
            if SPEC_LINES[i - 1].startswith("|") and (c := _cells(SPEC_LINES[i - 1]))[0].startswith("D04-G")}


GROWS = _parse_g()  # D04-G1 ... D04-G6


def g(gid: str) -> str:
    if gid not in GROWS:
        raise KeyError(gid)
    NOTES.add("g_rows", f"{gid} (§18.2 L{GROWS[gid][1]}): {GROWS[gid][0]}")
    return gid


RULES = {m.group(1): (m.group(2), i + 1) for i, ln in enumerate(SPEC_LINES)
         if (m := re.match(r"- \*\*(R-\d+) ([^*]+?)\.\*\*", ln))}


def rule(rid: str) -> str:
    """'R-5 Never stolen (§1.4 L<n>)'."""
    name, ln = RULES[rid]
    return f"{rid} {name} (§1.4 L{ln})"


# --- the recorded tick size (§H) and the synthetic world declared on every board's face
def _tick(symbol: str = "BTCUSDT") -> Decimal:
    def find(o: Any) -> str | None:
        if isinstance(o, dict):
            if o.get("symbol") == symbol and "priceFilter" in o:
                return str(o["priceFilter"]["tickSize"])
            vals = o.values()
        elif isinstance(o, list):
            vals = o
        else:
            return None
        for v in vals:
            r = find(v)
            if r:
                return r
        return None

    t = find(json.loads(FIXTURE.read_text(encoding="utf-8")))
    if not t:
        raise LookupError(f"{symbol}: no tickSize in {FIXTURE_REL}")
    return Decimal(t)


SYMBOL = "BTCUSDT"
TICK = _tick(SYMBOL)  # Decimal("0.10") in the pinned fixture
SYNTHETIC = (f"Synthetic data: a seeded book and position set; only the {SYMBOL} tick size ({TICK}) is recorded "
             f"({FIXTURE_REL})")


def region_name(kind: str, symbol: str, interval: str | None = None, env: str | None = None) -> str:
    """E15-D15's naming rule as §2 cites it (D15:262, :281): "{Kind}, {symbol} {interval spelled}" plus
    ", {Environment}" for the order-capable kinds."""
    s = f"{kind}, {symbol}" + (f" {interval}" if interval else "")
    return s + (f", {env}" if env else "")


PANELS = (  # the four-panel layout in reading order (§3: "the panels in reading order"); D15:262's examples
    ("chart", region_name("Chart", SYMBOL, "1 minute", "Live")),
    ("dom", region_name("DOM", SYMBOL, env="Live")),
    ("positions", region_name("Positions", "all symbols", env="Live")),
    ("tape", region_name("Tape", SYMBOL)),
)


# --- tokens (exact names in token-sync.json; the self-test checks every one)
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_ON_ACTION, TEXT_INVERSE = "color.text.on-action", "color.text.inverse"
BORDER, BORDER_SUBTLE, BORDER_STRONG, RING = ("color.border.default", "color.border.subtle", "color.border.strong",
                                              "color.focus.ring")
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
DANGER_STRONG, DANGER_SUBTLE, INFO_STRONG = ("color.status.danger.strong", "color.status.danger.subtle",
                                             "color.status.info.strong")
BUY, SELL, BUY_SUBTLE, SELL_SUBTLE = "color.buy.default", "color.sell.default", "color.buy.subtle", "color.sell.subtle"
ENV_LIVE = "color.env.live"
MARK_FILL = "color.status.info.default"  # the annotation markers (numbered stops, region tags): not product UI
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD, HEADING_LG = "type.ui.heading-sm", "type.ui.heading-md", "type.ui.heading-lg"
NUM = "type.num.base"
INSET_XS, INSET_SM, INSET_MD, INSET_LG = "space.inset.xs", "space.inset.sm", "space.inset.md", "space.inset.lg"
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
DIALOG_PAD, BUTTON_PADX, PANEL_PAD = "space.dialog.padding", "space.button.paddingX", "space.panel.padding"
ICON, ICON_SM = "size.icon", "size.icon.sm"
R_CONTROL, R_CARD, R_BADGE, R_DIALOG = "radius.control", "radius.card", "radius.badge", "radius.dialog"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
OPACITY_SCRIM = "opacity.scrim"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12, STACK_LG: 16,
      DIALOG_PAD: 24, BUTTON_PADX: 12, PANEL_PAD: 12, ICON: 16, ICON_SM: 12, HAIR: 1, THICK: 2, FOCUS_W: 2}
FALLBACKS = {
    "thick": "fallback: the 3 px thick ring (PROPOSED border.focus.thick, D04-G5: not a token) drawn as two "
             "adjacent strokes in color.focus.ring, border.focus (2) + border.hairline (1)",
    "panel-focus": "fallback: border.panel.focus (= {border.focus}, `16`:88) is not in the token file: the inset "
                   "panel frame is drawn as a border.focus inner stroke in color.focus.ring; the header bar as a "
                   "3 px color.focus.ring rect (border.thick + border.hairline, the `16`:88 composite)",
    "scrim": "fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim",
    "chrome": "kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab "
              "labels, RightRail rows, StatusBar items) drawn as neutral placeholders; only what the focus model "
              "names is drawn with words",
    "markers": "kit choice: numbered stop markers, region tags and move arrows are annotation overlays in "
               "color.status.info.default on color.text.inverse, never product UI",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)",
    "density": "kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, "
               "size.row.compact); the shell bars keep E10's 48 px TopBar",
}
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}
# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "g_rows", "spec_gaps", "fallbacks", "tokens", "live_checks",
              "deviations")


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
         HEADING_SM: (14, 1.2, False), HEADING_MD: (16, 1.2, False), HEADING_LG: (20, 1.2, False),
         NUM: (13, 1.2, True)}


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



# --- CMP-039 the ring (§7.1 geometry, §7.2 two tones), drawn from nested stroke-only boards (proven in the E08
# kit's rows) so every band is token-bound: outer halo, ring, inner halo, then the offset gap, then the control.
CONTROL_H, ROW_H = 24, 24  # compact density (§0)
HALO_TOKENS = {"normal": (HAIR,), "inset": (HAIR,), "thick": (THICK,)}
RING_TOKENS = {"normal": (FOCUS_W,), "inset": (FOCUS_W,), "thick": (FOCUS_W, HAIR)}


def ring_bands(variant: str) -> list[tuple[str, str]]:
    """Outside-in (colour, width token) bands of the ring; the sum of widths + the offset is §7.5's outer extent."""
    if variant == "thick":
        fallback("thick")
    return ([(CANVAS, t) for t in HALO_TOKENS[variant]] + [(RING, t) for t in RING_TOKENS[variant]]
            + [(CANVAS, t) for t in HALO_TOKENS[variant]])


def extent(variant: str) -> int:
    """offset + halo + ring + halo, in px (§7.5: 6 px normal, 9 px thick; the self-test checks both)."""
    return GEOM_PX[variant][2] + sum(PX[t] for _c, t in ring_bands(variant))


def _layers(name: str, wd: int, ht: int, variant: str, inner: Node | None, radius: str | None) -> Node:
    bands = ring_bands(variant)
    node_: Node | None = None
    sizes, s = [], 0
    for _c, t in bands:
        sizes.append(s)
        s += PX[t]
    for i in range(len(bands) - 1, -1, -1):
        c, t = bands[i]
        kids = [node_] if node_ else ([inner] if inner else [])
        node_ = box(f"band-{i + 1} · {'ring' if c == RING else 'halo'}", kids,
                    {"stroke": c, "strokeWidth": t, "strokeAlign": "inner", **({"radius": radius} if radius else {})},
                    w=wd - 2 * sizes[i], h=ht - 2 * sizes[i],
                    x=(PX[bands[i - 1][1]] if i else 0), y=(PX[bands[i - 1][1]] if i else 0))
    assert node_ is not None
    node_ = dict(node_, name=name)
    node_.pop("x", None)
    node_.pop("y", None)
    return node_


def focus_ring(control: Node, variant: str = "normal", *, radius: str = R_CONTROL, name: str | None = None) -> Node:
    """CMP-039 around a control with explicit w and h: a w + 2e x h + 2e board (e = extent(variant)); the control
    sits at the offset inside the inner halo."""
    if variant not in ("normal", "thick"):
        raise ValueError(variant)
    e = extent(variant)
    cw, ch = int(control["w"]), int(control["h"])
    band_sum = e - GEOM_PX[variant][2]
    last = PX[ring_bands(variant)[-1][1]]
    inner = dict(control, x=last + GEOM_PX[variant][2], y=last + GEOM_PX[variant][2])
    inner.pop("abs", None)
    del band_sum
    return dict(_layers(name or f"CMP-039 ring · {variant}", cw + 2 * e, ch + 2 * e, variant, inner, radius),
                note=f"focus-visible; {variant}: outer extent {e} px (§7.1, §7.5)")


def inset_ring(wd: int, ht: int, *, name: str = "CMP-039 ring · inset", radius: str | None = None) -> Node:
    """CMP-039 inset (rows, cells): the bands drawn inside the element's box, no offset; place it as the row's last
    kid (abs at 0, 0)."""
    return dict(_layers(name, wd, ht, "inset", None, radius), x=0, y=0, abs=True,
                note="CMP-039 inset: drawn inside the element (§7.1)")


# --- annotation overlays inside a frame: numbered stops, region tags, outlines, move arrows, callouts
def marker(n: int | str, x: int, y: int, *, name: str | None = None) -> Node:
    fallback("markers")
    return hbox(name or f"stop {n}", [text("n", str(n), LABEL, TEXT_INVERSE)],
                {"justify": "center", "fill": MARK_FILL, "radius": R_BADGE}, w=20, h=20, x=x, y=y, abs=True,
                note="annotation marker (not product UI)")


def tag(label_: str, x: int, y: int, *, name: str | None = None) -> Node:
    fallback("markers")
    return hbox((name or f"tag · {label_[:40]}").replace("/", SLASH), [text("label", label_, CAPTION, TEXT_INVERSE)],
                {"padX": INSET_XS, "radius": R_CONTROL, "fill": MARK_FILL}, h=16, x=x, y=y, abs=True,
                note="annotation tag (not product UI)")


def outline(name: str, x: int, y: int, wd: int, ht: int) -> Node:
    fallback("markers")
    return box(f"outline · {name}", [], {"stroke": MARK_FILL, "strokeWidth": THICK, "strokeAlign": "inner"},
               w=wd, h=ht, x=x, y=y, abs=True, note="annotation outline (not product UI)")


def hline(name: str, x: int, y: int, wd: int) -> Node:
    return rect(f"arrow · {name}", wd, 2, MARK_FILL, x=x, y=y, abs=True)


def vline(name: str, x: int, y: int, ht: int) -> Node:
    return rect(f"arrow · {name}", 2, ht, MARK_FILL, x=x, y=y, abs=True)


def arrow_head(name: str, glyph_: str, x: int, y: int) -> Node:
    return icon(f"arrow-head · {name}", glyph_, MARK_FILL, x=x, y=y, abs=True)


def callout(name: str, lines: Iterable[str], x: int, y: int, wd: int = 320) -> Node:
    """A spoken string or a move, boxed on the frame (an annotation overlay; the words are §15's)."""
    fallback("markers")
    ls = [ln for ln in lines if ln]
    kids = [text(f"line-{i}", s, CAPTION if i > 1 else LABEL, TEXT_1, w=wd - 2 * PX[INSET_SM])
            for i, s in enumerate(ls, 1)]
    return vbox(f"callout · {name}", kids, {"gap": STACK_XS, "pad": INSET_SM, "fill": OVERLAY, "radius": R_CONTROL,
                                            "stroke": MARK_FILL, "strokeWidth": THICK, "strokeAlign": "inner"},
                w=wd, x=x, y=y, abs=True, note="annotation callout (not product UI)")


# --- controls at compact density (24 px)
BUTTON_LOOK = {"primary": (ACTION_PRIMARY, TEXT_ON_ACTION, None), "secondary": (ACTION_SECONDARY, TEXT_1, None),
               "ghost": (None, TEXT_2, None), "destructive": (DANGER_SUBTLE, TEXT_1, DANGER_STRONG)}


def placeholder(name: str, w_: int, h: int = 12, fill: str = HOVER) -> Node:
    fallback("chrome")
    return rect(f"placeholder · {name}", w_, h, fill, {"radius": R_CONTROL})


def button(chars: str, variant: str = "secondary", *, name: str | None = None, lead: Node | None = None,
           focused: str | None = None) -> Node:
    """A CMP-001 button, 24 px; focused="normal" | "thick" wraps it in CMP-039."""
    fill_, col, stroke = BUTTON_LOOK[variant]
    kids = ([lead] if lead else []) + [text("label", chars, BODY_STRONG, col)]
    o: dict[str, Any] = {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "justify": "center"}
    if fill_:
        o["fill"] = fill_
    if stroke:
        o.update(stroke=stroke, strokeWidth=HAIR, strokeAlign="inner")
    wd = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    b = hbox(name or f"button · {chars}", kids, o, w=wd, h=CONTROL_H)
    return focus_ring(b, focused) if focused else b


def icon_button(glyph_: str, *, name: str | None = None, focused: str | None = None) -> Node:
    b = hbox(name or f"icon button · {glyph_}", [icon("glyph", glyph_, TEXT_2)], {"justify": "center",
                                                                                 "radius": R_CONTROL},
             w=CONTROL_H, h=CONTROL_H)
    return focus_ring(b, focused) if focused else b


def t2_button(chars: str, reason: str, *, focused: str | None = None, name: str | None = None,
              w_: int = 240) -> Node:
    """E09-D09 T2 (§10, R-10): the lock leads the full label (tertiary) on raised + border.default; the reason under it
    (aria-describedby); aria-disabled, never disabled; it stays in the Tab order."""
    kids = [icon("lock", "locked", TEXT_3), text("label", chars, BODY_STRONG, TEXT_3)]
    b = hbox(f"T2 · {chars}", kids, {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL, "fill": RAISED,
                                     "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner"},
             w=round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2), h=CONTROL_H,
             note='aria-disabled="true"; the reason is its aria-describedby')
    return vbox(name or f"T2 · {chars} + reason", [focus_ring(b, focused) if focused else b,
                                                   text("reason", reason, CAPTION, TEXT_2, w=w_)], {"gap": INSET_XS})


def switch(on: bool = False) -> Node:
    knob = ellipse("knob", 12, 12, {"fill": TEXT_ON_ACTION if on else TEXT_2}, x=22 if on else 4, y=4)
    return box("switch", [knob], {"fill": ACTION_PRIMARY if on else HOVER, "radius": R_BADGE, "stroke": BORDER,
                                  "strokeWidth": HAIR, "strokeAlign": "inner"}, w=38, h=20)


def toggle_row(label_: str, help_: str | None = None, *, on: bool = False, focused: str | None = None,
               w_: int = 560) -> Node:
    """CMP-004 Toggle with its visible label and description (SCR-117: "never a bare toggle")."""
    sw = switch(on)
    lines = [text("label", label_, BODY_STRONG, TEXT_1, w=w_ - 72)]
    if help_:
        lines.append(text("help", help_, CAPTION, TEXT_2, w=w_ - 72))
    return hbox(f"toggle · {label_[:40]}", [focus_ring(sw, focused, radius=R_BADGE) if focused else sw,
                                            vbox("text", lines, {"gap": STACK_XS})],
                {"gap": INSET_MD, "align": "start"}, w=w_, note='role="switch"')


# --- CMP-049 tables: every cell is a box padded space.inset.sm (8 px) a side, so adjacent texts sit >= 16 px apart
@dataclass(frozen=True)
class Col:
    key: str
    label: str
    w: int
    numeric: bool = False


def cell(name: str, content: str | Node | list[Node] | None, w_: int, *, numeric: bool = False, h: int = ROW_H,
         typo: str | None = None, color: str = TEXT_1, second: str | None = None) -> Node:
    """One cell: padX 8 px, end-justified for numbers (type.num.base), start otherwise; `second` adds a secondary
    line under the text (the Class cell's adapter class, §3.1)."""
    inner = w_ - 2 * PX[INSET_SM]
    if content is None or content == "":
        kids: list[Node] = []
    elif isinstance(content, str):
        t = text("value", content, typo or (NUM if numeric else BODY), color,
                 **({"w": inner} if text_w(content, typo or (NUM if numeric else BODY)) > inner else {}))
        kids = [t]
        if second:
            kids = [vbox("lines", [t, text("second", second, CAPTION, TEXT_2)], {"gap": STACK_XS})]
    elif isinstance(content, list):
        kids = content
    else:
        kids = [content]
    return hbox(name, kids, {"padX": INSET_SM, "justify": "end" if numeric else "start", "gap": INSET_XS}, w=w_, h=h)


def header_row(cols: Iterable[Col], *, fill: str = CANVAS) -> Node:
    cs = list(cols)
    return hbox("header row", [cell(f"th · {c.key}", c.label, c.w, numeric=c.numeric, typo=CAPTION, color=TEXT_2)
                               for c in cs], {"fill": fill}, w=sum(c.w for c in cs), h=ROW_H,
                note='column headers, scope="col"')


def table_row(cols: Iterable[Col], cells: dict[str, str | Node | list[Node] | None], name: str, i: int, *,
              h: int | None = None, focused: bool = False, second: dict[str, str] | None = None,
              colors: dict[str, str] | None = None, fill: str | None = None) -> Node:
    """One body row: zebra (odd color.surface.canvas, even color.surface.raised, §16); focused adds CMP-039 inset.
    h=None: the tallest cell's content + 8 px a side, at least ROW_H (32), rounded up to 4 px."""
    cs = list(cols)
    if h is None:
        probe = [cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=1, second=(second or {}).get(c.key))
                 for c in cs]
        need = max((est_height(dict(k, h=None)) for k in probe), default=0.0) + 2 * PX[INSET_SM]
        h = max(ROW_H, int(math.ceil(need / 4) * 4))
    unknown = set(cells) - {c.key for c in cs}
    if unknown:
        raise KeyError(f"{name}: cells for unknown columns {sorted(unknown)}")
    kids = [cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=h, second=(second or {}).get(c.key),
                 color=(colors or {}).get(c.key, TEXT_1)) for c in cs]
    for k in kids:  # a cell's content must fit the row (no clipped or overlapping text): pass a taller h
        need = est_height(dict(k, h=None))
        if need > h:
            raise ValueError(f"{name}: cell {k['name']!r} needs about {need:.0f} px > row h {h}")
    o: dict[str, Any] = {"fill": fill or (CANVAS if i % 2 else RAISED)}
    wd = sum(c.w for c in cs)
    if focused:  # CMP-039 inset on the focused row (§4 dense grid Tokens; §7.1 inset)
        kids.append(inset_ring(wd, h))
    return hbox(name, kids, o, w=wd, h=h)


def table(name: str, caption_: str | None, header: Node, rows: list[Node], *, note: str | None = None) -> Node:
    """A CMP-049 table: the visible caption (type.ui.caption, secondary), the header row, a 1 px rule, the rows."""
    wd = header["w"]
    kids = [text("caption", caption_, CAPTION, TEXT_2, w=wd) if caption_ else None, header,
            rect("header rule", wd, 1, BORDER),
            vbox("rows", rows, None, w=wd, h=round(sum(est_height(r) for r in rows))) if rows else None]
    return vbox(name, kids, {"gap": STACK_XS}, w=wd, note=note)


# §3.2's columns at 944 px (W-08 gives the six headings; Meter and State carry no visible heading in §3.2's list, so


# --- the shell (SCR-010) at 1280 x 800, compact: TopBar 48 (E10) | NavRail 56 · main 984 · RightRail 240 | StatusBar
# 24; on the workspace (SCR-020) main = the tab strip (RG-02) 32, the four panels 2 x 2 (490 x 332, 4 px splitters),
# the minimised tray (RG-04) 28. Frame coordinates of every region are in GEO for the overlays.
TOP_H, STATUS_H, NAV_W, RIGHT_W = 48, 24, 56, 240
MAIN_W, BODY_H = FRAME_W - NAV_W - RIGHT_W, FRAME_H - TOP_H - STATUS_H  # 984, 728
TAB_H, TRAY_H, SPLIT = 32, 28, 4
PANEL_W, PANEL_H = (MAIN_W - SPLIT) // 2, (BODY_H - TAB_H - TRAY_H - SPLIT) // 2  # 490, 332
HEADER_H = 28
GEO: dict[str, tuple[int, int, int, int]] = {
    "topbar": (0, 0, FRAME_W, TOP_H), "navrail": (0, TOP_H, NAV_W, BODY_H), "main": (NAV_W, TOP_H, MAIN_W, BODY_H),
    "tabstrip": (NAV_W, TOP_H, MAIN_W, TAB_H),
    "chart": (NAV_W, TOP_H + TAB_H, PANEL_W, PANEL_H),
    "dom": (NAV_W + PANEL_W + SPLIT, TOP_H + TAB_H, PANEL_W, PANEL_H),
    "positions": (NAV_W, TOP_H + TAB_H + PANEL_H + SPLIT, PANEL_W, PANEL_H),
    "tape": (NAV_W + PANEL_W + SPLIT, TOP_H + TAB_H + PANEL_H + SPLIT, PANEL_W, PANEL_H),
    "tray": (NAV_W, TOP_H + BODY_H - TRAY_H, MAIN_W, TRAY_H),
    "rightrail": (FRAME_W - RIGHT_W, TOP_H, RIGHT_W, BODY_H), "statusbar": (0, FRAME_H - STATUS_H, FRAME_W, STATUS_H),
}
FLATTEN = "FLATTEN ALL"  # the TopBar control §9.2 names (`14`:302); FREEZE beside it in `14` SCR-010's wireframe
FREEZE = "FREEZE"


def topbar(*, flatten: Node | None = None) -> Node:
    """TopBar (banner): placeholders, then FLATTEN ALL and FREEZE (or `flatten`, a focused / T2 variant)."""
    left = hbox("left", [placeholder("wordmark", 72), placeholder("env badge", 40, 16, ENV_LIVE),
                         placeholder("account picker", 120), placeholder("symbol picker", 88),
                         placeholder("interval picker", 48)], {"gap": INSET_MD}, h=TOP_H)
    right = hbox("right", [placeholder("health chips", 160), flatten or button(FLATTEN, "destructive"),
                           button(FREEZE, "destructive"), placeholder("user menu", 64)], {"gap": INSET_MD}, h=TOP_H)
    return hbox("TopBar · banner", [left, right, rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=TOP_H - 1,
                                                       abs=True)],
                {"padX": INSET_LG, "justify": "space-between", "fill": APP}, w=FRAME_W, h=TOP_H,
                note='role="banner"')


def navrail(*, admin: bool = True, current: int = 1) -> Node:
    """NavRail (navigation): six entries + Admin (Owner only; T3-absent otherwise, §10)."""
    rows = [hbox(f"entry-{i}", [placeholder("glyph", 16, 16)], {"justify": "center", "radius": R_CONTROL,
                                                                **({"fill": SELECTED} if i == current else {})},
                 w=40, h=CONTROL_H + 8) for i in range(1, 7)]
    if admin:
        rows.append(hbox("entry-admin", [placeholder("admin glyph", 16, 16)], {"justify": "center"}, w=40,
                         h=CONTROL_H + 8, note="Admin entry: Owner only"))
    return vbox("NavRail · navigation", [*rows, rect("divider", 1, BODY_H, BORDER_SUBTLE, x=NAV_W - 1, y=0,
                                                       abs=True)],
                {"gap": INSET_XS, "align": "center", "padY": INSET_SM, "fill": APP}, w=NAV_W, h=BODY_H,
                note='<nav> with aria-current')


def rightrail() -> Node:
    rows = [placeholder(f"row-{i}", RIGHT_W - 24) for i in range(1, 5)]
    return vbox("RightRail · complementary", [*rows, rect("divider", 1, BODY_H, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"gap": INSET_MD, "pad": INSET_MD, "fill": APP}, w=RIGHT_W, h=BODY_H, note='role="complementary"')


def statusbar() -> Node:
    return hbox("StatusBar · contentinfo", [placeholder("connection chip", 120), placeholder("clock", 96),
                                            placeholder("version", 48),
                                            rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"padX": INSET_LG, "gap": INSET_LG, "fill": APP}, w=FRAME_W, h=STATUS_H,
                note='role="contentinfo"')


def tabstrip() -> Node:
    tabs = [hbox(f"tab-{i}", [placeholder("tab label", 72)], {"padX": INSET_MD, "radius": R_CONTROL,
                                                              **({"fill": SELECTED} if i == 1 else {})},
                 h=CONTROL_H) for i in range(1, 4)]
    return hbox("tab strip · RG-02 Workspaces", tabs, {"gap": INSET_XS, "padX": INSET_SM, "fill": APP}, w=MAIN_W,
                h=TAB_H, note='role="tablist" aria-label="Workspaces"; the active tab is the visually hidden h1')


def tray() -> Node:
    chips = [placeholder(f"minimised-{i}", 96, 16) for i in (1, 2)]
    return hbox("tray · RG-04 Minimised panels", chips, {"gap": INSET_SM, "padX": INSET_SM, "fill": APP}, w=MAIN_W,
                h=TRAY_H, note='role="toolbar" aria-label="Minimised panels"')


def flatten_x(flatten: Node | None = None) -> int:
    """The frame x of the TopBar's FLATTEN ALL control (its right group is end-justified; estimate)."""
    fl = flatten or button(FLATTEN, "destructive")
    rest = 64 + est_width(button(FREEZE, "destructive")) + est_width(fl) + 3 * PX[INSET_MD]
    return round(FRAME_W - PX[INSET_LG] - rest)


TOOLBAR_GLYPHS = ("more-horizontal", "close")  # RG-08: the header actions (kit choice of glyphs)


def panel(kind: str, name: str, body: Node | None, *, focused: bool = False, toolbar_focus: int | None = None,
          w_: int = PANEL_W, h_: int = PANEL_H, extra: Iterable[Node] = ()) -> Node:
    """A docked panel (region named by D15's rule): the header (h2 + the RG-08 toolbar), the body; focused draws
    CMP-080's inset frame and the header bar in color.focus.ring (§7.4; `16`:88), never CMP-039 around the panel."""
    tools = [icon_button(gl, focused="normal" if toolbar_focus == i else None, name=f"tool {i} · {gl}")
             for i, gl in enumerate(TOOLBAR_GLYPHS, 1)]
    header = hbox("header", [text("h2", name, BODY_STRONG, TEXT_1), hbox("RG-08 toolbar", tools, {"gap": INSET_XS},
                                                                         h=HEADER_H)],
                  {"padX": INSET_SM, "justify": "space-between", "fill": RAISED}, w=w_, h=HEADER_H,
                  note=f'h2 "{name}"; RG-08 toolbar named by the panel')
    bh = h_ - HEADER_H
    kids: list[Node] = [header, box("body", [body] if body else [], {"fill": CANVAS, "clip": True}, w=w_, h=bh),
                        *extra]
    if focused:
        fallback("panel-focus")
        kids += [box("panel focus frame", [], {"stroke": RING, "strokeWidth": FOCUS_W, "strokeAlign": "inner"},
                     w=w_, h=h_, x=0, y=0, abs=True, note="CMP-080 inset frame (border.panel.focus)"),
                 rect("panel focus header bar", w_, 3, RING, x=0, y=0, abs=True)]
    return vbox(f"panel · {kind}", kids, {"clip": True}, w=w_, h=h_, note=f'role="region" aria-label="{name}"')


def _frame(fid: str, kids: list[Node], overlays: Iterable[Node], note: str | None) -> Node:
    if fid not in {f for fs in FRAME_PLAN.values() for f in fs}:
        raise KeyError(f"{fid!r} is not a §H frame")
    return vbox(frame_name(fid), [*kids, *overlays], {"fill": APP, "clip": True}, w=FRAME_W, h=FRAME_H, note=note)


def workspace_window(fid: str, bodies: dict[str, Node | None], *, focus_panel: str | None = None,
                     toolbar_focus: tuple[str, int] | None = None, panel_extra: dict[str, list[Node]] | None = None,
                     overlays: Iterable[Node] = (), flatten: Node | None = None, note: str | None = None) -> Node:
    """SCR-020 in the shell (§2, §3): bodies[kind] fills each of the four panels (None: an empty canvas)."""
    fallback("density")
    ps = []
    for kind, name in PANELS:
        x, y, _w, _h = GEO[kind]
        p = panel(kind, name, bodies.get(kind), focused=focus_panel == kind,
                  toolbar_focus=toolbar_focus[1] if toolbar_focus and toolbar_focus[0] == kind else None,
                  extra=(panel_extra or {}).get(kind, ()))
        ps.append(dict(p, x=x - NAV_W, y=y - TOP_H))
    main = box("main · workspace", [dict(tabstrip(), x=0, y=0), *ps,
                                    dict(tray(), x=0, y=BODY_H - TRAY_H)], {"fill": BORDER_SUBTLE, "clip": True},
               w=MAIN_W, h=BODY_H, note='<main>; each panel a region; splitters 4 px (color.border.subtle)')
    body = hbox("body", [navrail(), main, rightrail()], {"align": "start"}, w=FRAME_W, h=BODY_H)
    return _frame(fid, [topbar(flatten=flatten), body, statusbar()], overlays, note)


def page_window(fid: str, content: Node, *, admin: bool = True, flatten: Node | None = None,
                overlays: Iterable[Node] = (), note: str | None = None) -> Node:
    """A full page (§4 full-page form) in the shell: content fills main (984 x 728)."""
    fallback("density")
    main = box("main · page", [dict(content, x=0, y=0)], {"fill": APP, "clip": True}, w=MAIN_W, h=BODY_H,
               note="<main>")
    body = hbox("body", [navrail(admin=admin, current=6), main, rightrail()], {"align": "start"}, w=FRAME_W,
                h=BODY_H)
    return _frame(fid, [topbar(flatten=flatten), body, statusbar()], overlays, note)


def specimen_frame(fid: str, kids: list[Node], *, note: str | None = None) -> Node:
    """A 1280 x 800 specimen frame (boards 08-10): color.surface.app, 40 px inset, a column of kids."""
    inner = vbox("specimen", kids, {"gap": STACK_LG}, w=FRAME_W - 80, x=40, y=40)
    return box(frame_name(fid), [inner], {"fill": APP, "clip": True}, w=FRAME_W, h=FRAME_H,
                note=note or "specimen: every fill a token; the theme is set at export")


# --- dialogs (CMP-044 alertdialog over the flat scrim)
DIALOG_W = 480  # kit choice: no source gives CMP-044's width at 1280 (recorded)


def dialog(title: str, kids: Iterable[Node | None], actions: Iterable[Node], *, name: str | None = None,
           w_: int = DIALOG_W) -> Node:
    deviate(f"dialog width {w_} px: a kit choice (no source gives CMP-044's width)")
    iw = w_ - 2 * PX[DIALOG_PAD]
    body = [text("title", title, HEADING_MD, TEXT_1, w=iw, note="h2: the dialog's name"), *kids,
            hbox("actions", list(actions), {"gap": INSET_SM, "justify": "end"}, w=iw, h=CONTROL_H + 20)]
    return vbox(name or "CMP-044 dialog", body, {"fill": OVERLAY, "radius": R_DIALOG, "pad": DIALOG_PAD,
                                                 "gap": STACK_MD, "stroke": BORDER, "strokeWidth": HAIR,
                                                 "strokeAlign": "inner"}, w=w_,
                note='role="alertdialog" aria-modal; the page behind is inert')


def modal(dialog_node: Node, *, x: int | None = None, y: int | None = None) -> tuple[Node, tuple[int, int, int, int]]:
    """The overlay for a window's overlays: the flat scrim over the frame and the dialog centred; returns the overlay
    and the dialog's frame rect (x, y, w, h estimated)."""
    fallback("scrim")
    dw, dh = est_width(dialog_node), est_height(dialog_node)
    dx = round((FRAME_W - dw) / 2) if x is None else x
    dy = round(max((FRAME_H - dh) / 2, 0)) if y is None else y
    live(f"modal: re-centre '{dialog_node['name']}' after relayout (estimated {dw:.0f} x {dh:.0f} px)")
    scrim = rect("scrim", FRAME_W, FRAME_H, SUNKEN, {"opacity": OPACITY_SCRIM}, x=0, y=0)
    dlg = dict(dialog_node, x=dx, y=dy)
    return box("overlay", [scrim, dlg], None, w=FRAME_W, h=FRAME_H, x=0, y=0, abs=True), (dx, dy, round(dw), round(dh))


def lines_block(name: str, lines: Iterable[str], *, w_: int, typo: str = BODY, color: str = TEXT_1) -> Node:
    ls = [x for x in lines if x]
    return vbox(name, [text(f"line-{i}", s, typo, color, w=w_) for i, s in enumerate(ls, 1)], {"gap": STACK_XS},
                w=w_)


# --- the synthetic book and position set (declared on every board's face; seeded, deterministic)
SEED = 1303


def lcg(seed: int) -> Iterable[int]:
    x = seed
    while True:
        x = (1103515245 * x + 12345) % (1 << 31)
        yield x


def px_fmt(p: Decimal, tick: Decimal = TICK) -> str:
    return f"{p.quantize(tick):,}"


BEST_BID = Decimal("67420.00").quantize(TICK)  # synthetic anchor; every other price is BEST_BID +/- k * TICK
BEST_ASK = BEST_BID + TICK


@dataclass(frozen=True)
class Level:
    price: Decimal
    side: str  # bid | ask
    size: str | None  # None: no resting size at this price (a vanished level)


def ladder(rows: int = 11, *, asks: int = 5, seed: int = SEED, vanished: Iterable[Decimal] = ()) -> list[Level]:
    """Price rows top to bottom (descending): `asks` ask levels above the touch, then bids; sizes seeded (3 dp)."""
    r, gone = lcg(seed), set(vanished)
    out = []
    for k in range(asks, 0, -1):
        p = BEST_ASK + (k - 1) * TICK
        out.append(Level(p, "ask", None if p in gone else f"{(next(r) % 4000 + 5) / 1000:.3f}"))
    for k in range(rows - asks):
        p = BEST_BID - k * TICK
        out.append(Level(p, "bid", None if p in gone else f"{(next(r) % 4000 + 5) / 1000:.3f}"))
    return out


def nearest_survivor(levels: list[Level], gone: Decimal) -> Decimal:
    """§8: the nearest surviving level by price, ties toward the touch (best bid for a bid, best ask for an ask)."""
    side = next(lv.side for lv in levels if lv.price == gone)
    alive = [lv.price for lv in levels if lv.size is not None]
    best = min(abs(p - gone) for p in alive)
    tied = [p for p in alive if abs(p - gone) == best]
    return max(tied) if side == "bid" else min(tied)


LADDER_COLS = (Col("bid", "Bid size", 140, True), Col("price", "Price", 160, True), Col("ask", "Ask size", 140, True))


def ladder_table(levels: list[Level], *, focus: Decimal | None = None, name: str = "CMP-049 grid · DOM ladder") -> Node:
    """The DOM ladder (SCR-050) as one grid stop: Bid size | Price | Ask size; bids on color.buy.subtle, asks on
    color.sell.subtle size cells (colour plus the column words); the focused row carries CMP-039 inset."""
    rows = []
    for i, lv in enumerate(levels, 1):
        cells: dict[str, str | None] = {"price": px_fmt(lv.price), "bid": lv.size if lv.side == "bid" else None,
                                        "ask": lv.size if lv.side == "ask" else None}
        rows.append(table_row(LADDER_COLS, cells, f"row {px_fmt(lv.price)}", i, h=ROW_H, focused=lv.price == focus))
    hd = header_row(LADDER_COLS)
    hd = dict(hd, h=ROW_H, kids=[dict(k, h=ROW_H) for k in hd["kids"]])
    return table(name, None, hd, rows, note='role="grid" aria-label="DOM ladder"; one Tab stop, roving tabindex (R-2)')


@dataclass(frozen=True)
class Position:
    account: str
    symbol: str
    side: str  # Long | Short
    qty: str
    entry: Decimal
    mark: Decimal

    @property
    def key(self) -> str:  # §6.2: the position key (account, symbol, side)
        return f"{self.account} {self.symbol} {self.side}"


ACCOUNTS = ("Main", "sub_001", "sub_002")  # "Main": `14` SCR-010; sub_001 / sub_002: E39-D03's account ids
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")  # all three in the pinned fixture; prices on each one's tick
ANCHOR = {"BTCUSDT": BEST_BID, "ETHUSDT": Decimal("3480"), "SOLUSDT": Decimal("182")}


def positions(n: int = 6, seed: int = SEED) -> list[Position]:
    """n positions sorted by (symbol, account, side), the grid's current sort; prices on their recorded ticks."""
    r = lcg(seed + 1)
    keys = [(s, a, sd) for s in SYMBOLS for a in ACCOUNTS for sd in ("Long", "Short")]
    picked = sorted({keys[next(r) % len(keys)] for _ in range(n * 4)})[:n]
    out = []
    for s, a, sd in picked:
        t = _tick(s)
        entry = (ANCHOR[s] - (next(r) % 200) * t).quantize(t)
        mark = (ANCHOR[s] + (next(r) % 100) * t).quantize(t)
        out.append(Position(a, s, sd, f"{(next(r) % 900 + 100) / 1000:.3f}", entry, mark))
    return out


POS_COLS = (Col("account", "Account", 80), Col("symbol", "Symbol", 96), Col("side", "Side", 64),
            Col("qty", "Qty", 72, True), Col("entry", "Entry", 88, True), Col("mark", "Mark", 88, True))


def positions_table(ps: list[Position], *, focus: str | None = None, name: str = "CMP-049 grid · positions") -> Node:
    rows = [table_row(POS_COLS, {"account": p.account, "symbol": p.symbol, "side": p.side, "qty": p.qty,
                                 "entry": px_fmt(p.entry, _tick(p.symbol)), "mark": px_fmt(p.mark, _tick(p.symbol))},
                      f"row {p.key}", i, h=ROW_H, focused=p.key == focus) for i, p in enumerate(ps, 1)]
    hd = header_row(POS_COLS)
    hd = dict(hd, h=ROW_H, kids=[dict(k, h=ROW_H) for k in hd["kids"]])
    return table(name, None, hd, rows, note='role="grid"; identity = the position key (R-3, §6.2)')


# --- the annotation column (ONE, 400 px, outside the frames) and the board
def frame_block(fid: str, lines: Iterable[str], *, keyboard: str | None = None,
                waits: Iterable[str] = ()) -> tuple[str, list[str]]:
    """The annotation block of one frame: what it draws (the author's lines, each citing its §/L line), the keyboard
    path, the G-rows it waits on."""
    if fid not in {f for fs in FRAME_PLAN.values() for f in fs}:
        raise KeyError(f"{fid!r} is not a §H frame")
    out = [x for x in lines if x]
    if keyboard:
        out.append(f"Keyboard: {keyboard}")
    gs = [g(x) for x in waits]
    if gs:
        out.append("Waits on " + ", ".join(f"{k} ({GROWS[k][0][:70]})" for k in gs))
    return frame_name(fid), out


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    """The ONE 400 px column: title (the board name), a "Board" block (§0's Draws, theme, twin, export, §H frames,
    the synthetic declaration), one block per frame, footer "page <PAGE> · board NN · r1"."""
    b = BOARDS[nn]
    head = [f"§0 L{b.line}: {b.draws}",
            f"Theme: {b.theme}" + (f" (twin of board {b.twin:02d}: same frames, theme set at export)" if b.twin
                                   else ""),
            f"Frames (hand-off §H L{H_LINE}): " + ", ".join(frames_of(nn)), f"Export: {b.export}",
            "Every frame 1280 x 800 at compact density (§0); markers, tags, outlines and callouts in "
            "color.status.info.default are annotation, not product UI", SYNTHETIC, *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


def layout(frames: list[Node], per_row: int | None = None) -> list[Node]:
    """Frames placed 1:1 in rows of <= MAX_PER_ROW (2 or 4 frames: 2 per row); MARGIN margin, gutters MARGIN + the
    28 px state caption above each row."""
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


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


# the live check's root heights: max(annotation end, footer end) + MARGIN as Penpot measured them (build-notes, "Live
# check fold"); the estimate above is the floor a board without a measurement keeps
MEASURED_H = {1: 998, 2: 998, 3: 1036, 4: 1878, 5: 998, 6: 1101, 7: 998, 8: 998, 9: 998, 10: 998}


def board(nn: int, frames: list[Node], ann: Node, *, per_row: int | None = None,
          strict: bool = True) -> tuple[dict[str, Any], list[Node]]:
    """The sheet's root (board name, grid x/y, fill color.surface.app, clip) hugging its frames + the ONE annotation
    column + MARGIN; a "state: <id>" caption 28 px above each frame; the synthetic-data footer under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f) for f in frames_of(nn)]
    got = [f["name"] for f in frames]
    if strict and got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != §H {want}")
    if any(f["w"] != FRAME_W or f["h"] != FRAME_H for f in frames):
        raise ValueError(f"board {nn:02d}: every frame is a {FRAME_W} x {FRAME_H} window (§0)")
    placed = layout(frames, per_row)
    caps = [text(f"caption {i:02d}", f"state: {f['name'].split(' · ')[0]}", CAPTION, TEXT_3, x=f["x"],
                 y=f["y"] - 28) for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · synthetic", SYNTHETIC, CAPTION, TEXT_2, x=MARGIN, y=bottom + 24)]
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    h = int(math.ceil((max(bottom + 24 + 16, MARGIN + ah) + MARGIN) / 8) * 8)
    if strict and nn in MEASURED_H:  # the live-measured end + MARGIN (it must still clear the frames and the footer)
        if MEASURED_H[nn] < bottom + 24 + 14 + MARGIN:
            raise ValueError(f"board {nn:02d}: measured h {MEASURED_H[nn]} < footer end {bottom + 24 + 14} + {MARGIN}")
        h = MEASURED_H[nn]
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch: trim the annotations")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root (h {h}); "
         f"set the root's h to max(column end, footer end) + {MARGIN}")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


# --- sections (<= SECTION_RAW_BUDGET raw bytes each; e42kit's packer, copied), lint, write, pack
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


def write_sheet(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
                per_row: int | None = None, out_dir: Path = CAP_DIR, name: str | None = None,
                strict: bool = True) -> Path:
    """Assemble board nn (board()), split into sections, merge notes (the kit's + notes=), write
    out_dir/NN-<slug>.json, run the validator (tokens + components) and raise RuntimeError unless it exits 0 and the
    kit lint and the banned scan are clean. Requires at least one live_checks line. Clears NOTES."""
    b = BOARDS[nn]
    out_dir = out_dir.resolve()
    if out_dir not in (CAP_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    root, nodes = board(nn, frames, ann, per_row=per_row, strict=strict)
    if b.theme != "dark":
        live(f"theme: activate the {b.theme} token set before exporting board {nn:02d} (twin of {b.twin:02d}); read "
             f"back one bound fill (color.surface.canvas) as the {b.theme} value")
    live(f"export {b.export}: every frame is {FRAME_W} x {FRAME_H}; record the board id and the PNG size")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {SPEC.name} md5 {SPEC_MD5[SPEC.name][:8]} (§0 L{b.line}); hand-off "
                         f"{HANDOFF.name} md5 {SPEC_MD5[HANDOFF.name][:8]} (§H L{H_LINE}); tick size: {FIXTURE_REL} "
                         f"md5 {SPEC_MD5[FIXTURE.name][:8]}")
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




def pack_sheet(sheet_path: Path, out_dir: Path = V4_DIR) -> Path:
    """Pack with compact.py into out_dir/<same name>; the packer writes the source's absolute path into compactOf.file,
    which is then rewritten to the bare file name (the sha256 beside it is the source's, unchanged); check that, every
    packed section <= PACKED_MAX bytes (compact JSON), and that mkcall4.py's `count` agrees."""
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


def md_line3(nn: int) -> str:
    """The render drivers' line (they parse "page `...`" and "theme dark." / "theme light." / "theme hc.")."""
    b = BOARDS[nn]
    return (f"File `{FILE_NAME}`, page `{PAGE}`; export `{b.export}`; sheet `{b.sheet}` (validated); "
            f"theme {b.theme}.")


def write_md(nn: int, sheet_path: Path, *, summary: str = "", frames_info: Iterable[str] = ()) -> Path:
    """The sheet's .md beside it: line 1 "# <board name>", line 3 md_line3(nn), then the summary, frames, the
    validator line and the notes (live checks first). Refuses a banned string."""
    b = BOARDS[nn]
    sp = Path(sheet_path).resolve()
    sh = json.loads(sp.read_text(encoding="utf-8"))
    rc, msg = validate(sp)
    x, y = grid_xy(nn)
    out = [f"# {b.name}", "", md_line3(nn), "",
           summary or f"Board {nn:02d} of ten (§0 L{b.line}: {b.draws}). Grid ({x}, {y}); "
                      f"{sh['board']['w']} x {sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".",
           "", "## Frames", ""]
    out += [f"- `{frame_name(f)}`" for f in frames_of(nn)]
    out += [f"- {ln}" for ln in frames_info]
    out += ["", "## Validator and size", "", f"- `{msg.splitlines()[-1] if msg else ''}` (exit {rc})",
            f"- {len(sh['sections'])} sections, {len(json.dumps(sh))} bytes", ""]
    for kd in ("live_checks", "g_rows", "spec_gaps", "deviations", "copy_keys", "copy_gaps", "fallbacks", "sources",
               "tokens"):
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


def build_all(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
              summary: str = "", frames_info: Iterable[str] = ()) -> tuple[Path, Path, Path]:
    """write_sheet + write_md + pack_sheet for board nn; prints one line per board."""
    p = write_sheet(nn, frames, ann, notes=notes)
    md = write_md(nn, p, summary=summary, frames_info=frames_info)
    pk = pack_sheet(p)
    sh = json.loads(p.read_text(encoding="utf-8"))
    print(f"board {nn:02d}: {p.name} {sh['board']['w']} x {sh['board']['h']}, {len(sh['sections'])} sections; "
          f"packed {len(json.loads(pk.read_text(encoding='utf-8'))['sections'])}")
    return p, md, pk


# --- self-test: python3 -I -B e47d04kit.py selftest
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), f"pinned md5s {spec_md5_ok()}")
    check(sorted(BOARDS) == list(range(1, 11)) and str(len(BOARDS)) == COUNT["boards"], "§0: ten boards 01-10")
    th = [b.theme for b in BOARDS.values()]
    check((th.count("dark"), th.count("light"), th.count("hc")) == (8, 1, 1), "§0 themes 8 dark / 1 light / 1 hc")
    check(TWINS == {9: 8, 10: 8} and str(len(TWINS)) == COUNT["boards.twins"], f"§0 twins {TWINS}")
    check(sorted(FRAME_PLAN) == sorted(BOARDS) and sum(map(len, FRAME_PLAN.values())) == 24,
          f"§H: {sum(map(len, FRAME_PLAN.values()))} frames over ten boards")
    check(all(f.endswith(f" · {BOARDS[nn].theme}") for nn, fs in FRAME_PLAN.items() for f in fs),
          "§H frame themes agree with §0")
    check(PAGE == "E47-D04 — Focus model", f"§0 page {PAGE!r}")
    check(len(BACKGROUNDS) == 12 and all(len(bg.keys) == 6 for bg in BACKGROUNDS)
          and all(k_ in CONTRAST for bg in BACKGROUNDS for k_ in bg.keys.values()), "§7.6: 12 rows x 6 ratios")
    edges = [float(bg.r(t, "edge")) for bg in BACKGROUNDS for t in ("dark", "light", "hc")]
    rings = [float(bg.r(t, "ring")) for bg in BACKGROUNDS for t in ("dark", "light", "hc")]
    check(f"{min(edges):.2f}" == ratio("min.edge") and f"{min(rings):.2f}" == ratio("min.ring")
          and min(edges) >= 3, f"§7.6 min edge {ratio('min.edge')}, min ring {ratio('min.ring')} agree with the rows")
    check(all(float(ratio(f"pair.{t}")) >= 3 for t in ("dark", "light", "hc")), "§7.2 pairs >= 3:1")
    m = re.search(r"(\d+) px normal, (\d+) px thick", SPEC_LINES[EXTENT_LINE - 1])
    check(bool(m) and (extent("normal"), extent("thick")) == (int(m.group(1)), int(m.group(2))),  # type: ignore
          f"§7.5 outer extent {extent('normal')} / {extent('thick')} px")
    check(set(GEOMETRY) == {"normal", "inset", "thick"} and GEOMETRY["normal"].ring.startswith("2 px")
          and GEOMETRY["thick"].ring.startswith("3 px") and GEOMETRY["thick"].halo.startswith("2 px"),
          "§7.1 geometry rows parse and agree with GEOM_PX")
    check(len(COPY) == int(COUNT["copy"]) and COPY["W-2"].text == "DOM ladder, 200 levels, focused best bid",
          "§15 copy deck")
    check(sorted(GROWS) == [f"D04-G{i}" for i in range(1, 7)] and len(RULES) == 12, "§18.2 G-rows, §1.4 rules")
    check(TICK == Decimal("0.10"), f"fixture tick {TICK}")
    lv = ladder(seed=SEED + 7, vanished=[BEST_BID - 2 * TICK])
    check(nearest_survivor(lv, BEST_BID - 2 * TICK) == BEST_BID - TICK, "§8 nearest level, ties toward the touch")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for k_, v in globals().items() if k_.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border|opacity)\.", v)] + [bg.token for bg in BACKGROUNDS]
    check(all(u in toks for u in used), f"kit tokens exist ({len(set(used))}; missing "
                                        f"{sorted(set(u for u in used if u not in toks))})")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: w("W-1")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/', unfilled slot refused")
    NOTES.reset()
    fr = workspace_window(FRAME_PLAN[3][0], {"dom": ladder_table(ladder(), focus=BEST_BID)}, focus_panel="dom",
                          overlays=[callout("W-2", [w("W-2")], 700, 420)])
    blk = frame_block(FRAME_PLAN[3][0], ["self-test frame"])
    ann = annotations(3, [blk], board_lines=["Self-test sheet: one sample frame, not a board of the set"])
    path = write_sheet(3, [fr], ann, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False,
                       notes={"live_checks": ["self-test sheet: not for rendering"]})
    check(path.exists(), f"validator exit 0: {path.name}")
    md = write_md(3, path, summary="Self-test sheet (one sample frame); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    mp = re.search(r"page `([^`]+)`", l3)
    check(bool(mp) and mp.group(1) == PAGE and l3.endswith("theme dark."), f"md line 3 parses: {l3}")  # type: ignore
    check(md_line3(10).endswith("theme hc.") and md_line3(9).endswith("theme light."), "md line 3: light and hc")
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
