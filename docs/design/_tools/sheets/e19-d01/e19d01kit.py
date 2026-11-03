"""E19-D01 (#382) board kit: the nine research boards of the profiles UX memo as cvsheet JSON sheets for the Penpot
file "E19-D01 boards", page "E19-D01" (memo §0, BQ-15: nine greyscale boards, no light twins).

Offline only. Spec (binding; every string comes from it): docs/design/research/e19-profiles.md (the memo: §0 boards,
§2 RQs and hypotheses, §3 findings, §4 worked numbers, §5 levels, §6 modes and honesty states, §7 PD-1..PD-8, §8
competitive review, §9 C / G / A / OQ rows, §10 protocol, §11 traceability), plus `05` §6's profile table (the
columns A-6 extends), both read by repo-relative path and md5-pinned in DOCS (the kit refuses drifted bytes: re-read,
re-check, re-pin): the memo and the fixture from the checkout; `05` with `git show` at the memo's base (DOCS_BASE), the
text the memo cites, because it moved on main after it. The recorded instrument fixture gives the BTCUSDT tick (0.10) and qty step (0.001);
every chart value is the seeded synthetic world (seed 382, WORLD below), and every POC, VAH, VAL, node, count and time
on a board is derived from it.

RESEARCH BOARDS: greyscale only. Every colour bound is a neutral token (GREY below); a hue token is refused by node().
Dark only, no twins (memo §0, BQ-15).

Checkout: the kit sits at docs/design/_tools/sheets/e19-d01/ in a checkout (REPO = four levels up), or anywhere with
CV_CHECKOUT naming the checkout. Raw sheets + .md go to CAP_DIR, packed sheets to V4_DIR (BUILD.md).
Pipeline (one generator per board, gen/gen_NN.py; drawing parts in gen/rb.py):
    frames = [frame(fid, kids, w), ...]; blocks = [frame_block(fid, lines), ...]
    build(nn, frames, blocks, cols) -> raw sheet (validator exit 0), .md (line 3 = the render line), packed sheet
Self-test: python3 -I -B e19d01kit.py selftest

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (frame ids use U+2215); no local path, host, URL
or agent name anywhere in a sheet (BANNED); table cells carry 8 px inner padding a side; every frame has a caption.
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

KEY, EPIC, ISSUE = "E19-D01", "E19", 382
KIT_DIR = Path(__file__).resolve().parent
_MEMO_PATH = "docs/design/research/e19-profiles.md"


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / _MEMO_PATH).is_file():
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / _MEMO_PATH).is_file():
        raise SystemExit("e19d01kit: run inside a checkout or set CV_CHECKOUT to one")
    return Path(env).resolve()


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
DOCS_BASE = "ca49e693ae45512d77dbf7e16daf15dea79775a2"  # the memo's "Inputs pinned" base (on main)
DOCS = {  # key -> (repo-relative path, md5): every read is md5-checked; DOCS_AT_BASE are read at DOCS_BASE
    "spec": (_MEMO_PATH, "d4e666a3f87a41724547a89a1615d062"),
    "a11y": ("docs/plan/05-accessibility-standard.md", "16c60e646337d48dac83c9fb46f8a239"),
    "fixture": ("packages/fixtures/bybit/2026-10-05/rest/instruments_before.json", "edd9dd2a060c51bd4bd1450307728ddf"),
}
DOCS_AT_BASE = frozenset(("a11y",))
HEAD = "the boards PR (§0 drawn, §13 As built)"  # where the spec md5 was pinned (the text PR's pin was 949755375)
REV = "r1"
PITCH_X, PITCH_Y = 7000, 5200  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80
# SHEET-FIX ALL (live check 2026-11-03): each root's h read back on the board as max(annotation end, footer end) + 80
# once Penpot laid the text out; the kit's estimate (15 % slack, 8 px steps) is the upper bound it must sit under.
LIVE_ROOT_H = {1: 1664, 2: 1368, 3: 1376, 4: 1768, 5: 932, 6: 1095, 7: 847, 8: 1912, 9: 2956}
ANN_W = 400
ANN_TEXT_W = ANN_W - 32
SLASH = "∕"  # U+2215 stands for "/" in node names (Penpot splits names on "/")
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts, URLs and agent part names never belong in a sheet (the bare role word "orchestrator" the memo
# uses is allowed; the coordinator's part name is not); the words are hex here so this file carries none
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "636c61756465", "68747470", "7777772e", "2d6f7263686573747261746f72")) + r"|wt/\d|\b"
    + bytes.fromhex("616e76696c").decode() + r"\b", re.I | re.DOTALL)


def _doc_bytes(k: str) -> bytes:
    if k not in DOCS_AT_BASE:
        return (REPO / DOCS[k][0]).read_bytes()
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{DOCS_BASE}:{DOCS[k][0]}"], capture_output=True, timeout=60,
                         check=False)
    if res.returncode != 0:
        raise SystemExit(f"e19d01kit: {DOCS[k][0]} at {DOCS_BASE[:9]} is not in this checkout's objects")
    return res.stdout


def spec_md5_ok() -> dict[str, bool]:
    return {k: hashlib.md5(_doc_bytes(k)).hexdigest() == m for k, (_p, m) in DOCS.items()}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:
    raise SystemExit(f"e19d01kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")
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


def table_head(head: str, doc: str = "spec", start: int = 1) -> list[str]:
    """The header cells of the first markdown table after the line containing head (emphasis dropped)."""
    i = find_line(head, doc, start)
    ls = LINES[doc]
    while not ls[i].startswith("|"):
        i += 1
    return [c.replace("**", "").strip() for c in cells(ls[i])]


def plain(s: str) -> str:
    return re.sub(r"\*\*|`", "", s).strip()




# --- registries parsed from the memo (spec) and `05` §6 (never typed: a re-worded memo fails the parse)
S0 = L("## 0. Research boards (Penpot)")
_S0_TEXT = LINES["spec"][S0 + 1]
FILE_NAME = re.search(r"Penpot file `([^`]+)`", _S0_TEXT).group(1)  # type: ignore[union-attr]
PAGE = re.search(r"on the page `([^`]+)`", _S0_TEXT).group(1)  # type: ignore[union-attr]
EXPORT_PATTERN = re.search(r"exported to `([^`]+)`", _S0_TEXT).group(1)  # type: ignore[union-attr]
_V = " · "
KIT_FRAMES: dict[int, tuple[str, ...]] = {  # kit plan: the frames each §0 board carries (self-test checks the count)
    1: ("research/questions-hypotheses", "research/method-and-limits"),
    2: ("competitive/matrix", "competitive/schematics"),
    3: ("modes/vocabulary-map", "modes/defaults-and-switcher"),
    4: ("levels/ladder", "levels/in-situ-greyscale"),
    5: ("developing/as-of", "developing/final"),
    6: ("status/approximated-session", "status/partial-composite", "status/header-slot"),
    7: ("density/row-ladder", "density/compact-docked", "density/dense-overlay"),
    8: ("decisions/pd-1-to-pd-8", "decisions/traceability"),
    9: ("protocol/tasks", "protocol/rotation-and-rule", "protocol/table-alternative"),
}


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E19-D01 / 01 questions-hypotheses" (§0 verbatim)
    slug: str
    shows: str  # §0's content cell, verbatim
    line: int  # §0 line
    frames: tuple[str, ...]
    theme: str = "dark"

    @property
    def export(self) -> str:
        return EXPORT_PATTERN.replace("NN", f"{self.nn:02d}").replace("<slug>", self.slug)

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"


def _boards() -> dict[int, Board]:
    out = {}
    for i, c in table("## 0. Research boards (Penpot)"):
        nn, name = int(c[0]), plain(c[1])
        if plain(c[3]) != "PENDING" and not re.fullmatch(rf"drawn — {KEY}-{nn:02d}-[a-z0-9-]+\.png, .*", plain(c[3])):
            raise ValueError(f"§0 L{i}: state {c[3]!r}")
        m = re.fullmatch(rf"{re.escape(KEY)} / {nn:02d} ([a-z0-9-]+)", name)
        if not m:
            raise ValueError(f"§0 L{i}: board name {name!r}")
        out[nn] = Board(nn, name, m.group(1), plain(c[2]), i, KIT_FRAMES[nn])
    return out


BOARDS = _boards()


def frame_name(fid: str) -> str:
    return fid.replace("/", SLASH)


def rows_of(head: str, start: int = 1) -> list[tuple[int, list[str]]]:
    """A memo table's rows with bold dropped from every cell (code spans keep their backticks: `24`, `complete`)."""
    return [(i, [x.replace("**", "").strip() for x in c]) for i, c in table(head, "spec", start)]


_RQ = " ".join(LINES["spec"][L("**Research questions and hypotheses (all untested).**") - 1].split("**")[2:]).strip()
RQS = [(f"RQ{a}", q.strip(), h.strip()) for a, q, h in re.findall(r"RQ(\d) (.*?) \(H\1: (.*?)\)(?:;|\.$)", _RQ,
                                                                    re.DOTALL)]
RQ_LINE = L("**Research questions and hypotheses (all untested).**")
METHOD_LINE = L("## 2. Method note")
METHOD = LINES["spec"][METHOD_LINE + 1]
DEVIATIONS_LINE = L("**Deviations (recorded, not hidden).**")
FINDINGS = {c[0]: c for _i, c in rows_of("## 3. Heuristic evaluation")}
FINDING_LINE = {c[0]: i for i, c in rows_of("## 3. Heuristic evaluation")}
DENSITY = rows_of("### 4.3 Row density")
DENSITY_LINE = L("### 4.3 Row density")
GREYSCALE = rows_of("### 4.4 The profile tokens")
LEVELS = rows_of("## 5. Derived levels")
LEVELS_LINE = L("## 5. Derived levels")
MODES = rows_of("### 6.1 The user-facing vocabulary")
MODES_LINE = L("### 6.1 The user-facing vocabulary")
PDS = {c[0]: c for _i, c in rows_of("## 7. Proposed decisions")}
PD_LINE = {c[0]: i for i, c in rows_of("## 7. Proposed decisions")}
COMPETITIVE = rows_of("## 8. Competitive review")
COMPETITIVE_LINE = L("## 8. Competitive review")
CONTRA = rows_of("### 9.1 Contradictions")
GAPS = rows_of("### 9.2 Contract and definition gaps")
AMEND = {c[0]: c for _i, c in rows_of("### 9.3 Amendment proposals")}
OQS = rows_of("### 9.4 Open questions")
TASKS = rows_of("### 10.3 Tasks")
TASKS_LINE = L("### 10.3 Tasks")
RULES = rows_of("The four probes are verbatim from the ticket")
ROTATION = rows_of("### 10.4 Rotation")
TRACE = rows_of("## 11. Traceability")
A11Y_PROFILE = [(i, [plain(x) for x in c]) for i, c in table("**Profile table**", "a11y")]


def memo(chars: str, start: int = 1) -> str:
    """A memo string verbatim (raises if absent); the line is noted."""
    ln = L(chars, start)
    NOTES.add("copy_keys", f"memo L{ln}: \"{chars}\"")
    return chars


def memo_tpl(template: str, **subs: str) -> str:
    """A memo copy template (e.g. "Developing · as of HH:MM UTC") verbatim, its placeholders filled from the world."""
    ln = L(template)
    out = template
    for a, b in subs.items():
        if a not in out:
            raise ValueError(f"{template!r}: no placeholder {a!r}")
        out = out.replace(a, b)
    NOTES.add("copy_keys", f"memo L{ln}: \"{template}\" (placeholders filled from the world)")
    return out


def sentence_after(head: str, start: int = 1) -> str:
    """The paragraph text after a bold lead-in on its line (markdown emphasis dropped)."""
    ln = L(head, start)
    return LINES["spec"][ln - 1].split(head, 1)[1].replace("**", "").strip()
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
    "focus": "research board: the focus ring is drawn as a 2 px color.text.primary outline (border.focus), not "
             "color.focus.ring (a hue); E19-D02 / D03 bind the ring token in hi-fi",
    "chip": "research board: CMP-011 info and CMP-227 are drawn as bordered greyscale pills with their words; the "
            "status hues (color.status.info.*) are not bound (greyscale, memo §0)",
    "marker": "kit choice: board markers (measurements, reading notes, crossed-out examples) are caption text in a "
              "'dashed · ' outline (board markers, not product UI)",
    "hidden": "kit choice: a string a screen reader hears (an accessible name, the DOM mirror) is drawn as caption "
              "text in a 'dashed · ' outline",
    "profile": "lo-fi: a profile is drawn from the derived rows as rects (one per row, width = volume / the POC "
               "row's volume); every row has the same fill (color.text.tertiary), so no level is carried by fill "
               "(PD-3); the cues are solid rails, ticks, brackets and glyphs in color.text.primary",
    "hatch": "lo-fi stand-in: pattern.hatch.estimated is a registered pattern id (`16` §6 rule 4), not a Penpot "
             "token; approximated rows are drawn as hollow bars with an inner dashed outline ('dashed · ' name, dashed by "
             "the post-step); E19-D03 binds the pattern",
    "glyph": "kit stand-in (E19-D03 chooses the glyphs, memo §5): HVN = the local chevron-right icon (right-"
             "pointing), LVN = a solid 6 px circle, single prints = a solid 2 px bar in the TPO margin, IB = a solid "
             "vertical bar left of the TPO strip, nPOC = a solid 1 px ray",
    "tpo": "lo-fi: the TPO strip draws each row's TPO count as a solid bar 4 px per period (a stand-in for the "
           "letters; CMP-184 draws letters)",
    "schematic": "schematic: redrawn from the vendor's public words in greyscale boxes; no vendor screenshot, asset, "
                 "logo or trade dress (memo §8)",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs",
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
    """A label the memo does not write: drawn, and listed as a copy gap for E19-D02 / D03 (PROPOSED)."""
    NOTES.add("copy_gaps", f"\"{chars}\": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the "
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


# --- the seeded synthetic world (WORLD, seed 382). Every POC, VAH, VAL, node, count and time drawn is derived here.
import random  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from decimal import ROUND_HALF_EVEN, Decimal  # noqa: E402

UTC = timezone.utc
SEED = ISSUE
SYMBOL = "BTCUSDT"


def _fixture() -> tuple[Decimal, Decimal]:
    d = json.loads(_doc_bytes("fixture").decode("utf-8"))
    found: list[tuple[Decimal, Decimal]] = []

    def rec(o: Any) -> None:
        if isinstance(o, dict):
            if o.get("symbol") == SYMBOL:
                found.append((Decimal(o["priceFilter"]["tickSize"]), Decimal(o["lotSizeFilter"]["qtyStep"])))
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)
    rec(d)
    return found[0]


TICK, QTY_STEP = _fixture()
ROW_TICKS = 50  # synthetic row size for the illustrations: 50 ticks = 5.00 USDT (declared on every board)
ROW = TICK * ROW_TICKS
PERIOD = timedelta(minutes=30)  # TPO period (classic 30-minute letters, `22`'s tpo_period_minutes)
DAYS = tuple(datetime(2026, 10, d, tzinfo=UTC) for d in (28, 29, 30))  # sessions with data (UTC days)
REQUESTED = tuple(datetime(2026, 10, d, tzinfo=UTC) for d in (25, 26, 27, 28, 29))  # the composite's request
BARS_FROM = datetime(2026, 10, 28, tzinfo=UTC)  # kline bars kept from here (synthetic)
TICKS_FROM = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)  # recorded trades from here: before it, approximated from bars
NOW = datetime(2026, 10, 30, 14, 30, tzinfo=UTC)  # the developing session's "as of"
START_MID = Decimal("62900.0")
DRIFT = {28: (Decimal("0"), Decimal("4.0")), 29: (Decimal("2.0"), Decimal("4.0")),
         30: (Decimal("2.0"), Decimal("0"))}  # per-period drift (first half, second half of the day), USDT
VA_PCT = 70  # `24`'s default value-area percentage (the legend "Value area 70 %")
IB_PERIODS = 2  # kit choice: the initial balance = the first two TPO periods (00:00–01:00 UTC); the memo names none


def qt(v: Decimal, step: Decimal = TICK) -> Decimal:
    return (v / step).to_integral_value(rounding=ROUND_HALF_EVEN) * step


@dataclass(frozen=True)
class Period:
    start: datetime
    lo: int  # ticks (price / TICK)
    hi: int
    vol: int  # milli-BTC (qty step 0.001)
    buy: Decimal  # buy share of the period's volume (synthetic)

    @property
    def approximated(self) -> bool:
        return self.start < TICKS_FROM


def _periods() -> list[Period]:
    rng = random.Random(SEED)
    out, mid = [], START_MID
    for day in DAYS:
        for p in range(48):
            start = day + p * PERIOD
            if start >= NOW:
                break
            drift = DRIFT[day.day][0 if p < 24 else 1]
            mid = qt(mid + drift + Decimal(str(round(rng.gauss(0, 9), 1))))
            half = qt(Decimal(str(round(rng.uniform(6, 22), 1))))
            lo, hi = int((mid - half) / TICK), int((mid + half) / TICK)
            vol = rng.randint(8000, 60000) + (25000 if 13 <= start.hour < 17 else 0)
            out.append(Period(start, lo, hi, vol, Decimal(str(round(rng.uniform(0.36, 0.64), 2)))))
    return out


PERIODS = _periods()


def periods(day: datetime | None = None, *, until: datetime = NOW, days: Iterable[datetime] | None = None
            ) -> list[Period]:
    want = {day} if day else set(days or DAYS)
    return [p for p in PERIODS if p.start.replace(hour=0, minute=0) in want and p.start < until]


def _per_tick(p: Period) -> dict[int, int]:
    """A period's volume per tick, in qty steps. Bar-approximated periods use the memo's uniform rule (§4.1: spread
    evenly over [low, high]; the remainder goes to the lowest ticks). Recorded periods stand for trade prints: seeded
    integer weights (a triangle peaking at the period's middle tick, times a seeded factor 1-4), the volume split
    in proportion with the largest remainders to the lowest ticks."""
    n = p.hi - p.lo + 1
    if p.approximated:
        base, rem = divmod(p.vol, n)
        return {t: base + (1 if i < rem else 0) for i, t in enumerate(range(p.lo, p.hi + 1))}
    rng = random.Random(f"{SEED}-{p.start:%Y%m%d%H%M}")
    mid = (n - 1) / 2
    w = [(1 + round(mid - abs(i - mid))) * rng.randint(1, 4) for i in range(n)]
    tot = sum(w)
    share = [p.vol * x // tot for x in w]
    rem = p.vol - sum(share)
    order = sorted(range(n), key=lambda i: (-(p.vol * w[i] % tot), i))
    for i in order[:rem]:
        share[i] += 1
    return {p.lo + i: v for i, v in enumerate(share)}


@dataclass
class Profile:
    label: str
    row_ticks: int
    vol: dict[int, int]  # row index -> milli-BTC
    approx: dict[int, int]  # row index -> milli-BTC from the bar-approximated portion
    delta: dict[int, int]  # row index -> milli-BTC, over the recorded-trade portion only
    tpo: dict[int, int]  # row index -> TPO periods touching the row, over the recorded-trade portion only
    ib: tuple[int, int] | None  # rows of the initial balance
    complete: bool
    as_of: datetime
    first: datetime
    last: datetime
    poc: int = 0
    va: tuple[int, int] = (0, 0)

    def price(self, row: int) -> Decimal:
        return row * self.row_ticks * TICK  # a row's price = its lower bound

    @property
    def rows(self) -> list[int]:
        return list(range(min(self.vol), max(self.vol) + 1))

    @property
    def total(self) -> int:
        return sum(self.vol.values())


def build_profile(label: str, ps: list[Period], *, row_ticks: int = ROW_TICKS, complete: bool,
                  as_of: datetime = NOW) -> Profile:
    vol: dict[int, int] = {}
    approx: dict[int, int] = {}
    delta: dict[int, int] = {}
    tpo: dict[int, int] = {}
    for p in ps:
        touched = set()
        for t, v in _per_tick(p).items():
            r = t // row_ticks
            vol[r] = vol.get(r, 0) + v
            touched.add(r)
            if p.approximated:
                approx[r] = approx.get(r, 0) + v
            else:
                d = int((Decimal(v) * (2 * p.buy - 1)).to_integral_value(rounding=ROUND_HALF_EVEN))
                delta[r] = delta.get(r, 0) + d
        if not p.approximated:
            for r in touched:
                tpo[r] = tpo.get(r, 0) + 1
    rec = [p for p in ps if not p.approximated]
    ib = None
    if len(rec) >= IB_PERIODS and rec[0].start.hour == 0 and rec[0].start.minute == 0:
        ib = (min(p.lo for p in rec[:IB_PERIODS]) // row_ticks, max(p.hi for p in rec[:IB_PERIODS]) // row_ticks)
    pr = Profile(label, row_ticks, vol, approx, delta, tpo, ib, complete, as_of, ps[0].start, ps[-1].start + PERIOD)
    top = max(vol.values())
    pocs = [r for r, v in vol.items() if v == top]
    if len(pocs) != 1:
        raise ValueError(f"{label}: a POC tie {pocs} (the world must not need C-1's tie-break)")
    pr.poc = pocs[0]
    lo = hi = pr.poc
    got, need = vol[pr.poc], math.ceil(pr.total * VA_PCT / 100)
    while got < need:  # `22`'s single-step expansion: toward the heavier adjacent row (tie: up, kit choice)
        up, dn = vol.get(hi + 1, -1) if hi + 1 <= max(vol) else -1, vol.get(lo - 1, -1) if lo - 1 >= min(vol) else -1
        if up >= dn:
            hi += 1
            got += max(up, 0)
        else:
            lo -= 1
            got += max(dn, 0)
    pr.va = (lo, hi)
    return pr


def smoothed(pr: Profile, r: int) -> Decimal:
    return Decimal(sum(pr.vol.get(x, 0) for x in (r - 1, r, r + 1))) / 3


def nodes(pr: Profile) -> tuple[int, int]:
    """Kit illustration rule (not a definition; E19-C01 / E19-D03 define nodes): HVN = the highest strict local maximum
    of the 3-row smoothed volume (over ±2 rows) other than the POC's; LVN = the lowest smoothed row strictly between
    the POC and that HVN."""
    rs = pr.rows
    peaks = [r for r in rs[2:-2] if abs(r - pr.poc) > 2 and all(smoothed(pr, r) > smoothed(pr, r + d)
                                                                  for d in (-2, -1, 1, 2))]
    hvn = max(peaks, key=lambda r: (smoothed(pr, r), r))
    a, b = sorted((pr.poc, hvn))
    lvn = min(range(a + 1, b), key=lambda r: (smoothed(pr, r), r))
    return hvn, lvn


def single_prints(pr: Profile) -> list[int]:
    """Rows whose TPO count is 1 (the memo's derivation, F-12 / G-6), over the recorded-trade portion."""
    return sorted(r for r, n in pr.tpo.items() if n == 1)


SESSION = {d.day: build_profile(f"session {d.day} Oct", periods(d), complete=d + timedelta(days=1) <= NOW)
           for d in DAYS}
DEVELOPING, FINAL, APPROX_SESSION = SESSION[30], SESSION[29], SESSION[28]
COMPOSITE = build_profile("composite 25–29 Oct", periods(days=REQUESTED), complete=True)
RECORDED_DAYS = [d for d in REQUESTED if any(p.start.replace(hour=0, minute=0) == d and not p.approximated
                                              for p in PERIODS)]
COVERED_DAYS = [d for d in REQUESTED if any(p.start.replace(hour=0, minute=0) == d for p in PERIODS)]


def naked_pocs(until: datetime = NOW) -> list[tuple[datetime, Decimal, bool]]:
    """Each completed session's POC (price of its row) and whether a later period through `until` traded its row."""
    out = []
    for d in DAYS:
        pr = SESSION[d.day]
        if not pr.complete:
            continue
        lo_t, hi_t = pr.poc * pr.row_ticks, (pr.poc + 1) * pr.row_ticks - 1
        later = [p for p in PERIODS if d + timedelta(days=1) <= p.start < until]
        tested = any(p.lo <= hi_t and p.hi >= lo_t for p in later)
        out.append((d, pr.price(pr.poc), tested))
    return out


def one_tick(pr_label: str, ps: list[Period]) -> Profile:
    return build_profile(pr_label, ps, row_ticks=1, complete=True)


# --- formatting (every number on a board goes through these)
MINUS = "−"


def fmt_price(v: Decimal) -> str:
    """A price on the tick, with a comma thousands separator (the memo's label copy "POC 62,974.0")."""
    return f"{qt(v):,.1f}"


def row_price(pr: Profile, r: int) -> str:
    return fmt_price(pr.price(r))


def fmt_vol(milli: int) -> str:
    """BTC on the 0.001 qty step."""
    return f"{Decimal(milli) * QTY_STEP:,.3f}"


def fmt_delta(milli: int) -> str:
    v = Decimal(milli) * QTY_STEP
    return f"{MINUS if v < 0 else '+' if v > 0 else ''}{abs(v):,.3f}"


def hhmm(t: datetime) -> str:
    return f"{t:%H:%M}"


def day_word(t: datetime) -> str:
    return f"{t.day} {t:%b}"


def pd_line(pid: str) -> str:
    c = PDS[pid]
    return f"{pid} (memo §7 L{PD_LINE[pid]}, {c[5]}): {c[1]}"


def f_line(fid: str) -> str:
    c = FINDINGS[fid]
    return f"{fid} {c[1]} [{c[5]}] (memo §3 L{FINDING_LINE[fid]}): {c[3]}"


def level_row(name: str) -> list[str]:
    for _i, c in LEVELS:
        if c[0] == name:
            return c
    raise KeyError(name)


def mode_words() -> list[str]:
    return [c[0] for _i, c in MODES]


def developing_words(pr: Profile) -> str:
    """PD-1's words for a profile: the template filled from the profile's as-of clock, or "Final"."""
    if pr.complete:
        return memo("Final")
    return memo_tpl("Developing · as of HH:MM UTC", **{"HH:MM": hhmm(pr.as_of)})
    return f"{v} %"


# --- frames, tables, annotations, the board
FRAME_PAD = 24


def data_statement() -> str:
    return (f"Data: synthetic only where a board draws a profile — a seeded world (seed {SEED}): {SYMBOL} 30-minute "
            f"periods over the UTC days {', '.join(f'{d.day} Oct' for d in DAYS)} 2026 (the last developing, as of "
            f"{NOW:%H:%M} UTC), tick {TICK} and qty step {QTY_STEP} from the recorded instrument fixture; prices, "
            f"volumes and buy shares synthetic; rows of {ROW_TICKS} ticks ({fmt_price(ROW)} USDT) unless a frame says "
            f"otherwise; every POC, VAH, VAL, node, count and time derived from the periods (value area {VA_PCT} %, "
            f"`22`'s single-step expansion). Research board: greyscale, dark only; every finding (heuristic), every "
            f"decision PROPOSED; no session was run.")


def frame_header(fid: str, w_: int, framing: str) -> Node:
    return vbox("frame header", [
        hbox("title", [text("kind", "RESEARCH", LABEL, TEXT_2), text("id", fid, LABEL, TEXT_1)], {"gap": INSET_SM},
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
    return fid, [pd_line(w) for w in wds] + [x for x in lines if x]


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    b = BOARDS[nn]
    head = [f"memo §0 L{b.line}: {b.shows}", f"Frames: {', '.join(b.frames)}",
            "Theme: dark only — greyscale research board, no light twin (memo §0, BQ-15)", f"Export: {b.export}",
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
    for k_, why in (("a11y", "`05` §6 profile table: the columns A-6 extends"),
                    ("fixture", f"{SYMBOL} tick {TICK}, qty step {QTY_STEP}")):
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
           summary or f"Board {nn:02d} of nine (memo §0 L{b.line}: {b.shows}). Grid ({x}, {y}); {sh['board']['w']} x "
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
    check(sorted(BOARDS) == list(range(1, 10)), "memo §0: nine boards 01-09, each PENDING or drawn as its export")
    check(PAGE == KEY and FILE_NAME == f"{KEY} boards", f"page {PAGE!r}, file {FILE_NAME!r}")
    check(all(b.export.startswith("docs/design/research/img/E19-D01-") and b.export.endswith(f"-{b.slug}.png")
              for b in BOARDS.values()), f"exports follow §0's pattern {EXPORT_PATTERN}")
    check(sum(len(b.frames) for b in BOARDS.values()) == 21, f"{sum(len(b.frames) for b in BOARDS.values())} frames")
    check([r[0] for r in RQS] == [f"RQ{i}" for i in range(1, 7)], "§2: RQ1..RQ6 with H1..H6")
    check(sorted(FINDINGS, key=lambda x: int(x[2:])) == [f"F-{i}" for i in range(1, 23)] and
          all(c[1] == "(heuristic)" for c in FINDINGS.values()), "§3: F-1..F-22, every one (heuristic)")
    check(len(LEVELS) == 10, "§5: ten levels")
    check(mode_words() == ["Session", "Fixed range", "Visible range", "Anchored", "Composite"], "§6.1: five modes")
    check(sorted(PDS) == [f"PD-{i}" for i in range(1, 9)] and all(c[5] == "PROPOSED" for c in PDS.values()),
          "§7: PD-1..PD-8, every one PROPOSED")
    check(len(COMPETITIVE) == 6 and len(TASKS) == 12 and len(ROTATION) == 3 and len(RULES) == 10 and RULES[0][1][0].startswith("RQ1"), "§8 six rows; §10.3 T0..T11 and ten rule rows; §10.4 3")
    check([c[0] for _i, c in A11Y_PROFILE] == ["Price", "Volume", "Delta", "% of POC", "Value area"],
          "`05` §6 profile table: five columns")
    check(str(TICK) == "0.10" and str(QTY_STEP) == "0.001", "fixture: BTCUSDT tick 0.10, qty step 0.001")
    check(all(p.lo < p.hi for p in PERIODS) and len(periods(DAYS[2])) == (NOW - DAYS[2]) // PERIOD,
          f"world: {len(PERIODS)} periods; the developing day has {(NOW - DAYS[2]) // PERIOD} up to {hhmm(NOW)} UTC")
    check(not DEVELOPING.complete and FINAL.complete and APPROX_SESSION.complete, "30 Oct developing; 28, 29 final")
    for pr in (DEVELOPING, FINAL, APPROX_SESSION, COMPOSITE):
        inside = sum(v for r, v in pr.vol.items() if pr.va[0] <= r <= pr.va[1])
        check(pr.va[0] <= pr.poc <= pr.va[1] and inside * 100 >= VA_PCT * pr.total and
              pr.vol[pr.poc] == max(pr.vol.values()), f"{pr.label}: POC {row_price(pr, pr.poc)} in VA "
              f"{row_price(pr, pr.va[0])}–{row_price(pr, pr.va[1])} ({inside * 100 // pr.total} % ≥ {VA_PCT} %)")
    nk = naked_pocs()
    check(len(nk) == 2 and not any(t for _d, _p, t in nk), f"naked POCs as of {hhmm(NOW)} UTC: "
          f"{[(day_word(d), fmt_price(p)) for d, p, _t in nk]} (both untested)")
    hvn, lvn = nodes(DEVELOPING)
    check(hvn != DEVELOPING.poc and min(DEVELOPING.poc, hvn) < lvn < max(DEVELOPING.poc, hvn), "nodes: HVN, LVN")
    check(bool(single_prints(DEVELOPING)) and DEVELOPING.ib is not None, "single prints and an IB on 30 Oct")
    check(bool(APPROX_SESSION.approx) and not DEVELOPING.approx and not FINAL.approx, "28 Oct alone is approximated")
    check((len(RECORDED_DAYS), len(REQUESTED)) == (2, 5) and COVERED_DAYS == RECORDED_DAYS,
          f"composite: {len(RECORDED_DAYS)} of {len(REQUESTED)} requested days recorded")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for k_, v in globals().items() if k_.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border)\.", v)]
    miss = sorted(set(u for u in used if u not in toks))
    check(not miss and GREY <= toks, f"kit tokens exist (missing {miss})")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: text("x", "y", color="color.status.danger.strong"),
                 lambda: rect("x", 1, 1, "color.env.live"), lambda: text("x", "see " + "ht" + "tps://x")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/', a hue token and a URL refused")
    NOTES.reset()
    fid = BOARDS[1].frames[0]
    fr = frame(fid, [text("sample", developing_words(DEVELOPING), BODY, TEXT_1)], 480, "self-test sample frame")
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
