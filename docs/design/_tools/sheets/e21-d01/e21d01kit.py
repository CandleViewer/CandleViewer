"""E21-D01 (#417) research-board kit: memo §0's eight research boards as cvsheet JSON sheets for the per-set Penpot
file "E21-D01 boards", page "E21-D01" (the research-boards PR, which carries Closes #417; BQ-1, BQ-13 RULED).

Offline only. Spec (binding; every string comes from it): docs/design/research/e21-dom-heatmap.md (the memo: §0
boards, §2 RQ, §3 F, §4 W, §6 defaults, §7 AD, §8 K, §10 protocol, §12 C / OQ), read by repo-relative path from a
checkout and md5-pinned in DOCS (the kit refuses drifted bytes: re-read, re-check, re-pin). The recorded instrument
fixture gives the BTCUSDT tick (0.10) and qty step (0.001); every other value is the seeded synthetic book (seed 417,
WORLD below), and every drawn size, price, count and time is derived from it.

RESEARCH BOARDS: greyscale only (memo §0: "Dark only, greyscale, annotated; no visual design"). Every colour bound is
a neutral token (GREY below); a hue token is refused by node(). A board that shows a recommendation carries a PROPOSED
stamp. No third-party product name, imagery or logo is drawn (memo §5: product names in the memo only).

Checkout: the kit sits at docs/design/_tools/sheets/e21-d01/ in a checkout (REPO = four levels up), or anywhere with
CV_CHECKOUT naming the checkout. Raw sheets + .md go to CAP_DIR, packed sheets to V4_DIR (BUILD.md).
Pipeline (one generator per board, gen/gen_NN.py; shared parts in gen/rb.py):
    frames = [frame(fid, kids, w), ...]; blocks = [frame_block(fid, lines), ...]
    build(nn, frames, blocks, cols) -> raw sheet (validator exit 0), .md (line 3 = the render line), packed sheet
Self-test: python3 -I -B e21d01kit.py selftest

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (frame ids use U+2215); no local path, host or
agent name anywhere in a sheet (BANNED); table cells carry 8 px inner padding a side; every frame has a caption.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True

Node = dict[str, Any]

KEY, EPIC, ISSUE = "E21-D01", "E21", 417
KIT_DIR = Path(__file__).resolve().parent
_MEMO_PATH = "docs/design/research/e21-dom-heatmap.md"


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / _MEMO_PATH).is_file():
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / _MEMO_PATH).is_file():
        raise SystemExit("e21d01kit: run inside a checkout or set CV_CHECKOUT to one")
    return Path(env).resolve()


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
DOCS = {  # key -> (repo-relative path, md5): every read is md5-checked
    "spec": (_MEMO_PATH, "a95e35c3ab74dfb8b99e5633389d3dad"),
    "fixture": ("packages/fixtures/bybit/2026-10-05/rest/instruments_before.json", "edd9dd2a060c51bd4bd1450307728ddf"),
}
HEAD = "the boards PR (§0 drawn, §14 As built)"  # where the spec md5 was pinned (the text PR's pin was 934a56142)
REV = "r1"
PITCH_X, PITCH_Y = 7000, 6400  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80
# SHEET-FIX ALL (live check 2026-11-03): each root's h read back on the board as max(annotation end, footer end) + 80
# once Penpot laid the text out; the kit's estimate (15 % slack, 8 px steps) is the upper bound it must sit under.
LIVE_ROOT_H = {1: 2338, 2: 2591, 3: 2364, 4: 2151, 5: 1847, 6: 1299, 7: 1690, 8: 2250}
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
    raise SystemExit(f"e21d01kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
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


def quote(chars: str, doc: str = "spec", start: int = 1) -> str:
    """chars as it stands in doc (raises if absent)."""
    find_line(chars, doc, start)
    return chars


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



# --- registries parsed from the memo (spec): §0 boards, §2 RQ, §3 F, §4 W, §6 defaults, §7 AD, §8 K, §10 T, §12
S0 = find_line("## 0. Research boards (Penpot)")
PAGE = re.search(r"Page `([^`]+)`", LINES["spec"][S0 + 1]).group(1)  # type: ignore[union-attr]
FILE_NAME = f"{KEY} boards"
EXPORT_DIR = re.search(r"exported to `([^`]+)/" + re.escape(KEY) + r"-NN-slug\.png`",  # type: ignore[union-attr]
                       LINES["spec"][S0 + 1]).group(1)
KIT_FRAMES: dict[int, tuple[str, ...]] = {  # the kit's frame plan for memo §0's eight boards
    1: ("research/questions-hypotheses", "research/findings", "research/walkthroughs"),
    2: ("centring/auto-follow", "centring/free-scroll", "centring/centre-lock"),
    3: ("placement/beside", "placement/behind", "axis/locked-zoom"),
    4: ("pulled/consumed", "pulled/pulled", "pulled/side-by-side"),
    5: ("tiers/500-200-50", "shed/order", "shed/notice"),
    6: ("own-order/column-at-three-tiers", "legend/convention-and-anchors"),
    7: ("decisions/AD-1-to-AD-5", "decisions/AD-6-to-AD-10", "decisions/kill-list"),
    8: ("protocol/probes", "protocol/agenda-and-order", "keyboard/walkthrough-path"),
}


AD_DRAWN = {"AD-1": 3, "AD-2": 3, "AD-3": 2, "AD-4": 2, "AD-5": 6, "AD-6": 4, "AD-7": 5, "AD-8": 2, "AD-9": 3,
            "AD-10": 6}  # the board that illustrates each AD (check_all: that board's annotations carry its line)


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E21-D01 / 01 questions-hypotheses"
    slug: str
    shows: str  # §0's content cell, verbatim
    line: int  # §0 line
    frames: tuple[str, ...]
    theme: str = "dark"

    @property
    def export(self) -> str:
        return f"{EXPORT_DIR}/{KEY}-{self.nn:02d}-{self.slug}.png"

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"


def _boards() -> dict[int, Board]:
    out = {}
    for i, c in table("## 0. Research boards (Penpot)"):
        nn = int(c[0])
        name = plain(c[1])
        drawn = re.fullmatch(rf"drawn — {KEY}-{nn:02d}-[a-z0-9-]+\.png, .*", plain(c[3]))
        if (plain(c[3]) != "PENDING" and not drawn) or not name.startswith(f"{KEY} / {nn:02d} "):
            raise ValueError(f"§0 L{i}: {c!r}")
        slug = name.split(f"{KEY} / {nn:02d} ", 1)[1]
        out[nn] = Board(nn, name, slug, plain(c[2]), i, KIT_FRAMES[nn])
    return out


BOARDS = _boards()


def frame_name(fid: str) -> str:
    return fid.replace("/", SLASH)


def _rows(head: str, start: int = 1) -> dict[str, tuple[list[str], int]]:
    return {plain(c[0]): ([plain(x) for x in c], i) for i, c in table(head, "spec", start)}


RQS = _rows("## 2. Research questions")
FINDINGS = _rows("## 3. Heuristic evaluation")
WALKS = _rows("## 4. Persona walkthrough")
DEFAULTS = _rows("## 6. Recommended defaults")
ADS = _rows("## 7. Adopted decisions")
KILLS = _rows("## 8. Performance kill-list")
PROBES = _rows("### 10.2 Probes")
AGENDA = _rows("### 10.4 Agenda")
CONTRAS = _rows("### 12.1 Contradictions")
OQS = _rows("### 12.3 Open questions")
ORDER_LINE = find_line("Order: S1 runs T1")
BUDGET_LINE = find_line("Budget #1: ")


def memo(chars: str, start: int = 1) -> str:
    """A memo string verbatim (markdown code ticks and bold removed before the match; raises if absent)."""
    for i in range(start - 1, len(LINES["spec"])):
        if chars in plain(LINES["spec"][i]):
            NOTES.add("copy_keys", f"memo L{i + 1}: \"{chars}\"")
            return chars
    raise LookupError(f"memo: not found: {chars!r}")


def ad_line(aid: str) -> str:
    c, ln = ADS[aid]
    return f"{aid} (§7 L{ln}, PROPOSED): {c[2]}; {c[3]}"


def f_line(fid: str) -> str:
    c, ln = FINDINGS[fid]
    return f"{fid} (§3 L{ln}, {c[4]}): {c[1]}"
# --- tokens: WIREFRAME GREYSCALE. Only these colour tokens may be bound (node() refuses any other colour token).
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
BORDER_SUBTLE, BORDER, BORDER_STRONG = "color.border.subtle", "color.border.default", "color.border.strong"
NEUTRAL, NEUTRAL_SUBTLE = "color.neutral.default", "color.neutral.subtle"
GRID, AXIS = "color.grid.line", "color.axis.text"
GREY = frozenset((APP, CANVAS, RAISED, SUNKEN, HOVER, SELECTED, OVERLAY, TEXT_1, TEXT_2, TEXT_3, BORDER_SUBTLE, BORDER,
                  BORDER_STRONG, NEUTRAL, NEUTRAL_SUBTLE, GRID, AXIS))
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD = "type.ui.heading-sm", "type.ui.heading-md"
NUM_SM, NUM, NUM_MD, NUM_LG = "type.num.sm", "type.num.base", "type.num.md", "type.num.lg"
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
BUTTON_PADX, DIALOG_PAD = "space.button.paddingX", "space.dialog.padding"
ICON_SM, ICON = "size.icon.sm", "size.icon"
R_CONTROL, R_CARD, R_DIALOG, R_BADGE = "radius.control", "radius.card", "radius.dialog", "radius.badge"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, BUTTON_PADX: 12, DIALOG_PAD: 24, ICON_SM: 12, ICON: 16}
FALLBACKS = {
    "focus": "wireframe: the focus ring is drawn as a 2 px color.text.primary outline (border.focus), not "
             "color.focus.ring (a hue); E21-D02 binds the ring token in hi-fi",
    "ramp": "lo-fi: resting size is drawn as five grey steps on a log scale (none, color.surface.hover, "
            "color.surface.selected, color.neutral.default, color.text.secondary), never a hue; E21-D04 #504 picks the "
            "ramp tokens and checks them with contrast_check.py and cvd_sim.py (memo §1)",
    "side": "lo-fi: bid and ask are told apart by position (asks above the mark, bids below) and by the column "
            "heading, never by a hue (the bid/ask hue is user-configurable, F-16)",
    "pattern": "kit choice: the pulled carrier is a hollow 'dashed · ' outline with 'hatch line · ' rules inside "
               "(dashed and rotated 45 degrees by the post-step); a consumed level ends in print marks (filled "
               "circles) — the two differ by pattern, not by lightness (AD-6)",
    "marker": "kit choice: board markers (step numbers, reading arrows, region names, violation flags) are caption "
              "text in a 'dashed · ' outline (board markers, not product UI)",
    "stamp": "kit choice: the PROPOSED stamp is the word in a 2 px color.border.strong badge (memo §0: a board that "
             "shows a recommendation carries a PROPOSED stamp)",
    "mark": "lo-fi: the mark (last price) row is a color.surface.selected fill with a 2 px color.text.primary edge "
            "and the word 'mark' (board marker)",
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


def deviate(line: str) -> None:
    NOTES.add("deviations", line)


def fallback(key: str) -> None:
    NOTES.add("fallbacks", FALLBACKS[key])


def ui(chars: str, why: str = "") -> str:
    """A UI label the memo does not write: drawn as an illustration, listed as a copy gap (PROPOSED; E21-D02 #440,
    E21-D03 #503 and E21-D04 #504 write the copy)."""
    NOTES.add("copy_gaps", f"\"{chars}\": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / "
                           f"E21-D04 #504 write the copy){' — ' + why if why else ''}")
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
            if tk.startswith("color.") and tk not in GREY:
                raise ValueError(f"{name!r}: {tk} is a hue token (wireframes are greyscale)")
            if tk == "opacity.disabled" or tk == "color.text.disabled":
                raise ValueError(f"{name!r}: {tk} is never bound on a T2 control (E09-D09)")
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
         HEADING_SM: (14, 1.2, False), HEADING_MD: (16, 1.2, False), NUM_SM: (11, 1.2, True), NUM: (13, 1.2, True),
         NUM_MD: (14, 1.2, True), NUM_LG: (16, 1.2, True)}


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



# --- the seeded synthetic BTCUSDT book (WORLD, seed 417). Every drawn size, price, count and time is derived here.
import random  # noqa: E402
from decimal import ROUND_HALF_EVEN, Decimal  # noqa: E402

SEED = ISSUE
SYM = "BTCUSDT"


def _fixture() -> tuple[Decimal, Decimal]:
    d = json.loads(_doc_bytes("fixture").decode("utf-8"))
    hits: list[tuple[Decimal, Decimal]] = []

    def rec(o: Any) -> None:
        if isinstance(o, dict):
            if o.get("symbol") == SYM:
                hits.append((Decimal(o["priceFilter"]["tickSize"]), Decimal(o["lotSizeFilter"]["qtyStep"])))
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)
    rec(d)
    if len(set(hits)) != 1:
        raise ValueError(f"fixture: {SYM} instrument rows {hits}")
    return hits[0]


TICK, QTY_STEP = _fixture()
MID0 = Decimal("70000.00")  # synthetic: the mark (last price) at t0; best bid = mark, best ask = mark + 1 tick
LEVELS = 500  # levels a side in the synthetic book (the deepest tier)
TIERS = (500, 200, 50)  # memo §0 board 05: 500 → 200 → 50
COL_MS = 100  # SCR-050 heatmap column = 100 ms (memo F-5)
UPDATE_MS = 50  # book updates at up to 20 Hz (memo F-2) = one update per 50 ms
TRAIL_COLS = 20  # drawn trail excerpt: the last 20 columns (2.0 s) of the 60 s live trail (AD-9)
TRAIL_S = 60  # AD-9's live default
HALF = 8  # ladder rows drawn: the mark row ± 8 (17 rows)
BAND = 2  # ILLUSTRATIVE edge band in rows (OQ-3: E21-D05 #505 owns the numbers; not a proposal)
BAND_FROM = HALF - BAND + 1  # a row is in the band when |offset - centre| >= BAND_FROM (the outer BAND rows)
RAMP = (Decimal("0.4"), Decimal("2"), Decimal("10"), Decimal("50"))  # log scale, x5 per step (kit illustration)
WALL = RAMP[2]  # a "wall" on these boards = a level of at least 10 BTC (kit illustration)
CONSUMED_OFF, PULLED_OFF = 3, -5  # the ask wall traded through, the bid wall pulled (offsets in ticks from MID0)
ZOOM_OUT = 5  # board 03's zoomed-out step: one row = 5 ticks (kit illustration of a `-` zoom)
OWN = ((-3, "Buy", Decimal("0.250"), "Limit"), (6, "Sell", Decimal("0.120"), "Limit"))  # synthetic own orders


def qz(v: Decimal) -> Decimal:
    return v.quantize(QTY_STEP, rounding=ROUND_HALF_EVEN)


def px(off: int) -> Decimal:
    return MID0 + off * TICK


def _deep_book() -> dict[str, list[tuple[int, Decimal]]]:
    """Per side, LEVELS levels [(offset in ticks from MID0, size)], nearest first; seeded gaps of 1-3 ticks; walls at
    fixed level indices (two inside 50, one inside 200, one beyond 200 a side)."""
    rng = random.Random(SEED)
    walls = {"bid": {2: 0, 5: 0, 120: 0, 310: 0}, "ask": {2: 0, 6: 0, 90: 0, 260: 0}}
    out: dict[str, list[tuple[int, Decimal]]] = {}
    for side, sign, first in (("bid", -1, 0), ("ask", 1, 1)):
        off, levels = first, []
        for i in range(LEVELS):
            if i:
                off += sign * (1 if i < 30 else rng.choice((1, 1, 2, 2, 3)))
            size = min(qz(Decimal(str(rng.lognormvariate(-0.7, 0.9)))), Decimal("8")) or QTY_STEP
            if i in walls[side]:
                size = qz(Decimal(str(rng.uniform(14, 60))))
            levels.append((off, size))
        out[side] = levels
    return out


BOOK = _deep_book()
SIZE0 = {off: (side, s) for side, lv in BOOK.items() for off, s in lv}  # offset -> (side, size) at t0
if SIZE0[CONSUMED_OFF][0] != "ask" or SIZE0[CONSUMED_OFF][1] < WALL or SIZE0[PULLED_OFF][0] != "bid" or \
        SIZE0[PULLED_OFF][1] < WALL:
    raise ValueError("world: the consumed / pulled walls are not walls at their offsets")


def _trail() -> tuple[list[dict[int, Decimal]], list[tuple[int, int, Decimal]], list[int]]:
    """TRAIL_COLS columns of the visible rows' sizes, the prints (column, offset, qty) and the mark per column.
    Columns 0-8 static; from column 9 the asks at +1 and +2 trade away and the +3 wall is traded through in four
    prints (columns 9-12); the -5 bid wall vanishes at column 11 with no print at its price (the pull)."""
    rng = random.Random(SEED + 1)
    book = {off: s for off, (_side, s) in SIZE0.items() if -ZOOM_OUT * (HALF + 1) <= off <= ZOOM_OUT * (HALF + 1)}
    cols, prints, marks, mark = [], [], [], 0
    wall = book[CONSUMED_OFF]
    cuts = sorted(rng.sample(range(1, int(wall / QTY_STEP)), 3))
    chunks = [qz(QTY_STEP * (b - a)) for a, b in zip([0, *cuts], [*cuts, int(wall / QTY_STEP)])]
    for c in range(TRAIL_COLS):
        if c == 9:
            for off in (1, 2):
                prints.append((c, off, book[off]))
                book[off] = Decimal(0)
            mark = 2
        if 9 <= c <= 12:
            q_ = chunks[c - 9]
            prints.append((c, CONSUMED_OFF, q_))
            book[CONSUMED_OFF] -= q_
            mark = CONSUMED_OFF
        if c == 11:
            book[PULLED_OFF] = Decimal(0)  # no print at this price: the pull
        cols.append(dict(book))
        marks.append(mark)
    return cols, prints, marks


TRAIL, PRINTS, MARKS = _trail()


def bucket(size: Decimal) -> int:
    """0 = below the first anchor (not drawn), 1..4 = the ramp steps."""
    return sum(1 for e in RAMP if size >= e)


def walk_marks() -> list[int]:
    """The mark per update (offset in ticks) for the centring strips: a seeded walk, one update per 50 ms, up to and
    including the first update that enters the edge band (|offset| >= BAND_FROM)."""
    rng = random.Random(SEED + 2)
    out = [0]
    while abs(out[-1]) < BAND_FROM:
        out.append(out[-1] + rng.choice((-1, 0, 1, 1, 2)))
        if len(out) > 400:
            raise ValueError("walk never reached the band")
    return out


WALK = walk_marks()


def tier_stats(tier: int) -> dict[str, Any]:
    """What one tier holds a side: the far price, ticks a side, cumulative depth and the walls inside."""
    out: dict[str, Any] = {}
    for side, lv in BOOK.items():
        inside = lv[:tier]
        out[side] = {"far": inside[-1][0], "ticks": abs(inside[-1][0] - lv[0][0]) + 1,
                     "depth": sum((s for _o, s in inside), Decimal(0)),
                     "walls": [(o, s) for o, s in inside if s >= WALL]}
    return out


def tier_loss(hi: int, lo: int) -> dict[str, Any]:
    """What a step from tier hi to tier lo loses a side: the walls beyond lo, the cumulative depth beyond lo and the
    heatmap rows outside lo (ticks between the two far prices)."""
    a, b = tier_stats(hi), tier_stats(lo)
    return {side: {"walls": [w for w in a[side]["walls"] if w not in b[side]["walls"]],
                   "depth": a[side]["depth"] - b[side]["depth"], "rows": a[side]["ticks"] - b[side]["ticks"]}
            for side in BOOK}


# --- formatting (U+2212 for minus)
MINUS = "−"


def price(v: Decimal) -> str:
    exp = -TICK.as_tuple().exponent  # type: ignore[operator]
    return f"{v:,.{exp}f}"


def size_fmt(v: Decimal) -> str:
    return f"{v:,.3f}"


def btc(v: Decimal) -> str:
    return f"{v:,.3f} BTC"


def anchor(v: Decimal) -> str:
    return f"{v.normalize():f}"


def ms_label(col: int) -> str:
    t = (col - (TRAIL_COLS - 1)) * COL_MS / 1000
    return "0.0 s" if t == 0 else f"{MINUS}{abs(t):.1f} s"
# --- frames, tables, annotations, the board
FRAME_PAD = 24


DATA_BOARDS = frozenset((2, 3, 4, 5, 6))  # boards that draw a chart reading from the world


def data_statement(nn: int) -> str:
    if nn not in DATA_BOARDS:
        return ("Data: none — every word on this board is memo text (or a board marker); no market data, account, key "
                "or balance. Research board: lo-fi, greyscale, dark only.")
    return (f"Data: synthetic only — a seeded {SYM} book (seed {SEED}): tick {TICK} and qty step {QTY_STEP} from the "
            f"recorded instrument fixture; mark {price(MID0)} at t0; {LEVELS} levels a side with seeded gaps; sizes, "
            f"walls, prints, the pull, the mark walk and the own orders are synthetic; the ramp anchors "
            f"{', '.join(anchor(e) for e in RAMP)} BTC and the {BAND}-row edge band are kit illustrations, not "
            f"proposals; no account identifier, key or balance. Research board: lo-fi, greyscale, dark only.")


def stamp(words: str = "PROPOSED") -> Node:
    fallback("stamp")
    return hbox(f"stamp · {words}", [text("words", words, LABEL, TEXT_1)],
                {"padX": INSET_SM, "radius": R_BADGE, "stroke": BORDER_STRONG, "strokeWidth": THICK,
                 "strokeAlign": "inner"}, h=20, note="memo §0: PROPOSED stamp")


def frame_header(fid: str, w_: int, framing: str, kind: str, proposed: bool) -> Node:
    return vbox("frame header", [
        hbox("title", [text("kind", kind, LABEL, TEXT_2), text("id", fid, LABEL, TEXT_1),
                       stamp() if proposed else None], {"gap": INSET_SM}, h=20),
        text("framing", framing, CAPTION, TEXT_3, w=w_ - 2 * FRAME_PAD)], {"gap": STACK_XS}, w=w_ - 2 * FRAME_PAD)


def frame(fid: str, kids: list[Node | None], w_: int, framing: str, *, slack: int = 32, kind: str = "RESEARCH",
          proposed: bool = False) -> Node:
    """One frame: header (kind, id, PROPOSED stamp) + the content, on color.surface.canvas, clipped; its height hugs
    the estimate + slack (rounded to 8)."""
    body = [frame_header(fid, w_, framing, kind, proposed), *kids]
    inner = vbox("probe", body, {"gap": STACK_LG}, w=w_)
    h = int(math.ceil((est_height(inner) + 2 * FRAME_PAD + slack) / 8) * 8)
    return vbox(frame_name(fid), body, {"fill": CANVAS, "pad": INSET_XL, "gap": STACK_LG, "clip": True}, w=w_, h=h,
                note=f"frame {fid}")


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


def frame_block(fid: str, lines: Iterable[str] = (), ads: Iterable[str] = (),
                fs: Iterable[str] = ()) -> tuple[str, list[str]]:
    if not any(fid in b.frames for b in BOARDS.values()):
        raise KeyError(f"{fid!r} is not a planned frame")
    return fid, [ad_line(a) for a in ads] + [f_line(f) for f in fs] + [x for x in lines if x]


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    b = BOARDS[nn]
    head = [f"memo §0 L{b.line}: {b.shows}", f"Frames: {', '.join(b.frames)}",
            "Theme: dark only — greyscale, annotated, no visual design, no twin (memo §0, BQ-13)",
            f"Export: {b.export}", data_statement(nn), *board_lines]
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
    h = int(math.ceil((max(bottom + 24 + fh, MARGIN + ah) + MARGIN) / 8) * 8)
    if strict and nn in LIVE_ROOT_H:  # the live check's read-back: max(annotation end, footer end) + MARGIN
        if not bottom + 24 + MARGIN < LIVE_ROOT_H[nn] <= h:
            raise ValueError(f"board {nn:02d}: live root h {LIVE_ROOT_H[nn]} outside ({bottom + 24 + MARGIN}, {h}]")
        h = LIVE_ROOT_H[nn]
    if wd > PITCH_X - 200 or h > PITCH_Y - 200:
        raise ValueError(f"board {nn:02d}: {wd} x {h} crowds the {PITCH_X} x {PITCH_Y} pitch")
    x, y = grid_xy(nn)
    live(f"root {b.name!r} at ({x}, {y}): read back the name exactly after the first section call; size {wd} x {h}")
    live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px with 15 % slack) ends inside the "
         f"root (h {h}); raise the root's h to max(annotation end, footer end) + {MARGIN} if not")
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
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(path), "--components", str(COMPONENTS),
                          "--tokens", str(TOKENS_FILE)], capture_output=True, text=True, timeout=120, check=False)
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
    NOTES.add("sources", f"spec (memo) {DOCS['spec'][0]} md5 {DOCS['spec'][1]} at {HEAD} (§0 L{b.line})")
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
           summary or f"Board {nn:02d} of eight (memo §0 L{b.line}: {b.shows}). Grid ({x}, {y}); {sh['board']['w']} x "
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
    p.write_text(s, encoding="utf-8")
    if IN_REPO and sp.parent == CAP_DIR.resolve():  # the committed sidecar beside the kit
        (KIT_DIR / p.name).write_text(s, encoding="utf-8")
    return p


def pack_sheet(sheet_path: Path, out_dir: Path = V4_DIR) -> Path:
    """Pack with the repo packer (compact.py) into out_dir/<same name>; compactOf = the pack source's absolute path +
    its sha256 (mkcall4 renders only while that file is unchanged); check the sha256, every packed section <=
    PACKED_MAX bytes, mkcall4 count == the section count, and no banned string outside compactOf. In a checkout the
    committed v4/ copy then carries the bare raw-sheet name in compactOf.file (the sha256 beside it unchanged); to
    render, pack again outside the repository (BUILD.md)."""
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
    sh = json.loads(dst.read_text(encoding="utf-8"))
    if sh.get("compactOf") != {"file": str(src), "sha256": hashlib.sha256(src.read_bytes()).hexdigest()}:
        raise RuntimeError(f"{dst.name}: compactOf {sh.get('compactOf')!r} is not {src} + its sha256")
    cnt = subprocess.run([sys.executable, "-I", "-B", str(MKCALL), str(dst), "count"], capture_output=True, text=True,
                         timeout=120, check=False)
    if cnt.returncode != 0 or cnt.stdout.strip() != str(len(sh["sections"])):
        raise RuntimeError(f"{dst.name}: mkcall4 count {cnt.stdout.strip()!r} rc {cnt.returncode} != "
                           f"{len(sh['sections'])}: {cnt.stderr.strip()[-300:]}")
    big = [(s["node"]["name"], n) for s in sh["sections"]
           if (n := len(json.dumps(s, ensure_ascii=False, separators=(",", ":")).encode())) > PACKED_MAX]
    if big:
        raise RuntimeError(f"{dst.name}: packed sections over {PACKED_MAX} B: {big[:5]}")
    banned = _scan_banned({k: v for k, v in sh.items() if k != "compactOf"})
    if banned:
        raise RuntimeError(f"{dst.name}: banned {banned}")
    if IN_REPO and out_dir == V4_DIR.resolve():
        raw = dst.read_text(encoding="utf-8")
        abs_field = json.dumps(str(src), ensure_ascii=False)
        if raw.count(abs_field) != 1:
            raise RuntimeError(f"{dst.name}: the pack source path occurs {raw.count(abs_field)} times")
        dst.write_text(raw.replace(abs_field, json.dumps(src.name, ensure_ascii=False)), encoding="utf-8")
        if json.loads(dst.read_text(encoding="utf-8"))["compactOf"] != {
                "file": src.name, "sha256": hashlib.sha256(src.read_bytes()).hexdigest()}:
            raise RuntimeError(f"{dst.name}: compactOf is not the bare name and sha256 of {src.name}")
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
    check(sorted(BOARDS) == list(range(1, 9)), "memo §0: eight boards 01-08, each PENDING or drawn as its export")
    check(PAGE == KEY and FILE_NAME == f"{KEY} boards", f"page {PAGE!r}, file {FILE_NAME!r}")
    check(EXPORT_DIR == "docs/design/research/img", f"export dir {EXPORT_DIR!r} (memo §0)")
    check(sum(len(b.frames) for b in BOARDS.values()) == 23, f"{sum(len(b.frames) for b in BOARDS.values())} frames")
    check(sorted(RQS) == [f"RQ{i}" for i in range(1, 6)], "§2: RQ1..RQ5")
    check(sorted(FINDINGS, key=lambda x: int(x[2:])) == [f"F-{i}" for i in range(1, 18)], "§3: F-1..F-17")
    check(all(c[1].startswith("(heuristic)") for c, _i in FINDINGS.values()), "§3: every finding (heuristic)")
    check(sorted(WALKS) == [f"W{i}" for i in range(1, 5)], "§4: W1..W4")
    check(sorted(ADS, key=lambda x: int(x[3:])) == [f"AD-{i}" for i in range(1, 11)], "§7: AD-1..AD-10")
    check(all(c[2].startswith("satisfies if") and c[3].startswith("violates if") for c, _i in ADS.values()),
          "§7: every AD has its satisfies / violates clause")
    check(sorted(KILLS) == [f"K{i}" for i in range(1, 6)] and sorted(PROBES) == [f"T{i}" for i in range(1, 8)],
          "§8 K1..K5, §10.2 T1..T7")
    check(len(AGENDA) == 10 and sorted(CONTRAS) == [f"C{i}" for i in range(1, 9)], "§10.4 ten steps, §12.1 C1..C8")
    check(str(TICK) == "0.10" and str(QTY_STEP) == "0.001", f"fixture {SYM} tick {TICK}, qty step {QTY_STEP}")
    on_grid = all((px(o) % TICK == 0) and s % QTY_STEP == 0 and s > 0 for lv in BOOK.values() for o, s in lv)
    check(on_grid and all(len(lv) == LEVELS for lv in BOOK.values()), "book: every price on the tick, size on the step")
    check(max(o for o, _s in BOOK["bid"]) < min(o for o, _s in BOOK["ask"]), "book: bids below asks")
    printed = sum((q_ for _c, o, q_ in PRINTS if o == CONSUMED_OFF), Decimal(0))
    check(printed == SIZE0[CONSUMED_OFF][1] and TRAIL[-1][CONSUMED_OFF] == 0,
          f"consumed wall {size_fmt(SIZE0[CONSUMED_OFF][1])} = Σ prints at its price {size_fmt(printed)}")
    check(not any(o == PULLED_OFF for _c, o, _q in PRINTS) and TRAIL[-1][PULLED_OFF] == 0 and
          TRAIL[0][PULLED_OFF] >= WALL, "pulled wall: gone with no print at its price")
    check(all(TRAIL[c][o] >= 0 for c in range(TRAIL_COLS) for o in TRAIL[c]), "trail sizes never negative")
    check(abs(WALK[-1]) >= BAND_FROM and all(abs(m) < BAND_FROM for m in WALK[:-1]),
          f"walk: {len(WALK) - 1} updates to the band (offset {WALK[-1]})")
    t5, t2, t0 = (tier_stats(t) for t in TIERS)
    check(all(t5[s]["ticks"] > t2[s]["ticks"] > t0[s]["ticks"] for s in BOOK), "tiers: 500 > 200 > 50 ticks a side")
    loss = tier_loss(500, 200)
    check(all(loss[s]["walls"] for s in BOOK), "500 → 200 loses at least one wall a side")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for k_, v in globals().items() if k_.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border)\.", v)]
    miss = sorted(set(u for u in used if u not in toks))
    check(not miss and GREY <= toks, f"kit tokens exist (missing {miss})")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: text("x", "y", color="color.status.danger.strong"),
                 lambda: rect("x", 1, 1, "color.env.live"), lambda: memo("not a memo string at all xyzzy")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError, LookupError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/', a hue token and a non-memo string refused")
    NOTES.reset()
    fid = BOARDS[1].frames[0]
    fr = frame(fid, [text("sample", memo("auto-follow default, free-scroll visible, centre lock a setting"), BODY,
                          TEXT_1)], 480, "self-test sample frame")
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
