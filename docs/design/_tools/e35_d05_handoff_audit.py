#!/usr/bin/env python3
"""E35-D05 (#940) audit: the rule-engine screens' engineering hand-off pack (spec + keyed deck).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base `aba03ac309` (`git show`; #4829's merge, PR 1): the plan texts the
spec cites, the merged E35 design texts D02, D03, D04 and their hand-offs, the E36-D05 sister pack
and its deck, the backlog JSON, the calendar, the token JSON and the board tree; D04 at its merge
`0fe451f1da` for the lifted sections; and, from the working tree, the spec
`docs/design/E35/E35-D05.md`, the deck `docs/design/E35/E35-D05-copy.json`, `14` and the files
the pack must not edit.

1. **Values.** Every `{{KIND:key}}` is a placeholder that `--fill` writes as
   `VALUE<!--=KIND:key-->`: COUNT (boards in the base tree, the spec's own table rows, the deck's
   entries by status, the log's ids), DATE (a sprint start from the backlog JSON and
   `calendar_cv.py`), HASH (sha256 prefix of a lifted D04 section at its merge) and CITE (a
   figure parsed from the cited line). `--check` re-derives each anchored value (G-ANCHOR, with a
   left boundary, so "121" never hides "21"), FAILs a `{{` left behind, any HTML comment that is
   not an anchor (G-MARKER), a hand-typed figure before a unit (G-FIGURE) and a count written as
   a word before a counted noun (G-WORDCOUNT).
2. **Cites.** Every `NN`:line and named-file cite in the spec and the deck is read at the base and
   must be a non-blank line (G-CITE); quoted copy and every backticked event name in the spec must
   occur verbatim in a doc its line cites or in the ticket JSON (G-QUOTE); every deck string must
   equal a whole unit of its source line, never a substring (G-DECK), and every quoted string of
   the source spans BQ-15 names must be in the deck or carried by cite (the union, G-DECK).
3. **Gates.** One FAIL line per gate. Measured gates read the spec's tables cell by cell
   (G-FRAMES, G-STATES, G-BIND, G-A11Y, G-CMP, G-FROZEN, G-LIFT, G-FROW, G-GROWS, G-LOG,
   G-CONSUMERS, G-WALK, G-PERF, G-AROW); G-RULED requires each ruled sentence verbatim in its
   section and reads every clause, headings included, against a lexicon of opposite readings (a
   negation covers its own term only within its phrase); the lexicon is a tripwire for the
   paraphrases the lenses tried, not a proof: the default-deny pins (4.) are the backstop, and
   `--repin-ruled` prints every unit it changes so a reworded sentence shows in the PR. G-SESSION
   refuses a claimed session; G-DELTA reads §11's story deltas against each story's own text;
   G-SUPERSEDED keeps a superseded token out of the bindings; G-HOOKS and G-CROW close §11's
   test hooks and §14's letters. G-UNTOUCHED
   compares the working tree with `git merge-base HEAD origin/main` (committed, uncommitted and
   untracked paths alike): only `14` may differ, by exactly BQ-3's six pointer lines and the A-02
   / A-03 clauses; an unresolvable merge-base FAILs. G-VERSION FAILs (never WARNs) when a pinned
   input's last commit at `origin/main` differs from the base's, and when `origin/main` does not
   resolve; neither fetches, so run `git fetch origin main` first (the tail prints the sha read).
   G-CHARSET (NFKC on the whole line; CR, trailing whitespace; `…` only inside quoted merged
   copy; a letter outside Latin only inside quoted copy or a code span), G-CELLS (escaped pipes
   kept), G-CLOSE, G-URL, G-UNMERGED, G-UNBUILT,
   G-NOHANDOFF, G-BUDGET, G-GITLEAKS, G-TOKEN and G-MUTLIST close the set.
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of the spec (each
   heading, table row by its lead cell, rule line and prose sentence, by heading path and
   occurrence, with a line-shape tag per region) and over every deck entry, in
   `e35_d05_ruled_pins.txt`. Anchored values are cut out of the pinned text (G-ANCHOR owns them).
   `--repin-ruled` is the only writer and refuses while a placeholder is unfilled. A pin finding
   in a section another gate already FAILs prints as a NOTE line.
5. **--self-test** applies every mutation of the spec's §15 (and the tool's own P-n pin probes)
   in memory, with the values frozen at the filled baseline; each must add exactly one FAIL, from
   the gate it names; every text is restored byte-identically (sha256 in memory and on disk).
   Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e35_d05_handoff_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e35_d05_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e35_d05_handoff_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import difflib
import functools
import hashlib
import html
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
BASE = "aba03ac309"  # origin/main once PR 1 (#4829) merged (C-r); every cite is read here
HEAD = "origin/main"  # G-VERSION: a pinned input's last commit here must equal the base's
D04_SHA = "0fe451f1da"  # D04's merge (#4728): the lifted sections are hashed here

SPEC_REL = "docs/design/E35/E35-D05.md"
DECK_REL = "docs/design/E35/E35-D05-copy.json"
TOOL_REL = "docs/design/_tools/e35_d05_handoff_audit.py"
PIN_REL = "docs/design/_tools/e35_d05_ruled_pins.txt"
PLAN14 = "docs/plan/14-screens-catalogue.md"
OWN = (SPEC_REL, DECK_REL, TOOL_REL, PIN_REL, PLAN14)
LINE_BUDGET = 300  # BQ-4 as RULED: "one spec (<= 300 lines, the fourteen sections as listed)"

CITE_FILES = {
    "D02H": "docs/design/E35/E35-D02-handoff.md",
    "D03H": "docs/design/E35/E35-D03-handoff.md",
    "D02": "docs/design/E35/E35-D02.md",
    "D03": "docs/design/E35/E35-D03.md",
    "D04": "docs/design/E35/E35-D04.md",
    "MEMO": "docs/design/research/e35-rule-arming-trust.md",
    "E36P": "docs/design/E36/E36-D05.md",
    "E36DECK": "docs/design/E36/E36-D05-copy-deck.json",
    "E11-D09": "docs/design/E11/E11-D09.md",
    "E10H": "docs/design/E10/E10-D04-handoff.md",
    "CONST": "CONSTITUTION.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "KM": "apps/web/src/keymap/keymap.json",
    "README": "docs/design/README.md",
    "E35.json": "docs/plan/backlog/E35.json",
    "E36.json": "docs/plan/backlog/E36.json",
    "RCRUD": "services/api/candleviewer/api/rules_crud.py",
    "RAPI": "services/api/candleviewer/api/rules.py",
    "NAV": "apps/web/src/features/app-shell/navItems.ts",
}
PLAN = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "12": "docs/plan/12-sitemap.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "14": PLAN14,
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
}
# The standing list (the ruling's "Standing" line) plus `15` (PR 1 carries it) and the backlog.
UNTOUCHED = tuple(
    [PLAN[k] for k in ("02", "05", "15", "16", "22", "23", "24")]
    + [
        CITE_FILES[k]
        for k in ("D02", "D02H", "D03", "D03H", "D04", "MEMO", "E36P", "E36DECK", "KM")
    ]
    + [CITE_FILES[k] for k in ("E35.json", "E36.json", "README", "CONST")]
)
POINTER = (
    "- **Hand-off pack:** [E35-D05.md](../design/E35/E35-D05.md) v1 (E35-D05; owner approval"
    " pending; a11y contract: E35-D04)"
)
POINTER_DELTA = POINTER.replace("**Hand-off pack:**", "**Hand-off pack (E35-D03 delta):**")
POINTER_SCREENS = ("SCR-084", "SCR-085", "SCR-086", "SCR-087")
DELTA_SCREENS = ("SCR-088", "SCR-089")
E36_POINTER = "- **Hand-off pack:** [E36-D05.md](../design/E36/E36-D05.md)"
# BQ-3 as RULED: A-02 and A-03 applied in `14` now (D04:834-835), re-pinned by content.
A_ROWS_14 = (
    (
        "SCR-085",
        "the environment choice is a radio group with DEMO preselected",
        (
            "the environment is a read-only line until the arm request carries it (E35-D02 D02-G5),"
            " then a radio group with DEMO preselected"
        ),
    ),
    (
        "SCR-086",
        (
            "requires an explicit precedence ordering (drag"
            " list or numeric priority) before both can"
            " stay armed"
        ),
        (
            "requires an explicit precedence ordering (an ordered list with Move up / Move down;"
            " E35-D03 D03-C4) before both can stay armed"
        ),
    ),
)
# BQ-34: the version line's pinned inputs and their shas (the boards ride with D03).
IMG_DIR = "docs/design/E35/img"
PINNED = {
    CITE_FILES["D02"]: "3c8c42e27e",
    CITE_FILES["D02H"]: "3c8c42e27e",
    CITE_FILES["D03"]: "a8e51aca6d",
    CITE_FILES["D03H"]: "a8e51aca6d",
    IMG_DIR: "a8e51aca6d",
    CITE_FILES["D04"]: "0fe451f1da",
    CITE_FILES["MEMO"]: "4eebb713d9",
    CITE_FILES["E36P"]: "c861679e14",
    CITE_FILES["E36DECK"]: "c861679e14",
}
# BQ-19: the D04 sections lifted as they stand (D04:851), with their line spans.
LIFTED = (
    ("§5.1–§5.6", 175, 227, "d04.s5"),
    ("§6.1–§6.5", 231, 249, "d04.s6"),
    ("§7.1", 253, 323, "d04.s7"),
    ("§8.1–§8.4", 327, 370, "d04.s8"),
    ("§9.1", 374, 397, "d04.s9"),
    ("§10", 420, 430, "d04.s10"),
    ("§11.1–§11.4", 434, 448, "d04.s11"),
    ("§12", 450, 469, "d04.s12"),
    ("§13's replacements", 473, 492, "d04.s13"),
    ("§16.4", 829, 838, "d04.s16"),
)
SCREENS = ("SCR-084", "SCR-085", "SCR-086", "SCR-087", "SCR-088", "SCR-089")
DECK_SCREENS = (*SCREENS, "SCR-006")
STATUSES = ("merged", "binding-pending-owner", "shipped", "PROPOSED")
ANNOUNCE = ("polite", "assertive", "none")
OWNERS = ("E35-D02", "E35-D03", "E35-D04")
DECK_TOP = ("pack", "version", "base", "header", "strings", "events", "carried_by_cite")
ENTRY_FIELDS = ("string", "screen", "owner", "status", "announce", "source", "params", "rt",
                "frozen", "order")  # fmt: skip
HEADER = (
    "The copy deck contains the safety-critical strings; changing them later is a product "
    "decision requiring design and security review, not a copy tweak"
)
# BQ-16 as RULED (PROPOSED): the frozen rows; FZ-09 is the whole `rules.reason.*` class.
FROZEN = {
    "FZ-01": "rules.sim.ca1",
    "FZ-02": "rules.arm.ca8",
    "FZ-03": "rules.arm.ca26",
    "FZ-04": "rules.arm.ca10",
    "FZ-05": "rules.arm.ca17",
    "FZ-06": "rules.arm.ca31",
    "FZ-07": "rules.conflict.new11",
    "FZ-08": "rules.conflict.new45",
    "FZ-09": "rules.reason.*",
    "FZ-10": "rules.editor.stop.tightens, rules.editor.flatten.ack",
}
# BQ-17: the required order of the caveat pair and of block 6.
ORDER = {"rules.sim.ca2": 1, "rules.sim.ca1": 2, "rules.arm.ca8": 1}
# BQ-15: the source spans whose quoted strings the deck must hold (doc, first, last, cell index,
# loose placeholder match, instance match).
UNION = (
    ("D02", 302, 389, 2, False, False),
    ("D02", 395, 403, 1, False, False),
    ("D03", 370, 432, 2, False, False),
    ("D03", 220, 265, 3, False, False),
    ("D04", 257, 321, 5, True, False),
    ("D04", 333, 356, 2, True, False),
    ("D02", 163, 171, 4, False, True),
    ("D02", 216, 232, 6, False, True),
    ("D03", 171, 180, 2, False, True),
    ("D03", 194, 208, 2, False, True),
    ("D03", 282, 285, 2, False, True),
    ("D03", 301, 306, 2, False, True),
)
# The state tables (BQ-10): every frame row is a state row's source.
STATE_SPANS = (
    ("D02", 163, 171, "SCR-084"),
    ("D02", 216, 232, "SCR-085"),
    ("D03", 171, 180, "SCR-086"),
    ("D03", 194, 208, "SCR-087"),
    ("D03", 282, 285, "SCR-088"),
    ("D03", 301, 306, "SCR-089"),
)
# `14`'s States lines and the frame words that carry them.
STATES_14 = (
    (1925, "SCR-084", ("idle", "running", "completed", "partial", "failed", "no-history")),
    (1978, "SCR-087", ("empty", "streaming", "failed-rows", "engine-restart-marker")),
)
# BQ-6 as RULED: the A-row ids PR 1 applies, per component (F replacements folded first).
CMP_ROWS = (
    ("CMP-154", 1778, ("D02-A1", "F-11", "F-07", "D02-C13")),
    ("CMP-156", 1797, ("D02-A2", "D03-A1", "F-06", "D03-C9", "D03-C10", "A-04", "F-02")),
    ("CMP-158", 1817, ("arming dialog (SCR-085)", "CA-26", "CMP-028 `info`", "BQ-7")),
    ("CMP-159", 1831, ("D02-A6", "D03-A2", "F-18")),
    ("CMP-233", 2750, ("D02-A5",)),
    ("CMP-234", 2759, ("D03-A3", "F-10")),
)
# AC2's Storybook location, as PR 1 merged it: each component's `15` Storybook line.
STORY_LINE = {"CMP-154": 1785, "CMP-156": 1805, "CMP-158": 1827, "CMP-159": 1838,
              "CMP-233": 2756, "CMP-234": 2766}  # fmt: skip
PR1_FOLDS = "F-02, F-07, F-10, F-11, F-13, F-14, F-18; F-06 as D04 reads it"
# BQ-20 / BQ-6 / BQ-31 as RULED: each F row's landing class and its stories.
F_LANDING = {
    **dict.fromkeys(("F-02", "F-06", "F-07", "F-10", "F-11", "F-13", "F-14", "F-18"), "PR 1"),
    **dict.fromkeys(("F-03", "F-04", "F-05"), "recorded to E05; not fixed here"),
    **dict.fromkeys(("F-01", "F-08", "F-12", "F-15", "F-16", "F-17"), "this pack"),
    "F-09": "the deck",
}
S08_F = ("F-02", "F-07", "F-08", "F-11", "F-12", "F-13", "F-14", "F-15")
S09_F = ("F-01", "F-06", "F-08", "F-09", "F-10", "F-12", "F-13", "F-16", "F-17", "F-18")
# BQ-21 as RULED.
G_CLOSED = tuple(f"G-{n:02d}" for n in (1, 2, 3, 4, 5, 6, 7, 10, 11, 13, 14))
G_ROUTED = ("G-08", "G-09", "G-12", "G-15")
# Each G-row's consuming story, by the screen its D04 line names (D04:806-820; lens 3, M5); the
# routed rows reach E35-Q06's acceptance list (§10).
G_CONSUMER = {
    "G-01": ("E35-S09",), "G-02": ("E35-S09",), "G-03": ("E35-S08", "E35-S09"),
    "G-04": ("E35-S09",), "G-05": ("E35-S08",), "G-06": ("E35-S08",), "G-07": ("E35-S09",),
    "G-10": ("E35-S09",), "G-11": ("E35-S08", "E35-S09"), "G-13": ("E35-S08",),
    "G-14": ("E35-S09",), **dict.fromkeys(G_ROUTED, ("E35-Q06",)),
}  # fmt: skip
# The closing defaults D04 does not state: the pack's own wording, marked (lens 1, m5).
PACK_WORDED = ("G-10", "G-11")
PACK_MARK = "(the pack's PROPOSED wording, heuristic)"
NO_DEFAULT = re.compile(r"decided nowhere|not decided|undecided|to be decided|no default|\bTBD\b")
CONSUMER_ISSUES = (
    "#1048", "#1049", "#1113", "#1186", "#1046", "#1047", "#1114", "#1050", "#1115",
    "#1059", "#1062", "#958", "#947", "#874",
)  # fmt: skip
PUBLICATION = (
    "**Publication:** one comment each at merge on #56, S08, S09, Q06, D06, Q03, Q04, Q07, T06,"
    " X03, #947 and #874."
)
FEATURES_DIR = "apps/web/src/features/"
CHARSET_ALLOW = frozenset("…")
UNIT = (
    r"(?:px|ms|s|%|fps|Hz|KB|rows?|days?|rules|entries|strings?|keys?|events?|boards?|frames?"
    r"|renders?|items?|ids?|characters|lines?|mutations?|findings?|screens?|states?|sections?"
    r"|questions?|components?|variants?|sprints?|gaps?|messages?|drops?|blocks?|checks?)"
)  # G-FIGURE's units cover G-WORDCOUNT's counted nouns (lens 2, Minor-4)

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


@functools.lru_cache(maxsize=64)
def base_lines(doc: str) -> tuple[str, ...]:
    rel = cite_path(doc)
    if rel is None:
        return ()
    text = git_show(BASE, rel)
    return tuple(text.split("\n")) if text is not None else ()


def line_at(doc: str, n: int) -> str:
    lines = base_lines(doc)
    return lines[n - 1] if 1 <= n <= len(lines) else ""


def tree_at(rev: str, prefix: str) -> tuple[str, ...]:
    return tuple(n for n in git_out("ls-tree", "--name-only", rev, prefix).split("\n") if n)


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


def table_of(block: str, lead: str) -> list[list[str]]:
    """The data rows of the one table in `block` whose header's lead cell is `lead`."""
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


def pin_norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sec_key(heading: str) -> str:
    """A `##` section's key: its number, "RULED" for the ruling's heading, or its first word."""
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


_DASHES = re.compile(r"[\u2010-\u2015\u2212-]")


def norm_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", strip_comments(text))
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = t.replace("\u2019", "'").replace("'s ", " s ")
    t = re.sub(r"[*`']", "", t)
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
        elif ln.strip():  # a heading is read as a clause too (lens 2, Minor-2)
            out += [c for c in SENTENCE.split(ln.lstrip("#").strip()) if c.strip()]
    return out


# ---------------------------------------------------------------------------- the texts


@dataclass
class Texts:
    spec: str
    deck: str
    disk: dict[str, str]  # the untouched files and `14`, from the working tree
    stray: tuple[str, ...]  # changed paths outside OWN (against the merge-base, and untracked)
    handoffs: tuple[str, ...]  # any E35-D05 hand-off file present
    head_commits: dict[str, str] = field(default_factory=dict)  # G-VERSION: last commit at HEAD
    values: Values | None = None  # frozen values (self-test); None = computed
    head_ok: bool = True  # G-VERSION: `origin/main` resolves
    mb: str = ""  # G-UNTOUCHED: `git merge-base HEAD origin/main` ("" = unresolved)


def stray_of(diff_names: str, untracked: str) -> tuple[str, ...]:
    """Paths changed against the merge-base (committed or not) or untracked, outside the pack."""
    paths = {p.strip() for p in f"{diff_names}\n{untracked}".split("\n") if p.strip()}
    return tuple(sorted(p for p in paths if p not in OWN))


def load() -> Texts:
    spec = (ROOT / SPEC_REL).read_bytes().decode("utf-8")
    deck = (ROOT / DECK_REL).read_bytes().decode("utf-8")
    disk = {
        rel: (ROOT / rel).read_text(encoding="utf-8")
        for rel in (*UNTOUCHED, PLAN14)
        if (ROOT / rel).exists()
    }
    mb = git_out("merge-base", "HEAD", HEAD).strip()
    head_ok = bool(git_out("rev-parse", "--verify", "--quiet", f"{HEAD}^{{commit}}").strip())
    diff = git_out("diff", "--name-only", mb) if mb else ""
    stray = stray_of(diff, git_out("ls-files", "--others", "--exclude-standard"))
    handoffs = tuple(
        str(p.relative_to(ROOT)) for p in (ROOT / "docs/design/E35").glob("E35-D05*handoff*")
    )
    heads = {rel: last_commit(HEAD, rel) for rel in PINNED}
    return Texts(spec, deck, disk, stray, handoffs, heads, head_ok=head_ok, mb=mb)


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


def deck_data(t: Texts) -> dict[str, object]:
    data, _dups = parse_deck(t.deck)
    return data if isinstance(data, dict) else {}


def deck_entries(t: Texts) -> dict[str, dict[str, object]]:
    """The deck's entries by key (an object keyed by id, so no `"key": value` line exists for the
    secret scanners to read)."""
    strings = deck_data(t).get("strings")
    if not isinstance(strings, dict):
        return {}
    return {str(k): v for k, v in strings.items() if isinstance(v, dict)}


def carried(t: Texts) -> list[dict[str, object]]:
    rows = deck_data(t).get("carried_by_cite")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


@functools.lru_cache(maxsize=1)
def e36_deck() -> dict[str, dict[str, object]]:
    data = json.loads(at_base(CITE_FILES["E36DECK"]))
    strings = data.get("strings", {})
    return {str(k): v for k, v in strings.items() if isinstance(v, dict)}


def key_set(t: Texts) -> set[str]:
    return set(deck_entries(t)) | {str(r.get("id")) for r in carried(t)}


# ---------------------------------------------------------------------------- values


def cal_start(n: int, offset: int = 0) -> str:
    cal = at_base(CITE_FILES["CAL"])
    m = re.search(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", cal)
    d = re.search(r"SPRINT_DAYS = (\d+)", cal)
    if not m or not d:
        raise SystemExit("FAIL parse: calendar_cv.py")
    start = datetime.date(int(m[1]), int(m[2]), int(m[3]))
    return (start + datetime.timedelta(days=(n - 1) * int(d[1]) + offset)).isoformat()


@functools.lru_cache(maxsize=1)
def sprints() -> dict[str, int]:
    out: dict[str, int] = {}
    for key in ("E35.json", "E36.json"):
        data = json.loads(at_base(CITE_FILES[key]))
        items = data if isinstance(data, list) else data.get("tickets", [])
        for it in items:
            m = re.search(r"(\d+)", str(it.get("sprint", "")))
            if m:
                out[str(it.get("key"))] = int(m[1])
    return out


def boards(prefix: str) -> set[str]:
    return {
        m[1]
        for n in tree_at(BASE, IMG_DIR + "/")
        if (m := re.match(rf"{IMG_DIR}/{prefix}-(\d\d)-[a-z0-9-]+\.png$", n))
        and not re.search(r"-(greyscale|deuteranopia)\.png$", n)
    }


def lifted_hash(rev: str, a: int, b: int) -> str:
    text = git_show(rev, CITE_FILES["D04"]) or ""
    chunk = "\n".join(text.split("\n")[a - 1 : b])
    return hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:12]


CITE_FIGURES = {
    "row.compact": ("D02", 142, r"Compact (\d+) px"),
    "row.comfortable": ("D02", 142, r"comfortable (\d+) px"),
    "w.drawer": ("D02", 142, r"\*\*(\d+) px\*\* wide"),
    "w.dialog": ("D02", 175, r"\*\*(\d+) px\*\* wide"),
    "w.lg": ("15", 467, r"420 / 560 / (\d+) px"),
    "footer.compact": ("D02", 175, r"footer (\d+) px compact"),
    "footer.comfortable": ("D02", 175, r"compact / (\d+) comfortable"),
    "w.resolver": ("D03", 140, r"\((\d+) px;"),
    "cad.lane": ("D04", 362, r"at most once per (\d+) s"),
    "cad.d02": ("D02", 150, r"at most every (\d+) s"),
    "len.override": ("D04", 233, r"at most (\d+) characters"),
    "zoom": ("D04", 444, r"At (\d+) %"),
    "perf.sim.days": ("14", 1930, r"Target: (\d+) days"),
    "perf.sim.s": ("14", 1930, r"<=(\d+) s"),
    "perf.arm.s": ("14", 1955, r"within (\d+) s"),
    "perf.conflict.s": ("14", 1969, r"<=(\d+) s"),
    "perf.conflict.rules": ("14", 1969, r"for (\d+) rules"),
    "perf.hist.rows": ("14", 1982, r"(\d+k) rows"),
    "perf.hist.ms": ("14", 1982, r"exceeding (\d+) ms"),
    "perf.ir.kb": ("14", 1993, r"over (\d+) KB"),
    "perf.io.rules": ("14", 2006, r"a (\d+)-rule bundle"),
    "perf.io.s": ("14", 2006, r"<=(\d+) s"),
    "perf.ws.ms": ("23", 831, r"\| (\d+) ms"),
}


def compute(t: Texts) -> Values:
    if t.values is not None:
        return t.values
    v: Values = {}
    d02, d03 = boards("E35-D02"), boards("E35-D03")
    renders = [
        n
        for n in tree_at(BASE, IMG_DIR + "/")
        if re.search(r"E35-D03-.*-(greyscale|deuteranopia)", n)
    ]
    v["COUNT:boards.d02"], v["COUNT:boards.d03"] = str(len(d02)), str(len(d03))
    v["COUNT:renders.d03"], v["COUNT:boards.merged"] = str(len(renders)), str(len(d02) + len(d03))
    v["COUNT:states"] = str(len(state_rows(t.spec)))
    es = deck_entries(t)
    v["COUNT:deck.entries"] = str(len(es))
    for st, key in (("merged", "merged"), ("binding-pending-owner", "bpo"), ("shipped", "shipped"),
                    ("PROPOSED", "proposed")):  # fmt: skip
        v[f"COUNT:deck.{key}"] = str(sum(1 for e in es.values() if e.get("status") == st))
    v["COUNT:deck.announced"] = str(sum(1 for e in es.values() if "rt" in e))
    ev = deck_data(t).get("events")
    v["COUNT:deck.events"] = str(len(ev) if isinstance(ev, list) else 0)
    v["COUNT:deck.carried"] = str(len(carried(t)))
    v["COUNT:fz"] = str(len(table_of(h2(t.spec, "§5"), "FZ")))
    rts = [split_row(line_at("D04", n)) for n in range(333, 357)]
    v["COUNT:rt"] = str(len(rts))
    v["COUNT:rt.proposed"] = str(sum(1 for r in rts if r[-1].startswith("PROPOSED")))
    v["COUNT:f.rows"] = str(len({i for r in frow_rows(t.spec) for i in f_ids(r[0])}))
    lr = log_rows(t.spec)
    v["COUNT:log.ids"] = str(len({i for r in lr for i in expand_ids(r[0])}))
    v["COUNT:log.unowned"] = str(sum(1 for r in lr if len(r) < 4 or r[3] in ("", "—")))
    v["COUNT:log.undated"] = str(
        sum(1 for r in lr if len(r) < 6 or not (ANCHOR.search(r[5]) or PLACEHOLDER.search(r[5])))
    )
    v["COUNT:log.nodefault"] = str(
        sum(1 for r in lr if len(r) < 3 or r[2] in ("", "—") or NO_DEFAULT.search(r[2]))
    )
    v["COUNT:walk"] = str(len(re.findall(r"\bW-(\d+)\b", h2(t.spec, "§12"))))
    for key, n in sprints().items():
        v[f"DATE:{key}"] = cal_start(n)
    v["DATE:S15.end"] = cal_start(15, 6)
    for _label, a, b, key in LIFTED:
        v[f"HASH:{key}"] = lifted_hash(D04_SHA, a, b)
    for key, (doc, n, rx) in CITE_FIGURES.items():
        m = re.search(rx, strip_comments(line_at(doc, n)))
        v[f"CITE:{key}"] = m[1] if m else "?"
    return v


# ---------------------------------------------------------------------------- the spec's tables


def state_rows(spec: str) -> list[list[str]]:
    return [r for r in table_of(h2(spec, "§2"), "S") if re.fullmatch(r"S-\d\d", r[0])]


def bind_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§3"), "Screen")


def cmp_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§4"), "CMP")


def fz_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§5"), "FZ")


def frow_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§7"), "F")


def grow_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§7"), "G")


def log_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§10"), "Ids")


def consumer_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§11"), "Consumer")


def perf_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§9"), "Screen")


def pa_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§13"), "A")


def c_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§14"), "C")


def f_ids(cell: str) -> list[str]:
    """`F-03..F-05`, `F-13, F-14` → the F ids."""
    out: list[str] = []
    for a, b in re.findall(r"F-(\d\d)(?:\.\.F-(\d\d))?", cell):
        out += [f"F-{n:02d}" for n in range(int(a), int(b or a) + 1)]
    return out


def g_ids(cell: str) -> list[str]:
    out: list[str] = []
    for a, b in re.findall(r"G-(\d\d)(?:\.\.G-(\d\d))?", cell):
        out += [f"G-{n:02d}" for n in range(int(a), int(b or a) + 1)]
    return out


def expand_ids(cell: str) -> list[str]:
    """The log's ids: `D02-G1–D02-G3`, `D04 Q-02, Q-03`, `D04 C-01..C-26`, `E36-D02 D02-G2, …`,
    `G-P1`, `P-01`; a bare `Q-`/`C-`/`G-nn` takes the prefix of the clause it sits in."""
    out: list[str] = []
    for part in re.split(r";\s*", strip_comments(cell)):
        part = part.replace("`", "").strip()
        m = re.match(r"(D04|E36-D0[235])\s+(.*)$", part)
        pre, body = (m[1] + " ", m[2]) if m else ("", part)
        for tok in re.split(r",\s*", body):
            tok = tok.strip()
            r = re.fullmatch(
                r"((?:D0[23]-)?[A-Z]+-?[A-Z]?)(\d+)(?:–|\.\.)(?:D0[23]-)?[A-Z]+-?[A-Z]?(\d+)", tok
            )
            if r:
                w = len(r[2]) if r[2].startswith("0") else 0
                out += [f"{pre}{r[1]}{str(n).zfill(w)}" for n in range(int(r[2]), int(r[3]) + 1)]
            elif re.fullmatch(r"(?:D0[23]-)?[A-Z]+-?[A-Z0-9]+", tok):
                out.append(f"{pre}{tok}")
    return out


# ---------------------------------------------------------------------------- fill


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


OLD_VALUE = re.compile(r"(?<![\w.,])([0-9a-f?][0-9a-fk,.-]*)?<!--=([A-Z]+:[^>]+?)-->")


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
            pre, want = ln[: m.start()], v[key]
            if not pre.endswith(want) or want == "?":
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


FIGURE = re.compile(rf"(?<![\w.#:§×-])(\d(?:[\d,.]*\d)?)\s?(?:-)?{UNIT}(?![\w-])")


def prose_of(ln: str) -> str:
    """The line without code spans, quotes and anchored values (what a figure gate reads)."""
    work = CODE.sub(" ", ln)
    work = QUOTED.sub(" ", work)
    return re.sub(r"[^\s(|]*<!--=[A-Z]+:[^>]+?-->", " ", work)


def g_figure(t: Texts) -> list[Finding]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if ln.startswith("#") or sec_of_line(t.spec, i) == "§15":
            continue
        for m in FIGURE.finditer(prose_of(ln)):
            bad.append(F("G-FIGURE", f"line {i}: hand-typed figure {m[0]!r}", "spec",
                         sec_of_line(t.spec, i)))  # fmt: skip
    return bad


NUMBER_WORD = (
    r"(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    r"|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty"
    r"|ninety|hundred)(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?"
)
COUNTED = (
    r"(?:screens?|rows?|strings?|entries|keys?|boards?|frames?|questions?|items?|sections?"
    r"|states?|findings?|gaps?|events?|messages?|lines?|mutations?|components?|sprints?|days?"
    r"|drops?|variants?|renders?|ids?|blocks?|checks?)"
)
WORDCOUNT = re.compile(rf"\b{NUMBER_WORD}\s+(?:[a-z'-]+\s+)?{COUNTED}\b", re.IGNORECASE)


def g_wordcount(t: Texts) -> list[Finding]:
    """A count written as a word before a counted noun is a hand-typed figure (lessons)."""
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if ln.startswith("#") or sec_of_line(t.spec, i) == "§15":
            continue
        for m in WORDCOUNT.finditer(prose_of(ln)):
            bad.append(F("G-WORDCOUNT", f"line {i}: a count as a word {m[0]!r}", "spec",
                         sec_of_line(t.spec, i)))  # fmt: skip
    return bad


CITE_HEAD = re.compile(
    r"`?(?P<doc>\d{2}|D0[234]H?|MEMO|E36P|E36DECK|E11-D09|E10H|CONST|CAL|KM|README|E3[56]\.json"
    r"|RCRUD|RAPI|NAV)`?"
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


def cite_problem(doc: str, a: int, b: int) -> str | None:
    lines = base_lines(doc)
    if not lines:
        return f"{doc} unreadable at {BASE}"
    for n in (a, b):
        if not 1 <= n <= len(lines) or not lines[n - 1].strip() or b < a:
            return f"{doc}:{n} is not a line at {BASE}"
    return None


def g_cite(t: Texts) -> list[Finding]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if sec_of_line(t.spec, i) == "§15":
            continue
        for doc, a, b in cites_in(ln):
            why = cite_problem(doc, a, b)
            if why:
                bad.append(F("G-CITE", f"line {i}: {why}", "spec", sec_of_line(t.spec, i)))
    for k, e in deck_entries(t).items():
        for doc, a, b in cites_in(str(e.get("source", ""))):
            why = cite_problem(doc, a, b)
            if why:
                bad.append(F("G-CITE", f"deck {k}: {why}", "deck", "strings"))
    return bad


EVENT = re.compile(r"`(rule\.[a-z_]+)`")


def g_quote(t: Texts) -> list[Finding]:
    bad = []
    ticket = at_base(CITE_FILES["E35.json"]).replace('\\"', '"')
    for i, ln in enumerate(t.spec.split("\n"), 1):
        sec = sec_of_line(t.spec, i)
        if sec == "§15":
            continue
        docs = {d for d, _a, _b in cites_in(ln)}
        pool = [ticket] + [html.unescape("\n".join(base_lines(d))) for d in docs]
        if sec == "§13":  # the A-rows quote `14` as this PR leaves it
            pool.append(t.disk.get(PLAN14, ""))
        for m in EVENT.finditer(strip_comments(ln)):
            if not any(m[1] in p for p in pool):
                bad.append(F("G-QUOTE", f"line {i}: event `{m[1]}` is not in a cited text",
                             "spec", sec))  # fmt: skip
        if ln.startswith("| PA-"):  # the A-rows are G-AROW's: Old against `14`, New is new text
            continue
        src = ln
        work = CODE.sub(lambda m: m[0][1:-1], strip_comments(src)).replace('\\"', "\u0001")
        for m in QUOTED.finditer(work):
            q = m[0][1:-1].replace("\u0001", '"')
            if len(q) < 12 or q.startswith(("PROPOSED,", "owner approval")):
                continue
            if not any(q in p or q in p.replace("`", "") for p in pool):
                bad.append(F("G-QUOTE", f"line {i}: {q[:50]!r} is not verbatim in a cited text",
                             "spec", sec))  # fmt: skip
    return bad


FORBIDDEN_COPY = re.compile(r"ret_?msg|ret_?code|\bretCode\b|Traceback|Exception\b", re.IGNORECASE)
PENDING_COPY = re.compile(r"\bTBD\b|\bTODO\b")
QUOTE_SENT = re.compile(r"(?<=[.!?…])\s+")


def quotes_of(cell: str) -> list[str]:
    """Quoted copy in a cell; an attribute value (`role="alert"`) is not copy."""
    return [html.unescape(m[1]) for m in re.finditer(r'(?<![=\w])"([^"\n]*)"', cell)]


def wholes(line: str) -> set[str]:
    """The whole units a deck string may equal on its source line (whole-string equality, never a
    substring): the content of a "…" quote (HTML entities decoded); one whole sentence of a quote;
    one item of an unquoted parenthesised " · " list (D03:401's filter values)."""
    out: set[str] = set()
    for q in quotes_of(line):
        out.add(q)
        out.update(QUOTE_SENT.split(q))
    for par in re.findall(r"\(([^()\"]*· [^()\"]*)\)", line):
        out.update(p.strip() for p in par.split(" · "))
    # BQ-33's folds: one label of a colon-led " · " list, asides dropped (D02:152's summary rows,
    # D03:143's columns), or of a parenthesised list of bare lowercase phrases (D03:51's kinds)
    flat = line
    while (nxt := re.sub(r"\([^()]*\)", "", flat)) != flat:
        flat = nxt
    for lst in re.findall(r":\s*([^:;.\"|]*? · [^:;.\"|]*)", flat):
        out.update(p.strip() for p in lst.split(" · "))
    for par in re.findall(r"\(([a-z][a-z ]*(?:, [a-z][a-z ]*){2,})\)", line):
        out.update(p.strip() for p in par.split(", "))
    return out


def norm_a(s: str) -> str:
    return re.sub(r"[{}]", "", s)


def norm_b(s: str) -> str:
    return re.sub(r"\{[^{}]*\}", "{}", s)


def held(s: str, pool: list[str], loose: bool, instance: bool) -> bool:
    """`s` is in the pool: equal, equal with braces dropped, (loose) equal with every placeholder
    blanked, or (instance) a filled placeholder form, one sentence, or a result word + reason."""
    for x in pool:
        if x == s or norm_a(x) == norm_a(s) or (loose and norm_b(x) == norm_b(s)):
            return True
        if instance:
            rx = "".join(
                ".+?" if p.startswith("{") else re.escape(p) for p in re.split(r"(\{[^{}]*\})", x)
            )
            if re.fullmatch(rx, s) or s in QUOTE_SENT.split(x):
                return True
    m = re.match(r"✗ Failed — (.+)$", s) if instance else None
    return bool(m and any(x == "Failed — " + m[1] for x in pool))


def status_of(doc: str, n: int) -> str:
    """The deck status a source row fixes (D02 §8 / D03 §11's Status column; else PROPOSED)."""
    cells = split_row(line_at(doc, n))
    if doc == "D02" and 302 <= n <= 389 or doc == "D03" and 370 <= n <= 432:
        w = cells[3].split(" ")[0].strip("·").lower() if len(cells) > 3 else ""
        if w in ("unchanged", "grammar", "ruled", "e36-d03"):
            return "merged"
        if w in ("binding-pending-owner", "shipped"):
            return w
        if doc == "D03" and cells[0].startswith("`rbac"):
            return "merged"
    if doc == "D02" and 395 <= n <= 403 and cells[0].startswith("`rbac"):
        return "merged"
    return "PROPOSED"


@functools.lru_cache(maxsize=1)
def rt_region() -> dict[str, str]:
    out = {}
    for n in range(333, 357):
        c = split_row(line_at("D04", n))
        out[c[0]] = c[3]
    return out


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
    if (data.get("pack"), data.get("version"), data.get("base")) != ("E35-D05", "v1", BASE):
        D("the deck's pack, version or base is wrong")
    if data.get("header") != HEADER or HEADER not in at_base(CITE_FILES["E35.json"]):
        D("the header is not T Sec's sentence verbatim (BQ-14)")
    members = data.get("strings")
    for k, v in (members if isinstance(members, dict) else {}).items():
        if not isinstance(v, dict):
            D(f"{k}: a member of strings that is not an entry")
    es = deck_entries(t)
    seen: dict[str, str] = {}
    for k, e in es.items():
        extra = set(e) - set(ENTRY_FIELDS)
        if extra:
            D(f"{k}: unknown fields {sorted(extra)}")
        for f_ in ("string", "screen", "owner", "status", "announce", "source"):
            if not isinstance(e.get(f_), str) or not str(e.get(f_)).strip():
                D(f"{k}: {f_} missing or empty")
        s = str(e.get("string", ""))
        nk = norm_a(s)
        if nk in seen:
            D(f"{k}: the string of {seen[nk]} again (BQ-15: each once)")
        seen.setdefault(nk, k)
        want = list(dict.fromkeys(re.findall(r"\{([^{}]+)\}", s)))
        if e.get("params", []) != want or ("params" in e and not want):
            D(f"{k}: params must name the string's placeholders in order")
        if any(x not in DECK_SCREENS for x in str(e.get("screen", "")).split(", ")):
            D(f"{k}: screen {e.get('screen')!r}")
        if e.get("announce") not in ANNOUNCE:
            D(f"{k}: announce {e.get('announce')!r}")
        if FORBIDDEN_COPY.search(s) or PENDING_COPY.search(s):
            D(f"{k}: exchange text, exception text or a TBD in user copy (T Sec; D03:87)")
        src = cites_in(str(e.get("source", "")))
        if len(src) != 1 or src[0][1] != src[0][2]:
            D(f"{k}: source must be one line")
            continue
        doc, n, _b = src[0]
        if e.get("owner") != f"E35-{doc}" or doc not in ("D02", "D03", "D04"):
            D(f"{k}: owner {e.get('owner')!r} is not its source's spec")
        if s not in wholes(line_at(doc, n)):
            D(f"{k}: not a whole quote or sentence at {doc}:{n} (no substring)")
        if e.get("status") not in STATUSES or e.get("status") != status_of(doc, n):
            D(f"{k}: status {e.get('status')!r}, its source row fixes {status_of(doc, n)!r}")
        rt = e.get("rt")
        if rt is not None and (rt not in rt_region() or e.get("announce") != rt_region()[rt]):
            D(f"{k}: announce {e.get('announce')!r} is not {rt}'s region (BQ-22)")
        if rt is None and e.get("announce") != "none":
            D(f"{k}: an announced string names its RT row")
        fz = e.get("frozen")
        want_fz = next((z for z, kk in FROZEN.items() if kk == k), None)
        if k.startswith("rules.reason."):
            want_fz = "FZ-09"
        if fz != want_fz:
            D(f"{k}: frozen {fz!r}, the table says {want_fz!r} (BQ-16)")
        if e.get("order") != ORDER.get(k):
            D(f"{k}: order {e.get('order')!r} (BQ-17: CA-2, CA-1; CA-8 first)")
    for key, z in FROZEN.items():
        for kk in z.split(", "):
            if not kk.endswith("*") and kk not in key_set(t):
                D(f"{key}: {kk} is in neither the deck nor its carried rows")
    ev = data.get("events")
    if not isinstance(ev, list) or not ev:
        D("events: a list of event rows (BQ-27)")
        ev = []
    for r in ev:
        if not isinstance(r, dict) or set(r) != {"event", "class", "screen", "trigger", "source"}:
            D(f"events: {r!r:.40} is not event · class · screen · trigger · source")
            continue
        sid = re.search(r"S-\d\d", str(r["trigger"]))
        rows = {x[0]: x[1] for x in state_rows(t.spec)}
        if not sid or rows.get(sid[0]) != r["screen"]:
            D(f"events: {r['event']}'s trigger names no {r['screen']} state row (BQ-14)")
        src = cites_in(str(r["source"]))
        line = line_at(src[0][0], src[0][1]) if len(src) == 1 else ""
        if r["class"] not in ("audited", "analytics") or str(r["event"]) not in line:
            D(f"events: {r['event']} is not named at its source, or its class is wrong")
        if r["screen"] not in SCREENS:
            D(f"events: {r['event']}'s screen")
    e36 = e36_deck()
    e36_lines = at_base(CITE_FILES["E36DECK"]).split("\n")
    # never re-keyed (§5): a string #947's deck holds on the same shared screen is carried by cite
    shared = {(str(v.get("text")), str(v.get("screen"))) for v in e36.values()}
    for k, e in es.items():
        for scr in str(e.get("screen", "")).split(", "):
            if scr in ("SCR-088", "SCR-089") and (str(e.get("string")), scr) in shared:
                D(f"{k}: re-keys #947's {scr} string {str(e.get('string'))[:30]!r} (carry it)")
    for r in carried(t):
        cid = str(r.get("id"))
        src = cites_in(str(r.get("source", "")))
        ok = (
            set(r) == {"id", "owner", "source"}
            and cid in e36
            and r.get("owner") == "E36-D05 (#947)"
            and len(src) == 1
            and src[0][0] == "E36DECK"
            and e36_lines[src[0][1] - 1].strip().startswith(json.dumps(cid) + ":")
        )
        if not ok:
            D(f"carried {cid}: not #947's key at its E36DECK line")
    # BQ-15: the union, each quoted string of the named spans held once
    pool = [str(e.get("string")) for e in es.values()]
    cpool = [str(e36[str(r.get("id"))].get("text")) for r in carried(t) if str(r.get("id")) in e36]
    for doc, a, b, col, loose, inst in UNION:
        for n in range(a, b + 1):
            cells = split_row(line_at(doc, n))
            if len(cells) <= col:
                continue
            for q in quotes_of(cells[col]) + (
                [p for par in re.findall(r"\(([^()\"]*· [^()\"]*)\)", cells[col])
                 for p in par.split(" · ")] if doc == "D03" and 370 <= n <= 432 else []
            ):  # fmt: skip
                if not held(q.strip(), pool, loose, inst) and not held(
                    q.strip(), cpool, loose, True
                ):
                    D(f"{doc}:{n}: {q[:40]!r} is not in the deck (BQ-15)")
    return bad


def keys_of(cell: str, keys: set[str]) -> tuple[list[str], list[str]]:
    """(the deck ids a Keys cell names, the names it uses that the deck lacks)."""
    found, missing = [], []
    for k in re.findall(r"`([^`]+)`", cell):
        if k in keys:
            found.append(k)
        elif k.endswith(".*") and any(d.startswith(k[:-1]) for d in keys):
            found += [d for d in keys if d.startswith(k[:-1])]
        else:
            missing.append(k)
    return found, missing


def frame_name(cell: str) -> str:
    """`SCR-084/idle` → idle; `treatment view-as` → view-as; `treatment flag-off (R3)` →
    flag-off."""
    c = cell.strip("`")
    return c.split("/")[-1].strip() if c.startswith("SCR-") else c.split()[1] if " " in c else c


def g_states(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    keys = key_set(t)
    rows = state_rows(t.spec)
    covered: set[str] = set()
    spans: list[tuple[str, int, int, str]] = []
    for n, r in enumerate(rows, 1):
        if r[0] != f"S-{n:02d}":
            bad.append(F("G-STATES", f"{r[0]}: out of sequence (S-{n:02d} expected)", sec="§2"))
        if len(r) != 6:
            bad.append(F("G-STATES", f"{r[0]}: cell count", sec="§2"))
            continue
        found, missing = keys_of(r[5], keys)
        if not found or missing:
            bad.append(F("G-STATES", f"{r[0]}: keys {missing or 'none'} not in the deck", sec="§2"))
        # a key named whole is on its row's screen (SCR-085 hands off to SCR-006's step-up, S-12)
        on = {r[1], "SCR-006"} if r[1] == "SCR-085" else {r[1]}
        for k in re.findall(r"`([^`]+)`", r[5]):
            e = deck_entries(t).get(k)  # a `.*` family is not a key named whole
            if e is not None and not on & set(str(e.get("screen", "")).split(", ")):
                bad.append(F("G-STATES", f"{r[0]}: {k}'s screen is not {r[1]}", "deck", "strings"))
        covered.update(found)
        cs = cites_in(r[3])
        if not cs:
            bad.append(F("G-STATES", f"{r[0]}: no source cite", sec="§2"))
        spans += [(d, a, b, r[1]) for d, a, b in cs]
        for d, a, b in cs:
            span = next((s for s in STATE_SPANS if s[0] == d and s[1] <= a and b <= s[2]), None)
            if span is None or span[3] != r[1]:
                bad.append(F("G-STATES", f"{r[0]}: {d}:{a} is not a {r[1]} state row", sec="§2"))
            frames = {frame_name(split_row(line_at(d, x))[0]) for x in range(a, b + 1)}
            named = {w.strip().split(" ")[0] for w in r[2].split(";")}
            if not frames <= named | {w.split("-")[-1] for w in named}:
                bad.append(F("G-STATES", f"{r[0]}: frames {sorted(frames - named)[:2]} unnamed",
                             sec="§2"))  # fmt: skip
        bm = re.fullmatch(r"(D0[23]) (\d\d(?:, \d\d)*)", r[4])
        if not bm or not set(bm[2].split(", ")) <= boards(f"E35-{bm[1]}"):
            bad.append(F("G-STATES", f"{r[0]}: board {r[4]!r} is not a merged board", sec="§2"))
    for k in sorted(set(deck_entries(t)) - covered):
        bad.append(F("G-STATES", f"deck key {k} has no state row (AC1)", sec="§2"))
    for d, a, b, scr in STATE_SPANS:
        for n in range(a, b + 1):
            if not any(x == d and lo <= n <= hi for x, lo, hi, _s in spans):
                bad.append(F("G-STATES", f"the {scr} state at {d}:{n} has no S row", sec="§2"))
    for n, scr, words in STATES_14:
        line = line_at("14", n)
        for w in words:
            if w.split("-")[0] not in line.replace("failure rows", "failed"):
                bad.append(F("G-STATES", f"`14`:{n} no longer reads {w!r}", sec="§2"))
            if not any(r[1] == scr and re.search(rf"(?<![\w-]){w}(?![\w-])", r[2]) for r in rows):
                bad.append(F("G-STATES", f"`14`:{n}'s {w!r} has no {scr} row", sec="§2"))
    return bad


def g_frames(t: Texts) -> list[Finding]:
    bad = []
    rows = table_of(h2(t.spec, "§2"), "Spec")
    if [r[0] for r in rows] != ["D02", "D03", "D04"]:
        bad.append(F("G-FRAMES", "the frame index holds D02, D03 and D04", sec="§2"))
    for r in rows:
        if len(r) != 5 or r[0] == "D04":
            continue
        page = cites_in(r[2])
        if not page or "id" not in line_at(page[0][0], page[0][1]):
            bad.append(F("G-FRAMES", f"{r[0]}: the page cite holds no page id", sec="§2"))
        drawn = set(re.findall(r"(?<![\w-])(\d\d)(?![\w-])", strip_comments(r[1])))
        if drawn != boards(f"E35-{r[0]}"):
            bad.append(F("G-FRAMES", f"{r[0]}: the boards named are not the merged set", sec="§2"))
    return bad


BIND_STATUS = re.compile(
    r"^(?:(?:served(?: \([^)]*\))?|shipped-not-served|G-rows? [A-Z0-9 ,-]+|contract-gap D02-CG1"
    r"|served for those two)(?:; |$))+$"
)


@functools.lru_cache(maxsize=1)
def g_row_ids() -> frozenset[str]:
    ids = {m for ln in base_lines("D02")[502:513] for m in re.findall(r"\| (D02-G\d+) ", ln)}
    ids |= {m for ln in base_lines("D03")[503:520] for m in re.findall(r"\| (D03-G\d+) ", ln)}
    return frozenset(ids | {"D03-G1", "D03-G12"})


def g_bind(t: Texts) -> list[Finding]:
    """BQ-12: every redline row names its field at the cited `22` / `23` line, its status, and
    only G-rows that exist upstream; every screen has rows."""
    bad = []
    rows = bind_rows(t.spec)
    if {r[0] for r in rows} != set(SCREENS):
        bad.append(F("G-BIND", "every screen has a redline row", sec="§3"))
    for r in rows:
        if len(r) != 6:
            bad.append(F("G-BIND", f"{r[0]} {r[1][:20]}: cell count", sec="§3"))
            continue
        if not BIND_STATUS.match(r[4]):
            bad.append(F("G-BIND", f"{r[0]} {r[1][:20]}: status {r[4]!r}", sec="§3"))
        for gid in re.findall(r"D0[23]-G\d+", r[4]):
            if gid not in g_row_ids() and "E36-D03" not in r[4]:
                bad.append(F("G-BIND", f"{r[0]}: {gid} is no upstream G-row", sec="§3"))
        names = re.findall(r"`([A-Za-z_.]+)`", r[3])
        for doc, a, _b in cites_in(r[3]):
            if doc in ("22", "23") and not any(
                nm.split(".")[0] in line_at(doc, a) or nm.split(".")[-1] in line_at(doc, a)
                for nm in names
            ):
                bad.append(F("G-BIND", f"{r[0]}: `{doc}`:{a} names none of {names[:2]}", sec="§3"))
        for doc, a, _b in cites_in(r[4]):
            if doc in ("RCRUD", "RAPI") and "@router." not in line_at(doc, a):
                bad.append(F("G-BIND", f"{r[0]}: {doc}:{a} is not a route", sec="§3"))
        unrouted = not re.search(r"RCRUD|RAPI|the topic|for those", r[4])
        if r[4].startswith("served") and unrouted and "`23`" not in r[3]:
            bad.append(F("G-BIND", f"{r[0]}: served without its route", sec="§3"))
    for name, rx in (("simulateRule", r"/simulate"), ("listRuleRuns", r"/runs")):
        if any(re.search(rx, ln) for ln in base_lines("RCRUD") + base_lines("RAPI")):
            bad.append(F("G-BIND", f"{name} is served at the base now: re-read §3", sec="§3"))
    return bad


@functools.lru_cache(maxsize=1)
def d04_sets() -> dict[str, dict[str, set[str]]]:
    """Per screen, the D04 ids that apply (BQ-19): N (§7.1's Screen), RT (§8.1's Surface),
    T (§12's Surface), K (§5.4's Scope), AL (§14.2's Screen, `all` excluded)."""
    out: dict[str, dict[str, set[str]]] = {s: {} for s in SCREENS}

    def put(kind: str, rid: str, scope: str) -> None:
        if scope.strip() == "all":
            targets: tuple[str, ...] = SCREENS
        elif "SCR-084..SCR-089" in scope:
            targets = SCREENS
        else:
            targets = tuple(x for x in SCREENS if x in scope)
        for s in targets:
            out[s].setdefault(kind, set()).add(rid)

    for n in range(257, 322):
        c = split_row(line_at("D04", n))
        put("N", c[0], c[1])
    for n in range(333, 357):
        c = split_row(line_at("D04", n))
        put("RT", c[0], c[1])
    for n in range(456, 470):
        c = split_row(line_at("D04", n))
        put("T", c[0], c[1])
    for n in range(201, 216):
        c = split_row(line_at("D04", n))
        if c[3] != "Rules":
            put("K", c[0], c[3])
    for n in range(523, 539):
        c = split_row(line_at("D04", n))
        if c[2] != "all":
            put("AL", c[0], c[2])
    return out


def ids_in(text: str, kind: str) -> set[str]:
    out: set[str] = set()
    for a, b in re.findall(rf"\b{kind}-(\d\d)(?:\.\.{kind}-(\d\d))?", text):
        out |= {f"{kind}-{n:02d}" for n in range(int(a), int(b or a) + 1)}
    return out


FOCUS_ROW = {"SCR-084": 179, "SCR-085": 180, "SCR-086": 181, "SCR-087": 182, "SCR-088": 183,
             "SCR-089": 184}  # fmt: skip


def g_a11y(t: Texts) -> list[Finding]:
    """BQ-19: each screen's D04 ids, inline in §3, equal"
    " D04's own sets (made impossible to miss)."""
    bad = []
    block = h2(t.spec, "§3")
    for scr in SCREENS:
        m = re.search(rf"^- \*\*{scr}(?: deltas)? \(D04, pinned\):\*\*(.*)$", block, re.MULTILINE)
        if not m:
            bad.append(F("G-A11Y", f"{scr}: no pinned D04 line in §3", sec="§3"))
            continue
        line = m[1]
        want = d04_sets()[scr]
        for kind in ("N", "RT", "T", "K", "AL"):
            got = ids_in(line, kind)
            if got != want.get(kind, set()):
                diff = sorted(got ^ want.get(kind, set()))[:3]
                bad.append(F("G-A11Y", f"{scr}: {kind} ids differ from D04 ({diff})", sec="§3"))
        if f"D04:{FOCUS_ROW[scr]}" not in line:
            bad.append(F("G-A11Y", f"{scr}: the focus row is D04:{FOCUS_ROW[scr]}", sec="§3"))
    if "AL-08..AL-12, AL-15, AL-16" not in block:
        bad.append(F("G-A11Y", "the all-screen AL rows are named once", sec="§3"))
    return bad


def story_problems(cid: str, head: int, cell: str) -> list[Finding]:
    """AC2's Storybook location: the cell cites the component's merged `15` Storybook line and
    every story it names is on that line; a component PR 1 gave no story names its G-P row."""
    n = STORY_LINE[cid]
    nxt = next((i for i in range(head + 1, head + 40) if line_at("15", i).startswith("### ")), 0)
    ok = (
        cites_in(cell) == [("15", n, n)]
        and line_at("15", n).startswith("- **Storybook**:")
        and head < n < nxt
    )
    bad = [] if ok else [F("G-CMP", f"{cid}: Storybook is not `15`:{n}", sec="§4")]
    for name in re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", strip_comments(cell)):
        if name not in line_at("15", n):
            bad.append(F("G-CMP", f"{cid}: story {name} is not on `15`:{n}", sec="§4"))
    if "none" in cell and not re.search(r"\bG-P\d+\b", cell):
        bad.append(F("G-CMP", f"{cid}: a missing story names its G-P row", sec="§4"))
    return bad


def g_cmp(t: Texts) -> list[Finding]:
    bad = []
    rows = cmp_rows(t.spec)
    if [r[0][:7] for r in rows] != [c for c, _n, _a in CMP_ROWS]:
        bad.append(F("G-CMP", "the map holds CMP-154, 156, 158, 159, 233, 234 in order", sec="§4"))
    for r, (cid, line15, arows) in zip(rows, CMP_ROWS, strict=False):
        if len(r) != 6:
            continue
        c15 = cites_in(r[2])
        if c15 != [("15", line15, line15)] or not line_at("15", line15).startswith(f"### {cid}"):
            bad.append(F("G-CMP", f"{cid}: `15` cite is not its heading", sec="§4"))
        if any(a not in r[3] for a in arows):
            bad.append(F("G-CMP", f"{cid}: PR 1's A-rows are {', '.join(arows)} (BQ-6)", sec="§4"))
        for doc, a, _b in cites_in(r[4]):
            hd = line_at(doc, a)
            if not hd.startswith("## Handoff checklist") or (
                cid not in hd and "composite" not in hd
            ):
                bad.append(F("G-CMP", f"{cid}: {doc}:{a} is not its checklist", sec="§4"))
        bad += story_problems(cid, line15, r[5])
    block = h2(t.spec, "§4")
    for cid, n in re.findall(r"(CMP-\d{3}) \(`15`:(\d+)\)", block):
        if not line_at("15", int(n)).startswith(f"### {cid}"):
            bad.append(F("G-CMP", f"{cid}: `15`:{n} is not its heading", sec="§4"))
    if PR1_FOLDS not in block:
        bad.append(F("G-CMP", "PR 1 folds the F replacements first (BQ-6)", sec="§4"))
    return bad


def g_frozen(t: Texts) -> list[Finding]:
    bad = []
    rows = fz_rows(t.spec)
    if [r[0] for r in rows] != list(FROZEN):
        bad.append(F("G-FROZEN", f"FZ rows are {', '.join(FROZEN)} (BQ-16)", sec="§5"))
    es = deck_entries(t)
    for r in rows:
        if len(r) != 6 or r[0] not in FROZEN:
            continue
        ks = re.findall(r"`([^`]+)`", r[1])
        if ", ".join(ks) != FROZEN[r[0]]:
            bad.append(F("G-FROZEN", f"{r[0]}: keys {ks}", sec="§5"))
        e = es.get(ks[0]) if ks else None
        if e is not None:
            if cites_in(r[4]) != cites_in(str(e.get("source"))):
                bad.append(F("G-FROZEN", f"{r[0]}: source is not the deck's", sec="§5"))
            if str(e.get("status")) not in r[3]:
                bad.append(F("G-FROZEN", f"{r[0]}: status is not the deck's", sec="§5"))
        if f"frozen:{r[0]}" not in r[5] and "#947's" not in r[5]:
            bad.append(F("G-FROZEN", f"{r[0]}: no pinning test hook", sec="§5"))
    return bad


def g_lift(t: Texts) -> list[Finding]:
    bad = []
    block = h2(t.spec, "§7")
    m = re.search(r"\*\*Lifted, each with its hash:\*\* (.*)$", block, re.MULTILINE)
    parts = re.findall(r"(§[^()]+?) \(D04:(\d+)–(\d+)\) ([0-9a-f?]*)<!--=HASH:([\w.]+)-->",
                       m[1]) if m else []  # fmt: skip
    if [(p[0].strip(), int(p[1]), int(p[2]), p[4]) for p in parts] != list(LIFTED):
        bad.append(F("G-LIFT", f"the lifted list is not D04:851's {len(LIFTED)} spans", sec="§7"))
    for label, a, b, _key in LIFTED:
        if lifted_hash(D04_SHA, a, b) != lifted_hash(BASE, a, b):
            bad.append(F("G-LIFT", f"{label}: drifted between {D04_SHA} and {BASE}", sec="§7"))
    if not line_at("D04", 851).startswith("No `-handoff.md`"):
        bad.append(F("G-LIFT", "D04:851 no longer holds §17.2's list", sec="§7"))
    return bad


def g_frow(t: Texts) -> list[Finding]:
    bad = []
    rows = frow_rows(t.spec)
    ids = [i for r in rows for i in f_ids(r[0])]
    if ids != [f"F-{n:02d}" for n in range(1, 19)]:
        bad.append(F("G-FROW", "F-01..F-18 once each, in order (BQ-20)", sec="§7"))
    for r in rows:
        if len(r) != 6:
            continue
        for fid in f_ids(r[0]):
            n = 474 + int(fid[2:])
            src = split_row(line_at("D04", n))
            if src[0] != fid or src[1] != r[1]:
                bad.append(F("G-FROW", f"{fid}: severity differs from D04:{n}", sec="§7"))
            if not any(a <= n <= b for d, a, b in cites_in(r[2]) if d == "D04"):
                bad.append(F("G-FROW", f"{fid}: the contract does not cite D04:{n}", sec="§7"))
            if not r[3].startswith(F_LANDING[fid]) and F_LANDING[fid] not in r[3]:
                bad.append(F("G-FROW", f"{fid}: landing is not {F_LANDING[fid]!r}", sec="§7"))
        stories = set(re.findall(r"E35-S0[89]", r[4]))
        want = {
            s
            for fid in f_ids(r[0])
            for s, fs in (("E35-S08", S08_F), ("E35-S09", S09_F))
            if fid in fs
        }
        if stories != want and not set(f_ids(r[0])) <= {"F-03", "F-04", "F-05"}:
            bad.append(F("G-FROW", f"{r[0]}: stories {sorted(want)} (BQ-31)", sec="§7"))
        if r[5] != "pending (#2701)":
            bad.append(F("G-FROW", f"{r[0]}: close state {r[5]!r}", sec="§7"))
    return bad


def g_grows(t: Texts) -> list[Finding]:
    bad = []
    rows = grow_rows(t.spec)
    ids = [i for r in rows for i in g_ids(r[0])]
    if sorted(ids) != sorted(G_CLOSED + G_ROUTED) or len(ids) != len(set(ids)):
        bad.append(F("G-GROWS", "G-01..G-15 once each (BQ-21)", sec="§7"))
    for r in rows:
        if len(r) != 5:
            bad.append(F("G-GROWS", f"{r[0]}: Gap, Disposition, Owner lane, Consumer", sec="§7"))
            continue
        rids = g_ids(r[0])
        want_c = {s for gid in rids for s in G_CONSUMER.get(gid, ())}
        if set(re.findall(r"E35-[SQ]\d\d", r[4])) != want_c:
            bad.append(F("G-GROWS", f"{r[0]}: consumers {sorted(want_c)}", sec="§7"))
        if any(g in rids for g in PACK_WORDED) and r[2].count(PACK_MARK) != len(
            [g for g in rids if g in PACK_WORDED]
        ):
            bad.append(F("G-GROWS", f"{r[0]}: the pack's own default is marked", sec="§7"))
        closed = {i in G_CLOSED for i in rids}
        if closed == {True} and not r[2].startswith("closed, PROPOSED"):
            bad.append(F("G-GROWS", f"{r[0]}: closed in the pack as a PROPOSED default", sec="§7"))
        if closed == {False} and not r[2].startswith("routed"):
            bad.append(F("G-GROWS", f"{r[0]}: routed, not closed", sec="§7"))
        if len(closed) > 1:
            bad.append(F("G-GROWS", f"{r[0]}: mixes closed and routed ids", sec="§7"))
        for gid in rids:
            n = 805 + int(gid[2:])
            if not line_at("D04", n).startswith(f"- **{gid}**") or not any(
                a <= n <= b for d, a, b in cites_in(r[1]) if d == "D04"
            ):
                bad.append(F("G-GROWS", f"{gid}: the gap does not cite D04:{n}", sec="§7"))
    return bad


LOG_UNION = (
    ["D04 Q-01", "D04 Q-02", "D04 Q-03", "D04 Q-04", "D02-Q1", "D03-Q1", "D03-Q2"]
    + [f"D02-G{n}" for n in (1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12)]
    + ["D02-CG1"]
    + [f"D03-G{n}" for n in range(1, 13)]
    + [f"E36-D02 D02-G{n}" for n in (2, 6, 9, 15)]
    + [f"E36-D03 D03-G{n}" for n in (2, 3, 11, 14, 16, 17)]
    + ["E36-D05 F-13"]
    + [f"D02-C{n}" for n in (3, 4, 5, 6, 7, 8, 11, 13)]
    + [f"D03-C{n}" for n in (4, 5, 6, 7, 8, 12)]
    + [f"D04 C-{n:02d}" for n in range(1, 27)]
    + ["D04 G-08", "D04 G-09", "D04 G-12", "D04 G-15"]
    + [f"G-P{n}" for n in range(1, 13)]
    + ["P-01", "P-02"]
)


def g_log(t: Texts) -> list[Finding]:
    bad = []
    rows = log_rows(t.spec)
    v = compute(t)
    ids: list[str] = []
    for r in rows:
        got = expand_ids(r[0])
        ids += got
        if len(r) != 6:
            bad.append(F("G-LOG", f"{r[0][:20]}: cell count", sec="§10"))
            continue
        if r[3] in ("", "—") or re.search(r"\bagent\b|\bworker\b", r[3]):
            bad.append(F("G-LOG", f"{r[0][:20]}: no owner lane (never an agent)", sec="§10"))
        if re.search(r"E35-D0[23]'s (?:and E35-D0[23]'s )?specs?\b", r[3]):
            bad.append(F("G-LOG", f"{r[0][:20]}: owned by a spec no revision reaches (BQ-21)",
                         sec="§10"))  # fmt: skip
        if r[2] in ("", "—") or not (cites_in(r[2]) or "§" in r[2]) or NO_DEFAULT.search(r[2]):
            bad.append(F("G-LOG", f"{r[0][:20]}: no cited, drawn default", sec="§10"))
        cons = [c.strip() for c in r[4].split(",")]
        ok = all(c in sprints() for c in cons)
        first = min(cons, key=lambda c: sprints().get(c, 99)) if ok else ""
        a = ANCHOR.search(r[5]) or PLACEHOLDER.search(r[5])
        if (
            not ok
            or not a
            or a[1] != f"DATE:{first}"
            or (ANCHOR.search(r[5]) and not r[5].startswith(v.get(a[1], "?")))
        ):
            bad.append(F("G-LOG", f"{r[0][:20]}: due is not {r[4]}'s first sprint start",
                         sec="§10"))  # fmt: skip
    missing = [i for i in LOG_UNION if i not in ids]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    extra = [i for i in ids if i not in LOG_UNION]
    if missing or dup or extra:
        bad.append(
            F("G-LOG", f"union: missing {missing[:3]}, repeated {dup[:3]}, unknown {extra[:3]}",
              sec="§10")
        )  # fmt: skip
    if any(v.get(f"COUNT:log.{k}") != "0" for k in ("unowned", "undated", "nodefault")):
        bad.append(F("G-LOG", "unowned = undated = no-default = 0 (BQ-32)", sec="§10"))
    return bad


@functools.lru_cache(maxsize=1)
def scenarios() -> dict[str, tuple[str, ...]]:
    data = json.loads(at_base(CITE_FILES["E35.json"]))
    items = data if isinstance(data, list) else data.get("tickets", [])
    return {
        str(it.get("key")): tuple(re.findall(r"Scenario: ([^\n]+)", str(it.get("body", ""))))
        for it in items
        if it.get("key") in ("E35-S08", "E35-S09")
    }


def s_ids(cell: str) -> set[str]:
    out: set[str] = set()
    for a, b in re.findall(r"S-(\d\d)(?:\.\.S-(\d\d))?", cell):
        out |= {f"S-{n:02d}" for n in range(int(a), int(b or a) + 1)}
    return out


# Each scenario's trace must reach the rows that show it (lens 3, M2, m3, m4): S-24's skipped rows
# and S-26's filter for the cooldown; S-03's caveat (CA-1) for the coverage; the base screen's
# story for the IR clauses that are #947's.
SCENARIO_MUST = {
    "Simulation reports coverage honestly": ("S-03", "S-04"),
    "A suppressed firing is visible too": ("S-24", "S-26"),
    "The IR inspector proves the round trip": ("S-28", "E36-S03 (#1059)"),
    "Compilation failure names the offender (failure case)": ("S-28", "E36-S03 (#1059)"),
}


def g_consumers(t: Texts) -> list[Finding]:
    block = h2(t.spec, "§11")
    bad = [
        F("G-CONSUMERS", f"{i} is not named in §11", sec="§11")
        for i in CONSUMER_ISSUES
        if i not in block
    ]
    rows = {r[0][:7]: r for r in consumer_rows(t.spec) if len(r) == 3}
    states = state_rows(t.spec)
    need = {
        "E35-S08": {r[0] for r in states if r[1] in ("SCR-084", "SCR-085")},
        "E35-S09": {r[0] for r in states if r[1] not in ("SCR-084", "SCR-085")},
    }
    for story, titles in scenarios().items():
        r = rows.get(story)
        if r is None:
            bad.append(F("G-CONSUMERS", f"{story}: no consumer row", sec="§11"))
            continue
        for title in titles:
            seg = next((x for x in r[2].split("; ") if x.startswith(title + ":")), "")
            if not re.search(r": (?:S-\d\d|§\d)", seg):
                bad.append(F("G-CONSUMERS", f"{story}: scenario {title!r} untraced", sec="§11"))
            for must in SCENARIO_MUST.get(title, ()):
                if not re.search(rf"(?<![\w-]){re.escape(must)}(?![\w-])", seg):
                    bad.append(F("G-CONSUMERS", f"{story}: {title[:30]!r} lacks {must}",
                                 sec="§11"))  # fmt: skip
            for sid in s_ids(seg):
                if sid not in need[story]:
                    bad.append(F("G-CONSUMERS", f"{story}: {sid} is not its screen", sec="§11"))
        if s_ids(r[1]) != need[story]:
            bad.append(F("G-CONSUMERS", f"{story} builds its screens' S rows", sec="§11"))
        want_f = S08_F if story == "E35-S08" else S09_F
        got_f = {i for a, b in re.findall(r"F-(\d\d)(?:\.\.F-(\d\d))?", r[1])
                 for i in (f"F-{n:02d}" for n in range(int(a), int(b or a) + 1))}  # fmt: skip
        if got_f != set(want_f):
            bad.append(F("G-CONSUMERS", f"{story}: F rows {sorted(set(want_f) ^ got_f)[:3]}",
                         sec="§11"))  # fmt: skip
    if PUBLICATION not in h2(t.spec, "§13"):
        bad.append(F("G-CONSUMERS", "the publication list (BQ-35)", sec="§13"))
    return bad


# BQ-33 as RULED: the fresh reader's record (2026-10-28), E35-Q06 and E35-D06 apart.
WALK_ROLES = (
    "story: E35-S08 (#1048)", "story: E35-S09 (#1049)", "story: E35-Q06 (#1113)",
    "story: E35-D06 (#1186)", "story: E35-Q03, Q04, Q07", "story: E35-T06, X03",
    "backend: §3's bindings", "QA: §2, every S row",
)  # fmt: skip
WALK_DATE = "2026-10-28"
WRITER_PASS = "not by a fresh reader"
WALK_HEAD = ["Date (UTC)", "Role", "Needs listed", "Found", "Not found", "Disposition"]
DOD_TICK = re.compile(r"^- \[([ x])\] \*\*DoD \(BQ-33 b, c, d\):\*\*", re.MULTILINE)
ARROW = re.compile(r"→\s*(\S+)")


def walk_target(t: Texts, tok: str) -> str | None:
    tok = tok.strip("`*,;.()")
    if m := re.fullmatch(r"§(\d+)", tok):
        return None if h2(t.spec, f"§{m[1]}") else f"no section {tok}"
    if re.fullmatch(r"S-\d\d", tok):
        return None if tok in {r[0] for r in state_rows(t.spec)} else f"no state row {tok}"
    if re.fullmatch(r"G-P\d+|P-\d\d", tok):
        ids = {i for r in log_rows(t.spec) for i in expand_ids(r[0])}
        return None if tok in ids else f"no log row {tok}"
    return f"cannot parse the → target {tok[:20]!r}"


def walk_record(t: Texts) -> list[str]:
    block = h2(t.spec, "§12")
    if not any(ln.startswith("|") and split_row(ln) == WALK_HEAD for ln in block.split("\n")):
        return ["the dry-run table's header"]
    rows = table_of(block, "Date (UTC)")
    bad: list[str] = []
    if [r[1] if len(r) > 1 else "" for r in rows] != list(WALK_ROLES):
        bad.append("one row per consumer of §11, then the backend and QA rows, in order")
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
        if need != found + miss or need == 0:
            bad.append(f"{who}: {need} needs != {found} found + {miss} not found")
        arrows = ARROW.findall(r[5])
        if (miss == 0) != (r[5] == "—") or len(arrows) != miss:
            bad.append(f"{who}: {miss} not found, {len(arrows)} dispositions")
        for tok in arrows:
            why = walk_target(t, tok)
            if why:
                bad.append(f"{who}: {why}")
        if r[1].startswith("QA:") and need != len(state_rows(t.spec)):
            bad.append("the QA row does not cover every §2 row")
        # the backend pass counts each cited `22` / `23` line, so at least one need per §3 row
        if r[1].startswith("backend:") and need < len(bind_rows(t.spec)):
            bad.append("the backend row does not cover every §3 row")
    return bad


def g_walk(t: Texts) -> list[Finding]:
    block = h2(t.spec, "§12")
    ws = [int(x) for x in re.findall(r"\bW-(\d+)\b", block)]
    bad = []
    if ws != list(range(1, len(ws) + 1)) or not 1 <= len(ws) <= 10:
        bad.append(F("G-WALK", f"the owner walkthrough is W-1..W-n, at most ten ({len(ws)})",
                     sec="§12"))  # fmt: skip
    record = walk_record(t)
    for msg in record:
        bad.append(F("G-WALK", f"dry run: {msg}", sec="§12"))
    ticks = DOD_TICK.findall(block)
    acs = [ln for ln in t.spec.split("\n") if ln.startswith(("| AC1 ", "| Scope — the walk"))]
    # BQ-33 (b): the role is given only the pack, the deck and its ticket text; a pass the writer
    # ran is disclosed and leaves the box open (lens 1, m4).
    done = not record and WRITER_PASS not in block
    if ticks != ["x" if done else " "]:
        bad.append(F("G-WALK", "the DoD tick follows a fresh-reader record", sec="§12"))
    ac = "Acceptance-criteria"
    if any(("dry run done" in a) != done for a in acs) or not (
        done or all("dry run pending a fresh reader" in a for a in acs)
    ):
        bad.append(F("G-WALK", "AC1 and the walkthrough row: the dry run is pending", sec=ac))
    return bad


SESSION_CLAIM = (
    r"\b(?:session|walkthrough|meeting)s?\b(?:\s+\S+){0,2}?\s+(?:was |were |has been |is )?"
    r"(?:held|ran|run|recorded|conducted|completed|happened|took place)\b|\btook place\b"
    r"|\bparticipants?\b|\battendees?\b|\bwalked through\b|\b(?:was|were) held\b"
    r"|\bengineers? (?:met|attended|joined|acknowledged|walked)\b|\bbackend lead (?:joined|met"
    r"|attended|signed)\b"
    r"|\b(?:reviewed|read|went through|walked) (?:\S+ ){0,2}?together\b"
    r"|\bon a (?:call|video call)\b"
    r"|\bin a (?:call|meeting|session)\b"
)


def g_motion(t: Texts) -> list[Finding]:
    """BQ-23 as RULED, AC3's audit: every T row of D04 §12 has an instant, identical or static
    reduce twin, a carrier that is not motion and a layout that animates no size; `16` §7 and
    `05` §7 are where §6 says; §6 maps every T row to the ticket's classes."""
    bad = []
    for n in range(456, 470):
        c = split_row(line_at("D04", n))
        if not re.search(r"instant|identical|static", c[4]) or not c[5].strip("— "):
            bad.append(F("G-MOTION", f"{c[0]}: no instant twin or no carrier (D04:{n})", sec="§6"))
        if re.search(r"\banimat\w* (?:the |its )?(?:width|height|size)", c[6]):
            bad.append(F("G-MOTION", f"{c[0]}: animates a size (D04:{n})", sec="§6"))
    if not line_at("16", 173).startswith("## 7. Motion") or not line_at("05", 202).startswith(
        "## 7. Reduced motion"
    ):
        bad.append(F("G-MOTION", "`16` §7 or `05` §7 moved", sec="§6"))
    m = re.search(r"map to T rows: (.*?)\. \*\*Every reduce twin", h2(t.spec, "§6"))
    got = ids_in(m[1] if m else "", "T")
    if got != {f"T-{n:02d}" for n in range(1, 15)}:
        bad.append(F("G-MOTION", f"§6 maps T-01..T-14 ({sorted(got)[:2]})", sec="§6"))
    return bad


# BQ-36: each upstream cite re-pinned by content (the line at this base, the fragment it holds).
REPINS = (
    ("14", 1954, "radio group with DEMO preselected"),
    ("14", 1964, "drag list or numeric priority"),
    ("15", 1797, "### CMP-156 RuleEvaluationTimeline"),
    ("15", 1804, "E35-D03 D03-C9"),
    ("15", 1800, "E35-D03 D03-C10"),
    ("22", 8025, "operationId: simulateRule"),
)


def g_repin(t: Texts) -> list[Finding]:
    bad = []
    block = h2(t.spec, "§0")
    for doc, n, frag in REPINS:
        if frag not in line_at(doc, n):
            bad.append(F("G-REPIN", f"`{doc}`:{n} no longer holds {frag!r}", sec="§0"))
        if f"`{doc}`:{n}" not in block and f":{n}" not in block:
            bad.append(F("G-REPIN", f"§0 does not re-pin to `{doc}`:{n}", sec="§0"))
    return bad


def g_session(t: Texts) -> list[Finding]:
    bad = []
    for key, block in sections(t.spec):
        if key == "§15":
            continue
        for c in clauses(block):
            if live(c, SESSION_CLAIM):
                bad.append(F("G-SESSION", f"a session is claimed: {c[:60]!r}", sec=key))
    return bad


# The ruled sentences, required verbatim in their sections (the ruling's confirmations), and the
# opposite readings refused in any clause (a negation covers its own term).
REQUIRED = (
    ("RULED", "Every default is taken."),
    ("RULED", ("**BQ-3, BQ-4, BQ-6, BQ-7, BQ-9, BQ-12, BQ-19, BQ-21, BQ-23, BQ-29, BQ-33 and BQ-35"
              " are confirmed**")),
    ("RULED", "are **PROPOSED, owner approval pending (#2701)**"),
    ("RULED", "the orchestrator posts the pointer on #2701 at the pack's merge"),
    ("RULED", "**BQ-34** (the versioning rule) is PROPOSED"),
    ("§0", "**One spec plus the deck; no `-handoff.md`** (BQ-4)"),
    ("§0", "**No redraw, no new page, no boards PR** (BQ-9)"),
    ("§0", "D04 G-08 and G-09 are carried, not drawn"),
    ("§0", "**Nothing unmerged is pinned or quoted:**"),
    ("§2", "**Missing treatments are G-rows, never invented** (BQ-10)"),
    ("§3", "carried by id from D02 / D03 and never re-proposed (no `22` / `23` / `24` edit"),
    ("§4", "**No `15` edit in this PR** (G-UNTOUCHED)"),
    ("§4", "**a separate catalogue PR before the pack**"),
    ("§4", "variants are added beside #947's editor contract, never replacing"),
    ("§4", "by name and by the A-row ids PR 1 applied"),
    ("§4", "the `arming dialog (SCR-085)` variant, CA-26 static, inheriting CMP-028 `info`"),
    ("§5", "**No string is invented** (BQ-15)"),
    ("§5", "**Shared rows are carried by cite, never re-keyed:**"),
    ("§5", "**The frozen strings (BQ-16; PROPOSED, owner approval pending (#2701)).**"),
    ("§5", "a rewording needs design and security review, routed to E35-X03 (#1115)"),
    ("§5", "the owner can narrow the set to CA-1 / CA-8 without a redraw"),
    ("§6", "**D04 §12 is the record, by reference**"),
    ("§6", "**Every reduce twin is the instant end state**"),
    ("§6", "`16`:180's recipe against `15`:470 / :500 reads `15`'s"),
    ("§7", ("**The routing table (BQ-22): the stories build to RT-01..RT-24 as D04 has them,"
           " PROPOSED, owner approval pending (#2701)**")),
    ("§7", "if the owner takes Q-01 a versioned delta (§13) moves RT-01..RT-05 to polite"),
    ("§7", "each closes under the owner's `approved`, recorded pending (#2701)"),
    ("§7", ("**G-01..G-07, G-10, G-11, G-13 and G-14 are closed in the pack as PROPOSED defaults**"
           " (no revision of D02 / D03 is coming)")),
    ("§7", "**G-08, G-09, G-12 and G-15 are routed**"),
    ("§7", "**A-06 is recorded and routed to E11**"),
    ("§7", "A-05 is folded into its pointer lines"),
    ("§8", "\"Arm anyway\" returns to SCR-085 and never arms"),
    ("§10", "none without an owner lane, a drawn default the build follows and a due date"),
    ("§10", "Owner lanes, never agents"),
    ("§10", "nothing is filed"),
    ("§11", "**Build follows the design boundary** (BQ-29)"),
    ("§11", ("E36-S03 (#1059) and E36-S06 (#1062) build the SCR-088 / SCR-089 base screens, and"
            " E35-S09 builds E35-D03's deltas onto them")),
    ("§11", "One comment each on #1049, #1059 and #1062 at merge, no body edit by the lane"),
    ("§11", "the C-row routes to the orchestrator"),
    ("§12", "**No session took place and none is claimed**"),
    ("§12", "(d) **A backend-role pass**"),
    ("§12", "before recording any \"not found\" it searches"),
    ("§13", "**Version (BQ-34; PROPOSED):**"),
    ("§13", "which `--check` FAILs at `origin/main`"),
    ("§13", "owner approval pending (#2701); a design PR merges on the owner's approval"),
    ("§13", "which reads as met with room"),
    ("§13", "A-02 and A-03 applied now"),
    ("§13", "(D04's A-05 folded in)"),
)  # fmt: skip
REFUSED = (
    (
        r"\b(?:rt|routing table)\S*(?:\s+\S+){0,8}?\s+(?:is |are |was )?(?:ruled|approved|adopted"
        r"|confirmed|binding|accepted|final|agreed|signed)\b"
    ),
    (
        r"\b(?:frozen (?:strings?|set|table)|freeze)\b(?:\s+\S+){0,6}?\s+(?:is |are |was )?(?:ruled"
        r"|approved|adopted|confirmed|final|accepted|agreed|signed)\b"
    ),
    (
        r"\bversion(?:ing)? (?:rule|line)\b(?:\s+\S+){0,6}?\s+(?:is"
        r" |was )?(?:ruled|approved|adopted"
        r"|confirmed|final|accepted)\b"
    ),
    (
        r"\bowner (?:has |have )?approved\b|\bapproved by the owner\b|\bsigned off\b"
        r"|\bowner (?:has |have )?(?:given|granted|gave)\b"
        r"|\b(?:given|granted|gave|carries|carry|has|got|received?) (?:the |its |their )?"
        r"owner(?: s)? approv\w*|\bowner(?: s)? approv\w* (?:is|was|has been) (?:on|given|recorded"
        r"|received|in|granted|there)\b"
        r"|\bowner(?: s)? approval (?:granted|given|received|obtained)\b"
        r"|\bsign ?off (?:is |was |has been )?(?:recorded|given|received|obtained|done)\b"
    ),
    (
        r"\b(?:this|the pack(?: s)?|same|one|single) pr\b(?:\s+\S+){0,4}?\s+"
        r"(?:edits?|amends?|changes?"
        r"|updates?|carries|touches) (?:the )?(?:15|catalogue)\b"
        r"|\b(?:15|catalogue) (?:entries|edits?|changes?)\b(?:\s+\S+){0,3}?\s+(?:in|inside|with)"
        r" (?:this|the pack(?: s)?) pr\b|\b15 (?:is |gets )?(?:edited|amended|changed) here\b"
    ),
    (
        r"\b(?:a|an|this pack s?|the pack(?: s)?|its own|separate|second|new|extra) handoff\.md\b"
        r"|\bhandoff\.md (?:is|are|was) (?:written|added|shipped|delivered)\b"
        r"|\b(?:second|separate|another|extra|new) hand ?off (?:file|doc\w*|pack|spec)"
    ),
    (
        r"\b(?:new|fresh) penpot (?:page|board|frame)s?\b|\bre ?draw(?:n|s|ing)?\b"
        r"|\bboards? pr (?:is |was )?(?:opened|added|needed|follows)\b"
    ),
    (
        r"\bstrings? (?:is |are |was |were )?invented|\binvents? (?:a |the |one )?(?:new )?string"
        r"|\bcoin(?:s|ed)?\b|\bauthored here\b|\bstrings? (?:\S+ ){0,2}?(?:authored|written"
        r"|drafted|coined) (?:here|by this pack)\b"
    ),
    r"\bre ?key(?:s|ed|ing)?\b",
    (
        r"\bpropos\w* (?:a |the |an )?(?:new )?(?:topic |wire |payload )?(?:shape|schema|payload"
        r"|wire form|endpoint)s?\b|\b(?:shape|schema|payload"
        r"|endpoint)s? (?:\S+ ){0,2}?(?:is |are )?"
        r"(?:drafted|sketched|defined|proposed|added) (?:here|for)\b|\bedits? (?:22|23|24)\b"
    ),
    r"\b(?:only|just) warns?\b|\bwarns? (?:only|instead)\b",
    r"\bextends? (?:\S+ ){0,3}?locally\b|\blocally,? (?:\S+ ){0,4}?extends?\b",
    (
        r"\bg 0?(?:8|9|12|15)\b(?:\s+\S+){0,5}?\s+(?:is |are )?closed\b"
        r"|\bg 0?(?:1|2|3|4|5|6|7|10|11|13|14)\b(?:\s+\S+){0,3}?\s+(?:is"
        r" |are )?(?:routed|left open)\b"
    ),
    (
        r"\ba 06\b(?:\s+\S+){0,4}?\s+(?:is |was )?(?:applied|edited|added|lands)\b"
        r"|\bscr 117 (?:is |gets )?(?:edited|amended) here\b"
    ),
    r"\be35 s09 (?:builds?|owns?) (?:the )?(?:scr 088|scr 089|both screens|the base|the drawer)\b",
    r"\bwaiver (?:is |was )?(?:needed|required|recorded|escalated)\b|\bbreach(?:ed|es)?\b",
    r"\b(?:reword|rephras|edit)\w* (?:\S+ ){0,4}?(?:freely|at will)\b|\bcopy tweak\b",
    (
        r"\b(?:in|as) an appendix\b|\bcop(?:y|ies|ied) of"
        r" d04\b|\bd04 s (?:tables|sections) (?:are )?"
        r"(?:copied|restated)\b"
    ),
    (
        r"\breplac\w* (?:\S+ ){0,3}?(?:#?947 s(?: rule editor)?|the rule editor)"
        r" (?:variant|editor contract|sentence)s?\b"
        r"|\bfs 1 (?:and|/) fs 2 (?:in|on) scr 085\b"
    ),
    r"\barm anyway (?:arms|will arm|does arm)\b",
    r"\bscr 085 (?:has|takes|shows|holds) (?:a |the )?typed\b",
    (
        r"\bbody edits?\b(?:\s+\S+){0,3}?\s+(?:by the lane"
        r"|here)\b|\blane edits? (?:the )?(?:issue )?"
        r"bod(?:y|ies)\b"
    ),
    r"\b(?:agent|worker) (?:owns?|is the owner)\b",
    (
        r"\bsigned (?:\S+ ){0,3}?off\b|\bowner (?:has )?(?:ok ?ed|okayed|blessed|green ?lit|signed"
        r"|accepted|agreed)\b|\bno (?:owner )?approval (?:is )?pending\b"
    ),
    r"\b(?:rt|routing table)\S*(?:\s+\S+){0,3}?\s+binds?\b",
    (
        r"\b(?:this|the) (?:pack|pr) (?:also )?(?:edits?|amends?|changes?|updates?) (?:the )?"
        r"(?:15|catalogue|component catalogue)\b"
    ),
    r"\b(?:new|fresh|extra) (?:page|board|frame)s? (?:\S+ ){0,3}?(?:drawn|added|created)\b",
    r"\binvent(?:ed|s)? (?:\S+ ){0,2}?strings?\b",
    r"\b(?:loosens?|widens?|removes?) (?:a |the )?stop\b",
    (
        r"(?<!\.\.)\bbq (?:16|22|34)\b(?:\s+\S+){0,4}?\s+(?:is |was )?"
        r"(?:ruled|approved|final|confirmed"
        r"|accepted|adopted)\b"
    ),
    # lens 2's paraphrases that passed once re-pinned (A01..A31), one family each
    (
        r"\bowner\b(?! s\b)(?:\s+\S+){0,3}?\s+(?:settled|decided|resolved|ruled|accepted"
        r"|confirmed|cleared|approved|blessed|signed|agreed|endorsed|ratified|locked)\b"
        r"|\b(?:locked|settled|decided|ratified|confirmed|accepted|endorsed|blessed)(?: in)? by the"
        r" owner\b"
    ),
    (
        r"\bowner s (?:go ahead|approval|sign ?off|ok|blessing|consent|nod)\b(?:\s+\S+){0,4}?\s+"
        r"(?:is |was |has been )?(?:in hand|given|granted|recorded|received|obtained|secured"
        r"|on record|done|there)\b"
        r"|\bowner(?: s)? (?:approval|go ahead|sign ?off)\W{0,3}\s*(?:given|granted|received"
        r"|obtained|in hand|recorded|yes|done|secured)\b"
    ),
    (
        r"\b(?:frozen (?:strings?|set|table)|freeze)\b(?:\s+\S+){0,6}?\s+(?:is |are |was )?"
        r"(?:locked|settled|decided|in force|binding|mandatory|endorsed|ratified)\b"
    ),
    (
        r"\b(?:rt|routing table)\S*(?:\s+\S+){0,8}?\s+(?:is |are |was )?(?:mandatory|settled"
        r"|decided|locked|in force|non negotiable|authoritative)\b"
    ),
    r"(?<!\.\.)\bbq (?:16|22|34)\b(?:\s+\S+){0,4}?\s+(?:decided|settled|locked|binding|in force)\b",
    (
        r"\b(?:companion|accompanying|additional|separate|second|extra|another|new) (?:\S+ ){0,2}?"
        r"hand ?off (?:note|file|doc\w*|pack|spec|md)\b"
    ),
    (
        r"\bg 0?(?:8|9|12|15)\b(?:\s+\S+){0,5}?\s+(?:is |are )?(?<!not )(?<!never )"
        r"(?:drawn|resolved|fixed|decided|settled|done|answered)\b"
    ),
    (
        r"\bfills? (?:it|them|the gaps?|the treatments?) in\b|\bfill(?:s|ed)? in (?:the )?"
        r"(?:gap|treatment|missing)"
    ),
    r"\b(?:amends?|changes?|updates?|extends?|adds? to) (?:the )?(?:22|23|24)\b",
    r"\b15 (?:is |gets |was )?(?:updated|edited|amended|changed|touched|extended)\b",
    (
        r"\b(?:supersed|overrid|replac)\w* (?:\S+ ){0,3}?(?:#?947 s(?: rule editor)?|the rule"
        r" editor) (?:variant|editor contract|sentence)s?\b"
    ),
    (
        r"\bstrings? (?:are |were |is |was )?(?:\S+ )?(?:newly |freshly )?(?:written|authored"
        r"|drafted|coined|composed|created|made up) (?:for|here|by)\b"
    ),
    r"\b(?:fresh|own|separate|second|different) keys?\b|\bnew keys? (?:in|for) this deck\b",
    r"\broutine (?:copy )?(?:edit|change|tweak)s?\b|\bcopy edits?\b",
    (
        r"\ba 06\b(?:\s+\S+){0,4}?\s+(?:is |was )?(?:written|made|inserted|folded|put)\b"
        r"|\bscr 117\b(?:\s+\S+){0,3}?\s+(?:edited|amended|written|changed)\b"
    ),
    (
        r"\barm anyway\b(?:\s+\S+){0,6}?\s+(?<!never )(?<!not )(?<!no )(?:arms|arm|arming"
        r"|enables?)\b"
    ),
    (
        r"\b(?:an? |the )?(?:agent|worker)s? (?:\S+ ){0,2}?(?:owns?|holds?|takes?|leads?|runs?)"
        r" (?:the |a |this )?(?:lane|row|question|gap)s?\b"
    ),
    (
        r"\b(?:follow ?up )?(?:issues?|tickets?) (?:are |is |were |was |get )?(?:opened|filed"
        r"|created|raised)\b|\bfil(?:e|es|ed|ing) (?:\S+ ){0,2}?(?:issues?|tickets?)\b"
    ),
    (
        r"\be35 s09\b(?:\s+\S+){0,2}?\s+(?:builds?|owns?|implements?)\b(?:\s+\S+){0,2}?\s+"
        r"(?:scr 08[89]|both screens|base)\b"
    ),
    (
        r"\blane (?:\S+ )?(?:edits?|rewrites?|updates?|changes?|amends?) (?:the )?(?:issue )?"
        r"bod(?:y|ies)\b"
    ),
    r"\b(?:merely|only|just) (?:flags?|warns?|notes?|reports?)\b|\badvisory\b|\bnon ?blocking\b",
    (
        r"\bmerges? (?:\S+ ){0,4}?(?:once|when|after|on) (?:the )?(?:orchestrator|reviewer|lane|qa"
        r"|agent|design)s?\b(?! pr)"
    ),
    r"\b(?:it is |it s )?(?:not|never|hardly) (?:true|the case|so|correct|accurate) that\b",
    r"\b(?:adds?|draws?|ships?|creates?) (?:\S+ ){0,2}?(?:penpot )?(?:boards?|frames?|pages?)\b",
    r"\ba 05\b(?:\s+\S+){0,4}?\s+(?:is |are |was )?applied\b",
    r"\bsister(?: s)? (?:shape|layout|fields)\b",
)


def g_ruled(t: Texts) -> list[Finding]:
    bad = []
    for key, sent in REQUIRED:
        if sent not in h2(t.spec, key):
            bad.append(F("G-RULED", f"{key}: the ruled sentence {sent[:55]!r} is missing", sec=key))
    for rx in REFUSED:
        for sk, block in sections(t.spec):
            if sk == "§15":
                continue
            for c in clauses(block):
                if live(c, rx):
                    bad.append(F("G-RULED", f"{sk}: a paraphrase asserts {rx[:30]!r}: {c[:50]!r}",
                                 sec=sk))  # fmt: skip
    return bad


# BQ-30's story deltas quote each story's own text (lens 1, M1, m1): a quote under a story's name
# is in that story's body, and each re-sourced target cites the line that holds it.
DELTA_CITES = (
    ("→ a read-only line until D02-G5 (D02:76)", "D02", 76, "read-only line"),
    ("→ as stored (D03:534)", "D03", 534, "as-stored"),
)


@functools.lru_cache(maxsize=1)
def story_bodies() -> dict[str, str]:
    data = json.loads(at_base(CITE_FILES["E35.json"]))
    items = data if isinstance(data, list) else data.get("tickets", [])
    return {str(it.get("key")): str(it.get("body", "")) for it in items}


def g_delta(t: Texts) -> list[Finding]:
    bad = []
    m = re.search(r"\*\*Story deltas\*\*(.*)$", h2(t.spec, "§11"), re.MULTILINE)
    para = m[1] if m else ""
    if not para:
        return [F("G-DELTA", "§11 has no story-delta sentence (BQ-30)", sec="§11")]
    parts = re.split(r"(E35-[SQ]\d\d)'s ", para)
    for story, seg in zip(parts[1::2], parts[2::2], strict=False):
        body = story_bodies().get(story, "")
        for q in re.findall(r'"([^"]{3,})"', seg):
            if q not in body:
                bad.append(F("G-DELTA", f"{story}: {q[:40]!r} is not in its text", sec="§11"))
    for want, doc, n, frag in DELTA_CITES:
        if want not in para or frag not in line_at(doc, n):
            bad.append(F("G-DELTA", f"the delta {want[:30]!r} cites {doc}:{n}", sec="§11"))
    return bad


# F-06 (D04:480) supersedes D03's `sunken` on the three surfaces D03:142, :200, :283 bind.
SUPERSEDED_TOKEN = "`color.surface.sunken`"
F06_SCREENS = ("SCR-086", "SCR-087", "SCR-088")


def g_superseded(t: Texts) -> list[Finding]:
    bad = []
    for sk, block in sections(t.spec):
        if sk == "§15":
            continue
        for c in clauses(block):
            if SUPERSEDED_TOKEN in c and "superseded" not in c:
                bad.append(F("G-SUPERSEDED", f"{sk}: sunken bound, F-06 replaces it: {c[:40]!r}",
                             sec=sk))  # fmt: skip
    for scr in F06_SCREENS:
        if not any(r[0] == scr and "`color.surface.app` (F-06" in r[2] for r in bind_rows(t.spec)):
            bad.append(F("G-SUPERSEDED", f"{scr}: no row binds `color.surface.app` (F-06)",
                         sec="§3"))  # fmt: skip
    return bad


# Test hooks (PROPOSED; E36P:565's form): role and N-row name first; each element D04 §7.1 gives
# no role is a G-row (lens 3, M4).
HOOKS = {"G-P6": "restart marker row", "G-P7": "gate strip", "G-P8": "masked tokens",
         "G-P9": "verification strip"}  # fmt: skip
HOOK_LEAD = "**Test hooks (PROPOSED; T is silent; E36P:565's form):**"
HOOK_RULE = "a test finds an element by its role and its N-row name first (D04 §7.1)"


def g_hooks(t: Texts) -> list[Finding]:
    bad = []
    m = re.search(rf"^{re.escape(HOOK_LEAD)}(.*)$", h2(t.spec, "§11"), re.MULTILINE)
    para = m[1] if m else ""
    if not m or HOOK_RULE not in para:
        bad.append(F("G-HOOKS", "§11's PROPOSED test-hook paragraph and its rule", sec="§11"))
    named = [split_row(line_at("D04", n))[2].lower() for n in range(257, 322)]
    for gid, what in HOOKS.items():
        if f"{what} {gid}" not in para:
            bad.append(F("G-HOOKS", f"{gid}: the {what} has no hook G-row", sec="§11"))
        if any(what in x for x in named):
            bad.append(F("G-HOOKS", f"{gid}: the {what} has an N row (a role)", sec="§11"))
    for gid in re.findall(r"\bG-P\d+\b", para):
        if gid not in HOOKS:
            bad.append(F("G-HOOKS", f"{gid} is no role-less element's row", sec="§11"))
    return bad


# BQ-37's letters are kept (lens 1, n1): its C-l, C-n, C-o and C-p, by what each records; new rows
# follow from C-q; a C-row records merged texts, never a private brief (lens 1, m3).
C_LETTERS = {"C-l": "PENDING", "C-n": "6449721354", "C-o": "event", "C-p": "T Brief"}


def g_crow(t: Texts) -> list[Finding]:
    bad = []
    rows = c_rows(t.spec)
    ids = [r[0].split(" ")[0] for r in rows]
    if ids != [f"C-{chr(97 + i)}" for i in range(len(ids))]:
        bad.append(F("G-CROW", "the C-rows run C-a, C-b, … in order", sec="§14"))
    for r in rows:
        if r[0] in C_LETTERS and len(r) > 1 and C_LETTERS[r[0]] not in r[1]:
            bad.append(F("G-CROW", f"{r[0]} is BQ-37's {C_LETTERS[r[0]]!r} row", sec="§14"))
    if any(re.search(r"writing brief|the brief's", b) for k, b in sections(t.spec) if k != "§15"):
        bad.append(F("G-CROW", "a C-row cites a private brief, not a merged text", sec="§14"))
    return bad


def g_version(t: Texts) -> list[Finding]:
    bad = []
    block = h2(t.spec, "§13")
    for rel, sha in PINNED.items():
        if sha not in block:
            bad.append(F("G-VERSION", f"the version line misses {rel}'s {sha}", sec="§13"))
        base_c = last_commit(BASE, rel)
        if not base_c.startswith(sha):
            bad.append(
                F("G-VERSION", f"{rel}: last commit at {BASE} is {base_c[:10]}, pinned {sha}",
                  sec="§13")
            )  # fmt: skip
    if not t.head_ok:
        bad.append(F("G-VERSION", f"{HEAD} does not resolve: the drift is unread", sec="§13"))
    for rel in PINNED:
        head_c = t.head_commits.get(rel, "")
        if t.head_ok and not head_c:
            bad.append(F("G-VERSION", f"{rel}: no last commit at {HEAD}", sec="§13"))
        if head_c and head_c != last_commit(BASE, rel):
            bad.append(
                F("G-VERSION", f"{rel} drifted at {HEAD} ({head_c[:10]}): a late change", sec="§13")
            )
    if f"v1 at base `{BASE}`" not in block or deck_data(t).get("base") != BASE:
        bad.append(F("G-VERSION", f"the version line and the deck name v1 at base {BASE}",
                     sec="§13"))  # fmt: skip
    return bad


def expected_14(base14: str) -> str:
    """`14` at the merge-base plus BQ-3's lines: a pointer after the last Design line of SCR-084
    .. SCR-087, a delta pointer after #947's line on SCR-088 / SCR-089, A-02 and A-03 applied."""
    lines = base14.split("\n")
    heads = [i for i, ln in enumerate(lines) if ln.startswith("### SCR-")]
    out = list(lines)
    inserts: list[tuple[int, str]] = []
    for h in heads:
        scr = lines[h][4:11]
        end = next((j for j in heads if j > h), len(lines))
        body = range(h + 1, end)
        if scr in POINTER_SCREENS:
            last = max((i for i in body if lines[i].startswith("- **Design")), default=-1)
            if last >= 0:
                inserts.append((last + 1, POINTER))
        if scr in DELTA_SCREENS:
            ptr = next((i for i in body if lines[i].startswith(E36_POINTER)), -1)
            if ptr >= 0:
                inserts.append((ptr + 1, POINTER_DELTA))
        for a_scr, old, new in A_ROWS_14:
            if scr == a_scr:
                for i in body:
                    if old in out[i]:
                        out[i] = out[i].replace(old, new, 1)
    for at, ln in sorted(inserts, reverse=True):
        out.insert(at, ln)
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
    want = expected_14(base14)
    if t.disk.get(PLAN14) != want or want.count(POINTER) != 4 or want.count(POINTER_DELTA) != 2:
        diff = [
            d
            for d in difflib.unified_diff(
                want.split("\n"), t.disk.get(PLAN14, "").split("\n"), lineterm="", n=0
            )
            if d[:1] in "+-" and not d.startswith(("+++", "---"))
        ]
        bad.append(F("G-UNTOUCHED", f"`14` is not BQ-3's diff exactly: {diff[:2]}", None, None))
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
    want = f"holds {listed} and no rules slice"
    bad = []
    block = h2(t.spec, "§0")
    if want not in block:
        bad.append(F("G-UNBUILT", f"§0 must read {want[:60]!r}…", sec="§0"))
    routes = "\n".join(base_lines("RCRUD") + base_lines("RAPI"))
    if re.search(r"/simulate|/runs", routes) or "mount no `/simulate` and no `/runs`" not in block:
        bad.append(F("G-UNBUILT", "no route serves /simulate or /runs, said so", sec="§0"))
    if "R-160" not in line_at("NAV", 23) or "`R-160` (NAV:23)" not in block:
        bad.append(F("G-UNBUILT", "the one trace is NAV:23's R-160", sec="§0"))
    return bad


def g_unmerged(t: Texts) -> list[Finding]:
    rx = re.compile(r"#4755\b|/wt/|E35-Q06\.md|E35-D06\.md|catalogue PR's line|PR 1's `15`:")
    return [
        F("G-UNMERGED", f"line {i}: an unmerged text is cited or quoted", "spec",
          sec_of_line(t.spec, i))
        for i, ln in enumerate(t.spec.split("\n"), 1)
        if rx.search(ln) and sec_of_line(t.spec, i) != "§15"
    ]  # fmt: skip


PERF_HEAD = "Budget (from its line)"  # the cells paraphrase `14`; never "verbatim" (lens 1, n2)


def g_perf(t: Texts) -> list[Finding]:
    """BQ-26: each budget row cites its `14` Performance line, its figures anchored there."""
    bad = []
    rows = perf_rows(t.spec)
    want = {1930, 1955, 1969, 1982, 1993, 2006}
    got: set[int] = set()
    for r in rows:
        for doc, a, _b in cites_in(r[4]):
            got.add(a)
            if doc != "14" or not line_at("14", a).startswith("- **Performance:**"):
                bad.append(F("G-PERF", f"{r[0]}: {doc}:{a} is not a Performance line", sec="§9"))
        if "E35-Q04 (#1047)" not in r[3] and "#947" not in r[3]:
            bad.append(F("G-PERF", f"{r[0]}: the benchmark owner is E35-Q04 (#1047)", sec="§9"))
    if got != want:
        bad.append(F("G-PERF", f"the budget rows cite `14`:{sorted(want)}", sec="§9"))
    head = next((split_row(ln) for ln in h2(t.spec, "§9").split("\n") if ln.startswith("| Screen")),
                [])  # fmt: skip
    if head[1:2] != [PERF_HEAD]:
        bad.append(F("G-PERF", f"the budget column reads {PERF_HEAD!r}: its cells paraphrase",
                     sec="§9"))  # fmt: skip
    return bad


def g_arow(t: Texts) -> list[Finding]:
    """BQ-3: each pack A-row is copy-ready: every Old clause occurs once in `14` as this PR leaves
    it and at the base; New differs; Source cites the parent's C-row."""
    bad = []
    now14, base14 = t.disk.get(PLAN14, ""), at_base(PLAN14)
    for r in pa_rows(t.spec):
        if len(r) != 5:
            bad.append(F("G-AROW", f"{r[0]}: cell count", sec="§13"))
            continue
        olds = [q.replace('\\"', '"') for q in re.findall(r'"((?:[^"\\]|\\")*)"', r[2])]
        news = re.findall(r'"((?:[^"\\]|\\")*)"', r[3])
        if not olds or not news and "removed" not in r[3]:
            bad.append(F("G-AROW", f"{r[0]}: Old and New are quoted", sec="§13"))
        for o in olds:
            if now14.count(o) != 1 or base14.count(o) != 1:
                bad.append(F("G-AROW", f"{r[0]}: {o[:40]!r} is not once in `14`", sec="§13"))
        src = cites_in(r[4])  # the parent's C-row first; a further D04 cite backs a new clause
        if (
            not src
            or not re.search(r"\| D0[23]-C\d+", line_at(src[0][0], src[0][1]))
            or any(d != "D04" for d, _a, _b in src[1:])
        ):
            bad.append(F("G-AROW", f"{r[0]}: Source is not a parent C-row", sec="§13"))
    return bad


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
    if CLOSING.search(POINTER) or CLOSING.search(t.disk.get(PLAN14, "").split("\n")[0]):
        bad.append(F("G-CLOSE", "the `14` pointer line: a closing keyword", None, None))
    return bad


URLISH = re.compile(
    r"https?://|\bwww\.|" + "/ho" + "me/" + r"|\\\\|file://|/Users/\w|\.local\b|localhost",
    re.IGNORECASE,
)  # the home-directory fragment is built at run time, so no committed line names a local path


def g_url(t: Texts) -> list[Finding]:
    return per_line("G-URL", URLISH, "a URL, local path, host or user name", t)


def g_charset(t: Texts) -> list[Finding]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        sec = sec_of_line(t.spec, i)
        if "\r" in ln or ln != ln.rstrip():
            bad.append(F("G-CHARSET", f"line {i}: CR or trailing whitespace", "spec", sec))
        quoted = [(m.start(), m.end()) for m in QUOTED.finditer(ln)]
        spans = quoted + [(m.start(), m.end()) for m in CODE.finditer(ln)]
        seen: set[str] = set()
        for idx, ch in enumerate(ln):
            inq = any(a < idx < b for a, b in quoted)
            if (
                ch.isalpha()
                and not unicodedata.name(ch, "").startswith("LATIN")
                and not any(a < idx < b for a, b in spans)
                and ch not in seen
            ):
                seen.add(ch)
                why = f"line {i}: U+{ord(ch):04X} is no Latin letter (a homoglyph outside quotes)"
                bad.append(F("G-CHARSET", why, "spec", sec))
                continue
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
    width = 0
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if not ln.startswith("|"):
            if width and ln.strip():
                bad.append(F("G-CELLS", f"line {i}: a table swallows a paragraph", "spec",
                             sec_of_line(t.spec, i)))  # fmt: skip
            width = 0
            continue
        n = len(split_row(ln, keep_escapes=True))
        if width == 0:
            width = n
        elif n != width:
            bad.append(F("G-CELLS", f"line {i}: {n} cells, its header has {width}", "spec",
                         sec_of_line(t.spec, i)))  # fmt: skip
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
RECOVERY = re.compile(r"(?i)recovery[_-]?code.{0,20}?[a-z0-9]{5}-[a-z0-9]{5}")


def entropy(s: str) -> float:
    c = Counter(s)
    return -sum(v / len(s) * math.log2(v / len(s)) for v in c.values())


def g_gitleaks(t: Texts) -> list[Finding]:
    """The generic-api-key shape (a keyword, an operator, a value of 10+ characters with entropy
    above 3.5) and the repo's recovery-code rule, on every line of the spec, the deck and `14`'s
    pointer lines."""
    bad = []
    for d, x in (("spec", t.spec), ("deck", t.deck), ("14", POINTER + "\n" + POINTER_DELTA)):
        for i, ln in enumerate(x.split("\n"), 1):
            hits = [
                m[1]
                for m in GL.finditer(ln)
                if not re.fullmatch(r"[a-zA-Z_.-]+", m[1]) and entropy(m[1]) > 3.5
            ]
            hits += [m[0] for m in RECOVERY.finditer(ln)]  # fmt: skip
            for v in hits:
                sec = (
                    sec_of_line(t.spec, i) if d == "spec" else ("strings" if d == "deck" else None)
                )
                bad.append(F("G-GITLEAKS", f"{d} line {i}: {v[:30]!r} reads as a secret",
                             d if d != "14" else None, sec))  # fmt: skip
    return bad


TOKEN = re.compile(
    r"`((?:color|size|space|motion|font|border|radius|opacity|elevation|type)\.[a-z0-9.-]+)`"
)


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
        if m[1] not in token_names() and sec_of_line(t.spec, i) != "§15"
    ]


def g_mutlist(t: Texts) -> list[Finding]:
    block = h2(t.spec, "§15")
    listed = re.findall(r"(?:\*\* |; )(M-\d{2,3}) ", block)
    gates: dict[str, str] = {}
    for g, text in re.findall(r"\*\*(G-[A-Z0-9-]+):\*\*((?:(?!\*\*G-)[^\n])*)", block):
        gates[g] = gates.get(g, "") + text
    want = [m.mid for m in MUTATIONS if m.mid.startswith("M-")]
    bad = []
    if sorted(listed) != sorted(want) or len(set(listed)) != len(listed):
        bad.append(
            F("G-MUTLIST", f"§15 lists {len(listed)} mutations, the tool {len(want)}", sec="§15")
        )
    for m in MUTATIONS:
        if m.mid.startswith("M-") and not re.search(rf"{m.mid}\b", gates.get(m.gate, "")):
            bad.append(F("G-MUTLIST", f"{m.mid} is not listed under {m.gate}", sec="§15"))
    # §15 holds the tool's own rows and nothing else, so no claim hides there (lens 2, A31).
    rest = "\n".join(block.split("\n")[1:])
    for m in sorted(MUTATIONS, key=lambda x: -len(x.mid)):
        if m.mid.startswith("M-"):
            rest = rest.replace(f"{m.mid} {m.what}", " ")
    rest = re.sub(r"\*\*G-[A-Z0-9-]+:\*\*", " ", rest)
    if not re.fullmatch(r"[\s;.-]*", rest):
        left = " ".join(rest.replace(";", " ").split())
        bad.append(F("G-MUTLIST", f"§15 holds text no mutation row is: {left[:60]!r}", sec="§15"))
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
            key = " › ".join(p[1] for p in path)
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
            cells = " | ".join(pin_norm(c) for c in split_row(ln, keep_escapes=True))
            out.append(("spec", region, loc, cells))
        else:
            sents = [x for x in FULL_STOP.split(ln.strip()) if x.strip()]
            shape += f"{line_form(raw)}{len(sents)}"
            for s in sents:
                k += 1
                out.append(("spec", region, f"s{k}", pin_norm(s)))
    out.append(("spec", region, "shape", shape))
    return out


def deck_units(t: Texts) -> list[Unit]:
    data = deck_data(t)
    top = {k: v for k, v in data.items() if k != "strings"} | {"(fields)": list(data)}
    out: list[Unit] = [
        ("deck", "strings#1", "top", json.dumps(top, ensure_ascii=False, sort_keys=True)),
        ("deck", "strings#1", "shape", ",".join(deck_entries(t))),
    ]
    for k, e in deck_entries(t).items():
        out.append(
            ("deck", "strings#1", f"entry {k}", json.dumps(e, ensure_ascii=False, sort_keys=True))
        )
    return out


def all_units(t: Texts) -> list[Unit]:
    return spec_units(t.spec, compute(t)) + deck_units(t)


def write_pins(units: list[Unit]) -> str:
    head = (
        "# E35-D05 pins (every unit of the spec and every deck entry): doc, region (heading path "
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
    parts = region.rsplit("#", 1)[0].split(" › ")
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
                (f"{d} {r[-40:]!r} a sentence changed, moved, added or deleted: {first[:50]!r}",
                 d, r)
            )  # fmt: skip
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
    g_anchor, g_marker, g_figure, g_wordcount, g_cite, g_quote, deck_findings, g_states, g_frames,
    g_bind, g_a11y, g_cmp, g_frozen, g_lift, g_frow, g_grows, g_log, g_consumers, g_walk, g_motion,
    g_repin, g_session, g_ruled, g_delta, g_superseded, g_hooks, g_crow, g_version, g_untouched,
    g_nohandoff, g_unbuilt, g_unmerged, g_perf,
    g_arow, g_close, g_url, g_charset, g_cells, g_budget, g_gitleaks, g_token, g_mutlist,
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


def say(needle: str, extra: str) -> Edit:
    """Insert `extra` right after `needle` in the spec."""
    return sub(needle, needle + extra)


def row_line(prefix: str) -> Callable[[str], str]:
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


def deck_entry(key: str, fn: Callable[[dict[str, object]], None]) -> Edit:
    def go(d: dict[str, object]) -> None:
        strings = d["strings"]
        if isinstance(strings, dict):
            fn(strings[key])

    return deck_top(go)


def deck_raw(old: str, new: str) -> Edit:
    def run(t: Texts) -> Texts:
        if old not in t.deck:
            raise SystemExit(f"self-test: the needle {old[:50]!a} is gone from the deck")
        return replace(t, deck=t.deck.replace(old, new, 1))

    return run


def disk_edit(rel: str, fn: Callable[[str], str]) -> Edit:
    def run(t: Texts) -> Texts:
        d = dict(t.disk)
        d[rel] = fn(d[rel])
        return replace(t, disk=d)

    return run


def set_field(key: str, name: str, value: object) -> Edit:
    def go(e: dict[str, object]) -> None:
        e[name] = value

    return deck_entry(key, go)


def drop_field(key: str, name: str) -> Edit:
    def go(e: dict[str, object]) -> None:
        e.pop(name)

    return deck_entry(key, go)


def drop_entry(key: str) -> Edit:
    def go(d: dict[str, object]) -> None:
        strings = d["strings"]
        if isinstance(strings, dict):
            strings.pop(key)

    return deck_top(go)


def carried_src(d: dict[str, object]) -> None:
    rows = d["carried_by_cite"]
    if isinstance(rows, list) and isinstance(rows[0], dict):
        rows[0]["source"] = "E36DECK:1449"


def event_class(d: dict[str, object]) -> None:
    rows = d["events"]
    if isinstance(rows, list) and isinstance(rows[3], dict):
        rows[3]["class"] = "audit"


def event_trigger(d: dict[str, object]) -> None:
    rows = d["events"]
    if isinstance(rows, list) and isinstance(rows[0], dict):
        rows[0]["trigger"] = "Run simulation pressed (S-08)"


def hand_count(t: Texts) -> Texts:
    return replace(t, spec=re.sub(r"\d+(<!--=COUNT:states-->)", r"99\1", t.spec, count=1))


def unapply_a03(x: str) -> str:
    return x.replace(A_ROWS_14[1][2], A_ROWS_14[1][1], 1)


def no_a11y(x: str) -> str:
    i = x.index("### SCR-086")
    return x[:i] + x[i:].replace("; a11y contract: E35-D04", "", 1)


def q06_due(t: Texts) -> str:
    return (t.values or {})["DATE:E35-Q06"]


RUL = "Every default is taken."
S0 = "cited by frame name."
S3 = "the `Rules` collisions G-12's."
S4 = "a `14` A-row (§13)."
S5 = "every timestamp UTC."
S5F = "The pack is usable meanwhile;"
S6 = "nothing conveys status by motion alone."
S7 = "RT-20 is in `05`."
S7G = "(SCR-117 is outside T Scope);"
S8 = "a T2 control emits no audit and no analytics (D02:138)."
S10 = "None blocks: each has a drawn default."
S11 = "no story-side edit to a frozen string."
S12 = "**Owner walkthrough**"
S13 = "a design PR merges on the owner's approval (README:59)."
BQ34 = "**BQ-34** (the versioning rule) is PROPOSED."
G89 = "D04 G-08 and G-09 are carried, not drawn"
PROBE = "Zq8r4LmT" + "1vXc0p9W"  # built at run time, so no scanner reads it here


def claim_in_15(t: Texts) -> Texts:
    """Lens 2's A31: a claim appended to §15's first row, where G-RULED does not read."""
    head = t.spec.index("## 15. ")
    first = t.spec.index("\n- **G-RULED:**", head)
    end = t.spec.index("\n", first + 1)
    claim = " The owner has approved the frozen strings."
    return replace(t, spec=t.spec[:end] + claim + t.spec[end:])


def brief_row(t: Texts) -> Texts:
    row = row_line("| C-r ")(t.spec)
    extra = "| C-s | the writing brief's base vs the ruling | the ruling's | — |\n"
    return replace(t, spec=t.spec.replace(row, row + extra, 1))


def rekey_copied(d: dict[str, object]) -> None:
    strings = d["strings"]
    if isinstance(strings, dict):
        strings["rules.ir.e35.rt.rt13"] = {
            "string": "Copied", "screen": "SCR-088", "owner": "E35-D04", "status": "PROPOSED",
            "announce": "polite", "source": "D04:345", "rt": "RT-13",
        }  # fmt: skip


M = Mutation
MUTATIONS: tuple[Mutation, ...] = (
    M("M-01", "G-RULED", "delete the RULED paragraph's first sentence", sub(RUL + " ", "")),
    M("M-02", "G-RULED", "write approved for the RULED paragraph's PROPOSED clause",
      sub("are **PROPOSED, owner approval pending (#2701)**", "are **approved**")),
    M("M-03", "G-RULED", "delete the routing table's PROPOSED clause in §7",
      sub("as D04 has them, PROPOSED, owner approval pending (#2701)**", "as D04 has them**")),
    M("M-04", "G-RULED", "write that the routing table is approved as the build contract in §7",
      say(S7, " The routing table is approved as the build contract.")),
    M("M-05", "G-RULED", "write that RT-01..RT-24 are final in §7",
      say(S7, " RT-01..RT-24 are final.")),
    M("M-06", "G-RULED", "write that the routing table was adopted in §7",
      say(S7, " The routing table was adopted.")),
    M("M-07", "G-RULED", "write that the frozen set is approved in §5",
      say(S5F, " the frozen set is approved;")),
    M("M-08", "G-RULED", "write that the freeze is final in §5", say(S5F, " the freeze is final;")),
    M("M-09", "G-RULED", "write that the versioning rule is ruled in §13",
      say(S13, " The versioning rule is ruled.")),
    M("M-10", "G-RULED", "write that the owner approved the pack in §13",
      say(S13, " The owner approved the pack.")),
    M("M-11", "G-RULED", "write that owner sign-off is recorded in §13",
      say(S13, " Owner sign-off is recorded on the ticket.")),
    M("M-12", "G-RULED", "write that this PR also edits the catalogue in §4",
      say(S4, " This PR also edits `15`.")),
    M("M-13", "G-RULED", "write that the catalogue entries land in this PR in §4",
      say(S4, " The catalogue entries land in this PR.")),
    M("M-14", "G-RULED", "write that a separate hand-off file follows the spec in §0",
      say(S0, " A separate hand-off file follows the spec.")),
    M("M-15", "G-RULED", "write that board 05 is redrawn in §0", say(S0, " Board 05 is redrawn.")),
    M("M-16", "G-RULED", "write that a fresh Penpot frame shows the pill in §6",
      say(S6, " A fresh Penpot frame shows the pill.")),
    M("M-17", "G-RULED", "write that the pack coins a string in §5",
      say(S5, " The pack coins a string for the empty state.")),
    M("M-18", "G-RULED", "write that the deck re-keys the shared rows in §5",
      say(S5, " The deck re-keys the shared rows.")),
    M("M-19", "G-RULED", "write that the pack proposes a new payload shape in §3",
      say(S3, " The pack proposes a new payload shape.")),
    M("M-20", "G-RULED", "write that the drift check only warns in §13",
      say(S13, " In practice the drift check only warns.")),
    M("M-21", "G-RULED", "write that a story may extend a component locally in §4",
      say(S4, " A story may extend a component locally.")),
    M("M-22", "G-RULED", "write that G-08 is closed in §7", say(S7G, " G-08 is closed here;")),
    M("M-23", "G-RULED", "write that G-10 is routed in §7", say(S7G, " G-10 is routed to E05;")),
    M("M-24", "G-RULED", "write that A-06 is applied in the catalogue of screens in §7",
      say(S7G, " A-06 is applied in `14`;")),
    M("M-25", "G-RULED", "write that E35-S09 builds SCR-088 whole in §11",
      say(S11, " E35-S09 builds SCR-088 whole.")),
    M("M-26", "G-RULED", "write that a waiver is needed in §13", say(S13, " A waiver is needed.")),
    M("M-27", "G-RULED", "write that the frozen strings can be reworded freely in §5",
      say(S5, " The frozen strings can be reworded freely.")),
    M("M-28", "G-RULED", "write that the annotations sit in an appendix in §3",
      say(S3, " The annotations sit in an appendix.")),
    M("M-29", "G-RULED", "write that PR 1 replaces the rule-editor variant in §4",
      say(S4, " PR 1 replaces the rule editor variant.")),
    M("M-30", "G-RULED", "write that Arm anyway arms in §8",
      say(S8, " Then Arm anyway arms the rule.")),
    M("M-31", "G-RULED", "write that SCR-085 has a typed field in §8",
      say(S8, " SCR-085 has a typed confirmation field.")),
    M("M-32", "G-RULED", "write that the lane edits the issue bodies in §11",
      say(S11, " The lane edits the issue bodies.")),
    M("M-33", "G-RULED", "write that an agent owns a row in §10",
      say(S10, " An agent owns the D03-Q1 row.")),
    M("M-34", "G-RULED", "turn the no-catalogue-edit clause of §4 into its opposite",
      sub("**No `15` edit in this PR** (G-UNTOUCHED)", "**The `15` edit** (G-UNTOUCHED)")),
    M("M-35", "G-RULED", "delete the no-invented-string clause of §5",
      sub("**No string is invented** (BQ-15)", "(BQ-15)")),
    M("M-36", "G-RULED", "delete the no-revision clause of the G ledger",
      sub(" (no revision of D02 / D03 is coming)", "")),
    M("M-37", "G-RULED", "delete the never-invented clause of §2",
      sub("**Missing treatments are G-rows, never invented** (BQ-10)",
          "**Missing treatments** (BQ-10)")),
    M("M-38", "G-RULED", "delete the carried-not-drawn clause of §0",
      sub("; D04 G-08 and G-09 are carried, not drawn", "")),
    M("M-39", "G-RULED", "delete the C-row routing clause of §11",
      sub("; the C-row routes to the orchestrator (C-i)", " (C-i)")),
    M("M-40", "G-RULED", "delete the met-with-room clause of §13",
      sub(", which reads as met with room", "")),
    M("M-41", "G-RULED", "delete the A-05 fold clause of §13", sub(" (D04's A-05 folded in)", "")),
    M("M-42", "G-RULED", "delete the narrow-the-set clause of §5",
      sub("; the owner can narrow the set to CA-1 / CA-8 without a redraw", "")),
    M("M-43", "G-RULED", "drop the backend-role pass's name in §12",
      sub("(d) **A backend-role pass**", "(d) **A pass**")),
    M("M-44", "G-RULED", "write that the owner has given approval in §13",
      say(S13, " The owner has given approval to the pack.")),
    M("M-45", "G-RULED", "quote the one word of an owner claim in §13",
      say(S13, ' The owner "approved" it.')),
    M("M-46", "G-RULED", "write that no reviewer doubts the routing table is approved in §7",
      say(S7, " No reviewer doubts the routing table is approved.")),
    M("M-47", "G-SESSION", "write that the walkthrough session was held in §12",
      sub(S12, "The walkthrough session was held with the engineers. " + S12)),
    M("M-48", "G-SESSION", "write that engineers met and walked through the pack in §12",
      sub(S12, "Engineers met and walked through the pack. " + S12)),
    M("M-49", "G-SESSION", "write that the backend lead joined in §12",
      sub(S12, "The backend lead joined the review. " + S12)),
    M("M-50", "G-DECK", "change one character of CA-1 in the deck",
      deck_entry("rules.sim.ca1", lambda e: e.__setitem__("string", str(e["string"])[:-1] + ","))),
    M("M-51", "G-DECK", "write TBD as the fire history's error string",
      set_field("rules.history.new34", "string", "TBD")),
    M("M-52", "G-DECK", "put an exchange code into the failed result word",
      set_field("rules.history.new27.2", "string", "✗ Failed — {why} (retCode 110001)")),
    M("M-53", "G-DECK", "drop the frozen mark from CA-8", drop_field("rules.arm.ca8", "frozen")),
    M("M-54", "G-DECK", "mark CA-9 PROPOSED against its source row",
      set_field("rules.arm.ca9", "status", "PROPOSED")),
    M("M-55", "G-DECK", "make the resolver's refusal polite against RT-04",
      set_field("rules.conflict.new16", "announce", "polite")),
    M("M-56", "G-DECK", "delete an overlapping-flatten sentence from the deck",
      drop_entry("rules.conflict.new20.2")),
    M("M-57", "G-DECK", "add a top-level note field to the deck",
      deck_top(lambda d: d.__setitem__("note", "The owner approved the pack."))),
    M("M-58", "G-DECK", "write v2 as the deck's version",
      deck_top(lambda d: d.__setitem__("version", "v2"))),
    M("M-59", "G-DECK", "repeat a deck key ahead of its entry",
      deck_raw('"strings": {', '"strings": {\n    "rules.sim.ca1": {"string": "x"},')),
    M("M-60", "G-DECK", "empty the coverage line's params",
      set_field("rules.sim.ca3", "params", [])),
    M("M-61", "G-DECK", "reword the deck's header",
      deck_top(lambda d: d.__setitem__("header", "Copy may change."))),
    M("M-62", "G-DECK", "put CA-1 first in the caveat's order",
      set_field("rules.sim.ca1", "order", 1)),
    M("M-63", "G-DECK", "point a carried row one line off", deck_top(carried_src)),
    M("M-64", "G-DECK", "give an event a class outside the set", deck_top(event_class)),
    M("M-65", "G-STATES", "name a key the deck lacks in S-05",
      cell("| S-05 ", 5, "`rules.sim.new30.33`")),
    M("M-66", "G-STATES", "cite board D02 11 in S-04", cell("| S-04 ", 4, "D02 11")),
    M("M-67", "G-STATES", "drop the stale-run row from S-07's source",
      cell("| S-07 ", 3, "D02:169–170")),
    M("M-68", "G-STATES", "rename S-01's frame", cell("| S-01 ", 2, "ready")),
    M("M-69", "G-FRAMES", "drop board 09 from D02's list in the frame index",
      sub("SCR-085 03, 04, 05, 08, 09;", "SCR-085 03, 04, 05, 08;")),
    M("M-70", "G-BIND", "write an unknown status on a redline row",
      cell("| SCR-087 | the expanded row", 4, "maybe served")),
    M("M-71", "G-BIND", "cite the line under simulateRule", sub("`simulateRule` (`22`:8025)",
                                                            "`simulateRule` (`22`:8026)")),
    M("M-72", "G-BIND", "name a G-row no parent has",
      sub("G-rows D02-G2, D02-G3", "G-rows D02-G2, D02-G42")),
    M("M-73", "G-A11Y", "drop RT-13 from SCR-088's pinned line", sub("RT-08, RT-13;", "RT-08;")),
    M("M-74", "G-A11Y", "add N-66 to SCR-089's pinned line",
      sub("N-41..N-44 (", "N-41..N-44, N-66 (")),
    M("M-75", "G-A11Y", "cite SCR-085's focus row for SCR-084",
      sub("focus D04:179 (Run simulation first)", "focus D04:180 (Run simulation first)")),
    M("M-76", "G-CMP", "cite the line under CMP-156's heading",
      sub("| `15`:1797 ", "| `15`:1799 ")),
    M("M-77", "G-CMP", "drop D03-C10 from CMP-156's row",
      sub(", D03-C9, D03-C10, D04 A-04", ", D03-C9, D04 A-04")),
    M("M-78", "G-CMP", "drop F-06's fold from PR 1's paragraph",
      sub("; F-06 as D04 reads it)", ")")),
    M("M-79", "G-FROZEN", "delete the FZ-04 row", drop_line("| FZ-04 ")),
    M("M-80", "G-FROZEN", "cite CA-2's line for FZ-01", cell("| FZ-01 ", 4, "D02:303")),
    M("M-81", "G-LIFT", "shrink §12's lifted span by one line",
      sub("§12 (D04:450–469)", "§12 (D04:450–468)")),
    M("M-82", "G-FROW", "land F-08 in PR 1", cell("| F-08 ", 3, "PR 1")),
    M("M-83", "G-FROW", "write approved as F-06's close state", cell("| F-06 ", 5, "approved")),
    M("M-84", "G-FROW", "delete the F-11 row", drop_line("| F-11 ")),
    M("M-85", "G-GROWS", "route G-02", cell("| G-02 ", 2, "routed to E35-D03's spec")),
    M("M-86", "G-GROWS", "cite D04:817 for G-13 and G-14",
      sub("the override reason's count (D04:818); the T2 label on a selected row (D04:819)",
          "the override reason's count (D04:817); the T2 label on a selected row (D04:819)")),
    M("M-87", "G-LOG", "empty Q-01's owner lane", cell("| D04 Q-01 ", 3, "—")),
    M("M-88", "G-LOG", "delete the D03-Q1 row", drop_line("| D03-Q1 ")),
    M("M-89", "G-LOG", "give Q-01 E35-Q06's due date",
      lambda t: cell("| D04 Q-01 ", 5, f"{q06_due(t)}<!--=DATE:E35-Q06-->")(t)),
    M("M-90", "G-LOG", "write TBD as D03-Q1's default", cell("| D03-Q1 ", 2, "TBD (D03:556)")),
    M("M-91", "G-CONSUMERS", "drop E35-X03's issue number from §11",
      sub("E35-T06 (#1050); E35-X03 (#1115)", "E35-T06 (#1050); E35-X03")),
    M("M-92", "G-CONSUMERS", "drop the keyboard-only scenario's trace",
      sub("; Keyboard-only arming: §3 SCR-085", "")),
    M("M-93", "G-CONSUMERS", "drop F-12 from E35-S09's row",
      sub("F-01, F-06, F-08..F-10, F-12, F-13", "F-01, F-06, F-08..F-10, F-13")),
    M("M-94", "G-CONSUMERS", "drop #874 from the publication list",
      sub("X03, #947 and #874.", "X03 and #947.")),
    M("M-95", "G-WALK", "add an eleventh owner walkthrough item",
      sub("W-5 §11, BQ-29's build split.", "W-5 §11, BQ-29's build split. W-6 §2. W-7 §3. W-8 §4. "
          "W-9 §5. W-10 §6. W-11 §7.")),
    M("M-96", "G-WALK", "write 24 found for E35-S08",
      cell("| 2026-10-28 | story: E35-S08 ", 3, "24")),
    M("M-97", "G-WALK", "untick the DoD line after the fresh reader's record",
      sub("- [x] **DoD (BQ-33", "- [ ] **DoD (BQ-33")),
    M("M-98", "G-WALK", "point a carry at G-P0", sub("CMP-155 → §4", "CMP-155 → G-P0")),
    M("M-99", "G-WALK", "date E35-S09's dry-run row a day early",
      cell("| 2026-10-28 | story: E35-S09 ", 0, "2026-10-27")),
    M("M-100", "G-VERSION", "simulate a merged change to D04 at origin/main",
      lambda t: replace(t, head_commits={**t.head_commits, CITE_FILES["D04"]: "0" * 40})),
    M("M-101", "G-VERSION", "simulate an unresolvable origin/main",
      lambda t: replace(t, head_ok=False)),
    M("M-102", "G-VERSION", "pin E36P at a wrong sha in the version line",
      sub("E36P and E36DECK at `c861679e14`", "E36P and E36DECK at `c861679e15`")),
    M("M-103", "G-UNTOUCHED", "append a line to the catalogue in the working tree",
      disk_edit(PLAN["15"], lambda x: x + "drift\n")),
    M("M-104", "G-UNTOUCHED", "drop the a11y fold from SCR-086's pointer line",
      disk_edit(PLAN14, no_a11y)),
    M("M-105", "G-UNTOUCHED", "simulate a failed merge-base", lambda t: replace(t, mb="")),
    M("M-106", "G-UNTOUCHED", "simulate a committed change outside the pack",
      lambda t: replace(t, stray=stray_of(f"docs/plan/20-architecture.md\n{PLAN14}", ""))),
    M("M-107", "G-UNTOUCHED", "leave A-03 unapplied in the working tree",
      disk_edit(PLAN14, unapply_a03)),
    M("M-108", "G-NOHANDOFF", "add a hand-off file beside the spec",
      lambda t: replace(t, handoffs=("docs/design/E35/E35-D05-handoff.md",))),
    M("M-109", "G-UNBUILT", "delete the no-rules-slice clause of §0",
      sub(" and no rules slice", "")),
    M("M-110", "G-UNMERGED", "cite the sister pack's PR number in §6", say(S6, " As #4755 did.")),
    M("M-111", "G-CITE", "move a D02 cite past the end of D02",
      sub("| D02:90–112", "| D02:90–9999")),
    M("M-112", "G-QUOTE", "quote copy no merged text holds in §8",
      say(S8, ' The button reads "Arm the rule on DEMO now" (D02:225).')),
    M("M-113", "G-QUOTE", "misspell an event name in §9",
      sub("`rule.armed` (`14`:1953)", "`rule.armd` (`14`:1953)")),
    M("M-114", "G-ANCHOR", "hand-edit the S count's value", hand_count),
    M("M-115", "G-FIGURE", "type a board count by hand in §2",
      sub("merged boards; SCR-088", "merged boards of 18 boards; SCR-088")),
    M("M-116", "G-WORDCOUNT", "write a board count as a word in §2",
      sub("merged boards; SCR-088", "merged boards, eighteen boards in all; SCR-088")),
    M("M-117", "G-MARKER", "add a comment that is not an anchor",
      sub("## 6. Motion", "<!-- note -->\n## 6. Motion")),
    M("M-118", "G-CLOSE", "write a closing keyword before the ticket number in §13",
      say(S13, " This closes #940.")),
    M("M-119", "G-URL", "write a local path in §6", say(S6, " See /ho" + "me/x/wt.")),
    M("M-120", "G-CHARSET", "write a trailing space after §0's last sentence",
      say("PR 1 is merged at the base and cited there (C-r).", " ")),
    M("M-121", "G-CHARSET", "write a fullwidth letter inside a short quote in §8",
      sub('"Arm on DEMO"', '"Arm on ＤEMO"')),
    M("M-122", "G-CELLS", "merge two cells of C-a", merge_cells("| C-a ")),
    M("M-123", "G-BUDGET", "append lines past the budget",
      lambda t: replace(t, spec=t.spec + "\n.\n" * 20)),
    M("M-124", "G-GITLEAKS", "write a secret-shaped value in §6",
      say(S6, " `api_key: " + PROBE + "`.")),
    M("M-125", "G-GITLEAKS", "write a recovery-code-shaped value in §6",
      say(S6, " recovery_code=" + "probe" + "-value.")),
    M("M-126", "G-TOKEN", "name an unshipped token in §3",
      sub("`color.status.warning.subtle` rows", "`color.status.warning.subtlee` rows")),
    M("M-127", "G-MUTLIST", "rename M-01 in §15", sub("M-01 ", "M-0X ", 1)),
    M("M-128", "G-PERF", "cite the analytics line for SCR-084's budget",
      sub("`14`:1930", "`14`:1931")),
    M("M-129", "G-AROW", "alter PA-1's Old clause",
      sub("→ job id; progress", "→ a job id; progress")),
    M("M-130", "G-AROW", "cite a G-row as PA-1's source", cell("| PA-1 ", 4, "D02:503")),
    M("M-131", "G-MOTION", "drop T-09 from §6's mapping",
      sub("; the expanded row T-09 and the loading skeleton T-14.",
          "; the loading skeleton T-14.")),
    M("M-132", "G-REPIN", "drop the re-pin of `15`:1800 from §0",
      sub("applied at `15`:1804 / :1800 by PR 1", "applied at `15`:1804 by PR 1")),
    M("M-133", "G-DECK", "point an event's trigger at another screen's row",
      deck_top(event_trigger)),
    M("M-134", "G-LOG", "drop G-P4 from the log", sub("G-P1..G-P5", "G-P1..G-P3, G-P5")),
    M("M-135", "G-RULED", "write that the owner signed the pack off in §13",
      say(S13, " The owner signed the pack off.")),
    M("M-136", "G-RULED", "write that the routing table now binds the stories in §7",
      say(S7, " The routing table now binds the stories.")),
    M("M-137", "G-RULED", "write that a new frame is drawn in Penpot in §6",
      say(S6, " A new frame is drawn in Penpot.")),
    M("M-138", "G-RULED", "write that the pack invented strings in §5",
      say(S5, " We invented the strings.")),
    M("M-139", "G-RULED", "write that rules may loosen a stop in §8",
      say(S8, " Rules may loosen a stop.")),
    M("M-140", "G-RULED", "write that BQ-16 is ruled in §13", say(S13, " BQ-16 is ruled.")),
    M("M-141", "G-RULED", "write that no owner approval is pending in §13",
      say(S13, " No owner approval is pending.")),
    M("M-142", "G-RULED", "write that a payload shape is proposed for a gap in §3",
      say(S3, " A payload shape is proposed for the gap.")),
    M("M-143", "G-RULED", "write that the pack edits the catalogue in §4",
      say(S4, " The pack edits the catalogue too.")),
    M("M-144", "G-RULED",
      "write that the owner has since settled BQ-16 and BQ-22 in the RULED paragraph",
      say("the orchestrator posts the pointer on #2701 at the pack's merge;",
          " the owner has since settled BQ-16 and BQ-22;")),
    M("M-145", "G-RULED", "write that the frozen strings are locked in by the owner in §5",
      say("routed to E35-X03 (#1115)", ". The frozen strings are locked in by the owner")),
    M("M-146", "G-RULED", "write that the build treats RT-01..RT-24 as mandatory and settled in §7",
      sub("**G-08, G-09, G-12 and G-15 are routed**", "The build must treat RT-01..RT-24 as"
          " mandatory and settled. **G-08, G-09, G-12 and G-15 are routed**")),
    M("M-147", "G-RULED", "write that BQ-34 now stands as decided in the RULED paragraph",
      say(BQ34, " BQ-34 now stands as decided.")),
    M("M-148", "G-RULED", "write that a companion hand-off note ships beside the spec in §0",
      sub("**One spec plus the deck; no `-handoff.md`** (BQ-4):", "**One spec plus the deck; no"
          " `-handoff.md`** (BQ-4); a short companion hand-off note ships alongside the spec:")),
    M("M-149", "G-RULED", "write that G-08 and G-09 are drawn here after all in §0",
      say(G89, "; G-08 and G-09 are drawn here after all")),
    M("M-150", "G-RULED", "write that the designer fills a missing treatment in, in §2",
      say("**Missing treatments are G-rows, never invented** (BQ-10)",
          "; where a treatment is missing the designer fills it in")),
    M("M-151", "G-RULED", "write that the pack amends the WS protocol in §3",
      say("S06 #865 or S07 #866).", " The pack amends `23` with a run topic for the simulation.")),
    M("M-152", "G-RULED", "write that the catalogue is updated alongside in §4",
      say("**No `15` edit in this PR** (G-UNTOUCHED)", "; `15` is updated alongside, for CMP-156")),
    M("M-153", "G-RULED", "write that the variants supersede #947's editor contract in §4",
      say("beside #947's editor contract, never replacing",
          "; in practice they supersede #947's editor contract")),
    M("M-154", "G-RULED", "write that strings are newly written for the gaps in §5",
      say("**No string is invented** (BQ-15)",
          "; a handful of strings are newly written for the gaps")),
    M("M-155", "G-RULED", "write that shared rows get fresh keys in this deck in §5",
      say("FS-4 and FS-7 (E36P:301, :304)", ". Shared rows get fresh keys in this deck")),
    M("M-156", "G-RULED", "write that a rewording is a routine copy edit in §5",
      say("routed to E35-X03 (#1115)", "; in practice a rewording is a routine copy edit")),
    M("M-157", "G-RULED", "write that G-12 is resolved in the pack after all in §7",
      say("**G-08, G-09, G-12 and G-15 are routed**", "; G-12 is resolved in the pack after all")),
    M("M-158", "G-RULED", "write that A-06 is written into SCR-117 by this PR in §7",
      say("**A-06 is recorded and routed to E11**", "; A-06 is written into SCR-117 by this PR")),
    M("M-159", "G-RULED", "write that Arm anyway then proceeds to arm the rule in §8",
      say('"Arm anyway" returns to SCR-085 and never arms',
          "; Arm anyway then proceeds to arm the rule")),
    M("M-160", "G-RULED", "write that an agent holds the lane for G-12 in §10",
      say("Owner lanes, never agents", "; an agent holds the lane for G-12")),
    M("M-161", "G-RULED", "write that follow-up issues are opened for every row in §10",
      say("nothing is filed", "; follow-up issues are opened for every row")),
    M("M-162", "G-RULED", "write that E35-S09 also builds the SCR-088 base screen in §11",
      say("E35-S09 builds E35-D03's deltas onto them",
          "; E35-S09 also builds the SCR-088 base screen")),
    M("M-163", "G-RULED", "write that the lane rewrites the issue bodies in §11",
      say("no body edit by the lane", "; the lane rewrites the issue bodies")),
    M("M-164", "G-SESSION",
      "write that the owner and the backend lead reviewed it together on a call in §12",
      say("**No session took place and none is claimed**",
          "; the owner and the backend lead reviewed it together on a call")),
    M("M-165", "G-RULED", "write that the drift check merely flags it as advisory in §13",
      say("which `--check` FAILs at `origin/main`",
          " (in practice it merely flags it as advisory)")),
    M("M-166", "G-RULED", "write that this PR merges once the orchestrator approves in §13",
      say("a design PR merges on the owner's approval", "; this one merges once the orchestrator"
          " approves")),
    M("M-167", "G-RULED", "write that the owner's go-ahead is in hand in the RULED paragraph",
      say("the orchestrator posts the pointer on #2701 at the pack's merge",
          "; the owner's go-ahead on #2701 is in hand")),
    M("M-168", "G-RULED", "write a double negation that the frozen set is approved in the RULED"
      " paragraph", say(BQ34, " It is not true that the frozen set is not approved.")),
    M("M-169", "G-RULED", "write an owner approval split by a colon in the RULED paragraph",
      say(BQ34, " Owner approval: given.")),
    M("M-170", "G-CHARSET", "write an owner claim with a Cyrillic letter in the RULED paragraph",
      say(BQ34, " The owner has \u0430pproved BQ-16.")),
    M("M-171", "G-RULED", "write an owner claim as a heading in the RULED section",
      sub("## 0. Status and evidence", "### The owner approved BQ-16 and BQ-22\n\n## 0. Status and"
          " evidence")),
    M("M-172", "G-MUTLIST", "append an owner claim to the first row of §15", claim_in_15),
    M("M-173", "G-RULED", "write that the pack adds Penpot boards for G-08 in §0",
      say(G89 + ".", " The pack adds Penpot boards for G-08.")),
    M("M-174", "G-DELTA", "quote SCR-086's priority words as E35-S09's in §11",
      sub("as stored (D03:534),", 'as stored (D03:534); its "drag list or numeric priority" →'
          " Move up / Move down (D03:83),")),
    M("M-175", "G-DELTA", "cite D02:75 for the read-only line in §11",
      sub("until D02-G5 (D02:76)", "until D02-G5 (D02:75)")),
    M("M-176", "G-SUPERSEDED", "bind SCR-086's band to the sunken token again",
      sub("`color.surface.app` (F-06; D03's `sunken` superseded); `color.status.warning",
          "`color.surface.sunken` (F-06); `color.status.warning")),
    M("M-177", "G-SUPERSEDED", "drop the app surface from SCR-088's row",
      sub("`color.text.secondary` on `color.surface.app` (F-06; D03's `sunken` superseded)",
          "`color.text.secondary`")),
    M("M-178", "G-CROW", "write the writing brief back as a C-row", brief_row),
    M("M-179", "G-CROW", "put the event row's text into C-n",
      cell("| C-n ", 1, "`14`'s event names vs `24`")),
    M("M-180", "G-WALK", "write dry run pending in AC1",
      sub("| text done; dry run done (a fresh reader)", "| text done; dry run pending a fresh reader")),
    M("M-181", "G-GROWS", "drop the heuristic mark from G-11",
      sub("nothing truncates (the pack's PROPOSED wording, heuristic)", "nothing truncates")),
    M("M-182", "G-GROWS", "drop E35-S08 from G-13's consumers",
      sub("E35-S08 (G-13); E35-S09 (G-14)", "E35-S09 (G-13, G-14)")),
    M("M-183", "G-LOG", "give G-P1 to E35-D02's spec in the log",
      sub("this pack (G-P1, G-P2, G-P10);", "E35-D02's and E35-D03's specs (G-P1, G-P2, G-P10);")),
    M("M-184", "G-PERF", "write verbatim in §9's budget header",
      sub("| Budget (from its line)", "| Budget (verbatim at its line)")),
    M("M-185", "G-FROW", "put E35-S09 on F-14's row", cell("| F-14 ", 4, "E35-S08, E35-S09")),
    M("M-186", "G-FIGURE", "type a sprint count by hand in §13",
      say(S13, " The slip is 3 sprints.")),
    M("M-187", "G-CONSUMERS", "trace the suppressed firing to S-22 only",
      sub("visible too: S-24, S-26 (S-22 for a precedence skip)", "visible too: S-22")),
    M("M-188", "G-CONSUMERS", "drop S-03 from the coverage scenario",
      sub("coverage honestly: S-03 (CA-1, FZ-01), S-04", "coverage honestly: S-04")),
    M("M-189", "G-CONSUMERS", "drop E36-S03 from the round-trip scenario",
      sub("S-28, the hash, version and compiler stamps on E36-S03 (#1059)", "S-28")),
    M("M-190", "G-DECK", "re-key #947's Copied string in the deck", deck_top(rekey_copied)),
    M("M-191", "G-STATES", "set the audit notice's screen to SCR-086",
      set_field("rbac.permission.see_audit", "screen", "SCR-086")),
    M("M-192", "G-CMP", "name a story CMP-159's line lacks",
      sub("NoConflict (`15`:1838)", "NoConflict, ResolverError (`15`:1838)")),
    M("M-193", "G-CMP", "drop G-P5 from CMP-233's Storybook cell",
      sub("none from PR 1 (`15`:2756): G-P5", "none from PR 1 (`15`:2756)")),
    M("M-194", "G-HOOKS", "drop the PROPOSED mark from the hooks paragraph",
      sub("**Test hooks (PROPOSED; T is silent;", "**Test hooks (T is silent;")),
    M("M-195", "G-HOOKS", "drop G-P8 from the hooks paragraph",
      sub("masked tokens G-P8 and", "masked tokens and")),
    M("M-196", "G-RULED", "write that A-05 is applied in the catalogue of screens in §7",
      say(S7G, " A-05 is applied in `14`;")),
    M("M-197", "G-RULED", "write that the deck is in the sister shape in §5",
      say(S5, " The deck is in the sister shape.")),
    M("M-198", "G-HOOKS", "name the pill as a role-less element's hook",
      sub("the pill has its role (N-31)", "the pill G-P5")),
    # pin probes (no measured or lexicon gate reads these units)
    M("P-1", "G-RULED-PIN", "reword a §1 sentence",
      sub("#947's boundary and shared rows", "#947's boundary and its shared rows")),
    M("P-2", "G-RULED-PIN", "change C-b's reading", cell("| C-b ", 2, "variants replace nothing")),
    M("P-3", "G-RULED-PIN", "rename §9's heading",
      sub("## 9. Performance and events (BQ-26, BQ-27)", "## 9. Performance and events")),
    M("P-4", "G-RULED-PIN", "turn §6's paragraph into a bullet",
      sub("AC3)\n\n**D04 §12", "AC3)\n\n- **D04 §12")),
    M("P-5", "G-RULED-PIN", "widen a deck entry's screens",
      set_field("rules.sim.new2", "screen", "SCR-084, SCR-085")),
)  # fmt: skip


def texts_digest(t: Texts) -> str:
    h = hashlib.sha256()
    for part in (t.spec, t.deck, *sorted(t.disk.items()), t.stray, t.handoffs,
                 sorted(t.head_commits.items()), t.head_ok, t.mb):  # fmt: skip
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
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
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
        changed = [m for m, _d, _r in pin_problems(read_pins() or (), units)]
        (ROOT / PIN_REL).write_text(write_pins(units), encoding="utf-8", newline="\n")
        for m in changed:  # every reworded unit, so a delta's pin diff is read, never waved through
            print(f"  repinned: {m[:150]}".encode("ascii", "replace").decode())
        print(f"--repin-ruled: {len(units)} units pinned; {len(changed)} changed")
        return 0
    if a.check or a.json or a.fill:
        fails, notes, warns, n = audit(t)
        pins = read_pins()
        head = git_out("rev-parse", "--short=10", HEAD).strip() or "unresolved"
        tail = (
            f"check: {n} cites and deck strings read at {BASE} ({HEAD} {head}); "
            f"{len(pins or ())} units pinned; {len(fails)} FAIL / {len(notes)} NOTE / "
            f"{len(warns)} WARN"
        )
        if a.json:
            out = {"base": BASE, "values": compute(t), "fails": fails, "notes": notes,
                   "warns": warns, "tail": tail}  # fmt: skip
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
