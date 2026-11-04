"""E21-D02 (#440) hi-fi board kit: the spec's §0 ten boards (SCR-050 Heatmap + DOM ladder panel: anatomy and redlines,
tiers, densities, every state, the T2 legs, DEMO / LIVE, own orders and detectors, legend and colour vision, keyboard,
the Table view and reflow) as cvsheet JSON sheets for the per-set Penpot file "E21-D02 boards", page "E21-D02" (the
boards PR, which carries the closing keyword for #440; ruling of record 6576656158, BQ-1, BQ-13).

Offline only. Spec (binding; every string comes from it): docs/design/E21/E21-D02.md (§0 boards, §2 anatomy and
redlines, §3 tiers and densities, §4 states, §5 the T2 legs, §6 DEMO / LIVE, §7 encoding and colour vision, §8 own
orders and detectors, §9 keyboard and reflow, §10 the Table view, §11.1 events, §12 copy deck); there is no hand-off
file (BQ-2). Read by repo-relative path from a checkout and md5-pinned in DOCS (the kit refuses drifted bytes: re-read,
re-check, re-pin). The recorded instrument fixture gives the BTCUSDT tick (0.10) and qty step (0.001); every other value
is the seeded synthetic book (seed 440, the world below), and every drawn size, price, count, age and anchor is derived
from it.

Checkout: the kit sits at docs/design/_tools/sheets/e21-d02/ in a checkout (REPO = four levels up), or anywhere with
CV_CHECKOUT naming the checkout. Raw sheets + .md go to CAP_DIR, packed sheets to V4_DIR (build-notes.md).
Pipeline (one generator per board, gen/gen_NN.py; the panel and its widgets in gen/ui.py):
    frames = [ui.panel(fid, ...), ...]; blocks = [frame_block(fid, lines), ...]
    build(nn, frames, blocks, cols) -> raw sheet (validator exit 0), .md (line 3 = the render line), packed sheet
Self-test: python3 -X utf8 -I -B e21d02kit.py selftest (BUILD.md has the full rebuild)

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (frame ids use U+2215); no local path, host or
agent name anywhere in a sheet (BANNED); table cells carry 8 px inner padding a side; every frame has a caption;
color.text.disabled and opacity.disabled are never bound (E09-D09 §2.1 G-T2.2).
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
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KEY, EPIC, ISSUE = "E21-D02", "E21", 440
KIT_DIR = Path(__file__).resolve().parent
_SPEC_PATH = "docs/design/E21/E21-D02.md"


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / _SPEC_PATH).is_file() and KIT_DIR.is_relative_to(up / "docs"):
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / _SPEC_PATH).is_file():
        raise SystemExit("e21d02kit: run inside a checkout or set CV_CHECKOUT to one")
    return Path(env).resolve()


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
HEAD = "the boards PR"  # the text as built: #5488 (b4fdf44c9) plus the boards PR's in-place edits and its §17
DOCS = {  # key -> (repo-relative path, md5 at HEAD): every read is md5-checked
    "spec": (_SPEC_PATH, "0431d0041dabe975c91a73421fa4e187"),
    "fixture": ("packages/fixtures/bybit/2026-10-05/rest/instruments_before.json", "edd9dd2a060c51bd4bd1450307728ddf"),
}
REV = "r1"
PITCH_X, PITCH_Y = 6400, 3200  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80
ANN_W = 400
ANN_TEXT_W = ANN_W - 32
SLASH = "∕"  # U+2215 stands for "/" in node names (Penpot splits names on "/")
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465", "68747470")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode()
    + r"\b", re.I | re.DOTALL)


def _doc_bytes(k: str) -> bytes:
    return (REPO / DOCS[k][0]).read_bytes()


def spec_md5_ok() -> dict[str, bool]:
    return {k: hashlib.md5(_doc_bytes(k)).hexdigest() == m for k, (_p, m) in DOCS.items()}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:
    raise SystemExit(f"e21d02kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
LINES = {k: _COMMENT.sub("", _doc_bytes(k).decode("utf-8")).split("\n") for k in DOCS if k != "fixture"}


def find_line(needle: str, doc: str = "spec", start: int = 1) -> int:
    """1-based number of the first line of doc at or after start containing needle (raises if absent)."""
    ls = LINES[doc]
    for i in range(start - 1, len(ls)):
        if needle in ls[i]:
            return i + 1
    raise LookupError(f"{doc}: not found: {needle!r}")


def L(needle: str, start: int = 1) -> int:
    return find_line(needle, "spec", start)


_PIPE = re.compile(r"(?<!\\)\|")


def cells(row: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in _PIPE.split(row.strip().strip("|"))] if row.strip() else []


def table(head: str, doc: str = "spec", start: int = 1) -> list[tuple[int, list[str]]]:
    """The rows (line, cells) of the first markdown table after the line containing head (header and rule skipped)."""
    i = find_line(head, doc, start)
    ls = LINES[doc]
    while not ls[i].startswith("|"):
        i += 1
    out, j = [], i + 2
    while j < len(ls) and ls[j].startswith("|"):
        out.append((j + 1, cells(ls[j])))
        j += 1
    return out


def plain(s: str) -> str:
    return re.sub(r"\*\*|`", "", s).strip()


def unquote(s: str) -> str:
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


# --- registries parsed from the spec: §0 boards, §4 states, §12 copy deck, §2.1 / §2.3 / §2.4, §3.1, §5, §7, §9.2
S0 = L("## 0. Status, artefacts and the boards")
_S0_TEXT = LINES["spec"][S0 + 1]
PAGE = re.search(r"page `([^`]+)`", _S0_TEXT).group(1)  # type: ignore[union-attr]
FILE_NAME = re.search(r"the file `([^`]+)`", _S0_TEXT).group(1)  # type: ignore[union-attr]
EXPORT_DIR = re.search(r"exports go to `([^`]+)/" + re.escape(KEY) + r"-NN-<slug>\.png`",  # type: ignore[union-attr]
                       _S0_TEXT).group(1)
_FRAME_WH = re.search(r"Frames are (\d+) × (\d+) windows", _S0_TEXT)
WIN_W, WIN_H = int(_FRAME_WH.group(1)), int(_FRAME_WH.group(2))  # type: ignore[union-attr]
TWIN_CAP = re.search(r"(\d+) boards; (\d+) carry a light twin frame", _S0_TEXT)
# the kit's frame plan for §0's ten boards: §4's thirteen states on their §0 boards, the variants §0's Draws cells
# name ("tier strip", "density strip", the Owner CTA and the sentence form, T1 and the ≥ T2 step, the aggregate
# expanded), and board-marker frames for what a Draws cell names without a state id (redlines, the legs, the ARMED
# inset, the legend, the exports, the keys); "· <variant>" after a state id names the variant drawn
REDLINES, LEGS, ARMED = "redlines · token map", "legs · the one notice", "inset · ARMED (E30-D04)"
LEGEND, EXPORTS, KEYS = "legend · contrast · forced colours", "exports · greyscale and simulations", "keys · §9.2"
REFLOW = "reflow · 200 %"
KIT_FRAMES: dict[int, tuple[str, ...]] = {
    1: ("SCR-050/streaming", "SCR-050/free-scroll", REDLINES),
    2: ("SCR-050/streaming · tier 50", "SCR-050/streaming · tier 200", "SCR-050/streaming · tier 500",
        "SCR-050/500-unavailable"),
    3: ("SCR-050/streaming · compact", "SCR-050/streaming · cosy", "SCR-050/streaming · comfortable"),
    4: ("SCR-050/loading", "SCR-050/empty-no-recording", "SCR-050/empty-no-recording · sentence form"),
    5: ("SCR-050/stale", "SCR-050/stale · ≥ T2", "SCR-050/disconnected"),
    6: ("SCR-050/resyncing", "SCR-050/resyncing · rebuilt", "SCR-050/depth-shed"),
    7: ("SCR-050/arm-locked", "SCR-050/demo", "SCR-050/live", LEGS, ARMED),
    8: ("SCR-050/detector-chips", "SCR-050/detector-chips · aggregate expanded", "SCR-050/detector-chips · reveal"),
    9: ("SCR-050/streaming · CVD twin set", LEGEND, EXPORTS),
    10: ("SCR-050/streaming · focus order and row menu", "SCR-050/streaming · Table view", REFLOW, KEYS),
}
MARKER_FRAMES = (REDLINES, LEGS, ARMED, LEGEND, EXPORTS, KEYS)


def state_of(fid: str) -> str:
    """The §4 state a frame draws (the id before " · "), or the frame id itself for a board-marker frame."""
    return fid.split(" · ", 1)[0] if fid.startswith("SCR-050/") else fid


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E21-D02 / 01 anatomy-redlines"
    slug: str
    draws: str  # §0's Draws cell (code ticks removed)
    theme_cell: str  # "dark" or "dark + light"
    line: int  # §0 line
    frames: tuple[str, ...]

    @property
    def theme(self) -> str:
        return "dark"  # every board renders and first exports under dark; a twin is exported again under light

    @property
    def twin(self) -> bool:
        return self.theme_cell == "dark + light"

    @property
    def export(self) -> str:
        return f"{EXPORT_DIR}/{KEY}-{self.nn:02d}-{self.slug}.png"

    @property
    def export_light(self) -> str:
        return f"{EXPORT_DIR}/{KEY}-{self.nn:02d}-{self.slug}-light.png"

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"


def _boards() -> dict[int, Board]:
    out = {}
    for i, c in table("## 0. Status, artefacts and the boards"):
        nn = int(c[0])
        name = plain(c[1])
        # PENDING in the text PR; "drawn: board id ..." once the boards PR records them as built
        if not (plain(c[4]) == "PENDING" or plain(c[4]).startswith("drawn: board id ")) or not name.startswith(f"{KEY} / {nn:02d} ") or plain(c[3]) not in (
                "dark", "dark + light"):
            raise ValueError(f"§0 L{i}: {c!r}")
        out[nn] = Board(nn, name, name.split(f"{KEY} / {nn:02d} ", 1)[1], plain(c[2]), plain(c[3]), i, KIT_FRAMES[nn])
    return out


BOARDS = _boards()


def frame_name(fid: str) -> str:
    return fid.replace("/", SLASH)


def board_of(fid: str) -> int:
    return next(n for n, b in BOARDS.items() if fid in b.frames)


def _rows(head: str, start: int = 1) -> dict[str, tuple[list[str], int]]:
    return {plain(c[0]): (c, i) for i, c in table(head, "spec", start)}


STATES = _rows("## 4. States")  # frame id -> (cells, line): Frame, Signal, Shows, Tokens, Keyboard, Announced, T2, Board
STATES = {k_.replace(" (inset)", ""): v for k_, v in STATES.items()}  # "SCR-050/free-scroll (inset)" -> its id
COPY = _rows("## 12. Copy deck")  # W-n -> (cells, line): W, Key / slot, String, Source, Status
HEADER_SLOTS = table("### 2.1 The header")  # (line, [Slot, Content, Component, Notes])
COLUMNS = table("### 2.3 The ladder")  # (line, [Column, Header text, Content, Width rule])
COL_HEADS = tuple(unquote(plain(c[1])) for _i, c in COLUMNS)  # the six header texts, §2.3's order
REDLINE_ROWS = table("### 2.4 Redlines and the token map")
MATRIX = table("### 3.1 The matrix")
LEG_ROWS = table("### 5.1 One notice")  # (line, [Order, Leg, Key (string), When])
GATED = table("### 5.2 The gated controls")
STOP_ROWS = table("### 7.3 Computed contrast")
PAIR_ROWS = table("The other pairs this panel draws")
FORCED = table("### 7.4 Forced colours")
KEY_ROWS = table("### 9.2 Keys")


def W(wid: str, i: int = 0, **fills: Any) -> str:
    """The i-th quoted string of copy-deck row wid (§12), verbatim, with its {slot}s filled; raises on an unfilled or
    unknown slot."""
    c, ln = COPY[wid]
    qs = re.findall(r'"([^"]+)"', c[2])
    s = qs[i]
    for k_, v in fills.items():
        if "{" + k_ + "}" not in s:
            raise KeyError(f"{wid}: no slot {{{k_}}} in {s!r}")
        s = s.replace("{" + k_ + "}", str(v))
    if re.search(r"\{[a-zA-Z]+\}", s):
        raise KeyError(f"{wid}: unfilled slot in {s!r}")
    NOTES.add("copy_keys", f"{wid} (§12 L{ln}, {plain(c[4])}): \"{s}\"")
    return s


def Wf(wid: str, figures: dict[str, str]) -> str:
    """Copy-deck row wid with its illustrative figures (the spec's "Numbers" paragraph: prices and sizes inside quoted
    copy are illustrative) replaced by the world's; every old figure must occur once; equal figures stay verbatim."""
    c, ln = COPY[wid]
    s = re.findall(r'"([^"]+)"', c[2])[0]
    out = s
    for old, new in figures.items():
        if s.count(old) != 1:
            raise KeyError(f"{wid}: figure {old!r} not once in {s!r}")
        out = out.replace(old, new)
    NOTES.add("copy_keys", f"{wid} (§12 L{ln}, {plain(c[4])}): \"{out}\"" +
              ("" if out == s else f" — the form of \"{s}\", its illustrative figures derived from the world"))
    return out


def S(chars: str, start: int = 1) -> str:
    """A spec string verbatim (markdown code ticks and bold removed before the match; raises if absent)."""
    for i in range(start - 1, len(LINES["spec"])):
        if chars in plain(LINES["spec"][i]):
            NOTES.add("copy_keys", f"spec L{i + 1}: \"{chars}\"")
            return chars
    raise LookupError(f"spec: not found: {chars!r}")


def state_line(fid: str) -> str:
    """The annotation line for a §4 state: signal, keyboard / focus, announced, T2 (verbatim cells)."""
    c, ln = STATES[fid]
    return (f"§4 L{ln} {fid}: signal {plain(c[1])}; shows {plain(c[2])}; keyboard {plain(c[4])}; announced "
            f"{plain(c[5])}; T2 {plain(c[6])}")


# --- tokens (§2.4's map; every name ships in token-sync.json, checked by the self-test and node())
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_ON_ACTION = "color.text.on-action"
BORDER, BORDER_SUBTLE, BORDER_STRONG, BORDER_SELECTED = ("color.border.default", "color.border.subtle",
                                                         "color.border.strong", "color.border.selected")
RING = "color.focus.ring"
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
INFO_SUBTLE, INFO_STRONG = "color.status.info.subtle", "color.status.info.strong"
WARN_SUBTLE, WARN_STRONG = "color.status.warning.subtle", "color.status.warning.strong"
DANGER_SUBTLE, DANGER_STRONG = "color.status.danger.subtle", "color.status.danger.strong"
NEUTRAL = "color.neutral.default"
ENV_DEMO, ENV_LIVE = "color.env.demo", "color.env.live"
HM_ZERO = "color.heatmap.zero"
GRID = "color.grid.line"
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD = "type.ui.heading-sm", "type.ui.heading-md"
NUM_XS, NUM_SM, NUM = "type.num.xs", "type.num.sm", "type.num.base"
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
BUTTON_PADX, DIALOG_PAD = "space.button.paddingX", "space.dialog.padding"
ICON_SM, ICON = "size.icon.sm", "size.icon"
CTRL_COMFORTABLE, TARGET_MIN = "size.control.comfortable", "size.target.min"
R_CONTROL, R_CARD, R_DIALOG, R_BADGE = "radius.control", "radius.card", "radius.dialog", "radius.badge"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
SCRIM = "opacity.scrim"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, BUTTON_PADX: 12, DIALOG_PAD: 24, ICON_SM: 12, ICON: 16, CTRL_COMFORTABLE: 32, TARGET_MIN: 24}
ROW_H = 32  # comfortable rows (§2.4; `16`:130)
COMPACT_ROW = 24  # SCR-050 at compact (§0, §2.4; `16`:129)
NEVER = ("color.text.disabled", "opacity.disabled")  # E09-D09 §2.1 G-T2.2: never bound on these boards


def hm(side: str, level: int, cvd: bool = False) -> str:
    """color.heatmap.<side>.<1..5> (or the CVD set's twin)."""
    if side not in ("bid", "ask") or not 1 <= level <= 5:
        raise ValueError((side, level))
    return f"color.{'cvd.' if cvd else ''}heatmap.{side}.{level}"


TOKEN_NAMES = frozenset(r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8")))
STALE_SURFACE, STALE_TEXT = "color.data-confidence.stale.surface", "color.data-confidence.stale.text"
STALE_IND = "color.data-confidence.stale.indicator"
DISC_TEXT, RESYNC_TEXT = "color.data-confidence.disconnected.text", "color.data-confidence.resyncing.text"
BUY, SELL, BUY_SUBTLE, SELL_SUBTLE = "color.buy.default", "color.sell.default", "color.buy.subtle", "color.sell.subtle"
INFO = "color.status.info.default"
R_PILL = "radius.pill"
MUTED = "opacity.muted"


def tok_ok(t: str) -> bool:
    return t in TOKEN_NAMES


FALLBACKS = {
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock and the chevrons",
    "scrim": "the resync scrim is color.surface.overlay (§4's token) over the ladder and the pane at opacity.scrim "
             "(validator WARN: a Tier-1 primitive) so the frozen rows stay visible under it",
    "env-glyph": "kit choice: the env badge's icon (E10-D03's) is not in the local icon set; drawn as an 8 px dot in "
                 "the env colour, outlined for DEMO and filled for LIVE, beside the word (text + icon, the colour "
                 "never the only signal)",
    "marker": "kit choice: board markers (focus-order numbers, announcements, accessible names, redline callouts) are "
              "drawn in a 1 px color.border.strong outline — not product UI",
    "badge": "kit choice: focus-order numbers drawn as 20 px numbered markers in color.focus.ring (board markers)",
    "cells": "kit choice: the heatmap pane draws one row per ladder row (R-2) and one column per trail second (the "
             "cell chip's auto = 1 s), equal-stop runs drawn as one rect; compact and comfortable cells keep a 1 px "
             "gutter top and bottom, the cosy (`dense`) pane none (§3.1 'the pane's gutters tighter')",
    "hatch": "kit choice: the pulled mark's hatch (pattern.hatch.estimated's look, D05E11 §7, cited not re-made) "
             "drawn as 2 × 2 steps of color.text.primary on a 6 px 45° track over the pulled cell",
    "skeleton": "kit choice: loading skeleton bars are color.surface.raised rects inset 4 px in each 24 px row, "
                "their widths the kit's (static, no shimmer: motion is E21-D05's)",
    "own-glyph": "kit choice: CMP-230's glyph (second, after the text) drawn as an 8 px square in color.buy.default "
                 "or color.sell.default; the words carry the side",
    "chip": "kit choice: CMP-134 detector chips drawn as pills (radius.pill, a Tier-1 primitive: validator WARN) "
            "with a 1 px color.border.default outline, the local "
            "'info' glyph as CMP-227's stand-in and the words in full with \"(estimated)\"",
    "segmented": "kit choice: the `Ladder │ Table` radiogroup drawn as two 24 px segments, the checked one "
                 "color.surface.selected with a color.border.selected outline",
    "menu": "kit choice: menus and the open listbox drawn as color.surface.overlay cards with a 1 px "
            "color.border.default outline (popovers over the rows)",
}

_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "spec_gaps", "fallbacks", "tokens", "live_checks", "deviations",
              "derivations", "decisions")


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
    NOTES.add("live_checks", line)


def spec_gap(line: str) -> None:
    NOTES.add("spec_gaps", line)


def derive(line: str) -> None:
    NOTES.add("derivations", line)


def decide(line: str) -> None:
    NOTES.add("decisions", line)


def fallback(key: str) -> None:
    NOTES.add("fallbacks", FALLBACKS[key])


def ui(chars: str, why: str = "") -> str:
    """A label the spec does not write (a board-marker word, a label another document owns): drawn, and listed as
    a copy gap."""
    NOTES.add("copy_gaps", f"\"{chars}\": kit label, not E21-D02 copy{' — ' + why if why else ''}")
    return chars


# --- node primitives (cvsheet v4.3 schema; no inst nodes)
_KEYS = {
    "board": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "kids", "note"},
    "text": {"t", "name", "chars", "typo", "color", "w", "align", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "rect": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "ellipse": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "icon": {"t", "name", "icon", "color", "size", "x", "y", "abs", "alignSelf", "note"},
}


def node(t: str, name: str, **kw: Any) -> Node:
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
            if tk in NEVER:
                raise ValueError(f"{name!r}: {tk} is never bound on these boards (E09-D09 §2.1 G-T2.2)")
            if re.match(r"^(color|type|space|size|radius|border|opacity)\.", tk) and tk not in TOKEN_NAMES:
                raise ValueError(f"{name!r}: {tk} is not a shipped token (token-sync.json)")
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
    oo = {a: b for a, b in (o or {}).items() if b is not None}
    return node("board", name, o=oo or None, kids=unique_names(kids) or None, **kw)


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
         HEADING_SM: (14, 1.2, False), HEADING_MD: (16, 1.2, False), NUM_XS: (10, 1.2, True), NUM_SM: (11, 1.2, True),
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



# --- the seeded synthetic BTCUSDT book (seed 440). Every drawn size, price, count, age and anchor is derived here.
SEED = ISSUE
SYM = S("BTCUSDT")


def _fixture() -> tuple[Decimal, Decimal]:
    rows = json.loads(_doc_bytes("fixture").decode("utf-8"))
    lst = rows.get("result", rows).get("list", []) if isinstance(rows, dict) else rows
    for r in lst:
        if r.get("symbol") == "BTCUSDT":
            return Decimal(r["priceFilter"]["tickSize"]), Decimal(r["lotSizeFilter"]["qtyStep"])
    raise LookupError("fixture: BTCUSDT not found")


TICK, QTY_STEP = _fixture()
COIN = "BTC"
MARK_WORDS = S("mark 64,012.5")  # §2.2: the mark rule's text; the world's mark is this price
MARK = Decimal(MARK_WORDS.split()[1].replace(",", ""))
BEST_BID, BEST_ASK = MARK - TICK, MARK + TICK
TIERS = (50, 200, 500)  # §3: the 50 / 200 / 500 tiers, 200 the default
DEFAULT_TIER = 200
LEVELS = max(TIERS)  # exchange levels a side in the synthetic book (non-empty price levels, gaps between them)
STEP = Decimal(10)  # kit choice: the drawn zoom aggregates 100 ticks a row (`+`/`-`, R-2); bids floor, asks ceil
TRAIL_S = int(re.search(r"trail \[(\d+) s", S("trail [60 s ▾]")).group(1))  # type: ignore[union-attr]
COLS = TRAIL_S  # one heatmap column per trail second (the cell chip's auto: kit, FALLBACKS["cells"])
COL_W = 9
PANE_W = COLS * COL_W  # 540
T1_S = int(re.search(r"T1 \((\d+) s", S("T1 (2 s")).group(1))  # type: ignore[union-attr]
T2_S = 3 * T1_S  # "≥ T2 = 3 × T1" (§4)
STALE_T1_AGE = int(re.search(r"Stale (\d+)s", re.findall(r'"([^"]+)"', COPY["W-5"][0][2])[0]).group(1))  # type: ignore
# the T1 frame draws W-5 / W-6 verbatim (their example age 7 s); that it is ≥ T2 = 6 s is a spec gap (gen_05)
STALE_T2_AGE = int(re.search(r"Stale (\d+)s", re.findall(r'"([^"]+)"', COPY["W-26"][0][2])[0]).group(1))  # type: ignore
NOW = (0, 12, 19)  # kit choice: the newest column's time, UTC (W-7's "last data 00:12" is this minute)
DISC_LAST = (0, 12, 15)  # the disconnected frame's last data
ACCOUNTS = (S("Acct A"), S("Acct B"))  # §0: synthetic accounts
VIEW_AS_USER = "Manager 01"  # synthetic {user} for the rbac.view_as leg
PRESETS = ("0.10", "0.25", "0.50", "1.0")  # `14`:1211's footer (qty [0.10 v] [0.25][0.50][1.0]); 0.10 selected
_RNG = random.Random(SEED)


def hms(t: tuple[int, int, int], dt: int = 0) -> str:
    s = t[0] * 3600 + t[1] * 60 + t[2] - dt
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"


def qz(v: Decimal) -> Decimal:
    return (v / QTY_STEP).to_integral_value(ROUND_HALF_EVEN) * QTY_STEP


@dataclass(frozen=True)
class Own:
    price: Decimal
    side: str  # "buy" / "sell"
    qty: Decimal
    kind: str
    acct: str


# planted prices (the copy deck's figures are the world's): W-14, W-15, the pulled level, the own orders, the position
ICEBERG = Decimal(re.search(r"iceberg ([\d,]+)", COPY["W-14"][0][2]).group(1).replace(",", ""))  # type: ignore
STOP_RUN = Decimal(re.search(r"zone ([\d,]+)", COPY["W-15"][0][2]).group(1).replace(",", ""))  # type: ignore
PULL_WORDS = S("pulled 18.0 (estimated)")
PULL_SIZE = Decimal(PULL_WORDS.split()[1])
PULL_PRICE = Decimal("63960.0")  # kit choice: the pulled bid wall's level
PULL_COL = 44  # the column the wall leaves the book (no print at its price: pulled, M AD-6)
POSITION_AT, POSITION_QTY = Decimal("64020.0"), Decimal("0.30")  # W-25 "Long 0.30 · entry"; §15 item 1's 64,020
AHEAD = Decimal(re.search(r"ahead ([\d.]+)", COPY["W-24"][0][2]).group(1))  # type: ignore[union-attr]
OWN = (Own(Decimal("63980.0"), "buy", Decimal("0.5"), "limit", ACCOUNTS[0]),
       Own(Decimal("63980.0"), "buy", Decimal("0.4"), "limit", ACCOUNTS[1]),
       Own(Decimal("63980.0"), "buy", Decimal("0.3"), "limit", ACCOUNTS[1]),
       Own(Decimal("63950.0"), "buy", Decimal("0.5"), "limit", ACCOUNTS[0]),
       Own(Decimal("64100.0"), "sell", Decimal("0.5"), "limit", ACCOUNTS[1]))
AGG_AT, SINGLE_BUY_AT, SINGLE_SELL_AT = Decimal("63980.0"), Decimal("63950.0"), Decimal("64100.0")
BEHIND = Decimal("0.8")  # kit: resting size queued behind the own orders at the aggregate's level


def _levels(side: str) -> list[Decimal]:
    """LEVELS non-empty price levels from the touch outward, seeded gaps of 2 + Exp(4.8) ticks, the planted prices
    inserted (the farthest dropped to keep LEVELS)."""
    sgn = -1 if side == "bid" else 1
    p = BEST_BID if side == "bid" else BEST_ASK
    out = [p]
    while len(out) < LEVELS:
        p += sgn * TICK * (2 + int(_RNG.expovariate(1 / 4.8)))
        out.append(p)
    planted = {ICEBERG, STOP_RUN, PULL_PRICE, AGG_AT, SINGLE_BUY_AT} if side == "bid" else {SINGLE_SELL_AT,
                                                                                         POSITION_AT}
    out = sorted(set(out) | planted, reverse=side == "bid")[:LEVELS]
    return out


LEVEL_PX = {s: _levels(s) for s in ("bid", "ask")}


def _sizes() -> dict[str, list[list[Decimal]]]:
    """size[side][col][i] for COLS columns (col COLS-1 = now): a lognormal base per level, a seeded walk per column;
    the planted levels are constant (the pulled wall leaves at PULL_COL); sizes on the qty step."""
    out: dict[str, list[list[Decimal]]] = {}
    for side in ("bid", "ask"):
        pxs = LEVEL_PX[side]
        base = [math.exp(_RNG.gauss(-0.6, 0.8)) for _p in pxs]
        cols, cur = [], base[:]
        for c in range(COLS):
            cur = [x * math.exp(_RNG.gauss(0, 0.12)) for x in cur]
            col = [qz(Decimal(repr(round(x, 3)))) or QTY_STEP for x in cur]
            for i, p in enumerate(pxs):
                own = sum((o.qty for o in OWN if o.price == p), Decimal(0))
                if p == AGG_AT:
                    col[i] = AHEAD + own + BEHIND
                elif p == PULL_PRICE:
                    col[i] = PULL_SIZE if c < PULL_COL else Decimal(0)
                elif p == ICEBERG:
                    col[i] = Decimal("0.4")  # the iceberg's visible slice (refilled; its prints below)
                elif own:
                    col[i] = col[i] + own  # the level's size includes the own orders resting there
            cols.append(col)
        out[side] = cols
    return out


SIZES = _sizes()
PRINTS = {BEST_BID: Decimal("0.250"), BEST_ASK: Decimal("0.400"), ICEBERG: Decimal("2.6")}  # last traded size


def row_of(p: Decimal, side: str) -> Decimal:
    """The drawn row of a level: bids floor to STEP, asks ceil to STEP."""
    return (p / STEP).to_integral_value(ROUND_FLOOR if side == "bid" else ROUND_CEILING) * STEP


def tier_px(side: str, tier: int) -> list[Decimal]:
    return LEVEL_PX[side][:tier]


def row_size(r: Decimal, side: str, tier: int, col: int = COLS - 1) -> Decimal | None:
    """The row's resting size on side at tier (None when no level of the tier falls in the row)."""
    xs = [SIZES[side][col][i] for i, p in enumerate(LEVEL_PX[side][:tier]) if row_of(p, side) == r]
    return sum(xs, Decimal(0)) if xs else None


def row_side(r: Decimal) -> str:
    return "ask" if r > MARK else "bid"


def rows_window(n: int) -> list[Decimal]:
    """n rows, top = highest price, around the mark: the asks above it, the bids below (centred, auto-follow)."""
    top_bid = row_of(BEST_BID, "bid")
    n_ask = n // 2
    return [top_bid + STEP * (n_ask - i) for i in range(n)]


def extent_end(side: str, tier: int) -> Decimal:
    return row_of(LEVEL_PX[side][tier - 1], side)


def cum_depth(r: Decimal, tier: int) -> Decimal | None:
    side = row_side(r)
    if row_size(r, side, tier) is None:
        return None
    rows = sorted({row_of(p, side) for p in tier_px(side, tier)}, reverse=side == "bid")
    tot = Decimal(0)
    for x in rows:
        tot += row_size(x, side, tier) or 0
        if x == r:
            return tot
    return None


def row_prints(r: Decimal, tier: int) -> Decimal | None:
    side = row_side(r)
    xs = [v for p, v in PRINTS.items() if p in tier_px(side, tier) and row_of(p, side) == r]
    return sum(xs, Decimal(0)) if xs else None


def own_at(r: Decimal) -> list[Own]:
    return [o for o in OWN if row_of(o.price, "bid" if o.side == "buy" else "ask") == r]


STOP_Q = (0.10, 0.35, 0.60, 0.80, 0.95)  # kit: the stops' lower edges at these quantiles of the visible cells


def stops(tier: int = DEFAULT_TIER, n_rows: int = 25) -> tuple[Decimal, ...]:
    """The five stops' lower edges of the adaptive log scale at tier: STOP_Q of the visible window's non-zero cells
    (both sides, every column)."""
    xs = sorted(v for r in rows_window(n_rows) for c in range(COLS)
                if (v := row_size(r, row_side(r), tier, c)) is not None and v > 0)
    return tuple(qz(xs[min(len(xs) - 1, int(q * len(xs)))]) for q in STOP_Q)


def stop_of(v: Decimal | None, an: tuple[Decimal, ...]) -> int:
    """0 = color.heatmap.zero (no size, or below the first stop), else the highest stop reached (1..5)."""
    return 0 if not v else sum(1 for a in an if v >= a)


def window_max(tier: int = DEFAULT_TIER, n_rows: int = 25) -> Decimal:
    return max(v for r in rows_window(n_rows) for c in range(COLS) if (v := row_size(r, row_side(r), tier, c)))


MINUS = "−"


def price(v: Decimal) -> str:
    return f"{v:,.1f}"


def price0(v: Decimal) -> str:
    """A row price at the drawn zoom (whole USDT)."""
    return f"{v:,.0f}"


def qty1(v: Decimal) -> str:
    return f"{v.quantize(Decimal('0.1'), ROUND_HALF_EVEN):,.1f}"


def qty2(v: Decimal) -> str:
    return f"{v:.2f}"


def anchor_fmt(v: Decimal) -> str:
    return f"{v.quantize(Decimal(1), ROUND_HALF_EVEN):,.0f}" if v >= 10 else qty1(v)


# --- frames, tables, annotations, the board
def data_statement(nn: int) -> str:
    env = (" DEMO and LIVE are separate frames, each badge read from the session environment, never the feed "
           "(C-2.11); the LIVE session holds no synthetic order, so no account appears under both; nothing on the "
           "board switches the environment." if nn == 7 else
           " The env badge reads the session environment (DEMO on this board), never the feed (C-2.11).")
    return (f"Data: synthetic only — a seeded {SYM} book (seed {SEED}): tick {TICK} and qty step {QTY_STEP} from the "
            f"recorded instrument fixture; mark {price(MARK)}; {LEVELS} levels a side with seeded gaps; rows at a "
            f"{STEP:.0f} USDT zoom; {COLS} trail columns of 1 s to {hms(NOW)} UTC; sizes, walls, prints, stops, the "
            f"own orders and position, the accounts \"{ACCOUNTS[0]}\" and \"{ACCOUNTS[1]}\" and the viewing-as user "
            f"\"{VIEW_AS_USER}\" are synthetic. No real account identifier, key or balance.{env}")


def window(fid: str, kids: list[Node | None], *, w: int = WIN_W, h: int = WIN_H, note: str | None = None) -> Node:
    """One frame: a w × h window on color.surface.app, clipped, children positioned (non-flex)."""
    if not any(fid in b.frames for b in BOARDS.values()):
        raise KeyError(f"{fid!r} is not a planned frame")
    return box(frame_name(fid), [k for k in kids if k], {"fill": APP, "clip": True}, w=w, h=h,
               note=note or f"frame {fid}")


def marker_frame(fid: str, kids: list[Node | None], w: int, *, slack: int = 24) -> Node:
    """A board-marker frame (redlines, an inset, specimens): a column on color.surface.canvas, a 'board marker'
    caption first; its height hugs the estimate + slack (rounded to 8)."""
    fallback("marker")
    body = [text("board marker", ui("board marker — not product UI", "board-marker caption"), CAPTION, TEXT_3),
            *[k for k in kids if k]]
    probe = vbox("probe", body, {"gap": STACK_LG}, w=w)
    h = int(math.ceil((est_height(probe) + 2 * PX[INSET_XL] + slack) / 8) * 8)
    if not any(fid in b.frames for b in BOARDS.values()):
        raise KeyError(f"{fid!r} is not a planned frame")
    return vbox(frame_name(fid), body, {"fill": CANVAS, "pad": INSET_XL, "gap": STACK_LG, "clip": True}, w=w, h=h,
                note=f"board-marker frame {fid}")
@dataclass(frozen=True)
class Col:
    key: str
    label: str
    w: int
    typo: str = CAPTION


def cell(name: str, content: str | None, w_: int, *, h: int = 24, typo: str = CAPTION, color: str = TEXT_1,
         kids: list[Node] | None = None) -> Node:
    inner = w_ - 2 * PX[INSET_SM]
    ks = kids if kids is not None else ([text("value", content, typo, color, w=inner)] if content else [])
    return hbox(name, ks, {"padX": INSET_SM, "align": "center", "gap": INSET_XS}, w=w_, h=h)


def grid_table(name: str, cols: list[Col], rows: list[dict[str, Any]], *, cap: str | None = None, row_h: int = 28,
               selected: Iterable[int] = (), header: bool = True) -> Node:
    """A drawn table (CMP-049 form): header row and rows; cells carry 8 px padding a side (16 between texts); a cell
    value may be a str or a list of nodes; a row's height hugs its tallest text."""
    w_ = sum(c.w for c in cols)
    sel = set(selected)
    kids: list[Node | None] = [text("caption", cap, CAPTION, TEXT_2, w=w_ - 16) if cap else None]
    if header:
        kids += [hbox("header row", [cell(f"th · {c.key}", c.label, c.w, color=TEXT_3) for c in cols], {"fill": RAISED},
                      w=w_, h=24), rect("header rule", w_, 1, BORDER)]
    body = []
    for j, r in enumerate(rows):
        need = max(text_h(c.typo, text_lines(r[c.key], c.typo, c.w - 16)) if isinstance(r.get(c.key), str) else 16
                   for c in cols) + 8
        h = max(row_h, int(math.ceil(need / 4) * 4))
        cs = [cell(c.key, v, c.w, h=h, typo=c.typo) if isinstance(v := r.get(c.key), str) or v is None
              else cell(c.key, None, c.w, h=h, kids=v) for c in cols]
        body.append(hbox(f"row · {j + 1:02d}", cs, {"fill": SELECTED if j in sel else CANVAS if j % 2 else RAISED},
                         w=w_, h=h))
    kids.append(vbox("rows", body, {}, w=w_, h=sum(b["h"] for b in body) or 1) if body else None)
    return vbox(name, kids, {"gap": STACK_XS} if cap else {}, w=w_)




def frame_block(fid: str, lines: Iterable[str] = ()) -> tuple[str, list[str]]:
    if not any(fid in b.frames for b in BOARDS.values()):
        raise KeyError(f"{fid!r} is not a planned frame")
    head = [state_line(state_of(fid))] if state_of(fid) in STATES else []
    return fid, head + [x for x in lines if x]


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    b = BOARDS[nn]
    theme = (f"Theme: dark + light — this board is token-bound; it renders under dark and is exported twice: dark as "
             f"{b.export}, light as {b.export_light} (the theme is switched at export; §0 L{S0 + 3}: "
             f"{TWIN_CAP.group(2)} light twins of {TWIN_CAP.group(1)} boards)" if b.twin else  # type: ignore
             f"Theme: dark (exported as {b.export}); the light and high-contrast twins are not drawn — the text "
             f"is binding (§0)")
    head = [f"§0 L{b.line}: {b.draws}", f"Frames: {', '.join(b.frames)}", theme,
            f"Frames {WIN_W} × {WIN_H} windows at compact density unless the frame says otherwise; {SYM} on a seeded "
            f"synthetic book (§0)", *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)
def layout(frames: list[Node], cols: int) -> list[Node]:
    out, y, i = [], MARGIN + 28, 0
    while i < len(frames):
        x = MARGIN
        for f in frames[i:i + cols]:
            out.append(dict(f, x=x, y=y))
            x += f["w"] + MARGIN
        y += max(f["h"] for f in frames[i:i + cols]) + MARGIN + 28
        i += cols
    return out


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y




# root heights as the live check measured them: max(annotation end, footer end) + MARGIN (the annotation column's
# live end is not the kit's estimate, so the drawn value is kept; the footer governs on 03-06 and 08)
ROOT_H = {1: 2139, 2: 1947, 3: 1026, 4: 1026, 5: 1026, 6: 1026, 7: 2126, 8: 1026, 9: 1787, 10: 1667}


def board(nn: int, frames: list[Node], ann: Node, cols: int, *, strict: bool = True) -> tuple[dict[str, Any],
                                                                                            list[Node]]:
    """The root (the board name, grid x/y, color.surface.app, clip) hugging the frames + ONE annotation column + 80; a
    "state: <id>" caption 24 px above each frame; the data statement 24 px under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f) for f in b.frames]
    got = [f["name"] for f in frames]
    if strict and got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != plan {want}")
    if "/" in b.name.split(f"{KEY} / {nn:02d} ", 1)[1]:
        raise ValueError(f"board {nn:02d}: '/' after the prefix in {b.name!r}")
    placed = layout(frames, cols)
    ids = {frame_name(f): f for f in b.frames}
    caps = [text(f"caption {i:02d}", f"state: {ids.get(f['name'], f['name'])}", CAPTION, TEXT_3, x=f["x"],
                 y=f["y"] - 24) for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · data statement", data_statement(nn), CAPTION, TEXT_2, x=MARGIN, y=bottom + 24,
                 w=right - MARGIN)]
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann) * 1.15
    wd = right + MARGIN + ANN_W + MARGIN
    fh = est_height(foot[0])
    foot_end = bottom + 24 + fh
    h = ROOT_H[nn]  # the live check's max(annotation end, footer end) + MARGIN
    # the estimate may wrap the footer one line more than live text does (board 07: estimated end 2058, live 2046)
    if h < foot_end + MARGIN - text_h(CAPTION, 1) or h < MARGIN + ah * 0.8:
        raise ValueError(f"board {nn:02d}: root h {h} vs footer end {foot_end:.0f} / annotation estimate {ah:.0f}")
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the root h {h} is the live check's max(annotation end, footer end "
         f"{foot_end:.0f}) + {MARGIN} (the annotation column estimated {ah:.0f} px with 15 % slack); re-measure it "
         f"if the annotations change")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills "
             f"(raise h in 8 px steps if the lint reports text-overflow)")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


# --- sections (<= SECTION_RAW_BUDGET raw bytes each; the E08-D10 kit's packer), lint
SECTION_RAW_BUDGET, PACKED_MAX = 9000, 9216
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
        part, cut = _pack(n, into, budget - (len(json.dumps({"into": into, "node": {}})) - 2), budget)
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
    text carry h; no '/' in names; table cells padded 8 px a side."""
    bad: list[str] = []

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
        for p, x in walk(n):
            if x["t"] == "board" and re.search(r"/(header row|row · \d+)/[^/]+$", p, re.DOTALL) and \
                    (x.get("o") or {}).get("padX") != INSET_SM:
                bad.append(f"{p}: cell padX {(x.get('o') or {}).get('padX')} (8 px a side required)")
    return bad


def _scan_banned(obj: Any) -> list[str]:
    s = json.dumps(obj, ensure_ascii=False)
    return sorted({m.group(0) for m in BANNED.finditer(s)})


def validate(path: Path) -> tuple[int, str]:
    res = subprocess.run([sys.executable, "-X", "utf8", "-I", str(VALIDATOR), str(path), "--components",
                          str(COMPONENTS), "--tokens", str(TOKENS_FILE)], capture_output=True, text=True, timeout=120,
                         check=False)
    return res.returncode, "\n".join((res.stdout + res.stderr).strip().splitlines())


def write_sheet(nn: int, frames: list[Node], ann: Node, cols: int, *, notes: dict[str, Iterable[str]] | None = None,
                out_dir: Path = CAP_DIR, name: str | None = None, strict: bool = True) -> Path:
    """Assemble board nn, split into sections, merge notes, write out_dir/NN-<slug>.json, run the validator; raise
    unless it exits 0 and the kit lint and the banned scan are clean. Clears NOTES."""
    b = BOARDS[nn]
    out_dir = out_dir.resolve()
    if out_dir not in (CAP_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"sheets go to {CAP_DIR} (or {SELFTEST_DIR} for the self-test)")
    out_dir.mkdir(parents=True, exist_ok=True)
    root, nodes = board(nn, frames, ann, cols, strict=strict)
    live(f"export {b.export}: record the board id and the PNG size")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {DOCS['spec'][0]} md5 {DOCS['spec'][1]} at {HEAD} (§0 L{b.line}); no hand-off file "
                          f"(BQ-2)")
    NOTES.add("sources", f"{DOCS['fixture'][0]} md5 {DOCS['fixture'][1]} ({SYM} tick {TICK}, qty step {QTY_STEP})")
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
    shapes = sum(1 for s in sh["sections"] for _p, _n in walk(s["node"]))
    out = [f"# {b.name}", "", md_line3(nn), "",
           summary or f"Board {nn:02d} of {len(BOARDS)} (§0 L{b.line}: {b.draws}). Grid ({x}, {y}); {sh['board']['w']} x "
                      f"{sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".", "",
           *([f"Light twin: export this board again under the light theme as `{b.export_light}` (token-bound; §0 "
              f"{b.theme_cell}).", ""] if b.twin else []), "## Frames", ""]
    out += [f"- `{frame_name(f)}` (`{f}`)" for f in b.frames]
    out += ["", "## Validator and size", "", f"- `{msg.splitlines()[-1] if msg else ''}` (exit {rc})",
            f"- {len(sh['sections'])} sections, {shapes} shapes, {len(json.dumps(sh))} bytes", ""]
    for kd in ("live_checks", "derivations", "decisions", "spec_gaps", "deviations", "copy_keys", "copy_gaps",
               "fallbacks", "sources", "tokens"):
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
    """Pack with the repo packer (compact.py) into out_dir/<same name>; the packer writes the source's absolute path
    into compactOf.file, which is then rewritten to the bare file name (the sha256 beside it is the source's,
    unchanged); check that, every packed section <= PACKED_MAX bytes, mkcall4 count == the section count (counted
    before the name is made bare), and no banned string outside compactOf."""
    src = Path(sheet_path).resolve()
    out_dir = out_dir.resolve()
    if out_dir not in (V4_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"packed sheets go to {V4_DIR}")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (src.name if out_dir == V4_DIR.resolve() else src.stem + ".packed.json")
    res = subprocess.run([sys.executable, "-X", "utf8", "-I", str(PACKER), str(src), str(dst)], capture_output=True,
                         text=True, timeout=300, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"packer exit {res.returncode}: {(res.stdout + res.stderr).strip()[-600:]}")
    raw = dst.read_text(encoding="utf-8")
    pf = (json.loads(raw).get("compactOf") or {}).get("file")
    if not pf or not Path(pf).is_absolute() or Path(pf) != src:
        raise RuntimeError(f"{dst.name}: compactOf.file {pf!r} is not the absolute source path")
    n_sec = len(json.loads(raw)["sections"])  # mkcall4 reads the pack source, so count before the name is made bare
    cnt = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(MKCALL), str(dst), "count"],
                         capture_output=True, text=True, timeout=120, check=False)
    if cnt.returncode != 0 or cnt.stdout.strip() != str(n_sec):
        raise RuntimeError(f"{dst.name}: mkcall4 count {cnt.stdout.strip()!r} rc {cnt.returncode} != "
                           f"{n_sec}: {cnt.stderr.strip()[-300:]}")
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
    banned = _scan_banned({k: v for k, v in sh.items() if k != "compactOf"})
    if banned:
        raise RuntimeError(f"{dst.name}: banned {banned}")
    return dst


def build(nn: int, frames: list[Node], blocks: list[tuple[str, list[str]]], cols: int, *,
          board_lines: Iterable[str] = (), notes: dict[str, Iterable[str]] | None = None) -> tuple[Path, Path, Path]:
    """write_sheet + write_md + pack_sheet for one board (the generators' last step)."""
    ann = annotations(nn, blocks, board_lines=board_lines)
    p = write_sheet(nn, frames, ann, cols, notes=notes)
    return p, write_md(nn, p), pack_sheet(p)




# --- self-test
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), f"pinned md5s ({len(DOCS)} sources at {HEAD})")
    check(sorted(BOARDS) == list(range(1, 11)), "§0: ten boards 01-10, all PENDING")
    twins = [b.nn for b in BOARDS.values() if b.twin]
    check(twins == [1, 5, 7] and len(twins) * 3 <= len(BOARDS) and TWIN_CAP.groups() == ("10", "3"),  # type: ignore
          f"§0: light twins {twins} (≤ ⅓)")
    check(PAGE == KEY and FILE_NAME == f"{KEY} boards" and EXPORT_DIR == f"docs/design/{EPIC}/img",
          f"page {PAGE!r}, file {FILE_NAME!r}, export dir {EXPORT_DIR!r}")
    check((WIN_W, WIN_H) == (1280, 800), f"frames {WIN_W} × {WIN_H}")
    drawn = {state_of(f) for b in BOARDS.values() for f in b.frames if f.startswith("SCR-050/")}
    check(sorted(STATES) == sorted(drawn) and all(s in [state_of(f) for f in BOARDS[int(plain(c[7]))].frames]
                                                  for s, (c, _i) in STATES.items()),
          f"§4: all {len(STATES)} states drawn on their §0 boards ({sorted(drawn)})")
    check(sorted(COPY, key=lambda x: int(x[2:])) == [f"W-{i}" for i in range(1, 31)], "§12: W-1..W-30")
    check(COL_HEADS == ("Price", "Bid (B)", "Ask (A)", "Prints", "Cum. depth", "Your orders"),
          f"§2.3: six columns {COL_HEADS}")
    for w in ("W-3", "W-20"):
        check(len(W(w)) <= 60 and W(w).endswith(".") and W(w).count(".") == 1, f"{w} ≤ 60 characters, one sentence")
    check(str(TICK) == "0.10" and str(QTY_STEP) == "0.001", f"fixture {SYM} tick {TICK}, qty step {QTY_STEP}")
    check(all(x >= 0 and x % QTY_STEP == 0 for s in SIZES.values() for c in s for x in c), "book: sizes on the step")
    win = rows_window(25)
    check(all(row_size(r, row_side(r), DEFAULT_TIER) for r in win),
          f"200 tier: all 25 rows {price0(win[-1])}–{price0(win[0])} hold a level")
    check(all(LEVEL_PX["bid"].index(p) < DEFAULT_TIER for p in (ICEBERG, STOP_RUN, PULL_PRICE, AGG_AT, SINGLE_BUY_AT))
          and all(LEVEL_PX["ask"].index(p) < DEFAULT_TIER for p in (SINGLE_SELL_AT, POSITION_AT)),
          "planted levels inside the 200 tier")
    check(all(row_of(p, s) in win for p, s in ((ICEBERG, "bid"), (STOP_RUN, "bid"), (PULL_PRICE, "bid"),
                                               (AGG_AT, "bid"), (SINGLE_SELL_AT, "ask"), (POSITION_AT, "ask"))),
          "planted rows inside the drawn window")
    check(sum((o.qty for o in own_at(AGG_AT)), Decimal(0)) == Decimal("1.2") and len(own_at(AGG_AT)) == 3,
          "W-23: 3 orders, buy 1.2 at the aggregate's row")
    w6 = re.findall(r'"([^"]+)"', COPY["W-6"][0][2])[0]
    check(T1_S == 2 and T2_S == 6 and T1_S <= STALE_T1_AGE and T2_S <= STALE_T2_AGE
          and w6 == f"Last update {STALE_T1_AGE} s ago",
          f"stale ages: the T1 frame {STALE_T1_AGE} s = W-5's and W-6's figure; ≥ T2 {STALE_T2_AGE} s = W-26's")
    for t in TIERS:
        a = stops(t)
        check(all(a[i] < a[i + 1] for i in range(4)), f"tier {t}: stops strictly rising {[str(x) for x in a]}")
    miss = sorted(v for k_, v in globals().items() if k_.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border|opacity)\.", v) and v not in TOKEN_NAMES)
    hmiss = [hm(s, i, c) for s in ("bid", "ask") for i in range(1, 6) for c in (False, True)
             if hm(s, i, c) not in TOKEN_NAMES]
    check(not miss and not hmiss, f"kit tokens exist (missing {miss + hmiss})")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: text("x", "y", color="color.text.disabled"),
                 lambda: rect("x", 1, 1, "color.not.a.token"), lambda: box("x", [], {"opacity": "opacity.disabled"}),
                 lambda: S("not a spec string at all xyzzy"), lambda: W("W-13", nope=1), lambda: W("W-13"),
                 lambda: Wf("W-2", {"99,999": "1"})):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError, LookupError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/', the never-tokens, an unknown token, a non-spec string, an "
                "unfilled slot and an absent figure refused")
    NOTES.reset()
    fid = BOARDS[1].frames[0]
    fr = window(fid, [text("sample", W("W-1"), HEADING_SM, TEXT_1, x=40, y=40)])
    ann = annotations(1, [frame_block(fid, ["self-test"])], board_lines=["Self-test sheet, not a board of the set"])
    path = write_sheet(1, [fr], ann, 1, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False)
    check(path.exists(), f"validator exit 0: {path.name}")
    md = write_md(1, path, summary="Self-test sheet (one sample frame); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    check(l3 == md_line3(1) and f"page `{PAGE}`" in l3 and l3.endswith("theme dark."), f"md line 3: {l3}")
    packed = pack_sheet(path, SELFTEST_DIR)
    sh = json.loads(packed.read_text(encoding="utf-8"))
    check(sh["compactOf"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest(),
          f"packed {packed.name}: source sha256 = raw, {len(sh['sections'])} sections, mkcall4 count agrees")
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
    raise SystemExit(2)
