"""E26-D02 (#509) board kit: SCR-097, the replay page, as ten composite cvsheet JSON sheets for the per-set Penpot file
"E26-D02 boards", page "E26-D02 SCR-097 Replay page" (spec §16, RULED: comment 6555545802).

Offline only. Spec (binding; every string comes from it): docs/design/E26/E26-D02.md and E26-D02-handoff.md as the
checkout commits them, read by repo-relative path and md5-pinned in DOCS (the kit refuses drifted bytes; re-read,
re-pin). The recorded instrument fixture gives BTCUSDT's tick size and qty step only; every other number is the
shared synthetic replay world (seed 509), derived once below and never typed twice.
Registry: §16's composite table (BOARDS) and frame table (FRAMES) are parsed, never typed.

Checkout: the repository root is $CV_REPO when set, else this file's parents[4] (the committed layout
docs/design/_tools/sheets/e26-d02/). Outputs: raw sheets + their .md in CAP_DIR, packed sheets in V4_DIR, the .md
also beside the kit.

Pipeline (one generator per board, gen/gen_NN.py, calling gen/frames.py):
    frames = [frame(fid), ...]                 # the board's nested frames in §16's order
    build(nn, frames, blocks)                  # raw sheet (validator exit 0 or raises), md (line 3 = render line),
                                               # packed sheet (mkcall4 count agrees; compactOf = bare name + sha256)
Self-test: python3 -I -B e26d02kit.py selftest

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (U+2215 "∕" stands for it); no local path, host
or agent name anywhere in a sheet (BANNED); packed sections <= 9 KB; table cells carry 8 px inner padding a side.
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
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KIT_DIR = Path(__file__).resolve().parent
_ENV_REPO = os.environ.get("CV_REPO")
REPO = Path(_ENV_REPO).resolve() if _ENV_REPO else KIT_DIR.parents[4]
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR = TOOLS / "validate_sheet.py"
MKCALL = TOOLS / "mkcall4.py"
COMPONENTS = TOOLS / "components.offline.json"
BASE_TOKENS = TOOLS / "token-sync.json"
PACKER = TOOLS / "compact.py"
CAP_DIR = KIT_DIR / "build"  # raw sheets + their .md (not committed; .gitignore)
V4_DIR = KIT_DIR / "v4"  # packed sheets (committed; compactOf.file = the bare raw-sheet name)
SELFTEST_DIR = CAP_DIR / "selftest"
LOCAL_TOKENS = KIT_DIR / "local-tokens.json"  # the PROPOSED local token rows (BQ-10)
TOKENS_FILE = KIT_DIR / "tokens.with-local.json"  # token-sync.json + the local rows: the validator's --tokens

DOCS = {  # key -> (repo-relative path, md5): every read is md5-checked (pinned at the committed boards-PR text)
    "spec": ("docs/design/E26/E26-D02.md", "d4f771089fecf536af17f46dbb39dce8"),
    "handoff": ("docs/design/E26/E26-D02-handoff.md", "32dd05214341aed52e9e9ba533e1daac"),
    "fixture": ("packages/fixtures/bybit/2026-10-05/rest/instruments_before.json", "edd9dd2a060c51bd4bd1450307728ddf"),
}

KEY = "E26-D02"
FILE_NAME = "E26-D02 boards"
REV = "r1"
PITCH_X, PITCH_Y = 6000, 3200  # grid: x = ((NN-1) mod 5) * 6000, y = floor((NN-1)/5) * 3200
MARGIN = 80  # root margin and frame gutters
ANN_W = 400  # the ONE annotation column, outside the frames
ANN_TEXT_W = ANN_W - 32
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
    raise SystemExit(f"e26d02kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
LINES = {k: _COMMENT.sub("", _doc_bytes(k).decode("utf-8")).split("\n") for k in DOCS if k != "fixture"}
SPEC_LINES, HANDOFF_LINES = LINES["spec"], LINES["handoff"]
SPEC_TEXT = "\n".join(SPEC_LINES)
HANDOFF_TEXT = "\n".join(HANDOFF_LINES)


def _cells(row: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


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


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("\\|", "|")).strip()


def unquote(s: str) -> str:
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


def _flat(doc: str) -> str:
    return re.sub(r"[ \t]*\n[ \t]*", " ", (SPEC_TEXT if doc == "spec" else HANDOFF_TEXT).replace("\\|", "|"))


def S(chars: str, doc: str = "spec") -> str:
    """A drawn string that must occur verbatim in the spec (or the hand-off), line breaks read as spaces and
    table-escaped pipes unescaped: returns it unchanged."""
    if chars not in _flat(doc):
        raise LookupError(f"{doc}: string not in the text: {chars!r}")
    return chars


def SL(chars: str, doc: str = "spec") -> int:
    """The line a verbatim string starts on (after S)."""
    S(chars, doc)
    for n in (len(chars), 40, 20, 10):
        for i, ln in enumerate(LINES[doc], 1):
            if chars[:n] in ln.replace("\\|", "|"):
                return i
    raise LookupError(chars)


# --- §16: the ten composite boards and the frame table (parsed)
_H16 = L("## 16. Boards (Penpot file `")
PAGE = re.search(r"page `([^`]+)`", SPEC_LINES[_H16 - 1]).group(1)  # type: ignore[union-attr]
_DEF_SIZE = re.search(r"Frames (\d+) × (\d+) unless stated", SPEC_TEXT)
DEFAULT_W, DEFAULT_H = int(_DEF_SIZE.group(1)), int(_DEF_SIZE.group(2))  # type: ignore[union-attr]


@dataclass(frozen=True)
class Frame:
    fid: str  # "01"
    path: str  # "SCR-097/anatomy-redlines"
    w: int
    h: int
    boards: tuple[str, ...]  # ("B2", "B3"); () when not drawn
    shows: str
    purpose: str
    line: int


@dataclass(frozen=True)
class Board:
    nn: int
    bid: str  # "B1"
    name: str  # "E26-D02 / 01 anatomy-focus-order"
    slug: str
    nested: str  # the §16 "Nested frames" cell
    theme: str
    export_png: str
    frames: tuple[str, ...]  # frame ids in the cell's order
    line: int

    @property
    def export(self) -> str:
        return f"docs/design/E26/img/{self.export_png}"

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"

    @property
    def twin_of(self) -> str | None:
        m = re.search(r"light twin of (B\d+)", self.nested)
        return m.group(1) if m else None


def _parse_frames() -> dict[str, Frame]:
    a = L("| #   | Board ", _H16)
    out: dict[str, Frame] = {}
    for i in range(a + 2, len(SPEC_LINES) + 1):
        ln = SPEC_LINES[i - 1]
        if not ln.startswith("|"):
            break
        c = _cells(ln)
        m = re.fullmatch(r"`([^`]+)`(?: \((\d+) × (\d+)\))?", c[1])
        if not m:
            raise ValueError(f"spec L{i}: frame cell {c[1]!r}")
        bs = tuple(re.findall(r"B\d+", c[2]))
        out[c[0]] = Frame(c[0], m.group(1), int(m.group(2) or DEFAULT_W), int(m.group(3) or DEFAULT_H), bs,
                          plain(c[3]), plain(c[4]), i)
    return out


FRAMES = _parse_frames()


def _parse_boards() -> dict[int, Board]:
    out: dict[int, Board] = {}
    for i in range(_H16, L("**Not drawn — the text is binding", _H16)):
        ln = SPEC_LINES[i - 1]
        if not re.match(r"^\| B\d+ ", ln):
            continue
        c = _cells(ln)
        m = re.fullmatch(r"`(E26-D02 / (\d{2}) ([a-z0-9-]+))`", c[1])
        if not m:
            raise ValueError(f"spec L{i}: board cell {c[1]!r}")
        nn = int(m.group(2))
        if c[0] != f"B{nn}":
            raise ValueError(f"spec L{i}: {c[0]} vs {nn}")
        ids = [x for x in dict.fromkeys(re.findall(r"\b(\d{2})\b", c[2])) if x in FRAMES and c[0] in FRAMES[x].boards]
        out[nn] = Board(nn, c[0], m.group(1), m.group(3), plain(c[2]), c[3], c[4].strip("`"), tuple(ids), i)
    return out


BOARDS = _parse_boards()
NOT_DRAWN = tuple(f for f, fr in FRAMES.items() if not fr.boards)


def frame_label(fid: str, theme: str) -> str:
    """The caption id: '01 SCR-097/anatomy-redlines · dark'."""
    return f"{fid} {FRAMES[fid].path} · {theme}"


def frame_name(fid: str, theme: str) -> str:
    """The node name: the caption id with U+2215 for every '/'."""
    return frame_label(fid, theme).replace("/", SLASH)


def grid_xy(nn: int) -> tuple[int, int]:
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


# --- the PROPOSED local token (RULED BQ-10; OQ-1 the owner's): color.replay.border as E11-D02 CR-4's purple
# primitives, one row per theme set, written beside the kit and layered on token-sync.json for the validator
REPLAY = "color.replay.border"
_CR4 = re.search(r"CR-4's purple primitives \(`(palette\.purple\.\d+)` / `\.(\d+)` / `\.(\d+)`\)", SPEC_TEXT)
CR4 = {"dark": _CR4.group(1), "light": f"palette.purple.{_CR4.group(2)}",  # type: ignore[union-attr]
       "hc": f"palette.purple.{_CR4.group(3)}"}  # type: ignore[union-attr]
LOCAL_SET = "E26-D02 local · {theme}"
LOCAL_ROWS = [[LOCAL_SET.format(theme=t), REPLAY, "color", "{" + CR4[t] + "}"] for t in ("dark", "light", "hc")]


def _json_rows(rows: list[list[Any]]) -> str:
    return "[\n" + ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in rows) + "\n]\n"


def ensure_tokens() -> None:
    """Write local-tokens.json and tokens.with-local.json (deterministic; rewritten only when they differ)."""
    base = json.loads(BASE_TOKENS.read_text(encoding="utf-8"))
    prim = {r[1] for r in base if r[0] == "primitives"}
    if any(v[1:-1] not in prim for *_x, v in LOCAL_ROWS) or any(r[1] == REPLAY for r in base):
        raise RuntimeError("local token rows: a primitive is missing, or color.replay.border is already a token")
    for path, text_ in ((LOCAL_TOKENS, _json_rows(LOCAL_ROWS)), (TOKENS_FILE, _json_rows(base + LOCAL_ROWS))):
        if not path.exists() or path.read_text(encoding="utf-8") != text_:
            path.write_text(text_, encoding="utf-8")


ensure_tokens()


# --- tokens (exact names in token-sync.json + the local row; the self-test checks every one). §11 is the redline table.
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_ON_ACTION, TEXT_LINK = "color.text.on-action", "color.text.link"
BORDER, BORDER_SUBTLE, BORDER_STRONG, RING = ("color.border.default", "color.border.subtle", "color.border.strong",
                                              "color.focus.ring")
ACTION_PRIMARY, ACTION_SECONDARY = "color.action.primary.default", "color.action.secondary.default"
INFO_SUBTLE, INFO_STRONG = "color.status.info.subtle", "color.status.info.strong"
WARN_SUBTLE, WARN_STRONG = "color.status.warning.subtle", "color.status.warning.strong"
DANGER_SUBTLE, DANGER_STRONG = "color.status.danger.subtle", "color.status.danger.strong"
NEUTRAL = "color.neutral.default"
ENV_DEMO = "color.env.demo"
CANDLE_UP, CANDLE_DOWN, WICK = "color.candle.up", "color.candle.down", "color.candle.wick"
BUY, SELL = "color.buy.default", "color.sell.default"
GRID, AXIS_TEXT = "color.grid.line", "color.axis.text"
DISC_TEXT, DISC_IND = "color.data-confidence.disconnected.text", "color.data-confidence.disconnected.indicator"
LIVE_TEXT, LIVE_IND = "color.data-confidence.live.text", "color.data-confidence.live.indicator"
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD = "type.ui.heading-sm", "type.ui.heading-md"
NUM_XS, NUM_SM, NUM, NUM_MD = "type.num.xs", "type.num.sm", "type.num.base", "type.num.md"
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
SPACE_4 = "space.4"  # 16: §11's header group gap and divider margins
BUTTON_PADX = "space.button.paddingX"
ICON_SM, ICON, ICON_MD, ICON_LG = "size.icon.sm", "size.icon", "size.icon.md", "size.icon.lg"
R_CONTROL, R_CARD, R_BADGE, R_PILL = "radius.control", "radius.card", "radius.badge", "radius.pill"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
SCRIM = "opacity.scrim"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, SPACE_4: 16, BUTTON_PADX: 12, ICON_SM: 12, ICON: 16, ICON_MD: 16, ICON_LG: 20}
NEVER = ("color.text.disabled", "opacity.disabled")  # §5.3 G-T2.2: never on a T2 label, glyph or reason
FALLBACKS = {
    "chrome": "kit choice: the terminal's TopBar and StatusBar drawn as neutral placeholders (E10's, not this spec's); "
              "only the CMP-074 band position, the header strip, the dock and the transport are this spec's (§3)",
    "replay-glyph": "kit choice: icon/replay (E11-D02 CR-7) is not in the local icon set; its 16 px slot is drawn "
                    "with the local 'refresh' glyph, named 'icon∕replay (stand-in)'",
    "glyphs": "kit choice: the transport's |<<, <, > and >>| glyphs (CMP-002, icon-only) are drawn as their own "
              "characters in type.num.base inside the 24 × 24 button; the icons are E26-D05's",
    "spinner": "kit choice: CMP-001's loading spinner (no spinner icon in the local set) drawn as a 12 px ellipse "
               "outline in color.text.on-action, border.thick, centred at the label's width; static",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)",
    "scrim": "opacity.scrim is a Tier-1 primitive (validator WARN); §11 names it for the scrim and the dimmed future",
    "hidden": "kit choice: a visually hidden string drawn for the board as caption text in a dashed-look outline "
              "(the words a screen reader hears; not on screen in the product)",
    "badge": "kit choice: focus-order numbers drawn as 20 px numbered markers in color.focus.ring (board markers, "
              "not product UI)",
    "redline": "kit choice: redline callouts drawn as caption text joined to the specimen by a 1 px "
               "color.border.strong leader (board markers, not product UI)",
    "tray": "kit choice (§16 readings): a state's other moments drawn at full scale in 'board marker · tray' boxes "
            "inside the frame (1 px color.border.strong outline, a caption naming the moment), never as product UI",
    "hatch": "kit choice: the 45° hatch at a 6 px pitch drawn as 2 × 2 px color.neutral.default steps (three per "
             "stroke on the 6 px track); the chart's gap band draws the same steps in 12 px strips at its top and "
             "foot between its dashed edges (the full-height texture is E11-D05's rotated-line recipe, applied live)",
    "dash": "kit choice: dashed lines (virtual now, the hatch edges) drawn as 4 px dashes with 4 px gaps",
    "exit-glyph": "kit choice: board 17's exit glyph for comparison beside >>| drawn as a 12 × 14 door outline with "
                  "the local chevron-right (no exit icon in the local set), in a board marker box",
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
    """A drawn string the spec does not word (a kit choice or a neutral placeholder): say where it comes from."""
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
         HEADING_SM: (14, 1.2, False), HEADING_MD: (16, 1.2, False), NUM_XS: (10, 1.2, True), NUM_SM: (11, 1.2, True),
         NUM: (13, 1.2, True), NUM_MD: (14, 1.2, True)}


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



# --- the shared synthetic replay world (identical for every E26 board set; declared synthetic on every board)
SEED = 509  # the issue number: seeds every price, size and print
SYMBOL = "BTCUSDT"
_WIN = re.search(r"BTCUSDT, window (\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})–(\d{2}):(\d{2}) UTC", SPEC_TEXT)
_Y, _MO, _D, _H0, _M0, _H1, _M1 = (int(_WIN.group(i)) for i in range(1, 8))  # type: ignore[union-attr]
UTC = timezone.utc
W_FROM = datetime(_Y, _MO, _D, _H0, _M0, tzinfo=UTC)  # 2026-09-13 13:00 UTC: the window start (spec L25)
W_TO = datetime(_Y, _MO, _D, _H1, _M1, tzinfo=UTC)  # 15:00
PAPER = re.search(r'a paper account labelled "([^"]+)"', SPEC_TEXT).group(1)  # type: ignore[union-attr]


def _t(hms: str) -> datetime:
    h, m, s = (hms.split(":") + ["0"])[:3]
    sec = Decimal(s)
    return W_FROM.replace(hour=int(h), minute=int(m), second=int(sec), microsecond=int((sec % 1) * 1000000))


HISTORY_START = _t(re.search(r"Recorded from (\d\d:\d\d:\d\d)", SPEC_TEXT).group(1))  # type: ignore[union-attr]
_GAP = re.search(r"No data (\d\d:\d\d:\d\d)–(\d\d:\d\d:\d\d) UTC", SPEC_TEXT)
GAP_FROM, GAP_TO = _t(_GAP.group(1)), _t(_GAP.group(2))  # type: ignore[union-attr]
PARTIAL_FROM = _t(re.search(r"partial after (\d\d:\d\d)", SPEC_TEXT).group(1))  # type: ignore[union-attr]
PLAYHEAD = _t(re.search(r"`\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d\.\d{3}) UTC`", SPEC_TEXT).group(1))  # type: ignore
STOPPED = _t(re.search(r"Playback stopped at (\d\d:\d\d:\d\d\.\d{3})", SPEC_TEXT).group(1))  # type: ignore
CLOSED_AT = _t(re.search(r"data as of (\d\d:\d\d:\d\d)", SPEC_TEXT).group(1))  # type: ignore[union-attr]
SEEK_TO = _t(re.search(r"Seeking to (\d\d:\d\d:\d\d)…", SPEC_TEXT).group(1))  # type: ignore[union-attr]
STEPPED_TO = _t(re.search(r"Stepped one bar to (\d\d:\d\d:\d\d)", SPEC_TEXT).group(1))  # type: ignore[union-attr]
BOOKMARK_1 = _t(re.search(r'"1 · (\d\d:\d\d:\d\d) · label"', SPEC_TEXT).group(1))  # type: ignore[union-attr]
SPEED = 4  # the anatomy's 4× (§3, D-7)


def _fixture_filter(key: str, field_: str) -> Decimal:
    d = json.loads(_doc_bytes("fixture"))
    row = next(r for r in d["result"]["list"] if r["symbol"] == SYMBOL)
    return Decimal(row[key][field_])


TICK = _fixture_filter("priceFilter", "tickSize")  # 0.10
QTY_STEP = _fixture_filter("lotSizeFilter", "qtyStep")  # 0.001
PRICE_DP = max(0, -TICK.normalize().as_tuple().exponent)  # 1
QTY_DP = max(0, -QTY_STEP.normalize().as_tuple().exponent)  # 3
ANCHOR_LAST = Decimal(re.search(r"last (\d{2},\d{3}\.\d)", SPEC_TEXT).group(1).replace(",", ""))  # type: ignore
STEP_1M = timedelta(minutes=1)


def hms(t: datetime) -> str:
    return t.strftime("%H:%M:%S")


def hm(t: datetime) -> str:
    return t.strftime("%H:%M")


def hms_ms(t: datetime) -> str:
    return f"{hms(t)}.{t.microsecond // 1000:03d}"


def stamp(t: datetime) -> str:
    """The header's 27-character field (D-5): '2026-09-13 13:38:04.210 UTC'."""
    return f"{t.strftime('%Y-%m-%d')} {hms_ms(t)} UTC"


def chip_date(t: datetime) -> str:
    return f"{t.day} {t.strftime('%b')}"


def price(x: Decimal) -> str:
    return f"{x.quantize(TICK):,.{PRICE_DP}f}"


def qty(x: Decimal) -> str:
    return f"{x.quantize(QTY_STEP):.{QTY_DP}f}"


def recorded(t: datetime) -> str:
    """The coverage class at instant t (§6.1) over the session's streams: the world's one rule."""
    if t < HISTORY_START:
        return "not recorded"
    if GAP_FROM <= t < GAP_TO:
        return "gap"
    if t >= PARTIAL_FROM:
        return "partial"
    return "full"


@dataclass(frozen=True)
class Bar:
    t: datetime
    o: Decimal
    h: Decimal
    l: Decimal  # noqa: E741
    c: Decimal
    v: Decimal


@dataclass(frozen=True)
class Print:
    t: datetime
    p: Decimal
    q: Decimal
    side: str  # "Buy" | "Sell" (the taker)


def _world() -> tuple[list[Bar], list[Print]]:
    """1-minute bars and trade prints over the window from one seeded walk (SEED); no print where no trade stream was
    recorded (before the history start, inside the gap); then the whole walk shifted so the bar holding the playhead
    closes at the anatomy's illustrative last (§3: 64,011.0)."""
    rng = random.Random(SEED)
    p = Decimal(64000)
    prints: list[Print] = []
    t = W_FROM
    while t < W_TO:
        t += timedelta(milliseconds=rng.randint(700, 5200))
        p = (p + Decimal(rng.randint(-24, 24)) * TICK).quantize(TICK)
        if t < W_TO and recorded(t) != "gap" and t >= HISTORY_START:
            q = (Decimal(rng.randint(1, 900)) * QTY_STEP).quantize(QTY_STEP)
            prints.append(Print(t, p, q, "Buy" if rng.random() < 0.5 else "Sell"))
    cur = next(x for x in reversed(prints) if x.t <= PLAYHEAD)
    shift = ANCHOR_LAST - cur.p
    prints = [Print(x.t, x.p + shift, x.q, x.side) for x in prints]
    bars: list[Bar] = []
    m = HISTORY_START.replace(second=0, microsecond=0)
    while m < W_TO:
        ps = [x for x in prints if m <= x.t < m + STEP_1M]
        if ps:
            bars.append(Bar(m, ps[0].p, max(x.p for x in ps), min(x.p for x in ps), ps[-1].p, sum(x.q for x in ps)))
        m += STEP_1M
    return bars, prints


BARS, PRINTS = _world()


def bars_until(t: datetime) -> list[Bar]:
    """Bars as the clock shows them at t: closed bars plus the forming bar built from prints up to t."""
    out = [b for b in BARS if b.t + STEP_1M <= t]
    ps = [x for x in PRINTS if t.replace(second=0, microsecond=0) <= x.t <= t]
    if ps:
        out.append(Bar(ps[0].t.replace(second=0, microsecond=0), ps[0].p, max(x.p for x in ps), min(x.p for x in ps),
                       ps[-1].p, sum(x.q for x in ps)))
    return out


def last_at(t: datetime) -> Decimal:
    return next(x for x in reversed(PRINTS) if x.t <= t).p


def prints_until(t: datetime, k: int) -> list[Print]:
    return [x for x in PRINTS if x.t <= t][-k:]


def book_at(t: datetime, levels: int) -> tuple[list[tuple[Decimal, Decimal]], list[tuple[Decimal, Decimal]]]:
    """A seeded synthetic book around the last print at t: bids from the last price down, asks one tick up."""
    rng = random.Random(f"{SEED}-{t.isoformat()}")
    last = last_at(t)
    bids = [(last - TICK * i, Decimal(rng.randint(1, 4000)) * QTY_STEP) for i in range(levels)]
    asks = [(last + TICK * (i + 1), Decimal(rng.randint(1, 4000)) * QTY_STEP) for i in range(levels)]
    return bids, asks


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
def data_statement() -> str:
    s = S("**Frame data:** synthetic only")
    derive(f"world: {SYMBOL} 1-minute bars and prints from one walk seeded {SEED} (the issue number), prices at the "
           f"fixture's tick {TICK}, sizes at its qty step {QTY_STEP}; window {hm(W_FROM)}–{hm(W_TO)} UTC on "
           f"{W_FROM:%Y-%m-%d} (spec L{SL('window 2026-09-13 13:00–15:00 UTC')}); history start {hms(HISTORY_START)}; "
           f"gap {hms(GAP_FROM)}–{hms(GAP_TO)}; partial after {hm(PARTIAL_FROM)}; playhead {hms_ms(PLAYHEAD)}; the walk "
           f"shifted so the bar holding the playhead closes at §3's illustrative last {price(ANCHOR_LAST)}")
    return (f"Data: synthetic only ({s.strip('*').split(':')[0]}, spec L{SL(s)}): {SYMBOL}, window "
            f"{W_FROM:%Y-%m-%d} {hm(W_FROM)}–{hm(W_TO)} UTC, a paper account labelled \"{PAPER}\"; prices, sizes and "
            f"prints seeded {SEED}; tick size {TICK} from the recorded instrument fixture; no real account, key or "
            f"balance")


def frame_block(fid: str, theme: str, lines: Iterable[str]) -> tuple[str, list[str]]:
    fr = FRAMES[fid]
    head = [f"§16 L{fr.line}: {fr.shows}", f"For: {fr.purpose} · {fr.w} × {fr.h}"]
    return frame_label(fid, theme), head + [x for x in lines if x]


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    b = BOARDS[nn]
    head = [f"§16 L{b.line}: {b.nested}", f"Frames: {', '.join(b.frames)}",
            f"Theme: {b.theme}" + (f" (light twin of {b.twin_of}: every frame drawn by {b.twin_of}'s builders, "
                                   f"token-bound; the light set is activated at export)" if b.twin_of else ""),
            f"Export: {b.export}",
            f"Replay hue: {REPLAY}, PROPOSED local token (RULED BQ-10; OQ-1 the owner's): set "
            f"'{LOCAL_SET.format(theme=b.theme)}' = {CR4[b.theme]} (E11-D02 CR-4); AC 1 never rests on it",
            f"Not drawn — the text is binding; drawn on request: {', '.join(NOT_DRAWN)} (§16 "
            f"L{L('**Not drawn — the text is binding; drawn on request:**')})", *board_lines]
    kids = [text("title", b.name, HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate([("Board", head), *blocks], 1):
        bk = [text("label", lab, LABEL, TEXT_2, w=ANN_TEXT_W)] + [
            text(f"value-{j}", ln, CAPTION, TEXT_1, w=ANN_TEXT_W) for j, ln in enumerate(lines, 1) if ln.strip()]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} ({b.bid}) · {REV}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG, "fill": CANVAS}, w=ANN_W)


def layout(frames: list[Node]) -> list[Node]:
    """One row for one or two frames, rows of two otherwise; frames top-aligned in a row."""
    k = 2
    out, y, i = [], MARGIN, 0
    while i < len(frames):
        x = MARGIN
        for f in frames[i:i + k]:
            out.append(dict(f, x=x, y=y))
            x += f["w"] + MARGIN
        y += max(f["h"] for f in frames[i:i + k]) + MARGIN
        i += k
    return out


# the live check's root heights (build-notes "Live-check fold"): max(annotation end, footer end) + MARGIN as measured;
# the one-line footer measured 14 px where the estimate allows 28, so every root is 18 px under the estimate
MEASURED_H = {1: 1598, 2: 1278, 3: 1278, 4: 1278, 5: 2438, 6: 1398, 7: 2438, 8: 2438, 9: 1398, 10: 2558}
FOOTER_MEASURED_H = 14


def board(nn: int, frames: list[Node], ann: Node, *, strict: bool = True) -> tuple[dict[str, Any], list[Node]]:
    """The root (§16's name, grid x/y, color.surface.app, clip) hugging the frames + ONE annotation column + 80; a
    "state: <id>" caption 28 px above each frame; the data statement 24 px under the frames."""
    b = BOARDS[nn]
    want = [frame_name(f, b.theme) for f in b.frames]
    got = [f["name"] for f in frames]
    if strict and got != want:
        raise ValueError(f"board {nn:02d}: frames {got} != §16 {want}")
    for f in frames:
        fid = f["name"][:2]
        if strict and (f["w"], f["h"]) != (FRAMES[fid].w, FRAMES[fid].h):
            raise ValueError(f"board {nn:02d}: frame {fid} is {f['w']} x {f['h']}, §16 says {FRAMES[fid].w} x "
                             f"{FRAMES[fid].h}")
    if "/" in b.name.split(f"{KEY} / {nn:02d} ", 1)[1]:
        raise ValueError(f"board {nn:02d}: '/' after the prefix in {b.name!r}")
    placed = layout(frames)
    caps = [text(f"caption {i:02d}", f"state: {frame_label(f['name'][:2], b.theme) if strict else f['name']}",
                 CAPTION, TEXT_3, x=f["x"], y=f["y"] - 28) for i, f in enumerate(placed, 1)]
    right = max(f["x"] + f["w"] for f in placed)
    bottom = max(f["y"] + f["h"] for f in placed)
    foot = [text("footer · data statement", data_statement(), CAPTION, TEXT_2, x=MARGIN, y=bottom + 24,
                 w=right - MARGIN)]
    a = dict(ann, x=right + MARGIN, y=MARGIN)
    ah = est_height(ann)
    wd = right + MARGIN + ANN_W + MARGIN
    h = int(math.ceil((max(bottom + 24 + 28, MARGIN + ah) + MARGIN) / 8) * 8)
    if strict and nn in MEASURED_H:  # the live-measured end + MARGIN (it must still clear the frames and the footer)
        if MEASURED_H[nn] < bottom + 24 + FOOTER_MEASURED_H + MARGIN:
            raise ValueError(f"board {nn:02d}: measured h {MEASURED_H[nn]} < footer end "
                             f"{bottom + 24 + FOOTER_MEASURED_H} + {MARGIN}")
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
                          "--tokens", str(TOKENS_FILE)], capture_output=True, text=True, encoding="utf-8",
                         timeout=120, check=False)
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
        live(f"theme: activate the {b.theme} token set (and '{LOCAL_SET.format(theme=b.theme)}') before exporting "
             f"board {nn:02d}; read back one bound fill (color.surface.raised) as the {b.theme} value")
    live(f"local token: create set '{LOCAL_SET.format(theme=b.theme)}' with {REPLAY} = {CR4[b.theme]} "
         f"(local-tokens.json) before the first section call; every frame and chip border binds it")
    live(f"export {b.export}; record the board id and the PNG size")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", f"spec {DOCS['spec'][0].rsplit('/', 1)[1]} md5 {DOCS['spec'][1][:8]} and hand-off md5 "
                         f"{DOCS['handoff'][1][:8]} (§16 L{b.line}; §3-§13; RULED comment 6555545802)")
    NOTES.add("sources", f"{DOCS['fixture'][0]} md5 {DOCS['fixture'][1][:8]} (tick size and qty step only)")
    NOTES.add("sources", f"tokens: token-sync.json + local-tokens.json ({REPLAY}, PROPOSED, RULED BQ-10)")
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
           summary or f"Composite {b.bid} of ten (§16 L{b.line}: {b.nested}). Grid ({x}, {y}); {sh['board']['w']} x "
                      f"{sh['board']['h']} px; \"page {PAGE} · board {nn:02d} ({b.bid}) · {REV}\".", "", "## Frames", ""]
    out += [f"- `{frame_name(f, b.theme)}` (§16 frame {f}, L{FRAMES[f].line}, {FRAMES[f].w} x {FRAMES[f].h})"
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
    if sp.parent == CAP_DIR.resolve():  # the copy beside the kit
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
                         encoding="utf-8", timeout=300, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"packer exit {res.returncode}: {(res.stdout + res.stderr).strip()[-600:]}")
    raw = dst.read_text(encoding="utf-8")
    pf = (json.loads(raw).get("compactOf") or {}).get("file")
    if not pf or not Path(pf).is_absolute() or Path(pf) != src:
        raise RuntimeError(f"{dst.name}: compactOf.file {pf!r} is not the absolute source path")
    n_sec = len(json.loads(raw)["sections"])  # mkcall4 reads the pack source, so count before the name is made bare
    cnt = subprocess.run([sys.executable, "-I", "-B", str(MKCALL), str(dst), "count"], capture_output=True, text=True,
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


# --- §5.3's reason keys (parsed): key -> (string, condition, rendering, line)
def _t2_keys() -> dict[str, tuple[str, str, str, int]]:
    a = L("| Key                       | String")
    out = {}
    for i in range(a + 2, len(SPEC_LINES) + 1):
        ln = SPEC_LINES[i - 1]
        if not ln.startswith("|"):
            break
        c = _cells(ln)
        out[plain(c[0])] = (unquote(c[1]), plain(c[2]), plain(c[4]), i)
    return out


T2KEYS = _t2_keys()


def why(key: str) -> str:
    """The §5.3 string of a reason key (copy_keys note)."""
    s, _c, _r, ln = T2KEYS[key]
    copy_key(f"{key}: \"{s}\" (§5.3 L{ln})")
    return s


def tpl(example: str, subs: dict[str, str]) -> str:
    """A spec example re-filled with this frame's derived values: the example must occur verbatim in the spec."""
    S(example)
    out = example
    for a, b in subs.items():
        if a not in out:
            raise ValueError(f"{a!r} not in {example!r}")
        out = out.replace(a, b)
    if out != example:
        derive(f'"{out}": the spec\'s example "{example}" (L{SL(example)}) with this frame\'s values')
    return out



# --- tables (the E08-D10 kit's, copied): cells padded 8 px a side
ROW_H = 24  # compact rows (§11)


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


def spec_table(name: str, cols: list[Col], rows: list[dict[str, str]], *, cap: str, w_: int) -> Node:
    """A spec table drawn as a CMP-049-style grid on the panel surface (caption, header row, rows); cell strings are
    the spec's own."""
    if sum(c.w for c in cols) != w_:
        raise ValueError(f"{name}: columns {sum(c.w for c in cols)} != {w_}")
    body = [table_row(cols, r, f"row · {j + 1:02d}", fill=RAISED if j % 2 else CANVAS) for j, r in enumerate(rows)]
    return vbox(name, [text("caption", cap, CAPTION, TEXT_2, w=w_ - 16), header_row(cols),
                       rect("header rule", w_, 1, BORDER), rows_block(body)], {"gap": STACK_XS}, w=w_)

ETH = "ETHUSDT"  # the REAL-TIME panel's second symbol (kit choice, D-14's "a second-symbol chart"; OQ-3)


def _eth_bars() -> list[Bar]:
    """A second seeded walk (SEED-ETHUSDT) for the REAL-TIME panel's live chart, at ETHUSDT's fixture tick."""
    d = json.loads(_doc_bytes("fixture"))
    tick = Decimal(next(r for r in d["result"]["list"] if r["symbol"] == ETH)["priceFilter"]["tickSize"])
    rng = random.Random(f"{SEED}-{ETH}")
    p, out, m = Decimal("2400.00"), [], W_FROM
    while m < W_TO:
        o = p
        hi = lo = p
        for _ in range(12):
            p = (p + Decimal(rng.randint(-30, 30)) * tick).quantize(tick)
            hi, lo = max(hi, p), min(lo, p)
        out.append(Bar(m, o, hi, lo, p, Decimal(rng.randint(1, 900))))
        m += STEP_1M
    return out


ETH_BARS = _eth_bars()


# --- self-test: python3 -I -B e26d02kit.py selftest
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), f"pinned md5s ({len(DOCS)} sources)")
    check(sorted(BOARDS) == list(range(1, 11)), "§16: ten composite boards B1-B10")
    th = [b.theme for b in BOARDS.values()]
    check((th.count("dark"), th.count("light")) == (8, 2), "§16 themes: 8 dark, 2 light (B3, B8)")
    check(sum(1 for b in BOARDS.values() if b.twin_of) * 3 <= len(BOARDS), "light twins <= one third")
    drawn = sorted({f for b in BOARDS.values() for f in b.frames})
    check(drawn == sorted(f for f in FRAMES if f not in ("17", "20", "21")) and NOT_DRAWN == ("17", "20", "21"),
          f"frames 01-23 nested, not drawn {NOT_DRAWN}")
    check([BOARDS[n].frames for n in (1, 4, 9, 10)] == [("01", "19"), ("18", "05"), ("10", "09"),
                                                        ("15", "14", "22", "23")], "nested order per §16's cells")
    check(all(BOARDS[n].frames == BOARDS[int(BOARDS[n].twin_of[1:])].frames for n in BOARDS if BOARDS[n].twin_of),
          "every twin nests its base's frames")
    check(PAGE == "E26-D02 SCR-097 Replay page" and FILE_NAME == "E26-D02 boards", f"page {PAGE!r}")
    check(str(TICK) == "0.10" and str(QTY_STEP) == "0.001", f"fixture tick {TICK}, qty step {QTY_STEP}")
    check(len(stamp(PLAYHEAD)) == 27 and price(last_at(PLAYHEAD)) == "64,011.0",
          f"world: {stamp(PLAYHEAD)!r} (27 ch), last {price(last_at(PLAYHEAD))}")
    check(not any(GAP_FROM <= x.t < GAP_TO or x.t < HISTORY_START for x in PRINTS), "no print in the gap or before "
          "the history start")
    check(len(T2KEYS) == 17 and "replay.ended" in T2KEYS, f"§5.3: {len(T2KEYS)} reason keys")
    check(json.loads(LOCAL_TOKENS.read_text(encoding="utf-8")) == LOCAL_ROWS and
          [r[3] for r in LOCAL_ROWS] == ["{palette.purple.400}", "{palette.purple.600}", "{palette.purple.400}"],
          "local token rows: CR-4's purple per theme")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for kk, v in globals().items() if kk.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border|opacity)\.", v)]
    check(all(u in toks for u in used if u not in NEVER), "kit tokens exist (with the local row)")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: S("a string the spec never says")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError, LookupError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/' and an unworded string refused")
    sys.path.insert(0, str(KIT_DIR / "gen"))
    import frames as fr_  # noqa: PLC0415  (the frame builders import this kit)
    NOTES.reset()
    node_, lines = fr_.BUILDERS["18"]("dark")
    ann = annotations(4, [frame_block("18", "dark", lines)], board_lines=["Self-test sheet: one frame"])
    path = write_sheet(4, [node_], ann, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False,
                       notes={"live_checks": ["self-test sheet: not for rendering"]})
    check(path.exists(), f"validator exit 0: {path.name}")
    md = write_md(4, path, summary="Self-test sheet (frame 18); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    check(l3 == md_line3(4) and l3.endswith("theme dark."), f"md line 3: {l3}")
    check(md_line3(3).endswith("theme light.") and md_line3(8).endswith("theme light."), "md line 3: light twins")
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
