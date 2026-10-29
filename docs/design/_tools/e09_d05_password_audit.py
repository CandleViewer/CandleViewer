#!/usr/bin/env python3
"""E09-D05 (#188) audit: SCR-004, the forced password change, and the SCR-112 password section.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base `772f1f07ca` (`git show`): the token JSON (dark = primitives +
semantic-dark, light = + semantic-light, hc = + semantic-hc), the plan texts the spec cites, the
merged E09 design docs, the as-built auth code, the interim SCR-004, the audit registry, the CVD
script's constants and the ticket JSON (`E09.json`); then this ticket's spec and hand-off from the
working tree, and the working-tree files the standing rule keeps untouched.

1. **Values (RULED BQ-1).** Every `{{KIND:key}}` outside a code span is COMPUTED: CITE (a figure
   parsed from its cited line at the base), RULED (the ruling's own figures), COUNT (boards, twins,
   frames, items, scores, the truth table, the CVD checks, line budgets), CONTRAST (WCAG 2.x,
   truncated to two decimals, in three themes). `--fill` writes `VALUE<!--=KIND:key-->`;
   `--check` re-derives every anchored value with a left boundary (G-ANCHOR), and FAILs a figure
   typed by hand before a unit or a counted noun and a count written as a word (G-WORDCOUNT).
2. **The comment strip.** One pattern over the whole text, `re.DOTALL`; every HTML comment must be
   a value anchor the tool computes (G-MARKER); a `[//]: #` link-reference comment is refused
   (G-COMMENT). The lexicon gates read rendered text only.
3. **Cites.** Every cite is read at the base (G-CITE: FAIL when a line is gone or blank).
   G-VERSION is content-based: each cited range's lines must stand, in order and contiguous,
   somewhere in the file at `origin/main` (a move is fine; an edit or an insert inside a cited range
   FAILs; an unresolvable `origin/main` FAILs); it also reads the version line's semantics (the
   base, each pinned doc's last touch, every sha under the base, #2110's state from ALLOW).
   G-QUOTE: every backticked snake name is verbatim in a source the line cites (or a core source),
   or a PROPOSED name; every quoted string of 12 characters or more is verbatim there, a W-n
   string, or a D02 wireframe string.
4. **Gates.** Lexicon gates read rows and prose after the comment strip (inline HTML tags
   dropped, entities decoded, NFKC, markup dropped, dashes to spaces, lower case; a claim is read
   per clause; a negation covers its own term within five words, a list coordinated after it, and
   a clause whose subject it negates; quoted copy, the mutation rows and the hand-off's Old cells
   are not claims). Each ruled behaviour has its cells read and its synonyms refused: every
   paraphrase the X-n probes plant (X-25 onwards are the lens-2 adversary's) fails a named gate
   even after a re-pin. A lexicon is a finite word list, so a paraphrase outside every list is
   caught by the pins alone, never by a re-pin. The BQ-1 security gates (G-ECHO, G-HINT, G-BREACH,
   G-AUTOCOMPLETE, G-DETAIL) and the meter gates (G-METER, G-TRUTH) read cells and clauses;
   G-CHARSET refuses a non-Latin letter, raw or as an entity (a homoglyph). G-UNTOUCHED compares
   committed and uncommitted paths with
   `git merge-base HEAD origin/main` and FAILs when it does not resolve; only the ticket's four
   files may differ. G-CHARSET, G-CELLS, G-CLOSE, G-BUDGET, G-ENTROPY close the set.
5. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over EVERY unit of both docs, in
   RULED_PIN_TXT: each heading, table row (by its lead cell), rule line, prose sentence and fenced
   block, by doc, region (heading path plus occurrence), location and exact text (NFKC, whitespace
   collapsed), with a line-shape tag per region. Anchored values are pinned with their values cut
   out (G-ANCHOR owns them). `--repin-ruled` is the only writer and refuses while a placeholder is
   unfilled. A pin finding in a section another gate already FAILs prints as a NOTE line.
6. **--self-test** applies every mutation of the spec's §15.2 (M-n) and the tool's own X-n
   (paraphrases), P-n (one per pin class) and N-n probes (which must trip nothing), with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names, and every
   text is restored byte-identically (sha256 in memory and on disk). The report is ASCII, every
   line at most 100 characters.

Usage (from the repo root):
  python3 -I docs/design/_tools/e09_d05_password_audit.py --check [SPEC] [--handoff F] \
      [--json] [--fill]
  python3 -I docs/design/_tools/e09_d05_password_audit.py --self-test
  python3 -I docs/design/_tools/e09_d05_password_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import functools
import hashlib
import html
import io
import itertools
import json
import math
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "772f1f07ca"  # every cite was read here (the spec's Inputs line; re-based from 81dcf838aa)
HEAD = "origin/main"  # G-VERSION: a cited range edited at origin/main FAILs
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E09/E09-D05.md"
HAND_REL = "docs/design/E09/E09-D05-handoff.md"
RULED_PIN_TXT = "docs/design/_tools/e09_d05_ruled_pins.txt"
TOOL_REL = "docs/design/_tools/e09_d05_password_audit.py"
DS_SRC_REL = "packages/ui/tokens"
# the standing rule: no `14`, `15`, `16`, `21`, `22`, `23` or `24` edit in PR 1 or PR 2; nor of
# the merged design docs this spec builds on
UNTOUCHED = ("14", "15", "16", "21", "22", "23", "24")
UNTOUCHED_DOCS = ("D02", "D03", "D04", "D06", "D08", "D09", "S03", "README")
# the CodeQL accepted-risk entry for this tool's `--json` print, and its line pin (ruled on
# #4930, 08:49Z): the two files this PR may touch beyond its own four
RISK_PATHS = ("security/accepted-risks.yaml", "scripts/tests/test_security_gate.py")
OWN_PATHS = (SPEC_REL, HAND_REL, TOOL_REL, RULED_PIN_TXT) + RISK_PATHS
CITE_FILES: dict[str, str] = {
    "D02": "docs/design/E09/E09-D02.md",
    "D03": "docs/design/E09/E09-D03.md",
    "D04": "docs/design/E09/E09-D04.md",
    "D06": "docs/design/E09/E09-D06.md",
    "D08": "docs/design/E09/E09-D08.md",
    "D09": "docs/design/E09/E09-D09.md",
    "S03": "docs/design/E09/E09-S03.md",
    "README": "docs/design/README.md",
    "CONST": "CONSTITUTION.md",
    "ADR10": "docs/plan/27-adrs/ADR-0010-auth-and-rbac.md",
    "TM": "docs/security/threat-models/e09-auth-rbac.md",
    "REV": "docs/security/reviews/e09-auth-review.md",
    "INV": "services/api/candleviewer/auth/invite_service.py",
    "INVR": "services/api/candleviewer/api/invites.py",
    "ERR": "services/api/candleviewer/auth/errors.py",
    "SESS": "services/api/candleviewer/auth/session_service.py",
    "AUTHR": "services/api/candleviewer/api/auth.py",
    "ACT": "services/api/candleviewer/audit/actions.py",
    "ALLOW": "services/api/tests/unit/architecture/composition_allowlist.json",
    "MX": "services/api/tests/contract/rbac/matrix.yaml",
    "CPS": "apps/web/src/features/auth/ChangePasswordScreen.tsx",
    "API": "apps/web/src/features/auth/authApi.ts",
    "MAN": "apps/web/src/routes/manifest.ts",
    "CVD": "docs/research/_tools/cvd_simulate.py",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "E09J": "docs/plan/backlog/E09.json",
}
TICKET_KEY = "E09-D05"
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SEMANTIC = ("semantic-dark", "semantic-light", "semantic-hc")

RULING_ID = "6489306947"
BQ_LIST_ID = "6489179256"
# the allow-list of comment ids the docs may cite: the ruling, the BQ list, the reassignment, the
# claim
RULED_IDS = (RULING_ID, BQ_LIST_ID, "6488249707", "6488724738")
OWNER_PENDING = "PROPOSED, owner approval pending (#2701)"  # BQ-7, BQ-8, BQ-33
MAX_BOARDS = 10  # RULED BQ-5 (lever 4): at most ten boards
TWIN_SHARE = Fraction(1, 3)  # twins at most a third of the boards (lever 4)
SPEC_LINE_BUDGET = 625  # "about 600 lines at most"; the lens fold's 23 mutation rows (§15.2)
HAND_LINE_BUDGET = 150  # "about 150 lines at most"
MAX_WALK = 10  # RULED BQ-32: the owner walkthrough, at most ten items
REPORT_WIDTH = 100  # the self-test report: ASCII, at most 100 characters a line
# the ruling's own figures (BQ-32 accepted as written: one character per 200 ms, a 2 s pause)
RULED_VALUES = {"RULED:sr.char": "200", "RULED:sr.pause": "2"}
# the version line (spec **Start.**): every merged input's sha, in order
VERSION_SHAS = (
    "772f1f07ca",
    "b1425624b9",
    "ff8933a1c2",
    "a30c6ec6ad",
    "05c12212b4",
    "9750dc4bc9",
    "3669e891e6",
    "3c1a9d769d",
    "6359111929",
    "baccf724a1",
    "d117dc7328",
    "c99ad48d78",
    "2fd29ecc34",
    "e49557952f",
    "ff8933a1c2",
    "c99ad48d78",
    "d117dc7328",
    "2fd29ecc34",
    "e49557952f",
    "246879844c",
)
# the pinned docs of the version line and the sha each is pinned at (its last touch at the base)
PINNED_DOCS = {
    "D02": "ff8933a1c2",
    "D03": "ff8933a1c2",
    "D04": "ff8933a1c2",
    "D06": "ff8933a1c2",
    "D08": "c99ad48d78",
    "D09": "d117dc7328",
    "S03": "2fd29ecc34",
    "CPS": "e49557952f",
    "API": "246879844c",
}
NAMED_ONLY = ("#2110", "#2099", "#190", "#193", "#194", "#291")
CONSUMERS = (
    "story: E09-D07 (#190)",
    "story: E09-D10 (#193)",
    "story: E09-D12 (#194)",
    "story: E09-D11 (#291)",
    "frontend: E09-S01 (#228)",
    "frontend: E09-S05 (#232)",
    "QA: E09-Q02 (#293)",
    "QA: E09-Q06 (#297)",
)
DRY_DATE = "2026-10-29"
# the D02 wireframe strings, read from the PNGs (`D02 img`); the only quotes not in a text file
D02_IMG = (
    "Choose a new password",
    "Password policy list (length/complexity)",
    "You've used this password before.",
    "This password appeared in a data breach. Choose another.",
    "Password updated",
    "Continue",
)

# CITE values: key -> (cite id, line, pattern whose group 1 is the value)
CITE_VALUES: dict[str, tuple[str, int, str]] = {
    "min": ("14", 209, r"≥(\d+) chars"),
    "reuse": ("14", 209, r"previous (\d+)"),
    "max": ("22", 17666, r"maxLength: (\d+)"),
    "debounce": ("15", 2569, r"debounced to (\d+) ms"),
    "frame": ("14", 212, r"<=(\d+) ms"),
    "input": ("E09J", 447, r"for a (\d+)-character input"),
    "viewport.w": ("16", 213, r"\*\*(\d+)×\d+px\*\*"),
    "viewport.h": ("16", 213, r"\*\*\d+×(\d+)px\*\*"),
    "hires.w": ("E09J", 447, r"1280x800 and (\d+)x\d+"),
    "hires.h": ("E09J", 447, r"1280x800 and \d+x(\d+)"),
    "zoom": ("E09J", 447, r"(\d+)% zoom"),
    "slow": ("D08", 344, r"busy past (\d+) s"),
    "distinct": ("INV", 126, r"< (\d+) or"),
    "identity.min": ("INV", 129, r"len\(username\) >= (\d+)"),
    "target.compact": ("15", 64, r"(\d+)×\d+px compact"),
    "target.comfortable": ("15", 64, r"(\d+)×\d+px comfortable"),
    "bar.text": ("05", 125, r"≥(\d+(?:\.\d+)?):1 against their background"),
    "bar.ui": ("05", 126, r"≥(\d+):1 against adjacent colours"),
}
# load-bearing fragments: (cite id, line at the base, text the line must hold)
CITED: tuple[tuple[str, int, str], ...] = (
    ("14", 204, "### SCR-004 — Forced password change"),
    ("14", 206, "password age beyond policy"),
    ("14", 209, '"This password appears in a known breach list."'),
    ("14", 210, "not colour only"),
    ("14", 211, "US-AUTH-006"),
    ("14", 212, "within one frame"),
    ("14", 2317, "### SCR-112 — Security settings"),
    ("14", 2327, "[x] change-password flow with policy shown up front"),
    ("14", 85, "RBAC denies server-side; the UI presents."),
    ("14", 88, "**Audit.**"),
    ("15", 2551, 'the error region is `role="alert"` and receives focus on appearance'),
    ("15", 2560, "never suppresses paste"),
    ("15", 2569, '("Weak"/"Fair"/"Strong")'),
    ("15", 2570, "`color.status.*`"),
    ("15", 2576, "character classes"),
    ("15", 2578, 'the list as a whole is `aria-live="polite"`'),
    ("15", 2579, "`color.text.muted`"),
    ("15", 64, "the name does not change with the state"),
    ("15", 467, "announced once when blur validation shows or changes the message"),
    ("15", 320, "never the exchange's `ret_msg`"),
    ("12", 52, "No other route is reachable until the change completes."),
    ("13", 696, "S3d[step3-completed] --> SH"),
    ("04", 845, "no forced periodic rotation"),
    ("04", 830, "password change"),
    ("04", 831, "a refused password step"),
    ("04", 1340, "Write the `intent` before the side effect"),
    ("21", 468, "Session invalidation cutoff"),
    ("21", 3784, "`auth.password_change`"),
    ("22", 1954, "Revokes all other sessions on success."),
    ("22", 1955, "x-rbac: { permissions: [], scope: self }"),
    ("22", 17663, "required: [current_password, new_password]"),
    ("22", 12929, "required: [password]"),
    ("22", 12947, '"422": { description: Password violates the policy. }'),
    ("22", 234, '"Sign out instead" therefore works'),
    ("24", 5024, "`password`"),
    ("24", 5030, "`auth.password_changed`"),
    ("ACT", 97, '"auth.password_change"'),
    ("ACT", 110, '"users.invite_redeemed"'),
    ("ALLOW", 333, '"PUT /auth/password"'),
    ("ALLOW", 334, "contract-first operation"),
    ("INV", 80, "a full breached-password corpus is later hardening"),
    ("INV", 132, "Password must not contain your username or email"),
    ("INVR", 449, 'code="password_policy"'),
    ("SESS", 921, 'password`\'s "revokes all other sessions on success"'),
    ("CPS", 72, "Strength: {strength(next)}"),
    ("CPS", 8, 'if (pw.length < MIN) return "Weak";'),
    ("API", 79, 'code.includes("reuse")'),
    ("D08", 138, "SCR-001 / 002 / 003 / 005 / 006"),
    ("D08", 136, "SCR-004 server reject"),
    ("D08", 344, "Still working — the server is slow to answer."),
    ("D09", 95, '"Read-only while viewing as {user}."'),
    ("D09", 273, '"Not sent — read-only after three wrong codes."'),
    ("D04", 155, '"Sign out" secondary action'),
    ("S03", 39, "Confirm sub-dialog"),
)

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z0-9]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
UNITS = r"(?:ms|s|hz|px|%|:1|fps|h)"
COUNTED = (
    r"(?:boards?|twins?|frames?|rows?|states?|pairs?|themes?|questions?|mutations?|characters?"
    r"|items?|consumers?|rules?|scores?|fields?|passwords?|strings?|hosts?|reasons?|minutes?"
    r"|seconds?|roles?|lines?|needs|checks?|entries|codes?|tick-box(?:es)?|g-rows?|c-rows?"
    r"|q-rows?|a-rows?|variants?|sections?|causes?)"
)
FIGURE = re.compile(
    rf"(?<![\w.,:#/>{{§+~-])(\d+(?:[.,]\d+)*)\s?(?:{UNITS}(?![\w])|{COUNTED}\b)", re.IGNORECASE
)
NUM_WORDS = (
    "two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    "|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|hundred"
)
WORDCOUNT = re.compile(rf"\b({NUM_WORDS})\b(?:\s+[\w'’-]+){{0,2}}?\s+{COUNTED}\b", re.IGNORECASE)
_BARE_IDS = "|".join(sorted(CITE_FILES, key=len, reverse=True))
CITE_GROUP = re.compile(
    rf"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:{_BARE_IDS})\b)) ?"
    r":(?P<first>\d+(?:[–-]\d+)?)"
    r"(?P<more>(?:(?:\s*\([^()\n]*\))?(?:,|\s+and)\s*:\d+(?:[–-]\d+)?)*)"
)
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]|\b[a-z0-9-]+\.(?:com|net|org|io|dev)\b", re.IGNORECASE)
COMMENT_ID = re.compile(r"(?<![\w-])(\d{8,})(?![\w-])")

Values = dict[str, str]
Fetch = Callable[[str, str], str | None]
DRIFT: list[tuple[str, int, str]] = []  # self-test lever: (path, line, text) read at HEAD
INSERT: list[tuple[str, int, str]] = []  # self-test lever: a line inserted at HEAD before line n
BROKEN: list[str] = []  # self-test lever: "head" or "merge-base" does not resolve
EXTRA_PATHS: list[str] = []  # self-test lever: paths pretended changed (G-UNTOUCHED)
CVD_OVERRIDE: list[dict[str, tuple[float, ...]]] = []  # self-test lever: drifted CVD constants
# a gate finding: (gate tag, message, doc, section); doc / section None for a repo-level finding
Finding = tuple[str, str, str | None, str | None]


def cite_path(cid: str) -> str | None:
    if re.fullmatch(r"\d{2}", cid):
        return plan_rel(cid)
    if cid in CITE_FILES:
        return CITE_FILES[cid]
    if "/" in cid:
        return cid
    return None


def git_fetch_head(rel: str) -> str | None:
    """The file at HEAD with the self-test's DRIFT and INSERT levers applied (G-VERSION)."""
    text = git_show(HEAD, rel)
    if text is None or not (DRIFT or INSERT):
        return text
    lines = text.split("\n")
    for r, n, new in DRIFT:
        if r == rel and 0 < n <= len(lines):
            lines[n - 1] = new
    for r, n, new in INSERT:
        if r == rel and 0 < n <= len(lines):
            lines.insert(n - 1, new)
    return "\n".join(lines)


# -------------------------------------------------------- shared helpers (the E08-D08 tool form)


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


COMMENT = re.compile(r"<!--(?:>|->|.*?--!?>|.*\Z)", re.DOTALL)


_HIDDEN = re.compile(COMMENT.pattern + r"|[\u00ad\u200b-\u200d\u2060\ufeff]", re.DOTALL)


def strip_comments(text: str) -> str:
    return _HIDDEN.sub("", text)


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


_DASHES = re.compile(r"[\u2010-\u2015\u2212-]")


_MARKUP = re.compile(r"[*`]")


_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


_EMPH = re.compile(r"(?<!\w)_+|_+(?!\w)")


_INLINE_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")


def norm_text(text: str) -> str:
    """Rendered words only: comments, inline HTML tags, soft hyphens and markup dropped, HTML
    entities decoded, NFKC, dashes to spaces, whitespace collapsed, lower case."""
    t = html.unescape(_INLINE_TAG.sub("", strip_comments(text)))
    t = unicodedata.normalize("NFKC", t)
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


# a clause whose subject is negated ("No string ... carries ...") negates its whole predicate;
# the idioms that only open with a negation word ("never mind", "no doubt") do not
NEG_SUBJECT = re.compile(
    r"^\W*(?:no|nothing|none|neither|never)\b(?! (?:doubt|matter|longer|mind|less|sooner))"
)
TURN = re.compile(r"\b(?:but|except|yet|however|unless|instead|although|though)\b")
# a filler word inside a gate's own term that is not a negation (the term then cannot swallow
# one: "the `detail` is never shown" is a negation, not a claim)
NEGFREE = r"(?!(?:no|never|not|nor|without|nothing|none|cannot)\b)"


def _live(t: str, term: str) -> bool:
    t = DOUBLE_NEG.sub(" ", t)
    if NEG_SUBJECT.match(t) and not TURN.search(t):
        return False
    sep = r"(?:,\s*(?:or\s+|nor\s+|and\s+)?|\s+(?:or|nor|and)\s+)"
    listed = rf"(?:{sep}(?:an? )?(?:{term})\w*)*"
    item = rf"(?:[^\s,;]+\s+){{0,2}}[^\s,;]+{sep}"  # one coordinated item of at most 3 words
    word = rf"(?!{TURN.pattern})\S+"  # a negation's reach stops at "but", "except", "yet" ...
    near_ = rf"(?:\s+{word}){{0,5}}?\s+\W?(?:an? )?(?:[\w-]+\.)*"
    in_list = rf"(?:\s+{word}){{0,2}}?\s+(?:{item})+(?:[^\s,;]+\s+){{0,2}}?(?:[\w-]+\.)*"
    t = re.sub(rf"\b{NEG_WORD}\b(?:{near_}|{in_list})(?:{term}){listed}", " ", t)
    return re.search(term, t) is not None


SENTENCE = re.compile(r";\s|(?<=[.!?])\s+|(?<=[.!?]\*\*)\s+|\s—\s")


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


@functools.lru_cache(maxsize=1)
def head_resolves() -> bool:
    return bool(git_out("rev-parse", "--verify", "--quiet", f"{HEAD}^{{commit}}").strip())


def head_ok() -> bool:
    """`origin/main` resolves (the self-test's BROKEN lever says it does not)."""
    return "head" not in BROKEN and head_resolves()


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


def non_latin(c: str) -> bool:
    """A letter outside the Latin script (a Cyrillic or Greek homoglyph reads as a Latin word)."""
    return unicodedata.category(c).startswith("L") and "LATIN" not in unicodedata.name(c, "")


def g_charset(t: Texts) -> list[Finding]:
    """No compatibility character NFKC would fold beyond CHARSET_ALLOW, no invisible character
    or tab (NFKC keeps them), no letter outside the Latin script (raw or as an HTML entity), no
    CR, no trailing whitespace."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            odd = [
                c
                for c in line
                if c in INVISIBLE
                or (c not in CHARSET_ALLOW and unicodedata.normalize("NFKC", c) != c)
            ]
            odd += [c for c in html.unescape(line) if non_latin(c)]
            whys = [f"U+{ord(c):04X}" for c in odd[:1]]
            whys += ["a CR"] if "\r" in line else []
            whys += ["trailing whitespace"] if line != line.rstrip() else []
            if whys:
                bad.append(F("G-CHARSET", f"{doc}:{i} {', '.join(whys)}", doc, h2_at(text, i)))
    return bad


def g_cells(t: Texts) -> list[Finding]:
    """Every table row has its header's cell count (an escaped pipe is not a separator), and
    every table has its rule line under the header (without one the rows render as text)."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        width, row = 0, 0
        for i, ln in enumerate(text.split("\n"), 1):
            if not re.match(r"^ {0,3}\|", ln):
                width, row = 0, 0
                continue
            row += 1
            if row == 2 and not is_rule(ln.strip()):
                msg = f"{doc}:{i} a table with no rule line under its header"
                bad.append(F("G-CELLS", msg, doc, h2_at(text, i)))
            n = len(split_row(ln))
            if width == 0:
                width = n
            elif n != width:
                msg = f"{doc}:{i} {n} cells, its header has {width}"
                bad.append(F("G-CELLS", msg, doc, h2_at(text, i)))
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


def g_budget(t: Texts) -> list[Finding]:
    """BQ-1: the spec within its line budget, the hand-off within its own."""
    bad: list[Finding] = []
    for doc, text, cap in (("spec", t.spec, SPEC_LINE_BUDGET), ("hand", t.hand, HAND_LINE_BUDGET)):
        n = text.count("\n") + (0 if text.endswith("\n") else 1)
        if n > cap:
            last = h2_at(text, len(text.split("\n")))
            bad.append(F("G-BUDGET", f"the {doc} has {n} lines > {cap}", doc, last))
    return bad


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
    if PIN_UNITS_OVERRIDE and pinned is None:
        pinned = PIN_UNITS_OVERRIDE[-1]
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


def damaged_pins() -> Callable[[], None]:
    """The pins file with its last unit cut and its header unchanged."""
    text = pin_file_text() or ""
    PIN_TEXT_OVERRIDE.append(text.rstrip("\n").rsplit("\n", 1)[0] + "\n")

    def undo() -> None:
        PIN_TEXT_OVERRIDE.pop()

    return undo


def ascii_line(s: str) -> str:
    """The self-test report is ASCII: anything else is escaped."""
    return s.encode("ascii", "backslashreplace").decode("ascii")


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def write_text(path: Path, text: str) -> None:
    """Every writer opens its file with newline="\\n"."""
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------- texts and units

MUTATION_HEAD = "15.2 The mutation list"  # its rows describe the violations they plant
NEVER_HEAD = "11.2 The never-list"  # its bullets name what is forbidden (G-NEVER requires them)
NEEDS_HEAD = "§G Dry-run needs"  # the hand-off's need lists: labels and pointers, not claims
# cells that report another text's words, not this ticket's claims: (doc, head, column)
REPORTED = (
    ("hand", "Table A", 3),
    ("spec", "16.1 Contradictions", 1),
    ("hand", "§D The delta", 1),
)


def lex_units(doc: str, text: str) -> list[LexUnit]:
    """Every unit a lexicon gate reads, rendered: each table row (cells joined by " | "), each
    bullet or numbered item, each paragraph and each heading, with its `##` section. Skipped: the
    spec's §15.2 rows (they name the violations they plant), §11.2's bullets (the never-list
    names what is forbidden), the hand-off's §G need lists; and the REPORTED cells (another
    text's words: Table A's Old cells, the C-rows' conflicting texts, §D's shipped cells)."""
    out: list[LexUnit] = []
    lines = text.split("\n")
    fence = fenced(lines)
    sec, skip, drop = "(top)", False, -1
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
            skip = (doc == "spec" and m[2].startswith((MUTATION_HEAD, NEVER_HEAD))) or (
                doc == "hand" and m[2].startswith(NEEDS_HEAD)
            )
            drop = next(
                (c for d, h, c in REPORTED if d == doc and m[2].startswith(h)),
                -1 if len(m[1]) <= 3 else drop,
            )
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
                if 0 <= drop < len(cells):
                    cells = cells[:drop] + cells[drop + 1 :]
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


# ---------------------------------------------------------------------------- the ticket texts


@functools.lru_cache(maxsize=1)
def tickets() -> dict[str, str]:
    """Every ticket body in E09J at the base, by key."""
    data = json.loads(at_base(CITE_FILES["E09J"]))
    out = {
        str(item.get("key")): str(item.get("body", ""))
        for item in data
        if isinstance(item, dict) and "key" in item
    }
    if TICKET_KEY not in out:
        raise SystemExit("FAIL parse: the ticket body is missing in E09J")
    return out


def ticket() -> str:
    return tickets()[TICKET_KEY]


# ---------------------------------------------------------------------------- `22` as text


def op_responses(op_line: int) -> tuple[str, ...]:
    """The status codes an operation declares: the `"NNN":` keys of its `responses:` block, read
    as text from the operation's `operationId` line at the base."""
    lines = at_base(plan_rel("22") or "").split("\n")
    out: list[str] = []
    i = op_line - 1
    while i < len(lines) and "responses:" not in lines[i]:
        i += 1
    indent = len(lines[i]) - len(lines[i].lstrip())
    for ln in lines[i + 1 :]:
        if ln.strip() and len(ln) - len(ln.lstrip()) <= indent:
            break
        m = re.match(r'^\s*"(\d{3})":', ln)
        if m and len(ln) - len(ln.lstrip()) == indent + 2:
            out.append(m[1])
    return tuple(out)


def change_password_codes() -> tuple[str, ...]:
    return op_responses(grab_line("22", "operationId: authChangePassword"))


def redeem_codes() -> tuple[str, ...]:
    return op_responses(grab_line("22", "operationId: redeemInvite"))


def grab_line(cid: str, frag: str) -> int:
    rel = cite_path(cid)
    lines = at_base(rel or "").split("\n")
    for i, ln in enumerate(lines, 1):
        if frag in ln:
            return i
    raise SystemExit(f"FAIL parse: {frag!r} not in {cid} at {BASE}")


# ---------------------------------------------------------------------------- tokens


THEME_HEX: dict[tuple[str, str], str] = {}


def theme_hex(theme: str, name: str) -> str:
    key = (theme, name)
    if key not in THEME_HEX:
        THEME_HEX[key] = hex_of(load_theme(theme), name)
    return THEME_HEX[key]


def themes_json_names() -> list[str]:
    data = json.loads(at_base(f"{DS_SRC_REL}/themes.json"))
    return [str(t["name"]) for t in data["themes"]]


# ---------------------------------------------------------------------------- CVD (G-CVD)

# The constants of CVD:49-93 (Brettel / Vienot protan and deutan; Machado 2009 tritan). The tool
# keeps its own copy and G-CVD FAILs when the file at the base says otherwise.
RGB_TO_LMS: tuple[float, ...] = (
    17.8824,
    43.5161,
    4.11935,
    3.45565,
    27.1554,
    3.86714,
    0.0299566,
    0.184309,
    1.46709,
)
LMS_TO_RGB: tuple[float, ...] = (
    0.0809444479,
    -0.130504409,
    0.116721066,
    -0.0102485335,
    0.0540193266,
    -0.113614708,
    -0.000365296938,
    -0.00412161469,
    0.693511405,
)
PROTAN: tuple[float, ...] = (0.0, 2.02344, -2.52581, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
DEUTAN: tuple[float, ...] = (1.0, 0.0, 0.0, 0.494207, 0.0, 1.24827, 0.0, 0.0, 1.0)
TRITAN: tuple[float, ...] = (
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
DEFICIENCIES = ("protanopia", "deuteranopia", "tritanopia", "greyscale")


def cvd_constants_at_base() -> dict[str, tuple[float, ...]]:
    """The five constant tables of the CVD script, parsed as text (ast literals; nothing runs)."""
    if CVD_OVERRIDE:
        return CVD_OVERRIDE[-1]
    src = at_base(CITE_FILES["CVD"])
    tree = ast.parse(src)
    found: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("RGB_TO_LMS", "LMS_TO_RGB", "PROJECTIONS", "TRITAN_MACHADO"):
                found[name] = ast.literal_eval(node.value)

    def flat(v: object) -> tuple[float, ...]:
        if isinstance(v, tuple) and v and isinstance(v[0], tuple):
            return tuple(float(x) for row in v for x in row)
        return tuple(float(x) for x in v) if isinstance(v, tuple) else ()

    proj = found.get("PROJECTIONS")
    proj_d = proj if isinstance(proj, dict) else {}
    return {
        "RGB_TO_LMS": flat(found.get("RGB_TO_LMS")),
        "LMS_TO_RGB": flat(found.get("LMS_TO_RGB")),
        "protanopia": flat(proj_d.get("protanopia")),
        "deuteranopia": flat(proj_d.get("deuteranopia")),
        "tritanopia": flat(found.get("TRITAN_MACHADO")),
    }


def own_cvd_constants() -> dict[str, tuple[float, ...]]:
    return {
        "RGB_TO_LMS": RGB_TO_LMS,
        "LMS_TO_RGB": LMS_TO_RGB,
        "protanopia": PROTAN,
        "deuteranopia": DEUTAN,
        "tritanopia": TRITAN,
    }


def matvec(m: tuple[float, ...], v: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
        m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
        m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
    )


def linear_to_srgb(c: float) -> float:
    s = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return max(0.0, min(1.0, s)) * 255.0


def simulate(hex6: str, kind: str) -> str:
    """CVD:96-110's simulation (same constants), or greyscale by relative luminance."""
    r, g, b = rgb(hex6)
    lin = (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b))
    if kind == "greyscale":
        y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
        out = (y, y, y)
    elif kind == "tritanopia":
        out = matvec(TRITAN, lin)
    else:
        lms = matvec(RGB_TO_LMS, lin)
        out = matvec(LMS_TO_RGB, matvec(PROTAN if kind == "protanopia" else DEUTAN, lms))
    return "#" + "".join(f"{max(0, min(255, round(linear_to_srgb(c)))):02X}" for c in out)


# ---------------------------------------------------------------------------- the spec's tables

BOARDS_HEAD = "0. Status"
FRAME_HEAD = "15.1 The frame register"
FR_COLS = ("Frame", "Board", "Theme", "State", "Components", "Copy", "Tokens", "Status")
RULES_HEAD = "4.1 The rules"
METER_HEAD = "4.3 The meter"
TRUTH_HEAD = "4.4 The truth table"
PAIRS_HEAD = "13.2 Contrast"
BIND_HEAD = "13.1 Bindings"
REASONS_HEAD = "3.1 The reasons"
HOSTS_HEAD = "2.1 The hosts"
ERR_HEAD = "6.1 The signed-in hosts"
DECK_HEAD = "11.1 The strings"
CROW_HEAD = "16.1 Contradictions"
GROW_HEAD = "16.2 The G-ledger"
QROW_HEAD = "16.3 Open questions"
WALK_HEAD = "17.1 The story-role dry run"
WALKTHROUGH_HEAD = "§E Owner walkthrough"
TABLE_A_HEAD = "Table A"


def bars() -> dict[str, float]:
    """The contrast bars, read from `05` at the base (text 1.4.3, non-text 1.4.11)."""
    v = cite_values()
    return {"text": float(v["CITE:bar.text"]), "non-text": float(v["CITE:bar.ui"])}


def rows_of(text: str, head: str) -> list[list[str]]:
    return table_rows(section(text, head))


def board_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, BOARDS_HEAD) if re.fullmatch(r"\d{2}", r[0])]


def is_twin(row: list[str]) -> bool:
    return len(row) > 2 and re.search(r"\btwin of \d{2}\b", row[2]) is not None


def frames(spec: str) -> list[dict[str, str]]:
    out = []
    for r in rows_of(spec, FRAME_HEAD):
        if len(r) == len(FR_COLS) and r[0].startswith("`"):
            out.append(dict(zip(FR_COLS, r, strict=True)))
    return out


def pair_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, PAIRS_HEAD) if re.match(r"P-\d+", r[0])]


def rule_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, RULES_HEAD) if re.fullmatch(r"\d", r[0])]


def meter_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, METER_HEAD) if re.fullmatch(r"\d", r[0])]


def rules_14() -> list[str]:
    """`14`'s policy rules, the comma list of SCR-004's Validation line before "Messages"."""
    return grab(r"\*\*Validation:\*\* ([^.]*)\.", base_line("14", 209), "rules").split(", ")


def d02_states() -> int:
    line = base_line("D02", 63)
    return len(split_row(line)[1].split(" · "))


def denylist_count() -> int:
    lines = at_base(CITE_FILES["INV"]).split("\n")
    start = grab_line("INV", "_COMMON_PASSWORDS = frozenset(")
    n = 0
    for ln in lines[start:]:
        if ln.strip() == ")":
            break
        n += len(re.findall(r'"[^"]*",', ln))
    return n


def score_max() -> int:
    return int(grab(r"score: (?:\d\|)+(\d)`", base_line("15", 2568), "CMP-202's score"))


def client_items(spec: str) -> int:
    return sum(1 for r in rule_rows(spec) if len(r) > 3 and r[3].startswith("client"))


def meter_word(spec: str, score: int, length_met: bool) -> str:
    words = {int(r[0]): r[1] for r in meter_rows(spec) if len(r) > 1}
    if not length_met:
        return "Weak"
    return words.get(score, "?")


def truth_rows(spec: str) -> list[tuple[tuple[bool, ...], int, str]]:
    """Every combination of the client items (item 1 first) and the scores, with the word."""
    k = client_items(spec)
    out = []
    for combo in itertools.product((False, True), repeat=k):
        for score in range(score_max() + 1):
            out.append((combo, score, meter_word(spec, score, combo[0] if combo else True)))
    return out


def deck(spec: str) -> dict[str, list[str]]:
    return {r[0]: r for r in rows_of(spec, DECK_HEAD) if re.fullmatch(r"W-\d+", r[0])}


def deck_strings(spec: str) -> dict[str, str]:
    return {k: r[2] for k, r in deck(spec).items() if len(r) > 2}


def unq(cell: str) -> list[str]:
    """The quoted segments of a deck String cell."""
    return [q[1:-1] for q in re.findall(r'"[^"]*"', cell)]


# ---------------------------------------------------------------------------- computed values


def cite_values() -> Values:
    return {f"CITE:{k}": grab(p, base_line(c, n), k) for k, (c, n, p) in CITE_VALUES.items()}


PAIR_THEMES = ("dark", "light", "hc")


def contrast_grid(spec: str) -> dict[str, dict[str, float]]:
    """pair id -> theme -> ratio, for every §13.2 row (foreground, background tokens)."""
    out: dict[str, dict[str, float]] = {}
    for r in pair_rows(spec):
        if len(r) < 3:
            continue
        pid = r[0].split(" ")[0].lower().replace("-", "")
        fg, bg = r[1].strip("`"), r[2].strip("`")
        try:
            out[pid] = {t: contrast(theme_hex(t, fg), theme_hex(t, bg)) for t in PAIR_THEMES}
        except SystemExit:
            continue
    return out


def colour_values(spec: str) -> Values:
    v: Values = {}
    for pid, row in contrast_grid(spec).items():
        for t, r in row.items():
            v[f"CONTRAST:{pid}.{t}"] = show_ratio(r).removesuffix(":1") + ":1"
    return v


def count_values(spec: str) -> Values:
    rows = board_rows(spec)
    twins = [r for r in rows if is_twin(r)]
    return {
        "COUNT:boards": str(len(rows)),
        "COUNT:boards.twins": str(len(twins)),
        "COUNT:boards.dark": str(len(rows) - len(twins)),
        "COUNT:frames": str(len(frames(spec))),
        "COUNT:rules": str(len(rule_rows(spec))),
        "COUNT:states.d02": str(d02_states()),
        "COUNT:reasons": str(len(rows_of(spec, REASONS_HEAD))),
        "COUNT:denylist": str(denylist_count()),
        "COUNT:client.items": str(client_items(spec)),
        "COUNT:scores": str(score_max() + 1),
        "COUNT:truth.rows": str(len(truth_rows(spec))),
        "COUNT:fields": str(section(spec, "2.2 Anatomy").count("CMP-201")),
        "COUNT:hosts": str(
            len(rows_of(spec, HOSTS_HEAD)[0]) - 1 if rows_of(spec, HOSTS_HEAD) else 0
        ),
        "COUNT:rules.14": str(len(rules_14())),
        "COUNT:themes": str(len(themes_json_names())),
        "COUNT:reasons.14": str(
            len(grab(r"\(([^)]*)\)\.$", base_line("14", 206), "reasons").split(", "))
        ),
        "COUNT:causes": str(
            len(grab(r"\(first ([^)]*)\)", base_line("12", 52), "causes").split(", or "))
        ),
        "COUNT:checklist.14": str(base_line("14", 214).count("[ ]")),
        "COUNT:items.shipped": str(
            sum("<li>" in ln for ln in at_base(CITE_FILES["CPS"]).split("\n"))
        ),
        "COUNT:cvd.checks": str(len(pair_rows(spec)) * len(PAIR_THEMES) * len(DEFICIENCIES)),
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
    v |= colour_values(spec)
    extra = {
        "change_password_codes": list(change_password_codes()),
        "redeem_invite_codes": list(redeem_codes()),
        "truth_table": [[list(c), s, w] for c, s, w in truth_rows(spec)],
        "contrast": {
            p: {t: round(r, 3) for t, r in row.items()} for p, row in contrast_grid(spec).items()
        },
        "cvd_constants_match": cvd_constants_at_base() == own_cvd_constants(),
    }
    return tuple(sorted(v.items())), json.dumps(extra, ensure_ascii=False)


def compute(spec: str, hand: str) -> tuple[Values, dict[str, object]]:
    items, extra = compute_cached(spec, hand)
    return dict(items), json.loads(extra)


# ---------------------------------------------------------------------------- anchors

# copy columns a figure may sit in: (section, columns) — Table A's Old and New cells, the copy
# deck's String column, the mutation rows, the dry-run counts, the tick-box numbers
COPY_CELLS = (
    ("Table A", (3, 4)),
    ("11.1 The strings", (2,)),
    ("15.2 The mutation", (1, 2)),
    ("17.1 The story-role", (2, 3, 4)),
    ("4.3 The meter", (0,)),
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
    work = re.sub(
        r"\(#\d+\)|#\d+|\b\d{4}-\d{2}-\d{2}\b|\b[A-Z][A-Za-z0-9]*-\d+(?:\.\d+)?\b|\(\d\)",
        " ",
        work,
    )
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


# ---------------------------------------------------------------------------- cites (G-CITE,
# G-VERSION by content)


def cite_refs(line: str) -> list[tuple[str, int, int]]:
    """(cite id, first, last) for every cite on a rendered line."""
    out: list[tuple[str, int, int]] = []
    for m in CITE_GROUP.finditer(strip_comments(line)):
        cid = m["a"] or m["b"]
        if m["a"] and not (re.fullmatch(r"\d{2}", cid) or "/" in cid or cid in CITE_FILES):
            continue
        refs = [m["first"], *re.findall(r":(\d+(?:[–-]\d+)?)", m["more"])]
        for ref in refs:
            parts = [int(x) for x in re.split(r"[–-]", ref)]
            out.append((cid, parts[0], parts[-1]))
    return out


def block_at(lines: list[str], block: list[str]) -> bool:
    """`block` stands, in order and contiguous, somewhere in `lines`."""
    return block_count(lines, block, 1) >= 1


def block_count(lines: list[str], block: list[str], stop: int = 2) -> int:
    """How many times `block` stands in `lines` (counting stops at `stop`)."""
    n, first, hits = len(block), block[0], 0
    for i in range(len(lines) - n + 1):
        if lines[i] == first and lines[i : i + n] == block:
            hits += 1
            if hits >= stop:
                break
    return hits


def unique_block(base: list[str], a: int, b: int) -> list[str]:
    """The cited lines `a`..`b`, widened by one line of context on each side until the block is
    unique at the base: a cited line whose text repeats elsewhere is then checked where it
    stood, not wherever a copy survives (G-VERSION)."""
    lo, hi = a - 1, b
    while block_count(base, base[lo:hi]) > 1 and (lo > 0 or hi < len(base)):
        lo, hi = max(0, lo - 1), min(len(base), hi + 1)
    return base[lo:hi]


@functools.lru_cache(maxsize=1024)
def cited_block(rel: str, a: int, b: int) -> tuple[str, ...]:
    """unique_block at the base, cached (the base never changes within a run)."""
    return tuple(unique_block((git_show(BASE, rel) or "").split("\n"), a, b))


def cite_findings(docs: dict[str, str], fetch: Fetch) -> tuple[list[Finding], int]:
    """G-CITE (every line at the base, the range's ends non-blank) and G-VERSION (each cited
    range stands, by content, at `origin/main`; an unresolvable `origin/main` FAILs)."""
    del fetch
    fails: list[Finding] = []
    done: set[tuple[str, int, int]] = set()
    if not head_ok():
        fails.append(("G-VERSION", f"{HEAD} does not resolve: drift is unread", None, None))
    for doc, text in docs.items():
        for li, line in enumerate(text.split("\n"), 1):
            sec = h2_at(text, li)
            for cid, a, b in cite_refs(line):
                rel = cite_path(cid)
                base_t = git_show(BASE, rel) if rel else None
                if rel is None or base_t is None:
                    fails.append(("G-CITE", f"`{cid}`:{a} no such file", doc, sec))
                    continue
                if (cid, a, b) in done:
                    continue
                done.add((cid, a, b))
                base = base_t.split("\n")
                if b < a or a < 1 or b > len(base) or not base[a - 1].strip():
                    fails.append(("G-CITE", f"`{cid}`:{a}–{b} not a range at {BASE}", doc, sec))
                    continue
                if not base[b - 1].strip():
                    fails.append(("G-CITE", f"`{cid}`:{b} is blank at {BASE}", doc, sec))
                    continue
                if not head_ok():
                    continue
                head_t = git_fetch_head(rel)
                if head_t is None or not block_at(head_t.split("\n"), list(cited_block(rel, a, b))):
                    msg = f"`{cid}`:{a}–{b} edited at {HEAD}: re-read and re-point the cite"
                    fails.append(("G-VERSION", msg, doc, sec))
    for cid, n, frag in CITED:
        rel = cite_path(cid)
        bt = git_show(BASE, rel) if rel else None
        base = bt.split("\n") if bt is not None else []
        if n > len(base) or frag not in base[n - 1]:
            hits = [i + 1 for i, ln in enumerate(base) if frag in ln]
            msg = f'`{cid}`:{n} "{frag[:40]}" not on the line (found {hits[:4]})'
            fails.append(("G-CITE", msg, None, None))
    return fails, len(done) + len(CITED)


# ---------------------------------------------------------------------------- G-QUOTE

# names this spec PROPOSES (no merged source holds them); each must stand beside "PROPOSED"
PROPOSED_NAMES = frozenset({"password_changed"})
SNAKE = re.compile(r"(?<![\w.$/{-])((?:[a-z][a-z0-9]*\.)?[a-z][a-z0-9]*_[a-z0-9_]+(?:\.\*)?)\b")
QUOTE_MIN = 12
# G-QUOTE skips the rows other gates own: Table A (G-AROW), the deck (G-DECK), the mutation rows
QUOTE_SKIP = ("Table A", DECK_HEAD, MUTATION_HEAD)
CORE = ("14", "15", "22", "D09", "ACT", "INV", "INVR", "CPS", "API", "D08", "D03")


def template(s: str) -> str:
    """A W-n string as a pattern: each `{slot}` matches one to four words."""
    parts = re.split(r"\{[^{}]*\}", s)
    return r"\S+(?: \S+){0,3}?".join(re.escape(p) for p in parts)


@functools.lru_cache(maxsize=4)
def deck_patterns(spec: str) -> tuple[re.Pattern[str], ...]:
    pats: list[re.Pattern[str]] = []
    for cell in deck_strings(spec).values():
        for s in unq(cell):
            pats.append(re.compile(template(s)))
    return tuple(pats)


def loose(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("’", "'").replace("...", "…")
    return " ".join(s.split()).lower().rstrip(".")


@functools.lru_cache(maxsize=256)
def source_text(cid: str) -> str:
    """One source at the base ("" for the ticket key `T`), escaped quotes unescaped."""
    if cid == "T":
        return ticket().replace('\\"', '"')
    rel = cite_path(cid)
    return (git_show(BASE, rel) or "").replace('\\"', '"') if rel else ""


@functools.lru_cache(maxsize=256)
def loose_source(cid: str) -> str:
    return loose(source_text(cid))


class Pool:
    """The ticket, the core sources and the sources a line cites, searched file by file (one
    cached text per source, never a joined copy per cite set)."""

    def __init__(self, cids: tuple[str, ...]) -> None:
        self.cids = ("T", *CORE, *cids)

    def __contains__(self, s: str) -> bool:
        return any(s in source_text(c) for c in self.cids)

    def loose_has(self, s: str) -> bool:
        return any(s in loose_source(c) for c in self.cids)


def g_quote(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    pats = deck_patterns(t.spec)
    img = {loose(s) for s in D02_IMG}
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
            pool = Pool(cids)
            rendered = strip_comments(line)
            for c in CODE.finditer(rendered):
                for m in SNAKE.finditer(c[0][1:-1]):
                    name = m[1]
                    stem = name.removesuffix(".*")
                    if name in PROPOSED_NAMES or stem in pool:
                        continue
                    bad.append(F("G-QUOTE", f"{doc}:{i} `{name}` is in no cited text", doc, sec))
            for q in QUOTED.finditer(CODE.sub(" ", rendered)):
                s = q[0][1:-1]
                if len(s) < QUOTE_MIN or pool.loose_has(loose(s)) or s == OWNER_PENDING:
                    continue
                if any(loose(s) in x for x in img) or any(p.fullmatch(s) for p in pats):
                    continue
                if any(loose(s) in loose(d) for d in deck_strings(t.spec).values()):
                    continue
                bad.append(F("G-QUOTE", f"{doc}:{i} {s[:50]!r} is neither cited nor W-n", doc, sec))
    return bad


# ---------------------------------------------------------------------------- generic text gates


def g_penpot(t: Texts) -> list[Finding]:
    """S-3: no host, link or URL in either doc; the Penpot page by name (and id in PR 2)."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if URL.search(strip_comments(line)):
                bad.append(F("G-PENPOT", f"{doc}:{i} a URL or host", doc, h2_at(text, i)))
    if "page `E09-D05 SCR-004 password`" not in section(t.spec, BOARDS_HEAD):
        bad.append(F("G-PENPOT", "§0 does not name the page", "spec", spec_sec(t, BOARDS_HEAD)))
    return bad


def g_comment(t: Texts) -> list[Finding]:
    """No `[//]: #` comment and no link-reference definition: hidden text the gates cannot see."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if re.match(r"^ {0,3}\[[^\]]*\]:\s", line):
                bad.append(F("G-COMMENT", f"{doc}:{i} a link-reference line", doc, h2_at(text, i)))
    return bad


def shannon(s: str) -> float:
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


KEYISH = re.compile(
    r'"([\w.-]*(?:key|token|secret|passw\w*|pwd|auth|credential|api)[\w.-]*)"'
    r'\s*:\s*"([^"\n]{12,})"',
    re.IGNORECASE,
)
RECOVERY_SHAPE = re.compile(r"\b(?=[a-z]*\d)[a-z0-9]{5}-(?=[a-z]*\d)[a-z0-9]{5}\b")


def g_entropy(t: Texts) -> list[Finding]:
    """No high-entropy `"key": "<value>"` string and no recovery-code shape in the four files."""
    bad: list[Finding] = []
    texts = {"spec": t.spec, "hand": t.hand}
    for rel in (TOOL_REL, RULED_PIN_TXT):
        p = ROOT / rel
        texts[rel] = p.read_text(encoding="utf-8") if p.exists() else ""
    for doc, text in texts.items():
        for i, line in enumerate(text.split("\n"), 1):
            for m in KEYISH.finditer(line):
                v = m[2]
                if " " not in v and "/" not in v and shannon(v) > 3.5:
                    msg = f"{doc}:{i} a high-entropy value for {m[1]!r}"
                    bad.append(F("G-ENTROPY", msg, doc if doc in ("spec", "hand") else None, None))
            if RECOVERY_SHAPE.search(line) and doc in ("spec", "hand"):
                bad.append(F("G-ENTROPY", f"{doc}:{i} a recovery-code shape", doc, h2_at(text, i)))
    return bad


SESSION_CLAIM = (
    r"\b(?:session|walkthrough|meeting|interview|test)s?\b(?:\s+\S+){0,2}?\s+"
    r"(?:was |were |has been |is )?(?:held|ran|recorded|conducted|completed|happened)\b"
    r"|\btook place\b|\bparticipants?\b|\battendees?\b|\bwalked through\b|\bthe user said\b"
)


def g_session(t: Texts) -> list[Finding]:
    """Rider (a): no session, participant, timing or quote is claimed."""
    units = [u for u in lex(t) if not u.text.startswith("**No session took place")]
    return as_findings("G-SESSION", "a session held", claims(units, SESSION_CLAIM))


def g_marked(t: Texts) -> list[Finding]:
    """S-9: every PROPOSED name stands beside "PROPOSED" (its line or its heading)."""
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


def g_named(t: Texts) -> list[Finding]:
    """Rider (c): #2110, #2099, #190, #193, #194 and #291 are named only: no clause naming one
    quotes it or pins a sha beside it."""
    bad: list[Finding] = []
    for u in lex(t):
        for c in clauses(u.text):
            if not any(re.search(rf"{re.escape(n)}(?!\d)", c) for n in NAMED_ONLY):
                continue
            own = [loose(d) for d in deck_strings(t.spec).values()]
            quoted = [
                q
                for q in QUOTED.findall(CODE.sub(" ", c))
                if len(q) - 2 >= QUOTE_MIN and not any(loose(q[1:-1]) in d for d in own)
            ]
            if quoted or re.search(r"`[0-9a-f]{10}`", c):
                bad.append(F("G-NAMED", f"a named-only ticket quoted: {c[:60]!r}", u.doc, u.sec))
    return bad


# ---------------------------------------------------------------------------- the ruling


def g_trace(t: Texts) -> list[Finding]:
    """The AC trace holds AC1 ... AC6 and the T rows, each with a status."""
    sec = spec_sec(t, "Acceptance-criteria trace")
    rows = rows_of(t.spec, "Acceptance-criteria trace")
    lead = [r[0].split(" ")[0] for r in rows]
    bad = [
        F("G-TRACE", f"the trace lacks {ac}", "spec", sec)
        for ac in ("AC1", "AC2", "AC3", "AC4", "AC5", "AC6", "T")
        if ac not in lead
    ]
    bad += [F("G-TRACE", f"{r[0][:30]!r} has no status", "spec", sec) for r in rows if len(r) < 3]
    return bad


RULED_NINE = ("BQ-5", "BQ-10", "BQ-11", "BQ-13", "BQ-16", "BQ-18", "BQ-19", "BQ-24", "BQ-29")
AS_WRITTEN = (
    *("BQ-9", "BQ-12", "BQ-14", "BQ-15", "BQ-17", "BQ-20", "BQ-21", "BQ-22", "BQ-23"),
    *("BQ-25", "BQ-26", "BQ-27", "BQ-28", "BQ-30", "BQ-31", "BQ-32", "BQ-34"),
)


def g_ruled(t: Texts) -> list[Finding]:
    """The RULED paragraph: the ruling and the list by id, the nine confirmations, the accepted
    list, the three owner items PROPOSED, the riders, D1 to D3; every comment id cited is one of
    RULED_IDS."""
    head = "The questions BQ-1"
    sec = spec_sec(t, head)
    body = section(t.spec, head)
    para = next((p for p in body.split("\n") if p.startswith("**RULED.**")), "")
    bad: list[Finding] = []
    if RULING_ID not in body.split("\n")[0] or BQ_LIST_ID not in body.split("\n")[0]:
        bad.append(F("G-RULED", "the heading does not name the ruling and the list", "spec", sec))
    for q in (*RULED_NINE, *AS_WRITTEN, "BQ-7", "BQ-8", "BQ-33"):
        if not re.search(rf"\b{q}\b", para):
            bad.append(F("G-RULED", f"the RULED paragraph lacks {q}", "spec", sec))
    for need in (
        OWNER_PENDING,
        "Riders (a) to (d)",
        "Deviations D1 to D3",
        "name each doc's last touch at the base (C-27)",
    ):
        if need not in para:
            bad.append(F("G-RULED", f"the RULED paragraph lacks {need!r}", "spec", sec))
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            for m in COMMENT_ID.finditer(CODE.sub(" ", strip_comments(line))):
                if m[1] not in RULED_IDS:
                    msg = f"{doc}:{i} comment id {m[1]} is not the ruling's"
                    bad.append(F("G-RULED", msg, doc, h2_at(text, i)))
    return bad


def g_owner(t: Texts) -> list[Finding]:
    """BQ-7, BQ-8, BQ-33: each owner item carries the PROPOSED marker where it is built."""
    bad: list[Finding] = []
    for head in ("3.1 The reasons", "3.2 What an owner reset"):
        line = next((ln for ln in t.spec.split("\n") if ln.startswith(f"### {head}")), "")
        if OWNER_PENDING not in line:
            msg = f"§{head[:3]} lacks the PROPOSED marker"
            bad.append(F("G-OWNER", msg, "spec", spec_sec(t, REASONS_HEAD)))
    for head, need in (
        (REASONS_HEAD, "becomes a two-way one"),
        ("3.2 What an owner reset", "does nothing against a compromised password"),
        ("18.2 Hand-offs", "the rejected alternatives are reopening E09-S01"),
    ):
        body = section(t.spec, head)
        if "**The trade-off, for the owner:**" not in body or need not in body:
            msg = f"§{head.split(' ')[0]} lacks its trade-off ({need[:30]!r})"
            bad.append(F("G-OWNER", msg, "spec", spec_sec(t, head)))
    deltas = section(t.spec, "18.2 Hand-offs")
    if "BQ-33, " + OWNER_PENDING not in deltas:
        msg = "§18.2's delta lacks BQ-33's marker"
        bad.append(F("G-OWNER", msg, "spec", spec_sec(t, "18.2 Hand-offs")))
    for q in ("Q-1", "Q-2", "Q-3"):
        row = next((r for r in rows_of(t.spec, QROW_HEAD) if r[0] == q), [])
        if OWNER_PENDING not in " | ".join(row):
            bad.append(
                F("G-OWNER", f"{q} lacks the PROPOSED marker", "spec", spec_sec(t, QROW_HEAD))
            )
    return bad


# ---------------------------------------------------------------------------- boards and frames


def g_boards(t: Texts) -> list[Finding]:
    """BQ-5, S-8: at most ten boards; twins at most a third, each a twin of a dark board; the
    ten of the ruling in order; each to draw in PR 2."""
    sec = spec_sec(t, BOARDS_HEAD)
    rows = board_rows(t.spec)
    bad: list[Finding] = []
    twins = [r for r in rows if is_twin(r)]
    if len(rows) > MAX_BOARDS or Fraction(len(twins), max(len(rows), 1)) > TWIN_SHARE:
        bad.append(F("G-BOARDS", f"{len(rows)} boards, {len(twins)} twins", "spec", sec))
    want = (
        "entry-reasons",
        "typing-checklist-meter",
        "mismatch-and-submitting",
        "server-rejections",
        "other-failures",
        "success-and-escape",
        "scr-112-password-section",
        "server-rejections-light",
        "typing-checklist-meter-hc",
        "entry-reasons-scale",
    )
    got = tuple(re.sub(r"^`E09-D05 / \d{2} |`$", "", r[1]) for r in rows if len(r) > 1)
    if got != want:
        bad.append(F("G-BOARDS", f"the boards read {got[:3]}…, not the ruling's ten", "spec", sec))
    dark = {r[0] for r in rows if not is_twin(r) and len(r) > 3 and r[3] == "dark"}
    for r in rows:
        if len(r) < 5 or r[3] not in ("dark", "light", "hc") or r[4] != "to draw (PR 2)":
            bad.append(F("G-BOARDS", f"board {r[0]}: theme or status", "spec", sec))
        m = re.search(r"\b(?:twin|passes) of (\d{2})\b", r[2] if len(r) > 2 else "")
        if is_twin(r) and (not m or m[1] not in dark):
            bad.append(F("G-BOARDS", f"board {r[0]} is not a twin of a dark board", "spec", sec))
    return bad


@functools.lru_cache(maxsize=1)
def catalogue_ids() -> frozenset[str]:
    return frozenset(re.findall(r"^### (CMP-\d{3})\b", at_base(plan_rel("15") or ""), MULTI))


TOKEN_NAME = re.compile(r"`((?:color|space|radius|elevation|type|size|opacity)\.[a-z0-9.*-]+)`")


def g_frame(t: Texts) -> list[Finding]:
    """The frame register, column by column."""
    sec = spec_sec(t, FRAME_HEAD)
    boards = {r[0]: r for r in board_rows(t.spec)}
    deckids = set(deck(t.spec))
    names = all_token_names()
    bad: list[Finding] = []
    seen: set[str] = set()
    for f in frames(t.spec):
        name = f["Frame"]
        if name in seen:
            bad.append(F("G-FRAME", f"{name} repeated", "spec", sec))
        seen.add(name)
        b = boards.get(f["Board"])
        theme = name.strip("`").split(" · ")[-1].split("-")[0]
        if b is None or len(b) < 4 or b[3] != f["Theme"] or theme != f["Theme"]:
            bad.append(F("G-FRAME", f"{name}: board {f['Board']} or theme", "spec", sec))
        for c in re.findall(r"CMP-\d{3}", f["Components"]):
            if c not in catalogue_ids():
                bad.append(F("G-FRAME", f"{name}: {c} is not in `15`", "spec", sec))
        for w in re.findall(r"W-\d+", f["Copy"]):
            if w not in deckids:
                bad.append(F("G-FRAME", f"{name}: {w} is not in §11.1", "spec", sec))
        for tok in TOKEN_NAME.findall(f["Tokens"]):
            if tok not in names:
                bad.append(F("G-FRAME", f"{name}: `{tok}` is not shipped", "spec", sec))
        if f["Status"] != "to draw":
            bad.append(F("G-FRAME", f"{name}: status {f['Status']!r}", "spec", sec))
    drawn = {f["Board"] for f in frames(t.spec)}
    for bid in boards:
        if bid not in drawn:
            bad.append(F("G-FRAME", f"board {bid} has no frame", "spec", sec))
    return bad


LOCKED_LEADS = ("D02", "D03", "D04", "D06", "D08", "D09", "S03")


def g_locked(t: Texts) -> list[Finding]:
    """BQ-2: the locked inputs, one row per merged parent, in order."""
    rows = rows_of(t.spec, "1.3 Locked inputs")
    got = tuple(r[0].split(" ")[0] for r in rows)
    if got != LOCKED_LEADS:
        return [F("G-LOCKED", f"§1.3 reads {got}", "spec", spec_sec(t, "1.3 Locked inputs"))]
    return []


# ---------------------------------------------------------------------------- the form (BQ-9 ...)


def g_hosts(t: Texts) -> list[Finding]:
    """BQ-9, BQ-10: one form, three hosts; the operations and the current-password row."""
    sec = spec_sec(t, HOSTS_HEAD)
    rows = {r[0]: r[1:] for r in rows_of(t.spec, HOSTS_HEAD)}
    bad: list[Finding] = []
    want = {
        "Operation": ("`redeemInvite`", "`PUT /auth/password`", "`PUT /auth/password`"),
        "Current password": ("no", "yes", "yes"),
    }
    for lead, cells in want.items():
        got = rows.get(lead, [])
        for i, w in enumerate(cells):
            if len(got) <= i or not got[i].startswith(w):
                bad.append(F("G-HOSTS", f"{lead}: column {i + 1} is not {w}", "spec", sec))
    esc = rows.get("Escape", [])
    if len(esc) < 3 or not esc[1].startswith("Sign out") or not esc[2].startswith("Cancel"):
        bad.append(F("G-HOSTS", "the escapes are not the ruling's", "spec", sec))
    bad += as_findings(
        "G-HOSTS",
        "a second screen or a missing current field",
        claims(
            lex(t),
            r"\b(?:two (?:screens|components)|separate (?:screen|component)s?"
            r"|no current[- ]password field on the forced page|exactly two ways)\b",
            unless=r"\bt tech\b",
        ),
    )
    return bad


def g_reasons(t: Texts) -> list[Finding]:
    """BQ-7 (PROPOSED): two reasons drawn; aged out is not; no third variant drawn."""
    sec = spec_sec(t, REASONS_HEAD)
    rows = rows_of(t.spec, REASONS_HEAD)
    bad: list[Finding] = []
    if [r[0] for r in rows] != ["New account", "Owner reset"]:
        bad.append(F("G-REASONS", f"§3.1 rows {[r[0] for r in rows]}", "spec", sec))
    if "**Aged out is not drawn:**" not in section(t.spec, REASONS_HEAD):
        bad.append(F("G-REASONS", "§3.1 lacks the aged-out sentence", "spec", sec))
    a1 = " ".join(a_rows(t.hand).get("A-1", [])[4:5])
    if "a new user sets the password in the SCR-017 embedded step" not in a1 or re.search(
        r"new user (?:via|through|on) the invite", a1
    ):
        bad.append(F("G-REASONS", "A-1's trigger is not BQ-9's", "hand", h2_of(t.hand, "§C")))
    bad += as_findings(
        "G-REASONS",
        "an aged-out reason drawn",
        claims(
            lex(t),
            r"\b(?:aged[- ]out|password age|periodic rotation|expired password)\b",
            near=r"\b(?:draw|drawn|variant|reason|explanation|frame|show)",
            unless=r"\b(?:not drawn|dropped|forbids|waive|c-1\b|q-1\b|t context|t dod)",
        ),
    )
    return bad


def g_reset(t: Texts) -> list[Finding]:
    """BQ-8 (PROPOSED): the reset marks must-change and keeps the password; the trade-off."""
    body = norm_text(section(t.spec, "3.2 What an owner reset"))
    sec = spec_sec(t, "3.2 What an owner reset")
    bad = [
        F("G-RESET", f"§3.2 lacks {n!r}", "spec", sec)
        for n in (
            "marks the existing credential must-change and neither clears nor sets the password",
            "does nothing against a compromised password",
            "G-5",
        )
        if norm_text(n) not in body
    ]
    for wid, cell in deck_strings(t.spec).items():
        if re.search(
            r"\b(?:was|were|has been|have been|got) (?:\w+ )?reset\b", cell, re.IGNORECASE
        ):
            msg = f"{wid} says the password was reset, which §3.2 says it is not"
            bad.append(F("G-RESET", msg, "spec", spec_sec(t, DECK_HEAD)))
    bad += as_findings(
        "G-RESET",
        "a reset that sets or clears the password",
        claims(
            lex(t),
            r"\b(?:temporary password|one-time (?:password|link)|owner (?:sets|chooses|types)"
            r"|reset (?:clears|sets|issues))\b",
            unless=r"\bneither\b",
        ),
    )
    return bad


def g_order(t: Texts) -> list[Finding]:
    """BQ-20: the second factor first; the re-check; no code on the change; a late step-up."""
    return require(
        "G-ORDER",
        "3.3 The order of the gates",
        (
            "The second factor first.",
            "goes to SCR-004 while the must-change state holds",
            "No code on the change.",
            "a late change under S-14, no redraw",
        ),
    )(t)


def g_rules(t: Texts) -> list[Finding]:
    """BQ-11: `14`'s four rules in its order plus the identity item; who evaluates each; code
    points; no complexity item."""
    sec = spec_sec(t, RULES_HEAD)
    rows = rule_rows(t.spec)
    bad: list[Finding] = []
    want = (
        ("1", "W-1", "client, then server"),
        ("2", "W-2", "server only"),
        ("3", "W-3", "server only"),
        ("4", "W-4", "client only"),
        ("5", "W-5", "client on signed-in hosts; server on the invite step"),
    )
    got = tuple((r[0], r[1], r[3]) for r in rows if len(r) > 3)
    if got != want:
        bad.append(F("G-RULES", f"§4.1 reads {got[:2]}…, not the ruled five", "spec", sec))
    for r in rows:
        if len(r) > 4 and r[3] == "server only" and r[4] != "checked when you submit":
            bad.append(F("G-RULES", f"item {r[0]} claims a state before submit", "spec", sec))
    if "counted in Unicode code points" not in section(t.spec, RULES_HEAD):
        bad.append(F("G-RULES", "§4.1 lacks the code-point count", "spec", sec))
    for n in ("**Item 5's predicate is the server's**", "nor the email's local part"):
        if n not in section(t.spec, RULES_HEAD):
            bad.append(F("G-RULES", f"§4.1 lacks {n!r}", "spec", sec))
    bad += as_findings(
        "G-RULES",
        "a complexity item or a UTF-16 count",
        claims(
            lex(t),
            r"\b(?:complexity|character class(?:es)?|uppercase|a digit|a symbol"
            r"|utf-16 (?:length|count)"
            r"|\.length)\b",
            near=r"\b(?:item|rule|checklist|count|require|policy)",
            unless=r"\b(?:no|never|neither|nor|c-4|a-16)\b",
        ),
    )
    return bad


def g_checklist(t: Texts) -> list[Finding]:
    """BQ-12: three item states; one status node speaks the changed item; the list not live."""
    head = "4.2 The checklist"
    bad = require(
        "G-CHECKLIST",
        head,
        (
            '"checked when you submit"',
            "the list is not a live region",
            "one pre-rendered polite status node",
            "speaks only the item that changed",
            "never the whole list",
            "every item's line exists at mount",
            "item 3 is drawn only once the server enforces a reuse rule",
        ),
    )(t)
    bad += as_findings(
        "G-CHECKLIST",
        "a live list or a whole-list announcement",
        claims(
            lex(t),
            r"\b(?:(?:the )?(?:list|checklist|ul)\b(?:\s+\S+){0,3}?\s+(?:is|as) (?:a |the )?"
            r"(?:polite )?live region|aria-live on the (?:list|ul)|reads? the whole list"
            r"|announces? (?:the )?(?:whole|full|entire) list|per keystroke announcement)",
            unless=r"\b(?:not|never|c-8|a-11|t a11y)\b",
        ),
    )
    return bad


METER_HEADS = (METER_HEAD, TRUTH_HEAD, "13.1 Bindings", "13.3 CVD")
# a near word stands alone: never inside a token (`color.status.success.strong`) or a frame id
METER_NEAR = r"(?<![\w./-])(?:meter|score|strength|strong|fair|weak)(?![\w./-])"
METER_LOCAL_NEAR = (
    r"(?<![\w./-])(?:meter|score|strength|strong|fair|weak|bar|segments?|word|fill\w*)(?![\w./-])"
)
# a role or state that disables the submit by itself; it excuses a clause only when the clause
# names no meter, score or strength (so "Like Cancel, the meter gates ..." is still read)
METER_UNLESS = r"^(?!.*\b(?:meter|score|strength)\b).*\b(?:cancel|read-only|view-as|t2)\b"
METER_GATES = (
    r"\b(?:gates?|gated|gating|enables?|unlocks?|blocks?|disables?|allows?|permits?|approves?"
    r"|accepts?)\b(?:\s+\S+){0,2}?\s+(?:the )?(?:submit|button|change|password|press)\b"
    r"|\b(?:disabled|locked|refused|held|blocked|greyed) until\b(?:\s+\S+){0,5}?\s+"
    r"(?:strong|fair|the meter|score|strength)"
    r"|\b(?:accepted|allowed|sent|enabled|possible|submitted|permitted|valid)\b(?:\s+\S+){0,2}?"
    r"\s+only (?:once|when|after|if|while)\b"
    r"|\bonly (?:once|when|after|if|while)\b(?:\s+\S+){0,5}?\s+(?:reaches|reads|shows|is)\s+"
    r"(?:strong|fair)\b|\buntil\b(?:\s+\S+){0,5}?\s+(?:reaches|reads|shows) (?:strong|fair)\b"
    r"|\b(?:rarely|sometimes|mostly|usually|partly) gat\w+"
)
METER_APPROVAL = (
    r"\b(?:green|success (?:colou?r|token|state)|check(?:mark| glyph)?|tick(?!-box)\w*|✓|✔"
    r"|turns? (?:green|success))\b"
)
METER_IN_LIST = (
    r"\b(?:inside|within|in|into|part of|as|joins?)\b(?:\s+\S+){0,2}?\s+(?:the )?"
    r"checklist(?:'s|\u2019s)?"
    r"(?:\s+\S+){0,2}?\s+(?:line|item|row|entry)\b|\b(?:inside|within|in|into|part of|joins?) "
    r"(?:the )?checklist\b|\bchecklist(?:'s|\u2019s)? (?:\w+ )?(?:line|item|row|entry)\b"
)


def g_meter(t: Texts) -> list[Finding]:
    """BQ-13: CMP-202's three words over the five scores; the cap; advisory; submit never gated;
    never a success colour or a check glyph."""
    sec = spec_sec(t, METER_HEAD)
    words = re.findall(r'"(\w+)"', grab(r"\(((?:\"\w+\"/?)+)\)", base_line("15", 2569), "words"))
    rows = meter_rows(t.spec)
    got = [(r[0], r[1]) for r in rows if len(r) > 1]
    want = [("0", words[0]), ("1", words[0]), ("2", words[1]), ("3", words[2]), ("4", words[2])]
    bad: list[Finding] = []
    if got != want:
        bad.append(F("G-METER", f"§4.3 maps {got}", "spec", sec))
    body = norm_text(section(t.spec, METER_HEAD))
    for n in (
        'shows "weak" whatever the estimator returns',
        "the submit stays enabled",
        "the score never enters that check",
    ):
        if n not in body:
            bad.append(F("G-METER", f"§4.3 lacks {n!r}", "spec", sec))
    if (
        "- **R-3 The meter advises.** It never gates the submit, never takes a success colour"
        not in (section(t.spec, "1.4 Rules stated once"))
        or "never sits inside the checklist" not in section(t.spec, "1.4 Rules stated once")
    ):
        msg = "R-3 is not BQ-13's rule (its label, no gate, never inside the checklist)"
        bad.append(F("G-METER", msg, "spec", spec_sec(t, "1.4 Rules stated once")))
    units = lex(t)
    secs = {spec_sec(t, h) for h in METER_HEADS}
    local = [u for u in units if u.doc == "spec" and u.sec in secs]
    # the meter's own sections read its bar, segments and word as the meter (no "meter" needed)
    for us, near in ((units, METER_NEAR), (local, METER_LOCAL_NEAR)):
        bad += as_findings(
            "G-METER", "a meter that gates or passes", claims(us, METER_GATES, near, METER_UNLESS)
        )
        bad += as_findings(
            "G-METER", "a meter in success colour or with a check", claims(us, METER_APPROVAL, near)
        )
        bad += as_findings(
            "G-METER", "the meter inside the checklist", claims(us, METER_IN_LIST, near)
        )
    return [(a, b, c, d or sec) for a, b, c, d in bad]


def g_truth(t: Texts) -> list[Finding]:
    """The computed truth table: in every row the meter is Weak while item 1 is unmet, and no
    word claims acceptance; the §4.4 sentence states the result; §13.1's meter rows never bind
    a status token."""
    sec = spec_sec(t, TRUTH_HEAD)
    bad: list[Finding] = []
    words = set(re.findall(r'"(\w+)"', base_line("15", 2569)))
    for combo, score, word in truth_rows(t.spec):
        if combo and not combo[0] and word != "Weak":
            bad.append(F("G-TRUTH", f"score {score} with item 1 unmet reads {word}", "spec", sec))
        if word not in words:
            bad.append(F("G-TRUTH", f"score {score} reads {word!r}", "spec", sec))
    body = norm_text(section(t.spec, TRUTH_HEAD))
    for n in (
        "the submit is enabled",
        'the meter shows "weak" whenever item 1 is not met',
        "no row shows a check glyph or a success token on the meter",
    ):
        if n not in body:
            bad.append(F("G-TRUTH", f"§4.4 lacks {n!r}", "spec", sec))
    for r in rows_of(t.spec, BIND_HEAD):
        if r[0].startswith("meter") and "color.status." in r[1]:
            bad.append(F("G-TRUTH", f"{r[0]} binds {r[1]}", "spec", spec_sec(t, BIND_HEAD)))
    return bad


def g_fields(t: Texts) -> list[Finding]:
    """BQ-22: one reveal per field with a constant name; reveal resets; caps lock per CMP-201."""
    return require(
        "G-FIELDS",
        "5.1 The fields",
        (
            "**One reveal per field:**",
            "the constant name W-30 and `aria-pressed`",
            "resets to hidden after a submit",
            "on the focused field only",
        ),
    )(t)


# every token the HTML `autocomplete` attribute takes (WHATWG autofill field names and on/off);
# a clause naming a password field, CMP-201 or autocomplete may bind only the two password values
AUTOCOMPLETE_VALUES = frozenset(
    (
        *("on", "off", "name", "username", "email", "tel", "url", "current-password"),
        *("new-password", "one-time-code", "nickname", "organization", "street-address"),
        *("postal-code", "cc-number", "cc-csc", "bday", "sex", "webauthn", "photo", "language"),
        "transaction-amount",
    )
)
AUTOCOMPLETE_ATTR = re.compile(r"""autocomplete\s*=\s*["']?([\w -]*)""", re.IGNORECASE)
PASSWORD_FIELD = re.compile(
    r"autocomplete|cmp-201|password ?field|(?:current|new|confirm\w*)(?: new)? password|reveal",
    re.IGNORECASE,
)
ANATOMY_FIELDS = (
    "2. **Current password** (CMP-040 + CMP-201, `current-password`;",
    "3. **New password** (CMP-040 + CMP-201, `new-password`)",
    "5. **Confirm new password** (CMP-040 + CMP-201, `new-password`)",
)


def g_autocomplete(t: Texts) -> list[Finding]:
    """BQ-1 security: a field's autocomplete is only `current-password` or `new-password`. Every
    backticked token, and every `autocomplete="..."` form, in a clause that names a password
    field, CMP-201 or autocomplete is read; the `username` value appears only in the heuristic
    finding (no field is added); §2.2's three field items and §5.1's sentence stand verbatim."""
    bad: list[Finding] = []
    for u in lex(t):
        for c in clauses(u.text):
            if not PASSWORD_FIELD.search(norm_text(c)):
                continue
            vals = [x for code in CODE.findall(c) for x in AUTOCOMPLETE_ATTR.findall(code)]
            vals = [v for x in vals for v in x.split()]
            vals += [x[1:-1] for x in CODE.findall(c) if x[1:-1] in AUTOCOMPLETE_VALUES]
            for v in vals:
                if v in ("current-password", "new-password"):
                    continue
                if v == "username" and re.search(r"\(heuristic\)|password managers rely", c):
                    continue
                bad.append(F("G-AUTOCOMPLETE", f"autocomplete `{v}`: {c[:50]!r}", u.doc, u.sec))
    if "`current-password` on the current field and `new-password` on both new fields" not in (
        section(t.spec, "5.1 The fields")
    ):
        bad.append(F("G-AUTOCOMPLETE", "§5.1 lacks the two values", "spec", "5. Fields, mismatch"))
    anatomy = section(t.spec, "2.2 Anatomy")
    for item in ANATOMY_FIELDS:
        if item not in anatomy:
            bad.append(
                F("G-AUTOCOMPLETE", f"§2.2 lacks {item[:30]!r}", "spec", spec_sec(t, "2.2 Anatomy"))
            )
    return bad


def g_paste(t: Texts) -> list[Finding]:
    """T Sec: paste, drop and autofill are never blocked."""
    bad = as_findings(
        "G-PASTE",
        "paste or autofill blocked",
        claims(
            lex(t),
            r"\b(?:blocked|disabled|prevented|suppressed|refused|stripped|blocks?|suppress\w*"
            r"|prevents?)\b",
            near=r"\b(?:paste|drop|autofill|password managers?)\b",
            unless=r"\b(?:never|not|no|allowed)\b",
        ),
    )
    if "paste, drop and autofill allowed everywhere" not in section(t.spec, "5.1 The fields"):
        bad.append(F("G-PASTE", "§5.1 lacks the paste sentence", "spec", "5. Fields, mismatch"))
    return bad


def g_mismatch(t: Texts) -> list[Finding]:
    """BQ-14: the mismatch on blur and on submit; submit enabled."""
    bad = require(
        "G-MISMATCH",
        "5.2 The mismatch",
        ("on its blur once it holds text", "never while it is empty", "The submit is enabled"),
    )(t)
    c18 = " | ".join(next((r for r in rows_of(t.spec, CROW_HEAD) if r[0] == "C-18"), []))
    if "refuse for denied controls" not in c18 or "D09:230" not in c18:
        msg = "C-18 is not BQ-14's denied-control reading"
        bad.append(F("G-MISMATCH", msg, "spec", spec_sec(t, CROW_HEAD)))
    bad += as_findings(
        "G-MISMATCH",
        "a live mismatch error or a disabled submit",
        claims(
            lex(t),
            r"\b(?:on|per|at) (?:each |every )?(?:keystroke|key press|character typed)\b",
            near=r"\b(?:mismatch|don't match|match item|confirm field)\b",
            unless=r"\b(?:never|not)\b",
        ),
    )
    return bad


def g_busy(t: Texts) -> list[Finding]:
    """BQ-15: D08's busy rule; the busy label; the slow path; no minimum duration."""
    bad = require(
        "G-BUSY",
        "5.3 Submitting",
        ("the label W-19", "the slow-path line W-20", "no minimum duration, no delay"),
    )(t)
    bad += as_findings(
        "G-BUSY",
        "a minimum display time",
        claims(
            lex(t),
            r"\b(?:minimum (?:display )?(?:time|duration)|artificial (?:delay|wait)|held for at "
            r"least|shown for at least)\b",
            unless=r"\b(?:no|never|not)\b",
        ),
    )
    return bad


DECLARED_PROBLEMS = ("csrf_token_invalid",)  # `22`:1966's one declared `403`


def err_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, ERR_HEAD) if len(r) == 7]


def g_errmap(t: Texts) -> list[Finding]:
    """BQ-17: every response `22` declares on `authChangePassword` is a row marked declared; an
    undeclared answer names its G-row; every declared code of `redeemInvite` is in §6.2."""
    sec = spec_sec(t, ERR_HEAD)
    rows = err_rows(t.spec)
    bad: list[Finding] = []
    answers = " ".join(r[0] for r in rows)
    for code in change_password_codes():
        if f"`{code}`" not in answers:
            bad.append(F("G-ERRMAP", f"`{code}` (declared) has no row", "spec", sec))
    leads = [r[0] for r in rows]
    for dup in sorted({x for x in leads if leads.count(x) > 1}):
        bad.append(F("G-ERRMAP", f"{dup}: two rows answer it", "spec", sec))
    for r in rows:
        codes = re.findall(r"`(\d{3})`", r[0])
        problems = re.findall(r"`([a-z_]+)`", r[0])
        declared = r[1].startswith("yes")
        expect = all(c in change_password_codes() for c in codes) and all(
            p in DECLARED_PROBLEMS for p in problems
        )
        if codes and declared != expect:
            bad.append(F("G-ERRMAP", f"{r[0]}: declared cell is {r[1]!r}", "spec", sec))
        if r[1].startswith("no") and not re.search(r"G-\d", r[6]):
            bad.append(F("G-ERRMAP", f"{r[0]}: undeclared without a G-row", "spec", sec))
    body = section(t.spec, ERR_HEAD)
    for n in (
        (
            "a `401` from this operation is the session path (D08:127) and W-16 shows only on"
            " that code"
        ),
        "runs from the response's `Retry-After` only",
    ):
        if n not in body:
            bad.append(F("G-ERRMAP", f"§6.1 lacks {n[:40]!r}", "spec", sec))
    inv = section(t.spec, "6.2 The invite step")
    for code in redeem_codes():
        if code != "200" and code not in inv:
            bad.append(F("G-ERRMAP", f"redeemInvite `{code}` not in §6.2", "spec", sec))
    return bad


def g_clear(t: Texts) -> list[Finding]:
    """BQ-16: after a `422` both new fields are cleared, the current kept, W-13 says why; never
    retained."""
    sec = spec_sec(t, ERR_HEAD)
    bad: list[Finding] = []
    for r in err_rows(t.spec):
        if "`422`" in r[0] and (r[4] != "both new fields cleared" or "W-13" not in r[5]):
            bad.append(F("G-CLEAR", f"{r[0]}: value {r[4]!r}", "spec", sec))
    if "the current field keeps its value" not in section(t.spec, ERR_HEAD):
        bad.append(F("G-CLEAR", "§6.1 lacks the kept current field", "spec", sec))
    for r in err_rows(t.spec):
        if re.match(r"`(?:429|503|403)`", r[0]) and r[4] not in ("kept", "—"):
            msg = f"{r[0]}: a form-level failure reads {r[4]!r}; only a `422` clears"
            bad.append(F("G-CLEAR", msg, "spec", sec))
    delta = {r[0]: r for r in rows_of(t.hand, "§D The delta") if len(r) > 2}
    if "both new fields cleared" not in delta.get("after a rejection", ["", "", ""])[2]:
        msg = "§D's designed value after a rejection is not BQ-16's"
        bad.append(F("G-CLEAR", msg, "hand", h2_of(t.hand, "§D The delta")))
    bad += as_findings(
        "G-CLEAR",
        "a rejected value retained",
        claims(
            lex(t),
            r"\b(?:retain\w*|keep\w*|kept|preserv\w*)\b(?:\s+\S+){0,3}?\s+(?:the )?(?:new|rejected|"
            r"refused|entered|typed)\b(?:\s+\S+){0,1}?\s+(?:password|values?|fields?)",
            unless=r"\b(?:never|not|current (?:field|password))\b",
        ),
    )
    return bad


_SERVER_TEXT = (
    r"(?:the )?(?:server'?s?|response'?s?|problem'?s?|api'?s?)? ?(?:`?(?:detail|title)`?"
    r"|problem detail|error text|reason text|reason|message|explanation)s?"
)
DETAIL_TERM = (
    r"\b(?:render\w*|show\w*|display\w*|print\w*|reads?|surfac\w*|pass\w* through|relay\w*"
    r"|quot\w*)\b(?:\s+\S+){0,4}?\s+(?:the )?(?:server'?s? |response'?s? |problem'?s? )"
    r"(?:`?(?:detail|title)`?|problem detail|error text|reason text|reason|message|explanation)\b"
    r"|\b(?:render\w*|show\w*|display\w*|print\w*|surfac\w*)\b(?:\s+\S+){0,4}?\s+(?:the )?"
    r"(?:`?detail`?|problem detail|error text from the server)\b"
    rf"|\b{_SERVER_TEXT}\b(?:\s+{NEGFREE}\S+){{0,4}}?\s+(?:is |are |gets? )(?:{NEGFREE}\w+ )?"
    r"(?:shown|rendered|displayed|printed|surfaced|read out|relayed|passed through)"
    rf"|\b{_SERVER_TEXT}\b(?:\s+{NEGFREE}\S+){{0,6}}?\s+(?:word for word|verbatim"
    r"|as (?:it|they) arrives?"
    r"|as received|unfiltered|unedited|raw)\b"
)


def g_detail(t: Texts) -> list[Finding]:
    """BQ-1 security, BQ-21: no frame renders the server's `detail` raw."""
    bad = as_findings(
        "G-DETAIL",
        "a raw `detail` rendered",
        claims(lex(t), DETAIL_TERM),
    )
    if "**No raw `detail`:** a frame never renders the server's `detail`" not in t.spec:
        bad.append(
            F("G-DETAIL", "§6.1 lacks the no-raw-detail rule", "spec", spec_sec(t, ERR_HEAD))
        )
    return bad


def g_success(t: Texts) -> list[Finding]:
    """BQ-18: the sessions sentence; Continue with no countdown; this device stays signed in."""
    head = "7.1 Success"
    bad = require(
        "G-SUCCESS",
        head,
        (
            "body W-25",
            "held PROPOSED until tick-box (1)",
            "no countdown",
            "inline confirmation",
            "offers `revoke_all` an exclusion for the caller's session",
            "no code keeps or revokes a session on a credential change yet",
        ),
    )(t)
    bad += as_findings(
        "G-SUCCESS",
        "unmounted code read as behaviour",
        claims(
            lex(t),
            r"\bsess:[\d:, ]+(?:keeps|revokes|ends|rotates)\b"
            r"|\b(?:the )?(?:route|`?/auth/password`?) "
            r"(?:keeps|revokes|rotates) (?:the )?(?:caller|current|calling)",
        ),
    )
    bad += as_findings(
        "G-SUCCESS",
        "a timed redirect or sign-out on success",
        claims(
            lex(t),
            r"\b(?:redirect\w* (?:countdown|after)|count(?:s|ing)? down to|auto(?:matic)?[- ]?"
            r"redirect\w*|signs? (?:the user|you) out (?:of every|everywhere|on this device)"
            r"|revokes? (?:all|every) sessions?(?! of the user)(?: including)?)\b",
            unless=r"\b(?:no|never|not|c-13|other sessions)\b",
        ),
    )
    return bad


def g_escape(t: Texts) -> list[Finding]:
    """BQ-19, AC5: the forced page's Sign out with its confirm; the calling session only."""
    head = "7.2 The sign-out escape"
    bad = require(
        "G-ESCAPE",
        head,
        (
            'A secondary "Sign out" (W-27)',
            "W-28 (PROPOSED)",
            "without `all_sessions`",
            "ends the calling session only",
        ),
    )(t)
    regs = {f["Frame"] for f in frames(t.spec)}
    if "`escape/sign-out-confirm · dark`" not in regs:
        bad.append(F("G-ESCAPE", "no frame draws the escape", "spec", spec_sec(t, FRAME_HEAD)))
    bad += as_findings(
        "G-ESCAPE",
        "a forced page with no way out",
        claims(
            lex(t),
            r"\b(?:no (?:escape|way out|sign[- ]out)|cannot (?:sign|leave)|all_sessions: true"
            r"|signs? out (?:of )?every (?:device|session))\b",
            near=r"\b(?:forced|escape|sign out|sign-out|confirm)",
            unless=r"\b(?:never|not)\b",
        ),
    )
    return bad


@functools.lru_cache(maxsize=1)
def d09_keys() -> frozenset[str]:
    text = at_base(CITE_FILES["D09"])
    return frozenset(re.findall(r"^\| `((?:rbac|inflight|banner|notice)\.[a-z_.]+)`", text, MULTI))


def g_roles(t: Texts) -> list[Finding]:
    """BQ-23, S-10: every reason key is one of D09's; no role variant; nothing hidden."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            for k in re.findall(r"`((?:rbac|inflight)\.[a-z_]+)`", line):
                if k not in d09_keys():
                    msg = f"{doc}:{i} `{k}` is not a D09 key"
                    bad.append(F("G-ROLES", msg, doc, h2_at(text, i)))
    bad += require("G-ROLES", "8. Roles", ("**No role variant:**", "nothing is hidden"))(t)
    bad += as_findings(
        "G-ROLES",
        "a role-hidden or role-specific password control",
        claims(
            lex(t),
            r"\b(?:viewers?|managers?|owners?)\b(?:\s+\S+){0,4}?\s+(?:cannot|can't|may not)\s+"
            r"change (?:their|own|a) password|\bhid(?:e|den|es) (?:the )?(?:password )?section\b",
            unless=r"\b(?:never|not|no)\b",
        ),
    )
    return bad


def g_focus(t: Texts) -> list[Finding]:
    """BQ-24: focus to the first failing field; the region for form-level failures only; no
    CMP-027 summary."""
    sec = spec_sec(t, "9.1 Focus")
    rows = {r[0]: r for r in rows_of(t.spec, "9.1 Focus")}
    bad: list[Finding] = []
    for lead in ("A press with an unmet client item", "A `422` or a wrong current password"):
        if rows.get(lead, ["", ""])[1] != "the first failing field":
            bad.append(F("G-FOCUS", f"{lead}: focus is not the failing field", "spec", sec))
    if "No CMP-027 summary" not in section(t.spec, "9.1 Focus"):
        bad.append(F("G-FOCUS", "§9.1 lacks the no-summary rule", "spec", sec))
    for f in frames(t.spec):
        if "CMP-027" in f.get("Components", ""):
            msg = f"{f['Frame']} lists CMP-027: the alerts sit in CMP-200's region (BQ-24)"
            bad.append(F("G-FOCUS", msg, "spec", spec_sec(t, FRAME_HEAD)))
    bad += as_findings(
        "G-FOCUS",
        "focus to the alert region on a field rejection",
        claims(
            lex(t),
            r"\b(?:to|on) (?:the )?(?:alert|error) (?:region|summary|banner)\b"
            r"|\b(?:an|the) error summary\b",
            near=r"\bfocus",
            unless=r"\b(?:no|never|not|only|c-19|a-14|429|503)\b",
        ),
    )
    return bad


def g_motion(t: Texts) -> list[Finding]:
    """BQ-26: no new motion; cuts and class flips only."""
    bad = require("G-MOTION", "10. Motion", ("No new motion (R-6).", "is a cut"))(t)
    bad += as_findings(
        "G-MOTION",
        "new motion",
        claims(
            lex(t),
            r"\b(?:fades?|fading|slides?|sliding|shakes?|pulses?|animat\w+|transition\w*)\b",
            near=r"\b(?:success|error|meter|checklist|item|field|route|card|reject)",
            unless=r"\b(?:no|never|not|forbidden|d08)\b",
        ),
    )
    return bad


# ---------------------------------------------------------------------------- the copy (BQ-21)


# BQ-11: items 1 to 4 in `14`'s words; BQ-18: "Continue" is the ruled word, not D02 img's
# button (D02 img's Continue is the policy-shown submit)
RULED_PROVENANCE = {
    "W-1": "verbatim `14`:209",
    "W-2": "verbatim `14`:209",
    "W-3": "verbatim `14`:209",
    "W-4": "verbatim `14`:209",
    "W-26": "new, PROPOSED (the word ruled by BQ-18",
}


def g_deck(t: Texts) -> list[Finding]:
    """BQ-21: every string's provenance holds: verbatim at its line, as shipped at its CPS line,
    D02 img, or new and PROPOSED; every W-n used exists."""
    sec = spec_sec(t, DECK_HEAD)
    bad: list[Finding] = []
    img = {loose(s) for s in D02_IMG}
    for wid, r in deck(t.spec).items():
        if len(r) < 4:
            bad.append(F("G-DECK", f"{wid}: cells", "spec", sec))
            continue
        strings, prov = unq(r[2]), r[3]
        if not strings:
            bad.append(F("G-DECK", f"{wid}: no quoted string", "spec", sec))
        m = re.match(r"(verbatim|as shipped) (?:`(\d{2})`|([A-Z0-9]+)):(\d+)", prov)
        if prov.startswith("new, PROPOSED"):
            continue
        if prov.startswith("verbatim D02 img"):
            if not all(loose(s) in img for s in strings):
                bad.append(F("G-DECK", f"{wid}: not a D02 wireframe string", "spec", sec))
            continue
        if not m:
            bad.append(F("G-DECK", f"{wid}: provenance {prov[:30]!r}", "spec", sec))
            continue
        line = loose(base_line(m[2] or m[3], int(m[4])).replace('\\"', '"'))
        for s in strings:
            if loose(re.sub(r"\d{2}:\d{2}", "", s)).rstrip() not in line.replace("00:47", ""):
                bad.append(F("G-DECK", f"{wid}: {s[:30]!r} not at {m[0]}", "spec", sec))
    rows = deck(t.spec)
    for wid, prov in RULED_PROVENANCE.items():
        if not [*rows.get(wid, []), "", "", "", ""][3].startswith(prov):
            bad.append(F("G-DECK", f"{wid}: provenance is not {prov!r}", "spec", sec))
    used = {w for text in (t.spec, t.hand) for w in re.findall(r"\bW-\d+\b", text)}
    bad += [
        F("G-DECK", f"{w} is used but not in §11.1", "spec", sec) for w in used - set(deck(t.spec))
    ]
    return bad


NEVER_ITEMS = (
    "the password or any part of it outside the cmp-201 reveal",
    'a hint field, the word "hint"',
    "where, when, from what source or how often a password was breached",
    "whether a reused password was the last one or an older one",
    "a server `detail` rendered raw",
    "a sample password in any frame, annotation, example or illustrative value",
)


def g_never(t: Texts) -> list[Finding]:
    """BQ-21: the never-list holds its six items."""
    body = norm_text(section(t.spec, NEVER_HEAD)).replace("`", "")
    sec = spec_sec(t, NEVER_HEAD)
    return [
        F("G-NEVER", f"§11.2 lacks {n[:40]!r}", "spec", sec)
        for n in NEVER_ITEMS
        if norm_text(n).replace("`", "") not in body
    ]


_ECHO_VERB = (
    r"(?:echo\w*|read\w* (?:out|aloud|back)|announc\w+|log\w*|print\w*|mirror\w*|repeat\w*"
    r"|speak\w*|spoken|spell\w*|recit\w*|preview\w*|mask\w*[- ]and[- ]show\w*)"
)
_ECHO_WHAT = (
    r"(?:the |a |its |any |what )?(?:typed |new |current |entered |actual )?(?:password|value"
    r"|input|characters? (?:typed|entered)|what was typed)s?"
)
# a clause asserting an echo, active or passive; the lexicon's negation scope (`live`) decides,
# never a negation elsewhere in the clause
ECHO_TERM = (
    rf"\b{_ECHO_VERB}\b(?:\s+\S+){{0,4}}?\s+{_ECHO_WHAT}\b"
    rf"|\b(?:password|value|input)s?\b(?:\s+{NEGFREE}\S+){{0,2}}?\s+(?:is |are |gets? |being )"
    rf"(?:{NEGFREE}\w+ )?{_ECHO_VERB}"
    r"|\bhow many (?:characters|letters|keys)\b|\b(?:its|the password's) length as a number\b"
    r"|\b(?:first|last) (?:few |\d+ )?(?:characters|letters)\b"
)


def g_echo(t: Texts) -> list[Finding]:
    """BQ-1 security: no copy string or claim echoes, masks-and-shows or reads out a password."""
    bad: list[Finding] = []
    for wid, cell in deck_strings(t.spec).items():
        if re.search(r"\{(?:password|value|new|current)[^}]*\}|•|\*{3,}", cell, re.IGNORECASE):
            bad.append(F("G-ECHO", f"{wid} echoes a value", "spec", spec_sec(t, DECK_HEAD)))
    bad += as_findings("G-ECHO", "a password echoed", claims(lex(t), ECHO_TERM))
    return bad


HINT_TERM = (
    r"\b(?:hints?|reminders?|remind\w*|memory aids?|clues?|mnemonics?|prompt questions?"
    r"|security questions?|password questions?)\b"
)


def g_hint(t: Texts) -> list[Finding]:
    """BQ-1 security, T Sec: no hint field; every clause naming a hint is a negation."""
    bad: list[Finding] = []
    for u in lex(t):
        for c in clauses(u.text):
            nc = norm_text(unquote(c))
            if not re.search(HINT_TERM, nc):
                continue
            if not re.search(rf"\b{NEG_WORD}\b", nc) or live(c, HINT_TERM):
                bad.append(F("G-HINT", f"a hint asserted: {nc[:60]!r}", u.doc, u.sec))
    for wid, cell in deck_strings(t.spec).items():
        if re.search(HINT_TERM, cell, re.IGNORECASE):
            bad.append(F("G-HINT", f"{wid} names a hint", "spec", spec_sec(t, DECK_HEAD)))
    return bad


BREACH_DETAIL = (
    r"\b(?:where|when|how (?:many|often)|in which|which (?:leaks?|lists?|breach\w*|dumps?|sites?"
    r"|sources?|services?)|the (?:count|source|site|date|year|service)"
    r"|the number of (?:times|breaches|leaks|sightings)|(?:list|leak|dump|site) it came from"
    r"|times it (?:was|has been) (?:seen|found|breached|leaked)|how recently)\b"
)


def g_breach(t: Texts) -> list[Finding]:
    """BQ-1 security, T Sec: no breach string carries a count, a source or a date; no claim
    states where, when or how often."""
    bad: list[Finding] = []
    for wid, cell in deck_strings(t.spec).items():
        if re.search(r"breach", cell, re.IGNORECASE) and re.search(
            r"\d|\btimes?\b|\bsince\b|\bfrom\b|\bin \w+ (?:dump|leak)|\bon \w+\.|\bwhen\b",
            cell,
            re.IGNORECASE,
        ):
            bad.append(F("G-BREACH", f"{wid} carries a count, source or date", "spec", None))
    bad += as_findings(
        "G-BREACH",
        "a breach detail stated",
        claims(lex(t), BREACH_DETAIL, near=r"\b(?:breach\w*|leak\w*|dump\w*|pwned|compromis\w*)"),
    )
    return [(a, b, c, d or spec_sec(t, DECK_HEAD)) for a, b, c, d in bad]


# ---------------------------------------------------------------------------- audit (BQ-27)


def g_audit(t: Texts) -> list[Finding]:
    """BQ-27: the registered action as intent and outcome; per-session revocations; the invite
    step's record; no payload carries the password, hash, length or score."""
    head = "12. Audit"
    bad = require(
        "G-AUDIT",
        head,
        (
            "**registered** action `auth.password_change`",
            "a write-ahead intent",
            "an outcome after",
            "one `auth.session_revoked` per other session",
            "`users.invite_redeemed`",
            "an `auth.session_created` with `rotated_from`",
        ),
    )(t)
    if '"auth.password_change"' not in at_base(CITE_FILES["ACT"]):
        bad.append(F("G-AUDIT", "the action is not in ACT", None, None))
    bad += as_findings(
        "G-AUDIT",
        "a record carrying a secret or the score",
        claims(
            lex(t),
            r"\b(?:carr\w+|includ\w+|contain\w*|holds?|logs?)\b(?:\s+\S+){0,3}?\s+(?:the )?"
            r"(?:password|hash|strength score|score|length)\b",
            near=r"\b(?:records?|events?|payloads?|annotations?|audit)\b",
            unless=r"\b(?:never|not|no|nor)\b",
        ),
    )
    bad += as_findings(
        "G-AUDIT",
        "the unregistered dotted name annotated",
        claims(
            lex(t),
            r"auth\.password\.changed",
            near=r"\b(?:annotat\w*|emit\w*|writes?|frames?)\b",
            unless=r"\b(?:c-21|g-7|spelling|not)\b",
            keep_quotes=True,
        ),
    )
    return bad


# ---------------------------------------------------------------------------- tokens (BQ-28)

ALLOWED_UNSHIPPED = {"color.text.muted", "color.status.*", "color.status.success"}


def g_tokens(t: Texts) -> list[Finding]:
    """BQ-28: every bound token is shipped (the cited unshipped ones only in a cited context);
    no meter binding is a status token."""
    names = all_token_names()
    bad: list[Finding] = []
    for u in lex(t):
        for tok in TOKEN_NAME.findall(u.text):
            if tok in names:
                continue
            if tok in ALLOWED_UNSHIPPED and re.search(r"`15`:\d+|A-1[05]|C-9|not shipped", u.text):
                continue
            bad.append(F("G-TOKENS", f"`{tok}` is not shipped", u.doc, u.sec))
    bad += as_findings(
        "G-TOKENS",
        "a status colour on the meter",
        claims(
            lex(t),
            r"\b(?:color\.status\.\w+|status (?:colou?r|token)s?|danger|warning|red|amber)\b",
            near=r"\bmeter\b",
            unless=r"\b(?:never|not|no|c-9|a-10)\b|^meter (?:segment|words)",
        ),
    )
    return bad


def g_contrast(t: Texts) -> list[Finding]:
    """Every §13.2 pair meets its bar in all three themes (computed)."""
    sec = spec_sec(t, PAIRS_HEAD)
    bad: list[Finding] = []
    grid = contrast_grid(t.spec)
    for r in pair_rows(t.spec):
        pid = r[0].split(" ")[0].lower().replace("-", "")
        bar = bars().get(r[-1])
        if bar is None or pid not in grid:
            bad.append(F("G-CONTRAST", f"{r[0]}: bar {r[-1]!r} or tokens", "spec", sec))
            continue
        for theme, ratio in grid[pid].items():
            if ratio < bar:
                msg = f"{r[0]} {theme} {show_ratio(ratio)} < {bar}:1"
                bad.append(F("G-CONTRAST", msg, "spec", sec))
    if len(themes_json_names()) != len(PAIR_THEMES):
        bad.append(F("G-CONTRAST", "themes.json does not hold three colour themes", None, None))
    return bad


def g_cvd(t: Texts) -> list[Finding]:
    """The CVD constants equal CVD's at the base; every pair keeps its bar under each simulation
    and in greyscale (AC4)."""
    sec = spec_sec(t, "13.3 CVD")
    bad: list[Finding] = []
    base = cvd_constants_at_base()
    for k, v in own_cvd_constants().items():
        if base.get(k) != v:
            bad.append(F("G-CVD", f"the tool's {k} differs from CVD at the base", None, None))
    for r in pair_rows(t.spec):
        bar = bars().get(r[-1], bars()["text"])
        fg, bg = r[1].strip("`"), r[2].strip("`")
        for theme in PAIR_THEMES:
            try:
                a, b = theme_hex(theme, fg), theme_hex(theme, bg)
            except SystemExit:
                continue
            for kind in DEFICIENCIES:
                ratio = contrast(simulate(a, kind), simulate(b, kind))
                if ratio < bar:
                    msg = f"{r[0]} {theme} {kind} {show_ratio(ratio)} < {bar}:1"
                    bad.append(F("G-CVD", msg, "spec", sec))
    if "never rest on hue" not in section(t.spec, "13.3 CVD"):
        bad.append(F("G-CVD", "§13.3 lacks the carrier sentence", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- security (BQ-30)


R4 = (
    "- **R-4 No oracle.** A wrong current password reads the same for every wrong value, at the"
    " same time"
)
ORACLE = (
    r"\b(?:reads?|looks?|answers?|responds?|returns?|differs?|var(?:y|ies)|takes?)\s+(?:\w+\s+)?"
    r"(?:differently|faster|slower|otherwise|longer|shorter)\b|\b(?:close|closer|near|similar) to "
    r"the (?:real|right|correct|actual|stored|old) (?:one|password|value)\b"
    r"|\bpartially (?:correct|right|matching)\b|\bhow (?:close|near|many characters)\b"
)


def g_security(t: Texts) -> list[Finding]:
    """BQ-30: the owner tick-boxes (1) to (7), plus (8) from the Fable lens's fold (the
    current-password check throttled and counted like an unlock), open, in order; the Fable
    lens before READY."""
    head = "14. Security"
    body = section(t.spec, head)
    sec = spec_sec(t, head)
    got = re.findall(r"^- \[ \] \((\d)\)", body, MULTI)
    bad: list[Finding] = []
    if got != [str(n) for n in range(1, 9)]:
        bad.append(F("G-SECURITY", f"the tick-boxes read {got}", "spec", sec))
    if "The Fable lens reads §11 and this list before READY" not in body:
        bad.append(F("G-SECURITY", "§14 lacks the Fable lens", "spec", sec))
    if "counted toward the account lockout like a wrong unlock password" not in body:
        bad.append(F("G-SECURITY", "§14 lacks tick-box (8)'s lockout count", "spec", sec))
    if R4 not in section(t.spec, "1.4 Rules stated once"):
        bad.append(
            F("G-SECURITY", "R-4 is not the no-oracle rule", "spec", spec_sec(t, "1.4 Rules"))
        )
    bad += as_findings(
        "G-SECURITY",
        "an oracle on the current password",
        claims(lex(t), ORACLE, near=r"\b(?:wrong|current password|oracle|incorrect|refus\w*)"),
    )
    return bad


# ---------------------------------------------------------------------------- rows (BQ-34)

AGENT = re.compile(
    r"\b(?:agent|worker|hcl-|hpe-|vps-|orchestrator|claude|lane \d)\b", re.IGNORECASE
)


def ids_used(t: Texts, prefix: str) -> set[str]:
    out: set[str] = set()
    for text in (t.spec, t.hand):
        work = CODE.sub(" ", text)
        out |= set(re.findall(rf"(?<![\w-]){prefix}-\d+\b(?!\.\d)", work))
    return out


def g_rows(t: Texts, head: str, prefix: str, n: int, tag: str, due_col: int) -> list[Finding]:
    sec = spec_sec(t, head)
    rows = [r for r in rows_of(t.spec, head) if re.fullmatch(rf"{prefix}-\d+", r[0])]
    bad: list[Finding] = []
    ids = [r[0] for r in rows]
    if ids != [f"{prefix}-{k}" for k in range(1, n + 1)]:
        bad.append(F(tag, f"the rows read {ids[:3]}…, not {prefix}-1 … {prefix}-{n}", "spec", sec))
    for r in rows:
        lane = r[due_col - 1] if due_col else r[-1]
        if AGENT.search(lane):
            bad.append(F(tag, f"{r[0]}: an agent as the owner lane", "spec", sec))
        if due_col and r[due_col] != "at once":
            bad.append(F(tag, f"{r[0]}: due {r[due_col]!r}", "spec", sec))
    for x in sorted(ids_used(t, prefix) - set(ids)):
        bad.append(F(tag, f"{x} is cited but not defined", "spec", sec))
    return bad


def g_crows(t: Texts) -> list[Finding]:
    """BQ-34: the C-rows, numbered, each with its reading and an owner lane, never an agent."""
    return g_rows(t, CROW_HEAD, "C", 27, "G-CROWS", 0)


def g_grows(t: Texts) -> list[Finding]:
    """BQ-29, rider (b): G-1 … G-8, owners never an agent, due at once."""
    return g_rows(t, GROW_HEAD, "G", 8, "G-GROWS", 4)


def g_qrows(t: Texts) -> list[Finding]:
    """S-13: the open questions, owned and due at once."""
    return g_rows(t, QROW_HEAD, "Q", 6, "G-QROWS", 4)


# ---------------------------------------------------------------------------- the hand-off

A_IDS = tuple(f"A-{n}" for n in range(1, 19))


def a_rows(hand: str) -> dict[str, list[str]]:
    return {r[0]: r for r in rows_of(hand, TABLE_A_HEAD) if re.fullmatch(r"A-\d+", r[0])}


def unescape(cell: str) -> str:
    return cell.replace("\\|", "|")


def g_arow(t: Texts) -> list[Finding]:
    """BQ-3, S-15: departures ship as copy-ready A-rows; each Old cell is its target line (or one
    of its table cells) verbatim and whole at the base; every A-n used exists."""
    sec = h2_of(t.hand, TABLE_A_HEAD)
    rows = a_rows(t.hand)
    bad: list[Finding] = []
    if tuple(rows) != A_IDS:
        bad.append(F("G-AROW", f"Table A reads {list(rows)[:3]}…", "hand", sec))
    for aid, r in rows.items():
        if len(r) < 6:
            bad.append(F("G-AROW", f"{aid}: cells", "hand", sec))
            continue
        refs = cite_refs(r[2])
        if len(refs) != 1:
            bad.append(F("G-AROW", f"{aid}: its Field cites {len(refs)} lines", "hand", sec))
            continue
        cid, n, _b = refs[0]
        line = base_line(cid, n)
        old = pin_norm(unescape(r[3]))
        whole = pin_norm(line)
        cells = [pin_norm(c) for c in split_row(line)] if line.lstrip().startswith("|") else []
        if old not in (whole, " ".join(whole.split()), *cells):
            bad.append(F("G-AROW", f"{aid}: Old is not {cid}:{n} verbatim and whole", "hand", sec))
        if not r[4].strip() or r[4] == r[3]:
            bad.append(F("G-AROW", f"{aid}: no New", "hand", sec))
    for x in sorted(ids_used(t, "A") - set(rows)):
        bad.append(F("G-AROW", f"{x} is cited but not in Table A", "hand", sec))
    return bad


def expand(spec_: str) -> set[str]:
    out: set[str] = set()
    for part in spec_.split(","):
        m = re.match(r"\s*A-(\d+)(?:\s*…\s*A-(\d+))?", part)
        if m:
            a, b = int(m[1]), int(m[2] or m[1])
            out |= {f"A-{k}" for k in range(a, b + 1)}
    return out


def g_handoff(t: Texts) -> list[Finding]:
    """§A: every line ticked with evidence or open with its reason; §B covers every A-row once."""
    bad: list[Finding] = []
    sec = h2_of(t.hand, "§A Hand-off checklist")
    for r in rows_of(t.hand, "§A Hand-off checklist"):
        for c in r[1:]:
            m = re.match(r"\[( |x)\] (.+)", c)
            if not m or len(m[2].strip()) < 4:
                bad.append(F("G-HANDOFF", f"§A {r[0]}: {c[:30]!r}", "hand", sec))
    covered: list[str] = []
    for r in rows_of(t.hand, "§B Who applies"):
        covered += sorted(expand(r[0]))
    if sorted(covered) != sorted(A_IDS):
        missing = sorted(set(A_IDS) - set(covered))
        bad.append(F("G-HANDOFF", f"§B misses {missing[:4]}", "hand", h2_of(t.hand, "§B Who")))
    return bad


HAND_SECTIONS = re.compile(r"^## (§[A-H])\b", MULTI)


def g_handref(t: Texts) -> list[Finding]:
    """Every "hand-off §X" in the spec names a hand-off section; every "spec §n" (and every bare
    "§n" pointer in the hand-off) names a spec section."""
    bad: list[Finding] = []
    hand_secs = set(HAND_SECTIONS.findall(t.hand))
    spec_secs = set(re.findall(r"^#{2,3} (\d+(?:\.\d+)?)\.? ", t.spec, MULTI))
    for i, line in enumerate(t.spec.split("\n"), 1):
        for x in re.findall(r"hand-off(?:'s)? (§[A-Z])\b", line):
            if x not in hand_secs:
                bad.append(
                    F(
                        "G-HANDREF",
                        f"spec:{i} hand-off {x} does not exist",
                        "spec",
                        h2_at(t.spec, i),
                    )
                )
    for i, line in enumerate(t.hand.split("\n"), 1):
        for m in re.finditer(r"(?<![\w`])§(\d+(?:\.\d+)?)", line):
            x, pre = m[1], line[: m.start()]
            if re.search(r"`(?:\d\d|[A-Z0-9]+)`\s*$|\b(?:D0\d|S03|[A-Z]\w+-D\d\d)\s*$", pre):
                continue
            if x not in spec_secs:
                bad.append(
                    F("G-HANDREF", f"hand:{i} §{x} is not a spec section", "hand", h2_at(t.hand, i))
                )
    if "[E09-D05-handoff.md](E09-D05-handoff.md)" not in t.spec.split("\n", 3)[2]:
        bad.append(F("G-HANDREF", "the status line does not link the hand-off", "spec", "(top)"))
    return bad


def g_newcmp(t: Texts) -> list[Finding]:
    """No new component: every CMP id named is in `15` at the base, and no sentence introduces a
    new component."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            for c in re.findall(r"\bCMP-\d{3}\b", line):
                if c not in catalogue_ids():
                    bad.append(F("G-NEWCMP", f"{doc}:{i} {c} is not in `15`", doc, h2_at(text, i)))
    bad += as_findings(
        "G-NEWCMP",
        "a new component",
        claims(
            lex(t),
            r"\b(?:new|a further|an extra|another) (?:component|cmp|organism|molecule|atom)\b",
            unless=r"\b(?:no|never|not)\b",
        ),
    )
    return bad


# ---------------------------------------------------------------------------- the dry run


BQ31_SYNONYMS = (
    *("forced password change", "change password", "set password", "must change", "breach"),
    *("breached", "known breach list", "reuse", "previous 5", "last 5", "strength", "meter"),
    *("requirements", "checklist", "policy"),
)


def g_walk(t: Texts) -> list[Finding]:
    """BQ-31, BQ-32: one row per consumer role in order; needs = found + not found; each "not
    found" carried to a G-row or a Q-row; the hand-off's §G lists match; the walkthrough holds at
    most ten items; the DoD tick follows the record."""
    sec = spec_sec(t, WALK_HEAD)
    raw = section(t.spec, WALK_HEAD)
    rows = rows_of(t.spec, WALK_HEAD)
    bad: list[Finding] = []
    roles = tuple(r[1] for r in rows if len(r) > 1)
    if roles != CONSUMERS:
        bad.append(F("G-WALK", f"the roles read {roles[:2]}…, not every consumer", "spec", sec))
    gq = ids_defined(t)
    lists = {r[0]: r[1] for r in rows_of(t.hand, NEEDS_HEAD) if len(r) > 1}
    spec_secs = set(re.findall(r"^#{2,3} (\d+(?:\.\d+)?)\.? ", t.spec, MULTI))
    gsec = h2_of(t.hand, NEEDS_HEAD)
    for r in rows:
        if len(r) < 6 or r[0] != DRY_DATE or not all(x.isdigit() for x in r[2:5]):
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
            m = re.search(r"→ ([GQ]-\d+)$", d)
            if not m or m[1] not in gq:
                bad.append(F("G-WALK", f"{r[1]}: {d[:40]!r} does not resolve", "spec", sec))
        items = [x for x in lists.get(r[1], "").split(" · ") if x.strip()]
        if len(items) != need or sum("(not found)" in x for x in items) != nf:
            msg = f"{r[1]}: §G lists {len(items)} needs, the row {need} / {nf}"
            bad.append(F("G-WALK", msg, "hand", gsec))
        for x in items:
            m = re.search(r"→ (?:§(\d+(?:\.\d+)?)|([GQ]-\d+))$", x)
            if not m or (m[1] and m[1] not in spec_secs) or (m[2] and m[2] not in gq):
                bad.append(
                    F("G-WALK", f"{r[1]}: §G item {x[:40]!r} does not resolve", "hand", gsec)
                )
            if "(not found)" in x and not (m and m[2]):
                bad.append(F("G-WALK", f"{r[1]}: a not-found item without a row", "hand", gsec))
    walk = [ln for ln in section(t.hand, WALKTHROUGH_HEAD).split("\n") if ln.startswith("- [")]
    if not 0 < len(walk) <= MAX_WALK:
        msg = f"the owner walkthrough has {len(walk)} items, not 1 to {MAX_WALK}"
        bad.append(F("G-WALK", msg, "hand", h2_of(t.hand, WALKTHROUGH_HEAD)))
    for item in walk:
        if not re.search(r"\(boards? \d|no board\)|; no board\)", item):
            msg = f"walkthrough item {item[6:40]!r} names no board"
            bad.append(F("G-WALK", msg, "hand", h2_of(t.hand, WALKTHROUGH_HEAD)))
    for syn in BQ31_SYNONYMS:
        if f"`{syn}`" not in raw:
            bad.append(F("G-WALK", f"§17.1 lacks BQ-31's synonym {syn!r}", "spec", sec))
    pub = "the direct consumers #190, #193, #194 and #291 get the publication comment (BQ-31)"
    if pub not in section(t.spec, "18.2 Hand-offs"):
        bad.append(
            F("G-WALK", "§18.2 lacks the publication comment", "spec", spec_sec(t, "18.2 Hand"))
        )
    body = norm_text(raw)
    if norm_text("**No session took place and none is claimed.**") not in body:
        bad.append(F("G-WALK", "§17.1 lacks the no-session sentence", "spec", sec))
    if 'before any "not found" was recorded, the merged sources were searched' not in body:
        bad.append(F("G-WALK", "§17.1 lacks the search-first sentence", "spec", sec))
    dod = section(t.spec, "18.1 DoD")
    tick = re.search(r"^- \[(.)\] The dry run is the written confirmation", dod, MULTI)
    ok = not [f for f in bad if f[0] == "G-WALK"]
    if not tick or (tick[1] == "x") != ok:
        bad.append(
            F(
                "G-WALK",
                "the DoD dry-run tick does not follow the record",
                "spec",
                spec_sec(t, "18.1 DoD"),
            )
        )
    return bad


SR_PROTOCOL = (
    "NVDA with the Electron shell, and with Chromium for the fast gate",
    "VoiceOver with the Electron shell",
    "`05`:219–224",
    "one character per 200 ms, then a 2 s pause",
)


def g_protocol(t: Texts) -> list[Finding]:
    """BQ-32 and `05` §8.1: the SR protocol names `05`'s pinned pairs (the Electron shell; Chromium
    for the fast gate only; Safari and a plain browser out of scope) and the ruled cadence, one
    character per 200 ms then a 2 s pause, with no cadence detail the ruling does not have."""
    head = "17.2 The protocols"
    sec = spec_sec(t, head)
    body = norm_text(section(t.spec, head))
    bad = [
        F("G-PROTOCOL", f"§17.2 lacks {n[:40]!r}", "spec", sec)
        for n in SR_PROTOCOL
        if norm_text(n) not in body
    ]
    bad += as_findings(
        "G-PROTOCOL",
        "an SR pair or a cadence the ruling and `05` do not have",
        claims(
            lex(t),
            r"\b(?:safari|firefox|edge|chrome)\b"
            r"|\b(?:after|every) (?:every )?(?:\w+ )?(?:fourth|third"
            r"|fifth|\d+(?:st|nd|rd|th)?) (?:character|keystroke|key)s?\b",
            near=r"\b(?:nvda|voiceover|jaws|screen reader|sr protocol|cadence|pause|typ\w+)\b",
        ),
    )
    return bad


# BQ-6: the deltas the hand-off's §D must carry (its lead cells), each with its designed cell
DELTA_ROWS = (
    ("checklist", "items"),
    ("strength", "§4.3"),
    ("reveal", "one per field"),
    ("outcomes", "problem codes"),
    ("busy", "slow path"),
    ("success", "Continue to the shell"),
    ("escape", "Sign out"),
)


def g_delta(t: Texts) -> list[Finding]:
    """BQ-6: §D lists every delta against the shipped interim screen (the checklist, the strength
    source, the single reveal, the substring matching, the slow-path line, the success route, the
    escape), each with its designed cell."""
    sec = h2_of(t.hand, "§D The delta")
    rows = {r[0]: r for r in rows_of(t.hand, "§D The delta") if len(r) > 2}
    return [
        F("G-DELTA", f"§D lacks the {lead} delta", "hand", sec)
        for lead, need in DELTA_ROWS
        if need not in rows.get(lead, ["", "", ""])[2]
    ]


def ids_defined(t: Texts) -> set[str]:
    out: set[str] = set()
    for head in (GROW_HEAD, QROW_HEAD):
        out |= {r[0] for r in rows_of(t.spec, head)}
    return out


DOD_OPEN = (
    "All states and the entry variants drawn",
    "The copy deck reviewed with the owner",
    "Design QA",
    "Owner sign-off",
)


def g_dod(t: Texts) -> list[Finding]:
    """The DoD: the owner's and PR 2's items stay open; every ticked item names its evidence."""
    sec = spec_sec(t, "18.1 DoD")
    bad: list[Finding] = []
    for ln in section(t.spec, "18.1 DoD").split("\n"):
        m = re.match(r"^- \[(.)\] (.*)$", ln)
        if not m:
            continue
        if m[2].startswith(DOD_OPEN) and m[1] != " ":
            bad.append(F("G-DOD", f"{m[2][:40]!r} is ticked", "spec", sec))
        if m[1] == "x" and not re.search(r"§\d|hand-off §[A-Z]", m[2]):
            bad.append(F("G-DOD", f"{m[2][:40]!r} has no evidence", "spec", sec))
    return bad


PR_TITLE = (
    "docs(auth-rbac): E09-D05 hi-fi of the forced password change and the password policy surface"
)
LABELS = ("type/design", "area/auth-rbac", "priority/p1", "design", "a11y", "security-review")


def g_deviations(t: Texts) -> list[Finding]:
    """D1 to D3 as accepted; the PR title, labels and the partial line (rider d)."""
    sec = spec_sec(t, "18.3 Deviations")
    body = section(t.spec, "18.3 Deviations")
    bad: list[Finding] = []
    for d in ("**D1**", "**D2**", "**D3**"):
        if f"- {d} " not in body:
            bad.append(F("G-DEVIATIONS", f"§18.3 lacks {d}", "spec", sec))
    if f"`{PR_TITLE}`" not in body or len(PR_TITLE) > 100:
        bad.append(F("G-DEVIATIONS", "§18.3's PR title is not rider (d)'s", "spec", sec))
    for lab in LABELS:
        if f"`{lab}`" not in body:
            bad.append(F("G-DEVIATIONS", f"§18.3 lacks the label {lab}", "spec", sec))
    if "`Refs #188` and `Partial: PR 1 of 2`" not in body:
        bad.append(F("G-DEVIATIONS", "§18.3 lacks the partial line", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- repo-level gates


def g_version(t: Texts) -> list[Finding]:
    """The version line's semantics: v1 at the base; every sha in order and under the base; each
    pinned doc at its last touch at the base; #2110 open at the base (ALLOW still lists the route
    as unmounted), else a late change must be recorded."""
    lines = t.spec.split("\n")
    bad: list[Finding] = []
    i = next((n for n, ln in enumerate(lines) if ln.startswith("**Start.**")), None)
    if i is None:
        return [F("G-VERSION", "no **Start.** line", "spec", "(top)")]
    line, sec = lines[i], h2_at(t.spec, i + 1)
    if f"**v1 at base `{BASE}`.**" not in line:
        bad.append(F("G-VERSION", "the version line does not name v1 at the base", "spec", sec))
    got = tuple(re.findall(r"`([0-9a-f]{10})`", line))
    if got != VERSION_SHAS:
        msg = f"the version line carries {len(got)} shas, not the {len(VERSION_SHAS)}"
        bad.append(F("G-VERSION", msg, "spec", sec))
    bad += [
        F("G-VERSION", f"`{s}` is not a commit under the base", "spec", sec)
        for s in got
        if not under_base(s)
    ]
    pinned = line.split("**Pinned at their last touch at the base:**", 1)[-1].split("**", 1)[0]
    for cid, sha in PINNED_DOCS.items():
        last = last_touch(cid)
        if last != sha or not re.search(rf"\b{cid}\b[^;`]*(?:`[0-9a-f]{{10}}`)?", pinned):
            bad.append(F("G-VERSION", f"{cid} pinned at {sha}, last touched {last}", "spec", sec))
    open_at_head = '"PUT /auth/password"' in (git_fetch_head(CITE_FILES["ALLOW"]) or "")
    if head_ok() and not open_at_head and "**Late changes:** none" in line:
        bad.append(F("G-VERSION", "#2110 mounted the route: record the late change", "spec", sec))
    inputs = next((ln for ln in lines if ln.startswith("**Inputs pinned.**")), "")
    if inputs.count(BASE) < 2:
        bad.append(F("G-VERSION", f"the Inputs line does not name the base {BASE}", "spec", sec))
    return bad


@functools.cache
def last_touch(cid: str) -> str:
    rel = cite_path(cid) or ""
    return git_out("log", "-1", "--format=%h", "--abbrev=10", BASE, "--", rel).strip()


def g_untouched(t: Texts) -> list[Finding]:
    """The standing rule: the untouched files equal the merge-base; only this PR's four files
    differ (committed or not); an unresolvable merge-base FAILs."""
    ref = merge_base()
    if not ref:
        return [F("G-UNTOUCHED", f"no merge-base with {HEAD}: nothing compared", None, None)]
    bad: list[Finding] = []
    for nn, text in t.plans:
        rel = cite_path(nn)
        if rel is None or text != (git_show(ref, rel) or ""):
            bad.append(F("G-UNTOUCHED", f"`{nn}` differs from {ref[:10]}", None, None))
    bad += [
        F("G-UNTOUCHED", f"{p} is not this PR's path", None, None)
        for p in sorted({*stray_paths(), *EXTRA_PATHS})
    ]
    return bad


# lexicon gates first, then the measured gates; the pins (G-RULED-PIN) run last, in `audit`
LEXICON_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_penpot,
    g_comment,
    g_close,
    g_charset,
    g_cells,
    g_quote,
    g_marked,
    g_named,
    g_session,
    g_echo,
    g_hint,
    g_breach,
    g_detail,
    g_autocomplete,
    g_paste,
    g_newcmp,
)
MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_trace,
    g_ruled,
    g_owner,
    g_boards,
    g_frame,
    g_locked,
    g_hosts,
    g_reasons,
    g_reset,
    g_order,
    g_rules,
    g_checklist,
    g_meter,
    g_truth,
    g_fields,
    g_mismatch,
    g_busy,
    g_errmap,
    g_clear,
    g_success,
    g_escape,
    g_roles,
    g_focus,
    g_motion,
    g_deck,
    g_never,
    g_audit,
    g_tokens,
    g_contrast,
    g_cvd,
    g_security,
    g_crows,
    g_grows,
    g_qrows,
    g_arow,
    g_handoff,
    g_handref,
    g_walk,
    g_protocol,
    g_delta,
    g_dod,
    g_deviations,
    g_entropy,
    g_untouched,
    g_version,
    g_budget,
)


# ---------------------------------------------------------------------------- the pins

PIN_DOCS: tuple[str, ...] = ("spec", "hand")  # every unit of both docs; no span is exempt


def write_pins(units: list[Unit]) -> str:
    head = (
        "# E09-D05 pins (every unit of both docs): doc, region (heading path #occurrence), "
        f"location, the exact normalised text; {len(units)} units.\n# Written by `--repin-ruled` "
        "only; `--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in units)


# ---------------------------------------------------------------------------- mutations


def reg(frame: str, col: str, fn: Callable[[str], str]) -> Edit:
    return row_edit(FRAME_HEAD, f"`{frame}`", FR_COLS.index(col), fn)


def pristine_drift(cid: str, n: int, text: str) -> Callable[[], Callable[[], None]]:
    """A cited line edited at `origin/main` (G-VERSION's content lever)."""

    def run() -> Callable[[], None]:
        DRIFT.append((cite_path(cid) or "", n, text))

        def undo() -> None:
            DRIFT.pop()

        return undo

    return run


def inserted(cid: str, n: int, text: str) -> Callable[[], Callable[[], None]]:
    """A line inserted at `origin/main` inside a cited range."""

    def run() -> Callable[[], None]:
        INSERT.append((cite_path(cid) or "", n, text))

        def undo() -> None:
            INSERT.pop()

        return undo

    return run


def cvd_drift() -> Callable[[], None]:
    base = dict(cvd_constants_at_base())
    base["tritanopia"] = (*base["tritanopia"][:-1], 0.3)
    CVD_OVERRIDE.append(base)

    def undo() -> None:
        CVD_OVERRIDE.pop()

    return undo


def overrun(text: str, _v: Values) -> str:
    n = text.count("\n")
    return text + "filler\n" * (SPEC_LINE_BUDGET - n + 5)


def drop_row_prefix(head: str, prefix: str) -> Edit:
    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        kept = [
            ln
            for ln in block.split("\n")
            if not (ln.startswith("|") and split_row(ln)[0].startswith(prefix))
        ]
        return text.replace(block, "\n".join(kept), 1)

    return run


def walk_counts(role: str, need: str) -> Callable[[list[str]], list[str]]:
    def run(lines: list[str]) -> list[str]:
        return [
            set_cell(ln, 2, to(need)) if ln.startswith("|") and split_row(ln)[1:2] == [role] else ln
            for ln in lines
        ]

    return run


def coded(*parts: str) -> str:
    """A probe string assembled at run time, so no scanner meets the literal in this file."""
    return "-".join(parts)


S11 = "1.1 What this spec fixes"
S42 = "4.2 The checklist"
S51 = "5.1 The fields"
P172 = "17.2 The protocols"
MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1",
        "G-PENPOT",
        "S-3: the page by name only",
        spec=sub_in(
            BOARDS_HEAD,
            "page `E09-D05 SCR-004 password`",
            # a reserved example host (RFC 2606), planted in memory only: no real link
            "page `E09-D05 SCR-004 password` (https://penpot.example/view)",
        ),
    ),
    Mutation(
        "M-2",
        "G-COMMENT",
        "BQ-1: no hidden comment",
        spec=sub_in(S11, "\n\nOne password form", "\n[//]: # (a hidden note)\nOne password form"),
    ),
    Mutation(
        "M-3",
        "G-CLOSE",
        "S-1: no closing keyword",
        spec=say_in("18.2 Hand-offs", "This PR closes #188."),
    ),
    Mutation(
        "M-4",
        "G-CHARSET",
        "BQ-1: the charset",
        spec=sub_in(S11, "One password form", "One password form"),
    ),
    Mutation(
        "M-5",
        "G-CELLS",
        "BQ-1: every row its header's cells",
        spec=row_edit(HOSTS_HEAD, "Escape", 3, appended(" | an extra cell")),
    ),
    Mutation(
        "M-6",
        "G-QUOTE",
        "BQ-1: quotes verbatim at a cited source",
        spec=say_in(S11, 'It never says "a sentence from nowhere at all".'),
    ),
    Mutation(
        "M-7",
        "G-MARKED",
        "S-9: a PROPOSED name marked",
        spec=sub_in(
            "12. Audit", "`password_changed` (PROPOSED; the name", "`password_changed` (the name"
        ),
    ),
    Mutation(
        "M-8",
        "G-NAMED",
        "rider (c): named only",
        spec=say_in("18.2 Hand-offs", '#2110 reads "Revokes all other sessions on success."'),
    ),
    Mutation(
        "M-9",
        "G-SESSION",
        "rider (a): no session claimed",
        spec=say_in("17.2 The protocols", "A walkthrough was held with the owner."),
    ),
    Mutation(
        "M-10",
        "G-ECHO",
        "BQ-1: nothing echoes a password",
        spec=say_in("5.1 The fields", "The status node reads out the typed password."),
    ),
    Mutation(
        "M-11",
        "G-HINT",
        "BQ-1: no hint field",
        spec=say_in("5.1 The fields", "A password hint sits under the new field."),
    ),
    Mutation(
        "M-12",
        "G-BREACH",
        "BQ-1: no breach count, source or date",
        spec=say_in("6.2 The invite step", "The alert says where the password was breached."),
    ),
    Mutation(
        "M-13",
        "G-DETAIL",
        "BQ-1, BQ-21: no raw detail",
        spec=say_in(
            "6.2 The invite step", "The frame renders the server's detail under the field."
        ),
    ),
    Mutation(
        "M-14",
        "G-AUTOCOMPLETE",
        "BQ-1: only the two values",
        spec=sub_in(
            "5.1 The fields", "`new-password` on both new fields", "`off` on both new fields"
        ),
    ),
    Mutation(
        "M-15",
        "G-PASTE",
        "BQ-22: paste never blocked",
        spec=say_in("5.1 The fields", "Paste is blocked on the confirm field."),
    ),
    Mutation(
        "M-16",
        "G-NEWCMP",
        "BQ-1: no new component",
        spec=say_in("2.2 Anatomy", "A new component wraps the checklist."),
    ),
    Mutation(
        "M-17",
        "G-TRACE",
        "BQ-1: the AC trace",
        spec=drop_row_prefix("Acceptance-criteria trace", "AC5 "),
    ),
    Mutation(
        "M-18",
        "G-RULED",
        "the ruling's nine",
        spec=sub_in("The questions BQ-1", "**BQ-29** the G-ledger (§16.2)", "the G-ledger (§16.2)"),
    ),
    Mutation(
        "M-19",
        "G-OWNER",
        "BQ-8: PROPOSED, owner approval pending",
        spec=sub_in(
            "3.2 What an owner reset", "(PROPOSED, owner approval pending (#2701); BQ-8)", "(BQ-8)"
        ),
    ),
    Mutation(
        "M-20",
        "G-BOARDS",
        "BQ-5: each twin of a dark board",
        spec=row_edit(BOARDS_HEAD, "08", 2, to("light twin of 09")),
    ),
    Mutation(
        "M-21",
        "G-FRAME",
        "BQ-1: the register gated by column",
        spec=reg("typing/weak · dark", "Status", to("drawn")),
    ),
    Mutation(
        "M-22",
        "G-LOCKED",
        "BQ-2: the locked inputs",
        spec=drop_row_prefix("1.3 Locked inputs", "D09 "),
    ),
    Mutation(
        "M-23",
        "G-HOSTS",
        "BQ-10: the current field on the forced page",
        spec=row_edit(HOSTS_HEAD, "Current password", 2, to("no")),
    ),
    Mutation(
        "M-24",
        "G-REASONS",
        "BQ-7: two reasons, aged out not drawn",
        spec=add_row_after(
            REASONS_HEAD,
            "Owner reset",
            "| Aged out | forced page | W-21 | W-23 | `auth.password_change` (ACT:97) |",
        ),
    ),
    Mutation(
        "M-25",
        "G-RESET",
        "BQ-8: the password neither cleared nor set",
        spec=sub_in(
            "3.2 What an owner reset", "neither clears nor sets the password", "clears the password"
        ),
    ),
    Mutation(
        "M-26",
        "G-ORDER",
        "BQ-20: no code on the change",
        spec=sub_in(
            "3.3 The order of the gates", "**No code on the change.**", "**A code on the change.**"
        ),
    ),
    Mutation(
        "M-27", "G-RULES", "BQ-11: `14`'s order", spec=in_lines(RULES_HEAD, swap_rows("2", "3"))
    ),
    Mutation(
        "M-28",
        "G-CHECKLIST",
        "BQ-12: the list is not live",
        spec=sub_in(
            "4.2 The checklist",
            "the list is not a live region (C-8)",
            "the list is a polite live region (C-8)",
        ),
    ),
    Mutation(
        "M-29",
        "G-METER",
        "BQ-13: the words over the scores",
        spec=row_edit(METER_HEAD, "2", 1, to("Strong")),
    ),
    Mutation(
        "M-30",
        "G-TRUTH",
        "BQ-13, BQ-28: never a status token on the meter",
        spec=row_edit(BIND_HEAD, "meter segment, filled", 1, to("`color.status.success.strong`")),
    ),
    Mutation(
        "M-31",
        "G-FIELDS",
        "BQ-22: reveal resets after a submit",
        spec=sub_in(
            "5.1 The fields", "resets to hidden after a submit", "stays revealed after a submit"
        ),
    ),
    Mutation(
        "M-32",
        "G-MISMATCH",
        "BQ-14: the mismatch on blur",
        spec=sub_in("5.2 The mismatch", "on its blur once it holds text", "on each keystroke"),
    ),
    Mutation(
        "M-33",
        "G-BUSY",
        "BQ-15: no minimum duration",
        spec=say_in("5.3 Submitting", "The busy state is shown for at least one second."),
    ),
    Mutation(
        "M-34", "G-ERRMAP", "BQ-17: every declared answer", spec=drop_row_prefix(ERR_HEAD, "`503`")
    ),
    Mutation(
        "M-35",
        "G-CLEAR",
        "BQ-16: both new fields cleared",
        spec=row_edit(ERR_HEAD, "`422` reused", 4, to("both new fields kept")),
    ),
    Mutation(
        "M-36",
        "G-SUCCESS",
        "BQ-18: no countdown",
        spec=sub_in("7.1 Success", "no countdown, since", "a countdown, since"),
    ),
    Mutation(
        "M-37",
        "G-ESCAPE",
        "BQ-19: the calling session only",
        spec=sub_in(
            "7.2 The sign-out escape", "without `all_sessions`", "with `all_sessions: true`"
        ),
    ),
    Mutation(
        "M-38",
        "G-ROLES",
        "BQ-23: nothing hidden",
        spec=sub_in("8. Roles", "and nothing is hidden", "and the section is gone for a viewer"),
    ),
    Mutation(
        "M-39",
        "G-FOCUS",
        "BQ-24: focus to the failing field",
        spec=row_edit(
            "9.1 Focus", "A `422` or a wrong current password", 1, to("the CMP-200 region")
        ),
    ),
    Mutation(
        "M-40",
        "G-MOTION",
        "BQ-26: no new motion",
        spec=say_in("10. Motion", "The success card fades in."),
    ),
    Mutation(
        "M-41",
        "G-DECK",
        "BQ-21: `14`'s strings verbatim",
        spec=row_edit(DECK_HEAD, "W-11", 2, to('"Passwords do not match."')),
    ),
    Mutation(
        "M-42",
        "G-NEVER",
        "BQ-21: the never-list",
        spec=in_lines(NEVER_HEAD, drop_line("- A hint field")),
    ),
    Mutation(
        "M-43",
        "G-AUDIT",
        "BQ-27: never the score in a record",
        spec=say_in("12. Audit", "Each outcome record carries the strength score."),
    ),
    Mutation(
        "M-44",
        "G-TOKENS",
        "BQ-28: shipped tokens only",
        spec=row_edit(BIND_HEAD, "page", 1, to("`color.surface.page`")),
    ),
    Mutation(
        "M-45",
        "G-CONTRAST",
        "BQ-28: each pair has its bar",
        spec=row_edit(PAIRS_HEAD, "P-1 met words", 6, to("large")),
    ),
    Mutation("M-46", "G-CVD", "brief: the CVD constants gated", patch=lambda: cvd_drift()),
    Mutation(
        "M-47",
        "G-SECURITY",
        "BQ-30: tick-boxes (1) to (7)",
        spec=in_lines("14. Security", drop_line("- [ ] (6)")),
    ),
    Mutation(
        "M-48",
        "G-CROWS",
        "rider (b): never an agent",
        spec=row_edit(CROW_HEAD, "C-5", 3, to("the hcl-worker lane")),
    ),
    Mutation(
        "M-49",
        "G-GROWS",
        "rider (b): due at once",
        spec=row_edit(GROW_HEAD, "G-4", 4, to("2026-11-20")),
    ),
    Mutation(
        "M-50",
        "G-QROWS",
        "S-13: due at once",
        spec=row_edit(QROW_HEAD, "Q-4", 4, to("next sprint")),
    ),
    Mutation(
        "M-51",
        "G-AROW",
        "BQ-3: Old cells verbatim and whole",
        hand=row_edit(
            TABLE_A_HEAD,
            "A-4",
            3,
            to('- **A11y:** requirement checklist uses `aria-live="polite"`;'),
        ),
    ),
    Mutation(
        "M-52",
        "G-HANDOFF",
        "BQ-3: every hand-off line with evidence",
        hand=row_edit("§A Hand-off checklist", "Contrast", 2, to("[x]")),
    ),
    Mutation(
        "M-53",
        "G-HANDREF",
        "brief: hand-off references resolve",
        spec=sub_in(BOARDS_HEAD, "(hand-off §D, BQ-33)", "(hand-off §Z, BQ-33)"),
    ),
    Mutation(
        "M-54",
        "G-WALK",
        "BQ-31: needs = found + not found",
        spec=in_lines(WALK_HEAD, walk_counts("story: E09-D10 (#193)", "5")),
    ),
    Mutation(
        "M-55",
        "G-DOD",
        "the DoD: owner items open",
        spec=sub_in("18.1 DoD", "- [ ] Owner sign-off", "- [x] Owner sign-off"),
    ),
    Mutation(
        "M-56",
        "G-DEVIATIONS",
        "rider (d): the labels",
        spec=sub_in("18.3 Deviations", "`security-review`", "`needs-owner`"),
    ),
    Mutation(
        "M-57",
        "G-ENTROPY",
        "brief: no high-entropy or code-shaped value",
        spec=say_in("17.2 The protocols", f"The fixture code is {coded('ab3cd', 'ef4gh')}."),
    ),
    Mutation("M-58", "G-UNTOUCHED", "standing: `15` untouched", plan=("15", appended("x\n"))),
    Mutation(
        "M-59",
        "G-UNTOUCHED",
        "brief: only the four files",
        patch=pushed(EXTRA_PATHS, "docs/plan/22-api-openapi.yaml"),
    ),
    Mutation(
        "M-60",
        "G-UNTOUCHED",
        "brief: an unresolved merge-base FAILs",
        patch=pushed(BROKEN, "merge-base"),
    ),
    Mutation(
        "M-61",
        "G-VERSION",
        "brief: an edit inside a cited range",
        patch=pristine_drift("14", 209, "- **Validation:** changed."),
    ),
    Mutation(
        "M-62",
        "G-VERSION",
        "brief: an insert inside a cited range",
        patch=inserted("22", 1960, "          application/xml: {}"),
    ),
    Mutation(
        "M-63",
        "G-VERSION",
        "the version line: each doc at its last touch",
        spec=line_edit("**Start.**", "D08 at `c99ad48d78`", "D08 at `a30c6ec6ad`"),
    ),
    Mutation("M-64", "G-BUDGET", "brief: the line budget", spec=overrun),
    Mutation(
        "M-65",
        "G-CITE",
        "BQ-1: every cite on a line at the base",
        spec=sub_in("1.2 Method", "CVD:49–93", "CVD:49–999"),
    ),
    Mutation(
        "M-66",
        "G-ANCHOR",
        "BQ-1: every number computed",
        spec=with_values(
            lambda v: sub_in(
                "4.2 The checklist", av(v, "CITE:debounce"), "450<!--=CITE:debounce-->"
            )
        ),
    ),
    Mutation(
        "M-67", "G-WORDCOUNT", "brief: counts as figures", spec=say_in(S11, "It draws ten boards.")
    ),
    Mutation(
        "M-68",
        "G-MARKER",
        "BQ-1: every comment an anchor",
        spec=say_in(S11, "<!-- a hidden note -->"),
    ),
    Mutation(
        "M-69", "G-HEX", "BQ-28: no hex by hand", spec=say_in("13.3 CVD", "The fill is #B1BAC4.")
    ),
    # the fold of the three lenses (lens 1 the ruling, lens 2 the tool, lens 3 the Fable lens)
    Mutation(
        "M-70",
        "G-PROTOCOL",
        "BQ-32, `05`:219-224: the Electron shell",
        spec=sub_in(P172, "VoiceOver with the Electron shell", "VoiceOver with Safari"),
    ),
    Mutation(
        "M-71",
        "G-PROTOCOL",
        "BQ-32: the ruled cadence only",
        spec=sub_in(P172, " s pause; expect", " s pause after every fourth character; expect"),
    ),
    Mutation(
        "M-72",
        "G-DELTA",
        "BQ-6: the strength-source delta",
        hand=drop_row_prefix("§D The delta", "strength"),
    ),
    Mutation(
        "M-73",
        "G-OWNER",
        "BQ-33: PROPOSED with its trade-off",
        spec=sub_in("18.2 Hand-offs", "**The trade-off, for the owner:** the delta", "The delta"),
    ),
    Mutation(
        "M-74",
        "G-MISMATCH",
        "BQ-14: refused for denied controls",
        spec=row_edit(CROW_HEAD, "C-18", 1, to("D02 img against `14`:85 and D09:228")),
    ),
    Mutation(
        "M-75",
        "G-DECK",
        "BQ-18: Continue is the ruled word",
        spec=row_edit(DECK_HEAD, "W-26", 3, to("verbatim D02 img (the wireframe's button)")),
    ),
    Mutation(
        "M-76",
        "G-DECK",
        "BQ-11: `14`'s rules in its words",
        spec=lambda s, v: row_edit(DECK_HEAD, "W-2", 3, to("new, PROPOSED (`14`:209 in words)"))(
            row_edit(DECK_HEAD, "W-2", 2, to('"Not in a known breach list"'))(s, v), v
        ),
    ),
    Mutation(
        "M-77",
        "G-FOCUS",
        "BQ-24: no CMP-027 summary",
        spec=reg("fail/rate-limited · dark", "Components", to("CMP-200, CMP-027, CMP-001")),
    ),
    Mutation(
        "M-78",
        "G-REASONS",
        "BQ-9: a new user on the embedded step",
        hand=row_edit(
            TABLE_A_HEAD,
            "A-1",
            4,
            lambda c: c.replace(
                "(owner reset); a new user sets the password in the SCR-017 embedded step;",
                "(new user via the invite step, owner reset);",
            ),
        ),
    ),
    Mutation(
        "M-79",
        "G-WALK",
        "BQ-31: the ruled synonyms",
        spec=sub_in(WALK_HEAD, "`set password`, ", ""),
    ),
    Mutation(
        "M-80",
        "G-WALK",
        "BQ-31: the publication comment",
        spec=sub_in("18.2 Hand-offs", "get the publication comment (BQ-31)", "are told"),
    ),
    Mutation(
        "M-81",
        "G-WALK",
        "BQ-32: each walkthrough item its board",
        hand=sub_in(WALKTHROUGH_HEAD, "- [ ] W-12 (board 04):", "- [ ] W-12:"),
    ),
    Mutation(
        "M-82",
        "G-RULED",
        "BQ-34: the corrected version pins said",
        spec=sub_in("The questions BQ-1", "last touch at the base (C-27)", "last touch"),
    ),
    Mutation(
        "M-83",
        "G-VERSION",
        "brief: `14`:88 read after an and",
        spec=line_edit("**Inputs pinned.**", "`14`:85, :88", "`14`:85 and :88"),
        patch=pristine_drift("14", 88, "8. **Audit.** changed."),
    ),
    Mutation(
        "M-84",
        "G-VERSION",
        "brief: a repeated cited line where it stood",
        patch=pristine_drift("22", 17678, "        user: { $ref: UserSummary }"),
    ),
    Mutation(
        "M-85",
        "G-CHECKLIST",
        "BQ-11: a server item follows the server",
        spec=sub_in(S42, "drawn only once the server enforces a reuse rule", "drawn at mount"),
    ),
    Mutation(
        "M-86",
        "G-RESET",
        "BQ-8: the password is not reset",
        spec=row_edit(DECK_HEAD, "W-23", 2, to('"Your password was reset by an owner."')),
    ),
    Mutation(
        "M-87",
        "G-SUCCESS",
        "BQ-18: an unmounted route does nothing",
        spec=sub_in("7.1 Success", "offers `revoke_all` an exclusion for", "keeps"),
    ),
    Mutation(
        "M-88",
        "G-AUDIT",
        "BQ-27: the rotation pair",
        spec=sub_in("12. Audit", "an `auth.session_created` with `rotated_from`", "a new session"),
    ),
    Mutation(
        "M-89",
        "G-ERRMAP",
        "BQ-17: a code-less `401` is the session path",
        spec=sub_in(
            ERR_HEAD, "is the session path (D08:127) and W-16 shows only on that code", "is W-16"
        ),
    ),
    Mutation(
        "M-90",
        "G-ERRMAP",
        "BQ-17: the countdown from `Retry-After`",
        spec=sub_in(ERR_HEAD, "runs from the response's `Retry-After` only", "runs from a timer"),
    ),
    Mutation(
        "M-91",
        "G-SECURITY",
        "BQ-30: tick-box (8)",
        spec=in_lines("14. Security", drop_line("- [ ] (8)")),
    ),
    Mutation(
        "M-92",
        "G-RULES",
        "BQ-11: item 5's predicate",
        spec=sub_in(RULES_HEAD, "nor the email's local part", "nor the email"),
    ),
)
# ADVERSARY: the lens-2 paraphrases that passed every gate after a re-pin (2026-10-29), applied
# AFTER a simulated re-pin as X-25 onwards; each must now FAIL its named gate alone
CYRILLIC_A = "\u0430"
ADVERSARY: tuple[Mutation, ...] = tuple(
    Mutation(x, g, f"adversary after a re-pin: {w}", spec=s, hand=h)
    for x, g, w, s, h in (
        ("X-25", "G-ECHO", "A02", say_in(S42, "The status node mirrors the entered value."), None),
        ("X-26", "G-ECHO", "A03", say_in(S42, "It speaks how many characters were entered."), None),
        ("X-27", "G-ECHO", "A35", say_in(S51, "The tooltip previews the first characters."), None),
        (
            "X-28",
            "G-ECHO",
            "B16",
            say_in(S42, "Not the list but the typed password is read aloud."),
            None,
        ),
        (
            "X-29",
            "G-HINT",
            "A05",
            say_in(S51, "Memory aid: an optional field stores a reminder."),
            None,
        ),
        (
            "X-30",
            "G-HINT",
            "A32",
            None,
            say_in(WALKTHROUGH_HEAD, "And the optional reminder field."),
        ),
        (
            "X-31",
            "G-HINT",
            "B18",
            None,
            say_in(WALKTHROUGH_HEAD, "And the clue line the user sets."),
        ),
        (
            "X-32",
            "G-BREACH",
            "A08",
            say_in(ERR_HEAD, "The breach row names the list it came from."),
            None,
        ),
        (
            "X-33",
            "G-BREACH",
            "A09",
            say_in(ERR_HEAD, "The breach frame says which leak and how often."),
            None,
        ),
        (
            "X-34",
            "G-AUTOCOMPLETE",
            "A12",
            sub_in(
                "2.2 Anatomy",
                "**Confirm new password** (CMP-040 + CMP-201, `new-password`)",
                "**Confirm new password** (CMP-040 + CMP-201, `one-time-code`)",
            ),
            None,
        ),
        (
            "X-35",
            "G-AUTOCOMPLETE",
            "B20",
            None,
            row_edit(
                "§A Hand-off checklist",
                "Accessible name and role",
                1,
                to('[x] the field; `autocomplete="off"` (spec §5.1)'),
            ),
        ),
        (
            "X-36",
            "G-DETAIL",
            "A15",
            say_in(ERR_HEAD, "The response's reason text is shown word for word."),
            None,
        ),
        (
            "X-37",
            "G-DETAIL",
            "B19",
            say_in(ERR_HEAD, "The problem's `title` and `detail` are shown as they arrive."),
            None,
        ),
        (
            "X-38",
            "G-METER",
            "A18",
            say_in(METER_HEAD, "A press is accepted only once the word reaches Fair."),
            None,
        ),
        ("X-39", "G-METER", "A20", say_in(METER_HEAD, "At Strong the bar turns green."), None),
        (
            "X-40",
            "G-METER",
            "A21",
            say_in(METER_HEAD, "At Strong a tick appears beside the word."),
            None,
        ),
        (
            "X-41",
            "G-METER",
            "A22",
            say_in(METER_HEAD, "The meter is drawn as the checklist's sixth line."),
            None,
        ),
        (
            "X-42",
            "G-METER",
            "B11",
            say_in(METER_HEAD, "The meter g&#97;tes the submit until Strong."),
            None,
        ),
        (
            "X-43",
            "G-METER",
            "B12",
            say_in(METER_HEAD, "The meter ga<span></span>tes the submit until Strong."),
            None,
        ),
        (
            "X-44",
            "G-METER",
            "B15",
            say_in(METER_HEAD, "Like Cancel, the strength meter gates the submit."),
            None,
        ),
        (
            "X-45",
            "G-CHARSET",
            "A25",
            say_in(METER_HEAD, f"The meter g{CYRILLIC_A}tes the submit."),
            None,
        ),
        (
            "X-46",
            "G-PROTOCOL",
            "lens 1 M-2",
            say_in(P172, "The SR pass also runs VoiceOver with Safari."),
            None,
        ),
        (
            "X-47",
            "G-SUCCESS",
            "lens 3 m-2",
            say_in("7.1 Success", "SESS:915\u2013922 keeps the caller's session."),
            None,
        ),
        (
            "X-48",
            "G-SECURITY",
            "A30",
            sub_in(
                "1.4 Rules stated once",
                "reads the same for every wrong value, at the same time",
                "reads differently when it is close to the real one",
            ),
            None,
        ),
        (
            "X-49",
            "G-CLEAR",
            "A31",
            None,
            row_edit(
                "§D The delta", "after a rejection", 2, to("the values kept, as shipped (§6.1)")
            ),
        ),
        (
            "X-50",
            "G-ERRMAP",
            "B02",
            add_row_after(
                ERR_HEAD,
                "`204`",
                "| `204` | yes | success | the card | all fields kept | W-24 | G-6 |",
            ),
            None,
        ),
        ("X-51", "G-CLEAR", "B03", row_edit(ERR_HEAD, "`429`", 4, to("cleared")), None),
        ("X-52", "G-CELLS", "B05", sub_in(DECK_HEAD, "\n| W-15 ", "\n\n| W-15 "), None),
        (
            "X-53",
            "G-METER",
            "B06",
            sub_in(
                "1.4 Rules stated once", "- **R-3 The meter advises.**", "- R-3 The meter advises."
            ),
            None,
        ),
    )
)
# X-n: paraphrases of a ruled behaviour, applied AFTER a simulated re-pin (the pins accept them),
# so the named semantic gate alone must catch each
PARAPHRASES: tuple[tuple[str, str, str, str], ...] = (
    ("X-1", "G-METER", "4.3 The meter", "Once it reads Strong the meter enables the submit."),
    (
        "X-2",
        "G-CLEAR",
        "6.2 The invite step",
        "A rejected value is retained in the new password field.",
    ),
    ("X-3", "G-FOCUS", "6.2 The invite step", "After a 422, focus lands on the alert region."),
    ("X-4", "G-SUCCESS", "7.1 Success", "Success redirects after a short countdown."),
    ("X-5", "G-HINT", "5.1 The fields", "A hint line may help the user remember."),
    ("X-6", "G-ECHO", "4.2 The checklist", "The announcement reads out the new password."),
    ("X-7", "G-PASTE", "5.1 The fields", "Password managers are blocked on the forced page."),
    ("X-8", "G-DETAIL", "6.2 The invite step", "The frame shows the server's detail."),
    ("X-9", "G-BREACH", "6.2 The invite step", "The message says how many times it was breached."),
    ("X-10", "G-CHECKLIST", "4.2 The checklist", "The checklist is a polite live region."),
    ("X-11", "G-REASONS", "3.1 The reasons", "An aged-out variant is drawn as a third reason."),
    ("X-12", "G-AUDIT", "12. Audit", "The outcome record includes the strength score."),
    ("X-13", "G-MOTION", "10. Motion", "The meter animates its segments."),
    ("X-14", "G-AUTOCOMPLETE", "5.1 The fields", "The confirm field takes autocomplete `off`."),
    ("X-15", "G-ESCAPE", "7.2 The sign-out escape", "The confirm signs out every session."),
    ("X-16", "G-BUSY", "5.3 Submitting", "The spinner is held for at least a second."),
    (
        "X-17",
        "G-MISMATCH",
        "5.2 The mismatch",
        "The confirm field shows the mismatch on each keystroke.",
    ),
    ("X-18", "G-NEWCMP", "2.3 Data", "A new component carries the meter."),
    ("X-19", "G-TOKENS", "4.3 The meter", "The meter takes the danger colour when Weak."),
    ("X-20", "G-RULES", "4.1 The rules", "A complexity rule joins the checklist."),
    ("X-21", "G-HOSTS", "2.3 Data", "The forced page and the section are two screens."),
    ("X-22", "G-RESET", "3.2 What an owner reset", "An owner reset issues a temporary password."),
    ("X-23", "G-ROLES", "8. Roles", "Viewers cannot change their password."),
    ("X-24", "G-SESSION", "17.2 The protocols", "An owner walkthrough was held."),
)
# N-n: negated forms that must trip nothing (after a simulated re-pin)
NEGATIONS: tuple[tuple[str, str, str], ...] = (
    ("N-1", "4.3 The meter", "The meter never enables or blocks the submit."),
    ("N-2", "5.1 The fields", "Paste is never blocked."),
    ("N-3", "9.2 Tab order", "On a field rejection focus never moves to the alert region."),
    ("N-4", "5.1 The fields", "No hint field exists."),
    ("N-5", "4.2 The checklist", "The status node never reads out the typed password."),
    ("N-6", "5.1 The fields", "No reminder or clue field exists."),
    ("N-7", "6.1 The signed-in hosts", "The breach row never says which leak or how often."),
    ("N-8", "6.1 The signed-in hosts", "The server's `detail` is never shown word for word."),
    ("N-9", "4.3 The meter", "The meter never sits inside the checklist and never turns green."),
)
# P-n: one per pin class; no semantic gate reads these, so G-RULED-PIN alone must catch each
PIN_PROBES: tuple[Mutation, ...] = (
    Mutation(
        "P-1",
        "G-RULED-PIN",
        "pin: a word in a sentence",
        spec=sub_in("1.2 Method", "Desk work at the base", "Desk work near the base"),
    ),
    Mutation(
        "P-2", "G-RULED-PIN", "pin: a sentence added", spec=say_in("1.2 Method", "It is careful.")
    ),
    Mutation(
        "P-3",
        "G-RULED-PIN",
        "pin: a sentence deleted",
        spec=sub_in(
            "1.2 Method", " The tool reads `22`'s two operations as text;", " The tool reads;"
        ),
    ),
    Mutation(
        "P-4",
        "G-RULED-PIN",
        "pin: a heading renamed",
        spec=sub_in("2.3 Data", "### 2.3 Data", "### 2.3 The data"),
    ),
    Mutation(
        "P-5",
        "G-RULED-PIN",
        "pin: a cell no gate reads",
        spec=row_edit(
            "1.3 Locked inputs",
            "S03 — the SCR-112 sessions section (PROPOSED, no hi-fi); the sign-out confirm;"
            " focus to the heading",
            2,
            to("§7"),
        ),
    ),
    Mutation(
        "P-6",
        "G-RULED-PIN",
        "pin: rows swapped",
        spec=in_lines(BIND_HEAD, swap_rows("card", "page")),
    ),
    Mutation(
        "P-7",
        "G-RULED-PIN",
        "pin: a line indented",
        spec=in_lines("1.4 Rules stated once", indented("- **R-6", 2)),
    ),
    Mutation("P-8", "G-RULED-PIN", "pin: the pins file damaged", patch=lambda: damaged_pins()),
    Mutation(
        "P-9",
        "G-RULED-PIN",
        "pin: a hand-off sentence",
        hand=sub_in("§G Dry-run needs", "Each role's items, in order;", "Each role's items;"),
    ),
)


PIN_UNITS_OVERRIDE: list[tuple[Unit, ...]] = []  # the self-test's simulated re-pin (X-n, N-n)
ALL_MUTATIONS: tuple[Mutation, ...] = (
    *MUTATIONS,
    *(
        Mutation(x, g, f"paraphrase after a re-pin: {s[:40]}", spec=say_in(h, s))
        for x, g, h, s in PARAPHRASES
    ),
    *ADVERSARY,
    *(Mutation(n, "", f"negation: {s[:40]}", spec=say_in(h, s)) for n, h, s in NEGATIONS),
    *PIN_PROBES,
)


# ---------------------------------------------------------------------------- self-test


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


def report(line: str) -> str:
    """One self-test report line: ASCII, at most REPORT_WIDTH characters."""
    return ascii_line(line)[:REPORT_WIDTH]


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
    lines += [f"  baseline FAIL {x}" for x in base_fails]
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
        lines.append(f"  section 15.2 lists {len(listed)} M-rows, the tool builds {len(built)}")
        lines += [
            f"    differ at {a} / {b}" for a, b in zip(listed, built, strict=False) if a != b
        ][:3]
    pristine = digest_texts(spec_f, hand_f, *(x for _n, x in plans))
    for mu in ALL_MUTATIONS:
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
        repin = mu.mid.startswith(("X-", "N-"))
        if repin:
            PIN_UNITS_OVERRIDE.append(tuple(ruled_units(s, h, values)))
        try:
            fails, _n2, _w, _c = audit(Texts(s, h, new_plans, values), git_fetch)
        except SystemExit as exc:
            fails = [str(exc)]
        finally:
            if undo:
                undo()
            if repin:
                PIN_UNITS_OVERRIDE.pop()
        new = [x for x in fails if x not in base_fails]
        if mu.gate:
            named = [x for x in new if x.startswith(f"[{mu.gate}]")]
            hit = bool(named) and len(new) == 1
        else:
            named, hit = [], not new
        restored = digest_texts(spec_f, hand_f, *(x for _n, x in plans)) == pristine
        levers = DRIFT or INSERT or CVD_OVERRIDE or PIN_UNITS_OVERRIDE or EXTRA_PATHS or BROKEN
        restored = restored and digest(paths) == on_disk and not levers
        ok = ok and hit and restored
        first = (named or new or ["nothing new"])[0]
        lines.append(
            f"  {mu.mid} [{mu.gate or 'none'}] {'ok' if hit else 'MISSED'} ({len(new)} new"
            f"{'' if restored else ', NOT RESTORED'}) - {first}"
        )
        if not hit:
            lines += [f"      new: {x}" for x in new]
    return ok, [report(x) for x in lines]


# ---------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="E09-D05 password audit (module docstring)")
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
        print(report(f"--self-test: {'ok' if ok else 'FAIL'} - {len(ALL_MUTATIONS)} mutations"))
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
        gates = len(LEXICON_GATES) + len(MEASURED_GATES) + 7
        shown = spec_path.relative_to(ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        print(f"## E09-D05 audit of {shown} (+ the hand-off) at base {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(notes))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK - every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(notes)} NOTE, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
