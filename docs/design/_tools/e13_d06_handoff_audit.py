#!/usr/bin/env python3
"""E13-D06 (#347) audit: the design hand-off pack for the indicator surfaces.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the plan texts and the merged E13 design docs the pack
cites, `22`'s indicator operations and schemas, `23`'s topic lines, the audit registry, the icon
registry, the token JSON (dark = primitives + semantic-dark, light = + semantic-light, hc = +
semantic-hc), the calendar and the committed PNGs; then the pack and its copy deck from the
working tree.

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: CITE (a figure parsed from
   its cited line at the base), COUNT (the pack's tables, the deck, the PNG folder), HASH (sha256
   of a lifted block at the base, 12 hex), SPRINT (the calendar), RULED (R347's own figure).
   `--fill` writes `VALUE<!--=KIND:key-->`; `--check` re-derives every anchored value with a left
   boundary (G-ANCHOR; the HASH anchors as G-HASH) and refuses any other HTML comment (G-MARKER).
2. **Cites (a).** Every `DOC:line` or `` `NN`:line `` cite is read at the base (G-CITE: the lines
   exist, the range's ends are non-blank); G-VERSION is content-based: each cited range stands,
   in order and contiguous, somewhere in the file at `origin/main` (a move is fine, an edit
   FAILs); it also reads the version line (the base, every sha under it, each pinned input's last
   touch, the named-only list). G-QUOTE: every quoted string of QUOTE_MIN characters or more is
   verbatim in a source its line cites, the deck, a core source or R347's own words.
3. **Gates (b)-(k).** The redlines cell for cell against D02 §2 and D05 §6.3 (G-REDLINE); the
   deck against D04 §10.1, every quoted string verbatim at its source line (G-DECK), the keys
   (G-DECKKEY) and the frozen set's hooks (G-FROZEN); the lifted blocks' hashes (G-HASH); every
   PNG named exists (G-PNG); token names against the token JSON in three themes plus D04 §2's
   published names (G-TOKENS); the data-contract rows against `22` / `23` (G-FIELDS); the `14`
   diff = the three pointer lines + the fifteen ticks and nothing else (G-UNTOUCHED, with the
   merge-base; the other inputs byte-equal); the design-ahead dates against the calendar
   (G-AHEAD); the dry-run table (G-WALK: a pending row is accepted before the ready line, refused
   under `--strict-walk`); the icon table against the registry (G-ICONS). Then the rows (G-CROWS,
   G-GROWS, G-QROWS, G-AROWS), the ruling (G-RULED), the Storybook column (G-STORYBOOK), hygiene
   (G-HEX, G-PENPOT, G-NAMES, G-CLOSE, G-SESSION, G-STORYIDS), and the security lens's folded
   sentences (G-SEC: row (3)'s enforcer split and TM cites, row (6)'s code map and the deck's
   `codes`, the compute-failed `map` closed and verbatim at its source, every `indicator.*`
   reason in E09-D09 §3.1's form from D04 §10.2, row (1)'s text-node test, CG-2's `env` field,
   §3.1's `x-rbac` column against `22` / `23`).
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over EVERY unit of the pack
   (each heading, table row by its lead cell, rule line, prose sentence and fenced block, by
   region and location, NFKC and whitespace-normalised, with a line-shape tag per region) and
   every entry of the deck, in PIN_REL. Anchored values are pinned with their values cut out.
   `--repin-ruled` is the only writer and refuses while a placeholder is unfilled. A pin finding
   in a section another gate already FAILs prints as a NOTE line.
5. **--self-test** applies one mutation per gate (M-n) with the values frozen at the filled
   baseline; each must add exactly one FAIL, from the gate it names, and every text is restored
   byte-identically (sha256 in memory and on disk). The report is ASCII, every line at most 100
   characters.

Usage (from the repo root):
  python3 -I docs/design/_tools/e13_d06_handoff_audit.py --check [SPEC] [--json] [--fill]
  python3 -I docs/design/_tools/e13_d06_handoff_audit.py --check --strict-walk
  python3 -I docs/design/_tools/e13_d06_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e13_d06_handoff_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import datetime
import functools
import hashlib
import io
import json
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "8f182fa0c8"  # every cite was read here (the pack's Inputs line)
HEAD = "origin/main"  # G-VERSION: a cited range edited at origin/main FAILs
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E13/E13-D06.md"
DECK_REL = "docs/design/E13/E13-D06-copy.json"
TOOL_REL = "docs/design/_tools/e13_d06_handoff_audit.py"
PIN_REL = "docs/design/_tools/e13_d06_ruled_pins.txt"
PLAN14_REL = "docs/plan/14-screens-catalogue.md"
OWN_PATHS = (SPEC_REL, DECK_REL, TOOL_REL, PIN_REL, PLAN14_REL)
IMG_REL = "docs/design/E13/img"
TOKENS_REL = "packages/ui/tokens"

CITE_FILES: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "04": "docs/plan/04-security-program.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "13": "docs/plan/13-user-flows.md",
    "14": PLAN14_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "D02": "docs/design/E13/E13-D02.md",
    "D03": "docs/design/E13/E13-D03.md",
    "D03H": "docs/design/E13/E13-D03-handoff.md",
    "D04": "docs/design/E13/E13-D04.md",
    "D04H": "docs/design/E13/E13-D04-handoff.md",
    "D05": "docs/design/E13/E13-D05.md",
    "README": "docs/design/README.md",
    "CONST": "CONSTITUTION.md",
    "TM": "docs/security/threat-models/E13-indicators.md",
    "ACT": "services/api/candleviewer/audit/actions.py",
    "ICONS": "packages/ui/src/icons/registry.ts",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
}
DOC_KEYS = tuple(k for k in CITE_FILES if not k.isdigit())
# the untouched inputs: byte-equal to the merge-base (G-UNTOUCHED); `14` only by the 18 lines
UNTOUCHED = ("02", "04", "05", "06", "11", "13", "15", "16", "22", "23")
UNTOUCHED_DOCS = ("D02", "D03", "D03H", "D04", "D04H", "D05", "README", "TM", "ACT", "ICONS", "CAL")
TICKET_KEY = "E13-D06"
RULING_ID = "6512926664"
BQ_LIST_ID = "6512769876"
RULED_IDS = (
    RULING_ID,
    BQ_LIST_ID,
    "6491680793",  # ledger 1
    "6490317249",  # the owner directive
    "6495555374",  # R194
    "6364739361",  # R315
    "6363161528",  # R316
    "6356062207",  # R314
)
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
REPORT_WIDTH = 100
QUOTE_MIN = 12
# the version line (G-VERSION): the shas in order, every one a commit under the base
VERSION_SHAS = (
    BASE,
    "642114e0a9",
    "5955bca1bf",
    "aea32f6f6c",
    "f128ba6c6b",
    "afaa498076",
    "5570377b2e",
    "f437dc6b4d",
    "af5f111752",
    "5570377b2e",
    "d117dc7328",
    "5955bca1bf",
    "aea32f6f6c",
    "afaa498076",
    "299e02ad5a",
    "58db7d7002",
    "f954f38680",
    "e906565e67",
    "6359111929",
)
PINNED_DOCS = {
    "D02": "5570377b2e",
    "D03": "d117dc7328",
    "D03H": "d117dc7328",
    "D04": "5955bca1bf",
    "D04H": "aea32f6f6c",
    "D05": "afaa498076",
    "22": "299e02ad5a",
    "ACT": "299e02ad5a",
    "23": "58db7d7002",
    "14": "f954f38680",
    "15": "aea32f6f6c",
    "ICONS": "e906565e67",
    "TM": "6359111929",
}
NAMED_ONLY = (
    "#425",
    "#423",
    "#424",
    "#460",
    "#461",
    "#462",
    "#463",
    "#464",
    "#465",
    "#422",
    "#457",
    "#454",
    "#466",
    "#539",
    "#947",
    "#5008",
    "E05-T01",
    "E05-T05",
    "E05-T06",
    "E47-D05",
)
RULED_VALUES = {"bq.total": "14"}
# R347's own words (G-QUOTE accepts them verbatim); the waiver line is quoted in §13
RULING_QUOTES = (
    (
        "waived 2026-10-30 (orchestrator, the #347 ruling of record of 2026-10-30 — this comment): "
        "E13-D06 Done in Sprint 06, one sprint before Sprint 07 — reason: the design chain slipped "
        "one sprint under the compressed calendar; the pack is complete at its merge."
    ),
    (
        "owner-approved exception recorded (orchestrator under the delegation, 2026-10-30, #347 "
        "ruling, #2701 ledger addendum A row A29)"
    ),
    "E13-D05 LR-05 / Q-06; E13-D06 PROPOSED",
    "published by D04 §2, not shipped",
    "N/A — rendered, not exported",
    "RULED (orchestrator, 2026-10-30, #347 ruling of record)",
    "(#316 Done 2026-10-24; E13-D05 §4.2)",
    "lifted by exception (A29)",
    "Security engineer reviewed",
    "store pending",
    "catalogued, TBD",
    "Closes #347",
)
# the eighteen `14` lines this PR adds or changes (RULED BQ-08): the pointer line, once per screen,
# directly before the screen's sign-off checklist line, and the fifteen boxes ticked with a cite
POINTER_14 = "- **Hand-off pack:** [E13-D06.md](../design/E13/E13-D06.md) (v1, E13-D06)."
POINTER_SCREENS = ("SCR-034", "SCR-035", "SCR-036")
CHECKLIST_PREFIX = "- **Design sign-off acceptance checklist:**"
TICK = re.compile(r"\[x\] (?P<item>[^\[\]]*?) \((?P<cite>(?:E13-D0[0-9]|#316)[^()]*)\)")
FIFTEENTH = "(#316 Done 2026-10-24; E13-D05 §4.2)"
# the deck's keys (G-DECKKEY): D04 §10.2's six PROPOSED keys, else a stable row id
INDICATOR_KEYS = (
    "indicator.cap_instances",
    "indicator.cap_subpanes",
    "indicator.style_pending",
    "indicator.references_open",
    "indicator.references_owner",
    "indicator.locked",
)
ROW_ID = re.compile(
    r"^(?:d02\.12\.r(?:0[1-9]|[1-3]\d|4[0-4])|d03\.13\.r(?:0[1-9]|10)|d04\.10\.r01|d05\.lr05"
    r"|d02\.07\.errored)$"
)
D04_DECK_ROWS = (397, 451)
# the pack's own PROPOSED deck rows, in order: the A29 warm-up line, the compute-failed map
PROPOSED_ROWS = ("d05.lr05", "d02.07.errored")
D04_KEY_ROWS = (459, 464)
D02_DECK_ROWS = (453, 496)
D03_DECK_ROWS = (512, 521)
LIFTS = {"d12": ("D02", 185, 191), "d05s141": ("D05", 889, 1008), "d03s2": ("D03", 94, 119)}
# the published-not-shipped token names (D04 §2; BQ-02) and the registry ids D04 §4 cites
PUBLISHED_TOKENS = frozenset(
    {f"color.indicator.palette.{i}" for i in range(1, 9)}
    | {"opacity.indicator.fill", "size.stroke.thin", "size.stroke.regular", "size.stroke.bold"}
    | {"color.border.control", "size.row.option"}
)
REGISTRY_IDS = frozenset(
    {
        "dash.solid",
        "dash.8-4",
        "dash.8-3-2-3",
        "glyph.diamond",
        "glyph.disc",
        "glyph.square",
        "bar.full",
        "bar.narrow",
        "bar.outline",
        "pattern.dashed.provisional",
        "motion.slide",  # `15` CMP-046's phantom, named as D04 C-38 / CR-11
        "color.indicator.palette[]",  # the `15`:2471 bracket spelling, named as D04 C-33
    }
)
TOKEN_PREFIXES = (
    "color.",
    "size.",
    "space.",
    "radius.",
    "elevation.",
    "opacity.",
    "motion.",
    "type.",
)
PR_TITLE = "docs(charting-ui): E13-D06 design hand-off pack for the indicator surfaces"
LABELS = ("type/design", "area/charting-ui", "priority/p1", "handoff", "security-review")
WAIVED = ("#423", "#424", "#425", "#422")
SPRINT07_CONSUMERS = WAIVED
CAL_SPRINT06 = 6

# the pack's section heads (the first words of each heading; `section()` matches by prefix)
STATUS_HEAD = "0. Status"
LOCKED_HEAD = "1.1 Locked inputs"
FRAME_HEAD = "2. The frame register"
OPS_HEAD = "3.1 The operation set"
FIELDS_HEAD = "3.2 Rendered fields"
VOCAB_HEAD = "3.3 The vocabulary mapping"
COMP_HEAD = "4. The component inventory"
TAB_HEAD = "5.1 Tab order"
FOCUS_HEAD = "5.2 Focus moves"
PREVIEW_HEAD = "6. The live-preview rule"
REORDER_HEAD = "7. Reorder"
BUDGET_HEAD = "8.1 Budgets"
FROZEN_HEAD = "8.3 The frozen security-bearing set"
CHECKLIST_HEAD = "9.1 The `14` sign-off checklists"
SCRIPT_HEAD = "9.2 The accessibility acceptance script"
DECK_HEAD = "9.3 The deck"
REDLINE_HEAD = "10.1 Redlines per screen"
TOKENS_HEAD = "10.2 Token bindings"
TARGET_HEAD = "10.3 Targets"
ICON_HEAD = "11.1 Icons"
THUMB_HEAD = "11.2 Thumbnails"
AHEAD_HEAD = "13. The design-ahead record"
QROW_HEAD = "14. The open-questions log"
CROW_HEAD = "15.1 C-rows"
GROW_HEAD = "15.2 The G-ledger"
AROW_HEAD = "15.3 §C Copy-ready A-rows"
CONSUMER_HEAD = "16.1 Consumers"
WALK_HEAD = "16.2 The story-role dry run"
QA_HEAD = "16.3 The walkthrough protocol"
VERSION_HEAD = "17. Versioning"
RULED_HEAD = "The questions BQ-01..BQ-14"

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z0-9]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"([^"\n]*)"')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]|\b[a-z0-9-]+\.(?:com|net|org|io|dev)\b", re.IGNORECASE)
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
COMMENT_ID = re.compile(r"(?<![\w-])(\d{8,})(?![\w-])")
NAMES = re.compile(
    r"\b(?:hpe|hcl)-\w|\bworker-\d\b|\w+-orchestrator\b|\bAgent [A-Z]\b|/home/\w|/mnt/c/|userToken"
    r"|team id|file id `",
    re.IGNORECASE,
)
PENPOT_WORDS = re.compile(r"workspace URL|team/[0-9a-f]|/view\?|/workspace/", re.IGNORECASE)
CLOSING = re.compile(r"\b(?:Closes|Fixes|Resolves)\s+#\d+", re.IGNORECASE)
SESSION_WORDS = re.compile(
    r"(?<![Nn]o )\bsession (?:was )?held\b|\bengineers met\b|\bmet with the\b|\bwalked through with the (?:FE|chart-engine) lead\b"
    r"|\bsession took place and\b(?! none)|\bin the session the\b",
    re.IGNORECASE,
)
STORY_ID = re.compile(r"\bUS-[A-Z]+-\d{3}\b")
PNG_NAME = re.compile(r"`?(E13-D0[2-5]-\d\d-[a-z0-9-]+\.png)`?")
TOKEN_NAME = re.compile(
    r"`((?:" + "|".join(re.escape(p) for p in TOKEN_PREFIXES) + r")[a-z0-9.*\[\]-]+)`"
)
# a cite: a doc key (D02, D03H, README, TM, ACT, ICONS, CAL) or a backticked plan id (`14`),
# then `:n` or `:n–m`, optionally after a descriptor ("D05 F-01 :770", "D04 §13 :518"); the
# nearest preceding key in the same cell or clause binds every later `:n` reference
KEY_TOKEN = re.compile(
    r"(?<![\w-])(?:`(\d\d)`|(" + "|".join(sorted(DOC_KEYS, key=len, reverse=True)) + r"))(?![\w-])"
)
REF_TOKEN = re.compile(r"(?<=[\s`\)\(])(?<!\d):(\d{1,5})(?:[–-](\d{1,5}))?(?![\d:])")
KEY_REF = re.compile(KEY_TOKEN.pattern + r":(\d{1,5})(?:[–-](\d{1,5}))?(?![\d:])")
CLAUSE_SPLIT = re.compile(r"\s\|\s|;\s|\)\s—\s")

Values = dict[str, str]
Finding = tuple[str, str, str | None, str | None]  # (gate, message, doc, section)
Unit = tuple[str, str, str, str]  # (doc, region, loc, text)
EXTRA_PATHS: list[str] = []  # self-test lever: paths pretended changed (G-UNTOUCHED)
PLAN_OVERRIDE: list[tuple[str, str]] = []  # self-test lever: a working-tree plan text (nn, text)
PIN_UNITS_OVERRIDE: list[tuple[Unit, ...]] = []  # self-test lever: re-pinned units
HEAD_OVERRIDE: list[tuple[str, str]] = []  # self-test lever: (rel, text) pretended at origin/main
IMG_OVERRIDE: list[frozenset[str]] = []  # self-test lever: the PNG folder's names
STRICT_WALK: list[bool] = []  # --strict-walk: a pending dry-run row FAILs


# ---------------------------------------------------------------------------- git and sources


def git_out(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        ).stdout
    except OSError:
        return ""


def git_ok(*args: str) -> tuple[bool, str]:
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return False, ""
    return p.returncode == 0, p.stdout


@functools.lru_cache(maxsize=256)
def git_show(rev: str, rel: str) -> str | None:
    ok, out = git_ok("show", f"{rev}:{rel}")
    return out if ok else None


def at_head(rel: str) -> str | None:
    for r, text in reversed(HEAD_OVERRIDE):
        if r == rel:
            return text
    return git_show(HEAD, rel)


def base_lines(cid: str) -> list[str]:
    rel = CITE_FILES.get(cid)
    text = git_show(BASE, rel) if rel else None
    return (text or "").split("\n")


def base_line(cid: str, n: int) -> str:
    lines = base_lines(cid)
    return lines[n - 1] if 1 <= n <= len(lines) else ""


@functools.cache
def head_ok() -> bool:
    return bool(git_out("rev-parse", "--verify", "--quiet", f"{HEAD}^{{commit}}").strip())


@functools.cache
def under_base(sha: str) -> bool:
    full = git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").strip()
    return bool(full) and git_out("merge-base", full, BASE).strip() == full


@functools.cache
def last_touch(cid: str) -> str:
    return git_out("log", "-1", "--format=%h", "--abbrev=10", BASE, "--", CITE_FILES[cid]).strip()


def merge_base() -> str:
    return git_out("merge-base", "HEAD", HEAD).strip()


# ---------------------------------------------------------------------------- markdown helpers

COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^(#{1,6}) (.*)$")
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[A-Z_*`\"(])")


def strip_comments(text: str) -> str:
    return COMMENT.sub("", text)


def fenced(lines: list[str]) -> list[bool]:
    out, open_, mark = [], False, ""
    for ln in lines:
        m = FENCE_OPEN.match(ln)
        if m and not open_:
            open_, mark = True, m[1]
            out.append(True)
        elif m and open_ and ln.strip().startswith(mark):
            out.append(True)
            open_ = False
        else:
            out.append(open_)
    return out


def section(text: str, head: str) -> str:
    """The body under the heading whose text starts with `head`, up to the next heading of the
    same or a higher level."""
    lines = text.split("\n")
    fence = fenced(lines)
    start = level = None
    for i, ln in enumerate(lines):
        m = HEADING.match(ln) if not fence[i] else None
        if m and start is None and m[2].startswith(head):
            start, level = i, len(m[1])
        elif m and start is not None and len(m[1]) <= (level or 9):
            return "\n".join(lines[start + 1 : i])
    return "\n".join(lines[start + 1 :]) if start is not None else ""


def h2_at(text: str, line_no: int) -> str:
    cur = "(top)"
    for i, ln in enumerate(text.split("\n"), 1):
        m = HEADING.match(ln)
        if m and len(m[1]) == 2:
            cur = m[2]
        if i == line_no:
            return cur
    return cur


def h2_of(text: str, head: str) -> str:
    for ln in text.split("\n"):
        m = HEADING.match(ln)
        if m and m[2].startswith(head):
            if len(m[1]) == 2:
                return m[2]
            return h2_at(text, text.split("\n").index(ln) + 1)
    return "(top)"


def split_row(line: str) -> list[str]:
    body = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def is_rule(line: str) -> bool:
    cells = split_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def table_rows(block: str) -> list[list[str]]:
    rows = []
    for ln in block.split("\n"):
        if ln.lstrip().startswith("|") and not is_rule(ln):
            rows.append(split_row(strip_comments(ln)))
    return rows[1:] if rows else []  # drop the header row


def rows_of(text: str, head: str) -> list[list[str]]:
    return table_rows(section(text, head))


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", strip_comments(s))
    s = re.sub(r"[*`_]", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def pin_norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


def unquote(s: str) -> str:
    return s.strip().strip('"“”').strip()


def ascii_line(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def report(line: str) -> str:
    s = ascii_line(line)
    return s if len(s) <= REPORT_WIDTH else s[: REPORT_WIDTH - 3] + "..."


def F(tag: str, msg: str, doc: str | None, sec: str | None) -> Finding:
    return (tag, msg, doc, sec)


@dataclass(frozen=True)
class Texts:
    spec: str
    deck: str
    plans: tuple[tuple[str, str], ...]  # (cite id, working-tree text) for every untouched input
    vals: tuple[tuple[str, str], ...]

    @property
    def values(self) -> Values:
        return dict(self.vals)


def spec_sec(t: Texts, head: str) -> str:
    return h2_of(t.spec, head)


def deck_data(deck: str) -> dict[str, object]:
    try:
        d = json.loads(deck)
    except json.JSONDecodeError:
        return {}
    return d if isinstance(d, dict) else {}


def deck_entries(deck: str) -> dict[str, dict[str, object]]:
    s = deck_data(deck).get("strings")
    return s if isinstance(s, dict) else {}


# ---------------------------------------------------------------------------- values


def figure_at(cid: str, n: int, pattern: str) -> str:
    m = re.search(pattern, strip_comments(base_line(cid, n)))
    return m[1] if m else "?"


def cite_values() -> Values:
    return {
        "perf.scr034": figure_at("14", 874, r"<=\s?(\d+)\s?ms"),
        "perf.scr035": figure_at("14", 892, r"\(<=\s?(\d+)\s?ms\)"),
        "perf.pane": figure_at("06", 78, r"≤(\d+)ms"),
    }


@functools.cache
def cal_start() -> datetime.date:
    m = re.search(
        r"SPRINT01_START = datetime\.date\((\d{4}), (\d{1,2}), (\d{1,2})\)",
        base_lines("CAL") and "\n".join(base_lines("CAL")),
    )
    return datetime.date(int(m[1]), int(m[2]), int(m[3])) if m else datetime.date(2026, 9, 25)


@functools.cache
def cal_days() -> int:
    m = re.search(r"SPRINT_DAYS = (\d+)", "\n".join(base_lines("CAL")))
    return int(m[1]) if m else 7


def sprint_start(n: int) -> datetime.date:
    return cal_start() + datetime.timedelta(days=(n - 1) * cal_days())


def sprint_of(day: datetime.date) -> int:
    return (day - cal_start()).days // cal_days() + 1


def sprint_values() -> Values:
    return {
        "gate.s08": (sprint_start(CAL_SPRINT06 + 1) - datetime.timedelta(days=1)).isoformat(),
        "s07.start": sprint_start(7).isoformat(),
        "s08.start": sprint_start(8).isoformat(),
    }


def lift_text(key: str) -> str:
    cid, a, b = LIFTS[key]
    return "\n".join(base_lines(cid)[a - 1 : b])


def hash_values() -> Values:
    return {k: hashlib.sha256(lift_text(k).encode("utf-8")).hexdigest()[:12] for k in LIFTS}


def img_names() -> frozenset[str]:
    if IMG_OVERRIDE:
        return IMG_OVERRIDE[-1]
    folder = ROOT / IMG_REL
    return frozenset(p.name for p in folder.glob("*.png")) if folder.is_dir() else frozenset()


def walk_item_count(spec: str) -> int:
    body = section(spec, QA_HEAD)
    return len([ln for ln in body.split("\n") if re.match(r"^\d{1,2}\. ", ln)])


def count_values(spec: str, deck: str) -> Values:
    entries = deck_entries(deck)
    return {
        "pngs": str(len(img_names())),
        "deck": str(len(entries)),
        "deck.keyed": str(sum(1 for e in entries.values() if e.get("indicator_keys"))),
        "deck.frozen": str(sum(1 for e in entries.values() if e.get("frozen"))),
        "themes": str(len(THEMES)),
        "walk.items": str(walk_item_count(spec)),
    }


def compute(spec: str, deck: str) -> Values:
    out: Values = {}
    for kind, vals in (
        ("CITE", cite_values()),
        ("COUNT", count_values(spec, deck)),
        ("HASH", hash_values()),
        ("SPRINT", sprint_values()),
        ("RULED", RULED_VALUES),
    ):
        out.update({f"{kind}:{k}": v for k, v in vals.items()})
    return out


def code_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in CODE.finditer(line)]


def in_code(line: str, pos: int) -> bool:
    return any(a <= pos < b for a, b in code_spans(line))


def fill(text: str, values: Values) -> tuple[str, list[str]]:
    unknown: list[str] = []

    def sub(m: re.Match[str]) -> str:
        key = m[1]
        if key not in values:
            unknown.append(key)
            return m[0]
        return f"{values[key]}<!--={key}-->"

    out = []
    for ln in text.split("\n"):
        pieces, last = [], 0
        for m in PLACEHOLDER.finditer(ln):
            if in_code(ln, m.start()):
                continue
            pieces.append(ln[last : m.start()])
            pieces.append(sub(m))
            last = m.end()
        pieces.append(ln[last:])
        out.append("".join(pieces))
    return "\n".join(out), unknown


def anchored(line: str) -> list[tuple[str, str, int]]:
    """(key, value as written, position) for every `VALUE<!--=KEY-->` on a line."""
    out = []
    for m in ANCHOR.finditer(line):
        left = line[: m.start()]
        v = re.search(r"(\d{4}-\d{2}-\d{2}|[a-f0-9]{12}|\d+(?:\.\d+)?)$", left)
        out.append((m[1], v[1] if v else "", m.start()))
    return out


def g_anchor_doc(text: str, values: Values) -> list[Finding]:
    bad: list[Finding] = []
    for i, ln in enumerate(text.split("\n"), 1):
        for key, val, _pos in anchored(ln):
            tag = "G-HASH" if key.startswith("HASH:") else "G-ANCHOR"
            if key not in values:
                bad.append(F(tag, f"line {i}: no computed value for {key}", "spec", h2_at(text, i)))
            elif val != values[key]:
                bad.append(
                    F(
                        tag,
                        f"line {i}: {key} reads {val!r}, computed {values[key]!r}",
                        "spec",
                        h2_at(text, i),
                    )
                )
        for m in PLACEHOLDER.finditer(ln):
            if not in_code(ln, m.start()):
                bad.append(
                    F("G-ANCHOR", f"line {i}: unfilled placeholder {m[0]}", "spec", h2_at(text, i))
                )
    return bad


def g_marker_doc(text: str) -> list[Finding]:
    bad: list[Finding] = []
    for i, ln in enumerate(text.split("\n"), 1):
        for m in COMMENT.finditer(ln):
            if not ANCHOR.fullmatch(m[0]):
                bad.append(
                    F(
                        "G-MARKER",
                        f"line {i}: an HTML comment that is not a value anchor",
                        "spec",
                        h2_at(text, i),
                    )
                )
    return bad


def g_hex(t: Texts) -> list[Finding]:
    bad = []
    for doc, text in (("spec", t.spec), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            if HEXLIT.search(ln):
                bad.append(
                    F(
                        "G-HEX",
                        f"{doc} line {i}: a hex colour literal",
                        doc,
                        h2_at(text, i) if doc == "spec" else "(deck)",
                    )
                )
    return bad


# ---------------------------------------------------------------------------- cites (a)


def cite_refs(line: str) -> list[tuple[str, int, int]]:
    """(cite id, first, last) for every cite on a rendered line: the nearest preceding key in
    the same cell or clause binds each `:n` reference."""
    out: list[tuple[str, int, int]] = []
    for clause in CLAUSE_SPLIT.split(strip_comments(line)):
        events: list[tuple[int, str, object]] = []
        for m in KEY_TOKEN.finditer(clause):
            events.append((m.start(), "key", m[1] or m[2]))
        for m in KEY_REF.finditer(clause):
            events.append((m.end() - 1, "ref", (int(m[3]), int(m[4]) if m[4] else int(m[3]))))
        for m in REF_TOKEN.finditer(clause):
            events.append((m.start(), "ref", (int(m[1]), int(m[2]) if m[2] else int(m[1]))))
        events.sort(key=lambda e: e[0])
        cur: str | None = None
        for pos, kind, val in events:
            if kind == "key":
                cur = str(val)
            elif cur is not None and cur in CITE_FILES:
                a, b = val  # type: ignore[misc]
                out.append((cur, a, b))
    return out


def unique_block(base: list[str], a: int, b: int) -> list[str]:
    lo, hi = a - 1, b
    while base[lo:hi] and base.count(base[lo]) > 1 and (lo > 0 or hi < len(base)):
        lo, hi = max(0, lo - 1), min(len(base), hi + 1)
    return base[lo:hi]


def block_in(hay: list[str], block: list[str]) -> bool:
    n = len(block)
    return any(hay[i : i + n] == block for i in range(len(hay) - n + 1)) if block else True


def cite_findings(t: Texts) -> tuple[list[Finding], int]:
    fails: list[Finding] = []
    done: set[tuple[str, int, int]] = set()
    if not head_ok():
        fails.append(
            F("G-VERSION", f"{HEAD} does not resolve: no cited range compared", None, None)
        )
    sources = [("spec", t.spec)]
    deck_lines = [
        f"{k} {e.get('source', '')} {e.get('row', '')}" for k, e in deck_entries(t.deck).items()
    ]
    sources.append(("deck", "\n".join(deck_lines)))
    for doc, text in sources:
        for i, ln in enumerate(text.split("\n"), 1):
            sec = h2_at(text, i) if doc == "spec" else "(deck)"
            for cid, a, b in cite_refs(ln):
                if (cid, a, b) in done:
                    continue
                done.add((cid, a, b))
                lines = base_lines(cid)
                if not lines or lines == [""]:
                    fails.append(F("G-CITE", f"{cid} is not readable at the base", doc, sec))
                    continue
                if a < 1 or b > len(lines) or b < a:
                    fails.append(
                        F(
                            "G-CITE",
                            f"{cid}:{a}–{b} is outside the file ({len(lines)} lines)",
                            doc,
                            sec,
                        )
                    )
                    continue
                if not lines[a - 1].strip() or not lines[b - 1].strip():
                    fails.append(
                        F("G-CITE", f"{cid}:{a}–{b} starts or ends on a blank line", doc, sec)
                    )
                if head_ok():
                    head = (at_head(CITE_FILES[cid]) or "").split("\n")
                    if not block_in(head, unique_block(lines, a, b)):
                        fails.append(
                            F("G-VERSION", f"{cid}:{a}–{b} was edited at {HEAD}", doc, sec)
                        )
    return fails, len(done)


def source_text(cid: str) -> str:
    return "\n".join(base_lines(cid))


def loose(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[‐-―−]", "-", s).replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


@functools.cache
def core_sources() -> str:
    return loose(
        "\n".join(
            source_text(c)
            for c in ("D02", "D03", "D04", "D05", "14", "15", "22", "23", "README", "TM")
        )
    )


def g_quote(t: Texts) -> list[Finding]:
    """Every quoted string of QUOTE_MIN+ characters is verbatim in a source the line cites, the
    deck, a core source or R347's own words."""
    entries = deck_entries(t.deck)
    deck_text = loose(
        "\n".join(
            str(e.get("text", "")) + " " + " ".join(map(str, e.get("strings", [])))
            for e in entries.values()
        )
    )
    ruled = loose("\n".join(RULING_QUOTES))
    bad: list[Finding] = []
    arow = h2_of(t.spec, AROW_HEAD)
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if h2_at(t.spec, i) == arow and ln.startswith("| A-"):
            continue  # copy-ready text is authored here
        cited = loose("\n".join(source_text(c) for c, _a, _b in cite_refs(ln)))
        for q in QUOTED.findall(strip_comments(ln)):
            q = q.strip()
            if len(q) < QUOTE_MIN or "…" in q or "<" in q or q.endswith("-form"):
                continue
            lq = loose(q)
            if lq in cited or lq in deck_text or lq in ruled or lq in core_sources():
                continue
            bad.append(
                F(
                    "G-QUOTE",
                    f"line {i}: {q[:60]!r} is in no cited source, the deck or R347",
                    "spec",
                    h2_at(t.spec, i),
                )
            )
    return bad


def g_version(t: Texts) -> list[Finding]:
    lines = t.spec.split("\n")
    i = next((n for n, ln in enumerate(lines) if ln.startswith("**Start.**")), None)
    if i is None:
        return [F("G-VERSION", "no **Start.** line", "spec", "(top)")]
    line, sec = lines[i], h2_at(t.spec, i + 1)
    bad: list[Finding] = []
    if f"**v1 at base `{BASE}`.**" not in line:
        bad.append(F("G-VERSION", "the version line does not name v1 at the base", "spec", sec))
    got = tuple(re.findall(r"`([0-9a-f]{10})`", line))
    if got != VERSION_SHAS:
        bad.append(
            F(
                "G-VERSION",
                f"the version line carries {len(got)} shas, not the {len(VERSION_SHAS)} in order",
                "spec",
                sec,
            )
        )
    bad += [
        F("G-VERSION", f"`{s}` is not a commit under the base", "spec", sec)
        for s in got
        if not under_base(s)
    ]
    pinned = line.split("**Pinned at their last touch at the base:**", 1)[-1].split("**", 1)[0]
    for cid, sha in PINNED_DOCS.items():
        last = last_touch(cid)
        if last != sha or sha not in pinned:
            bad.append(F("G-VERSION", f"{cid} pinned at {sha}, last touched {last}", "spec", sec))
    named = line.split("**Named only, never pinned or quoted:**", 1)[-1].split("**", 1)[0]
    bad += [
        F("G-VERSION", f"{n} is not in the named-only list", "spec", sec)
        for n in NAMED_ONLY
        if n not in named
    ]
    if "**Late changes:**" not in line:
        bad.append(F("G-VERSION", "the version line has no late-changes field", "spec", sec))
    inputs = next((ln for ln in lines if ln.startswith("**Inputs pinned.**")), "")
    if inputs.count(BASE) < 2:
        bad.append(
            F("G-VERSION", f"the Inputs line does not name the base {BASE} twice", "spec", sec)
        )
    body = norm_text(section(t.spec, VERSION_HEAD))
    for need in (
        f"v1 at base {BASE}",
        "re-sync needed",
        "posted once on each affected consumer",
        "at PR 3's merge",
    ):
        if norm_text(need) not in body:
            bad.append(F("G-VERSION", f"§17 lacks {need!r}", "spec", spec_sec(t, VERSION_HEAD)))
    d = deck_data(t.deck)
    if d.get("base") != BASE or d.get("version") != "v1" or d.get("pack") != TICKET_KEY:
        bad.append(
            F(
                "G-VERSION",
                "the deck's pack, base or version is not E13-D06 v1 at the base",
                "deck",
                "(deck)",
            )
        )
    return bad


# ---------------------------------------------------------------------------- (b) redlines


def d02_anatomy() -> dict[str, list[str]]:
    rows = {}
    for n in range(60, 74):
        cells = split_row(base_line("D02", n))
        if len(cells) >= 3:
            rows[pin_norm(cells[0])] = cells
    return rows


def d05_targets() -> dict[str, list[str]]:
    rows = {}
    for n in range(466, 486):
        cells = split_row(base_line("D05", n))
        if len(cells) >= 8:
            rows[cells[0].strip("`")] = cells
    return rows


def g_redline(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, REDLINE_HEAD)
    src = d02_anatomy()
    rows = rows_of(t.spec, REDLINE_HEAD)
    if len(rows) != len(src):
        bad.append(
            F("G-REDLINE", f"§10.1 carries {len(rows)} rows, D02 §2 {len(src)}", "spec", sec)
        )
    for r in rows:
        key = pin_norm(r[0])
        if key not in src:
            bad.append(F("G-REDLINE", f"§10.1 row {r[0][:40]!r} has no D02 §2 row", "spec", sec))
            continue
        for col, name in ((1, "compact"), (2, "comfortable")):
            if pin_norm(r[col]) != pin_norm(src[key][col]):
                bad.append(
                    F(
                        "G-REDLINE",
                        f"§10.1 {r[0][:30]!r} {name} {r[col]!r} != D02 {src[key][col]!r}",
                        "spec",
                        sec,
                    )
                )
    tsec = spec_sec(t, TARGET_HEAD)
    tsrc = d05_targets()
    trows = rows_of(t.spec, TARGET_HEAD)
    if len(trows) != len(tsrc):
        bad.append(
            F("G-REDLINE", f"§10.3 carries {len(trows)} rows, D05 §6.3 {len(tsrc)}", "spec", tsec)
        )
    for r in trows:
        tid = r[0].strip("`")
        if tid not in tsrc or len(r) < 6:
            bad.append(F("G-REDLINE", f"§10.3 row {tid!r} has no D05 §6.3 row", "spec", tsec))
            continue
        s = tsrc[tid]
        pairs = (
            (1, 1, "surface"),
            (2, 2, "density"),
            (3, 5, "smaller px"),
            (4, 6, "dimension kind"),
            (5, 7, "spec"),
        )
        for mine, theirs, name in pairs:
            if pin_norm(r[mine].strip("`")) != pin_norm(s[theirs].strip("`")):
                bad.append(
                    F(
                        "G-REDLINE",
                        f"§10.3 {tid} {name} {r[mine]!r} != D05 {s[theirs]!r}",
                        "spec",
                        tsec,
                    )
                )
    return bad


# ---------------------------------------------------------------------------- (c) the deck


def d04_deck_rows() -> dict[int, list[str]]:
    a, b = D04_DECK_ROWS
    return {n: split_row(base_line("D04", n)) for n in range(a, b + 1)}


def source_holds(source: str, strings: list[str]) -> list[str]:
    m = re.fullmatch(r"(D0[2-5]):(\d+)", source.strip())
    if not m:
        return ["unparsable source"]
    line = loose(base_line(m[1], int(m[2])))
    return [s for s in strings if loose(s) not in line]


def g_deck(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    entries = deck_entries(t.deck)
    by_row = {str(e.get("row", "")): (k, e) for k, e in entries.items()}
    rows = d04_deck_rows()
    for n, cells in rows.items():
        key = f"D04:{n}"
        if key not in by_row:
            bad.append(
                F("G-DECK", f"D04 §10.1 row :{n} is missing from the deck", "deck", "(deck)")
            )
            continue
        k, e = by_row[key]
        if pin_norm(str(e.get("text", ""))) != pin_norm(cells[1]):
            bad.append(F("G-DECK", f"{k}: text is not D04 :{n}'s cell verbatim", "deck", "(deck)"))
        strings = [str(s) for s in e.get("strings", [])]
        if strings != QUOTED.findall(cells[1]):
            bad.append(
                F(
                    "G-DECK",
                    f"{k}: strings are not the quoted strings of D04 :{n}",
                    "deck",
                    "(deck)",
                )
            )
        missing = source_holds(str(e.get("source", "")), strings)
        if missing:
            bad.append(
                F(
                    "G-DECK",
                    f"{k}: {missing[0][:40]!r} is not verbatim at {e.get('source')}",
                    "deck",
                    "(deck)",
                )
            )
    extra = [k for k, e in entries.items() if not re.fullmatch(r"D04:\d+", str(e.get("row", "")))]
    if extra != list(PROPOSED_ROWS):
        bad.append(
            F(
                "G-DECK",
                f"the deck's non-D04 entries are {extra}, expected {list(PROPOSED_ROWS)}",
                "deck",
                "(deck)",
            )
        )
    a29 = entries.get("d05.lr05", {})
    if a29 and source_holds(str(a29.get("source", "")), [str(s) for s in a29.get("strings", [])]):
        bad.append(F("G-DECK", "d05.lr05's string is not verbatim at its source", "deck", "(deck)"))
    if a29 and RULING_QUOTES[1] not in str(a29.get("notes", "")):
        bad.append(F("G-DECK", "d05.lr05 lacks the A29 stamp", "deck", "(deck)"))
    want = len(rows) + len(PROPOSED_ROWS)
    if len(entries) != want:
        bad.append(
            F("G-DECK", f"the deck holds {len(entries)} entries, expected {want}", "deck", "(deck)")
        )
    return bad


def g_deckkey(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    entries = deck_entries(t.deck)
    a, b = D04_KEY_ROWS
    published = "\n".join(base_lines("D04")[a - 1 : b])
    for key in INDICATOR_KEYS:
        if f"`{key}`" not in published:
            bad.append(F("G-DECKKEY", f"{key} is not one of D04 §10.2's keys", "deck", "(deck)"))
    carried = {k for e in entries.values() for k in e.get("indicator_keys", [])}
    for key in INDICATOR_KEYS:
        if key not in carried:
            bad.append(F("G-DECKKEY", f"{key} is carried by no entry", "deck", "(deck)"))
    for k, e in entries.items():
        keys = [str(x) for x in e.get("indicator_keys", [])]
        if keys:
            if (
                k != keys[0]
                or e.get("key_status") != "PROPOSED (D04 §10.2)"
                or any(x not in INDICATOR_KEYS for x in keys)
            ):
                bad.append(
                    F(
                        "G-DECKKEY",
                        f"{k}: a keyed entry must be keyed by its first `indicator.*` key, PROPOSED",
                        "deck",
                        "(deck)",
                    )
                )
        elif not ROW_ID.match(k) or e.get("key_status") != "row id" or e.get("row_id") != k:
            bad.append(
                F(
                    "G-DECKKEY",
                    f"{k}: not a stable row id with key_status 'row id'",
                    "deck",
                    "(deck)",
                )
            )
    return bad


def g_frozen(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, FROZEN_HEAD)
    entries = deck_entries(t.deck)
    rows = rows_of(t.spec, FROZEN_HEAD)
    ids = [r[0] for r in rows]
    if ids != [f"({i})" for i in range(1, 8)]:
        bad.append(F("G-FROZEN", f"the frozen set is {ids}, not (1)..(7)", "spec", sec))
    deck_text = loose("\n".join(" ".join(map(str, e.get("strings", []))) for e in entries.values()))
    hooked: set[str] = set()
    for r in rows:
        if len(r) < 5 or any(not c.strip() for c in r[:5]):
            bad.append(F("G-FROZEN", f"row {r[0]} has an empty cell", "spec", sec))
            continue
        for q in QUOTED.findall(r[1]):
            if len(q) >= QUOTE_MIN and loose(q) not in deck_text:
                bad.append(
                    F("G-FROZEN", f"row {r[0]}: {q[:40]!r} is not a deck string", "spec", sec)
                )
        for key in re.findall(r"`([a-z0-9_.]+)`", r[4]):
            if key in entries:
                hooked.add(key)
                if entries[key].get("frozen") != r[0]:
                    bad.append(
                        F(
                            "G-FROZEN",
                            f"row {r[0]}: deck entry {key} is not flagged frozen {r[0]}",
                            "deck",
                            "(deck)",
                        )
                    )
    for k, e in entries.items():
        if e.get("frozen") and k not in hooked:
            bad.append(
                F(
                    "G-FROZEN",
                    f"deck entry {k} is frozen {e.get('frozen')} but no §8.3 row hooks it",
                    "deck",
                    "(deck)",
                )
            )
        if e.get("frozen") and not str(e.get("breaks", "")).strip():
            bad.append(
                F(
                    "G-FROZEN",
                    f"deck entry {k} is frozen without a `breaks` sentence",
                    "deck",
                    "(deck)",
                )
            )
    return bad


# ---------------------------------------------------------------------------- (l) the security lens (G-SEC)

# row (6)'s map: the problem / WS code -> the deck entry that renders it (never the body's text)
SEC_CODES = {
    "422 validation_failed": "d02.12.r19",
    "409 name_taken": "d02.12.r25",
    "409 limit_reached": "d02.12.r12",
    "sub_ok subscription_limit": "d02.12.r10",
    "err internal_error": "d02.07.errored",
}
SEC_ROW6_WORDS = ("`422`", "`409`", "`403`", "`413`", "`503`", "`sub_ok`", "`err`", "never echoed")
SEC_ROW6_FIELDS = ("`title`", "`detail`", "`errors[].message`")
SEC_ROW3_WORDS = ("client state gate", "T2-09", "T2-10", "hidden instances counted")
SEC_ROW3_CITES = ("TM:110 (20 / 6)", ":111 (8)", ":115 (500)", "remain TM proposals")
SEC_ROW1_WORDS = ("text nodes", "`dangerouslySetInnerHTML`", "`$ref`", "`pattern`", "`description`")
SEC_TM_ROWS = (
    (110, "<= 20 indicator instances per chart"),
    (111, "<= 8 server instances per user"),
    (115, "<= 500 live presets per user"),
)
COMPUTE_FAILED = "d02.07.errored"
COMPUTE_FAILED_TEXT = "Compute failed: <reason>"
REASON_MAX = 60
REASON_DIGITS = {"20", "6"}  # the caps are the only numbers a reason may carry


def x_rbac_of(api: list[str], start: int) -> tuple[str, bool] | None:
    """`22`'s `x-rbac` line and whether the operation takes the CSRF token, read from the
    operation block that starts at `start` (1-based) up to the next `operationId:`."""
    rbac, csrf = "", False
    for ln in api[start - 1 :]:
        if "operationId:" in ln and ln is not api[start - 1]:
            break
        if "x-rbac:" in ln:
            rbac = ln
        if "CsrfToken" in ln:
            csrf = True
    m = re.search(r"permissions: \[([^\]]+)\], scope: (\w+)", rbac)
    return (f"`{m[1]}` · `{m[2]}`", csrf) if m else None


def g_sec(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, FROZEN_HEAD)
    entries = deck_entries(t.deck)
    rows = {r[0]: r for r in rows_of(t.spec, FROZEN_HEAD)}

    def cell(rid: str, i: int) -> str:
        r = rows.get(rid, [])
        return r[i] if len(r) > i else ""

    # H-1 / L-2: row (3) splits the caps by enforcer, cites TM's rows and tests the client gate
    for need in (*SEC_ROW3_WORDS, *SEC_ROW3_CITES):
        if need not in cell("(3)", 1):
            bad.append(F("G-SEC", f"row (3) does not carry {need!r}", "spec", sec))
    if "no network call" not in cell("(3)", 4):
        bad.append(
            F(
                "G-SEC",
                "row (3)'s hook does not test the 21st add without a network call",
                "spec",
                sec,
            )
        )
    tm = base_lines("TM")
    for n, words in SEC_TM_ROWS:
        if len(tm) < n or words not in tm[n - 1]:
            bad.append(F("G-SEC", f"TM:{n} no longer reads {words!r}", "spec", sec))
    # M-1: row (6) names every code and field; every mapped code is carried by its deck entry
    for need in (*SEC_ROW6_WORDS, *SEC_ROW6_FIELDS):
        if need not in cell("(6)", 1):
            bad.append(F("G-SEC", f"row (6) does not name {need}", "spec", sec))
    hook = cell("(6)", 4)
    carried = {str(c): k for k, e in entries.items() for c in e.get("codes", [])}
    for code, key in SEC_CODES.items():
        if carried.get(code) != key:
            bad.append(F("G-SEC", f"{code} is not carried by deck entry {key}", "deck", "(deck)"))
        if key not in hook or code.split(" ", 1)[1] not in hook:
            bad.append(F("G-SEC", f"row (6)'s hook does not map {code} to {key}", "spec", sec))
    # M-2: the compute-failed row is PROPOSED, its map closed and verbatim at its source
    cf = entries.get(COMPUTE_FAILED)
    if cf is None:
        bad.append(F("G-SEC", f"the deck has no {COMPUTE_FAILED} entry", "deck", "(deck)"))
    else:
        strings = [str(x) for x in cf.get("strings", [])]
        cmap = cf.get("map")
        if not isinstance(cmap, dict) or "internal_error" not in cmap:
            bad.append(
                F("G-SEC", f"{COMPUTE_FAILED}: no closed map with internal_error", "deck", "(deck)")
            )
        else:
            sentences = [str(v) for v in cmap.values()]
            if source_holds(str(cf.get("map_source", "")), sentences):
                bad.append(
                    F(
                        "G-SEC",
                        f"{COMPUTE_FAILED}: a map sentence is not verbatim at its source",
                        "deck",
                        "(deck)",
                    )
                )
            if any(v not in strings for v in sentences):
                bad.append(
                    F(
                        "G-SEC",
                        f"{COMPUTE_FAILED}: a map sentence is not one of the entry's strings",
                        "deck",
                        "(deck)",
                    )
                )
        if COMPUTE_FAILED_TEXT not in strings or source_holds(
            str(cf.get("source", "")), [COMPUTE_FAILED_TEXT]
        ):
            bad.append(
                F(
                    "G-SEC",
                    f"{COMPUTE_FAILED}: the row's text is not at its source",
                    "deck",
                    "(deck)",
                )
            )
        if cf.get("status") != "PROPOSED" or "(Q-16)" not in str(cf.get("notes", "")):
            bad.append(
                F("G-SEC", f"{COMPUTE_FAILED}: not PROPOSED with its Q-16 stamp", "deck", "(deck)")
            )
    # M-3: row (5) hooks indicator.locked; every key's reason is D04 §10.2's candidate sentence
    if "`indicator.locked`" not in cell("(5)", 4):
        bad.append(F("G-SEC", "row (5) does not hook indicator.locked", "spec", sec))
    a, b = D04_KEY_ROWS
    d04: dict[str, str] = {}
    for n in range(a, b + 1):
        cells = split_row(base_line("D04", n))
        if len(cells) >= 3:
            q = QUOTED.findall(cells[2])
            d04[cells[0].strip("`")] = q[0] if q else ""
    reasons = {str(k): str(v) for e in entries.values() for k, v in (e.get("reasons") or {}).items()}  # type: ignore[union-attr]
    for key in INDICATOR_KEYS:
        r = reasons.get(key)
        if r is None:
            bad.append(F("G-SEC", f"{key} has no `reasons` sentence in the deck", "deck", "(deck)"))
        elif r != d04.get(key):
            bad.append(
                F(
                    "G-SEC",
                    f"{key}: the reason is not D04 §10.2's candidate sentence",
                    "deck",
                    "(deck)",
                )
            )
        elif (
            len(r) > REASON_MAX or not r.endswith(".") or set(re.findall(r"\d+", r)) - REASON_DIGITS
        ):
            bad.append(
                F("G-SEC", f"{key}: the reason is off E09-D09 §3.1's form", "deck", "(deck)")
            )
    for k, e in entries.items():
        for key in e.get("reasons") or {}:  # type: ignore[union-attr]
            if key not in e.get("indicator_keys", []):
                bad.append(
                    F(
                        "G-SEC",
                        f"{k}: a reason for a key the entry does not carry",
                        "deck",
                        "(deck)",
                    )
                )
    # L-1: row (1)'s hook pins text-only rendering of the server-supplied schema words
    for need in SEC_ROW1_WORDS:
        if need not in cell("(1)", 4):
            bad.append(F("G-SEC", f"row (1)'s hook does not carry {need}", "spec", sec))
    # L-3: CG-2's carried row names the env field
    cg2 = next((r for r in rows_of(t.spec, GROW_HEAD) if r[0].startswith("D02 CG-2")), None)
    if cg2 is None or len(cg2) < 3 or "`env`" not in cg2[2] or "frozen (7)" not in cg2[2]:
        bad.append(
            F(
                "G-SEC",
                "the CG-2 row does not carry the `env` field under frozen (7)",
                "spec",
                spec_sec(t, GROW_HEAD),
            )
        )
    # I-1: §3.1's x-rbac column equals `22`'s line per operation and `23` §6.3's row for the topic
    api = base_lines("22")
    osec = spec_sec(t, OPS_HEAD)
    for r in rows_of(t.spec, OPS_HEAD):
        op = r[0].strip("`")
        got = r[3] if len(r) > 3 else ""
        if op.startswith("WS "):
            if "`marketdata:read`" not in got or "`marketdata:read`" not in base_line("23", 901):
                bad.append(
                    F("G-SEC", "the topic's x-rbac cell is not `23` §6.3's row", "spec", osec)
                )
            continue
        m = re.search(r"`22`:(\d+)", r[2] if len(r) > 2 else "")
        want = x_rbac_of(api, int(m[1])) if m else None
        if want is None:
            bad.append(F("G-SEC", f"{op}: no x-rbac line in `22`'s operation block", "spec", osec))
        elif not got.startswith(want[0] + (" · CSRF" if want[1] else "") + " ("):
            bad.append(F("G-SEC", f"{op}: the x-rbac cell is not `22`'s {want[0]!r}", "spec", osec))
    return bad


# ---------------------------------------------------------------------------- (e) PNGs, (f) tokens


def g_png(t: Texts) -> list[Finding]:
    have = img_names()
    bad: list[Finding] = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for name in PNG_NAME.findall(ln):
            if name not in have:
                bad.append(
                    F("G-PNG", f"line {i}: {name} is not under {IMG_REL}", "spec", h2_at(t.spec, i))
                )
    for scr in ("E13-D02-", "E13-D03-", "E13-D04-", "E13-D05-"):
        if not any(n.startswith(scr) for n in have):
            bad.append(
                F("G-PNG", f"no {scr}*.png under {IMG_REL}", "spec", spec_sec(t, FRAME_HEAD))
            )
    return bad


@functools.cache
def token_names() -> frozenset[str]:
    names: set[str] = set()
    for theme_files in THEMES.values():
        for stem in theme_files:
            text = git_show(BASE, f"{TOKENS_REL}/{stem}.tokens.json") or "{}"
            try:
                names |= set(json.loads(text).keys())
            except json.JSONDecodeError:
                pass
    return frozenset(names)


def g_tokens(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    known = token_names()
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for name in TOKEN_NAME.findall(ln):
            base = name.rstrip("`")
            if "*" in base or base.endswith(".") or base in REGISTRY_IDS:
                continue
            if base in known or base in PUBLISHED_TOKENS:
                continue
            bad.append(
                F(
                    "G-TOKENS",
                    f"line {i}: `{base}` is in no token file and not a published D04 §2 name",
                    "spec",
                    h2_at(t.spec, i),
                )
            )
    return bad


# ---------------------------------------------------------------------------- (g) the data contract

DESCRIPTOR_FIELDS = (
    "id",
    "name",
    "category",
    "pane",
    "compute",
    "estimated",
    "params_schema",
    "defaults",
    "outputs",
    "warmup_bars",
    "unit",
    "nullable_when",
)


def g_fields(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, OPS_HEAD)
    api = base_lines("22")
    for r in rows_of(t.spec, OPS_HEAD):
        op = r[0].strip("`")
        m = re.search(r"`22`:(\d+)", r[2])
        if op.startswith("WS "):
            if "indicators.{symbol}" not in base_line("23", 748):
                bad.append(F("G-FIELDS", "`23`:748 is not the indicators topic row", "spec", sec))
            continue
        if not m or f"operationId: {op}" not in api[int(m[1]) - 1]:
            bad.append(F("G-FIELDS", f"{op} is not declared at the cited `22` line", "spec", sec))
    desc = "\n".join(api[23104:23155])
    for fld in DESCRIPTOR_FIELDS:
        if not re.search(rf"^\s+{fld}:", desc, MULTI):
            bad.append(
                F(
                    "G-FIELDS",
                    f"IndicatorDescriptor.{fld} is not in `22`'s schema block",
                    "spec",
                    spec_sec(t, FIELDS_HEAD),
                )
            )
    vsec = spec_sec(t, VOCAB_HEAD)
    pane_enum = (
        re.search(r"pane: \{ type: string, enum: \[([^\]]+)\]", api[23111])
        if len(api) > 23111
        else None
    )
    target_enum = (
        re.search(r"enum: \[([^\]]+)\]", "\n".join(api[21997:22001])) if len(api) > 22001 else None
    )
    panes = {x.strip() for x in (pane_enum[1].split(",") if pane_enum else [])}
    targets = {x.strip() for x in (target_enum[1].split(",") if target_enum else [])}
    rows = rows_of(t.spec, VOCAB_HEAD)
    mine_p = {r[0].strip("`") for r in rows if r[0].startswith("`")}
    mine_t = {r[1].strip("`") for r in rows if r[1].startswith("`")}
    if mine_p != panes:
        bad.append(
            F(
                "G-FIELDS",
                f"§3.3's `pane` values {sorted(mine_p)} != `22`'s {sorted(panes)}",
                "spec",
                vsec,
            )
        )
    if mine_t != targets:
        bad.append(
            F(
                "G-FIELDS",
                f"§3.3's `pane_target` values {sorted(mine_t)} != `22`'s {sorted(targets)}",
                "spec",
                vsec,
            )
        )
    style = "\n".join(api[22006:22016])
    if "The set is empty until E13-D04 publishes it" not in style:
        bad.append(
            F(
                "G-FIELDS",
                "`22` IndicatorPresetStyle no longer reads 'empty until E13-D04'",
                "spec",
                spec_sec(t, FIELDS_HEAD),
            )
        )
    return bad


# ---------------------------------------------------------------------------- (h) G-UNTOUCHED


def revert_ticks(line: str) -> str:
    return TICK.sub(lambda m: f"[ ] {m['item']}", line)


def pointer_problems(text: str, base: str) -> list[str]:
    lines = text.split("\n")
    out: list[str] = []
    reverted = [revert_ticks(ln) for ln in lines if ln != POINTER_14]
    if reverted != base.split("\n"):
        out.append(
            "`14` differs from the merge-base beyond the three pointer lines and the fifteen ticks"
        )
    heads = [(i, m[1]) for i, ln in enumerate(lines) if (m := re.match(r"^### (SCR-\d{3})\b", ln))]
    ticked_total = 0
    for k, (i, scr) in enumerate(heads):
        body = lines[i : heads[k + 1][0] if k + 1 < len(heads) else len(lines)]
        at = [j for j, ln in enumerate(body) if ln == POINTER_14]
        ticks = [m for ln in body for m in TICK.finditer(ln)]
        if scr not in POINTER_SCREENS:
            if at or ticks:
                out.append(f"`14` {scr} carries a pointer line or a tick")
            continue
        if len(at) != 1:
            out.append(f"`14` {scr} carries {len(at)} pointer lines, not one")
            continue
        nxt = body[at[0] + 1] if at[0] + 1 < len(body) else ""
        if not nxt.startswith(CHECKLIST_PREFIX):
            out.append(f"`14` {scr}'s pointer is not directly before its sign-off checklist line")
        if "[ ]" in nxt or len(ticks) != 5:
            out.append(f"`14` {scr}'s checklist carries {len(ticks)} evidence ticks, not five")
        ticked_total += len(ticks)
        if scr == "SCR-036" and not any(FIFTEENTH in ln for ln in body):
            out.append("`14` SCR-036's accessible-equivalent tick lacks the ruled parenthesis")
    if ticked_total != 15:
        out.append(f"`14` carries {ticked_total} ticks, not fifteen")
    return out


def stray_paths_at(ref: str) -> tuple[str, ...] | None:
    ok_diff, diff = git_ok("diff", "--name-only", ref)
    ok_new, new = git_ok("ls-files", "--others", "--exclude-standard")
    if not (ok_diff and ok_new):
        return None
    names = [*diff.split("\n"), *new.split("\n")]
    return tuple(sorted({n for n in names if n and n not in OWN_PATHS}))


def g_untouched(t: Texts) -> list[Finding]:
    ref = merge_base()
    if not ref:
        return [F("G-UNTOUCHED", f"no merge-base with {HEAD}: nothing compared", None, None)]
    bad: list[Finding] = []
    override = dict(PLAN_OVERRIDE)
    for cid, text in t.plans:
        text = override.get(cid, text)
        base = git_show(ref, CITE_FILES[cid])
        if base is None:
            bad.append(F("G-UNTOUCHED", f"{cid} is not readable at {ref[:10]}", None, None))
        elif cid == "14":
            bad += [F("G-UNTOUCHED", m, None, None) for m in pointer_problems(text, base)]
        elif text != base:
            bad.append(F("G-UNTOUCHED", f"{cid} differs from {ref[:10]}", None, None))
    strays = stray_paths_at(ref)
    if strays is None:
        return [*bad, F("G-UNTOUCHED", "a git call failed: no path compared", None, None)]
    bad += [
        F("G-UNTOUCHED", f"{p} is not this PR's path", None, None)
        for p in sorted({*strays, *EXTRA_PATHS})
    ]
    return bad


# ---------------------------------------------------------------------------- (i) design-ahead, (j) dry run, (k) icons


def g_ahead(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, AHEAD_HEAD)
    rows = rows_of(t.spec, AHEAD_HEAD)
    for r in rows:
        consumer, sprint, status = r[0], r[1], r[-1]
        if any(w in consumer for w in WAIVED):
            if sprint != "07" or not status.startswith("waived 2026-10-30"):
                bad.append(
                    F(
                        "G-AHEAD",
                        f"{consumer[:24]}: a Sprint 07 consumer without the ruled waiver line",
                        "spec",
                        sec,
                    )
                )
        elif sprint == "08" and "gate met" not in status:
            bad.append(
                F(
                    "G-AHEAD",
                    f"{consumer[:24]}: a Sprint 08 consumer without the gate condition",
                    "spec",
                    sec,
                )
            )
    if RULING_QUOTES[0] not in strip_comments(section(t.spec, AHEAD_HEAD)):
        bad.append(F("G-AHEAD", "the waiver line is not quoted verbatim", "spec", sec))
    body = norm_text(section(t.spec, AHEAD_HEAD))
    if sprint_of(datetime.date(2026, 10, 29)) != 5 or "one sprint plus one day" not in body:
        bad.append(
            F(
                "G-AHEAD",
                "D04's margin is not recorded as one sprint plus one day of Sprint 05",
                "spec",
                sec,
            )
        )
    if len(rows) < 6:
        bad.append(F("G-AHEAD", f"§13 carries {len(rows)} rows", "spec", sec))
    return bad


def g_walk(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, WALK_HEAD)
    rows = rows_of(t.spec, WALK_HEAD)
    if len(rows) < 12:
        bad.append(
            F("G-WALK", f"§16.2 carries {len(rows)} rows, fewer than the twelve roles", "spec", sec)
        )
    roles = " ".join(r[1] for r in rows)
    for need in ("FE-lead read", "chart-engine-lead read"):
        if need not in roles:
            bad.append(F("G-WALK", f"§16.2 has no row for the {need}", "spec", sec))
    for r in rows:
        if len(r) < 6:
            bad.append(F("G-WALK", f"row {r[0]!r} is short", "spec", sec))
            continue
        date, role, needs, found, nf, disp = r[:6]
        if date == "pending":
            if STRICT_WALK and STRICT_WALK[-1]:
                bad.append(
                    F("G-WALK", f"{role[:30]}: still pending at the ready line", "spec", sec)
                )
            elif not (needs == found == nf == "pending" and disp.startswith("pending")):
                bad.append(
                    F(
                        "G-WALK",
                        f"{role[:30]}: a pending row must be pending in every cell",
                        "spec",
                        sec,
                    )
                )
            continue
        try:
            datetime.date.fromisoformat(date)
            n, f_, x = int(needs), int(found), int(nf)
        except ValueError:
            bad.append(
                F("G-WALK", f"{role[:30]}: the date or the counts are not well-formed", "spec", sec)
            )
            continue
        if f_ + x != n or not disp.strip() or (x > 0 and not re.search(r"\b[GQ]-\d|CG-\d", disp)):
            bad.append(
                F(
                    "G-WALK",
                    f"{role[:30]}: found + not found != needs, or a not-found without a row",
                    "spec",
                    sec,
                )
            )
    return bad


@functools.cache
def registry_keys() -> frozenset[str]:
    text = source_text("ICONS")
    return frozenset(
        a or b
        for a, b in re.findall(r'^  (?:"([a-z0-9.-]+)"|([a-z][a-zA-Z0-9]*)): \{', text, MULTI)
    )


def g_icons(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, ICON_HEAD)
    keys = registry_keys()
    if len(keys) < 40:
        bad.append(F("G-ICONS", f"the registry parsed {len(keys)} keys", "spec", sec))
    for r in rows_of(t.spec, ICON_HEAD):
        names = re.findall(r"`icon/([a-z0-9-]+)`", r[0])
        regs = re.findall(r"`([a-z0-9-]+)`", r[1])
        status = r[2]
        if status.startswith("present"):
            missing = [k for k in regs if k not in keys]
            if not regs or missing:
                bad.append(
                    F(
                        "G-ICONS",
                        f"{r[0][:30]}: registry key {missing or '(none)'} not in ICONS",
                        "spec",
                        sec,
                    )
                )
            if any(n not in keys for n in names) and "name-mapped" not in status:
                bad.append(
                    F(
                        "G-ICONS",
                        f"{r[0][:30]}: a spec name absent from the registry without 'name-mapped'",
                        "spec",
                        sec,
                    )
                )
            if "name-mapped" in status and "C-5" not in status:
                bad.append(
                    F("G-ICONS", f"{r[0][:30]}: a name-mapped row without its C-row", "spec", sec)
                )
        elif status.startswith("absent"):
            if r[1] != "—" or any(n in keys for n in names):
                bad.append(
                    F("G-ICONS", f"{r[0][:30]}: marked absent but a key exists", "spec", sec)
                )
            if "E05-T06" not in status and "badge" not in status:
                bad.append(
                    F("G-ICONS", f"{r[0][:30]}: an absent icon without its route", "spec", sec)
                )
        else:
            bad.append(
                F("G-ICONS", f"{r[0][:30]}: status is neither present nor absent", "spec", sec)
            )
    thumb = norm_text(section(t.spec, THUMB_HEAD))
    if "rendered, not exported" not in thumb or ".svg" in thumb.lower():
        bad.append(
            F(
                "G-ICONS",
                "§11.2 does not route the thumbnail as rendered, not exported",
                "spec",
                spec_sec(t, THUMB_HEAD),
            )
        )
    return bad


# ---------------------------------------------------------------------------- the rows


def seq_rows(
    t: Texts, head: str, prefix: str, tag: str, n_min: int
) -> tuple[list[list[str]], list[Finding]]:
    rows = rows_of(t.spec, head)
    sec = spec_sec(t, head)
    bad: list[Finding] = []
    ids = [r[0] for r in rows]
    want = [f"{prefix}{i}" for i in range(1, len(rows) + 1)]
    if ids != want or len(rows) < n_min:
        bad.append(
            F(
                tag,
                f"{head[:20]}: ids {ids[:3]}… are not {prefix}1..{prefix}{max(len(rows), n_min)} in order",
                "spec",
                sec,
            )
        )
    return rows, bad


def g_crows(t: Texts) -> list[Finding]:
    rows, bad = seq_rows(t, CROW_HEAD, "C-", "G-CROWS", 20)
    sec = spec_sec(t, CROW_HEAD)
    for r in rows:
        if len(r) < 3 or not r[1].strip() or not r[2].strip():
            bad.append(F("G-CROWS", f"{r[0]} has no contradiction or no reading", "spec", sec))
    body = section(t.spec, CROW_HEAD)
    for letter in ("C-a", "C-b", "C-c", "C-d"):
        if letter not in body:
            bad.append(F("G-CROWS", f"{letter} is not mapped to a C-row", "spec", sec))
    return bad


DATE_OR_ANCHOR = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|at once)")


def g_grows(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, GROW_HEAD)
    rows = rows_of(t.spec, GROW_HEAD)
    if len(rows) < 42:
        bad.append(
            F("G-GROWS", f"§15.2 carries {len(rows)} rows, fewer than the carried set", "spec", sec)
        )
    for r in rows:
        if len(r) < 5 or not r[3].strip() or not DATE_OR_ANCHOR.match(r[4].strip()):
            bad.append(F("G-GROWS", f"{r[0][:16]}: no owner lane or no due date", "spec", sec))
        if re.search(r"\bhpe-|\bhcl-|\bagent\b", r[3], re.IGNORECASE):
            bad.append(F("G-GROWS", f"{r[0][:16]}: the owner is an agent, not a lane", "spec", sec))
    return bad


def g_qrows(t: Texts) -> list[Finding]:
    rows, bad = seq_rows(t, QROW_HEAD, "Q-", "G-QROWS", 10)
    sec = spec_sec(t, QROW_HEAD)
    for r in rows:
        if (
            len(r) < 5
            or any(not c.strip() for c in r[1:4])
            or not DATE_OR_ANCHOR.match(r[4].strip())
        ):
            bad.append(F("G-QROWS", f"{r[0]}: no default, no owner lane or no due", "spec", sec))
    return bad


def g_arows(t: Texts) -> list[Finding]:
    rows, bad = seq_rows(t, AROW_HEAD, "A-", "G-AROWS", 3)
    sec = spec_sec(t, AROW_HEAD)
    for r in rows:
        if len(r) < 4 or any(not c.strip() for c in r[1:4]):
            bad.append(F("G-AROWS", f"{r[0]}: a target, text or owner cell is empty", "spec", sec))
    if "13" not in (rows[0][1] if rows else ""):
        bad.append(F("G-AROWS", "A-1 is not the `13` Indicators flow", "spec", sec))
    return bad


def g_ruled(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    body = section(t.spec, RULED_HEAD)
    sec = spec_sec(t, RULED_HEAD)
    if RULING_ID not in t.spec or BQ_LIST_ID not in t.spec:
        bad.append(F("G-RULED", "the ruling or the BQ list id is missing", "spec", sec))
    for n in range(1, 15):
        if f"BQ-{n:02d}" not in body:
            bad.append(F("G-RULED", f"BQ-{n:02d} is not carried in the ruled section", "spec", sec))
    if "RULED as proposed" not in body:
        bad.append(
            F(
                "G-RULED",
                "the ruled section does not state that every default is RULED as proposed",
                "spec",
                sec,
            )
        )
    if RULING_QUOTES[5] not in t.spec:
        bad.append(F("G-RULED", "no reading carries the ruled-of-record cite form", "spec", sec))
    for m in COMMENT_ID.finditer(CODE.sub("", strip_comments(t.spec))):
        if m[1] not in RULED_IDS:
            bad.append(
                F(
                    "G-RULED",
                    f"comment id {m[1]} is not a ruling of record",
                    "spec",
                    h2_at(t.spec, t.spec[: m.start()].count("\n") + 1),
                )
            )
    return bad


def g_storybook(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, COMP_HEAD)
    for r in rows_of(t.spec, COMP_HEAD):
        if len(r) >= 4 and re.search(
            r"\b(?:built|shipped|implemented|done)\b", r[3], re.IGNORECASE
        ):
            bad.append(
                F(
                    "G-STORYBOOK",
                    f"{r[0][:24]}: the Storybook column claims a built story",
                    "spec",
                    sec,
                )
            )
    return bad


# ---------------------------------------------------------------------------- hygiene


def g_penpot(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            if URL.search(ln) or UUID.search(ln) or PENPOT_WORDS.search(ln):
                bad.append(
                    F(
                        "G-PENPOT",
                        f"{doc} line {i}: a URL, hostname, UUID or workspace word",
                        doc,
                        h2_at(text, i) if doc == "spec" else "(deck)",
                    )
                )
    return bad


def g_names(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            if NAMES.search(ln):
                bad.append(
                    F(
                        "G-NAMES",
                        f"{doc} line {i}: a worker, session, user or host name",
                        doc,
                        h2_at(text, i) if doc == "spec" else "(deck)",
                    )
                )
    return bad


def g_close(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    hits = [(i, m[0]) for i, ln in enumerate(t.spec.split("\n"), 1) for m in CLOSING.finditer(ln)]
    allowed = [
        h
        for h in hits
        if h[1] == "Closes #347"
        and (
            h2_at(t.spec, h[0]) in ("(top)", h2_of(t.spec, VERSION_HEAD))
            or h2_at(t.spec, h[0]).startswith("The questions")
        )
    ]
    for i, word in hits:
        if (i, word) not in allowed:
            bad.append(
                F(
                    "G-CLOSE",
                    f"line {i}: {word!r} outside the header, the ruled section and §17",
                    "spec",
                    h2_at(t.spec, i),
                )
            )
    if len(allowed) > 3:
        bad.append(F("G-CLOSE", "`Closes #347` is stated more than three times", "spec", "(top)"))
    return bad


def g_session(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if SESSION_WORDS.search(ln):
            bad.append(
                F(
                    "G-SESSION",
                    f"line {i}: a session or meeting is claimed",
                    "spec",
                    h2_at(t.spec, i),
                )
            )
    body = norm_text(section(t.spec, WALK_HEAD))
    if "No session took place and none is claimed" not in body:
        bad.append(
            F(
                "G-SESSION",
                "§16.2 does not say that no session took place",
                "spec",
                spec_sec(t, WALK_HEAD),
            )
        )
    return bad


def g_storyids(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    known = set(STORY_ID.findall(source_text("11")))
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for sid in STORY_ID.findall(ln):
            if sid not in known:
                bad.append(
                    F("G-STORYIDS", f"line {i}: {sid} is not in `11`", "spec", h2_at(t.spec, i))
                )
    return bad


# ---------------------------------------------------------------------------- pins (G-RULED-PIN)


def unvalued(line: str, values: Values) -> str:
    out = line
    for key, val, _pos in anchored(line):
        if val and val == values.get(key, val):
            out = out.replace(f"{val}<!--={key}-->", f"<!--={key}-->", 1)
    return out


def indent_tag(raw: str) -> str:
    return "i" if raw.startswith((" ", "\t")) else ""


def line_form(line: str) -> str:
    s = line.lstrip()
    if s.startswith(("- ", "* ")):
        return "b"
    if re.match(r"^\d{1,2}\. ", s):
        return "n"
    return "p"


def spec_units(text: str, values: Values) -> list[Unit]:
    lines = text.split("\n")
    fence = fenced(lines)
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    count: dict[str, int] = {}
    region, k, shape, nf = "(top)#1", 0, "", 0
    seen: dict[str, int] = {}
    block: list[str] = []
    for i, raw in enumerate(lines):
        if fence[i]:
            shape += "f"
            block.append(raw)
            if (
                i + 1 == len(lines)
                or not fence[i + 1]
                or (len(block) > 1 and FENCE_OPEN.match(raw))
            ):
                nf += 1
                out.append(("spec", region, f"fence {nf}", json.dumps("\n".join(block))))
                block = []
            continue
        ln = unvalued(raw, values)
        m = HEADING.match(ln)
        if m:
            out.append(("spec", region, "shape", shape))
            level = len(m[1])
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m[2]))]
            key = " > ".join(p[1] for p in path)
            count[key] = count.get(key, 0) + 1
            region, k, seen, shape, nf = f"{key}#{count[key]}", 0, {}, "h", 0
            out.append(("spec", region, "heading", pin_norm(ln)))
            continue
        if not ln.strip():
            shape += "."
        elif is_rule(ln):
            shape += "r"
            out.append(
                ("spec", region, f"rule {shape.count('r')}", pin_norm(re.sub(r"-+", "-", ln)))
            )
        elif re.match(r"^ {0,3}\|", ln):
            shape += indent_tag(raw) + "t"
            rid = pin_norm(split_row(ln)[0])[:60] or "(blank)"
            seen[rid] = seen.get(rid, 0) + 1
            loc = f"row {rid}" + (f"#{seen[rid]}" if seen[rid] > 1 else "")
            out.append(("spec", region, loc, " | ".join(pin_norm(c) for c in split_row(ln))))
        else:
            sents = [x for x in FULL_STOP.split(ln.strip()) if x.strip()]
            shape += f"{indent_tag(raw)}{line_form(ln)}{len(sents)}"
            for s in sents:
                k += 1
                out.append(("spec", region, f"s{k}", pin_norm(s)))
    out.append(("spec", region, "shape", shape))
    return out


def deck_units(deck: str) -> list[Unit]:
    data = deck_data(deck)
    out: list[Unit] = []
    meta = {k: v for k, v in data.items() if k != "strings"}
    out.append(("deck", "(meta)#1", "meta", json.dumps(meta, ensure_ascii=False, sort_keys=True)))
    for key, e in deck_entries(deck).items():
        out.append(("deck", f"{key}#1", "entry", json.dumps(e, ensure_ascii=False, sort_keys=True)))
    return out


def ruled_units(spec: str, deck: str, values: Values) -> list[Unit]:
    return [*spec_units(spec, values), *deck_units(deck)]


def parse_pins(text: str) -> tuple[Unit, ...]:
    out: list[Unit] = []
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 4:
            out.append((parts[0], parts[1], parts[2], parts[3]))
    return tuple(out)


def write_pins(units: list[Unit]) -> str:
    head = (
        "# E13-D06 pins (every unit of the pack and every deck entry): doc, region (heading path"
        f" #occurrence), location, the exact normalised text; {len(units)} units.\n# Written by "
        "`--repin-ruled` only; `--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in units)


def pin_file_text() -> str | None:
    path = ROOT / PIN_REL
    return path.read_text(encoding="utf-8") if path.exists() else None


def pin_findings(t: Texts) -> list[Finding]:
    text = pin_file_text()
    if text is None:
        return [F("G-RULED-PIN", f"{PIN_REL} is missing: run --repin-ruled", None, None)]
    m = re.search(r"; (\d+) units\.", text.split("\n", 1)[0])
    pinned = parse_pins(text)
    bad: list[Finding] = []
    if not m or int(m[1]) != len(pinned):
        bad.append(
            F("G-RULED-PIN", "the pins header count does not match the parsed units", None, None)
        )
    if PIN_UNITS_OVERRIDE:
        pinned = PIN_UNITS_OVERRIDE[-1]
    current = tuple(ruled_units(t.spec, t.deck, t.values))
    pinned_set, current_set = set(pinned), set(current)
    for doc, region, loc, _text in sorted(current_set - pinned_set):
        sec = region.split(" > ")[0].split("#")[0] if doc == "spec" else "(deck)"
        if doc == "spec" and " > " in region:
            sec = next((p for p in region.split(" > ") if p and not p.startswith("E13-D06")), sec)
        bad.append(
            F(
                "G-RULED-PIN",
                f"{doc} {region[:40]} {loc[:30]}: not pinned (changed or new)",
                doc,
                sec_of_region(t.spec, region) if doc == "spec" else "(deck)",
            )
        )
    for doc, region, loc, _text in sorted(pinned_set - current_set):
        bad.append(
            F(
                "G-RULED-PIN",
                f"{doc} {region[:40]} {loc[:30]}: pinned unit gone",
                doc,
                sec_of_region(t.spec, region) if doc == "spec" else "(deck)",
            )
        )
    return bad


def sec_of_region(spec: str, region: str) -> str:
    """The h2 heading text a pin region sits under."""
    parts = region.rsplit("#", 1)[0].split(" > ")
    heads = [
        pin_norm(m[2]) for ln in spec.split("\n") if (m := HEADING.match(ln)) and len(m[1]) == 2
    ]
    for p in parts:
        if p in heads:
            return p
    return "(top)"


# ---------------------------------------------------------------------------- audit

MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_hex,
    g_version,
    g_quote,
    g_redline,
    g_deck,
    g_deckkey,
    g_sec,
    g_frozen,
    g_png,
    g_tokens,
    g_fields,
    g_untouched,
    g_ahead,
    g_walk,
    g_icons,
    g_crows,
    g_grows,
    g_qrows,
    g_arows,
    g_ruled,
    g_storybook,
    g_penpot,
    g_names,
    g_close,
    g_session,
    g_storyids,
)
GATE_NAMES = (
    "G-ANCHOR",
    "G-HASH",
    "G-MARKER",
    "G-CITE",
    "G-VERSION",
    "G-QUOTE",
    "G-REDLINE",
    "G-DECK",
    "G-DECKKEY",
    "G-FROZEN",
    "G-PNG",
    "G-TOKENS",
    "G-FIELDS",
    "G-UNTOUCHED",
    "G-AHEAD",
    "G-WALK",
    "G-ICONS",
    "G-CROWS",
    "G-GROWS",
    "G-QROWS",
    "G-AROWS",
    "G-RULED",
    "G-STORYBOOK",
    "G-HEX",
    "G-PENPOT",
    "G-NAMES",
    "G-CLOSE",
    "G-SESSION",
    "G-STORYIDS",
    "G-SEC",
    "G-RULED-PIN",
)


def audit(t: Texts) -> tuple[list[str], list[str], int]:
    """(FAIL lines, NOTE lines, cites checked). One FAIL line per gate; a pin finding in a
    section another gate already FAILs is demoted to a NOTE line."""
    found: list[Finding] = []
    v = t.values
    found += g_anchor_doc(t.spec, v)
    found += g_marker_doc(t.spec)
    cf, n = cite_findings(t)
    found += cf
    for gate in MEASURED_GATES:
        found += gate(t)
    flagged = {(f[2], f[3]) for f in found if f[2] is not None}
    pins = pin_findings(t)
    notes = [f"NOTE [G-RULED-PIN] {p[1][:150]}" for p in pins if (p[2], p[3]) in flagged]
    found += [p for p in pins if (p[2], p[3]) not in flagged]
    merged: dict[str, list[str]] = {}
    for tag, msg, _d, _s in found:
        merged.setdefault(tag, []).append(msg)
    fails = []
    for tag, msgs in merged.items():
        msgs = list(dict.fromkeys(msgs))
        more = f" (+{len(msgs) - 4} more)" if len(msgs) > 4 else ""
        fails.append(f"[{tag}] " + "; ".join(m[:150] for m in msgs[:4]) + more)
    return fails, notes, n


# ---------------------------------------------------------------------------- self-test

Edit = Callable[[str], str]


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str
    what: str
    spec: Edit | None = None
    deck: Edit | None = None
    lever: Callable[[], Callable[[], None]] | None = None


def sub(old: str, new: str, count: int = 1) -> Edit:
    def edit(text: str) -> str:
        if old not in text:
            return text
        return text.replace(old, new, count)

    return edit


def line_sub(prefix: str, old: str, new: str) -> Edit:
    """Replace `old` with `new` on the first line starting with `prefix`."""

    def edit(text: str) -> str:
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith(prefix) and old in ln:
                lines[i] = ln.replace(old, new, 1)
                return "\n".join(lines)
        return text

    return edit


def cell_set(prefix: str, col: int, new: str) -> Edit:
    """Rewrite cell `col` (0-based) of the first table row whose lead cell starts with `prefix`."""

    def edit(text: str) -> str:
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("|") and split_row(ln) and split_row(ln)[0].startswith(prefix):
                cells = split_row(ln)
                if col < len(cells):
                    cells[col] = new
                    lines[i] = "| " + " | ".join(cells) + " |"
                    return "\n".join(lines)
        return text

    return edit


def deck_edit(fn: Callable[[dict[str, object]], None]) -> Edit:
    def edit(deck: str) -> str:
        data = json.loads(deck)
        fn(data)
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    return edit


def deck_set(key: str, fld: str, value: object) -> Edit:
    def fn(d: dict[str, object]) -> None:
        d["strings"][key][fld] = value  # type: ignore[index]

    return deck_edit(fn)


def deck_drop(key: str) -> Edit:
    def fn(d: dict[str, object]) -> None:
        d["strings"].pop(key)  # type: ignore[union-attr]

    return deck_edit(fn)


def popper(lst: list) -> Callable[[], None]:  # type: ignore[type-arg]
    return lambda: lst.pop()


def lever_extra_path() -> Callable[[], None]:
    EXTRA_PATHS.append("docs/plan/22-api-openapi.yaml")
    return popper(EXTRA_PATHS)


def lever_plan14() -> Callable[[], None]:
    text = (ROOT / PLAN14_REL).read_text(encoding="utf-8")
    PLAN_OVERRIDE.append(("14", text.replace(POINTER_14, POINTER_14 + "\n" + POINTER_14, 1)))
    return popper(PLAN_OVERRIDE)


def lever_head_edit() -> Callable[[], None]:
    rel = CITE_FILES["D02"]
    text = (git_show(BASE, rel) or "").split("\n")
    text[184] = text[184] + " (edited)"
    HEAD_OVERRIDE.append((rel, "\n".join(text)))
    return popper(HEAD_OVERRIDE)


def lever_png_missing() -> Callable[[], None]:
    IMG_OVERRIDE.append(
        frozenset(n for n in img_names() if n != "E13-D02-01-library-landing-1280.png")
    )
    return popper(IMG_OVERRIDE)


def lever_strict_walk() -> Callable[[], None]:
    STRICT_WALK.append(True)
    return popper(STRICT_WALK)


def hash_mutation() -> Edit:
    def edit(text: str) -> str:
        return re.sub(r"[0-9a-f]{12}(<!--=HASH:d12-->)", r"0a0b0c0d0e0f\1", text, count=1)

    return edit


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1",
        "G-ANCHOR",
        "a count anchor drifts",
        spec=sub("57<!--=COUNT:deck-->", "58<!--=COUNT:deck-->"),
    ),
    Mutation("M-2", "G-HASH", "a lifted block's hash drifts", spec=hash_mutation()),
    Mutation(
        "M-3",
        "G-MARKER",
        "a stray HTML comment",
        spec=sub("## 7. Reorder", "## 7. Reorder <!-- note -->"),
    ),
    Mutation("M-4", "G-CITE", "a cite outside the file", spec=sub("(`14`:874)", "(`14`:98741)")),
    Mutation("M-5", "G-VERSION", "a cited range edited at origin/main", lever=lever_head_edit),
    Mutation(
        "M-6",
        "G-QUOTE",
        "a quote no source holds",
        spec=sub(
            '"Preview on Apply — this indicator is computed on the server."',
            '"Preview on Apply — this indicator is computed remotely."',
        ),
    ),
    Mutation(
        "M-7",
        "G-REDLINE",
        "a redline figure not equal to its source cell",
        spec=cell_set("SCR-034 footer action bar", 1, "44"),
    ),
    Mutation(
        "M-8",
        "G-DECK",
        "a deck string not verbatim",
        deck=deck_set("d02.12.r22", "strings", ["This indicator has no parameter."]),
    ),
    Mutation(
        "M-9",
        "G-DECKKEY",
        "a key outside the six and the row ids",
        deck=deck_edit(
            lambda d: d["strings"].update({"indicator.unknown": d["strings"].pop("d02.12.r18")})
        ),
    ),
    Mutation(
        "M-10",
        "G-FROZEN",
        "a frozen row's hook re-aimed",
        spec=cell_set(
            "(4)",
            4,
            "`d02.12.r22`; a test that a `compute: server` field edit sends no `ctl` before Apply",
        ),
    ),
    Mutation("M-11", "G-PNG", "a named PNG missing", lever=lever_png_missing),
    Mutation(
        "M-12",
        "G-TOKENS",
        "a token name in no file and not published",
        spec=sub("`color.text.tertiary` on T2", "`color.text.quaternary` on T2"),
    ),
    Mutation(
        "M-13",
        "G-FIELDS",
        "a vocabulary value not in the enum",
        spec=cell_set("`sub`", 1, "`sub-pane`"),
    ),
    Mutation("M-14", "G-UNTOUCHED", "a `14` edit outside the allowed lines", lever=lever_plan14),
    Mutation(
        "M-15",
        "G-AHEAD",
        "a waived row without the waiver",
        spec=cell_set("E13-Q01 (#422)", 5, "gate met"),
    ),
    Mutation(
        "M-16",
        "G-WALK",
        "a dry-run row whose counts do not add up",
        spec=cell_set("2026-10-30", 2, "99"),
    ),
    Mutation(
        "M-17",
        "G-ICONS",
        "an absent icon claimed present",
        spec=cell_set("`icon/star`", 2, "present"),
    ),
    Mutation("M-18", "G-CROWS", "a C-row without a reading", spec=cell_set("C-18", 2, "")),
    Mutation("M-19", "G-GROWS", "a G-row without a due date", spec=cell_set("D12-G-7", 4, "soon")),
    Mutation("M-20", "G-QROWS", "a Q-row without an owner", spec=cell_set("Q-4", 3, "")),
    Mutation("M-21", "G-AROWS", "an A-row without an owner", spec=cell_set("A-2", 3, "")),
    Mutation(
        "M-22",
        "G-RULED",
        "a BQ dropped from the ruled section",
        spec=sub("- **BQ-03:** redlines consolidated", "- **BQ-3:** redlines consolidated"),
    ),
    Mutation(
        "M-23",
        "G-STORYBOOK",
        "a Storybook cell claims built",
        spec=cell_set("CMP-240 TreeView", 3, "Default, MultiSelect (built)"),
    ),
    Mutation(
        "M-24",
        "G-HEX",
        "a hex literal",
        spec=sub("## 11.2 Thumbnails", "## 11.2 Thumbnails (#0b0e11)"),
    ),
    Mutation(
        "M-25",
        "G-PENPOT",
        "a Penpot host",
        spec=sub("## 11.2 Thumbnails", "## 11.2 Thumbnails (see https://penpot.example.com)"),
    ),
    Mutation(
        "M-26",
        "G-NAMES",
        "a local path or worker name",
        spec=sub("## 11.2 Thumbnails", "## 11.2 Thumbnails (/home/someone)"),
    ),
    Mutation(
        "M-27",
        "G-CLOSE",
        "a closing keyword outside the sanctioned lines",
        spec=sub("## 11.2 Thumbnails", "## 11.2 Thumbnails (Closes #347)"),
    ),
    Mutation(
        "M-28",
        "G-SESSION",
        "a session claimed",
        spec=sub(
            "**No session took place and none is claimed.**",
            "**A session was held with the leads.**",
        ),
    ),
    Mutation(
        "M-29",
        "G-STORYIDS",
        "a story id not in `11`",
        spec=sub("## 11.2 Thumbnails", "## 11.2 Thumbnails (US-IND-099)"),
    ),
    Mutation(
        "M-30",
        "G-RULED-PIN",
        "a sentence reworded with no gate behind it",
        spec=sub(
            "No new page and no boards (S-1; RULED BQ-01)",
            "No new page and no boards (S-1; RULED BQ-01) today",
        ),
    ),
    Mutation(
        "M-31",
        "G-WALK",
        "a pending row under --strict-walk",
        spec=cell_set("2026-10-30", 0, "pending"),
        lever=lever_strict_walk,
    ),
    Mutation("M-32", "G-UNTOUCHED", "a stray path", lever=lever_extra_path),
    # the security lens's folded sentences (I-2): one mutation per sentence, all under G-SEC
    Mutation(
        "M-33",
        "G-SEC",
        "the 20 / 6 client state gate attributed to the server (H-1)",
        spec=sub(
            "20 instances / 6 sub-panes — a client state gate",
            "20 instances / 6 sub-panes — the server's gate",
        ),
    ),
    Mutation(
        "M-34",
        "G-SEC",
        "a problem code dropped from row (6) (M-1)",
        spec=sub("(`422`, `409`, `403`, `413`, `503` — ", "(`422`, `409`, `403`, `503` — "),
    ),
    Mutation(
        "M-35",
        "G-SEC",
        "the compute-failed map opened (M-2)",
        deck=deck_set("d02.07.errored", "map", {}),
    ),
    Mutation(
        "M-36",
        "G-SEC",
        "a reason sentence off D04 §10.2's form (M-3)",
        deck=deck_set(
            "indicator.locked", "reasons", {"indicator.locked": "Unlock to move or remove"}
        ),
    ),
    Mutation(
        "M-37",
        "G-SEC",
        "row (1)'s text-node test dropped (L-1)",
        spec=sub(
            "render as text nodes (no `dangerouslySetInnerHTML`, no markdown)",
            "render (no markdown)",
        ),
    ),
    Mutation(
        "M-38",
        "G-SEC",
        "CG-2's env field dropped (L-3)",
        spec=cell_set("D02 CG-2", 2, "D24's dialog renders the server's answer once it exists"),
    ),
    Mutation(
        "M-39",
        "G-SEC",
        "an x-rbac cell off `22`'s line (I-1)",
        spec=cell_set("`listIndicatorPresets`", 3, "`workspaces:read` · `none` (`22`:10064)"),
    ),
    Mutation(
        "M-40",
        "G-SEC",
        "the TM cap cites moved off their rows (L-2)",
        spec=sub(
            ":115 (500): 8 / 500 are the contract's", ":112 (500): 8 / 500 are the contract's"
        ),
    ),
)


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(x.encode("utf-8")).hexdigest() for x in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def plan_paths() -> tuple[tuple[str, Path], ...]:
    return tuple((cid, ROOT / CITE_FILES[cid]) for cid in (*UNTOUCHED, "14", *UNTOUCHED_DOCS))


def read_plans() -> tuple[tuple[str, str], ...]:
    out = []
    for cid, p in plan_paths():
        out.append((cid, p.read_text(encoding="utf-8") if p.exists() else ""))
    return tuple(out)


def selftest(spec: str, deck: str, paths: tuple[Path, ...]) -> tuple[bool, list[str]]:
    on_disk = digest(paths)
    plans = read_plans()
    values = compute(spec, deck)
    spec_f, _ = fill(spec, values)
    values = compute(spec_f, deck)
    vt = tuple(sorted(values.items()))
    base_fails, _n, _c = audit(Texts(spec_f, deck, plans, vt))
    lines = [f"baseline (filled in memory): {len(base_fails)} FAIL"]
    lines += [f"  baseline FAIL {x}" for x in base_fails]
    ok = not base_fails
    pristine = digest_texts(spec_f, deck)
    for mu in MUTATIONS:
        s = mu.spec(spec_f) if mu.spec else spec_f
        d = mu.deck(deck) if mu.deck else deck
        if (s, d) == (spec_f, deck) and mu.lever is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        undo = mu.lever() if mu.lever else None
        repin = mu.gate != "G-RULED-PIN"
        if repin:
            PIN_UNITS_OVERRIDE.append(tuple(ruled_units(s, d, values)))
        try:
            fails, _n2, _c2 = audit(Texts(s, d, plans, vt))
        finally:
            if undo:
                undo()
            if repin:
                PIN_UNITS_OVERRIDE.pop()
        new = [x for x in fails if x not in base_fails]
        named = [x for x in new if x.startswith(f"[{mu.gate}]")]
        hit = bool(named) and len(new) == 1
        levers = (
            EXTRA_PATHS
            or PLAN_OVERRIDE
            or PIN_UNITS_OVERRIDE
            or HEAD_OVERRIDE
            or IMG_OVERRIDE
            or STRICT_WALK
        )
        restored = (
            digest_texts(spec_f, deck) == pristine and digest(paths) == on_disk and not levers
        )
        ok = ok and hit and restored
        first = (named or new or ["nothing new"])[0]
        lines.append(
            f"  {mu.mid} [{mu.gate}] {'ok' if hit else 'MISSED'} ({len(new)} new{'' if restored else ', NOT RESTORED'}) - {first}"
        )
        if not hit:
            lines += [f"      new: {x}" for x in new]
    return ok, [report(x) for x in lines]


# ---------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="E13-D06 hand-off pack audit (module docstring)")
    ap.add_argument("--check", nargs="?", const=SPEC_REL, default=None, metavar="SPEC")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="replace placeholders, then check")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="apply every mutation")
    ap.add_argument("--repin-ruled", action="store_true", help=f"rewrite {PIN_REL}")
    ap.add_argument(
        "--strict-walk", action="store_true", help="a pending dry-run row FAILs (the ready line)"
    )
    args = ap.parse_args(argv)
    if args.strict_walk:
        STRICT_WALK.append(True)
    spec_path = ROOT / (args.check or SPEC_REL)
    deck_path = ROOT / DECK_REL
    spec = spec_path.read_bytes().decode("utf-8")
    deck = deck_path.read_bytes().decode("utf-8")
    if args.repin_ruled:
        left = [
            m
            for ln in spec.split("\n")
            for m in PLACEHOLDER.finditer(ln)
            if not in_code(ln, m.start())
        ]
        if left:
            print(f"FAIL --repin-ruled: {len(left)} unfilled placeholders; run --fill first")
            return 1
        units = ruled_units(spec, deck, compute(spec, deck))
        (ROOT / PIN_REL).write_text(write_pins(units), encoding="utf-8", newline="\n")
        print(f"--repin-ruled: {len(units)} units pinned in {PIN_REL}")
        return 0
    if args.self_test:
        paths = (spec_path, deck_path, ROOT / PIN_REL, *(p for _n, p in plan_paths()))
        ok, lines = selftest(spec, deck, paths)
        print("\n".join(lines))
        print(report(f"--self-test: {'ok' if ok else 'FAIL'} - {len(MUTATIONS)} mutations"))
        return 0 if ok else 1
    values = compute(spec, deck)
    if args.fill:
        spec, unknown = fill(spec, values)
        spec_path.write_text(spec, encoding="utf-8", newline="\n")
        for u in unknown:
            print(f"FAIL --fill: no value for {{{{{u}}}}}")
        values = compute(spec, deck)
    if args.json and not (args.check or args.fill):
        print(json.dumps({"values": values}, ensure_ascii=False, indent=1))
        return 0
    t = Texts(spec, deck, read_plans(), tuple(sorted(values.items())))
    fails, notes, n = audit(t)
    if args.json:
        print(
            json.dumps(
                {"values": values, "fails": fails, "notes": notes, "cites": n},
                ensure_ascii=False,
                indent=1,
            )
        )
    else:
        shown = spec_path.relative_to(ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        print(f"## E13-D06 audit of {shown} (+ the deck) at base {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {len(GATE_NAMES)}")
        print("\n".join(notes))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK - every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(notes)} NOTE")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
