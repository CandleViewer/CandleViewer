#!/usr/bin/env python3
"""E33-D05 (#989) audit: the accessibility design review of the algo builders and monitor.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the token JSON (`themes.json` layering: dark = primitives
+ semantic-dark, light = + semantic-light, hc = + semantic-hc), the plan texts, the merged E33
specs D02 / D03 / D04 and the hand-offs H03 / D04H, the `PAIRS_TABLE` literals of
`e33_d02_algo_builders_audit.py` and `e33_d03_oco_monitor_audit.py` (parsed, never imported),
D04 section 10's table, the CVD source `docs/research/_tools/cvd_simulate.py` (its constants
parsed, never imported), the reserved-key fixture of E11-D07 and the keymap; then this ticket's
spec from the working tree, and the working-tree files the review must leave untouched (compared
with `git merge-base HEAD origin/main`, never a fixed sha). RULED BQ-34: no hand-off file.

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: COUNT (boards, renders and
   frames at the base, the spec's own table rows, the fixture's matches per K row), BAR / TIME /
   RATE / GEOM (parsed from the cited lines or the token JSON), CONTRAST (WCAG 2.x, two decimals
   rounded half up, truncated instead when rounding would lift a value onto a bar it fails), CVD
   (CIE76 dE under the Machado 2009 / Brettel port, one decimal truncated), GREY (the CIELAB L*
   gap of the Rec. 601 luma greys). `--fill` writes `VALUE<!--=KIND:key-->`; `--check`
   re-derives every anchored value (G-ANCHOR, with a left boundary: the value must not be the
   tail of a longer number) and FAILs on a figure typed by hand.
2. **Lexicon gates.** Each reads every rendered unit (table rows cell by cell, bullets,
   paragraphs, headings, fence lines) after the comment strip, NFKC, markup dropped, dashes to
   spaces, lower case; quoted copy is not a claim; a negation covers its term within five words.
   The mutation table (section 15) and the A table's Old cells are skipped. Synonym sets carry
   each ruled behaviour, and a need-check keeps each ruled sentence's own words; the pins stay the
   backstop. Structure first: G-CHARSET and G-CELLS.
3. **Then the table and measured gates**, then the cites (at the base), G-VERSION (a pinned input
   that differs at origin/main FAILs; a cited range is every line in it), G-UNTOUCHED (committed,
   uncommitted and staged, against the merge-base; an unresolved merge-base FAILs), then the pins.
4. **Pins (G-RULED-PIN).** Whole-document default-deny: every heading, table row (by lead cell),
   rule line, prose sentence and fenced block, keyed by heading path + occurrence, with each
   region's line shape. `--repin-ruled` is the only writer. A pin finding in a section another
   gate already FAILs prints as a NOTE, so one wrong form yields one FAIL.
5. **--self-test** applies every section-15 mutation in memory (plus the tool's probes): each must
   add exactly one FAIL from the gate it names, and every text is restored byte-identically
   (sha256 in memory and on disk). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e33_d05_a11y_review_audit.py --check [SPEC] [--json] [--fill]
  python3 -I docs/design/_tools/e33_d05_a11y_review_audit.py --self-test
  python3 -I docs/design/_tools/e33_d05_a11y_review_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL. G-UNTOUCHED and G-VERSION read the local `origin/main`:
run `git fetch` first; a stale or missing ref fails closed (a false FAIL, never a false pass).
"""

from __future__ import annotations

import argparse
import ast
import datetime
import difflib
import functools
import hashlib
import itertools
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
BASE = "5fa89c5903"  # every cite was read here (the spec's Inputs line; the merge-base at start)
HEAD = "origin/main"  # G-VERSION: a pinned input that differs here FAILs
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E33/E33-D05.md"
RULED_PIN_TXT = "docs/design/_tools/e33_d05_ruled_pins.txt"
THEME_DIR = "packages/ui/tokens"
FIXTURE_REL = "docs/design/_tools/e11_d07_sr_reserved_keys.json"
D02_TOOL_REL = "docs/design/_tools/e33_d02_algo_builders_audit.py"
D03_TOOL_REL = "docs/design/_tools/e33_d03_oco_monitor_audit.py"
CVD_SOURCE_REL = "docs/research/_tools/cvd_simulate.py"  # the port's source (RULED BQ-26)
GREY_SOURCE_REL = "docs/design/_tools/cvd_sim.py"  # the greyscale leg's source (RULED BQ-26)
IMG_E33 = "docs/design/E33/img"
FEATURES_REL = "apps/web/src/features"
UI_SRC_REL = "packages/ui/src"
RULING_ID = "6446955065"
BQ_LIST_ID = "6446697369"
PENDING = "PROPOSED, owner approval pending (#2701)"
D04_PENDING = "PENDING (text-first; E33-D04 #988 boards)"
SPEC_LINE_BUDGET = 900  # RULED BQ-36: the spec at about 900 lines at most

CITE_FILES = {
    "D02": "docs/design/E33/E33-D02.md",
    "D03": "docs/design/E33/E33-D03.md",
    "H03": "docs/design/E33/E33-D03-handoff.md",
    "D04": "docs/design/E33/E33-D04.md",
    "D04H": "docs/design/E33/E33-D04-handoff.md",
    "KM": "apps/web/src/keymap/keymap.json",
    "README": "docs/design/README.md",
    "E33.json": "docs/plan/backlog/E33.json",
}
# never edited by this ticket (the ruling's "Standing" line); compared with the merge-base of HEAD
# and origin/main, committed and uncommitted alike
UNTOUCHED = ("05", "14", "15", "16", "D02", "D03", "H03", "D04", "D04H", "KM")
# named only, never cited by line or quoted: unmerged work, and E36-D05 (merged at #4755, inside the base; kept named only)
UNMERGED = ("E33-D06", "E33-Q05", "E33-D07", "E36-D05")
# the consumers RULED BQ-34 names (comments at merge; nothing filed)
CONSUMERS = ("#990", "#1100", "#1105", "#1106", "#988")
STORIES = ("#1105", "#1106", "#990", "#1100")  # §0 names them (BQ list, the standing conditions)
# the inputs G-VERSION pins: each must read the same at origin/main as at the base
PINNED_INPUTS = (
    "docs/plan/02-definition-of-ready-done.md",
    "docs/plan/05-accessibility-standard.md",
    "docs/plan/14-screens-catalogue.md",
    "docs/plan/15-component-catalogue.md",
    "docs/plan/16-design-system-brief.md",
    "docs/design/E33/E33-D02.md",
    "docs/design/E33/E33-D03.md",
    "docs/design/E33/E33-D03-handoff.md",
    "docs/design/E33/E33-D04.md",
    "docs/design/E33/E33-D04-handoff.md",
    "docs/design/E29/E29-D05.md",
    "docs/design/E35/E35-D04.md",
    "docs/design/README.md",
    "docs/plan/backlog/E33.json",
    "apps/web/src/keymap/keymap.json",
    "packages/ui/tokens/primitives.tokens.json",
    "packages/ui/tokens/semantic-dark.tokens.json",
    "packages/ui/tokens/semantic-light.tokens.json",
    "packages/ui/tokens/semantic-hc.tokens.json",
    "packages/ui/tokens/themes.json",
    CVD_SOURCE_REL,
    GREY_SOURCE_REL,
    FIXTURE_REL,
    D02_TOOL_REL,
    D03_TOOL_REL,
)

THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SIMS = ("protanopia", "deuteranopia", "tritanopia")
GREY = "greyscale"  # RULED BQ-26's fourth leg: Rec. 601 luma, floored (cvd_sim.py)

# the clause checklist of RULED BQ-5 (one row each in §3), plus the ticket's security note
CLAUSES = (
    *(f"3.1.{n}" for n in range(1, 8)),
    "3.2",
    *(f"3.3.{n}" for n in range(1, 7)),
    *(f"3.4.{n}" for n in range(1, 11)),
    "4.1",
    "4.2",
    "4.3",
    "4.4",
    *(f"5.{n}" for n in range(1, 8)),
    "6.1",
    "6.2a",
    "6.2b",
    "6.2c",
    "6.2d",
    "6.3",
    "6.4",
    "6.5",
    "7.1",
    "7.2",
    "7.3",
    "7.4",
    "14:0.5.1",
    "14:0.5.2",
    "14:0.5.4",
    "14:0.5.5",
    "14:0.5.6",
    "02:180",
    "T Sec",
)
# the WCAG 2.2 cross-walk of RULED BQ-5 (one row each in §4), with 3.3.4 for the send paths
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
    "2.5.8",
    "3.2.1",
    "3.2.2",
    "3.3.1",
    "3.3.3",
    "3.3.4",
    "4.1.2",
    "4.1.3",
    "2.3.3 (AAA)",
)
VERDICT = re.compile(
    r"^(?:compliant|at risk|non-compliant|out of scope — E\d\d\b.*"
    r"|not yet decidable — routed to E33-Q05)$"
)
SEVERITIES = ("Blocking", "Major", "Minor", "Info")

# ---------------------------------------------------------------------------- regexes

PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'(?<!=)"[^"\n]*"')  # an attribute value (role="note") is not copy
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
FIGURE = re.compile(
    r"(?<![\w.,:#/>{-])(\d+(?:[.,]\d+)*)\s?(ms|s|hz|px|%|:1)(?![\w])"
    r"|(?<![\w.,:#/>{-])(\d+)\s?×\s?(\d+)(?![\w])",
    re.IGNORECASE,
)
COUNTED = re.compile(
    r"(?<![\w.,:#/>{-])(\d+)\s+(?:boards?|renders?|findings?|clauses?|criteria|pairs?|"
    r"mutations?|questions?|signals?|strings?|lines?|rows?|cells?|units?|elements?|frames?|"
    r"times|items?|characters?|treatments?|names?|keys?|roles?|surfaces?)\b",
    re.IGNORECASE,
)
CITE_GROUP = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:D0[234]H?|H03|README|E\d\d-D\d\d)\b)) ?"
    r":(?P<first>\d+(?:[–-]\d+)?)(?P<more>(?:(?:\s*\([^()\n]*\))?,\s*:\d+(?:[–-]\d+)?)*)"
)
MUT_ROW = re.compile(r"^\| G-[A-Z0-9-]+ \|")  # a section-15 row (its cells describe violations)
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*(?:[\w.-]+/[\w.-]+)?#\d+",
    re.IGNORECASE,
)

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


def fork_point() -> str | None:
    """`git merge-base HEAD origin/main` (G-UNTOUCHED's reference; never a fixed sha)."""
    return git_out("merge-base", "HEAD", HEAD).strip() or None


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
    """For each line, whether it is a fence line or inside a fenced block."""
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


def tables(block: str) -> list[list[list[str]]]:
    """Every table in `block`, each as its data rows."""
    out: list[list[list[str]]] = []
    rest = block
    while True:
        rows = table(rest)
        if not rows:
            return out
        out.append(rows)
        lines = rest.split("\n")
        idx = [i for i, ln in enumerate(lines) if re.match(r"^ {0,3}\|", ln)]
        first = idx[0]
        end = first
        while end < len(lines) and re.match(r"^ {0,3}\|", lines[end]):
            end += 1
        rest = "\n".join(lines[end:])


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
    t = DOUBLE_NEG.sub(" ", t)
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
    data = json.loads(at_base(f"{THEME_DIR}/{name}.tokens.json"))
    return {k: v.get("$value") for k, v in data.items() if isinstance(v, dict)}


@functools.lru_cache(maxsize=4)
def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        merged.update(token_file(f))
    return merged


def themes_json_ok() -> bool:
    data = json.loads(at_base(f"{THEME_DIR}/themes.json"))
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
# Fernandes 2009 tritan matrix at severity 1.0 (#4652's row), carried as constants; G-CVD re-reads
# them from `docs/research/_tools/cvd_simulate.py` at the base (parsed, never imported).
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
# the pre-#4652 tritan row (the projection D04's tool still carries); never used, only refused
DEFECTIVE_TRITAN_ROW = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -0.395913, 0.801109, 0.0)
CVD_PINNED = {  # protan, deutan, tritan, then greyscale (the E35-D04 port's own pins)
    "#2EBD59": ("#B4B458", "#A3A35D", "#00B9A6", "#868686"),
    "#E5484D": ("#6B6B4E", "#8F8F44", "#FB194B", "#777777"),
}
GREY_WEIGHTS = (0.299, 0.587, 0.114)  # Rec. 601, applied to the sRGB bytes, then floored
JND_FLOOR = 5.0  # cvd_simulate.py's JND_FLOOR (G-CVD reads it)


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


def cvd_source_problems() -> list[str]:
    """The carried constants against the source's literals at the base (parsed, never imported)."""
    want: dict[str, object] = {
        "RGB_TO_LMS": RGB_TO_LMS,
        "LMS_TO_RGB": LMS_TO_RGB,
        "PROJECTIONS": PROJECTIONS,
        "TRITAN_MACHADO": TRITAN_MACHADO,
        "JND_FLOOR": JND_FLOOR,
    }
    got: dict[str, object] = {}
    for node in ast.parse(at_base(CVD_SOURCE_REL)).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in want:
            got[str(getattr(node.targets[0], "id", ""))] = ast.literal_eval(node.value)
    bad = [f"{k} differs from {CVD_SOURCE_REL}" for k, v in want.items() if got.get(k) != v]
    if TRITAN_MACHADO == DEFECTIVE_TRITAN_ROW:
        bad.append("the tritan row is the pre-#4652 projection")
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
    src: str  # D02 | D03 | D04 | composed
    printed: tuple[str, ...] = ()  # the source's printed dark / light / hc values, when it prints


def role_of(raw: str) -> str:
    r = raw.strip()
    if r.startswith("rejected"):
        return "rejected"
    return {"text": "text", "non-text": "non-text"}.get(r, "decorative")


def literal_table(rel: str, name: str) -> str:
    """A module-level string literal of a merged tool at the base, parsed (never imported)."""
    tree = ast.parse(at_base(rel))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == name:
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise SystemExit(f"FAIL parse: no {name} string in {rel}")


def tool_pairs(rel: str, src: str) -> list[Pair]:
    """A merged tool's `PAIRS_TABLE` literal (element | fg | bg | role)."""
    out: list[Pair] = []
    for ln in literal_table(rel, "PAIRS_TABLE").strip().split("\n"):
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) == 4:
            out.append(Pair(cells[1], cells[2], role_of(cells[3]), src))
    return out


def printed_rows(rel: str, head: str) -> dict[tuple[str, str, str], tuple[str, str, str]]:
    """A merged spec's measured table (element | fg | bg | role | dark | light | hc | ...)."""
    out: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    for r in table(section(at_base(rel), head)):
        if len(r) >= 7:
            fg, bg = r[1].strip("`"), r[2].strip("`")
            vals = tuple(re.sub(r":1.*$", "", strip_comments(x)).strip() for x in r[4:7])
            out[(fg, bg, r[3].strip())] = (vals[0], vals[1], vals[2])
    return out


def d04_pairs() -> list[Pair]:
    """D04 §10's rows at the base (key | fg | bg | role | dark | light | hc)."""
    out: list[Pair] = []
    for r in table(section(at_base(CITE_FILES["D04"]), "10. Contrast")):
        toks = [c.strip("`") for c in r[1:3]] if len(r) >= 7 else []
        if len(toks) == 2 and toks[0].startswith("color."):
            vals = tuple(re.sub(r":1$", "", strip_comments(x)).strip() for x in r[4:7])
            out.append(Pair(toks[0], toks[1], role_of(r[3]), "D04", vals))
    return out


_S = "color.status."
_T = "color.text."
# the compositions RULED BQ-27 names; keys are the spec's CONTRAST anchors
COMPOSED: dict[str, tuple[str, str, str]] = {
    "focus.warning": ("color.focus.ring", _S + "warning.subtle", "non-text"),
    "focus.danger": ("color.focus.ring", _S + "danger.subtle", "non-text"),
    "focus.selected": ("color.focus.ring", "color.surface.selected", "non-text"),
    "t2.selected": (_T + "tertiary", "color.surface.selected", "measured"),
    "t2fix.selected": (_T + "secondary", "color.surface.selected", "text"),
    "bar.hover": ("color.action.primary.default", "color.surface.hover", "non-text"),
}
HC_PAIR = (_T + "on-action", _S + "danger.default")  # RULED BQ-27: the danger buttons


@functools.lru_cache(maxsize=1)
def union() -> tuple[Pair, ...]:
    d02 = tool_pairs(D02_TOOL_REL, "D02")
    d03 = tool_pairs(D03_TOOL_REL, "D03")
    comp = [Pair(fg, bg, role, "composed") for fg, bg, role in COMPOSED.values()]
    return tuple(d02 + d03 + d04_pairs() + comp)


@functools.lru_cache(maxsize=1)
def bar_values() -> tuple[tuple[str, str], ...]:
    return (
        ("text", grab(r"≥(\d+(?:\.\d+)?):1", base_line("05", 125), "`05`:125 text bar")),
        ("nontext", grab(r"≥(\d+(?:\.\d+)?):1", base_line("05", 126), "`05`:126 non-text")),
        ("hc", grab(r"≥(\d+(?:\.\d+)?):1 body text", base_line("05", 130), "`05`:130 hc bar")),
    )


def bars() -> dict[str, float]:
    return {k: float(v) for k, v in bar_values()}


def bar_for(role: str, theme: str) -> float | None:
    b = bars()
    if role == "text":
        return b["hc"] if theme == "hc" else b["text"]
    if role == "non-text":
        return b["nontext"]
    return None


def measure(p: Pair) -> dict[str, float | None]:
    return {t: ratio(t, p.fg, p.bg) for t in THEMES}


def hc_under() -> list[Pair]:
    """Gated text pairs below the high-contrast bar, one per distinct (fg, bg)."""
    seen: dict[tuple[str, str], Pair] = {}
    for p in union():
        r = ratio("hc", p.fg, p.bg)
        if p.role == "text" and r is not None and r < bars()["hc"]:
            seen.setdefault((p.fg, p.bg), p)
    return list(seen.values())


def printed_agreement() -> tuple[int, int]:
    """D02 §10's, D03 §14's and D04 §10's printed cells against the re-measure (two decimals)."""
    agree = total = 0
    rows: list[tuple[str, str, tuple[str, ...]]] = []
    for rel, head in ((CITE_FILES["D02"], "10. Themes"), (CITE_FILES["D03"], "14. Measured")):
        rows += [(k[0], k[1], v) for k, v in printed_rows(rel, head).items()]
    rows += [(p.fg, p.bg, p.printed) for p in d04_pairs()]
    for fg, bg, vals in rows:
        for t, printed in zip(THEMES, vals, strict=True):
            r = ratio(t, fg, bg)
            if not re.fullmatch(r"\d+\.\d+", printed) or r is None:
                continue
            total += 1
            agree += int(abs(float(printed) - r) <= 0.0051)
    return agree, total


# ---------------------------------------------------------------------------- the treatments

# RULED BQ-26 (confirmed): every status treatment of AC3 and D04 §3.1's families, with its fill,
# its glyph colour and its word (D04:165–173; the words D03:210–224)
TREATMENTS: dict[str, tuple[str, str]] = {
    "running": ("color.surface.hover", _T + "primary"),
    "paused": (_S + "warning.subtle", _S + "warning.strong"),
    "degraded-1": ("color.data-confidence.stale.surface", "color.data-confidence.stale.text"),
    "degraded-2": (_S + "warning.subtle", _S + "warning.strong"),
    "halted": (_S + "danger.subtle", _S + "danger.strong"),
    "failed": (_S + "danger.subtle", _S + "danger.strong"),
    "orphaned": (_S + "warning.subtle", _S + "warning.strong"),
    "done": (_S + "success.subtle", _S + "success.strong"),
    "cancelled": ("color.surface.hover", _T + "primary"),
}


# the other colour-carrying pairs of §9.1 (RULED BQ-26: computed CVD over every pair)
OTHER_PAIRS: dict[str, tuple[str, str]] = {
    "buysell": ("color.buy.default", "color.sell.default"),  # CR-11
    "stop": (_S + "success.strong", _S + "danger.strong"),  # CR-12
}


def fills() -> list[str]:
    return sorted({f for f, _g in TREATMENTS.values()})


def glyph_colours() -> list[str]:
    return sorted({g for _f, g in TREATMENTS.values()})


def sim_dist(theme: str, a: str, b: str, sim: str) -> float:
    ha, hb = hex_of(theme, a), hex_of(theme, b)
    if ha is None or hb is None:
        raise SystemExit(f"FAIL parse: {a} / {b} do not resolve in {theme}")
    if sim == GREY:
        return abs(lab(simulate(ha, GREY))[0] - lab(simulate(hb, GREY))[0])
    return delta_e76(simulate(ha, sim), simulate(hb, sim))


def treatment_min(name: str, sim: str) -> float:
    """The treatment's fill against every OTHER fill, the minimum over the three themes."""
    own = TREATMENTS[name][0]
    return min(sim_dist(t, own, f, sim) for t in THEMES for f in fills() if f != own)


def set_min(group: list[str], sim: str, theme: str) -> float:
    return min(sim_dist(theme, a, b, sim) for a, b in itertools.combinations(group, 2))


def under_floor(group: list[str]) -> int:
    """Pairs of `group` under the JND floor in any theme and any of the three simulations."""
    n = 0
    for a, b in itertools.combinations(group, 2):
        if any(sim_dist(t, a, b, s) < JND_FLOOR for t in THEMES for s in SIMS):
            n += 1
    return n


def cvd_values() -> dict[str, str]:
    out: dict[str, str] = {}
    keys = {"protanopia": "protan", "deuteranopia": "deutan", "tritanopia": "tritan", GREY: "grey"}
    for name in TREATMENTS:
        for sim, k in keys.items():
            kind = "GREY" if sim == GREY else "CVD"
            out[f"{kind}:{name}.{k}"] = trunc1(treatment_min(name, sim))
    for sim, k in keys.items():
        for th in ("dark", "light"):
            kind = "GREY" if sim == GREY else "CVD"
            out[f"{kind}:fill.{k}.{th}"] = trunc1(set_min(fills(), sim, th))
            out[f"{kind}:glyph.{k}.{th}"] = trunc1(set_min(glyph_colours(), sim, th))
    for name, (a, b) in OTHER_PAIRS.items():
        for sim, k in keys.items():
            kind = "GREY" if sim == GREY else "CVD"
            out[f"{kind}:{name}.{k}"] = trunc1(min(sim_dist(t, a, b, sim) for t in THEMES))
    out["COUNT:fills"] = str(len(fills()))
    out["COUNT:fill.pairs"] = str(len(list(itertools.combinations(fills(), 2))))
    out["COUNT:fill.under"] = str(under_floor(fills()))
    out["COUNT:glyph.under"] = str(under_floor(glyph_colours()))
    out["CVD:floor"] = trunc1(JND_FLOOR)
    return out


# ---------------------------------------------------------------------------- values


def grab(pattern: str, text: str, what: str) -> str:
    m = re.search(pattern, strip_comments(text), MULTI)
    if not m:
        raise SystemExit(f"FAIL parse: {what} not found ({pattern})")
    return m[1]


RENDER = re.compile(r"-(?:greyscale|deuteranopia|protanopia|tritanopia)\.png$")


def board_counts() -> dict[str, str]:
    names = [Path(n).name for n in ls_tree(BASE, IMG_E33)]

    def render(x: str) -> bool:
        return RENDER.search(x) is not None and RENDER.sub(".png", x) in names

    def boards(prefix: str) -> int:
        return len([x for x in names if re.match(rf"{prefix}-\d\d-", x) and not render(x)])

    def renders(prefix: str, sim: str = "") -> int:
        return len([x for x in names if x.startswith(prefix) and render(x) and sim in x])

    out = {
        "COUNT:boards.d02": str(boards("E33-D02")),
        "COUNT:boards.d03": str(boards("E33-D03")),
        "COUNT:boards.d04": str(boards("E33-D04")),
        "COUNT:renders.d02": str(renders("E33-D02-")),
        "COUNT:renders.d03": str(renders("E33-D03-")),
    }
    for sim in (*SIMS, GREY):
        out[f"COUNT:renders.d02.{sim}"] = str(renders("E33-D02-", sim))
    return out


def time_values() -> dict[str, str]:
    rows = grab(r"with (\d+) running algos", base_line("14", 1622), "`14`:1622 rows")
    hz = grab(r"coalesced to (\d+) Hz", base_line("14", 1622), "`14`:1622 cadence")
    return {
        "TIME:lane": grab(r"at most once every (\d+) s", base_line("14", 1571), "`14`:1571"),
        "TIME:throttle": grab(r"1 update / (\d+)s", base_line("05", 147), "`05`:147"),
        "TIME:pause": grab(r">(\d+)s", base_line("05", 207), "`05`:207"),
        "RATE:flash.limit": grab(
            r"more than (\d+) times per second", base_line("05", 208), "`05`:208"
        ),
        "TIME:guard": grab(r"≥(\d+) ms after open", base_line("H03", 79), "H03:79"),
        "TIME:autocancel": grab(r"the (\d+) s auto-cancel", base_line("D02", 114), "D02:114"),
        "TIME:header": grab(r"≤ 1 / (\d+) s", base_line("H03", 120), "H03:120"),
        "RATE:render": grab(r"at most (\d+) Hz", base_line("D04", 272), "D04:272"),
        "COUNT:monitor.rows": rows,
        "RATE:monitor": hz,
        "COUNT:monitor.updates": str(int(rows) * int(hz)),
    }


def geom_values() -> dict[str, str]:
    frame = re.search(r"Reflow \((\d+) × (\d+) and", strip_comments(base_line("D02", 159)))
    ring = base_line("D02", 155)
    if not frame:
        raise SystemExit("FAIL parse: D02:159 frame")

    def tok(name: str) -> str:
        v = resolve("dark", name)
        if not re.fullmatch(r"\d+", v):
            raise SystemExit(f"FAIL parse: token {name} = {v}")
        return v

    return {
        "GEOM:focus.width": grab(r"double focus ring \((\d+) px", ring, "D02:155 ring"),
        "GEOM:halo": grab(r"outside a (\d+) px `color\.surface\.overlay` halo", ring, "halo"),
        "GEOM:footer": grab(r"one sticky row, (\d+) px", ring, "D02:155 footer"),
        "GEOM:target.min": tok("size.target.min"),
        "GEOM:target.comfortable": tok("size.control.comfortable"),
        "GEOM:row.compact": tok("space.row.height.compact"),
        "GEOM:row.comfortable": tok("space.row.height.comfortable"),
        "GEOM:zoom": grab(r"(\d+)% browser", base_line("05", 131), "`05`:131 zoom"),
        "GEOM:frame.w": frame[1],
        "GEOM:frame.h": frame[2],
        "GEOM:dialog": grab(r"(\d+) px wide PROPOSED", base_line("D02", 145), "D02:145"),
        "GEOM:dock": grab(r"The (\d+)\s+px core", base_line("D03", 202), "D03:202"),
        "GEOM:actions": grab(r"the (\d+) × \d+ Actions", base_line("H03", 131), "H03:131"),
        "GEOM:textscale": grab(r"`100\|112\|(\d+)\|150`", base_line("16", 138), "`16`:138"),
    }


def frame_ids(rel: str, head: str) -> list[str]:
    """The frame ids (first-cell code spans) of every table under the heading `head` at BASE."""
    out: list[str] = []
    for rows in tables(section(at_base(rel), head)):
        for r in rows:
            out += [x for x in re.findall(r"`((?:SCR|CMP)-\d{3}/[^`]+|motion/[^`]+)`", r[0])]
    return out


# where the merged frames live (the annotation layer's keys, RULED BQ-35)
FRAME_HEADS: tuple[tuple[str, str, str], ...] = (
    ("D02", "3.4 State inventory", "twap"),
    ("D02", "4.3 The projected", "iceberg"),
    ("D02", "5.4 State inventory", "chase"),
    ("D03", "3. SCR-069 — states", "oco"),
    ("D03", "5. SCR-070 — anatomy", "anatomy"),
    ("D03", "6. SCR-070 — the row-kind", "rows"),
    ("D03", "7. SCR-070 — panel states", "panel"),
    ("D03", "8. Bulk actions", "bulk"),
    ("D03", "9. The 100-row", "density"),
)


@functools.lru_cache(maxsize=1)
def merged_frames() -> tuple[tuple[str, str], ...]:
    """(source, frame id) for every merged D02 / D03 frame, in document order."""
    out: list[tuple[str, str]] = []
    for cid, head, _key in FRAME_HEADS:
        out += [(cid, f) for f in frame_ids(CITE_FILES[cid], head)]
    return tuple(out)


@functools.lru_cache(maxsize=1)
def d04_frames() -> tuple[str, ...]:
    """D04 §9.2's frame register (the boards PENDING), the theme suffix dropped."""
    ids = frame_ids(CITE_FILES["D04"], "9.2 The frame register")
    return tuple(dict.fromkeys(re.sub(r" · (?:dark|light)$", "", x) for x in ids))


def frame_counts() -> dict[str, str]:
    mf = merged_frames()
    out = {
        "COUNT:frames.d02": str(sum(1 for c, _f in mf if c == "D02")),
        "COUNT:frames.d03": str(sum(1 for c, _f in mf if c == "D03")),
        "COUNT:frames.merged": str(len(mf)),
        "COUNT:frames.d04": str(len(frame_ids(CITE_FILES["D04"], "9.2 The frame register"))),
        "COUNT:frames.d04.ids": str(len(d04_frames())),
    }
    for cid, head, key in FRAME_HEADS:
        out[f"COUNT:frames.{key}"] = str(len(frame_ids(CITE_FILES[cid], head)))
    return out


def contrast_values() -> dict[str, str]:
    out: dict[str, str] = {}
    r = ratio("hc", *HC_PAIR)
    out["CONTRAST:hc.danger"] = round2(r) if r is not None else "MISSING"
    for k, (fg, bg, _role) in COMPOSED.items():
        for t in THEMES:
            v = ratio(t, fg, bg)
            out[f"CONTRAST:{k}.{t}"] = round2(v) if v is not None else "MISSING"
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
    for s in ("D02", "D03", "D04", "composed"):
        out[f"COUNT:pairs.{s.lower()}"] = str(len(srcs.get(s, set())))
    out["COUNT:pairs.union"] = str(len({(p.fg, p.bg) for p in union()}))
    out["COUNT:pairs.hc-under"] = str(len(hc_under()))
    out["HEX:sunken.dark"] = hex_of("dark", "color.surface.sunken") or "?"
    agree, total = printed_agreement()
    out["COUNT:printed.agree"] = str(agree)
    out["COUNT:printed.values"] = str(total)
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
    v.update({f"BAR:{k}": x for k, x in bar_values()})
    v.update(board_counts())
    v.update(time_values())
    v.update(geom_values())
    v.update(contrast_values())
    v.update(cvd_values())
    v.update(frame_counts())
    v["COUNT:fx.rows"] = str(len(fixture()))
    v["BUDGET:lines.spec"] = str(SPEC_LINE_BUDGET)
    return tuple(sorted(v.items()))


def base_value(key: str) -> str:
    return dict(base_values())[key]


SR_HEAD = "14.1 Tasks"
AL_HEAD = "14.2 The acceptance checklist"
SCRIPT_HEAD = "14.3 "
CLAUSE_HEAD = "3. Clause by clause"
SC_HEAD = "4. WCAG 2.2 cross-walk"
FOCUS_HEAD = "5.1 The focus contract"
PEG_HEAD = "5.2 Radio groups"
MONITOR_HEAD = "5.3 The monitor's keyboard"
KEY_HEAD = "5.4 Keys"
OBSCURED_HEAD = "5.5 Focus visible"
TARGET_HEAD = "5.6 Targets"
FORMS_HEAD = "6.1 Forms"
CAVEAT_HEAD = "6.2 The emulation caveat"
SCHEDULE_HEAD = "6.3 The TWAP schedule"
NOTE_HEAD = "6.4 The OCO residual-risk note"
HEADINGS_HEAD = "6.5 Headings"
NAME_HEAD = "7.1 The names table"
LEAK_HEAD = "7.2 Names never leak"
ROUTE_HEAD = "8.1 The routing table"
AGG_HEAD = "8.2 Algo-child fills"
THROTTLE_HEAD = "8.3 The throttle"
DEGRADED_HEAD = "8.4 The degraded banner"
CARRIER_HEAD = "9.1 The carrier table"
CVD_HEAD = "9.2 Colour-vision"
CONTRAST_HEAD = "10. Contrast"
MOTION_HEAD = "11.1 Motion"
TIME_HEAD = "11.2 Time limits"
ZOOM_HEAD = "11.3 Zoom"
ANNOT_HEAD = "12. The annotation layer"
FINDING_HEAD = "13. The finding register"
C_HEAD = "16.1 Contradictions"
G_HEAD = "16.2 Gaps"
Q_HEAD = "16.3 Open questions"
A_HEAD = A_TABLE_HEAD
WALK_HEAD = "17. The story-role dry run"
DOD_HEAD = "18.1 DoD"
HANDOFF_HEAD = "18.2 Hand-offs"
SUMMARY_HEAD = "19. Summary"
RULED_HEAD = "The thirty-seven questions"


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
    focus = table(section(spec, FOCUS_HEAD))
    out["COUNT:traps"] = str(sum(len(r) == 8 and r[3] == "yes" for r in focus))
    out["COUNT:names"] = str(len(table(section(spec, NAME_HEAD))))
    for r in table(section(spec, KEY_HEAD)):
        if len(r) > 1:
            out[f"COUNT:fx.{r[0]}"] = str(len(fixture_hits(r[1])))
    out.update(walk_values(spec))
    return out


def walk_values(spec: str) -> dict[str, str]:
    """The dry run's counts: needs = the items its role's list names; not found = its → targets;
    the QA row's state rows = §12's rows plus §9.2's."""
    out: dict[str, str] = {}
    block = section(spec, WALK_HEAD)
    para = next((ln for ln in block.split("\n") if ln.startswith("**What each role")), "")
    lists = dict(re.findall(r"\b(E33-[A-Z]\d\d): (.+?)\.(?= E33-|$)", strip_comments(para)))
    tabs = tables(block)
    for rows in tabs[:1]:
        for r in rows:
            m = WALK_ROLE.match(r[1]) if len(r) == 6 else None
            if m:
                needs = len([x for x in lists.get(m[1], "").split(", ") if x.strip()])
                miss = len(WALK_TARGET.findall(r[5]))
                out[f"COUNT:walk.{m[1]}.needs"] = str(needs)
                out[f"COUNT:walk.{m[1]}.found"] = str(needs - miss)
                out[f"COUNT:walk.{m[1]}.not"] = str(miss)
    states = len(table(section(spec, ANNOT_HEAD))) + len(table(section(spec, CVD_HEAD)))
    qa = tabs[1][0] if len(tabs) > 1 and tabs[1] and len(tabs[1][0]) == 6 else []
    miss = len(WALK_TARGET.findall(qa[5])) if qa else 0
    out["COUNT:walk.qa.rows"] = str(states)
    out["COUNT:walk.qa.found"] = str(states - miss)
    out["COUNT:walk.qa.not"] = str(miss)
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


@functools.lru_cache(maxsize=1)
def fence_template_lines() -> frozenset[str]:
    """`05` §10's template lines (verbatim): a fenced line here may carry their figures."""
    text = at_base(plan_rel("05") or "")
    lines = text.split("\n")
    fence = fenced(lines)
    return frozenset(ln.strip() for i, ln in enumerate(lines) if fence[i] and ln.strip())


DATE = re.compile(r"\b\d{4}-\d\d-\d\d\b")


def bare_figures(text: str, values: Values) -> list[tuple[int, str]]:
    """Figures typed by hand: outside an anchor, a quote, a code span, a cite, an issue number,
    a date, the A table's Old cells and a fenced line that is `05` §10's template verbatim."""
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
        work = DATE.sub(" ", re.sub(r"\(#\d+\)|#\d+", " ", work))
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
            bad.append(("G-ANCHOR", f"{doc}:{i + 1} an unclosed comment hides the rest", doc, sec))
        elif am is None or am[1] not in values:
            bad.append(("G-ANCHOR", f"{doc}:{i + 1} a hidden comment {m[0][:40]!r}", doc, sec))
    return bad


def g_hex_doc(doc: str, text: str) -> list[Finding]:
    bad: list[Finding] = []
    for i, line in enumerate(text.split("\n"), 1):
        work = CODE.sub(lambda c: " " * len(c[0]), line)
        for m in HEXLIT.finditer(work):
            if not re.match(r"<!--=HEX:", line[m.end() :]):
                bad.append(("G-ANCHOR", f"{doc}:{i} {m[0]} typed by hand", doc, h2_at(text, i)))
    return bad


# ---------------------------------------------------------------------------- cites

# load-bearing fragments: (cite id, line at the base, text the line must hold)
CITED: tuple[tuple[str, int, str], ...] = (
    ("05", 5, "single source of truth"),
    ("05", 11, "no timing limits"),
    ("05", 30, "no keyboard trap"),
    ("05", 33, "never a mouse-hold-only or timing-only gate"),
    ("05", 35, "hover-only or drag-only"),
    ("05", 63, "Cancel focused order"),
    ("05", 95, "Roving tabindex"),
    ("05", 96, "Focus is never silently stolen"),
    ("05", 97, "return focus to the triggering element on close"),
    ("05", 99, "Focus Not Obscured"),
    ("05", 100, "≥24×24 CSS px"),
    ("05", 125, "≥4.5:1"),
    ("05", 126, "≥3:1"),
    ("05", 129, "near-black (not #000)"),
    ("05", 130, "≥7:1 body text"),
    ("05", 131, "200% browser"),
    ("05", 147, "default 1 update / 2s per field"),
    ("05", 148, "order filled, order rejected"),
    ("05", 148, "never throttled/coalesced"),
    ("05", 150, "pre-rendered empty containers"),
    ("05", 200, "WAI-ARIA APG patterns"),
    ("05", 207, "any auto-moving content lasting >5s"),
    ("05", 208, "more than 3 times per second"),
    ("05", 209, "design-system token/mode"),
    ("05", 224, "exclusively the Electron shell"),
    ("05", 229, "no skipped levels"),
    ("02", 180, 'no "internal tool, a11y doesn\'t matter" exception'),
    ("14", 1559, "Slice schedule is previewed as a table (slice #, planned time, qty)"),
    ("14", 1571, "running state announces refreshes politely at most once every 5 s"),
    ("14", 1584, "Peg configuration is a radio group (best bid / best ask / mid)"),
    ("14", 1596, 'the residual-risk warning is `role="note"` and always visible, not a hover'),
    ("14", 1621, "('Cancel TWAP a_12 on BTCUSDT, Main')"),
    ("14", 1621, 'the degraded banner is `role="status"`'),
    ("14", 1622, "with 100 running algos"),
    ("15", 104, '`role="radiogroup"`, roving tabindex'),
    ("15", 124, "the unit in `aria-valuetext`"),
    ("15", 268, "never a live region"),
    ("15", 269, "a new value moves the fill over `motion.duration.normal`"),
    ("15", 318, "`live` overrides the default"),
    ("15", 386, "except countdowns in a grid column, which announce nothing"),
    ("15", 469, 'a `dialog`\'s close button is named "Close {title}"'),
    ("15", 470, "while the card appears at once"),
    ("15", 529, "grid (interactive cells, the APG Grid pattern"),
    ("15", 1277, "### CMP-115 OrderRow"),
    ("15", 1330, '"(emulated)" text always visible'),
    ("16", 127, "in practice 40-44px"),
    ("16", 138, "`data-text-scale`"),
    ("D02", 111, "**The T2 rule (stated once"),
    ("D02", 114, "the 20 s auto-cancel"),
    ("D02", 145, "Reading order (memo §9a row 8 :543)"),
    ("D02", 150, "never a tooltip, never smaller than body"),
    ("D02", 155, "double focus ring (2 px `color.focus.ring` outside a 1 px"),
    ("D02", 181, "not an APG grid"),
    ("D02", 270, '`role="radiogroup"` named "Peg"'),
    ("D02", 331, "**no new global key is proposed**"),
    ("D02", 331, "`Esc` = Close"),
    ("D02", 337, "a halt, a failure, a rejected slice, a double refusal"),
    ("D02", 415, "`normal` scale + fade"),
    ("D02", 451, "| 4.54  |"),
    ("D03", 140, "help text behind CMP-016 on hover and focus"),
    ("D03", 165, "the 20 s auto-cancel off for an algo"),
    ("D03", 167, "kept until acknowledged"),
    (
        "D03",
        202,
        "Cancel TWAP a_12 on BTCUSDT, Main — its 0.07 BTC order at Bybit is cancelled too",
    ),
    ("D03", 221, "Halted — {user} can no longer trade on {account} — {when}"),
    ("D03", 233, "silent on first render because SCR-152's alert already announced it"),
    ("D03", 264, "`Esc` closes menus and dialogs and never cancels a run"),
    ("D03", 276, "E33-D05 / E29-D05 decide the class"),
    ("D03", 465, "| 4.54  |"),
    ("H03", 79, "the panel header"),
    ("H03", 96, "no announcement on first render"),
    ("H03", 98, "the restatement sentence"),
    ("H03", 120, "≤ 1 / 2 s"),
    ("H03", 161, "the 20 s auto-cancel is off for an algo"),
    ("D04", 213, "tritanopia ΔE76 4.5"),
    ("D04", 244, "Algos — Emulated — run by CandleViewer, not Bybit"),
    ("D04", 573, "the annotation layer reads §3.6 and §4.5"),
    ("D04H", 190, "DR-14"),
    ("E09-D09", 85, "user name"),
    ("E29-D05", 613, "both named; the shipped binding tested until AM-2 lands"),
    ("E35-D04", 440, "Essential exception"),
    ("KM", 413, '"ticket.submit"'),
    ("KM", 503, '"positions.open_sltp"'),
    ("KM", 523, '"positions.close"'),
    ("KM", 535, '"positions.close_all"'),
    ("E33.json", 423, '"E33-D05"'),
    ("E33.json", 602, '"E33-Q05"'),
)


def cite_findings(docs: dict[str, str], fetch: Fetch) -> tuple[list[Finding], int]:
    fails: list[Finding] = []
    done: set[tuple[str, int]] = set()

    def lines_of(rev: str, rel: str) -> list[str] | None:
        t = fetch(rev, rel)
        return None if t is None else t.split("\n")

    for doc, text in docs.items():
        lines = text.split("\n")
        fence = fenced(lines)
        for li, line in enumerate(lines, 1):
            if fence[li - 1] or MUT_ROW.match(line):
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
    for cid, n, frag in CITED:
        rel = cite_path(cid)
        base = lines_of(BASE, rel) if rel else None
        if base is None or n > len(base) or frag not in strip_comments(base[n - 1]):
            hits = [i + 1 for i, ln in enumerate(base or []) if frag in ln]
            msg = f'`{cid}`:{n} "{frag[:40]}" not on the line (found {hits[:4]})'
            fails.append(("G-CITE", msg, None, None))
    return fails, len(done) + len(CITED)


# ---------------------------------------------------------------------------- the texts


@dataclass(frozen=True)
class Texts:
    spec: str
    plans: tuple[tuple[str, str], ...]  # the working-tree untouched files (G-UNTOUCHED)
    values: Values
    extra_files: tuple[str, ...] = ()  # files named for this ticket beside the spec (BQ-34)
    fork: str | None = "merge-base"  # the merge-base sha, or None when it does not resolve
    head_texts: tuple[tuple[str, str | None], ...] = ()  # each pinned input at origin/main
    staged: tuple[str, ...] = ()  # untouched ids whose index differs from the merge-base


@functools.lru_cache(maxsize=64)
def lex_cached(doc: str, text: str) -> tuple[LexUnit, ...]:
    return tuple(lex_units(doc, text))


def lex(t: Texts) -> list[LexUnit]:
    return list(lex_cached("spec", t.spec))


def docs_of(t: Texts) -> dict[str, str]:
    return {"spec": t.spec}


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


def line_of(t: Texts, prefix: str) -> str:
    return next((ln for ln in t.spec.split("\n") if ln.startswith(prefix)), "")


# ---------------------------------------------------------------------------- lexicon gates

# Each ruled behaviour is carried by a synonym set plus a need-check on the ruled sentence's own
# words; the pins stay the backstop. A gap that may not hold a negation is written NOGAP, so
# "never cancels a run" never reads as the claim.
NOGAP = r"(?:(?!(?:no|never|not|nor|nothing|none|without|cannot)\b)\S+ )"
SPEAK = (
    r"(?:announc\w*|spoken|speaks?|spoke|voiced|voices?|read aloud|read out|reads? out|says?"
    r"|said|narrated|politely|assertively|interrupts?)"
)
PENDING_TERM = (
    r"\b(?:bq 16|bq 17|routing table|assertive set|the fold|child fill fold)\b"
    rf" {NOGAP}{{0,4}}?(?:is |was |are )?(?:ruled|confirmed|approved|settled|final|adopted"
    r"|binding|in force|decided|agreed|locked)\b"
)
AGG_TERM = (
    r"\b(?:each|every|per) (?:algo )?(?:child(?:'s)? )?(?:fill|child order fill|child fill)s?"
    rf" {NOGAP}{{0,3}}?{SPEAK}\b"
    rf"|\bchild fills? {NOGAP}{{0,2}}?(?:are |is )?(?:announced|spoken) {NOGAP}{{0,2}}?"
    r"(?:assertively|individually|one by one|separately|each)\b"
    rf"|\b(?:events|fills|failures) of one class {NOGAP}{{0,4}}?(?:speak|are announced)"
    r" (?:separately|one by one|individually|each)\b"
    r"|\bclasses (?:may |can |do )?merge\b"
)
THROTTLE_TERM = (
    rf"\bprogress {NOGAP}{{0,4}}?(?:every|each|once per|at most once per|at most every) [12] s\b"
    rf"|\bprogress {NOGAP}{{0,3}}?(?:per|on each|on every) (?:tick|sample|refresh|slice|update)\b"
    rf"|\b(?:each|every) refresh {NOGAP}{{0,3}}?{SPEAK}\b"
    rf"|\bnext slice countdown {NOGAP}{{0,3}}?(?:speaks|is announced|announces)\b(?! nothing)"
)
CASE1_TERM = (
    r"\bcase 1(?:'s)? (?:in panel )?line"
    rf" {NOGAP}{{0,3}}?(?:speaks?|announc\w*|is spoken|is heard|is polite)\b"
    r"(?! nothing| never| no\b)"
    rf"|\bcase 1(?:'s)? (?:in panel )?line {NOGAP}{{0,3}}?(?:is |stays |keeps )(?:a )?"
    r'role="status"'
)
NOTE_TERM = (
    r"\b(?:residual(?: risk)? note|the note) "
    rf"{NOGAP}{{0,4}}?(?:is |as |takes |keeps )(?:an? )?role=\"alert\""
    rf"|\b(?:residual(?: risk)? note|the note) {NOGAP}{{0,3}}?(?:is |gets |will be )?"
    r"(?:announced|spoken|dismissed|hidden|removed|cleared|auto dismissed)\b"
    r"(?! once acknowledged)"
)
PEG_TERM = (
    r"\b(?:a|the|third|with a|offers? a) mid (?:option|radio|peg|choice)\b"
    r"|\bmid (?:is (?:a|an|the third) (?:option|radio|choice))\b"
    rf"|\bpeg {NOGAP}{{0,3}}?to (?:the )?mid\b"
)
AUTOCANCEL_TERM = (
    rf"\bauto ?cancel {NOGAP}{{0,4}}?(?:applies|runs|stays on|is kept|is on|remains on"
    r"|still runs|counts down)\b"
    rf"|\b(?:an? |the )?(?:extend|extension|more time|add time) {NOGAP}{{0,3}}?"
    r"(?:control|button|option)\b"
)
RENDER_TERM = (
    r"\b(?:protanopia|tritanopia|d03) renders? (?:\(\S+\) )?"
    r"(?:exists?|were run|was run|were made|was made|are attached|are committed|is attached)\b"
)
TRITAN_TERM = (
    rf"\bd04(?:'s)? (?:\S+ )?tritan\w* (?:figures|minima) {NOGAP}{{0,3}}?(?:stand|hold|are current"
    r"|are correct|are valid|are kept|kept|remain|still apply|apply)\b"
)
LEAK_TERM = (
    rf"\b(?:names?|descriptions?|announcements?|rows?|strings?|the tree) {NOGAP}{{0,3}}?"
    r"(?:may|can|does|will|should) (?:\S+ ){0,2}?(?:name|show|expose|reveal|include|hold|carry)s?"
    r" (?:\S+ ){0,2}?(?:another|the other|other) (?:user|users|user's|account)\b"
)
RETURN_TERM = (
    rf"\bfocus {NOGAP}{{0,2}}?(?:returns?|goes back|lands?|moves) (?:\S+ ){{0,2}}?(?:to|on) "
    r"the panel header\b(?! only| when no| if no)"
)
ESC_TERM = (
    rf"\besc(?:ape)? {NOGAP}{{0,3}}?(?:cancels?|stops?|ends?|kills?|halts?|aborts?)"
    r" (?:the |a |every |its )?(?:\S+ )?(?:run|algo|algos|runs)\b"
)
KEY_PROPOSE_TERM = (
    r"\b(?:this review |we |the review )?(?:proposes?|adds?|introduces?|registers?)"
    r" (?:a |an |the )?(?:new )?global (?:key|chord|shortcut|binding|hotkey)s?\b"
)
POSITIONS_TERM = (
    r"\b(?:ctrl\+w|ctrl\+shift\+w|positions keys|positions context|the three keys)"
    rf" {NOGAP}{{0,4}}?(?:are |is )?(?:excluded|removed|unbound|disabled|scoped away|turned off"
    r"|dead) (?:on|from|in) the algos tab\b"
)
AT_NAMES = r"\b(?:nvda|jaws|voiceover|voice over|narrator|talkback|orca)\b"
AT_RUN_TERM = (
    r"\b(?:tested|verified|checked|confirmed|heard|listened|ran|run|was run|were run|walked"
    r"|observed|recorded|captured)"
    r" (?:\S+ ){0,2}?(?:with|on|using|under|in) (?:a |the |two |both )?screen ?readers?\b"
    r"|\bscreen ?readers? (?:read|reads|said|says|announc\w*|spoke|speaks|voiced|confirmed"
    r"|verified|checked|showed|reported|agreed|rendered)\b"
)
HCBAR_TERM = (
    r"\b(?:every|all|each|any) (?:\S+ ){0,2}?(?:pairs?|texts?|labels?|buttons?|confirms?)"
    r" (?:\S+ ){0,3}?(?:pass\w*|meets?|clears?|holds?) (?:\S+ ){0,5}?high contrast\b"
    r"|\bhigh contrast (?:text )?(?:bar|threshold|minimum) (?:is|of|at) 4\.5\b"
    r"|\bdanger (?:buttons?|confirms?) (?:\S+ ){0,3}?(?:pass|passes|are passes|is a pass)\b"
)
NODRAW_TERM = (
    r"\b(?:redrawn|redraws?|redrawing|drawn anew|drawn again|drawn in penpot"
    r"|new penpot (?:page|board)s?|verdict boards?|sketch(?:es|ed)?|mock ?ups?"
    r"|(?:fresh|additional|extra|added|new) (?:penpot |annotation )?(?:boards?|frames?|drawings?"
    r"|sheets?))\b"
)
NODRAW_IF = r"\b(?:should|unless|if) the owner\b|\balternative\b|\bq 03\b"
HANDOFF_TERM = (
    r"\bhand ?off (?:file|document|pack file|markdown)s?\b|\be33 d05 handoff\.md\b"
    r"|\bhand ?off carries\b|\bcompanion hand ?off\b"
)
CLOSE_RULE_TERM = (
    r"\b(?:fixed|corrected|repaired|amended|edited|patched|updated|changed) in (?:the )?"
    r"(?:designs?|design file|merged (?:spec|text|design)\w*|penpot file|figma file)\b"
    r"|\bmarks? (?:it|the finding|a finding|them) (?:as )?(?:done|closed|resolved|fixed)\b"
    r"|\bcloses? (?:once|when|after) (?:\S+ ){0,3}?(?:fixe[sd]|edits?|redraws?|patch\w*)\b"
)
SIGNOFF_TERM = (
    r"\b(?:a11y lead|accessibility lead|accessibility specialist|cdo|design lead)(?:'s|s)?"
    r" (?:\S+ ){0,3}?(?:signed|approved|sign(?:ed)? off|countersigned|endorsed|accepted|reviewed"
    r" it|cleared|ratified)\b"
    r"|\bsigned off by (?:the )?(?:a11y lead|accessibility lead|cdo)\b"
    r"|\bowner's approved (?:is |was |has been )?(?:taken|assumed|granted|given|obtained"
    r"|received|recorded as given)\b"
    r"|\bthe owner (?:has )?(?:approved|signed off|endorsed)\b"
)
EDIT_TERM = (
    r"\b(?:edits?|rewrites?|patch(?:es)?|modif(?:y|ies)|changes?) (?:the |a |any )?merged"
    r" (?:text|spec|design|file)s?\b"
)
EXCEPTION_TERM = (
    r"\bessential exception (?:\S+ ){0,3}?(?:covers|applies to (?:the )?(?:targets?|rows?|"
    r"checkbox\w*|buttons?)|is used for|exempts (?:the )?(?:targets?|rows?))\b"
)
COLOUR_ONLY = (
    r"\b(?:by|through|via|with) (?:its |the )?(?:colou?r|fill|hue|tint) (?:alone|only)\b"
    r"|\b(?:most|some|many|nearly all|almost all) (?:\S+ ){0,1}?(?:colou?r carrying )?signals\b"
    r"|\brests? on (?:its |their |the |a )?(?:fill|colou?r|hue|tint)s? (?:alone|only)\b"
)
ASSERTIVE_EVENTS = (
    r"\b(?:a halt|halts|halted by risk control|failed run|double fill|rejected slice"
    r"|double refusal|account going down|untracked lockout|failed start|t4 refusal)\b"
)
POLITE_EVENTS = r"\b(?:progress|completion|the filter result|behind plan|the bulk result)\b"
TO_POLITE = r"\b(?:politely|polite region|in the polite|is polite|are polite|stays? polite)\b"
TO_ASSERTIVE = (
    r"\b(?:assertively|assertive region|in the assertive|is assertive|are assertive"
    r"|interrupts?|interrupting)\b"
)


def g_route_prose(t: Texts) -> list[Finding]:
    """BQ-16 in prose (cells read too): an assertive class read as polite, or the converse."""
    bad: list[Finding] = []
    for u in lex(t):
        for c in clauses(u.text):
            n = norm_text(unquote(c))
            if re.search(r"\b(?:would|alternative|q 01|q 02)\b", n):
                continue
            for ev, to_, what in (
                (ASSERTIVE_EVENTS, TO_POLITE, "an assertive class read as polite"),
                (POLITE_EVENTS, TO_ASSERTIVE, "a polite class read as assertive"),
            ):
                if re.search(ev, n) and live(c, to_):
                    bad.append(F("G-ROUTE", f"{what}: {n[:70]!r}", u.doc, u.sec))
    return bad


def g_pending(t: Texts) -> list[Finding]:
    """BQ-16, BQ-17: PROPOSED, owner approval pending (#2701), in their headings and the RULED
    paragraph; nothing reads them as ruled."""
    bad = lexicon("G-PENDING", "BQ-16 / BQ-17 read as ruled", PENDING_TERM)(t)
    for prefix, sec in (("### 8.1 ", "8.1"), ("### 8.2 ", "8.2")):
        if PENDING not in line_of(t, prefix):
            bad.append(
                F("G-PENDING", f"§{sec}'s heading lacks the PROPOSED marker", "spec", at(t, sec))
            )
    ruled = norm_text(spec_sec(t, RULED_HEAD))
    marker = norm_text(PENDING)
    if "bq 17 (algo child fills" not in ruled or f"are {marker}" not in ruled:
        bad.append(
            F(
                "G-PENDING",
                "the RULED paragraph lost BQ-16 / BQ-17's marker",
                "spec",
                at(t, RULED_HEAD),
            )
        )
    return bad


def g_agg(t: Texts) -> list[Finding]:
    """BQ-17 (PROPOSED): child fills fold into the run's polite summary; one class, one sample,
    one sentence; it narrows `05`:148."""
    bad = lexicon("G-AGG", "child fills or a class burst spoken one by one", AGG_TERM)(t)
    return bad + need(
        t,
        "G-AGG",
        AGG_HEAD,
        (
            'is not 05\'s "order filled"',
            "folded into the run's state and announced through the run's polite summary",
            "speak as one sentence with a count and the ids",
            "different classes never merge",
            'narrows 05:148\'s "never throttled/coalesced"',
            "one announcer per surface",
        ),
    )


def g_throttle(t: Texts) -> list[Finding]:
    """AC4, BQ-18: progress at most once per 5 s, latest only; the countdown speaks nothing."""
    lane = base_value("TIME:lane")
    bad = lexicon("G-THROTTLE", "progress faster than the lane", THROTTLE_TERM)(t)
    return bad + need(
        t,
        "G-THROTTLE",
        THROTTLE_HEAD,
        (
            f"progress speaks at most once per {lane} s, the latest value only, politely",
            "the monitor beneath is inert",
            "the next slice countdown speaks nothing anywhere",
            "the focused scr 070 row only",
        ),
    )


def g_degraded(t: Texts) -> list[Finding]:
    """BQ-19 (confirmed): case 1 is CMP-028 `live="off"`; SCR-152 speaks once; C-04."""
    bad = lexicon("G-DEGRADED", "the case-1 line speaks", CASE1_TERM)(t)
    return bad + need(
        t,
        "G-DEGRADED",
        DEGRADED_HEAD,
        (
            "cannot be both a status and silent on insertion",
            'cmp 028 live="off" text',
            "so scr 152 speaks once",
            "(c 04; a 04)",
            'is the catalogue\'s banner: role="status"',
            "account down is its outcome line, assertive once per account",
        ),
    )


def g_note(t: Texts) -> list[Finding]:
    """BQ-15 (confirmed): the OCO note is `role="note"` until acknowledged; C-02, C-03."""
    bad = lexicon("G-NOTE", "the residual note announced, alerted or cleared", NOTE_TERM)(t)
    return bad + need(
        t,
        "G-NOTE",
        NOTE_HEAD,
        (
            'the note is role="note" with cmp 028 live="off"',
            "kept until acknowledged",
            "stays reachable as the oco row's detail",
            "never the note",
            "(c 02, c 03; a 03, a 05)",
        ),
    )


def g_peg(t: Texts) -> list[Finding]:
    """BQ-13 (confirmed): maker / taker / offset; "mid" an absence; `14`:1584 a C row."""
    bad = lexicon("G-PEG", "a mid peg offered", PEG_TERM)(t)
    return bad + need(
        t,
        "G-PEG",
        PEG_HEAD,
        (
            "ruled maker / taker / offset set",
            '"mid" is an absence',
            '14:1584\'s "best bid / best ask / mid" is a c row (c 01; a 02)',
        ),
    )


def g_time(t: Texts) -> list[Finding]:
    """BQ-24 (confirmed): no auto-cancel on an algo start; C-10; WCAG 2.2.1's Essential."""
    bad = lexicon("G-TIME", "the auto-cancel kept, or an extend control", AUTOCANCEL_TERM)(t)
    return bad + need(
        t,
        "G-TIME",
        TIME_HEAD,
        (
            f"{base_value('TIME:autocancel')} s auto cancel is off for every algo start",
            "is c 10 and f 08",
            "wcag 2.2.1's essential exception as e09 d06 merged it",
            "limits nothing the user must do in time",
            "countdowns are not time limits",
        ),
    )


def g_hcbar(t: Texts) -> list[Finding]:
    """BQ-27 (confirmed): 7:1 for high-contrast text; a pair below it is an F row to E05."""
    bad = lexicon("G-HCBAR", "high contrast read at the AA bar", HCBAR_TERM)(t)
    listed = set()
    for r in table(spec_sec(t, CONTRAST_HEAD)):
        toks = re.findall(r"`(color\.[^`]+)`", r[0]) if r else []
        if len(toks) == 2:
            listed.add((toks[0], toks[1]))
    want = {(p.fg, p.bg) for p in hc_under()}
    if listed != want:
        msg = f"§10's high-contrast table differs: missing {sorted(want - listed)}"
        bad.append(F("G-HCBAR", msg, "spec", at(t, CONTRAST_HEAD)))
    return bad + need(
        t,
        "G-HCBAR",
        CONTRAST_HEAD,
        (
            f"{base_value('BAR:hc')}:1 for text in high contrast",
            "each an f row to the token owner (e05), never a pass",
            "the bar is applied to all text in high contrast, button labels included",
        ),
    )


def g_at(t: Texts) -> list[Finding]:
    bad = [
        F("G-AT", f"an assistive technology named: {h[0]!r}", h[1], h[2])
        for h in claims(lex(t), AT_NAMES)
    ]
    bad += lexicon("G-AT", "a screen-reader run claimed", AT_RUN_TERM)(t)
    return bad + need(t, "G-AT", "0. Status", ("nothing was run on a screen reader",))


def g_nodraw(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for u in lex(t):
        for c in clauses(u.text):
            if re.search(NODRAW_IF, norm_text(c)):
                continue
            if live(c, NODRAW_TERM):
                bad.append(F("G-NODRAW", f"a new drawing: {norm_text(c)[:70]!r}", u.doc, u.sec))
    return bad + need(t, "G-NODRAW", "0. Status", ("no new boards, no new penpot page",))


def other_d05_files() -> list[str]:
    """Any file in the spec's folder named for this ticket other than the spec itself."""
    folder = ROOT / Path(SPEC_REL).parent
    spec_name = Path(SPEC_REL).name
    return sorted(
        p.name
        for p in folder.glob("*")
        if p.is_file() and re.search(r"(?i)e33.?d05", p.name) and p.name != spec_name
    )


def g_nohandoff(t: Texts) -> list[Finding]:
    bad = lexicon("G-NOHANDOFF", "a hand-off file", HANDOFF_TERM)(t)
    if "no handoff.md" not in norm_text(spec_sec(t, HANDOFF_HEAD)):
        bad.append(F("G-NOHANDOFF", "§18.2 lost 'No `-handoff.md`'", "spec", at(t, HANDOFF_HEAD)))
    if t.extra_files:
        bad.append(F("G-NOHANDOFF", f"{t.extra_files} exist against RULED BQ-34", None, None))
    return bad


def g_close_rule(t: Texts) -> list[Finding]:
    bad = lexicon("G-CLOSE-RULE", "closing by an edit of the designs", CLOSE_RULE_TERM)(t)
    n = norm_text(line_of(t, "- **R-2"))
    for w in (
        "one owner (a spec and its area, never an agent)",
        "a finding closes when it is routed",
        "one target",
        "a close state",
        "routed",
        "accepted with a written rationale",
        "owner's approved",
    ):
        if w not in n:
            bad.append(F("G-CLOSE-RULE", f"R-2 lacks {w!r}", "spec", "1. Purpose, method,"))
    return bad


def g_signoff(t: Texts) -> list[Finding]:
    bad = lexicon("G-SIGNOFF", "a sign-off claimed", SIGNOFF_TERM)(t)
    n = norm_text(spec_sec(t, DOD_HEAD))
    for w in (
        "standing arrangement's design approval plus the qa record",
        "pending the owner's approved on #2701",
        "walkthrough is posted on #989",
    ):
        if w not in n:
            bad.append(F("G-SIGNOFF", f"§18.1 lacks {w!r}", "spec", at(t, DOD_HEAD)))
    if "nothing here claims the owner's approved" not in norm_text(line_of(t, "**Ticket:**")):
        bad.append(F("G-SIGNOFF", "the status line lost its no-approval claim", "spec", "(top)"))
    return bad


def g_close(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for doc, text in docs_of(t).items():
        for i, line in enumerate(text.split("\n"), 1):
            if CLOSING.search(strip_comments(line)):
                msg = f"{doc}:{i} a closing keyword before an issue number"
                bad.append(F("G-CLOSE", msg, doc, h2_at(text, i)))
    return bad


SCRIPT_OK = frozenset("Δ")  # the one letter outside the Latin script (ΔE76, ΔL*)
ELLIPSIS = "…"


def g_charset(t: Texts) -> list[Finding]:
    """A CR, trailing whitespace, a char NFKC changes (`…` only inside a quote or a code span), a
    format char or a non-Latin letter outside a code span (a homoglyph)."""
    bad: list[Finding] = []
    for doc, text in docs_of(t).items():
        if "\r" in text:
            bad.append(F("G-CHARSET", f"{doc} holds a CR", doc, None))
        for i, line in enumerate(text.split("\n"), 1):
            sec = h2_at(text, i)
            if line != line.rstrip():
                bad.append(F("G-CHARSET", f"{doc}:{i} trailing whitespace", doc, sec))
            outside = CODE.sub(" ", line)
            bare = QUOTED.sub(" ", outside)
            for ch in sorted(set(line)):
                cat = unicodedata.category(ch)
                if ch == ELLIPSIS:
                    if ch in bare:
                        bad.append(
                            F("G-CHARSET", f"{doc}:{i} an ellipsis outside a quote", doc, sec)
                        )
                    continue
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
    """Every table row has its header's cell count, split on unescaped pipes only (an unescaped
    `|` inside a cell, code spans included, adds a cell GFM drops)."""
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
            if pat.search(line) and not MUT_ROW.match(line):
                msg = f"{doc}:{i} an unmerged text is cited by line"
                bad.append(F("G-UNMERGED", msg, doc, h2_at(text, i)))
    for name in UNMERGED[:3]:
        epic = name.split("-")[0]
        if git_show(BASE, f"docs/design/{epic}/{name}.md") is not None:
            bad.append(F("G-UNMERGED", f"{name} is merged at the base: re-read it", None, None))
    return bad


def g_keypropose(t: Texts) -> list[Finding]:
    """BQ-23: no new global key; the Positions keys stay live on the Algos tab (C-11)."""
    bad = lexicon("G-KEYS", "a new global key proposed", KEY_PROPOSE_TERM)(t)
    bad += lexicon("G-KEYS", "the Positions keys removed from the Algos tab", POSITIONS_TERM)(t)
    return bad + need(t, "G-KEYS", KEY_HEAD, ("no new global key is proposed on the five screens",))


def g_leak_prose(t: Texts) -> list[Finding]:
    """T Sec, F-01 (ruled Major): no name, description or announcement may name another user."""
    bad = lexicon("G-LEAK", "a name that may disclose another user", LEAK_TERM)(t)
    return bad + need(
        t,
        "G-LEAK",
        LEAK_HEAD,
        (
            "the leak (f 01, major)",
            "e09 d09's reason grammar, applied by analogy, forbids",
            "the view as key, e09 d09:95",
            "no row level name or description lists actions",
            "follows d03's close; #988's owner is told at merge",
            'where the row shows "another user" (d03:194, :241)',
            "c 12.4 scopes server side",
            'the close state is "the row shows the role visible label only"',
            "live region strings follow the same rule as names",
        ),
    )


ESC_CELL = (
    r"\b(?:cancels?|stops?|ends?|kills?|halts?|aborts?) (?:the |a |every |its )?(?:\S+ )?"
    r"(?:run|algo|runs)\b"
)


def g_esc(t: Texts) -> list[Finding]:
    """`Esc` closes and never cancels a run (D02:331; D03:264)."""
    bad = lexicon("G-ESC", "Esc cancels a run", ESC_TERM)(t)
    for r in table(spec_sec(t, FOCUS_HEAD)):
        if len(r) == 8 and live(r[5], ESC_CELL):
            bad.append(F("G-ESC", f"{r[0]}'s Esc cell cancels a run", "spec", at(t, FOCUS_HEAD)))
    k06 = rows_by(spec_sec(t, KEY_HEAD)).get("K-06", [])
    if len(k06) < 3 or "never cancel a run" not in norm_text(k06[2]):
        bad.append(F("G-ESC", "K-06 lost 'never cancel a run'", "spec", at(t, KEY_HEAD)))
    return bad


def g_return_prose(t: Texts) -> list[Finding]:
    """F-02: `05`:97 binds the trigger; focus never returns to the panel header as the rule."""
    return lexicon("G-FOCUS", "focus returns to the panel header", RETURN_TERM)(t)


def g_tritan(t: Texts) -> list[Finding]:
    """The ruling: #988's tritan figures predating #4652 are a G row to #988's owner (G-16),
    re-derived and named as superseded."""
    bad = lexicon("G-TRITAN", "D04's tritan figures read as current", TRITAN_TERM)(t)
    g16 = line_of(t, "- **G-16**")
    if "d04's tritan minima superseded (g 16)" not in norm_text(line_of(t, "5. AC3:")):
        bad.append(F("G-TRITAN", "§19 lost the superseded tritan minima", "spec", "19. Summary"))
    for w in ("D04:213", "#4652", "E33-D04's owner (#988)", "supersedes"):
        if w not in g16:
            bad.append(F("G-TRITAN", f"G-16 lacks {w!r}", "spec", at(t, G_HEAD)))
    return bad + need(
        t,
        "G-TRITAN",
        CVD_HEAD,
        (
            "its tritanopia minima are superseded by this review's",
            "g 16 to #988's owner",
            "they are not superseded",
        ),
    )


def g_target(t: Texts) -> list[Finding]:
    """BQ-28: no essential exception; widths never assumed."""
    bad = lexicon("G-TARGET", "the essential exception used", EXCEPTION_TERM)(t)
    return (
        bad
        + need(
            t,
            "G-TARGET",
            TARGET_HEAD,
            (
                "no essential exception is used",
                "are g 12's, never assumed",
                "cmp 008's steppers are cmp 002 ghost buttons",
                "every other control d02 and d03 draw without a width",
            ),
        )
        + (
            [
                F(
                    "G-TARGET",
                    "G-12 lists the steppers, whose width 15:64 states",
                    "spec",
                    at(t, G_HEAD),
                )
            ]
            if "stepper" in line_of(t, "- **G-12**")
            else []
        )
    )


CAVEAT_TERM = (
    r"\b(?:shown|rendered|placed|put|lives?|sits?|appears?|hidden|moved|kept|is|as) (?:\S+ ){0,2}?"
    r"(?:as |in |behind |inside )(?:a |the )?(?:tooltip|hover card|popover)s?\b"
    r"|\bcaveat (?:\S+ ){0,3}?(?:on|by) hover\b"
)


def g_caveat(t: Texts) -> list[Finding]:
    """RULED BQ-11: the caveat is a paragraph, never a tooltip, read before the fields."""
    bad = lexicon(
        "G-CAVEAT", "the caveat moved behind a hover", CAVEAT_TERM, r"\bcaveat|\bregion 2"
    )(t)
    return bad + need(
        t,
        "G-CAVEAT",
        CAVEAT_HEAD,
        ("region 2, type.ui.body, never a tooltip", "the lead caveat is the first body block"),
    )


OBSCURE_TERM = (
    rf"\b(?:footer|header|selection bar|bar|banner)s? {NOGAP}{{0,2}}?(?:covers?|cover|hides?|hide"
    r"|obscures?|obscure|overlaps?|overlap|sits? over|sit over) (?:a |the |any )?focused\b"
    r"|\bfocused (?:control|row) (?:\S+ ){0,2}?(?:sits?|stays?|goes|scrolls)"
    r" (?:under|beneath|behind)"
    r" (?:a |the )?(?:sticky )?(?:footer|header|bar)\b(?! never)"
)


def g_obscured(t: Texts) -> list[Finding]:
    """RULED BQ-31 (PROPOSED, F-10): a focused control is never under a sticky bar."""
    bad = lexicon("G-OBSCURED", "a sticky bar may cover focus", OBSCURE_TERM)(t)
    return bad + need(
        t,
        "G-OBSCURED",
        OBSCURED_HEAD,
        (
            "the builders' scrolling body keeps a focused control clear of the",
            "scr 070's grid keeps a focused row clear of its sticky header",
        ),
    )


NUM_WORDS = (
    r"(?:none|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen"
    r"|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
)
WORD_COUNT = re.compile(
    rf"\b{NUM_WORDS} (?:surfaces?|non compliant|findings?|clauses?|frames?|pairs?|renders?"
    r"|signals?|carriers?|treatments?|f rows?|mutations?)\b"
)


def g_wordcount(t: Texts) -> list[Finding]:
    """A count written as a word escapes G-ANCHOR (lens 2): every measured count is a figure."""
    bad: list[Finding] = []
    for u in lex(t):
        for m in WORD_COUNT.finditer(norm_text(unquote(u.text))):
            bad.append(F("G-WORDCOUNT", f"a count written as a word: {m[0]!r}", u.doc, u.sec))
    return bad


def g_untouched_prose(t: Texts) -> list[Finding]:
    bad = lexicon("G-UNTOUCHED", "a merged text edited", EDIT_TERM)(t)
    return bad + need(t, "G-UNTOUCHED", "1.1 What this", ("it edits no merged text",))


LEXICON_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_charset,
    g_cells,
    g_close,
    g_at,
    g_route_prose,
    g_pending,
    g_agg,
    g_throttle,
    g_degraded,
    g_note,
    g_peg,
    g_time,
    g_hcbar,
    g_nodraw,
    g_nohandoff,
    g_close_rule,
    g_signoff,
    g_unmerged,
    g_keypropose,
    g_leak_prose,
    g_esc,
    g_return_prose,
    g_tritan,
    g_target,
    g_caveat,
    g_obscured,
    g_wordcount,
    g_untouched_prose,
)

# ---------------------------------------------------------------------------- table gates

ID_CELL = re.compile(r"\b(?:F|C|G|Q|A|H|K|N|CR|RT|L|SR|AL)-\d\d\b")


def defined_ids(t: Texts) -> set[str]:
    out: set[str] = set()
    for ln in t.spec.split("\n"):
        m = re.match(r"^\| ((?:F|C|A|K|N|CR|RT|L|SR|AL)-\d\d) \|", ln)
        if m:
            out.add(m[1])
        m2 = re.match(r"^- \*\*((?:G|Q|H)-\d\d)", ln)
        if m2:
            out.add(m2[1])
    return out


def expand_ids(cell: str) -> list[str]:
    """Ids named in a cell, ranges expanded ("N-01..N-17", "K-02..K-05")."""
    out: list[str] = []
    for p, a, b in re.findall(
        r"\b(F|C|G|Q|A|H|K|N|CR|RT|L|SR|AL)-(\d\d)(?:\.\.\1-(\d\d))?\b", cell
    ):
        lo, hi = int(a), int(b or a)
        out += [f"{p}-{n:02d}" for n in range(lo, hi + 1)]
    return out


def f_ids(cell: str) -> list[str]:
    return [x for x in expand_ids(cell) if x.startswith("F-")]


# clauses whose verdict a ruled reading fixes: (verdict, words its row must carry)
CLAUSE_RULED: dict[str, tuple[str, ...]] = {
    "T Sec": ("at risk", "F-01", 'another user\'s run reads "another user"'),
    "3.1.2": ("compliant", "C-11", "G-08", "`KM`:657"),  # lens 3 m2: view-local keys
    "6.3": (
        "at risk",
        "G-19",
        "interim path",
    ),  # lens 3 M1: sort and row detail  # the ruling: the name leak, a Major F row
    "3.4.4": ("at risk", "F-02"),  # the ruling: focus return is an F row
    "5.6": ("at risk", "F-11", "F-12"),  # RULED BQ-27: the danger confirms
    "6.2a": ("at risk", "F-04"),  # RULED BQ-18: the header total
    "6.2b": ("at risk", "C-07", "C-08", "interim path"),  # BQ-16, BQ-17 PROPOSED
    "6.2d": ("at risk", "F-05"),  # RULED BQ-19: the case-1 line
    "7.4": ("at risk", "F-09", "H21"),  # BQ-30: the dialogs, FO H21 open (D04-Q2)
    "3.1.4": ("at risk", "F-08", "interim path"),  # RULED BQ-24: the auto-cancel
    "3.3.1": ("at risk", "C-11", "interim path"),  # the ruling: the keys stay live
    "3.4.7": ("at risk", "G-12", "interim path"),  # BQ-28: widths unstated
    "5.5": ("at risk", "interim path"),  # D04's DR-1 / DR-2 move the track
}


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
            msg = f"{cid} at risk with no Major F row or interim path"
            bad.append(F("G-CLAUSE", msg, "spec", sec))
        if verdict == "compliant" and ({"Major", "Blocking"} & set(sevs)):
            msg = f"{cid} compliant with a Major or Blocking F row"
            bad.append(F("G-CLAUSE", msg, "spec", sec))
        rule = CLAUSE_RULED.get(cid)
        if rule and not (verdict == rule[0] and all(w in where + " " + fnd for w in rule[1:])):
            bad.append(F("G-CLAUSE", f"{cid} must read {rule}", "spec", sec))
    if "`out of scope — <epic>`" not in line_of(t, "- **R-3"):
        bad.append(F("G-CLAUSE", "R-3 lost the <epic> verdict word", "spec", "1. Purpose, method,"))
    return bad + need(
        t, "G-CLAUSE", CLAUSE_HEAD, ("one row per clause across the five screens (deviation d4)",)
    )


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
        if not VERDICT.match(r[2]):
            bad.append(F("G-SC", f"{r[0]} verdict {r[2]!r}", "spec", sec))
    return bad


# RULED BQ-9 (as proposed) with the ruling's F-02: one row per surface, its initial focus
FOCUS_RULED: dict[str, tuple[int, str]] = {
    "SCR-066..SCR-068, configured": (2, "the first strategy field, never Start"),
    "the running view": (2, "the state label's heading (PROPOSED; G-02)"),
    "SCR-076, cited": (2, "Cancel"),
    'the CMP-044 confirms ("Cancel…", "Cancel and flatten…", "Pause all…", "Cancel all…")': (
        6,
        "the trigger's row and cell, else the next row, else the header (PROPOSED; F-02)",
    ),
    "SCR-070, the panel": (
        4,
        "the header controls → the filter bar → the grid (one stop) → the footer",
    ),
}
FOCUS_ROWS = (
    "SCR-066..SCR-068, configured",
    "the running view",
    "SCR-069, OCO half",
    "SCR-076, cited",
    'the CMP-044 confirms ("Cancel…", "Cancel and flatten…", "Pause all…", "Cancel all…")',
    "the adopt step-up (SCR-006, cited)",
    "SCR-070, the panel",
    "SCR-063's Algos tab",
)


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
        if (modal == "yes") != (trap == "yes"):
            bad.append(F("G-FOCUS", f"{s} modal {modal!r} with trap {trap!r}", "spec", sec))
        if modal == "yes" and back in ("", "—"):
            bad.append(F("G-FOCUS", f"{s} names no focus return", "spec", sec))
        if not CITE_GROUP.search(src):
            bad.append(F("G-FOCUS", f"{s} carries no source cite", "spec", sec))
        rule = FOCUS_RULED.get(s)
        if rule and r[rule[0]] != rule[1]:
            bad.append(F("G-FOCUS", f"{s} cell {rule[0]} must be {rule[1]!r}", "spec", sec))
    traps = sum(1 for r in rows.values() if len(r) == 8 and r[3] == "yes")
    bad += need(t, "G-FOCUS", FOCUS_HEAD, (f"{traps} surfaces trap focus",))
    return bad + need(
        t, "G-FOCUS", MONITOR_HEAD, ("tab leaves it, so the 100 row table is escapable",)
    )


SEVERITY_ROW = re.compile(r"^(?:Blocking|Major|Minor|Info)$")


def g_frow(t: Texts) -> list[Finding]:
    sec = at(t, FINDING_HEAD)
    rows = table(spec_sec(t, FINDING_HEAD))
    clause_rows = {r[0].strip("`"): r for r in table(spec_sec(t, CLAUSE_HEAD)) if r}
    bad: list[Finding] = []
    for r in rows:
        if len(r) != 9 or any(not c.strip() or c == "—" for c in r):
            bad.append(F("G-FROW", f"{r[0]} must have nine filled cells", "spec", sec))
            continue
        fid, sev, cl, _spec, ev, _rep, _owner, target, _close = r
        if not SEVERITY_ROW.match(sev):
            bad.append(F("G-FROW", f"{fid} severity {sev!r}", "spec", sec))
        c = cl.strip("`")
        if c not in clause_rows or fid not in f_ids(clause_rows[c][4]):
            bad.append(F("G-FROW", f"{fid} is not listed on clause {c}'s row", "spec", sec))
        if not CITE_GROUP.search(ev):
            bad.append(F("G-FROW", f"{fid} evidence carries no file:line", "spec", sec))
        if not re.search(r"#\d+|E05 tokens", target):
            bad.append(F("G-FROW", f"{fid} target names no issue", "spec", sec))
    r1 = norm_text(line_of(t, "- **R-1"))
    for w in (
        "non compliant with no compliant path",
        "a status carried by colour alone",
        "an announcement with no string or politeness",
        "a name that discloses what a role may not see",
        "not used for design findings",
    ):
        if w not in r1:
            bad.append(F("G-FROW", f"R-1 lost {w!r}", "spec", "1. Purpose, method,"))
    return bad


AGENT = re.compile(
    r"\b(?:agents?|workers?|hcl|hpe|bots?|claude|orchestrator|sessions?|lane \d|assistant)\b"
)


OWNER_FORM = re.compile(
    r"^E33-D0\d's (?:spec|hand-off H03) \(`area/[a-z-]+`\)$"
    r"|^the area `area/[a-z-]+` \([^()]*\)$"
    r"|^E05, the token owner \(`[^`]+`\)$"
)


def g_fowner(t: Texts) -> list[Finding]:
    """RULED BQ-7: one owner per F row, a spec or an area, never an agent."""
    sec = at(t, FINDING_HEAD)
    bad: list[Finding] = []
    for r in table(spec_sec(t, FINDING_HEAD)):
        if len(r) < 9:
            continue
        if AGENT.search(norm_text(r[6])):
            bad.append(F("G-FOWNER", f"{r[0]} names an agent as owner", "spec", sec))
        elif not OWNER_FORM.match(r[6]):
            bad.append(F("G-FOWNER", f"{r[0]} owner is not one spec or area", "spec", sec))
    return bad


def hc_sources() -> list[tuple[Pair, str]]:
    """Each high-contrast shortfall with the merged line that binds it."""
    out: list[tuple[Pair, str]] = []
    for p in hc_under():
        for cid in ("D02", "D03"):
            lines = at_base(CITE_FILES[cid]).split("\n")
            for i, ln in enumerate(lines, 1):
                if f"`{p.fg}`" in ln and f"`{p.bg}`" in ln and ln.startswith("|"):
                    out.append((p, f"{cid}:{i}"))
    return out


def g_hcfrow(t: Texts) -> list[Finding]:
    rows = table(spec_sec(t, FINDING_HEAD))
    bad: list[Finding] = []
    for p, cite in hc_sources():
        if not any(
            f"`{p.fg}` on `{p.bg}`" in " ".join(r)
            and cite in r[4]
            and r[7] == "E05 tokens"
            and r[1] == "Major"
            for r in rows
            if len(r) == 9
        ):
            msg = f"no Major F row routes {p.fg} on {p.bg} at {cite} (high contrast) to E05"
            bad.append(F("G-HCFROW", msg, "spec", at(t, FINDING_HEAD)))
    return bad


# the F rows the ruling fixes: id -> (severity, clause, evidence words, target words, close)
FROWS_RULED: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...], str]] = {
    "F-01": (
        "Major",
        "T Sec",
        ("D03:221", "E09-D09:85", ":95", "C-12.4", "D04:171 follows D03's close"),
        ("#990", "#1106"),
        "the row shows the role-visible label only",
    ),
    "F-02": (
        "Major",
        "3.4.4",
        ("H03:79", "`05`:97"),
        ("#990",),
        "H03's Confirm row returns focus as `05`:97 binds",
    ),
    "F-03": ("Minor", "3.1.6", ("D03:140",), ("#990",), ""),
    "F-04": ("Minor", "6.2a", ("H03:120", "`14`:1571"), ("#990",), ""),
    "F-05": ("Minor", "6.2d", ("D03:233", "H03:96", "`15`:318"), ("#990",), ""),
    "F-06": (
        "Minor",
        "6.5",
        ("D03:202", "`14`:1621", '"its target algo and effect"', "(heuristic"),
        ("#990",),
        "",
    ),
    "F-07": ("Minor", "6.5", ("H03:98", "`15`:469"), ("#990",), ""),
    "F-08": ("Minor", "3.1.4", ("D02:114", "D03:165", "`05`:11"), ("#990",), ""),
    "F-09": (
        "Minor",
        "7.4",
        ("D02:415", "`15`:470", "`16`:178", "D04:558", "D04H:190"),
        ("#990",),
        "the dialogs follow CMP-043 as H21 rules",
    ),
    "F-10": ("Minor", "3.4.6", ("D02:155", "D03:258"), ("#990",), ""),
    "F-11": ("Major", "5.6", ("D02:451",), ("E05 tokens",), ""),
    "F-12": ("Major", "5.6", ("D03:465",), ("E05 tokens",), ""),
}


def g_frows_ruled(t: Texts) -> list[Finding]:
    rows = rows_by(spec_sec(t, FINDING_HEAD))
    sec = at(t, FINDING_HEAD)
    bad: list[Finding] = []
    for fid, (sev, cl, cites, target, close) in FROWS_RULED.items():
        r = rows.get(fid)
        if r is None or len(r) != 9:
            bad.append(F("G-FROWS-RULED", f"{fid} is missing", "spec", sec))
            continue
        if (
            r[1] != sev
            or r[2].strip("`") != cl
            or any(c not in r[4] for c in cites)
            or any(w not in r[7] for w in target)
            or (close and r[8] != close)
        ):
            msg = f"{fid} must read {sev} · {cl} · evidence {cites} · target {target} · {close!r}"
            bad.append(F("G-FROWS-RULED", msg, "spec", sec))
    f01 = rows.get("F-01", [])
    if len(f01) != 9 or 'where the row shows "another user"' not in f01[5]:
        msg = 'F-01\'s replacement must be scoped to where the row shows "another user"'
        bad.append(F("G-FROWS-RULED", msg, "spec", sec))
    return bad


# BQ-16 (PROPOSED): the routing of every event class; (RT, event pattern, region, new to `05`)
ROUTES: tuple[tuple[str, str, str, bool], ...] = (
    ("RT-01", r"\bfailed start or place\b", "assertive", True),
    ("RT-02", r"\ba halt\b.*\bhalted by risk control\b with its reason", "assertive", True),
    ("RT-03", r"^a failed run$", "assertive", True),
    ("RT-04", r"\boco double fill\b", "assertive", True),
    ("RT-05", r"\brejected slice; a double refusal\b", "assertive", True),
    ("RT-06", r"^an account going down$", "assertive", True),
    ("RT-07", r"\b2 orders at bybit need you\b", "assertive", True),
    ("RT-08", r"\buntracked lockout line\b", "assertive", True),
    ("RT-09", r"\bpost reconnect summary\b", "assertive", True),
    ("RT-10", r"\bcompletion, ended short, cancelled, limit reached\b", "polite", True),
    ("RT-11", r"\bbehind plan, bound reached\b", "polite", True),
    ("RT-12", r"^paused by you; resumed$", "polite", True),
    ("RT-13", r"\bcase 2 banner's bold lead\b", "polite", True),
    ("RT-14", r"\ba press on a t2 or validity control\b", "polite", True),
    ("RT-15", r"^the filter result$", "polite", True),
    ("RT-16", r"\bbulk result's count line\b", "polite", True),
    ("RT-17", r"\bplaced oco a_15 is running\b", "polite", True),
    ("RT-18", r"\bheader age's warning\b", "polite", True),
    ("RT-19", r"^progress$", "polite", True),
    ("RT-20", r"\balgo child's fill or rejection\b", "polite", True),
    ("RT-21", r"\bat bybit now header total\b", "polite", True),
    ("RT-22", r"\bvalue the user is editing\b", "polite", False),
    ("RT-23", r"^countdowns\b", "none", True),
    ("RT-24", r"^the header age, checked with bybit\b", "none", True),
    ("RT-25", r"\bper row values off the focused row\b", "none", True),
    ("RT-26", r"\bcase 1 in panel line\b", "none", True),
    ("RT-27", r"\bresidual risk note itself\b", "none", True),
    ("RT-28", r"\bserver's refusal at the point of action\b", "assertive", False),
)


def g_route(t: Texts) -> list[Finding]:
    sec = at(t, ROUTE_HEAD)
    rows = table(spec_sec(t, ROUTE_HEAD))
    bad: list[Finding] = []
    lane, throttle = base_value("TIME:lane"), base_value("TIME:throttle")
    for rid, pat, region, new in ROUTES:
        hit = [r for r in rows if len(r) == 7 and re.search(pat, norm_text(r[2].replace('"', "")))]
        if len(hit) != 1 or hit[0][0] != rid:
            bad.append(F("G-ROUTE", f"{rid} {pat!r} has {len(hit)} rows", "spec", sec))
            continue
        r = hit[0]
        if norm_text(r[3]) != region:
            bad.append(F("G-ROUTE", f"{rid} region {r[3]!r}; ruled {region}", "spec", sec))
        if new and r[6] != PENDING:
            bad.append(F("G-ROUTE", f"{rid} is new to `05`: status must be PROPOSED", "spec", sec))
        if not new and r[6] != "in `05`":
            bad.append(F("G-ROUTE", f"{rid} is `05`'s: status must be 'in `05`'", "spec", sec))
        cad = norm_text(r[4])
        if region == "none" and not cad.startswith("never"):
            bad.append(F("G-ROUTE", f"{rid} cadence must be never", "spec", sec))
        if region == "assertive" and not cad.startswith("once"):
            bad.append(F("G-ROUTE", f"{rid} is assertive once, never coalesced", "spec", sec))
        if rid in ("RT-19", "RT-20", "RT-21") and f"at most once per {lane} s" not in cad:
            bad.append(F("G-ROUTE", f"{rid} cadence must be the lane's {lane} s", "spec", sec))
        if rid == "RT-22" and f"at most once per {throttle} s" not in cad:
            bad.append(F("G-ROUTE", f"{rid} keeps `05`:147's {throttle} s", "spec", sec))
        if not CITE_GROUP.search(r[5]):
            bad.append(F("G-ROUTE", f"{rid} carries no source cite", "spec", sec))
    if len(rows) != len(ROUTES):
        bad.append(F("G-ROUTE", f"§8.1 has {len(rows)} rows; ruled {len(ROUTES)}", "spec", sec))
    return bad + need(
        t,
        "G-ROUTE",
        ROUTE_HEAD,
        (
            "two regions per surface, one polite and one assertive, pre rendered empty",
            "the text is swapped, never the node",
            "every announced string d02 §7 and d03 §10 bind has its row here",
        ),
    )


def g_alt(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for qid, words in (
        ("Q-01", ("`05`:148's list only", "PROPOSED", "#2701")),
        ("Q-02", ("every child fill assertive", "PROPOSED", "#2701")),
        ("Q-03", ("five annotation boards", "none drawn")),
        ("Q-04", ("a glyph per treatment", "#988", "C-30's reading, PROPOSED", "#2701")),
    ):
        q = line_of(t, f"- **{qid}**")
        if any(w not in q for w in words):
            bad.append(
                F("G-PENDING", f"{qid} lost its alternative or default", "spec", at(t, Q_HEAD))
            )
    return bad


def shipped_bindings(km: object) -> dict[str, str]:
    out: dict[str, str] = {}

    def walk(o: object) -> None:
        if isinstance(o, dict):
            if "id" in o and "defaultBinding" in o:
                out[str(o["id"])] = str(o["defaultBinding"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(km)
    return out


# the shipped bindings live on the Algos tab that §5.4 must set against the screens' keys
KM_ROWS = {"K-10": "ticket.submit", "K-11": "positions.open_sltp", "K-12": "positions.close"}


def g_keys(t: Texts) -> list[Finding]:
    sec = at(t, KEY_HEAD)
    ids = defined_ids(t)
    bad: list[Finding] = []
    shipped = shipped_bindings(json.loads(at_base(CITE_FILES["KM"])))
    rows = rows_by(spec_sec(t, KEY_HEAD))
    for kid, cmd in KM_ROWS.items():
        r = rows.get(kid, [])
        if len(r) < 7 or f"`{shipped.get(cmd, '?')}`" not in r[1] or "`KM`" not in r[4]:
            bad.append(F("G-KEYS", f"{kid} lost the shipped {cmd}", "spec", sec))
    for kid in ("K-11", "K-12"):
        r = rows.get(kid, [])
        if len(r) < 7 or "C-11" not in r[6]:
            bad.append(F("G-KEYS", f"{kid} must resolve by C-11 (they stay live)", "spec", sec))
    r = rows.get("K-15", [])  # lens 3 M1: the sort key is bound by the merged sources
    if (
        len(r) < 7
        or "sort" not in r[2]
        or "PROPOSED" in r[2]
        or "binds, per `05`:187 and `15`:531" not in r[2]
        or "D03 silent" not in r[2]
    ):
        bad.append(
            F(
                "G-KEYS",
                "K-15 binds the sort key per `05`:187 and `15`:531, not PROPOSED",
                "spec",
                sec,
            )
        )
    r = rows.get("K-16", [])  # lens 3 M1: no mouse-only path
    if len(r) < 7 or "expand" not in r[2] or "G-19" not in r[6] or "PROPOSED" not in r[2]:
        bad.append(F("G-KEYS", "K-16 must bind the row expand key, PROPOSED (G-19)", "spec", sec))
    c11 = rows_by(spec_sec(t, C_HEAD)).get("C-11", [])
    if len(c11) < 3 or "stay live on the Algos tab" not in c11[2] or "E29-D05:613" not in c11[2]:
        bad.append(
            F("G-KEYS", "C-11 lost the ruled reading (they stay live)", "spec", at(t, C_HEAD))
        )
    for r in rows.values():
        if len(r) < 7:
            bad.append(F("G-KEYS", f"{r[0]} has {len(r)} cells", "spec", sec))
            continue
        hits = fixture_hits(r[1])
        modes = {h.get("mode", "") for h in hits}
        res = ID_CELL.findall(r[6])
        if modes & {"table", "focus", "global"} and not res:
            msg = f"{r[0]} collides in {sorted(modes)} with no resolution"
            bad.append(F("G-KEYS", msg, "spec", sec))
        for x in res:
            if x not in ids:
                bad.append(F("G-KEYS", f"{r[0]} resolution {x} is not defined", "spec", sec))
        if "`KM`" in r[4]:
            bound = set(shipped.values())
            for c in chords(r[1]):
                if c not in bound:
                    bad.append(F("G-KEYS", f"{r[0]} {c} is not a shipped binding", "spec", sec))
    return bad


CONTROL_ROLES = frozenset({"button", "menuitem", "link", "checkbox", "radio", "tab"})
# BQ-20's pattern: the names that must be verb + kind + id + " on " + symbol + ", " + account
PATTERN = re.compile(
    r"^(?:Pause|Resume|Cancel|Cancel and flatten|Acknowledge|Select) "
    r"(?:TWAP|iceberg|chase|OCO) a_\d+ on [A-Z]+, \w+$"
)
PATTERN_ROWS = ("N-19", "N-20", "N-21", "N-22", "N-41", "N-42")
NAMES_REQUIRED: tuple[tuple[str, str], ...] = (
    ("running view", "Cancel"),
    ("running view", "Cancel and flatten"),
    ("SCR-070", "Adopt into run"),
    ("SCR-070", "an orphan's Cancel"),
    ("SCR-070", "Cancel all"),
    ("SCR-070", "the bulk confirm"),
    ("SCR-070", "the grid"),
    ("SCR-069", "the residual-risk note"),
    ("SCR-066", "the schedule"),
    ("SCR-068", "Peg"),
)


def _quoted(cell: str) -> list[str]:
    return [m[1:-1] for m in re.findall(r'"[^"]+"', cell)]


def _label_norm(s: str) -> str:
    return norm_text(s.replace(ELLIPSIS, " ")).strip(" .")


def g_names(t: Texts) -> list[Finding]:
    sec = at(t, NAME_HEAD)
    rows = table(spec_sec(t, NAME_HEAD))
    bad: list[Finding] = []
    have = {(r[1], r[2]) for r in rows if len(r) == 8}
    for key in NAMES_REQUIRED:
        if key not in have:
            bad.append(F("G-NAMES", f"no names row for {key}", "spec", sec))
    for r in rows:
        if len(r) != 8:
            bad.append(F("G-NAMES", f"{r[0]} has {len(r)} cells", "spec", sec))
            continue
        nid, _scr, _el, role, label, name, _desc, src = r
        if not CITE_GROUP.search(src):
            bad.append(F("G-NAMES", f"{nid} carries no source cite", "spec", sec))
        roles = {x.strip() for x in re.split(r"[/,]", role)}
        labels, names = _quoted(label), _quoted(name)
        if roles & CONTROL_ROLES and labels and names:
            for lb in labels:
                if not any(_label_norm(lb) in _label_norm(nm) for nm in names):
                    msg = f"{nid} name {names} does not hold its visible label {lb!r}"
                    bad.append(F("G-NAMES", msg, "spec", sec))
        if nid in PATTERN_ROWS and not all(PATTERN.match(nm) for nm in names[:1]):
            bad.append(F("G-NAMES", f"{nid} name breaks BQ-20's pattern", "spec", sec))
    return bad + need(
        t,
        "G-NAMES",
        NAME_HEAD,
        (
            (
                'the effect clause ("its 0.07 btc order at bybit is cancelled too") and a t2'
                " reason are the description, never the name"
            ),
            "a visible label leads its name",
        ),
    )


# AC3's treatments: each has its carrier row (the signal cell)
CARRIER_TREATMENTS = (
    "running",
    "paused",
    "degraded, case 1",
    "degraded, case 2",
    "halted",
    "failed",
    "orphaned",
)


def g_carrier(t: Texts) -> list[Finding]:
    sec = at(t, CARRIER_HEAD)
    rows = table(spec_sec(t, CARRIER_HEAD))
    bad = [
        F("G-CARRIER", f"a signal carried by colour alone: {h[0]!r}", h[1], h[2])
        for h in claims(lex(t), COLOUR_ONLY)
        if "blocking" not in h[0]
    ]
    signals = [r[1] for r in rows if len(r) == 8]
    for tr in CARRIER_TREATMENTS:
        if tr not in signals:
            bad.append(F("G-CARRIER", f"no carrier row for the treatment {tr!r}", "spec", sec))
    for r in rows:
        if len(r) != 8:
            bad.append(F("G-CARRIER", f"{r[0]} has {len(r)} cells", "spec", sec))
            continue
        word, glyph, state = r[3], r[4], r[5]
        if all(c in ("", "—") for c in (word, glyph, state)):
            bad.append(F("G-CARRIER", f"{r[0]} has no non-colour carrier", "spec", sec))
        if r[1] in CARRIER_TREATMENTS and (word in ("", "—") or glyph in ("", "—")):
            bad.append(F("G-CARRIER", f"{r[0]} lost its word or its glyph", "spec", sec))
    bad += need(
        t,
        "G-CARRIER",
        CARRIER_HEAD,
        ("nothing rests on a fill (r 5)", "which d04 §3.1's glyphs supersede"),
    )
    r5 = norm_text(line_of(t, "- **R-5"))
    if "every colour carrying signal" not in r5 or "colour alone is blocking" not in r5:
        bad.append(F("G-CARRIER", "R-5 lost its rule", "spec", "1. Purpose, method,"))
    return bad


TREATMENT_ROWS = {
    "running": "running",
    "paused": "paused",
    "degraded, case 1": "degraded-1",
    "degraded, case 2": "degraded-2",
    "halted": "halted",
    "failed": "failed",
    "orphaned": "orphaned",
    "done": "done",
    "cancelled": "cancelled",
}


def g_cvd(t: Texts) -> list[Finding]:
    """BQ-26 (confirmed): the port gated against its source; one row per treatment with its four
    simulations; the missing renders said."""
    bad = [F("G-CVD", msg, None, None) for msg in cvd_port_problems()]
    sec = at(t, CVD_HEAD)
    bad += lexicon("G-CVD", "a render claimed that does not exist", RENDER_TERM)(t)
    rows = {r[0]: r for r in table(spec_sec(t, CVD_HEAD)) if r}
    for name, key in TREATMENT_ROWS.items():
        r = rows.get(name)
        if r is None or len(r) != 7:
            bad.append(F("G-CVD", f"no seven-cell row for {name!r}", "spec", sec))
            continue
        fill_tok = re.findall(r"`(color\.[^`]+)`", r[1])
        if fill_tok[:1] != [TREATMENTS[key][0]]:
            bad.append(F("G-CVD", f"{name!r} fill must be {TREATMENTS[key][0]}", "spec", sec))
        for col, sim in ((2, "protan"), (3, "deutan"), (4, "tritan")):
            if f"CVD:{key}.{sim}" not in r[col]:
                bad.append(F("G-CVD", f"{name!r} {sim} cell is not its anchor", "spec", sec))
        if f"GREY:{key}.grey" not in r[5]:
            bad.append(F("G-CVD", f"{name!r} greyscale cell is not its anchor", "spec", sec))
    return bad + need(
        t,
        "G-CVD",
        CVD_HEAD,
        (
            "no protanopia render",
            "no tritanopia render",
            "no d03 render",
            "the computed leg stands in for them (c 18)",
            "machado 2009 for tritan, #4652's row",
            "every treatment stays distinguishable by glyph and text",
            "buy against sell (cr 11)",
            'the stop ✓ against "none" (cr 12)',
            (
                'so ac3 is read as "carried by glyph and text, never colour alone, and told apart'
                ' at least by word" (c 30; q 04)'
            ),
        ),
    )


def g_annot(t: Texts) -> list[Finding]:
    """BQ-35 (confirmed): every merged frame keyed exactly once; D04's frames PENDING rows."""
    sec = at(t, ANNOT_HEAD)
    rows = table(spec_sec(t, ANNOT_HEAD))
    ids = defined_ids(t)
    bad: list[Finding] = []
    merged = [f for _c, f in merged_frames()]
    d04 = list(d04_frames())
    seen_m: dict[str, int] = {}
    seen_p: dict[str, int] = {}
    for r in rows:
        if len(r) != 8:
            bad.append(F("G-ANNOT", f"{r[0]} has {len(r)} cells", "spec", sec))
            continue
        frames = re.findall(r"`((?:SCR|CMP)-\d{3}/[^`]+|motion/[^`]+)`", r[1])
        pending = r[2] == D04_PENDING
        for f in frames:
            target = seen_p if pending else seen_m
            target[f] = target.get(f, 0) + 1
        if not pending:
            if any(c in ("", "—") for c in (r[3], r[4], r[5], r[6])):
                msg = f"{r[0]} lacks roles, focus, announcements or keys (none is written out)"
                bad.append(F("G-ANNOT", msg, "spec", sec))
            if not re.search(r"\b[DH]0\d \d\d", r[2]):
                bad.append(F("G-ANNOT", f"{r[0]} names no board", "spec", sec))
        for x in expand_ids(" ".join(r[3:])):
            if x not in ids:
                bad.append(F("G-ANNOT", f"{r[0]} refers to {x}, not defined", "spec", sec))
    for f in merged:
        if seen_m.get(f, 0) != 1:
            bad.append(F("G-ANNOT", f"{f} keyed {seen_m.get(f, 0)} times", "spec", sec))
    for f in d04:
        if seen_p.get(f, 0) != 1:
            bad.append(
                F("G-ANNOT", f"D04's {f} keyed {seen_p.get(f, 0)} times PENDING", "spec", sec)
            )
    for f in set(seen_m) - set(merged):
        bad.append(F("G-ANNOT", f"{f} is not a merged frame", "spec", sec))
    for f in set(seen_p) - set(d04):
        bad.append(F("G-ANNOT", f"{f} is not a D04 frame", "spec", sec))
    return bad + need(
        t,
        "G-ANNOT",
        ANNOT_HEAD,
        (
            "no new drawing",
            "is keyed exactly once",
            "rows marked pending (text first; e33 d04 #988 boards)",
        ),
    )


def g_crows(t: Texts) -> list[Finding]:
    rows = [" ".join(r) for r in table(spec_sec(t, C_HEAD))]
    need_ = (
        ("the peg options", r"`14`:1584.*D02's maker / taker / offset"),
        ("the note's visibility", r"`14`:1596's and S05's \"always visible\".*always reachable"),
        ("the warning-is-alert", r"`15`:318's warning-is-alert.*D03's"),
        ("the status role", r"`14`:1621's `role=\"status\"`.*case 1 `live=\"off\"`"),
        ("the name example", r"`14`:1621's name example.*the effect is the description"),
        ("the absent controls", r"`T Sec`.*the rulings' T2"),
        ("the assertive list", r"`05`:148's assertive list.*PROPOSED; Q-01"),
        ("the coalescing", r"never throttled/coalesced.*PROPOSED; Q-02"),
        ("the header total", r"`05`:147's.*the lane's"),
        ("the auto-cancel", r"D02:114.*off \(§11\.2\)"),
        ("the Positions keys", r"`KM`:503.*stay live on the Algos tab"),
        ("the Esc key", r"`05`:63's.*D03's"),
        ("the high-contrast bar", r"never gated.*for text in high contrast"),
        ("the dialog motion", r"`16`:178.*`15`:470.*H21.*cited, not decided"),
        ("the board glyphs", r"D03 board 04's glyphs.*D04 §3\.1's.*superseded, not redrawn"),
        ("the AC3 reading", r"`T AC3`.*told apart at least by word.*Q-04"),
        ("the renders", r"rendered.*computed"),
        ("the annotation layer", r"annotated a11y layer.*per-frame rows"),
        ("the sign-off", r"accessibility lead \+ CDO.*pending the owner's"),
        ("the screen readers", r"VoiceOver.*`05`:224"),
    )
    bad: list[Finding] = []
    for what, pat in need_:
        if not any(re.search(pat, r) for r in rows):
            bad.append(F("G-CROWS", f"no C row records {what}", "spec", at(t, C_HEAD)))
    return bad


def sprint_start(key: str) -> str:
    """The consumer's sprint start (`E33.json`'s sprint and `calendar_cv.py`'s constants)."""
    tickets = json.loads(at_base(CITE_FILES["E33.json"]))
    sprint = next((str(x.get("sprint", "")) for x in tickets if x.get("key") == key), "")
    cal = at_base("docs/plan/backlog/_tools/calendar_cv.py")
    y, mo, d = (
        int(x)
        for x in grab(
            r"SPRINT01_START = datetime\.date\((\d+, \d+, \d+)\)", cal, "SPRINT01_START"
        ).split(", ")
    )
    days = int(grab(r"^SPRINT_DAYS = (\d+)", cal, "SPRINT_DAYS"))
    n = int(grab(r"(\d+)", sprint, f"{key}'s sprint"))
    return (datetime.date(y, mo, d) + datetime.timedelta(days=(n - 1) * days)).isoformat()


CONSUMER_KEYS = {
    "#990": "E33-D06",
    "#1105": "E33-S05",
    "#1106": "E33-S06",
    "#1100": "E33-Q05",
    "#988": "E33-D04",
    "#1096": "E33-D07",
}
GROWS_NEED = (
    ("G-01", ("§6.5",)),
    ("G-02", ("SCR-076",)),
    ("G-05", ("D03:248", "RT-16")),
    ("G-08", ("`Ctrl+A`", "E49")),
    ("G-09", ("D03:202",)),
    ("G-12", ("Why", "every control", "`15`:64")),
    ("G-14", ("D02:111", "not an F row")),
    ("G-15", ("cvd_sim.py",)),
    ("G-16", ("D04:213",)),
    ("G-17", ("`15`:1032",)),
    ("G-18", ("D03:235",)),
    ("G-19", ("D03:252", "K-16", "`05`:187", "`15`:531")),
)


def g_grows(t: Texts) -> list[Finding]:
    lines = {
        m[1]: ln
        for ln in spec_sec(t, G_HEAD).split("\n")
        if (m := re.match(r"^- \*\*(G-\d\d)\*\*", ln))
    }
    bad: list[Finding] = []
    for gid, words in GROWS_NEED:
        miss = [w for w in words if w not in lines.get(gid, "")]
        if miss:
            bad.append(F("G-GROWS", f"{gid} lacks {miss}", "spec", at(t, G_HEAD)))
    for gid, ln in lines.items():
        m = re.search(
            r"Owner: ([^;]+); consumer (E33-[A-Z]\d\d) \((#\d+)\); due (\d{4}-\d\d-\d\d)", ln
        )
        if not m:
            bad.append(
                F("G-GROWS", f"{gid} lacks its owner, consumer or due date", "spec", at(t, G_HEAD))
            )
            continue
        if AGENT.search(norm_text(m[1])):
            bad.append(F("G-GROWS", f"{gid} names an agent as owner", "spec", at(t, G_HEAD)))
        if CONSUMER_KEYS.get(m[3]) != m[2] or m[4] != sprint_start(m[2]):
            msg = f"{gid} due {m[4]} is not {m[2]}'s sprint start {sprint_start(m[2])}"
            bad.append(F("G-GROWS", msg, "spec", at(t, G_HEAD)))
    return bad


# what E33-D06 lifts as it stands (RULED BQ-34)
LIFTED = ("§5", "§6", "§7", "§8", "§9.1", "§10", "§11", "§12", "§13's replacements", "§16.4")


def g_consumers(t: Texts) -> list[Finding]:
    block = spec_sec(t, HANDOFF_HEAD)
    bad: list[Finding] = []
    miss = [c for c in CONSUMERS if not re.search(rf"{re.escape(c)}\b", block)]
    if miss:
        bad.append(F("G-CONSUMERS", f"§18.2 lacks {miss}", "spec", at(t, HANDOFF_HEAD)))
    lifted = next((x for x in sentences(block) if "lifts" in x and "as they stand" in x), "")
    gone = [x for x in LIFTED if not re.search(rf"{re.escape(x)}(?![\d.])", lifted)]
    if gone:
        bad.append(
            F("G-CONSUMERS", f"§18.2's lifted sections lack {gone}", "spec", at(t, HANDOFF_HEAD))
        )
    for w in ("F-01's D04:171 occurrence", "C-29", "Q-04"):
        if w not in block:
            bad.append(F("G-CONSUMERS", f"§18.2's #988 lacks {w}", "spec", at(t, HANDOFF_HEAD)))
    if "E33-Q05 (#1100) takes §14" not in block:
        bad.append(F("G-CONSUMERS", "§18.2 lost E33-Q05's §14", "spec", at(t, HANDOFF_HEAD)))
    return bad


def g_unbuilt(t: Texts) -> list[Finding]:
    first = line_of(t, "**The algo screens are unbuilt.**")
    bad: list[Finding] = []
    feats = sorted(Path(n).name for n in ls_tree(BASE, FEATURES_REL) if "." not in Path(n).name)
    named = sorted(re.findall(r"`([A-Za-z0-9-]+)`", first.split("and no algo slice")[0]))
    sec = at(t, "0. Status")
    if "and no algo slice" not in first or "holds no algo component" not in first:
        bad.append(F("G-UNBUILT", "§0 lost the unbuilt statement", "spec", sec))
    elif named != feats:
        bad.append(F("G-UNBUILT", f"§0 lists {named}; the base holds {feats}", "spec", sec))
    shipped = git_out(
        "grep",
        "-l",
        "-e",
        "AlgoRun",
        "-e",
        "AlgoSupervisor",
        BASE,
        "--",
        "services",
        "apps",
        "packages",
    )
    if shipped.strip():
        bad.append(F("G-UNBUILT", "shipped code names AlgoRun / AlgoSupervisor", None, None))
    miss = [s for s in STORIES if s not in first]
    if miss:
        bad.append(F("G-UNBUILT", f"§0 does not name {miss}", "spec", sec))
    return bad


A01_RULED = (
    "a failed start or place",
    "a halt with its reason",
    "a failed run",
    "an oco double fill",
    "the untracked lockout, the post reconnect summary",
    "an algo child's fill is folded into its run's polite summary",
    "events of one class in one rendered sample speak as one sentence",
)


def g_arow(t: Texts) -> list[Finding]:
    sec = at(t, A_HEAD)
    bad: list[Finding] = []
    rows = rows_by(spec_sec(t, A_HEAD))
    a01 = norm_text(rows.get("A-01", ["", "", "", "", ""])[-1])
    for w in A01_RULED:
        if w not in a01:
            bad.append(F("G-AROW", f"A-01 New lost {w!r}", "spec", sec))
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
        bad.append(F("G-UNION", "themes.json no longer layers the three themes", None, None))
    for p in union():
        for th, v in measure(p).items():
            b = bar_for(p.role, th)
            if v is None:
                bad.append(F("G-UNION", f"{p.fg} / {p.bg} unresolved in {th}", None, None))
            elif b is not None and th != "hc" and v < b:
                bad.append(
                    F("G-UNION", f"{p.src} {p.fg} on {p.bg} {round2(v)} in {th}", None, None)
                )
    agree, total = printed_agreement()
    if agree != total or total == 0:
        bad.append(F("G-UNION", f"printed cells agree in {agree} of {total}", None, None))
    return bad


def g_untouched(t: Texts) -> list[Finding]:
    """Committed and uncommitted alike: each untouched file's working-tree bytes against the
    merge-base of HEAD and origin/main; an unresolved merge-base FAILs."""
    bad: list[Finding] = []
    ref = t.fork
    if ref is None:
        return [F("G-UNTOUCHED", "git merge-base HEAD origin/main does not resolve", None, None)]
    for nn, text in t.plans:
        rel = cite_path(nn)
        if rel is None:
            continue
        if text == DELETED:
            bad.append(F("G-UNTOUCHED", f"{rel} deleted in the working tree", None, None))
        elif git_show(ref, rel) != text:
            bad.append(F("G-UNTOUCHED", f"{rel} differs from {ref[:10]} (merge-base)", None, None))
        if nn in t.staged:  # the index too: a staged change the working tree reverted
            bad.append(F("G-UNTOUCHED", f"{rel} is staged against {ref[:10]}", None, None))
    summary = line_of(t, "9. Sign-off per RULED BQ-34")
    shown = {nn: (f"`{nn}`" if re.fullmatch(r"\d\d|KM", nn) else nn) for nn in UNTOUCHED}
    gone = [s for s in shown.values() if not re.search(rf"{re.escape(s)}(?![\w-])", summary)]
    if gone:
        bad.append(
            F("G-UNTOUCHED", f"§19's untouched list lacks {gone}", "spec", at(t, SUMMARY_HEAD))
        )
    return bad


# whole-file inputs: parsed or measured as a whole, so any drift at origin/main FAILs
WHOLE_INPUTS = frozenset(
    {
        "apps/web/src/keymap/keymap.json",
        "packages/ui/tokens/primitives.tokens.json",
        "packages/ui/tokens/semantic-dark.tokens.json",
        "packages/ui/tokens/semantic-light.tokens.json",
        "packages/ui/tokens/semantic-hc.tokens.json",
        "packages/ui/tokens/themes.json",
        CVD_SOURCE_REL,
        GREY_SOURCE_REL,
        FIXTURE_REL,
        D02_TOOL_REL,
        D03_TOOL_REL,
    }
)


def cited_lines(text: str) -> set[tuple[str, int]]:
    """(rel, line) of every `file`:line cite in the spec (a range expanded to every line in it)
    and every CITED fragment."""
    out: set[tuple[str, int]] = set()
    lines = text.split("\n")
    fence = fenced(lines)
    for li, line in enumerate(lines):
        if fence[li] or MUT_ROW.match(line):
            continue
        for m in CITE_GROUP.finditer(line):
            cid = m["a"] or m["b"]
            rel = cite_path(cid) if cid not in UNMERGED else None
            if rel is None:
                continue
            for ref in [m["first"], *re.findall(r":(\d+(?:[–-]\d+)?)", m["more"])]:
                ends = [int(x) for x in re.split(r"[–-]", ref)]
                # a range is every line in it (lens 2: an edit inside a range must FAIL too)
                out |= {(rel, n) for n in range(ends[0], ends[-1] + 1)}
    out |= {(r, n) for cid, n, _f in CITED if (r := cite_path(cid)) is not None}
    return out


def g_version(t: Texts) -> list[Finding]:
    """A pinned input that drifts at origin/main FAILs: a whole-file input on any change, a cited
    document on any change to a line this spec cites, every line of a cited range included."""
    bad: list[Finding] = []
    heads = dict(t.head_texts)
    if not heads:
        return [F("G-VERSION", "no pinned input was read at origin/main", None, None)]
    for rel in sorted(WHOLE_INPUTS):
        if heads.get(rel) != git_show(BASE, rel):
            bad.append(F("G-VERSION", f"{rel} drifted at {HEAD}: re-read and re-pin", None, None))
    for rel, n in sorted(cited_lines(t.spec)):
        if rel in WHOLE_INPUTS:
            continue
        head = heads[rel] if rel in heads else git_show(HEAD, rel)
        base = git_show(BASE, rel)
        if head is None or base is None:
            bad.append(F("G-VERSION", f"{rel} is not readable at {HEAD}", None, None))
            continue
        hl, bl = head.split("\n"), base.split("\n")
        if n > len(bl):
            continue  # G-CITE's: a cite out of range at the base
        if n > len(hl) or hl[n - 1] != bl[n - 1]:
            bad.append(
                F("G-VERSION", f"{rel}:{n} drifted at {HEAD}: re-read and re-pin", None, None)
            )
    return bad


def g_t2(t: Texts) -> list[Finding]:
    r4 = norm_text(line_of(t, "- **R-4"))
    if "an over or under conversion is major" not in r4 or "d02:111" not in r4:
        return [F("G-T2", "R-4 lost the T2 reading", "spec", "1. Purpose, method,")]
    return []


LOCKS = ("D02:46–71", "D02:111–112", "D03:31–53", "D03:101–131", "D04:40–67", "E29-D05:258–285")


def g_locked(t: Texts) -> list[Finding]:
    block = spec_sec(t, "1.3 Locked inputs")
    miss = [x for x in LOCKS if x not in block]
    return [F("G-LOCKED", f"§1.3 lacks {miss}", "spec", at(t, "1.3"))] if miss else []


# BQ-33: Q05's five scenarios map one to one (SR id -> scenario)
Q05_SCENARIOS = {"SR-01": "2", "SR-03": "3", "SR-06": "4", "SR-12": "5", "SR-13": "1"}
SCRIPT_SURFACES = (
    "SCR-066 TWAP builder",
    "SCR-067 iceberg builder",
    "SCR-068 chase builder",
    "SCR-069 OCO builder",
    "SCR-070 algo monitor",
)
OBJECTIVE = re.compile(r"`[^`]+`|<!--=|\{\{|\b(?:N|RT|K|CR)-\d\d\b|\"[^\"]+\"")
VAGUE = re.compile(r"\b(?:is accessible|works|properly|correctly|good|fine|as expected)\b")


@functools.lru_cache(maxsize=1)
def template_steps() -> tuple[str, ...]:
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
    named: set[str] = set()
    for x in re.findall(r"\bSR-(\d\d)(?: (?:to|and) SR-(\d\d))?", block):
        lo, hi = int(x[0]), int(x[1] or x[0])
        named |= {f"SR-{n:02d}" for n in range(lo, hi + 1)}
    if srs - named - {"SR-12", "SR-13", "SR-14"}:
        msg = f"§14.3 names no Feature for {sorted(srs - named)}"
        bad.append(F("G-SCRIPT", msg, "spec", sec))
    for r in table(spec_sec(t, AL_HEAD)):
        if len(r) != 5 or "E33-Q05" not in r[3] or not r[4].strip():
            bad.append(F("G-SCRIPT", f"{r[0]} names no E33-Q05 verifier or source", "spec", sec))
        elif not OBJECTIVE.search(r[1]) or VAGUE.search(norm_text(r[1])):
            bad.append(F("G-SCRIPT", f"{r[0]} is not objectively checkable", "spec", sec))
    for r in table(spec_sec(t, SR_HEAD)):
        got = re.findall(r"Q05 scenario (\d)", r[-1]) if r else []
        want = Q05_SCENARIOS.get(r[0]) if r else None
        if got != ([want] if want else []):
            msg = f"{r[0]} maps Q05 scenario {got}; BQ-33 maps {want}"
            bad.append(F("G-SCRIPT", msg, "spec", at(t, SR_HEAD)))
    als = rows_by(spec_sec(t, AL_HEAD))
    srs_rows = rows_by(spec_sec(t, SR_HEAD))
    axe = "zero new serious or critical"  # `05`:247's bar, one bar for AL-29 and SR-13
    if axe not in " ".join(als.get("AL-29", [])) or axe not in " ".join(srs_rows.get("SR-13", [])):
        bad.append(F("G-SCRIPT", f"AL-29 and SR-13 must both read {axe!r}", "spec", sec))
    if "is present in its card" not in " ".join(als.get("AL-27", [])):
        bad.append(F("G-SCRIPT", "AL-27 has no pass condition", "spec", sec))
    al_text = " ".join(" ".join(r) for r in als.values())
    for kid in ("K-11", "K-12", "K-15", "K-16"):
        if kid not in al_text:
            bad.append(F("G-SCRIPT", f"no acceptance row checks {kid}", "spec", sec))
    head = line_of(t, "### 14.3 ")
    if "the template's six scenarios shared once" not in head or "deviation D5" not in head:
        bad.append(F("G-SCRIPT", "§14.3's heading lost the compression note", "spec", sec))
    bad += need(
        t, "G-SCRIPT", "14. The acceptance", ("e33 q05 executes §14.2 verbatim, item by item",)
    )
    return bad


def g_budget(t: Texts) -> list[Finding]:
    n = t.spec.count("\n")
    if n > SPEC_LINE_BUDGET:
        return [F("G-BUDGET", f"spec {n} lines > {SPEC_LINE_BUDGET}", "spec", h2_at(t.spec, n))]
    return []


WALK_ROLE = re.compile(r"^story: (E33-[A-Z]\d\d) \((#\d+)\)$")
WALK_TARGET = re.compile(r"→ (§\d+(?:\.\d+)?|G-\d\d|RT-\d\d)")


def g_walk(t: Texts) -> list[Finding]:
    """The story-role dry run: the table is present; counts add up; every → target parses and
    resolves; a role per consumer; the DoD tick matches."""
    sec = at(t, WALK_HEAD)
    block = spec_sec(t, WALK_HEAD)
    tabs = tables(block)
    bad: list[Finding] = []
    ids = defined_ids(t)
    heads = {m[1] for m in re.finditer(r"^#{2,3} (\d+(?:\.\d+)?)[ .]", t.spec, MULTI)}
    if len(tabs) != 2:
        bad.append(F("G-WALK", f"§17 holds {len(tabs)} tables; two are ruled", "spec", sec))
    roles: set[str] = set()
    ok = len(tabs) == 2
    for rows in tabs:
        for r in rows:
            if len(r) != 6 or not DATE.fullmatch(r[0]):
                bad.append(F("G-WALK", f"a dry-run row is malformed: {r[:2]}", "spec", sec))
                ok = False
                continue
            m = WALK_ROLE.match(r[1])
            if m:
                roles.add(m[2])
                if CONSUMER_KEYS.get(m[2]) != m[1]:
                    bad.append(F("G-WALK", f"{r[1]} names the wrong ticket", "spec", sec))
            elif not r[1].startswith("QA: "):
                bad.append(F("G-WALK", f"{r[1]!r} is not a role", "spec", sec))
            try:
                n_need, n_found, n_not = (int(strip_comments(x)) for x in r[2:5])
            except ValueError:
                bad.append(F("G-WALK", f"{r[1]} counts are not numbers", "spec", sec))
                ok = False
                continue
            if n_found + n_not != n_need:
                bad.append(F("G-WALK", f"{r[1]}: {n_found} + {n_not} != {n_need}", "spec", sec))
                ok = False
            targets = WALK_TARGET.findall(r[5])
            if n_not == 0 and r[5] != "—":
                bad.append(F("G-WALK", f"{r[1]} has no not-found but a disposition", "spec", sec))
            if len(targets) != n_not:
                msg = f"{r[1]}: {n_not} not found, {len(targets)} dispositions"
                bad.append(F("G-WALK", msg, "spec", sec))
                ok = False
            for x in targets:
                good = x.lstrip("§") in heads if x.startswith("§") else x in ids
                if not good:
                    bad.append(F("G-WALK", f"{r[1]}: → {x} does not resolve", "spec", sec))
                    ok = False
                if x.startswith("G-") and m and m[2] not in line_of(t, f"- **{x}**"):
                    msg = f"{r[1]}: {x} does not name {m[2]} as its consumer"
                    bad.append(F("G-WALK", msg, "spec", sec))
                    ok = False
    miss = sorted(set(CONSUMERS) - roles)
    if miss:
        bad.append(F("G-WALK", f"no dry-run role for {miss}", "spec", sec))
        ok = False
    tick = line_of(t, "- [x] Story-role dry run")
    untick = line_of(t, "- [ ] Story-role dry run")
    if ok and not tick:
        bad.append(
            F("G-WALK", "the dry run holds but the DoD line is not ticked", "spec", at(t, DOD_HEAD))
        )
    if not ok and tick:
        bad.append(
            F("G-WALK", "the DoD ticks a dry run that does not hold", "spec", at(t, DOD_HEAD))
        )
    if not tick and not untick:
        bad.append(F("G-WALK", "§18.1 lost the dry-run line", "spec", at(t, DOD_HEAD)))
    if "not a T DoD item" not in (tick or untick):
        msg = "§18.1's dry-run line must say it is added, not a T DoD item"
        bad.append(F("G-WALK", msg, "spec", at(t, DOD_HEAD)))
    return bad + need(
        t,
        "G-WALK",
        WALK_HEAD,
        ("no session took place and none is claimed", "run 2026 10 27 by the writer agent itself"),
    )


def mutation_groups() -> list[tuple[str, list[str]]]:
    """(gate, its mutation ids in order), gates in order of first use: section 15's rows."""
    groups: dict[str, list[str]] = {}
    for m in MUTATIONS:
        groups.setdefault(m.gate, []).append(m.mid)
    return list(groups.items())


def g_mutlist(t: Texts) -> list[Finding]:
    """Section 15 holds one row per gate: the gate, its ruled sentences, and every mutation that
    must trip it, in the tool's order (one to one with MUTATIONS)."""
    rows = table(section(t.spec, MUTATION_HEAD))
    got = [(r[0], re.findall(r"\bM-\d+\b", r[2])) for r in rows if len(r) == 3]
    if len(got) != len(rows):
        got.append(("malformed row", []))
    want = mutation_groups()
    if got != want:
        diff = [x for x in got if x not in want][:3] + [x for x in want if x not in got][:3]
        msg = f"§15 differs from the tool's mutations: {diff}"
        return [F("G-MUTLIST", msg, "spec", h2_of(t.spec, MUTATION_HEAD))]
    return []


MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
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
    g_cvd,
    g_annot,
    g_crows,
    g_grows,
    g_consumers,
    g_unbuilt,
    g_arow,
    g_union,
    g_untouched,
    g_version,
    g_t2,
    g_locked,
    g_script,
    g_budget,
    g_walk,
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
        "# E33-D05 pins (every unit of the review): doc, region (heading path #occurrence), "
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


def audit(t: Texts, fetch: Fetch) -> tuple[list[str], list[str], int]:
    """(FAIL lines, NOTE lines, cites checked). One FAIL line per gate; a pin finding in a section
    another gate already FAILs is demoted to a NOTE line."""
    found: list[Finding] = []
    for gate in LEXICON_GATES:
        found += gate(t)
    for doc, text in docs_of(t).items():
        found += g_anchor_doc(doc, text, t.values)
        found += g_marker_doc(doc, text, t.values)
        found += g_hex_doc(doc, text)
    for gate in MEASURED_GATES:
        found += gate(t)
    cf, n = cite_findings(docs_of(t), fetch)
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
    return fails, notes, n


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


def rep(old: str, new: str) -> Edit:
    """The first `old` anywhere in the spec, replaced."""
    return lambda s: s.replace(old, new, 1)


def edit_line(text: str, n: int, old: str, new: str) -> str:
    """Line `n` (1-based) of `text` with `old` replaced (an origin/main drift inside a range)."""
    lines = text.split("\n")
    if n <= len(lines):
        lines[n - 1] = lines[n - 1].replace(old, new, 1)
    return "\n".join(lines)


def overrun(text: str) -> str:
    n = text.count("\n")
    return text + "filler\n" * (SPEC_LINE_BUDGET - n + 5)


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str  # the gate tag that must trip ("" for a probe that must trip nothing)
    spec: Edit | None = None
    plan: tuple[str, Edit] | None = None  # (untouched id, edit) on the working-tree copy
    extra: tuple[str, ...] = ()  # files named for this ticket beside the spec
    fork: str | None = "merge-base"  # "none" simulates an unresolved merge-base
    head: tuple[str, Edit] | None = None  # (pinned rel, edit) on its origin/main text
    staged: tuple[str, ...] = ()  # untouched ids staged in the index (simulated)
    what: str = ""  # §15's Mutation cell
    rule: str = ""  # §15's ruled-sentence cell (after the gate tag)


def cell_sub(head: str, first: str, col: int, old: str, new: str) -> Edit:
    """Replace `old` inside one cell of the row whose first cell is `first`."""
    return row_edit(head, first, col, lambda c: c.replace(old, new, 1))


def walk_edit(role: str, col: int, fn: Callable[[str], str]) -> Edit:
    """A cell of the dry-run row whose Role cell is `role`."""

    def run(text: str) -> str:
        block = section(text, WALK_HEAD)
        lines = block.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("|") and len(split_row(ln)) > 1 and split_row(ln)[1] == role:
                lines[i] = set_cell(ln, col, fn)
                return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def say(head: str, sentence: str) -> Edit:
    return say_in(head, sentence)


def trailing_space(text: str) -> str:
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("**The algo screens are unbuilt.**"):
            lines[i] = ln + " "
            break
    return "\n".join(lines)


def _drop_feature(name: str) -> Callable[[list[str]], list[str]]:
    def run(lines: list[str]) -> list[str]:
        i = next((k for k, ln in enumerate(lines) if ln.startswith(f"Feature: {name}")), -1)
        return lines if i < 0 else lines[:i] + lines[i + 5 :]

    return run


def in_lines(head: str, fn: Callable[[list[str]], list[str]]) -> Edit:
    def run(text: str) -> str:
        block = section(text, head)
        return text.replace(block, "\n".join(fn(block.split("\n"))), 1) if block else text

    return run


def _swap_first_rows(lines: list[str]) -> list[str]:
    idx = [i for i, ln in enumerate(lines) if ln.startswith("|") and not is_rule(ln)][1:3]
    if len(idx) == 2:
        lines[idx[0]], lines[idx[1]] = lines[idx[1]], lines[idx[0]]
    return lines


LIGHTHOUSE = "    And the affected screen's Lighthouse Accessibility score remains >= 95\n"
RH, FH, NH, KH, CH = ROUTE_HEAD, FINDING_HEAD, NAME_HEAD, KEY_HEAD, CLAUSE_HEAD
M = Mutation
MUTATIONS: tuple[Mutation, ...] = (
    M(
        "M-01",
        "G-PENDING",
        sub_in(RH, "PROPOSED, owner approval pending (#2701))", "RULED)"),
        what='write "RULED" for the PROPOSED marker in §8.1\'s heading',
        rule="BQ-16 is PROPOSED, owner approval pending (#2701)",
    ),
    M(
        "M-02",
        "G-PENDING",
        say(AGG_HEAD, "BQ-17 is confirmed."),
        what='write "BQ-17 is confirmed." in §8.2',
        rule="BQ-17 is never read as ruled",
    ),
    M(
        "M-03",
        "G-PENDING",
        rep("are **PROPOSED, owner approval pending (#2701)**", "are **ruled**"),
        what='write "ruled" for BQ-16 / BQ-17\'s marker in the RULED paragraph',
        rule="the RULED paragraph keeps the PROPOSED marker",
    ),
    M(
        "M-04",
        "G-PENDING",
        line_sub("- **Q-01**", "PROPOSED", "taken"),
        what='write "taken" for "PROPOSED" in Q-01',
        rule="Q-01 keeps BQ-16's alternative and its PROPOSED default",
    ),
    M(
        "M-05",
        "G-ROUTE",
        cell_sub(RH, "RT-02", 3, "assertive", "polite"),
        what='write "polite" in RT-02\'s Region cell',
        rule="a halt is assertive, once (BQ-16)",
    ),
    M(
        "M-06",
        "G-ROUTE",
        cell_sub(RH, "RT-03", 3, "assertive", "polite"),
        what='write "polite" in RT-03\'s Region cell',
        rule="a failed run is assertive, once (BQ-16)",
    ),
    M(
        "M-07",
        "G-ROUTE",
        cell_sub(RH, "RT-19", 3, "polite", "assertive"),
        what='write "assertive" in RT-19\'s Region cell',
        rule="progress is polite (BQ-18)",
    ),
    M(
        "M-08",
        "G-ROUTE",
        cell_sub(RH, "RT-23", 3, "none", "polite"),
        what='write "polite" in RT-23\'s Region cell',
        rule="countdowns are never announced (BQ-18)",
    ),
    M(
        "M-09",
        "G-ROUTE",
        cell_sub(RH, "RT-01", 6, PENDING, "in `05`"),
        what='write "in `05`" in RT-01\'s Status cell',
        rule="the E33 assertive set is new to `05` and PROPOSED (BQ-16)",
    ),
    M(
        "M-10",
        "G-ROUTE",
        cell_sub(RH, "RT-02", 4, "once per event", "twice per event"),
        what='write "twice per event" in RT-02\'s Cadence cell',
        rule="assertive once, never repeated (BQ-16)",
    ),
    M(
        "M-11",
        "G-ROUTE",
        cell_sub(RH, "RT-19", 4, "5<!--=TIME:lane-->", "2<!--=TIME:throttle-->"),
        what="write the field throttle's anchor for the lane's in RT-19's Cadence cell",
        rule="progress at the lane's rate (BQ-18)",
    ),
    M(
        "M-12",
        "G-ROUTE",
        say(DEGRADED_HEAD, "A halt is announced politely."),
        what='write "A halt is announced politely." in §8.4',
        rule="an assertive class is never read as polite (BQ-16)",
    ),
    M(
        "M-13",
        "G-ROUTE",
        rep("the text is swapped, never the node", "the text and the node are swapped"),
        what='write "the text and the node are swapped" in §8.1',
        rule="the text is swapped, never the node (`05`:150)",
    ),
    M(
        "M-14",
        "G-AGG",
        say(AGG_HEAD, "Each child fill is announced assertively."),
        what='write "Each child fill is announced assertively." in §8.2',
        rule="child fills fold into the run's polite summary (BQ-17)",
    ),
    M(
        "M-15",
        "G-AGG",
        rep("different classes never merge", "different classes merge"),
        what='write "different classes merge" in §8.2',
        rule="different classes never merge (BQ-17)",
    ),
    M(
        "M-16",
        "G-THROTTLE",
        say(THROTTLE_HEAD, "Progress speaks every 2<!--=TIME:throttle--> s."),
        what='write "Progress speaks every {{TIME:throttle}} s." in §8.3',
        rule="progress at most once per {{TIME:lane}} s (AC4)",
    ),
    M(
        "M-17",
        "G-THROTTLE",
        rep("the monitor beneath is inert", "the monitor beneath is live"),
        what='write "live" for "inert" in §8.3',
        rule="the modal makes the monitor beneath inert (BQ-18)",
    ),
    M(
        "M-18",
        "G-DEGRADED",
        say(DEGRADED_HEAD, "Case 1's line is announced politely."),
        what='write "Case 1\'s line is announced politely." in §8.4',
        rule='the case-1 line is `live="off"` (BQ-19)',
    ),
    M(
        "M-19",
        "G-NOTE",
        say(NOTE_HEAD, "The residual note is announced on appearance."),
        what='write "The residual note is announced on appearance." in §6.4',
        rule='the note is `role="note"`, never announced (BQ-15)',
    ),
    M(
        "M-20",
        "G-NOTE",
        sub_in(NOTE_HEAD, "kept until acknowledged", "dismissed on close"),
        what='write "dismissed on close" for "kept until acknowledged" in §6.4',
        rule="the note is kept until acknowledged (BQ-15)",
    ),
    M(
        "M-21",
        "G-PEG",
        say(PEG_HEAD, "The peg offers a mid option."),
        what='write "The peg offers a mid option." in §5.2',
        rule='maker / taker / offset; "mid" an absence (BQ-13)',
    ),
    M(
        "M-22",
        "G-TIME",
        say(TIME_HEAD, "The auto-cancel still runs on an algo start."),
        what='write "The auto-cancel still runs on an algo start." in §11.2',
        rule="no auto-cancel on any algo start (BQ-24)",
    ),
    M(
        "M-23",
        "G-HCBAR",
        say(CONTRAST_HEAD, "Every danger confirm passes in high contrast."),
        what='write "Every danger confirm passes in high contrast." in §10',
        rule="a pair below {{BAR:hc}}:1 is an F row, never a pass (BQ-27)",
    ),
    M(
        "M-24",
        "G-HCBAR",
        in_lines(CONTRAST_HEAD, lambda ls: [x for x in ls if not x.startswith("| `color.text")]),
        what="delete §10's high-contrast row",
        rule="§10 lists every pair the re-measure finds (BQ-27)",
    ),
    M(
        "M-25",
        "G-HCFROW",
        cell_sub(FH, "F-12", 3, "`color.text.on-action`", "`color.text.primary`"),
        what="write `color.text.primary` for the token in F-12's Spec cell",
        rule="each shortfall has its Major F row to E05 (BQ-27)",
    ),
    M(
        "M-26",
        "G-LEAK",
        say(LEAK_HEAD, "A row's name may name another user."),
        what='write "A row\'s name may name another user." in §7.2',
        rule="no name discloses another user (F-01)",
    ),
    M(
        "M-27",
        "G-LEAK",
        rep("**The leak (F-01, Major):**", "**The leak (F-01):**"),
        what='delete ", Major" from §7.2\'s leak',
        rule="the leak is graded Major (the ruling)",
    ),
    M(
        "M-28",
        "G-FROWS-RULED",
        cell_sub(FH, "F-01", 8, "role-visible label only", "user"),
        what='write "the row shows the user" in F-01\'s Close state cell',
        rule='F-01 closes as "the row shows the role-visible label only"',
    ),
    M(
        "M-29",
        "G-FROWS-RULED",
        cell_sub(FH, "F-02", 4, "; `05`:97 binds", ""),
        what='delete "`05`:97 binds" from F-02\'s Evidence cell',
        rule="F-02: `05`:97 binds the trigger (the ruling)",
    ),
    M(
        "M-30",
        "G-FOCUS",
        say(FOCUS_HEAD, "Focus returns to the panel header after a confirm."),
        what='write "Focus returns to the panel header after a confirm." in §5.1',
        rule="focus returns to the trigger (F-02)",
    ),
    M(
        "M-31",
        "G-FOCUS",
        row_edit(FOCUS_HEAD, FOCUS_ROWS[4], 6, to("the panel header")),
        what='write "the panel header" in the confirms\' Focus returns cell',
        rule="the confirms return focus to the trigger's row (F-02)",
    ),
    M(
        "M-32",
        "G-FOCUS",
        cell_sub(FOCUS_HEAD, FOCUS_ROWS[0], 2, "the first strategy field, never Start", "Start"),
        what='write "Start" in the builders\' Initial focus cell',
        rule="initial focus is the first strategy field, never Start (BQ-9)",
    ),
    M(
        "M-33",
        "G-FOCUS",
        cell_sub(FOCUS_HEAD, "SCR-069, OCO half", 3, "yes", "no"),
        what='write "no" in SCR-069\'s Trap cell',
        rule="a modal traps focus (BQ-9)",
    ),
    M(
        "M-34",
        "G-ESC",
        say(MONITOR_HEAD, "`Esc` cancels the run."),
        what='write "`Esc` cancels the run." in §5.3',
        rule="`Esc` never cancels a run",
    ),
    M(
        "M-35",
        "G-KEYS",
        say(KH, "This review proposes a new global key for Pause."),
        what='write "This review proposes a new global key for Pause." in §5.4',
        rule="no new global key (BQ-23)",
    ),
    M(
        "M-36",
        "G-KEYS",
        say(KH, "The Positions keys are excluded from the Algos tab."),
        what='write "The Positions keys are excluded from the Algos tab." in §5.4',
        rule="the Positions keys stay live on the Algos tab (the ruling)",
    ),
    M(
        "M-37",
        "G-KEYS",
        cell_sub(KH, "K-12", 6, "C-11", "—"),
        what='write "—" in K-12\'s Resolution cell',
        rule="the live Positions keys resolve by C-11 (the ruling)",
    ),
    M(
        "M-38",
        "G-NAMES",
        cell_sub(NH, "N-21", 5, "Cancel TWAP a_12 on BTCUSDT, Main", "Cancel run"),
        what='write "Cancel run" in N-21\'s Accessible name cell',
        rule='the "Cancel TWAP a_12 on BTCUSDT, Main" pattern (BQ-20)',
    ),
    M(
        "M-39",
        "G-NAMES",
        cell_sub(NH, "N-45", 5, "Adopt into run, order on", "Adopt order into run,"),
        what='write "Adopt order into run, BTCUSDT, Main" in N-45\'s name',
        rule="the visible label leads the name (WCAG 2.5.3)",
    ),
    M(
        "M-40",
        "G-NAMES",
        cell_sub(NH, "N-48", 1, "SCR-070", "SCR-069"),
        what='write "SCR-069" in N-48\'s Screen cell',
        rule="every control the screens draw has its row (BQ-20)",
    ),
    M(
        "M-41",
        "G-CARRIER",
        cell_sub("9.1 The carrier", "CR-05", 4, "✗", "—"),
        what='write "—" in CR-05\'s Glyph cell',
        rule="every treatment keeps its glyph (AC3)",
    ),
    M(
        "M-42",
        "G-CARRIER",
        say(CARRIER_HEAD, "Halted is told by its fill alone."),
        what='write "Halted is told by its fill alone." in §9.1',
        rule="no status by colour alone (R-5)",
    ),
    M(
        "M-43",
        "G-CVD",
        say(CVD_HEAD, "Protanopia renders exist for every board."),
        what='write "Protanopia renders exist for every board." in §9.2',
        rule="the review says which renders do not exist (BQ-26)",
    ),
    M(
        "M-44",
        "G-CVD",
        drop_row(CVD_HEAD, "halted"),
        what="delete §9.2's halted row",
        rule="every treatment computed in four simulations (BQ-26)",
    ),
    M(
        "M-45",
        "G-TRITAN",
        say(CVD_HEAD, "D04's tritan minima stand."),
        what='write "D04\'s tritan minima stand." in §9.2',
        rule="#988's pre-#4652 tritan figures are superseded (G-16)",
    ),
    M(
        "M-46",
        "G-TRITAN",
        line_sub("- **G-16**", "#4652", "the fix"),
        what='write "the fix" for "#4652" in G-16',
        rule="G-16 names #4652 and #988's owner (the ruling)",
    ),
    M(
        "M-47",
        "G-ANNOT",
        rep(
            "`SCR-070/orphan-not-linked`, `SCR-070/orphan-untracked`", "`SCR-070/orphan-not-linked`"
        ),
        what="delete `SCR-070/orphan-untracked` from L-24",
        rule="every merged frame keyed once (BQ-35)",
    ),
    M(
        "M-48",
        "G-ANNOT",
        cell_sub(ANNOT_HEAD, "L-32", 2, D04_PENDING, "D03 04"),
        what='write "D03 04" in L-32\'s Boards cell',
        rule="D04's frames are rows marked PENDING (BQ-35)",
    ),
    M(
        "M-49",
        "G-FROW",
        line_sub("- **R-1", "a status carried by colour alone, ", ""),
        what='delete "a status carried by colour alone, " from R-1',
        rule="colour alone is Blocking (BQ-6; T AC3)",
    ),
    M(
        "M-50",
        "G-FOWNER",
        cell_sub(FH, "F-03", 6, "E33-D03's spec", "the hcl agent's spec"),
        what="write \"the hcl agent's spec\" in F-03's Owner cell",
        rule="an owner is a spec or area, never an agent (BQ-7)",
    ),
    M(
        "M-51",
        "G-CLAUSE",
        cell_sub(CH, "`6.2d`", 3, "at risk", "compliant"),
        what='write "compliant" in the `6.2d` Verdict cell',
        rule="`6.2d` is at risk with F-05 (BQ-19)",
    ),
    M(
        "M-52",
        "G-CLAUSE",
        drop_row(CH, "`3.3.5`"),
        what="delete the `3.3.5` clause row",
        rule="every clause of BQ-5 has a row",
    ),
    M(
        "M-53",
        "G-SC",
        drop_row(SC_HEAD, "2.4.11"),
        what="delete the 2.4.11 row of §4",
        rule="every criterion of BQ-5's cross-walk has a row",
    ),
    M(
        "M-54",
        "G-AROW",
        cell_sub(A_HEAD, "A-02", 3, "best bid / best ask / mid", "best bid / ask"),
        what='write "best bid / ask" in A-02\'s Old cell',
        rule="an Old cell is verbatim at its line (BQ-3)",
    ),
    M(
        "M-55",
        "G-CROWS",
        drop_row(C_HEAD, "C-04"),
        what="delete C-04",
        rule='`14`:1621\'s `role="status"` is a C row (BQ-19)',
    ),
    M(
        "M-56",
        "G-GROWS",
        line_sub("- **G-17**", "2027-01-22", "2027-01-08"),
        what="write E33-D06's sprint start as G-17's due date",
        rule="a G row is due at its consumer's sprint start",
    ),
    M(
        "M-57",
        "G-CONSUMERS",
        rep(
            ", #988 (E33-D04's owner, G-16, C-29, Q-04, F-01's D04:171 occurrence and the D04 rows"
            " of §12)",
            "",
        ),
        what="delete #988 from §18.2's comments",
        rule="the consumer comments at merge (BQ-34)",
    ),
    M(
        "M-58",
        "G-UNBUILT",
        rep("`onboarding`, `session`, ", "`onboarding`, "),
        what="delete `session` from §0's list",
        rule="§0 lists the base's feature slices (the unbuilt statement)",
    ),
    M(
        "M-59",
        "G-UNTOUCHED",
        plan=("05", lambda x: x + "\nedited\n"),
        what="append a line to `05` in the working tree",
        rule="`05` untouched (the ruling's Standing)",
    ),
    M(
        "M-60",
        "G-UNTOUCHED",
        plan=("D03", lambda x: x.replace("Halted", "Stopped", 1)),
        what="change a word of D03 in the working tree",
        rule="D03 untouched, committed or not (the ruling's Standing)",
    ),
    M(
        "M-61",
        "G-UNTOUCHED",
        fork="none",
        what="make `git merge-base HEAD origin/main` unresolvable",
        rule="an unresolved merge-base FAILs, never passes",
    ),
    M(
        "M-62",
        "G-VERSION",
        head=(
            "docs/plan/14-screens-catalogue.md",
            lambda x: x.replace(
                "Peg configuration is a radio group", "Peg configuration is a radio set", 1
            ),
        ),
        what="change `14`:1584 at origin/main",
        rule="a cited line that drifts at origin/main FAILs",
    ),
    M(
        "M-63",
        "G-VERSION",
        head=("packages/ui/tokens/themes.json", lambda x: x + " "),
        what="change `themes.json` at origin/main",
        rule="a whole-file input that drifts at origin/main FAILs",
    ),
    M(
        "M-64",
        "G-CHARSET",
        trailing_space,
        what="write a trailing space after §0's unbuilt line",
        rule="no trailing whitespace, CR or NFKC change (#241 lesson)",
    ),
    M(
        "M-65",
        "G-CHARSET",
        say(MONITOR_HEAD, "The header's Cancel all… is a button."),
        what="write an ellipsis outside a quote in §5.3",
        rule="`…` only inside quotes",
    ),
    M(
        "M-66",
        "G-CELLS",
        rep("| D02 §2, §3; boards", "| D02 §2 | §3; boards"),
        what="write an unescaped pipe into §2's first Evidence cell",
        rule="a row keeps its header's cell count (escaped pipes)",
    ),
    M(
        "M-67",
        "G-ANCHOR",
        sub_in(TARGET_HEAD, "24<!--=GEOM:target.min--> ×", "20<!--=GEOM:target.min--> ×"),
        what="write 20 for the first target size in §5.6",
        rule="every number is the tool's (with a left boundary)",
    ),
    M(
        "M-68",
        "G-CLOSE",
        say(HANDOFF_HEAD, "This " + "closes" + " #989."),
        what="write a closing keyword before the ticket's number in §18.2",
        rule="no closing keyword in the doc; the PR body carries it",
    ),
    M(
        "M-69",
        "G-NOHANDOFF",
        say(HANDOFF_HEAD, "The hand-off file carries the A rows."),
        what='write "The hand-off file carries the A rows." in §18.2',
        rule="no `-handoff.md` (BQ-34)",
    ),
    M(
        "M-70",
        "G-NOHANDOFF",
        extra=("E33-D05-handoff.md",),
        what="place a hand-off file beside the spec",
        rule="no hand-off under any name (BQ-34)",
    ),
    M(
        "M-71",
        "G-AT",
        say(NH, "NVDA reads the grid's caption."),
        what='write "NVDA reads the grid\'s caption." in §7.1',
        rule="nothing claimed as run on a screen reader",
    ),
    M(
        "M-72",
        "G-NODRAW",
        say("0. Status", "Board 05 is redrawn in Penpot."),
        what='write "Board 05 is redrawn in Penpot." in §0',
        rule="no new drawing (BQ-35)",
    ),
    M(
        "M-73",
        "G-SIGNOFF",
        say(DOD_HEAD, "The CDO signed off."),
        what='write "The CDO signed off." in §18.1',
        rule="nothing claims the owner's `approved` (BQ-34)",
    ),
    M(
        "M-74",
        "G-CLOSE-RULE",
        say(FH, "A finding closes when it is fixed in the designs."),
        what='write "A finding closes when it is fixed in the designs." in §13',
        rule="a finding closes routed or accepted (BQ-7)",
    ),
    M(
        "M-75",
        "G-UNMERGED",
        say("0. Status", "E33-D06:12 lists the pack."),
        what="cite an unmerged text by line in §0",
        rule="nothing unmerged is cited or quoted",
    ),
    M(
        "M-76",
        "G-CITE",
        rep("(D02:331)", "(D02:9999)"),
        what="move a D02 cite past the end of D02",
        rule="every cite is in range at the base",
    ),
    M(
        "M-77",
        "G-BUDGET",
        overrun,
        what="append enough lines to pass the line budget",
        rule="the spec stays within {{BUDGET:lines.spec}} lines (BQ-36)",
    ),
    M(
        "M-78",
        "G-SCRIPT",
        in_lines(SCRIPT_HEAD, _drop_feature("SCR-069 OCO builder")),
        what="delete the SCR-069 Feature from §14.3",
        rule="one Feature per screen (BQ-33)",
    ),
    M(
        "M-79",
        "G-SCRIPT",
        rep(LIGHTHOUSE, ""),
        what="delete the Lighthouse step from §14.3",
        rule="every `05` §10 template step is kept (BQ-33)",
    ),
    M(
        "M-80",
        "G-SCRIPT",
        cell_sub(AL_HEAD, "AL-05", 3, "E33-Q05 manual pass", "the owner"),
        what='write "the owner" in AL-05\'s Verifier cell',
        rule="every checklist row names its E33-Q05 verifier",
    ),
    M(
        "M-81",
        "G-SCRIPT",
        row_edit(AL_HEAD, "AL-14", 1, to("the bulk dialog is accessible")),
        what='write "the bulk dialog is accessible" as AL-14\'s check',
        rule="every item objectively checkable (T Test)",
    ),
    M(
        "M-82",
        "G-SCRIPT",
        cell_sub(SR_HEAD, "SR-01", 5, "Q05 scenario 2", "Q05 scenario 3"),
        what='write "Q05 scenario 3" in SR-01\'s Source cell',
        rule="Q05's five scenarios map one to one",
    ),
    M(
        "M-83",
        "G-WALK",
        walk_edit("story: E33-S05 (#1105)", 3, to("17")),
        what="write 17 in the E33-S05 row's Found cell",
        rule="the dry run's counts add up",
    ),
    M(
        "M-84",
        "G-WALK",
        walk_edit("story: E33-S06 (#1106)", 5, lambda c: c.replace("G-18", "G-99")),
        what='write "→ G-99" in the E33-S06 row\'s Disposition cell',
        rule="every → target parses and resolves",
    ),
    M(
        "M-85",
        "G-WALK",
        in_lines(WALK_HEAD, lambda ls: [x for x in ls if "(#988)" not in x]),
        what="delete the E33-D04 role row",
        rule="one role per consumer the review hands to",
    ),
    M(
        "M-86",
        "G-WALK",
        rep("- [x] Story-role dry run", "- [ ] Story-role dry run"),
        what="untick the DoD's dry-run line",
        rule="the DoD tick matches the dry run",
    ),
    M(
        "M-87",
        "G-WALK",
        walk_edit("story: E33-S05 (#1105)", 5, lambda c: c.replace("G-17", "G-16")),
        what='write "→ G-16" in the E33-S05 row\'s Disposition cell',
        rule="a carried not-found names the role's consumer",
    ),
    M(
        "M-88",
        "G-MUTLIST",
        in_lines(MUTATION_HEAD, lambda ls: [x for x in ls if not x.startswith("| G-PENDING ")]),
        what="delete the G-PENDING row from §15",
        rule="§15 lists the tool's mutations, one to one",
    ),
    M(
        "M-89",
        "G-TARGET",
        say(TARGET_HEAD, "The essential exception covers the row checkboxes."),
        what='write "The essential exception covers the row checkboxes." in §5.6',
        rule="no essential exception is used (BQ-28)",
    ),
    M(
        "M-90",
        "G-TARGET",
        sub_in(TARGET_HEAD, "are G-12's, never assumed", "are G-12's, assumed"),
        what='delete "never" before "assumed" in §5.6',
        rule="unstated widths are G rows, never assumed (BQ-28)",
    ),
    M(
        "M-91",
        "G-VERSION",
        head=(
            "docs/plan/14-screens-catalogue.md",
            lambda x: edit_line(x, 1555, "**Validation:**", "**Checks:**"),
        ),
        what="change `14`:1555, a line inside the cited range `14`:1551–1626, at origin/main",
        rule="every line of a cited range is pinned, not its two ends (lens 2)",
    ),
    M(
        "M-92",
        "G-UNTOUCHED",
        staged=("05",),
        what="stage a change to `05` that the working tree reverted",
        rule="the index is read too, not the working tree alone (lens 2)",
    ),
    M(
        "M-93",
        "G-ROUTE",
        cell_sub(RH, "RT-09", 6, PENDING, "in `05`"),
        what='write "in `05`" in RT-09\'s Status cell',
        rule="the post-reconnect summary is BQ-16's PROPOSED set (lens 1)",
    ),
    M(
        "M-94",
        "G-AROW",
        rep("the untracked lockout, the post-reconnect summary;", "the untracked lockout;"),
        what="delete the post-reconnect summary from A-01",
        rule="A-01 lists every class new to `05`, RT-09 included",
    ),
    M(
        "M-95",
        "G-FROWS-RULED",
        cell_sub(
            FH,
            "F-01",
            5,
            "where the row shows",
            "wherever the session is not the run's creator, as",
        ),
        what="widen F-01's replacement to every session that did not create the run",
        rule='F-01 replaces the name only where the row shows "another user" (lens 1)',
    ),
    M(
        "M-96",
        "G-CONSUMERS",
        rep("F-01's D04:171 occurrence and ", ""),
        what="delete F-01's D04:171 occurrence from §18.2's #988 comment",
        rule="#988's owner is told of D04:171 at merge (lens 1)",
    ),
    M(
        "M-97",
        "G-CVD",
        rep("buy against sell (CR-11)", "buy and sell"),
        what="drop the buy and sell pair's label from §9.2",
        rule="CVD is computed over every colour pair (BQ-26)",
    ),
    M(
        "M-98",
        "G-PEG",
        sub_in(PEG_HEAD, '"best bid / best ask / mid"', '"best bid / ask / mid"'),
        what="shorten §5.2's quote of `14`:1584",
        rule="`14`:1584 is quoted verbatim (lens 1)",
    ),
    M(
        "M-99",
        "G-LEAK",
        rep("reason grammar, applied by analogy, forbids", "reason grammar forbids"),
        what='delete "applied by analogy" from §7.2',
        rule="E09-D09:85 governs T2 reasons, applied here by analogy (lens 1)",
    ),
    M(
        "M-100",
        "G-WALK",
        rep(" (added by the orchestrator's standing requirement, not a T DoD item)", ""),
        what="drop the added-row note from the DoD's dry-run line",
        rule="the dry-run line is added, not a T DoD item (lens 1)",
    ),
    M(
        "M-101",
        "G-FROWS-RULED",
        cell_sub(FH, "F-09", 8, "CMP-043 as H21 rules", "`15`:470"),
        what='write "the dialogs follow `15`:470" in F-09\'s Close state cell',
        rule="F-09 closes as H21 rules; DR-14 cited as it reads (lens 1)",
    ),
    M(
        "M-102",
        "G-CROWS",
        cell_sub(C_HEAD, "C-29", 2, "the board is superseded, not redrawn", "the board stands"),
        what='write "the board stands" in C-29\'s Reading cell',
        rule="D03 board 04's glyphs against D04 §3.1 are a C row (lens 3)",
    ),
    M(
        "M-103",
        "G-CROWS",
        drop_row(C_HEAD, "C-30"),
        what="delete C-30",
        rule="AC3's reading is recorded (lens 3)",
    ),
    M(
        "M-104",
        "G-PENDING",
        line_sub("- **Q-04**", "PROPOSED", "taken"),
        what='write "taken" for "PROPOSED" in Q-04',
        rule="Q-04 keeps AC3's alternative and its PROPOSED default",
    ),
    M(
        "M-105",
        "G-ESC",
        cell_sub(
            FOCUS_HEAD,
            FOCUS_ROWS[0],
            5,
            "closes; never cancels a run",
            "closes and ends the run too",
        ),
        what='write "closes and ends the run too" in the builders\' `Esc` cell',
        rule="`Esc` never cancels a run (lens 2 A01)",
    ),
    M(
        "M-106",
        "G-ESC",
        say(MONITOR_HEAD, "Pressing `Esc` in the grid stops the focused run."),
        what='write "Pressing `Esc` in the grid stops the focused run." in §5.3',
        rule="`Esc` never cancels a run (lens 2 A02)",
    ),
    M(
        "M-107",
        "G-DEGRADED",
        sub_in(DEGRADED_HEAD, "assertive once per account", "polite, once per account"),
        what='write "polite" for "assertive" in §8.4\'s account-down line',
        rule="an account going down is assertive once (lens 2 A08)",
    ),
    M(
        "M-108",
        "G-CLAUSE",
        rep(
            'another user\'s run reads "another user"',
            "another user's run shows the creator's own name",
        ),
        what='write "shows the creator\'s own name" in the `T Sec` clause row',
        rule='another user\'s run reads "another user" (lens 2 A14)',
    ),
    M(
        "M-109",
        "G-LEAK",
        rep(
            "no row-level name or description lists actions",
            "a row-level name or description may list its actions",
        ),
        what="let a row-level name list its actions in §7.2",
        rule="no row-level name or description lists actions (lens 2 A16)",
    ),
    M(
        "M-110",
        "G-CARRIER",
        rep("nothing rests on a fill (R-5)", "two states rest on their fill alone (R-5)"),
        what="let two states rest on their fill alone in §9.1",
        rule="nothing rests on a fill (lens 2 A17)",
    ),
    M(
        "M-111",
        "G-TRITAN",
        rep("D04's tritan minima superseded (G-16)", "D04's tritan minima kept as printed (G-16)"),
        what="keep D04's tritan minima as printed in §19",
        rule="#988's pre-#4652 tritan minima are superseded (lens 2 A18)",
    ),
    M(
        "M-112",
        "G-CLOSE-RULE",
        line_sub(
            "- **R-2",
            "A finding closes when it is routed",
            "A finding closes once the designer marks it fixed; it is routed",
        ),
        what="close a finding once the designer marks it fixed in R-2",
        rule="a finding closes routed or accepted (lens 2 A22)",
    ),
    M(
        "M-113",
        "G-CAVEAT",
        sub_in(CAVEAT_HEAD, "never a tooltip", "shown as a tooltip"),
        what='write "shown as a tooltip" for "never a tooltip" in §6.2',
        rule="the caveat is a paragraph, never a tooltip (BQ-11; lens 2 A32)",
    ),
    M(
        "M-114",
        "G-OBSCURED",
        sub_in(
            OBSCURED_HEAD, "keeps a focused control clear of", "lets a focused control sit under"
        ),
        what="let the sticky footer cover a focused control in §5.5",
        rule="a focused control is never under a sticky bar (BQ-31; lens 2 A33)",
    ),
    M(
        "M-115",
        "G-WORDCOUNT",
        say(SUMMARY_HEAD, "Seven surfaces trap focus."),
        what='write "Seven surfaces trap focus." in §19',
        rule="every count is a figure the tool computes (lens 2 A34)",
    ),
    M(
        "M-116",
        "G-WORDCOUNT",
        rep("0<!--=COUNT:clauses.non-compliant--> non-compliant;", "two non-compliant;"),
        what='write "two non-compliant" in §19',
        rule="every count is a figure the tool computes (lens 2 A35)",
    ),
    M(
        "M-117",
        "G-CLAUSE",
        drop_row(CH, "`3.1.2`"),
        what="delete the `3.1.2` clause row",
        rule="every clause of `05` §3 to §7 has a row (lens 3)",
    ),
    M(
        "M-118",
        "G-KEYS",
        cell_sub(KH, "K-16", 2, "expand or collapse its detail", "open it"),
        what='write "open it" in K-16\'s Action cell',
        rule="row detail and sort have key paths (AC2; lens 3)",
    ),
    M(
        "M-119",
        "G-GROWS",
        line_sub("- **G-19**", "`15`:531", "`15`:53"),
        what="drop the `15`:531 cite from G-19",
        rule="G-19 names the unbound row-detail key and where the sort key is bound",
    ),
    M(
        "M-120",
        "G-SCRIPT",
        cell_sub(AL_HEAD, "AL-29", 1, "zero new serious or critical axe-core", "zero axe-core"),
        what='write "zero axe-core violations" in AL-29',
        rule="one axe bar, `05`:247's (lens 3)",
    ),
    M(
        "M-121",
        "G-SCRIPT",
        cell_sub(
            AL_HEAD,
            "AL-27",
            1,
            "every §7.1 name and every value of the frame is present in its card",
            "nothing clipped",
        ),
        what='write "nothing clipped" for AL-27\'s pass condition',
        rule="every item objectively checkable (lens 3)",
    ),
    M(
        "M-122",
        "G-SCRIPT",
        drop_row(AL_HEAD, "AL-33"),
        what="delete AL-33",
        rule="the live Positions keys are checked as shipped (C-11)",
    ),
    M(
        "M-123",
        "G-TARGET",
        line_sub("- **G-12**", "the row checkbox,", "the row checkbox, CMP-008's steppers,"),
        what="list CMP-008's steppers in G-12",
        rule="a width `15`:64 states is not a gap (lens 3)",
    ),
    M(
        "M-124",
        "G-FROWS-RULED",
        cell_sub(FH, "F-06", 4, '"its target algo and effect"', "target and effect only"),
        what="misquote `14`:1621 in F-06's Evidence cell",
        rule="`14`:1621 is quoted as it reads (lens 3)",
    ),
    M(
        "M-125",
        "G-GROWS",
        line_sub("- **G-14**", "not an F row", "a gap"),
        what="drop why G-14 is not an F row",
        rule="G-14 says why it is a gap (lens 3)",
    ),
    M(
        "M-126",
        "G-ANNOT",
        cell_sub(
            ANNOT_HEAD,
            "L-14",
            5,
            "none: no live event; the dialog's open is its role and name (N-24)",
            "—",
        ),
        what='write "—" in L-14\'s Announcements cell',
        rule="an empty announcement cell is written out (AC1; lens 3)",
    ),
    M(
        "M-127",
        "G-HCBAR",
        rep(", button labels included,", ","),
        what='drop "button labels included" from §10',
        rule="the {{BAR:hc}}:1 bar covers all text in high contrast (lens 3)",
    ),
    M(
        "M-128",
        "G-CVD",
        rep('and told apart at least by word" (C-30; Q-04)', '" (C-30; Q-04)'),
        what='drop "told apart at least by word" from §9.2\'s AC3 reading',
        rule="AC3's reading is stated in §9.2 (lens 3)",
    ),
    M(
        "M-129",
        "G-CARRIER",
        rep("which D04 §3.1's glyphs supersede", "which D04 §3.1's glyphs follow"),
        what="drop the supersession of D03 board 04's glyphs in §9.1",
        rule="D04's glyphs supersede the board's (lens 3)",
    ),
    M(
        "M-130",
        "G-KEYS",
        cell_sub(KH, "K-15", 2, "binds, per `05`:187 and `15`:531; D03 silent", "(PROPOSED)"),
        what="mark K-15 PROPOSED again",
        rule="the header sort key is bound by the merged sources, not proposed",
    ),
)
PROBES: tuple[Mutation, ...] = (
    M("P-01", "G-RULED-PIN", sub_in("1.2 Method", "A desk review", "A desk-only review")),
    M("P-02", "G-RULED-PIN", in_lines("2. Inventory", _swap_first_rows)),
    M("N-01", "", sub_in("1.1 What this", "It edits no merged", "It edits  no merged")),
)


# ---------------------------------------------------------------------------- self-test


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


def read_heads() -> tuple[tuple[str, str | None], ...]:
    return tuple((rel, git_show(HEAD, rel)) for rel in PINNED_INPUTS)


def ascii_line(s: str) -> str:
    """ASCII-only output (a cp1252 console never crashes): every other char as \\uXXXX."""
    return s.encode("ascii", "backslashreplace").decode("ascii")


def read_staged(fork: str | None) -> tuple[str, ...]:
    """Untouched ids whose index differs from the merge-base (`git diff --cached`, read-only)."""
    if fork is None:
        return ()
    rels = {cite_path(nn): nn for nn in UNTOUCHED}
    names = git_out("diff", "--cached", "--name-only", fork, "--", *(r for r in rels if r))
    return tuple(rels[n] for n in names.split() if n in rels)


def make_texts(spec: str, values: Values) -> Texts:
    fork = fork_point()
    return Texts(
        spec,
        read_plans(),
        values,
        tuple(other_d05_files()),
        fork,
        read_heads(),
        read_staged(fork),
    )


def selftest(spec: str, paths: tuple[Path, ...]) -> tuple[bool, list[str]]:
    on_disk = digest(paths)
    values = compute(spec)
    spec_f, _ = fill(spec, values)
    values = compute(spec_f)  # frozen at the filled baseline
    base_t = make_texts(spec_f, values)
    base_fails, _notes, _ = audit(base_t, git_fetch)
    lines = [f"baseline (filled in memory): {len(base_fails)} FAIL"]
    lines += [f"  baseline FAIL {x[:160]}" for x in base_fails]
    ok = not base_fails
    probe = fence_pin_probe()
    lines.append(f"  fence probe: {'ok' if not probe else 'FAIL'}")
    lines += [f"    {x}" for x in probe]
    port = cvd_port_problems()
    lines.append(
        f"  CVD port self-test (constants and two pinned inputs): {'ok' if not port else 'FAIL'}"
    )
    ok = ok and not probe and not port
    pristine = digest_texts(spec_f, *(x for _n, x in base_t.plans))
    for mu in (*MUTATIONS, *PROBES):
        s = mu.spec(spec_f) if mu.spec else spec_f
        plans = base_t.plans
        if mu.plan:
            nn, edit = mu.plan
            plans = tuple((k, edit(x) if k == nn else x) for k, x in plans)
        heads = base_t.head_texts
        if mu.head:
            rel, hedit = mu.head
            heads = tuple((r, hedit(x or "") if r == rel else x) for r, x in heads)
        fork = None if mu.fork == "none" else base_t.fork
        extra = mu.extra or base_t.extra_files
        staged = mu.staged or base_t.staged
        changed = (s, plans, heads, fork, extra, staged) != (
            spec_f,
            base_t.plans,
            base_t.head_texts,
            base_t.fork,
            base_t.extra_files,
            base_t.staged,
        )
        if not changed:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        try:
            mt = Texts(s, plans, values, extra, fork, heads, staged)
            fails, _n2, _c = audit(mt, git_fetch)
        except SystemExit as exc:
            fails = [str(exc)]
        new = [x for x in fails if x not in base_fails]
        if mu.gate:
            named = [x for x in new if x.startswith(f"[{mu.gate}]")]
            hit = bool(named) and len(new) == 1
        else:
            named, hit = [], not new
        restored = digest_texts(spec_f, *(x for _n, x in base_t.plans)) == pristine
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
    ap = argparse.ArgumentParser(description="E33-D05 a11y review audit (module docstring)")
    ap.add_argument("--check", nargs="?", const=SPEC_REL, metavar="SPEC", help="audit the spec")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="replace placeholders, then check")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="apply every mutation")
    ap.add_argument("--repin-ruled", action="store_true", help=f"rewrite {RULED_PIN_TXT}")
    args = ap.parse_args(argv)
    spec_path = ROOT / (args.check or SPEC_REL)
    spec = spec_path.read_bytes().decode("utf-8")
    if args.repin_ruled:
        left = PLACEHOLDER.findall(CODE.sub("", spec))
        if left:
            print(f"FAIL --repin-ruled: {len(left)} unfilled placeholders; run --fill first")
            return 1
        t = Texts(spec, (), compute(spec))
        units = ruled_units(t)
        write_text(ROOT / RULED_PIN_TXT, write_pins(units))
        print(f"--repin-ruled: {len(units)} units pinned in {RULED_PIN_TXT}")
        return 0
    if args.self_test:
        paths = (spec_path, ROOT / RULED_PIN_TXT, *(p for _n, p in plan_paths()))
        ok, lines = selftest(spec, paths)
        print("\n".join(lines))
        print(
            f"--self-test: {'ok' if ok else 'FAIL'} - {len(MUTATIONS)} mutations"
            f" + {len(PROBES)} probes in memory"
        )
        return 0 if ok else 1
    values = compute(spec)
    if args.fill:
        spec, unknown = fill(spec, values)
        write_text(spec_path, spec)
        for u in unknown:
            print(f"FAIL --fill: no value for {u}")
        values = compute(spec)
    if args.json and not (args.check or args.fill):
        print(json.dumps({"values": values}, ensure_ascii=True, indent=1))
        return 0
    t = make_texts(spec, values)
    fails, notes, n = audit(t, git_fetch)
    if args.json:
        doc = {"values": values, "fails": fails, "notes": notes, "cites": n}
        print(json.dumps(doc, ensure_ascii=True, indent=1))
    else:
        gates = len(LEXICON_GATES) + len(MEASURED_GATES) + 4
        shown = spec_path.relative_to(ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        out = [f"## E33-D05 audit of {shown} at base {BASE}"]
        out.append(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        out += notes
        out += [f"FAIL {x}" for x in fails] or ["OK - every gate passed"]
        out.append(f"summary: {len(fails)} FAIL, 0 WARN, {len(notes)} NOTE")
        print("\n".join(ascii_line(x) for x in out))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
