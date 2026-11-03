"""E47-D13 (#1311) board kit: the accessibility statement (the page at /accessibility, a sub-view of SCR-119 inside
CMP-086 SettingsLayout), its states, its tables, its feedback path, its entries, reflow and keyboard order: ten
boards as cvsheet JSON sheets for the per-set Penpot file "E47-D13 boards", page "E47-D13 — Conformance statement"
(spec §0).

Offline only. Sources (binding; every string, frame and figure comes from them), read from a checkout by
repo-relative path (`14` with git show at the spec's base) and md5-pinned in DOCS (the kit refuses drifted bytes;
after an edit re-check every L<n> cite, re-pin and rebuild): the spec docs/design/E47/E47-D13.md and its hand-off,
the generated dry run docs/plan/a11y/47-conformance-report.md (the 55 rows and their conformance words), the
limitations register docs/plan/a11y/47-limitations.json (the statement rows, the category sentences) and `14` (the
SCR-110 settings nav, SCR-116's largest text scale, SCR-117 and SCR-119).
Registry: §0's board table (BOARDS) and §H's frame table (FRAME_PLAN) are parsed; §11's copy deck (COPY, w() fills
the slots), §14.2's G-ledger (GROWS), §1.4's rules (RULES), §7.6's ratios (CONTRAST) and every COUNT slot likewise.
Synthetic data (declared on every board): the statement's version, dates and running version (SYNTH below); the
rows and limitations are the dry run's, read from the committed files.

Pipeline (one generator per board, gen/gen_NN.py):
    frames = [...]                                    # one 1280 x 800 frame per FRAME_PLAN entry, in order
    ann = annotations(nn, [frame_block(...), ...])    # the ONE 400 px column
    build_all(nn, frames, ann)                        # raw sheet (validator exit 0), its .md, the packed sheet
Twins: boards 02 and 10 (light) and 04 (hc): every fill is a token, the theme is set at export.
Self-test: python3 -I -B e47d13kit.py selftest ; all boards: python3 -I -B check_all.py (build + scan).

Checkout: the kit sits at docs/design/_tools/sheets/e47-d13/ in a checkout (REPO = four levels up), or anywhere with
CV_CHECKOUT naming the checkout. Raw sheets + .md go to CAP_DIR, packed sheets to V4_DIR.

Penpot lessons kept as hard checks: no "inst" node; icons only from ICONS_OK; o.wrap only "wrap"/"nowrap"; every
flex child without text carries an explicit h; no "/" in a node name (U+2215 instead); no local path, host or agent
name anywhere in a sheet (BANNED); packed sections <= 9 KB; table cells carry 8 px inner padding a side.
"""
from __future__ import annotations

import datetime as _dt
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

KEY, EPIC, ISSUE = "E47-D13", "E47", 1311
KIT_DIR = Path(__file__).resolve().parent
_SPEC_PATH = "docs/design/E47/E47-D13.md"


def _repo() -> Path:
    up = KIT_DIR.parents[4] if len(KIT_DIR.parents) > 4 else KIT_DIR
    if (up / _SPEC_PATH).is_file():
        return up
    env = os.environ.get("CV_CHECKOUT")
    if not env or not (Path(env) / _SPEC_PATH).is_file():
        raise SystemExit("e47d13kit: run inside a checkout or set CV_CHECKOUT to one")
    return Path(env).resolve()


REPO = _repo()
IN_REPO = KIT_DIR.is_relative_to(REPO)
CAP_DIR = KIT_DIR / "build" if IN_REPO else KIT_DIR.parent / f"{KEY}-cap"  # raw sheets + .md
V4_DIR = KIT_DIR / "v4" if IN_REPO else KIT_DIR.parent / f"{KEY}-v4"  # packed sheets
SELFTEST_DIR = CAP_DIR / "selftest"
TOOLS = REPO / "docs" / "design" / "_tools" / "sheets" / "tools"
VALIDATOR, PACKER, MKCALL = TOOLS / "validate_sheet.py", TOOLS / "compact.py", TOOLS / "mkcall4.py"
COMPONENTS, TOKENS_FILE = TOOLS / "components.offline.json", TOOLS / "token-sync.json"
DOCS = {  # key -> (repo-relative path, md5 as read): every read is md5-checked; AT_BASE keys are read at SPEC_BASE
    "spec": (_SPEC_PATH, "0cbd55df52e306873f04d033d7a55446"),
    "handoff": ("docs/design/E47/E47-D13-handoff.md", "1da094e2e8d26b9cda830821319a42d0"),
    "report": ("docs/plan/a11y/47-conformance-report.md", "807dc1d0ddd03165f5ea39a35cdf1cd4"),
    "limits": ("docs/plan/a11y/47-limitations.json", "f609cce782720cf0f7d1f84b7df06e85"),
    "cat": ("docs/plan/14-screens-catalogue.md", "1ca288905451c9e5c495a0468c062641"),
}
FILE_NAME = f"{KEY} boards"
REV = "r1"
PITCH_X, PITCH_Y = 6000, 3200  # grid: x = ((NN-1) mod 5) * PITCH_X, y = floor((NN-1)/5) * PITCH_Y
MARGIN = 80  # root margin and frame gutters
ANN_W = 400  # the one annotation column, outside the frames
ANN_TEXT_W = ANN_W - 32
FRAME_W, FRAME_H = 1280, 800
MAX_PER_ROW = 3
SECTION_RAW_BUDGET = 9000
PACKED_MAX = 9216
SLASH = "∕"  # U+2215 stands for "/" in node names (Penpot splits names on "/")
ICONS_OK = frozenset(("locked arrow-up arrow-down close drag-handle search check chevron-down chevron-right info "
                      "warning danger pending refresh cancelled copy show more-horizontal").split())
# local paths, hosts and agent names never belong in a sheet; the words are hex here so this file carries none of them
BANNED = re.compile("|".join(re.escape(bytes.fromhex(h).decode()) for h in (
    "2f686f6d652f", "736372617463682d616e76696c", "6e65772d70726f6a65637473", "68636c2d", "6870652d",
    "6f7263686573747261746f72", "636c61756465", "68747470")) + r"|wt/\d|\b" + bytes.fromhex("616e76696c").decode()
    + r"\b", re.I | re.DOTALL)


# `14` as the spec cites it: at the base its "Inputs pinned" line names (git show); main has moved on
AT_BASE = frozenset(("cat",))


def _git_show(sha: str, rel: str) -> bytes:
    res = subprocess.run(["git", "-C", str(REPO), "show", f"{sha}:{rel}"], capture_output=True, timeout=60,
                         check=False)
    if res.returncode != 0:
        raise SystemExit(f"e47d13kit: {rel} at {sha} is not in this checkout's objects")
    return res.stdout


def _spec_base() -> str:
    m = re.search(rb"\*\*Inputs pinned\.\*\* Base `origin/main` `([0-9a-f]{7,40})`",
                  (REPO / DOCS["spec"][0]).read_bytes())
    if not m:
        raise SystemExit("e47d13kit: the spec's Inputs pinned line names no base")
    return m.group(1).decode()


SPEC_BASE = _spec_base()
_BYTES: dict[str, bytes] = {}


def _doc_bytes(k_: str) -> bytes:
    if k_ not in _BYTES:
        rel = DOCS[k_][0]
        _BYTES[k_] = _git_show(SPEC_BASE, rel) if k_ in AT_BASE else (REPO / rel).read_bytes()
    return _BYTES[k_]


def spec_md5_ok() -> dict[str, bool]:
    return {k_: hashlib.md5(_doc_bytes(k_)).hexdigest() == m for k_, (_p, m) in DOCS.items()}


_DRIFT = [n for n, ok in spec_md5_ok().items() if not ok]
if _DRIFT:
    raise SystemExit(f"e47d13kit: source text drifted from DOCS md5 ({', '.join(_DRIFT)}): re-read, re-check, re-pin")


def _lines(k_: str) -> list[str]:
    return _doc_bytes(k_).decode("utf-8").split("\n")


SPEC_LINES, HANDOFF_LINES, CAT_LINES = _lines("spec"), _lines("handoff"), _lines("cat")
SPEC_TEXT = "\n".join(SPEC_LINES)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


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


def CL(needle: str, start: int = 1) -> int:
    return find_line(needle, CAT_LINES, start)


def _plain(s: str) -> str:
    """A table cell as words: placeholder comments dropped, backticks removed, spaces collapsed."""
    return re.sub(r"\s+", " ", _COMMENT.sub("", s).replace("`", "")).strip()


# --- the spec's tool-filled figures: "16.05<!--=CONTRAST:p1.dark-->", "10<!--=COUNT:boards-->"
CONTRAST: dict[str, str] = {k_: v for v, k_ in re.findall(r"([0-9]+(?:\.[0-9]+)?)<!--=CONTRAST:([\w.-]+)-->",
                                                          SPEC_TEXT, re.DOTALL)}
COUNT: dict[str, str] = {k_: v for v, k_ in re.findall(r"([0-9]+)<!--=COUNT:([\w.-]+)-->", SPEC_TEXT, re.DOTALL)}


def ratio(key: str) -> str:
    if key not in CONTRAST:
        raise KeyError(f"CONTRAST:{key} is not in the spec")
    return CONTRAST[key]


# --- §0: the ten boards; §H: their frames
PAGE_LINE = L(f"Penpot: the per-set file `{FILE_NAME}`")
PAGE = re.search(r"page `([^`]+)`", SPEC_LINES[PAGE_LINE - 1]).group(1)  # type: ignore[union-attr]


@dataclass(frozen=True)
class Board:
    nn: int
    name: str  # "E47-D13 / 01 statement-anatomy"
    slug: str
    draws: str
    theme: str  # dark | light | hc
    line: int  # §0 line

    @property
    def export(self) -> str:
        return f"docs/design/{EPIC}/img/{KEY}-{self.nn:02d}-{self.slug}.png"

    @property
    def sheet(self) -> str:
        return f"{self.nn:02d}-{self.slug}.json"


_B_ROW = re.compile(r"^\|\s*(\d{2})\s*\|\s*`(" + re.escape(KEY) + r" / (\d{2}) ([a-z0-9-]+))`\s*\|([^|]*)\|"
                    r"\s*(dark|light|hc)\s*\|([^|]*)\|\s*$")


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
        out[nn] = Board(nn, m.group(2), m.group(4), _plain(m.group(5)), m.group(6), i)
    return out


BOARDS = _parse_boards()
THEMED = {nn: b.theme for nn, b in BOARDS.items() if b.theme != "dark"}  # {2: light, 4: hc, 10: light}
NOT_DRAWN_LINE = L("**Not drawn — the text is binding**")
H_LINE = HL("## §H The board plan")


def _parse_frames() -> dict[int, tuple[str, ...]]:
    """§H: board -> its frame names as written ("statement/anatomy · dark", ...)."""
    out: dict[int, tuple[str, ...]] = {}
    for i in range(H_LINE, len(HANDOFF_LINES)):
        ln = HANDOFF_LINES[i]
        if ln.startswith("## "):
            break
        c = _cells(ln) if ln.startswith("|") else []
        if c and re.fullmatch(r"\d{2}", c[0]):
            out[int(c[0])] = tuple(re.findall(r"`([^`]+)`", c[1]))
    return out


# §0's board 03 Draws names "the offline frame (§7.3)" and §7.3 says "board 03's offline frame", while §H lists two
# frames for 03: the spec's board table and §7.3 decide (BUILD reading 1), so 03 draws a third frame
EXTRA_FRAMES = {3: ("statement/offline · dark",)}
FRAME_PLAN = {nn: fs + EXTRA_FRAMES.get(nn, ()) for nn, fs in _parse_frames().items()}


def frames_of(nn: int) -> tuple[str, ...]:
    return FRAME_PLAN[nn]


def frame_name(fid: str) -> str:
    """The Penpot frame name: §H's "<section>/<state> · <theme>" with U+2215 for the slash."""
    return fid.replace("/", SLASH)


def frame_id(fid: str) -> str:
    return frame_name(fid).split(" · ")[0]


# --- §11 the copy deck (W-1 ... W-20), §14.2 the G-ledger, §1.4 the rules, §7.6 the pairs
@dataclass(frozen=True)
class Copy:
    key: str
    text: str
    status: str
    line: int


def _parse_copy() -> dict[str, Copy]:
    a = L("## 11. Copy deck")
    out = {}
    for i in range(a, L("## 12.", start=a)):
        c = _cells(SPEC_LINES[i - 1]) if SPEC_LINES[i - 1].startswith("|") else []
        if c and re.fullmatch(r"W-\d+", c[0]):
            out[c[0]] = Copy(c[0], c[1].strip(), _plain(c[3]), i)
    return out


COPY = _parse_copy()
_SLOT = re.compile(r"\{[^{}]*\}")


def w_parts(key: str) -> list[str]:
    """W-10 / W-14 carry several quoted strings: '"A" / "B" / "C"' -> [A, B, C]."""
    return re.findall(r'"([^"]+)"', COPY[key].text)


def w(key: str, *vals: Any, part: int | None = None) -> str:
    """W-n (or its part-th quoted string) with its {slots} filled in order; every slot must be filled."""
    parts = w_parts(key)
    s = parts[part] if part is not None else (parts[0] if len(parts) == 1 else None)
    if s is None:
        raise ValueError(f"{key} has {len(parts)} strings: name a part")
    slots = _SLOT.findall(s)
    if len(vals) != len(slots):
        raise ValueError(f"{key}: {len(slots)} slots {slots}, {len(vals)} values")
    for v in vals:
        s = _SLOT.sub(str(v).replace("\\", "\\\\"), s, count=1)
    NOTES.add("copy_keys", f"{key} (§11 L{COPY[key].line}, {COPY[key].status})")
    return s


def wcite(key: str) -> str:
    return f"{key} (§11 L{COPY[key].line})"


def _parse_g() -> dict[str, tuple[str, int]]:
    a = L("### 14.2 The G-ledger")
    return {c[0]: (_plain(c[1]), i) for i in range(a, L("### 14.3", start=a))
            if SPEC_LINES[i - 1].startswith("|") and (c := _cells(SPEC_LINES[i - 1]))[0].startswith(f"{KEY[-3:]}-G")}


GROWS = _parse_g()  # D13-G1 ... D13-G5


def g(gid: str) -> str:
    if gid not in GROWS:
        raise KeyError(gid)
    NOTES.add("g_rows", f"{gid} (§14.2 L{GROWS[gid][1]}): {GROWS[gid][0]}")
    return gid


RULES = {m.group(1): (m.group(2), i + 1) for i, ln in enumerate(SPEC_LINES)
         if (m := re.match(r"- \*\*(R-\d+) ([^*]+?)\.\*\*", ln))}


def rule(rid: str) -> str:
    name, ln = RULES[rid]
    return f"{rid} {name} (§1.4 L{ln})"


@dataclass(frozen=True)
class Pair:
    pid: str
    fg: str
    bg: str
    bar: str
    line: int

    def r(self, theme: str) -> str:
        return ratio(f"{self.pid.lower()}.{theme}")


def _parse_pairs() -> dict[str, Pair]:
    a = L("### 7.6 Contrast (computed)")
    out = {}
    for i in range(a, L("### 7.7", start=a)):
        c = _cells(SPEC_LINES[i - 1]) if SPEC_LINES[i - 1].startswith("|") else []
        if c and re.fullmatch(r"P\d", c[0]):
            out[c[0]] = Pair(c[0], _plain(c[1]), _plain(c[2]), _plain(c[-1]), i)
    return out


PAIRS = _parse_pairs()
THEME_WORD = {"dark": "dark", "light": "light", "hc": "high contrast"}


def pair_line(pid: str, theme: str) -> str:
    p = PAIRS[pid]
    return f"{pid} {p.fg} on {p.bg}: {p.r(theme)}:1 {THEME_WORD[theme]} (bar {p.bar}; §7.6 L{p.line})"


# --- the dry run (the committed report) and the limitations register: the data every board shows
@dataclass(frozen=True)
class Row:
    sc: str  # "1.4.10"
    name: str  # "Reflow"
    level: str  # "A" | "AA"
    word: str  # "Partially Supports" ...
    line: int  # report line

    @property
    def criterion(self) -> str:
        return f"{self.sc} {self.name}"

    @property
    def level_words(self) -> str:  # §7.2 item 7: cell text "Level A" or "Level AA"
        return f"Level {self.level}"


WORDS = ("Supports", "Partially Supports", "Does Not Support", "Not Applicable")  # §2.2, R-9
REPORT_LINES = _lines("report")
_R_ROW = re.compile(r"^\|\s*(\d+\.\d+\.\d+) ([^|]+?)\s*\|\s*(A|AA)\s*\|\s*([^|]+?)\s*\|")


def _parse_report() -> list[Row]:
    out = [Row(m.group(1), m.group(2), m.group(3), m.group(4), i + 1) for i, ln in enumerate(REPORT_LINES)
           if (m := _R_ROW.match(ln))]
    bad = [r.criterion for r in out if r.word not in WORDS]
    if bad:
        raise ValueError(f"report rows with a word outside §2.2: {bad}")
    return out


ROWS = _parse_report()
BANNER_LINE = find_line("**Dry run at `", REPORT_LINES)
BASE_SHA = re.search(r"Dry run at `([0-9a-f]+)`", REPORT_LINES[BANNER_LINE - 1]).group(1)  # type: ignore[union-attr]


def status_words() -> str:
    """§7.2 item 1 / R-9 / BQ-9: "Fully conforms" iff every row is Supports or Not Applicable, else W-5."""
    if all(r.word in ("Supports", "Not Applicable") for r in ROWS):
        raise ValueError("every row Supports / N/A: the status would be 'Fully conforms', which the copy deck lacks")
    return w("W-5")


LIMITS_DOC = json.loads(_doc_bytes("limits").decode("utf-8"))
LIMITS = LIMITS_DOC["limitations"]
CATEGORIES: dict[str, str] = LIMITS_DOC["categories"]
STATEMENT_LIMITS = [x for x in LIMITS if x["disclosure"] == "statement"]
INTERNAL_LIMITS = [x for x in LIMITS if x["disclosure"] == "internal"]
BLOCKED = [x["id"] for x in LIMITS if x["disposition"]["kind"] == "none"]


def notice_cell(lim: dict[str, Any]) -> str:
    """§7.2 item 5 / R-7: the words first, the criterion number after, in parentheses."""
    return f"{lim['plain']} ({', '.join(lim['sc'])})"


# --- the synthetic statement document (§8.1 fields) and the running app: declared on every board's face
ISSUED = _dt.date(2026, 11, 2)  # synthetic
REVIEW_DAYS = 90  # synthetic: reviewBy = issued + 90 days (the cadence is per release, §8.3; no interval is given)
SYNTH = {
    "appliesTo": "1.4.0",  # synthetic BuildInfo.version the statement was issued for (`22`:25006, a free string)
    "running": "1.4.0",  # synthetic running version (CMP-207) when current
    "running_stale": "1.5.0",  # synthetic running version on the stale frame (any difference is stale, §8.2, D13-G2)
    "issued": ISSUED,
    "reviewBy": ISSUED + _dt.timedelta(days=REVIEW_DAYS),
    "commit": "a1b2c3d",  # synthetic build commit on the CMP-207 footer
}


def date_words(d: _dt.date) -> str:
    """A date as words (kit reading: "2 November 2026"; the statement is read by non-specialists, R-7)."""
    return f"{d.day} {d.strftime('%B')} {d.year}"


SYNTHETIC = (f"Synthetic data: the statement's version {SYNTH['appliesTo']}, issued {date_words(SYNTH['issued'])}, "
             f"review by {date_words(SYNTH['reviewBy'])}, and the running app's version and build line are invented; "
             f"the {len(ROWS)} rows and the {len(LIMITS)} limitations are the dry run at {BASE_SHA} "
             "(47-conformance-report.md, 47-limitations.json): dry run, not a conformance claim")


# --- `14`: the settings nav (SCR-110), the largest text scale (SCR-116), SCR-117's options, SCR-119's links
SCR110_LINE = CL("Left nav: Profile")
SETTINGS_NAV = tuple(s.strip() for s in re.search(r"Left nav: ([^.]+)\.", CAT_LINES[SCR110_LINE - 1])
                     .group(1).split("·"))  # type: ignore[union-attr]
SCR116_LINE = CL("font size scale (")
TEXT_SCALES = tuple(int(x) for x in re.search(r"font size scale \(([\d/]+) %\)", CAT_LINES[SCR116_LINE - 1])
                    .group(1).split("/"))  # type: ignore[union-attr]
SCR117_LINE = CL("Reduced motion, disable canvas animation")
SCR119_LINE = CL("Version, build hash, backend version")
SCR119_CHECK_LINE = CL("links to the hotkey cheatsheet, accessibility statement")


# --- tokens (exact names in token-sync.json; the self-test checks every one)
APP, CANVAS, RAISED, SUNKEN = "color.surface.app", "color.surface.canvas", "color.surface.raised", "color.surface.sunken"
HOVER, SELECTED, OVERLAY = "color.surface.hover", "color.surface.selected", "color.surface.overlay"
TEXT_1, TEXT_2, TEXT_3 = "color.text.primary", "color.text.secondary", "color.text.tertiary"
TEXT_ON_ACTION, TEXT_INVERSE, TEXT_LINK = "color.text.on-action", "color.text.inverse", "color.text.link"
BORDER, BORDER_SUBTLE, BORDER_STRONG, RING = ("color.border.default", "color.border.subtle", "color.border.strong",
                                              "color.focus.ring")
BORDER_SEL = "color.border.selected"
INFO_SUBTLE, INFO_STRONG = "color.status.info.subtle", "color.status.info.strong"
ACTION_PRIMARY = "color.action.primary.default"
SUCCESS, DANGER = "color.status.success.default", "color.status.danger.default"
MARK_FILL = "color.status.info.default"  # the annotation markers (numbered stops, tags): not product UI
CAPTION, LABEL, BODY, BODY_STRONG = "type.ui.caption", "type.ui.label", "type.ui.body", "type.ui.body-strong"
HEADING_SM, HEADING_MD, HEADING_LG, DISPLAY = ("type.ui.heading-sm", "type.ui.heading-md", "type.ui.heading-lg",
                                               "type.ui.display")
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = ("space.inset.xs", "space.inset.sm", "space.inset.md",
                                                    "space.inset.lg", "space.inset.xl")
STACK_XS, STACK_SM, STACK_MD, STACK_LG = "space.stack.xs", "space.stack.sm", "space.stack.md", "space.stack.lg"
BUTTON_PADX = "space.button.paddingX"
ICON, ICON_SM = "size.icon", "size.icon.sm"
R_CONTROL, R_CARD, R_BADGE = "radius.control", "radius.card", "radius.badge"
HAIR, THICK, FOCUS_W = "border.hairline", "border.thick", "border.focus"
NUM = "type.num.base"
PX = {INSET_XS: 4, INSET_SM: 8, INSET_MD: 12, INSET_LG: 16, INSET_XL: 24, STACK_XS: 4, STACK_SM: 8, STACK_MD: 12,
      STACK_LG: 16, BUTTON_PADX: 12, ICON: 16, ICON_SM: 12, HAIR: 1, THICK: 2, FOCUS_W: 2}
FALLBACKS = {
    "chrome": "kit choice: the shell chrome around SettingsLayout (wordmark, pickers, health chip, rail glyphs, "
              "StatusBar items) and every SCR-117 / SCR-119 item this spec does not word are neutral placeholders; "
              "only what E47-D13 names is drawn with words",
    "markers": "kit choice: numbered stops, tags, outlines, redlines and callouts in color.status.info.default on "
               "color.text.inverse are annotation, never product UI",
    "underline": "fallback: a text node has no underline; the link underline (`15`:258 block, §7.6) is a 1 px "
                 "color.text.link rule under the link text",
    "kbd": "kit choice: the kbd chip is color.surface.raised with a border.hairline color.border.default edge, "
           "radius.control, its keys as text (§7.6: the edge is decoration, the key text identifies it)",
    "ring": "CMP-039 focus ring per E47-D04's model (PR #5387, pinned in the spec's Start line): 2 px "
            "color.focus.ring between 1 px color.surface.canvas halos, 2 px offset (outer extent 6 px)",
    "icon-sm": "size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)",
    "density": "kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact)",
    "type-150": "fallback: no type token at 150 %: each role maps to the token nearest 1.5 x (caption -> heading-md, "
                "body -> heading-lg, heading-md / heading-lg -> display), as the E47-D03 kit does",
    "zoom": "kit choice: a zoomed page is drawn at 1:1 CSS px in strips (the E47-D03 kit's zoom frame): 200 % is a "
            "640 CSS px viewport, 400 % a 320 CSS px one; each strip names its CSS y range",
}
_TOKEN_OPTS = {"fill", "stroke", "strokeWidth", "radius", "pad", "padX", "padY", "padT", "padR", "padB", "padL", "gap",
               "rowGap", "colGap", "height", "width", "minW", "minH", "opacity", "shadow"}
# --- notes (merged into every sheet; cleared by write_sheet)
NOTE_KINDS = ("sources", "copy_keys", "copy_gaps", "g_rows", "spec_gaps", "fallbacks", "tokens", "live_checks",
              "deviations", "ambiguities")


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


def ambiguity(line: str) -> None:
    """A reading the kit took where the sources leave room (also listed in build-notes.md)."""
    NOTES.add("ambiguities", line)


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
         DISPLAY: (24, 1.2, False)}


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
    """Measured, not nominal: a text box paints at ceil(size x line-height x lines) px (13 px at 1.4: 19 for one
    line, 37 for two, 55 for three, not 18.2; 11 px at 1.2: 14; 12 px at 1.2: 15), the drawing lane's live check."""
    size, lh, _m = _FONT.get(typo, _FONT[BODY])
    return float(math.ceil(round(size * lh * lines, 3)))


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




# --- CMP-039 the ring (E47-D04's geometry, FALLBACKS['ring']), drawn from nested stroke-only boards (proven in the E08
# kit's rows) so every band is token-bound: outer halo, ring, inner halo, then the offset gap, then the control.
CONTROL_H, ROW_H = 24, 24  # compact density (§0)
HALO_TOKENS = {"normal": (HAIR,), "inset": (HAIR,)}
RING_TOKENS = {"normal": (FOCUS_W,), "inset": (FOCUS_W,)}
GEOM_PX = {"normal": (2, 1, 2), "inset": (2, 1, 0)}  # (ring, halo, offset) px, E47-D04 §7.1 (FALLBACKS["ring"])


def ring_bands(variant: str) -> list[tuple[str, str]]:
    """Outside-in (colour, width token) bands of the ring; the sum of widths + the offset is the outer extent."""
    fallback("ring")
    return ([(CANVAS, t) for t in HALO_TOKENS[variant]] + [(RING, t) for t in RING_TOKENS[variant]]
            + [(CANVAS, t) for t in HALO_TOKENS[variant]])


def extent(variant: str) -> int:
    """offset + halo + ring + halo, in px (6 px normal; the self-test checks it)."""
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
    if variant != "normal":
        raise ValueError(variant)
    e = extent(variant)
    cw, ch = int(control["w"]), int(control["h"])
    band_sum = e - GEOM_PX[variant][2]
    last = PX[ring_bands(variant)[-1][1]]
    inner = dict(control, x=last + GEOM_PX[variant][2], y=last + GEOM_PX[variant][2])
    inner.pop("abs", None)
    del band_sum
    return dict(_layers(name or f"CMP-039 ring · {variant}", cw + 2 * e, ch + 2 * e, variant, inner, radius),
                note=f"focus-visible; CMP-039 {variant}: outer extent {e} px")


def inset_ring(wd: int, ht: int, *, name: str = "CMP-039 ring · inset", radius: str | None = None) -> Node:
    """CMP-039 inset (rows, cells): the bands drawn inside the element's box, no offset; place it as the row's last
    kid (abs at 0, 0)."""
    return dict(_layers(name, wd, ht, "inset", None, radius), x=0, y=0, abs=True,
                note="CMP-039 inset: drawn inside the element")


# --- annotation overlays inside a frame: numbered stops, region tags, outlines, move arrows, callouts
def marker(n: int | str, x: int, y: int, *, name: str | None = None) -> Node:
    fallback("markers")
    wd = 20 if str(n).isdigit() else 28  # an alphabetic label ("Esc") is a 28 x 20 pill (boards lens D-5)
    return hbox(name or f"stop {n}", [text("n", str(n), LABEL, TEXT_INVERSE)],
                {"justify": "center", "fill": MARK_FILL, "radius": R_BADGE}, w=wd, h=20, x=x, y=y, abs=True,
                note="annotation marker (not product UI)")


def tag(label_: str, x: int, y: int, *, name: str | None = None) -> Node:
    fallback("markers")
    return hbox((name or f"tag · {label_[:40]}").replace("/", SLASH), [text("label", label_, CAPTION, TEXT_INVERSE)],
                {"padX": INSET_XS, "radius": R_CONTROL, "fill": MARK_FILL}, h=16, x=x, y=y, abs=True,
                note="annotation tag (not product UI)")


def tag_stack(name: str, lines: Iterable[str], x: int, y: int, wd: int) -> Node:
    """A tag on several lines, for a narrow region (the 56 px NavRail; boards lens m-5)."""
    fallback("markers")
    kids = [text(f"line-{i}", s, CAPTION, TEXT_INVERSE, w=wd - 2 * PX[INSET_XS]) for i, s in enumerate(lines, 1)]
    return vbox(f"tag · {name}".replace("/", SLASH), kids, {"padX": INSET_XS, "padY": INSET_XS, "radius": R_CONTROL,
                                                            "fill": MARK_FILL}, w=wd, x=x, y=y, abs=True,
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
    """A note boxed on the frame (an annotation overlay)."""
    fallback("markers")
    ls = [ln for ln in lines if ln]
    kids = [text(f"line-{i}", s, CAPTION if i > 1 else LABEL, TEXT_1, w=wd - 2 * PX[INSET_SM])
            for i, s in enumerate(ls, 1)]
    return vbox(f"callout · {name}", kids, {"gap": STACK_XS, "pad": INSET_SM, "fill": OVERLAY, "radius": R_CONTROL,
                                            "stroke": MARK_FILL, "strokeWidth": THICK, "strokeAlign": "inner"},
                w=wd, x=x, y=y, abs=True, note="annotation callout (not product UI)")


# --- controls at compact density (24 px)
BUTTON_LOOK = {"ghost": (None, TEXT_1, BORDER), "secondary": (RAISED, TEXT_1, BORDER)}


def placeholder(name: str, w_: int, h: int = 12, fill: str = HOVER) -> Node:
    fallback("chrome")
    return rect(f"placeholder · {name}", w_, h, fill, {"radius": R_CONTROL})


def button(chars: str, variant: str = "secondary", *, name: str | None = None, lead: Node | None = None,
           focused: str | None = None) -> Node:
    """A CMP-001 button, 24 px; focused="normal" wraps it in CMP-039."""
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
    line under the text."""
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


def header_row(cols: Iterable[Col], *, fill: str = RAISED, typo: str = LABEL) -> Node:
    cs = list(cols)
    hh = max(ROW_H, int(math.ceil(text_h(typo) + 2 * PX[INSET_XS])))
    return hbox("header row", [cell(f"th · {c.key}", c.label, c.w, numeric=c.numeric, typo=typo, color=TEXT_2, h=hh)
                               for c in cs], {"fill": fill}, w=sum(c.w for c in cs), h=hh,
                note='column headers, scope="col"')


def table_row(cols: Iterable[Col], cells: dict[str, str | Node | list[Node] | None], name: str, i: int, *,
              h: int | None = None, focused: bool = False, second: dict[str, str] | None = None,
              colors: dict[str, str] | None = None, fill: str | None = None, typo: str | None = None) -> Node:
    """One body row: zebra (odd color.surface.app, even color.surface.raised: §7.6's P1, P2, P5, P6); focused adds CMP-039 inset.
    h=None: the tallest cell's content + 8 px a side, at least ROW_H (32), rounded up to 4 px."""
    cs = list(cols)
    if h is None:
        probe = [cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=1, second=(second or {}).get(c.key),
                      typo=typo)
                 for c in cs]
        need = max((est_height(dict(k, h=None)) for k in probe), default=0.0) + 2 * PX[INSET_SM]
        h = max(ROW_H, int(math.ceil(need / 4) * 4))
    unknown = set(cells) - {c.key for c in cs}
    if unknown:
        raise KeyError(f"{name}: cells for unknown columns {sorted(unknown)}")
    kids = [cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=h, second=(second or {}).get(c.key),
                 color=(colors or {}).get(c.key, TEXT_1), typo=typo) for c in cs]
    for k in kids:  # a cell's content must fit the row (no clipped or overlapping text): pass a taller h
        need = est_height(dict(k, h=None))
        if need > h:
            raise ValueError(f"{name}: cell {k['name']!r} needs about {need:.0f} px > row h {h}")
    o: dict[str, Any] = {"fill": fill or (APP if i % 2 else RAISED)}  # §7.6 measures app and raised only
    wd = sum(c.w for c in cs)
    if focused:  # CMP-039 inset on a focused row
        kids.append(inset_ring(wd, h))
    return hbox(name, kids, o, w=wd, h=h)


def table(name: str, caption_: str | None, header: Node, rows: list[Node], *, note: str | None = None) -> Node:
    """A CMP-049 table: the visible caption (type.ui.caption, secondary), the header row, a 1 px rule, the rows."""
    wd = header["w"]
    kids = [text("caption", caption_, CAPTION, TEXT_2, w=wd) if caption_ else None, header,
            rect("header rule", wd, 1, BORDER),
            vbox("rows", rows, None, w=wd, h=round(sum(est_height(r) for r in rows))) if rows else None]
    return vbox(name, kids, {"gap": STACK_XS}, w=wd, note=note)


# --- the window: SettingsLayout in the shell at 1280 x 800 (the E47-D03 kit's SCR-116 window): TopBar 48 | NavRail
# 64 · CMP-086 settings nav 208 · main 1008 | StatusBar 48; SCR-119 ("Help & about") selected in the nav (§7.1)
TOP_H, STATUS_H, NAV_W, SET_NAV_W = 48, 48, 64, 208
BODY_H = FRAME_H - TOP_H - STATUS_H  # 704
CONTENT_W = FRAME_W - NAV_W - SET_NAV_W  # 1008
MAIN_X, MAIN_Y = NAV_W + SET_NAV_W, TOP_H  # the main pane's origin in frame coordinates
PAGE_PAD = PX[INSET_XL]  # 24
PAGE_W = CONTENT_W - 2 * PAGE_PAD  # 960: the single column
TEXT_W = 720  # kit choice: the prose measure inside the column (tables take the full 960)
SECTION_GAP = PX[INSET_XL]  # 24 between sections (positional; the redlines name it)
CONTROL_H, ROW_H = 24, 24  # compact density (§0)
NAV_ENTRY_H, NAV_GAP, NAV_PAD = 28, PX[INSET_XS], PX[INSET_SM]
SCR119 = SETTINGS_NAV[-1]  # "Help & about" (`14` SCR-110's left nav; SCR-119's title)
SCR117 = "Accessibility"


def placeholder(name: str, w_: int, h: int = 12) -> Node:
    fallback("chrome")
    return rect(f"placeholder · {name}", w_, h, HOVER, {"radius": R_CONTROL})


def topbar() -> Node:
    left = hbox("left", [placeholder("wordmark", 88), placeholder("env badge", 56, 20),
                         placeholder("account picker", 136)], {"gap": INSET_MD}, h=TOP_H)
    right = hbox("right", [placeholder("health chip", 120), placeholder("user menu", 72)], {"gap": INSET_MD}, h=TOP_H)
    return hbox("TopBar (placeholder)", [left, right, rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=TOP_H - 1,
                                                          abs=True)],
                {"padX": INSET_LG, "justify": "space-between", "fill": APP}, w=FRAME_W, h=TOP_H,
                note="the shell's TopBar, not this spec's: placeholders only")


def navrail() -> Node:
    rows = [hbox(f"entry-{i}", [placeholder("glyph", 16, 16)], {"justify": "center"}, w=48, h=32) for i in range(1, 7)]
    return vbox("NavRail (placeholder)", [*rows, rect("divider", 1, BODY_H, BORDER_SUBTLE, x=NAV_W - 1, y=0, abs=True)],
                {"gap": INSET_XS, "align": "center", "padY": INSET_SM, "fill": APP}, w=NAV_W, h=BODY_H)


def statusbar() -> Node:
    return hbox("StatusBar (placeholder)", [placeholder("connection chip", 120), placeholder("env word", 56),
                                            rect("divider", FRAME_W, 1, BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"padX": INSET_LG, "gap": INSET_LG, "fill": APP}, w=FRAME_W, h=STATUS_H)


def nav_entry_y(label_: str) -> int:
    """The frame y of a settings-nav entry's top edge."""
    return MAIN_Y + NAV_PAD + SETTINGS_NAV.index(label_) * (NAV_ENTRY_H + NAV_GAP)


def settings_nav(current: str = SCR119, *, focus: str | None = None) -> Node:
    """CMP-086 SettingsNav: `nav aria-label="Settings"`, the nine entries of `14` SCR-110 as links, the current one
    selected (aria-current="page")."""
    ents = []
    for s_ in SETTINGS_NAV:
        e = hbox(f"entry · {s_}", [text("label", s_, BODY_STRONG if s_ == current else BODY, TEXT_1)],
                 {"padX": INSET_SM, "radius": R_CONTROL, **({"fill": SELECTED} if s_ == current else {})},
                 w=SET_NAV_W - 2 * NAV_PAD, h=NAV_ENTRY_H, note='aria-current="page"' if s_ == current else None)
        if s_ == focus:
            e = focus_ring(e, name=f"entry · {s_} · focused")
        ents.append(e)
    return vbox("CMP-086 SettingsNav · navigation Settings",
                [*ents, rect("divider", 1, BODY_H, BORDER_SUBTLE, x=SET_NAV_W - 1, y=0, abs=True)],
                {"gap": INSET_XS, "pad": INSET_SM, "fill": RAISED}, w=SET_NAV_W, h=BODY_H,
                note=f'nav aria-label="Settings"; entries from `14` SCR-110 L{SCR110_LINE}')



def crop(n: Node, top: float, bottom: float, y0: float = 0.0) -> Node | None:
    """Drop what a viewport [top, bottom) cannot show (it is clipped anyway), so a sheet carries only the visible
    part of a long page: positioned kids outside the range go; in a flex column the kids above the range become one
    empty spacer of their height (the layout below is unchanged) and the kids below go. Returns None when nothing of
    n (drawn at page y y0) is visible."""
    h = est_height(n)
    if y0 >= bottom or y0 + h <= top:
        return None
    kids = n.get("kids") or []
    if n["t"] != "board" or not kids:
        return n
    o = n.get("o") or {}
    if not o.get("dir"):
        keep = [c for k_ in kids if (c := crop(k_, top, bottom, y0 + float(k_.get("y", 0)))) is not None]
        return dict(n, kids=keep)
    if o.get("dir") != "column":
        return n
    gap = _px(o.get("gap"))
    y = y0 + _px(o.get("pad")) + _px(o.get("padY")) + _px(o.get("padT"))
    keep, above = [], 0.0
    for k_ in kids:
        if k_.get("abs"):
            keep.append(k_)
            continue
        kh = est_height(k_)
        if y + kh <= top:
            above += kh + gap
        elif y < bottom:
            c = crop(k_, top, bottom, y)
            if c is not None:
                keep.append(c)
        y += kh + gap
    if above:
        keep.insert(0, rect(f"spacer · {int(above - gap)} px cropped above", n.get("w") or 1, int(above - gap)))
    return dict(n, kids=keep, h=n.get("h") or int(math.ceil(h)))


def window(fid: str, page_node: Node, *, scroll: int = 0, current: str = SCR119, nav_focus: str | None = None,
           overlays: Iterable[Node] = (), note: str | None = None, main_extra: Iterable[Node] = ()) -> Node:
    """One 1280 x 800 frame: TopBar | NavRail · SettingsNav · main (the page scrolled by `scroll`) | StatusBar."""
    if fid not in {f for fs in FRAME_PLAN.values() for f in fs}:
        raise KeyError(f"{fid!r} is not a §H frame")
    fallback("density")
    page_node = crop(page_node, scroll, scroll + BODY_H) or page_node
    main = box("main · CMP-086 content", [dict(page_node, x=0, y=-scroll), *main_extra], {"fill": APP, "clip": True},
               w=CONTENT_W, h=BODY_H, note=f"<main>; scrolled {scroll} px" if scroll else "<main>")
    body = hbox("body", [navrail(), settings_nav(current, focus=nav_focus), main], {"align": "start"}, w=FRAME_W,
                h=BODY_H)
    return vbox(frame_name(fid), [topbar(), body, statusbar(), *overlays], {"fill": APP, "clip": True}, w=FRAME_W,
                h=FRAME_H, note=note)


def strips_frame(fid: str, page_node: Node, tops: Iterable[int], strip_w: int, *, note: str,
                 overlays: Iterable[Node] = ()) -> Node:
    """A zoomed page at 1:1 CSS px (FALLBACKS['zoom']): FRAME_W // strip_w strips side by side, each FRAME_H tall,
    strip i showing CSS y tops[i] .. tops[i] + FRAME_H."""
    if fid not in {f for fs in FRAME_PLAN.values() for f in fs}:
        raise KeyError(f"{fid!r} is not a §H frame")
    fallback("zoom")
    ts = list(tops)
    if len(ts) * strip_w != FRAME_W:
        raise ValueError(f"{len(ts)} strips of {strip_w} px do not fill {FRAME_W}")
    strips = []
    for i, top in enumerate(ts):
        strips.append(box(f"strip {i + 1} · CSS y {top}-{top + FRAME_H}",
                          [dict(crop(page_node, top, top + FRAME_H) or page_node, x=0, y=-top)],
                          {"fill": APP, "clip": True}, w=strip_w, h=FRAME_H, x=strip_w * i, y=0))
        if i:
            strips.append(rect(f"strip rule {i}", 2, FRAME_H, BORDER_STRONG, x=strip_w * i - 1, y=0))
    return box(frame_name(fid), [*strips, *overlays], {"fill": APP, "clip": True}, w=FRAME_W, h=FRAME_H, note=note)


# --- the statement page (§7.2 anatomy, §7.3 states, §9 feedback): built as positioned sections so every board knows
# where each item sits (estimates; the live drawer re-measures after touchTexts)
_T150 = {CAPTION: HEADING_MD, LABEL: HEADING_LG, BODY: HEADING_LG, BODY_STRONG: HEADING_LG, HEADING_SM: DISPLAY,
         HEADING_MD: DISPLAY, HEADING_LG: DISPLAY}


class Scale:
    """The in-app text scale: 1.0 = the tokens as named; 1.5 = FALLBACKS['type-150']."""

    def __init__(self, factor: float = 1.0) -> None:
        self.f = factor

    def __call__(self, typo: str) -> str:
        if self.f == 1.0:
            return typo
        fallback("type-150")
        return _T150[typo]


S1 = Scale(1.0)


@dataclass
class State:
    stale: bool = False  # §8.2: the W-7 notice above the version line
    unknown: bool = False  # §8.2: W-8
    copy: str = "default"  # default | copied | failed (CMP-033, §9)
    focus: str | None = None  # h1 | scr013 | scr117 | copy | footer
    internal_demo: bool = False  # board 04 frame 2: one synthetic internal row (§6.5)
    nav_above: bool = False  # zoomed: CMP-086's nav collapses above the content (§7.5)
    width: int = PAGE_W
    pad: int = PAGE_PAD
    stacked: bool = False  # 320 CSS px: both tables stack into label-value pairs (§7.5)
    sc: Scale = S1

    @property
    def running(self) -> str:
        return SYNTH["running_stale"] if self.stale else SYNTH["running"]


@dataclass
class Page:
    node: Node
    y: dict[str, int]  # section key -> top (page px)
    h: dict[str, int]  # section key -> height
    spots: dict[str, tuple[int, int]]  # focusable / item key -> (x, y) in page px
    height: int
    st: State

    def frame_xy(self, key: str, scroll: int = 0) -> tuple[int, int]:
        """A spot in frame coordinates when the page fills the window's main pane scrolled by `scroll`."""
        x, y = self.spots[key]
        return MAIN_X + x, MAIN_Y + y - scroll


def _th(typo: str, chars: str = "", width: float | None = None) -> int:
    return int(math.ceil(text_h(typo, text_lines(chars, typo, width) if (chars and width) else 1)))


# the link labels' measured widths at type.ui.body (the drawing lane's live check; the estimates ran 19-41 px wide)
MEASURED_LINK_W: dict[str, int] = {"link · SCR-013": 187, "link · SCR-117": 194, "link · statement": 143}


def link(chars: str, st: State, *, name: str, focused: bool = False) -> Node:
    """CMP-021 Link: color.text.link, always underlined (FALLBACKS['underline']); the underline takes the label's
    measured width where the live check measured it (MEASURED_LINK_W), else the estimate + 2."""
    fallback("underline")
    typo = st.sc(BODY)
    est = int(math.ceil(text_w(chars, typo))) + 2
    tw = MEASURED_LINK_W[name] if typo == BODY and name in MEASURED_LINK_W else est
    v = vbox(name, [text("label", chars, typo, TEXT_LINK), rect("underline", tw, 1, TEXT_LINK)], None, w=tw,
             h=_th(typo) + 2, note="CMP-021 Link: native <a>, underlined; a Tab stop")
    return focus_ring(v, name=f"{name} · focused") if focused else v


def kbd(keys: str, st: State) -> Node:
    fallback("kbd")
    typo = st.sc(BODY)
    return hbox(f"kbd · {keys}", [text("keys", keys, typo, TEXT_1)],
                {"padX": INSET_XS, "radius": R_CONTROL, "fill": RAISED, "stroke": BORDER, "strokeWidth": HAIR,
                 "strokeAlign": "inner"}, h=_th(typo) + 4, note='one <kbd> element; its text joins the keys with "+"')


def h2(chars: str, st: State) -> Node:
    return text("h2", chars, st.sc(HEADING_MD), TEXT_1, w=st.width, note="h2")


def copy_gap_h2(chars: str, where: str) -> str:
    copy_gap(f'h2 "{chars}": the section name in {where} (§11 has no heading string for it)')
    return chars


ALT_KEYS = tuple(dict.fromkeys(k_ for k_ in re.findall(r"`([^`]+)`", SPEC_LINES[L("6. Alternatives: `Alt+T`") - 1])
                               if re.fullmatch(r"(?:Alt|Ctrl|Shift)(?:\+\S+)+", k_)))
ALT_LINE = L("6. Alternatives: `Alt+T`")
_ALT_TEXT = {  # the `05` §… keyboard-table descriptions (`05`:57, :77, :78, :79) as the row words (copy gaps)
    "Alt+T": "Show a data table in place of a chart or panel",
    "Ctrl+=": "Make the text larger",
    "Ctrl+Shift+M": "Turn reduced motion on or off",
    "Ctrl+Shift+H": "Turn the high-contrast theme on or off",
}
_ALT_LINKS = ("Keyboard equivalents for every action", "How much the screen reader announces")
SCR116_TEXT = "or the font size scale in Appearance & density settings (SCR-116)"


def alternatives_rows(st: State) -> list[tuple[str, list[Node], str | None]]:
    """§7.2 item 6 in its order: Alt+T, the SCR-013 link (W-3), the SCR-117 link (W-19), Ctrl+= (+ SCR-116),
    Ctrl+Shift+M, Ctrl+Shift+H. Returns (label, trailing nodes, focus key)."""
    if ALT_KEYS != ("Alt+T", "Ctrl+=", "Ctrl+Shift+M", "Ctrl+Shift+H"):
        raise ValueError(f"§7.2 item 6 keys moved: {ALT_KEYS}")
    for k_ in ALT_KEYS:
        copy_gap(f'"{_ALT_TEXT[k_]}" before {k_}: §7.2 item 6 L{ALT_LINE} with `05`\'s keyboard table (no W-string)')
    for s_ in _ALT_LINKS:
        copy_gap(f'"{s_}" before its link: §7.2 item 6 L{ALT_LINE} (no W-string)')
    copy_gap(f'"{SCR116_TEXT}": §7.2 item 6 L{ALT_LINE} ("beside Ctrl+= the page names the SCR-116 text-scale '
             f'control"; `14` SCR-116 L{SCR116_LINE} names it "font size scale")')
    typo = st.sc(BODY)
    return [
        (_ALT_TEXT["Alt+T"], [kbd("Alt+T", st)], None),
        (_ALT_LINKS[0], [link(w("W-3"), st, name="link · SCR-013", focused=st.focus == "scr013")], "scr013"),
        (_ALT_LINKS[1], [link(w("W-19"), st, name="link · SCR-117", focused=st.focus == "scr117")], "scr117"),
        (_ALT_TEXT["Ctrl+="], [kbd("Ctrl+=", st), text("SCR-116", SCR116_TEXT, typo, TEXT_2)], None),
        (_ALT_TEXT["Ctrl+Shift+M"], [kbd("Ctrl+Shift+M", st)], None),
        (_ALT_TEXT["Ctrl+Shift+H"], [kbd("Ctrl+Shift+H", st)], None),
    ]


def _pairs(name: str, pairs: list[tuple[str, str]], st: State, i: int) -> Node:
    """A stacked table row at 320 CSS px (§7.5): label-value pairs, the label in the header's words; the table roles
    are kept (note)."""
    inner = st.width - 2 * PX[INSET_SM]
    kids = [vbox(f"pair · {lab}", [text("label", lab, st.sc(LABEL), TEXT_2, w=inner),
                                   text("value", val, st.sc(BODY), TEXT_1, w=inner)],
                 {"gap": STACK_XS, "padX": INSET_SM}, w=st.width) for lab, val in pairs]
    return vbox(name, kids, {"gap": STACK_SM, "padY": INSET_SM, "fill": APP if i % 2 else RAISED}, w=st.width,
                note="stacked row: role=row kept, each value a cell tied to its columnheader (§7.5)")


def _cols(st: State, spec_: tuple[tuple[str, str, float], ...]) -> list[Col]:
    ws = [int(st.width * f) for _k, _l, f in spec_]
    ws[-1] = st.width - sum(ws[:-1])
    return [Col(k_, lab, wd) for (k_, lab, _f), wd in zip(spec_, ws)]


LIM_COLS = (("notice", "", 0.375), ("who", "", 0.27), ("instead", "", 0.355))
CRIT_COLS = (("criterion", "Criterion", 0.54), ("level", "Level", 0.17), ("word", "Conformance level", 0.29))


def limitations_table(st: State) -> Node:
    heads = [w("W-10", part=i) for i in range(3)]
    spec_ = tuple((k_, heads[i], f) for i, (k_, _l, f) in enumerate(LIM_COLS))
    if st.stacked:
        rows = [_pairs(f"row {i:02d} · {x['id']}", [(heads[0], notice_cell(x)), (heads[1], x["impact"]),
                                                     (heads[2], x["workaround"])], st, i)
                for i, x in enumerate(STATEMENT_LIMITS, 1)]
        return vbox("CMP-049 table · Known limitations (stacked)", rows, None, w=st.width,
                    note='static table, aria-labelledby its h2; stacked at 320 CSS px')
    cols = _cols(st, spec_)
    hdr = header_row(cols, typo=st.sc(LABEL))
    rows = [table_row(cols, {"notice": notice_cell(x), "who": x["impact"], "instead": x["workaround"]},
                      f"row {i:02d} · {x['id']}", i, typo=st.sc(BODY)) for i, x in enumerate(STATEMENT_LIMITS, 1)]
    return table("CMP-049 table · Known limitations", None, hdr, rows,
                 note='static <table> (not grid), aria-labelledby its h2; three th scope="col" (W-10)')


def criteria_table(st: State, *, rows_from: int = 0, rows_to: int | None = None, header: bool = True) -> Node:
    copy_gap(f'column headers "Criterion", "Level", "Conformance level": §2.2 L{L("### 2.2 Columns")} '
             f'and §7.2 item 7 L{L("7. All criteria:")} (no W-string)')
    sel = ROWS[rows_from:rows_to]
    if st.stacked:
        rows = [_pairs(f"row {i:02d} · {r.sc}", [("Criterion", r.criterion), ("Level", r.level_words),
                                                  ("Conformance level", r.word)], st, i)
                for i, r in enumerate(sel, rows_from + 1)]
        return vbox("CMP-049 table · All criteria (stacked)", rows, None, w=st.width,
                    note="static table, aria-labelledby its h2; stacked at 320 CSS px")
    cols = _cols(st, CRIT_COLS)
    rows = [table_row(cols, {"criterion": r.criterion, "level": r.level_words, "word": r.word},
                      f"row {i:02d} · {r.sc}", i, typo=st.sc(BODY)) for i, r in enumerate(sel, rows_from + 1)]
    hdr = header_row(cols, typo=st.sc(LABEL))
    if not header:
        return vbox("CMP-049 table · All criteria (rows)", rows, None, w=st.width)
    return table("CMP-049 table · All criteria", None, hdr, rows,
                 note='static <table>, aria-labelledby its h2; Criterion th scope="row"; levels and conformance '
                      'as words only (R-9)')


def notice(st: State) -> Node | None:
    """CMP-028 Callout tone info (role="status"): W-7 (stale) or W-8 (version unknown), above the version line."""
    if not (st.stale or st.unknown):
        return None
    chars = w("W-7", SYNTH["appliesTo"], st.running) if st.stale else w("W-8")
    tw = min(TEXT_W, st.width) - 2 * PX[INSET_MD] - PX[ICON] - PX[INSET_SM] - 2
    t = text("message", chars, st.sc(BODY), TEXT_1, w=tw)
    hh = int(est_height(t)) + 2 * PX[INSET_SM]
    return hbox("CMP-028 callout · info", [icon("glyph", "info", INFO_STRONG), t,
                                           rect("start edge", 2, hh, INFO_STRONG, x=0, y=0, abs=True)],
                {"gap": INSET_SM, "padX": INSET_MD, "padY": INSET_SM, "fill": INFO_SUBTLE, "align": "start"},
                w=min(TEXT_W, st.width), h=hh,
                note='role="status"; in the DOM before the version line at first render (§7.3); the glyph and '
                     'the words carry it, never the fill alone')


def copy_button(st: State) -> Node:
    """CMP-033 CopyButton (inherits CMP-002 ghost): its glyph by state (copy / check / danger), its label W-13."""
    glyph, col = {"default": ("copy", TEXT_2), "copied": ("check", SUCCESS), "failed": ("danger", DANGER)}[st.copy]
    if st.copy == "failed":
        spec_gap("CMP-033's failed glyph is `error` (`15` CMP-033 States), not in the local icon set: drawn `danger`")
    kids = [icon("glyph", glyph, col), text("label", w("W-13"), st.sc(BODY_STRONG), TEXT_1)]
    wd = round(est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[BUTTON_PADX] + 2)
    b = hbox("CMP-033 CopyButton", kids, {"gap": INSET_XS, "padX": BUTTON_PADX, "radius": R_CONTROL,
                                          "stroke": BORDER, "strokeWidth": HAIR, "strokeAlign": "inner"},
             w=wd, h=max(CONTROL_H, _th(st.sc(BODY_STRONG)) + 8),
             note=f"native <button>, name = its label (W-13); state {st.copy}; >= 24 x 24 (2.5.8)")
    return focus_ring(b, name="CMP-033 CopyButton · focused") if st.focus == "copy" else b


def copy_status(st: State) -> Node | None:
    """CMP-033's polite region, in text (§9): W-2 once on success; W-17 then W-18 once on failure."""
    if st.copy == "copied":
        return text("polite region · W-2", w("W-2"), st.sc(BODY), TEXT_2, note="aria-live polite; said once")
    if st.copy == "failed":
        tw = max(min(TEXT_W, st.width) - 260, 200)
        return vbox("polite region · W-17 W-18", [text("W-17", w("W-17"), st.sc(BODY_STRONG), TEXT_1, w=tw),
                                                  text("W-18", w("W-18"), st.sc(BODY), TEXT_2, w=tw)],
                    {"gap": STACK_XS}, w=tw, note="aria-live polite; W-17 then W-18, once")
    return None


def footer_text(st: State) -> str:
    copy_gap(f"CMP-207 BuildFooter line: version, commit, environment and build time (`15` CMP-207); format and "
             "values synthetic")
    return (f"Version {st.running} · commit {SYNTH['commit']} · demo · built {date_words(SYNTH['issued'])}")


def statement_page(st: State | None = None) -> Page:
    """The whole page as positioned sections, top to bottom (§7.2 items 1-8, then CMP-207): one h1, an h2 per section
    from item 4 on; returns the node, each section's top / height and the focusable spots (page px)."""
    st = st or State()
    sc, W = st.sc, st.width
    tw = min(TEXT_W, W)
    gh = PX[STACK_MD]  # h2 -> body
    secs: list[tuple[str, Node, int]] = []  # key, node, gap before
    if st.nav_above:
        fallback("chrome")
        secs.append(("nav", hbox("CMP-086 SettingsNav · collapsed above the content",
                                 [text("label", "Settings", sc(LABEL), TEXT_2), placeholder("current entry", 96)],
                                 {"gap": INSET_SM, "padX": INSET_SM, "fill": RAISED, "radius": R_CONTROL},
                                 w=W, h=_th(sc(LABEL)) + 16,
                                 note='nav aria-label="Settings", collapsed above the content; its items stay in the '
                                      'Tab order (§7.5)'), 0))
    h1 = text("h1", w("W-1"), sc(HEADING_LG), TEXT_1, w=tw,
              note='h1 tabindex="-1", focused once on arrival (§7.4); the document title is W-20')
    copy_gap(f'h1 "Accessibility statement": W-1 (§11 L{COPY["W-1"].line}), the shipped link\'s words, as the page '
             f'title (§7.2 item 1 L{L("1. `h1` \"Accessibility statement\"")})')
    if st.focus == "h1":
        hw = int(text_w(w("W-1"), sc(HEADING_LG))) + 24
        h1 = focus_ring(hbox("h1 box", [{k_: v for k_, v in h1.items() if k_ != "w"}], {"padX": INSET_XS}, w=hw,
                             h=_th(sc(HEADING_LG)) + 4), name="h1 · focused")
    head = vbox("1 · h1 + status", [h1, text("status · W-5", status_words(), sc(BODY_STRONG), TEXT_1, w=tw,
                                             note="the status in words (R-9), the first text after the h1")],
                {"gap": STACK_SM}, w=W)
    secs.append(("head", head, PX[STACK_MD] if st.nav_above else 0))
    copy_gap(f'"Scope: the web app in its desktop shell.": §7.2 item 2 L{L("2. The target (W-4)")} (no W-string)')
    secs.append(("target", vbox("2 · target + scope", [text("W-4", w("W-4"), sc(BODY), TEXT_1, w=tw),
                                                      text("scope", "Scope: the web app in its desktop shell.",
                                                           sc(BODY), TEXT_1, w=tw)], {"gap": STACK_XS}, w=W),
                 PX[STACK_MD]))
    nt = notice(st)
    if nt:
        secs.append(("notice", nt, PX[STACK_MD]))
    secs.append(("version", text("3 · version line · W-6", w("W-6", SYNTH["appliesTo"], date_words(SYNTH["issued"]),
                                                                  date_words(SYNTH["reviewBy"])),
                                 sc(CAPTION), TEXT_2, w=tw, note="type.ui.caption (§7.7); text, not a control"),
                 PX[STACK_MD]))
    sup = copy_gap_h2("What is supported", f"§7.2 item 4 L{L('4. What is supported')}")
    secs.append(("supported", vbox("4 · supported", [h2(sup, st), text("W-11", w("W-11"), sc(BODY), TEXT_1, w=tw)],
                                   {"gap": STACK_MD}, w=W), SECTION_GAP))
    lim_kids: list[Node | None] = [h2(w("W-9"), st), limitations_table(st)]
    if st.internal_demo:
        cat = "security"
        lim_kids += [text("W-16", w("W-16"), sc(BODY), TEXT_1, w=tw),
                     text(f"generic · {cat}", CATEGORIES[cat], sc(BODY), TEXT_1, w=tw,
                          note="the category's one generic sentence (R-8); the row's own text stays internal")]
    secs.append(("limitations", vbox("5 · known limitations", lim_kids, {"gap": STACK_MD}, w=W), SECTION_GAP))
    alt_h2 = copy_gap_h2("Alternatives", f"§7.2 item 6 L{ALT_LINE}")
    rows, alt_spots, yy = [], {}, _th(sc(HEADING_MD)) + gh
    for i, (lab, trail, fk) in enumerate(alternatives_rows(st), 1):
        if st.stacked:
            trail = [dict(t, w=W) if t["t"] == "text" and "w" not in t else t for t in trail]
            r = vbox(f"alternative {i}", [text("label", lab, sc(BODY), TEXT_1, w=W), *trail], {"gap": STACK_XS}, w=W)
        else:
            lw = min(360, int(W * 0.45))
            room = W - lw - PX[INSET_MD] * len(trail) - sum(est_width(t) for t in trail if t["t"] != "text")
            trail = [dict(t, w=int(room)) if t["t"] == "text" and "w" not in t else t for t in trail]
            r = hbox(f"alternative {i}", [text("label", lab, sc(BODY), TEXT_1, w=lw), *trail], {"gap": INSET_MD},
                     w=W, h=max(int(est_height(t)) for t in [text("p", lab, sc(BODY), TEXT_1, w=lw), *trail]) + 4)
        alt_spots[f"alt{i}"] = yy
        if fk:
            alt_spots[fk] = yy
        rows.append(r)
        yy += int(est_height(r)) + PX[STACK_SM]
    alt = vbox("6 · alternatives", [h2(alt_h2, st), vbox("list", rows, {"gap": STACK_SM}, w=W)], {"gap": STACK_MD}, w=W,
               note="a list; the two links are the section's only Tab stops")
    secs.append(("alternatives", alt, SECTION_GAP))
    crit_h2 = copy_gap_h2("All criteria", f"§7.2 item 7 L{L('7. All criteria:')}")
    secs.append(("criteria", vbox("7 · all criteria", [h2(crit_h2, st), criteria_table(st)], {"gap": STACK_MD}, w=W),
                 SECTION_GAP))
    lines = [w("W-14", part=0), w("W-14", part=1), w("W-14", st.running, part=2)]
    tpl = vbox("template · W-14", [text(f"line {i}", s_, sc(BODY), TEXT_1, w=tw - 2 * PX[INSET_MD])
                                   for i, s_ in enumerate(lines, 1)],
               {"gap": STACK_XS, "pad": INSET_MD, "fill": RAISED, "radius": R_CONTROL, "stroke": BORDER,
                "strokeWidth": HAIR, "strokeAlign": "inner"}, w=tw,
               note="selectable static text with real line breaks; nothing personal (§9)")
    btn = copy_button(st)
    act = hbox("actions", [btn, copy_status(st)], {"gap": INSET_MD, "align": "start"}, w=W,
               h=max(int(est_height(btn)), int(est_height(copy_status(st))) if copy_status(st) else 0))
    fb = vbox("8 · report a problem", [h2(w("W-12"), st), tpl, act], {"gap": STACK_MD}, w=W)
    copy_spot = _th(sc(HEADING_MD)) + gh + int(est_height(tpl)) + gh
    secs.append(("feedback", fb, SECTION_GAP))
    foot = text("CMP-207 BuildFooter", footer_text(st), sc(CAPTION), TEXT_2, w=W,
                note="<footer>, plain text; the commit is selectable (`15` CMP-207)")
    secs.append(("footer", foot, SECTION_GAP))
    kids, ys, hs, y = [], {}, {}, st.pad
    for key, n, gap in secs:
        y += gap
        hh = int(math.ceil(est_height(n)))
        ys[key], hs[key] = y, hh
        kids.append(dict(n, x=st.pad, y=y))
        y += hh
    total = y + st.pad
    spots = {k_: (st.pad, v) for k_, v in ys.items()}
    spots["h1"] = (st.pad, ys["head"])
    spots["status"] = (st.pad, ys["head"] + _th(sc(HEADING_LG)) + PX[STACK_SM])
    spots["W-4"] = (st.pad, ys["target"])
    spots["scope"] = (st.pad, ys["target"] + _th(sc(BODY), "x", tw) + PX[STACK_XS])
    spots["supported.h2"] = (st.pad, ys["supported"])
    spots["supported.text"] = (st.pad, ys["supported"] + _th(sc(HEADING_MD)) + gh)
    spots["limitations.h2"] = (st.pad, ys["limitations"])
    spots["limitations.table"] = (st.pad, ys["limitations"] + _th(sc(HEADING_MD)) + gh)
    spots["alternatives.h2"] = (st.pad, ys["alternatives"])
    for fk, dy in alt_spots.items():
        spots[fk] = (st.pad, ys["alternatives"] + dy)
    spots["criteria.h2"] = (st.pad, ys["criteria"])
    spots["criteria.table"] = (st.pad, ys["criteria"] + _th(sc(HEADING_MD)) + gh)
    spots["criteria.rows"] = (st.pad, spots["criteria.table"][1] + ROW_H + 2 * PX[STACK_XS] + 1)
    spots["feedback.h2"] = (st.pad, ys["feedback"])
    spots["template"] = (st.pad, ys["feedback"] + _th(sc(HEADING_MD)) + gh)
    spots["copy"] = (st.pad, ys["feedback"] + copy_spot)
    node_ = box("page · SCR-119∕statement", kids, {"fill": APP}, w=W + 2 * st.pad, h=total,
                note="route /accessibility; one main, one h1; a lazy chunk (§7.1)")
    return Page(node_, ys, hs, spots, total, st)


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
        out.append("Waits on " + ", ".join(f"{k} ({GROWS[k][0]})" for k in gs))  # the full §14.2 title
    return frame_name(fid), out


def annotations(nn: int, blocks: Iterable[tuple[str, list[str]]], *, board_lines: Iterable[str] = ()) -> Node:
    """The ONE 400 px column: title (the board name), a "Board" block (§0's Draws, theme, twin, export, §H frames,
    the synthetic declaration), one block per frame, footer "page <PAGE> · board NN · r1"."""
    b = BOARDS[nn]
    head = [f"§0 L{b.line}: {b.draws}",
            f"Theme: {THEME_WORD[b.theme]}" + (f" (token-bound, set at export; one of the {COUNT['boards.twins']} "
                                               f"themed boards of §0 L{PAGE_LINE}, cap one third)"
                                               if b.theme != "dark" else ""),
            f"Frames (hand-off §H L{H_LINE}): " + ", ".join(frames_of(nn)), f"Export: {b.export}",
            "Every frame a 1280 x 800 window at compact density (§0 L" + str(PAGE_LINE) + "); markers, tags, "
            "outlines, redlines and callouts in color.status.info.default are annotation, not product UI",
            "Read-only for every role and view-as; no control on this page is T2 or T3, so no T2 rendering is drawn "
            f"(§7.8 L{L('### 7.8 Roles')}; {rule('R-11')})", SYNTHETIC, *board_lines]
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


# the live check's root heights, measured by the drawing lane (the checked want: footer end + 80, or the annotation
# column end + 80 on 01, 04 and 09); board 01's is its redraw's read-back (column end 1099 + 80)
MEASURED_H: dict[int, int] = {1: 1179, 2: 998, 3: 998, 4: 1001, 5: 998, 6: 998, 7: 998, 8: 998, 9: 1029, 10: 998}


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
    if strict and nn in MEASURED_H:
        live(f"after touchTexts + relayout: the root's h {h} is the measured max(column end, footer end) + {MARGIN} "
             f"(annotation column estimated {ah:.0f} px); read it back")
    else:
        live(f"after touchTexts + relayout: the annotation column (estimated {ah:.0f} px) ends inside the root "
             f"(h {h}); set the root's h to max(column end, footer end) + {MARGIN}")
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
        live(f"theme: activate the {b.theme} token set before exporting board {nn:02d}; read back one bound fill "
             f"(color.surface.app) as the {b.theme} value")
    live(f"export {b.export}: every frame is {FRAME_W} x {FRAME_H}; record the board id and the PNG size")
    bad = lint(nodes)
    for kind, lines in (notes or {}).items():
        for ln in [lines] if isinstance(lines, str) else lines:
            NOTES.add(kind, ln)
    NOTES.add("sources", "; ".join(f"{Path(pth).name} md5 {m[:8]}" + (f" at {SPEC_BASE}" if k_ in AT_BASE else "")
                                   for k_, (pth, m) in DOCS.items()) + f" (§0 L{b.line}; §H L{H_LINE})")
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
    if IN_REPO and sp.parent == CAP_DIR.resolve():  # the committed copy beside the kit
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



# --- self-test: python3 -I -B e47d13kit.py selftest
def selftest() -> int:
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    check(all(spec_md5_ok().values()), f"pinned md5s ({', '.join(sorted(AT_BASE))} at {SPEC_BASE}): {spec_md5_ok()}")
    check(sorted(BOARDS) == list(range(1, 11)) and str(len(BOARDS)) == COUNT["boards"], "§0: ten boards 01-10")
    check(THEMED == {2: "light", 4: "hc", 10: "light"} and str(len(THEMED)) == COUNT["boards.twins"]
          and 3 * len(THEMED) <= len(BOARDS), f"§0 themed boards {THEMED} (cap one third)")
    check(PAGE == "E47-D13 — Conformance statement", f"§0 page {PAGE!r}")
    check(sorted(FRAME_PLAN) == sorted(BOARDS) and all(f.endswith(f" · {BOARDS[nn].theme}") for nn, fs in
                                                       FRAME_PLAN.items() for f in fs),
          f"§H: {sum(map(len, FRAME_PLAN.values()))} frames, themes agree with §0")
    check("offline frame" in BOARDS[3].draws and FRAME_PLAN[3][-1] == "statement/offline · dark",
          "board 03 draws §0's offline frame (EXTRA_FRAMES)")
    check(len(COPY) == int(COUNT["copy"]) and len(w_parts("W-10")) == 3 and len(w_parts("W-14")) == 3, "§11 copy deck")
    check(sorted(GROWS) == [f"D13-G{i}" for i in range(1, 6)] and len(RULES) == 11, "§14.2 G-rows, §1.4 rules")
    check(sorted(PAIRS) == [f"P{i}" for i in range(1, 9)] and all(float(PAIRS[p_].r(t)) >= float(PAIRS[p_].bar[:-2])
                                                                  for p_ in PAIRS for t in ("dark", "light", "hc")),
          "§7.6: eight pairs, every ratio meets its bar")
    words = [r.word for r in ROWS]
    check(len(ROWS) == int(COUNT["report.rows"]) and sum(r.level == "A" for r in ROWS) == int(COUNT["report.a"])
          and words.count("Supports") == int(COUNT["report.supports"])
          and words.count("Partially Supports") == int(COUNT["report.partial"])
          and words.count("Does Not Support") == int(COUNT["report.dns"])
          and words.count("Not Applicable") == int(COUNT["report.na"]), "report rows agree with the spec's counts")
    check(len(LIMITS) == int(COUNT["limits.rows"]) and len(BLOCKED) == int(COUNT["limits.blocked"]),
          f"limitations: {len(LIMITS)} rows, {len(BLOCKED)} block sign-off")
    check(status_words() == "Partially conforms", "status in words derived from the rows (R-9)")
    check(SETTINGS_NAV[-1] == "Help & about" and "Accessibility" in SETTINGS_NAV and max(TEXT_SCALES) == 150,
          f"`14`: nav {SETTINGS_NAV}, text scales {TEXT_SCALES}")
    check(extent("normal") == 6, "CMP-039 outer extent 6 px")
    toks = {r[1] for r in json.loads(TOKENS_FILE.read_text(encoding="utf-8"))}
    used = [v for k_, v in globals().items() if k_.isupper() and isinstance(v, str) and re.match(
        r"^(color|type|space|size|radius|border|opacity)\.", v)] + [p_.fg for p_ in PAIRS.values()] \
        + [p_.bg for p_ in PAIRS.values()]
    check(all(u in toks for u in used), f"kit tokens exist ({len(set(used))}; missing "
                                        f"{sorted(set(u for u in used if u not in toks))})")
    for bad_ in (lambda: node("inst", "x"), lambda: icon("x", "clock"), lambda: hbox("x", [], {"wrap": True}),
                 lambda: text("a/b", "x"), lambda: w("W-6"), lambda: w("W-10")):
        try:
            bad_()
            check(False, "refusal")
        except (ValueError, KeyError):
            pass
    check(True, "inst, unknown icon, boolean wrap, '/', unfilled slot, unnamed part refused")
    NOTES.reset()
    pg = statement_page(State())
    check(list(pg.y) == ["head", "target", "version", "supported", "limitations", "alternatives", "criteria",
                         "feedback", "footer"] and all(pg.y[a] < pg.y[b] for a, b in zip(pg.y, list(pg.y)[1:])),
          f"page sections in §7.2 order, {pg.height} px")
    fid = FRAME_PLAN[1][0]
    fr = window(fid, pg.node)
    blk = frame_block(fid, ["self-test frame"])
    ann = annotations(1, [blk], board_lines=["Self-test sheet: one sample frame, not a board of the set"])
    path = write_sheet(1, [fr], ann, out_dir=SELFTEST_DIR, name="00-selftest.json", strict=False,
                       notes={"live_checks": ["self-test sheet: not for rendering"]})
    check(path.exists(), f"validator exit 0: {path.name}")
    md = write_md(1, path, summary="Self-test sheet (one sample frame); not a board of the set.")
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    mp = re.search(r"page `([^`]+)`", l3)
    check(bool(mp) and mp.group(1) == PAGE and l3.endswith("theme dark."), f"md line 3 parses: {l3}")  # type: ignore
    check(md_line3(4).endswith("theme hc.") and md_line3(2).endswith("theme light."), "md line 3: light and hc")
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
