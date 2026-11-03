"""E47-D05 (#1304) board kit: SCR-117 accessibility settings, ten boards (8 dark, 1 light twin, 1 high-contrast twin)
as cvsheet JSON sheets for the per-set Penpot file "E47-D05 boards", page "E47-D05 SCR-117" (spec §0, hand-off §H).

Offline only. Spec (binding; every string, number, token and frame comes from it): docs/design/E47/E47-D05.md and
E47-D05-handoff.md as the checkout commits them, read by repo-relative path and md5-pinned in DOCS (the kit refuses
drifted bytes: re-read, re-check the cites, re-pin). Two cited sources are read the same way: the shipped screen
(ASS, its option labels, §7.1 "as shipped") and the recorded instrument fixture (BTCUSDT's tick size only). E47-D04's
ring geometry (§6.2 cites D04:237) is read with `git show <pin>:docs/design/E47/E47-D04.md`, the pin parsed from the
spec's Key line, and its §7.1 rows are checked, not typed.
Registry (parsed, never typed): §0's board table (BOARDS), the hand-off's §H frame plan (FRAMES), §15's copy deck
(COPY), §3's key list (KEYS), §4's labels and descriptions (ROWS), §7.2's classes (CLASSES), §10's states (STATES),
§2's section order (SECTION_ORDER), §5.1's Effective template, §10's search synonyms.

Checkout: the kit sits at docs/design/_tools/sheets/e47-d05/ in a checkout (REPO = four levels up), or anywhere with
CV_CHECKOUT naming the checkout. Raw sheets + .md go to CAP_DIR, packed sheets to V4_DIR (build-notes.md, Build).
Pipeline (one generator per board, gen/gen_NN.py; a twin's generator calls its base board's frame builder):
    frames = [...]; blocks = [(frame id, lines), ...]
    build(nn, frames, blocks) -> raw sheet (validator exit 0), .md (line 3 = the render line), packed sheet
Self-test: python3 -I -B e47d05kit.py selftest

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
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KEY, EPIC, ISSUE = "E47-D05", "E47", 1304
KIT_DIR = Path(__file__).resolve().parent


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / "docs" / "design" / EPIC).is_dir() and KIT_DIR.is_relative_to(up / "docs"):
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / "docs" / "design" / EPIC).is_dir():
        raise SystemExit("e47d05kit: run inside a checkout or set CV_CHECKOUT to one")
    return Path(env).resolve()


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
ASS_REL = "apps/web/src/features/a11y-preferences/AccessibilitySettingsScreen.tsx"
FIXTURE_REL = "packages/fixtures/bybit/2026-10-05/rest/instruments_before.json"
DOCS = {  # key -> (repo-relative path, md5 as read): every read is md5-checked; "ass" is read at SPEC_BASE
    "spec": ("docs/design/E47/E47-D05.md", "e63e13fcaffe5e8e5f94592ed7c24784"),
    "handoff": ("docs/design/E47/E47-D05-handoff.md", "ccc824d08192284a0a665d0a00e76b71"),
    "ass": (ASS_REL, "797df795698e1467fbd445296ede769f"),
    "fixture": (FIXTURE_REL, "edd9dd2a060c51bd4bd1450307728ddf"),
}
REV = "r1"
PITCH_X, PITCH_Y = 7000, 4200  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80
ANN_W = 400
ANN_TEXT_W = ANN_W - 32
FRAME_W, FRAME_H = 1280, 800
ZOOM_W = 640  # the 200 % viewport in CSS px (§0, §11)
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


AT_BASE = frozenset(("ass",))  # read as the spec cites it: at the base its "Inputs pinned" line names (git show)


def _git_show(sha: str, rel: str) -> bytes:
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{sha}:{rel}"], capture_output=True, timeout=60,
                         check=False)
    if res.returncode != 0:
        raise SystemExit(f"e47d05kit: {rel} at {sha} is not in this checkout's objects")
    return res.stdout


def _spec_base() -> str:
    m = re.search(rb"\*\*Inputs pinned\.\*\* Base `origin/main` `([0-9a-f]{7,40})`",
                  (REPO / DOCS["spec"][0]).read_bytes())
    if not m:
        raise SystemExit("e47d05kit: the spec's Inputs pinned line names no base")
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
    raise SystemExit(f"e47d05kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
SPEC_LINES = _doc_bytes("spec").decode("utf-8").split("\n")
HANDOFF_LINES = _doc_bytes("handoff").decode("utf-8").split("\n")
ASS_LINES = _doc_bytes("ass").decode("utf-8").split("\n")
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
                raise SystemExit(f"e47d05kit: anchor {k} carries two values ({vals[k]} / {v})")
            vals[k] = v
    return vals


VAL = _parse_values()


def val(kind: str, key: str) -> str:
    """A figure from the spec's tool output (KeyError when the spec has none: never invent one)."""
    return VAL[f"{kind}:{key}"]


# --- §0: the boards; the hand-off's §H: their frames
_P0 = L("## 0. Status, artefacts and the boards")
_S0 = L("**SCR-117 is built**")
_PAGE_M = re.search(r"Penpot file `([^`]+)` \(README:14\), one page `([^`]+)`", SPEC_LINES[_S0 - 1])
if not _PAGE_M:
    raise SystemExit("e47d05kit: §0 names no Penpot file and page")
FILE_NAME, PAGE = _PAGE_M.group(1), _PAGE_M.group(2)
_EXPORT_PAT = re.search(r"exports go to `([^`]+)`", SPEC_LINES[_S0 - 1]).group(1)  # .../E47-D05-NN-<slug>.png
_DATA_M = re.search(r"data is a seeded synthetic stream \(seed (\d+), (\w+), tick ([\d.]+)\)", SPEC_LINES[_S0 - 1])
_TWINS_M = re.search(r"of them twins in another theme \((\d{2}) (light), (\d{2}) (high contrast)\)", SPEC_LINES[_S0 - 1])
NOT_DRAWN_LINE = L("**Not drawn — the text is binding**")
THEME_OF = {"light": "light", "high contrast": "hc"}


@dataclass(frozen=True)
class Board:
    nn: int
    name: str
    slug: str
    draws: str
    theme: str  # dark | light | hc
    line: int
    twin: int | None
    frames: tuple[str, ...]  # the §H frame ids, "/" as written

    @property
    def export(self) -> str:
        return _EXPORT_PAT.replace("NN", f"{self.nn:02d}").replace("<slug>", self.slug)

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"


H_LINE = HL("## §H The board plan")
FRAME_SUFFIX: dict[str, str] = {}  # frame id -> " at 640 CSS px" etc. (the viewport words §H gives after the id)


def _parse_frames() -> dict[int, tuple[str, ...]]:
    out = {}
    for _ln, c in table_after("## §H The board plan", HANDOFF_LINES):
        ids = re.findall(r"`([^`]+)`", c[1])
        tail = re.sub(r"`[^`]+`,?", "", c[1]).strip()
        if tail and len(ids) == 1:
            FRAME_SUFFIX[ids[0]] = tail
        out[int(c[0])] = tuple(ids)
    return out


FRAMES = _parse_frames()


def _parse_boards() -> dict[int, Board]:
    out = {}
    twins = {int(_TWINS_M.group(1)): THEME_OF[_TWINS_M.group(2)], int(_TWINS_M.group(3)): THEME_OF[_TWINS_M.group(4)]}
    for ln, c in table_after("## 0. Status, artefacts and the boards"):
        m = re.fullmatch(rf"`({KEY} / (\d{{2}}) ([a-z0-9-]+))`", c[1])
        if not m:
            raise SystemExit(f"e47d05kit: §0 row L{ln} unreadable")
        nn = int(m.group(2))
        theme = c[3]
        if nn in twins and twins[nn] != theme:
            raise SystemExit(f"e47d05kit: §0 board {nn:02d} theme {theme} != the twins sentence")
        out[nn] = Board(nn, m.group(1), m.group(3), plain(c[2]), theme, ln, 1 if nn in twins else None, FRAMES[nn])
    return out


BOARDS = _parse_boards()


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


def frame_name(fid: str) -> str:
    """The §H frame id as a node name: the spec's "/" drawn as U+2215 (cvsheet's path separator is "/")."""
    return fid.replace("/", SLASH)


# --- §15 copy deck
@dataclass(frozen=True)
class Copy:
    key: str
    s: str
    source: str
    status: str
    line: int


COPY = {c[0]: Copy(c[0], plain(c[1]), plain(c[2]), plain(c[3]), ln) for ln, c in table_after("## 15. Copy deck")}


def _quoted(s: str) -> list[str]:
    return re.findall(r'"([^"]+)"', s)


def w(key: str, i: int = 0) -> str:
    """The i-th quoted string of a W-n row exactly as §15 gives it (NOTES records the key)."""
    c = COPY[key]
    s = _quoted(c.s)[i]
    NOTES.add("copy_keys", f"{key} (§15 L{c.line}, {c.status}): {s}")
    return s


def fill(template: str, **slots: str) -> str:
    """A {a|b} template filled with one alternative per slot, in order; each value must be one of its slot's."""
    vals = list(slots.values())
    alts = re.findall(r"\{([^{}]+)\}", template)
    if len(alts) != len(vals):
        raise ValueError(f"{template!r}: {len(alts)} slots, {len(vals)} values")
    out = template
    for a, v in zip(alts, vals):
        if "|" in a and v not in a.split("|"):
            raise ValueError(f"{v!r} is not one of {a!r}")
        out = out.replace("{" + a + "}", v, 1)
    return out


# --- §3 keys, §4 rows, §2 sections, §7.2 classes, §10 states
KEYS = {plain(c[0]): dict(values=[plain(v) for v in plain(c[1]).split(" / ")], default=plain(c[2]),
                          applies=plain(c[3]), status=plain(c[5]), line=ln)
        for ln, c in table_after("## 3. The preference key list")}
ROWS = {plain(c[0]): dict(label=plain(c[1]), desc=plain(c[2]), line=ln)
        for ln, c in table_after("## 4. Option rows: labels and descriptions")}
_S2 = L("## 2. Structure, IA and heading")
_ORDER_M = re.search(r"in this order: (.+?); then \*\*([^*]+)\*\*", SPEC_LINES[_S2 + 1])
SECTION_ORDER = re.findall(r"\*\*([^*]+)\*\*", _ORDER_M.group(1))
HELP_SECTION = _ORDER_M.group(2)
H1 = re.search(r"exactly one `h1` \"([^\"]+)\"", SPEC_LINES[_S2 + 1]).group(1)
CLASSES = [plain(c[0]) for _ln, c in table_after("### 7.2 What")]
CLASSES_LINE = L("### 7.2 What")
INFO_TITLE = re.search(r'for the "([^"]+)" note', SPEC_LINES[L("## 14. Components") + 1]).group(1)
STATES = {plain(c[0]): dict(shows=plain(c[1]), board=plain(c[2]), line=ln)
          for ln, c in table_after("## 10. States")}
_S51 = L("Effective value = user override")
EFFECTIVE_TEMPLATE = re.search(r'the template "([^"]+)"', SPEC_LINES[_S51 - 1]).group(1)
TRI_OPTIONS = _quoted(re.search(r'RadioGroup ("[^)]+?") \(', SPEC_LINES[_S51 - 1]).group(1))
_S10 = STATES["SCR-117/search-results"]
SYNONYMS = [s.strip() for s in re.search(r"synonyms: ([a-z ,]+) \(", _S10["shows"]).group(1).split(",")]
_S73 = L("### 7.3 The low-verbosity sample")
_BURST_M = re.search(r"plays a (\d+)-second synthetic BTCUSDT burst \(seed (\d+)\) at (\d+) prints a second with "
                     r"one fill, one reject and one reconnect", SPEC_LINES[_S73 + 1])
BURST_S, PRINTS_PER_S = int(_BURST_M.group(1)), int(_BURST_M.group(3))
LOOP_S = int(re.search(r"on a (\d+)-second loop", SPEC_LINES[L("### 6.1 Motion") + 1]).group(1))
SEARCH_LABEL_GAP = "Search settings"  # copy gap: §10 names "the settings search", §15 gives it no label


def _ass_options(name: str) -> list[str]:
    """The shipped radio labels of one ASS group (§7.1: "as shipped, ASS:123–127")."""
    i = find_line(f'name="{name}"', ASS_LINES)
    j = find_line("onChange", ASS_LINES, i)
    return re.findall(r'label: "([^"]+)"', "\n".join(ASS_LINES[i - 1:j]))


ANNOUNCE_OPTIONS = dict(zip(KEYS["announce_prices"]["values"], _ass_options("announce")))
VERBOSITY_OPTIONS = dict(zip(KEYS["verbosity"]["values"], _ass_options("verbosity")))
CADENCE_OPTIONS = {v: f"{v} s" for v in KEYS["announce_throttle_s"]["values"]}  # §7.1: "1 / 2 / 5 s"


# --- E47-D04's ring geometry (§7.1 there), read at the pin the spec's Key line names
D04_SHA = re.search(r"`E47-D04\.md` at `([0-9a-f]{7,40})`", SPEC_LINES[L("**Key.**") - 1]).group(1)


def _d04_lines() -> list[str]:
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{D04_SHA}:docs/design/E47/E47-D04.md"],
                         capture_output=True, text=True, timeout=60, check=False)
    if res.returncode != 0:
        raise SystemExit(f"e47d05kit: E47-D04 at {D04_SHA} is not in this checkout's objects")
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
            raise SystemExit(f"e47d05kit: D04 §7.1 {v} row unreadable")
        out[v] = (px[0], px[1], px[2], ln)
    return out


RING_GEOM = _ring_geometry()  # {"normal": (2, 1, 2, 235), "thick": (3, 2, 2, 237)}


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


def deviate(line: str) -> None:
    NOTES.add("deviations", line)


def ambiguity(line: str) -> None:
    NOTES.add("ambiguities", line)


FALLBACKS = {
    "chrome": "kit choice: the shell chrome (TopBar, NavRail, StatusBar) and the other CMP-086 entries drawn as neutral "
              "placeholders; only SCR-117's content, its SettingsNav entry and the reveal hosts' named parts are drawn",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)",
    "thick": "fallback: the 3 px thick ring (PROPOSED border.focus.thick, D04-G5: not a token) drawn as two adjacent "
             "strokes in color.focus.ring, border.focus (2) + border.hairline (1); its 2 px halos as border.thick",
    "markers": "kit choice: numbered stop markers, tags and callouts are annotation overlays in "
               "color.status.info.default with color.text.inverse words, never product UI",
    "scrim": "fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim",
    "type-150": "fallback: no type token at 150 %: each role is drawn with the token nearest 1.5 x its size "
                "(caption 11 -> heading-md 16, label 12 / body 13 -> heading-lg 20, heading-sm 14 / heading-md 16 -> "
                "display 24), as the E47-D03 kit does",
    "zoom-200": "kit choice (the E47-D03 kit's): the 200 % frame draws the 640 CSS px page at 1:1 in 640 x 800 strips "
                "side by side (CSS y 0-800, 800-1600, ...); the device shows it at 2 x; the first 640 x 400 CSS viewport "
                "is outlined on strip 1",
    "full-length": "kit choice: a 1280-wide window whose page is longer than the 800 px viewport is drawn at its full "
                   "scroll length (the fixed TopBar and StatusBar drawn once, at the top and the bottom), with the "
                   "800 px fold marked by a dashed annotation line",
    "underline": "fallback: the link underline (A11Y-F-0018) drawn as a 1 px color.text.link rect under the words "
                 "(no text-decoration field in cvsheet)",
    "border-control": "fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control "
                      "boundaries bind border.hairline in dark and light and border.thick in high contrast",
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


class Scale:
    """Text scale (§11: 100 / 112 / 125 / 150 %); 1.5 maps each role to the nearest token (FALLBACKS type-150)."""
    _T150 = {CAPTION: HEADING_MD, LABEL: HEADING_LG, BODY: HEADING_LG, BODY_STRONG: HEADING_LG, HEADING_SM: DISPLAY,
             HEADING_MD: DISPLAY, NUM: HEADING_LG, NUM_SM: HEADING_MD}

    def __init__(self, factor: float = 1.0) -> None:
        self.f = factor

    def __call__(self, typo: str) -> str:
        if self.f == 1.0:
            return typo
        fallback("type-150")
        return self._T150[typo]

    def px(self, v: int) -> int:
        return int(round(v * self.f))


S1 = Scale(1.0)


# --- the illustrative world: a seeded synthetic stream (seed 1304), declared on every board; every figure on a frame
# is derived from it (the burst's prints, the heatmap column, the candles, the order line, the drawing point)
SEED = int(_DATA_M.group(1))
SYMBOL = _DATA_M.group(2)


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
    return Decimal(t)


TICK = _tick(SYMBOL)
if TICK != Decimal(_DATA_M.group(3)):
    raise SystemExit(f"e47d05kit: §0's tick {_DATA_M.group(3)} != the fixture's {TICK}")
ANCHOR_PRICE = Decimal("64250.0")  # synthetic anchor (kit choice); every price is ANCHOR_PRICE + k x TICK
DATA_LINE = (f"Data: seeded synthetic stream (seed {SEED}, {SYMBOL}, tick {TICK.normalize()}); sample data, never a "
             f"market capture (§0 L{_S0}); the tick size is the recorded fixture's")


def px_fmt(p: Decimal) -> str:
    return f"{p.quantize(TICK.normalize()):,}".replace(",", " ")


@dataclass(frozen=True)
class Print:
    t: Decimal  # seconds from the burst start, 0.025 s apart (40 a second)
    price: Decimal


@dataclass(frozen=True)
class Event:
    t: Decimal
    cls: str  # a §7.2 class, verbatim


@dataclass(frozen=True)
class Candle:
    minute: int
    o: Decimal
    h: Decimal
    l: Decimal
    c: Decimal


@dataclass(frozen=True)
class World:
    prints: tuple[Print, ...]
    events: tuple[Event, ...]
    heat: tuple[tuple[Decimal, int], ...]  # (price, resting size) top = highest price
    candles: tuple[Candle, ...]

    @property
    def last(self) -> Decimal:
        return self.prints[-1].price

    def price_at(self, t: Decimal) -> Decimal:
        return [p for p in self.prints if p.t <= t][-1].price


def make_world() -> World:
    rnd = random.Random(SEED)
    n = BURST_S * PRINTS_PER_S
    step = Decimal(1) / PRINTS_PER_S
    k, prints = 0, []
    for i in range(n):
        k += rnd.choice((-1, 0, 0, 1))
        prints.append(Print(step * i, ANCHOR_PRICE + k * TICK))
    # one fill, one reject, one reconnect inside the burst (§7.3), at seeded tenths of a second
    ev_cls = (CLASSES[0], CLASSES[1], CLASSES[4])
    ts = sorted(rnd.sample(range(10, BURST_S * 10 - 10), 3))
    events = tuple(Event(Decimal(t) / 10, c) for t, c in zip(ts, ev_cls))
    last = prints[-1].price
    heat = tuple((last + (4 - j) * TICK, rnd.randint(1, 40) * 25) for j in range(9))
    candles, o = [], ANCHOR_PRICE - 40 * TICK
    for m in range(6):
        path = [o]
        for _ in range(20):
            path.append(path[-1] + rnd.choice((-3, -1, 0, 1, 3)) * TICK)
        candles.append(Candle(m, path[0], max(path), min(path), path[-1]))
        o = path[-1]
    return World(tuple(prints), events, heat, tuple(candles))


WORLD = make_world()


def heat_stop(size: int) -> int:
    """The heatmap ramp stop (1 … 5) of a resting size: quintiles of the column's own sizes."""
    sizes = sorted(s for _p, s in WORLD.heat)
    rank = sizes.index(size)
    return 1 + min(4, rank * 5 // len(sizes))


# --- CMP-039 the ring (E47-D04 §7.1), nested stroke-only boards so every band is token-bound (the E47-D04 kit's way):
# outer halo, ring, inner halo, the offset gap, then the control. normal: 1 + 2 + 1 (+ 2 offset); thick: 2 + 3 + 2.
_BANDS = {"normal": ([HAIR], [FOCUS_W]), "thick": ([THICK], [FOCUS_W, HAIR])}


def ring_bands(variant: str) -> list[tuple[str, str]]:
    halo, ring_ = _BANDS[variant]
    if variant == "thick":
        fallback("thick")
    bands = [(CANVAS, t) for t in halo] + [(RING, t) for t in ring_] + [(CANVAS, t) for t in halo]
    r_px, h_px, _o, _ln = RING_GEOM[variant]
    if sum(PX[t] for c, t in bands if c == RING) != r_px or sum(PX[t] for t in halo) != h_px:
        raise SystemExit(f"e47d05kit: the {variant} bands disagree with D04 §7.1 ({r_px} / {h_px} px)")
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


def fold_line(name: str, y: int, wd: int, x: int = 0) -> Node:
    fallback("full-length")
    live(f"'{name}': set its stroke to dashed style (post-step), so it reads as an annotation, not a divider")
    return rect(name, wd, 2, None, {"stroke": MARK_FILL, "strokeWidth": HAIR, "strokeAlign": "inner"}, x=x, y=y,
                abs=True, note="annotation: the viewport fold (not product UI)")


# --- the window: SCR-117 inside the shell at 1280 x 800 (the E47-D03 kit's SCR-116 chrome): TopBar 48 | NavRail 64 ·
# CMP-086 settings list 208 · content 1008 | StatusBar 48. Compact density: controls 24 px.
TOP_H, STATUS_H, NAV_W, SET_NAV_W = 48, 48, 64, 208
BODY_H = FRAME_H - TOP_H - STATUS_H  # 704
CONTENT_W = FRAME_W - NAV_W - SET_NAV_W  # 1008
CONTENT_PAD = 24
COL_W = CONTENT_W - 2 * CONTENT_PAD  # 960 = the 60 rem max-width (§2)
ROWS_W, TILE_W, COL_GAP = 560, 360, 24
CONTROL_H = 24


def border_w(theme: str) -> str:
    fallback("border-control")
    return THICK if theme == "hc" else HAIR


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


def settings_nav(h: int, *, focused: bool = False) -> Node:
    """CMP-086 (`nav aria-label="Settings"`): placeholder entries and the PROPOSED own entry "Accessibility" (BQ-8,
    D05-A6), its selected label in color.text.link with the selected underline in color.border.selected."""
    lab = text("label", H1, BODY_STRONG, TEXT_LINK)
    cur = vbox(f"entry · {H1} (current)", [lab, rect("selected underline", 96, 2, BORDER_SEL)],
               {"gap": STACK_XS, "padX": INSET_MD, "padY": INSET_XS}, w=SET_NAV_W - 16, h=36,
               note='aria-current="page"; its own SettingsNav entry and sub-route (BQ-8, D05-A6, PROPOSED)')
    if focused:
        cur = focus_ring(cur)
    ents = [hbox(f"entry-{i}", [placeholder("label", 96 + 8 * (i % 3))], {"padX": INSET_MD}, w=SET_NAV_W - 16, h=28)
            for i in range(1, 5)]
    return vbox("CMP-086 SettingsNav", [*ents[:2], cur, *ents[2:],
                                       rect("divider", 1, h, BORDER_SUBTLE, x=SET_NAV_W - 1, y=0, abs=True)],
                {"gap": INSET_XS, "pad": INSET_SM, "fill": RAISED}, w=SET_NAV_W, h=h)


def window(name: str, content: Node, *, settings: bool = True, body_h: int = BODY_H, overlays: Iterable[Node] = (),
           note: str | None = None, nav_focused: bool = False) -> Node:
    """One window: TopBar | NavRail · (SettingsNav) · main | StatusBar. body_h > BODY_H draws the full scroll length
    (FALLBACKS full-length); the main column clips at the viewport otherwise (a scrolled view)."""
    main_w = CONTENT_W if settings else FRAME_W - NAV_W
    main = box("main", [dict(content, x=0, y=0)], {"fill": APP, "clip": True}, w=main_w, h=body_h)
    body = hbox("body", [navrail(body_h), settings_nav(body_h, focused=nav_focused) if settings else None, main],
                {"align": "start"}, w=FRAME_W, h=body_h)
    fh = TOP_H + body_h + STATUS_H
    kids: list[Node] = [topbar(), body, statusbar()]
    if body_h > BODY_H:
        kids.append(fold_line("dashed · fold · 800 px viewport", FRAME_H, FRAME_W))
    kids += list(overlays)
    return vbox(name, kids, {"fill": APP, "clip": True}, w=FRAME_W, h=fh, note=note)


# --- page state: every value a key can hold (§3), the OS signals, and what the frame shows
SECTION_KEYS = {  # §2 names the five sections and their order, not their rows: the kit's reading (ambiguity note)
    "Motion": ("reduced_motion", "disable_canvas_animation"),
    "Contrast and focus": ("increased_contrast", "thick_focus_ring", "always_show_focus_ring"),
    "Data views": ("always_show_tables",),
    "Announcements": ("announce_prices", "announce_throttle_s", "verbosity"),
    "Interaction": ("keyboard_only", "larger_hit_targets"),
}
SECTION_TILE = {"Motion": "motion", "Contrast and focus": "focus", "Data views": "table-alt",
                "Announcements": "announcements"}
TRI = ("reduced_motion", "increased_contrast")


def section_reading_note() -> None:
    ambiguity(f"§2 L{_S2 + 2} gives the five FormSections and their order but not which rows each holds: the kit "
              "groups §3's keys by their words — " + "; ".join(f"{s}: {', '.join(ks)}" for s, ks in SECTION_KEYS.items())
              + " (the tiles: motion, focus, table-alt and announcements after their group's last row, §6)")


@dataclass(frozen=True)
class PS:
    theme: str = "dark"
    values: tuple[tuple[str, str], ...] = ()  # overrides of §3's defaults, (key, value)
    os_reduce: bool = False  # prefers-reduced-motion: reduce
    os_contrast: bool = False  # prefers-contrast: more
    forced: bool = False  # forced-colors: active
    status: str | None = None  # the status region's text (ASS:74), shown as a line under the scope line
    w16: tuple[str, ...] = ()  # rows showing W-16
    focus: str | None = None  # a key, "nav", "search", "reset:<key>", "section-reset:<section>", "tile:<section>"
    sc: Scale = S1
    stacked: bool = False
    width: int = CONTENT_W
    search: str | None = None
    sections: tuple[str, ...] = tuple(SECTION_ORDER) + (HELP_SECTION,)
    header: bool = True
    motion_running: bool = False  # the motion tile's loop (it runs while focus or the pointer is in its group, §13.2)
    ann_at: Decimal | None = None  # the announcement tile mid-play at this burst second (None: idle or done)
    ann_done: bool = False
    focus_variant: str = "normal"
    markers: tuple[tuple[str, int], ...] = ()  # board 10: (stop id, number)

    def v(self, key: str) -> str:
        return dict(self.values).get(key, KEYS[key]["default"])

    def on(self, key: str) -> bool:
        return self.v(key) == "true"

    def modified(self, key: str) -> bool:
        return self.v(key) != KEYS[key]["default"]

    def mark(self, stop: str) -> int | None:
        return dict(self.markers).get(stop)


def effective(ps: PS, key: str) -> tuple[bool, str]:
    """(effective on, the Effective line) for a tri-state (§5.1): override ?? OS signal ?? default; forced colours
    force contrast on (§5.4, W-26)."""
    os_sig = ps.os_reduce if key == "reduced_motion" else ps.os_contrast
    if key == "increased_contrast" and ps.forced:
        return True, w("W-26")
    v = ps.v(key)
    if v in ("on", "off"):
        on, src = v == "on", "your choice"
    elif os_sig:
        on, src = True, "from your system setting"
    else:
        on, src = False, "the product default"
    return on, fill(EFFECTIVE_TEMPLATE, a="On" if on else "Off", b=src)


def motion_full(ps: PS) -> bool:
    """§6.1: the tile animates only when the effective motion is full (reduced motion off and canvas animation on)."""
    return not effective(ps, "reduced_motion")[0] and not ps.on("disable_canvas_animation")


def marker_inline(n: int) -> Node:
    fallback("markers")
    return hbox(f"stop {n}", [text("n", str(n), LABEL, TEXT_INV)],
                {"justify": "center", "fill": MARK_FILL, "radius": R_BADGE}, w=20 if n < 10 else 28, h=20,
                note="annotation marker: Tab stop (not product UI)")


def marked(ps: PS, stop: str, n_: Node) -> Node:
    m = ps.mark(stop)
    return hbox(f"stop {m} + {n_['name']}", [marker_inline(m), n_], {"gap": INSET_SM}) if m else n_


# --- controls (compact, 24 px)
def button(chars: str, ps: PS, *, name: str | None = None, focused: str | None = None, lead: Node | None = None) -> Node:
    sc = ps.sc
    kids = ([lead] if lead else []) + [text("label", chars, sc(BODY_STRONG), TEXT_1)]
    wd = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    b = hbox(name or f"button · {chars}", kids, {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL,
                                                 "justify": "center", "fill": ACTION_SECONDARY, "stroke": BORDER_STRONG,
                                                 "strokeWidth": border_w(ps.theme), "strokeAlign": "inner"},
             w=wd, h=max(CONTROL_H, round(text_h(sc(BODY_STRONG))) + 8), note="CMP-001 Button (secondary)")
    return focus_ring(b, focused) if focused else b


# the live check's measured widths of the two links' words, keyed by (words, the kit's estimate): 100 % text on 01, 02
# and 03, 150 % on 10 (the drawn underlines were set to these)
MEASURED_UNDERLINE = {("Read the accessibility statement", 233): 199, ("Change shortcuts", 116): 110,
                      ("Read the accessibility statement", 358): 314, ("Change shortcuts", 179): 173}


def link(chars: str, ps: PS) -> Node:
    fallback("underline")
    t = text("words", chars, ps.sc(BODY), TEXT_LINK)
    est = round(text_w(chars, ps.sc(BODY)))
    wd = MEASURED_UNDERLINE.get((chars, est), est)
    live(f"link '{chars}': after relayout set the underline's width to the words' measured width ({wd} px expected)")
    return vbox(f"link · {chars}", [t, rect("underline", wd, 1, TEXT_LINK)], {"gap": STACK_XS},
                note="a real link, same tab, underlined in every theme (§9, A11Y-F-0018)")


def radio(label_: str, checked: bool, ps: PS, *, t2: bool = False, focused: bool = False) -> Node:
    edge = BORDER if t2 else BORDER_STRONG
    dot = [ellipse("dot", 8, 8, {"fill": TEXT_3 if t2 else ACTION_PRIMARY}, x=4, y=4, abs=True)] if checked else []
    circle = box("circle", [ellipse("outline", 16, 16, {"fill": CANVAS, "stroke": edge, "strokeWidth": border_w(ps.theme),
                                                       "strokeAlign": "inner"}, x=0, y=0, abs=True), *dot], w=16, h=16)
    r = hbox(f"radio · {label_}", [circle, text("label", label_, ps.sc(BODY), TEXT_3 if t2 else TEXT_1)],
             {"gap": INSET_SM}, h=max(CONTROL_H, round(text_h(ps.sc(BODY)))),
             note=f'role="radio" aria-checked="{str(checked).lower()}"' + (' aria-disabled="true"' if t2 else ""))
    if focused:
        r = dict(r, w=round(est_width(r)))
        r = focus_ring(r)
    return r


def switch(on: bool, ps: PS) -> Node:
    knob = ellipse("knob", 12, 12, {"fill": TEXT_ON_ACTION if on else TEXT_2}, x=22 if on else 4, y=4, abs=True)
    return box("switch", [knob], {"fill": ACTION_PRIMARY if on else HOVER, "radius": R_BADGE, "stroke": BORDER_STRONG,
                                  "strokeWidth": border_w(ps.theme), "strokeAlign": "inner"}, w=38, h=20,
               note=f'role="switch" aria-checked="{str(on).lower()}"; Enter / Space toggles (`15`:87)')


def changed_line(key: str, ps: PS) -> Node:
    lab = ROWS[key]["label"]
    reset_ = button(w("W-24", 1), ps, name=f"button · Reset {lab}",
                    focused=ps.focus_variant if ps.focus == f"reset:{key}" else None)
    reset_ = dict(reset_, note=f'CMP-001; accessible name "{fill(_quoted(COPY["W-24"].s)[2], label=lab)}" (W-24); '
                               "activating it moves focus to the option's control (§10)")
    return hbox("changed", [text("Changed", w("W-24", 0), ps.sc(CAPTION), TEXT_2), marked(ps, f"reset:{key}", reset_)],
                {"gap": INSET_SM})


def row_width(ps: PS) -> int:
    return (ps.width - 2 * (16 if ps.width < CONTENT_W else CONTENT_PAD)) if ps.stacked or ps.sc.f > 1 else ROWS_W


# --- option rows (§4: the label, the description as the row's aria-describedby target, the control, §5's lines)
def _desc(key: str, ps: PS, wd: int) -> Node:
    return text("description", ROWS[key]["desc"], ps.sc(CAPTION), TEXT_2, w=wd)


def tri_row(key: str, ps: PS) -> Node:
    """CMP-006 RadioGroup "Follow my system" / "On" / "Off" + the Effective line (§5.1); T2 under forced colours
    (§5.4's T2 paragraph: lock + full label in color.text.tertiary, raised fill + border.default hairline, the reason
    W-17 under the control in color.text.secondary, aria-disabled, still in the Tab order)."""
    sc, wd = ps.sc, row_width(ps)
    t2 = key == "increased_contrast" and ps.forced
    lab = ROWS[key]["label"]
    head = (hbox("label", [icon("lock", "locked", TEXT_3, note='CMP-019 Icon lock, decorative=false, name "Not available"'),
                           text("words", lab, sc(BODY_STRONG), TEXT_3)], {"gap": INSET_XS},
                 note="T2: the full label in color.text.tertiary, the lock glyph leading it in the same colour")
            if t2 else text("label", lab, sc(BODY_STRONG), TEXT_1))
    val_ = ps.v(key)
    opts = list(zip(KEYS[key]["values"], TRI_OPTIONS))
    focused = ps.focus == key
    radios = [radio(lbl, val_ == v, ps, t2=t2, focused=focused and val_ == v) for v, lbl in opts]
    group_o: dict[str, Any] = {"gap": INSET_LG}
    if t2:
        group_o.update(fill=RAISED, stroke=BORDER, strokeWidth=HAIR, strokeAlign="inner", padX=INSET_SM, radius=R_CONTROL)
    group = hbox("CMP-006 RadioGroup", radios, group_o, h=max(CONTROL_H + 8, round(text_h(sc(BODY))) + 8) +
                 (2 * extent("normal") if focused else 0),
                 note="radiogroup: one Tab stop, arrows move a roving tabindex (`15`:108)"
                      + ("; T2: every radio aria-disabled, arrows move focus without checking (§5.4)" if t2 else ""))
    kids: list[Node] = [head, _desc(key, ps, wd), marked(ps, key, group)]
    _on, line = effective(ps, key)
    kids.append(text("Effective line", line, sc(CAPTION), TEXT_2, w=wd,
                     note="a text node in the row's aria-describedby, not a live region (§5.1)"))
    if key in ps.w16:
        kids.append(text("W-16", w("W-16"), sc(CAPTION), TEXT_2, w=wd, note="visible only, never spoken (§5.3)"))
    if t2:
        kids.append(text("reason · W-17", w("W-17"), sc(CAPTION), TEXT_2, w=wd,
                         note="CMP-079 RbacGate reason node, in the DOM at mount; aria-describedby order: description, "
                              "Effective line, reason (§5.4)"))
    if ps.modified(key):
        kids.append(changed_line(key, ps))
    return vbox(f"option row · {key}", kids, {"gap": STACK_XS}, w=wd,
                note=f"fieldset/legend \"{lab}\"" + ("; CMP-079 RbacGate (T2, rendering 2a)" if t2 else ""))


def toggle_row(key: str, ps: PS) -> Node:
    sc, wd = ps.sc, row_width(ps)
    sw = switch(ps.on(key), ps)
    if ps.focus == key:
        sw = focus_ring(sw, ps.focus_variant, radius=R_BADGE)
    m = ps.mark(key)
    # a marked switch is marker + gap + switch; a two-digit stop's marker is 28 px, not 20 (live check: board 10's
    # stops 13 and 14 cut their row texts by 8 px at 882; 874 fits)
    tw = wd - est_width(sw) - PX[INSET_MD] - ((20 if m < 10 else 28) + PX[INSET_SM] if m else 0)
    lines: list[Node] = [text("label", ROWS[key]["label"], sc(BODY_STRONG), TEXT_1, w=round(tw)),
                         _desc(key, ps, round(tw))]
    if key == "thick_focus_ring" and ps.theme == "hc":
        lines.append(text("Effective line · W-25", w("W-25"), sc(CAPTION), TEXT_2, w=round(tw),
                          note="hc: the ring is thick regardless (D04:247); a switch reading Off never hides it (§5.1)"))
    if ps.modified(key):
        lines.append(changed_line(key, ps))
    return hbox(f"option row · {key}", [marked(ps, key, sw), vbox("text", lines, {"gap": STACK_XS}, w=round(tw))],
                {"gap": INSET_MD, "align": "start"}, w=wd, note='CMP-004 Toggle: role="switch", its label visible')


def choice_row(key: str, ps: PS, options: dict[str, str], *, extra: Iterable[Node] = ()) -> Node:
    """A shipped / PROPOSED radio group (announce_prices, announce_throttle_s, verbosity), §7.1."""
    sc, wd = ps.sc, row_width(ps)
    radios = [radio(lbl, ps.v(key) == v, ps, focused=ps.focus == key and ps.v(key) == v) for v, lbl in options.items()]
    group = hbox("CMP-006 RadioGroup", radios, {"gap": INSET_LG, "wrap": "wrap"}, w=wd,
                 h=max(CONTROL_H + 8, round(text_h(sc(BODY))) + 8))
    kids: list[Node] = [text("label", ROWS[key]["label"], sc(BODY_STRONG), TEXT_1, w=wd), _desc(key, ps, wd),
                        marked(ps, key, group), *extra]
    if ps.modified(key):
        kids.append(changed_line(key, ps))
    return vbox(f"option row · {key}", kids, {"gap": STACK_XS}, w=wd, note="radiogroup: one Tab stop, arrows move")


def info_panel(ps: PS) -> Node:
    """CMP-069 InfoPanel inline under the announcement choice (§7.2): the six classes verbatim from `05`:152."""
    sc, wd = ps.sc, row_width(ps)
    items = [text(f"class · {c}", f"• {c}", sc(CAPTION), TEXT_1, w=wd - 24) for c in CLASSES]
    return vbox("CMP-069 InfoPanel · inline", [hbox("title", [icon("info", "info", TEXT_2),
                                                              text("words", INFO_TITLE, sc(LABEL), TEXT_1)],
                                                    {"gap": INSET_XS}), *items],
                {"gap": STACK_XS, "pad": INSET_MD, "fill": RAISED, "radius": R_CARD}, w=wd,
                note="its own aria-describedby target after the row's description; never throttled (`05`:152)")


def row_for(key: str, ps: PS) -> Node | None:
    if key in TRI:
        return tri_row(key, ps)
    if key == "announce_prices":
        return choice_row(key, ps, ANNOUNCE_OPTIONS, extra=[info_panel(ps)])
    if key == "announce_throttle_s":  # shown only when Always is chosen (§7.1)
        return choice_row(key, ps, CADENCE_OPTIONS) if ps.v("announce_prices") == "always" else None
    if key == "verbosity":
        return choice_row(key, ps, VERBOSITY_OPTIONS)
    return toggle_row(key, ps)


# --- CMP-228 preview tiles, four PROPOSED kinds (§6; D05-A1 … D05-A4): a role="group" named in words holding a
# role="img" preview node (presentational children) and, outside it, the real controls
TILE_IN = TILE_W - 2 * 16


def tile_frame(kind: str, ps: PS, img: Node, controls: Iterable[Node | None], name_words: str) -> Node:
    copy_gap(f'the {kind} tile\'s accessible name "{name_words}": §6 L{L("## 6. Preview tiles") + 2} asks for "the '
             'configuration in words" and gives no string (an aria-label, not drawn)')
    wd = TILE_W if not (ps.stacked or ps.sc.f > 1) else min(ps.sc.px(TILE_W), row_width(ps))
    kids = [dict(img, note=(img.get("note") or "") + f"; role=\"img\" aria-label=\"{name_words}\"; its children "
                 "presentational"), *[c for c in controls if c]]
    ht = round(est_height(vbox("m", kids, {"gap": STACK_MD, "pad": INSET_LG})))
    return vbox(f"CMP-228 PreviewTile · {kind}", kids,
                {"gap": STACK_MD, "pad": INSET_LG, "fill": CANVAS, "radius": R_CARD, "stroke": BORDER,
                 "strokeWidth": HAIR, "strokeAlign": "inner"}, w=wd, h=ht,
                note=f'role="group" aria-label="{name_words}"; never the only disclosure (R-1); the frame is the '
                     "decorative color.border.default (§11)")


def heat_column(name: str, ps: PS, price: Decimal, flash: bool) -> Node:
    """The heatmap column (resting sizes as ramp stops) and the price cell; a flash fills the cell once per change."""
    rows = []
    for p, s in WORLD.heat:
        rows.append(hbox(f"level {px_fmt(p)}", [text("price", px_fmt(p), ps.sc(NUM_SM), AXIS),
                                               rect("cell", 40, 12, HM[heat_stop(s)])], {"gap": INSET_SM},
                         h=max(14, round(text_h(ps.sc(NUM_SM))))))
    prev = WORLD.price_at(Decimal(0))
    up = price >= prev
    cell = hbox("price cell", [text("last", px_fmt(price), ps.sc(NUM), TEXT_1)],
                {"padX": INSET_SM, "radius": R_CONTROL, "justify": "end",
                 **({"fill": BUY_SUBTLE if up else "color.sell.subtle"} if flash else {"stroke": BORDER,
                                                                                     "strokeWidth": HAIR,
                                                                                     "strokeAlign": "inner"})},
                w=ps.sc.px(96), h=max(CONTROL_H, round(text_h(ps.sc(NUM))) + 4), note="flash once per change, never above three a second (`05`:218)" if flash else None)
    return vbox(name, [vbox("heatmap column", rows), cell], {"gap": STACK_SM})


def motion_tile(ps: PS) -> Node:
    t_end = Decimal(LOOP_S)
    if motion_full(ps):
        img = hbox("preview", [heat_column("frame", ps, WORLD.price_at(t_end), ps.motion_running)], {"gap": INSET_LG},
                   note=(f"a {LOOP_S}-second loop: the trail fades and the price flashes once per change (§6.1)"
                         if ps.motion_running else "idle: no loop until focus or the pointer enters the group "
                                                   "(§13.2); zero frames rendered"))
        ctl = (button("Pause", ps, focused=ps.focus_variant if ps.focus == "tile:Motion" else None,
                      name="button · Pause") if ps.motion_running else None)
        if ctl:
            copy_gap(f'"Pause" / "Play": the motion tile\'s one button (§6 L{L("## 6. Preview tiles") + 2}: "one button '
                     'whose label swaps \\"Pause\\" / \\"Play\\"")')
            ctl = marked(ps, "tile:Motion", ctl)
        return tile_frame("motion", ps, img, [ctl], "Motion preview, full motion: the heatmap trail fades, the "
                                                    "price flashes")
    stills = [vbox(f"still · {lab}", [text("caption", lab, ps.sc(CAPTION), TEXT_2),
                                       heat_column("frame", ps, WORLD.price_at(t), False)], {"gap": STACK_XS})
              for lab, t in ((w("W-18", 0), Decimal(0)), (w("W-18", 1), t_end))]
    img = hbox("preview", stills, {"gap": INSET_LG, "align": "start"},
               note="reduce: the loop stops; two still frames side by side, no tween (§6.1, R-6)")
    return tile_frame("motion", ps, img, [], "Motion preview, reduced: still before and after frames")


def ladder_row(ps: PS, variant: str | None) -> Node:
    p_bid, s_bid = WORLD.heat[5]
    _p_ask, s_ask = WORLD.heat[3]
    rh = max(CONTROL_H, round(text_h(ps.sc(NUM))) + 8)
    cols = (("bid", f"{s_bid}", ps.sc.px(96)), ("price", px_fmt(p_bid), ps.sc.px(104)), ("ask", f"{s_ask}", ps.sc.px(96)))
    cells = [hbox(c, [text("value", v, ps.sc(NUM), TEXT_1)], {"padX": INSET_SM, "justify": "end"}, w=wd, h=rh)
             for c, v, wd in cols]
    wd = sum(c[2] for c in cols)
    kids = [*cells, *([inset_ring(wd, rh, variant)] if variant else [])]
    return hbox("row · ladder", kids, {"fill": RAISED}, w=wd, h=rh,
                note="a ladder row (bid size, price, ask size) from the seeded heatmap column")


def focus_tile(ps: PS, variant: str, *, after_click: bool = False) -> Node:
    copy_gap(f'"Sample": the focus tile\'s CMP-001 Button label (§6.2 L{L("### 6.2 Focus")} names the button, not its '
             "words)")
    btn = button("Sample", ps, name="CMP-001 Button · Sample")
    kids: list[Node] = [focus_ring(btn, variant), ladder_row(ps, variant)]
    if after_click:
        fallback("markers")
        kids.insert(0, hbox("tag · after a simulated click", [text("label", "after a simulated click", CAPTION, TEXT_INV)],
                            {"padX": INSET_XS, "radius": R_CONTROL, "fill": MARK_FILL}, h=16,
                            note="annotation tag (not product UI): the ring stays after a click (always-show)"))
    img = vbox("preview", kids, {"gap": STACK_MD},
               note="static, no loop; the samples inert and out of the Tab order; the ring painted by the "
                    "data-focus-ring token path (§6.2)")
    words = {"normal": "normal ring", "thick": "thick ring"}[variant] + (", shown after a click" if after_click else "")
    return tile_frame("focus", ps, img, [], f"Focus preview: {words}")


CANDLE_COLS = (("Time", 48), ("Open", 70), ("High", 70), ("Low", 70), ("Close", 70))  # 328 = TILE_IN


def candle_minute(m: int) -> str:
    return f"10:{m:02d}"  # synthetic minute labels (kit choice), no date


def table_tile(ps: PS) -> Node:
    on = ps.on("always_show_tables")
    if on:
        for c, _w in CANDLE_COLS:
            copy_gap(f'"{c}": a candle-table column header in the table tile (§6.4 L{L("### 6.4 Table alternative")} '
                     "names the CMP-049 table, §15 no header)")
        hdr = hbox("header row", [hbox(f"th · {c}", [text("value", c, ps.sc(CAPTION), TEXT_2)],
                                       {"padX": INSET_SM, "justify": "start" if c == "Time" else "end"}, w=wd,
                                       h=CONTROL_H) for c, wd in CANDLE_COLS], {"fill": CANVAS}, w=TILE_IN, h=CONTROL_H)
        rows = []
        for i, k_ in enumerate(WORLD.candles):
            vals = (candle_minute(k_.minute), px_fmt(k_.o), px_fmt(k_.h), px_fmt(k_.l), px_fmt(k_.c))
            rows.append(hbox(f"row {i + 1}", [hbox(f"td · {c}", [text("value", v, ps.sc(NUM_SM), TEXT_1)],
                                                   {"padX": INSET_SM, "justify": "start" if c == "Time" else "end"},
                                                   w=wd, h=CONTROL_H) for (c, wd), v in zip(CANDLE_COLS, vals)],
                             {"fill": CANVAS if i % 2 else RAISED}, w=TILE_IN, h=CONTROL_H))
        img = vbox("preview · CMP-049 table", [hdr, rect("header rule", TILE_IN, 1, BORDER), *rows], None,
                   w=TILE_IN, note="the same rows as the chart, no refetch (S07:24–25); the flip is instant under reduce")
        return tile_frame("table-alt", ps, img, [], "Table preview: the sample candles as a table")
    lo = min(k_.l for k_ in WORLD.candles)
    hi = max(k_.h for k_ in WORLD.candles)
    span, ch = float(hi - lo) or 1.0, 120
    sticks = []
    for i, k_ in enumerate(WORLD.candles):
        y_hi = round((float(hi - k_.h) / span) * ch)
        y_lo = round((float(hi - k_.l) / span) * ch)
        top, bot = max(k_.o, k_.c), min(k_.o, k_.c)
        y_t, y_b = round((float(hi - top) / span) * ch), round((float(hi - bot) / span) * ch)
        col = C_UP if k_.c >= k_.o else C_DOWN
        sticks += [rect(f"wick {i + 1}", 1, max(1, y_lo - y_hi), C_WICK, x=24 + 48 * i + 7, y=y_hi),
                   rect(f"body {i + 1}", 16, max(2, y_b - y_t), col, x=24 + 48 * i, y=y_t)]
    img = box("preview · candles", sticks, None, w=TILE_IN, h=ch,
              note=f"six seeded 1-minute candles, low {px_fmt(lo)} to high {px_fmt(hi)}")
    return tile_frame("table-alt", ps, img, [], "Table preview: the sample candles as a chart")


# --- the announcement sample (§6.3, §7.3): what a screen reader would say over the seeded burst
PRICE_CLASS = "latest price"  # copy gap: §7.3's "one latest-price line per field per cadence" names no label


def sample_lines(ps: PS) -> list[tuple[Decimal, str]]:
    """(second, line) in time order: the class events always (assertive, never throttled, Off does not silence them,
    §7.1); under Always with normal or high verbosity one latest-price line per cadence (§7.3); low verbosity reads
    only the class events."""
    out = [(e.t, f"[{e.cls}]") for e in WORLD.events]
    if ps.v("announce_prices") == "always" and ps.v("verbosity") != "low":
        cad = Decimal(ps.v("announce_throttle_s"))
        t = cad
        while t <= BURST_S:
            out.append((t, f"[{PRICE_CLASS}] {SYMBOL} {px_fmt(WORLD.price_at(t))}"))
            t += cad
    return sorted(out)


def fmt_s(t: Decimal) -> str:
    return f"{t:.1f} s"


def announcement_tile(ps: PS) -> Node:
    copy_gap(f'"Play sample": the announcement tile\'s button (§6.3 L{L("### 6.3 Announcements")}; W-27 "Show all" is '
             "its label while playing)")
    lines = sample_lines(ps)
    playing = ps.ann_at is not None
    shown = [x for x in lines if playing and x[0] <= ps.ann_at] if playing else (lines if ps.ann_done else [])
    btn = button(w("W-27") if playing else "Play sample", ps, name="button · Play sample",
                 focused=ps.focus_variant if ps.focus == "tile:Announcements" else None)
    btn = marked(ps, "tile:Announcements", btn)
    items = [text(f"li {i + 1}", f"{fmt_s(t)}  {s}", ps.sc(NUM_SM), TEXT_1) for i, (t, s) in enumerate(shown)]
    ul = vbox("ul · transcript", items, {"gap": STACK_XS}, note="a plain list, never a live region; lines append at the end, focus never "
                                      "moves (§6.3)") if items else None
    tin = (TILE_W if not (ps.stacked or ps.sc.f > 1) else min(ps.sc.px(TILE_W), row_width(ps))) - 32
    img = vbox("preview", [text("burst", f"{BURST_S} s {SYMBOL} burst, {PRINTS_PER_S} prints a second "
                                         f"({BURST_S * PRINTS_PER_S} prints)", ps.sc(CAPTION), TEXT_2, w=tin)],
               {"gap": STACK_XS}, note="the role=img part: the burst it reads (§7.3)")
    copy_gap(f'the tile\'s burst line "{BURST_S} s {SYMBOL} burst, {PRINTS_PER_S} prints a second": §7.3 L{_S73 + 2}\'s '
             "figures, worded by the kit")
    words = f"Announcement preview: {ANNOUNCE_OPTIONS[ps.v('announce_prices')]}, verbosity " \
            f"{VERBOSITY_OPTIONS[ps.v('verbosity')]}"
    return tile_frame("announcements", ps, img, [btn, ul], words)


TILES = {"motion": motion_tile, "focus": lambda ps: focus_tile(ps, "thick" if ps.on("thick_focus_ring") or ps.theme == "hc"
                                                                 else "normal", after_click=ps.on("always_show_focus_ring")),
         "table-alt": table_tile, "announcements": announcement_tile}


# --- sections, the header, the help section, the page
def section(name: str, ps: PS) -> Node:
    sc = ps.sc
    rows = [r for k_ in SECTION_KEYS[name] if (r := row_for(k_, ps))]
    any_mod = any(ps.modified(k_) for k_ in SECTION_KEYS[name])
    reset_all = None
    if any_mod:
        copy_gap(f'"Reset this section": §10 L{STATES["SCR-117/section-reset-preview"]["line"]} and §12 name the button; '
                 "§15 has no W-row for it")
        reset_all = marked(ps, f"section-reset:{name}",
                           button("Reset this section", ps, focused=ps.focus_variant if ps.focus == f"section-reset:{name}"
                                  else None))
    tile = TILES[SECTION_TILE[name]](ps) if name in SECTION_TILE else None
    head = text("h2", name, sc(HEADING_SM), TEXT_1, note="h2 inside the fieldset's legend (`15`:743)")
    rw = row_width(ps)
    col = vbox("rows", [*rows, reset_all], {"gap": STACK_LG}, w=rw)
    if ps.stacked or sc.f > 1 or tile is None:
        body = vbox("group", [col, tile], {"gap": STACK_LG}, w=rw,
                    note="the tile stacks under its group (§11)" if tile else None)
    else:
        body = hbox("group", [col, tile], {"gap": INSET_XL, "align": "start"}, w=ROWS_W + COL_GAP + TILE_W,
                    note="the tile after the group's last row in the DOM, to its right at >= 1280 px (§2)")
    return vbox(f"CMP-065 FormSection · {name}", [head, body], {"gap": STACK_MD}, w=rw if ps.stacked or sc.f > 1
                else COL_W, note=f'fieldset, legend "{name}"')


def help_section(ps: PS) -> Node:
    sc = ps.sc
    btn = button(w("W-22"), ps, focused=ps.focus_variant if ps.focus == "cheatsheet" else None)
    btn = dict(btn, note='CMP-001; aria-haspopup="dialog"; opens SCR-013 in place, focus back on close (§9)')
    kids = [text("h2", HELP_SECTION, sc(HEADING_SM), TEXT_1), marked(ps, "link:statement", link(w("W-21"), ps)),
            marked(ps, "link:shortcuts", link(w("W-23"), ps)), marked(ps, "cheatsheet", btn)]
    return vbox(f"CMP-065 FormSection · {HELP_SECTION}", kids, {"gap": STACK_MD}, w=row_width(ps))


def search_matches(term: str) -> list[str]:
    """The keys whose label or description holds the term (case-folded) — the kit's reading of §10's search."""
    t = term.casefold()
    return [k_ for s in SECTION_ORDER for k_ in SECTION_KEYS[s]
            if t in ROWS[k_]["label"].casefold() or t in ROWS[k_]["desc"].casefold()]


def section_of(key: str) -> str:
    return next(s for s, ks in SECTION_KEYS.items() if key in ks)


def header(ps: PS) -> Node:
    sc, wd = ps.sc, row_width(ps) if (ps.stacked or ps.sc.f > 1) else COL_W
    copy_gap(f'"{SEARCH_LABEL_GAP}": the settings search\'s visible label (§10 L{_S10["line"]} names the search; no '
             "placeholder stands in for a label, `11`:5077)")
    field_ = hbox("input", [icon("glyph", "search", TEXT_2), *([text("query", ps.search, sc(BODY), TEXT_1)]
                                                              if ps.search else [])],
                  {"gap": INSET_SM, "padX": INSET_SM, "fill": CANVAS, "radius": R_CONTROL, "stroke": BORDER_STRONG,
                   "strokeWidth": border_w(ps.theme), "strokeAlign": "inner"}, w=min(320, wd),
                  h=max(28, round(text_h(sc(BODY))) + 8), note='role="searchbox"')
    if ps.focus == "search":
        field_ = focus_ring(field_)
    srch = vbox("settings search", [text("label", SEARCH_LABEL_GAP, sc(LABEL), TEXT_1), marked(ps, "search", field_)],
                {"gap": STACK_XS})
    kids: list[Node | None] = [text("h1", H1, sc(HEADING_MD), TEXT_1, note='the one h1 (tabindex="-1", a route-change '
                                                                            'target only; BQ-8)'),
                               text("intro · W-1", w("W-1"), sc(BODY), TEXT_1, w=wd),
                               text("scope · W-2", w("W-2"), sc(CAPTION), TEXT_2, w=wd)]
    if ps.status:
        kids.append(hbox("status region", [icon("glyph", "info", TEXT_2), text("words", ps.status, sc(BODY), TEXT_1,
                                                                               w=wd - 24)],
                         {"gap": INSET_XS, "align": "start"}, w=wd,
                         note='the existing role="status" aria-live="polite" region (ASS:74): text replaced, never '
                              "appended; latest wins (§5.3)"))
    kids.append(srch)
    if ps.search:
        ms = search_matches(ps.search)
        found = fill(_quoted(COPY["W-29"].s)[0], n=str(len(ms))) if ms else fill(_quoted(COPY["W-29"].s)[1],
                                                                                    term=ps.search)
        NOTES.add("copy_keys", f"W-29 (§15 L{COPY['W-29'].line}, {COPY['W-29'].status}): {found}")
        copy_gap(f'the result\'s section path "{H1} › <section>": §10 asks for "their section path", §15 gives no form')
        res = [vbox(f"result · {k_}", [text("label", ROWS[k_]["label"], sc(BODY_STRONG), TEXT_LINK),
                                       text("path", f"{H1} › {section_of(k_)}", sc(CAPTION), TEXT_2)],
                    {"gap": STACK_XS, "padX": INSET_SM, "padY": INSET_XS}, w=min(480, wd),
                    note="activating it moves focus to its control, scrolled clear of sticky chrome (2.4.11)")
               for k_ in ms]
        kids.append(vbox("search results", [text("status · W-29", found, sc(CAPTION), TEXT_2,
                                                 note='one polite status (W-29)'), *res],
                         {"gap": STACK_XS, "pad": INSET_SM, "fill": RAISED, "radius": R_CARD}, w=min(496, wd)))
    return vbox("header", kids, {"gap": STACK_SM}, w=wd)


def page(ps: PS) -> Node:
    pad = INSET_LG if ps.width < CONTENT_W else INSET_XL
    kids: list[Node | None] = [header(ps) if ps.header else None]
    for s in ps.sections:
        kids.append(help_section(ps) if s == HELP_SECTION else section(s, ps))
    return vbox("SCR-117 content", kids, {"gap": STACK_LG if ps.sc.f == 1 else INSET_XL, "pad": pad, "fill": APP},
                w=ps.width, note="main: one column, max-width 60 rem (S07:33–34); DOM order = visual order")


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
            f"Frames (hand-off §H L{H_LINE}): " + "; ".join(f + (f" {FRAME_SUFFIX[f]}" if f in FRAME_SUFFIX else "")
                                                             for f in b.frames),
            f"Export: {b.export}", DATA_LINE,
            "Markers, tags, fold lines and callouts in color.status.info.default are annotation, not product UI",
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


def board(nn: int, frames: list[Node], ann: Node, *, per_row: int = 3,
          full_length: Iterable[str] = ()) -> tuple[dict[str, Any], list[Node]]:
    """The sheet's root (board name, grid x/y, color.surface.app, clip) hugging its frames + the ONE annotation column
    + MARGIN; a "state: <frame id>" caption 28 px above each frame; the data line under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f) for f in b.frames]
    got = [f["name"] for f in frames]
    if got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != §H {want}")
    fl = {frame_name(f) for f in full_length}
    for f, fid in zip(frames, b.frames):
        if FRAME_SUFFIX.get(fid, "").startswith(f"at {ZOOM_W} CSS px"):
            ok = f["w"] % ZOOM_W == 0 and f["h"] == FRAME_H
        elif f["name"] in fl:
            ok = f["w"] == FRAME_W and f["h"] >= FRAME_H
        else:
            ok = f["w"] == FRAME_W and f["h"] == FRAME_H
        if not ok:
            raise ValueError(f"board {nn:02d}: frame {f['name']!r} is {f['w']} x {f['h']} (§0: 1280 x 800 windows "
                             f"unless the board names the 200 % viewport)")
    if "/" in b.name[len(f"{KEY} / {nn:02d} "):]:
        raise ValueError(f"board {nn:02d}: '/' after the prefix in {b.name!r}")
    placed = layout(frames, per_row)
    fid = dict(zip(want, b.frames))
    caps = [text(f"caption {i:02d}", f"state: {fid[f['name']]}" + (f" {FRAME_SUFFIX[fid[f['name']]]}"
                                                                    if fid[f["name"]] in FRAME_SUFFIX else ""),
                 CAPTION, TEXT_3, x=f["x"], y=f["y"] - 28) for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · data", DATA_LINE, CAPTION, TEXT_2, x=MARGIN, y=bottom + 24)]
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    h = int(math.ceil((max(bottom + 24 + 16, MARGIN + ah) + MARGIN) / 8) * 8)
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root (h {h}); "
         f"raise the root's h to its end + {MARGIN} if not")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


def write_sheet(nn: int, frames: list[Node], ann: Node, *, notes: dict[str, Iterable[str]] | None = None,
                per_row: int = 3, full_length: Iterable[str] = (), out_dir: Path = CAP_DIR,
                name: str | None = None) -> Path:
    """Assemble board nn, split into sections, merge notes, write out_dir/NN-<slug>.json, run the validator (tokens +
    components); RuntimeError unless it exits 0 and the kit lint and the banned scan are clean. Clears NOTES."""
    b = BOARDS[nn]
    out_dir = out_dir.resolve()
    if out_dir not in (CAP_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    root, nodes = board(nn, frames, ann, per_row=per_row, full_length=full_length)
    if b.theme != "dark":
        live(f"theme: activate the {b.theme} token set before exporting board {nn:02d}; read back one bound fill "
             f"(color.surface.canvas) as the {b.theme} value")
    live(f"export {b.export}; record the board id and the PNG size in §0")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {DOCS['spec'][0]} md5 {DOCS['spec'][1][:8]}, hand-off {DOCS['handoff'][0]} md5 "
                         f"{DOCS['handoff'][1][:8]} (§0 L{b.line}; hand-off §H L{H_LINE}); shipped labels "
                         f"{DOCS['ass'][0]} at {SPEC_BASE} md5 {DOCS['ass'][1][:8]}; tick size {FIXTURE_REL} md5 "
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
    out += [f"- `{frame_name(f)}` (§H: `{f}`{' ' + FRAME_SUFFIX[f] if f in FRAME_SUFFIX else ''})" for f in b.frames]
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
          per_row: int = 3, full_length: Iterable[str] = (),
          notes: dict[str, Iterable[str]] | None = None) -> tuple[Path, Path, Path]:
    """The generators' one call: annotations, sheet, md, packed sheet."""
    ann = annotations(nn, blocks, board_lines=board_lines)
    p = write_sheet(nn, frames, ann, per_row=per_row, full_length=full_length, notes=notes)
    return p, write_md(nn, p), pack_sheet(p)


# --- self-test: python3 -I -B e47d05kit.py selftest
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), "source md5 pins")
    check(len(BOARDS) == int(val("COUNT", "boards")) == 10, "§0 board count = COUNT:boards")
    check(sum(b.twin is not None for b in BOARDS.values()) == int(val("COUNT", "boards.twins")), "twin count")
    check(sum(b.twin is not None for b in BOARDS.values()) * 3 <= len(BOARDS), "twins <= a third")
    check(all(BOARDS[n].frames for n in BOARDS), "§H frames for every board")
    check(all("/" not in b.name[len(f"{KEY} / {n:02d} "):] for n, b in BOARDS.items()), "no '/' after the prefix")
    check(len(COPY) == int(val("COUNT", "copy")), "§15 string count = COUNT:copy")
    check(len(KEYS) == int(val("COUNT", "keys")) and len(ROWS) == len(KEYS), "§3 / §4 key counts = COUNT:keys")
    check(sorted(k_ for ks in SECTION_KEYS.values() for k_ in ks) == sorted(KEYS), "every key in one section")
    check(list(SECTION_KEYS) == SECTION_ORDER, "SECTION_KEYS follows §2's order")
    check(len(CLASSES) == int(val("COUNT", "classes")), "§7.2 classes = COUNT:classes")
    check(len(STATES) == int(val("COUNT", "states")), "§10 states = COUNT:states")
    for wk, (a, b) in (("W-12", ("On", "from your system setting")), ("W-13", ("On", "your choice")),
                       ("W-14", ("Off", "the product default"))):
        check(w(wk) == fill(EFFECTIVE_TEMPLATE, a=a, b=b), f"{wk} is a fill of §5.1's template")
    check(w("W-11") == TRI_OPTIONS[0], "W-11 = the first tri-state option")
    check([ROWS[k_]["label"] for k_ in ("reduced_motion", "increased_contrast")] == [w("W-3"), w("W-4")], "W-3/W-4")
    check(RING_GEOM["normal"][:3] == (2, 1, 2) and RING_GEOM["thick"][:3] == (3, 2, 2), "D04 §7.1 geometry read")
    check(extent("normal") == 6 and extent("thick") == 9, "ring extents 6 / 9 px")
    check(len(WORLD.prints) == BURST_S * PRINTS_PER_S and len(WORLD.events) == 3, "the burst: prints and three events")
    low = sample_lines(PS(values=(("verbosity", "low"),)))
    check(len(low) == 3 and all(s[1:-1] in CLASSES for _t, s in low), "low verbosity: exactly the three class lines")
    alw = sample_lines(PS(values=(("announce_prices", "always"),)))
    check(len(alw) == 3 + BURST_S // int(KEYS["announce_throttle_s"]["default"]), "Always: + one price line per 2 s")
    toks = set(_TS.get("semantic-dark", {})) | set(_TS.get("primitives", {}))
    used = [v for k_, v in globals().items() if k_.isupper() and isinstance(v, str)
            and re.match(r"(color|type|space|size|radius|border|opacity)\.", v)] + list(HM.values())
    check(all(t in toks for t in used), f"kit tokens exist: {[t for t in used if t not in toks]}")
    SELFTEST_DIR.mkdir(parents=True, exist_ok=True)
    ps = PS(sections=("Motion",))
    fr = window(frame_name(BOARDS[4].frames[0]), page(ps))
    fr2 = window(frame_name(BOARDS[4].frames[1]), page(ps))
    fr3 = window(frame_name(BOARDS[4].frames[2]), page(PS(forced=True, sections=("Contrast and focus",))))
    ann = annotations(4, [(BOARDS[4].frames[0], ["self-test"])])
    try:
        p = write_sheet(4, [fr, fr2, fr3], ann, out_dir=SELFTEST_DIR, name="00-selftest.json")
        pk = pack_sheet(p, SELFTEST_DIR)
        check(json.loads(pk.read_text())["compactOf"]["file"] == p.name, "packed source is the bare name")
        check('"t": "inst"' not in p.read_text(), "no inst")
    except Exception as e:  # noqa: BLE001 - reported as a failure
        fails.append(f"sample sheet: {e}")
    for f in fails:
        print("FAIL", f)
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


# --- CMP-043 dialog and the modal overlay (the E47-D04 kit's)
DIALOG_W = 440


def dialog(title: str, kids: Iterable[Node | None], actions: Iterable[Node], *, name: str = "CMP-043 Dialog") -> Node:
    deviate(f"dialog width {DIALOG_W} px: a kit choice (no source gives CMP-043's width)")
    iw = DIALOG_W - 2 * PX[DIALOG_PAD]
    body = [text("title", title, HEADING_MD, TEXT_1, w=iw, note="h2: the dialog's name"), *kids,
            hbox("actions", list(actions), {"gap": INSET_SM, "justify": "end"}, w=iw, h=CONTROL_H + 20)]
    return vbox(name, body, {"fill": OVERLAY, "radius": R_DIALOG, "pad": DIALOG_PAD, "gap": STACK_MD, "stroke": BORDER,
                             "strokeWidth": HAIR, "strokeAlign": "inner"}, w=DIALOG_W,
                note='role="dialog" aria-modal="true"; the page behind is inert')


def modal(dialog_node: Node, *, measured_h: int | None = None) -> Node:
    """The overlay over a 1280 x 800 window: the flat scrim and the dialog centred (on its live-measured height when
    the live check gave one)."""
    fallback("scrim")
    dw, dh = est_width(dialog_node), measured_h or est_height(dialog_node)
    dx, dy = round((FRAME_W - dw) / 2), round(max((FRAME_H - dh) / 2, 0))
    live(f"modal: re-centre '{dialog_node['name']}' after relayout (estimated {dw:.0f} x {dh:.0f} px)")
    scrim = rect("scrim", FRAME_W, FRAME_H, SUNKEN, {"opacity": OPACITY_SCRIM}, x=0, y=0)
    return box("overlay", [scrim, dict(dialog_node, x=dx, y=dy)], None, w=FRAME_W, h=FRAME_H, x=0, y=0, abs=True)


def field(label_: str, value: str, ps: PS, *, wd: int = 120, steps: bool = False, picker: bool = False,
          focused: bool = False) -> Node:
    """A labelled input (type.num.base for numbers) with optional step buttons (arrow-up / arrow-down, one tick) or
    a picker chevron."""
    inp = hbox("input", [text("value", value, NUM if not picker else BODY, TEXT_1),
                         *([icon("chevron", "chevron-down", TEXT_2)] if picker else [])],
               {"padX": INSET_SM, "gap": INSET_XS, "justify": "space-between" if picker else "end", "fill": CANVAS,
                "radius": R_CONTROL, "stroke": BORDER_STRONG, "strokeWidth": border_w(ps.theme), "strokeAlign": "inner"},
               w=wd, h=CONTROL_H + 4)
    if focused:
        inp = focus_ring(inp)
    kids: list[Node] = [inp]
    if steps:
        for g_, nm in (("arrow-up", "up"), ("arrow-down", "down")):
            kids.append(hbox(f"step {nm}", [icon("glyph", g_, TEXT_1)],
                             {"justify": "center", "radius": R_CONTROL, "fill": ACTION_SECONDARY,
                              "stroke": BORDER_STRONG, "strokeWidth": border_w(ps.theme), "strokeAlign": "inner"},
                             w=CONTROL_H + 4, h=CONTROL_H + 4, note=f"CMP-001 icon button: one tick {nm}"))
    return vbox(f"field · {label_}", [text("label", label_, LABEL, TEXT_1), hbox("control", kids, {"gap": INSET_XS})],
                {"gap": STACK_XS})


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
