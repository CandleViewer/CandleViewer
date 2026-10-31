#!/usr/bin/env python3
"""E09-D12 (#194) audit: the engineering hand-off pack for the auth, session and RBAC band.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the plan texts and the merged E09 design docs the spec
cites, `22`'s operations, the shipped screens it cites as evidence, the audit registry, the token
JSON (dark = primitives + semantic-dark, light = + semantic-light, hc = + semantic-hc), the CVD
script's constants, the calendar and the ticket JSON; then the spec and its copy deck from the
working tree.

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: CITE (a figure parsed from
   its cited line at the base), RULED (R194's own figures), COUNT (the spec's tables and the
   deck), CONTRAST (WCAG 2.x, truncated to two decimals, in three themes), SPRINT (the calendar).
   `--fill` writes `VALUE<!--=KIND:key-->`; `--check` re-derives every anchored value with a
   left boundary (G-ANCHOR), and FAILs a figure typed by hand before a unit or a counted noun and
   a count written as a word (G-WORDCOUNT).
2. **The comment strip.** One pattern over the whole text; every HTML comment must be a value
   anchor the tool computes (G-MARKER); a `[//]: #` comment is refused (G-COMMENT).
3. **Cites.** Every cite is read at the base (G-CITE); G-VERSION is content-based: each cited
   range stands, in order and contiguous, somewhere in the file at `origin/main` (a move is fine,
   an edit FAILs; an unresolvable `origin/main` FAILs); it also reads the version line (the base,
   each pinned doc's last touch, every sha under the base). G-QUOTE: every quoted string of
   QUOTE_MIN characters or more is verbatim in a source its line cites, a core source, the deck or
   R194's own words.
4. **Gates.** The data contract against `22` (G-OPS, G-FIELDS), the error map (G-ERRMAP,
   G-FALLBACK), the deck (G-DECK: provenance re-read at the cited line; G-FROZEN), the frame
   register (G-FRAME), the component map (G-COMP, G-NEWCMP), tokens, contrast and CVD (G-TOKENS,
   G-CONTRAST, G-CVD), the rows (G-CROWS, G-GROWS, G-QROWS, G-AROWS), the design-ahead record
   (G-AHEAD), the dry run (G-WALK), the ruling (G-RULED, G-DEVIATIONS), and one lexicon gate per
   ruled behaviour that reads cells and clauses with its synonyms (G-BADGE, G-FOOTER, G-UNIFORM,
   G-COUNTDOWN, G-TRUST, G-RECOVERY, G-DISABLE, G-REASON, G-INVITE, G-EXHAUST, G-SESSION,
   G-GRACE). A lexicon is a finite word list: a paraphrase outside every list is caught by the
   pins alone. An exemption word counts only next to the term it exempts and never inside a
   falsity frame; a quoted label before its unit is read as words; clauses split at ` · ` too.
   G-FROZEN and G-NEVER read the frozen set's cells, the hooks' security texts and the never-list
   word by word; G-DECKKEY the keys' provenance (BQ-26); G-FOLD the folded lens findings;
   G-SHAPE and G-BOLD the heading levels, code indentation and the ruled clauses' bold.
   G-UNTOUCHED compares committed and uncommitted paths with `git merge-base HEAD origin/main`
   and FAILs when it does not resolve or a git call fails; only this PR's four files may differ,
   and `14` only by BQ-40's pointer lines. G-EDGE matches patterns, never literals: a cite key
   the key table does not declare, a server-tree path it does not carry, or a fix-direction
   wording arm (round 1 P-1: ids and trackers public, detail private). G-CHARSET, G-CELLS,
   G-CLOSE, G-PENPOT, G-ENTROPY, G-HANDREF and G-BUDGET close the set.
5. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over EVERY unit of the spec
   (each heading, table row by its lead cell, rule line, prose sentence and fenced block, by
   region and location, NFKC and whitespace-normalised, with a line-shape tag per region) and
   every entry of the deck, in PIN_REL. Anchored values are pinned with their values cut out.
   `--repin-ruled` is the only writer and refuses while a placeholder is unfilled. A pin finding
   in a section another gate already FAILs prints as a NOTE line.
6. **--self-test** applies every mutation of the spec's §18 (M-n) and the tool's X-n paraphrases
   (re-pinned, so only the lexicon gate may catch them) and P-n pin probes, with the values frozen
   at the filled baseline; each must add exactly one FAIL, from the gate it names, and every text
   is restored byte-identically (sha256 in memory and on disk). The report is ASCII, every line at
   most 100 characters.
7. **v2 (the closing version, R2 = ruling 6547862139).** The spec is v1 as merged (`V1_SHA`) plus
   blocks whose heading ends "(v2)" and the in-place lines its §17.1 register names (C rows).
   A line is a v1 line or a v2 line by content: a v1 line's cites are read at `BASE`, a v2 line's
   at `BASE_V2`. The v1 gates run on the v1 view (the spec without its v2 blocks); the lexicon,
   document, cite and pin gates run on the whole spec; the v2 gates read the v2 blocks. G-V1-FROZEN
   holds the v1 view byte-equal to v1 but for the C rows; G-REGISTER reads §17.1; G-DELTA ties the
   pin diff against v1's pins to §17.1; G-CITED-STABLE keeps the lines and section numbers other
   files cite. A v1 cite edited at `origin/main` must be a §17.3 row.
8. **Modes, by content (never a flag).** PR mode: the spec differs from its copy at `origin/main`.
   Post-merge mode: the spec equals that copy and the copy carries the v2 version line; a cited
   range edited later is then a WARN naming the commit, never a FAIL, and G-UNTOUCHED reads
   nothing; every content gate runs unchanged. `--self-test` runs its PR tuple in PR mode and its
   post-merge tuple (Z-n, with expected WARNs) in post-merge mode, and prints both counts.

Usage (from the repo root):
  python3 -I docs/design/_tools/e09_d12_audit.py --check [SPEC] [--json] [--fill]
  python3 -I docs/design/_tools/e09_d12_audit.py --self-test
  python3 -I docs/design/_tools/e09_d12_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import ast
import datetime
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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "121e9e989b"  # v1's base: every v1 line's cite was read here (the spec's Inputs line)
BASE_V2 = "16d70feed9"  # v2's base: every v2 line's cite is read here (the Ticket line)
V1_SHA = "67ab4aa8a5"  # v1 as merged (#4959): G-V1-FROZEN's reference and G-DELTA's pins
V2_MARK = "(v2)"  # every v2 block's heading ends with it
HEAD = "origin/main"  # G-VERSION: a cited range edited at origin/main FAILs (PR mode)
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E09/E09-D12.md"
DECK_REL = "docs/design/E09/E09-D12-copy.json"
TOOL_REL = "docs/design/_tools/e09_d12_audit.py"
PIN_REL = "docs/design/_tools/e09_d12_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, DECK_REL, TOOL_REL, PIN_REL)
DS_SRC_REL = "packages/ui/tokens"
CITE_FILES: dict[str, str] = {
    "D02": "docs/design/E09/E09-D02.md",
    "D03": "docs/design/E09/E09-D03.md",
    "D03A": "docs/design/E09/E09-D03-a11y-audit.md",
    "D03Q": "docs/design/E09/E09-D03-design-qa-checklist.md",
    "D04": "docs/design/E09/E09-D04.md",
    "D05": "docs/design/E09/E09-D05.md",
    "D05H": "docs/design/E09/E09-D05-handoff.md",
    "D06": "docs/design/E09/E09-D06.md",
    "D08": "docs/design/E09/E09-D08.md",
    "D09": "docs/design/E09/E09-D09.md",
    "S03": "docs/design/E09/E09-S03.md",
    "README": "docs/design/README.md",
    "CONST": "CONSTITUTION.md",
    "TM": "docs/security/threat-models/e09-auth-rbac.md",
    "REV": "docs/security/reviews/e09-auth-review.md",
    "ACT": "services/api/candleviewer/audit/actions.py",
    "GEN": "services/api/candleviewer/api/_generated/openapi_models.py",
    "LOGIN": "apps/web/src/features/auth/LoginScreen.tsx",
    "INVITE": "apps/web/src/features/invites/InviteAcceptScreen.tsx",
    "CHECK": "apps/web/src/features/onboarding/SetupChecklistCard.tsx",
    "STEPUP": "apps/web/src/features/stepUp/StepUpDialog.tsx",
    "SESSAPI": "apps/web/src/features/session/sessionsApi.ts",
    "MAN": "apps/web/src/routes/manifest.ts",
    "CVD": "docs/research/_tools/cvd_simulate.py",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "E09J": "docs/plan/backlog/E09.json",
    "D07": "docs/design/E09/E09-D07.md",
    "D10": "docs/design/E09/E09-D10.md",
    "E17D02": "docs/design/E17/E17-D02.md",
}
# the standing rule: no `05`, `14`, `15`, `16`, `21`, `22`, `23` or `24` edit, nor of a merged E09
# design doc (G-UNTOUCHED compares each with the merge-base, and refuses any other stray path)
UNTOUCHED = ("05", "14", "15", "16", "21", "22", "23", "24")
UNTOUCHED_DOCS = ("D02", "D03", "D03A", "D03Q", "D04", "D05", "D05H", "D06", "D08", "D09", "S03")
TICKET_KEY = "E09-D12"
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SEMANTIC = ("semantic-dark", "semantic-light", "semantic-hc")
RULING_ID = "6495555374"
BQ_LIST_ID = "6495025903"
# the comment ids the docs may cite: R194, the BQ list, ledger 1, the directive, R188, R940
RULED_IDS = (RULING_ID, BQ_LIST_ID, "6491680793", "6490317249", "6489306947", "6463770354")
# v2: R2 (the ruling of record), its BQ list and the owner's 2026-10-31 directive
R2_ID = "6547862139"
RULED_IDS_V2 = (R2_ID, "6547530536", "6546079373")
REPORT_WIDTH = 100
# S-20 "≤ ~300 lines"; v1 ran past it by the one-row-per-item tables (D6), and v2 adds its
# register and its blocks beside v1's byte-equal text (R2 BQ-02)
SPEC_LINE_BUDGET = 900
# R194's own figures: 34 defaults as proposed of 40, six ruled differently, riders on fifteen;
# the walkthrough protocol "≤ 10 minutes" (BQ-36, taken as proposed); the recovery-code file
# holds "ten codes only" (R194's BQ-34 rider)
RULED_VALUES = {
    "RULED:file.codes": "10",
    "RULED:bq.asproposed": "34",
    "RULED:bq.total": "40",
    "RULED:bq.differently": "6",
    "RULED:bq.riders": "15",
    "RULED:walk.minutes": "10",
}
RULED_DIFFERENTLY = ("BQ-3", "BQ-14", "BQ-15", "BQ-18", "BQ-19", "BQ-39")
RIDERS = (
    "BQ-1",
    "BQ-2",
    "BQ-5",
    "BQ-7",
    "BQ-11",
    "BQ-12",
    "BQ-20",
    "BQ-22",
    "BQ-24",
    "BQ-27",
    "BQ-28",
    "BQ-34",
    "BQ-35",
    "BQ-38",
    "BQ-40",
)
# R194's wording, carried exactly (G-RULED reads each in its bullet)
RULED_WORDS: dict[str, tuple[str, ...]] = {
    "BQ-3": ('not "pending v2"', "the closing-keyword rule stands"),
    "BQ-14": (
        'keep "no link, no affordance"',
        "v1 has no in-product password recovery",
        "still needs the current password",
        "the owner's lever is disable",
        "any future mechanism keeps TOTP and US-ONB-006",
    ),
    "BQ-15": (
        '"trust this device" is not in v1',
        "the client never sends `remember_device_days`",
        '"no effect in v1" or remove the field',
        "must never skip or shorten TOTP",
    ),
    "BQ-18": (
        'no "Disable two-factor" control in v1',
        "only a per-method remove of a non-last method via `authMfaDeleteMethod`",
        "never D04's client-side step-up",
        "regenerate held",
    ),
    "BQ-19": ("v1 takes E09-D05's strings, row states and error table by cite",),
    "BQ-39": ("G-1 = the version label only", "G-4 re-aimed", "G-9 re-owned"),
    "BQ-11": (
        "no environment badge before sign-in",
        "truthful or absent",
        "G-1's environment half dropped",
        "never the compiled bundle's environment",
    ),
}
# R194's own words the docs may quote (G-QUOTE); the ruling is a comment, not a file at the base
RULING_QUOTES = (
    "no link, no affordance",
    "disabled to zero",
    "no trust-device control in v1",
    "trust this device",
    "no effect in v1",
    "Disable two-factor",
    "not published — #190 not started",
    "built in code (#4745), not published",
    "E09-D05 boards (PR 2) pending",
    "waived 2026-10-29",
    "every screen",
    "≤ ~300 lines",  # S-20, ruled in bulk with S-1..S-21
)
# the version line (spec **Start.**): every merged input's sha, in order
VERSION_SHAS = (
    "121e9e989b",
    "a30c6ec6ad",
    "05c12212b4",
    "9750dc4bc9",
    "3669e891e6",
    "e1dfcb3e2f",
    "2145b48036",
    "3c1a9d769d",
    "6359111929",
    "b1425624b9",
    "c99ad48d78",
    "baccf724a1",
    "d117dc7328",
    "2fd29ecc34",
    "ff8933a1c2",
    "2145b48036",
    "c99ad48d78",
    "d117dc7328",
    "2fd29ecc34",
    "a8f47b754f",
)
PINNED_DOCS = {
    "D02": "ff8933a1c2",
    "D03": "ff8933a1c2",
    "D04": "ff8933a1c2",
    "D06": "ff8933a1c2",
    "D05": "2145b48036",
    "D05H": "2145b48036",
    "D08": "c99ad48d78",
    "D09": "d117dc7328",
    "S03": "2fd29ecc34",
    "22": "a8f47b754f",
}
NAMED_ONLY = ("#190", "#193", "#2110", "#2711", "#4743", "#2289", "#291", "#293", "#297")
CONSUMER_ROLES = (
    "story: #2711 (SCR-002)",
    "story: #2110 frontend leg",
    "story: #4743 (Lock now)",
    "story: E09-D07 (#190)",
    "story: E09-D10 (#193)",
    "QA: E09-D11 (#291)",
    "QA: E09-Q02 (#293)",
    "QA: E09-Q06 (#297)",
    "QA: #2490",
    "frontend: the band (AC3)",
    "backend: the `22` owner",
)
PUBLISH_TO = ("#2711", "#2110", "#4743", "#291", "#293", "#297", "#193", "#190", "#2490")
DRY_DATE = "2026-10-29"
PR_TITLE = "docs(auth-rbac): E09-D12 engineering hand-off pack for the auth, session and RBAC band"
LABELS = (
    "type/design",
    "area/auth-rbac",
    "priority/p0",
    "design",
    "handoff",
    "a11y",
    "security-review",
)

# CITE values: key -> (cite id, line, pattern whose group 1 is the value)
CITE_VALUES: dict[str, tuple[str, int, str]] = {
    "perf.scr001": ("14", 147, r"first paint ≤(\d+) s cold"),
    "perf.scr002": ("14", 174, r"<=(\d+) ms p95"),
    "perf.scr003": ("14", 197, r"QR render <=(\d+) ms"),
    "perf.scr005": ("14", 235, r"Modal mounts <=(\d+) ms"),
    "perf.scr006": ("14", 261, r"Step-up elevation <=(\d+) ms p95"),
    "perf.scr017": ("14", 465, r"between steps <=(\d+) ms"),
    "perf.scr019": ("14", 484, r"cached for (\d+) s"),
    "bar.text": ("05", 125, r"≥(\d+(?:\.\d+)?):1 against their background"),
    "bar.ui": ("05", 126, r"≥(\d+):1 against adjacent colours"),
    "sr024.idle": ("04", 841, r"Idle session timeout (\d+) h"),
    "sr024.abs": ("04", 841, r"absolute lifetime (\d+) days"),
    "ahead.sprints": ("02", 53, r"Done for ≥(\d+) sprints"),
}
# load-bearing fragments: (cite id, line at the base, text the line must hold)
CITED: tuple[tuple[str, int, str], ...] = (
    ("22", 1144, "Failures are deliberately uniform (`unauthenticated`)"),
    ("22", 1145, "the password is wrong, or the account is disabled — no user enumeration."),
    ("22", 1146, "Five consecutive failures lock the account"),
    ("22", 1242, "Six failed attempts invalidate the `mfa_token`"),
    ("22", 1436, "`X-Reauth-Password`. The last remaining method cannot be removed"),
    ("22", 12803, "Every recovery sign-in forces TOTP"),
    ("22", 12908, "expired or consumed token is indistinguishable from an unknown one"),
    ("22", 14088, "Available to any authenticated"),
    ("22", 17562, '"Username or email."'),
    ("22", 17621, "remember_device_days: { type: integer, minimum: 0, maximum: 30"),
    ("22", 22451, 'reason: { type: ["string", "null"] }'),
    ("TM", 133, "The build label (the version) only before authentication"),
    ("04", 831, "Login responses MUST be indistinguishable"),
    ("04", 833, "After 10 consecutive failures"),
    ("04", 841, '"remember this device" MUST NOT bypass TOTP'),
    ("04", 846, "Disabling a user MUST immediately terminate their sessions"),
    ("05", 116, "present on every screen"),
    ("14", 85, "RBAC denies server-side; the UI presents."),
    ("14", 124, "environment badge of the _server_"),
    ("14", 144, "account disabled"),
    ("14", 258, "Confirm disabled until both fields are valid"),
    ("14", 461, "already used"),
    ("14", 2325, "This will sign you out on this device."),
    ("CONST", 758, "TOTP 2FA** is mandatory for every user"),
    ("D03", 107, '"Forgot password?" text link'),
    ("D03", 132, '"Trust this device for 30 days"'),
    ("D04", 166, "**Disable two-factor**"),
    ("D06", 47, "no-grace (Live enablement, kill-switch disable)"),
    ("D08", 471, "E09-D12 (hand-off pack)"),
    ("D09", 408, "The UI is never the security control"),
    ("S03", 186, 'No "Lock now"'),
    ("GEN", 350, "remember_device_days"),
)

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z0-9]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
UNITS = r"(?:ms|s|hz|px|%|:1|fps|h|min)"
COUNTED = (
    r"(?:boards?|twins?|frames?|rows?|states?|pairs?|themes?|questions?|mutations?|characters?"
    r"|items?|consumers?|rules?|fields?|strings?|screens?|roles?|lines?|needs|checks?|entries"
    r"|codes?|g-rows?|c-rows?|q-rows?|a-rows?|variants?|sections?|operations?|conditions?"
    r"|fallbacks?|flows?|tasks?|sprints?|days?|minutes?|seconds?|attempts?|failures?|tries"
    r"|methods?|sessions?|defaults?|riders?|keys?|pngs?|components?|stories|story|gates?)"
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
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
COMMENT_ID = re.compile(r"(?<![\w-])(\d{8,})(?![\w-])")

Values = dict[str, str]
DRIFT: list[tuple[str, int, str]] = []  # self-test lever: (path, line, text) read at HEAD
BROKEN: list[str] = []  # self-test lever: "head" or "merge-base" does not resolve
EXTRA_PATHS: list[str] = []  # self-test lever: paths pretended changed (G-UNTOUCHED)
CVD_OVERRIDE: list[dict[str, tuple[float, ...]]] = []  # self-test lever: drifted CVD constants
PLAN_OVERRIDE: list[tuple[str, str]] = []  # self-test lever: a working-tree plan text (nn, text)
PIN_UNITS_OVERRIDE: list[tuple[Unit, ...]] = []  # self-test lever: re-pinned units (X-n)
PIN_TEXT_OVERRIDE: list[str] = []  # self-test lever: a damaged pins file
# a gate finding: (gate tag, message, doc, section); doc / section None for a repo-level finding
Finding = tuple[str, str, str | None, str | None]
Unit = tuple[str, str, str, str]  # (doc, region, loc, text)


# ---------------------------------------------------------------------------- git and sources


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


@functools.lru_cache(maxsize=512)
def exists_at(rev: str, rel: str) -> bool:
    """`rel` exists at `rev` (binary files included)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", f"{rev}:{rel}"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def git_out(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.decode("utf-8") if out.returncode == 0 else ""


def git_ok(*args: str) -> tuple[bool, str]:
    """(exit status 0, stdout) of a git call; a call that cannot run, or the self-test's "git"
    lever, is (False, "") so a caller can fail closed."""
    if "git" in BROKEN:
        return False, ""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return out.returncode == 0, out.stdout.decode("utf-8")


def git_fetch_head(rel: str) -> str | None:
    """The file at HEAD with the self-test's DRIFT lever applied (G-VERSION)."""
    text = git_show(HEAD, rel)
    if text is None or not DRIFT:
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


def cite_path(cid: str) -> str | None:
    if re.fullmatch(r"\d{2}", cid):
        return plan_rel(cid)
    if cid in CITE_FILES:
        return CITE_FILES[cid]
    if "/" in cid:
        return cid
    return None


def base_lines(cid: str, rev: str = "") -> list[str]:
    rel = cite_path(cid)
    text = git_show(rev or BASE, rel) if rel else None
    return text.split("\n") if text is not None else []


def base_line(cid: str, n: int) -> str:
    lines = base_lines(cid)
    if not 1 <= n <= len(lines):
        raise SystemExit(f"FAIL parse: {cid}:{n} is not a line at {BASE}")
    return lines[n - 1]


@functools.lru_cache(maxsize=1)
def ticket() -> str:
    data = json.loads(at_base(CITE_FILES["E09J"]))
    for t in data:
        if t.get("key") == TICKET_KEY:
            return str(t.get("body", ""))
    raise SystemExit(f"FAIL parse: {TICKET_KEY} not in E09.json")


# ---------------------------------------------------------------------------- markdown helpers

COMMENT = re.compile(r"<!--(?:>|->|.*?--!?>|.*\Z)", re.DOTALL)
_HIDDEN = re.compile(COMMENT.pattern + r"|[\u00ad\u200b-\u200d\u2060\ufeff]", re.DOTALL)


def strip_comments(text: str) -> str:
    return _HIDDEN.sub("", text)


FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def fenced(lines: list[str]) -> list[bool]:
    """For each line, whether it is a fence line or inside a fenced block (the same kind, at
    least as long, closes; an unclosed fence runs to the end)."""
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
    """From the heading starting with `head` (outside fences) to the next heading of the same or
    a higher level outside a fence."""
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


def rows_of(text: str, head: str) -> list[list[str]]:
    return table_rows(section(text, head))


def row_key(cell: str) -> str:
    k = re.sub(r"[*_`]", "", cell).strip()
    return re.sub(r"^([A-Za-z]+)\s+(\d+)$", r"\1-\2", k)


def pin_norm(text: str) -> str:
    """The exact text, NFKC with whitespace collapsed (Prettier's table padding is no change)."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sec_id(heading: str) -> str:
    """A `##` section's key: the first three words of its rendered heading."""
    text = PLACEHOLDER.sub(" ", strip_comments(heading)).lstrip("# ")
    return " ".join(pin_norm(text).split()[:3]) or "(top)"


def h2_of(text: str, head: str) -> str:
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
    """Rendered words only: comments, inline tags and markup dropped, entities decoded, NFKC,
    dashes to spaces, whitespace collapsed, lower case."""
    t = html.unescape(_INLINE_TAG.sub("", strip_comments(text)))
    t = unicodedata.normalize("NFKC", t)
    t = _EMPH.sub(" ", _MARKUP.sub("", _LINK.sub(r"\1", t)))
    return " ".join(_DASHES.sub(" ", t).split()).lower()


def unquote(text: str) -> str:
    return QUOTED.sub(" ", text)


# ---------------------------------------------------------------------------- clause reading

NEG_WORD = r"(?:no|never|not|nor|without|nothing|none|cannot|n't)"
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
NEG_SUBJECT = re.compile(
    r"^\W*(?:no|nothing|none|neither|never)\b(?! (?:doubt|matter|longer|mind|less|sooner))"
)
TURN = re.compile(r"\b(?:but|except|yet|however|unless|instead|although|though)\b")


def _live(t: str, term: str) -> bool:
    t = DOUBLE_NEG.sub(" ", t)
    if NEG_SUBJECT.match(t) and not TURN.search(t):
        return False
    sep = r"(?:,\s*(?:or\s+|nor\s+|and\s+)?|\s+(?:or|nor|and)\s+)"
    listed = rf"(?:{sep}(?:an? )?(?:{term})\w*)*"
    item = rf"(?:[^\s,;]+\s+){{0,2}}[^\s,;]+{sep}"
    word = rf"(?!{TURN.pattern})\S+"
    near_ = rf"(?:\s+{word}){{0,5}}?\s+\W?(?:an? )?(?:[\w-]+\.)*"
    in_list = rf"(?:\s+{word}){{0,2}}?\s+(?:{item})+(?:[^\s,;]+\s+){{0,2}}?(?:[\w-]+\.)*"
    neg = r"(?:\b(?:no|never|not|nor|without|nothing|none|cannot)\b|n't\b)"
    t = re.sub(rf"{neg}(?:{near_}|{in_list})(?:{term}){listed}", " ", t)
    return re.search(term, t) is not None


def live(clause: str, term: str) -> bool:
    """`term` asserted in `clause` once every negated mention is removed (a negation covers its
    own term within five words and a list coordinated after it; a double negation asserts; a
    falsity frame inverts what follows it)."""
    t = norm_text(unquote(clause))
    f = FLIP.search(t)
    if f:
        rest = t[f.end() :]
        return _live(t[: f.start()], term) or (
            re.search(term, rest) is not None and not _live(rest, term)
        )
    return _live(t, term)


SENTENCE = re.compile(r";\s|(?<=[.!?])\s+|(?<=[.!?]\*\*)\s+|\s—\s|:\s|\s·\s")


def sentences(text: str) -> list[str]:
    return [c for c in SENTENCE.split(strip_comments(text)) if c.strip()]


def clauses(text: str) -> list[str]:
    """A unit's clauses; a table row is read cell by cell with its lead cell as the subject."""
    if " | " not in QUOTED.sub("", text):
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


# sections whose rows describe others' texts or plant violations: never claims
NOT_CLAIMS = ("15.1 C-rows", "8.3 The never-list")
# table columns that are copy (A-row text) or labels, never claims: (section head, columns)
COPY_COLS = (
    ("15.3 §C", (2,)),
    ("16.2 The story-role", (2, 3, 4)),
    ("14. The open-questions", (1,)),
)


def lex_units(doc: str, text: str) -> list[LexUnit]:
    """Every prose line and table row of `text` (fences, headings and NOT_CLAIMS skipped; the
    COPY_COLS cells blanked)."""
    lines = text.split("\n")
    fence = fenced(lines)
    skip: set[int] = set()
    blank: dict[int, tuple[int, ...]] = {}
    for head in NOT_CLAIMS:
        body = section(text, head)
        if body:
            start = lines.index(body.split("\n")[0])
            skip |= set(range(start, start + body.count("\n") + 1))
    for head, cols in COPY_COLS:
        body = section(text, head)
        if body:
            start = lines.index(body.split("\n")[0])
            for k in range(start, start + body.count("\n") + 1):
                blank[k] = cols
    out: list[LexUnit] = []
    for i, ln in enumerate(lines):
        if fence[i] or i in skip or not ln.strip() or HEADING.match(ln) or is_rule(ln):
            continue
        t = ln
        if ln.lstrip().startswith("|") and i in blank:
            cells = split_row(ln)
            t = "| " + " | ".join("" if j in blank[i] else c for j, c in enumerate(cells)) + " |"
        out.append(LexUnit(doc, h2_at(text, i + 1), t.strip().strip("|").strip()))
    return out


@functools.lru_cache(maxsize=64)
def lex_cached(text: str) -> tuple[LexUnit, ...]:
    return tuple(lex_units("spec", text))


# a quoted label before its unit ("Disable two-factor" button) is read as words, not blanked
LABEL = re.compile(
    r'["“]([^"”\n]{1,40})["”](?=\s+(?:control|button|link|checkbox|check box|toggle|switch'
    r"|option|action|affordance|box|menu item)s?\b)"
)
UNLESS_WINDOW = 60  # characters either side of an asserted term an exemption may sit


def near_unless(scope: str, term: str, unless: str) -> bool:
    """An exemption counts only next to a term match (within UNLESS_WINDOW characters) and never
    inside a falsity frame's scope, so a cite or a far clause cannot exempt a claim."""
    flip = FLIP.search(scope)
    head = scope[: flip.start()] if flip else scope
    spans = [m.span() for m in re.finditer(term, scope)]
    return any(
        u.start() < b + UNLESS_WINDOW and a - UNLESS_WINDOW < u.end()
        for u in re.finditer(unless, head)
        for a, b in spans
    )


def claims(units: list[LexUnit], term: str, near: str = "", unless: str = "") -> list[str]:
    hits: list[str] = []
    for u in units:
        for c in clauses(u.text):
            c = LABEL.sub(r"\1", c)
            scope = norm_text(unquote(c))
            if near and not (re.search(near, scope) and live(c, near)):
                continue
            if unless and near_unless(scope, term, unless):
                continue
            if live(c, term):
                hits.append(f"{u.sec}: {norm_text(c)[:70]!r}")
    return hits


@dataclass(frozen=True)
class Texts:
    spec: str
    deck: str
    plans: tuple[tuple[str, str], ...]  # the working-tree untouched files (G-UNTOUCHED)
    values: tuple[tuple[str, str], ...]

    @property
    def vals(self) -> Values:
        return dict(self.values)


def F(tag: str, msg: str, doc: str | None, sec: str | None) -> Finding:
    return (tag, msg, doc, sec)


def spec_sec(t: Texts, head: str) -> str:
    return h2_of(t.spec, head)


def lexicon(
    tag: str, what: str, term: str, near: str = "", unless: str = ""
) -> Callable[[Texts], list[Finding]]:
    """No clause of the spec asserts `term` (naming `near`; never one naming `unless`)."""

    def run(t: Texts) -> list[Finding]:
        out: list[Finding] = []
        for u in lex_cached(t.spec):
            for h in claims([u], term, near=near, unless=unless):
                out.append(F(tag, f"{what}: {h}", "spec", u.sec))
        return out

    run.__doc__ = f"{tag}: no clause asserts {what}."
    run.__name__ = f"g_{tag[2:].lower()}"
    return run


# ---------------------------------------------------------------------------- tokens and colour


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


def theme_hex(theme: str, name: str) -> str:
    v = resolve(load_theme(theme), name)
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
        raise SystemExit(f"FAIL token {name} does not resolve to an opaque colour in {theme}")
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


# the CVD script's constants (CVD:49-92), copied so the simulation runs without executing it;
# G-CVD gates them against the script at the base
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
    """The constant tables of the CVD script, parsed as text (ast literals; nothing runs)."""
    if CVD_OVERRIDE:
        return CVD_OVERRIDE[-1]
    tree = ast.parse(at_base(CITE_FILES["CVD"]))
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
    """CVD's simulation (the same constants), or greyscale by relative luminance."""
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

RULED_HEAD = "The questions BQ-1..BQ-40"
STATUS_HEAD = "0. Status"
LOCKED_HEAD = "1.1 Locked inputs"
INDEX_HEAD = "2.1 The screen index"
FRAME_HEAD = "2.2 The frame register"
OPS_HEAD = "3.1 The operation set"
FIELDS_HEAD = "3.2 Rendered fields"
ERR_HEAD = "4.1 The conditions"
FALLBACK_HEAD = "4.2 The fallbacks"
COMP_HEAD = "6. The component"
REBIND_HEAD = "7.1 The re-binding table"
PAIRS_HEAD = "7.2 Contrast"
CVD_HEAD = "7.3 CVD"
DECK_HEAD = "8.1 The deck index"
FROZEN_HEAD = "8.2 The frozen set"
FOCUS_HEAD = "9.2 The interim focus"
AHEAD_HEAD = "13. The design-ahead"
QROW_HEAD = "14. The open-questions"
CROW_HEAD = "15.1 C-rows"
GROW_HEAD = "15.2 The G-ledger"
AROW_HEAD = "15.3 §C"
WALK_HEAD = "16.2 The story-role"
QA_HEAD = "16.3 The walkthrough"
VERSION_HEAD = "17. Versioning"
MUTATION_HEAD = "18. The mutation list"
PAIR_THEMES = ("dark", "light", "hc")
BARS = {"text": "bar.text", "non-text": "bar.ui"}


@functools.lru_cache(maxsize=8)
def deck_data(deck: str) -> dict[str, object]:
    try:
        data = json.loads(deck)
    except json.JSONDecodeError as exc:
        return {"_error": str(exc)}
    return data if isinstance(data, dict) else {"_error": "not an object"}


def deck_strings(deck: str) -> dict[str, dict[str, object]]:
    s = deck_data(deck).get("strings")
    if not isinstance(s, dict):
        return {}
    return {k: v for k, v in s.items() if isinstance(v, dict)}


def pair_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, PAIRS_HEAD) if re.match(r"P-\d+", r[0])]


def bars(values: Values) -> dict[str, float]:
    return {k: float(values.get(f"CITE:{v}", "0")) for k, v in BARS.items()}


def cite_values() -> Values:
    out: Values = {}
    for key, (cid, n, pat) in CITE_VALUES.items():
        m = re.search(pat, base_line(cid, n))
        if not m:
            raise SystemExit(f"FAIL parse: CITE:{key} not on {cid}:{n} ({pat})")
        out[f"CITE:{key}"] = m[1]
    return out


def contrast_values(spec: str) -> Values:
    out: Values = {}
    for r in pair_rows(spec):
        pid = r[0].split()[0].lower().replace("-", "")
        fg, bg = r[1].strip("`"), r[2].strip("`")
        for theme in PAIR_THEMES:
            try:
                out[f"CONTRAST:{pid}.{theme}"] = show_ratio(
                    contrast(theme_hex(theme, fg), theme_hex(theme, bg))
                )
            except SystemExit:
                out[f"CONTRAST:{pid}.{theme}"] = "unresolved"
    return out


def sprint_of(day: datetime.date) -> int:
    start = datetime.date.fromisoformat(cal_start())
    return (day - start).days // cal_days() + 1


@functools.lru_cache(maxsize=1)
def cal_start() -> str:
    m = re.search(r"SPRINT01_START = datetime\.date\((\d+), (\d+), (\d+)\)", at_base(cal_rel()))
    if not m:
        raise SystemExit("FAIL parse: CAL's SPRINT01_START")
    return f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}"


@functools.lru_cache(maxsize=1)
def cal_days() -> int:
    m = re.search(r"^SPRINT_DAYS = (\d+)", at_base(cal_rel()), MULTI)
    if not m:
        raise SystemExit("FAIL parse: CAL's SPRINT_DAYS")
    return int(m[1])


def cal_rel() -> str:
    return CITE_FILES["CAL"]


def ahead_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, AHEAD_HEAD) if len(r) == 5]


def sprint_values(spec: str) -> Values:
    out: Values = {}
    gap = int(cite_values()["CITE:ahead.sprints"])
    for r in ahead_rows(spec):
        if r[0].startswith("#4743") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[2]):
            n = sprint_of(datetime.date.fromisoformat(r[2])) + gap
            out["SPRINT:gate.4743"] = f"Sprint {n:02d}"
    return out


def count_values(spec: str, deck: str) -> Values:
    ops = [r for r in rows_of(spec, OPS_HEAD) if r[0].startswith("`")]
    fallbacks = re.findall(r"^- \*\*F-\d+\*\*", section(spec, FALLBACK_HEAD), MULTI)
    strings = deck_strings(deck)
    return {
        "COUNT:themes": str(len(THEMES)),
        "COUNT:ops": str(len(ops)),
        "COUNT:ops.ticket": str(sum(1 for r in ops if r[-1] == "yes")),
        "COUNT:ops.added": str(sum(1 for r in ops if r[-1] == "added")),
        "COUNT:fallbacks": str(len(fallbacks)),
        "COUNT:deck": str(len(strings)),
        "COUNT:deck.security": str(sum(1 for v in strings.values() if v.get("security"))),
    }


@functools.lru_cache(maxsize=16)
def compute_cached(spec: str, deck: str) -> tuple[tuple[str, str], ...]:
    """v1's values over the v1 view (its sections end where a v2 block begins) and v2's."""
    view = v1_view(spec)
    values: Values = {}
    values.update(RULED_VALUES)
    values.update(cite_values())
    values.update(count_values(view, deck))
    values.update(contrast_values(view))
    values.update(sprint_values(view))
    values.update(hash_values())
    values.update(v2_values(spec))
    return tuple(sorted(values.items()))


def compute(spec: str, deck: str) -> Values:
    return dict(compute_cached(spec, deck))


# ---------------------------------------------------------------------------- anchors and figures


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


# copy and label cells a figure check does not read: (section head, columns)
FIGURE_SKIP = (
    (WALK_HEAD, (2, 3, 4)),
    (AROW_HEAD, (2,)),
    (MUTATION_HEAD, (2,)),
    (AHEAD_HEAD, (2, 3)),
)


def blanked(text: str) -> dict[str, tuple[int, ...]]:
    out: dict[str, tuple[int, ...]] = {}
    for head, cols in FIGURE_SKIP:
        for ln in section(text, head).split("\n"):
            if ln.startswith("|") and not is_rule(ln):
                out[ln] = cols
    return out


def plain(line: str, values: Values, blank: dict[str, tuple[int, ...]]) -> str:
    """The line with anchored values, placeholders, quotes, code spans, cites, ids and dates cut,
    and the FIGURE_SKIP cells dropped."""
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
        r"\(#\d+\)|#\d+|\b\d{4}-\d{2}-\d{2}\b|\b[A-Z][A-Za-z0-9]*-\d+(?:\.\d+)?\b|\(\d+\)"
        r"|§\d+(?:\.\d+)*|\bv\d\b",
        " ",
        work,
    )
    return work


def g_anchor_doc(text: str, values: Values) -> list[Finding]:
    bad: list[Finding] = []
    blank = blanked(text)
    for i, line in enumerate(text.split("\n"), 1):
        sec = h2_at(text, i)
        for m in PLACEHOLDER.finditer(CODE.sub("", line)):
            bad.append(
                F("G-ANCHOR", f"spec:{i} placeholder {{{{{m[1]}}}}} not filled", "spec", sec)
            )
        spans = code_spans(line)
        for m in ANCHOR.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue
            want = values.get(m[1])
            pre = line[: m.start()]
            if want is None:
                bad.append(F("G-ANCHOR", f"spec:{i} {m[1]} is not a computed value", "spec", sec))
            elif not pre.endswith(want):
                got = re.split(r"[ |*(]", pre)[-1]
                msg = f"spec:{i} {m[1]} reads {got!r}; the tool computes {want!r}"
                bad.append(F("G-ANCHOR", msg, "spec", sec))
            elif re.search(r"[\w.,]$", pre[: len(pre) - len(want)]):
                msg = f"spec:{i} {m[1]}'s value has no left boundary"
                bad.append(F("G-ANCHOR", msg, "spec", sec))
        if line.startswith("#") and not ANCHOR.search(line) and not PLACEHOLDER.search(line):
            continue
        for m in FIGURE.finditer(plain(line, values, blank)):
            bad.append(F("G-ANCHOR", f"spec:{i} {m[0]!r} is a figure typed by hand", "spec", sec))
    return bad


def g_wordcount_doc(text: str, values: Values) -> list[Finding]:
    """A count is an anchored figure, never a word ("ten boards")."""
    bad: list[Finding] = []
    blank = blanked(text)
    for i, line in enumerate(text.split("\n"), 1):
        for m in WORDCOUNT.finditer(plain(line, values, blank)):
            msg = f"spec:{i} {m[0]!r} is a count written as a word"
            bad.append(F("G-WORDCOUNT", msg, "spec", h2_at(text, i)))
    return bad


def g_marker_doc(text: str, values: Values) -> list[Finding]:
    """Every HTML comment is a value anchor the tool computes."""
    bad: list[Finding] = []
    lines = text.split("\n")
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln) + 1)
    for m in COMMENT.finditer(text):
        i = next(k for k in range(len(starts) - 1) if starts[k] <= m.start() < starts[k + 1])
        col = m.start() - starts[i]
        if any(a <= col < b for a, b in code_spans(lines[i])):
            continue
        sec = h2_at(text, i + 1)
        am = ANCHOR.fullmatch(m[0])
        if not m[0].endswith(("-->", "--!>")) and m.end() == len(text):
            bad.append(
                F("G-MARKER", f"spec:{i + 1} an unclosed comment hides the rest", "spec", sec)
            )
        elif am is None or am[1] not in values:
            bad.append(F("G-MARKER", f"spec:{i + 1} a hidden comment {m[0][:40]!r}", "spec", sec))
    return bad


def g_hex_doc(text: str) -> list[Finding]:
    """A hex value stands only in §7.1's left column (E09-D06's literals, re-bound)."""
    bad: list[Finding] = []
    allowed = {split_row(ln)[0] for ln in section(text, REBIND_HEAD).split("\n") if "|" in ln}
    for i, line in enumerate(text.split("\n"), 1):
        work = CODE.sub(lambda c: " " * len(c[0]), line)
        lead = split_row(line)[0] if line.startswith("|") else None
        for m in HEXLIT.finditer(work):
            if lead is not None and lead == m[0] and lead in allowed:
                continue
            bad.append(
                F("G-HEX", f"spec:{i} {m[0]} outside §7.1's left column", "spec", h2_at(text, i))
            )
    return bad


# ---------------------------------------------------------------------------- generic gates


@functools.lru_cache(maxsize=1)
def head_resolves() -> bool:
    return bool(git_out("rev-parse", "--verify", "--quiet", f"{HEAD}^{{commit}}").strip())


def head_ok() -> bool:
    return "head" not in BROKEN and head_resolves()


CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#\d")


def g_close(t: Texts) -> list[Finding]:
    """BQ-3 (RULED): no closing keyword before an issue number anywhere in the pack."""
    bad: list[Finding] = []
    for i, line in enumerate(t.spec.split("\n"), 1):
        if CLOSING.search(norm_text(line)):
            bad.append(F("G-CLOSE", f"spec:{i} a closing keyword", "spec", h2_at(t.spec, i)))
    for key, e in deck_strings(t.deck).items():
        if CLOSING.search(norm_text(json.dumps(e, ensure_ascii=False))):
            bad.append(F("G-CLOSE", f"deck {key} a closing keyword", "deck", key))
    return bad


CHARSET_ALLOW = frozenset("…")
INVISIBLE = frozenset("\u00ad\u200b\u200c\u200d\u2060\ufeff\t")


def non_latin(c: str) -> bool:
    """A letter outside the Latin script (a homoglyph reads as a Latin word)."""
    return unicodedata.category(c).startswith("L") and "LATIN" not in unicodedata.name(c, "")


def charset_problems(line: str) -> list[str]:
    odd = [
        c
        for c in line
        if c in INVISIBLE or (c not in CHARSET_ALLOW and unicodedata.normalize("NFKC", c) != c)
    ]
    odd += [c for c in html.unescape(line) if non_latin(c)]
    whys = [f"U+{ord(c):04X}" for c in odd[:1]]
    whys += ["a CR"] if "\r" in line else []
    whys += ["trailing whitespace"] if line != line.rstrip() else []
    return whys


def g_charset(t: Texts) -> list[Finding]:
    """No compatibility or invisible character, tab, non-Latin letter, CR or trailing space."""
    bad: list[Finding] = []
    for i, line in enumerate(t.spec.split("\n"), 1):
        whys = charset_problems(line)
        if whys:
            bad.append(F("G-CHARSET", f"spec:{i} {', '.join(whys)}", "spec", h2_at(t.spec, i)))
    for key, e in deck_strings(t.deck).items():
        whys = charset_problems(json.dumps(e, ensure_ascii=False))
        if whys:
            bad.append(F("G-CHARSET", f"deck {key} {', '.join(whys)}", "deck", key))
    return bad


def g_cells(t: Texts) -> list[Finding]:
    """Every table row has its header's cell count, and every table its rule line."""
    bad: list[Finding] = []
    width, row = 0, 0
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if not re.match(r"^ {0,3}\|", ln):
            width, row = 0, 0
            continue
        row += 1
        if row == 2 and not is_rule(ln.strip()):
            bad.append(
                F("G-CELLS", f"spec:{i} no rule line under the header", "spec", h2_at(t.spec, i))
            )
        n = len(split_row(ln))
        if width == 0:
            width = n
        elif n != width:
            msg = f"spec:{i} {n} cells, its header has {width}"
            bad.append(F("G-CELLS", msg, "spec", h2_at(t.spec, i)))
    return bad


def g_comment(t: Texts) -> list[Finding]:
    """No `[//]: #` link-reference comment (it hides text from the renderer and the gates)."""
    return [
        F("G-COMMENT", f"spec:{i} a link-reference comment", "spec", h2_at(t.spec, i))
        for i, ln in enumerate(t.spec.split("\n"), 1)
        if re.match(r"^ {0,3}\[[^\]]*\]:\s*(?:#|<>|\S)", ln)
    ]


def g_penpot(t: Texts) -> list[Finding]:
    """Penpot by page name and page id by cite only: no URL, host, UUID or comment id beyond
    RULED_IDS (README:47-50)."""
    bad: list[Finding] = []
    for i, line in enumerate(t.spec.split("\n"), 1):
        sec = h2_at(t.spec, i)
        work = strip_comments(line)
        if URL.search(work) or UUID.search(work):
            bad.append(F("G-PENPOT", f"spec:{i} a URL, host or id", "spec", sec))
        for m in COMMENT_ID.finditer(CODE.sub(" ", CITE_GROUP.sub(" ", work))):
            if m[1] not in (*RULED_IDS, *RULED_IDS_V2):
                bad.append(F("G-PENPOT", f"spec:{i} an unlisted id {m[1]}", "spec", sec))
    raw = t.deck
    if URL.search(raw) or UUID.search(raw):
        bad.append(F("G-PENPOT", "the deck holds a URL, host or id", "deck", "(meta)"))
    return bad


def shannon(s: str) -> float:
    n = len(s)
    return -sum(s.count(c) / n * math.log2(s.count(c) / n) for c in set(s)) if n else 0.0


KEYISH = re.compile(
    r"(?i)[\w.-]*(?:key|token|secret|passw|auth|api|credential)[\w.-]*\"?\s*[:=,]\s*\"?"
    r"([^\s\"',;]{10,})"
)
CODE_SHAPE = re.compile(r"\b(?=[a-z]*\d)[a-z0-9]{5}-(?=[a-z]*\d)[a-z0-9]{5}\b")


def entropy_hits(text: str) -> list[str]:
    hits = [m[1] for m in KEYISH.finditer(text) if shannon(m[1]) > 3.5 and not m[1].startswith("{")]
    hits += [m[0] for m in CODE_SHAPE.finditer(text)]
    return hits


def g_entropy(t: Texts) -> list[Finding]:
    """No high-entropy `key: value` string and no recovery-code-shaped value in the pack (the
    secret scanners' shape; examples use `22`'s placeholders)."""
    bad: list[Finding] = []
    for i, line in enumerate(t.spec.split("\n"), 1):
        for h in entropy_hits(line):
            bad.append(F("G-ENTROPY", f"spec:{i} {h[:12]!r}…", "spec", h2_at(t.spec, i)))
    for key, e in deck_strings(t.deck).items():
        for h in entropy_hits(json.dumps({key: e}, ensure_ascii=False)):
            bad.append(F("G-ENTROPY", f"deck {key} {h[:12]!r}…", "deck", key))
    return bad


def g_budget(t: Texts) -> list[Finding]:
    """S-20: the spec stays a hand-off pack, within its line budget."""
    n = t.spec.count("\n") + (0 if t.spec.endswith("\n") else 1)
    if n > SPEC_LINE_BUDGET:
        last = h2_at(t.spec, len(t.spec.split("\n")))
        return [F("G-BUDGET", f"the spec has {n} lines > {SPEC_LINE_BUDGET}", "spec", last)]
    return []


def g_handref(t: Texts) -> list[Finding]:
    """S-20 (RULED): this pack has no `-handoff.md`; every `-handoff.md` it names exists at the
    base and is a parent's."""
    bad: list[Finding] = []
    for i, line in enumerate(t.spec.split("\n"), 1):
        for m in re.finditer(r"[\w/.-]*-handoff\.md", line):
            name = m[0] if not m[0].startswith("-") else f"E09{m[0]}"
            rel = name if name.startswith("docs/") else f"docs/design/E09/{name.split('/')[-1]}"
            if "E09-D12" in name or git_show(BASE, rel) is None:
                msg = f"spec:{i} {name} is not a parent's hand-off at the base"
                bad.append(F("G-HANDREF", msg, "spec", h2_at(t.spec, i)))
        if re.search(
            r"\bthis pack'?s? hand.?off file\b|\be09-d12 hand.?off\.md\b", norm_text(line)
        ):
            bad.append(F("G-HANDREF", f"spec:{i} names a hand-off file", "spec", h2_at(t.spec, i)))
    return bad


CMP_ID = re.compile(r"\bCMP-(\d{3})\b")


@functools.lru_cache(maxsize=1)
def catalogue_ids() -> dict[str, int]:
    out: dict[str, int] = {}
    for i, ln in enumerate(base_lines("15"), 1):
        m = re.match(r"^### (CMP-\d{3}) ", ln)
        if m:
            out[m[1]] = i
    return out


NEWCMP = (
    r"\b(?:new|added|adds|add|introduc\w*|propos\w*) (?:a )?(?:component|cmp id|cmp-\d+|"
    r"variant of cmp-\d+|catalogue entry)"
)
g_newcmp_lex = lexicon("G-NEWCMP", "a new component", NEWCMP, unless=r"\b#190\b")


def g_newcmp(t: Texts) -> list[Finding]:
    """No new component: every CMP id the pack names is a `15` entry at the base, and no clause
    adds one (#190 owns the band)."""
    bad = g_newcmp_lex(t)
    for i, line in enumerate(t.spec.split("\n"), 1):
        for m in CMP_ID.finditer(line):
            if f"CMP-{m[1]}" not in catalogue_ids():
                msg = f"spec:{i} CMP-{m[1]} is not a `15` entry"
                bad.append(F("G-NEWCMP", msg, "spec", h2_at(t.spec, i)))
    for key, e in deck_strings(t.deck).items():
        for m in CMP_ID.finditer(json.dumps(e)):
            if f"CMP-{m[1]}" not in catalogue_ids():
                bad.append(F("G-NEWCMP", f"deck {key} CMP-{m[1]} not in `15`", "deck", key))
    return bad


# ---------------------------------------------------------------------------- cites


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


def block_count(lines: list[str], block: list[str], stop: int = 2) -> int:
    n, first, hits = len(block), block[0], 0
    for i in range(len(lines) - n + 1):
        if lines[i] == first and lines[i : i + n] == block:
            hits += 1
            if hits >= stop:
                break
    return hits


def unique_block(base: list[str], a: int, b: int) -> list[str]:
    """The cited lines widened by context until the block is unique at the base."""
    lo, hi = a - 1, b
    while block_count(base, base[lo:hi]) > 1 and (lo > 0 or hi < len(base)):
        lo, hi = max(0, lo - 1), min(len(base), hi + 1)
    return base[lo:hi]


@functools.lru_cache(maxsize=2048)
def cited_block(rev: str, rel: str, a: int, b: int) -> tuple[str, ...]:
    return tuple(unique_block((git_show(rev, rel) or "").split("\n"), a, b))


def deck_cites(deck: str) -> list[tuple[str, str]]:
    """(deck key, source cell) for every deck entry."""
    return [(k, str(e.get("source", ""))) for k, e in deck_strings(deck).items()]


def drift_sha(rel: str, rev: str) -> str:
    """The latest commit after `rev` that touched `rel` on `origin/main` (a WARN names it)."""
    return git_out("log", "-1", "--format=%h", "--abbrev=10", f"{rev}..{HEAD}", "--", rel).strip()


def cite_findings(t: Texts) -> tuple[list[Finding], int]:
    """G-CITE (every line at its base, the range's ends non-blank) and G-VERSION (each cited
    range stands, by content, at `origin/main`; an unresolvable `origin/main` FAILs). A v1 line
    reads at `BASE`, a v2 line at `BASE_V2`; a v1 range edited at `origin/main` must be a §17.3
    row, and in post-merge mode an edit is a WARN naming the commit."""
    fails: list[Finding] = []
    done: set[tuple[str, str, int, int]] = set()
    post = post_merge()
    if not head_ok():
        fails.append(F("G-VERSION", f"{HEAD} does not resolve: drift is unread", None, None))
    v2 = v2_line_set(t.spec)
    registered = drift_registered(t.spec)
    drift_rows = {ln for ln in section(t.spec, DRIFT_HEAD).split("\n") if ln.startswith("| ")}
    sources: list[tuple[str, int, str, str, str]] = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        sec = h2_at(t.spec, i)
        if ln in drift_rows:  # §17.3: the first cell is v1's cite, the rest the v2 base's
            cells = split_row(ln)
            sources += [
                ("spec", i, cells[0], sec, BASE),
                ("spec", i, " | ".join(cells[1:]), sec, BASE_V2),
            ]
        else:
            sources.append(("spec", i, ln, sec, BASE_V2 if i in v2 else BASE))
    sources += [("deck", 0, src, key, BASE) for key, src in deck_cites(t.deck)]
    for doc, li, line, sec, rev in sources:
        for cid, a, b in cite_refs(line):
            rel = cite_path(cid)
            base_t = git_show(rev, rel) if rel else None
            where = f"{doc}:{li}" if li else f"deck {sec}"
            if rel is None or base_t is None:
                fails.append(F("G-CITE", f"{where} `{cid}`:{a} no such file", doc, sec))
                continue
            if (rev, cid, a, b) in done:
                continue
            done.add((rev, cid, a, b))
            base = base_t.split("\n")
            if b < a or a < 1 or b > len(base) or not base[a - 1].strip():
                fails.append(F("G-CITE", f"{where} `{cid}`:{a}–{b} not a range at {rev}", doc, sec))
                continue
            if not base[b - 1].strip():
                fails.append(F("G-CITE", f"{where} `{cid}`:{b} is blank at {rev}", doc, sec))
                continue
            if not head_ok():
                continue
            head_t = git_fetch_head(rel)
            if head_t is not None and block_count(
                head_t.split("\n"), list(cited_block(rev, rel, a, b)), 1
            ):
                continue
            if rev == BASE and (cid, a, b) in registered:
                continue
            msg = f"`{cid}`:{a}–{b} edited at {HEAD}"
            if post:
                warn(f"[G-VERSION] {msg} by {drift_sha(rel, rev) or 'a later commit'}")
            else:
                fails.append(F("G-VERSION", f"{msg}: re-read and re-point the cite", doc, sec))
    for rev, table in ((BASE, CITED), (BASE_V2, CITED_V2)):
        for cid, n, frag in table:
            base = base_lines(cid, rev)
            if n > len(base) or frag not in base[n - 1]:
                hits = [i + 1 for i, ln in enumerate(base) if frag in ln]
                msg = f'`{cid}`:{n} "{frag[:40]}" not on the line at {rev} (found {hits[:4]})'
                fails.append(F("G-CITE", msg, None, None))
    return fails, len(done) + len(CITED) + len(CITED_V2)


# ---------------------------------------------------------------------------- G-QUOTE

QUOTE_MIN = 12
CORE = ("14", "15", "22", "D03", "D04", "D05", "D06", "D09", "S03", "T")
# G-QUOTE skips the copy cells other gates own (the A-rows' text, the mutation rows)
QUOTE_SKIP = ((AROW_HEAD, (2,)), (MUTATION_HEAD, (2,)))


def loose(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("’", "'").replace("...", "…")
    s = re.sub(r"[*`_]", "", s)
    return " ".join(s.split()).lower().rstrip(".")


def template(s: str) -> str:
    parts = re.split(r"\{[^{}]*\}", s)
    return r"\S+(?: \S+){0,3}?".join(re.escape(p) for p in parts)


@functools.lru_cache(maxsize=512)
def source_text(cid: str, rev: str = "") -> str:
    if cid == "T":
        return loose(ticket().replace('\\"', '"'))
    rel = cite_path(cid)
    text = git_show(rev or BASE, rel) if rel else None
    return loose(text.replace('\\"', '"')) if text else ""


def quoted_ok(q: str, cids: list[str], deck_texts: list[str], rev: str = "") -> bool:
    """A quote of a v2 line (`rev` = BASE_V2) may also be v1's own text or R2's words."""
    lq = loose(q)
    if any(lq == loose(r) or lq in loose(r) for r in RULING_QUOTES):
        return True
    if any(lq == d or re.fullmatch(template(d), lq) for d in deck_texts):
        return True
    if rev == BASE_V2 and (lq in loose(v1_text()) or any(lq in loose(r) for r in R2_QUOTES)):
        return True
    v1_strings = [loose(str(e.get("string", ""))) for e in v1_deck().values()]
    if rev == BASE_V2 and lq in v1_strings:
        return True
    pat = re.compile(template(lq)) if "{" in lq else None
    for cid in [*cids, *CORE]:
        src = source_text(cid, rev)
        if lq in src or (pat is not None and pat.search(src)):
            return True
    return False


def g_quote(t: Texts) -> list[Finding]:
    """Every quoted string of QUOTE_MIN characters or more is verbatim in a source the line
    cites, a core source, the deck or R194's own words."""
    bad: list[Finding] = []
    deck_texts = [loose(str(e.get("string", ""))) for e in deck_strings(t.deck).values()]
    skip: dict[str, tuple[int, ...]] = {}
    for head, cols in QUOTE_SKIP:
        for ln in section(t.spec, head).split("\n"):
            if ln.startswith("|"):
                skip[ln] = cols
    v2 = v2_line_set(t.spec)
    for i, line in enumerate(t.spec.split("\n"), 1):
        rev = BASE_V2 if i in v2 else BASE
        work = line
        if line in skip:
            work = " | ".join(c for j, c in enumerate(split_row(line)) if j not in skip[line])
        cids = [c for c, _a, _b in cite_refs(work)]
        cids += re.findall(rf"\b({_BARE_IDS})\b", work)
        for m in QUOTED.finditer(CODE.sub(" ", strip_comments(work))):
            q = m[0][1:-1]
            if len(q) < QUOTE_MIN:
                continue
            if not quoted_ok(q, cids, deck_texts, rev):
                msg = f"spec:{i} {q[:50]!r} is not verbatim in a cited source"
                bad.append(F("G-QUOTE", msg, "spec", h2_at(t.spec, i)))
    return bad


# ---------------------------------------------------------------------------- untouched, version


@functools.lru_cache(maxsize=1)
def merge_base_sha() -> str:
    return git_out("merge-base", "HEAD", HEAD).strip()


def merge_base() -> str:
    return "" if "merge-base" in BROKEN else merge_base_sha()


def stray_paths_at(ref: str) -> tuple[str, ...] | None:
    """Paths changed against the merge-base (committed, staged, working tree or untracked) that
    are not this PR's own; None when a git call fails (the gate then FAILs closed)."""
    if not ref:
        return ()
    ok_diff, diff = git_ok("diff", "--name-only", ref)
    ok_new, new = git_ok("ls-files", "--others", "--exclude-standard")
    if not (ok_diff and ok_new):
        return None
    names = [*diff.split("\n"), *new.split("\n")]
    own = {*OWN_PATHS, cite_path("14") or ""}
    return tuple(sorted({n for n in names if n and n not in own}))


# BQ-40 (RULED as proposed): one content-only pointer line in `14` after the last design line of
# each band screen; nothing else in `14` changes (G-UNTOUCHED reads it by content)
# R2 BQ-07: the version-free form "(E09-D12)", once; the merge-base may still carry v1's form
POINTER_14 = "- **Hand-off pack:** [E09-D12.md](../design/E09/E09-D12.md) (E09-D12)."
POINTER_14_V1 = "- **Hand-off pack:** [E09-D12.md](../design/E09/E09-D12.md) (v1, E09-D12)."
POINTER_SCREENS = (
    "SCR-001",
    "SCR-002",
    "SCR-003",
    "SCR-004",
    "SCR-005",
    "SCR-006",
    "SCR-017",
    "SCR-019",
    "SCR-112",
)
DESIGN_LINE = re.compile(r"^- \*\*(?:Design|Hi-fi|Motion|Wireframes|Sign-off)\b")


def pointer_problems(text: str, base: str) -> list[str]:
    """`14` against the merge-base: equal once the pointer lines are dropped; one pointer in each
    band screen, right after its last design line (or that line's continuation); none elsewhere."""
    lines = text.split("\n")
    out: list[str] = []
    forms = (POINTER_14, POINTER_14_V1)
    if [ln for ln in lines if ln not in forms] != [
        ln for ln in base.split("\n") if ln not in forms
    ]:
        out.append("`14` differs from the merge-base beyond BQ-40's pointer lines")
    if POINTER_14_V1 in lines:
        out.append("`14` still carries v1's pointer form (R2 BQ-07)")
    heads = [(i, m[1]) for i, ln in enumerate(lines) if (m := re.match(r"^### (SCR-\d{3})\b", ln))]
    for k, (i, scr) in enumerate(heads):
        body = lines[i : heads[k + 1][0] if k + 1 < len(heads) else len(lines)]
        at = [j for j, ln in enumerate(body) if ln == POINTER_14]
        if scr not in POINTER_SCREENS:
            if at:
                out.append(f"`14` {scr} carries a pointer line")
            continue
        if len(at) != 1:
            out.append(f"`14` {scr} carries {len(at)} pointer lines, not one")
            continue
        prev = body[at[0] - 1]
        later = any(DESIGN_LINE.match(x) for x in body[at[0] + 1 :])
        if not (DESIGN_LINE.match(prev) or prev.startswith("  ")) or later:
            out.append(f"`14` {scr}'s pointer is not after its last design line")
    return out


def g_untouched(t: Texts) -> list[Finding]:
    """The standing rule: the untouched files equal the merge-base; only this PR's four files
    differ (committed or not), and `14` only by BQ-40's pointer lines; an unresolvable merge-base
    or a failed git call FAILs closed."""
    if post_merge():
        return []
    ref = merge_base()
    if not ref:
        return [F("G-UNTOUCHED", f"no merge-base with {HEAD}: nothing compared", None, None)]
    bad: list[Finding] = []
    override = dict(PLAN_OVERRIDE)
    for nn, text in t.plans:
        text = override.get(nn, text)
        rel = cite_path(nn)
        base = git_show(ref, rel) if rel else None
        if rel is None or base is None:
            bad.append(F("G-UNTOUCHED", f"`{nn}` is not readable at {ref[:10]}", None, None))
        elif nn == "14":
            bad += [F("G-UNTOUCHED", m, None, None) for m in pointer_problems(text, base)]
        elif text != base:
            bad.append(F("G-UNTOUCHED", f"`{nn}` differs from {ref[:10]}", None, None))
    strays = stray_paths_at(ref)
    if strays is None:
        return [*bad, F("G-UNTOUCHED", "a git call failed: no path compared", None, None)]
    bad += [
        F("G-UNTOUCHED", f"{p} is not this PR's path", None, None)
        for p in sorted({*strays, *EXTRA_PATHS})
    ]
    return bad


@functools.cache
def under_base(sha: str) -> bool:
    full = git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").strip()
    return bool(full) and git_out("merge-base", full, BASE).strip() == full


@functools.cache
def last_touch(cid: str) -> str:
    rel = cite_path(cid) or ""
    return git_out("log", "-1", "--format=%h", "--abbrev=10", BASE, "--", rel).strip()


def g_version(t: Texts) -> list[Finding]:
    """The version line's semantics: v1 at the base; every sha in order and under the base; each
    pinned doc at its last touch at the base; the named-only items named; the Inputs line names
    the base; §17 restates the version and the delta rule."""
    lines = t.spec.split("\n")
    i = next((n for n, ln in enumerate(lines) if ln.startswith("**Start.**")), None)
    if i is None:
        return [F("G-VERSION", "no **Start.** line", "spec", "(top)")]
    line, sec = lines[i], h2_at(t.spec, i + 1)
    bad: list[Finding] = []
    if f"**v1 at base `{BASE}`.**" not in line:
        bad.append(F("G-VERSION", "the version line does not name v1 at the base", "spec", sec))
    got = tuple(re.findall(r"`([0-9a-f]{10})`", line))
    if got != VERSION_SHAS:
        msg = f"the version line carries {len(got)} shas, not the {len(VERSION_SHAS)} in order"
        bad.append(F("G-VERSION", msg, "spec", sec))
    bad += [
        F("G-VERSION", f"`{s}` is not a commit under the base", "spec", sec)
        for s in got
        if not under_base(s)
    ]
    pinned = line.split("**Pinned at their last touch at the base:**", 1)[-1].split("**", 1)[0]
    for cid, sha in PINNED_DOCS.items():
        last = last_touch(cid)
        shown = cid if not cid.isdigit() else f"`{cid}`"
        if last != sha or shown not in pinned:
            bad.append(F("G-VERSION", f"{cid} pinned at {sha}, last touched {last}", "spec", sec))
    named = line.split("**Named only, never pinned or quoted:**", 1)[-1].split("**", 1)[0]
    bad += [
        F("G-VERSION", f"{n} is not in the named-only list", "spec", sec)
        for n in NAMED_ONLY
        if not re.search(rf"{re.escape(n)}\b", named)
    ]
    if "**Late changes:** none" not in line and "**Late changes:**" not in line:
        bad.append(F("G-VERSION", "the version line has no late-changes field", "spec", sec))
    inputs = next((ln for ln in lines if ln.startswith("**Inputs pinned.**")), "")
    if inputs.count(BASE) < 2:
        bad.append(F("G-VERSION", f"the Inputs line does not name the base {BASE}", "spec", sec))
    body = norm_text(section(t.spec, VERSION_HEAD))
    vsec = spec_sec(t, VERSION_HEAD)
    for need in (f"v1 at base {BASE}", "re-sync needed", "posted once on each affected consumer"):
        if norm_text(need) not in body:
            bad.append(F("G-VERSION", f"§17 lacks {need!r}", "spec", vsec))
    return bad


# ---------------------------------------------------------------------------- the ruling (R194)


def bullet(body: str, bq: str) -> str:
    """The RULED section's bullet that opens with `bq` (bold)."""
    for ln in body.split("\n"):
        if re.match(rf"^- \*\*{re.escape(bq)}(?!\w)", ln):
            return ln
    return ""


def g_ruled(t: Texts) -> list[Finding]:
    """R194 carried exactly: the heading names the ruling and the BQ list; the six ruled
    differently and the fifteen riders by id; each ruled-differently bullet holds its words."""
    sec = spec_sec(t, RULED_HEAD)
    body = section(t.spec, RULED_HEAD)
    bad: list[Finding] = []
    head = body.split("\n", 1)[0]
    if RULING_ID not in head or BQ_LIST_ID not in head:
        bad.append(F("G-RULED", "the heading does not name R194 and the BQ list", "spec", sec))
    lead = bullet(body, "Taken as proposed:")
    diff = lead.split("**Ruled differently:**", 1)[-1].split("**Riders**", 1)[0]
    if tuple(re.findall(r"\bBQ-\d+\b", diff)) != RULED_DIFFERENTLY:
        bad.append(F("G-RULED", "the ruled-differently list is not R194's", "spec", sec))
    riders = lead.split("**Riders**", 1)[-1]
    if tuple(re.findall(r"\bBQ-\d+\b", riders)) != RIDERS:
        bad.append(F("G-RULED", "the riders list is not R194's", "spec", sec))
    for bq, words in RULED_WORDS.items():
        text = loose(bullet(body, bq))
        for w in words:
            if loose(w) not in text:
                bad.append(F("G-RULED", f"{bq}'s bullet lacks {w!r}", "spec", sec))
    if "RULED (orchestrator, 2026-10-29, R194)" not in bullet(body, "BQ-11"):
        bad.append(F("G-RULED", "BQ-11 is not stamped RULED", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- the data contract


@functools.lru_cache(maxsize=1)
def openapi_ops() -> dict[str, tuple[str, str, int]]:
    """operationId -> (METHOD, path, the path line) read from `22` at the base."""
    out: dict[str, tuple[str, str, int]] = {}
    path, path_line, method = "", 0, ""
    for i, ln in enumerate(base_lines("22"), 1):
        m = re.match(r"^  (/[^:]*):\s*$", ln)
        if m:
            path, path_line = m[1], i
            continue
        m = re.match(r"^    (get|put|post|delete|patch):\s*$", ln)
        if m:
            method = m[1].upper()
            continue
        m = re.match(r"^      operationId: (\w+)\s*$", ln)
        if m and path:
            out[m[1]] = (method, path, path_line)
    return out


@functools.lru_cache(maxsize=1)
def ticket_ops() -> frozenset[tuple[str, str]]:
    m = re.search(r"mapped to the operation that supplies it \((.*?)\), with", ticket())
    if not m:
        raise SystemExit("FAIL parse: T Scope's operation list")
    out = set()
    for a, b in re.findall(r"`(GET|PUT|POST|DELETE) ([^`]+)`", m[1]):
        out.add((a, b.removeprefix("/api/v1")))
    return frozenset(out)


def op_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, OPS_HEAD) if r[0].startswith("`")]


def g_ops(t: Texts) -> list[Finding]:
    """§3.1 against `22`: each operation exists with its method, path and path line; the
    ticket column is exactly T Scope's list."""
    sec = spec_sec(t, OPS_HEAD)
    bad: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for r in op_rows(t.spec):
        op = r[0].strip("`")
        got = openapi_ops().get(op)
        mp = r[1].split(" ", 1)
        if got is None or len(mp) != 2:
            bad.append(F("G-OPS", f"{op} is not a `22` operation", "spec", sec))
            continue
        method, path = mp[0], mp[1].strip("`")
        if (method, path) != got[:2] or r[2] != f"`22`:{got[2]}":
            bad.append(F("G-OPS", f"{op} is {got[0]} {got[1]} at `22`:{got[2]}", "spec", sec))
        on_list = (method, path) in ticket_ops()
        seen.add((method, path))
        if r[-1] != ("yes" if on_list else "added"):
            bad.append(F("G-OPS", f"{op}'s ticket column reads {r[-1]!r}", "spec", sec))
    missing = sorted(f"{a} {b}" for a, b in ticket_ops() - seen)
    bad += [F("G-OPS", f"T Scope's {x} has no row", "spec", sec) for x in missing]
    return bad


BAND = ("SCR-001", "SCR-002", "SCR-003", "SCR-004", "SCR-005", "SCR-006", "SCR-017", "SCR-019")


def g_fields(t: Texts) -> list[Finding]:
    """AC1: every band screen has a field row; every operation a field names is in §3.1; every
    status is served, served (client), as D05, or a G-row that exists."""
    sec = spec_sec(t, FIELDS_HEAD)
    rows = rows_of(t.spec, FIELDS_HEAD)
    ops = {r[0].strip("`") for r in op_rows(t.spec)} | {"resetUserMfa"}
    ledger = g_ids(t.spec)
    bad: list[Finding] = []
    for scr in (*BAND, "SCR-112"):
        if not any(r[0].startswith(scr) for r in rows):
            bad.append(F("G-FIELDS", f"{scr} has no field row", "spec", sec))
    for r in rows:
        for name in re.findall(r"`([a-z][A-Za-z]+)`", r[1]):
            if name in openapi_ops() and name not in ops:
                bad.append(F("G-FIELDS", f"{r[0]} names {name}, not in §3.1", "spec", sec))
        status = r[-1]
        if not re.match(
            r"^(?:served(?: \(client\))?(?:; G-\d+)?|G-row \(G-\d+(?:, G-\d+)*\)(?:, held)?"
            r"|as D05)",
            status,
        ):
            bad.append(F("G-FIELDS", f"{r[0]}'s status {status!r} is not allowed", "spec", sec))
        for g in re.findall(r"\bG-(\d+)\b", status):
            if int(g) not in ledger and "D05" not in status:
                bad.append(F("G-FIELDS", f"{r[0]} names G-{g}, not in §15.2", "spec", sec))
        if "←" not in r[1]:
            bad.append(F("G-FIELDS", f"{r[0]} names no source (←)", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- the error map

T_CONDITIONS = (
    "invalid credentials",
    "disabled account",
    "rate limited",
    "invalid or replayed TOTP",
    "expired challenge",
    "invalid recovery code",
    "exhausted recovery codes",
    "reused / breached password",
    "step-up denied",
    "403 from RBAC",
)


@functools.lru_cache(maxsize=1)
def d09_keys() -> frozenset[str]:
    keys: set[str] = set()
    for ln in base_lines("D09")[251:282]:
        for k in re.findall(r"`([a-z0-9_.]+(?:\.\*)?)`", ln.split("|")[1] if "|" in ln else ""):
            keys.add(k)
        m = re.match(r"^\| `([a-z0-9_.]+)` / `\.(\w+)`", ln)
        if m:
            keys.add(f"{m[1]}.{m[2]}".replace(".h1.", "."))
    for k in list(keys):
        if "." in k:
            keys.add(k)
    return frozenset(keys)


def key_ok(key: str, deck: str) -> bool:
    k = key.strip("`")
    return k in deck_strings(deck) or k in d09_keys() or k.startswith(("D05 W-", "D09 §10"))


def g_errmap(t: Texts) -> list[Finding]:
    """AC2: each of T Scope's conditions once, one state and one string key; the credential
    failures share one state and one key, each later one with its fallback; every key exists."""
    sec = spec_sec(t, ERR_HEAD)
    rows = rows_of(t.spec, ERR_HEAD)
    by: dict[str, list[list[str]]] = {}
    for r in rows:
        by.setdefault(r[0], []).append(r)
    bad: list[Finding] = []
    for c in T_CONDITIONS:
        got = by.get(c, [])
        if len(got) != 1:
            bad.append(F("G-ERRMAP", f"{c!r} has {len(got)} rows", "spec", sec))
            continue
        r = got[0]
        if not r[2] or r[3] in ("", "—"):
            bad.append(F("G-ERRMAP", f"{c!r} lacks a state or a string", "spec", sec))
        elif not all(key_ok(k, t.deck) for k in re.findall(r"`[^`]+`", r[3]) or [r[3]]):
            bad.append(F("G-ERRMAP", f"{c!r}'s key {r[3]!r} is not in the deck", "spec", sec))
    first = by.get("invalid credentials", [[""] * 5])[0]
    for c in ("disabled account", "locked account (not listed)", "exhausted recovery codes"):
        r = by.get(c, [[""] * 5])[0]
        if c != "exhausted recovery codes" and (r[3] != first[3] or r[2] != "the same"):
            bad.append(F("G-ERRMAP", f"{c!r} is not the uniform failure", "spec", sec))
        if not re.fullmatch(r"F-\d+", r[4]):
            bad.append(F("G-ERRMAP", f"{c!r} shares a state without a fallback", "spec", sec))
    for r in rows:
        if "429" in r[1] and "Retry-After" not in r[1]:
            bad.append(F("G-ERRMAP", f"{r[0]!r}: a 429 without Retry-After", "spec", sec))
        if "Retry" in r[1] and "429" in r[1] and "aria-disabled" not in r[2]:
            bad.append(F("G-ERRMAP", f"{r[0]!r}: zero is not aria-disabled", "spec", sec))
    return bad


def fallbacks(spec: str) -> dict[str, str]:
    return dict(re.findall(r"^- \*\*(F-\d+)\*\* (.*)$", section(spec, FALLBACK_HEAD), MULTI))


def g_fallback(t: Texts) -> list[Finding]:
    """AC2: F-1..F-4 only, each with a reason that cites; every F used in §4.1 exists."""
    sec = spec_sec(t, FALLBACK_HEAD)
    fb = fallbacks(t.spec)
    bad: list[Finding] = []
    if list(fb) != ["F-1", "F-2", "F-3", "F-4"]:
        bad.append(F("G-FALLBACK", f"the fallbacks are {list(fb)}", "spec", sec))
    for k, v in fb.items():
        if not cite_refs(v) and "SR-" not in v:
            bad.append(F("G-FALLBACK", f"{k} cites no reason", "spec", sec))
    for r in rows_of(t.spec, ERR_HEAD):
        if re.fullmatch(r"F-\d+", r[-1]) and r[-1] not in fb:
            bad.append(F("G-FALLBACK", f"{r[0]!r} names {r[-1]}, not in §4.2", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- lexicon gates

SIGNIN = (
    r"(?:before sign.?in|before authenticat\w*|pre.?auth\w*|unauthenticated|scr.?001|login"
    r"|sign.?in (?:card|screen|page))"
)
g_badge = lexicon(
    "G-BADGE",
    "an environment shown before sign-in (RULED BQ-11)",
    r"(?:environment|env|server'?s?|demo|live)(?:[ /-]+\w+){0,2}?[ /-]*(?:badge|band|pill|chip|tag"
    r"|indicator|environment|ribbon|banner|marker|stripe|strip)"
    r"|(?:tells|shows|says|indicates|states|reveals)(?: \S+){0,6}? (?:demo or live|live or demo"
    r"|which environment)",
    near=SIGNIN,
    unless=r"begins at the shell|signed.?in screens?|after sign.?in|truthful or absent|dropped"
    r"|compiled bundle'?s environment is never",
)
g_footer = lexicon(
    "G-FOOTER",
    "more than the version label before sign-in (RULED BQ-10)",
    r"\b(?:commit|node name|build time|git sha|getbuildinfo|system/build|source revision|revision"
    r"|host(?:name)?|build date|build number)\b",
    near=r"\bfooter\b|before sign.?in|pre.?auth",
    unless=r"\bonly\b|after sign.?in|authenticated|no pre.?auth|none before sign.?in",
)
g_uniform = lexicon(
    "G-UNIFORM",
    "a distinct sign-in answer for a disabled, locked or unknown account (RULED BQ-12)",
    r"(?:disabled|locked|unknown)(?:[ -](?:account|user))?[ -](?:state|message|banner|string|frame"
    r"|variant|copy|screen|sentence|error|answer)s?|(?:told|informed|shown|warned)(?: \S+){0,4}?"
    r" (?:the )?(?:account|user) (?:is|was) (?:locked|disabled)",
    near=r"scr.?001|sign.?in|login|credential",
    unless=r"unreachable|not built|inference|f-1|uniform|the same|one failure|one sentence"
    r"|mid.?session|g-10",
)
g_countdown = lexicon(
    "G-COUNTDOWN",
    "a countdown not from Retry-After (RULED BQ-12)",
    r"\bcount(?:s|ing)? ?down\b|\bcountdown\b|\btimer\b|\bticks? (?:down|until)\b",
    near=r"\b(?:lock(?:out)?|fail(?:ure)?s?|attempts?|tally|client.?side|minutes?|min)\b",
    unless=r"retry.?after|only from|from 429|no figure|header|session|cmp.?098|warning|idle",
)
g_trust_b = lexicon(
    "G-TRUST",
    "a device-trust period or keep-signed-in control in v1 (RULED BQ-15)",
    r"\bday count\b|keep me signed in|remember me",
    unless=r"not in v1|no effect",
)
g_trust_a = lexicon(
    "G-TRUST",
    "a trust-this-device control in v1 (RULED BQ-15)",
    r"(?:trust(?:ed)?|remember)(?: this| the| a)? device|remember_device_days",
    near=r"\b(?:build|built|show\w*|render\w*|send|sent|sends|offer\w*|draw\w*|tick\w*|has"
    r"|carr(?:y|ies)|includ\w*|adds?|keeps?|ships?|posts?)\b",
    unless=r"not in v1|never sends|dropped|g-4|no trust|later device trust|must never skip"
    r"|no effect",
)
g_recovery = lexicon(
    "G-RECOVERY",
    "an in-product password recovery in v1 (RULED BQ-14)",
    r"forgot(?:ten)?(?: the| your| a)? password|password (?:reset|recovery)|reset(?:s)?"
    r"(?: the| your| a)? password|recover\w*(?: of)?(?: the| your| a)? password|self.?service"
    r" (?:reset|recovery)",
    near=r"\b(?:link|affordance|button|offer\w*|route|path|flow|email\w*|screen|page|in.?product"
    r"|gets?|shows?|sends?)\b",
    unless=r"no in.?product|no link|post.?v1|not in v1|g-9|must.?change|lever is disable",
)
g_disable_a = lexicon(
    "G-DISABLE",
    "a disable-two-factor control in v1 (RULED BQ-18)",
    r"disabl\w* (?:the )?(?:two.?factor|totp|2fa|mfa)|(?:turn|switch)\w* off (?:the )?"
    r"(?:two.?factor|totp|2fa|mfa)|switch\w* (?:the )?(?:two.?factor|totp|2fa|mfa) off",
    near=r"\b(?:control|button|action|offer\w*|build|built|show\w*|render\w*|draw\w*|step.?up"
    r"|typed|confirm\w*)\b",
    unless=r"no .{0,24}disable|not in v1|could only ever",
)
g_disable_b = lexicon(
    "G-DISABLE",
    "a step-up or typed phrase on removing a method (RULED BQ-18)",
    r"step.?up|typed (?:phrase|confirmation)|re.?prov\w*|fresh (?:totp )?code|second factor"
    r"|(?:totp|authenticator) code",
    near=r"\b(?:remove|removal|removing|delete|authmfadeletemethod|method)\b",
    unless=r"x.?reauth.?password[^.]*never|never d04|client.?side",
)
g_reason = lexicon(
    "G-REASON",
    "a server's free text rendered (RULED BQ-23)",
    r"(?:render\w*|show\w*|display\w*|print\w*)(?: \S+){0,3}? (?:(?:the )?(?:free.?text|raw"
    r"|server'?s?) (?:reason|detail|text|message)|reason raw|detail raw)|(?:free.?text|raw)"
    r" (?:reason|detail)s? (?:is |are )?(?:rendered|shown|displayed)"
    r"|(?:reason|detail)s? (?:is |are )?(?:rendered|shown|displayed|printed|surfaced)"
    r" (?:raw|verbatim|as (?:is|received|sent))",
)
g_invite = lexicon(
    "G-INVITE",
    "distinct invalid-invite states (RULED BQ-22)",
    r"(?:expired|already.?used|used|consumed|unknown)(?: invite| invitation| token)? (?:state"
    r"|message|string|screen|copy|variant|sentence)s?|(?:separate|distinct|different)"
    r" (?:invite|invitation) (?:states|messages|strings)|(?:gets?|has|have|with) (?:its|their) own"
    r" (?:wording|message|state|screen|copy|sentence|string|page)",
    near=r"invit|scr.?017|token",
    unless=r"one invalid|read alike|indistinguishable|the same|frozen",
)
g_exhaust = lexicon(
    "G-EXHAUST",
    "the recovery-code count or exhaustion built (RULED BQ-17)",
    r"n of 10|remaining (?:count|codes)|codes? remain\w*|exhaust\w*|low.?count warning"
    r"|how many (?:recovery )?codes|codes? (?:are )?(?:still )?unused|unused (?:recovery )?codes",
    near=r"\b(?:built|build|builds|show\w*|render\w*|display\w*|draw\w*)\b",
    unless=r"held|unsourced|unreachable|g-3|not built|re-enters|no remaining|none|f-3",
)
g_session = lexicon(
    "G-SESSION",
    "a session, walkthrough or participant claimed (S-19)",
    r"(?:walkthrough|session|interview|cold read|usability test)s? (?:was |were |is )?(?:held"
    r"|recorded|conducted|took place|completed)|participants? (?:said|reported|found|struggled"
    r"|noted)|(?:we|the owner) (?:held|ran|recorded) (?:a |the )?(?:walkthrough|session)"
    r"|(?:sat|went|walked) through (?:the |a )?(?:walkthrough|session|cold read)"
    r"|(?:found|reported|noted|saw) no gaps",
    unless=r"optional|for the owner|substitut|protocol|recorded \(",
)

g_confirm = lexicon(
    "G-CONFIRM",
    "a disabled Confirm on SCR-006 (RULED BQ-21)",
    r"confirm(?: button)? (?:is |stays |starts )?(?:disabled|greyed|inert|blocked|unavailable"
    r"|inactive)|disabled confirm|confirm (?:cannot|can't|can not) be (?:pressed|clicked|used"
    r"|activated|submitted)",
    near=r"scr.?006|step.?up|field|valid|dialog",
    unless=r"refused with focus",
)
g_attempts = lexicon(
    "G-ATTEMPTS",
    "an attempt count shown on SCR-001 or SCR-002 (RULED BQ-12, BQ-16)",
    r"(?:attempts?|tries|failures?) (?:left|remaining)"
    r"|(?:\w+) of (?:5|6|five|six) (?:attempts|tries)|attempt count(?:er)?"
    r"|how many (?:more )?(?:wrong |failed |bad )?(?:codes|attempts|tries|guesses)",
    near=r"scr.?00[12]|totp|second factor|sign.?in|login|show\w*|display\w*|render\w*|tell\w*"
    r"|warn\w*",
    unless=r"failures_remaining|step.?up|scr.?006",
)

g_grace = lexicon(
    "G-GRACE",
    "a grace for Live enablement or kill-switch disable (frozen (4), D06:47)",
    r"(?:recent|earlier|prior|valid|fresh) step.?up (?:\w+ ){0,2}?(?:covers|counts|applies"
    r"|is reused|suffices|carries over)|grace (?:\w+ ){0,3}?(?:live enablement|kill.?switch)",
    near=r"live enablement|kill.?switch",
)


def g_trace(t: Texts) -> list[Finding]:
    """BQ-40: a `US-AUTH-*` id is never a trace (`11` has none); only C-rows and A-rows name it."""
    bad: list[Finding] = []
    allowed = {ln for h in (CROW_HEAD, AROW_HEAD) for ln in section(t.spec, h).split("\n")}
    for i, line in enumerate(t.spec.split("\n"), 1):
        if "US-AUTH-" in line and line not in allowed:
            bad.append(F("G-TRACE", f"spec:{i} a US-AUTH-* trace", "spec", h2_at(t.spec, i)))
    return bad


# the ruled clauses that stand in bold (a bold dropped is a ruled clause demoted)
BOLD_CLAUSES = (
    "**v1 has no in-product password recovery**",
    '**"trust this device" is not in v1**',
    '**no "Disable two-factor" control in v1**',
    '**no "Disable two-factor" control in v1;**',
    "**no environment badge before sign-in**",
    "**No environment badge before sign-in**",
    "**No grace for Live enablement and kill-switch disable**",
    "**`reason` is never rendered raw**",
    "**One invalid-invite state**",
    "**Confirm is enabled;**",
    "**No trust-device control in v1:**",
    "**The lockout is that same state:**",
    "**Held, not built:**",
    "**The disabled and locked frames are unreachable by contract (SR-014):**",
    "**BQ-22 the invalid-invite sentence is RULED as proposed (frozen-set member)**",
    "**BQ-34 the recovery-code file format and filename are RULED as proposed**",
)


def g_shape(t: Texts) -> list[Finding]:
    """The spec's shape: a numbered section is `##`, a numbered subsection `###`; no line outside
    a fence is indented four spaces (it would render as code and drop out of the reading)."""
    lines = t.spec.split("\n")
    fence = fenced(lines)
    bad: list[Finding] = []
    for i, ln in enumerate(lines):
        if fence[i]:
            continue
        m = HEADING.match(ln)
        if m and re.match(r"\d+\.\d+ ", m[2]) and len(m[1]) != 3:
            bad.append(
                F("G-SHAPE", f"spec:{i + 1} a subsection is not ###", "spec", h2_at(t.spec, i + 1))
            )
        elif m and re.match(r"\d+\. ", m[2]) and len(m[1]) != 2:
            bad.append(
                F("G-SHAPE", f"spec:{i + 1} a section is not ##", "spec", h2_at(t.spec, i + 1))
            )
        if ln.startswith("    ") and ln.strip():
            bad.append(F("G-SHAPE", f"spec:{i + 1} indented as code", "spec", h2_at(t.spec, i + 1)))
    return bad


def g_bold(t: Texts) -> list[Finding]:
    """Every occurrence of a BOLD_CLAUSES clause stands inside bold (a reworded clause is
    G-RULED's or the pins')."""
    bad: list[Finding] = []
    for no, line in enumerate(t.spec.split("\n"), 1):
        for c in BOLD_CLAUSES:
            plain = c.strip("*")
            for m in re.finditer(re.escape(plain), line):
                if line[: m.start()].count("**") % 2 == 0:
                    sec = h2_at(t.spec, no)
                    bad.append(F("G-BOLD", f"spec:{no} {plain[:50]!r} is not in bold", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- frames, components


PNG = re.compile(r"`([\w+.-]+\.png)`")


def g_frame(t: Texts) -> list[Finding]:
    """Every PNG the pack names exists under `docs/design/E09/img/` at the base; SCR-004 reads
    "E09-D05 boards (PR 2) pending" (BQ-7) and SCR-112's sessions "no frame (L1-11)"."""
    sec = spec_sec(t, FRAME_HEAD)
    bad: list[Finding] = []
    for i, line in enumerate(t.spec.split("\n"), 1):
        for m in PNG.finditer(line):
            if not exists_at(BASE, f"docs/design/E09/img/{m[1]}"):
                msg = f"spec:{i} {m[1]} is not under img/ at the base"
                bad.append(F("G-FRAME", msg, "spec", h2_at(t.spec, i)))
    rows = {r[0]: r for r in rows_of(t.spec, FRAME_HEAD)}
    if "E09-D05 boards (PR 2) pending" not in rows.get("SCR-004", [""] * 5)[-1]:
        bad.append(F("G-FRAME", "SCR-004 does not read the boards pending", "spec", sec))
    if "no frame (L1-11)" not in rows.get("SCR-112", [""] * 5)[-1]:
        bad.append(F("G-FRAME", "SCR-112's sessions do not read no frame", "spec", sec))
    for scr in BAND:
        if scr not in rows:
            bad.append(F("G-FRAME", f"{scr} has no frame-register row", "spec", sec))
    for r in rows.values():
        if not re.search(r"\(D\d\d:\d+(?:–\d+)?\)", r[1]):
            bad.append(F("G-FRAME", f"{r[0]}'s page has no id by cite", "spec", sec))
    return bad


UNPUBLISHED = (
    "CMP-097",
    "CMP-200",
    "CMP-201",
    "CMP-202",
    "CMP-203",
    "CMP-204",
    "CMP-205",
    "CMP-206",
)


def storybook_of(cmp: str) -> str:
    n = catalogue_ids().get(cmp, 0)
    for ln in base_lines("15")[n : n + 12]:
        m = re.match(r"^- \*\*Storybook\*\*: (.*?)\.?$", ln)
        if m:
            return m[1]
    return ""


def g_comp(t: Texts) -> list[Finding]:
    """§6 against `15`: each id at its line; the Storybook cell is `15`'s required list (never
    "built"); the publication notes as R194's BQ-5 rider words them."""
    sec = spec_sec(t, COMP_HEAD)
    bad: list[Finding] = []
    body = section(t.spec, COMP_HEAD)
    preamble = body.split("\n|", 1)[0]
    for need in ("not published — #190 not started", "built in code (#4745), not published"):
        if need not in preamble:
            bad.append(F("G-COMP", f"§6 does not say {need!r}", "spec", sec))
    for r in table_rows(body):
        cmp = r[0].split()[0]
        line = catalogue_ids().get(cmp)
        if line is None or r[1] != f":{line}":
            bad.append(F("G-COMP", f"{cmp} is not at `15`{r[1]}", "spec", sec))
            continue
        name = base_line("15", line).removeprefix("### ")
        if r[0] not in (name, re.sub(r" \([^()]*\)$", "", name)):
            bad.append(F("G-COMP", f"{r[0]!r} is not `15`'s name {name!r} (BQ-28)", "spec", sec))
        sb = r[3]
        if "built" in sb.lower() or (sb != storybook_of(cmp) and sb != f"as `15`:{line}'s entry"):
            bad.append(F("G-COMP", f"{cmp}'s Storybook cell {sb!r} is not `15`'s", "spec", sec))
        if cmp in UNPUBLISHED and "not published — #190 not started" not in r[4]:
            bad.append(F("G-COMP", f"{cmp} is not marked unpublished", "spec", sec))
        if cmp == "CMP-098" and "built in code (#4745), not published" not in r[4]:
            bad.append(F("G-COMP", "CMP-098 is not marked built in code", "spec", sec))
    return bad


def g_status(t: Texts) -> list[Finding]:
    """BQ-5 (rider): the status table names each screen; unmounted routes say so; CMP-098 is
    built in code, not published."""
    sec = spec_sec(t, STATUS_HEAD)
    rows = rows_of(t.spec, STATUS_HEAD)
    bad: list[Finding] = []
    for scr in (*BAND, "SCR-112"):
        if not any(r[0].startswith(scr) for r in rows):
            bad.append(F("G-STATUS", f"{scr} has no status row", "spec", sec))
    for r in rows:
        if r[0].startswith("SCR-004") and "unmounted" not in r[2]:
            bad.append(F("G-STATUS", f"{r[0]}: the unmounted route is not said", "spec", sec))
        if r[0].startswith("SCR-003") and "renders no feature screen" not in r[2]:
            bad.append(F("G-STATUS", f"{r[0]}: the screenless route is not said", "spec", sec))
        if r[0].startswith("SCR-005") and "built in code (#4745), not published" not in r[1]:
            bad.append(F("G-STATUS", "CMP-098 is not marked built in code", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- tokens, contrast

TOKEN_NAME = re.compile(r"`(color\.[a-z0-9.-]+)`")
NOT_SHIPPED = frozenset({"color.text.muted", "color.surface.base", "color.surface.scrim"})


def g_tokens(t: Texts) -> list[Finding]:
    """BQ-29: every token name is shipped, or a parent's unshipped name the line says is not
    shipped; §7.1's right column resolves in every theme (but the scrim, D08's PROPOSED name)."""
    bad: list[Finding] = []
    for i, line in enumerate(t.spec.split("\n"), 1):
        for m in TOKEN_NAME.finditer(line):
            name = m[1]
            if name in all_token_names():
                continue
            if name not in NOT_SHIPPED or "not shipped" not in line.lower():
                msg = f"spec:{i} {name} is not a shipped token"
                bad.append(F("G-TOKENS", msg, "spec", h2_at(t.spec, i)))
    sec = spec_sec(t, REBIND_HEAD)
    for r in rows_of(t.spec, REBIND_HEAD):
        if not re.fullmatch(r"#[0-9a-f]{6}", r[0]):
            bad.append(F("G-TOKENS", f"§7.1 {r[0]!r} is not a lower-case literal", "spec", sec))
        name = r[2].split("`")[1] if "`" in r[2] else ""
        if name in NOT_SHIPPED:
            continue
        for theme in PAIR_THEMES:
            try:
                theme_hex(theme, name)
            except SystemExit:
                bad.append(F("G-TOKENS", f"§7.1 {name} unresolved in {theme}", "spec", sec))
    return bad


def below_bar(values: Values, spec: str) -> list[str]:
    out = []
    b = bars(values)
    for r in pair_rows(spec):
        pid = r[0].split()[0]
        for theme in PAIR_THEMES:
            v = values.get(f"CONTRAST:{pid.lower().replace('-', '')}.{theme}", "0:1")
            if v == "unresolved" or float(v.split(":")[0]) < b.get(r[-1], b["text"]):
                out.append(f"{pid} in {theme}")
    return out


def g_contrast(t: Texts) -> list[Finding]:
    """Every pair resolves in each theme; a pair below its bar is named in §7.2's below-the-bar
    sentence and routed to a Q-row there; nothing else is named."""
    sec = spec_sec(t, PAIRS_HEAD)
    body = section(t.spec, PAIRS_HEAD)
    named = re.findall(r"\b(P-\d+ in (?:dark|light|hc))\b", body.split("**Below the bar", 1)[-1])
    got = below_bar(t.vals, t.spec)
    bad: list[Finding] = []
    if sorted(set(named)) != sorted(got):
        bad.append(F("G-CONTRAST", f"below the bar {got}, named {named}", "spec", sec))
    if got and not re.search(r"routed as Q-\d+", body):
        bad.append(F("G-CONTRAST", "the shortfall is not routed to a Q-row", "spec", sec))
    if len(pair_rows(t.spec)) < 1:
        bad.append(F("G-CONTRAST", "no pairs", "spec", sec))
    return bad


def cvd_below(values: Values, spec: str) -> list[str]:
    out = []
    b = bars(values)
    for r in pair_rows(spec):
        pid, fg, bg = r[0].split()[0], r[1].strip("`"), r[2].strip("`")
        for theme in PAIR_THEMES:
            try:
                a, c = theme_hex(theme, fg), theme_hex(theme, bg)
            except SystemExit:
                continue
            base_ok = contrast(a, c) >= b.get(r[-1], b["text"])
            for kind in DEFICIENCIES:
                if base_ok and contrast(simulate(a, kind), simulate(c, kind)) < b.get(r[-1], 0):
                    out.append(f"{pid} {theme} {kind}")
    return out


def g_cvd(t: Texts) -> list[Finding]:
    """The CVD constants equal CVD's at the base; every pair that meets its bar keeps it under
    each simulation and in greyscale, or is named in §7.3."""
    sec = spec_sec(t, CVD_HEAD)
    bad: list[Finding] = []
    base = cvd_constants_at_base()
    for k, v in own_cvd_constants().items():
        if base.get(k) != v:
            bad.append(F("G-CVD", f"the tool's {k} differs from CVD at the base", None, None))
    body = section(t.spec, CVD_HEAD)
    named = re.findall(
        r"\b(P-\d+ (?:dark|light|hc) (?:protanopia|deuteranopia|tritanopia|greyscale))", body
    )
    got = cvd_below(t.vals, t.spec)
    if sorted(set(named)) != sorted(got):
        bad.append(F("G-CVD", f"below the bar under CVD {got}, named {named}", "spec", sec))
    if "no state rests on hue" not in body:
        bad.append(F("G-CVD", "§7.3 lacks the carrier sentence", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- the deck

PROVENANCE = ("verbatim", "14", "as shipped", "new PROPOSED", "RULED")
SCREENS = (*BAND, "SCR-112", "CMP-098")
DECK_FIELDS = ("string", "screen", "state", "provenance", "source", "status")


def source_holds(source: str, string: str) -> bool:
    refs = cite_refs(source)
    if len(refs) != 1:
        return False
    cid, a, b = refs[0]
    lines = base_lines(cid)
    if not lines or b > len(lines):
        return False
    raw = " ".join(lines[a - 1 : b]).replace('\\"', '"')
    text = loose(raw)
    s = loose(string)
    return (
        s in text
        or quoted_pieces(raw, string)
        or (
            ("{" in s or "N " in string or "m:ss" in s)
            and bool(re.search(template(s).replace("n\\ ", r"\S+\ "), text))
        )
    )


def g_deck(t: Texts) -> list[Finding]:
    """BQ-26: the deck's shape; every entry's provenance re-read at its cited line; a new string
    PROPOSED with its Q-row; a security entry names its row and what breaks."""
    data = deck_data(t.deck)
    if "_error" in data:
        return [F("G-DECK", f"the deck is not JSON: {data['_error']}", "deck", "(meta)")]
    bad: list[Finding] = []
    for k in ("pack", "version", "base", "header", "by_cite", "strings"):
        if k not in data:
            bad.append(F("G-DECK", f"the deck lacks {k!r}", "deck", "(meta)"))
    qids = {r[0] for r in rows_of(t.spec, QROW_HEAD)}
    for key, e in deck_strings(t.deck).items():
        where = ("deck", key)
        if not re.fullmatch(r"[a-z0-9_]+(?:\.[a-z0-9_]+)+", key):
            bad.append(F("G-DECK", f"{key} is not a dotted key", *where))
        if any(not isinstance(e.get(f), str) or not e.get(f) for f in DECK_FIELDS):
            bad.append(F("G-DECK", f"{key} lacks a field", *where))
            continue
        prov, src, st = str(e["provenance"]), str(e["source"]), str(e["status"])
        if prov not in PROVENANCE or str(e["screen"]) not in SCREENS:
            bad.append(F("G-DECK", f"{key} provenance or screen not allowed", *where))
        elif prov in ("verbatim", "14", "as shipped") and not source_holds(src, str(e["string"])):
            bad.append(F("G-DECK", f"{key} is not at {src}", *where))
        elif prov == "14" and not src.startswith("`14`"):
            bad.append(F("G-DECK", f"{key} reads 14 from {src}", *where))
        elif prov == "new PROPOSED" and (
            st != "PROPOSED" or not any(q in src for q in qids) or not re.search(r"Q-\d+", src)
        ):
            bad.append(F("G-DECK", f"{key} is new without PROPOSED and its Q-row", *where))
        elif prov == "RULED" and ("R194" not in src or st != "RULED"):
            bad.append(F("G-DECK", f"{key} is RULED without R194", *where))
        sec_cell = e.get("security")
        if sec_cell is not None and (
            not isinstance(sec_cell, str)
            or not re.search(r"frozen \(\d+\)|F-\d+", sec_cell)
            or not str(e.get("breaks", "")).strip()
        ):
            bad.append(F("G-DECK", f"{key} security without its row or what breaks", *where))
    by = data.get("by_cite")
    if not isinstance(by, dict) or not all(cite_refs(str(v)) for v in by.values()):
        bad.append(F("G-DECK", "by_cite holds an uncited entry", "deck", "(meta)"))
    sources = {str(e.get("source", "")) for e in deck_strings(t.deck).values()}
    s03 = base_lines("S03")
    for n in s03_rows("### 4.2"):
        keyed = re.findall(r"`([a-z0-9_.]+)`", s03[n - 1].split("|")[1])
        if f"S03:{n}" not in sources and not any(k in deck_strings(t.deck) for k in keyed):
            bad.append(F("G-DECK", f"S03:{n} (§4.2) has no deck entry (BQ-26)", "deck", "(meta)"))
    for key in HELD_G12:
        st = str(deck_strings(t.deck).get(key, {}).get("status", ""))
        if st != "held (G-12)":
            bad.append(F("G-DECK", f"{key} is {st!r}, not held (G-12)", "deck", key))
    return bad


# the re-enrol entries no operation serves at the base (`22`:1295–1296; lens 3 M-2)
HELD_G12 = ("twofactor.reenrol", "enrol.reenrol.banner")


@functools.lru_cache(maxsize=4)
def s03_rows(head: str) -> tuple[int, ...]:
    """The line numbers of S03's table rows under `head` (to the next heading), at the base."""
    lines = base_lines("S03")
    start = next((i for i, ln in enumerate(lines) if ln.startswith(head + " ")), None)
    if start is None:
        return ()
    out: list[int] = []
    for i in range(start + 1, len(lines)):
        if HEADING.match(lines[i]):
            break
        if lines[i].startswith("|") and not is_rule(lines[i]) and not lines[i].startswith("| Key"):
            out.append(i + 1)
    return tuple(out)


@functools.lru_cache(maxsize=1)
def merged_keys() -> frozenset[str]:
    """The keys the merged parents define: S03 §4's tables and D09 §10."""
    keys: set[str] = set(d09_keys())
    lines = base_lines("S03")
    for n in (*s03_rows("### 4.1"), *s03_rows("### 4.2")):
        keys |= set(re.findall(r"`([a-z0-9_.]+)`", lines[n - 1].split("|")[1]))
    return frozenset(keys)


def g_deckkey(t: Texts) -> list[Finding]:
    """BQ-26 (RULED as proposed): a key reuses a merged one (S03 §4, D09 §10) or is coined here
    with `key_status: PROPOSED`; a coined key's namespace is BQ-26's or one §8.1 records."""
    sec = spec_sec(t, DECK_HEAD)
    body = section(t.spec, DECK_HEAD)
    named = set(re.findall(r"`([a-z]+)\.\*`", body)) | {k.split(".")[0] for k in merged_keys()}
    bad: list[Finding] = []
    if "key_status: PROPOSED" not in body:
        bad.append(F("G-DECKKEY", "§8.1 does not say coined keys are PROPOSED", "spec", sec))
    for key, e in deck_strings(t.deck).items():
        ks = e.get("key_status")
        if ks not in ("merged", "PROPOSED"):
            bad.append(F("G-DECKKEY", f"{key} has no key_status", "deck", key))
        elif (ks == "merged") != (key in merged_keys()):
            bad.append(F("G-DECKKEY", f"{key}'s key_status {ks!r} is wrong", "deck", key))
        elif ks == "PROPOSED" and key.split(".")[0] not in named:
            bad.append(F("G-DECKKEY", f"{key}: namespace not recorded in §8.1", "spec", sec))
    return bad


# each frozen row's load-bearing words (norm_text), and each hook's security property
FROZEN_CELLS: dict[str, tuple[str, ...]] = {
    "(1)": ("one failure string", "no enumeration"),
    "(2)": ("identical to an unknown route", "existence hidden"),
    "(3)": ("shown once", "display exactly once"),
    "(4)": ("no grace for live enablement", "unconditional step up"),
    "(5)": ("presentation, never enforcement", "rbac server side"),
    "(6)": ("no order sent after expiry",),
    "(7)": ("does not say which", "no token oracle"),
    "(8)": ("no trust device control in v1", "totp never skipped"),
    "(9)": ("revoked knowingly",),
    "(10)": ("never list", "no password leak"),
}
FROZEN_DECK: dict[str, str] = {
    "auth.login.failed": "no enumeration",
    "enrol.codes.ack": "the acknowledgement gate",
    "enrol.codes.once": "displayed exactly once",
    "invite.invalid": "no token oracle",
    "lock.expired.badge": "nothing sent after expiry",
    "lock.expired.body": "nothing sent after expiry",
    "sessions.revoke.self": "revoked knowingly",
}
# §8.3's never-list, item by item (NOT_CLAIMS keeps it out of the lexicons, so it is read here)
NEVER_ITEMS = (
    "never rendered or written",
    "a server detail or free text reason raw",
    "any password, code, recovery code or token",
    "whether an account exists, is disabled or is locked",
    "how many attempts are left before a lock",
    "a minute scale countdown figure in copy",
    "the remaining count of recovery codes",
)


def g_never(t: Texts) -> list[Finding]:
    """§8.3: the never-list holds every item (BQ-23, BQ-26; SR-014)."""
    text = norm_text(section(t.spec, "8.3 The never-list"))
    sec = spec_sec(t, "8.3 The never-list")
    return [F("G-NEVER", f"§8.3 lacks {n!r}", "spec", sec) for n in NEVER_ITEMS if n not in text]


def frozen_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, FROZEN_HEAD) if re.fullmatch(r"\(\d+\)", r[0])]


def g_frozen(t: Texts) -> list[Finding]:
    """AC6 and BQ-27: rows (1)..(10) in order, each with its property, what breaks and a hook
    that exists; a deck entry flagged frozen (n) is row n's hook, and row n's hook carries it."""
    sec = spec_sec(t, FROZEN_HEAD)
    rows = frozen_rows(t.spec)
    bad: list[Finding] = []
    if [r[0] for r in rows] != [f"({n})" for n in range(1, 11)]:
        bad.append(F("G-FROZEN", "the frozen set is not rows (1)..(10)", "spec", sec))
    deck = deck_strings(t.deck)
    hooks: dict[str, str] = {}
    for r in rows:
        if not (r[2] and r[3]):
            bad.append(F("G-FROZEN", f"{r[0]} lacks its property or what breaks", "spec", sec))
        hook = r[4]
        keys = re.findall(r"`([a-z0-9_.]+)`", hook)
        ok = hook == "behaviour, no string" or hook.startswith("D05 W-")
        ok = ok or (bool(keys) and all(k in deck or k in d09_keys() for k in keys))
        if not ok:
            bad.append(F("G-FROZEN", f"{r[0]}'s hook {hook!r} does not exist", "spec", sec))
        for k in keys:
            hooks[k] = r[0]
    for key, e in deck.items():
        m = re.search(r"frozen (\(\d+\))", str(e.get("security") or ""))
        if m and not any(rr[0] == m[1] for rr in rows):
            bad.append(F("G-FROZEN", f"deck {key} names {m[1]}, not a row", "deck", key))
    for k, n in hooks.items():
        entry = deck.get(k)
        if entry is not None and f"frozen {n}" not in str(entry.get("security") or ""):
            bad.append(F("G-FROZEN", f"{n}'s hook {k} is not flagged frozen {n}", "deck", k))
    words = {r[0]: norm_text(" ".join(r[1:])) for r in rows}
    if "no trust device control in v1" not in words.get("(8)", ""):
        bad.append(F("G-FROZEN", "(8) does not read no trust-device control in v1", "spec", sec))
    if "ruled bq 22" not in words.get("(7)", ""):
        bad.append(F("G-FROZEN", "(7) is not the RULED invalid-invite sentence", "spec", sec))
    for n, phrases in FROZEN_CELLS.items():
        for ph in phrases:
            if ph not in words.get(n, ""):
                bad.append(F("G-FROZEN", f"{n} lacks {ph!r}", "spec", sec))
    for k, ph in FROZEN_DECK.items():
        if ph not in norm_text(str(deck.get(k, {}).get("security") or "")):
            bad.append(F("G-FROZEN", f"deck {k}'s security lacks {ph!r}", "deck", k))
    inv = deck.get("invite.invalid", {})
    if inv.get("string") != "This invitation is no longer valid. Ask the owner for a new one.":
        bad.append(F("G-FROZEN", "invite.invalid is not R194's sentence", "deck", "invite.invalid"))
    return bad


# ---------------------------------------------------------------------------- rows

AGENT = re.compile(r"(?i)\b(?:agent|worker|hcl-|hpe-|claude|orchestrator lane|the lane)\b")
CARRIED = r"(?:D05|D08|D09|S03|#188|E09-D05)(?:'s)?(?:\s+\S+){0,2}?\s"


def g_ids(spec: str) -> set[int]:
    return {int(r[0][2:]) for r in rows_of(spec, GROW_HEAD) if re.fullmatch(r"G-\d+", r[0])}


def own_refs(spec: str, prefix: str) -> dict[int, int]:
    """Every `<prefix>-n` the spec uses as its own id, with the first line using it: a match
    whose clause (back to the last `;`, `(` or sentence start) names a parent (D05, D08, D09,
    S03, #188) is the parent's."""
    out: dict[int, int] = {}
    for no, line in enumerate(spec.split("\n"), 1):
        for m in re.finditer(rf"(?<![\w'-]){prefix}-(\d+)\b", line):
            clause = re.split(r"[;(]|\.\s|\|", line[: m.start()])[-1]
            if re.search(r"\b(?:D05H?|D08|D09|S03|E09-D05)\b|#188", clause):
                continue
            out.setdefault(int(m[1]), no)
    return out


def seq_rows(t: Texts, head: str, prefix: str, tag: str) -> list[Finding]:
    sec = spec_sec(t, head)
    rows = [r for r in rows_of(t.spec, head) if re.fullmatch(rf"{prefix}-\d+", r[0])]
    ids = [int(r[0].split("-")[1]) for r in rows]
    bad: list[Finding] = []
    if ids != sorted(set(ids)):
        bad.append(F(tag, f"the {prefix}-rows are not in order or repeat", "spec", sec))
    for r in rows:
        if any(not c for c in r[1:]):
            bad.append(F(tag, f"{r[0]} has an empty cell", "spec", sec))
        if AGENT.search(" ".join(r[1:])):
            bad.append(F(tag, f"{r[0]} names an agent", "spec", sec))
    used = own_refs(t.spec, prefix)
    for n in sorted(set(used) - set(ids)):
        where = h2_at(t.spec, used[n])
        bad.append(F(tag, f"{prefix}-{n} is used but not defined (line {used[n]})", "spec", where))
    return bad


def g_crows(t: Texts) -> list[Finding]:
    """Every C-row read; every C-n used is defined."""
    bad = seq_rows(t, CROW_HEAD, "C", "G-CROWS")
    ids = [r[0] for r in rows_of(t.spec, CROW_HEAD)]
    if ids != [f"C-{n}" for n in range(1, len(ids) + 1)]:
        bad.append(F("G-CROWS", "the C-rows are not C-1..C-n", "spec", spec_sec(t, CROW_HEAD)))
    return bad


# G-rows past R194's ledger (G-1..G-10): G-11 and G-12 acknowledged (D7, ruled 14:24Z) and G-13
# (round 1 P-2); each is a plain G-row, and the old acknowledgement marker is stale
NEW_GROW = "new, for the orchestrator's acknowledgement"
ACKED_GROWS = (11, 12, 13)


def g_grows(t: Texts) -> list[Finding]:
    """S-6 / S-16: G-rows owned by tickets or spec owners (never an agent), due at once; G-5 and
    G-8 kept free; the parents' rows carried by id."""
    sec = spec_sec(t, GROW_HEAD)
    bad = seq_rows(t, GROW_HEAD, "G", "G-GROWS")
    for r in rows_of(t.spec, GROW_HEAD):
        if r[-1] != "at once":
            bad.append(F("G-GROWS", f"{r[0]} is not due at once", "spec", sec))
    ids = g_ids(t.spec)
    for r in rows_of(t.spec, GROW_HEAD):
        if NEW_GROW in r[1]:
            bad.append(F("G-GROWS", f"{r[0]} keeps the stale acknowledgement marker", "spec", sec))
    if ids - {1, 2, 3, 4, 6, 7, 9, 10, *ACKED_GROWS}:
        bad.append(F("G-GROWS", f"{sorted(ids)} has a row not acknowledged", "spec", sec))
    if ids & {5, 8} or not {1, 2, 3, 4, 6, 7, 9, 10, *ACKED_GROWS} <= ids:
        bad.append(F("G-GROWS", f"the ledger's ids are {sorted(ids)}", "spec", sec))
    body = section(t.spec, GROW_HEAD)
    for need in ("D05:565–574", "D08:433–434", "D09:463–472", "S03:195–196"):
        if need not in body:
            bad.append(F("G-GROWS", f"the carried rows lack {need}", "spec", sec))
    g1 = next((r for r in rows_of(t.spec, GROW_HEAD) if r[0] == "G-1"), [""] * 5)
    if "environment" in norm_text(g1[1]):
        bad.append(F("G-GROWS", "G-1 keeps its environment half (R194 BQ-11)", "spec", sec))
    return bad


def g_qrows(t: Texts) -> list[Finding]:
    """S-13: one log; each row a default, an owner lane (never an agent), due at once; the OWNER
    items BQ-11 / 14 / 15 RULED."""
    sec = spec_sec(t, QROW_HEAD)
    bad = seq_rows(t, QROW_HEAD, "Q", "G-QROWS")
    rows = {r[0]: r for r in rows_of(t.spec, QROW_HEAD)}
    for r in rows.values():
        if r[-1] != "at once":
            bad.append(F("G-QROWS", f"{r[0]} is not due at once", "spec", sec))
    for q, bq in (("Q-1", "BQ-11"), ("Q-2", "BQ-14"), ("Q-3", "BQ-15")):
        r = rows.get(q, [""] * 5)
        if bq not in r[1] or "RULED" not in r[2]:
            bad.append(F("G-QROWS", f"{q} is not {bq} RULED", "spec", sec))
    return bad


def g_arows(t: Texts) -> list[Finding]:
    """S-15: the A-rows are copy-ready, owned and never applied here."""
    sec = spec_sec(t, AROW_HEAD)
    bad = seq_rows(t, AROW_HEAD, "A", "G-AROWS")
    targets = " ".join(r[1] for r in rows_of(t.spec, AROW_HEAD))
    for need in ("`14` SCR-001 Layout", "`05`", "`15` CMP-207"):
        if need not in targets:
            bad.append(F("G-AROWS", f"no A-row targets {need}", "spec", sec))
    if "Hand-off pack" in section(t.spec, AROW_HEAD).split("\n|", 1)[-1]:
        bad.append(F("G-AROWS", "BQ-40's pointer is an A-row, not applied here", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- the dry run


def g_walk(t: Texts) -> list[Finding]:
    """The story-role dry run: one row per consumer role in order, dated, needs = found + not
    found, every not-found folded to a row that exists, the synonym search recorded."""
    sec = spec_sec(t, WALK_HEAD)
    body = section(t.spec, WALK_HEAD)
    rows = [r for r in table_rows(body) if len(r) == 6]
    bad: list[Finding] = []
    if tuple(r[1] for r in rows) != CONSUMER_ROLES:
        bad.append(F("G-WALK", "the roles are not the consumers in order", "spec", sec))
    gids = g_ids(t.spec)
    qids = {r[0] for r in rows_of(t.spec, QROW_HEAD)}
    for r in rows:
        try:
            need, found, nf = int(r[2]), int(r[3]), int(r[4])
        except ValueError:
            bad.append(F("G-WALK", f"{r[1]}: a count is not a number", "spec", sec))
            continue
        if r[0] != DRY_DATE or need != found + nf or need < 1:
            bad.append(F("G-WALK", f"{r[1]}: {need} != {found} + {nf}", "spec", sec))
        if nf and not r[5]:
            bad.append(F("G-WALK", f"{r[1]}: a not-found with no disposition", "spec", sec))
        if not nf and r[5]:
            bad.append(F("G-WALK", f"{r[1]}: a disposition with nothing not found", "spec", sec))
        for m in re.finditer(r"(?<![\w'-])(?:(D05|D08)'s )?(G|Q)-(\d+)\b", r[5]):
            carried = m[1] is not None
            if not carried and m[2] == "G" and int(m[3]) not in gids:
                bad.append(F("G-WALK", f"{r[1]}: G-{m[3]} is not in §15.2", "spec", sec))
            if not carried and m[2] == "Q" and f"Q-{m[3]}" not in qids:
                bad.append(F("G-WALK", f"{r[1]}: Q-{m[3]} is not in §14", "spec", sec))
        if nf and not re.search(r"(?:G|Q)-\d+", r[5]):
            bad.append(F("G-WALK", f"{r[1]}: the not-found is not carried", "spec", sec))
    text = norm_text(body)
    for phrase in ("no session took place and none is claimed", "searched under other names"):
        if phrase not in text:
            bad.append(F("G-WALK", f"§16.2 lacks {phrase!r}", "spec", sec))
    for nn in ("14", "15", "16", "20", "21", "22", "24"):
        if f"`{nn}`" not in body:
            bad.append(F("G-WALK", f"the search did not cover `{nn}`", "spec", sec))
    return bad


def g_ahead(t: Texts) -> list[Finding]:
    """AC4: a closed story built ahead is recorded, not waived after the fact; #2711 and #2110
    read "waived 2026-10-29" (R194); a built-ahead row's gap is under the rule's sprints."""
    sec = spec_sec(t, AHEAD_HEAD)
    gap = int(cite_values()["CITE:ahead.sprints"])
    bad: list[Finding] = []
    rows = ahead_rows(t.spec)
    for r in rows:
        done = r[2]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", done):
            bad.append(F("G-AHEAD", f"{r[0]}: no design Done date", "spec", sec))
            continue
        if r[0].startswith(("#2711", "#2110")):
            if not r[4].startswith("waived 2026-10-29 (R194 BQ-35)"):
                bad.append(F("G-AHEAD", f"{r[0]} is not waived 2026-10-29", "spec", sec))
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[3]):
            d = datetime.date.fromisoformat
            behind = sprint_of(d(r[3])) - sprint_of(d(done)) < gap
            recorded = r[4].startswith("built ahead — recorded, not waived after the fact")
            if behind != recorded:
                bad.append(F("G-AHEAD", f"{r[0]}: built-ahead reading wrong", "spec", sec))
    if not any(r[0].startswith("#2711") for r in rows) or not any(
        r[0].startswith("#2110") for r in rows
    ):
        bad.append(F("G-AHEAD", "#2711 or #2110 has no row", "spec", sec))
    return bad


# ---------------------------------------------------------------------------- the edge

# round 1 P-1 / P-2 (ids, status and trackers public, detail private): patterns only, never the
# literals they refuse. An all-caps cite key the key table does not declare, a server-tree path the
# key table does not carry, or a fix-direction wording arm; the default-deny pins hold the rows,
# so no answer needs a literal here (§4.1)
CITE_LIKE = re.compile(r"\b([A-Z][A-Z0-9]+) ?:\s*\d")
SERVER_PATH = re.compile(r"\bservices/[\w./-]*\w")
EDGE_WORDS = re.compile(
    r"until (?:it|the edge|the server|the base) aligns|\balign\w* (?:the|its) (?:edge|server)"
    r"|\b(?:the )?(?:shipped )?(?:log.?in |sign.?in )?edge(?:'s)? (?:answers|returns|still)"
    r"|the shipped (?:log.?in |sign.?in )?edge|\bthe edge's\b|\bat the base the edge\b"
    r"|\bonce the (?:edge|server) (?:is )?(?:aligned|fixed|corrected)",
    re.IGNORECASE,
)


def edge_hit(text: str) -> str | None:
    """The first undeclared cite key, undeclared server-tree path or wording arm in text."""
    for m in CITE_LIKE.finditer(text):
        if m[1] not in CITE_FILES:
            return m[0]
    for m in SERVER_PATH.finditer(text):
        if m[0] not in CITE_FILES.values():
            return m[0]
    w = EDGE_WORDS.search(text)
    return w[0].strip() if w else None


def g_edge(t: Texts) -> list[Finding]:
    """Round 1 P-1: no line of the spec or the deck cites the sign-in edge or its answers."""
    bad: list[Finding] = []
    for i, line in enumerate(t.spec.split("\n"), 1):
        hit = edge_hit(strip_comments(line))
        if hit:
            msg = f"spec:{i} an edge cite or answer ({hit})"
            bad.append(F("G-EDGE", msg, "spec", h2_at(t.spec, i)))
    for key, e in deck_strings(t.deck).items():
        hit = edge_hit(json.dumps(e, ensure_ascii=False))
        if hit:
            bad.append(F("G-EDGE", f"deck {key}: an edge cite or answer ({hit})", "deck", key))
    return bad


# ---------------------------------------------------------------------------- the folds

# each fold of a lens finding on a ruled sentence: (section, the text that carries it, what it
# carries, the self-test's paraphrase of it); G-FOLD reads the text, M-n plants the paraphrase
FOLDS: tuple[tuple[str, str, str, str], ...] = (
    (
        "15.1 C-rows",
        "`22`:1242 invalidates the challenge after six",
        "C-6 names `22`:1242's six (BQ-40)",
        "`22`:1242 invalidates the challenge later",
    ),
    (
        "15.1 C-rows",
        '`14`:170\'s "Codes refresh every 30 s."',
        "the `14`:170 C-row (BQ-16)",
        "`14`:170's refresh line",
    ),
    (
        "15.1 C-rows",
        "the client rule of §4.1 (F-1)",
        "C-22 against #4961 by number only (round 1 P-1)",
        "the client's own rule",
    ),
    (
        "5.8 SCR-019",
        "E27-D02 §5.7's (`14`:489)",
        "E27-D02 §5.7 cited for the account tasks (BQ-23)",
        "E27-D02's",
    ),
    (
        "4.1 The conditions",
        "`auth.reason.unlock_attempts` only for that cause",
        "the reason line only for its cause (BQ-24)",
        "`auth.reason.unlock_attempts`",
    ),
    (
        "4.1 The conditions",
        "the client keys on the status alone, never on a `code`, `title` or `detail`",
        "the pre-auth `401`s keyed on status alone",
        "the client keys on the `code`",
    ),
    (
        "0. Status",
        "not built; owner: the E09 frontend lane",
        "R-008 step 4 not built, with its owner (round 1 M-1)",
        "built; owner: the E09 frontend lane",
    ),
    (
        "0. Status",
        "step 3's CMP-206 acknowledgement gate (frozen (3))",
        "R-009's acknowledgement-gate delta (round 1 M-1)",
        "step 3's codes",
    ),
    (
        "5.7 SCR-017",
        "`invite.live_from`",
        "the step-4 strings keyed, the live-from line included (round 1 M-1)",
        "`invite.later`",
    ),
    (
        "5.1 SCR-001",
        "the client never reads an environment before sign-in",
        "no environment read before sign-in (RULED BQ-11)",
        "the client reads an environment before sign-in",
    ),
    (
        "5.9 SCR-112",
        "**Re-enrol** held (G-12",
        "SCR-112's Re-enrol held (G-12)",
        "**Re-enrol** offered (G-12",
    ),
    (
        "6. The component",
        "re-aimed by A-7: version-only before sign-in",
        "CMP-207's stories re-aimed before sign-in",
        "as drawn",
    ),
    (
        "15.2 The G-ledger",
        "the locked and the disabled account's login answers",
        "G-10 asks for both answers (R194 BQ-39)",
        "the locked account's login answer",
    ),
    (
        "16.1 Consumers",
        "**In this PR** (RULED BQ-40)",
        "the pointer lines applied as ruled",
        "**Later** (RULED BQ-40)",
    ),
    (
        "17. Versioning",
        "**D5** RULED (accepted",
        "D5 RULED",
        "**D5** asks a ruling (ready line",
    ),
    (
        "17. Versioning",
        "**D6** RULED (accepted",
        "D6 RULED",
        "**D6** asks a ruling (ready line",
    ),
    (
        "17. Versioning",
        "**D7** RULED (acknowledged",
        "D7 acknowledged",
        "**D7** asks an acknowledgement (ready line",
    ),
)
# §10.2: the registered names the band's operations write (ACT; lens 3 m-3)
AUDIT_NAMES = (
    "auth.login_failed",
    "auth.account_locked",
    "auth.unlock_failed",
    "auth.csrf_refused",
    "auth.mfa_enroll",
    "auth.mfa_enrolled",
    "auth.recovery_code_used",
    "auth.recovery_codes_exhausted",
    "auth.recovery_codes_regenerated",
)
# §4.1: the band's own conditions beyond T Scope's (lens 3 m-4)
BAND_CONDITIONS = (
    "unlock on an unlocked session",
    "re-enrol while enrolled",
    "invite rate limited",
)


def g_fold(t: Texts) -> list[Finding]:
    """The folds stand: each FOLDS text in its section, §10.2's names, §4.1's band rows."""
    bad: list[Finding] = []
    for head, needle, what, _alt in FOLDS:
        if needle not in section(t.spec, head):
            bad.append(F("G-FOLD", f"§{head.split()[0]} lacks: {what}", "spec", spec_sec(t, head)))
    audit_body = section(t.spec, "10.2 Audit")
    for name in AUDIT_NAMES:
        if f"`{name}`" not in audit_body:
            bad.append(F("G-FOLD", f"§10.2 lacks `{name}`", "spec", spec_sec(t, "10.2 Audit")))
    rows = {r[0] for r in rows_of(t.spec, ERR_HEAD)}
    for c in BAND_CONDITIONS:
        if c not in rows:
            bad.append(F("G-FOLD", f"§4.1 lacks the row {c!r}", "spec", spec_sec(t, ERR_HEAD)))
    return bad


# ---------------------------------------------------------------------------- remaining rules


def g_deviations(t: Texts) -> list[Finding]:
    """D1..D5; the PR title and labels; `Refs #194` and `Partial:` (RULED BQ-3)."""
    sec = spec_sec(t, VERSION_HEAD)
    body = section(t.spec, VERSION_HEAD)
    bad: list[Finding] = []
    for d in ("**D1**", "**D2**", "**D3**", "**D4**", "**D5**", "**D6**", "**D7**"):
        if d not in body:
            bad.append(F("G-DEVIATIONS", f"§17 lacks {d}", "spec", sec))
    if f"`{PR_TITLE}`" not in body or len(PR_TITLE) > 100:
        bad.append(F("G-DEVIATIONS", "§17's PR title is not BQ-1's", "spec", sec))
    for lab in LABELS:
        if f"`{lab}`" not in body:
            bad.append(F("G-DEVIATIONS", f"§17 lacks the label {lab}", "spec", sec))
    if "`Refs #194`" not in body or "`Partial: " not in body:
        bad.append(F("G-DEVIATIONS", "§17 lacks Refs and Partial", "spec", sec))
    return bad


def g_publish(t: Texts) -> list[Finding]:
    """BQ-37: no story moved; one comment each on the open consumers; no body edited."""
    sec = spec_sec(t, "16.1 Consumers")
    body = section(t.spec, "16.1 Consumers")
    bad = [
        F("G-PUBLISH", f"§16.1 does not name {n}", "spec", sec)
        for n in PUBLISH_TO
        if not re.search(rf"{re.escape(n)}\b", body)
    ]
    text = norm_text(body)
    for need in ("no story is moved", "no issue body or backlog json is edited"):
        if need not in text:
            bad.append(F("G-PUBLISH", f"§16.1 lacks {need!r}", "spec", sec))
    return bad


LOCKED_LEADS = ("D02", "D03", "D04", "D05", "D06", "D08", "D09", "S03", "L1")


def g_locked(t: Texts) -> list[Finding]:
    """BQ-2: one locked-input row per parent, each cited."""
    sec = spec_sec(t, LOCKED_HEAD)
    rows = {r[0]: r for r in rows_of(t.spec, LOCKED_HEAD)}
    bad: list[Finding] = []
    for lead in LOCKED_LEADS:
        r = rows.get(lead)
        if r is None or (lead != "L1" and not cite_refs(r[2])):
            bad.append(F("G-LOCKED", f"§1.1 lacks a cited {lead} row", "spec", sec))
    return bad


def g_a11y(t: Texts) -> list[Finding]:
    """BQ-30: the criteria are part of the Definition of Done, not advisory; the focus map is
    interim until #193; every band screen has a criteria row."""
    sec = spec_sec(t, "9. Accessibility")
    body = section(t.spec, "9. Accessibility")
    text = norm_text(body)
    bad: list[Finding] = []
    for need in (
        "part of each consuming story's definition of done",
        "not advisory",
        "interim until #193",
    ):
        if need not in text:
            bad.append(F("G-A11Y", f"§9 lacks {need!r}", "spec", sec))
    crit = " ".join(r[0] for r in rows_of(t.spec, "9.1 Per-screen"))
    for scr in ("SCR-001", "SCR-003", "SCR-004", "SCR-005", "SCR-017", "SCR-112"):
        if scr not in crit:
            bad.append(F("G-A11Y", f"§9.1 has no row for {scr}", "spec", sec))
    if len(rows_of(t.spec, FOCUS_HEAD)) < 5:
        bad.append(F("G-A11Y", "§9.2's focus map is short", "spec", sec))
    return bad


FORBIDDEN = ("blur", "filter", "layout", "delays focus", "auto-submit", "looping", "masked data")


def g_motion(t: Texts) -> list[Finding]:
    """BQ-31: D08 §3 and §4 lifted by hash (the tool's HASH value); §6's forbidden list for
    builders; D08's open items left open."""
    sec = spec_sec(t, "9.3 Motion")
    body = section(t.spec, "9.3 Motion")
    bad = [
        F("G-MOTION", f"§9.3's forbidden list lacks {w!r}", "spec", sec)
        for w in FORBIDDEN
        if w not in body
    ]
    if "<!--=HASH:d08-->" not in body and "{{HASH:d08}}" not in body:
        bad.append(F("G-MOTION", "§9.3 does not carry D08's hash", "spec", sec))
    return bad


def g_assets(t: Texts) -> list[Finding]:
    """BQ-34 (RULED): the file format and filename as ruled."""
    sec = spec_sec(t, "11. Assets")
    body = section(t.spec, "11. Assets")
    text = norm_text(body)
    bad = (
        []
        if "`candleviewer-recovery-codes.txt`" in body
        else [F("G-ASSETS", "§11 lacks the ruled filename", "spec", sec)]
    )
    if "RULED:file.codes" not in body:
        bad = [*bad, F("G-ASSETS", "§11's code count is not R194's anchor", "spec", sec)]
    need = (
        "utf 8",
        "lf line ends",
        f"the {RULED_VALUES['RULED:file.codes']} codes in display order",
        "one per line",
        "no username, email, server or url",
        "ruled bq 34",
    )
    return bad + [F("G-ASSETS", f"§11 lacks {n!r}", "spec", sec) for n in need if n not in text]


def hash_values() -> Values:
    """The lifted sections' fingerprints at the base (BQ-25, BQ-31): D08 §3 and §4, and D09's
    lifted ranges; G-VERSION re-reads the same ranges at `origin/main`."""
    d08 = "\n".join(base_lines("D08")[93:168])
    d09 = "\n".join(
        "\n".join(base_lines("D09")[a - 1 : b]) for a, b in ((30, 55), (81, 122), (222, 282))
    )
    return {
        "HASH:d08": hashlib.sha256(d08.encode("utf-8")).hexdigest()[:12],
        "HASH:d09": hashlib.sha256(d09.encode("utf-8")).hexdigest()[:12],
    }


# ---------------------------------------------------------------------------- the pins

PIN_SENT = re.compile(r"s\d+")
FULL_STOP = re.compile(r"(?<=[.!?])\s+")


def unvalued(line: str, values: Values) -> str:
    """The line with every anchored value cut to its anchor (outside code spans)."""

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


def spec_units(text: str, values: Values) -> list[Unit]:
    """Every unit of the spec: per region (heading path, `#n` its occurrence) the heading, the
    line shape, each rule line, each table row by its lead cell, each prose sentence and each
    fenced block."""
    lines = text.split("\n")
    fence = fenced(lines)
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    count: dict[str, int] = {}
    region, k, shape, nf = "(top)#1", 0, "", 0
    seen: dict[str, int] = {}
    block: list[str] = []
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
                out.append(("spec", region, f"fence {nf}", json.dumps("\n".join(block))))
                block = []
            continue
        ln = unvalued(raw, values)
        m = HEADING.match(ln)
        if m:
            out.append(("spec", region, "shape", shape))
            level = len(m[1])
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m[2]))]
            key = " › ".join(p[1] for p in path)
            count[key] = count.get(key, 0) + 1
            region, k, seen, shape, nf = f"{key}#{count[key]}", 0, {}, "h", 0
            out.append(("spec", region, "heading", pin_norm(ln)))
            continue
        if not ln.strip():
            shape += "."
        elif is_rule(ln):
            shape += "r"
            out.append(
                ("spec", region, f"rule {shape.count('r')}", pin_norm(re.sub(r"-+", "-", ln)))
            )
        elif re.match(r"^ {0,3}\|", ln):
            shape += indent_tag(raw) + "t"
            rid = row_key(split_row(ln)[0]) or "(blank)"
            seen[rid] = seen.get(rid, 0) + 1
            loc = f"row {rid}" + (f"#{seen[rid]}" if seen[rid] > 1 else "")
            out.append(("spec", region, loc, " | ".join(pin_norm(c) for c in split_row(ln))))
        else:
            sents = [x for x in FULL_STOP.split(ln.strip()) if x.strip()]
            shape += f"{indent_tag(raw)}{line_form(ln)}{len(sents)}"
            for s in sents:
                k += 1
                out.append(("spec", region, f"s{k}", pin_norm(s)))
    out.append(("spec", region, "shape", shape))
    return out


def deck_units(deck: str) -> list[Unit]:
    data = deck_data(deck)
    out: list[Unit] = []
    meta = {k: v for k, v in data.items() if k != "strings"}
    out.append(("deck", "(meta)#1", "meta", json.dumps(meta, ensure_ascii=False, sort_keys=True)))
    for key, e in deck_strings(deck).items():
        out.append(("deck", f"{key}#1", "entry", json.dumps(e, ensure_ascii=False, sort_keys=True)))
    return out


def ruled_units(spec: str, deck: str, values: Values) -> list[Unit]:
    return [*spec_units(spec, values), *deck_units(deck)]


def parse_pins(text: str) -> tuple[Unit, ...]:
    out: list[Unit] = []
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 4:
            out.append((parts[0], parts[1], parts[2], parts[3]))
    return tuple(out)


def write_pins(units: list[Unit]) -> str:
    head = (
        "# E09-D12 pins (every unit of the spec and every deck entry): doc, region (heading path"
        f" #occurrence), location, the exact normalised text; {len(units)} units.\n# Written by "
        "`--repin-ruled` only; `--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in units)


def pin_file_text() -> str | None:
    if PIN_TEXT_OVERRIDE:
        return PIN_TEXT_OVERRIDE[-1]
    path = ROOT / PIN_REL
    return path.read_text(encoding="utf-8") if path.exists() else None


def pin_file_problems() -> list[str]:
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


def region_label(region: str) -> str:
    return region if len(region) <= 60 else "…" + region[-59:]


def region_sec(doc: str, region: str) -> str:
    """A pin region's section key (the gates' key): the `##` heading for the spec, the entry key
    for the deck."""
    if doc == "deck":
        return region.rsplit("#", 1)[0]
    parts = region.rsplit("#", 1)[0].split(" › ")
    return sec_id(parts[1] if len(parts) > 1 else parts[0])


PinProblem = tuple[str, str, str]  # (message, doc, region)


def prose_problems(
    where: str, doc: str, region: str, was: list[str], now: list[str]
) -> list[PinProblem]:
    bad: list[PinProblem] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, was, now, autojunk=False).get_opcodes():
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


def row_problems(
    where: str, doc: str, region: str, was: list[Unit], now: list[Unit]
) -> list[PinProblem]:
    bad: list[PinProblem] = []
    old_t: dict[str, str] = {}
    for u in was:
        old_t.setdefault(u[2], u[3])
    new_t: dict[str, str] = {}
    for u in now:
        if u[2] in new_t:
            bad.append((f"{where} {u[2]} repeated: {u[3][:60]!r}", doc, region))
        else:
            new_t[u[2]] = u[3]
    for loc, txt in new_t.items():
        if loc not in old_t:
            kind = "duplicated" if txt in old_t.values() else "unpinned (new)"
            bad.append((f"{where} {loc} {kind}: {txt[:60]!r}", doc, region))
        elif old_t[loc] != txt:
            what = "shape changed" if loc == "shape" else f"{loc} changed: {txt[:60]!r}"
            bad.append((f"{where} {what}", doc, region))
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
    order = [x for x in old_r if x in new_r]
    if common != order:
        first = next(a for a, b in zip(common, order, strict=True) if a != b)
        bad.append(("a pinned region moved (the heading or key order changed)", first[0], first[1]))
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
    return bad


@functools.lru_cache(maxsize=1)
def read_pins_cached(text: str) -> tuple[Unit, ...]:
    return parse_pins(text)


def pin_findings(t: Texts) -> list[Finding]:
    if PIN_UNITS_OVERRIDE:
        pins: tuple[Unit, ...] | None = PIN_UNITS_OVERRIDE[-1]
        damaged: list[Finding] = []
    else:
        text = pin_file_text()
        pins = read_pins_cached(text) if text is not None else None
        damaged = [F("G-RULED-PIN", m, None, None) for m in pin_file_problems()]
    if pins is None:
        return [F("G-RULED-PIN", f"no {PIN_REL}; run --repin-ruled deliberately", None, None)]
    return damaged + [
        F("G-RULED-PIN", m, d, region_sec(d, r))
        for m, d, r in pin_problems(pins, ruled_units(t.spec, t.deck, t.vals))
    ]


# ---------------------------------------------------------------------------- v2: the delta

# R2's own words the v2 blocks may quote (G-QUOTE); the ruling is a comment, not a file
R2_QUOTES = ("(E09-D12)", "Outside", "pending", "re-sync needed: <what changed>")
# v2's load-bearing fragments: (cite id, line at BASE_V2, text the line must hold)
CITED_V2: tuple[tuple[str, int, str], ...] = (
    ("22", 1832, "operationId: authLock"),
    ("22", 1196, "Every failed sign-in gets one answer, whatever the account's state"),
    ("22", 1864, "if the audit sink is"),
    ("22", 1865, "the session is not locked"),
    ("22", 24308, "maxLength: 32"),
    ("04", 834, "Every failed sign-in gets one answer"),
    ("04", 844, "Absolute lifetime 12 h"),
    ("14", 468, "link not valid"),
    ("15", 2609, 'the constant name "Show password"'),
    ("15", 2646, "name contains its visible heading"),
    ("15", 2660, "untinted"),
    ("15", 2684, "`version: string`"),
    ("ACT", 53, '"auth.session_locked"'),
    ("D07", 22, "`E09-D07 auth band`"),
    ("D07", 37, "Nothing in the band is published."),
    ("D07", 240, "quiet-zone token"),
    ("D07", 242, "D12 Q-9"),
    ("D07", 254, "D12 Q-9, D12 Q-10"),
    ("D09", 49, "**never the `disabled` attribute**"),
    ("D09", 204, "CMP-079 RbacGate"),
    ("D09", 207, '"Not available"'),
    ("D10", 237, '"Two-factor code"'),
    ("D10", 406, "pre-rendered polite region"),
    ("D10", 408, "the carrier"),
    ("D10", 517, '"Invalid password or code."'),
    ("D10", 518, '"Signed out. Market data stopped. Sign in again."'),
    ("D10", 912, "the enrolment-only session"),
    ("D10", 919, "the owner MFA-reset operation"),
    ("D10", 931, "forces enrolment under a fresh password re-authentication"),
    ("E17D02", 249, "owned by the app shell"),
)
REGISTER_HEAD = "17.1 The v2 delta register"
MODES_HEAD = "17.2 The modes and the gates"
DRIFT_HEAD = "17.3 The v1 cites re-read"
STATUS2_HEAD = "0.1 The status table"
PARENTS_HEAD = "1.3 The parents at the v2 base"
LIFT_HEAD = "1.4 Lift, copy or cite"
OPS2_HEAD = "3.4 `authLock`"
ERR2_HEAD = "4.3 The error map at the v2 base"
COMP2_HEAD = "6.1 The inventory at the v2 base"
T2_HEAD = "6.2 The T2 controls"
PAIRS2_HEAD = "7.4 Contrast and CVD at the v2 base"
DECK2_HEAD = "8.4 The deck at v2"
CROSS_HEAD = "9.4 The crosswalk"
FIND_HEAD = "9.6 D10's findings carried"
LIVE_HEAD = "9.7 Live regions"
AHEAD2_HEAD = "13.1 The design-ahead record at the v2 base"
QROW2_HEAD = "14.1 The open questions at the v2 base"
CROW2_HEAD = "15.4 C-rows at the v2 base"
GROW2_HEAD = "15.5 The G-ledger at the v2 base"
AROW2_HEAD = "15.6 A-rows at the v2 base"
STORY_HEAD = "16.0 The per-story table"
OUTSIDE_HEAD = "16.4 The outside dry run"
# BQ-04 (R2 as default): the D12 lines E09-D07's tool cites by content, kept byte-stable (never a
# C row), and the section numbers the e2e specs and `15` cite
D07_CITED = (
    (60, "#190 takes §6 as its input"),
    (252, "not published"),
    (424, "Q-9"),
    (425, "Q-10"),
    (488, "`version: string`"),
)
CITED_HEADS = (
    "## 6. The component and state inventory",
    "### 8.3 The never-list",
    "### 9.2 The interim focus-continuity map",
    "### 10.2 Audit and analytics",
)
# §1.4's lifted blocks: (cite id, first, last, the HASH key) at BASE_V2
LIFTS = (
    ("D10", 308, 402, "d10.map"),
    ("D10", 590, 635, "d10.script"),
    ("D10", 639, 661, "d10.assert"),
    ("D10", 663, 781, "d10.templates"),
    ("D07", 104, 115, "d07.contracts"),
)
GRADES = ("Blocker", "Major", "Minor", "Info")
D10_BLOCKERS = ("F-1", "F-2", "F-25", "F-26")
D10_FINDINGS = (532, 588)  # D10 §12 at BASE_V2
D10_MAP = (308, 402)  # D10 §6.2 at BASE_V2
D10_SCRIPT = (590, 635)
D10_ASSERT = (639, 661)
STORY_CONSUMERS = (
    "#2711 (SCR-002)",
    "#2110 frontend leg (SCR-004)",
    'the web "Lock now" leg',
    "E09-D11 (#291)",
    "E09-Q02 (#293)",
    "E09-Q06 (#297)",
    "#2490",
)
A_STATUS = ("applied", "applied in part", "open", "the RULED sentence")
DEPUTY = re.compile(r"\(deputy, \d{4}-\d{2}-\d{2}\)")
MODE_OVERRIDE: list[str] = []  # self-test lever: "pr" or "post"
WARNS: list[str] = []  # the WARN lines of the current audit


def warn(msg: str) -> None:
    WARNS.append(msg)


@functools.lru_cache(maxsize=1)
def v1_text() -> str:
    """v1 as merged; an unreadable v1 is a parse failure (every v2 gate reads it)."""
    text = git_show(V1_SHA, SPEC_REL)
    if text is None:
        raise SystemExit(f"FAIL parse: {SPEC_REL} is not readable at {V1_SHA}")
    return text


@functools.lru_cache(maxsize=1)
def v1_deck() -> dict[str, dict[str, object]]:
    return deck_strings(git_show(V1_SHA, DECK_REL) or "")


def on_disk_spec() -> str:
    return (ROOT / SPEC_REL).read_bytes().decode("utf-8")


@functools.lru_cache(maxsize=1)
def post_merge_by_content() -> bool:
    """Post-merge: the spec on disk equals its copy at `origin/main`, which carries the v2 line."""
    head = git_show(HEAD, SPEC_REL)
    return head is not None and head == on_disk_spec() and f"**v2 at base `{BASE_V2}`**" in head


def post_merge() -> bool:
    if MODE_OVERRIDE:
        return MODE_OVERRIDE[-1] == "post"
    return post_merge_by_content()


def mode_name() -> str:
    return "post-merge" if post_merge() else "PR"


def v2_spans(spec: str) -> tuple[tuple[int, int], ...]:
    """0-based [start, end) line spans of the v2 blocks: a heading ending in "(v2)" to the next
    heading that does not."""
    return v2_spans_cached(spec)


@functools.lru_cache(maxsize=64)
def v2_spans_cached(spec: str) -> tuple[tuple[int, int], ...]:
    lines = spec.split("\n")
    fence = fenced(lines)
    out: list[tuple[int, int]] = []
    start = -1
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if not m or fence[i]:
            continue
        mine = m[2].rstrip().endswith(V2_MARK)
        if mine and start < 0:
            start = i
        elif not mine and start >= 0:
            out.append((start, i))
            start = -1
    if start >= 0:
        out.append((start, len(lines)))
    return tuple(out)


@functools.lru_cache(maxsize=64)
def v2_line_set(spec: str) -> frozenset[int]:
    """The 1-based line numbers inside v2 blocks, plus the C lines §17.1 names."""
    lines: set[int] = set()
    for a, b in v2_spans(spec):
        lines |= set(range(a + 1, b + 1))
    view_map = v1_view_map(spec)
    for n in c_lines(spec):
        if 0 < n <= len(view_map):
            lines.add(view_map[n - 1])
    return frozenset(lines)


@functools.lru_cache(maxsize=64)
def v1_view_map(spec: str) -> tuple[int, ...]:
    """For each line of the v1 view, its 1-based line number in the spec."""
    drop: set[int] = set()
    for a, b in v2_spans(spec):
        drop |= set(range(a, b))
    return tuple(i + 1 for i in range(len(spec.split("\n"))) if i not in drop)


@functools.lru_cache(maxsize=64)
def v1_view(spec: str) -> str:
    lines = spec.split("\n")
    return "\n".join(lines[n - 1] for n in v1_view_map(spec))


def register_rows(spec: str) -> list[list[str]]:
    return [r for r in rows_of(spec, REGISTER_HEAD) if re.fullmatch(r"V-\d+", r[0])]


@functools.lru_cache(maxsize=64)
def c_lines(spec: str) -> frozenset[int]:
    """The v1 line numbers §17.1's C rows name ("v1 line N")."""
    out: set[int] = set()
    for r in register_rows(spec):
        if len(r) > 2 and r[2] == "C":
            out |= {int(n) for n in re.findall(r"v1 line (\d+)", r[1])}
    return frozenset(out)


def unit_name(cell: str) -> str:
    """A register Unit cell's key: "§4.3", "(top)", "deck `key`", "deck (meta)", "`14`"."""
    cell = cell.strip()
    m = re.match(r"(§\d+(?:\.\d+)?|\(top\)|deck `[^`]+`|deck \(meta\)|`14`)", cell)
    return m[1] if m else cell


@functools.lru_cache(maxsize=64)
def drift_registered(spec: str) -> frozenset[tuple[str, int, int]]:
    """The v1 cites §17.3's first column names (the ranges edited after v1's base)."""
    out: set[tuple[str, int, int]] = set()
    for r in rows_of(spec, DRIFT_HEAD):
        if len(r) >= 4:
            out |= set(cite_refs(r[0]))
    return frozenset(out)


def v1_drifted() -> set[tuple[str, int, int]]:
    """Every v1 cite (spec v1 lines and deck sources) whose range is edited at `origin/main`."""
    out: set[tuple[str, int, int]] = set()
    if not head_ok():
        return out
    spec = v1_text()
    deck = git_show(V1_SHA, DECK_REL) or ""
    lines = [*spec.split("\n"), *(src for _k, src in deck_cites(deck))]
    for line in lines:
        for cid, a, b in cite_refs(line):
            rel = cite_path(cid)
            if rel is None or git_show(BASE, rel) is None:
                continue
            head_t = git_fetch_head(rel)
            block = list(cited_block(BASE, rel, a, b))
            if head_t is None or not block or not block_count(head_t.split("\n"), block, 1):
                out.add((cid, a, b))
    return out


def sec_of_v1(n: int) -> str:
    return h2_at(v1_text(), n)


def quoted(cell: str) -> list[str]:
    return [m[0][1:-1] for m in QUOTED.finditer(CODE.sub(" ", strip_comments(cell)))]


def quoted_pieces(raw: str, string: str) -> bool:
    """`string` is quoted pieces of `raw`, in order, joined by single spaces."""
    rest = string
    for q in quoted(raw):
        if rest.startswith(q):
            rest = rest[len(q) :].lstrip(" ")
            if not rest:
                return True
    return False


def d10_rows(a: int, b: int, prefix: str) -> dict[str, list[str]]:
    """D10's table rows at BASE_V2 within lines a..b whose lead cell starts with `prefix`."""
    out: dict[str, list[str]] = {}
    for ln in base_lines("D10", BASE_V2)[a - 1 : b]:
        if ln.startswith(f"| {prefix}"):
            cells = split_row(ln)
            out[cells[0]] = cells
    return out


def id_span(text: str, prefix: str) -> list[str]:
    """Every `prefix`-n id in text, with "X-a to X-b" expanded."""
    ids: list[str] = []
    for m in re.finditer(rf"\b{prefix}-(\d+)(?: to {prefix}-(\d+))?\b", text):
        lo = int(m[1])
        hi = int(m[2]) if m[2] else lo
        ids += [f"{prefix}-{n}" for n in range(lo, hi + 1)]
    return ids


@functools.lru_cache(maxsize=4)
def openapi_ops_at(rev: str) -> dict[str, tuple[str, str, int]]:
    out: dict[str, tuple[str, str, int]] = {}
    path, path_line, method = "", 0, ""
    for i, ln in enumerate(base_lines("22", rev), 1):
        m = re.match(r"^  (/[^:]*):\s*$", ln)
        if m:
            path, path_line = m[1], i
            continue
        m = re.match(r"^    (get|put|post|delete|patch):\s*$", ln)
        if m:
            method = m[1].upper()
            continue
        m = re.match(r"^      operationId: (\w+)\s*$", ln)
        if m and path:
            out[m[1]] = (method, path, path_line)
    return out


@functools.lru_cache(maxsize=16)
def token_file_at(rev: str, name: str) -> dict[str, object]:
    text = git_show(rev, f"{DS_SRC_REL}/{name}.tokens.json")
    if text is None:
        raise SystemExit(f"FAIL parse: the {name} tokens are not readable at {rev}")
    data = json.loads(text)
    return {k: v.get("$value") for k, v in data.items() if isinstance(v, dict)}


def theme_hex_at(rev: str, theme: str, name: str) -> str:
    merged: dict[str, object] = {}
    for f in THEMES[theme]:
        merged.update(token_file_at(rev, f))
    v = resolve(merged, name)
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
        raise SystemExit(f"FAIL token {name} does not resolve to an opaque colour in {theme}")
    return v.upper()


def lift_hash(cid: str, a: int, b: int) -> str:
    text = "\n".join(base_lines(cid, BASE_V2)[a - 1 : b])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def v2_values(spec: str) -> Values:
    """v2's computed values: the ops count, the pairs at BASE_V2, D10's grade counts, the lift
    hashes."""
    view = v1_view(spec)
    out: Values = {}
    v1_ops = [r for r in rows_of(view, OPS_HEAD) if r[0].startswith("`")]
    v2_ops = [r for r in rows_of(spec, OPS2_HEAD) if r[0].startswith("`")]
    out["COUNT:v2.ops"] = str(len(v1_ops) + len(v2_ops))
    for r in pair_rows(view):
        pid = r[0].split()[0].lower().replace("-", "")
        fg, bg = r[1].strip("`"), r[2].strip("`")
        for theme in PAIR_THEMES:
            try:
                ratio = contrast(theme_hex_at(BASE_V2, theme, fg), theme_hex_at(BASE_V2, theme, bg))
                out[f"CONTRAST:v2.{pid}.{theme}"] = show_ratio(ratio)
            except SystemExit:
                out[f"CONTRAST:v2.{pid}.{theme}"] = "unresolved"
    rows = d10_rows(*D10_FINDINGS, "F-")
    out["COUNT:v2.f.total"] = str(len(rows))
    for g in GRADES:
        out[f"COUNT:v2.f.{g.lower()}"] = str(sum(1 for c in rows.values() if c[2] == g))
    for cid, a, b, key in LIFTS:
        out[f"HASH:{key}"] = lift_hash(cid, a, b)
    return out


def v2_below(spec: str) -> tuple[list[str], list[str]]:
    """(pairs below their bar at BASE_V2, pairs that meet it but fall below it simulated)."""
    view = v1_view(spec)
    cite = cite_values()
    bar = {"text": float(cite["CITE:bar.text"]), "non-text": float(cite["CITE:bar.ui"])}
    below: list[str] = []
    sim: list[str] = []
    for r in pair_rows(view):
        pid, fg, bg = r[0].split()[0], r[1].strip("`"), r[2].strip("`")
        need = bar.get(r[-1], bar["text"])
        for theme in PAIR_THEMES:
            a, c = theme_hex_at(BASE_V2, theme, fg), theme_hex_at(BASE_V2, theme, bg)
            if contrast(a, c) < need:
                below.append(f"{pid} {theme}")
                continue
            for kind in DEFICIENCIES:
                if contrast(simulate(a, kind), simulate(c, kind)) < need:
                    sim.append(f"{pid} {theme} {kind}")
    return below, sim


def v2_body(t: Texts, head: str) -> tuple[str, str]:
    return section(t.spec, head), spec_sec(t, head)


def g_v1_frozen(t: Texts) -> list[Finding]:
    """R2 BQ-02/03: the spec without its v2 blocks is v1 byte for byte, but for the v1 lines a
    §17.1 C row names (a finding here is a NOTE where another gate flags the same section)."""
    want = v1_text().split("\n")
    got = v1_view(t.spec).split("\n")
    allowed = c_lines(t.spec)
    bad: list[Finding] = []
    ops = difflib.SequenceMatcher(None, want, got, autojunk=False).get_opcodes()
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            continue
        if op == "replace" and i2 - i1 == j2 - j1:
            for i in range(i1, i2):
                if i + 1 not in allowed:
                    msg = f"v1 line {i + 1} changed without a §17.1 C row"
                    bad.append(F("G-V1-FROZEN", msg, "spec", sec_of_v1(i + 1)))
            continue
        at = max(i1, 1)
        what = {"insert": "lines added", "delete": "lines dropped", "replace": "lines changed"}[op]
        msg = f"v1 lines {i1 + 1}..{max(i1 + 1, i2)}: {what} outside a v2 block ({j2 - j1} now)"
        bad.append(F("G-V1-FROZEN", msg, "spec", sec_of_v1(at)))
    return bad


def g_register(t: Texts) -> list[Finding]:
    """R2 BQ-02: §17.1's rows are V-1..V-n in order; each change is C, A or S; an A or S row names
    a v2 block, a C row a v1 line that differs; an S row quotes the v1 unit it supersedes, which
    still stands in the v1 view."""
    _body, sec = v2_body(t, REGISTER_HEAD)
    rows = register_rows(t.spec)
    bad: list[Finding] = []
    if not rows:
        return [F("G-REGISTER", "§17.1 has no rows", "spec", sec)]
    if [r[0] for r in rows] != [f"V-{n}" for n in range(1, len(rows) + 1)]:
        bad.append(F("G-REGISTER", "§17.1's ids are not V-1..V-n in order", "spec", sec))
    blocks = set()
    lines = t.spec.split("\n")
    for a, b in v2_spans(t.spec):
        for ln in lines[a:b]:
            m = re.match(r"^#+ (\d+(?:\.\d+)?)[ .].*\(v2\)\s*$", ln)
            if m:
                blocks.add(f"§{m[1]}")
    view = strip_comments(v1_view(t.spec))
    want = v1_text().split("\n")
    got = v1_view(t.spec).split("\n")
    for r in rows:
        if len(r) < 6:
            bad.append(F("G-REGISTER", f"{r[0]} has {len(r)} cells", "spec", sec))
            continue
        name, change = unit_name(r[1]), r[2]
        if change not in ("C", "A", "S"):
            bad.append(F("G-REGISTER", f"{r[0]} change {change!r} is not C, A or S", "spec", sec))
        elif change in ("A", "S") and name not in blocks:
            bad.append(F("G-REGISTER", f"{r[0]} names {name}, no v2 block", "spec", sec))
        elif change == "S" and not any(q in view for q in quoted(r[3])):
            bad.append(F("G-REGISTER", f"{r[0]} supersedes nothing that stands", "spec", sec))
        elif change == "C" and name == "(top)":
            for n in (int(x) for x in re.findall(r"v1 line (\d+)", r[1])):
                if n > len(want) or n > len(got) or want[n - 1] == got[n - 1]:
                    bad.append(F("G-REGISTER", f"{r[0]}: v1 line {n} is unchanged", "spec", sec))
    return bad


def pin_regions(text: str | None) -> set[tuple[str, str, str, str]]:
    return set(parse_pins(text)) if text is not None else set()


def region_unit(doc: str, region: str) -> str:
    """A pin region's register key (the inverse of unit_name)."""
    if doc == "deck":
        key = region.rsplit("#", 1)[0]
        return "deck (meta)" if key == "(meta)" else f"deck `{key}`"
    last = region.rsplit("#", 1)[0].split(" › ")[-1]
    m = re.match(r"(\d+(?:\.\d+)?)[ .]", last)
    if m is None or " › " not in region:
        return "(top)"
    return f"§{m[1]}"


def g_delta(t: Texts) -> list[Finding]:
    """R2 BQ-06: every pin unit that differs from v1's pins (`V1_SHA`) sits in a region §17.1
    names; it runs in both modes."""
    _body, sec = v2_body(t, REGISTER_HEAD)
    old = git_show(V1_SHA, PIN_REL)
    if old is None:
        return [F("G-DELTA", f"v1's pins are not readable at {V1_SHA}", "spec", sec)]
    new = pin_file_text()
    if new is None:
        return [F("G-DELTA", "no pins file in the tree", "spec", sec)]
    named = {unit_name(r[1]) for r in register_rows(t.spec) if len(r) > 1}
    changed = {(u[0], u[1]) for u in pin_regions(old) ^ pin_regions(new)}
    missing = sorted({region_unit(d, r) for d, r in changed} - named)
    return [
        F("G-DELTA", f"the pin diff touches {m}, which §17.1 does not name", "spec", sec)
        for m in missing
    ]


def v1_kept(spec: str) -> frozenset[int]:
    """The 1-based v1 lines that stand unchanged in the v1 view (aligned by content)."""
    want = v1_text().split("\n")
    got = v1_view(spec).split("\n")
    kept: set[int] = set()
    for op, i1, i2, _j1, _j2 in difflib.SequenceMatcher(
        None, want, got, autojunk=False
    ).get_opcodes():
        if op == "equal":
            kept |= set(range(i1 + 1, i2 + 1))
    return frozenset(kept)


def g_cited_stable(t: Texts) -> list[Finding]:
    """BQ-04: the D12 lines E09-D07's tool cites stand byte-equal (never a C row; aligned by
    content, so a line inserted elsewhere is no change) and the cited headings keep their
    numbers."""
    want = v1_text().split("\n")
    kept = v1_kept(t.spec)
    bad: list[Finding] = []
    for n, frag in D07_CITED:
        if n not in kept or frag not in want[n - 1]:
            msg = f"v1 line {n} ({frag!r}), cited by E09-D07's tool, changed"
            bad.append(F("G-CITED-STABLE", msg, "spec", sec_of_v1(n)))
    lines = t.spec.split("\n")
    for head in CITED_HEADS:
        if not any(ln.startswith(head) for ln in lines):
            bad.append(F("G-CITED-STABLE", f"the cited heading {head!r} is gone", "spec", None))
    return bad


def g_drift(t: Texts) -> list[Finding]:
    """R2 BQ-14: each §17.3 row names v1 cites whose range is edited at `origin/main`, and its
    v2 column cites lines at the v2 base."""
    _body, sec = v2_body(t, DRIFT_HEAD)
    drifted = v1_drifted()
    bad: list[Finding] = []
    rows = [r for r in rows_of(t.spec, DRIFT_HEAD) if len(r) >= 4]
    if not rows:
        return [F("G-DRIFT", "§17.3 has no rows", "spec", sec)]
    for r in rows:
        refs = cite_refs(r[0])
        if not refs or not cite_refs(r[1]):
            bad.append(F("G-DRIFT", f"§17.3 row {r[0][:30]!r} lacks a cite", "spec", sec))
        for ref in refs:
            if ref not in drifted and not post_merge():
                msg = f"§17.3 names `{ref[0]}`:{ref[1]}–{ref[2]}, which is not edited"
                bad.append(F("G-DRIFT", msg, "spec", sec))
    return bad


def g_mode(t: Texts) -> list[Finding]:
    """R2 BQ-01/05: the Ticket line names v2 at its base; the deck reads v2 at it; §17.2 states
    both versions and R2; the v2 base is a commit under `origin/main`."""
    _body, sec = v2_body(t, MODES_HEAD)
    bad: list[Finding] = []
    first = next((ln for ln in t.spec.split("\n") if ln.startswith("**Ticket:**")), "")
    if f"**v2 at base `{BASE_V2}`**" not in first:
        bad.append(F("G-MODE", "the Ticket line does not name v2 at its base", "spec", "(top)"))
    meta = deck_data(t.deck)
    if meta.get("version") != "v2" or meta.get("base") != BASE_V2:
        bad.append(F("G-MODE", "the deck's version or base is not v2's", "deck", "(meta)"))
    body = norm_text(section(t.spec, MODES_HEAD))
    for need in (f"v2 at base {BASE_V2}", f"v1 at base {BASE}", R2_ID, "post merge mode"):
        if norm_text(need) not in body:
            bad.append(F("G-MODE", f"§17.2 lacks {need!r}", "spec", sec))
    full = git_out("rev-parse", "--verify", "--quiet", f"{BASE_V2}^{{commit}}").strip()
    if head_ok() and (not full or git_out("merge-base", full, HEAD).strip() != full):
        bad.append(F("G-MODE", f"{BASE_V2} is not under {HEAD}", "spec", sec))
    return bad


def g_parents(t: Texts) -> list[Finding]:
    """R2 BQ-08: each merged parent's sha is a commit under the v2 base whose subject names its
    PR; an unmerged parent reads "none" and is named only."""
    body, sec = v2_body(t, PARENTS_HEAD)
    bad: list[Finding] = []
    for r in table_rows(body):
        if len(r) < 4:
            continue
        for pr, sha in re.findall(r"#(\d+) `([0-9a-f]{10})`", r[2]):
            full = git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").strip()
            subj = git_out("log", "-1", "--format=%s", sha).strip()
            under = bool(full) and git_out("merge-base", full, BASE_V2).strip() == full
            if not under or not subj.endswith(f"(#{pr})"):
                bad.append(
                    F("G-PARENTS", f"#{pr} `{sha}` is not its merge under the base", "spec", sec)
                )
        if r[1].startswith("not merged") and r[2] != "none":
            bad.append(F("G-PARENTS", f"{r[0]} is unmerged but names a merge", "spec", sec))
    if "**Named only, never pinned or quoted (v2):**" not in body:
        bad.append(F("G-PARENTS", "§1.3 lacks the named-only line", "spec", sec))
    return bad


def g_lift(t: Texts) -> list[Finding]:
    """R2 BQ-10: §1.4's lifted rows are LIFTS, each with its range and its HASH anchor."""
    body, sec = v2_body(t, LIFT_HEAD)
    rows = [r for r in table_rows(body) if len(r) >= 3 and r[2].startswith("lifted by hash")]
    got = set()
    for r in rows:
        for cid, a, b in cite_refs(r[1]):
            keys = re.findall(r"HASH:([a-z0-9.]+)", r[2])
            got.add((cid, a, b, keys[0] if keys else ""))
    want = set(LIFTS)
    bad = [
        F("G-LIFT", f"§1.4 lacks the lift {x[0]}:{x[1]}–{x[2]} ({x[3]})", "spec", sec)
        for x in sorted(want - got)
    ]
    bad += [
        F("G-LIFT", f"§1.4 lifts {x[0]}:{x[1]}–{x[2]} ({x[3]}), not a tool lift", "spec", sec)
        for x in sorted(got - want)
    ]
    return bad


def g_ops2(t: Texts) -> list[Finding]:
    """R2 BQ-12: §3.4's rows are operations of `22` at the v2 base, at their path's line, absent
    from §3.1; the count is §3.1's plus §3.4's."""
    body, sec = v2_body(t, OPS2_HEAD)
    ops = openapi_ops_at(BASE_V2)
    v1_ops = {r[0].strip("`") for r in rows_of(v1_view(t.spec), OPS_HEAD)}
    bad: list[Finding] = []
    rows = [r for r in table_rows(body) if r[0].startswith("`")]
    if not rows:
        bad.append(F("G-OPS2", "§3.4 has no operation", "spec", sec))
    for r in rows:
        op = r[0].strip("`")
        got = ops.get(op)
        cites = cite_refs(r[2])
        method_path = f"{got[0]} `{got[1]}`" if got else ""
        if got is None or r[1] != method_path or not cites or cites[0][1] != got[2]:
            bad.append(F("G-OPS2", f"§3.4 {op} is not `22`'s at the v2 base", "spec", sec))
        if op in v1_ops:
            bad.append(F("G-OPS2", f"§3.4 {op} is already a §3.1 row", "spec", sec))
    return bad


def g_errmap2(t: Texts) -> list[Finding]:
    """R2 BQ-13: §4.3 maps each condition onto one state, a deck key or none, a fallback of §4.2
    or none; a supersede cell quotes a §4.1 row that stands."""
    body, sec = v2_body(t, ERR2_HEAD)
    view = v1_view(t.spec)
    fbs = set(fallbacks(view))
    keys = deck_strings(t.deck)
    v1_conds = {r[0] for r in rows_of(view, ERR_HEAD)}
    bad: list[Finding] = []
    for r in table_rows(body):
        if len(r) != 6:
            continue
        key = r[3].strip("`")
        if r[3] != "—" and key not in keys:
            bad.append(F("G-ERRMAP2", f"§4.3 {r[0]}: {r[3]} is not a deck key", "spec", sec))
        if r[4] != "—" and r[4] not in fbs:
            bad.append(F("G-ERRMAP2", f"§4.3 {r[0]}: {r[4]} is not a §4.2 fallback", "spec", sec))
        if r[5] != "—" and not any(q in v1_conds for q in quoted(r[5])):
            bad.append(F("G-ERRMAP2", f"§4.3 {r[0]} supersedes no §4.1 row", "spec", sec))
    return bad


def g_crosswalk(t: Texts) -> list[Finding]:
    """R2 BQ-17: each §9.2 row appears once in §9.4, naming T-rows of D10's map at the v2 base
    and the first one's focus target verbatim; a row that disagrees names a §15.4 C-row."""
    body, sec = v2_body(t, CROSS_HEAD)
    interim = [r[0] for r in rows_of(v1_view(t.spec), FOCUS_HEAD)]
    tmap = d10_rows(*D10_MAP, "T-")
    crows = {r[0] for r in rows_of(t.spec, CROW2_HEAD)}
    rows = [r for r in table_rows(body) if len(r) == 4]
    bad: list[Finding] = []
    if sorted(r[0] for r in rows) != sorted(interim):
        bad.append(F("G-CROSSWALK", "§9.4 does not cross every §9.2 row once", "spec", sec))
    for r in rows:
        tids = id_span(r[1], "T")
        if not tids or any(x not in tmap for x in tids):
            bad.append(F("G-CROSSWALK", f"§9.4 {r[0]}: {r[1]} not in D10's map", "spec", sec))
            continue
        if pin_norm(r[2]) != pin_norm(tmap[tids[0]][4]):
            bad.append(F("G-CROSSWALK", f"§9.4 {r[0]}: not {tids[0]}'s focus target", "spec", sec))
        m = re.fullmatch(r"no \((C-\d+)\)", r[3])
        if r[3] != "yes" and (m is None or m[1] not in crows):
            bad.append(F("G-CROSSWALK", f"§9.4 {r[0]}: {r[3]!r} names no C-row", "spec", sec))
    return bad


def g_findings(t: Texts) -> list[Finding]:
    """R2 BQ-21/22: §9.6 carries D10's rows with D10's grade, owner and close state, in the four
    grades; the four Blockers are carried and none reads closed."""
    body, sec = v2_body(t, FIND_HEAD)
    d10 = d10_rows(*D10_FINDINGS, "F-")
    rows = {r[0]: r for r in table_rows(body) if re.fullmatch(r"F-\d+", r[0])}
    bad: list[Finding] = []
    for fid in D10_BLOCKERS:
        if fid not in rows:
            bad.append(F("G-FINDINGS", f"§9.6 does not carry the Blocker {fid}", "spec", sec))
    for fid, r in rows.items():
        src = d10.get(fid)
        if src is None or len(r) != 5:
            bad.append(F("G-FINDINGS", f"§9.6 {fid} is not a D10 row", "spec", sec))
            continue
        if r[1] not in GRADES or r[1] != src[2] or r[2] != src[5] or r[4] != src[8]:
            bad.append(
                F("G-FINDINGS", f"§9.6 {fid} is not D10's grade, owner or state", "spec", sec)
            )
        if re.search(r"\bclosed\b", r[4]):
            bad.append(F("G-FINDINGS", f"§9.6 {fid} reads closed", "spec", sec))
    text = norm_text(body)
    for g in GRADES:
        if (
            f"<!--=COUNT:v2.f.{g.lower()}-->" not in body
            and f"{{{{COUNT:v2.f.{g.lower()}}}}}" not in body
        ):
            bad.append(F("G-FINDINGS", f"§9.6 does not count the grade {g}", "spec", sec))
    for need in ("not claimed closed", "info rows carry and none is dropped"):
        if need not in text:
            bad.append(F("G-FINDINGS", f"§9.6 lacks {need!r}", "spec", sec))
    return bad


SELF_HOSTED = re.compile(
    r"(?:before sign.?in|scr-001|/login)[^.;]*\bown(?:s)? (?:their|its) own\b"
    r"|\bown(?:s)? (?:their|its) own (?:pair|regions?)\b[^.;]*before sign.?in",
)


def g_announcer(t: Texts) -> list[Finding]:
    """R2 BQ-19: no rule is invented for the screens before sign-in; G-14 carries the case to
    D10 §7 and E17-D02 §11, the shell's presence on `/login` UNVERIFIED."""
    body, sec = v2_body(t, LIVE_HEAD)
    text = norm_text(body)
    bad: list[Finding] = []
    for need in ("g 14", "d10 §7", "e17 d02 §11", "unverified", "no rule is invented"):
        if need not in text:
            bad.append(F("G-ANNOUNCER", f"§9.7 lacks {need!r}", "spec", sec))
    for c in clauses(body):
        if SELF_HOSTED.search(norm_text(c)) and not re.search(rf"\b{NEG_WORD}\b", norm_text(c)):
            bad.append(
                F("G-ANNOUNCER", f"§9.7 rules a host before sign-in: {c[:50]!r}", "spec", sec)
            )
    g14 = next((r for r in rows_of(t.spec, GROW2_HEAD) if r[0] == "G-14"), [])
    if len(g14) < 4 or g14[3] != "D10 §7 and E17-D02 §11":
        bad.append(F("G-ANNOUNCER", "G-14's owner is not D10 §7 and E17-D02 §11", "spec", sec))
    return bad


T2_NEEDS = (
    '`aria-disabled="true"`',
    "never the `disabled` attribute",
    "`aria-describedby`",
    "in the DOM at mount",
    "CMP-079 RbacGate",
    "CMP-019 `lock`",
    "`decorative={false}`",
    '"Not available"',
    "leads the full label",
)


@functools.lru_cache(maxsize=1)
def d09_verbs() -> frozenset[str]:
    lines = base_lines("D09", BASE_V2)
    start = next((i for i, ln in enumerate(lines) if ln.startswith("### 3.2 ")), 0)
    out: set[str] = set()
    for ln in lines[start : start + 40]:
        out |= set(re.findall(r"→ \"([^\"]+)\"", ln))
    return frozenset(out)


def g_t2(t: Texts) -> list[Finding]:
    """D09's T2 anatomy restated for the band's T2 controls: each row a D09 §3.1 key, a §3.2
    verb (or none, for a key that fills none), a `15` component; §6.1 names CMP-079 and CMP-019."""
    body, sec = v2_body(t, T2_HEAD)
    bad = [F("G-T2", f"§6.2 lacks {n!r}", "spec", sec) for n in T2_NEEDS if n not in body]
    keys = set(d09_keys())
    for r in table_rows(body):
        if len(r) != 4:
            continue
        key = re.match(r"`([a-z_.]+)`", r[1])
        if key is None or key[1] not in keys:
            bad.append(F("G-T2", f"§6.2 {r[0][:30]}: {r[1][:30]} is not a D09 key", "spec", sec))
        verb = quoted(r[2])
        if not (r[2].startswith("none:") or (verb and verb[0] in d09_verbs())):
            bad.append(F("G-T2", f"§6.2 {r[0][:30]}: {r[2][:30]} is not a D09 verb", "spec", sec))
        if not CMP_ID.search(r[3]):
            bad.append(F("G-T2", f"§6.2 {r[0][:30]} names no component", "spec", sec))
    comp = section(t.spec, COMP2_HEAD)
    for cmp in ("CMP-079 RbacGate", "CMP-019 Icon"):
        if cmp not in comp:
            bad.append(F("G-T2", f"§6.1 does not list {cmp}", "spec", sec))
    return bad


def g_comp2(t: Texts) -> list[Finding]:
    """R2 BQ-15: §6.1 re-cites each component at its `15` heading at the v2 base and lists D07's
    composition records for the band's screens, by id, exactly."""
    body, sec = v2_body(t, COMP2_HEAD)
    heads = {
        m[1]: i
        for i, ln in enumerate(base_lines("15", BASE_V2), 1)
        if (m := re.match(r"^### (CMP-\d{3}) ", ln))
    }
    comp_json = git_show(BASE_V2, "docs/design/E09/E09-D07-composition.json") or "{}"
    records = json.loads(comp_json).get("records", [])
    band = {*BAND, "SCR-112"}
    by: dict[str, list[str]] = {}
    for rec in records if isinstance(records, list) else []:
        if isinstance(rec, dict) and rec.get("screen") in band:
            by.setdefault(str(rec.get("component")), []).append(str(rec.get("id")))
    bad: list[Finding] = []
    for r in table_rows(body):
        if len(r) != 4:
            continue
        cmp = r[0].split()[0]
        if heads.get(cmp) != int(r[1].lstrip(":") or 0):
            bad.append(F("G-COMP2", f"§6.1 {cmp} is not at `15`:{r[1]}", "spec", sec))
        want = by.get(cmp, [])
        got = re.findall(r"R-\d+", r[3])
        if got != want:
            bad.append(F("G-COMP2", f"§6.1 {cmp}'s records are not D07's {want}", "spec", sec))
    return bad


def g_contrast2(t: Texts) -> list[Finding]:
    """R2 BQ-16: §7.4 names exactly the pairs below their bar at the v2 base (none: "none") and
    exactly those below it under a simulation, routed to a Q-row of §14.1."""
    body, sec = v2_body(t, PAIRS2_HEAD)
    below, sim = v2_below(t.spec)
    bad: list[Finding] = []
    head = body.split("**Under simulation", 1)[0].split("**Below the bar", 1)[-1]
    named = re.findall(r"\b(P-\d+ (?:dark|light|hc))\b", head)
    if sorted(named) != sorted(below) or (not below and "none" not in head):
        bad.append(F("G-CONTRAST2", f"below the bar {below}, named {named}", "spec", sec))
    tail = body.split("**Under simulation", 1)[-1]
    named_sim = re.findall(
        r"\b(P-\d+ (?:dark|light|hc) (?:protanopia|deuteranopia|tritanopia|greyscale))", tail
    )
    if sorted(named_sim) != sorted(sim):
        bad.append(F("G-CONTRAST2", f"under simulation {sim}, named {named_sim}", "spec", sec))
    route = re.search(r"carried as (Q-\d+)", tail)
    qids = {r[0] for r in rows_of(t.spec, QROW2_HEAD)}
    if sim and (route is None or route[1] not in qids):
        bad.append(F("G-CONTRAST2", "the shortfall is not carried to a §14.1 Q-row", "spec", sec))
    if "Machado 2009" not in body or "linear-sRGB" not in body:
        bad.append(F("G-CONTRAST2", "§7.4 does not state the simulation applied", "spec", sec))
    return bad


def g_deck2(t: Texts) -> list[Finding]:
    """R2 BQ-11: the re-keyed entries hold D10's copy of record (D10:517, :518) with C-25; a
    superseded entry names its §15.4 C-row; the frozen set's entries are v1's byte for byte."""
    strings = deck_strings(t.deck)
    lines = base_lines("D10", BASE_V2)
    record = {
        "lock.wrong_password": " ".join(quoted(lines[516])),
        "lock.expired.announce": " ".join(quoted(lines[517])),
    }
    crows = {r[0] for r in rows_of(t.spec, CROW2_HEAD)}
    bad: list[Finding] = []
    for key, want in record.items():
        e = strings.get(key, {})
        if e.get("string") != want or "C-25" not in str(e.get("notes", "")):
            bad.append(F("G-DECK2", f"{key} is not D10's copy of record with C-25", "deck", key))
    for key, e in strings.items():
        st = str(e.get("status", ""))
        m = re.fullmatch(r"superseded \((C-\d+)\)", st)
        if st.startswith("superseded") and (m is None or m[1] not in crows):
            bad.append(F("G-DECK2", f"{key} is superseded without its C-row", "deck", key))
    return bad


def g_frozen_stable(t: Texts) -> list[Finding]:
    """R2 BQ-27: every deck entry with a `security` cell is v1's entry byte for byte (a NOTE
    where another gate flags the same entry)."""
    old = v1_deck()
    bad: list[Finding] = []
    for key, e in deck_strings(t.deck).items():
        held = "security" in e or "security" in old.get(key, {})
        if held and json.dumps(e, sort_keys=True) != json.dumps(old.get(key), sort_keys=True):
            bad.append(F("G-FROZEN-STABLE", f"{key} differs from v1's entry", "deck", key))
    return bad


def g_outside(t: Texts) -> list[Finding]:
    """R2 BQ-26: §16.4's Outside cells are empty, or carry the deputy's dated record."""
    body, sec = v2_body(t, OUTSIDE_HEAD)
    bad: list[Finding] = []
    rows = [r for r in table_rows(body) if len(r) == 5]
    if len(rows) < 6:
        bad.append(F("G-OUTSIDE", "§16.4's table is short of the six steps", "spec", sec))
    for r in rows:
        for cell in r[3:5]:
            if cell and not DEPUTY.search(cell):
                bad.append(
                    F("G-OUTSIDE", f"§16.4 step {r[0]}: an Outside cell filled", "spec", sec)
                )
    for need in ("the orchestrator's deputy", "never fills", "no session took place"):
        if need not in norm_text(body):
            bad.append(F("G-OUTSIDE", f"§16.4 lacks {need!r}", "spec", sec))
    return bad


def g_4743(t: Texts) -> list[Finding]:
    """R2 (BQ-25 delegation): #4743 is closed; the web Lock-now leg is G-15's, the E09 frontend
    lane's, and #291's list names the same owner."""
    body, sec = v2_body(t, AHEAD2_HEAD)
    bad: list[Finding] = []
    row = next((r for r in table_rows(body) if r[0].startswith("#4743")), [])
    cell = row[-1] if row else ""
    if "#4743 is closed" not in cell or "G-15" not in cell or "#291" not in cell:
        bad.append(F("G-4743", "§13.1's #4743 row is not R2's", "spec", sec))
    g15 = next((r for r in rows_of(t.spec, GROW2_HEAD) if r[0] == "G-15"), [])
    if len(g15) < 4 or g15[3] != "the E09 frontend lane" or "#291" not in g15[1]:
        bad.append(F("G-4743", "G-15 is not the E09 frontend lane's, with #291", "spec", sec))
    return bad


def g_story(t: Texts) -> list[Finding]:
    """R2 BQ-23: §16.0 has one row per consumer; its T-, SR- and AS- ids are D10's."""
    body, sec = v2_body(t, STORY_HEAD)
    rows = [r for r in table_rows(body) if len(r) == 5]
    bad: list[Finding] = []
    if sorted(r[0] for r in rows) != sorted(STORY_CONSUMERS):
        bad.append(F("G-STORY", "§16.0's consumers are not the pack's", "spec", sec))
    known = {
        **d10_rows(*D10_MAP, "T-"),
        **d10_rows(*D10_SCRIPT, "SR-"),
        **d10_rows(*D10_ASSERT, "AS-"),
    }
    for r in rows:
        for prefix in ("T", "SR", "AS"):
            for x in id_span(r[3], prefix):
                if x not in known:
                    bad.append(F("G-STORY", f"§16.0 {r[0]}: {x} is not D10's", "spec", sec))
    return bad


def g_arows2(t: Texts) -> list[Finding]:
    """R2 BQ-29: §15.6 gives each of v1's A-rows a status read at the v2 base, with its cite."""
    body, sec = v2_body(t, AROW2_HEAD)
    bad: list[Finding] = []
    for r in table_rows(body):
        if len(r) != 4:
            continue
        if not re.fullmatch(r"A-(?:[2-9]|1[01])", r[0]):
            bad.append(F("G-AROWS2", f"§15.6 {r[0]} is not an A-row id", "spec", sec))
        if not any(r[2].startswith(s) for s in A_STATUS) or not cite_refs(r[2]):
            bad.append(F("G-AROWS2", f"§15.6 {r[0]}: no status with its cite", "spec", sec))
    return bad


def g_rows2(t: Texts) -> list[Finding]:
    """R2 BQ-29: new ids continue each series; the rows v2 closes are closed by new rows, the old
    rows byte-stable."""
    bad: list[Finding] = []
    series = ((CROW2_HEAD, "C", 25), (QROW2_HEAD, "Q", 12))
    for head, prefix, first in series:
        ids = [r[0] for r in rows_of(t.spec, head) if re.fullmatch(rf"{prefix}-\d+", r[0])]
        want = [f"{prefix}-{n}" for n in range(first, first + len(ids))]
        if ids != want:
            bad.append(F("G-ROWS2", f"{head[:5]}'s ids are not {want}", "spec", spec_sec(t, head)))
    new_g = [r[0] for r in rows_of(t.spec, GROW2_HEAD) if r[0] not in ("G-1", "G-10")]
    if new_g != ["G-14", "G-15"]:
        bad.append(
            F("G-ROWS2", "§15.5's new ids are not G-14, G-15", "spec", spec_sec(t, GROW2_HEAD))
        )
    whole = norm_text("\n".join(section(t.spec, h) for h in (CROW2_HEAD, GROW2_HEAD, QROW2_HEAD)))
    for need in ("c 24 closed", "c 11 closed", "g 10", "q 9 and q 10"):
        if need not in whole:
            bad.append(F("G-ROWS2", f"no v2 row closes {need!r}", "spec", spec_sec(t, CROW2_HEAD)))
    return bad


V2_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_register,
    g_delta,
    g_cited_stable,
    g_drift,
    g_mode,
    g_parents,
    g_lift,
    g_ops2,
    g_errmap2,
    g_crosswalk,
    g_findings,
    g_announcer,
    g_t2,
    g_comp2,
    g_contrast2,
    g_deck2,
    g_outside,
    g_4743,
    g_story,
    g_arows2,
    g_rows2,
)


# ---------------------------------------------------------------------------- the audit


def g_trust(t: Texts) -> list[Finding]:
    """RULED BQ-15: no trust-device control, and no device-trust period or keep-signed-in box."""
    return [*g_trust_a(t), *g_trust_b(t)]


def g_disable(t: Texts) -> list[Finding]:
    """RULED BQ-18: no disable-two-factor control, and no step-up or typed phrase on removal."""
    return [*g_disable_a(t), *g_disable_b(t)]


LEXICON_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_close,
    g_charset,
    g_cells,
    g_comment,
    g_penpot,
    g_entropy,
    g_handref,
    g_newcmp,
    g_quote,
    g_badge,
    g_footer,
    g_uniform,
    g_countdown,
    g_trust,
    g_recovery,
    g_disable,
    g_reason,
    g_invite,
    g_exhaust,
    g_session,
    g_confirm,
    g_attempts,
    g_grace,
    g_trace,
    g_shape,
    g_bold,
)
MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_ruled,
    g_ops,
    g_fields,
    g_errmap,
    g_fallback,
    g_frame,
    g_comp,
    g_status,
    g_tokens,
    g_contrast,
    g_cvd,
    g_deck,
    g_deckkey,
    g_frozen,
    g_never,
    g_fold,
    g_edge,
    g_crows,
    g_grows,
    g_qrows,
    g_arows,
    g_walk,
    g_ahead,
    g_deviations,
    g_publish,
    g_locked,
    g_a11y,
    g_motion,
    g_assets,
    g_untouched,
    g_version,
    g_budget,
)
DOC_GATES = ("G-ANCHOR", "G-WORDCOUNT", "G-MARKER", "G-HEX", "G-CITE", "G-RULED-PIN")


WHOLE_SPEC_GATES = (g_budget, g_edge)


def audit(t: Texts) -> tuple[list[str], list[str], list[str], int]:
    """(FAIL lines, NOTE lines, WARN lines, cites checked). One FAIL line per gate; a pin or a
    G-V1-FROZEN finding in a section another gate already FAILs is demoted to a NOTE line. The
    v1 gates read the v1 view; the lexicon, document, cite, pin and v2 gates the whole spec."""
    WARNS.clear()
    found: list[Finding] = []
    v = t.vals
    v1t = Texts(v1_view(t.spec), t.deck, t.plans, t.values)
    found += g_anchor_doc(t.spec, v)
    found += g_wordcount_doc(t.spec, v)
    found += g_marker_doc(t.spec, v)
    found += g_hex_doc(t.spec)
    for gate in LEXICON_GATES:
        found += gate(t)
    cf, n = cite_findings(t)
    found += cf
    for gate in MEASURED_GATES:
        found += gate(t if gate in WHOLE_SPEC_GATES else v1t)
    for gate in V2_GATES:
        found += gate(t)
    flagged = {(f[2], f[3]) for f in found if f[2] is not None}
    pins = pin_findings(t)
    notes = [f"NOTE [{p[0]}] {p[1][:150]}" for p in pins if (p[2], p[3]) in flagged]
    found += [p for p in pins if (p[2], p[3]) not in flagged]
    flagged |= {(p[2], p[3]) for p in pins if p[2] is not None}
    held = [*g_v1_frozen(t), *g_frozen_stable(t)]
    notes += [f"NOTE [{p[0]}] {p[1][:150]}" for p in held if (p[2], p[3]) in flagged]
    found += [p for p in held if (p[2], p[3]) not in flagged]
    merged: dict[str, list[str]] = {}
    for tag, msg, _d, _s in found:
        merged.setdefault(tag, []).append(msg)
    fails = []
    for tag, msgs in merged.items():
        msgs = list(dict.fromkeys(msgs))
        more = f" (+{len(msgs) - 4} more)" if len(msgs) > 4 else ""
        fails.append(f"[{tag}] " + "; ".join(m[:150] for m in msgs[:4]) + more)
    return fails, notes, list(dict.fromkeys(WARNS)), n


# ---------------------------------------------------------------------------- self-test

Edit = Callable[[str], str]


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str  # "" = a probe that must trip nothing
    what: str
    spec: Edit | None = None
    deck: Edit | None = None
    lever: Callable[[], Callable[[], None]] | None = None
    repin: bool = False  # v2's Y-n and Z-n: re-pinned, so only a content gate may catch them
    warns: int = 0  # the new WARN lines a probe (gate "") must add


def sub(old: str, new: str, count: int = 1) -> Edit:
    def run(text: str) -> str:
        return text.replace(old, new, count) if old in text else text

    return run


def after_line(prefix: str, extra: str) -> Edit:
    """Insert `extra` as a new line after the first line starting with `prefix`."""

    def run(text: str) -> str:
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith(prefix):
                return "\n".join([*lines[: i + 1], extra, *lines[i + 1 :]])
        return text

    return run


def drop_line(prefix: str) -> Edit:
    def run(text: str) -> str:
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith(prefix):
                return "\n".join([*lines[:i], *lines[i + 1 :]])
        return text

    return run


def deck_edit(fn: Callable[[dict[str, object]], None]) -> Edit:
    def run(text: str) -> str:
        data = json.loads(text)
        fn(data)
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    return run


def deck_set(key: str, fld: str, value: object) -> Edit:
    def fn(data: dict[str, object]) -> None:
        strings = data["strings"]
        assert isinstance(strings, dict)
        if value is None:
            strings[key].pop(fld, None)
        else:
            strings[key][fld] = value

    return deck_edit(fn)


def deck_drop(key: str) -> Edit:
    def fn(data: dict[str, object]) -> None:
        strings = data["strings"]
        assert isinstance(strings, dict)
        strings.pop(key, None)

    return deck_edit(fn)


def popper[T](lst: list[T]) -> Callable[[], None]:
    """The undo of a self-test lever: pop what the lever pushed."""

    def run() -> None:
        lst.pop()

    return run


def ascii_line(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "replace").decode("ascii")


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(x.encode("utf-8")).hexdigest() for x in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "-" for p in paths]


def write_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def report(line: str) -> str:
    """One self-test report line: ASCII, at most REPORT_WIDTH characters."""
    return ascii_line(line)[:REPORT_WIDTH]


def plan_paths() -> tuple[tuple[str, Path], ...]:
    out = []
    for nn in (*UNTOUCHED, *UNTOUCHED_DOCS):
        rel = cite_path(nn)
        if rel is None:
            raise SystemExit(f"FAIL parse: {nn} has no path")
        out.append((nn, ROOT / rel))
    return tuple(out)


def read_plans() -> tuple[tuple[str, str], ...]:
    return tuple((nn, p.read_bytes().decode("utf-8")) for nn, p in plan_paths())


def cell_set(key: str, col: int, value: str, key_col: int = 0) -> Edit:
    """Set cell `col` of the first table row whose cell `key_col` reads `key` (padding-proof)."""

    def run(text: str) -> str:
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("|") and not is_rule(ln):
                cells = split_row(ln)
                if len(cells) > max(col, key_col) and cells[key_col] == key:
                    cells[col] = value
                    lines[i] = "| " + " | ".join(cells) + " |"
                    return "\n".join(lines)
        return text

    return run


def drop_row(key: str, key_col: int = 0) -> Edit:
    """Drop the first table row whose cell `key_col` starts with `key`."""

    def run(text: str) -> str:
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            cells = split_row(ln) if ln.startswith("|") and not is_rule(ln) else []
            if len(cells) > key_col and cells[key_col].startswith(key):
                return "\n".join([*lines[:i], *lines[i + 1 :]])
        return text

    return run


def swap_lines(text: str, a: str, b: str) -> str:
    """Swap the first lines starting with `a` and with `b`."""
    lines = text.split("\n")
    ia = next((i for i, ln in enumerate(lines) if ln.startswith(a)), None)
    ib = next((i for i, ln in enumerate(lines) if ln.startswith(b)), None)
    if ia is None or ib is None:
        return text
    lines[ia], lines[ib] = lines[ib], lines[ia]
    return "\n".join(lines)


def lever_drift() -> Callable[[], None]:
    DRIFT.append(("docs/plan/14-screens-catalogue.md", 147, "- **Performance:** changed."))
    return popper(DRIFT)


def lever_extra() -> Callable[[], None]:
    EXTRA_PATHS.append("docs/plan/15-component-catalogue.md")
    return popper(EXTRA_PATHS)


def plan_text(nn: str) -> str:
    return dict(read_plans()).get(nn, "")


def lever_pointer_missing() -> Callable[[], None]:
    PLAN_OVERRIDE.append(("14", plan_text("14").replace(POINTER_14 + "\n", "", 1)))
    return popper(PLAN_OVERRIDE)


def lever_plan_edit() -> Callable[[], None]:
    text = plan_text("14").replace("first paint ≤1 s cold", "first paint ≤2 s cold", 1)
    PLAN_OVERRIDE.append(("14", text))
    return popper(PLAN_OVERRIDE)


def lever_git() -> Callable[[], None]:
    BROKEN.append("git")
    return popper(BROKEN)


def lever_cvd() -> Callable[[], None]:
    drifted = dict(own_cvd_constants())
    drifted["protanopia"] = (0.0, 2.0, -2.5, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    CVD_OVERRIDE.append(drifted)
    return popper(CVD_OVERRIDE)


def lever_pins_damaged() -> Callable[[], None]:
    text = pin_file_text() or ""
    PIN_TEXT_OVERRIDE.append(text.replace("units.", "units (damaged).", 1) + "x\ty\n")
    return popper(PIN_TEXT_OVERRIDE)


def lever_merge_base() -> Callable[[], None]:
    BROKEN.append("merge-base")
    return popper(BROKEN)


def lever_drift_v2() -> Callable[[], None]:
    """A range a v2 line cites (`22`:1832, §0.1) edited at `origin/main`."""
    DRIFT.append(("docs/plan/22-api-openapi.yaml", 1832, "      operationId: authLockNow"))
    return popper(DRIFT)


def both(*edits: Edit) -> Edit:
    def run(text: str) -> str:
        for e in edits:
            text = e(text)
        return text

    return run


def deck_meta(fld: str, value: str) -> Edit:
    def fn(data: dict[str, object]) -> None:
        data[fld] = value

    return deck_edit(fn)


# built at run time so the source holds no scanner-shaped literal
ENTROPY_PROBE = (
    "The fixture uses "
    + "api"
    + chr(95)
    + "key"
    + ": "
    + "".join(reversed("6tK4mN8bV2pL7wQ9xZ"))
    + "."
)
STATUS_004 = "SCR-004 (R-007) and the SCR-112 password"
S51 = "- **Fields:** one identifier field labelled"
S52 = "- CMP-204 as one labelled input;"
S59 = "- **Password:** E09-D05 (§5.4)."
S57 = "**One invalid-invite state**"
S58 = "The task set is `22`'s enum"
S53 = "- States as D04 §3 lists"
S56 = "D06's frames bound to `authStepUp`"
# a v2 line: the N-n probes land in a v2 block, where a v1 line added would be G-V1-FROZEN's
S510 = "- **SCR-002 and SCR-006** (R2 BQ-22)"
MUTATIONS = (
    Mutation(
        "M-1",
        "G-ANCHOR",
        "a budget typed over its anchor",
        spec=sub("≤ 1<!--=CITE:perf.scr001-->", "≤ 2<!--=CITE:perf.scr001-->"),
    ),
    Mutation(
        "M-2",
        "G-ANCHOR",
        "a figure typed by hand",
        spec=after_line(S56, "The dialog waits 30 seconds."),
    ),
    Mutation(
        "M-3",
        "G-WORDCOUNT",
        "a count as a word",
        spec=after_line(S56, "The dialog has three states."),
    ),
    Mutation(
        "M-4",
        "G-MARKER",
        "a hidden comment",
        spec=sub("The task set is `22`'s enum", "The task set <!-- hidden --> is `22`'s enum"),
    ),
    Mutation(
        "M-5",
        "G-COMMENT",
        "a link-reference comment",
        spec=after_line(S58, "\n[//]: # (a hidden note)"),
    ),
    Mutation(
        "M-6",
        "G-HEX",
        "a hex outside §7.1",
        spec=sub("so no state rests on hue.", "so no state rests on hue (#e8eaed)."),
    ),
    Mutation(
        "M-7", "G-CHARSET", "a Cyrillic homoglyph", spec=sub("The task set is", "The tаsk set is")
    ),
    Mutation("M-8", "G-CELLS", "a row with an extra cell", spec=cell_set("C-21", 1, "x | D04:107")),
    Mutation(
        "M-9",
        "G-CLOSE",
        "a closing keyword",
        spec=sub("the closing version (R2 BQ-01)", "the closing version, closes #194 (R2 BQ-01)"),
    ),
    Mutation(
        "M-10",
        "G-QUOTE",
        "an unsourced quote",
        spec=after_line(S56, 'The dialog reads "Please confirm this sensitive action now".'),
    ),
    Mutation(
        "M-11",
        "G-PENPOT",
        "a Penpot URL",
        spec=after_line(S56, "See https://penpot.example.org/page."),
    ),
    Mutation("M-12", "G-ENTROPY", "a high-entropy key value", spec=after_line(S56, ENTROPY_PROBE)),
    Mutation("M-13", "G-BUDGET", "past the line budget", spec=lambda s: s + "\n" * 60),
    Mutation(
        "M-14",
        "G-HANDREF",
        "a hand-off file of this pack",
        spec=after_line(S56, "Its rows are in `docs/design/E09/E09-D12-handoff.md`."),
    ),
    Mutation(
        "M-15",
        "G-NEWCMP",
        "a component not in `15`",
        spec=after_line(S56, "The grace chip is CMP-299."),
    ),
    Mutation(
        "M-16",
        "G-CITE",
        "a cite past the file",
        spec=sub("(a task needs a key first, `14`:47)", "(a task needs a key first, `14`:99999)"),
    ),
    Mutation("M-17", "G-VERSION", "a cited line edited at origin/main", lever=lever_drift),
    Mutation(
        "M-18",
        "G-VERSION",
        "a sha dropped from the version line",
        spec=sub(
            "E09-D04 #1440 `9750dc4bc9` and #1470 `3669e891e6`;", "E09-D04 #1440 `9750dc4bc9`;"
        ),
    ),
    Mutation("M-19", "G-UNTOUCHED", "a plan file changed", lever=lever_extra),
    Mutation("M-20", "G-UNTOUCHED", "no merge-base", lever=lever_merge_base),
    Mutation(
        "M-21",
        "G-RULED",
        "a ruled word paraphrased",
        spec=sub("**v1 has no in-product password recovery** —", "**v1 offers no recovery yet** —"),
    ),
    Mutation(
        "M-22",
        "G-RULED",
        "a ruled-differently id dropped",
        spec=sub(
            "— BQ-3, BQ-14, BQ-15, BQ-18, BQ-19, BQ-39 (each",
            "— BQ-3, BQ-14, BQ-15, BQ-18, BQ-39 (each",
        ),
    ),
    Mutation(
        "M-23",
        "G-OPS",
        "an operation's path",
        spec=cell_set("`authUnlock`", 1, "POST `/auth/unlocks`"),
    ),
    Mutation("M-24", "G-OPS", "a ticket column", spec=cell_set("`listMySessions`", 4, "added")),
    Mutation("M-25", "G-FIELDS", "a screen's field row dropped", spec=drop_row("task, state", 1)),
    Mutation(
        "M-26",
        "G-ERRMAP",
        "a failure with its own key",
        spec=cell_set("disabled account", 3, "`auth.unreachable`"),
    ),
    Mutation(
        "M-27",
        "G-FALLBACK",
        "a fallback without its reason",
        spec=sub(": the server's `detail` is never rendered (S03:67).", "."),
    ),
    Mutation(
        "M-28",
        "G-BADGE",
        "a badge before sign-in",
        spec=after_line(S51, "- Before sign-in the card shows the server's environment badge."),
    ),
    Mutation(
        "M-29",
        "G-FOOTER",
        "the commit in the pre-auth footer",
        spec=after_line(S51, "- The footer shows the commit before sign-in."),
    ),
    Mutation(
        "M-30",
        "G-UNIFORM",
        "a disabled message at sign-in",
        spec=after_line(S51, "- A disabled account sees its own disabled message at sign-in."),
    ),
    Mutation(
        "M-31",
        "G-COUNTDOWN",
        "a countdown from the lock",
        spec=after_line(S51, "- The countdown runs from the account lock."),
    ),
    Mutation(
        "M-32",
        "G-TRUST",
        "a trust-device checkbox",
        spec=after_line(S52, "- The trust this device checkbox is shown."),
    ),
    Mutation(
        "M-33",
        "G-RECOVERY",
        "a forgot-password link",
        spec=after_line(S51, "- SCR-001 offers a forgot password link."),
    ),
    Mutation(
        "M-34",
        "G-DISABLE",
        "a disable-two-factor button",
        spec=after_line(S59, "- SCR-112 shows a disable two-factor button."),
    ),
    Mutation(
        "M-35",
        "G-DISABLE",
        "a step-up on removing a method",
        spec=after_line(S59, "- Removing a method asks for a step-up."),
    ),
    Mutation(
        "M-36",
        "G-REASON",
        "the server's free text rendered",
        spec=after_line(S58, "The card shows the server's free-text reason."),
    ),
    Mutation(
        "M-37",
        "G-INVITE",
        "a distinct expired-invite message",
        spec=after_line(S57, "SCR-017 shows a distinct expired invitation message."),
    ),
    Mutation(
        "M-38",
        "G-EXHAUST",
        "the remaining count built",
        spec=after_line(S53, "- SCR-003 shows the N of 10 count."),
    ),
    Mutation(
        "M-39",
        "G-SESSION",
        "a session claimed",
        spec=after_line(S56, "The walkthrough was held with the frontend engineers."),
    ),
    Mutation(
        "M-69",
        "G-CONFIRM",
        "a disabled Confirm",
        spec=after_line(S56, "Confirm stays disabled until both fields are valid."),
    ),
    Mutation(
        "M-70",
        "G-ATTEMPTS",
        "an attempt count shown",
        spec=after_line(S52, "- SCR-002 shows the attempts left."),
    ),
    Mutation(
        "M-40", "G-TRACE", "a US-AUTH trace", spec=after_line(S56, "It traces to US-AUTH-008.")
    ),
    Mutation(
        "M-41",
        "G-FRAME",
        "a PNG that does not exist",
        spec=sub("`E09-D06-SCR-006-code-only.png`", "`E09-D06-SCR-006-code-only-x.png`"),
    ),
    Mutation(
        "M-42", "G-FRAME", "SCR-004's pending line dropped", spec=cell_set("SCR-004", 4, "pending")
    ),
    Mutation(
        "M-43",
        "G-COMP",
        "a Storybook cell reads built",
        spec=cell_set("CMP-205 QrCode", 3, "Default, built"),
    ),
    Mutation(
        "M-44", "G-STATUS", "the unmounted route unsaid", spec=cell_set(STATUS_004, 2, "interim")
    ),
    Mutation(
        "M-45",
        "G-TOKENS",
        "an unshipped token",
        spec=sub(
            "Token **names** only, resolved",
            "Token **names** only (`color.surface.card`), resolved",
        ),
    ),
    Mutation(
        "M-46",
        "G-CONTRAST",
        "a shortfall not named",
        spec=sub("P-3 in light, P-4 in light and P-5 in light:", "P-3 in light and P-4 in light:"),
    ),
    Mutation("M-47", "G-CVD", "the CVD constants drifted", lever=lever_cvd),
    Mutation(
        "M-48",
        "G-DECK",
        "a verbatim string reworded",
        deck=deck_set("auth.mfa.verify", "string", "Verify now"),
    ),
    Mutation(
        "M-49",
        "G-DECK",
        "a new string not PROPOSED",
        deck=deck_set("auth.recovery.label", "status", "merged"),
    ),
    Mutation(
        "M-50",
        "G-FROZEN",
        "a hook's security flag dropped",
        deck=deck_set("enrol.codes.once", "security", None),
    ),
    Mutation(
        "M-51",
        "G-FROZEN",
        "the RULED invite sentence reworded",
        deck=deck_set(
            "invite.invalid", "string", "This invitation expired. Ask the owner for a new one."
        ),
    ),
    Mutation("M-52", "G-CROWS", "a C-row used, not defined", spec=after_line(S56, "See C-99.")),
    Mutation("M-53", "G-GROWS", "a G-row not due at once", spec=cell_set("G-2", 4, "2026-11-30")),
    Mutation(
        "M-54", "G-QROWS", "an agent as owner", spec=cell_set("Q-5", 3, "the worker on #2701")
    ),
    Mutation(
        "M-55",
        "G-AROWS",
        "an A-row target lost",
        spec=sub("| A-3  | `05` Demo vs Live;", "| A-3  | the a11y Demo vs Live;"),
    ),
    Mutation(
        "M-56", "G-WALK", "a dry-run sum broken", spec=cell_set("story: #2711 (SCR-002)", 2, "7", 1)
    ),
    Mutation(
        "M-57",
        "G-WALK",
        "a not-found left uncarried",
        spec=cell_set("QA: E09-Q06 (#297)", 5, "an exhaustion signal", 1),
    ),
    Mutation(
        "M-58",
        "G-AHEAD",
        "a waiver date changed",
        spec=cell_set("#2711 (SCR-002)", 4, "waived 2026-10-30 (R194 BQ-35)"),
    ),
    Mutation(
        "M-59",
        "G-DEVIATIONS",
        "a label changed",
        spec=sub("`design`, `handoff`, `a11y`", "`design`, `hand-off`, `a11y`"),
    ),
    Mutation(
        "M-60",
        "G-PUBLISH",
        "a consumer not named",
        spec=sub("#193, #190, #2490: the pack's path", "#193, #190: the pack's path"),
    ),
    Mutation("M-61", "G-LOCKED", "a locked-input row dropped", spec=drop_row("L1-7, L1-8", 1)),
    Mutation(
        "M-62",
        "G-A11Y",
        "the criteria made advisory",
        spec=sub(
            "Definition of Done, `02`:67, not advisory)", "Definition of Done, `02`:67, advisory)"
        ),
    ),
    Mutation(
        "M-63",
        "G-MOTION",
        "a forbidden technique dropped",
        spec=sub("looping motion on an error; ", ""),
    ),
    Mutation(
        "M-64",
        "G-ASSETS",
        "the ruled filename changed",
        spec=sub("filename `candleviewer-recovery-codes.txt`", "filename `recovery-codes.txt`"),
    ),
    Mutation(
        "M-65",
        "G-RULED-PIN",
        "a sentence reworded where no other gate reads",
        spec=sub("The band adds its own controls:", "The band adds these controls:"),
    ),
    Mutation("M-66", "G-RULED-PIN", "a deck entry deleted", deck=deck_drop("auth.retry")),
    Mutation("M-67", "G-RULED-PIN", "the pins file damaged", lever=lever_pins_damaged),
    Mutation(
        "M-68",
        "G-RULED-PIN",
        "two table rows swapped",
        spec=lambda s: swap_lines(s, "| CMP-043 Dialog", "| CMP-044 ConfirmDialog"),
    ),
    # the folds of the lens findings (each FOLDS text paraphrased; one more per new gate)
    *(
        Mutation(f"M-{71 + i}", "G-FOLD", what, spec=sub(needle, alt))
        for i, (_h, needle, what, alt) in enumerate(FOLDS)
    ),
    Mutation(
        "M-88",
        "G-FOLD",
        "a registered audit name dropped",
        spec=sub("`auth.csrf_refused` (ACT:55)", "the refusal (ACT:55)"),
    ),
    Mutation("M-89", "G-FOLD", "a band condition dropped", spec=drop_row("invite rate limited")),
    Mutation(
        "M-90",
        "G-ASSETS",
        "the ruled ten codes dropped (BQ-34)",
        spec=sub(
            "the 10<!--=RULED:file.codes--> codes in display order", "the codes in display order"
        ),
    ),
    Mutation(
        "M-91",
        "G-COMP",
        "a component not by `15`'s name (BQ-28)",
        spec=sub("| CMP-097 OnboardingChecklist", "| CMP-097 Checklist"),
    ),
    Mutation(
        "M-92",
        "G-DECKKEY",
        "a coined key marked merged (BQ-26)",
        deck=deck_set("enrol.done", "key_status", "merged"),
    ),
    Mutation(
        "M-93",
        "G-DECKKEY",
        "a coined namespace not recorded (BQ-26)",
        spec=sub("`enrol.*`, ", ""),
    ),
    Mutation(
        "M-94",
        "G-DECK",
        "an S03 §4.2 row without its entry (BQ-26)",
        deck=deck_set("sessions.columns", "source", "S03:154"),
    ),
    Mutation(
        "M-95",
        "G-DECK",
        "the unserved re-enrol entry not held",
        deck=deck_set("twofactor.reenrol", "status", "merged"),
    ),
    Mutation(
        "M-96",
        "G-GROWS",
        "the stale acknowledgement marker kept (D7)",
        spec=sub("| G-12 | ", "| G-12 | new, for the orchestrator's acknowledgement: "),
    ),
    Mutation("M-97", "G-UNTOUCHED", "a BQ-40 pointer line missing", lever=lever_pointer_missing),
    Mutation("M-98", "G-UNTOUCHED", "`14` edited past the pointer lines", lever=lever_plan_edit),
    Mutation("M-99", "G-UNTOUCHED", "a git call fails", lever=lever_git),
    Mutation(
        "M-100",
        "G-AROWS",
        "the pointer turned back into an A-row",
        spec=after_line("| A-2 ", "| A-11 | `14` SCR-001 | Hand-off pack line | the `14` owner |"),
    ),
    Mutation(
        "M-101",
        "G-EDGE",
        "a fix-direction wording returns (round 1 P-1)",
        spec=after_line(S51, "- Until the server aligns, the client keeps its generic wording."),
    ),
    # X-n: paraphrases, re-pinned, so only the lexicon gate may catch them
    Mutation(
        "X-1",
        "G-BADGE",
        "pre-auth DEMO pill",
        spec=after_line(S51, "- Pre-auth, the login card carries a DEMO pill."),
    ),
    Mutation(
        "X-2",
        "G-TRUST",
        "a remember-device toggle",
        spec=after_line(S52, "- SCR-002 offers a remember device toggle."),
    ),
    Mutation(
        "X-3",
        "G-RECOVERY",
        "a password reset path",
        spec=after_line(S51, "- The login page shows a password reset link."),
    ),
    Mutation(
        "X-4",
        "G-DISABLE",
        "turning off TOTP",
        spec=after_line(S59, "- A button lets the user turn off TOTP."),
    ),
    Mutation(
        "X-5",
        "G-UNIFORM",
        "a locked account banner",
        spec=after_line(S51, "- SCR-001 shows a locked account banner."),
    ),
    Mutation(
        "X-6",
        "G-REASON",
        "the raw reason displayed",
        spec=after_line(S58, "The checklist displays the raw reason text."),
    ),
    Mutation(
        "X-7",
        "G-INVITE",
        "separate invite states",
        spec=after_line(S57, "The wizard draws separate invitation states for each token."),
    ),
    Mutation(
        "X-8",
        "G-EXHAUST",
        "an exhaustion frame built",
        spec=after_line(S53, "- The exhaustion lockout is built and shown."),
    ),
    Mutation(
        "X-9",
        "G-FOOTER",
        "build info before sign-in",
        spec=after_line(S51, "- The pre-auth footer calls getBuildInfo for the build time."),
    ),
    Mutation(
        "X-10",
        "G-COUNTDOWN",
        "a client tally countdown",
        spec=after_line(S51, "- The countdown is a client-side tally of failures."),
    ),
    Mutation(
        "X-12",
        "G-CONFIRM",
        "Confirm greyed",
        spec=after_line(S56, "The step-up dialog's Confirm button starts greyed."),
    ),
    Mutation(
        "X-13",
        "G-ATTEMPTS",
        "two of five tries",
        spec=after_line(S52, "- The TOTP card displays the tries remaining."),
    ),
    Mutation(
        "X-11",
        "G-SESSION",
        "participants reported",
        spec=after_line(S56, "Participants reported no confusion."),
    ),
    # the lens-2 adversary's paraphrases that passed after a re-pin (A-, B-, P-n of its report)
    Mutation(
        "X-14",
        "G-BADGE",
        "A02 a DEMO / LIVE ribbon",
        spec=after_line(S51, "- The login page carries a DEMO / LIVE ribbon."),
    ),
    Mutation(
        "X-15",
        "G-BADGE",
        "A03 demo or live told before sign-in",
        spec=after_line(
            S51,
            "- Before authenticating, the page tells the user whether the server is demo or live.",
        ),
    ),
    Mutation(
        "X-16",
        "G-FOOTER",
        "A05 the source revision and the host",
        spec=after_line(S51, "- The pre-auth footer shows the source revision and the host."),
    ),
    Mutation(
        "X-17",
        "G-UNIFORM",
        "A06 a locked-account message in the States list",
        spec=sub(
            "`server-unreachable` with Retry.",
            "`server-unreachable` with Retry · a locked-account message on sign-in.",
        ),
    ),
    Mutation(
        "X-18",
        "G-UNIFORM",
        "A07 a locked user told so",
        spec=after_line(S51, "- On sign-in a locked user is told that the account is locked."),
    ),
    Mutation(
        "X-19",
        "G-COUNTDOWN",
        "A08 a client-side countdown in the States list",
        spec=sub(
            "`server-unreachable` with Retry.",
            "`server-unreachable` with Retry · a client-side countdown of the lockout.",
        ),
    ),
    Mutation(
        "X-20",
        "G-COUNTDOWN",
        "A09 a client timer until the lock lifts",
        spec=after_line(S51, "- SCR-001 runs a client timer that ticks until the lock lifts."),
    ),
    Mutation(
        "X-21",
        "G-TRUST",
        "A11 a keep-me-signed-in box",
        spec=after_line(S52, "- A keep-me-signed-in box ships on SCR-002 and posts the day count."),
    ),
    Mutation(
        "X-22",
        "G-DISABLE",
        "A15 a quoted Disable two-factor button",
        spec=after_line(S59, '- SCR-112 has a "Disable two-factor" button in v1.'),
    ),
    Mutation(
        "X-23",
        "G-DISABLE",
        "A16 a control that switches two-factor off",
        spec=after_line(S59, "- SCR-112 offers a control that switches two-factor off."),
    ),
    Mutation(
        "X-24",
        "G-DISABLE",
        "A18 a removal behind a fresh code",
        spec=after_line(
            S59,
            "- Removing a method goes through after the user re-proves identity with a fresh code.",
        ),
    ),
    Mutation(
        "X-25",
        "G-REASON",
        "A19 the negation dropped",
        spec=sub("**`reason` is never rendered raw**", "**`reason` is rendered raw**"),
    ),
    Mutation(
        "X-26",
        "G-REASON",
        "A20 the reason surfaced verbatim",
        spec=after_line(S58, "The server's `reason` is surfaced verbatim."),
    ),
    Mutation(
        "X-27",
        "G-INVITE",
        "A22 each token its own wording",
        spec=after_line(
            S57, "On SCR-017 each of expired, used and unknown invite tokens gets its own wording."
        ),
    ),
    Mutation(
        "X-28",
        "G-EXHAUST",
        "A24 the unused codes displayed",
        spec=after_line(S53, "- SCR-112 displays how many recovery codes are still unused."),
    ),
    Mutation(
        "X-29",
        "G-CONFIRM",
        "A26 Confirm cannot be pressed",
        spec=after_line(
            S56, "On the step-up dialog, Confirm cannot be pressed until every field is complete."
        ),
    ),
    Mutation(
        "X-30",
        "G-ATTEMPTS",
        "A28 how many wrong codes are left",
        spec=after_line(
            S52, "- The TOTP step tells the user how many more wrong codes lock the account."
        ),
    ),
    Mutation(
        "X-31",
        "G-RECOVERY",
        "A30 a flipped no-recovery",
        spec=after_line(S51, "- It is false that the band has no in-product password recovery."),
    ),
    Mutation(
        "X-32",
        "G-GRACE",
        "A31 a recent step-up covers Live enablement",
        spec=after_line(
            S56, "A recent step-up also covers Live enablement and kill-switch disable."
        ),
    ),
    Mutation(
        "X-33",
        "G-SESSION",
        "A41 the owner sat through it",
        spec=after_line(S56, "The owner sat through the walkthrough and found no gaps."),
    ),
    Mutation(
        "X-34",
        "G-TRUST",
        "A42 the permanent answer flipped",
        spec=sub(
            "Nothing; the control is not in v1 (§5.2).", "The day count from the checkbox (§5.2)."
        ),
    ),
    Mutation(
        "X-35",
        "G-DISABLE",
        "B04 a cite cannot exempt",
        spec=after_line(S59, "- SCR-112 shows a Disable two-factor button in v1 (R194)."),
    ),
    Mutation(
        "X-36",
        "G-TRUST",
        "B05 a far exemption cannot exempt",
        spec=after_line(
            S52,
            "- The trust this device control is built (held for nothing) and sends"
            " `remember_device_days`.",
        ),
    ),
    Mutation(
        "X-37",
        "G-INVITE",
        "B07 a used invite its own screen",
        spec=after_line(S57, "A used invite gets its own screen."),
    ),
    Mutation(
        "X-38",
        "G-FROZEN",
        "A32 frozen (5) inverted",
        spec=cell_set("(5)", 1, "a disabled control is the enforcement (D09:408)"),
    ),
    Mutation(
        "X-39",
        "G-FROZEN",
        "A33 frozen (7) property inverted",
        spec=cell_set("(7)", 2, "a token oracle is acceptable (`22`:12908)"),
    ),
    Mutation(
        "X-40",
        "G-FROZEN",
        "P09 frozen (3)'s deck security softened",
        deck=deck_set("enrol.codes.once", "security", "frozen (3): shown when convenient (SR-022)"),
    ),
    Mutation(
        "X-41",
        "G-NEVER",
        "B06 the never-list inverted",
        spec=sub("Never rendered or written:", "Always rendered as received:"),
    ),
    Mutation(
        "X-42",
        "G-SHAPE",
        "P02 a heading level changed",
        spec=sub("### 5.2 SCR-002 TOTP challenge", "#### 5.2 SCR-002 TOTP challenge"),
    ),
    Mutation(
        "X-43",
        "G-SHAPE",
        "P06 a line indented into code",
        spec=sub("\n**Every credential failure", "\n    **Every credential failure"),
    ),
    Mutation(
        "X-44",
        "G-BOLD",
        "P03 frozen (4)'s bold dropped",
        spec=sub(
            "**No grace for Live enablement and kill-switch disable**",
            "No grace for Live enablement and kill-switch disable",
        ),
    ),
    # Y-n: v2's gates, each mutation re-pinned so only its content gate may catch it
    Mutation(
        "Y-1",
        "G-V1-FROZEN",
        "a v1 sentence edited outside the register",
        spec=sub(
            "The band was built before most of its design",
            "The band was built before much of its design",
        ),
        repin=True,
    ),
    Mutation(
        "Y-2",
        "G-REGISTER",
        "an S row quotes a unit that does not stand",
        spec=sub(
            '"Below the bar (computed, not heuristic):"', '"Every failed sign-in gets one answer"'
        ),
        repin=True,
    ),
    Mutation(
        "Y-3",
        "G-DELTA",
        "a changed deck entry the register does not name",
        spec=cell_set("V-28", 1, "deck `lock.title`"),
        repin=True,
    ),
    Mutation(
        "Y-4",
        "G-CITED-STABLE",
        "a line E09-D07's tool cites changed under a C row",
        spec=both(
            sub(
                "below the text bar in light (§7.2); P-6",
                "below the text bar in light at v1 (§7.2); P-6",
            ),
            sub("| (top), v1 line 3 ", "| (top), v1 line 3 and v1 line 424 "),
        ),
        repin=True,
    ),
    Mutation(
        "Y-5",
        "G-DRIFT",
        "a §17.3 row for a range that is not edited",
        spec=after_line("| `04`:831 ", "| `05`:125 | `05`:125 | nothing changed | holds |"),
        repin=True,
    ),
    Mutation(
        "Y-6", "G-MODE", "the deck still reads v1", deck=deck_meta("version", "v1"), repin=True
    ),
    Mutation(
        "Y-7",
        "G-PARENTS",
        "a parent's sha is another PR's merge",
        spec=sub("#4963 `ccaad0fea6`", "#4963 `c3119e61e7`"),
        repin=True,
    ),
    Mutation(
        "Y-8",
        "G-LIFT",
        "a lifted range cut short",
        spec=sub("D10:590–635", "D10:590–630"),
        repin=True,
    ),
    Mutation(
        "Y-9",
        "G-OPS2",
        "the added operation's method changed",
        spec=sub("| `authLock` | POST `/auth/lock`", "| `authLock` | GET `/auth/lock`"),
        repin=True,
    ),
    Mutation(
        "Y-10",
        "G-ERRMAP2",
        "a fallback outside §4.2",
        spec=cell_set("locked account", 4, "F-9"),
        repin=True,
    ),
    Mutation(
        "Y-11",
        "G-CROSSWALK",
        "a focus target that is not D10's",
        spec=sub("| T-42        | SCR-005's password field", "| T-42        | SCR-005's dialog"),
        repin=True,
    ),
    Mutation(
        "Y-12",
        "G-FINDINGS",
        "a Blocker read closed",
        spec=cell_set("F-25", 4, "closed"),
        repin=True,
    ),
    Mutation(
        "Y-13",
        "G-ANNOUNCER",
        "a rule invented for the screens before sign-in",
        spec=after_line(
            "Signed-in screens write into", "The screens before sign-in own their own pair."
        ),
        repin=True,
    ),
    Mutation(
        "Y-14",
        "G-T2",
        "a T2 key D09 does not have",
        spec=sub("`rbac.owner_only` (D09:90)", "`rbac.owners_only` (D09:90)"),
        repin=True,
    ),
    Mutation(
        "Y-15",
        "G-COMP2",
        "a composition record that is not D07's",
        spec=sub("R-21, R-22, R-23", "R-21, R-22, R-24"),
        repin=True,
    ),
    Mutation(
        "Y-16",
        "G-CONTRAST2",
        "a pair named under simulation that keeps its bar",
        spec=sub(
            "simulation: P-6 dark protanopia,",
            "simulation: P-3 dark protanopia, P-6 dark protanopia,",
        ),
        repin=True,
    ),
    Mutation(
        "Y-17",
        "G-DECK2",
        "a re-keyed entry without C-25",
        deck=deck_set("lock.wrong_password", "notes", "D10's copy of record (D10:517)"),
        repin=True,
    ),
    Mutation(
        "Y-18",
        "G-FROZEN-STABLE",
        "a frozen-set entry changed",
        deck=deck_set("auth.login.failed", "notes", "a note"),
        repin=True,
    ),
    Mutation(
        "Y-19",
        "G-OUTSIDE",
        "an Outside cell filled here",
        spec=cell_set("1", 3, "found"),
        repin=True,
    ),
    Mutation(
        "Y-20",
        "G-4743",
        "#4743 read as open",
        spec=sub("#4743 is closed and the route", "#4743 is open and the route"),
        repin=True,
    ),
    Mutation(
        "Y-21",
        "G-STORY",
        "a script step D10 does not have",
        spec=sub("T-41 · SR-19 · AS-8", "T-41 · SR-99 · AS-8"),
        repin=True,
    ),
    Mutation(
        "Y-22",
        "G-AROWS2",
        "an A-row status outside the set",
        spec=sub("open: the remember line stands", "done: the remember line stands"),
        repin=True,
    ),
    Mutation(
        "Y-23",
        "G-ROWS2",
        "C-11 left open",
        spec=sub("| C-11 closed", "| C-11 still open"),
        repin=True,
    ),
    Mutation(
        "Y-24", "G-VERSION", "a v2 cite edited at origin/main", lever=lever_drift_v2, repin=True
    ),
    Mutation(
        "Y-25",
        "G-CITE",
        "a v2 cite past the file",
        spec=sub("(`22`:1835)", "(`22`:99999)"),
        repin=True,
    ),
    Mutation(
        "Y-26",
        "G-QUOTE",
        "an unsourced quote in a v2 block",
        spec=after_line(
            "- **SCR-002 and SCR-006** (R2 BQ-22)",
            'The dialog reads "Please confirm this sensitive action now".',
        ),
        repin=True,
    ),
    # N-n: probes that must trip nothing (a negated or cited form of a ruled behaviour)
    Mutation(
        "N-1",
        "",
        "a negated badge",
        spec=after_line(S510, "- No environment badge is shown before sign-in."),
    ),
    Mutation(
        "N-2",
        "",
        "a negated trust control",
        spec=after_line(S510, "- The trust this device checkbox is never shown in v1."),
    ),
)

# Z-n: the post-merge tuple (run in post-merge mode): drift is a WARN, never a FAIL; G-UNTOUCHED
# reads nothing; the content gates still catch
POST_MUTATIONS = (
    Mutation(
        "Z-1", "", "a v2 cite edited later: one WARN", lever=lever_drift_v2, repin=True, warns=1
    ),
    Mutation("Z-2", "", "a v1 cite edited later: one WARN", lever=lever_drift, repin=True, warns=1),
    Mutation("Z-3", "", "a stray path: nothing", lever=lever_extra, repin=True),
    Mutation(
        "Z-4",
        "G-V1-FROZEN",
        "a v1 sentence edited outside the register",
        spec=sub(
            "The band was built before most of its design",
            "The band was built before much of its design",
        ),
        repin=True,
    ),
    Mutation(
        "Z-5",
        "G-DELTA",
        "a changed deck entry the register does not name",
        spec=cell_set("V-28", 1, "deck `lock.title`"),
        repin=True,
    ),
)


def run_mutations(
    muts: tuple[Mutation, ...], spec_f: str, deck: str, values: Values, paths: tuple[Path, ...]
) -> tuple[bool, int, list[str]]:
    """Apply each mutation in the current mode: (all caught, caught, report lines)."""
    on_disk = digest(paths)
    plans = read_plans()
    vt = tuple(sorted(values.items()))
    base_fails, _n, base_warns, _c = audit(Texts(spec_f, deck, plans, vt))
    lines = [f"{mode_name()} baseline: {len(base_fails)} FAIL, {len(base_warns)} WARN"]
    lines += [f"  baseline FAIL {x}" for x in base_fails]
    lines += [f"  baseline WARN {x}" for x in base_warns]
    ok = not base_fails and not base_warns
    caught = 0
    pristine = digest_texts(spec_f, deck)
    for mu in muts:
        s = mu.spec(spec_f) if mu.spec else spec_f
        d = mu.deck(deck) if mu.deck else deck
        if (s, d) == (spec_f, deck) and mu.lever is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        undo = mu.lever() if mu.lever else None
        repin = mu.mid.startswith(("X-", "N-")) or mu.repin
        if repin:
            PIN_UNITS_OVERRIDE.append(tuple(ruled_units(s, d, values)))
        try:
            fails, _n2, warns, _c2 = audit(Texts(s, d, plans, vt))
        except SystemExit as exc:
            fails, warns = [str(exc)], []
        finally:
            if undo:
                undo()
            if repin:
                PIN_UNITS_OVERRIDE.pop()
        new = [x for x in fails if x not in base_fails]
        new_w = [x for x in warns if x not in base_warns]
        if mu.gate:
            named = [x for x in new if x.startswith(f"[{mu.gate}]")]
            hit = bool(named) and len(new) == 1 and not new_w
        else:
            named, hit = [], not new and len(new_w) == mu.warns
        levers = (
            DRIFT or CVD_OVERRIDE or PIN_UNITS_OVERRIDE or EXTRA_PATHS or BROKEN or PLAN_OVERRIDE
        )
        restored = digest_texts(spec_f, deck) == pristine and digest(paths) == on_disk
        restored = restored and not levers and not PIN_TEXT_OVERRIDE
        ok = ok and hit and restored
        caught += int(hit and restored)
        first = (named or new or new_w or ["nothing new"])[0]
        lines.append(
            f"  {mu.mid} [{mu.gate or 'none'}] {'ok' if hit else 'MISSED'} ({len(new)} new,"
            f" {len(new_w)} warn{'' if restored else ', NOT RESTORED'}) - {first}"
        )
        if not hit:
            lines += [f"      new: {x}" for x in [*new, *new_w]]
    return ok, caught, lines


def selftest(spec: str, deck: str, paths: tuple[Path, ...]) -> tuple[bool, list[str]]:
    """The PR tuple in PR mode and the post-merge tuple in post-merge mode, each against its own
    baseline, with the values frozen at the filled baseline."""
    values = compute(spec, deck)
    spec_f, _ = fill(spec, values)
    values = compute(spec_f, deck)
    ok = True
    lines: list[str] = []
    counts: list[str] = []
    for mode, muts in (("pr", MUTATIONS), ("post", POST_MUTATIONS)):
        MODE_OVERRIDE.append(mode)
        try:
            good, caught, out = run_mutations(muts, spec_f, deck, values, paths)
        finally:
            MODE_OVERRIDE.pop()
        ok = ok and good
        lines += out
        counts.append(f"{'PR' if mode == 'pr' else 'post-merge'} {caught} of {len(muts)}")
    lines.append("caught: " + "; ".join(counts))
    return ok, [report(x) for x in lines]


# ---------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="E09-D12 hand-off pack audit (module docstring)")
    ap.add_argument("--check", nargs="?", const=SPEC_REL, default=None, metavar="SPEC")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="replace placeholders, then check")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="apply every mutation")
    ap.add_argument("--repin-ruled", action="store_true", help=f"rewrite {PIN_REL}")
    args = ap.parse_args(argv)
    spec_path = ROOT / (args.check or SPEC_REL)
    deck_path = ROOT / DECK_REL
    spec = spec_path.read_bytes().decode("utf-8")
    deck = deck_path.read_bytes().decode("utf-8")
    if args.repin_ruled:
        left = PLACEHOLDER.findall(CODE.sub("", spec))
        if left:
            print(f"FAIL --repin-ruled: {len(left)} unfilled placeholders; run --fill first")
            return 1
        units = ruled_units(spec, deck, compute(spec, deck))
        write_text(ROOT / PIN_REL, write_pins(units))
        print(f"--repin-ruled: {len(units)} units pinned in {PIN_REL}")
        return 0
    if args.self_test:
        paths = (spec_path, deck_path, ROOT / PIN_REL, *(p for _n, p in plan_paths()))
        ok, lines = selftest(spec, deck, paths)
        print("\n".join(lines))
        total = len(MUTATIONS) + len(POST_MUTATIONS)
        print(report(f"--self-test: {'ok' if ok else 'FAIL'} - {total} mutations"))
        return 0 if ok else 1
    values = compute(spec, deck)
    if args.fill:
        spec, unknown = fill(spec, values)
        write_text(spec_path, spec)
        for u in unknown:
            print(f"FAIL --fill: no value for {{{{{u}}}}}")
        values = compute(spec, deck)
    if args.json and not (args.check or args.fill):
        print(json.dumps({"values": values}, ensure_ascii=False, indent=1))
        return 0
    t = Texts(spec, deck, read_plans(), tuple(sorted(values.items())))
    fails, notes, warns, n = audit(t)
    if args.json:
        doc = {
            "values": values,
            "mode": mode_name(),
            "fails": fails,
            "notes": notes,
            "warnings": warns,
            "cites": n,
        }
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        gates = len(LEXICON_GATES) + len(MEASURED_GATES) + len(DOC_GATES) + len(V2_GATES) + 2
        shown = spec_path.relative_to(ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        print(f"## E09-D12 audit of {shown} (+ the deck): v1 at {BASE}, v2 at {BASE_V2}")
        print(f"mode: {mode_name()} (by content)")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(notes))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK - every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(notes)} NOTE, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
