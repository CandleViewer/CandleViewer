#!/usr/bin/env python3
"""E36-D05 (#947) audit: the rule-form-editor engineering hand-off pack (spec + hand-off).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base `927794a8ba` (`git show`): the token JSON (`themes.json` layering:
dark = primitives + semantic-dark, light = + semantic-light, hc = + semantic-hc), the plan texts
`02`, `05`, `14`, `15`, `16`, `20`, `22`, `23`, the backlog JSON `E36.json` and the calendar
`calendar_cv.py`, the merged E36 design docs (D02, D02H, D03, D03H, D04) and the other merged
docs the spec cites; then this ticket's spec, hand-off and copy-deck JSON from the working tree,
and the working-tree files the pack must not edit (which must equal the fork point).

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: PX and OPACITY (a size,
   space, border or opacity token resolved through `themes.json`, equal in the three themes),
   HEX (a colour token in dark / light / hc), CONTRAST (WCAG 2.x, truncated to two decimals), CITE
   (a number parsed from the cited line: a typed dimension, a budget, a cadence), COUNT (boards,
   frames, deck rows and strings, frozen strings, motion rows, F-rows, AL rows, log rows and ids,
   parsed from the base docs and the spec's own tables), HASH (sha256 prefix of D04 §16's forty
   rows at the base) and DATE (a sprint start from `calendar_cv.py` and `E36.json`). `--fill`
   writes `VALUE<!--=KIND:key-->` and the copy-deck JSON; `--check` re-derives every anchored value
   and FAILs on a difference, a `{{` left outside a code span, a hand-typed figure with a unit, a
   hand-typed count before a counted noun, or a hand-typed hex.
2. **The comment strip.** One pattern over the whole text, `re.DOTALL`: `<!--` closes at `-->` or
   `--!>`, `<!-->` and `<!--->` close at once, and an unclosed comment runs to the end. Every
   comment must be a value anchor the tool computes (G-MARKER); the lexicon gates read rendered
   text only.
3. **Cites.** Every `NN`:line and `D02`/`D02H`/`D03`/`D03H`/`D04`/`CAL`/`CONST`/`AGENTS`/`README`/
   `E10H`/`E29H`/`Exx-Dyy`:line cite is read at the base (FAIL when the line is gone or blank; WARN
   when it drifted at `origin/main`); the load-bearing fragments of CITED must sit on their lines.
4. **Gates.** Lexicon gates first (each reads table cells and prose after the comment strip, NFKC,
   markup dropped, dashes to spaces and lower case; a claim is read per clause; a negation covers
   its own term within five words and a list coordinated after it; quoted copy, §20's mutation rows
   and the hand-off's Old cells are not claims; a ruled behaviour has a synonym set where one
   reaches, and its ruled sentence is REQUIRED verbatim in its section, so a paraphrase that
   replaces it FAILs a gate even after a repin; the pins catch the rest), then the measured gates
   (the frame register column by column, the redlines, the mapping, the copy deck byte by byte at
   its source lines, the frozen strings, the contrast pairs, the contract operations, the F-row
   ledger, the AL list against D04 at the base, the log's union, the consumers, the version line,
   the props and the stories against `15`, the A-rows, the Gherkin trace against `E36.json`, the
   cell count of every table row (G-CELLS), the heading levels (G-HEADS), G-UNTOUCHED against `git
   merge-base HEAD origin/main` (`14` may differ only by A-1 … A-5's five pointer lines), G-BASE (a
   branch with commits must contain BASE) and G-VERSION's drift check: the last commit of every
   version-line input and D04 §16's hash at `origin/main` must equal the base's (FAIL, BQ-33)),
   then the pins. Each gate reports one FAIL line.
5. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over EVERY unit of both docs, in
   RULED_PIN_TXT (`e36_d05_ruled_pins.txt`): each heading, table row (by its lead cell), rule line,
   prose sentence (`s<k>`) and fenced block, by doc, region (heading path plus occurrence `#n`),
   location and exact text (NFKC, whitespace collapsed; a table row keeps an escaped `\\|`, so a
   merged cell never pins as the two it replaced). Anchored values are pinned with their
   values cut out (G-ANCHOR re-derives them). Each region pins its line shape (line-shape tags: `.`
   blank, `h` heading, `t` row, `r` rule, `b` bullet, `n` numbered item, `p` prose, `f` fence; a
   prose, bullet or numbered tag carries its sentence count, the line-form tag; `>n` an n-column
   indent). A unit changed, moved, duplicated, deleted or added FAILs by location. `--repin-ruled`
   is the only writer (it refuses while a placeholder is unfilled); `--check` writes nothing. Pins
   fold NFKC, so G-CHARSET FAILs any compatibility character but `…` (quoted merged copy), any
   format character (a soft hyphen), any letter outside the Latin script (a homoglyph), a space
   before a full stop or comma, any CR and any trailing whitespace. NOTE demotion: when a lexicon
   or measured gate already FAILs a section, that section's pin findings print as NOTE lines, so
   one wrong form yields one FAIL.
6. **--self-test** (alias `--selftest`) applies every §20 mutation M-n in memory, plus the tool's
   own P-n (one per pin class), with the values frozen at the filled baseline; each must add
   exactly one FAIL, from the gate it names, and every text is restored byte-identically (sha256
   in memory and on disk). Output is ASCII plus UTF-8 on a reconfigured stream.

Usage (from the repo root):
  python3 -I docs/design/_tools/e36_d05_handoff_audit.py --check [SPEC] [--handoff F] [--json]
      [--fill]
  python3 -I docs/design/_tools/e36_d05_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e36_d05_handoff_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import functools
import hashlib
import json
import math
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "927794a8ba"  # every cite was read here (the spec's Inputs line: #4762's merge)
HEAD = "origin/main"  # drift: a cited line WARNs; a version-line input or the AL hash FAILs
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E36/E36-D05.md"
HAND_REL = "docs/design/E36/E36-D05-handoff.md"
DECK_REL = "docs/design/E36/E36-D05-copy-deck.json"
TOOL_REL = "docs/design/_tools/e36_d05_handoff_audit.py"
RULED_PIN_TXT = "docs/design/_tools/e36_d05_ruled_pins.txt"
DS_SRC_REL = "packages/ui/tokens"
TICKETS_REL = "docs/plan/backlog/E36.json"
UNTOUCHED = ("05", "06", "14", "15", "16", "22", "23")  # R-2 (`14`: only A-1 … A-5's lines)
POINTER_PLAN = "14"  # BQ-3: this PR adds its five pointer lines, nothing else
UNTOUCHED_DOCS = ("D02", "D02H", "D03", "D03H", "D04", "MEMO", "KM", "RK")
OWN_PATHS = (SPEC_REL, HAND_REL, DECK_REL, TOOL_REL, RULED_PIN_TXT)
CITE_FILES: dict[str, str] = {
    "D02": "docs/design/E36/E36-D02.md",
    "D02H": "docs/design/E36/E36-D02-handoff.md",
    "D03": "docs/design/E36/E36-D03.md",
    "D03H": "docs/design/E36/E36-D03-handoff.md",
    "D04": "docs/design/E36/E36-D04.md",
    "MEMO": "docs/design/research/e36-rules-in-words.md",
    "KM": "apps/web/src/keymap/keymap.json",
    "RK": "apps/web/src/keymap/reserved-keys.json",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "CONST": "CONSTITUTION.md",
    "AGENTS": "AGENTS.md",
    "README": "docs/design/README.md",
    "E10H": "docs/design/E10/E10-D04-handoff.md",
    "E29H": "docs/design/E29/E29-D04-handoff.md",
}
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SEMANTIC = ("semantic-dark", "semantic-light", "semantic-hc")

# ---- the ruling and the fixed facts
RULING_ID = "6439245637"
BQ_LIST_ID = "6439029896"
D04_RULING_ID = "6364610731"  # E36-D04's ruling, cited by the locked-inputs table
RULED_IDS = (RULING_ID, BQ_LIST_ID, D04_RULING_ID)  # the allow-list: every comment id cited
OWNER_PENDING = "owner approval pending (#2701)"
FREEZE = "freeze PROPOSED, owner approval pending (#2701)"
PENDING_STATUS = "PENDING (text-first; E36-D02 #873 boards)"
DRAWN_STATUS = "drawn (D03 #4337)"
SPEC_LINE_BUDGET = 600  # standing condition: "about 600 lines"
HAND_LINE_BUDGET = 150  # standing condition: "about 150 lines"
SCREENS = ("SCR-080", "SCR-081", "SCR-083", "SCR-088", "SCR-089")
PENDING_SCREENS = ("SCR-081", "SCR-083")  # BQ-6: D02's boards are not drawn
# the consumers the ticket and the ruling name, with their issues (`gh`, verified at the claim)
ISSUES: dict[str, str] = {
    "E36-T01": "1063",
    "E36-S01": "1057",
    "E36-S02": "1058",
    "E36-S03": "1059",
    "E36-S04": "1060",
    "E36-S05": "1061",
    "E36-S06": "1062",
    "E36-Q01": "1053",
    "E36-Q03": "1055",
    "E36-Q04": "1056",
    "E36-D06": "1052",
    "E36-X01": "948",
    "E36-T02": "1064",
}
CONSUMERS = (
    "E36-T01",
    "E36-S01",
    "E36-S02",
    "E36-S03",
    "E36-S04",
    "E36-S05",
    "E36-S06",
    "E36-Q01",
    "E36-Q03",
    "E36-Q04",
    "E36-D06",
    "E36-X01",
)
CONTRACT_CMPS = (
    "CMP-140",
    "CMP-141",
    "CMP-142",
    "CMP-143",
    "CMP-144",
    "CMP-145",
    "CMP-155",
    "CMP-157",
    "CMP-158",
    "CMP-159",
    "CMP-233",
    "CMP-234",
    "CMP-235",
)
NEW_CMPS = {"CMP-240": ("A-6", 2807), "CMP-243": ("A-11", 2825)}  # BQ-9: catalogued by #4735
TBD = "TBD (E36-D05 #947)"  # the fields `15` leaves to this pack (filled by A-6 … A-17)
OPS = (
    "listRules",
    "getRule",
    "createRule",
    "updateRule",
    "deleteRule",
    "validateRule",
    "compileRule",
    "simulateRule",
    "setRuleMode",
    "getRuleVocabulary",
    "getRuleIrSchema",
    "listRuleVersions",
    "setActiveRuleVersion",
    "listRuleAccounts",
)
# the frozen strings (BQ-17): the status each string's cell must carry, beside FREEZE
FROZEN_STATUS: dict[str, str] = {
    "FS-1": "string merged",
    "FS-2": "string PROPOSED",
    "FS-3": "string RULED (#4137)",
    "FS-4": "string RULED (memo Q2)",
    "FS-5": "string RULED (D02 BQ-4)",
    "FS-6": "string PROPOSED",
    "FS-7": "string RULED (D02 BQ-4)",
    "FS-8": "string PROPOSED",
    "FS-9": "string PROPOSED",
}
ROUTED_F = ("F-01", "F-02", "F-13", "F-17")  # BQ-25: routed elsewhere, cited only
LIST_F = ("F-06", "F-09", "F-10", "F-11", "F-15")  # SCR-080's F-rows: E36-S02 and E36-S05 (D05-C10)
STORIES = ("E36-T01", "E36-S01", "E36-S02", "E36-S03", "E36-S04", "E36-S05", "E36-S06")
ANNOUNCE = ("polite", "assertive", "none")
# BQ-16 / BQ-26 / F-04 / F-05: the marks the names and live-data tables fix
ANNOUNCE_FIXED = {
    "rules.editor.roundtrip.mismatch": "assertive",
    "rules.editor.roundtrip.checking": "none",
    "rules.list.banner.engine_down": "assertive",
    "rules.editor.banner.engine_down": "assertive",
    "rules.editor.banner.estimated": "polite",
    "rules.editor.stop.kept": "polite",
    "rules.list.bulk.count": "polite",
    "rules.ir.copy.copied": "polite",
    "rules.io.import.checked": "polite",
    "rules.io.import.progress": "polite",
    "rbac.view_as": "polite",
}
# D03:155: each SCR-089 reason is a server answer or a client prediction
IO_CHECK = {
    "account": "client",
    "metric": "server",
    "action": "server",
    "format": "client",
    "name": "client",
    "prefix": "client",
    "budget": "client",
    "accepted": "client",
    "too_large": "server",
    "not_checked": "server",
    "predicted": "client",
    "field": "server",
}
# BQ-16: the arm refusals D02:188 lists (`arming.py` 58-126), by status
ARM_GATES = {
    "draft (a Manager)": "T2 (state)",
    "valid": "T1",
    "invalid": "validity (R-4)",
    "armed": "\u2014",
    "engine down or vocabulary unavailable": "T2 (state)",
    "viewing as another user": "T2 (session)",
    "live step-up missing": "T1",
    "refusal at the point of action": "T4",
}
MOTION_CONFLICTS = {"2": "D05-C5a", "7": "D05-C5b", "10": "D05-C5c", "13": "D05-C5d"}
A_ROW_LINES = {"A-1": 1798, "A-2": 1844, "A-3": 1898, "A-4": 1990, "A-5": 2003}  # BQ-3: `14`
TBD_SPAN = (2804, 2837)  # CMP-240 and CMP-243 in `15` at the base
A18_LINE = 2812  # CMP-240's Storybook line in `15`: A-18 adds SCR-088's two stories
PROPOSED_TOKENS = ("space.rulegroup.indent",)
KINDS = (
    "label",
    "word",
    "reason",
    "banner",
    "confirm",
    "validation",
    "announce",
    "name",
    "tooltip",
)
DECK_NS = {
    "6.1": ("rules.list.", "rbac.", "rule.", "engine."),
    "6.2": ("rules.editor.",),
    "6.3": ("rules.templates.",),
    "6.4": ("rules.ir.",),
    "6.5": ("rules.io.",),
    "6.6": ("rbac.", "rule."),
}
DECK_SCREEN = {
    "6.1": "SCR-080",
    "6.2": "SCR-081",
    "6.3": "SCR-083",
    "6.4": "SCR-088",
    "6.5": "SCR-089",
    "6.6": "shared",
}
CHARSET_ALLOW = frozenset("…")  # quoted merged copy ("Arm…", "Checking…") keeps its ellipsis
# numbers parsed from the cited lines: key -> (cite id, line, pattern with one group)
CITE_NUMS: dict[str, tuple[str, int, str]] = {
    "d03.header": ("D03", 101, r"Header (\d+) px"),
    "d03.banner.compact": ("D03", 109, r"\((\d+) px compact"),
    "d03.banner.comfortable": ("D03", 109, r"/ (\d+) px comfortable"),
    "d02.column": ("D02", 86, r"column of (\d+) px"),
    "d02.label": ("D02", 91, r"label column (\d+) px"),
    "d02.bar": ("D02", 97, r"\| (\d+) px, `color\.surface\.raised`"),
    "d02.dialog": ("D02", 192, r"`size: lg`, (\d+) px"),
    "d03.drawer": ("D03", 135, r"\*\*(\d+) px wide\*\*"),
    "d03.drawer.narrow": ("D03", 135, r"; (\d+) px narrow mode"),
    "d03.dialog": ("D03", 151, r"`size: lg`, (\d+) px"),
    "d03.zoom": ("D03", 131, r"At (\d+) % the eight columns"),
    "d04.cadence": ("D04", 531, r"≤ 1 per (\d+) s"),
    "14.validate": ("14", 1838, r"validation round-trip ≤(\d+) ms"),
    "14.compile": ("14", 1838, r"within ≤(\d+) ms p95"),
    "14.nodes": ("14", 1838, r"for a (\d+)-node rule"),
    "14.rows": ("14", 1796, r"(\d+) rules render"),
    "14.frame": ("14", 1796, r"exceeding (\d+) ms"),
    "14.template": ("14", 1894, r"<=(\d+) ms"),
    "14.bundle": ("14", 1998, r"a (\d+)-rule bundle"),
    "14.import": ("14", 1998, r"in <=(\d+) s"),
    "23.rules": ("23", 831, r"\| (\d+) ms +\|"),
    "d03.reads": ("D03", 346, r"≤(\d+) reads in flight"),
    "d02.debounce": ("D02", 367, r"debounced (\d+) ms"),
}
# load-bearing fragments: (cite id, line, fragment that must sit on the line at the base)
CITED: tuple[tuple[str, int, str], ...] = (
    ("20", 719, "rule-graph/"),
    ("D03", 44, "5c7e632f-bdb1-809b-8008-d5d82d687aba"),
    ("D04", 29, "80bd2332-4271-80a7-8008-d5ea83539704"),
    ("15", 2804, "### CMP-240 TreeView"),
    ("15", 2822, "### CMP-243 BulkActionBar"),
    ("E13-D02", 369, "CMP-240 TreeView"),
    ("E13-D02", 372, "CMP-243 BulkActionBar"),
    ("05", 148, "assertive"),
    ("16", 138, "data-motion"),
    ("16", 342, "never a hex/px literal"),
    ("02", 52, "Status=Done"),
    ("CONST", 378, "C-4.4"),
    ("CONST", 495, "C-6.1"),
    ("CONST", 1111, "C-16.5"),
    ("AGENTS", 544, "accessibility tree"),
    ("D04", 723, "E36-D05 (the handoff pack)"),
    ("D02", 4, "BLOCKED-PENPOT"),
    ("22", 16892, "RuleMode"),
    ("22", 20032, "RuleValidationIssue"),
    ("15", 1674, "must type the rule name"),
    ("D03", 168, "the typed confirm is SCR-085"),
    ("15", 470, "the card appears at once"),
    ("15", 500, "a docked drawer that reflows its host arrives in one frame"),
    ("14", 85, "RBAC denies server-side"),
    ("D03H", 65, "D02's blocks point here"),
    ("E10-D04", 85, "R-3 Instant under reduce"),
    ("E10-D04", 90, "R-8 One source"),
    ("E11-D09", 948, "no session"),
    ("D04", 629, "1:1"),
    ("D02", 367, "Validation debounced"),
    ("README", 78, "<ticket>.md"),
    ("05", 5, "single source of truth for accessibility acceptance criteria"),
    ("22", 16155, "RuleIrInvalid:"),
    ("22", 16295, "ServiceUnavailable:"),
    ("22", 7781, "RuleIrInvalid"),
    ("22", 7842, "RuleIrInvalid"),
    ("22", 13547, "RuleIrInvalid"),
    ("22", 7840, '"412"'),
    ("22", 7821, "If-Match"),
    ("22", 7813, "/active-version"),
    ("D02", 209, "403 view_as_read_only"),
    ("D02", 438, "D02-Q12"),
    ("D02", 188, "acknowledgement_required"),
    ("D03", 155, "each tagged **server** or **client**"),
    ("D03", 214, "**Announcements:**"),
    ("D03", 127, "body: the three names"),
    ("D02", 258, "**Announcement policy**"),
)

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z0-9]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
FIGURE = re.compile(
    r"(?<![\w.,:#/>{-])(\d+(?:[.,]\d+)*)\s?(ms|s|hz|px|%|:1)(?![\w])", re.IGNORECASE
)
# a count typed by hand before a counted noun (the spec writes counts as COUNT anchors)
COUNTED = re.compile(
    r"(?<![\w.,:#/>{§-])(\d+)\s(rows?|strings?|frames?|boards?|states?|questions?|ids|"
    r"consumers?|keys?|entries|items|lines|words|chords|templates|components|mutations|pairs)\b",
    re.IGNORECASE,
)
CITE_GROUP = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:D0[234]H?|CAL|CONST|AGENTS|README|E10H|E29H"
    r"|E\d\d-D\d\d)\b)) ?"
    r":(?P<first>\d+(?:[\u2013-]\d+)?)(?P<more>(?:(?:\s*\([^()\n]*\))?,\s*:\d+(?:[\u2013-]\d+)?)*)"
)
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]|/home/|\\\\|file://", re.IGNORECASE)
COMMENT_ID = re.compile(r"(?<![\w-])(\d{8,})(?![\w-])")

Values = dict[str, str]
Fetch = Callable[[str, str], str | None]
# a gate finding: (gate tag, message, doc, section); doc / section None for a repo-level finding
Finding = tuple[str, str, str | None, str | None]

# ---------------------------------------------------------------------------- reading


@functools.lru_cache(maxsize=256)
def git_show(rev: str, rel: str) -> str | None:
    """The file at `rev`, or None when it does not exist there (never raises)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8") if out.returncode == 0 else None


def git_out(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.decode("utf-8") if out.returncode == 0 else ""


def git_fetch(rev: str, rel: str) -> str | None:
    return git_show(rev, rel)


def at_base(rel: str) -> str:
    text = git_show(BASE, rel)
    if text is None:
        raise SystemExit(f"FAIL parse: {rel} is not readable at {BASE}")
    return text


@functools.lru_cache(maxsize=1)
def plan_listing() -> str:
    return git_out("ls-tree", "--name-only", BASE, "docs/plan/")


def plan_rel(nn: str) -> str | None:
    names = [n for n in plan_listing().split("\n") if n.startswith(f"docs/plan/{nn}-")]
    return min(names) if names else None


def plan(nn: str) -> str:
    rel = plan_rel(nn)
    if rel is None:
        raise SystemExit(f"FAIL parse: docs/plan/{nn}-* missing at {BASE}")
    return at_base(rel)


def base_line(cid: str, n: int) -> str:
    rel = cite_path(cid)
    lines = at_base(rel).split("\n") if rel else []
    if not 1 <= n <= len(lines):
        raise SystemExit(f"FAIL parse: {cid}:{n} is not a line at {BASE}")
    return lines[n - 1]


def cite_path(cid: str) -> str | None:
    if re.fullmatch(r"\d{2}", cid):
        return plan_rel(cid)
    if cid in CITE_FILES:
        return CITE_FILES[cid]
    m = re.fullmatch(r"(E\d{2})-D\d{2}", cid)
    if m:
        return f"docs/design/{m[1]}/{cid}.md"
    if "/" in cid:
        return cid
    return None


@functools.lru_cache(maxsize=8)
def tree_at_base(prefix: str) -> tuple[str, ...]:
    return tuple(n for n in git_out("ls-tree", "--name-only", BASE, prefix).split("\n") if n)


# ---------------------------------------------------------------------------- the comment strip

# ONE pattern over the whole text, DOTALL. `<!-->` and `<!--->` close at once, a comment closes
# at `-->` or `--!>`, and an unclosed comment runs to the end of the text.
COMMENT = re.compile(r"<!--(?:>|->|.*?--!?>|.*\Z)", re.DOTALL)
_HIDDEN = re.compile(COMMENT.pattern + r"|[\u00ad\u200b-\u200d\u2060\ufeff]", re.DOTALL)


def strip_comments(text: str) -> str:
    return _HIDDEN.sub("", text)


# ---------------------------------------------------------------------------- markdown

FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def fenced(lines: list[str]) -> list[bool]:
    """For each line, whether it is a fence line or inside a fenced block (kind and length read
    from the marker after the indent; an unclosed fence runs to the end)."""
    out: list[bool] = []
    open_m: str | None = None
    for ln in lines:
        m = FENCE_OPEN.match(ln)
        if open_m is None:
            if m:
                open_m = m[1]
            out.append(open_m is not None)
            continue
        out.append(True)
        if m and m[1][0] == open_m[0] and len(m[1]) >= len(open_m) and not ln[m.end() :].strip():
            open_m = None
    return out


HEADING = re.compile(r"^(#{1,6}) (.*)$")


def section(text: str, head: str) -> str:
    """From the heading starting with `head` (outside fences) to the next heading of the same or a
    higher level outside a fence."""
    lines = text.split("\n")
    fence = fenced(lines)
    start, level = -1, 0
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if m and not fence[i] and m[2].startswith(head):
            start, level = i, len(m[1])
            break
    if start < 0:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = HEADING.match(lines[j])
        if m and not fence[j] and len(m[1]) <= level:
            end = j
            break
    return "\n".join(lines[start:end])


def split_row(line: str, keep_escapes: bool = False) -> list[str]:
    body = line.strip().removeprefix("|").removesuffix("|")
    cells = [c.strip() for c in re.split(r"(?<!\\)\|", body)]
    return cells if keep_escapes else [c.replace("\\|", "|") for c in cells]


def is_rule(line: str) -> bool:
    return re.match(r"^\s*\|\s*:?-{1,}", line) is not None and set(line.strip()) <= set("|-: ")


def table_rows(block: str) -> list[list[str]]:
    """Every table row of `block` but each table's header and rule rows."""
    out: list[list[str]] = []
    lines = block.split("\n")
    for i, ln in enumerate(lines):
        if not re.match(r"^ {0,3}\|", ln) or is_rule(ln):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if is_rule(nxt):
            continue
        out.append(split_row(ln))
    return out


def row_key(cell: str) -> str:
    k = re.sub(r"[*_`]", "", cell).strip()
    return re.sub(r"^([A-Za-z]+)\s+(\d+)$", r"\1-\2", k)


def pin_norm(text: str) -> str:
    """The exact text, NFKC with whitespace collapsed (Prettier's table padding is not a change)."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sec_id(heading: str) -> str:
    """A `##` section's key: the first three words of its rendered heading (values and anchors
    dropped), the same for the lexicon units, the gates and the pin regions."""
    text = PLACEHOLDER.sub(" ", strip_comments(heading)).lstrip("# ")
    return " ".join(pin_norm(text).split()[:3]) or "(top)"


def h2_of(text: str, head: str) -> str:
    """The `##` section key of the heading that starts with `head`."""
    cur = "(top)"
    lines = text.split("\n")
    fence = fenced(lines)
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if not m or fence[i]:
            continue
        if len(m[1]) <= 2:
            cur = sec_id(m[2])
        if m[2].startswith(head):
            return cur
    return "(top)"


def h2_at(text: str, line_no: int) -> str:
    """The `##` section key of 1-based line `line_no`."""
    cur = "(top)"
    lines = text.split("\n")
    fence = fenced(lines)
    for i, ln in enumerate(lines[:line_no]):
        m = HEADING.match(ln)
        if m and not fence[i] and len(m[1]) <= 2:
            cur = sec_id(m[2])
    return cur


def line_of(text: str, needle: str) -> int:
    """The 1-based line holding `needle` (0 when absent)."""
    for i, ln in enumerate(text.split("\n"), 1):
        if needle in ln:
            return i
    return 0


# ---------------------------------------------------------------------------- normalisation

_DASHES = re.compile(r"[\u2010-\u2015\u2212-]")
_MARKUP = re.compile(r"[*`]")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EMPH = re.compile(r"(?<!\w)_+|_+(?!\w)")


def norm_text(text: str) -> str:
    """Rendered words only: comments, soft hyphens and markup dropped, NFKC, dashes to spaces,
    whitespace collapsed, lower case."""
    t = unicodedata.normalize("NFKC", strip_comments(text))
    t = _EMPH.sub(" ", _MARKUP.sub("", _LINK.sub(r"\1", t)))
    return " ".join(_DASHES.sub(" ", t).split()).lower()


def unquote(text: str) -> str:
    return QUOTED.sub(" ", text)


NEG_WORD = r"(?:no|never|not|nor|without|nothing|none|cannot)"
DOUBLE_NEG = re.compile(
    r"\b(?:never|not|no)\s+(?:\S+\s+){0,2}?without\b|\bnever not\b|\bnot never\b"
    r"|\bnot (?:only|just)\b"
    r"|\b(?:never|not|no|cannot|nothing)\s+(?:\S+\s+){0,2}?"
    r"(?:fail(?:s|ed|ing)?|lack(?:s|ed|ing)?|omit\w*|ceas\w*|stop(?:s|ped|ping)?)\b"
)
FALSITY = (
    r"(?:false|untrue|wrong|incorrect|inaccurate|mistaken|a myth"
    r"|not (?:true|the case|correct|accurate|so|right))"
)
FLIP = re.compile(
    rf"\b(?:it|this)(?: \w+){{0,2}}? (?:is|was|be|['\u2019]s) (?:\w+ )?{FALSITY}"
    r" (?:that|to (?:say|claim|state|suggest|write)(?: that)?)\b"
)


def live(clause: str, term: str, keep_quotes: bool = False) -> bool:
    """`term` asserted in `clause` once every negated mention is removed. A negation covers its
    own term (at most five words before it) and a list of its terms coordinated after it; a double
    negation or a negation chain asserts its term; a falsity frame inverts what follows it."""
    t = norm_text(clause) if keep_quotes else norm_text(unquote(clause))
    f = FLIP.search(t)
    if f:
        rest = t[f.end() :]
        return _live(t[: f.start()], term) or (
            re.search(term, rest) is not None and not _live(rest, term)
        )
    return _live(t, term)


def _live(t: str, term: str) -> bool:
    t = DOUBLE_NEG.sub(" ", t)
    sep = r"(?:,\s*(?:or\s+|nor\s+|and\s+)?|\s+(?:or|nor|and)\s+)"
    listed = rf"(?:{sep}(?:an? )?(?:{term})\w*)*"
    item = rf"(?:[^\s,;]+\s+){{0,2}}[^\s,;]+{sep}"  # one coordinated item of at most 3 words
    near_ = r"(?:\s+\S+){0,5}?\s+\W?(?:an? )?(?:[\w-]+\.)*"
    in_list = rf"(?:\s+\S+){{0,2}}?\s+(?:{item})+(?:[^\s,;]+\s+){{0,2}}?(?:[\w-]+\.)*"
    t = re.sub(rf"\b{NEG_WORD}\b(?:{near_}|{in_list})(?:{term}){listed}", " ", t)
    return re.search(term, t) is not None


SENTENCE = re.compile(r";\s|(?<=[.!?])\s+|\s—\s")


def sentences(text: str) -> list[str]:
    """The clauses of rendered `text` (the comment strip first), split at "; ", " — " and a
    sentence end, never at a comma."""
    return [c for c in SENTENCE.split(strip_comments(text)) if c.strip()]


def clauses(text: str) -> list[str]:
    """A unit's clauses; a table row is read cell by cell with its lead cell as the subject."""
    if " | " not in text:
        return sentences(text)
    cells = text.split(" | ")
    out = sentences(cells[0])
    for c in cells[1:]:
        out += [f"{cells[0]} | {x}" for x in sentences(c)]
    return out


@dataclass(frozen=True)
class LexUnit:
    doc: str  # "spec" or "hand"
    sec: str  # the `##` section (normalised heading text)
    text: str


MUTATION_HEAD = "20. The mutation list"  # its rows describe the violations they plant
OLD_HEAD = "§C Copy-ready rows"  # the hand-off's Old cells are verbatim text at the base


def lex_units(doc: str, text: str) -> list[LexUnit]:
    """Every unit a lexicon gate reads, rendered: each table row (cells joined by " | "), each
    bullet or numbered item, each paragraph and each heading, with its `##` section. Skipped: the
    spec's §20 rows (they name the violations they plant) and §C's Old cells in the hand-off."""
    out: list[LexUnit] = []
    lines = text.split("\n")
    fence = fenced(lines)
    sec, skip, old_col = "(top)", False, False
    para: list[str] = []

    def flush() -> None:
        if para and not skip:
            out.append(LexUnit(doc, sec, " ".join(para)))
        para.clear()

    for i, ln in enumerate(lines):
        s = ln.strip()
        m = HEADING.match(ln) if not fence[i] else None
        if m:
            flush()
            if len(m[1]) <= 2:
                sec = sec_id(m[2])
                skip = doc == "spec" and m[2].startswith(MUTATION_HEAD)
                old_col = doc == "hand" and m[2].startswith(OLD_HEAD)
            if not skip:
                out.append(LexUnit(doc, sec, s))
            continue
        if fence[i]:
            flush()
            if not skip and not FENCE_OPEN.match(ln):
                out.append(LexUnit(doc, sec, s))
            continue
        if re.match(r"^\s*\|", ln):
            flush()
            if not is_rule(ln) and not skip:
                cells = split_row(s)
                if old_col and len(cells) > 3:
                    cells = cells[:2] + cells[3:]
                out.append(LexUnit(doc, sec, " | ".join(cells)))
        elif re.match(r"^\s*(?:[-*+]|\d+\.) ", ln):
            flush()
            if not skip:
                out.append(LexUnit(doc, sec, s))
        elif s:
            para.append(s)
        else:
            flush()
    flush()
    return out


def claims(
    units: list[LexUnit],
    term: str,
    near: str = "",
    unless: str = "",
    keep_quotes: bool = False,
) -> list[tuple[str, str, str]]:
    """(clause, doc, section) for every clause asserting `term` (naming `near`, when given; never
    one naming `unless`, the cited or recorded forms a gate allows)."""
    hits: list[tuple[str, str, str]] = []
    for u in units:
        for c in clauses(u.text):
            scope = norm_text(c if keep_quotes else unquote(c))
            if near and not re.search(near, scope):
                continue
            if unless and re.search(unless, norm_text(c)):
                continue
            if live(c, term, keep_quotes):
                hits.append((norm_text(c)[:70], u.doc, u.sec))
    return hits


def as_findings(tag: str, what: str, hits: list[tuple[str, str, str]]) -> list[Finding]:
    return [(tag, f"{what}: {h[0]!r}", h[1], h[2]) for h in hits]


# ---------------------------------------------------------------------------- tokens


@functools.lru_cache(maxsize=8)
def token_file(name: str) -> dict[str, object]:
    data = json.loads(at_base(f"{DS_SRC_REL}/{name}.tokens.json"))
    return {k: v.get("$value") for k, v in data.items() if isinstance(v, dict)}


@functools.lru_cache(maxsize=4)
def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        merged.update(token_file(f))
    return merged


def resolve(tokens: dict[str, object], name: str) -> str:
    if name not in tokens:
        return "MISSING"
    value, hops = tokens[name], 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1], "MISSING"), hops + 1
    return value if isinstance(value, str) else json.dumps(value)


@functools.lru_cache(maxsize=1)
def all_token_names() -> frozenset[str]:
    names: set[str] = set()
    for f in ("primitives", *SEMANTIC):
        names |= set(token_file(f))
    return frozenset(names)


def themes_json_names() -> list[str]:
    data = json.loads(at_base(f"{DS_SRC_REL}/themes.json"))
    return [str(t["name"]) for t in data["themes"]]


def hex_of(theme: str, name: str) -> str:
    v = resolve(load_theme(theme), name)
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
        raise SystemExit(f"FAIL token {name} does not resolve to an opaque colour ({v})")
    return v.upper()


def px_of(name: str) -> str:
    """A dimension token's value in px, the same in the three themes (density is a token pair)."""
    got = {resolve(load_theme(th), name) for th in THEMES}
    if len(got) != 1:
        raise SystemExit(f"FAIL token {name} differs across the themes ({sorted(got)})")
    v = got.pop()
    if not re.fullmatch(r"\d+(?:\.\d+)?", v):
        raise SystemExit(f"FAIL token {name} is not a plain number ({v})")
    return v


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex6: str) -> float:
    r, g, b = (srgb_to_linear(v) for v in rgb(hex6))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def show_ratio(r: float) -> str:
    """Two decimals, truncated (never rounded up across a bar)."""
    return f"{math.floor(r * 100) / 100:.2f}"


# ---------------------------------------------------------------------------- calendar, tickets


def cal_start() -> tuple[datetime.date, int]:
    """Sprint 01's start and the sprint length, parsed from `calendar_cv.py` at the base."""
    src = at_base(CITE_FILES["CAL"])
    m = re.search(r"^SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", src, MULTI)
    d = re.search(r"^SPRINT_DAYS = (\d+)", src, MULTI)
    if not m or not d:
        raise SystemExit("FAIL parse: calendar_cv.py constants")
    return datetime.date(int(m[1]), int(m[2]), int(m[3])), int(d[1])


def sprint_start(n: int) -> str:
    start, days = cal_start()
    return (start + datetime.timedelta(days=(n - 1) * days)).isoformat()


@functools.lru_cache(maxsize=1)
def ticket_sprints() -> dict[str, int]:
    data = json.loads(at_base(TICKETS_REL))
    out: dict[str, int] = {}
    for t in data:
        m = re.search(r"(\d+)", str(t.get("sprint", "")))
        if m:
            out[str(t["key"])] = int(m[1])
    return out


# ---------------------------------------------------------------------------- the spec's tables

FRAME_HEAD = "2. The frame register"
FR_COLS = ("Frame", "Screen", "State", "Board", "Page", "PNG", "Source", "Status")
REDLINE_HEAD = "3. Redlines"
MAP_HEAD = "5. The component mapping"
FROZEN_HEAD = "7. The frozen safety strings"
CONTRACT_HEAD = "9. The contract"
DIAG_HEAD = "10. Diagnostics"
MOTION_HEAD = "11. Motion"
FROW_HEAD = "12.1 The F-row ledger"
AL_HEAD = "13. The a11y acceptance list"
BUDGETS_HEAD = "14. Performance budgets"
EVENTS_HEAD = "15. Observability"
LOG_HEAD = "16. The open-questions log"
WALK_HEAD = "17. The walkthrough"
CONSUMER_HEAD = "18. The consumers"
VERSION_HEAD = "19. Versioning"
CROW_HEAD = "21.1 Contradictions"
GROW_HEAD = "21.2 Gaps"


def dict_rows(block: str, cols: tuple[str, ...]) -> list[dict[str, str]]:
    return [dict(zip(cols, r, strict=False)) for r in table_rows(block)]


def frames(spec: str) -> list[dict[str, str]]:
    return dict_rows(section(spec, FRAME_HEAD), FR_COLS)


def cites_in(cell: str) -> list[tuple[str, int]]:
    """Every (cite id, line) a cell names, ranges expanded."""
    out: list[tuple[str, int]] = []
    for m in CITE_GROUP.finditer(cell):
        cid = m["a"] or m["b"]
        refs = [m["first"], *re.findall(r":(\d+(?:[\u2013-]\d+)?)", m["more"])]
        for ref in refs:
            parts = [int(p) for p in re.split(r"[\u2013-]", ref)]
            lo, hi = parts[0], parts[-1]
            out += [(cid, n) for n in range(lo, hi + 1)]
    return out


@dataclass(frozen=True)
class DeckRow:
    sub: str  # "6.1" … "6.6", or "7" for the frozen strings
    keys: tuple[str, ...]
    strings: tuple[str, ...]
    where: str
    kind: str
    owner: str
    source: str
    by_cite: bool
    line: int  # the row's 1-based line in the spec
    announce: str = ""  # the Announce cell (BQ-16, BQ-26)


def expand_keys(cell: str) -> tuple[str, ...]:
    k = cell.strip().strip("`")
    m = re.fullmatch(r"(.*?)\{([^{}]+)\}", k)
    if not m:
        return (k,)
    return tuple(m[1] + x.strip() for x in m[2].split(","))


def deck_rows(spec: str) -> list[DeckRow]:
    out: list[DeckRow] = []
    lines = spec.split("\n")
    sub = ""
    for i, ln in enumerate(lines, 1):
        m = HEADING.match(ln)
        if m:
            h = m[2]
            sm = re.match(r"(6\.\d) ", h)
            sub = sm[1] if sm else ("7" if h.startswith(FROZEN_HEAD) else "")
            continue
        if not sub or not ln.startswith("|") or is_rule(ln):
            continue
        cells = split_row(ln)
        if sub == "7":
            if not re.fullmatch(r"FS-\d", cells[0]):
                continue
            text = re.findall(r'"([^"]*)"', cells[1])
            out.append(
                DeckRow(
                    "7",
                    expand_keys(cells[2]),
                    tuple(text),
                    "frozen",
                    "frozen",
                    cells[3],
                    cells[4],
                    False,
                    i,
                    cells[7] if len(cells) > 7 else "",
                )
            )
            continue
        if cells[0] == "Key" or len(cells) < 6:
            continue
        by_cite = cells[1].startswith("—")
        strings = () if by_cite else tuple(re.findall(r'"([^"]*)"', cells[1]))
        out.append(
            DeckRow(
                sub,
                expand_keys(cells[0]),
                strings,
                cells[2],
                cells[3],
                cells[4],
                cells[5],
                by_cite,
                i,
                cells[6] if len(cells) > 6 else "",
            )
        )
    return out


ANNOUNCE_PART = re.compile(r"((?:`[a-z_]+`(?:, )?)+) (polite|assertive|none)(?: \((F-\d\d)\))?")


def announce_marks(r: DeckRow) -> dict[str, str] | None:
    """Each key's mark from the row's Announce cell: a default, then `; `-separated exceptions
    naming key suffixes; None when the cell does not parse or names a key the row lacks."""
    parts = r.announce.split("; ")
    if parts[0] not in ANNOUNCE:
        return None
    marks = {k: parts[0] for k in r.keys}
    tails = {k.rsplit(".", 1)[-1]: k for k in r.keys}
    for p in parts[1:]:
        m = ANNOUNCE_PART.fullmatch(p)
        if not m:
            return None
        for suffix in re.findall(r"`([a-z_]+)`", m[1]):
            if suffix not in tails:
                return None
            marks[tails[suffix]] = m[2]
    return marks


def io_checks(r: DeckRow) -> dict[str, list[str]]:
    """The server / client tags an SCR-089 reason row's Where cell gives each key (D03:155)."""
    tails = {k.rsplit(".", 1)[-1]: k for k in r.keys}
    out: dict[str, list[str]] = {k: [] for k in r.keys}
    for m in re.finditer(r"((?:`[a-z_]+`(?:, )?)+) (server|client)\b", r.where):
        for suffix in re.findall(r"`([a-z_]+)`", m[1]):
            if suffix in tails:
                out[tails[suffix]].append(m[2])
    return out


def has_figures(text: str) -> bool:
    """A string that holds a figure and no `{slot}`: merged instance text (D05-G8)."""
    return re.search(r"\d", text) is not None and "{" not in text


FROZEN_SCREEN = {"rules.editor.": "SCR-081", "rules.list.": "SCR-080"}


def deck_json(spec: str) -> str:
    """The copy deck as data (hand-off §F): every key with its string, screen, kind, owner and
    source; the rows carried by cite listed apart. Written by `--fill`; compared by G-DECK-JSON."""
    strings: dict[str, dict[str, object]] = {}
    by_cite: list[dict[str, str]] = []
    for r in deck_rows(spec):
        if r.by_cite:
            by_cite.append({"key": r.keys[0], "owner": r.owner, "source": r.source})
            continue
        marks = announce_marks(r) or {}
        checks = io_checks(r) if r.sub == "6.5" else {}
        for k, s in zip(r.keys, r.strings, strict=False):
            entry: dict[str, object] = {"text": s}
            if r.sub == "7":
                refs = cites_in(r.source)
                entry["screen"] = next(
                    (v for p, v in FROZEN_SCREEN.items() if k.startswith(p)), "shared"
                )
                entry["owner"] = refs[0][0] if refs else ""
                entry["status"] = r.owner
                entry["frozen"] = True
            else:
                entry["screen"] = DECK_SCREEN[r.sub]
                entry["kind"] = r.kind
                entry["owner"] = r.owner
            entry["source"] = r.source
            entry["announce"] = marks.get(k, "")
            if checks.get(k):
                entry["check"] = checks[k][0]
            if has_figures(s):
                entry["has_figures"] = True
            strings[k] = entry
    doc: dict[str, object] = {"pack": "E36-D05", "version": "v1", "base": BASE}
    doc["strings"] = strings
    doc["carried_by_cite"] = by_cite
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def frozen_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, FROZEN_HEAD)) if re.fullmatch(r"FS-\d", r[0])]


def log_rows(spec: str) -> list[list[str]]:
    return table_rows(section(spec, LOG_HEAD))


def log_ids(cell: str) -> list[str]:
    return [x.strip() for x in cell.split(",") if x.strip()]


@functools.lru_cache(maxsize=1)
def scenarios() -> dict[str, tuple[str, ...]]:
    """The consuming stories' Gherkin scenario titles in `E36.json` at the base, in order."""
    out: dict[str, tuple[str, ...]] = {}
    for tk in json.loads(at_base(TICKETS_REL)):
        if isinstance(tk, dict) and tk.get("key") in STORIES:
            body = str(tk.get("body", ""))
            titles = re.findall(r"^\s*Scenario(?: Outline)?:\s*(.+?)\s*$", body, MULTI)
            out[str(tk["key"])] = tuple(titles)
    return out


@functools.lru_cache(maxsize=1)
def d04_rows(prefix: str) -> tuple[tuple[int, tuple[str, ...]], ...]:
    """D04's table rows whose lead cell matches `prefix` (e.g. `F-\\d\\d`), with their lines."""
    out: list[tuple[int, tuple[str, ...]]] = []
    for i, ln in enumerate(at_base(CITE_FILES["D04"]).split("\n"), 1):
        if ln.startswith("|") and not is_rule(ln):
            cells = split_row(ln)
            if re.fullmatch(prefix, cells[0]):
                out.append((i, tuple(cells)))
    return tuple(out)


def board_bullets(cid: str) -> dict[str, tuple[str, str]]:
    """A merged spec's boards as drawn: number -> (board id, PNG basename)."""
    out: dict[str, tuple[str, str]] = {}
    for ln in at_base(CITE_FILES[cid]).split("\n"):
        m = re.match(
            r"^- `(\d{2}) [a-z0-9-]+` — board id `([0-9a-f-]+)` — `docs/design/E36/img/([^`]+)`",
            ln,
        )
        if m:
            out[m[1]] = (m[2], m[3])
    return out


def upstream_ids() -> list[str]:
    """Every upstream open row the log must carry (BQ-30): D02's C / G / Q rows, D03's C / G / Q
    rows but the closed D03-G18 and the withdrawn D03-Q9, D04's C / G rows and its open or
    answered Q rows (Q-01, Q-03, Q-06; Q-02, Q-04, Q-05 are RULED)."""
    ids: list[str] = []
    for cid, pat in (("D02", r"D02-[CGQ]\d+"), ("D03", r"D03-[CGQ]\d+")):
        for ln in at_base(CITE_FILES[cid]).split("\n"):
            if ln.startswith("|") and not is_rule(ln):
                c0 = split_row(ln)[0]
                if re.fullmatch(pat, c0) and c0 not in ("D03-G18", "D03-Q9"):
                    ids.append(c0)
    for _i, cells in d04_rows(r"[CG]-\d\d|Q-0[136]"):
        ids.append(f"D04-{cells[0]}")
    return list(dict.fromkeys(ids))


def own_rows(spec: str) -> list[str]:
    body = section(spec, GROW_HEAD)
    return re.findall(r"^- \*\*(D05-[GQ]\d+)\*\*", body, MULTI)


# ---------------------------------------------------------------------------- computed values


def theme_pairs(spec: str) -> set[tuple[str, str]]:
    return {
        (m[1], m[2])
        for m in re.finditer(r"\{\{CONTRAST:(?:dark|light|hc):([a-z.-]+)/([a-z.-]+)\}\}", spec)
    } | {
        (m[1], m[2])
        for m in re.finditer(r"<!--=CONTRAST:(?:dark|light|hc):([a-z.-]+)/([a-z.-]+)-->", spec)
    }


def keys_named(text: str, kind: str) -> set[str]:
    bare = CODE.sub("", text)
    return {
        k.split(":", 1)[1]
        for k in set(PLACEHOLDER.findall(bare)) | set(ANCHOR.findall(bare))
        if k.startswith(f"{kind}:")
    }


def count_values(spec: str) -> Values:
    fr = frames(spec)
    rows = deck_rows(spec)
    fz = frozen_rows(spec)
    lg = log_rows(spec)
    ids = [x for r in lg for x in log_ids(r[0])]
    d03_motion = [
        r for r in table_rows(section(at_base(CITE_FILES["D03"]), "10. Motion")) if r[0].isdigit()
    ]
    v: Values = {
        "COUNT:boards.d03": str(len(board_bullets("D03"))),
        "COUNT:boards.d04": str(len(board_bullets("D04"))),
        "COUNT:frames.total": str(len(fr)),
        "COUNT:frames.drawn": str(sum(1 for f in fr if f.get("Status") == DRAWN_STATUS)),
        "COUNT:frames.pending": str(sum(1 for f in fr if f.get("Status") == PENDING_STATUS)),
        "COUNT:deck.rows": str(sum(1 for r in rows if r.sub != "7")),
        "COUNT:deck.strings": str(sum(len(r.strings) for r in rows)),
        "COUNT:deck.bycite": str(sum(1 for r in rows if r.by_cite)),
        "COUNT:frozen.rows": str(len(fz)),
        "COUNT:frozen.proposed": str(sum(1 for r in fz if "string PROPOSED" in r[3])),
        "COUNT:motion.rows": str(len(d03_motion)),
        "COUNT:frows": str(len(d04_rows(r"F-\d\d"))),
        "COUNT:al": str(len(d04_rows(r"AL-\d\d"))),
        "COUNT:log.rows": str(len(lg)),
        "COUNT:log.ids": str(len(ids)),
        "COUNT:log.upstream": str(sum(1 for x in ids if not x.startswith("D05-"))),
        "COUNT:log.unowned": str(sum(1 for r in lg if len(r) < 3 or not r[2].strip())),
        "COUNT:log.undated": str(sum(1 for r in lg if len(r) < 5 or "DATE:" not in r[4])),
        "COUNT:motion.conflicts": str(len(table_rows(section(spec, MOTION_HEAD)))),
        "COUNT:deck.figures": str(
            sum(1 for r in rows if not r.by_cite for s in r.strings if has_figures(s))
        ),
        "COUNT:gherkin.scenarios": str(sum(len(v) for v in scenarios().values())),
    }
    return v


def al_hash() -> str:
    rows = "\n".join(pin_norm(" | ".join(c)) for _i, c in d04_rows(r"AL-\d\d"))
    return hashlib.sha256(rows.encode("utf-8")).hexdigest()[:12]


def compute_values(spec: str, hand: str) -> Values:
    both_ = spec + "\n" + hand
    v: Values = {}
    for key, (cid, n, pat) in CITE_NUMS.items():
        m = re.search(pat, base_line(cid, n))
        if not m:
            raise SystemExit(f"FAIL parse: CITE:{key} not on {cid}:{n}")
        v[f"CITE:{key}"] = m[1]
    for tok in keys_named(both_, "PX"):
        v[f"PX:{tok}"] = px_of(tok)
    for tok in keys_named(both_, "OPACITY"):
        v[f"OPACITY:{tok}"] = px_of(tok)
    for key in keys_named(both_, "HEX"):
        th, tok = key.split(".", 1)
        v[f"HEX:{key}"] = hex_of(th, tok)
    for th in THEMES:
        for fg, bg in theme_pairs(both_):
            ratio = contrast(hex_of(th, f"color.{fg}"), hex_of(th, f"color.{bg}"))
            v[f"CONTRAST:{th}:{fg}/{bg}"] = show_ratio(ratio)
    v["DATE:S01"] = sprint_start(1)
    v["DATE:S16"] = sprint_start(16)
    sprints = ticket_sprints()
    for key in keys_named(both_, "DATE"):
        if key in sprints:
            v[f"DATE:{key}"] = sprint_start(sprints[key])
    v["HASH:d04.al"] = al_hash()
    v.update(count_values(spec))
    return v


@functools.lru_cache(maxsize=16)
def compute_cached(spec: str, hand: str) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(compute_values(spec, hand).items()))


def compute(spec: str, hand: str) -> Values:
    return dict(compute_cached(spec, hand))


# ---------------------------------------------------------------------------- fill and anchors


def code_spans(line: str) -> list[tuple[int, int]]:
    return [c.span() for c in CODE.finditer(line)]


def fill(text: str, values: Values) -> tuple[str, list[str]]:
    """Replace every placeholder outside a code span with `VALUE<!--=KEY-->`."""
    unknown: list[str] = []

    def sub(m: re.Match[str]) -> str:
        if m[1] not in values:
            unknown.append(m[1])
            return m[0]
        return f"{values[m[1]]}<!--={m[1]}-->"

    out_lines = []
    for line in text.split("\n"):
        parts, pos = [], 0
        for c in CODE.finditer(line):
            parts.append(PLACEHOLDER.sub(sub, line[pos : c.start()]))
            parts.append(c[0])
            pos = c.end()
        parts.append(PLACEHOLDER.sub(sub, line[pos:]))
        out_lines.append("".join(parts))
    return "\n".join(out_lines), sorted(set(unknown))


def unfill(text: str) -> str:
    """Every anchored value back to its placeholder (outside code spans), so `--fill` refreshes a
    value that changed; the value is the run of `#`, word, `.` and `-` characters before it."""

    def part(seg: str) -> str:
        return re.sub(r"[#\w.-]*<!--=([A-Z0-9]+:[^>]+?)-->", lambda m: f"{{{{{m[1]}}}}}", seg)

    out_lines = []
    for line in text.split("\n"):
        parts, pos = [], 0
        for c in CODE.finditer(line):
            parts += [part(line[pos : c.start()]), c[0]]
            pos = c.end()
        out_lines.append("".join(parts) + part(line[pos:]))
    return "\n".join(out_lines)


def bare_figures(text: str, values: Values) -> list[tuple[int, str]]:
    """Figures with a unit, or counts before a counted noun, typed by hand: outside an anchor, a
    quote, a code span, a cite, an issue number and the hand-off's Old cells."""
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(text.split("\n"), 1):
        work = line
        for m in reversed(list(ANCHOR.finditer(work))):
            want = values.get(m[1], "")
            start = m.start() - len(want) if work[: m.start()].endswith(want) else m.start()
            work = work[:start] + " ⟨v⟩ " + work[m.end() :]
        work = PLACEHOLDER.sub(" ⟨v⟩ ", work)
        work = QUOTED.sub(" ", CODE.sub(" ", work))
        work = re.sub(r"\(#\d+\)|#\d+", " ", work)
        hits += [(i, m[0]) for m in FIGURE.finditer(work)]
        hits += [(i, m[0]) for m in COUNTED.finditer(work)]
    return hits


def g_anchor_doc(doc: str, text: str, values: Values) -> list[Finding]:
    bad: list[Finding] = []
    for i, line in enumerate(text.split("\n"), 1):
        sec = h2_at(text, i)
        for m in PLACEHOLDER.finditer(CODE.sub("", line)):
            bad.append(("G-ANCHOR", f"{doc}:{i} placeholder {{{{{m[1]}}}}} not filled", doc, sec))
        spans = code_spans(line)
        for m in ANCHOR.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue  # an anchor quoted as code (the format's description)
            want = values.get(m[1])
            if want is None:
                bad.append(("G-ANCHOR", f"{doc}:{i} {m[1]} is not a computed value", doc, sec))
            elif not line[: m.start()].endswith(want) or re.search(
                r"[\w.,]$", line[: m.start() - len(want)]
            ):
                got = re.split(r"[ |*(]", line[: m.start()])[-1]
                msg = f"{doc}:{i} {m[1]} reads {got!r}; the tool computes {want!r}"
                bad.append(("G-ANCHOR", msg, doc, sec))
    for i, fig in bare_figures(text, values):
        bad.append(
            ("G-ANCHOR", f"{doc}:{i} {fig!r} is a figure typed by hand", doc, h2_at(text, i))
        )
    return bad


def g_marker_doc(doc: str, text: str, values: Values) -> list[Finding]:
    """Every HTML comment (the one strip pattern) is a value anchor the tool computes; a hidden
    note, an unknown key or an unclosed comment FAILs."""
    bad: list[Finding] = []
    starts = [0]
    for ln in text.split("\n"):
        starts.append(starts[-1] + len(ln) + 1)
    lines = text.split("\n")
    for m in COMMENT.finditer(text):
        i = next(k for k in range(len(starts) - 1) if starts[k] <= m.start() < starts[k + 1])
        col = m.start() - starts[i]
        if any(a <= col < b for a, b in code_spans(lines[i])):
            continue
        sec = h2_at(text, i + 1)
        am = ANCHOR.fullmatch(m[0])
        if not m[0].endswith(("-->", "--!>")) and m.end() == len(text):
            bad.append(("G-MARKER", f"{doc}:{i + 1} an unclosed comment hides the rest", doc, sec))
        elif am is None or am[1] not in values:
            bad.append(("G-MARKER", f"{doc}:{i + 1} a hidden comment {m[0][:40]!r}", doc, sec))
    return bad


def g_hex_doc(doc: str, text: str) -> list[Finding]:
    """A hex is the tool's (an anchored value), never typed by hand."""
    bad: list[Finding] = []
    for i, line in enumerate(text.split("\n"), 1):
        work = CODE.sub(lambda c: " " * len(c[0]), line)
        for m in HEXLIT.finditer(work):
            if not line[m.end() :].startswith("<!--=HEX:"):
                msg = f"{doc}:{i} {m[0]} typed by hand (not the tool's value)"
                bad.append(("G-HEX", msg, doc, h2_at(text, i)))
    return bad


# ---------------------------------------------------------------------------- cites


def cite_findings(docs: dict[str, str], fetch: Fetch) -> tuple[list[Finding], list[str], int]:
    fails: list[Finding] = []
    warns: list[str] = []
    done: set[tuple[str, int]] = set()

    def lines_of(rev: str, rel: str) -> list[str] | None:
        t = fetch(rev, rel)
        return None if t is None else t.split("\n")

    for doc, text in docs.items():
        for li, line in enumerate(text.split("\n"), 1):
            for m in CITE_GROUP.finditer(line):
                cid = m["a"] or m["b"]
                if m["a"] and not (re.fullmatch(r"\d{2}|E\d\d-D\d\d", cid) or "/" in cid):
                    continue
                refs = [m["first"], *re.findall(r":(\d+(?:[\u2013-]\d+)?)", m["more"])]
                for ref in refs:
                    for part in re.split(r"[\u2013-]", ref):
                        n = int(part)
                        if (cid, n) in done:
                            continue
                        done.add((cid, n))
                        rel = cite_path(cid)
                        base = lines_of(BASE, rel) if rel else None
                        sec = h2_at(text, li)
                        if rel is None or base is None:
                            fails.append(("G-CITE", f"`{cid}`:{n} no such file", doc, sec))
                            continue
                        if n < 1 or n > len(base) or not base[n - 1].strip():
                            msg = f"`{cid}`:{n} line missing or blank at {BASE}"
                            fails.append(("G-CITE", msg, doc, sec))
                            continue
                        head = lines_of(HEAD, rel)
                        if head is not None and (n > len(head) or head[n - 1] != base[n - 1]):
                            warns.append(f"[G-CITE] `{cid}`:{n} drifted at {HEAD}")
    for cid, n, frag in CITED:
        rel = cite_path(cid)
        base = lines_of(BASE, rel) if rel else None
        if base is None or n > len(base) or frag not in base[n - 1]:
            hits = [i + 1 for i, ln in enumerate(base or []) if frag in ln]
            msg = f'`{cid}`:{n} "{frag[:40]}" not on the line (found {hits[:4]})'
            fails.append(("G-CITE", msg, None, None))
    return fails, warns, len(done) + len(CITED)


# ---------------------------------------------------------------------------- the texts


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    deck: str  # the copy-deck JSON on disk (G-DECK-JSON)
    plans: tuple[tuple[str, str], ...]  # the working-tree untouched files (G-UNTOUCHED)
    values: Values = field(default_factory=dict)


@functools.lru_cache(maxsize=64)
def lex_cached(doc: str, text: str) -> tuple[LexUnit, ...]:
    return tuple(lex_units(doc, text))


def lex(t: Texts) -> list[LexUnit]:
    return [*lex_cached("spec", t.spec), *lex_cached("hand", t.hand)]


def spec_sec(t: Texts, head: str) -> str:
    return h2_of(t.spec, head)


def hand_sec(t: Texts, head: str) -> str:
    return h2_of(t.hand, head)


def F(tag: str, msg: str, doc: str | None, sec: str | None) -> Finding:
    return (tag, msg, doc, sec)


def lexicon(
    tag: str, what: str, term: str, near: str = "", unless: str = "", head: str = ""
) -> Callable[[Texts], list[Finding]]:
    """No clause asserts `term` (naming `near`); `head` restricts it to one spec section."""

    def run(t: Texts) -> list[Finding]:
        units = lex(t)
        if head:
            sec = spec_sec(t, head)
            units = [u for u in units if u.doc == "spec" and u.sec == sec]
        return as_findings(tag, what, claims(units, term, near=near, unless=unless))

    run.__doc__ = f"{tag}: no clause asserts {what}."
    return run


def require(
    tag: str, head: str, needles: tuple[str, ...], doc: str = "spec"
) -> Callable[[Texts], list[Finding]]:
    """The section `head` holds every needle (rendered, lower case)."""

    def run(t: Texts) -> list[Finding]:
        text = t.spec if doc == "spec" else t.hand
        body = norm_text(section(text, head))
        sec = h2_of(text, head)
        return [
            F(tag, f"{head.split(' ')[0]} lacks {n!r}", doc, sec)
            for n in needles
            if norm_text(n) not in body
        ]

    return run


def both(*gates: Callable[[Texts], list[Finding]]) -> Callable[[Texts], list[Finding]]:
    def run(t: Texts) -> list[Finding]:
        return [x for gate in gates for x in gate(t)]

    return run


# ---------------------------------------------------------------------------- lexicon gates
#
# Each ruled behaviour has a synonym set read from table cells and prose alike; quoted copy is
# not a claim; a negated mention is not a claim.

g_session = lexicon(
    "G-SESSION",
    "a walkthrough or session held, recorded or attended",
    r"\b(?:took place|was held|were held|has happened|happened|was run|was recorded|"
    r"were recorded|attended|attendance)\b",
    near=r"\bsession\b|\bwalkthrough\b|\bmeeting\b|\bengineers?\b",
    unless=r"no session took place|at most ten items|owner walkthrough \(",
)
g_pendlex = lexicon(
    "G-PENDING",
    "SCR-081 / SCR-083 boards drawn or exported",
    r"\b(?:drawn|exported|redrawn|rendered on (?:a )?board|has (?:a )?board|boards? (?:exist|are "
    r"ready|merged))\b",
    near=r"\bscr 081\b|\bscr 083\b|\be36 d02\b|\bd02\b|\bp d02\b|\b873\b",
    unless=r"pending|text first|blocked penpot|not drawn|no board|v1\.1|once|until|when #?873|"
    r"d03|d04|takes? their",
)
g_no15 = lexicon(
    "G-NO15",
    "this PR editing `15`",
    r"\b(?:(?:this|the) (?:pr|pack|ticket) (?:\w+ )?(?:edits|adds|amends|appends|changes|writes|"
    r"catalogues|registers|updates|modifies|rewrites|touches|fills in|patches)|edited here|"
    r"added here|catalogued here|updated here|added in this pr|edited in this pr)\b",
    near=r"\b15\b|catalogue|cmp 24[03]",
)
g_no22 = lexicon(
    "G-NO22",
    "this PR editing `22` or proposing an operation's shape",
    r"\b(?:(?:this|the) (?:pr|pack|ticket) (?:\w+ )?(?:edits|adds|amends|changes|defines|proposes|"
    r"sketches|drafts|specifies|designs|outlines|writes)|(?:edited|added|defined|proposed|sketched|"
    r"drafted) here)\b",
    near=r"\b22\b|operation|endpoint|contract|shape|schema|request body",
)
g_frozen_lex = lexicon(
    "G-FROZEN",
    "the freeze approved, final or ruled by the owner",
    r"\b(?:approved|ratified|signed off|final|ruled|binding|locked|in force|in effect|effective|"
    r"settled|agreed|adopted|accepted)\b",
    near=r"\bfreeze\b|\bfrozen\b",
    unless=r"pending|proposed|until the owner|owner rules|stays",
)
g_motion_lex = lexicon(
    "G-MOTION",
    "D02H Table 4 as the motion record, or an edit of D03",
    r"\b(?:is|are|stays|remains) (?:the )?(?:motion )?(?:record|source)\b|\bgoverns?\b|"
    r"\bprevails?\b|\b(?:edits?|amends?|changes?) d03\b|\bd03 is edited\b",
    near=r"\bd02h\b|d02 handoff|\bnone animated\b|\bd03\b",
    unless=r"d03 §10 \(|d03 §10 and d03h|d03h table 4 \(d03h|superseded|never an edit",
)
g_al_lex = lexicon(
    "G-AL",
    "the AL list copied into the pack or an AL row added",
    r"\b(?:cop(?:y|ies|ied)|reproduc\w+|restat\w+|adds?|added|extends?)\b",
    near=r"\bal \d|\bal rows?\b|acceptance list|d04 §16",
    unless=r"for navigation only|f row changes",
)
g_split = lexicon(
    "G-SPLIT",
    "this pack owning SCR-084 … SCR-087 or E35-D03's deltas",
    r"\b(?:owns?|specif(?:y|ies)|carries|covers|draws|designs)\b",
    near=r"\bscr 08[4-7]\b|e35 d03(?:'s)? (?:scr 088 / scr 089 )?deltas?",
    unless=r"e35 d05|by cite|\(#940\) owns|e35 d05's",
)
g_advanced = lexicon(
    "G-ADVANCED",
    "an advanced or free-text expression mode in the form",
    r"\b(?:offers?|has|provides?|adds?|shows?|includes?|gains?|switch(?:es)?(?: \w+){0,3} into)"
    r" (?:an? )?(?:(?:advanced|expression|free text|free typed|formula|power user) ?)+"
    r"(?:mode|editor|field|toggle|expressions?)\b",
    near=r"\bform\b|cmp 141|editor",
    unless=r"scr 082",
)
g_loosen = lexicon(
    "G-LOOSEN",
    "a control that loosens or clears a stop, or `widen_stop` offered",
    r"\b(?:offers?|shows?|provides?|exposes?|lists?|adds?) (?:a |an |the )?(?:loosen\w*|"
    r"stop clearing|widen_stop|widen stop)\b|\bonly_tighten (?:is|as) (?:a )?(?:control|toggle|"
    r"checkbox)\b|\bmoves? (?:a|the) stop (?:further|away|wider)\b|"
    r"\b(?:relax\w*|widen\w*|loosen\w*) (?:a |the |its )?stops?\b",
)
g_keystroke = lexicon(
    "G-KEYSTROKE",
    "a compile or round-trip check per keystroke",
    r"\b(?:per|on (?:every|each)|each) keystrokes?\b|\bas you type\b|\bwhile typing\b|"
    r"\bcontinuously\b|\bas the user (?:edits|types)\b",
    near=r"compil|round trip|indicator|computed?|check",
)
g_oneclick = lexicon(
    "G-ONECLICK",
    "a one-click arm or a toggle that arms",
    r"\bone click arm\b|\barms? (?:in|with|on) (?:one|a single) click\b|\btoggle (?:that )?arms\b|"
    r"\b(?:the )?enable toggle arms\b|\b(?:a )?(?:single|one) click arms\b",
)
g_bulkop = lexicon(
    "G-BULKOP",
    "a bulk-disarm operation",
    r"\b(?:a|one|the)(?: single)? (?:bulk|batch) (?:disarm )?(?:operation|endpoint|call|request)s?"
    r"\b",
    near=r"disarm",
)
g_validity = lexicon(
    "G-VALIDITY",
    "form validity drawn as T2 or with the lock",
    r"\b(?:is|as|drawn) t2\b|\bwith the lock\b|\bcmp 079\b|\block glyph\b",
    near=r"fix the errors|validity|invalid|flatten all box|no action",
    unless=r"never t2|no lock|not t2|t2 is not validity|t2 \(|is t2 \(the|no cmp 079|"
    r"on a t2 control|under form validity no lock|over conversion|role , grant",
)
g_layer = lexicon(
    "G-LAYER",
    "the validator message as the primary line",
    r"\b(?:is|as) the primary line\b|\bprimary line (?:is|shows) the validator\b",
    near=r"validator|shipped text|message",
    unless=r"except|shipped safety messages|designed line is primary",
)
g_redraw = lexicon(
    "G-REDRAW",
    "a redraw or a new Penpot page in this PR",
    r"\b(?:redraws?|redrawn|new (?:penpot )?page|new board|draws? (?:a |new )?boards?|"
    r"board (?:now )?(?:sits|exists|lives|is placed))\b",
    near=r"\bthis (?:pr|pack|ticket)\b|\be36 d05\b|\bhere\b",
    unless=r"no redraw|no new page|none is drawn|no e36 d05 board",
)
g_signoff = lexicon(
    "G-SIGNOFF",
    "the owner's approval or the CDO sign-off given",
    r"\b(?:owner (?:has )?approved|approved by the owner|cdo signed|signed off by|"
    r"owner's approval (?:is )?(?:given|granted|recorded)|owner's go ahead|owner (?:has )?"
    r"(?:signed|ratified|accepted))\b",
)
g_testid = lexicon(
    "G-TESTID",
    "a `data-testid` per control",
    r"\b(?:every|each|all) (?:controls?|elements?|components?|rows?) "
    r"(?:gets?|has|have|carr(?:y|ies)) (?:a )?data testid\b"
    r"|\bdata testid (?:on|for) (?:every|each|all)\b",
)


g_except = lexicon(
    "G-EXCEPT",
    "an exception carved out of a universal safety or role rule",
    r"\b(?:except|but|other than|apart from|save for|unless)\b(?: for)?(?: (?:the|an?))? "
    r"(?:owners?|managers?|viewers?|admins?)\b",
    near=r"\bevery role\b|\bany role\b|\bno one click\b|\bnever\b|\bomitted\b|\bno screen\b"
    r"|\bfor every\b",
)


def g_close(t: Texts) -> list[Finding]:
    """A text-first doc names no closing keyword before an issue number."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if re.search(
                r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#\d", norm_text(line)
            ):
                bad.append(F("G-CLOSE", f"{doc}:{i} a closing keyword", doc, h2_at(text, i)))
    return bad


def g_charset(t: Texts) -> list[Finding]:
    """No compatibility character that NFKC would fold beyond CHARSET_ALLOW, no format character
    (a soft hyphen, a zero-width space), no letter outside the Latin script (a homoglyph), no
    space before a full stop or comma outside a code span, no CR, no trailing whitespace: what the
    pins fold away, or a reader cannot see, is not allowed in."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            odd = [
                c
                for c in line
                if c not in CHARSET_ALLOW
                and (
                    unicodedata.normalize("NFKC", c) != c
                    or unicodedata.category(c) == "Cf"
                    or (c.isalpha() and not unicodedata.name(c, "").startswith("LATIN"))
                )
            ]
            whys = [f"U+{ord(c):04X}" for c in odd[:1]]
            if re.search(r"\S\s+[.,](?=\s|$)", CODE.sub("``", line)):
                whys.append("a space before a full stop or comma")
            whys += ["a CR"] if "\r" in line else []
            whys += ["trailing whitespace"] if line != line.rstrip() else []
            if whys:
                bad.append(F("G-CHARSET", f"{doc}:{i} {', '.join(whys)}", doc, h2_at(text, i)))
    return bad


def g_url(t: Texts) -> list[Finding]:
    """No host, URL or local path (README:49)."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if URL.search(line):
                bad.append(F("G-URL", f"{doc}:{i} a host, URL or local path", doc, h2_at(text, i)))
    return bad


def g_ruled(t: Texts) -> list[Finding]:
    """The RULED heading cites the ruling and the BQ list; every comment id is on the allow-list."""
    bad: list[Finding] = []
    head = next((ln for ln in t.spec.split("\n") if ln.startswith("## The thirty-six")), "")
    if f"comment {RULING_ID}, on the BQ list {BQ_LIST_ID}" not in head:
        bad.append(F("G-RULED", "the RULED heading does not cite the ruling", "spec", sec_id(head)))
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            for cid in COMMENT_ID.findall(line):
                if cid not in RULED_IDS:
                    bad.append(F("G-RULED", f"{cid} is not a ruling comment", doc, h2_at(text, i)))
    return bad


def g_unbuilt(t: Texts) -> list[Finding]:
    """BQ-1: §0.1 states the rule screens are unbuilt from the base tree and names the consumers."""
    sec = spec_sec(t, "0. Status")
    raw = section(t.spec, "0.1 What is built")
    body = norm_text(raw)
    bad = [
        F("G-UNBUILT", f"§0.1 lacks {n!r}", "spec", sec)
        for n in (
            "the rule screens are unbuilt",
            "this pack is the implementation contract",
            "packages/rule editor core does not exist",
        )
        if n not in body
    ]
    feats = sorted(
        p.split("/")[-1] for p in tree_at_base("apps/web/src/features/") if "." not in p[-5:]
    )
    named = re.findall(r"`([a-zA-Z0-9-]+)`", raw.split(" and no rules slice")[0])
    if [f for f in feats if f != "README.md"] != sorted(n for n in named if n in feats) or any(
        "rule" in f for f in feats
    ):
        bad.append(
            F("G-UNBUILT", f"§0.1's feature list differs from the base: {feats}", "spec", sec)
        )
    if any(p.endswith("rule-editor-core") for p in tree_at_base("packages/")):
        bad.append(F("G-UNBUILT", "packages/rule-editor-core exists at the base", "spec", sec))
    for key in CONSUMERS:
        if key == "E36-X01":
            continue
        if f"{key} (#{ISSUES[key]})" not in raw:
            bad.append(F("G-UNBUILT", f"§0.1 does not name {key} (#{ISSUES[key]})", "spec", sec))
    if OWNER_PENDING.lower() not in t.spec.split("\n## ")[0].lower():
        bad.append(
            F("G-UNBUILT", "the status line lacks the owner-pending record", "spec", "(top)")
        )
    return bad


# The ruled sentences each lexicon gate guards, REQUIRED verbatim (rendered) in their sections:
# a paraphrase that replaces one FAILs here even after a repin.
g_redraw = both(
    g_redraw, require("G-REDRAW", "0.2 Evidence", ("No E36-D05 board exists and none is drawn.",))
)
g_advanced = both(
    g_advanced,
    require(
        "G-ADVANCED",
        "8.1 Conditions",
        (
            (
                'The form has no "advanced" expression mode: a graph-only construct renders the '
                "read-only card in place"
            ),
            "an expression editor is SCR-082's (E37).",
        ),
    ),
)
g_loosen = both(
    g_loosen,
    require(
        "G-LOOSEN",
        "1.2 Rules stated once",
        (
            (
                "No screen offers a control that loosens or clears a stop, for any role; "
                "`widen_stop` is omitted for every role and `only_tighten` is never a control "
                "(D02:158; D03:165)."
            ),
        ),
    ),
    require(
        "G-LOOSEN",
        "8.1 Conditions",
        ("`widen_stop` omitted for every role, `only_tighten` fixed and never a control (R-6;",),
    ),
)
g_keystroke = both(
    g_keystroke,
    require(
        "G-KEYSTROKE",
        "8.2 The round-trip",
        ("computed **on save and on mode switch only**, never per keystroke (`14`:1838);",),
    ),
)
g_oneclick = both(
    g_oneclick,
    require("G-ONECLICK", "8.3 Arm and disarm", ("No one-click arm exists (D03-C11).",)),
)
g_bulkop = both(
    g_bulkop,
    require(
        "G-BULKOP",
        "8.4 Disarm",
        (
            "**bulk disarm is n idempotent `PUT /rules/{ruleId}/mode` calls**, each audited,",
            "no bulk operation exists or is proposed.",
        ),
    ),
)
g_scr080 = require(
    "G-SCR080",
    "8.4 Disarm",
    (
        "A protected system rule is listed as skipped before any call (D03:127).",
        "Delete while armed is T2 `rule.delete.armed` (D03:104).",
        "A viewer sees every write as T2 under one panel-header notice (D03:97).",
    ),
)
g_rn = require(
    "G-RN",
    "1.2 Rules stated once",
    (
        "are not edited by this PR; `14` changes only by the five pointer lines this PR adds",
        (
            "The strings of §7 render exactly as written; a rewording needs design and security "
            "review (T Sec), routed to E36-X01 (#948)."
        ),
        "a control disabled by form validity takes the validity look",
        (
            "The form never ships an IR the validator rejects, and form and graph report identical "
            "diagnostics (`15`:2749; T Brief)."
        ),
        (
            "RBAC, risk and arming gates are enforced server-side; the UI renders server truth "
            "(`14`:85)."
        ),
    ),
)
g_errors = require(
    "G-ERRORS",
    "6.2 SCR-081",
    (
        "`RuleIrInvalid` (`22`:16155; `createRule`, `updateRule` and `compileRule`",
        (
            "the 503 (`22`:16295) while the engine is down keeps the edits under the engine-down "
            "banner (D02-Q12, D02:438)"
        ),
        "`403 view_as_read_only` on create (D02:209) is `rbac.view_as`",
        (
            "the 412 of a stale `If-Match` on `updateRule` (`22`:7821, :7840) has no designed "
            "state "
            "yet (D05-G6)"
        ),
    ),
)


LEXICON_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_unbuilt,
    g_session,
    g_pendlex,
    g_no15,
    g_no22,
    g_frozen_lex,
    g_motion_lex,
    g_al_lex,
    g_split,
    g_advanced,
    g_loosen,
    g_keystroke,
    g_oneclick,
    g_bulkop,
    g_validity,
    g_layer,
    g_redraw,
    g_signoff,
    g_testid,
    g_except,
    g_scr080,
    g_rn,
    g_errors,
    g_ruled,
    g_close,
    g_charset,
    g_url,
)


# ---------------------------------------------------------------------------- measured gates


def g_trace(t: Texts) -> list[Finding]:
    """The trace has one row per acceptance criterion (AC1 … AC4)."""
    rows = table_rows(section(t.spec, "Acceptance-criteria trace"))
    have = [m[1] for r in rows if (m := re.match(r"(AC\d)\b", r[0]))]
    sec = spec_sec(t, "Acceptance-criteria trace")
    return [
        F("G-TRACE", f"the trace has no {ac} row", "spec", sec)
        for ac in ("AC1", "AC2", "AC3", "AC4")
        if have.count(ac) != 1
    ]


def state_words(nn: str, n: int) -> list[str]:
    """`14`'s States line, as its state names (parentheses dropped)."""
    line = re.sub(r"\([^()]*\)", "", base_line(nn, n)).split("**States:**", 1)[-1]
    return [norm_text(x).strip(" .") for x in line.split("·") if x.strip(" .")]


def g_frame(t: Texts) -> list[Finding]:
    """BQ-6, BQ-7: the frame register, column by column, and `14`'s States lines covered."""
    sec = spec_sec(t, FRAME_HEAD)
    d03 = board_bullets("D03")
    bad: list[Finding] = []
    seen: set[str] = set()
    states: list[tuple[str, str]] = []
    for fr in frames(t.spec):
        fid, scr = fr.get("Frame", ""), fr.get("Screen", "")
        if fid in seen or scr not in SCREENS or not fid.startswith(f"`{scr}/"):
            bad.append(F("G-FRAME", f"{fid}: Frame / Screen", "spec", sec))
        seen.add(fid)
        if not fr.get("State"):
            bad.append(F("G-FRAME", f"{fid}: no State", "spec", sec))
        states.append((norm_text(fr.get("State", "")), scr))
        if len(cites_in(fr.get("Source", ""))) != 1:
            bad.append(F("G-FRAME", f"{fid}: Source is not one cite", "spec", sec))
        if scr in PENDING_SCREENS:
            want = ("— (#873)", "P-D02", "—", PENDING_STATUS)
            got = (fr.get("Board"), fr.get("Page"), fr.get("PNG"), fr.get("Status"))
            if got != want:
                bad.append(F("G-FRAME", f"{fid}: a pending row reads {got}", "spec", sec))
            continue
        m = re.fullmatch(r"D03 (\d{2})", fr.get("Board", ""))
        board = d03.get(m[1]) if m else None
        png = fr.get("PNG", "").strip("`")
        if board is None or png != board[1]:
            bad.append(F("G-FRAME", f"{fid}: Board / PNG {fr.get('Board')} {png}", "spec", sec))
        elif f"docs/design/E36/img/{png}" not in tree_at_base("docs/design/E36/img/"):
            bad.append(F("G-FRAME", f"{fid}: {png} is not in the tree at {BASE}", "spec", sec))
        if fr.get("Page") != "P-D03" or fr.get("Status") != DRAWN_STATUS:
            bad.append(F("G-FRAME", f"{fid}: Page / Status", "spec", sec))
    for scr, nn, n in (("SCR-080", "14", 1791), ("SCR-081", "14", 1830)):
        for w in state_words(nn, n):
            key = w.split(" banner")[0].split(" warning")[0]
            if not any(key in s and sc == scr for s, sc in states):
                bad.append(F("G-FRAME", f"{scr}: `14`'s state {w!r} has no frame", "spec", sec))
    return bad


def g_penpot(t: Texts) -> list[Finding]:
    """The pages are cited by name + id (README:47 to :50); the ids match D03:44 and D04:29."""
    sec = spec_sec(t, "0. Status")
    body = section(t.spec, "0.2 Evidence")
    bad: list[Finding] = []
    for key, cid, n in (("P-D03", "D03", 44), ("P-D04", "D04", 29)):
        want = re.search(r"`([0-9a-f]{8}-[0-9a-f-]{27})`", base_line(cid, n))
        m = re.search(rf"\*\*{key}\*\* = page `[^`]+`, page id `([0-9a-f-]+)`", body)
        if not want or not m or m[1] != want[1]:
            bad.append(F("G-PENPOT", f"{key}'s page id differs from {cid}:{n}", "spec", sec))
    if "**P-D02** = page `E36-D02 Rule form editor and templates`" not in body:
        bad.append(F("G-PENPOT", "P-D02 is not named", "spec", sec))
    return bad


def g_redline(t: Texts) -> list[Finding]:
    """BQ-8: every token resolves in the three themes (or is the PROPOSED alias); every value is
    the tool's anchor of a token the row names; a typed dimension names its G-row."""
    sec = spec_sec(t, REDLINE_HEAD)
    names = all_token_names()
    bad: list[Finding] = []
    for r in table_rows(section(t.spec, REDLINE_HEAD)):
        if len(r) != 6:
            bad.append(F("G-REDLINE", f"{r[0]}: {len(r)} cells", "spec", sec))
            continue
        tok_cell, val = r[3], r[4]
        named = re.findall(r"`([a-z][a-z0-9.-]+)`", tok_cell + " " + val)
        if tok_cell.startswith("— (typed"):
            if not re.search(r"D05-G1|D04 G-06|D03-Q7", tok_cell) or "typed" not in val:
                bad.append(F("G-REDLINE", f"{r[0]}: a typed value without its row", "spec", sec))
            if any(not k.startswith(("CITE:", "PX:space.12")) for k in ANCHOR.findall(val)):
                bad.append(F("G-REDLINE", f"{r[0]}: a typed value is not cited", "spec", sec))
            continue
        for tok in named:
            if tok in PROPOSED_TOKENS:
                if "PROPOSED" not in tok_cell:
                    bad.append(F("G-REDLINE", f"{r[0]}: {tok} not marked PROPOSED", "spec", sec))
            elif tok not in names:
                bad.append(F("G-REDLINE", f"{r[0]}: {tok} does not resolve", "spec", sec))
        for key in ANCHOR.findall(val) + PLACEHOLDER.findall(val):
            kind, rest = key.split(":", 1)
            tok = rest.split(".", 1)[1] if kind == "HEX" else rest
            if tok not in named and f"{{{tok}}}" not in tok_cell:
                bad.append(F("G-REDLINE", f"{r[0]}: {key} is not the row's token", "spec", sec))
        if not ANCHOR.findall(val) and not PLACEHOLDER.findall(val):
            bad.append(F("G-REDLINE", f"{r[0]}: no computed value", "spec", sec))
    return bad


def g_map(t: Texts) -> list[Finding]:
    """BQ-9, AC3: every mapped CMP heading is the cited `15` line; CMP-240 / CMP-243 are E13-D02's
    G-1 / G-4 until the separate PR; the thirteen contract components are all mapped."""
    sec = spec_sec(t, MAP_HEAD)
    bad: list[Finding] = []
    mapped: set[str] = set()
    for r in table_rows(section(t.spec, MAP_HEAD)):
        if len(r) != 4:
            bad.append(F("G-MAP", f"{r[0]}: {len(r)} cells", "spec", sec))
            continue
        ids = re.findall(r"CMP-\d{3}", r[2])
        mapped |= set(ids)
        lines = cites_in(r[3])
        for cmp_ in ids:
            ok = any(
                cid == "15" and base_line("15", n).startswith(f"### {cmp_} ") for cid, n in lines
            )
            if not ok:
                bad.append(F("G-MAP", f"{cmp_}: no `15` heading cited", "spec", sec))
    for cmp_ in (*CONTRACT_CMPS, *NEW_CMPS):
        if cmp_ not in mapped:
            bad.append(F("G-MAP", f"{cmp_} is not mapped", "spec", sec))
    body = norm_text(section(t.spec, MAP_HEAD))
    for n in ("separate one look docs(design) pr before this pack's pr (#4735", "so ac3 is met"):
        if n not in body:
            bad.append(F("G-MAP", f"§5 lacks {n!r}", "spec", sec))
    return bad


def g_deck(t: Texts) -> list[Finding]:
    """BQ-15, AC2: every deck string is verbatim on a line its row cites, at the base; keys are
    namespaced per screen (the T2 keys keep their E09-D09 names), unique and as many as the
    strings; a row carried by cite names its owner and its cite."""
    bad: list[Finding] = []
    keys: list[str] = []
    for r in deck_rows(t.spec):
        sec = h2_at(t.spec, r.line)
        where = f"spec:{r.line}"
        keys += list(r.keys)
        refs = cites_in(r.source)
        if not refs:
            bad.append(F("G-DECK", f"{where} no source cite", "spec", sec))
            continue
        if r.by_cite and r.announce != "\u2014":
            bad.append(
                F("G-DECK", f"{where} a by-cite row's Announce is not '\u2014'", "spec", sec)
            )
        elif not r.by_cite and announce_marks(r) is None:
            bad.append(
                F("G-DECK", f"{where} Announce {r.announce[:40]!r} does not parse", "spec", sec)
            )
        if r.sub == "6.5" and any(k.startswith("rules.io.reason.") for k in r.keys):
            for k, tags in io_checks(r).items():
                if tags != [IO_CHECK.get(k.rsplit(".", 1)[-1], "?")]:
                    bad.append(F("G-DECK", f"{where} {k} tagged {tags} (D03:155)", "spec", sec))
        if r.sub == "7":
            continue  # the frozen strings are G-FROZEN's
        if r.by_cite:
            if len(r.keys) != 1 or not r.owner:
                bad.append(F("G-DECK", f"{where} a by-cite row without key / owner", "spec", sec))
            continue
        if r.kind not in KINDS or not r.owner or not r.where:
            bad.append(F("G-DECK", f"{where} kind / owner / where", "spec", sec))
        if len(r.keys) != len(r.strings) or not r.strings:
            bad.append(
                F("G-DECK", f"{where} {len(r.keys)} keys for {len(r.strings)} strings", "spec", sec)
            )
        for k in r.keys:
            if not k.startswith(DECK_NS[r.sub]):
                bad.append(F("G-DECK", f"{where} {k} is outside its namespace", "spec", sec))
        src = [base_line(cid, n) for cid, n in refs]
        for s in r.strings:
            if not any(s in ln for ln in src):
                bad.append(F("G-DECK", f"{where} {s[:50]!r} is not on {r.source}", "spec", sec))
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        bad.append(F("G-DECK", f"duplicate keys {dup[:3]}", "spec", spec_sec(t, "6. The copy")))
    return bad


def g_deck_json(t: Texts) -> list[Finding]:
    """BQ-15: the JSON twin equals the spec's tables (written by `--fill`)."""
    if t.deck != deck_json(t.spec):
        return [F("G-DECK-JSON", f"{DECK_REL} differs from the spec's tables", None, None)]
    return []


def g_frozen(t: Texts) -> list[Finding]:
    """BQ-17 (OWNER, early-ruled): the nine frozen strings, each verbatim on its source line, each
    row 'freeze PROPOSED, owner approval pending (#2701)' with its string's own status, each with
    its pinning test; a rewording routes to design + security review (E36-X01, #948)."""
    sec = spec_sec(t, FROZEN_HEAD)
    rows = frozen_rows(t.spec)
    bad: list[Finding] = []
    if [r[0] for r in rows] != list(FROZEN_STATUS):
        bad.append(F("G-FROZEN", f"the rows read {[r[0] for r in rows]}", "spec", sec))
    others = [(d, s) for d in deck_rows(t.spec) if d.sub != "7" for s in d.strings]
    for r in rows:
        if len(r) != 8:
            bad.append(F("G-FROZEN", f"{r[0]}: {len(r)} cells", "spec", sec))
            continue
        line = cites_in(r[4])
        for s in re.findall(r'"([^"]*)"', r[1]):
            # BQ-15: a source line's string is keyed once; a frozen one never again in a key
            # that cites the same line (a template sentence that ends with FS-4 is its own line)
            for d, o in others:
                if s in o and set(line) & set(cites_in(d.source)):
                    where = h2_at(t.spec, d.line)
                    bad.append(F("G-FROZEN", f"{r[0]}: keyed twice (spec:{d.line})", "spec", where))
        if r[0] == "FS-3" and "pending D05-G5" not in r[5]:
            bad.append(F("G-FROZEN", "FS-3: its test is not marked pending D05-G5", "spec", sec))
        text = re.findall(r'"([^"]*)"', r[1])
        refs = cites_in(r[4])
        if len(text) != 1 or len(refs) != 1 or text[0] not in base_line(*refs[0]):
            bad.append(F("G-FROZEN", f"{r[0]}: the string is not verbatim at {r[4]}", "spec", sec))
        if FREEZE not in r[3] or not r[3].startswith(FROZEN_STATUS.get(r[0], "?")):
            bad.append(F("G-FROZEN", f"{r[0]}: the status reads {r[3][:60]!r}", "spec", sec))
        if not r[5].startswith(f"`frozen:{r[0]}`"):
            bad.append(F("G-FROZEN", f"{r[0]}: no pinning test", "spec", sec))
    body = norm_text(section(t.spec, FROZEN_HEAD))
    for n in ("design and security review, routed to e36 x01's lane (#948)", "byte for byte"):
        if n not in body:
            bad.append(F("G-FROZEN", f"§7 lacks {n!r}", "spec", sec))
    return bad


def g_contrast(t: Texts) -> list[Finding]:
    """Every pair the frozen strings sit on clears 4.5:1 (text) in dark, light and hc."""
    sec = spec_sec(t, FROZEN_HEAD)
    bad: list[Finding] = []
    for r in frozen_rows(t.spec):
        cell = r[6] if len(r) > 6 else ""
        m = re.match(r"`color\.([a-z.-]+)` on `color\.([a-z.-]+)`", cell)
        if not m:
            if not cell.startswith("— (") or "D05-G5" not in cell:
                bad.append(F("G-CONTRAST", f"{r[0]}: no pair", "spec", sec))
            continue
        for th in THEMES:
            key = f"CONTRAST:{th}:{m[1]}/{m[2]}"
            if key not in "".join(ANCHOR.findall(cell)) + "".join(PLACEHOLDER.findall(cell)):
                bad.append(F("G-CONTRAST", f"{r[0]}: {th} not measured", "spec", sec))
                continue
            ratio = contrast(hex_of(th, f"color.{m[1]}"), hex_of(th, f"color.{m[2]}"))
            if ratio < 4.5:
                bad.append(F("G-CONTRAST", f"{r[0]}: {th} {show_ratio(ratio)} < 4.5", "spec", sec))
    return bad


def g_contract(t: Texts) -> list[Finding]:
    """BQ-18: every operation sits at its cited `22` line; the gaps are G-rows; contract first."""
    sec = spec_sec(t, CONTRACT_HEAD)
    bad: list[Finding] = []
    named: list[str] = []
    for r in table_rows(section(t.spec, CONTRACT_HEAD)):
        ops = re.findall(r"`([a-zA-Z]+)`", r[0])
        lines = [n for cid, n in cites_in(r[1]) if cid == "22"]
        named += ops
        if len(ops) != len(lines):
            bad.append(F("G-CONTRACT", f"{r[0]}: {len(ops)} ops, {len(lines)} lines", "spec", sec))
            continue
        for op, n in zip(ops, lines, strict=True):
            if f"operationId: {op}" not in base_line("22", n):
                bad.append(F("G-CONTRACT", f"{op} is not at `22`:{n}", "spec", sec))
        if r[3] != "present":
            bad.append(F("G-CONTRACT", f"{r[0]}: status {r[3]!r}", "spec", sec))
    if sorted(named) != sorted(OPS):
        bad.append(F("G-CONTRACT", f"the operations read {named}", "spec", sec))
    body = section(t.spec, CONTRACT_HEAD)
    for g in ("D03-G1", "D02-G10", "D02-G13", "D02-G5", "D03-G17", "D03-G16", "D03-G9", "C-6.1"):
        if g not in body:
            bad.append(F("G-CONTRACT", f"§9 does not name {g}", "spec", sec))
    if "E36-S06's own interface-first PR" not in body:
        bad.append(F("G-CONTRACT", "§9 lacks the contract-first PR", "spec", sec))
    return bad


g_diag = require(
    "G-DIAG",
    DIAG_HEAD,
    (
        "`anchor` from the form model's row ids by mapping `path`",
        "`id` from `path` + `code` (PROPOSED)",
        "`severity: info` never arrives from the validator and is client-only (PROPOSED)",
        "`fixHint` is the designed primary line",
        "the validator `message` goes in the details disclosure",
        "The validator is the single source of truth",
    ),
)


def g_motion(t: Texts) -> list[Finding]:
    """BQ-14 (confirmed): D03 §10 + D03H Table 4 are the record; the four conflicting rows are
    C-rows with PROPOSED replacements; reduce twins are the instant end state."""
    sec = spec_sec(t, MOTION_HEAD)
    rows = table_rows(section(t.spec, MOTION_HEAD))
    got = {m[1]: r[3] for r in rows if (m := re.match(r"(\d+) \(", r[0]))}
    bad: list[Finding] = []
    if got != MOTION_CONFLICTS:
        bad.append(F("G-MOTION", f"the conflict rows read {got}", "spec", sec))
    for r in rows:
        if len(r) != 4 or not r[2]:
            bad.append(F("G-MOTION", f"{r[0]}: no PROPOSED replacement", "spec", sec))
    body = norm_text(section(t.spec, MOTION_HEAD))
    for n in (
        "d03 §10 (d03:181\u2013202) and d03h table 4 (d03h:65\u201382) are the motion record",
        "every reduce twin is the instant end state",
        "never an edit of d03",
    ):
        if norm_text(n) not in body:
            bad.append(F("G-MOTION", f"§11 lacks {n[:40]!r}", "spec", sec))
    return bad


def g_frow(t: Texts) -> list[Finding]:
    """BQ-25 (early-ruled): every D04 F-row once, its severity and line as D04 has them at the
    base, a corrected contract, a consumer and a close state (accepted or routed)."""
    sec = spec_sec(t, "12. E36-D04's")
    base = {cells[0]: (i, cells) for i, cells in d04_rows(r"F-\d\d")}
    rows = table_rows(section(t.spec, FROW_HEAD))
    bad: list[Finding] = []
    if [r[0] for r in rows] != list(base):
        bad.append(F("G-FROW", f"the ledger lists {[r[0] for r in rows][:4]}…", "spec", sec))
    for r in rows:
        if r[0] not in base or len(r) != 7:
            continue
        line, cells = base[r[0]]
        if r[1] != cells[2] or cites_in(r[3]) != [("D04", line)]:
            bad.append(F("G-FROW", f"{r[0]}: severity / line differ from D04:{line}", "spec", sec))
        if not r[4] or not r[5]:
            bad.append(F("G-FROW", f"{r[0]}: no contract / consumer", "spec", sec))
        state = r[6]
        want = "routed — " if r[0] in ROUTED_F else "accepted — supersedes"
        if not state.startswith(want):
            bad.append(F("G-FROW", f"{r[0]}: close state {state[:40]!r}", "spec", sec))
    return bad


def g_al(t: Texts) -> list[Finding]:
    """BQ-27 (confirmed): AL-01 … AL-40 once each by reference, their first words as D04 has them
    at the base; the hash anchor; the pack never adds an AL row."""
    sec = spec_sec(t, AL_HEAD)
    base = [(cells[0], cells[1]) for _i, cells in d04_rows(r"AL-\d\d")]
    rows = table_rows(section(t.spec, AL_HEAD))
    bad: list[Finding] = []
    ids: list[str] = []
    frags: list[str] = []
    for r in rows:
        m = re.fullmatch(r"AL-(\d\d) … AL-(\d\d)", r[0])
        if not m:
            bad.append(F("G-AL", f"{r[0]}: not an id range", "spec", sec))
            continue
        ids += [f"AL-{n:02d}" for n in range(int(m[1]), int(m[2]) + 1)]
        frags += re.findall(r'"([^"]*)"', r[1])
    if ids != [b[0] for b in base] or len(frags) != len(base):
        bad.append(
            F("G-AL", f"{len(ids)} ids / {len(frags)} words for {len(base)} rows", "spec", sec)
        )
    else:
        for (aid, crit), frag in zip(base, frags, strict=True):
            if not norm_text(crit).lstrip('"').startswith(norm_text(frag)):
                bad.append(F("G-AL", f"{aid}: {frag[:30]!r} is not its first words", "spec", sec))
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if re.search(r"\bAL-(?:4[1-9]|[5-9]\d)\b", line):
                bad.append(F("G-AL", f"{doc}:{i} an AL row beyond D04's", doc, h2_at(text, i)))
    if "HASH:d04.al" not in "".join(ANCHOR.findall(t.spec) + PLACEHOLDER.findall(t.spec)):
        bad.append(F("G-AL", "§13 carries no hash of D04 §16", "spec", sec))
    return bad


def event_names() -> set[str]:
    """The events `14` names for the five screens and the keys the manager writes (D03:20)."""
    names: set[str] = set()
    for n in (1793, 1839, 1895, 1987, 1996):
        line = base_line("14", n)
        names |= set(re.findall(r"rule\.[a-z_]+", line))
        for m in re.finditer(r"`rule\.((?:[a-z_]+\|)+[a-z_]+)`", line):
            names |= {f"rule.{x}" for x in m[1].split("|")}
    names |= set(re.findall(r"`(rule\.[a-z_]+)`", base_line("D03", 20)))
    return names


REASON_KEY = re.compile(
    r"rule\.(?:arm|save|disarm|delete)\.[a-z_]+|rule\.(?:quarantined|system_protected)"
)


def g_events(t: Texts) -> list[Finding]:
    """BQ-29: every `rule.*` event named exists in `14` or in the manager's keys; the two names no
    code writes carry D05-C9; nothing is invented."""
    known = event_names()
    bad: list[Finding] = []
    skip = set(section(t.spec, MUTATION_HEAD).split("\n"))
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if doc == "spec" and line in skip and line.startswith("|"):
                continue
            for name in re.findall(r"`(rule\.[a-z_.]+)", line):
                if REASON_KEY.fullmatch(name) or name.startswith("rule.editor"):
                    continue
                if name.rstrip(".") not in known:
                    bad.append(F("G-EVENTS", f"{doc}:{i} {name} is no event", doc, h2_at(text, i)))
    row = next(
        (r for r in table_rows(section(t.spec, EVENTS_HEAD)) if "`rule.exported`" in r[0]), None
    )
    if row is None or "written by no code" not in row[4] or "D05-C9" not in row[4]:
        bad.append(
            F("G-EVENTS", "rule.exported / imported not marked", "spec", spec_sec(t, EVENTS_HEAD))
        )
    return bad


def g_log(t: Texts) -> list[Finding]:
    """BQ-30, AC1: the log carries every upstream open id and the pack's own rows exactly once,
    each row with an owner lane (never an agent), a consumer issue and its sprint start."""
    sec = spec_sec(t, LOG_HEAD)
    want = upstream_ids() + own_rows(t.spec)
    bad: list[Finding] = []
    got: list[str] = []
    for r in log_rows(t.spec):
        if len(r) != 5:
            bad.append(F("G-LOG", f"{r[0][:20]}: {len(r)} cells", "spec", sec))
            continue
        got += log_ids(r[0])
        if not r[2] or re.search(r"worker|agent|orchestrator", r[2], re.IGNORECASE):
            bad.append(F("G-LOG", f"{r[0][:20]}: owner lane {r[2]!r}", "spec", sec))
        m = re.fullmatch(r"(E36-[A-Z]\d\d) \(#(\d+)\)", r[3])
        due = re.findall(r"DATE:(E36-[A-Z]\d\d)", r[4])
        if not m or ISSUES.get(m[1]) != m[2] or due != [m[1]]:
            bad.append(F("G-LOG", f"{r[0][:20]}: consumer / due {r[3]!r}", "spec", sec))
    missing = [x for x in want if x not in got]
    extra = sorted({x for x in got if got.count(x) > 1 or x not in want})
    if missing or extra:
        bad.append(F("G-LOG", f"missing {missing[:4]}, extra {extra[:4]}", "spec", sec))
    return bad


def g_consumers(t: Texts) -> list[Finding]:
    """BQ-32: one row per consumer with its issue and an exit check."""
    sec = spec_sec(t, CONSUMER_HEAD)
    rows = table_rows(section(t.spec, CONSUMER_HEAD))
    got = [r[0] for r in rows]
    want = [f"{k} (#{ISSUES[k]})" for k in CONSUMERS]
    bad: list[Finding] = []
    if got != want:
        bad.append(F("G-CONSUMERS", f"the consumers read {got[:3]}…", "spec", sec))
    bad += [
        F("G-CONSUMERS", f"{r[0]}: no exit check", "spec", sec)
        for r in rows
        if len(r) > 2 and not r[2]  # a short row is G-CELLS's, never a crash here
    ]
    return bad


def g_crows(t: Texts) -> list[Finding]:
    """BQ-36: D05-C1 … D05-C20 in order, each with its contradiction and reading."""
    sec = spec_sec(t, "21. Rows")
    rows = table_rows(section(t.spec, CROW_HEAD))
    bad: list[Finding] = []
    if [r[0] for r in rows] != [f"D05-C{n}" for n in range(1, 21)]:
        bad.append(F("G-CROWS", f"the C-rows read {[r[0] for r in rows][-3:]}", "spec", sec))
    bad += [F("G-CROWS", f"{r[0]}: empty cell", "spec", sec) for r in rows if not all(r[:3])]
    return bad


def last_commit(rel: str) -> str:
    return git_out("log", "-1", "--format=%H", BASE, "--", rel).strip()[:10]


def g_version(t: Texts) -> list[Finding]:
    """BQ-33 (PROPOSED): the version line pins each input at the last commit touching it at the
    base; a merged change after it is drift."""
    sec = spec_sec(t, VERSION_HEAD)
    body = section(t.spec, VERSION_HEAD)
    bad: list[Finding] = []
    m = re.search(r"\*\*Version line:\*\* v1 at base `([0-9a-f]+)`(.*?)\(.*?PROPOSED\)", body)
    if not m or m[1] != BASE:
        return [F("G-VERSION", "the version line is not 'v1 at base' with PROPOSED", "spec", sec)]
    pins = re.findall(r"((?:D0\dH?|the memo)(?: and D0\dH)?) at `([0-9a-f]{10})`", m[2])
    want = {
        "D02": "D02",
        "D02H": "D02H",
        "D03": "D03",
        "D03H": "D03H",
        "D04": "D04",
        "the memo": "MEMO",
    }
    seen: set[str] = set()
    for names, sha in pins:
        for nm in names.split(" and "):
            seen.add(nm)
            if last_commit(CITE_FILES[want[nm]]) != sha:
                bad.append(
                    F("G-VERSION", f"{nm} pinned at {sha}, last touched elsewhere", "spec", sec)
                )
    if seen != set(want):
        bad.append(F("G-VERSION", f"the version line pins {sorted(seen)}", "spec", sec))
    # BQ-33: a late change is a merged change to a pinned input (or the boards) after its sha
    for rel in [CITE_FILES[w] for w in want.values()] + ["docs/design/E36/img/"]:
        at_head = head_commit(rel)
        if at_head and at_head != last_commit(rel):
            bad.append(
                F("G-VERSION", f"{rel} changed at {HEAD} ({at_head}): a late change", "spec", sec)
            )
    if head_al_hash() not in ("", al_hash()):
        bad.append(F("G-VERSION", f"D04 \u00a716's hash differs at {HEAD}", "spec", sec))
    return bad


def storybook_names(n: int) -> list[str]:
    line = base_line("15", n).split("**Storybook**:", 1)[1]
    line = line.replace("**E36-D03 —**", "").strip()
    line = re.split(r" \(", line)[0].rstrip(".")
    return [x.strip() for x in line.split(",")]


def a_rows(hand: str) -> dict[str, list[str]]:
    return {r[0]: r for r in table_rows(section(hand, OLD_HEAD)) if r[0].startswith("A-")}


def a15_names(hand: str) -> list[str]:
    new = a_rows(hand).get("A-15", ["", "", "", ""])[3]
    m = re.search(r"PROPOSED: ([A-Za-z, ]+)\.", new)
    return [x.strip() for x in m[1].split(",")] if m else []


def a18_names(hand: str) -> list[str]:
    new = a_rows(hand).get("A-18", ["", "", "", ""])[3]
    m = re.search(r"PROPOSED for SCR-088: ([A-Za-z, ]+) \(", new)
    return [x.strip() for x in m[1].split(",")] if m else []


def g_story(t: Texts) -> list[Finding]:
    """BQ-12: §D's lists equal `15`'s Storybook lines at the base; CMP-243's is A-15's."""
    sec = hand_sec(t, "§D Storybook")
    bad: list[Finding] = []
    for r in table_rows(section(t.hand, "§D Storybook")):
        cell, _, added = r[1].partition("; A-18 adds ")
        refs = cites_in(cell)
        names = [x.strip() for x in re.sub(r"\s*\([^()]*\)$", "", cell).split(",")]
        if r[0] == "CMP-240":
            extra = [x.strip() for x in added.removesuffix(" (PROPOSED)").split(",")]
            if not added.endswith("(PROPOSED)") or extra != a18_names(t.hand):
                bad.append(F("G-STORY", "CMP-240: not A-18's proposal", "hand", sec))
        if r[0] == "CMP-243":
            if refs or "A-15, PROPOSED" not in r[1] or names != a15_names(t.hand):
                bad.append(F("G-STORY", "CMP-243: not A-15's proposal", "hand", sec))
        elif len(refs) != 1 or "**Storybook**" not in base_line(*refs[0]):
            bad.append(F("G-STORY", f"{r[0]}: no Storybook line cited", "hand", sec))
        elif names != storybook_names(refs[0][1]):
            bad.append(F("G-STORY", f"{r[0]}: the stories differ from `15`", "hand", sec))
    return bad


def g_props(t: Texts) -> list[Finding]:
    """BQ-10: every prop §B.1 names is on the cited `15` Props line at the base."""
    sec = hand_sec(t, "§B The contract")
    bad: list[Finding] = []
    rows = table_rows(section(t.hand, "§B.1 Props"))
    if [r[0] for r in rows] != [*CONTRACT_CMPS, *NEW_CMPS]:
        bad.append(F("G-PROPS", "the rows are not the fifteen components", "hand", sec))
    for r in rows:
        refs = [x for x in cites_in(r[1]) if x[0] == "15"]
        props = [p for p in re.findall(r"`([a-zA-Z0-9]+)`", r[1]) if not p.isdigit()]
        if r[0] in NEW_CMPS:
            arow, n = NEW_CMPS[r[0]]
            if (
                refs != [("15", n)]
                or TBD not in base_line("15", n)
                or f"{arow} (PROPOSED)" not in r[1]
            ):
                bad.append(F("G-PROPS", f"{r[0]}: not `15`'s TBD with its A-row", "hand", sec))
            continue
        if len(refs) != 1 or "**Props**" not in base_line(*refs[0]):
            bad.append(F("G-PROPS", f"{r[0]}: no Props line cited", "hand", sec))
            continue
        line = base_line(*refs[0])
        for p in props:
            if not re.search(rf"`{p}\b", line):
                bad.append(F("G-PROPS", f"{r[0]}: `{p}` is not on `15`:{refs[0][1]}", "hand", sec))
    return bad


def scr_of(n: int) -> str:
    """The SCR block of `14` that holds line n."""
    cur = ""
    for i, ln in enumerate(plan("14").split("\n"), 1):
        m = re.match(r"^### (SCR-\d{3})", ln)
        if m:
            cur = m[1]
        if i == n:
            return cur
    return ""


def g_arow(t: Texts) -> list[Finding]:
    """BQ-3 (with D05-C19): A-1 … A-5 are the five `14` pointer lines after the last Design line
    of each screen's block, one New text; BQ-9: A-6 … A-17 fill every field `15` leaves "TBD
    (E36-D05 #947)" on CMP-240 and CMP-243, each Old verbatim on its line at the base."""
    sec = hand_sec(t, OLD_HEAD)
    rows = a_rows(t.hand)
    bad: list[Finding] = []
    want = [*A_ROW_LINES, *(f"A-{n}" for n in range(6, 19))]
    if list(rows) != want:
        bad.append(F("G-AROW", f"the A-rows read {list(rows)[:3]}…", "hand", sec))
    news = set()
    for aid, n in A_ROW_LINES.items():
        r = rows.get(aid, ["", "", "", ""])
        ok = f"after `14`:{n}" in r[1] and scr_of(n) in r[1] and r[2] == "—"
        if not ok or not re.match(r"- \*\*(?:Design|A11y review)", base_line("14", n)):
            bad.append(F("G-AROW", f"{aid}: target {r[1]!r}", "hand", sec))
        news.add(r[3])
    if len(news) != 1 or "[E36-D05.md](../design/E36/E36-D05.md) v1" not in "".join(news):
        bad.append(F("G-AROW", "the five New cells differ", "hand", sec))
    tbd = [
        i
        for i in range(TBD_SPAN[0], TBD_SPAN[1] + 1)
        if TBD in base_line("15", i) and not base_line("15", i).startswith("| ")
    ]
    covered: list[int] = []
    a18 = rows.get("A-18", ["", "", "", ""])
    old18 = re.findall(r'"([^"]*)"', a18[2])
    if (
        cites_in(a18[1]) != [("15", A18_LINE)]
        or len(old18) != 1
        or old18[0] not in base_line("15", A18_LINE)
        or not a18[3].startswith(f'"{old18[0].rstrip(".")}; PROPOSED')
    ):
        bad.append(
            F("G-AROW", "A-18: not `15`'s Storybook line with SCR-088's stories", "hand", sec)
        )
    for aid in want[5:-1]:
        r = rows.get(aid, ["", "", "", ""])
        refs = cites_in(r[1])
        old = re.findall(r'"([^"]*)"', r[2])
        if len(refs) != 1 or refs[0][0] != "15" or len(old) != 1:
            bad.append(F("G-AROW", f"{aid}: no single `15` line or Old", "hand", sec))
            continue
        covered.append(refs[0][1])
        if old[0] not in base_line(*refs[0]) or TBD not in old[0]:
            bad.append(F("G-AROW", f"{aid}: Old is not verbatim on `15`:{refs[0][1]}", "hand", sec))
        if not r[3] or TBD in r[3]:
            bad.append(F("G-AROW", f"{aid}: no New text", "hand", sec))
    if sorted(covered) != tbd:
        bad.append(F("G-AROW", f"the TBD fields {tbd} are not covered once each", "hand", sec))
    return bad


TOKEN_NAME = re.compile(
    r"`((?:color|space|radius|opacity|elevation|size|type|border|motion)\.[a-z0-9.*-]+)`"
)


def g_token(t: Texts) -> list[Finding]:
    """Every token named resolves, or is the PROPOSED alias of D03:177."""
    names = all_token_names()
    bad: list[Finding] = []
    skip = set(section(t.spec, MUTATION_HEAD).split("\n"))
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if doc == "spec" and line in skip and line.startswith("|"):
                continue
            for name in TOKEN_NAME.findall(line):
                if name not in names and name not in PROPOSED_TOKENS:
                    msg = f"{doc}:{i} {name} does not resolve"
                    bad.append(F("G-TOKEN", msg, doc, h2_at(text, i)))
    return bad


@functools.lru_cache(maxsize=1)
def merge_base() -> str:
    return git_out("merge-base", "HEAD", "origin/main").strip()


def fork_point() -> str:
    """The commit this branch forked from main (`git merge-base HEAD origin/main`), else BASE: the
    untouched files move on main under other PRs, so the working tree is compared with the fork
    point, never with a fixed sha that main has left."""
    return merge_base() or BASE


@functools.lru_cache(maxsize=1)
def stray_paths() -> tuple[str, ...]:
    """Paths changed against the fork point that are not this ticket's own."""
    ref = fork_point()
    names = git_out("diff", "--name-only", ref).split("\n")
    names += git_out("ls-files", "--others", "--exclude-standard").split("\n")
    own = (*OWN_PATHS, plan_rel(POINTER_PLAN))
    return tuple(sorted({n for n in names if n and n not in own}))


def pointer_lines(hand: str) -> str:
    """A-1's New text: the one pointer line this PR adds under each of the five screens."""
    new = a_rows(hand).get("A-1", ["", "", "", ""])[3]
    m = re.fullmatch(r'"(.*)"', new)
    return m[1] if m else ""


def with_pointers(fork: str, hand: str) -> str | None:
    """`14` at the fork point with A-1 … A-5's line after each target line (BQ-3), else None."""
    lines = fork.split("\n")
    out: list[str] = []
    want = [base_line("14", n) for n in A_ROW_LINES.values()]
    for ln in lines:
        out.append(ln)
        if want and ln == want[0]:
            out.append(pointer_lines(hand))
            want.pop(0)
    return None if want else "\n".join(out)


def g_untouched(t: Texts) -> list[Finding]:
    """R-2, BQ-3, BQ-9: the untouched files equal the fork point, `14` but for the five pointer
    lines of A-1 … A-5 (AC4: linked), which it must carry; no other path differs."""
    bad: list[Finding] = []
    ref = fork_point()
    for nn, text in t.plans:
        rel = cite_path(nn)
        fork = git_show(ref, rel) if rel else None
        fork = fork if fork is not None else (at_base(rel) if rel else None)
        want = with_pointers(fork, t.hand) if fork is not None and nn == POINTER_PLAN else fork
        if rel is None or text != want:
            what = "but for its five pointer lines " if nn == POINTER_PLAN else ""
            bad.append(
                F("G-UNTOUCHED", f"`{nn}` differs from {ref[:10]} {what}".strip(), None, None)
            )
    bad += [F("G-UNTOUCHED", f"{p} is not this ticket's path", None, None) for p in stray_paths()]
    return bad


def g_budget(t: Texts) -> list[Finding]:
    """The spec within SPEC_LINE_BUDGET lines, the hand-off within HAND_LINE_BUDGET."""
    bad: list[Finding] = []
    for doc, text, cap in (("spec", t.spec, SPEC_LINE_BUDGET), ("hand", t.hand, HAND_LINE_BUDGET)):
        n = text.count("\n") + (0 if text.endswith("\n") else 1)
        if n > cap:
            last = h2_at(text, len(text.split("\n")))
            bad.append(F("G-BUDGET", f"the {doc} has {n} lines > {cap}", doc, last))
    return bad


g_walk_text = require(
    "G-WALK",
    WALK_HEAD,
    (
        "No session took place and none is claimed",
        "E36-T01, E36-S01 … E36-S06, E36-Q01, E36-Q03, E36-Q04, E36-D06",
        (
            "its result table (date · role · needs listed · found · not found) is the written "
            "confirmation"
        ),
        "every state row of §2 has an observable outcome",
        "at most ten items, posted on #947",
    ),
)
WALK_DATE = "2026-10-27"
WALK_ROLES = tuple(k for k in CONSUMERS if k != "E36-X01")  # §17 item 1's protocol list
DOD_HEAD = "22.1 DoD"
DOD_WALK = "Walkthrough recorded and engineers' written confirmation"


def walk_targets_ok(t: Texts, cell: str) -> list[str]:
    """Each "→ target" of a disposition names a pack section that exists (spec §n, hand-off §X)
    or a G- / Q-row of §21.2; returns the targets that do not resolve."""
    own = set(own_rows(t.spec))
    bad: list[str] = []
    for m in re.finditer(r"→ (hand-off §[A-F]|§\d+(?:\.\d+)?|D05-[GQ]\d+)", cell):
        x = m[1]
        if x.startswith("D05-"):
            ok = x in own
        elif x.startswith("hand-off"):
            ok = bool(section(t.hand, x.removeprefix("hand-off ") + " "))
        else:
            ok = bool(section(t.spec, x[1:] + (" " if "." in x else ". ")))
        if not ok:
            bad.append(x)
    return bad


def g_walk_record(t: Texts) -> list[Finding]:
    """BQ-31 (b), (c): §17 records the story-role dry run (one row per consumer of the protocol)
    and the QA pass over §2's state rows; counts add up, every not-found has a disposition that
    resolves (a fold into a pack section or a G- / Q-row), and §22.1's box is ticked exactly when
    the record is complete."""
    sec = spec_sec(t, WALK_HEAD)
    rows = table_rows(section(t.spec, WALK_HEAD))
    bad: list[Finding] = []
    story = [r for r in rows if len(r) == 6 and r[1].startswith("story: ")]
    qa = [r for r in rows if len(r) == 6 and r[1].startswith("QA: ")]
    roles = [r[1].removeprefix("story: ") for r in story]
    want = [f"{k} (#{ISSUES[k]})" for k in WALK_ROLES]
    if roles != want:
        bad.append(
            F("G-WALK", f"the dry-run rows read {roles[:3]}…, not the protocol's", "spec", sec)
        )
    # the count G-ANCHOR re-derives (frozen under --self-test, so a dropped frame is G-FRAME's)
    if len(qa) != 1 or not qa[0][2].isdigit() or qa[0][2] != t.values.get("COUNT:frames.total"):
        bad.append(F("G-WALK", "no QA row over every state row of §2", "spec", sec))
    for r in story + qa:
        nums = r[2:5]
        if r[0] != WALK_DATE or not all(n.isdigit() for n in nums):
            bad.append(F("G-WALK", f"{r[1]}: date or counts", "spec", sec))
            continue
        need, found, missing = (int(n) for n in nums)
        if need != found + missing:
            bad.append(F("G-WALK", f"{r[1]}: {need} needs != {found} + {missing}", "spec", sec))
        arrows = r[5].count("→")
        if (missing and arrows != missing) or (not missing and r[5] != "—"):
            bad.append(
                F("G-WALK", f"{r[1]}: {missing} not found, {arrows} dispositions", "spec", sec)
            )
        left = walk_targets_ok(t, r[5])
        if left:
            bad.append(
                F("G-WALK", f"{r[1]}: disposition {left[0]!r} does not resolve", "spec", sec)
            )
    dod = [ln for ln in section(t.spec, DOD_HEAD).split("\n") if DOD_WALK in ln]
    ticked = len(dod) == 1 and dod[0].startswith("- [x] ")
    if ticked == bool(bad) or len(dod) != 1:
        dsec = spec_sec(t, DOD_HEAD)
        what = "ticked over an incomplete record" if ticked else "unticked"
        bad.append(F("G-WALK", f"§22.1's written-confirmation box is {what}", "spec", dsec))
    return bad


g_walk = both(g_walk_text, g_walk_record)
g_split_req = require(
    "G-SPLIT",
    "0.3 The boundary",
    ("E35-D05 (#940) owns SCR-084 … SCR-087 and E35-D03's SCR-088 / SCR-089 deltas",),
)
g_paths = require(
    "G-PATHS",
    "22.2 Deviations",
    (
        "Branch `design/e36-d05-rule-form-handoff`",
        "`docs(rule-engine): E36-D05 rule-form-editor engineering hand-off pack`",
    ),
)
g_announce = require(
    "G-ANNOUNCE",
    "12.2 D04's open",
    (
        "assertive once, for `mismatch` only",
        'D03\'s wording, "Condition 2 of 4 moved up"',
        "Q-01** (`Alt+Shift+↑/↓` and an OS layout switch) stays open",
    ),
)
g_hooks = require(
    "G-HOOKS", "§E Test hooks", ("PROPOSED: the specs are silent", "No `data-testid`"), doc="hand"
)
g_signoff_req = require(
    "G-SIGNOFF",
    VERSION_HEAD,
    ('recorded "owner approval pending (#2701)"', "the standing arrangement"),
)


def g_announce_marks(t: Texts) -> list[Finding]:
    """BQ-16, BQ-26, F-04, F-05: the marks the names and live-data tables fix; every string of
    kind `announce` is polite."""
    sec = spec_sec(t, "6. The copy")
    marks: dict[str, str] = {}
    bad: list[Finding] = []
    for r in deck_rows(t.spec):
        got = announce_marks(r) or {}
        marks.update(got)
        if r.kind == "announce" and any(v != "polite" for v in got.values()):
            bad.append(F("G-ANNOUNCE", f"spec:{r.line} an announcement not polite", "spec", sec))
    for k, want in ANNOUNCE_FIXED.items():
        if marks.get(k) != want:
            bad.append(F("G-ANNOUNCE", f"{k} is {marks.get(k)!r}, not {want!r}", "spec", sec))
    return bad


def g_arm(t: Texts) -> list[Finding]:
    """BQ-23, BQ-16: §8.3's gate kinds; a missing live step-up is never a reason to disable; the
    refusal row lists exactly D02:188's 403 and 422 codes."""
    sec = spec_sec(t, "8. The editor")
    rows = {r[0]: r for r in table_rows(section(t.spec, "8.3 Arm and disarm")) if len(r) == 4}
    bad: list[Finding] = []
    for sit, kind in ARM_GATES.items():
        if sit not in rows or rows[sit][1] != kind:
            bad.append(F("G-ARM", f"{sit}: gate kind {rows.get(sit, ['', '?'])[1]!r}", "spec", sec))
    if not rows.get("live step-up missing", ["", "", ""])[2].startswith(
        "never a reason to disable"
    ):
        bad.append(F("G-ARM", "the live step-up is a reason to disable", "spec", sec))

    def codes(text: str) -> tuple[list[str], list[str]]:
        text = text.split("(`arming.py`")[0]
        head, _, tail = text.partition("422 ")
        head = head.split("403 ", 1)[-1]
        return re.findall(r"`([a-z_]+)`", head), re.findall(r"`([a-z_]+)`", tail)

    want = codes(base_line("D02", 188).split("(ii)", 1)[-1])
    got = codes(rows.get("refusal at the point of action", ["", "", ""])[2])
    if got != want:
        bad.append(F("G-ARM", f"the refusal codes read {got}, D02:188 has {want}", "spec", sec))
    return bad


def table_blocks(text: str) -> list[tuple[int, list[str]]]:
    """Every table: (its first line, its lines), outside fences."""
    lines = text.split("\n")
    fence = fenced(lines)
    out: list[tuple[int, list[str]]] = []
    cur: list[str] = []
    start = 0
    for i, ln in enumerate([*lines, ""]):
        if i < len(lines) and not fence[i] and re.match(r"^ {0,3}\|", ln):
            if not cur:
                start = i + 1
            cur.append(ln)
        elif cur:
            out.append((start, cur))
            cur = []
    return out


def g_cells(t: Texts) -> list[Finding]:
    """Every table row has its header's cell count (an escaped pipe never merges two cells)."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for start, block in table_blocks(text):
            width = len(split_row(block[0], keep_escapes=True))
            for k, ln in enumerate(block):
                n = len(split_row(ln, keep_escapes=True))
                if n != width and not is_rule(ln):
                    msg = f"{doc}:{start + k} {n} cells, its header {width}"
                    bad.append(F("G-CELLS", msg, doc, h2_at(text, start + k)))
    return bad


def g_heads(t: Texts) -> list[Finding]:
    """A heading's level follows its number: `N.` and `§X` are `##`, `N.M` and `§X.n` are `###`;
    the title is the one `#`; every other heading is `##`."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        lines = text.split("\n")
        fence = fenced(lines)
        for i, ln in enumerate(lines):
            m = HEADING.match(ln)
            if not m or fence[i]:
                continue
            num = re.match(r"(§[A-F]|\d+)((?:\.\d+)*)[. ]", m[2])
            want = 2 + num[2].count(".") if num else (1 if i == 0 else 2)
            if len(m[1]) != want:
                msg = f"{doc}:{i + 1} a level-{len(m[1])} heading, its number says {want}"
                bad.append(F("G-HEADS", msg, doc, h2_at(text, i + 1)))
    return bad


def frozen_status_ids(spec: str) -> list[str]:
    return [r[0] for r in frozen_rows(spec)]


def g_gherkin(t: Texts) -> list[Finding]:
    """T AC1 (lens M1): every consuming story's Gherkin scenario, verbatim and in order, points at
    a pack row, key, F-, FS-, C- or G-row that exists."""
    sec = spec_sec(t, "Acceptance-criteria trace")
    rows = {r[0]: r for r in table_rows(section(t.spec, "Acceptance-criteria trace"))}
    keys = [k for d in deck_rows(t.spec) for k in d.keys]
    heads = set(re.findall(r"^#{2,6} (\d+(?:\.\d+)?)[. ]", t.spec, MULTI))
    known = set(own_rows(t.spec)) | set(a_rows(t.hand)) | set(frozen_status_ids(t.spec))
    known |= {r[0] for r in table_rows(section(t.spec, CROW_HEAD))}
    known |= {r[0] for r in table_rows(section(t.spec, FROW_HEAD))}
    known |= set(re.findall(r"^- \*\*(R-\d)\b", section(t.spec, "1.2 Rules stated once"), MULTI))
    bad: list[Finding] = []
    for story, titles in scenarios().items():
        r = rows.get(f"{story} (#{ISSUES[story]}) Gherkin")
        if r is None or len(r) < 2:
            bad.append(F("G-GHERKIN", f"{story}: no trace row", "spec", sec))
            continue
        pairs = re.findall(r'"([^"]+)" \u2192 (.+?)(?= \u00b7 "|$)', r[1])
        if [p[0] for p in pairs] != list(titles):
            bad.append(F("G-GHERKIN", f"{story}: the scenarios differ from E36.json", "spec", sec))
        for title, where in pairs:
            refs = re.findall(r"`([a-z_]+(?:\.[a-z_*]+)+)`", where)
            for k in refs:
                ok = k in keys or (k.endswith(".*") and any(x.startswith(k[:-1]) for x in keys))
                if not ok:
                    bad.append(F("G-GHERKIN", f"{title[:30]!r}: no key {k}", "spec", sec))
            ids = re.findall(r"\b(?:D0[2-5]-[CGQ]\d+|F-\d\d|FS-\d|AL-\d\d|R-\d|A-\d+)\b", where)
            for x in ids:
                al_ok = x.startswith("AL-") and 1 <= int(x[3:]) <= len(d04_rows(r"AL-\d\d"))
                upstream = x.startswith(("D02-", "D03-", "D04-")) and x in upstream_ids()
                if x not in known and not al_ok and not upstream:
                    bad.append(F("G-GHERKIN", f"{title[:30]!r}: no row {x}", "spec", sec))
            for s in re.findall(r"§(\d+(?:\.\d+)?)", where):
                if s not in heads:
                    bad.append(F("G-GHERKIN", f"{title[:30]!r}: no section §{s}", "spec", sec))
            if not (refs or ids or "§" in where):
                bad.append(F("G-GHERKIN", f"{title[:30]!r}: no pointer", "spec", sec))
    return bad


def g_route(t: Texts) -> list[Finding]:
    """D05-C10: SCR-080's F-rows name both E36-S02 and E36-S05, in §12.1 and in §18."""
    sec = spec_sec(t, "12. E36-D04's")
    bad: list[Finding] = []
    for r in table_rows(section(t.spec, FROW_HEAD)):
        if r[0] in LIST_F and (len(r) < 6 or "E36-S02" not in r[5] or "E36-S05" not in r[5]):
            bad.append(F("G-FROW", f"{r[0]}: consumer is not E36-S02 and E36-S05", "spec", sec))
    s05 = next(
        (r for r in table_rows(section(t.spec, CONSUMER_HEAD)) if r[0].startswith("E36-S05")), None
    )
    if s05 is None or len(s05) < 2 or any(f not in s05[1] for f in LIST_F):
        bad.append(F("G-FROW", "§18's E36-S05 row does not list SCR-080's F-rows", "spec", sec))
    return bad


# Self-test seams: the git state a mutation may stand in for (never set outside --self-test).
ENV: dict[str, object] = {}


def head_commit(rel: str) -> str:
    """The last commit touching `rel` at origin/main (a self-test mutation may override it)."""
    over = ENV.get("head_commit")
    if isinstance(over, dict) and rel in over:
        return str(over[rel])
    return git_out("log", "-1", "--format=%H", HEAD, "--", rel).strip()[:10]


def head_al_hash() -> str:
    over = ENV.get("head_al_hash")
    if isinstance(over, str):
        return over
    text = git_show(HEAD, CITE_FILES["D04"])
    if text is None:
        return ""
    rows = []
    for ln in text.split("\n"):
        if ln.startswith("|") and not is_rule(ln) and re.fullmatch(r"AL-\d\d", split_row(ln)[0]):
            rows.append(pin_norm(" | ".join(split_row(ln))))
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()[:12]


def branch_state() -> tuple[bool, int]:
    """(BASE is an ancestor of HEAD, commits on HEAD that origin/main lacks)."""
    over = ENV.get("branch_state")
    if isinstance(over, tuple):
        return bool(over[0]), int(over[1])
    base = git_out("rev-parse", BASE).strip()
    anc = bool(base) and git_out("merge-base", BASE, "HEAD").strip() == base
    ahead = git_out("rev-list", "--count", f"{HEAD}..HEAD").strip()
    return anc, int(ahead) if ahead.isdigit() else 0


def g_base(t: Texts) -> list[Finding]:
    """A branch that carries commits must contain BASE, so its PR base matches the pinned inputs
    (lens: the worktree predated #4735); an uncommitted tree on an older fork point passes."""
    anc, ahead = branch_state()
    if ahead and not anc:
        msg = f"HEAD carries {ahead} commits but lacks BASE {BASE}; rebase onto {HEAD}"
        return [F("G-BASE", msg, None, None)]
    return []


MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_trace,
    g_frame,
    g_penpot,
    g_redline,
    g_map,
    g_deck,
    g_deck_json,
    g_frozen,
    g_contrast,
    g_contract,
    g_diag,
    g_motion,
    g_frow,
    g_al,
    g_events,
    g_log,
    g_consumers,
    g_crows,
    g_version,
    g_story,
    g_props,
    g_arow,
    g_token,
    g_walk,
    g_split_req,
    g_paths,
    g_announce,
    g_hooks,
    g_signoff_req,
    g_announce_marks,
    g_arm,
    g_cells,
    g_heads,
    g_gherkin,
    g_route,
    g_base,
    g_untouched,
    g_budget,
)


# ---------------------------------------------------------------------------- the pins

PIN_DOCS: tuple[str, ...] = ("spec", "hand")  # every unit of both docs; no span is exempt
PIN_SENT = re.compile(r"s\d+")
Unit = tuple[str, str, str, str]  # (doc, region, loc, text)


def unvalued(line: str, values: Values) -> str:
    """The line with every anchored value cut to its anchor and every placeholder written as one
    (outside code spans), so `--fill` never moves a pin and a value is gated by G-ANCHOR."""

    def part(seg: str) -> str:
        seg = PLACEHOLDER.sub(lambda m: f"<!--={m[1]}-->", seg)
        out, pos = [], 0
        for m in ANCHOR.finditer(seg):
            pre, want = seg[pos : m.start()], values.get(m[1], "")
            out += [pre[: len(pre) - len(want)] if want and pre.endswith(want) else pre, m[0]]
            pos = m.end()
        return "".join(out) + seg[pos:]

    parts, pos = [], 0
    for c in CODE.finditer(line):
        parts += [part(line[pos : c.start()]), c[0]]
        pos = c.end()
    return "".join(parts) + part(line[pos:])


def indent_tag(raw: str) -> str:
    """`>n` for a line indented n columns (a tab counts 4), else nothing: an indent can nest a
    bullet or turn prose into a code block without changing a word."""
    lead = raw[: len(raw) - len(raw.lstrip(" \t"))]
    n = len(lead.expandtabs(4))
    return f">{n}" if n else ""


def line_form(line: str) -> str:
    if re.match(r"^\s*[-*+] ", line):
        return "b"
    if re.match(r"^\s*\d+\. ", line):
        return "n"
    return "p"


def doc_units(doc: str, text: str, values: Values) -> list[Unit]:
    """Every unit of the doc: per region (heading path joined by U+203A, `#n` its occurrence), the
    heading, the line shape (one line-form tag per line), each rule line (`rule <k>`), each table
    row by its lead cell (`row <id>`, `#n` on a repeat), each prose sentence (`s<k>`) and each
    fenced block (`fence <k>`, verbatim as JSON)."""
    lines = text.split("\n")
    fence = fenced(lines)
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    count: dict[str, int] = {}
    region, k, shape, nf = "(top)#1", 0, "", 0
    seen: dict[str, int] = {}
    block: list[str] = []

    def close() -> None:
        out.append((doc, region, "shape", shape))

    for i, raw in enumerate(lines):
        if fence[i]:
            shape += "f"
            block.append(raw)
            opener = FENCE_OPEN.match(block[0])
            m_close = FENCE_OPEN.match(raw) if len(block) > 1 else None
            closing = (
                opener is not None
                and m_close is not None
                and m_close[1][0] == opener[1][0]
                and len(m_close[1]) >= len(opener[1])
                and not raw[m_close.end() :].strip()
            )
            if closing or i + 1 == len(lines) or not fence[i + 1]:
                nf += 1
                text_ = json.dumps("\n".join(block), ensure_ascii=False)
                out.append((doc, region, f"fence {nf}", text_))
                block = []
            continue
        ln = unvalued(raw, values)
        m = HEADING.match(ln)
        if m:
            close()
            level = len(m[1])
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m[2]))]
            key = " \u203a ".join(p[1] for p in path)
            count[key] = count.get(key, 0) + 1
            region, k, seen, shape, nf = f"{key}#{count[key]}", 0, {}, "h", 0
            out.append((doc, region, "heading", pin_norm(ln)))
            continue
        if not ln.strip():
            shape += "."
        elif is_rule(ln):
            shape += "r"
            out.append((doc, region, f"rule {shape.count('r')}", pin_norm(re.sub(r"-+", "-", ln))))
        elif re.match(r"^ {0,3}\|", ln):
            shape += indent_tag(raw) + "t"
            rid = row_key(split_row(ln)[0]) or "(blank)"
            seen[rid] = seen.get(rid, 0) + 1
            loc = f"row {rid}" + (f"#{seen[rid]}" if seen[rid] > 1 else "")
            cells = split_row(ln, keep_escapes=True)
            out.append((doc, region, loc, " | ".join(pin_norm(c) for c in cells)))
        else:
            sents = [x for x in FULL_STOP.split(ln.strip()) if x.strip()]
            shape += f"{indent_tag(raw)}{line_form(ln)}{len(sents)}"
            for s in sents:
                k += 1
                out.append((doc, region, f"s{k}", pin_norm(s)))
    close()
    return out


FULL_STOP = re.compile(r"(?<=[.!?])\s+")


def ruled_units(spec: str, hand: str, values: Values) -> list[Unit]:
    docs = {"spec": spec, "hand": hand}
    return [u for d in PIN_DOCS for u in doc_units(d, docs[d], values)]


def write_pins(units: list[Unit]) -> str:
    head = (
        "# E36-D05 pins (every unit of both docs): doc, region (heading path #occurrence), "
        f"location, the exact normalised text; {len(units)} units.\n# Written by `--repin-ruled` "
        "only; `--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in units)


def parse_pins(text: str) -> tuple[Unit, ...]:
    out: list[Unit] = []
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 4:
            out.append((parts[0], parts[1], parts[2], parts[3]))
    return tuple(out)


@functools.lru_cache(maxsize=1)
def read_pins() -> tuple[Unit, ...] | None:
    path = ROOT / RULED_PIN_TXT
    if not path.exists():
        return None
    return parse_pins(path.read_text(encoding="utf-8"))


def region_label(region: str) -> str:
    return region if len(region) <= 60 else "…" + region[-59:]


def region_sec(region: str) -> str:
    """A pin region's `##` section key (the lexicon gates' key)."""
    parts = region.rsplit("#", 1)[0].split(" \u203a ")
    return sec_id(parts[1] if len(parts) > 1 else parts[0])


PinProblem = tuple[str, str, str]  # (message, doc, region)


def prose_problems(
    where: str, doc: str, region: str, was: list[str], now: list[str]
) -> list[PinProblem]:
    bad: list[PinProblem] = []
    ops = difflib.SequenceMatcher(None, was, now, autojunk=False).get_opcodes()
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            continue
        if op == "replace":
            n = min(i2 - i1, j2 - j1)
            for j in range(j1, j1 + n):
                bad.append((f"{where} s{j + 1} changed: {now[j][:60]!r}", doc, region))
            i1, j1 = i1 + n, j1 + n
        for j in range(j1, j2) if op != "delete" else ():
            txt = now[j]
            if txt in was:
                kind = "duplicated" if now.count(txt) > was.count(txt) else "moved"
                bad.append((f"{where} s{j + 1} {kind}: {txt[:60]!r}", doc, region))
            else:
                bad.append((f"{where} s{j + 1} is unpinned (new): {txt[:60]!r}", doc, region))
        for i in range(i1, i2) if op != "insert" else ():
            if was[i] not in now:
                bad.append((f"{where} s{i + 1} deleted: {was[i][:60]!r}", doc, region))
    return bad


def loc_map(
    where: str, doc: str, region: str, units: list[Unit], bad: list[PinProblem]
) -> dict[str, str]:
    out: dict[str, str] = {}
    for u in units:
        if u[2] in out:
            bad.append(
                (f"{where} {u[2]} repeated (a duplicated location): {u[3][:60]!r}", doc, region)
            )
        else:
            out[u[2]] = u[3]
    return out


def row_problems(
    where: str, doc: str, region: str, was: list[Unit], now: list[Unit]
) -> list[PinProblem]:
    bad: list[PinProblem] = []
    old_t = loc_map(where, doc, region, was, [])
    new_t = loc_map(where, doc, region, now, bad)
    for loc, txt in new_t.items():
        if loc not in old_t:
            kind = "duplicated" if txt in old_t.values() else "unpinned (new)"
            bad.append((f"{where} {loc} {kind}: {txt[:60]!r}", doc, region))
        elif old_t[loc] != txt and loc != "shape":
            bad.append((f"{where} {loc} changed: {txt[:60]!r}", doc, region))
    bad += [
        (f"{where} {loc} deleted: {txt[:60]!r}", doc, region)
        for loc, txt in old_t.items()
        if loc not in new_t
    ]
    kept = [loc for loc in new_t if loc in old_t]
    order = [x for x in old_t if x in new_t]
    if kept != order:
        moved = next(a for a, b in zip(kept, order, strict=True) if a != b)
        bad.append((f"{where} {moved} moved (the row order changed)", doc, region))
    return bad


def pin_problems(pinned: tuple[Unit, ...], current: list[Unit]) -> list[PinProblem]:
    bad: list[PinProblem] = []
    old_r = list(dict.fromkeys((u[0], u[1]) for u in pinned))
    new_r = list(dict.fromkeys((u[0], u[1]) for u in current))
    runs = [(u[0], u[1]) for n, u in enumerate(current) if n == 0 or current[n - 1][:2] != u[:2]]
    bad += [
        (f"{d} region '{region_label(r)}' repeated", d, r)
        for d, r in new_r
        if runs.count((d, r)) > 1
    ]
    bad += [
        (f"{d} region '{region_label(r)}' deleted or renamed", d, r)
        for d, r in old_r
        if (d, r) not in new_r
    ]
    for d, r in new_r:
        if (d, r) not in old_r:
            dup = not r.endswith("#1") and (d, r.rsplit("#", 1)[0] + "#1") in old_r
            kind = "duplicated (a repeated heading)" if dup else "unpinned (new)"
            bad.append((f"{d} region '{region_label(r)}' is {kind}", d, r))
    common = [x for x in new_r if x in old_r]
    if common != [x for x in old_r if x in new_r]:
        first = next(
            a for a, b in zip(common, [x for x in old_r if x in new_r], strict=True) if a != b
        )
        bad.append(("a pinned region moved (the heading order changed)", first[0], first[1]))
    for d, r in common:
        where = f"{d} '{region_label(r)}'"
        was = [u for u in pinned if (u[0], u[1]) == (d, r)]
        now = [u for u in current if (u[0], u[1]) == (d, r)]
        bad += row_problems(
            where,
            d,
            r,
            [u for u in was if not PIN_SENT.fullmatch(u[2])],
            [u for u in now if not PIN_SENT.fullmatch(u[2])],
        )
        bad += prose_problems(
            where,
            d,
            r,
            [u[3] for u in was if PIN_SENT.fullmatch(u[2])],
            [u[3] for u in now if PIN_SENT.fullmatch(u[2])],
        )
        shape = [[u[3] for u in x if u[2] == "shape"] for x in (was, now)]
        if shape[0] != shape[1]:
            bad.append(
                (
                    f"{where} shape changed (line forms, sentences per line, indents, blank lines)",
                    d,
                    r,
                )
            )
    return bad


def pin_findings(t: Texts, pinned: tuple[Unit, ...] | None = None) -> list[Finding]:
    pins = read_pins() if pinned is None else pinned
    if pins is None:
        return [F("G-RULED-PIN", f"no {RULED_PIN_TXT}; run --repin-ruled deliberately", None, None)]
    return [
        F("G-RULED-PIN", m, d, region_sec(r))
        for m, d, r in pin_problems(pins, ruled_units(t.spec, t.hand, t.values))
    ]


# The docs hold no fenced block, so the self-test probes the fence path on a small document of its
# own (E15-D09's fence-pin bug): pinned and parsed back it holds, and each verbatim change inside
# the fence FAILs once; a `~~~` line inside a ``` fence does not close it (the kind is read from
# the marker after the indent).
FENCE_PROBE = (
    "# 1. Probe\n\nA sketch follows.\n\n```text\n  [ body ]   [ wick ]\n"
    "| not | a table |\n~~~\n```\n\nAfter it.\n"
)
FENCE_PROBE_CUTS = (
    ("a run of spaces inside a line", "]   [ wick", "] [ wick"),
    ("a line's indent", "\n  [ body", "\n[ body"),
    ("a doubled space in a `|` line", "| not | a table |\n", "| not |  a table |\n"),
    ("a line removed", "| not | a table |\n", ""),
    ("a line added", "| not | a table |\n", "| not | a table |\n  Esc\n"),
)


def fence_pin_probe() -> list[str]:
    units = doc_units("spec", FENCE_PROBE, {})
    pins = parse_pins(write_pins(units))
    fences = [u for u in pins if u[2].startswith("fence")]
    if len(fences) != 1 or "  [ body ]   [ wick ]" not in json.loads(fences[0][3]):
        return [f"fence probe: not one verbatim fence block: {fences[:1]}"]
    if "~~~" not in json.loads(fences[0][3]):
        return ["fence probe: a ~~~ line closed a ``` fence"]
    bad = [f"fence probe: unchanged FAILs {p[0][:60]!r}" for p in pin_problems(pins, units)]
    for name, old, new in FENCE_PROBE_CUTS:
        cut = FENCE_PROBE.replace(old, new, 1)
        got = pin_problems(pins, doc_units("spec", cut, {}))
        fence_hits = [p for p in got if "fence 1" in p[0]]
        if cut == FENCE_PROBE or len(fence_hits) != 1:
            bad.append(
                f"fence probe {name}: expected one fence finding, got {[p[0][:50] for p in got]}"
            )
    return bad


# ---------------------------------------------------------------------------- the audit


def audit(t: Texts, fetch: Fetch) -> tuple[list[str], list[str], list[str], int]:
    """(FAIL lines, NOTE lines, WARN lines, cites checked). One FAIL line per gate; a pin finding
    in a section another gate already FAILs is demoted to a NOTE line."""
    found: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        found += g_anchor_doc(doc, text, t.values)
        found += g_marker_doc(doc, text, t.values)
        found += g_hex_doc(doc, text)
    for gate in LEXICON_GATES:
        found += gate(t)
    cf, warns, n = cite_findings({"spec": t.spec, "hand": t.hand}, fetch)
    if not merge_base():
        warns.append(f"[G-UNTOUCHED] no merge-base with origin/main; compared with BASE {BASE}")
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
    return fails, notes, warns, n


# ---------------------------------------------------------------------------- mutations

Edit = Callable[[str, Values], str]


def set_cell(line: str, idx: int, fn: Callable[[str], str]) -> str:
    cells = split_row(line)
    cells[idx] = fn(cells[idx])
    return "| " + " | ".join(cells) + " |"


def row_edit(head: str, first: str, col: int, fn: Callable[[str], str]) -> Edit:
    """A cell of the row whose first cell is `first`, inside the section `head`."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("|") and split_row(ln)[0] == first:
                lines[i] = set_cell(ln, col, fn)
                return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def reg(frame: str, col: str, fn: Callable[[str], str]) -> Edit:
    return row_edit(FRAME_HEAD, f"`{frame}`", FR_COLS.index(col), fn)


def sub_in(head: str, old: str, new: str) -> Edit:
    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        return text.replace(block, block.replace(old, new, 1), 1) if old in block else text

    return run


def drop_row(head: str, first: str) -> Edit:
    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        kept = [
            ln for ln in block.split("\n") if not (ln.startswith("|") and split_row(ln)[0] == first)
        ]
        return text.replace(block, "\n".join(kept), 1)

    return run


def walk_row(role: str, fn: Callable[[list[str]], list[str]] | None) -> Edit:
    """§17's result row whose Role cell is `role`: rewritten by `fn`, or dropped when None."""

    def run(text: str, _v: Values) -> str:
        block = section(text, WALK_HEAD)
        lines = block.split("\n")
        for i, ln in enumerate(lines):
            cells = split_row(ln) if ln.startswith("|") else []
            if len(cells) > 1 and cells[1] == role:
                if fn is None:
                    del lines[i]
                else:
                    lines[i] = "| " + " | ".join(fn(cells)) + " |"
                return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def to(value: str) -> Callable[[str], str]:
    return lambda _c: value


def appended(extra: str) -> Callable[[str], str]:
    return lambda c: c + extra


def line_edit(prefix: str, old: str, new: str) -> Edit:
    def run(text: str, _v: Values) -> str:
        out = text.split("\n")
        for i, ln in enumerate(out):
            if ln.startswith(prefix) and old in ln:
                out[i] = ln.replace(old, new, 1)
                break
        return "\n".join(out)

    return run


def with_values(build: Callable[[Values], Edit]) -> Edit:
    return lambda text, v: build(v)(text, v)


def av(v: Values, key: str) -> str:
    """The filled form of `key`: its value and its anchor."""
    return f"{v[key]}<!--={key}-->"


def prose_at(head: str, sentence: str) -> Edit:
    """Append a paragraph `sentence` at the end of the section `head`."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        return text.replace(block, block.rstrip("\n") + "\n\n" + sentence + "\n", 1)

    return run


def say_in(head: str, sentence: str) -> Edit:
    """Append `sentence` to the last prose, bullet or numbered line of the section `head` (no line
    is added, so the line budget and the other sections' shapes stay as they were)."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i in range(len(lines) - 1, 0, -1):
            ln = lines[i]
            if ln.strip() and not ln.startswith(("|", "#")):
                lines[i] = ln + " " + sentence
                return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def add_row_after(head: str, first: str, row: str) -> Edit:
    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("|") and split_row(ln)[0] == first:
                lines.insert(i + 1, row)
                return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def in_lines(head: str, fn: Callable[[list[str]], list[str]]) -> Edit:
    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        return text.replace(block, "\n".join(fn(block.split("\n"))), 1) if block else text

    return run


def swap_rows(a: str, b: str) -> Callable[[list[str]], list[str]]:
    def run(lines: list[str]) -> list[str]:
        ids = [split_row(ln)[0] if ln.startswith("|") else "" for ln in lines]
        if a in ids and b in ids:
            i, j = ids.index(a), ids.index(b)
            lines[i], lines[j] = lines[j], lines[i]
        return lines

    return run


def dup_line(prefix: str) -> Callable[[list[str]], list[str]]:
    def run(lines: list[str]) -> list[str]:
        i = next((n for n, ln in enumerate(lines) if ln.startswith(prefix)), None)
        return lines if i is None else [*lines[: i + 1], lines[i], *lines[i + 1 :]]

    return run


def drop_line(prefix: str) -> Callable[[list[str]], list[str]]:
    return lambda lines: [ln for ln in lines if not ln.startswith(prefix)]


def migrate(src: str, dst: str) -> Callable[[list[str]], list[str]]:
    """Move the last sentence of the line led by `src` to the start of the line led by `dst`:
    no word changes and the region's sentence order is kept (only the line boundary moves)."""

    def run(lines: list[str]) -> list[str]:
        i = next((n for n, ln in enumerate(lines) if ln.startswith(src)), None)
        j = next((n for n, ln in enumerate(lines) if ln.startswith(dst)), None)
        if i is None or j is None:
            return lines
        parts = FULL_STOP.split(lines[i])
        if len(parts) < 2:
            return lines
        lines[i] = lines[i][: len(lines[i]) - len(parts[-1])].rstrip()
        lines[j] = parts[-1] + " " + lines[j]
        return lines

    return run


def indented(prefix: str, n: int) -> Callable[[list[str]], list[str]]:
    return lambda lines: [(" " * n + ln if ln.startswith(prefix) else ln) for ln in lines]


def squeezed(edit: Edit | None, n: int) -> Edit:
    """`edit`, then drop the blank line under the last `n` headings (room kept under G-BUDGET)."""

    def run(text: str, v: Values) -> str:
        lines = (edit(text, v) if edit else text).split("\n")
        under = [i + 1 for i, ln in enumerate(lines[:-1]) if HEADING.match(ln) and not lines[i + 1]]
        drop = set(under[-n:])
        return "\n".join(ln for i, ln in enumerate(lines) if i not in drop)

    return run


def shadow(head: str, fn: Callable[[str], str] | None = None) -> Edit:
    """Repeat the section `head` right after itself; `fn` edits the first copy, so the repeat is
    the pristine shadow."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head).rstrip("\n")
        first = fn(block) if fn else block
        return text.replace(block, first + "\n\n" + block, 1) if block else text

    return run


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str  # the gate tag that must trip
    desc: str  # the mutation, as §20 lists it
    ruled: str  # the ruled sentence it trips, as §20 lists it
    spec: Edit | None = None
    hand: Edit | None = None
    plan: tuple[str, Callable[[str], str]] | None = None  # (untouched id, edit) on the plan text
    deck: Callable[[str], str] | None = None  # edits the JSON twin (else rebuilt from the spec)
    env: tuple[tuple[str, object], ...] = ()  # the git state it stands in for (see ENV)


def filler(text: str, _v: Values) -> str:
    n = text.count("\n")
    return text + "Filler.\n" * (SPEC_LINE_BUDGET - n + 5)


def plain_av(v: Values, key: str) -> str:
    return f"{v[key]}<!--={key}-->"


M = Mutation
MUTATIONS: tuple[Mutation, ...] = (
    M(
        "M-1",
        "G-TRACE",
        "drop the AC3 row of the trace",
        "AC1 … AC4 traced (BQ-1)",
        spec=drop_row("Acceptance-criteria trace", "AC3 — a visual with no CMP id blocks hand-off"),
    ),
    M(
        "M-2",
        "G-RULED",
        "cite the BQ list as the ruling in the RULED heading",
        "the ruling of record (6439245637)",
        spec=line_edit("## The thirty-six", "comment 6439245637", "comment 6439029896"),
    ),
    M(
        "M-3",
        "G-UNBUILT",
        'write "describes the screens" for "is the implementation contract"',
        "the body states the rule screens are unbuilt (BQ-1)",
        spec=sub_in(
            "0.1 What is built",
            "this pack is the implementation contract",
            "this pack describes the screens",
        ),
    ),
    M(
        "M-4",
        "G-PENPOT",
        "change one character of P-D03's page id",
        "pages by name + id (BQ-7)",
        spec=sub_in("0.2 Evidence", "5c7e632f-bdb1", "5c7e632f-bdb2"),
    ),
    M(
        "M-5",
        "G-FRAME",
        "write `drawn (D03 #4337)` in `SCR-081/02-1 draft`'s Status",
        "SCR-081 / SCR-083 rows PENDING (BQ-6)",
        spec=row_edit(FRAME_HEAD, "`SCR-081/02-1 draft`", 7, to(DRAWN_STATUS)),
    ),
    M(
        "M-6",
        "G-FRAME",
        "drop the `SCR-080/loading` row",
        "every `14` state has a frame (BQ-7)",
        spec=drop_row(FRAME_HEAD, "`SCR-080/loading`"),
    ),
    M(
        "M-7",
        "G-PENDING",
        'write "SCR-081\'s frames exported" in a trace cell',
        "no SCR-081 / SCR-083 board claimed (BQ-6)",
        spec=row_edit(
            "Acceptance-criteria trace",
            "T Scope — the walkthrough",
            1,
            appended("; SCR-081's frames exported"),
        ),
    ),
    M(
        "M-8",
        "G-NO15",
        'write "This pack adds the CMP-240 entry to `15`." in §5',
        "no `15` edit (BQ-9)",
        spec=say_in("5. The component mapping", "This pack adds the CMP-240 entry to `15`."),
    ),
    M(
        "M-9",
        "G-UNTOUCHED",
        "append a line to `15` in the working tree",
        "`15` untouched, against the merge base (BQ-9, R-2)",
        plan=("15", lambda x: x + "\nAn added line.\n"),
    ),
    M(
        "M-10",
        "G-NO22",
        'write "The pack proposes the export operation\'s shape." in §9',
        "no `22` edit; the gaps are G-rows (BQ-18)",
        spec=say_in("9. The contract", "The pack proposes the export operation's shape."),
    ),
    M(
        "M-11",
        "G-CONTRACT",
        "cite `deleteRule` one line off",
        "each operation at its `22` line (BQ-18)",
        spec=sub_in("9. The contract", ":7808, :7846", ":7808, :7847"),
    ),
    M(
        "M-12",
        "G-FROZEN",
        "drop the freeze clause from FS-8's status",
        '"PROPOSED, owner approval pending (#2701)" (BQ-17)',
        spec=row_edit(FROZEN_HEAD, "FS-8", 3, to("string PROPOSED (an addition to T Sec)")),
    ),
    M(
        "M-13",
        "G-FROZEN",
        'write "you may move it" in FS-1',
        "byte for byte (BQ-17)",
        spec=row_edit(
            FROZEN_HEAD, "FS-1", 1, lambda c: c.replace("you can move it", "you may move it")
        ),
    ),
    M(
        "M-14",
        "G-FROZEN",
        'write "The freeze is final." in §7',
        "the freeze stays PROPOSED (BQ-17)",
        spec=say_in(FROZEN_HEAD, "The freeze is final."),
    ),
    M(
        "M-15",
        "G-CONTRAST",
        "put FS-5 on `color.text.tertiary` without measuring it",
        "every frozen string's pair measured (BQ-17)",
        spec=row_edit(
            FROZEN_HEAD,
            "FS-5",
            6,
            lambda c: c.replace("`color.text.primary` on", "`color.text.tertiary` on", 1),
        ),
    ),
    M(
        "M-16",
        "G-DECK",
        'write "Fix your errors first." in the validity row',
        "every string verbatim at its source (BQ-15)",
        spec=sub_in("6.2 SCR-081", '"Fix the errors first."', '"Fix your errors first."'),
    ),
    M(
        "M-17",
        "G-DECK",
        "rename `rules.io.import.{choose, drop}` to `rules.import.{choose, drop}`",
        "keys per T Tech's namespaces (BQ-15)",
        spec=sub_in(
            "6.5 SCR-089", "`rules.io.import.{choose, drop}`", "`rules.import.{choose, drop}`"
        ),
    ),
    M(
        "M-18",
        "G-DECK-JSON",
        "edit one string of the JSON twin only",
        "the JSON twin equals the tables (BQ-15)",
        deck=lambda d: d.replace("Search rules", "Search the rules", 1),
    ),
    M(
        "M-19",
        "G-REDLINE",
        "drop the G-row from a typed dimension",
        "a typed dimension is a G-row (BQ-8)",
        spec=row_edit(REDLINE_HEAD, "page header", 3, to("— (typed)")),
    ),
    M(
        "M-20",
        "G-TOKEN",
        "name `color.text.muted` in §3",
        "only shipped tokens or the PROPOSED alias (BQ-8)",
        spec=say_in(REDLINE_HEAD, "Captions use `color.text.muted`."),
    ),
    M(
        "M-21",
        "G-MAP",
        "cite CMP-158's heading one line off",
        "every element maps to a `15` heading (AC3)",
        spec=row_edit(MAP_HEAD, "native-stop notice", 3, to("`15`:1797")),
    ),
    M(
        "M-22",
        "G-DIAG",
        'drop "(PROPOSED)" after the derived `id`',
        "the diagnostics mapping (BQ-19)",
        spec=sub_in(DIAG_HEAD, "`id` from `path` + `code` (PROPOSED)", "`id` from `path` + `code`"),
    ),
    M(
        "M-23",
        "G-MOTION",
        "swap the C-rows of rows 7 and 10",
        "the four motion C-rows (BQ-14)",
        spec=in_lines(
            MOTION_HEAD,
            lambda ls: [
                ln.replace("D05-C5b", "D05-CXX")
                .replace("D05-C5c", "D05-C5b")
                .replace("D05-CXX", "D05-C5c")
                for ln in ls
            ],
        ),
    ),
    M(
        "M-24",
        "G-MOTION",
        'write "D02H Table 4 governs the condition rows." in §11',
        "D03 §10 is the motion record (BQ-14)",
        spec=sub_in(MOTION_HEAD, "(D05-C4).", "(D05-C4). D02H Table 4 governs the condition rows."),
    ),
    M(
        "M-25",
        "G-FROW",
        "route F-09 instead of accepting it",
        "the F-rows absorbed as rows (BQ-25)",
        spec=row_edit(FROW_HEAD, "F-09", 6, to("routed — E36-D03")),
    ),
    M(
        "M-26",
        "G-FROW",
        "write Minor for F-05",
        "each F-row's severity as D04 (BQ-25)",
        spec=row_edit(FROW_HEAD, "F-05", 1, to("Minor")),
    ),
    M(
        "M-27",
        "G-AL",
        "reword AL-11's first words",
        "AL-01 … AL-40 by pinned reference (BQ-27)",
        spec=sub_in(AL_HEAD, '"a metric option exposes"', '"each metric option shows"'),
    ),
    M(
        "M-28",
        "G-AL",
        'write "The pack copies D04 §16\'s rows." in §13',
        "never copied (BQ-27)",
        spec=say_in(AL_HEAD, "The pack copies D04 §16's rows."),
    ),
    M(
        "M-29",
        "G-EVENTS",
        "name `rule.ir_exported` as an event",
        "no event invented (BQ-29)",
        spec=row_edit(
            EVENTS_HEAD, "`rule.ir_viewed`, `rule.ir_copied`", 0, appended(", `rule.ir_exported`")
        ),
    ),
    M(
        "M-30",
        "G-LOG",
        "drop D02-G7 from the log",
        "every upstream id logged once (BQ-30)",
        spec=sub_in(LOG_HEAD, "| D02-G7, D03-G15,", "| D03-G15,"),
    ),
    M(
        "M-31",
        "G-LOG",
        "write an agent as an owner lane",
        "owner lanes, never agents (BQ-30)",
        spec=row_edit(LOG_HEAD, "D02-G10", 2, to("hcl-worker-1")),
    ),
    M(
        "M-32",
        "G-CONSUMERS",
        "drop E36-Q04's row",
        "one row per consumer (BQ-32)",
        spec=drop_row(CONSUMER_HEAD, "E36-Q04 (#1056)"),
    ),
    M(
        "M-33",
        "G-CROWS",
        "drop D05-C10",
        "the C-row register (BQ-36)",
        spec=drop_row(CROW_HEAD, "D05-C10"),
    ),
    M(
        "M-34",
        "G-VERSION",
        "pin D03 at its text merge `6c2446be25`",
        "the version line (BQ-33)",
        spec=sub_in(VERSION_HEAD, "D03 and D03H at `e2f82d033c`", "D03 and D03H at `6c2446be25`"),
    ),
    M(
        "M-35",
        "G-STORY",
        "drop Stale from CMP-145's stories",
        "`15`'s Storybook lines (BQ-12)",
        hand=row_edit("§D Storybook", "CMP-145", 1, lambda c: c.replace(", Stale,", ",")),
    ),
    M(
        "M-36",
        "G-PROPS",
        "add `onArm` to CMP-140's props",
        "`15`'s Props lines (BQ-10)",
        hand=row_edit("§B.1 Props", "CMP-140", 1, lambda c: "`onArm` · " + c),
    ),
    M(
        "M-37",
        "G-AROW",
        "aim A-3 one line above SCR-083's Design line",
        "the `14` pointer A-rows (BQ-3)",
        hand=row_edit(OLD_HEAD, "A-3", 1, lambda c: c.replace(":1898", ":1897")),
    ),
    M(
        "M-38",
        "G-AROW",
        "reword A-9's Old cell",
        "Old verbatim; every TBD field filled once (BQ-9)",
        hand=row_edit(OLD_HEAD, "A-9", 2, to('"TBD (E36-D05)."')),
    ),
    M(
        "M-39",
        "G-WALK",
        'drop "No session took place and none is claimed"',
        "no session claimed (BQ-31)",
        spec=sub_in(WALK_HEAD, "**No session took place and none is claimed** (", "("),
    ),
    M(
        "M-40",
        "G-SESSION",
        'write "The walkthrough was held with the engineers." in §17',
        "no fabricated session (BQ-1, BQ-31)",
        spec=say_in(WALK_HEAD, "The walkthrough was held with the engineers."),
    ),
    M(
        "M-41",
        "G-SPLIT",
        'write "this pack also covers SCR-084" in E36-D06\'s row',
        "the E35-D05 boundary (BQ-5)",
        spec=row_edit(
            CONSUMER_HEAD, "E36-D06 (#1052)", 1, appended("; this pack also covers SCR-084")
        ),
    ),
    M(
        "M-42",
        "G-SPLIT",
        "drop E35-D05's ownership from §0.3",
        "E35-D05 owns SCR-084 … SCR-087 (BQ-5)",
        spec=sub_in(
            "0.3 The boundary", "E35-D05 (#940) owns SCR-084", "E35-D05 (#940) reviews SCR-084"
        ),
    ),
    M(
        "M-43",
        "G-ADVANCED",
        'write "the form offers an advanced mode" in CMP-141\'s notes',
        "no advanced mode in the form (BQ-20)",
        hand=row_edit("§B.1 Props", "CMP-141", 2, appended("; the form offers an advanced mode")),
    ),
    M(
        "M-44",
        "G-LOOSEN",
        'write "offers a loosening toggle" in CMP-142\'s notes',
        "no loosening control (BQ-21, #4137)",
        hand=row_edit(
            "§B.1 Props", "CMP-142", 2, appended("; the Owner's row offers a loosening toggle")
        ),
    ),
    M(
        "M-45",
        "G-KEYSTROKE",
        'write "the indicator compiles on every keystroke" in §8.2',
        "save and mode switch only (BQ-22)",
        spec=say_in("8.2 The round-trip", "The indicator compiles on every keystroke."),
    ),
    M(
        "M-46",
        "G-ONECLICK",
        'write "CMP-155\'s enable toggle arms the rule" in §8.4',
        "no one-click arm (BQ-23)",
        spec=say_in("8.4 Disarm", "CMP-155's enable toggle arms the rule."),
    ),
    M(
        "M-47",
        "G-BULKOP",
        'write "Bulk disarm sends one batch request." in §8.4',
        "n idempotent calls (BQ-24)",
        spec=say_in("8.4 Disarm", "Bulk disarm sends one batch request."),
    ),
    M(
        "M-48",
        "G-VALIDITY",
        "draw the invalid row's `Arm…` T2 with the lock",
        "validity is never T2 (R-4)",
        spec=row_edit(
            "8.3 Arm and disarm",
            "invalid",
            2,
            lambda c: c.replace("never T2", "drawn T2 with the lock"),
        ),
    ),
    M(
        "M-49",
        "G-LAYER",
        "write the validator message as the primary line in §6.2",
        "the two-layer rule (BQ-16)",
        spec=sub_in(
            "6.2 SCR-081",
            "except the shipped safety messages D02:270 keeps.",
            "except the shipped safety messages D02:270 keeps. Otherwise the validator's "
            "message is shown as the primary line.",
        ),
    ),
    M(
        "M-50",
        "G-REDRAW",
        'write "This PR redraws board 03." in §0.2',
        "no redraw (BQ-35)",
        spec=say_in("0.2 Evidence", "This PR redraws board 03."),
    ),
    M(
        "M-51",
        "G-SIGNOFF",
        'write "the owner has approved the pack" in §19',
        "owner approval pending (#2701) (BQ-34)",
        spec=say_in(VERSION_HEAD, "Since then the owner has approved the pack."),
    ),
    M(
        "M-52",
        "G-SIGNOFF",
        "drop the owner-pending record from §19",
        'recorded "owner approval pending (#2701)" (BQ-34)',
        spec=sub_in(VERSION_HEAD, 'recorded "owner approval pending (#2701)"', "recorded"),
    ),
    M(
        "M-53",
        "G-TESTID",
        'write "each control gets a data-testid" in §E',
        "role and name first (BQ-13)",
        hand=say_in("§E Test hooks", "In addition each control gets a data-testid."),
    ),
    M(
        "M-54",
        "G-HOOKS",
        'drop "PROPOSED" from §E\'s heading',
        "test hooks PROPOSED (BQ-13)",
        hand=sub_in("§E Test hooks", "(BQ-13, PROPOSED: the specs are silent)", "(BQ-13)"),
    ),
    M(
        "M-55",
        "G-ANNOUNCE",
        'write "polite" for the mismatch in §12.2',
        "Q-03 assertive once (BQ-26)",
        spec=sub_in(
            "12.2 D04", "assertive once, for `mismatch` only", "polite, like the other words"
        ),
    ),
    M(
        "M-56",
        "G-PATHS",
        "change the branch name in §22.2",
        "the branch and title (BQ-1)",
        spec=sub_in(
            "22.2 Deviations", "design/e36-d05-rule-form-handoff", "design/rule-form-handoff-x"
        ),
    ),
    M(
        "M-57",
        "G-CLOSE",
        "write a closing keyword before #947 in §22.2",
        "no closing keyword in the docs; the PR body carries the ruling's (BQ-1)",
        spec=say_in("22.2 Deviations", "This PR closes #947."),
    ),
    M(
        "M-58",
        "G-CHARSET",
        "put a no-break space in §23",
        "no compatibility character",
        spec=sub_in("23. Summary", "A text-first engineering", "A text-first\u00a0engineering"),
    ),
    M(
        "M-59",
        "G-URL",
        "add a host URL beside P-D03",
        "no host, URL or path (README:49)",
        spec=sub_in("0.2 Evidence", "(D03:44)", "(D03:44, https://penpot.example)"),
    ),
    M(
        "M-60",
        "G-ANCHOR",
        "write 17 for the F-row count",
        "every number is the tool's",
        spec=with_values(
            lambda v: sub_in(FROW_HEAD, plain_av(v, "COUNT:frows"), "17<!--=COUNT:frows-->")
        ),
    ),
    M(
        "M-61",
        "G-ANCHOR",
        'type a bare "48 px" in §3',
        "no hand-typed figure",
        spec=say_in(REDLINE_HEAD, "The bar is 48 px tall."),
    ),
    M(
        "M-62",
        "G-MARKER",
        "hide a comment in §1.2",
        "every comment is a computed anchor",
        spec=say_in("1.2 Rules stated once", "<!-- a hidden note -->"),
    ),
    M(
        "M-63",
        "G-HEX",
        "type a hex in §3",
        "a hex is the tool's",
        spec=say_in(REDLINE_HEAD, "The ink reads #E8EAED."),
    ),
    M(
        "M-64",
        "G-CITE",
        "cite a line past `22`'s end",
        "every cite in range at the base",
        spec=sub_in("10. Diagnostics", "(`22`:20032)", "(`22`:99999)"),
    ),
    M(
        "M-65",
        "G-BUDGET",
        "append lines past the budget",
        "the spec within its line budget",
        spec=filler,
    ),
    M(
        "M-66",
        "G-DECK",
        "drop the owner of the SCR-088 by-cite row",
        "a by-cite row names its owner (BQ-5)",
        spec=row_edit("6.4 SCR-088", "`rules.ir.e35`", 4, to("")),
    ),
    M(
        "M-67",
        "G-AL",
        "drop the hash of D04 §16",
        "verbatim met by a hash (BQ-27)",
        spec=with_values(
            lambda v: sub_in(
                AL_HEAD, f"(sha256 prefix {plain_av(v, 'HASH:d04.al')})", "(a sha256 prefix)"
            )
        ),
    ),
    M(
        "P-1",
        "G-RULED-PIN",
        "reword §4's first sentence",
        "a prose sentence (pin)",
        spec=sub_in(
            "4. The pack's form",
            "Two files, the E10-D04 split (README:81",
            "Two files, as E10-D04 splits them (README:81",
        ),
    ),
    M(
        "P-2",
        "G-RULED-PIN",
        "drop a row of §15",
        "a table row (pin)",
        spec=drop_row(EVENTS_HEAD, "`rule.ir_viewed`, `rule.ir_copied`"),
    ),
    M(
        "P-3",
        "G-RULED-PIN",
        "swap two rows of §14",
        "the row order (pin)",
        spec=in_lines(
            BUDGETS_HEAD, swap_rows("template instantiation", "the `rules` topic coalescing")
        ),
    ),
    M("P-4", "G-RULED-PIN", "repeat §10", "a repeated region (pin)", spec=shadow(DIAG_HEAD)),
    M(
        "P-5",
        "G-RULED-PIN",
        "drop the blank line under a heading",
        "the line shape (pin)",
        spec=squeezed(None, 1),
    ),
    M(
        "P-6",
        "G-RULED-PIN",
        "indent a line of §17",
        "an indent (pin)",
        spec=in_lines(WALK_HEAD, indented("3. **The QA pass.**", 4)),
    ),
)

POINTER = (
    "- **Hand-off pack:** [E36-D05.md](../design/E36/E36-D05.md) v1 "
    "(E36-D05; owner approval pending)"
)


def drop_nth(line: str, n: int) -> Callable[[str], str]:
    """Drop the n-th line equal to `line` (1-based)."""

    def run(text: str) -> str:
        lines = text.split("\n")
        hits = [i for i, ln in enumerate(lines) if ln == line]
        return "\n".join(ln for i, ln in enumerate(lines) if i != hits[n - 1]) if hits else text

    return run


def merge_cells(first: str, pad: bool) -> Callable[[list[str]], list[str]]:
    """Escape the pipe between the row's second and third cells (they render as one); `pad`
    appends an empty cell, so the row keeps its header's cell count."""

    def run(lines: list[str]) -> list[str]:
        for i, ln in enumerate(lines):
            if ln.startswith("|") and split_row(ln)[0] == first:
                c = split_row(ln, keep_escapes=True)
                cells = [c[0], f"{c[1]} \\| {c[2]}", *c[3:], *([""] if pad else [])]
                lines[i] = "| " + " | ".join(cells) + " |"
        return lines

    return run


EXTRA_MUTATIONS: tuple[Mutation, ...] = (
    M(
        "M-68",
        "G-UNTOUCHED",
        "drop SCR-083's pointer line from `14`",
        "`14` reflects the pack, linked (AC4, BQ-3)",
        plan=("14", drop_nth(POINTER, 3)),
    ),
    M(
        "M-69",
        "G-UNTOUCHED",
        "append another line to `14`",
        "`14` only by BQ-3's five lines (BQ-3)",
        plan=("14", lambda x: x + "\nAn added line.\n"),
    ),
    M(
        "M-70",
        "G-RN",
        "invert R-7",
        "the validator is the single source of truth (R-7)",
        spec=sub_in(
            "1.2 Rules stated once",
            "The form never ships an IR the validator rejects, and form and graph report identical",
            "The form may ship an IR the validator rejects, and form and graph may report "
            "different",
        ),
    ),
    M(
        "M-71",
        "G-RN",
        "move R-8's gates into the browser",
        "server-side truth (R-8)",
        spec=sub_in(
            "1.2 Rules stated once",
            "are enforced server-side; the UI renders server truth",
            "are enforced in the browser; the UI decides",
        ),
    ),
    M(
        "M-72",
        "G-RN",
        "drop `14`'s pointer-line clause from R-2",
        "`14` only by BQ-3's lines (R-2)",
        spec=sub_in(
            "1.2 Rules stated once",
            "; `14` changes only by the five pointer lines this PR adds "
            "(hand-off §C A-1 \u2026 A-5, "
            "BQ-3)",
            "",
        ),
    ),
    M(
        "M-73",
        "G-REDRAW",
        "replace §0.2's no-board sentence with a board on P-D03",
        "no redraw, no new page (BQ-35)",
        spec=sub_in(
            "0.2 Evidence",
            "No E36-D05 board exists and none is drawn.",
            "An E36-D05 board now sits on P-D03 beside the merged ones.",
        ),
    ),
    M(
        "M-74",
        "G-ADVANCED",
        "turn §8.1's no-advanced-mode sentence into free-typed expressions",
        "no advanced mode in the form (BQ-20)",
        spec=sub_in(
            "8.1 Conditions",
            '**The form has no "advanced" expression mode:**',
            "**Power users can switch the form into free-typed expressions:**",
        ),
    ),
    M(
        "M-75",
        "G-LOOSEN",
        "let the Owner move a stop further from price in R-6",
        "no loosening control, for any role (BQ-21, #4137)",
        spec=sub_in(
            "1.2 Rules stated once",
            "No screen offers a control that loosens or clears a stop, for any role;",
            "The Owner may move a stop further from price from SCR-081;",
        ),
    ),
    M(
        "M-76",
        "G-KEYSTROKE",
        "compute the indicator continuously as the user edits",
        "save and mode switch only (BQ-22)",
        spec=sub_in(
            "8.2 The round-trip",
            "computed **on save and on mode switch only**, never per keystroke",
            "computed **continuously as the user edits a field**",
        ),
    ),
    M(
        "M-77",
        "G-ONECLICK",
        "write that a single click arms the rule",
        "no one-click arm (BQ-23)",
        spec=sub_in(
            "8.3 Arm and disarm",
            "No one-click arm exists (D03-C11).",
            "A single click arms the rule (D03-C11).",
        ),
    ),
    M(
        "M-78",
        "G-BULKOP",
        "make bulk disarm a single batch request",
        "n idempotent calls (BQ-24)",
        spec=sub_in(
            "8.4 Disarm",
            "**bulk disarm is n idempotent `PUT /rules/{ruleId}/mode` calls**",
            "**bulk disarm is a single batch request**",
        ),
    ),
    M(
        "M-79",
        "G-SCR080",
        "permit Delete while armed",
        "Delete while armed is T2 (BQ-24)",
        spec=sub_in(
            "8.4 Disarm",
            "Delete while armed is T2 `rule.delete.armed` (D03:104).",
            "Delete while armed is permitted without a gate (D03:104).",
        ),
    ),
    M(
        "M-80",
        "G-ARM",
        "make a missing live step-up a reason to disable",
        "elevation is never a reason to disable (BQ-23)",
        spec=row_edit(
            "8.3 Arm and disarm",
            "live step-up missing",
            2,
            lambda c: c.replace("never a reason to disable", "a reason to disable"),
        ),
    ),
    M(
        "M-81",
        "G-ARM",
        "drop `promotion_gate` from the refusal codes",
        "the arm refusals and their source (BQ-16)",
        spec=row_edit(
            "8.3 Arm and disarm",
            "refusal at the point of action",
            2,
            lambda c: c.replace(" · `promotion_gate`", ""),
        ),
    ),
    M(
        "M-82",
        "G-FROZEN",
        'write "The freeze is now in force." in §7',
        "the freeze stays PROPOSED (BQ-17)",
        spec=say_in(FROZEN_HEAD, "The freeze is now in force."),
    ),
    M(
        "M-83",
        "G-NO15",
        'write "This PR also updates `15` with CMP-240\'s props." in §1.2',
        "no `15` edit (BQ-9)",
        spec=say_in("1.2 Rules stated once", "This PR also updates `15` with CMP-240's props."),
    ),
    M(
        "M-84",
        "G-NO22",
        "write that the pack sketches an export request body for `22`",
        "no `22` edit (BQ-18)",
        spec=say_in(
            CONTRACT_HEAD, "The pack sketches an export operation's request body for `22`."
        ),
    ),
    M(
        "M-85",
        "G-EXCEPT",
        "carve the Owner out of `widen_stop`'s omission in CMP-142's notes",
        "for every role (R-6, BQ-21)",
        hand=row_edit(
            "§B.1 Props", "CMP-142", 2, appended("; omitted for every role but the Owner")
        ),
    ),
    M(
        "M-86",
        "G-CHARSET",
        "put a Cyrillic letter in §23",
        "no homoglyph",
        spec=sub_in("23. Summary", "A text-first engineering", "A t\u0435xt-first engineering"),
    ),
    M(
        "M-87",
        "G-CHARSET",
        "put a soft hyphen in §23",
        "no format character",
        spec=sub_in(
            "23. Summary", "engineering hand-off pack for", "engi\u00adneering hand-off pack for"
        ),
    ),
    M(
        "M-88",
        "G-CHARSET",
        "put a space before §4's last full stop",
        "no space before a full stop",
        spec=sub_in(
            "4. The pack's form",
            "get their lines in hand-off §B.",
            "get their lines in hand-off §B .",
        ),
    ),
    M(
        "M-89",
        "G-CELLS",
        "escape a column pipe in §14",
        "every row has its header's cells",
        spec=in_lines(BUDGETS_HEAD, merge_cells("the `rules` topic coalescing", pad=False)),
    ),
    M(
        "M-90",
        "G-HEADS",
        "demote §8.4's heading to `####`",
        "a heading's level follows its number",
        spec=line_edit("### 8.4 Disarm", "### 8.4", "#### 8.4"),
    ),
    M(
        "M-91",
        "G-GHERKIN",
        "drop a scenario from E36-S04's trace row",
        "every consumer scenario traced (AC1)",
        spec=sub_in(
            "Acceptance-criteria trace", ' · "Templates are always valid (edge)" → §9 (D02-G10)', ""
        ),
    ),
    M(
        "M-92",
        "G-GHERKIN",
        "point the concurrent save at a G-row that does not exist",
        "every pointer resolves (AC1)",
        spec=sub_in("Acceptance-criteria trace", '(error)" → D05-G6', '(error)" → D05-G16'),
    ),
    M(
        "M-93",
        "G-FROW",
        "drop E36-S05 from F-09's consumer",
        "SCR-080's F-rows name both stories (D05-C10)",
        spec=row_edit(FROW_HEAD, "F-09", 5, to("E36-S02")),
    ),
    M(
        "M-94",
        "G-ANNOUNCE",
        "drop the mismatch's assertive mark",
        "the mismatch assertive once (F-05, BQ-26)",
        spec=sub_in(
            "6.2 SCR-081",
            "polite; `mismatch` assertive (F-05); `checking` none",
            "polite; `checking` none",
        ),
    ),
    M(
        "M-95",
        "G-DECK",
        'mark a row "loud"',
        "polite, assertive or none (BQ-16)",
        spec=row_edit("6.4 SCR-088", "`rules.ir.announce.count`", 6, to("loud")),
    ),
    M(
        "M-96",
        "G-DECK",
        "tag `metric` client",
        "each import reason server or client (BQ-16, D03:155)",
        spec=sub_in("6.5 SCR-089", "`metric`, `action` server", "`action` server; `metric` client"),
    ),
    M(
        "M-97",
        "G-ERRORS",
        "drop `RuleIrInvalid` from §6.2's server refusals",
        "the server errors listed (BQ-16)",
        spec=sub_in("6.2 SCR-081", "`RuleIrInvalid` (`22`:16155;", "a refusal (`22`:16155;"),
    ),
    M(
        "M-98",
        "G-FROZEN",
        "put FS-9's sentence back into `disarm_body`",
        "every source string keyed once (BQ-15)",
        spec=sub_in(
            "6.1 SCR-080",
            'Native stops are unaffected." · "sys.',
            "Native stops are unaffected. This is not the kill switch — nothing is cancelled or "
            'flattened." · "sys.',
        ),
    ),
    M(
        "M-99",
        "G-FROZEN",
        "drop FS-3's pending mark",
        "FS-3's test waits on D05-G5",
        spec=row_edit(FROZEN_HEAD, "FS-3", 5, to("`frozen:FS-3`")),
    ),
    M(
        "M-100",
        "G-FROZEN",
        'write "string merged" for FS-6',
        "each string's own status (BQ-17)",
        spec=row_edit(
            FROZEN_HEAD, "FS-6", 3, lambda c: c.replace("string PROPOSED", "string merged")
        ),
    ),
    M(
        "M-101",
        "G-CONTRACT",
        "drop the `listRuleAccounts` row",
        "every operation the screens call (BQ-18)",
        spec=drop_row(CONTRACT_HEAD, "`listRuleAccounts`"),
    ),
    M(
        "M-102",
        "G-STORY",
        "drop CopyPath from §D's CMP-240 additions",
        "A-18's stories (BQ-12)",
        hand=row_edit("§D Storybook", "CMP-240", 1, lambda c: c.replace(", CopyPath", "")),
    ),
    M(
        "M-103",
        "G-AROW",
        "reword A-18's Old cell",
        "Old verbatim (BQ-12)",
        hand=row_edit(OLD_HEAD, "A-18", 2, lambda c: c.replace("InlineRename", "Rename")),
    ),
    M(
        "M-104",
        "G-VERSION",
        "a merged change to D04 at origin/main",
        "a late change FAILs (BQ-33)",
        env=(("head_commit", {CITE_FILES["D04"]: "0123456789"}),),
    ),
    M(
        "M-105",
        "G-VERSION",
        "D04 §16's rows changed at origin/main",
        "the AL hash at origin/main (BQ-27, BQ-33)",
        env=(("head_al_hash", "000000000000"),),
    ),
    M(
        "M-106",
        "G-BASE",
        "commits on a branch that lacks BASE",
        "the PR base matches the pinned inputs",
        env=(("branch_state", (False, 3)),),
    ),
    M(
        "M-107",
        "G-ADVANCED",
        'write "the form offers an advanced expression mode" in CMP-141\'s notes',
        "no advanced mode in the form (BQ-20)",
        hand=row_edit(
            "§B.1 Props", "CMP-141", 2, appended("; the form offers an advanced expression mode")
        ),
    ),
    M(
        "M-108",
        "G-KEYSTROKE",
        'write "on every keystroke" for "never per keystroke" in §8.2',
        "save and mode switch only (BQ-22)",
        spec=sub_in("8.2 The round-trip", "never per keystroke", "and on every keystroke"),
    ),
    M(
        "M-109",
        "G-SIGNOFF",
        "write that the owner's go-ahead came on #2701",
        "owner approval pending (#2701) (BQ-34)",
        spec=say_in(VERSION_HEAD, "The owner's go-ahead came on #2701."),
    ),
    M(
        "M-110",
        "G-TESTID",
        "write `data-testid` on all controls in §E",
        "role and name first (BQ-13)",
        hand=say_in("§E Test hooks", "Hooks: `data-testid` on all controls."),
    ),
    M(
        "M-111",
        "G-WALK",
        "drop E36-S03's dry-run row from §17",
        "a dry-run row per consumer (BQ-31 b)",
        spec=walk_row("story: E36-S03 (#1059)", None),
    ),
    M(
        "M-112",
        "G-WALK",
        "write — for E36-S06's dispositions",
        "every not-found folded or carried (BQ-31 b)",
        spec=walk_row("story: E36-S06 (#1062)", lambda c: c[:5] + ["—"]),
    ),
    M(
        "M-113",
        "G-WALK",
        "untick §22.1's written-confirmation box",
        "the DoD box matches the record (BQ-31)",
        spec=sub_in(DOD_HEAD, "- [x] Walkthrough", "- [ ] Walkthrough"),
    ),
    M(
        "M-114",
        "G-WALK",
        "write 13 found for E36-Q04",
        "the counts add up (BQ-31 b)",
        spec=walk_row("story: E36-Q04 (#1056)", lambda c: c[:3] + ["13"] + c[4:]),
    ),
    M(
        "M-115",
        "G-WALK",
        "carry E36-Q03's not-found to a G-row that does not exist",
        "every carry names a G- or Q-row (BQ-31 b)",
        spec=walk_row(
            "story: E36-Q03 (#1055)", lambda c: c[:5] + [c[5].replace("D05-G12", "D05-G19")]
        ),
    ),
    M(
        "M-116",
        "G-WALK",
        "drop the QA row from §17",
        "the QA pass over §2's state rows (BQ-31 c)",
        spec=walk_row("QA: §2, all five screens", None),
    ),
    M(
        "P-7",
        "G-RULED-PIN",
        "escape a pipe in §14 and pad the row",
        "a merged cell (pin)",
        spec=in_lines(BUDGETS_HEAD, merge_cells("the `rules` topic coalescing", pad=True)),
    ),
)

MUTATIONS = (
    *[mu for mu in MUTATIONS if mu.mid.startswith("M-")],
    *[mu for mu in EXTRA_MUTATIONS if mu.mid.startswith("M-")],
    *[mu for mu in MUTATIONS if mu.mid.startswith("P-")],
    *[mu for mu in EXTRA_MUTATIONS if mu.mid.startswith("P-")],
)


# ---------------------------------------------------------------------------- the self-test


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def plan_paths() -> tuple[tuple[str, Path], ...]:
    """The working-tree files G-UNTOUCHED compares: UNTOUCHED and UNTOUCHED_DOCS."""
    out = []
    for nn in (*UNTOUCHED, *UNTOUCHED_DOCS):
        rel = cite_path(nn)
        if rel is None:
            raise SystemExit(f"FAIL parse: docs/plan/{nn}-* missing")
        out.append((nn, ROOT / rel))
    return tuple(out)


def read_plans() -> tuple[tuple[str, str], ...]:
    return tuple((nn, p.read_bytes().decode("utf-8")) for nn, p in plan_paths())


def ascii_line(text: str) -> str:
    """Self-test output in ASCII (a cp1252 console never crashes on it)."""
    return text.encode("ascii", "backslashreplace").decode("ascii")


def mutation_ids(spec: str) -> list[str]:
    """§20's rows as "M-n G-TAG", in order: a row lists up to three mutations, its last cell
    naming each one's gate as "M-n G-TAG: …"."""
    out: list[str] = []
    for r in table_rows(section(spec, MUTATION_HEAD)):
        out += [f"{m[1]} {m[2]}" for m in re.finditer(r"\b(M-\d+) (G-[A-Z0-9-]+):", r[-1])]
    return out


PER_ROW = 30


def mutation_table() -> str:
    """§20's rows, thirty mutations to a row (written into the spec by hand from this output)."""
    ms = [mu for mu in MUTATIONS if mu.mid.startswith("M-")]
    rows = []
    for i in range(0, len(ms), PER_ROW):
        part = ms[i : i + PER_ROW]
        ids = part[0].mid if len(part) == 1 else f"{part[0].mid} … {part[-1].mid}"
        what = "; ".join(f"{mu.mid}: {mu.desc}" for mu in part)
        gate = "; ".join(f"{mu.mid} {mu.gate}: {mu.ruled}" for mu in part)
        rows.append(f"| {ids} | {what} | {gate} |")
    return "\n".join(rows)


def selftest(spec: str, hand: str, paths: tuple[Path, ...]) -> tuple[bool, list[str]]:
    on_disk = digest(paths)
    plans = read_plans()
    values = compute(spec, hand)
    spec_f, _ = fill(spec, values)
    hand_f, _ = fill(hand, values)
    values = compute(spec_f, hand_f)  # frozen at the filled baseline
    deck_f = deck_json(spec_f)
    base_t = Texts(spec_f, hand_f, deck_f, plans, values)
    base_fails, _notes, base_warns, _ = audit(base_t, git_fetch)
    lines = [f"baseline (filled in memory): {len(base_fails)} FAIL, {len(base_warns)} WARN"]
    lines += [f"  baseline FAIL {x[:160]}" for x in base_fails]
    ok = not base_fails
    probe = fence_pin_probe()
    lines.append(f"  fence probe: {'ok' if not probe else 'FAIL'}")
    lines += [f"    {x}" for x in probe]
    ok = ok and not probe
    listed = mutation_ids(spec_f)
    built = [f"{mu.mid} {mu.gate}" for mu in MUTATIONS if mu.mid.startswith("M-")]
    if listed != built:
        ok = False
        lines.append(f"  §20 lists {len(listed)} M-rows, the tool builds {len(built)}: they differ")
    pristine = digest_texts(spec_f, hand_f, deck_f, *(x for _n, x in plans))
    for mu in MUTATIONS:
        s = mu.spec(spec_f, values) if mu.spec else spec_f
        h = mu.hand(hand_f, values) if mu.hand else hand_f
        d = mu.deck(deck_f) if mu.deck else deck_json(s)
        new_plans = tuple(
            (nn, mu.plan[1](x) if mu.plan and mu.plan[0] == nn else x) for nn, x in plans
        )
        if not mu.env and (s, h, d, new_plans) == (spec_f, hand_f, deck_f, plans):
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        ENV.clear()
        ENV.update(dict(mu.env))
        try:
            fails, _n2, _w, _c = audit(Texts(s, h, d, new_plans, values), git_fetch)
        except SystemExit as exc:
            fails = [str(exc)]
        finally:
            ENV.clear()
        new = [x for x in fails if x not in base_fails]
        named = [x for x in new if x.startswith(f"[{mu.gate}]")]
        hit = bool(named) and len(new) == 1
        restored = digest_texts(spec_f, hand_f, deck_f, *(x for _n, x in plans)) == pristine
        restored = restored and digest(paths) == on_disk
        ok = ok and hit and restored
        first = (named or new or ["nothing new"])[0][:110]
        lines.append(
            f"  {mu.mid} [{mu.gate}] {'ok' if hit else 'MISSED'} ({len(new)} new"
            f"{'' if restored else ', NOT RESTORED'}) -- {first}"
        )
        if not hit:
            lines += [f"      new: {x[:200]}" for x in new]
    return ok, [ascii_line(x) for x in lines]


# ---------------------------------------------------------------------------- main


def write_text(path: Path, text: str) -> None:
    """Every writer opens its file with newline="\\n"."""
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    ap = argparse.ArgumentParser(description="E36-D05 hand-off audit (module docstring)")
    ap.add_argument(
        "--check",
        nargs="?",
        const=SPEC_REL,
        default=None,
        metavar="SPEC",
        help="audit the spec (default: the committed path) and the hand-off",
    )
    ap.add_argument("--handoff", default=HAND_REL, metavar="F", help="the hand-off to audit")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="fill placeholders and the deck JSON")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="apply every mutation")
    ap.add_argument("--repin-ruled", action="store_true", help=f"rewrite {RULED_PIN_TXT}")
    ap.add_argument("--mutation-table", action="store_true", help="print §20's rows")
    args = ap.parse_args(argv)
    if args.mutation_table:
        print(mutation_table())
        return 0
    spec_path = ROOT / (args.check or SPEC_REL)
    hand_path = ROOT / args.handoff
    deck_path = ROOT / DECK_REL
    spec = spec_path.read_bytes().decode("utf-8")
    hand = hand_path.read_bytes().decode("utf-8")
    if args.repin_ruled:
        left = PLACEHOLDER.findall(CODE.sub("", spec + hand))
        if left:
            print(f"FAIL --repin-ruled: {len(left)} unfilled placeholders; run --fill first")
            return 1
        units = ruled_units(spec, hand, compute(spec, hand))
        write_text(ROOT / RULED_PIN_TXT, write_pins(units))
        print(f"--repin-ruled: {len(units)} units pinned in {RULED_PIN_TXT}")
        return 0
    if args.self_test:
        paths: tuple[Path, ...] = (spec_path, hand_path, deck_path, ROOT / RULED_PIN_TXT)
        paths += tuple(p for _n, p in plan_paths())
        ok, lines = selftest(spec, hand, paths)
        print("\n".join(lines))
        print(f"--self-test: {'ok' if ok else 'FAIL'} -- {len(MUTATIONS)} mutations in memory")
        return 0 if ok else 1
    values = compute(spec, hand)
    if args.fill:
        spec, hand = unfill(spec), unfill(hand)
        values = compute(spec, hand)
        spec, unknown = fill(spec, values)
        hand, unknown_h = fill(hand, values)
        write_text(spec_path, spec)
        write_text(hand_path, hand)
        values = compute(spec, hand)
        write_text(deck_path, deck_json(spec))
        for u in unknown + unknown_h:
            print(f"FAIL --fill: no value for {{{{{u}}}}}")
    if args.json and not (args.check or args.fill):
        print(json.dumps({"values": values}, ensure_ascii=False, indent=1))
        return 0
    deck = deck_path.read_bytes().decode("utf-8") if deck_path.exists() else ""
    t = Texts(spec, hand, deck, read_plans(), values)
    fails, notes, warns, n = audit(t, git_fetch)
    if args.json:
        doc = {"values": values, "fails": fails, "notes": notes, "warnings": warns, "cites": n}
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        gates = len(LEXICON_GATES) + len(MEASURED_GATES) + 5
        shown = spec_path.relative_to(ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        print(f"## E36-D05 audit of {shown} (+ the hand-off) at base {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(notes))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK -- every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(notes)} NOTE, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
