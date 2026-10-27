#!/usr/bin/env python3
"""E35-D04 (#939) audit: the accessibility design review of the six rule-engine screens (spec only).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the token JSON (`themes.json` layering: dark = primitives
+ semantic-dark, light = + semantic-light, hc = + semantic-hc), the plan texts, the merged E35
specs D02 / D03 and their hand-offs, the E35-D01 memo, E36-D03 / E36-D04, the `PAIRS_TABLE`
literals of `e35_d02_sim_arming_audit.py` and `e36_d03_screens_audit.py` (parsed, never imported),
D03 §13's table, the reserved-key fixture of E11-D07 and the keymap; then this ticket's spec from
the working tree, and the working-tree files the review must leave untouched (compared with
`git merge-base HEAD origin/main`, never a fixed sha). RULED BQ-33: no hand-off file exists.

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: COUNT (boards and renders at
   the base, the spec's own table rows, the fixture's matches per K row, utterances), BAR / TIME /
   RATE / GEOM / LEN (parsed from the cited lines or the token JSON), CONTRAST (WCAG 2.x, two
   decimals rounded half up, truncated instead when rounding would lift a value onto a bar it
   fails), CVD (CIE76 dE, the minimum over three themes and three simulations, one decimal
   truncated), HEX (a resolved token). `--fill` writes `VALUE<!--=KEY-->`; `--check` re-derives
   every anchored value (G-ANCHOR, with a left boundary: the value must not be the tail of a
   longer number) and FAILs on a figure typed by hand.
2. **Lexicon gates first.** Each reads every rendered unit (table rows cell by cell, bullets,
   paragraphs, headings, fence lines) after the comment strip, NFKC, markup dropped, dashes to
   spaces, lower case; quoted copy is not a claim; a negation covers its term within five words and
   a list coordinated after it. The mutation table (§15) and the A table's Old cells are skipped.
   Synonym sets, not single phrases, carry each ruled behaviour (`*_TERM` constants), and a
   need-check keeps each ruled sentence's own words (a falsity frame around them counts as lost);
   the pins stay the backstop for the forms no lexicon lists. Structure first: G-CHARSET (CR,
   trailing whitespace, a char NFKC changes, a format char, a non-Latin letter) and G-CELLS (a
   table row whose cell count differs from its header's; GFM drops the cells past the header).
3. **Then the measured and table gates** (column by column), then the cites, then the pins.
4. **Pins (G-RULED-PIN).** Whole-document default-deny: every heading, table row (by lead cell),
   rule line, prose sentence (`s<k>`) and fenced block, keyed by heading path + occurrence `#n`,
   with each region's line shape (one tag per line: `.` blank, `h`, `t`, `r`, `b`, `n`, `p`, `f`;
   prose, bullet and numbered tags carry their sentence count, an indent its `>n`).
   `--repin-ruled` is the only writer. NOTE demotion: a pin finding in a section another gate
   already FAILs prints as a NOTE, so one wrong form yields one FAIL.
5. **--self-test** applies every §15 mutation in memory (plus the tool's X, P and N probes; a
   mutation may also pass a hand-off, which RULED BQ-33 forbids under any name): each must add
   exactly one FAIL from the gate it names (N probes none), and every text is restored
   byte-identically (sha256 in memory and on disk). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e35_d04_a11y_review_audit.py --check [SPEC] [--handoff F] [--json]
      [--fill]
  python3 -I docs/design/_tools/e35_d04_a11y_review_audit.py --self-test
  python3 -I docs/design/_tools/e35_d04_a11y_review_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL. G-UNTOUCHED reads the local `origin/main`: run
`git fetch` first, or a stale ref fails closed (a false FAIL, never a false pass).
"""

from __future__ import annotations

import argparse
import ast
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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "00ec6976f6"  # every cite was read here (the spec's Inputs line)
HEAD = "origin/main"  # drift is reported against this ref (WARN, never FAIL)
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E35/E35-D04.md"
RULED_PIN_TXT = "docs/design/_tools/e35_d04_ruled_pins.txt"
TOKENS_REL = "packages/ui/tokens"
FIXTURE_REL = "docs/design/_tools/e11_d07_sr_reserved_keys.json"
D02_TOOL_REL = "docs/design/_tools/e35_d02_sim_arming_audit.py"
E36_TOOL_REL = "docs/design/_tools/e36_d03_screens_audit.py"
IMG_E35 = "docs/design/E35/img"
IMG_E36 = "docs/design/E36/img"
FEATURES_REL = "apps/web/src/features"
UI_SRC_REL = "packages/ui/src"
RULING_ID = "6436378128"
BQ_LIST_ID = "6436079208"
PENDING = "PROPOSED, owner approval pending (#2701)"
# "spec <= ~600, hand-off <= ~150" (the brief) against RULED BQ-1's "about 900": RULED BQ-33 ships
# no hand-off, so the spec carries the hand-off's rows; the lens fold sets RULED BQ-1's 900
SPEC_LINE_BUDGET = 900
HAND_LINE_BUDGET = 150

CITE_FILES = {
    "D02": "docs/design/E35/E35-D02.md",
    "D02H": "docs/design/E35/E35-D02-handoff.md",
    "D03": "docs/design/E35/E35-D03.md",
    "D03H": "docs/design/E35/E35-D03-handoff.md",
    "MEMO": "docs/design/research/e35-rule-arming-trust.md",
    "KM": "apps/web/src/keymap/keymap.json",
    "RK": "apps/web/src/keymap/reserved-keys.json",
    "README": "docs/design/README.md",
    "E40R": "docs/design/a11y/e40-alerts-a11y-review.md",
    "E40A": "docs/design/research/e40-alert-attention.md",
    "E35.json": "docs/plan/backlog/E35.json",
}
# never edited by this ticket (RULED BQ-3 and the ruling's "untouched" line); compared with the
# merge-base of HEAD and origin/main, never a fixed sha
UNTOUCHED = (
    "05",
    "06",
    "14",
    "15",
    "16",
    "D02",
    "D02H",
    "D03",
    "D03H",
    "MEMO",
    "E36-D03",
    "E36-D04",
    "KM",
    "RK",
)
UNMERGED = ("E35-D05", "E35-Q06")  # named only, never cited or quoted
CONSUMERS = ("#940", "#1113", "#1048", "#1049", "#874", "#958")  # RULED BQ-33
STORIES = ("#1048", "#1049", "#940", "#1113")  # the body names them (the brief; BQ-1)

THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SIMS = ("protanopia", "deuteranopia", "tritanopia")
GREY = "greyscale"  # RULED BQ-23's fourth leg: Rec. 601 luma, floored (cvd_sim.py, D02:422)

# the clause checklist of RULED BQ-5 (one row each in §3)
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
    "14:0.5.2",
    "14:0.5.5",
    "14:0.5.6",
    "02:180",
)
# the WCAG 2.2 cross-walk of RULED BQ-5 (one row each in §4)
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
    "2.4.3",
    "2.4.6",
    "2.4.7",
    "2.4.11",
    "2.5.3",
    "2.5.7",
    "2.5.8",
    "3.2.1",
    "3.2.2",
    "3.3.1",
    "3.3.3",
    "3.3.4",
    "4.1.2",
    "4.1.3",
    "2.3.3 (AAA)",
    "2.4.13 (AAA)",
)
VERDICT = re.compile(
    r"^(?:compliant|at risk|non-compliant|out of scope — E\d\d\b.*"
    r"|not yet decidable — routed to E35-Q06)$"
)
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
# clauses whose verdict a ruled reading fixes: (verdict, words its row must carry)
CLAUSE_RULED: dict[str, tuple[str, ...]] = {
    "6.2b": ("at risk", "F-01"),  # RULED BQ-16: the double voice, a Major F row
    "3.4.2": ("at risk", "F-02"),  # RULED BQ-14: SCR-084's table, a Major F row
    "5.6": ("at risk", "F-03", "F-04", "F-05"),  # RULED BQ-22: the three high-contrast rows
    "6.2a": ("at risk", "F-11", "G-01"),  # RULED BQ-18 / BQ-15: progress and the pill cadence
    "7.4": ("at risk", "F-13..F-16"),  # RULED BQ-27: the motion rows
    "7.2": ("at risk", "F-17"),  # RULED BQ-27: the looping skeleton
    "5.5": ("at risk", "F-06", "interim path"),  # the lens fold: E10-D04 F-12's Minor grade
    "3.4.7": ("at risk", "G-10", "interim path"),  # the lens fold: widths unstated
    "5.1": ("compliant", "G-14", "C-25"),  # the lens fold: D03 keeps tertiary off the row
}

# RULED BQ-17 (PROPOSED): the routing of every event class; (event pattern, region, new to `05`)
ROUTES: tuple[tuple[str, str, bool], ...] = (
    (r"\barm refused at the point of action\b", "assertive", True),
    (r"\breturned from step up drop\b", "assertive", True),
    (r"\bsimulation failed\b", "assertive", True),
    (r"\bresolver's refusal\b", "assertive", True),
    (r"\bexport check that withholds a file\b", "assertive", True),
    (r"\benvironment change after d02 g5\b", "polite", True),
    (r"^armed; disarmed$", "polite", True),
    (r"^an arrow or a press on a t2 control$", "polite", True),
    (r"\bvalidity press\b", "polite", True),
    (r"\bsimulation complete or partial\b", "polite", True),
    (r"^the filter result$", "polite", True),
    (r"^the pill$", "polite", True),
    (r"^copied$", "polite", True),
    (r"\border set\b", "polite", True),
    (r"\bimport pre check count\b.*\bimport outcome\b", "polite", True),
    (r"^progress$", "polite", True),
    (r"\bper evaluation events\b.*\bper firing rows\b", "none", True),
    (r"\bstep up's countdown\b", "none", True),
    (r"\bimport count per keystroke\b", "none", True),
    (r"\brule triggered\b.*\be40's one announcer\b", "none", False),
    (r"\bmove up / move down move\b", "polite", True),  # D03:145, :354 (BQ-5 (g))
    (r"\bthe pill pressed\b", "polite", True),  # D03:356
    (r"^pending \(the text is read on focus\)$", "none", True),  # D02:288
    (r"\bimport button's count after the pause\b", "polite", True),  # D03:360
)
# RULED BQ-17's assertive set, in the ruling's words (A-01 carries them to `05`)
A01_RULED = (
    "an arm refused at the point of action",
    "a returned from step up drop",
    "a simulation failed",
    "the resolver's refusal",
    "the export check that withholds a file",
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
    r"mutations?|questions?|signals?|strings?|lines?|rows?|cells?|units?|elements?|frames?|"
    r"times|items?|characters?)\b",
    re.IGNORECASE,
)
CITE_GROUP = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:D0[23]H?|MEMO|README|E40[RA]|E\d\d-D\d\d)\b)) ?"
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
    """Two decimals, rounded half up as the merged specs print them, except that a value under a
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
CVD_PINNED = {  # protan, deutan, tritan, then greyscale
    "#2EBD59": ("#B4B458", "#A3A35D", "#00B9A6", "#868686"),
    "#E5484D": ("#6B6B4E", "#8F8F44", "#FB194B", "#777777"),
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


GREY_SOURCE_REL = "docs/design/_tools/cvd_sim.py"  # the greyscale leg's source (RULED BQ-23)
GREY_WEIGHTS = (0.299, 0.587, 0.114)  # Rec. 601, applied to the sRGB bytes, then floored


def simulate(hex6: str, deficiency: str) -> str:
    if deficiency == GREY:
        r, g, b = rgb(hex6)
        y = int(GREY_WEIGHTS[0] * r + GREY_WEIGHTS[1] * g + GREY_WEIGHTS[2] * b)
        return f"#{y:02X}{y:02X}{y:02X}"
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


CVD_SOURCE_REL = "docs/research/_tools/cvd_simulate.py"  # the port's source (RULED BQ-23)


def cvd_source_problems() -> list[str]:
    """The carried constants against the source's literals at the base (parsed, never imported)."""
    want: dict[str, object] = {
        "RGB_TO_LMS": RGB_TO_LMS,
        "LMS_TO_RGB": LMS_TO_RGB,
        "PROJECTIONS": PROJECTIONS,
        "TRITAN_MACHADO": TRITAN_MACHADO,
    }
    got: dict[str, object] = {}
    for node in ast.parse(at_base(CVD_SOURCE_REL)).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in want:
            got[str(getattr(node.targets[0], "id", ""))] = ast.literal_eval(node.value)
    bad = [f"{k} differs from {CVD_SOURCE_REL}" for k, v in want.items() if got.get(k) != v]
    grey = re.findall(r"arr\[\.\.\., \d\] \* ([0-9.]+)", at_base(GREY_SOURCE_REL))
    if tuple(float(x) for x in grey) != GREY_WEIGHTS:
        bad.append(f"GREY_WEIGHTS differ from {GREY_SOURCE_REL}'s luma weights {grey}")
    return bad


def cvd_port_problems() -> list[str]:
    bad: list[str] = cvd_source_problems()
    for src, want in CVD_PINNED.items():
        got = tuple(simulate(src, s) for s in (*SIMS, GREY))
        if got != want:
            bad.append(f"{src} simulates to {got}, pinned {want}")
    return bad


# ---------------------------------------------------------------------------- the contrast union


@dataclass(frozen=True)
class Pair:
    fg: str
    bg: str
    role: str  # text | non-text | rejected | decorative | measured
    src: str  # D02 | D03 | E36 | composed
    printed: tuple[str, ...] = ()  # the source's printed dark / light / hc values, when it prints


def role_of(raw: str) -> str:
    r = raw.strip()
    if r.startswith("rejected"):
        return "rejected"
    return {"text": "text", "hc-text": "text", "non-text": "non-text"}.get(r, "decorative")


def literal_table(rel: str, name: str) -> str:
    """A module-level string literal of a merged tool at the base, parsed (never imported)."""
    tree = ast.parse(at_base(rel))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == name:
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise SystemExit(f"FAIL parse: no {name} string in {rel}")


def d02_pairs() -> list[Pair]:
    """D02 §10's pairs: the `PAIRS_TABLE` literal of its tool (element | fg | bg | role)."""
    out: list[Pair] = []
    for ln in literal_table(D02_TOOL_REL, "PAIRS_TABLE").strip().split("\n"):
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) == 4:
            out.append(Pair(cells[1], cells[2], role_of(cells[3]), "D02"))
    return out


def e36_pairs() -> list[Pair]:
    """E36-D03 §12's pairs: its tool's `PAIRS_TABLE` (a 2-space line continues the record)."""
    text = literal_table(E36_TOOL_REL, "PAIRS_TABLE").strip().replace("\n  |", " |")
    out: list[Pair] = []
    for ln in text.split("\n"):
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) >= 4:
            out.append(Pair(cells[1], cells[2], role_of(cells[3]), "E36"))
    return out


def d03_pairs() -> list[Pair]:
    """D03 §13's table at the base (`# | Pair | Role | dark | light | hc | ...`)."""
    block = section(at_base(CITE_FILES["D03"]), "13. Themes and densities")
    out: list[Pair] = []
    for r in table(block):
        toks = re.findall(r"`(color\.[^`]+)`", r[1]) if len(r) > 5 else []
        if len(toks) == 2:
            out.append(Pair(toks[0], toks[1], role_of(r[2]), "D03", (r[3], r[4], r[5])))
    return out


_T = "color.text."
# the compositions RULED BQ-22 names; keys are the spec's CONTRAST anchors
COMPOSED: dict[str, tuple[str, str, str]] = {
    "t2.selected": (_T + "tertiary", "color.surface.selected", "measured"),  # G-14, never gated
    "t2.action": (_T + "tertiary", "color.action.selected", "measured"),  # `15`:531 (C-25)
    "t2fix.selected": (_T + "secondary", "color.surface.selected", "text"),
    "focus.warning": ("color.focus.ring", "color.status.warning.subtle", "non-text"),
    "focus.danger": ("color.focus.ring", "color.status.danger.subtle", "non-text"),
}
HC_PAIRS: dict[str, tuple[str, str]] = {
    "hc.flatten": (_T + "on-action", "color.status.danger.default"),
    "hc.link.overlay": (_T + "link", "color.surface.overlay"),
    "hc.link.danger": (_T + "link", "color.status.danger.subtle"),
}


def composed_pairs() -> list[Pair]:
    return [Pair(fg, bg, role, "composed") for fg, bg, role in COMPOSED.values()]


@functools.lru_cache(maxsize=1)
def union() -> tuple[Pair, ...]:
    return tuple(d02_pairs() + d03_pairs() + e36_pairs() + composed_pairs())


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


RENDER = re.compile(r"-(?:greyscale|deuteranopia|protanopia|tritanopia)\.png$")


def board_counts() -> dict[str, str]:
    e35 = [Path(n).name for n in ls_tree(BASE, IMG_E35)]
    e36 = [Path(n).name for n in ls_tree(BASE, IMG_E36)]

    def render(x: str, names: list[str]) -> bool:
        """A CVD render: the name minus its simulation suffix is another board's export."""
        return RENDER.search(x) is not None and RENDER.sub(".png", x) in names

    def boards(names: list[str], prefix: str) -> int:
        return len([x for x in names if re.match(rf"{prefix}-\d\d-", x) and not render(x, names)])

    d02, d03 = boards(e35, "E35-D02"), boards(e35, "E35-D03")
    return {
        "COUNT:boards.d02": str(d02),
        "COUNT:boards.d03": str(d03),
        "COUNT:boards.merged": str(d02 + d03),
        "COUNT:renders.d03": str(
            len([x for x in e35 if x.startswith("E35-D03-") and render(x, e35)])
        ),
        "COUNT:boards.e36d03": str(boards(e36, "E36-D03")),
    }


def time_values() -> dict[str, str]:
    run = grab(r"<=(\d+) s", base_line("14", 1923), "`14`:1923 run")
    lane = grab(r"≤1 ambient announcement per (\d+) s", base_line("E36-D03", 342), "lane")
    throttle = grab(r"1 update / (\d+)s", base_line("05", 147), "`05`:147")
    step = re.search(r"at (\d+) s and (\d+) s only", strip_comments(base_line("E09-D06", 67)))
    if not step:
        raise SystemExit("FAIL parse: E09-D06:67 step-up marks")
    return {
        "TIME:throttle": throttle,
        "TIME:lane": lane,
        "TIME:pause": grab(r">(\d+)s", base_line("05", 207), "`05`:207"),
        "TIME:guard": grab(r"activation for (\d+) ms", base_line("D02", 273), "D02:273"),
        "TIME:count.pause": grab(r"pause of (\d+) ms", base_line("D03", 360), "D03:360"),
        "TIME:stepup.first": step[1],
        "TIME:stepup.last": step[2],
        "TIME:d02.progress": grab(r"at most every (\d+) s", base_line("D02", 150), "D02:150"),
        "TIME:run": run,
        "RATE:flash.limit": grab(
            r"more than (\d+) times per second", base_line("05", 208), "`05`:208"
        ),
        "COUNT:utter.lane": str(int(run) // int(lane)),
        "COUNT:utter.default": str(int(run) // int(throttle)),
    }


def geom_values() -> dict[str, str]:
    frame = re.search(r"and (\d+) × (\d+) \(", strip_comments(base_line("D02", 277)))
    footer = re.search(
        r"footer (\d+) px compact / (\d+) comfortable", strip_comments(base_line("D02", 175))
    )
    if not frame or not footer:
        raise SystemExit("FAIL parse: D02:277 frame or D02:175 footer")

    def tok(name: str) -> str:
        v = resolve("dark", name)
        if not re.fullmatch(r"\d+", v):
            raise SystemExit(f"FAIL parse: token {name} = {v}")
        return v

    ring = base_line("D02", 187)
    return {
        "GEOM:focus.width": grab(r"(\d+) px `color\.focus\.ring` outside", ring, "D02:187 ring"),
        "GEOM:halo": grab(r"(\d+) px `color\.surface\.canvas` halo", ring, "D02:187 halo"),
        "GEOM:target.min": tok("size.target.min"),
        "GEOM:target.comfortable": tok("size.control.comfortable"),
        "GEOM:zoom": grab(r"(\d+)% browser", base_line("05", 131), "`05`:131 zoom"),
        "GEOM:frame.w": frame[1],
        "GEOM:frame.h": frame[2],
        "GEOM:footer.compact": footer[1],
        "GEOM:footer.comfortable": footer[2],
        "GEOM:textscale": grab(r"`100\|112\|(\d+)\|150`", base_line("16", 138), "`16`:138"),
        "GEOM:links.cell": grab(r"\*\*Links\*\* (\d+)", base_line("D03", 184), "D03:184"),
        "LEN:reason.max": grab(r"≤ (\d+) characters", base_line("D02", 138), "D02:138"),
        "LEN:override": grab(r"≤ (\d+) chars", base_line("D02", 219), "D02:219"),
    }


_S = "color.status."
# RULED BQ-23 (as proposed): every pair of colour tokens one carrier row of §9.1 binds, plus the
# two fill pairs read across rows (CVD_CROSS); keys are the spec's CVD anchors
CVD_PAIRS: dict[str, tuple[str, str]] = {
    "demo-live": ("color.env.demo", "color.env.live"),
    "success-danger": (_S + "success.strong", _S + "danger.strong"),
    "success-warning": (_S + "success.strong", _S + "warning.strong"),
    "warning-danger": (_S + "warning.strong", _S + "danger.strong"),
    "warning.subtle-strong": (_S + "warning.subtle", _S + "warning.strong"),
    "danger.subtle-strong": (_S + "danger.subtle", _S + "danger.strong"),
    "warning.subtle-success": (_S + "warning.subtle", _S + "success.strong"),
    "success-info.subtle": (_S + "success.strong", _S + "info.subtle"),
    "warning-danger.subtle": (_S + "warning.subtle", _S + "danger.subtle"),
    "info-warning": (_S + "info.subtle", _S + "warning.subtle"),
}
CVD_CROSS = frozenset({"warning-danger.subtle", "info-warning"})


def cvd_min(a: str, b: str) -> float:
    best = math.inf
    for t in THEMES:
        ha, hb = hex_of(t, a), hex_of(t, b)
        if ha is None or hb is None:
            raise SystemExit(f"FAIL parse: {a} / {b} do not resolve in {t}")
        for s in (*SIMS, GREY):
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


def d03_agreement() -> tuple[int, int]:
    """D03 §13's printed cells against the re-measure (two decimals)."""
    agree = total = 0
    for p in union():
        if p.src != "D03":
            continue
        for t, printed in zip(THEMES, p.printed, strict=True):
            r = ratio(t, p.fg, p.bg)
            if not re.fullmatch(r"\d+\.\d+", printed) or r is None:
                continue
            total += 1
            agree += int(abs(float(printed) - r) <= 0.0051)
    return agree, total


def contrast_values() -> dict[str, str]:
    out: dict[str, str] = {}
    for k, (fg, bg) in HC_PAIRS.items():
        r = ratio("hc", fg, bg)
        out[f"CONTRAST:{k}"] = round2(r) if r is not None else "MISSING"
    for k, (fg, bg, _role) in COMPOSED.items():
        for t in THEMES:
            r = ratio(t, fg, bg)
            out[f"CONTRAST:{k}.{t}"] = round2(r) if r is not None else "MISSING"
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
    out["COUNT:pairs.d02"] = str(len(srcs.get("D02", set())))
    out["COUNT:pairs.d03"] = str(len(srcs.get("D03", set())))
    out["COUNT:pairs.e36"] = str(len(srcs.get("E36", set())))
    out["COUNT:pairs.union"] = str(len({(p.fg, p.bg) for p in union()}))
    out["COUNT:pairs.hc-under"] = str(len(hc_under()))
    agree, total = d03_agreement()
    out["COUNT:d03.agree"] = str(agree)
    out["COUNT:d03.values"] = str(total)
    for k, (a, b) in CVD_PAIRS.items():
        out[f"CVD:{k}"] = trunc1(cvd_min(a, b))
    out["HEX:sunken.dark"] = hex_of("dark", "color.surface.sunken") or "?"
    out["HEX:danger.strong.light"] = hex_of("light", _S + "danger.strong") or "?"
    out["HEX:danger.strong.dark"] = hex_of("dark", _S + "danger.strong") or "?"
    return out


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
    v.update(time_values())
    v.update(geom_values())
    v.update(contrast_values())
    v["COUNT:fx.rows"] = str(len(fixture()))
    v["BUDGET:lines.spec"] = str(SPEC_LINE_BUDGET)
    return tuple(sorted(v.items()))


CLAUSE_HEAD = "3. Clause by clause"
SC_HEAD = "4. WCAG 2.2 cross-walk"
FOCUS_HEAD = "5.1 The focus contract"
RADIO_HEAD = "5.2 Radio groups"
DRAG_HEAD = "5.3 Drag"
KEY_HEAD = "5.4 Keys"
OBSCURED_HEAD = "5.5 Focus visible"
TARGET_HEAD = "5.6 Targets"
FORMS_HEAD = "6.1 Forms"
ARM_HEAD = "6.2 Arming"
TABLES_HEAD = "6.3 Tables"
IR_HEAD = "6.4 SCR-088"
NAME_HEAD = "7.1 The names table"
ROUTE_HEAD = "8.1 The routing table"
LOG_HEAD = "8.2 SCR-087"
FIRE_HEAD = "8.3 Rule fires"
PROGRESS_HEAD = "8.4 Progress"
CARRIER_HEAD = "9.1 The carrier table"
CONTRAST_HEAD = "10. Contrast"
MOTION_HEAD = "11.1 Motion"
TIME_HEAD = "11.2 Time limits"
ZOOM_HEAD = "11.3 Zoom"
RBAC_HEAD = "11.4 RBAC"
TRANS_HEAD = "12. The transition register"
FINDING_HEAD = "13. The finding register"
SR_HEAD = "14.1 Tasks"
AL_HEAD = "14.2 The acceptance list"
SCRIPT_HEAD = "14.3 "
C_HEAD = "16.1 Contradictions"
G_HEAD = "16.2 Gaps"
Q_HEAD = "16.3 Open questions"
A_HEAD = A_TABLE_HEAD
DOD_HEAD = "17.1 DoD"
HANDOFF_HEAD = "17.2 Hand-offs"
WALK_HEAD = "17.3 The owner walkthrough"


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
    out["COUNT:names"] = str(len(table(section(spec, NAME_HEAD))))
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
    ("05", 11, "no timing limits"),
    ("05", 30, "no keyboard trap"),
    ("05", 86, "`Ctrl+W`"),
    ("05", 95, "Roving tabindex"),
    ("05", 96, "Only explicit user action or an explicit modal alert"),
    ("05", 97, "return focus to the triggering element on close"),
    ("05", 99, "Focus Not Obscured"),
    ("05", 100, "≥24×24 CSS px"),
    ("05", 101, "Dragging Movements"),
    ("05", 125, "≥4.5:1"),
    ("05", 126, "≥3:1"),
    ("05", 129, "near-black (not #000)"),
    ("05", 130, "≥7:1 body text"),
    ("05", 131, "200% browser"),
    ("05", 147, "default 1 update / 2s per field"),
    ("05", 148, "rule triggered"),
    ("05", 148, "never throttled/coalesced"),
    ("05", 150, "pre-rendered empty containers"),
    ("05", 200, "WAI-ARIA APG patterns"),
    ("05", 207, "any auto-moving content lasting >5s"),
    ("05", 208, "more than 3 times per second"),
    ("05", 209, "design-system token/mode"),
    ("14", 1923, "UI must remain fully interactive during a run"),
    ("14", 1947, "the environment choice is a radio group with DEMO preselected"),
    ("14", 1957, "drag list or numeric priority"),
    ("14", 1972, "condition values shown in a nested table"),
    ("15", 104, '`role="radiogroup"`, roving tabindex, arrow-key navigation'),
    ("15", 267, "never a live region"),
    ("15", 469, "while the card appears at once"),
    ("15", 498, 'A non-modal drawer is a `role="dialog"` without `aria-modal`'),
    ("15", 499, "a docked drawer that reflows its host arrives in one frame"),
    ("15", 530, 'with `grid`, `role="grid"`'),
    ("15", 694, "drag-and-drop is additive, never the only path"),
    ("15", 2744, 'a `role="log"` list ordered errors-first'),
    ("16", 125, "Density changes spacing-token resolution only"),
    ("16", 127, "in practice 40-44px"),
    ("16", 138, "`data-text-scale`"),
    ("16", 175, "no motion lasting more than 5 seconds without a pause control"),
    ("D02", 138, "**The one T2 rule"),
    ("D02", 142, '`role="region"` named "Simulation — {rule name}"'),
    ("D02", 150, "a polite announcement at most every 2 s"),
    ("D02", 175, '**`role="alertdialog"`**'),
    ("D02", 177, "**The reading order"),
    ("D02", 181, "**Until D02-G5 lands: a read-only line**"),
    ("D02", 187, "ignores activation for 400 ms"),
    ("D02", 189, "the trade-off (a long description) is stated for E35-D04 to confirm"),
    ("D02", 219, "Reason for overriding (required)"),
    ("D02", 222, "Not armed — {why}. Nothing was sent."),
    ("D02", 273, "`Shift+Tab` from Cancel lands on the last body stop, never on Arm"),
    ("D02", 275, "named here so E35-D04 reviews one model"),
    ("D02", 277, "**`forced-colors: active`:**"),
    ("D02", 286, "the error summary's first line"),
    ("D02", 291, "polite, throttled ≤ 1 per 2 s"),
    ("D02", 411, "`normal` scale + fade"),
    ("D02", 412, "`normal` slide from the right"),
    ("D02", 413, "`fast` width transition"),
    ("D02", 441, "| 4.54  |"),
    ("D02", 454, "| 6.15  |"),
    ("D03", 93, "nothing in SCR-086 arms"),
    ("D03", 142, "`color.surface.sunken`"),
    ("D03", 143, "the radios sit under each row, not in cells"),
    ("D03", 196, "focus stays where it was"),
    ("D03", 200, "`color.surface.sunken`"),
    ("D03", 283, "`color.surface.sunken`"),
    ("D03", 294, "Imported 2 rules — none is armed; all on demo."),
    ("D03", 297, '`role="log"` named "Import problems — {n}"'),
    ("D03", 302, "Not exported — this file still contains 1 account id."),
    ("D03", 356, "because the expanded row holds controls"),
    ("D03", 358, "Main (…4f2a), account, masked"),
    ("D03", 360, "never per keystroke"),
    ("D03", 362, "**a failed LIVE firing arriving live is assertive once**"),
    ("D03", 362, "Imported 2 rules — all disarmed, on demo."),
    ("D03", 438, "`normal` scale + fade"),
    ("D03", 439, "`fast` height transition"),
    ("D03", 445, "`slow` shimmer"),
    ("D03", 450, "`color.text.tertiary` on `color.surface.selected` is 3.98 in dark"),
    ("D03", 490, "| 5.59  |"),
    ("D03", 498, "`color.surface.sunken` 0 / 217 / 0"),
    ("D03H", 86, "Move {rule} up"),
    ("D03H", 103, "assertive, then polite"),
    ("D02H", 125, "outputs not committed"),
    ("MEMO", 459, "E35-D04 confirms with `05`'s owner"),
    ("MEMO", 462, "E35-D04 settles it with `05`'s owner"),
    ("E09-D06", 67, "grace/challenge time polite at 60 s and 10 s only"),
    ("E10-D04", 83, "**R-1 Compositor only.**"),
    ("E10-D04", 84, "**R-2 One layout per transition**"),
    ("E10-D04", 89, "**R-7 Nothing loops or flashes.**"),
    ("E30-D02", 141, "inserts under the header and takes focus"),
    ("E36-D03", 334, "Compiled rule IR, read-only"),
    ("E36-D03", 342, "a rule fire assertively once, by the notification path, never repeated"),
    ("E36-D04", 529, "`rules.move_up` / `move_down`"),
    ("E36-D04", 539, "F-12"),
    ("E40R", 27, "One **announcer** owns every alert-system announcement"),
    ("E40R", 190, '`aria-live="off"` while closed'),
    ("E40A", 322, "OQ-13"),
    ("E11-D07", 590, "F-04"),
    ("E13-D05", 86, "a review changes no component contract"),
    ("KM", 608, '"rules.move_up"'),
    ("KM", 617, '"rules.move_down"'),
    ("KM", 654, '"rules.select_all"'),
    ("KM", 693, '"rules.cycle_nodes"'),
    ("KM", 702, '"rules.inspect_node"'),
    ("E35.json", 106, '"E35-D04"'),
    ("E35.json", 351, "## Context"),
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
# words (the #241 lens lesson); the pins stay the backstop for the forms no lexicon lists, and every
# paraphrase an adversary lens found past the lexicons is now an X probe. A gap that may not hold
# a negation is written `(?:(?!NEG)\S+ )`, so "speaks no firing" or "never arms" never reads as
# the claim.
NOGAP = r"(?:(?!(?:no|never|not|nor|nothing|none|without|cannot)\b)\S+ )"
SPEAK = (
    r"(?:announc\w*|spoken|speaks?|spoke|voiced|voices?|read aloud|read out|reads? out|says?"
    r"|said|narrated|politely|assertively|conveyed)"
)
NEVER_ITEM = (
    r"(?:per evaluation|per firing|each firing|every firing|per keystroke|each keystroke"
    r"|the countdown|every second|each second|every evaluation|each evaluation)"
)
NEVER_TERM = (
    rf"\b{SPEAK} {NOGAP}{{0,6}}?{NEVER_ITEM}\b"
    rf"|\b{NEVER_ITEM} {NOGAP}{{0,4}}?(?:is|are|gets?|get) (?:\S+ )?(?:announced|spoken|read)\b"
)
FIRE_TERM = (
    r"\b(?:the page|the grid|the list|the log|scr 087|the fire history|the row|each row)"
    rf" {NOGAP}{{0,3}}?(?:speaks?|announc\w*|voices?|reads? out|says?|repeats?|also speaks?)"
    rf" {NOGAP}{{0,3}}?(?:the |a |each |every |its )?(?:failed )?(?:live )?"
    r"(?:fire|fires|firing|firings|rule fires?)\b(?! count)"
    r"|\b(?:fire|fires|firing|firings) (?:\S+ ){0,3}?(?:voiced|announced|spoken|read out|repeated)"
    r" (?:\S+ ){0,2}?by (?:the )?(?:page|grid|list|log|row|scr 087)(?:'s)?\b"
)
ARMS_TERM = (
    r"\b(?:apply|the resolver|scr 086|imports?|imported rules?|the import|arm anyway)"
    rf" {NOGAP}{{0,3}}?(?:arms?|arms the rule|lands? armed|lands? on live|starts? armed)\b"
    r"(?! \(?nothing| nothing| no )"
)
ESC_TERM = (
    rf"\b(?:esc|escape|enter on a radio) {NOGAP}{{0,3}}?"
    r"(?:arms?|writes?|commits?|confirms?|applies|saves?|submits?)\b(?! \(?nothing)"
    rf"|\bshift\+tab {NOGAP}{{0,4}}?(?:lands?|land|goes|go|moves|reaches|reach) (?:on |to )?arm\b"
)
# what `Esc` may do in a K-08 / `3.3.3` / §5.1 `Esc` cell (RULED BQ-9): close, cancel, return
ESC_ACT = (
    r"\b(?:arms (?!nothing)|arm the rule|arms the rule|confirms? (?:the |an? )?(?:pending )?arm"
    r"|commits?|applies|saves?|submits?"
    r"|writes (?!nothing)|write (?!nothing)|records)\b"
)
CUT_TERM = (
    r"\b(?:truncat\w*|shorten\w*|abridg\w*|abbreviat\w*|condens\w*|compress\w*|elid\w*"
    r"|trimm\w*|clips?|clipped|cuts?|collaps\w*"
    r"|summari[sz]\w*) (?:\S+ ){0,2}?(?:restatement|description)\b"
    r"|\b(?:restatement|description) (?:is |are |gets? |may be |can be |will be )?"
    r"(?:truncated|shortened|abridged|trimmed|clipped|cut|collapsed|summari[sz]ed)\b"
    r"|\b(?:read more|show more|read the full description)\b"
)
MOVE_TERM = (
    r"\b(?:rows?|firings?|new firings?|entries) (?:\S+ ){0,2}?(?:auto ?insert\w*"
    r"|insert\w* (?:automatically|live|as they arrive|on arrival|at once)|auto ?scroll\w*)\b"
    rf"|\bfocus {NOGAP}{{0,2}}?(?:moves|jumps|goes|is moved|follows) (?:to )?(?:the )?"
    r"(?:new|newest|pill|top|latest|first row)\b"
    r"|\bauto ?scroll\w*\b|\bscroll(?:s)? to the (?:top|new|latest)\b"
    r"|\b(?:viewport|view|scroll position|the grid) (?:\S+ ){0,2}?(?:follows|tracks|jumps to"
    r"|moves to|scrolls to|sticks to|keeps up with) (?:the )?(?:newest|latest|new|top)\b"
)
PROGRESS_TERM = (
    r"\bprogress (?:\S+ ){0,4}?(?:every|each|once per|at most once per|at most every) 2 s\b"
    rf"|\bprogress {NOGAP}{{0,3}}?(?:per|on each|on every) (?:evaluation|event|tick)\b"
)
MOTION_OK_TERM = (
    r"\b(?:scale and fade|scale \+ fade|slides?|slide in|width transition|height transition"
    r"|shimmer|looping skeleton)\b (?:\S+ ){0,4}?(?:is|are|stays?|remains?|holds?) (?:\S+ )?"
    r"(?:compliant|fine|allowed|acceptable|kept)\b"
)
EXTEND_TERM = (
    r"\b(?:an? |the )?(?:extend|extension|more time|add time|extra time)\b (?:\S+ ){0,3}?"
    r"(?:control|button|option|link|is offered|is added|offered)\b"
)
LIMIT_TERM = (
    r"\b(?:activation guard|guard|count pause|pause before|the pause)\b (?:\S+ ){0,4}?"
    r"(?:is|are) (?:a |the )?time limits?\b"
)
SCOPE_TERM = (
    r"\b(?:may|can|does|will|is allowed to|should)"
    r" (?:\S+ ){0,2}?(?:name|count|reveal|expose)s? (?:\S+ ){0,2}?the hidden rule\b"
)
KEY_PROPOSE_TERM = (
    r"\b(?:this review |we |the review )?(?:proposes?|adds?|introduces?|registers?)"
    r" (?:a |an |the )?(?:new )?(?:global )?(?:key|chord|shortcut|binding|hotkey)s?\b"
)
AT_NAMES = r"\b(?:nvda|jaws|voiceover|voice over|narrator|talkback|orca)\b"
AT_RUN_TERM = (
    r"\b(?:tested|verified|checked|confirmed|heard|listened|ran|run|was run|were run|walked"
    r"|observed|recorded|captured)"
    r" (?:\S+ ){0,2}?(?:with|on|using|under|in) (?:a |the |two |both )?screen ?readers?\b"
    r"|\bscreen ?readers? (?:read|reads|said|says|announc\w*|spoke|speaks|voiced|confirmed"
    r"|verified|checked|showed|reported|agreed|rendered)\b"
    r"|\bscreen ?reader output (?:was |is |were )?(?:observed|recorded|captured|heard|checked"
    r"|logged)\b"
)
HCBAR_TERM = (
    r"\b(?:every|all|each|any) (?:\S+ ){0,2}?(?:pairs?|texts?|links?|labels?)"
    r" (?:\S+ ){0,3}?(?:pass\w*|meets?|clears?|holds?) (?:\S+ ){0,5}?high contrast\b"
    r"|\bhigh contrast (?:text )?(?:bar|threshold|minimum) (?:is|of|at) 4\.5\b"
    r"|\bhigh contrast (?:\S+ ){0,2}?(?:measured|held|read|kept) (?:against|at|to) 4\.5\b"
    r"|\bhigh contrast,? (?:\S+ ){0,6}?same (?:text )?(?:bar|threshold|minimum) as\b"
    r"|\bsame (?:text )?(?:bar|threshold|minimum) (?:in|for|across) (?:every theme|all three"
    r" themes|the three themes|high contrast)\b"
)
NODRAW_TERM = (
    r"\b(?:redrawn|redraws?|redrawing|drawn anew|drawn again|drawn in penpot"
    r"|new penpot (?:page|board)s?|new boards?|new frames?|verdict boards?|sketch(?:es|ed)?"
    r"|mock ?ups?|wireframes?"
    r"|(?:fresh|additional|extra|added|new) (?:penpot )?(?:boards?|frames?|drawings?|sheets?))\b"
)
NODRAW_IF = r"\b(?:should|unless|if) the owner\b"
HANDOFF_TERM = (
    r"\bhand ?off (?:file|document|pack file|markdown)s?\b|\be35 d04 handoff\.md\b"
    r"|\bhand ?off carries\b|\bcompanion hand ?off\b"
)
CLOSE_RULE_TERM = (
    r"\b(?:fixed|corrected|repaired|amended|edited|patched|updated|changed) in (?:the )?"
    r"(?:designs?|design file|merged (?:spec|text|design)\w*|penpot file|figma file)\b"
    r"|\b(?:design file|merged (?:spec|text|design)\w*|penpot file) (?:is |are )?"
    r"(?:fixed|corrected|repaired|amended|edited|patched|updated|changed)\b"
    r"|\b(?:reviewer|author|writer|agent|lane|qa) marks? (?:it|the finding|a finding)"
    r" (?:as )?(?:done|closed|resolved|fixed)\b"
    r"|\b(?:reviewer|author|writer|agent|lane|qa) (?:ticks?|checks? off|signs? off|closes?"
    r"|resolves?) (?:it|the finding|a finding|the row)\b"
)
SIGNOFF_TERM = (
    r"\b(?:a11y lead|accessibility lead|cdo|design lead)(?:'s|s)?(?: delegate)?\b (?:\S+ ){0,3}?"
    r"(?:signed|approved|sign(?:ed)? off|countersigned|endorsed|accepted|cleared|ratified"
    r"|okayed|blessed|nodded|gave (?:the |their |its |a )?(?:nod|go ahead|green light"
    r"|thumbs up))\b"
    r"|\bsigned off by (?:the )?(?:a11y lead|accessibility lead|cdo)\b"
    r"|\bowner's approved (?:is |was |has been )?(?:taken|assumed|granted|given|obtained|in hand"
    r"|received|recorded as given)\b"
    r"|\bthe owner (?:has )?(?:approved|signed off|endorsed)\b"
)
PENDING_TERM = (
    r"\b(?:bq 17|routing table|assertive set|live region (?:routing )?table|live region routing)\b"
    r" (?:\S+ ){0,4}?(?:is |was )?(?:ruled|confirmed|approved|settled|final|adopted|binding"
    r"|in force|authoritative|decided|agreed|locked|governs|controls|applies to every)\b"
)
EDIT_TERM = (
    r"\b(?:edits?|rewrites?|patch(?:es)?|modif(?:y|ies)|changes?) (?:the |a |any )?merged"
    r" (?:text|spec|design|file)s?\b"
)
EXCEPTION_TERM = (
    r"\bessential exception (?:\S+ ){0,3}?(?:covers|applies to (?:the )?(?:targets?|links?|rows?)"
    r"|is used for|exempts (?:the )?(?:targets?|links?))\b"
)
MOST_TERM = (
    r"\b(?:most|some|many|nearly all|almost all|the majority of)"
    r" (?:\S+ ){0,1}?(?:colou?r carrying )?signals\b"
)
# RULED BQ-17 in prose: an assertive class never read as polite, a polite one never as assertive
ASSERTIVE_EVENTS = (
    r"\b(?:arm refus\w*|refused arm|refused live arm|returned from step up|step up drops?"
    r"|simulation failed|failed simulation|resolver's refusal|withholds? a file"
    r"|export check)\b"
)
POLITE_EVENTS = (
    r"\b(?:the filter result|the pill|order set|pre check count|simulation complete"
    r"|environment change|copied)\b"
)
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


def framed_false(block: str, w: str) -> bool:
    """`w` sits only in sentences whose falsity frame ("it is untrue that ...") precedes it."""
    hits = [norm_text(s) for s in sentences(block) if w in norm_text(s)]
    return bool(hits) and all(
        (f := FLIP.search(s)) is not None and f.start() < s.find(w) for s in hits
    )


def need(t: Texts, tag: str, head: str, words: tuple[str, ...]) -> list[Finding]:
    """The ruled sentence's own words, each present in the section `head` (normalised) and not
    wrapped in a falsity frame."""
    block = spec_sec(t, head)
    n = norm_text(block)
    return [
        F(tag, f"§{head.split()[0]} lost {w!r}", "spec", at(t, head))
        for w in words
        if w not in n or framed_false(block, w)
    ]


def g_route_prose(t: Texts) -> list[Finding]:
    """BQ-17 in prose (cells read too): an assertive class read as polite, or the converse."""
    bad: list[Finding] = []
    for u in lex(t):
        for c in clauses(u.text):
            n = norm_text(unquote(c))
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


def g_never(t: Texts) -> list[Finding]:
    bad = lexicon("G-NEVER", "a never-announced item announced", NEVER_TERM)(t)
    return bad + need(t, "G-NEVER", ROUTE_HEAD, ("text is swapped, never the node",))


def g_fire(t: Texts) -> list[Finding]:
    """RULED BQ-16: SCR-087 speaks no individual firing; E40's announcer speaks it once."""
    bad = lexicon("G-FIRE", "the page speaks a fire", FIRE_TERM)(t)
    return bad + need(
        t,
        "G-FIRE",
        FIRE_HEAD,
        (
            "scr 087 speaks no individual firing",
            "by e40's one announcer in cmp 212",
            "the page never repeats it",
            "f 01, major, double voice",
            "the coalescing question is oq 13's",
        ),
    )


def g_arm(t: Texts) -> list[Finding]:
    """RULED BQ-11 (as proposed): nothing but SCR-085's footer arms."""
    bad = lexicon("G-ARM", "something else arms", ARMS_TERM)(t)
    return bad + need(
        t,
        "G-ARM",
        ARM_HEAD,
        (
            "nothing else arms",
            "records a resolution and returns to scr 085",
            "imports land not armed",
            "the demo leg proposed there (memo sc 21)",
        ),
    )


def g_esc(t: Texts) -> list[Finding]:
    """RULED BQ-9 (as proposed): `Esc` never arms and writes nothing; `Enter` on a radio never."""
    bad = lexicon("G-ESC", "Esc or Enter arms", ESC_TERM)(t)
    cells_: list[tuple[str, str]] = []
    k08 = rows_by(spec_sec(t, KEY_HEAD)).get("K-08", [])
    cells_ += [(at(t, KEY_HEAD), k08[2])] if len(k08) > 2 else []
    c333 = rows_by(spec_sec(t, CLAUSE_HEAD)).get("`3.3.3`", [])
    cells_ += [(at(t, CLAUSE_HEAD), c333[2])] if len(c333) > 2 else []
    cells_ += [(at(t, FOCUS_HEAD), r[5]) for r in table(spec_sec(t, FOCUS_HEAD)) if len(r) == 8]
    for sec, cell in cells_:
        for c in sentences(cell):
            if live(c, ESC_ACT):
                bad.append(F("G-ESC", f"an Esc cell acts: {norm_text(c)[:70]!r}", "spec", sec))
    return bad + need(
        t,
        "G-ESC",
        FOCUS_HEAD,
        ("never lands on arm", "closes and arms nothing", "writes nothing"),
    )


def g_desc(t: Texts) -> list[Finding]:
    """RULED BQ-11 (as proposed): the description is the restatement, whole."""
    bad = lexicon("G-DESC", "the description cut", CUT_TERM)(t)
    return bad + need(
        t,
        "G-DESC",
        ARM_HEAD,
        (
            "described by the restatement",
            "the description stays whole",
            "no truncation",
            "a long description, read whole",
        ),
    )


def g_pill(t: Texts) -> list[Finding]:
    """RULED BQ-15 (as proposed): nothing moves until the pill is pressed."""
    bad = lexicon("G-PILL", "rows or focus move by themselves", MOVE_TERM)(t)
    return bad + need(
        t,
        "G-PILL",
        LOG_HEAD,
        (
            "rows insert on a press only",
            "focus stays where it was",
            "the scroll position is preserved",
            f"at most once per {base_value('TIME:lane')} s, never per firing",
            "(proposed; g 01)",
        ),
    )


def g_progress(t: Texts) -> list[Finding]:
    """RULED BQ-18 (confirmed): progress at the lane's rate; completion one sentence."""
    bad = lexicon("G-PROGRESS", "progress at the field rate", PROGRESS_TERM)(t)
    return bad + need(
        t,
        "G-PROGRESS",
        PROGRESS_HEAD,
        (
            f"at most once per {base_value('TIME:lane')} s, the latest value, politely",
            "is f 11",
            "is c 09",
            "completion is one polite sentence",
        ),
    )


def g_motion(t: Texts) -> list[Finding]:
    """RULED BQ-27 (confirmed): the five motion rows are Minor F rows to E35-D05."""
    bad = lexicon("G-MOTION", "a ruled motion row read as compliant", MOTION_OK_TERM)(t)
    return bad + need(
        t,
        "G-MOTION",
        MOTION_HEAD,
        (
            "the card appears at once while the scrim fades",
            "arrives in one frame",
            "transform: scalex",
            "a static two tone skeleton in both modes (proposed)",
            "the reading is 15's (c 12)",
            "data motion on the root",
            "applied here as proposed",
        ),
    )


def g_time(t: Texts) -> list[Finding]:
    """RULED BQ-28 (confirmed): the Essential exception; the two short delays are not limits."""
    bad = lexicon("G-TIME", "an extend control offered", EXTEND_TERM)(t)
    bad += lexicon("G-TIME", "a short delay read as a time limit", LIMIT_TERM)(t)
    return bad + need(
        t,
        "G-TIME",
        TIME_HEAD,
        (
            "essential exception (level a)",
            "extending a request bound step up would defeat it",
            "are not time limits",
            "c 14 records",
        ),
    )


def g_scope(t: Texts) -> list[Finding]:
    """RULED BQ-29 (as proposed): nothing in the tree names or counts the hidden rule."""
    bad = lexicon("G-SCOPE", "the hidden rule named", SCOPE_TERM)(t)
    return bad + need(
        t,
        "G-SCOPE",
        RBAC_HEAD,
        (
            "no accessible name, description or hidden text names or counts the hidden rule",
            "echoed on hover and on focus",
            "never hover only",
            "one notice",
        ),
    )


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
    bad += need(
        t,
        "G-HCBAR",
        CONTRAST_HEAD,
        (f"{base_value('BAR:hc')}:1 for text in high contrast", "the token owner (e05)"),
    )
    return bad


def g_at(t: Texts) -> list[Finding]:
    bad = [
        F("G-AT", f"an assistive technology named: {h[0]!r}", h[1], h[2])
        for h in claims(lex(t), AT_NAMES)
    ]
    bad += lexicon("G-AT", "a screen-reader run claimed", AT_RUN_TERM)(t)
    return bad


def g_nodraw(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for u in lex(t):
        for c in clauses(u.text):
            if re.search(NODRAW_IF, norm_text(c)):
                continue
            if live(c, NODRAW_TERM):
                bad.append(F("G-NODRAW", f"a new drawing: {norm_text(c)[:70]!r}", u.doc, u.sec))
    return bad


def other_d04_files() -> list[str]:
    """Any file in the spec's folder named for this ticket other than the spec itself."""
    folder = ROOT / Path(SPEC_REL).parent
    spec_name = Path(SPEC_REL).name
    return sorted(
        p.name
        for p in folder.glob("*")
        if p.is_file() and re.search(r"(?i)e35.?d04", p.name) and p.name != spec_name
    )


def g_nohandoff(t: Texts) -> list[Finding]:
    bad = lexicon("G-NOHANDOFF", "a hand-off file", HANDOFF_TERM)(t)
    if "no handoff.md" not in norm_text(spec_sec(t, HANDOFF_HEAD)):
        bad.append(F("G-NOHANDOFF", "§17.2 lost 'No `-handoff.md`'", "spec", at(t, HANDOFF_HEAD)))
    if t.hand is not None:
        bad.append(F("G-NOHANDOFF", "a hand-off was passed against RULED BQ-33", "hand", None))
    elif t.hand_exists:
        bad.append(F("G-NOHANDOFF", f"{t.extra_files} exist against RULED BQ-33", None, None))
    return bad


def g_close_rule(t: Texts) -> list[Finding]:
    bad = lexicon("G-CLOSE-RULE", "closing by an edit of the designs", CLOSE_RULE_TERM)(t)
    r2 = next((ln for ln in t.spec.split("\n") if ln.startswith("- **R-2")), "")
    n = norm_text(r2)
    for w in (
        "routed",
        "accepted with a written rationale",
        "owner's approved",
        "c 18",
        "never an agent",
    ):
        if w not in n:
            bad.append(F("G-CLOSE-RULE", f"R-2 lacks {w!r}", "spec", "1. Purpose, method,"))
    return bad


def g_signoff(t: Texts) -> list[Finding]:
    bad = lexicon("G-SIGNOFF", "a sign-off claimed", SIGNOFF_TERM)(t)
    n = norm_text(spec_sec(t, DOD_HEAD))
    for w in (
        "standing arrangement's design approval",
        "qa record",
        "pending the owner's approved on #2701",
        "walkthrough",
        "#939",
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
    bad = lexicon("G-PENDING", "BQ-17 read as ruled", PENDING_TERM)(t)
    head = next((ln for ln in t.spec.split("\n") if ln.startswith("### 8.1 ")), "")
    if PENDING not in head:
        bad.append(F("G-PENDING", "§8.1's heading lacks the PROPOSED marker", "spec", at(t, "8.1")))
    ruled = section(t.spec, "The thirty-five questions")
    bq17 = next((s for s in ruled.split(". ") if "**BQ-17**" in s and "routing" in s), "")
    if PENDING not in bq17.replace("**", ""):
        sec = h2_of(t.spec, "The thirty-five questions")
        bad.append(F("G-PENDING", "the RULED line lacks BQ-17's marker", "spec", sec))
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


def g_keypropose(t: Texts) -> list[Finding]:
    """RULED BQ-30 (as proposed): no new key."""
    bad = lexicon("G-KEYS", "a new key proposed", KEY_PROPOSE_TERM)(t)
    return bad + need(t, "G-KEYS", KEY_HEAD, ("no new key is proposed on the six screens",))


LEXICON_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_charset,
    g_cells,
    g_close,
    g_at,
    g_route_prose,
    g_never,
    g_fire,
    g_arm,
    g_esc,
    g_desc,
    g_pill,
    g_progress,
    g_motion,
    g_time,
    g_scope,
    g_hcbar,
    g_nodraw,
    g_nohandoff,
    g_close_rule,
    g_signoff,
    g_pending,
    g_unmerged,
    g_keypropose,
)

# ---------------------------------------------------------------------------- table gates

ID_CELL = re.compile(r"\b(?:F|C|G|Q|A|H|K|N|CR|RT|T|SR|AL)-\d\d\b")


def base_value(key: str) -> str:
    return dict(base_values())[key]


def defined_ids(t: Texts) -> set[str]:
    out: set[str] = set()
    for ln in t.spec.split("\n"):
        m = re.match(r"^\| ((?:F|C|A|K|N|CR|RT|T|SR|AL)-\d\d) \|", ln)
        if m:
            out.add(m[1])
        m2 = re.match(r"^- \*\*((?:G|Q|H)-\d\d)", ln)
        if m2:
            out.add(m2[1])
    return out


def f_ids(cell: str) -> list[str]:
    """F ids named in a cell, ranges expanded ("F-13..F-16")."""
    out: list[str] = []
    for a, b in re.findall(r"\bF-(\d\d)(?:\.\.F-(\d\d))?\b", cell):
        lo, hi = int(a), int(b or a)
        out += [f"F-{n:02d}" for n in range(lo, hi + 1)]
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
            bad.append(F("G-CLAUSE", f"{cid} is not a clause of BQ-5", "spec", sec))
        if not VERDICT.match(verdict):
            bad.append(F("G-CLAUSE", f"{cid} verdict {verdict!r}", "spec", sec))
        if not CITE_GROUP.search(req + " " + where) and not verdict.startswith("out of scope"):
            bad.append(F("G-CLAUSE", f"{cid} carries no file:line evidence", "spec", sec))
        sevs = [sev.get(f, "") for f in f_ids(fnd)]
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
    r3 = next((ln for ln in t.spec.split("\n") if ln.startswith("- **R-3")), "")
    if "`out of scope — <epic>`" not in r3:
        bad.append(
            F("G-CLAUSE", "R-3 lost the <epic> verdict word (BQ-6)", "spec", "1. Purpose, method,")
        )
    bad += need(
        t,
        "G-CLAUSE",
        CLAUSE_HEAD,
        (
            "one row per clause across the six screens (deviation d4)",
            "the tool row is the §15 gate",
        ),
    )
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
    return bad


# RULED BQ-9 (as proposed): the focus contract, one row per surface
FOCUS_ROWS = (
    "SCR-084",
    "SCR-085",
    "SCR-086",
    "SCR-087",
    "SCR-088",
    "SCR-089",
    "the disarm confirm",
)
FOCUS_RULED: dict[str, tuple[int, str]] = {
    "SCR-085": (2, "Cancel"),
    "SCR-086": (2, "the first conflict's first radio"),
    "SCR-089": (2, "the first section tab"),
    "SCR-087": (2, "the filter bar (board D03 06; C-26)"),  # the lens fold: board D03 06
    "SCR-088": (2, "the close button (E36-D04:596; C-26)"),  # E36-D04's reviewed base
    "the disarm confirm": (2, "Cancel (`15`:478)"),  # `15`:478 binds it, not a proposal
}


def g_focus(t: Texts) -> list[Finding]:
    sec = at(t, FOCUS_HEAD)
    rows = {r[0]: r for r in table(spec_sec(t, FOCUS_HEAD)) if r}
    bad: list[Finding] = []
    for s in FOCUS_ROWS:
        r = rows.get(s)
        if r is None or len(r) != 8:
            bad.append(F("G-FOCUS", f"no eight-cell focus row for {s}", "spec", sec))
            continue
        modal, trap, back, src = r[1], r[3], r[6], r[7]
        if modal.startswith("yes") != (trap == "yes"):
            bad.append(F("G-FOCUS", f"{s} modal {modal!r} with trap {trap!r}", "spec", sec))
        if modal.startswith("yes") and back in ("", "—"):
            bad.append(F("G-FOCUS", f"{s} names no focus return", "spec", sec))
        if not CITE_GROUP.search(src):
            bad.append(F("G-FOCUS", f"{s} carries no source cite", "spec", sec))
        rule = FOCUS_RULED.get(s)
        if rule and r[rule[0]] != rule[1]:
            bad.append(F("G-FOCUS", f"{s} initial focus must be {rule[1]!r}", "spec", sec))
    return bad


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
        if c not in clause_rows or fid not in f_ids(clause_rows[c][4]):
            bad.append(F("G-FROW", f"{fid} is not listed on clause {c}'s row", "spec", sec))
        if not CITE_GROUP.search(ev):
            bad.append(F("G-FROW", f"{fid} evidence carries no file:line", "spec", sec))
        if not re.search(r"#\d+|E05 tokens", target):
            bad.append(F("G-FROW", f"{fid} target names no issue", "spec", sec))
    r1 = norm_text(next((ln for ln in t.spec.split("\n") if ln.startswith("- **R-1")), ""))
    for w in (
        "non compliant with no compliant path",
        "a status carried by colour alone",
        "an announcement with no string or politeness",
        "a t2 over or under conversion, a contrast pair below its bar",
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
        if not any(
            f"`{p.fg}` on `{p.bg}`" in " ".join(r) and "E05" in " ".join(r) and r[1] == "Major"
            for r in rows
        ):
            msg = f"no Major F row routes {p.fg} on {p.bg} (high contrast) to E05"
            bad.append(F("G-HCFROW", msg, "spec", at(t, FINDING_HEAD)))
    return bad


# the F rows the ruling (and the lens fold) fix: id -> (severity, clause, words the evidence must
# carry, target issue, words the replacement must carry)
FROWS_RULED: dict[str, tuple[str, str, tuple[str, ...], str, tuple[str, ...]]] = {
    "F-01": ("Major", "6.2b", ("D03:362",), "#940", ()),  # BQ-16 the double voice
    "F-02": ("Major", "3.4.2", ("D02:275", "`SCR-084/completed`"), "#940", ()),  # BQ-14
    "F-06": ("Minor", "5.5", ("E10-D04:392", "E05-D01:57"), "#940", ("`color.surface.app`",)),
    "F-07": ("Minor", "6.5", ("D02:142",), "#940", ()),  # BQ-9 the drawer's role
    "F-08": (  # BQ-10 the error summary; the lens fold: one voice (C-23)
        "Minor",
        "6.5",
        ("E30-D02:141", "anything about focus", "heard twice"),
        "#940",
        ('no `role="alert"`',),
    ),
    "F-09": ("Minor", "6.2a", ("D03:294", "board D03 06"), "#940", ()),  # BQ-17 the import line
    "F-10": ("Minor", "6.2d", ("D03:297",), "#940", ()),  # BQ-17 CMP-234's log
    "F-11": ("Minor", "6.2a", ("D02:150", "the F form is RULED BQ-18's"), "#940", ()),  # BQ-18
    "F-12": ("Minor", "3.4.6", ("D02:175", "`SCR-085/review-demo`"), "#940", ()),  # BQ-24
    "F-13": ("Minor", "7.4", ("D02:411",), "#940", ()),  # BQ-27 the dialogs
    "F-14": ("Minor", "7.4", ("D02:412",), "#940", ()),  # BQ-27 the drawer
    "F-15": ("Minor", "7.4", ("D02:413",), "#940", ("PROPOSED",)),  # BQ-27 the width
    "F-16": ("Minor", "7.4", ("D03:439",), "#940", ("PROPOSED",)),  # BQ-27 the height
    "F-17": ("Minor", "7.2", ("D03:445",), "#940", ("PROPOSED",)),  # BQ-27 the shimmer
}


def g_frows_ruled(t: Texts) -> list[Finding]:
    rows = rows_by(spec_sec(t, FINDING_HEAD))
    sec = at(t, FINDING_HEAD)
    bad: list[Finding] = []
    for fid, (sev, cl, cites, target, repl) in FROWS_RULED.items():
        r = rows.get(fid)
        if r is None or len(r) != 8:
            bad.append(F("G-FROWS-RULED", f"{fid} is missing", "spec", sec))
            continue
        if (
            r[1] != sev
            or r[2].strip("`") != cl
            or any(c not in r[4] for c in cites)
            or target not in r[7]
            or any(w not in r[5] for w in repl)
        ):
            msg = f"{fid} must read {sev} · {cl} · evidence {cites} · {repl} · target {target}"
            bad.append(F("G-FROWS-RULED", msg, "spec", sec))
    return bad


def g_route(t: Texts) -> list[Finding]:
    sec = at(t, ROUTE_HEAD)
    rows = table(spec_sec(t, ROUTE_HEAD))
    bad: list[Finding] = []
    for pat, region, new in ROUTES:
        hit = [
            r[:7] for r in rows if len(r) >= 7 and re.search(pat, norm_text(r[2].replace('"', "")))
        ]
        if len(hit) != 1:
            bad.append(F("G-ROUTE", f"event {pat!r} has {len(hit)} rows", "spec", sec))
            continue
        r = hit[0]
        if norm_text(r[3]) != region:
            bad.append(F("G-ROUTE", f"{r[0]} region {r[3]!r}; ruled {region}", "spec", sec))
        if new and r[6] != PENDING:
            msg = f"{r[0]} is new to `05`: status must be {PENDING}"
            bad.append(F("G-ROUTE", msg, "spec", sec))
        if not new and r[6] != "in `05`":
            bad.append(F("G-ROUTE", f"{r[0]} is `05`:148's: status must be 'in `05`'", "spec", sec))
        if region == "none" and not norm_text(r[4]).startswith("never"):
            bad.append(F("G-ROUTE", f"{r[0]} cadence must be never", "spec", sec))
        if region == "assertive" and norm_text(r[4]) != "once":
            bad.append(F("G-ROUTE", f"{r[0]} is assertive once, never coalesced", "spec", sec))
    lane = base_value("TIME:lane")
    for rid in ("RT-12", "RT-16"):
        r = next((x for x in rows if x and x[0] == rid), [])
        if len(r) >= 7 and f"at most once per {lane} s" not in norm_text(r[4]):
            bad.append(F("G-ROUTE", f"{rid} cadence must be the lane's {lane} s", "spec", sec))
    bad += need(
        t,
        "G-ROUTE",
        ROUTE_HEAD,
        (
            "two regions per surface, one polite and one assertive, pre rendered empty",
            "every announced string d02 §7 and d03 §10 bind has its row here",
        ),
    )
    return bad


def g_alt(t: Texts) -> list[Finding]:
    q = next((ln for ln in t.spec.split("\n") if ln.startswith("- **Q-01**")), "")
    if "`05`:148's list only" not in q or "PROPOSED" not in q or "#2701" not in q:
        return [F("G-ALT", "Q-01 lost BQ-17's alternative", "spec", at(t, Q_HEAD))]
    return []


# RULED BQ-30: every key the six screens bind, typed with its source line (the lens fold's adds)
KEYS_RULED: tuple[tuple[str, str], ...] = (
    ("Ctrl+Home", "D03:356"),
    ("Ctrl+End", "D03:356"),
    ("*", "D03:358"),
    ("Shift+Tab", "D03:360"),
    ("Home", "D03:356"),
    ("PageUp", "D03:356"),
)


def unscoped_rules(km: object) -> list[str]:
    """The shipped `Rules` context's bindings that carry no `screens` list."""
    out: list[str] = []

    def walk(o: object) -> None:
        if isinstance(o, dict):
            if o.get("context") == "Rules" and "defaultBinding" in o and not o.get("screens"):
                out.append(str(o["defaultBinding"]))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(km)
    return out


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
    rows = table(spec_sec(t, KEY_HEAD))
    typed = {c: r for r in rows if len(r) >= 7 for c in chords(r[1])}
    for chord, cite in KEYS_RULED:
        r = typed.get(chord)
        if r is None or cite.split(":")[0] not in r[4] or ":" + cite.split(":")[1] not in r[4]:
            bad.append(F("G-KEYS", f"{chord} is not typed with {cite} (RULED BQ-30)", "spec", sec))
    for chord in unscoped_rules(km):
        r = typed.get(chord)
        if r is None or "`KM`" not in r[4]:
            msg = f"the unscoped `Rules` binding {chord} has no K row (RULED BQ-30)"
            bad.append(F("G-KEYS", msg, "spec", sec))
    bad += need(
        t,
        "G-KEYS",
        KEY_HEAD,
        ("every key the six screens bind is typed with its source line",),
    )
    for r in rows:
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


# roles the merged hand-offs and `15` bind (the lens fold): N id -> role
NAMES_ROLE: dict[str, str] = {
    "N-13": "option",  # D02H:83 pairs an account row with option
    "N-54": "alertdialog",  # `15`:478, a destructive confirm
    "N-65": "radiogroup",  # E36-D04:203, the "Inspector view" segments
}
# RULED BQ-31 / BQ-5 (i): every interactive element drawn has a row ((screen, element) pairs the
# adversary lens found missing, plus the first table's)
NAMES_REQUIRED: tuple[tuple[str, str], ...] = (
    ("SCR-084", "Run again"),
    ("SCR-085", "Done"),
    ("SCR-085", "show all"),
    ("SCR-085", "an account's include box"),
    ("SCR-085", "the estimated chip"),
    ("SCR-085", "How it is estimated"),
    ("SCR-085", "CMP-158"),
    ("SCR-085", "Arm again on DEMO&hellip;"),
    ("SCR-085", "Arm again on LIVE&hellip;"),
    ("SCR-085", "the disarm confirm"),
    ("SCR-085", "the confirm's Cancel"),
    ("SCR-085", "the confirm's Disarm"),
    ("SCR-086", "Set priority"),
    ("SCR-086", "Narrow scope"),
    ("SCR-086", "Disarm one"),
    ("SCR-086", "Arm anyway"),
    ("SCR-086", "Cancel"),
    ("SCR-087", "Newer"),
    ("SCR-087", "Older"),
    ("SCR-087", "Open rule"),
    ("SCR-087", "a Copy button in the expanded row"),
    ("SCR-088", "the segments"),
)


def _label_norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w{}&;.-]+", " ", s.lower()).split())


def g_names(t: Texts) -> list[Finding]:
    sec = at(t, NAME_HEAD)
    bad: list[Finding] = []
    rows = table(spec_sec(t, NAME_HEAD))
    have = {(r[1], r[2]) for r in rows if len(r) > 2}
    for s, el in NAMES_REQUIRED:
        if (s, el) not in have:
            bad.append(F("G-NAMES", f"no names row for {s} {el!r}", "spec", sec))
    roles = {r[0]: r[3] for r in rows if len(r) > 3}
    for nid, role in NAMES_ROLE.items():
        if roles.get(nid) != role:
            bad.append(F("G-NAMES", f"{nid} role must be {role!r}", "spec", sec))
    bad += need(
        t,
        "G-NAMES",
        NAME_HEAD,
        ("one row for every interactive element the six screens draw (ruled bq 31)",),
    )
    for r in rows:
        if len(r) != 8:
            bad.append(F("G-NAMES", f"{r[0]} has {len(r)} cells", "spec", sec))
            continue
        label = _label_norm(html.unescape(r[4].strip('"')))
        name = _label_norm(html.unescape(r[5].strip('"')))
        if label and label not in name:
            bad.append(F("G-NAMES", f"{r[0]} name {name!r} lacks its label {label!r}", "spec", sec))
        if label and not name.startswith(label):
            bad.append(F("G-NAMES", f"{r[0]} name does not start with its label", "spec", sec))
        if not name:
            bad.append(F("G-NAMES", f"{r[0]} has no accessible name", "spec", sec))
        if not (CITE_GROUP.search(r[7]) or "PROPOSED" in r[7]):
            bad.append(F("G-NAMES", f"{r[0]} source neither cited nor PROPOSED", "spec", sec))
    return bad


COLOUR_ONLY = re.compile(
    r"^(?:the )?(?:fill|colou?r|hue|tint|highlight|shade|accent)s?\.?$", re.IGNORECASE
)


def g_carrier(t: Texts) -> list[Finding]:
    sec = at(t, CARRIER_HEAD)
    bad: list[Finding] = []
    for r in table(spec_sec(t, CARRIER_HEAD)):
        if len(r) != 8:
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
def motion_lines() -> frozenset[tuple[str, int]]:
    """The base lines of D02 §9's and D03 §12's motion tables (the reduce substitutes' home)."""
    out: set[tuple[str, int]] = set()
    for cid, head in (("D02", "9. Motion"), ("D03", "12. Motion")):
        text = at_base(CITE_FILES[cid])
        block = section(text, head)
        start = text.split("\n").index(block.split("\n")[0])
        for k, ln in enumerate(block.split("\n")):
            if ln.startswith("| ") and not is_rule(ln) and not ln.startswith("| Property"):
                out.add((cid, start + k + 1))
    return frozenset(out)


SURFACES = {"SCR-084", "SCR-085", "SCR-086", "SCR-087", "SCR-088", "SCR-089"}
MOTION_WORDS = re.compile(
    r"\b(?:slides?|sliding|fades?|fading|animat\w*|eas(?:e|ing)|tween\w*|transition\w*"
    r"|scales?|shimmer\w*)\b",
    re.IGNORECASE,
)
REDUCE_OK = re.compile(r"\b(?:instant|identical|static)\b", re.IGNORECASE)
LAYOUT_OK = re.compile(
    r"in place|at once|in one frame|compositor-only|fixed row height", re.IGNORECASE
)
LAYOUT_BAD = re.compile(
    r"\b(?:animat\w* (?:the )?(?:width|height|size)|grows? the row|(?:width|height) (?:grows|"
    r"changes|animates|transition)|slides? in|reflows? (?:the )?(?:host|editor) over|loops?)\b",
    re.IGNORECASE,
)
PAIR_CELL = re.compile(r"^`(color\.[^`]+)` on `(color\.[^`]+)` \((text|non-text)\)$")
# the reduce lines whose default motion is an F row (RULED BQ-27): line -> the F row it names
MOTION_F = {
    ("D02", 411): "F-13",
    ("D03", 438): "F-13",
    ("D02", 412): "F-14",
    ("D02", 413): "F-15",
    ("D03", 439): "F-16",
    ("D03", 445): "F-17",
}


def g_trans(t: Texts) -> list[Finding]:
    sec = at(t, TRANS_HEAD)
    bad: list[Finding] = []
    rows = table(spec_sec(t, TRANS_HEAD))
    if not rows:
        bad.append(F("G-TRANS", "the transition register is empty", "spec", sec))
    seen: set[tuple[str, int]] = set()
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
        cites = [
            (str(g["b"]), int(n))
            for g in CITE_GROUP.finditer(reduce_)
            for n in [g["first"], *re.findall(r":(\d+)", g["more"])]
        ]
        if not cites or not all(c in motion_lines() for c in cites):
            bad.append(F("G-TRANS", f"{tid} reduce substitute cites no motion row", "spec", sec))
        if not REDUCE_OK.search(reduce_) or MOTION_WORDS.search(reduce_):
            bad.append(F("G-TRANS", f"{tid} reduce substitute moves: {reduce_!r}", "spec", sec))
        if not carrier.strip() or COLOUR_ONLY.match(carrier.strip()) or carrier == "—":
            bad.append(F("G-TRANS", f"{tid} carrier {carrier!r} is colour alone", "spec", sec))
        if not LAYOUT_OK.search(layout) or LAYOUT_BAD.search(layout):
            bad.append(F("G-TRANS", f"{tid} layout rule {layout!r}", "spec", sec))
        for c in cites:
            seen.add(c)
            fid = MOTION_F.get(c)
            if fid and fid not in layout:
                bad.append(F("G-TRANS", f"{tid} layout rule must name {fid}", "spec", sec))
    for c, fid in MOTION_F.items():
        if c not in seen:
            bad.append(F("G-TRANS", f"no transition row for {c[0]}:{c[1]} ({fid})", "spec", sec))
    return bad


def g_crows(t: Texts) -> list[Finding]:
    rows = [" ".join(r) for r in table(spec_sec(t, C_HEAD))]
    need_ = (
        ("the two modals", r"two modals.*all four reviewed"),
        ("the drawer's role", r'role="region"`.*`15`\'s'),
        ("the error summary", r"error summary.*D16's"),
        ("the typed field", r"typed-confirmation dialog.*SCR-006's field"),
        ("the radio group", r"`14`:1947.*A-02"),
        ("the drag list", r"`14`:1957.*A-03"),
        ("the page-level fire line", r"D03:362.*E40's routing under OQ-13"),
        ("the coalescing", r"MEMO:462.*OQ-13's"),
        ("the progress rate", r"`05`:147.*the lane's, for progress"),
        ("the high-contrast bar", r"BAR:hc-->:1 \(§10"),
        ("the motion lines", r"D02:411.*`15`'s"),
        ("the time limit", r"`05`:11.*the Essential exception"),
        ("the text scale", r"125 ?%.*both readings"),
        ("the assertive set", r"`05`:148's list.*PROPOSED; Q-01"),
        ("fixed in the designs", r"fixed in the designs.*fixed in the pack E35-D05 lifts"),
        ("the sign-off", r"accessibility lead and the CDO delegate.*pending the owner's"),
        ("no hand-off file", r"README:81–82.*no `-handoff\.md`"),
        ("the alert summary", r"E30-D02:141.*RULED BQ-17.*no alert role"),
        ("the black step", r"`05`:129.*E05-D01:57.*E10-D04 F-12"),
        ("the selected-row token", r"`15`:531.*D03:184.*G-14"),
        ("the initial focus", r"board D03 06.*E36-D04:596.*the reviewed base"),
    )
    bad: list[Finding] = []
    for what, pat in need_:
        if not any(re.search(pat, r) for r in rows):
            bad.append(F("G-CROWS", f"no C row records {what}", "spec", at(t, C_HEAD)))
    return bad


def g_grows(t: Texts) -> list[Finding]:
    lines = {
        m[1]: ln
        for ln in spec_sec(t, G_HEAD).split("\n")
        if (m := re.match(r"^- \*\*(G-\d\d)\*\*", ln))
    }
    need_ = (
        ("G-01", ("D03:362", "at most once per", "E35-D05 (#940)")),
        ("G-02", ("D03:143", "fieldsets after the table")),
        ("G-03", ("mounted",)),
        ("G-08", ("cvd_sim.py", "two kinds only")),
        ("G-09", ("D02H:125",)),
        (
            "G-12",
            (
                "E36-D04 F-02",
                "the keymap owner (E49)",
                "SCR-084..SCR-089",
                "This review's addition, after D03-C22",
                "`rules.pan`",
                "E36-D03:381",
            ),
        ),
        ("G-14", ("D03:134, :184", "PROPOSED `color.text.secondary`", "C-25")),
        ("G-15", ("H-02", "Owner: E05")),
    )
    bad: list[Finding] = []
    for gid, words in need_:
        ln = lines.get(gid, "")
        miss = [w for w in words if w not in ln]
        if miss:
            bad.append(F("G-GROWS", f"{gid} lacks {miss}", "spec", at(t, G_HEAD)))
    return bad


# the sections E35-D05 lifts (RULED BQ-33: every section holding a replacement or a bound rule)
LIFTED = (
    "§5.1–§5.6",
    "§6.1–§6.5",
    "§7.1",
    "§8.1–§8.4",
    "§9.1",
    "§10",
    "§11.1–§11.4",
    "§12",
    "§13's replacements",
    "§16.4",
)


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
    if "E35-Q06 takes §14" not in block:
        bad.append(F("G-CONSUMERS", "§17.2 lost E35-Q06's §14", "spec", at(t, HANDOFF_HEAD)))
    return bad


def g_unbuilt(t: Texts) -> list[Finding]:
    block = spec_sec(t, "0. Status")
    first = next(
        (p for p in block.split("\n") if p.startswith("**The rule screens are unbuilt.**")), ""
    )
    bad: list[Finding] = []
    feats = sorted(Path(n).name for n in ls_tree(BASE, FEATURES_REL) if "." not in Path(n).name)
    named = sorted(re.findall(r"`([A-Za-z0-9-]+)`", first.split("no rules slice")[0]))
    if "no rules slice" not in first or "holds no CMP-156 and no CMP-159" not in first:
        bad.append(F("G-UNBUILT", "§0 lost the unbuilt statement", "spec", at(t, "0. Status")))
    elif named != feats:
        bad.append(F("G-UNBUILT", f"§0 lists {named}; the base holds {feats}", "spec", at(t, "0.")))
    ui = git_out("grep", "-l", "-e", "CMP-156", "-e", "CMP-159", BASE, "--", UI_SRC_REL)
    if ui.strip():
        bad.append(
            F("G-UNBUILT", "packages/ui/src holds CMP-156 or CMP-159 at the base", None, None)
        )
    miss = [s for s in STORIES if s not in first]
    if miss:
        bad.append(F("G-UNBUILT", f"§0 does not name {miss}", "spec", at(t, "0. Status")))
    if "the `stepUp` slice" not in first:
        bad.append(F("G-UNBUILT", "§0 lost the built neighbour", "spec", at(t, "0. Status")))
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
    agree, total = d03_agreement()
    if agree != total:
        bad.append(F("G-UNION", f"D03 §13 agrees in {agree} of {total} cells", None, None))
    return bad


CVD_HEAD = "9.2 Colour-vision"


def g_cvd(t: Texts) -> list[Finding]:
    """RULED BQ-23 (as proposed): the port is gated against its sources; §9.2 lists every pair of
    colour tokens one §9.1 row binds plus CVD_CROSS, under the three simulations and greyscale."""
    bad = [F("G-CVD", msg, None, None) for msg in cvd_port_problems()]
    sec = at(t, CVD_HEAD)

    def key(a: str, b: str) -> frozenset[str]:
        return frozenset((a, b))

    want = {key(a, b) for a, b in CVD_PAIRS.values()}
    derived = {key(*CVD_PAIRS[k]) for k in CVD_CROSS}
    for r in table(spec_sec(t, CARRIER_HEAD)):
        toks = [
            x
            for x in re.findall(r"`(color\.[^`]+)`", r[2] if len(r) > 2 else "")
            if x.startswith(("color.status.", "color.env."))
        ]
        derived |= {key(a, b) for i, a in enumerate(toks) for b in toks[i + 1 :] if a != b}
    listed = set()
    for r in table(spec_sec(t, CVD_HEAD)):
        toks = re.findall(r"`(color\.[^`]+)`", r[0]) if r else []
        if len(toks) == 2:
            listed.add(key(toks[0], toks[1]))
    if derived != want:
        msg = f"CVD_PAIRS differ from §9.1's carrier pairs: {len(derived ^ want)} apart"
        bad.append(F("G-CVD", msg, "spec", at(t, CARRIER_HEAD)))
    if listed != want:
        bad.append(F("G-CVD", f"§9.2 lists {len(listed)} of {len(want)} pairs", "spec", sec))
    light = {hex_of("light", _S + x) for x in ("warning.strong", "danger.strong")}
    if len(light) != 1:
        bad.append(F("G-CVD", "H-02's light identity no longer holds", "spec", sec))
    bad += need(
        t,
        "G-CVD",
        CVD_HEAD,
        ("tritanopia and greyscale", "an identity, not a simulation's collapse", "(g 15)"),
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
    summary = next((ln for ln in t.spec.split("\n") if ln.startswith("9. Sign-off per RULED")), "")
    shown = {nn: (f"`{nn}`" if re.fullmatch(r"\d\d|KM|RK", nn) else nn) for nn in UNTOUCHED}
    gone = [s for s in shown.values() if not re.search(rf"{re.escape(s)}(?![\w-])", summary)]
    if gone:
        msg = f"§18's untouched list lacks {gone}"
        bad.append(F("G-UNTOUCHED", msg, "spec", h2_of(t.spec, "18. Summary")))
    bad += lexicon("G-UNTOUCHED", "a merged text edited", EDIT_TERM)(t)
    bad += need(t, "G-UNTOUCHED", "1.1 What this", ("it edits no merged text",))
    return bad


def g_target(t: Texts) -> list[Finding]:
    """RULED BQ-25 (as proposed): no essential exception; widths never assumed."""
    bad = lexicon("G-TARGET", "the essential exception used", EXCEPTION_TERM)(t)
    return bad + need(
        t,
        "G-TARGET",
        TARGET_HEAD,
        ("no essential exception is used", "are g 10, never assumed"),
    )


def g_grid(t: Texts) -> list[Finding]:
    """RULED BQ-14 (as proposed): SCR-084's timeline becomes `grid: true`."""
    return need(
        t,
        "G-GRID",
        TABLES_HEAD,
        (
            "the replacement is grid: true",
            "the focused row stays mounted",
            "not yet decidable routed to e35 q06",
        ),
    )


def g_t2(t: Texts) -> list[Finding]:
    """RULED BQ-11 (as proposed): T2 read against D02 §1 / D03 §1; a wrong conversion is Major."""
    r4 = norm_text(next((ln for ln in t.spec.split("\n") if ln.startswith("- **R-4")), ""))
    if "an over or under conversion is major" not in r4 or "d02:138" not in r4:
        return [F("G-T2", "R-4 lost the T2 reading", "spec", "1. Purpose, method,")]
    return need(t, "G-T2", ARM_HEAD, ("the view as leg first with one notice per frame",))


# RULED BQ-32: Q06's five scenarios map one to one (SR id -> scenario)
Q06_SCENARIOS = {"SR-03": "2", "SR-07": "3", "SR-08": "4", "SR-10": "5", "SR-12": "1"}
# RULED BQ-32 (as proposed): one Feature per screen, `05` §10's template lines kept
SCRIPT_SURFACES = (
    "SCR-084 simulation drawer",
    "SCR-085 arming dialog",
    "SCR-086 conflict resolver",
    "SCR-087 fire history",
    "SCR-088 IR inspector",
    "SCR-089 import and export",
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
    sec = at(t, SCRIPT_HEAD)
    block = section(t.spec, SCRIPT_HEAD)
    steps = fence_steps(block)
    bad: list[Finding] = []
    feats = [x for x in steps if x.startswith("Feature: ")]
    for name in SCRIPT_SURFACES:
        if sum(bool(re.match(rf"Feature: {re.escape(name)} ", x)) for x in feats) != 1:
            bad.append(F("G-SCRIPT", f"§14.3 has no Feature for {name!r}", "spec", sec))
    if not template_steps():
        bad.append(F("G-SCRIPT", "`05` §10's template steps not found at the base", None, None))
    for st in template_steps():
        if st not in steps:
            bad.append(F("G-SCRIPT", f"§14.3 drops the template step {st[:60]!r}", "spec", sec))
    srs = {r[0] for r in table(spec_sec(t, SR_HEAD)) if r}
    named = set(re.findall(r"\bSR-\d\d\b", block))
    if srs - named:
        bad.append(F("G-SCRIPT", f"§14.3 names no Feature for {sorted(srs - named)}", "spec", sec))
    for r in table(spec_sec(t, AL_HEAD)):
        if len(r) != 5 or "E35-Q06" not in r[3] or not r[4].strip():
            bad.append(F("G-SCRIPT", f"{r[0]} names no E35-Q06 verifier or source", "spec", sec))
    for r in table(spec_sec(t, SR_HEAD)):
        got = re.findall(r"Q06 scenario (\d)", r[-1]) if r else []
        want = Q06_SCENARIOS.get(r[0]) if r else None
        if got != ([want] if want else []):
            msg = f"{r[0]} maps Q06 scenario {got}; BQ-32 maps {want}"
            bad.append(F("G-SCRIPT", msg, "spec", at(t, SR_HEAD)))
    states = rows_by(spec_sec(t, AL_HEAD)).get("AL-16", []) + rows_by(spec_sec(t, SR_HEAD)).get(
        "SR-12", []
    )
    if sum("D02:245" in c and "D03:310" in c for c in states) != 2:
        msg = "SR-12 / AL-16 lost the producibility tables they cover (D02:245; D03:310)"
        bad.append(F("G-SCRIPT", msg, "spec", sec))
    head = next((ln for ln in t.spec.split("\n") if ln.startswith("### 14.3 ")), "")
    if "the template's six scenarios shared once" not in head or "deviation D5" not in head:
        bad.append(F("G-SCRIPT", "§14.3's heading lost the compression note", "spec", sec))
    return bad


def g_budget(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    n = t.spec.count("\n")
    if n > SPEC_LINE_BUDGET:
        bad.append(F("G-BUDGET", f"spec {n} lines > {SPEC_LINE_BUDGET}", "spec", h2_at(t.spec, n)))
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


def g_summary(t: Texts) -> list[Finding]:
    """BQ-10 (as proposed) with BQ-17's polite validity press: the focus move reads it once."""
    bad = need(
        t,
        "G-SUMMARY",
        FORMS_HEAD,
        (
            'the summary carries no role="alert"',
            "the focus move reads it once",
            "a validity press is never assertive",
        ),
    )
    rt9 = rows_by(spec_sec(t, ROUTE_HEAD)).get("RT-09", [])
    if len(rt9) < 3 or 'no `role="alert"`' not in rt9[2]:
        bad.append(F("G-SUMMARY", "RT-09 lost the summary's one voice", "spec", at(t, ROUTE_HEAD)))
    return bad


TQUOTE = re.compile(r"`T [A-Za-z0-9]+`(?: / `T [A-Za-z0-9]+`)?'s \"([^\"]+)\"")


@functools.lru_cache(maxsize=1)
def ticket_body() -> str:
    data = json.loads(at_base(CITE_FILES["E35.json"]))
    items = data if isinstance(data, list) else []
    body = next((str(x.get("body", "")) for x in items if x.get("key") == "E35-D04"), "")
    if not body:
        raise SystemExit("FAIL parse: E35-D04's body is not in E35.json at the base")
    return body


def g_tquote(t: Texts) -> list[Finding]:
    """A quote of the ticket (`T Scope`'s "...") is verbatim in its body (the lens fold)."""
    body = norm_text(ticket_body())
    bad: list[Finding] = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for q in TQUOTE.findall(strip_comments(ln)):
            if norm_text(html.unescape(q)) not in body:
                msg = f"line {i}: {q[:60]!r} is not verbatim in the ticket"
                bad.append(F("G-TQUOTE", msg, "spec", h2_at(t.spec, i)))
    return bad


# RULED BQ-2: the locks §1.3 must cite
LOCKS = ("D02:65–84", "D03:73–94", "E36-D03:133–153", "E36-D03:179", "E09-D06:60", "E40R:27")


def g_locked(t: Texts) -> list[Finding]:
    block = section(t.spec, "1.3 Locked inputs")
    return [
        F("G-LOCKED", f"§1.3 lost the lock {c}", "spec", at(t, "1.3 Locked"))
        for c in LOCKS
        if c not in block
    ]


MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_summary,
    g_tquote,
    g_locked,
    g_clause,
    g_sc,
    g_focus,
    g_frow,
    g_fowner,
    g_hcfrow,
    g_frows_ruled,
    g_route,
    g_alt,
    g_keys,
    g_names,
    g_carrier,
    g_trans,
    g_crows,
    g_grows,
    g_consumers,
    g_unbuilt,
    g_arow,
    g_union,
    g_cvd,
    g_untouched,
    g_target,
    g_grid,
    g_t2,
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
        "# E35-D04 pins (every unit of the review): doc, region (heading path #occurrence), "
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
        if ln.startswith("**The rule screens are unbuilt.**"):
            lines[i] = ln + " "
            break
    return "\n".join(lines)


def cite_out_of_range(text: str) -> str:
    return text.replace("(D02:142, :175; D03:140, :184)", "(D02:9999, :175; D03:140, :184)", 1)


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str  # the gate tag that must trip ("" for a probe that must trip nothing)
    spec: Edit | None = None
    plan: tuple[str, Edit] | None = None  # (untouched id, edit) on the working-tree copy
    hand: Edit | None = None  # a hand-off text passed beside the spec


LIGHTHOUSE = "    And the affected screen's Lighthouse Accessibility score remains >= 95\n"
LANE_ANCHOR = "5<!--=TIME:lane-->"


def _drop_feature(name: str) -> Callable[[list[str]], list[str]]:
    def run(lines: list[str]) -> list[str]:
        i = next((k for k, ln in enumerate(lines) if ln.startswith(f"Feature: {name}")), -1)
        return lines if i < 0 else lines[:i] + lines[i + 5 :]

    return run


def rep(old: str, new: str) -> Edit:
    """The first `old` anywhere in the spec, replaced (the adversary lens's attacks)."""
    return lambda s: s.replace(old, new, 1)


def first_in(head: str, old: str, new: str) -> Edit:
    """The first `old` inside the section `head`, replaced."""
    return sub_in(head, old, new)


def _swap_first_rows(lines: list[str]) -> list[str]:
    idx = [i for i, ln in enumerate(lines) if ln.startswith("|") and not is_rule(ln)][1:3]
    if len(idx) == 2:
        lines[idx[0]], lines[idx[1]] = lines[idx[1]], lines[idx[0]]
    return lines


RT = ROUTE_HEAD
FH = FINDING_HEAD
MUTATIONS: tuple[Mutation, ...] = (
    Mutation("M-01", "G-ROUTE", row_edit(RT, "RT-01", 3, to("polite"))),
    Mutation("M-02", "G-ROUTE", row_edit(RT, "RT-02", 3, to("polite"))),
    Mutation("M-03", "G-ROUTE", row_edit(RT, "RT-03", 3, to("polite"))),
    Mutation("M-04", "G-ROUTE", row_edit(RT, "RT-04", 3, to("polite"))),
    Mutation("M-05", "G-ROUTE", row_edit(RT, "RT-05", 3, to("polite"))),
    Mutation("M-06", "G-ROUTE", row_edit(RT, "RT-12", 3, to("assertive"))),
    Mutation("M-07", "G-ROUTE", row_edit(RT, "RT-17", 3, to("polite"))),
    Mutation("M-08", "G-ROUTE", row_edit(RT, "RT-18", 3, to("polite"))),
    Mutation("M-09", "G-ROUTE", row_edit(RT, "RT-01", 6, to("in `05`"))),
    Mutation("M-10", "G-ROUTE", drop_row(RT, "RT-19")),
    Mutation("M-11", "G-ROUTE", row_edit(RT, "RT-03", 4, to("once, then coalesced"))),
    Mutation("M-12", "G-ROUTE", row_edit(RT, "RT-16", 4, to("at most once per second"))),
    Mutation(
        "M-13", "G-ROUTE", say_in(PROGRESS_HEAD, "A failed simulation is announced politely.")
    ),
    Mutation("M-14", "G-NEVER", say_in(TIME_HEAD, "The countdown is spoken every second.")),
    Mutation(
        "M-15",
        "G-NEVER",
        sub_in(RT, "the text is swapped, never the node", "the text and the node are swapped"),
    ),
    Mutation("M-16", "G-PENDING", line_sub("### 8.1 ", ", owner approval pending (#2701)", "")),
    Mutation(
        "M-17",
        "G-PENDING",
        sub_in(
            "The thirty-five questions",
            "is **PROPOSED, owner approval pending (#2701)**",
            "is **ruled**",
        ),
    ),
    Mutation("M-18", "G-ALT", line_sub("- **Q-01**", "`05`:148's list only", "the composed table")),
    Mutation("M-19", "G-FIRE", say_in(FIRE_HEAD, "The page also speaks each failed firing.")),
    Mutation(
        "M-20",
        "G-FIRE",
        sub_in(
            FIRE_HEAD, "SCR-087 speaks no individual firing", "SCR-087 speaks the failed firings"
        ),
    ),
    Mutation(
        "M-21", "G-FIRE", sub_in(FIRE_HEAD, "and the page never repeats it", "and the page echoes")
    ),
    Mutation("M-22", "G-FROWS-RULED", row_edit(FH, "F-01", 7, to("E35-S09 (#1049)"))),
    Mutation("M-23", "G-FROWS-RULED", row_sub(FH, "F-13", "D02:411 and ", "")),
    Mutation("M-24", "G-FROWS-RULED", row_edit(FH, "F-11", 4, to("the cadence (E36-D03:342)"))),
    Mutation("M-25", "G-HCBAR", say_in(CONTRAST_HEAD, "Every link pair passes in high contrast.")),
    Mutation(
        "M-26", "G-HCBAR", drop_row(CONTRAST_HEAD, "`color.text.link` on `color.surface.overlay`")
    ),
    Mutation("M-27", "G-HCFROW", row_sub(FH, "F-04", "`color.text.link`", "`color.text.primary`")),
    Mutation("M-28", "G-MOTION", say_in(MOTION_HEAD, "The drawer's slide is compliant.")),
    Mutation(
        "M-29",
        "G-MOTION",
        sub_in(MOTION_HEAD, "a static two-tone skeleton in both modes", "a softer shimmer"),
    ),
    Mutation(
        "M-30",
        "G-MOTION",
        sub_in(MOTION_HEAD, "the card appears at once while the scrim fades", "the card fades"),
    ),
    Mutation("M-31", "G-TRANS", row_edit(TRANS_HEAD, "T-01", 4, to("D02:411: a short fade"))),
    Mutation(
        "M-32", "G-TRANS", row_edit(TRANS_HEAD, "T-04", 6, to("the fill's width animates (F-15)"))
    ),
    Mutation("M-33", "G-TRANS", row_edit(TRANS_HEAD, "T-09", 5, to("fill"))),
    Mutation("M-34", "G-TRANS", row_sub(TRANS_HEAD, "T-14", "; F-17)", ")")),
    Mutation("M-35", "G-TRANS", drop_row(TRANS_HEAD, "T-03")),
    Mutation(
        "M-36", "G-TIME", say_in(TIME_HEAD, "An extend button is offered before the grant ends.")
    ),
    Mutation("M-37", "G-TIME", sub_in(TIME_HEAD, "are not time limits", "are time limits")),
    Mutation(
        "M-38", "G-DESC", say_in(ARM_HEAD, "A long restatement is truncated after two lines.")
    ),
    Mutation("M-39", "G-DESC", sub_in(ARM_HEAD, "no truncation and no", "a short summary and a")),
    Mutation("M-40", "G-ARM", say_in(ARM_HEAD, "Apply arms the rule when Arm anyway is chosen.")),
    Mutation(
        "M-41", "G-ARM", sub_in(ARM_HEAD, "imports land not armed", "imports land armed on demo")
    ),
    Mutation("M-42", "G-ESC", say_in(FOCUS_HEAD, "`Esc` arms the rule on DEMO.")),
    Mutation(
        "M-43",
        "G-ESC",
        sub_in(FOCUS_HEAD, "before the arm closes and arms nothing", "before the arm closes"),
    ),
    Mutation("M-44", "G-PILL", say_in(LOG_HEAD, "New firings insert automatically at the top.")),
    Mutation(
        "M-45",
        "G-PILL",
        sub_in(LOG_HEAD, "focus stays where it was", "focus moves to the new row"),
    ),
    Mutation(
        "M-46",
        "G-PROGRESS",
        sub_in(PROGRESS_HEAD, "the latest value, politely", "each value, politely"),
    ),
    Mutation(
        "M-47",
        "G-PROGRESS",
        sub_in(
            PROGRESS_HEAD,
            "Completion is one polite sentence",
            "Completion is a progress tick",
        ),
    ),
    Mutation(
        "M-48", "G-SCOPE", say_in(RBAC_HEAD, "A hidden description may name the hidden rule.")
    ),
    Mutation(
        "M-49", "G-SCOPE", sub_in(RBAC_HEAD, "echoed on hover and on focus", "echoed on hover")
    ),
    Mutation("M-50", "G-CLAUSE", row_edit(CLAUSE_HEAD, "`6.2b`", 3, to("compliant"))),
    Mutation("M-51", "G-CLAUSE", drop_row(CLAUSE_HEAD, "`3.3.5`")),
    Mutation("M-52", "G-CLAUSE", row_edit(CLAUSE_HEAD, "`5.5`", 3, to("compliant"))),
    Mutation("M-53", "G-CLAUSE", row_sub(CLAUSE_HEAD, "`7.4`", "; interim path: every", "; every")),
    Mutation("M-54", "G-SC", drop_row(SC_HEAD, "2.4.11")),
    Mutation("M-55", "G-FOCUS", row_edit(FOCUS_HEAD, "SCR-086", 2, to("Cancel"))),
    Mutation("M-56", "G-FOCUS", row_edit(FOCUS_HEAD, "SCR-089", 3, to("no"))),
    Mutation("M-57", "G-FROW", row_edit(FH, "F-18", 1, to("Grave"))),
    Mutation("M-58", "G-FOWNER", row_edit(FH, "F-18", 6, to("an agent"))),
    Mutation(
        "M-59",
        "G-CLOSE-RULE",
        say_in(FH, "A finding closes when it is fixed in the designs."),
    ),
    Mutation("M-60", "G-CLOSE-RULE", line_sub("- **R-2", ", never an agent, plus", ", plus")),
    Mutation("M-61", "G-SIGNOFF", say_in(DOD_HEAD, "The CDO delegate signed off.")),
    Mutation(
        "M-62",
        "G-SIGNOFF",
        line_sub(
            "**Ticket:**",
            "nothing here claims the owner's `approved`",
            "the owner's `approved` is taken as given",
        ),
    ),
    Mutation("M-63", "G-NOHANDOFF", say_in(HANDOFF_HEAD, "The hand-off file carries the A rows.")),
    Mutation("M-64", "G-NOHANDOFF", hand=lambda _h: "# E35-D04 hand-off\n\nA rows.\n"),
    Mutation(
        "M-65",
        "G-CONSUMERS",
        sub_in(HANDOFF_HEAD, "and #958 (E40, the routing note under OQ-13)", "and E40"),
    ),
    Mutation("M-66", "G-CONSUMERS", sub_in(HANDOFF_HEAD, "§5.1–§5.6, ", "")),
    Mutation("M-67", "G-AT", say_in(NAME_HEAD, "NVDA reads the dialog's name.")),
    Mutation("M-68", "G-KEYS", row_edit(KEY_HEAD, "K-08", 6, to("—"))),
    Mutation("M-69", "G-KEYS", say_in(KEY_HEAD, "This review proposes a new key for Apply.")),
    Mutation("M-70", "G-NAMES", row_edit(NAME_HEAD, "N-26", 5, to('"Move BE after 1R up"'))),
    Mutation(
        "M-71",
        "G-CARRIER",
        lambda s: row_edit(CARRIER_HEAD, "CR-08", 4, to("—"))(
            row_edit(CARRIER_HEAD, "CR-08", 3, to("—"))(s)
        ),
    ),
    Mutation(
        "M-72",
        "G-CARRIER",
        line_sub(
            "- **R-5", "Every colour-carrying signal has", "Most colour-carrying signals have"
        ),
    ),
    Mutation("M-73", "G-CROWS", drop_row(C_HEAD, "C-07")),
    Mutation("M-74", "G-CROWS", row_sub(C_HEAD, "C-12", "`15`'s (§11.1", "D02's (§11.1")),
    Mutation("M-75", "G-GROWS", line_sub("- **G-12**", "E36-D04 F-02", "E36-D04 F-99")),
    Mutation(
        "M-76",
        "G-UNBUILT",
        line_sub("**The rule screens are unbuilt.**", " and no rules slice", ""),
    ),
    Mutation("M-77", "G-UNTOUCHED", plan=("05", lambda s: s + "An appended line.\n")),
    Mutation("M-78", "G-UNTOUCHED", plan=("D03", lambda s: s.replace("never", "seldom", 1))),
    Mutation(
        "M-79",
        "G-UNTOUCHED",
        sub_in("1.1 What this", "It edits no merged text:", "It edits merged text where obvious:"),
    ),
    Mutation("M-80", "G-UNMERGED", say_in("0. Status", "E35-D05:12 lists the pack.")),
    Mutation("M-81", "G-NODRAW", say_in("0. Status", "Board 06 is redrawn in Penpot.")),
    Mutation("M-82", "G-CITE", cite_out_of_range),
    Mutation("M-83", "G-CLOSE", say_in(DOD_HEAD, "Closes #939.")),
    Mutation("M-84", "G-BUDGET", overrun),
    Mutation("M-85", "G-CHARSET", trailing_space),
    Mutation(
        "M-86",
        "G-CELLS",
        lambda s: s.replace(
            "|\n\n**Inside the table, two fixes", "| **Inside the table, two fixes", 1
        ),
    ),
    Mutation("M-87", "G-AROW", row_sub(A_HEAD, "A-01", "a simulation failed, ", "")),
    Mutation("M-88", "G-AROW", row_edit(A_HEAD, "A-02", 3, to("the environment is a dropdown"))),
    Mutation("M-89", "G-SCRIPT", in_lines(SCRIPT_HEAD, _drop_feature("SCR-089 import and export"))),
    Mutation("M-90", "G-SCRIPT", sub_in(SCRIPT_HEAD, LIGHTHOUSE, "")),
    Mutation("M-91", "G-SCRIPT", row_edit(AL_HEAD, "AL-05", 3, to("the owner"))),
    Mutation(
        "M-92", "G-TARGET", say_in(TARGET_HEAD, "The essential exception covers the row links.")
    ),
    Mutation(
        "M-93",
        "G-GRID",
        sub_in(TABLES_HEAD, "the replacement is `grid: true`", "the replacement is a static table"),
    ),
    Mutation(
        "M-94", "G-T2", line_sub("- **R-4", ", and an over- or under-conversion is Major", "")
    ),
    Mutation("M-95", "G-FROW", line_sub("- **R-1", "a status carried by colour alone, ", "")),
    Mutation(
        "M-96",
        "G-ANCHOR",
        sub_in(TARGET_HEAD, "24<!--=GEOM:target.min--> ×", "20<!--=GEOM:target.min--> ×"),
    ),
    # the lens fold (lenses 1-3 on the first write): one mutation per folded ruled sentence
    Mutation("M-97", "G-FROWS-RULED", row_sub(FH, "F-17", "(PROPOSED; T-14)", "(T-14)")),
    Mutation("M-98", "G-MOTION", sub_in(MOTION_HEAD, "in both modes (PROPOSED)", "in both modes")),
    Mutation(
        "M-99", "G-GROWS", line_sub("- **G-12**", "This review's addition, after D03-C22: s", "S")
    ),
    Mutation("M-100", "G-SCRIPT", row_edit(SR_HEAD, "SR-01", 5, to("Q06 scenario 2"))),
    Mutation(
        "M-101",
        "G-SUMMARY",
        sub_in(FORMS_HEAD, 'carries no `role="alert"`', 'carries `role="alert"`'),
    ),
    Mutation(
        "M-102",
        "G-FROWS-RULED",
        row_sub(FH, "F-08", "neither says anything about focus", "both leave focus on the button"),
    ),
    Mutation("M-103", "G-NAMES", row_edit(NAME_HEAD, "N-13", 3, to("row"))),
    Mutation(
        "M-104",
        "G-TQUOTE",
        row_sub(
            C_HEAD,
            "C-04",
            "the typed-confirmation dialog, the environment badge, the virtualised table — reuse"
            " its specification",
            "reuse the typed-confirmation dialog",
        ),
    ),
    Mutation("M-105", "G-TQUOTE", row_sub(C_HEAD, "C-13", '"125%"', '"125 %"')),
    Mutation(
        "M-106",
        "G-SCRIPT",
        line_sub("### 14.3 ", ", the template's six scenarios shared once", ""),
    ),
    Mutation("M-107", "G-KEYS", drop_row(KEY_HEAD, "K-11")),
    Mutation("M-108", "G-KEYS", drop_row(KEY_HEAD, "K-14")),
    Mutation("M-109", "G-FROWS-RULED", row_edit(FH, "F-06", 1, to("Major"))),
    Mutation("M-110", "G-CLAUSE", row_sub(CLAUSE_HEAD, "`5.5`", "; interim path: E05", "; E05")),
    Mutation("M-111", "G-CROWS", drop_row(C_HEAD, "C-24")),
    Mutation("M-112", "G-CLAUSE", row_edit(CLAUSE_HEAD, "`5.1`", 3, to("at risk"))),
    Mutation("M-113", "G-CROWS", drop_row(C_HEAD, "C-25")),
    Mutation(
        "M-114",
        "G-GROWS",
        line_sub("- **G-14**", "PROPOSED `color.text.secondary`", "a colour to be chosen"),
    ),
    Mutation(
        "M-115",
        "G-CVD",
        drop_row(CVD_HEAD, "`color.status.success.strong` / `color.status.warning.strong`"),
    ),
    Mutation("M-116", "G-CVD", sub_in(CVD_HEAD, "tritanopia and greyscale (", "tritanopia (")),
    Mutation(
        "M-117",
        "G-CVD",
        sub_in(CVD_HEAD, "is an identity, not a simulation's collapse", "is a collapse"),
    ),
    Mutation("M-118", "G-CLAUSE", row_edit(CLAUSE_HEAD, "`3.3.2`", 3, to("out of scope — the UI"))),
    Mutation(
        "M-119",
        "G-UNTOUCHED",
        line_sub("9. Sign-off per RULED", "`KM` and `RK` untouched", "`KM` untouched"),
    ),
    Mutation(
        "M-120",
        "G-LOCKED",
        row_sub(
            "1.3 Locked",
            "E36-D03's BQ-D03-2: SCR-088's tree is CMP-240 TreeView as E13-D02 G-1 proposed it",
            "E36-D03:179",
            "E36-D03",
        ),
    ),
    Mutation("M-121", "G-CLAUSE", sub_in(CLAUSE_HEAD, " (deviation D4)", "")),
    Mutation("M-122", "G-ARM", sub_in(ARM_HEAD, ", the DEMO leg PROPOSED there (memo SC-21)", "")),
    Mutation("M-123", "G-FOCUS", row_edit(FOCUS_HEAD, "SCR-087", 2, to("the page"))),
    Mutation(
        "M-124", "G-FOCUS", row_edit(FOCUS_HEAD, "the disarm confirm", 2, to("Cancel (PROPOSED)"))
    ),
    Mutation("M-125", "G-CROWS", drop_row(C_HEAD, "C-26")),
    Mutation("M-126", "G-CLAUSE", row_edit(CLAUSE_HEAD, "`3.4.7`", 3, to("compliant"))),
    Mutation("M-127", "G-SCRIPT", row_edit(AL_HEAD, "AL-16", 4, to("Q06 scenario 1"))),
    Mutation("M-128", "G-NAMES", drop_row(NAME_HEAD, "N-54")),
    Mutation("M-129", "G-ROUTE", drop_row(RT, "RT-23")),
    Mutation("M-130", "G-ROUTE", row_edit(RT, "RT-08", 2, to("a T2 press"))),
    Mutation("M-131", "G-ROUTE", drop_row(RT, "RT-21")),
    Mutation(
        "M-132", "G-FROWS-RULED", row_sub(FH, "F-09", "; board D03 06 draws the lead line", "")
    ),
    Mutation("M-133", "G-FROWS-RULED", row_sub(FH, "F-11", "the F form is RULED BQ-18's: ", "")),
    Mutation("M-134", "G-CROWS", drop_row(C_HEAD, "C-23")),
    Mutation("M-135", "G-SUMMARY", row_sub(RT, "RT-09", ', with no `role="alert"`', "")),
    Mutation(
        "M-136",
        "G-KEYS",
        sub_in(
            KEY_HEAD, "Every key the six screens bind is typed with its source line, and e", "E"
        ),
    ),
    Mutation(
        "M-137",
        "G-NAMES",
        sub_in(NAME_HEAD, "one row for every interactive element the six screens draw", "rows"),
    ),
    Mutation(
        "M-138",
        "G-ROUTE",
        sub_in(
            RT, " Every announced string D02 §7 and D03 §10 bind has its row here (BQ-5 (g)).", ""
        ),
    ),
    Mutation("M-139", "G-CLAUSE", line_sub("- **R-3", "<epic>", "<owner>")),
)

# the tool's own probes: X = a paraphrase a gate must catch, P = a pin class, N = must trip nothing
PROBES: tuple[Mutation, ...] = (
    Mutation("X-01", "G-FIRE", say_in(LOG_HEAD, "The grid also announces each failed firing.")),
    Mutation("X-02", "G-FIRE", rep("and the page never repeats it", "and the list repeats it")),
    Mutation("X-03", "G-ARM", say_in(RADIO_HEAD, "Arm anyway arms the rule at once.")),
    Mutation("X-04", "G-ESC", say_in(RADIO_HEAD, "Enter on a radio arms the rule.")),
    Mutation("X-05", "G-DESC", say_in(ARM_HEAD, "The description is shortened to two lines.")),
    Mutation("X-06", "G-DESC", say_in(ARM_HEAD, "A read more link opens the rest.")),
    Mutation("X-07", "G-PILL", say_in(LOG_HEAD, "The grid auto-scrolls to the newest firing.")),
    Mutation("X-08", "G-NEVER", say_in(LOG_HEAD, "Each firing is announced as it arrives.")),
    Mutation(
        "X-09", "G-ROUTE", say_in(LOG_HEAD, "The resolver's refusal waits until the user is idle.")
    ),
    Mutation("X-10", "G-ROUTE", say_in(LOG_HEAD, "The filter result interrupts the reader.")),
    Mutation("X-11", "G-HCBAR", say_in(ZOOM_HEAD, "High contrast uses the same text bar as dark.")),
    Mutation("X-12", "G-MOTION", say_in(ZOOM_HEAD, "The shimmer is acceptable as drawn.")),
    Mutation("X-13", "G-TIME", say_in(ZOOM_HEAD, "The activation guard is a time limit.")),
    Mutation("X-14", "G-SCOPE", say_in(ZOOM_HEAD, "The tree can reveal the hidden rule.")),
    Mutation("X-15", "G-AT", say_in(SR_HEAD, "We tested this with two screen readers.")),
    Mutation("X-16", "G-SIGNOFF", say_in(WALK_HEAD, "The accessibility lead approved the review.")),
    Mutation("X-17", "G-CLOSE", say_in(WALK_HEAD, "This fixes #939.")),
    Mutation("X-18", "G-CHARSET", say_in("0. Status", "The pill reads Arm on LIVE….")),
    Mutation("X-19", "G-CHARSET", lambda s: s.replace("\n", "\r\n", 1)),
    Mutation("X-20", "G-CHARSET", rep("never lands on Arm", "never lands on\u200b Arm")),
    Mutation("X-21", "G-ANCHOR", say_in(TARGET_HEAD, "Rows are 24 px tall.")),
    Mutation("X-22", "G-MARKER", say_in("0. Status", "<!-- a hidden note -->")),
    Mutation("X-23", "G-HEX", say_in("0. Status", "The ring is #6EA1F5.")),
    Mutation("X-24", "G-PENDING", say_in(LOG_HEAD, "The routing table is approved.")),
    Mutation("X-25", "G-CELLS", row_edit(RT, "RT-13", 6, lambda c: c + " | an extra cell")),
    Mutation("X-26", "G-MUTLIST", row_edit(MUTATION_HEAD, "M-01", 2, to("G-NEVER: a wrong gate"))),
    Mutation(
        "X-27",
        "G-PROGRESS",
        say_in(ZOOM_HEAD, "Progress speaks at most every 2<!--=TIME:d02.progress--> s."),
    ),
    Mutation("X-28", "G-KEYS", say_in(ZOOM_HEAD, "We add a new shortcut for Apply.")),
    # the adversary lens's paraphrases that reached the pins alone (A03 ... A38), each now a gate's
    Mutation(
        "X-29",
        "G-FIRE",
        rep(
            "SCR-087 speaks no individual firing.",
            "It is untrue that SCR-087 speaks no individual" " firing.",
        ),
    ),
    Mutation(
        "X-30",
        "G-DESC",
        say_in(ARM_HEAD, "Screen readers may abbreviate the restatement after the first reading."),
    ),
    Mutation(
        "X-31",
        "G-PILL",
        rep(
            "rows insert on a press only",
            "rows insert on a press only while the viewport follows the newest row",
        ),
    ),
    Mutation(
        "X-32",
        "G-HCBAR",
        say_in(
            CONTRAST_HEAD, "In high contrast, text is held to the same threshold as dark and light."
        ),
    ),
    Mutation("X-33", "G-SIGNOFF", say_in(DOD_HEAD, "The CDO's delegate gave the nod on #939.")),
    Mutation(
        "X-34", "G-PENDING", say_in(LOG_HEAD, "The routing table now governs every consumer.")
    ),
    Mutation("X-35", "G-AT", say_in(SR_HEAD, "Two screen readers confirmed the reading order.")),
    Mutation(
        "X-36",
        "G-NODRAW",
        say_in("0. Status", "A fresh sketch of board 06 accompanies this review."),
    ),
    Mutation("X-37", "G-ESC", row_sub(SC_HEAD, "2.4.3", "never lands on Arm", "may land on Arm")),
    Mutation(
        "X-38",
        "G-ESC",
        row_edit(KEY_HEAD, "K-08", 2, to("close; confirm the pending arm; write nothing")),
    ),
    Mutation(
        "X-39",
        "G-CLOSE-RULE",
        say_in(FH, "A finding also closes when the reviewer ticks it in the register."),
    ),
    Mutation(
        "X-40",
        "G-HCBAR",
        rep(
            "Every gated pair passes in dark and light",
            "Every gated pair passes in dark, light and high contrast at the text bar",
        ),
    ),
    Mutation(
        "X-41",
        "G-ESC",
        row_edit(
            CLAUSE_HEAD, "`3.3.3`", 2, to("`Esc` commits the chosen order (D02:273; D03:354)")
        ),
    ),
    Mutation(
        "X-42",
        "G-FIRE",
        say_in(LOG_HEAD, "Each new firing is also voiced by the grid's live region."),
    ),
    Mutation(
        "P-01",
        "G-RULED-PIN",
        row_edit("2. Inventory", "the two keyboard boards", 1, to("cited, not reviewed")),
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
        in_lines("2. Inventory", _swap_first_rows),
    ),
    Mutation(
        "P-04",
        "G-RULED-PIN",
        sub_in("1.1 What this", "It edits no merged text: ", "It edits no merged text. "),
    ),
    Mutation("N-01", "", sub_in("1.1 What this", "It edits no merged", "It edits  no merged")),
)


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
    extra = tuple(other_d04_files())
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
    ap = argparse.ArgumentParser(description="E35-D04 a11y review audit (module docstring)")
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
    extra = tuple(other_d04_files())
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
        shown = spec_path.relative_to(ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        out = [f"## E35-D04 audit of {shown} at base {BASE}"]
        out.append(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        out += [f"WARN {w}" for w in warns] + notes
        out += [f"FAIL {x}" for x in fails] or ["OK - every gate passed"]
        out.append(f"summary: {len(fails)} FAIL, {len(warns)} WARN, {len(notes)} NOTE")
        print("\n".join(ascii_line(x) for x in out))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
