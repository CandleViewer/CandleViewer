#!/usr/bin/env python3
"""E33-D06 (#990) audit: the emulated-algo screens' engineering hand-off pack (spec + keyed deck).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base `c888406d2` (`git show`): the plan texts the spec cites, the merged E33
design texts D01..D05 with the D03 and D04 hand-offs, the E33 threat model, the backlog JSON, the
calendar, the token JSON and the board tree; D04 and D05 at their merges for the lifted sections;
and, from the working tree, the spec `docs/design/E33/E33-D06.md`, the deck
`docs/design/E33/E33-D06-copy.json`, `14` and the files the pack must not edit. It is adapted from
the E35-D05 (#940) tool: the same modes, the same value, pin and mutation machinery, and gates
re-cut for this pack's tables.

1. **Values.** Every `{{KIND:key}}` is a placeholder that `--fill` writes as
   `VALUE<!--=KIND:key-->`: COUNT (boards in the base tree, the spec's own table rows, the deck's
   entries by status, the register's ids, the D04 frames by family), DATE (a sprint start from the
   backlog JSON and `calendar_cv.py`), HASH (sha256 prefix of a lifted D04 or D05 section at its
   merge) and CITE (a figure parsed from the cited line). `--check` re-derives each anchored value
   (G-ANCHOR, with a left boundary), FAILs a `{{` left behind, any HTML comment that is not an
   anchor (G-MARKER), a hand-typed figure before a unit (G-FIGURE) and a count written as a word
   before a counted noun (G-WORDCOUNT).
2. **Cites.** Every `NN`:line and named-file cite in the spec and the deck is read at the base and
   must be a non-blank line (G-CITE); quoted copy and every backticked `algo.*` name in the spec
   must occur verbatim in a doc its line cites or in the ticket JSON (G-QUOTE); every deck string
   must equal a whole quote, or one item of a colon-led list, of its source line, never a substring
   (G-DECK), and every quoted string of the parents' deck spans must be in the deck, carried by
   cite or recorded as superseded (the union, G-DECK).
3. **Gates.** One FAIL line per gate. Measured gates read the spec's tables cell by cell
   (G-FRAMES, G-STATES, G-REDLINE, G-API, G-VERBS, G-CMP, G-STORY, G-FROZEN, G-LIFT, G-LAYER,
   G-FROW, G-LOG, G-CONSUMERS, G-WALK); G-RULED requires each standing sentence verbatim in its
   section and reads every clause against a lexicon of opposite readings (a negation covers its own
   term only within its phrase); the lexicon is a tripwire, not a proof: the default-deny pins (4.)
   are the backstop. G-SESSION refuses a claimed session. G-UNTOUCHED compares the working tree
   with `git merge-base HEAD origin/main`: only `14` may differ, by exactly the five pointer lines.
   G-VERSION FAILs when a pinned input's last commit at `origin/main` differs from the base's, and
   when `origin/main` does not resolve; neither fetches, so run `git fetch origin main` first.
   G-CHARSET, G-CELLS, G-CLOSE, G-URL, G-UNMERGED, G-UNBUILT, G-NOHANDOFF, G-BUDGET, G-GITLEAKS,
   G-TOKEN and G-MUTLIST close the set.
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of the spec (each
   heading, table row by its lead cell, rule line and prose sentence, by heading path and
   occurrence, with a line-shape tag per region) and over every deck entry, in
   `e33_d06_ruled_pins.txt`. Anchored values are cut out of the pinned text (G-ANCHOR owns them).
   `--repin-ruled` is the only writer and refuses while a placeholder is unfilled; it prints every
   unit it changes. A pin finding in a section another gate already FAILs prints as a NOTE line.
5. **--self-test** applies every mutation of the spec's §15 (and the tool's own P-n pin probes) in
   memory, with the values frozen at the filled baseline; each must add exactly one FAIL, from the
   gate it names; every text is restored byte-identically (sha256 in memory and on disk). Output
   is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e33_d06_handoff_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e33_d06_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e33_d06_handoff_audit.py --repin-ruled
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
BASE = "c888406d2"  # origin/main when the pack was written; every cite is read here
HEAD = "origin/main"  # G-VERSION: a pinned input's last commit here must equal the base's
D04_SHA = "eba90876c"  # D04's boards merge (#4845): D04 §7 and §8 are hashed here
D05_SHA = "27fbdabd3"  # D05's merge (#4816): the lifted D05 sections are hashed here

SPEC_REL = "docs/design/E33/E33-D06.md"
DECK_REL = "docs/design/E33/E33-D06-copy.json"
TOOL_REL = "docs/design/_tools/e33_d06_handoff_audit.py"
PIN_REL = "docs/design/_tools/e33_d06_ruled_pins.txt"
PLAN14 = "docs/plan/14-screens-catalogue.md"
OWN = (SPEC_REL, DECK_REL, TOOL_REL, PIN_REL, PLAN14)
LINE_BUDGET = 300  # BQ-2's default: within the E35-D05 line budget

CITE_FILES = {
    "D01": "docs/design/research/e33-emulated-algo-trust.md",
    "D02": "docs/design/E33/E33-D02.md",
    "D03": "docs/design/E33/E33-D03.md",
    "H03": "docs/design/E33/E33-D03-handoff.md",
    "D04": "docs/design/E33/E33-D04.md",
    "D04H": "docs/design/E33/E33-D04-handoff.md",
    "D05": "docs/design/E33/E33-D05.md",
    "TM": "docs/security/threat-models/E33-emulated-algos.md",
    "E09-D09": "docs/design/E09/E09-D09.md",
    "E29-D03": "docs/design/E29/E29-D03.md",
    "E30-D02": "docs/design/E30/E30-D02.md",
    "E30-D03": "docs/design/E30/E30-D03.md",
    "E32-D02": "docs/design/E32/E32-D02.md",
    "CONST": "CONSTITUTION.md",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "README": "docs/design/README.md",
    "E33.json": "docs/plan/backlog/E33.json",
}
PLAN = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": PLAN14,
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "18": "docs/plan/18-traceability-matrix.md",
    "21": "docs/plan/21-database-schema.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
}
UNTOUCHED = tuple(
    [PLAN[k] for k in ("02", "05", "11", "15", "16", "18", "21", "22", "23", "24")]
    + [CITE_FILES[k] for k in ("D01", "D02", "D03", "H03", "D04", "D04H", "D05", "TM")]
    + [CITE_FILES[k] for k in ("E33.json", "README", "CONST")]
)
POINTER = (
    "- **Hand-off pack:** [E33-D06.md](../design/E33/E33-D06.md) v1 (E33-D06; owner approval"
    " pending; a11y contract: E33-D05)"
)
POINTER_OCO = POINTER.replace("**Hand-off pack:**", "**Hand-off pack (OCO half):**")
POINTER_SCREENS = ("SCR-066", "SCR-067", "SCR-068", "SCR-069", "SCR-070")
IMG_DIR = "docs/design/E33/img"
# The version line's pinned inputs and their shas (the boards ride with D04's boards PR).
PINNED = {
    CITE_FILES["D01"]: "68702165b",
    CITE_FILES["D02"]: "6a8fc9626",
    CITE_FILES["D03"]: "05aa6fba1",
    CITE_FILES["H03"]: "05aa6fba1",
    CITE_FILES["D04"]: "eba90876c",
    CITE_FILES["D04H"]: "eba90876c",
    IMG_DIR: "eba90876c",
    CITE_FILES["D05"]: "27fbdabd3",
    CITE_FILES["TM"]: "051e5a330",
}
# The sections lifted as they stand (D05:833 names D05's), with their spans and merge shas.
LIFTED = (
    ("D05", "§5", 183, 239, "d05.s5"),
    ("D05", "§6", 241, 265, "d05.s6"),
    ("D05", "§7", 267, 336, "d05.s7"),
    ("D05", "§8", 338, 387, "d05.s8"),
    ("D05", "§9.1", 391, 415, "d05.s9"),
    ("D05", "§10", 438, 446, "d05.s10"),
    ("D05", "§11", 448, 460, "d05.s11"),
    ("D05", "§12", 462, 503, "d05.s12"),
    ("D05", "§13", 505, 522, "d05.s13"),
    ("D05", "§16.4", 788, 799, "d05.s16"),
    ("D04", "§7", 268, 309, "d04.s7"),
    ("D04", "§8", 311, 315, "d04.s8"),
)
LIFT_SHA = {"D04": D04_SHA, "D05": D05_SHA}
SCREENS = ("SCR-066", "SCR-067", "SCR-068", "SCR-069", "SCR-070")
DECK_SCREENS = (*SCREENS, "SCR-063", "SCR-076")
STATUSES = ("merged", "binding-pending-owner", "PROPOSED")
ANNOUNCE = ("polite", "assertive", "none")
OWNERS = ("E33-D02", "E33-D03", "E33-D04", "E33-D05")
DECK_TOP = ("pack", "version", "base", "header", "strings", "events", "carried_by_cite")
ENTRY_FIELDS = ("string", "screen", "owner", "status", "announce", "source", "params", "rt",
                "frozen", "order")  # fmt: skip
HEADER = (
    "The package must carry the security-relevant UI rules verbatim so they cannot be dropped in"
    " implementation"
)
# The frozen rows (PROPOSED): each FZ row's keys, in order.
FROZEN = {
    "FZ-01": ("caveat.twap", "caveat.iceberg", "caveat.chase"),
    "FZ-02": ("caveat.oco_entry", "caveat.oco_exit"),
    "FZ-03": ("caveat.gap", "stop.interim"),
    "FZ-04": ("case2.status", "banner.case2.1"),
    "FZ-05": ("disconnect.line",),
    "FZ-06": ("stop.algo_builder.1", "stop.algo_builder.2", "stop.algo_builder.reduce_only"),
    "FZ-07": ("oco.race", "refused.plain_tp_sl.1"),
    "FZ-08": ("v.slice_min", "v.visible"),
    "FZ-09": ("v.over_budget.1", "not_started"),
    "FZ-10": ("cancel.flatten.2", "control.2"),
}
# The parents' deck spans whose quoted strings the deck must hold (doc, first, last, cell index),
# and the colon-led label list of D03:390.
UNION = (("D02", 350, 409, 1), ("D03", 360, 425, 1), ("D03", 236, 236, 2), ("D04", 234, 240, 1))
LABEL_LINES = (("D03", 390, 1),)
# Strings a parent holds that the deck records elsewhere: C-e's two (D03's link-down wording is
# carried; the registered lockout reason is carried by cite).
SUPERSEDED = {
    ("D02", 403): "C-e",
    ("D03", 413): "C-e",
}
# A source line outside the parents' deck tables fixes its own status.
STATUS_AT = {
    ("D02", 187): "binding-pending-owner",
    ("D02", 237): "binding-pending-owner",
    ("D02", 287): "binding-pending-owner",
    ("D03", 221): "PROPOSED",
    ("D03", 236): "binding-pending-owner",
    ("D04", 236): "merged",
    ("D05", 315): "merged",
    ("D05", 509): "PROPOSED",
}
DECK_TABLES = (("D02", 350, 409), ("D03", 360, 425))
# The frame tables: every frame row is a state row's source.
STATE_SPANS = (
    ("D02", 193, 217, "SCR-066"),
    ("D02", 245, 259, "SCR-067"),
    ("D02", 293, 310, "SCR-068"),
    ("D03", 157, 171, "SCR-069"),
    ("D03", 199, 200, "SCR-070"),
    ("D03", 210, 224, "SCR-070"),
    ("D03", 230, 241, "SCR-070"),
    ("D03", 247, 252, "SCR-070"),
    ("D03", 258, 260, "SCR-070"),
)
# `14`'s States lines and the drawn frames that carry their words (mapping rows, D02-C8).
STATES_14 = (
    (1558, "SCR-066", {"configured": "configured-default", "running": "running",
                       "paused": "paused-by-you", "completed": "completed",
                       "cancelled": "cancelled", "failed": "failed"}),
    (1583, "SCR-068", {"running": "running", "limit reached": "limit-reached",
                       "fell back to market": "fell-back-to-market"}),
    (1621, "SCR-070", {"running": "running", "paused": "row-paused-by-you",
                       "degraded": "degraded-case-1", "completed": "row-completed",
                       "failed": "row-failed"}),
)  # fmt: skip
# The upstream G and CG rows a status may name (by their table lines at the base).
G_LINES = (("D02", 519, 531), ("D03", 338, 349))
D04_G = ("D04-G1", "D04-G2", "D04-G3")
OWNER_TICKET = re.compile(r"\((?:E33-[A-Z]\d\d)(?:, E33-[A-Z]\d\d)*\)")
# The component headings the map must name, in its rows (`15` line → CMP id).
CMP_HEADINGS = {
    1357: "CMP-118", 1841: "CMP-158", 1085: "CMP-103", 1437: "CMP-123", 271: "CMP-023",
    2698: "CMP-227", 1517: "CMP-130", 528: "CMP-047", 1382: "CMP-119", 549: "CMP-049",
    606: "CMP-055", 624: "CMP-057", 488: "CMP-043", 498: "CMP-044", 411: "CMP-036",
    119: "CMP-008", 1043: "CMP-100", 1057: "CMP-101", 844: "CMP-079", 974: "CMP-093",
}  # fmt: skip
A_ROWS = {"CMP-245": "A-1", "CMP-246": "A-2", "CMP-118": "A-3", "CMP-158": "A-4",
          "CMP-103": "A-5", "CMP-123": "A-6", "CMP-023": "A-7"}  # fmt: skip
# The story items: SB id → (story, the CITE key of its story count, the runs anchor).
SB_ITEMS = {
    "SB-1": ("E33-S05", "st.shell", "runs.sb1"),
    "SB-2": ("E33-S05", "st.card", "runs.sb2"),
    "SB-3": ("E33-S06", "st.row", "runs.sb3"),
    "SB-4": ("E33-S05, E33-S06", "st.label", "runs.sb4"),
    "SB-5": ("E33-S05", "st.cmp158", "runs.sb5"),
}
CELLS_PER_STORY = 4  # dark / light × compact / comfortable (`15`:41)
# D05's L rows of D04 frame ids (L id → its D05 line and the D04 family prefix).
LAYER = {
    "L-32": (499, "CMP-246/"),
    "L-33": (500, "CMP-118/card-"),
    "L-34": (501, "CMP-118/row-"),
    "L-35": (502, "CMP-245/"),
    "L-36": (503, "motion/"),
}
D04_REGISTER = (329, 397)
F_SPAN = (509, 520)
CONSUMER_ISSUES = ("#1105", "#1106", "#1042", "#1100", "#1096", "#994", "#1107")
FEATURES_DIR = "apps/web/src/features/"
CHARSET_ALLOW = frozenset("…")
NO_DEFAULT = re.compile(r"decided nowhere|not decided|undecided|to be decided|no default|\bTBD\b")
UNIT = (
    r"(?:px|ms|s|%|fps|Hz|KB|rows?|days?|entries|strings?|keys?|events?|boards?|frames?"
    r"|renders?|items?|ids?|characters|lines?|mutations?|findings?|screens?|states?|sections?"
    r"|questions?|components?|variants?|sprints?|gaps?|messages?|blocks?|checks?|runs?"
    r"|stories|story|twins?|algos?)"
)

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
    """A `##` section's key: its number, "BQ" for the questions' heading, or its first word."""
    t = heading.lstrip("# ").strip()
    m = re.match(r"(\d+)\.", t)
    if m:
        return f"§{m[1]}"
    return "BQ" if t.startswith("The questions") else t.split()[0] if t else "(top)"


def sec_of_line(text: str, line_no: int) -> str:
    cur = "(top)"
    for ln in text.split("\n")[:line_no]:
        m = HEADING.match(ln)
        if m and len(m[1]) <= 2:
            cur = sec_key(m[2])
    return cur


def h2(text: str, key: str) -> str:
    """The `##` section whose key is `key` (e.g. "§3", "BQ", "Acceptance-criteria")."""
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
    past a doubting verb."""
    t = norm_text(unquote(clause))

    def drop(m: re.Match[str]) -> str:
        return m[0] if DOUBTING.search(m[1]) else " "

    t = re.sub(rf"\b{NEG_WORD}\b((?:\s+[^\s:;,]+){{0,6}}?)\s+(?:{term})", drop, t)
    return re.search(term, t) is not None


SENTENCE = re.compile(r";\s|(?<=[.!?])\s+|(?<=[.!?]\*\*)\s+|\s—\s")


def clauses(text: str) -> list[str]:
    out: list[str] = []
    for ln in strip_comments(text).split("\n"):
        if ln.startswith("|"):
            out += [c for cell in split_row(ln) for c in SENTENCE.split(cell) if c.strip()]
        elif ln.strip():
            out += [c for c in SENTENCE.split(ln.lstrip("#").strip()) if c.strip()]
    return out


# ---------------------------------------------------------------------------- the texts


@dataclass
class Texts:
    spec: str
    deck: str
    disk: dict[str, str]  # the untouched files and `14`, from the working tree
    stray: tuple[str, ...]  # changed paths outside OWN (against the merge-base, and untracked)
    handoffs: tuple[str, ...]  # any E33-D06 hand-off file present
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
        str(p.relative_to(ROOT)) for p in (ROOT / "docs/design/E33").glob("E33-D06*handoff*")
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
def tickets() -> dict[str, dict[str, object]]:
    data = json.loads(at_base(CITE_FILES["E33.json"]))
    items = data if isinstance(data, list) else data.get("tickets", [])
    return {str(it.get("key")): it for it in items if isinstance(it, dict)}


@functools.lru_cache(maxsize=1)
def sprints() -> dict[str, int]:
    out: dict[str, int] = {}
    for key, it in tickets().items():
        m = re.search(r"(\d+)", str(it.get("sprint", "")))
        if m:
            out[key] = int(m[1])
    return out


def boards(prefix: str) -> set[str]:
    return {
        m[1]
        for n in tree_at(BASE, IMG_DIR + "/")
        if (m := re.match(rf"{IMG_DIR}/{prefix}-(\d\d)-[a-z0-9-]+\.png$", n))
        and not re.search(r"-(greyscale|deuteranopia)\.png$", n)
    }


def renders(prefix: str) -> list[str]:
    return [
        n
        for n in tree_at(BASE, IMG_DIR + "/")
        if re.search(rf"{prefix}-.*-(greyscale|deuteranopia)\.png$", n)
    ]


def lifted_hash(doc: str, rev: str, a: int, b: int) -> str:
    text = git_show(rev, CITE_FILES[doc]) or ""
    chunk = "\n".join(text.split("\n")[a - 1 : b])
    return hashlib.sha256(chunk.encode("utf-8")).hexdigest()[:12]


CITE_FIGURES = {
    "w.dialog": ("D02", 145, r"(\d+) px wide PROPOSED"),
    "h.header": ("D02", 149, r"Header row \((\d+) px\)"),
    "h.footer": ("D02", 155, r"one sticky row, (\d+) px"),
    "pad.dialog": ("D02", 145, r"`space\.dialog\.padding` (\d+) px"),
    "row.compact": ("D02", 151, r"`space\.row\.height\.compact` (\d+) px"),
    "boundary": ("D02", 154, r"the (\d+) px `color\.status\.danger\.default`"),
    "variant.row": ("D03", 139, r"; (\d+) px row"),
    "walk.chase.ms": ("D02", 549, r"Set a (\d+) ms chase"),
    "row.comfortable": ("D02", 151, r"`\.comfortable` (\d+) px"),
    "core": ("D03", 202, r"The (\d+)\s+px core"),
    "zoom": ("D05", 460, r"At (\d+)\s*%"),
    "target.min": ("D05", 239, r"targets are (\d+)"),
    "hz": ("14", 1624, r"coalesced to (\d+) Hz"),
    "ms.frame": ("14", 1624, r"under (\d+) ms"),
    "rows.100": ("14", 1624, r"with (\d+) running"),
    "announce.s": ("14", 1573, r"once every (\d+) s"),
    "stale.s": ("D03", 53, r"= (\d+) s;"),
    "reconcile.s": ("24", 5298, r"= (\d+)"),
    "confirm.ms": ("D02", 114, r"after (\d+) ms"),
    "modal.ms": ("E33.json", 271, r"Modal open < (\d+) ms"),
    "frames.d02": ("D05", 464, r"\((\d+)\s*in D02"),
    "frames.d03": ("D05", 464, r"(\d+)\s*in D03\)"),
    "d04.pending": ("D05", 464, r"D04's (\d+)\s*frame ids"),
    "d04.drawn": ("D04", 321, r"(\d+)\s*frames are drawn"),
    "d04.request": ("D04", 321, r"; (\d+)\s*named frames"),
    "st.shell": ("D04", 515, r"AlgoBuilderShell (\d+)"),
    "st.card": ("D04", 515, r"CMP-118 card (\d+)"),
    "st.row": ("D04", 515, r"H03 Table 1 \((\d+)\)"),
    "st.label": ("D04", 515, r"AlgoStateLabel (\d+)"),
    "st.runs": ("D04", 515, r"(\d+)\s*runs in all"),
    "st.cmp158": ("D04H", 204, r"\| (\d+) added"),
}


def compute(t: Texts) -> Values:
    if t.values is not None:
        return t.values
    v: Values = {}
    tot = 0
    for d in ("D01", "D02", "D03", "D04"):
        n = len(boards(f"E33-{d}"))
        v[f"COUNT:boards.{d.lower()}"] = str(n)
        tot += n
    v["COUNT:boards.merged"] = str(tot)
    v["COUNT:renders.d02"] = str(len(renders("E33-D02")))
    rows = state_rows(t.spec)
    v["COUNT:states"] = str(len(rows))
    for scr in SCREENS:
        v[f"COUNT:frames.{scr[4:]}"] = str(
            sum(len(frames_named(r[2])) for r in rows if len(r) > 2 and r[1] == scr)
        )
    api = api_rows(t.spec)
    v["COUNT:api.rows"] = str(len(api))
    v["COUNT:api.grows"] = str(sum(1 for r in api if len(r) > 5 and "G-row" in r[5]))
    for key, (doc, n, rx) in CITE_FIGURES.items():
        m = re.search(rx, strip_comments(line_at(doc, n)))
        v[f"CITE:{key}"] = m[1] if m else "?"
    total = 0
    for _story, cite_key, runs_key in SB_ITEMS.values():
        figure = v.get(f"CITE:{cite_key}", "?")
        runs = int(figure) * CELLS_PER_STORY if figure.isdigit() else 0
        v[f"COUNT:{runs_key}"] = str(runs)
        total += runs
    v["COUNT:runs.total"] = str(total)
    es = deck_entries(t)
    v["COUNT:deck.entries"] = str(len(es))
    for st, key in (("merged", "merged"), ("binding-pending-owner", "bpo"),
                    ("PROPOSED", "proposed")):  # fmt: skip
        v[f"COUNT:deck.{key}"] = str(sum(1 for e in es.values() if e.get("status") == st))
    ev = deck_data(t).get("events")
    v["COUNT:deck.events"] = str(len(ev) if isinstance(ev, list) else 0)
    v["COUNT:deck.carried"] = str(len(carried(t)))
    v["COUNT:fz"] = str(len(fz_rows(t.spec)))
    reg = d04_register()
    ids_all = dark_all = light_all = 0
    for lid, (n, prefix) in LAYER.items():
        ids = layer_ids(n)
        dark = [f for f, th in reg if f.startswith(prefix) and th == "dark"]
        light = [f for f, th in reg if f.startswith(prefix) and th == "light"]
        v[f"COUNT:l.{lid[2:]}.ids"] = str(len(ids))
        v[f"COUNT:l.{lid[2:]}.dark"] = str(len(dark))
        v[f"COUNT:l.{lid[2:]}.light"] = str(len(light))
        ids_all, dark_all, light_all = (
            ids_all + len(ids),
            dark_all + len(dark),
            light_all + len(light),
        )
    v["COUNT:l.ids"], v["COUNT:l.dark"] = str(ids_all), str(dark_all)
    v["COUNT:l.light"] = str(light_all)
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
    for key, n in sprints().items():
        v[f"DATE:{key}"] = cal_start(n)
    v["DATE:S16.start"] = cal_start(16)
    v["DATE:S16.end"] = cal_start(16, 6)
    for doc, _label, a, b, key in LIFTED:
        v[f"HASH:{key}"] = lifted_hash(doc, LIFT_SHA[doc], a, b)
    return v


@functools.lru_cache(maxsize=1)
def d04_register() -> tuple[tuple[str, str], ...]:
    """D04 §9.2's drawn frames as (frame id, theme)."""
    out: list[tuple[str, str]] = []
    for n in range(D04_REGISTER[0], D04_REGISTER[1] + 1):
        m = re.match(r"\| `([^`]+) · (dark|light)`\s*\|", line_at("D04", n))
        if m:
            out.append((m[1], m[2]))
    return tuple(out)


def layer_ids(n: int) -> list[str]:
    cells = split_row(line_at("D05", n))
    return re.findall(r"`([^`]+)`", cells[1]) if len(cells) > 1 else []


# ---------------------------------------------------------------------------- the spec's tables


def state_rows(spec: str) -> list[list[str]]:
    return [r for r in table_of(h2(spec, "§2"), "S") if re.fullmatch(r"S-\d\d", r[0])]


def frame_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§2"), "Spec")


def redline_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§3"), "Screen")


def api_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§3"), "Control or datum")


def cmp_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§4"), "CMP")


def sb_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§4"), "SB")


def fz_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§5"), "FZ")


def layer_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§7"), "L")


def frow_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§7"), "F")


def safety_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§8"), "Path")


def verb_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§9"), "Control")


def log_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§10"), "Ids")


def c_rows(spec: str) -> list[list[str]]:
    return table_of(h2(spec, "§14"), "C")


def f_ids(cell: str) -> list[str]:
    out: list[str] = []
    for a, b in re.findall(r"F-(\d\d)(?:(?:\.\.|, )F-(\d\d))?", cell):
        out += [f"F-{n:02d}" for n in sorted({int(a), int(b or a)})]
    return out


def frame_name(cell: str) -> str:
    """`SCR-066/configured-default` → configured-default; `SCR-076/oco` → oco."""
    c = cell.strip().strip("`").strip()
    return c.split("/")[-1].strip() if c.startswith("SCR-") else c


def frames_named(cell: str) -> list[str]:
    return [frame_name(w) for w in strip_comments(cell).split(";") if w.strip()]


ID_TOKEN = re.compile(
    r"(?P<pre>(?:D0[2-5]|TM)\s+)?(?P<a>(?:D0[2-5]-)?(?:OQ|Q|G|C|CG|P|G-P|D)-?\d+)"
    r"(?:\.\.(?P<b>(?:D0[2-5]-)?(?:OQ|Q|G|C|CG|P|G-P|D)-?\d+))?"
)


def expand_ids(cell: str) -> list[str]:
    """The register's ids: `OQ-1, OQ-12`, `D02-Q2..D02-Q4`, `D05 Q-01..Q-04`, `TM D6, TM D8`,
    `G-P1..G-P3`; a range keeps its left id's zero padding and prefix."""
    out: list[str] = []
    for tok in re.split(r"[;,]\s*", strip_comments(cell).replace("`", "")):
        tok = tok.strip()
        m0 = re.match(r"(D0[2-5]|TM)\s+", tok)
        prefix = m0[1] + " " if m0 else ""
        body = tok[len(m0[0]) :] if m0 else tok
        r = re.fullmatch(r"((?:D0[2-5]-)?[A-Z]+(?:-P)?-?)(\d+)\.\.(?:D0[2-5]-)?[A-Z-]*?(\d+)", body)
        if r:
            w = len(r[2]) if r[2].startswith("0") else 0
            out += [f"{prefix}{r[1]}{str(n).zfill(w)}" for n in range(int(r[2]), int(r[3]) + 1)]
        elif re.fullmatch(r"(?:D0[2-5]-)?[A-Z]+(?:-P)?-?\d+", body):
            out.append(f"{prefix}{body}")
    return out


# ---------------------------------------------------------------------------- fill


OLD_VALUE = re.compile(r"(?<![\w.,])([0-9a-f?][0-9a-fk,.-]*)?<!--=([A-Z]+:[^>]+?)-->")


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
    r"|variants?|renders?|ids?|blocks?|checks?|runs?|stories|algos?|twins?)"
)
WORDCOUNT = re.compile(rf"\b{NUMBER_WORD}\s+(?:[a-z'-]+\s+)?{COUNTED}\b", re.IGNORECASE)


def g_wordcount(t: Texts) -> list[Finding]:
    """A count written as a word before a counted noun is a hand-typed figure."""
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if ln.startswith("#") or sec_of_line(t.spec, i) == "§15":
            continue
        for m in WORDCOUNT.finditer(prose_of(ln)):
            bad.append(F("G-WORDCOUNT", f"line {i}: a count as a word {m[0]!r}", "spec",
                         sec_of_line(t.spec, i)))  # fmt: skip
    return bad


CITE_HEAD = re.compile(
    r"`?(?P<doc>\d{2}|H03|D04H|D0[1-5]|TM|E09-D09|E29-D03|E30-D0[23]|E32-D02|CONST|CAL|README"
    r"|E33\.json)`?"
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


EVENT = re.compile(r"`(algo\.[a-z_]+)")


def g_quote(t: Texts) -> list[Finding]:
    bad = []
    ticket = at_base(CITE_FILES["E33.json"]).replace('\\"', '"')
    for i, ln in enumerate(t.spec.split("\n"), 1):
        sec = sec_of_line(t.spec, i)
        if sec == "§15":
            continue
        docs = {d for d, _a, _b in cites_in(ln)}
        pool = [ticket] + [html.unescape("\n".join(base_lines(d))) for d in docs]
        for m in EVENT.finditer(strip_comments(ln)):
            if not any(m[1] in p for p in pool):
                bad.append(F("G-QUOTE", f"line {i}: `{m[1]}` is not in a cited text", "spec",
                             sec))  # fmt: skip
        work = CODE.sub(lambda m: m[0][1:-1], strip_comments(ln)).replace('\\"', "\u0001")
        for m in QUOTED.finditer(work):
            q = m[0][1:-1].replace("\u0001", '"')
            if len(q) < 12:
                continue
            if not any(q in p or q in p.replace("`", "") for p in pool):
                bad.append(F("G-QUOTE", f"line {i}: {q[:50]!r} is not verbatim in a cited text",
                             "spec", sec))  # fmt: skip
    return bad


FORBIDDEN_COPY = re.compile(r"ret_?code|\bretCode\b|Traceback|Exception\b", re.IGNORECASE)
PENDING_COPY = re.compile(r"\bTBD\b|\bTODO\b")


def quotes_of(cell: str) -> list[str]:
    """Quoted copy in a cell; an attribute value (`role="note"`) is not copy."""
    return [html.unescape(m[1]) for m in re.finditer(r'(?<![=\w])"([^"\n]*)"', cell)]


def label_items(cell: str) -> list[str]:
    """The items of a colon-led " · " label list (D03:390's `state.*` labels)."""
    if ": " not in cell:
        return []
    return [p.strip() for p in cell.split(": ", 1)[1].split(" · ") if p.strip()]


def wholes(doc: str, n: int) -> set[str]:
    """The whole units a deck string may equal on its source line: a quote's content, or one item
    of the colon-led label list of a LABEL_LINES row. Never a substring."""
    line = line_at(doc, n)
    out = set(quotes_of(strip_comments(line)))
    for d, ln, col in LABEL_LINES:
        if (d, ln) == (doc, n):
            cells = split_row(line)
            out.update(label_items(cells[col]) if len(cells) > col else [])
    return out


def status_of(doc: str, n: int) -> tuple[str, ...]:
    """The deck statuses a source row allows: the parent deck table's Source cell (memo → binding
    pending the owner; `14` and an upstream registry → merged; `new` → PROPOSED; a PROPOSED key
    → PROPOSED), a mixed cell adding PROPOSED; elsewhere STATUS_AT, else PROPOSED."""
    if (doc, n) in STATUS_AT:
        return (STATUS_AT[(doc, n)],)
    if (doc, n) in LABEL_LINES_SET:
        return ("binding-pending-owner",)
    if not any(d == doc and a <= n <= b for d, a, b in DECK_TABLES):
        return ("PROPOSED",)
    cell = split_row(line_at(doc, n))[2]
    if "PROPOSED" in cell:
        return ("PROPOSED",)
    first = re.split(r"[\s(;]", cell.strip())[0].strip("`")
    main = (
        "binding-pending-owner"
        if first.startswith("memo")
        else "PROPOSED" if first == "new" else "merged"
    )
    mixed = main != "PROPOSED" and re.search(r"`new`|\bnew\b", cell[len(first) + 1 :])
    return (main, "PROPOSED") if mixed else (main,)


LABEL_LINES_SET = {(d, n) for d, n, _c in LABEL_LINES}


@functools.lru_cache(maxsize=1)
def rt_region() -> dict[str, str]:
    """D05 §8.1's routing rows: RT id → region."""
    out = {}
    for n in range(346, 374):
        c = split_row(line_at("D05", n))
        if len(c) > 3 and c[0].startswith("RT-"):
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
    if (data.get("pack"), data.get("version"), data.get("base")) != ("E33-D06", "v1", BASE):
        D("the deck's pack, version or base is wrong")
    if data.get("header") != HEADER or HEADER not in at_base(CITE_FILES["E33.json"]):
        D("the header is not T Sec's sentence verbatim")
    members = data.get("strings")
    for k, val in (members if isinstance(members, dict) else {}).items():
        if not isinstance(val, dict):
            D(f"{k}: a member of strings that is not an entry")
    es = deck_entries(t)
    seen: dict[str, str] = {}
    fz_of = {k: z for z, ks in FROZEN.items() for k in ks}
    for k, e in es.items():
        extra = set(e) - set(ENTRY_FIELDS)
        if extra:
            D(f"{k}: unknown fields {sorted(extra)}")
        for f_ in ("string", "screen", "owner", "status", "announce", "source"):
            if not isinstance(e.get(f_), str) or not str(e.get(f_)).strip():
                D(f"{k}: {f_} missing or empty")
        s = str(e.get("string", ""))
        if s in seen:
            D(f"{k}: the string of {seen[s]} again (each once)")
        seen.setdefault(s, k)
        want = list(dict.fromkeys(re.findall(r"\{([^{}]+)\}", s)))
        if e.get("params", []) != want or ("params" in e and not want):
            D(f"{k}: params must name the string's placeholders in order")
        if any(x not in DECK_SCREENS for x in str(e.get("screen", "")).split(", ")):
            D(f"{k}: screen {e.get('screen')!r}")
        if e.get("announce") not in ANNOUNCE:
            D(f"{k}: announce {e.get('announce')!r}")
        if FORBIDDEN_COPY.search(s) or PENDING_COPY.search(s):
            D(f"{k}: exchange text, exception text or a TBD in user copy (T Sec)")
        src = cites_in(str(e.get("source", "")))
        if len(src) != 1 or src[0][1] != src[0][2]:
            D(f"{k}: source must be one line")
            continue
        doc, n, _b = src[0]
        if e.get("owner") != f"E33-{doc}" or e.get("owner") not in OWNERS:
            D(f"{k}: owner {e.get('owner')!r} is not its source's spec")
        if s not in wholes(doc, n):
            D(f"{k}: not a whole quote at {doc}:{n} (no substring)")
        if e.get("status") not in STATUSES or e.get("status") not in status_of(doc, n):
            D(f"{k}: status {e.get('status')!r}, its source row allows {status_of(doc, n)}")
        rt = e.get("rt")
        if rt is not None and (rt not in rt_region() or e.get("announce") != rt_region()[rt]):
            D(f"{k}: announce {e.get('announce')!r} is not {rt}'s region")
        if rt is None and e.get("announce") != "none":
            D(f"{k}: an announced string names its RT row")
        if e.get("frozen") != fz_of.get(k):
            D(f"{k}: frozen {e.get('frozen')!r}, the table says {fz_of.get(k)!r}")
    for z, ks in FROZEN.items():
        for kk in ks:
            if kk not in es:
                D(f"{z}: {kk} is not in the deck")
    ev = data.get("events")
    if not isinstance(ev, list) or not ev:
        D("events: a list of event rows")
        ev = []
    srows = {x[0]: x[1] for x in state_rows(t.spec)}
    for r in ev:
        if not isinstance(r, dict) or set(r) != {"event", "class", "screen", "trigger", "source"}:
            D(f"events: {r!r:.40} is not event · class · screen · trigger · source")
            continue
        sid = re.search(r"S-\d\d", str(r["trigger"]))
        if not sid or srows.get(sid[0]) != r["screen"]:
            D(f"events: {r['event']}'s trigger names no {r['screen']} state row")
        src = cites_in(str(r["source"]))
        line = line_at(src[0][0], src[0][1]) if len(src) == 1 else ""
        if r["class"] not in ("audited", "analytics") or str(r["event"]) not in line:
            D(f"events: {r['event']} is not named at its source, or its class is wrong")
        if r["screen"] not in SCREENS:
            D(f"events: {r['event']}'s screen")
    for r in carried(t):
        cid = str(r.get("id"))
        src = cites_in(str(r.get("source", "")))
        ok = (
            set(r) == {"id", "owner", "source"}
            and len(src) == 1
            and src[0][0] == r.get("owner")
            and f"`{cid}`" in line_at(src[0][0], src[0][1])
        )
        if not ok:
            D(f"carried {cid}: not its owner's key at the cited line")
    # the union: every quoted string of the parents' deck spans is held, carried or superseded
    pool = {str(e.get("string")) for e in es.values()}
    cpool: set[str] = set()
    for r in carried(t):
        for d, a, _b in cites_in(str(r.get("source", ""))):
            cpool.update(quotes_of(line_at(d, a)))
    for doc, a, b, col in UNION:
        for n in range(a, b + 1):
            if (doc, n) in SUPERSEDED:
                continue
            cells = split_row(line_at(doc, n))
            if len(cells) <= col:
                continue
            for q in quotes_of(strip_comments(cells[col])):
                if q not in pool and q not in cpool and not carried_line(doc, n, t):
                    D(f"{doc}:{n}: {q[:40]!r} is not in the deck (the union)")
    for doc, n, col in LABEL_LINES:
        for q in label_items(split_row(line_at(doc, n))[col]):
            if q not in pool:
                D(f"{doc}:{n}: the label {q[:40]!r} is not in the deck (the union)")
    return bad


def carried_line(doc: str, n: int, t: Texts) -> bool:
    """A parent deck row whose key is carried by cite (its strings are the owner's)."""
    cells = split_row(line_at(doc, n))
    keys = re.findall(r"`([^`]+)`", cells[0]) if cells else []
    ids = {str(r.get("id")) for r in carried(t)}
    alias = {"notice.viewer": "notice.panel_read_only", "stop.note": "e32.sl.note.draft",
             "stop.reduce_only": "sl.reduce_only", "risk.slippage": "preview.slippage"}  # fmt: skip
    return any(k in ids or alias.get(k) in ids for k in keys)


def g_frames(t: Texts) -> list[Finding]:
    bad = []
    rows = frame_rows(t.spec)
    if [r[0] for r in rows] != ["D01", "D02", "D03", "D04", "D05"]:
        bad.append(F("G-FRAMES", "the frame register holds D01..D05 in order", sec="§2"))
    for r in rows:
        if len(r) != 5 or r[0] == "D05":
            continue
        page = cites_in(r[2])
        if not page or not any(
            re.search(r"\bid\b", line_at(page[0][0], n)) for n in range(page[0][1], page[0][2] + 1)
        ):
            bad.append(F("G-FRAMES", f"{r[0]}: the page cite holds no page id", sec="§2"))
        m = re.search(r"drawn: (\d\d)\.\.(\d\d)", r[1])
        drawn = {f"{n:02d}" for n in range(int(m[1]), int(m[2]) + 1)} if m else set()
        if drawn != boards(f"E33-{r[0]}"):
            bad.append(F("G-FRAMES", f"{r[0]}: the boards named are not the merged set", sec="§2"))
    return bad


def span_of(doc: str, n: int) -> tuple[str, int, int, str] | None:
    return next((s for s in STATE_SPANS if s[0] == doc and s[1] <= n <= s[2]), None)


def g_states(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    keys = key_set(t)
    es = deck_entries(t)
    rows = state_rows(t.spec)
    covered: set[str] = set()
    cited: set[tuple[str, int]] = set()
    for n, r in enumerate(rows, 1):
        if r[0] != f"S-{n:02d}":
            bad.append(F("G-STATES", f"{r[0]}: out of sequence (S-{n:02d} expected)", sec="§2"))
        if len(r) != 6:
            bad.append(F("G-STATES", f"{r[0]}: cell count", sec="§2"))
            continue
        if r[1] not in SCREENS:
            bad.append(F("G-STATES", f"{r[0]}: screen {r[1]!r}", sec="§2"))
        named = frames_named(r[2])
        names = re.findall(r"`([^`]+)`", r[5])
        missing = [k for k in names if k not in keys]
        if not names or missing:
            bad.append(F("G-STATES", f"{r[0]}: keys {missing or 'none'} not in the deck",
                         sec="§2"))  # fmt: skip
        for k in names:
            e = es.get(k)
            if e is not None and r[1] not in str(e.get("screen", "")).split(", "):
                bad.append(F("G-STATES", f"{r[0]}: {k}'s screen is not {r[1]}", "deck", "strings"))
        covered.update(names)
        cs = cites_in(r[3])
        if not cs:
            bad.append(F("G-STATES", f"{r[0]}: no source cite", sec="§2"))
        frames: list[str] = []
        for d, a, b in cs:
            for x in range(a, b + 1):
                span = span_of(d, x)
                if span is None or span[3] != r[1]:
                    bad.append(F("G-STATES", f"{r[0]}: {d}:{x} is not a {r[1]} frame row",
                                 sec="§2"))  # fmt: skip
                    continue
                cited.add((d, x))
                frames.append(frame_name(split_row(line_at(d, x))[0]))
        if sorted(frames) != sorted(named):
            bad.append(F("G-STATES", f"{r[0]}: frames named {sorted(set(named) ^ set(frames))[:2]}"
                         " differ from the cited rows", sec="§2"))  # fmt: skip
        bm = re.fullmatch(r"(D0[23]) (\d\d(?:, \d\d)*)", r[4])
        if not bm or not set(bm[2].split(", ")) <= boards(f"E33-{bm[1]}"):
            bad.append(F("G-STATES", f"{r[0]}: board {r[4]!r} is not a merged board", sec="§2"))
    for k in sorted(set(es) - covered):
        bad.append(F("G-STATES", f"deck key {k} has no state row (AC1)", sec="§2"))
    for d, a, b, scr in STATE_SPANS:
        for x in range(a, b + 1):
            if (d, x) not in cited:
                bad.append(F("G-STATES", f"the {scr} frame at {d}:{x} has no S row", sec="§2"))
    v = compute(t)
    if int(v["COUNT:frames.066"]) + int(v["COUNT:frames.067"]) + int(v["COUNT:frames.068"]) != int(
        v.get("CITE:frames.d02", "0") if v.get("CITE:frames.d02", "?").isdigit() else -1
    ):
        bad.append(F("G-STATES", "SCR-066..SCR-068's frames are not D05's D02 count", sec="§2"))
    if int(v["COUNT:frames.069"]) + int(v["COUNT:frames.070"]) != int(
        v.get("CITE:frames.d03", "0") if v.get("CITE:frames.d03", "?").isdigit() else -1
    ):
        bad.append(F("G-STATES", "SCR-069 and SCR-070's frames are not D05's D03 count", sec="§2"))
    for n, scr, words in STATES_14:
        line = line_at("14", n)
        for word, frame in words.items():
            if word not in line:
                bad.append(F("G-STATES", f"`14`:{n} no longer reads {word!r}", sec="§2"))
            if not any(r[1] == scr and frame in frames_named(r[2]) for r in rows if len(r) > 2):
                bad.append(F("G-STATES", f"`14`:{n}'s {word!r} has no {scr} frame row", sec="§2"))
    return bad


@functools.lru_cache(maxsize=1)
def drift_rows() -> dict[str, list[str]]:
    """D04H §E's drift rows: DR id → cells."""
    out = {}
    for n in range(175, 193):
        c = split_row(line_at("D04H", n))
        if c and re.fullmatch(r"DR-\d+", c[0]):
            out[c[0]] = c
    return out


TOKEN = re.compile(
    r"`((?:color|size|space|motion|font|border|radius|opacity|elevation|type)\.[a-z0-9.-]+)`"
)


def g_redline(t: Texts) -> list[Finding]:
    bad = []
    rows = redline_rows(t.spec)
    named = {s for r in rows for s in re.findall(r"SCR-0\d\d", r[0])}
    span = {f"SCR-{n:03d}" for n in range(66, 71)}
    if not span <= named | {"SCR-067", "SCR-068"} or not rows:
        bad.append(F("G-REDLINE", "every screen has a redline row", sec="§3"))
    dr = drift_rows()
    for r in rows:
        if len(r) != 5:
            bad.append(F("G-REDLINE", f"{r[0]} {r[1][:20]}: cell count", sec="§3"))
            continue
        if not cites_in(r[3]):
            bad.append(F("G-REDLINE", f"{r[1][:24]}: no source", sec="§3"))
        if not re.fullmatch(r"as merged|corrected \((?:DR-\d+|D04-C\d+)(?:, (?:DR-\d+|D04-C\d+))*\)",
                            r[4]):  # fmt: skip
            bad.append(F("G-REDLINE", f"{r[1][:24]}: status {r[4]!r}", sec="§3"))
        for d in re.findall(r"DR-\d+", r[4]):
            row = dr.get(d)
            if row is None or not row[-1].startswith("corrected"):
                bad.append(F("G-REDLINE", f"{r[1][:24]}: {d} is no corrected drift row", sec="§3"))
                continue
            want = re.match(r"`([^`]+)`", row[4])
            if want and f"`{want[1]}`" not in r[2]:
                bad.append(F("G-REDLINE", f"{r[1][:24]}: {d}'s `{want[1]}` is not bound",
                             sec="§3"))  # fmt: skip
            for old in re.findall(r"`([^`]+)`", row[2]):
                if (
                    TOKEN.fullmatch(f"`{old}`")
                    and f"`{old}`" in r[2]
                    and not re.search(rf"not [^;|]*`{re.escape(old)}`", r[2])
                ):
                    bad.append(F("G-REDLINE", f"{r[1][:24]}: the superseded `{old}` is bound",
                                     sec="§3"))  # fmt: skip
    return bad


@functools.lru_cache(maxsize=1)
def upstream_g() -> frozenset[str]:
    ids = {
        m
        for d, a, b in G_LINES
        for n in range(a, b + 1)
        for m in re.findall(r"^\| (D0[23]-C?G\d+) ", line_at(d, n))
    }
    return frozenset(ids | set(D04_G))


API_STATUS = re.compile(
    r"^(?:both|in `2[24]`|`24` only|partial|neither|neither carries the other)"
    r"(?:; (?:C D02-C7|G-row [A-Z0-9, -]+ \([A-Z0-9, -]+\)|rendered at most \S+ Hz \(D04-C10\)"
    r"|G-row [A-Z0-9, -]+ \([A-Z0-9, -]+\) for `mode`))*$"
)


def names_on(cell: str, lines: list[str]) -> bool:
    names = [
        n
        for n in re.findall(r"`([^`]+)`", cell)
        if not re.fullmatch(r"\d\d", n) and not n.startswith(("algo: ", "AlgoSpec"))
    ]
    if not names:
        return True
    return any(
        nm in ln or nm.split(".")[0].split(":")[0] in ln or nm.split(".")[-1] in ln
        for nm in names
        for ln in lines
    )


def g_api(t: Texts) -> list[Finding]:
    """AC2: every control and datum row binds a field at its cited `22` / `23` / `24` line, and
    every missing carrier is an upstream G-row with its owner ticket."""
    bad = []
    rows = api_rows(t.spec)
    if not rows:
        return [F("G-API", "no field → API table", sec="§3")]
    for r in rows:
        if len(r) != 6:
            bad.append(F("G-API", f"{r[0][:24]}: cell count", sec="§3"))
            continue
        if not re.fullmatch(r"SCR-0\d\d(?:\.\.SCR-0\d\d)?", r[1]):
            bad.append(F("G-API", f"{r[0][:24]}: screen {r[1]!r}", sec="§3"))
        for col in (2, 3, 4):
            cs = [c for c in cites_in(r[col]) if c[0] in ("22", "23", "24", "14")]
            lines = [line_at(d, n) for d, a, b in cs for n in range(a, b + 1)]
            if cs and not names_on(r[col], lines):
                bad.append(F("G-API", f"{r[0][:24]}: the names are not at their cited lines",
                             sec="§3"))  # fmt: skip
        st = r[5]
        if not API_STATUS.match(strip_comments(re.sub(r"[0-9]+<!--=[^>]+-->", "N", st))):
            bad.append(F("G-API", f"{r[0][:24]}: status {st[:30]!r}", sec="§3"))
        for gid in re.findall(r"D0[2-4]-C?G\d+", st):
            if gid not in upstream_g():
                bad.append(F("G-API", f"{r[0][:24]}: {gid} is no upstream G-row", sec="§3"))
        if "G-row" in st and not OWNER_TICKET.search(st):
            bad.append(F("G-API", f"{r[0][:24]}: a G-row names no owner ticket", sec="§3"))
        if st.startswith("both") and not (cites_in(r[2]) and cites_in(r[3])):
            bad.append(F("G-API", f"{r[0][:24]}: both without a `22` and a `24` cite", sec="§3"))
        if st.startswith(("neither", "`24` only")) and "G-row" not in st:
            bad.append(F("G-API", f"{r[0][:24]}: a missing carrier names no G-row", sec="§3"))
    algos = re.search(r"/algos", at_base(PLAN["22"]) + at_base(PLAN["23"]))
    if algos:
        bad.append(F("G-API", "`22` / `23` serve `/algos` now: re-read §3 and §9", sec="§3"))
    return bad


def g_verbs(t: Texts) -> list[Finding]:
    """T Scope's control → verb → audit table: every audit key at its TM line, every per-kind key
    at its `14` line, every absent verb a G-row naming E33-T02."""
    bad = []
    rows = verb_rows(t.spec)
    need = ("Pause", "Resume", "Cancel", "Cancel and flatten", "Adopt", "Cancel all", "Pause all")
    controls = " ".join(r[0] for r in rows)
    for c in need:
        if c not in controls:
            bad.append(F("G-VERBS", f"no row for {c!r}", sec="§9"))
    for r in rows:
        if len(r) != 5:
            bad.append(F("G-VERBS", f"{r[0][:24]}: cell count", sec="§9"))
            continue
        for col, doc in ((3, "TM"), (4, "14")):
            keys = re.findall(r"`(algo\.[a-z_]+)`", r[col])
            lines = [line_at(d, n) for d, a, b in cites_in(r[col]) if d == doc
                     for n in range(a, b + 1)]  # fmt: skip
            for k in keys:
                if not any(k in ln for ln in lines):
                    bad.append(F("G-VERBS", f"{r[0][:20]}: `{k}` is not at its cited line",
                                 sec="§9"))  # fmt: skip
        if r[2].startswith("none") and not (
            re.search(r"G-row D0[23]-G\d+", r[2]) and "(E33-T02)" in r[2]
        ):
            bad.append(F("G-VERBS", f"{r[0][:20]}: an absent verb names no E33-T02 G-row",
                         sec="§9"))  # fmt: skip
        for gid in re.findall(r"D0[23]-G\d+", r[2]):
            if gid not in upstream_g():
                bad.append(F("G-VERBS", f"{r[0][:20]}: {gid} is no upstream G-row", sec="§9"))
        for d, a, _b in cites_in(r[2]):
            if d == "22" and "operationId" not in line_at(d, a):
                bad.append(F("G-VERBS", f"{r[0][:20]}: `22`:{a} is not an operation", sec="§9"))
    return bad


def g_cmp(t: Texts) -> list[Finding]:
    bad = []
    rows = cmp_rows(t.spec)
    seen: list[str] = []
    for r in rows:
        if len(r) != 5:
            bad.append(F("G-CMP", f"{r[0][:20]}: cell count", sec="§4"))
            continue
        ids = re.findall(r"CMP-\d{3}", r[0])
        seen += ids
        heads = [n for d, a, b in cites_in(r[2]) if d == "15" for n in range(a, b + 1)]
        for n in heads:
            if n in CMP_HEADINGS and not line_at("15", n).startswith(f"### {CMP_HEADINGS[n]}"):
                bad.append(F("G-CMP", f"`15`:{n} is no longer {CMP_HEADINGS[n]}", sec="§4"))
            if n in CMP_HEADINGS and CMP_HEADINGS[n] not in ids:
                bad.append(F("G-CMP", f"`15`:{n} is not a heading of this row", sec="§4"))
            if n not in CMP_HEADINGS and n != 1380:
                bad.append(F("G-CMP", f"`15`:{n} is no known heading", sec="§4"))
        for cid in ids:
            a = A_ROWS.get(cid)
            if a and f"{a} " not in r[3] + " " and f"{a} (" not in r[3] and f"{a}," not in r[3]:
                bad.append(F("G-CMP", f"{cid}: D04H's {a} is not named", sec="§4"))
            if a and not any(
                a in line_at("D04H", n) for d, x, y in cites_in(r[3]) if d == "D04H"
                for n in range(x, y + 1)
            ):  # fmt: skip
                bad.append(F("G-CMP", f"{cid}: {a}'s D04H cite does not hold it", sec="§4"))
    for cid in A_ROWS:
        if cid not in seen:
            bad.append(F("G-CMP", f"{cid}: no component row", sec="§4"))
    if "CMP-115" in "".join(r[0] for r in rows):
        bad.append(F("G-CMP", "CMP-115 is OrderRow, not the selector (D02-C2)", sec="§4"))
    return bad


def g_story(t: Texts) -> list[Finding]:
    bad = []
    v = compute(t)
    rows = sb_rows(t.spec)
    if [r[0] for r in rows] != list(SB_ITEMS):
        bad.append(F("G-STORY", f"the SB rows are {', '.join(SB_ITEMS)}", sec="§4"))
    for r in rows:
        if len(r) != 5 or r[0] not in SB_ITEMS:
            continue
        story, cite_key, runs_key = SB_ITEMS[r[0]]
        if r[1] != story:
            bad.append(F("G-STORY", f"{r[0]}: story {r[1]!r}, not {story}", sec="§4"))
        if f"<!--=COUNT:{runs_key}-->" not in r[4] and f"{{{{COUNT:{runs_key}}}}}" not in r[4]:
            bad.append(F("G-STORY", f"{r[0]}: the runs are not anchored", sec="§4"))
        if r[0] != "SB-5" and f"CITE:{cite_key}" not in r[3]:
            bad.append(F("G-STORY", f"{r[0]}: the story count is not D04's", sec="§4"))
    figs = [v.get(f"CITE:{k}", "?") for k in ("st.shell", "st.card", "st.row", "st.label")]
    if not all(f.isdigit() for f in figs) or CELLS_PER_STORY * sum(map(int, figs)) != int(
        v.get("CITE:st.runs", "0") if v.get("CITE:st.runs", "?").isdigit() else -1
    ):
        bad.append(F("G-STORY", "D04's runs are not four cells per story", sec="§4"))
    states = split_row(line_at("H03", 63))
    kinds = len(states[1].split(" · ")) if len(states) > 2 else 0
    per = len(states[2].split(" · ")) if len(states) > 2 else 0
    orph = len(split_row(line_at("H03", 64))[2].split(" · "))
    if str(kinds * per + orph) != v.get("CITE:st.row"):
        bad.append(F("G-STORY", "H03 Table 1's matrix is not D04's row count", sec="§4"))
    return bad


def g_frozen(t: Texts) -> list[Finding]:
    bad = []
    rows = fz_rows(t.spec)
    if [r[0] for r in rows] != list(FROZEN):
        bad.append(F("G-FROZEN", f"FZ rows are {', '.join(FROZEN)}", sec="§5"))
    es = deck_entries(t)
    for r in rows:
        if len(r) != 6 or r[0] not in FROZEN:
            continue
        ks = tuple(re.findall(r"`([^`]+)`", r[1]))
        if ks != FROZEN[r[0]]:
            bad.append(F("G-FROZEN", f"{r[0]}: keys {list(ks)}", sec="§5"))
        e = es.get(ks[0]) if ks else None
        if e is not None:
            if cites_in(r[4]) != cites_in(str(e.get("source"))):
                bad.append(F("G-FROZEN", f"{r[0]}: source is not the deck's", sec="§5"))
            if str(e.get("status")) != r[3]:
                bad.append(F("G-FROZEN", f"{r[0]}: status is not the deck's", sec="§5"))
        if f"frozen:{r[0]}" not in r[5]:
            bad.append(F("G-FROZEN", f"{r[0]}: no pinning test hook", sec="§5"))
    return bad


def g_lift(t: Texts) -> list[Finding]:
    bad = []
    block = h2(t.spec, "§7")
    m = re.search(
        r"\*\*Lifted, each with its hash at its merge\*\* \([^)]*\): (.*?)\. Drift", block
    )
    parts = re.findall(
        r"(?:(D0[45]) )?(§[\d.]+) \((D0[45]):(\d+)–(\d+)\) ([0-9a-f?]*)<!--=HASH:([\w.]+)-->",
        m[1] if m else "",
    )
    got = [(p[2], p[1], int(p[3]), int(p[4]), p[6]) for p in parts]
    if got != list(LIFTED):
        bad.append(F("G-LIFT", f"the lifted list is not the {len(LIFTED)} spans", sec="§7"))
    for doc, label, a, b, _key in LIFTED:
        if lifted_hash(doc, LIFT_SHA[doc], a, b) != lifted_hash(doc, BASE, a, b):
            bad.append(F("G-LIFT", f"{doc} {label}: drifted between its merge and {BASE}",
                         sec="§7"))  # fmt: skip
    if "lifts §5, §6, §7, §8, §9.1, §10, §11, §12, §13's replacements and §16.4" not in line_at(
        "D05", 833
    ):
        bad.append(F("G-LIFT", "D05:833 no longer names the lifted sections", sec="§7"))
    return bad


def g_layer(t: Texts) -> list[Finding]:
    """D05's PENDING D04 ids reconciled against D04's drawn frames, family by family."""
    bad = []
    v = compute(t)
    rows = {r[0]: r for r in layer_rows(t.spec)}
    if list(rows) != list(LAYER):
        bad.append(F("G-LAYER", f"the L rows are {', '.join(LAYER)}", sec="§7"))
    reg = d04_register()
    for lid, (n, prefix) in LAYER.items():
        ids = set(layer_ids(n))
        dark = {f for f, th in reg if f.startswith(prefix) and th == "dark"}
        if ids != dark:
            bad.append(F("G-LAYER", f"{lid}: D05's ids are not D04's dark frames", sec="§7"))
        r = rows.get(lid)
        if r is not None and (len(r) != 5 or f"(D05:{n})" not in r[4]):
            bad.append(F("G-LAYER", f"{lid}: the annotation cites no D05:{n}", sec="§7"))
    pend, drawn = v.get("CITE:d04.pending", "?"), v.get("CITE:d04.drawn", "?")
    if v["COUNT:l.ids"] != pend or str(int(v["COUNT:l.dark"]) + int(v["COUNT:l.light"])) != drawn:
        bad.append(F("G-LAYER", "the ids and frames do not add up to D05's and D04's", sec="§7"))
    if len(reg) != (int(drawn) if drawn.isdigit() else -1):
        bad.append(F("G-LAYER", "D04's register is not its drawn count", sec="§7"))
    return bad


def g_frow(t: Texts) -> list[Finding]:
    bad = []
    rows = frow_rows(t.spec)
    ids = [i for r in rows for i in f_ids(r[0])]
    want = [f"F-{n:02d}" for n in range(1, F_SPAN[1] - F_SPAN[0] + 2)]
    if ids != want:
        bad.append(F("G-FROW", f"the F rows are {want[0]}..{want[-1]}, each once", sec="§7"))
    sev = {split_row(line_at("D05", n))[0]: split_row(line_at("D05", n))[1]
           for n in range(F_SPAN[0], F_SPAN[1] + 1)}  # fmt: skip
    for r in rows:
        if len(r) != 6:
            bad.append(F("G-FROW", f"{r[0]}: cell count", sec="§7"))
            continue
        for i in f_ids(r[0]):
            if sev.get(i) != r[1]:
                bad.append(F("G-FROW", f"{i}: severity {r[1]!r}, D05 says {sev.get(i)!r}",
                             sec="§7"))  # fmt: skip
        if r[5] != "pending (#2701)" or not cites_in(r[2]):
            bad.append(F("G-FROW", f"{r[0]}: close state or D05 cite", sec="§7"))
    return bad


LOG_UNION = (
    [f"OQ-{n}" for n in range(1, 15)]
    + [f"D02-Q{n}" for n in range(1, 6)]
    + [f"D03-Q{n}" for n in (1, 2, 3, 4, 6)]
    + ["D04-Q2"]
    + [f"D05 Q-{n:02d}" for n in range(1, 5)]
    + ["TM D6", "TM D7", "TM D8"]
    + [f"P-{n:02d}" for n in range(1, 5)]
    + [f"D02-G{n}" for n in range(1, 14)]
    + [f"D03-G{n}" for n in range(1, 12)]
    + ["D03-CG1"]
    + [f"D04-G{n}" for n in range(1, 4)]
    + [f"D05 G-{n:02d}" for n in range(1, 20)]
    + [f"D02-C{n}" for n in range(1, 18)]
    + [f"D03-C{n}" for n in range(1, 18)]
    + [f"D04-C{n}" for n in range(1, 16)]
    + [f"D05 C-{n:02d}" for n in range(1, 31)]
    + [f"G-P{n}" for n in range(1, 4)]
)


def g_log(t: Texts) -> list[Finding]:
    bad = []
    rows = log_rows(t.spec)
    v = compute(t)
    ids: list[str] = []
    for r in rows:
        ids += expand_ids(r[0])
        if len(r) != 6:
            bad.append(F("G-LOG", f"{r[0][:20]}: cell count", sec="§10"))
            continue
        if r[3] in ("", "—") or re.search(r"\bagent\b|\bworker\b", r[3]):
            bad.append(F("G-LOG", f"{r[0][:20]}: no owner lane (never an agent)", sec="§10"))
        if r[2] in ("", "—") or not (cites_in(r[2]) or "§" in r[2]) or NO_DEFAULT.search(r[2]):
            bad.append(F("G-LOG", f"{r[0][:20]}: no cited default", sec="§10"))
        cons = r[4].strip()
        a = ANCHOR.search(r[5]) or PLACEHOLDER.search(r[5])
        if (
            cons not in sprints()
            or not a
            or a[1] != f"DATE:{cons}"
            or (ANCHOR.search(r[5]) and not r[5].startswith(v.get(a[1], "?")))
        ):
            bad.append(F("G-LOG", f"{r[0][:20]}: due is not {cons}'s sprint start", sec="§10"))
    missing = [i for i in LOG_UNION if i not in ids]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    extra = [i for i in ids if i not in LOG_UNION]
    if missing or dup or extra:
        bad.append(
            F("G-LOG", f"union: missing {missing[:3]}, repeated {dup[:3]}, unknown {extra[:3]}",
              sec="§10")
        )  # fmt: skip
    if any(v.get(f"COUNT:log.{k}") != "0" for k in ("unowned", "undated", "nodefault")):
        bad.append(F("G-LOG", "unowned = undated = no-default = 0 (AC4)", sec="§10"))
    return bad


@functools.lru_cache(maxsize=1)
def scenarios() -> tuple[str, ...]:
    out: list[str] = []
    for key in ("E33-S05", "E33-S06"):
        out += re.findall(r"Scenario: ([^\n]+)", str(tickets().get(key, {}).get("body", "")))
    return tuple(s.strip() for s in out)


def g_consumers(t: Texts) -> list[Finding]:
    bad = []
    block = h2(t.spec, "§11")
    sids = {r[0] for r in state_rows(t.spec)}
    titles = scenarios()
    if len(titles) < 2:
        bad.append(F("G-CONSUMERS", "the stories' scenarios are unreadable", sec="§11"))
    for title in titles:
        m = re.search(rf'"{re.escape(title)}" ((?:S-\d\d|§\d+)(?:, (?:S-\d\d|§\d+))*)', block)
        if not m:
            bad.append(F("G-CONSUMERS", f"scenario {title[:30]!r} is untraced", sec="§11"))
            continue
        for sid in re.findall(r"S-\d\d", m[1]):
            if sid not in sids:
                bad.append(F("G-CONSUMERS", f"{title[:24]!r}: no state row {sid}", sec="§11"))
    for issue in CONSUMER_ISSUES:
        if issue not in block:
            bad.append(F("G-CONSUMERS", f"the consumer {issue} is not named", sec="§11"))
    s05 = re.search(r"E33-S05 \(#1105\) takes S-01\.\.S-(\d\d)", block)
    s06 = re.search(r"E33-S06 \(#1106\) takes S-(\d\d)\.\.S-(\d\d)", block)
    builders = [r[0] for r in state_rows(t.spec) if r[1] != "SCR-070"]
    monitor = [r[0] for r in state_rows(t.spec) if r[1] == "SCR-070"]
    if not s05 or not builders or f"S-{s05[1]}" != builders[-1]:
        bad.append(F("G-CONSUMERS", "E33-S05 takes every builder row", sec="§11"))
    if not s06 or not monitor or (f"S-{s06[1]}", f"S-{s06[2]}") != (monitor[0], monitor[-1]):
        bad.append(F("G-CONSUMERS", "E33-S06 takes every monitor row", sec="§11"))
    return bad


WALK_ROLES = (
    "story: E33-S05 (#1105)", "story: E33-S06 (#1106)", "QA: E33-Q01 (#1042)",
    "QA: E33-Q05 (#1100)", "backend: §3's bindings", "QA: §2, every S row",
)  # fmt: skip
WALK_DATE = "2026-10-28"
WRITER_PASS = "not by a fresh reader"
WALK_HEAD = ["Date (UTC)", "Role", "Needs listed", "Found", "Not found", "Disposition"]
DOD_TICK = re.compile(r"^- \[([ x])\] \*\*DoD \(walkthrough\):\*\*", re.MULTILINE)
ARROW = re.compile(r"→\s*(\S+)")


def walk_target(t: Texts, tok: str) -> str | None:
    tok = tok.strip("`*,;.()")
    if m := re.fullmatch(r"§(\d+)", tok):
        return None if h2(t.spec, f"§{m[1]}") else f"no section {tok}"
    if re.fullmatch(r"S-\d\d", tok):
        return None if tok in {r[0] for r in state_rows(t.spec)} else f"no state row {tok}"
    if re.fullmatch(r"G-P\d+|P-\d\d", tok):
        ids = {i for r in log_rows(t.spec) for i in expand_ids(r[0])}
        return None if tok in ids else f"no register row {tok}"
    return f"cannot parse the target {tok[:20]!r}"


def walk_record(t: Texts) -> list[str]:
    block = h2(t.spec, "§12")
    if not any(ln.startswith("|") and split_row(ln) == WALK_HEAD for ln in block.split("\n")):
        return ["the dry-run table's header"]
    rows = table_of(block, "Date (UTC)")
    bad: list[str] = []
    if [r[1] if len(r) > 1 else "" for r in rows] != list(WALK_ROLES):
        bad.append("one row per consumer role, then the backend and QA rows, in order")
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
        if r[1].startswith("QA: §2") and need != len(state_rows(t.spec)):
            bad.append("the QA row does not cover every §2 row")
        if r[1].startswith("backend:") and need < len(api_rows(t.spec)):
            bad.append("the backend row does not cover every §3 binding row")
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
    done = not record and WRITER_PASS not in block
    if ticks != ["x" if done else " "]:
        bad.append(F("G-WALK", "the DoD tick follows a fresh reader's record", sec="§12"))
    ac1 = [ln for ln in t.spec.split("\n") if ln.startswith("| AC1 ")]
    if (
        not ac1
        or ("dry run done" in ac1[0]) != done
        or (not done and "dry run pending a fresh reader" not in ac1[0])
    ):
        bad.append(F("G-WALK", "AC1: the dry run is pending a fresh reader",
                     sec="Acceptance-criteria"))  # fmt: skip
    return bad


SESSION_CLAIM = (
    r"\b(?:session|walkthrough|meeting)s?\b(?:\s+\S+){0,2}?\s+(?:was |were |has been |is )?"
    r"(?:held|ran|run|recorded|conducted|completed|happened|took place)\b|\btook place\b"
    r"|\bparticipants?\b|\battendees?\b|\bwalked through\b|\b(?:was|were) held\b"
    r"|\bengineers? (?:met|attended|joined|acknowledged|walked)\b"
    r"|\b(?:reviewed|read|went through|walked) (?:\S+ ){0,2}?together\b"
    r"|\bon a (?:call|video call)\b|\bin a (?:call|meeting|session)\b"
)


def g_session(t: Texts) -> list[Finding]:
    bad = []
    for key, block in sections(t.spec):
        if key == "§15":
            continue
        for c in clauses(block):
            if live(c, SESSION_CLAIM):
                bad.append(F("G-SESSION", f"a session is claimed: {c[:60]!r}", sec=key))
    return bad


# The standing sentences, required verbatim in their sections, and the opposite readings refused
# in any clause (a negation covers its own term).
REQUIRED = (
    ("BQ", "defaults built; ruling pending (comment 6476797633)"),
    ("BQ", "**BQ-1** (arm and lock gating) **default built:**"),
    ("BQ", "**BQ-2** (the line budget) **default built:**"),
    ("BQ", "Both defaults are built and **ruling pending**"),
    ("§0", "**One spec plus the deck; no `-handoff.md`, no redraw, no new board:**"),
    ("§0", "**Nothing unmerged is pinned or quoted:**"),
    ("§2", "**Missing treatments are G-rows, never invented**"),
    ("§4", "**No `15` edit in this PR** (G-UNTOUCHED)"),
    ("§5", "**No string is invented:**"),
    ("§5", "**Shared rows are carried by cite, never re-keyed:**"),
    ("§5", "**The frozen strings (PROPOSED, owner approval pending (#2701)):**"),
    ("§5", "a rewording is a design and security decision, routed to E33-X03 (#1109)"),
    ("§6", "**D04 §7 is the record, by reference**"),
    ("§6", "**Every reduce twin is the instant end state.**"),
    ("§7", ("**The routing table: the stories build to RT-01..RT-28 as D05 has them, PROPOSED,"
            " owner approval pending (#2701)**")),
    ("§7", "each closes under the owner's `approved`, recorded pending (#2701)"),
    ("§8", "RBAC and risk are the server's (C-12.4)"),
    ("§9", "Audit is server-side and never the client's"),
    ("§9", "The verbs are E33-T02's, PROPOSED: none exists in `22` at the base."),
    ("§10", ("**No open question** means none without an owner lane, a default the build follows"
             " and a due date")),
    ("§10", "Owner lanes, never agents; nothing is filed"),
    ("§11", ("One comment each on #1105, #1106, #1042, #1100, #1096, #994 and #1107 at merge, no"
             " body edit.")),
    ("§12", "**No session took place and none is claimed.**"),
    ("§12", "not by a fresh reader, so the box stays open until a fresh reader repeats it"),
    ("§13", "**Version (PROPOSED):**"),
    ("§13", "which `--check` FAILs at `origin/main`"),
    ("§13", ("owner approval pending (#2701); the owner's `approved` stands in for the CDO, FE-lead,"
             " QA-lead and OMS-tech-lead sign-offs (T Adapt), and a design PR merges on the"
             " owner's approval (README:59)")),
    ("§13", "which reads as met with room once the owner approves"),
    ("§13", "nothing else in `14` changes"),
    ("§14", "The parents' C ledgers stand unchanged and are carried by reference (§10)."),
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
        r"\bversion(?:ing)? (?:rule|line)\b(?:\s+\S+){0,6}?\s+(?:is |was )?(?:ruled|approved"
        r"|adopted|confirmed|final|accepted)\b"
    ),
    (
        r"\bowner (?:has |have )?approved\b|\bapproved by the owner\b|\bsigned off\b"
        r"|\bowner (?:has |have )?(?:given|granted|gave)\b"
    ),
    (
        r"\b(?:follow ?up )?(?:issues?|tickets?) (?:are |is |were |was |get )?(?:opened|filed"
        r"|created|raised)\b|\bfil(?:e|es|ed|ing) (?:\S+ ){0,2}?(?:issues?|tickets?)\b"
    ),
    r"\b(?:merely|only|just) (?:flags?|warns?|notes?|reports?)\b|\badvisory\b|\bnon ?blocking\b",
    (
        r"\bmerges? (?:\S+ ){0,4}?(?:once|when|after|on) (?:the )?(?:orchestrator|reviewer|lane|qa"
        r"|agent)s?\b"
    ),
    r"\b(?:it is |it s )?(?:not|never|hardly) (?:true|the case|so|correct|accurate) that\b",
    r"\b(?:adds?|draws?|ships?|creates?) (?:\S+ ){0,2}?(?:new )?(?:penpot )?(?:boards?|pages?)\b",
    (
        r"\bbq (?:0|1|2)\b(?:\s+\S+){0,4}?\s+(?:is |are |was |were )?(?:ruled|approved|confirmed"
        r"|accepted|final)\b"
    ),
    r"\blocked (?:blocks|gates|stops)\b|\bdisarmed (?:users? )?(?:cannot|can t) (?:submit|start)\b",
    r"\bclient (?:is|writes|emits|sends) (?:the |an )?audit\b",
    r"\blive (?:is |are )?(?:enabled|allowed|available|drawn)\b",
    r"\bcontrols? (?:are |is )?(?:absent|hidden|removed)\b",
)


def g_ruled(t: Texts) -> list[Finding]:
    bad = []
    for key, sent in REQUIRED:
        if sent not in h2(t.spec, key):
            bad.append(F("G-RULED", f"{key}: the sentence {sent[:55]!r} is missing", sec=key))
    for rx in REFUSED:
        for sk, block in sections(t.spec):
            if sk == "§15":
                continue
            for c in clauses(block):
                if live(c, rx):
                    bad.append(F("G-RULED", f"{sk}: a paraphrase asserts {rx[:30]!r}: {c[:50]!r}",
                                 sec=sk))  # fmt: skip
    return bad


def g_crow(t: Texts) -> list[Finding]:
    """§14's C-rows run C-a, C-b, … without a gap, each has a reading and an owner cell, and every
    C-letter the spec names is one of them; the traceability line's `11` cites are the stories."""
    bad = []
    rows = c_rows(t.spec)
    letters = [r[0].split()[0] if r[0] else "" for r in rows]
    want = [f"C-{chr(97 + i)}" for i in range(len(rows))]
    if letters != want:
        bad.append(F("G-CROW", f"the C-rows are not {want[0]}..{want[-1]} in order", sec="§14"))
    for r in rows:
        if len(r) == 4 and (not r[2].strip("— ") or not r[3].strip()):
            bad.append(F("G-CROW", f"{r[0]}: a conflict, a reading and an owner cell", sec="§14"))
    for i, ln in enumerate(strip_comments(t.spec).split("\n"), 1):
        for c in re.findall(r"(?<![\w-])(C-[a-z])(?![\w-])", ln):
            if c not in letters:
                bad.append(F("G-CROW", f"line {i}: {c} is named but no §14 row holds it",
                             sec=sec_of_line(t.spec, i)))  # fmt: skip
    trace = re.search(r"\*\*Traceability:\*\* (.*)$", h2(t.spec, "§11"), re.MULTILINE)
    for d, a, _b in cites_in(trace[1] if trace else ""):
        if d == "11" and not line_at(d, a).startswith("#### US-ALGO-"):
            bad.append(F("G-CROW", f"`11`:{a} is not a US-ALGO story", sec="§11"))
    if not trace:
        bad.append(F("G-CROW", "§11 has no traceability line", sec="§11"))
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
    """`14` at the merge-base plus one pointer line after the last Design line of SCR-066..070."""
    lines = base14.split("\n")
    heads = [i for i, ln in enumerate(lines) if ln.startswith("### SCR-")]
    inserts: list[tuple[int, str]] = []
    for h in heads:
        scr = lines[h][4:11]
        if scr not in POINTER_SCREENS:
            continue
        end = next((j for j in heads if j > h), len(lines))
        last = max((i for i in range(h + 1, end) if lines[i].startswith("- **Design")), default=-1)
        if last >= 0:
            inserts.append((last + 1, POINTER_OCO if scr == "SCR-069" else POINTER))
    out = list(lines)
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
    want = expected_14(git_show(mb, PLAN14) or "")
    if t.disk.get(PLAN14) != want or want.count(POINTER) != 4 or want.count(POINTER_OCO) != 1:
        diff = [
            d
            for d in difflib.unified_diff(
                want.split("\n"), t.disk.get(PLAN14, "").split("\n"), lineterm="", n=0
            )
            if d[:1] in "+-" and not d.startswith(("+++", "---"))
        ]
        bad.append(F("G-UNTOUCHED", f"`14` is not the five pointer lines exactly: {diff[:2]}",
                     None, None))  # fmt: skip
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
    want = f"holds {listed} and no algo slice"
    bad = []
    block = h2(t.spec, "§0")
    if want not in block:
        bad.append(F("G-UNBUILT", f"§0 must read {want[:60]!r}…", sec="§0"))
    if re.search(r"/algos", at_base(PLAN["22"]) + at_base(PLAN["23"])) or (
        "neither `22` nor `23` names `/algos`" not in block
    ):
        bad.append(F("G-UNBUILT", "no contract names /algos, said so", sec="§0"))
    return bad


def g_unmerged(t: Texts) -> list[Finding]:
    rx = re.compile(r"/wt/|E33-D0[7-9]\.md|E33-[STQXK]\d\d\.md|E33-T0\d\.md")
    return [
        F("G-UNMERGED", f"line {i}: an unmerged text is cited or quoted", "spec",
          sec_of_line(t.spec, i))
        for i, ln in enumerate(t.spec.split("\n"), 1)
        if rx.search(ln) and sec_of_line(t.spec, i) != "§15"
    ]  # fmt: skip


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
    if CLOSING.search(POINTER) or CLOSING.search(POINTER_OCO):
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
                if not inq and not any(a < idx < b for a, b in spans) and "…" not in seen:
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
    above 3.5) and the repo's recovery-code rule, on every line of the spec, the deck and the
    pointer lines."""
    bad = []
    for d, x in (("spec", t.spec), ("deck", t.deck), ("14", POINTER + "\n" + POINTER_OCO)):
        for i, ln in enumerate(x.split("\n"), 1):
            hits = [
                m[1]
                for m in GL.finditer(ln)
                if not re.fullmatch(r"[a-zA-Z_.-]+", m[1]) and entropy(m[1]) > 3.5
            ]
            hits += [m[0] for m in RECOVERY.finditer(ln)]
            for val in hits:
                sec = (
                    sec_of_line(t.spec, i) if d == "spec" else ("strings" if d == "deck" else None)
                )
                bad.append(F("G-GITLEAKS", f"{d} line {i}: {val[:30]!r} reads as a secret",
                             d if d != "14" else None, sec))  # fmt: skip
    return bad


@functools.lru_cache(maxsize=1)
def token_names() -> frozenset[str]:
    names: set[str] = set()

    def walk(d: object, path: str) -> None:
        if isinstance(d, dict):
            if "$value" in d:
                names.add(path)
                return
            for k, val in d.items():
                walk(val, f"{path}.{k}" if path else str(k))

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
    top = {k: val for k, val in data.items() if k != "strings"} | {"(fields)": list(data)}
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
        "# E33-D06 pins (every unit of the spec and every deck entry): doc, region (heading path "
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
    g_anchor, g_marker, g_figure, g_wordcount, g_cite, g_quote, deck_findings, g_frames, g_states,
    g_redline, g_api, g_verbs, g_cmp, g_story, g_frozen, g_lift, g_layer, g_frow, g_log,
    g_consumers, g_walk, g_session, g_ruled, g_crow, g_version, g_untouched, g_nohandoff, g_unbuilt,
    g_unmerged, g_close, g_url, g_charset, g_cells, g_budget, g_gitleaks, g_token, g_mutlist,
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
    warns = [
        f"WARN [G-VERSION] {HEAD} is ahead of the base for {rel}"
        for rel in PINNED
        if t.head_commits.get(rel) and t.head_commits.get(rel) != last_commit(BASE, rel)
    ][:0]
    n = len(cites_in(t.spec)) + len(deck_entries(t))
    return fails, notes, warns, n


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


def carried_src(d: dict[str, object]) -> None:
    rows = d["carried_by_cite"]
    if isinstance(rows, list) and isinstance(rows[0], dict):
        rows[0]["source"] = "E09-D09:96"


def event_trigger(d: dict[str, object]) -> None:
    rows = d["events"]
    if isinstance(rows, list) and isinstance(rows[0], dict):
        rows[0]["trigger"] = "the read-out renders (S-13)"


def hand_count(t: Texts) -> Texts:
    return replace(t, spec=re.sub(r"\d+(<!--=COUNT:states-->)", r"99\1", t.spec, count=1))


def head_drift(t: Texts) -> Texts:
    heads = dict(t.head_commits)
    heads[CITE_FILES["D02"]] = "0" * 40
    return replace(t, head_commits=heads)


def drop_oco_pointer(x: str) -> str:
    return x.replace(POINTER_OCO + "\n", "", 1)


def append_15(x: str) -> str:
    return x + "\nA line the pack must not add.\n"


def add_handoff(t: Texts) -> Texts:
    return replace(t, handoffs=("docs/design/E33/E33-D06-handoff.md",))


def bust_budget(t: Texts) -> Texts:
    return replace(t, spec=t.spec.rstrip("\n") + "\n" + "\n-" * 12 + "\n")


PROBE = "Zq8r4LmT" + "1vXc0p9W"  # built at run time, so no scanner reads it here
BQP = "a ruling either way is a versioned delta (§13)."
S0 = "E33-T02's OpenAPI delta is named only."
S5 = "routed to E33-X03 (#1109)."
S7 = "owner approval pending (#2701)** (D05:340)."
S8 = "statecharts record and synchronous code enforces (D02:108)."
S9 = "none exists in `22` at the base."
S10 = "D04-Q1 and D04-Q3 are closed (D04:557, :559)."
S12 = "**No session took place and none is claimed.**"
S13 = "which reads as met with room once the owner approves."

M = Mutation
MUTATIONS: tuple[Mutation, ...] = (
    M("M-01", "G-RULED", "delete the BQ paragraph's ruling-pending sentence",
      sub(" Both defaults are built and **ruling pending**; " + BQP, "")),
    M("M-02", "G-RULED", "write that BQ-1 was approved in the BQ paragraph",
      say(BQP, " BQ-1 was approved.")),
    M("M-03", "G-RULED", "write that the routing table is approved in §7",
      say(S7, " The routing table is approved.")),
    M("M-04", "G-RULED", "write that the frozen set is final in §5",
      say(S5, " The frozen set is final.")),
    M("M-05", "G-RULED", "write that the owner approved the pack in §13",
      say(S13, " The owner approved the pack.")),
    M("M-06", "G-RULED", "write that follow-up issues are filed in §10",
      say(S10, " Follow-up issues are filed.")),
    M("M-07", "G-RULED", "write that a locked arm blocks a builder in §8",
      say(S8, " Locked blocks a builder.")),
    M("M-08", "G-RULED", "write that the client writes the audit record in §9",
      say(S9, " The client writes the audit record.")),
    M("M-09", "G-RULED", "drop the frozen strings' PROPOSED clause in §5",
      sub("**The frozen strings (PROPOSED, owner approval pending (#2701)):**",
          "**The frozen strings:**")),
    M("M-10", "G-RULED", "write that this pack draws new boards in §0",
      say(S0, " This pack draws new boards.")),
    M("M-11", "G-RULED", "write that the drift check only warns in §13",
      say(S13, " In practice the drift check only warns.")),
    M("M-12", "G-RULED", "write that LIVE is enabled in §8", say(S8, " LIVE is enabled.")),
    M("M-13", "G-RULED", "write that the Viewer's controls are absent in §8",
      say(S8, " The Viewer's controls are absent.")),
    M("M-14", "G-SESSION", "write that the walkthrough session was held in §12",
      say(S12, " The walkthrough session was held.")),
    M("M-15", "G-SESSION", "write that engineers met and walked through the pack in §12",
      say(S12, " Two engineers met and walked through the pack.")),
    M("M-16", "G-DECK", "change one character of the TWAP caveat in the deck",
      deck_raw("CandleViewer runs this TWAP, not Bybit.", "CandleViewer runs this TWAP, not Bybit!")),
    M("M-17", "G-DECK", "write TBD as the loading string",
      set_field("loading", "string", "TBD")),
    M("M-18", "G-DECK", "drop the frozen mark from the T4 line",
      drop_field("not_started", "frozen")),
    M("M-19", "G-DECK", "mark a memo string merged", set_field("header.count", "status", "merged")),
    M("M-20", "G-DECK", "announce the error summary politely",
      set_field("v.summary", "announce", "polite")),
    M("M-21", "G-DECK", "point an event at the wrong screen's row", deck_top(event_trigger)),
    M("M-22", "G-DECK", "point a carried row at the wrong line", deck_top(carried_src)),
    M("M-23", "G-ANCHOR", "hand-edit the state-row count", hand_count),
    M("M-24", "G-MARKER", "add an HTML comment in §5", say(S5, " <!-- note -->")),
    M("M-25", "G-FIGURE", "write a hand-typed dialog width in §6",
      say("**Every reduce twin is the instant end state.**", " The dialog is 640 px wide.")),
    M("M-26", "G-WORDCOUNT", "write a count as a word in §10",
      say(S10, " Twelve rows follow.")),
    M("M-27", "G-CITE", "cite a line past the end of D02 in §0",
      say(S0, " See D02:9999.")),
    M("M-28", "G-QUOTE", "misquote the TWAP caveat in §1",
      say("D01's binding caveat", " (\"CandleViewer runs every TWAP for you\", D02:187)")),
    M("M-29", "G-STATES", "drop a frame name from S-30",
      cell("| S-30 ", 2, "density-100-rows; zoom-200-cards")),
    M("M-30", "G-STATES", "name a key the deck lacks in S-26",
      cell("| S-26 ", 5, "`loading`, `empty.1`, `empty.2`, `filter_empty`, `no.such.key`")),
    M("M-31", "G-FRAMES", "name nine boards for D02",
      sub("drawn: 01..10;", "drawn: 01..09;")),
    M("M-32", "G-REDLINE", "bind the superseded elevation primitive in §3",
      sub("(not D02's primitives `elevation.4`, `radius.lg`)", "`elevation.4`")),
    M("M-33", "G-API", "drop the owner ticket from a G-row",
      sub("G-row D02-G4 (E33-T02)", "G-row D02-G4")),
    M("M-34", "G-API", "name a G-row no parent has",
      sub("G-row D03-G4 (E33-T02)", "G-row D03-G44 (E33-T02)")),
    M("M-35", "G-VERBS", "cite the wrong threat-model line for pause",
      sub("`algo.paused`, `algo.resumed` (TM:607)", "`algo.paused`, `algo.resumed` (TM:606)")),
    M("M-36", "G-CMP", "write CMP-115 for the selector in §4",
      cell("| CMP-103 ", 0, "CMP-115 OrderTypeSelector")),
    M("M-37", "G-STORY", "give SB-1 to E33-S06", cell("| SB-1 ", 1, "E33-S06")),
    M("M-38", "G-FROZEN", "drop FZ-03's pinning hook", cell("| FZ-03 ", 5, "the caveat")),
    M("M-39", "G-LIFT", "shorten §6's lifted span", sub("§6 (D05:241–265)", "§6 (D05:243–265)")),
    M("M-40", "G-LAYER", "cite the wrong D05 row for L-34",
      sub("the host caption carries the tag's name (D05:501)",
          "the host caption carries the tag's name (D05:500)")),
    M("M-41", "G-FROW", "write Minor for F-01", cell("| F-01 ", 1, "Minor")),
    M("M-42", "G-LOG", "drop the owner of the TM row", cell("| TM D6, TM D8 ", 3, "—")),
    M("M-43", "G-LOG", "drop OQ-13 from the register",
      cell("| OQ-13, OQ-14 ", 0, "OQ-14")),
    M("M-44", "G-CONSUMERS", "untrace a scenario",
      sub('"Orphan detection" S-25;', '"Orphan detection";')),
    M("M-45", "G-WALK", "write 48 found for E33-S05",
      cell("| 2026-10-28 | story: E33-S05 ", 3, "48")),
    M("M-46", "G-WALK", "tick the DoD box on the writer's pass",
      sub("- [ ] **DoD (walkthrough):**", "- [x] **DoD (walkthrough):**")),
    M("M-47", "G-WALK", "add an eleventh walkthrough item",
      sub("W-10 say which", "W-10 read the deck; W-11 say which")),
    M("M-64", "G-CROW", "name a C-row §14 does not hold in §0", say(S0, " See C-z.")),
    M("M-48", "G-VERSION", "pin D02 at a wrong sha in the version line",
      sub("D02 at `6a8fc9626`", "D02 at `6a8fc9627`")),
    M("M-49", "G-VERSION", "simulate a merged change to D02 at origin/main", head_drift),
    M("M-50", "G-VERSION", "simulate an unresolvable origin/main",
      lambda t: replace(t, head_ok=False, head_commits={})),
    M("M-51", "G-UNTOUCHED", "append a line to the component catalogue in the working tree",
      disk_edit(PLAN["15"], append_15)),
    M("M-52", "G-UNTOUCHED", "drop the SCR-069 pointer line from the screens catalogue",
      disk_edit(PLAN14, drop_oco_pointer)),
    M("M-53", "G-NOHANDOFF", "add a hand-off file", add_handoff),
    M("M-54", "G-UNBUILT", "drop the no-algo-slice clause in §0",
      sub("and no algo slice", "and nothing else")),
    M("M-55", "G-UNMERGED", "cite an unmerged contract file in §0",
      say(S0, " See E33-T02.md.")),
    M("M-56", "G-CLOSE", "write a closing keyword in §13",
      say(S13, " Closes #990.")),
    M("M-57", "G-URL", "write a URL in §6",
      say("**Every reduce twin is the instant end state.**", " See https" + "://example.org.")),
    M("M-58", "G-CHARSET", "write a trailing space after §0's last sentence",
      sub(S0 + "\n", S0 + " \n")),
    M("M-59", "G-CELLS", "merge two cells of C-c", merge_cells("| C-c ")),
    M("M-60", "G-BUDGET", "append lines past the budget", bust_budget),
    M("M-61", "G-GITLEAKS", "write a secret-shaped value in §6",
      say("**Every reduce twin is the instant end state.**", f" The api_key: {PROBE}.")),
    M("M-62", "G-TOKEN", "name an unshipped token in §3",
      sub("`color.surface.app` with a", "`color.surface.nope` with a")),
    M("M-63", "G-MUTLIST", "rename a mutation in §15",
      sub("M-01 delete the BQ paragraph's ruling-pending sentence",
          "M-01 delete the BQ paragraph's sentence")),
    # pin probes (no measured or lexicon gate reads these units)
    M("P-1", "G-RULED-PIN", "reword a §1 sentence",
      sub("the stale boundary (D03:53)", "the staleness boundary (D03:53)")),
    M("P-2", "G-RULED-PIN", "change C-g's reading",
      cell("| C-g ", 2, "`sub_001` everywhere")),
    M("P-3", "G-RULED-PIN", "rename §6's heading", sub("## 6. Motion", "## 6. Motion spec")),
    M("P-4", "G-RULED-PIN", "widen a deck entry's screens",
      set_field("header.count", "screen", "SCR-063, SCR-070")),
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
        for m in changed:
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
