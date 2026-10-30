#!/usr/bin/env python3
"""E22-D05 (#578) audit: the design hand-off pack for the tape and the big-trade bubbles.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the plan texts and the merged E22 design docs the pack
cites (D02, D03, D03H, D04), `21`'s `st_key_fmt`, `22` / `23` lines, the E22 bounds module, the
ticket JSON, the calendar and the committed PNGs; then the pack and its copy deck from the
working tree.

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: CITE (a figure parsed from
   its cited line at the base, found by content), COUNT (the pack's tables, the deck, the PNG
   folder, a line shift), HASH (sha256 of a lifted block at the base, 12 hex), SPRINT (the
   calendar), REGEX (`21`'s `st_key_fmt` applied to a key), STATUS (a contract or tree probe at
   the base), RULED (R578's own figure). `--fill` writes `VALUE<!--=KIND:key-->`; `--check`
   re-derives every anchored value (G-ANCHOR; the HASH anchors as G-HASH) and refuses any other
   HTML comment (G-MARKER).
2. **Cites.** Every `DOC:line` or `` `NN`:line `` cite outside the copied D04 blocks is read at
   the base (G-CITE: the lines exist, the range's ends are non-blank); G-VERSION is content
   based: each cited range stands, in order and contiguous, somewhere in the file at
   `origin/main`; it also reads the version line (every sha a commit under the base, each pinned
   input's last touch, the named-only list). G-QUOTE: every quoted string of QUOTE_MIN characters
   or more is verbatim in a source its line cites, the deck, a core source or R578's own words.
3. **Gates.** D04 §2's 18 rows, §5 and §7 byte-equal at the base, and §9.4.1's re-found cites
   (G-COPY); the hash-lifts' row-id indexes and line ranges (G-INDEX); the redline cells, per
   density column, against the figures D02 states for that slot (G-REDLINE) and their tokens
   and boards against the slot's own D03 §2 row(s) and D03 §8.2 (G-THEMES); §0's status cells
   against the tool's probes (G-STATUS); the deck against D02 §13,
   D04 §7 and D03 (G-DECK); the Storybook lists against `15` and D02 §4 (G-STORYBOOK); the five
   settings keys against T and S02 and the regex rows (G-KEYS); the budgets' CITE anchors against
   the line each row cites, and each layer bound to its own anchor (G-BUDGET); the design-ahead rows against
   the ticket JSON and the calendar (G-AHEAD); the open-rows log against the parents' tables
   (G-OPENROWS); `14` = the pointer line + the six ticks and every other input byte-equal to the
   merge-base (G-UNTOUCHED); the dry-run table (G-WALK: a pending row passes before READY and
   FAILs under `--strict-walk`); every PNG named exists (G-PNG); the ruling stamp and the
   seventeen BQ ids (G-RULED); hygiene (G-HEX, G-PENPOT, G-NAMES, G-CLOSE, G-WORDS, G-SESSION).
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over EVERY unit of the pack
   (each heading, table row by its lead cell, rule line, prose sentence and fenced block, by
   region and location, NFKC and whitespace-normalised, with a line-shape tag per region) and
   every entry of the deck, in PIN_REL. Anchored values are pinned with their values cut out.
   `--repin-ruled` is the only writer and refuses while a placeholder is unfilled. A pin finding
   in a section another gate already FAILs prints as a WARN line.
5. **--self-test** applies one mutation per gate (M-n) with the values frozen at the filled
   baseline; each must add exactly one FAIL, from the gate it names, and every text is restored
   byte-identically (sha256 in memory and on disk). The report is ASCII, every line at most 100
   characters.

Usage (from the repo root):
  python3 -I docs/design/_tools/e22_d05_handoff_audit.py --check [SPEC] [--json] [--fill]
  python3 -I docs/design/_tools/e22_d05_handoff_audit.py --check --strict-walk
  python3 -I docs/design/_tools/e22_d05_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e22_d05_handoff_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import codecs
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
from typing import TypeVar

_T = TypeVar("_T")

ROOT = Path(__file__).resolve().parents[3]
BASE = "9c16743339"  # every cite was read here (the pack's Inputs line)
HEAD = "origin/main"  # G-VERSION: a cited range edited at origin/main FAILs

SPEC_REL = "docs/design/E22/E22-D05.md"
DECK_REL = "docs/design/E22/E22-D05-copy.json"
TOOL_REL = "docs/design/_tools/e22_d05_handoff_audit.py"
PIN_REL = "docs/design/_tools/e22_d05_ruled_pins.txt"
PLAN14_REL = "docs/plan/14-screens-catalogue.md"
OWN_PATHS = (SPEC_REL, DECK_REL, TOOL_REL, PIN_REL, PLAN14_REL)
IMG_REL = "docs/design/E22/img"

CITE_FILES: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": PLAN14_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "21": "docs/plan/21-database-schema.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "26": "docs/plan/26-chart-engine-design.md",
    "D02": "docs/design/E22/E22-D02.md",
    "D03": "docs/design/E22/E22-D03.md",
    "D03H": "docs/design/E22/E22-D03-handoff.md",
    "D04": "docs/design/E22/E22-D04.md",
    "README": "docs/design/README.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "LIM": "services/api/candleviewer/orderflow/limits.py",
    "E22J": "docs/plan/backlog/E22.json",
}
DOC_KEYS = tuple(k for k in CITE_FILES if not k.isdigit())
# the untouched inputs: byte-equal to the merge-base (G-UNTOUCHED); `14` only by its seven lines
UNTOUCHED = ("02", "06", "11", "15", "21", "22", "23", "26")
UNTOUCHED_DOCS = ("D02", "D03", "D03H", "D04", "README", "CAL", "LIM", "E22J")
TICKET_KEY = "E22-D05"
STAMP = "RULED (orchestrator, 2026-10-30, #578 ruling of record — 6531540637's answer)"
PINNED_DOCS = {
    "D02": "4ce8f43822",
    "D03": "87e90e8392",
    "D03H": "87e90e8392",
    "D04": "757b765334",
    "11": "1044c4f602",
    "14": "c179308446",
    "15": "c179308446",
    "21": "174c691e18",
    "23": "9b30a1f372",
    "22": "174c691e18",
    "26": "d9da6b2f05",
    "LIM": "0836869e2f",
    "E22J": "13f5a32644",
}
NAMED_ONLY = (
    "#714",
    "#715",
    "#716",
    "#717",
    "#718",
    "#713",
    "#751",
    "#752",
    "#753",
    "#754",
    "#608",
    "#654",
    "#1398",
    "E05-T01",
)
RULED_VALUES = {"bq.total": "17"}
# R578's own words (G-QUOTE accepts them verbatim)
RULING_QUOTES = (
    "Analytics: named, unsourced",
    "Hand-off pack:",
    "filled at READY by the orchestrator's deputy",
    "re-sync needed",
    "named, never worded",  # the outside dry run's own words (#578 6533399589)
)
REPORT_WIDTH = 100
QUOTE_MIN = 12

# the seven `14` lines (RULED BQ-10): the pointer line directly before SCR-053's checklist line
# and its six boxes ticked with an evidence cite
POINTER_14 = "- **Hand-off pack:** [E22-D05.md](../design/E22/E22-D05.md) (v1, E22-D05)."
POINTER_SCREEN = "SCR-053"
CHECKLIST_PREFIX = "- **Design sign-off acceptance checklist:**"
TICK = re.compile(r"\[x\] (?P<item>[^\[\]]*?) \((?P<cite>E22-D0[2-5] §[^()]*)\)")
TICKS = 6
# the copied D04 blocks (G-COPY) and the lifted blocks (G-HASH, G-INDEX), line ranges at the base
COPIES = {"d04s2": ("D04", 96, 115), "d04s5": ("D04", 191, 237), "d04s7": ("D04", 265, 316)}
LIFTS = {
    "d02s3": ("D02", 97, 112),
    "d02s5": ("D02", 144, 184),
    "d02s6": ("D02", 186, 214),
    "d02s7": ("D02", 216, 245),
    "d02s11": ("D02", 281, 305),
    "d02s12": ("D02", 307, 327),
    "d03s2": ("D03", 98, 127),
    "d03s3": ("D03", 129, 159),
    "d03h": ("D03H", 1, 174),
    "d04s3": ("D04", 128, 156),
    "d04s4": ("D04", 158, 187),
    "d04s8": ("D04", 318, 331),
    "d04s9": ("D04", 333, 373),
}
# the row-id index of each D04 hash-lift: how the ids are read from the lifted text
INDEX_READERS: dict[str, str] = {
    "d04s3": r"^- (?:\*\*)?(DNA-\d+)",
    "d04s4": r"^- \*\*([^*(]+?)\.?(?: \(.*\))?\.?\*\*",
    "d04s8": r"^\| (KR-\d+) ",
    "d04s9": r"^\| (FP-\d+) ",
}
# the settings keys (G-KEYS): T's four, S02's fifth, and one rejected example
T_KEYS = (
    "bigtrade.threshold_mode",
    "bigtrade.threshold_value",
    "bigtrade.cluster_window_ms",
    "bigtrade.cluster_tolerance_ticks",
)
S02_KEY = "bigtrade.percentile_window_ms"
REJECTED_KEY = "bigtrade.BTCUSDT.threshold_mode"
T_STORIES = ("Circle", "Square", "Diamond", "TextMode", "LogScale")
# the dry-run roles (G-WALK), in order
WALK_ROLES = (
    ("E22-S01", "E22-S01"),
    ("E22-S02", "E22-S02"),
    ("E22-S03", "E22-S03"),
    ("E22-S04", "E22-S04"),
    ("E22-S05", "E22-S05"),
    ("motion and a11y", "Motion / a11y"),
    ("E22-Q01 and E22-Q04", "E22-Q01 / Q04"),
    ("FE lead", "FE lead"),
    ("chart-engine lead", "Engine lead"),
)
WALK_TABLE_HEAD = "12.4 The dry run's needs"
VERDICTS = ("FOUND", "NOT FOUND", "AMBIGUOUS")
# the parents' open-row tables (G-OPENROWS): (doc, first, last, lead-cell id pattern)
OPEN_SOURCES = (
    ("D02", 408, 534, r"C\d+|D02-C\d+|G\d+|D02-G\d+|Q\d+"),
    ("D02", 376, 389, r"A15-\d+"),
    ("D03", 325, 332, r"CR-\d+"),
    ("D03", 367, 386, r"A-\d+"),
    ("D03", 415, 487, r"D03-[CGQ]\d+"),
    ("D04", 450, 495, r"F-\d\d|[CGAD]-\d+"),
)
# the contract and tree probes (STATUS): key -> (kind, where, needle, value if found, else)
STATUS_PROBES: dict[str, tuple[str, str, str, str, str]] = {
    "G1": ("cite", "23", "`is_big_trade`", "served", "open"),
    "G2": ("cite", "23", "`cluster_size`", "served", "open"),
    "G5": ("cite", "22", "big_trade_notional", "served", "open"),
    "G10": ("cite", "22", "trade_cluster", "served", "open"),
    "a15.6": ("cmp", "CMP-056", "reorder via keyboard (`Alt+↑/↓`", "open", "applied"),
    "a15.7": ("cmp", "CMP-055", "`space.filterbar.*`", "open", "applied"),
    "web.tape": ("tree", "apps/web/src", "tape", "present", "absent"),
    "engine.options": (
        "ggrep",
        "packages/chart-engine",
        "interface BubbleOptions",
        "present",
        "absent",
    ),
    "engine.layer": (
        "ggrep",
        "packages/chart-engine",
        "BigTradeBubble|BubbleLayer",
        "present",
        "absent",
    ),
    "G3": ("cite", "15", '`sizeScale: "sqrt"', "served", "open"),
    "G7": ("ggrep", "packages/ui/tokens", "text\\.(buy|sell)", "served", "open"),
    "G11": ("cite", "22", "tape.paused", "served", "open"),
    "a15.4": ("cmp", "CMP-049", "`aria-sort`", "open", "applied"),
    "a15.5": ("cmp", "CMP-049", "`font.mono`", "open", "applied"),
    "a15.8": ("cmp", "CMP-011", '|"estimated"|', "open", "applied"),
    "token.aged": ("grep", "packages/ui/tokens", "opacity.bubble.aged", "present", "absent"),
    "sot.tape": ("grep", "scripts/sot-registry.json", "bubble|tape", "an entry", "no entry"),
}
# the banned words (G-WORDS), rot13 so this public file never spells them
BANNED_ROT13 = (
    "yrnx",
    "rkcbfrq",
    "olcnff",
    "rkcybvg",
    "nggnpx",
    "benpyr",
    "erirny",
    "haobhaqrq",
    "sybbq",
    "fgnyy",
    "qbf",
    "nqivfbel",
    "tufn",
    "cer-nhgu",
)

# the pack's section heads (the first words of each heading; `section()` matches by prefix)
RULED_HEAD = "The questions BQ-01..BQ-17"
FRAME_HEAD = "2. The frame register"
STORY_HEAD = "3.1 What each story builds"
COMP_HEAD = "4.1 Components"
CMP112_HEAD = "4.2 CMP-112 stories"
TAPE_HEAD = "4.3 The tape organism"
KEYS_HEAD = "5. Persistence keys"
BUDGET_HEAD = "6. Budgets"
REDLINE_HEAD = "8.1 SCR-053 redlines"
DECK_HEAD = "8.4 The deck"
D04_HEAD = "9. The motion"
ENTRY_HEAD = "9.2 The entry table"
ROWCOPY_HEAD = "8.1.1 Row anatomy"
COPY_HEADS = (ENTRY_HEAD, "9.3 Reduced motion", "9.4 Announcements", ROWCOPY_HEAD)
COPYCITE_HEAD = "9.4.1 After the copy"
STATUS_HEAD = "0. Status and evidence"
LIFT_HEAD = "9.5 Lifted by hash"
AHEAD_HEAD = "10. The design-ahead record"
OPEN_HEAD = "11.1 The parents' rows"
PROTO_HEAD = "12.2 The walkthrough protocol"
WALK_HEAD = "12.3 The story-role dry run"
VERSION_HEAD = "13. Versions and deltas"
SIGN_HEAD = "14. Sign-off"

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z0-9]+:[^>]+?)-->")
ANCHOR_VALUE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|[a-f0-9]{12}|no match|match|served|open|applied|absent|present"
    r"|no entry|an entry|\d{1,3}(?: \d{3})+|\d+)$"
)
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"([^"\n]*)"')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]|\b[a-z0-9-]+\.(?:com|net|org|io|dev)\b", re.IGNORECASE)
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
NAMES = re.compile(
    r"\b(?:hpe|hcl)-\w|\bworker-\d\b|\w+-orchestrator\b|\bAgent [A-Z]\b|/home/\w|/mnt/c/|userToken"
    r"|team id|file id `|\bsession [0-9a-f]{8}",
    re.IGNORECASE,
)
PENPOT_WORDS = re.compile(r"workspace URL|team/[0-9a-f]|/view\?|/workspace/", re.IGNORECASE)
CLOSING = re.compile(r"\b(?:Closes|Fixes|Resolves)\s+#\d+", re.IGNORECASE)
SESSION_WORDS = re.compile(
    r"(?<![Nn]o )\bsession (?:was )?held\b|\bengineers met\b|\bmet with the\b"
    r"|\bwalked through with the (?:FE|chart-engine) lead\b|\bin the session the\b",
    re.IGNORECASE,
)
PNG_NAME = re.compile(r"`(E22-D03-\d\d-[a-z0-9-]+\.png)`")
TOKEN = re.compile(r"`((?:color|opacity|size|space|type|border|radius)\.[a-z0-9.-]+)`")
NUMBER = re.compile(r"\d{1,3}(?: \d{3})+|\d+")
# a cite: a doc key or a backticked plan id, then `:n` or `:n–m`; the nearest preceding key in
# the same cell or clause binds every later `:n` reference
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
PLAN_OVERRIDE: list[tuple[str, str]] = []  # self-test lever: a working-tree plan text (id, text)
PIN_UNITS_OVERRIDE: list[tuple[Unit, ...]] = []  # self-test lever: re-pinned units
HEAD_OVERRIDE: list[tuple[str, str]] = []  # self-test lever: (rel, text) pretended at origin/main
IMG_OVERRIDE: list[frozenset[str]] = []  # self-test lever: the PNG folder's names
STRICT_WALK: list[bool] = []  # --strict-walk: a pending dry-run row FAILs


def banned_words() -> tuple[str, ...]:
    return tuple(codecs.decode(w, "rot13") for w in BANNED_ROT13)


# ---------------------------------------------------------------------------- git and sources


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


def git_out(*args: str) -> str:
    return git_ok(*args)[1]


@functools.lru_cache(maxsize=256)
def git_show(rev: str, rel: str) -> str | None:
    ok, out = git_ok("show", f"{rev}:{rel}")
    return out if ok else None


def base_lines(cid: str) -> list[str]:
    rel = CITE_FILES.get(cid)
    text = git_show(BASE, rel) if rel else None
    return (text or "").split("\n")


def base_line(cid: str, n: int) -> str:
    lines = base_lines(cid)
    return lines[n - 1] if 1 <= n <= len(lines) else ""


@functools.cache
def line_of(cid: str, needle: str, start: int = 0) -> int:
    """The 1-based number of the first line at the base, from `start`, holding `needle`
    (0 when none): the anchors are found by content, never by a fixed line."""
    for i, ln in enumerate(base_lines(cid)[start:], start + 1):
        if needle in ln:
            return i
    return 0


@functools.cache
def source_text(cid: str) -> str:
    return "\n".join(base_lines(cid))


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


@functools.cache
def tree_paths(prefix: str) -> tuple[str, ...]:
    ok, out = git_ok("ls-tree", "-r", "--name-only", BASE, "--", prefix)
    return tuple(p for p in out.split("\n") if p) if ok else ()


# ---------------------------------------------------------------------------- markdown helpers

COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^(#{1,6}) (.*)$")
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[A-Z_*`\"(])")


def strip_comments(text: str) -> str:
    return COMMENT.sub("", text)


def fenced(lines: list[str]) -> list[bool]:
    out: list[bool] = []
    open_, mark = False, ""
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
    start: int | None = None
    level = 9
    for i, ln in enumerate(lines):
        m = HEADING.match(ln) if not fence[i] else None
        if m and start is None and m[2].startswith(head):
            start, level = i, len(m[1])
        elif m and start is not None and len(m[1]) <= level:
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
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if m and m[2].startswith(head):
            return m[2] if len(m[1]) == 2 else h2_at(text, i + 1)
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


def raw_rows(text: str, head: str) -> list[list[str]]:
    """The table rows under a heading with their value anchors kept (split, not stripped)."""
    rows = [split_row(ln) for ln in section(text, head).split("\n") if ln.lstrip().startswith("|")]
    return [r for r in rows if not all(re.fullmatch(r":?-{3,}:?", c) for c in r)][1:]


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", strip_comments(s))
    s = re.sub(r"[*`_]", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def pin_norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


def loose(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[‐-―−]", "-", s).replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def ascii_line(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def report(line: str) -> str:
    s = ascii_line(line)
    return s if len(s) <= REPORT_WIDTH else s[: REPORT_WIDTH - 3] + "..."


def F(tag: str, msg: str, doc: str | None, sec: str | None) -> Finding:
    return (tag, msg, doc, sec)


def expand_ids(cell: str) -> set[str]:
    """Every id a cell names: single ids and inclusive ranges `X1–X9` with one prefix."""
    out: set[str] = set()
    for part in re.split(r",\s*|;\s*", strip_comments(cell)):
        part = part.strip().strip("`")
        m = re.fullmatch(r"([A-Za-z0-9-]*?)(\d+)–([A-Za-z0-9-]*?)(\d+)", part)
        if m and (m[3] in ("", m[1])):
            width = len(m[2])
            for n in range(int(m[2]), int(m[4]) + 1):
                out.add(f"{m[1]}{n:0{width}d}")
        elif part:
            out.add(part)
    return out


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
    if not isinstance(s, dict):
        return {}
    return {str(k): v for k, v in s.items() if isinstance(v, dict)}


def str_list(v: object) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else []


# ---------------------------------------------------------------------------- values


def figure_at(cid: str, needle: str, pattern: str) -> tuple[int, str]:
    """(line, figure): the first line at the base holding `needle`, and the figure `pattern`
    captures on it ("?" when either is missing)."""
    n = line_of(cid, needle)
    m = re.search(pattern, strip_comments(base_line(cid, n))) if n else None
    return n, (m[1].replace("_", " ") if m else "?")


# CITE key -> (cite id, needle that finds the line, pattern that captures the figure)
CITES: dict[str, tuple[str, str, str]] = {
    "perf.fps": ("11", "≥55 fps at 2 000 prints/s", r"≥(\d+) fps"),
    "perf.rate": ("11", "≥55 fps at 2 000 prints/s", r"at (\d{1,3}(?: \d{3})*) prints/s"),
    "perf.dom": ("14", "≤60 rows in the DOM", r"≤(\d+) rows in the DOM"),
    "perf.ring": ("14", "≤60 rows in the DOM", r"ring buffer of (\d{1,3}(?: \d{3})*) prints"),
    "perf.lod": ("26", "Keep ≤ 500 visible instances", r"Keep ≤ (\d+) visible"),
    "lim.visible": ("LIM", "VISIBLE_BUBBLES_MAX:", r"= ([\d_]+)"),
    "lim.ws": ("LIM", "CLUSTER_WINDOW_MS_MAX_WS:", r"= ([\d_]+)"),
    "lim.rest": ("LIM", "CLUSTER_WINDOW_MS_MAX_REST:", r"= ([\d_]+)"),
    "lim.ticks": ("LIM", "CLUSTER_TOLERANCE_TICKS_MAX:", r"= ([\d_]+)"),
    "lim.symbols": ("LIM", "THRESHOLD_SYMBOLS_PER_USER_MAX:", r"= ([\d_]+)"),
    "lim.ring": ("LIM", "RING_BUFFER_MAX_PRINTS:", r"= ([\d_]+)"),
    "s02.debounce": ("E22J", "debounce writes (", r"debounce writes \((\d+) ms\)"),
}


def cite_values() -> Values:
    return {k: figure_at(c, n, p)[1] for k, (c, n, p) in CITES.items()}


@functools.cache
def cal_start() -> datetime.date:
    m = re.search(
        r"SPRINT01_START = datetime\.date\((\d{4}), (\d{1,2}), (\d{1,2})\)", source_text("CAL")
    )
    return datetime.date(int(m[1]), int(m[2]), int(m[3])) if m else datetime.date(2026, 9, 25)


@functools.cache
def cal_days() -> int:
    m = re.search(r"SPRINT_DAYS = (\d+)", source_text("CAL"))
    return int(m[1]) if m else 7


def sprint_start(n: int) -> datetime.date:
    return cal_start() + datetime.timedelta(days=(n - 1) * cal_days())


def sprint_end(n: int) -> datetime.date:
    return sprint_start(n + 1) - datetime.timedelta(days=1)


def sprint_of(day: datetime.date) -> int:
    return (day - cal_start()).days // cal_days() + 1


def sprint_values() -> Values:
    return {
        "s06.end": sprint_end(6).isoformat(),
        "s09.end": sprint_end(9).isoformat(),
        "s12.start": sprint_start(12).isoformat(),
        "s13.start": sprint_start(13).isoformat(),
        "margin.s12": str((sprint_start(12) - sprint_end(9)).days),
        "margin.s06": str((sprint_start(12) - sprint_end(6)).days),
    }


def lift_text(key: str) -> str:
    cid, a, b = {**LIFTS, **COPIES}[key]
    return "\n".join(base_lines(cid)[a - 1 : b])


def hash_values() -> Values:
    return {k: hashlib.sha256(lift_text(k).encode("utf-8")).hexdigest()[:12] for k in LIFTS}


@functools.cache
def st_key_fmt() -> str:
    m = re.search(r"st_key_fmt CHECK \(key ~ '([^']+)'\)", source_text("21"))
    return m[1] if m else "(?!)"


def regex_values() -> Values:
    keys = (*T_KEYS, S02_KEY, REJECTED_KEY)
    return {k: ("match" if re.fullmatch(st_key_fmt(), k) else "no match") for k in keys}


def cmp_block(cmp: str) -> str:
    lines = base_lines("15")
    start = line_of("15", f"### {cmp} ")
    if not start:
        return ""
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("### ")), len(lines))
    return "\n".join(lines[start - 1 : end])


def status_values() -> Values:
    out: Values = {}
    for key, (kind, where, needle, yes, no) in STATUS_PROBES.items():
        if kind == "cite":
            hit = needle in source_text(where)
        elif kind == "cmp":
            hit = needle in cmp_block(where)
        elif kind == "tree":
            hit = any(needle in p.lower() for p in tree_paths(where))
        elif kind == "ggrep":
            ok, found = git_ok("grep", "-l", "-E", needle, BASE, "--", where)
            hit = ok and bool(found.strip())
        else:
            texts = [git_show(BASE, p) or "" for p in tree_paths(where)]
            hit = any(re.search(needle, x, re.IGNORECASE) for x in texts)
        out[key] = yes if hit else no
    return out


def img_names() -> frozenset[str]:
    if IMG_OVERRIDE:
        return IMG_OVERRIDE[-1]
    folder = ROOT / IMG_REL
    return frozenset(p.name for p in folder.glob("*.png")) if folder.is_dir() else frozenset()


def numbered_items(spec: str, head: str) -> int:
    return len([ln for ln in section(spec, head).split("\n") if re.match(r"^\d{1,2}\. ", ln)])


def cmp112_list(spec: str) -> list[str]:
    body = norm_text(section(spec, CMP112_HEAD))
    m = re.search(r"minimum and come first: (.*?)\. ", body)
    if not m:
        return []
    names = re.sub(r"\(T minimum\)", "", m[1])
    return [n.strip() for n in re.split(r"[,·]", names) if n.strip()]


@functools.cache
def shift_14() -> int:
    needle = "opt-in polite announcements for whale prints only"
    old = (git_show(PINNED_DOCS["D04"], PLAN14_REL) or "").split("\n")
    at = next((i for i, ln in enumerate(old, 1) if needle in ln), 0)
    return line_of("14", needle) - at if at else -1


def walk_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, WALK_TABLE_HEAD) if len(r) >= 5]


def count_values(spec: str, deck: str) -> Values:
    entries = deck_entries(deck)
    return {
        "pngs": str(len(img_names())),
        "deck": str(len(entries)),
        "deck.d02": str(sum(1 for k in entries if k.startswith("d02.13."))),
        "deck.unkeyed": str(
            sum(1 for k in entries if k.startswith("d02.") and not k.startswith("d02.13."))
        ),
        "deck.named": str(sum(1 for e in entries.values() if e.get("status") == "named-elsewhere")),
        "deck.proposed": str(sum(1 for e in entries.values() if e.get("status") == "proposed")),
        "walk.needs": str(len(walk_rows(spec))),
        "walk.found": str(sum(1 for r in walk_rows(spec) if r[3] == "FOUND")),
        "walk.notfound": str(sum(1 for r in walk_rows(spec) if r[3] == "NOT FOUND")),
        "walk.ambiguous": str(sum(1 for r in walk_rows(spec) if r[3] == "AMBIGUOUS")),
        "deck.d04": str(sum(1 for k in entries if k.startswith("d04."))),
        "deck.d03": str(sum(1 for k in entries if k.startswith("d03."))),
        "stories.cmp112": str(len(cmp112_list(spec))),
        "stories.tape": str(len(rows_of(spec, TAPE_HEAD))),
        "walk.items": str(numbered_items(spec, PROTO_HEAD)),
        "d04.rows": str(sum(1 for r in rows_of(spec, ENTRY_HEAD) if r[0].startswith("D4-"))),
        "shift.14": str(shift_14()),
    }


def compute(spec: str, deck: str) -> Values:
    out: Values = {}
    for kind, vals in (
        ("CITE", cite_values()),
        ("COUNT", count_values(spec, deck)),
        ("HASH", hash_values()),
        ("SPRINT", sprint_values()),
        ("REGEX", regex_values()),
        ("STATUS", status_values()),
        ("RULED", RULED_VALUES),
    ):
        out.update({f"{kind}:{k}": v for k, v in vals.items()})
    return out


def in_code(line: str, pos: int) -> bool:
    return any(m.start() <= pos < m.end() for m in CODE.finditer(line))


def fill(text: str, values: Values) -> tuple[str, list[str]]:
    unknown: list[str] = []
    out = []
    for ln in text.split("\n"):
        pieces, last = [], 0
        for m in PLACEHOLDER.finditer(ln):
            if in_code(ln, m.start()):
                continue
            pieces.append(ln[last : m.start()])
            if m[1] in values:
                pieces.append(f"{values[m[1]]}<!--={m[1]}-->")
            else:
                unknown.append(m[1])
                pieces.append(m[0])
            last = m.end()
        pieces.append(ln[last:])
        out.append("".join(pieces))
    return "\n".join(out), unknown


def anchored(line: str) -> list[tuple[str, str, int]]:
    """(key, value as written, position) for every `VALUE<!--=KEY-->` on a line."""
    out = []
    for m in ANCHOR.finditer(line):
        v = ANCHOR_VALUE.search(line[: m.start()])
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
                msg = f"line {i}: {key} reads {val!r}, computed {values[key]!r}"
                bad.append(F(tag, msg, "spec", h2_at(text, i)))
        for m in PLACEHOLDER.finditer(ln):
            if not in_code(ln, m.start()):
                msg = f"line {i}: unfilled placeholder {m[0]}"
                bad.append(F("G-ANCHOR", msg, "spec", h2_at(text, i)))
    return bad


def g_marker_doc(text: str) -> list[Finding]:
    bad: list[Finding] = []
    for i, ln in enumerate(text.split("\n"), 1):
        for m in COMMENT.finditer(ln):
            if not ANCHOR.fullmatch(m[0]):
                msg = f"line {i}: an HTML comment that is not a value anchor"
                bad.append(F("G-MARKER", msg, "spec", h2_at(text, i)))
    return bad


# ---------------------------------------------------------------------------- cites


def copied_lines(spec: str) -> frozenset[int]:
    """0-based indexes of the spec lines under the three copy headings (their cites are D04's;
    G-COPY owns their bytes)."""
    lines = spec.split("\n")
    out: set[int] = set()
    cur = False
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if m:
            cur = any(m[2].startswith(h) for h in COPY_HEADS)
        elif cur:
            out.add(i)
    return frozenset(out)


def cite_refs(line: str) -> list[tuple[str, int, int]]:
    """(cite id, first, last) for every cite on a rendered line: the nearest preceding key in
    the same cell or clause binds each `:n` reference."""
    out: list[tuple[str, int, int]] = []
    for clause in CLAUSE_SPLIT.split(strip_comments(line)):
        events: list[tuple[int, str, str, int, int]] = []
        for m in KEY_TOKEN.finditer(clause):
            events.append((m.start(), "key", m[1] or m[2], 0, 0))
        for m in KEY_REF.finditer(clause):
            a = int(m[3])
            events.append((m.end() - 1, "ref", "", a, int(m[4]) if m[4] else a))
        for m in REF_TOKEN.finditer(clause):
            a = int(m[1])
            events.append((m.start(), "ref", "", a, int(m[2]) if m[2] else a))
        events.sort(key=lambda e: e[0])
        cur: str | None = None
        for _pos, kind, key, a, b in events:
            if kind == "key":
                cur = key
            elif cur is not None and cur in CITE_FILES:
                out.append((cur, a, b))
    return out


def unique_block(base: list[str], a: int, b: int) -> list[str]:
    lo, hi = a - 1, b
    while base[lo:hi] and base.count(base[lo]) > 1 and (lo > 0 or hi < len(base)):
        lo, hi = max(0, lo - 1), min(len(base), hi + 1)
    return base[lo:hi]


@functools.cache
def head_joined_git(rel: str) -> str:
    return "\n" + (git_show(HEAD, rel) or "") + "\n"


def head_joined(rel: str) -> str:
    for r, text in reversed(HEAD_OVERRIDE):
        if r == rel:
            return "\n" + text + "\n"
    return head_joined_git(rel)


def spec_cite_lines(spec: str) -> list[tuple[int, str]]:
    """Every spec line outside the copied blocks; in §9.4.1's table the first cell (the D04
    cite as the copy states it) is dropped, since only its re-found cite holds at the base."""
    skip = copied_lines(spec)
    table = set(section(spec, COPYCITE_HEAD).split("\n"))
    out = []
    for i, ln in enumerate(spec.split("\n"), 1):
        if i - 1 in skip:
            continue
        if ln in table and ln.startswith("|") and not is_rule(ln):
            ln = "| " + " | ".join(split_row(ln)[1:]) + " |"
        out.append((i, ln))
    return out


def cite_findings(t: Texts) -> tuple[list[Finding], int]:
    fails: list[Finding] = []
    done: set[tuple[str, int, int]] = set()
    if not head_ok():
        fails.append(F("G-VERSION", f"{HEAD} does not resolve: no range compared", None, None))
    deck_lines = [str(e.get("source", "")) for e in deck_entries(t.deck).values()]
    sources = [
        ("spec", [(i, ln, h2_at(t.spec, i)) for i, ln in spec_cite_lines(t.spec)]),
        ("deck", [(i, " " + ln, "(deck)") for i, ln in enumerate(deck_lines, 1)]),
    ]
    for doc, rows in sources:
        for _i, ln, sec in rows:
            for cid, a, b in cite_refs(ln):
                if (cid, a, b) in done:
                    continue
                done.add((cid, a, b))
                lines = base_lines(cid)
                if lines == [""]:
                    fails.append(F("G-CITE", f"{cid} is not readable at the base", doc, sec))
                    continue
                if a < 1 or b > len(lines) or b < a:
                    msg = f"{cid}:{a}-{b} is outside the file ({len(lines)} lines)"
                    fails.append(F("G-CITE", msg, doc, sec))
                    continue
                if not lines[a - 1].strip() or not lines[b - 1].strip():
                    msg = f"{cid}:{a}-{b} starts or ends on a blank line"
                    fails.append(F("G-CITE", msg, doc, sec))
                if head_ok():
                    block = unique_block(lines, a, b)
                    if ("\n" + "\n".join(block) + "\n") not in head_joined(CITE_FILES[cid]):
                        msg = f"{cid}:{a}-{b} was edited at {HEAD}"
                        fails.append(F("G-VERSION", msg, doc, sec))
    return fails, len(done)


@functools.cache
def loose_source(cid: str) -> str:
    return loose(source_text(cid))


@functools.cache
def core_sources() -> str:
    return loose(
        "\n".join(source_text(c) for c in ("D02", "D03", "D03H", "D04", "11", "14", "15", "E22J"))
    )


def g_quote(t: Texts) -> list[Finding]:
    """Every quoted string of QUOTE_MIN+ characters is verbatim in a source the line cites, the
    deck, a core source or R578's own words."""
    entries = deck_entries(t.deck)
    deck_text = loose("\n".join(str(e.get("text", "")) for e in entries.values()))
    ruled = loose("\n".join(RULING_QUOTES))
    bad: list[Finding] = []
    for i, ln in spec_cite_lines(t.spec):
        cited = tuple(dict.fromkeys(c for c, _a, _b in cite_refs(ln)))
        for q in QUOTED.findall(strip_comments(ln)):
            q = q.strip()
            if len(q) < QUOTE_MIN or "…" in q or "<" in q:
                continue
            lq = loose(q)
            if (
                lq in deck_text
                or lq in ruled
                or any(lq in loose_source(c) for c in cited)
                or lq in core_sources()
            ):
                continue
            msg = f"line {i}: {q[:60]!r} is in no cited source, the deck or R578"
            bad.append(F("G-QUOTE", msg, "spec", h2_at(t.spec, i)))
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
    bad += [
        F("G-VERSION", f"`{s}` is not a commit under the base", "spec", sec)
        for s in re.findall(r"`([0-9a-f]{10})`", line)
        if not under_base(s)
    ]
    pinned = line.split("**Pinned at their last touch at the base:**", 1)[-1].split("**", 1)[0]
    for cid, sha in PINNED_DOCS.items():
        last = last_touch(cid)
        if last != sha or f"`{sha}`" not in pinned:
            bad.append(F("G-VERSION", f"{cid} pinned at {sha}, last touched {last}", "spec", sec))
    named = line.split("**Named only, never pinned or quoted:**", 1)[-1].split("**", 1)[0]
    bad += [
        F("G-VERSION", f"{n} is not in the named-only list", "spec", sec)
        for n in NAMED_ONLY
        if not re.search(re.escape(n) + r"(?![\w-])", named)
    ]
    if "**Late changes:**" not in line:
        bad.append(F("G-VERSION", "the version line has no late-changes field", "spec", sec))
    inputs = next((ln for ln in lines if ln.startswith("**Inputs pinned.**")), "")
    if inputs.count(BASE) < 2:
        bad.append(F("G-VERSION", f"the Inputs line does not name {BASE} twice", "spec", sec))
    vsec = spec_sec(t, VERSION_HEAD)
    rows = rows_of(t.spec, VERSION_HEAD)
    if not rows or any(r[0] != "v1" or r[1] != f"`{BASE}`" for r in rows):
        bad.append(F("G-VERSION", "a versions row is not v1 at the base", "spec", vsec))
    body = norm_text(section(t.spec, VERSION_HEAD))
    for need in ("re-sync needed", "posted once on each affected consumer", "affected story"):
        if need not in body:
            bad.append(F("G-VERSION", f"§13 lacks {need!r}", "spec", vsec))
    d = deck_data(t.deck)
    if d.get("base") != BASE or d.get("version") != "v1" or d.get("pack") != TICKET_KEY:
        msg = "the deck's pack, base or version is not E22-D05 v1 at the base"
        bad.append(F("G-VERSION", msg, "deck", "(deck)"))
    return bad


# ---------------------------------------------------------------------------- copy, lifts, redlines


def g_copy(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, D04_HEAD)
    joined = "\n" + t.spec + "\n"
    for key, (cid, a, b) in COPIES.items():
        block = lift_text(key)
        n = joined.count("\n" + block + "\n")
        if n != 1:
            msg = f"{cid}:{a}-{b} ({key}) is present {n} times byte for byte, not once"
            bad.append(F("G-COPY", msg, "spec", sec))
    copies = "\n".join(lift_text(k) for k in COPIES)
    rows = rows_of(t.spec, COPYCITE_HEAD)
    if len(rows) != 4:
        bad.append(F("G-COPY", f"§9.4.1 has {len(rows)} rows, not 4", "spec", sec))
    for r in rows:
        if len(r) < 3:
            continue
        old = cite_refs(" " + r[0])
        new = cite_refs(" " + r[1])
        needle = r[2].strip("`")
        if not old or r[0] not in copies:
            bad.append(F("G-COPY", f"{r[0]}: not a cite inside the copies", "spec", sec))
        elif needle in base_line(old[0][0], old[0][1]):
            bad.append(F("G-COPY", f"{r[0]}: its old line still holds {needle!r}", "spec", sec))
        if not new or needle not in base_line(new[0][0], new[0][1]):
            bad.append(F("G-COPY", f"{r[1]}: the line does not hold {needle!r}", "spec", sec))
    return bad


def index_ids(key: str) -> list[str]:
    pat = re.compile(INDEX_READERS[key])
    out: list[str] = []
    for ln in lift_text(key).split("\n"):
        m = pat.match(ln)
        if m and m[1].strip() not in out:
            out.append(m[1].strip())
    return out


def g_index(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, LIFT_HEAD)
    rows = {r[3]: r for r in raw_rows(t.spec, LIFT_HEAD) if len(r) >= 4}
    by_hash = {k: r for r in rows.values() for k in LIFTS if f"<!--=HASH:{k}-->" in r[2]}
    raw = section(t.spec, LIFT_HEAD)
    for key in LIFTS:
        if f"<!--=HASH:{key}-->" not in raw and key.startswith(("d04", "d02")):
            bad.append(F("G-INDEX", f"{key} has no row in §9.5", "spec", sec))
    for key, r in by_hash.items():
        cid, a, b = LIFTS[key]
        if norm_text(r[1]) != f"{cid}:{a}–{b}":
            bad.append(F("G-INDEX", f"{key}: Lines reads {r[1]!r}, not {cid}:{a}–{b}", "spec", sec))
        if key in INDEX_READERS:
            want = index_ids(key)
            sep = "·" if "·" in r[3] else ","
            got = [x.strip() for x in norm_text(r[3]).split(sep) if x.strip()]
            if got != want:
                bad.append(
                    F("G-INDEX", f"{key}: the index is not {', '.join(want)[:60]}", "spec", sec)
                )
        else:
            body = lift_text(key)
            for rid in expand_ids(r[3]):
                if not re.search(r"\b" + re.escape(rid) + r"\b", body):
                    bad.append(
                        F("G-INDEX", f"{key}: {rid} is not in the lifted block", "spec", sec)
                    )
    return bad


# §8.1 row -> (compact, comfortable): (D02 line, pattern) pairs whose groups are the figures
REDLINE_SRC: dict[str, tuple[tuple[tuple[int, str], ...], tuple[tuple[int, str], ...]]] = {
    "Header row": (((83, r"\| (\d+) px = `size\.control\.compact`"),), ((93, r"header (\d+) ="),)),
    "Panel notice": (
        ((84, r"\| (\d+) px \(comfortable \d+\)"),),
        ((84, r"\| \d+ px \(comfortable (\d+)\)"),),
    ),
    "Status row": (
        ((85, r"\| (\d+) px = 20 px pills"),),
        ((85, r"pills \+ `space\.2` \(comfortable (\d+)"),),
    ),
    "Chips row": (((86, r"\| (\d+) px per row"),), ((86, r"`space\.2` \(comfortable (\d+)\)"),)),
    "Column header row": (((87, r"\| (\d+) px \(a 16 px"),), ((87, r"; comfortable (\d+)\)"),)),
    "The log at 1280": (
        ((88, r"\*\*(\d+) px at 1280×800 → (\d+) rows"),),
        ((88, r"comfortable: (\d+) → (\d+);"),),
    ),
    "The log at 2560": (
        ((88, r"; (\d{1,3}(?: \d{3})*) px at 2560×1440 → (\d+)\*\*"),),
        ((88, r"; (\d{1,3}(?: \d{3})*) → (\d+)\)"),),
    ),
    "Row, tiers": (
        ((88, r"`size\.row\.compact` (\d+) px"),),
        ((93, r"`size\.row\.comfortable` (\d+) px"),),
    ),
    "Control strip, collapsed": (
        ((89, r"collapsed by default: (\d+) px"),),
        ((89, r"one summary line; comfortable (\d+)\)"),),
    ),
    "Control strip, expanded": (
        ((89, r"expanded (\d+) px = three"),),
        ((89, r"`space\.2` \(comfortable (\d+)\)"),),
    ),
    "Cells and gaps": (
        ((91, r"at `type\.num\.sm` (\d+) px"), (91, r"`space\.2` (\d+) px gaps")),
        ((91, r"px gaps and (\d+) px cells"), (91, r"`space\.3` (\d+) px gaps and")),
    ),
    "Panel width": (
        ((91, r"\*\*(\d+) px minimum width compact\*\*"), (91, r"drawn at \*\*(\d+) px\*\*")),
        ((91, r"\*\*(\d+) px\*\* \((\d+) px if the"),),
    ),
}
# §8.1 row -> the D03 §2 rows (by lead) whose tokens and boards bind it
REDLINE_D03: dict[str, tuple[str, ...]] = {
    "Header row": ("Panel surface and header row",),
    "Panel notice": ("Panel notice",),
    "Status row": ("Status row",),
    "Chips row": ("Chips row (CMP-055)", "capped · compressed", '"(estimated)"'),
    "Column header row": ("Column header row",),
    "The log at": ("Row, tier 0", "Divider rows"),
    "Row, tiers": ("Row, tier 0", "Row, tier 1", "Row, tier 2", "Located row"),
    "Control strip": ("Control strip",),
    "Cells and gaps": ("Row, tier 0",),
    "Panel width": ("Panel surface and header row",),
}
D02_SLOTS = (
    "Header row",
    "Panel notice",
    "Status row",
    "Chips row",
    "Column header row",
    "The log",
    "Control strip",
)


def redline_expected(slot: str) -> tuple[list[str], list[str]] | None:
    """(compact, comfortable): the figures D02 states for a §8.1 row, parsed by position from
    the slot's own D02 line(s) (REDLINE_SRC); None when the row is unknown."""
    spec = next((v for k, v in REDLINE_SRC.items() if slot.startswith(k)), None)
    if spec is None:
        return None
    out: tuple[list[str], list[str]] = ([], [])
    for col, parts in enumerate(spec):
        for n, pattern in parts:
            m = re.search(pattern, base_line("D02", n))
            out[col].extend(m.groups() if m else ["?"])
    return out


def cell_numbers(cell: str) -> list[str]:
    """The figures of a cell in reading order (positional: an in-cell swap fails)."""
    cell = re.sub(r"D02-C\d+|\d+×\d+", "", strip_comments(cell))
    return NUMBER.findall(cell)


def g_redline(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, REDLINE_HEAD)
    rows = rows_of(t.spec, REDLINE_HEAD)
    slot_rows = [ln for ln in base_lines("D02")[80:89] if ln.startswith("| **")]
    for name in D02_SLOTS:
        if not any(name in ln for ln in slot_rows):
            bad.append(F("G-REDLINE", f"D02 §2 has no slot {name!r} at the base", "spec", sec))
        if not any(r[0].startswith(name) for r in rows):
            bad.append(F("G-REDLINE", f"D02 §2's slot {name!r} has no redline row", "spec", sec))
    for r in rows:
        want = redline_expected(r[0])
        if len(r) < 7 or want is None:
            bad.append(F("G-REDLINE", f"{r[0][:24]}: not a known slot row", "spec", sec))
            continue
        for col, label in ((1, "compact"), (2, "comfortable")):
            got, exp = cell_numbers(r[col]), want[col - 1]
            if got != exp:
                msg = f"{r[0][:24]}: {label} reads {got}, D02 states {exp}"
                bad.append(F("G-REDLINE", msg, "spec", sec))
    bad += row_copy_findings(t)
    return bad


def row_copy_findings(t: Texts) -> list[Finding]:
    """§8.1.1 is D02:101-112 cell for cell: each table row's cells by position, the rule row's
    width, and the D8-D12 and row-name paragraphs byte for byte."""
    bad: list[Finding] = []
    sec = spec_sec(t, ROWCOPY_HEAD)
    want = base_lines("D02")[100:112]
    got = [ln for ln in section(t.spec, ROWCOPY_HEAD).split("\n")]
    while got and not got[0].strip():
        got.pop(0)
    while got and not got[-1].strip():
        got.pop()
    if len(got) != len(want):
        return [
            F("G-REDLINE", f"§8.1.1 has {len(got)} lines, D02:101-112 has {len(want)}", "spec", sec)
        ]
    for k, (a, b) in enumerate(zip(got, want, strict=True), 101):
        if b.startswith("|") and not is_rule(b):
            ca, cb = split_row(a), split_row(b)
            for col, (x, y) in enumerate(zip(ca, cb, strict=False)):
                if x != y:
                    msg = f"§8.1.1 D02:{k} cell {col} reads {x[:24]!r}, not {y[:24]!r}"
                    bad.append(F("G-REDLINE", msg, "spec", sec))
            if len(ca) != len(cb):
                bad.append(F("G-REDLINE", f"§8.1.1 D02:{k} has {len(ca)} cells", "spec", sec))
        elif a != b:
            bad.append(F("G-REDLINE", f"§8.1.1 differs from D02:{k}", "spec", sec))
    return bad


@functools.cache
def resolved_tokens() -> dict[str, int]:
    """D03 §8.2's line: token -> the number of resolved theme values (shorthand expanded)."""
    line = base_line("D03", line_of("D03", "`color.surface.canvas` #"))
    out: dict[str, int] = {}
    parent = ""
    for seg in line.split(" · "):
        names = re.findall(r"`([a-z.][a-z0-9.-]*)`", seg)
        values = len(re.findall(r"#[0-9A-Fa-f]{6}", seg))
        for name in names:
            if name.startswith("."):
                parts, first = parent.split("."), name[1:].split(".")[0]
                cut = parts.index(first) if first in parts else len(parts) - 1
                full = ".".join(parts[:cut]) + name
            else:
                full, parent = name, name
            out[full] = values
    return out


def d03_rows(leads: tuple[str, ...]) -> list[list[str]]:
    rows = table_rows(lift_text("d03s2"))
    return [r for r in rows if any(r[0].startswith(x) for x in leads)]


def g_themes(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, REDLINE_HEAD)
    res = resolved_tokens()
    for r in rows_of(t.spec, REDLINE_HEAD):
        if len(r) < 6:
            continue
        leads = next((v for k, v in REDLINE_D03.items() if r[0].startswith(k)), ())
        own = d03_rows(leads)
        if not own:
            bad.append(F("G-THEMES", f"{r[0][:24]}: no D03 §2 row binds it", "spec", sec))
            continue
        text = " ".join(" ".join(x[1:4]) for x in own)
        boards = {b for x in own for b in re.findall(r"\d\d", x[-1])}
        if "01" in boards:
            boards.add("02")  # board 02 is board 01's light twin (D03 §0)
        toks = TOKEN.findall(r[3])
        for tok in toks:
            if f"`{tok}`" not in text:
                msg = f"{r[0][:24]}: `{tok}` is not in its D03 §2 row(s)"
                bad.append(F("G-THEMES", msg, "spec", sec))
        for b in re.findall(r"\d\d", r[5]):
            if b not in boards:
                msg = f"{r[0][:24]}: board {b} does not draw its D03 §2 row(s)"
                bad.append(F("G-THEMES", msg, "spec", sec))
        ok3 = all(res.get(x) == 3 for x in toks)
        want = "—" if not toks else ("dark · light · hc" if ok3 else "partial")
        if r[4] != want:
            msg = f"{r[0][:24]}: Themes reads {r[4]!r}, computed {want!r}"
            bad.append(F("G-THEMES", msg, "spec", sec))
    body = norm_text(section(t.spec, REDLINE_HEAD))
    need = "The comfortable-light and comfortable-dark full-panel cells are text-only"
    if need not in body:
        bad.append(F("G-THEMES", "§8.1 lacks the text-only sentence", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- deck, Storybook, keys


def d02_cp_rows() -> dict[str, tuple[int, list[str]]]:
    out: dict[str, tuple[int, list[str]]] = {}
    for n in range(329, 361):
        ln = base_line("D02", n)
        if re.match(r"^\| CP\d+ ", ln):
            cells = split_row(ln)
            out[cells[0]] = (n, cells)
    return out


def g_deck(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    entries = deck_entries(t.deck)
    cps = d02_cp_rows()
    d02_text = "\n".join(base_lines("D02")[328:360])

    def f(msg: str) -> None:
        bad.append(F("G-DECK", msg, "deck", "(deck)"))

    if not entries:
        f("the deck has no entries")
    seen: set[str] = set()
    for key, e in entries.items():
        src = str(e.get("source", ""))
        m = re.fullmatch(r"(D0[234]|E22J):(\d+)", src)
        strings = str_list(e.get("strings"))
        text = str(e.get("text", ""))
        if not m:
            f(f"{key}: source {src!r} is not a D02/D03/D04/E22J line")
            continue
        cid, n = m[1], int(m[2])
        if not str(e.get("status", "")) or not re.fullmatch(
            r"E22-S0[1-5]", str(e.get("story", ""))
        ):
            f(f"{key}: no status or no E22-S01..S05 story")
        if strings != QUOTED.findall(text):
            f(f"{key}: strings are not the quoted strings of its text")
        if key.startswith("d02.13.cp"):
            rid = str(e.get("row", ""))
            seen.add(rid)
            if rid not in cps or cps[rid][0] != n or pin_norm(cps[rid][1][2]) != pin_norm(text):
                f(f"{key}: the text is not D02 §13's {rid} cell at D02:{n}")
        elif e.get("status") == "named-elsewhere":
            owner = str(e.get("owner", ""))
            if strings or not owner or owner.split(" ")[0] not in base_line(cid, n):
                f(f"{key}: a named-elsewhere row words a string or misses its owner on {cid}:{n}")
        elif e.get("status") == "proposed" and cid != "E22J":
            one = strings[0] if len(strings) == 1 else ""
            line = base_line(cid, n).replace("–", "-")
            sentence = len(re.findall(r"[.!?](?:\s|$)", one)) == 1 and one.endswith(".")
            nums = NUMBER.findall(one)
            if not (one and len(one) <= 60 and sentence and nums and all(x in line for x in nums)):
                f(f"{key}: a proposed row is not one sentence of <= 60 naming its source's bounds")
        else:
            for s in strings:
                if s not in base_line(cid, n):
                    f(f"{key}: {s[:40]!r} is not on {cid}:{n}")
            if key.startswith("d05.06") and "estimate" not in str(e.get("label", "")):
                f(f"{key}: the memory figure is not labelled an estimate")
            if key.startswith(("d03.", "d02.")) and any(s in d02_text for s in strings):
                f(f"{key}: a D03 string already in D02 §13")
            if key.startswith("d04.") and "A38" not in str(e.get("stamp", "")):
                f(f"{key}: no A38 stamp")
    if seen != set(cps):
        f(f"the deck carries {len(seen)} of D02 §13's {len(cps)} rows")
    cp26 = entries.get("d02.13.cp26", {})
    tsrc = re.fullmatch(r"D02:(\d+)", str(cp26.get("template_source", "")))
    tmpl = str(cp26.get("template", ""))
    if not tsrc or not tmpl or tmpl not in base_line("D02", int(tsrc[1])):
        f("d02.13.cp26: the row-name template is not verbatim at its source")
    return bad


def g_storybook(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, CMP112_HEAD)
    sb = cmp_block("CMP-112")
    m = re.search(r"\*\*Storybook\*\*: `ChartEngine/BigTradeBubble` — (.*?)\.\n", sb + "\n")
    catalogue = [x.strip() for x in m[1].split(",")] if m else []
    got = cmp112_list(t.spec)
    if not catalogue or got != catalogue:
        bad.append(
            F("G-STORYBOOK", "§4.2's list is not `15` CMP-112's Storybook list", "spec", sec)
        )
    if tuple(got[:5]) != T_STORIES or ", ".join(T_STORIES) not in source_text("E22J"):
        bad.append(F("G-STORYBOOK", "T's five are not the first five", "spec", sec))
    if "(T minimum)" not in section(t.spec, CMP112_HEAD):
        bad.append(F("G-STORYBOOK", "T's five are not marked as the minimum", "spec", sec))
    tsec = spec_sec(t, TAPE_HEAD)
    states: list[str] = []
    state_lines: list[str] = []
    for n in range(114, 143):
        mm = re.match(r"^\| (S\d+) +\| \*\*([^*]+)\*\*", base_line("D02", n))
        if mm:
            states.append(mm[2])
            state_lines.append(base_line("D02", n))
    rows = rows_of(t.spec, TAPE_HEAD)
    keys = deck_entries(t.deck)
    if len(rows) != len(states) or not states:
        bad.append(
            F("G-STORYBOOK", f"§4.3 has {len(rows)} rows for {len(states)} states", "spec", tsec)
        )
    for k, (r, name) in enumerate(zip(rows, states, strict=False), 1):
        words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w and w.lower() != "the"]
        want = f"St{k:02d} " + "".join(w[0].upper() + w[1:] for w in words)
        if r[0] != want or r[1] != f"S{k}":
            bad.append(F("G-STORYBOOK", f"§4.3 row {k} reads {r[0]!r}, not {want!r}", "spec", tsec))
        for dk in re.findall(r"`(d0\d\.[a-z0-9.]+)`", r[2]):
            if dk not in keys:
                bad.append(F("G-STORYBOOK", f"§4.3 row {k}: {dk} is not a deck key", "spec", tsec))
        own = [q for q in QUOTED.findall(state_lines[k - 1]) if len(q) > 3]
        cited = [keys[dk] for dk in re.findall(r"`(d0\d\.[a-z0-9.]+)`", r[2]) if dk in keys]
        covered = any(s in state_lines[k - 1] for e in cited for s in str_list(e.get("strings")))
        covered = covered or any(q in r[2] for q in own)
        if own and not covered:
            msg = f"§4.3 row {k}: no cited deck row holds the state's own D02 string"
            bad.append(F("G-STORYBOOK", msg, "spec", tsec))
    for r in rows_of(t.spec, COMP_HEAD):
        if len(r) >= 4 and re.search(r"\b(?:built|shipped|implemented)\b", r[3], re.IGNORECASE):
            bad.append(
                F(
                    "G-STORYBOOK",
                    f"{r[0][:24]}: a story claimed built",
                    "spec",
                    spec_sec(t, COMP_HEAD),
                )
            )
    return bad


def g_keys(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, KEYS_HEAD)
    rows = rows_of(t.spec, KEYS_HEAD)
    named = [re.findall(r"`([^`]+)`", r[0])[0] for r in rows if re.findall(r"`([^`]+)`", r[0])]
    want = [*T_KEYS[:2], S02_KEY, *T_KEYS[2:], REJECTED_KEY]
    if named != want:
        bad.append(
            F(
                "G-KEYS",
                "§5's keys are not T's four, S02's fifth and the rejected example",
                "spec",
                sec,
            )
        )
    body = source_text("E22J")
    for k in T_KEYS:
        if k not in body:
            bad.append(F("G-KEYS", f"{k} is not in T", "spec", sec))
    if S02_KEY not in body:
        bad.append(F("G-KEYS", f"{S02_KEY} is not in S02", "spec", sec))
    for r in rows:
        if len(r) < 5:
            continue
        key = (re.findall(r"`([^`]+)`", r[0]) or [""])[0]
        if key != REJECTED_KEY and r[2] != "`object`":
            bad.append(F("G-KEYS", f"{key}: value_type is not object", "spec", sec))
        if r[4] != t.values.get(f"REGEX:{key}"):
            bad.append(F("G-KEYS", f"{key}: the regex cell is not the tool's", "spec", sec))
    if st_key_fmt() not in section(t.spec, KEYS_HEAD):
        bad.append(F("G-KEYS", "§5 does not state `21`'s st_key_fmt verbatim", "spec", sec))
    if "PROPOSED, no shape added" not in h2_of(t.spec, KEYS_HEAD):
        bad.append(F("G-KEYS", "§5's heading does not say PROPOSED, no shape added", "spec", sec))
    return bad


def g_budget(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, BUDGET_HEAD)
    for r in raw_rows(t.spec, BUDGET_HEAD):
        for key in re.findall(r"<!--=CITE:([^>]+)-->", r[1]):
            cid, needle, pattern = CITES[key]
            n = figure_at(cid, needle, pattern)[0]
            if (cid, n, n) not in cite_refs(" " + r[2]):
                msg = f"{r[0][:24]}: {key} is on {cid}:{n}, the row cites {r[2]}"
                bad.append(F("G-BUDGET", msg, "spec", sec))
    raw = section(t.spec, BUDGET_HEAD)
    for pattern in (
        r"<!--=CITE:lim\.visible--> is the engine's hard instance cap",
        r"<!--=CITE:perf\.lod--> is the LOD trigger",
        r"E22-K01 \(#608\) measures",
    ):
        if not re.search(pattern, raw):
            bad.append(F("G-BUDGET", f"§6 lacks {pattern[:40]!r}", "spec", sec))
    for r in raw_rows(t.spec, BUDGET_HEAD):
        label = r[0]
        if "hard instance cap" in label and "CITE:lim.visible" not in r[1]:
            bad.append(F("G-BUDGET", f"{label[:30]}: not the LIM cap", "spec", sec))
        if "LOD trigger" in label and "CITE:perf.lod" not in r[1]:
            bad.append(F("G-BUDGET", f"{label[:30]}: not `26`'s trigger", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- ahead, rows, `14`


@functools.cache
def ticket_sprints() -> dict[str, int]:
    try:
        data = json.loads(source_text("E22J"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, int] = {}
    for tk in data if isinstance(data, list) else []:
        if isinstance(tk, dict):
            m = re.search(r"(\d+)", str(tk.get("sprint", "")))
            if m:
                out[str(tk.get("key", ""))] = int(m[1])
    return out


def g_ahead(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, AHEAD_HEAD)
    sprints = ticket_sprints()
    for r in rows_of(t.spec, STORY_HEAD):
        for k in re.findall(r"E22-[A-Z]\d\d", r[0])[:1]:
            if len(r) > 1 and f"{sprints.get(k, 0):02d}" != r[1]:
                msg = f"{k}: §3.1 Sprint {r[1]}, E22J says {sprints.get(k)}"
                bad.append(F("G-AHEAD", msg, "spec", spec_sec(t, STORY_HEAD)))
    rows = rows_of(t.spec, AHEAD_HEAD)
    keys_seen: set[str] = set()
    margins = {12: "Sprints 10 and 11 whole", 13: "Sprints 10 to 12 whole"}
    for r in rows:
        keys = re.findall(r"E22-[A-Z]\d\d", r[0])
        keys_seen.update(keys)
        for k in keys:
            if f"{sprints.get(k, 0):02d}" != r[1]:
                bad.append(
                    F("G-AHEAD", f"{k}: Sprint {r[1]}, E22J says {sprints.get(k)}", "spec", sec)
                )
        if "the parent" in r[0]:
            if not r[-1].startswith("open, text merged"):
                bad.append(F("G-AHEAD", f"{r[0][:24]}: not 'open, text merged'", "spec", sec))
            continue
        if r[-1] != "met, no waiver":
            bad.append(F("G-AHEAD", f"{r[0][:24]}: not 'met, no waiver'", "spec", sec))
        want = margins.get(int(r[1]) if r[1].isdigit() else 0)
        if want and r[4] not in (want, "as above"):
            bad.append(F("G-AHEAD", f"{r[0][:24]}: the margin is not {want!r}", "spec", sec))
    need = {f"E22-S0{n}" for n in range(1, 6)} | {f"E22-Q0{n}" for n in range(1, 5)} | {"E22-D06"}
    readers = norm_text(
        next((ln for ln in t.spec.split("\n") if ln.startswith("**Readers:**")), "")
    )
    story_keys = {
        k for r in rows_of(t.spec, STORY_HEAD) for k in re.findall(r"E22-[A-Z]\d\d", r[0])
    }
    for k in sorted(need - {f"E22-S0{n}" for n in range(1, 6)}):
        if k not in readers:
            bad.append(F("G-AHEAD", f"{k} is not on the Readers line", "spec", "(top)"))
    for k in sorted({f"E22-Q0{n}" for n in range(1, 4)} - story_keys):
        bad.append(F("G-AHEAD", f"{k} is not in §3.1", "spec", spec_sec(t, STORY_HEAD)))
    if not need <= keys_seen:
        bad.append(F("G-AHEAD", f"§10 lacks {', '.join(sorted(need - keys_seen))}", "spec", sec))
    if sprints.get(TICKET_KEY) != 9:
        bad.append(F("G-AHEAD", "E22J does not put E22-D05 in Sprint 09", "spec", sec))
    body = norm_text(section(t.spec, AHEAD_HEAD))
    d03 = sprint_of(datetime.date(2026, 10, 29))
    d04 = sprint_of(datetime.date(2026, 10, 30))
    if (
        f"Sprint {d03:02d} (D03, 2026-10-29)" not in body
        or f"Sprint {d04:02d} (D04, 2026-10-30)" not in body
    ):
        bad.append(F("G-AHEAD", "the parents' close sprints are not the calendar's", "spec", sec))
    return bad


def parent_ids() -> set[str]:
    out: set[str] = set()
    for cid, a, b, pat in OPEN_SOURCES:
        rx = re.compile(r"^\| (" + pat + r") +\|")
        for n in range(a, b + 1):
            m = rx.match(base_line(cid, n))
            if m:
                out.add(f"{cid}:{m[1]}")
    return out


def g_openrows(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, OPEN_HEAD)
    listed: set[str] = set()
    for r in rows_of(t.spec, OPEN_HEAD):
        if len(r) < 4:
            continue
        refs = cite_refs(" " + r[1])
        if not refs:
            bad.append(F("G-OPENROWS", f"{r[0][:24]}: no parent lines", "spec", sec))
            continue
        cid = refs[0][0]
        for rid in expand_ids(r[0]):
            listed.add(f"{cid}:{rid}")
        if not r[2] or not r[3]:
            bad.append(F("G-OPENROWS", f"{r[0][:24]}: no owner lane or status", "spec", sec))
    stories = {
        k: r[3]
        for r in rows_of(t.spec, STORY_HEAD)
        if len(r) > 3
        for k in re.findall(r"E22-S0\d", r[0])[:1]
    }
    for r in rows_of(t.spec, "11.2 This pack's rows"):
        for k in re.findall(r"E22-S0\d", r[3] if len(r) > 3 else ""):
            if r[0] not in stories.get(k, ""):
                msg = f"{r[0]}: owner {k}, but §3.1's {k} row does not bind it"
                bad.append(F("G-OPENROWS", msg, "spec", spec_sec(t, STORY_HEAD)))
    have = parent_ids()
    for x in sorted(have - listed):
        bad.append(F("G-OPENROWS", f"{x} is not in the log", "spec", sec))
    for x in sorted(listed - have):
        bad.append(F("G-OPENROWS", f"{x} is named but is no parent row", "spec", sec))
    return bad


def revert_ticks(line: str) -> str:
    return TICK.sub(lambda m: f"[ ] {m['item']}", line)


def pointer_problems(text: str, base: str) -> list[str]:
    lines = text.split("\n")
    out: list[str] = []
    reverted = [revert_ticks(ln) for ln in lines if ln != POINTER_14]
    if reverted != base.split("\n"):
        out.append("`14` differs from the merge-base beyond the pointer line and the six ticks")
    at = [i for i, ln in enumerate(lines) if ln == POINTER_14]
    if len(at) != 1:
        return [*out, f"`14` carries {len(at)} pointer lines, not one"]
    head = max((i for i, ln in enumerate(lines[: at[0]]) if ln.startswith("### SCR-")), default=-1)
    if head < 0 or not lines[head].startswith(f"### {POINTER_SCREEN} "):
        out.append(f"the pointer line is not under {POINTER_SCREEN}")
    nxt = lines[at[0] + 1] if at[0] + 1 < len(lines) else ""
    ticks = TICK.findall(nxt)
    if not nxt.startswith(CHECKLIST_PREFIX):
        out.append("the pointer is not directly before the sign-off checklist line")
    if "[ ]" in nxt or len(ticks) != TICKS:
        out.append(f"the checklist carries {len(ticks)} evidence ticks, not {TICKS}")
    if sum(len(TICK.findall(ln)) for ln in lines) != TICKS:
        out.append("`14` carries a tick outside SCR-053's checklist")
    for _item, cite in ticks:
        if "E22-D02" in cite and "board" in cite.split("E22-D03")[0]:
            out.append("a tick cites D02's boards")
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


# ---------------------------------------------------------------------------- walk, PNGs, ruling


def g_walk(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, WALK_HEAD)
    rows = rows_of(t.spec, WALK_HEAD)
    needs = walk_rows(t.spec)
    if len(rows) != len(WALK_ROLES) or any(
        not r[0].startswith(role) for r, (role, _p) in zip(rows, WALK_ROLES, strict=False)
    ):
        bad.append(F("G-WALK", f"§12.3 does not list the {len(WALK_ROLES)} roles", "spec", sec))
    for r, (_role, prefix) in zip(rows, WALK_ROLES, strict=False):
        mine = [x for x in needs if x[1].startswith(prefix)]
        want = [len(mine), *(sum(1 for x in mine if x[3] == v) for v in VERDICTS)]
        try:
            got = [int(x) for x in r[1:5]]
        except ValueError:
            bad.append(F("G-WALK", f"{r[0][:30]}: a pending or non-numeric count", "spec", sec))
            continue
        if got != want:
            bad.append(F("G-WALK", f"{r[0][:30]}: counts {got}, §12.4 gives {want}", "spec", sec))
    tsec = spec_sec(t, WALK_TABLE_HEAD)
    if not needs:
        bad.append(F("G-WALK", "§12.4 has no needs", "spec", tsec))
    for r in needs:
        if r[3] not in VERDICTS:
            bad.append(F("G-WALK", f"{r[0]}: verdict {r[3]!r}", "spec", tsec))
        answer = r[4].strip()
        cited = bool(cite_refs(" " + answer)) or "§" in answer or "`d0" in answer
        if r[3] != "FOUND" and (not answer or answer in ("—", "-") or not cited):
            bad.append(F("G-WALK", f"{r[0]}: a {r[3]} need with no answer", "spec", tsec))
        if STRICT_WALK and not answer:
            bad.append(F("G-WALK", f"{r[0]}: an empty answer", "spec", tsec))
    items = numbered_items(t.spec, PROTO_HEAD)
    if not 1 <= items <= 10:
        bad.append(F("G-WALK", f"the protocol has {items} items", "spec", spec_sec(t, PROTO_HEAD)))
    return bad


def g_png(t: Texts) -> list[Finding]:
    have = img_names()
    sec = spec_sec(t, FRAME_HEAD)
    names = set(PNG_NAME.findall(t.spec))
    bad = [F("G-PNG", f"{n} is not under {IMG_REL}", "spec", sec) for n in sorted(names - have)]
    if not names:
        bad.append(F("G-PNG", "no board PNG is named", "spec", sec))
    return bad


def g_ruled(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    first = next((ln for ln in t.spec.split("\n") if ln.startswith("**Ticket:**")), "")
    if STAMP not in first:
        bad.append(F("G-RULED", "the header does not carry the ruling stamp", "spec", "(top)"))
    sec = spec_sec(t, RULED_HEAD)
    body = section(t.spec, RULED_HEAD)
    for n in range(1, 18):
        if f"BQ-{n:02d}" not in body:
            bad.append(F("G-RULED", f"BQ-{n:02d} is not in the ruled section", "spec", sec))
    if not any(
        ln.startswith("## ") and STAMP.removeprefix("RULED ") in ln for ln in t.spec.split("\n")
    ):
        bad.append(
            F("G-RULED", "the ruled section's heading does not carry the stamp", "spec", sec)
        )
    return bad


def g_status(t: Texts) -> list[Finding]:
    """§0's Status cell agrees with the tool's tree probes and contract reads."""
    bad: list[Finding] = []
    sec = spec_sec(t, STATUS_HEAD)
    rows = raw_rows(t.spec, STATUS_HEAD)
    if not rows:
        bad.append(F("G-STATUS", "§0 has no status table", "spec", sec))
    for r in rows:
        if len(r) < 4:
            continue
        built, status = r[2], strip_comments(r[3])
        if "absent<!--=STATUS:" in built and status not in ("unbuilt", "pending"):
            bad.append(
                F("G-STATUS", f"{r[0][:24]}: absent at the base but {status!r}", "spec", sec)
            )
        if "served" in built and status != "built (backend)":
            bad.append(F("G-STATUS", f"{r[0][:24]}: served but {status!r}", "spec", sec))
        if "STATUS:" not in built and "served" not in built and status.startswith("built"):
            bad.append(F("G-STATUS", f"{r[0][:24]}: 'built' with no evidence", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- hygiene


def scan(t: Texts, tag: str, hit: Callable[[str], bool], what: str) -> list[Finding]:
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            if hit(ln):
                where = h2_at(text, i) if doc == "spec" else "(deck)"
                bad.append(F(tag, f"{doc} line {i}: {what}", doc, where))
    return bad


def g_hex(t: Texts) -> list[Finding]:
    return scan(t, "G-HEX", lambda ln: bool(HEXLIT.search(ln)), "a hex colour literal")


def g_penpot(t: Texts) -> list[Finding]:
    return scan(
        t,
        "G-PENPOT",
        lambda ln: bool(URL.search(ln) or UUID.search(ln) or PENPOT_WORDS.search(ln)),
        "a URL, hostname, UUID or workspace word",
    )


def g_names(t: Texts) -> list[Finding]:
    return scan(t, "G-NAMES", lambda ln: bool(NAMES.search(ln)), "an agent, user or host name")


def g_words(t: Texts) -> list[Finding]:
    words = banned_words()
    return scan(t, "G-WORDS", lambda ln: any(w in ln.lower() for w in words), "a banned word")


def g_close(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    hits = [(i, m[0]) for i, ln in enumerate(t.spec.split("\n"), 1) for m in CLOSING.finditer(ln)]
    ok_secs = ("(top)", spec_sec(t, RULED_HEAD), spec_sec(t, SIGN_HEAD))
    allowed = [h for h in hits if h[1] == "Closes #578" and h2_at(t.spec, h[0]) in ok_secs]
    for i, word in hits:
        if (i, word) not in allowed:
            msg = f"line {i}: {word!r} outside the header, the ruled section and §14"
            bad.append(F("G-CLOSE", msg, "spec", h2_at(t.spec, i)))
    if len(allowed) > 3:
        bad.append(F("G-CLOSE", "`Closes #578` is stated more than three times", "spec", "(top)"))
    for i, ln in enumerate(t.deck.split("\n"), 1):
        if CLOSING.search(ln):
            bad.append(F("G-CLOSE", f"deck line {i}: a closing keyword", "deck", "(deck)"))
    return bad


def g_session(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if SESSION_WORDS.search(ln):
            msg = f"line {i}: a session or meeting is claimed"
            bad.append(F("G-SESSION", msg, "spec", h2_at(t.spec, i)))
    if "no session is held here and none is claimed" not in norm_text(section(t.spec, PROTO_HEAD)):
        msg = "§12.2 does not say that no session is held"
        bad.append(F("G-SESSION", msg, "spec", spec_sec(t, PROTO_HEAD)))
    return bad


# ---------------------------------------------------------------------------- pins (G-RULED-PIN)


def unvalued(line: str, values: Values) -> str:
    out = line
    for key, val, _pos in anchored(line):
        if val and val == values.get(key, val):
            out = out.replace(f"{val}<!--={key}-->", f"<!--={key}-->", 1)
    return out


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
        indent = "i" if raw.startswith((" ", "\t")) else ""
        if not ln.strip():
            shape += "."
        elif is_rule(ln):
            shape += "r"
            rule = pin_norm(re.sub(r"-+", "-", ln))
            out.append(("spec", region, f"rule {shape.count('r')}", rule))
        elif re.match(r"^ {0,3}\|", ln):
            shape += indent + "t"
            rid = pin_norm(split_row(ln)[0])[:60] or "(blank)"
            seen[rid] = seen.get(rid, 0) + 1
            loc = f"row {rid}" + (f"#{seen[rid]}" if seen[rid] > 1 else "")
            out.append(("spec", region, loc, " | ".join(pin_norm(c) for c in split_row(ln))))
        else:
            sents = [x for x in FULL_STOP.split(ln.strip()) if x.strip()]
            shape += f"{indent}{line_form(ln)}{len(sents)}"
            for s in sents:
                k += 1
                out.append(("spec", region, f"s{k}", pin_norm(s)))
    out.append(("spec", region, "shape", shape))
    return out


def deck_units(deck: str) -> list[Unit]:
    data = deck_data(deck)
    meta = {k: v for k, v in data.items() if k != "strings"}
    out: list[Unit] = [
        ("deck", "(meta)#1", "meta", json.dumps(meta, ensure_ascii=False, sort_keys=True))
    ]
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
        "# E22-D05 pins (every unit of the pack and every deck entry): doc, region (heading path"
        f" #occurrence), location, the exact normalised text; {len(units)} units.\n# Written by "
        "`--repin-ruled` only; `--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in units)


def sec_of_region(spec: str, region: str) -> str:
    parts = region.rsplit("#", 1)[0].split(" > ")
    heads = [
        pin_norm(m[2]) for ln in spec.split("\n") if (m := HEADING.match(ln)) and len(m[1]) == 2
    ]
    return next((p for p in parts if p in heads), "(top)")


def pin_findings(t: Texts) -> list[Finding]:
    path = ROOT / PIN_REL
    if not path.exists():
        return [F("G-RULED-PIN", f"{PIN_REL} is missing: run --repin-ruled", None, None)]
    text = path.read_text(encoding="utf-8")
    m = re.search(r"; (\d+) units\.", text.split("\n", 1)[0])
    pinned = parse_pins(text)
    bad: list[Finding] = []
    if not m or int(m[1]) != len(pinned):
        msg = "the pins header count does not match the parsed units"
        bad.append(F("G-RULED-PIN", msg, None, None))
    if PIN_UNITS_OVERRIDE:
        pinned = PIN_UNITS_OVERRIDE[-1]
    current = set(ruled_units(t.spec, t.deck, t.values))
    pinned_set = set(pinned)
    for what, units in (
        ("not pinned (changed or new)", current - pinned_set),
        ("pinned unit gone", pinned_set - current),
    ):
        for doc, region, loc, _text in sorted(units):
            sec = sec_of_region(t.spec, region) if doc == "spec" else "(deck)"
            bad.append(F("G-RULED-PIN", f"{doc} {region[:40]} {loc[:30]}: {what}", doc, sec))
    return bad


# ---------------------------------------------------------------------------- audit

MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_version,
    g_quote,
    g_copy,
    g_index,
    g_redline,
    g_themes,
    g_deck,
    g_storybook,
    g_keys,
    g_budget,
    g_ahead,
    g_openrows,
    g_untouched,
    g_walk,
    g_png,
    g_status,
    g_ruled,
    g_hex,
    g_penpot,
    g_names,
    g_close,
    g_words,
    g_session,
)
GATE_NAMES = (
    "G-ANCHOR",
    "G-HASH",
    "G-MARKER",
    "G-CITE",
    "G-VERSION",
    "G-QUOTE",
    "G-COPY",
    "G-INDEX",
    "G-REDLINE",
    "G-THEMES",
    "G-DECK",
    "G-STORYBOOK",
    "G-KEYS",
    "G-BUDGET",
    "G-AHEAD",
    "G-OPENROWS",
    "G-UNTOUCHED",
    "G-WALK",
    "G-PNG",
    "G-STATUS",
    "G-RULED",
    "G-HEX",
    "G-PENPOT",
    "G-NAMES",
    "G-CLOSE",
    "G-WORDS",
    "G-SESSION",
    "G-RULED-PIN",
)


def audit(t: Texts) -> tuple[list[str], list[str], int]:
    """(FAIL lines, WARN lines, cites checked). One FAIL line per gate; a pin finding in a
    section another gate already FAILs is demoted to a WARN line."""
    found: list[Finding] = []
    found += g_anchor_doc(t.spec, t.values)
    found += g_marker_doc(t.spec)
    cf, n = cite_findings(t)
    found += cf
    for gate in MEASURED_GATES:
        found += gate(t)
    flagged = {(f[2], f[3]) for f in found if f[2] is not None}
    pins = pin_findings(t)
    warns = [f"WARN [G-RULED-PIN] {p[1][:150]}" for p in pins if (p[2], p[3]) in flagged]
    found += [p for p in pins if (p[2], p[3]) not in flagged]
    merged: dict[str, list[str]] = {}
    for tag, msg, _d, _s in found:
        merged.setdefault(tag, []).append(msg)
    fails = []
    for tag, msgs in merged.items():
        msgs = list(dict.fromkeys(msgs))
        more = f" (+{len(msgs) - 4} more)" if len(msgs) > 4 else ""
        fails.append(f"[{tag}] " + "; ".join(m[:150] for m in msgs[:4]) + more)
    return fails, warns, n


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


def sub(old: str, new: str) -> Edit:
    def edit(text: str) -> str:
        return text.replace(old, new, 1) if old in text else text

    return edit


def cell_set(prefix: str, col: int, new: str) -> Edit:
    """Rewrite cell `col` (0-based) of the first table row whose lead cell starts with `prefix`."""

    def edit(text: str) -> str:
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            cells = split_row(ln) if ln.startswith("|") else []
            if cells and cells[0].startswith(prefix) and col < len(cells):
                cells[col] = new
                lines[i] = "| " + " | ".join(cells) + " |"
                return "\n".join(lines)
        return text

    return edit


def deck_edit(fn: Callable[[dict[str, dict[str, object]]], None]) -> Edit:
    def edit(deck: str) -> str:
        data = json.loads(deck)
        fn(data["strings"])
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    return edit


def deck_field(key: str, fld: str, value: str) -> Edit:
    def fn(s: dict[str, dict[str, object]]) -> None:
        s[key][fld] = value

    return deck_edit(fn)


def deck_text(key: str, text: str) -> Edit:
    def fn(s: dict[str, dict[str, object]]) -> None:
        s[key]["text"] = text
        s[key]["strings"] = QUOTED.findall(text)

    return deck_edit(fn)


def popper(lst: list[_T]) -> Callable[[], None]:
    def undo() -> None:
        lst.pop()

    return undo


def lever_extra_path() -> Callable[[], None]:
    EXTRA_PATHS.append("docs/plan/22-api-openapi.yaml")
    return popper(EXTRA_PATHS)


def lever_head_edit() -> Callable[[], None]:
    rel = CITE_FILES["D02"]
    text = (git_show(BASE, rel) or "").split("\n")
    text[211] = text[211] + " (edited)"
    HEAD_OVERRIDE.append((rel, "\n".join(text)))
    return popper(HEAD_OVERRIDE)


def lever_png_missing() -> Callable[[], None]:
    IMG_OVERRIDE.append(frozenset(n for n in img_names() if "-04-tape-states-hifi.png" not in n))
    return popper(IMG_OVERRIDE)


def lever_strict_walk() -> Callable[[], None]:
    STRICT_WALK.append(True)
    return popper(STRICT_WALK)


def hash_mutation() -> Edit:
    def edit(text: str) -> str:
        return re.sub(r"[0-9a-f]{12}(<!--=HASH:d04s8-->)", r"0a0b0c0d0e0f\1", text, count=1)

    return edit


def word_mutation() -> Edit:
    word = banned_words()[1]
    return sub("No new page and no boards", f"No new page, nothing {word}, and no boards")


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1",
        "G-ANCHOR",
        "a count anchor drifts",
        spec=sub("39<!--=COUNT:deck-->", "40<!--=COUNT:deck-->"),
    ),
    Mutation("M-2", "G-HASH", "a lifted block's hash drifts", spec=hash_mutation()),
    Mutation(
        "M-3",
        "G-MARKER",
        "a stray HTML comment",
        spec=sub("## 7. Analytics", "## 7. Analytics <!-- x -->"),
    ),
    Mutation(
        "M-4",
        "G-CITE",
        "a cite past the end of its file",
        spec=sub("README:11–14", "README:11–99999"),
    ),
    Mutation("M-5", "G-VERSION", "a cited D02 line edited at origin/main", lever=lever_head_edit),
    Mutation(
        "M-6",
        "G-QUOTE",
        "a quote no source holds",
        spec=sub("No event catalogue, schema", 'No "catalogue of tape events here", schema'),
    ),
    Mutation(
        "M-7",
        "G-COPY",
        "one byte of a copied D04 block",
        spec=sub("Off by default. Its home", "Off by default.  Its home"),
    ),
    Mutation(
        "M-8",
        "G-INDEX",
        "an id dropped from a hash-lift index",
        spec=sub(", FP-11, FP-12", ", FP-11"),
    ),
    Mutation(
        "M-9",
        "G-REDLINE",
        "a comfortable px value off its D02 line",
        spec=cell_set("Header row", 2, "46 px"),
    ),
    Mutation(
        "M-10",
        "G-THEMES",
        "a Themes cell not the tool's",
        spec=cell_set("Status row", 4, "dark · light"),
    ),
    Mutation(
        "M-11", "G-DECK", "a D02 deck row reworded", deck=deck_text("d02.13.cp01", '"Tape ETHUSDT"')
    ),
    Mutation(
        "M-12",
        "G-STORYBOOK",
        "a CMP-112 story renamed",
        spec=sub("Greyscale, ReducedMotionIdentical", "Greyscale, ReducedMotionSame"),
    ),
    Mutation(
        "M-13",
        "G-KEYS",
        "a settings key renamed",
        spec=sub("| `bigtrade.threshold_value` ", "| `bigtrade.threshold_val` "),
    ),
    Mutation(
        "M-14",
        "G-BUDGET",
        "a budget row cites the wrong line",
        spec=sub("| `26`:237 ", "| `26`:236 "),
    ),
    Mutation(
        "M-15",
        "G-AHEAD",
        "a consumer's sprint off the ticket JSON",
        spec=cell_set("E22-S03 (#716)", 1, "13"),
    ),
    Mutation(
        "M-16",
        "G-OPENROWS",
        "a parent row dropped from the log",
        spec=sub("| F-01–F-08 ", "| F-01–F-07 "),
    ),
    Mutation("M-17", "G-UNTOUCHED", "a contract file changed", lever=lever_extra_path),
    Mutation(
        "M-18",
        "G-WALK",
        "a NOT FOUND need left without an answer",
        spec=cell_set("T4", 4, "—"),
    ),
    Mutation("M-19", "G-PNG", "a board's PNG missing", lever=lever_png_missing),
    Mutation(
        "M-20",
        "G-RULED",
        "the header's stamp altered",
        spec=sub("6531540637's answer); the PR", "6531540637); the PR"),
    ),
    Mutation(
        "M-21",
        "G-HEX",
        "a colour literal",
        spec=sub(
            "This file carries no colour literal",
            "This file carries no colour literal like #1A2B3C",
        ),
    ),
    Mutation(
        "M-22",
        "G-PENPOT",
        "a page id spelled out",
        spec=sub(
            "`E22-D03 BigTrade hi-fi` (D03:36)",
            "`E22-D03 BigTrade hi-fi` (12345678-aaaa-bbbb-cccc-1234567890ab)",
        ),
    ),
    Mutation(
        "M-23",
        "G-NAMES",
        "an agent name",
        spec=sub(
            "The outside read is the orchestrator's deputy's", "The outside read is Agent Q's"
        ),
    ),
    Mutation(
        "M-24",
        "G-CLOSE",
        "a closing keyword in a body section",
        spec=sub("Nothing is emitted until", "Fixes #578. Nothing is emitted until"),
    ),
    Mutation("M-25", "G-WORDS", "a banned word", spec=word_mutation()),
    Mutation(
        "M-26",
        "G-SESSION",
        "a session claimed",
        spec=sub(
            "Each consumer's acknowledgement is",
            "A session was held with the FE lead. Each consumer's acknowledgement is",
        ),
    ),
    Mutation(
        "M-28",
        "G-REDLINE",
        "lens m1: header 32 / 44 swapped",
        spec=cell_set("Header row", 1, "44 px"),
    ),
    Mutation(
        "M-29",
        "G-THEMES",
        "lens m2: header tokens from another row",
        spec=cell_set(
            "Header row",
            3,
            "`color.surface.raised`, `color.text.tertiary`, `color.border.strong`",
        ),
    ),
    Mutation(
        "M-30",
        "G-STORYBOOK",
        "lens m3: a state's deck row off its D02 string",
        spec=cell_set("St08 StaleT1", 2, "`d02.13.cp01`"),
    ),
    Mutation(
        "M-31",
        "G-THEMES",
        "lens m4: a board that does not draw the row",
        spec=cell_set("Row, tiers", 5, "09"),
    ),
    Mutation(
        "M-32",
        "G-STATUS",
        "lens m5: an unbuilt surface called built",
        spec=cell_set("SCR-053 tape panel", 3, "built"),
    ),
    Mutation(
        "M-33",
        "G-REDLINE",
        "lens m6: the log's comfortable rows",
        spec=cell_set("The log at 1280", 2, "572 px, 37 rows"),
    ),
    Mutation(
        "M-34",
        "G-OPENROWS",
        "lens m7: a story's own C-row dropped from its binding",
        spec=sub("| D05-C-3 (2 000 on the subscription path); ", "| "),
    ),
    Mutation(
        "M-35",
        "G-BUDGET",
        "lens m8: the two layers swapped",
        spec=sub(
            "is the engine's hard instance cap (LIM:30, `11`:2228); 500<!--=CITE:perf.lod--> is the LOD trigger",
            "is the LOD trigger (LIM:30, `11`:2228); 500<!--=CITE:perf.lod--> is the engine's hard instance cap",
        ),
    ),
    Mutation(
        "M-36",
        "G-ANCHOR",
        "lens m9: the debounce",
        spec=sub("500<!--=CITE:s02.debounce-->", "250<!--=CITE:s02.debounce-->"),
    ),
    Mutation(
        "M-37",
        "G-REDLINE",
        "lens m10: cell size and gap swapped between densities",
        spec=cell_set("Cells and gaps", 1, "13 px cells, 12 px gaps"),
    ),
    Mutation(
        "M-38",
        "G-COPY",
        "a copy-cite re-found on the wrong line",
        spec=sub("| `21`:3732 ", "| `21`:3719 "),
    ),
    Mutation(
        "M-39",
        "G-AHEAD",
        "E22-Q02 dropped from the Readers line",
        spec=sub("E22-Q02 (#752) takes", "the E2E suite takes"),
    ),
    Mutation(
        "M-40",
        "G-REDLINE",
        "a copied tier cell changed in §8.1.1",
        spec=sub("| `font.weight.medium` 500 ", "| `font.weight.medium` 600 "),
    ),
    Mutation(
        "M-41",
        "G-REDLINE",
        "an in-cell swap (positional)",
        spec=cell_set("The log at 1280", 1, "25 px, 604 rows"),
    ),
    Mutation(
        "M-42",
        "G-DECK",
        "the proposed range sentence past 60 characters",
        deck=deck_text(
            "d05.05.range",
            '"Enter a value of 0 or more; a percentile is between 0 and 100 inclusive."',
        ),
    ),
    Mutation(
        "M-43",
        "G-OPENROWS",
        "a D03 A-row dropped from the log",
        spec=sub("| A-1–A-20 ", "| A-1–A-19 "),
    ),
    Mutation(
        "M-44",
        "G-WALK",
        "a role's dry-run counts off the needs table",
        spec=cell_set("E22-S04 clustering", 2, "3"),
    ),
    Mutation(
        "M-45",
        "G-DECK",
        "the row-name template reworded",
        deck=deck_field("d02.13.cp26", "template", "side first, then the tier word, then the tags"),
    ),
    Mutation(
        "M-27",
        "G-RULED-PIN",
        "a ruled sentence edited without a re-pin",
        spec=sub("does not apply to a design pack", "does not fit a design pack"),
    ),
)


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(x.encode("utf-8")).hexdigest() for x in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def plan_paths() -> tuple[tuple[str, Path], ...]:
    return tuple((cid, ROOT / CITE_FILES[cid]) for cid in (*UNTOUCHED, "14", *UNTOUCHED_DOCS))


def read_plans() -> tuple[tuple[str, str], ...]:
    return tuple(
        (cid, p.read_text(encoding="utf-8") if p.exists() else "") for cid, p in plan_paths()
    )


def selftest(spec: str, deck: str, paths: tuple[Path, ...]) -> tuple[bool, list[str]]:
    on_disk = digest(paths)
    plans = read_plans()
    values = compute(spec, deck)
    spec_f, _ = fill(spec, values)
    values = compute(spec_f, deck)
    vt = tuple(sorted(values.items()))
    base_fails, _w, _n = audit(Texts(spec_f, deck, plans, vt))
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
            fails, _w2, _n2 = audit(Texts(s, d, plans, vt))
        finally:
            if undo:
                undo()
            if repin:
                PIN_UNITS_OVERRIDE.pop()
        new = [x for x in fails if x not in base_fails]
        named = [x for x in new if x.startswith(f"[{mu.gate}]")]
        hit = bool(named) and len(new) == 1
        levers = EXTRA_PATHS or PLAN_OVERRIDE or PIN_UNITS_OVERRIDE or HEAD_OVERRIDE
        restored = (
            digest_texts(spec_f, deck) == pristine
            and digest(paths) == on_disk
            and not (levers or IMG_OVERRIDE or STRICT_WALK)
        )
        ok = ok and hit and restored
        first = (named or new or ["nothing new"])[0]
        state = ("ok" if hit else "MISSED") + ("" if restored else ", NOT RESTORED")
        lines.append(f"  {mu.mid} [{mu.gate}] {state} ({len(new)} new) - {first}")
        if not hit:
            lines += [f"      new: {x}" for x in new]
    gates = {mu.gate for mu in MUTATIONS}
    missing = [g for g in GATE_NAMES if g not in gates]
    if missing:
        ok = False
        lines.append(f"  gates with no mutation: {', '.join(missing)}")
    return ok, [report(x) for x in lines]


# ---------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="E22-D05 hand-off pack audit (module docstring)")
    ap.add_argument("--check", nargs="?", const=SPEC_REL, default=None, metavar="SPEC")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="replace placeholders, then check")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="apply every mutation")
    ap.add_argument("--repin-ruled", action="store_true", help=f"rewrite {PIN_REL}")
    ap.add_argument("--strict-walk", action="store_true", help="a pending dry-run row FAILs")
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
    fails, warns, n = audit(t)
    if args.json:
        out = {"values": values, "fails": fails, "warns": warns, "cites": n}
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        shown = spec_path.relative_to(ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        print(f"## E22-D05 audit of {shown} (+ the deck) at base {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {len(GATE_NAMES)}")
        print("\n".join(report(w) for w in warns))
        print("\n".join(report(f"FAIL {x}") for x in fails) or "OK - every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
