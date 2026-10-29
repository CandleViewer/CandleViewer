#!/usr/bin/env python3
"""E09-D10 (#193) audit: the accessibility design review of the auth band and its SR script.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base `e74121321e` (`git show`): the token JSON (dark = primitives +
semantic-dark, light = + semantic-light, hc = + semantic-hc), the plan texts the spec cites, the
merged E09 design docs (E09-D05 included, merged as #4930; D05 and D05H are read at their late
change #4939, `2145b48036`, LATE_REV), the QA plan and report, the CVD script's constants, the
merged frames' PNGs (TARGETS) and the ticket JSON (`E09.json`); then this ticket's spec from the
working tree, and the working-tree files the standing rule keeps untouched. There is no hand-off
file: the spec's own §C carries the A-rows (RULED BQ-1, BQ-32).

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: CITE (a figure parsed from
   its cited line at the base), RULED (the ruling's own figures), COUNT (the templates, the map,
   the script, the findings, the clauses, the assertions, the themes, the checks), CONTRAST
   (WCAG 2.x, truncated to two decimals, in three themes), CVD (the least ΔE76 under the three
   simulations, the least greyscale ratio) and TARGET (a boxed target's drawn width and height,
   read from the frame's own pixels with a stdlib PNG decoder, on the frames drawn at one CSS
   pixel per image pixel). `--fill` writes `VALUE<!--=KIND:key-->`; `--check`
   re-derives every anchored value with a left boundary (G-ANCHOR), and FAILs a figure typed by
   hand before a unit or a counted noun and a count written as a word (G-WORDCOUNT).
2. **The comment strip.** One pattern over the whole text, `re.DOTALL`; every HTML comment must be
   a value anchor the tool computes (G-MARKER); a `[//]: #` link-reference comment is refused
   (G-COMMENT). The lexicon gates read rendered text only.
3. **Cites.** Every cite is read at the base, D05 and D05H at the late change (G-CITE: FAIL
   when a line is gone or blank).
   G-VERSION is content-based: each cited range's lines must stand, in order and contiguous,
   somewhere in the file at `origin/main` (a move is fine; an edit inside a cited range FAILs; an
   unresolvable `origin/main` FAILs). Known limit: a cited block is widened only until it is
   unique at the base, so an in-place edit is masked when an unchanged copy of the whole widened
   block also stands elsewhere at `origin/main`; and pins collapse whitespace, so a doubled space
   inside a prose line is unpinned (render-neutral). It also reads the version line's semantics
   (the base, each pinned doc's last touch, every sha under the base or the recorded late
   change). G-QUOTE: every backticked snake name is
   verbatim in a source the line cites (or a core source); every quoted string of 12 characters
   or more is verbatim there or a frame's own words (IMG_STRINGS).
4. **Gates.** Lexicon gates read rows and prose after the comment strip (inline HTML tags
   dropped, entities decoded, NFKC, markup dropped, dashes to spaces, lower case; a claim is read
   per clause; a negation covers its own term within five words, a list coordinated after it,
   and a clause whose subject it negates; quoted copy, the mutation rows, the never-list, the
   reported cells and the clauses that report an F-row with its severity, ": F-3, a Major", are
   not claims; a clause that merely names an F-row is read). Each ruled behaviour has its
   table cells read and its synonyms refused, so a paraphrase planted after a re-pin (the X-n
   probes) fails a named gate; a lexicon is a finite word list, so a paraphrase outside every list
   is caught by the pins alone. G-UNTOUCHED compares committed and uncommitted paths with
   `git merge-base HEAD origin/main` and FAILs when it does not resolve; only this PR's three
   files may differ. G-CHARSET, G-CELLS, G-CLOSE, G-ENTROPY close the set.
5. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over EVERY unit of the spec, in
   RULED_PIN_TXT: each heading, table row (by its lead cell), rule line, prose sentence and fenced
   block, by region (heading path plus occurrence), location and exact text (NFKC, whitespace
   collapsed), with a line-shape tag per region. Anchored values are pinned with their values cut
   out (G-ANCHOR owns them). `--repin-ruled` is the only writer and refuses while a placeholder is
   unfilled. A pin finding in a section another gate already FAILs prints as a NOTE line.
6. **--self-test** applies every mutation of the spec's §16 (M-n) and the tool's own X-n
   (paraphrases), P-n (one per pin class) and N-n probes (which must trip nothing), with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names, and every
   text is restored byte-identically (sha256 in memory and on disk). The report is ASCII, every
   line at most 100 characters.

Usage (from the repo root):
  python3 -I docs/design/_tools/e09_d10_a11y_review_audit.py --check [SPEC] [--json] [--fill]
  python3 -I docs/design/_tools/e09_d10_a11y_review_audit.py --self-test
  python3 -I docs/design/_tools/e09_d10_a11y_review_audit.py --repin-ruled
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
import json
import math
import re
import subprocess
import sys
import unicodedata
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "e74121321e"  # every cite was read here (the spec's Inputs line; re-based from b49bd4853a)
HEAD = "origin/main"  # G-VERSION: a cited range edited at origin/main FAILs
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E09/E09-D10.md"
RULED_PIN_TXT = "docs/design/_tools/e09_d10_ruled_pins.txt"
TOOL_REL = "docs/design/_tools/e09_d10_a11y_review_audit.py"
DS_SRC_REL = "packages/ui/tokens"
# the standing rule: no `05`, `14`, `15`, `16`, `21`, `22`, `23` or `24` edit, and no edit of the
# merged E09 design docs; this PR's own three files are the only paths that may differ
UNTOUCHED = ("05", "14", "15", "16", "21", "22", "23", "24")
UNTOUCHED_DOCS = ("D02", "D03", "D03A", "D04", "D05", "D05H", "D06", "D08", "D09", "S03", "README")
OWN_PATHS = (SPEC_REL, TOOL_REL, RULED_PIN_TXT)
CITE_FILES: dict[str, str] = {
    "D02": "docs/design/E09/E09-D02.md",
    "D03": "docs/design/E09/E09-D03.md",
    "D03A": "docs/design/E09/E09-D03-a11y-audit.md",
    "D04": "docs/design/E09/E09-D04.md",
    "D05": "docs/design/E09/E09-D05.md",
    "D05H": "docs/design/E09/E09-D05-handoff.md",
    "D06": "docs/design/E09/E09-D06.md",
    "D08": "docs/design/E09/E09-D08.md",
    "D09": "docs/design/E09/E09-D09.md",
    "S03": "docs/design/E09/E09-S03.md",
    "RES": "docs/design/research/e09-auth-mental-models.md",
    "TM": "docs/security/threat-models/e09-auth-rbac.md",
    "Q04": "docs/qa/a11y/e09-auth-a11y-audit.md",
    "QP": "qa/plans/e09-auth-rbac-test-plan.md",
    "README": "docs/design/README.md",
    "CONST": "CONSTITUTION.md",
    "CVD": "docs/research/_tools/cvd_simulate.py",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "E09J": "docs/plan/backlog/E09.json",
}
TICKET_KEY = "E09-D10"
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SEMANTIC = ("semantic-dark", "semantic-light", "semantic-hc")

RULING_ID = "6495540658"
BQ_LIST_ID = "6495023892"
# the allow-list of comment ids the doc may cite: the ruling and the BQ list
RULED_IDS = (RULING_ID, BQ_LIST_ID)
OWNER_PENDING = "owner approval pending (#2701)"
MAX_WALK = 10  # RULED BQ-34: the owner walkthrough, at most ten items
REPORT_WIDTH = 100  # the self-test report: ASCII, at most 100 characters a line
# the ruling's own figures (BQ-15 confirmed: the warning at least 20 s; the 20-hour exemption)
RULED_VALUES = {"RULED:wcag.warn": "20", "RULED:wcag.long": "20"}
# the version line (spec **Start.**): every merged input's sha, in order
VERSION_SHAS = (
    "e74121321e",
    "a30c6ec6ad",
    "05c12212b4",
    "9750dc4bc9",
    "3669e891e6",
    "e1dfcb3e2f",
    "3c1a9d769d",
    "6359111929",
    "baccf724a1",
    "d117dc7328",
    "c99ad48d78",
    "b1425624b9",
    "132f1514b1",
    "c8ab5ab2f0",
    "2fd29ecc34",
    "ff8933a1c2",
    "a30c6ec6ad",
    "c99ad48d78",
    "d117dc7328",
    "2fd29ecc34",
    "c8ab5ab2f0",
    "2145b48036",
    "2145b48036",
)
# the pinned docs of the version line and the sha each is pinned at (its last touch at the base)
PINNED_DOCS = {
    "D02": "ff8933a1c2",
    "D03": "ff8933a1c2",
    "D04": "ff8933a1c2",
    "D06": "ff8933a1c2",
    "D03A": "a30c6ec6ad",
    "D05": "2145b48036",
    "D05H": "2145b48036",
    "D08": "c99ad48d78",
    "D09": "d117dc7328",
    "S03": "2fd29ecc34",
    "RES": "c8ab5ab2f0",
}
# the late change (S-14): #4939 merged after the base and edited D05 and D05H, so both are read
# at its merge; every other cite is read at the base
LATE = "2145b48036"
LATE_REV = {"D05": LATE, "D05H": LATE}
# named only in the version line: never pinned (no sha beside it) and never quoted (BQ-1)
NAMED_NO_SHA = ("#190", "#194", "#291", "#293", "#297", "#2110", "#4743")
CONSUMERS = (
    "story: E09-D11 (#291)",
    "story: E09-D12 (#194)",
    "story: E09-D07 (#190)",
    "story: E09-D05 (#188)",
    "frontend: E09-S03 (#1640)",
    "QA: E09-Q02 (#293)",
    "QA: E09-Q06 (#297)",
)
DRY_DATE = "2026-10-29"
# the merged frames' own words, read from their PNGs (the only quotes not in a text file)
IMG_STRINGS = (
    "Two-factor code",
    "Enter the 6-digit code from your authenticator app.",
    "Use a recovery code",
    "Enter one of the ten single-use codes you saved at enrolment.",
    "Back to authenticator code",
    "Confirm the code",
    "This enrolment challenge has expired. Start over from step 1.",
    "Admin screens need a fresh confirmation",
    "Too many attempts. Admin unlock is locked for 5:00. You can keep using the non-admin app.",
    (
        "Your admin session expired while editing. Your changes are kept and the save is held"
        " until you confirm."
    ),
    "Cancel - back to workspace",
    "Incorrect code. 2 attempts left.",
    "Save your recovery codes",
    "I've saved these somewhere I can find them later.",
)

# CITE values: key -> (cite id, line, pattern whose group 1 is the value)
CITE_VALUES: dict[str, tuple[str, int, str]] = {
    "bar.text": ("05", 125, r"≥(\d+(?:\.\d+)?):1 against their background"),
    "bar.ui": ("05", 126, r"≥(\d+):1 against adjacent colours"),
    "bar.hc": ("05", 130, r"\(≥(\d+):1 body text\)"),
    "target": ("05", 100, r"≥(\d+)×\d+ CSS px"),
    "target.comfortable": ("15", 64, r"(\d+)×\d+px comfortable"),
    "zoom": ("05", 131, r"usable with (\d+)% browser"),
    "warn": ("D06", 45, r"CMP-098 warning at (\d+) s"),
    "idle.default": ("21", 632, r"Idle timeout (\d+) min default"),
    "idle.min": ("21", 632, r"(\d+)–\d+ min"),
    "idle.max": ("21", 632, r"\d+–(\d+) min"),
    "abs": ("22", 17724, r"End of the (\d+) h absolute"),
    "enrol": ("22", 81, r"lives at most (\d+) minutes"),
    "mfa": ("22", 1131, r"\(`(\d+) min`\)"),
    "stepup": ("22", 12428, r"\((\d+) minutes after"),
    "grace.a": ("D08", 81, r"politely at (\d+) s and \d+ s"),
    "grace.b": ("D08", 81, r"politely at \d+ s and (\d+) s"),
    "debounce": ("15", 2569, r"debounced to (\d+) ms"),
    "admin": ("14", 2929, r"older than (\d+) minutes"),
    "lockout": ("22", 1146, r"for (\d+) minutes"),
    "totp": ("QP", 140, r"(\d+) s step"),
    "invite": ("22", 2037, r"valid for (\d+) h"),
    "jnd": ("D09", 342, r"JND floor (\d+(?:\.\d+)?)"),
}
# load-bearing fragments: (cite id, line at the base, text the line must hold)
CITED: tuple[tuple[str, int, str], ...] = (
    ("05", 116, "present on every screen"),
    ("05", 148, "Demo/Live environment switch confirmed"),
    ("05", 237, "a living checklist file maintained alongside this doc"),
    ("05", 96, "Focus is never silently stolen"),
    ("05", 97, "dismissible via `Esc`"),
    ("05", 85, "permanently reserved"),
    ("05", 238, "release blocker (P0)"),
    ("05", 224, "Safari-direct or non-Electron-browser testing is out of scope"),
    ("14", 169, "auto-advance per digit"),
    ("14", 171, 'screen reader announces "digit 3 of 6"'),
    ("14", 85, "RBAC denies server-side; the UI presents."),
    ("14", 2929, "older than 15 minutes"),
    ("15", 2587, 'exposed as **one** labelled input to assistive tech ("Six-digit authentication'),
    ("15", 1045, "warns before auth session/admin re-auth expiry"),
    ("15", 2551, 'the error region is `role="alert"` and receives focus on appearance'),
    ("15", 64, "the name does not change with the state"),
    ("22", 81, "lives at most 15 minutes from sign-in"),
    ("22", 94, "TOTP is mandatory for every user"),
    ("22", 1144, "Failures are deliberately uniform"),
    ("22", 1138, "it lives at most 15 minutes"),
    ("22", 17533, '"Username or email."'),
    ("04", 831, "indistinguishable"),
    ("04", 1925, "RR-15"),
    ("D03", 138, "The primary button and OtpInput are both disabled the instant auto-submit"),
    ("D03", 158, '`aria-label="Verification code"`'),
    ("D03", 120, '"Too many attempts. Try again in 00:47."'),
    ("D03", 123, "account-disabled"),
    ("D03A", 99, '"Show password" / "Hide password" (toggles)'),
    ("D03A", 25, "Finding and resolution — input border contrast"),
    ("D04", 83, '`aria-label="6-digit authentication code"`'),
    ("D04", 167, "disabled entirely (button hidden, not just greyed)"),
    ("D04", 142, "`color.status.warning.strong`"),
    ("D06", 60, "Esc does not dismiss SCR-005"),
    ("D06", 39, "unless it is a trading action control"),
    ("D08", 82, "Failure feedback is one frame"),
    ("D08", 83, "No motion oracle"),
    ("D08", 86, '`aria-live="off"`'),
    ("D08", 340, '"Invalid password or code."'),
    ("D08", 336, "Market data stopped."),
    ("D09", 143, "focus does **not** move"),
    ("S03", 84, "Expiry card: focus on Sign in."),
    ("S03", 132, '"Incorrect password. Try again."'),
    ("S03", 131, '"Signed out after too many unlock attempts."'),
    ("E09J", 646, '"E09-D07"'),
)

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z0-9]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
UNITS = r"(?:ms|s|hz|px|%|:1|fps|h|min)"
COUNTED = (
    r"(?:boards?|frames?|rows?|states?|pairs?|themes?|questions?|mutations?|characters?"
    r"|items?|consumers?|rules?|fields?|strings?|surfaces?|reasons?|minutes?|seconds?|hours?"
    r"|roles?|lines?|needs|checks?|entries|codes?|variants?|sections?|causes?|templates?"
    r"|features?|scenarios?|findings?|steps?|tasks?|transitions?|assertions?|clauses?"
    r"|criteria|blockers?|majors?|minors?|attempts?|days?|configurations?|measurements?)"
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


def rev_for(cid: str) -> str:
    """The revision a cite is read at: the base, or the late change for D05 and D05H."""
    return LATE_REV.get(cid, BASE)


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
    r"|\b(?:nothing|no \w+)\s+(?:stops|prevents|keeps|blocks)\b[^.;]{0,30}?\bfrom\b"
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
def under_head(sha: str) -> bool:
    """`sha` names a commit that `origin/main` contains (a late change)."""
    full = git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").strip()
    return bool(full) and git_out("merge-base", full, HEAD).strip() == full


@functools.cache
def under_base(sha: str) -> bool:
    """`sha` names a commit that is the base or one of its ancestors."""
    full = git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").strip()
    return bool(full) and git_out("merge-base", full, BASE).strip() == full


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


def line_after(prefix: str, new: str) -> Callable[[list[str]], list[str]]:
    def run(lines: list[str]) -> list[str]:
        i = next((n for n, ln in enumerate(lines) if ln.startswith(prefix)), None)
        return lines if i is None else [*lines[: i + 1], new, *lines[i + 1 :]]

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

# cells that report another text's words or a defect, not this ticket's claims:
# (doc, head, column) - the C-rows' conflicting texts, the F-rows' defect sentences, the script's
# must-not-hear column, the A-rows' Old cells
REPORTED = (
    ("spec", "1.2 Method", 1),  # pass 2's own rows (BQ-7)
    ("spec", "17.1 Contradictions", 1),
    ("spec", "12. The finding register", 4),
    ("spec", "13.3 The steps", 6),
    ("spec", "18. §C Copy-ready", 3),
)
NEEDS_HEAD = "(no hand-off)"  # there is no hand-off file (RULED BQ-1)


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


# ---------------------------------------------------------------------------- the spec's sections

TRACE_HEAD = "Acceptance-criteria trace"
METHOD_HEAD = "1.2 Method"
RULED_HEAD = "The questions BQ-1"
STATUS_HEAD = "0. Status"
LOCKED_HEAD = "1.3 Locked inputs"
RULES_HEAD = "1.4 Rules stated once"
INV_HEAD = "2. Inventory"
CLAUSE_HEAD = "3. Clause by clause"
WCAG_HEAD = "4. WCAG 2.2"
TRAPS_HEAD = "5.1 Traps"
OTP_HEAD = "5.2 The OTP control"
BUSY_HEAD = "5.3 Busy states"
MAP_HEAD = "6.2 The map"
LIVE_HEAD = "7. Live regions"
TL_HEAD = "8.1 The time-limit table"
EX_HEAD = "8.2 Essential exceptions"
CR_HEAD = "9.1 Carriers"
PAIRS_HEAD = "9.2 Contrast"
CVD_HEAD = "9.3 CVD and greyscale"
RBAC_HEAD = "10.2 The RBAC pattern"
COPY_HEAD = "11.1 The copy of record"
NEVER_HEAD = "11.2 The never-list"
FROW_HEAD = "12. The finding register"
SRCONF_HEAD = "13.1 Configurations"
SCRIPT_HEAD = "13.3 The steps"
ASSERT_HEAD = "14. The CI-checkable"
TEMPLATE_HEAD = "15. The `05` §10 templates"
MUTATION_HEAD = "16. The mutation list"
CROW_HEAD = "17.1 Contradictions"
GROW_HEAD = "17.2 The G-ledger"
QROW_HEAD = "17.3 Open questions"
HROW_HEAD = "17.4 Heuristic rows"
AROW_HEAD = "18. §C Copy-ready"
WALK_HEAD = "19.1 The story-role dry run"
WALKTHROUGH_HEAD = "19.3 The owner walkthrough"
DOD_HEAD = "20.1 DoD"
DEV_HEAD = "20.3 Deviations"


def rows_of(text: str, head: str) -> list[list[str]]:
    return table_rows(section(text, head))


def ided(text: str, head: str, prefix: str) -> list[list[str]]:
    """The rows of `head` whose lead cell is `prefix`-n."""
    return [r for r in rows_of(text, head) if re.fullmatch(rf"{prefix}-\d+", row_key(r[0]))]


def row_by_id(text: str, head: str, rid: str) -> list[str]:
    return next((r for r in rows_of(text, head) if row_key(r[0]) == rid), [])


def bars() -> dict[str, float]:
    v = cite_values()
    return {
        "text": float(v["CITE:bar.text"]),
        "non-text": float(v["CITE:bar.ui"]),
        "hc": float(v["CITE:bar.hc"]),
    }


def gherkin(spec: str) -> list[str]:
    """The fenced lines of §15 (the templates)."""
    lines = section(spec, TEMPLATE_HEAD).split("\n")
    fence = fenced(lines)
    return [ln for ln, f in zip(lines, fence, strict=True) if f and not FENCE_OPEN.match(ln)]


TEMPLATE_SCENARIOS = (
    "Keyboard-only operation",
    "Screen-reader operation",
    "Colour-independence",
    "Contrast",
    "Reduced motion",
    "Automated gates",
)


def features(spec: str) -> list[tuple[str, list[tuple[str, list[str]]]]]:
    """(feature line, [(scenario name, its step lines)]) for every Feature in §15."""
    out: list[tuple[str, list[tuple[str, list[str]]]]] = []
    for ln in gherkin(spec):
        s = ln.strip()
        if s.startswith("Feature:"):
            out.append((s, []))
        elif s.startswith("Scenario:") and out:
            out[-1][1].append((s.removeprefix("Scenario:").strip(), []))
        elif s and out and out[-1][1]:
            out[-1][1][-1][1].append(s)
    return out


# ---------------------------------------------------------------------------- tokens and colour


PAIR_THEMES = ("dark", "light", "hc")


def pair_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, PAIRS_HEAD) if re.match(r"P-\d+ ", r[0])]


def pair_id(cell: str) -> str:
    return cell.split(" ")[0].lower().replace("-", "")


def contrast_grid(spec: str) -> dict[str, dict[str, float]]:
    """pair id -> theme -> ratio, for every §9.2 row (foreground, background tokens)."""
    out: dict[str, dict[str, float]] = {}
    for r in pair_rows(spec):
        if len(r) < 3:
            continue
        fg, bg = r[1].strip("`"), r[2].strip("`")
        try:
            out[pair_id(r[0])] = {
                t: contrast(theme_hex(t, fg), theme_hex(t, bg)) for t in PAIR_THEMES
            }
        except SystemExit:
            continue
    return out


def bar_for(kind: str, theme: str) -> float | None:
    """The bar a §9.2 row's Bar cell names, per theme (high-contrast text takes `05`:130's)."""
    b = bars()
    if kind == "text":
        return b["hc"] if theme == "hc" else b["text"]
    if kind == "non-text":
        return b["non-text"]
    return None


def below(spec: str) -> list[tuple[str, str, float, float]]:
    """(pair, theme, ratio, bar) for every measurement under its bar."""
    out: list[tuple[str, str, float, float]] = []
    grid = contrast_grid(spec)
    for r in pair_rows(spec):
        pid = pair_id(r[0])
        kind = r[6] if len(r) > 6 else ""
        for t in PAIR_THEMES:
            bar = bar_for(kind, t)
            got = grid.get(pid, {}).get(t)
            if bar is not None and got is not None and math.floor(got * 100) / 100 < bar:
                out.append((pid, t, got, bar))
    return out


# CIE L*a*b* (D65) for ΔE76
def lab(hex6: str) -> tuple[float, float, float]:
    r, g, b = (srgb_to_linear(v) for v in rgb(hex6))
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: str, b: str) -> float:
    la, lb = lab(a), lab(b)
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(la, lb, strict=True)))


def cvd_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, CVD_HEAD) if re.fullmatch(r"CR-\d+", r[0])]


def cvd_pair(row: list[str]) -> tuple[str, str]:
    toks = re.findall(r"`([^`]+)`", row[1])
    return (toks[0], toks[1]) if len(toks) >= 2 else ("", "")


SIMS = ("protanopia", "deuteranopia", "tritanopia")


def cvd_grid(spec: str) -> dict[str, dict[str, float]]:
    """carrier id -> {theme: least ΔE76 under the three simulations, theme-grey: luminance}."""
    out: dict[str, dict[str, float]] = {}
    for r in cvd_rows(spec):
        a, b = cvd_pair(r)
        if not a:
            continue
        row: dict[str, float] = {}
        greys: list[float] = []
        try:
            for t in PAIR_THEMES:
                ha, hb = theme_hex(t, a), theme_hex(t, b)
                row[t] = min(delta_e(simulate(ha, k), simulate(hb, k)) for k in SIMS)
                greys.append(contrast(simulate(ha, "greyscale"), simulate(hb, "greyscale")))
        except SystemExit:
            continue
        row["grey"] = min(greys)
        out[r[0].lower().replace("-", "")] = row
    return out


# ---------------------------------------------------------------------------- computed values


def cite_values() -> Values:
    return {f"CITE:{k}": grab(p, base_line(c, n), k) for k, (c, n, p) in CITE_VALUES.items()}


def colour_values(spec: str) -> Values:
    v: Values = {}
    for pid, row in contrast_grid(spec).items():
        for t, r in row.items():
            v[f"CONTRAST:{pid}.{t}"] = show_ratio(r)
    for cid, row in cvd_grid(spec).items():
        for t in PAIR_THEMES:
            v[f"CVD:{cid}.{t}"] = f"{math.floor(row[t] * 10) / 10:.1f}"
        v[f"CVD:{cid}.grey"] = show_ratio(row["grey"])
    return v


def map_rows(spec: str) -> list[list[str]]:
    return ided(spec, MAP_HEAD, "T")


BODY = re.compile(r"\b(?:the )?(?:document )?body\b|^\s*$|^—$|^none$", re.IGNORECASE)


GAP = "none in any merged text"  # a missing announcement, routed to its F-row


def bound_say(cell: str) -> bool:
    """A map row's announcement is bound: not blank, not a dash, not "none" (a gap or silence)."""
    return cell not in ("", "—") and not cell.startswith("none")


def verdict_counts(spec: str) -> dict[str, int]:
    rows = [r for r in rows_of(spec, CLAUSE_HEAD) if r and r[0].startswith("`")]
    out = {"compliant": 0, "at risk": 0, "non-compliant": 0}
    for r in rows:
        if len(r) > 3 and r[3] in out:
            out[r[3]] += 1
    out["all"] = len(rows)
    return out


def severities(spec: str) -> dict[str, int]:
    out = {"Blocker": 0, "Major": 0, "Minor": 0, "Info": 0}
    for r in ided(spec, FROW_HEAD, "F"):
        if len(r) > 2 and r[2] in out:
            out[r[2]] += 1
    return out


def count_values(spec: str) -> Values:
    maps = map_rows(spec)
    feats = features(spec)
    sev = severities(spec)
    vc = verdict_counts(spec)
    steps = ided(spec, SCRIPT_HEAD, "SR")
    dry = [r[1] for r in ided(spec, METHOD_HEAD, "SR") if len(r) > 1]
    first = int(PASS2_FIRST.removeprefix("F-"))
    new_f = [r for r in ided(spec, FROW_HEAD, "F") if int(r[0][2:]) >= first]
    return {
        "COUNT:themes": str(len(themes_json_names())),
        "COUNT:features": str(len(feats)),
        "COUNT:scenarios": str(min((len(s) for _f, s in feats), default=0)),
        "COUNT:map.rows": str(len(maps)),
        "COUNT:map.dest": str(sum(1 for r in maps if len(r) > 4 and not BODY.search(r[4]))),
        "COUNT:map.announce": str(sum(1 for r in maps if len(r) > 5 and bound_say(r[5]))),
        "COUNT:map.gaps": str(sum(1 for r in maps if len(r) > 5 and r[5].startswith(GAP))),
        "COUNT:map.silent": str(
            sum(
                1
                for r in maps
                if len(r) > 5 and r[5].startswith("none") and not r[5].startswith(GAP)
            )
        ),
        "COUNT:map.body": str(sum(1 for r in maps if len(r) > 4 and BODY.search(r[4]))),
        "COUNT:script.steps": str(len(steps)),
        "COUNT:assertions": str(len(ided(spec, ASSERT_HEAD, "AS"))),
        "COUNT:clauses": str(vc["all"]),
        "COUNT:clauses.compliant": str(vc["compliant"]),
        "COUNT:clauses.at-risk": str(vc["at risk"]),
        "COUNT:clauses.non-compliant": str(vc["non-compliant"]),
        "COUNT:findings": str(len(ided(spec, FROW_HEAD, "F"))),
        "COUNT:findings.blocker": str(sev["Blocker"]),
        "COUNT:findings.major": str(sev["Major"]),
        "COUNT:findings.minor": str(sev["Minor"]),
        "COUNT:findings.info": str(sev["Info"]),
        "COUNT:pairs.below": str(len(below(spec))),
        "COUNT:pass2.rows": str(len(ided(spec, METHOD_HEAD, "P2"))),
        "COUNT:pass2.frows": str(len(new_f)),
        "COUNT:dry.yes": str(dry.count("yes")),
        "COUNT:dry.partly": str(dry.count("partly")),
        "COUNT:dry.no": str(dry.count("no")),
        "COUNT:cvd.checks": str(len(cvd_rows(spec)) * len(PAIR_THEMES) * (len(SIMS) + 1)),
    }


# ---------------------------------------------------------------------------- targets (BQ-23)

IMG_DIR = "docs/design/E09/img"
# key -> (frame, mode, x, y, bx, by): a point inside the boxed target; "fill" scans while a pixel
# differs from the surround sampled at (bx, by); "outline" (a stroke on the surround's own fill)
# scans across the interior, then across the stroke. Rows and columns through (x, y) carry no
# label text. The frames are drawn at one CSS pixel per image pixel (D03:52; D06:11).
TARGETS: dict[str, tuple[str, str, int, int, int, int]] = {
    "scr001.user": ("SCR-001-idle-hifi-dark.png", "fill", 600, 300, 460, 300),
    "scr001.password": ("SCR-001-idle-hifi-dark.png", "fill", 600, 366, 460, 366),
    "scr001.signin": ("SCR-001-idle-hifi-dark.png", "fill", 480, 410, 460, 410),
    "scr002.cell": ("SCR-002-idle-hifi-dark.png", "fill", 476, 292, 460, 292),
    "scr002.verify": ("SCR-002-idle-hifi-dark.png", "fill", 480, 374, 460, 374),
    "scr005.password": ("E09-D06-SCR-005-locked-default.png", "fill", 600, 368, 432, 368),
    "scr005.estop": ("E09-D06-SCR-005-locked-default.png", "outline", 450, 520, 0, 0),
    "scr005.signout": ("E09-D06-SCR-005-locked-default.png", "outline", 570, 520, 0, 0),
    "scr005.unlock": ("E09-D06-SCR-005-locked-default.png", "fill", 745, 520, 732, 520),
    "cmp098.locknow": (
        "E09-D06-CMP-098-session-timeout-warning-60s.png",
        "outline",
        585,
        416,
        0,
        0,
    ),
    "cmp098.stay": ("E09-D06-CMP-098-session-timeout-warning-60s.png", "fill", 695, 416, 680, 416),
    "scr149.password": ("E09-D06-SCR-149-default.png", "fill", 600, 305, 410, 305),
    "scr149.code": ("E09-D06-SCR-149-default.png", "fill", 600, 380, 410, 380),
    "scr149.cancel": ("E09-D06-SCR-149-default.png", "outline", 430, 440, 0, 0),
    "scr149.confirm": ("E09-D06-SCR-149-default.png", "fill", 720, 440, 690, 440),
}
PIX_TOL = 6  # the largest channel difference still read as the same colour


@functools.lru_cache(maxsize=16)
def git_show_bytes(rev: str, rel: str) -> bytes | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


@functools.lru_cache(maxsize=8)
def png_rows(frame: str) -> tuple[int, int, int, tuple[bytes, ...]]:
    """(width, height, bytes per pixel, rows) of an 8-bit RGB or RGBA PNG at the base."""
    data = git_show_bytes(BASE, f"{IMG_DIR}/{frame}")
    if data is None or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"FAIL parse: {frame} is not a PNG at {BASE}")
    i, idat, w, h, bpp = 8, b"", 0, 0, 0
    while i < len(data):
        n = int.from_bytes(data[i : i + 4], "big")
        kind, chunk = data[i + 4 : i + 8], data[i + 8 : i + 8 + n]
        i += 12 + n
        if kind == b"IHDR":
            w, h = int.from_bytes(chunk[0:4], "big"), int.from_bytes(chunk[4:8], "big")
            if chunk[8] != 8 or chunk[9] not in (2, 6) or chunk[12] != 0:
                raise SystemExit(f"FAIL parse: {frame} is not 8-bit RGB(A), non-interlaced")
            bpp = 3 if chunk[9] == 2 else 4
        elif kind == b"IDAT":
            idat += chunk
    raw, stride, rows, prev, p = zlib.decompress(idat), w * bpp, [], bytearray(w * bpp), 0
    for _y in range(h):
        kind_f, line = raw[p], bytearray(raw[p + 1 : p + 1 + stride])
        p += 1 + stride
        for x in range(stride) if kind_f else ():
            a = line[x - bpp] if x >= bpp else 0
            c = prev[x - bpp] if x >= bpp else 0
            pred = (a, prev[x], (a + prev[x]) // 2, _paeth(a, prev[x], c))[kind_f - 1]
            line[x] = (line[x] + pred) & 255
        rows.append(bytes(line))
        prev = line
    return w, h, bpp, tuple(rows)


def measure(key: str) -> tuple[int, int]:
    """A boxed target's drawn (width, height) in CSS px (see TARGETS)."""
    frame, mode, x, y, bx, by = TARGETS[key]
    w, h, bpp, rows = png_rows(frame)

    def px(px_x: int, px_y: int) -> bytes:
        return rows[px_y][px_x * bpp : px_x * bpp + 3]

    def same(a: bytes, b: bytes) -> bool:
        return max(abs(p - q) for p, q in zip(a, b, strict=True)) <= PIX_TOL

    def extent(dx: int, dy: int) -> int:
        cx, cy = x, y
        if mode == "fill":
            bg = px(bx, by)
            while 0 <= cx + dx < w and 0 <= cy + dy < h and not same(px(cx + dx, cy + dy), bg):
                cx, cy = cx + dx, cy + dy
        else:
            inner = px(x, y)
            while same(px(cx + dx, cy + dy), inner):
                cx, cy = cx + dx, cy + dy
            while 0 <= cx + dx < w and 0 <= cy + dy < h and not same(px(cx + dx, cy + dy), inner):
                cx, cy = cx + dx, cy + dy
        return cx if dx else cy

    return extent(1, 0) - extent(-1, 0) + 1, extent(0, 1) - extent(0, -1) + 1


@functools.lru_cache(maxsize=1)
def target_values() -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for key in TARGETS:
        tw, th = measure(key)
        out += [(f"TARGET:{key}.w", str(tw)), (f"TARGET:{key}.h", str(th))]
    return tuple(out)


@functools.lru_cache(maxsize=4)
def compute_cached(spec: str) -> tuple[tuple[tuple[str, str], ...], str]:
    v: Values = {}
    v |= cite_values()
    v |= dict(RULED_VALUES)
    v |= count_values(spec)
    v |= colour_values(spec)
    v |= dict(target_values())
    extra = {
        "contrast": {
            p: {t: round(r, 3) for t, r in row.items()} for p, row in contrast_grid(spec).items()
        },
        "below_bar": [[p, t, round(r, 3), b] for p, t, r, b in below(spec)],
        "cvd": {c: {t: round(x, 2) for t, x in row.items()} for c, row in cvd_grid(spec).items()},
        "cvd_constants_match": cvd_constants_at_base() == own_cvd_constants(),
    }
    return tuple(sorted(v.items())), json.dumps(extra, ensure_ascii=False)


def compute(spec: str, hand: str = "") -> tuple[Values, dict[str, object]]:
    del hand  # there is no hand-off file (RULED BQ-1)
    items, extra = compute_cached(spec)
    return dict(items), json.loads(extra)


# ---------------------------------------------------------------------------- anchors

# copy columns a figure may sit in: (section, columns) - the mutation rows, the dry-run counts,
# the A-rows' Old and New cells
COPY_CELLS = (
    ("16. The mutation", (1, 2)),
    ("19.1 The story-role", (2, 3, 4)),
    ("18. §C Copy-ready", (3, 4)),
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
def cited_block(rel: str, a: int, b: int, rev: str = BASE) -> tuple[str, ...]:
    """unique_block at the cite's revision, cached (it never changes within a run)."""
    return tuple(unique_block((git_show(rev, rel) or "").split("\n"), a, b))


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
                rev = rev_for(cid)
                base_t = git_show(rev, rel) if rel else None
                if rel is None or base_t is None:
                    fails.append(("G-CITE", f"`{cid}`:{a} no such file", doc, sec))
                    continue
                if (cid, a, b) in done:
                    continue
                done.add((cid, a, b))
                base = base_t.split("\n")
                if b < a or a < 1 or b > len(base) or not base[a - 1].strip():
                    fails.append(("G-CITE", f"`{cid}`:{a}–{b} not a range at {rev}", doc, sec))
                    continue
                if not base[b - 1].strip():
                    fails.append(("G-CITE", f"`{cid}`:{b} is blank at {rev}", doc, sec))
                    continue
                if not head_ok():
                    continue
                head_t = git_fetch_head(rel)
                block = list(cited_block(rel, a, b, rev))
                if head_t is None or not block_at(head_t.split("\n"), block):
                    msg = f"`{cid}`:{a}–{b} edited at {HEAD}: re-read and re-point the cite"
                    fails.append(("G-VERSION", msg, doc, sec))
    for cid, n, frag in CITED:
        rel = cite_path(cid)
        bt = git_show(rev_for(cid), rel) if rel else None
        base = bt.split("\n") if bt is not None else []
        if n > len(base) or frag not in base[n - 1]:
            hits = [i + 1 for i, ln in enumerate(base) if frag in ln]
            msg = f'`{cid}`:{n} "{frag[:40]}" not on the line (found {hits[:4]})'
            fails.append(("G-CITE", msg, None, None))
    return fails, len(done) + len(CITED)


# ---------------------------------------------------------------------------- the D10 gates

# a clause that REPORTS an F-row with its severity (": F-3, a Major", "is F-1, a Blocker") states
# a defect, never the design; a clause that merely names an F-row ("as F-3 records") is read
REPORTS = (  # rendered: dashes become spaces
    r"(?::|\bis|\bare)\s+f \d+(?:(?:,|\s+and|\s+to)\s+f \d+)*,?\s+(?:a |an |both )?"
    r"(?:blocker|major|minor|info)s?\b"
)


def unless_f(extra: str = "") -> str:
    return REPORTS + (f"|{extra}" if extra else "")


def g_trace(t: Texts) -> list[Finding]:
    """The AC trace holds AC1 ... AC6 and the T rows, each with a status."""
    sec = spec_sec(t, TRACE_HEAD)
    rows = rows_of(t.spec, TRACE_HEAD)
    lead = [r[0].split(" ")[0] for r in rows]
    bad = [
        F("G-TRACE", f"the trace lacks {ac}", "spec", sec)
        for ac in ("AC1", "AC2", "AC3", "AC4", "AC5", "AC6", "T")
        if ac not in lead
    ]
    bad += [
        F("G-TRACE", f"{r[0][:30]!r} has no status", "spec", sec)
        for r in rows
        if len(r) < 3 or not r[2].strip()
    ]
    return bad


RULED_DIFFERENTLY = ("BQ-3", "BQ-12", "BQ-16", "BQ-17", "BQ-27")
BITE = ("BQ-13", "BQ-14", "BQ-15", "BQ-20", "BQ-24")
RULING_NEEDS = (
    "Thirty defaults are taken as proposed",
    "the six riders bind",
    "one generic failure",
    "graded at risk with an F-row until the `05` owner applies A-5, never compliant",
    "where focus already moves into an `alertdialog` (lock, expiry) that is the carrier",
    "no SCR-005 exception to the copy ladder",
    '"Username or email" and "Sign in" (#194 BQ-13)',
    "absent by plan in v1",
    "never as compliant",
    "the compatible remedy is a warning and a restart that keeps progress",
    "no verdict depends on A-5",
    "E09-D05 pinned at `e1dfcb3e2f`",
)


def g_ruled(t: Texts) -> list[Finding]:
    """The RULED paragraph: the ruling and the list by id; the five ruled differently, each with
    the ruling's words; the six riders; the five confirmations that bite; every comment id cited is
    one of RULED_IDS."""
    sec = spec_sec(t, RULED_HEAD)
    body = section(t.spec, RULED_HEAD)
    head = body.split("\n")[0]
    para = next((p for p in body.split("\n") if p.startswith("**RULED.**")), "")
    bad: list[Finding] = []
    if RULING_ID not in head or BQ_LIST_ID not in head:
        bad.append(F("G-RULED", "the heading does not name the ruling and the list", "spec", sec))
    for q in RULED_DIFFERENTLY:
        if not re.search(rf"\*\*{q}:\*\*", para):
            bad.append(
                F("G-RULED", f"the RULED paragraph does not rule {q} as worded", "spec", sec)
            )
    bite = para.split("**Confirmed and named because they bite:**", 1)[-1]
    for q in BITE:
        if not re.search(rf"\b{q}\b", bite):
            bad.append(F("G-RULED", f"the confirmations lack {q}", "spec", sec))
    for need in RULING_NEEDS:
        if need not in para:
            bad.append(F("G-RULED", f"the RULED paragraph lacks {need[:40]!r}", "spec", sec))
    for i, line in enumerate(t.spec.split("\n"), 1):
        for m in COMMENT_ID.finditer(CODE.sub(" ", strip_comments(line))):
            if m[1] not in RULED_IDS:
                msg = f"spec:{i} comment id {m[1]} is not the ruling's"
                bad.append(F("G-RULED", msg, "spec", h2_at(t.spec, i)))
    return bad


SURFACES = ("SCR-001", "SCR-002", "SCR-003", "SCR-004", "SCR-005", "SCR-006", "SCR-149", "RBAC")


def g_inventory(t: Texts) -> list[Finding]:
    """RULED BQ-5: the eight surfaces reviewed, each with a Feature in §15."""
    sec = spec_sec(t, INV_HEAD)
    rows = rows_of(t.spec, INV_HEAD)
    feats = " ".join(f for f, _s in features(t.spec))
    bad: list[Finding] = []
    for s in SURFACES:
        hit = [r for r in rows if s in r[0] and len(r) > 1 and r[1] == "reviewed"]
        if not hit:
            bad.append(F("G-INVENTORY", f"§2 does not review {s}", "spec", sec))
        if s not in feats:
            bad.append(F("G-INVENTORY", f"§15 has no Feature for {s}", "spec", sec))
    return bad


VERDICTS = ("compliant", "at risk", "non-compliant", "N/A")


def g_clause(t: Texts) -> list[Finding]:
    """R-3: a compliant clause names no F-row; an at-risk clause names an F-row, or a C-row with
    its A-row; a non-compliant clause names a Blocking or Major F-row; N/A states its reason."""
    sec = spec_sec(t, CLAUSE_HEAD)
    sev = {r[0]: r[2] for r in ided(t.spec, FROW_HEAD, "F") if len(r) > 2}
    bad: list[Finding] = []
    for r in [r for r in rows_of(t.spec, CLAUSE_HEAD) if r and r[0].startswith("`")]:
        if len(r) < 5:
            continue
        v, f = r[3], r[4]
        frows = re.findall(r"F-\d+", f)
        if ".." in f:
            a, b = (int(x) for x in re.findall(r"F-(\d+)\.\.F-(\d+)", f)[0])
            frows += [f"F-{k}" for k in range(a, b + 1)]
        if v not in VERDICTS:
            bad.append(F("G-CLAUSE", f"{r[0]}: verdict {v!r}", "spec", sec))
        elif v == "compliant" and frows:
            bad.append(F("G-CLAUSE", f"{r[0]}: compliant with {frows[0]}", "spec", sec))
        elif v == "at risk" and not (
            frows or (re.search(r"C-\d+", f) and re.search(r"A-\d+", f)) or re.search(r"Q-\d+", f)
        ):
            bad.append(F("G-CLAUSE", f"{r[0]}: at risk with no row", "spec", sec))
        elif v == "non-compliant" and not any(sev.get(x) in ("Blocker", "Major") for x in frows):
            bad.append(
                F("G-CLAUSE", f"{r[0]}: non-compliant with no Blocker or Major", "spec", sec)
            )
        elif v == "N/A" and len(r[2].split()) < 3:
            bad.append(F("G-CLAUSE", f"{r[0]}: N/A without its reason", "spec", sec))
    return bad


def g_envbadge(t: Texts) -> list[Finding]:
    """The BQ-8 rider: SCR-001's environment-badge clause (`05`:116) is never compliant; it
    carries C-25 and A-8."""
    sec = spec_sec(t, CLAUSE_HEAD)
    row = next(
        (r for r in rows_of(t.spec, CLAUSE_HEAD) if r and r[0] == "`4.1`" and "`05`:116" in r[1]),
        [],
    )
    if len(row) < 5:
        return [F("G-ENVBADGE", "§3 lacks the `05`:116 row", "spec", sec)]
    bad: list[Finding] = []
    if row[3] == "compliant":
        bad.append(F("G-ENVBADGE", "the environment badge is graded compliant", "spec", sec))
    if "C-25" not in row[4] or "A-8" not in row[4]:
        bad.append(F("G-ENVBADGE", "the badge row lacks C-25 and A-8", "spec", sec))
    return bad


MAP_COLS = 9
MAP_VERDICT = re.compile(r"^(?:compliant|(?:at risk|non-compliant) \([FG]-\d+(?:, [FG]-\d+)*\))$")


def g_map(t: Texts) -> list[Finding]:
    """AC3: every transition names a focus destination that is never the body, and an
    announcement; "unchanged" only with a named element before; a row with no merged
    announcement carries its F-row; ids in order; every T-n cited exists."""
    sec = spec_sec(t, MAP_HEAD)
    rows = map_rows(t.spec)
    bad: list[Finding] = []
    ids = [row_key(r[0]) for r in rows]
    if ids != [f"T-{k}" for k in range(1, len(rows) + 1)]:
        bad.append(F("G-MAP", "the T-rows are not T-1 … T-n in order", "spec", sec))
    for r in rows:
        if len(r) != MAP_COLS:
            bad.append(F("G-MAP", f"{r[0]}: {len(r)} cells", "spec", sec))
            continue
        before, after, say, verdict = r[3], r[4], r[5], r[8]
        if BODY.search(after):
            bad.append(F("G-MAP", f"{r[0]}: focus after is {after!r}", "spec", sec))
        if after.startswith("unchanged") and re.fullmatch(r"none|—|", before):
            bad.append(F("G-MAP", f"{r[0]}: unchanged from no element", "spec", sec))
        if say in ("", "—"):
            bad.append(F("G-MAP", f"{r[0]}: no announcement", "spec", sec))
        if not MAP_VERDICT.match(verdict):
            bad.append(F("G-MAP", f"{r[0]}: verdict {verdict!r}", "spec", sec))
        if say.startswith("none in any merged text") and "(F-" not in verdict:
            bad.append(F("G-MAP", f"{r[0]}: a missing announcement with no F-row", "spec", sec))
    if not any(r[1] == "CMP-098" and "Lock now" in r[2] for r in rows if len(r) > 2):
        bad.append(F("G-MAP", "no CMP-098 Lock now row (BQ-11)", "spec", sec))
    defined = set(ids)
    for x in sorted(set(re.findall(r"(?<![\w-])T-\d+\b", CODE.sub(" ", t.spec))) - defined):
        bad.append(F("G-MAP", f"{x} is cited but not in the map", "spec", sec))
    return bad


def g_generic(t: Texts) -> list[Finding]:
    """RULED BQ-12 (differently): SCR-001 has one generic failure row; no SCR-001 row or script
    step carries a distinct disabled or locked failure; C-23 and C-24 carry D03:123-124 and
    D08:83."""
    sec = spec_sec(t, MAP_HEAD)
    bad: list[Finding] = []
    fails = [r for r in map_rows(t.spec) if r[1].startswith("SCR-001") and len(r) > 2]
    generic = [r for r in fails if "generic failure" in r[2]]
    if len(generic) != 1:
        bad.append(F("G-GENERIC", f"{len(generic)} generic-failure rows for SCR-001", "spec", sec))
    for r in fails:
        if r not in generic and re.search(r"\b(?:disabled|locked)\b", r[2] + r[5]):
            bad.append(F("G-GENERIC", f"{r[0]}: a distinct disabled or locked row", "spec", sec))
    for r in ided(t.spec, SCRIPT_HEAD, "SR"):
        if re.search(r"viewer-disabled|\b(?:disabled|locked) account\b", " ".join(r[1:3])):
            msg = f"{r[0]}: a distinct disabled or locked script step"
            bad.append(F("G-GENERIC", msg, "spec", spec_sec(t, SCRIPT_HEAD)))
    crows = {r[0]: r for r in ided(t.spec, CROW_HEAD, "C")}
    for cid, cite in (("C-23", "D03:123–124"), ("C-24", "D08:83")):
        if cite not in " | ".join(crows.get(cid, [])):
            bad.append(
                F("G-GENERIC", f"{cid} does not carry {cite}", "spec", spec_sec(t, CROW_HEAD))
            )
    bad += as_findings(
        "G-GENERIC",
        "a distinct disabled or locked sign-in failure",
        claims(
            lex(t),
            r"\b(?:distinct|separate|own|dedicated) (?:disabled|locked|account[- ]disabled)"
            r"(?: account)? (?:failure|banner|message|row|state|string)\b"
            r"|\b(?:disabled|locked) accounts? (?:get|gets|hear|hears|see|sees|show|shows)"
            r" (?:a |their |its )?(?:own|distinct|different|separate)\b"
            r"|\b(?:distinct|separate|own|dedicated|different) (?:failure|banner|message|row"
            r"|state|string|step)s? for (?:a |an |the )?(?:disabled|locked)(?: account)?\b",
            unless=unless_f(r"\bc 2[34]\b|\bone generic\b"),
        ),
    )
    return bad


OTP_NEEDS = (
    "one `<input>`",
    '`autocomplete="one-time-code"`',
    "paste of the whole code accepted",
    'no "digit 3 of 6" announcement',
    "its accessible name contains the visible heading",
    "the auto-submit fires once",
    "focus stays in the field",
)
OTP_TERM = (
    r"\b(?:six|6)[- ](?:separate |individual )?(?:inputs|edit fields|text ?boxes|fields|controls)"
    r"\b(?:[^.;]{0,30}\b(?:exposed|announced|kept|stay|stays|remain|remains))?"
    r"|\b(?:keep|keeps|kept|expose[sd]?|exposing)\b[^.;]{0,30}\b(?:six|6)[- ]"
    r"(?:inputs|boxes|fields|edit fields)\b"
    r"|\bauto[- ]advance\w*\b|\bdigit \w+ of (?:6|six)\b"
    r"|\bfocus (?:hops?|hopping|jumps?|jumping|moves?|moving|advances?|advancing|skips?|skipping)"
    r"\b[^.;]{0,30}\b(?:next|forward|following)\b"
    r"|\b(?:six|6) (?:[\w-]+ )?(?:boxes|cells|inputs|fields)\b[^.;]{0,40}\bfocus (?!stays)\w+"
)


def g_otp(t: Texts) -> list[Finding]:
    """RULED BQ-13 (confirmed): §5.2 states the one-input contract; F-1 is a Blocker against
    E09-D03; no clause makes the OTP six inputs, auto-advance per digit or announce digits."""
    sec = spec_sec(t, OTP_HEAD)
    body = section(t.spec, OTP_HEAD)
    bad = [F("G-OTP", f"§5.2 lacks {n[:40]!r}", "spec", sec) for n in OTP_NEEDS if n not in body]
    f1 = row_by_id(t.spec, FROW_HEAD, "F-1")
    if len(f1) < 6 or not f1[5].startswith("E09-D03 "):
        bad.append(F("G-OTP", "F-1 is not owned by E09-D03", "spec", spec_sec(t, FROW_HEAD)))
    bad += as_findings(
        "G-OTP",
        "the OTP as six inputs or per-digit",
        claims(
            lex(t),
            OTP_TERM,
            near=r"\b(?:otp|code field|code|cmp-204|cells?|boxes|digits?)\b",
            unless=unless_f(r"\bc 7\b|\ba [12]\b|\bstyled as six cells\b"),
        ),
    )
    return bad


LOCKOUT = ("F-1", "F-2", "F-25")  # F-25: pass 2 (§1.2)


def g_lockout(t: Texts) -> list[Finding]:
    """AC6: every lockout path is a Blocker, however rare."""
    sec = spec_sec(t, FROW_HEAD)
    bad: list[Finding] = []
    for fid in LOCKOUT:
        r = row_by_id(t.spec, FROW_HEAD, fid)
        if len(r) < 3 or r[2] != "Blocker":
            bad.append(F("G-LOCKOUT", f"{fid} (a lockout path) is not a Blocker", "spec", sec))
    if "**Blocker:**" not in section(t.spec, RULES_HEAD) or "however rare" not in section(
        t.spec, RULES_HEAD
    ):
        bad.append(F("G-LOCKOUT", "R-1 lacks the lockout rule", "spec", spec_sec(t, RULES_HEAD)))
    bad += as_findings(
        "G-LOCKOUT",
        "a lockout path graded below Blocker",
        claims(
            lex(t),
            r"\b(?:lock ?out|lockout) paths?\b[^.;]{0,60}\b(?:graded|rated|logged|classed|kept)\b"
            r"[^.;]{0,20}\b(?:major|minor|info)\b"
            r"|\b(?:rare|unlikely)\b[^.;]{0,40}\b(?:graded|rated)\b[^.;]{0,10}\b(?:major|minor)\b",
        ),
    )
    return bad


BUSY_NEEDS = (
    "becomes `readonly`, never `disabled`",
    '`aria-disabled="true"` and `aria-busy="true"` and stays focusable',
    "focus does not move",
    "focus rests on the dialog",
)
BUSY_TERM = (
    r"\b(?:natively )?(?:disable[sd]?|disabling)\b[^.;]{0,30}\bfocused (?:field|control|input|"
    r"element|button|submit)s?\b"
    r"|\bfocused (?:field|control|input|element|button|submit)s? (?:is |are |becomes? |gets? |goes"
    r" )?(?:natively )?(?:disabled|removed from the tab order)\b"
    r"|\b(?:focus|it) (?:drops|falls|moves|goes) to the (?:document )?body\b"
    r"|\b(?:drops?|dropping|dropped|falls?|falling|fell|moved?|moving|goes|going|went|lands?"
    r"|landing|sent|sends?)(?: focus)? (?:to|onto|into) the (?:document )?body\b"
    r"|\b(?:holds|has|with|holding) focus\b[^.;]{0,30}\b(?:greyed|grayed|disabled|inert"
    r"|(?:taken|removed|dropped) (?:out of|from) the tab (?:order|sequence))\b"
    r"|\bfocus\b[^.;]{0,20}\b(?:left|lands?|goes|stays)\b[^.;]{0,10}\bwherever\b[^.;]{0,30}"
    r"\b(?:browser|user agent|platform)\b"
)
BUSY_SURFACES = ("SCR-001", "SCR-002", "SCR-003", "SCR-004", "SCR-005", "SCR-006", "SCR-149")


def g_busy(t: Texts) -> list[Finding]:
    """RULED BQ-14 (confirmed): R-5 as worded; F-3 a Major; no clause disables the focused
    control."""
    sec = spec_sec(t, RULES_HEAD)
    body = section(t.spec, RULES_HEAD)
    bad = [F("G-BUSY", f"R-5 lacks {n[:40]!r}", "spec", sec) for n in BUSY_NEEDS if n not in body]
    f3 = row_by_id(t.spec, FROW_HEAD, "F-3")
    if len(f3) < 3 or f3[2] != "Major":
        bad.append(F("G-BUSY", "F-3 is not a Major", "spec", spec_sec(t, FROW_HEAD)))
    maps = map_rows(t.spec)
    for surface in BUSY_SURFACES:
        if not any(r[1].startswith(surface) and "R-5" in r[4] for r in maps if len(r) > 4):
            msg = f"{surface} has no busy row under R-5 (BQ-14)"
            bad.append(F("G-BUSY", msg, "spec", spec_sec(t, MAP_HEAD)))
    bad += as_findings(
        "G-BUSY",
        "the focused control disabled",
        claims(
            lex(t),
            BUSY_TERM,
            unless=unless_f(
                r"\bnames where focus goes\b|\bpermission_change\b|\bpermission change\b"
            ),
        ),
    )
    return bad


TL_READING = re.compile(
    r"^(?:satisfies 2\.2\.1|the Epic's documented exception|non-compliant|the Essential exception"
    r"|at risk|not a limit|over the)"
)
LONGER_TERM = (
    r"\b(?:longer|extend(?:ed|able|s)?|lengthen\w*|prolong\w*|more time for)\b[^.;]{0,30}"
    r"\b(?:enrolment|enrollment)(?: only)?(?: session| window)\b"
    r"|\b(?:enrolment|enrollment)(?: only)? (?:session|window)\b[^.;]{0,30}"
    r"\b(?:extended|lengthened|made longer|raised|doubled)\b"
)


def g_time(t: Texts) -> list[Finding]:
    """RULED BQ-15 (confirmed) and AC4: every limit carries a 2.2.1 reading; the idle lock
    satisfies 2.2.1 and is never an exception; the enrolment window is non-compliant with F-2 and
    G-1; G-1 never asks for a longer or extendable enrolment-only session."""
    sec = spec_sec(t, TL_HEAD)
    rows = ided(t.spec, TL_HEAD, "TL")
    bad: list[Finding] = []
    for r in rows:
        if len(r) < 6 or not TL_READING.match(r[4]):
            bad.append(F("G-TIME", f"{r[0]}: no 2.2.1 reading", "spec", sec))
    tl1 = next((r for r in rows if r[0] == "TL-1"), [])
    if len(tl1) < 6 or not tl1[4].startswith("satisfies 2.2.1, never an exception"):
        bad.append(F("G-TIME", "TL-1 is not read as satisfying 2.2.1", "spec", sec))
    tl3 = next((r for r in rows if r[0] == "TL-3"), [])
    if len(tl3) < 6 or not tl3[4].startswith("non-compliant") or "F-2" not in tl3[5]:
        bad.append(F("G-TIME", "TL-3 lacks F-2 and its reading", "spec", sec))
    bad += as_findings(
        "G-TIME",
        "a longer or extendable enrolment window asked",
        claims(
            lex(t),
            LONGER_TERM,
            unless=r"\bnot asked\b|\bno longer or extendable\b",
        ),
    )
    return bad


LIVE_NEEDS = (
    '`aria-live="off"`',
    "is at risk: F-19 to F-24",
    "the carrier, so they are compliant",
    "No verdict is raised to compliant on the strength of A-5",
)
# the carrier rows: focus moves into the lock's or the expiry's `alertdialog` (RULED BQ-16)
CARRIER = re.compile(
    r"^(?:SCR-005's password field|the expiry card's Sign in" r"|the signed-out card's Sign in)$"
)
LIVE_TERM = (
    r"\b(?:announce[sd]?|announcing|speaks?|spoken|read(?:s)? out|polite(?:ly)?|update[sd]?"
    r"|voice[sd]?|voicing)\b[^.;]{0,30}"
    r"\b(?:each|every|per) (?:second|tick|keystroke|key ?press|character|digit)\b"
    r"|\b(?:each|every|per) (?:second|tick|keystroke|key ?press)\b[^.;]{0,20}"
    r"\b(?:announce[sd]?|spoken|read out|polite|voiced)\b"
    r"|\bcountdown\w*\b[^.;]{0,40}\b(?:polite|assertive)(?: live)? region\b"
)
# BQ-32 rider: no verdict waits on, holds only after, or depends on A-5
WAITS_TERM = (
    r"\b(?:verdicts?|grades?|gradings?)\b[^.;]{0,40}\b(?:hold|holds|stand|stands|depend|depends"
    r"|wait|waits|rest|rests|apply|applies)\b[^.;]{0,20}\b(?:only )?(?:once|when|after|until|on)\b"
    r"[^.;]{0,40}\ba 5\b"
)


def g_live(t: Texts) -> list[Finding]:
    """RULED BQ-16 and T Perf: §7 as worded (countdowns `off`, the assertive set at risk, the
    carrier rule); F-19..F-23 exist as Minor; nothing announces per keystroke or per tick."""
    sec = spec_sec(t, LIVE_HEAD)
    body = section(t.spec, LIVE_HEAD)
    bad = [F("G-LIVE", f"§7 lacks {n[:40]!r}", "spec", sec) for n in LIVE_NEEDS if n not in body]
    for k in range(19, 25):
        r = row_by_id(t.spec, FROW_HEAD, f"F-{k}")
        if len(r) < 4 or r[2] != "Minor" or r[3] != "`6.2b`":
            bad.append(F("G-LIVE", f"F-{k} is not the at-risk assertive row", "spec", sec))
    bad += as_findings(
        "G-LIVE",
        "an announcement per tick or keystroke",
        claims(
            lex(t),
            LIVE_TERM,
            unless=unless_f(r"\bc 8\b|\bat most once a second\b|\bswap at most\b"),
        ),
    )
    bad += as_findings("G-LIVE", "a verdict waiting on A-5", claims(lex(t), WAITS_TERM))
    for r in map_rows(t.spec):
        compliant = len(r) == MAP_COLS and r[8] == "compliant"
        if compliant and "assertive" in r[5] and not CARRIER.match(r[4]):
            msg = f"{r[0]}: an assertive use graded compliant with no `alertdialog` carrier"
            bad.append(F("G-LIVE", msg, "spec", spec_sec(t, MAP_HEAD)))
    return bad


COPY_ROWS = (
    ("SCR-005 and SCR-006 failure", '"Invalid password or code."'),
    ("SCR-001 label and verb", '"Username or email" · "Sign in"'),
)
STALE_COPY = ('"Incorrect password. Try again."', '"Email"', '"Log in"')


def g_copy(t: Texts) -> list[Finding]:
    """RULED BQ-17 (differently): D08's string for SCR-005 and SCR-006; SCR-001's label and verb;
    the superseded strings stand only in the C-rows that record them."""
    sec = spec_sec(t, COPY_HEAD)
    rows = {r[0]: r for r in rows_of(t.spec, COPY_HEAD)}
    bad: list[Finding] = []
    for lead, want in COPY_ROWS:
        r = rows.get(lead, [])
        if len(r) < 2 or r[1] != want:
            bad.append(F("G-COPY", f"§11.1's {lead!r} is not {want}", "spec", sec))
    allowed = {
        ln
        for h in (CROW_HEAD, MUTATION_HEAD)
        for ln in section(t.spec, h).split("\n")
        if ln.startswith("|")
    }
    bad += as_findings(
        "G-COPY",
        "SCR-001's superseded label or verb",
        claims(
            lex(t),
            r"\b(?:verb|button|action|label)\b[^.;]{0,20}\b(?:is|stays|remains|reads|becomes"
            r"|kept as)\b[^.;]{0,10}\b(?:log in|email)\b(?! or)",
            near=r"\bscr 001\b",
            unless=r"\bc 13\b",
        ),
    )
    for i, line in enumerate(t.spec.split("\n"), 1):
        if line in allowed:
            continue
        for s in STALE_COPY:
            if s in line:
                msg = f"spec:{i} {s} outside the C-rows"
                bad.append(F("G-COPY", msg, "spec", h2_at(t.spec, i)))
    return bad


SR_NEEDS = (
    "NVDA on Windows with the Electron shell and with Chromium for the fast gate",
    "VoiceOver on macOS with the Electron shell",
    "JAWS with the Electron shell runs the smoke subset",
    "not this script's steps",
    "`05`:219–224",
)


def g_sr(t: Texts) -> list[Finding]:
    """RULED BQ-18: `05` §8.1's configurations; no Chrome, Safari or Firefox target."""
    sec = spec_sec(t, SRCONF_HEAD)
    body = section(t.spec, SRCONF_HEAD)
    bad = [F("G-SR", f"§13.1 lacks {n[:40]!r}", "spec", sec) for n in SR_NEEDS if n not in body]
    bad += as_findings(
        "G-SR",
        "a browser outside `05` §8.1",
        claims(
            lex(t),
            r"\b(?:safari|firefox|chrome|edge|brave|opera|vivaldi)\b",
            near=r"\b(?:nvda|voiceover|jaws|screen readers?|configurations?|targets?|runs?)\b",
            unless=r"\b(?:c 1|d4)\b|\bread as\b|\bin place of\b|\bout of scope\b",
        ),
    )
    return bad


SCRIPT_COLS = 7
# R-7's carried causes (§6.1): the expired challenge, the fifth wrong unlock password, a revocation
CARRIED = ("T-11", "T-46", "T-52")
PASS_NEEDS = (
    "every scripted string is heard once, in order",
    "focus is where its map row says",
    "nothing on the never-list is heard",
    "A delayed or doubled announcement fails",
)


def g_script(t: Texts) -> list[Finding]:
    """AC5 (RULED BQ-19): every step has its setup, keys, a map row and its expected strings; the
    pass rule as worded; the steps in order."""
    sec = spec_sec(t, SCRIPT_HEAD)
    rows = ided(t.spec, SCRIPT_HEAD, "SR")
    maps = {row_key(r[0]) for r in map_rows(t.spec)}
    bad: list[Finding] = []
    if [row_key(r[0]) for r in rows] != [f"SR-{k}" for k in range(1, len(rows) + 1)]:
        bad.append(F("G-SCRIPT", "the SR-rows are not SR-1 … SR-n in order", "spec", sec))
    for r in rows:
        if len(r) != SCRIPT_COLS:
            bad.append(F("G-SCRIPT", f"{r[0]}: {len(r)} cells", "spec", sec))
            continue
        if not r[2].strip() or not r[3].strip():
            bad.append(F("G-SCRIPT", f"{r[0]}: no setup or keys", "spec", sec))
        cited = re.findall(r"T-\d+", r[4])
        if not cited or not set(cited) <= maps:
            bad.append(F("G-SCRIPT", f"{r[0]}: its focus names no map row", "spec", sec))
        exp = r[5]
        if not re.search(
            r'"|\(F-\d+\)|by the user\'s own navigation|`\{item\}: \{state\}`|\bSR-\d+\b', exp
        ):
            bad.append(F("G-SCRIPT", f"{r[0]}: no expected string", "spec", sec))
    focus = {x for r in rows if len(r) > 4 for x in re.findall(r"T-\d+", r[4])}
    for tid in CARRIED:
        if tid not in focus:
            bad.append(F("G-SCRIPT", f"no step scripts the carried cause {tid}", "spec", sec))
    conf = section(t.spec, SRCONF_HEAD)
    bad += [
        F("G-SCRIPT", f"§13.1 lacks {n[:40]!r}", "spec", spec_sec(t, SRCONF_HEAD))
        for n in PASS_NEEDS
        if n not in conf
    ]
    return bad


NEVER_ITEMS = ("a password", "a totp code", "a recovery code", "the totp secret", "mfa_token")
SECRET = r"(?:password|totp code|code|recovery codes?|secret|mfa_token|token|value)"
NEVER_TERM = (
    r"\b(?:announce[sd]?|read(?:s)? (?:out|aloud)|reads|speaks?|echo(?:es|ed)?|heard|says"
    r"|voice[sd]?)\b"
    rf" (?:the |a |its |each )?(?:typed |copied |current |entered )?(?:totp )?{SECRET}\b"
    rf"|\b(?:the |a )?(?:typed |copied |entered )?{SECRET} (?:is |are )?(?:read (?:out|aloud)"
    r"|announced|spoken|echoed|heard|voiced)\b"
)
NEVER_BULLETS = 4  # §11.2's prohibitions, each a bullet; a permission is never one
PERMIT = re.compile(
    r"\b(?:may|can|exception|allowed|permitted|unless|except|optional)\b", re.IGNORECASE
)
PLACEHOLDER_CODE = "{totp_gen(fixture_secret, now)}"  # RULED BQ-20 (QP:37's form)


def g_never(t: Texts) -> list[Finding]:
    """RULED BQ-20 (confirmed): the never-list names each forbidden item; no clause reads one out;
    no code value stands in the script (codes are `{totp_gen(...)}` placeholders)."""
    sec = spec_sec(t, NEVER_HEAD)
    body = norm_text(section(t.spec, NEVER_HEAD))
    bad = [F("G-NEVER", f"§11.2 lacks {n!r}", "spec", sec) for n in NEVER_ITEMS if n not in body]
    bad += as_findings(
        "G-NEVER",
        "a secret read out",
        claims(
            lex(t),
            NEVER_TERM,
            unless=(
                r"\bby the user's own navigation\b|\bnever\b"
                r"|\bwrong (?:unlock )?password is heard\b"
            ),
        ),
    )
    for r in ided(t.spec, SCRIPT_HEAD, "SR"):
        if re.search(r"(?<![\w{])\d{6}(?!\w)", " ".join(r[2:6])):
            bad.append(F("G-NEVER", f"{r[0]}: a literal code value", "spec", sec))
    bullets = [ln for ln in section(t.spec, NEVER_HEAD).split("\n") if ln.startswith("- ")]
    if len(bullets) != NEVER_BULLETS or any(PERMIT.search(unquote(b)) for b in bullets):
        msg = f"§11.2 holds {len(bullets)} bullets, or one permits what it forbids"
        bad.append(F("G-NEVER", msg, "spec", sec))
    for m in re.finditer(r"\{totp_gen\([^)]*\)\}", t.spec):
        if m[0] != PLACEHOLDER_CODE:
            at = h2_at(t.spec, t.spec.count("\n", 0, m.start()) + 1)
            bad.append(F("G-NEVER", f"{m[0]} is not the ruled placeholder", "spec", at))
    return bad


def g_esc(t: Texts) -> list[Finding]:
    """RULED BQ-21: the lock ignores `Esc`; CMP-098's `Esc` dismisses and never extends; SCR-006
    and SCR-149 cancel; no clause lets `Esc` dismiss the lock."""
    sec = spec_sec(t, TRAPS_HEAD)
    rows = {r[0]: r for r in rows_of(t.spec, TRAPS_HEAD)}
    bad: list[Finding] = []
    for lead, want in (
        ("SCR-005 lock", "inert"),
        ("CMP-098 warning", "dismiss, never extend"),
        ("the expiry card", "inert"),
    ):
        r = rows.get(lead, [])
        if len(r) < 3 or r[2] != want:
            bad.append(F("G-ESC", f"§5.1's {lead!r} `Esc` is not {want!r}", "spec", sec))
    bad += as_findings(
        "G-ESC",
        "`Esc` dismissing the lock",
        claims(
            lex(t),
            r"\b(?:esc|escape)\b (?:dismisses|closes|unlocks|leaves|exits|ends|cancels) (?:scr 005"
            r"|the lock\b|the lock card|the locked card)"
            r"|\b(?:esc|escape)\b(?:(?!\b(?:no|never|not|without)\b)[^.;]){0,40}"
            r"\b(?:extend(?:s|ed|ing)? the session|keeps? the user"
            r" signed in|resets? the (?:idle )?timer)\b",
        ),
    )
    return bad


TARGET_HEAD = "5.5 Targets"


def g_target(t: Texts) -> list[Finding]:
    """RULED BQ-23: every boxed target on the frames drawn at one CSS pixel per image pixel is
    measured (each TARGETS key in §5.5's table, anchored); its verdict agrees with the measurement
    against `05`:100's bar; the targets not measured say why and go to Q-5."""
    sec = spec_sec(t, TARGET_HEAD)
    block = section(t.spec, TARGET_HEAD)
    bar = int(t.values.get("CITE:target", "24"))
    seen: list[str] = []
    bad: list[Finding] = []
    for ln in block.split("\n"):
        keys = re.findall(r"<!--=TARGET:([\w.]+)\.w-->", ln)
        if not keys:
            continue
        key, cells = keys[0], split_row(ln)
        seen.append(key)
        w = int(t.values.get(f"TARGET:{key}.w", "0"))
        h = int(t.values.get(f"TARGET:{key}.h", "0"))
        meets = min(w, h) >= bar
        verdict = cells[3] if len(cells) > 3 else ""
        if meets and verdict != "meets the bar":
            bad.append(
                F("G-TARGET", f"{key}: {w}x{h} meets the bar, graded {verdict!r}", "spec", sec)
            )
        if not meets and not re.fullmatch(r"below the bar \(F-\d+\)", verdict):
            bad.append(
                F("G-TARGET", f"{key}: {w}x{h} below the bar, graded {verdict!r}", "spec", sec)
            )
    if sorted(seen) != sorted(TARGETS):
        bad.append(F("G-TARGET", "§5.5 does not list every measured target once", "spec", sec))
    if "Not measured, and why:" not in block or "Q-5" not in block:
        bad.append(F("G-TARGET", "§5.5 does not say why the rest are not measured", "spec", sec))
    return bad


def g_contrast(t: Texts) -> list[Finding]:
    """RULED BQ-24 (confirmed): every pair measured in the three themes; every measurement below
    its bar carries an F-row in its row; D03's self-logged exception is not accepted."""
    sec = spec_sec(t, PAIRS_HEAD)
    bad: list[Finding] = []
    rows = {pair_id(r[0]): r for r in pair_rows(t.spec)}
    for pid, theme, got, bar in below(t.spec):
        where = rows.get(pid, [""] * 8)[-1]
        if not re.search(r"\(F-\d+\)", where):
            msg = f"{pid} {theme} {show_ratio(got)} below {bar} marked as passing"
            bad.append(F("G-CONTRAST", msg, "spec", sec))
    for pid, r in rows.items():
        if len(r) < 8 or r[6] not in ("text", "non-text", "reported"):
            bad.append(F("G-CONTRAST", f"{pid}: its bar {r[6:7]}", "spec", sec))
    body = section(t.spec, PAIRS_HEAD)
    if "(D03A:23–34) is not accepted" not in body:
        bad.append(F("G-CONTRAST", "D03's border exception is not refused", "spec", sec))
    bad += as_findings(
        "G-CONTRAST",
        "a self-logged contrast exception accepted",
        claims(
            lex(t),
            r"\bexception\b[^.;]{0,40}\b(?:is |was )?(?:accepted|stands|holds|kept|upheld|retained"
            r"|remains|stays)\b"
            r"|\b(?:accept\w*|uphold\w*|keep\w*)\b[^.;]{0,20}\b(?:the |its |d03's )?(?:self-logged "
            r"|border )?exception\b",
            near=r"\b(?:border|d03a?|input|field)\b",
            unless=r"\bnot accepted\b|\bc 29\b",
        ),
    )
    return bad


# RULED BQ-25's carriers, each a §9.1 state
CARRIERS = (
    "an error (field or banner)",
    "a warning banner",
    "few recovery codes left",
    "focus",
    "a T2 control",
    "an invalid field",
    "the environment badge",
    "met / not met",
    "the strength meter",
    "selected and disabled",
)


def g_cvd(t: Texts) -> list[Finding]:
    """RULED BQ-25: a carrier whose state rests on colour alone is non-compliant with its F-row;
    every §9.3 row computes; the CVD constants match CVD at the base."""
    sec = spec_sec(t, CR_HEAD)
    bad: list[Finding] = []
    for r in ided(t.spec, CR_HEAD, "CR"):
        if len(r) < 5:
            continue
        alone = r[2].startswith("none")
        if r[4].startswith("N/A: ") and r[2].startswith("N/A"):
            continue
        if alone and not re.match(r"non-compliant \(F-\d+\)", r[4]):
            bad.append(F("G-CVD", f"{r[0]}: colour alone graded {r[4]!r}", "spec", sec))
        if not alone and r[4] != "compliant":
            bad.append(F("G-CVD", f"{r[0]}: {r[4]!r} with other carriers", "spec", sec))
    states = {r[1] for r in ided(t.spec, CR_HEAD, "CR") if len(r) > 1}
    for c in CARRIERS:
        if c not in states:
            bad.append(F("G-CVD", f"§9.1 lacks the carrier {c!r} (BQ-25)", "spec", sec))
    grid = cvd_grid(t.spec)
    for r in cvd_rows(t.spec):
        if r[0].lower().replace("-", "") not in grid:
            bad.append(
                F("G-CVD", f"{r[0]}: its pair does not compute", "spec", spec_sec(t, CVD_HEAD))
            )
    if cvd_constants_at_base() != own_cvd_constants():
        bad.append(F("G-CVD", "the CVD constants differ from CVD at the base", None, None))
    return bad


def g_rbac(t: Texts) -> list[Finding]:
    """RULED BQ-27 (differently): F-17 a Minor whose replacement reads "absent by plan in v1"
    only; no clause offers a T2 state reason for "Disable two-factor"."""
    sec = spec_sec(t, FROW_HEAD)
    r = row_by_id(t.spec, FROW_HEAD, "F-17")
    bad: list[Finding] = []
    if len(r) < 5 or r[2] != "Minor":
        bad.append(F("G-RBAC", "F-17 is not a Minor", "spec", sec))
    elif not r[4].endswith("· absent by plan in v1"):
        bad.append(
            F("G-RBAC", "F-17's replacement is not 'absent by plan in v1' only", "spec", sec)
        )
    bad += as_findings(
        "G-RBAC",
        "a T2 or a state reason for the hidden control",
        claims(
            lex(t),
            r"\b(?:t2|aria disabled|a state reason|disabled with a (?:visible )?reason"
            r"|(?:drawn|shown|rendered|kept) as a disabled)\b",
            near=r"\bdisable two factor\b",
        ),
    )
    return bad


AGENT = re.compile(
    r"\b(?:agent|worker|hcl-|hpe-|vps-|orchestrator|claude|lane \d)\b", re.IGNORECASE
)
SEVERITY = ("Blocker", "Major", "Minor", "Info")
FROW_COLS = 9


def g_frows(t: Texts) -> list[Finding]:
    """S-20, R-2: every F-row has its class, severity, clause, sentence and replacement, one
    owner that is a spec and its area (never an agent), a target, a consumer and a close state;
    ids in order; every F-n cited exists."""
    sec = spec_sec(t, FROW_HEAD)
    rows = ided(t.spec, FROW_HEAD, "F")
    bad: list[Finding] = []
    if [r[0] for r in rows] != [f"F-{k}" for k in range(1, len(rows) + 1)]:
        bad.append(F("G-FROWS", "the F-rows are not F-1 … F-n in order", "spec", sec))
    for r in rows:
        if len(r) != FROW_COLS or not all(c.strip() for c in r):
            bad.append(F("G-FROWS", f"{r[0]}: an empty or missing cell", "spec", sec))
            continue
        if r[2] not in SEVERITY:
            bad.append(F("G-FROWS", f"{r[0]}: severity {r[2]!r}", "spec", sec))
        if " · " not in r[4]:
            bad.append(F("G-FROWS", f"{r[0]}: no sentence · replacement", "spec", sec))
        if AGENT.search(r[5]) or not re.match(r"^E\d\d-[DSQ]\d\d\b.*\(`area/[a-z-]+`\)$", r[5]):
            bad.append(F("G-FROWS", f"{r[0]}: owner {r[5]!r}", "spec", sec))
        if AGENT.search(r[6] + r[7]):
            bad.append(F("G-FROWS", f"{r[0]}: an agent as target or consumer", "spec", sec))
    used = set(re.findall(r"(?<![\w-])F-\d+\b", CODE.sub(" ", t.spec)))
    for x in sorted(used - {r[0] for r in rows}):
        bad.append(F("G-FROWS", f"{x} is cited but not defined", "spec", sec))
    if "Every finding is `(heuristic)`" not in section(t.spec, FROW_HEAD):
        bad.append(F("G-FROWS", "the findings are not marked `(heuristic)`", "spec", sec))
    return bad


def g_assert(t: Texts) -> list[Finding]:
    """T Obs (RULED BQ-29): every assertion names its requirement, route, check and harness."""
    sec = spec_sec(t, ASSERT_HEAD)
    rows = ided(t.spec, ASSERT_HEAD, "AS")
    bad: list[Finding] = []
    for r in rows:
        if len(r) != 6 or not all(c.strip() for c in r[1:]):
            bad.append(F("G-ASSERT", f"{r[0]}: an empty cell", "spec", sec))
            continue
        if not re.search(r"\b(?:F|T|TL|R)-\d+\b|§\d|\b\d\.\d\.\d+\b|`\d+(?:\.\d+)*`", r[1]):
            bad.append(F("G-ASSERT", f"{r[0]}: no named requirement", "spec", sec))
    if [r[0] for r in rows] != [f"AS-{k}" for k in range(1, len(rows) + 1)]:
        bad.append(F("G-ASSERT", "the AS-rows are not in order", "spec", sec))
    return bad


def g_template(t: Texts) -> list[Finding]:
    """AC1 (RULED BQ-5): one Feature per surface, each with the template's six scenarios in order,
    each with a step; every N/A states its reason."""
    sec = spec_sec(t, TEMPLATE_HEAD)
    feats = features(t.spec)
    bad: list[Finding] = []
    if len(feats) != len(SURFACES):
        bad.append(F("G-TEMPLATE", f"{len(feats)} Features, not {len(SURFACES)}", "spec", sec))
    for name, scen in feats:
        if tuple(s for s, _l in scen) != TEMPLATE_SCENARIOS:
            bad.append(F("G-TEMPLATE", f"{name[:40]!r}: the scenarios differ", "spec", sec))
        for s, steps in scen:
            if not steps:
                bad.append(F("G-TEMPLATE", f"{name[:30]!r} {s}: no step", "spec", sec))
            for st in steps:
                m = re.search(r"\bN/A\b(.*)", st)
                if m and len(re.findall(r"\w+", m[1])) < 4:
                    bad.append(F("G-TEMPLATE", f"{name[:30]!r} {s}: N/A unexplained", "spec", sec))
    return bad


def g_rows(t: Texts, head: str, prefix: str, tag: str, due_col: int) -> list[Finding]:
    """Rows `prefix`-1 … n in order; the owner lane never an agent; due at once where a due column
    exists; every `prefix`-n cited is defined."""
    sec = spec_sec(t, head)
    rows = ided(t.spec, head, prefix)
    bad: list[Finding] = []
    ids = [r[0] for r in rows]
    if ids != [f"{prefix}-{k}" for k in range(1, len(rows) + 1)] or not rows:
        bad.append(F(tag, f"the rows read {ids[:3]}…, not {prefix}-1 … n", "spec", sec))
    for r in rows:
        lane = r[due_col - 1] if due_col else r[-1]
        if AGENT.search(lane):
            bad.append(F(tag, f"{r[0]}: an agent as the owner lane", "spec", sec))
        if due_col and (len(r) <= due_col or r[due_col] != "at once"):
            bad.append(F(tag, f"{r[0]}: not due at once", "spec", sec))
    used = set(re.findall(rf"(?<![\w-]){prefix}-\d+\b(?!\.\d)", CODE.sub(" ", t.spec)))
    for x in sorted(used - set(ids)):
        bad.append(F(tag, f"{x} is cited but not defined", "spec", sec))
    return bad


def g_crows(t: Texts) -> list[Finding]:
    """BQ-35: the C-rows, numbered, each with its reading and an owner lane, never an agent."""
    return g_rows(t, CROW_HEAD, "C", "G-CROWS", 0)


def g_grows(t: Texts) -> list[Finding]:
    """S-16 and the BQ-15 rider: the G-ledger to tickets or spec owners, due at once; G-1 asks for
    the warning and the progress-keeping restart and leaves the window to its owners."""
    bad = g_rows(t, GROW_HEAD, "G", "G-GROWS", 4)
    g1 = " | ".join(row_by_id(t.spec, GROW_HEAD, "G-1"))
    for need in ("a restart that keeps the enrolment's progress", "the `04` and threat-model"):
        if need not in g1:
            bad.append(F("G-GROWS", f"G-1 lacks {need[:30]!r}", "spec", spec_sec(t, GROW_HEAD)))
    return bad


def g_qrows(t: Texts) -> list[Finding]:
    """S-13: the open questions and the heuristic rows, owned, the questions due at once."""
    return g_rows(t, QROW_HEAD, "Q", "G-QROWS", 4) + g_rows(t, HROW_HEAD, "H", "G-QROWS", 0)


def a_rows(spec: str) -> dict[str, list[str]]:
    return {r[0]: r for r in ided(spec, AROW_HEAD, "A")}


def g_arow(t: Texts) -> list[Finding]:
    """S-15: departures ship as copy-ready A-rows; each Old cell stands verbatim on its cited line
    at the base; each New differs; every A-n cited exists."""
    sec = spec_sec(t, AROW_HEAD)
    rows = a_rows(t.spec)
    bad: list[Finding] = []
    if list(rows) != [f"A-{k}" for k in range(1, len(rows) + 1)]:
        bad.append(F("G-AROW", "the A-rows are not in order", "spec", sec))
    for aid, r in rows.items():
        if len(r) != 5:
            bad.append(F("G-AROW", f"{aid}: cells", "spec", sec))
            continue
        refs = cite_refs(r[2])
        if len(refs) != 1:
            bad.append(F("G-AROW", f"{aid}: its Field cites {len(refs)} lines", "spec", sec))
            continue
        cid, n, _b = refs[0]
        old = pin_norm(r[3].replace("\\|", "|"))
        if len(old) < 7 or old not in pin_norm(base_line(cid, n)):
            bad.append(F("G-AROW", f"{aid}: Old is not on {cid}:{n} verbatim", "spec", sec))
        if not r[4].strip() or r[4] == r[3]:
            bad.append(F("G-AROW", f"{aid}: no New", "spec", sec))
    used = set(re.findall(r"(?<![\w-])A-\d+\b", CODE.sub(" ", t.spec)))
    for x in sorted(used - set(rows)):
        bad.append(F("G-AROW", f"{x} is cited but not in §C", "spec", sec))
    return bad


HANDOFF_FILE = re.compile(r"[\w./-]*-handoff\.md")


def g_handref(t: Texts) -> list[Finding]:
    """BQ-1: there is no hand-off file; every `-handoff.md` named is a merged one at the base,
    never this ticket's; every "§C" names this spec's own §C section."""
    bad: list[Finding] = []
    has_c = any(
        m and m[2].startswith("18. §C") for m in (HEADING.match(x) for x in t.spec.split("\n"))
    )
    for i, line in enumerate(t.spec.split("\n"), 1):
        sec = h2_at(t.spec, i)
        for m in HANDOFF_FILE.finditer(line):
            name = m[0].split("/")[-1]
            rel = next((p for p in CITE_FILES.values() if p.endswith(name)), None)
            if "E09-D10" in name or rel is None or git_show(BASE, rel) is None:
                bad.append(F("G-HANDREF", f"spec:{i} {name} is not a merged hand-off", "spec", sec))
        if "§C" in line and not has_c:
            bad.append(F("G-HANDREF", f"spec:{i} §C names no section", "spec", sec))
    return bad


SYNONYMS = (
    *("screen reader", "SR", "NVDA", "VoiceOver", "assistive", "focus order", "focus continuity"),
    *("focus map", "focus return", "announce", "live region", "aria-live", "alert"),
    *("time limit", "timeout", "idle", "expiry", "axe", "a11y gate"),
)


def ids_defined(t: Texts) -> set[str]:
    return {r[0] for h in (GROW_HEAD, QROW_HEAD) for r in rows_of(t.spec, h)}


def g_walk(t: Texts) -> list[Finding]:
    """S-12 (RULED BQ-33): one row per consumer role in order; needs = found + not found; each
    "not found" carried to a G-row or a Q-row; the synonyms searched; no session claimed; the
    walkthrough at most ten items, each naming its board or "no board"."""
    sec = spec_sec(t, WALK_HEAD)
    raw = section(t.spec, WALK_HEAD)
    rows = rows_of(t.spec, WALK_HEAD)
    bad: list[Finding] = []
    roles = tuple(r[1] for r in rows if len(r) > 1)
    if roles != CONSUMERS:
        bad.append(F("G-WALK", f"the roles read {roles[:2]}…, not every consumer", "spec", sec))
    gq = ids_defined(t)
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
    for syn in SYNONYMS:
        if f"`{syn}`" not in raw:
            bad.append(F("G-WALK", f"§19.1 lacks the synonym {syn!r}", "spec", sec))
    body = norm_text(raw)
    for phrase in (
        "**No session took place and none is claimed.**",
        'before any "not found" was recorded, the merged sources were searched',
        "nothing claims a screen reader ran",
    ):
        if norm_text(phrase) not in body:
            bad.append(F("G-WALK", f"§19.1 lacks {phrase[:40]!r}", "spec", sec))
    walk = [ln for ln in section(t.spec, WALKTHROUGH_HEAD).split("\n") if ln.startswith("- [")]
    wsec = spec_sec(t, WALKTHROUGH_HEAD)
    if not 0 < len(walk) <= MAX_WALK:
        bad.append(F("G-WALK", f"the walkthrough has {len(walk)} items", "spec", wsec))
    for item in walk:
        if not re.search(r"\((?:no board|boards? [\w ,-]+)\)$", item):
            bad.append(F("G-WALK", f"walkthrough item {item[6:40]!r} names no board", "spec", wsec))
    return bad


def g_except(t: Texts) -> list[Finding]:
    """RULED BQ-30: the essential exceptions in `16` §11.4's form, each with its compensating
    control, the stand-in reviewer and the date; the idle lock never among them."""
    sec = spec_sec(t, EX_HEAD)
    rows = ided(t.spec, EX_HEAD, "EX")
    bad: list[Finding] = []
    if not rows:
        bad.append(F("G-EXCEPT", "no essential exception is logged", "spec", sec))
    for r in rows:
        if len(r) != 5 or not r[2].strip():
            bad.append(F("G-EXCEPT", f"{r[0]}: cells", "spec", sec))
            continue
        if re.search(r"\bidle\b|\bTL-1\b", r[1]):
            bad.append(F("G-EXCEPT", f"{r[0]}: the idle lock logged as an exception", "spec", sec))
        if "`L1 row 119`" not in r[3] or r[4] != DRY_DATE:
            bad.append(F("G-EXCEPT", f"{r[0]}: reviewer or date", "spec", sec))
    bad += as_findings(
        "G-EXCEPT",
        "the idle lock read as an exception",
        claims(
            lex(t),
            r"\bidle lock (?:is |was )?(?:treated |read |logged |counted )?(?:as )?(?:an? )?"
            r"(?:essential )?exception\b",
        ),
    )
    return bad


DOD_OPEN = ("Every Blocker resolved and re-reviewed", "Owner sign-off")


def g_dod(t: Texts) -> list[Finding]:
    """The DoD: the Blocker line and the owner's sign-off stay open; every ticked item names its
    evidence."""
    sec = spec_sec(t, DOD_HEAD)
    bad: list[Finding] = []
    for ln in section(t.spec, DOD_HEAD).split("\n"):
        m = re.match(r"^- \[(.)\] (.*)$", ln)
        if not m:
            continue
        if m[2].startswith(DOD_OPEN) and m[1] != " ":
            bad.append(F("G-DOD", f"{m[2][:40]!r} is ticked", "spec", sec))
        if m[1] == "x" and not re.search(r"§\d", m[2]):
            bad.append(F("G-DOD", f"{m[2][:40]!r} has no evidence", "spec", sec))
    return bad


PR_TITLE = (  # RULED BQ-1 (the ruled default, verbatim)
    "docs(auth-rbac): E09-D10 accessibility design review and screen-reader script for the auth"
    " band"
)
LABELS = (
    *("type/design", "area/auth-rbac", "priority/p0", "design", "design-qa", "a11y"),
    "security-review",
)


def g_deviations(t: Texts) -> list[Finding]:
    """D1 to D4; the PR title, the labels and the `Refs` + `Partial:` line (BQ-10)."""
    sec = spec_sec(t, DEV_HEAD)
    body = section(t.spec, DEV_HEAD)
    bad: list[Finding] = []
    for d in ("**D1**", "**D2**", "**D3**", "**D4**"):
        if f"- {d} " not in body:
            bad.append(F("G-DEVIATIONS", f"§20.3 lacks {d}", "spec", sec))
    if f"`{PR_TITLE}`" not in body or len(PR_TITLE) > 100:
        bad.append(F("G-DEVIATIONS", "§20.3's PR title is not the ruled one (BQ-1)", "spec", sec))
    for lab in LABELS:
        if f"`{lab}`" not in body:
            bad.append(F("G-DEVIATIONS", f"§20.3 lacks the label {lab}", "spec", sec))
    if "`Refs #193` and a `Partial:` line" not in body:
        bad.append(F("G-DEVIATIONS", "§20.3 lacks the Refs line", "spec", sec))
    return bad


def g_penpot(t: Texts) -> list[Finding]:
    """S-3: no host, link or URL; the merged pages by name and id, never a link."""
    bad: list[Finding] = []
    for i, line in enumerate(t.spec.split("\n"), 1):
        if URL.search(strip_comments(line)):
            bad.append(F("G-PENPOT", f"spec:{i} a URL or host", "spec", h2_at(t.spec, i)))
    if "No new boards, no Penpot page, no PNG" not in section(t.spec, STATUS_HEAD):
        bad.append(F("G-PENPOT", "§0 does not say no boards", "spec", spec_sec(t, STATUS_HEAD)))
    return bad


def catalogue_ids() -> frozenset[str]:
    return frozenset(re.findall(r"^### (CMP-\d{3})\b", plan("15"), MULTI))


def g_newcmp(t: Texts) -> list[Finding]:
    """No new component: every CMP id named is in `15` at the base, and no sentence introduces a
    new component."""
    bad: list[Finding] = []
    for i, line in enumerate(t.spec.split("\n"), 1):
        for c in re.findall(r"\bCMP-\d{3}\b", line):
            if c not in catalogue_ids():
                bad.append(F("G-NEWCMP", f"spec:{i} {c} is not in `15`", "spec", h2_at(t.spec, i)))
    bad += as_findings(
        "G-NEWCMP",
        "a new component",
        claims(
            lex(t),
            r"\b(?:new|a further|an extra|another) (?:component|cmp|organism|molecule|atom)\b",
        ),
    )
    return bad


# ---------------------------------------------------------------------------- G-QUOTE

SNAKE = re.compile(r"(?<![\w.$/{-])((?:[a-z][a-z0-9]*\.)?[a-z][a-z0-9]*_[a-z0-9_]+(?:\.\*)?)\b")
QUOTE_MIN = 12
# the ruling's own words, quoted where the spec carries them (comment 6495540658)
RULING_PHRASES = ("absent by plan in v1",)
# G-QUOTE skips the mutation rows (they describe the violations they plant)
QUOTE_SKIP = (MUTATION_HEAD,)
CORE = (
    *("05", "13", "14", "15", "16", "22", "D02", "D03", "D03A", "D04", "D05", "D06", "D08"),
    *("D09", "S03", "QP", "Q04"),
)


def loose(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("’", "'").replace("...", "…")
    return " ".join(s.split()).lower().rstrip(".")


@functools.lru_cache(maxsize=1)
def ticket() -> str:
    """The ticket body in E09J at the base."""
    data = json.loads(at_base(CITE_FILES["E09J"]))
    for item in data:
        if isinstance(item, dict) and item.get("key") == TICKET_KEY:
            return str(item.get("body", ""))
    raise SystemExit("FAIL parse: the ticket body is missing in E09J")


@functools.lru_cache(maxsize=256)
def source_text(cid: str) -> str:
    """One source at the base (the ticket for `T`), escaped quotes unescaped."""
    if cid == "T":
        return ticket().replace('\\"', '"')
    rel = cite_path(cid)
    return (git_show(rev_for(cid), rel) or "").replace('\\"', '"') if rel else ""


@functools.lru_cache(maxsize=256)
def loose_source(cid: str) -> str:
    return loose(source_text(cid))


class Pool:
    """The ticket, the core sources and the sources a line cites, searched file by file."""

    def __init__(self, cids: tuple[str, ...]) -> None:
        self.cids = ("T", *CORE, *cids)

    def __contains__(self, s: str) -> bool:
        return any(s in source_text(c) for c in self.cids)

    def loose_has(self, s: str) -> bool:
        return any(s in loose_source(c) for c in self.cids)


def g_quote(t: Texts) -> list[Finding]:
    """Every backticked snake name is in a cited or core source; every quoted string of twelve
    characters or more is verbatim there, a frame's own words or the ruling's."""
    bad: list[Finding] = []
    own = {loose(s) for s in (*IMG_STRINGS, *RULING_PHRASES, OWNER_PENDING)}
    skip = {ln for h in QUOTE_SKIP for ln in section(t.spec, h).split("\n") if ln.startswith("|")}
    for i, line in enumerate(t.spec.split("\n"), 1):
        if line in skip:
            continue
        sec = h2_at(t.spec, i)
        pool = Pool(tuple(sorted({c for c, _a, _b in cite_refs(line)})))
        rendered = strip_comments(line)
        for c in CODE.finditer(rendered):
            for m in SNAKE.finditer(c[0][1:-1]):
                if m[1].removesuffix(".*") not in pool:
                    bad.append(F("G-QUOTE", f"spec:{i} `{m[1]}` is in no cited text", "spec", sec))
        for q in QUOTED.finditer(CODE.sub(" ", rendered)):
            s = q[0][1:-1]
            if len(s) < QUOTE_MIN or pool.loose_has(loose(s)) or loose(s) in own:
                continue
            bad.append(F("G-QUOTE", f"spec:{i} {s[:50]!r} is in no cited text", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- generic text gates


def g_comment(t: Texts) -> list[Finding]:
    """No `[//]: #` comment and no link-reference definition: hidden text the gates cannot see."""
    return [
        F("G-COMMENT", f"spec:{i} a link-reference line", "spec", h2_at(t.spec, i))
        for i, line in enumerate(t.spec.split("\n"), 1)
        if re.match(r"^ {0,3}\[[^\]]*\]:\s", line)
    ]


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
    """No high-entropy `"key": "<value>"` string in the three files; no recovery-code shape in the
    spec (RULED BQ-20)."""
    bad: list[Finding] = []
    texts = {"spec": t.spec}
    for rel in (TOOL_REL, RULED_PIN_TXT):
        p = ROOT / rel
        texts[rel] = p.read_text(encoding="utf-8") if p.exists() else ""
    for doc, text in texts.items():
        for i, line in enumerate(text.split("\n"), 1):
            sec = h2_at(text, i) if doc == "spec" else None
            for m in KEYISH.finditer(line):
                v = m[2]
                if " " not in v and "/" not in v and shannon(v) > 3.5:
                    msg = f"{doc}:{i} a high-entropy value for {m[1]!r}"
                    bad.append(F("G-ENTROPY", msg, doc if doc == "spec" else None, sec))
            if doc == "spec" and RECOVERY_SHAPE.search(line):
                bad.append(F("G-ENTROPY", f"spec:{i} a recovery-code shape", "spec", sec))
    return bad


SESSION_CLAIM = (
    r"\b(?:session|walkthrough|meeting|interview|test|pass|run)s?\b(?:\s+\S+){0,2}?\s+"
    r"(?:was |were |has been |is )?(?:held|ran|recorded|conducted|completed|happened)\b"
    r"|\btook place\b|\bparticipants?\b|\battendees?\b|\bwalked through\b|\bthe user said\b"
    r"|\bthe screen reader (?:read|said|announced)\b"
)


def g_session(t: Texts) -> list[Finding]:
    """S-9: no session, participant, timing, quote or screen-reader output is claimed."""
    units = [u for u in lex(t) if not u.text.startswith("**No session took place")]
    return as_findings(
        "G-SESSION", "a session held", claims(units, SESSION_CLAIM, unless=r"\bnot yet run\b")
    )


NAMED_HEAD = "**Named only, never pinned or quoted:**"


def g_named(t: Texts) -> list[Finding]:
    """BQ-1: the version line's named-only tickets carry no quote and no sha; no sha stands beside
    a named-only or open ticket anywhere."""
    bad: list[Finding] = []
    lines = t.spec.split("\n")
    i = next((n for n, ln in enumerate(lines) if ln.startswith("**Start.**")), 0)
    start, sec = lines[i], h2_at(t.spec, i + 1)
    named = start.split(NAMED_HEAD, 1)[-1].split("**", 1)[0] if NAMED_HEAD in start else ""
    if not named:
        bad.append(F("G-NAMED", "the version line has no named-only clause", "spec", sec))
    elif QUOTED.search(named) or re.search(r"`[0-9a-f]{7,}`", named):
        bad.append(
            F("G-NAMED", f"a named-only ticket quoted or pinned: {named[:60]!r}", "spec", sec)
        )
    for u in lex(t):
        for c in clauses(u.text):
            if any(re.search(rf"{re.escape(n)}(?!\d)", c) for n in NAMED_NO_SHA) and re.search(
                r"`[0-9a-f]{10}`", c
            ):
                bad.append(F("G-NAMED", f"a sha beside an open ticket: {c[:60]!r}", u.doc, u.sec))
    return bad


# ---------------------------------------------------------------------------- repo-level gates


@functools.cache
def last_touch(cid: str) -> str:
    rel = cite_path(cid) or ""
    return git_out("log", "-1", "--format=%h", "--abbrev=10", rev_for(cid), "--", rel).strip()


def g_version(t: Texts) -> list[Finding]:
    """The version line's semantics: v1 at the base; every sha in order and under the base; each
    pinned doc at its last touch at the base; the Inputs line names the base."""
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
        if not (under_base(s) or (s == LATE and under_head(s)))
    ]
    late = line.split("**Late changes:**", 1)[-1].split("**", 1)[0]
    if f"#4939 `{LATE}`" not in late or not under_head(LATE):
        bad.append(F("G-VERSION", f"the late change #4939 `{LATE}` is not recorded", "spec", sec))
    pinned = line.split("**Pinned at their last touch at the base:**", 1)[-1].split("**", 1)[0]
    for cid, sha in PINNED_DOCS.items():
        last = last_touch(cid)
        if last != sha or not re.search(rf"\b{cid}\b", pinned):
            bad.append(F("G-VERSION", f"{cid} pinned at {sha}, last touched {last}", "spec", sec))
    inputs = next((ln for ln in lines if ln.startswith("**Inputs pinned.**")), "")
    if inputs.count(BASE) < 2:
        bad.append(F("G-VERSION", f"the Inputs line does not name the base {BASE}", "spec", sec))
    return bad


def g_untouched(t: Texts) -> list[Finding]:
    """The standing rule: the untouched files equal the merge-base; only this PR's three files
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


# ---------------------------------------------------------------------------- pass 2 (BQ-7)

PASS2_TOTAL = 39  # pass 2's own report: 39 rows (2 Blocker, 10 Major, 23 Minor, 4 Info)
PASS2_FIRST = "F-25"  # the first F-row pass 2 adds
# each pass-2 F-row: its severity and its owner, as the fold settled them (F-25: G-LOCKOUT)
PASS2_ROWS: dict[str, tuple[str, str]] = {
    "F-26": ("Blocker", "E09-D06"),
    **{f"F-{k}": ("Major", "E09-D03") for k in (27, 29, 30, 34)},
    **{f"F-{k}": ("Major", "E09-D06") for k in (28, 31, 32)},
    **{f"F-{k}": ("Minor", "E09-D03") for k in (35, 38, 44, 46)},
    **{f"F-{k}": ("Minor", "E09-D04") for k in (33, 37, 42, 43, 45, 47)},
    **{f"F-{k}": ("Minor", "E09-D06") for k in (36, 39, 40, 41)},
    "F-48": ("Minor", "E09-D09"),
    **{f"F-{k}": ("Info", "E09-D04") for k in (49, 51)},
    "F-50": ("Info", "E09-D06"),
}
DRY_VERDICTS = ("yes", "partly", "no")
FOLD_ID = re.compile(r"(?<![\w-])((?:F|C|Q|G|T|SR)-\d+)\b")


def g_pass2(t: Texts) -> list[Finding]:
    """RULED BQ-7: pass 2's rows, P2-1 ... P2-n, each folded into a defined F-, C-, Q-, G-, T- or
    SR-row, a §-section fix, or closed with its reason; every pass-2 F-row at the severity and
    owner the fold settled; the dry run one row per script step, each yes, partly or no, and every
    step not marked yes fixed in §13.2 or §13.3 or carried by a defined Q- or G-row."""
    sec = spec_sec(t, METHOD_HEAD)
    bad: list[Finding] = []
    rows = ided(t.spec, METHOD_HEAD, "P2")
    if [r[0] for r in rows] != [f"P2-{k}" for k in range(1, PASS2_TOTAL + 1)]:
        bad.append(F("G-PASS2", f"§1.2 lists {len(rows)} pass-2 rows, not P2-1 … n", "spec", sec))
    defined = {
        row_key(r[0])
        for h in (FROW_HEAD, CROW_HEAD, GROW_HEAD, QROW_HEAD, MAP_HEAD, SCRIPT_HEAD)
        for r in rows_of(t.spec, h)
    }
    for r in rows:
        fold = r[2] if len(r) > 2 else ""
        ids = FOLD_ID.findall(fold)
        closed = fold.startswith("closed: ") and len(fold.split()) >= 6
        if set(ids) - defined or not (ids or closed or "§" in fold):
            msg = f"{r[0]}: its fold {fold[:30]!r} does not resolve"
            bad.append(F("G-PASS2", msg, "spec", sec))
    fsec = spec_sec(t, FROW_HEAD)
    for fid, (sev, owner) in PASS2_ROWS.items():
        f = row_by_id(t.spec, FROW_HEAD, fid)
        if len(f) < 6 or f[2] != sev or not f[5].startswith(f"{owner} "):
            bad.append(F("G-PASS2", f"{fid} is not the {sev} the fold settled", "spec", fsec))
    steps = [row_key(r[0]) for r in ided(t.spec, SCRIPT_HEAD, "SR")]
    dry = ided(t.spec, METHOD_HEAD, "SR")
    if [r[0] for r in dry] != steps:
        bad.append(F("G-PASS2", "the dry run is not one row per script step", "spec", sec))
    gq = {r[0] for h in (GROW_HEAD, QROW_HEAD) for r in rows_of(t.spec, h)}
    for r in dry:
        if len(r) < 3 or r[1] not in DRY_VERDICTS:
            bad.append(F("G-PASS2", f"{r[0]}: dry-run verdict {r[1:2]}", "spec", sec))
            continue
        carried = set(re.findall(r"(?<![\w-])([GQ]-\d+)\b", r[2])) & gq
        if r[1] != "yes" and not (re.match(r"§13\.[23]: ", r[2]) or carried):
            bad.append(F("G-PASS2", f"{r[0]}: {r[1]} with no fix or row", "spec", sec))
    return bad


# lexicon gates first, then the measured gates; the pins (G-RULED-PIN) run last, in `audit`
LEXICON_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_penpot,
    g_comment,
    g_close,
    g_charset,
    g_cells,
    g_quote,
    g_named,
    g_session,
    g_newcmp,
)
MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_trace,
    g_ruled,
    g_inventory,
    g_clause,
    g_envbadge,
    g_map,
    g_generic,
    g_otp,
    g_lockout,
    g_busy,
    g_time,
    g_live,
    g_copy,
    g_sr,
    g_script,
    g_never,
    g_esc,
    g_target,
    g_contrast,
    g_cvd,
    g_rbac,
    g_frows,
    g_assert,
    g_pass2,
    g_template,
    g_crows,
    g_grows,
    g_qrows,
    g_arow,
    g_handref,
    g_walk,
    g_except,
    g_dod,
    g_deviations,
    g_entropy,
    g_untouched,
    g_version,
)


# ---------------------------------------------------------------------------- the pins

PIN_DOCS: tuple[str, ...] = ("spec",)  # every unit of the spec; no span is exempt


def write_pins(units: list[Unit]) -> str:
    head = (
        "# E09-D10 pins (every unit of the spec): doc, region (heading path #occurrence), "
        f"location, the exact normalised text; {len(units)} units.\n# Written by `--repin-ruled` "
        "only; `--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in units)


# ---------------------------------------------------------------------------- mutations


def pristine_drift(cid: str, n: int, text: str) -> Callable[[], Callable[[], None]]:
    """A cited line edited at `origin/main` (G-VERSION's content lever)."""

    def run() -> Callable[[], None]:
        DRIFT.append((cite_path(cid) or "", n, text))

        def undo() -> None:
            DRIFT.pop()

        return undo

    return run


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


S11 = "1.1 What this review fixes"
MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1",
        "G-PENPOT",
        "S-3: pages by name and id only",
        # a reserved example host (RFC 2606), planted in memory only: no real link
        spec=sub_in(STATUS_HEAD, "D09:514).", "D09:514; https://penpot.example/view)."),
    ),
    Mutation("M-2", "G-COMMENT", "BQ-1: no hidden comment", spec=prose_at(S11, "[//]: # (a note)")),
    Mutation(
        "M-3",
        "G-CLOSE",
        "BQ-10: no closing keyword",
        spec=line_edit(
            "**Ticket:**", "with a `Partial:` line,", "with a `Partial:` line; closes #193,"
        ),
    ),
    Mutation(
        "M-4",
        "G-CHARSET",
        "BQ-1: the charset",
        spec=sub_in(S11, "The accessibility contract", "The accessibility contract"),
    ),
    Mutation(
        "M-5",
        "G-CELLS",
        "BQ-1: every row its header's cells",
        spec=row_edit(INV_HEAD, "SCR-005 lock with CMP-098", 2, appended(" | extra")),
    ),
    Mutation(
        "M-6",
        "G-QUOTE",
        "BQ-1: quotes verbatim at a cited source",
        spec=say_in(S11, 'It reads "a sentence that no merged source holds".'),
    ),
    Mutation(
        "M-7",
        "G-NAMED",
        "BQ-1: named only, never quoted",
        spec=line_edit("**Start.**", "quoted:** #190,", 'quoted:** #190 ("boards"),'),
    ),
    Mutation(
        "M-8",
        "G-SESSION",
        "S-9: no session claimed",
        spec=say_in("19.2 The heuristic", "An owner walkthrough was held."),
    ),
    Mutation(
        "M-9",
        "G-NEWCMP",
        "BQ-1: no new component",
        spec=say_in(OTP_HEAD, "A new component draws the cells."),
    ),
    Mutation("M-10", "G-TRACE", "BQ-1: the AC trace", spec=drop_row_prefix(TRACE_HEAD, "AC3")),
    Mutation(
        "M-11",
        "G-RULED",
        "the five ruled differently",
        spec=sub_in(RULED_HEAD, "**BQ-27:** D04's hidden", "BQ-27: D04's hidden"),
    ),
    Mutation(
        "M-12", "G-INVENTORY", "BQ-5: the eight surfaces", spec=drop_row_prefix(INV_HEAD, "SCR-149")
    ),
    Mutation(
        "M-13",
        "G-CLAUSE",
        "R-3: a verdict with its row",
        spec=row_edit(CLAUSE_HEAD, "`5.1`", 3, to("compliant")),
    ),
    Mutation(
        "M-14",
        "G-ENVBADGE",
        "BQ-8 rider: never compliant",
        spec=row_edit(CLAUSE_HEAD, "`4.1`", 3, to("compliant")),
    ),
    Mutation(
        "M-15",
        "G-MAP",
        "AC3: never the body",
        spec=row_edit(MAP_HEAD, "T-6", 4, to("the document body")),
    ),
    Mutation(
        "M-16",
        "G-MAP",
        "AC3: a defined announcement",
        spec=row_edit(MAP_HEAD, "T-13", 5, to("—")),
    ),
    Mutation(
        "M-17",
        "G-GENERIC",
        "BQ-12: one generic failure",
        spec=row_edit(MAP_HEAD, "T-6", 2, to("a disabled account")),
    ),
    Mutation(
        "M-18", "G-OTP", "BQ-13: one input", spec=say_in(OTP_HEAD, "The OTP keeps six inputs.")
    ),
    Mutation(
        "M-19",
        "G-LOCKOUT",
        "AC6: a lockout path is a Blocker",
        spec=row_edit(FROW_HEAD, "F-1", 2, to("Major")),
    ),
    Mutation(
        "M-20",
        "G-BUSY",
        "BQ-14: never disable the focused control",
        spec=sub_in(RULES_HEAD, "becomes `readonly`, never `disabled`", "becomes `disabled`"),
    ),
    Mutation(
        "M-21",
        "G-TIME",
        "AC4: satisfying 2.2.1",
        spec=row_edit(TL_HEAD, "TL-1", 4, to("an exception under 2.2.1")),
    ),
    Mutation(
        "M-22",
        "G-TIME",
        "BQ-15 rider: no longer window asked",
        spec=say_in(TL_HEAD, "G-1 asks for a longer enrolment-only session."),
    ),
    Mutation(
        "M-23",
        "G-LIVE",
        "BQ-16: at risk until the A-row",
        spec=sub_in(LIVE_HEAD, "is at risk: F-19 to F-24", "is compliant: F-19 to F-24"),
    ),
    Mutation(
        "M-24",
        "G-LIVE",
        "T Perf: no per-tick region",
        spec=say_in(LIVE_HEAD, "The SCR-001 countdown is announced every second."),
    ),
    Mutation(
        "M-25",
        "G-COPY",
        "BQ-17: no SCR-005 exception",
        spec=row_edit(
            COPY_HEAD, "SCR-005 and SCR-006 failure", 1, to('"Incorrect password. Try again."')
        ),
    ),
    Mutation(
        "M-26",
        "G-SR",
        "BQ-18: `05` §8.1's configurations",
        spec=say_in(SRCONF_HEAD, "The script also targets VoiceOver with Safari."),
    ),
    Mutation(
        "M-27",
        "G-SCRIPT",
        "AC5: every step its strings",
        spec=row_edit(SCRIPT_HEAD, "SR-12", 5, to("the step's announcement")),
    ),
    Mutation(
        "M-28",
        "G-NEVER",
        "BQ-20: the never-list",
        spec=row_edit(SCRIPT_HEAD, "SR-5", 5, appended("; the code read aloud")),
    ),
    Mutation(
        "M-29",
        "G-ESC",
        "BQ-21: the lock ignores `Esc`",
        spec=row_edit(TRAPS_HEAD, "SCR-005 lock", 2, to("dismisses")),
    ),
    Mutation(
        "M-30",
        "G-CONTRAST",
        "BQ-24: no pass below the bar",
        spec=row_edit(PAIRS_HEAD, "P-14 links", 7, to("the recovery and back links")),
    ),
    Mutation(
        "M-31",
        "G-CONTRAST",
        "BQ-24: no self-logged exception",
        spec=sub_in(PAIRS_HEAD, "(D03A:23–34) is not accepted", "(D03A:23–34) is accepted"),
    ),
    Mutation(
        "M-32",
        "G-CVD",
        "BQ-25: colour alone fails",
        spec=row_edit(CR_HEAD, "CR-3", 4, to("compliant")),
    ),
    Mutation(
        "M-33",
        "G-RBAC",
        "BQ-27: a Minor, absent by plan in v1",
        spec=row_edit(FROW_HEAD, "F-17", 2, to("Major")),
    ),
    Mutation(
        "M-34",
        "G-FROWS",
        "S-20: never an agent",
        spec=row_edit(FROW_HEAD, "F-5", 5, to("the hcl-worker-1 agent")),
    ),
    Mutation(
        "M-35",
        "G-ASSERT",
        "T Obs: a named requirement",
        spec=row_edit(ASSERT_HEAD, "AS-6", 1, to("the login form")),
    ),
    Mutation(
        "M-36",
        "G-TEMPLATE",
        "AC1: no unexplained N/A",
        spec=sub_in(
            TEMPLATE_HEAD,
            "Then N/A: the pattern adds no motion; a permission change re-renders in place"
            " (D09:128)",
            "Then N/A",
        ),
    ),
    Mutation(
        "M-37",
        "G-GROWS",
        "S-16: tickets or spec owners",
        spec=row_edit(GROW_HEAD, "G-2", 3, to("the agent lane")),
    ),
    Mutation(
        "M-38", "G-CROWS", "BQ-35: the C-rows in order", spec=drop_row_prefix(CROW_HEAD, "C-30")
    ),
    Mutation(
        "M-39",
        "G-QROWS",
        "S-13: due at once",
        spec=row_edit(QROW_HEAD, "Q-2", 4, to("next sprint")),
    ),
    Mutation(
        "M-40",
        "G-AROW",
        "S-15: Old verbatim at its line",
        spec=row_edit(AROW_HEAD, "A-4", 3, to("warns before the admin session ends")),
    ),
    Mutation(
        "M-41",
        "G-HANDREF",
        "BQ-1: no hand-off file",
        spec=say_in(S11, "The rows also live in E09-D10-handoff.md."),
    ),
    Mutation(
        "M-42",
        "G-WALK",
        "S-12: needs = found + not found",
        spec=in_lines(WALK_HEAD, walk_counts("QA: E09-Q02 (#293)", "4")),
    ),
    Mutation(
        "M-43",
        "G-EXCEPT",
        "BQ-30: never the idle lock",
        spec=row_edit(EX_HEAD, "EX-3", 1, to("the idle lock (TL-1)")),
    ),
    Mutation(
        "M-44",
        "G-DOD",
        "S-7: the owner's items stay open",
        spec=line_edit("- [ ] Owner sign-off", "- [ ]", "- [x]"),
    ),
    Mutation(
        "M-45",
        "G-DEVIATIONS",
        "BQ-1: the title and labels",
        spec=sub_in(
            DEV_HEAD, "E09-D10 accessibility design review", "E09-D10 accessibility review"
        ),
    ),
    Mutation(
        "M-46",
        "G-ANCHOR",
        "BQ-1: every figure computed",
        spec=say_in(TL_HEAD, "The lock lasts 15 min."),
    ),
    Mutation(
        "M-47",
        "G-WORDCOUNT",
        "BQ-1: counts are anchored",
        spec=say_in(S11, "It reviews eight surfaces."),
    ),
    Mutation(
        "M-48",
        "G-MARKER",
        "BQ-1: comments are anchors",
        spec=sub_in(S11, "The accessibility contract", "<!-- note -->The accessibility contract"),
    ),
    Mutation(
        "M-49",
        "G-HEX",
        "BQ-1: hex values are the tool's",
        spec=say_in(PAIRS_HEAD, "The ring reads #6EA1F5."),
    ),
    Mutation("M-50", "G-CITE", "BQ-1: every cite at the base", spec=say_in(S11, "See `05`:9999.")),
    Mutation(
        "M-51",
        "G-VERSION",
        "S-11: re-pin by content",
        patch=pristine_drift("22", 81, "    * **Lifetime.** changed at origin/main."),
    ),
    Mutation("M-52", "G-UNTOUCHED", "the standing rule", plan=("14", lambda x: x + "\nan edit\n")),
    Mutation(
        "M-53",
        "G-ENTROPY",
        "BQ-20: no secret shape",
        spec=with_values(
            lambda _v: say_in(
                "13.2 Fixtures", '`"apikey": "' + coded("Zx9QpL", "2mWv7R", "tY4kBn8") + '"`'
            )
        ),
    ),
    Mutation(
        "M-54",
        "G-TARGET",
        "BQ-23: every drawn target measured",
        spec=row_edit(TARGET_HEAD, "SCR-001 Sign in", 3, to("below the bar")),
    ),
    Mutation(
        "M-55",
        "G-LIVE",
        "BQ-16: no assertive map row compliant",
        spec=row_edit(MAP_HEAD, "T-61", 8, to("compliant")),
    ),
    Mutation(
        "M-56",
        "G-GENERIC",
        "BQ-12: one generic-failure step",
        spec=row_edit(SCRIPT_HEAD, "SR-1", 2, to("`viewer-disabled`")),
    ),
    Mutation(
        "M-57",
        "G-MAP",
        "BQ-11: the Lock now row",
        spec=row_edit(MAP_HEAD, "T-41", 2, to("the button pressed")),
    ),
    Mutation(
        "M-58",
        "G-BUSY",
        "BQ-14: a busy row per surface",
        spec=row_edit(MAP_HEAD, "T-66", 4, to("Unlock admin, natively disabled")),
    ),
    Mutation(
        "M-59",
        "G-SR",
        "BQ-18: tasks 1-3 are `05`'s own",
        spec=sub_in(SRCONF_HEAD, "not this script's steps", "this script's steps"),
    ),
    Mutation(
        "M-60",
        "G-CVD",
        "BQ-25: every carrier listed",
        spec=drop_row_prefix(CR_HEAD, "CR-7"),
    ),
    Mutation(
        "M-61",
        "G-SCRIPT",
        "BQ-12: a step per carried cause",
        spec=row_edit(SCRIPT_HEAD, "SR-24", 4, to("T-50")),
    ),
    Mutation(
        "M-62",
        "G-NEVER",
        "BQ-20: the ruled placeholder",
        spec=sub_in(
            "13.2 Fixtures",
            "`{totp_gen(fixture_secret, now)}` (QP:37's form)",
            "`{totp_gen(secret, at)}` (QP:37's form)",
        ),
    ),
    Mutation(
        "M-63",
        "G-LOCKOUT",
        "AC6: pass 2's lockout path a Blocker",
        spec=row_edit(FROW_HEAD, "F-25", 2, to("Major")),
    ),
    Mutation(
        "M-64",
        "G-PASS2",
        "BQ-7: each pass-2 row at its severity",
        spec=row_edit(FROW_HEAD, "F-26", 2, to("Minor")),
    ),
    Mutation(
        "M-65",
        "G-PASS2",
        "BQ-7: each pass-2 row folded",
        spec=row_edit(METHOD_HEAD, "P2-39", 2, to("to be decided")),
    ),
    Mutation(
        "M-66",
        "G-PASS2",
        "AC5: each dry-run step fixed",
        spec=row_edit(METHOD_HEAD, "SR-23", 2, to("nothing changed")),
    ),
)
# X-n: paraphrases of a ruled behaviour, applied AFTER a simulated re-pin (the pins accept them),
# so the named semantic gate alone must catch each
PARAPHRASES: tuple[tuple[str, str, str, str], ...] = (
    ("X-1", "G-OTP", OTP_HEAD, "Each cell is its own field, six inputs exposed."),
    ("X-2", "G-BUSY", BUSY_HEAD, "While verifying, the focused field is disabled."),
    ("X-3", "G-TIME", TL_HEAD, "The remedy is an extended enrolment window."),
    ("X-4", "G-LIVE", LIVE_HEAD, "The countdown speaks each second."),
    ("X-5", "G-NEVER", COPY_HEAD, "The alert reads out the typed password."),
    ("X-6", "G-SR", SRCONF_HEAD, "QA runs the script on Safari with VoiceOver."),
    ("X-7", "G-ESC", TRAPS_HEAD, "Escape dismisses the lock card."),
    ("X-8", "G-CONTRAST", PAIRS_HEAD, "The border exception stands."),
    ("X-9", "G-RBAC", RBAC_HEAD, "Disable two-factor could be T2 with a state reason."),
    ("X-10", "G-GENERIC", "6.1 Precedence", "A disabled account gets its own banner."),
    ("X-11", "G-SESSION", "19.2 The heuristic", "A session was held with the owner."),
    ("X-12", "G-NEWCMP", OTP_HEAD, "Another component carries the code."),
    ("X-13", "G-OTP", OTP_HEAD, "The field auto-advances per digit."),
    ("X-14", "G-ESC", TRAPS_HEAD, "Esc dismisses SCR-005."),
    ("X-15", "G-TIME", TL_HEAD, "The enrolment-only window is extended for assistive users."),
    # lens 2's paraphrases that passed a re-pin (X1 ... X32 there), each now a named gate's
    (
        "X-16",
        "G-BUSY",
        BUSY_HEAD,
        (
            "While verifying, the field that holds focus is greyed out and taken out of the tab"
            " sequence."
        ),
    ),
    (
        "X-17",
        "G-BUSY",
        BUSY_HEAD,
        "Nothing stops focus from dropping to the document body while the form is busy.",
    ),
    ("X-18", "G-BUSY", BUSY_HEAD, "During the request focus is moved onto the body of the page."),
    (
        "X-19",
        "G-BUSY",
        BUSY_HEAD,
        "Focus drops to the document body, as F-3 records for every surface.",
    ),
    (
        "X-20",
        "G-OTP",
        OTP_HEAD,
        (
            "The code is typed into six single-character boxes, focus hopping to the next one after"
            " each digit."
        ),
    ),
    ("X-21", "G-OTP", OTP_HEAD, "Focus jumps forward automatically after every digit of the code."),
    ("X-22", "G-LIVE", LIVE_HEAD, "The rate-limit countdown is voiced politely on each tick."),
    ("X-23", "G-LIVE", LIVE_HEAD, "The countdown region is a polite live region."),
    (
        "X-24",
        "G-NEVER",
        COPY_HEAD,
        "After a failed attempt the typed password is voiced back to the user.",
    ),
    ("X-25", "G-NEVER", COPY_HEAD, "The live region reads the TOTP secret to the user once."),
    (
        "X-28",
        "G-TIME",
        EX_HEAD,
        "G-1 asks the threat-model owner to prolong the enrolment window to an hour.",
    ),
    ("X-30", "G-ESC", TRAPS_HEAD, "Escape exits the lock."),
    (
        "X-31",
        "G-ESC",
        TRAPS_HEAD,
        "On CMP-098, `Esc` keeps the user signed in by extending the session.",
    ),
    ("X-32", "G-CONTRAST", PAIRS_HEAD, "On reflection, D03's border exception is retained."),
    ("X-33", "G-COPY", COPY_HEAD, "SCR-001's verb stays Log in and its label stays Email."),
    ("X-34", "G-SR", SRCONF_HEAD, "NVDA also runs against Edge and Brave."),
    (
        "X-35",
        "G-LOCKOUT",
        RULES_HEAD,
        "A lockout path that only a rare user meets may be graded Major instead of Blocker.",
    ),
    ("X-36", "G-LIVE", LIVE_HEAD, "The verdicts of §7 hold only once the `05` owner applies A-5."),
    (
        "X-37",
        "G-RBAC",
        RBAC_HEAD,
        "Until v2 the control is drawn as a disabled Disable two-factor button.",
    ),
    (
        "X-38",
        "G-BUSY",
        BUSY_HEAD,
        "When a focused control unmounts, focus is left wherever the browser puts it.",
    ),
    (
        "X-39",
        "G-GENERIC",
        "6.1 Precedence",
        "SCR-001 shows a separate message for a disabled account.",
    ),
)
# X-n edits in place (lens 2's X15, X17, X19): a ruled sentence inverted where it stands
PARA_EDITS: tuple[tuple[str, str, Edit], ...] = (
    (
        "X-26",
        "G-NEVER",
        in_lines(
            NEVER_HEAD,
            line_after(
                "- A literal value",
                "- Exception: a recovery code may be read aloud in the polite region when the user"
                " asks.",
            ),
        ),
    ),
    (
        "X-27",
        "G-TIME",
        sub_in(TL_HEAD, "so it is not asked here,", "so it is asked here as the fallback,"),
    ),
    (
        "X-29",
        "G-EXCEPT",
        sub_in(
            EX_HEAD,
            "The idle lock is not an exception (AC4).",
            "The idle lock is treated as an Essential exception as well (AC4).",
        ),
    ),
)
# N-n: negated forms that must trip nothing (after a simulated re-pin)
NEGATIONS: tuple[tuple[str, str, str], ...] = (
    ("N-1", OTP_HEAD, "The OTP never keeps six inputs."),
    ("N-2", BUSY_HEAD, "No focused field is ever disabled."),
    ("N-3", LIVE_HEAD, "No countdown is announced every second."),
    ("N-4", TRAPS_HEAD, "Escape never dismisses the lock card."),
    ("N-5", COPY_HEAD, "No alert reads out the typed password."),
    ("N-6", SRCONF_HEAD, "Safari is out of scope."),
    ("N-7", TL_HEAD, "No longer enrolment window is asked."),
    ("N-8", BUSY_HEAD, "Focus never drops to the document body."),
    ("N-9", EX_HEAD, "The idle lock is never an exception."),
    ("N-10", LIVE_HEAD, "No verdict depends on A-5."),
    ("N-11", TRAPS_HEAD, "Esc never extends the session."),
)
# P-n: one per pin class; no semantic gate reads these, so G-RULED-PIN alone must catch each
PIN_PROBES: tuple[Mutation, ...] = (
    Mutation(
        "P-1",
        "G-RULED-PIN",
        "pin: a word in a sentence",
        spec=sub_in("1.2 Method", "A desk review under T Adapt.", "A desk review near T Adapt."),
    ),
    Mutation(
        "P-2", "G-RULED-PIN", "pin: a sentence added", spec=say_in("1.2 Method", "It is careful.")
    ),
    Mutation(
        "P-3",
        "G-RULED-PIN",
        "pin: a sentence deleted",
        spec=sub_in("1.2 Method", " No participant, session, timing or quote exists.", ""),
    ),
    Mutation(
        "P-4",
        "G-RULED-PIN",
        "pin: a heading renamed",
        spec=sub_in(S11, "### 1.1 What this review fixes", "### 1.1 What the review fixes"),
    ),
    Mutation(
        "P-5",
        "G-RULED-PIN",
        "pin: a cell no gate reads",
        spec=row_edit(
            LOCKED_HEAD,
            "D02 — the states matrix; the shared chassis; the no-dead-ends rule",
            2,
            to("§2"),
        ),
    ),
    Mutation(
        "P-6",
        "G-RULED-PIN",
        "pin: rows swapped",
        spec=in_lines(INV_HEAD, swap_rows("SCR-005 lock with CMP-098", "SCR-006 step-up")),
    ),
    Mutation(
        "P-7",
        "G-RULED-PIN",
        "pin: a line indented",
        spec=in_lines(RULES_HEAD, indented("- **R-8", 2)),
    ),
    Mutation("P-8", "G-RULED-PIN", "pin: the pins file damaged", patch=lambda: damaged_pins()),
    Mutation(
        "P-9",
        "G-RULED-PIN",
        "pin: a fenced line",
        spec=sub_in(
            TEMPLATE_HEAD,
            "Then the route cut and the error swap are instant",
            "Then the route cut and the error swap are quick",
        ),
    ),
)


PIN_UNITS_OVERRIDE: list[tuple[Unit, ...]] = []  # the self-test's simulated re-pin (X-n, N-n)
ALL_MUTATIONS: tuple[Mutation, ...] = (
    *MUTATIONS,
    *(
        Mutation(x, g, f"paraphrase after a re-pin: {s[:40]}", spec=say_in(h, s))
        for x, g, h, s in PARAPHRASES
    ),
    *(Mutation(x, g, f"paraphrase in place after a re-pin: {x}", spec=e) for x, g, e in PARA_EDITS),
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


def selftest(spec: str, paths: tuple[Path, ...]) -> tuple[bool, list[str]]:
    on_disk = digest(paths)
    plans = read_plans()
    values = compute(spec)[0]
    spec_f, _ = fill(spec, values)
    values = compute(spec_f)[0]  # frozen at the filled baseline
    base_fails, _notes, base_warns, _ = audit(Texts(spec_f, "", plans, values), git_fetch)
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
    built = [(mu.mid, mu.gate) for mu in MUTATIONS]
    if listed != built:
        ok = False
        lines.append(f"  section 16 lists {len(listed)} M-rows, the tool builds {len(built)}")
        lines += [
            f"    differ at {a} / {b}" for a, b in zip(listed, built, strict=False) if a != b
        ][:3]
    pristine = digest_texts(spec_f, *(x for _n, x in plans))
    for mu in ALL_MUTATIONS:
        s = mu.spec(spec_f, values) if mu.spec else spec_f
        new_plans = plans
        if mu.plan:
            key, fn = mu.plan
            new_plans = tuple((nn, fn(x) if nn == key else x) for nn, x in plans)
        if (s, new_plans) == (spec_f, plans) and mu.patch is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        undo = mu.patch() if mu.patch else None
        repin = mu.mid.startswith(("X-", "N-"))
        if repin:
            PIN_UNITS_OVERRIDE.append(tuple(ruled_units(s, "", values)))
        try:
            fails, _n2, _w, _c = audit(Texts(s, "", new_plans, values), git_fetch)
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
        restored = digest_texts(spec_f, *(x for _n, x in plans)) == pristine
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
    ap = argparse.ArgumentParser(description="E09-D10 a11y review audit (module docstring)")
    ap.add_argument(
        "--check",
        nargs="?",
        const=SPEC_REL,
        default=None,
        metavar="SPEC",
        help="audit the spec (default: the committed path)",
    )
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
        units = ruled_units(spec, "", compute(spec)[0])
        write_text(ROOT / RULED_PIN_TXT, write_pins(units))
        print(f"--repin-ruled: {len(units)} units pinned in {RULED_PIN_TXT}")
        return 0
    if args.self_test:
        paths = (spec_path, ROOT / RULED_PIN_TXT, *(p for _n, p in plan_paths()))
        ok, lines = selftest(spec, paths)
        print("\n".join(lines))
        print(report(f"--self-test: {'ok' if ok else 'FAIL'} - {len(ALL_MUTATIONS)} mutations"))
        return 0 if ok else 1
    values, extra = compute(spec)
    if args.fill:
        spec, unknown = fill(spec, values)
        write_text(spec_path, spec)
        for u in unknown:
            print(f"FAIL --fill: no value for {{{{{u}}}}}")
        values, extra = compute(spec)
    if args.json and not (args.check or args.fill):
        print(json.dumps({"values": values, "extra": extra}, ensure_ascii=False, indent=1))
        return 0
    t = Texts(spec, "", read_plans(), values)
    fails, notes, warns, n = audit(t, git_fetch)
    if args.json:
        doc = {"values": values, "extra": extra, "fails": fails, "notes": notes, "warnings": warns}
        print(json.dumps(doc | {"cites": n}, ensure_ascii=False, indent=1))
    else:
        gates = len(LEXICON_GATES) + len(MEASURED_GATES) + 7
        shown = spec_path.relative_to(ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        print(f"## E09-D10 audit of {shown} at base {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(notes))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK - every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(notes)} NOTE, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
