"""E47-D06 (#1305) board kit: canvas accessibility (the four layers, the surrogate grammars, the profile and ladder
tables, their states, the equal-status headers with the T2 controls, the parity oracle), eight boards (7 dark, 1 light
twin) as cvsheet JSON sheets for the per-set Penpot file "E47-D06 boards", page "E47-D06 — Canvas accessibility"
(spec §0, hand-off §I).

Offline only. Spec (binding; every string, number, token and frame comes from it): docs/design/E47/E47-D06.md and
E47-D06-handoff.md as the checkout commits them, read by repo-relative path and md5-pinned in DOCS (the kit refuses
drifted bytes: re-read, re-check the cites, re-pin). The recorded instrument fixture gives BTCUSDT's tick size only
(hand-off §I). E47-D04's ring geometry (§7.1 there) is read with `git show <pin>:docs/design/E47/E47-D04.md`, the pin
parsed from the spec's Start line.
Registry (parsed, never typed): §0's board table (BOARDS) and its twins sentence, the hand-off's §I frame plan
(FRAMES), §2's inventory (INV), §4's caps (CAPS), §5's name grammar (NAMES), §6.2's column sets (COLS), §8's labels
(LABELS), §9's oracle (ORACLE), §13's copy deck (COPY), §10's T2 reasons (verbs and keys).

Checkout: the kit sits at docs/design/_tools/sheets/e47-d06/ in a checkout (REPO = four levels up), or anywhere with
CV_CHECKOUT naming the checkout. Raw sheets + .md go to CAP_DIR, packed sheets to V4_DIR (build-notes.md, Build).
Pipeline (one generator per board, gen/gen_NN.py; the twin's generator calls its base board's frame builders):
    frames = [...]; blocks = [(frame id, lines), ...]
    build(nn, frames, blocks) -> raw sheet (validator exit 0), .md (line 3 = the render line), packed sheet
Self-test: python3 -I -B e47d06kit.py selftest

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (frame ids use U+2215); no local path, host or
agent name anywhere in a sheet (BANNED); table cells carry 8 px inner padding a side; every frame has a caption.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KEY, EPIC, ISSUE = "E47-D06", "E47", 1305
KIT_DIR = Path(__file__).resolve().parent


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / "docs" / "design" / EPIC).is_dir() and KIT_DIR.is_relative_to(up / "docs"):
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / "docs" / "design" / EPIC).is_dir():
        raise SystemExit("e47d06kit: run inside a checkout or set CV_CHECKOUT to one")
    return Path(env).resolve()


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
FIXTURE_REL = "packages/fixtures/bybit/2026-10-05/rest/instruments_before.json"
_PATHS = {  # alias -> repo-relative path; AT_BASE aliases are read at SPEC_BASE
    "spec": "docs/design/E47/E47-D06.md",
    "handoff": "docs/design/E47/E47-D06-handoff.md",
    "fixture": FIXTURE_REL,
    "d09e09": "docs/design/E09/E09-D09.md",  # the T2 reason templates
    "screens": "docs/plan/14-screens-catalogue.md",  # the panel titles
    "d04e11": "docs/design/E11/E11-D04.md",  # SCR-047's copy, the stale chip
}
_MD5 = (  # md5 as read, one per _PATHS entry in its order
    "fdde6ab4690b487898b5fc5b5ed4389c",
    "c6ebe77c6e7d04cf59fbcdb03d9f888f",
    "edd9dd2a060c51bd4bd1450307728ddf",
    "20c5d5f43537b6a919553704c06f7c18",
    "77968fd41dc1526b6ed03b7eee0bae52",
    "02f3ff690f4c840aebb734889d0a17c6",
)
# alias -> (path, md5): every read is md5-checked
DOCS = {a: (rel, m) for (a, rel), m in zip(_PATHS.items(), _MD5, strict=True)}
# `14` as the spec cites it: at the base its "Inputs pinned" line names (git show); main has moved on
AT_BASE = frozenset(("screens",))
REV = "r1"
PITCH_X, PITCH_Y = 7000, 4200  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80
ANN_W = 400
ANN_TEXT_W = ANN_W - 32
FRAME_W, FRAME_H = 1280, 800
SECTION_RAW_BUDGET = 9000
PACKED_MAX = 9216
SLASH = "∕"  # U+2215 stands for "/" in node names (Penpot splits names on "/")
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465", "2f746d70")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode()
                    + r"\b", re.I)


def _git_show(sha: str, rel: str) -> bytes:
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{sha}:{rel}"], capture_output=True, timeout=60,
                         check=False)
    if res.returncode != 0:
        raise SystemExit(f"e47d06kit: {rel} at {sha} is not in this checkout's objects")
    return res.stdout


def _spec_base() -> str:
    m = re.search(rb"\*\*Inputs pinned\.\*\* Base `origin/main` `([0-9a-f]{7,40})`",
                  (REPO / DOCS["spec"][0]).read_bytes())
    if not m:
        raise SystemExit("e47d06kit: the spec's Inputs pinned line names no base")
    return m.group(1).decode()


SPEC_BASE = _spec_base()
_BYTES: dict[str, bytes] = {}


def _doc_bytes(k: str) -> bytes:
    if k not in _BYTES:
        rel = DOCS[k][0]
        _BYTES[k] = _git_show(SPEC_BASE, rel) if k in AT_BASE else (REPO / rel).read_bytes()
    return _BYTES[k]


def spec_md5_ok() -> dict[str, bool]:
    return {k: hashlib.md5(_doc_bytes(k)).hexdigest() == m for k, (_p, m) in DOCS.items()}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:
    raise SystemExit(f"e47d06kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
SPEC_LINES = _doc_bytes("spec").decode("utf-8").split("\n")
HANDOFF_LINES = _doc_bytes("handoff").decode("utf-8").split("\n")
_ANCHOR = re.compile(r"([^\s|`(]+?)<!--=([A-Z]+):([^>]+?)-->", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def plain(s: str) -> str:
    """A spec cell without anchors, backticks, bold marks or table escapes."""
    s = _COMMENT.sub("", s)
    return re.sub(r"\*\*|`", "", s).replace("\\|", "|").strip()


def _cells(row: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


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


def table_after(head: str, lines: list[str] | None = None, start: int = 1) -> list[tuple[int, list[str]]]:
    """(line, cells) of the first markdown table after the line holding `head` (header and rule rows dropped)."""
    ls = SPEC_LINES if lines is None else lines
    i = find_line(head, ls, start)
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
                raise SystemExit(f"e47d06kit: anchor {k} carries two values ({vals[k]} / {v})")
            vals[k] = v
    return vals


VAL = _parse_values()


def val(kind: str, key: str) -> str:
    """A figure from the spec's tool output (KeyError when the spec has none: never invent one)."""
    return VAL[f"{kind}:{key}"]


D09E09_LINES = _doc_bytes("d09e09").decode("utf-8").split("\n")

# --- §0: the boards (and the twins sentence); the hand-off's §I: their frames
_S0 = L("**The four layers are unbuilt across surfaces.**")
_P0 = SPEC_LINES[_S0 - 1]
_PAGE_M = re.search(r"Penpot: the file `([^`]+)` \(README:14\), page `([^`]+)`", _P0)
if not _PAGE_M:
    raise SystemExit("e47d06kit: §0 names no Penpot file and page")
FILE_NAME, PAGE = _PAGE_M.group(1), _PAGE_M.group(2)
_EXPORT_PAT = re.search(r"Exports go to `([^`]+)`", _P0).group(1)  # .../E47-D06-NN-<slug>.png
_TWINS_M = re.search(r"(\d+)<!--=COUNT:boards--> boards, (\d+)<!--=COUNT:boards.twins--> of them (light) twins", _P0)
_FRAMES_WORDS = re.search(r"Frames are (\d+) × (\d+) windows at (\w+) density", _P0)
if not (_TWINS_M and _FRAMES_WORDS) or (int(_FRAMES_WORDS.group(1)), int(_FRAMES_WORDS.group(2))) != (FRAME_W, FRAME_H):
    raise SystemExit("e47d06kit: §0's twins sentence or the 1280 x 800 frame sentence is unreadable")
DENSITY = _FRAMES_WORDS.group(3)  # compact
NOT_DRAWN_LINE = L("**Not drawn — the text is binding**")


@dataclass(frozen=True)
class Board:
    nn: int
    name: str
    slug: str
    draws: str
    theme: str  # dark | light
    line: int
    twin: int | None  # the base board of a twin
    frames: tuple[str, ...]  # the §I frame ids, "/" as written

    @property
    def export(self) -> str:
        return _EXPORT_PAT.replace("NN", f"{self.nn:02d}").replace("<slug>", self.slug)

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"


I_LINE = HL("## §I The board plan")


def _parse_frames() -> dict[int, tuple[str, ...]]:
    return {int(c[0]): tuple(re.findall(r"`([^`]+)`", c[1])) for _ln, c in table_after("## §I The board plan",
                                                                                         HANDOFF_LINES)}


FRAMES = _parse_frames()


def _parse_boards() -> dict[int, Board]:
    out = {}
    for ln, c in table_after("## 0. Status, artefacts and the boards"):
        m = re.fullmatch(rf"`({KEY} / (\d{{2}}) ([a-z0-9-]+))`", c[1])
        if not m:
            raise SystemExit(f"e47d06kit: §0 row L{ln} unreadable")
        nn, theme = int(m.group(2)), c[3]
        tw = re.fullmatch(r"(\w+) twin of (\d{2})", plain(c[2]))
        if tw and tw.group(1) != theme:
            raise SystemExit(f"e47d06kit: §0 board {nn:02d}: twin theme {tw.group(1)} != {theme}")
        out[nn] = Board(nn, m.group(1), m.group(3), plain(c[2]), theme, ln, int(tw.group(2)) if tw else None,
                        FRAMES[nn])
    return out


BOARDS = _parse_boards()


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


def frame_name(fid: str) -> str:
    """The §I frame id as a node name: the spec's "/" drawn as U+2215 (cvsheet's path separator is "/")."""
    return fid.replace("/", SLASH)


# --- the registries (§2, §4, §5, §6.2, §8, §9, §13)
def _rows(head: str, keys: tuple[str, ...], start: int = 1) -> dict[str, dict[str, Any]]:
    out = {}
    for ln, c in table_after(head, start=start):
        d = {k_: plain(v) for k_, v in zip(keys, c)}
        d["line"] = ln
        out[d[keys[0]]] = d
    return out


INV = _rows("## 2. The surface inventory", ("iv", "surface", "screen", "l1", "l2", "l3", "l4", "design"))
INV_LINE = L("## 2. The surface inventory")
CAPS = [dict(panel=plain(c[0]), cap=plain(c[1]), figure=plain(c[2]), source=plain(c[3]), status=plain(c[4]), line=ln)
        for ln, c in table_after("## 4. The caps and the distant jump")]
NAMES = _rows("## 5. The accessible name", ("n", "surface", "unit", "values", "flags", "estimated"))
NAME_GRAMMAR = re.search(r"One grammar, ear-first: `([^`]+)`", SPEC_LINES[L("One grammar, ear-first") - 1]).group(1)
SLOT_JOIN, VALUE_JOIN = ". ", ", "  # checked against §5's prose by the self-test (PW:87's ". " and its ", ")
_S62 = L("### 6.2 The column sets")
COLS = {
    "footprint": [plain(c[0]) for _ln, c in table_after("**Footprint**", start=_S62)],
    "profile": [plain(c[0]) for _ln, c in table_after("**Profile**", start=_S62)],
    "ladder": [plain(c[0]) for _ln, c in table_after("**DOM ladder**", start=_S62)],
}
COL_RULE = {
    "profile": {plain(c[0]): plain(c[1]) for _ln, c in table_after("**Profile**", start=_S62)},
    "ladder": {plain(c[0]): plain(c[1]) for _ln, c in table_after("**DOM ladder**", start=_S62)},
}
PERIODS_COL = "Periods"  # §6.2: "TPO adds Periods, PROPOSED"
if "TPO adds Periods, PROPOSED" not in SPEC_LINES[L("**Profile**", _S62) - 1]:
    raise SystemExit("e47d06kit: §6.2 no longer adds the Periods column")
CAPTION_FORM = re.search(r'the caption is "([^"]+)"', SPEC_LINES[L("Every table names its row header") - 1]).group(1)
LABELS = _rows("## 8. Layer 4", ("l", "surface", "template"))
ORACLE = _rows("## 9. The parity oracle", ("p", "iv", "canvas", "mirror", "column", "slot", "source"))


@dataclass(frozen=True)
class Copy:
    key: str
    s: str
    source: str
    status: str
    line: int


COPY = {plain(c[0]): Copy(plain(c[0]), plain(c[1]).strip('"'), plain(c[2]), plain(c[3]), ln)
        for ln, c in table_after("## 13. Copy deck")}


def w(key: str) -> str:
    return COPY[key].s


def fill(template: str, **slots: str) -> str:
    """Fill a {slot} template; every slot must be given and none may be left over."""
    need = set(re.findall(r"\{([^}]+)\}", template))
    if need != set(slots):
        raise KeyError(f"template {template!r} needs {sorted(need)}, got {sorted(slots)}")
    out = template
    for k_, v in slots.items():
        out = out.replace("{" + k_ + "}", v)
    return out




# --- tokens (exact names in token-sync.json; the self-test checks every one)
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_INV, TEXT_ON_ACTION, TEXT_LINK = "color.text.inverse", "color.text.on-action", "color.text.link"
BORDER, BORDER_SUBTLE, BORDER_STRONG, BORDER_SEL = ("color.border.default", "color.border.subtle",
                                                   "color.border.strong", "color.border.selected")
RING = "color.focus.ring"
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
INFO_STRONG, DANGER_STRONG, WARN_STRONG = ("color.status.info.strong", "color.status.danger.strong",
                                           "color.status.warning.strong")
MARK_FILL = "color.status.info.default"  # annotation markers (numbered stops, tags, callouts): not product UI
BUY, SELL, BUY_SUBTLE = "color.buy.default", "color.sell.default", "color.buy.subtle"
C_UP, C_DOWN, C_WICK, AXIS, GRID = ("color.candle.up", "color.candle.down", "color.candle.wick", "color.axis.text",
                                    "color.grid.line")
HM = {i: f"color.heatmap.bid.{i}" for i in range(1, 6)}
HM_ZERO = "color.heatmap.zero"
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD, HEADING_LG, DISPLAY = ("type.ui.heading-sm", "type.ui.heading-md", "type.ui.heading-lg",
                                               "type.ui.display")
NUM, NUM_SM = "type.num.base", "type.num.sm"
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
BUTTON_PADX, DIALOG_PAD = "space.button.paddingX", "space.dialog.padding"
ICON, ICON_SM = "size.icon", "size.icon.sm"
R_CONTROL, R_CARD, R_BADGE, R_DIALOG = "radius.control", "radius.card", "radius.badge", "radius.dialog"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
OPACITY_SCRIM = "opacity.scrim"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, BUTTON_PADX: 12, DIALOG_PAD: 24, ICON: 16, ICON_SM: 12, HAIR: 1, THICK: 2, FOCUS_W: 2}

_TS: dict[str, dict[str, str]] = {}
for _s, _n, _t, _v in json.loads(TOKENS_FILE.read_text(encoding="utf-8")):
    _TS.setdefault(_s, {})[_n] = str(_v)
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}


# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "spec_gaps", "fallbacks", "tokens", "live_checks", "deviations",
              "ambiguities")


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
    """A string the copy deck lacks, drawn from the spec's prose or a kit label (cite the line)."""
    NOTES.add("copy_gaps", line)


def copy_key(line: str) -> None:
    """A PROPOSED copy key a drawn string carries."""
    NOTES.add("copy_keys", line)


def deviate(line: str) -> None:
    NOTES.add("deviations", line)


def ambiguity(line: str) -> None:
    NOTES.add("ambiguities", line)


WARN_SUBTLE, WARN_DEFAULT = "color.status.warning.subtle", "color.status.warning.default"
FP_BID, FP_ASK, FP_IMB = "color.footprint.bid", "color.footprint.ask", "color.footprint.imbalance"
PROF_BAR, PROF_POC, PROF_VA = "color.profile.bar", "color.profile.poc", "color.profile.valuearea"
CVD_BUY, CVD_SELL, CROSSHAIR, ORDER_LINE = "color.cvd.buy", "color.cvd.sell", "color.crosshair", "color.order.line"
SELL_SUBTLE, ACTION_SELECTED, ENV_DEMO = "color.sell.subtle", "color.action.selected", "color.env.demo"
HM_ASK = {i: f"color.heatmap.ask.{i}" for i in range(1, 6)}
DRAW_DEFAULT, NODE_TRIGGER, NODE_ACTION = "color.drawing.default", "color.node.trigger", "color.node.action"

FALLBACKS = {
    "chrome": "kit choice: the shell chrome (TopBar, NavRail, StatusBar) drawn as neutral placeholders (the E47-D03 "
              "kit's SCR-116 chrome); only the panels this spec designs carry words",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)",
    "markers": "kit choice: numbered markers, tags, brackets and callouts are annotation overlays in "
               "color.status.info.default with color.text.inverse words, never product UI",
    "hidden-layer": "kit choice: a hidden layer (the mirror table, a surrogate's bounds, an aria-describedby link) is "
                    "drawn as an annotation callout or a dashed-outline overlay in color.status.info.default; it has "
                    "no pixels in the product (clip-path, R-4)",
    "lock": "the CMP-019 Icon `lock` glyph is the local set's `locked` icon (the same glyph, the set's name)",
    "plot": "kit choice: the canvas surfaces are drawn as simplified synthetic plots (bodies, wicks, bars, bubbles) "
            "from the seeded stream; their own visual design is their tickets', not this spec's",
    "underline": "fallback: a link underline drawn as a 1 px color.text.link rect under the words (no text-decoration "
                 "field in cvsheet)",
}


def fallback(key: str) -> None:
    NOTES.add("fallbacks", FALLBACKS[key])


# --- node primitives (cvsheet v4.3 schema; no inst nodes)
_KEYS = {
    "board": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "kids", "note"},
    "text": {"t", "name", "chars", "typo", "color", "w", "align", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "rect": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "ellipse": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "icon": {"t", "name", "icon", "color", "size", "x", "y", "abs", "alignSelf", "note"},
}


def node(t: str, name: str, **kw: Any) -> Node:
    """A node of type t (None values dropped). Refuses inst nodes, unknown keys, a non-string o.wrap and a banned
    string; a "/" in the name becomes U+2215. Records bound tokens."""
    if t not in _KEYS:
        raise ValueError(f"node type {t!r} not allowed (no inst nodes in the per-set file)")
    name = name.replace("/", SLASH)
    if not name:
        raise ValueError(f"{t} name is empty")
    if isinstance(kw.get("o"), dict):
        kw["o"] = {k: v for k, v in kw["o"].items() if v is not None} or None
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
    # cite marks are drawn plain: a backtick is markdown, never board text (the first render kept them)
    return node("text", name, chars=str(chars).replace("`", ""), typo=typo, color=color, **kw)


def icon(name: str, glyph_: str, color: str = TEXT_2, size: str = ICON, **kw: Any) -> Node:
    if glyph_ not in ICONS_OK:
        raise ValueError(f"icon {glyph_!r} not in the local set {sorted(ICONS_OK)}")
    if size == ICON_SM:
        fallback("icon-sm")
    return node("icon", name, icon=glyph_, color=color, size=size, **kw)


def rect(name: str, w_: float, h: float, fill_: str | None = None, o: dict[str, Any] | None = None, **kw: Any) -> Node:
    opts = dict(o or {})
    if fill_:
        opts["fill"] = fill_
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
         DISPLAY: (24, 1.2, False), NUM: (13, 1.2, True), NUM_SM: (11, 1.2, True)}


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




# --- the illustrative world: a seeded synthetic stream (seed = the issue number, BTCUSDT), declared on every board;
# only the tick size is recorded (hand-off §I). Every figure on a frame is derived from it.
SEED, SYMBOL = ISSUE, "BTCUSDT"


def _tick(symbol: str) -> Decimal:
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

    t = find(json.loads(_doc_bytes("fixture").decode("utf-8")))
    if not t:
        raise LookupError(f"{symbol}: no tickSize in {FIXTURE_REL}")
    return Decimal(t).normalize()


TICK = _tick(SYMBOL)
DATA_LINE = (f"Data: seeded synthetic stream (seed {SEED}, {SYMBOL}, 1m bars); sample data, never a market capture "
             f"(§0 L{_S0}); only the tick size ({TICK}) is the recorded fixture's (hand-off §I L{I_LINE})")
AC3_LINE = L("**AC3 in one line:**")
AC3_PRICE = Decimal(re.search(r"focus on ([\d,]+):", SPEC_LINES[AC3_LINE - 1]).group(1).replace(",", ""))
QTY = Decimal("0.001")  # kit choice: BTC sizes at 3 decimals (the drawn precision, not a fixture field)
N_BARS, FIRST_MIN = 600, 4 * 60  # kit choice: 600 loaded 1m bars, 04:00 to 13:59 UTC
STALE_BAR_MIN = int(re.search(r"bar (\d+):(\d+)", w("W-1")).group(1)) * 60 + int(re.search(r"bar \d+:(\d+)",
                                                                                              w("W-1")).group(1))
VIS_BARS = 40  # kit choice: the chart shows the last 40 bars (13:20 to 13:59)
FP_ROW, PROF_ROW = 5, 10  # kit choice: footprint rows of 5 ticks, profile rows of 10 ticks (SCR-038's Row size)
VA_PCT = 70  # kit choice: SCR-038's "Value area %" setting (`14`:1025) at the conventional 70
PERIOD_MIN = 30  # kit choice: TPO periods of 30 minutes, lettered from A
PROFILE_FROM = 12 * 60  # kit choice: the profile covers 12:00 to 14:00 UTC (periods A to D)
BOOK_LEVELS = 50  # kit choice: 50 drawn book levels a side (the cap is 200, §4)
IMB_RATIO = 3  # `05`'s example threshold (300 %), the kit's reading of the imbalance flag


def hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def hms(sec: int) -> str:
    return f"{sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d}"


def px_fmt(p: Decimal) -> str:
    return f"{p.quantize(TICK):,}"


def q_fmt(q: Decimal) -> str:
    return f"{q.quantize(QTY):,}"


def signed(v: Decimal, fmt: Any = q_fmt) -> str:
    """Signs as text: "+" or U+2212 "−" (`05`:167); zero unsigned."""
    return ("+" if v > 0 else "−" if v < 0 else "") + fmt(abs(v))


def usdt(v: Decimal) -> str:
    return f"{v.quantize(Decimal(1), ROUND_HALF_UP):,}"


@dataclass(frozen=True)
class Print:
    sec: int  # seconds of the day (UTC)
    k: int  # price in ticks above BASE
    qty: Decimal
    buy: bool  # aggressor side


@dataclass(frozen=True)
class Bar:
    minute: int
    o: int
    h: int
    l: int
    c: int
    buy: Decimal
    sell: Decimal

    @property
    def vol(self) -> Decimal:
        return self.buy + self.sell

    @property
    def delta(self) -> Decimal:
        return self.buy - self.sell


def _walk() -> list[Print]:
    rnd = random.Random(SEED)
    k, out = 0, []
    for m in range(FIRST_MIN, FIRST_MIN + N_BARS):
        n = rnd.randint(24, 48)
        secs = sorted(rnd.sample(range(60), min(n, 60)))
        for s in secs:
            k += rnd.choice((-3, -2, -1, 0, 0, 1, 2, 3))
            out.append(Print(m * 60 + s, k, QTY * rnd.randint(1, 900), rnd.random() < 0.5))
        if m == STALE_BAR_MIN:  # kit choice: a refill burst at one level of the 13:42 bar (the estimate it names)
            for _j in range(20):
                out.append(Print(m * 60 + 59, k, QTY * rnd.randint(400, 1200), True))
    return out


_RAW = _walk()
BURST_K = [p.k for p in _RAW if p.sec // 60 == STALE_BAR_MIN][-1]


def _bars(prints: list[Print]) -> list[Bar]:
    by: dict[int, list[Print]] = {}
    for p in prints:
        by.setdefault(p.sec // 60, []).append(p)
    return [Bar(m, ps[0].k, max(p.k for p in ps), min(p.k for p in ps), ps[-1].k,
                sum((p.qty for p in ps if p.buy), Decimal(0)), sum((p.qty for p in ps if not p.buy), Decimal(0)))
            for m, ps in sorted(by.items())]


BARS = _bars(_RAW)
BOOK_BEST_BID_K = BARS[-1].c - 1  # the book's best bid one tick under the last print; the ask one tick above it
MY_ORDERS = ((-12, Decimal("0.500")), (-27, Decimal("0.250")), (8, Decimal("0.400")), (19, Decimal("0.150")))
# kit choice: the account's working orders, in ticks from the best bid (bids) / best ask (asks); the first is AC3's
BASE = AC3_PRICE - (BOOK_BEST_BID_K + MY_ORDERS[0][0]) * TICK  # derived so that AC3's focused level is a drawn price


def price(k: int) -> Decimal:
    return BASE + k * TICK


BASE_K = int(BASE / TICK)  # BASE in absolute ticks


def row_floor(k_: int, row: int) -> int:
    """The low tick of the k_'s row of `row` ticks, rows aligned to absolute prices (a row starts at a multiple of
    row x TICK)."""
    return ((BASE_K + k_) // row) * row - BASE_K


def bar_at(minute: int) -> Bar:
    return next(b for b in BARS if b.minute == minute)


VISIBLE = BARS[-VIS_BARS:]
CURSOR = bar_at(STALE_BAR_MIN)


# --- the footprint of the cursor bar (13:42, W-1's bar): levels of FP_ROW ticks; bid = sells, ask = buys
@dataclass(frozen=True)
class FpLevel:
    k: int  # the level's low tick
    bid: Decimal
    ask: Decimal
    flag: str  # "Bid-stacked" / "Ask-stacked" / "—"
    estimated: str | None  # the CMP-227 display name, or None

    @property
    def delta(self) -> Decimal:
        return self.ask - self.bid


EST_NAME = "Iceberg"  # CMP-227's display name for `iceberg` (E25-D05 §4.5), one of `05`:169's reasons
IMB_WORDS = ("Bid-stacked", "Ask-stacked")  # `05`'s Imbalance flag words, verbatim (§5 N-2)


def _fp_levels(minute: int) -> list[FpLevel]:
    acc: dict[int, list[Decimal]] = {}
    for p in _RAW:
        if p.sec // 60 == minute:
            lv = row_floor(p.k, FP_ROW)
            a = acc.setdefault(lv, [Decimal(0), Decimal(0)])
            a[1 if p.buy else 0] += p.qty
    burst = row_floor(BURST_K, FP_ROW)
    out = []
    for lv in sorted(acc, reverse=True):
        b, a = acc[lv]
        flag = (IMB_WORDS[1] if b and a >= IMB_RATIO * b or (a and not b) else
                IMB_WORDS[0] if a and b >= IMB_RATIO * a or (b and not a) else "—")
        out.append(FpLevel(lv, b, a, flag, EST_NAME if lv == burst else None))
    return out


FOOTPRINT = _fp_levels(CURSOR.minute)
FP_FOCUS = next(x for x in FOOTPRINT if x.estimated)  # AC2 / QA-1: the estimated, imbalanced level
if FP_FOCUS.flag == "—":
    raise SystemExit("e47d06kit: the seeded burst level is not imbalanced: re-seed")


# --- the profile (12:00 to 14:00) and its TPO letters, rows of PROF_ROW ticks
@dataclass(frozen=True)
class ProfLevel:
    k: int
    vol: Decimal
    delta: Decimal
    letters: str
    in_va: bool
    marks: tuple[str, ...]  # "POC" / "VAH" / "VAL" words
    ib: bool  # inside the initial balance (periods A and B)


def _profile() -> tuple[list[ProfLevel], dict[str, Any]]:
    bars = [b for b in BARS if b.minute >= PROFILE_FROM]
    vol: dict[int, list[Decimal]] = {}
    for p in _RAW:
        if p.sec // 60 >= PROFILE_FROM:
            a = vol.setdefault(row_floor(p.k, PROF_ROW), [Decimal(0), Decimal(0)])
            a[0 if p.buy else 1] += p.qty
    letters: dict[int, str] = {lv: "" for lv in vol}
    ib_lo = ib_hi = None
    for i in range((14 * 60 - PROFILE_FROM) // PERIOD_MIN):
        pb = [b for b in bars if PROFILE_FROM + i * PERIOD_MIN <= b.minute < PROFILE_FROM + (i + 1) * PERIOD_MIN]
        lo, hi = row_floor(min(b.l for b in pb), PROF_ROW), row_floor(max(b.h for b in pb), PROF_ROW)
        for lv in letters:
            if lo <= lv <= hi:
                letters[lv] += chr(ord("A") + i)
        if i < 2:
            ib_lo = lo if ib_lo is None else min(ib_lo, lo)
            ib_hi = hi if ib_hi is None else max(ib_hi, hi)
    levels = sorted(vol)
    tot = {lv: vol[lv][0] + vol[lv][1] for lv in levels}
    poc = max(levels, key=lambda lv: (tot[lv], -lv))
    total = sum(tot.values())
    i = j = levels.index(poc)
    acc = tot[poc]
    while acc * 100 < total * VA_PCT:  # the conventional build-out: add the larger neighbour first
        up = tot[levels[j + 1]] if j + 1 < len(levels) else Decimal(-1)
        dn = tot[levels[i - 1]] if i > 0 else Decimal(-1)
        if up >= dn:
            j += 1
            acc += up
        else:
            i -= 1
            acc += dn
    val_, vah = levels[i], levels[j]
    out = []
    for lv in sorted(levels, reverse=True):
        marks = tuple(w_ for w_, x in (("POC", poc), ("VAH", vah), ("VAL", val_)) if lv == x)
        out.append(ProfLevel(lv, tot[lv], vol[lv][0] - vol[lv][1], letters[lv], val_ <= lv <= vah, marks,
                             ib_lo is not None and ib_lo <= lv <= ib_hi))
    return out, dict(poc=poc, vah=vah, val=val_, total=total, pocvol=tot[poc])


PROFILE, PROF_META = _profile()


def pct_of_poc(x: ProfLevel) -> str:
    return f"{(x.vol * 100 / PROF_META['pocvol']).quantize(Decimal('0.1'), ROUND_HALF_UP)} %"


def prof_px(k_: int) -> str:
    return px_fmt(price(k_))


# --- the book at the last print and one tick later (the SCR-117 cadence), BOOK_LEVELS a side; own orders included
@dataclass(frozen=True)
class BookRow:
    k: int
    side: str  # "buy" (a bid level) / "sell" (an ask level)
    size: Decimal
    depth: Decimal  # running total from the best price outward on its side
    mine: Decimal | None  # the account's working order at this level

    @property
    def my_words(self) -> str | None:
        return fill(N6_FLAG, side=self.side, size=q_fmt(self.mine)) if self.mine else None


N6_FLAG = re.search(r"(your \{side\} order \{size\})", NAMES["N-6"]["flags"]).group(1)
BEST_ASK_K = BOOK_BEST_BID_K + 2  # the last print sits between the best bid and the best ask
_MINE = {BOOK_BEST_BID_K + d if d < 0 else BEST_ASK_K + d: q for d, q in MY_ORDERS}


def _book(seed: int, base: dict[int, Decimal] | None = None) -> list[BookRow]:
    rnd = random.Random(seed)
    sizes: dict[int, Decimal] = {}
    for i in range(BOOK_LEVELS):
        for k_ in (BOOK_BEST_BID_K - i, BEST_ASK_K + i):
            sizes[k_] = base[k_] if base else QTY * rnd.randint(5, 3000) + _MINE.get(k_, Decimal(0))
    if base:  # one tick: a seeded fifth of the levels change size (never below the own order)
        for k_ in rnd.sample(sorted(sizes), len(sizes) // 5):
            sizes[k_] = max(_MINE.get(k_, QTY), sizes[k_] + QTY * rnd.randint(-800, 800))
    rows = []
    for side, ks in (("buy", [BOOK_BEST_BID_K - i for i in range(BOOK_LEVELS)]),
                     ("sell", [BEST_ASK_K + i for i in range(BOOK_LEVELS)])):
        run = Decimal(0)
        for k_ in ks:
            run += sizes[k_]
            rows.append(BookRow(k_, side, sizes[k_], run, _MINE.get(k_)))
    return sorted(rows, key=lambda r: -r.k)


BOOK = _book(SEED + 1)
BOOK_NEXT = _book(SEED + 2, {r.k: r.size for r in BOOK})
MY_ROWS = sorted((r for r in BOOK if r.mine), key=lambda r: r.depth)  # My levels only, sorted by Cumulative depth
MY_ROWS_NEXT_HELD = [next(x for x in BOOK_NEXT if x.k == r.k) for r in MY_ROWS]  # patched in place, order held
MY_ROWS_NEXT_SORTED = sorted(MY_ROWS_NEXT_HELD, key=lambda r: r.depth)  # the order re-applied when focus leaves
FOCUS_ROW = next(r for r in MY_ROWS if price(r.k) == AC3_PRICE)


# --- big trades (bubbles): prints at or above the big-trade threshold (kit choice: the loaded series' 99th size
# percentile, the estimate CMP-227 names "Big-trade threshold"); prints at one price, side and second are one cluster
@dataclass(frozen=True)
class Bubble:
    sec: int
    k: int
    buy: bool
    qty: Decimal
    n: int  # prints in the cluster (1 = a single print)

    @property
    def notional(self) -> Decimal:
        return self.qty * price(self.k)


_SIZES = sorted(p.qty for p in _RAW)
BIG_QTY = _SIZES[len(_SIZES) * 99 // 100]


def _bubbles() -> list[Bubble]:
    groups: dict[tuple[int, int, bool], list[Print]] = {}
    for p in _RAW:
        groups.setdefault((p.sec, p.k, p.buy), []).append(p)
    out = []
    for (sec, k_, buy), ps in sorted(groups.items()):
        q = sum((p.qty for p in ps), Decimal(0))
        if q >= BIG_QTY:
            out.append(Bubble(sec, k_, buy, q, len(ps)))
    return out


BUBBLES = _bubbles()
VIS_FROM = VISIBLE[0].minute * 60
BUBBLES_VIS = [b for b in BUBBLES if b.sec >= VIS_FROM]





# --- E47-D04's ring geometry (§7.1 there), read at the pin the spec's Key line names
D04_SHA = re.search(r"E47-D04 \(#1303\), merged as PR #\d+ at `([0-9a-f]{7,40})`",
                    SPEC_LINES[L("**Start.**") - 1]).group(1)


def _d04_lines() -> list[str]:
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{D04_SHA}:docs/design/E47/E47-D04.md"],
                         capture_output=True, text=True, timeout=60, check=False)
    if res.returncode != 0:
        raise SystemExit(f"e47d06kit: E47-D04 at {D04_SHA} is not in this checkout's objects")
    return res.stdout.split("\n")


D04_LINES = _d04_lines()


def _ring_geometry() -> dict[str, tuple[int, int, int, int]]:
    """variant -> (ring px, halo px, offset px, D04 line) from D04 §7.1's table."""
    out = {}
    for ln, c in table_after("### 7.1 Geometry", D04_LINES):
        v = c[0].split(" ")[0]
        px = [int(m) for m in re.findall(r"(\d+) px", " ".join(c[1:4]))]
        if v == "inset":
            continue
        if len(px) != 3:
            raise SystemExit(f"e47d06kit: D04 §7.1 {v} row unreadable")
        out[v] = (px[0], px[1], px[2], ln)
    return out




# outer halo, ring, inner halo, the offset gap, then the control. normal: 1 + 2 + 1 (+ 2 offset); thick: 2 + 3 + 2.
RING_GEOM = _ring_geometry()  # {"normal": (2, 1, 2, line), "thick": (3, 2, 2, line)}
_BANDS = {"normal": ([HAIR], [FOCUS_W]), "thick": ([THICK], [FOCUS_W, HAIR])}


def ring_bands(variant: str) -> list[tuple[str, str]]:
    halo, ring_ = _BANDS[variant]
    if variant == "thick":
        fallback("thick")
    bands = [(CANVAS, t) for t in halo] + [(RING, t) for t in ring_] + [(CANVAS, t) for t in halo]
    r_px, h_px, _o, _ln = RING_GEOM[variant]
    if sum(PX[t] for c, t in bands if c == RING) != r_px or sum(PX[t] for t in halo) != h_px:
        raise SystemExit(f"e47d06kit: the {variant} bands disagree with D04 §7.1 ({r_px} / {h_px} px)")
    return bands


def extent(variant: str, inset: bool = False) -> int:
    return (0 if inset else RING_GEOM[variant][2]) + sum(PX[t] for _c, t in ring_bands(variant))


def _layers(name: str, wd: int, ht: int, variant: str, inner: Node | None, radius: str | None) -> Node:
    bands = ring_bands(variant)
    sizes, s = [], 0
    for _c, t in bands:
        sizes.append(s)
        s += PX[t]
    node_: Node | None = None
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
    """CMP-039 around a control with explicit w and h: a (w + 2e) x (h + 2e) board, e = offset + the bands."""
    e = extent(variant)
    last = PX[ring_bands(variant)[-1][1]]
    off = RING_GEOM[variant][2]
    inner = dict(control, x=last + off, y=last + off)
    inner.pop("abs", None)
    return dict(_layers(name or f"CMP-039 ring · {variant}", int(control["w"]) + 2 * e, int(control["h"]) + 2 * e,
                        variant, inner, radius),
                note=f"focus-visible; {variant}: ring {RING_GEOM[variant][0]} px, halo {RING_GEOM[variant][1]} px each "
                     f"side, offset {off} px (D04 §7.1 L{RING_GEOM[variant][3]})")


def inset_ring(wd: int, ht: int, variant: str = "normal") -> Node:
    """CMP-039 inset (rows): the bands inside the row's box, no offset; the row's last kid at (0, 0)."""
    return dict(_layers(f"CMP-039 ring · inset {variant}", wd, ht, variant, None, None), x=0, y=0, abs=True,
                note="CMP-039 inset: drawn inside the row (E47-D04 §7.1)")


# --- annotation overlays (FALLBACKS markers)
def marker(n: int | str, x: int, y: int, *, name: str | None = None) -> Node:
    fallback("markers")
    wd = 20 if len(str(n)) == 1 else 28
    return hbox(name or f"stop {n}", [text("n", str(n), LABEL, TEXT_INV)],
                {"justify": "center", "fill": MARK_FILL, "radius": R_BADGE}, w=wd, h=20, x=x, y=y, abs=True,
                note="annotation marker (not product UI)")


def tag(label_: str, x: int, y: int, *, name: str | None = None) -> Node:
    fallback("markers")
    return hbox(name or f"tag · {label_[:40]}", [text("label", label_, CAPTION, TEXT_INV)],
                {"padX": INSET_XS, "radius": R_CONTROL, "fill": MARK_FILL}, h=16, x=x, y=y, abs=True,
                note="annotation tag (not product UI)")


def callout(name: str, lines: Iterable[str], x: int, y: int, wd: int = 320) -> Node:
    fallback("markers")
    ls = [ln for ln in lines if ln]
    kids = [text(f"line-{i}", s, CAPTION if i > 1 else LABEL, TEXT_1, w=wd - 2 * PX[INSET_SM])
            for i, s in enumerate(ls, 1)]
    return vbox(f"callout · {name}", kids, {"gap": STACK_XS, "pad": INSET_SM, "fill": OVERLAY, "radius": R_CONTROL,
                                            "stroke": MARK_FILL, "strokeWidth": THICK, "strokeAlign": "inner"},
                w=wd, x=x, y=y, abs=True, note="annotation callout (not product UI)")



# --- the window: the workspace inside the shell at 1280 x 800 (the E47-D03 kit's SCR-116 chrome): TopBar 48 |
# NavRail 64 · the dock 1216 x 704 | StatusBar 48. Compact density: rows and controls 24 px.
TOP_H, STATUS_H, NAV_W = 48, 48, 64
DOCK_W, DOCK_H = FRAME_W - NAV_W, FRAME_H - TOP_H - STATUS_H  # 1216 x 704
DOCK_PAD, GUTTER = 8, 8
ROW_H, CONTROL_H, HEAD_H = 24, 24, 32
ROW_TOKEN = "size.row.compact"


def placeholder(name: str, w_: int, h: int = 12) -> Node:
    fallback("chrome")
    return rect(f"placeholder · {name}", w_, h, HOVER, {"radius": R_CONTROL})


def topbar(wd: int = FRAME_W) -> Node:
    left = hbox("left", [placeholder("wordmark", 88), placeholder("env badge", 56, 20),
                         placeholder("account picker", 136)], {"gap": INSET_MD}, h=TOP_H)
    right = hbox("right", [placeholder("health chip", 120), placeholder("user menu", 72)], {"gap": INSET_MD}, h=TOP_H)
    return hbox("TopBar (placeholder)", [left, right, rect("divider", wd, 1, BORDER_SUBTLE, x=0, y=TOP_H - 1, abs=True)],
                {"padX": INSET_LG, "justify": "space-between", "fill": APP}, w=wd, h=TOP_H,
                note="the shell's TopBar, not this spec's: placeholders only")


def navrail(h: int) -> Node:
    rows = [hbox(f"entry-{i}", [placeholder("glyph", 16, 16)], {"justify": "center"}, w=48, h=32) for i in range(1, 7)]
    return vbox("NavRail (placeholder)", [*rows, rect("divider", 1, h, BORDER_SUBTLE, x=NAV_W - 1, y=0, abs=True)],
                {"gap": INSET_XS, "align": "center", "padY": INSET_SM, "fill": APP}, w=NAV_W, h=h)


def statusbar(wd: int = FRAME_W) -> Node:
    ks = [placeholder("connection chip", 120), placeholder("env word", 56)]
    return hbox("StatusBar (placeholder)", [*ks, rect("divider", wd, 1, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"padX": INSET_LG, "gap": INSET_LG, "fill": APP}, w=wd, h=STATUS_H)


def window(fid: str, dock_kids: list[Node], *, overlays: Iterable[Node] = (), note: str | None = None,
           direction: str = "column") -> Node:
    """One 1280 x 800 window named frame_name(fid): TopBar | NavRail · dock | StatusBar; the dock holds the panels
    (stacked in `direction`, 8 px gutters) and clips. Overlays are absolute, in frame coordinates."""
    dock = box("dock", dock_kids, {"dir": direction, "align": "start", "gap": INSET_SM, "pad": INSET_SM, "fill": APP,
                                   "clip": True}, w=DOCK_W, h=DOCK_H)
    body = hbox("body", [navrail(DOCK_H), dock], {"align": "start"}, w=FRAME_W, h=DOCK_H)
    return vbox(frame_name(fid), [topbar(), body, statusbar(), *overlays], {"fill": APP, "clip": True}, w=FRAME_W,
                h=FRAME_H, note=note)


def sheet_frame(fid: str, kids: list[Node], *, note: str | None = None) -> Node:
    """A 1280 x 800 sheet frame (§0's "as a sheet" boards): the spec's table drawn on color.surface.canvas."""
    return vbox(frame_name(fid), kids, {"fill": CANVAS, "pad": INSET_LG, "gap": STACK_MD, "clip": True}, w=FRAME_W,
                h=FRAME_H, note=note)


# --- controls (compact, 24 px)
def kbd(chars: str) -> Node:
    """CMP-022 Kbd: the key resolved from the keymap, drawn as a keycap."""
    return hbox(f"CMP-022 Kbd · {chars}", [text("key", chars, CAPTION, TEXT_2)],
                {"padX": INSET_XS, "radius": R_CONTROL, "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner"},
                h=18)


def control(name: str, chars: str, *, caret: bool = False, pressed: bool | None = None, lead: str | None = None,
            fill_: str = RAISED, note: str | None = None) -> Node:
    """A compact 24 px button / toggle: optional lead glyph, label (type.ui.label), optional chevron; pressed = the
    selected fill + a check glyph (aria-pressed="true")."""
    kids = [icon("check", "check", TEXT_1, ICON_SM) if pressed else None,
            icon("lead", lead, TEXT_2, ICON_SM) if lead else None, text("label", chars, LABEL, TEXT_1),
            icon("caret", "chevron-down", TEXT_2, ICON_SM) if caret else None]
    nt = note or ""
    if pressed is not None:
        nt = (f'aria-pressed="{str(pressed).lower()}"; ' + nt).strip("; ")
    return hbox(name, kids, {"fill": SELECTED if pressed else fill_, "stroke": BORDER, "strokeWidth": HAIR,
                             "strokeAlign": "inner", "radius": R_CONTROL, "padX": INSET_SM, "gap": INSET_XS},
                h=CONTROL_H, note=nt or None)


def chip(chars: str, *, close: bool = True) -> Node:
    return hbox(f"filter chip · {chars}", [text("label", chars, LABEL, TEXT_1),
                                           icon("remove", "close", TEXT_2, ICON_SM) if close else None],
                {"fill": SELECTED, "radius": R_BADGE, "padX": INSET_SM, "gap": INSET_XS}, h=20,
                note=f'a button "Remove filter {chars}"' if close else None)


def view_switch(first: str, table_on: bool) -> Node:
    """D04E11 D1's `View │ Table` switch (CMP-003 SegmentedControl, manual activation), Alt+T in the panel's context
    (§7, R-8)."""
    return hbox(f"CMP-003 SegmentedControl · {first} │ Table",
                [control(f"segment · {first}", first, pressed=not table_on),
                 control("segment · Table", "Table", pressed=table_on), kbd("Alt+T")],
                {"gap": INSET_XS}, h=CONTROL_H,
                note="the equal-status entry in the panel header, every role (§7, R-8); Alt+T toggles in this "
                     "panel's context (D06-A16); manual activation")


def feed_chip(state: str, label_: str | None = None) -> Node:
    glyph, col = {"Live": ("check", TEXT_2), "Stale": ("warning", WARN_STRONG)}[state]
    return hbox(f"feed chip · {state}", [icon("glyph", glyph, col, ICON_SM),
                                         text("label", label_ or state, CAPTION, TEXT_1)],
                {"stroke": WARN_STRONG if state == "Stale" else BORDER, "strokeWidth": HAIR, "strokeAlign": "inner",
                 "radius": R_BADGE, "padX": INSET_SM, "gap": INSET_XS}, h=20,
                note="the panel's feed chip (E17-D01's states; the word is the signal, never colour alone)")


def panel(name: str, title: str, body: Node | None, *, w_: int, h: int, first: str = "View", table_on: bool = False,
          head_extra: Iterable[Node | None] = (), chips: Iterable[Node] = (), note: str | None = None) -> Node:
    """CMP-080 DockPanel (composition): a 32 px header (title, symbol, the View │ Table switch, extras, chips) over
    the body."""
    head = hbox("panel header", [text("title", title, BODY_STRONG, TEXT_1), text("symbol", SYMBOL, LABEL, TEXT_2),
                                 view_switch(first, table_on), *head_extra,
                                 hbox("chips", list(chips), {"gap": INSET_XS, "justify": "end"}, w=None, h=20)
                                 if chips else None],
                {"gap": INSET_SM, "padX": INSET_SM, "fill": RAISED}, w=w_, h=HEAD_H)
    kids: list[Node | None] = [head, body]
    return vbox(name, kids, {"fill": CANVAS, "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner",
                             "radius": R_CARD, "clip": True}, w=w_, h=h, note=note)


# --- §10's T2 paragraph: the gated items, their reasons (E09-D09 §3.1's templates and verbs, read from its text)
T2_LINE = L("**The T2 paragraph")
_T2 = SPEC_LINES[T2_LINE - 1]


def _d09_template(key: str) -> str:
    for ln in D09E09_LINES:
        m = re.match(rf"\| `{re.escape(key)}` +\| \"([^\"]+)\"", ln)
        if m:
            return m.group(1)
    raise LookupError(key)


def _d09_verb(perm: str) -> str:
    for ln in D09E09_LINES:
        m = re.search(rf"`{re.escape(perm)}` → \"([^\"]+)\"", ln)
        if m:
            return m.group(1)
    raise LookupError(perm)


PERMISSION_T, VIEW_AS_T = _d09_template("rbac.permission"), _d09_template("rbac.view_as")
SPEC_VERBS = re.findall(r'"([^"]+)"', re.search(r"with the verbs (.+?) \(D09E09", _T2).group(1))
ROW_ACTIONS = [(m.group(1), m.group(2)) for m in re.finditer(r"\*\*([A-Z][a-z ]+?)\*\* \(`([a-z_]+:write)`\)", _T2)]
COPY_ROW = re.search(r"\*\*(Copy row as TSV)\*\* is not gated", _T2).group(1)
EXPORT_LABEL = re.search(r"\*\*(Export CSV)\*\* in each table", _T2).group(1)
EXPORT_REASON = re.search(r"SCR-045's own string \"([^\"]+)\"", _T2).group(1)
EXPORT_KEY = re.search(r"PROPOSED state key `([a-z_.]+)`", _T2).group(1)
LOCK_NAME = re.search(r'accessible name "([^"]+)"', _T2).group(1)
MY_LEVELS = re.search(r"the \*\*(My levels only)\*\* filter item without `(orders:read)`", _T2)
MY_LEVELS_LABEL, MY_LEVELS_PERM = MY_LEVELS.group(1), MY_LEVELS.group(2)
TRADE_PERM = re.search(r"trade keys without `(orders:write)`", _T2).group(1)
VIEW_AS_USER = "Morgan"  # synthetic: the view-as target's display name (E09-D09 §3.1 admits the target's name)


def reason(perm: str) -> str:
    v = _d09_verb(perm)
    if v not in SPEC_VERBS:
        raise SystemExit(f"e47d06kit: {perm} -> {v!r} is not one of §10's verbs {SPEC_VERBS}")
    return fill(PERMISSION_T, verb=v)


def view_as_reason() -> str:
    return fill(VIEW_AS_T, user=VIEW_AS_USER)


def lock(color: str = TEXT_3) -> Node:
    fallback("lock")
    return icon("CMP-019 Icon lock", "locked", color, ICON_SM, note=f'decorative=false, accessible name "{LOCK_NAME}"')


def t2_item(label_: str, why: str | None, *, focused: bool = False, wd: int = 260, rid: str = "reason") -> Node:
    """A CMP-041 menu item under CMP-079 RbacGate, T2 rendering 2a inline: the lock glyph leads the full label in
    color.text.tertiary; the reason is the item's second line in color.text.secondary (in the DOM at mount); with
    why=None the item points at a panel's one notice (no per-item reason)."""
    top = hbox("label line", [lock(), text("label", label_, BODY, TEXT_3)], {"gap": INSET_XS}, h=20)
    kids: list[Node | None] = [top, text(rid, why, CAPTION, TEXT_2, w=wd - 16) if why else None]
    it = vbox(f"menu item · {label_} (T2)", kids, {"padX": INSET_SM, "padY": INSET_XS, "gap": STACK_XS,
                                                  "fill": HOVER if focused else None}, w=wd,
              note='role="menuitem" aria-disabled="true" (never disabled, never inert); aria-describedby → '
                   + ("its reason line" if why else "the panel's one notice") + "; Enter / Space change nothing and "
                   "re-show the reason with one polite announcement (W-11)")
    return focus_ring(dict(it, h=round(est_height(it))), radius=R_CONTROL) if focused else it


def menu_item(label_: str, *, wd: int = 260, lead: str | None = None) -> Node:
    return hbox(f"menu item · {label_}", [icon("lead", lead, TEXT_2, ICON_SM) if lead else None,
                                         text("label", label_, BODY, TEXT_1)],
                {"padX": INSET_SM, "gap": INSET_XS}, w=wd, h=28, note='role="menuitem"')


def menu(name: str, items: list[Node], *, wd: int = 276, x: int, y: int) -> Node:
    return vbox(f"CMP-041 Menu · {name}", items, {"fill": OVERLAY, "stroke": BORDER, "strokeWidth": HAIR,
                                                  "strokeAlign": "inner", "radius": R_CONTROL, "pad": INSET_XS,
                                                  "gap": STACK_XS}, w=wd, x=x, y=y, abs=True, note='role="menu"')


def t2_button(label_: str, why: str | None) -> Node:
    """A T2 button (2a inline): the enabled fill goes to color.surface.raised with a color.border.default hairline,
    the lock glyph leads the full label in color.text.tertiary, the reason beside it in color.text.secondary."""
    b = hbox(f"button · {label_} (T2)", [lock(), text("label", label_, LABEL, TEXT_3)],
             {"fill": RAISED, "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner", "radius": R_CONTROL,
              "padX": INSET_SM, "gap": INSET_XS}, h=CONTROL_H,
             note='CMP-079 RbacGate; aria-disabled="true", never disabled, never inert; aria-describedby → '
                  + ("the reason beside it" if why else "the panel's one notice"))
    return hbox(f"T2 · {label_}", [b, text("reason", why, CAPTION, TEXT_2) if why else None], {"gap": INSET_SM},
                h=CONTROL_H)


def notice(why: str, *, wd: int, name: str = "one notice") -> Node:
    """The one-notice form (D09E09:49): one 2a notice in the panel header region; every gated item's
    aria-describedby points at it."""
    return hbox(f"CMP-079 notice · {name}", [lock(TEXT_2), text("reason", why, CAPTION, TEXT_2)],
                {"fill": RAISED, "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner", "radius": R_CONTROL,
                 "padX": INSET_SM, "gap": INSET_XS}, w=wd, h=CONTROL_H,
                note="one node, many pointers (D09E09:49, :236): in the DOM at mount, its text swapped in place")


# --- Layer 3: SCR-045's shell (§6.1): CMP-055 FilterBar, CMP-028 banner, the caption, the CMP-049 grid, CMP-053 and
# CMP-099 in the footer
def _after(head: str, pat: str) -> str:
    """Group 1 of `pat` on the first line after the heading `head` that matches it."""
    for ln in SPEC_LINES[L(head):]:
        m = re.search(pat, ln)
        if m:
            return m.group(1)
    raise LookupError(pat)


REFRESH = _after("### 6.5 The stale banner", r"\*\*(Refresh to current)\*\*")
PAUSE = _after("### 6.4 The in-place patch", r"\*\*(Pause updates)\*\*")
_S66 = SPEC_LINES[L("### 6.6 Empty, no data") + 1]
if "Load more rows" not in _S66:
    raise SystemExit("e47d06kit: §6.6's paragraph moved")
LOAD_MORE = re.search(r"\*\*(Load more rows)\*\*", _S66).group(1)
CLEAR = re.search(r"\*\*(Clear filters)\*\*", _S66).group(1)
NO_MATCH = re.search(r'filtered to zero shows "([^"]+)"', _S66).group(1)  # "No rows match: {filters}"
COUNT_FORM = re.sub(r"\d+ of \d+", "{k} of {n}", re.match(r"(Showing \d+ of \d+ rows)", w("W-2")).group(1))
AS_OF = _after("### 6.5 The stale banner", r'the caption adds "([^"]+)"')  # "values as of {time}"


@dataclass(frozen=True)
class Col:
    name: str
    w: int
    numeric: bool = True


def cell(name: str, chars: str, col: Col, *, color: str = TEXT_1, typo: str | None = None, th: bool = False,
         note: str | None = None, mark: bool = False) -> Node:
    """A grid cell: 8 px inner padding a side; the text must fit (no clipping in a table)."""
    ty = typo or (LABEL if th else NUM if col.numeric else BODY)
    if text_w(chars, ty) > col.w - 2 * PX[INSET_SM]:
        raise ValueError(f"cell {name!r}: {chars!r} ({text_w(chars, ty):.0f} px) overflows {col.name} ({col.w} px)")
    return hbox(name, [text("value", chars, ty, color)],
                {"padX": INSET_SM, "justify": "end" if col.numeric else "start",
                 **({"fill": SELECTED} if mark else {})}, w=col.w, h=ROW_H, note=note)


def header_row(cols: list[Col], *, sort: str | None = None, direction: str = "ascending",
               filter_only: Iterable[str] = ()) -> Node:
    fo = set(filter_only)
    kids = []
    for c in cols:
        s = c.name == sort
        lab = [text("label", c.name, LABEL, TEXT_1 if s else TEXT_2),
               icon("sort", "arrow-up" if direction == "ascending" else "arrow-down", TEXT_1, ICON_SM) if s else None]
        kids.append(hbox(f"th · {c.name}", lab, {"padX": INSET_SM, "gap": INSET_XS,
                                                  "justify": "end" if c.numeric else "start"}, w=c.w, h=ROW_H,
                         note=(f'aria-sort="{direction}"' if s else "filter-only, not sortable" if c.name in fo
                               else 'aria-sort="none"') + ("; the row header column" if c is cols[0] else "")))
    return hbox("header row", kids, {"fill": RAISED, "align": "center"}, w=sum(c.w for c in cols), h=ROW_H,
                note="sticky header; <th scope=\"col\">")


def data_row(i: int, cols: list[Col], values: list[str], *, focused: bool = False, patched: Iterable[str] = (),
             colors: dict[str, str] | None = None, note: str | None = None, actions: str | None = None) -> Node:
    pt, cl = set(patched), colors or {}
    kids = [cell(f"{'th' if j == 0 else 'td'} · {c.name}", v, c, color=cl.get(c.name, TEXT_1),
                 typo=NUM if c.numeric else BODY, mark=c.name in pt,
                 note=('<th scope="row">' if j == 0 else None) if c.name not in pt else
                 "patched in place this tick (the same cell node)") for j, (c, v) in enumerate(zip(cols, values))]
    if actions:
        kids.append(hbox("td · actions", [icon("glyph", "more-horizontal", TEXT_2, ICON_SM)], {"justify": "center"},
                         w=40, h=ROW_H, note=f'a button "Actions for {actions}" (D04E11 §5.1)'))
    wd = sum(c.w for c in cols) + (40 if actions else 0)
    r = hbox(f"row {i:02d}", kids, {"fill": SELECTED if focused else None, "align": "center"}, w=wd, h=ROW_H,
             note=("aria-current=\"true\"; the grid's one stop (roving), focus here" if focused else "") +
                  ("; " if focused and note else "") + (note or "") or None)
    if focused:
        r["kids"] = r["kids"] + [dict(inset_ring(wd, ROW_H), name="CMP-039 ring · inset (focus)")]
    return r


def filter_bar(wd: int, *, chips: Iterable[str] = (), shown: int, total: int, paused: bool = False,
               t2: Node | None = None) -> Node:
    kids = [control("CMP-055 Add filter", "Add filter", caret=True), *[chip(c) for c in chips], t2,
            control("CMP-056 Columns", "Columns", caret=True),
            control(f"toggle · {PAUSE}", PAUSE, pressed=paused, note="PROPOSED (D06-Q6; WCAG 2.2.2), after the "
                                                                     "filters (§6.4)"),
            text("count", fill(COUNT_FORM, k=f"{shown:,}", n=f"{total:,}"), CAPTION, TEXT_2)]
    return hbox("CMP-055 FilterBar", kids, {"gap": INSET_SM, "padX": INSET_SM}, w=wd, h=HEAD_H)


def banner(chars: str, wd: int, key: str = "Shift+R") -> Node:
    """CMP-028 warning banner, polite (D04E11 §7): the copy with the key as a CMP-022 Kbd and the Refresh button."""
    a, b = chars.split(key, 1)
    return hbox("CMP-028 banner · stale", [icon("glyph", "warning", WARN_STRONG), text("copy · a", a.rstrip(), BODY),
                                           kbd(key), text("copy · b", b.lstrip(), BODY),
                                           control(f"button · {REFRESH}", REFRESH, lead="refresh")],
                {"fill": WARN_SUBTLE, "gap": INSET_XS, "padX": INSET_SM}, w=wd, h=HEAD_H,
                note="appears without moving focus; no Tab stop when absent; polite, once (W-1 / W-5)")


def table_caption(panel_: str, scope: str, wd: int, *, clause: str | None = None) -> Node:
    s = fill(CAPTION_FORM, panel=panel_, symbol=SYMBOL, scope=scope) + (f", {clause}" if clause else "")
    return hbox("caption", [text("caption", s, CAPTION, TEXT_2)], {"padX": INSET_SM}, w=wd, h=20,
                note="<caption>: \"{panel}, {symbol}, {scope}\" plus the feed-state clause (§6.2, §6.5)")


def footer(wd: int, *, load_more: bool = True, export_reason: str | None = EXPORT_REASON,
           focus_load: bool = False) -> Node:
    lm = control(f"CMP-053 {LOAD_MORE}", LOAD_MORE, note="appends without moving focus (`05`:195)")
    if focus_load:
        lm = focus_ring(dict(lm, w=round(est_width(lm))))
    return hbox("footer", [lm if load_more else None, hbox("spacer", [], None, w=8, h=8),
                           hbox("CMP-099 PrintExportBar", [t2_button(EXPORT_LABEL, export_reason)], {"gap": INSET_SM},
                                h=CONTROL_H)],
                {"gap": INSET_SM, "padX": INSET_SM, "justify": "space-between"}, w=wd, h=HEAD_H)


# a link label's live-measured width (the underline takes it; the estimate ran 2 px long)
MEASURED_W: dict[str, int] = {"Learn more": 71}


def empty_block(heading: str, cause: str, wd: int, *, action: str | None = None, link: str | None = None,
                live_: str | None = None) -> Node:
    """CMP-026 EmptyState in the grid body (the header row kept): heading, cause, action, link, live sentence."""
    acts = [control(f"button · {action}", action) if action else None,
            vbox(f"CMP-021 Link · {link}", [text("label", link, BODY, TEXT_LINK),
                                             rect("underline", MEASURED_W.get(link, text_w(link, BODY)), 1,
                                                  TEXT_LINK)], None,
                 h=20) if link else None]
    if link:
        fallback("underline")
    return vbox("CMP-026 EmptyState", [text("heading", heading, HEADING_SM, TEXT_1, w=wd - 64,
                                            note="h3 in the panel's heading hierarchy"),
                                       text("cause", cause, BODY, TEXT_2, w=wd - 64),
                                       hbox("actions", acts, {"gap": INSET_MD}, h=CONTROL_H) if any(acts) else None,
                                       text("live", live_, BODY, TEXT_2, w=wd - 64) if live_ else None],
                {"gap": STACK_SM, "padX": INSET_XL, "padY": INSET_XL}, w=wd)


def grid(name: str, header: Node, rows: list[Node], wd: int, h: int, *, below: str | None = None) -> Node:
    kids: list[Node | None] = [header, *rows]
    if below:
        kids.append(text("more rows", below, CAPTION, TEXT_3))
    return vbox(f"CMP-049 Table · {name}", kids, {"padX": INSET_SM, "clip": True}, w=wd, h=h,
                note='role="grid", one Tab stop (APG grid, `05`:95); rows keyed by logical identity (R-6)')


# --- sections (<= SECTION_RAW_BUDGET raw bytes each; the E08-D09 kit's packer, as the E47-D03 kit copies it)
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


CELL_ROW = re.compile(r"/(header row|row \d+|row · [^/]*)/[^/]+$", re.DOTALL)


def lint(nodes: Iterable[Node]) -> list[str]:
    """Kit rules the validator does not check: no inst; icons in the local set; o.wrap a string; flex children without
    text carry h; no '/' in names; table cells padded 8 px a side."""
    bad: list[str] = []
    nodes = list(nodes)

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
        if parent_flex and not n.get("abs") and n["t"] in ("board", "rect", "ellipse") and not n.get("h") \
                and not has_text(n):
            bad.append(f"{p}: flex child without text and without h")
        for k in n.get("kids") or []:
            rec(k, bool(o.get("dir")), p)

    for n in nodes:
        rec(n, False, "")
    for n in nodes:
        for p, x in walk(n):
            if x["t"] == "board" and CELL_ROW.search(p) and "padX" in (x.get("o") or {}) and x["o"]["padX"] != INSET_SM:
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
    """The ONE 400 px column: title, a "Board" block (§0's Draws, theme, twin, frames, export, the data line), one
    block per frame, footer "page <PAGE> · board NN · r1"."""
    b = BOARDS[nn]
    tw = (f" (twin of board {b.twin:02d}: same frames and words; the {b.theme} token set is switched at export)"
          if b.twin else "")
    head = [f"§0 L{b.line}: {b.draws}", f"Theme: {b.theme}{tw}",
            f"Frames (hand-off §I L{I_LINE}): " + "; ".join(b.frames) + f" (each {FRAME_W} x {FRAME_H}, {DENSITY})",
            f"Export: {b.export}", DATA_LINE,
            "Markers, tags, brackets and callouts in color.status.info.default are annotation, not product UI",
            *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


def layout(frames: list[Node], per_row: int) -> list[Node]:
    out, y, i = [], MARGIN, 0
    while i < len(frames):
        row = frames[i:i + per_row]
        x = MARGIN
        for f in row:
            out.append(dict(f, x=x, y=y))
            x += f["w"] + MARGIN
        y += max(f["h"] for f in row) + MARGIN
        i += per_row
    return out


# root heights measured live, the drawing lane's checked `want` (footer end + MARGIN): the one-line data statement
# ends 2 px above the estimate on every board (998 for one frame row, 1878 for two)
MEASURED_H: dict[int, int] = {1: 998, 2: 998, 3: 998, 4: 998, 5: 1878, 6: 1878, 7: 998, 8: 998}


def board(nn: int, frames: list[Node], ann: Node, *, per_row: int = 3) -> tuple[dict[str, Any], list[Node]]:
    """The sheet's root (board name, grid x/y, color.surface.app, clip) hugging its frames + the ONE annotation column
    + MARGIN; a "state: <frame id>" caption 28 px above each frame; the data line under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f) for f in b.frames]
    got = [f["name"] for f in frames]
    if got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != §I {want}")
    for f in frames:
        if (f["w"], f["h"]) != (FRAME_W, FRAME_H):
            raise ValueError(f"board {nn:02d}: frame {f['name']!r} is {f['w']} x {f['h']} (§0: {FRAME_W} x {FRAME_H})")
    if "/" in b.name[len(f"{KEY} / {nn:02d} "):]:
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
    est = int(math.ceil((max(bottom + 24 + 16, MARGIN + ah) + MARGIN) / 8) * 8)
    h = MEASURED_H.get(nn, est)
    if h < est - 8:
        raise ValueError(f"board {nn:02d}: measured h {h} is under the estimate {est}: re-measure")
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    if nn in MEASURED_H:
        live(f"after touchTexts + relayout: the root's h {h} is the measured max(column end, footer end) + {MARGIN} "
             f"(annotation column estimated {ah:.0f} px); read it back")
    else:
        live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root "
             f"(h {h}); set the root's h to max(column end, footer end) + {MARGIN}")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


def write_sheet(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
                per_row: int = 3, out_dir: Path = CAP_DIR,
                name: str | None = None) -> Path:
    """Assemble board nn, split into sections, merge notes, write out_dir/NN-<slug>.json, run the validator (tokens +
    components); RuntimeError unless it exits 0 and the kit lint and the banned scan are clean. Clears NOTES."""
    b = BOARDS[nn]
    out_dir = out_dir.resolve()
    if out_dir not in (CAP_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    root, nodes = board(nn, frames, ann, per_row=per_row)
    if b.theme != "dark":
        live(f"theme: activate the {b.theme} token set before exporting board {nn:02d}; read back one bound fill "
             f"(color.surface.canvas) as the {b.theme} value")
    live(f"export {b.export}; record the board id and the PNG size in §0")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {DOCS['spec'][0]} md5 {DOCS['spec'][1][:8]}, hand-off {DOCS['handoff'][0]} md5 "
                         f"{DOCS['handoff'][1][:8]} (§0 L{b.line}; hand-off §I L{I_LINE}); T2 reason templates "
                         f"{DOCS['d09e09'][0]} md5 {DOCS['d09e09'][1][:8]}; tick size {FIXTURE_REL} md5 "
                         f"{DOCS['fixture'][1][:8]}; ring geometry E47-D04 at {D04_SHA} (§7.1)")
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
    b = BOARDS[nn]
    sp = Path(sheet_path).resolve()
    sh = json.loads(sp.read_text(encoding="utf-8"))
    rc, msg = validate(sp)
    x, y = grid_xy(nn)
    out = [f"# {b.name}", "", md_line3(nn), "",
           summary or f"Board {nn:02d} of {len(BOARDS)} (§0 L{b.line}: {b.draws}). Grid ({x}, {y}); "
                      f"{sh['board']['w']} x {sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".",
           "", "## Frames", ""]
    out += [f"- `{frame_name(f)}` (§I: `{f}`)" for f in b.frames]
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
    if sp.parent == CAP_DIR.resolve():  # the copy beside the kit (the committed sidecar once the kit is in a checkout)
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
          per_row: int = 3,
          notes: dict[str, Iterable[str]] | None = None) -> tuple[Path, Path, Path]:
    """The generators' one call: annotations, sheet, md, packed sheet."""
    ann = annotations(nn, blocks, board_lines=board_lines)
    p = write_sheet(nn, frames, ann, per_row=per_row, notes=notes)
    return p, write_md(nn, p), pack_sheet(p)




# --- the panels' titles (`14`'s screen headings, " panel" and the parenthesis dropped) and SCR-047's copy (D04E11)
SCREENS_LINES = _doc_bytes("screens").decode("utf-8").split("\n")


def screen_title(scr: str) -> str:
    for ln in SCREENS_LINES:
        m = re.match(rf"### {scr} — (.+)$", ln)
        if m:
            return re.sub(r" panel$", "", re.sub(r" \(.*\)$", "", m.group(1)))
    raise LookupError(scr)


D04E11_LINES = _doc_bytes("d04e11").decode("utf-8").split("\n")


def scr047(reason_id: str) -> dict[str, str]:
    """The SCR-047 copy row of D04E11 §11 whose first cell names `reason_id` (heading, cause, action, link, live)."""
    for i, ln in enumerate(D04E11_LINES, 1):
        if ln.startswith(f"| **{reason_id}**"):
            c = _cells(ln)
            q = [re.search(r'"([^"]+)"', x) for x in (c[2], c[3], c[6])]
            return dict(heading=q[0].group(1), cause=q[1].group(1), live=q[2].group(1),
                        action=re.search(r"\*\*([^*]+)\*\*", c[4]).group(1),
                        link=re.search(r"\*\*([^*]+)\*\*", c[5]).group(1), line=str(i))
    raise LookupError(reason_id)


STALE_CHIP = re.search(r"`(Stale \d+s · last [\d:]+)`", "\n".join(D04E11_LINES)).group(1)  # E11-D02 LD-1's form


# --- the canvas plots (FALLBACKS plot): price -> y over a drawn range; the bar slots of a time axis
@dataclass(frozen=True)
class PriceScale:
    lo: int  # ticks
    hi: int
    h: int
    pad: int = 12

    def y(self, k_: int) -> int:
        return self.pad + round((self.hi - k_) * (self.h - 2 * self.pad) / max(1, self.hi - self.lo))


def candle_plot(name: str, bars: list[Bar], wd: int, ht: int, *, cursor: int | None = None,
                extra: Iterable[Node] = (), axis: bool = True) -> tuple[Node, PriceScale, float]:
    """Bodies and wicks of `bars` (color.candle.*), the selected cursor's column (color.crosshair) and a price axis
    of five labels at quarter steps of the drawn range. Returns the plot, its scale and the slot width."""
    fallback("plot")
    ax = 64 if axis else 0
    sc = PriceScale(min(b.l for b in bars) - 4, max(b.h for b in bars) + 4, ht)
    slot = (wd - ax) / len(bars)
    kids: list[Node] = []
    for i, b in enumerate(bars):
        x = round(i * slot)
        if b.minute == cursor:
            kids.append(rect("cursor column", max(4, round(slot)), ht, CROSSHAIR, {"opacity": "opacity.muted"}, x=x,
                             y=0, note="the selected cursor's column (D07E11:139: the plot stop's focus mark)"))
        bw = max(2, round(slot * 0.6))
        top, bot = max(b.o, b.c), min(b.o, b.c)
        kids += [rect(f"wick {hhmm(b.minute)}", 1, max(1, sc.y(b.l) - sc.y(b.h)), C_WICK, x=x + bw // 2, y=sc.y(b.h)),
                 rect(f"body {hhmm(b.minute)}", bw, max(2, sc.y(bot) - sc.y(top)), C_UP if b.c >= b.o else C_DOWN,
                      x=x, y=sc.y(top))]
    if axis:
        for j in range(5):
            k_ = sc.lo + (sc.hi - sc.lo) * j // 4
            kids.append(text(f"axis {j + 1}", px_fmt(price(k_)), NUM_SM, AXIS, x=wd - ax + 6, y=sc.y(k_) - 7))
    return box(name, [*kids, *extra], {"fill": CANVAS, "clip": True}, w=wd, h=ht,
               note=f"canvas role=\"img\" (L-1); {len(bars)} synthetic bars {hhmm(bars[0].minute)} to "
                    f"{hhmm(bars[-1].minute)}; axis labels at quarter steps of the drawn range"), sc, slot


def bubble_r(b: Bubble) -> int:
    """Kit choice: radius 4 + sqrt(notional / 10,000) px (CMP-112's size encoding is E22's)."""
    return 4 + int(math.sqrt(float(b.notional) / 10000))


def bubble_xy(b: Bubble, sc: PriceScale, slot: float, first_min: int) -> tuple[int, int]:
    return round((b.sec / 60 - first_min) * slot), sc.y(b.k)


def mini_plot(name: str, kind: str, wd: int, ht: int) -> Node:
    """A small synthetic plot per inventory panel (board 06's switches): candles, profile bars, heatmap cells, CVD
    columns, bubbles, a speed line, an imbalance strip or a node graph, all from the seeded stream."""
    fallback("plot")
    kids: list[Node] = []
    bars = VISIBLE
    if kind == "candles":
        return candle_plot(name, bars, wd, ht, axis=False)[0]
    if kind == "profile":
        lv = PROFILE[:: max(1, len(PROFILE) // 12)]
        for i, x in enumerate(lv):
            kids.append(rect(f"level {i + 1}", max(2, round(float(x.vol / PROF_META["pocvol"]) * (wd - 16))),
                             max(2, ht // len(lv) - 2), PROF_POC if "POC" in x.marks else
                             PROF_VA if x.in_va else PROF_BAR, x=8, y=4 + i * (ht // len(lv))))
    elif kind == "heatmap":
        rows = [r for r in BOOK if abs(r.k - BOOK_BEST_BID_K) <= 12]
        big = sorted(r.size for r in rows)
        for i, r in enumerate(rows):
            q = 1 + min(4, big.index(r.size) * 5 // len(big))
            kids.append(rect(f"cell {px_fmt(price(r.k))}", wd - 16, max(2, ht // len(rows) - 1),
                             (HM if r.side == "buy" else HM_ASK)[q], x=8, y=i * (ht // len(rows))))
    elif kind in ("cvd", "speed", "strip"):
        slot = wd / len(bars)
        for i, b in enumerate(bars):
            v = float(b.delta) if kind != "speed" else float(b.vol) / 2
            hh = max(1, min(ht // 2 - 4, round(abs(v) * 2)))
            up = v >= 0 or kind == "speed"
            col = (CVD_BUY if up else CVD_SELL) if kind == "cvd" else C_UP if kind == "speed" else \
                (HM_ASK[3] if up else HM[3])
            kids.append(rect(f"{kind} {hhmm(b.minute)}", max(2, round(slot) - 2), hh if kind != "strip" else ht - 8,
                             col, x=round(i * slot), y=(ht // 2 - hh if up else ht // 2) if kind != "strip" else 4))
    elif kind == "bubbles":
        sc = PriceScale(min(b.l for b in bars), max(b.h for b in bars), ht)
        slot = wd / len(bars)
        for b in BUBBLES_VIS:
            x, y = bubble_xy(b, sc, slot, bars[0].minute)
            r = bubble_r(b)
            kids.append(ellipse(f"bubble {hms(b.sec)}", 2 * r, 2 * r, {"fill": C_UP if b.buy else C_DOWN},
                                x=x - r, y=y - r))
    elif kind == "graph":
        for i, (col, lab) in enumerate(((NODE_TRIGGER, "trigger"), (NODE_ACTION, "action"))):
            kids.append(rect(f"node · {lab}", 96, 32, col, {"radius": R_CONTROL}, x=24 + i * 160, y=ht // 2 - 16))
        kids.append(rect("edge", 64, 2, BORDER_STRONG, x=120, y=ht // 2))
    return box(name, kids, {"fill": CANVAS, "clip": True}, w=wd, h=ht, note=f"canvas role=\"img\" ({kind}, synthetic)")


# --- §5's names and §8's labels, filled from the world (one grammar, ear-first)
def _cite_free(s: str) -> str:
    return re.sub(r"\s*\([^()]*:\d+[^()]*\)$", "", s).strip()


def value_words(n: str) -> list[str]:
    return [v.strip() for v in _cite_free(NAMES[n]["values"]).split(",")]


def _sentence(s: str) -> str:
    return s[:1].upper() + s[1:]


def acc_name(unit: str, values: list[str], flags: Iterable[str] = (), est: str | None = None) -> str:
    """{unit}. {values}. {flags as words}. {Estimated, display name}: slots joined by ". " (each a sentence), values
    by ", " (§5); absent slots are dropped."""
    slots = [unit, _sentence(VALUE_JOIN.join(values))]
    fl = [f for f in flags if f and f != "—"]
    if fl:
        slots.append(_sentence(VALUE_JOIN.join(fl)))
    if est:
        slots.append(f"Estimated, {est}")
    return SLOT_JOIN.join(slots)


def bar_name(b: Bar) -> str:
    v = dict(zip(value_words("N-1"), (px_fmt(price(b.o)), px_fmt(price(b.h)), px_fmt(price(b.l)), px_fmt(price(b.c)),
                                      q_fmt(b.vol), signed(b.delta))))
    return acc_name(hhmm(b.minute), [f"{k_} {x}" for k_, x in v.items()])


def fp_name(x: FpLevel) -> str:
    v = dict(zip(value_words("N-2"), (q_fmt(x.bid), q_fmt(x.ask), signed(x.delta))))
    return acc_name(px_fmt(price(x.k)), [f"{k_} {y}" for k_, y in v.items()], [x.flag], x.estimated)


def bubble_name(b: Bubble) -> str:
    unit = fill(NAMES["N-8"]["unit"], side="buy" if b.buy else "sell")
    flags = [fill(NAMES["N-8"]["flags"], n=str(b.n))] if b.n > 1 else []
    return acc_name(unit, [f"{usdt(b.notional)} USDT", px_fmt(price(b.k)), hms(b.sec)], flags,
                    "Trade cluster" if b.n > 1 else None)


def label(l_: str, **slots: str) -> str:
    return fill(_cite_free(LABELS[l_]["template"]), **slots)


def l1_label(bars: list[Bar]) -> str:
    return label("L-1", symbol=SYMBOL, interval="1m", n=str(len(bars)), close=px_fmt(price(bars[-1].c)),
                 **{"±d": signed(bars[-1].delta)})


def l2_label() -> str:
    return label("L-2", symbol=SYMBOL, period=f"{hhmm(PROFILE_FROM)} to 14:00", p=prof_px(PROF_META["poc"]),
                 val=prof_px(PROF_META["val"]), vah=prof_px(PROF_META["vah"]))


# --- the profile and ladder tables (§6.2): columns, values, rows
PROFILE_COLS = [Col("Price", 104), Col("Volume", 104), Col("Delta", 104), Col("% of POC", 96),
                Col("Value area", 136, False), Col(PERIODS_COL, 232, False)]
LADDER_COLS = [Col("Price", 104), Col("Bid size", 96), Col("Ask size", 96), Col("Cumulative depth", 144),
               Col("My orders", 200, False)]
if [c.name for c in PROFILE_COLS[:5]] != COLS["profile"] or [c.name for c in LADDER_COLS] != COLS["ladder"]:
    raise SystemExit("e47d06kit: the drawn columns are not §6.2's sets")
IN_VA, OUT_VA = "In VA", "Outside VA"  # `05`'s Value area words (§6.2 Profile, `05` verbatim)
IB_WORD = "Initial balance"  # §5 N-4's flag word


def prof_values(x: ProfLevel) -> list[str]:
    va = VALUE_JOIN.join([IN_VA if x.in_va else OUT_VA, *x.marks])
    per = VALUE_JOIN.join([x.letters, f"{len(x.letters)} TPO", *([IB_WORD] if x.ib else [])])
    return [prof_px(x.k), q_fmt(x.vol), signed(x.delta), pct_of_poc(x), va, per]


def ladder_values(r: BookRow, *, mine: bool = True) -> list[str]:
    vals = [px_fmt(price(r.k)), q_fmt(r.size) if r.side == "buy" else "—", q_fmt(r.size) if r.side == "sell" else "—",
            q_fmt(r.depth)]
    return vals + ([r.my_words or "—"] if mine else [])


def side_colors(r: BookRow) -> dict[str, str]:
    return {"Bid size": BUY if r.side == "buy" else TEXT_3, "Ask size": SELL if r.side == "sell" else TEXT_3}


def table_body(cols: list[Col], rows: list[Node], *, wd: int, h: int, sort: str | None = None,
               direction: str = "descending", filter_only: Iterable[str] = (), chips: Iterable[str] = (),
               shown: int, total: int, paused: bool = False, banner_text: str | None = None,
               banner_key: str = "Shift+R", caption: tuple[str, str] = ("", ""), clause: str | None = None,
               load_more: bool = False, export_reason: str | None = EXPORT_REASON, empty: Node | None = None,
               below: str | None = None, filter_t2: Node | None = None, left: Node | None = None,
               focus_load: bool = False, actions: bool = True) -> Node:
    """The table in place of the canvas (D04E11 D2): FilterBar, banner, caption, grid (or the empty block under the
    kept header row), footer. Raises when the rows do not fit the grid's height."""
    fixed = HEAD_H + (HEAD_H if banner_text else 0) + 20 + HEAD_H
    gh = h - fixed
    tw = sum(c.w for c in cols) + (40 if actions else 0) + 2 * PX[INSET_SM]
    hdr = header_row(cols, sort=sort, direction=direction, filter_only=filter_only)
    if actions:
        hdr["kids"].append(hbox("th · actions", [], None, w=40, h=ROW_H, note="actions column (no header text)"))
        hdr["w"] += 40
    body_rows: list[Node] = [empty] if empty else rows
    need = ROW_H + sum(est_height(r) for r in body_rows) + (16 if below else 0)
    if need > gh:
        raise ValueError(f"table rows need {need:.0f} px > the grid's {gh}")
    g = grid("grid", hdr, body_rows, tw, gh, below=below)
    mid = hbox("grid area", [left, g], {"align": "start", "gap": INSET_MD}, w=wd, h=gh) if left else g
    return vbox("table view", [filter_bar(wd, chips=chips, shown=shown, total=total, paused=paused, t2=filter_t2),
                               banner(banner_text, wd, banner_key) if banner_text else None,
                               table_caption(caption[0], caption[1], wd, clause=clause), mid,
                               footer(wd, load_more=load_more, export_reason=export_reason, focus_load=focus_load)],
                None, w=wd, h=h)


def native_ladder(rows: list[BookRow], h: int, *, focus_k: int | None = None, describedby: bool = False) -> Node:
    """CMP-108 DOM ladder (native DOM, `15`:1235): price rows with bid / ask size and the own-order marker."""
    cw = (Col("Price", 96), Col("Bid", 80), Col("Ask", 80), Col("Mine", 72, False))
    kids = [hbox("header row", [hbox(f"th · {c.name}", [text("label", c.name, LABEL, TEXT_2)],
                                     {"padX": INSET_SM, "justify": "end" if c.numeric else "start"}, w=c.w, h=ROW_H)
                                for c in cw], {"fill": RAISED}, w=sum(c.w for c in cw), h=ROW_H)]
    for i, r in enumerate(rows, 1):
        vals = [px_fmt(price(r.k)), q_fmt(r.size) if r.side == "buy" else "", q_fmt(r.size) if r.side == "sell" else "",
                q_fmt(r.mine) if r.mine else ""]
        cells = [cell(f"{'th' if j == 0 else 'td'} · {c.name}", v, c, color=(BUY if c.name == "Bid" else SELL
                                                                              if c.name == "Ask" else TEXT_1))
                 if v else hbox(f"td · {c.name}", [], {"padX": INSET_SM}, w=c.w, h=ROW_H)
                 for j, (c, v) in enumerate(zip(cw, vals))]
        nm = (f"Price {px_fmt(price(r.k))}; " + ("bid" if r.side == "buy" else "ask") + f" size {q_fmt(r.size)}"
              + (f"; {r.my_words} at this price" if r.mine else ""))
        rw = hbox(f"row {i:02d}", cells, {"fill": (BUY_SUBTLE if r.side == "buy" else SELL_SUBTLE)
                                          if r.k in (BOOK_BEST_BID_K, BEST_ASK_K) else None}, w=sum(c.w for c in cw),
                  h=ROW_H, note=f'role="row" aria-label "{nm}"' + ("; aria-describedby → the one notice"
                                                                  if describedby else ""))
        if r.k == focus_k:
            rw["kids"].append(dict(inset_ring(rw["w"], ROW_H), name="CMP-039 ring · inset (focus)"))
        kids.append(rw)
    return vbox("CMP-108 DOM ladder (native grid)", kids, {"fill": CANVAS, "clip": True}, w=sum(c.w for c in cw), h=h,
                note='role="grid", native DOM rows (IV-6); no canvas node; the trade keys are not named here (D06-C16)')


def ladder_window_rows(n_side: int, center_bid: int = BOOK_BEST_BID_K) -> list[BookRow]:
    return [r for r in BOOK if center_bid - n_side < r.k <= center_bid + 1 + n_side]


# --- self-test: python3 -I -B e47d06kit.py selftest
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), "source md5 pins")
    check(len(BOARDS) == int(val("COUNT", "boards")) == int(_TWINS_M.group(1)), "§0 board count = COUNT:boards")
    twins = [b for b in BOARDS.values() if b.twin]
    check(len(twins) == int(val("COUNT", "boards.twins")), "twin count = COUNT:boards.twins")
    check(len(twins) * 3 <= len(BOARDS), "twins <= a third")
    check(all(BOARDS[b.twin].frames == tuple(f.replace(f"· {b.theme}", "· dark") for f in b.frames) for b in twins),
          "a twin's frames are its base board's, theme word swapped")
    check(all(BOARDS[n].frames for n in BOARDS) and sorted(FRAMES) == sorted(BOARDS), "§I frames for every board")
    check(all(f.endswith(f"· {b.theme}") for b in BOARDS.values() for f in b.frames), "frame ids end in the theme")
    check(all("/" not in b.name[len(f"{KEY} / {n:02d} "):] for n, b in BOARDS.items()), "no '/' after the prefix")
    check(len(INV) == int(val("COUNT", "inv")), "§2 surfaces = COUNT:inv")
    check(len(ORACLE) == int(val("COUNT", "parity")), "§9 rows = COUNT:parity")
    check(f'PW:87\'s "{SLOT_JOIN}"' in SPEC_LINES[L("One grammar, ear-first") - 1]
          and f'its "{VALUE_JOIN}"' in SPEC_LINES[L("One grammar, ear-first") - 1], "§5's joiners")
    check(fill(w("W-1").replace(hhmm(STALE_BAR_MIN), "{t}"), t=hhmm(CURSOR.minute)) == w("W-1"),
          "W-1's bar is the world's cursor bar")
    check(FOCUS_ROW.mine is not None and price(FOCUS_ROW.k) == AC3_PRICE, "AC3's level is an own-order level")
    check(FP_FOCUS.flag in IMB_WORDS and FP_FOCUS.estimated == EST_NAME, "QA-1's level: imbalanced and estimated")
    check(sum(1 for x in PROFILE if "POC" in x.marks) == 1 and PROF_META["val"] <= PROF_META["poc"] <= PROF_META["vah"],
          "one POC inside the value area")
    check(all(r.depth > 0 for r in BOOK) and len(BOOK) == 2 * BOOK_LEVELS, "the book")
    check(len(BUBBLES_VIS) <= int(next(c["figure"] for c in CAPS if c["cap"].startswith("bubble"))), "bubble set cap")
    check([reason(p) for _l, p in ROW_ACTIONS] == [fill(PERMISSION_T, verb=v) for v in SPEC_VERBS[1:4]],
          "row-action reasons in §10's verb order")
    toks = set(_TS.get("semantic-dark", {})) | set(_TS.get("primitives", {}))
    light = set(_TS.get("semantic-light", {})) | set(_TS.get("primitives", {})) | {
        t for t in _TS.get("semantic-dark", {}) if not t.startswith("color.")}
    used = [v for k_, v in globals().items() if k_.isupper() and isinstance(v, str)
            and re.match(r"(color|type|space|size|radius|border|opacity)\.", v)] + list(HM.values()) + list(
        HM_ASK.values())
    check(all(t in toks for t in used), f"kit tokens exist: {[t for t in used if t not in toks]}")
    check(all(t in light for t in used), f"kit tokens exist in light: {[t for t in used if t not in light]}")
    check(not any(re.search(r"opacity\.disabled|color\.text\.disabled", str(v)) for v in used), "no T2 dimming token")
    SELFTEST_DIR.mkdir(parents=True, exist_ok=True)
    fr = sheet_frame(BOARDS[1].frames[0], [text("t", "self-test", BODY)])
    ann = annotations(1, [(BOARDS[1].frames[0], ["self-test"])])
    try:
        p = write_sheet(1, [fr], ann, out_dir=SELFTEST_DIR, name="00-selftest.json")
        pk = pack_sheet(p, SELFTEST_DIR)
        check(json.loads(pk.read_text())["compactOf"]["file"] == p.name, "packed source is the bare name")
        check('"t": "inst"' not in p.read_text(), "no inst")
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
