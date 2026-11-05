"""E20-D02 (#574) wireframe board kit: the spec's §0 ten greyscale boards (the CMP-225 Deep Stats strip under SCR-030
in every state, the narrow-bar collapse and readout, the breach in greyscale, forming / partial / empty, the hidden
strip and its restore, SCR-033's catalogue, reorder, thresholds and validation, the SCR-045 delta and the chunked
export, the alignment study) as cvsheet JSON sheets for the Penpot file "E20-D02 boards", page "E20-D02" (PR 2 of the
ticket, the boards PR; the ruling of record is folded into the text, BQ-0 ... BQ-9).

Offline only. Spec (binding; every string comes from it): docs/design/E20/E20-D02.md, read by repo-relative path from a
checkout and md5-pinned in DOCS with the planning floor's source (E18-D02:124) and the recorded instrument fixture (tick
and qty step); the kit refuses drifted bytes: re-read, re-check, re-pin. Every other value is the seeded synthetic 1m
series (seed 574, the world below), and every drawn value, time, count and axis label is derived from it.

Checkout: the kit sits at docs/design/_tools/sheets/e20-d02/ in a checkout (REPO = four levels up), or anywhere with
CV_CHECKOUT naming the checkout. Raw sheets + .md go to CAP_DIR, packed sheets to V4_DIR (build-notes.md).
Pipeline: gen/gen_NN.py builds its frames with gen/ui.py and calls ui.run -> build(): raw sheet (validator exit 0),
.md (line 3 = the render line), packed sheet. Self-test: python3 -X utf8 -I -B e20d02kit.py selftest

WIREFRAMES (§0, R32): greyscale only: node() refuses any colour token outside GREY. Penpot lessons kept as hard checks:
no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every flex child without text carries an explicit
h; no "/" in a node name (U+2215 stands for it); no backtick in drawn text (text() strips it, check_all fails on one);
no local path, host or agent name anywhere (BANNED); table cells carry 8 px padding a side; every frame has a caption;
color.text.disabled and opacity.disabled are never bound (E09-D09 §2.1); every file is written with LF line ends;
every Python child runs with -X utf8.
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
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KEY, EPIC, ISSUE = "E20-D02", "E20", 574
KIT_DIR = Path(__file__).resolve().parent
_SPEC_PATH = "docs/design/E20/E20-D02.md"
PY = [sys.executable, "-X", "utf8", "-I", "-B"]  # every Python child: UTF-8 mode, isolated, no bytecode


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / _SPEC_PATH).is_file() and KIT_DIR.is_relative_to(up / "docs"):
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / _SPEC_PATH).is_file():
        raise SystemExit("e20d02kit: run inside a checkout or set CV_CHECKOUT to one")
    return Path(env).resolve()


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
HEAD = "the boards PR"  # the spec as built (§0 drawn, §19); re-pin DOCS when a further text fold lands
DOCS = {  # key -> (repo-relative path, md5 at HEAD): every read is md5-checked
    "spec": (_SPEC_PATH, "558c4ba6afdb5eafb65d4ac6b2e922df"),
    "floor": ("docs/design/E18/E18-D02.md", "c18b4d41a6d91836a193cf5991a3adbf"),
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
    raise SystemExit(f"e20d02kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
LINES = {k: _COMMENT.sub("", _doc_bytes(k).decode("utf-8")).split("\n") for k in DOCS if k != "fixture"}


def write_lf(p: Path, s: str) -> None:
    """Every kit output is UTF-8 with LF line ends, whatever the platform."""
    p.write_text(s, encoding="utf-8", newline="\n")


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


# --- registries parsed from the spec: §0 boards (and their frames), §2 states, §12 copy, the row tables, §9 sources
S0 = L("## 0. Status and the boards")
_S0_TEXT = LINES["spec"][S0 + 1]
FILE_NAME = re.search(r"Penpot file `([^`]+)`", _S0_TEXT).group(1)  # type: ignore[union-attr]
PAGE = re.search(r"page `([^`]+)`", _S0_TEXT).group(1)  # type: ignore[union-attr]
EXPORT_DIR = re.search(r"Exports go to `([^`]+)/" + re.escape(KEY) + r"-NN-<slug>\.png`",  # type: ignore[union-attr]
                       _S0_TEXT).group(1)
_FRAME_WH = re.search(r"desktop, (\d+) × (\d+) windows", _S0_TEXT)
WIN_W, WIN_H = int(_FRAME_WH.group(1)), int(_FRAME_WH.group(2))  # type: ignore[union-attr]
TWIN_CAP = re.search(r"(\d+) boards, (\d+) light twins", _S0_TEXT)
GREYSCALE_WORDS = re.search(r"(Greyscale, desktop, \d+ × \d+ windows)", _S0_TEXT).group(1)  # type: ignore


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E20-D02 / 01 strip-default-allrows"
    slug: str
    line: int  # §0 line
    frames: tuple[str, ...]

    @property
    def theme(self) -> str:
        return "dark"  # §0: 0 light twins; the T2 and greyscale grammar is token-bound, so it holds in every theme

    @property
    def twin(self) -> bool:
        return False

    @property
    def export(self) -> str:
        return f"{EXPORT_DIR}/{KEY}-{self.nn:02d}-{self.slug}.png"

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"


def _boards() -> dict[int, Board]:
    out = {}
    for i, c in table("## 0. Status and the boards"):
        nn, name = int(c[0]), plain(c[1])
        drawn = plain(c[3]).startswith("drawn: board id ") and f"/{KEY}-{nn:02d}-" in c[3]  # §0 as built
        if (plain(c[3]) != "PENDING" and not drawn) or not name.startswith(f"{KEY} / {nn:02d} "):
            raise ValueError(f"§0 L{i}: {c!r}")
        out[nn] = Board(nn, name, name.split(f"{KEY} / {nn:02d} ", 1)[1], i, tuple(re.findall(r"`([^`]+)`", c[2])))
    return out


BOARDS = _boards()
ALL_FRAMES = tuple(f for b in BOARDS.values() for f in b.frames)


def safe(s: str) -> str:
    """A node name built from a label: "/" becomes U+2215 (Penpot splits names on "/")."""
    return s.replace("/", SLASH)


def frame_name(fid: str) -> str:
    return fid.replace("/", SLASH)


def board_of(fid: str) -> int:
    return next(n for n, b in BOARDS.items() if fid in b.frames)


def _states() -> dict[str, tuple[str, int, str, int]]:
    """§2's register: frame id -> (state, board, specified-in, line); "`-dense`" style suffixes expand on the first."""
    out = {}
    for i, c in table("## 2. State register"):
        ids = re.findall(r"`([^`]+)`", c[1])
        base = ids[0]
        for f in ids:
            fid = base.rsplit("-", 1)[0] + f if f.startswith("-") else f
            out[fid] = (plain(c[0]), int(c[2]), plain(c[3]), i)
    return out


STATES = _states()
COPY = {plain(c[0]): (c, i) for i, c in table("## 12. Copy deck")}  # W-n -> (cells, line): W, Where, Copy, Source


def _row_table(head: str) -> list[dict[str, Any]]:
    """A row table: label (`24` §7), metric(s), unit or short label, with its line."""
    out = []
    for i, c in table(head):
        out.append({"label": plain(c[1]), "metric": plain(c[2]), "x": plain(c[3]), "line": i})
    return out


DEFAULT_ROWS = _row_table("### 3.2 Default")  # x = unit
ALL_ROWS = _row_table("### 3.3 AllRows")  # x = unit
COMPACT_ROWS = _row_table("### 3.4 CompactMode")  # x = short label (PROPOSED)
CATALOGUE = _row_table("### 6.1 Layout and the catalogue")  # x = unit; `24` §7 order
SOURCES = {plain(c[0]): (plain(c[1]), plain(c[2]), plain(c[3]), i) for i, c in table("## 9. Data sources per row")}
BREACH_ROWS = table("### 3.6 ThresholdsBreached")  # Row, Bar, State, Shade, Glyph, Word, Accessible text
OTHER_8 = tuple(x.strip() for x in re.search(r"enable-able in SCR-033: ([^.]+)\.",  # type: ignore[union-attr]
                                             LINES["spec"][L("### 3.3 AllRows") + 1]).group(1).split(","))
UNIT = {r["label"]: r["x"] for r in CATALOGUE}
FLOOR_LINE = 124  # E18-D02:124, the planning floors the spec seeds E20-K01's collapse floor from (§4.1)
_FL = re.search(r"width floors (\d+) / (\d+) / (\d+) / (\d+) px \(`bid_ask` / `delta`", LINES["floor"][FLOOR_LINE - 1])
FLOOR_PX = int(_FL.group(2))  # type: ignore[union-attr]  # the `delta` floor: the kit's seed for the collapse


def W(wid: str, i: int = 0, **fills: Any) -> str:
    """The i-th quoted string of copy-deck row wid (§12), verbatim, with its {slot}s filled; raises on an unfilled or
    unknown slot."""
    c, ln = COPY[wid]
    qs = re.findall(r'"([^"]+)"', c[2])
    s = qs[i]
    for k_, v in fills.items():
        if "{" + k_ + "}" not in s and "<" + k_ + ">" not in s:
            raise KeyError(f"{wid}: no slot {{{k_}}} in {s!r}")
        s = s.replace("{" + k_ + "}", str(v)).replace("<" + k_ + ">", str(v))
    if re.search(r"\{[a-zA-Z]+\}|<ts>", s):
        raise KeyError(f"{wid}: unfilled slot in {s!r}")
    NOTES.add("copy_keys", f"{wid} (§12 L{ln}, {plain(c[3])}): \"{s}\"")
    return s


def S(chars: str, start: int = 1) -> str:
    """A spec string verbatim (markdown code ticks and bold removed before the match; raises if absent)."""
    for i in range(start - 1, len(LINES["spec"])):
        if chars in plain(LINES["spec"][i]):
            NOTES.add("copy_keys", f"spec L{i + 1}: \"{chars}\"")
            return chars
    raise LookupError(f"spec: not found: {chars!r}")


def state_line(fid: str) -> str:
    st, bd, spec_in, ln = STATES[fid]
    return f"§2 L{ln}: {st} — specified in {spec_in} (board {bd:02d})"


def source_line(label: str) -> str:
    live_, boot, hist, ln = SOURCES[label]
    return f"§9 L{ln} {label}: live {live_}; bootstrap {boot}; history {hist}"


# --- tokens: WIREFRAME GREYSCALE (§0). Only these colour tokens may be bound (node() refuses any other colour token).
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
BORDER_SUBTLE, BORDER, BORDER_STRONG = "color.border.subtle", "color.border.default", "color.border.strong"
NEUTRAL, NEUTRAL_SUBTLE = "color.neutral.default", "color.neutral.subtle"
GRID, AXIS = "color.grid.line", "color.axis.text"
GREY = frozenset((APP, CANVAS, RAISED, SUNKEN, HOVER, SELECTED, OVERLAY, TEXT_1, TEXT_2, TEXT_3, BORDER_SUBTLE, BORDER,
                  BORDER_STRONG, NEUTRAL, NEUTRAL_SUBTLE, GRID, AXIS))
PLACEHOLDER = NEUTRAL  # placeholder grey: distinct from the T2 label's grey (TEXT_3), §1.4
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD = "type.ui.heading-sm", "type.ui.heading-md"
NUM_XS, NUM_SM, NUM = "type.num.xs", "type.num.sm", "type.num.base"
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
BUTTON_PADX, DIALOG_PAD = "space.button.paddingX", "space.dialog.padding"
ICON_SM, ICON = "size.icon.sm", "size.icon"
R_CONTROL, R_CARD, R_DIALOG, R_BADGE = "radius.control", "radius.card", "radius.dialog", "radius.badge"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
SCRIM = "opacity.scrim"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, BUTTON_PADX: 12, DIALOG_PAD: 24, ICON_SM: 12, ICON: 16}
NEVER = ("color.text.disabled", "opacity.disabled")  # E09-D09 §2.1: never on a T2 label, glyph or reason, nor anywhere
TOKEN_NAMES = frozenset(r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8")))

FALLBACKS = {
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock, the chevrons, the flag",
    "focus": "wireframe: the focus ring (E47-D04's, §6.3) is drawn as a 2 px color.text.primary outline (border.focus) "
             "outside the row or control, not color.focus.ring (a hue); E20-D03 binds the ring token in hi-fi",
    "marker": "kit choice: board markers (announcements, accessible names, x(t) edges, notes) are drawn in a 1 px "
              "color.border.strong outline on color.surface.canvas, named 'board marker · …' — not product UI",
    "shade": "wireframe: the breach shade (hi-fi E20-D03) is drawn as a color.surface.selected cell fill named "
             "'shade slot (hi-fi E20-D03)'; the greyscale frame removes it",
    "breach-slot": "wireframe: the breach-glyph slot is an 8 × 8 outlined square (color.text.primary hairline) — a "
                   "shape distinct from both sign glyphs ▲ / ▼; its form is E20-D03's",
    "flag": "kit choice: Delta Divergence's flag is drawn with the local 'warning' glyph at size.icon.sm (the flag's "
            "form is E20-D03's); a false value leaves the glyph slot empty, its accessible text 'no divergence'",
    "sparkline": "kit choice: CMP-024 sparklines are drawn as N dots (2 × 2 rects) on a 48 × 16 slot (no polyline "
                 "node in the sheet schema); the dots are the row's last N values, scaled to their own min and max",
    "runs": "kit choice: below an 8 px pitch adjacent same-glyph collapsed cells are pixel-contiguous, so each run is "
            "drawn as one rect (pixel-equivalent); at 8 px and over every cell is its own glyph",
    "candles": "kit choice: candles are wireframe greys — body color.text.secondary (up bars outlined, down bars "
               "filled) and a 1 px wick; below a 4 px pitch the bar is its high-low rect only",
    "menu": "kit choice: menus, the readout and the dialog are color.surface.overlay cards with a 1 px "
            "color.border.default outline",
    "scrim": "the dialog's scrim is color.surface.overlay at opacity.scrim (validator WARN: a Tier-1 primitive) over "
             "the inert SCR-030 behind it",
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
        line = line.replace("`", "")
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
    NOTES.add("copy_gaps", f"\"{chars}\": kit label, not {KEY} copy{' — ' + why if why else ''}")
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
    n: Node = {"t": t, "name": name.replace("`", "")}
    n.update({k: v for k, v in kw.items() if v is not None})
    if isinstance(n.get("note"), str):
        n["note"] = n["note"].replace("`", "")
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
                raise ValueError(f"{name!r}: {tk} is never bound on these boards (E09-D09 §2.1)")
            if re.match(r"^(color|type|space|size|radius|border|opacity)\.", tk) and tk not in TOKEN_NAMES:
                raise ValueError(f"{name!r}: {tk} is not a shipped token (token-sync.json)")
            if tk.startswith("color.") and tk not in GREY:
                raise ValueError(f"{name!r}: {tk} is a hue; wireframes are greyscale (§0)")
            NOTES.add("tokens", tk)
    return n


def text(name: str, chars: str, typo: str = BODY, color: str = TEXT_1, **kw: Any) -> Node:
    """A text node; markdown backticks never reach a drawn string (they are stripped here; check_all re-scans)."""
    s = str(chars).replace("`", "")
    if not s.strip():
        raise ValueError(f"text {name!r} is empty")
    return node("text", name, chars=s, typo=typo, color=color, **kw)


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


def bands(prefix: str, nodes: list[Node], w: float, h: float, budget: int = 8200) -> list[Node]:
    """Many positioned siblings regrouped into overlaid non-flex bands (each band the parent's full size, its children
    keeping their coordinates), each band filled up to `budget` bytes of JSON, so the sheet packs into few sections
    (a section holds one node). A list that fits one band stays as it is."""
    if len(json.dumps(nodes)) <= budget:
        return nodes
    groups: list[list[Node]] = [[]]
    for n in nodes:
        if groups[-1] and len(json.dumps([*groups[-1], n])) > budget:
            groups.append([])
        groups[-1].append(n)
    return [box(f"{prefix} · band {i + 1:02d}", g, {}, w=w, h=h, x=0, y=0) for i, g in enumerate(groups)]


def walk(n: Node, path: str = "") -> Iterable[tuple[str, Node]]:
    p = f"{path}/{n['name']}" if path else n["name"]
    yield p, n
    for k in n.get("kids") or []:
        yield from walk(k, p)


# --- text metrics (estimates; Inter / JetBrains Mono) and the measured-height table
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
    return float(math.ceil(size * lh * lines))  # measured, not nominal: a text box paints at ceil(size x lh x lines)


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


# The live roots' heights, measured by the drawing lane after touchTexts + relayout (the checked want: max(annotation
# column end, footer end) + MARGIN), folded from the live check of the ten drawn boards. The root takes the measured
# value (it must still clear the frames and the footer); the estimate below serves only a board not yet measured.
# Board 08 gained SCR-033/apply-no-write in the design-read fold (#5782): estimated until the redraw re-measures it.
MEASURED_H: dict[int, int] = {1: 1934, 2: 1026, 3: 1026, 4: 1947, 5: 1934, 6: 1026, 7: 1934, 8: 2842, 9: 1934, 10: 1934}
ANN_SLACK = 1.15  # the estimate's slack on the annotation column until MEASURED_H holds the board


# --- the seeded synthetic world (seed 574): one 1m series per symbol; every drawn value is derived from it
SEED = ISSUE
D = Decimal
MINUS = "−"


def _fixture() -> dict[str, tuple[Decimal, Decimal]]:
    rows = json.loads(_doc_bytes("fixture").decode("utf-8"))
    out = {}
    for r in rows["result"]["list"]:
        if r.get("symbol") in ("BTCUSDT", "ETHUSDT"):
            out[r["symbol"]] = (D(r["priceFilter"]["tickSize"]), D(r["lotSizeFilter"]["qtyStep"]))
    return out


INSTR = _fixture()
SYM = S("BTCUSDT")
SYM2 = S("ETHUSDT")  # W-2's per-symbol set names it: the symbol-set frame charts a second synthetic series
COIN = {SYM: "BTC", SYM2: "ETH"}
N_BARS = 800  # bars generated a series (the alignment study's ~800, §8); the last bar is the forming one
LAST = (14, 5)  # the forming bar's minute, UTC (kit choice); every visible window ends on it


def hm_(i: int, n: int = N_BARS) -> str:
    """The bar time of index i (0 .. n-1), the last index being LAST."""
    m = LAST[0] * 60 + LAST[1] - (n - 1 - i)
    return f"{m // 60:02d}:{m % 60:02d}"


def idx(t: str) -> int:
    h, m = (int(x) for x in t.split(":"))
    return N_BARS - 1 - ((LAST[0] * 60 + LAST[1]) - (h * 60 + m))


def _breach_plants() -> dict[str, dict[str, Decimal]]:
    """§3.6's table: bar -> {row label: value} (the drawn values the table writes, as numbers)."""
    out: dict[str, dict[str, Decimal]] = {}
    for _i, c in BREACH_ROWS:
        acc = unquote(c[6])
        m = re.match(r"(.+?) ([+−-][\d,.]+)", acc)
        out.setdefault(plain(c[1]), {})[plain(c[0])] = D(m.group(2).replace("−", "-").replace(",", ""))  # type: ignore
    return out


PLANTS = _breach_plants()
PCT_BOUND = D(re.search(r"The (\d+) % bound is the story's seed", LINES["spec"][L("The 60 % bound") - 1]).group(1))  # type: ignore
DELTA_BOUND = D(re.search(r"the (\d+) BTC bound is a board placeholder", LINES["spec"][L("The 60 % bound") - 1]).group(1))  # type: ignore
SPARK_N = int(re.search(r"default (\d+),", LINES["spec"][L("### 3.5 WithSparklines") + 1]).group(1))  # type: ignore
GUARD_MAX = int(re.search(r"with more than (\d+) rows' sparklines", LINES["spec"][L("### 3.5 WithSparklines") + 1]).group(1))  # type: ignore
GUARD_DRAW = int(re.search(r"falls back to the (\d+) most recently enabled", LINES["spec"][L("### 3.5 WithSparklines") + 1]).group(1))  # type: ignore
CEILING = int(re.search(r"AllRows draws (\d+) rows", LINES["spec"][L("### 3.3 AllRows") + 1]).group(1))  # type: ignore
FORMING_V, FORMING_PCT = D("120.000"), D("57")  # kit: the forming bar so far, its Delta % near the 60 % bound (§3.7)
EXPORT_JOB = int(re.search(r"A range over ([\d ]+) bars runs as a job", LINES["spec"][L("### 7.2 Progress")+1]).group(1).replace(" ", ""))  # type: ignore
VIEW_AS_USER = "Manager 01"  # synthetic {user} for W-17


@dataclass(frozen=True)
class Bar:
    i: int
    t: str
    o: Decimal
    h: Decimal
    l: Decimal  # noqa: E741
    c: Decimal
    buy: Decimal
    sell: Decimal
    trades: int
    mx: Decimal  # intrabar max delta
    mn: Decimal  # intrabar min delta
    cvd: Decimal
    forming: bool

    @property
    def vol(self) -> Decimal:
        return self.buy + self.sell

    @property
    def delta(self) -> Decimal:
        return self.buy - self.sell

    @property
    def pct(self) -> Decimal:
        return self.delta / self.vol * 100


def _q(v: float | Decimal, step: Decimal) -> Decimal:
    return (D(str(v)) / step).quantize(D(1), ROUND_HALF_EVEN) * step


def _series(sym: str, seed: int, p0: Decimal, v_mid: float, pct_max: float, plants: dict[str, tuple[Decimal, Decimal]],
            forming: tuple[Decimal, Decimal]) -> tuple[Bar, ...]:
    """N_BARS one-minute bars ending on LAST (the last one forming). Volume lognormal around v_mid, Delta % uniform in
    ±pct_max (so no unplanted bar breaches a bound), plants: bar time -> (volume, Delta %); price drifts with the delta
    plus noise (so divergences occur), trades from a seeded average size."""
    tick, step = INSTR[sym]
    rng = random.Random(seed)
    out, cvd, px = [], D(0), p0
    for i in range(N_BARS):
        t = hm_(i)
        is_f = i == N_BARS - 1
        if is_f:
            v, pct = forming
        elif t in plants:
            v, pct = plants[t]
        else:
            v = _q(min(max(math.exp(rng.gauss(math.log(v_mid), 0.25)), v_mid * 0.5), v_mid * 1.6), step)
            pct = D(str(round(rng.uniform(-pct_max, pct_max), 1)))
        delta = _q(v * pct / 100, step)
        buy = _q((v + delta) / 2, step)
        sell = buy - delta
        avg = min(max(rng.gauss(0.12, 0.02), 0.07), 0.2)
        trades = max(1, round(float(buy + sell) / avg))
        drift = float(delta) * float(p0) / 64000 * 0.06 + rng.gauss(0, float(p0) / 64000 * 14)
        o = px
        c = _q(o + D(str(drift)), tick)
        h = _q(max(o, c) + D(str(abs(rng.gauss(0, float(p0) / 64000 * 9)))), tick)
        lo = _q(min(o, c) - D(str(abs(rng.gauss(0, float(p0) / 64000 * 9)))), tick)
        mx = max(delta, D(0)) + _q((buy + sell) * D(str(round(rng.uniform(0.02, 0.12), 3))), step)
        mn = min(delta, D(0)) - _q((buy + sell) * D(str(round(rng.uniform(0.02, 0.12), 3))), step)
        cvd += delta
        out.append(Bar(i, t, o, h, lo, c, buy, sell, trades, mx, mn, cvd, is_f))
        px = c
    return tuple(out)


def _plants_btc() -> dict[str, tuple[Decimal, Decimal]]:
    """§3.6's three breached cells and its neutral one, as (volume, Delta %) per bar: 13:58 carries Delta % and Delta
    together (volume = Delta / Delta %); the others take a kit volume under the Delta bound."""
    out = {}
    for t, rows in PLANTS.items():
        pct = rows["Delta %"]
        v = (rows["Delta"] * 100 / pct) if "Delta" in rows else D(250 if pct < 0 else 300)
        out[t] = (_q(v, INSTR[SYM][1]), pct)
    return out


BARS = {SYM: _series(SYM, SEED, D("64000.0"), 300.0, 45.0, _plants_btc(), (FORMING_V, FORMING_PCT)),
        SYM2: _series(SYM2, SEED + 1, D("3200.00"), 4200.0, 62.0, {}, (D("1500.000"), D("21")))}
SET2_PCT = D(50)  # kit example: the ETHUSDT set's Delta % bound (labelled "example" on the frame; MEMO OQ-3)


def window(n: int, sym: str = SYM) -> tuple[Bar, ...]:
    """The n visible bars ending on the forming bar."""
    return BARS[sym][-n:]


# --- row values: the cell (row's format), the full value (readout / accessible text), the side, the glyph
SIGNED = frozenset(("Delta", "Delta %", "Cumulative Delta", "Max Delta", "Min Delta", "CumΔ Change"))
FLAG = frozenset(("Delta Divergence",))


def _int(v: Decimal, signed: bool) -> str:
    s = f"{abs(v).quantize(D(1), ROUND_HALF_EVEN):,.0f}"
    return (("+" if v > 0 else MINUS if v < 0 else "") + s) if signed else s


def raw_value(label: str, b: Bar) -> Decimal | bool:
    return {"Delta": lambda: b.delta, "Delta %": lambda: b.pct, "Total Volume": lambda: b.vol,
            "# Trades": lambda: D(b.trades), "Cumulative Delta": lambda: b.cvd, "Max Delta": lambda: b.mx,
            "Min Delta": lambda: b.mn, "Ask Volume": lambda: b.buy, "Bid Volume": lambda: b.sell,
            "Delta Divergence": lambda: (b.c > b.o and b.delta < 0) or (b.c < b.o and b.delta > 0),
            "Avg Trade Size": lambda: b.vol / b.trades, "Volume Imbalance": lambda: b.buy / b.sell,
            "Speed": lambda: D(b.trades) / 60}[label]()


def value(label: str, b: Bar) -> str:
    """The value as the cell and the readout show it (the row's default format: whole units for qty and count rows,
    whole percent, 3 dp for the average trade size, 2 dp for the ratio, 1 dp for Speed)."""
    v = raw_value(label, b)
    if isinstance(v, bool):
        return "yes" if v else "no"
    if label == "Delta %":
        return _int(v, True) + " %"
    if label == "Avg Trade Size":
        return f"{v.quantize(D('0.001'), ROUND_HALF_EVEN)}"
    if label == "Volume Imbalance":
        return f"{v.quantize(D('0.01'), ROUND_HALF_EVEN)}"
    if label == "Speed":
        return f"{v.quantize(D('0.1'), ROUND_HALF_EVEN)}"
    return _int(v, label in SIGNED)


def unit_word(label: str, sym: str = SYM) -> str:
    """The readout's unit (kit mapping of §6.1's Unit: qty -> the base coin, pct -> %, count / ratio / bool -> none)."""
    return {"qty": COIN[sym]}.get(UNIT[label], "")


def side(label: str, b: Bar) -> str | None:
    if label not in SIGNED:
        return None
    v = raw_value(label, b)
    return "buy" if v > 0 else "sell" if v < 0 else None  # type: ignore[operator]


def glyph(label: str, b: Bar) -> str:
    """§4.1's row-class glyph: ▲ / ▼ for a signed row, the presence mark for an unsigned row, the flag (drawn as an
    icon) for a true Delta Divergence, '' for a false one."""
    if label in FLAG:
        return "flag" if raw_value(label, b) else ""
    if label in SIGNED:
        return {"buy": "▲", "sell": "▼", None: "·"}[side(label, b)]
    return "·"


def breached(label: str, b: Bar, sym: str = SYM) -> bool:
    """MEMO AD-6: signed rows compare the magnitude (abs >). The Global set: Delta % 60 % (the story's seed), Delta
    300 BTC (example); the ETHUSDT set: Delta % SET2_PCT (example)."""
    if label == "Delta %":
        return abs(b.pct) > (PCT_BOUND if sym == SYM else SET2_PCT)
    if label == "Delta" and sym == SYM:
        return abs(b.delta) > DELTA_BOUND
    return False


# --- frames, tables, annotations, the board
def data_statement(nn: int) -> str:
    syms = f"{SYM} (seed {SEED})" + (f" and, on the per-symbol frame, {SYM2} (seed {SEED + 1})" if nn == 4 else "")
    return (f"Data: synthetic only — a seeded {syms} 1m series of {N_BARS} bars to the forming bar {hm_(N_BARS - 1)} "
            f"UTC; tick and qty step from the recorded instrument fixture; volumes, deltas, trades, prices, the "
            f"thresholds' example bounds and the viewing-as user \"{VIEW_AS_USER}\" are synthetic. No account data, "
            f"key or balance. C-2.11 (R-1): the strip reads the live public trade stream on demo and live alike; no "
            f"DEMO / LIVE badge and no environment control appears; nothing on this board differs by environment.")


def frame(fid: str, kids: list[Node | None], *, w: int = WIN_W, h: int = WIN_H, note: str | None = None) -> Node:
    """One frame: a w × h window on color.surface.app, clipped, children positioned (non-flex)."""
    if fid not in ALL_FRAMES:
        raise KeyError(f"{fid!r} is not a §0 frame")
    return box(frame_name(fid), [k for k in kids if k], {"fill": APP, "clip": True}, w=w, h=h,
               note=note or f"frame {fid}")


@dataclass(frozen=True)
class Col:
    key: str
    label: str
    w: int
    typo: str = CAPTION
    align: str | None = None


def cell(name: str, content: str | None, w_: int, *, h: int = 24, typo: str = CAPTION, color: str = TEXT_1,
         align: str | None = None, kids: list[Node] | None = None) -> Node:
    inner = w_ - 2 * PX[INSET_SM]
    ks = kids if kids is not None else ([text("value", content, typo, color, w=inner, align=align)] if content else [])
    return hbox(name, ks, {"padX": INSET_SM, "align": "center", "gap": INSET_XS}, w=w_, h=h)


def grid_table(name: str, cols: list[Col], rows: list[dict[str, Any]], *, row_h: int = 28,
               selected: Iterable[int] = ()) -> Node:
    """A drawn table (CMP-049 form): header row and rows; cells carry 8 px padding a side (16 between texts)."""
    w_ = sum(c.w for c in cols)
    sel = set(selected)
    kids: list[Node | None] = [hbox("header row", [cell(f"th · {c.key}", c.label, c.w, color=TEXT_2, align=c.align)
                                                   for c in cols], {"fill": RAISED}, w=w_, h=28),
                               rect("header rule", w_, 1, BORDER)]
    body = []
    for j, r in enumerate(rows):
        cs = [cell(c.key, r.get(c.key), c.w, h=row_h, typo=c.typo, align=c.align) for c in cols]
        body.append(hbox(f"row · {j + 1:02d}", cs, {"fill": SELECTED if j in sel else CANVAS if j % 2 else RAISED},
                         w=w_, h=row_h))
    kids.append(vbox("rows", body, {}, w=w_, h=sum(b["h"] for b in body) or 1) if body else None)
    return vbox(name, kids, {}, w=w_)


def frame_block(fid: str, lines: Iterable[str] = ()) -> tuple[str, list[str]]:
    if fid not in ALL_FRAMES:
        raise KeyError(f"{fid!r} is not a §0 frame")
    return fid, [state_line(fid), *[x for x in lines if x]]


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    b = BOARDS[nn]
    head = [f"§0 L{b.line}: {b.name}", f"Frames: {', '.join(b.frames)}",
            f"Theme: dark (exported as {b.export}); §0 L{S0 + 2}: {TWIN_CAP.group(1)} boards, "  # type: ignore
            f"{TWIN_CAP.group(2)} light twins — the light and high-contrast renders are not drawn, the text is binding; "  # type: ignore
            f"every fill here is a neutral token, so the T2 and breach grammar holds under any theme switch",
            f"{GREYSCALE_WORDS} (§0): a wireframe — colour, type, iconography and elevation are E20-D03's", *board_lines]
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


def board(nn: int, frames: list[Node], ann: Node, cols: int, *, strict: bool = True) -> tuple[dict[str, Any],
                                                                                            list[Node]]:
    """The root (the board name, grid x/y, color.surface.app, clip) hugging the frames + ONE annotation column + 80; a
    "state: <id>" caption 24 px above each frame; the data statement 24 px under the frames. The root's h is
    MEASURED_H[nn] once the drawing lane measured it, else the estimate."""
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
    ah = est_height(ann) * ANN_SLACK
    wd = right + MARGIN + ANN_W + MARGIN
    fh = est_height(foot[0])
    h = int(math.ceil((max(bottom + 24 + fh, MARGIN + ah) + MARGIN) / 8) * 8)
    if strict and nn in MEASURED_H:
        # the estimate may wrap the footer one caption line more than the live text does (01: estimated end 1867,
        # live 1854), so one line of slack; a measured h any lower still fails
        if MEASURED_H[nn] < bottom + 24 + fh + MARGIN - text_h(CAPTION, 1):
            raise ValueError(f"board {nn:02d}: measured h {MEASURED_H[nn]} < footer end {bottom + 24 + fh} + {MARGIN} "
                             f"less one caption line")
        h = MEASURED_H[nn]
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    if strict and nn in MEASURED_H:
        live(f"after touchTexts + relayout: the root's h {h} is the measured max(column end, footer end) + {MARGIN}")
    else:
        live(f"after touchTexts + relayout: measure max(annotation column end, footer end) + {MARGIN} and record it in "
             f"MEASURED_H[{nn}] (estimated {h}: the column at {ah:.0f} px with {ANN_SLACK - 1:.0%} slack)")
    for f in placed:
        live(f"frame {f['name']!r}: read back {f['w']} x {f['h']} at ({f['x']}, {f['y']}); clip on, no child spills")
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
    text carry h; no '/' in names; no backtick in drawn text; colours greyscale; table cells padded 8 px a side."""
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
        if n["t"] == "text" and "`" in n.get("chars", ""):
            bad.append(f"{p}: backtick in drawn text")
        o = n.get("o") or {}
        if "wrap" in o and o["wrap"] not in ("wrap", "nowrap"):
            bad.append(f"{p}: wrap {o['wrap']!r}")
        for v in [n.get("color"), *o.values()]:
            if isinstance(v, str) and v.startswith("color.") and v not in GREY:
                bad.append(f"{p}: hue {v}")
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


def run_py(args: list[str], timeout: int = 300, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """A Python child in UTF-8 mode (-X utf8), isolated (-I), without bytecode (-B)."""
    return subprocess.run([*PY, *args], capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False,
                          cwd=cwd)


def validate(path: Path) -> tuple[int, str]:
    res = run_py([str(VALIDATOR), str(path), "--components", str(COMPONENTS), "--tokens", str(TOKENS_FILE)], 120)
    return res.returncode, "\n".join((res.stdout + res.stderr).strip().splitlines())


def write_sheet(nn: int, frames: list[Node], ann: Node, cols: int, *, notes: dict[str, Iterable[str]] | None = None,
                out_dir: Path = CAP_DIR, name: str | None = None, strict: bool = True) -> Path:
    """Assemble board nn, split into sections, merge notes, write out_dir/NN-<slug>.json (LF), run the validator;
    raise unless it exits 0 and the kit lint and the banned scan are clean. Clears NOTES."""
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
    NOTES.add("sources", f"spec {DOCS['spec'][0]} md5 {DOCS['spec'][1]} at {HEAD} (§0 L{b.line}); the ruling of "
                         f"record folded (BQ-0 … BQ-9); no hand-off file")
    NOTES.add("sources", f"{DOCS['floor'][0]} md5 {DOCS['floor'][1]} (L{FLOOR_LINE}: the delta width floor "
                         f"{FLOOR_PX} px, the collapse floor's seed, §4.1)")
    NOTES.add("sources", f"{DOCS['fixture'][0]} md5 {DOCS['fixture'][1]} (tick and qty step: " +
              ", ".join(f"{s} {t} / {q}" for s, (t, q) in INSTR.items()) + ")")
    shapes = sum(1 for n in nodes for _p, _x in walk(n))
    if shapes > 2000:
        NOTES.add("live_checks", f"{shapes} shapes on this board (over 2,000): draw it in its section order and allow "
                                 f"for the longer render")
    sheet = {"board": root, "sections": sections_for(nodes), "export": b.export,
             "notes": {k: list(v) for k, v in NOTES.d.items()}}
    NOTES.reset()
    banned = _scan_banned(sheet)
    if bad or banned:
        raise RuntimeError(f"board {nn:02d}: lint {bad[:8]} banned {banned}")
    out = out_dir / (name or b.sheet)
    write_lf(out, json.dumps(sheet, ensure_ascii=False, indent=1) + "\n")
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
           summary or f"Board {nn:02d} of {len(BOARDS)} (§0 L{b.line}). Grid ({x}, {y}); {sh['board']['w']} x "
                      f"{sh['board']['h']} px; \"page {PAGE} · board {nn:02d} · {REV}\".", "", "## Frames", ""]
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
    write_lf(p, s)
    if sp.parent == CAP_DIR.resolve():  # the sidecar beside the kit (committed with it; check_all compares the two)
        write_lf(KIT_DIR / p.name, s)
    return p


def pack_sheet(sheet_path: Path, out_dir: Path = V4_DIR) -> Path:
    """Pack with the repo packer (compact.py) into out_dir/<same name>; the pack-source record = the raw sheet's
    absolute path + its sha256 (mkcall4 renders only while that file is unchanged); check the sha256, every packed
    section <= PACKED_MAX bytes, mkcall4 count == the section count, and no banned string outside that record."""
    src = Path(sheet_path).resolve()
    out_dir = out_dir.resolve()
    if out_dir not in (V4_DIR.resolve(), SELFTEST_DIR.resolve()):
        raise ValueError(f"packed sheets go to {V4_DIR}")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (src.name if out_dir == V4_DIR.resolve() else src.stem + ".packed.json")
    res = run_py([str(PACKER), str(src), str(dst)])
    if res.returncode != 0:
        raise RuntimeError(f"packer exit {res.returncode}: {(res.stdout + res.stderr).strip()[-600:]}")
    raw = dst.read_bytes()
    if b"\r\n" in raw:
        write_lf(dst, raw.decode("utf-8").replace("\r\n", "\n"))
    sh = json.loads(dst.read_text(encoding="utf-8"))
    src_key = next(k for k in sh if k.startswith("compact"))
    if sh.get(src_key) != {"file": str(src), "sha256": hashlib.sha256(src.read_bytes()).hexdigest()}:
        raise RuntimeError(f"{dst.name}: pack source {sh.get(src_key)!r} is not {src} + its sha256")
    # the provenance field is the bare raw file name (never an absolute path); mkcall4 resolves it from the raw
    # sheet's folder, so the render lane runs mkcall4 with that folder as its working directory
    txt = dst.read_text(encoding="utf-8")
    old = json.dumps(str(src), ensure_ascii=False)
    if txt.count(old) != 1:
        raise RuntimeError(f"{dst.name}: the raw path appears {txt.count(old)} times in the packed sheet")
    write_lf(dst, txt.replace(old, json.dumps(src.name, ensure_ascii=False)))
    sh = json.loads(dst.read_text(encoding="utf-8"))
    cnt = run_py([str(MKCALL), str(dst), "count"], 120, cwd=src.parent)
    if cnt.returncode != 0 or cnt.stdout.strip() != str(len(sh["sections"])):
        raise RuntimeError(f"{dst.name}: mkcall4 count {cnt.stdout.strip()!r} rc {cnt.returncode} != "
                           f"{len(sh['sections'])}: {cnt.stderr.strip()[-300:]}")
    big = [(s["node"]["name"], n) for s in sh["sections"]
           if (n := len(json.dumps(s, ensure_ascii=False, separators=(",", ":")).encode())) > PACKED_MAX]
    if big:
        raise RuntimeError(f"{dst.name}: packed sections over {PACKED_MAX} B: {big[:5]}")
    banned = _scan_banned({k: v for k, v in sh.items() if k != src_key})
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
    check(sorted(BOARDS) == list(range(1, 11)), "§0: ten boards 01-10, each PENDING or drawn as its own board")
    check(TWIN_CAP.groups() == ("10", "0") and not any(b.twin for b in BOARDS.values()),  # type: ignore[union-attr]
          "§0: 0 light twins (≤ ⅓)")
    check(PAGE == KEY and FILE_NAME == f"{KEY} boards" and EXPORT_DIR == f"docs/design/{EPIC}/img",
          f"page {PAGE!r}, file {FILE_NAME!r}, export dir {EXPORT_DIR!r}")
    check((WIN_W, WIN_H) == (1280, 800), f"frames {WIN_W} × {WIN_H}")
    check(len(ALL_FRAMES) == len(set(ALL_FRAMES)) == 31, f"§0: {len(ALL_FRAMES)} frames, unique")
    check(sorted(STATES) == sorted(ALL_FRAMES) and all(board_of(f) == STATES[f][1] for f in ALL_FRAMES),
          f"§2: every state's frame on its §0 board ({len(STATES)})")
    check(sorted(COPY, key=lambda x: int(x[2:])) == [f"W-{i}" for i in range(1, 30)], "§12: W-1..W-29")
    check([r["label"] for r in ALL_ROWS[:5]] == [r["label"] for r in DEFAULT_ROWS] and len(ALL_ROWS) == CEILING == 12
          and [r["label"] for r in COMPACT_ROWS] == [r["label"] for r in DEFAULT_ROWS[:3]],
          "§3.2 / §3.3 / §3.4: the default five lead the twelve; compact = the default's first three")
    check(len(CATALOGUE) == 20 and set(SOURCES) == {r["label"] for r in CATALOGUE} and
          set(OTHER_8) == {r["label"] for r in CATALOGUE} - {r["label"] for r in ALL_ROWS},
          f"§6.1 / §9: 20 rows, one source line each; the other 8 {OTHER_8}")
    check(FLOOR_PX == 40, f"E18-D02:{FLOOR_LINE}: the delta width floor {FLOOR_PX} px")
    check((PCT_BOUND, DELTA_BOUND, SPARK_N, GUARD_MAX, GUARD_DRAW, EXPORT_JOB) == (60, 300, 20, 6, 3, 50000),
          f"bounds {PCT_BOUND} % / {DELTA_BOUND} BTC, sparkline N {SPARK_N}, guard {GUARD_MAX} / {GUARD_DRAW}, "
          f"job over {EXPORT_JOB} bars")
    win = {b.t: b for b in window(16)}
    for t, rows in PLANTS.items():
        for lab, v in rows.items():
            drawn = D(value(lab, win[t]).replace(" %", "").replace(MINUS, "-").replace(",", ""))
            check(drawn == v, f"§3.6: {lab} at {t} draws {value(lab, win[t])} (the table's {v})")
    br = sorted((lab, b.t) for b in window(16) for lab in ("Delta", "Delta %") if breached(lab, b) and not b.forming)
    want = sorted((lab, t) for t, rows in PLANTS.items() for lab, v in rows.items()
                  if abs(v) > (PCT_BOUND if lab == "Delta %" else DELTA_BOUND))
    check(br == want, f"§3.6: exactly the table's breached cells breach in the window {br}")
    check(all(b.buy >= 0 and b.sell >= 0 and b.l <= min(b.o, b.c) and b.h >= max(b.o, b.c) for s in BARS.values()
              for b in s), "series: non-negative legs, high / low bound the body")
    miss = sorted(v for k_, v in globals().items() if k_.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border|opacity)\.", v) and v not in TOKEN_NAMES)
    check(not miss and GREY <= TOKEN_NAMES, f"kit tokens exist (missing {miss})")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: text("x", "y", color="color.text.disabled"),
                 lambda: rect("x", 1, 1, "color.not.a.token"), lambda: box("x", [], {"opacity": "opacity.disabled"}),
                 lambda: rect("x", 1, 1, "color.buy.default"), lambda: S("not a spec string at all xyzzy"),
                 lambda: W("W-13", nope=1), lambda: W("W-13")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError, LookupError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/', the never-tokens, an unknown token, a hue, a non-spec string "
                "and an unfilled slot refused")
    check(text("x", "`code`")["chars"] == "code", "backticks stripped from drawn text")
    NOTES.reset()
    fid = BOARDS[1].frames[0]
    fr = frame(fid, [text("sample", W("W-1"), HEADING_SM, TEXT_1, x=40, y=40)])
    ann = annotations(1, [frame_block(fid, ["self-test"])], board_lines=["Self-test sheet, not a board of the set"])
    path = write_sheet(1, [fr], ann, 1, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False)
    check(path.exists() and b"\r\n" not in path.read_bytes(), f"validator exit 0, LF only: {path.name}")
    md = write_md(1, path, summary="Self-test sheet (one sample frame); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    check(l3 == md_line3(1) and f"page `{PAGE}`" in l3 and l3.endswith("theme dark."), f"md line 3: {l3}")
    packed = pack_sheet(path, SELFTEST_DIR)
    sh = json.loads(packed.read_text(encoding="utf-8"))
    src_key = next(k for k in sh if k.startswith("compact"))
    check(sh[src_key]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest(),
          f"packed {packed.name}: source sha256 = raw, {len(sh['sections'])} sections, mkcall4 count agrees")
    print(f"{'OK' if not fails else 'FAILED'}: {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        raise SystemExit(selftest())
    print(__doc__)
    raise SystemExit(2)
