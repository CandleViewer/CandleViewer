#!/usr/bin/env python3
"""E08-D08 (#176) audit: SCR-104, the scanner panel (spec + hand-off).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base `2cf551f4af` (`git show`): the token JSON (`themes.json` layering:
dark = primitives + semantic-dark, light = + semantic-light, hc = + semantic-hc), the plan texts
the spec cites, the merged design docs it cites, the RBAC seed, the keymap, the ticket JSON
(`E08.json`) and the QA plan; then this ticket's spec and hand-off from the working tree, and the
working-tree files RULED BQ-3 keeps untouched.

1. **Values (RULED 6453599089, BQ-1).** Every `{{KIND:key}}` outside a code span is COMPUTED:
   CITE (a figure parsed from its cited line at the base: the cap, the cadence, the poll rate, the
   scan budget, T2, the hold, the connection cap, the reference width, the window, row heights,
   the zoom, the virtualisation threshold, `Limit`, the `filters` bound, the preset-name bound, the
   list cap, the target size, the clock, the cache, the decimals and figures of E08-D06 F6-F7, the
   mount and scroll budgets), RULED (the ruling's own figures), COUNT (boards, twins, frames,
   criteria and their classes read from `22`, states, pairs, themes, line budgets), HEX (every
   bound token in dark / light / hc) and CONTRAST (WCAG 2.x, truncated to two decimals). `--fill`
   writes `VALUE<!--=KIND:key-->`; `--check` re-derives every anchored value with a left
   boundary, and FAILs a `{{` left outside a code span, a figure typed by hand before a unit or a
   counted noun, a count written as a word (G-WORDCOUNT) and a hand-typed hex.
2. **The comment strip.** One pattern over the whole text, `re.DOTALL`; every comment must be a
   value anchor the tool computes (G-MARKER); the lexicon gates read rendered text only.
3. **Cites.** Every cite is read at the base (G-CITE: FAIL when a line is gone or blank), and
   G-VERSION FAILs (never WARNs) when any line inside any cited range differs at `origin/main`, or
   when `origin/main` does not resolve. Load-bearing fragments in CITED must sit on their line.
   G-QUOTE: every backticked field, metric, event or schema name is verbatim in a source the line
   cites (or the ticket texts), or a PROPOSED name; every quoted string of 12 characters or more is
   verbatim there or an instance of a W-n string of the spec's copy deck.
4. **Gates.** Lexicon gates read rows and prose after the comment strip (NFKC, markup dropped,
   dashes to spaces, lower case; a claim is read per clause; a negation covers its own term within
   five words and a list coordinated after it; quoted copy, the mutation rows and the hand-off's
   Old cells are not claims) and each ruled behaviour also has synonyms refused. Measured gates
   read the tables column by column (criteria, states, frames, pairs, C-rows, the G-ledger, the
   dry run, Table A). G-UNTOUCHED compares committed and uncommitted paths with
   `git merge-base HEAD origin/main` and FAILs when it does not resolve; only this PR's four files
   may differ. G-CHARSET, G-CELLS (escaped pipes kept), G-CLOSE, G-BUDGET close the set. The
   lens folds of 2026-10-27 add G-FILTERBAR (chips, the remove button, the popover's names,
   Regime's classes), G-HANDOFF (§A ticks and evidence, §F) and G-WALK's item-by-item need lists
   (hand-off §G); the synonyms were re-run against the adversary lens's 36 paraphrases, each
   caught after a repin.
5. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over EVERY unit of both docs, in
   RULED_PIN_TXT: each heading, table row (by its lead cell), rule line, prose sentence and fenced
   block, by doc, region (heading path plus occurrence), location and exact text (NFKC, whitespace
   collapsed), with a line-shape tag per region. Anchored values are pinned with their values cut
   out (G-ANCHOR owns them). `--repin-ruled` is the only writer and refuses while a placeholder is
   unfilled. A pin finding in a section another gate already FAILs prints as a NOTE line.
6. **--self-test** applies every mutation of the spec's §16.2 (M-n) and the tool's own X-n
   (paraphrases), P-n (one per pin class) and N-n probes (which must trip nothing), with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names, and every
   text is restored byte-identically (sha256 in memory and on disk). The report is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e08_d08_scanner_audit.py --check [SPEC] [--handoff F] \
      [--json] [--fill]
  python3 -I docs/design/_tools/e08_d08_scanner_audit.py --self-test
  python3 -I docs/design/_tools/e08_d08_scanner_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import difflib
import functools
import hashlib
import io
import json
import math
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "2cf551f4af"  # every cite was read here (the spec's Inputs line; the merge-base at start)
HEAD = "origin/main"  # G-VERSION: a cited line that drifts here FAILs
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E08/E08-D08.md"
HAND_REL = "docs/design/E08/E08-D08-handoff.md"
RULED_PIN_TXT = "docs/design/_tools/e08_d08_ruled_pins.txt"
DS_SRC_REL = "packages/ui/tokens"
# RULED BQ-3 and the standing list: never edited by this ticket
UNTOUCHED = ("14", "15", "16", "22", "23")
UNTOUCHED_DOCS = ("D04", "D07", "E08-D06", "E09-D09", "E25-D05", "KM", "SEED")
# the only paths this PR may add or change against the merge-base (the PR 2 boards come later)
OWN_PATHS = (
    "docs/design/E08/E08-D08.md",
    "docs/design/E08/E08-D08-handoff.md",
    "docs/design/_tools/e08_d08_scanner_audit.py",
    "docs/design/_tools/e08_d08_ruled_pins.txt",
)
CITE_FILES: dict[str, str] = {
    "D04": "docs/design/E08/E08-D04.md",
    "D07": "docs/design/E08/E08-D07.md",
    "README": "docs/design/README.md",
    "SEED": "services/api/candleviewer/auth/rbac_seed.json",
    "KM": "apps/web/src/keymap/keymap.json",
    "VAL": "docs/plan/backlog/_tools/validate.py",
    "E08J": "docs/plan/backlog/E08.json",
    "QAP": "qa/plans/e08-market-data-test-plan.md",
}
# the ticket texts (bodies inside E08J): T (#176), S11 (#4705), T09 (#4708)
TICKET_KEYS = {"T": "E08-D08", "S11": "E08-S11", "T09": "E08-T09"}
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SEMANTIC = ("semantic-dark", "semantic-light", "semantic-hc")

RULING_ID = "6453599089"
BQ_LIST_ID = "6453391851"
RULED_IDS = (RULING_ID, BQ_LIST_ID)  # the allow-list: every comment id the docs cite
OWNER_PENDING = "PROPOSED, owner approval pending (#2701)"  # BQ-7, BQ-13
MAX_BOARDS = 10  # RULED BQ-24 (lever 4): at most ten boards
TWIN_SHARE = Fraction(1, 3)  # twins at most a third of the boards (lever 4)
SPEC_LINE_BUDGET = 600  # "about 600 lines at most"
HAND_LINE_BUDGET = 150  # "about 150 lines at most"
# the ruling's own figures (comment 6453599089, BQ-15 and BQ-24)
RULED_VALUES = {"RULED:sparkline.samples": "24", "RULED:board01.rows": "24"}
GITHUB_ISSUE = "#4708"
LEDGER_OWNER = "E08-T09 (#4708)"  # RULED BQ-4: G-1 ... G-10, one owner
# lens 1 carry: G-1 ... G-10 name their consumer and due date as G-11 ... G-13 do (S11's sprint
# start, E08J:482 "Planned for Sprint 07 (2026-11-06"; calendar_cv: Sprint 01 + 6 weeks)
LEDGER_DUE = "E08-S11 (#4705), due 2026-11-06"
LEDGER_DUE_HEAD = "Consumer, due (Sprint 07's start, E08J:482)"
# the version line (spec **Start.**): every merged input's sha, in order (lens 1 carry)
VERSION_SHAS = (
    "a899ca1760",
    "5311bc5636",
    "daeafcb465",
    "52f62f6457",
    "33bb920225",
    "baccf724a1",
    "c41025bd47",
    "c0674eb95a",
    "d6597cbcf7",
)
MAX_WALK = 10  # the owner walkthrough (hand-off §E): at most ten items (lens 1 carry)
CONSUMERS = (
    "E08-S11 (#4705)",
    "E08-T09 (#4708)",
    "E08-D12 (#180)",
    "E08-D13 (#181)",
    "E08-D14 (#277)",
    "E08-Q05 (#282)",
)

# CITE values: key -> (cite id, line, pattern whose group 1 is the value)
CITE_VALUES: dict[str, tuple[str, int, str]] = {
    "cap": ("14", 2273, r"capped at (\d+)"),
    "cadence": ("14", 2272, r"on a (\d+) s cadence"),
    "poll-hz": ("14", 2277, r"<=(\d+(?:\.\d+)?) Hz"),
    "scan-budget": ("14", 2277, r"returns in <=(\d+) s"),
    "t2": ("D07", 86, r"T2 = (\d+) s"),
    "resort": ("D07", 90, r"at most every (\d+) s"),
    "conn-cap": ("23", 397, r"\|\s*(\d+)\s*\|\s*distinct symbols"),
    "ref-width": ("D07", 164, r"Reference width (\d+) px"),
    "viewport.w": ("16", 212, r"(\d+)×\d+px"),
    "viewport.h": ("16", 212, r"\d+×(\d+)px"),
    "row.compact": ("16", 113, r"\|\s*(\d+)px"),
    "row.comfortable": ("16", 114, r"\|\s*(\d+)px"),
    "zoom": ("05", 131, r"(\d+)% browser"),
    "virtualise": ("15", 528, r"default true above (\d+) rows"),
    "limit.max": ("22", 14868, r"maximum: (\d+)"),
    "limit.default": ("22", 14868, r"default: (\d+)"),
    "filters.max": ("22", 13034, r"maxLength: (\d+)"),
    "preset.name-max": ("E08J", 614, r"`name` \(1–(\d+)\)"),
    "list-cap": ("22", 21807, r"maxItems: (\d+)"),
    "target.min": ("05", 100, r"≥(\d+)×\d+ CSS px"),
    "clock-hz": ("D07", 107, r"One shared (\d+) Hz clock"),
    "cache": ("E08J", 614, r"\(≤ (\d+) s\)"),
    "funding.dp": ("E08-D06", 230, r"keeps at least (\d+) decimals"),
    "change.dp": ("E08-D06", 231, r"to (\d+) decimals"),
    "magnitude.sf": ("E08-D06", 234, r"show (\d+) significant figures"),
    "mount": ("14", 87, r"panel mount ≤(\d+) ms"),
    "d07.funding-dp": ("D07", 94, r"Funding (\d+) dp"),
    "spread.dp": ("D07", 176, r"(\d+) dp, neutral"),
    "scroll-fps": ("15", 534, r"@(\d+)fps"),
}
# load-bearing fragments: (cite id, line at the base, text the line must hold)
CITED: tuple[tuple[str, int, str], ...] = (
    ("14", 2269, "### SCR-104 — Scanner / screener panel"),
    ("14", 2271, "saved screens"),
    ("14", 2273, "Minimum must be less than maximum"),
    ("14", 2276, "result count is announced on change"),
    ("14", 2277, "or subscribes to a scan topic"),
    ("14", 2278, "`scanner.alert_created_from_result`"),
    ("14", 2279, "scanning is limited to live metrics for symbols we are not recording"),
    ("14", 3093, '"(estimated)" labelling'),
    ("14", 85, "never hidden"),
    ("14", 88, "Every state-changing action emits an append-only audit record"),
    ("14", 1245, "`Ctrl+F` filter"),
    ("14", 2944, "Every empty surface uses the same anatomy"),
    ("15", 2675, "CMP-133 is the only host today"),
    ("15", 2679, "never from a catalogue adjective"),
    ("15", 529, "implied whenever a body column is interactive"),
    ("15", 587, "`space.filterbar.*`"),
    ("22", 13022, "operationId: runScanner"),
    ("22", 13029, "x-rbac: { permissions: [marketdata:read], scope: none }"),
    ("22", 13033, "`ScannerFilter`"),
    ("22", 21814, "ScannerRow:"),
    ("22", 21832, "rather than evaluated as zero"),
    ("22", 16678, "Present only where a cheap exact count exists."),
    ("22", 20476, "PaneKind:"),
    ("22", 20497, "account panes"),
    ("23", 397, "max_symbols_per_connection"),
    ("24", 1057, "| `tape_speed` "),
    ("24", 1058, "`tape_speed_zscore`"),
    ("E08J", 482, "Planned for Sprint 07 (2026-11-06"),
    ("32", 43, "Schedule & capacity"),
    ("VAL", 56, '"R9 Advice boundary"'),
    ("D04", 42, '"Stale 4s"'),
    ("D04", 74, "a data-confidence state not in this set of eight"),
    ("D07", 90, "Re-sort"),
    ("D07", 102, "The panel owns no live region."),
    ("D07", 164, "Reference width 784 px"),
    ("D07", 626, "illustrative values, not a market capture"),
    ("D07", 802, "C-8"),
    ("E09-D09", 95, "Read-only while viewing as {user}."),
    ("E09-D09", 114, '"save workspaces"'),
    ("E09-D09", 112, '"change alerts"'),
    ("E15-D07", 205, "not offered until a contract PR adds a kind"),
    ("E25-D05", 127, "A classification from ADX, Hurst and ATR %"),
    ("E25-D05", 133, "E24-D01 C7"),
    ("E25-D01", 95, "The advice boundary"),
    ("SEED", 239, '"viewer": ['),
    ("QAP", 106, "E08-TC-C05"),
)

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z0-9]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
UNITS = r"(?:ms|s|hz|px|%|:1|fps)"
COUNTED = (
    r"(?:boards?|twins?|frames?|criteria|criterion|columns?|rows?|states?|pairs?|themes?"
    r"|questions?|mutations?|symbols?|samples?|decimals?|characters?|lines?|consumers?"
    r"|cadences?|seconds?|minutes?|significant|items?|options?|matches|g-rows?|c-rows?)"
)
FIGURE = re.compile(
    rf"(?<![\w.,:#/>{{§+~-])(\d+(?:[.,]\d+)*)\s?(?:{UNITS}(?![\w])|{COUNTED}\b)", re.IGNORECASE
)
NUM_WORDS = (
    "two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    "|sixteen|seventeen|eighteen|nineteen|twenty|twenty-four|thirty|forty|fifty|hundred"
)
WORDCOUNT = re.compile(rf"\b({NUM_WORDS})\b(?:\s+[\w'’-]+){{0,2}}?\s+{COUNTED}\b", re.IGNORECASE)
CITE_GROUP = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:D0[47]|SEED|KM|VAL|E08J|QAP|README"
    r"|E\d\d-D\d\d)\b)) ?"
    r":(?P<first>\d+(?:[–-]\d+)?)(?P<more>(?:(?:\s*\([^()\n]*\))?,\s*:\d+(?:[–-]\d+)?)*)"
)
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]|\b[a-z0-9-]+\.(?:com|net|org|io|dev)\b", re.IGNORECASE)
COMMENT_ID = re.compile(r"(?<![\w-])(\d{8,})(?![\w-])")

Values = dict[str, str]
Fetch = Callable[[str, str], str | None]
DRIFT: list[tuple[str, int, str]] = []  # self-test lever: (path, line, text) read at HEAD
BROKEN: list[str] = []  # self-test lever: "head" or "merge-base" does not resolve
# a gate finding: (gate tag, message, doc, section); doc / section None for a repo-level finding
Finding = tuple[str, str, str | None, str | None]


# ---------------------------------------------------------------------------- reading
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
    """`git_show`, with the self-test's DRIFT applied to the HEAD side (G-VERSION)."""
    text = git_show(rev, rel)
    if rev != HEAD or text is None or not DRIFT:
        return text
    lines = text.split("\n")
    for r, n, new in DRIFT:
        if r == rel and 0 < n <= len(lines):
            lines[n - 1] = new
    return "\n".join(lines)


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


def grab(pattern: str, text: str, what: str, flags: int = MULTI) -> str:
    m = re.search(pattern, text, flags)
    if not m:
        raise SystemExit(f"FAIL parse: {what} not found ({pattern})")
    return m[1]


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


# ---------------------------------------------------------------------------- the comment strip

# RULED BQ-1 (a): ONE pattern over the whole text, DOTALL. `<!-->` and `<!--->` close at once, a
# comment closes at `-->` or `--!>`, and an unclosed comment runs to the end of the text.
COMMENT = re.compile(r"<!--(?:>|->|.*?--!?>|.*\Z)", re.DOTALL)
_HIDDEN = re.compile(COMMENT.pattern + r"|[\u00ad\u200b-\u200d\u2060\ufeff]", re.DOTALL)


def strip_comments(text: str) -> str:
    return _HIDDEN.sub("", text)


# ---------------------------------------------------------------------------- markdown

FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def fenced(lines: list[str]) -> list[bool]:
    """For each line, whether it is a fence line or inside a fenced block. The fence kind (``` or
    ~~~) and its length are read from the marker after the indent; only a marker of the same kind,
    at least as long and with nothing after it, closes the block; an unclosed fence runs to the
    end."""
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
    rf"\b(?:it|this)(?: \w+){{0,2}}? (?:is|was|be|['’]s) (?:\w+ )?{FALSITY}"
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
    """The clauses of rendered `text` (the comment strip first, so a comment never splits or
    hides a clause), split at "; ", " — " and a sentence end, never at a comma."""
    return [c for c in SENTENCE.split(strip_comments(text)) if c.strip()]


def clauses(text: str) -> list[str]:
    """A unit's clauses; a table row is read cell by cell with its lead cell as the subject."""
    if " | " not in QUOTED.sub("", text):  # a pipe inside quoted copy does not make a row
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


MUTATION_HEAD = "16.2 The mutation list"  # its rows describe the violations they plant
NEEDS_HEAD = "§G Dry-run needs"  # the hand-off's need lists: labels and pointers, not claims


def lex_units(doc: str, text: str) -> list[LexUnit]:
    """Every unit a lexicon gate reads, rendered: each table row (cells joined by " | "), each
    bullet or numbered item, each paragraph and each heading, with its `##` section. Skipped: the
    spec's §16.2 rows (they name the violations they plant), the hand-off's §G need lists
    (labels and pointers) and Table A's Old cells in the hand-off (verbatim text at the base, not
    this ticket's claims)."""
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
            skip = (doc == "spec" and m[2].startswith(MUTATION_HEAD)) or (
                doc == "hand" and m[2].startswith(NEEDS_HEAD)
            )
            old_col = doc == "hand" and m[2].startswith("Table A")
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
    """The theme names of `themes.json` at the base (dark, light, high-contrast)."""
    data = json.loads(at_base(f"{DS_SRC_REL}/themes.json"))
    return [str(t["name"]) for t in data["themes"]]


# ---------------------------------------------------------------------------- colour


def hex_of(tokens: dict[str, object], name: str) -> str:
    v = resolve(tokens, name)
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
        raise SystemExit(f"FAIL token {name} does not resolve to an opaque colour ({v})")
    return v.upper()


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
    """Two decimals, truncated (never rounded up across a bar), with the `:1`."""
    return f"{math.floor(r * 100) / 100:.2f}:1"


# ---------------------------------------------------------------------------- the texts


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    plans: tuple[tuple[str, str], ...]  # the working-tree untouched files (G-UNTOUCHED)
    values: Values = field(default_factory=dict)


@functools.lru_cache(maxsize=64)
def lex_cached(doc: str, text: str) -> tuple[LexUnit, ...]:
    return tuple(lex_units(doc, text))


def lex(t: Texts) -> list[LexUnit]:
    return [*lex_cached("spec", t.spec), *lex_cached("hand", t.hand)]


def spec_sec(t: Texts, head: str) -> str:
    return h2_of(t.spec, head)


def F(tag: str, msg: str, doc: str | None, sec: str | None) -> Finding:
    return (tag, msg, doc, sec)


def lexicon(
    tag: str,
    what: str,
    term: str,
    near: str = "",
    unless: str = "",
    heads: tuple[str, ...] = (),
    doc: str = "",
) -> Callable[[Texts], list[Finding]]:
    """No clause asserts `term` (naming `near`); `heads` restricts it to those spec sections."""

    def run(t: Texts) -> list[Finding]:
        units = lex(t)
        if heads:
            secs = {spec_sec(t, h) for h in heads}
            units = [u for u in units if u.doc == "spec" and u.sec in secs]
        if doc:
            units = [u for u in units if u.doc == doc]
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
            F(tag, f"§{head.split(' ')[0]} lacks {n!r}", doc, sec)
            for n in needles
            if norm_text(n) not in body
        ]

    return run


def both(*gates: Callable[[Texts], list[Finding]]) -> Callable[[Texts], list[Finding]]:
    def run(t: Texts) -> list[Finding]:
        return [x for gate in gates for x in gate(t)]

    return run


# ---------------------------------------------------------------------------- the ticket texts


@functools.lru_cache(maxsize=1)
def tickets() -> dict[str, str]:
    """The bodies of T, S11 and T09 in E08J at the base."""
    data = json.loads(at_base(CITE_FILES["E08J"]))
    out: dict[str, str] = {}
    for item in data:
        for short, key in TICKET_KEYS.items():
            if isinstance(item, dict) and item.get("key") == key:
                out[short] = str(item.get("body", ""))
    if set(out) != set(TICKET_KEYS):
        raise SystemExit(f"FAIL parse: ticket bodies missing in E08J ({sorted(out)})")
    return out


def t_section(short: str, head: str) -> str:
    body = tickets()[short]
    m = re.search(rf"^## {re.escape(head)}[^\n]*\n(.*?)(?=^## |\Z)", body, re.MULTILINE | re.DOTALL)
    return m[1] if m else ""


def top_split(text: str) -> list[str]:
    """Split at ", " outside parentheses and quotes."""
    out, depth, quote, cur = [], 0, False, ""
    i = 0
    while i < len(text):
        c = text[i]
        if c == '"':
            quote = not quote
        elif c == "(" and not quote:
            depth += 1
        elif c == ")" and not quote:
            depth -= 1
        if text.startswith(", ", i) and depth == 0 and not quote:
            out.append(cur.strip())
            cur, i = "", i + 2
            continue
        cur += c
        i += 1
    if cur.strip():
        out.append(cur.strip())
    return out


def t_criteria() -> list[str]:
    """T Context's criteria list, in its order."""
    m = re.search(r"live criteria \(([^)]*)\)", t_section("T", "Context"))
    if not m:
        raise SystemExit("FAIL parse: T Context has no criteria list")
    return [x.strip() for x in m[1].split(",")]


def t_scope_states() -> list[str]:
    first = next(
        (ln for ln in t_section("T", "Scope / Deliverables").split("\n") if "Hi-fi frames" in ln),
        "",
    )
    m = re.search(r"`SCR-104`: (.*)\.\s*$", first)
    if not m:
        raise SystemExit("FAIL parse: T Scope's frame list")
    return top_split(m[1])


# ---------------------------------------------------------------------------- `22`, read as text


def yaml_block(text: str, head: str, indent: int) -> list[str]:
    lines = text.split("\n")
    pad = " " * indent
    start = next((i for i, ln in enumerate(lines) if ln == f"{pad}{head}:"), -1)
    if start < 0:
        raise SystemExit(f"FAIL parse: {head} not in 22")
    out = []
    for ln in lines[start + 1 :]:
        if ln.strip() and len(ln) - len(ln.lstrip(" ")) <= indent:
            break
        out.append(ln)
    return out


@functools.lru_cache(maxsize=8)
def schema_props(name: str) -> tuple[str, ...]:
    block = yaml_block(plan("22"), name, 4)
    return tuple(m[1] for ln in block if (m := re.match(r"^ {8}([a-z_0-9]+):", ln)))


@functools.lru_cache(maxsize=1)
def schema_names() -> frozenset[str]:
    return frozenset(re.findall(r"^ {4}([A-Z][A-Za-z0-9]+):", plan("22"), MULTI))


@functools.lru_cache(maxsize=1)
def sort_enum() -> tuple[str, ...]:
    """`runScanner`'s `sort` enum, read after its operationId up to the closing bracket."""
    text = plan("22")
    start = text.find("operationId: runScanner")
    m = re.search(r"- name: sort\n.*?enum:\s*\[(.*?)\]", text[start:], re.DOTALL)
    if start < 0 or not m:
        raise SystemExit("FAIL parse: runScanner's sort enum")
    return tuple(x.strip() for x in m[1].replace("\n", " ").split(",") if x.strip())


# T's criteria -> the `ScannerRow` property that carries it today, or None (no field). The tool
# checks both directions: a named property exists; a None criterion has no property for it.
T_FIELD: dict[str, str | None] = {
    "24 h change": "price_change_pct_24h",
    "volume": "volume_24h",
    "funding rate": None,
    "OI delta": None,
    "tape-speed z-score": None,
    "spread": None,
    "volatility": None,
}
NO_FIELD = re.compile(r"funding|spread|volatil|range|zscore|z_score|delta|chg|change_oi|oi_")


def missing_criteria() -> int:
    props = schema_props("ScannerRow")
    crit = t_criteria()
    if [c for c in crit if c not in T_FIELD]:
        raise SystemExit(f"FAIL parse: T Context's criteria moved: {crit}")
    for f in T_FIELD.values():
        if f is not None and f not in props:
            raise SystemExit(f"FAIL parse: ScannerRow lacks {f}")
    if [p for p in props if NO_FIELD.search(p)]:
        raise SystemExit("FAIL parse: ScannerRow gained a field the G-2 count assumes absent")
    return sum(1 for c in crit if T_FIELD[c] is None)


# ---------------------------------------------------------------------------- tokens and pairs

BOUND = (
    "surface.canvas",
    "surface.raised",
    "surface.overlay",
    "data-confidence.stale.surface",
    "text.primary",
    "text.secondary",
    "text.tertiary",
    "status.info.subtle",
    "status.warning.subtle",
    "focus.ring",
    "surface.hover",
)
PAIRS: dict[str, tuple[str, str, str]] = {
    "primary-canvas": ("text.primary", "surface.canvas", "text"),
    "primary-raised": ("text.primary", "surface.raised", "text"),
    "secondary-raised": ("text.secondary", "surface.raised", "text"),
    "primary-hover": ("text.primary", "surface.hover", "text"),
    "tertiary-canvas": ("text.tertiary", "surface.canvas", "mark"),
    "tertiary-raised": ("text.tertiary", "surface.raised", "mark"),
    "primary-overlay": ("text.primary", "surface.overlay", "text"),
    "secondary-overlay": ("text.secondary", "surface.overlay", "text"),
    "tertiary-overlay": ("text.tertiary", "surface.overlay", "text"),
    "primary-info": ("text.primary", "status.info.subtle", "text"),
    "infodefault-info": ("status.info.default", "status.info.subtle", "mark"),
    "staletext-stale": ("data-confidence.stale.text", "data-confidence.stale.surface", "text"),
    "staleind-stale": ("data-confidence.stale.indicator", "data-confidence.stale.surface", "mark"),
    "primary-warning": ("text.primary", "status.warning.subtle", "text"),
    "warnstrong-warning": ("status.warning.strong", "status.warning.subtle", "mark"),
    "danger-overlay": ("status.danger.strong", "surface.overlay", "mark"),
    "danger-raised": ("status.danger.strong", "surface.raised", "mark"),
    "buy-raised": ("buy.default", "surface.raised", "mark"),
    "sell-raised": ("sell.default", "surface.raised", "mark"),
    "buy-canvas": ("buy.default", "surface.canvas", "mark"),
    "sell-canvas": ("sell.default", "surface.canvas", "mark"),
    "ring-raised": ("focus.ring", "surface.raised", "mark"),
    "ring-overlay": ("focus.ring", "surface.overlay", "mark"),
    "ring-stale": ("focus.ring", "data-confidence.stale.surface", "mark"),
    "onaction-action": ("text.on-action", "action.primary.default", "text"),
    "primary-app": ("text.primary", "surface.app", "text"),
    "tertiary-app": ("text.tertiary", "surface.app", "text"),
    "ring-canvas": ("focus.ring", "surface.canvas", "mark"),
    "ring-app": ("focus.ring", "surface.app", "mark"),
    "ring-info": ("focus.ring", "status.info.subtle", "mark"),
    "buy-stale": ("buy.default", "data-confidence.stale.surface", "mark"),
    "sell-stale": ("sell.default", "data-confidence.stale.surface", "mark"),
    "secondary-neutral": ("text.secondary", "neutral.subtle", "text"),
}
# routed names, cited as not shipped or PROPOSED, never bound (hand-off A-9, A-11)
NOT_SHIPPED = {"space.filterbar.*", "pattern.dashed.estimated"}
MARK_MIN_OVERRIDE: list[Decimal] = []


def theme_hex(theme: str, name: str) -> str:
    return hex_of(load_theme(theme), f"color.{name}")


def mark_min_base() -> Decimal:
    return Decimal(grab(r"≥(\d+(?:\.\d+)?):1", base_line("05", 126), "05:126"))


def mark_min() -> Decimal:
    return MARK_MIN_OVERRIDE[-1] if MARK_MIN_OVERRIDE else mark_min_base()


def text_min() -> Decimal:
    return Decimal(grab(r"≥(\d+(?:\.\d+)?):1", base_line("05", 125), "05:125"))


@functools.lru_cache(maxsize=1)
def contrast_grid() -> dict[str, dict[str, float]]:
    return {
        t: {k: contrast(theme_hex(t, fg), theme_hex(t, bg)) for k, (fg, bg, _) in PAIRS.items()}
        for t in THEMES
    }


def colour_values() -> Values:
    v: Values = {}
    for t in THEMES:
        for k in BOUND:
            v[f"HEX:{k}.{t}"] = theme_hex(t, k)
    v["CONTRAST:text.min"] = f"{text_min()}:1"
    v["CONTRAST:mark.min"] = f"{mark_min_base()}:1"
    for t, row in contrast_grid().items():
        for k, r in row.items():
            v[f"CONTRAST:{k}.{t}"] = show_ratio(r)
    return v


# ---------------------------------------------------------------------------- the values


def cite_values() -> Values:
    return {
        f"CITE:{k}": grab(pat, base_line(cid, n), f"{cid}:{n} ({k})")
        for k, (cid, n, pat) in CITE_VALUES.items()
    }


def board_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "0. Status")) if re.fullmatch(r"\d{2}", r[0])]


def is_twin(row: list[str]) -> bool:
    return len(row) > 2 and "twin of" in row[2]


FRAME_HEAD = "16.1 The frame register"
FR_COLS = ("Frame", "Board", "Theme", "State", "Components", "Copy", "Tokens", "Status")
FRAME_STATUS = "to draw (PR 2)"


def frames(spec: str) -> list[dict[str, str]]:
    rows = [r for r in table_rows(section(spec, FRAME_HEAD)) if r and r[0].startswith("`")]
    return [dict(zip(FR_COLS, r, strict=False)) for r in rows]


CRIT_HEAD = "3.1 The criteria"
STATES_HEAD = "9. The result states"


def crit_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, CRIT_HEAD)) if re.fullmatch(r"\d", r[0])]


def pair_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "14. Tokens")) if " on " in r[0]]


def d04_states() -> int:
    rows = table_rows(section(at_base(CITE_FILES["D04"]), "3. States matrix"))
    return len([r for r in rows if r and r[0].startswith("`")])


def count_values(spec: str) -> Values:
    bd = board_rows(spec)
    twins = [r for r in bd if is_twin(r)]
    crit = crit_rows(spec)
    themes = json.loads(at_base(f"{DS_SRC_REL}/themes.json"))["themes"]
    return {
        "COUNT:boards": str(len(bd)),
        "COUNT:boards.dark": str(len(bd) - len(twins)),
        "COUNT:boards.twins": str(len(twins)),
        "COUNT:boards.max": str(MAX_BOARDS),
        "COUNT:frames": str(len(frames(spec))),
        "COUNT:criteria": str(len(crit)),
        "COUNT:criteria.history": str(len([r for r in crit if r[4] == "recorded history"])),
        "COUNT:criteria.t": str(len(t_criteria())),
        "COUNT:criteria.missing": str(missing_criteria()),
        "COUNT:states": str(len(table_rows(section(spec, STATES_HEAD)))),
        "COUNT:states.t": str(len(t_scope_states())),
        "COUNT:states.14": str(len(re.split(r" · ", base_line("14", 2273).split(":**", 1)[1]))),
        "COUNT:states.d04": str(d04_states()),
        "COUNT:pairs": str(len(PAIRS)),
        "COUNT:themes": str(len(themes)),
        "COUNT:lines.budget": str(SPEC_LINE_BUDGET),
        "COUNT:lines.budget-handoff": str(HAND_LINE_BUDGET),
    }


@functools.lru_cache(maxsize=4)
def compute_cached(spec: str, hand: str) -> tuple[tuple[tuple[str, str], ...], str]:
    del hand  # the hand-off adds no computed key of its own
    v: Values = {}
    v |= cite_values()
    v |= dict(RULED_VALUES)
    v |= count_values(spec)
    v |= colour_values()
    extra = {
        "scanner_row": list(schema_props("ScannerRow")),
        "ticker": list(schema_props("Ticker")),
        "sort_enum": list(sort_enum()),
        "t_criteria": t_criteria(),
        "t_scope_states": t_scope_states(),
        "contrast": {
            t: {k: round(r, 3) for k, r in row.items()} for t, row in contrast_grid().items()
        },
    }
    return tuple(sorted(v.items())), json.dumps(extra, ensure_ascii=False)


def compute(spec: str, hand: str) -> tuple[Values, dict[str, object]]:
    items, extra = compute_cached(spec, hand)
    return dict(items), json.loads(extra)


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


# copy columns a figure may sit in: (section, columns) — Table A's Old and New cells (copy for `14`
# and `15`, verbatim or copy-ready), the copy deck's String column, the dry-run counts
COPY_CELLS = (
    ("Table A", (3, 4)),
    ("13. Copy deck", (2,)),
    ("16.2 The mutation", (1, 2)),
    ("18. The story-role", (2, 3, 4)),
)


def blanked(text: str) -> dict[str, tuple[int, ...]]:
    out: dict[str, tuple[int, ...]] = {}
    for head, cols in COPY_CELLS:
        for ln in section(text, head).split("\n"):
            if ln.startswith("|") and not is_rule(ln):
                out[ln] = cols
    return out


def plain(line: str, values: Values, blank: dict[str, tuple[int, ...]]) -> str:
    """The line with anchored values, placeholders, quotes, code spans, cites, ids and dates cut,
    and the copy cells of COPY_CELLS dropped."""
    work = line
    if line in blank:
        cells = split_row(line)
        work = " | ".join(c for j, c in enumerate(cells) if j not in blank[line])
    for m in reversed(list(ANCHOR.finditer(work))):
        want = values.get(m[1], "")
        start = m.start() - len(want) if work[: m.start()].endswith(want) else m.start()
        work = work[:start] + " ⟨v⟩ " + work[m.end() :]
    work = PLACEHOLDER.sub(" ⟨v⟩ ", work)
    work = QUOTED.sub(" ", CODE.sub(" ", work))
    work = CITE_GROUP.sub(" ", work)
    work = re.sub(r"\(#\d+\)|#\d+|\b\d{4}-\d{2}-\d{2}\b|\b[A-Z][A-Za-z]*-\d+\b", " ", work)
    return work


def g_anchor_doc(doc: str, text: str, values: Values) -> list[Finding]:
    bad: list[Finding] = []
    blank = blanked(text)
    for i, line in enumerate(text.split("\n"), 1):
        sec = h2_at(text, i)
        for m in PLACEHOLDER.finditer(CODE.sub("", line)):
            bad.append(("G-ANCHOR", f"{doc}:{i} placeholder {{{{{m[1]}}}}} not filled", doc, sec))
        spans = code_spans(line)
        for m in ANCHOR.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue
            want = values.get(m[1])
            pre = line[: m.start()]
            if want is None:
                bad.append(("G-ANCHOR", f"{doc}:{i} {m[1]} is not a computed value", doc, sec))
            elif not pre.endswith(want):
                got = re.split(r"[ |*(]", pre)[-1]
                msg = f"{doc}:{i} {m[1]} reads {got!r}; the tool computes {want!r}"
                bad.append(("G-ANCHOR", msg, doc, sec))
            elif re.search(r"[\w.,]$", pre[: len(pre) - len(want)]):
                msg = f"{doc}:{i} {m[1]}'s value has no left boundary"
                bad.append(("G-ANCHOR", msg, doc, sec))
        if line.startswith("#") and not ANCHOR.search(line):
            continue
        for m in FIGURE.finditer(plain(line, values, blank)):
            bad.append(("G-ANCHOR", f"{doc}:{i} {m[0]!r} is a figure typed by hand", doc, sec))
    return bad


def g_wordcount_doc(doc: str, text: str, values: Values) -> list[Finding]:
    """A count is an anchored figure, never a word ("ten boards", "eight criteria")."""
    bad: list[Finding] = []
    blank = blanked(text)
    for i, line in enumerate(text.split("\n"), 1):
        for m in WORDCOUNT.finditer(plain(line, values, blank)):
            msg = f"{doc}:{i} {m[0]!r} is a count written as a word"
            bad.append(("G-WORDCOUNT", msg, doc, h2_at(text, i)))
    return bad


def g_marker_doc(doc: str, text: str, values: Values) -> list[Finding]:
    """Every HTML comment (the one strip pattern) is a value anchor the tool computes."""
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
            if not re.match(r"<!--=HEX:", line[m.end() :]):
                msg = f"{doc}:{i} {m[0]} typed by hand (not the tool's value)"
                bad.append(("G-HEX", msg, doc, h2_at(text, i)))
    return bad


# ---------------------------------------------------------------------------- cites


def cite_refs(line: str) -> list[tuple[str, int, int]]:
    """(cite id, first, last) for every cite on a rendered line."""
    out: list[tuple[str, int, int]] = []
    for m in CITE_GROUP.finditer(strip_comments(line)):
        cid = m["a"] or m["b"]
        if m["a"] and not (re.fullmatch(r"\d{2}", cid) or "/" in cid):
            continue
        refs = [m["first"], *re.findall(r":(\d+(?:[–-]\d+)?)", m["more"])]
        for ref in refs:
            parts = [int(x) for x in re.split(r"[–-]", ref)]
            out.append((cid, parts[0], parts[-1]))
    return out


@functools.lru_cache(maxsize=1)
def head_resolves() -> bool:
    return bool(git_out("rev-parse", "--verify", "--quiet", f"{HEAD}^{{commit}}").strip())


def head_ok() -> bool:
    """`origin/main` resolves (the self-test's BROKEN lever says it does not)."""
    return "head" not in BROKEN and head_resolves()


def cite_findings(docs: dict[str, str], fetch: Fetch) -> tuple[list[Finding], int]:
    """G-CITE (every line at the base, non-blank) and G-VERSION (every line of every cited range
    unchanged at `origin/main`; an unresolvable `origin/main` FAILs)."""
    fails: list[Finding] = []
    done: set[tuple[str, int]] = set()
    if not head_ok():
        fails.append(("G-VERSION", f"{HEAD} does not resolve: drift is unread", None, None))
    for doc, text in docs.items():
        for li, line in enumerate(text.split("\n"), 1):
            sec = h2_at(text, li)
            for cid, a, b in cite_refs(line):
                rel = cite_path(cid)
                base_t = fetch(BASE, rel) if rel else None
                if rel is None or base_t is None:
                    fails.append(("G-CITE", f"`{cid}`:{a} no such file", doc, sec))
                    continue
                base = base_t.split("\n")
                if b < a:
                    fails.append(("G-CITE", f"`{cid}`:{a}–{b} is a reversed range", doc, sec))
                    continue
                head_t = fetch(HEAD, rel) if head_ok() else None
                head = head_t.split("\n") if head_t is not None else None
                for n in range(a, b + 1):
                    if (cid, n) in done:
                        continue
                    done.add((cid, n))
                    if n < 1 or n > len(base) or (n in (a, b) and not base[n - 1].strip()):
                        msg = f"`{cid}`:{n} line missing or blank at {BASE}"
                        fails.append(("G-CITE", msg, doc, sec))
                        continue
                    if head_ok() and (head is None or n > len(head) or head[n - 1] != base[n - 1]):
                        msg = f"`{cid}`:{n} drifted at {HEAD}: re-point the cite"
                        fails.append(("G-VERSION", msg, doc, sec))
    for cid, n, frag in CITED:
        rel = cite_path(cid)
        bt = fetch(BASE, rel) if rel else None
        base = bt.split("\n") if bt is not None else []
        if n > len(base) or frag not in base[n - 1]:
            hits = [i + 1 for i, ln in enumerate(base) if frag in ln]
            msg = f'`{cid}`:{n} "{frag[:40]}" not on the line (found {hits[:4]})'
            fails.append(("G-CITE", msg, None, None))
    return fails, len(done) + len(CITED)


# ---------------------------------------------------------------------------- G-QUOTE

# names this spec PROPOSES (no merged source holds them); each must stand beside "PROPOSED"
PROPOSED_NAMES = frozenset(
    {
        "scanner.result_state",
        "scanner.matches_sent_to_watchlist",
        "rank_position",
        "preset_count",
        "live_only_count",
        "stale_inputs",
        "pattern.dashed.estimated",
    }
)
SNAKE = re.compile(r"(?<![\w.$/{-])((?:[a-z][a-z0-9]*\.)?[a-z][a-z0-9]*_[a-z0-9_]+(?:\.\*)?)\b")
SCHEMA = re.compile(r"`([A-Z][a-z]+(?:[A-Z][a-z0-9]+)+)`")
PERM = re.compile(r"`([a-z]+:(?:read|write|manage|arm_live|export))`")
QUOTE_MIN = 12
# G-QUOTE skips the rows other gates own: Table A (G-AROW), the deck (it is the W-n source), the
# mutation rows, §11's T2 cells (G-T2) and §15.1's properties (G-EVENTS)
QUOTE_SKIP = (
    "Table A",
    "13. Copy deck",
    "16.2 The mutation",
    "11. Result actions",
    "15.1 Analytics",
)


def deck(spec: str) -> dict[str, str]:
    return {
        r[0]: r[2]
        for r in table_rows(section(spec, "13. Copy deck"))
        if re.fullmatch(r"W-\d+", r[0]) and len(r) > 2
    }


def template(s: str) -> str:
    """A W-n string as a pattern: each `{slot}` matches one to four words (a slot matching any
    text let every quote holding " to " pass as W-5's range chip)."""
    parts = re.split(r"\{[^{}]*\}", s)
    return r"\S+(?: \S+){0,3}?".join(re.escape(p) for p in parts)


@functools.lru_cache(maxsize=4)
def deck_patterns(spec: str) -> tuple[re.Pattern[str], ...]:
    pats: list[re.Pattern[str]] = []
    for s in deck(spec).values():
        segs = [x.strip() for x in s.split(" · ")]
        for i in range(len(segs)):
            for j in range(i + 1, len(segs) + 1):
                pats.append(re.compile(template(" · ".join(segs[i:j]))))
    return tuple(pats)


def loose(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("’", "'")
    return " ".join(s.split()).lower().rstrip(".")


@functools.lru_cache(maxsize=64)
def pool_text(cids: tuple[str, ...]) -> str:
    texts = list(tickets().values())
    for cid in ("14", "22", *cids):
        rel = cite_path(cid)
        if rel:
            texts.append(git_show(BASE, rel) or "")
    return "\n".join(texts).replace('\\"', '"')


@functools.lru_cache(maxsize=64)
def loose_pool(cids: tuple[str, ...]) -> str:
    return loose(pool_text(cids))


def g_quote(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    pats = deck_patterns(t.spec)
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        skip = {
            ln
            for head in QUOTE_SKIP
            for ln in section(text, head).split("\n")
            if ln.startswith("|")
        }
        for i, line in enumerate(text.split("\n"), 1):
            if line in skip:
                continue
            sec = h2_at(text, i)
            cids = tuple(sorted({c for c, _a, _b in cite_refs(line)}))
            pool = pool_text(cids)
            lpool = loose_pool(cids)
            rendered = strip_comments(line)
            for c in CODE.finditer(rendered):
                for m in SNAKE.finditer(c[0][1:-1]):
                    name = m[1]
                    stem = name.removesuffix(".*")
                    if name in PROPOSED_NAMES or stem in pool:
                        continue
                    bad.append(F("G-QUOTE", f"{doc}:{i} `{name}` is in no cited text", doc, sec))
            for m in SCHEMA.finditer(rendered):
                if m[1] not in schema_names() and m[1] not in pool:
                    bad.append(F("G-QUOTE", f"{doc}:{i} `{m[1]}` is not a `22` schema", doc, sec))
            for m in PERM.finditer(rendered):
                if f'"{m[1]}"' not in at_base(CITE_FILES["SEED"]):
                    bad.append(F("G-QUOTE", f"{doc}:{i} `{m[1]}` is not a permission", doc, sec))
            for q in QUOTED.finditer(CODE.sub(" ", rendered)):
                s = q[0][1:-1]
                if len(s) < QUOTE_MIN or loose(s) in lpool or s == OWNER_PENDING:
                    continue
                if any(p.fullmatch(s) for p in pats):
                    continue
                bad.append(F("G-QUOTE", f"{doc}:{i} {s[:50]!r} is neither cited nor W-n", doc, sec))
    return bad


# ---------------------------------------------------------------------------- the gates
#
# Each gate returns findings (tag, message, doc, section). A lexicon gate reads rendered clauses
# (comments stripped, NFKC, markup dropped, lower case); quoted copy is not a claim.


def g_penpot(t: Texts) -> list[Finding]:
    """BQ-1, S-3: no host, link or URL in either doc; §0 cites the page by name and id only."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if URL.search(CODE.sub(" ", strip_comments(line))):
                bad.append(F("G-PENPOT", f"{doc}:{i} a URL or host", doc, h2_at(text, i)))
    if "cited by name and page id only" not in norm_text(section(t.spec, "0. Status")):
        msg = "§0 does not cite the page by name and id only"
        bad.append(F("G-PENPOT", msg, "spec", spec_sec(t, "0. Status")))
    return bad


def g_unbuilt(t: Texts) -> list[Finding]:
    """BQ-1: §0 states the scanner UI is unbuilt and that the spec is the implementation
    contract; the base holds no scanner feature slice."""
    sec = spec_sec(t, "0. Status")
    body = norm_text(section(t.spec, "0. Status"))
    bad = [
        F("G-UNBUILT", f"§0 lacks {n!r}", "spec", sec)
        for n in ("the scanner ui is unbuilt.", "this spec is the implementation contract")
        if norm_text(n) not in body
    ]
    feats = git_out("ls-tree", "--name-only", BASE, "apps/web/src/features/")
    if "scanner" in feats:
        bad.append(F("G-UNBUILT", "a scanner slice exists at the base", "spec", sec))
    return bad


def g_trace(t: Texts) -> list[Finding]:
    """BQ-1: the trace holds AC1 ... AC6."""
    rows = table_rows(section(t.spec, "Acceptance-criteria trace"))
    got = [m[0] for r in rows if (m := re.match(r"AC\d", r[0]))]
    want = [f"AC{n}" for n in range(1, 7)]
    if got != want:
        sec = spec_sec(t, "Acceptance-criteria trace")
        return [F("G-TRACE", f"the trace rows read {got}", "spec", sec)]
    return []


def g_ruled(t: Texts) -> list[Finding]:
    """The RULED heading cites the ruling and the BQ list; every comment id is on the list."""
    bad: list[Finding] = []
    head = next((ln for ln in t.spec.split("\n") if ln.startswith("## The questions")), "")
    sec = spec_sec(t, "The questions")
    if f"comment {RULING_ID}, on the BQ list {BQ_LIST_ID}" not in head:
        bad.append(F("G-RULED", "the RULED heading does not cite the ruling", "spec", sec))
    if "every default is taken." not in norm_text(section(t.spec, "The questions")):
        bad.append(F("G-RULED", "the RULED section lacks 'Every default is taken.'", "spec", sec))
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            for cid in COMMENT_ID.findall(line):
                if cid not in RULED_IDS:
                    bad.append(F("G-RULED", f"{cid} is not a ruling comment", doc, h2_at(text, i)))
    return bad


def g_boards(t: Texts) -> list[Finding]:
    """BQ-24: ten boards at most, twins at most a third, each twin of a dark board; the window
    and the reference width; illustrative values marked."""
    sec = spec_sec(t, "0. Status")
    rows = board_rows(t.spec)
    bad: list[Finding] = []
    twins = [r for r in rows if is_twin(r)]
    if len(rows) > MAX_BOARDS or Fraction(len(twins), max(len(rows), 1)) > TWIN_SHARE:
        bad.append(F("G-BOARDS", f"{len(rows)} boards, {len(twins)} twins", "spec", sec))
    ids = [r[0] for r in rows]
    if ids != [f"{n:02d}" for n in range(1, len(rows) + 1)]:
        bad.append(F("G-BOARDS", f"board numbers {ids}", "spec", sec))
    by = {r[0]: r for r in rows}
    for r in rows:
        if len(r) < 5 or r[4] != FRAME_STATUS or not r[1].startswith(f"`E08-D08 / {r[0]} "):
            bad.append(F("G-BOARDS", f"board {r[0]}: name or status", "spec", sec))
            continue
        m = re.fullmatch(r"(light|high-contrast) twin of (\d{2})", r[2])
        if is_twin(r):
            src = by.get(m[2]) if m else None
            want = {"light": "light", "high-contrast": "hc"}[m[1]] if m else ""
            if src is None or is_twin(src) or src[3] != "dark" or r[3] != want:
                bad.append(F("G-BOARDS", f"board {r[0]}: a twin of no dark board", "spec", sec))
        elif r[3] != "dark":
            bad.append(F("G-BOARDS", f"board {r[0]}: a first board not in dark", "spec", sec))
    if {f.get("Board") for f in frames(t.spec)} != set(by):
        bad.append(F("G-BOARDS", "a board draws no frame of §16.1", "spec", sec))
    body = norm_text(section(t.spec, "0. Status"))
    for n in (
        "each frame a",
        "window (`16`:212) holding the panel at d07's",
        "px reference width",
        "illustrative values, not a market capture",
        "every board marks each column that waits on its field with the g-row it waits on",
    ):
        if norm_text(n) not in body:
            bad.append(F("G-BOARDS", f"§0 lacks {n!r}", "spec", sec))
    return bad


def g_frame(t: Texts) -> list[Finding]:
    """BQ-24: the frame register, column by column."""
    sec = spec_sec(t, FRAME_HEAD)
    boards = {r[0]: r for r in board_rows(t.spec)}
    cmps = set(re.findall(r"^### (CMP-\d{3})\b", plan("15"), MULTI))
    copy_ids = set(deck(t.spec))
    bad: list[Finding] = []
    for f in frames(t.spec):
        fid = f["Frame"]
        theme = fid.rsplit("· ", 1)[-1].rstrip("`")
        b = boards.get(f.get("Board", ""))
        if b is None or b[3] != f.get("Theme") or theme != f.get("Theme"):
            bad.append(F("G-FRAME", f"{fid}: Board / Theme", "spec", sec))
        for c in re.findall(r"CMP-\d+", f.get("Components", "")):
            if c not in cmps:
                bad.append(F("G-FRAME", f"{fid}: {c} is not a catalogue entry", "spec", sec))
        copy = re.findall(r"\b[A-Z]-\d+\b", f.get("Copy", ""))
        if not copy or any(c not in copy_ids for c in copy):
            bad.append(F("G-FRAME", f"{fid}: copy {copy} not all W-n of §13", "spec", sec))
        for tok in re.findall(r"`([a-z][a-z0-9.*-]+)`", f.get("Tokens", "")):
            if any(resolve(load_theme(th), tok) == "MISSING" for th in THEMES):
                bad.append(F("G-FRAME", f"{fid}: {tok} does not resolve", "spec", sec))
        if f.get("Status") != FRAME_STATUS:
            bad.append(F("G-FRAME", f"{fid}: status {f.get('Status')!r}", "spec", sec))
    drawn: dict[str, set[str]] = {}
    for f in frames(t.spec):
        drawn.setdefault(f.get("Board", ""), set()).add(f["Frame"].rsplit(" · ", 1)[0])
    rows = {r[0]: r for r in board_rows(t.spec)}
    for b in rows.values():
        m = re.search(r"twin of (\d{2})", b[2]) if len(b) > 2 else None
        src = rows.get(m[1]) if m else None
        if not m or src is None or is_twin(src) or b[0] not in drawn:
            continue  # G-BOARDS owns a twin of no dark board and a board with no frame
        if drawn[b[0]] != drawn.get(m[1], set()):
            bad.append(
                F("G-FRAME", f"board {b[0]} does not draw every frame of {m[1]}", "spec", sec)
            )
    return bad


LOCKED_LEADS = ("D04", "D07", "D07", "E25-D05", "E08-D06", "E09-D09")
# each locked row's first cite must sit on the line holding its fragment
LOCKED_FRAG = (
    "| State | Text token",
    "| D1  |",
    "The 40-symbol cap is a security control.",
    'the literal word "estimated" is in the accessible name',
    "**F1 Strings, not floats.**",
    "`rbac.permission`",
)


def g_locked(t: Texts) -> list[Finding]:
    """BQ-2: §1.3's locked inputs, each cited where it says."""
    sec = spec_sec(t, "1.3 Locked")
    rows = table_rows(section(t.spec, "1.3 Locked"))
    leads = tuple(r[0].split(" ")[0] for r in rows)
    bad: list[Finding] = []
    if leads != LOCKED_LEADS:
        bad.append(F("G-LOCKED", f"§1.3 rows read {leads}", "spec", sec))
    for r, frag in zip(rows, LOCKED_FRAG, strict=False):
        lead = r[0].split(" ")[0]
        refs = cite_refs(r[1]) if len(r) > 1 else []
        if not refs:
            bad.append(F("G-LOCKED", f"{lead}: no cite", "spec", sec))
            continue
        cid, n, _b = refs[0]
        if frag not in base_line(cid, n):
            bad.append(F("G-LOCKED", f"{lead}: {cid}:{n} is not where it says", "spec", sec))
    return bad


A_IDS = tuple(f"A-{n}" for n in range(1, 13))


def a_rows(hand: str) -> dict[str, list[str]]:
    return {r[0]: r for r in table_rows(section(hand, "Table A")) if r[0].startswith("A-")}


def unescape(cell: str) -> str:
    return cell.replace("\\|", "|")


def g_arow(t: Texts) -> list[Finding]:
    """BQ-3: departures ship as copy-ready A-rows; each Old is verbatim and whole at the base;
    §B routes every row; a New stating the cap states the computed one."""
    sec = h2_of(t.hand, "§C Copy-ready")
    rows = a_rows(t.hand)
    bad: list[Finding] = []
    if tuple(rows) != A_IDS:
        bad.append(F("G-AROW", f"Table A rows read {list(rows)}", "hand", sec))
    routed = norm_text(section(t.hand, "§B Who applies"))
    if not all(norm_text(x) in routed for x in ("A-1 … A-8", "A-9 … A-11", "A-12")):
        bad.append(F("G-AROW", "§B does not route every A-row", "hand", h2_of(t.hand, "§B")))
    cap = t.values.get("CITE:cap", "")
    a3 = rows.get("A-3", [])
    if len(a3) > 4 and re.search(r"live.only", a3[4], re.IGNORECASE):
        bad.append(F("G-AROW", "A-3 lists live-only rows as a state (R-4)", "hand", sec))
    a5 = rows.get("A-5", [])
    if len(a5) < 5 or "- **Interactions:**" not in a5[4] or "Interactions/hotkeys" in a5[4]:
        bad.append(F("G-AROW", "A-5 does not keep the `**Interactions:**` marker", "hand", sec))
    if "`**Interactions:**`, never `**Interactions/hotkeys:**`" not in t.hand:
        bad.append(F("G-AROW", "§B lacks the keymap-lint reason for A-5", "hand", sec))
    for aid, r in rows.items():
        if len(r) < 5:
            bad.append(F("G-AROW", f"{aid}: cells", "hand", sec))
            continue
        old, new = unescape(r[3]), unescape(r[4])
        if old == "—":
            continue
        refs = cite_refs(r[2])
        if not refs:
            bad.append(F("G-AROW", f"{aid}: no cite", "hand", sec))
            continue
        cid, n, _b = refs[0]
        line = base_line(cid, n)
        whole = pin_norm(line) == pin_norm(old)
        clause = re.search(rf"; {re.escape(old)}(?: |$)", line.strip()) is not None
        if not (whole or clause):
            bad.append(
                F("G-AROW", f"{aid}: Old is not whole and verbatim at {cid}:{n}", "hand", sec)
            )
        if old == new:
            bad.append(F("G-AROW", f"{aid}: New equals Old", "hand", sec))
        for m in re.finditer(r"capped at (\d+)", new):
            if m[1] != cap:
                bad.append(F("G-AROW", f"{aid}: New caps at {m[1]}, not {cap}", "hand", sec))
    bad += a12_findings(rows.get("A-12", []), sec)
    return bad


A12_NEW = ("no nested button", "no `EstimatedBadgeHost` context", "selects the criterion", "§3.3")


def a12_findings(r: list[str], sec: str) -> list[Finding]:
    """Lens 1 Major 2: A-12's Old is the whole host clause of CMP-227's A11y line (never only its
    "CMP-133 is the only host today" tail), and its New says how the option embeds the look."""
    refs = cite_refs(r[2]) if len(r) > 4 else []
    if not refs:
        return [F("G-AROW", "A-12: no row or no cite", "hand", sec)]
    m = re.search(r"embedded only by a host — (.+?); ", base_line(refs[0][0], refs[0][1]))
    host = m[1] if m else "(no host clause at the cite)"
    old, new = unescape(r[3]), unescape(r[4])
    bad = [] if host in old else [F("G-AROW", "A-12: Old lacks the whole host clause", "hand", sec)]
    bad += [F("G-AROW", f"A-12: New lacks {n!r}", "hand", sec) for n in A12_NEW if n not in new]
    return bad


HANDA_HEAD = "§A Hand-off checklist"


def g_handoff(t: Texts) -> list[Finding]:
    """`16` §11.4: every §A cell is ticked with its evidence or unticked with its reason; the
    keyboard evidence stands in spec §12.1; the sparkline never animates; §F points E08-T09 at
    the ledger, Rank by, the pane kind and the series."""
    sec = h2_of(t.hand, HANDA_HEAD)
    raw = section(t.hand, HANDA_HEAD)
    rows = table_rows(raw)
    bad: list[Finding] = []
    if "Rule: every line is `[x]` with its evidence, or `[ ]` with the reason." not in raw:
        bad.append(F("G-HANDOFF", "§A lacks its rule line", "hand", sec))
    for r in rows:
        for c in r[1:]:
            if not re.match(r"\[(?:x| )\] \S", c):
                bad.append(
                    F("G-HANDOFF", f"§A {r[0]}: a cell without tick and evidence", "hand", sec)
                )
    by = {r[0]: r for r in rows}
    grid = section(t.spec, "12.1 The grid")
    for k in re.findall(r"`[^`]+`", (by.get("Keyboard table", []) + ["", ""])[1]):
        if k not in grid:
            bad.append(
                F("G-HANDOFF", f"§A keyboard evidence {k} is not in spec §12.1", "hand", sec)
            )
    if (by.get("Motion pair", []) + ["", "", ""])[2] != "[x] none: never animated":
        bad.append(F("G-HANDOFF", "§A: the sparkline's motion cell", "hand", sec))
    t09 = next(
        (r for r in table_rows(section(t.hand, "§F Consumer")) if r[0] == "E08-T09 (#4708)"), []
    )
    for n in ("§2.1", "§5.1", "§8.3", "§17.2"):
        if len(t09) < 2 or n not in t09[1]:
            bad.append(F("G-HANDOFF", f"§F's E08-T09 row lacks {n}", "hand", h2_of(t.hand, "§F")))
    return bad


g_handoff_words = lexicon(
    "G-HANDOFF",
    "a §A cell allowed blank",
    r"\b(?:blank|empty|unticked|unmarked)\b (?:\w+ ){0,2}?(?:is |are )?(?:acceptable|allowed|fine"
    r"|ok|permitted)\b|\b(?:left|leave|stay)s? (?:\w+ )?(?:blank|empty)\b",
    doc="hand",
)


def g_close(t: Texts) -> list[Finding]:
    """BQ-1: a text-first doc names no closing keyword before an issue number."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if re.search(
                r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#\d", norm_text(line)
            ):
                bad.append(F("G-CLOSE", f"{doc}:{i} a closing keyword", doc, h2_at(text, i)))
    return bad


CHARSET_ALLOW = frozenset("…")
INVISIBLE = frozenset("\u00ad\u200b\u200c\u200d\u2060\ufeff\t")  # NFKC keeps these


def g_charset(t: Texts) -> list[Finding]:
    """No compatibility character NFKC would fold beyond CHARSET_ALLOW, no invisible character
    or tab (NFKC keeps them), no CR, no trailing whitespace."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            odd = [
                c
                for c in line
                if c in INVISIBLE
                or (c not in CHARSET_ALLOW and unicodedata.normalize("NFKC", c) != c)
            ]
            whys = [f"U+{ord(c):04X}" for c in odd[:1]]
            whys += ["a CR"] if "\r" in line else []
            whys += ["trailing whitespace"] if line != line.rstrip() else []
            if whys:
                bad.append(F("G-CHARSET", f"{doc}:{i} {', '.join(whys)}", doc, h2_at(text, i)))
    return bad


def g_cells(t: Texts) -> list[Finding]:
    """Every table row has its header's cell count (an escaped pipe is not a separator)."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        width = 0
        for i, ln in enumerate(text.split("\n"), 1):
            if not re.match(r"^ {0,3}\|", ln):
                width = 0
                continue
            n = len(split_row(ln))
            if width == 0:
                width = n
            elif n != width:
                msg = f"{doc}:{i} {n} cells, its header has {width}"
                bad.append(F("G-CELLS", msg, doc, h2_at(text, i)))
    return bad


# ---- §3 the criteria (BQ-6, BQ-7, BQ-8)

CRITERIA = (
    ("24 h change %", "live", "no"),
    ("Turnover 24 h (USDT)", "live", "no"),
    ("Funding %", "live", "no"),
    ("OI Δ 24 h %", "recorded history", "no"),
    ("Spread (bps)", "live", "no"),
    ("Tape speed z-score", "recorded history", "yes"),
    ("24 h range %", "live", "no"),
    ("Regime", "recorded history", "yes"),
)
UNITS_OF = ("%", "USDT", "%", "%", "bps", "z", "%", "class")


def w_segments(spec: str, wid: str) -> list[str]:
    return [x.strip() for x in deck(spec).get(wid, "").split(" · ")]


def g_criteria(t: Texts) -> list[Finding]:
    """BQ-6: the eight criteria in that order and those units; labels are W-1; the estimated
    and recorded-history sets; every source field exists in `22`."""
    sec = spec_sec(t, CRIT_HEAD)
    rows = crit_rows(t.spec)
    got = tuple((r[1], r[4], r[5]) for r in rows if len(r) > 5)
    bad: list[Finding] = []
    if got != CRITERIA:
        bad.append(F("G-CRITERIA", f"§3.1 rows read {[g[0] for g in got]}", "spec", sec))
    if tuple(r[3] for r in rows if len(r) > 3) != UNITS_OF:
        bad.append(F("G-CRITERIA", "§3.1 units", "spec", sec))
    if w_segments(t.spec, "W-1") != [c[0] for c in CRITERIA]:
        bad.append(F("G-CRITERIA", "W-1 differs from §3.1", "spec", sec))
    fields = set(schema_props("ScannerRow")) | set(schema_props("Ticker"))
    for r in rows:
        for f in re.findall(r"`([a-z_0-9]+)`", r[2] if len(r) > 2 else ""):
            if f not in fields and f not in pool_text(("24",)):
                bad.append(F("G-CRITERIA", f"{r[1]}: `{f}` is not a source field", "spec", sec))
    if [r[6] for r in rows if len(r) > 6 and r[6] != "in `ScannerRow`"] != ["D08-G2"] * 7:
        bad.append(F("G-CRITERIA", "§3.1 Contract column", "spec", sec))
    body = norm_text(section(t.spec, CRIT_HEAD))
    for n in (
        '"turnover 24 h (usdt)" stands for t\'s "volume"',
        "`volume_24h` stays an optional column",
        "are not offered as criteria",
        "no class list is fixed here",
    ):
        if norm_text(n) not in body:
            bad.append(F("G-CRITERIA", f"§3.1 lacks {n!r}", "spec", sec))
    return bad


VOL_FORMULA = "(`high_24h` − `low_24h`) ÷ `low_24h` × 100, from `Ticker`"


def g_volatility(t: Texts) -> list[Finding]:
    """BQ-7: 24 h range % exactly as ruled; labelled so everywhere, never the bare word."""
    head = "3.2 24 h range %"
    sec = spec_sec(t, head)
    raw = section(t.spec, head)
    bad: list[Finding] = []
    if VOL_FORMULA not in raw:
        bad.append(F("G-VOLATILITY", "§3.2's formula is not the ruled one", "spec", sec))
    body = norm_text(raw)
    for n in (
        "in decimal arithmetic",
        'labelled "24 h range %" in every place, never the bare word "volatility"',
        "live for every symbol and not estimated",
    ):
        if norm_text(n) not in body:
            bad.append(F("G-VOLATILITY", f"§3.2 lacks {n!r}", "spec", sec))
    for wid, s in deck(t.spec).items():
        if re.search(r"volatil", s, re.IGNORECASE):
            bad.append(F("G-VOLATILITY", f"{wid} uses the bare word", "spec", spec_sec(t, "13.")))
    for f in frames(t.spec):
        if re.search(r"volatil", f.get("State", ""), re.IGNORECASE):
            bad.append(F("G-VOLATILITY", f"{f['Frame']}: the bare word", "spec", None))
    return bad


g_volatility_words = lexicon(
    "G-VOLATILITY",
    "volatility as a label or a column",
    r"\bvolatility\b",
    near=r"\b(?:label\w*|column|header|criterion|option|chip|reads?)\b",
    unless=r"bare word|d08-q1|realised|atr|alternative",
)


def g_owner(t: Texts) -> list[Finding]:
    """BQ-7, BQ-13: the two OWNER defaults are PROPOSED, owner approval pending (#2701)."""
    bad: list[Finding] = []
    for head in ("3.2 24 h range %", "6. Symbols we do not record"):
        line = next((ln for ln in t.spec.split("\n") if ln.lstrip("# ").startswith(head)), "")
        if OWNER_PENDING not in line:
            msg = f"§{head.split(' ')[0]} lacks the owner marker"
            bad.append(F("G-OWNER", msg, "spec", spec_sec(t, head)))
    q = section(t.spec, "17.3 Open questions")
    for qid in ("D08-Q1", "D08-Q2"):
        m = re.search(rf"\*\*{qid}\*\*[^\n]*", q)
        if not m or OWNER_PENDING not in m[0]:
            bad.append(F("G-OWNER", f"{qid} lacks the owner marker", "spec", spec_sec(t, "17.")))
    if "**BQ-7** and **BQ-13** are the owner's" not in section(t.spec, "The questions"):
        msg = "the RULED section does not name BQ-7 and BQ-13"
        bad.append(F("G-OWNER", msg, "spec", spec_sec(t, "The questions")))
    return bad


def g_estimated(t: Texts) -> list[Finding]:
    """BQ-8, AC1: the marker lives in the option itself; never a nested button; the drawer
    from the note's link; funding not badged until C7."""
    head = "3.3 Estimated"
    sec = spec_sec(t, head)
    body = norm_text(section(t.spec, head))
    bad: list[Finding] = []
    for n in (
        "the marker lives in the option itself",
        "the option's accessible name carries the word",
        "never a nested button",
        "outside the list",
        "funding is not badged until",
        "the badge follows the descriptor",
        "never from a catalogue adjective",
        'the cell text is never "est."',
        "(a departure from `15`:2675 at the base: d08-c8, a-12)",
        "the embedded look is presentational: no role, no tabindex, its glyph `aria-hidden`",
        "the one-line note (w-3, w-4) stands in for it",
        "the header's accessible name is its text, the word once",
        "the drawer opens from the derivation note's link",
    ):
        if norm_text(n) not in body:
            bad.append(F("G-ESTIMATED", f"§3.3 lacks {n!r}", "spec", sec))
    want = [f"{c[0]} (estimated)" for c in CRITERIA if c[2] == "yes"]
    if w_segments(t.spec, "W-2") != want:
        bad.append(F("G-ESTIMATED", "W-2 is not the estimated set", "spec", sec))
    return bad


g_nested = lexicon(
    "G-ESTIMATED",
    "a nested button or a badged funding criterion",
    r"\bnested (?:button|control)\b|\bbutton (?:inside|within|in) (?:the |each |an? )?options?\b"
    r"|\b(?:two|2) (?:tab )?stops per option\b"
    r"|\b(?:button|control)s? (?:inside|within|in) (?:the |each |an? )?(?:column )?headers?\b"
    r"|\bheaders? (?:holds?|carr(?:y|ies)|contains?) (?:an? |its )?(?:own )?(?:badge )?buttons?\b"
    r"|\bfunding (?:% )?(?:is |gets |carries )?(?:badged|estimated|an estimate|flagged)\b",
)
g_estimated_words = lexicon(
    "G-ESTIMATED",
    "an estimated criterion left unbadged or called exact",
    r"\bnot (?:badged|estimated|flagged)\b|\bno (?:badge|marker)\b|\bunbadged\b|\bexact\b",
    near=r"\bz.?score\b|\bregime\b",
    unless=r"d08.c6|records|descriptor",
    heads=("3.3 Estimated", "8.1 Columns"),
)


FILTERBAR_W6 = (
    "{Funding %} range",
    "{Funding %} minimum",
    "{Funding %} maximum",
    "Regime classes",
    "Remove {Funding %} filter",
)


def g_filterbar(t: Texts) -> list[Finding]:
    """BQ-9, AC3 (folds of lens 3 M4, M5, m6-m8; lens 1 m4): the chips' spoken names; a chip
    is two sibling buttons, its remove button named and focus kept; the popover and fields named
    by the criterion; Regime's class editor and its empty set; commit-time parsing; W-3 marked a
    placeholder."""
    head = "4.1 Anatomy"
    sec = spec_sec(t, head)
    body = norm_text(section(t.spec, head))
    bad: list[Finding] = []
    for n in (
        "each chip's accessible name is w-5's spoken form",
        "the symbols visible only",
        "a chip is two sibling buttons, never nested",
        "its remove button, cmp-011's labelled iconbutton",
        "focus then moves to the next chip, else the previous one, else add filter",
        "the popover is a dialog named by its criterion",
        "a cmp-005 checkbox per class the descriptor lists",
        "with no class checked apply is disabled, so an empty set is never a filter",
        "when the field commits, on blur or apply, never mid-keystroke",
        "so `home` and `end` do nothing",
        "a proposed placeholder there that `detectormethodology.assumption` replaces",
    ):
        if norm_text(n) not in body:
            bad.append(F("G-FILTERBAR", f"§4.1 lacks {n!r}", "spec", sec))
    w6 = w_segments(t.spec, "W-6")
    for n in FILTERBAR_W6:
        if n not in w6:
            bad.append(F("G-FILTERBAR", f"W-6 lacks {n!r}", "spec", deck_sec(t)))
    w5 = w_segments(t.spec, "W-5")
    if not any(" is at most " in x for x in w5) or not any(x.startswith("Regime is ") for x in w5):
        bad.append(F("G-FILTERBAR", "W-5 lacks the spoken form or Regime's form", "spec", sec))
    return bad


g_filterbar_words = lexicon(
    "G-FILTERBAR",
    "an empty class set filtering, or text refused while typed",
    r"\b(?:refus|reject|check|validat|pars)\w* (?:\w+ ){0,2}?(?:at entry|as (?:it is )?typed"
    r"|on (?:each|every) keystroke|per keystroke|mid.keystroke)\b"
    r"|\bempty (?:class )?set (?:is|counts as|acts as) an? (?:filter|match)\b"
    r"|\bno class (?:checked|selected) (?:matches|filters|applies)\b",
    heads=("4.1 Anatomy", "4.2 The rule"),
)


def g_range(t: Texts) -> list[Finding]:
    """BQ-9, AC3: strict min < max; min == max refused; the `14` text verbatim, prefixed with
    the criterion; the previous results stay; polling goes on with the last valid set."""
    head = "4.2 The rule"
    sec = spec_sec(t, head)
    body = norm_text(section(t.spec, head))
    bad: list[Finding] = []
    for n in (
        "**strict min < max**",
        "min == max is refused",
        "the `14` text prefixed with the criterion",
        "**the previous results stay**",
        "polling continues on the last valid filter set",
        '"showing results for the previous filters."',
        "its text is `color.text.primary`",
        "`color.status.danger.strong` marks only the ✕ glyph and the invalid boundary",
    ):
        if norm_text(n) not in body:
            bad.append(F("G-RANGE", f"§4.2 lacks {n!r}", "spec", sec))
    core = grab(r'\("([^"]+)"\)', base_line("14", 2273), "14:2273 error")
    if deck(t.spec).get("W-7") != f"{{Funding %}}: {core}.":
        msg = "W-7 is not the criterion + `14`:2273 verbatim"
        bad.append(F("G-RANGE", msg, "spec", spec_sec(t, "13. Copy deck")))
    return bad


g_range_words = both(
    lexicon(
        "G-RANGE",
        "results cleared on an invalid range",
        r"\b(?:clear(?:s|ed|ing)?|empt(?:y|ies|ied)|blank(?:s|ed)?|hid(?:e|es|den)|discard\w*"
        r"|drop(?:s|ped)?|wip(?:e|es|ed)|reset\w*)\b",
        near=r"\bresults?\b|\btable\b|\bgrid\b",
        heads=("4.1 Anatomy", "4.2 The rule"),
    ),
    lexicon(
        "G-RANGE",
        "min equal to max accepted",
        r"\b(?:min (?:==|=|equals?|equal to|the same as) max\w*|equal (?:min|bounds))\b",
        near=r"\b(?:allowed|accepted|valid|exactly|fine|kept|applies)\b",
    ),
)


def g_rank(t: Texts) -> list[Finding]:
    """BQ-12, AC2: Rank by is the server `sort` and picks the set; headers sort it on the client
    and never send a request; the default is Turnover 24 h."""
    head = "5.1 Rank by"
    sec = spec_sec(t, head)
    body = norm_text(section(t.spec, head))
    bad: list[Finding] = []
    for n in (
        "**rank by** is the server `sort`",
        "default turnover 24 h",
        "it picks which",
        "**column headers sort those",
        "on the client** and never send a request",
        "the cap note says both",
        "its options are §3.1's criteria except regime, a class, and each ranks highest first",
        "no direction control is drawn",
        "rows open in the rank by order with no header marked",
        "a header cycles descending, ascending, then back to the rank by order",
        "only the sorted header carries `aria-sort`",
        "a rank by, filter or preset change clears the header sort",
        "w-15's slot names the header sort, or the rank by criterion while none is set",
    ):
        if norm_text(n) not in body:
            bad.append(F("G-RANK", f"§5.1 lacks {n!r}", "spec", sec))
    m = re.search(r"default ([^():]+?) \(D08-G3\)", section(t.spec, head))
    default = m[1] if m else ""
    first = re.search(r"ranked by ([^,.]+)", section(t.spec, "10.2 Default"))
    seen = {
        "§10.2's first use": (first[1] if first else "", spec_sec(t, "10.2 Default")),
        "W-9": ((w_segments(t.spec, "W-9") + [""])[1], deck_sec(t)),
    }
    for where, (got, at) in seen.items():
        if not default or got != default:
            bad.append(F("G-RANK", f"{where} ranks by {got!r}, not {default!r}", "spec", at))
    return bad


g_rank_words = lexicon(
    "G-RANK",
    "a header sort that asks the server",
    r"\b(?:re.?quer\w*|re.?request\w*|requests?|fetch\w*|calls? the server|server(?:-side)?)\b",
    near=r"\b(?:headers?|column sort\w*|header sort\w*)\b",
    unless=r"rank by is the server|picks which|sortable table|header row",
)
g_rank_universe = lexicon(
    "G-RANK",
    "a header sort over the universe",
    r"\buniverse\b|\ball (?:matching )?instruments\b|\bevery match\w*\b",
    near=r"\b(?:headers?|column sort\w*|header sort\w*)\b",
    unless=r"rank by|never",
)


def g_hold(t: Texts) -> list[Finding]:
    """BQ-12: D07 D5's hold applies."""
    return require(
        "G-HOLD",
        "5.1 Rank by",
        (
            "d07 d5's hold applies",
            "held while the pointer or focus is in the grid",
            '"paused" and "re-sort"',
            "one polite line says w-20 first",
            "the hold covers order, not membership",
        ),
    )(t)


def deck_sec(t: Texts) -> str:
    """The `##` key of the copy deck: a finding about a W-n string is reported there."""
    return spec_sec(t, "13. Copy deck")


def g_cap(t: Texts) -> list[Finding]:
    """BQ-11, AC2: the panel requests the cap; the count never guesses a total; the note's
    figures are the cap; the note is linked by `aria-describedby`."""
    head = "5.2 The cap"
    sec = spec_sec(t, head)
    raw = section(t.spec, head)
    body = norm_text(raw)
    cap = t.values.get("CITE:cap", "")
    dsec = deck_sec(t)
    bad: list[Finding] = []
    if not re.search(rf"`limit` = (?:{cap}<!--=CITE:cap-->|\{{\{{CITE:cap\}}\}})", raw):
        bad.append(F("G-CAP", "§5.2 does not request the cap", "spec", sec))
    for n in ("never a guessed total", "linked by `aria-describedby`"):
        if norm_text(n) not in body:
            bad.append(F("G-CAP", f"§5.2 lacks {n!r}", "spec", sec))
    for i, ln in enumerate(t.spec.split("\n"), 1):
        work = QUOTED.sub(" ", CODE.sub(" ", ln))
        for m in re.finditer(
            r"\b(?:capped at|cap of|limit(?:ed)? (?:to|at)) (\d+)(?!\d)(?!<!--=CITE)", work
        ):
            if m[1] != cap:
                bad.append(F("G-CAP", f"line {i}: a cap of {m[1]}", "spec", h2_at(t.spec, i)))
    for wid in ("W-10", "W-11", "W-22"):
        s = deck(t.spec).get(wid, "")
        for m in re.finditer(r"(\d+)(\+)? matches|first (\d+) matches|these (\d+) only", s):
            if m[2] or m[3] or m[4]:
                num = m[1] if m[2] else (m[3] or m[4])
                if num != cap:
                    bad.append(F("G-CAP", f"{wid} names {num}, not the cap {cap}", "spec", dsec))
    return bad


g_cap_words = lexicon(
    "G-CAP",
    "a guessed or estimated total",
    r"\b(?:approximate\w*|estimated|about|roughly|around|~|projected|extrapolated|predicted"
    r"|likely|expected|guessed|inferred) (?:\d+ |the )?(?:total|matches|count)\b",
    heads=("5.2 The cap",),
)


def g_liveonly(t: Texts) -> list[Finding]:
    """BQ-13: included and flagged; the chip; the cells' name; the note in `14`:2279's words;
    the split count; the recorded-history criteria."""
    head = "6. Symbols we do not record"
    sec = spec_sec(t, head)
    body = norm_text(section(t.spec, head))
    bad: list[Finding] = []
    for n in (
        "**such a row is included and flagged.**",
        'it carries the "live only" chip',
        "not a new state",
        '"—" with the accessible name "not evaluated: not recorded"',
        "`14`:2279's words",
        '"scanning is limited to live metrics for symbols we are not recording."',
        '"143 matches · 38 live only"',
    ):
        if norm_text(n) not in body:
            bad.append(F("G-LIVEONLY", f"§6 lacks {n!r}", "spec", sec))
    if norm_text("capped, it reads") not in body:
        bad.append(F("G-LIVEONLY", "§6 lacks the capped split count", "spec", sec))
    w11 = deck(t.spec).get("W-11", "")
    if "200+ matches · {38} live only" not in w11 or "{143} matches · {38} live only" not in w11:
        bad.append(F("G-LIVEONLY", "W-11 lacks a split count form", "spec", deck_sec(t)))
    status = next((r for r in table_rows(section(t.spec, "8.1 Columns")) if r[0] == "Status"), [])
    if len(status) < 3 or "both when both apply" not in status[2]:
        msg = "§8.1's Status cell drops one of two chips"
        bad.append(F("G-LIVEONLY", msg, "spec", spec_sec(t, "8.1 Columns")))
    words = grab(r"'([^']+)' note", base_line("14", 2279), "14:2279 note")
    if w_segments(t.spec, "W-12")[-1].lower().rstrip(".") != words.lower():
        bad.append(F("G-LIVEONLY", "W-12's note is not `14`:2279's words", "spec", sec))
    return bad


LIVEONLY_OUT = (
    r"\b(?:exclud\w*|drop(?:s|ped)?|omit\w*|hid(?:e|es|den)|zero(?:ed)?|ranked as zero"
    r"|left out|filtered out|not counted|removed|set aside|put aside|prun\w*|discard\w*"
    r"|suppress\w*|skip(?:s|ped)? (?:the |such )?rows?|withheld|cut)\b"
    r"|\bnew (?:data.confidence )?state\b|\bat most one chip\b"
)
g_liveonly_words = both(
    lexicon(
        "G-LIVEONLY",
        "live-only rows dropped, zeroed or a new state",
        LIVEONLY_OUT,
        near=r"\blive.only\b|\bnot recorded\b|\bnever.recorded\b",
        heads=("8.1 Columns",),
    ),
    lexicon(  # §6 is about those rows: no subject word is needed there
        "G-LIVEONLY",
        "live-only rows dropped, zeroed or a new state",
        LIVEONLY_OUT,
        heads=("6. Symbols we do not record",),
    ),
)


def g_pane(t: Texts) -> list[Finding]:
    """BQ-5: a workspace pane of the kind D08-G10 asks for, binding no symbol; one poll per pane; the
    server cache shared."""
    return require(
        "G-PANE",
        "2.1 Placement",
        (
            "of the pane kind d08-g10 asks for (no `scanner` `panekind` at the base)",
            "binds neither `symbol` nor `interval_code`",
            "one pane is one filter set and one poll",
            "share t09's server cache",
        ),
    )(t)


g_pane_words = lexicon(
    "G-PANE",
    "a scanner pane that binds a symbol, or a modal or page",
    r"\bbinds? (?:a |the |its )?(?:`?symbol`?|`?interval_code`?|interval)\b"
    r"|\b(?:a |the )?(?:modal|page route|dialog)\b"
    r"|\b(?:follows?|tracks?|mirrors?|takes?) (?:\w+ ){0,3}?(?:symbol|sync group|interval)\w*\b",
    unless=r"neither|never|not a",
    heads=("2.1 Placement", "2.2 Anatomy"),
)


def g_cadence(t: Texts) -> list[Finding]:
    """BQ-10: one scan per cadence while visible, never overlapping; a hidden pane polls
    nothing."""
    return require(
        "G-CADENCE",
        "7.1 Cadence",
        (
            "while the pane and the document are visible, never overlapping",
            "a hidden pane polls nothing",
        ),
    )(t)


g_cadence_words = lexicon(
    "G-CADENCE",
    "a poll faster than the cadence, or one while hidden",
    r"\b(?:every|each) (?:second|tick|frame)\b|\bper (?:second|tick)\b|\bcontinuous\w*\b"
    r"|\bin real time\b|\b(?:background|inactive|unfocused) (?:tab|window)s?\b"
    r"|\bkeeps? (?:on )?(?:scanning|polling|refreshing)\b"
    r"|\b(?:polls?|scans?) (?:\w+ ){0,2}?while (?:hidden|in the background)\b",
    heads=("7.1 Cadence", "7.2 Age", "15.2 Performance"),
)


NOSUB = (
    "the panel subscribes to no ws topic for its rows: every live value, the sparkline included,"
    " comes from the scan response"
)
DATA_NOTES = (
    "2.3 Data",
    "7.1 Cadence",
    "7.2 Age",
    "7.3 The stale scan",
    "7.4 Stale inputs",
    "8.3 The sparkline",
    "15.2 Performance",
)


def g_nosub(t: Texts) -> list[Finding]:
    """BQ-10: the no-subscription rule written in §15.2, and no `subscribe` in the panel's data
    notes."""
    sec = spec_sec(t, "15.2 Performance")
    if NOSUB not in norm_text(section(t.spec, "15.2 Performance")):
        return [F("G-NOSUB", "§15.2 lacks the ruled no-subscription sentence", "spec", sec)]
    return []


g_nosub_words = lexicon(
    "G-NOSUB",
    "a WS subscription in the panel's data notes",
    r"\bsubscrib\w*\b(?! to no\b)|\blistens? (?:to|on)\b|\bstream(?:s|ed|ing)? (?:its |the )?"
    r"(?:rows|values|tickers?)\b|\b(?:ticker|ws|scan) (?:topic|feed|stream)s? "
    r"(?:feeds?|drives?|updates?|carr(?:y|ies)|delivers?|sends?)\b|\bpushe[sd]\b"
    r"|\b(?:over|via|through|from|on) (?:the |a )?(?:\w+ )?(?:ws|websockets?|sockets?)\b"
    r"|\bwebsockets?\b(?! banner)",
    heads=DATA_NOTES,
)


def g_server(t: Texts) -> list[Finding]:
    """T Tech, R-1: the scan is server-side; written in §1.4 and §15.2."""
    bad: list[Finding] = []
    for head in ("1.4 Rules", "15.2 Performance"):
        if norm_text("never evaluates criteria client-side across the universe") not in norm_text(
            section(t.spec, head)
        ).replace("a criterion", "criteria"):
            msg = f"§{head.split(' ')[0]} lacks the rule"
            bad.append(F("G-SERVER", msg, "spec", spec_sec(t, head)))
    return bad


g_server_words = lexicon(
    "G-SERVER",
    "client-side evaluation",
    r"\bclient.side\b|\b(?:filters?|evaluates?|scans?|ranks?|matches?) (?:\S+ ){0,3}?"
    r"(?:in the browser|locally|on the client)\b"
    r"|\bre.?appl\w* (?:the |its |each )?(?:criteria|criterion|filters?)\b"
    r"|\b(?:criteria|criterion|filters?) (?:\w+ ){0,3}?(?:itself|themselves|in the (?:web )?app)\b"
    r"|\b(?:web )?app (?:\w+ ){0,2}?(?:evaluates|filters|matches|re.?checks)\b",
    unless=r"sort those|column sort|header",
)


def g_stale(t: Texts) -> list[Finding]:
    """BQ-10, AC4: the whole set stale after T2; Inputs stale; one polite announcement on entry
    and exit through the app's region; no row authoritative."""
    bad = require(
        "G-STALE",
        "7.3 The stale scan",
        (
            "puts d04's `stale` on the whole result set",
            "one polite announcement is made on entry and one on exit, through the app's region",
        ),
    )(t)
    bad += require(
        "G-STALE",
        "7.4 Stale inputs",
        (
            'the label "inputs stale"',
            "no row reads as authoritative while it shows",
            "the label is cmp-239's chip at the head of that note, panel level, never a row's",
            "d08-c19",
        ),
    )(t)
    return bad


g_stale_words = lexicon(
    "G-STALE",
    "an assertive or repeated stale announcement, a new state or an authoritative stale scan",
    r"\bassertive\w*\b|\brole=.?alert\b|\bannounc\w* (?:on )?(?:every|each)\b"
    r"|\bnew (?:data.confidence )?state\b|\b(?:authoritative|trusted|a clean result)\b"
    r"|\b(?:reliable|dependable|trustworthy|accurate|definitive|safe to (?:trade|act))\b"
    r"|\burgent\b|\binterrupt\w*|\baria.live=.?assertive",
    heads=("7.1 Cadence", "7.2 Age", "7.3 The stale scan", "7.4 Stale inputs", "7.5 Pause"),
)


def g_pause(t: Texts) -> list[Finding]:
    """BQ-10, `05`:207: the pause control; nothing animates."""
    return require(
        "G-PAUSE",
        "7.5 Pause",
        ('a "pause updates" toggle', 'the footer says "paused"', "no row animation, no flash"),
    )(t)


g_pause_words = lexicon(
    "G-PAUSE",
    "a refresh that animates, flashes or pulses",
    r"\bpuls\w*|\bflash\w*|\bblink\w*|\bglow\w*|\bshimmer\w*|\bfade\w*|\btween\w*"
    r"|\banimat\w*|\bhighlight\w* (?:\w+ )?(?:briefly|on change|on refresh)\b",
    heads=("7.5 Pause",),  # the `##` section 7; G-SPARK owns the sparkline in §8
)


STATE_ROWS = (
    ("First load", "—"),
    ("No matches", "W-17"),
    ("Scan failed", "W-18"),
    ("Refresh failed", "W-19"),
)


def shingles(s: str) -> set[str]:
    w = re.findall(r"[a-z']+", s.lower().replace("’", "'"))
    return {" ".join(w[i : i + 3]) for i in range(len(w) - 2)}


def g_states(t: Texts) -> list[Finding]:
    """BQ-14, AC5: four states; no shared string; failed never reads "No …"; a 403 is the
    failed state."""
    sec = spec_sec(t, STATES_HEAD)
    rows = table_rows(section(t.spec, STATES_HEAD))
    got = tuple((r[0], r[3]) for r in rows if len(r) > 3)
    bad: list[Finding] = []
    if got != STATE_ROWS:
        bad.append(F("G-STATES", f"§9 rows read {got}", "spec", sec))
    d = deck(t.spec)
    dsec = deck_sec(t)
    ids = ("W-17", "W-18", "W-19")
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            sa, sb = w_segments(t.spec, a), w_segments(t.spec, b)
            if set(sa) & set(sb) or shingles(d.get(a, "")) & shingles(d.get(b, "")):
                bad.append(F("G-STATES", f"{a} and {b} share wording", "spec", dsec))
    for wid in ("W-18", "W-19"):
        if d.get(wid, "").lower().startswith("no "):
            bad.append(F("G-STATES", f"{wid} reads like no matches", "spec", dsec))
    body = norm_text(section(t.spec, STATES_HEAD))
    for n in (
        "states share no string",
        "and is drawn as the failed state",
        "polling retries at the cadence and retry polls at once",
        "static, never a countdown",
        "the grid's tab stop passes to the state's action",
    ):
        if norm_text(n) not in body:
            bad.append(F("G-STATES", f"§9 lacks {n!r}", "spec", sec))
    return bad


GRID_KEYS_OUT = ("`Alt+↑`", "`Alt+↓`", "`Del`")


g_states_words = lexicon(
    "G-STATES",
    "a state reusing another state's copy",
    r"\breus\w*\b|\b(?:same|shared?) (?:copy|wording|strings?|text|heading)\b",
    near=r"\bno.matches\b|\bempty\b|\bfailed\b|\brefresh\b|\bstates?\b",
    unless=r"share no|no shared",
    heads=(STATES_HEAD,),
)


def g_grid(t: Texts) -> list[Finding]:
    """BQ-16: a grid; D07 §6.2's keys minus reorder / remove / `Del`; a PROPOSED KM context; no
    single-letter key; `Ctrl+F` not taken."""
    head = "12.1 The grid"
    sec = spec_sec(t, head)
    raw = section(t.spec, head)
    body = norm_text(raw)
    bad: list[Finding] = []
    for n in (
        '`<table role="grid">`',
        "minus reorder, remove and `del`",
        "a proposed `scanner` context",
        "no single-letter key",
        "`ctrl+f` is not taken here",
        "**focus is never moved by a refresh**",
        "except from a focused row that leaves the set, where w-20 is announced first",
        "**filter bar keys:** `enter` on a chip opens its popover",
        "`esc` closes it without applying and returns focus to the chip",
        "`enter` or `space` on a chip's remove button removes the filter",
        "the notes are not focusable, except a derivation note's link",
    ):
        if norm_text(n) not in body:
            bad.append(F("G-GRID", f"§12.1 lacks {n!r}", "spec", sec))
    if re.search(r"`[A-Za-z]`", CODE.sub(lambda c: c[0] if len(c[0]) == 3 else " ", raw)):
        bad.append(F("G-GRID", "§12.1 binds a single-letter key", "spec", sec))
    keys = next((ln for ln in raw.split("\n") if ln.startswith("- **Keys:**")), "")
    listed = keys.split("minus reorder, remove and `Del`", 1)[-1]
    if any(k in listed for k in GRID_KEYS_OUT) or re.search(r"`[A-Za-z]`", listed):
        bad.append(
            F("G-GRID", "§12.1's key list holds a removed or single-letter key", "spec", sec)
        )
    return bad


def g_announce(t: Texts) -> list[Finding]:
    """BQ-17: one polite announcement per user change and per state-class change; drift, ages
    and re-ranks silent; the app's region."""
    return require(
        "G-ANNOUNCE",
        "12.2 The caption",
        (
            "**silent:** count drift between polls, ages and re-ranks",
            "the panel owns none",
            "speaks once on entry, each with its w-22 string",
            "stale and inputs stale speak once more on exit",
            "refresh failed speaks nothing",
            "the first result after the pane opens is the first state entry",
        ),
    )(t) + [
        F("G-ANNOUNCE", f"W-22 lacks {x!r}", "spec", deck_sec(t))
        for x in ANNOUNCED
        if not any(
            re.fullmatch(re.escape(x).replace(re.escape("200+"), r"\d+\+"), seg)
            for seg in w_segments(t.spec, "W-22")
        )
    ]


# one string per speaking state (matches, none, capped, live only, failed, stale, inputs stale)
ANNOUNCED = (
    "{38} matches.",
    "No matches.",
    "200+ matches; results capped.",
    "{143} matches, {38} live only.",
    "200+ matches, {38} live only; results capped.",
    "Couldn't run the scan.",
    "Results are stale.",
    "Results are current again.",
    "Computed from possibly stale inputs.",
    "Inputs are current again.",
)


g_focus_words = lexicon(
    "G-GRID",
    "a refresh that moves focus",
    r"\b(?:moves?|jumps?|resets?|returns?) (?:the )?focus\b",
    near=r"\b(?:refresh\w*|poll\w*|scans?|re.?rank\w*)\b",
    unless=r"leaves the set|at its index|never",
)


g_announce_words = lexicon(
    "G-ANNOUNCE",
    "an announcement per poll, refresh or count change",
    r"\b(?:announc|speak|voic|read)\w* (?:\w+ ){0,2}?(?:on |at |after )?(?:every|each|per) "
    r"(?:\S+ ){0,2}?(?:poll|refresh|scan|tick|count|re-?rank)\w*\b"
    r"|\b(?:voiced|spoken|announced):? count drift\b"
    r"|\b(?:every|each) (?:count change|refresh|poll) (?:is )?(?:announced|spoken)\b",
)


def t2_strings() -> list[str]:
    tpl = grab(r'"(Your role can\'t \{verb\}\.)"', base_line("E09-D09", 89), "E09-D09:89")
    save = grab(r'"(save workspaces)"', base_line("E09-D09", 114), "E09-D09:114")
    alert = grab(r'"(change alerts)"', base_line("E09-D09", 112), "E09-D09:112")
    view = grab(r'"(Read-only while viewing as \{user\}\.)"', base_line("E09-D09", 95), "95")
    return [tpl.replace("{verb}", save), tpl.replace("{verb}", alert), view]


def g_t2(t: Texts) -> list[Finding]:
    """BQ-19, S-10: T2 reasons only from E09-D09 §3; `rbac.view_as` first; no action hidden."""
    sec = spec_sec(t, "11. Result actions")
    bad: list[Finding] = []
    want = t2_strings()
    if w_segments(t.spec, "W-30") != want:
        bad.append(F("G-T2", "W-30 is not E09-D09's strings", "spec", sec))
    for r in table_rows(section(t.spec, "11. Result actions")):
        cell = r[3] if len(r) > 3 else ""
        for q in re.findall(r'T2 "([^"]+)"', cell):
            if q not in want:
                bad.append(F("G-T2", f"{r[0]}: T2 reason {q!r} is not merged", "spec", sec))
    body = norm_text(section(t.spec, "11. Result actions"))
    for n in ("`rbac.view_as` comes first", "no action is hidden"):
        if norm_text(n) not in body:
            bad.append(F("G-T2", f"§11 lacks {n!r}", "spec", sec))
    return bad


g_t2_words = lexicon(
    "G-T2",
    "an action hidden from a role",
    r"\b(?:hid(?:e|es|den|ing)|removed|omitted|not shown|absent|not (?:see|visible|offered)"
    r"|invisible)\b",
    near=r"\b(?:action|item|menu|viewer|role|control)s?\b",
    heads=("11. Result actions",),
)


def g_presets(t: Texts) -> list[Finding]:
    """BQ-18: the name bound; never auto-saved; a removed criterion never silently dropped;
    user-scoped; the helper line."""
    bad = require(
        "G-PRESETS",
        "10. Presets",
        (
            "characters, unique per user",
            "a preset is never auto-saved",
            "with cancel focused",
            "it is never silently dropped",
            "with no cross-user visibility",
            '"a preset saves your filters and ranking, not the results."',
        ),
    )(t)
    return bad


g_presets_shared = lexicon(  # anywhere in either doc, not only §10
    "G-PRESETS",
    "presets visible across users",
    r"\beach other'?s\b|\bone another'?s\b|\bteams? (?:\w+ ){0,3}?presets?\b"
    r"|\b(?:browse|see|view|open|share)s? (?:\w+ ){0,2}?(?:other users'?|others'|colleagues'?)"
    r" presets?\b",
)
g_presets_words = lexicon(
    "G-PRESETS",
    "auto-save, shared presets or stored results",
    r"\bauto.?sav\w*|\bshared? (?:with|across|between) (?:other )?users\b|\bresults? (?:are |is )?"
    r"(?:saved|stored|kept) (?:in|with|by) (?:the |a )?presets?\b|\bdropped silently\b"
    r"|\bpresets? (?:\w+ ){0,2}?(?:keep|store|save|hold)s? (?:\w+ ){0,2}?results\b"
    r"|\bvisible to (?:every|all|other) users?\b|\bevery user can see\b"
    r"|\b(?:saved|stored) automatically\b|\bautomatically (?:saved|stored)\b"
    r"|\beach other'?s\b|\bone another'?s\b|\bteams? (?:\w+ ){0,3}?presets?\b"
    r"|\bpresets? (?:\w+ ){0,3}?(?:other users|colleagues|the team)\b"
    r"|\bsaves? itself\b",
    heads=("10. Presets",),
)

ADVICE = re.compile(
    r"(?<![\w-])(?:buy|sell|long|short|enter|exit|opportunit\w*|signals?|setups?|top picks?"
    r"|best|top"
    r"|recommend\w*|should|bullish|bearish|winners?|losers?|hot)\b",
    re.IGNORECASE,
)


def g_advice(t: Texts) -> list[Finding]:
    """BQ-20, F21: no advice word in the copy deck, a preset's example name, a name quoted in §10
    (even a short "Top" one) or an empty state; "Rank by" and "matches", never "best" or "top"."""
    sec = spec_sec(t, "13. Copy deck")
    bad: list[Finding] = []
    for wid, s in deck(t.spec).items():
        if ADVICE.search(s):
            bad.append(F("G-ADVICE", f"{wid}: an advice word in {s[:40]!r}", "spec", sec))
    names = re.findall(r"`\{([A-Z][^}]*)\}` a preset's name", section(t.spec, "13. Copy deck"))
    for n in names:
        if ADVICE.search(n):
            bad.append(F("G-ADVICE", f"preset example {n!r}", "spec", sec))
    for r in table_rows(section(t.spec, STATES_HEAD)):
        if ADVICE.search(" ".join(r[2:3])):
            bad.append(F("G-ADVICE", f"§9 {r[0]}: an advice word", "spec", spec_sec(t, "9.")))
    for q in re.findall(r'"([^"\n]+)"', strip_comments(section(t.spec, "10. Presets"))):
        if ADVICE.search(q):
            bad.append(F("G-ADVICE", f"§10 quotes {q!r}", "spec", spec_sec(t, "10. Presets")))
    body = norm_text(section(t.spec, "13. Copy deck"))
    for n in ('"rank by" and "matches", never "best" or "top"', "never a direction arrow"):
        if norm_text(n) not in body:
            bad.append(F("G-ADVICE", f"§13 lacks {n!r}", "spec", sec))
    return bad


g_advice_words = lexicon(
    "G-ADVICE",
    "a recommendation or a regime direction in buy or sell colour",
    r"\brecommend\w*\b|\bsuggests? (?:a |the )?(?:trade|entry|position|buy|sell)\b"
    r"|\b(?:green|red|buy colou?r|sell colou?r)\b"
    r"|\bnudg\w*|\bsteer\w*|\bencourag\w*|\bprompts? (?:a |the )?(?:trade|entry)\b"
    r"|\btoward\w* (?:an? |the )?(?:entry|trade|position|buy|sell)\b",
    unless=r"never|not a recommendation|conditions, never",
    heads=("1.4 Rules", "3.3 Estimated", "8.1 Columns", "8.2 Number rule", "13. Copy deck"),
)


FORBIDDEN_COLS = re.compile(
    r"pnl|p&l|position|account|balance|equity|margin|order|leverage", re.IGNORECASE
)


def g_security(t: Texts) -> list[Finding]:
    """BQ-21: public market metadata only; filter text rendered as text; the caption from the
    parsed filter; presets user-scoped."""
    bad: list[Finding] = []
    sec = spec_sec(t, "8.1 Columns")
    for r in table_rows(section(t.spec, "8.1 Columns")):
        if FORBIDDEN_COLS.search(r[0] + " " + (r[1] if len(r) > 1 else "")):
            bad.append(F("G-SECURITY", f"an account-scoped column {r[0]!r}", "spec", sec))
    if norm_text(
        "**No account-scoped column, ever, without a separate RBAC review**"
    ) not in norm_text(section(t.spec, "8.1 Columns")):
        bad.append(F("G-SECURITY", "§8.1 lacks the RBAC-review rule", "spec", sec))
    bad += require(
        "G-SECURITY",
        "15.3 Security",
        (
            "public market metadata only",
            "render as text, never markup or a query",
            "built from the parsed filter, not the raw input",
            "presets are user-scoped, with no cross-user visibility",
        ),
    )(t)
    return bad


g_security_words = lexicon(
    "G-SECURITY",
    "markup, interpretation or account data on the panel",
    r"\b(?:render(?:s|ed)? as (?:html|markup)|innerhtml|interpret(?:s|ed)? (?:the )?filter"
    r"|(?:pnl|p&l|positions?|balances?|profit|loss|equity|margin|exposure) columns?)\b",
    unless=r"never|separate rbac review|needs a",
)
g_security_format = lexicon(  # a clause that also says "never markup" still may not allow these
    "G-SECURITY",
    "formatting in a filter value, preset name or caption",
    r"\b(?:inline |rich )?formatting\b|\brich text\b|\bmarkdown\b|\bstyled (?:names?|text)\b",
)

EVENT_PROPS = {"criteria", "action", "preset_count", "rank_position", "state", "live_only_count"}
EVENT_PROPS |= {"count", "overflow"}


def g_events(t: Texts) -> list[Finding]:
    """BQ-22: the four `14` names, the proposed two marked; ids and counts only."""
    head = "15.1 Analytics"
    sec = spec_sec(t, head)
    rows = table_rows(section(t.spec, head))
    names = re.findall(r"`(scanner\.[a-z_]+)`", base_line("14", 2278))
    bad: list[Finding] = []
    got = [re.sub(r"[`*]", "", r[0]).split(" ")[0] for r in rows]
    if got[:4] != names:
        bad.append(F("G-EVENTS", f"§15.1's first rows {got[:4]} are not `14`:2278's", "spec", sec))
    for r in rows:
        if r[0].split("`")[1] not in names and "(PROPOSED)" not in r[0]:
            bad.append(F("G-EVENTS", f"{r[0]}: an unmarked new event", "spec", sec))
        props = set(re.findall(r"([a-z_]+)(?=:|,|\})", r[1].replace(" ", ""))) - {
            "matches",
            "empty",
            "capped",
            "failed",
            "stale_inputs",
            "added",
            "changed",
            "removed",
        }
        if props - EVENT_PROPS:
            bad.append(
                F("G-EVENTS", f"{r[0]}: properties {sorted(props - EVENT_PROPS)}", "spec", sec)
            )
    raw = next((ln for ln in t.spec.split("\n") if ln.startswith("### 15.1")), "")
    if "ids and counts only, never a filter value or a preset name" not in raw:
        bad.append(F("G-EVENTS", "§15.1's heading lacks the rule", "spec", sec))
    if norm_text("scans write no audit record") not in norm_text(section(t.spec, "15.3 Security")):
        bad.append(F("G-EVENTS", "§15.3 lacks 'scans write no audit record'", "spec", sec))
    return bad


g_events_words = lexicon(
    "G-EVENTS",
    "a filter value or preset name in analytics, or a scan audited",
    r"\b(?:carr(?:y|ies)|sends?|includes?|logs?|records?) (?:\w+ ){0,3}?(?:the )?(?:filter "
    r"values?|preset names?|min|max|thresholds?)\b|\bscans? (?:are |is )?audited\b"
    r"|\bscans? (?:write|emit|create)s? (?:an? )?audit\b",
    unless=r"never",
)


def g_numbers(t: Texts) -> list[Finding]:
    """BQ-15: E08-D06 F1–F7 win over D07 D9; no float, `toFixed` or `price_scale`."""
    return require("G-NUMBERS", "8.2 Number rule", ("e08-d06 f1–f7 win over d07 d9",))(t)


g_numbers_words = lexicon(
    "G-NUMBERS",
    "a float, `Number`, `toFixed` or `price_scale` for a contract value",
    r"\btofixed\b|\bnumber\(|\bparsefloat\b|\bfloats?\b|\bfloat arithmetic\b|\bprice_scale\b",
    heads=tuple(
        h
        for h in (
            "1.4 Rules",
            "3.1 The criteria",
            "4.1 Anatomy",
            "8.1 Columns",
            "8.2 Number rule",
            "8.3 The sparkline",
        )
    ),
)


def g_spark(t: Texts) -> list[Finding]:
    """BQ-15: the sparkline's samples, static, never animated, `colorBySign` off, its neighbour."""
    return require(
        "G-SPARK",
        "8.3 The sparkline",
        (
            "hourly samples, static per refresh and never animated",
            "`colorbysign` off",
            "is its numeric neighbour",
            "display geometry only, never a value",
        ),
    )(t)


g_spark_words = lexicon(
    "G-SPARK",
    "an animated or sign-coloured sparkline",
    r"\banimat\w*|\bcolou?red by (?:its )?sign\b|\b`?colorbysign`? on\b|\btween\w*",
    heads=("8.3 The sparkline",),
)

g_spark_hand = lexicon(
    "G-SPARK",
    "an animated sparkline or popover in the hand-off",
    r"\banimat\w*|\bdraw.in\b|\btween\w*|\bfade\w*|\btransition\w*|\bgrows? in\b",
    doc="hand",
)

TOKEN_NAME = re.compile(
    r"`((?:color|space|radius|opacity|elevation|size|type|border|motion|pattern)\.[a-z0-9.*-]+)`"
)


def g_tokens(t: Texts) -> list[Finding]:
    """BQ-23: every token resolves, or is a routed name standing beside "not shipped" or
    "PROPOSED"; `space.filterbar.*` goes to `space.inset.*` with a DS row."""
    names = all_token_names()
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        skip = {
            ln
            for head in ("Table A", "17.1 Contradictions", MUTATION_HEAD)
            for ln in section(text, head).split("\n")
            if ln.startswith("|")
        }
        for i, line in enumerate(text.split("\n"), 1):
            if line in skip:
                continue
            for name in TOKEN_NAME.findall(line):
                star = name.endswith(".*") and any(n.startswith(name[:-1]) for n in names)
                if name in names or (star and name not in NOT_SHIPPED):
                    continue
                if name in NOT_SHIPPED and re.search(r"not shipped|unshipped|PROPOSED", line):
                    continue
                bad.append(F("G-TOKENS", f"{doc}:{i} {name} is unbound", doc, h2_at(text, i)))
    body = norm_text(section(t.spec, "14. Tokens"))
    if norm_text("the filter bar binds `space.inset.*`, with DS row A-9") not in body:
        bad.append(F("G-TOKENS", "§14 lacks the filter-bar binding", "spec", spec_sec(t, "14.")))
    return bad


def g_contrast(t: Texts) -> list[Finding]:
    """BQ-23: §14 lists every pair once with its bar; each clears it in all three themes."""
    sec = spec_sec(t, "14. Tokens")
    rows = pair_rows(t.spec)
    got: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        m = re.fullmatch(r"`([a-z.-]+)` on `([a-z.-]+)`", r[0])
        if m:
            got[(m[1], m[2])] = r
    bad: list[Finding] = []
    grid = contrast_grid()
    for key, (fg, bg, kind) in PAIRS.items():
        row = got.get((fg, bg))
        if row is None or len(row) < 5 or row[4] != kind:
            bad.append(F("G-CONTRAST", f"{key}: missing or wrong bar", "spec", sec))
            continue
        bar = text_min() if kind == "text" else mark_min()
        for th in THEMES:
            if Decimal(str(math.floor(grid[th][key] * 100) / 100)) < bar:
                bad.append(F("G-CONTRAST", f"{key} {th} under {bar}:1", "spec", sec))
    if len(rows) != len(PAIRS):
        bad.append(F("G-CONTRAST", f"{len(rows)} pair rows != {len(PAIRS)}", "spec", sec))
    return bad


# each C-row the ruling names: id -> a fragment its Contradiction cell holds
C_ROWS = {
    "D08-C1": "the criteria lists",
    "D08-C2": 'T Context\'s "volume"',
    "D08-C3": "T AC2",
    "D08-C4": "D07 D9",
    "D08-C5": "`funding`",
    "D08-C6": "`tape_speed_zscore`",
    "D08-C7": "sortable table",
    "D08-C8": "CMP-055",
    "D08-C9": "US-MKT-005",
    "D08-C10": "T DoD",
    "D08-C11": "R9 Advice boundary",
    "D08-C12": "saved screens",
    "D08-C13": "`14`:2273 lists",
    "D08-C14": "account panes",
    "D08-C15": "(estimated) labelling",
    "D08-C16": "D07:345",
    "D08-C17": "E15-D07",
    "D08-C18": "send matches to watchlist",
    "D08-C19": "Inputs stale",
}


def g_crows(t: Texts) -> list[Finding]:
    """BQ-3 and the ruling's contradictions: each C-row present with its subject and an owner
    cell; `14`'s "min < max" against T09 is a G-row, never a C-row."""
    head = "17.1 Contradictions"
    sec = spec_sec(t, head)
    rows = {r[0]: r for r in table_rows(section(t.spec, head))}
    bad: list[Finding] = []
    if list(rows) != list(C_ROWS):
        bad.append(F("G-CROWS", f"C-rows read {list(rows)}", "spec", sec))
    for cid, frag in C_ROWS.items():
        r = rows.get(cid)
        if r is None or len(r) < 4 or frag.lower() not in strip_comments(r[1]).lower() or not r[3]:
            bad.append(F("G-CROWS", f"{cid}: subject or owner", "spec", sec))
        elif re.search(r"min\s*>=?\s*max|min > max", r[1]):
            bad.append(F("G-CROWS", f"{cid}: the min/max rule is a G-row", "spec", sec))
    return bad


SHAPE = re.compile(
    r"\badd(?:s|ing)? `|\bshould (?:carry|hold|add|return)\b|:\s*\{|\btype:|\bnew field\b"
    r"|\brename\w*\b|\bas `[a-z_]+: ",
    re.IGNORECASE,
)


def g_grows(t: Texts) -> list[Finding]:
    """BQ-4: G-1 ... G-10 to E08-T09 (#4708), one owner, contract first, no shape proposed; the
    routed rows carry an owner, a consumer and a due date."""
    head = "17.2 The G-ledger"
    sec = spec_sec(t, head)
    raw = section(t.spec, head)
    rows = table_rows(raw)
    bad: list[Finding] = []
    ids = [r[0] for r in rows]
    if ids != [f"D08-G{n}" for n in range(1, 11)]:
        bad.append(F("G-GROWS", f"the ledger reads {ids}", "spec", sec))
    for r in rows:
        if len(r) < 4 or r[3] != LEDGER_OWNER:
            bad.append(F("G-GROWS", f"{r[0]}: owner {r[3] if len(r) > 3 else ''!r}", "spec", sec))
        if any(SHAPE.search(c) for c in r[1:3]):
            bad.append(F("G-GROWS", f"{r[0]}: a shape is proposed", "spec", sec))
    head_line = next((ln for ln in raw.split("\n") if ln.startswith("### 17.2")), "")
    for n in ("contract first", "no shape is proposed"):
        if n not in head_line:
            bad.append(F("G-GROWS", f"the ledger heading lacks {n!r}", "spec", sec))
    for r in rows:
        if len(r) < 5 or r[4] != LEDGER_DUE:
            bad.append(F("G-GROWS", f"{r[0]}: consumer and due date", "spec", sec))
    if LEDGER_DUE_HEAD not in raw:
        bad.append(F("G-GROWS", "the ledger's due column cites no sprint start", "spec", sec))
    for r in rows:
        if r[0] in ("D08-G2", "D08-G3") and not ("raw trades/s" in r[1] and "`24`:1057" in r[1]):
            bad.append(
                F("G-GROWS", f"{r[0]}: `tape_speed` is not said to be raw trades/s", "spec", sec)
            )
    for gid in ("D08-G11", "D08-G12", "D08-G13"):
        m = re.search(rf"\*\*{gid}\*\*(.*?)(?=\*\*D08-G\d+\*\*|$)", raw, re.DOTALL)
        seg = m[1] if m else ""
        if not (re.search(r"→", seg) and re.search(r"due \d{4}-\d{2}-\d{2}", seg)):
            bad.append(F("G-GROWS", f"{gid}: owner lane or due date", "spec", sec))
        if gid != "D08-G12" and "consumer" not in seg:
            bad.append(F("G-GROWS", f"{gid}: no consumer", "spec", sec))
    return bad


def g_marked(t: Texts) -> list[Finding]:
    """BQ-1, S-9: every PROPOSED name stands beside "PROPOSED" (its line or its heading)."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        head = ""
        skip = {ln for ln in section(text, MUTATION_HEAD).split("\n") if ln.startswith("|")}
        for i, line in enumerate(text.split("\n"), 1):
            if HEADING.match(line):
                head = line
            if line in skip:
                continue
            for c in CODE.finditer(line):
                for name in PROPOSED_NAMES:
                    hit = re.search(rf"(?<![\w.]){re.escape(name)}(?![\w])", c[0])
                    if hit and "PROPOSED" not in line and "PROPOSED" not in head:
                        msg = f"{doc}:{i} `{name}` is not marked PROPOSED"
                        bad.append(F("G-MARKED", msg, doc, h2_at(text, i)))
    return bad


SESSION_CLAIM = (
    r"\b(?:session|walkthrough|meeting)s?\b(?:\s+\S+){0,2}?\s+(?:was |were |has been |is )?"
    r"(?:held|ran|recorded|conducted|completed|happened|took place)\b|\btook place\b"
    r"|\bparticipants?\b|\battendees?\b|\bwalked through\b"
)
g_session = lexicon("G-SESSION", "a session held", SESSION_CLAIM)

WALK_HEAD = "18. The story-role dry run"
WALKTHROUGH_HEAD = "§E Owner walkthrough"


def g_walk(t: Texts) -> list[Finding]:
    """The dry run: one row per consumer, then the QA row; needs = found + not found; one
    resolvable disposition per not-found; the DoD tick follows the record."""
    sec = spec_sec(t, WALK_HEAD)
    raw = section(t.spec, WALK_HEAD)
    rows = table_rows(raw)
    bad: list[Finding] = []
    roles = [r[1] for r in rows if len(r) > 1]
    if roles[:-1] != [f"story: {c}" for c in CONSUMERS] or not (
        roles and roles[-1].startswith("QA: ")
    ):
        bad.append(F("G-WALK", f"the rows read {roles[:2]}…, not every consumer + QA", "spec", sec))
    sections_ = set(re.findall(r"^#{2,3} (\d+(?:\.\d+)?)\.? ", t.spec, MULTI))
    grows = set(re.findall(r"\bD08-G\d+\b", section(t.spec, "17.2 The G-ledger")))
    for r in rows:
        if len(r) < 6 or r[0] != "2026-10-27" or not all(x.isdigit() for x in r[2:5]):
            bad.append(F("G-WALK", f"{r[1] if len(r) > 1 else r}: date or counts", "spec", sec))
            continue
        need, found, nf = (int(x) for x in r[2:5])
        if need != found + nf:
            bad.append(F("G-WALK", f"{r[1]}: {need} != {found} + {nf}", "spec", sec))
        disp = [d for d in r[5].split(" · ") if d.strip()] if nf else []
        if len(disp) != nf:
            bad.append(
                F("G-WALK", f"{r[1]}: {nf} not found, {len(disp)} dispositions", "spec", sec)
            )
        for d in disp:
            m = re.search(r"→ (?:§(\d+(?:\.\d+)?)|(D08-G\d+))", d)
            if not m or (m[1] and m[1] not in sections_) or (m[2] and m[2] not in grows):
                bad.append(F("G-WALK", f"{r[1]}: {d[:40]!r} does not resolve", "spec", sec))
    walk = [ln for ln in section(t.hand, WALKTHROUGH_HEAD).split("\n") if ln.startswith("- [")]
    if not 0 < len(walk) <= MAX_WALK:
        msg = f"the owner walkthrough has {len(walk)} items, not 1 to {MAX_WALK}"
        bad.append(F("G-WALK", msg, "hand", h2_of(t.hand, WALKTHROUGH_HEAD)))
    lists = {r[0]: r[1] for r in table_rows(section(t.hand, NEEDS_HEAD)) if len(r) > 1}
    for r in rows:
        if len(r) < 6 or not all(x.isdigit() for x in r[2:5]):
            continue
        need, nf = int(r[2]), int(r[4])
        if r[1].startswith("QA: "):
            states = len(table_rows(section(t.spec, STATES_HEAD))) + len(frames(t.spec))
            if need != states:
                bad.append(F("G-WALK", f"QA needs {need} != {states} state rows", "spec", sec))
            continue
        items = [x for x in lists.get(r[1], "").split(" · ") if x.strip()]
        gsec = h2_of(t.hand, NEEDS_HEAD)
        if len(items) != need or sum("(not found)" in x for x in items) != nf:
            msg = f"{r[1]}: hand-off §G lists {len(items)} needs, the row {need} / {nf}"
            bad.append(F("G-WALK", msg, "hand", gsec))
        for x in items:
            m = re.search(r"→ (?:§(\d+(?:\.\d+)?)|(D08-G\d+))$", x)
            if not m or (m[1] and m[1] not in sections_) or (m[2] and m[2] not in grows):
                bad.append(
                    F("G-WALK", f"{r[1]}: §G item {x[:40]!r} does not resolve", "hand", gsec)
                )
    body = norm_text(raw)
    if norm_text("**No session took place and none is claimed.**") not in body:
        bad.append(F("G-WALK", "§18 lacks the no-session sentence", "spec", sec))
    if 'before any "not found" was recorded, the merged sources were searched' not in body:
        bad.append(F("G-WALK", "§18 lacks the search-first sentence", "spec", sec))
    dod = section(t.spec, "19.1 DoD")
    tick = re.search(r"^- \[(.)\] The dry run is the written confirmation", dod, MULTI)
    ok = not [f for f in bad if f[0] == "G-WALK"]
    if not tick or (tick[1] == "x") != ok:
        msg = "the DoD dry-run tick does not follow the record"
        bad.append(F("G-WALK", msg, "spec", spec_sec(t, "19.1 DoD")))
    return bad


@functools.lru_cache(maxsize=1)
def merge_base_sha() -> str:
    return git_out("merge-base", "HEAD", HEAD).strip()


def merge_base() -> str:
    """`git merge-base HEAD origin/main` (empty under the self-test's BROKEN lever)."""
    return "" if "merge-base" in BROKEN else merge_base_sha()


def stray_paths() -> tuple[str, ...]:
    return stray_paths_at(merge_base())


@functools.lru_cache(maxsize=2)
def stray_paths_at(ref: str) -> tuple[str, ...]:
    """Paths changed against the merge-base (committed, staged, working tree or untracked) that
    are not this PR's own."""
    if not ref:
        return ()
    names = git_out("diff", "--name-only", ref).split("\n")
    names += git_out("ls-files", "--others", "--exclude-standard").split("\n")
    return tuple(sorted({n for n in names if n and n not in OWN_PATHS}))


@functools.cache
def under_base(sha: str) -> bool:
    """`sha` names a commit that is the base or one of its ancestors."""
    full = git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").strip()
    return bool(full) and git_out("merge-base", full, BASE).strip() == full


def g_version(t: Texts) -> list[Finding]:
    """G-VERSION's shape (lens 1 carry): the version line (**Start.**) carries every merged
    input's sha, in order, each under the base; the Inputs line names the base it was read at."""
    lines = t.spec.split("\n")
    bad: list[Finding] = []
    for lead, check in (("**Start.**", "shas"), ("**Inputs pinned.**", "base")):
        i = next((n for n, ln in enumerate(lines) if ln.startswith(lead)), None)
        if i is None:
            bad.append(F("G-VERSION", f"no {lead} line", "spec", "(top)"))
            continue
        sec, line = h2_at(t.spec, i + 1), lines[i]
        if check == "shas":
            got = tuple(re.findall(r"`([0-9a-f]{10})`", line))
            if got != VERSION_SHAS:
                msg = f"the version line carries {len(got)} shas, not the {len(VERSION_SHAS)}"
                bad.append(F("G-VERSION", msg, "spec", sec))
            bad += [
                F("G-VERSION", f"`{s}` is not a commit under the base", "spec", sec)
                for s in got
                if not under_base(s)
            ]
        elif line.count(BASE) < 2:
            bad.append(
                F("G-VERSION", f"the Inputs line does not name the base {BASE}", "spec", sec)
            )
    return bad


def g_untouched(t: Texts) -> list[Finding]:
    """BQ-3: the untouched files equal the merge-base; nothing but this PR's four files differs;
    an unresolvable merge-base FAILs."""
    ref = merge_base()
    if not ref:
        return [F("G-UNTOUCHED", f"no merge-base with {HEAD}: nothing compared", None, None)]
    bad: list[Finding] = []
    for nn, text in t.plans:
        rel = cite_path(nn)
        if rel is None or text != (git_show(ref, rel) or ""):
            bad.append(F("G-UNTOUCHED", f"`{nn}` differs from {ref[:10]}", None, None))
    bad += [F("G-UNTOUCHED", f"{p} is not this PR's path", None, None) for p in stray_paths()]
    return bad


def g_budget(t: Texts) -> list[Finding]:
    """BQ-1: the spec within its line budget, the hand-off within its own."""
    bad: list[Finding] = []
    for doc, text, cap in (("spec", t.spec, SPEC_LINE_BUDGET), ("hand", t.hand, HAND_LINE_BUDGET)):
        n = text.count("\n") + (0 if text.endswith("\n") else 1)
        if n > cap:
            last = h2_at(text, len(text.split("\n")))
            bad.append(F("G-BUDGET", f"the {doc} has {n} lines > {cap}", doc, last))
    return bad


# lexicon gates first, then the measured gates; the pins (G-RULED-PIN) run last, in `audit`
LEXICON_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_penpot,
    g_unbuilt,
    g_trace,
    g_ruled,
    g_close,
    g_charset,
    g_cells,
    g_quote,
    g_marked,
    g_session,
    g_volatility_words,
    g_nested,
    g_estimated_words,
    g_pane_words,
    g_cadence_words,
    g_states_words,
    g_range_words,
    g_rank_words,
    g_rank_universe,
    g_cap_words,
    g_liveonly_words,
    g_nosub_words,
    g_server_words,
    g_stale_words,
    g_focus_words,
    g_announce_words,
    g_t2_words,
    g_presets_words,
    g_advice_words,
    g_security_words,
    g_events_words,
    g_numbers_words,
    g_spark_words,
    g_filterbar_words,
    g_pause_words,
    g_spark_hand,
    g_handoff_words,
    g_security_format,
    g_presets_shared,
)
MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_boards,
    g_pane,
    g_cadence,
    g_frame,
    g_locked,
    g_arow,
    g_criteria,
    g_volatility,
    g_owner,
    g_estimated,
    g_filterbar,
    g_range,
    g_rank,
    g_hold,
    g_cap,
    g_liveonly,
    g_nosub,
    g_server,
    g_stale,
    g_pause,
    g_states,
    g_grid,
    g_announce,
    g_t2,
    g_presets,
    g_advice,
    g_security,
    g_events,
    g_numbers,
    g_spark,
    g_tokens,
    g_contrast,
    g_crows,
    g_grows,
    g_handoff,
    g_walk,
    g_untouched,
    g_version,
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
    """Every unit of the doc: per region (heading path `a › b`, `#n` its occurrence), the heading,
    the line shape (one line-form tag per line), each rule line (`rule <k>`), each table row by its
    lead cell (`row <id>`, `#n` on a repeat), each prose sentence (`s<k>`) and each fenced block
    (`fence <k>`, verbatim as JSON)."""
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


FULL_STOP = re.compile(r"(?<=[.!?])\s+")


def ruled_units(spec: str, hand: str, values: Values) -> list[Unit]:
    docs = {"spec": spec, "hand": hand}
    return [u for d in PIN_DOCS for u in doc_units(d, docs[d], values)]


def write_pins(units: list[Unit]) -> str:
    head = (
        "# E08-D08 pins (every unit of both docs): doc, region (heading path #occurrence), "
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


PIN_TEXT_OVERRIDE: list[str] = []  # the self-test's lever (a damaged pins file)


def pin_file_text() -> str | None:
    if PIN_TEXT_OVERRIDE:
        return PIN_TEXT_OVERRIDE[-1]
    path = ROOT / RULED_PIN_TXT
    return path.read_text(encoding="utf-8") if path.exists() else None


def pin_file_problems() -> list[str]:
    """The header's unit count equals the parsed units; every pin line has its four fields."""
    text = pin_file_text()
    if text is None:
        return []
    m = re.search(r"; (\d+) units\.", text.split("\n", 1)[0])
    n = len(parse_pins(text))
    bad = [] if m and int(m[1]) == n else [f"the pins header names {m[1] if m else '?'}, {n} parse"]
    for i, ln in enumerate(text.split("\n"), 1):
        if ln and not ln.startswith("#") and len(ln.split("\t")) != 4:
            bad.append(f"pins line {i} is malformed")
    return bad


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
    damaged = (
        [F("G-RULED-PIN", m, None, None) for m in pin_file_problems()] if pinned is None else []
    )
    return damaged + [
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
        found += g_wordcount_doc(doc, text, t.values)
        found += g_marker_doc(doc, text, t.values)
        found += g_hex_doc(doc, text)
    for gate in LEXICON_GATES:
        found += gate(t)
    cf, n = cite_findings({"spec": t.spec, "hand": t.hand}, fetch)
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
    return fails, notes, [], n


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


def pushed[T](lst: list[T], item: T) -> Callable[[], Callable[[], None]]:
    """Push `item` onto a tool-state lever; the undo pops it."""

    def run() -> Callable[[], None]:
        lst.append(item)

        def undo() -> None:
            lst.pop()

        return undo

    return run


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str  # the gate tag that must trip ("" for a probe that must trip nothing)
    ruled: str  # the ruled sentence or the pin class it trips
    spec: Edit | None = None
    hand: Edit | None = None
    plan: tuple[str, Callable[[str], str]] | None = None  # edits an untouched working-tree file
    patch: Callable[[], Callable[[], None]] | None = None  # moves tool state; returns the undo


def drift(cid: str, n: int, text: str) -> Callable[[], Callable[[], None]]:
    """A cited line that moved at `origin/main` (G-VERSION's mutation)."""

    def run() -> Callable[[], None]:
        rel = cite_path(cid) or ""
        DRIFT.append((rel, n, text))

        def undo() -> None:
            DRIFT.pop()

        return undo

    return run


def add_board(text: str, _v: Values) -> str:
    rows = [ln for ln in section(text, "0. Status").split("\n") if ln.startswith("| 10 ")]
    if not rows:
        return text
    extra = "| 11  | `E08-D08 / 11 capped-light` | light twin of 04 | light | to draw (PR 2) |"
    return text.replace(rows[0], rows[0] + "\n" + extra, 1)


def overrun(text: str, _v: Values) -> str:
    n = text.count("\n")
    return text + "filler\n" * (SPEC_LINE_BUDGET - n + 5)


def appended_line(extra: str) -> Callable[[str], str]:
    return lambda x: x + extra


def qa_counts(need: str, found: str) -> Callable[[list[str]], list[str]]:
    """The QA row of the dry run with new Needs and Found cells (the sum still holds)."""

    def run(lines: list[str]) -> list[str]:
        out = []
        for ln in lines:
            if ln.startswith("|") and "QA: §9" in ln:
                ln = set_cell(set_cell(ln, 2, to(need)), 3, to(found))
            out.append(ln)
        return out

    return run


def damaged_pins() -> Callable[[], None]:
    """The pins file with its last unit cut and its header unchanged."""
    text = pin_file_text() or ""
    PIN_TEXT_OVERRIDE.append(text.rstrip("\n").rsplit("\n", 1)[0] + "\n")

    def undo() -> None:
        PIN_TEXT_OVERRIDE.pop()

    return undo


PNL_ROW = "| PnL | PnL | F6 | |"
T09_ROW = "| 2026-10-27 | story: E08-T09 (#4708) |"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1",
        "G-PENPOT",
        "BQ-1, S-3: the page by name and id only",
        spec=sub_in(
            "0. Status",
            "page `E08-D08 SCR-104 Scanner`",
            "page `E08-D08 SCR-104 Scanner` (https://penpot.example/view)",
        ),
    ),
    Mutation(
        "M-2",
        "G-UNBUILT",
        "BQ-1: the implementation contract",
        spec=sub_in("0. Status", "**this spec is the implementation contract**", "**this spec**"),
    ),
    Mutation(
        "M-3",
        "G-CITE",
        "BQ-1: every cite on a line at the base",
        spec=sub_in("1.3 Locked", "`23`:397", "`23`:99999"),
    ),
    Mutation(
        "M-4",
        "G-VERSION",
        "brief: a cited line that drifts at origin/main FAILs",
        patch=drift("14", 2276, "- **A11y:** moved"),
    ),
    Mutation(
        "M-5",
        "G-UNTOUCHED",
        "BQ-3: `15` untouched",
        plan=("15", appended_line("\nan edit\n")),
    ),
    Mutation(
        "M-6",
        "G-UNTOUCHED",
        "standing: D07 untouched",
        plan=("D07", appended_line("\nan edit\n")),
    ),
    Mutation("M-7", "G-BUDGET", "BQ-1: the line budgets", spec=overrun),
    Mutation("M-8", "G-BOARDS", "BQ-24: at most ten boards, twins a third", spec=add_board),
    Mutation(
        "M-9",
        "G-BOARDS",
        "BQ-24: each twin of a dark board",
        spec=row_edit("0. Status", "09", 2, to("light twin of 08")),
    ),
    Mutation(
        "M-10",
        "G-HEX",
        "BQ-23: every hex is the tool's",
        spec=say_in("14. Tokens", "The stale fill reads #000000 in dark."),
    ),
    Mutation(
        "M-11",
        "G-ANCHOR",
        "BQ-1: every number computed",
        spec=with_values(
            lambda v: sub_in(
                "5.1 Rank by", f"picks which {av(v, 'CITE:cap')}", "picks which 250<!--=CITE:cap-->"
            )
        ),
    ),
    Mutation(
        "M-12",
        "G-WORDCOUNT",
        "brief: counts written as figures",
        spec=say_in("1.1 What this spec", "It draws ten boards."),
    ),
    Mutation(
        "M-13",
        "G-LOCKED",
        "BQ-2: the locked inputs",
        spec=in_lines("1.3 Locked", drop_line("| E09-D09 ")),
    ),
    Mutation(
        "M-14",
        "G-AROW",
        "BQ-3: departures ship as A-rows",
        hand=drop_row("Table A", "A-3"),
    ),
    Mutation(
        "M-15",
        "G-AROW",
        "BQ-3: Old cells verbatim and whole",
        hand=row_edit("Table A", "A-1", 3, lambda c: c.split(". ", 1)[0] + "."),
    ),
    Mutation(
        "M-16",
        "G-CRITERIA",
        "BQ-6: the eight in that order",
        spec=in_lines(CRIT_HEAD, swap_rows("2", "3")),
    ),
    Mutation(
        "M-17",
        "G-CRITERIA",
        "BQ-6, BQ-13: OI Δ needs recorded history",
        spec=row_edit(CRIT_HEAD, "4", 4, to("live")),
    ),
    Mutation(
        "M-18",
        "G-VOLATILITY",
        "BQ-7: the ruled formula",
        spec=sub_in("3.2 24 h range", "÷ `low_24h` × 100", "÷ `high_24h` × 100"),
    ),
    Mutation(
        "M-19",
        "G-OWNER",
        "BQ-7: PROPOSED, owner approval pending",
        spec=line_edit("### 3.2 24 h range", OWNER_PENDING, "PROPOSED"),
    ),
    Mutation(
        "M-20",
        "G-OWNER",
        "BQ-13: PROPOSED, owner approval pending",
        spec=line_edit("- **D08-Q2**", OWNER_PENDING, "PROPOSED"),
    ),
    Mutation(
        "M-21",
        "G-ESTIMATED",
        "BQ-8: never a nested button",
        spec=sub_in("3.3 Estimated", ", never a nested button", ""),
    ),
    Mutation(
        "M-22",
        "G-ESTIMATED",
        "BQ-8: a badge button inside the option",
        spec=say_in("3.3 Estimated", "Each option holds a CMP-227 button inside the option."),
    ),
    Mutation(
        "M-23",
        "G-RANGE",
        "BQ-9: min == max refused",
        spec=sub_in("4.2 The rule", "; min == max is refused", ""),
    ),
    Mutation(
        "M-24",
        "G-RANGE",
        "BQ-9: the previous results stay",
        spec=say_in("4.2 The rule", "An invalid range clears the results."),
    ),
    Mutation(
        "M-25",
        "G-RANGE",
        "BQ-9: the `14` copy verbatim",
        spec=row_edit(
            "13. Copy deck", "W-7", 2, to("{Funding %}: Minimum must not exceed maximum.")
        ),
    ),
    Mutation(
        "M-26",
        "G-RANK",
        "BQ-12: headers sort the shown rows on the client",
        spec=say_in("5.1 Rank by", "A header click re-queries the server."),
    ),
    Mutation(
        "M-27",
        "G-HOLD",
        "BQ-12: D07 D5's hold",
        spec=sub_in("5.1 Rank by", ', with "paused" and "Re-sort" in the footer', ""),
    ),
    Mutation(
        "M-28",
        "G-CAP",
        "BQ-11: never a guessed total",
        spec=say_in("5.2 The cap", "Above the cap the count shows an estimated total."),
    ),
    Mutation(
        "M-29",
        "G-CAP",
        "BQ-11: the capped count is the cap",
        spec=row_edit(
            "13. Copy deck", "W-22", 2, lambda c: c.replace("200+ matches;", "300+ matches;")
        ),
    ),
    Mutation(
        "M-30",
        "G-LIVEONLY",
        "BQ-13: included and flagged",
        spec=say_in("6. Symbols we do not", "A live-only row is excluded from the matches."),
    ),
    Mutation(
        "M-31",
        "G-LIVEONLY",
        "BQ-13: the split count",
        spec=sub_in("6. Symbols we do not", ': "143 matches · 38 live only"', ""),
    ),
    Mutation(
        "M-32",
        "G-NOSUB",
        "BQ-10: no subscription in the data notes",
        spec=say_in("7.1 Cadence", "The panel subscribes to `ticker` for the rows in view."),
    ),
    Mutation(
        "M-33",
        "G-NOSUB",
        "BQ-10: the rule written in §15.2",
        spec=sub_in(
            "15.2 Performance",
            "the panel subscribes to no WS topic for its rows",
            "the panel reads the scan",
        ),
    ),
    Mutation(
        "M-34",
        "G-SERVER",
        "T Tech, R-1: never client-side",
        spec=say_in("4.1 Anatomy", "The panel filters the universe on the client."),
    ),
    Mutation(
        "M-35",
        "G-STALE",
        "BQ-10: polite, once on entry and exit",
        spec=say_in("7.3 The stale scan", "The stale scan is announced assertively."),
    ),
    Mutation(
        "M-36",
        "G-STALE",
        "BQ-10, AC4: never authoritative",
        spec=sub_in("7.4 Stale inputs", " No row reads as authoritative while it shows.", ""),
    ),
    Mutation(
        "M-37",
        "G-PAUSE",
        "BQ-10, `05`:207: the pause control",
        spec=sub_in(
            "7.5 Pause", 'A "Pause updates" toggle in the footer', "A toggle in the footer"
        ),
    ),
    Mutation(
        "M-38",
        "G-STATES",
        "BQ-14: no shared string",
        spec=row_edit(
            "13. Copy deck",
            "W-18",
            2,
            to("No instruments match these filters · The scanner didn't answer. · Retry"),
        ),
    ),
    Mutation(
        "M-39",
        "G-GRID",
        "BQ-16: D07's keys minus reorder, remove and `Del`",
        spec=sub_in(
            "12.1 The grid",
            "`Ctrl+C` copies the symbol.",
            "`Ctrl+C` copies the symbol, `Alt+↑` reorders.",
        ),
    ),
    Mutation(
        "M-40",
        "G-GRID",
        "BQ-16: `Ctrl+F` not taken",
        spec=sub_in(
            "12.1 The grid", " `Ctrl+F` is not taken here (SCR-053 binds it, `14`:1245).", ""
        ),
    ),
    Mutation(
        "M-41",
        "G-ANNOUNCE",
        "BQ-17: drift, ages and re-ranks silent",
        spec=say_in("12.2 The caption", "The count is announced on every refresh."),
    ),
    Mutation(
        "M-42",
        "G-T2",
        "BQ-19, S-10: merged reason keys only",
        spec=row_edit(
            "11. Result actions",
            "Create alert…",
            3,
            lambda c: c.replace("Your role can't change alerts.", "You can't create alerts."),
        ),
    ),
    Mutation(
        "M-43",
        "G-T2",
        "BQ-19: no action hidden",
        spec=say_in("11. Result actions", "A Viewer's watchlist items are hidden."),
    ),
    Mutation(
        "M-44",
        "G-PRESETS",
        "BQ-18: never auto-saved",
        spec=say_in("10.2 Default", "A modified preset is auto-saved."),
    ),
    Mutation(
        "M-45",
        "G-ADVICE",
        "BQ-20: conditions, never advice",
        spec=row_edit(
            "13. Copy deck", "W-17", 2, lambda c: c.replace("Clear filters", "Find the best setups")
        ),
    ),
    Mutation(
        "M-46",
        "G-SECURITY",
        "BQ-21: no account-scoped column",
        spec=add_row_after("8.1 Columns", "Status", PNL_ROW),
    ),
    Mutation(
        "M-47",
        "G-SECURITY",
        "BQ-21: the caption from the parsed filter",
        spec=sub_in(
            "15.3 Security", "; the caption is built from the parsed filter, not the raw input", ""
        ),
    ),
    Mutation(
        "M-48",
        "G-EVENTS",
        "BQ-22: ids and counts only",
        spec=row_edit(
            "15.1 Analytics",
            "`scanner.filter_changed`",
            1,
            lambda c: c.replace("{criteria:", "{filter_values, criteria:"),
        ),
    ),
    Mutation(
        "M-49",
        "G-NUMBERS",
        "BQ-15: no float for a contract value",
        spec=say_in("8.2 Number rule", "Values are formatted with `toFixed`."),
    ),
    Mutation(
        "M-50",
        "G-SPARK",
        "BQ-15: static, never animated",
        spec=say_in("8.3 The sparkline", "The sparkline animates between refreshes."),
    ),
    Mutation(
        "M-51",
        "G-TOKENS",
        "BQ-23: `space.filterbar.*` is not bound",
        spec=say_in("14. Tokens", "The chips sit `space.filterbar.md` apart."),
    ),
    Mutation(
        "M-52",
        "G-CONTRAST",
        "BQ-23: every pair measured",
        spec=in_lines("14. Tokens", drop_line("| `focus.ring` on `data-confidence.stale.surface`")),
    ),
    Mutation(
        "M-53",
        "G-FRAME",
        "BQ-24: the frame register column by column",
        spec=reg("filter/invalid-range · dark", "Copy", to("W-7, W-99")),
    ),
    Mutation(
        "M-54",
        "G-CROWS",
        "the ruling's contradictions as C-rows",
        spec=drop_row("17.1 Contradictions", "D08-C9"),
    ),
    Mutation(
        "M-55",
        "G-GROWS",
        "BQ-4: one owner",
        spec=row_edit("17.2 The G-ledger", "D08-G8", 3, to("E15 (pane kinds)")),
    ),
    Mutation(
        "M-56",
        "G-GROWS",
        "BQ-4: no shape proposed",
        spec=row_edit(
            "17.2 The G-ledger", "D08-G5", 1, appended(": add `generated_at` to `ScannerRow`")
        ),
    ),
    Mutation(
        "M-57",
        "G-WALK",
        "brief: needs = found + not found",
        spec=row_edit(WALK_HEAD, "2026-10-27", 3, to("18")),
    ),
    Mutation(
        "M-58",
        "G-CLOSE",
        "BQ-1: PR 1 is Refs #176",
        spec=say_in("19.3 Deviations", "PR 1 closes #176."),
    ),
    # X-n: the tool's own mutations, one per remaining ruled sentence or paraphrase class
    Mutation(
        "X-1",
        "G-MARKER",
        "a hidden note",
        spec=say_in("1.2 Method", "<!-- a note -->"),
    ),
    Mutation(
        "X-2",
        "G-ANCHOR",
        "a figure typed by hand",
        spec=with_values(
            lambda v: sub_in("7.3 The stale scan", f"{av(v, 'CITE:t2')} s (D07", "15 s (D07")
        ),
    ),
    Mutation(
        "X-3",
        "G-QUOTE",
        "a quote that is neither cited nor W-n",
        spec=say_in("2.1 Placement", 'The pane is "always the quickest view".'),
    ),
    Mutation(
        "X-4",
        "G-QUOTE",
        "a field name in no cited text",
        spec=say_in("15.3 Security", "No `scanner.filter_value` leaves the client."),
    ),
    Mutation(
        "X-5",
        "G-MARKED",
        "PROPOSED names marked",
        spec=line_edit("### 15.1 Analytics", "; properties PROPOSED", ""),
    ),
    Mutation(
        "X-6",
        "G-SESSION",
        "no session claimed",
        spec=say_in(WALK_HEAD, "A walkthrough session was held with the builders."),
    ),
    Mutation(
        "X-7",
        "G-CHARSET",
        "a no-break space",
        spec=sub_in(
            "1.1 What this spec", "SCR-104 as a workspace pane", "SCR-104 as a workspace pane"
        ),
    ),
    Mutation(
        "X-8",
        "G-CELLS",
        "a row with an extra cell",
        spec=row_edit("8.1 Columns", "Last", 3, to("tick | extra")),
    ),
    Mutation(
        "X-9",
        "G-TRACE",
        "every AC traced",
        spec=in_lines("Acceptance-criteria trace", drop_line("| AC4 ")),
    ),
    Mutation(
        "X-10",
        "G-RULED",
        "the ruling cited",
        spec=line_edit("## The questions", RULING_ID, "6453599088"),
    ),
    Mutation(
        "X-11",
        "G-VOLATILITY",
        "the bare word as a column",
        spec=say_in("8.1 Columns", "The volatility column sorts by range."),
    ),
    Mutation(
        "X-12",
        "G-ESTIMATED",
        "funding not badged until C7",
        spec=say_in("3.3 Estimated", "Funding is badged as estimated."),
    ),
    Mutation(
        "X-13",
        "G-SECURITY",
        "text, never markup",
        spec=say_in("15.3 Security", "Filter values render as HTML in the caption."),
    ),
    Mutation(
        "X-14",
        "G-EVENTS",
        "a new event marked PROPOSED",
        spec=row_edit(
            "15.1 Analytics", "`scanner.result_state` (PROPOSED)", 0, to("`scanner.result_state`")
        ),
    ),
    Mutation(
        "X-15",
        "G-EVENTS",
        "scans write no audit record",
        spec=say_in("15.3 Security", "Scans are audited as reads."),
    ),
    Mutation(
        "X-16",
        "G-PRESETS",
        "no cross-user visibility",
        spec=say_in("10.4 Permission", "Presets are shared with other users on request."),
    ),
    Mutation(
        "X-17",
        "G-CRITERIA",
        "the units",
        spec=row_edit(CRIT_HEAD, "5", 3, to("%")),
    ),
    Mutation(
        "X-18",
        "G-LIVEONLY",
        "the Live only chip",
        spec=sub_in("6. Symbols we do not", 'the "Live only" chip', 'the "Unrecorded" chip'),
    ),
    Mutation(
        "X-19",
        "G-WALK",
        "a disposition that resolves",
        spec=row_edit(
            WALK_HEAD,
            "2026-10-27",
            5,
            lambda c: c.replace("→ §11 (S11 Scope)", "→ §99 (S11 Scope)"),
        ),
    ),
    Mutation(
        "X-20",
        "G-WALK",
        "a row per consumer",
        spec=in_lines(WALK_HEAD, drop_line("| 2026-10-27 | story: E08-D14")),
    ),
    Mutation(
        "X-21",
        "G-WALK",
        "the DoD tick follows the record",
        spec=line_edit("- [x] The dry run is the written", "- [x]", "- [ ]"),
    ),
    Mutation(
        "X-22",
        "G-STALE",
        "the whole set stale after T2",
        spec=sub_in("7.3 The stale scan", " on the whole result set", ""),
    ),
    Mutation(
        "X-23",
        "G-RANK",
        "the default Rank by",
        spec=sub_in("5.1 Rank by", ", default Turnover 24 h (D08-G3)", " (D08-G3)"),
    ),
    Mutation(
        "X-24",
        "G-NOSUB",
        "a streamed row in the data notes",
        spec=say_in("8.3 The sparkline", "The panel streams its rows between scans."),
    ),
    Mutation(
        "X-25",
        "G-ANNOUNCE",
        "the app's region, never the panel's",
        spec=sub_in("12.2 The caption", "; the panel owns none", ""),
    ),
    Mutation(
        "X-26",
        "G-GROWS",
        "a routed row's due date",
        spec=sub_in(
            "17.2 The G-ledger",
            "agreed with QA; consumer E08-S11 (#4705), due 2026-11-06",
            "agreed with QA; consumer E08-S11 (#4705)",
        ),
    ),
    Mutation(
        "X-27",
        "G-CROWS",
        "each C-row's owner",
        spec=row_edit("17.1 Contradictions", "D08-C5", 3, to("")),
    ),
    Mutation(
        "X-28",
        "G-UNBUILT",
        "the scanner UI is unbuilt",
        spec=sub_in("0. Status", "**The scanner UI is unbuilt.** ", ""),
    ),
    Mutation(
        "X-29",
        "G-AROW",
        "a New cap is the cap",
        hand=row_edit("Table A", "A-3", 4, lambda c: c.replace("capped at 200", "capped at 250")),
    ),
    Mutation(
        "X-30",
        "G-STATES",
        "each state its own copy",
        spec=row_edit(STATES_HEAD, "Scan failed", 3, to("W-17")),
    ),
    Mutation(
        "X-31",
        "G-ADVICE",
        "no direction arrow in buy or sell colour",
        spec=sub_in("13. Copy deck", ", never a direction arrow in buy or sell colour", ""),
    ),
    Mutation(
        "X-32",
        "G-T2",
        "no action hidden",
        spec=sub_in("11. Result actions", " No action is hidden (`14`:85).", ""),
    ),
    Mutation(
        "X-33",
        "G-VERSION",
        "origin/main must resolve",
        patch=pushed(BROKEN, "head"),
    ),
    Mutation(
        "X-34",
        "G-UNTOUCHED",
        "the merge-base must resolve",
        patch=pushed(BROKEN, "merge-base"),
    ),
    Mutation(
        "X-35",
        "G-QUOTE",
        "a schema name `22` lacks",
        spec=sub_in("2.3 Data", "Each row is a `ScannerRow`", "Each row is a `ScannerRows`"),
    ),
    Mutation(
        "X-36",
        "G-QUOTE",
        "a permission the seed lacks",
        spec=say_in("10.4 Permission", "No `marketdata:write` is needed."),
    ),
    Mutation(
        "X-37",
        "G-SERVER",
        "the rule written in §1.4",
        spec=sub_in(
            "1.4 Rules", "never evaluates a criterion client-side", "never evaluates a criterion"
        ),
    ),
    Mutation(
        "X-38",
        "G-HOLD",
        "the hold while focus is in the grid",
        spec=sub_in("5.1 Rank by", ", held while the pointer or focus is in the grid", ""),
    ),
    Mutation(
        "X-39",
        "G-BOARDS",
        "each board marks a column that waits on its field",
        spec=sub_in(
            "0. Status",
            " Every board marks each column that waits on its field with the G-row it waits on"
            " (D08-G2), and draws it against `runScanner` as it stands plus that row (RULED BQ-4).",
            "",
        ),
    ),
    Mutation(
        "X-40",
        "G-AROW",
        "A-5 keeps `**Interactions:**`",
        hand=row_edit(
            "Table A",
            "A-5",
            4,
            lambda c: c.replace("- **Interactions:**", "- **Interactions/hotkeys:**"),
        ),
    ),
    Mutation(
        "X-41",
        "G-PANE",
        "BQ-5: the pane binds no symbol",
        spec=say_in("2.1 Placement", "The pane binds a `symbol`."),
    ),
    Mutation(
        "X-42",
        "G-CADENCE",
        "BQ-10: one scan per cadence",
        spec=say_in("7.1 Cadence", "The panel polls every second."),
    ),
    Mutation(
        "X-43",
        "G-STATES",
        "BQ-14: no state reuses another's copy",
        spec=say_in(STATES_HEAD, "The failed state reuses the no-matches copy."),
    ),
    Mutation(
        "X-44",
        "G-STALE",
        "AC4: a stale scan is never authoritative",
        spec=say_in("7.4 Stale inputs", "Stale inputs are presented as authoritative."),
    ),
    Mutation(
        "X-45",
        "G-RANGE",
        "AC3: the previous results stay",
        spec=say_in("4.2 The rule", "The previous results are discarded."),
    ),
    Mutation(
        "X-46",
        "G-GRID",
        "BQ-16: no single-letter key",
        spec=say_in("12.1 The grid", "`R` re-sorts the grid."),
    ),
    Mutation(
        "X-47",
        "G-PRESETS",
        "BQ-18: never auto-saved",
        spec=say_in("10.2 Default", "Changes are saved automatically."),
    ),
    Mutation(
        "X-48",
        "G-EVENTS",
        "BQ-21: scans write no audit record",
        spec=say_in("15.3 Security", "Scans write an audit record."),
    ),
    Mutation(
        "X-49",
        "G-ADVICE",
        "BQ-20: no direction in buy or sell colour",
        spec=say_in("8.1 Columns", "Regime arrows are green for up."),
    ),
    Mutation(
        "X-50",
        "G-RANK",
        "BQ-12: headers sort the shown rows only",
        spec=say_in("5.1 Rank by", "Header sort reorders the universe."),
    ),
    Mutation(
        "X-51",
        "G-GRID",
        "BQ-16: focus never moved by a refresh",
        spec=say_in("12.1 The grid", "A refresh moves focus to the first row."),
    ),
    Mutation(
        "X-52",
        "G-ESTIMATED",
        "BQ-8: the estimated set badged",
        spec=say_in("3.3 Estimated", "The z-score is exact, so it carries no badge."),
    ),
    Mutation(
        "X-53",
        "G-CAP",
        "BQ-11: the cap is the computed one",
        spec=say_in("5.2 The cap", "Results are capped at 500."),
    ),
    Mutation(
        "X-54",
        "G-NOSUB",
        "BQ-10: no WS path for rows",
        spec=say_in("7.1 Cadence", "Rows refresh over the WS gateway between scans."),
    ),
    Mutation(
        "X-55",
        "G-LIVEONLY",
        "BQ-13: live-only rows counted",
        spec=say_in("6. Symbols we do not", "Live-only rows are left out of the count."),
    ),
    Mutation(
        "X-56",
        "G-T2",
        "BQ-19: no action hidden",
        spec=say_in("11. Result actions", "Viewers do not see the watchlist actions."),
    ),
    Mutation(
        "X-57",
        "G-PANE",
        "BQ-5: one pane, one poll",
        spec=sub_in("2.1 Placement", "One pane is one filter set and one poll; ", ""),
    ),
    Mutation(
        "X-58",
        "G-CADENCE",
        "BQ-10: a hidden pane polls nothing",
        spec=sub_in("7.1 Cadence", " A hidden pane polls nothing.", ""),
    ),
    # X-59 ... : the folds of the three lens reports (2026-10-27), one per gateable rule
    Mutation(
        "X-59",
        "G-ESTIMATED",
        "lens 1 m2: the option host departs from `15`:2675",
        spec=sub_in("3.3 Estimated", " (a departure from `15`:2675 at the base: D08-C8, A-12)", ""),
    ),
    Mutation(
        "X-60",
        "G-ESTIMATED",
        "lens 3 M3: no button nested in a header",
        spec=say_in("3.3 Estimated", "The header holds a badge button."),
    ),
    Mutation(
        "X-61",
        "G-ESTIMATED",
        "lens 3 M3: the drawer from the note's link",
        spec=sub_in(
            "3.3 Estimated",
            "the drawer opens from the derivation note's link",
            "the drawer opens from the header",
        ),
    ),
    Mutation(
        "X-62",
        "G-FILTERBAR",
        "lens 3 M4: a chip is two sibling buttons",
        spec=sub_in("4.1 Anatomy", "A chip is two sibling buttons, never nested:", "A chip:"),
    ),
    Mutation(
        "X-63",
        "G-FILTERBAR",
        "lens 3 M4: the remove button is named",
        spec=row_edit(
            "13. Copy deck", "W-6", 2, lambda c: c.replace(" · Remove {Funding %} filter", "")
        ),
    ),
    Mutation(
        "X-64",
        "G-FILTERBAR",
        "lens 3 M5: an empty class set is never a filter",
        spec=sub_in(
            "4.1 Anatomy", "so an empty set is never a filter", "so an empty set is a filter"
        ),
    ),
    Mutation(
        "X-65",
        "G-FILTERBAR",
        "lens 3 m8: text parsed on commit, never as typed",
        spec=say_in("4.1 Anatomy", "Non-numeric text is refused at entry."),
    ),
    Mutation(
        "X-66",
        "G-FILTERBAR",
        "lens 1 m4: W-3 marked a placeholder",
        spec=sub_in(
            "4.1 Anatomy",
            ", a PROPOSED placeholder there that `DetectorMethodology.assumption` replaces,"
            " E25-D05:118",
            "",
        ),
    ),
    Mutation(
        "X-67",
        "G-RANGE",
        "lens 3 m1: the error's text token",
        spec=sub_in("4.2 The rule", "Its text is `color.text.primary`; ", ""),
    ),
    Mutation(
        "X-68",
        "G-RANK",
        "lens 3 M6: each option ranks highest first",
        spec=sub_in("5.1 Rank by", ", and each ranks highest first", ""),
    ),
    Mutation(
        "X-69",
        "G-RANK",
        "lens 3 M7: `aria-sort` on the sorted header only",
        spec=sub_in("5.1 Rank by", ", and only the sorted header carries `aria-sort`", ""),
    ),
    Mutation(
        "X-70",
        "G-RANK",
        "lens 2 A31: one default Rank by",
        spec=sub_in(
            "10.2 Default", "ranked by Turnover 24 h, capped", "ranked by Funding %, capped"
        ),
    ),
    Mutation(
        "X-71",
        "G-HOLD",
        "lens 3 m5: the hold covers order, not membership",
        spec=sub_in(
            "5.1 Rank by",
            " The hold covers order, not membership: a row that stops matching leaves at the next"
            " refresh.",
            "",
        ),
    ),
    Mutation(
        "X-72",
        "G-LIVEONLY",
        "lens 3 m2: both chips when both apply",
        spec=row_edit("8.1 Columns", "Status", 2, to('at most one chip: "Live only", "Stale 15s"')),
    ),
    Mutation(
        "X-73",
        "G-LIVEONLY",
        "lens 3 m3: the capped split count",
        spec=row_edit(
            "13. Copy deck", "W-11", 2, lambda c: c.replace("200+ matches · {38} live only · ", "")
        ),
    ),
    Mutation(
        "X-74",
        "G-LIVEONLY",
        "lens 2 A01: live-only rows never set aside",
        spec=say_in("6. Symbols we do not", "Such rows are then set aside from the count."),
    ),
    Mutation(
        "X-75",
        "G-STALE",
        "lens 3 M2: the inputs-stale chip is panel level (D08-C19)",
        spec=sub_in(
            "7.4 Stale inputs",
            " The label is CMP-239's chip at the head of that note, panel level, never a row's"
            " Status chip; it departs from D04's chip texts (D04:42, :76): D08-C19.",
            "",
        ),
    ),
    Mutation(
        "X-76",
        "G-STALE",
        "lens 2 A08: never presented as reliable",
        spec=say_in("7.4 Stale inputs", "The rows remain reliable while it shows."),
    ),
    Mutation(
        "X-77",
        "G-STATES",
        "lens 3 m9: the retry figure is static",
        spec=sub_in(
            "9. The result states", " W-19's figure is the cadence, static, never a countdown.", ""
        ),
    ),
    Mutation(
        "X-78",
        "G-STATES",
        "lens 3 m9: the tab stop passes to the state's action",
        spec=sub_in(
            "9. The result states",
            " The grid's tab stop passes to the state's action: Retry when the scan failed, Clear"
            " filters when nothing matches.",
            "",
        ),
    ),
    Mutation(
        "X-79",
        "G-GRID",
        "lens 3 M8: `Esc` returns focus to the chip",
        spec=sub_in("12.1 The grid", "returns focus to the chip,", "returns focus to the grid,"),
    ),
    Mutation(
        "X-80",
        "G-HANDOFF",
        "lens 3 M8: the hand-off's keyboard evidence is in spec §12.1",
        hand=row_edit(HANDA_HEAD, "Keyboard table", 1, appended("; `Alt+R` resets the filters")),
    ),
    Mutation(
        "X-81",
        "G-HANDOFF",
        "lens 2 A35: no §A cell left blank",
        hand=say_in(HANDA_HEAD, "A blank cell is acceptable."),
    ),
    Mutation(
        "X-82",
        "G-HANDOFF",
        "`16` §11.4: every §A cell ticked or unticked",
        hand=row_edit(HANDA_HEAD, "Live data", 2, to("none")),
    ),
    Mutation(
        "X-83",
        "G-HANDOFF",
        "lens 3 m11: §F points E08-T09 at the ledger",
        hand=row_edit(
            "§F Consumer", "E08-T09 (#4708)", 1, lambda c: c.replace(", §17.2 (the G-ledger)", "")
        ),
    ),
    Mutation(
        "X-84",
        "G-ANNOUNCE",
        "lens 3 M1: a string for each state's entry and exit",
        spec=row_edit(
            "13. Copy deck", "W-22", 2, lambda c: c.replace(" · Results are current again.", "")
        ),
    ),
    Mutation(
        "X-85",
        "G-ANNOUNCE",
        "lens 3 M1: refresh failed speaks nothing",
        spec=sub_in(
            "12.2 The caption",
            " Refresh failed speaks nothing: its footer line shows, and past T2 it is the stale"
            " scan (§7.3).",
            "",
        ),
    ),
    Mutation(
        "X-86",
        "G-ANNOUNCE",
        "lens 2 A15: never once per scan",
        spec=say_in("12.2 The caption", "The panel speaks on every scan."),
    ),
    Mutation(
        "X-87",
        "G-WALK",
        "lens 3 M9: the needs listed item by item",
        hand=row_edit(
            NEEDS_HEAD, "story: E08-S11 (#4705)", 1, lambda c: c.replace("pause → §7.5 · ", "")
        ),
    ),
    Mutation(
        "X-88",
        "G-WALK",
        "lens 3 M9: QA's needs are the state rows",
        spec=in_lines(WALK_HEAD, qa_counts("30", "27")),
    ),
    Mutation(
        "X-89",
        "G-WALK",
        "lens 3 M9: each listed need resolves",
        hand=row_edit(
            NEEDS_HEAD, "story: E08-D14 (#277)", 1, lambda c: c.replace("→ §8.4", "→ §8.9")
        ),
    ),
    Mutation(
        "X-90",
        "G-FRAME",
        "lens 3 m4: a twin draws every frame of its board",
        spec=reg("results/row-menu-viewer · light", "Frame", to("`results/row-menu · light`")),
    ),
    Mutation(
        "X-91",
        "G-CROWS",
        "lens 1 m1: the BQ-19 C-row",
        spec=drop_row("17.1 Contradictions", "D08-C18"),
    ),
    Mutation(
        "X-92",
        "G-CROWS",
        "lens 3 M2: the inputs-stale C-row",
        spec=drop_row("17.1 Contradictions", "D08-C19"),
    ),
    Mutation(
        "X-93",
        "G-AROW",
        "lens 1 m5: live only is no state in A-3",
        hand=row_edit(
            "Table A",
            "A-3",
            4,
            lambda c: c.replace("· stale inputs.", "· stale inputs · live-only rows."),
        ),
    ),
    Mutation(
        "X-94",
        "G-CHARSET",
        "lens 2 nit: an invisible character",
        spec=sub_in(
            "7.1 Cadence", "A hidden pane polls nothing.", "A hidden pane polls no\u200bthing."
        ),
    ),
    Mutation(
        "X-95",
        "G-RULED-PIN",
        "lens 2 nit: the pins header counts its units",
        patch=damaged_pins,
    ),
    Mutation(
        "X-96",
        "G-CONTRAST",
        "lens 3 n3: the unit is text",
        spec=row_edit("14. Tokens", "`text.tertiary` on `surface.app`", 4, to("mark")),
    ),
    Mutation(
        "X-97",
        "G-QUOTE",
        'a quote holding " to " is no W-5 range chip',
        spec=say_in(
            "2.1 Placement",
            'It is "the one pane a desk could ever really want to scan the market from".',
        ),
    ),
    Mutation(
        "X-98",
        "G-SECURITY",
        "lens 2 A21: no formatting in a name",
        spec=sub_in(
            "15.3 Security",
            "render as text, never markup or a query;",
            "render as text, never markup or a query, though a preset name may carry inline"
            " formatting;",
        ),
    ),
    Mutation(
        "X-99",
        "G-PRESETS",
        "lens 2 A22: no cross-user browsing",
        spec=say_in("15.3 Security", "A team can browse each other's presets."),
    ),
    Mutation(
        "X-100",
        "G-PRESETS",
        "lens 2 A34: Cancel focused in the delete confirm",
        spec=sub_in("10.1 The menu", "with Cancel focused", "with Delete focused"),
    ),
    Mutation(
        "X-101",
        "G-PAUSE",
        "lens 2 A25: no pulse on refresh",
        spec=say_in("7.5 Pause", "Changed cells pulse briefly."),
    ),
    Mutation(
        "X-102",
        "G-SPARK",
        "lens 2 A36: the hand-off never animates the sparkline",
        hand=say_in("§E Owner walkthrough", "The sparkline has a short draw-in."),
    ),
    Mutation(
        "X-103",
        "G-CADENCE",
        "lens 2 A03: no background polling",
        spec=say_in("7.1 Cadence", "A pane in a background tab keeps scanning."),
    ),
    Mutation(
        "X-104",
        "G-NOSUB",
        "lens 2 A05: no WebSocket path for rows",
        spec=say_in("7.1 Cadence", "Rows also update from the ticker WebSocket between scans."),
    ),
    Mutation(
        "X-105",
        "G-SERVER",
        "lens 2 A06: the app never re-applies the criteria",
        spec=say_in("4.1 Anatomy", "The web app re-applies the criteria itself."),
    ),
    Mutation(
        "X-106",
        "G-CAP",
        "lens 2 A07: no projected total",
        spec=say_in("5.2 The cap", "A projected total sits beside it."),
    ),
    Mutation(
        "X-107",
        "G-STALE",
        "lens 2 A09: never an urgent region",
        spec=say_in("7.3 The stale scan", "It speaks through an urgent live region."),
    ),
    Mutation(
        "X-108",
        "G-ADVICE",
        "lens 2 A27: never a nudge",
        spec=sub_in("1.4 Rules", "it never advises", "it may nudge toward an entry"),
    ),
    Mutation(
        "X-109",
        "G-PANE",
        "lens 2 A23: the pane follows no symbol",
        spec=say_in("2.1 Placement", "It follows the sync group's symbol like a chart."),
    ),
    Mutation(
        "X-110",
        "G-AROW",
        "lens 1 Major 2: A-12's Old is the whole host clause",
        hand=row_edit(
            "Table A", "A-12", 3, to("CMP-133 is the only host today (E25-D05 §3, §7.4).")
        ),
    ),
    Mutation(
        "X-111",
        "G-AROW",
        "lens 1 Major 2: A-12's New embeds the look with no nested button",
        hand=row_edit("Table A", "A-12", 4, lambda c: c.replace("no nested button and ", "")),
    ),
    Mutation(
        "X-112",
        "G-ADVICE",
        "lens 1 carry: a short advice name quoted in §10",
        spec=say_in("10.1 The menu", 'An example preset is "Top movers".'),
    ),
    Mutation(
        "X-113",
        "G-WALK",
        "lens 1 carry: the walkthrough has at most ten items",
        hand=in_lines(
            "§E Owner walkthrough",
            lambda ls: dup_line("- [ ] Board 01")(
                dup_line("- [ ] Board 01")(dup_line("- [ ] Board 01")(ls))
            ),
        ),
    ),
    Mutation(
        "X-114",
        "G-VERSION",
        "lens 1 carry: the version line carries its shas",
        spec=lambda text, _v: "\n".join(
            re.sub(r" \(`[0-9a-f]{10}`\)", "", ln) if ln.startswith("**Start.**") else ln
            for ln in text.split("\n")
        ),
    ),
    Mutation(
        "X-115",
        "G-GROWS",
        "lens 1 carry: G-1 ... G-10 name their consumer and due date",
        spec=row_edit("17.2 The G-ledger", "D08-G4", 4, to("E08-S11 (#4705)")),
    ),
    Mutation(
        "X-116",
        "G-GROWS",
        "lens 1 carry: `tape_speed` is raw trades/s",
        spec=row_edit(
            "17.2 The G-ledger",
            "D08-G3",
            1,
            lambda c: c.replace(" (its `tape_speed` ranks raw trades/s, `24`:1057)", ""),
        ),
    ),
    # one per pin class (G-RULED-PIN only)
    Mutation(
        "P-1",
        "G-RULED-PIN",
        "a frame row changed",
        spec=reg("stale/paused · dark", "State", to("Pause updates pressed (sic)")),
    ),
    Mutation(
        "P-2",
        "G-RULED-PIN",
        "a frame row moved",
        spec=in_lines(FRAME_HEAD, swap_rows("`presets/menu · dark`", "`presets/modified · dark`")),
    ),
    Mutation(
        "P-3", "G-RULED-PIN", "a sentence added to a paragraph", spec=say_in("1.2 Method", "Ok.")
    ),
    Mutation(
        "P-4",
        "G-RULED-PIN",
        "a bullet duplicated",
        spec=in_lines("1.4 Rules", dup_line("- **R-6")),
    ),
    Mutation(
        "P-5", "G-RULED-PIN", "a sentence deleted", spec=in_lines("1.4 Rules", drop_line("- **R-6"))
    ),
    Mutation(
        "P-6",
        "G-RULED-PIN",
        "a new heading",
        spec=squeezed(prose_at("7.5 Pause", "### 7.6 Notes\n\nSee §7.5."), 4),
    ),
    Mutation("P-7", "G-RULED-PIN", "blank lines squeezed", spec=squeezed(None, 3)),
    Mutation(
        "P-8",
        "G-RULED-PIN",
        "a hand-off row changed",
        hand=row_edit("§D Storybook", "CMP-024 Sparkline", 1, appended(" (cited)")),
    ),
    Mutation(
        "P-9",
        "G-RULED-PIN",
        "a bullet turned into prose",
        spec=line_edit("- **R-6", "- **R-6", "**R-6"),
    ),
    Mutation(
        "P-10", "G-RULED-PIN", "a line indented", spec=in_lines("1.4 Rules", indented("- **R-5", 2))
    ),
    Mutation("P-11", "G-RULED-PIN", "a duplicated section", spec=squeezed(shadow("7.5 Pause"), 4)),
    # probes that must trip nothing
    Mutation(
        "N-1",
        "",
        "Prettier re-pads a table row",
        spec=in_lines(
            FRAME_HEAD,
            lambda ls: [
                x.replace(" | ", "   |   ") if "`stale/paused · dark`" in x else x for x in ls
            ],
        ),
    ),
    Mutation(
        "N-2",
        "",
        "Prettier pads a table's cells",
        spec=in_lines(
            "8.1 Columns",
            lambda ls: [x.replace(" | ", "  |  ") if x.startswith("| Last ") else x for x in ls],
        ),
    ),
)


def ascii_line(s: str) -> str:
    """The self-test report is ASCII: anything else is escaped."""
    return s.encode("ascii", "backslashreplace").decode("ascii")


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
            raise SystemExit(f"FAIL parse: {nn} has no path")
        out.append((nn, ROOT / rel))
    return tuple(out)


def read_plans() -> tuple[tuple[str, str], ...]:
    return tuple((nn, p.read_bytes().decode("utf-8")) for nn, p in plan_paths())


def selftest(spec: str, hand: str, paths: tuple[Path, ...]) -> tuple[bool, list[str]]:
    on_disk = digest(paths)
    plans = read_plans()
    values = compute(spec, hand)[0]
    spec_f, _ = fill(spec, values)
    hand_f, _ = fill(hand, values)
    values = compute(spec_f, hand_f)[0]  # frozen at the filled baseline
    base_t = Texts(spec_f, hand_f, plans, values)
    base_fails, _notes, base_warns, _ = audit(base_t, git_fetch)
    lines = [f"baseline (filled in memory): {len(base_fails)} FAIL, {len(base_warns)} WARN"]
    lines += [f"  baseline FAIL {ascii_line(x[:160])}" for x in base_fails]
    ok = not base_fails
    probe = fence_pin_probe()
    lines.append(f"  fence probe: {'ok' if not probe else 'FAIL'}")
    lines += [f"    {x}" for x in probe]
    ok = ok and not probe
    listed = [
        (r[0], r[2].split(":")[0])
        for r in table_rows(section(spec_f, MUTATION_HEAD))
        if r[0].startswith("M-") and len(r) > 2
    ]
    built = [(mu.mid, mu.gate) for mu in MUTATIONS if mu.mid.startswith("M-")]
    if listed != built:
        ok = False
        lines.append(
            f"  section 16.2 lists {len(listed)} M-rows, the tool builds {len(built)}: they differ"
        )
    pristine = digest_texts(spec_f, hand_f, *(x for _n, x in plans))
    for mu in MUTATIONS:
        s = mu.spec(spec_f, values) if mu.spec else spec_f
        h = mu.hand(hand_f, values) if mu.hand else hand_f
        new_plans = plans
        if mu.plan:
            key, fn = mu.plan
            new_plans = tuple((nn, fn(x) if nn == key else x) for nn, x in plans)
        if (s, h, new_plans) == (spec_f, hand_f, plans) and mu.patch is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        undo = mu.patch() if mu.patch else None
        try:
            fails, _n2, _w, _c = audit(Texts(s, h, new_plans, values), git_fetch)
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
        restored = digest_texts(spec_f, hand_f, *(x for _n, x in plans)) == pristine
        restored = restored and digest(paths) == on_disk and not MARK_MIN_OVERRIDE
        ok = ok and hit and restored
        first = ascii_line((named or new or ["nothing new"])[0][:110])
        lines.append(
            f"  {mu.mid} [{mu.gate or 'none'}] {'ok' if hit else 'MISSED'} ({len(new)} new"
            f"{'' if restored else ', NOT RESTORED'}) - {first}"
        )
        if not hit:
            lines += [f"      new: {ascii_line(x[:200])}" for x in new]
    return ok, lines


# ---------------------------------------------------------------------------- main


def write_text(path: Path, text: str) -> None:
    """Every writer opens its file with newline="\\n"."""
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv: list[str]) -> int:
    # the reports print `→`, `§` and `…`: a cp1252 (or any non-UTF-8) console must not crash them,
    # and `python3 -I` ignores PYTHONIOENCODING, so the tool sets the stream itself
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="E08-D08 scanner audit (module docstring)")
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
    ap.add_argument("--fill", action="store_true", help="replace placeholders, then check")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="apply every mutation")
    ap.add_argument("--repin-ruled", action="store_true", help=f"rewrite {RULED_PIN_TXT}")
    args = ap.parse_args(argv)
    spec_path = ROOT / (args.check or SPEC_REL)
    hand_path = ROOT / args.handoff
    spec = spec_path.read_bytes().decode("utf-8")
    hand = hand_path.read_bytes().decode("utf-8")
    if args.repin_ruled:
        left = PLACEHOLDER.findall(CODE.sub("", spec + hand))
        if left:
            print(f"FAIL --repin-ruled: {len(left)} unfilled placeholders; run --fill first")
            return 1
        units = ruled_units(spec, hand, compute(spec, hand)[0])
        write_text(ROOT / RULED_PIN_TXT, write_pins(units))
        print(f"--repin-ruled: {len(units)} units pinned in {RULED_PIN_TXT}")
        return 0
    if args.self_test:
        paths = (spec_path, hand_path, ROOT / RULED_PIN_TXT, *(p for _n, p in plan_paths()))
        ok, lines = selftest(spec, hand, paths)
        print("\n".join(lines))
        print(f"--self-test: {'ok' if ok else 'FAIL'} - {len(MUTATIONS)} mutations in memory")
        return 0 if ok else 1
    values, extra = compute(spec, hand)
    if args.fill:
        spec, unknown = fill(spec, values)
        hand, unknown_h = fill(hand, values)
        write_text(spec_path, spec)
        write_text(hand_path, hand)
        for u in unknown + unknown_h:
            print(f"FAIL --fill: no value for {{{{{u}}}}}")
        values, extra = compute(spec, hand)
    if args.json and not (args.check or args.fill):
        print(json.dumps({"values": values, "extra": extra}, ensure_ascii=False, indent=1))
        return 0
    t = Texts(spec, hand, read_plans(), values)
    fails, notes, warns, n = audit(t, git_fetch)
    if args.json:
        doc = {"values": values, "extra": extra, "fails": fails, "notes": notes, "warnings": warns}
        print(json.dumps(doc | {"cites": n}, ensure_ascii=False, indent=1))
    else:
        gates = len(LEXICON_GATES) + len(MEASURED_GATES) + 5
        shown = spec_path.relative_to(ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        print(f"## E08-D08 audit of {shown} (+ the hand-off) at base {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(notes))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK - every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(notes)} NOTE, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
