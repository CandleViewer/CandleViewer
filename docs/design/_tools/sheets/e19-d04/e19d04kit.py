"""E19-D04 (#439) board kit: the ten boards of the profile flows (presets, period anchoring, drawing anchors, the
gesture-conflict matrix, the keyboard paths) on SCR-038 / SCR-039, as cvsheet JSON sheets for the Penpot file
"E19-D04 boards", page "E19-D04" (spec §0; the BQ ruling of comment 6585044844 is folded in the spec; its strings stay PROPOSED
until the owner approves). The boards are drawn: spec §0 and §16 record them, BUILD.md rebuilds the sheets.

Offline only. Sources (binding; every drawn string comes from them, k.S checks it verbatim): the spec
docs/design/E19/E19-D04.md (§0's board table, §8's states, §9's copy deck W-n, §5's matrix and §6's keyboard table are
parsed, never typed), the E19-D03 spec (D03: the profile panel's words, its copy deck D03 W-n), the E19-D02 spec (D02,
its copy deck D02 W-n), E14-D02 / E14-D07 (the drawing popover, handles, context menu and delete toast) and E17-D02
(the feed chip), all read by repo-relative path from a checkout and md5-pinned in DOCS (the kit refuses drifted bytes:
re-read, re-check, re-pin). D02 and D03 are read from the checkout when its bytes match the pin, else from the pinned
commit with `git show` (the spec reads them at PR #5487's / #5517's heads until they merge). The recorded instrument
fixture gives BTCUSDT's tick size and qty step only; every price, size, time and level on a board is the seeded
synthetic world below (seed 439, the issue number), derived once and never typed twice.

Checkout: the repository root is $CV_REPO when set, else this file's parents[4] (the committed layout
docs/design/_tools/sheets/e19-d04/). Outputs: raw sheets + their .md in CAP_DIR, packed sheets in V4_DIR.

Pipeline (one generator per board, gen/gen_NN.py, calling gen/flows.py on gen/panel.py):
    frames = [builder(theme) for each §0 frame]  # nested frames in §0's order
    build(nn, frames, blocks)                    # raw sheet (validator exit 0 or raises), md (line 3 = render line),
                                                 # packed sheet (mkcall4 count agrees; compactOf = bare name + sha256)
Self-test: python3 -I -B e19d04kit.py selftest

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (U+2215 stands for it); no local path, host
or agent name anywhere in a sheet (BANNED); packed sections <= 9 KB; table cells carry 8 px inner padding a side;
every frame has a "state: <id>" caption.
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
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KEY, EPIC, ISSUE = "E19-D04", "E19", 439
KIT_DIR = Path(__file__).resolve().parent
_SPEC_PATH = "docs/design/E19/E19-D04.md"


def _repo() -> Path:
    env = os.environ.get("CV_REPO")
    if env:
        if not (Path(env) / _SPEC_PATH).is_file():
            raise SystemExit(f"e19d04kit: CV_REPO has no {_SPEC_PATH}")
        return Path(env).resolve()
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / _SPEC_PATH).is_file():
        return up
    raise SystemExit("e19d04kit: run inside a checkout or set CV_REPO to one")


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
BASE = "95a625b09"  # the text PR's base v2 (origin/main); E14 / E17 specs and the fixture are read there
# key -> (repo-relative path, md5, commit to read from when the checkout's bytes differ or the file is absent; "" =
# this checkout only: the spec is read where the kit is committed, its §0 and §16 recording the boards as drawn).
# The md5 pins sit apart from the paths (a hex value beside a path is the shape a secret scanner flags).
_PATHS = {
    "spec": _SPEC_PATH,
    "d03": "docs/design/E19/E19-D03.md",
    "d02": "docs/design/E19/E19-D02.md",
    "d02e14": "docs/design/E14/E14-D02.md",
    "d07e14": "docs/design/E14/E14-D07.md",
    "d02e17": "docs/design/E17/E17-D02.md",
    "fixture": "packages/fixtures/bybit/2026-10-05/rest/instruments_before.json",
}
_MD5 = {
    "spec": "bad23883d6c6a70aeebfb359e873ae3a",
    "d03": "928db4e4b68dafe97694c6ec9a718c7b",
    "d02": "1299df3b853121295e018bed3b819262",
    "d02e14": "8560e3060eb1ed1711ede63becb662bc",
    "d07e14": "697232d6e088c861ac7e30cf9d95ca9c",
    "d02e17": "cb9a4d78b6f73de77e6bcebaefb44ff0",
    "fixture": "edd9dd2a060c51bd4bd1450307728ddf",
}
_AT = {"spec": "", "d03": "35032f521", "d02": "3619e95c5", "d02e14": BASE, "d07e14": BASE, "d02e17": BASE,
       "fixture": BASE}
DOCS = {k: (_PATHS[k], _MD5[k], _AT[k]) for k in _PATHS}
REV = "r1"
PITCH_X, PITCH_Y = 7600, 5600  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80
ANN_W = 400
ANN_TEXT_W = ANN_W - 32
SECTION_RAW_BUDGET = 9000
PACKED_MAX = 9216
SLASH = "∕"  # U+2215 stands for "/" in node names (Penpot splits names on "/")
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts, URLs and agent part names never belong in a sheet; the words are hex here so this file carries
# none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "636c61756465", "68747470", "7777772e", "2d6f7263686573747261746f72")) + r"|wt/\d|\b"
    + bytes.fromhex("616e76696c").decode() + r"\b", re.I | re.DOTALL)
_SOURCE_NOTE: dict[str, str] = {}


def _doc_bytes(k: str) -> bytes:
    path, md5, commit = DOCS[k]
    f = REPO / path
    if f.is_file() and hashlib.md5(f.read_bytes()).hexdigest() == md5:
        _SOURCE_NOTE[k] = "checkout"
        return f.read_bytes()
    if not commit:
        raise SystemExit(f"e19d04kit: {path} drifted from its md5 {md5[:8]}: re-read, re-check, re-pin")
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{path}"], capture_output=True, timeout=60,
                         check=False)
    if res.returncode != 0:
        raise SystemExit(f"e19d04kit: {path} is neither in the checkout at its pin nor readable at {commit}")
    _SOURCE_NOTE[k] = f"git show {commit}"
    return res.stdout


_BYTES = {k: _doc_bytes(k) for k in DOCS}


def spec_md5_ok() -> dict[str, bool]:
    return {k: hashlib.md5(_BYTES[k]).hexdigest() == DOCS[k][1] for k in DOCS}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:
    raise SystemExit(f"e19d04kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
LINES = {k: _COMMENT.sub("", _BYTES[k].decode("utf-8")).split("\n") for k in DOCS if k != "fixture"}
TEXTS = {k: "\n".join(v) for k, v in LINES.items()}
DOC_LABEL = {"spec": "spec", "d03": "D03", "d02": "D02", "d02e14": "D02E14", "d07e14": "D07E14",
             "d02e17": "D02E17"}
WORD_DOCS = ("spec", "d03", "d02", "d02e14", "d07e14", "d02e17")


def _cells(row: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


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


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("**", "").replace("\\|", "|")).strip()


def _flat(doc: str) -> str:
    return re.sub(r"[ \t]*\n[ \t]*", " ", TEXTS[doc].replace("\\|", "|"))


_FLAT = {k: _flat(k) for k in TEXTS}


def S(chars: str, doc: str | None = None) -> str:
    """A drawn string that must occur verbatim in a source (doc names one): returns it."""
    docs = [doc] if doc else list(WORD_DOCS)
    if not any(chars in _FLAT[d] for d in docs):
        raise LookupError(f"{'/'.join(docs)}: string not in the text: {chars!r}")
    return chars


def SL(chars: str, doc: str | None = None) -> str:
    """'<doc> L<n>': where a verbatim string first stands (after S)."""
    S(chars, doc)
    for d in [doc] if doc else list(WORD_DOCS):
        if chars in _FLAT[d]:
            for n in (len(chars), 40, 20, 10):
                for i, ln in enumerate(LINES[d], 1):
                    if chars[:n] in ln.replace("\\|", "|"):
                        return f"{DOC_LABEL[d]} L{i}"
    raise LookupError(chars)


# --- §0: the ten boards (parsed) and the kit's frame plan
_H0 = L("## 0. Status and the boards")
_S0 = LINES["spec"][_H0 + 1]
FILE_NAME = re.search(r"Penpot file `([^`]+)`", _S0).group(1)  # type: ignore[union-attr]
PAGE = re.search(r"page `([^`]+)`", _S0).group(1)  # type: ignore[union-attr]
EXPORT_PATTERN = re.search(r"exports go to `([^`]+)`", _S0).group(1)  # type: ignore[union-attr]
_WIN = re.search(r"(\d+) × (\d+) windows", _S0)
WIN_W, WIN_H = int(_WIN.group(1)), int(_WIN.group(2))  # type: ignore[union-attr]
DRAWING_NAME = re.search(r'synthetic rectangle drawing named "([^"]+)"', _S0).group(1)  # type: ignore[union-attr]
NOT_DRAWN_LINE = L("**Not drawn — the text is binding**", _H0)
NOT_DRAWN = tuple(re.findall(r"`(SCR-03[89]/[a-z0-9-]+)`", LINES["spec"][NOT_DRAWN_LINE - 1]))
# kit choice: the gesture-matrix frames are reference sheets (§5's sixteen rows at full text, then the cursor key),
# 1280 wide like a window and as tall as the table needs; flows.f_matrix raises when the content outgrows them
MATRIX_SIZE = (1280, 1200)
FRAME_SIZE = {"SCR-038/gesture-matrix-dark": MATRIX_SIZE, "SCR-038/gesture-matrix-light": MATRIX_SIZE}


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E19-D04 / 01 preset-menu" (§0 verbatim)
    slug: str
    cell: str  # §0's Frames cell, plain
    theme: str  # "dark" (every board; a light twin is a "-light" frame on a dark board)
    twin: bool
    line: int
    frames: tuple[str, ...]  # frame ids in §0's order

    @property
    def export(self) -> str:
        return EXPORT_PATTERN.replace("NN", f"{self.nn:02d}").replace("<slug>", self.slug)

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"

    @property
    def mixed(self) -> bool:
        """A board that nests a '-light' twin beside its '-dark' frames: exported once per theme (kit reading R-K1)."""
        return self.twin and any(f.endswith("-light") for f in self.frames)

    @property
    def export_light(self) -> str:
        return self.export.replace(".png", "-light.png")


def _boards() -> dict[int, Board]:
    out: dict[int, Board] = {}
    for i in range(_H0 + 2, NOT_DRAWN_LINE):
        ln = LINES["spec"][i - 1]
        if not re.match(r"^\| \d{2} ", ln):
            continue
        c = _cells(ln)
        nn = int(c[0])
        m = re.fullmatch(rf"`({re.escape(KEY)} / {nn:02d} ([a-z0-9-]+))`", c[1])
        if not m or not (plain(c[4]) == "PENDING" or c[4].startswith("drawn: board id ")):
            raise ValueError(f"§0 L{i}: board cell {c[1]!r} / state {c[4]!r}")
        shots = tuple(re.findall(r"`(SCR-03[89]/[a-z0-9-]+)`", c[2]))
        th = plain(c[3])
        if th not in ("dark", "dark, light twin"):
            raise ValueError(f"§0 L{i}: theme {th!r}")
        out[nn] = Board(nn, m.group(1), m.group(2), plain(c[2]), "dark", th == "dark, light twin", i, shots)
    return out


BOARDS = _boards()


def frame_theme(fid: str, board_theme: str) -> str:
    """A frame's own theme: its id's '-dark' / '-light' suffix, else the board's."""
    m = re.search(r"-(dark|light)$", fid)
    return m.group(1) if m else board_theme


def frame_size(fid: str) -> tuple[int, int]:
    return FRAME_SIZE.get(fid, (WIN_W, WIN_H))


def frame_name(fid: str) -> str:
    return fid.replace("/", SLASH)


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


# --- §8's state rows (parsed): frame id -> (trigger, what shows, copy, announcement, T2, board) for the annotations
def _states() -> dict[str, tuple[str, ...]]:
    a = L("## 8. States (boards 01–10")
    out: dict[str, tuple[str, ...]] = {}
    for i in range(a + 1, L("## 9. Copy deck (W-n)")):
        ln = LINES["spec"][i - 1]
        if not ln.startswith("| `SCR-"):
            continue
        c = _cells(ln)
        for fid in re.findall(r"`(SCR-03[89]/[a-z0-9-]+)`", c[0]):
            out[fid] = (*(plain(x) for x in c[1:7]), str(i))
    return out


STATES = _states()


def state_line(fid: str) -> str:
    """§8's row for a frame, as one annotation line (cited by its line)."""
    trig, shows, copy_, ann, t2, _bd, ln = STATES[fid]
    return (f"§8 L{ln}: trigger \"{trig}\"; shows \"{shows}\"; copy {copy_}; announcement {ann}"
            + (f"; {t2}" if t2 != "—" else ""))


# --- tokens (exact names in token-sync.json; the self-test checks every one). No local token rows: §11 adds nothing.
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_ON_ACTION = "color.text.on-action"
BORDER, BORDER_SUBTLE, BORDER_STRONG, RING = ("color.border.default", "color.border.subtle", "color.border.strong",
                                              "color.focus.ring")
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
INFO_SUBTLE, INFO_STRONG = "color.status.info.subtle", "color.status.info.strong"
WARN, WARN_SUBTLE, WARN_STRONG = ("color.status.warning.default", "color.status.warning.subtle",
                                  "color.status.warning.strong")
DANGER, DANGER_SUBTLE, DANGER_STRONG = ("color.status.danger.default", "color.status.danger.subtle",
                                        "color.status.danger.strong")
NEUTRAL = "color.neutral.default"
CANDLE_UP, CANDLE_DOWN, WICK = "color.candle.up", "color.candle.down", "color.candle.wick"
BUY, SELL = "color.buy.default", "color.sell.default"
P_BAR, P_POC, P_VA = "color.profile.bar", "color.profile.poc", "color.profile.valuearea"
GRID, AXIS_TEXT = "color.grid.line", "color.axis.text"
STALE_SURFACE = "color.data-confidence.stale.surface"
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD, HEADING_LG = "type.ui.heading-sm", "type.ui.heading-md", "type.ui.heading-lg"
NUM_XS, NUM_SM, NUM, NUM_MD, NUM_LG, NUM_XL = ("type.num.xs", "type.num.sm", "type.num.base", "type.num.md",
                                              "type.num.lg", "type.num.xl")
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
BUTTON_PADX, DIALOG_PAD = "space.button.paddingX", "space.dialog.padding"
ICON_SM, ICON = "size.icon.sm", "size.icon"
R_CONTROL, R_CARD, R_BADGE, R_DIALOG = "radius.control", "radius.card", "radius.badge", "radius.dialog"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
SCRIM = "opacity.scrim"
EL_POPOVER, EL_DIALOG = "elevation.popover", "elevation.dialog"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, BUTTON_PADX: 12, DIALOG_PAD: 24, ICON_SM: 12, ICON: 16}
NEVER = ("color.text.disabled", "opacity.disabled")  # §1.4 G-T2.2: never on a T2 label, glyph or reason
FALLBACKS = {
    "chrome": "kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the "
              "bound chart is a plain SCR-030 price pane (candles, grid, price axis); its status row draws only the "
              "chips these flows touch (the tool chip, the feed chip on the stale frame) — no environment "
              "badge or control anywhere (R-1, C-2.11)",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs",
    "scrim": "opacity.scrim is a Tier-1 primitive (validator WARN); the CMP-078 stale shade and the dialog scrim use it",
    "hidden": "kit choice: a string a screen reader hears (an accessible name, a polite announcement) is drawn for the "
              "board as caption text in a bordered 'visually hidden' box (not on screen in the product)",
    "busy-free": "kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a "
                 "specimen, a click path or a measurement, never product UI",
    "chart-ring": "token-sync.json has no color.chart.focus.ring; SD:715 aliases it to color.focus.ring, so the canvas "
                  "ring binds color.focus.ring",
    "link": "kit stand-in: the link glyph (§4.2) is not in the local icon set; it is drawn as two interlocked 7 × 5 px "
            "rings stroked 1 px in color.text.secondary beside W-33 (the words carry the state, R-2)",
    "cursor": "kit stand-in: a CSS cursor (§5's keywords) is drawn as a small shape (crosshair: two 1 px strokes; "
              "ew-resize / ns-resize: a bar with two end ticks; grab / grabbing / move / pointer / default: a 10 px "
              "glyph box) with its keyword beside it in type.num.sm — the shape is a board marker, the keyword binds",
    "handle": "E14's handle language (§11): a color.text.primary dot in a color.border.strong ring, the glyph 8 px "
              "(D02E14 L287), its 24 × 24 target drawn only as a dashed board-marker outline where the target matters",
    "elevation3": "elevation.3 is a Tier-1 primitive (validator WARN): the delete toast's binding as D07E14 L299 names it",
    "glyph": "kit stand-in (the E19-D03 kit's): the engine bakes the HVN / LVN triangles into the bar instance; the "
             "board draws them as the characters ▶ / ◀ in type.num.xs",
    "selection": "kit stand-in: the field's selected text is drawn as a color.surface.selected box behind the name",
}
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}


# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "readings", "spec_gaps", "fallbacks", "tokens", "live_checks",
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
    NOTES.add("live_checks", line)


def copy_gap(line: str) -> None:
    """A drawn string no source words (a kit choice or a neutral placeholder): say where it comes from."""
    NOTES.add("copy_gaps", line)


def reading(line: str) -> None:
    NOTES.add("readings", line)


def derive(line: str) -> None:
    NOTES.add("derivations", line)


def fallback(key: str) -> None:
    NOTES.add("fallbacks", FALLBACKS[key])


def copy_key(line: str) -> None:
    NOTES.add("copy_keys", line)


_KEYS = {
    "board": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "kids", "note"},
    "text": {"t", "name", "chars", "typo", "color", "w", "align", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "rect": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "ellipse": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "icon": {"t", "name", "icon", "color", "size", "x", "y", "abs", "alignSelf", "note"},
}


def node(t: str, name: str, **kw: Any) -> Node:
    """A node of type t (None values dropped). Refuses inst nodes, unknown keys, "/" in the name, a non-string
    o.wrap, a NEVER token and a banned string in the name, note or chars. Records bound tokens."""
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
                raise ValueError(f"{name!r}: {tk} is never bound (§1.4 G-T2.2)")
            NOTES.add("tokens", tk)
    return n


def text(name: str, chars: str, typo: str = BODY, color: str = TEXT_1, **kw: Any) -> Node:
    if not str(chars).strip():
        raise ValueError(f"text {name!r} is empty")
    return node("text", name, chars=str(chars).replace("`", ""), typo=typo, color=color, **kw)  # no backtick is drawn


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


# --- text metrics (estimates; Inter / JetBrains Mono at the type tokens' sizes)
_FONT = {CAPTION: (11, 1.2, False), BODY: (13, 1.4, False), BODY_STRONG: (13, 1.4, False), LABEL: (12, 1.2, False),
         HEADING_SM: (14, 1.2, False), HEADING_MD: (16, 1.2, False), NUM_XS: (10, 1.2, True), NUM_SM: (11, 1.2, True),
         NUM: (13, 1.2, True), NUM_MD: (14, 1.2, True), HEADING_LG: (20, 1.2, False), NUM_LG: (16, 1.2, True),
         NUM_XL: (20, 1.2, True)}
MONO_ADVANCE = Decimal("0.6")  # em (D04E11:196, §6.1)


def text_w(chars: str, typo: str, scale: float = 1.0) -> float:
    size, _lh, mono = _FONT.get(typo, _FONT[BODY])
    return round(len(chars) * (0.6 if mono else 0.56) * size * scale, 1)


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




# --- the copy decks (parsed): the spec's §9 (W-n), D03's §13 (D03 W-n), D02's §12 (D02 W-n); each cell's quoted
# strings in order
def _deck(doc: str, head: str) -> dict[str, tuple[list[str], int]]:
    a = find_line(head, doc)
    out: dict[str, tuple[list[str], int]] = {}
    for i in range(a + 1, len(LINES[doc]) + 1):
        ln = LINES[doc][i - 1]
        if ln.startswith("## ") and i > a + 1:
            break
        m = re.match(r"^\| (W-\d+) +\| (.*?) +\| ", ln)
        if m:
            out[m.group(1)] = (re.findall(r'"([^"]+)"', m.group(2)), i)
    return out


DECK = {"spec": _deck("spec", "## 9. Copy deck (W-n)"), "d03": _deck("d03", "## 13. Copy deck (W-n)"),
        "d02": _deck("d02", "## 12. Copy deck (W-n)")}


def W(num: int, alt: int = 0, *, doc: str = "spec", **subs: str) -> str:
    """The copy-deck string W-n (D03's with doc="d03", D02's with doc="d02"), alternative alt, its {placeholders}
    filled from the world; every placeholder in the string must be filled (an illustrative number is never kept)."""
    strings, ln = DECK[doc][f"W-{num}"]
    s = strings[alt]
    for a, b in subs.items():
        a = a.replace("_", " ")
        if "{" + a + "}" not in s:
            raise ValueError(f"{doc} W-{num} {s!r}: no placeholder {{{a}}}")
        s = s.replace("{" + a + "}", b)
    if re.search(r"\{[^}]+\}", s):
        raise ValueError(f"{doc} W-{num}: unfilled placeholder in {s!r}")
    who = {"spec": "", "d03": "D03 ", "d02": "D02 "}[doc]
    copy_key(f"{who}W-{num}: \"{strings[alt]}\" ({DOC_LABEL[doc]} L{ln})" + (" filled from the world" if subs else ""))
    return s


def W3(num: int, alt: int = 0, *, doc: str = "d03", **subs: str) -> str:
    """The panel pieces copied from the E19-D03 kit say W(n) for D03's deck: this is that call."""
    return W(num, alt, doc=doc, **subs)


def tpl(example: str, subs: dict[str, str], doc: str | None = None) -> str:
    """A source example re-filled with this frame's derived values: the example must occur verbatim."""
    S(example, doc)
    out = example
    for a, b in subs.items():
        if a not in out:
            raise ValueError(f"{a!r} not in {example!r}")
        out = out.replace(a, b)
    if out != example:
        derive(f'"{out}": the example "{example}" ({SL(example, doc)}) with this frame\'s values')
    return out


# --- the synthetic world (seed 439, the issue number; declared synthetic on every board)
UTC = timezone.utc
SEED = ISSUE
SYMBOL = "BTCUSDT"


def _fixture() -> tuple[Decimal, Decimal]:
    d = json.loads(_BYTES["fixture"].decode("utf-8"))
    row = next(r for r in d["result"]["list"] if r["symbol"] == SYMBOL)
    return Decimal(row["priceFilter"]["tickSize"]), Decimal(row["lotSizeFilter"]["qtyStep"])


TICK, QTY_STEP = _fixture()  # 0.10, 0.001
PRICE_DP = max(0, -TICK.normalize().as_tuple().exponent)  # type: ignore[operator]
QTY_DP = max(0, -QTY_STEP.normalize().as_tuple().exponent)  # type: ignore[operator]
BAR = timedelta(minutes=5)  # the bound chart's interval: §0's drawing "Rectangle 13:40 → 14:05" sits on 5-minute bars
INTERVAL = "5m"
DAY0 = datetime(2026, 11, 2, tzinfo=UTC)  # R-7's example date; the one session of the world (nothing before it)
NOW = datetime(2026, 11, 2, 14, 30, tzinfo=UTC)  # the boards' clock: the forming bar opened at 14:25
START_PX = 68400.0
LEG_BARS = 24  # the walk's drift is redrawn every two hours
DRIFT, NOISE, RANGE_SD = 9.0, 30.0, 14.0  # USDT per bar: drift bound, close noise and high / low excursion (s.d.)
ROW_TICKS = 100  # the panel's row size (10.0 USDT), kit choice
VA_PCT = 70  # `22`:4876 default, the legend's "VA 70 %"
TICKS_FROM = DAY0  # recorded trades for every bar (nothing approximated in this world)
IB_MIN = 60
SHARES = (Decimal("0.40"), Decimal("0.45"), Decimal("0.50"), Decimal("0.55"), Decimal("0.60"))  # buy share per tick


def qt(v: float | Decimal) -> int:
    """A price in USDT to integer ticks (round half even)."""
    return int((Decimal(str(v)) / TICK).to_integral_value(rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True)
class Bar:
    start: datetime
    o: int  # ticks
    h: int
    l: int  # noqa: E741
    c: int
    vol: int  # qty steps (milli-BTC)
    wick: tuple[int, int] | None = None

    @property
    def end(self) -> datetime:
        return self.start + BAR

    @property
    def approximated(self) -> bool:
        return self.start < TICKS_FROM

    @property
    def top(self) -> int:
        return self.h

    @property
    def bottom(self) -> int:
        return self.l


def _bars() -> list[Bar]:
    """One seeded walk of 5-minute bars from DAY0 to the clock: a drift redrawn every LEG_BARS bars, gaussian noise;
    volume heavier 13:00-17:00 UTC."""
    rng = random.Random(SEED)
    out: list[Bar] = []
    px, t, drift = START_PX, DAY0, 0.0
    i = 0
    while t < NOW:
        if i % LEG_BARS == 0:
            drift = rng.uniform(-DRIFT, DRIFT)
        o = px
        c = o + drift + rng.gauss(0, NOISE)
        hi, lo = max(o, c) + abs(rng.gauss(0, RANGE_SD)), min(o, c) - abs(rng.gauss(0, RANGE_SD))
        vol = rng.randint(3000, 15000) + (5000 if 13 <= t.hour < 17 else 0)
        out.append(Bar(t, qt(o), qt(hi), qt(lo), qt(c), vol))
        px, t, i = c, t + BAR, i + 1
    return out


BARS = _bars()


def bars_between(a: datetime, b: datetime) -> list[Bar]:
    """The bars that open in [a, b)."""
    return [x for x in BARS if a <= x.start < b]


def bar_at(t: datetime) -> Bar:
    return next(x for x in BARS if x.start == t)


def last_price(at: datetime = NOW) -> int:
    return [x for x in BARS if x.start < at][-1].c


def _per_tick(b: Bar) -> dict[int, tuple[int, int]]:
    """One bar's (buy, sell) per tick in qty steps: seeded triangle weights peaking mid-range, times a seeded factor
    1-4; a buy share per tick from SHARES."""
    rng = random.Random(f"{SEED}-{b.start:%Y%m%d%H%M}")
    n = b.h - b.l + 1
    mid = (n - 1) / 2
    w = [(1 + round(mid - abs(i - mid))) * rng.randint(1, 4) for i in range(n)]
    tot = sum(w)
    share = [b.vol * x // tot for x in w]
    for i in sorted(range(n), key=lambda i: (-(b.vol * w[i] % tot), i))[:b.vol - sum(share)]:
        share[i] += 1
    out = {}
    for i, v in enumerate(share):
        sh = rng.choice(SHARES)
        buy = int((Decimal(v) * sh).to_integral_value(rounding=ROUND_HALF_EVEN))
        out[b.l + i] = (buy, v - buy)
    return out


_TICKS: dict[datetime, dict[int, tuple[int, int]]] = {}


def per_tick(b: Bar) -> dict[int, tuple[int, int]]:
    if b.start not in _TICKS:
        _TICKS[b.start] = _per_tick(b)
    return _TICKS[b.start]


LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"  # `24`:1021: A–Z, a–z, AA, … by bucket index


@dataclass
class Level:
    vol: int = 0
    buy: int = 0
    sell: int = 0
    approx: int = 0  # the bar-approximated part of vol (no side)
    tpo: set[int] = field(default_factory=set)  # TPO bucket indices touching the row (recorded bars only)

    @property
    def delta(self) -> int:
        return self.buy - self.sell

    @property
    def recorded(self) -> int:
        return self.vol - self.approx


@dataclass
class Profile:
    label: str
    kind: str  # the period word (PD-6): Session, Fixed range, Visible range, Anchored, Composite
    start: datetime
    end: datetime
    row_ticks: int
    tpo_min: int
    levels: dict[int, Level]
    complete: bool
    vwap_ticks: Decimal
    last_ticks: int
    poc: int = 0
    va: tuple[int, int] = (0, 0)
    hvn: tuple[int, ...] = ()
    lvn: tuple[int, ...] = ()
    va_pct: int = VA_PCT

    def price(self, r: int) -> Decimal:
        """A row's price: its lower boundary (`24`:987)."""
        return r * self.row_ticks * TICK

    @property
    def rows(self) -> list[int]:
        return list(range(min(self.levels), max(self.levels) + 1))

    def lv(self, r: int) -> Level:
        return self.levels.get(r) or Level()

    @property
    def total(self) -> int:
        return sum(x.vol for x in self.levels.values())

    @property
    def max_vol(self) -> int:
        return max(x.vol for x in self.levels.values())

    @property
    def untraded(self) -> list[int]:
        return [r for r in self.rows if self.lv(r).vol == 0]

    @property
    def zero_delta(self) -> list[int]:
        return [r for r in self.rows if self.lv(r).recorded > 0 and self.lv(r).delta == 0]

    @property
    def approximated(self) -> list[int]:
        return [r for r in self.rows if self.lv(r).approx > 0]

    @property
    def single_prints(self) -> list[int]:
        return [r for r in self.rows if len(self.lv(r).tpo) == 1]

    @property
    def tpo_buckets(self) -> int:
        return max((max(x.tpo) for x in self.levels.values() if x.tpo), default=-1) + 1

    def letters(self, r: int) -> str:
        return "".join(LETTERS[i] for i in sorted(self.lv(r).tpo))

    @property
    def ib(self) -> tuple[int, int] | None:
        """The rows the first IB_MIN minutes touched (recorded bars), or None when the session lacks them."""
        k = IB_MIN // self.tpo_min
        rs = [r for r in self.rows if any(i < k for i in self.lv(r).tpo)]
        return (min(rs), max(rs)) if rs and self.start.hour == 0 else None


def build_profile(label: str, kind: str, bars: list[Bar], *, row_ticks: int = ROW_TICKS, tpo_min: int = 30,
                  complete: bool, at: datetime = NOW, va_pct: int = VA_PCT) -> Profile:
    levels: dict[int, Level] = {}
    num = Decimal(0)
    for b in bars:
        bucket = int((b.start - bars[0].start.replace(hour=0, minute=0)) / timedelta(minutes=tpo_min)) \
            if kind == "Session" else int((b.start - bars[0].start) / timedelta(minutes=tpo_min))
        for t, (buy, sell) in per_tick(b).items():
            r = t // row_ticks
            lv = levels.setdefault(r, Level())
            v = buy + sell
            lv.vol += v
            num += Decimal(t) * v
            if b.approximated:
                lv.approx += v
            else:
                lv.buy += buy
                lv.sell += sell
                lv.tpo.add(bucket)
    pr = Profile(label, kind, bars[0].start, bars[-1].start + BAR, row_ticks, tpo_min, levels, complete,
                 num / sum(x.vol for x in levels.values()), last_price(at))
    top = pr.max_vol
    # `24`:1009: max volume; ties by closeness to the period VWAP, then to the last price, then the lower ticks
    mid = Decimal(row_ticks - 1) / 2
    pr.poc = min((r for r, x in levels.items() if x.vol == top),
                 key=lambda r: (abs(r * row_ticks + mid - pr.vwap_ticks), abs(r * row_ticks + mid - pr.last_ticks), r))
    lo = hi = pr.poc
    got, need = levels[pr.poc].vol, Decimal(pr.total) * va_pct / 100
    rmin, rmax = min(levels), max(levels)
    while got < need:  # `24` §4.5 step 2: absorb the larger neighbour; ties absorb both; an exhausted side yields
        up = pr.lv(hi + 1).vol if hi < rmax else None
        dn = pr.lv(lo - 1).vol if lo > rmin else None
        if up is not None and (dn is None or up >= dn):
            hi += 1
            got += up
        if dn is not None and (up is None or dn >= up):
            lo -= 1
            got += dn
    pr.va = (lo, hi)
    pr.va_pct = va_pct
    pr.hvn, pr.lvn = _nodes(pr)
    return pr


def _nodes(pr: Profile) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """`24` §5.2 HVN / LVN: a centred 3-level moving average; HVN = a strict local maximum with raw volume >= 0.5 of
    the POC's, peaks within 3 rows merged into the higher; LVN = a strict local minimum with raw volume <= 0.25 of the
    POC's (levels are sparse, `24`:992, so an untraded row is never a node). The POC row itself is not listed as an
    HVN (it carries its own mark)."""
    rs = pr.rows
    sm = {r: Decimal(sum(pr.lv(x).vol for x in (r - 1, r, r + 1))) / 3 for r in rs}
    pocv = pr.max_vol
    peaks = [r for r in rs[1:-1] if sm[r] > sm[r - 1] and sm[r] > sm[r + 1] and pr.lv(r).vol * 2 >= pocv]
    merged: list[int] = []
    for r in sorted(peaks, key=lambda r: (-sm[r], r)):
        if all(abs(r - m) > 3 for m in merged):
            merged.append(r)
    troughs = [r for r in rs[1:-1] if sm[r] < sm[r - 1] and sm[r] < sm[r + 1] and 0 < pr.lv(r).vol * 4 <= pocv]
    return tuple(sorted(r for r in merged if abs(r - pr.poc) > 3)), tuple(sorted(troughs))




# --- the panel's redlines: D03 §10.1 (PROPOSED there), parsed
_RED = _FLAT["d03"]
PANEL_W, GUTTER_W, IB_LANE, BRACKET_LANE = (int(re.search(rx, _RED).group(1)) for rx in (  # type: ignore[union-attr]
    r"Redlines \(PROPOSED\): panel (\d+) px", r"price gutter (\d+) px", r"IB lane (\d+) px", r"bracket lane (\d+) px"))
REDLINE_SRC = SL("Redlines (PROPOSED): panel", "d03")


# --- the world's views (every one derived from BARS)
def ts(t: datetime) -> str:
    """R-7's time form: YYYY-MM-DD HH:MM (the zone word follows from the copy: "… UTC")."""
    return f"{t:%Y-%m-%d %H:%M}"


def hm(t: datetime) -> str:
    return f"{t:%H:%M}"


SESSION = build_profile(f"Session {DAY0.day} {DAY0:%b}", "Session", bars_between(DAY0, NOW), complete=False)
CHART_FROM = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)  # kit choice: the bound chart shows 11:00 to the clock
CHART_SLOTS = 54  # 42 bars and 12 empty slots to the right of the forming bar
RANGE = (datetime(2026, 11, 2, 12, 30, tzinfo=UTC), datetime(2026, 11, 2, 13, 30, tzinfo=UTC))  # kit: board 04's range
DRAG_TO = datetime(2026, 11, 2, 13, 15, tzinfo=UTC)  # kit: the pointer's bar edge mid-drag (range-mode frames)
NUDGE = 3  # kit: board 09's Range start thumb moved three bars left with ← (pending, not committed)
_RECT = re.fullmatch(r"Rectangle (\d\d):(\d\d) → (\d\d):(\d\d)", DRAWING_NAME)
RECT = (DAY0.replace(hour=int(_RECT.group(1)), minute=int(_RECT.group(2))),  # type: ignore[union-attr]
        DAY0.replace(hour=int(_RECT.group(3)), minute=int(_RECT.group(4))))  # type: ignore[union-attr]
MOVE_BARS = 2  # kit: board 07's move shifts the rectangle two bars later
RECT_MOVED = (RECT[0] + MOVE_BARS * BAR, RECT[1] + MOVE_BARS * BAR)


def rect_prices(span: tuple[datetime, datetime]) -> tuple[int, int]:
    """A synthetic rectangle's price edges: the low and high of the bars it spans (kit choice, derived)."""
    bs = bars_between(*span)
    return min(b.l for b in bs), max(b.h for b in bs)


def drawing_label(span: tuple[datetime, datetime]) -> str:
    """E14's label form "type + anchor" (D02E14 L372: "Trendline 13:40 → 14:05"), here a rectangle's two times."""
    return f"Rectangle {hm(span[0])} → {hm(span[1])}"


def range_profile(span: tuple[datetime, datetime], kind: str = "Fixed range", **kw: Any) -> Profile:
    return build_profile(kind, kind, bars_between(*span), complete=span[1] <= NOW - BAR, **kw)


@dataclass(frozen=True)
class Preset:
    name: str
    period: str
    row_ticks: int
    va_pct: int
    vwap: bool
    nodes: bool
    builtin: bool = False


# the built-in's held values are the panel defaults (kit reading: D02 L302 names "Session value" without its values);
# the two user presets and their names are synthetic (kit choice; `22`:10802's 1–80 rule holds)
BUILTIN = Preset("Session value", "Session", ROW_TICKS, VA_PCT, False, True, True)
USER_PRESETS = (Preset("Scalp tight", "Session", 50, 68, True, True), Preset("Wide value", "Session", 200, 80, False,
                                                                             False))
MODIFIED_ROWS = 80  # kit: the held key changed after applying "Scalp tight" (row size 50 -> 80 ticks)
VIEW_AS_USER = "Sam"  # synthetic display name for {user} (no account identifier, R-1)
STALE_S = int(re.search(r"Stale (\d+)s", DECK["spec"]["W-39"][0][0]).group(1))  # type: ignore[union-attr]

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


def chunk(n: Node, budget: int = SECTION_RAW_BUDGET - 1200) -> Node:
    """Wrap the kids of a large non-flex board into full-size 'group NN' boards (x 0, y 0, the parent's w and h, no
    fill) of at most `budget` raw bytes each, so the packer emits one section per group instead of one per shape;
    positions are unchanged (the groups sit at the parent's origin). Flex boards are never regrouped."""
    if n["t"] != "board" or not n.get("kids"):
        return n
    kids = [chunk(c, budget) for c in n["kids"]]
    m = dict(n, kids=kids)
    if (n.get("o") or {}).get("dir") or len(json.dumps(m)) <= budget or len(kids) < 8:
        return m
    groups: list[list[Node]] = [[]]
    for c in kids:
        if groups[-1] and len(json.dumps(groups[-1] + [c])) > budget:
            groups.append([])
        groups[-1].append(c)
    if len(groups) == 1:
        return m
    m["kids"] = [{"t": "board", "name": f"group {i:02d}", "w": n["w"], "h": n["h"], "x": 0, "y": 0,
                  "kids": g} for i, g in enumerate(groups, 1)]
    return m


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
            if (x["t"] == "board" and re.search(r"/(header row|row ·[^/]*)/[^/]+$", p) and "padX" in (x.get("o") or {})
                    and (x["o"]["padX"] != INSET_SM)):
                bad.append(f"{p}: cell padX {x['o']['padX']} (8 px a side required)")
    return bad


def _scan_banned(obj: Any) -> list[str]:
    s = json.dumps(obj, ensure_ascii=False)
    return sorted({m.group(0) for m in BANNED.finditer(s)})



# --- the annotation column (ONE, 400 px, outside the frames) and the board
def data_statement() -> str:
    derive(f"world: {SYMBOL} {INTERVAL} bars from {DAY0:%Y-%m-%d %H:%M} UTC to the clock {ts(NOW)} UTC, one walk "
           f"seeded {SEED} (the issue number; drift redrawn every {LEG_BARS} bars), prices at the fixture's tick "
           f"{TICK}, sizes at its qty step {QTY_STEP}; row size {ROW_TICKS} ticks unless a preset says otherwise; "
           f"the rectangle's price edges are the low / high of the bars it spans")
    return (f"Data: synthetic only ({SL('data is a seeded synthetic BTCUSDT profile')}): {SYMBOL} {INTERVAL} bars "
            f"seeded {SEED}, {DAY0:%Y-%m-%d} 00:00 – {hm(NOW)} UTC; the drawing \"{DRAWING_NAME}\" is synthetic; tick "
            f"size {TICK} from the recorded instrument fixture; no account, key, balance or environment on any frame "
            f"(R-1, C-2.11: the flows are identical in DEMO and LIVE and nothing here reads one)")


def frame_block(fid: str, theme: str, lines: Iterable[str]) -> tuple[str, list[str]]:
    w, h = frame_size(fid)
    return f"{fid} · {theme}", [f"{w} × {h}"] + ([state_line(fid)] if fid in STATES else []) + [x for x in lines if x]


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    b = BOARDS[nn]
    head = [f"§0 L{b.line}: {b.cell}",
            f"Theme: dark" + (" with a light twin frame (token-bound; kit reading R-K1: the board is exported under "
                              "the dark set and again under the light set)" if b.twin else ""),
            f"Export: {b.export}" + (f"; the '-light' frame is read from {b.export_light} (R-K1)" if b.mixed else ""),
            f"BQ ruling: RULED (comment 6585044844 on the BQ list 6582998807), folded in the spec; the strings stay PROPOSED "
            f"(spec L{L('## The questions BQ-0')})",
            f"Not drawn — the text is binding (§0 L{NOT_DRAWN_LINE}): {', '.join(NOT_DRAWN)}", *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


ROW_MAX = 2 * WIN_W + MARGIN  # frames flow left to right in rows no wider than two windows


def layout(frames: list[Node]) -> list[Node]:
    """Frames left to right, wrapping at ROW_MAX; frames top-aligned in a row; 80 px gutters (the caption sits in the
    gutter above its frame)."""
    out, y, x, row_h = [], MARGIN, MARGIN, 0
    for f in frames:
        if x > MARGIN and x - MARGIN + f["w"] > ROW_MAX:
            x, y, row_h = MARGIN, y + row_h + MARGIN, 0
        out.append(dict(f, x=x, y=y))
        x += f["w"] + MARGIN
        row_h = max(row_h, f["h"])
    return out


# root heights as drawn: max(annotation end, footer end) + 80, read back on the live boards (live-check fold)
LIVE_ROOT_H = {1: 1878, 2: 1878, 3: 998, 4: 1878, 5: 998, 6: 998, 7: 2758, 8: 1398, 9: 998, 10: 1878}


def board(nn: int, frames: list[Node], ann: Node, *, strict: bool = True) -> tuple[dict[str, Any], list[Node]]:
    """The root (§0's name, grid x/y, color.surface.app, clip) hugging the frames + ONE annotation column + 80; a
    "state: <id>" caption 28 px above each frame; the data statement 24 px under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f) for f in b.frames]
    got = [f["name"] for f in frames]
    if strict and got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != §0 {want}")
    for f in frames:
        fid = f["name"].replace(SLASH, "/")
        if strict and (f["w"], f["h"]) != frame_size(fid):
            raise ValueError(f"board {nn:02d}: frame {fid} is {f['w']} x {f['h']}, the plan says {frame_size(fid)}")
    if "/" in b.name.split(f"{KEY} / {nn:02d} ", 1)[1]:
        raise ValueError(f"board {nn:02d}: '/' after the prefix in {b.name!r}")
    placed = layout(frames)
    caps = [text(f"caption {i:02d}", f"state: {f['name'].replace(SLASH, '/')} · "
                 f"{frame_theme(f['name'].replace(SLASH, '/'), b.theme)}", CAPTION, TEXT_3, x=f["x"], y=f["y"] - 28)
            for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · data statement", data_statement(), CAPTION, TEXT_2, x=MARGIN, y=bottom + 24,
                 w=right - MARGIN)]
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    est = int(math.ceil((max(bottom + 24 + 28, MARGIN + ah) + MARGIN) / 8) * 8)
    # live-check fold: the drawing lane measured max(annotation end, footer end) + 80 on every root (the estimate ran
    # 18 px over on all ten); the measured height is used, never below the footer end + 80
    h = LIVE_ROOT_H.get(nn, est) if strict else est
    foot_end = bottom + 24 + text_h(CAPTION)  # the data statement's one caption line
    if h < foot_end + MARGIN:
        raise ValueError(f"board {nn:02d}: root h {h} leaves less than {MARGIN} px under the footer (ends {foot_end})")
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch: trim the annotations")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root (h {h}, "
         f"the drawn max(annotation end, footer end) + {MARGIN}); raise the root's h to that rule if not")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
    return ({"name": b.name, "w": wd, "h": h, "x": x, "y": y, "o": {"fill": APP, "clip": True}},
            [*placed, *caps, *foot, a])


def validate(path: Path) -> tuple[int, str]:
    res = subprocess.run([sys.executable, "-X", "utf8", "-I", str(VALIDATOR), str(path), "--components", str(COMPONENTS),
                          "--tokens", str(TOKENS_FILE)], capture_output=True, text=True, encoding="utf-8",
                         timeout=180, check=False)
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
    live(f"export {b.export} under the dark set; record the board id and the PNG size")
    if b.mixed:
        live(f"kit reading R-K1: export board {nn:02d} a second time under the light set as {b.export_light}; read "
             f"back one bound fill (color.surface.raised) as the light value; its '-light' frame is read from that "
             f"export, its '-dark' frames from {b.export}")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {DOCS['spec'][0].rsplit('/', 1)[1]} md5 {DOCS['spec'][1][:8]} in this checkout "
                         f"(§0 L{b.line}; BQ ruling RULED, comment 6585044844)")
    for d, why in (("d03", "PR #5517 head; re-pinned when it merges"), ("d02", "merge commit of PR #5487")):
        NOTES.add("sources", f"{DOC_LABEL[d]} {DOCS[d][0].rsplit('/', 1)[1]} md5 {DOCS[d][1][:8]} at {DOCS[d][2]} "
                             f"(read via {_SOURCE_NOTE[d]}; {why})")
    for d in ("d02e14", "d07e14", "d02e17"):
        NOTES.add("sources", f"{DOC_LABEL[d]} {DOCS[d][0].rsplit('/', 1)[1]} md5 {DOCS[d][1][:8]} at the base {BASE}")
    NOTES.add("sources", f"{DOCS['fixture'][0]} md5 {DOCS['fixture'][1][:8]} (tick size and qty step only)")
    NOTES.add("sources", "tokens: token-sync.json only (§11: shipped names, nothing new)")
    sheet = {"board": root, "sections": sections_for([chunk(n) for n in nodes]), "export": b.export,
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
           summary or f"Board {nn:02d} of ten (§0 L{b.line}: {b.cell}). Grid ({x}, {y}); {sh['board']['w']} x "
                      f"{sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".", "", "## Frames", ""]
    out += [f"- `{frame_name(f)}` ({frame_theme(f, b.theme)}, {frame_size(f)[0]} x {frame_size(f)[1]})"
            for f in b.frames]
    out += ["", "## Validator and size", "", f"- `{msg.splitlines()[-1] if msg else ''}` (exit {rc})",
            f"- {len(sh['sections'])} sections, {len(json.dumps(sh))} bytes", ""]
    for kd in ("live_checks", "readings", "derivations", "spec_gaps", "deviations", "copy_keys", "copy_gaps",
               "fallbacks", "sources", "tokens"):
        lines = sh["notes"].get(kd) or []
        out += [f"## {kd.replace('_', ' ').capitalize()} ({len(lines)})", ""] + [f"- {ln}" for ln in lines] + [""]
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    m = BANNED.search(s)
    if m:
        raise RuntimeError(f"md for board {nn:02d}: banned string {m.group(0)!r}")
    p = sp.parent / (sp.stem + ".md")
    p.write_text(s, encoding="utf-8")
    if IN_REPO and sp.parent == CAP_DIR.resolve():  # the committed sidecar beside the kit, the same bytes
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
    res = subprocess.run([sys.executable, "-X", "utf8", "-I", str(PACKER), str(src), str(dst)], capture_output=True, text=True,
                         encoding="utf-8", timeout=300, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"packer exit {res.returncode}: {(res.stdout + res.stderr).strip()[-600:]}")
    raw = dst.read_text(encoding="utf-8")
    pf = (json.loads(raw).get("compactOf") or {}).get("file")
    if not pf or not Path(pf).is_absolute() or Path(pf) != src:
        raise RuntimeError(f"{dst.name}: compactOf.file {pf!r} is not the absolute source path")
    n_sec = len(json.loads(raw)["sections"])  # mkcall4 reads the pack source, so count before the name is made bare
    cnt = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(MKCALL), str(dst), "count"], capture_output=True, text=True,
                         encoding="utf-8", timeout=120, check=False)
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
# --- tables (the E08-D10 kit's, copied): cells padded 8 px a side
ROW_H = 24  # compact rows (§12.1)


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


def rows_block(rows: list[Node], name: str = "rows") -> Node:
    return vbox(name, rows, None, w=rows[0]["w"], h=round(sum(est_height(r) for r in rows)))




# --- self-test: python3 -I -B e19d04kit.py selftest
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), f"pinned md5s ({len(DOCS)} sources; D02 via {_SOURCE_NOTE['d02']}, D03 via "
                                       f"{_SOURCE_NOTE['d03']})")
    check(sorted(BOARDS) == list(range(1, 11)), "§0: ten boards 01-10")
    twins = [b.nn for b in BOARDS.values() if b.twin]
    check(twins == [1, 4, 8] and len(twins) * 3 <= len(BOARDS), f"light twins {twins} <= one third")
    check([len(BOARDS[n].frames) for n in range(1, 11)] == [4, 4, 2, 3, 2, 2, 5, 2, 2, 3], "frames per board (§0)")
    drawn = [f for b in BOARDS.values() for f in b.frames]
    check(all(f not in NOT_DRAWN for f in drawn) and len(NOT_DRAWN) == 7, f"no drawn frame is on §0's not-drawn line "
          f"({len(NOT_DRAWN)} not drawn)")
    rows8 = {f: s[5] for f, s in STATES.items()}
    check(all(rows8[f] == f"{n:02d}" for n, b in BOARDS.items() for f in b.frames)
          and all(rows8[f] == "not drawn" for f in NOT_DRAWN) and len(STATES) == len(drawn) + len(NOT_DRAWN),
          "§8 states <-> §0 boards reconcile (every drawn frame on its board, the not-drawn rows 'not drawn')")
    check((FILE_NAME, PAGE) == ("E19-D04 boards", "E19-D04") and (WIN_W, WIN_H) == (1280, 800),
          f"file {FILE_NAME!r}, page {PAGE!r}, windows {WIN_W} x {WIN_H}")
    check(all("/" not in b.name.split(f"{KEY} / {b.nn:02d} ", 1)[1] for b in BOARDS.values()), "no '/' after the prefix")
    check(str(TICK) == "0.10" and str(QTY_STEP) == "0.001", f"fixture tick {TICK}, qty step {QTY_STEP}")
    check(len(DECK["spec"]) == 42 and DECK["spec"]["W-13"][0][1:] == ["Overwrite", "Rename"],
          "copy deck: W-1 … W-42 parsed, the quoted strings of a cell in order")
    check(drawing_label(RECT) == DRAWING_NAME and all(b.start.minute % 5 == 0 for b in BARS),
          f"the drawing {DRAWING_NAME!r} sits on the world's {INTERVAL} bar edges")
    check(SESSION.rows and RANGE[0] < DRAG_TO < RANGE[1] and RECT[1] <= NOW and RECT_MOVED[1] <= NOW,
          "the kit's range, drag and rectangle times lie inside the world")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for kk, v in globals().items() if kk.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border|opacity|elevation)\.", v)]
    check(all(u in toks for u in used if u not in NEVER), "kit tokens exist in token-sync.json")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: S("a string no source says"),
                 lambda: text("x", "y", CAPTION, "color.text.disabled")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError, LookupError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/', an unworded string and a NEVER token refused")
    sys.path.insert(0, str(KIT_DIR / "gen"))
    import registry  # noqa: PLC0415  (the frame builders import this kit)
    check(set(registry.BUILDERS) == set(drawn), "a builder for every frame")
    NOTES.reset()
    fid = "SCR-038/preset-menu-dark"
    node_, lines = registry.BUILDERS[fid]("dark")
    ann = annotations(1, [frame_block(fid, "dark", lines)], board_lines=["Self-test sheet: one frame"])
    path = write_sheet(1, [node_], ann, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False,
                       notes={"live_checks": ["self-test sheet: not for rendering"]})
    check(path.exists(), f"validator exit 0: {path.name}")
    md = write_md(1, path, summary="Self-test sheet (one frame); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    check(l3 == md_line3(1) and l3.endswith("theme dark."), f"md line 3: {l3}")
    packed = pack_sheet(path, SELFTEST_DIR)
    sh = json.loads(packed.read_text(encoding="utf-8"))
    check(sh["compactOf"]["file"] == path.name, f"packed: bare source name, sha256 ok, {len(sh['sections'])} "
          "sections, mkcall4 count agrees")
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
    raise SystemExit(2)
