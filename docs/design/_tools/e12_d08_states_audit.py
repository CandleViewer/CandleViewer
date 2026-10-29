#!/usr/bin/env python3
"""E12-D08 (#243) audit: the rebuild, partial-history, empty and error states (spec + hand-off).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base `527cf2b253` (`git show`): the token JSON (`themes.json` layering:
dark = primitives + semantic-dark, light = + semantic-light, hc = + semantic-hc), the plan texts
the spec cites (`22`'s `x-error-codes` and `getBars`, `23` §10.2, `14`'s SCR-030 matrix), the
merged design docs it cites, the shipped bars route, the RBAC seed, the ticket JSON (`E12.json`:
T and the consumers' bodies), `calendar_cv.py` and the research CVD script; then this ticket's
spec and hand-off from the working tree, and the working-tree files RULED BQ-3 keeps untouched.

1. **Values (RULED 6475004920, BQ-1).** Every `{{KIND:key}}` outside a code span is COMPUTED:
   CITE (a figure parsed from its cited line at the base: the window, the phases, the ladder and
   its stops, the countdown, the cadences, the budget, the slow path, the cancel bound, the dash,
   the bootstrap bound), COUNT (boards, twins, frames, the SCR-047 frames and the `reason` enum,
   the SCR-048 classes and the `kind` enum, the matrix pairs, the contrast pairs, themes, the CVD
   simulations, the line budgets), HEX (every bound token in dark / light / hc) and CONTRAST
   (WCAG 2.x, truncated to two decimals). `--fill` writes `VALUE<!--=KIND:key-->`; `--check`
   re-derives every anchored value with a left boundary, and FAILs a `{{` left outside a code
   span, a figure typed by hand before a unit or a counted noun, a count written as a word
   (G-WORDCOUNT) and a hand-typed hex.
2. **The comment strip.** One pattern over the whole text, `re.DOTALL`; every comment must be a
   value anchor the tool computes (G-MARKER); a `[//]: #` comment or any link-reference line is
   hidden text and FAILs (G-HIDDEN); the lexicon gates read rendered text only.
3. **Cites.** Every cite is read at the base (G-CITE: FAIL when a line is gone or blank), and
   G-VERSION FAILs (never WARNs) when any line inside any cited range differs at `origin/main`, or
   when `origin/main` does not resolve; it also reads the **Start.** and **Version.** lines (every
   merged input's sha under the base, the late change of #4853 recorded). G-QUOTE: every
   backticked field, event or schema name is verbatim in a source the line cites (or the ticket
   texts), or a PROPOSED name; every quoted string of 12 characters or more is verbatim there or
   an instance of a W-n string of the spec's copy deck.
4. **Gates.** Lexicon gates read rows and prose after the comment strip (NFKC, markup dropped,
   dashes to spaces, lower case; a claim is read per clause; a negation covers its own term within
   five words and a list coordinated after it; quoted copy, the mutation list and the hand-off's
   Old cells are not claims), and every ruled behaviour also has synonyms refused (never
   approximate, the one primary, the ladder's stops, `Cancel` from the strip's first line, focus
   kept, no GL for SCR-047, no new data-confidence state). Measured gates read the tables column
   by column: the mapping table against both registries (G-MAP), the matrix against `14`:746-761
   (G-MATRIX), the reasons and classes pairwise (G-REASONS, G-CLASSES), the deck against its
   sources (G-DECK), the frames, the pairs, the C-rows, the G-ledger, the Q-rows, the dry run and
   Table A. G-UNTOUCHED compares committed and uncommitted paths with
   `git merge-base HEAD origin/main` and FAILs when it does not resolve or git cannot list the
   paths; only this PR's four files may differ (untracked files `.gitignore` hides are not seen:
   git never commits them). G-REVIEW reads §16.1 (the `14` checklists, the flows, the heuristics,
   the session protocol). G-CHARSET, G-CELLS (escaped pipes kept), G-CLOSE, G-BUDGET close the
   set. The report header names the `origin/main` sha drift was read against, and WARNs when it
   equals the base.
5. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over EVERY unit of both docs, in
   RULED_PIN_TXT: each heading, table row (by its lead cell), rule line, prose sentence and fenced
   block, by doc, region (heading path plus occurrence), location and exact text (NFKC, whitespace
   collapsed), with a line-shape tag per region. Anchored values are pinned with their values cut
   out (G-ANCHOR owns them). `--repin-ruled` is the only writer and refuses while a placeholder is
   unfilled. A pin finding in a section another gate already FAILs prints as a NOTE line.
6. **--self-test** applies every mutation of the spec's §14.2 (M-n) and the tool's own X-n
   (paraphrases), P-n (one per pin class) and N-n probes (which must trip nothing), with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names, and every
   text is restored byte-identically (sha256 in memory and on disk). The report is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e12_d08_states_audit.py --check [SPEC] [--handoff F] \
      [--json] [--fill]
  python3 -I docs/design/_tools/e12_d08_states_audit.py --self-test
  python3 -I docs/design/_tools/e12_d08_states_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import datetime
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
BASE = "527cf2b253"  # every cite was read here (the spec's Inputs line; the merge-base at start)
HEAD = "origin/main"  # G-VERSION: a cited line that drifts here FAILs
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E12/E12-D08.md"
HAND_REL = "docs/design/E12/E12-D08-handoff.md"
RULED_PIN_TXT = "docs/design/_tools/e12_d08_ruled_pins.txt"
DS_SRC_REL = "packages/ui/tokens"
CVD_SRC = "docs/research/_tools/cvd_simulate.py"
# RULED BQ-3 and the standing list: never edited by this ticket (PR 1 or PR 2)
UNTOUCHED = ("14", "15", "16", "22", "23", "24")
UNTOUCHED_DOCS = ("D02", "D03", "D06", "D09", "E11-D02", "E11-D04", "E11-D05", "E16-D05", "SEED")
# the only paths this PR may add or change against the merge-base (the PR 2 boards come later)
OWN_PATHS = (
    "docs/design/E12/E12-D08.md",
    "docs/design/E12/E12-D08-handoff.md",
    "docs/design/_tools/e12_d08_states_audit.py",
    "docs/design/_tools/e12_d08_ruled_pins.txt",
)
CITE_FILES: dict[str, str] = {
    "D01": "docs/design/E12/E12-D01.md",
    "D02": "docs/design/E12/E12-D02.md",
    "D03": "docs/design/E12/E12-D03.md",
    "D04": "docs/design/E12/E12-D04.md",
    "D05": "docs/design/E12/E12-D05.md",
    "D06": "docs/design/E12/E12-D06.md",
    "D09": "docs/design/E12/E12-D09.md",
    "RF": "docs/research/findings/E12-bar-modes.md",
    "ADR33": "docs/plan/27-adrs/ADR-0033-renko-brick-sizing-and-series-rebuild.md",
    "MR": "services/api/candleviewer/api/market_response.py",
    "MB": "services/api/candleviewer/api/market_bars.py",
    "SEED": "services/api/candleviewer/auth/rbac_seed.json",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "VAL": "docs/plan/backlog/_tools/validate.py",
    "README": "docs/design/README.md",
    "E12J": "docs/plan/backlog/E12.json",
}
# the ticket texts (bodies inside E12J): T (#243) and the consumers the dry run reads (BQ-29)
TICKET_KEYS = {
    "T": "E12-D08",
    "S06": "E12-S06",
    "S11": "E12-S11",
    "S12": "E12-S12",
    "Q03": "E12-Q03",
    "Q07": "E12-Q07",
    "D13": "E12-D13",
}
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SEMANTIC = ("semantic-dark", "semantic-light", "semantic-hc")

RULING_ID = "6475004920"
BQ_LIST_ID = "6473367744"
RULED_IDS = (RULING_ID, BQ_LIST_ID)  # the allow-list: every comment id the docs cite
OWNER_PENDING = "PROPOSED, owner approval pending (#2701)"  # BQ-31
CONFIRMED = ("BQ-3", "BQ-4", "BQ-6", "BQ-7", "BQ-11", "BQ-13", "BQ-14", "BQ-18", "BQ-19", "BQ-21")
CONFIRMED_LAST = "BQ-22"  # the eleventh of the ruling's explicit confirmations
DONE_TARGET = "2026-11-06"  # BQ-31's targeted Done date (the ruling)
MAX_BOARDS = 10  # RULED BQ-6 (lever 4): at most ten boards
TWIN_SHARE = Fraction(1, 3)  # twins at most a third of the boards (lever 4)
# RULED BQ-6: the three twins, exactly: board -> (theme, source board)
TWINS = {"08": ("light", "01"), "09": ("light", "06"), "10": ("hc", "05")}
SPEC_LINE_BUDGET = 600  # "about 600 lines at most"
HAND_LINE_BUDGET = 150  # "about 150 lines at most"
MAX_WALK = 10  # the owner walkthrough (hand-off §E): at most ten items (RULED BQ-30, rider d)
# the version line (spec **Start.** and **Version.**): every merged input's sha, in order
START_SHAS = (
    "8e2b2d8a78",
    "de8b7242f0",
    "41d81b2bd5",
    "513ba523d5",
    "63b13d034a",
    "5dce4dd2ff",
    "cba937ef0f",
    "d117dc7328",
    "d05966f7a6",
    "a899ca1760",
    "da7b0f8a92",
    "afebadb0fa",
    "d6597cbcf7",
    "43c5ebdd86",
)
VERSION_SHAS = (
    "527cf2b253",
    "41d81b2bd5",
    "63b13d034a",
    "5dce4dd2ff",
    "d117dc7328",
    "afebadb0fa",
    "afebadb0fa",
    "d1a687b743",
)
# RULED rider e: the late change, recorded in the version line
LATE_CHANGE = ("**Late change (RULED rider e):**", "#4853", "afebadb0fa", "2026-10-28")
# named only, never pinned or quoted (S-9; rider e): no sha of theirs may appear
UNMERGED = ("#4501", "#242", "#245", "#312", "#313", "#4787")
# the dry run's rows, in order (BQ-29; rider d): consumers, then the frontend and QA passes
WALK_ROLES = (
    "story: E12-S06 (#395)",
    "story: E12-S11 (#451)",
    "story: E12-S12 (#535)",
    "QA: E12-Q03 (#419)",
    "QA: E12-Q07 (#530)",
    "design QA: E12-D13 (#450)",
    "frontend: typeability",
    "QA: §4 and §14.1, every state row",
)
WALK_DATE = "2026-10-28"
# consumer -> its ticket key in E12J (its sprint gives the due date through CAL)
CONSUMER_KEYS = {
    "E12-S06 (#395)": "E12-S06",
    "E12-S11 (#451)": "E12-S11",
    "E12-S12 (#535)": "E12-S12",
    "E12-Q03 (#419)": "E12-Q03",
    "E12-Q07 (#530)": "E12-Q07",
    "E12-D13 (#450)": "E12-D13",
}

# CITE values: key -> (cite id, line, pattern whose group 1 is the value)
CITE_VALUES: dict[str, tuple[str, int, str]] = {
    "viewport.w": ("16", 212, r"\*\*(\d+)×\d+px\*\*"),
    "viewport.h": ("16", 212, r"\*\*\d+×(\d+)px\*\*"),
    "silent": ("D02", 29, r"nothing for (\d+) ms"),
    "cancel.old": ("D02", 29, r"after (\d+) s;"),
    "ladder.1": ("14", 1111, r"\((\d+)s, \d+s, \d+s, \d+s"),
    "ladder.2": ("14", 1111, r"\(\d+s, (\d+)s, \d+s, \d+s"),
    "ladder.3": ("14", 1111, r"\(\d+s, \d+s, (\d+)s, \d+s"),
    "ladder.4": ("14", 1111, r"\(\d+s, \d+s, \d+s, (\d+)s"),
    "ladder.cap": ("14", 1111, r"capped (\d+)s\)"),
    "attempts.context": ("E11-D04", 374, r"attempt 1 of (\d+)"),
    "countdown.hz": ("E11-D04", 381, r"updated at (\d+) Hz"),
    "cadence.rf": ("RF", 181, r"updated at ≤(\d+) Hz"),
    "budget.s": ("11", 935, r"complete in ≤(\d+) s"),
    "budget.m": ("11", 935, r"rebuilds of (\d+)M prints"),
    "slow.s": ("15", 436, r"slow \(after (\d+) s,"),
    "cancel.s": ("D02", 370, r"cancel ≤(\d+) s"),
    "dash": ("E11-D05", 315, r"dashed (\d+) / \d+ edges"),
    "dash.gap": ("E11-D05", 315, r"dashed \d+ / (\d+) edges"),
    "bootstrap.s": ("E11-D04", 968, r"bootstrap (\d+) s"),
    "target.min": ("05", 100, r"≥(\d+)×\d+ CSS px"),
    "zoom": ("05", 131, r"(\d+)% browser"),
}
# the ruling's own figures (comment 6475004920, BQ-21: `Esc` cancels from 0 ms)
RULED_VALUES = {"RULED:esc.ms": "0"}
# load-bearing fragments: (cite id, line at the base, text the line must hold)
CITED: tuple[tuple[str, int, str], ...] = (
    ("14", 736, "a progress bar with `Cancel` after 2 s"),
    ("14", 737, "Dashed full-height boundary with a text tag"),
    ("14", 743, "rebuilding > cache-loading > partial-history"),
    ("14", 761, "empty and error (error wins"),
    ("14", 1085, "exchange returned no bars"),
    ("14", 1096, "CMP-029 Skeleton-Chart placeholder."),
    ("14", 1100, "`chart.empty_state_shown`"),
    ("14", 1102, "no infinite spinner path"),
    ("14", 1111, "capped 30s"),
    ("14", 1113, "WebGL-unavailable fallback message"),
    ("15", 275, "an unknown total uses CMP-038"),
    ("15", 435, "a load, an export or a replay only"),
    ("22", 4189, "`no_data_recorded` (422) rather than silently"),
    ("22", 16937, "matches the `X-Correlation-Id` header"),
    ("22", 16957, "retry_after_seconds"),
    ("23", 1547, '"request_id"'),
    ("D02", 29, "| D-5  |"),
    ("D02", 37, "Emptiness comes only from `no_data_recorded`"),
    ("D02", 270, "Build cancelled at 40 %"),
    ("D02", 271, "The bar service is busy. Try again shortly."),
    ("D02", 328, "`bar_window_too_large` and `response_too_large` never reach the user"),
    ("D03", 208, "A size this small can stop updating after one very large trade."),
    ("D06", 289, "never hatched and never a band"),
    ("D09", 117, "`Cancel` sits on the strip, not on CMP-038"),
    ("E11-D04", 351, "Live data is streaming at a reduced rate."),
    ("E11-D04", 367, "while disconnected — it will load when the connection returns."),
    ("E11-D04", 386, "`Problem.detail`"),
    ("E11-D04", 406, '`kind: "engine" \\| "data-feed" \\| "backend"`'),
    ("E16-D05", 154, "`empty.cause.recorded_only`"),
    ("E16-D05", 168, "`empty.cause.interval_too_fine`"),
    ("RF", 146, "no cancel needed yet"),
    ("ADR33", 158, "only the requesting principal (or Owner) may cancel"),
    ("VAL", 55, '"R7 Data accuracy"'),
    ("CAL", 13, "SPRINT01_START = datetime.date(2026, 9, 25)"),
    ("02", 53, "explicit Architect/CDO waiver"),
    ("apps/web/e2e/specs/e12-bars/history-states.spec.ts", 8, "test.fixme(true"),
)

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z0-9]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
UNITS = r"(?:ms|s|hz|px|%|:1|fps)"
COUNTED = (
    r"(?:boards?|twins?|frames?|columns?|rows?|states?|pairs?|themes?|questions?"
    r"|mutations?|samples?|characters?|lines?|consumers?|seconds?|minutes?|items?|options?"
    r"|simulations?|g-rows?|c-rows?|q-rows?)"
)
FIGURE = re.compile(
    rf"(?<![\w.,:#/>{{§+~-])(\d+(?:[.,]\d+)*)\s?(?:{UNITS}(?![\w])|{COUNTED}\b)", re.IGNORECASE
)
NUM_WORDS = (
    "two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    "|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|hundred"
)
WORDCOUNT = re.compile(rf"\b({NUM_WORDS})\b(?:\s+[\w'’-]+){{0,2}}?\s+{COUNTED}\b", re.IGNORECASE)
CITE_GROUP = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:D0[1-69]|RF|ADR33|MR|MB|SEED|CAL|VAL|README|E12J"
    r"|E\d\d-D\d\d)\b)) ?"
    r":(?P<first>\d+(?:[–-]\d+)?)(?P<more>(?:(?:\s*\([^()\n]*\))?,\s*:\d+(?:[–-]\d+)?)*)"
)
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]|\b[a-z0-9-]+\.(?:com|net|org|io|dev)\b", re.IGNORECASE)
COMMENT_ID = re.compile(r"(?<![\w-])(\d{8,})(?![\w-])")

Values = dict[str, str]
Fetch = Callable[[str, str], str | None]
DRIFT: list[tuple[str, int, str]] = []  # self-test lever: (path, line, text) read at HEAD
BROKEN: list[str] = []  # self-test lever: "head" / "merge-base" do not resolve, "diff" errors
CVD_DRIFT: list[str] = []  # self-test lever: the research CVD script as changed at the base
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
    return git_run(*args)[1]


def git_run(*args: str) -> tuple[bool, str]:
    """(ok, stdout): ok is False on a non-zero exit, a timeout or an OS error, so a caller that
    must fail closed can tell "no output" from "git could not answer" (lens 2 Minor 1)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return out.returncode == 0, out.stdout.decode("utf-8") if out.returncode == 0 else ""


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


MUTATION_HEAD = "14.2 The mutation list"  # its rows describe the violations they plant
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
def ticket_items() -> tuple[dict[str, object], ...]:
    data = json.loads(at_base(CITE_FILES["E12J"]))
    return tuple(x for x in data if isinstance(x, dict))


@functools.lru_cache(maxsize=1)
def tickets() -> dict[str, str]:
    """The bodies of T and the dry run's consumers in E12J at the base."""
    out: dict[str, str] = {}
    for item in ticket_items():
        for short, key in TICKET_KEYS.items():
            if item.get("key") == key:
                out[short] = str(item.get("body", ""))
    if set(out) != set(TICKET_KEYS):
        raise SystemExit(f"FAIL parse: ticket bodies missing in E12J ({sorted(out)})")
    return out


def t_section(short: str, head: str) -> str:
    body = tickets()[short]
    m = re.search(rf"^## {re.escape(head)}[^\n]*\n(.*?)(?=^## |\Z)", body, re.MULTILINE | re.DOTALL)
    return m[1] if m else ""


def t_scenarios() -> list[str]:
    """T's Gherkin scenarios, in order (the trace's AC1 ... AC5)."""
    return re.findall(r"^Scenario: (.+)$", t_section("T", "Acceptance criteria"), MULTI)


def t_cadence() -> str:
    return grab(r"coalesced \(≤(\d+) Hz\)", t_section("T", "Performance notes"), "T Perf cadence")


def sprint_start(key: str) -> str:
    """The sprint start of an E12 ticket: its `sprint` field through CAL's Sprint 01 + n weeks."""
    item = next((x for x in ticket_items() if x.get("key") == key), None)
    m = re.fullmatch(r"Sprint (\d+)", str(item.get("sprint", "")) if item else "")
    cal = at_base(CITE_FILES["CAL"])
    ymd = re.search(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", cal)
    days = re.search(r"^SPRINT_DAYS = (\d+)", cal, MULTI)
    if not m or not ymd or not days:
        raise SystemExit(f"FAIL parse: the sprint of {key} or CAL's calendar")
    first = datetime.date(int(ymd[1]), int(ymd[2]), int(ymd[3]))
    return (first + datetime.timedelta(days=(int(m[1]) - 1) * int(days[1]))).isoformat()


# ---------------------------------------------------------------------------- the registries


@functools.lru_cache(maxsize=1)
def rest_codes() -> dict[str, int]:
    """`22`'s `x-error-codes`: code -> status."""
    block = plan("22").split("\n")[499:810]
    out: dict[str, int] = {}
    code = ""
    for ln in block:
        m = re.match(r"^  - code: ([a-z_]+)$", ln)
        if m:
            code = m[1]
            continue
        s = re.match(r"^    status: (\d{3})$", ln)
        if s and code:
            out[code] = int(s[1])
            code = ""
    if len(out) < 40:
        raise SystemExit("FAIL parse: `22`'s x-error-codes")
    return out


@functools.lru_cache(maxsize=1)
def ws_codes() -> frozenset[str]:
    """`23` §10.2's codes (the table at `23`:1578-1608)."""
    lines = plan("23").split("\n")[1577:1608]
    got = {m[1] for ln in lines if (m := re.match(r"^\| `([a-z_]+)`\s*\|", ln))}
    if len(got) < 20:
        raise SystemExit("FAIL parse: `23` §10.2")
    return frozenset(got)


def getbars_statuses() -> tuple[int, ...]:
    """`getBars`' declared error statuses (`22`:4264-4268)."""
    lines = plan("22").split("\n")[4263:4268]
    return tuple(int(m[1]) for ln in lines if (m := re.match(r'^\s+"(\d{3})":', ln)))


@functools.lru_cache(maxsize=1)
def shipped_codes() -> frozenset[str]:
    """The codes the shipped bars route answers (MB, read as text)."""
    return frozenset(re.findall(r'problem\(\d+, "([a-z_]+)"', at_base(CITE_FILES["MB"])))


def e11d04_codes() -> frozenset[str]:
    """The data-feed and backend triggers of E11-D04 §12.1 (E11-D04:367-368)."""
    text = "\n".join(base_line("E11-D04", n).split("|")[2] for n in (367, 368))
    return frozenset(re.findall(r"`([a-z_]+)`", text)) & registry()


# BQ-11's own list (the ruling): the codes it names beyond the registries' reach above
BQ11_CODES = frozenset(
    {
        "exchange_unavailable",
        "exchange_rate_limited",
        "exchange_error",
        "degraded_data",
        "subscription_limit",
        "unsupported_symbol",
        "invalid_topic_format",
        "encoding_unsupported",
        "internal_error",
        "not_implemented",
        "store_unavailable",
        "timeout",
        "validation_failed",
        "forbidden",
        "invalid_cursor",
        "bar_window_too_large",
        "response_too_large",
        "unauthenticated",
        "no_data_recorded",
    }
)
# signals that are not registry codes (client-side or engine), each mapped by name in §4
NON_REGISTRY = frozenset(
    {
        "bar_rebuild_too_large",
        "bar_rebuild_busy",
        "webglcontextlost",
        "recording_started_at",
        "recorded",
    }
)


@functools.lru_cache(maxsize=1)
def ws_scoped() -> frozenset[str]:
    """`23` §10.2's codes whose Scope is `topic`, `request` or `any`: every one a `bars.*`
    subscribe can be answered with (the `connection` rest are the session's and SCR-152's)."""
    lines = plan("23").split("\n")[1577:1608]
    got = {
        m[1]
        for ln in lines
        if (m := re.match(r"^\| `([a-z_]+)`\s*\|\s*(topic|request|any)\s*\|", ln))
    }
    if len(got) < 15:
        raise SystemExit("FAIL parse: `23` §10.2's scopes")
    return frozenset(got)


# connection-scope codes a bars chart still meets: a bars body that fails its decoder (`23`:271)
# and the outbound-queue close that takes the transport down (`23`:1601)
WS_BARS_CONNECTION = frozenset({"frame_malformed", "slow_consumer"})


def reachable_codes() -> frozenset[str]:
    """Every code a chart can meet from `getBars` and the `bars.*` subscribe: the shipped route,
    E11-D04's triggers, BQ-11's list, `rate_limited` (the per-user 429 of every route), every
    topic-, request- and any-scope code of `23` §10.2, and the two connection-scope codes a bars
    body and the socket's queue meet (derived from the registries, never a curated list alone)."""
    return frozenset(
        shipped_codes()
        | e11d04_codes()
        | BQ11_CODES
        | {"rate_limited"}
        | ws_scoped()
        | WS_BARS_CONNECTION
    )


def registry() -> frozenset[str]:
    return frozenset(rest_codes()) | ws_codes()


# ---------------------------------------------------------------------------- tokens and pairs

BOUND = (
    "surface.canvas",
    "surface.raised",
    "surface.sunken",
    "text.primary",
    "text.secondary",
    "text.tertiary",
    "status.danger.strong",
    "status.warning.subtle",
    "status.warning.strong",
    "action.primary.default",
    "surface.hover",
    "text.on-action",
    "focus.ring",
)
PAIRS: dict[str, tuple[str, str, str]] = {
    "primary-canvas": ("text.primary", "surface.canvas", "text"),
    "secondary-canvas": ("text.secondary", "surface.canvas", "text"),
    "primary-raised": ("text.primary", "surface.raised", "text"),
    "secondary-raised": ("text.secondary", "surface.raised", "text"),
    "primary-sunken": ("text.primary", "surface.sunken", "text"),
    "tertiary-canvas": ("text.tertiary", "surface.canvas", "mark"),
    "tertiary-raised": ("text.tertiary", "surface.raised", "mark"),
    "danger-raised": ("status.danger.strong", "surface.raised", "mark"),
    "primary-warning": ("text.primary", "status.warning.subtle", "text"),
    "warnstrong-warning": ("status.warning.strong", "status.warning.subtle", "mark"),
    "fill-track": ("action.primary.default", "surface.hover", "mark"),
    "onaction-action": ("text.on-action", "action.primary.default", "text"),
    "ring-raised": ("focus.ring", "surface.raised", "mark"),
    "ring-canvas": ("focus.ring", "surface.canvas", "mark"),
}
# routed names, cited as PROPOSED, never bound (E11-D05:92)
NOT_SHIPPED = {"color.chart.boundary"}
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


# ---------------------------------------------------------------------------- CVD
#
# The Brettel (1997) / Vienot protan and deutan projections and the Machado, Oliveira & Fernandes
# (2009) tritan matrix, carried as constants (no import of repo code); G-CVD checks each number
# against `docs/research/_tools/cvd_simulate.py` at the base, and two pinned simulations.
RGB_TO_LMS = (
    17.8824, 43.5161, 4.11935,
    3.45565, 27.1554, 3.86714,
    0.0299566, 0.184309, 1.46709,
)  # fmt: skip
LMS_TO_RGB = (
    0.0809444479, -0.130504409, 0.116721066,
    -0.0102485335, 0.0540193266, -0.113614708,
    -0.000365296938, -0.00412161469, 0.693511405,
)  # fmt: skip
PROTAN = (0.0, 2.02344, -2.52581, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
DEUTAN = (1.0, 0.0, 0.0, 0.494207, 0.0, 1.24827, 0.0, 0.0, 1.0)
TRITAN = (
    1.255528, -0.076749, -0.178779,
    -0.078411, 0.930809, 0.147602,
    0.004733, 0.691367, 0.303900,
)  # fmt: skip
SIMS = ("protan", "deutan", "tritan")
# simulate(#8B5CF6) and simulate(#2EBD59) under protan / deutan / tritan (E12-D09's pins)
CVD_PINNED: dict[str, tuple[str, str, str]] = {
    "#8B5CF6": ("#6363F6", "#6C6CF6", "#6C80A1"),
    "#2EBD59": ("#B4B458", "#A3A35D", "#00B9A6"),
}


def lin(c: int) -> float:
    v = c / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def unlin(c: float) -> float:
    s = c * 12.92 if c <= 0.0031308 else 1.055 * (max(c, 0.0) ** (1 / 2.4)) - 0.055
    return max(0.0, min(1.0, s)) * 255.0


def matvec(m: tuple[float, ...], v: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
        m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
        m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
    )


def simulate(hex6: str, sim: str) -> str:
    r, g, b = rgb(hex6)
    v = (lin(r), lin(g), lin(b))
    if sim == "tritan":
        out = matvec(TRITAN, v)
    else:
        lms = matvec(RGB_TO_LMS, v)
        out = matvec(LMS_TO_RGB, matvec(PROTAN if sim == "protan" else DEUTAN, lms))
    return "#" + "".join(f"{max(0, min(255, round(unlin(c)))):02X}" for c in out)


def cvd_src_text() -> str:
    return CVD_DRIFT[-1] if CVD_DRIFT else at_base(CVD_SRC)


def cvd_src_problems() -> list[str]:
    """Each constant equals the research script's at the base; the pinned simulations hold."""
    src = cvd_src_text()
    bad: list[str] = []

    def nums(block: str) -> tuple[float, ...]:
        return tuple(float(x) for x in re.findall(r"-?\d+\.\d+(?:e-?\d+)?|-?\d+(?=[,)\s])", block))

    def block(name: str) -> str:
        m = re.search(rf"^{name}\s*=\s*\((.*?)^\)", src, re.MULTILINE | re.DOTALL)
        return m[1] if m else ""

    for name, mine in (("RGB_TO_LMS", RGB_TO_LMS), ("LMS_TO_RGB", LMS_TO_RGB)):
        if nums(block(name)) != mine:
            bad.append(f"{name} differs from {CVD_SRC} at {BASE}")
    for key, mine in (("protanopia", PROTAN), ("deuteranopia", DEUTAN)):
        m = re.search(rf'"{key}":\s*\(([^)]*)\)', src)
        if not m or nums(m[1] + ",") != mine:
            bad.append(f"the {key} projection differs from {CVD_SRC} at {BASE}")
    if nums(block("TRITAN_MACHADO")) != TRITAN:
        bad.append(f"TRITAN_MACHADO differs from {CVD_SRC} at {BASE}")
    for src_hex, want in CVD_PINNED.items():
        got = tuple(simulate(src_hex, s) for s in SIMS)
        if got != want:
            bad.append(f"{src_hex} simulates to {got}, pinned {want}")
    return bad


def mark_keys() -> list[str]:
    return [k for k, (_f, _b, kind) in PAIRS.items() if kind == "mark"]


@functools.lru_cache(maxsize=1)
def cvd_grid() -> dict[tuple[str, str, str], float]:
    """(theme, pair, simulation) -> the contrast of the simulated mark pair."""
    out: dict[tuple[str, str, str], float] = {}
    for th in THEMES:
        for k in mark_keys():
            fg, bg, _kind = PAIRS[k]
            a, b = theme_hex(th, fg), theme_hex(th, bg)
            for s in SIMS:
                out[(th, k, s)] = contrast(simulate(a, s), simulate(b, s))
    return out


# ---------------------------------------------------------------------------- the values


def colour_values() -> Values:
    v: Values = {}
    for t in THEMES:
        for k in BOUND:
            v[f"HEX:{k}.{t}"] = theme_hex(t, k)
    v["CONTRAST:text.min"] = f"{text_min()}:1"
    v["CONTRAST:mark.min"] = f"{mark_min_base()}:1"
    for k in CVD_EXEMPT:
        worst = min(r for (_th, key, _s), r in cvd_grid().items() if key == k)
        v[f"CONTRAST:cvd.{k}.min"] = show_ratio(worst)
    for t, row in contrast_grid().items():
        for k, r in row.items():
            v[f"CONTRAST:{k}.{t}"] = show_ratio(r)
    return v


def cite_values() -> Values:
    v = {
        f"CITE:{k}": grab(pat, base_line(cid, n), f"{cid}:{n} ({k})")
        for k, (cid, n, pat) in CITE_VALUES.items()
    }
    steps = grab(r"automatic ([\d, ]+) s then stop", base_line("E11-D04", 367), "E11-D04:367")
    v["CITE:attempts.feed"] = str(len([x for x in steps.split(",") if x.strip()]))
    v["CITE:cadence.t"] = t_cadence()
    return v


def board_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "0. Status")) if re.fullmatch(r"\d{2}", r[0])]


def is_twin(row: list[str]) -> bool:
    return len(row) > 2 and "twin of" in row[2]


FRAME_HEAD = "14.1 The frame register"
FR_COLS = ("Frame", "Board", "Theme", "State", "Components", "Copy", "Tokens", "Status")
FRAME_STATUS = "to draw (PR 2)"


def frames(spec: str) -> list[dict[str, str]]:
    rows = [r for r in table_rows(section(spec, FRAME_HEAD)) if r and r[0].startswith("`")]
    return [dict(zip(FR_COLS, r, strict=False)) for r in rows]


REASONS_HEAD = "3.1 The frames"
CLASSES_HEAD = "5.1 The three classes"
MAP_HEAD = "4. The error"
MATRIX_HEAD = "9.1 The matrix"
DECK_HEAD = "11. Copy deck"
PAIRS_HEAD = "12. Tokens"
FOURWAY = "rebuilding + partial-history + stale + LOD-aggregated (the four-way row)"


def reason_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, REASONS_HEAD)) if r[0].startswith("`SCR-047/")]


def class_rows(spec: str) -> list[list[str]]:
    return table_rows(section(spec, CLASSES_HEAD))


def matrix_rows(spec: str) -> list[list[str]]:
    return table_rows(section(spec, MATRIX_HEAD))


def pair_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, PAIRS_HEAD)) if " on " in r[0]]


def enum_count(cid: str, n: int, field_: str) -> int:
    """How many values the enum of `field_` lists on its cited line."""
    line = base_line(cid, n)
    m = re.search(rf"{field_}:\s*(.+?)(?:\}}|`\s*\(|`,|$)", line)
    if not m:
        raise SystemExit(f"FAIL parse: {cid}:{n} has no {field_} enum")
    return len(re.findall(r"['\"]([a-z_-]+)['\"]", m[1]))


def count_values(spec: str) -> Values:
    bd = board_rows(spec)
    twins = [r for r in bd if is_twin(r)]
    themes = json.loads(at_base(f"{DS_SRC_REL}/themes.json"))["themes"]
    return {
        "COUNT:boards": str(len(bd)),
        "COUNT:boards.dark": str(len(bd) - len(twins)),
        "COUNT:boards.twins": str(len(twins)),
        "COUNT:frames": str(len(frames(spec))),
        "COUNT:scr047.frames": str(len(reason_rows(spec))),
        "COUNT:reason.enum": str(enum_count("14", 1100, "reason")),
        "COUNT:scr048.classes": str(len(class_rows(spec))),
        "COUNT:kind.enum": str(enum_count("E11-D04", 406, "kind")),
        "COUNT:matrix.pairs": str(len([r for r in matrix_rows(spec) if r[0] != FOURWAY])),
        "COUNT:pairs": str(len(PAIRS)),
        "COUNT:themes": str(len(themes)),
        "COUNT:cvd.pairs": str(len(cvd_grid())),
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
        "rest_codes": len(rest_codes()),
        "ws_codes": sorted(ws_codes()),
        "getbars_statuses": list(getbars_statuses()),
        "shipped_codes": sorted(shipped_codes()),
        "reachable": sorted(reachable_codes()),
        "t_scenarios": t_scenarios(),
        "contrast": {
            t: {k: round(r, 3) for k, r in row.items()} for t, row in contrast_grid().items()
        },
        "cvd_min": round(min(cvd_grid().values()), 3),
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
    ("11. Copy deck", (1,)),
    ("16. The dry run", (2, 3, 4)),
)


def blanked(text: str) -> dict[str, tuple[int, ...]]:
    out: dict[str, tuple[int, ...]] = {}
    for ln in section(text, MUTATION_HEAD).split("\n")[1:]:
        out[ln] = (-1,)  # the mutation list names the violations it plants: never read
    for head, cols in COPY_CELLS:
        for ln in section(text, head).split("\n"):
            if ln.startswith("|") and not is_rule(ln):
                out[ln] = cols
    return out


def plain(line: str, values: Values, blank: dict[str, tuple[int, ...]]) -> str:
    """The line with anchored values, placeholders, quotes, code spans, cites, ids and dates cut,
    and the copy cells of COPY_CELLS dropped."""
    work = line
    if blank.get(line) == (-1,):
        return ""
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


@functools.lru_cache(maxsize=1)
def head_sha() -> str:
    """The `origin/main` G-VERSION read, as 10 hex (the report header prints it)."""
    return git_out("rev-parse", "--short=10", f"{HEAD}^{{commit}}").strip()


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
        "before_start",
        "exchange_no_bars",
        "not_trading",
        "empty.cause.exchange_no_bars",
        "color.chart.boundary",
    }
)
SNAKE = re.compile(r"(?<![\w.$/{-])((?:[a-z][a-z0-9]*\.)*[a-z][a-z0-9]*_[a-z0-9_]+(?:\.\*)?)\b")
SCHEMA = re.compile(r"`([A-Z][a-z]+(?:[A-Z][a-z0-9]+)+)`")
PERM = re.compile(r"`([a-z]+:(?:read|write|manage|arm_live|export))`")
QUOTE_MIN = 12
# G-QUOTE skips the rows other gates own: Table A (G-AROW), the deck (G-DECK), the mutation list
QUOTE_SKIP = ("Table A", DECK_HEAD, MUTATION_HEAD)


def deck(spec: str) -> dict[str, str]:
    return {
        r[0]: r[1]
        for r in table_rows(section(spec, DECK_HEAD))
        if re.fullmatch(r"W-\d+", r[0]) and len(r) > 3
    }


def deck_rows(spec: str) -> dict[str, list[str]]:
    return {r[0]: r for r in table_rows(section(spec, DECK_HEAD)) if re.fullmatch(r"W-\d+", r[0])}


def quoted_parts(cell: str) -> list[str]:
    return [q[1:-1] for q in QUOTED.findall(cell)]


def template(s: str) -> str:
    """A string as a pattern: each `{slot}`, figure, date, time or symbol matches one to four
    words, so a deck string and its slotted form in a hand-off row match each other."""
    parts = re.split(r"\{[^{}]*\}", s)
    return r"\S+(?: \S+){0,3}?".join(re.escape(p) for p in parts)


def shape(s: str) -> str:
    """A string with its variable parts cut: slots, figures, dates, times and symbols."""
    s = re.sub(r"\{[^{}]*\}|<[^<>]*>", "§", s.replace("...", "…"))
    s = re.sub(r"\b[A-Z]{3,}USDT\b", "§", s)
    s = re.sub(r"\d+(?:[:.,-]\d+)*(?:\s?(?:M|ms|s|%|m|h|d|UTC)\b)?", "§", s)
    s = re.sub(r"\b(?:Renko|Volume|Range|Tick|Delta)\s+§(?:\s+(?:ticks?|BTC|bricks?))?", "§", s)
    return " ".join(re.sub(r"(?:§\s*)+", "§ ", s).split())


@functools.lru_cache(maxsize=4)
def deck_patterns(spec: str) -> tuple[re.Pattern[str], ...]:
    pats: list[re.Pattern[str]] = []
    for s in deck(spec).values():
        for q in quoted_parts(s) or [s]:
            pats.append(re.compile(template(q)))
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


def skip_lines(text: str, heads: tuple[str, ...]) -> set[str]:
    return {ln for head in heads for ln in section(text, head).split("\n") if ln.strip()}


def g_quote(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    pats = deck_patterns(t.spec)
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        skip = skip_lines(text, QUOTE_SKIP)
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
                if m[1] not in pool:
                    bad.append(F("G-QUOTE", f"{doc}:{i} `{m[1]}` is in no cited text", doc, sec))
            for m in PERM.finditer(rendered):
                if f'"{m[1]}"' not in at_base(CITE_FILES["SEED"]):
                    bad.append(F("G-QUOTE", f"{doc}:{i} `{m[1]}` is not a permission", doc, sec))
            for q in QUOTED.finditer(CODE.sub(" ", rendered)):
                s = q[0][1:-1]
                if len(s) < QUOTE_MIN or loose(s) in lpool or s == OWNER_PENDING:
                    continue
                if "{" in s and re.search(template(loose(s)), lpool):
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
    """BQ-1: §0 states the E12 states are unbuilt and that the spec is the implementation
    contract; the base builds no SCR-047 or SCR-048 in `apps/web/src`."""
    sec = spec_sec(t, "0. Status")
    body = norm_text(section(t.spec, "0. Status"))
    bad = [
        F("G-UNBUILT", f"§0 lacks {n!r}", "spec", sec)
        for n in ("the e12 states are unbuilt.", "this spec is the implementation contract")
        if norm_text(n) not in body
    ]
    if git_out("grep", "-l", "SCR-04[78]", BASE, "--", "apps/web/src").strip():
        bad.append(F("G-UNBUILT", "an SCR-047 / SCR-048 surface exists at the base", "spec", sec))
    return bad


def g_trace(t: Texts) -> list[Finding]:
    """BQ-1: the trace holds AC1 ... AC5, one per Gherkin scenario of T."""
    rows = table_rows(section(t.spec, "Acceptance-criteria trace"))
    got = [m[0] for r in rows if (m := re.match(r"AC\d", r[0]))]
    want = [f"AC{n}" for n in range(1, len(t_scenarios()) + 1)]
    sec = spec_sec(t, "Acceptance-criteria trace")
    bad = [] if got == want else [F("G-TRACE", f"the trace rows read {got}", "spec", sec)]
    for r in rows:
        if r[0].startswith("T DoD — Done") and (len(r) < 3 or r[2] != OWNER_PENDING):
            bad.append(F("G-TRACE", "the waiver row is not owner approval pending", "spec", sec))
    return bad


def g_ruled(t: Texts) -> list[Finding]:
    """The RULED heading cites the ruling and the BQ list; the eleven confirmations; BQ-31's
    owner default; every comment id is on the list."""
    bad: list[Finding] = []
    head = next((ln for ln in t.spec.split("\n") if ln.startswith("## The questions")), "")
    sec = spec_sec(t, "The questions")
    body = section(t.spec, "The questions")
    if f"comment {RULING_ID}, on the BQ list {BQ_LIST_ID}" not in head:
        bad.append(F("G-RULED", "the RULED heading does not cite the ruling", "spec", sec))
    ids = ", ".join((*CONFIRMED, CONFIRMED_LAST))
    want = (
        f"the eleven asked for explicitly ({ids}) are carried with the specifics the ruling states",
        f"**BQ-31** is the owner's: {OWNER_PENDING}, Done targeted {DONE_TARGET}",
        "Riders (a) … (e) bind; deviations D1 … D3 are accepted as written",
        "Every ORCH default is taken as proposed",
    )
    for n in want:
        if norm_text(n) not in norm_text(body):
            bad.append(F("G-RULED", f"the RULED section lacks {n[:50]!r}", "spec", sec))
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            for cid in COMMENT_ID.findall(line):
                if cid not in RULED_IDS:
                    bad.append(F("G-RULED", f"{cid} is not a ruling comment", doc, h2_at(text, i)))
    return bad


def g_boards(t: Texts) -> list[Finding]:
    """BQ-6: ten boards at most, twins at most a third and exactly the ruled three; the window;
    illustrative values marked."""
    sec = spec_sec(t, "0. Status")
    rows = board_rows(t.spec)
    bad: list[Finding] = []
    twins = [r for r in rows if is_twin(r)]
    if len(rows) > MAX_BOARDS or Fraction(len(twins), max(len(rows), 1)) > TWIN_SHARE:
        bad.append(F("G-BOARDS", f"{len(rows)} boards, {len(twins)} twins", "spec", sec))
    ids = [r[0] for r in rows]
    if ids != [f"{n:02d}" for n in range(1, len(rows) + 1)]:
        bad.append(F("G-BOARDS", f"board numbers {ids}", "spec", sec))
    for r in rows:
        if len(r) < 5 or r[4] != FRAME_STATUS or not r[1].startswith(f"`E12-D08 / {r[0]} "):
            bad.append(F("G-BOARDS", f"board {r[0]}: name or status", "spec", sec))
            continue
        m = re.fullmatch(r"(light|high-contrast / `forced-colors`) twin of (\d{2})", r[2])
        if is_twin(r):
            got = ({"light": "light"}.get(m[1], "hc"), m[2]) if m else None
            if got != TWINS.get(r[0]) or r[3] != (got[0] if got else ""):
                bad.append(F("G-BOARDS", f"board {r[0]}: not a ruled twin", "spec", sec))
        elif r[3] != "dark" or r[0] in TWINS:
            bad.append(F("G-BOARDS", f"board {r[0]}: a first board not in dark", "spec", sec))
    if {f.get("Board") for f in frames(t.spec)} != set(ids):
        bad.append(F("G-BOARDS", "a board draws no frame of §14.1", "spec", sec))
    status = t.spec.split("\n", 3)[2]
    if "Penpot boards of §0 are drawn in PR 2, which completes #243" not in status:  # lens 2 X29
        bad.append(
            F(
                "G-BOARDS",
                "the status line does not put the boards in PR 2",
                "spec",
                h2_at(t.spec, 3),
            )
        )
    body = norm_text(section(t.spec, "0. Status"))
    for n in (
        "each frame a",
        "window (`16`:212) holding one scr-030 panel",
        "illustrative values, not a market capture",
        "**specified (drawn on request)**",
        "the error-mapping table (§4) is a spec table, not a board.",
    ):
        if norm_text(n) not in body:
            bad.append(F("G-BOARDS", f"§0 lacks {n!r}", "spec", sec))
    return bad


def g_frame(t: Texts) -> list[Finding]:
    """BQ-6: the frame register, column by column; every twin draws its source's frames."""
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
        if (not copy and f.get("Copy") != "—") or any(c not in copy_ids for c in copy):
            bad.append(F("G-FRAME", f"{fid}: copy {copy} not all W-n of §11", "spec", sec))
        for tok in re.findall(r"`([a-z][a-z0-9.*-]+)`", f.get("Tokens", "")):
            if any(resolve(load_theme(th), tok) == "MISSING" for th in THEMES):
                bad.append(F("G-FRAME", f"{fid}: {tok} does not resolve", "spec", sec))
        if f.get("Status") != FRAME_STATUS:
            bad.append(F("G-FRAME", f"{fid}: status {f.get('Status')!r}", "spec", sec))
    drawn: dict[str, list[str]] = {}
    for f in frames(t.spec):
        drawn.setdefault(f.get("Board", ""), []).append(f["Frame"].rsplit(" · ", 1)[0])
    for bid, (_th, src) in TWINS.items():
        if bid in drawn and drawn[bid] != drawn.get(src, []):
            msg = f"board {bid} does not draw every frame of {src}"
            bad.append(F("G-FRAME", msg, "spec", sec))
    return bad


LOCKED_LEADS = ("D02", "`14`", "RF", "E11-D04", "E16-D05", "D06", "E08-D04", "D09")
# each locked row's first cite must sit on the line holding its fragment
LOCKED_FRAG = (
    "| D-1  |",
    "| State ",
    "## 4. Precedence rule",
    "SCR-151's anatomy",
    "**The deck grammar",
    "never hatched and never a band",
    "| State | Text token",
    "CMP-180..199 is full",
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
        rel = cite_path(cid)
        lines_ = (git_show(BASE, rel) or "").split("\n") if rel else []
        if not 1 <= n <= len(lines_):
            continue  # G-CITE owns a cite that is not a line at the base
        if frag not in lines_[n - 1]:
            bad.append(F("G-LOCKED", f"{lead}: {cid}:{n} is not where it says", "spec", sec))
    return bad


A_IDS = tuple(f"A-{n}" for n in range(1, 15))
# A-rows whose New carries a `new` deck string's slotted form: A-row -> its W-n
A_CARRY = {
    "A-6": ("W-7",),
    "A-7": ("W-34", "W-49"),
    "A-8": ("W-29", "W-30", "W-32", "W-46", "W-47", "W-48"),
    "A-12": ("W-40", "W-41", "W-42", "W-43", "W-44", "W-45"),
    "A-14": ("W-36",),
}


def a_rows(hand: str) -> dict[str, list[str]]:
    return {r[0]: r for r in table_rows(section(hand, "Table A")) if r[0].startswith("A-")}


def unescape(cell: str) -> str:
    return cell.replace("\\|", "|")


def g_arow(t: Texts) -> list[Finding]:
    """BQ-3: departures ship as copy-ready A-rows; each Old is a verbatim fragment of its cited
    line at the base; §B routes every row; the carried strings match the deck."""
    sec = h2_of(t.hand, "§C Copy-ready")
    rows = a_rows(t.hand)
    bad: list[Finding] = []
    if tuple(rows) != A_IDS:
        bad.append(F("G-AROW", f"Table A rows read {list(rows)}", "hand", sec))
    routed = norm_text(section(t.hand, "§B Who applies"))
    for x in ("A-1 … A-5, A-9", "A-6", "A-7, A-8", "A-10, A-14", "A-11", "A-12", "A-13"):
        if norm_text(f"| {x} |") not in routed:
            bad.append(F("G-AROW", f"§B does not route {x}", "hand", h2_of(t.hand, "§B")))
    silent = t.values.get("CITE:silent", "")
    dk = deck(t.spec)
    for aid, r in rows.items():
        if len(r) < 5:
            bad.append(F("G-AROW", f"{aid}: cells", "hand", sec))
            continue
        old, new = unescape(r[3]), unescape(r[4])
        refs = cite_refs(r[2])
        if not refs:
            bad.append(F("G-AROW", f"{aid}: no cite", "hand", sec))
            continue
        if old != "—":
            cid, n, _b = refs[0]
            if pin_norm(old) not in pin_norm(base_line(cid, n)):
                bad.append(F("G-AROW", f"{aid}: Old is not verbatim at {cid}:{n}", "hand", sec))
            if old == new:
                bad.append(F("G-AROW", f"{aid}: New equals Old", "hand", sec))
        want = f"`Cancel` on the strip from {silent} ms" if aid == "A-8" else f"from {silent} ms"
        if aid in ("A-5", "A-8", "A-10") and want not in new:  # A-8: lens 1 M4 (D09:117)
            bad.append(F("G-AROW", f"{aid}: New does not put Cancel at {silent} ms", "hand", sec))
        for wid in A_CARRY.get(aid, ()):
            ws = quoted_parts(dk.get(wid, "")) or [dk.get(wid, "")]
            if not all(shape(w) in shape(new) for w in ws):
                bad.append(F("G-AROW", f"{aid}: New does not carry {wid}", "hand", sec))
    return bad


HANDA_HEAD = "§A Hand-off checklist"


def g_handoff(t: Texts) -> list[Finding]:
    """`16` §11.4: every §A cell is ticked with its evidence or unticked with its reason; every
    `-handoff.md` reference names this hand-off or a file at the base; §F names the consumers."""
    sec = h2_of(t.hand, HANDA_HEAD)
    raw = section(t.hand, HANDA_HEAD)
    bad: list[Finding] = []
    if "Rule: every line is `[x]` with its evidence, or `[ ]` with the reason." not in raw:
        bad.append(F("G-HANDOFF", "§A lacks its rule line", "hand", sec))
    for r in table_rows(raw):
        for c in r[1:]:
            if not re.match(r"\[(?:x| )\] \S", c):
                msg = f"§A {r[0]}: a cell without tick and evidence"
                bad.append(F("G-HANDOFF", msg, "hand", sec))
    own = Path(HAND_REL).name
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            for m in re.finditer(r"([A-Za-z0-9_./-]*-handoff\.md)", strip_comments(line)):
                name = m[1]
                path = f"docs/design/E12/{name}" if "/" not in name else name
                if Path(name).name != own and git_show(BASE, path) is None:
                    msg = f"{doc}:{i} {name} is neither this hand-off nor a file at the base"
                    bad.append(F("G-HANDOFF", msg, doc, h2_at(text, i)))
    if f"[{own}]({own})" not in t.spec.split("\n", 3)[2]:
        bad.append(
            F("G-HANDOFF", "the spec's status line does not link the hand-off", "spec", "(top)")
        )
    fsec = h2_of(t.hand, "§F Consumer")
    consumers = " ".join(r[0] for r in table_rows(section(t.hand, "§F Consumer")))
    for c in CONSUMER_KEYS:
        if c not in consumers:
            bad.append(F("G-HANDOFF", f"§F names no row for {c}", "hand", fsec))
    return bad


g_handoff_words = lexicon(
    "G-HANDOFF",
    "a §A cell allowed blank",
    r"\b(?:blank|empty|unticked|unmarked)\b (?:\w+ ){0,2}?(?:is |are )?(?:acceptable|allowed|fine"
    r"|ok|permitted)\b|\b(?:left|leave|stay)s? (?:\w+ )?(?:blank|empty)\b",
    doc="hand",
)


def g_hidden(t: Texts) -> list[Finding]:
    """A `[//]: #` comment or any link-reference definition is text no reader sees."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        lines = text.split("\n")
        fence = fenced(lines)
        for i, line in enumerate(lines, 1):
            if not fence[i - 1] and re.match(r"^ {0,3}\[[^\]]*\]:\s*\S", line):
                msg = f"{doc}:{i} a hidden link-reference line ({line[:30]!r})"
                bad.append(F("G-HIDDEN", msg, doc, h2_at(text, i)))
    return bad


def g_newcmp(t: Texts) -> list[Finding]:
    """No new component: every CMP id is a catalogue entry at the base, or D09's CMP-248 named
    with D09; no sentence claims a new entry or a new component of this ticket's own."""
    cmps = set(re.findall(r"^### (CMP-\d{3})\b", plan("15"), MULTI))
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        skip = skip_lines(text, (MUTATION_HEAD,))
        for i, line in enumerate(text.split("\n"), 1):
            if line in skip:
                continue
            for c in set(re.findall(r"\bCMP-\d{3}\b", line)) - cmps:
                if c != "CMP-248" or "D09" not in line:
                    msg = f"{doc}:{i} {c} is not a catalogue entry at the base"
                    bad.append(F("G-NEWCMP", msg, doc, h2_at(text, i)))
    units = lex(t)
    term = (
        r"\b(?:a |one )?new (?:component|catalogue entry|cmp|entry)\b(?! for e12 d09)"
        r"|\b(?:adds?|introduces?|creates?|defines?) (?:a |one )?(?:new )?(?:component|cmp \d+)\b"
    )
    bad += as_findings("G-NEWCMP", "a new component", claims(units, term, unless=r"\bd09\b"))
    return bad


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


# ---- §3 SCR-047 (BQ-7, BQ-8, BQ-9, BQ-10)

REASON_FRAMES = (
    "`SCR-047/never-recorded-owner`",
    "`SCR-047/before-start`",
    "`SCR-047/interval-too-fine`",
    "`SCR-047/exchange-no-bars`",
    "`SCR-047/not-trading`",
)
REASON_ENUM = ("not_recorded", "no_data_in_range", "symbol_delisted")
SHARED_CAUSE = ("`SCR-047/never-recorded-owner`", "`SCR-047/before-start`")  # D08-C17


def w_of(cell: str) -> str:
    m = re.match(r"(W-\d+)", cell.strip())
    return m[1] if m else ""


def w_text(spec: str, wid: str) -> str:
    s = deck(spec).get(wid, "")
    return " ".join(quoted_parts(s)) or s


ALL_DISTINCT = (
    r"\b(?:each|every) heading and (?:each |every )?cause (?:are |is )?"
    r"(?:distinct|its own|unique)\b"
    r"|\bheadings? and causes? (?:are |all )?(?:distinct|unique|pairwise distinct)\b"
    r"|\b(?:every|each|all) causes? (?:are |is )?(?:distinct|unique|its own)\b(?! but| except)"
)


def g_reasons(t: Texts) -> list[Finding]:
    """BQ-7 (AC1): the five frames in order; headings pairwise distinct; causes pairwise distinct
    but for 1a and 1b, which share E16-D05's family cause (D08-C17); the enum kept at three."""
    sec = spec_sec(t, REASONS_HEAD)
    rows = reason_rows(t.spec)
    bad: list[Finding] = []
    if tuple(r[0] for r in rows) != REASON_FRAMES:
        bad.append(F("G-REASONS", f"§3.1 frames read {[r[0] for r in rows]}", "spec", sec))
    heads: dict[str, str] = {}
    causes: dict[str, str] = {}
    for r in rows:
        if len(r) < 7:
            bad.append(F("G-REASONS", f"{r[0]}: cells", "spec", sec))
            continue
        if r[3].strip("`") not in REASON_ENUM:
            bad.append(F("G-REASONS", f"{r[0]}: `reason` {r[3]} is not the enum's", "spec", sec))
        heads[r[0]] = shape(w_text(t.spec, w_of(r[4])))
        causes[r[0]] = shape(w_text(t.spec, w_of(r[5])))
    names = list(heads)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if heads[a] == heads[b] or not heads[a]:
                bad.append(F("G-REASONS", f"{a} and {b} share a heading", "spec", sec))
            same = causes[a] == causes[b]
            if (a, b) == SHARED_CAUSE:
                if not same:
                    bad.append(F("G-REASONS", "1a and 1b leave the family cause", "spec", sec))
            elif same or not causes[a]:
                bad.append(F("G-REASONS", f"{a} and {b} share a cause", "spec", sec))
    # D08-C17 stated the same way everywhere: no unit claims every cause distinct (lens 1 M2)
    bad += as_findings("G-REASONS", "every cause claimed distinct", claims(lex(t), ALL_DISTINCT))
    body = norm_text(section(t.spec, REASONS_HEAD))
    n = t.values.get("COUNT:reason.enum", "")
    if norm_text(f"The `reason` enum stays at {n}") not in body or n != str(len(REASON_ENUM)):
        bad.append(F("G-REASONS", "§3.1 does not keep the `reason` enum", "spec", sec))
    return bad


def g_enum(t: Texts) -> list[Finding]:
    """BQ-7, BQ-13: `reason` keeps its three values, `kind` its three; no fourth of either."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        skip = skip_lines(text, (MUTATION_HEAD,))
        for i, line in enumerate(text.split("\n"), 1):
            if line in skip:
                continue
            sec = h2_at(text, i)
            for m in re.finditer(r"`reason(?:: |` = |`: )`?\"?([a-z_]+)", line):
                if m[1] not in REASON_ENUM:
                    bad.append(F("G-ENUM", f"{doc}:{i} a `reason` value {m[1]}", doc, sec))
            for m in re.finditer(r"`kind: ([a-z-]+)`", line):
                if m[1] not in ("engine", "data-feed", "backend"):
                    bad.append(F("G-ENUM", f"{doc}:{i} a `kind` value {m[1]}", doc, sec))
    body = norm_text(section(t.spec, CLASSES_HEAD))
    if norm_text("`kind` stays `engine | data-feed | backend`") not in body:
        bad.append(F("G-ENUM", "§5.1 does not keep `kind`", "spec", spec_sec(t, CLASSES_HEAD)))
    term = r"\b(?:a )?(?:fourth|new|extra|additional) (?:`)?(?:kind|reason)\b(?: value)?"
    bad += as_findings("G-ENUM", "a fourth enum value", claims(lex(t), term))
    return bad


g_role_words = lexicon(
    "G-ROLE",
    "a gated CTA drawn for a non-owner, or a lock on the sentence form",
    r"\b(?:disabled|locked|greyed|grayed|dimmed|inactive) (?:record this symbol|cta|button)\b"
    r"|\brecord this symbol\b (?:\S+ ){0,3}?(?:for|to) (?:a |the )?(?:manager|viewer)s?\b"
    r"|\b(?:lock|padlock)(?: glyph)? (?:\S+ ){0,3}?(?:on|beside|before) (?:the )?sentence form\b"
    r"|\bhiding (?:\S+ ){0,3}?(?:secures|enforces|is the security)\b",
)


def g_role(t: Texts) -> list[Finding]:
    """BQ-8, S-10, R-7: the role legs, the sentence form, the server decides."""
    sec = spec_sec(t, "3.2 The role legs")
    body = norm_text(section(t.spec, "3.2 The role legs"))
    need = (
        "never a button, never a lock, never dimmed",
        "the view-as leg first",
        "**The server decides (R-7):**",
        "M-023 alternative",
    )
    return [F("G-ROLE", f"§3.2 lacks {n!r}", "spec", sec) for n in need if norm_text(n) not in body]


g_live_words = lexicon(
    "G-LIVE",
    "the live sentence under Stale",
    r"\b(?:shown|appears|reads|stays|kept|remains) (?:\S+ ){0,3}?(?:under|while|when) "
    r"(?:the feed is )?stale\b",
    heads=("3.3 The live-data", "3.1 The five", "10. Accessibility"),
)


def g_live(t: Texts) -> list[Finding]:
    sec = spec_sec(t, "3.3 The live-data")
    body = norm_text(section(t.spec, "3.3 The live-data"))
    need = ("E11-D04:351 verbatim", "omitted under Stale", "the words carry the meaning")
    return [F("G-LIVE", f"§3.3 lacks {n!r}", "spec", sec) for n in need if norm_text(n) not in body]


g_nogl_words = lexicon(
    "G-NOGL",
    "SCR-047 mounting a canvas or a GL context",
    r"(?:scr 047|the empty state|an empty chart)\b(?:\s+\S+){0,6}?\s+(?:mounts?|creates?"
    r"|initiali[sz]es?|draws? on|opens?|needs?) (?:a |the )?(?:<canvas>|canvas|gl|webgl)\b",
)


def g_nogl(t: Texts) -> list[Finding]:
    sec = spec_sec(t, "3.4 DOM")
    body = norm_text(section(t.spec, "3.4 DOM"))
    need = (
        "**no `<canvas>` mounted and no GL context created**",
        "a timeout is SCR-048 backend (E11-D04:353), never a longer wait (R-3)",  # lens 2 X09
    )
    return [F("G-NOGL", f"§3.4 lacks {n!r}", "spec", sec) for n in need if norm_text(n) not in body]


g_skeleton_words = lexicon(
    "G-SKELETON",
    "CMP-029 as a final state",
    r"\bcmp 029\b (?:\S+ ){0,6}?(?:stays|remains|is the final|as the final|after the reason"
    r"|in the empty state|as the empty state)\b",
)


def g_skeleton(t: Texts) -> list[Finding]:
    sec = spec_sec(t, "3.4 DOM")
    n = "CMP-029 appears only while the fetch decides the reason"
    if norm_text(n) not in norm_text(section(t.spec, "3.4 DOM")):
        return [F("G-SKELETON", f"§3.4 lacks {n!r}", "spec", sec)]
    return []


# ---- §4 the mapping table (BQ-11, BQ-12)

MAP_COLS = ("Signal", "Previous series?", "Destination", "Class / `reason`", "Copy source", "Retry")


def map_rows(spec: str) -> list[dict[str, str]]:
    return [dict(zip(MAP_COLS, r, strict=False)) for r in table_rows(section(spec, MAP_HEAD))]


def e11d04_sentences() -> str:
    """E11-D04 §12.1's data-feed and backend rows: the per-code sentences end in `(code)`."""
    return "\n".join(base_line("E11-D04", n) for n in (367, 368))


def copy_gaps(spec: str, codes: set[str], r: dict[str, str]) -> list[str]:
    """Lens 3 M2: every code of an SCR-048 row has words, either E11-D04's sentence for it (the
    cell citing E11-D04's line) or a W-n of the cell whose string names it or carries `{code}`;
    a bare "by code" claim covers nothing."""
    cell = r.get("Copy source", "")
    wids = re.findall(r"\bW-\d+\b", cell)
    ws = [w_text(spec, w) for w in wids]
    slot = any("{code}" in w for w in ws)
    cites = {n for _c, n, _b in cite_refs(cell) if _c == "E11-D04"} | {
        int(n) for n in re.findall(r"E11-D04:(\d+)'s sentence", cell)
    }
    src = e11d04_sentences() if cites & {367, 368} else ""
    out = []
    for c in sorted(codes - NON_REGISTRY):
        if f"({c})" in src or slot or any(f"({c})" in w for w in ws):
            continue
        out.append(f"`{c}` on SCR-048 has no words (an E11-D04 sentence or a W-n)")
    return out


def g_map(t: Texts) -> list[Finding]:
    """BQ-11: every reachable code has a row; every row's code is in a registry; every declared
    `getBars` status is met; the 422 and the empty `200` readings; never SCR-048 for a 422."""
    sec = spec_sec(t, MAP_HEAD)
    rows = map_rows(t.spec)
    bad: list[Finding] = []
    mapped: set[str] = set()
    statuses: set[int] = set()
    for r in rows:
        sig = r.get("Signal", "")
        codes = set(re.findall(r"`([a-z_]+)`", sig))
        mapped |= codes
        statuses |= {int(x) for x in re.findall(r"\b([45]\d\d)\b", sig)}
        for c in codes - registry() - NON_REGISTRY:
            bad.append(F("G-MAP", f"`{c}` is in neither registry", "spec", sec))
        dest = norm_text(r.get("Destination", ""))
        if "no_data_recorded" in codes and "scr 048" in dest:
            bad.append(F("G-MAP", "a 422 `no_data_recorded` routed to SCR-048", "spec", sec))
        if "straddling" in sig and not ("never scr 047" in dest and "boundary" in dest):
            bad.append(F("G-MAP", "a straddling 422 is not the boundary", "spec", sec))
        if "wholly before" in sig and "scr 047 before start" not in dest:
            bad.append(F("G-MAP", "a wholly-before 422 is not SCR-047 before-start", "spec", sec))
        if "zero rows, non-time" in sig and not ("never scr 047" in dest and "f bar 3" in dest):
            bad.append(F("G-MAP", "an empty non-time `200` is not the build", "spec", sec))
        if "zero rows, time bars" in sig and "scr 047 exchange no bars" not in dest:
            bad.append(F("G-MAP", "an empty time `200` is not exchange-no-bars", "spec", sec))
        if r.get("Previous series?") == "yes" and not ("inline" in dest and "kept" in dest):
            bad.append(F("G-MAP", "a failure with a previous series is not inline", "spec", sec))
        if "scr 048" in dest:
            bad += [F("G-MAP", m, "spec", sec) for m in copy_gaps(t.spec, codes, r)]
    for c in sorted(reachable_codes() - mapped):  # derived: lens 1 M5, lens 3 M1
        bad.append(F("G-MAP", f"`{c}` is unmapped (T Test: a blocking finding)", "spec", sec))
    for s in getbars_statuses():
        if s not in statuses:
            bad.append(F("G-MAP", f"`getBars`' declared {s} has no row", "spec", sec))
    return bad


# ---- §5 SCR-048 (BQ-13, BQ-15, BQ-16)

CLASS_LEADS = ("data-feed / bootstrap", "recompute", "context loss")
CLASS_HEADS = ("W-17", "W-19", "W-20", "W-23")  # the four card headings, pairwise distinct


def g_classes(t: Texts) -> list[Finding]:
    """BQ-13: three classes in order on E11-D04's card; the headings pairwise distinct; the
    recompute heading `new`, PROPOSED; WebGL2 unavailable cited, not redrawn."""
    sec = spec_sec(t, CLASSES_HEAD)
    rows = class_rows(t.spec)
    bad: list[Finding] = []
    if tuple(r[0] for r in rows) != CLASS_LEADS:
        bad.append(F("G-CLASSES", f"§5.1 classes read {[r[0] for r in rows]}", "spec", sec))
    heads = {w: shape(w_text(t.spec, w)) for w in CLASS_HEADS}
    for i, a in enumerate(CLASS_HEADS):
        for b in CLASS_HEADS[i + 1 :]:
            if heads[a] == heads[b] or not heads[a]:
                for s_ in (sec, spec_sec(t, DECK_HEAD)):  # the headings live in the deck
                    bad.append(F("G-CLASSES", f"{a} and {b} share a heading", "spec", s_))
    by = {r[0]: r for r in rows}
    rc = by.get("recompute", [])
    if len(rc) < 3 or "**new**, PROPOSED" not in rc[2]:
        bad.append(F("G-CLASSES", "the recompute heading is not new, PROPOSED", "spec", sec))
    body = norm_text(section(t.spec, CLASSES_HEAD))
    for n in ("WebGL2 unavailable keeps E11-D04's own card", "cited and not redrawn"):
        if norm_text(n) not in body:
            bad.append(F("G-CLASSES", f"§5.1 lacks {n!r}", "spec", sec))
    return bad


REF_ORDER = ("`Problem.instance`", "`X-Correlation-Id`", "`request_id`", "`urn:cv:ui:{uuid4}`")
g_ref_words = lexicon(
    "G-REF",
    "a reference built from data",
    r"\b(?:reference|correlation id|ref|id)\b (?:\S+ ){0,6}?(?:built|derived|made|composed|formed"
    r"|hashed|encoded) (?:from|of|with|by) (?:the )?(?:symbol|account|session|user|token|name)",
)


def g_ref(t: Texts) -> list[Finding]:
    """BQ-15, R-5: the source order; opaque by construction; never internal detail."""
    sec = spec_sec(t, "5.2 The reference")
    raw = section(t.spec, "5.2 The reference")
    pos = [raw.find(x) for x in REF_ORDER]
    bad: list[Finding] = []
    if -1 in pos or pos != sorted(pos):
        bad.append(F("G-REF", "§5.2's source order", "spec", sec))
    for n in (
        (
            "**The id is opaque by construction:** no account id, symbol, session token or user"
            " identity"
        ),
        "Never on the card",
    ):  # lens 2 X11: the opaque sentence whole
        if n not in raw:
            bad.append(F("G-REF", f"§5.2 lacks {n!r}", "spec", sec))
    return bad


LEAK = re.compile(
    r"ret_msg|\bsql\b|\bselect\b.*\bfrom\b|stack|exception|traceback|hostname|\.py\b|\.local\b"
    r"|questdb|postgres|parquet|\b\d{1,3}(?:\.\d{1,3}){3}\b|https?:|\bnull\b|\bundefined\b",
    re.IGNORECASE,
)


def g_leak(t: Texts) -> list[Finding]:
    """T Sec: no copy string shows internal detail (a host, a URL, SQL, a store, `ret_msg`)."""
    sec = spec_sec(t, DECK_HEAD)
    bad: list[Finding] = []
    for w, s in deck(t.spec).items():
        hit = LEAK.search(" ".join(quoted_parts(s)) or s)
        if hit:
            bad.append(F("G-LEAK", f"{w}: internal detail {hit[0]!r}", "spec", sec))
    return bad


def g_workspace(t: Texts) -> list[Finding]:
    """BQ-16 (AC5): one panel; the rest live; no stop-loss claim; diagnostics owner-only."""
    sec = spec_sec(t, "5.3 The rest")
    body = norm_text(section(t.spec, "5.3 The rest"))
    need = (
        "lives in one panel's pane-stack region",
        "board 04 draws a live neighbour panel",
        "The card claims nothing about stop-losses",
        "`Open diagnostics` (SCR-046) is owner-only",
    )
    return [
        F("G-WORKSPACE", f"§5.3 lacks {n!r}", "spec", sec) for n in need if norm_text(n) not in body
    ]


# ---- §6 the ladder (BQ-14)

g_ladder_words = lexicon(
    "G-LADDER",
    "a retry without a stop, or a 4xx retried, or the shorter wait",
    r"\bkeeps? (?:on )?retrying\b|\bretr(?:y|ies) (?:until|till) (?:it )?succeed\w*"
    r"|\bretr(?:y|ies|ying)\b (?:\S+ ){0,3}?(?:forever|indefinitely|endlessly|without (?:a |any )?"
    r"(?:limit|stop|end|cap))\b|\binfinite (?:spinner|retr\w+|loop)\b|\bshorter of\b"
    r"|\b(?:minimum|min) of the (?:ladder|step)\b|\bretr(?:y|ies)\b (?:a |every |any |each )?4xx\b"
    r" automatically\b|\b4xx\b (?:is |are )?retr(?:y|ies|ied) automatically\b"
    r"|\bcountdown (?:\S+ ){0,3}?(?:while|when|under) (?:the transport is )?disconnected\b",
)


def g_ladder(t: Texts) -> list[Finding]:
    """BQ-14: the ladder, its stops, `Retry-After`, the stop sentence, the countdown."""
    sec = spec_sec(t, "6. The retry")
    body = norm_text(section(t.spec, "6. The retry"))
    need = (
        "truncated by E11-D04's stops",
        "**No automatic retry on a 4xx**",
        "except a 429, which follows the ladder",
        "the longer of the ladder step and the server's `retry_after_seconds`",
        "(**new**, PROPOSED)",
        'W-25 "Automatic retries stopped"',
        '`aria-live="off"`',
        "no countdown of its own",
        "O-9 carried",
        "so §4 splits them by code (PROPOSED; D08-C20)",
    )
    bad = [F("G-LADDER", f"§6 lacks {n!r}", "spec", sec) for n in need if norm_text(n) not in body]
    cap = t.values.get("CITE:ladder.cap", "")
    if f"capped at {cap}<!--=CITE:ladder.cap--> s (**new**, PROPOSED)" not in section(
        t.spec, "6. The retry"
    ):  # the `Retry-After` cap bound to its own key (lens 2 X15)
        bad.append(F("G-LADDER", "§6's `Retry-After` cap is not CITE:ladder.cap", "spec", sec))
    r3 = '**R-3 No infinite spinner.** Every wait states a bound, a next attempt time or "Automatic'
    if r3 not in section(t.spec, "1.4 Rules"):  # lens 2 X04
        bad.append(
            F("G-LADDER", "§1.4 lacks R-3's every-wait sentence", "spec", spec_sec(t, "1.4"))
        )
    return bad


# ---- §7 the rebuild (BQ-19, BQ-20, BQ-21, BQ-25)

g_progress_words = lexicon(
    "G-PROGRESS",
    "a fake percentage or an indeterminate loop",
    r"\bpercentage (?:\S+ ){0,2}?(?:from|based on|derived from) (?:the )?(?:estimate|elapsed|"
    r"pre commit)\b|\bindeterminate (?:loop|spinner|bar|progress bar)\b|\bfake percentage\b"
    r"|\b(?:a |the )?time left (?:\S+ ){0,3}?(?:when|while) (?:the )?total is "
    r"(?:unknown|not known)"
    r"|\belapsed (?:counter |time )?(?:\S+ ){0,4}?(?:inside|within|in) (?:cmp 038's |the |its )?"
    r"(?:status |live )?region\b|\belapsed (?:counter |time )?(?:is |are )?(?:announced|spoken)\b",
    unless=r"\bnever\b",
)


def g_progress(t: Texts) -> list[Finding]:
    """BQ-19: determinate only with G-1's done and total; the total-unknown phase shows elapsed
    time, never a percentage or a time left; the boards mark the determinate phase."""
    sec = spec_sec(t, "7.1 Phases")
    raw = section(t.spec, "7.1 Phases")
    rows = {r[0]: r for r in table_rows(raw)}
    bad: list[Finding] = []
    det = rows.get("determinate", [])
    if len(det) < 2 or "only while G-1's progress frame carries both done and total" not in det[1]:
        bad.append(F("G-PROGRESS", "the determinate phase is not G-1-bound", "spec", sec))
    unk = rows.get("total unknown", [])
    if len(unk) < 3 or "never a percentage or a time left" not in unk[2]:
        bad.append(F("G-PROGRESS", "the total-unknown phase allows a percentage", "spec", sec))
    for wid in ("W-29", "W-46"):  # the total-unknown phase and its overrun (lens 1 M3, lens 3 M4)
        w = w_text(t.spec, wid)
        if "%" in w or re.search(r"\bleft\b", w) or "elapsed" not in w:
            bad.append(F("G-PROGRESS", f"{wid} shows a percentage or a time left", "spec", sec))
    for r in table_rows(raw):
        comp = r[3] if len(r) > 3 else ""
        if " or " in comp:
            bad.append(F("G-PROGRESS", f"{r[0]}: the component is left open", "spec", sec))
        if "CMP-038" in comp:
            for wid in re.findall(r"\bW-\d+\b", r[2] if len(r) > 2 else ""):
                if "%" in w_text(t.spec, wid):
                    msg = f"{r[0]}: {wid} puts a percentage in CMP-038 text"
                    bad.append(F("G-PROGRESS", msg, "spec", sec))
    if rows.get("over budget, total known", ["", "", "", ""])[3:4] != ["CMP-023"] or not rows.get(
        "over budget, total unknown", ["", "", "", ""]
    )[3].startswith("CMP-038"):
        bad.append(F("G-PROGRESS", "the overrun is not split by the total", "spec", sec))
    for n in (
        '"needs G-1"',
        "is a fake percentage and is never shown",
        'outside that status region, `aria-live="off"`',
        "A-13 asks CMP-038's owner",
    ):
        if n not in raw:
            bad.append(F("G-PROGRESS", f"§7.1 lacks {n!r}", "spec", sec))
    return bad


g_cadence_words = lexicon(
    "G-CADENCE",
    "progress redrawn per frame or per tick",
    r"\b(?:update|refresh|redraw|repaint|announce)\w* (?:\S+ ){0,4}?(?:every frame|per frame"
    r"|continuously|each frame|per tick|every tick|on every print)\b",
)


def g_cadence(t: Texts) -> list[Finding]:
    """T Perf: the progress cadence is the computed one, inside both caps."""
    sec = spec_sec(t, "7.2 Cadence")
    body = section(t.spec, "7.2 Cadence")
    v = t.values
    rf, cap = v.get("CITE:cadence.rf", "0"), v.get("CITE:cadence.t", "0")
    bad: list[Finding] = []
    if f"update at {rf}<!--=CITE:cadence.rf--> Hz" not in body or int(rf) > int(cap):
        bad.append(F("G-CADENCE", "§7.2's cadence is not the computed one", "spec", sec))
    if "no animation carries meaning" not in body:
        bad.append(F("G-CADENCE", "§7.2 lacks the reduced-motion rule", "spec", sec))
    if "one polite announcement at the crossing, W-48, none after" not in body:
        bad.append(F("G-CADENCE", "§7.2 lacks the overrun's one announcement", "spec", sec))
    for n in ("no automatic cancel", "its stall bound is part of D08-G1 (R-3)"):
        if n not in body:
            bad.append(F("G-CADENCE", f"§7.2 lacks {n!r}", "spec", sec))
    return bad


g_cancel_words = lexicon(
    "G-CANCEL",
    "Cancel later than the strip's first line, or CMP-038's Cancel",
    r"\bcancel\b(?:\s+\S+){0,5}?\s+(?:only\s+)?(?:after|from|past|once|beyond)\s+(?:2|two|5|five)"
    r"\s*s\b|\bcancel\b (?:\S+ ){0,3}?(?:is|as|from|uses|on|through) (?:a |the )?cmp 038(?:'s)?\b"
    r"|\bno cancel (?:\S+ ){0,2}?(?:needed|shown)\b"
    r"|\bcancel\b (?:\S+ ){0,4}?(?:appears|shows|is shown)"
    r" (?:only )?(?:once|when|after) (?:the )?determinate\b",
    unless=r"\bd 5\b|\bd02\b|\brf\b|\bcmp 038 allows\b|\bnever cmp 038\b|\b2 s when the total\b",
)


def g_cancel(t: Texts) -> list[Finding]:
    """BQ-21 (AC2): `Cancel` on the strip from its first line, `Esc` from 0 ms, the D-5
    amendment as a C-row and A-rows, never CMP-038's."""
    sec = spec_sec(t, "7.3 `Cancel`")
    body = section(t.spec, "7.3 `Cancel`")
    v = t.values
    need = (
        f"from the moment the strip appears ({v.get('CITE:silent')}<!--=CITE:silent--> ms)",
        f"`Esc` cancels from {v.get('RULED:esc.ms')}<!--=RULED:esc.ms--> ms",
        "This amends D-5 by one clause",
        "`Cancel` is never CMP-038's",
        "D08-C8, with A-5 to D02 and `14`:736, and A-8 to D09's pattern",
        f"Cancel takes effect within {v.get('CITE:cancel.s')}<!--=CITE:cancel.s--> s (D02:370).",
    )
    return [F("G-CANCEL", f"§7.3 lacks {n[:40]!r}", "spec", sec) for n in need if n not in body]


g_focus_words = lexicon(
    "G-FOCUS",
    "focus moved by a state or returned to the trigger",
    r"\bfocus (?:\S+ ){0,2}?(?:returns|moves|goes|jumps|is moved|is returned) to (?:the )?"
    r"(?:control|trigger|field|editor|pill|button) that (?:started|triggered|began)\b"
    r"|\b(?:completion|cancel|the result|(?:the|a|an) (?:\w+ )?state|the card|the alert)"
    r" (?:(?!never |not |no )\S+ ){0,2}?(?:moves?|takes?|steals?|grabs?) (?:the )?focus\b",
    unless=r"\bonly from a pressed\b",
)


def g_focus(t: Texts) -> list[Finding]:
    sec = spec_sec(t, "7.4 The restore")
    body = norm_text(section(t.spec, "7.4 The restore"))
    need = ("D-11 and F-BAR-3 stand", "routed to #530")
    return [
        F("G-FOCUS", f"§7.4 lacks {n!r}", "spec", sec) for n in need if norm_text(n) not in body
    ]


def g_restore(t: Texts) -> list[Finding]:
    """BQ-21 (AC2): the restore from screen, the outcome notice, no timer, `Esc` never."""
    sec = spec_sec(t, "7.4 The restore")
    body = norm_text(section(t.spec, "7.4 The restore"))
    need = (
        "the previous series is already on screen: no refetch, no empty frame",
        "no partial series is shown",
        "it has no timer and `Esc` never dismisses it",
        "drawings keep their timestamps",
    )
    return [
        F("G-RESTORE", f"§7.4 lacks {n!r}", "spec", sec) for n in need if norm_text(n) not in body
    ]


g_rbac_words = lexicon(
    "G-RBAC",
    "anyone may cancel a build",
    r"\b(?:any|every|each) (?:role|user|principal|viewer|manager|session)\b (?:\S+ ){0,3}?"
    r"(?:may|can|is able to) cancel\b|\bcancel\b (?:\S+ ){0,3}?(?:for|by) (?:any|every|each)"
    r" (?:role|user|principal)\b",
)


def g_rbac(t: Texts) -> list[Finding]:
    sec = spec_sec(t, "7.5 Who may")
    n = "Only the requesting principal or the Owner may cancel (ADR33:158)"
    if n not in section(t.spec, "7.5 Who may"):
        return [F("G-RBAC", f"§7.5 lacks {n[:40]!r}", "spec", sec)]
    return []


# ---- R-1 never approximate (BQ-28)

APPROX = (
    r"\bapproximat\w*|\bestimat\w* (?:the )?(?:bars|series|missing)\b|\bfill\w* (?:in )?"
    r"(?:\S+ ){0,2}?(?:from|with) (?:rest )?klines\b"
    r"|\bbuild\w* (?:non time )?bars from (?:klines|estimates)"
    r"|\bsynthes\w+|\binterpolat\w+|\bkline (?:fallback|substitut\w+)\b|\bsubstitut\w+ (?:rest )?"
    r"klines\b|\bbest guess\b|\bclose enough\b"
)
g_approx_words = lexicon("G-APPROX", "an approximate-it-anyway path", APPROX)


def g_approx(t: Texts) -> list[Finding]:
    """BQ-28: no action label and no copy string offers to approximate; R-1 stated once."""
    bad: list[Finding] = []
    labels: list[tuple[str, str, str]] = []
    for r in reason_rows(t.spec):
        labels += [(x, "spec", spec_sec(t, REASONS_HEAD)) for x in re.findall(r"`([^`]+)`", r[-1])]
    for s in deck(t.spec).values():
        labels.append((s, "spec", spec_sec(t, DECK_HEAD)))
    for x, doc, sec in labels:
        if re.search(APPROX, norm_text(x)):
            bad.append(F("G-APPROX", f"{x[:40]!r} offers to approximate", doc, sec))
    r1 = norm_text(section(t.spec, "1.4 Rules"))
    if norm_text("**R-1 Never approximate.**") not in r1:
        bad.append(F("G-APPROX", "§1.4 lacks R-1", "spec", spec_sec(t, "1.4 Rules")))
    return bad


# ---- §8 partial history (BQ-17, BQ-18)

g_boundary_words = lexicon(
    "G-BOUNDARY",
    "a hatched or banded boundary",
    r"\bboundar(?:y|ies)\b (?:is |are |becomes )?(?:drawn |shown )?(?:as )?(?:a )?(?:hatched|shaded"
    r"|tinted|band|filled|region)\b|\bhatch\w* (?:the )?(?:region )?(?:before|left of) (?:the )?"
    r"(?:boundary|recording start)\b",
)


def g_marker(t: Texts) -> list[Finding]:
    """BQ-17 (AC3): the dashed line with its tag; the timestamp as text; never announced; the
    difference from a gap stated."""
    bad: list[Finding] = []
    for head, need in (
        (
            "8.1 The boundary",
            (
                "A dashed full-height boundary",
                "the timestamp is text in the tag",
                "it is never announced",
                "Drawn at its pixel column under LOD",
            ),
        ),
        ("8.3 The difference", ("never hatched, never a band", "one line at one instant")),
    ):
        body = norm_text(section(t.spec, head))
        bad += [
            F("G-BOUNDARY", f"§{head[:3]} lacks {n!r}", "spec", spec_sec(t, head))
            for n in need
            if norm_text(n) not in body
        ]
    # the hand-off's own statements of the same rules (lens 2 H02, H04)
    hsum = section(t.hand, "§H Summary")
    if "a dashed line with a timestamp tag, never a band" not in hsum:
        bad.append(
            F("G-BOUNDARY", "§H does not keep the boundary off a band", "hand", h2_of(t.hand, "§H"))
        )
    live_row = next((r for r in table_rows(section(t.hand, HANDA_HEAD)) if r[0] == "Live data"), [])
    if live_row[4:5] != ["[x] none: never announced"]:
        msg = "§A says the boundary is announced"
        bad.append(F("G-BOUNDARY", msg, "hand", h2_of(t.hand, HANDA_HEAD)))
    return bad


EDGE_ENTER = (
    r"\b(?:the )?(?:tag|note) (?:itself )?pans\b|\benter on the (?:tag|note)\b"
    r"|\bactivating (?:the )?(?:tag|note)\b|\b(?:tag|note) (?:is|as) (?:a |the )?(?:button|link)\b"
)


def g_edge(t: Texts) -> list[Finding]:
    """BQ-18: the edge tag at the left edge in the loading band's slot, its words, its action,
    its yield; the finding "not verifiable at the base"; its catalogue home an A-row."""
    sec = spec_sec(t, "8.2 The off-screen")
    body = norm_text(section(t.spec, "8.2 The off-screen"))
    need = (
        "a text tag pinned at the plot's left edge, in the slot E11-D02 gives the loading band",
        "reads W-34 (**new**, PROPOSED)",
        "never the only carrier",
        "pans to the boundary",
        "It yields to the loading band while a page loads",
        "**Not verifiable at the base:**",
        "The tag's catalogue home is A-7",
        "D08-Q2",
        'the text is a `role="note"` and the action a `button` named W-49',  # lens 3 M5
    )
    bad = [
        F("G-EDGE", f"§8.2 lacks {n[:40]!r}", "spec", sec) for n in need if norm_text(n) not in body
    ]
    w = w_text(t.spec, "W-34")
    if "off-view" not in w or "←" not in w:
        bad.append(F("G-EDGE", "W-34 is not the ruled edge tag", "spec", spec_sec(t, DECK_HEAD)))
    bad += as_findings("G-EDGE", "the note activated", claims(lex(t), EDGE_ENTER))
    return bad


# ---- §9 the matrix (BQ-22, BQ-23, AC4)


@functools.lru_cache(maxsize=1)
def matrix_14() -> dict[str, tuple[str, int]]:
    """`14`'s pair table (`14`:746-758): the pair cell -> (wins cell, line)."""
    out: dict[str, tuple[str, int]] = {}
    for n in range(746, 759):
        ln = base_line("14", n)
        if ln.startswith("|") and not is_rule(ln):
            c = split_row(ln)
            if len(c) >= 3 and c[0] != "Pair":
                out[pin_norm(c[0])] = (pin_norm(c[1]), n)
    return out


def g_matrix(t: Texts) -> list[Finding]:
    """BQ-22: every pair row equals `14`'s pair and winner and cites its own line, and every pair
    of `14`:746-758 has its row, in `14`'s order; the never together pairs stand on `14`:761;
    disconnected cancels the build (`14`:762)."""
    sec = spec_sec(t, MATRIX_HEAD)
    bad: list[Finding] = []
    m14 = matrix_14()
    for r in matrix_rows(t.spec):
        if r[0] == FOURWAY:
            continue
        got = m14.get(pin_norm(r[0]))
        if got is None:
            bad.append(F("G-MATRIX", f"{r[0][:40]!r} is not a pair of `14`:746-758", "spec", sec))
            continue
        wins, line = got
        if len(r) < 3 or pin_norm(r[1]) != wins:
            bad.append(
                F("G-MATRIX", f"{r[0][:30]!r}: wins {r[1]!r}, `14` says {wins!r}", "spec", sec)
            )
        elif f"`14`:{line})" not in r[2]:
            bad.append(F("G-MATRIX", f"{r[0][:30]!r} does not cite `14`:{line}", "spec", sec))
    got_rows = [pin_norm(r[0]) for r in matrix_rows(t.spec) if r[0] != FOURWAY]
    for pair, (_w, line) in m14.items():  # both ways: every pair of `14` is here (lens 1 M1)
        if pair not in got_rows:
            bad.append(F("G-MATRIX", f"`14`:{line}'s pair {pair[:40]!r} is missing", "spec", sec))
    if [p_ for p_ in got_rows if p_ in m14] != [p_ for p_ in m14 if p_ in got_rows]:
        bad.append(F("G-MATRIX", "the pair rows are not in `14`'s order", "spec", sec))
    raw = section(t.spec, MATRIX_HEAD)
    l761, l762 = base_line("14", 761), base_line("14", 762)
    for pair, src in (
        ("rebuilding and error", "progressive-backfill or rebuilding and error"),
        ("empty and error (error wins)", "empty and error (error wins"),
    ):
        if pair not in raw or src not in l761:
            bad.append(F("G-MATRIX", f"never together: {pair!r} vs `14`:761", "spec", sec))
    if (
        "Disconnected cancels the build (`14`:762)" not in raw
        or "is cancelled by the disconnect" not in l762
    ):
        bad.append(F("G-MATRIX", "disconnected and rebuilding vs `14`:762", "spec", sec))
    return bad


g_primary_words = lexicon(
    "G-PRIMARY",
    "two primaries or a stacked strip",
    r"\b(?:two|both|several|multiple) (?:primar\w+|strip lines|lines in the strip)\b"
    r"|\bboth (?:\S+ ){0,2}?(?:are|is) primary\b|\bstrip stacks\b"
    r"|\bstack\w* (?:\S+ ){0,2}?strip\b"
    r"|\bstrip (?:\S+ ){0,3}?(?:shows|holds) (?:two|both|several)\b",
    heads=("9.1 The matrix", "9.2 E08", "1.4 Rules"),
)


def g_primary(t: Texts) -> list[Finding]:
    """AC4: the four-way row has one primary, rebuilding, and each other state in its slot."""
    sec = spec_sec(t, MATRIX_HEAD)
    row = next((r for r in matrix_rows(t.spec) if r[0] == FOURWAY), None)
    if row is None or len(row) < 3:
        return [F("G-PRIMARY", "§9.1 has no four-way row", "spec", sec)]
    bad: list[Finding] = []
    if row[1] != "rebuilding (strip)":
        bad.append(F("G-PRIMARY", f"the four-way row's primary reads {row[1]!r}", "spec", sec))
    for n in ("partial history:", "stale:", "LOD:", "never hidden"):
        if n not in row[2]:
            bad.append(F("G-PRIMARY", f"the four-way row lacks {n!r}", "spec", sec))
    return bad


g_vocab_words = lexicon(
    "G-VOCAB",
    "a new data-confidence state",
    r"\b(?:series paused|paused series|frozen series|quarantined state|data paused"
    r"|stale series state|rebuilding state chip|history state chip|partial state chip)\b"
    r"|\bnew (?:data confidence )?(?:state|chip word)\b (?:\S+ ){0,3}?(?:for|named|called)\b",
)


def g_vocab(t: Texts) -> list[Finding]:
    """BQ-9, BQ-23, R-4: E08's vocabulary consumed unchanged, and confirmed in words."""
    sec = spec_sec(t, "9.2 E08")
    body = norm_text(section(t.spec, "9.2 E08"))
    need = (
        "E12 adds no data-confidence state",
        (
            "**The confirmation T DoD asks for:** the stale and reconnecting vocabulary is"
            " consumed from E08-D04 and E11-D02 §10 unchanged"
        ),
    )
    bad = [
        F("G-VOCAB", f"§9.2 lacks {n[:40]!r}", "spec", sec)
        for n in need
        if norm_text(n) not in body
    ]
    if norm_text("no new state, no new words") not in norm_text(
        section(t.spec, "9.3 The quarantined")
    ):
        bad.append(F("G-VOCAB", "§9.3 gives the quarantine a state", "spec", spec_sec(t, "9.3")))
    return bad


# ---- §11 the deck, §12 tokens and contrast

DECK_SRC = re.compile(
    r"^(?P<cid>`\d\d`|[A-Z][A-Z0-9-]*?)(?::(?P<n>\d+))? (?P<how>verbatim|form)$"
    r"|^\*\*new\*\*, PROPOSED; (?P<arow>A-\d+)$"
)


def g_deck(t: Texts) -> list[Finding]:
    """R-6 (BQ-4): a verbatim string is on its cited line at the base, a form shares the cited
    string's shape, a `new` one is PROPOSED with its A-row."""
    sec = spec_sec(t, DECK_HEAD)
    rows = deck_rows(t.spec)
    arows = a_rows(t.hand)
    bad: list[Finding] = []
    ids = list(rows)
    if ids != [f"W-{n}" for n in range(1, len(ids) + 1)]:
        bad.append(F("G-DECK", f"the deck's ids read {ids[:3]}…", "spec", sec))
    for wid, r in rows.items():
        if len(r) < 4:
            bad.append(F("G-DECK", f"{wid}: cells", "spec", sec))
            continue
        m = DECK_SRC.match(r[3])
        if not m:
            bad.append(F("G-DECK", f"{wid}: source {r[3]!r}", "spec", sec))
            continue
        parts = quoted_parts(r[1]) or [r[1]]
        if m["arow"]:
            if m["arow"] not in arows:
                bad.append(F("G-DECK", f"{wid}: {m['arow']} is not in Table A", "spec", sec))
            continue
        cid = m["cid"].strip("`")
        line = base_line(cid, int(m["n"] or 0)) if m["n"] else ""
        quotes = [q[1:-1] for q in QUOTED.findall(line)] + [line]
        for p in parts:
            if m["how"] == "verbatim" and loose(p) not in loose(line):
                bad.append(
                    F("G-DECK", f"{wid}: {p[:30]!r} is not verbatim at {cid}:{m['n']}", "spec", sec)
                )
            if m["how"] == "form" and not any(shape(p).rstrip(".") in shape(q) for q in quotes):
                bad.append(
                    F("G-DECK", f"{wid}: {p[:30]!r} is not a form at {cid}:{m['n']}", "spec", sec)
                )
    return bad


TOKEN_NAME = re.compile(
    r"`((?:color|space|radius|opacity|elevation|size|type|border|motion|pattern)\.[a-z0-9.*-]+)`"
)


def g_tokens(t: Texts) -> list[Finding]:
    """BQ-27: every token resolves, or is a routed name standing beside "PROPOSED"."""
    names = all_token_names()
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        skip = skip_lines(text, ("Table A", "15.1 Contradictions", MUTATION_HEAD))
        for i, line in enumerate(text.split("\n"), 1):
            if line in skip:
                continue
            for name in TOKEN_NAME.findall(line):
                star = name.endswith(".*") and any(n.startswith(name[:-1]) for n in names)
                if name in names or star:
                    continue
                if name in NOT_SHIPPED and "PROPOSED" in line:
                    continue
                bad.append(F("G-TOKENS", f"{doc}:{i} {name} is unbound", doc, h2_at(text, i)))
    if "no new token" not in norm_text(section(t.spec, PAIRS_HEAD)):
        bad.append(F("G-TOKENS", "§12 lacks 'no new token'", "spec", spec_sec(t, PAIRS_HEAD)))
    return bad


def g_contrast(t: Texts) -> list[Finding]:
    """BQ-27: §12 lists every pair once with its bar; each clears it in all three themes."""
    sec = spec_sec(t, PAIRS_HEAD)
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


# the one allowed CVD exception: the pair -> the words §12 must state it with (CMP-023's value
# text is always shown, `15`:275, so the fill is never the only carrier)
CVD_EXEMPT = {"fill-track": "except the progress fill on its track"}


def g_cvd(t: Texts) -> list[Finding]:
    """BQ-27: the CVD constants are the research script's; every simulated mark pair clears the
    mark bar in every theme, but the one exception §12 states with its reason."""
    sec = spec_sec(t, PAIRS_HEAD)
    bad = [F("G-CVD", m, "spec", sec) for m in cvd_src_problems()]
    bar = mark_min()
    body = section(t.spec, PAIRS_HEAD)
    for (th, k, s), r in sorted(cvd_grid().items()):
        if Decimal(str(math.floor(r * 100) / 100)) >= bar:
            continue
        if k in CVD_EXEMPT and CVD_EXEMPT[k] in body and "(`15`:275)" in body:
            continue
        bad.append(F("G-CVD", f"{k} {th} under {s} is {show_ratio(r)}", "spec", sec))
    if f"`{CVD_SRC}`" not in section(t.spec, PAIRS_HEAD):
        bad.append(F("G-CVD", "§12 does not name the CVD script", "spec", sec))
    return bad


# ---- §15 the rows

C_ROWS = {
    "D08-C1": "T Tech's line mapping `no_data_recorded`",
    "D08-C2": "an empty successful response",
    "D08-C3": "four reasons",
    "D08-C4": "three SCR-048 classes",
    "D08-C5": "CMP-029",
    "D08-C6": "CMP-069",
    "D08-C7": "M-023",
    "D08-C8": "AC2's `Cancel`",
    "D08-C9": "E12-Q07's",
    "D08-C10": "Shorten the window",
    "D08-C11": "RF §8",
    "D08-C12": "corner badge",
    "D08-C13": "Stale 4s",
    "D08-C14": "R7 Data accuracy",
    "D08-C15": "`14`:716",
    "D08-C16": "T DoD's",
    "D08-C17": "`empty.cause.recorded_only`",
    "D08-C18": "`fixme`",
    "D08-C19": "no elapsed counter",
    "D08-C20": "`retryable`",
    "D08-C21": "1280 × 720",
    "D08-C22": "`forbidden` 403",
}
# C-rows whose Owner cell must name a lane (lens 1 M2, M4): row -> fragments the cell holds
C_OWNERS = {
    "D08-C8": ("CMP-248's owner (D09's pattern)", "CMP-038's owner (E05-S02, #265)"),
    "D08-C17": ("#243",),
    "D08-C19": ("CMP-038's owner",),
    "D08-C21": ("#243",),
}


def g_crows(t: Texts) -> list[Finding]:
    """BQ-32 and the ruling's C-rows: each present with its subject and an owner cell; T Tech's
    two literal lines are two C-rows; `32` is not cited for the R7 / R8 rule (rider c)."""
    head = "15.1 Contradictions"
    sec = spec_sec(t, head)
    rows = {r[0]: r for r in table_rows(section(t.spec, head))}
    bad: list[Finding] = []
    if list(rows) != list(C_ROWS):
        bad.append(F("G-CROWS", f"C-rows read {list(rows)[:4]}…", "spec", sec))
    for cid, frag in C_ROWS.items():
        r = rows.get(cid)
        if r is None or len(r) < 4 or frag.lower() not in strip_comments(r[1]).lower() or not r[3]:
            bad.append(F("G-CROWS", f"{cid}: subject or owner", "spec", sec))
    for cid, frags in C_OWNERS.items():
        owner = rows.get(cid, ["", "", "", ""])[3:4]
        if not owner or any(f not in owner[0] for f in frags):
            bad.append(F("G-CROWS", f"{cid}: owner lane {owner!r}", "spec", sec))
    r14 = rows.get("D08-C14", [])
    if any("`32`:" in c for c in r14):
        bad.append(F("G-CROWS", "D08-C14 cites `32` for the rule", "spec", sec))
    return bad


SHAPE_RE = re.compile(
    r"\badd(?:s|ing)? `|\bshould (?:carry|hold|add|return)\b|:\s*\{|\btype:|\bnew field\b"
    r"|\brename\w*\b|\bas `[a-z_]+: ",
    re.IGNORECASE,
)
AGENT = re.compile(r"\bagent\b|hcl-worker|orchestrator|worker-\d|\blane\b", re.IGNORECASE)
DUE = re.compile(r"(E12-[SQD]\d\d \(#\d+\)), due (\d{4}-\d{2}-\d{2})")


def due_ok(cell: str) -> bool:
    ms = DUE.findall(cell)
    return bool(ms) and all(
        c in CONSUMER_KEYS and d == sprint_start(CONSUMER_KEYS[c]) for c, d in ms
    )


def g_grows(t: Texts) -> list[Finding]:
    """BQ-12, rider b: G-1 ... G-4, contract first, no shape; owners are tickets or spec owners,
    never an agent; due = the consumer's sprint start from CAL; the carried rows cited; the Q-rows
    owned and dated the same way."""
    head = "15.2 The G-ledger"
    sec = spec_sec(t, head)
    raw = section(t.spec, head)
    rows = table_rows(raw)
    bad: list[Finding] = []
    if [r[0] for r in rows] != [f"D08-G{n}" for n in range(1, 5)]:
        bad.append(F("G-GROWS", f"the ledger reads {[r[0] for r in rows]}", "spec", sec))
    for r in rows:
        if len(r) < 5 or not r[3] or AGENT.search(r[3]):
            bad.append(F("G-GROWS", f"{r[0]}: owner {r[3] if len(r) > 3 else ''!r}", "spec", sec))
        if any(SHAPE_RE.search(c) for c in r[1:3]):
            bad.append(F("G-GROWS", f"{r[0]}: a shape is proposed", "spec", sec))
        if len(r) < 5 or not due_ok(r[4]):
            bad.append(F("G-GROWS", f"{r[0]}: consumer and due date", "spec", sec))
    head_line = next((ln for ln in raw.split("\n") if ln.startswith("### 15.2")), "")
    for n in ("contract first", "no shape is proposed", "RULED rider b"):
        if n not in head_line:
            bad.append(F("G-GROWS", f"the ledger heading lacks {n!r}", "spec", sec))
    if "sprint start, CAL:13" not in raw:
        bad.append(F("G-GROWS", "the due column cites no sprint start", "spec", sec))
    for n in (
        "E11-D04 G-1",
        "G-2",
        "G-10 and O-12",
        "OQ-14",
        "D05-G1",
        "**Carried, cited, not re-proposed:**",
    ):
        if n not in raw:
            bad.append(F("G-GROWS", f"the carried rows lack {n!r}", "spec", sec))
    qsec = spec_sec(t, "15.3 Open questions")
    qraw = section(t.spec, "15.3 Open questions")
    qs = re.findall(r"^- \*\*(D08-Q\d+)\*\* (.*)$", qraw, MULTI)
    if [q for q, _ in qs] != [f"D08-Q{n}" for n in range(1, len(qs) + 1)] or len(qs) < 5:
        bad.append(F("G-GROWS", f"the Q-rows read {[q for q, _ in qs]}", "spec", qsec))
    for q, body in qs:
        if q == "D08-Q1":
            continue
        if not due_ok(body) or AGENT.search(body):
            bad.append(F("G-GROWS", f"{q}: owner lane or due date", "spec", qsec))
    return bad


def g_owner(t: Texts) -> list[Finding]:
    """BQ-31: the waiver PROPOSED, owner approval pending (#2701), Done targeted, the
    alternative reading beside it, the reason stated."""
    sec = spec_sec(t, "15.3 Open questions")
    q1 = next(
        (ln for ln in section(t.spec, "15.3 Open questions").split("\n") if "**D08-Q1**" in ln), ""
    )
    need = (
        OWNER_PENDING,
        f"Done targeted {DONE_TARGET}",
        "**Alternative reading:**",
        "E12-S06 (#395",
        "E12-S11 (#451)",
        "E12-D13 (#450",
        "`02`:53",
    )
    bad = [F("G-OWNER", f"D08-Q1 lacks {n!r}", "spec", sec) for n in need if n not in q1]
    dod = section(t.spec, "17.1 DoD")
    waiver = "- [ ] Done ≥2 sprints before the consuming stories — D08-Q1, owner approval pending"
    if f"{waiver} (#2701)." not in dod:
        bad.append(F("G-OWNER", "the DoD's waiver line", "spec", spec_sec(t, "17.1 DoD")))
    return bad


def g_marked(t: Texts) -> list[Finding]:
    """S-7, S-9: every PROPOSED name stands beside "PROPOSED" (its line or its heading); every
    `new` string is PROPOSED."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        head = ""
        skip = skip_lines(text, (MUTATION_HEAD,))
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
            for m in re.finditer(r"\*\*new\*\*(?!, PROPOSED)", line):
                msg = f"{doc}:{i} a `new` item not marked PROPOSED"
                bad.append(F("G-MARKED", msg, doc, h2_at(text, i)))
                del m
    return bad


SESSION_CLAIM = (
    r"\b(?:session|walkthrough|meeting)s?\b(?:\s+\S+){0,2}?\s+(?:was |were |has been |is )?"
    r"(?:held|ran|recorded|conducted|completed|happened|took place)\b|\btook place\b"
    r"|\bparticipants?\b|\battendees?\b|\bwalked through\b"
)
g_session = lexicon("G-SESSION", "a session held", SESSION_CLAIM)

WALK_HEAD = "16. The dry run"
WALKTHROUGH_HEAD = "§E Owner walkthrough"
REF = re.compile(r"→ (?:§(\d+(?:\.\d+)?)|(D08-[GQ]\d+))(?: \([^)]*\))?$")


def g_walk(t: Texts) -> list[Finding]:
    """Rider d (BQ-29, BQ-30): one row per role in order; needs = found + not found; one
    resolvable disposition per not-found; the §G lists count; the walkthrough at most ten; the
    DoD tick follows the record."""
    sec = spec_sec(t, WALK_HEAD)
    raw = section(t.spec, WALK_HEAD)
    rows = table_rows(raw)
    bad: list[Finding] = []
    if tuple(r[1] for r in rows if len(r) > 1) != WALK_ROLES:
        bad.append(F("G-WALK", "the rows are not every consumer + frontend + QA", "spec", sec))
    sections_ = set(re.findall(r"^#{2,3} (\d+(?:\.\d+)?)\.? ", t.spec, MULTI))
    rowids = set(re.findall(r"\bD08-[GQ]\d+\b", section(t.spec, "15. Rows")))

    def resolves(m: re.Match[str] | None) -> bool:
        if m is None:
            return False
        return (m[1] or "") in sections_ or (m[2] or "") in rowids

    lists = {r[0]: r[1] for r in table_rows(section(t.hand, NEEDS_HEAD)) if len(r) > 1}
    gsec = h2_of(t.hand, NEEDS_HEAD)
    for r in rows:
        if len(r) < 6 or r[0] != WALK_DATE or not all(x.isdigit() for x in r[2:5]):
            bad.append(F("G-WALK", f"{r[1] if len(r) > 1 else r}: date or counts", "spec", sec))
            continue
        need, found, nf = (int(x) for x in r[2:5])
        if need != found + nf:
            bad.append(F("G-WALK", f"{r[1]}: {need} != {found} + {nf}", "spec", sec))
        disp = [d for d in r[5].split(" · ") if d.strip() and d.strip() != "—"]
        if len(disp) != nf:
            bad.append(
                F("G-WALK", f"{r[1]}: {nf} not found, {len(disp)} dispositions", "spec", sec)
            )
        for d in disp:
            if not resolves(REF.search(d.strip())):
                bad.append(F("G-WALK", f"{r[1]}: {d[:40]!r} does not resolve", "spec", sec))
        items = [x.strip() for x in lists.get(r[1], "").split(" · ") if x.strip()]
        if len(items) != need or sum("(not found)" in x for x in items) != nf:
            msg = f"{r[1]}: hand-off §G lists {len(items)} needs, the row {need} / {nf}"
            bad += [F("G-WALK", msg, "hand", gsec), F("G-WALK", msg, "spec", sec)]
        for x in items:
            if not resolves(REF.search(x)):
                bad.append(
                    F("G-WALK", f"{r[1]}: §G item {x[:40]!r} does not resolve", "hand", gsec)
                )
    walk = [ln for ln in section(t.hand, WALKTHROUGH_HEAD).split("\n") if ln.startswith("- [")]
    if not 0 < len(walk) <= MAX_WALK:
        msg = f"the owner walkthrough has {len(walk)} items, not 1 to {MAX_WALK}"
        bad.append(F("G-WALK", msg, "hand", h2_of(t.hand, WALKTHROUGH_HEAD)))
    body = norm_text(raw)
    if norm_text("**No session took place and none is claimed.**") not in body:
        bad.append(F("G-WALK", "§16 lacks the no-session sentence", "spec", sec))
    if 'before any "not found" was recorded, the merged sources were searched' not in body:
        bad.append(F("G-WALK", "§16 lacks the search-first sentence", "spec", sec))
    for n in ('"test hook" / "data-testid" / "probe"', '"malformed" / "decoder", d09 and `23` §3'):
        if norm_text(n) not in body:  # lens 3 M6: the synonyms that found DR-4 and `23`:271
            bad.append(F("G-WALK", f"§16's search lacks {n[:30]!r}", "spec", sec))
    if "`Retry-After`" not in section(t.hand, WALKTHROUGH_HEAD):  # BQ-30's item; lens 1 m4
        msg = "the walkthrough lacks BQ-14's `Retry-After` item"
        bad.append(F("G-WALK", msg, "hand", h2_of(t.hand, WALKTHROUGH_HEAD)))
    dod = section(t.spec, "17.1 DoD")
    tick = re.search(r"^- \[(.)\] The dry run is the written confirmation", dod, MULTI)
    ok = not [f for f in bad if f[0] == "G-WALK"]
    if not tick or (tick[1] == "x") != ok:
        msg = "the DoD dry-run tick does not follow the record"
        bad.append(F("G-WALK", msg, "spec", spec_sec(t, "17.1 DoD")))
    return bad


REVIEW_HEAD = "16.1 Reviews in place of sessions"
# F-BAR-5's branches and F-BAR-3's outcome branches (`13`:817-900), each walked to a destination
FLOW_NODES = ("L5", "D5", "E5", "F5", "M5", "H5", "I5", "Q5", "J5", "J3", "K3", "N3", "O3", "P3")
NIELSEN = (
    "visibility of status",
    "match with the real world",
    "user control and freedom",
    "consistency",
    "error prevention",
    "recognition over recall",
    "flexibility",
    "minimalist design",
    "recovery from errors",
    "help",
)


def checklist_items(n: int) -> list[str]:
    """The `[ ] ` items of a `14` design sign-off checklist line."""
    line = base_line("14", n).split("checklist:**", 1)[-1]
    return [x.strip() for x in line.split("[ ]") if x.strip()]


def g_review(t: Texts) -> list[Finding]:
    """RULED BQ-30 (lens 1 M6): the `14` SCR-047 and SCR-048 checklists item by item, F-BAR-5 and
    F-BAR-3's outcome branches walked to a designed destination, the heuristic table and the
    session protocol, every row `(heuristic)`."""
    sec = spec_sec(t, REVIEW_HEAD)
    raw = section(t.spec, REVIEW_HEAD)
    body = norm_text(raw)
    bad: list[Finding] = []
    if not raw.startswith(f"### {REVIEW_HEAD}") or "`(heuristic)`" not in raw.split("\n", 1)[0]:
        bad.append(F("G-REVIEW", "§16.1 is missing or not marked `(heuristic)`", "spec", sec))
    for n in (1102, 1113):
        for item in checklist_items(n):
            if norm_text(f"{item} →") not in body:
                bad.append(
                    F("G-REVIEW", f"`14`:{n}'s item {item[:40]!r} is not walked", "spec", sec)
                )
    flows = "\n".join(base_line("13", n) for n in range(817, 901))
    for node in FLOW_NODES:
        if f"{node}[" not in flows:
            raise SystemExit(f"FAIL parse: `13` has no node {node}")
        if not re.search(rf"\b{node.lower()} [^·→]*(?:→ §|no state)", body):
            bad.append(F("G-REVIEW", f"the flow node {node} ends nowhere", "spec", sec))
    for h in NIELSEN:
        if not re.search(rf"\b{h} →", body):
            bad.append(F("G-REVIEW", f"the heuristic {h!r} has no row", "spec", sec))
    for need in (
        "**The session protocol, ready for the owner.**",
        "Every branch ends at a designed",
    ):
        if norm_text(need) not in body:
            bad.append(F("G-REVIEW", f"§16.1 lacks {need[:40]!r}", "spec", sec))
    return bad


@functools.lru_cache(maxsize=1)
def merge_base_sha() -> str:
    return git_out("merge-base", "HEAD", HEAD).strip()


def merge_base() -> str:
    """`git merge-base HEAD origin/main` (empty under the self-test's BROKEN lever)."""
    return "" if "merge-base" in BROKEN else merge_base_sha()


def stray_paths() -> tuple[str, ...] | None:
    """None under the self-test's BROKEN "diff" lever: git that cannot list paths."""
    return None if "diff" in BROKEN else stray_paths_at(merge_base())


@functools.lru_cache(maxsize=2)
def stray_paths_at(ref: str) -> tuple[str, ...] | None:
    """Paths changed against the merge-base (committed, staged, working tree or untracked) that
    are not this PR's own; None when git cannot list them (G-UNTOUCHED then FAILs closed).
    Untracked files that `.gitignore` hides are not listed: git never commits them."""
    if not ref:
        return ()
    ok_d, diff = git_run("diff", "--name-only", ref)
    ok_u, untracked = git_run("ls-files", "--others", "--exclude-standard")
    if not (ok_d and ok_u):
        return None
    names = diff.split("\n") + untracked.split("\n")
    return tuple(sorted({n for n in names if n and n not in OWN_PATHS}))


@functools.cache
def under_base(sha: str) -> bool:
    """`sha` names a commit that is the base or one of its ancestors."""
    full = git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").strip()
    return bool(full) and git_out("merge-base", full, BASE).strip() == full


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
    stray = stray_paths()
    if stray is None:
        return [*bad, F("G-UNTOUCHED", "git could not list the changed paths", None, None)]
    bad += [F("G-UNTOUCHED", f"{p} is not this PR's path", None, None) for p in stray]
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


def g_version(t: Texts) -> list[Finding]:
    """G-VERSION's shape: the **Start.** line carries every merged input's sha in order and the
    **Version.** line the pinned shas in order, each under the base; the version line records the
    late change (#4853) and names no unmerged work's sha; the Inputs line names the base."""
    lines = t.spec.split("\n")
    bad: list[Finding] = []
    for lead, want in (
        ("**Start.**", START_SHAS),
        ("**Version.**", VERSION_SHAS),
        ("**Inputs pinned.**", ()),
    ):
        i = next((n for n, ln in enumerate(lines) if ln.startswith(lead)), None)
        if i is None:
            bad.append(F("G-VERSION", f"no {lead} line", "spec", "(top)"))
            continue
        sec, line = h2_at(t.spec, i + 1), lines[i]
        if lead == "**Inputs pinned.**":
            if line.count(BASE) < 2:
                bad.append(F("G-VERSION", f"the Inputs line does not name {BASE}", "spec", sec))
            if "of the cited files only D09 is new" not in line:  # lens 1 m3
                bad.append(F("G-VERSION", "the Inputs line overclaims the diff", "spec", sec))
            continue
        got = tuple(re.findall(r"`([0-9a-f]{10})`", line))
        if got != want:
            msg = f"the {lead} line carries {len(got)} shas, not the {len(want)} in order"
            bad.append(F("G-VERSION", msg, "spec", sec))
        bad += [
            F("G-VERSION", f"`{s}` is not a commit under the base", "spec", sec)
            for s in got
            if not under_base(s)
        ]
        if lead == "**Version.**":
            for n in LATE_CHANGE:
                if n not in line:
                    bad.append(F("G-VERSION", f"the version line lacks {n!r}", "spec", sec))
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
    g_hidden,
    g_quote,
    g_marked,
    g_session,
    g_newcmp,
    g_handoff_words,
    g_role_words,
    g_live_words,
    g_nogl_words,
    g_skeleton_words,
    g_ref_words,
    g_ladder_words,
    g_progress_words,
    g_cadence_words,
    g_cancel_words,
    g_focus_words,
    g_rbac_words,
    g_approx_words,
    g_boundary_words,
    g_primary_words,
    g_vocab_words,
)
MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_boards,
    g_frame,
    g_locked,
    g_arow,
    g_handoff,
    g_reasons,
    g_enum,
    g_role,
    g_live,
    g_nogl,
    g_skeleton,
    g_map,
    g_classes,
    g_ref,
    g_leak,
    g_workspace,
    g_ladder,
    g_progress,
    g_cadence,
    g_cancel,
    g_focus,
    g_restore,
    g_rbac,
    g_approx,
    g_marker,
    g_edge,
    g_matrix,
    g_primary,
    g_vocab,
    g_deck,
    g_tokens,
    g_contrast,
    g_cvd,
    g_crows,
    g_grows,
    g_owner,
    g_walk,
    g_review,
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
        "# E12-D08 pins (every unit of both docs): doc, region (heading path #occurrence), "
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
    warns = []
    if head_ok() and head_sha().startswith(BASE):  # lens 2 Minor 2: a drift check of base on base
        warns.append(f"{HEAD} equals the base {BASE}: G-VERSION compared the base with itself")
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
    extra = (
        "| 11 | `E12-D08 / 11 rebuild-cancel-light` | light twin of 07 | light | to draw (PR 2) |"
    )
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
            if ln.startswith("|") and "QA: §4" in ln:
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


def walk_counts(role: str, need: str, found: str) -> Callable[[list[str]], list[str]]:
    """A dry-run row with new Needs and Found cells (the sum still holds)."""

    def run(lines: list[str]) -> list[str]:
        out = []
        for ln in lines:
            if ln.startswith("|") and not is_rule(ln) and split_row(ln)[1:2] == [role]:
                ln = set_cell(set_cell(ln, 2, to(need)), 3, to(found))
            out.append(ln)
        return out

    return run


def cvd_drift() -> Callable[[], None]:
    CVD_DRIFT.append(at_base(CVD_SRC).replace("2.02344", "2.02345", 1))

    def undo() -> None:
        CVD_DRIFT.pop()

    return undo


# §4's lead cells the lens-fold mutations edit
MAP_TOPIC_ROW = (
    "`subscription_limit`, `unsupported_symbol`, `invalid_topic_format`, `encoding_unsupported`,"
    " `invalid_options`, `unknown_topic` (`23`:1590–1595)"
)
MAP_4XX_ROW = (
    "`validation_failed` 400 or 422, `forbidden` 403 (drawn as the failed state; no role lacks"
    " `marketdata:read`), `rate_limited` 429"
)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1",
        "G-PENPOT",
        "BQ-1, S-3: the page by name and id only",
        spec=sub_in(
            "0. Status",
            "page `E12-D08 bar states`",
            "page `E12-D08 bar states` (https://penpot.example/v)",
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
        spec=sub_in("1.3 Locked", "`14`:729–762", "`14`:99999"),
    ),
    Mutation(
        "M-4",
        "G-VERSION",
        "brief: a cited line that drifts at origin/main FAILs",
        patch=drift("14", 737, "| partial-history | moved |"),
    ),
    Mutation(
        "M-5",
        "G-VERSION",
        "rider e: the late change recorded in the version line",
        spec=line_edit("**Version.**", "**Late change (RULED rider e):**", "**Note:**"),
    ),
    Mutation(
        "M-6",
        "G-VERSION",
        "BQ-32: the version line pins every merged input",
        spec=line_edit("**Start.**", " (`d05966f7a6`)", ""),
    ),
    Mutation(
        "M-7", "G-UNTOUCHED", "BQ-3: `15` untouched", plan=("15", appended_line("\nan edit\n"))
    ),
    Mutation(
        "M-8",
        "G-UNTOUCHED",
        "BQ-4: E16-D05 untouched",
        plan=("E16-D05", appended_line("\nan edit\n")),
    ),
    Mutation("M-9", "G-BUDGET", "brief: the line budgets", spec=overrun),
    Mutation("M-10", "G-BOARDS", "BQ-6: at most ten boards, twins a third", spec=add_board),
    Mutation(
        "M-11",
        "G-BOARDS",
        "BQ-6: the three ruled twins",
        spec=row_edit("0. Status", "10", 2, to("high-contrast / `forced-colors` twin of 06")),
    ),
    Mutation(
        "M-12",
        "G-HEX",
        "BQ-27: every hex is the tool's",
        spec=say_in("12. Tokens", "The strip reads #161B22."),
    ),
    Mutation(
        "M-13",
        "G-ANCHOR",
        "BQ-1: every number computed",
        spec=with_values(
            lambda v: sub_in(
                "7.1 Phases", f"0 to {av(v, 'CITE:silent')}", "0 to 500<!--=CITE:silent-->"
            )
        ),
    ),
    Mutation(
        "M-14",
        "G-WORDCOUNT",
        "brief: counts written as figures",
        spec=say_in("1.1 What this spec", "It draws ten boards."),
    ),
    Mutation(
        "M-15",
        "G-MARKER",
        "brief: every comment an anchor",
        spec=say_in("1.1 What this spec", "<!-- hidden -->"),
    ),
    Mutation(
        "M-16",
        "G-HIDDEN",
        "brief: no `[//]: #` comment",
        spec=prose_at("8.2 The off-screen", "[//]: # (the tag may sit on the right)"),
    ),
    Mutation(
        "M-17",
        "G-LOCKED",
        "BQ-2: the locked inputs",
        spec=in_lines("1.3 Locked", drop_line("| E08-D04 ")),
    ),
    Mutation("M-18", "G-AROW", "BQ-3: departures ship as A-rows", hand=drop_row("Table A", "A-3")),
    Mutation(
        "M-19",
        "G-AROW",
        "BQ-3: Old cells verbatim at the base",
        hand=row_edit("Table A", "A-4", 3, to("CMP-029 Skeleton placeholder.")),
    ),
    Mutation(
        "M-20",
        "G-AROW",
        "BQ-4: a `new` string's A-row carries it",
        hand=row_edit(
            "Table A", "A-6", 4, lambda c: c.replace("before {first available ts}", "yet")
        ),
    ),
    Mutation(
        "M-21",
        "G-HANDOFF",
        "brief: every `-handoff.md` reference correct",
        spec=say_in("2.1 What this spec", "See E12-D09-handoff.md."),
    ),
    Mutation(
        "M-22",
        "G-HANDOFF",
        "`16` §11.4: every §A cell ticked with evidence",
        hand=row_edit("§A Hand-off", "Density notes", 1, to("—")),
    ),
    Mutation(
        "M-23", "G-CLOSE", "S-1: no closing keyword", hand=say_in("§H Summary", "Closes #243.")
    ),
    Mutation(
        "M-24", "G-CHARSET", "brief: the charset", spec=say_in("1.1 What this spec", "A\u200bB.")
    ),
    Mutation(
        "M-25",
        "G-CELLS",
        "brief: every row has its header's cells",
        spec=row_edit(MAP_HEAD, "`unauthenticated` 401", 5, appended(" | extra")),
    ),
    Mutation(
        "M-26",
        "G-TRACE",
        "BQ-1: the trace holds AC1 ... AC5",
        spec=in_lines("Acceptance-criteria trace", drop_line("| AC3 ")),
    ),
    Mutation(
        "M-27",
        "G-RULED",
        "the ruling cited, no other comment id",
        spec=say_in("1.1 What this spec", "See comment 6400000001."),
    ),
    Mutation(
        "M-28",
        "G-RULED",
        "the eleven explicit confirmations",
        spec=sub_in("The questions", "BQ-21, BQ-22**", "BQ-21**"),
    ),
    Mutation(
        "M-29",
        "G-FRAME",
        "BQ-6: the frame register's Copy column",
        spec=reg("SCR-047/not-trading · dark", "Copy", to("W-8, W-99")),
    ),
    Mutation(
        "M-30",
        "G-DECK",
        "R-6: E11-D04's words verbatim",
        spec=row_edit(DECK_HEAD, "W-19", 1, to('"The server could not build this chart."')),
    ),
    Mutation(
        "M-31",
        "G-REASONS",
        "BQ-7: headings pairwise distinct",
        spec=row_edit(
            REASONS_HEAD, "`SCR-047/exchange-no-bars`", 4, to("W-4, the E16-D05:205 heading form")
        ),
    ),
    Mutation(
        "M-32",
        "G-REASONS",
        "BQ-7: causes pairwise distinct (D08-C17)",
        spec=row_edit(
            REASONS_HEAD, "`SCR-047/interval-too-fine`", 5, to("W-2, E16-D05:158 verbatim")
        ),
    ),
    Mutation(
        "M-33",
        "G-ENUM",
        "BQ-13: `kind` stays three values",
        spec=say_in(CLASSES_HEAD, "A recompute failure carries `kind: recompute`."),
    ),
    Mutation(
        "M-34",
        "G-CLASSES",
        "BQ-13: the class headings distinct",
        spec=row_edit(DECK_HEAD, "W-20", 1, to('"The server couldn\'t build this chart."')),
    ),
    Mutation(
        "M-35",
        "G-MAP",
        "BQ-11: every reachable code mapped",
        spec=sub_in(
            MAP_HEAD, "| `subscription_limit`, `unsupported_symbol`", "| `unsupported_symbol`"
        ),
    ),
    Mutation(
        "M-36",
        "G-MAP",
        "BQ-11: a straddling 422 draws the boundary",
        spec=row_edit(
            MAP_HEAD,
            "`no_data_recorded` 422, the window straddling `recording_started_at`",
            2,
            to("SCR-047 `before-start`"),
        ),
    ),
    Mutation(
        "M-37",
        "G-MAP",
        "BQ-11: an empty non-time `200` builds",
        spec=row_edit(
            MAP_HEAD, "`200` with zero rows, non-time", 2, to("SCR-047 `exchange-no-bars`")
        ),
    ),
    Mutation(
        "M-38",
        "G-MAP",
        "BQ-11: `no_data_recorded` never reaches SCR-048",
        spec=row_edit(
            MAP_HEAD,
            "`no_data_recorded` 422, the window wholly before `recording_started_at`",
            2,
            to("SCR-048 backend"),
        ),
    ),
    Mutation(
        "M-39",
        "G-LADDER",
        "BQ-14: no automatic retry on a 4xx",
        spec=sub_in("6. The retry", "**No automatic retry on a 4xx**", "**Retry a 4xx too**"),
    ),
    Mutation(
        "M-40",
        "G-LADDER",
        "BQ-14: the stops",
        spec=say_in("6. The retry", "Automatic retries continue indefinitely."),
    ),
    Mutation(
        "M-41",
        "G-LADDER",
        "BQ-14: the longer of the step and `Retry-After`",
        spec=sub_in(
            "6. The retry", "the longer of the ladder step", "the shorter of the ladder step"
        ),
    ),
    Mutation(
        "M-42",
        "G-PROGRESS",
        "BQ-19: no percentage while the total is unknown",
        spec=row_edit(
            "7.1 Phases",
            "total unknown",
            2,
            to("W-29 with `Cancel` and a percentage from the estimate"),
        ),
    ),
    Mutation(
        "M-43",
        "G-PROGRESS",
        "BQ-19: determinate only with G-1's done and total",
        spec=row_edit("7.1 Phases", "determinate", 1, to("whenever the strip shows")),
    ),
    Mutation(
        "M-44",
        "G-CADENCE",
        "T Perf: the cadence",
        spec=say_in("7.2 Cadence", "The progress bar redraws every frame."),
    ),
    Mutation(
        "M-45",
        "G-CANCEL",
        "BQ-21: `Cancel` never CMP-038's",
        spec=sub_in("7.3 `Cancel`", "`Cancel` is never CMP-038's", "`Cancel` is CMP-038's own"),
    ),
    Mutation(
        "M-46",
        "G-CANCEL",
        "BQ-21: `Cancel` from the strip's first line",
        spec=say_in("7.3 `Cancel`", "No cancel is needed in the first phase."),
    ),
    Mutation(
        "M-47",
        "G-FOCUS",
        "BQ-21: focus per D-11",
        spec=say_in(
            "7.4 The restore",
            "After a cancel, focus returns to the control that started the rebuild.",
        ),
    ),
    Mutation(
        "M-48",
        "G-RESTORE",
        "BQ-21: no partial series after a cancel",
        spec=sub_in("7.4 The restore", ", and no partial series is shown", ""),
    ),
    Mutation(
        "M-49",
        "G-RBAC",
        "BQ-25: who may cancel",
        spec=say_in("7.5 Who may", "Any role may cancel any build."),
    ),
    Mutation(
        "M-50",
        "G-APPROX",
        "BQ-28: no approximate action",
        spec=row_edit(
            REASONS_HEAD,
            "`SCR-047/never-recorded-owner`",
            6,
            appended(" · `Approximate from klines`"),
        ),
    ),
    Mutation(
        "M-51",
        "G-APPROX",
        "BQ-28: never approximate (prose)",
        spec=say_in("8.1 The boundary", "Earlier non-time bars are filled from klines."),
    ),
    Mutation(
        "M-52",
        "G-ROLE",
        "BQ-8, S-10: a sentence, never a dead button",
        spec=say_in("3.2 The role legs", "A Manager sees a disabled `Record this symbol` button."),
    ),
    Mutation(
        "M-53",
        "G-REF",
        "BQ-15: the reference opaque",
        spec=say_in(
            "5.2 The reference", "The reference is derived from the symbol and the session."
        ),
    ),
    Mutation(
        "M-54",
        "G-LEAK",
        "T Sec: no internal detail in copy",
        spec=row_edit(
            DECK_HEAD,
            "W-20",
            1,
            to('"Couldn\'t build Renko 40 ticks for BTCUSDT (postgres timeout)."'),
        ),
    ),
    Mutation(
        "M-55",
        "G-WORKSPACE",
        "BQ-16: no stop-loss claim",
        spec=sub_in(
            "5.3 The rest",
            "The card claims nothing about stop-losses",
            "The card says stop-losses hold",
        ),
    ),
    Mutation(
        "M-56",
        "G-NOGL",
        "BQ-10: SCR-047 without GL",
        spec=say_in("3.4 DOM", "The empty state mounts a canvas for the axes."),
    ),
    Mutation(
        "M-57",
        "G-SKELETON",
        "BQ-10: CMP-029 for the deciding phase only",
        spec=say_in("3.4 DOM", "CMP-029 stays as the empty state."),
    ),
    Mutation(
        "M-58",
        "G-LIVE",
        "BQ-9: the live sentence omitted under Stale",
        spec=say_in("3.3 The live-data", "The sentence stays under Stale."),
    ),
    Mutation(
        "M-59",
        "G-BOUNDARY",
        "D06:289: never hatched",
        spec=say_in("8.3 The difference", "The boundary is a hatched band."),
    ),
    Mutation(
        "M-60",
        "G-EDGE",
        "BQ-18: the tag at the left edge",
        spec=sub_in("8.2 The off-screen", "plot's left edge", "plot's right edge"),
    ),
    Mutation(
        "M-61",
        "G-MATRIX",
        "BQ-22: every pair as `14`",
        spec=row_edit(
            MATRIX_HEAD, "rebuilding + partial-history", 1, to("partial-history (strip)")
        ),
    ),
    Mutation(
        "M-62",
        "G-PRIMARY",
        "AC4: exactly one primary",
        spec=row_edit(MATRIX_HEAD, FOURWAY, 1, to("rebuilding and partial-history (strip)")),
    ),
    Mutation(
        "M-63",
        "G-PRIMARY",
        "AC4: one line in the strip",
        spec=say_in(MATRIX_HEAD, "The strip shows both lines when both are true."),
    ),
    Mutation(
        "M-64",
        "G-VOCAB",
        "BQ-9, BQ-23: no new data-confidence state",
        spec=say_in("9.3 The quarantined", "A quarantined series shows a series paused chip."),
    ),
    Mutation(
        "M-65",
        "G-OWNER",
        "BQ-31: owner approval pending (#2701)",
        spec=line_edit("- **D08-Q1**", "PROPOSED, owner approval pending (#2701).", "taken."),
    ),
    Mutation(
        "M-66",
        "G-GROWS",
        "rider b: owners are tickets, never an agent",
        spec=row_edit("15.2 The G-ledger", "D08-G3", 3, to("the writing agent")),
    ),
    Mutation(
        "M-67",
        "G-GROWS",
        "rider b: due = the consumer's sprint start",
        spec=row_edit("15.2 The G-ledger", "D08-G3", 4, to("E12-S06 (#395), due 2026-11-20")),
    ),
    Mutation(
        "M-68", "G-CROWS", "BQ-32: the C-rows", spec=drop_row("15.1 Contradictions", "D08-C17")
    ),
    Mutation(
        "M-69",
        "G-QUOTE",
        "S-9: nothing quoted that no source holds",
        spec=say_in("2.1 What this spec", 'The strip reads "Rebuilding the whole chart now".'),
    ),
    Mutation(
        "M-70",
        "G-MARKED",
        "S-7: every `new` string PROPOSED",
        spec=sub_in(
            "7.5 Who may",
            "W-32 without `Cancel` (**new**, PROPOSED)",
            "W-32 without `Cancel` (**new**)",
        ),
    ),
    Mutation(
        "M-71",
        "G-SESSION",
        "T Adapt: no session claimed",
        spec=say_in(WALK_HEAD, "A walkthrough was held with the owner."),
    ),
    Mutation(
        "M-72",
        "G-WALK",
        "rider d: the counts follow the needs lists",
        spec=in_lines(WALK_HEAD, walk_counts("story: E12-S12 (#535)", "15", "14")),
    ),
    Mutation(
        "M-73",
        "G-WALK",
        "BQ-30: the walkthrough at most ten items",
        hand=in_lines(
            WALKTHROUGH_HEAD, lambda ls: dup_line("- [ ] Board 01")(dup_line("- [ ] Board 01")(ls))
        ),
    ),
    Mutation(
        "M-74",
        "G-TOKENS",
        "BQ-27: shipped tokens only",
        spec=say_in("12. Tokens", "The strip edge uses `color.strip.edge`."),
    ),
    Mutation(
        "M-75",
        "G-CONTRAST",
        "BQ-27: each pair clears its bar",
        spec=row_edit(PAIRS_HEAD, "`action.primary.default` on `surface.hover`", 4, to("text")),
    ),
    Mutation(
        "M-76", "G-CVD", "BQ-27: the CVD constants are the research script's", patch=cvd_drift
    ),
    Mutation(
        "M-77",
        "G-CVD",
        "BQ-27: the one CVD exception stated",
        spec=sub_in("12. Tokens", "except the progress fill on its track", "except one pair"),
    ),
    Mutation(
        "M-78",
        "G-NEWCMP",
        "BQ-5: no new component here",
        spec=say_in("2.1 What this spec", "This spec adds a new component for the edge tag."),
    ),
    # the lens folds (2026-10-28): one per ruled sentence they touched
    Mutation(
        "M-79",
        "G-MATRIX",
        "BQ-22: every pair of `14`:746-761 has its row",
        spec=drop_row(MATRIX_HEAD, "rebuilding or cache-loading + streaming, forming-bar"),
    ),
    Mutation(
        "M-80",
        "G-MATRIX",
        "BQ-22: the pairs in `14`'s order",
        spec=in_lines(
            MATRIX_HEAD,
            swap_rows("LOD-aggregated + forming-bar", "LOD-aggregated + partial-history"),
        ),
    ),
    Mutation(
        "M-81",
        "G-REASONS",
        "BQ-7 / D08-C17: no doc claims every cause distinct",
        hand=line_edit(
            "2. SCR-047",
            "each heading distinct and each cause but 1a and 1b's (D08-C17)",
            "each heading and cause distinct",
        ),
    ),
    Mutation(
        "M-82",
        "G-CROWS",
        "BQ-7: D08-C17 routed to #243's ruling",
        spec=row_edit("15.1 Contradictions", "D08-C17", 3, to("—")),
    ),
    Mutation(
        "M-83",
        "G-PROGRESS",
        "BQ-19: never a percentage in CMP-038 text",
        spec=row_edit("7.1 Phases", "over budget, total unknown", 2, to("W-30 with `Cancel`")),
    ),
    Mutation(
        "M-84",
        "G-PROGRESS",
        "BQ-19: each overrun form binds its component",
        spec=row_edit("7.1 Phases", "over budget, total known", 3, to("CMP-023 or CMP-038")),
    ),
    Mutation(
        "M-85",
        "G-PROGRESS",
        "BQ-19, BQ-24: the elapsed counter outside CMP-038's region",
        spec=say_in("7.1 Phases", "The elapsed counter sits inside CMP-038's status region."),
    ),
    Mutation(
        "M-86",
        "G-AROW",
        "BQ-21: A-8 carries `Cancel` from 600 ms to D09's pattern",
        hand=row_edit(
            "Table A",
            "A-8",
            4,
            lambda c: c.replace("`Cancel` on the strip from 600 ms", "`Cancel`"),
        ),
    ),
    Mutation(
        "M-87",
        "G-CROWS",
        "BQ-21: D08-C8 routed to D09's pattern owner",
        spec=row_edit(
            "15.1 Contradictions",
            "D08-C8",
            3,
            lambda c: c.replace("CMP-248's owner (D09's pattern); ", ""),
        ),
    ),
    Mutation(
        "M-88",
        "G-MAP",
        "BQ-11: every topic-scope code of `23` §10.2 mapped",
        spec=sub_in(MAP_HEAD, ", `unknown_topic` (`23`:1590–1595)", " (`23`:1590–1595)"),
    ),
    Mutation(
        "M-89",
        "G-MAP",
        "BQ-11, R-6: every SCR-048 code has words",
        spec=row_edit(MAP_HEAD, MAP_TOPIC_ROW, 4, to("W-17, E11-D04:367 by code")),
    ),
    Mutation(
        "M-90",
        "G-REVIEW",
        "BQ-30: the `14` checklists item by item",
        spec=sub_in(REVIEW_HEAD, " · correlation id copyable → §5.2", ""),
    ),
    Mutation(
        "M-91",
        "G-REVIEW",
        "BQ-30: every flow branch walked",
        spec=sub_in(REVIEW_HEAD, " · O3 connection lost → §7.4", ""),
    ),
    Mutation(
        "M-92",
        "G-EDGE",
        "BQ-18: the note is not the control",
        spec=say_in("8.2 The off-screen", "Enter on the tag pans to the boundary."),
    ),
    Mutation(
        "M-93",
        "G-LADDER",
        "BQ-14: the 429 split PROPOSED",
        spec=sub_in("6. The retry", "(PROPOSED; D08-C20)", "(D08-C20)"),
    ),
    Mutation(
        "M-94",
        "G-VERSION",
        "BQ-2: the Inputs line claims only what the diff shows",
        spec=line_edit("**Inputs pinned.**", "of the cited files only D09", "only D09"),
    ),
    Mutation(
        "M-95",
        "G-WALK",
        "BQ-30: BQ-14's `Retry-After` rule a walkthrough item",
        hand=line_edit(
            "- [ ] Board 03",
            ", and a `Retry-After` wait is the longer of the step and the server's",
            "",
        ),
    ),
    Mutation(
        "M-96",
        "G-WALK",
        "rider d: the synonym search",
        spec=sub_in(WALK_HEAD, '; "test hook" / "data-testid" / "probe"', ""),
    ),
    Mutation(
        "M-97",
        "G-UNTOUCHED",
        "BQ-3: git that cannot list the paths FAILs",
        patch=pushed(BROKEN, "diff"),
    ),
    Mutation(
        "M-98",
        "G-CANCEL",
        "BQ-21: the D-5 amendment routed to D09's pattern",
        spec=sub_in("7.3 `Cancel`", ", and A-8 to D09's pattern, which still", ", which still"),
    ),
    # paraphrases of ruled sentences (synonyms each gate refuses)
    Mutation(
        "X-1",
        "G-APPROX",
        "BQ-28 paraphrase",
        spec=say_in("3.1 The frames", "Offer to estimate the missing bars."),
    ),
    Mutation(
        "X-2",
        "G-APPROX",
        "BQ-28 paraphrase",
        spec=say_in("8.1 The boundary", "The chart synthesises earlier bars."),
    ),
    Mutation(
        "X-3",
        "G-APPROX",
        "BQ-28 paraphrase",
        spec=say_in("8.1 The boundary", "It may fill the gap with REST klines."),
    ),
    Mutation(
        "X-4",
        "G-LADDER",
        "BQ-14 paraphrase",
        spec=say_in("6. The retry", "The card keeps retrying."),
    ),
    Mutation(
        "X-5",
        "G-LADDER",
        "BQ-14 paraphrase",
        spec=say_in("6. The retry", "A 4xx is retried automatically."),
    ),
    Mutation(
        "X-6",
        "G-CANCEL",
        "BQ-21 paraphrase",
        spec=say_in("7.3 `Cancel`", "The Cancel button appears once the determinate phase starts."),
    ),
    Mutation(
        "X-7",
        "G-CANCEL",
        "BQ-21 paraphrase",
        spec=say_in("7.3 `Cancel`", "Cancel uses CMP-038's slow path."),
    ),
    Mutation(
        "X-8",
        "G-PRIMARY",
        "AC4 paraphrase",
        spec=say_in(MATRIX_HEAD, "Both indicators are primary."),
    ),
    Mutation(
        "X-9",
        "G-PRIMARY",
        "AC4 paraphrase",
        spec=say_in(MATRIX_HEAD, "The strip stacks both lines."),
    ),
    Mutation(
        "X-10",
        "G-BOUNDARY",
        "D06:289 paraphrase",
        spec=say_in("8.3 The difference", "The region left of the boundary is shaded."),
    ),
    Mutation(
        "X-11",
        "G-BOUNDARY",
        "D06:289 paraphrase",
        spec=say_in("8.3 The difference", "The boundary is drawn as a shaded band."),
    ),
    Mutation(
        "X-12",
        "G-NOGL",
        "BQ-10 paraphrase",
        spec=say_in("3.4 DOM", "SCR-047 initialises WebGL for the axes."),
    ),
    Mutation(
        "X-13",
        "G-SKELETON",
        "BQ-10 paraphrase",
        spec=say_in("3.4 DOM", "CMP-029 remains after the reason is known."),
    ),
    Mutation(
        "X-14",
        "G-VOCAB",
        "R-4 paraphrase",
        spec=say_in("9.3 The quarantined", "It gets a new state named Paused."),
    ),
    Mutation(
        "X-15",
        "G-RBAC",
        "BQ-25 paraphrase",
        spec=say_in("7.5 Who may", "Every user can cancel the build."),
    ),
    Mutation(
        "X-16",
        "G-REF",
        "BQ-15 paraphrase",
        spec=say_in("5.2 The reference", "The ref is made of the account id."),
    ),
    Mutation(
        "X-17",
        "G-ROLE",
        "S-10 paraphrase",
        spec=say_in("3.2 The role legs", "Managers see the CTA as a locked button."),
    ),
    Mutation(
        "X-18",
        "G-PROGRESS",
        "BQ-19 paraphrase",
        spec=say_in("7.1 Phases", "Show a percentage based on elapsed time."),
    ),
    Mutation(
        "X-19",
        "G-CADENCE",
        "T Perf paraphrase",
        spec=say_in("7.2 Cadence", "The text updates continuously."),
    ),
    Mutation(
        "X-20",
        "G-LIVE",
        "BQ-9 paraphrase",
        spec=say_in("3.3 The live-data", "It remains while the feed is stale."),
    ),
    Mutation(
        "X-21",
        "G-ENUM",
        "BQ-13 paraphrase",
        spec=say_in(CLASSES_HEAD, "It adds a new kind value for recompute."),
    ),
    Mutation(
        "X-22",
        "G-NEWCMP",
        "BQ-5 paraphrase",
        spec=say_in("2.1 What this spec", "This ticket introduces a component for the tag."),
    ),
    Mutation(
        "X-23",
        "G-SESSION",
        "T Adapt paraphrase",
        spec=say_in(WALK_HEAD, "Participants reviewed the boards."),
    ),
    Mutation(
        "X-24",
        "G-FOCUS",
        "BQ-21 paraphrase",
        spec=say_in("10.2 Keyboard", "The alert steals focus once."),
    ),
    Mutation(
        "X-25",
        "G-FOCUS",
        "BQ-21 paraphrase",
        spec=say_in("7.4 The restore", "Focus goes to the field that started the build."),
    ),
    # lens 2's paraphrases the pins alone caught, and the lens folds' own paraphrases
    Mutation(
        "X-26",
        "G-LADDER",
        "R-3 paraphrase (lens 2 X04)",
        spec=sub_in("1.4 Rules", "Every wait states a bound", "Most waits state a bound"),
    ),
    Mutation(
        "X-27",
        "G-NOGL",
        "BQ-10 paraphrase (lens 2 X09)",
        spec=sub_in(
            "3.4 DOM",
            "a timeout is SCR-048 backend (E11-D04:353)",
            "a timeout extends the skeleton once more (E11-D04:353)",
        ),
    ),
    Mutation(
        "X-28",
        "G-REF",
        "BQ-15 paraphrase (lens 2 X11)",
        spec=sub_in(
            "5.2 The reference",
            "no account id, symbol, session token or user identity (T Sec)",
            "it may carry the symbol to help support, but no session token (T Sec)",
        ),
    ),
    Mutation(
        "X-29",
        "G-LADDER",
        "BQ-14 anchor swap (lens 2 X15)",
        spec=with_values(
            lambda v: sub_in(
                "6. The retry",
                f"capped at {av(v, 'CITE:ladder.cap')} s (**new**",
                f"capped at {av(v, 'CITE:silent')} s (**new**",
            )
        ),
    ),
    Mutation(
        "X-30",
        "G-CADENCE",
        "BQ-20 paraphrase (lens 2 X17)",
        spec=sub_in(
            "7.2 Cadence", "no automatic cancel;", "the build cancels itself at twice the estimate;"
        ),
    ),
    Mutation(
        "X-31",
        "G-CANCEL",
        "BQ-21 paraphrase (lens 2 X18)",
        spec=with_values(
            lambda v: sub_in(
                "7.3 `Cancel`", f"within {av(v, 'CITE:cancel.s')} s", "within a few seconds"
            )
        ),
    ),
    Mutation(
        "X-32",
        "G-FOCUS",
        "BQ-21 paraphrase (lens 2 X21)",
        spec=sub_in(
            "7.4 The restore",
            "completion and cancel never move focus",
            "completion and cancel move focus to the pill",
        ),
    ),
    Mutation(
        "X-33",
        "G-FOCUS",
        "BQ-24 paraphrase (lens 2 X28)",
        spec=sub_in(
            "10.2 Keyboard",
            "**Focus is never moved by a state**",
            "**The error state moves focus to Retry**",
        ),
    ),
    Mutation(
        "X-34",
        "G-BOARDS",
        "S-1 paraphrase (lens 2 X29)",
        spec=line_edit("**Ticket:**", "are drawn in PR 2, which", "are drawn in this PR, which"),
    ),
    Mutation(
        "X-35",
        "G-BOUNDARY",
        "D06:289 paraphrase in the hand-off (lens 2 H02)",
        hand=sub_in(
            "§H Summary",
            "with a timestamp tag, never a band;",
            "with a timestamp tag over a soft tinted band;",
        ),
    ),
    Mutation(
        "X-36",
        "G-BOUNDARY",
        "`14`:737 paraphrase in the hand-off (lens 2 H04)",
        hand=row_edit(HANDA_HEAD, "Live data", 4, to("[x] announced politely once")),
    ),
    Mutation(
        "X-37",
        "G-CANCEL",
        "BQ-21: the cancel bound moved away (lens 2 X32)",
        spec=in_lines("7.3 `Cancel`", drop_line("- Cancel takes effect")),
    ),
    Mutation(
        "X-38",
        "G-REASONS",
        "D08-C17 paraphrase",
        hand=line_edit(
            "- [ ] Board 01",
            "each heading its own and each cause but 1a and 1b's shared one (D08-C17)",
            "every cause unique",
        ),
    ),
    Mutation(
        "X-39",
        "G-EDGE",
        "BQ-18 paraphrase",
        spec=say_in("10.2 Keyboard", "Activating the note pans to the boundary."),
    ),
    Mutation(
        "X-40",
        "G-PROGRESS",
        "BQ-24 paraphrase",
        spec=say_in("10.1 Roles", "The elapsed time is announced at each tick."),
    ),
    Mutation(
        "X-41",
        "G-MAP",
        "BQ-11 paraphrase",
        spec=row_edit(MAP_HEAD, MAP_4XX_ROW, 4, to("W-19, E11-D04:368 by code")),
    ),
    Mutation(
        "X-42",
        "G-MATRIX",
        "BQ-22 paraphrase",
        spec=drop_row(MATRIX_HEAD, "LOD-aggregated + coverage-gap"),
    ),
    # one per pin class (G-RULED-PIN only)
    Mutation(
        "P-1",
        "G-RULED-PIN",
        "a frame row changed",
        spec=reg(
            "SCR-030/boundary-at-l2 · dark", "State", to("the boundary at an L2 column (sic)")
        ),
    ),
    Mutation(
        "P-2",
        "G-RULED-PIN",
        "a frame row moved",
        spec=in_lines(
            FRAME_HEAD,
            swap_rows("`SCR-048/data-feed-retrying · dark`", "`SCR-048/data-feed-stopped · dark`"),
        ),
    ),
    Mutation(
        "P-3", "G-RULED-PIN", "a sentence added to a paragraph", spec=say_in("1.2 Method", "Ok.")
    ),
    Mutation(
        "P-4", "G-RULED-PIN", "a bullet duplicated", spec=in_lines("1.4 Rules", dup_line("- **R-6"))
    ),
    Mutation(
        "P-5", "G-RULED-PIN", "a sentence deleted", spec=in_lines("1.4 Rules", drop_line("- **R-6"))
    ),
    Mutation(
        "P-6",
        "G-RULED-PIN",
        "a new heading",
        spec=squeezed(prose_at("9.3 The quarantined", "### 9.4 Notes\n\nSee §9.3."), 4),
    ),
    Mutation("P-7", "G-RULED-PIN", "blank lines squeezed", spec=squeezed(None, 3)),
    Mutation(
        "P-8",
        "G-RULED-PIN",
        "a hand-off row changed",
        hand=row_edit("§D Storybook", "CMP-027 ErrorState", 1, appended(" (cited)")),
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
    Mutation(
        "P-11",
        "G-RULED-PIN",
        "a duplicated section",
        spec=squeezed(shadow("9.3 The quarantined"), 4),
    ),
    Mutation("P-12", "G-RULED-PIN", "a damaged pins file", patch=damaged_pins),
    # probes that must trip nothing
    Mutation(
        "N-1",
        "",
        "Prettier re-pads a table row",
        spec=in_lines(
            FRAME_HEAD,
            lambda ls: [
                x.replace(" | ", "   |   ") if "`SCR-030/boundary-at-l2 · dark`" in x else x
                for x in ls
            ],
        ),
    ),
    Mutation(
        "N-2",
        "",
        "Prettier pads a table's cells",
        spec=in_lines(
            MAP_HEAD,
            lambda ls: [
                x.replace(" | ", "  |  ") if x.startswith("| `invalid_cursor`") else x for x in ls
            ],
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
        (f"M-{n}", gate)
        for gate, body in re.findall(
            r"\*\*(G-[A-Z0-9-]+):\*\* (.*?)(?=\*\*G-|\Z)", section(spec_f, MUTATION_HEAD), re.DOTALL
        )
        for n in re.findall(r"\bM-(\d+)\b", body)
    ]
    built = [(mu.mid, mu.gate) for mu in MUTATIONS if mu.mid.startswith("M-")]
    if listed != built:
        ok = False
        lines.append(
            f"  section 14.2 lists {len(listed)} M-rows, the tool builds {len(built)}: they differ"
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
    ap = argparse.ArgumentParser(description="E12-D08 states audit (module docstring)")
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
        doc["head"] = head_sha()
        print(json.dumps(doc | {"cites": n}, ensure_ascii=False, indent=1))
    else:
        gates = len(LEXICON_GATES) + len(MEASURED_GATES) + 5
        shown = spec_path.relative_to(ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        print(f"## E12-D08 audit of {shown} (+ the hand-off) at base {BASE}")
        print(f"drift read against {HEAD} {head_sha() or '(unresolved)'}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(notes))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK - every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(notes)} NOTE, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
