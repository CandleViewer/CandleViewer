#!/usr/bin/env python3
"""E29-D06 (#825) audit: the OMS blotters' engineering hand-off pack (spec + keyed copy deck).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base `927794a8ba` (`git show`): the plan texts the spec cites, the merged
E29 design texts D01-D05 and D04H, the backlog JSON (`E29.json`, `E05.json`), the calendar
(`calendar_cv.py`) and the board tree; D05 at its merge `966f9edcd9` for the lifted sections; and,
from the working tree, the spec `docs/design/E29/E29-D06.md`, the deck
`docs/design/E29/E29-D06-copy.json` and the files the pack must not edit.

1. **Values.** Every `{{KIND:key}}` is a placeholder that `--fill` writes as
   `VALUE<!--=KIND:key-->`:
   COUNT (boards in the base tree, the spec's own table rows, the deck's strings and keys, the
   union of gap and question ids), DATE (a sprint start from `E29.json` and `calendar_cv.py`), HASH
   (sha256 prefix of a lifted D05 section at its merge) and CITE (a figure parsed from the cited
   line). `--check` re-derives each anchored value (G-ANCHOR, with a left boundary, so "121" never
   hides "21"), FAILs a `{{` left behind, any HTML comment that is not an anchor (G-MARKER) and a
   hand-typed figure before a unit or a counted noun (G-FIGURE).
2. **Cites.** Every `NN`:line, `D0n`:line, `D04H`:line, `E10H`:line, `E11-D09`:line, `CONST`,
   `CAL`, `KM`, `README`, `E29.json`, `E05.json` and `TM29` cite, in the spec and in the deck, is
   read at the base and must be a non-blank line (G-CITE); quoted copy and every backticked metric
   name in the spec must occur verbatim in a doc its line cites or in the ticket JSON (G-QUOTE); every deck string (or rule) must equal a
   whole unit of its source line, never a substring (G-DECK; `wholes` bounds a unit). The deck is default-deny: its top-level fields, its
   version, duplicate keys, non-object members, the string-or-rule choice and each string's
   `params` (every data-bound span named with its kind) are checked, and the pins cover every
   top-level value.
3. **Gates.** One FAIL line per gate. Measured gates read the spec's tables column by column
   (G-STATES, G-FRAMES, G-CMP, G-CR, G-FROW, G-LIFT, G-GROWS, G-LOG, G-CONSUMERS, G-WALK,
   G-VERSION, G-UNBUILT); G-WALK also reads §14's dry-run record (one row per consumer, then
   the QA row; needs = found + not found; one resolvable `→` per not-found, an unparseable
   target FAILs; the DoD tick and AC3 follow the record); G-CONSUMERS also traces every Gherkin scenario of each consuming story
   and gives each tab-level state to the stories that build that tab. The lexicon gate G-RULED
   requires each ruled sentence verbatim in its section and reads every clause of every section,
   §17 included (quoted mutation text excepted), for a paraphrase that asserts the opposite; a
   negation covers its own term only within its phrase (never across `:`, `;` or `,`, and never
   past a doubting verb), and a quote of one or two words is read as prose. The paraphrase set the
   self-test carries FAILs a named gate; the pins are the backstop for any other wording.
   G-SESSION refuses any claimed session. G-UNTOUCHED compares the working tree with
   `git merge-base HEAD origin/main` (committed and uncommitted paths alike): only `14` may differ,
   by exactly the three pointer lines of BQ-3; an unresolvable merge-base FAILs. G-VERSION FAILs
   (never WARNs) when a pinned input's last commit at `origin/main` differs from the base's, and
   when `origin/main` does not resolve. G-CHARSET (NFKC on the whole line, quotes included; CR,
   trailing whitespace; `…` only inside quoted merged copy), G-CELLS (escaped pipes kept),
   G-CLOSE, G-URL, G-UNMERGED, G-NOHANDOFF, G-BUDGET, G-GITLEAKS and G-MUTLIST close the set.
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of the spec (each
   heading, table row by its lead cell, rule line and prose sentence, by heading path and
   occurrence, with a line-shape tag per region) and over every deck entry, in
   `e29_d06_ruled_pins.txt`. Anchored values are cut out of the pinned text (G-ANCHOR owns them).
   `--repin-ruled` is the only writer and refuses while a placeholder is unfilled. A pin finding
   in a section another gate already FAILs prints as a NOTE line.
5. **--self-test** applies every mutation of the spec's §17 (and the tool's own P-n pin probes)
   in memory, with the values frozen at the filled baseline; each must add exactly one FAIL, from
   the gate it names; every text is restored byte-identically (sha256 in memory and on disk).
   Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e29_d06_handoff_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e29_d06_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e29_d06_handoff_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import copy
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
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "927794a8ba"  # the origin/main sha at the start of the work; every cite is read here
HEAD = "origin/main"  # G-VERSION: a pinned input's last commit here must equal the base's
D05_SHA = "966f9edcd9"  # D05's merge (#4701): the lifted sections are hashed here

SPEC_REL = "docs/design/E29/E29-D06.md"
DECK_REL = "docs/design/E29/E29-D06-copy.json"
TOOL_REL = "docs/design/_tools/e29_d06_handoff_audit.py"
PIN_REL = "docs/design/_tools/e29_d06_ruled_pins.txt"
PLAN14 = "docs/plan/14-screens-catalogue.md"
OWN = (SPEC_REL, DECK_REL, TOOL_REL, PIN_REL, PLAN14)
LINE_BUDGET = 300  # 6437730643: "<=~300 lines"; the ruling's BQ-4: "about 300 lines at most"

CITE_FILES = {
    "D01": "docs/design/E29/E29-D01.md",
    "D02": "docs/design/E29/E29-D02.md",
    "D03": "docs/design/E29/E29-D03.md",
    "D04": "docs/design/E29/E29-D04.md",
    "D05": "docs/design/E29/E29-D05.md",
    "D04H": "docs/design/E29/E29-D04-handoff.md",
    "E10H": "docs/design/E10/E10-D04-handoff.md",
    "E11-D09": "docs/design/E11/E11-D09.md",
    "CONST": "CONSTITUTION.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "KM": "apps/web/src/keymap/keymap.json",
    "README": "docs/design/README.md",
    "E29.json": "docs/plan/backlog/E29.json",
    "E05.json": "docs/plan/backlog/E05.json",
    "TM29": "docs/security/threat-models/E29-oms.md",
}
PLAN = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "14": PLAN14,
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "20": "docs/plan/20-architecture.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
}
# BQ-3: these stay byte-identical with the merge-base (the `14` diff is gated exactly).
UNTOUCHED = tuple(
    [PLAN[k] for k in ("02", "05", "06", "15", "16", "20", "22", "23", "24")]
    + [CITE_FILES[k] for k in ("D01", "D02", "D03", "D04", "D05", "D04H", "KM", "E29.json")]
    + [CITE_FILES["E05.json"], CITE_FILES["README"], CITE_FILES["TM29"]]
)
POINTER = (
    "- **Hand-off pack:** [E29-D06.md](../design/E29/E29-D06.md) v1 (E29-D06; owner approval"
    " pending) (a11y contract: E29-D05)."
)
POINTER_AFTER = (
    "- **Hi-fi spec:** [E29-D02.md](../design/E29/E29-D02.md)",
    "- **Hi-fi (E29-D03):** [E29-D03.md](../design/E29/E29-D03.md)",
    "- **Hi-fi (E29-D03, OMS account states):** [E29-D03.md](../design/E29/E29-D03.md)",
)
# BQ-34: the version line's pinned inputs and their shas (the boards ride with each file).
PINNED = {
    CITE_FILES["D01"]: "9da45ae353",
    CITE_FILES["D02"]: "75a33c1640",
    CITE_FILES["D03"]: "af18afb25c",
    CITE_FILES["D04"]: "932495cbe9",
    CITE_FILES["D04H"]: "932495cbe9",
    CITE_FILES["D05"]: "966f9edcd9",
}
IMG_DIR = "docs/design/E29/img"
# BQ-25: the D05 sections lifted as they stand (D05:670), with their line spans.
LIFTED = (
    ("§5.1–§5.4", 171, 190, "d05.s5"),
    ("§6.1–§6.3", 194, 226, "d05.s6"),
    ("§7.1–§7.2", 230, 254, "d05.s7"),
    ("§8.1–§8.4", 258, 297, "d05.s8"),
    ("§9.1", 301, 323, "d05.s9"),
    ("§10", 339, 353, "d05.s10"),
    ("§11.1–§11.3", 357, 367, "d05.s11"),
    ("§12", 369, 388, "d05.s12"),
    ("§13's Replacement column", 392, 404, "d05.s13"),
    ("§14", 408, 520, "d05.s14"),
)
# BQ-11 as RULED (ruling 6442970686, BQ-11 re-pointed 15:29Z): the E05 slice per change request, and the core-path set.
RULED_SLICE = {
    "CMP-057": "E05-S03 (#266)",
    "CMP-011": "E05-S02 (#265)",
    "CMP-099": "E05-S03 (#266)",
    "CMP-100": "E05-S03 (#266)",
    "CMP-019": "E05-S02 (#265) via E05-T06 (#271)",
    "CMP-028": "E05-S03 (#266)",
    "CMP-078": "E05-S03 (#266)",
    "CMP-239": "E05-S03 (#266)",
    "CMP-055": "E05-S03 (#266)",
    "CMP-075": "E05-S03 (#266)",
    "CMP-139": "E05-S03 (#266)",
    "height": "none: token-level, P-02 (BQ-27)",
}
CORE_CR = ("CMP-057", "CMP-011", "CMP-099", "CMP-100")
CR_ROWS = range(257, 269)  # D04H's change-request index rows
# BQ-23 as RULED: the landing class of each F row.
F_LANDING = {
    "F-01": "carried here",
    "F-02": "carried here",
    "F-04": "carried here",
    "F-09": "carried here",
    "F-03": "E29-T09 (#1029) applies",
    "F-05": "E29-T09 (#1029) applies",
    "F-06": "recorded to E05",
    "F-07": "recorded to E05",
    "F-11": "recorded to E05",
    "F-08": "the pointer",
    "F-10": "accepted",
}
F_PROPOSED = ("F-01", "F-02", "F-03", "F-04", "F-05", "F-09")
F_LANE = {"F-06": "the E05 token lane", "F-07": "the E05 token lane", "F-11": "E05-S03 (#266)"}
# lens 3 (m1): the stories each carried F row reaches (`15`'s CMP-049 is E29-S01's; SCR-078 S04's)
F_CONSUMERS = {
    "F-01": ("E29-S01", "E29-S02"),
    "F-02": ("E29-S01", "E29-S04"),
    "F-03": ("E29-S01", "E29-S02", "E29-S04"),
    "F-04": ("E29-S01", "E29-S04"),
    "F-05": ("E29-S01", "E29-S02"),
    "F-09": ("E29-S07",),
    "F-10": ("E29-S07",),
}
# BQ-21: the gap ids the ledger must hold (the union of D02, D03, D04 and D05) and the blockers.
G_UNION = (
    [f"D03 G{n}" for n in range(1, 21)]
    + [f"D04-G{n}" for n in range(1, 10)]
    + [f"D05 G-{n:02d}" for n in range(1, 10)]
    + [f"D02 gap {n}" for n in (11, 12, 13)]
    + ["G-P", "G-O"]
    + [f"G-W{n}" for n in range(1, 5)]
)
G_BLOCKING = {
    "G-P": "E29-S01, E29-S02, E29-S04",
    "G20": "E29-S04",
    "G7": "E29-S04",
    "G1": "E29-S07",
    "G15": "E29-S07",
}
# BQ-21's union by id: each id's consumers (lens 3, M5); a row holds ids with the same consumers.
G_CONSUMER = {
    **{f"D03 G{n}": "E29-S04" for n in (2, 3, 4, 5, 6, 8, 9, 12, 13, 18)},
    **{f"D03 G{n}": "E29-S07" for n in (10, 11, 14, 16, 17, 19)},
    **dict.fromkeys(("D04-G1", "D04-G2", "D04-G4", "D04-G7", "D05 G-01", "D02 gap 13"), "E29-S01"),
    "D05 G-02": "E29-S01, E29-S02",
    "D04-G8": "E29-S02",
    "D05 G-03": "E29-S02",
    "D05 G-04": "E29-S01, E29-S04",
    "D04-G9": "E29-S01, E29-S02, E29-S04",
    "D02 gap 11": "E29-S01, E29-S02, E29-S06",
    "D04-G5": "E29-S04",
    "D04-G3": "E29-S06",
    **dict.fromkeys(("D04-G6", "D05 G-05", "D05 G-06", "D02 gap 12", "G-O"), "E29-S07"),
    **{f"D05 G-0{n}": "E29-Q05" for n in (7, 8, 9)},
    "G-P": G_BLOCKING["G-P"],
    "D03 G20": G_BLOCKING["G20"],
    "D03 G7": G_BLOCKING["G7"],
    "D03 G1": G_BLOCKING["G1"],
    "D03 G15": G_BLOCKING["G15"],
    # orchestrator lens 1 (Major 1): §14's dry-run carries, each due at its earliest consumer
    "G-W1": "E29-Q02, E29-Q03, E29-Q05, E29-D07",
    "G-W2": "E29-S01, E29-S02, E29-S04, E29-S06, E29-S07, E29-Q03, E29-X02",
    "G-W3": "E29-S01, E29-S03, E29-S05, E29-S06, E29-S07, E29-Q01, E29-X02",
    "G-W4": "E29-S08",
}
GP_SPRINT = "Sprint 19 against the consumers' sprints"  # lens 1: the ruling's framing of G-P
# BQ-27: the open-question union by id.
LOG_UNION = (
    [f"D01 OQ-{n}" for n in range(1, 14)]
    + [f"D02 OQ-{c}" for c in "ABCDEFGHIJKLMNOPQRST"]
    + [f"D03 OQ-{n}" for n in range(1, 21)]
    + [f"D04H Q-{n}" for n in range(1, 23)]
    + [f"D05 Q-{n:02d}" for n in range(1, 8)]
    + ["P-01", "P-02", "P-03", "P-04"]
)
LOG_CORE = ("D02 OQ-E", "D02 OQ-R", "D02 OQ-Q", "D01 OQ-3", "D03 OQ-10", "D03 OQ-5", "D03 OQ-12")
# lens 3 (m3): items that bind a story are due at its start, not at E29-T09's.
LOG_BINDS = {
    **{f"D04H Q-{n}": "E29-S01" for n in (2, 3, 4, 7, 8, 15, 16, 17, 20, 21)},
    "D04H Q-5": "E29-S02",
    **{f"D04H Q-{n}": "E29-S07" for n in (1, 6, 19)},
    "P-03": "E29-S04",
    "P-04": "E29-S02",
}
NO_DEFAULT = re.compile(r"decided nowhere|not decided|undecided|to be decided|no default|\bTBD\b")
CONSUMER_ISSUES = (
    "#911", "#912", "#978", "#979", "#981", "#1028", "#1151",
    "#844", "#1147", "#977", "#1149", "#1146", "#982", "#1029",
)  # fmt: skip
SCREENS = ("SCR-063", "SCR-078", "SCR-152")
STATUSES = ("merged", "registered", "PROPOSED")
ANNOUNCE = ("polite", "assertive", "none")
OWNERS = ("E29-D02", "E29-D03", "E29-D04", "E09-D09", "E30-D02", "E39-D01", "E17-D01", "E32-D01")
DECK_TOP = ("pack", "version", "base", "strings")
# lens 3 (M3): a data-bound span of a string, and its kind; `fixed` may stand for a number's kind.
SPAN = re.compile(
    r"(?P<ph>\{[^{}]+\})"
    r"|(?P<dt>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)"
    r"|(?P<tw>\d\d:\d\d(?::\d\d)?–\d\d:\d\d(?::\d\d)?)"
    r"|(?P<tm>\d\d:\d\d(?::\d\d)?)"
    r"|(?P<ns>\bN ?s\b)"
    r"|(?P<id>…[0-9a-f]{4})"
    r"|(?P<acct>\b(?:Main|Sub-\d)\b)"
    r"|(?P<env>\b(?:LIVE|DEMO)\b)"
    r"|(?P<sym>\b[A-Z]{3,}USDT\b)"
    r"|(?P<side>[▲▼] (?:Buy|Sell)|\b(?:Buy|Sell|long|short)\b)"
    r"|(?P<num>[−+]?\d[\d,]*(?:\.\d+)?(?: ?%| s\b| m\b| ticks\b| (?:BTC|ETH|SOL)\b| USDT\b)?)"
)
SPAN_KIND = {
    "ph": "placeholder",
    "dt": "date-time (UTC)",
    "tw": "time window (UTC)",
    "tm": "time (UTC)",
    "ns": "duration",
    "id": "short id",
    "acct": "account label",
    "env": "environment",
    "sym": "symbol",
    "side": "side",
}


def span_kind(m: re.Match[str]) -> str:
    v = m[0]
    if m.lastgroup != "num":
        return SPAN_KIND[str(m.lastgroup)]
    for end, kind in (("%", "percentage"), (" s", "duration"), (" m", "duration")):
        if v.endswith(end):
            return kind
    for end, kind in (("ticks", "ticks"), ("BTC", "quantity"), ("ETH", "quantity")):
        if v.endswith(end):
            return kind
    if v.endswith("SOL"):
        return "quantity"
    if v.endswith("USDT"):
        return "money (USDT)"
    return "figure" if "." in v else "count"


def spans_of(s: str) -> dict[str, tuple[str, bool]]:
    """Each data-bound span of a deck string: (its kind, whether it is a number)."""
    out: dict[str, tuple[str, bool]] = {}
    for m in SPAN.finditer(s):
        out.setdefault(m[0], (span_kind(m), m.lastgroup == "num"))
    return out


# `14`:1478's SCR-063 States line: each catalogued state word and the S row that carries it.
STATES_14 = {
    "loading": ("S-01", "Loading"),
    "empty": ("S-03", "Empty"),
    "reconciling": ("S-14", "Reconciling"),
    "desync warning": ("S-15", "desync"),
    "liq-proximity": ("S-09", "Liquidation proximity"),
    "frozen/lockout": ("S-21", "Risk lockout"),
    "viewer read-only": ("S-22", "Viewer read-only"),
}
# The source spans every state of which a row must cover (D02 §10.1, D03 §3.7, D03 §4.1).
STATE_SPANS = (("D02", 388, 400), ("D03", 183, 196), ("D03", 212, 219))
FEATURES_DIR = "apps/web/src/features/"
CHARSET_ALLOW = frozenset("…")
UNIT = r"(?:px|ms|s|%|fps|Hz|rows?|fills?|boards?|frames?|strings?|keys?|questions?|items?|ids?)"

Values = dict[str, str]
Finding = tuple[str, str, str | None, str | None]  # (gate, message, doc, section key)

# ---------------------------------------------------------------------------- reading


@functools.lru_cache(maxsize=512)
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


@functools.lru_cache(maxsize=256)
def git_out(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.decode("utf-8") if out.returncode == 0 else ""


def at_base(rel: str) -> str:
    text = git_show(BASE, rel)
    if text is None:
        raise SystemExit(f"FAIL parse: {rel} is not readable at {BASE}")
    return text


def cite_path(doc: str) -> str | None:
    return PLAN.get(doc) or CITE_FILES.get(doc)


def base_lines(doc: str) -> list[str]:
    rel = cite_path(doc)
    if rel is None:
        return []
    text = git_show(BASE, rel)
    return text.split("\n") if text is not None else []


def tree_at(rev: str, prefix: str) -> tuple[str, ...]:
    return tuple(n for n in git_out("ls-tree", "--name-only", rev, prefix).split("\n") if n)


@functools.lru_cache(maxsize=1)
def merge_base() -> str:
    return git_out("merge-base", "HEAD", HEAD).strip()


def last_commit(rev: str, rel: str) -> str:
    return git_out("log", "-1", "--format=%H", rev, "--", rel).strip()


# ---------------------------------------------------------------------------- markdown

COMMENT = re.compile(r"<!--(?:>|->|.*?--!?>|.*\Z)", re.DOTALL)
_HIDDEN = re.compile(COMMENT.pattern + r"|[\u00ad\u200b-\u200d\u2060\ufeff]", re.DOTALL)
PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"')
HEADING = re.compile(r"^(#{1,6}) (.*)$")


def strip_comments(text: str) -> str:
    return _HIDDEN.sub("", text)


def section(text: str, head: str) -> str:
    """From the heading starting with `head` to the next heading of the same or a higher level."""
    lines = text.split("\n")
    start, level = -1, 0
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if m and m[2].startswith(head):
            start, level = i, len(m[1])
            break
    if start < 0:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = HEADING.match(lines[j])
        if m and len(m[1]) <= level:
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
    """Every data row of the tables in `block` (header and rule rows dropped)."""
    out: list[list[str]] = []
    lines = block.split("\n")
    for i, ln in enumerate(lines):
        if not ln.startswith("|") or is_rule(ln):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if is_rule(nxt):
            continue
        out.append(split_row(ln))
    return out


def pin_norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sec_key(heading: str) -> str:
    """A `##` section's key: its number, "RULED" for the ruling's heading (so G-RULED and the pins
    name one section, orchestrator lens 1), or its first word for the other unnumbered ones."""
    t = heading.lstrip("# ").strip()
    m = re.match(r"(\d+)\.", t)
    if m:
        return f"§{m[1]}"
    return "RULED" if "— RULED" in t else t.split()[0] if t else "(top)"


def sec_of_line(text: str, line_no: int) -> str:
    cur = "(top)"
    for ln in text.split("\n")[:line_no]:
        m = HEADING.match(ln)
        if m and len(m[1]) <= 2:
            cur = sec_key(m[2])
    return cur


def h2(text: str, key: str) -> str:
    """The `##` section whose key is `key` (e.g. "§3", "Acceptance-criteria")."""
    for ln in text.split("\n"):
        m = HEADING.match(ln)
        if m and len(m[1]) == 2 and sec_key(m[2]) == key:
            return section(text, m[2])
    return ""


def sections(text: str) -> list[tuple[str, str]]:
    """Every `##` section as (key, block), the text before the first one as "(top)"."""
    out: list[tuple[str, list[str]]] = [("(top)", [])]
    for ln in text.split("\n"):
        m = HEADING.match(ln)
        if m and len(m[1]) <= 2:
            out.append((sec_key(m[2]), []))
        out[-1][1].append(ln)
    return [(k, "\n".join(v)) for k, v in out]


def rendered(text: str) -> str:
    """Rendered text: comments dropped (values stay), code spans kept as their content."""
    return strip_comments(text)


_DASHES = re.compile(r"[\u2010-\u2015\u2212-]")


def norm_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", strip_comments(text))
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[*`]", "", t)
    return " ".join(_DASHES.sub(" ", t).split()).lower()


# ---------------------------------------------------------------------------- negation

NEG_WORD = r"(?:no|never|not|nor|without|nothing|none|cannot)"
DOUBTING = re.compile(r"\b(?:doubt|den(?:y|ies|ied)|disput|question|skip|miss|lack|refus|fail)\w*")


def unquote(clause: str) -> str:
    """Quoted copy is never a claim, but a quote of one or two words is read as prose."""
    return QUOTED.sub(lambda m: m[0][1:-1] if len(m[0][1:-1].split()) <= 2 else " ", clause)


def live(clause: str, term: str) -> bool:
    """`term` asserted in `clause` once each negated mention is removed: a negation covers its own
    term at most six words after it, within its phrase (never across `:`, `;` or `,`) and never
    past a doubting verb ("no reviewer doubts …" asserts the term)."""
    t = norm_text(unquote(clause))

    def drop(m: re.Match[str]) -> str:
        return m[0] if DOUBTING.search(m[1]) else " "

    t = re.sub(rf"\b{NEG_WORD}\b((?:\s+[^\s:;,]+){{0,6}}?)\s+(?:{term})", drop, t)
    return re.search(term, t) is not None


SENTENCE = re.compile(r";\s|(?<=[.!?])\s+|\s—\s")


def clauses(text: str) -> list[str]:
    out: list[str] = []
    for ln in strip_comments(text).split("\n"):
        if ln.startswith("|"):
            out += [c for cell in split_row(ln) for c in SENTENCE.split(cell) if c.strip()]
        elif ln.strip() and not ln.startswith("#"):
            out += [c for c in SENTENCE.split(ln) if c.strip()]
    return out


# ---------------------------------------------------------------------------- the texts


@dataclass
class Texts:
    spec: str
    deck: str
    disk: dict[str, str]  # the untouched files and `14`, from the working tree
    stray: tuple[str, ...]  # changed paths outside OWN (git status)
    handoffs: tuple[str, ...]  # any E29-D06 hand-off file present
    head_commits: dict[str, str] = field(default_factory=dict)  # G-VERSION: last commit at HEAD
    values: Values | None = None  # frozen values (self-test); None = computed
    head_ok: bool = True  # G-VERSION: `origin/main` resolves
    mb: str = ""  # G-UNTOUCHED: `git merge-base HEAD origin/main` ("" = unresolved)


def stray_of(diff_names: str, untracked: str) -> tuple[str, ...]:
    """Paths changed against the merge-base (committed or not) or untracked, outside the pack."""
    paths = {p.strip() for p in f"{diff_names}\n{untracked}".split("\n") if p.strip()}
    return tuple(sorted(p for p in paths if p not in OWN))


def load() -> Texts:
    spec = (ROOT / SPEC_REL).read_text(encoding="utf-8")
    deck = (ROOT / DECK_REL).read_text(encoding="utf-8")
    disk = {
        rel: (ROOT / rel).read_text(encoding="utf-8")
        for rel in (*UNTOUCHED, PLAN14)
        if (ROOT / rel).exists()
    }
    mb = merge_base()
    head_ok = bool(git_out("rev-parse", "--verify", "--quiet", f"{HEAD}^{{commit}}").strip())
    diff = git_out("diff", "--name-only", mb) if mb else ""
    stray = stray_of(diff, git_out("ls-files", "--others", "--exclude-standard"))
    handoffs = tuple(
        str(p.relative_to(ROOT)) for p in (ROOT / "docs/design/E29").glob("E29-D06*handoff*")
    )
    heads = {rel: last_commit(HEAD, rel) for rel in [*PINNED, IMG_DIR]}
    return Texts(spec, deck, disk, stray, handoffs, heads, head_ok=head_ok, mb=mb)


def deck_entries(t: Texts) -> list[dict[str, object]]:
    """The deck's entries in order, each with its `key` (the object key without `#n`) and its
    `variant` (n, else 1). The deck is an object keyed by id, so no `"key": value` line exists
    for the secret scanners to read."""
    data, _dups = parse_deck(t.deck)
    if not isinstance(data, dict) or not isinstance(data.get("strings"), dict):
        return []
    out: list[dict[str, object]] = []
    for eid, e in data["strings"].items():
        if isinstance(e, dict):
            key, _, var = str(eid).partition("#")
            out.append({"key": key, "variant": int(var) if var.isdigit() else 1, **e})
    return out


def parse_deck(text: str) -> tuple[object, list[str]]:
    """The deck as JSON (None when it is not) and every key a JSON object repeats."""
    dups: list[str] = []

    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: set[str] = set()
        for k, _v in pairs:
            if k in seen:
                dups.append(k)
            seen.add(k)
        return dict(pairs)

    try:
        return json.loads(text, object_pairs_hook=hook), dups
    except json.JSONDecodeError:
        return None, dups


def entry_text(e: dict[str, object]) -> str:
    return str(e.get("string", e.get("rule", "")))


def entry_id(e: dict[str, object]) -> str:
    v = e.get("variant", 1)
    return f"{e.get('key')}" + (f"#{v}" if v != 1 else "")


ENTRY_FIELDS = (
    "string", "rule", "renders", "params", "screen", "owner", "status", "announce", "source",
    "key_status", "safety",
)  # fmt: skip
SAFETY_KEYS = (
    "acct.reassure.true", "acct.reassure.false", "sl.note", "blotter.ui.bulk.excluded",
    "blotter.ui.close.stop_stays",
)  # fmt: skip


# ---------------------------------------------------------------------------- values


def cal_start(n: int) -> str:
    cal = at_base(CITE_FILES["CAL"])
    m = re.search(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", cal)
    d = re.search(r"SPRINT_DAYS = (\d+)", cal)
    if not m or not d:
        raise SystemExit("FAIL parse: calendar_cv.py")
    start = datetime.date(int(m[1]), int(m[2]), int(m[3]))
    return (start + datetime.timedelta(days=(n - 1) * int(d[1]))).isoformat()


@functools.lru_cache(maxsize=1)
def sprints() -> dict[str, int]:
    data = json.loads(at_base(CITE_FILES["E29.json"]))
    items = data if isinstance(data, list) else data.get("tickets", [])
    out: dict[str, int] = {}
    for it in items:
        m = re.search(r"(\d+)", str(it.get("sprint", "")))
        if m:
            out[str(it.get("key"))] = int(m[1])
    return out


def boards(prefix: str) -> set[str]:
    names = tree_at(BASE, IMG_DIR + "/")
    return {
        m[1]
        for n in names
        if (m := re.match(rf"{IMG_DIR}/{prefix}-(\d\d)-[a-z0-9-]+\.png$", n))
        and not re.search(r"-(greyscale|deuteranopia)\.png$", n)
    }


def lifted_hash(rev: str, a: int, b: int) -> str:
    text = git_show(rev, CITE_FILES["D05"]) or ""
    chunk = "\n".join(text.split("\n")[a - 1 : b])
    return hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:12]


CITE_FIGURES = {
    "perf.rows": ("14", 1481, r"handles (\d+) rows"),
    "perf.fps": ("14", 1481, r"at (\d+) fps"),
    "perf.pos.hz": ("14", 1481, r"coalesced at (\d+) Hz"),
    "perf.fills": ("14", 1749, r"a ([\d,]+)-fill session"),
    "perf.ms": ("14", 1749, r"exceeding (\d+) ms"),
    "perf.fill.hz": ("14", 1749, r"coalesced to (\d+) Hz"),
}


def expand_ids(cell: str) -> list[str]:
    """Ids in a cell: `D03 OQ-1–OQ-4, OQ-6`, `D04H Q-1–Q-8`, `D04-G1–G9`, `D05 G-01–G-09`,
    `D03 G2–G6, G8`, `D02 gaps 11–13`, `P-01`, `G-P`, `G20` (a bare G is D03's)."""
    out: list[str] = []
    for part in re.split(r";\s*", strip_comments(cell)):
        part = part.replace("`", "").strip()
        m = re.match(r"(D0[1-5]H?)\s+(.*)$", part)
        src = m[1] if m else ""
        body = m[2] if m else part
        g = re.match(r"gaps? (\d+)(?:[–-](\d+))?$", body)
        if src == "D02" and g:
            out += [f"D02 gap {n}" for n in range(int(g[1]), int(g[2] or g[1]) + 1)]
            continue
        d4 = re.findall(r"D04-G(\d+)(?:[–-]G(\d+))?", part)
        if d4 and re.fullmatch(r"D04-G\d+(?:[–-]G\d+)?(?:,\s*D04-G\d+(?:[–-]G\d+)?)*", part):
            out += [f"D04-G{n}" for a, b in d4 for n in range(int(a), int(b or a) + 1)]
            continue
        for tok in re.split(r",\s*", body):
            tok = tok.strip()
            r = re.match(r"(OQ|Q|G|G-)-?([A-Z0-9]+)[–-](?:OQ|Q|G)?-?([A-Z0-9]+)$", tok)
            one = re.match(r"(OQ-|Q-|G-|G|P-)([A-Z0-9]+)$", tok)
            if r:
                kind = tok.split("-")[0] if tok.startswith(("OQ", "Q-")) else "G"
                lo, hi = r[2], r[3]
                if lo.isdigit() and hi.isdigit():
                    seq = [str(n).zfill(len(lo)) for n in range(int(lo), int(hi) + 1)]
                else:
                    seq = [chr(c) for c in range(ord(lo), ord(hi) + 1)]
                dash = "-" if tok.startswith(("OQ", "Q", "G-")) else ""
                kind = "G-" if tok.startswith("G-") else kind
                for s in seq:
                    out.append(fmt_id(src, f"{kind}{'' if kind.endswith('-') else dash}{s}"))
            elif one:
                out.append(fmt_id(src, tok))
    return out


def fmt_id(src: str, tok: str) -> str:
    if tok.startswith("P-") or tok == "G-P":
        return tok
    if not src and re.match(r"G\d+$", tok):
        return f"D03 {tok}"
    return f"{src} {tok}".strip()


def compute(t: Texts) -> Values:
    if t.values is not None:
        return t.values
    v: Values = {}
    d02, d03, d04 = boards("E29-D02"), boards("E29-D03"), boards("E29-D04")
    d01 = [n for n in tree_at(BASE, IMG_DIR + "/") if "/E29-D01-" in n]
    renders = [
        n
        for n in tree_at(BASE, IMG_DIR + "/")
        if re.search(r"E29-D03-.*-(greyscale|deuteranopia)\.png$", n)
    ]
    v["COUNT:boards.d02"], v["COUNT:boards.d03"], v["COUNT:boards.d04"] = (
        str(len(d02)), str(len(d03)), str(len(d04))
    )  # fmt: skip
    v["COUNT:frames.d01"], v["COUNT:renders.d03"] = str(len(d01)), str(len(renders))
    v["COUNT:boards.merged"] = str(len(d02) + len(d03) + len(d04))
    v["COUNT:boards.all"] = str(len(d02) + len(d03) + len(d04) + len(d01))
    s3 = table_rows(h2(t.spec, "§3"))
    v["COUNT:states"] = str(sum(1 for r in s3 if re.match(r"S-\d\d$", r[0])))
    entries = deck_entries(t)
    v["COUNT:deck.entries"] = str(len(entries))
    v["COUNT:deck.strings"] = str(sum(1 for e in entries if "string" in e))
    v["COUNT:deck.rules"] = str(sum(1 for e in entries if "rule" in e))
    v["COUNT:deck.keys"] = str(len({e.get("key") for e in entries}))
    v["COUNT:deck.safety"] = str(sum(1 for e in entries if e.get("safety") is True))
    for st in ("merged", "registered", "PROPOSED"):
        v[f"COUNT:deck.{st.lower()}"] = str(sum(1 for e in entries if e.get("status") == st))
    crs = cr_rows(t.spec)
    v["COUNT:cr"] = str(len(crs))
    v["COUNT:cr.core"] = str(sum(1 for r in crs if len(r) > 4 and r[4].startswith("core path")))
    gl = g_rows(t.spec)
    v["COUNT:g.ids"] = str(len({i for r in gl for i in expand_ids(r[0])}))
    v["COUNT:g.blocking"] = str(sum(1 for r in gl if len(r) > 4 and r[4].startswith("blocks")))
    lr = log_rows(t.spec)
    v["COUNT:log.ids"] = str(len({i for r in lr for i in expand_ids(r[0])}))
    v["COUNT:log.unowned"] = str(sum(1 for r in lr if len(r) < 4 or r[3] in ("", "—")))
    v["COUNT:log.undated"] = str(
        sum(
            1
            for r in lr
            if len(r) < 6 or (not ANCHOR.search(r[5]) and not PLACEHOLDER.search(r[5]))
        )
    )
    v["COUNT:log.nodefault"] = str(
        sum(1 for r in lr if len(r) < 3 or r[2] in ("", "—") or NO_DEFAULT.search(r[2]))
    )
    v["COUNT:walk"] = str(len(re.findall(r"\bW-(\d+)\b", h2(t.spec, "§14"))))
    for key, n in sprints().items():
        v[f"DATE:{key}"] = cal_start(n)
    for _label, a, b, key in LIFTED:
        v[f"HASH:{key}"] = lifted_hash(D05_SHA, a, b)
    for key, (doc, n, rx) in CITE_FIGURES.items():
        m = re.search(rx, base_lines(doc)[n - 1]) if len(base_lines(doc)) >= n else None
        v[f"CITE:{key}"] = m[1] if m else "?"
    return v


def table_of(block: str, lead: str) -> list[list[str]]:
    """The data rows of the one table in `block` whose header's lead cell is `lead` (so a deleted
    paragraph between two tables fails only the gate that owns that paragraph, lens 1)."""
    rows: list[list[str]] = []
    inside = False
    lines = block.split("\n")
    for i, ln in enumerate(lines):
        if not ln.startswith("|"):
            inside = False
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if is_rule(nxt):
            inside = split_row(ln)[0] == lead
        elif inside and not is_rule(ln):
            rows.append(split_row(ln))
    return rows


def cr_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§4"), "CR")


def cmp_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§4"), "CMP")


def g_rows(spec: str) -> list[list[str]]:
    return table_rows(h2(spec, "§9"))


def log_rows(spec: str) -> list[list[str]]:
    return table_rows(h2(spec, "§12"))


# ---------------------------------------------------------------------------- fill


def code_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in CODE.finditer(line)]


def fill(text: str, values: Values) -> tuple[str, list[str]]:
    """Write each placeholder as `VALUE<!--=KIND:key-->` and refresh each anchored value."""
    missing: list[str] = []

    def ph(m: re.Match[str]) -> str:
        if m[1] not in values:
            missing.append(m[1])
            return m[0]
        return f"{values[m[1]]}<!--={m[1]}-->"

    def an(m: re.Match[str]) -> str:
        if m[2] not in values:
            missing.append(m[2])
            return m[0]
        return f"{values[m[2]]}<!--={m[2]}-->"

    text = PLACEHOLDER.sub(ph, text)
    text = OLD_VALUE.sub(an, text)
    return text, missing


OLD_VALUE = re.compile(r"(?<![\w.,])([0-9a-f?][0-9a-f,.-]*)?<!--=([A-Z]+:[^>]+?)-->")


def unvalued(line: str, values: Values) -> str:
    """The line with each anchored value cut to its anchor (so `--fill` never moves a pin)."""
    line = PLACEHOLDER.sub(lambda m: f"<!--={m[1]}-->", line)
    out, pos = [], 0
    for m in ANCHOR.finditer(line):
        pre, want = line[pos : m.start()], values.get(m[1], "")
        out += [pre[: len(pre) - len(want)] if want and pre.endswith(want) else pre, m[0]]
        pos = m.end()
    return "".join(out) + line[pos:]


# ---------------------------------------------------------------------------- the gates


def F(gate: str, msg: str, doc: str | None = "spec", sec: str | None = None) -> Finding:
    return (gate, msg, doc, sec)


def g_anchor(t: Texts) -> list[Finding]:
    v = compute(t)
    bad: list[Finding] = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        sec = sec_of_line(t.spec, i)
        for m in PLACEHOLDER.finditer(ln):
            bad.append(F("G-ANCHOR", f"line {i}: unfilled {{{{{m[1]}}}}}", "spec", sec))
        for m in ANCHOR.finditer(ln):
            key = m[1]
            if key not in v:
                bad.append(F("G-ANCHOR", f"line {i}: unknown anchor {key}", "spec", sec))
                continue
            pre = ln[: m.start()]
            want = v[key]
            if not pre.endswith(want):
                got = re.search(r"[^\s(|]*$", pre)
                bad.append(
                    F("G-ANCHOR", f"line {i}: {key} reads {got[0] if got else ''!r}, is {want}",
                      "spec", sec)
                )  # fmt: skip
                continue
            left = pre[: len(pre) - len(want)]
            if left and (left[-1].isalnum() or left[-1] in ".,"):
                bad.append(
                    F("G-ANCHOR", f"line {i}: {key}'s value has no left boundary", "spec", sec)
                )
    return bad


def g_marker(t: Texts) -> list[Finding]:
    bad = []
    for m in COMMENT.finditer(t.spec):
        if not re.fullmatch(r"<!--=[A-Z]+:[^>]+?-->", m[0]):
            n = t.spec[: m.start()].count("\n") + 1
            bad.append(F("G-MARKER", f"line {n}: a comment that is not a value anchor", "spec",
                         sec_of_line(t.spec, n)))  # fmt: skip
    return bad


FIGURE = re.compile(rf"(?<![\w.#:§-])(\d[\d,.]*)\s?(?:-)?{UNIT}\b")


def g_figure(t: Texts) -> list[Finding]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if ln.startswith("#"):
            continue
        work = CODE.sub(" ", ln)
        work = QUOTED.sub(" ", work)
        work = re.sub(r"[^\s(|]*<!--=[A-Z]+:[^>]+?-->", " ", work)
        for m in FIGURE.finditer(work):
            bad.append(F("G-FIGURE", f"line {i}: hand-typed figure {m[0]!r}", "spec",
                         sec_of_line(t.spec, i)))  # fmt: skip
    return bad


CITE_HEAD = re.compile(
    r"`?(?P<doc>\d{2}|D04H|D0[1-5]|E10H|E11-D09|TM29|CONST|CAL|KM|README|E29\.json|E05\.json)`?"
    r":(?P<a>\d+)(?:[–-](?P<b>\d+))?(?P<more>(?:,\s*:\d+(?:[–-]\d+)?)*)"
)


def cites_in(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE_HEAD.finditer(strip_comments(text)):
        doc = m["doc"]
        if re.fullmatch(r"\d{2}", doc) and doc not in PLAN:
            continue
        out.append((doc, int(m["a"]), int(m["b"] or m["a"])))
        for mm in re.finditer(r":(\d+)(?:[–-](\d+))?", m["more"] or ""):
            out.append((doc, int(mm[1]), int(mm[2] or mm[1])))
    return out


def g_cite(t: Texts) -> list[Finding]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for doc, a, b in cites_in(ln):
            lines = base_lines(doc)
            if not lines:
                bad.append(F("G-CITE", f"line {i}: {doc} unreadable at {BASE}", "spec",
                             sec_of_line(t.spec, i)))  # fmt: skip
                continue
            for n in (a, b):
                if not 1 <= n <= len(lines) or not lines[n - 1].strip() or b < a:
                    bad.append(F("G-CITE", f"line {i}: {doc}:{n} is not a line at {BASE}",
                                 "spec", sec_of_line(t.spec, i)))  # fmt: skip
    return bad


METRIC = re.compile(r"`([a-z][a-z0-9_]*_(?:total|seconds)(?:\{[a-z_,]+\})?)`")


def g_quote(t: Texts) -> list[Finding]:
    bad = []
    ticket = at_base(CITE_FILES["E29.json"]).replace('\\"', '"')
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if sec_of_line(t.spec, i) == "§17":
            continue
        work = CODE.sub(" ", strip_comments(ln))
        docs = {d for d, _a, _b in cites_in(ln)}
        pool = [ticket] + ["\n".join(base_lines(d)) for d in docs]
        # a metric name is the source's, byte for byte
        for m in METRIC.finditer(strip_comments(ln)):
            bare = "{" not in m[1]  # a bare name may stand for its labelled form
            if not any(f"`{m[1]}`" in p or (bare and f"`{m[1]}{{" in p) for p in pool):
                bad.append(F("G-QUOTE", f"line {i}: metric `{m[1][:50]}` is not in a cited text",
                             "spec", sec_of_line(t.spec, i)))  # fmt: skip
        for m in QUOTED.finditer(work):
            q = m[0][1:-1]
            if len(q) < 12:
                continue
            if not any(q in p for p in pool):
                bad.append(F("G-QUOTE", f"line {i}: {q[:50]!r} is not verbatim in a cited text",
                             "spec", sec_of_line(t.spec, i)))  # fmt: skip
    return bad


FORBIDDEN_COPY = re.compile(
    r"ret_?msg|ret_?code|oms\.account_|account_(?:stale|desync|resyncing|synced)", re.IGNORECASE
)
PENDING_COPY = re.compile(r"\bTBD\b|\bOPEN\b|\bTODO\b")


def deck_findings(t: Texts) -> list[Finding]:
    bad: list[Finding] = []

    def D(msg: str) -> None:
        bad.append(F("G-DECK", msg, "deck", "strings"))

    data, dups = parse_deck(t.deck)
    if data is None:
        return [F("G-DECK", "the deck is not JSON", "deck", "strings")]
    if dups:
        D(f"repeated keys {dups[:3]} (a parser keeps only one)")
    if not isinstance(data, dict) or tuple(data) != DECK_TOP:
        D(f"the deck's fields are {', '.join(DECK_TOP)}, in that order, and nothing else")
        data = data if isinstance(data, dict) else {}
    if data.get("base") != BASE or data.get("pack") != "E29-D06" or data.get("version") != "v1":
        D("the deck's pack, version or base is wrong")
    members = data.get("strings")
    for k, v in (members.items() if isinstance(members, dict) else []):
        if not isinstance(v, dict):
            D(f"{k}: a member of strings that is not an entry")
    for e in deck_entries(t):
        eid = entry_id(e)
        extra = set(e) - {"key", "variant", *ENTRY_FIELDS}
        if extra:
            D(f"{eid}: unknown fields {sorted(extra)}")
        if ("string" in e) == ("rule" in e):
            D(f"{eid}: exactly one of string or rule")
        if "rule" in e and (e.get("status") != "PROPOSED" or not str(e.get("renders", "")).strip()):
            D(f"{eid}: a rule is PROPOSED and names what it renders (BQ-17)")
        if "rule" not in e and "renders" in e:
            D(f"{eid}: renders belongs to a rule")
        for f_ in ("key", "screen", "owner", "status", "announce", "source"):
            if not isinstance(e.get(f_), str) or not str(e.get(f_)).strip():
                D(f"{eid}: {f_} missing or empty")
        s = entry_text(e)
        if not s.strip():
            D(f"{eid}: string missing or empty")
        want = spans_of(s) if "string" in e else {}
        got = e.get("params", {})
        if not isinstance(got, dict) or ("rule" in e and "params" in e):
            D(f"{eid}: params malformed")
            got = {}
        if set(got) != set(want) or ("params" in e and not got):
            D(f"{eid}: params name {sorted(set(want) ^ set(got))[:3]} wrongly (lens 3, M3)")
        for span, kind in got.items():
            k0, is_num = want.get(span, ("", False))
            if span in want and kind != k0 and not (kind == "fixed" and is_num):
                D(f"{eid}: params {span!r} is a {k0}, not {kind!r}")
        if e.get("screen") not in SCREENS:
            D(f"{eid}: screen {e.get('screen')!r}")
        if e.get("status") not in STATUSES:
            D(f"{eid}: status {e.get('status')!r}")
        if e.get("announce") not in ANNOUNCE:
            D(f"{eid}: announce {e.get('announce')!r}")
        if e.get("owner") not in OWNERS:
            D(f"{eid}: owner {e.get('owner')!r}")
        if "key_status" in e and e["key_status"] != "PROPOSED name":
            D(f"{eid}: key_status {e['key_status']!r}")
        if FORBIDDEN_COPY.search(s):
            D(f"{eid}: internal taxonomy or exchange text in user copy (T Sec)")
        safety = "still work" in s or e.get("key") in SAFETY_KEYS
        if bool(e.get("safety")) != safety or e.get("safety") not in (None, True):
            D(f"{eid}: a safety statement is marked `safety`, and only one (BQ-19)")
        if PENDING_COPY.search(s):
            D(f"{eid}: marked TBD or OPEN (AC2)")
        src = cites_in(str(e.get("source", "")))
        if len(src) != 1:
            D(f"{eid}: source must be one cite")
            continue
        doc, a, _b = src[0]
        lines = base_lines(doc)
        if not 1 <= a <= len(lines) or s not in wholes(lines[a - 1], "rule" in e):
            D(f"{eid}: not a whole quote, cell or clause at {doc}:{a} (lens 1: no substring)")
    return bad


QUOTE_SENT = re.compile(r"(?<=[.!?…])\s+")


def wholes(line: str, rule: bool) -> set[str]:
    """The whole units a deck string may equal on its source line (lens 1, carry 4: whole-string
    equality, never a substring). A unit is: the content of a "…" quote; that content less a
    leading glyph and its space (a symbol character, Unicode category S, as D02:323's "⚠ ");
    one whole sentence of a quote (D02:447's two-sentence quote); a whole table cell, or one part
    of a cell that lists alternatives with " / " (D02:334); and, for a `rule` only, one clause of
    the line between `;`, `,`, `:` or parentheses (`15`:477's "the object's own name")."""
    out: set[str] = set()
    for q in re.findall(r'"([^"\n]*)"', line):
        out.add(q)
        g = re.match(r"(\S) (.+)$", q)
        if g and unicodedata.category(g[1]).startswith("S"):
            out.add(g[2])
        out.update(QUOTE_SENT.split(q))
    if line.lstrip().startswith("|"):
        for c in split_row(line):
            out.add(c)
            out.update(c.split(" / "))
    if rule:
        out.update(c.strip() for c in re.split(r"[;,:()]", line))
    return out


def deck_key_set(t: Texts) -> set[str]:
    return {entry_id(e) for e in deck_entries(t)}


def keys_of(cell: str, deck: set[str]) -> tuple[list[str], list[str]]:
    """(the deck ids a Keys cell names, the names it uses that the deck lacks)."""
    found, missing = [], []
    for k in re.findall(r"`([^`]+)`", cell):
        if k in deck:
            found.append(k)
        elif k.endswith(".*") and any(d.startswith(k[:-1]) for d in deck):
            found += [d for d in deck if d.startswith(k[:-1])]
        else:
            missing.append(k)
    return found, missing


def g_states(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    deck = deck_key_set(t)
    rows = [r for r in table_rows(h2(t.spec, "§3")) if re.match(r"S-\d\d$", r[0])]
    covered: set[str] = set()
    spans: list[tuple[str, int, int]] = []
    for n, r in enumerate(rows, 1):
        if r[0] != f"S-{n:02d}":
            bad.append(F("G-STATES", f"{r[0]}: out of sequence (S-{n:02d} expected)", sec="§3"))
        if len(r) != 7:
            continue
        found, missing = keys_of(r[6], deck)
        if not found or missing:
            bad.append(F("G-STATES", f"{r[0]}: keys {missing or 'none'} not in the deck", sec="§3"))
        covered.update(found)
        cs = cites_in(r[4])
        if not cs:
            bad.append(F("G-STATES", f"{r[0]}: no source cite", sec="§3"))
        spans += cs
        if not re.search(r"\b(all|Owner|Manager|Viewer)\b", r[3]):
            bad.append(F("G-STATES", f"{r[0]}: no role", sec="§3"))
        if r[5] != "text":
            bm = re.fullmatch(r"(D0[234]) (\d\d(?:, \d\d)*)", r[5])
            if not bm or not set(bm[2].split(", ")) <= boards(f"E29-{bm[1]}"):
                bad.append(F("G-STATES", f"{r[0]}: board {r[5]!r} is not a merged board", sec="§3"))
    for e in sorted(deck - covered):
        bad.append(F("G-STATES", f"deck key {e} has no state row (AC2)", sec="§3"))
    line14 = base_lines("14")[1477] if len(base_lines("14")) > 1477 else ""
    byid = {r[0]: r for r in rows}
    for word, (sid, label) in STATES_14.items():
        if word not in line14:
            bad.append(F("G-STATES", f"`14`:1478 no longer reads {word!r}", sec="§3"))
        if sid not in byid or label.lower() not in byid[sid][1].lower():
            bad.append(F("G-STATES", f"`14`:1478's {word!r} is not carried by {sid}", sec="§3"))
    for doc, a, b in STATE_SPANS:
        for n in range(a, b + 1):
            if not base_lines(doc)[n - 1].startswith("|"):
                continue
            if not any(d == doc and x <= n <= y for d, x, y in spans):
                bad.append(F("G-STATES", f"the state at {doc}:{n} has no S row", sec="§3"))
    return bad


def g_frames(t: Texts) -> list[Finding]:
    bad = []
    rows = table_rows(h2(t.spec, "§2"))
    if [r[0] for r in rows] != ["D02", "D03", "D04", "D01"]:
        bad.append(F("G-FRAMES", "the frame index must hold D02, D03, D04 and D01", sec="§2"))
    for r in rows:
        if len(r) < 5:
            continue
        page = cites_in(r[2])
        if r[0] != "D01" and (not page or "id" not in base_lines(page[0][0])[page[0][1] - 1]):
            bad.append(F("G-FRAMES", f"{r[0]}: the page cite holds no page id", sec="§2"))
        if r[0] in ("D02", "D03", "D04") and not boards(f"E29-{r[0]}"):
            bad.append(F("G-FRAMES", f"{r[0]}: no PNG at the base", sec="§2"))
    return bad


def g_cmp(t: Texts) -> list[Finding]:
    bad = []
    rows = cmp_rows(t.spec)
    want = ("CMP-114", "CMP-115", "CMP-116", "CMP-129", "CMP-123", "CMP-049", "CMP-105", "CMP-209")
    if [r[0][:7] for r in rows] != list(want):
        bad.append(F("G-CMP", "the component map must hold D04's eight entries in order", sec="§4"))
    for r in rows:
        if len(r) != 6:
            continue
        c15 = cites_in(r[2])
        if not c15 or not base_lines("15")[c15[0][1] - 1].startswith(f"### {r[0][:7]}"):
            bad.append(F("G-CMP", f"{r[0][:7]}: `15` cite is not its heading", sec="§4"))
        ch = cites_in(r[3])
        if not ch or r[0][:7] not in base_lines("D04H")[ch[0][1] - 1]:
            bad.append(F("G-CMP", f"{r[0][:7]}: contract cite does not name it", sec="§4"))
        if not re.fullmatch(r"E29-S0\d", r[5]):
            bad.append(F("G-CMP", f"{r[0][:7]}: story {r[5]!r}", sec="§4"))
        if not storybook_ok(r[0][:7], r[4]):
            bad.append(F("G-CMP", f"{r[0][:7]}: Storybook cite is not its stories", sec="§4"))
    return bad


def storybook_ok(cmp_: str, cell: str) -> bool:
    """A D04H Storybook line of this component (in its own §C block or Table A row); CMP-209 has
    none at the base, which the spec says, with P-03 (lens 1, lens 3 M4)."""
    if cmp_ == "CMP-209":
        return cell == "none at the base; P-03"
    c = cites_in(cell)
    d04h = base_lines("D04H")
    if len(c) != 1 or c[0][0] != "D04H" or not 1 <= c[0][1] <= len(d04h):
        return False
    n = c[0][1]
    line = d04h[n - 1]
    head = next((d04h[i] for i in range(n - 1, -1, -1) if d04h[i].startswith("### ")), "")
    return "Storybook" in line and (cmp_ in line or cmp_ in head)


def g_cr(t: Texts) -> list[Finding]:
    bad = []
    rows = cr_rows(t.spec)
    d04h = base_lines("D04H")
    src_rows = {n: split_row(d04h[n - 1]) for n in CR_ROWS}
    seen = set()
    for r in rows:
        if len(r) != 6:
            bad.append(F("G-CR", f"{r[0]}: cell count", sec="§4"))
            continue
        cmp_ = re.match(r"CMP-\d{3}", r[0])
        key = cmp_[0] if cmp_ else ("height" if "height" in r[0] else r[0])
        seen.add(key)
        if r[2] != RULED_SLICE.get(key):
            bad.append(
                F("G-CR", f"{key}: slice {r[2]!r}, ruled {RULED_SLICE.get(key)!r}", sec="§4")
            )
        c = cites_in(r[1])
        if not c or c[0][0] != "D04H" or c[0][1] not in src_rows:
            bad.append(F("G-CR", f"{key}: owner cite is not a D04H CR row", sec="§4"))
            continue
        src = src_rows[c[0][1]]
        if (cmp_ and cmp_[0] not in src[0]) or (not cmp_ and "height" not in src[0]):
            bad.append(F("G-CR", f"{key}: owner cite names another CR", sec="§4"))
        if r[5] != src[3]:
            bad.append(F("G-CR", f"{key}: status {r[5]!r}, D04H reads {src[3]!r}", sec="§4"))
        core = r[4].startswith("core path")
        if core != (key in CORE_CR):
            bad.append(F("G-CR", f"{key}: core-path marking differs from the ruling", sec="§4"))
        if not cites_in(r[4]):
            bad.append(F("G-CR", f"{key}: the interim is not cited", sec="§4"))
    p02 = next((ln for ln in t.spec.splitlines() if ln.startswith("| P-02 ")), "")
    if not all(w in p02 for w in ("token-level", "size.control.height", "BQ-27", "#2701")):
        bad.append(
            F("G-CR", "P-02 is not stated token-level on the BQ-27 pointer (#2701)", sec="§12")
        )
    if seen != set(RULED_SLICE):
        bad.append(F("G-CR", f"CRs missing: {sorted(set(RULED_SLICE) - seen)}", sec="§4"))
    return bad


def g_frow(t: Texts) -> list[Finding]:
    bad = []
    rows = [r for r in table_rows(h2(t.spec, "§8")) if re.match(r"F-\d\d$", r[0])]
    d05 = base_lines("D05")
    if [r[0] for r in rows] != [f"F-{n:02d}" for n in range(1, 12)]:
        bad.append(F("G-FROW", "F-01..F-11 once each, in order", sec="§8"))
    for r in rows:
        if len(r) != 5:
            continue
        n = 393 + int(r[0][2:])
        if split_row(d05[n - 1])[1] != r[1]:
            bad.append(F("G-FROW", f"{r[0]}: severity differs from D05:{n}", sec="§8"))
        if F_LANDING[r[0]] not in r[3]:
            bad.append(F("G-FROW", f"{r[0]}: landing is not {F_LANDING[r[0]]!r}", sec="§8"))
        if r[0] in F_PROPOSED and "PROPOSED" not in r[2]:
            bad.append(F("G-FROW", f"{r[0]}: the carried contract must stay PROPOSED", sec="§8"))
        if r[0] in F_LANE and F_LANE[r[0]] not in r[3]:
            bad.append(F("G-FROW", f"{r[0]}: landing names no lane ({F_LANE[r[0]]})", sec="§8"))
        if r[4] != "pending (#2701)":
            bad.append(F("G-FROW", f"{r[0]}: close state {r[4]!r}", sec="§8"))
    f10 = next((r for r in rows if r[0] == "F-10"), [])
    if f10 and "accepted with its rationale, not rewritten" not in f10[2]:
        bad.append(F("G-FROW", "F-10 is accepted with its rationale, not rewritten", sec="§8"))
    return bad


def g_lift(t: Texts) -> list[Finding]:
    bad = []
    rows = table_rows(h2(t.spec, "§7"))
    if len(rows) != len(LIFTED):
        bad.append(F("G-LIFT", f"{len(rows)} lifted rows, D05:670 names {len(LIFTED)}", sec="§7"))
    for r, (label, a, b, key) in zip(rows, LIFTED, strict=False):
        if r[0] != label or cites_in(r[1]) != [("D05", a, b)]:
            bad.append(F("G-LIFT", f"{label}: row reads {r[0]!r} {r[1]!r}", sec="§7"))
        if f"<!--=HASH:{key}-->" not in r[2] and f"{{{{HASH:{key}}}}}" not in r[2]:
            bad.append(F("G-LIFT", f"{label}: hash anchor missing", sec="§7"))
        here = {rev: lifted_hash(rev, a, b) for rev in (D05_SHA, BASE)}
        if len(set(here.values())) != 1:
            bad.append(F("G-LIFT", f"{label}: drifted between {D05_SHA} and {BASE}", sec="§7"))
    if "PROPOSED, owner approval pending (#2701)" not in next(
        (r[3] for r in rows if r[0] == "§8.1–§8.4"), ""
    ):
        bad.append(
            F("G-LIFT", "the RT table is PROPOSED, owner approval pending (#2701)", sec="§7")
        )
    return bad


def g_grows(t: Texts) -> list[Finding]:
    bad = []
    rows = g_rows(t.spec)
    ids: list[str] = []
    for r in rows:
        ids += expand_ids(r[0])
    missing = [g for g in G_UNION if g not in ids]
    dup = [g for g, c in Counter(ids).items() if c > 1]
    if missing or dup:
        bad.append(F("G-GROWS", f"gap union: missing {missing[:4]}, repeated {dup[:4]}", sec="§9"))
    for r in rows:
        for gid in expand_ids(r[0]):
            if len(r) >= 4 and gid in G_CONSUMER and r[3] != G_CONSUMER[gid]:
                bad.append(F("G-GROWS", f"{gid}: consumers {G_CONSUMER[gid]} (BQ-21)", sec="§9"))
    byid = {r[0]: r for r in rows}
    for gid, consumer in G_BLOCKING.items():
        r = byid.get(gid, [])
        if len(r) < 5 or r[3] != consumer or not r[4].startswith("blocks"):
            bad.append(F("G-GROWS", f"{gid}: blocks {consumer} (BQ-21)", sec="§9"))
    gp = byid.get("G-P", [])
    if len(gp) == 5 and not (
        "#4207" in gp[1] and "the owner item on #2701" in gp[2] and "nothing proposed here" in gp[4]
    ):
        bad.append(
            F(
                "G-GROWS",
                "G-P names E29-T13 (#4207), the owner item on #2701, nothing proposed",
                sec="§9",
            )
        )
    if GP_SPRINT not in "".join(gp[1:2]) or sprints().get("E29-T13") != 19:
        bad.append(F("G-GROWS", f"G-P names {GP_SPRINT!r} (BQ-21; E29-T13's sprint)", sec="§9"))
    for gid in (g for g in G_CONSUMER if g.startswith("G-W")):
        r = byid.get(gid, [])
        first = min(G_CONSUMER[gid].split(", "), key=lambda k: (sprints().get(k, 99), k))
        due = re.search(rf"due (?:[\d-]+<!--=DATE:{first}-->|{{{{DATE:{first}}}}})$", r[-1])
        if len(r) != 5 or not due:
            bad.append(F("G-GROWS", f"{gid}: due at {first}'s start, its first consumer", sec="§9"))
    return bad


def g_log(t: Texts) -> list[Finding]:
    bad = []
    rows = log_rows(t.spec)
    v = compute(t)
    ids: list[str] = []
    for r in rows:
        got = expand_ids(r[0])
        ids += got
        if len(r) != 6:
            bad.append(F("G-LOG", f"{r[0]}: cell count", sec="§12"))
            continue
        if r[3] in ("", "—"):
            bad.append(F("G-LOG", f"{r[0]}: no owner lane", sec="§12"))
        if r[2] in ("", "—") or not (cites_in(r[2]) or "§" in r[2]) or NO_DEFAULT.search(r[2]):
            bad.append(F("G-LOG", f"{r[0]}: no cited, drawn default", sec="§12"))
        cons = [c.strip() for c in r[4].split(",")]
        ok = all(re.fullmatch(r"E29-[A-Z]\d\d", c) for c in cons)
        sp = sprints()
        first = min(cons, key=lambda c: sp.get(c, 99)) if ok else ""
        a = ANCHOR.search(r[5]) or PLACEHOLDER.search(r[5])
        if (
            not ok
            or first != cons[0]
            or not a
            or a[1] != f"DATE:{first}"
            or (ANCHOR.search(r[5]) and not r[5].startswith(v.get(a[1], "?")))
        ):
            bad.append(F("G-LOG", f"{r[0]}: due is not {r[4]}'s first sprint start", sec="§12"))
        for gid in got:
            if gid in LOG_BINDS and LOG_BINDS[gid] not in cons:
                bad.append(F("G-LOG", f"{gid} binds {LOG_BINDS[gid]}, due at its start", sec="§12"))
    missing = [i for i in LOG_UNION if i not in ids]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    extra = [i for i in ids if i not in LOG_UNION]
    if missing or dup or extra:
        bad.append(
            F(
                "G-LOG",
                f"union: missing {missing[:4]}, repeated {dup[:4]}, unknown {extra[:4]}",
                sec="§12",
            )
        )
    for core in LOG_CORE:
        if not any(core in expand_ids(r[0]) and len(expand_ids(r[0])) <= 5 for r in rows):
            bad.append(
                F("G-LOG", f"{core}: a core-path question is named in its own row", sec="§12")
            )
    cp = re.search(r"\*\*Core path\*\* \(BQ-27\):([^\n]*)", h2(t.spec, "§12"))
    for core in LOG_CORE:
        if not cp or not re.search(rf"\b{core.split()[1]}\b", cp[1].split(", each in")[0]):
            bad.append(F("G-LOG", f"{core}: not named in the core-path line (BQ-27)", sec="§12"))
    return bad


def g_consumers(t: Texts) -> list[Finding]:
    block = h2(t.spec, "§13")
    bad = [
        F("G-CONSUMERS", f"{i} is not a consumer row", sec="§13")
        for i in CONSUMER_ISSUES
        if i not in block
    ]
    if "one comment each at merge on #55, E29-S01..S08" not in block:
        bad.append(F("G-CONSUMERS", "the links: one comment each at merge (T DoD)", sec="§13"))
    rows = {
        m[0]: r for r in table_rows(block) if (m := re.match(r"E29-S0\d", r[0])) and len(r) == 3
    }
    for story, titles in scenarios().items():
        r = rows.get(story)
        if r is None:
            bad.append(F("G-CONSUMERS", f"{story}: no consumer row", sec="§13"))
            continue
        for title in titles:
            seg = next((x for x in r[2].split("; ") if title in x), "")
            if not re.search(rf"{re.escape(title)}(?:, [^:;]+)?: \S", seg):
                bad.append(F("G-CONSUMERS", f"{story}: scenario {title!r} untraced", sec="§13"))
    for sid, needs in state_needs(t.spec).items():
        for story in needs:
            if story in rows and sid not in s_ids(rows[story][1]):
                bad.append(F("G-CONSUMERS", f"{sid} is {story}'s to build", sec="§13"))
    for fid, stories in F_CONSUMERS.items():
        for story in stories:
            if story in rows and fid not in re.findall(r"F-\d\d", rows[story][1]):
                bad.append(F("G-CONSUMERS", f"{fid} reaches {story}", sec="§13"))
    return bad


@functools.lru_cache(maxsize=1)
def scenarios() -> dict[str, tuple[str, ...]]:
    """Each consuming story's Gherkin scenario titles, from the ticket JSON at the base."""
    data = json.loads(at_base(CITE_FILES["E29.json"]))
    items = data if isinstance(data, list) else data.get("tickets", [])
    keep = ("E29-S01", "E29-S02", "E29-S03", "E29-S04", "E29-S06", "E29-S07", "E29-S08")
    return {
        str(it.get("key")): tuple(re.findall(r"Scenario: ([^\n]+)", str(it.get("body", ""))))
        for it in items
        if it.get("key") in keep
    }


def s_ids(cell: str) -> set[str]:
    out: set[str] = set()
    for a, b in re.findall(r"S-(\d\d)(?:–S-(\d\d))?", cell):
        out |= {f"S-{n:02d}" for n in range(int(a), int(b or a) + 1)}
    return out


def state_needs(spec: str) -> dict[str, set[str]]:
    """The stories that build each §3 row's tab (lens 3, M5)."""
    out: dict[str, set[str]] = {}
    for r in table_rows(h2(spec, "§3")):
        if not re.match(r"S-\d\d$", r[0]) or len(r) != 7:
            continue
        need: set[str] = set()
        if "every tab" in r[2]:
            need |= {"E29-S01", "E29-S02", "E29-S04"}
        for word, story in (
            ("Positions", "E29-S01"),
            ("Working orders", "E29-S02"),
            ("Fills", "E29-S04"),
            ("SCR-078", "E29-S04"),
        ):
            if word in r[2]:
                need.add(story)
        need |= {"S-37": {"E29-S03"}, "S-10": {"E29-S06"}}.get(r[0], set())
        out[r[0]] = need
    return out


# BQ-33 (b), (c) (orchestrator lens 1, Major 1): the dry run's roles, in order (every consumer
# §13 names, E29-S05 included as named-only), then the QA role over every §3 row.
WALK_ROLES = (
    "E29-S01 (#911)", "E29-S02 (#912)", "E29-S03 (#978)", "E29-S04 (#979)", "E29-S05 (#980)",
    "E29-S06 (#981)", "E29-S07 (#1028)", "E29-S08 (#1151)", "E29-T09 (#1029)", "E29-Q01 (#844)",
    "E29-Q02 (#1147)", "E29-Q03 (#977)", "E29-Q05 (#1149)", "E29-D07 (#1146)", "E29-X02 (#982)",
)  # fmt: skip
WALK_DATE = "2026-10-27"
WALK_HEAD = ["Date (UTC)", "Role", "Needs listed", "Found", "Not found", "Disposition"]
WALK_QA = "QA: §3, every S row"
DOD_TICK = re.compile(r"^- \[([ x])\] \*\*DoD \(BQ-33 b, c\):\*\*", re.MULTILINE)
ARROW = re.compile(r"→\s*(\S+)")


def walk_target(t: Texts, tok: str, role: str = "") -> str | None:
    """None when a `→` target resolves (a spec §, a §3 S row or a §9 G id, a G-W row naming
    the role among its consumers); else the reason."""
    tok = tok.strip("`*,;.()")
    if tok.startswith("G-W") and role.startswith("E29-"):
        row = next((r for r in g_rows(t.spec) if r[0] == tok), [])
        if row and role not in row[3]:
            return f"{tok} does not name {role} among its consumers"
    if m := re.fullmatch(r"§(\d+)", tok):
        return None if h2(t.spec, f"§{m[1]}") else f"no section {tok}"
    if re.fullmatch(r"S-\d\d", tok):
        rows = {r[0] for r in table_rows(h2(t.spec, "§3"))}
        return None if tok in rows else f"no state row {tok}"
    if re.fullmatch(r"G-[A-Z0-9]+|G\d+", tok):
        ids = {i for r in g_rows(t.spec) for i in expand_ids(r[0])}
        return None if (tok if tok.startswith("G-") else f"D03 {tok}") in ids else f"no {tok}"
    return f"cannot parse the → target {tok[:20]!r}"


def walk_record(t: Texts) -> list[str]:
    """The dry-run record's problems: the table, its counts, its dispositions (BQ-33 b, c)."""
    block = h2(t.spec, "§14")
    if not any(ln.startswith("|") and split_row(ln) == WALK_HEAD for ln in block.split("\n")):
        return ["the dry-run table's header"]
    rows = table_of(block, "Date (UTC)")
    bad: list[str] = []
    want = [f"story: {r}" for r in WALK_ROLES] + [WALK_QA]
    if [r[1] if len(r) > 1 else "" for r in rows] != want:
        bad.append("one row per consumer of §13, in order, then the QA row")
    for r in rows:
        if len(r) != 6:
            continue
        who = r[1][:24]
        if r[0] != WALK_DATE:
            bad.append(f"{who}: date {r[0]!r}")
        if not all(re.fullmatch(r"\d+", c) for c in r[2:5]):
            bad.append(f"{who}: the counts are not numbers")
            continue
        need, found, miss = int(r[2]), int(r[3]), int(r[4])
        if need != found + miss:
            bad.append(f"{who}: {need} needs != {found} found + {miss} not found")
        arrows = ARROW.findall(r[5])
        if (miss == 0) != (r[5] == "—") or len(arrows) != miss:
            bad.append(f"{who}: {miss} not found, {len(arrows)} dispositions")
        for tok in arrows:
            why = walk_target(t, tok, r[1].removeprefix("story: ").split(" ")[0])
            if why:
                bad.append(f"{who}: {why}")
        top = max((int(k[2:]) for k in state_needs(t.spec)), default=0)
        if r[1] == WALK_QA and need != top:  # the highest S id: a deleted row is G-STATES'
            bad.append("the QA row does not cover every §3 row")
    return bad


def g_walk(t: Texts) -> list[Finding]:
    block = h2(t.spec, "§14")
    ws = [int(x) for x in re.findall(r"\bW-(\d+)\b", block)]
    bad = []
    if ws != list(range(1, len(ws) + 1)) or not 1 <= len(ws) <= 10:
        bad.append(
            F("G-WALK", f"the owner walkthrough is W-1..W-n, at most ten ({len(ws)})", sec="§14")
        )
    record = walk_record(t)
    for msg in record:
        bad.append(F("G-WALK", f"dry run: {msg}", sec="§14"))
    ticks = DOD_TICK.findall(block)
    ac3 = next((ln for ln in t.spec.split("\n") if ln.startswith("| AC3 ")), "")
    done = not record
    if ticks != ["x" if done else " "] or ("dry run done" in ac3) != done:
        bad.append(F("G-WALK", "the DoD line's tick and AC3's status follow the record", sec="§14"))
    return bad


SESSION_CLAIM = (
    r"\b(?:session|walkthrough|meeting)s?\b(?:\s+\S+){0,2}?\s+(?:was |were |has been |is )?"
    r"(?:held|ran|run|recorded|conducted|completed|happened|took place)\b|\btook place\b"
    r"|\bparticipants?\b|\battendees?\b|\bwalked through\b|\b(?:was|were) held\b"
    r"|\bengineers? (?:met|attended|joined|acknowledged|walked)\b"
)


def g_session(t: Texts) -> list[Finding]:
    bad = []
    for key, block in sections(t.spec):
        for c in clauses(block):
            if live(c, SESSION_CLAIM):
                bad.append(F("G-SESSION", f"a session is claimed: {c[:60]!r}", sec=key))
    return bad


# The ruled sentences, required verbatim in their sections, and the opposite readings refused in
# any clause (a negation covers its own term).
REQUIRED = (
    ("RULED", "Every default is taken."),
    ("RULED", "the 15:29Z correction (comment 6446126816)"),
    ("RULED", "**PROPOSED, owner approval pending (#2701)**"),
    ("§0", "**One spec plus the deck; no `-handoff.md`:**"),
    ("§0", "**No redraw and no new Penpot page**"),
    ("§4", "**No `15` edit, in this PR or a separate one** (BQ-10)"),
    ("§4", "never as one catalogue PR"),
    ("§4", "never extends a component locally"),
    ("§6", "**No string is invented** (BQ-17)"),
    ("§6", "the LIVE account-flatten typed word is PROPOSED from `15`:477's rule"),
    (
        "§7",
        "the stories build to RT-01..RT-20 as they stand, PROPOSED, owner approval pending (#2701)",
    ),
    ("§7", "moves RT-04..RT-17 by a versioned delta"),
    ("§8", "Each closes under the owner's `approved`, recorded pending (#2701)"),
    ("§9", "no shape is proposed for a missing operation"),
    ("§12", "none without an owner lane, a drawn default the build follows and a due date"),
    ("§12", "goes to #2701 as one list"),
    ("§14", "**No session took place and none is claimed**"),
    ("§15", "**Version (BQ-34; PROPOSED, owner approval pending (#2701)):**"),
    ("§15", "which `--check` FAILs at `origin/main`"),
    ("§15", "both checked by hand at each delta because the tool cannot read them"),
    ("§15", "BQ-3's one line per entry with no later edit stands until the owner answers (C-p)"),
    ("§6", "a `rule` that renders the account label, never a string"),
)
REFUSED = (
    (
        "*",
        (
            r"\b(?:rt|routing table)\S*(?:\s+\S+){0,8}?\s+(?:ruled|approved|adopted|confirmed"
            r"|binding|accepted|final|agreed|signed)\b"
        ),
    ),
    ("*", r"\bextends? (?:\S+ ){0,3}?locally\b|\blocally,? (?:\S+ ){0,4}?extends?\b"),
    ("*", r"\blocal(?:ly)? extension\b"),
    (
        "*",
        (
            r"\b15 edit\b|\bedits? 15\b|\bseparate 15 pr\b|\bfollow ?up (?:15 |catalogue )?pr\b"
            r"|\b15 (?:is |gets |will be )?(?:amended|edited|changed|updated|rewritten)\b"
        ),
    ),
    ("*", r"\b(?:one|a|single) catalogue pr\b|\bcatalogue pr (?:to 15 )?(?:follows|lands)\b"),
    (
        "*",
        (
            r"\bf 10\b(?:\s+\S+){0,6}?\s+(?:is |was |gets )?(?:rewritten|reworded|rephrased|revised"
            r"|edited)\b"
        ),
    ),
    (
        "*",
        (
            r"\bpropos\w* (?:a |the |an )?(?:new )?(?:topic |wire |payload )?(?:shape|topic|schema"
            r"|payload|wire form)s?\b|\b(?:topic|payload|schema|shape|wire form)s? (?:\S+ ){0,2}?"
            r"(?:is |are |was |were )?(?:drafted|proposed|sketched|defined|added)\b"
        ),
    ),
    (
        "*",
        (
            r"\bstrings? (?:is |are |was |were )?invented"
            r"|\binvents? (?:a |the |one )?(?:new )?string"
            r"|\bcoin(?:s|ed)?\b|\bnew strings?\b|\bauthored here\b"
            r"|\bstrings? (?:\S+ ){0,2}?(?:authored|written|drafted|coined)\b"
        ),
    ),
    (
        "*",
        (
            r"(?<!d04 )\bhandoff\.md\b"
            r"|\b(?:second|separate|another|extra|new) hand ?off (?:file|doc\w*|pack|spec)"
        ),
    ),
    (
        "*",
        (
            r"\bowner (?:has |have )?approved\b|\bapproved by the owner\b|\bsigned off\b"
            r"|\bowner (?:has |have )?(?:given|granted|gave)\b"
            r"|\b(?:given|granted|gave|carries|carry|has|got|received?) (?:the |its |their )?"
            r"owner'?s? approv\w*|\bowner'?s? approv\w* (?:is|was|has been) (?:on|given|recorded"
            r"|received|in|granted|there)\b|\bowner'?s? approval (?:granted|given|received|obtained)\b"
            r"|\bsign ?off (?:is |was |has been )?(?:recorded|given"
            r"|received|obtained|done|in)\b"
        ),
    ),
    (
        "*",
        (
            r"\b(?:new|fresh) penpot (?:page|board|frame)s?\b|\bre ?draw(?:n|s|ing)?\b"
            r"|\bpenpot (?:page|board|frame)s? (?:is |are |was |were )?(?:added|drawn|created)\b"
        ),
    ),
    (
        "*",
        (
            r"\b(?:remain|remains|stay|stays|left|lack|lacks|lacking)\b(?:\s+\S+){0,3}?\s+"
            r"(?:without (?:an? )?(?:owner|default|due)|an owner|a default|a due)"
        ),
    ),
    ("*", r"\b(?:only|just) warns?\b|\bwarns? (?:only|instead)\b"),
    (
        "*",
        (
            r"\bcheck\S*\s+(?:fails?|catches|detects|flags|sees|reads)\b(?:\s+\S+){0,10}?"
            r"\s+(?:ruling|paste)"
        ),
    ),
)


def g_ruled(t: Texts) -> list[Finding]:
    bad = []
    for key, sent in REQUIRED:
        block = h2(t.spec, key)
        if sent not in block:
            bad.append(F("G-RULED", f"{key}: the ruled sentence {sent[:55]!r} is missing", sec=key))
    for key, rx in REFUSED:
        for sk, block in sections(t.spec):
            if key not in ("*", sk):
                continue
            for c in clauses(block):
                if live(c, rx):
                    bad.append(F("G-RULED", f"{sk}: a paraphrase asserts {rx[:30]!r}: {c[:50]!r}",
                                 sec=sk))  # fmt: skip
    return bad


def g_version(t: Texts) -> list[Finding]:
    bad = []
    line = h2(t.spec, "§15")
    for rel, sha in PINNED.items():
        if sha not in line:
            bad.append(F("G-VERSION", f"the version line misses {rel}'s {sha}", sec="§15"))
        base_c = last_commit(BASE, rel)
        if not base_c.startswith(sha):
            bad.append(
                F(
                    "G-VERSION",
                    f"{rel}: last commit at {BASE} is {base_c[:10]}, pinned {sha}",
                    sec="§15",
                )
            )
    if not t.head_ok:
        bad.append(F("G-VERSION", f"{HEAD} does not resolve: the drift is unread", sec="§15"))
    for rel in [*PINNED, IMG_DIR]:
        head_c = t.head_commits.get(rel, "")
        if t.head_ok and not head_c:
            bad.append(F("G-VERSION", f"{rel}: no last commit at {HEAD}", sec="§15"))
        if head_c and head_c != last_commit(BASE, rel):
            bad.append(
                F("G-VERSION", f"{rel} drifted at {HEAD} ({head_c[:10]}): a late change", sec="§15")
            )
    if f"v1 at base `{BASE}`" not in line:
        bad.append(F("G-VERSION", f"the version line names v1 at base {BASE}", sec="§15"))
    return bad


def expected_14(base14: str) -> str:
    lines = base14.split("\n")
    out = []
    for ln in lines:
        out.append(ln)
        if any(ln.startswith(p) for p in POINTER_AFTER):
            out.append(POINTER)
    return "\n".join(out)


def g_untouched(t: Texts) -> list[Finding]:
    bad = []
    mb = t.mb
    if not mb:
        return [F("G-UNTOUCHED", f"no merge-base with {HEAD}: nothing is compared", None, None)]
    for rel in UNTOUCHED:
        was = git_show(mb, rel)
        if was is not None and t.disk.get(rel) != was:
            bad.append(F("G-UNTOUCHED", f"{rel} differs from the merge-base", None, None))
    base14 = git_show(mb, PLAN14) or ""
    if t.disk.get(PLAN14) != expected_14(base14):
        diff = [
            d
            for d in difflib.unified_diff(
                base14.split("\n"), t.disk.get(PLAN14, "").split("\n"), lineterm="", n=0
            )
            if d[:1] in "+-" and not d.startswith(("+++", "---"))
        ]
        bad.append(
            F("G-UNTOUCHED", f"`14` differs from the three pointer lines: {diff[:2]}", None, None)
        )
    if t.stray:
        bad.append(F("G-UNTOUCHED", f"changed outside the pack: {list(t.stray)[:3]}", None, None))
    return bad


def g_nohandoff(t: Texts) -> list[Finding]:
    return [F("G-NOHANDOFF", f"a hand-off file exists: {p}", None, None) for p in t.handoffs]


def g_unbuilt(t: Texts) -> list[Finding]:
    feats = sorted(
        n[len(FEATURES_DIR) :]
        for n in tree_at(BASE, FEATURES_DIR)
        if "." not in n[len(FEATURES_DIR) :]
    )
    listed = ", ".join(f"`{f}`" for f in feats[:-1]) + f" and `{feats[-1]}`" if feats else ""
    want = f"holds {listed} and no blotter slice"
    bad = []
    if want not in h2(t.spec, "§0"):
        bad.append(F("G-UNBUILT", f"§0 must read {want[:60]!r}…", sec="§0"))
    ui = git_out("grep", "-l", "CMP-049", BASE, "--", "packages/ui/src")
    if ui.strip() or "and `packages/ui/src` holds no CMP-049" not in h2(t.spec, "§0"):
        bad.append(F("G-UNBUILT", "packages/ui/src holds no CMP-049, said so", sec="§0"))
    return bad


def g_unmerged(t: Texts) -> list[Finding]:
    rx = re.compile(r"#4755\b|E36-D05|/wt/|E29-D07\.md|E05-D03\.md|E29-D06-handoff")
    return [
        F(
            "G-UNMERGED",
            f"line {i}: an unmerged text is cited or quoted",
            "spec",
            sec_of_line(t.spec, i),
        )
        for i, ln in enumerate(t.spec.split("\n"), 1)
        if rx.search(ln)
    ]


CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*#\d+", re.IGNORECASE)


def per_line(gate: str, rx: re.Pattern[str], what: str, t: Texts) -> list[Finding]:
    bad = [
        F(gate, f"line {i}: {what}", "spec", sec_of_line(t.spec, i))
        for i, ln in enumerate(t.spec.split("\n"), 1)
        if rx.search(ln)
    ]
    if rx.search(t.deck):
        bad.append(F(gate, f"the deck: {what}", "deck", "strings"))
    return bad


def g_close(t: Texts) -> list[Finding]:
    bad = per_line("G-CLOSE", CLOSING, "a closing keyword before an issue number", t)
    if CLOSING.search(POINTER):
        bad.append(F("G-CLOSE", "the `14` pointer line: a closing keyword", None, None))
    return bad


URLISH = re.compile(
    r"https?://|\bwww\.|/home/|\\\\|file://|/Users/\w|\.local\b|localhost", re.IGNORECASE
)


def g_url(t: Texts) -> list[Finding]:
    return per_line("G-URL", URLISH, "a URL, local path, host or user name", t)


def g_charset(t: Texts) -> list[Finding]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        sec = sec_of_line(t.spec, i)
        if "\r" in ln or ln != ln.rstrip():
            bad.append(F("G-CHARSET", f"line {i}: CR or trailing whitespace", "spec", sec))
        quoted = [(m.start(), m.end()) for m in QUOTED.finditer(ln)]
        seen: set[str] = set()
        for idx, ch in enumerate(ln):
            inq = any(a < idx < b for a, b in quoted)
            if ch in CHARSET_ALLOW:
                if not inq and "…" not in seen:
                    bad.append(F("G-CHARSET", f"line {i}: '…' outside quoted copy", "spec", sec))
                seen.add("…")
            elif ch not in seen and (
                unicodedata.normalize("NFKC", ch) != ch or unicodedata.category(ch) == "Cf"
            ):
                seen.add(ch)
                bad.append(
                    F("G-CHARSET", f"line {i}: U+{ord(ch):04X} changes under NFKC", "spec", sec)
                )
    if "\r" in t.deck or any(x != x.rstrip() for x in t.deck.split("\n")):
        bad.append(F("G-CHARSET", "the deck: CR or trailing whitespace", "deck", "strings"))
    return bad


def g_cells(t: Texts) -> list[Finding]:
    bad = []
    lines = t.spec.split("\n")
    width = 0
    for i, ln in enumerate(lines, 1):
        if not ln.startswith("|"):
            if width and ln.strip():
                where = sec_of_line(t.spec, i)
                bad.append(F("G-CELLS", f"line {i}: a table swallows a paragraph", "spec", where))
            width = 0
            continue
        n = len(split_row(ln, keep_escapes=True))
        if width == 0:
            width = n
        elif n != width:
            bad.append(
                F(
                    "G-CELLS",
                    f"line {i}: {n} cells, its header has {width}",
                    "spec",
                    sec_of_line(t.spec, i),
                )
            )
    return bad


def g_budget(t: Texts) -> list[Finding]:
    n = len(t.spec.rstrip("\n").split("\n"))
    last = sections(t.spec)[-1][0]
    return (
        [F("G-BUDGET", f"the spec has {n} lines, the budget {LINE_BUDGET}", "spec", last)]
        if n > LINE_BUDGET
        else []
    )


GL = re.compile(
    r"(?i)[\w.-]{0,50}?(?:access|auth|(?-i:[Aa]pi|API)|credential|creds|key|passw(?:or)?d"
    r"|secret|token)"
    r"(?:[ \t\w.-]{0,20})[\s'\"]{0,3}(?:=|>|:{1,3}=|\|\||:|=>|\?=|,)[\x60'\"\s=]{0,5}"
    r"([\w.=-]{10,150}|[a-z0-9][a-z0-9+/]{11,}={0,3})(?:[\x60'\"\s;]|\\[nr]|$)"
)


def entropy(s: str) -> float:
    c = Counter(s)
    return -sum(v / len(s) * math.log2(v / len(s)) for v in c.values())


def g_gitleaks(t: Texts) -> list[Finding]:
    bad = []
    for d, x in (("spec", t.spec), ("deck", t.deck), ("14", POINTER)):
        for ln in x.split("\n"):
            for m in GL.finditer(ln):
                v = m[1]
                if re.fullmatch(r"[a-zA-Z_.-]+", v) or entropy(v) < 3.5:
                    continue
                sec = (
                    "strings"
                    if d == "deck"
                    else (
                        sec_of_line(t.spec, t.spec[: t.spec.find(ln)].count("\n") + 1)
                        if d == "spec"
                        else None
                    )
                )
                bad.append(
                    F(
                        "G-GITLEAKS",
                        f"{d}: {v[:30]!r} reads as a secret (entropy {entropy(v):.2f})",
                        d if d != "14" else None,
                        sec,
                    )
                )
    return bad


TOKEN = re.compile(r"`((?:color|size|space|motion|font|border|radius|opacity)\.[a-z0-9.-]+)`")


@functools.lru_cache(maxsize=1)
def token_names() -> frozenset[str]:
    names: set[str] = set()

    def walk(d: object, path: str) -> None:
        if isinstance(d, dict):
            if "$value" in d:
                names.add(path)
                return
            for k, v in d.items():
                walk(v, f"{path}.{k}" if path else str(k))

    for f in ("primitives", "semantic-dark", "semantic-light", "semantic-hc"):
        walk(json.loads(at_base(f"packages/ui/tokens/{f}.tokens.json")), "")
    return frozenset(names)


def g_token(t: Texts) -> list[Finding]:
    """Every token the spec names resolves in `packages/ui/tokens` at the base (none invented)."""
    return [
        F("G-TOKEN", f"line {i}: {m[1]} is not a token at {BASE}", "spec", sec_of_line(t.spec, i))
        for i, ln in enumerate(t.spec.split("\n"), 1)
        for m in TOKEN.finditer(ln)
        if m[1] not in token_names()
    ]


def g_mutlist(t: Texts) -> list[Finding]:
    block = h2(t.spec, "§17")
    listed = re.findall(r"(?:\*\* |; )(M-\d{2,3}) ", block)
    gates: dict[str, str] = {}
    for g, text in re.findall(r"\*\*(G-[A-Z-]+):\*\*((?:(?!\*\*G-)[^\n])*)", block):
        gates[g] = gates.get(g, "") + text
    want = [m.mid for m in MUTATIONS if m.mid.startswith("M-")]
    bad = []
    if sorted(listed) != sorted(want) or len(set(listed)) != len(listed):
        bad.append(
            F("G-MUTLIST", f"§17 lists {len(listed)} mutations, the tool {len(want)}", sec="§17")
        )
    for m in MUTATIONS:
        if m.mid.startswith("M-") and not re.search(rf"{m.mid}\b", gates.get(m.gate, "")):
            bad.append(F("G-MUTLIST", f"{m.mid} is not listed under {m.gate}", sec="§17"))
    return bad


# ---------------------------------------------------------------------------- pins

PIN_SENT = re.compile(r"s\d+")
Unit = tuple[str, str, str, str]  # (doc, region, loc, text)
FULL_STOP = re.compile(r"(?<=[.!?])\s+")


def line_form(raw: str) -> str:
    lead = len(raw) - len(raw.lstrip(" "))
    ind = f">{lead}" if lead else ""
    if re.match(r"^\s*[-*+] ", raw):
        return ind + "b"
    if re.match(r"^\s*\d+\. ", raw):
        return ind + "n"
    return ind + "p"


def spec_units(text: str, values: Values) -> list[Unit]:
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    count: dict[str, int] = {}
    region, k, shape = "(top)#1", 0, ""
    seen: dict[str, int] = {}
    for raw in text.split("\n"):
        ln = unvalued(raw, values)
        m = HEADING.match(ln)
        if m:
            out.append(("spec", region, "shape", shape))
            level = len(m[1])
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m[2]))]
            key = " \u203a ".join(p[1] for p in path)
            count[key] = count.get(key, 0) + 1
            region, k, seen, shape = f"{key}#{count[key]}", 0, {}, "h"
            out.append(("spec", region, "heading", pin_norm(ln)))
            continue
        if not ln.strip():
            shape += "."
        elif is_rule(ln):
            shape += "r"
            out.append(
                ("spec", region, f"rule {shape.count('r')}", pin_norm(re.sub(r"-+", "-", ln)))
            )
        elif ln.startswith("|"):
            shape += "t"
            rid = re.sub(r"[*_`]", "", split_row(ln)[0]).strip() or "(blank)"
            seen[rid] = seen.get(rid, 0) + 1
            loc = f"row {rid}" + (f"#{seen[rid]}" if seen[rid] > 1 else "")
            out.append(
                (
                    "spec",
                    region,
                    loc,
                    " | ".join(pin_norm(c) for c in split_row(ln, keep_escapes=True)),
                )
            )
        else:
            sents = [x for x in FULL_STOP.split(ln.strip()) if x.strip()]
            shape += f"{line_form(raw)}{len(sents)}"
            for s in sents:
                k += 1
                out.append(("spec", region, f"s{k}", pin_norm(s)))
    out.append(("spec", region, "shape", shape))
    return out


def deck_units(t: Texts) -> list[Unit]:
    entries = deck_entries(t)
    data, _dups = parse_deck(t.deck)
    top = (
        {k: v for k, v in data.items() if k != "strings"} | {"(fields)": list(data)}
        if isinstance(data, dict)
        else {}
    )
    out: list[Unit] = [
        ("deck", "strings#1", "top", json.dumps(top, ensure_ascii=False, sort_keys=True)),
        ("deck", "strings#1", "shape", ",".join(entry_id(e) for e in entries)),
    ]
    for e in entries:
        out.append(
            (
                "deck",
                "strings#1",
                f"entry {entry_id(e)}",
                json.dumps(
                    {k: v for k, v in e.items() if k not in ("key", "variant")},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )
    return out


def all_units(t: Texts) -> list[Unit]:
    return spec_units(t.spec, compute(t)) + deck_units(t)


def write_pins(units: list[Unit]) -> str:
    head = (
        "# E29-D06 pins (every unit of the spec and every deck entry): doc, region (heading path "
        f"#occurrence), location, exact normalised text; {len(units)} units.\n# Written by "
        "`--repin-ruled` only; `--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
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
    path = ROOT / PIN_REL
    return parse_pins(path.read_text(encoding="utf-8")) if path.exists() else None


def region_sec(doc: str, region: str) -> str | None:
    if doc == "deck":
        return "strings"
    parts = region.rsplit("#", 1)[0].split(" \u203a ")
    return sec_key(parts[1]) if len(parts) > 1 else "(top)"


def pin_problems(pinned: tuple[Unit, ...], current: list[Unit]) -> list[tuple[str, str, str]]:
    bad: list[tuple[str, str, str]] = []
    old_r = list(dict.fromkeys((u[0], u[1]) for u in pinned))
    new_r = list(dict.fromkeys((u[0], u[1]) for u in current))
    for d, r in old_r:
        if (d, r) not in new_r:
            bad.append((f"{d} region {r[-50:]!r} deleted or renamed", d, r))
    for d, r in new_r:
        if (d, r) not in old_r:
            bad.append((f"{d} region {r[-50:]!r} is unpinned (new)", d, r))
    common = [x for x in new_r if x in old_r]
    if common != [x for x in old_r if x in new_r]:
        bad.append(("a pinned region moved", common[0][0], common[0][1]))
    for d, r in common:
        was = [u for u in pinned if (u[0], u[1]) == (d, r)]
        now = [u for u in current if (u[0], u[1]) == (d, r)]
        wm = {u[2]: u[3] for u in was if not PIN_SENT.fullmatch(u[2])}
        nm: dict[str, str] = {}
        for u in now:
            if PIN_SENT.fullmatch(u[2]):
                continue
            if u[2] in nm:
                bad.append((f"{d} {r[-40:]!r} {u[2]} repeated", d, r))
            nm[u[2]] = u[3]
        for loc in sorted(set(wm) | set(nm)):
            if wm.get(loc) != nm.get(loc):
                what = (
                    "deleted" if loc not in nm else "unpinned (new)" if loc not in wm else "changed"
                )
                bad.append((f"{d} {r[-40:]!r} {loc} {what}", d, r))
        if [x for x in wm if x in nm] != [x for x in nm if x in wm]:
            bad.append((f"{d} {r[-40:]!r} rows moved", d, r))
        ws = [u[3] for u in was if PIN_SENT.fullmatch(u[2])]
        ns = [u[3] for u in now if PIN_SENT.fullmatch(u[2])]
        if ws != ns:
            first = next(
                (a for a, b in zip(ns, ws, strict=False) if a != b),
                (ns or ws)[-1:][0] if (ns or ws) else "",
            )
            bad.append(
                (
                    f"{d} {r[-40:]!r} a sentence changed, moved, added or deleted: {first[:50]!r}",
                    d,
                    r,
                )
            )
    return bad


def pin_findings(t: Texts) -> list[Finding]:
    pins = read_pins()
    if pins is None:
        return [F("G-RULED-PIN", f"no {PIN_REL}; run --repin-ruled deliberately", None, None)]
    return [
        F("G-RULED-PIN", m, d, region_sec(d, r)) for m, d, r in pin_problems(pins, all_units(t))
    ]


# ---------------------------------------------------------------------------- the audit

GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_anchor, g_marker, g_figure, g_cite, g_quote, deck_findings, g_states, g_frames, g_cmp,
    g_cr, g_frow, g_lift, g_grows, g_log, g_consumers, g_walk, g_session, g_ruled, g_version,
    g_untouched, g_nohandoff, g_unbuilt, g_unmerged, g_close, g_url, g_charset, g_cells,
    g_budget, g_gitleaks, g_token, g_mutlist,
)  # fmt: skip


def audit(t: Texts) -> tuple[list[str], list[str], list[str], int]:
    """(FAIL lines, NOTE lines, WARN lines, cites checked); one FAIL line per gate."""
    found: list[Finding] = []
    for gate in GATES:
        found += gate(t)
    flagged = {(f[2], f[3]) for f in found if f[2] is not None}
    flagged_secs = {f[3] for f in found if f[3] is not None}
    pins = pin_findings(t)
    notes = [
        f"NOTE [G-RULED-PIN] {p[1][:150]}"
        for p in pins
        if (p[2], p[3]) in flagged or p[3] in flagged_secs
    ]
    found += [p for p in pins if not ((p[2], p[3]) in flagged or p[3] in flagged_secs)]
    merged: dict[str, list[str]] = {}
    for tag, msg, _d, _s in found:
        merged.setdefault(tag, []).append(msg)
    fails = []
    for tag, msgs in merged.items():
        msgs = list(dict.fromkeys(msgs))
        more = f" (+{len(msgs) - 3} more)" if len(msgs) > 3 else ""
        fails.append(f"[{tag}] " + "; ".join(m[:140] for m in msgs[:3]) + more)
    n = len(cites_in(t.spec)) + len(deck_entries(t))
    return fails, notes, [], n


# ---------------------------------------------------------------------------- mutations

Edit = Callable[[Texts], Texts]


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str
    what: str
    edit: Edit


def sub(old: str, new: str, count: int = 1) -> Edit:
    def run(t: Texts) -> Texts:
        if old not in t.spec:
            raise SystemExit(f"self-test: the needle {old[:50]!a} is gone from the spec")
        return replace(t, spec=t.spec.replace(old, new, count))

    return run


def deck_edit(fn: Callable[[dict[str, dict[str, object]]], None]) -> Edit:
    def run(t: Texts) -> Texts:
        data = json.loads(t.deck)
        fn(data["strings"])
        return replace(t, deck=json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    return run


def set_string(key: str, s: str) -> Callable[[dict[str, dict[str, object]]], None]:
    def run(es: dict[str, dict[str, object]]) -> None:
        es[key]["string"] = s

    return run


def disk_edit(rel: str, fn: Callable[[str], str]) -> Edit:
    def run(t: Texts) -> Texts:
        d = dict(t.disk)
        d[rel] = fn(d[rel])
        return replace(t, disk=d)

    return run


def row_line(prefix: str) -> Callable[[str], str]:
    """The whole spec line starting with `prefix` (for row deletions)."""

    def get(spec: str) -> str:
        for ln in spec.split("\n"):
            if ln.startswith(prefix):
                return ln + "\n"
        raise SystemExit(f"self-test: no line starts with {prefix!a}")

    return get


def drop_line(prefix: str) -> Edit:
    def run(t: Texts) -> Texts:
        return replace(t, spec=t.spec.replace(row_line(prefix)(t.spec), "", 1))

    return run


def cell(prefix: str, idx: int, new: str) -> Edit:
    def run(t: Texts) -> Texts:
        old = row_line(prefix)(t.spec).rstrip("\n")
        cells = split_row(old, keep_escapes=True)
        cells[idx] = new
        return replace(t, spec=t.spec.replace(old, "| " + " | ".join(cells) + " |", 1))

    return run


def merge_cells(prefix: str) -> Edit:
    def run(t: Texts) -> Texts:
        old = row_line(prefix)(t.spec).rstrip("\n")
        i = old.index("|", 1)
        return replace(t, spec=t.spec.replace(old, old[:i] + " " + old[i + 1 :], 1))

    return run


def deck_top(fn: Callable[[dict[str, object]], None]) -> Edit:
    def run(t: Texts) -> Texts:
        data = json.loads(t.deck)
        fn(data)
        return replace(t, deck=json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    return run


def deck_raw(old: str, new: str) -> Edit:
    def run(t: Texts) -> Texts:
        if old not in t.deck:
            raise SystemExit(f"self-test: the needle {old[:50]!a} is gone from the deck")
        return replace(t, deck=t.deck.replace(old, new, 1))

    return run


def subs_cells(*edits: tuple[str, int, str]) -> Edit:
    def run(t: Texts) -> Texts:
        for prefix, idx, new in edits:
            t = cell(prefix, idx, new)(t)
        return t

    return run


def drop_param(es: dict[str, dict[str, object]]) -> None:
    params = es["blotter.ui.loading"]["params"]
    if isinstance(params, dict):
        params.pop("Sub-1")


def bare_member(d: dict[str, object]) -> None:
    members = d["strings"]
    if isinstance(members, dict):
        members["blotter.ui.note"] = "Owner approved."


def unmark_safety(es: dict[str, dict[str, object]]) -> None:
    del es["acct.reassure.true"]["safety"]


def say(needle: str, extra: str) -> Edit:
    """Insert `extra` right after `needle` in the spec."""
    return sub(needle, needle + extra)


def p02_due(t: Texts) -> Texts:
    value = (t.values or {})["DATE:E29-S04"]
    return cell("| P-02 ", 5, f"{value}<!--=DATE:E29-S04-->")(t)


def no_a11y(x: str) -> str:
    return x.replace(POINTER, POINTER.replace(" (a11y contract: E29-D05)", ""), 1)


def hand_count(t: Texts) -> Texts:
    return replace(t, spec=re.sub(r"\d+(<!--=COUNT:states-->)", r"99\1", t.spec, count=1))


D5 = "nothing animates per tick (D04:346)."
S4 = "never extends a component locally (`02`:54)."
S4B = "no new CMP id (D04:21)."
S6 = "**No string is invented** (BQ-17): "
S7 = "the `announce_prices` composition rides with it (D05:285)."
S9 = "no shape is proposed for a missing operation."
S12 = "nothing is filed here."
S14 = "AC3's record is the dry-run table"
S15 = "a design PR merges on the owner's approval (README:59)."
RUL = "Every default is taken."
S8 = "Each closes under the owner's `approved`, recorded pending (#2701); D02–D05 stay untouched."
PROBE = "Zq8r4LmT" + "1vXc0p9W"  # built at run time, so no scanner reads it here
M = Mutation
MUTATIONS: tuple[Mutation, ...] = (
    M("M-01", "G-RULED", "delete the routing table's PROPOSED clause in §7",
      sub("as they stand, PROPOSED, owner approval pending (#2701);", "as they stand;")),
    M("M-02", "G-RULED", 'write "the routing table is approved as the build contract" in §7',
      sub("Q-01's alternative and Q-07",
          "the routing table is approved as the build contract; Q-01's alternative and Q-07")),
    M("M-03", "G-RULED", 'write "Stories may extend a component locally." in §4',
      say("never extends a component locally (`02`:54).",
          " Stories may extend a component locally.")),
    M("M-04", "G-RULED", 'write "A `15` edit lands in a separate PR." in §4',
      say("no new CMP id (D04:21).", " A `15` edit lands in a separate PR.")),
    M("M-05", "G-RULED", 'delete "No string is invented" from §6',
      sub("**No string is invented** (BQ-17): ", "(BQ-17): ")),
    M("M-06", "G-RULED", 'write "the pack proposes the topic shape" in §9',
      sub("no shape is proposed for a missing operation.",
          "no shape is proposed for a missing operation, and the pack proposes the topic shape.")),
    M("M-07", "G-RULED", "delete the versioning line's PROPOSED clause in §15",
      sub("**Version (BQ-34; PROPOSED, owner approval pending (#2701)):**",
          "**Version (BQ-34):**")),
    M("M-08", "G-RULED", 'write "The owner approved the pack." in §15',
      say("a design PR merges on the owner's approval (README:59).",
          " The owner approved the pack.")),
    M("M-09", "G-RULED", 'write "A hand-off file `-handoff.md` carries the CRs." in §5',
      say(D5, " A hand-off file `-handoff.md` carries the CRs.")),
    M("M-10", "G-RULED", 'write "Board 20 is redrawn in Penpot." in §5',
      say(D5, " Board 20 is redrawn in Penpot.")),
    M("M-11", "G-SESSION", 'write "The session was held with the engineers." in §14',
      sub("AC3's record is the dry-run table",
          "The session was held with the engineers. AC3's record is the dry-run table")),
    M("M-12", "G-CR", 'write "E05-S01 (#264)" as CMP-011\'s slice',
      cell("| CMP-011 Tag `toggle` ", 2, "E05-S01 (#264)")),
    M("M-13", "G-CR", "delete the CMP-099 CR row", drop_line("| CMP-099 PrintExportBar ")),
    M("M-14", "G-CR", 'drop "core path" from CMP-011\'s Meanwhile cell',
      cell("| CMP-011 Tag `toggle` ", 4, "D04's interim (D04:292)")),
    M("M-15", "G-FROW",
      'write "rewritten" for F-10\'s "accepted with its rationale, not rewritten"',
      sub("accepted with its rationale, not rewritten: the slot", "rewritten: the slot")),
    M("M-16", "G-FROW", 'write "carried here" in F-06\'s Landing cell',
      cell("| F-06 ", 3, "carried here; E29-S01")),
    M("M-17", "G-FROW", "delete the F-08 row", drop_line("| F-08 ")),
    M("M-18", "G-FROW", 'write "approved" in F-04\'s Close state cell',
      cell("| F-04 ", 4, "approved")),
    M("M-19", "G-GROWS", "delete the G20 row", drop_line("| G20 ")),
    M("M-20", "G-GROWS", 'write "E29-S02" as G1\'s consumer', cell("| G1 ", 3, "E29-S02")),
    M("M-21", "G-LOG", "empty the D02 OQ-Q row's Owner lane cell",
      cell("| D02 OQ-Q ", 3, "—")),
    M("M-22", "G-LOG", 'drop "D03 OQ-5, " from the log',
      sub("| D03 OQ-5, OQ-12, OQ-16; D05 Q-02", "| D03 OQ-12, OQ-16; D05 Q-02")),
    M("M-23", "G-LOG", "give the P-02 row E29-S04's date under E29-S01", p02_due),
    M("M-24", "G-STATES", "name a key the deck lacks in S-05",
      cell("| S-05 ", 6, "`blotter.ui.last_updated`")),
    M("M-25", "G-STATES", "delete the S-14 row", drop_line("| S-14 ")),
    M("M-26", "G-STATES", "cite board D02 22 in S-04", cell("| S-04 ", 5, "D02 22")),
    M("M-27", "G-DECK", "change one character of `acct.reassure.true`",
      deck_edit(set_string("acct.reassure.true",
                           "Your exchange-side stop-losses are not affected."))),
    M("M-28", "G-DECK", 'write "TBD" as `fills.error`\'s string',
      deck_edit(set_string("fills.error", "TBD"))),
    M("M-29", "G-DECK", "put the exchange's `retCode` into `blotter.ui.amend.rejected`",
      deck_edit(set_string("blotter.ui.amend.rejected",
                           "Amend rejected — your order is unchanged (retCode 110001)"))),
    M("M-30", "G-LIFT", "shrink §12's lifted span by one line",
      cell("| §12 ", 1, "D05:369–387")),
    M("M-31", "G-CMP", "cite CMP-114's heading for CMP-115", sub("`15`:1277", "`15`:1243")),
    M("M-32", "G-WALK", "add an eleventh walkthrough item",
      say("W-10 §16, the C-rows.", " W-11 §17, the mutations.")),
    M("M-33", "G-CONSUMERS", 'delete "#1151" from §13', sub("E29-S08 (#1151)", "E29-S08")),
    M("M-34", "G-VERSION", "simulate a merged change to D03 at origin/main",
      lambda t: replace(t, head_commits={**t.head_commits, CITE_FILES["D03"]: "0" * 40})),
    M("M-35", "G-UNTOUCHED", "append a line to `15` in the working tree",
      disk_edit(PLAN["15"], lambda x: x + "drift\n")),
    M("M-36", "G-UNTOUCHED", 'drop "(a11y contract: E29-D05)" from the SCR-063 pointer line',
      disk_edit(PLAN14, no_a11y)),
    M("M-37", "G-NOHANDOFF", "add a hand-off file beside the spec",
      lambda t: replace(t, handoffs=("docs/design/E29/E29-D06-handoff.md",))),
    M("M-38", "G-UNBUILT", 'delete "and no blotter slice" from §0',
      sub(" and no blotter slice", "")),
    M("M-39", "G-CITE", "move a D02 cite past the end of D02",
      sub("(D02:90–100)", "(D02:90–9999)")),
    M("M-40", "G-QUOTE", "quote copy no merged text holds",
      sub('T2 "Frozen — the owner closes or releases"', 'T2 "Frozen — closes wait for the owner"')),
    M("M-41", "G-ANCHOR", "hand-edit the S count's value", hand_count),
    M("M-42", "G-FIGURE", 'type "41 boards" by hand in §2',
      sub("a state's board is §3's Board column.",
          "a state's board is §3's Board column, of 41 boards.")),
    M("M-43", "G-MARKER", "add a comment that is not an anchor",
      sub("## 5. Redlines", "<!-- note -->\n## 5. Redlines")),
    M("M-44", "G-CLOSE", "write a closing keyword before #825 in §15",
      sub("the owner's `approved` on #825,", "the owner's `approved`; closes #825,")),
    M("M-45", "G-URL", "write a local path in §5",
      sub("(D04:346).", "(D04:346, " + "/ho" + "me/x/wt).")),
    M("M-46", "G-UNMERGED", "cite the unmerged sister pack's PR in §5",
      sub("(D04:346).", "(D04:346; the form of #4755).")),
    M("M-47", "G-CHARSET", "write a trailing space at the end of §0's first paragraph",
      say("as D05 did (D05:38).", " ")),
    M("M-48", "G-CELLS", "merge two cells of C-a", merge_cells("| C-a ")),
    M("M-49", "G-BUDGET", "append lines past the budget",
      lambda t: replace(t, spec=t.spec + "\nPadding.\n" * 40)),
    M("M-50", "G-GITLEAKS", "write a secret-shaped value in §5",
      sub("(D04:346).", "(D04:346; `api_key: " + PROBE + "`).")),
    M("M-51", "G-MUTLIST", "delete M-01 from §17", sub("M-01 ", "M-0X ", 1)),
    M("M-52", "G-DECK", "drop the `safety` mark from `acct.reassure.true`",
      deck_edit(unmark_safety)),
    M("M-53", "G-TOKEN", "name an unshipped token in F-06",
      sub("a high-contrast `color.text.link`", "a high-contrast `color.text.link-hc`")),
    M("M-54", "G-LOG", 'write "cited, decided nowhere here" as OQ-R\'s default',
      cell("| D02 OQ-R", 2, "cited, decided nowhere here (D02:667)")),
    M("M-55", "G-LOG", "drop OQ-R from the core-path line",
      sub("D02 OQ-E, OQ-R and OQ-Q", "D02 OQ-E and OQ-Q")),
    M("M-56", "G-LOG", "move D04H Q-2 to the E29-T09 row",
      subs_cells(("| D04H Q-2–Q-5, ", 0, "D04H Q-3–Q-5, Q-7, Q-8, Q-15–Q-17, Q-20, Q-21"),
                 ("| D04H Q-12–Q-14, ", 0, "D04H Q-2, Q-12–Q-14, Q-18, Q-22"))),
    M("M-57", "G-CMP", "cite D04H:171 as CMP-209's Storybook",
      cell("| CMP-209 RightRail ", 4, "D04H:171")),
    M("M-58", "G-CONSUMERS", "drop S-01 and S-02 from E29-S04's row",
      sub("| S-01, S-02, S-04, S-05, S-07, S-08, S-19,", "| S-04, S-05, S-07, S-08, S-19,")),
    M("M-59", "G-CONSUMERS", "drop the lost-race scenario from E29-S02's trace",
      sub("Cancel that lost the race: P-04; ", "")),
    M("M-60", "G-CONSUMERS", "drop F-03 from E29-S04's row",
      sub("F-02, F-03, F-04;", "F-02, F-04;")),
    M("M-61", "G-FROW", "drop F-03's PROPOSED",
      cell("| F-03 ", 2, "D05 §5.3's set position (D05:181)")),
    M("M-62", "G-FROW", "name no lane in F-11's Landing cell",
      cell("| F-11 ", 3, "recorded to E05; the build binds tokens as shipped")),
    M("M-63", "G-GROWS", "give D04-G3 to E29-S01", cell("| D04-G3 ", 3, "E29-S01")),
    M("M-64", "G-GROWS", "delete the G-O row", drop_line("| G-O ")),
    M("M-65", "G-STATES", "delete the S-36 row", drop_line("| S-36 ")),
    M("M-66", "G-DECK", "drop the account span from `blotter.ui.loading`'s params",
      deck_edit(drop_param)),
    M("M-67", "G-DECK", "add a top-level note field to the deck",
      deck_top(lambda d: d.__setitem__("note", "The owner approved the pack."))),
    M("M-68", "G-DECK", "put a bare string under the deck's strings",
      deck_top(bare_member)),
    M("M-69", "G-DECK", "repeat a deck key ahead of its entry",
      deck_raw('"strings": {', '"strings": {\n    "fills.chrome": {"string": "Time"},')),
    M("M-70", "G-DECK", "write v2 as the deck's version",
      deck_top(lambda d: d.__setitem__("version", "v2"))),
    M("M-71", "G-DECK", "give the typed word's rule a string as well",
      deck_edit(set_string("flatten.typed.account", "the object's own name"))),
    M("M-72", "G-VERSION", "simulate an unresolvable origin/main",
      lambda t: replace(t, head_ok=False)),
    M("M-73", "G-UNTOUCHED", "simulate a failed merge-base", lambda t: replace(t, mb="")),
    M("M-74", "G-UNTOUCHED", "simulate a committed change to `20` outside the pack",
      lambda t: replace(t, stray=stray_of(f"docs/plan/20-architecture.md\n{PLAN14}", ""))),
    M("M-75", "G-CHARSET", "write a fullwidth letter inside C-i's short quote",
      sub('"hide zero"', '"hide \uff5aero"')),
    M("M-76", "G-RULED", "delete BQ-3's standing clause from §15",
      sub(", and BQ-3's one line per entry with no later edit stands until the owner answers (C-p)",
          "")),
    M("M-77", "G-RULED", "write a string for the typed word's rule in §6",
      sub("a `rule` that renders the account label, never a string", "a string")),
    M("M-78", "G-RULED", "delete the hand-checked clause from §15",
      sub("both checked by hand at each delta because the tool cannot read them, ", "")),
    M("M-79", "G-RULED", 'write "The owner has given approval to the pack." in §15',
      say(S15, " The owner has given approval to the pack.")),
    M("M-80", "G-RULED", 'write "Owner sign-off is recorded on #825." in §15',
      say(S15, " Owner sign-off is recorded on #825.")),
    M("M-81", "G-RULED", "put the owner's `approved` on #825 as a fact in §15",
      say(S15, " The owner's `approved` is on #825.")),
    M("M-82", "G-RULED", 'write "RT-01..RT-20 are final." in §7',
      say(S7, " RT-01..RT-20 are final.")),
    M("M-83", "G-RULED", 'write "The routing table is accepted as the build contract." in §7',
      say(S7, " The routing table is accepted as the build contract.")),
    M("M-84", "G-RULED", 'write "No reviewer doubts the routing table is approved." in §7',
      say(S7, " No reviewer doubts the routing table is approved.")),
    M("M-85", "G-RULED", 'write "Stories can locally extend a component." in §4',
      say(S4, " Stories can locally extend a component.")),
    M("M-86", "G-RULED", 'write "A story may extend the CMP locally." in §4',
      say(S4, " A story may extend the CMP locally.")),
    M("M-87", "G-RULED", 'write "`15` is amended in a follow-up PR." in §4',
      say(S4B, " `15` is amended in a follow-up PR.")),
    M("M-88", "G-RULED", 'write "The CRs ship bundled in a single catalogue PR." in §4',
      say(S4, " The CRs ship bundled in a single catalogue PR.")),
    M("M-89", "G-RULED", 'write "The pack coins one new string for the empty state;" in §6',
      say(S6, "The pack coins one new string for the empty state; ")),
    M("M-90", "G-RULED", 'write "two strings were authored here, not lifted;" in §6',
      say(S6, "two strings were authored here, not lifted; ")),
    M("M-91", "G-RULED", 'write "A topic shape is drafted for the missing operation." in §9',
      say(S9, " A topic shape is drafted for the missing operation.")),
    M("M-92", "G-RULED", 'write "The pack proposes a new payload." in §9',
      say(S9, " The pack proposes a new payload.")),
    M("M-93", "G-RULED", 'write "A second hand-off file follows the spec." in §5',
      say(D5, " A second hand-off file follows the spec.")),
    M("M-94", "G-RULED", 'write "Board 20 gets a fresh Penpot frame." in §5',
      say(D5, " Board 20 gets a fresh Penpot frame.")),
    M("M-95", "G-RULED", 'write "Board 20 is re-drawn in Penpot." in §5',
      say(D5, " Board 20 is re-drawn in Penpot.")),
    M("M-96", "G-RULED", 'write "in practice it only WARNs" after the drift clause in §15',
      sub("FAILs at `origin/main`.", "FAILs at `origin/main`; in practice it only WARNs.")),
    M("M-97", "G-RULED", 'write "BQ-24 carries the owner\'s approval." in the RULED paragraph',
      say(RUL, " BQ-24 carries the owner's approval.")),
    M("M-98", "G-RULED", 'write "Two questions remain without an owner lane." in §12',
      say(S12, " Two questions remain without an owner lane.")),
    M("M-99", "G-RULED", 'write "F-10 is reworded to match D05." in §8',
      say(S8, " F-10 is reworded to match D05.")),
    M("M-100", "G-RULED", 'write "Stories may extend a component locally." in §5',
      say(D5, " Stories may extend a component locally.")),
    M("M-101", "G-RULED", 'add a §17 bullet "Note: the owner approved the pack."',
      sub("\n\n- **G-RULED:**", "\n\n- Note: the owner approved the pack.\n- **G-RULED:**")),
    M("M-102", "G-RULED", "wrap the one word of an owner claim in quotes in §15",
      say(S15, ' The owner "approved" it.')),
    M("M-103", "G-RULED", 'write "Locally, a story extends the component." in §4',
      say(S4, " Locally, a story extends the component.")),
    M("M-104", "G-SESSION", 'write "The walkthrough session ran with two engineers." in §14',
      sub(S14, "The walkthrough session ran with two engineers. " + S14)),
    M("M-105", "G-SESSION", 'write "Engineers met and walked through the pack." in §14',
      sub(S14, "Engineers met and walked through the pack. " + S14)),
    M("M-106", "G-SESSION",
      'write "Not a single engineer skipped it: the session was held." in §14',
      sub(S14, "Not a single engineer skipped it: the session was held. " + S14)),
    M("M-107", "G-SESSION", 'write "The walkthrough was held on 2026-10-26." in §14',
      sub(S14, "The walkthrough was held on 2026-10-26. " + S14)),
    M("M-108", "G-CR", 'write "E05-S02 (#265)" as CMP-057\'s slice',
      cell("| CMP-057 SplitButton ", 2, "E05-S02 (#265)")),
    M("M-109", "G-CR", 'write "E05-S01 (#264)" as CMP-019\'s slice',
      cell("| CMP-019 Icon glyphs ", 2, "E05-S01 (#264) via E05-T06 (#271)")),
    M("M-110", "G-CR", "drop the token-level reading and BQ-27 from the P-02 row",
      cell("| P-02 ", 2, "the shipped tokens (D04H:244)")),
    M("M-111", "G-WALK", "drop E29-S03's dry-run row", drop_line("| 2026-10-27 | story: E29-S03 ")),
    M("M-112", "G-WALK", "write — for E29-S06's dispositions",
      cell("| 2026-10-27 | story: E29-S06 ", 5, "—")),
    M("M-113", "G-WALK", "untick the DoD line", sub("- [x] **DoD (BQ-33", "- [ ] **DoD (BQ-33")),
    M("M-114", "G-WALK", "write 13 found for E29-Q03",
      cell("| 2026-10-27 | story: E29-Q03 ", 3, "13")),
    M("M-115", "G-WALK", "point a carry at G-W9",
      sub("`exec_dedupe_hits_total` → G-W2", "`exec_dedupe_hits_total` → G-W9")),
    M("M-116", "G-WALK", "drop the QA row", drop_line("| 2026-10-27 | QA: ")),
    M("M-117", "G-WALK", "write a → target the tool cannot parse",
      sub("the orders-frame scripting budget → G-W2", "the orders-frame scripting budget → later")),
    M("M-118", "G-WALK", "route E29-S04's metric to G-W4, which does not name E29-S04",
      sub("`exec_dedupe_hits_total` → G-W2", "`exec_dedupe_hits_total` → G-W4")),
    M("M-119", "G-WALK", "date E29-S01's dry-run row 2026-10-26",
      cell("| 2026-10-27 | story: E29-S01 ", 0, "2026-10-26")),
    M("M-120", "G-RULED", "delete the 15:29Z correction's cite from the RULED paragraph",
      sub(" BQ-11's slices follow the 15:29Z correction (comment 6446126816);", "")),
    M("M-121", "G-GROWS", "drop the Sprint 19 framing from G-P", sub(f"; {GP_SPRINT}", "")),
    M("M-122", "G-GROWS", "give G-W3 E29-S01's due date",
      lambda t: cell("| G-W3 ", 4, "nothing blocks; the drawn states meanwhile; due "
                     f"{(t.values or {})['DATE:E29-S01']}<!--=DATE:E29-S01-->")(t)),
    M("M-123", "G-DECK", "shorten `fills.error` by one character",
      deck_edit(lambda es: es["fills.error"].__setitem__("string", str(es["fills.error"]["string"])[:-1]))),
    M("M-124", "G-RULED", 'write "owner approval granted" for the RULED paragraph\'s pending clause',
      sub("**PROPOSED, owner approval pending (#2701)**", "**PROPOSED, owner approval granted**")),
    M("M-125", "G-RULED", "delete §4's Change requests paragraph",
      lambda t: replace(t, spec=t.spec.replace(row_line("**Change requests**")(t.spec), "", 1))),
    M("M-126", "G-CELLS", "let §4's CR table swallow a paragraph",
      lambda t: replace(t, spec=t.spec.replace(row_line("| comfortable control height ")(t.spec),
                        row_line("| comfortable control height ")(t.spec) + "A note.\n", 1))),
    M("M-127", "G-QUOTE", "rename §10's exit-refusal counter",
      sub("`oms_exit_refused_total{operation,code}`", "`oms_exit_refusals_total{operation,code}`")),
    # pin probes (no measured or lexicon gate reads these units)
    M("P-1", "G-RULED-PIN", "reword a §5 sentence",
      sub("Redlines: D02 §12 and board 21", "Redlines: D02 §12 with board 21")),
    M("P-2", "G-RULED-PIN", "change C-l's reading", cell("| C-l ", 2, "D03's budget alone (§10)")),
    M("P-3", "G-RULED-PIN", "rename §11's heading",
      sub("## 11. Not designed yet, and why", "## 11. Not designed yet")),
    M("P-4", "G-RULED-PIN", "turn §11's paragraph into a bullet",
      sub("why\n\nTrade groups and Algos:", "why\n\n- Trade groups and Algos:")),
    M("P-5", "G-RULED-PIN", "change a deck entry's owner",
      deck_edit(lambda es: es["fills.footer"].__setitem__("owner", "E29-D02"))),
)  # fmt: skip


def texts_digest(t: Texts) -> str:
    h = hashlib.sha256()
    for part in (
        t.spec,
        t.deck,
        *sorted(t.disk.items()),
        t.stray,
        t.handoffs,
        sorted(t.head_commits.items()),
        t.head_ok,
        t.mb,
    ):
        h.update(repr(part).encode("utf-8"))
    return h.hexdigest()


def disk_digest() -> str:
    h = hashlib.sha256()
    for rel in (*OWN, *UNTOUCHED):
        p = ROOT / rel
        h.update(p.read_bytes() if p.exists() else b"")
    return h.hexdigest()


def self_test() -> int:
    t0 = load()
    t0 = replace(t0, values=compute(t0))
    fails0, notes0, _w, _n = audit(t0)
    if fails0 or notes0:
        print("self-test: the baseline is not clean; run --check first")
        for f in fails0 + notes0:
            print(f"  {f}"[:200].encode("ascii", "replace").decode())
        return 1
    d0, disk0 = texts_digest(t0), disk_digest()
    ok = True
    for mu in MUTATIONS:
        t1 = mu.edit(copy.deepcopy(t0))
        if texts_digest(t1) == d0:
            print(f"{mu.mid}: no change applied")
            ok = False
            continue
        fails, _notes, _w, _n = audit(t1)
        tags = [f.split("]")[0].lstrip("[") for f in fails]
        good = tags == [mu.gate]
        ok &= good
        line = f"{mu.mid} {'ok  ' if good else 'BAD '} {mu.gate:<14} got {tags}"
        print(line.encode("ascii", "replace").decode())
        if not good:
            for f in fails:
                print(f"    {f[:180]}".encode("ascii", "replace").decode())
    if texts_digest(t0) != d0 or disk_digest() != disk0:
        print("self-test: a text was not restored byte-identically")
        ok = False
    print(f"--self-test: {'ok' if ok else 'FAIL'} -- {len(MUTATIONS)} mutations in memory")
    return 0 if ok else 1


# ---------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fill", action="store_true")
    ap.add_argument("--self-test", "--selftest", dest="self_test", action="store_true")
    ap.add_argument("--repin-ruled", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    t = load()
    if a.fill:
        filled, missing = fill(t.spec, compute(t))
        if missing:
            print(f"FAIL fill: unknown keys {sorted(set(missing))}")
            return 1
        (ROOT / SPEC_REL).write_text(filled, encoding="utf-8", newline="\n")
        t = load()
        print(f"--fill: {len(ANCHOR.findall(filled))} anchors written")
    if a.repin_ruled:
        if PLACEHOLDER.search(t.spec):
            print("FAIL repin: a placeholder is unfilled; run --fill first")
            return 1
        units = all_units(t)
        (ROOT / PIN_REL).write_text(write_pins(units), encoding="utf-8", newline="\n")
        print(f"--repin-ruled: {len(units)} units pinned")
        return 0
    if a.check or a.json or a.fill:
        fails, notes, warns, n = audit(t)
        pins = read_pins()
        tail = (
            f"check: {n} cites and deck strings read at {BASE}; {len(pins or ())} units pinned; "
            f"{len(fails)} FAIL / {len(notes)} NOTE / {len(warns)} WARN"
        )
        if a.json:
            out = {
                "base": BASE,
                "values": compute(t),
                "fails": fails,
                "notes": notes,
                "warns": warns,
                "tail": tail,
            }
            print(json.dumps(out, ensure_ascii=True, indent=2))
            return 1 if fails else 0
        for f in fails:
            print(f"FAIL {f}".encode("ascii", "replace").decode())
        for x in notes + warns:
            print(x.encode("ascii", "replace").decode())
        print(tail)
        return 1 if fails else 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
