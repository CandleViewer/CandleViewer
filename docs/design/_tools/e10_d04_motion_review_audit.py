#!/usr/bin/env python3
"""E10-D04 (#198) audit: the shell's motion contract, reduced motion and a11y design review.

Standalone, offline, stdlib only; runs under `python3 -I` from any directory. It reads AS TEXT at
the pinned base `63b13d034a` (`git show`): the primitive and semantic token JSON, the plan texts
`05`, `06`, `11`, `14`, `15`, `16`, `26`, the ticket JSON (`docs/plan/backlog/E10.json`, and
`E05.json` for one due date), the calendar constants of `docs/plan/backlog/_tools/calendar_cv.py`,
the merged design docs the spec cites, `apps/desktop/src/main/index.ts`, the keymap and the
reserved keys; then this ticket's spec, hand-off and names JSON from the working tree, and the
working-tree copies of the texts this ticket must not touch. E10-D03's tool is read at the base
too, so a later edit to it never changes how D03's names table is parsed.

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: TOK (the seven motion tokens
   and `opacity.scrim` at the base), GEOM (the shell regions from the primitives, the canvas sizes
   at the shipped 1280 x 800 window, the toast stack offsets; gated equal to D03's text), CITE
   (a figure parsed from the cited line, so a quoted budget never drifts from its source),
   CONTRAST (WCAG 2.x over each pair in dark / light / high contrast, rounded to the hundredth as
   E10-D03's tool rounds, cross-checked with D03's figures), COUNT (parsed from the docs' own
   tables and the repo files) and DATE (a consumer's sprint end from the calendar constants).
   `--fill` writes `VALUE<!--=KIND:key-->`; `--check` re-derives every anchored value.
2. **Gates, in order.** Text form first (G-ANCHOR with a left boundary, G-MARKER, G-HEX,
   G-CHARSET, G-CLOSE), then the lexicon gates (rendered clauses: comments stripped, NFKC, markup
   dropped, dashes to spaces, lower case; quoted copy and the mutation list are not claims; a
   negation covers its own term within five words), then the table gates (the transition
   register column by column, the safety rows, the inventory, the `Esc` table, the route, the
   names table against D03 and the JSON, the clause verdicts against `05`, the findings, the rows,
   the hand-off's A-rows, stories and log), then the measured gates (contrast, geometry, cites,
   G-UNTOUCHED against `git merge-base HEAD origin/main`, the line budgets), then the pins.
3. **Pins (G-RULED-PIN).** Whole-document default-deny pins over every unit of the spec and the
   hand-off, in `e10_d04_ruled_pins.txt`: each heading, table row (by its lead cell), rule line and
   prose sentence, by doc, region (heading path plus occurrence `#n`), location and exact text
   (NFKC, whitespace collapsed; anchored values cut out). Each region pins its line shape (one tag
   per line: `.` blank, `h` heading, `t` row, `r` rule, `b` bullet, `n` numbered, `p` prose, a
   sentence count after a prose tag, `>n` for an indent). `--repin-ruled` is the only writer.
   NOTE demotion: when another gate FAILs a section, that section's pin findings print as NOTE.
   The names JSON is pinned too (doc `names`: its key order and every entry's every field, by id)
   and gated field by field (G-NAMES: the table, the key sets, `base`, `spec`, `cmp`, `scr`, each
   template's variables); its pin findings are the spec names section's, for NOTE demotion.
4. **--self-test** applies every mutation of the spec's §20 (M-nn) plus the tool's own X-, P- and
   N- probes and one Y- probe per ruled needle (G-RULES, G-REGCELL: the needle replaced) in
   memory, with the values frozen at the filled baseline; each M-, X-, P- and Y- probe must add
   exactly one FAIL, from the gate it names, an N- probe none; every text is restored
   byte-identically (sha256 in memory and on disk). Output is ASCII.

Usage (from anywhere):
  python3 -I docs/design/_tools/e10_d04_motion_review_audit.py --check [SPEC] [--handoff F]
      [--json] [--fill]
  python3 -I docs/design/_tools/e10_d04_motion_review_audit.py --self-test
  python3 -I docs/design/_tools/e10_d04_motion_review_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
BASE = "63b13d034a"  # every cite was read here (the spec's Inputs line)
HEAD = "origin/main"  # drift is reported against this ref (WARN, never FAIL)
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E10/E10-D04.md"
HAND_REL = "docs/design/E10/E10-D04-handoff.md"
NAMES_REL = "docs/design/E10/E10-D04-names.json"
RULED_PIN_TXT = "docs/design/_tools/e10_d04_ruled_pins.txt"
D03_TOOL_REL = "docs/design/_tools/e10_d03_shell_audit.py"
TOK_REL = "packages/ui/tokens/primitives.tokens.json"
CAL_REL = "docs/plan/backlog/_tools/calendar_cv.py"
CITE_FILES: dict[str, str] = {
    "D02": "docs/design/E10/E10-D02.md",
    "D03": "docs/design/E10/E10-D03.md",
    "FO": "docs/design/E05/E05-D02-feedback-overlays.md",
    "TOK": TOK_REL,
    "CSS": "packages/ui/src/theme/theme.css",
    "STORE": "packages/ui/src/theme/store.ts",
    "PRE": "packages/ui/src/theme/prepaint.ts",
    "KM": "apps/web/src/keymap/keymap.json",
    "KH": "apps/web/src/keymap/KeymapHost.tsx",
    "RK": "apps/web/src/keymap/reserved-keys.json",
    "VAL": "apps/web/src/keymap/validate.ts",
    "MAIN": "apps/desktop/src/main/index.ts",
    "BL": "docs/plan/backlog/E10.json",
}
UNTOUCHED: tuple[str, ...] = (
    "05",
    "06",
    "14",
    "15",
    "16",
    CITE_FILES["D02"],
    CITE_FILES["D03"],
    CITE_FILES["KM"],
    CITE_FILES["RK"],
)
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SPEC_LINE_BUDGET = 600  # standing condition: the spec within about 600 lines
HAND_LINE_BUDGET = 150  # the hand-off within about 150

RULING_ID = "6433315840"
BQ_LIST_ID = "6433027016"
RULED_IDS = (RULING_ID, BQ_LIST_ID)
CONSUMERS = ("#304", "#305", "#306", "#302", "#303")

# ---- the regexes shared by the gates
PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
FIGURE = re.compile(
    r"(?<![\w.,:#/>{-])(\d+(?:[.,]\d+)*)\s?(ms|s|hz|px|%|:1)(?![\w])", re.IGNORECASE
)
CITE_ALIAS = r"D0[23]|FO|TOK|CSS|STORE|PRE|KM|KH|RK|VAL|MAIN|BL|E\d\d-D\d\d"
CITE_GROUP = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:" + CITE_ALIAS + r")\b)) ?"
    r":(?P<first>\d+(?:[–-]\d+)?)(?P<more>(?:(?:\s*\([^()\n]*\))?,\s*:\d+(?:[–-]\d+)?)*)"
)
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]|\bpenpot\.[a-z0-9-]+\.[a-z]{2,}", re.IGNORECASE)
COMMENT_ID = re.compile(r"(?<![\w-])(\d{8,})(?![\w-])")
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


@functools.lru_cache(maxsize=1)
def plan_listing() -> str:
    return git_out("ls-tree", "--name-only", BASE, "docs/plan/")


def plan_rel(nn: str) -> str | None:
    names = [n for n in plan_listing().split("\n") if n.startswith(f"docs/plan/{nn}-")]
    return min(names) if names else None


def cite_path(cid: str) -> str | None:
    if re.fullmatch(r"\d{2}", cid):
        return plan_rel(cid)
    if cid in CITE_FILES:
        return CITE_FILES[cid]
    m = re.fullmatch(r"(E\d{2})-D\d{2}(?:-handoff)?", cid)
    if m:
        return f"docs/design/{m[1]}/{cid}.md"
    return None


def untouched_rel(key: str) -> str:
    rel = plan_rel(key) if re.fullmatch(r"\d{2}", key) else key
    if rel is None:
        raise SystemExit(f"FAIL parse: docs/plan/{key}-* missing at {BASE}")
    return rel


def grab(pattern: str, text: str, what: str) -> str:
    """The first group of `pattern` in `text`; a parse FAIL when it is absent."""
    m = re.search(pattern, text)
    if not m:
        raise SystemExit(f"FAIL parse: {what} not found ({pattern})")
    return m[1]


def base_line(cid: str, n: int) -> str:
    rel = cite_path(cid)
    lines = at_base(rel).split("\n") if rel else []
    if not 1 <= n <= len(lines):
        raise SystemExit(f"FAIL parse: {cid}:{n} is not a line at {BASE}")
    return lines[n - 1]


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
    """For each line, whether it is a fence line or inside a fenced block (kind and length read
    from the marker; only a marker of the same kind, at least as long, closes it)."""
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


def rows_led(block: str, lead: str) -> list[list[str]]:
    """The table rows of `block` whose lead cell matches the regex `lead`."""
    return [r for r in table_rows(block) if re.fullmatch(lead, r[0].strip("`"))]


def row_key(cell: str) -> str:
    k = re.sub(r"[*_`]", "", cell).strip()
    return re.sub(r"^([A-Za-z]+)\s+(\d+)$", r"\1-\2", k)


def pin_norm(text: str) -> str:
    """The exact text, NFKC with whitespace collapsed (Prettier's table padding is not a change)."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sec_id(heading: str) -> str:
    """A section key: the first three words of its rendered heading (anchors dropped)."""
    text = PLACEHOLDER.sub(" ", strip_comments(heading)).lstrip("# ")
    return " ".join(pin_norm(text).split()[:3]) or "(top)"


def h2_of(text: str, head: str) -> str:
    """The section key (an `#` or `##` heading) of the heading that starts with `head`."""
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
    """The section key (an `#` or `##` heading) of 1-based line `line_no`."""
    cur = "(top)"
    lines = text.split("\n")
    fence = fenced(lines)
    for i, ln in enumerate(lines[:line_no]):
        m = HEADING.match(ln)
        if m and not fence[i] and len(m[1]) <= 2:
            cur = sec_id(m[2])
    return cur


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


def flat(text: str) -> str:
    """NFKC, curly quotes straightened, whitespace collapsed (verbatim comparisons)."""
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return " ".join(t.split())


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


def live(clause: str, term: str) -> bool:
    """`term` asserted in `clause` once every negated mention is removed. A negation covers its
    own term (at most five words before it) and a list of its terms coordinated after it; a
    double negation asserts its term; a falsity frame inverts what follows it."""
    t = norm_text(unquote(clause))
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


MUTATION_HEAD = "20. The mutation list"  # its rows describe the violations they plant


def lex_units(doc: str, text: str) -> list[LexUnit]:
    """Every unit a lexicon gate reads: each table row (cells joined by " | "), each bullet or
    numbered item, each paragraph and each heading, with its section. The spec's mutation list
    and the hand-off's §C Old cells (verbatim text at the base) are not claims."""
    out: list[LexUnit] = []
    lines = text.split("\n")
    fence = fenced(lines)
    sec, skip, in_c = "(top)", False, False
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
            in_c = doc == "hand" and m[2].startswith("§C")
            if not skip:
                out.append(LexUnit(doc, sec, s))
            continue
        if re.match(r"^\s*\|", ln):
            flush()
            if not is_rule(ln) and not skip:
                cells = split_row(s)
                if in_c and len(cells) > 3:
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
    units: list[LexUnit], term: str, near: str = "", unless: str = ""
) -> list[tuple[str, str, str]]:
    hits: list[tuple[str, str, str]] = []
    for u in units:
        for c in clauses(u.text):
            scope = norm_text(unquote(c))
            if near and not re.search(near, scope):
                continue
            if unless and re.search(unless, norm_text(c)):
                continue
            if live(c, term):
                hits.append((norm_text(c)[:70], u.doc, u.sec))
    return hits


# ---------------------------------------------------------------------------- tokens and colour


@functools.lru_cache(maxsize=8)
def token_file(name: str) -> dict[str, object]:
    data = json.loads(at_base(f"packages/ui/tokens/{name}.tokens.json"))
    return {k: v.get("$value") for k, v in data.items() if isinstance(v, dict)}


@functools.lru_cache(maxsize=4)
def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        merged.update(token_file(f))
    return merged


def resolve(tokens: dict[str, object], name: str) -> object:
    if name not in tokens:
        raise SystemExit(f"FAIL token {name} is not a token at {BASE}")
    value, hops = tokens[name], 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1], "MISSING"), hops + 1
    return value


def hex_of(theme: str, name: str) -> str:
    v = resolve(load_theme(theme), name)
    if not isinstance(v, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
        raise SystemExit(f"FAIL token {name} does not resolve to an opaque colour ({v})")
    return v.upper()


def px(name: str) -> int:
    v = resolve(load_theme("dark"), name)
    return int(str(v))


def srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex6: str) -> float:
    h = hex6.lstrip("#")
    r, g, b = (srgb_to_linear(int(h[i : i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


# (key, fg, bg, role, D03 cite or "") — the pairs spec §18 relies on
PAIRS: tuple[tuple[str, str, str, str, str], ...] = (
    ("ring-raised", "color.focus.ring", "color.surface.raised", "ui", "D03:259"),
    ("ring-selected", "color.focus.ring", "color.surface.selected", "ui", "D03:259"),
    ("ring-overlay", "color.focus.ring", "color.surface.overlay", "ui", ""),
    ("primary-overlay", "color.text.primary", "color.surface.overlay", "text", "D03:268"),
    ("primary-raised", "color.text.primary", "color.surface.raised", "badge", "D03:183"),
    ("secondary-raised", "color.text.secondary", "color.surface.raised", "text", "D03:192"),
    ("live-raised", "color.env.live", "color.surface.raised", "ui", "D03:184"),
    ("demo-raised", "color.env.demo", "color.surface.raised", "ui", "D03:185"),
)
ROLE_BAR = {"text": "05.text-min", "ui": "05.ui-min", "badge": "05.badge-min"}
BAR_OVERRIDE: list[float] = []  # a self-test lever: raises every bar


def ratio_grid() -> dict[str, dict[str, float]]:
    return {
        k: {t: contrast(hex_of(t, fg), hex_of(t, bg)) for t in THEMES}
        for k, fg, bg, _r, _c in PAIRS
    }


# ---------------------------------------------------------------------------- values

MOTION_TOKENS = (
    "motion.duration.instant",
    "motion.duration.fast",
    "motion.duration.normal",
    "motion.duration.slow",
    "motion.easing.standard",
    "motion.easing.decelerate",
    "motion.easing.accelerate",
)


def num(x: object) -> str:
    f = float(str(x))
    return str(int(f)) if f == int(f) else str(f)


def tok_values() -> Values:
    prim = token_file("primitives")
    v: Values = {}
    for name in MOTION_TOKENS:
        raw = prim[name]
        key = "TOK:" + name.removeprefix("motion.")
        if isinstance(raw, list):
            v[key] = ", ".join(num(x) for x in raw)
        else:
            v[key] = str(raw).removesuffix("ms")
    v["TOK:opacity.scrim"] = num(prim["opacity.scrim"])
    return v


# (key, cite id, line, regex): a figure the docs quote, parsed from its source line at the base
CITE_FIGURES: tuple[tuple[str, str, int, str], ...] = (
    ("t.perf-ms", "BL", 107, r"more than (\d+) ms of main-thread scripting"),
    ("05.pause-s", "05", 207, r"lasting >(\d+)s"),
    ("05.flash-hz", "05", 208, r"more than (\d+) times per second"),
    ("05.polite-s", "05", 147, r"1 update / (\d+)s"),
    ("05.text-min", "05", 125, r"≥(\d+(?:\.\d+)?):1"),
    ("05.ui-min", "05", 126, r"≥(\d+(?:\.\d+)?):1"),
    ("05.badge-min", "05", 127, r"≥(\d+(?:\.\d+)?):1"),
    ("14.rail-ms", "14", 329, r"<=(\d+) ms"),
    ("14.cheat-ms", "14", 370, r"<=(\d+) ms"),
    ("14.route-ms", "14", 87, r"route transition ≤(\d+) ms"),
    ("d02.hz", "D02", 250, r"≤ (\d+) Hz"),
    ("d03.slow-s", "D03", 324, r"SLOW_BOOT_THRESHOLD_MS` (\d+) 000 ms"),
    ("d03.toast-s", "D03", 293, r"\| (\d+) s \(`17`"),
    ("d03.target-px", "D03", 652, r"Hit targets ≥ (\d+) px compact"),
    ("d03.zoom-pct", "D03", 486, r"(\d+) % zoom"),
    ("e09d08.spin-ms", "E09-D08", 87, r"period of \*\*(\d+) ms"),
    ("e40.drawer-from", "E40-D02", 1237, r"`translateX` (\d+) % → 0"),
    ("e40.rise", "E40-D02", 1232, r"`translateY` (\d+) px"),
    ("e30.rise", "E30-D04", 547, r"\((\d+) px translate\)"),
    ("e42.hover-ms", "E42-D04", 570, r"hover after (\d+) ms"),
)


def cite_values() -> Values:
    v: Values = {}
    for key, cid, n, rx in CITE_FIGURES:
        m = re.search(rx, base_line(cid, n))
        if not m:
            raise SystemExit(f"FAIL parse: {cid}:{n} lacks {rx}")
        v[f"CITE:{key}"] = m[1]
    return v


def geom_values() -> Values:
    """The shell regions from the primitives (E10-D03 §2.1's derivation) at the shipped window."""
    main = at_base(CITE_FILES["MAIN"])
    vw = int(grab(r"width: (\d+),", main, "MAIN width"))  # MAIN:186-187
    vh = int(grab(r"height: (\d+),", main, "MAIN height"))
    d02 = at_base(CITE_FILES["D02"]).split("\n")[64]
    rail_x = int(grab(r"\*\*NavRail\*\* w (\d+)", d02, "D02:65 NavRail"))
    drawer = int(grab(r"\*\*RightRail\*\* w (\d+)", d02, "D02:65 RightRail"))
    launcher = int(grab(r"the (\d+) px launcher", base_line("D03", 122), "D03:122 launcher"))
    s1, s2, s3, s4 = (px(f"space.{n}") for n in (1, 2, 3, 4))
    ctl = px("size.control.comfortable")
    row_c, row_k = px("size.row.compact"), px("size.row.comfortable")
    topbar = ctl + 2 * s2 + row_k
    status = ctl + 2 * s2
    banner_c, banner_k = row_c + 2 * s1, row_k + 2 * s1
    rail_c = ctl + 2 * s4
    strip = launcher + 2 * s1
    canvas_h = vh - topbar - status
    g = {
        "topbar": topbar,
        "statusbar": status,
        "banner.compact": banner_c,
        "banner.comfortable": banner_k,
        "rail.collapsed": rail_c,
        "rail.expanded": rail_x,
        "rail.travel": rail_x - rail_c,
        "strip": strip,
        "drawer": drawer,
        "drawer.panel": drawer - strip,
        "canvas.w.collapsed": vw - rail_c - strip,
        "canvas.w.expanded": vw - rail_x - strip,
        "canvas.w.drawer": vw - rail_c - drawer,
        "canvas.w.both": vw - rail_x - drawer,
        "canvas.h": canvas_h,
        "canvas.h.banner": canvas_h - banner_c,
        "stack.compact-1": s2,
        "stack.compact-2": 2 * s2,
        "stack.comfortable-1": s3,
        "stack.comfortable-2": 2 * s3,
        "stack.lift": px("space.inset.md") + px("size.icon"),
    }
    return {f"GEOM:{k}": str(x) for k, x in g.items()}


def contrast_values() -> Values:
    v: Values = {}
    for k, row in ratio_grid().items():
        for t, r in row.items():
            v[f"CONTRAST:{k}.{t}"] = f"{r:.2f}"
    return v


@functools.lru_cache(maxsize=1)
def calendar() -> tuple[datetime.date, int]:
    """SPRINT01_START and SPRINT_DAYS read from calendar_cv.py at the base (never executed)."""
    text = at_base(CAL_REL)
    start = grab(r"SPRINT01_START = datetime\.date\((\d+, \d+, \d+)\)", text, "the start")
    y, mo, d = (int(x) for x in start.split(", "))
    days = int(grab(r"SPRINT_DAYS = (\d+)", text, "SPRINT_DAYS"))
    return datetime.date(y, mo, d), days


def sprint_of(key: str) -> str:
    epic = key.split("-")[0]
    data = json.loads(at_base(f"docs/plan/backlog/{epic}.json"))
    for t in data:
        if t.get("key") == key:
            return str(t.get("sprint"))
    raise SystemExit(f"FAIL parse: {key} not in {epic}.json")


def due(key: str) -> str:
    start, days = calendar()
    n = int(grab(r"(\d+)", sprint_of(key), f"{key}'s sprint"))
    end = start + datetime.timedelta(days=(n - 1) * days + days - 1)
    return end.isoformat()


DATE_KEYS = ("E10-S01", "E10-S02", "E10-S04", "E10-Q03", "E10-T02", "E05-D03")


@functools.lru_cache(maxsize=1)
def d03_tool() -> ModuleType:
    """E10-D03's audit tool AT THE BASE, loaded as a module (never copied): its table helpers
    read D03's names, so a working-tree edit to that tool cannot change the parse."""
    name = "e10_d03_shell_audit_at_base"
    mod = ModuleType(name)
    mod.__file__ = str(ROOT / D03_TOOL_REL)
    sys.modules[name] = mod
    # S102: the code run is this repo's own merged tool, read with `git show` at the pinned base
    exec(compile(at_base(D03_TOOL_REL), D03_TOOL_REL, "exec"), mod.__dict__)  # noqa: S102
    return mod


@functools.lru_cache(maxsize=1)
def d03_names() -> tuple[tuple[str, str, str, str], ...]:
    """D03 §10.2's rows at the base: (element, role, name cell, source), via E10-D03's tool."""
    mod = d03_tool()
    block = mod.section(
        at_base(CITE_FILES["D03"]), "### 10.2 Names", "Names marked PROPOSED are E10-D04's"
    )
    out = []
    for ln in mod.table_rows(block):
        cells = split_row(ln)
        if len(cells) == 4 and cells[0] != "Element":
            out.append((cells[0], cells[1], cells[2], cells[3]))
    return tuple(out)


def count_values(spec: str, hand: str) -> Values:
    reg = register(spec)
    names = names_rows(spec)
    cl = clause_rows(spec)
    fr = finding_rows(spec)
    status = [n["Review"].split(" ")[0].rstrip(";") for n in names]
    verdicts = [c[3] for c in cl]
    sev = [f[1] for f in fr]
    d03 = at_base(CITE_FILES["D03"])
    km = at_base(CITE_FILES["KM"])
    c = {
        "boards": len(re.findall(r"(?m)^- `\d\d [a-z0-9-]+` — board id", d03)),
        "register.rows": len(reg),
        "register.animated": sum(1 for r in reg if animated(r)),
        "register.cuts": sum(1 for r in reg if not animated(r)),
        "names.d03": len(d03_names()),
        "names.rows": len(names),
        "names.cited": status.count("cited"),
        "names.confirmed": status.count("confirmed"),
        "names.rewritten": status.count("rewritten"),
        "names.open": status.count("open"),
        "clauses.total": len(cl),
        "clauses.compliant": verdicts.count("compliant"),
        "clauses.at-risk": verdicts.count("at risk"),
        "clauses.non-compliant": verdicts.count("non-compliant"),
        "clauses.out-of-scope": verdicts.count("out of scope"),
        "clauses.routed": sum(1 for x in verdicts if x.startswith("not yet decidable")),
        "f.rows": len(fr),
        "f.blocking": sev.count("Blocking"),
        "f.major": sev.count("Major"),
        "f.minor": sev.count("Minor"),
        "f.info": sev.count("Info"),
        "rk.keys": len(json.loads(at_base(CITE_FILES["RK"]))),
        "km.overrides": km.count('"reservedOverride"'),
    }
    del hand
    return {f"COUNT:{k}": str(x) for k, x in c.items()}


@functools.lru_cache(maxsize=4)
def compute_cached(spec: str, hand: str) -> tuple[tuple[str, str], ...]:
    v: Values = {}
    v |= tok_values()
    v |= cite_values()
    v |= geom_values()
    v |= contrast_values()
    v |= count_values(spec, hand)
    v |= {f"DATE:{k}": due(k) for k in DATE_KEYS}
    return tuple(sorted(v.items()))


def compute(spec: str, hand: str) -> Values:
    return dict(compute_cached(spec, hand))


# ---------------------------------------------------------------------------- fill and anchors


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


FILLED = re.compile(r"(?<![\w.])(\d[\d.,\- ]*\d|\d)<!--=([A-Z]+:[^>]+?)-->")


def unfill(text: str) -> str:
    """Every anchored value back to its placeholder, so `--fill` refreshes a value that moved."""
    return FILLED.sub(lambda m: "{{" + m[2] + "}}", text)


def code_spans(line: str) -> list[tuple[int, int]]:
    return [c.span() for c in CODE.finditer(line)]


def bare_figures(text: str, values: Values) -> list[tuple[int, str]]:
    """Figures with a unit typed by hand: outside an anchor, a quote and a code span."""
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
    return hits


def g_anchor_doc(doc: str, text: str, values: Values) -> list[Finding]:
    """Every anchor's value is the tool's, with a left boundary (a value is never the tail of a
    longer number or word); no placeholder is left; no figure with a unit is typed by hand."""
    bad: list[Finding] = []
    for i, line in enumerate(text.split("\n"), 1):
        sec = h2_at(text, i)
        for m in PLACEHOLDER.finditer(CODE.sub("", line)):
            bad.append(("G-ANCHOR", f"{doc}:{i} placeholder {{{{{m[1]}}}}} not filled", doc, sec))
        spans = code_spans(line)
        for m in ANCHOR.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue
            want = values.get(m[1])
            head = line[: m.start()]
            if want is None:
                bad.append(("G-ANCHOR", f"{doc}:{i} {m[1]} is not a computed value", doc, sec))
            elif not head.endswith(want):
                got = re.split(r"[ |*(]", head)[-1]
                msg = f"{doc}:{i} {m[1]} reads {got!r}; the tool computes {want!r}"
                bad.append(("G-ANCHOR", msg, doc, sec))
            elif re.search(r"[\w.,]$", head[: len(head) - len(want)]):
                msg = f"{doc}:{i} {m[1]}: the value {want!r} has no left boundary"
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
    """A colour is a token name; no hex is typed (the tool resolves every token)."""
    bad: list[Finding] = []
    for i, line in enumerate(text.split("\n"), 1):
        for m in HEXLIT.finditer(CODE.sub(lambda c: " " * len(c[0]), line)):
            bad.append(("G-HEX", f"{doc}:{i} {m[0]} typed by hand", doc, h2_at(text, i)))
    return bad


def odd_char(c: str) -> bool:
    """NFKC-unstable, or a control, format, private, unassigned or separator character other
    than the ASCII space (TAB, form feed, U+1680, U+2028, a soft hyphen, a zero-width joiner)."""
    if unicodedata.normalize("NFKC", c) != c:
        return True
    cat = unicodedata.category(c)
    return cat in ("Cc", "Cf", "Co", "Cn", "Cs", "Zl", "Zp") or (cat == "Zs" and c != " ")


def g_charset_doc(doc: str, text: str) -> list[Finding]:
    """No character whose NFKC form differs and no control, format or separator character but
    the space and the line feed; no CR, no trailing whitespace (the #241 lesson)."""
    bad: list[Finding] = []
    for i, line in enumerate(text.split("\n"), 1):
        sec = h2_at(text, i)
        odd = sorted({c for c in line if c != "\r" and odd_char(c)})
        if odd:
            names = ", ".join(f"U+{ord(c):04X}" for c in odd)
            bad.append(("G-CHARSET", f"{doc}:{i} NFKC-unstable {names}", doc, sec))
        if "\r" in line:
            bad.append(("G-CHARSET", f"{doc}:{i} a carriage return", doc, sec))
        elif line != line.rstrip():
            bad.append(("G-CHARSET", f"{doc}:{i} trailing whitespace", doc, sec))
    return bad


def g_close_doc(doc: str, text: str) -> list[Finding]:
    """No closing keyword before an issue number in either doc (a text PR closes nothing)."""
    return [
        ("G-CLOSE", f"{doc}:{i} {m[0]!r}", doc, h2_at(text, i))
        for i, line in enumerate(text.split("\n"), 1)
        for m in CLOSING.finditer(line)
    ]


# ---------------------------------------------------------------------------- cites


def cite_findings(docs: dict[str, str], fetch: Fetch) -> tuple[list[Finding], list[str], int]:
    """Every `file`:line cite is in range and non-blank at the base (FAIL), unchanged at
    origin/main (WARN); every figure source line and every D03 geometry fragment holds."""
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
                if m["a"] and not re.fullmatch(r"\d{2}|E\d\d-D\d\d(?:-handoff)?", cid):
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
    return fails, warns, len(done)


# ---------------------------------------------------------------------------- the texts


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    names: str  # the names JSON
    plans: tuple[tuple[str, str], ...]  # the working-tree copies of UNTOUCHED
    values: Values = field(default_factory=dict)


@functools.lru_cache(maxsize=64)
def lex_cached(doc: str, text: str) -> tuple[LexUnit, ...]:
    return tuple(lex_units(doc, text))


def lex(t: Texts) -> list[LexUnit]:
    return [*lex_cached("spec", t.spec), *lex_cached("hand", t.hand)]


def F(tag: str, msg: str, doc: str | None, sec: str | None) -> Finding:
    return (tag, msg, doc, sec)


def lexicon(
    tag: str, what: str, term: str, near: str = "", unless: str = "", doc: str = ""
) -> Callable[[Texts], list[Finding]]:
    def run(t: Texts) -> list[Finding]:
        units = [u for u in lex(t) if not doc or u.doc == doc]
        hits = claims(units, term, near=near, unless=unless)
        return [F(tag, f"{what}: {h[0]!r}", h[1], h[2]) for h in hits]

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
        return [F(tag, f"§{head[:20]} lacks {n!r}", doc, sec) for n in needles if n not in body]

    return run


def both(*gates: Callable[[Texts], list[Finding]]) -> Callable[[Texts], list[Finding]]:
    def run(t: Texts) -> list[Finding]:
        return [x for gate in gates for x in gate(t)]

    return run


# ---------------------------------------------------------------------------- the tables

REG_HEAD = "4. The transition register"
REG_COLS = (
    "Row",
    "Surface",
    "Trigger",
    "Property",
    "Token pair",
    "Reduce",
    "Carrier",
    "Layout",
    "Source",
)
SAFETY_HEAD = "6.1 Safety rows"
ESC_HEAD = "13.2"
ROUTE_HEAD = "13.1"
NAMES_HEAD = "16. The accessible-name table"
NAME_COLS = ("Id", "D03 element", "Role / ARIA", "Name", "Source", "Review")
CLAUSE_HEAD = "17.1 The clauses"
F_HEAD = "19.2 Findings"
ROWS_HEAD = "19. Rows"


def register(spec: str) -> list[dict[str, str]]:
    return [
        dict(zip(REG_COLS, r, strict=False)) for r in rows_led(section(spec, REG_HEAD), r"T-\d\d")
    ]


ANIMATES = re.compile(r"\bopacity\b|\btransform\b")


def animated(r: dict[str, str]) -> bool:
    return ANIMATES.search(norm_text(r.get("Property", ""))) is not None


def names_rows(spec: str) -> list[dict[str, str]]:
    rows = rows_led(section(spec, NAMES_HEAD), r"(?:shell|window)\.[a-z0-9.]+")
    return [dict(zip(NAME_COLS, r, strict=False)) for r in rows]


CLAUSES: tuple[str, ...] = (
    *("3.1.1", "3.1.2", "3.1.3", "3.1.4", "3.1.5", "3.1.6", "3.1.7", "3.2"),
    *("3.3.1", "3.3.2", "3.3.3", "3.3.4", "3.3.5", "3.3.6"),
    *("3.4.1", "3.4.2", "3.4.3", "3.4.4", "3.4.5", "3.4.6a", "3.4.6b", "3.4.7", "3.4.8"),
    *("3.4.9", "3.4.10", "4.1", "4.2", "4.3", "4.4"),
    *("5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7"),
    *("6.1", "6.2a", "6.2b", "6.2c", "6.2d", "6.3", "6.4a", "6.5a"),
    *("7.1", "7.2a", "7.2b", "7.3", "7.4"),
)
VERDICTS = (
    "compliant",
    "at risk",
    "non-compliant",
    "out of scope",
    "not yet decidable, routed to E10-Q03",
)
SEVERITIES = ("Blocking", "Major", "Minor", "Info")


def clause_rows(spec: str) -> list[list[str]]:
    return rows_led(section(spec, CLAUSE_HEAD), r"\d\.\d(?:\.\d+)?[a-d]?")


def finding_rows(spec: str) -> list[list[str]]:
    return rows_led(section(spec, F_HEAD), r"F-\d\d")


def row_ids(spec: str) -> set[str]:
    """Every C-, F-, G-, Q- and H- id the spec defines (a row's lead or a bold bullet)."""
    block = section(spec, ROWS_HEAD)
    ids = {r[0] for r in table_rows(block) if re.fullmatch(r"[CF]-\d\d", r[0])}
    ids |= set(re.findall(r"(?m)^- \*\*([GQH]-\d\d)\*\*", block))
    return ids


# ---------------------------------------------------------------------------- the register gates

FORBIDDEN_PROP = re.compile(r"\b(?:width|height|top|left|box shadow|filter|backdrop|scal\w*)\b")
ALLOWED_PROP = re.compile(r"\bopacity\b|\btransform\b|\bpresence\b|\btext swap\b|\bos owned\b")
TOKEN_NAME = re.compile(r"`(motion\.[a-z0-9.-]+)`")
GROW = ("T-01", "T-03", "T-17", "T-24")
SHRINK = ("T-02", "T-04", "T-18", "T-19")
LAYOUTS = ("frame 0", "last frame", "none")
CUT_ROWS = (
    *("T-05", "T-09", "T-12", "T-17", "T-18", "T-20", "T-21", "T-22", "T-24", "T-25", "T-27"),
)
LOOP_ROWS = ("T-28",)  # the request-bound spinner: a CSS animation whose period is not a token


def reg_sec(t: Texts) -> str:
    return h2_of(t.spec, REG_HEAD)


def g_prop(t: Texts) -> list[Finding]:
    """R-1: a Property cell names only `opacity`, `transform`, presence or a text swap."""
    bad = []
    for r in register(t.spec):
        cell = norm_text(r.get("Property", ""))
        if FORBIDDEN_PROP.search(cell.replace("pointer events", "")):
            bad.append(
                F("G-PROP", f"{r['Row']} animates a layout or paint property", "spec", reg_sec(t))
            )
        elif not ALLOWED_PROP.search(cell):
            bad.append(F("G-PROP", f"{r['Row']} names no allowed property", "spec", reg_sec(t)))
    return bad


def g_token(t: Texts) -> list[Finding]:
    """BQ-5: shipped tokens only; an animated row a duration and an easing; a cut instant."""
    bad = []
    for r in register(t.spec):
        cell = r.get("Token pair", "")
        names = TOKEN_NAME.findall(cell)
        unknown = [n for n in names if n not in MOTION_TOKENS]
        durs = [n for n in names if n.startswith("motion.duration.")]
        eases = [n for n in names if n.startswith("motion.easing.")]
        why = ""
        if r["Row"] in LOOP_ROWS:
            if names or "not a token" not in norm_text(cell):
                why = "is the spinner yet names a token or does not say its period is not one"
        elif unknown:
            why = f"names a non-token {unknown[0]}"
        elif "motion.duration.slow" in durs:
            why = "uses `slow`"
        elif animated(r) and not (set(durs) - {"motion.duration.instant"} and eases):
            why = "animates without a duration and an easing"
        elif not animated(r) and (eases or set(durs) != {"motion.duration.instant"}):
            why = "is a cut not on `motion.duration.instant` alone"
        if why:
            bad.append(F("G-TOKEN", f"{r['Row']} {why}", "spec", reg_sec(t)))
    return bad


REDUCE_BAD = re.compile(
    r"\bshort\w*|\bfaster\b|\bfad\w*|\bslid\w*|\bscal\w*|\bcross\b"
    r"|motion\.duration\.(?:fast|normal|slow)"
)


def g_reduce(t: Texts) -> list[Finding]:
    """R-3 / T AC2: every twin is instant; never shorter, a fade or a slide."""
    bad = []
    for r in register(t.spec):
        cell = norm_text(r.get("Reduce", ""))
        if "instant" not in cell or REDUCE_BAD.search(cell):
            bad.append(F("G-REDUCE", f"{r['Row']} reduce twin {cell[:40]!r}", "spec", reg_sec(t)))
    return bad


def g_carrier(t: Texts) -> list[Finding]:
    """BQ-18: every row names the carrier a reduce user reads."""
    return [
        F("G-CARRIER", f"{r['Row']} has no carrier", "spec", reg_sec(t))
        for r in register(t.spec)
        if norm_text(r.get("Carrier", "")) in ("", "—", "none")
    ]


def g_layout(t: Texts) -> list[Finding]:
    """R-2: frame 0 when the chrome grows, the last frame when it shrinks, else none."""
    bad = []
    for r in register(t.spec):
        cell = norm_text(r.get("Layout", ""))
        want = "frame 0" if r["Row"] in GROW else "last frame" if r["Row"] in SHRINK else None
        if cell not in LAYOUTS or (want and cell != want):
            bad.append(F("G-LAYOUT", f"{r['Row']} layout {cell!r}", "spec", reg_sec(t)))
    return bad


INVENTORY = (
    r"rail expand",
    r"rail collapse",
    r"drawer open",
    r"drawer close",
    r"drawer switch",
    r"toast enter",
    r"toast exit",
    r"toast stack shift",
    r"toast overflow",
    r"palette open",
    r"palette close",
    r"cheatsheet",
    r"menus",
    r"tooltips",
    r"blocking dialog open",
    r"blocking dialog close",
    r"banner enter",
    r"safety banner clear",
    r"informational banner dismiss",
    r"error boundary swap",
    r"boot",
    r"scr 159 pages",
    r"view as",
    r"environment switch",
    r"floating window",
    r"tree group",
    r"spinner",
)


def g_inventory(t: Texts) -> list[Finding]:
    """BQ-4: every animated element D03 names (H1's pairs, §5.4, §7) has a register row."""
    surf = " | ".join(norm_text(r.get("Surface", "")) for r in register(t.spec))
    return [
        F("G-INVENTORY", f"no register row for {need!r}", "spec", reg_sec(t))
        for need in INVENTORY
        if not re.search(need, surf)
    ]


def g_cut(t: Texts) -> list[Finding]:
    """BQ-11, BQ-13, BQ-14: the cut rows never fade, slide or translate."""
    bad = []
    for r in register(t.spec):
        if r["Row"] in CUT_ROWS and live(
            r.get("Property", ""),
            r"\bfad\w*|\bslid\w*|\btranslat\w*|\bscal\w*|\bnormal\b|\bfast\b",
        ):
            bad.append(F("G-CUT", f"{r['Row']} is a cut that moves", "spec", reg_sec(t)))
    return bad


SAFETY_SIGNALS = (
    r"env badge",
    r"unconfirmed",
    r"disconnected banner",
    r"frozen banner",
    r"lockout panel",
    r"t2 lock",
    r"kill switch line",
)


SAFETY_AT_ONCE = re.compile(r"\bin the frame\b|\bin one frame\b|\bnever transitions\b|\bat 0 ms\b")
SAFETY_LATE = re.compile(
    r"\b(?:once|after|until|settl\w*|wait\w*|then|following|later|before|delay\w*|lag\w*)\b"
)


def g_safety(t: Texts) -> list[Finding]:
    """BQ-12 / T Sec: every safety signal has an instant row; nothing in §6 animates it."""
    block = section(t.spec, SAFETY_HEAD)
    sec = h2_of(t.spec, SAFETY_HEAD)
    rows = rows_led(block, r"S-\d\d")
    sig = " | ".join(norm_text(r[1]) for r in rows)
    bad = [
        F("G-SAFETY", f"no safety row for {s!r}", "spec", sec)
        for s in SAFETY_SIGNALS
        if not re.search(s, sig)
    ]
    if "motion.duration.instant` in both modes" not in block:
        bad.append(F("G-SAFETY", "§6.1 lacks the instant rule", "spec", sec))
    for r in rows:
        rule = norm_text(r[2]) if len(r) > 2 else ""
        if not SAFETY_AT_ONCE.search(rule) or SAFETY_LATE.search(rule):
            bad.append(
                F("G-SAFETY", f"{r[0]} is not applied in the frame it is known", "spec", sec)
            )
    term = r"\b(?:fad(?:e|es|ed|ing)|slid(?:e|es|ing)|animat\w*|transitions?|tween\w*|delay\w*)\b"
    units = lex_units("spec", block)
    bad += [
        F("G-SAFETY", f"a safety signal moves: {h[0]!r}", "spec", sec) for h in claims(units, term)
    ]
    return bad


# ---------------------------------------------------------------------------- keyboard and names

ESC_OVERLAYS = (
    "palette",
    "cheatsheet",
    "rightrail drawer",
    "context menu",
    "menus",
    "tooltip",
    "toast",
    "scr 157",
    "scr 156",
)


def g_esc(t: Texts) -> list[Finding]:
    """BQ-14 / BQ-22: one `Esc` row per overlay; SCR-157's is Continue read-only."""
    block = section(t.spec, ESC_HEAD)
    sec = h2_of(t.spec, ESC_HEAD)
    rows = [r for r in table_rows(block) if len(r) >= 4]
    leads = " | ".join(norm_text(r[0]) for r in rows)
    bad = [
        F("G-ESC", f"no `Esc` row for {o!r}", "spec", sec) for o in ESC_OVERLAYS if o not in leads
    ]
    for r in rows:
        if "scr 157" in norm_text(r[0]) and (
            norm_text(r[1]) != "continue read only" or "search trigger" not in norm_text(r[2])
        ):
            bad.append(F("G-ESC", "SCR-157's `Esc` is not Continue read-only", "spec", sec))
        if norm_text(r[1]) in ("", "—") and "no overlay" not in norm_text(r[1]):
            bad.append(F("G-ESC", f"{r[0]!r} has no `Esc` action", "spec", sec))
    bad += [
        F("G-ESC", f"`Esc` inert: {h[0]!r}", h[1], h[2])
        for h in claims(lex(t), r"\besc (?:does nothing|is inert|is ignored|changes nothing)\b")
    ]
    return bad


ROUTE_SPLIT = re.compile(r"\s*→\s*")


def route_of(text: str) -> list[str]:
    return [norm_text(re.sub(r"\([^)]*\)", "", x)) for x in ROUTE_SPLIT.split(text)]


def g_route(t: Texts) -> list[Finding]:
    """BQ-22: the documented route is D02:254's, in the spec and the hand-off's test hooks."""
    d02 = base_line("D02", 254).split(": ", 1)[1].rstrip(".")
    want = route_of(d02)
    bad = []
    m = re.search(r"\*\*([^*]+)\*\*", section(t.spec, ROUTE_HEAD))
    if not m or route_of(m[1]) != want:
        bad.append(
            F("G-ROUTE", "§13.1's route is not D02:254's", "spec", h2_of(t.spec, ROUTE_HEAD))
        )
    line = next((ln for ln in t.hand.split("\n") if "The keyboard route, verbatim" in ln), "")
    got = re.search(r"E10-Q03: (.*?) \(D02:254\)", line)
    if not got or route_of(got[1]) != want:
        bad.append(F("G-ROUTE", "§E's route is not D02:254's", "hand", h2_of(t.hand, "§E")))
    return bad


def quoted_names(cell: str) -> list[str]:
    return [flat(q) for q in re.findall(r'"([^"]+)"', cell)]


TEMPLATE_FILL = re.compile(r"\\\{[a-z]+\\\}")
TEMPLATE_VAR = re.compile(r"\{([a-z]+)\}")
# every templated name and its variables (D03 §10.2's examples; the toast's per FO:1838)
TEMPLATES: dict[str, tuple[str, ...]] = {
    "shell.navrail.item": ("count",),
    "shell.navrail.item.collapsed": ("count", "key"),
    "shell.rightrail.launcher": ("count",),
    "shell.toast.dismiss": ("title",),
    "shell.toast.overflow": ("count",),
    "window.titlebar.close": ("kind", "symbol", "environment"),
}
JSON_TOP = ("$schema", "base", "spec", "names")
JSON_KEYS = (
    *("id", "element", "cmp", "scr", "role", "name", "template", "source", "status", "finding"),
)
# the screen each id prefix lives on (D03 §10.2's grouping); the default is SCR-010
SCR_OF: tuple[tuple[str, str], ...] = (
    ("shell.navrail.", "SCR-011"),
    ("shell.toast.", "SCR-015"),
    ("shell.cheatsheet.", "SCR-013"),
    ("shell.palette.", "SCR-012"),
    ("shell.scr157.", "SCR-157"),
    ("shell.scr156.", "SCR-156"),
    ("window.", "SCR-027"),
)


# the host component each id prefix must list (D03 §2's regions)
CMP_OF: tuple[tuple[str, str], ...] = (
    ("shell.navrail.", "CMP-071"),
    ("shell.rightrail.", "CMP-209"),
    ("shell.statusbar.region", "CMP-208"),
    ("shell.statusbar.latency", "CMP-208"),
    ("shell.statusbar.killswitch", "CMP-208"),
    ("shell.toast.overflow", "CMP-212"),
    ("shell.scr157.", "CMP-043"),
    ("shell.scr156.", "CMP-091"),
    ("shell.env.", "CMP-074"),
)


@functools.lru_cache(maxsize=1)
def base_sha() -> str:
    return git_out("rev-parse", BASE).strip()


def json_problems(doc: object, rows: list[dict[str, str]]) -> list[str]:
    """The JSON's own fields: its key sets, `base`, `spec`, each entry's `cmp`, `scr` and
    template (the variables named in TEMPLATES, the name a literal fill of it)."""
    if not isinstance(doc, dict):
        return ["the names JSON is not an object"]
    bad: list[str] = []
    if tuple(doc) != JSON_TOP:
        bad.append(f"the JSON's top keys are {list(doc)}")
    if doc.get("base") != base_sha():
        bad.append("the JSON's base is not the pinned base")
    if doc.get("spec") != SPEC_REL:
        bad.append("the JSON's spec is not this spec")
    cells = {r["Id"]: r["D03 element"] + " " + r["Role / ARIA"] for r in rows}
    for e in doc.get("names") or []:
        if not isinstance(e, dict):
            bad.append("a JSON entry is not an object")
            continue
        rid = str(e.get("id"))
        if tuple(e) != JSON_KEYS:
            bad.append(f"JSON {rid} keys {list(e)}")
        cmp = e.get("cmp")
        named = set(re.findall(r"CMP-\d{3}", cells.get(rid, "")))
        named |= {c for p, c in CMP_OF if rid.startswith(p)}
        if (
            not isinstance(cmp, list)
            or not all(isinstance(c, str) and re.fullmatch(r"CMP-\d{3}", c) for c in cmp)
            or len(set(cmp)) != len(cmp)
            or not named <= set(cmp)
            or (rid in ICON_ONLY and not cmp)
        ):
            bad.append(f"JSON {rid}.cmp {cmp!r}")
        want_scr = next((s for p, s in SCR_OF if rid.startswith(p)), "SCR-010")
        if e.get("scr") != want_scr:
            bad.append(f"JSON {rid}.scr {e.get('scr')!r} is not {want_scr}")
        tpl, name = e.get("template"), e.get("name")
        if rid in TEMPLATES:
            ok = (
                isinstance(tpl, str)
                and isinstance(name, str)
                and sorted(TEMPLATE_VAR.findall(tpl)) == sorted(TEMPLATES[rid])
                and re.fullmatch(TEMPLATE_FILL.sub(".+", re.escape(tpl)), name) is not None
            )
            if not ok:
                bad.append(f"JSON {rid}.template {tpl!r} lacks its variables or its fill")
        elif tpl is not None:
            bad.append(f"JSON {rid}.template is set on an untemplated name")
    return bad


ICON_ONLY = (
    "shell.topbar.overflow",
    "shell.rightrail.launcher",
    "shell.rightrail.launcher.other",
    "shell.toast.dismiss",
    "shell.navrail.item.collapsed",
    "shell.navrail.toggle.collapse",
    "shell.navrail.toggle.expand",
    "window.titlebar.more",
    "window.titlebar.close",
)


def g_names(t: Texts) -> list[Finding]:
    """BQ-25 / T AC3: the table = D03 §10.2's rows plus the review's rows = the JSON."""
    sec = h2_of(t.spec, NAMES_HEAD)
    rows = names_rows(t.spec)
    bad: list[str] = []
    by_el: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_el.setdefault(flat(r["D03 element"]), []).append(r)
    for el, _role, name_cell, src in d03_names():
        mine = by_el.get(flat(el))
        if not mine:
            bad.append(f"D03 row {el[:30]!r} missing")
            continue
        want = set(quoted_names(name_cell))
        kept = {flat(r["Name"].strip('"')) for r in mine if not r["Review"].startswith("rewritten")}
        for r in mine:
            if r["Review"].startswith("rewritten") and not want & set(quoted_names(r["Review"])):
                bad.append(f"{r['Id']} rewritten without quoting D03's name")
        if kept and kept != want:
            bad.append(f"{mine[0]['Id']} names differ from D03")
        if "PROPOSED" in src and any(r["Review"].startswith("cited") for r in mine):
            bad.append(f"{mine[0]['Id']} is PROPOSED in D03 yet only cited")
    ids = row_ids(t.spec)
    for r in rows:
        status = r["Review"].split(" ")[0].rstrip(";")
        fid = re.findall(r"F-\d\d", r["Review"])
        if (r["Name"] == "—") != (status == "open"):
            bad.append(f"{r['Id']} name {r['Name'][:20]!r} vs status {status!r}")
        if status in ("open", "rewritten") and not (fid and fid[0] in ids):
            bad.append(f"{r['Id']} {status} without a finding")
    have = {r["Id"] for r in rows}
    bad += [f"icon-only control {i} has no row" for i in ICON_ONLY if i not in have]
    try:
        doc = json.loads(t.names)
        entries = doc["names"]
        if doc.get("$schema") != "cv.a11y-names.v1":
            bad.append("the JSON's $schema is not cv.a11y-names.v1")
    except (ValueError, KeyError, TypeError):
        entries = []
        bad.append("the names JSON does not parse")
    if [e.get("id") for e in entries if isinstance(e, dict)] != [r["Id"] for r in rows]:
        bad.append("the JSON's ids differ from the table's")
    try:
        bad += json_problems(json.loads(t.names), rows)
    except ValueError:
        pass
    for e, r in zip([x for x in entries if isinstance(x, dict)], rows, strict=False):
        name = None if r["Name"] == "—" else flat(r["Name"].strip('"'))
        fid = re.findall(r"F-\d\d", r["Review"])
        want_e = {
            "element": flat(r["D03 element"]),
            "role": flat(r["Role / ARIA"].replace("`", "")),
            "name": name,
            "source": flat(r["Source"]),
            "status": r["Review"].split(" ")[0].rstrip(";"),
            "finding": fid[0] if fid else None,
        }
        for k, v in want_e.items():
            got = e.get(k)
            if (flat(got) if isinstance(got, str) else got) != v:
                bad.append(f"JSON {r['Id']}.{k} differs from the table")
    return [F("G-NAMES", "; ".join(bad[:4]), "spec", sec)] if bad else []


# ---------------------------------------------------------------------------- the review gates


def g_clause(t: Texts) -> list[Finding]:
    """BQ-21: every clause once, its requirement quoted verbatim from `05`, a verdict from the
    scale, a severity from the scale; an at-risk row names its finding, owner and target."""
    sec = h2_of(t.spec, CLAUSE_HEAD)
    rows = clause_rows(t.spec)
    lines05 = at_base(untouched_rel("05")).split("\n")
    ids = row_ids(t.spec)
    by_clause: dict[str, list[list[str]]] = {}
    for f in finding_rows(t.spec):
        if len(f) > 2 and any(s == f[1] for s in SEVERITIES):
            by_clause.setdefault(f[2].strip("`"), []).append(f)
    bad: list[str] = []
    seen = [r[0].strip("`") for r in rows]
    bad += [f"clause {c} missing" for c in CLAUSES if c not in seen]
    bad += [
        f"clause {c} repeated or unknown" for c in seen if seen.count(c) > 1 or c not in CLAUSES
    ]
    for r in rows:
        cid = r[0].strip("`")
        if len(r) < 8:
            bad.append(f"clause {cid}: {len(r)} cells")
            continue
        m = re.search(r"`05`:(\d+)", r[1])
        quotes = re.findall(r'"([^"]+)"', r[1].replace('\\"', "'"))
        if not m or not quotes:
            bad.append(f"clause {cid}: no quote and `05` line")
        elif not all(flat(q) in flat(lines05[int(m[1]) - 1]) for q in quotes):
            bad.append(f"clause {cid}: the quote is not `05`:{m[1]}")
        if r[3] not in VERDICTS:
            bad.append(f"clause {cid}: verdict {r[3]!r}")
        if r[4] not in (*SEVERITIES, "—"):
            bad.append(f"clause {cid}: severity {r[4]!r}")
        named = re.findall(r"[CFGQH]-\d\d", r[5])
        if r[3] in ("at risk", "non-compliant") and (
            not named or any(n not in ids for n in named) or "—" in (r[6], r[7])
        ):
            bad.append(f"clause {cid}: {r[3]} without a finding, owner and target")
        if r[3] in ("at risk", "non-compliant") and r[4] not in SEVERITIES:
            bad.append(f"clause {cid}: {r[3]} without a severity")
        mine = by_clause.get(cid, [])
        gaps = [g for g, c in GAP_CLAUSE.items() if c == cid and g in ids]
        if (gaps or named) and r[3] not in ("at risk", "non-compliant"):
            bad.append(f"clause {cid} is {r[3]} yet names or owes {named or gaps}")
        if any(g not in named for g in gaps):
            bad.append(f"clause {cid} does not name its gap {gaps}")
        if mine and r[3] not in ("at risk", "non-compliant"):
            bad.append(f"clause {cid} is {r[3]} yet {', '.join(f[0] for f in mine)} name it")
        elif mine:
            missing = [f[0] for f in mine if f[0] not in named]
            worst = SEVERITIES[min(SEVERITIES.index(f[1]) for f in mine if f[1] in SEVERITIES)]
            if missing:
                bad.append(f"clause {cid} does not name {missing}")
            if r[4] != worst:
                bad.append(f"clause {cid}: severity {r[4]!r}, its worst finding is {worst}")
    return [F("G-CLAUSE", "; ".join(bad[:4]), "spec", sec)] if bad else []


# the G-rows that hold a clause at risk (spec §17.1): the clause row must name them
GAP_CLAUSE = {"G-01": "7.4", "G-03": "3.2", "G-04": "3.4.1", "G-07": "7.3"}


AGENT = re.compile(r"worker|agent|claude|session|\bhcl\b|\bhpe\b|orchestrator", re.IGNORECASE)


def g_finding(t: Texts) -> list[Finding]:
    """BQ-21: each F-row one severity from the scale, one lane owner (never an agent), one
    target, a clause from the list and a board as evidence."""
    sec = h2_of(t.spec, F_HEAD)
    bad = []
    for r in finding_rows(t.spec):
        why = ""
        if len(r) < 8:
            why = "lacks cells"
        elif r[1] not in SEVERITIES:
            why = f"severity {r[1]!r}"
        elif r[2].strip("`") not in CLAUSES:
            why = f"clause {r[2]!r}"
        elif AGENT.search(r[5]) or not re.search(r"\(`area/[a-z-]+`\)", r[5]):
            why = f"owner {r[5]!r} is not a lane"
        elif r[6] in ("", "—") or "board" not in r[7]:
            why = "no target or no board evidence"
        if why:
            bad.append(F("G-FINDING", f"{r[0]} {why}", "spec", sec))
    return bad


REQUIRED_ROWS: dict[str, tuple[str, ...]] = {
    "C-01": ("E15-D14",),
    "C-02": ("PROPOSED",),
    "C-04": ("instant",),
    "C-05": ("cut",),
    "C-06": ("one frame",),
    "C-08": ("D03:309", "Continue read-only"),
    "C-10": ("instant",),
    "C-14": ("never tokens",),
    "C-17": ("D03:152", "PROPOSED"),
    "G-01": ("E05-D03",),
    "G-02": ("E10-T02",),
    "G-03": ("Ctrl+Shift+M", "E10-S02"),
    "G-04": ("Ctrl+\\", "E10-S02"),
    "G-05": ("E10-S01",),
    "G-06": ("CMP-165",),
    "G-07": ("event.repeat", "E10-S02"),
}


def g_rows(t: Texts) -> list[Finding]:
    """BQ-28 and the G-rows the ruling names: each present with its reading."""
    block = section(t.spec, ROWS_HEAD)
    sec = h2_of(t.spec, ROWS_HEAD)
    bad = []
    for rid, needles in REQUIRED_ROWS.items():
        line = next(
            (ln for ln in block.split("\n") if ln.startswith((f"| {rid} ", f"- **{rid}**"))), ""
        )
        if not line or not all(n in line for n in needles):
            bad.append(F("G-ROWS", f"{rid} missing or lacks {needles}", "spec", sec))
    return bad


g_sr = both(
    lexicon(
        "G-SR",
        "a screen-reader run",
        r"\b(?:tested|ran|run|verified|observed|checked|passed)\b(?: \w+){0,3} "
        r"(?:with|on|in|using|under) (?:nvda|jaws|voiceover|narrator|a screen reader)\b"
        r"|\bscreen reader (?:pass|test|run)\w* (?:was |were )?(?:run|done|passed|completed)\b",
    ),
    require("G-SR", "1.2 Method", ("nothing was run on a screen reader",)),
)


def g_flash(t: Texts) -> list[Finding]:
    """BQ-17: every flash candidate is "not a flash"; no rate cell counts flashes."""
    block = section(t.spec, "11. Flash")
    sec = h2_of(t.spec, "11. Flash")
    bad = []
    rows3 = [r for r in table_rows(block) if len(r) == 3]
    for r in rows3:
        if r[2] != "not a flash" or re.search(r"\bflash\w*", norm_text(r[1])):
            bad.append(F("G-FLASH", f"{r[0][:30]!r} is a flash", "spec", sec))
    if not any("auto repeat" in norm_text(r[0]) and "event.repeat" in r[1] for r in rows3):
        bad.append(F("G-FLASH", "§11 lacks the held toggle (key auto-repeat) row", "spec", sec))
    bad += [
        F("G-FLASH", f"a flash asserted: {h[0]!r}", h[1], h[2])
        for h in claims(lex(t), r"(?<!three )\bflash(?:es|ed|ing)\b|\bblinks? twice\b")
    ]
    return bad


# ---------------------------------------------------------------------------- the hand-off gates

AROWS: dict[str, str] = {
    "A-01": "`14`",
    "A-02": "`14`:406",
    "A-03": "`15`:2491",
    "A-04": "`15`:2521",
    "A-05": "`15`:622",
    "A-06": "`16`:178",
    "A-07": "`16`:180",
    "A-08": "`05`:98",
    "A-09": "`05`:102",
    "A-10": "`06`",
}


def unwrap(cell: str) -> str:
    return cell.strip().removeprefix("“").removesuffix("”").replace("\\|", "|")


def g_arow(t: Texts) -> list[Finding]:
    """BQ-3: every A-row with its file, its owner and an Old cell verbatim at the base."""
    block = section(t.hand, "§C")
    sec = h2_of(t.hand, "§C")
    rows = {r[0]: r for r in rows_led(block, r"A-\d\d")}
    bad = []
    for aid, where in AROWS.items():
        r = rows.get(aid)
        if not r or len(r) < 5 or where not in r[1] or r[4] in ("", "—"):
            bad.append(F("G-AROW", f"{aid} missing or incomplete", "hand", sec))
            continue
        m = re.search(r"`(\d\d)`:(\d+)", r[1])
        if r[2] != "—" and m:
            line = at_base(untouched_rel(m[1])).split("\n")[int(m[2]) - 1]
            if flat(unwrap(r[2])) not in flat(line):
                bad.append(F("G-AROW", f"{aid}'s Old is not `{m[1]}`:{m[2]}", "hand", sec))
    return bad


STORIES = ("CMP-070", "CMP-071", "CMP-209", "CMP-059", "CMP-043", "CMP-212")


def g_story(t: Texts) -> list[Finding]:
    """BQ-26: a `ReducedMotion` story wherever a row animates, each with data-motion="reduce"."""
    body = section(t.hand, "§D")
    sec = h2_of(t.hand, "§D")
    bad = [
        F("G-STORY", f"no ReducedMotion story for {c}", "hand", sec)
        for c in STORIES
        if c not in body
    ]
    if "`ReducedMotion`" not in body or 'data-motion="reduce"' not in body:
        bad.append(F("G-STORY", "§D lacks the ReducedMotion form", "hand", sec))
    return bad


g_walk = both(
    lexicon(
        "G-WALK",
        "a fabricated attendance or quote",
        r"\battended\b|\battendees\b|\bparticipants?\b|\bsaid that\b|\bwas held\b",
        doc="hand",
    ),
    require("G-WALK", "§F", ("written protocol", "acknowledgement comment"), doc="hand"),
)


def g_due(t: Texts) -> list[Finding]:
    """BQ-26 / T AC4: every open F-, G- and Q- row is in the log with a lane owner and the
    consumer's sprint end as its due date."""
    sec = h2_of(t.hand, "§F")
    rows = {r[0]: r for r in rows_led(section(t.hand, "§F"), r"[FGQ]-\d\d")}
    open_ids = {i for i in row_ids(t.spec) if i[0] in "FGQ"}
    bad = [F("G-DUE", f"{i} is not in the log", "hand", sec) for i in sorted(open_ids - set(rows))]
    for rid, r in rows.items():
        if len(r) < 5:
            bad.append(F("G-DUE", f"{rid} lacks cells", "hand", sec))
            continue
        key = re.match(r"([A-Z]\d\d-[A-Z]\d\d)", r[3])
        due_key = ANCHOR.search(r[4]) or PLACEHOLDER.search(r[4])
        if (
            AGENT.search(r[2])
            or not re.search(r"area/|#\d+", r[2])
            or not key
            or not due_key
            or due_key[1] != f"DATE:{key[1]}"
        ):
            bad.append(F("G-DUE", f"{rid}'s owner or due date", "hand", sec))
    return bad


# ---------------------------------------------------------------------------- the status gates


def g_unbuilt(t: Texts) -> list[Finding]:
    """BQ-1 / BQ-26: the body states the shell is unbuilt and names the consumers."""
    body = section(t.spec, "0. Status")
    sec = h2_of(t.spec, "0. Status")
    needles = (
        "**The shell is unbuilt.**",
        "this spec is the implementation contract",
        *CONSUMERS,
        "E10-T02",
        "E05-D03 (#162)",
    )
    return [F("G-UNBUILT", f"§0 lacks {n!r}", "spec", sec) for n in needles if n not in body]


def g_proposed(t: Texts) -> list[Finding]:
    """BQ-6 confirmed as PROPOSED: §5's heading, its first sentence and the RULED section say so;
    no item is routed to the owner's queue."""
    bad = []
    sec = h2_of(t.spec, "5. One layout")
    body = section(t.spec, "5. One layout")
    first = section(t.spec, "5.1 The rule").split("\n")[2] if body else ""
    if "(BQ-6, PROPOSED)" not in body.split("\n")[0] or not first.startswith("PROPOSED"):
        bad.append(F("G-PROPOSED", "§5 does not mark BQ-6 PROPOSED", "spec", sec))
    if "**BQ-6** as PROPOSED" not in section(t.spec, "The twenty-eight"):
        bad.append(F("G-PROPOSED", "the RULED section", "spec", h2_of(t.spec, "The twenty-eight")))
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        if "#2701" in text:
            bad.append(F("G-PROPOSED", f"the {doc} routes an item to #2701", doc, None))
    return bad


g_pending = both(
    lexicon(
        "G-PENDING",
        "the owner's approval as given",
        r"\b(?:approved|accepted|signed off) by the owner\b"
        r"|\bthe owner (?:has )?(?:approved|accepted)\b",
    ),
    lambda t: (
        []
        if "**Owner approval pending**" in t.spec.split("\n## ")[0]
        else [F("G-PENDING", "the status line lacks 'Owner approval pending'", "spec", "(top)")]
    ),
)


def g_ruled(t: Texts) -> list[Finding]:
    """The RULED heading cites the ruling on the list; every comment id is one of the two."""
    bad = []
    head = next((ln for ln in t.spec.split("\n") if ln.startswith("## The twenty-eight")), "")
    if f"comment {RULING_ID}, on the BQ list {BQ_LIST_ID}" not in head:
        bad.append(F("G-RULED", "the RULED heading does not cite the ruling", "spec", sec_id(head)))
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            for cid in COMMENT_ID.findall(line):
                if cid not in RULED_IDS:
                    bad.append(F("G-RULED", f"{cid} is not the ruling", doc, h2_at(text, i)))
    return bad


def g_penpot(t: Texts) -> list[Finding]:
    """BQ-27: the Penpot page by name and id only; no URL or host."""
    return [
        F("G-PENPOT", f"{doc}:{i} a URL or host", doc, h2_at(text, i))
        for doc, text in (("spec", t.spec), ("hand", t.hand))
        for i, ln in enumerate(text.split("\n"), 1)
        if URL.search(CODE.sub(" ", ln))
    ]


# ---------------------------------------------------------------------------- lexicon gates

g_layoutprop = lexicon(
    "G-LAYOUTPROP",
    "a layout property animated",
    r"\b(?:animat\w*|transition\w*|tween\w*) (?:the |its |a )?(?:width|height|top|left)\b"
    r"|\b(?:width|height) (?:animat\w*|transition\w*|tween\w*)\b",
)
g_card = lexicon(
    "G-CARD",
    "a dialog card that fades or scales",
    r"\bcards? (?:\S+ ){0,3}?(?:fades?|scales?|slides?|rises?|animates?|grows?) in\b"
    r"|\bscal\w* ?(?:and|\+) ?fad\w*|\bfad\w* ?(?:and|\+) ?scal\w*",
)
g_source = lexicon(
    "G-SOURCE",
    "a component reading the media query",
    r"\breads? (?:the )?(?:media query|prefers reduced motion)\b|\bper component reduce\b",
)
LOOP_TERM = r"\bpuls\w*|\bloops?\b|\blooping\b|\bshak\w*|\bblink\w*|\bthrob\w*"
# the one allowed loop (R-7, T-28), cut out of a unit before G-LOOP reads it, so a pulse beside it
# in the same clause still FAILs
SPINNER_OK = re.compile(
    r"(?:\bthe one loop is |\bloops? but )?\bSCR-150['’]s (?:request-bound |boot )?spinner\b"
)


def g_loop(t: Texts) -> list[Finding]:
    """BQ-17: nothing loops, pulses or blinks but SCR-150's request-bound spinner."""
    units = [LexUnit(u.doc, u.sec, SPINNER_OK.sub(" ", u.text)) for u in lex(t)]
    return [
        F("G-LOOP", f"a loop or attention motion: {h[0]!r}", h[1], h[2])
        for h in claims(units, LOOP_TERM)
    ]


g_perf = lexicon(
    "G-PERF",
    "script-driven animation",
    r"\brequestanimationframe\b|\braf\b|\bjs driven\b|\bscript driven\b",
)
g_oracle = lexicon(
    "G-ORACLE",
    "motion that differs by role",
    r"\b(?:fad(?:e|es|ed|ing)|slid(?:e|es|ing)|animat\w*|transition\w*)\b",
    near=r"\b(?:manager|viewer|owner|role|permission)s?\b",
)
g_scrim = lexicon(
    "G-SCRIM",
    "a scrim over the ENV badge",
    r"\b(?:covers?|dims?|darken\w*|fogs?|hides?|obscures?|veils?)\b(?:\s+\S+){0,4}?\s+"
    r"(?:the |a |its |every )?(?:env |environment )?badges?\b"
    r"|\bbadges? (?:sits? )?(?:under|beneath|behind) (?:a |the )?scrim\b",
    near=r"\bscrims?\b",
)
g_newtoken = lexicon(
    "G-NEWTOKEN",
    "a named pair as a token",
    r"\btokens?\b(?! map)",
    near=r"motion\.(?:drawer|toast|slide|fast)\b",
)
g_short = lexicon(
    "G-REDUCE",
    "a reduce twin that only shortens",
    r"\bshorten(?:s|ed|ing)?\b|\b(?:shorter|faster|halved|reduced|quick|quicker) "
    r"(?:duration|transition|animation|fade)s?\b|\b(?:sped up|quickened)\b",
    unless=r"\bdefect\b",
)


# ---------------------------------------------------------------------------- ruled sentences

# (doc, section head, needle): each ruled sentence verbatim (NFKC, whitespace collapsed); a
# paraphrase that drops or rewrites one FAILs here even after a re-pin (the #241 lesson)
RULE_NEEDLES: tuple[tuple[str, str, str], ...] = (
    (
        "spec",
        "1.4 Rules",
        (
            "**R-1 Compositor only.** Only `opacity` and `transform` animate; nothing animates "
            "`width`, `height`, `top`, `left`, `box-shadow` or a `filter`"
        ),
    ),
    (
        "spec",
        "1.4 Rules",
        (
            "**R-2 One layout per transition** (PROPOSED, §5): the WorkspaceCanvas takes its end "
            "geometry in exactly one frame and never lays out during a transition's frames."
        ),
    ),
    (
        "spec",
        "1.4 Rules",
        (
            "**R-3 Instant under reduce.** Every reduce twin is the instant end state with its "
            "carrier; a twin that only shortens a duration is a defect"
        ),
    ),
    (
        "spec",
        "1.4 Rules",
        (
            "**R-4 Safety never waits.** A status change is applied in the frame it is known; a "
            "transition follows it, never precedes or delays it"
        ),
    ),
    (
        "spec",
        "1.4 Rules",
        (
            "**R-5 Focus never fades.** A focused control is never inside a fading element; "
            "focus never animates; nothing delays focus or an announcement"
        ),
    ),
    (
        "spec",
        "1.4 Rules",
        (
            "**R-6 No motion oracle.** No duration, easing or transition differs by role, "
            "permission, environment or cause"
        ),
    ),
    (
        "spec",
        "1.4 Rules",
        (
            "**R-7 Nothing loops or flashes.** No chrome transition loops; the one loop is "
            "SCR-150's request-bound spinner (T-28)"
        ),
    ),
    ("spec", "1.4 Rules", "; nothing flashes; nothing else moves on its own for more than"),
    (
        "spec",
        "1.4 Rules",
        (
            "**R-8 One source.** The resolved `data-motion` on the root is the only mode a "
            "component reads"
        ),
    ),
    (
        "spec",
        "1.4 Rules",
        ("no component reads the media query and no component adds its own reduce rule"),
    ),
    ("spec", "1.2 Method", "is filled in the hand-off's §E as E10-Q03's script, never as a result"),
    ("spec", "5.1 The rule", "takes its end geometry in exactly one frame"),
    ("spec", "5.1 The rule", "Under reduce the motion and the layout both happen at frame 0."),
    ("spec", "6.1 Safety", "every scrim stops below the TopBar and above the StatusBar"),
    (
        "spec",
        "6.2 Never",
        (
            "a restored rail (the collapse persisted, D02:248) paints in its end state with no "
            "motion"
        ),
    ),
    (
        "spec",
        "9. The single",
        ("the override `system | on | off` wins over the OS in both directions"),
    ),
    ("spec", "9. The single", "**Mid-flight:** a running transition completes on its own clock"),
    ("spec", "9. The single", "the next one obeys the new mode"),
    ("spec", "10. The substitution", "A reduce user misses a transition, never a state."),
    ("spec", "10. The substitution", "this spec takes T AC2's instant"),
    ("hand", "§E", "the only mode a component reads"),
    ("hand", "§F", "Every row has an owner lane, never an agent"),
)


def g_rules(t: Texts) -> list[Finding]:
    """Each ruled sentence of RULE_NEEDLES is present, verbatim, in its section."""
    bad = []
    for doc, head, needle in RULE_NEEDLES:
        text = t.spec if doc == "spec" else t.hand
        if flat(needle) not in flat(strip_comments(section(text, head))):
            msg = f"§{head[:16]} lacks the ruled {needle[:50]!r}"
            bad.append(F("G-RULES", msg, doc, h2_of(text, head)))
    return bad


# (row, column, needle): the register cells the ruling fixes word for word
REGCELL: tuple[tuple[str, str, str], ...] = (
    ("T-01", "Property", "beside the static"),
    ("T-01", "Carrier", "focus stays on the toggle, outside the moving layer"),
    ("T-02", "Property", "the icon column and the toggle stay"),
    ("T-02", "Carrier", "focus stays on the toggle"),
    ("T-03", "Property", "the content complete at frame 0"),
    ("T-03", "Property", "the strip and its launchers static"),
    ("T-03", "Carrier", "focus stays on the launcher, outside the moving layer"),
    ("T-04", "Carrier", "focus back on the launcher in frame 0"),
    ("T-07", "Trigger", "warning and error never"),
    ("T-07", "Trigger", "paused on hover and focus"),
    ("T-10", "Property", "the card is a cut, painted in the first frame with focus in the input"),
    ("T-11", "Carrier", "focus on the search trigger in frame 0"),
    ("T-15", "Property", "the card is a cut"),
    ("T-16", "Carrier", "focus on the search trigger in frame 0"),
    ("T-19", "Carrier", "else the TopBar's search trigger, in frame 0 (PROPOSED)"),
    ("T-27", "Property", "heights never animate"),
    ("T-28", "Property", "stopped in the frame the phase settles"),
    ("T-28", "Reduce", "a static glyph beside the text"),
)


def g_regcell(t: Texts) -> list[Finding]:
    """The ruled register cells hold their words (a missing row is G-INVENTORY's; an empty
    cell G-CARRIER's)."""
    reg = {r["Row"]: r for r in register(t.spec)}
    bad = []
    for row, col, needle in REGCELL:
        cell = reg.get(row, {}).get(col, "")
        if (
            row in reg
            and norm_text(cell) not in ("", "—")
            and norm_text(needle) not in norm_text(cell)
        ):
            bad.append(F("G-REGCELL", f"{row} {col} lacks {needle!r}", "spec", reg_sec(t)))
    return bad


HEDGE_HEADS: tuple[tuple[str, str], ...] = (
    *(("spec", h) for h in ("1. Purpose", "4. The transition", "5. One layout", "6. What never")),
    *(("spec", h) for h in ("8. Performance", "9. The single", "10. The substitution")),
    *(("spec", h) for h in ("11. Flash", "13. The keyboard", "14. Live regions")),
    *(("hand", h) for h in ("§B", "§D", "§E", "§F")),
)
HEDGE = (
    r"\b(?:may|might|mostly|largely|usually|typically|optionally|ideally|preferably|briefly"
    r"|except|unless)\b|\bwhere it helps\b|\b(?:if|as) needed\b|\bbut for\b"
)


def g_hedge(t: Texts) -> list[Finding]:
    """No permissive modal or exception word in a section that states rules."""
    keys = {(doc, h2_of(t.spec if doc == "spec" else t.hand, h)) for doc, h in HEDGE_HEADS}
    units = [u for u in lex(t) if (u.doc, u.sec) in keys]
    return [F("G-HEDGE", f"a hedge: {h[0]!r}", h[1], h[2]) for h in claims(units, HEDGE)]


LIVE_HEAD = "14. Live regions"


def g_live(t: Texts) -> list[Finding]:
    """BQ-23: the clock and the HealthChips sit outside every region and are never announced;
    the StatusBar's region never announces a value-only change; no throttle per tick."""
    sec = h2_of(t.spec, LIVE_HEAD)
    rows = [r for r in table_rows(section(t.spec, LIVE_HEAD)) if len(r) >= 5]
    bad = []
    for lead in ("the clock", "healthchips"):
        r = next((x for x in rows if norm_text(x[0]).startswith(lead)), None)
        if (
            not r
            or norm_text(r[1]) != "outside every region"
            or norm_text(r[3]) != "never announced"
        ):
            bad.append(F("G-LIVE", f"{lead!r} is announced or inside a region", "spec", sec))
    sb = next((x for x in rows if "statusbar" in norm_text(x[0])), None)
    if not sb or "value only changes never" not in norm_text(sb[3]):
        bad.append(F("G-LIVE", "the StatusBar region announces value-only changes", "spec", sec))
    tick = r"\b(?:each|every|per) (?:second|tick|frame|update|value)\b|\bcontinuous\w*"
    bad += [
        F("G-LIVE", f"{r[0][:24]!r} throttles per tick", "spec", sec)
        for r in rows
        if live(r[3], tick)
    ]
    return bad


TRAVEL = {"T-01": "GEOM:rail.travel", "T-03": "GEOM:drawer.panel", "T-06": "CITE:e40.rise"}


def g_tokval(t: Texts) -> list[Finding]:
    """BQ-5: an anchor's key matches its row: §2's value cells their token, §11's durations the
    T-row's own token, §11's distances the moving element's travel."""
    bad = []
    sec2 = h2_of(t.spec, "2. The tokens")
    for r in table_rows(section(t.spec, "2. The tokens")):
        m = re.fullmatch(r"`((?:motion|opacity)\.[a-z.]+)`", r[0])
        keys = ANCHOR.findall(r[1]) if m and len(r) > 1 else []
        if m and any(k != "TOK:" + m[1].removeprefix("motion.") for k in keys):
            bad.append(F("G-TOKVAL", f"{m[1]}'s value is anchored to {keys}", "spec", sec2))
    reg = {r["Row"]: r for r in register(t.spec)}
    sec11 = h2_of(t.spec, "11. Flash")
    for r in table_rows(section(t.spec, "11. Flash")):
        m = re.search(r"\((T-\d\d)\)", r[0])
        if len(r) != 5 or not m or m[1] not in reg:
            continue
        toks = TOKEN_NAME.findall(reg[m[1]].get("Token pair", ""))
        dur = next((x for x in toks if x.startswith("motion.duration.")), "")
        keys = ANCHOR.findall(r[1] + " " + r[2])
        tok = [k for k in keys if k.startswith("TOK:")]
        geo = sorted({k for k in keys if not k.startswith("TOK:")})
        if dur and tok != ["TOK:" + dur.removeprefix("motion.")]:
            bad.append(F("G-TOKVAL", f"§11 {m[1]}'s duration is {tok}", "spec", sec11))
        if m[1] in TRAVEL and geo != [TRAVEL[m[1]]]:
            bad.append(F("G-TOKVAL", f"§11 {m[1]}'s travel is {geo}", "spec", sec11))
    return bad


g_script = require(
    "G-SCRIPT",
    "§E",
    ("<feature/screen name> =", "<primary task> =", "<nvda|jaws|voiceover> =", "05:261 307"),
    doc="hand",
)


# ---------------------------------------------------------------------------- measured gates


def g_contrast(t: Texts) -> list[Finding]:
    """§18: every pair clears its bar in every theme; D03's figures reproduced."""
    sec = h2_of(t.spec, "18. The contrast")
    bad = []
    grid = ratio_grid()
    for k, _fg, _bg, role, cite in PAIRS:
        bar = float(t.values.get(f"CITE:{ROLE_BAR[role]}", "0"))
        bar = max([bar, *BAR_OVERRIDE])
        low = [th for th, r in grid[k].items() if round(r, 2) < bar]
        if low:
            bad.append(F("G-CONTRAST", f"{k} under {bar}:1 in {low}", "spec", sec))
        if cite:
            line = base_line("D03", int(cite.split(":")[1]))
            miss = [v for v in (f"{grid[k][th]:.2f}" for th in THEMES) if v not in line]
            if miss:
                bad.append(F("G-CONTRAST", f"{k} differs from {cite}: {miss}", "spec", sec))
    return bad


def g_geom(t: Texts) -> list[Finding]:
    """§5.1: the derived canvas sizes equal D03:122's text; the stack offsets equal D03:298's."""
    v = t.values
    d122, d298 = base_line("D03", 122), base_line("D03", 298)
    h = v["GEOM:canvas.h"]
    frags = [
        (d122, f"{v['GEOM:canvas.w.collapsed']}×{h}"),
        (d122, f"{v['GEOM:canvas.w.expanded']}×{h}"),
        (d122, f"{v['GEOM:canvas.w.both']}×{h}"),
        (d122, f"{v['GEOM:canvas.w.collapsed']}×{v['GEOM:canvas.h.banner']}"),
        (d298, f"0 / {v['GEOM:stack.compact-1']} / {v['GEOM:stack.compact-2']}"),
        (d298, f"0 / {v['GEOM:stack.comfortable-1']} / {v['GEOM:stack.comfortable-2']}"),
        (d298, f"{v['GEOM:stack.lift']} px"),
    ]
    sec = h2_of(t.spec, "5. One layout")
    bad = [F("G-GEOM", f"{f!r} not in D03", "spec", sec) for line, f in frags if f not in line]
    drawer = next(
        (r for r in table_rows(section(t.spec, "5.1 The rule")) if "canvas.w.drawer" in r[1]), None
    )
    if drawer is None or "derived" not in drawer[0]:
        bad.append(F("G-GEOM", "the drawer-only canvas row is not marked derived", "spec", sec))
    return bad


@functools.lru_cache(maxsize=1)
def fork_point() -> str:
    """The merge-base with origin/main, else BASE (never a fixed sha that main has left)."""
    mb = git_out("merge-base", "HEAD", "origin/main").strip()
    return mb or BASE


def g_untouched(t: Texts) -> list[Finding]:
    """BQ-3: `05` `06` `14` `15` `16`, D02, D03, KM and RK equal the fork point."""
    ref = fork_point()
    bad = []
    for key, text in t.plans:
        rel = untouched_rel(key)
        if text != (git_show(ref, rel) or at_base(rel)):
            bad.append(F("G-UNTOUCHED", f"{rel} differs from {ref[:10]}", None, None))
    return bad


def g_budget(t: Texts) -> list[Finding]:
    bad = []
    for doc, text, cap in (("spec", t.spec, SPEC_LINE_BUDGET), ("hand", t.hand, HAND_LINE_BUDGET)):
        n = text.count("\n") + (0 if text.endswith("\n") else 1)
        if n > cap:
            bad.append(F("G-BUDGET", f"the {doc} has {n} lines > {cap}", doc, h2_at(text, n)))
    return bad


# lexicon gates and table gates first, then the measured gates; the pins run last, in `audit`
LEXICON_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_prop,
    g_token,
    g_reduce,
    g_short,
    g_carrier,
    g_layout,
    g_inventory,
    g_cut,
    g_card,
    g_safety,
    g_esc,
    g_route,
    g_names,
    g_sr,
    g_clause,
    g_finding,
    g_rows,
    g_source,
    g_loop,
    g_flash,
    g_perf,
    g_oracle,
    g_scrim,
    g_newtoken,
    g_layoutprop,
    g_rules,
    g_regcell,
    g_hedge,
    g_live,
    g_tokval,
    g_script,
    g_unbuilt,
    g_proposed,
    g_pending,
    g_ruled,
    g_penpot,
    g_arow,
    g_story,
    g_walk,
    g_due,
)
MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_contrast,
    g_geom,
    g_untouched,
    g_budget,
)


# ---------------------------------------------------------------------------- the pins

PIN_DOCS: tuple[str, ...] = ("spec", "hand")  # every unit of both docs; no span is exempt
PIN_SENT = re.compile(r"s\d+")
Unit = tuple[str, str, str, str]  # (doc, region, loc, text)
FULL_STOP = re.compile(r"(?<=[.!?])\s+")


def unvalued(line: str, values: Values) -> str:
    """The line with every anchored value cut to its anchor (outside code spans), so `--fill`
    never moves a pin and a value is gated by G-ANCHOR alone."""

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
    """Every unit of the doc, per region (heading path, `#n` its occurrence): the heading, the
    line shape, each rule line, each table row by its lead cell, each prose sentence and each
    fenced block (verbatim)."""
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
            if (
                i + 1 == len(lines)
                or not fence[i + 1]
                or (len(block) > 1 and FENCE_OPEN.match(raw))
            ):
                nf += 1
                out.append((doc, region, f"fence {nf}", json.dumps("\n".join(block))))
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


def names_units(names: str) -> list[Unit]:
    """The names JSON: its top-level key order and values, then per entry (region = its id) the
    key order and each field's JSON value."""
    try:
        doc = json.loads(names)
    except ValueError:
        return [("names", "(json)#1", "parse", "invalid JSON")]
    if not isinstance(doc, dict):
        return [("names", "(json)#1", "parse", "not an object")]
    out: list[Unit] = [("names", "(top)#1", "keys", json.dumps(list(doc)))]
    out += [
        ("names", "(top)#1", k, json.dumps(v, ensure_ascii=False))
        for k, v in doc.items()
        if k != "names"
    ]
    seen: dict[str, int] = {}
    for e in doc.get("names") or []:
        if not isinstance(e, dict):
            out.append(("names", "(entry)#1", "parse", "not an object"))
            continue
        rid = str(e.get("id"))
        seen[rid] = seen.get(rid, 0) + 1
        region = f"{rid}#{seen[rid]}"
        out.append(("names", region, "keys", json.dumps(list(e))))
        out += [("names", region, k, json.dumps(v, ensure_ascii=False)) for k, v in e.items()]
    return out


def ruled_units(spec: str, hand: str, values: Values, names: str = "") -> list[Unit]:
    docs = {"spec": spec, "hand": hand}
    units = [u for d in PIN_DOCS for u in doc_units(d, docs[d], values)]
    return units + (names_units(names) if names else [])


def write_pins(units: list[Unit]) -> str:
    head = (
        "# E10-D04 pins (every unit of the spec, the hand-off and the names JSON): doc, region "
        "(heading path "
        f"#occurrence), location, the exact normalised text; {len(units)} units.\n# Written by "
        "`--repin-ruled` only; `--check` reads it (never hand-edit; see G-RULED-PIN). The names "
        "JSON's units follow the docs' (doc `names`, region = an entry id).\n"
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
    return region if len(region) <= 60 else "..." + region[-57:]


def region_sec(region: str) -> str:
    """A pin region's section key (the gates' key: the `#` or `##` heading above it)."""
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
            kind = "moved or duplicated" if now[j] in was else "unpinned (new)"
            bad.append((f"{where} s{j + 1} {kind}: {now[j][:60]!r}", doc, region))
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
    bad += [
        (f"{d} region '{region_label(r)}' is unpinned (new)", d, r)
        for d, r in new_r
        if (d, r) not in old_r
    ]
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
            bad.append((f"{where} shape changed (line forms, sentences, indents, blanks)", d, r))
    return bad


def pin_findings(t: Texts, pinned: tuple[Unit, ...] | None = None) -> list[Finding]:
    pins = read_pins() if pinned is None else pinned
    if pins is None:
        return [F("G-RULED-PIN", f"no {RULED_PIN_TXT}; run --repin-ruled deliberately", None, None)]
    names_sec = h2_of(t.spec, NAMES_HEAD)
    return [
        (
            F("G-RULED-PIN", m, "spec", names_sec)
            if d == "names"
            else F("G-RULED-PIN", m, d, region_sec(r))
        )
        for m, d, r in pin_problems(pins, ruled_units(t.spec, t.hand, t.values, t.names))
    ]


# ---------------------------------------------------------------------------- the audit


def audit(t: Texts, fetch: Fetch) -> tuple[list[str], list[str], list[str], int]:
    """(FAIL lines, NOTE lines, WARN lines, cites checked). One FAIL line per gate tag; a pin
    finding in a section another gate already FAILs is demoted to a NOTE line."""
    found: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        found += g_anchor_doc(doc, text, t.values)
        found += g_marker_doc(doc, text, t.values)
        found += g_hex_doc(doc, text)
        found += g_charset_doc(doc, text)
        found += g_close_doc(doc, text)
    for gate in LEXICON_GATES:
        found += gate(t)
    cf, warns, n = cite_findings({"spec": t.spec, "hand": t.hand}, fetch)
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


def say_in(head: str, sentence: str) -> Edit:
    """Append `sentence` to the last prose or bullet line of the section `head`."""

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


def in_lines(head: str, fn: Callable[[list[str]], list[str]]) -> Edit:
    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        return text.replace(block, "\n".join(fn(block.split("\n"))), 1) if block else text

    return run


def dup_line(prefix: str) -> Callable[[list[str]], list[str]]:
    def run(lines: list[str]) -> list[str]:
        i = next((n for n, ln in enumerate(lines) if ln.startswith(prefix)), None)
        return lines if i is None else [*lines[: i + 1], lines[i], *lines[i + 1 :]]

    return run


def drop_line(prefix: str) -> Callable[[list[str]], list[str]]:
    return lambda lines: [ln for ln in lines if not ln.startswith(prefix)]


def squeezed(n: int) -> Edit:
    """Drop the blank line under the last `n` headings."""

    def run(text: str, _v: Values) -> str:
        lines = text.split("\n")
        under = [i + 1 for i, ln in enumerate(lines[:-1]) if HEADING.match(ln) and not lines[i + 1]]
        drop = set(under[-n:])
        return "\n".join(ln for i, ln in enumerate(lines) if i not in drop)

    return run


def overrun(text: str, _v: Values) -> str:
    return text + "filler\n" * (SPEC_LINE_BUDGET - text.count("\n") + 5)


def pushed(lst: list[float], item: float) -> Callable[[], Callable[[], None]]:
    """Push `item` onto a tool-state lever; the undo pops it."""

    def run() -> Callable[[], None]:
        lst.append(item)

        def undo() -> None:
            lst.pop()

        return undo

    return run


def json_sub(old: str, new: str) -> Callable[[str], str]:
    return lambda text: text.replace(old, new, 1)


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str  # the gate tag that must trip ("" for a probe that must trip nothing)
    spec: Edit | None = None
    hand: Edit | None = None
    names: Callable[[str], str] | None = None
    plan: tuple[str, Callable[[str], str]] | None = None
    patch: Callable[[], Callable[[], None]] | None = None


REG, ESC, NAMES, CLA, FIND = REG_HEAD, ESC_HEAD, NAMES_HEAD, CLAUSE_HEAD, F_HEAD
MUTATIONS: tuple[Mutation, ...] = (
    Mutation("M-01", "G-PROP", spec=row_edit(REG, "T-01", 3, appended("; `width`"))),
    Mutation(
        "M-02",
        "G-LAYOUTPROP",
        spec=say_in("5.1 The rule", "The banner slot opens by a height animation."),
    ),
    Mutation("M-03", "G-TOKEN", spec=row_edit(REG, "T-03", 4, appended("; `motion.drawer`"))),
    Mutation(
        "M-04", "G-TOKEN", spec=row_edit(REG, "T-03", 4, appended("; `motion.duration.slow`"))
    ),
    Mutation("M-05", "G-REDUCE", spec=row_edit(REG, "T-01", 5, appended("; a shorter duration"))),
    Mutation("M-06", "G-REDUCE", spec=row_edit(REG, "T-06", 5, to("fade only"))),
    Mutation("M-07", "G-CARRIER", spec=row_edit(REG, "T-04", 6, to(""))),
    Mutation("M-08", "G-LAYOUT", spec=row_edit(REG, "T-02", 7, to("frame 0"))),
    Mutation("M-09", "G-INVENTORY", spec=drop_row(REG, "T-08")),
    Mutation(
        "M-10",
        "G-CARD",
        spec=row_edit(REG, "T-10", 3, appended("; the card fades in over `normal`")),
    ),
    Mutation("M-11", "G-CUT", spec=row_edit(REG, "T-25", 3, appended("; a `normal` cross-fade"))),
    Mutation(
        "M-12", "G-SAFETY", spec=row_edit(SAFETY_HEAD, "S-01", 2, appended("; the badge fades in"))
    ),
    Mutation("M-13", "G-SAFETY", spec=drop_row(SAFETY_HEAD, "S-03")),
    Mutation(
        "M-14",
        "G-ESC",
        spec=row_edit(ESC, "SCR-157 blocking dialog", 1, to("`Esc` does nothing")),
    ),
    Mutation("M-15", "G-ESC", spec=drop_row(ESC, "RightRail drawer")),
    Mutation(
        "M-16",
        "G-ROUTE",
        spec=sub_in(ROUTE_HEAD, "SkipLink → TopBar → NavRail", "SkipLink → NavRail → TopBar"),
    ),
    Mutation(
        "M-17",
        "G-NAMES",
        names=json_sub('"name": "Collapse navigation rail"', '"name": "Collapse rail"'),
    ),
    Mutation("M-18", "G-NAMES", spec=drop_row(NAMES, "window.titlebar.more")),
    Mutation("M-19", "G-NAMES", spec=row_edit(NAMES, "shell.topbar.overflow", 5, to("confirmed"))),
    Mutation("M-20", "G-SR", spec=say_in("1.2 Method", "It was tested with NVDA.")),
    Mutation("M-21", "G-FINDING", spec=row_edit(FIND, "F-04", 1, to("blocking"))),
    Mutation("M-22", "G-FINDING", spec=row_edit(FIND, "F-03", 5, to("hcl-worker-1"))),
    Mutation("M-23", "G-CLAUSE", spec=drop_row(CLA, "`3.4.9`")),
    Mutation(
        "M-24", "G-CLAUSE", spec=row_edit(CLA, "`3.3.3`", 1, to('"Esc is reserved" (`05`:85)'))
    ),
    Mutation("M-25", "G-CLAUSE", spec=row_edit(CLA, "`5.1`", 3, to("at risk"))),
    Mutation("M-26", "G-ROWS", spec=in_lines(ROWS_HEAD, drop_line("- **G-02**"))),
    Mutation("M-27", "G-ROWS", spec=drop_row(ROWS_HEAD, "C-08")),
    Mutation(
        "M-28",
        "G-SOURCE",
        spec=say_in("9. The single", "A component reads `prefers-reduced-motion` itself."),
    ),
    Mutation("M-29", "G-LOOP", spec=say_in("6.2 Never", "The drawer pulses while open.")),
    Mutation(
        "M-30", "G-FLASH", spec=row_edit("11. Flash", "the scrim (T-10, T-15)", 1, to("4 flashes"))
    ),
    Mutation(
        "M-31",
        "G-PERF",
        spec=say_in("8.1 Rules", "The rail is animated by `requestAnimationFrame`."),
    ),
    Mutation(
        "M-32", "G-ORACLE", spec=say_in("6.3 RBAC", "The Admin item fades out for a Manager.")
    ),
    Mutation(
        "M-33",
        "G-UNBUILT",
        spec=sub_in(
            "0. Status", "this spec is the implementation contract", "this spec is the contract"
        ),
    ),
    Mutation(
        "M-34",
        "G-UNBUILT",
        spec=sub_in("0. Status", "for E10-Q04 (#303)", "for E10-Q04"),
    ),
    Mutation(
        "M-35",
        "G-PROPOSED",
        spec=sub_in("5.1 The rule", "PROPOSED (no merged", "Taken here (no merged"),
    ),
    Mutation(
        "M-36",
        "G-PENDING",
        spec=line_edit(
            "**Ticket:**",
            "**Owner approval pending**",
            "**Owner approval pending**; approved by the owner",
        ),
    ),
    Mutation(
        "M-37",
        "G-CLOSE",
        spec=line_edit("**Ticket:**", "one PR whose body", "one PR that closes #198, whose body"),
    ),
    Mutation("M-38", "G-RULED", spec=line_edit("## The twenty-eight", RULING_ID, "6433315841")),
    Mutation("M-39", "G-CITE", spec=sub_in("0. Status", "(D03:31)", "(D03:99999)")),
    Mutation("M-40", "G-UNTOUCHED", plan=("16", lambda x: x + "drift\n")),
    Mutation("M-41", "G-BUDGET", spec=overrun),
    Mutation("M-42", "G-ANCHOR", spec=say_in("2. The tokens", "The rail takes 100 ms.")),
    Mutation(
        "M-43",
        "G-CHARSET",
        spec=sub_in("1.1 What", "The motion contract", "The motion contract"),
    ),
    Mutation("M-44", "G-AROW", hand=drop_row("§C", "A-02")),
    Mutation("M-45", "G-STORY", hand=sub_in("§D", "**CMP-059 CommandPalette** and ", "and ")),
    Mutation(
        "M-46",
        "G-WALK",
        hand=say_in("§F", "The walkthrough was attended by the frontend team."),
    ),
    Mutation(
        "M-47",
        "G-DUE",
        hand=with_values(lambda v: row_edit("§F", "F-05", 4, to(av(v, "DATE:E10-T02")))),
    ),
    Mutation(
        "M-48",
        "G-PENPOT",
        spec=sub_in("0. Status", "page id `b9d0", "https://penpot.example.org page id `b9d0"),
    ),
    Mutation("M-49", "G-SCRIM", spec=say_in("6.2 Never", "The scrim covers the ENV badge.")),
    Mutation("M-50", "G-NEWTOKEN", spec=say_in("2. The tokens", "`motion.drawer` is a token.")),
    Mutation("M-51", "G-RULES", spec=sub_in("1.4 Rules", ", never precedes or delays it", "")),
    Mutation(
        "M-52",
        "G-HEDGE",
        spec=say_in("10. The substitution", "Under reduce a row may keep its motion."),
    ),
    Mutation(
        "M-53",
        "G-LIVE",
        spec=row_edit("14. Live", "the clock, offset, countdown", 3, to("announced each second")),
    ),
    Mutation(
        "M-54",
        "G-REGCELL",
        spec=row_edit(REG, "T-03", 3, lambda c: c.replace("; the content complete at frame 0", "")),
    ),
    Mutation(
        "M-55",
        "G-TOKVAL",
        spec=with_values(
            lambda v: sub_in(
                "2. The tokens",
                "| " + av(v, "TOK:duration.fast"),
                "| " + av(v, "TOK:duration.normal"),
            )
        ),
    ),
    Mutation("M-56", "G-CLAUSE", spec=row_edit(CLA, "`6.5a`", 3, to("compliant"))),
    Mutation("M-57", "G-INVENTORY", spec=drop_row(REG, "T-28")),
    Mutation("M-58", "G-FLASH", spec=in_lines("11. Flash", drop_line("| a toggle binding under"))),
    Mutation(
        "M-59",
        "G-NAMES",
        names=json_sub("{kind} {symbol} {environment}", "{kind} {symbol}"),
    ),
    Mutation("M-60", "G-SCRIPT", hand=in_lines("§E", drop_line("- The `05` §10 template"))),
    # the tool's own probes
    Mutation(
        "X-01",
        "G-ANCHOR",
        spec=with_values(
            lambda v: sub_in(
                "2. The tokens",
                "| " + av(v, "TOK:duration.fast"),
                "| 1" + av(v, "TOK:duration.fast"),
            )
        ),
    ),
    Mutation(
        "X-02",
        "G-CHARSET",
        spec=line_edit("**Inputs pinned.**", "since the shas named.", "since the shas named. "),
    ),
    Mutation(
        "X-03",
        "G-MARKER",
        spec=sub_in("1.1 What", "The motion contract", "<!-- note -->The motion contract"),
    ),
    Mutation(
        "X-04",
        "G-CLOSE",
        hand=line_edit("Components:", "(RULED, comment", "(fixes #198; RULED, comment"),
    ),
    Mutation("X-05", "G-CONTRAST", patch=pushed(BAR_OVERRIDE, 30.0)),
    Mutation(
        "X-06",
        "G-REDUCE",
        spec=say_in("10. The substitution", "Under reduce a toast has a shorter duration."),
    ),
    Mutation(
        "X-07", "G-CHARSET", spec=sub_in("1.1 What", "The motion contract", "The\tmotion contract")
    ),
    Mutation(
        "X-08",
        "G-CHARSET",
        spec=sub_in("1.1 What", "The motion contract", "The\u2028motion contract"),
    ),
    Mutation(
        "X-09",
        "G-CHARSET",
        spec=sub_in("1.1 What", "The motion contract", "The mo\u00adtion contract"),
    ),
    Mutation("X-10", "G-NAMES", names=json_sub('"scr": "SCR-157"', '"scr": "SCR-010"')),
    Mutation(
        "X-11", "G-NAMES", names=json_sub('"finding": null\n', '"finding": null,\n      "x": 1\n')
    ),
    Mutation(
        "X-12", "G-NAMES", names=json_sub('"template": "Dismiss {title}"', '"template": null')
    ),
    Mutation(
        "X-13",
        "G-SCRIM",
        spec=say_in("6.1 Safety", "A scrim darkens the TopBar's badge mid-flight."),
    ),
    # one per pin class (G-RULED-PIN only)
    Mutation("P-01", "G-RULED-PIN", spec=row_edit(REG, "T-05", 8, appended(" (sic)"))),
    Mutation(
        "P-02",
        "G-RULED-PIN",
        spec=line_edit("The motion contract of the shell", "(§19.1).", "(§19.1). Ok."),
    ),
    Mutation("P-03", "G-RULED-PIN", spec=in_lines("1.4 Rules", dup_line("- **R-8"))),
    Mutation("P-04", "G-RULED-PIN", spec=squeezed(2)),
    Mutation(
        "P-05",
        "G-RULED-PIN",
        hand=row_edit("§B", "CMP-094 HotkeyOverlay", 5, appended(" (cited)")),
    ),
    Mutation("P-06", "G-RULED-PIN", spec=line_edit("- **R-8", "- **R-8", "**R-8")),
    # a probe that must trip nothing
    Mutation(
        "N-01",
        "",
        spec=in_lines(
            REG, lambda ls: [re.sub(r" {2,}", " ", x) if x.startswith("| T-05") else x for x in ls]
        ),
    ),
)


def removed(needle: str) -> Callable[[str], str]:
    return lambda c: c.replace(needle, "(removed)")


def needle_probes() -> tuple[Mutation, ...]:
    """One Y- probe per ruled needle: the needle replaced must FAIL its gate alone."""
    out: list[Mutation] = []
    for doc, head, needle in RULE_NEEDLES:
        edit = sub_in(head, needle, "(removed)")
        mid = f"Y-{len(out) + 1:02d}"
        out.append(
            Mutation(mid, "G-RULES", spec=edit)
            if doc == "spec"
            else Mutation(mid, "G-RULES", hand=edit)
        )
    for row, col, needle in REGCELL:
        idx = REG_COLS.index(col)
        out.append(
            Mutation(
                f"Y-{len(out) + 1:02d}",
                "G-REGCELL",
                spec=row_edit(REG, row, idx, removed(needle)),
            )
        )
    return tuple(out)


PROBES: tuple[Mutation, ...] = MUTATIONS + needle_probes()


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def plan_paths() -> tuple[tuple[str, Path], ...]:
    return tuple((k, ROOT / untouched_rel(k)) for k in UNTOUCHED)


def read_plans() -> tuple[tuple[str, str], ...]:
    return tuple((k, p.read_bytes().decode("utf-8")) for k, p in plan_paths())


def mutation_table(spec: str) -> list[tuple[str, str]]:
    """(id, gate tag) of each row of the spec's mutation list."""
    out = []
    for r in rows_led(section(spec, MUTATION_HEAD), r"M-\d\d"):
        m = re.match(r"(G-[A-Z-]+):", r[2]) if len(r) > 2 else None
        out.append((r[0], m[1] if m else ""))
    return out


def ascii_line(s: str) -> str:
    return s.encode("ascii", "backslashreplace").decode("ascii")


def selftest(spec: str, hand: str, names: str, paths: tuple[Path, ...]) -> tuple[bool, list[str]]:
    on_disk = digest(paths)
    plans = read_plans()
    values = compute(spec, hand)
    spec_f, _ = fill(spec, values)
    hand_f, _ = fill(hand, values)
    values = compute(spec_f, hand_f)  # frozen at the filled baseline
    base_t = Texts(spec_f, hand_f, names, plans, values)
    base_fails, _notes, base_warns, _ = audit(base_t, git_show)
    lines = [f"baseline (filled in memory): {len(base_fails)} FAIL, {len(base_warns)} WARN"]
    lines += [f"  baseline FAIL {x[:160]}" for x in base_fails]
    ok = not base_fails
    listed = mutation_table(spec_f)
    tool_m = [(m.mid, m.gate) for m in MUTATIONS if m.mid.startswith("M-")]
    if listed != tool_m:
        ok = False
        diff = [x for x in listed if x not in tool_m] + [x for x in tool_m if x not in listed]
        lines.append(f"  the spec's mutation list differs from the tool's: {diff[:4]}")
    pristine = digest_texts(spec_f, hand_f, names, *(x for _n, x in plans))
    for mu in PROBES:
        s = mu.spec(spec_f, values) if mu.spec else spec_f
        h = mu.hand(hand_f, values) if mu.hand else hand_f
        nm = mu.names(names) if mu.names else names
        new_plans = tuple(
            (k, mu.plan[1](x) if mu.plan and mu.plan[0] == k else x) for k, x in plans
        )
        if (s, h, nm, new_plans) == (spec_f, hand_f, names, plans) and mu.patch is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        undo = mu.patch() if mu.patch else None
        try:
            fails, _n2, _w, _c = audit(Texts(s, h, nm, new_plans, values), git_show)
        except SystemExit as exc:
            fails = [str(exc)]
        finally:
            if undo:
                undo()
        new = [x for x in fails if x not in base_fails]
        if mu.gate:
            named = [x for x in new if x.startswith(f"[{mu.gate}]")]
            hit = bool(named) and len(new) == 1
        else:
            named, hit = [], not new
        restored = digest_texts(spec_f, hand_f, names, *(x for _n, x in plans)) == pristine
        restored = restored and digest(paths) == on_disk and not BAR_OVERRIDE
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="E10-D04 motion and review audit (module docstring)")
    ap.add_argument("--check", nargs="?", const=SPEC_REL, metavar="SPEC", help="audit the docs")
    ap.add_argument("--handoff", metavar="F", default=HAND_REL, help="the hand-off to audit")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="replace placeholders, then check")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="apply every mutation")
    ap.add_argument("--repin-ruled", action="store_true", help=f"rewrite {RULED_PIN_TXT}")
    args = ap.parse_args(argv)
    spec_path = ROOT / (args.check or SPEC_REL)
    hand_path = ROOT / args.handoff
    names_path = ROOT / NAMES_REL
    spec = spec_path.read_bytes().decode("utf-8")
    hand = hand_path.read_bytes().decode("utf-8")
    names = names_path.read_bytes().decode("utf-8")
    if args.repin_ruled:
        left = PLACEHOLDER.findall(CODE.sub("", spec + hand))
        if left:
            print(f"FAIL --repin-ruled: {len(left)} unfilled placeholders; run --fill first")
            return 1
        units = ruled_units(spec, hand, compute(spec, hand), names)
        write_text(ROOT / RULED_PIN_TXT, write_pins(units))
        print(f"--repin-ruled: {len(units)} units pinned in {RULED_PIN_TXT}")
        return 0
    if args.self_test:
        paths = (
            spec_path,
            hand_path,
            names_path,
            ROOT / RULED_PIN_TXT,
            *(p for _n, p in plan_paths()),
        )
        ok, lines = selftest(spec, hand, names, paths)
        print("\n".join(lines))
        print(f"--self-test: {'ok' if ok else 'FAIL'} - {len(PROBES)} mutations in memory")
        return 0 if ok else 1
    values = compute(spec, hand)
    if args.fill:
        spec, unknown = fill(unfill(spec), values)
        hand, unknown_h = fill(unfill(hand), values)
        write_text(spec_path, spec)
        write_text(hand_path, hand)
        for u in unknown + unknown_h:
            print(f"FAIL --fill: no value for {{{{{u}}}}}")
        values = compute(spec, hand)
    if args.json and not (args.check or args.fill):
        print(json.dumps({"values": values}, ensure_ascii=False, indent=1))
        return 0
    t = Texts(spec, hand, names, read_plans(), values)
    fails, notes, warns, n = audit(t, git_show)
    if args.json:
        doc = {"values": values, "fails": fails, "notes": notes, "warnings": warns, "cites": n}
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        gates = len(LEXICON_GATES) + len(MEASURED_GATES) + 7
        shown = os.path.relpath(spec_path, ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        print(f"## E10-D04 audit of {shown} (+ the hand-off) at {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(notes))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK - every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(notes)} NOTE, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
