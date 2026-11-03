"""E41-D01 (#1017) board kit: the research board and the SCR-093..096 lo-fi wireframes as ten cvsheet JSON sheets
for the per-set Penpot file "E41-D01 boards", page "E41-D01" (memo §0, Deviation 2).

Offline only. Spec (binding; every string comes from it): docs/design/research/e41-journal-review.md (the memo: §0
boards, §5 findings, §6 decisions, §7 frames, §7.1 copy deck), its session protocol and the `17` §1.6 journey, plus
the `14` SCR-093..096 entries the memo cites (state words) and `21` §3.7.2 (tag categories), all read by
repo-relative path and md5-pinned in DOCS (the kit refuses drifted bytes: re-read, re-check, re-pin): the memo, the
protocol, `17` and the fixture from the checkout; `14` and `21` with `git show` at the memo's base (DOCS_BASE), the text the
memo cites, because both moved on main after it.
The recorded instrument fixture gives the BTCUSDT (0.10) and ETHUSDT (0.01) ticks and the 0.001 qty step; every other
value is the seeded synthetic journal (seed 1017, WORLD below), and every P&L, R, count and rate is derived from it.

WIREFRAMES: greyscale only. Every colour bound is a neutral token (GREY below); a hue token (status, env, action,
focus ring, link, candle, ...) is refused by node(). Dark only, no twins (memo §0, BQ-15).

Checkout: the kit sits at docs/design/_tools/sheets/e41-d01/ in a checkout (REPO = four levels up), or anywhere with
CV_CHECKOUT naming the checkout. Raw sheets + .md go to CAP_DIR, packed sheets to V4_DIR (BUILD in build-notes.md).
Pipeline (one generator per board, gen/gen_NN.py; wireframe parts in gen/wf.py):
    frames = [frame(fid, kids, w), ...]; blocks = [frame_block(fid, lines), ...]
    build(nn, frames, blocks, cols) -> raw sheet (validator exit 0), .md (line 3 = the render line), packed sheet
Self-test: python3 -I -B e41d01kit.py selftest

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

KEY, EPIC, ISSUE = "E41-D01", "E41", 1017
KIT_DIR = Path(__file__).resolve().parent
_MEMO_PATH = "docs/design/research/e41-journal-review.md"


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / _MEMO_PATH).is_file():
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / _MEMO_PATH).is_file():
        raise SystemExit("e41d01kit: run inside a checkout or set CV_CHECKOUT to one")
    return Path(env).resolve()


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
DOCS_BASE = "46e6acd2ddf3835580a801ac9b143d32f4478090"  # the memo's "Read at" base (on main)
DOCS = {  # key -> (repo-relative path, md5): every read is md5-checked; DOCS_AT_BASE are read at DOCS_BASE
    "spec": (_MEMO_PATH, "f8c849aa9a46a3c9416f197d79eca321"),
    "protocol": ("docs/design/research/e41-d01-session-protocol.md", "01433dd72a698bca4453a45f12250544"),
    "journey": ("docs/plan/17-ux-diagrams.md", "0494186310c960cef92f3c614625db44"),
    "cat": ("docs/plan/14-screens-catalogue.md", "1ca288905451c9e5c495a0468c062641"),
    "schema": ("docs/plan/21-database-schema.md", "60a9ee1cef41b27a1f0524190b68f199"),
    "fixture": ("packages/fixtures/bybit/2026-10-05/rest/instruments_before.json", "edd9dd2a060c51bd4bd1450307728ddf"),
}
DOCS_AT_BASE = frozenset(("cat", "schema"))
HEAD = "the boards PR (§0 drawn, §12 As built)"  # where the spec md5 was pinned (the text PR's pin was dfa1e34c5)
REV = "r1"
PITCH_X, PITCH_Y = 7000, 5200  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80
# SHEET-FIX ALL (live check 2026-11-03): each root's h read back on the board as max(annotation end, footer end) + 80
# once Penpot laid the text out; the kit's estimate (15 % slack, 8 px steps) is the upper bound it must sit under.
LIVE_ROOT_H = {1: 2615, 2: 1595, 3: 2827, 4: 1356, 5: 2263, 6: 1487, 7: 2343, 8: 1851, 9: 2418, 10: 2995}
# Board 10's 2995 is 2923 + 72 (the padded legend strips move its frame bottom 2792 -> 2864; the footer still ends
# 27 px under it): predicted by the design-read fold, read back on the board by the redraw (2026-11-03).
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
    if k not in DOCS_AT_BASE:
        return (REPO / DOCS[k][0]).read_bytes()
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{DOCS_BASE}:{DOCS[k][0]}"], capture_output=True, timeout=60,
                         check=False)
    if res.returncode != 0:
        raise SystemExit(f"e41d01kit: {DOCS[k][0]} at {DOCS_BASE[:9]} is not in this checkout's objects")
    return res.stdout


def spec_md5_ok() -> dict[str, bool]:
    return {k: hashlib.md5(_doc_bytes(k)).hexdigest() == m for k, (_p, m) in DOCS.items()}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:
    raise SystemExit(f"e41d01kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
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


# --- registries parsed from the memo (spec), the `17` §1.6 journey, `14` and `21`
# the §0 line always names the page (a miss raises AttributeError at import): Match | None narrowed by hand
PAGE = re.search(r"Penpot page `([^`]+)`", LINES["spec"][L("Boards on the Penpot page `") - 1]).group(1)  # type: ignore[union-attr]
FILE_NAME = f"{KEY} boards"
S0 = L("## 0. Wireframe boards (Penpot)")
SLUGS = {1: "research-board", 2: "scr093-default", 3: "scr093-states", 4: "scr094-default",
         5: "scr094-context-states", 6: "scr095-default", 7: "scr095-states", 8: "scope-and-cohort",
         9: "scr096-tag-manager", 10: "keyboard-and-reflow"}
_V = " · "
KIT_FRAMES: dict[int, tuple[str, ...]] = {  # kit plan: §7's frames placed on §0's boards (self-test checks coverage)
    1: ("research/journey", "research/findings-to-decisions", "research/walkthroughs"),
    2: ("SCR-093/default", "SCR-093/bulk-tag", "SCR-093/export"),
    3: tuple(f"SCR-093/{s}" for s in ("loading", "empty", "partial", "reconciling", "no-match", "error",
                                      "viewer-write-disabled")),
    4: ("SCR-094/default",),
    5: tuple(f"SCR-094/{s}" for s in ("loading", "bar-only", "context-not-recorded", "pruned", "error")),
    6: ("SCR-095/default", "SCR-095/table-view"),
    7: tuple(f"SCR-095/{s}" for s in ("insufficient-sample", "low-bucket", "empty", "no-match", "loading", "error")),
    8: (f"SCR-093/default{_V}DEMO scope", f"SCR-095/default{_V}DEMO toggle on", f"SCR-095/default{_V}cohort controls"),
    9: tuple(f"SCR-096/{s}" for s in ("default", "create", "rename", "merge", "delete", "empty", "error")),
    10: (f"SCR-093/default{_V}keyboard order", f"SCR-096/default{_V}200 % reflow", f"SCR-093/export{_V}200 % reflow",
         f"SCR-096/default{_V}forced colours", f"SCR-093/export{_V}forced colours",
         f"SCR-096/default{_V}focus return", f"SCR-093/export{_V}focus return"),
}


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E41-D01 / 01 research-board"
    slug: str
    shows: str  # §0's cell, verbatim
    line: int  # §0 line
    frames: tuple[str, ...]
    theme: str = "dark"

    @property
    def export(self) -> str:
        return f"docs/design/{EPIC}/img/{KEY}-{self.nn:02d}-{self.slug}.png"

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"


def _boards() -> dict[int, Board]:
    out = {}
    for i, c in table("## 0. Wireframe boards (Penpot)"):
        nn = int(c[0])
        if plain(c[2]) != "PENDING" and not re.fullmatch(rf"drawn — {KEY}-{nn:02d}-{SLUGS[nn]}\.png, .*", plain(c[2])):
            raise ValueError(f"§0 L{i}: state {c[2]!r}")
        out[nn] = Board(nn, f"{KEY} / {nn:02d} {SLUGS[nn]}", SLUGS[nn], plain(c[1]), i, KIT_FRAMES[nn])
    return out


BOARDS = _boards()


def frame_name(fid: str) -> str:
    return fid.replace("/", SLASH)


FRAMES_7 = {plain(c[0]): [s.strip() for s in c[1].split("·")] for _i, c in table("## 7. Frames per screen (AC2)")}
NOT_DRAWN_LINE = L("Not drawn — the text is binding:")
COPY = {plain(c[0]): (plain(c[1]), i) for i, c in table("### 7.1 Copy deck")}


def deck(key: str, **kw: object) -> str:
    """A §7.1 string verbatim, its {placeholders} filled from the world; the key is noted."""
    s, ln = COPY[key]
    out = s.format(**kw) if kw else s
    if "{" in out:
        raise ValueError(f"{key}: unfilled placeholder in {out!r}")
    NOTES.add("copy_keys", f"{key} (§7.1 L{ln}): \"{s}\"")
    return out


@dataclass(frozen=True)
class WD:
    wid: str
    decision: str
    frame: str
    check: str
    owner: str
    line: int


WDS = {plain(c[0]): WD(plain(c[0]), plain(c[1]), plain(c[2]), plain(c[3]), plain(c[4]), i)
       for i, c in table("## 6. Wireframe decisions")}
FINDINGS = {plain(c[0]): (plain(c[1]), plain(c[2]), plain(c[3]), plain(c[5]), i) for i, c in table("## 5. Findings")}


def wd_line(wid: str) -> str:
    w = WDS[wid]
    return f"{wid} (§6 L{w.line}, PROPOSED; {w.frame}): {w.check}"


def _journey() -> list[tuple[str, list[tuple[str, int, str]]]]:
    """`17` §1.6's mermaid journey: [(section, [(step, score, actors)])]."""
    i = find_line("### 1.6 Review journey", "journey")
    ls, out = LINES["journey"], []
    j = find_line("```mermaid", "journey", i)
    while not ls[j].startswith("```"):
        t = ls[j].strip()
        if t.startswith("section "):
            out.append((t[8:], []))
        elif out and ":" in t:
            step, score, who = t.rsplit(":", 2)
            out[-1][1].append((step.strip(), int(score), who.strip()))
        j += 1
    return out


JOURNEY = _journey()
JOURNEY_LINE = find_line("### 1.6 Review journey", "journey")
JOURNEY_TITLE = next(x.strip()[6:] for x in LINES["journey"][JOURNEY_LINE:JOURNEY_LINE + 20]
                     if x.strip().startswith("title "))
ABANDON = [(i, [plain(x) for x in c]) for i, c in table("**Abandonment points**", "journey", JOURNEY_LINE)]
WALKS = [(i, LINES["spec"][i - 1][2:]) for i in range(L("## 4. Persona walkthroughs") + 1, L("## 5. Findings"))
         if LINES["spec"][i - 1].startswith("- **")]
CAT = find_line("### SCR-093 — Journal (trade list)", "cat")
TAG_CATEGORIES = tuple(re.findall(r"'([a-z]+)'", LINES["schema"][find_line("CONSTRAINT jtag_cat", "schema") - 1]))


def cat(chars: str, start_head: str = "### SCR-093") -> str:
    """A `14` string verbatim (raises if absent under start_head)."""
    s = find_line(start_head, "cat")
    ln = find_line(chars, "cat", s)
    NOTES.add("copy_keys", f"`14` L{ln}: \"{chars}\"")
    return chars


def memo(chars: str, start: int = 1) -> str:
    """A memo string verbatim (raises if absent)."""
    ln = L(chars, start)
    NOTES.add("copy_keys", f"memo L{ln}: \"{chars}\"")
    return chars


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
             "color.focus.ring (a hue); E41-D02 / D03 bind the ring token in hi-fi",
    "primary": "wireframe: a primary action is a color.surface.selected fill with a 2 px color.border.strong edge; "
               "no action hue",
    "scope": "wireframe: the LIVE / DEMO scope label is words in a bordered badge; color.env.* (hues) is not bound",
    "skeleton": "fallback: loading skeletons are color.neutral.subtle rects; static (reduced motion); no spinner",
    "t2stroke": "kit choice: every disabled T2 control (E09-D09 §2.1) keeps its label, a CMP-019 lock glyph and a dashed "
                "color.border.default stroke ('dashed · ' name, dashed by the post-step) where enabled controls have "
                "a solid color.border.strong stroke, so the state survives forced colours without the glyph",
    "marker": "kit choice: board markers (focus-order numbers, reading-order arrows, zoom notes) are caption text in "
              "a 'dashed · ' outline (board markers, not product UI)",
    "hidden": "kit choice: a visually hidden string (a chart's text summary for a screen reader, a status) is drawn "
              "as caption text in a 'dashed · ' outline",
    "chart": "lo-fi: charts are drawn from the derived series as rects (bars, steps) and 6 px marks; a scatter's "
             "outcome is a shape (win = circle, loss = square), never colour (`14` SCR-095 A11y)",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for the CMP-019 lock glyph",
    "context": "lo-fi: the CMP-181 context pane draws bars as hollow / filled rects from the seeded bar path (no "
               "candle hue); entry, exit and SL as labelled 1 px rules",
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
    """A UI label the memo does not write: drawn, and listed as a copy gap for E41-D02 / D03 (PROPOSED)."""
    NOTES.add("copy_gaps", f"\"{chars}\": kit label, not in §7.1 (PROPOSED; E41-D02 #1018 / E41-D03 #1081 write the "
                           f"copy){' — ' + why if why else ''}")
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


# --- the seeded synthetic journal (WORLD). Every displayed number is derived from these trades.
import random  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal  # noqa: E402

UTC = timezone.utc
SEED = ISSUE
RANGE = (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 30, 23, 59, 59, tzinfo=UTC))
YESTERDAY = datetime(2026, 10, 30, tzinfo=UTC)  # the review happens on the evening of 31 Oct (memo §4, P1)
RECORDING_FROM = datetime(2026, 10, 8, tzinfo=UTC)  # before it: no market context was recorded
TICKS_FROM = datetime(2026, 10, 16, tzinfo=UTC)  # before it: recorded ticks pruned, bars kept (bar replay)
TICK_GAP = (datetime(2026, 10, 22, 10, 0, tzinfo=UTC), datetime(2026, 10, 22, 10, 40, tzinfo=UTC))  # bars only
LIVE_ACCOUNTS = ("Account A", "Account B", "Account C")
DEMO_ACCOUNT = "Demo 1"
FEE_RATE = Decimal("0.00055")  # synthetic taker rate per side (declared; not a fixture value)
FUNDING_RATE = Decimal("0.0001")  # synthetic, at 00:00 / 08:00 / 16:00 UTC; longs pay
RISK_USDT = Decimal("50")  # synthetic risk per single trade


def _fixture() -> dict[str, tuple[Decimal, Decimal]]:
    d = json.loads(_doc_bytes("fixture").decode("utf-8"))
    out: dict[str, tuple[Decimal, Decimal]] = {}

    def rec(o: Any) -> None:
        if isinstance(o, dict):
            if o.get("symbol") in ("BTCUSDT", "ETHUSDT"):
                out[o["symbol"]] = (Decimal(o["priceFilter"]["tickSize"]), Decimal(o["lotSizeFilter"]["qtyStep"]))
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)
    rec(d)
    return out


INSTR = _fixture()
TICK = {s: t for s, (t, _q) in INSTR.items()}
QTY_STEP = {s: q for s, (_t, q) in INSTR.items()}
BASE = {"BTCUSDT": Decimal("70000"), "ETHUSDT": Decimal("2550")}
SPREAD = {"BTCUSDT": 2500, "ETHUSDT": 120}
TAGS = (  # (name, category, auto rule words or ""): categories are `21`'s enum
    ("breakout", "setup", ""), ("fade", "setup", ""), ("range-retest", "setup", ""), ("late-entry", "mistake", ""),
    ("moved-stop", "mistake", ""), ("fomo", "emotion", ""), ("us-open", "session", "by session: 13:00–15:59 UTC"),
    ("news", "general", ""))
RULE = "breakeven at +1R"  # synthetic rule name (attribution)


def q(v: Decimal, step: Decimal, rounding: str = ROUND_HALF_EVEN) -> Decimal:
    return (v / step).to_integral_value(rounding=rounding) * step


@dataclass
class Trade:
    no: int
    env: str  # LIVE | DEMO
    account: str
    symbol: str
    side: int  # +1 long, -1 short
    qty: Decimal
    entry: Decimal
    stop: Decimal
    exit: Decimal
    opened: datetime
    closed: datetime
    mae: Decimal
    mfe: Decimal
    mae_at: datetime
    mfe_at: datetime
    tags: list[tuple[str, bool]]  # (name, auto)
    managed: str
    group: str = ""

    @property
    def risk(self) -> Decimal:
        return abs(self.entry - self.stop)

    def r_of(self, px: Decimal) -> Decimal:
        return q(self.side * (px - self.entry) / self.risk, Decimal("0.01"))

    @property
    def r(self) -> Decimal:
        return self.r_of(self.exit)

    @property
    def gross(self) -> Decimal:
        return q(self.side * (self.exit - self.entry) * self.qty, Decimal("0.01"))

    @property
    def fees(self) -> Decimal:
        return q(FEE_RATE * (self.entry + self.exit) * self.qty, Decimal("0.01"))

    @property
    def funding(self) -> Decimal:
        n = sum(1 for h in range(int((self.closed - self.opened).total_seconds() // 3600) + 2)
                if (t := (self.opened.replace(minute=0, second=0) + timedelta(hours=h))) > self.opened
                and t <= self.closed and t.hour % 8 == 0)
        return q(-self.side * FUNDING_RATE * self.entry * self.qty * n, Decimal("0.01"))

    @property
    def net(self) -> Decimal:
        return self.gross - self.fees + self.funding

    @property
    def hold(self) -> timedelta:
        return self.closed - self.opened

    @property
    def context(self) -> str:
        if self.opened < RECORDING_FROM:
            return "not recorded"
        if self.opened < TICKS_FROM:
            return "pruned"
        if self.opened < TICK_GAP[1] and self.closed > TICK_GAP[0]:
            return "bar-only"
        return "recorded"


def _price(rng: random.Random, sym: str) -> Decimal:
    return q(BASE[sym] + Decimal(str(round(rng.uniform(-SPREAD[sym], SPREAD[sym]), 4))), TICK[sym])


_R_DRAW = (-1, -1, -1, -1, Decimal("-0.6"), Decimal("-0.3"), Decimal("0.4"), Decimal("0.9"), Decimal("1.3"),
           Decimal("1.8"), Decimal("2.2"), Decimal("2.6"), Decimal("3.1"))


def _trade(rng: random.Random, no: int, env: str, account: str, opened: datetime, *, sym: str | None = None,
           side: int | None = None, r: Decimal | None = None, hold_min: int | None = None, news: bool = False) -> Trade:
    sym = sym or ("BTCUSDT" if rng.random() < 0.6 else "ETHUSDT")
    side = side or rng.choice((1, -1))
    entry = _price(rng, sym)
    dist = q(entry * Decimal(str(round(rng.uniform(0.004, 0.009), 5))), TICK[sym])
    stop = entry - side * dist
    rr = Decimal(r if r is not None else rng.choice(_R_DRAW))
    if rr != -1:
        rr += Decimal(str(round(rng.uniform(-0.1, 0.1), 2)))
    exit_ = q(entry + side * rr * dist, TICK[sym])
    qty = q(RISK_USDT / dist, QTY_STEP[sym], ROUND_DOWN)
    hold = timedelta(minutes=hold_min if hold_min is not None else rng.randrange(6, 300))
    closed = opened + hold
    mae_r = -Decimal(1) if rr == -1 else -Decimal(str(round(rng.uniform(0.1, 0.9), 2)))
    mae_r = min(mae_r, rr) if rr < 0 else mae_r
    mfe_r = max(rr, Decimal(0)) + Decimal(str(round(rng.uniform(0.05, 0.8), 2)))
    t1, t2 = sorted(rng.uniform(0.05, 0.95) for _ in range(2))
    first_mae = rr >= 0
    mae_at = closed if rr == -1 else opened + hold * (t1 if first_mae else t2)  # a stopped trade's MAE is its exit
    mfe_at = opened + hold * (t2 if first_mae else t1)
    tags = [(rng.choice(("breakout", "fade", "range-retest")), False)]
    if rng.random() < 0.2:
        tags.append((rng.choice(("late-entry", "moved-stop")), False))
    if rng.random() < 0.15:
        tags.append(("fomo", False))
    if news:
        tags.append(("news", False))
    if 13 <= opened.hour <= 15:
        tags.append(("us-open", True))
    managed = f"rule: {RULE}" if rng.random() < 0.3 else "manual"
    return Trade(no, env, account, sym, side, qty, entry, stop, exit_, opened, closed,
                 q(entry + side * mae_r * dist, TICK[sym]), q(entry + side * mfe_r * dist, TICK[sym]),
                 mae_at.replace(microsecond=0), mfe_at.replace(microsecond=0), tags, managed)


def _journal() -> list[Trade]:
    rng = random.Random(SEED)
    out: list[Trade] = []
    forced_gap = False
    for i in range(39):
        day = 30 if i >= 37 else 1 + (i * 29) // 37
        opened = datetime(2026, 10, day, rng.randrange(0, 24) if i < 37 else 6 + 3 * (i - 37), rng.randrange(60),
                          rng.randrange(60), tzinfo=UTC)
        kw: dict[str, Any] = {}
        if day == 22 and not forced_gap:  # one trade spans the tick gap: its context is bars only
            opened, forced_gap, kw = datetime(2026, 10, 22, 9, 52, 14, tzinfo=UTC), True, {"hold_min": 31}
        out.append(_trade(rng, 0, "LIVE", rng.choice(LIVE_ACCOUNTS), opened, news=i in (5, 17, 29), **kw))
    lead = _trade(rng, 0, "LIVE", LIVE_ACCOUNTS[0], datetime(2026, 10, 30, 14, 32, 5, tzinfo=UTC), sym="BTCUSDT",
                  side=1, r=Decimal(-1), hold_min=35)
    lead.closed += timedelta(seconds=36)
    lead.mae_at = lead.closed  # stopped: the MAE is the exit
    lead.tags = [("breakout", False), ("late-entry", False), ("us-open", True)]
    lead.managed, lead.group = "manual", "G-1"
    for acct, share in zip(LIVE_ACCOUNTS, (Decimal(1), Decimal("0.6"), Decimal("0.4"))):
        leg = Trade(**{**lead.__dict__, "account": acct,
                       "qty": q(RISK_USDT * share / lead.risk, QTY_STEP["BTCUSDT"], ROUND_DOWN),
                       "tags": list(lead.tags)})
        out.append(leg)
    for i in range(12):
        opened = datetime(2026, 10, 20 + (i * 10) // 11, rng.randrange(0, 24), rng.randrange(60), rng.randrange(60),
                          tzinfo=UTC)
        out.append(_trade(rng, 0, "DEMO", DEMO_ACCOUNT, opened))
    out.sort(key=lambda t: (t.closed, t.account))
    for n, t in enumerate(out):
        t.no = 2001 + n
    return out


JOURNAL = _journal()


def trades(env: str = "LIVE", *, accounts: Iterable[str] | None = None, symbol: str | None = None,
           tag: str | None = None, frm: datetime = RANGE[0], to: datetime = RANGE[1]) -> list[Trade]:
    """The server's filtered read: one row per account (aggregate rows never exist here, WD-9), newest first."""
    acc = set(accounts) if accounts is not None else None
    rows = [t for t in JOURNAL if t.env == env and frm <= t.closed <= to and (acc is None or t.account in acc)
            and (symbol is None or t.symbol == symbol) and (tag is None or tag in [n for n, _a in t.tags])]
    return sorted(rows, key=lambda t: (t.closed, t.no), reverse=True)


GROUP = [t for t in JOURNAL if t.group == "G-1"]
LOSER = GROUP[0]  # yesterday's losing trade, opened on SCR-094 (Account A's leg)


@dataclass(frozen=True)
class Stats:
    n: int
    wins: int
    win_rate: Decimal  # percent, 0 dp
    expectancy: Decimal  # mean R, 2 dp
    net: Decimal
    profit_factor: Decimal | None
    max_dd: Decimal
    avg_hold: timedelta
    win_streak: int
    loss_streak: int


def stats(rows: list[Trade]) -> Stats:
    rows = sorted(rows, key=lambda t: (t.closed, t.no))
    n = len(rows)
    wins = sum(1 for t in rows if t.net > 0)
    gw = sum((t.net for t in rows if t.net > 0), Decimal(0))
    gl = -sum((t.net for t in rows if t.net < 0), Decimal(0))
    eq, peak, dd = Decimal(0), Decimal(0), Decimal(0)
    cur_w = cur_l = best_w = best_l = 0
    for t in rows:
        eq += t.net
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        cur_w, cur_l = (cur_w + 1, 0) if t.net > 0 else (0, cur_l + 1)
        best_w, best_l = max(best_w, cur_w), max(best_l, cur_l)
    return Stats(n, wins, q(Decimal(100) * wins / n, Decimal(1)) if n else Decimal(0),
                 q(sum((t.r for t in rows), Decimal(0)) / n, Decimal("0.01")) if n else Decimal(0),
                 sum((t.net for t in rows), Decimal(0)), q(gw / gl, Decimal("0.01")) if gl else None, dd,
                 sum((t.hold for t in rows), timedelta()) / n if n else timedelta(), best_w, best_l)


def equity(rows: list[Trade]) -> list[tuple[Trade, Decimal, Decimal]]:
    """(trade, cumulative net, drawdown from the running peak), oldest first."""
    out, eq, peak = [], Decimal(0), Decimal(0)
    for t in sorted(rows, key=lambda t: (t.closed, t.no)):
        eq += t.net
        peak = max(peak, eq)
        out.append((t, eq, peak - eq))
    return out


R_BUCKETS = (("≤ −1R", None, Decimal(-1)), ("−1R to 0R", Decimal(-1), Decimal(0)), ("0R to 1R", Decimal(0), Decimal(1)),
             ("1R to 2R", Decimal(1), Decimal(2)), ("≥ 2R", Decimal(2), None))


def r_bucket(r: Decimal) -> int:
    if r <= -1:
        return 0
    if r < 0:
        return 1
    return 2 if r < 1 else 3 if r < 2 else 4


def breakdown(rows: list[Trade], key: str) -> list[tuple[str, list[Trade]]]:
    """Rows grouped by tag / symbol / account / hour block, in a fixed order; a trade with two tags is in both."""
    groups: dict[str, list[Trade]] = {}
    for t in rows:
        if key == "tag":
            ks = [n for n, _a in t.tags]
        elif key == "hour":
            h = t.opened.hour // 4 * 4
            ks = [f"{h:02d}:00–{h + 3:02d}:59"]
        else:
            ks = [getattr(t, key)]
        for k_ in ks:
            groups.setdefault(k_, []).append(t)
    order = [n for n, _c, _a in TAGS] if key == "tag" else sorted(groups)
    return [(k_, groups[k_]) for k_ in order if k_ in groups]


def no_match_filter() -> tuple[str, str]:
    """The first (symbol, tag) pair, in fixed order, with no LIVE trade in the range (SCR-093 / SCR-095 no-match)."""
    for sym in ("BTCUSDT", "ETHUSDT"):
        for name, _c, _a in TAGS:
            if not trades(symbol=sym, tag=name):
                return sym, name
    raise LookupError("every (symbol, tag) pair has a trade: pick another no-match filter")


# --- formatting (signed, unit-labelled; U+2212 for minus)
MINUS = "−"


def signed(v: Decimal, unit: str = "") -> str:
    s = f"{abs(v):,.2f}"
    return f"{'+' if v > 0 else MINUS if v < 0 else ''}{s}{unit}"


def usdt(v: Decimal) -> str:
    return signed(v, " USDT")


def rfmt(v: Decimal) -> str:
    return signed(v, "R")


def price(v: Decimal, sym: str) -> str:
    exp = -TICK[sym].as_tuple().exponent  # type: ignore[operator]
    return f"{v:,.{exp}f}"


def qtyfmt(v: Decimal) -> str:
    return f"{v:.3f}"


def side_word(t: Trade) -> str:
    return "Long" if t.side > 0 else "Short"


def dt_short(t: datetime) -> str:
    return f"{t.day} {t.strftime('%b %H:%M')}"


def dt_long(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S") + " UTC"


def day_range(a: datetime, b: datetime) -> str:
    return f"{a.day} {a.strftime('%b %Y')} – {b.day} {b.strftime('%b %Y')}"


def hold_fmt(d: timedelta) -> str:
    m = int(d.total_seconds() // 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def pct(v: Decimal) -> str:
    return f"{v} %"


# --- frames, tables, annotations, the board
FRAME_PAD = 24


def data_statement() -> str:
    live_, demo_ = trades(), trades("DEMO")
    return (f"Data: synthetic only — a seeded journal (seed {SEED}): {len(live_)} LIVE trades on "
            f"{', '.join(LIVE_ACCOUNTS)} and {len(demo_)} DEMO trades on {DEMO_ACCOUNT}, {day_range(*RANGE)}; BTCUSDT "
            f"(tick {TICK['BTCUSDT']}) and ETHUSDT (tick {TICK['ETHUSDT']}), qty step {QTY_STEP['BTCUSDT']}, from the "
            f"recorded instrument fixture; prices synthetic; P&L, R, fees, counts and rates derived from the trades "
            f"(fee rate {(FEE_RATE * 100).normalize()} % a side and funding {(FUNDING_RATE * 100).normalize()} % per "
            f"8 h are synthetic); no "
            f"account identifier, key or balance. Wireframe: lo-fi, greyscale, dark only.")


def frame_header(fid: str, w_: int, framing: str) -> Node:
    return vbox("frame header", [
        hbox("title", [text("kind", "WIREFRAME", LABEL, TEXT_2), text("id", fid, LABEL, TEXT_1)], {"gap": INSET_SM},
             h=16),
        text("framing", framing, CAPTION, TEXT_3, w=w_ - 2 * FRAME_PAD)], {"gap": STACK_XS}, w=w_ - 2 * FRAME_PAD)


def frame(fid: str, kids: list[Node | None], w_: int, framing: str, *, slack: int = 32) -> Node:
    """One state frame: header + the wireframe, on color.surface.canvas, clipped; its height hugs the estimate +
    slack (rounded to 8)."""
    body = [frame_header(fid, w_, framing), *kids]
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


def frame_block(fid: str, lines: Iterable[str] = (), wds: Iterable[str] = ()) -> tuple[str, list[str]]:
    if not any(fid in b.frames for b in BOARDS.values()):
        raise KeyError(f"{fid!r} is not a planned frame")
    return fid, [wd_line(w) for w in wds] + [x for x in lines if x]


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    b = BOARDS[nn]
    head = [f"memo §0 L{b.line}: {b.shows}", f"Frames: {', '.join(b.frames)}",
            "Theme: dark only — lo-fi greyscale wireframe, no twin (memo §0, BQ-15)", f"Export: {b.export}",
            data_statement(), *board_lines]
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
    foot = [text("footer · data statement", data_statement(), CAPTION, TEXT_2, x=MARGIN, y=bottom + 24,
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
    for k_, why in (("protocol", "the session protocol: stimuli, §4a prompts"), ("journey", "`17` §1.6 journey"),
                    ("cat", "`14` SCR-093..096 state words the memo cites"), ("schema", "`21` §3.7.2 tag categories"),
                    ("fixture", f"BTCUSDT tick {TICK['BTCUSDT']}, ETHUSDT tick {TICK['ETHUSDT']}, qty step")):
        at = f" at {DOCS_BASE[:9]}" if k_ in DOCS_AT_BASE else ""
        NOTES.add("sources", f"{DOCS[k_][0]}{at} md5 {DOCS[k_][1]} ({why})")
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
           summary or f"Board {nn:02d} of ten (memo §0 L{b.line}: {b.shows}). Grid ({x}, {y}); {sh['board']['w']} x "
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
    check(sorted(BOARDS) == list(range(1, 11)), "memo §0: ten boards 01-10, each PENDING or drawn as its export")
    check(PAGE == KEY and FILE_NAME == f"{KEY} boards", f"page {PAGE!r}, file {FILE_NAME!r}")
    planned = {f.split(" · ")[0] for b in BOARDS.values() for f in b.frames}
    want = {f"{s}/{x}" for s, xs in FRAMES_7.items() for x in xs}
    missing = sorted(want - planned)
    check(missing == ["SCR-093/export-failed"], f"every §7 frame drawn but the export-failed toast (missing {missing})")
    nd = LINES["spec"][NOT_DRAWN_LINE - 1]
    check("SCR-093/export-failed" in nd.split(". ")[0] and "SCR-093/viewer-write-disabled" not in nd.split(". ")[0],
          f"§0 L{NOT_DRAWN_LINE} names export-failed as the only not-drawn frame (board 03 draws viewer-write-disabled)")
    check(sum(len(b.frames) for b in BOARDS.values()) == 44, f"{sum(len(b.frames) for b in BOARDS.values())} frames")
    check(sorted(COPY) == sorted(("scope.live", "scope.demo", "caveat.sample", "caveat.bucket", "empty.range",
                                  "empty.filter", "context.none", "context.bars", "context.pruned", "export.confirm",
                                  "export.failed")), f"§7.1: {len(COPY)} keys")
    check(sorted(WDS, key=lambda x: int(x[3:])) == [f"WD-{i}" for i in range(1, 15)], "§6: WD-1..WD-14")
    check(sorted(FINDINGS) == [f"F-{i}" for i in range(1, 9)], "§5: F-1..F-8")
    check(len(JOURNEY) == 6 and len(ABANDON) == 5 and len(WALKS) == 3, "`17` §1.6: 6 sections, 5 abandonment rows; 3 "
                                                                      "walkthroughs")
    check(TAG_CATEGORIES == ("setup", "mistake", "emotion", "session", "general"), "`21` tag categories")
    check(str(TICK["BTCUSDT"]) == "0.10" and str(TICK["ETHUSDT"]) == "0.01" and str(QTY_STEP["BTCUSDT"]) == "0.001",
          "fixture ticks 0.10 / 0.01, qty step 0.001")
    live_, demo_ = trades(), trades("DEMO")
    check((len(live_), len(demo_)) == (42, 12), f"world: {len(live_)} LIVE, {len(demo_)} DEMO trades")
    on_grid = all(x % TICK[t.symbol] == 0 for t in JOURNAL for x in (t.entry, t.exit, t.stop, t.mae, t.mfe)) and \
        all(t.qty % QTY_STEP[t.symbol] == 0 and t.qty > 0 for t in JOURNAL)
    check(on_grid, "every price on its tick, every qty on the step")
    check(len(GROUP) == 3 and len({(t.entry, t.exit, t.stop) for t in GROUP}) == 1 and
          {t.account for t in GROUP} == set(LIVE_ACCOUNTS) and LOSER.r == -1, "group G-1: 3 legs, one per account, "
                                                                              "same prices, stopped at −1R")
    check(all(t.r_of(t.mae) <= min(t.r, 0) and t.r_of(t.mfe) >= max(t.r, 0) for t in JOURNAL),
          "MAE ≤ min(R, 0) and MFE ≥ max(R, 0) on every trade")
    check(all(t.mae_at == t.closed for t in JOURNAL if t.r == -1), "a stopped trade's MAE is at its exit")
    ctx = {c: sum(1 for t in live_ if t.context == c) for c in ("not recorded", "pruned", "bar-only", "recorded")}
    check(all(ctx.values()), f"context classes all occur {ctx}")
    low = [n for n, r in breakdown(live_, "tag") if len(r) < 5]
    check("news" in low and len(trades(tag="news")) == 3, f"low buckets {low}: 'news' n = 3 (WD-4's example)")
    s = stats(live_)
    check(s.net == sum((t.net for t in live_), Decimal(0)) == equity(live_)[-1][1], "net = Σ rows = equity end")
    check(no_match_filter() is not None and not trades(symbol=no_match_filter()[0], tag=no_match_filter()[1]),
          f"no-match filter {no_match_filter()}")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for k_, v in globals().items() if k_.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border)\.", v)]
    miss = sorted(set(u for u in used if u not in toks))
    check(not miss and GREY <= toks, f"kit tokens exist (missing {miss})")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: text("x", "y", color="color.status.danger.strong"),
                 lambda: rect("x", 1, 1, "color.env.live"), lambda: text("x", "y", color="color.text.disabled")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/', a hue token and a T2-forbidden token refused")
    NOTES.reset()
    fid = BOARDS[2].frames[0]
    fr = frame(fid, [text("sample", deck("scope.live"), BODY, TEXT_1)], 480, "self-test sample frame")
    ann = annotations(2, [frame_block(fid, ["self-test"])], board_lines=["Self-test sheet, not a board of the set"])
    path = write_sheet(2, [fr], ann, 1, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False)
    check(path.exists(), f"validator exit 0: {path.name}")
    md = write_md(2, path, summary="Self-test sheet (one sample frame); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    check(l3 == md_line3(2) and f"page `{PAGE}`" in l3 and l3.endswith("theme dark."), f"md line 3: {l3}")
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
