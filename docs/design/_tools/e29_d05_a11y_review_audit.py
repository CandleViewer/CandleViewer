#!/usr/bin/env python3
"""E29-D05 (#824) audit: the accessibility design review of the blotters (spec, optional hand-off).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the token JSON (`themes.json` layering: dark = primitives
+ semantic-dark, light = + semantic-light, hc = + semantic-hc), the plan texts, the merged E29
specs D01..D04 and their hand-off, D02's grid tool (its `PAIRS` literal, parsed, never imported),
the reserved-key fixture of E11-D07, the keymap and the a11y preference model; then this ticket's
spec (and a hand-off, when `--handoff` names one) from the working tree, and the working-tree
files the review must leave untouched (compared with `git merge-base HEAD origin/main`).

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: COUNT (boards and renders at
   the base, the spec's own table rows, the fixture's matches per K row), BAR / TIME / RATE / GEOM
   / LEN (parsed from the cited lines or the token JSON), CONTRAST (WCAG 2.x, two decimals
   rounded half up, truncated instead when rounding would lift a value onto a bar it fails),
   CVD (CIE76 dE, the minimum over three themes and three simulations, one decimal truncated),
   HEX (a resolved token). `--fill` writes `VALUE<!--=KEY-->`;
   `--check` re-derives every anchored value (G-ANCHOR, with a left boundary: the value must not be
   the tail of a longer number) and FAILs on a figure typed by hand.
2. **Lexicon gates first.** Each reads every rendered unit (table rows cell by cell, bullets,
   paragraphs, headings, fence lines) after the comment strip, NFKC, markup dropped, dashes to
   spaces, lower case; quoted copy is not a claim; a negation covers its term within five words and
   a list coordinated after it. The mutation table (§15) and the A table's Old cells are skipped.
   Synonym sets, not single phrases, carry each ruled behaviour (`*_TERM` constants), and a
   need-check keeps each ruled sentence's wording; every paraphrase the adversary lens found
   (probes X-42..) must trip its gate with the pins rewritten. The pins stay the backstop for
   forms no lexicon lists. Structure first: G-CELLS fails a table row whose cell count differs
   from its header's (GFM drops the cells past the header).
3. **Then the measured and table gates** (column by column), then the cites, then the pins.
4. **Pins (G-RULED-PIN).** Whole-document default-deny: every heading, table row (by lead cell),
   rule line, prose sentence (`s<k>`) and fenced block, keyed by heading path + occurrence `#n`,
   with each region's line shape (one tag per line: `.` blank, `h`, `t`, `r`, `b`, `n`, `p`, `f`;
   prose, bullet and numbered tags carry their sentence count, an indent its `>n`).
   `--repin-ruled` is the only writer. NOTE demotion: a pin finding in a section another gate
   already FAILs prints as a NOTE, so one wrong form yields one FAIL.
5. **--self-test** applies every §15 mutation in memory (plus the tool's X, P and N probes; a
   mutation may also pass a hand-off, which RULED BQ-31 forbids under any name): each
   must add exactly one FAIL from the gate it names (N probes none), and every text is restored
   byte-identically (sha256 in memory and on disk). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e29_d05_a11y_review_audit.py --check [SPEC] [--handoff F] [--json]
      [--fill]
  python3 -I docs/design/_tools/e29_d05_a11y_review_audit.py --self-test
  python3 -I docs/design/_tools/e29_d05_a11y_review_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import ast
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
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "802e99f575"  # every cite was read here (the spec's Inputs line)
HEAD = "origin/main"  # drift is reported against this ref (WARN, never FAIL)
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E29/E29-D05.md"
HAND_DEFAULT = "docs/design/E29/E29-D05-handoff.md"
RULED_PIN_TXT = "docs/design/_tools/e29_d05_ruled_pins.txt"
TOKENS_REL = "packages/ui/tokens"
FIXTURE_REL = "docs/design/_tools/e11_d07_sr_reserved_keys.json"
D02_TOOL_REL = "docs/design/_tools/e29_d02_grid_audit.py"
D03_TOOL_REL = "docs/design/_tools/e29_d03_audit.py"  # named at D03:428; absent at the base (F-08)
IMG_REL = "docs/design/E29/img"
FEATURES_REL = "apps/web/src/features"
UI_SRC_REL = "packages/ui/src"
RULING_ID = "6433580460"
BQ_LIST_ID = "6433450480"
PENDING = "PROPOSED, owner approval pending (#2701)"
SPEC_LINE_BUDGET = 700  # "spec <= ~600" against RULED BQ-1 "about 900": the folds need ~690
HAND_LINE_BUDGET = 150  # standing condition: "hand-off <= ~150"
HEADROOM_PCT = 10  # RULED BQ-27 (as proposed): a slot line under 10 % headroom is flagged

CITE_FILES = {
    "D01": "docs/design/E29/E29-D01.md",
    "D02": "docs/design/E29/E29-D02.md",
    "D03": "docs/design/E29/E29-D03.md",
    "D04": "docs/design/E29/E29-D04.md",
    "D04H": "docs/design/E29/E29-D04-handoff.md",
    "KM": "apps/web/src/keymap/keymap.json",
    "RK": "apps/web/src/keymap/reserved-keys.json",
    "PREF": "apps/web/src/features/a11y-preferences/model.ts",
    "README": "docs/design/README.md",
    "E40R": "docs/design/a11y/e40-alerts-a11y-review.md",
    "E29.json": "docs/plan/backlog/E29.json",
}
# never edited by this ticket (RULED BQ-3; the brief's standing conditions); compared with the
# merge-base of HEAD and origin/main, never a fixed sha
UNTOUCHED = ("05", "06", "14", "15", "16", "D01", "D02", "D03", "D04", "D04H", "KM", "RK")
UNMERGED = ("E29-D06", "E29-D07", "E10-D04", "E05-D03")  # named only, never cited or quoted
CONSUMERS = ("#825", "#1149", "#911", "#912", "#979", "#1028", "#1146", "#1029")  # RULED BQ-31
STORIES = ("#911", "#912", "#979", "#1028", "#825", "#1149")  # the body names them (BQ-1)

THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SIMS = ("protanopia", "deuteranopia", "tritanopia")

# the clause checklist of RULED BQ-6 (one row each in §3)
CLAUSES = (
    "3.1.1",
    "3.1.4",
    "3.1.6",
    *(f"3.3.{n}" for n in range(1, 7)),
    *(f"3.4.{n}" for n in range(1, 11)),
    "4.1",
    "4.2",
    "4.3",
    "4.4",
    *(f"5.{n}" for n in range(1, 8)),
    "6.2a",
    "6.2b",
    "6.2c",
    "6.2d",
    "6.5",
    "7.1",
    "7.2",
    "7.3",
    "7.4",
    "14:0.5.1",
    "14:0.5.5",
    "14:0.5.6",
    "02:180",
)
# the WCAG 2.2 cross-walk of RULED BQ-6 (one row each in §4)
CRITERIA = (
    "1.3.1",
    "1.3.2",
    "1.4.1",
    "1.4.3",
    "1.4.4",
    "1.4.10",
    "1.4.11",
    "1.4.12",
    "1.4.13",
    "2.1.1",
    "2.1.2",
    "2.2.1",
    "2.2.2",
    "2.3.1",
    "2.4.1",
    "2.4.3",
    "2.4.6",
    "2.4.7",
    "2.4.11",
    "2.5.3",
    "2.5.7",
    "2.5.8",
    "3.2.1",
    "3.2.2",
    "3.2.6",
    "3.3.1",
    "3.3.4",
    "4.1.2",
    "4.1.3",
    "2.3.3 (AAA)",
    "2.4.13 (AAA)",
)
VERDICT = re.compile(
    r"^(?:compliant|at risk|non-compliant|out of scope — \S.*"
    r"|not yet decidable — routed to E29-Q05)$"
)
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
# clauses whose verdict a ruled reading fixes: (verdict, words its row must carry)
CLAUSE_RULED: dict[str, tuple[str, ...]] = {
    "6.2a": ("at risk", "PROPOSED", "shouldAnnounce", "G-05"),  # RULED BQ-19's composition
    "5.5": ("at risk", "F-11"),  # `05`:129 vs the black stale surface, a Major F row (R-3)
}

# RULED BQ-19 (PROPOSED): the routing of every event class; (event pattern, region, new to `05`)
ROUTES: tuple[tuple[str, str, bool], ...] = (
    (r"\border filled\b", "assertive", False),
    (r"\border rejected\b", "assertive", False),
    (r"\boffline\b.*\breconnected\b", "assertive", False),
    (r"\bno sl on\b", "assertive", True),
    (r"\bcrossing into critical\b", "assertive", True),
    (r"\brejected amend\b", "assertive", True),
    (r"\bstale lock\b.*\bkill ?switch lock\b", "assertive", True),
    (r"\bcorrection findings\b", "assertive", True),
    (r"\badl\b.*\bliquidation fill\b", "assertive", True),
    (r"\bpost reconnect summary\b", "assertive", True),
    (r"\breconciling\b.*\bsynced\b.*\bdesync\b", "polite", True),
    (r"\bnear crossing\b", "polite", True),
    (r"\bselection count\b", "polite", True),
    (r"\bconfirmed amend\b", "polite", True),
    (r"\bexport done\b.*\bcould not load\b.*\brevoked\b", "polite", True),
    (r"\bfocused row's changed values\b.*\btotals\b", "polite", True),
    (
        (
            r"\bages\b.*\blast update\b.*\bno sl timer\b.*\bcountdown\b"
            r".*\bvalue flashes\b.*\bother fills\b"
        ),
        "none",
        True,
    ),
    (r"\bposition auto flattened by the risk engine\b", "assertive", False),  # `05`:148
    (r"\brule triggered\b.*\bdemo/live switch confirmed\b", "assertive", False),  # `05`:148
    (r"\brisk lockout\b", "assertive", True),  # D01:410, beyond the ruled list (Q-07)
)

# ---------------------------------------------------------------------------- regexes

PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
FIGURE = re.compile(
    r"(?<![\w.,:#/>{-])(\d+(?:[.,]\d+)*)\s?(ms|s|hz|px|%|:1)(?![\w])"
    r"|(?<![\w.,:#/>{-])(\d+)\s?×\s?(\d+)(?![\w])",
    re.IGNORECASE,
)
COUNTED = re.compile(
    r"(?<![\w.,:#/>{-])(\d+)\s+(?:boards?|renders?|findings?|clauses?|criteria|pairs?|"
    r"mutations?|questions?|signals?|strings?|lines?|rows?|cells?|units?)\b",
    re.IGNORECASE,
)
CITE_GROUP = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:D0[1-4]H?|README|E\d\d-D\d\d)\b)) ?"
    r":(?P<first>\d+(?:[–-]\d+)?)(?P<more>(?:(?:\s*\([^()\n]*\))?,\s*:\d+(?:[–-]\d+)?)*)"
)
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*(?:[\w.-]+/[\w.-]+)?#\d+",
    re.IGNORECASE,
)
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]", re.IGNORECASE)

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


@functools.lru_cache(maxsize=32)
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


def plan_rel(nn: str) -> str | None:
    names = [n for n in git_out("ls-tree", "--name-only", BASE, "docs/plan/").split("\n") if n]
    hits = [n for n in names if n.startswith(f"docs/plan/{nn}-")]
    return min(hits) if hits else None


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


def base_line(cid: str, n: int) -> str:
    rel = cite_path(cid)
    lines = at_base(rel).split("\n") if rel else []
    if not 1 <= n <= len(lines):
        raise SystemExit(f"FAIL parse: {cid}:{n} is not a line at {BASE}")
    return lines[n - 1]


@functools.lru_cache(maxsize=1)
def fork_point() -> str:
    """`git merge-base HEAD origin/main` (G-UNTOUCHED's reference; never a fixed sha)."""
    sha = git_out("merge-base", "HEAD", HEAD).strip()
    if not sha:
        raise SystemExit("FAIL parse: no merge-base of HEAD and origin/main")
    return sha


def ls_tree(rev: str, rel: str) -> list[str]:
    return [n for n in git_out("ls-tree", "--name-only", rev, rel + "/").split("\n") if n]


# ---------------------------------------------------------------------------- the comment strip

# ONE pattern over the whole text, DOTALL: `<!-->` and `<!--->` close at once, a comment closes at
# `-->` or `--!>`, and an unclosed comment runs to the end of the text.
COMMENT = re.compile(r"<!--(?:>|->|.*?--!?>|.*\Z)", re.DOTALL)
_HIDDEN = re.compile(COMMENT.pattern + r"|[\u00ad\u200b-\u200d\u2060\ufeff]", re.DOTALL)


def strip_comments(text: str) -> str:
    return _HIDDEN.sub("", text)


# ---------------------------------------------------------------------------- markdown

FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^(#{1,6}) (.*)$")


def fenced(lines: list[str]) -> list[bool]:
    """For each line, whether it is a fence line or inside a fenced block (kind and length are
    read from the marker after the indent; an unclosed fence runs to the end)."""
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


def split_row(line: str) -> list[str]:
    body = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def is_rule(line: str) -> bool:
    return re.match(r"^\s*\|\s*:?-{1,}", line) is not None and set(line.strip()) <= set("|-: ")


def table(block: str) -> list[list[str]]:
    """The data rows of the first table in `block` (no header, no rule)."""
    out: list[list[str]] = []
    lines = block.split("\n")
    started = False
    for i, ln in enumerate(lines):
        if not re.match(r"^ {0,3}\|", ln):
            if started:
                break
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if is_rule(ln) or is_rule(nxt):
            started = True
            continue
        started = True
        out.append(split_row(ln))
    return out


def rows_by(block: str) -> dict[str, list[str]]:
    return {r[0]: r for r in table(block) if r}


def row_key(cell: str) -> str:
    k = re.sub(r"[*_`]", "", cell).strip()
    return re.sub(r"^([A-Za-z]+)\s+(\d+)$", r"\1-\2", k)


def pin_norm(text: str) -> str:
    """The exact text, NFKC with whitespace collapsed (Prettier's table padding is not a change)."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sec_id(heading: str) -> str:
    """A `##` section's key: the first three words of its rendered heading."""
    text = PLACEHOLDER.sub(" ", strip_comments(heading)).lstrip("# ")
    return " ".join(pin_norm(text).split()[:3]) or "(top)"


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


def h2_of(text: str, head: str) -> str:
    """The `##` section key of the heading that starts with `head`."""
    lines = text.split("\n")
    fence = fenced(lines)
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if m and not fence[i] and m[2].startswith(head):
            return h2_at(text, i + 1)
    return "(top)"


# ---------------------------------------------------------------------------- normalisation

_DASHES = re.compile(r"[\u2010-\u2015\u2212-]")
_MARKUP = re.compile(r"[*`]")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EMPH = re.compile(r"(?<!\w)_+|_+(?!\w)")


def norm_text(text: str) -> str:
    """Rendered words only: comments and markup dropped, NFKC, dashes to spaces, lower case."""
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
    rf"\b(?:it|this)(?: \w+){{0,2}}? (?:is|was|be|['’]s) (?:\w+ )?{FALSITY}"
    r" (?:that|to (?:say|claim|state|suggest|write)(?: that)?)\b"
)


def live(clause: str, term: str, keep_quotes: bool = False) -> bool:
    """`term` asserted in `clause` once every negated mention is removed. A negation covers its
    own term (at most five words before it) and a list of its terms coordinated after it; a double
    negation asserts its term; a falsity frame inverts what follows it."""
    t = norm_text(clause) if keep_quotes else norm_text(unquote(clause))
    f = FLIP.search(t)
    if f:
        rest = t[f.end() :]
        return _live(t[: f.start()], term) or (
            re.search(term, rest) is not None and not _live(rest, term)
        )
    return _live(t, term)


def _live(t: str, term: str) -> bool:
    t = DOUBLE_NEG.sub(" ", re.sub(r"\bno sl\b", "nosl", t))
    sep = r"(?:,\s*(?:or\s+|nor\s+|and\s+)?|\s+(?:or|nor|and)\s+)"
    listed = rf"(?:{sep}(?:an? )?(?:{term})\w*)*"
    item = rf"(?:[^\s,;]+\s+){{0,2}}[^\s,;]+{sep}"
    near_ = r"(?:\s+\S+){0,5}?\s+\W?(?:an? )?(?:[\w-]+\.)*"
    in_list = rf"(?:\s+\S+){{0,2}}?\s+(?:{item})+(?:[^\s,;]+\s+){{0,2}}?(?:[\w-]+\.)*"
    t = re.sub(rf"\b{NEG_WORD}\b(?:{near_}|{in_list})(?:{term}){listed}", " ", t)
    return re.search(term, t) is not None


SENTENCE = re.compile(r";\s|(?<=[.!?])\s+|\s—\s")


def sentences(text: str) -> list[str]:
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
    doc: str
    sec: str
    text: str


MUTATION_HEAD = "15. The mutation list"  # its rows describe the violations they plant
A_TABLE_HEAD = "16.4 Copy-ready amendments"  # its Old cells are verbatim base text


def lex_units(doc: str, text: str) -> list[LexUnit]:
    """Every unit a lexicon gate reads, rendered: each table row (cells joined by " | "), each
    bullet or numbered item, each paragraph, heading and fence line, with its `##` section."""
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
                skip = m[2].startswith(MUTATION_HEAD)
            old_col = m[2].startswith(A_TABLE_HEAD)
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
                    cells = cells[:3] + cells[4:]
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
    units: list[LexUnit], term: str, near: str = "", keep_quotes: bool = False
) -> list[tuple[str, str, str]]:
    """(clause, doc, section) for every clause asserting `term` (naming `near`, when given)."""
    hits: list[tuple[str, str, str]] = []
    for u in units:
        for c in clauses(u.text):
            scope = norm_text(c if keep_quotes else unquote(c))
            if near and not re.search(near, scope):
                continue
            if live(c, term, keep_quotes):
                hits.append((norm_text(c)[:70], u.doc, u.sec))
    return hits


# ---------------------------------------------------------------------------- tokens and colour


@functools.lru_cache(maxsize=8)
def token_file(name: str) -> dict[str, object]:
    data = json.loads(at_base(f"{TOKENS_REL}/{name}.tokens.json"))
    return {k: v.get("$value") for k, v in data.items() if isinstance(v, dict)}


@functools.lru_cache(maxsize=4)
def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        merged.update(token_file(f))
    return merged


def themes_json_ok() -> bool:
    data = json.loads(at_base(f"{TOKENS_REL}/themes.json"))
    got = {str(t["name"]): tuple(t["sets"]) for t in data["themes"]}
    want = {"dark": THEMES["dark"], "light": THEMES["light"], "high-contrast": THEMES["hc"]}
    return got == want


def resolve(theme: str, name: str) -> str:
    tokens = load_theme(theme)
    if name not in tokens:
        return "MISSING"
    value, hops = tokens[name], 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1], "MISSING"), hops + 1
    return value if isinstance(value, str) else json.dumps(value)


def hex_of(theme: str, name: str) -> str | None:
    """A token's opaque hex in `theme`; `a@0.25/b` composites `a` at that alpha over `b`."""
    if "@" in name:
        top, rest = name.split("@", 1)
        alpha_s, under = rest.split("/", 1)
        a, b = hex_of(theme, top), hex_of(theme, under)
        if a is None or b is None:
            return None
        alpha = float(alpha_s)
        out = []
        for x, y in zip(rgb(a), rgb(b), strict=True):
            out.append(f"{max(0, min(255, round(alpha * x + (1 - alpha) * y))):02X}")
        return "#" + "".join(out)
    v = resolve(theme, name)
    return v.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else None


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


def round2(r: float) -> str:
    """Two decimals, rounded half up as D02, D03 and D04 print them, except that a value under a
    bar is truncated rather than rounded up onto it (never shown passing a bar it fails)."""
    up = math.floor(r * 100 + 0.5 + 1e-9) / 100
    if any(r < b <= up for b in (3.0, 4.5, 7.0)):
        up = math.floor(r * 100 + 1e-9) / 100
    return f"{up:.2f}"


def trunc1(x: float) -> str:
    return f"{math.floor(x * 10 + 1e-9) / 10:.1f}"


def ratio(theme: str, fg: str, bg: str) -> float | None:
    a, b = hex_of(theme, fg), hex_of(theme, bg)
    return None if a is None or b is None else contrast(a, b)


# The Brettel (1997) / Vienot projection for protan and deutan and the Machado, Oliveira &
# Fernandes 2009 tritan matrix at severity 1.0, carried as constants (the E12-D06 port, gated
# there against `docs/research/_tools/cvd_simulate.py`); CVD_PINNED is this tool's self-test.
RGB_TO_LMS = (
    (17.8824, 43.5161, 4.11935),
    (3.45565, 27.1554, 3.86714),
    (0.0299566, 0.184309, 1.46709),
)
LMS_TO_RGB = (
    (0.0809444479, -0.130504409, 0.116721066),
    (-0.0102485335, 0.0540193266, -0.113614708),
    (-0.000365296938, -0.00412161469, 0.693511405),
)
PROJECTIONS: dict[str, tuple[float, ...]] = {
    "protanopia": (0.0, 2.02344, -2.52581, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    "deuteranopia": (1.0, 0.0, 0.0, 0.494207, 0.0, 1.24827, 0.0, 0.0, 1.0),
}
TRITAN_MACHADO = (
    1.255528,
    -0.076749,
    -0.178779,
    -0.078411,
    0.930809,
    0.147602,
    0.004733,
    0.691367,
    0.303900,
)
CVD_PINNED = {
    "#2EBD59": ("#B4B458", "#A3A35D", "#00B9A6"),
    "#E5484D": ("#6B6B4E", "#8F8F44", "#FB194B"),
}


def matvec(flat: tuple[float, ...], v: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        flat[0] * v[0] + flat[1] * v[1] + flat[2] * v[2],
        flat[3] * v[0] + flat[4] * v[1] + flat[5] * v[2],
        flat[6] * v[0] + flat[7] * v[1] + flat[8] * v[2],
    )


def flat3(m: tuple[tuple[float, float, float], ...]) -> tuple[float, ...]:
    return tuple(x for row in m for x in row)


def linear_to_srgb(c: float) -> float:
    s = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return max(0.0, min(1.0, s)) * 255.0


def simulate(hex6: str, deficiency: str) -> str:
    lin = tuple(srgb_to_linear(v) for v in rgb(hex6))
    v3 = (lin[0], lin[1], lin[2])
    if deficiency == "tritanopia":
        lin2 = matvec(TRITAN_MACHADO, v3)
    else:
        lms = matvec(flat3(RGB_TO_LMS), v3)
        lin2 = matvec(flat3(LMS_TO_RGB), matvec(PROJECTIONS[deficiency], lms))
    return "#" + "".join(f"{max(0, min(255, round(linear_to_srgb(c)))):02X}" for c in lin2)


def lab(hex6: str) -> tuple[float, float, float]:
    r, g, b = (srgb_to_linear(v) for v in rgb(hex6))
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e76(a: str, b: str) -> float:
    la, lb = lab(a), lab(b)
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(la, lb, strict=True)))


def cvd_port_problems() -> list[str]:
    bad: list[str] = []
    for src, want in CVD_PINNED.items():
        got = tuple(simulate(src, s) for s in SIMS)
        if got != want:
            bad.append(f"{src} simulates to {got}, pinned {want}")
    return bad


# ---------------------------------------------------------------------------- the contrast union


@dataclass(frozen=True)
class Pair:
    fg: str
    bg: str
    role: str  # text | non-text | rejected | decorative | exempt | measured
    src: str  # D02 | D03 | D04 | composed
    printed: tuple[str, ...] = ()  # the source's printed dark / light / hc values, when it prints


def d02_pairs() -> list[Pair]:
    """D02 §13's pairs: the `PAIRS` literal of its tool at the base, parsed (never imported)."""
    tree = ast.parse(at_base(D02_TOOL_REL))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PAIRS":
            raw = ast.literal_eval(node.value)
            break
    else:
        raise SystemExit(f"FAIL parse: no PAIRS in {D02_TOOL_REL}")
    out: list[Pair] = []
    for _el, fg, bg, role in raw:
        r = str(role)
        role_n = "rejected" if r.startswith("rejected") else r
        out.append(Pair(f"color.{fg}", f"color.{bg}", role_n, "D02"))
    return out


# D03 §7, one entry per measured cell (its table names tokens by short forms): (line at the base,
# fg tokens in the cell's order, bg, roles in the same order). "x" = rejected, "e" = exempt.
_T = "color.text."
D03_ROWS: tuple[tuple[int, tuple[str, ...], str, str], ...] = (
    (432, (_T + "primary",), "color.surface.raised", "t"),
    (433, (_T + "secondary",), "color.surface.raised", "t"),
    (434, (_T + "tertiary",), "color.surface.raised", "t"),
    (435, (_T + "link",), "color.surface.raised", "t"),
    (
        436,
        (_T + "primary", _T + "secondary", _T + "tertiary", _T + "link"),
        "color.surface.overlay",
        "tttt",
    ),
    (437, (_T + "primary", _T + "secondary", _T + "tertiary"), "color.surface.canvas", "ttt"),
    (438, ("color.focus.ring",) * 3, "", "nnn"),
    (439, (_T + "tertiary", _T + "secondary"), "color.surface.selected", "xt"),
    (440, ("color.buy.default", "color.sell.default"), "color.surface.raised", "nn"),
    (441, ("color.status.warning.strong",), "color.surface.raised", "n"),
    (442, ("color.env.live", "color.env.demo"), "color.surface.raised", "nn"),
    (
        443,
        (_T + "primary", "color.status.info.strong", _T + "link", "color.focus.ring"),
        "color.status.info.subtle",
        "tntn",
    ),
    (
        444,
        (_T + "primary", "color.status.warning.strong", _T + "link", _T + "secondary"),
        "color.status.warning.subtle",
        "tntt",
    ),
    (445, (_T + "tertiary", "color.action.primary.default"), "color.status.warning.subtle", "xx"),
    (
        446,
        (_T + "primary", "color.status.danger.strong", _T + "link", _T + "secondary"),
        "color.status.danger.subtle",
        "tntt",
    ),
    (447, (_T + "tertiary", _T + "secondary"), "color.status.danger.subtle", "tt"),
    (
        448,
        (_T + "primary", "color.status.success.strong", _T + "link", _T + "secondary"),
        "color.status.success.subtle",
        "tntt",
    ),
    (449, ("color.focus.ring",) * 3, "", "nnn"),
    (
        450,
        (
            "color.data-confidence.stale.text",
            "color.data-confidence.stale.indicator",
            _T + "tertiary",
        ),
        "color.data-confidence.stale.surface",
        "tnt",
    ),
    (451, ("color.action.secondary.default",), "color.surface.canvas", "e"),
)
# rows 438 and 449 measure one token on several fills, in the cell's order
D03_MULTI_BG = {
    438: ("color.surface.raised", "color.surface.overlay", "color.surface.canvas"),
    449: (
        "color.status.warning.subtle",
        "color.status.danger.subtle",
        "color.status.success.subtle",
    ),
}
ROLE_OF = {"t": "text", "n": "non-text", "x": "rejected", "e": "exempt"}


def d03_cells(line: str) -> list[list[str]]:
    """The Dark, Light and HC cells of a D03 §7 row, each split into its values (" / ", " → ")."""
    cells = split_row(line)[-3:]
    return [re.findall(r"\d+\.\d+", c) for c in cells]


def d03_pairs() -> list[Pair]:
    lines = at_base(CITE_FILES["D03"]).split("\n")
    out: list[Pair] = []
    for ln_no, fgs, bg, roles in D03_ROWS:
        vals = d03_cells(lines[ln_no - 1])
        for k, fg in enumerate(fgs):
            b = D03_MULTI_BG[ln_no][k] if ln_no in D03_MULTI_BG else bg
            printed = tuple(v[k] if k < len(v) else "" for v in vals)
            out.append(Pair(fg, b, ROLE_OF[roles[k]], "D03", printed))
    return out


def flash_alpha() -> str:
    m = re.search(r"at peak (0\.\d+)", strip_comments(base_line("D04", 352)))
    if not m:
        raise SystemExit("FAIL parse: D04:352 flash peak opacity")
    return m[1]


def d04_pairs() -> list[Pair]:
    block = section(at_base(CITE_FILES["D04"]), "5. Tokens and contrast")
    out: list[Pair] = []
    for r in table(block):
        if len(r) < 7 or not r[0].startswith("`"):
            continue
        fg = r[1].strip("`")
        bgm = re.findall(r"`([^`]+)`", r[2])
        bg = f"{bgm[0]}@{flash_alpha()}/{bgm[1]}" if " over " in r[2] else bgm[0]
        role = {"text": "text", "non-text": "non-text"}.get(r[3], "measured")
        printed = tuple((re.findall(r"\d+\.\d+", strip_comments(c)) or [""])[0] for c in r[4:7])
        out.append(Pair(fg, bg, role, "D04", printed))
    return out


# the compositions no single spec measured (RULED BQ-24); keys are the spec's CONTRAST anchors
COMPOSED: dict[str, tuple[str, str, str]] = {
    "t2.selected": (_T + "secondary", "color.surface.selected", "text"),
    "t2.danger": (_T + "tertiary", "color.status.danger.subtle", "text"),
    "focus.stale": ("color.focus.ring", "color.data-confidence.stale.surface", "non-text"),
    "asof.stale": (_T + "tertiary", "color.data-confidence.stale.surface", "text"),
    "focus.flash": ("color.focus.ring", "", "non-text"),  # bg: D04's flash peak (filled below)
}
HC_PAIRS: dict[str, tuple[str, str]] = {
    "link.raised": (_T + "link", "color.surface.raised"),
    "link.overlay": (_T + "link", "color.surface.overlay"),
    "link.info": (_T + "link", "color.status.info.subtle"),
    "link.warning": (_T + "link", "color.status.warning.subtle"),
    "link.danger": (_T + "link", "color.status.danger.subtle"),
    "link.success": (_T + "link", "color.status.success.subtle"),
    "flatten": (_T + "on-action", "color.status.danger.default"),
}


def flash_bg() -> str:
    return f"color.status.info.subtle@{flash_alpha()}/color.surface.raised"


def composed_pairs() -> list[Pair]:
    out = []
    for fg, bg, role in COMPOSED.values():
        out.append(Pair(fg, bg or flash_bg(), role, "composed"))
    return out


@functools.lru_cache(maxsize=1)
def union() -> tuple[Pair, ...]:
    return tuple(d02_pairs() + d03_pairs() + d04_pairs() + composed_pairs())


def bars() -> dict[str, float]:
    return {k: float(v) for k, v in bar_values().items()}


def bar_for(role: str, theme: str) -> float | None:
    b = bars()
    if role == "text":
        return b["hc"] if theme == "hc" else b["text"]
    if role == "non-text":
        return b["nontext"]
    return None


def measure(p: Pair) -> dict[str, float | None]:
    return {t: ratio(t, p.fg, p.bg) for t in THEMES}


# ---------------------------------------------------------------------------- values


def grab(pattern: str, text: str, what: str) -> str:
    m = re.search(pattern, strip_comments(text), MULTI)
    if not m:
        raise SystemExit(f"FAIL parse: {what} not found ({pattern})")
    return m[1]


@functools.lru_cache(maxsize=1)
def bar_values() -> dict[str, str]:
    return {
        "text": grab(r"≥(\d+(?:\.\d+)?):1", base_line("05", 125), "`05`:125 text bar"),
        "nontext": grab(r"≥(\d+(?:\.\d+)?):1", base_line("05", 126), "`05`:126 non-text bar"),
        "hc": grab(r"≥(\d+(?:\.\d+)?):1 body text", base_line("05", 130), "`05`:130 hc bar"),
    }


def board_counts() -> dict[str, str]:
    names = [Path(n).name for n in ls_tree(BASE, IMG_REL)]
    render = re.compile(r"-(?:greyscale|deuteranopia|protanopia|tritanopia)\.png$")
    out: dict[str, str] = {}
    total = 0
    for d in ("D02", "D03", "D04"):
        n = len([x for x in names if re.match(rf"E29-{d}-\d\d-", x) and not render.search(x)])
        out[f"COUNT:boards.{d.lower()}"] = str(n)
        total += n
    out["COUNT:boards.merged"] = str(total)
    out["COUNT:renders.d03"] = str(
        len([x for x in names if x.startswith("E29-D03-") and render.search(x)])
    )
    return out


@functools.lru_cache(maxsize=1)
def deck_rows() -> dict[str, list[str]]:
    """D03 §5.2's rows: key -> the quoted strings of its String cell."""
    block = section(at_base(CITE_FILES["D03"]), "5.2 Account states")
    out: dict[str, list[str]] = {}
    for r in table(block):
        if len(r) > 1:
            out[r[0].strip("`")] = re.findall(r'"([^"]*)"', r[1])
    return out


def deck_line_no(key: str) -> int:
    lines = at_base(CITE_FILES["D03"]).split("\n")
    for i, ln in enumerate(lines, 1):
        if ln.startswith(f"| `{key}`"):
            return i
    return 0


LOCK_KEYS = re.compile(
    r"^acct\.(?:[a-z]+\.line(?:\.[a-z]+)?|announce\.(?:reconciling|desync|stale))$"
)
SLOT_KEYS = re.compile(r"^acct\.[a-z]+\.line(?:\.[a-z]+)?$")


def slot_budget() -> int:
    return int(grab(r"≤ (\d+) characters", base_line("D03", 233), "D03:233 slot budget"))


def tight_lines() -> list[tuple[str, int]]:
    budget = slot_budget()
    out = []
    for k, strings in deck_rows().items():
        if SLOT_KEYS.match(k) and strings:
            n = len(strings[0])
            if n > budget * (100 - HEADROOM_PCT) / 100:
                out.append((k, n))
    return out


def deck_values() -> dict[str, str]:
    lock = [s for k, v in deck_rows().items() if LOCK_KEYS.match(k) for s in v if "Sub-" in s]
    works = [s for s in lock if "still work" in s]
    out = {
        "COUNT:deck.lock-strings": str(len(lock)),
        "COUNT:deck.still-work": str(len(works)),
        "LEN:slot.budget": str(slot_budget()),
        "LEN:reason.max": grab(r"≤ (\d+) characters", base_line("D03", 332), "D03:332"),
        "PCT:headroom": str(HEADROOM_PCT),
        "COUNT:slot.tight": str(len(tight_lines())),
    }
    for k, strings in deck_rows().items():
        if SLOT_KEYS.match(k) and strings:
            out[f"LEN:{k}"] = str(len(strings[0]))
    return out


def time_values() -> dict[str, str]:
    gap = grab(r"every (\d+)\s*ms", base_line("D04", 352), "D04:352 flash gap")
    return {
        "TIME:throttle": grab(r"1 update / (\d+)s", base_line("05", 147), "`05`:147"),
        "TIME:episode": grab(r"(\d+) s window", base_line("E17-D01", 218), "E17-D01:218"),
        "TIME:hold": grab(r"<=(\d+) s", base_line("14", 2963), "`14`:2963"),
        "TIME:pause": grab(r">(\d+)s", base_line("05", 207), "`05`:207"),
        "TIME:flash.gap": gap,
        "RATE:flash.limit": grab(
            r"more than (\d+) times per second", base_line("05", 208), "`05`:208"
        ),
        "RATE:flash.cell": str(1000 // int(gap)),
    }


def geom_values() -> dict[str, str]:
    frame = re.search(r"(\d+) × (\d+) window", strip_comments(base_line("D02", 481)))
    if not frame:
        raise SystemExit("FAIL parse: D02:481 frame")

    def tok(name: str) -> str:
        v = resolve("dark", name)
        if not re.fullmatch(r"\d+", v):
            raise SystemExit(f"FAIL parse: token {name} = {v}")
        return v

    return {
        "GEOM:focus.width": tok("border.focus"),
        "GEOM:target.min": tok("size.target.min"),
        "GEOM:target.comfortable": tok("size.control.comfortable"),
        "GEOM:zoom": grab(r"(\d+)% browser", base_line("05", 131), "`05`:131 zoom"),
        "GEOM:frame.w": frame[1],
        "GEOM:frame.h": frame[2],
        "GEOM:slot.line": grab(
            r"^\| Account slot line\s*\| (\d+)", base_line("D03", 399), "D03:399 slot line"
        ),
    }


CVD_PAIRS: dict[str, tuple[str, str]] = {
    "buy-sell": ("color.buy.default", "color.sell.default"),
    "near-critical": ("color.status.warning.strong", "color.status.danger.strong"),
    "live-demo": ("color.env.live", "color.env.demo"),
    "info-warning": ("color.status.info.subtle", "color.status.warning.subtle"),
    "warning-danger": ("color.status.warning.subtle", "color.status.danger.subtle"),
}


def cvd_min(a: str, b: str) -> float:
    best = math.inf
    for t in THEMES:
        ha, hb = hex_of(t, a), hex_of(t, b)
        if ha is None or hb is None:
            raise SystemExit(f"FAIL parse: {a} / {b} do not resolve in {t}")
        for s in SIMS:
            best = min(best, delta_e76(simulate(ha, s), simulate(hb, s)))
    return best


def hc_under() -> list[Pair]:
    """Gated text pairs below the high-contrast bar, one per distinct (fg, bg)."""
    seen: dict[tuple[str, str], Pair] = {}
    for p in union():
        r = ratio("hc", p.fg, p.bg)
        if p.role == "text" and r is not None and r < bars()["hc"]:
            seen.setdefault((p.fg, p.bg), p)
    return list(seen.values())


def contrast_values() -> dict[str, str]:
    out: dict[str, str] = {}
    for k, (fg, bg) in HC_PAIRS.items():
        r = ratio("hc", fg, bg)
        out[f"CONTRAST:{k}.hc"] = round2(r) if r is not None else "MISSING"
    for k, (fg, bg, _role) in COMPOSED.items():
        for t in THEMES:
            r = ratio(t, fg, bg or flash_bg())
            out[f"CONTRAST:{k}.{t}"] = round2(r) if r is not None else "MISSING"
    r = ratio("dark", _T + "primary", "color.surface.raised")
    out["CONTRAST:pill.dark"] = round2(r) if r is not None else "MISSING"
    focus = [
        v
        for p in union()
        if p.fg == "color.focus.ring" and p.role == "non-text"
        for v in measure(p).values()
        if v is not None
    ]
    out["CONTRAST:focus.min"] = round2(min(focus))
    srcs: dict[str, set[tuple[str, str]]] = {}
    for p in union():
        srcs.setdefault(p.src, set()).add((p.fg, p.bg))
    others = srcs.get("D02", set()) | srcs.get("D03", set()) | srcs.get("D04", set())
    out["COUNT:pairs.d02"] = str(len(srcs.get("D02", set())))
    out["COUNT:pairs.d03"] = str(len(srcs.get("D03", set())))
    out["COUNT:pairs.d04"] = str(len(srcs.get("D04", set())))
    out["COUNT:pairs.composed"] = str(len(srcs.get("composed", set()) - others))
    out["COUNT:pairs.union"] = str(len({(p.fg, p.bg) for p in union()}))
    out["COUNT:pairs.hc-under"] = str(len(hc_under()))
    agree, total = d03_agreement()
    out["COUNT:d03.agree"] = str(agree)
    out["COUNT:d03.values"] = str(total)
    for k, (a, b) in CVD_PAIRS.items():
        out[f"CVD:{k}"] = trunc1(cvd_min(a, b))
    out["HEX:stale.surface.dark"] = hex_of("dark", "color.data-confidence.stale.surface") or "?"
    return out


def d03_agreement() -> tuple[int, int]:
    agree = total = 0
    for p in union():
        if p.src != "D03":
            continue
        for t, printed in zip(THEMES, p.printed, strict=True):
            r = ratio(t, p.fg, p.bg)
            if not printed or r is None:
                continue
            total += 1
            agree += int(abs(float(printed) - r) <= 0.0051)
    return agree, total


@functools.lru_cache(maxsize=1)
def fixture() -> list[dict[str, str]]:
    data = json.loads(at_base(FIXTURE_REL))
    return [{str(k): str(v) for k, v in e.items()} for e in data["keys"]]


def chords(cell: str) -> list[str]:
    return [c for c in re.findall(r"`([^`]+)`", cell)]


def fixture_hits(cell: str) -> list[dict[str, str]]:
    keys = {c.strip() for c in chords(cell)}
    return [e for e in fixture() if e.get("norm") in keys]


@functools.lru_cache(maxsize=1)
def base_values() -> tuple[tuple[str, str], ...]:
    v: dict[str, str] = {}
    v.update({f"BAR:{k}": x for k, x in bar_values().items()})
    v.update(board_counts())
    v.update(deck_values())
    v.update(time_values())
    v.update(geom_values())
    v.update(contrast_values())
    v["COUNT:fx.rows"] = str(len(fixture()))
    v["BUDGET:lines.spec"] = str(SPEC_LINE_BUDGET)
    v["BUDGET:lines.hand"] = str(HAND_LINE_BUDGET)
    return tuple(sorted(v.items()))


CLAUSE_HEAD = "3. Clause by clause"
SC_HEAD = "4. WCAG 2.2 cross-walk"
KEY_HEAD = "6.1 The keyboard contract"
NAME_HEAD = "7.1 Names"
ROUTE_HEAD = "8.1 The routing table"
CARRIER_HEAD = "9.1 The carrier table"
CONTRAST_HEAD = "10. Contrast"
TRANS_HEAD = "12. The transition register"
FINDING_HEAD = "13. The finding register"
C_HEAD = "16.1 Contradictions"
G_HEAD = "16.2 Gaps"
Q_HEAD = "16.3 Open questions"
A_HEAD = A_TABLE_HEAD
DOD_HEAD = "17.1 DoD"
HANDOFF_HEAD = "17.2 Hand-offs"


def count_values(spec: str) -> dict[str, str]:
    out: dict[str, str] = {}
    cl = table(section(spec, CLAUSE_HEAD))
    out["COUNT:clauses"] = str(len(cl))
    verdicts = [r[3] if len(r) > 3 else "" for r in cl]
    out["COUNT:clauses.compliant"] = str(sum(v == "compliant" for v in verdicts))
    out["COUNT:clauses.at-risk"] = str(sum(v == "at risk" for v in verdicts))
    out["COUNT:clauses.non-compliant"] = str(sum(v == "non-compliant" for v in verdicts))
    out["COUNT:clauses.oos"] = str(sum(v.startswith("out of scope") for v in verdicts))
    fr = table(section(spec, FINDING_HEAD))
    out["COUNT:findings"] = str(len(fr))
    for s in SEVERITIES:
        out[f"COUNT:findings.{s.lower()}"] = str(sum(len(r) > 1 and r[1] == s for r in fr))
    out["COUNT:carriers"] = str(len(table(section(spec, CARRIER_HEAD))))
    for r in table(section(spec, KEY_HEAD)):
        if len(r) > 1:
            out[f"COUNT:fx.{r[0]}"] = str(len(fixture_hits(r[1])))
    return out


def compute(spec: str) -> Values:
    v = dict(base_values())
    v.update(count_values(anch(spec)))
    return v


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


def anch(text: str) -> str:
    """Every placeholder written as its anchor (the gates read filled and unfilled docs alike)."""
    return PLACEHOLDER.sub(lambda m: f"<!--={m[1]}-->", text)


def fence_template_lines() -> set[str]:
    """`05` §10's template lines (verbatim): a fenced line here may carry their figures."""
    text = at_base(plan_rel("05") or "")
    lines = text.split("\n")
    fence = fenced(lines)
    return {ln.strip() for i, ln in enumerate(lines) if fence[i] and ln.strip()}


def bare_figures(text: str, values: Values) -> list[tuple[int, str]]:
    """Figures typed by hand: outside an anchor, a quote, a code span, a cite, an issue number,
    the A table's Old cells and a fenced line that is `05` §10's template verbatim."""
    hits: list[tuple[int, str]] = []
    lines = text.split("\n")
    fence = fenced(lines)
    tmpl = fence_template_lines()
    a_rows = {ln for ln in section(text, A_HEAD).split("\n") if ln.startswith("|")}
    for i, line in enumerate(lines, 1):
        if fence[i - 1] and line.strip() in tmpl:
            continue
        work = line
        if line in a_rows:
            cells = split_row(line)
            work = " | ".join(c for j, c in enumerate(cells) if j != 3)
        for m in reversed(list(ANCHOR.finditer(work))):
            want = values.get(m[1], "")
            start = m.start() - len(want) if work[: m.start()].endswith(want) else m.start()
            work = work[:start] + " ⟨v⟩ " + work[m.end() :]
        work = PLACEHOLDER.sub(" ⟨v⟩ ", work)
        work = QUOTED.sub(" ", CODE.sub(" ", work))
        work = re.sub(r"\(#\d+\)|#\d+", " ", work)
        work = CITE_GROUP.sub(" ", work)
        hits += [(i, m[0]) for m in FIGURE.finditer(work)]
        hits += [(i, m[0]) for m in COUNTED.finditer(work)]
    return hits


def anchored_ok(prefix: str, want: str) -> bool:
    """The value ends `prefix` and starts at a left boundary (not the tail of a longer number)."""
    if not prefix.endswith(want):
        return False
    before = prefix[: len(prefix) - len(want)]
    return not before or not re.search(r"[\d.,+−-]$", before)


def g_anchor_doc(doc: str, text: str, values: Values) -> list[Finding]:
    bad: list[Finding] = []
    for i, line in enumerate(text.split("\n"), 1):
        sec = h2_at(text, i)
        for m in PLACEHOLDER.finditer(CODE.sub("", line)):
            bad.append(("G-ANCHOR", f"{doc}:{i} placeholder {m[1]} not filled", doc, sec))
        spans = code_spans(line)
        for m in ANCHOR.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue
            want = values.get(m[1])
            if want is None:
                bad.append(("G-ANCHOR", f"{doc}:{i} {m[1]} is not a computed value", doc, sec))
            elif not anchored_ok(line[: m.start()], want):
                got = re.split(r"[ |*(]", line[: m.start()])[-1]
                msg = f"{doc}:{i} {m[1]} reads {got!r}; the tool computes {want!r}"
                bad.append(("G-ANCHOR", msg, doc, sec))
    for i, fig in bare_figures(text, values):
        bad.append(
            ("G-ANCHOR", f"{doc}:{i} {fig!r} is a figure typed by hand", doc, h2_at(text, i))
        )
    return bad


def g_marker_doc(doc: str, text: str, values: Values) -> list[Finding]:
    """Every HTML comment is a value anchor the tool computes; a hidden note FAILs."""
    bad: list[Finding] = []
    starts = [0]
    for ln in text.split("\n"):
        starts.append(starts[-1] + len(ln) + 1)
    for m in COMMENT.finditer(text):
        i = next(k for k in range(len(starts) - 1) if starts[k] <= m.start() < starts[k + 1])
        line = text.split("\n")[i]
        col = m.start() - starts[i]
        if any(a <= col < b for a, b in code_spans(line)):
            continue
        sec = h2_at(text, i + 1)
        am = ANCHOR.fullmatch(m[0])
        if not m[0].endswith(("-->", "--!>")) and m.end() == len(text):
            bad.append(("G-MARKER", f"{doc}:{i + 1} an unclosed comment hides the rest", doc, sec))
        elif am is None or am[1] not in values:
            bad.append(("G-MARKER", f"{doc}:{i + 1} a hidden comment {m[0][:40]!r}", doc, sec))
    return bad


def g_hex_doc(doc: str, text: str) -> list[Finding]:
    bad: list[Finding] = []
    for i, line in enumerate(text.split("\n"), 1):
        work = CODE.sub(lambda c: " " * len(c[0]), line)
        for m in HEXLIT.finditer(work):
            if not re.match(r"<!--=HEX:", line[m.end() :]):
                bad.append(("G-HEX", f"{doc}:{i} {m[0]} typed by hand", doc, h2_at(text, i)))
    return bad


# ---------------------------------------------------------------------------- cites

# load-bearing fragments: (cite id, line at the base, text the line must hold)
CITED: tuple[tuple[str, int, str], ...] = (
    ("05", 63, "`Esc` (when order row focused)"),
    ("05", 86, "`Ctrl+W`"),
    ("05", 125, "≥4.5:1"),
    ("05", 126, "≥3:1"),
    ("05", 129, "near-black (not #000)"),
    ("05", 130, "≥7:1 body text"),
    ("05", 147, "default 1 update / 2s"),
    ("05", 148, "order filled, order rejected"),
    ("05", 150, "pre-rendered empty containers"),
    ("05", 208, "more than 3 times per second"),
    ("14", 1480, "real table semantics, sortable headers with `aria-sort`, row actions reachable"),
    ("14", 1746, "table semantics; fee and funding shown with sign and currency."),
    ("14", 2960, '`role="alert"` once'),
    ("14", 2963, "<=5 s"),
    ("15", 316, "Dismiss {title}"),
    ("15", 317, '`role="alert"` (warning/danger'),
    ("15", 498, 'non-modal drawer is a `role="dialog"` without `aria-modal`'),
    ("15", 2490, '`role="complementary"`'),
    ("16", 128, "a required state for every CMP-049-based table"),
    ("02", 180, '"internal tool, a11y doesn\'t matter" exception'),
    ("D01", 325, "**Esc precedence**"),
    ("D01", 406, "Updates paused · 2 new · 1 closed"),
    ("D01", 408, "A focused row never leaves while it has focus"),
    ("D02", 142, '"LIVE total"'),
    ("D02", 176, '"Select BTCUSDT Long on Main"'),
    ("D02", 220, '"!! Critical 0.5"'),
    ("D02", 320, "Amending → 2,495.00 · 2,500.00 still live"),
    ("D02", 320, "Amend to 2,495.00 sent to Bybit. The order is still at 2,500.00 until Bybit"),
    ("D02", 375, "Remove filter Account: Sub-1"),
    ("D02", 400, "No longer shown — access to Sub-2 was withdrawn."),
    ("D02", 429, '"Not available"'),
    ("D02", 435, "Read-only while viewing as {user}."),
    ("D02", 441, "Positions and orders — LIVE and DEMO"),
    ("D02", 447, "`Esc` closes and reverts, and never cancels"),
    ("D02", 465, "Never per tick"),
    ("D02", 481, "1280 × 800"),
    ("D03", 122, "Close fills detail"),
    ("D03", 147, "order ending a3f2"),
    ("D03", 173, "your legs (2)"),
    ("D03", 233, "≤ 200 characters"),
    ("D03", 342, "Only the owner can resolve the lock."),
    ("D03", 375, "Corrected. Size was 0.250, now 0.200, from Bybit. Detected 14:02:11 UTC."),
    ("D03", 428, "e29_d03_audit.py"),
    ("D03", 479, "pre-rendered empty"),
    ("D03", 488, "the hold is E29-D05's"),
    ("D03", 557, "resolves to black in dark and HC"),
    ("D04", 159, "LIVE · BTCUSDT · Long · 0.250 BTC · Main"),
    ("D04", 212, "profit 8.00 USDT"),
    ("D04", 240, "Flatten account — Sub-1 · LIVE"),
    ("D04", 316, "the blotter's one motion definition"),
    ("D04", 429, "flatten-confirm-label"),
    ("E17-D01", 218, "5 s window"),
    ("E11-D07", 589, "F-01"),
    ("E11-D07", 590, "F-04"),
    ("E11-D07", 611, "F-30"),
    ("KM", 523, '"positions.close"'),
    ("KM", 535, '"positions.close_all"'),
    ("KM", 157, '"workspace.panel_prev"'),
    ("KM", 166, '"workspace.panel_next"'),
    ("PREF", 13, "thick_focus_ring"),
    ("PREF", 25, 'announce_prices: "significant"'),
    ("PREF", 93, '"significant"'),
    ("02", 180, "internal tool"),
    ("05", 84, "**Detection algorithm**"),
    ("05", 87, "resolved per-account quantities"),
    ("05", 88, "rule-builder node-graph keyboard spec"),
    ("05", 96, "Only explicit user action or an explicit modal alert"),
    ("05", 187, "(tri-state)"),
    ("05", 238, "P0"),
    ("15", 530, "a focused cell (grid mode) scrolls below it (`scroll-margin-top`)"),
    ("15", 530, 'takes `aria-busy="true"` and stays focusable'),
    ("15", 530, "one polite live region for sort, filter, selection and load results"),
    ("D01", 410, "a risk lockout"),
    ("D02", 303, "`Esc`, `Tab` away or a click elsewhere restores the confirmed value"),
    ("D02", 349, "the counts per account"),
    ("D02", 423, "Risk lockout (B20 `locked`)"),
    ("D02", 447, "which the roving model treats as two cells"),
    ("D02", 461, "No control is smaller"),
    ("D03", 146, "the full id"),
    ("D03", 332, "≤ 60 characters"),
    ("D03", 399, "Account slot line"),
    ("D03", 604, "OQ-18"),
    ("D04", 272, "with its level and position"),
    ("D04", 273, "one polite region for sort, filter, selection and load results"),
    ("D04", 340, "overlay fallback"),
    ("D04", 367, "the countdown sits outside the live region"),
    ("E13-D05", 89, "BQ-6"),
    ("E29.json", 154, "the canvas-surrogate pattern (§6.1) does **not** apply here"),
    ("E29.json", 834, "windowed-grid rules in `05-accessibility-standard.md` section 6.1"),
)


def cite_findings(docs: dict[str, str], fetch: Fetch) -> tuple[list[Finding], list[str], int]:
    fails: list[Finding] = []
    warns: list[str] = []
    done: set[tuple[str, int]] = set()

    def lines_of(rev: str, rel: str) -> list[str] | None:
        t = fetch(rev, rel)
        return None if t is None else t.split("\n")

    for doc, text in docs.items():
        lines = text.split("\n")
        fence = fenced(lines)
        for li, line in enumerate(lines, 1):
            if fence[li - 1]:
                continue
            for m in CITE_GROUP.finditer(line):
                cid = m["a"] or m["b"]
                if cid in UNMERGED:
                    continue  # G-UNMERGED reports it
                if m["a"] and not (re.fullmatch(r"\d{2}", cid) or cid in CITE_FILES or "/" in cid):
                    continue
                refs = [m["first"], *re.findall(r":(\d+(?:[–-]\d+)?)", m["more"])]
                for ref in refs:
                    for part in re.split(r"[–-]", ref):
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
        if base is None or n > len(base) or frag not in strip_comments(base[n - 1]):
            hits = [i + 1 for i, ln in enumerate(base or []) if frag in ln]
            msg = f'`{cid}`:{n} "{frag[:40]}" not on the line (found {hits[:4]})'
            fails.append(("G-CITE", msg, None, None))
    return fails, warns, len(done) + len(CITED)


# ---------------------------------------------------------------------------- the texts


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str | None
    plans: tuple[tuple[str, str], ...]  # the working-tree untouched files (G-UNTOUCHED)
    values: Values
    hand_exists: bool = False
    extra_files: tuple[str, ...] = ()  # files named for this ticket beside the spec (BQ-31)


@functools.lru_cache(maxsize=64)
def lex_cached(doc: str, text: str) -> tuple[LexUnit, ...]:
    return tuple(lex_units(doc, text))


def lex(t: Texts) -> list[LexUnit]:
    out = list(lex_cached("spec", t.spec))
    if t.hand is not None:
        out += list(lex_cached("hand", t.hand))
    return out


def docs_of(t: Texts) -> dict[str, str]:
    return {"spec": t.spec} | ({"hand": t.hand} if t.hand is not None else {})


def F(tag: str, msg: str, doc: str | None, sec: str | None) -> Finding:
    return (tag, msg, doc, sec)


def spec_sec(t: Texts, head: str) -> str:
    return section(t.spec, head)


def at(t: Texts, head: str) -> str:
    return h2_of(t.spec, head)


def lexicon(tag: str, what: str, term: str, near: str = "") -> Callable[[Texts], list[Finding]]:
    def run(t: Texts) -> list[Finding]:
        return [F(tag, f"{what}: {h[0]!r}", h[1], h[2]) for h in claims(lex(t), term, near)]

    return run


# ---------------------------------------------------------------------------- lexicon gates

# Each ruled behaviour is carried by a synonym set plus a need-check on the ruled sentence's own
# words. Every paraphrase the adversary lens found (probes X-42..) trips a gate here with the pins
# rewritten; the pins stay the backstop for forms no lexicon lists.
FOCUS_INDEX_TERM = (
    r"\b(?:bound|tied|keyed|anchored|pinned|attached|linked|fixed) to (?:the |its |an |a |their )?"
    r"(?:row'?s? |rows' |visual |screen |list |grid )?"
    r"(?:index|position|row number|rowindex|aria rowindex|offset|slot|ordinal)\b"
    r"|\bfocus (?:\S+ ){0,2}?(?:by|via|through|using|follows|tracks) (?:the |its |an |a )?"
    r"(?:row'?s? )?(?:index|position|row number|offset|rowindex)\b"
    r"|\bindex based focus\b"
    r"|\b(?:at|on|to|in) the same (?:screen|visual|vertical|display) (?:row|position|place|slot)\b"
    r"|\bsame (?:height|vertical (?:place|position)|screen position|place on (?:the )?screen)"
    r"(?: in the (?:grid|list|table|window))?\b"
    r"|\bwhatever row now sits there\b"
)
LEAVE_TERM = (
    r"\bfocused rows? (?:\S+ ){0,2}?(?:may|can|will|does|is allowed to|are allowed to)"
    r" (?:\S+ ){0,2}?(?:leave|disappear|vanish|be removed|unmount|drop out)\b"
)
RESORT_TERM = (
    r"\b(?:live|automatic\w*|auto|streaming|opted in live)(?: \S+)? re ?(?:sort|order)\w*"
    r" (?:\S+ ){0,3}?(?:under|while|during|beneath) (?:the )?(?:focus\b|a (?:row|cell) (?:is|has)"
    r" focus\w*|focused)"
    r"|\bre ?sort\w* (?:live|automatically|on (?:every|each) update)\b (?:\S+ ){0,3}?"
    r"(?:under|while|during) (?:the )?(?:focus\b|a (?:row|cell) (?:is|has) focus\w*|focused)"
    r"|\blive sort (?:\S+ ){0,2}?(?:runs|applies|fires|continues|moves rows)"
    r" (?:\S+ ){0,2}?(?:under|while|during) (?:the )?(?:focus\b|a (?:row|cell) (?:is|has) focus\w*)"
    r"|\blive (?:sort\w*|ordering|order|re ?sort\w*|re ?order\w*) (?:\S+ ){0,2}?"
    r"(?:keeps? \w+ing|applies|runs|continues|fires|goes on)\b(?: \S+){0,6}?"
    r" (?:with|while|under|during|beneath)(?: \S+){0,3}? focus\w*"
    r"|\b(?:re ?order|re ?sort)\w*(?: themselves| itself)? (?:on|with|at|after) (?:each|every|any)"
    r" (?:update|tick|change|message)\b(?: \S+){0,3}? (?:while|when|as|even when) "
    r"(?:the user|a user|focus|a row|the row)\b"
)
BODY_TERM = (
    r"\b(?:moves?|goes|go|falls?(?: back)?|returns?|lands?|drops?|dropped|jumps?|resets?|is lost"
    r"|is sent|reverts?|is dropped)"
    r" (?:to|on|onto) (?:the )?(?:top of the )?(?:document |page )?(?:body|document root|document"
    r"|page)\b"
)
NEVER_ITEM = (
    r"\b(?:countdown|ages?|timers?|last update|value flash\w*|flashes|other fills|every tick"
    r"|each tick|ticks)\b"
)
SPEAK_TERM = (
    r"\b(?:announc\w*|spoken|speaks?|spoke|voiced|read aloud|read out|politely|assertively"
    r"|in (?:the|a) (?:polite|assertive) region|live region speaks|read to the user|conveyed"
    r"|narrated|reported to the user|(?:through|via|into|in) (?:the |a )?live regions?)\b"
)
AT_NAMES = r"\b(?:nvda|jaws|voiceover|voice over|narrator|talkback|orca)\b"
AT_RUN_TERM = (
    r"\b(?:tested|verified|checked|confirmed|heard|listened|ran|run|was run|were run|walked"
    r"|observed|recorded|captured)"
    r" (?:\S+ ){0,2}?(?:with|on|using|under|in) (?:a |the |two |both )?screen ?readers?\b"
    r"|\bscreen ?readers? (?:read|reads|said|says|announc\w*|spoke|speaks|voiced)\b"
    r"|\bscreen ?reader output (?:was |is |were )?(?:observed|recorded|captured|heard|checked"
    r"|logged)\b"
)
HCBAR_TERM = (
    r"\b(?:every|all|each|any) (?:\S+ ){0,2}?(?:pairs?|texts?|links?|labels?)"
    r" (?:\S+ ){0,3}?(?:pass\w*|meets?|clears?|holds?) (?:\S+ ){0,3}?high contrast\b"
    r"|\bhigh contrast (?:text )?(?:bar|threshold|minimum) (?:is|of|at) 4\.5\b"
    r"|\bhigh contrast (?:\S+ ){0,2}?(?:measured|held|read|kept) (?:against|at|to) 4\.5\b"
    r"|\bhigh contrast (?:\S+ ){0,3}?same (?:text )?(?:bar|threshold|minimum) as\b"
    r"|\bsame (?:text )?(?:bar|threshold|minimum) (?:in|for|across) (?:every theme|all three"
    r" themes|the three themes|high contrast)\b"
)
STATIC_TERM = (
    r"\bstatic (?:\S+ ){0,2}?(?:highlight\w*|tint|fill) (?:\S+ ){0,3}?reduced motion\b"
    r"|\b(?:highlight\w*|tint) (?:\S+ ){0,2}?(?:stays|remains|kept|is kept) static\b"
    r"|\bstatic under reduced motion\b"
    r"|\b(?:slides?|fades?|animates?|glides?|eases?) (?:\S+ ){0,3}?under reduced motion\b"
    r"|\bstatic (?:\S+ ){0,2}?(?:highlight\w*|tint|fill)\w* (?:\S+ ){0,3}?(?:when|while|if|once)"
    r" motion is reduced\b"
)
NODRAW_TERM = (
    r"\b(?:redrawn|redraws?|redrawing|drawn anew|drawn again|drawn in penpot"
    r"|new penpot (?:page|board)s?|new boards?|new frames?|verdict boards?"
    r"|(?:fresh|additional|extra|added|new) (?:penpot )?(?:boards?|frames?|drawings?|sheets?))\b"
)
NODRAW_IF = r"\b(?:should|unless|if) the owner\b"
HANDOFF_TERM = (
    r"\bhand ?off (?:file|document|pack file|markdown)s?\b|\be29 d05 handoff\.md\b"
    r"|\bhand ?off carries\b|\bcompanion hand ?off\b"
)
CLOSE_RULE_TERM = (
    r"\b(?:fixed|corrected|repaired|amended|edited|patched|updated|changed) in (?:the )?"
    r"(?:design file|merged (?:spec|text|design)\w*|penpot file|figma file)\b"
    r"|\b(?:design file|merged (?:spec|text|design)\w*|penpot file) (?:is |are )?"
    r"(?:fixed|corrected|repaired|amended|edited|patched|updated|changed)\b"
    r"|\b(?:reviewer|author|writer|agent|lane|qa) marks? (?:it|the finding|a finding)"
    r" (?:as )?(?:done|closed|resolved|fixed)\b"
)
SIGNOFF_TERM = (
    r"\b(?:a11y lead|accessibility lead|cdo|design lead)s?\b (?:\S+ ){0,3}?"
    r"(?:signed|approved|sign(?:ed)? off|countersigned|endorsed|accepted|cleared|ratified"
    r"|okayed|blessed)\b"
    r"|\bsigned off by (?:the )?(?:a11y lead|accessibility lead|cdo)\b"
    r"|\bowner's approved (?:is |was |has been )?(?:taken|assumed|granted|given|obtained|in hand"
    r"|received|recorded as given)\b"
    r"|\bthe owner (?:has )?(?:approved|signed off|endorsed)\b"
)
PENDING_TERM = (
    r"\b(?:bq 19|routing table|assertive set|live region (?:routing )?table|live region routing)\b"
    r" (?:\S+ ){0,4}?(?:is |was )?(?:ruled|confirmed|approved|settled|final|adopted|binding"
    r"|in force|authoritative|decided|agreed|locked)\b"
)
EDIT_TERM = (
    r"\b(?:edits?|rewrites?|patch(?:es)?|modif(?:y|ies)|changes?) (?:the |a |any )?merged"
    r" (?:text|spec|design|file)s?\b"
)
SCOPE_TERM = (
    r"\b(?:may|can|does|will|is allowed to) (?:\S+ ){0,2}?(?:count|counts|number|total)"
    r"\b(?: \S+){0,4}? out of scope\b"
    r"|\bcounts? (?:\S+ ){0,2}?out of scope (?:legs?|accounts?|rows?)\b"
    r"|\browcount counts (?:every|all|the hidden|out of scope)\b"
)
EXCEPTION_TERM = (
    r"\bessential exception (?:\S+ ){0,3}?(?:covers|applies|is used|exempts|is claimed|is taken"
    r"|is relied on)\b"
)
ONE_SENTENCE_TERM = (
    r"\bone sentence (?:for|covering|across) (?:all|every|the) accounts\b"
    r"|\ball accounts (?:\S+ ){0,2}?(?:in|as) (?:one|a single) sentence\b"
)
MOST_TERM = (
    r"\b(?:most|some|many|nearly all|almost all|the majority of)"
    r" (?:\S+ ){0,1}?(?:colou?r carrying )?signals\b"
)
# RULED BQ-19 in prose: an assertive class never read as polite, a polite one never as assertive
ASSERTIVE_EVENTS = (
    r"\b(?:nosl|critical crossings?|crossings? into critical|rejected amends?|amend rejected"
    r"|stale locks?|kill switch locks?|adl|liquidation fills?|new correction findings"
    r"|post reconnect summary|missing stop ?loss|no stop ?loss|unprotected positions?)\b"
)
POLITE_EVENTS = r"\b(?:near crossings?|selection count|confirmed amends?|amend confirmed)\b"
TO_POLITE = r"\b(?:politely|polite region|in the polite|is polite|are polite|stays? polite)\b"
TO_POLITE_SOFT = (
    r"\b(?:without interrupting|never interrupts?|does not interrupt|non interrupting"
    r"|waits? (?:until|for) (?:the user (?:is )?)?idle|when (?:the user is )?idle"
    r"|after the current (?:speech|utterance|sentence)|quietly)\b"
)
TO_ASSERTIVE = (
    r"\b(?:assertively|assertive region|in the assertive|is assertive|are assertive"
    r"|interrupts?|interrupting|cuts? in|pre ?empts?)\b"
)


def need(t: Texts, tag: str, head: str, words: tuple[str, ...]) -> list[Finding]:
    """The ruled sentence's own words, each present in the section `head` (normalised)."""
    n = norm_text(spec_sec(t, head))
    return [
        F(tag, f"§{head.split()[0]} lost {w!r}", "spec", at(t, head)) for w in words if w not in n
    ]


def g_route_prose(t: Texts) -> list[Finding]:
    """BQ-19 in prose (cells read too): an assertive class read as polite, or the converse."""
    bad: list[Finding] = []
    for u in lex(t):
        for c in clauses(u.text):
            n = re.sub(r"\bno sl\b", "nosl", norm_text(unquote(c)))
            if re.search(r"\b(?:would|alternative|q 01)\b", n):
                continue
            for ev, to_, what in (
                (ASSERTIVE_EVENTS, TO_POLITE, "an assertive class read as polite"),
                (POLITE_EVENTS, TO_ASSERTIVE, "a polite class read as assertive"),
            ):
                if re.search(ev, n) and live(c, to_):
                    bad.append(F("G-ROUTE", f"{what}: {n[:70]!r}", u.doc, u.sec))
            if re.search(ASSERTIVE_EVENTS, n) and re.search(TO_POLITE_SOFT, n):
                msg = f"an assertive class read as polite: {n[:70]!r}"
                bad.append(F("G-ROUTE", msg, u.doc, u.sec))
    return bad


FOCUS_HEAD = "5.4 The focus rule"


def g_focus(t: Texts) -> list[Finding]:
    bad = lexicon("G-FOCUS", "focus bound to an index", FOCUS_INDEX_TERM)(t)
    bad += lexicon("G-FOCUS", "a focused row leaves", LEAVE_TERM)(t)
    bad += need(
        t,
        "G-FOCUS",
        FOCUS_HEAD,
        (
            "bound to the row's id and its column, never to an index",
            "leave focus on the same row and cell",
            "a focused row never leaves while it is focused",
        ),
    )
    return bad


def g_resort(t: Texts) -> list[Finding]:
    bad = lexicon("G-RESORT", "a live re-sort under focus", RESORT_TERM)(t)
    return bad + need(
        t,
        "G-RESORT",
        FOCUS_HEAD,
        (
            "opted in live sort waits while a row is focused or selected",
            "only an explicit header press re sorts under focus",
        ),
    )


def g_body(t: Texts) -> list[Finding]:
    return lexicon("G-BODY", "focus sent to body", BODY_TERM, near=r"\bfocus\b")(t)


def g_revoke(t: Texts) -> list[Finding]:
    block = spec_sec(t, FOCUS_HEAD)
    line = next((ln for ln in block.split("\n") if "**Revocation" in ln), "")
    n = norm_text(line)
    need_ = ("proposed", "no longer shown", "never", "body", "f 02", "focus moves to", "rt 15")
    miss = [w for w in need_ if w not in n]
    if miss:
        return [F("G-REVOKE", f"§5.4 revocation clause lacks {miss}", "spec", at(t, "5.4"))]
    return []


def g_never(t: Texts) -> list[Finding]:
    return lexicon("G-NEVER", "a never-announced item announced", SPEAK_TERM, NEVER_ITEM)(t)


def g_at(t: Texts) -> list[Finding]:
    bad = [
        F("G-AT", f"an assistive technology named: {h[0]!r}", h[1], h[2])
        for h in claims(lex(t), AT_NAMES)
    ]
    bad += lexicon("G-AT", "a screen-reader run claimed", AT_RUN_TERM)(t)
    return bad


def g_hcbar(t: Texts) -> list[Finding]:
    bad = lexicon("G-HCBAR", "high contrast read at the AA bar", HCBAR_TERM)(t)
    rows = table(spec_sec(t, CONTRAST_HEAD))
    listed = set()
    for r in rows:
        toks = re.findall(r"`(color\.[^`]+)`", r[0]) if r else []
        if len(toks) == 2:
            listed.add((toks[0], toks[1]))
    want = {(p.fg, p.bg) for p in hc_under()}
    if listed != want:
        miss, extra = sorted(want - listed), sorted(listed - want)
        msg = (
            f"§10's high-contrast table differs from the re-measure: missing {miss}, extra {extra}"
        )
        bad.append(F("G-HCBAR", msg, "spec", at(t, CONTRAST_HEAD)))
    return bad


def g_static(t: Texts) -> list[Finding]:
    bad = lexicon("G-STATIC", "a static highlight under reduced motion", STATIC_TERM)(t)
    return bad + need(t, "G-STATIC", "11.1 Motion", ("d04's readings hold",))


def g_nodraw(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for u in lex(t):
        for c in clauses(u.text):
            if re.search(NODRAW_IF, norm_text(c)):
                continue
            if live(c, NODRAW_TERM):
                bad.append(F("G-NODRAW", f"a new drawing: {norm_text(c)[:70]!r}", u.doc, u.sec))
    return bad


def other_d05_files() -> list[str]:
    """Any file in the spec's folder named for this ticket other than the spec itself."""
    folder = ROOT / Path(SPEC_REL).parent
    spec_name = Path(SPEC_REL).name
    return sorted(
        p.name
        for p in folder.glob("*")
        if p.is_file() and re.search(r"(?i)e29.?d05", p.name) and p.name != spec_name
    )


def g_nohandoff(t: Texts) -> list[Finding]:
    bad = lexicon("G-NOHANDOFF", "a hand-off file", HANDOFF_TERM)(t)
    if "no handoff.md" not in norm_text(spec_sec(t, HANDOFF_HEAD)):
        bad.append(F("G-NOHANDOFF", "§17.2 lost 'No `-handoff.md`'", "spec", at(t, HANDOFF_HEAD)))
    if t.hand is not None:
        bad.append(F("G-NOHANDOFF", "a hand-off was passed against RULED BQ-31", "hand", None))
    elif t.hand_exists:
        bad.append(F("G-NOHANDOFF", f"{t.extra_files} exist against RULED BQ-31", None, None))
    return bad


def g_close_rule(t: Texts) -> list[Finding]:
    bad = lexicon("G-CLOSE-RULE", "closing by an edit of the design file", CLOSE_RULE_TERM)(t)
    r2 = next((ln for ln in t.spec.split("\n") if ln.startswith("- **R-2")), "")
    n = norm_text(r2)
    for w in ("routed", "accepted with a written rationale", "owner's approved", "c 19"):
        if w not in n:
            bad.append(F("G-CLOSE-RULE", f"R-2 lacks {w!r}", "spec", "1. Purpose, method,"))
    return bad


def g_signoff(t: Texts) -> list[Finding]:
    bad = lexicon("G-SIGNOFF", "a sign-off claimed", SIGNOFF_TERM)(t)
    n = norm_text(spec_sec(t, DOD_HEAD))
    for w in (
        "orchestrator's design approval",
        "qa record",
        "pending the owner's approved on #2701",
        "walkthrough",
        "#824",
    ):
        if w not in n:
            bad.append(F("G-SIGNOFF", f"§17.1 lacks {w!r}", "spec", at(t, DOD_HEAD)))
    lines = t.spec.split("\n")
    i = next((k for k, ln in enumerate(lines) if ln.startswith("**Ticket:**")), 0)
    if "nothing here claims the owner's approved" not in norm_text(lines[i]):
        msg = "the status line lost its no-approval claim"
        bad.append(F("G-SIGNOFF", msg, "spec", h2_at(t.spec, i + 1)))
    return bad


def g_pending(t: Texts) -> list[Finding]:
    bad = lexicon("G-PENDING", "BQ-19 read as ruled", PENDING_TERM)(t)
    head = next((ln for ln in t.spec.split("\n") if ln.startswith("### 8.1 ")), "")
    if PENDING not in head:
        bad.append(F("G-PENDING", "§8.1's heading lacks the PROPOSED marker", "spec", at(t, "8.1")))
    ruled = section(t.spec, "The thirty-three questions")
    bq19 = next((s for s in sentences(ruled) if "**BQ-19**" in s and "routing" in s), "")
    if PENDING not in bq19.replace("**", ""):
        bad.append(
            F("G-PENDING", "the RULED line lacks BQ-19's marker", "spec", "The thirty-three")
        )
    return bad


def g_close(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for doc, text in docs_of(t).items():
        for i, line in enumerate(text.split("\n"), 1):
            if CLOSING.search(strip_comments(line)):
                msg = f"{doc}:{i} a closing keyword before an issue number"
                bad.append(F("G-CLOSE", msg, doc, h2_at(text, i)))
    return bad


# letters allowed outside the Latin script (the review's own symbols)
SCRIPT_OK = frozenset("Δ")


def g_charset(t: Texts) -> list[Finding]:
    """A CR, trailing whitespace, a char NFKC changes, a format char (category Cf: zero-width,
    soft hyphen, bidi marks) or a non-Latin letter outside a code span (a homoglyph)."""
    bad: list[Finding] = []
    for doc, text in docs_of(t).items():
        if "\r" in text:
            bad.append(F("G-CHARSET", f"{doc} holds a CR", doc, None))
        for i, line in enumerate(text.split("\n"), 1):
            sec = h2_at(text, i)
            if line != line.rstrip():
                bad.append(F("G-CHARSET", f"{doc}:{i} trailing whitespace", doc, sec))
            outside = CODE.sub(" ", line)
            for ch in sorted(set(line)):
                cat = unicodedata.category(ch)
                if unicodedata.normalize("NFKC", ch) != ch:
                    msg = f"{doc}:{i} U+{ord(ch):04X} changes under NFKC"
                elif cat == "Cf":
                    msg = f"{doc}:{i} U+{ord(ch):04X} is a format (invisible) char"
                elif (
                    cat.startswith("L")
                    and ch in outside
                    and ch not in SCRIPT_OK
                    and not unicodedata.name(ch, "").startswith("LATIN")
                ):
                    msg = f"{doc}:{i} U+{ord(ch):04X} is a non-Latin letter (homoglyph)"
                else:
                    continue
                bad.append(F("G-CHARSET", msg, doc, sec))
    return bad


def g_cells(t: Texts) -> list[Finding]:
    """Every table row has its header's cell count (GFM drops cells past the header, so a
    paragraph glued onto a row never renders)."""
    bad: list[Finding] = []
    for doc, text in docs_of(t).items():
        lines = text.split("\n")
        fence = fenced(lines)
        width = 0
        for i, ln in enumerate(lines):
            if fence[i] or not re.match(r"^ {0,3}\|", ln):
                width = 0
                continue
            n = len(split_row(ln))
            if i + 1 < len(lines) and is_rule(lines[i + 1]) and width == 0:
                width = n
            elif width and n != width:
                msg = f"{doc}:{i + 1} a row of {n} cells under a {width}-cell header"
                bad.append(F("G-CELLS", msg, doc, h2_at(text, i + 1)))
    return bad


def g_unmerged(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    pat = re.compile(rf"\b(?:{'|'.join(UNMERGED)})(?:\.md)?`? ?:\d+")
    for doc, text in docs_of(t).items():
        for i, line in enumerate(text.split("\n"), 1):
            if pat.search(line) and not line.startswith(("| M-",)):
                msg = f"{doc}:{i} an unmerged text is cited by line"
                bad.append(F("G-UNMERGED", msg, doc, h2_at(text, i)))
    for name in UNMERGED:
        epic = name.split("-")[0]
        if git_show(BASE, f"docs/design/{epic}/{name}.md") is not None:
            bad.append(F("G-UNMERGED", f"{name} is merged at the base: re-read it", None, None))
    return bad


LEXICON_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_charset,
    g_cells,
    g_close,
    g_at,
    g_focus,
    g_resort,
    g_route_prose,
    g_body,
    g_never,
    g_hcbar,
    g_static,
    g_nodraw,
    g_nohandoff,
    g_close_rule,
    g_signoff,
    g_pending,
    g_unmerged,
)

# ---------------------------------------------------------------------------- table gates

ID_CELL = re.compile(r"\b(?:F|C|G|Q|A|H|K|N|CR|RT|T|SR)-\d\d\b")


def defined_ids(t: Texts) -> set[str]:
    out: set[str] = set()
    for ln in t.spec.split("\n"):
        m = re.match(r"^\| ((?:F|C|A|K|N|CR|RT|T|SR)-\d\d) \|", ln)
        if m:
            out.add(m[1])
        m2 = re.match(r"^- \*\*((?:G|Q|H)-\d\d)", ln)
        if m2:
            out.add(m2[1])
    return out


def g_clause(t: Texts) -> list[Finding]:
    sec = at(t, CLAUSE_HEAD)
    rows = table(spec_sec(t, CLAUSE_HEAD))
    sev = {r[0]: r[1] for r in table(spec_sec(t, FINDING_HEAD)) if len(r) > 1}
    bad: list[Finding] = []
    ids = [r[0].strip("`") for r in rows]
    for c in CLAUSES:
        if ids.count(c) != 1:
            bad.append(F("G-CLAUSE", f"clause {c} has {ids.count(c)} rows", "spec", sec))
    for r in rows:
        if len(r) < 5:
            bad.append(F("G-CLAUSE", f"row {r[0]} has {len(r)} cells", "spec", sec))
            continue
        cid, req, where, verdict, fnd = r[0].strip("`"), r[1], r[2], r[3], r[4]
        if cid not in CLAUSES:
            bad.append(F("G-CLAUSE", f"{cid} is not a clause of BQ-6", "spec", sec))
        if not VERDICT.match(verdict):
            bad.append(F("G-CLAUSE", f"{cid} verdict {verdict!r}", "spec", sec))
        if not CITE_GROUP.search(req + " " + where) and not verdict.startswith("out of scope"):
            bad.append(F("G-CLAUSE", f"{cid} carries no file:line evidence", "spec", sec))
        fs = re.findall(r"\bF-\d\d\b", fnd)
        sevs = [sev.get(f, "") for f in fs]
        if verdict == "non-compliant" and "Blocking" not in sevs:
            bad.append(F("G-CLAUSE", f"{cid} non-compliant without a Blocking F row", "spec", sec))
        if verdict == "at risk" and "Major" not in sevs and "interim path" not in where:
            bad.append(
                F("G-CLAUSE", f"{cid} at risk with no Major F row or interim path", "spec", sec)
            )
        if verdict == "compliant" and ({"Major", "Blocking"} & set(sevs)):
            bad.append(
                F("G-CLAUSE", f"{cid} compliant with a Major or Blocking F row", "spec", sec)
            )
        rule = CLAUSE_RULED.get(cid)
        if rule and not (verdict == rule[0] and all(w in where + " " + fnd for w in rule[1:])):
            bad.append(F("G-CLAUSE", f"{cid} must read {rule}", "spec", sec))
    return bad


def g_sc(t: Texts) -> list[Finding]:
    sec = at(t, SC_HEAD)
    rows = table(spec_sec(t, SC_HEAD))
    clause_ids = {r[0].strip("`") for r in table(spec_sec(t, CLAUSE_HEAD))}
    bad: list[Finding] = []
    got = [r[0] for r in rows]
    for c in CRITERIA:
        if got.count(c) != 1:
            bad.append(F("G-SC", f"criterion {c} has {got.count(c)} rows", "spec", sec))
    for r in rows:
        if len(r) < 4:
            bad.append(F("G-SC", f"row {r[0]} has {len(r)} cells", "spec", sec))
            continue
        for c in re.findall(r"`([^`]+)`", r[1]):
            if c not in clause_ids:
                bad.append(F("G-SC", f"{r[0]} names clause {c}, not in §3", "spec", sec))
        if not (VERDICT.match(r[2]) or (r[2] == "Info" and r[0].endswith("(AAA)"))):
            bad.append(F("G-SC", f"{r[0]} verdict {r[2]!r}", "spec", sec))
    row = next((r for r in rows if r[0] == "2.2.2"), None)
    if row is not None and not ("PROPOSED" in row[3] and "Updates paused" in row[3]):
        bad.append(F("G-222", "2.2.2 lacks the PROPOSED essential-exception reading", "spec", sec))
    return bad


def g_222(t: Texts) -> list[Finding]:
    block = spec_sec(t, "11.1 Motion")
    s = next((x for x in sentences(block) if "WCAG 2.2.2" in x), "")
    if not all(w in s for w in ("PROPOSED", "essential exception", "Updates paused")):
        return [
            F(
                "G-222",
                "§11.1's WCAG 2.2.2 sentence lost its PROPOSED reading",
                "spec",
                at(t, "11.1"),
            )
        ]
    return []


def g_frow(t: Texts) -> list[Finding]:
    sec = at(t, FINDING_HEAD)
    rows = table(spec_sec(t, FINDING_HEAD))
    clause_rows = {r[0].strip("`"): r for r in table(spec_sec(t, CLAUSE_HEAD)) if r}
    bad: list[Finding] = []
    for r in rows:
        if len(r) != 8 or any(not c.strip() for c in r):
            bad.append(F("G-FROW", f"{r[0]} must have eight filled cells", "spec", sec))
            continue
        fid, sev, cl, _spec, ev, _rep, _owner, target = r
        if sev not in SEVERITIES:
            bad.append(F("G-FROW", f"{fid} severity {sev!r}", "spec", sec))
        c = cl.strip("`")
        if c not in clause_rows or fid not in clause_rows[c][4]:
            bad.append(F("G-FROW", f"{fid} is not listed on clause {c}'s row", "spec", sec))
        if not CITE_GROUP.search(ev):
            bad.append(F("G-FROW", f"{fid} evidence carries no file:line", "spec", sec))
        if not re.search(r"#\d+|E05 tokens", target):
            bad.append(F("G-FROW", f"{fid} target names no issue", "spec", sec))
    r1 = norm_text(next((ln for ln in t.spec.split("\n") if ln.startswith("- **R-1")), ""))
    for w in (
        "non compliant with no compliant path",
        "a state carried by colour alone",
        "an announcement with no string or politeness",
        "an at risk clause, a key collision without a declared shadow",
        "not used for design findings",
    ):
        if w not in r1:
            bad.append(F("G-FROW", f"R-1 lost {w!r}", "spec", "1. Purpose, method,"))
    return bad


AGENT = re.compile(
    r"\b(?:agents?|workers?|hcl|hpe|bots?|claude|orchestrator|sessions?|lane \d|assistant)\b"
)


def g_fowner(t: Texts) -> list[Finding]:
    sec = at(t, FINDING_HEAD)
    bad: list[Finding] = []
    for r in table(spec_sec(t, FINDING_HEAD)):
        if len(r) < 8:
            continue
        owner = norm_text(r[6] + " " + r[3])
        if AGENT.search(owner):
            bad.append(F("G-FOWNER", f"{r[0]} names an agent as owner", "spec", sec))
        elif not (("spec" in owner and "area/" in owner) or "token owner" in owner):
            bad.append(F("G-FOWNER", f"{r[0]} owner is not a spec and its area", "spec", sec))
    return bad


def g_hcfrow(t: Texts) -> list[Finding]:
    rows = table(spec_sec(t, FINDING_HEAD))
    bad: list[Finding] = []
    for p in hc_under():
        if not any(f"`{p.fg}`" in " ".join(r) and "E05" in " ".join(r) for r in rows):
            msg = f"no F row routes {p.fg} on {p.bg} (high contrast) to E05"
            bad.append(F("G-HCFROW", msg, "spec", at(t, FINDING_HEAD)))
    return bad


def g_frows_ruled(t: Texts) -> list[Finding]:
    rows = table(spec_sec(t, FINDING_HEAD))
    bad: list[Finding] = []
    if git_show(BASE, D03_TOOL_REL) is None and not any(
        "e29_d03_audit.py" in " ".join(r) and "E29-D03" in " ".join(r) for r in rows
    ):
        bad.append(
            F("G-FROWS-RULED", "no F row for D03:428's missing tool", "spec", at(t, FINDING_HEAD))
        )
    tight = [deck_line_no(k) for k, _n in tight_lines()]
    if tight and not any(all(f":{n}" in " ".join(r) for n in tight) for r in rows):
        bad.append(F("G-FROWS-RULED", f"no F row cites the tight slot lines {tight}", "spec", None))
    return bad


def g_route(t: Texts) -> list[Finding]:
    sec = at(t, ROUTE_HEAD)
    rows = table(spec_sec(t, ROUTE_HEAD))
    bad: list[Finding] = []
    for pat, region, new in ROUTES:
        hit = [
            r
            for r in rows
            if len(r) > 5
            and re.search(pat, norm_text(unquote(r[1]).replace('"', "")) + " " + norm_text(r[1]))
        ]
        if len(hit) != 1:
            bad.append(F("G-ROUTE", f"event {pat!r} has {len(hit)} rows", "spec", sec))
            continue
        r = hit[0]
        if norm_text(r[2]) != region:
            bad.append(F("G-ROUTE", f"{r[0]} region {r[2]!r}; ruled {region}", "spec", sec))
        if new and PENDING not in r[5]:
            bad.append(
                F("G-ROUTE", f"{r[0]} is new to `05`: status must be {PENDING}", "spec", sec)
            )
        if not new and r[5] != "in `05`":
            bad.append(F("G-ROUTE", f"{r[0]} is `05`:148's: status must be 'in `05`'", "spec", sec))
        if region == "none" and norm_text(r[3]) != "never":
            bad.append(F("G-ROUTE", f"{r[0]} throttle must be never", "spec", sec))
    return bad


def g_alt(t: Texts) -> list[Finding]:
    q = next((ln for ln in t.spec.split("\n") if ln.startswith("- **Q-01**")), "")
    if "`05`:148's list only" not in q or "PROPOSED" not in q:
        return [F("G-ALT", "Q-01 lost BQ-19's alternative", "spec", at(t, Q_HEAD))]
    return []


def g_keys(t: Texts) -> list[Finding]:
    sec = at(t, KEY_HEAD)
    ids = defined_ids(t)
    bad: list[Finding] = []
    km = json.loads(at_base(CITE_FILES["KM"]))
    shipped: dict[str, str] = {}

    def walk(o: object) -> None:
        if isinstance(o, dict):
            if "id" in o and "defaultBinding" in o:
                shipped[str(o["id"])] = str(o["defaultBinding"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(km)
    for r in table(spec_sec(t, KEY_HEAD)):
        if len(r) < 7:
            bad.append(F("G-KEYS", f"{r[0]} has {len(r)} cells", "spec", sec))
            continue
        hits = fixture_hits(r[1])
        modes = {h.get("mode", "") for h in hits}
        res = ID_CELL.findall(r[6])
        if modes & {"table", "focus", "global"} and not res:
            bad.append(
                F("G-KEYS", f"{r[0]} collides in {sorted(modes)} with no resolution", "spec", sec)
            )
        for x in res:
            if x not in ids:
                bad.append(F("G-KEYS", f"{r[0]} resolution {x} is not defined", "spec", sec))
        if "`KM`" in r[4]:
            bound = set(shipped.values())
            for c in chords(r[1]):
                if c not in bound:
                    bad.append(F("G-KEYS", f"{r[0]} {c} is not a shipped binding", "spec", sec))
    return bad


def g_names(t: Texts) -> list[Finding]:
    sec = at(t, NAME_HEAD)
    bad: list[Finding] = []
    for r in table(spec_sec(t, NAME_HEAD)):
        if len(r) < 7:
            bad.append(F("G-NAMES", f"{r[0]} has {len(r)} cells", "spec", sec))
            continue
        label = r[3].strip('"')
        name = r[4].strip('"')
        if label != "—" and label.lower() not in name.lower():
            bad.append(F("G-NAMES", f"{r[0]} name {name!r} lacks its label {label!r}", "spec", sec))
        if not name or name == "—":
            bad.append(F("G-NAMES", f"{r[0]} has no accessible name", "spec", sec))
        if not (CITE_GROUP.search(r[6]) or "PROPOSED" in r[6]):
            bad.append(F("G-NAMES", f"{r[0]} source neither cited nor PROPOSED", "spec", sec))
    return bad


COLOUR_ONLY = re.compile(
    r"^(?:the )?(?:fill|colou?r|hue|tint|highlight|shade|accent)s?\.?$", re.IGNORECASE
)


def g_carrier(t: Texts) -> list[Finding]:
    sec = at(t, CARRIER_HEAD)
    bad: list[Finding] = []
    for r in table(spec_sec(t, CARRIER_HEAD)):
        if len(r) < 8:
            bad.append(F("G-CARRIER", f"{r[0]} has {len(r)} cells", "spec", sec))
            continue
        carriers = [
            c for c in (r[3], r[4], r[5]) if c not in ("—", "") and not COLOUR_ONLY.match(c)
        ]
        if not carriers:
            bad.append(F("G-CARRIER", f"{r[0]} ({r[1]}) has no non-colour carrier", "spec", sec))
        for tok in re.findall(r"`(color\.[^`]+)`", r[2]):
            for th in THEMES:
                if hex_of(th, tok) is None:
                    bad.append(
                        F("G-CARRIER", f"{r[0]} {tok} does not resolve in {th}", "spec", sec)
                    )
        if not CITE_GROUP.search(r[7]):
            bad.append(F("G-CARRIER", f"{r[0]} carries no source cite", "spec", sec))
    bad += lexicon("G-CARRIER", "colour carriers weakened", MOST_TERM)(t)
    r5 = norm_text(next((ln for ln in t.spec.split("\n") if ln.startswith("- **R-5")), ""))
    if "every colour carrying signal has a word, glyph, sign or aria state" not in r5:
        bad.append(F("G-CARRIER", "R-5 lost its every-signal rule", "spec", "1. Purpose, method,"))
    return bad


@functools.lru_cache(maxsize=1)
def mo_ids() -> frozenset[str]:
    block = section(at_base(CITE_FILES["D04"]), "3.2 The motion table")
    return frozenset(r[0] for r in table(block) if r and r[0].startswith("Mo-"))


SURFACES = {"SCR-063", "SCR-078", "slot"}
MOTION_WORDS = re.compile(
    r"\b(?:slides?|sliding|fades?|fading|animat\w*|eas(?:e|ing)|tween\w*|transition\w*)\b",
    re.IGNORECASE,
)
LAYOUT_OK = re.compile(r"fixed row height|in place|one frame|the slot grows", re.IGNORECASE)
LAYOUT_BAD = re.compile(
    r"\b(?:animat\w*|grows? the row|expands? the row|height (?:grows|changes|animates)|"
    r"reflows? the (?:window|list|grid)|pushes? rows)\b",
    re.IGNORECASE,
)
PAIR_CELL = re.compile(r"^`(color\.[^`]+)` on `(color\.[^`]+)` \((text|non-text)\)$")


def g_trans(t: Texts) -> list[Finding]:
    sec = at(t, TRANS_HEAD)
    bad: list[Finding] = []
    rows = table(spec_sec(t, TRANS_HEAD))
    if not rows:
        bad.append(F("G-TRANS", "the transition register is empty", "spec", sec))
    for r in rows:
        if len(r) != 7:
            bad.append(F("G-TRANS", f"{r[0]} has {len(r)} cells", "spec", sec))
            continue
        tid, surface, trigger, pair, reduce_, carrier, layout = r
        if not {s.strip() for s in surface.split(",")} <= SURFACES:
            bad.append(F("G-TRANS", f"{tid} surface {surface!r}", "spec", sec))
        if not trigger.strip() or trigger == "—":
            bad.append(F("G-TRANS", f"{tid} has no trigger", "spec", sec))
        m = PAIR_CELL.match(pair)
        if not m:
            bad.append(F("G-TRANS", f"{tid} token pair {pair!r} unreadable", "spec", sec))
        else:
            for th in THEMES:
                v = ratio(th, m[1], m[2])
                b = bar_for(m[3], th)
                if v is None or b is None or v < b:
                    shown = "unresolved" if v is None else round2(v)
                    bad.append(
                        F("G-TRANS", f"{tid} pair {shown} in {th} under its bar", "spec", sec)
                    )
        mo = re.match(r"^(Mo-\d+):", reduce_)
        if not mo or mo[1] not in mo_ids():
            bad.append(F("G-TRANS", f"{tid} reduce substitute cites no D04 Mo row", "spec", sec))
        if MOTION_WORDS.search(reduce_):
            bad.append(F("G-TRANS", f"{tid} reduce substitute moves: {reduce_!r}", "spec", sec))
        if not carrier.strip() or COLOUR_ONLY.match(carrier.strip()) or carrier == "—":
            bad.append(F("G-TRANS", f"{tid} carrier {carrier!r} is colour alone", "spec", sec))
        if not LAYOUT_OK.search(layout) or LAYOUT_BAD.search(layout):
            bad.append(F("G-TRANS", f"{tid} layout rule {layout!r}", "spec", sec))
    return bad


def g_crows(t: Texts) -> list[Finding]:
    rows = [" ".join(r) for r in table(spec_sec(t, C_HEAD))]
    need = (
        (
            "static highlight vs D04 Mo-4, D04's reading",
            r"static under reduced motion.*D04's: no highlight",
        ),
        ("drawer slide vs D04-C8", r"drawer slide.*D04-C8.*D04's: docked"),
        ("7:1 vs the specs' 4.5:1", r"BAR:hc.*BAR:text.*F-06"),
        ("announce_prices composition", r"announce_prices.*shouldAnnounce.*G-05"),
        ("fixed in the design file", r"fixed in the design file.*E29-D06 lifts"),
        ("Esc cancels", r"Cancel focused order.*never cancels"),
        ("shipped Ctrl+W", r"Ctrl\+W.*G-03"),
        ("shipped Ctrl+Alt arrows", r"Ctrl\+Alt.*F-01.*G-04"),
        ("stacked reflow", r"`16`:128.*at risk"),
        ("the revocation focus move vs `05`:96", r"`05`:96.*revocation.*heuristic"),
    )
    bad: list[Finding] = []
    for what, pat in need:
        if not any(re.search(pat, r) for r in rows):
            bad.append(F("G-CROWS", f"no C row records {what}", "spec", at(t, C_HEAD)))
    return bad


def g_grows(t: Texts) -> list[Finding]:
    lines = {
        m[1]: ln
        for ln in spec_sec(t, G_HEAD).split("\n")
        if (m := re.match(r"^- \*\*(G-\d\d)\*\*", ln))
    }
    need = (
        ("G-01", ("mounted", "D04")),
        ("G-03", ("Ctrl+W", "E11-S13 (#520)", "F-01", "screen-reader table navigation", "K-13")),
        ("G-04", ("Ctrl+Alt", "E11-S13 (#520)", "F-01")),
        ("G-05", ("shouldAnnounce", "preference's owner")),
    )
    bad: list[Finding] = []
    for gid, words in need:
        ln = lines.get(gid, "")
        miss = [w for w in words if w not in ln]
        if miss:
            bad.append(F("G-GROWS", f"{gid} lacks {miss}", "spec", at(t, G_HEAD)))
    return bad


def g_consumers(t: Texts) -> list[Finding]:
    block = spec_sec(t, HANDOFF_HEAD)
    miss = [c for c in CONSUMERS if not re.search(rf"{re.escape(c)}\b", block)]
    bad: list[Finding] = []
    if miss:
        bad.append(
            F("G-CONSUMERS", f"§17.2 lacks the comments on {miss}", "spec", at(t, HANDOFF_HEAD))
        )
    lifted = next((x for x in sentences(block) if "lifts as they stand" in x), "")
    gone = [x for x in LIFTED if x not in lifted]
    if gone:
        msg = f"§17.2's lifted sections lack {gone}"
        bad.append(F("G-CONSUMERS", msg, "spec", at(t, HANDOFF_HEAD)))
    return bad


# the sections E29-D06 lifts (lens 3: every section holding a replacement or a bound rule)
LIFTED = (
    "§5.1–§5.4",
    "§6.1–§6.3",
    "§7.1–§7.2",
    "§8.1–§8.4",
    "§9.1",
    "§10",
    "§11.1–§11.3",
    "§12",
    "§13's replacements",
    "§14",
)


def g_unbuilt(t: Texts) -> list[Finding]:
    block = spec_sec(t, "0. Status")
    first = next(
        (p for p in block.split("\n") if p.startswith("**The blotters are unbuilt.**")), ""
    )
    bad: list[Finding] = []
    feats = sorted(Path(n).name for n in ls_tree(BASE, FEATURES_REL) if "." not in Path(n).name)
    named = sorted(re.findall(r"`([A-Za-z0-9-]+)`", first.split("no blotter slice")[0]))
    if "no blotter slice" not in first or "holds no CMP-049" not in first:
        bad.append(F("G-UNBUILT", "§0 lost the unbuilt statement", "spec", at(t, "0. Status")))
    elif named != feats:
        bad.append(F("G-UNBUILT", f"§0 lists {named}; the base holds {feats}", "spec", at(t, "0.")))
    ui = git_out("grep", "-l", "CMP-049", BASE, "--", UI_SRC_REL)
    if ui.strip():
        bad.append(F("G-UNBUILT", "packages/ui/src holds CMP-049 at the base", None, None))
    miss = [s for s in STORIES if s not in first]
    if miss:
        bad.append(F("G-UNBUILT", f"§0 does not name {miss}", "spec", at(t, "0. Status")))
    return bad


def g_arow(t: Texts) -> list[Finding]:
    sec = at(t, A_HEAD)
    bad: list[Finding] = []
    rows = rows_by(spec_sec(t, A_HEAD))
    a01 = norm_text(rows.get("A-01", ["", "", "", "", ""])[-1])
    for w in A01_RULED:
        if w not in a01:
            bad.append(F("G-AROW", f"A-01 New lost the ruled words {w!r}", "spec", sec))
    for r in table(spec_sec(t, A_HEAD)):
        if len(r) != 5:
            bad.append(F("G-AROW", f"{r[0]} has {len(r)} cells", "spec", sec))
            continue
        if r[3] == "—":
            continue
        m = CITE_GROUP.search(r[2])
        if not m:
            bad.append(F("G-AROW", f"{r[0]} names no line", "spec", sec))
            continue
        cid = m["a"] or m["b"]
        line = pin_norm(strip_comments(base_line(cid, int(m["first"]))))
        if pin_norm(r[3]) not in line:
            bad.append(
                F("G-AROW", f"{r[0]} Old is not verbatim at {cid}:{m['first']}", "spec", sec)
            )
    return bad


# RULED BQ-19's blotter set, in the ruling's words (A-01 carries them to `05`)
A01_RULED = (
    "no sl on a position",
    "a crossing into critical",
    "a rejected amend",
    "the stale and kill switch locks once per episode",
    "a run's new correction findings once per occurrence",
    "an adl or liquidation fill once per position",
    "the post reconnect summary",
)


def g_deck(t: Texts) -> list[Finding]:
    v = dict(base_values())
    if v["COUNT:deck.still-work"] != v["COUNT:deck.lock-strings"]:
        msg = "a D03 lock string lacks what still works: §8.2's claim is false"
        return [F("G-DECK", msg, "spec", at(t, "8.2"))]
    return []


def g_union(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    if not themes_json_ok():
        bad.append(
            F("G-UNION", "themes.json no longer layers the three themes as THEMES", None, None)
        )
    for p in union():
        for th, v in measure(p).items():
            b = bar_for(p.role, th)
            if v is None:
                bad.append(F("G-UNION", f"{p.fg} / {p.bg} unresolved in {th}", None, None))
            elif b is not None and th != "hc" and v < b:
                bad.append(
                    F("G-UNION", f"{p.src} {p.fg} on {p.bg} {round2(v)} in {th}", None, None)
                )
    return bad


def g_untouched(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    ref = fork_point()
    for nn, text in t.plans:
        rel = cite_path(nn)
        if rel is None:
            continue
        if text == DELETED:
            bad.append(F("G-UNTOUCHED", f"{rel} deleted in the working tree", None, None))
        elif git_show(ref, rel) != text:
            bad.append(F("G-UNTOUCHED", f"{rel} differs from {ref[:10]} (merge-base)", None, None))
    bad += lexicon("G-UNTOUCHED", "a merged text edited", EDIT_TERM)(t)
    bad += need(t, "G-UNTOUCHED", "1.1 What this", ("it edits no merged text",))
    return bad


def g_target(t: Texts) -> list[Finding]:
    """RULED BQ-16 (as proposed): no essential exception; no control under the minimum."""
    bad = lexicon("G-TARGET", "the essential exception used", EXCEPTION_TERM)(t)
    return bad + need(
        t,
        "G-TARGET",
        "6.3 Targets",
        ("no essential exception is used", "no control is smaller", "link style actions"),
    )


def g_order(t: Texts) -> list[Finding]:
    """RULED BQ-21 (as proposed): the reconnect utterance, its hold and the order of a burst."""
    bad = lexicon("G-ORDER", "accounts merged into one sentence", ONE_SENTENCE_TERM)(t)
    return bad + need(
        t,
        "G-ORDER",
        "8.3 Order",
        (
            "then one sentence per account in the slot's order",
            "whichever comes first",
            "serialised, never concatenated, most severe first",
        ),
    )


def g_scope(t: Texts) -> list[Finding]:
    """RULED BQ-28 (as proposed): nothing reveals an out-of-scope leg or account."""
    bad = lexicon("G-SCOPE", "an out-of-scope leg or account counted", SCOPE_TERM)(t)
    bad += need(
        t,
        "G-SCOPE",
        "11.3 RBAC",
        (
            "no visible string names or counts an out of scope leg or account",
            "aria rowcount counts in scope rows only",
            "the countdown sits outside the live regions",
            "ends with the same safety sentence",
            "one sentence of at most",
        ),
    )
    safety = {s.rsplit(". ", 1)[-1] for s in deck_rows().get("acct.announce.stale", [])}
    safety = {x for x in safety if x.endswith("still work.")}
    if len(safety) != 1:
        bad.append(
            F("G-SCOPE", f"D03's stale variants end differently: {sorted(safety)}", None, None)
        )
    return bad


# RULED BQ-30 (as proposed): one Feature per surface, `05` §10's template lines kept
SCRIPT_SURFACES = (
    "SCR-063 Positions",
    "Working orders",
    "Fills and Closed today",
    "the account states",
    "corrections",
    "the post-reconnect summary",
    "SCR-078 in its three scopes",
)


@functools.lru_cache(maxsize=1)
def template_steps() -> tuple[str, ...]:
    """`05` §10's Then / And steps, continuation lines joined (the template's own words)."""
    text = at_base(plan_rel("05") or "")
    block = section(text, "10. Accessibility acceptance-criteria template")
    return tuple(s for s in fence_steps(block) if re.match(r"^(?:Then|And) ", s))


def fence_steps(block: str) -> list[str]:
    lines = block.split("\n")
    fence = fenced(lines)
    steps: list[str] = []
    for i, ln in enumerate(lines):
        if not fence[i] or FENCE_OPEN.match(ln):
            continue
        st = ln.strip()
        if re.match(r"^(?:Given|When|Then|And|Feature|Scenario|Examples|#|\|)", st) or not st:
            steps.append(st)
        elif steps:
            steps[-1] += " " + st
    return [x for x in steps if x]


def g_script(t: Texts) -> list[Finding]:
    sec = at(t, "14.2 ")
    block = section(t.spec, "14.2 ")
    steps = fence_steps(block)
    bad: list[Finding] = []
    feats = [x for x in steps if x.startswith("Feature: ")]
    for name in SCRIPT_SURFACES:
        if sum(bool(re.match(rf"Feature: {re.escape(name)}[ ,]", x)) for x in feats) != 1:
            bad.append(F("G-SCRIPT", f"§14.2 has no Feature for {name!r}", "spec", sec))
    if not template_steps():
        bad.append(F("G-SCRIPT", "`05` §10's template steps not found at the base", None, None))
    for st in template_steps():
        if st not in steps:
            bad.append(F("G-SCRIPT", f"§14.2 drops the template step {st[:60]!r}", "spec", sec))
    srs = {r[0] for r in table(spec_sec(t, "14.1 Tasks")) if r}
    named = set(re.findall(r"\bSR-\d\d\b", block))
    if srs - named:
        bad.append(F("G-SCRIPT", f"§14.2 names no Feature for {sorted(srs - named)}", "spec", sec))
    sr08 = " ".join(rows_by(spec_sec(t, "14.1 Tasks")).get("SR-08", []))
    if "hold" not in sr08:
        bad.append(F("G-SCRIPT", "SR-08 no longer tests the reconnect hold (BQ-21)", "spec", sec))
    return bad


def g_budget(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    n = t.spec.count("\n")
    if n > SPEC_LINE_BUDGET:
        bad.append(F("G-BUDGET", f"spec {n} lines > {SPEC_LINE_BUDGET}", "spec", h2_at(t.spec, n)))
    if t.hand is not None and t.hand.count("\n") > HAND_LINE_BUDGET:
        bad.append(F("G-BUDGET", f"hand-off over {HAND_LINE_BUDGET} lines", "hand", None))
    return bad


def g_mutlist(t: Texts) -> list[Finding]:
    rows = table(section(t.spec, MUTATION_HEAD))
    got = [
        (r[0], (re.match(r"^(G-[A-Z0-9-]+):", r[2]) or [None, ""])[1]) for r in rows if len(r) > 2
    ]
    want = [(m.mid, m.gate) for m in MUTATIONS]
    if got != want:
        diff = [x for x in got if x not in want][:3] + [x for x in want if x not in got][:3]
        return [
            F(
                "G-MUTLIST",
                f"§15 differs from the tool's mutations: {diff}",
                "spec",
                h2_of(t.spec, MUTATION_HEAD),
            )
        ]
    return []


MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_clause,
    g_sc,
    g_222,
    g_frow,
    g_fowner,
    g_hcfrow,
    g_frows_ruled,
    g_route,
    g_alt,
    g_revoke,
    g_keys,
    g_names,
    g_carrier,
    g_trans,
    g_crows,
    g_grows,
    g_consumers,
    g_unbuilt,
    g_arow,
    g_deck,
    g_union,
    g_untouched,
    g_target,
    g_order,
    g_scope,
    g_script,
    g_budget,
    g_mutlist,
)

# ---------------------------------------------------------------------------- pins (G-RULED-PIN)

PIN_SENT = re.compile(r"s\d+")
Unit = tuple[str, str, str, str]  # (doc, region, loc, text)
FULL_STOP = re.compile(r"(?<=[.!?])\s+")


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
    """Every unit of the doc: per region (heading path `a > b`, `#n` its occurrence), the heading,
    the line shape, each rule line, each table row by its lead cell, each prose sentence and each
    fenced block (verbatim, as JSON)."""
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
                out.append(
                    (doc, region, f"fence {nf}", json.dumps("\n".join(block), ensure_ascii=False))
                )
                block = []
            continue
        ln = unvalued(raw, values)
        m = HEADING.match(ln)
        if m:
            close()
            level = len(m[1])
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m[2]))]
            key = " › ".join(p[1] for p in path)
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
            out.append((doc, region, loc, " | ".join(pin_norm(c) for c in split_row(ln))))
        else:
            sents = [x for x in FULL_STOP.split(ln.strip()) if x.strip()]
            shape += f"{indent_tag(raw)}{line_form(ln)}{len(sents)}"
            for s in sents:
                k += 1
                out.append((doc, region, f"s{k}", pin_norm(s)))
    close()
    return out


def ruled_units(t: Texts) -> list[Unit]:
    return [u for d, x in docs_of(t).items() for u in doc_units(d, x, t.values)]


def write_pins(units: list[Unit]) -> str:
    head = (
        "# E29-D05 pins (every unit of the review): doc, region (heading path #occurrence), "
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


def read_pins() -> tuple[Unit, ...] | None:
    path = ROOT / RULED_PIN_TXT
    if not path.exists():
        return None
    return parse_pins(path.read_text(encoding="utf-8"))


def region_label(region: str) -> str:
    return region if len(region) <= 60 else "..." + region[-57:]


def region_sec(region: str) -> str:
    parts = region.rsplit("#", 1)[0].split(" › ")
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
            bad.append((f"{where} {u[2]} repeated: {u[3][:60]!r}", doc, region))
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
            msg = f"{where} shape changed (line forms, sentences per line, indents, blank lines)"
            bad.append((msg, d, r))
    return bad


def pin_findings(t: Texts, pinned: tuple[Unit, ...] | None = None) -> list[Finding]:
    pins = read_pins() if pinned is None else pinned
    if pins is None:
        return [F("G-RULED-PIN", f"no {RULED_PIN_TXT}; run --repin-ruled deliberately", None, None)]
    return [F("G-RULED-PIN", m, d, region_sec(r)) for m, d, r in pin_problems(pins, ruled_units(t))]


FENCE_PROBE = (
    "# 1. Probe\n\nA sketch follows.\n\n```text\n  [ row ]   [ cell ]\n"
    "| not | a table |\n~~~\n```\n\nAfter it.\n"
)
FENCE_PROBE_CUTS = (
    ("a run of spaces inside a line", "]   [ cell", "] [ cell"),
    ("a line's indent", "\n  [ row", "\n[ row"),
    ("a doubled space in a `|` line", "| not | a table |\n", "| not |  a table |\n"),
    ("a line removed", "| not | a table |\n", ""),
    ("a line added", "| not | a table |\n", "| not | a table |\n  Esc\n"),
)


def fence_pin_probe() -> list[str]:
    units = doc_units("spec", FENCE_PROBE, {})
    pins = parse_pins(write_pins(units))
    fences = [u for u in pins if u[2].startswith("fence")]
    if len(fences) != 1 or "  [ row ]   [ cell ]" not in json.loads(fences[0][3]):
        return [f"fence probe: not one verbatim fence block: {fences[:1]}"]
    if "~~~" not in json.loads(fences[0][3]):
        return ["fence probe: a ~~~ line closed a ``` fence"]
    bad = [f"fence probe: unchanged FAILs {p[0][:60]!r}" for p in pin_problems(pins, units)]
    for name, old, new in FENCE_PROBE_CUTS:
        cut = FENCE_PROBE.replace(old, new, 1)
        got = pin_problems(pins, doc_units("spec", cut, {}))
        hits = [p for p in got if "fence 1" in p[0]]
        if cut == FENCE_PROBE or len(hits) != 1:
            bad.append(
                f"fence probe {name}: expected one fence finding, got {[p[0][:50] for p in got]}"
            )
    return bad


# ---------------------------------------------------------------------------- the audit


def audit(t: Texts, fetch: Fetch) -> tuple[list[str], list[str], list[str], int]:
    """(FAIL lines, NOTE lines, WARN lines, cites checked). One FAIL line per gate; a pin finding
    in a section another gate already FAILs is demoted to a NOTE line."""
    found: list[Finding] = []
    for gate in LEXICON_GATES:
        found += gate(t)
    for doc, text in docs_of(t).items():
        found += g_anchor_doc(doc, text, t.values)
        found += g_marker_doc(doc, text, t.values)
        found += g_hex_doc(doc, text)
    for gate in MEASURED_GATES:
        found += gate(t)
    cf, warns, n = cite_findings(docs_of(t), fetch)
    found += cf
    flagged = {(f[2], f[3]) for f in found if f[2] is not None}
    flagged_docs = {f[2] for f in found if f[2] is not None and f[3] is None}
    pins = pin_findings(t)
    demote = [p for p in pins if (p[2], p[3]) in flagged or p[2] in flagged_docs]
    notes = [f"NOTE [G-RULED-PIN] {p[1][:150]}" for p in demote]
    found += [p for p in pins if p not in demote]
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

Edit = Callable[[str], str]


def set_cell(line: str, idx: int, fn: Callable[[str], str]) -> str:
    cells = split_row(line)
    cells[idx] = fn(cells[idx])
    return "| " + " | ".join(cells) + " |"


def row_edit(head: str, first: str, col: int, fn: Callable[[str], str]) -> Edit:
    """A cell of the row whose first cell is `first`, inside the section `head`."""

    def run(text: str) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("|") and split_row(ln)[0] == first:
                lines[i] = set_cell(ln, col, fn)
                return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def row_sub(head: str, first: str, old: str, new: str) -> Edit:
    """Replace every `old` in the row whose first cell is `first`."""

    def run(text: str) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("|") and split_row(ln)[0] == first and old in ln:
                lines[i] = ln.replace(old, new)
                return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def to(value: str) -> Callable[[str], str]:
    return lambda _c: value


def sub_in(head: str, old: str, new: str) -> Edit:
    def run(text: str) -> str:
        block = section(text, head)
        return text.replace(block, block.replace(old, new, 1), 1) if old in block else text

    return run


def drop_row(head: str, first: str) -> Edit:
    def run(text: str) -> str:
        block = section(text, head)
        kept = [
            ln for ln in block.split("\n") if not (ln.startswith("|") and split_row(ln)[0] == first)
        ]
        return text.replace(block, "\n".join(kept), 1)

    return run


def say_in(head: str, sentence: str) -> Edit:
    """Append `sentence` to the last prose, bullet or numbered line of the section `head`."""

    def run(text: str) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i in range(len(lines) - 1, 0, -1):
            ln = lines[i]
            if ln.strip() and not ln.startswith(("|", "#", "```", "    ")):
                lines[i] = ln + " " + sentence
                return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def line_sub(prefix: str, old: str, new: str) -> Edit:
    def run(text: str) -> str:
        out = text.split("\n")
        for i, ln in enumerate(out):
            if ln.startswith(prefix) and old in ln:
                out[i] = ln.replace(old, new, 1)
                break
        return "\n".join(out)

    return run


def in_lines(head: str, fn: Callable[[list[str]], list[str]]) -> Edit:
    def run(text: str) -> str:
        block = section(text, head)
        return text.replace(block, "\n".join(fn(block.split("\n"))), 1) if block else text

    return run


def overrun(text: str) -> str:
    n = text.count("\n")
    return text + "filler\n" * (SPEC_LINE_BUDGET - n + 5)


def trailing_space(text: str) -> str:
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("**The blotters are unbuilt.**"):
            lines[i] = ln + " "
            break
    return "\n".join(lines)


def cite_out_of_range(text: str) -> str:
    return text.replace("(D02:142, :244)", "(D02:9999, :244)", 1)


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str  # the gate tag that must trip ("" for a probe that must trip nothing)
    spec: Edit | None = None
    plan: tuple[str, Edit] | None = None  # (untouched id, edit) on the working-tree copy
    hand: Edit | None = None  # a hand-off text passed beside the spec


REVOKE_ONCE = (
    'the focus move speaks the line once and RT-15\'s polite "revoked" stays silent for that'
    " account, so the line is heard once; "
)
LIGHTHOUSE = "    And the affected screen's Lighthouse Accessibility score remains >= 95\n"
VIEW_AS_BANNER = (
    " The shell's view-as banner, its Exit and its countdown are E42-D02's, cited by D04:367: the"
    " countdown sits outside the live regions and never animates."
)
G03_SR = (
    " The ruling reads them as colliding with screen-reader table navigation; that reading was"
    " checked, and K-13 matches 0<!--=COUNT:fx.K-13--> fixture rows, so the gap is the OS"
    " blocklist."
)


def _drop_feature(name: str) -> Callable[[list[str]], list[str]]:
    def run(lines: list[str]) -> list[str]:
        i = next((k for k, ln in enumerate(lines) if ln.startswith(f"Feature: {name}")), -1)
        return lines if i < 0 else lines[:i] + lines[i + 5 :]

    return run


def rep(old: str, new: str) -> Edit:
    """The first `old` anywhere in the spec, replaced (the adversary lens's attacks)."""
    return lambda s: s.replace(old, new, 1)


RT = ROUTE_HEAD
MUTATIONS: tuple[Mutation, ...] = (
    Mutation("M-01", "G-ROUTE", row_edit(RT, "RT-04", 2, to("polite"))),
    Mutation("M-02", "G-ROUTE", row_edit(RT, "RT-05", 2, to("polite"))),
    Mutation("M-03", "G-ROUTE", row_edit(RT, "RT-06", 2, to("polite"))),
    Mutation("M-04", "G-ROUTE", row_edit(RT, "RT-07", 2, to("polite"))),
    Mutation("M-05", "G-ROUTE", row_edit(RT, "RT-12", 2, to("assertive"))),
    Mutation("M-06", "G-ROUTE", row_edit(RT, "RT-17", 2, to("polite"))),
    Mutation("M-07", "G-ROUTE", row_edit(RT, "RT-04", 5, to("in `05`"))),
    Mutation("M-08", "G-ROUTE", drop_row(RT, "RT-09")),
    Mutation("M-09", "G-NEVER", say_in("8.4 One surface", "The countdown is announced politely.")),
    Mutation("M-10", "G-PENDING", line_sub("### 8.1 ", ", owner approval pending (#2701)", "")),
    Mutation("M-11", "G-ALT", line_sub("- **Q-01**", "`05`:148's list only", "the composed table")),
    Mutation("M-12", "G-FOCUS", say_in("5.4 The focus rule", "Focus is bound to the row's index.")),
    Mutation("M-13", "G-RESORT", say_in("5.2 Sorting", "The live sort re-sorts under focus.")),
    Mutation(
        "M-14",
        "G-BODY",
        line_sub(
            "- **Revocation",
            "never moves to `body`.",
            "never moves to `body`; else focus moves to the body.",
        ),
    ),
    Mutation("M-15", "G-REVOKE", line_sub("- **Revocation", " (PROPOSED; F-02)", "")),
    Mutation("M-16", "G-FOWNER", row_edit(FINDING_HEAD, "F-01", 6, to("an agent"))),
    Mutation("M-17", "G-FROW", row_edit(FINDING_HEAD, "F-04", 1, to("Grave"))),
    Mutation("M-18", "G-FROW", row_edit(FINDING_HEAD, "F-03", 7, to(""))),
    Mutation(
        "M-19",
        "G-CLOSE-RULE",
        say_in(FINDING_HEAD, "A finding closes when it is fixed in the design file."),
    ),
    Mutation(
        "M-20", "G-ANCHOR", sub_in(CONTRAST_HEAD, "**7<!--=BAR:hc-->:1", "**4.5<!--=BAR:hc-->:1")
    ),
    Mutation("M-21", "G-HCBAR", say_in(CONTRAST_HEAD, "Every text pair passes in high contrast.")),
    Mutation(
        "M-22",
        "G-HCFROW",
        row_sub(FINDING_HEAD, "F-06", "`color.text.link`", "`color.text.primary`"),
    ),
    Mutation(
        "M-23",
        "G-STATIC",
        row_edit(TRANS_HEAD, "T-04", 4, to("Mo-4: a static highlight under reduced motion")),
    ),
    Mutation(
        "M-24", "G-TRANS", row_edit(TRANS_HEAD, "T-05", 4, to("Mo-99: open or closed at frame 0"))
    ),
    Mutation("M-25", "G-TRANS", row_edit(TRANS_HEAD, "T-06", 5, to("fill"))),
    Mutation(
        "M-26",
        "G-TRANS",
        row_edit(
            TRANS_HEAD, "T-09", 3, to("`color.text.disabled` on `color.surface.raised` (text)")
        ),
    ),
    Mutation("M-27", "G-TRANS", row_edit(TRANS_HEAD, "T-01", 6, to("the row height animates"))),
    Mutation(
        "M-28",
        "G-222",
        line_sub(
            "D04 §3 is the blotters' one motion definition",
            "**WCAG 2.2.2 (PROPOSED):**",
            "**WCAG 2.2.2:**",
        ),
    ),
    Mutation(
        "M-29", "G-CROWS", row_sub(C_HEAD, "C-07", "D04's: no highlight", "D02's: a static fill")
    ),
    Mutation(
        "M-30",
        "G-CARRIER",
        (
            row_edit(CARRIER_HEAD, "CR-03", 3, to("—"))
            if False
            else (
                lambda s: row_edit(CARRIER_HEAD, "CR-03", 4, to("—"))(
                    row_edit(CARRIER_HEAD, "CR-03", 3, to("—"))(s)
                )
            )
        ),
    ),
    Mutation("M-31", "G-SIGNOFF", say_in(DOD_HEAD, "The a11y lead and the CDO signed off.")),
    Mutation("M-32", "G-CONSUMERS", sub_in(HANDOFF_HEAD, "#1146 (E29-D07)", "E29-D07")),
    Mutation("M-33", "G-NOHANDOFF", say_in(HANDOFF_HEAD, "The hand-off file carries the A rows.")),
    Mutation("M-34", "G-AT", say_in(NAME_HEAD, "NVDA reads the row name.")),
    Mutation("M-35", "G-CLAUSE", row_edit(CLAUSE_HEAD, "`3.4.3`", 3, to("compliant"))),
    Mutation("M-36", "G-CLAUSE", drop_row(CLAUSE_HEAD, "`3.3.1`")),
    Mutation("M-37", "G-SC", drop_row(SC_HEAD, "2.4.11")),
    Mutation("M-38", "G-KEYS", row_edit(KEY_HEAD, "K-15", 6, to("—"))),
    Mutation("M-39", "G-NAMES", row_edit(NAME_HEAD, "N-04", 4, to('"Exit the position"'))),
    Mutation("M-40", "G-CLOSE", say_in(DOD_HEAD, "Closes #824.")),
    Mutation("M-41", "G-CITE", cite_out_of_range),
    Mutation("M-42", "G-UNTOUCHED", plan=("05", lambda s: s + "An appended line.\n")),
    Mutation("M-43", "G-NODRAW", say_in("0. Status", "Board 20 is redrawn in Penpot.")),
    Mutation(
        "M-44", "G-UNBUILT", line_sub("**The blotters are unbuilt.**", " and no blotter slice", "")
    ),
    Mutation("M-45", "G-GROWS", line_sub("- **G-03**", "E11-S13 (#520)", "E11-S99 (#599)")),
    Mutation(
        "M-46",
        "G-FROWS-RULED",
        row_sub(FINDING_HEAD, "F-08", "`docs/design/_tools/e29_d03_audit.py`", "a tool"),
    ),
    Mutation("M-47", "G-UNMERGED", say_in("0. Status", "E29-D06:12 lists the pack.")),
    Mutation("M-48", "G-BUDGET", overrun),
    Mutation("M-49", "G-CHARSET", trailing_space),
    Mutation(
        "M-50",
        "G-CELLS",
        lambda s: s.replace("|\n\nDesync stays polite", "| Desync stays polite", 1),
    ),
    Mutation("M-51", "G-CLAUSE", row_edit(CLAUSE_HEAD, "`5.5`", 3, to("compliant"))),
    Mutation("M-52", "G-CLAUSE", row_edit(CLAUSE_HEAD, "`6.2a`", 3, to("compliant"))),
    Mutation("M-53", "G-CLAUSE", drop_row(CLAUSE_HEAD, "`3.3.5`")),
    Mutation("M-54", "G-ROUTE", row_edit(RT, "RT-18", 2, to("polite"))),
    Mutation("M-55", "G-ROUTE", drop_row(RT, "RT-19")),
    Mutation("M-56", "G-REVOKE", line_sub("- **Revocation", REVOKE_ONCE, "")),
    Mutation("M-57", "G-CROWS", drop_row(C_HEAD, "C-22")),
    Mutation("M-58", "G-SCRIPT", in_lines("14.2 ", _drop_feature("Fills and Closed today"))),
    Mutation("M-59", "G-SCRIPT", sub_in("14.2 ", LIGHTHOUSE, "")),
    Mutation(
        "M-60",
        "G-SCOPE",
        say_in("11.3 RBAC", "A visible string may count the out-of-scope accounts."),
    ),
    Mutation("M-61", "G-SCOPE", sub_in("11.3 RBAC", VIEW_AS_BANNER, "")),
    Mutation(
        "M-62", "G-TARGET", say_in("6.3 Targets", "The essential exception covers the ▾ half.")
    ),
    Mutation(
        "M-63",
        "G-ORDER",
        sub_in(
            "8.3 Order", "then one sentence per account in", "then one sentence for all accounts in"
        ),
    ),
    Mutation("M-64", "G-FROW", line_sub("- **R-1", "a state carried by colour alone, ", "")),
    Mutation(
        "M-65",
        "G-CARRIER",
        line_sub(
            "- **R-5", "Every colour-carrying signal has", "Most colour-carrying signals have"
        ),
    ),
    Mutation(
        "M-66",
        "G-UNTOUCHED",
        sub_in("1.1 What this", "It edits no merged text:", "It edits merged text where obvious:"),
    ),
    Mutation(
        "M-67",
        "G-SIGNOFF",
        line_sub(
            "**Ticket:**",
            "nothing here claims the owner's `approved`",
            "the owner's `approved` is taken as given",
        ),
    ),
    Mutation("M-68", "G-GROWS", line_sub("- **G-03**", G03_SR, "")),
    Mutation(
        "M-69",
        "G-AROW",
        row_sub(A_HEAD, "A-01", "the stale and kill-switch locks once", "an account lock once"),
    ),
    Mutation("M-70", "G-CONSUMERS", sub_in(HANDOFF_HEAD, "§6.1–§6.3, ", "")),
    Mutation("M-71", "G-NOHANDOFF", hand=lambda _h: "# E29-D05 hand-off\n\nA rows.\n"),
)

# the tool's own probes: X = a paraphrase a gate must catch, P = a pin class, N = must trip nothing
PROBES: tuple[Mutation, ...] = (
    Mutation(
        "X-01", "G-FOCUS", say_in("5.2 Sorting", "Focus stays tied to its position in the list.")
    ),
    Mutation(
        "X-02",
        "G-FOCUS",
        say_in("5.3 Virtualisation", "Focus is restored by row index after a sort."),
    ),
    Mutation(
        "X-03",
        "G-RESORT",
        say_in("5.2 Sorting", "An automatic re-sort runs while a row has focus."),
    ),
    Mutation(
        "X-04",
        "G-BODY",
        say_in("8.4 One surface", "After a revocation focus falls to the document body."),
    ),
    Mutation("X-05", "G-NEVER", say_in("8.3 Order", "The NO SL timer is spoken each second.")),
    Mutation(
        "X-06",
        "G-NEVER",
        row_edit(RT, "RT-13", 1, to("the selection count; the countdown, announced politely")),
    ),
    Mutation("X-07", "G-AT", say_in("14.1 Tasks", "We tested this with two screen readers.")),
    Mutation("X-08", "G-AT", say_in("14.1 Tasks", "VoiceOver says the row name.")),
    Mutation(
        "X-09", "G-HCBAR", say_in("11.2 Zoom", "All link labels meet the bar in high contrast.")
    ),
    Mutation(
        "X-10",
        "G-STATIC",
        say_in("11.1 Motion", "The highlight stays static under reduced motion."),
    ),
    Mutation("X-11", "G-NODRAW", say_in("17.2 Hand-offs", "A new board shows the routing.")),
    Mutation(
        "X-12", "G-NOHANDOFF", say_in("17.3 Deviations", "The handoff document lists the A rows.")
    ),
    Mutation(
        "X-13", "G-CLOSE-RULE", say_in("16.2 Gaps", "Each defect is corrected in the merged spec.")
    ),
    Mutation("X-14", "G-SIGNOFF", say_in("17.3 Deviations", "The CDO approved the review.")),
    Mutation("X-15", "G-CLOSE", say_in("17.3 Deviations", "This fixes #824.")),
    Mutation("X-16", "G-CLOSE", say_in("17.3 Deviations", "Resolved: #824.")),
    Mutation("X-17", "G-CHARSET", say_in("0. Status", "The pill reads ＬＩＶＥ.")),
    Mutation("X-18", "G-CHARSET", lambda s: s.replace("\n", "\r\n", 1)),
    Mutation(
        "X-19", "G-ANCHOR", sub_in(CONTRAST_HEAD, "**7<!--=BAR:hc-->:1", "**17<!--=BAR:hc-->:1")
    ),
    Mutation("X-20", "G-ANCHOR", say_in("6.3 Targets", "Rows are 24 px tall.")),
    Mutation("X-21", "G-ANCHOR", say_in("0. Status", "The review read 41 boards.")),
    Mutation("X-22", "G-MARKER", say_in("0. Status", "<!-- a hidden note -->")),
    Mutation("X-23", "G-HEX", say_in("0. Status", "The ring is #6EA1F5.")),
    Mutation("X-24", "G-PENDING", say_in("8.2 The correction", "The routing table is approved.")),
    Mutation("X-25", "G-FOWNER", row_edit(FINDING_HEAD, "F-02", 6, to("hcl-worker-1"))),
    Mutation("X-26", "G-ROUTE", row_edit(RT, "RT-11", 2, to("assertive"))),
    Mutation("X-27", "G-TRANS", row_edit(TRANS_HEAD, "T-03", 4, to("Mo-3: a short fade"))),
    Mutation("X-28", "G-KEYS", row_edit(KEY_HEAD, "K-13", 1, to("`Ctrl+Q`"))),
    Mutation("X-29", "G-AROW", row_edit(A_HEAD, "A-03", 3, to("real table semantics with scope"))),
    Mutation("X-30", "G-MUTLIST", row_edit(MUTATION_HEAD, "M-01", 2, to("G-NEVER: a wrong gate"))),
    Mutation("X-31", "G-ROUTE", say_in("8.3 Order", "NO SL speaks in the polite region.")),
    Mutation("X-32", "G-ROUTE", say_in("8.3 Order", "A Near crossing is announced assertively.")),
    Mutation("X-33", "G-FOCUS", say_in("5.3 Virtualisation", "Focus moves by row index.")),
    Mutation(
        "X-34", "G-RESORT", say_in("5.2 Sorting", "Rows re-sort live while a row is focused.")
    ),
    Mutation("X-35", "G-BODY", say_in("5.3 Virtualisation", "Then focus lands on the body.")),
    Mutation(
        "X-36", "G-STATIC", say_in("11.1 Motion", "The drawer slides in under reduced motion.")
    ),
    Mutation(
        "X-37", "G-HCBAR", say_in("11.2 Zoom", "Every link pair clears the bar in high contrast.")
    ),
    Mutation("X-38", "G-NODRAW", say_in("11.2 Zoom", "Board 12 is drawn again.")),
    Mutation(
        "X-39",
        "G-CLOSE-RULE",
        say_in("16.2 Gaps", "A finding closes once the design file is fixed."),
    ),
    Mutation("X-40", "G-PENDING", say_in("8.2 The correction", "The live-region table is final.")),
    Mutation("X-41", "G-AT", say_in("14.1 Tasks", "Screen readers announce each row update.")),
    Mutation(
        "P-01",
        "G-RULED-PIN",
        row_edit(
            "2. Inventory",
            "SCR-078 in its three scopes and every state",
            1,
            to("cited, not reviewed"),
        ),
    ),
    Mutation(
        "P-02",
        "G-RULED-PIN",
        in_lines(
            "1.2 Method",
            lambda ls: [("  " + ln if ln.startswith("A desk review") else ln) for ln in ls],
        ),
    ),
    Mutation(
        "P-03",
        "G-RULED-PIN",
        in_lines(
            "1.1 What this", lambda ls: [ln for i, ln in enumerate(ls) if not (i == 1 and not ln)]
        ),
    ),
    Mutation(
        "P-04",
        "G-RULED-PIN",
        line_sub(
            "### 16.3 Open questions",
            "16.3 Open questions (Q rows; default taken)",
            "16.2 Gaps (G rows)",
        ),
    ),
    Mutation(
        "P-05",
        "G-RULED-PIN",
        in_lines(
            "2. Inventory", lambda ls: [ls[0], *ls[1:][::-1]] if False else _swap_first_rows(ls)
        ),
    ),
    Mutation(
        "P-06",
        "G-RULED-PIN",
        sub_in("1.1 What this", "It edits no merged text: ", "It edits no merged text. "),
    ),
    Mutation("N-01", "", sub_in("1.1 What this", "It edits no merged", "It edits  no merged")),
    # the adversary lens's paraphrases (lens 2, A01..A40) that only the pins caught
    Mutation(
        "X-42",
        "G-FOCUS",
        rep(
            "all leave focus on the same row and cell",
            "all leave focus at the same screen row and cell, whatever row now sits there",
        ),
    ),
    Mutation(
        "X-43",
        "G-FOCUS",
        rep(
            "- **Leaving rows.**",
            "- **Place.** After a re-sort focus stays at the same height in the grid.\n"
            "- **Leaving rows.**",
        ),
    ),
    Mutation(
        "X-44",
        "G-RESORT",
        rep(
            "only an explicit header press re-sorts under focus",
            "live ordering keeps applying as data streams even with a focused row",
        ),
    ),
    Mutation(
        "X-45",
        "G-RESORT",
        rep(
            "A focused row never leaves while it is focused",
            "Rows reorder themselves on each update while the user sits on a row, and a focused"
            " row never leaves while it is focused",
        ),
    ),
    Mutation(
        "X-46",
        "G-NEVER",
        rep(
            "the countdown, ages, timers and flashes never speak",
            "the countdown is read to the user each second; ages, timers and flashes never speak",
        ),
    ),
    Mutation(
        "X-47",
        "G-NEVER",
        rep(
            "Desync stays polite pending",
            "Ages and timers are conveyed through the live region too. Desync stays polite pending",
        ),
    ),
    Mutation(
        "X-48",
        "G-AT",
        rep(
            "nothing in this section says what either reads",
            "screen-reader output was observed on both",
        ),
    ),
    Mutation(
        "X-49",
        "G-HCBAR",
        rep(
            "D04 §3 is the one definition;",
            "high contrast uses the same text bar as dark and light; D04 §3 is the one definition;",
        ),
    ),
    Mutation(
        "X-50",
        "G-STATIC",
        rep("D04's readings hold.", "D02's static highlight holds when motion is reduced."),
    ),
    Mutation(
        "X-51",
        "G-NODRAW",
        rep(
            "no new boards; nothing run on a screen reader",
            "two fresh Penpot boards illustrate the rule; nothing run on a screen reader",
        ),
    ),
    Mutation(
        "X-52",
        "G-CLOSE-RULE",
        rep(
            "A finding closes when it is routed",
            "A finding closes when its merged design is patched or it is routed",
        ),
    ),
    Mutation(
        "X-53",
        "G-SIGNOFF",
        rep(
            "the ten-item owner walkthrough is posted on #824",
            "the CDO endorsed the review; the ten-item owner walkthrough is posted on #824",
        ),
    ),
    Mutation(
        "X-54",
        "G-PENDING",
        rep(
            "Two regions, one polite and one assertive",
            "The live-region routing is binding as written. Two regions, one polite and one"
            " assertive",
        ),
    ),
    Mutation(
        "X-55",
        "G-ROUTE",
        rep(
            "Desync stays polite pending",
            "A missing stop-loss is spoken without interrupting the user. Desync stays polite"
            " pending",
        ),
    ),
    Mutation(
        "X-56",
        "G-ROUTE",
        rep(
            "Desync stays polite pending",
            "A crossing into Critical waits until the user is idle before it speaks. Desync"
            " stays polite pending",
        ),
    ),
    Mutation(
        "X-57",
        "G-ROUTE",
        rep(
            "Desync stays polite pending",
            "The selection count interrupts whatever is being read. Desync stays polite pending",
        ),
    ),
    Mutation(
        "X-58",
        "G-REVOKE",
        rep(
            "and focus moves to that account's",
            "and focus is released rather than moved to that account's",
        ),
    ),
    Mutation(
        "X-59",
        "G-FOCUS",
        rep(
            "A focused row never leaves while it is focused",
            "A focused row may leave at once even while focused",
        ),
    ),
    Mutation(
        "X-60",
        "G-CLOSE-RULE",
        rep(
            "A finding closes when it is routed",
            "A finding closes when the reviewer marks it done, or when it is routed",
        ),
    ),
    Mutation(
        "X-61",
        "G-FROW",
        rep("a state carried by colour alone, or an announcement", "an announcement"),
    ),
    Mutation(
        "X-62",
        "G-CARRIER",
        rep("Every colour-carrying signal has a word", "Most colour-carrying signals have a word"),
    ),
    Mutation(
        "X-63",
        "G-TARGET",
        rep("No essential exception is used", "The essential exception covers the ▾ half"),
    ),
    Mutation(
        "X-64",
        "G-ORDER",
        rep(
            "then one sentence per account in the slot's order",
            "then one sentence for all accounts together",
        ),
    ),
    Mutation(
        "X-65",
        "G-UNTOUCHED",
        rep("It edits no merged text:", "It edits merged text only where a defect is obvious:"),
    ),
    Mutation(
        "X-66",
        "G-SCOPE",
        rep(
            "no visible string names or counts an out-of-scope leg or account",
            "a visible string may count but never name an out-of-scope leg or account",
        ),
    ),
    Mutation(
        "X-67",
        "G-SIGNOFF",
        rep(
            "nothing here claims the owner's `approved`",
            "the owner's `approved` is taken as given",
        ),
    ),
    Mutation("X-68", "G-SCRIPT", rep("without flooding", "including every tick")),
    Mutation("X-69", "G-CHARSET", rep("never to an index", "ne\u200bver to an index")),
    Mutation("X-70", "G-CHARSET", rep("never to an index", "nev\u00ader to an index")),
    Mutation("X-71", "G-CHARSET", say_in("0. Status", "The pill reads LIV\u0415.")),
    Mutation("X-72", "G-CELLS", row_edit(RT, "RT-13", 5, lambda c: c + " | an extra cell")),
)


def _swap_first_rows(lines: list[str]) -> list[str]:
    idx = [i for i, ln in enumerate(lines) if ln.startswith("|") and not is_rule(ln)][1:3]
    if len(idx) == 2:
        lines[idx[0]], lines[idx[1]] = lines[idx[1]], lines[idx[0]]
    return lines


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def plan_paths() -> tuple[tuple[str, Path], ...]:
    out = []
    for nn in UNTOUCHED:
        rel = cite_path(nn)
        if rel is None:
            raise SystemExit(f"FAIL parse: {nn} has no path")
        out.append((nn, ROOT / rel))
    return tuple(out)


DELETED = "\x00deleted\x00"  # a working-tree untouched file that is gone (G-UNTOUCHED names it)


def read_plans() -> tuple[tuple[str, str], ...]:
    return tuple(
        (nn, p.read_bytes().decode("utf-8") if p.exists() else DELETED) for nn, p in plan_paths()
    )


def ascii_line(s: str) -> str:
    """ASCII-only output (a cp1252 console never crashes): every other char as \\uXXXX."""
    return s.encode("ascii", "backslashreplace").decode("ascii")


def selftest(spec: str, hand: str | None, paths: tuple[Path, ...]) -> tuple[bool, list[str]]:
    on_disk = digest(paths)
    plans = read_plans()
    values = compute(spec)
    spec_f, _ = fill(spec, values)
    values = compute(spec_f)  # frozen at the filled baseline
    hand_f = fill(hand, values)[0] if hand is not None else None
    extra = tuple(other_d05_files())
    base_t = Texts(spec_f, hand_f, plans, values, bool(extra), extra)
    base_fails, _notes, base_warns, _ = audit(base_t, git_fetch)
    lines = [f"baseline (filled in memory): {len(base_fails)} FAIL, {len(base_warns)} WARN"]
    lines += [f"  baseline FAIL {x[:160]}" for x in base_fails]
    ok = not base_fails
    probe = fence_pin_probe()
    lines.append(f"  fence probe: {'ok' if not probe else 'FAIL'}")
    lines += [f"    {x}" for x in probe]
    port = cvd_port_problems()
    lines.append(f"  CVD port self-test (two pinned hex inputs): {'ok' if not port else 'FAIL'}")
    ok = ok and not probe and not port
    pristine = digest_texts(spec_f, *(x for _n, x in plans))
    for mu in (*MUTATIONS, *PROBES):
        s = mu.spec(spec_f) if mu.spec else spec_f
        new_plans = plans
        if mu.plan:
            nn, edit = mu.plan
            new_plans = tuple((k, edit(x) if k == nn else x) for k, x in plans)
        h = mu.hand(hand_f or "") if mu.hand else hand_f
        if s == spec_f and new_plans == plans and h == hand_f:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        try:
            fails, _n2, _w, _c = audit(
                Texts(s, h, new_plans, values, base_t.hand_exists, extra), git_fetch
            )
        except SystemExit as exc:
            fails = [str(exc)]
        new = [x for x in fails if x not in base_fails]
        if mu.gate:
            named = [x for x in new if x.startswith(f"[{mu.gate}]")]
            hit = bool(named) and len(new) == 1
        else:
            named, hit = [], not new
        restored = digest_texts(spec_f, *(x for _n, x in plans)) == pristine
        restored = restored and digest(paths) == on_disk
        ok = ok and hit and restored
        first = (named or new or ["nothing new"])[0][:110]
        lines.append(
            f"  {mu.mid} [{mu.gate or 'none'}] {'ok' if hit else 'MISSED'} ({len(new)} new"
            f"{'' if restored else ', NOT RESTORED'}) - {first}"
        )
        if not hit:
            lines += [f"      new: {x[:200]}" for x in new]
    return ok, [ascii_line(x) for x in lines]


# ---------------------------------------------------------------------------- main


def write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E29-D05 a11y review audit (module docstring)")
    ap.add_argument("--check", nargs="?", const=SPEC_REL, metavar="SPEC", help="audit the spec")
    ap.add_argument("--handoff", metavar="F", help="also audit this hand-off file")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="replace placeholders, then check")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="apply every mutation")
    ap.add_argument("--repin-ruled", action="store_true", help=f"rewrite {RULED_PIN_TXT}")
    args = ap.parse_args(argv)
    spec_path = ROOT / (args.check or SPEC_REL)
    hand_path = ROOT / args.handoff if args.handoff else None
    spec = spec_path.read_bytes().decode("utf-8")
    hand = hand_path.read_bytes().decode("utf-8") if hand_path else None
    extra = tuple(other_d05_files())
    hand_exists = bool(extra)
    if args.repin_ruled:
        left = PLACEHOLDER.findall(CODE.sub("", spec + (hand or "")))
        if left:
            print(f"FAIL --repin-ruled: {len(left)} unfilled placeholders; run --fill first")
            return 1
        t = Texts(spec, hand, (), compute(spec), hand_exists, extra)
        units = ruled_units(t)
        write_text(ROOT / RULED_PIN_TXT, write_pins(units))
        print(f"--repin-ruled: {len(units)} units pinned in {RULED_PIN_TXT}")
        return 0
    if args.self_test:
        extra = (hand_path,) if hand_path else ()
        paths = (spec_path, ROOT / RULED_PIN_TXT, *extra, *(p for _n, p in plan_paths()))
        ok, lines = selftest(spec, hand, paths)
        print("\n".join(lines))
        n = len(MUTATIONS)
        print(
            f"--self-test: {'ok' if ok else 'FAIL'} - {n} mutations"
            f" + {len(PROBES)} probes in memory"
        )
        return 0 if ok else 1
    values = compute(spec)
    if args.fill:
        spec, unknown = fill(spec, values)
        write_text(spec_path, spec)
        if hand is not None and hand_path is not None:
            hand, unknown_h = fill(hand, values)
            write_text(hand_path, hand)
            unknown += unknown_h
        for u in unknown:
            print(f"FAIL --fill: no value for {u}")
        values = compute(spec)
    if args.json and not (args.check or args.fill):
        print(json.dumps({"values": values}, ensure_ascii=True, indent=1))
        return 0
    t = Texts(spec, hand, read_plans(), values, hand_exists, extra)
    fails, notes, warns, n = audit(t, git_fetch)
    if args.json:
        doc = {"values": values, "fails": fails, "notes": notes, "warnings": warns, "cites": n}
        print(json.dumps(doc, ensure_ascii=True, indent=1))
    else:
        gates = len(LEXICON_GATES) + len(MEASURED_GATES) + 5
        out = [f"## E29-D05 audit of {spec_path.relative_to(ROOT)} at base {BASE}"]
        out.append(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        out += [f"WARN {w}" for w in warns] + notes
        out += [f"FAIL {x}" for x in fails] or ["OK - every gate passed"]
        out.append(f"summary: {len(fails)} FAIL, {len(warns)} WARN, {len(notes)} NOTE")
        print("\n".join(ascii_line(x) for x in out))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
