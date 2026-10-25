#!/usr/bin/env python3
"""E29-D04 (#823) audit: the blotter design-system contributions and the motion spec.

Standalone, offline, stdlib only. It reads AS TEXT at the pinned base `6fc8aacc6` (`git show`):
the plan texts `05`, `14`, `15`, `16`, the merged E29-D01 / E29-D02 / E29-D03 texts, E09-D09,
E30-D02, `theme.css`, `tools/contrast/pairs.mjs`, the CVD port's source
`docs/research/_tools/cvd_simulate.py` and the E11-D05 tool's JND floor; then this ticket's spec
and hand-off and the working-tree `15` and `16`, which must equal the base. It runs no repo code
apart from the two design helpers the merged E29-D02 and E30-D04 tools load the same way, read
through one `_load`: `contrast_check.contrast_ratio()` and the theme loader of
`packages/ui/tokens/tests/verify_tokens.py` (`load`, `merged_set`, `resolve`, `over`,
`delta_e76`, `rgb_to_lab`); both, and the token JSON they read, must equal the base
(G-UNTOUCHED).

1. **Values.** Every token, motion, distance, contrast and count figure is COMPUTED and printed
   by `--json` (`values`): durations and easings from the primitives; the flash, loop, polite,
   linger, hold, skeleton and size constants parsed from their cited lines (CITED_VALUES);
   contrast per theme (dark, light, high contrast) through the helpers; CVD as CIE76 ΔE after the
   Brettel / Viénot projection of `cvd_simulate.py` (ported verbatim; G-CVD-PORT re-reads its
   constants) and the greyscale CIELAB L* gap; the counts from the spec's own tables. A figure in
   the spec is written `VALUE <!-- audit:NAME=VALUE -->`; `--check` re-derives every marker and
   the number in front of it, and FAILs on a hand-typed figure with a unit, a two-decimal number
   or a Δ value outside a marker, and on an unfilled `{{audit:NAME}}`; `--fill` writes the
   marked value for each `{{audit:NAME}}` in the spec and the hand-off.
2. **Cites.** Every `NN`:line, `D01`/`D02`/`D03`/`PRIM`:line, `Exx-Dyy`:line and `path`:line
   resolves at the base (FAIL when the line is gone or blank; WARN when it drifted at
   `origin/main`). A cite followed by a quoted fragment, and every Table A Old cell, is looked up
   whole: on its line it passes, once elsewhere it WARNs (moved), nowhere or more than once off
   its line it FAILs (gone, ambiguous). The merged-sha pins are ancestors of the base, carry
   their PR numbers and touch the cited files.
3. **Gates (RULED comment 6399392172).** Every table row, bullet, prose sentence and heading of
   the spec and the hand-off is read, fenced copy-ready blocks included, after normalising (HTML
   comments, soft hyphens and zero-width characters dropped, NFKC, markup stripped, dashes to
   spaces, lower case; quoted copy removed where a gate reads claims). WHOLE-UNIT reading: a
   table row is one sentence across all its cells, a sentence runs across `;`, `—` and
   parentheses, and a sentence that opens on a pronoun or a conjunction reads the previous
   sentence's subject in its place. A negation covers only its own fragment (it stops at `;`,
   `—`, a parenthesis, a colon, a cell, and a comma or a conjunction that opens a new clause); a
   negation chain ("never fails to", "not without") asserts its term; a name that holds a
   negation word ("NO SL", "Not available") is never one. A gate that pairs a subject with a
   claim reads them within a few words of each other, across fragments; the structured tables
   (the motion table, the state tables of §2, §4.1's legs, the `16` block) are read by column,
   frame by frame. Vocabulary lists are case-insensitive. A section whose body still holds a
   `> **To write (` line is skipped by its gates and fails G-PLACEHOLDER alone.
4. **Pins (default-deny).** A heading, table cell, prose sentence or fenced line that names
   view-as, a fixture account (Main, Sub-n), an environment (LIVE / DEMO), flatten or a bulk
   exit, the kill switch or a freeze, a native stop or NO SL, liquidation, reduce-only,
   read-only, `aria-disabled`, audit, or keys and their kin is security-bearing; each must equal,
   whitespace-normalised and in document order, its entry of SEC_PIN_TXT (section, row and
   column or "prose", exact text). New, changed, moved, duplicated and gone clauses FAIL
   G-SEC-PIN; `--check` never re-pins; `--repin-security` prints the table from the current text
   for a reviewer to read and commit at the end of this file.
5. **--self-test** (or `--selftest`) builds the baseline in memory: the spec and the hand-off
   on disk, each section still holding a placeholder filled from FIXTURE (so the skeleton is
   exercised whole; `--fixture HEADING` prints a block). The baseline must have no FAIL. Every
   mutation of MUTATIONS is applied in memory, values frozen at the baseline: it must add
   exactly one distinct FAIL, from the gate it names, and every gate has at least one; the
   semantic mutations run against a pin table re-rendered from the mutated text (the gate holds
   even after a careless re-pin), the pin mutations against the baseline's own pins. Restore is
   proven by sha256 of the in-memory baseline and of every file on disk, and by a final audit of
   the baseline with no FAIL. The disk is never written.

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e29_d04_ds_motion_audit.py --check [--json]
  python3 -I -B docs/design/_tools/e29_d04_ds_motion_audit.py --json
  python3 -I -B docs/design/_tools/e29_d04_ds_motion_audit.py --fill
  python3 -I -B docs/design/_tools/e29_d04_ds_motion_audit.py --self-test
  python3 -I -B docs/design/_tools/e29_d04_ds_motion_audit.py --repin-security
  python3 -I -B docs/design/_tools/e29_d04_ds_motion_audit.py --fixture "3.2"
Exit 0 = no FAIL; 1 = at least one FAIL. WARNs never fail.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import textwrap
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
BASE = "6fc8aacc6"  # every cite was read here (the spec's Inputs line)
HEAD = "origin/main"  # drift is reported against this ref (WARN, never FAIL)
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E29/E29-D04.md"
HAND_REL = "docs/design/E29/E29-D04-handoff.md"
P15_REL = "docs/plan/15-component-catalogue.md"
P16_REL = "docs/plan/16-design-system-brief.md"
DS_DIR_REL = "packages/ui/tokens"
DS_FILES = ("primitives", "semantic-dark", "semantic-light", "semantic-hc")
LOADER_REL = "packages/ui/tokens/tests/verify_tokens.py"
RATIO_REL = "docs/design/_tools/contrast_check.py"
CSS_REL = "packages/ui/src/theme/theme.css"
PAIRS_MJS_REL = "tools/contrast/pairs.mjs"
CVD_REL = "docs/research/_tools/cvd_simulate.py"
JND_REL = "docs/design/_tools/e11_d05_ds_audit.py"
D09_REL = "docs/design/E09/E09-D09.md"
E30D02_REL = "docs/design/E30/E30-D02.md"
CITE_FILES: dict[str, str] = {
    "D01": "docs/design/E29/E29-D01.md",
    "D02": "docs/design/E29/E29-D02.md",
    "D03": "docs/design/E29/E29-D03.md",
    "PRIM": f"{DS_DIR_REL}/primitives.tokens.json",
    "theme.css": CSS_REL,
}
# the inputs every measurement reads from disk: they must equal the base (G-UNTOUCHED)
MEASURED: tuple[str, ...] = (
    P15_REL,
    P16_REL,
    LOADER_REL,
    RATIO_REL,
    *(f"{DS_DIR_REL}/{f}.tokens.json" for f in DS_FILES),
    f"{DS_DIR_REL}/themes.json",
)
THEMES = ("dark", "light", "high-contrast")
THEME_SHORT = {"dark": "dark", "light": "light", "high-contrast": "hc"}
SIMS = ("protanopia", "deuteranopia", "tritanopia")
SIM_SHORT = {"protanopia": "protan", "deuteranopia": "deutan", "tritanopia": "tritan"}

# ---- the ruling and the fixed facts
RULING_ID = "6399392172"
BQ_LIST_ID = "6399349188"
OWNER_MARK = "owner approval pending (#2701)"
OWNER_BQS = ("BQ-2", "BQ-10", "BQ-11", "BQ-12")
BQ_COUNT = 16
APPLIER = "E29-T09"
# sha → (PR, a path the merge touched): the merged inputs of the spec's Start / Inputs lines
PINS: dict[str, tuple[str, str]] = {
    "9da45ae35": ("#3899", "docs/design/E29/E29-D01.md"),
    "c4270ba93": ("#4114", "docs/design/E29/E29-D02.md"),
    "75a33c164": ("#4330", "docs/design/E29/img/"),
    "a59ba382b": ("#4307", "docs/design/E29/E29-D03.md"),
    "ca7d61fa1": ("#4271", "docs/design/E30/E30-D04.md"),
    "baccf724a": ("#3953", "docs/design/E09/E09-D09.md"),
    "0beb67563": ("#4175", "docs/design/E39/E39-D03.md"),
    "7c804aacc": ("#3914", "docs/design/E05/E05-D02.md"),
    "c899241c8": ("#4290", "docs/design/E05/E05-D02-data-display.md"),
    "3a2fc5c29": ("#4322", "docs/design/E05/E05-D02-form-controls.md"),
    "04a8caa95": ("#4414", "docs/design/E05/E05-D02-feedback-overlays.md"),
}
# sha → the document it pins: a document id named next to it must be this one
PIN_DOC = {
    "9da45ae35": "d01",
    "c4270ba93": "d02",
    "75a33c164": "d02",
    "a59ba382b": "d03",
    "ca7d61fa1": "e30 d04",
    "baccf724a": "e09 d09",
    "0beb67563": "e39 d03",
    "7c804aacc": "e05 d02",
    "c899241c8": "e05 d02",
    "3a2fc5c29": "e05 d02",
    "04a8caa95": "e05 d02",
}
DOC_IDS = r"\b(e29 d01|e29 d02|e29 d03|d01|d02|d03|e30 d04|e09 d09|e39 d03|e05 d02)\b"
HAND_PINS = ("9da45ae35", "c4270ba93", "75a33c164", "a59ba382b")
MAX_BOARDS = 10  # RULED BQ-15: at most ten boards, seven dark and three light twins
LIGHT_BOARDS = 3
SPEC_LINE_BUDGET = 600  # RULED BQ-1: the spec's line budget
SUMMARY_LINES = 10

# the load-bearing fragments the tool's constants and gates rest on: (cite id, line, text)
CITED: tuple[tuple[str, int, str], ...] = (
    ("D01", 125, "E29-D04 caps data-row motion at 200 ms"),
    ("D01", 174, "| B1 lifecycle state | Label"),
    ("D01", 407, '"New" marker for 5 s'),
    ("D01", 408, "stays in place for about 5 s"),
    ("D01", 409, "At most 200 ms"),
    ("D01", 500, "AM-3"),
    ("D02", 147, "2 px accent bar"),
    ("D02", 211, "### 5.3 Liquidation tiers"),
    ("D02", 224, "### 5.4 Protection chip"),
    ("D02", 320, "still live"),
    ("D02", 325, "never optimistically as confirmed"),
    ("D02", 353, "Live adds the typed confirm"),
    ("D02", 590, "**Components by id:**"),
    ("D02", 617, "No catalogued component for the pending tag"),
    ("D02", 622, "a Live flatten needs hold and typed"),
    ("D03", 46, "E29 runs on Bybit"),
    ("D03", 401, "the correction highlight is E29-D04's motion item"),
    ("D03", 613, "| Item "),
    ("15", 41, "Test requirement baseline"),
    ("15", 192, "one sweep per 1,200 ms, stopped at 5 s"),
    ("15", 476, "default 800 ms, PROPOSED `motion.duration.hold-confirm`"),
    ("15", 526, "PositionsGrid (CMP-107)"),
    ("15", 1240, "### CMP-114 PositionsGrid"),
    ("15", 1274, "### CMP-115 OrderRow"),
    ("15", 1300, "### CMP-116 PnLBadge"),
    ("15", 1403, "### CMP-123 FlattenAllButton"),
    ("15", 1474, "### CMP-129 PositionModeToggle"),
    ("16", 175, "No flashing content exceeding 3 times per second"),
    ("16", 179, "colour-only momentary text tint"),
    ("16", 199, "value-change emphasis"),
    ("05", 147, "1 update / 2s per field"),
    ("05", 206, "single low-amplitude cross-fade"),
    ("05", 208, "No content flashes more than 3 times per second"),
    ("14", 1479, "CMP-114 PositionsGrid"),
    ("14", 1743, "CMP-099 PrintExportBar"),
    ("PRIM", 450, '"motion.duration.instant"'),
    ("theme.css", 56, ':root[data-motion="reduce"],'),
    ("E09-D09", 410, "Every treatment in this document is presentation"),
    ("E30-D04", 351, "## 8. CMP-105 AccountMultiSelect"),
    ("E30-D04", 553, "**Never animates**"),
)
# constants the spec quotes, parsed from their cited line at the base: name → (cite id, line,
# pattern); the first group is the value (thousands separators dropped)
CITED_VALUES: dict[str, tuple[str, int, str]] = {
    "cited.16.flash-peak-opacity": ("16", 199, r"peak (0\.\d+)"),
    "cited.16.flash-gap-ms": ("16", 199, r"≥ (\d+) ms between starts"),
    "cited.16.flash-cells-per-frame": ("16", 199, r"≤ (\d+) cells per frame"),
    "cited.16.flash-stop-hz": ("16", 199, r"≥ (\d+) Hz for"),
    "cited.16.flash-stop-after-s": ("16", 199, r"Hz for (\d+) s"),
    "cited.16.loop-max-s": ("16", 175, r"more than (\d+) seconds"),
    "cited.05.flash-max-per-s": ("05", 208, r"more than (\d+) times per second"),
    "cited.05.polite-gap-s": ("05", 147, r"1 update / (\d+)s per field"),
    "cited.d01.flash-max-ms": ("D01", 409, r"At most (\d+) ms"),
    "cited.d01.flash-gap-ms": ("D01", 409, r"once per cell per (\d+) ms"),
    "cited.d01.new-marker-s": ("D01", 407, r'"New" marker for (\d+) s'),
    "cited.d01.linger-s": ("D01", 408, r"about (\d+) s"),
    "cited.d02.accent-bar-px": ("D02", 147, r"(\d+) px accent bar"),
    "cited.d02.critical-accent-px": ("D02", 220, r"(\d+) px leading accent"),
    "cited.d02.focus-ring-px": ("D02", 461, r"a (\d+) px `color\.focus\.ring`"),
    "cited.d02.narrow-dock-px": ("D02", 469, r"At (\d+) px the panel"),
    "cited.d02.pill-px": ("D02", 619, r"the (\d+) / \d+ px pill"),
    "cited.d02.tag-px": ("D02", 619, r"the \d+ / (\d+) px pill"),
    "cited.cmp044.hold-ms": ("15", 476, r"default (\d+) ms, PROPOSED"),
    "cited.cmp044.hold-min-ms": ("15", 476, r"within a (\d+)–"),
    "cited.cmp044.hold-max-ms": ("15", 476, r"–([\d,]+) ms setting"),
    "cited.cmp015.period-ms": ("15", 192, r"one sweep per ([\d,]+) ms"),
    "cited.cmp015.stop-s": ("15", 192, r"stopped at (\d+) s"),
    "cited.theme.reduce-ms": ("theme.css", 63, r"transition-duration: ([\d.]+)ms"),
}
# §5's pairs: name → (fg, bg, role); a bg "X over Y" is X at the `16` §7.1 flash peak over Y
PAIRS: dict[str, tuple[str, str, str]] = {
    "digits": ("color.text.primary", "color.surface.raised", "text"),
    "digits-selected": ("color.text.primary", "color.surface.selected", "text"),
    "digits-flash-peak": (
        "color.text.primary",
        "color.status.info.subtle over color.surface.raised",
        "text",
    ),
    "bar-buy": ("color.buy.default", "color.surface.raised", "non-text"),
    "bar-sell": ("color.sell.default", "color.surface.raised", "non-text"),
    "bar-neutral": ("color.neutral.default", "color.surface.raised", "non-text"),
    "bar-buy-selected": ("color.buy.default", "color.surface.selected", "non-text"),
    "bar-sell-selected": ("color.sell.default", "color.surface.selected", "non-text"),
    "bar-neutral-selected": ("color.neutral.default", "color.surface.selected", "non-text"),
    "pending-tag": ("color.text.primary", "color.status.info.subtle", "text"),
    "pending-glyph": ("color.status.info.strong", "color.status.info.subtle", "non-text"),
    "rejected-line": ("color.text.primary", "color.status.warning.subtle", "text"),
    "rejected-glyph": ("color.status.warning.strong", "color.status.warning.subtle", "non-text"),
    "liq-watch-glyph": ("color.text.secondary", "color.surface.raised", "non-text"),
    "liq-near-glyph": ("color.status.warning.strong", "color.surface.raised", "non-text"),
    "liq-critical-glyph": ("color.status.danger.strong", "color.surface.raised", "non-text"),
    "no-sl-chip": ("color.text.primary", "color.status.danger.subtle", "text"),
    "no-sl-glyph": ("color.status.danger.strong", "color.status.danger.subtle", "non-text"),
    "t2-label": ("color.text.tertiary", "color.surface.raised", "text"),
    "t2-reason": ("color.text.secondary", "color.surface.raised", "text"),
    "t2-label-selected": ("color.text.secondary", "color.surface.selected", "text"),
    "env-live-border": ("color.env.live", "color.surface.raised", "non-text"),
    "env-demo-border": ("color.env.demo", "color.surface.raised", "non-text"),
    "focus-row": ("color.focus.ring", "color.surface.raised", "non-text"),
    "focus-selected": ("color.focus.ring", "color.surface.selected", "non-text"),
    "flatten-confirm-label": ("color.text.on-action", "color.status.danger.default", "text"),
    "stale-row": (
        "color.data-confidence.stale.text",
        "color.data-confidence.stale.surface",
        "text",
    ),
}
# measured, never gated: the figures a Deliberate exception or a C-row records
MEASURED_ONLY: dict[str, tuple[str, str, str]] = {
    "t2-label-selected-tertiary": ("color.text.tertiary", "color.surface.selected", "measured"),
    "digits-coloured-sell": ("color.sell.default", "color.surface.raised", "measured"),
}
# the colour pairs whose CVD and greyscale distances §5 reports: name → (a, b)
CVD_PAIRS: dict[str, tuple[str, str]] = {
    "bar-buy-sell": ("color.buy.default", "color.sell.default"),
    "liq-near-critical": ("color.status.warning.strong", "color.status.danger.strong"),
    "pending-rejected": ("color.status.info.strong", "color.status.warning.strong"),
    "env-live-demo": ("color.env.live", "color.env.demo"),
}
# D02 gap 8's elements, each a named part of its parent entry in §2.9 (D02:617)
GAP8 = (
    "pending tag",
    "protection chip",
    "liquidation tier cell",
    "correction markers",
    "Updates paused",
    "Fills Type toggle chips",
    "group header row",
    "totals row",
)
# the eight kinds of state swap that change at frame 0 in both modes (RULED BQ-11)
SWAP_KINDS: dict[str, str] = {
    "status words": r"\bstatus words?\b",
    "glyphs": r"\bglyphs?\b",
    "fills": r"\bfills?\b",
    "pills": r"\bpills?\b",
    "liq tier": r"\bliq(?:uidation)? tiers?\b",
    "protection chip": r"\bprotection chips?\b",
    "T2 ↔ enabled": r"\bt2 ↔ enabled\b",
    "DEMO / LIVE": r"\bdemo / live\b",
}

Values = dict[str, str]
Fetch = Callable[[str, str], str | None]

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


def git_ok(*args: str) -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def at_base(rel: str) -> str:
    text = git_show(BASE, rel)
    if text is None:
        raise SystemExit(f"FAIL parse: {rel} is not readable at {BASE}")
    return text


@functools.lru_cache(maxsize=64)
def plan_rel(nn: str) -> str | None:
    listing = git_out("ls-tree", "--name-only", BASE, "docs/plan/")
    names = [n for n in listing.split("\n") if n.startswith(f"docs/plan/{nn}-")]
    return min(names) if names else None


def plan(nn: str) -> str:
    rel = plan_rel(nn)
    if rel is None:
        raise SystemExit(f"FAIL parse: docs/plan/{nn}-* missing at {BASE}")
    return at_base(rel)


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
        raise SystemExit(f"FAIL parse: {cid}:{n} is past the end at {BASE}")
    return lines[n - 1]


def grab(pattern: str, text: str, what: str, flags: int = MULTI) -> str:
    m = re.search(pattern, text, flags)
    if not m:
        raise SystemExit(f"FAIL parse: {what} not found ({pattern})")
    return m[1]


# ---------------------------------------------------------------------------- markdown

HEADING = re.compile(r"^(#{1,6}) (.*)$")
PLACEHOLDER = re.compile(r"^> \*\*To write \(")


def fenced(lines: list[str]) -> list[bool]:
    """For each line, whether it sits inside (or is) a ``` fence."""
    out: list[bool] = []
    inside = False
    for ln in lines:
        if ln.lstrip().startswith("```"):
            out.append(True)
            inside = not inside
            continue
        out.append(inside)
    return out


def section(text: str, head: str) -> str:
    """From the heading starting with `head` (outside fences) to the next heading of the same or
    a higher level outside a fence; "" when there is no such heading."""
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


def pending(text: str, head: str) -> bool:
    """Whether the section `head` (its subsections included) still holds a placeholder."""
    return any(PLACEHOLDER.match(ln) for ln in section(text, head).split("\n"))


def split_row(line: str) -> list[str]:
    body = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", body)]


def is_rule(line: str) -> bool:
    return re.match(r"^\s*\|\s*:?-{1,}", line) is not None and set(line.strip()) <= set("|-: ")


def tables(block: str) -> list[tuple[list[str], list[list[str]]]]:
    """Every table of `block`: its header cells and its body rows (cells)."""
    out: list[tuple[list[str], list[list[str]]]] = []
    lines = block.split("\n")
    i = 0
    while i < len(lines):
        if re.match(r"^\s*\|", lines[i]) and i + 1 < len(lines) and is_rule(lines[i + 1]):
            head = split_row(lines[i])
            body: list[list[str]] = []
            j = i + 2
            while j < len(lines) and re.match(r"^\s*\|", lines[j]):
                if not is_rule(lines[j]):
                    body.append(split_row(lines[j]))
                j += 1
            out.append((head, body))
            i = j
            continue
        i += 1
    return out


def table_rows(block: str) -> list[list[str]]:
    """Every body row of every table of `block`."""
    return [r for _h, body in tables(block) for r in body]


def table_with(block: str, *words: str) -> list[dict[str, str]]:
    """The rows of the first table whose header holds every word of `words` (case-insensitive),
    as dicts keyed by the header cells (empty when there is no such table)."""
    for head, body in tables(block):
        joined = " | ".join(head).lower()
        if all(w.lower() in joined for w in words):
            return [dict(zip(head, r, strict=False)) for r in body]
    return []


def col(row: dict[str, str], word: str) -> str:
    """The cell of `row` whose header starts with `word` (case-insensitive); "" when none."""
    for k, v in row.items():
        if k.lower().startswith(word.lower()):
            return v
    return ""


def row_key(cell: str) -> str:
    """A row id with markup dropped and its separator normalised (`**Mo-11**`, `DR 16` → id)."""
    k = re.sub(r"[*_`]", "", cell).strip()
    return re.sub(r"^([A-Za-z]+)\s+(\d+)$", r"\1-\2", k)


def bullet(block: str, label: str) -> str:
    """The `- **Label**…` line of a block (fenced lines included); "" when there is none."""
    for ln in block.split("\n"):
        if re.match(rf"^\s*- \*\*{re.escape(label)}", ln):
            return ln
    return ""


# ---------------------------------------------------------------------------- normalising

_DASHES = re.compile(r"[\u2010-\u2015\u2212-]")
_MARKUP = re.compile(r"[*`]")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# hidden in rendered markdown: HTML comments (markers included), soft hyphens, zero-width
_HIDDEN = re.compile(r"<!--.*?-->|[\u00ad\u200b-\u200d\u2060\ufeff]", re.DOTALL)
_EMPH = re.compile(r"(?<!\w)_+|_+(?!\w)")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
CODE = re.compile(r"`[^`\n]*`")


def norm_text(text: str) -> str:
    """Rendered words only: comments, soft hyphens and markup dropped, NFKC, dashes to spaces,
    whitespace collapsed, lower case."""
    t = unicodedata.normalize("NFKC", _HIDDEN.sub("", text))
    t = _EMPH.sub(" ", _MARKUP.sub("", _LINK.sub(r"\1", t)))
    return " ".join(_DASHES.sub(" ", t).split()).lower()


def unquote(text: str) -> str:
    return QUOTED.sub(" ", text)


def visible(text: str) -> str:
    """The text with HTML comments and placeholder lines dropped (what a reader sees)."""
    kept = [ln for ln in text.split("\n") if not PLACEHOLDER.match(ln)]
    return _HIDDEN.sub(" ", "\n".join(kept))


# ---------------------------------------------------------------------------- whole-unit reading

# a hard fragment boundary: a semicolon, a spaced dash, a parenthesis or bracket, a colon, a
# table cell, a sentence end; a negation never reaches across one
HARD = re.compile(r";\s*|\s+[—–]\s+|[()\[\]]|:\s+|\s\|\s|(?<=[.!?])\s+")
# a soft boundary inside a fragment: a comma or a conjunction that opens a new clause
SOFT = re.compile(
    r",\s+(?=(?:the|a|an|it|its|they|their|this|these|that|those|which|each|every|both|so|"
    r"but|while|whereas|yet|then|instead)\b)"
    r"|\s(?=(?:but|except|unless|while|whereas|although|though|yet|instead|however|only)\s)"
    r"|\s(?:and|or)\s(?=(?:the|a|an|it|its|they|their|this|these|that|those|each|every)\b)"
)
NEG = re.compile(r"\b(?:no|never|not|nor|without|nothing|none|cannot|neither)\b|n't\b")
DOUBLE_NEG = re.compile(
    r"\b(?:never|not|no) without\b|\bnever not\b|\bnot never\b|\bnot (?:only|just)\b"
    # a negation chain asserts its term: "never fails to", "never un-gated", "no other … than"
    r"|\b(?:never|not|no|cannot|nothing)\s+(?:\S+\s+){0,2}?"
    r"(?:fail(?:s|ed|ing)?|lack(?:s|ed|ing)?|omit\w*|un|other|ceas\w*)\b"
)
NEG_REACH = 8  # words a negation covers inside its fragment
# phrases whose negation word is part of a name or of the asserted claim, never a negation
PROTECT: tuple[tuple[str, str], ...] = (
    (r"\bno sl\b", "no_sl"),
    (r"\bnot shown\b", "not_shown"),
    (r"\bnot offered\b", "not_offered"),
    (r"\bnot available\b", "not_available"),
)


def protect(t: str) -> str:
    for pattern, name in PROTECT:
        t = re.sub(pattern, name, t)
    return t


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`\"“*(])")
PRONOUN = re.compile(
    r"^(?:it|its|they|their|them|this|these|that|those|which|both|each|either|neither|such|"
    r"then|also|so|and|or|but|while|whose|here|there)\b"
)


def fragments(raw: str) -> list[str]:
    return [f for f in HARD.split(raw) if f.strip()]


def _asserts(raw_fragment: str, term: str, keep_quotes: bool) -> bool:
    t = norm_text(raw_fragment if keep_quotes else unquote(raw_fragment))
    t = protect(DOUBLE_NEG.sub(" ", t))
    out = list(t)
    for m in NEG.finditer(t):
        start = m.end()
        soft = SOFT.search(t, start)
        end = soft.start() if soft else len(t)
        words = list(re.finditer(r"\S+", t[start:end]))
        if len(words) > NEG_REACH:
            end = start + words[NEG_REACH - 1].end()
        for k in range(m.start(), end):
            out[k] = " "
    return re.search(term, "".join(out)) is not None


def live(raw: str, term: str, keep_quotes: bool = False) -> bool:
    """`term` asserted in `raw` once every negated mention is blanked: a negation covers its
    own fragment only, up to a soft boundary and at most NEG_REACH words; a negation chain
    asserts its term."""
    return any(_asserts(f, term, keep_quotes) for f in fragments(raw))


def units(text: str) -> list[str]:
    """Every unit a gate reads: each table row (its cells joined by " | "), each bullet, each
    prose paragraph and each heading; fenced copy-ready lines are read like the rest; HTML
    comments and placeholder lines are dropped."""
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(" ".join(para))
            para.clear()

    for ln in visible(text).split("\n"):
        s = ln.strip()
        if s.startswith("```"):
            flush()
        elif re.match(r"^\s*\|", ln):
            flush()
            if not is_rule(ln):
                out.append(" | ".join(split_row(s)))
        elif re.match(r"^\s*(?:[-*+]|\d+\.) ", ln) or s.startswith("#"):
            flush()
            out.append(s)
        elif s:
            para.append(s)
        else:
            flush()
    flush()
    return out


def sentences(unit: str) -> list[str]:
    """A table row is one sentence across all its cells; prose splits at a sentence end only
    (never at a semicolon, a dash or a parenthesis)."""
    if " | " in unit:
        return [unit]
    return [s for s in SENTENCE_END.split(unit) if s.strip()]


def claims(
    texts: list[str],
    term: str,
    near: str = "",
    keep_quotes: bool = False,
    unless: str = "",
    near_live: bool = False,
) -> list[str]:
    """Every sentence (a row: across its cells) asserting `term` whose subject names `near`
    (asserted too when `near_live`); a sentence opening on a pronoun or a conjunction carries the
    previous sentence's subject. A sentence naming `unless` (the cited or recorded forms a gate
    allows) is skipped."""
    hits: list[str] = []
    for text in texts:
        for u in units(text):
            carried = False
            for s in sentences(u):
                n = norm_text(s if keep_quotes else unquote(s))
                has = not near or (
                    re.search(near, n) is not None and (not near_live or live(s, near, keep_quotes))
                )
                if near and not has and carried and PRONOUN.match(n):
                    has = True
                carried = bool(near) and has
                if not has:
                    continue
                if unless and re.search(unless, norm_text(s)):
                    continue
                if live(s, term, keep_quotes):
                    hits.append(n[:72])
    return hits


def blanked(raw: str, keep_quotes: bool = False) -> str:
    """The sentence normalised, each fragment's negated words blanked, fragments joined by " ¦ "
    (so a term and its subject may sit in different fragments of one sentence)."""
    parts: list[str] = []
    for f in fragments(raw):
        t = protect(DOUBLE_NEG.sub(" ", norm_text(f if keep_quotes else unquote(f))))
        out = list(t)
        for m in NEG.finditer(t):
            start = m.end()
            soft = SOFT.search(t, start)
            end = soft.start() if soft else len(t)
            words = list(re.finditer(r"\S+", t[start:end]))
            if len(words) > NEG_REACH:
                end = start + words[NEG_REACH - 1].end()
            for k in range(m.start(), end):
                out[k] = " "
        parts.append(" ".join("".join(out).split()))
    return " ¦ ".join(p for p in parts if p)


def adjacent(raw: str, a: str, b: str, gap: int, keep_quotes: bool = False) -> bool:
    """`a` and `b` both asserted within `gap` words of each other, in either order."""
    t = blanked(raw, keep_quotes)
    w = rf"\W+(?:\S+\W+){{0,{gap}}}?"
    return re.search(rf"(?:{a}){w}(?:{b})|(?:{b}){w}(?:{a})", t) is not None


def pair_claims(
    texts: list[str],
    a: str,
    b: str,
    gap: int,
    keep_quotes: bool = False,
    unless: str = "",
    need: str = "",
) -> list[str]:
    """Every sentence (a row: across its cells) where `a` and `b` are asserted within `gap`
    words; a sentence opening on a pronoun or a conjunction reads the previous sentence's subject
    (the phrase that matched `a`) in its place."""
    hits: list[str] = []
    for text in texts:
        for u in units(text):
            subject = ""
            for s in sentences(u):
                n = norm_text(s if keep_quotes else unquote(s))
                read = s
                m = re.search(a, n)
                if m:
                    subject = m[0]
                elif subject and PRONOUN.match(n):
                    read = subject + " " + re.sub(r"^\W*\w+", "", s, count=1)
                if unless and re.search(unless, norm_text(read)):
                    continue
                if need and not re.search(need, norm_text(unquote(read))):
                    continue
                if adjacent(read, a, b, gap, keep_quotes):
                    hits.append(norm_text(read)[:72])
    return hits


def one(tag: str, problems: list[str]) -> list[str]:
    """At most one FAIL line per gate."""
    if not problems:
        return []
    uniq = list(dict.fromkeys(problems))
    more = f" (+{len(uniq) - 4} more)" if len(uniq) > 4 else ""
    return [f"[{tag}] " + "; ".join(uniq[:4]) + more]


def nullish(cell: str) -> bool:
    """No value: blank, punctuation only ("—", "-", "(…)"), or a null word ("none", "n/a")."""
    words = " ".join(
        re.sub(r"[\s\-\u2010-\u2015.,;:!?()\[\]{}<>|*'\"`_\u2026]+", " ", norm_text(cell)).split()
    )
    return not words or re.fullmatch(NULL_WORDS, words) is not None


NULL_WORDS = (
    r"(?:none|n ?/? ?a|nil|null|empty|tb[dc]|todo|unknown|same|unchanged|as above|"
    r"same as above|ditto|nothing|open|pending|unresolved)"
)


# ---------------------------------------------------------------------------- the design helpers


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"FAIL parse: cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@functools.lru_cache(maxsize=1)
def helpers() -> tuple[ModuleType, ModuleType]:
    """The theme loader of `verify_tokens.py` and `contrast_check.py`, loaded read-only."""
    return _load(ROOT / LOADER_REL, "verify_tokens"), _load(ROOT / RATIO_REL, "contrast_check")


@functools.lru_cache(maxsize=4)
def theme_colours(theme: str) -> dict[str, str]:
    """Every colour name → its resolved hex in `theme`, layered as `verify_tokens.py` does."""
    loader, _ratio = helpers()
    layered: dict[str, object] = dict(loader.load(loader.PRIMITIVES))
    layered.update(loader.merged_set(loader.THEMES[theme]))
    out: dict[str, str] = {}
    for name, entry in layered.items():
        if isinstance(entry, dict) and entry.get("$type") == "color":
            out[name] = str(loader.resolve(entry["$value"], layered))
    return out


def hex_of(theme: str, name: str) -> str:
    value = theme_colours(theme).get(name, "MISSING")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?", value):
        raise SystemExit(f"FAIL parse: {name} does not resolve to a colour in {theme} ({value})")
    if len(value) == 9:  # an alpha colour, painted over the raised surface of the same theme
        loader, _ratio = helpers()
        alpha = int(value[7:9], 16) / 255
        return str(loader.over(value[:7], hex_of(theme, "color.surface.raised"), alpha)).upper()
    return value.upper()


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def paint(theme: str, spec: str, peak: float) -> str:
    """A background: a colour name, or "X over Y" (X at the flash peak over Y)."""
    if " over " in spec:
        top, under = spec.split(" over ", 1)
        loader, _ratio = helpers()
        return str(loader.over(hex_of(theme, top), hex_of(theme, under), peak)).upper()
    return hex_of(theme, spec)


def ratio(theme: str, fg: str, bg: str, peak: float) -> float:
    _loader, contrast = helpers()
    return float(contrast.contrast_ratio(rgb(hex_of(theme, fg)), rgb(paint(theme, bg, peak))))


@functools.lru_cache(maxsize=8)
def ds_file(name: str) -> dict[str, object]:
    """One token file at the base: name → its raw `$value`."""
    data = json.loads(at_base(f"{DS_DIR_REL}/{name}.tokens.json"))
    return {k: v.get("$value") for k, v in data.items() if isinstance(v, dict)}


@functools.lru_cache(maxsize=1)
def ds_names() -> frozenset[str]:
    names: set[str] = set()
    for f in DS_FILES:
        names |= set(ds_file(f))
    return frozenset(names)


def expand(name: str, known: frozenset[str]) -> list[str]:
    """`a.{b,c}` → [a.b, a.c]; `a.*` → every known name under `a.`."""
    m = re.search(r"\{([^}]+)\}", name)
    if m:
        return [x for part in m[1].split(",") for x in expand(name.replace(m[0], part), known)]
    if name.endswith(".*"):
        return sorted(n for n in known if n.startswith(name[:-1])) or [name]
    return [name]


# The Brettel (1997) / Viénot projection of `docs/research/_tools/cvd_simulate.py`, ported
# verbatim (G-CVD-PORT re-reads these constants from that file at the base).
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
    "tritanopia": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, -0.395913, 0.801109, 0.0),
}


def matvec(flat: tuple[float, ...], v: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        flat[0] * v[0] + flat[1] * v[1] + flat[2] * v[2],
        flat[3] * v[0] + flat[4] * v[1] + flat[5] * v[2],
        flat[6] * v[0] + flat[7] * v[1] + flat[8] * v[2],
    )


def flat3(m: tuple[tuple[float, float, float], ...]) -> tuple[float, ...]:
    return tuple(x for row in m for x in row)


def srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    s = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return max(0.0, min(1.0, s)) * 255.0


def simulate(hex6: str, deficiency: str) -> str:
    lin = tuple(srgb_to_linear(v) for v in rgb(hex6))
    lms = matvec(flat3(RGB_TO_LMS), (lin[0], lin[1], lin[2]))
    lin2 = matvec(flat3(LMS_TO_RGB), matvec(PROJECTIONS[deficiency], lms))
    return "#" + "".join(f"{max(0, min(255, round(linear_to_srgb(c)))):02X}" for c in lin2)


def delta_e(a: str, b: str) -> float:
    loader, _ratio = helpers()
    return float(loader.delta_e76(a, b))


def lightness(hex6: str) -> float:
    loader, _ratio = helpers()
    return float(loader.rgb_to_lab(rgb(hex6))[0])


# ---------------------------------------------------------------------------- the spec's tables

MO_ID = r"Mo-\d+"


def boards(spec: str) -> list[dict[str, str]]:
    rows = table_with(section(spec, "0. Planned boards"), "#", "Board")
    return [r for r in rows if re.fullmatch(r"\d\d", col(r, "#").strip())]


def is_light(board: dict[str, str]) -> bool:
    return re.search(r"-light`?$", col(board, "Board").strip()) is not None


def mo_rows(spec: str) -> dict[str, dict[str, str]]:
    rows = table_with(section(spec, "3.2 The motion table"), "Mo", "Property")
    return {row_key(col(r, "Mo")): r for r in rows}


def state_rows(spec: str, head: str) -> list[dict[str, str]]:
    return table_with(section(spec, head), "Frame", "State", "Word")


STATE_HEADS = (
    "2.1 CMP-114",
    "2.2 CMP-115",
    "2.3 CMP-116",
    "2.4 CMP-123",
    "2.5 CMP-129",
    "2.6 CMP-105",
    "2.7 CMP-049",
)


def all_state_rows(spec: str) -> list[tuple[str, dict[str, str]]]:
    return [(h, r) for h in STATE_HEADS for r in state_rows(spec, h)]


def gated_rows(spec: str) -> list[dict[str, str]]:
    return table_with(section(spec, "4.1 The gated controls"), "Control", "Legs")


def contrast_rows(spec: str) -> list[dict[str, str]]:
    return table_with(section(spec, "5. Tokens and contrast"), "Pair", "fg", "bg")


def proposed_names(spec: str) -> set[str]:
    rows = table_with(section(spec, "5. Tokens and contrast"), "Name", "Owner")
    return {n.lower() for r in rows for n in re.findall(r"`([^`]+)`", col(r, "Name"))}


def copy_rows(spec: str) -> list[dict[str, str]]:
    return table_with(section(spec, "6. Copy keys"), "Key", "String", "Status")


def c_rows(spec: str) -> dict[str, dict[str, str]]:
    rows = table_with(section(spec, "7.2 Contradictions"), "C", "Resolution")
    return {row_key(next(iter(r.values()), "")): r for r in rows}


DR_ID = r"DR-\d+"


def drift_rows(spec: str) -> dict[str, dict[str, str]]:
    rows = table_with(section(spec, "7.4 Drift ledger"), "DR", "Replacement", "Verdict")
    return {row_key(col(r, "DR")): r for r in rows}


def gate_rows(spec: str) -> list[dict[str, str]]:
    return table_with(section(spec, "8.2 The gate tool"), "Gate", "Mutations")


def table_a(hand: str) -> list[dict[str, str]]:
    return table_with(section(hand, "C.5 Table A"), "Field", "Old", "New")


def block16_rows(hand: str) -> list[dict[str, str]]:
    return table_with(section(hand, "C.6 The `16` block"), "Surface", "Enter")


# ---------------------------------------------------------------------------- the base's facts


@functools.lru_cache(maxsize=1)
def statuses() -> tuple[str, ...]:
    """D01 D2's lifecycle labels (D01:174 onwards, the Label column), each by its lead word."""
    lines = at_base(CITE_FILES["D01"]).split("\n")
    out: list[str] = []
    for ln in lines[175:]:
        if not ln.startswith("|"):
            break
        label = split_row(ln)[1]
        if is_rule(ln) or label.startswith("not shown"):
            continue
        m = re.match(r"[A-Za-z]+", label)
        if m:
            out.append(m[0])
    return tuple(out)


@functools.lru_cache(maxsize=1)
def tiers_and_b8() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """D02 §5.3's tier words (but `none`) and §5.4's B8 states, read from their tables."""
    d02 = at_base(CITE_FILES["D02"])
    tiers = [r[0] for r in table_rows(section(d02, "5.3 Liquidation tiers")) if r[0] != "none"]
    b8 = [r[0].strip("`") for r in table_rows(section(d02, "5.4 Protection chip"))]
    return tuple(tiers), tuple(b8)


@functools.lru_cache(maxsize=1)
def row_markers() -> tuple[str, ...]:
    """The row markers the merged texts draw: D02's "Verifying" (D02:414) and every marker of
    D03 §5.4's table (D03:327–344), the first quoted string of its Row marker column."""
    d03 = at_base(CITE_FILES["D03"])
    out = ["Verifying"]
    for r in table_with(section(d03, "5.4 Correction lines"), "Category", "Row marker"):
        m = re.search(r'"([^"]+)"', col(r, "Row marker"))
        if m and m[1] not in out:
            out.append(m[1])
    return tuple(out)


@functools.lru_cache(maxsize=1)
def inventory() -> tuple[str, ...]:
    """Every CMP id SCR-063 and SCR-078 name: `14`:1479 and :1743, D02:590, D03:615–617."""
    ids: set[str] = set()
    for cid, n in (("14", 1479), ("14", 1743), ("D02", 590)):
        ids |= {f"CMP-{x}" for x in re.findall(r"CMP-(\d{3})", base_line(cid, n))}
    for n in (615, 616, 617):
        cell = split_row(base_line("D03", n))[2]
        ids |= {f"CMP-{x}" for x in re.findall(r"(?<![\d-])(\d{3})(?!\d)", cell)}
    return tuple(sorted(ids))


@functools.lru_cache(maxsize=1)
def registered_reasons() -> frozenset[str]:
    """The reason and state keys merged texts register: E09-D09's and E30-D02's backticked keys."""
    text = at_base(D09_REL) + at_base(E30D02_REL)
    return frozenset(re.findall(r"`([a-z][a-z_]*(?:\.[a-z_{}]+)*)`", text))


def same(a: str, b: str) -> bool:
    a2, b2 = a.replace(",", ""), b.replace(",", "")
    if a2 == b2:
        return True
    try:
        return abs(float(a2) - float(b2)) < 0.006
    except ValueError:
        return False


# ---------------------------------------------------------------------------- values


def motion_values() -> Values:
    prim = ds_file("primitives")
    out: Values = {}
    for k in ("instant", "fast", "normal", "slow"):
        out[f"motion.duration.{k}"] = str(prim[f"motion.duration.{k}"]).removesuffix("ms")
    for k in ("standard", "decelerate", "accelerate"):
        curve = prim[f"motion.easing.{k}"]
        if not isinstance(curve, list):
            raise SystemExit(f"FAIL parse: motion.easing.{k} is not a cubic Bézier")
        out[f"motion.easing.{k}"] = ",".join(f"{x:g}" for x in curve)
    for k in ("compact", "comfortable"):
        out[f"ds.size.row.{k}"] = str(prim[f"size.row.{k}"])
    for name, (cid, n, pattern) in CITED_VALUES.items():
        out[name] = grab(pattern, base_line(cid, n), f"{cid}:{n} {name}").replace(",", "")
    return out


def contrast_values(peak: float) -> tuple[Values, dict[str, dict[str, float]]]:
    mjs = at_base(PAIRS_MJS_REL)
    text_bar = float(grab(r"^\s*TEXT: ([\d.]+)", mjs, "THRESHOLD.TEXT"))
    non_text_bar = float(grab(r"^\s*NON_TEXT: ([\d.]+)", mjs, "THRESHOLD.NON_TEXT"))
    out: Values = {
        "contrast.bar.text": f"{text_bar:g}",
        "contrast.bar.non-text": f"{non_text_bar:g}",
    }
    matrix: dict[str, dict[str, float]] = {}
    for name, (fg, bg, _role) in {**PAIRS, **MEASURED_ONLY}.items():
        for theme in THEMES:
            r = ratio(theme, fg, bg, peak)
            matrix.setdefault(name, {})[THEME_SHORT[theme]] = round(r, 4)
            out[f"contrast.{name}.{THEME_SHORT[theme]}"] = f"{r:.2f}"
    return out, matrix


def cvd_values() -> tuple[Values, dict[str, object]]:
    out: Values = {}
    doc: dict[str, object] = {}
    for name, (a, b) in CVD_PAIRS.items():
        for theme in THEMES:
            ha, hb = hex_of(theme, a), hex_of(theme, b)
            t = THEME_SHORT[theme]
            out[f"cvd.{name}.normal.{t}"] = f"{delta_e(ha, hb):.1f}"
            for sim in SIMS:
                d = delta_e(simulate(ha, sim), simulate(hb, sim))
                out[f"cvd.{name}.{SIM_SHORT[sim]}.{t}"] = f"{d:.1f}"
            out[f"grey.{name}.{t}"] = f"{abs(lightness(ha) - lightness(hb)):.1f}"
            doc[f"{name}.{t}"] = {"a": ha, "b": hb}
    jnd = float(grab(r"^JND = ([\d.]+)", at_base(JND_REL), "E11-D05 JND"))
    out["cvd.jnd"] = f"{jnd:.1f}"
    return out, doc


def animated(row: dict[str, str]) -> bool:
    """A motion row that moves under motion-safe: its Property is opacity or a transform."""
    prop = norm_text(col(row, "Property"))
    return prop.startswith(("opacity", "transform"))


def count_values(spec: str) -> Values:
    bd = boards(spec)
    mos = mo_rows(spec)
    drs = drift_rows(spec)
    verdicts = [norm_text(col(d, "Verdict")) for d in drs.values()]
    unresolved = [k for k, d in drs.items() if drift_problems(k, d)]
    return {
        "count.boards": str(len(bd)),
        "count.boards-light": str(len([b for b in bd if is_light(b)])),
        "count.boards-dark": str(len([b for b in bd if not is_light(b)])),
        "count.motion-rows": str(len(mos)),
        "count.motion-animated": str(len([m for m in mos.values() if animated(m)])),
        "count.mutations": str(len(MUTATIONS)),
        "count.gates": str(len(GATE_TAGS)),
        "count.drift-rows": str(len(drs)),
        "count.drift-corrected": str(verdicts.count("corrected")),
        "count.drift-justified": str(verdicts.count("justified")),
        "count.drift-unresolved": str(len(unresolved)),
        "count.inventory": str(len(inventory())),
        "count.statuses": str(len(statuses())),
        "count.gap8": str(len(GAP8)),
        "count.pairs": str(len(PAIRS)),
        "count.sec-pins": str(len(pin_rows(SEC_PIN_TXT))),
        "budget.spec-lines": str(SPEC_LINE_BUDGET),
        "budget.summary-lines": str(SUMMARY_LINES),
        "budget.reason-chars": str(REASON_MAX),
    }


Computed = tuple[Values, dict[str, object]]


def compute(spec: str) -> Computed:
    values: Values = {}
    values.update(motion_values())
    peak = float(values["cited.16.flash-peak-opacity"])
    cv, matrix = contrast_values(peak)
    values.update(cv)
    dv, colours = cvd_values()
    values.update(dv)
    values.update(count_values(spec))
    extra: dict[str, object] = {
        "contrast": matrix,
        "cvd.colours": colours,
        "inventory": list(inventory()),
        "statuses": list(statuses()),
        "tiers": list(tiers_and_b8()[0]),
        "markers": list(row_markers()),
        "b8": list(tiers_and_b8()[1]),
        "gap8": list(GAP8),
        "pairs": {k: list(v) for k, v in {**PAIRS, **MEASURED_ONLY}.items()},
    }
    return values, extra


# ---------------------------------------------------------------------------- markers (G-VALUE)

MARKER = re.compile(r"<!-- audit:([A-Za-z0-9_.\-]+)=([^ >]+) -->")
FILL = re.compile(r"\{\{audit:([A-Za-z0-9_.\-]+)\}\}")
NUMBER = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?")
FIGURE = re.compile(
    r"(?<![\w.,:#/>{-])(\d+(?:[.,]\d+)*)\s?(ms|s|hz|px|%|:1)(?![\w])", re.IGNORECASE
)
TWO_DP = re.compile(r"(?<![\w.,:#/-])\d+\.\d{2}(?![\d.])")
DELTA = re.compile(r"Δ[EL]\*?(?:76)?\s+\d")
# the copy columns a figure may sit in verbatim (fixtures, catalogue text)
COPY_HEADS = ("word", "string", "old", "cell text", "copy")


def fill(text: str, values: Values) -> tuple[str, list[str]]:
    """Replace every `{{audit:NAME}}` outside a code span with `VALUE <marker>`."""
    unknown: list[str] = []

    def sub(m: re.Match[str]) -> str:
        if m[1] not in values:
            unknown.append(m[1])
            return m[0]
        return f"{values[m[1]]} <!-- audit:{m[1]}={values[m[1]]} -->"

    out_lines = []
    for line in text.split("\n"):
        parts, pos = [], 0
        for c in CODE.finditer(line):
            parts.append(FILL.sub(sub, line[pos : c.start()]))
            parts.append(c[0])
            pos = c.end()
        parts.append(FILL.sub(sub, line[pos:]))
        out_lines.append("".join(parts))
    return "\n".join(out_lines), sorted(set(unknown))


def copy_cells(text: str) -> dict[str, set[int]]:
    """Table lines → the indexes of their verbatim copy columns (a header in COPY_HEADS)."""
    out: dict[str, set[int]] = {}
    for head, body in tables(text):
        idx = {i for i, h in enumerate(head) if norm_text(h).startswith(COPY_HEADS)}
        if not idx:
            continue
        for r in body:
            out["| " + " | ".join(r) + " |"] = idx
    return out


def bare_figures(text: str) -> list[str]:
    """Figures with a unit, two-decimal numbers and Δ values typed by hand: outside a marker
    (and the figure in front of it), a quote, a code span, a cite and a verbatim copy cell."""
    hits: list[str] = []
    copies = copy_cells(text)
    for i, line in enumerate(text.split("\n"), 1):
        if PLACEHOLDER.match(line):
            continue
        work = line
        if line.lstrip().startswith("|"):
            cells = split_row(line)
            skip = copies.get("| " + " | ".join(cells) + " |", set())
            work = " | ".join(c for j, c in enumerate(cells) if j not in skip)
        work = re.sub(r"(\d):1\b(?=\s*<!--)", r"\1", work)
        prev = 0
        parts = []
        for m in MARKER.finditer(work):
            seg = work[prev : m.start()]
            nums = list(NUMBER.finditer(seg))
            if nums:
                seg = seg[: nums[-1].start()] + " ⟨v⟩ " + seg[nums[-1].end() :]
            parts.append(seg)
            prev = m.end()
        parts.append(work[prev:])
        work = "".join(parts)
        work = QUOTED.sub(" ", CODE.sub(" ", work))
        work = re.sub(r"#\d+|\b[A-Za-z0-9.`/-]+:\d+(?:[–-]\d+)?", " ", work)
        work = re.sub(r"§\s?\d+(?:\.\d+)*|^#+\s+\d+(?:\.\d+)*", " ", work)  # section numbers
        found = [m[0] for m in FIGURE.finditer(work)] + TWO_DP.findall(work)
        found += [m[0] for m in DELTA.finditer(work)]
        hits += [f"line {i}: {f!r}" for f in found]
    return hits


def marker_problems(name: str, text: str, values: Values) -> list[str]:
    bad: list[str] = []
    for i, line in enumerate(text.split("\n"), 1):
        if PLACEHOLDER.match(line):
            continue
        spans = [c.span() for c in CODE.finditer(line)]
        prev = 0
        for m in MARKER.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue
            want = values.get(m[1])
            if want is None:
                bad.append(f"{name}:{i} marker {m[1]} is not a value the tool computes")
            elif not same(m[2], want):
                bad.append(f"{name}:{i} marker {m[1]}={m[2]}; the tool computes {want}")
            else:
                seg = re.sub(r"(\d):1\b", r"\1", line[prev : m.start()])
                nums = NUMBER.findall(seg)
                if not nums or not same(nums[-1], want):
                    got = nums[-1] if nums else "nothing"
                    bad.append(f"{name}:{i} the figure before {m[1]} reads {got}, not {want}")
            prev = m.end()
        for m in FILL.finditer(CODE.sub("", line)):
            bad.append(f"{name}:{i} {{{{audit:{m[1]}}}}} is not filled (--fill)")
    bad += [f"{name} {h}: a figure typed by hand" for h in bare_figures(text)]
    return bad


# ---------------------------------------------------------------------------- cites (G-CITE)

CITE = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:D01|D02|D03|PRIM|E\d\d-D\d\d)\b)) ?"
    r":(?P<first>\d+(?:[–-]\d+)?)(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
    r'(?: "(?P<frag>[^"\n]+)")?'
)


def lookup(lines: list[str], n: int, frag: str) -> str:
    """Where `frag` sits: "ok" on line `n`, "moved" once elsewhere, "gone" nowhere, "ambiguous"
    more than once off its line."""
    if 1 <= n <= len(lines) and frag in lines[n - 1]:
        return "ok"
    found = [i + 1 for i, ln in enumerate(lines) if frag in ln]
    if not found:
        return "gone"
    return "moved" if len(found) == 1 else "ambiguous"


def cite_problems(texts: dict[str, str], fetch: Fetch) -> tuple[list[str], list[str], int]:
    fails: list[str] = []
    warns: list[str] = []
    done: set[tuple[str, int]] = set()

    def lines_of(rev: str, rel: str) -> list[str] | None:
        t = fetch(rev, rel)
        return None if t is None else t.split("\n")

    for name, text in texts.items():
        for m in CITE.finditer(visible(text)):
            cid = m["a"] or m["b"]
            refs = [m["first"], *re.findall(r":(\d+(?:[–-]\d+)?)", m["more"])]
            rel = cite_path(cid)
            base = lines_of(BASE, rel) if rel else None
            if rel is None or base is None:
                fails.append(f"{name} `{cid}`:{refs[0]} no such file at {BASE}")
                continue
            head = lines_of(HEAD, rel)
            for ref in refs:
                for part in re.split(r"[–-]", ref):
                    n = int(part)
                    if (cid, n) in done:
                        continue
                    done.add((cid, n))
                    if n < 1 or n > len(base) or not base[n - 1].strip():
                        fails.append(f"{name} `{cid}`:{n} is missing or blank at {BASE}")
                    elif head is not None and (n > len(head) or head[n - 1] != base[n - 1]):
                        warns.append(f"[G-CITE] `{cid}`:{n} drifted at {HEAD}")
            if m["frag"]:
                where = lookup(base, int(re.split(r"[–-]", refs[0])[0]), m["frag"])
                if where in ("gone", "ambiguous"):
                    fails.append(f'{name} `{cid}`:{refs[0]} "{m["frag"][:40]}" is {where}')
                elif where == "moved":
                    warns.append(f'[G-CITE] `{cid}`:{refs[0]} "{m["frag"][:40]}" moved')
    for cid, n, frag in CITED:
        rel = cite_path(cid)
        base = lines_of(BASE, rel) if rel else None
        if base is None or lookup(base, n, frag) != "ok":
            fails.append(f'the tool\'s `{cid}`:{n} "{frag[:40]}" is not on its line at {BASE}')
    p15 = (fetch(BASE, P15_REL) or "").split("\n")
    hand = texts.get("hand-off", "")
    for r in table_a(hand):
        m2 = re.search(r"`15`:(\d+)", col(r, "Field"))
        old = col(r, "Old")
        if m2 is None or nullish(old):
            fails.append(f"Table A {col(r, 'A')}: no `15`:line or no Old text")
            continue
        where = lookup(p15, int(m2[1]), old)
        if where in ("gone", "ambiguous"):
            fails.append(f"Table A {col(r, 'A')}: the Old text is {where} in `15` at {BASE}")
        elif where == "moved":
            warns.append(f"[G-CITE] Table A {col(r, 'A')}: the Old text moved off `15`:{m2[1]}")
    return fails, warns, len(done) + len(CITED)


# ---------------------------------------------------------------------------- pins (G-PIN)


def pin_claims(clause: str) -> list[str]:
    """The pin errors of one sentence: an unknown sha; `#PR (sha)` pairs that disagree; a role
    word ("text" / "boards") or a document id next to a sha that is not that pin's."""
    bad: list[str] = []
    last = 0
    for m in re.finditer(r"`([0-9a-f]{7,40})`", clause):
        sha, start, last = m[1], last, m.end()
        pin = next((k for k in PINS if sha.startswith(k) or k.startswith(sha)), None)
        if pin is None:
            if not (sha.startswith(BASE) or BASE.startswith(sha)):
                bad.append(f"`{sha}` is neither a pin nor the base")
            continue
        pr, path = PINS[pin]
        role = "boards" if path.endswith("img/") else "text"
        before = norm_text(clause[start : m.start()])
        prm = re.search(r"#(\d{3,5})\W{0,4}$", clause[: m.start()])
        if prm and f"#{prm[1]}" != pr:
            bad.append(f"#{prm[1]} is pinned at `{sha}`, which is {pr}")
        after = norm_text(clause[m.end() :])[:14]
        paren = re.match(r"\W*\((text|boards?)\b", after)
        words = [paren[1]] if paren else re.findall(r"\b(text|boards?)\b", before)
        if words:
            said = "boards" if words[-1].startswith("board") else "text"
            if said != role:
                bad.append(f"`{sha}` is the {PIN_DOC[pin]} {role} pin, read as {said}")
        docs = re.findall(DOC_IDS, before)
        if docs and docs[-1].replace("e29 ", "") != PIN_DOC[pin]:
            bad.append(f"`{sha}` is the {PIN_DOC[pin]} pin, cited for {docs[-1]}")
    return bad


@functools.lru_cache(maxsize=1)
def pin_facts() -> tuple[str, ...]:
    bad: list[str] = []
    for sha, (pr, path) in PINS.items():
        if not git_ok("merge-base", "--is-ancestor", sha, BASE):
            bad.append(f"`{sha}` is not an ancestor of {BASE}")
        if pr not in git_out("log", "-1", "--format=%s", sha):
            bad.append(f"`{sha}` is not {pr}")
        touched = git_out("show", "--name-only", "--format=", sha).split()
        if not any(n.startswith(path) for n in touched):
            bad.append(f"`{sha}` does not touch {path}")
    return tuple(bad)


# ---------------------------------------------------------------------------- the gates


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    p15: str
    p16: str
    inputs: tuple[tuple[str, str], ...]  # (rel, text on disk) of MEASURED but `15` / `16`
    values: Values
    diff_names: tuple[str, ...]  # `git diff --name-only BASE` on disk (G-UNTOUCHED)
    pins: str  # the pinned table the security text is held to


def swept(t: Texts) -> list[str]:
    """The texts every claim sweep reads: the spec without §8.2 (its rows name the gates and
    their mutations) and the hand-off."""
    return [t.spec.replace(section(t.spec, "8.2 The gate tool"), ""), t.hand]


def without(text: str, *heads: str) -> str:
    for h in heads:
        block = section(text, h)
        if block:
            text = text.replace(block, "")
    return text


def g_value(t: Texts) -> list[str]:
    """Condition: every figure is the tool's (a marker re-derived from `--json`)."""
    bad = marker_problems("spec", t.spec, t.values) + marker_problems("hand-off", t.hand, t.values)
    return one("G-VALUE", bad)


def g_cite(t: Texts) -> list[str]:
    """Condition: every cite resolves at the base; quoted fragments and Table A's Old cells sit
    on their lines (moved: WARN; gone or ambiguous: FAIL)."""
    fails, _warns, _n = cite_problems({"spec": t.spec, "hand-off": t.hand}, git_show)
    return one("G-CITE", fails)


def g_pin(t: Texts) -> list[str]:
    """Condition: merged texts at their merge shas; every sha named is a pin or the base."""
    bad = list(pin_facts())
    lines = t.spec.split("\n")
    head = " ".join(ln for ln in lines if ln.startswith(("**Start.**", "**Inputs pinned.**")))
    for sha, (pr, _path) in PINS.items():
        if not re.search(rf"{re.escape(pr)}\W{{1,4}}`{sha}`", head):
            bad.append(f"the Start / Inputs lines do not pin {pr} at `{sha}`")
    if f"Base `origin/main` `{BASE}`" not in head or f"Base `{BASE}`" not in t.hand:
        bad.append(f"the base `{BASE}` is not named in the spec's Inputs line and the hand-off")
    bad += [f"the hand-off does not cite `{sha}`" for sha in HAND_PINS if f"`{sha}`" not in t.hand]
    for name, text in (("spec", t.spec), ("hand-off", t.hand)):
        for u in units(text):
            for s in sentences(u):
                bad += [f"{name}: {x}" for x in pin_claims(s)]
    return one("G-PIN", bad)


def g_ruled(t: Texts) -> list[str]:
    """Condition: "RULED" cites comment 6399392172; BQ-1…BQ-16 are there."""
    bad: list[str] = []
    want = f"RULED (orchestrator, comment {RULING_ID}, on the BQ list {BQ_LIST_ID})"
    heading = next((ln for ln in t.spec.split("\n") if ln.startswith("## The sixteen")), "")
    if want not in heading:
        bad.append("the RULED heading does not cite the ruling comment")
    if f"comment {RULING_ID}" not in t.hand:
        bad.append("the hand-off does not cite the ruling comment")
    for name, text in (("spec", t.spec), ("hand-off", t.hand)):
        for cid in re.findall(r"\b(?:comment|ruling|RULED) (\d{9,})", visible(text)):
            if cid not in (RULING_ID, BQ_LIST_ID):
                bad.append(f"{name}: comment {cid} is not the ruling")
    rows = table_with(section(t.spec, "The sixteen questions"), "#", "Question")
    ids = [row_key(col(r, "#")) for r in rows]
    if ids != [f"BQ-{i}" for i in range(1, BQ_COUNT + 1)]:
        bad.append(f"the BQ table is not BQ-1…BQ-{BQ_COUNT}")
    if "**Conditions (binding, same comment).**" not in section(t.spec, "The sixteen questions"):
        bad.append("the binding conditions are not restated")
    return one("G-RULED", bad)


def g_owner(t: Texts) -> list[str]:
    """BQ-2 / BQ-10 / BQ-11 / BQ-12 are owner-level: marked wherever they depart."""
    rows = table_with(section(t.spec, "The sixteen questions"), "#", "Question")
    bq = {row_key(col(r, "#")): " | ".join(r.values()) for r in rows}
    bad = [f"{k} lacks the owner mark" for k in OWNER_BQS if OWNER_MARK not in bq.get(k, "")]
    for prefix in ("### 3.3 ", "### 7.4 "):
        heading = next((ln for ln in t.spec.split("\n") if ln.startswith(prefix)), "")
        if OWNER_MARK not in heading:
            bad.append(f"the {prefix.strip('# ')} heading lacks the owner mark")
    return one("G-OWNER", bad)


def g_ac(t: Texts) -> list[str]:
    """BQ-2: AC1, AC3 and DoD 1–2 are met as copy-ready A-rows, applied by E29-T09."""
    rows = table_with(section(t.spec, "Acceptance-criteria trace"), "Ticket item", "Status")
    bad: list[str] = []
    for item in ("AC1 —", "AC3 —", "DoD 1 "):
        r = next((x for x in rows if col(x, "Ticket item").startswith(item)), None)
        status = col(r, "Status") if r else ""
        if "met as copy-ready A-rows" not in status or OWNER_MARK not in status:
            bad.append(f"trace row {item.strip(' —')} is not met as copy-ready A-rows")
        elif APPLIER not in status:
            bad.append(f"trace row {item.strip(' —')} does not name {APPLIER}")
    r2 = next((x for x in rows if col(x, "Ticket item").startswith("AC2 —")), None)
    if r2 is None or "prefers-reduced-motion" not in " | ".join(r2.values()):
        bad.append("trace row AC2 does not name the `prefers-reduced-motion` twin")
    return one("G-AC", bad)


def g_crow(t: Texts) -> list[str]:
    """The owner-level and merged-rule departures each have their C-row (§7.2)."""
    if pending(t.spec, "7.2 Contradictions"):
        return []
    rows = c_rows(t.spec)
    bad: list[str] = []
    ids = list(rows)
    if ids != [f"D04-C{i}" for i in range(1, len(ids) + 1)]:
        bad.append("the C-rows are not D04-C1… in order")
    texts = {k: norm_text(" | ".join(r.values())) for k, r in rows.items()}
    need = {
        "the DoD wording (BQ-2)": (r"\bdod\b", r"copy ready", True),
        'the ticket\'s "shimmer" (BQ-10)': (r"\bshimmer\b", r"\bstate\b", True),
        "timed state swaps (BQ-11)": (r"\bframe 0\b", r"\bstate", True),
        "token names and drift (BQ-12)": (r"\btoken", r"\ba rows?\b", True),
        'the ticket\'s "optimistic" (BQ-5)': (r"\boptimistic", r"\bpending\b", False),
        "the `16`:179 tint (BQ-9)": (r"\b16:179\b", r"\btint\b", False),
    }
    for what, (a, b, owner) in need.items():
        hit = [k for k, x in texts.items() if re.search(a, x) and re.search(b, x)]
        if not hit:
            bad.append(f"no C-row records {what}")
        elif owner and not any(OWNER_MARK in " | ".join(rows[k].values()) for k in hit):
            bad.append(f"the C-row for {what} lacks the owner mark")
    return one("G-CROW", bad)


NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "twenty": 20,
}  # fmt: skip


def g_boards(t: Texts) -> list[str]:
    """RULED BQ-15: at most ten boards, light twins at most a third, each the twin of a dark
    board; numbered 01…n; every board PENDING; any board count in the text is the table's."""
    bd = boards(t.spec)
    bad: list[str] = []
    rows = table_with(section(t.spec, "0. Planned boards"), "#", "Board")
    bad += [f"§0 row {col(r, '#')!r} is not a board number" for r in rows if r not in bd]
    if len(bd) > MAX_BOARDS:
        bad.append(f"{len(bd)} boards > {MAX_BOARDS}")
    nums = [col(b, "#").strip() for b in bd]
    if nums != [f"{i:02d}" for i in range(1, len(bd) + 1)]:
        bad.append("the boards are not numbered 01…n")
    light = [b for b in bd if is_light(b)]
    if 3 * len(light) > len(bd) or len(light) > LIGHT_BOARDS:
        bad.append(
            f"{len(light)} light twins of {len(bd)} boards (at most a third, {LIGHT_BOARDS})"
        )
    dark = {col(b, "#").strip() for b in bd if not is_light(b)}
    for b in light:
        m = re.search(r"light twin of (\d\d)", col(b, "Draws"))
        if m is None or m[1] not in dark:
            bad.append(f"board {col(b, '#')} is not the light twin of a dark board")
    bad += [f"board {col(b, '#')} is not PENDING" for b in bd if "PENDING" not in col(b, "Status")]
    for name, text in (("spec", t.spec), ("hand-off", t.hand)):
        for m in re.finditer(
            r"\b(\w+) (?:planned |penpot |drawn |dark )?boards\b", norm_text(text)
        ):
            n = NUMBER_WORDS.get(m[1]) if not m[1].isdigit() else int(m[1])
            if n is not None and n not in (len(bd), MAX_BOARDS) and n > 1:
                bad.append(f"{name} says {m[0]!r}; §0 has {len(bd)}")
        for m in re.finditer(r"E29-D04 / (\d+) ", visible(text)):
            if m[1] not in nums:
                bad.append(f"{name} names board {m[1]}, which §0 does not have")
    return one("G-BOARDS", bad)


def g_budget(t: Texts) -> list[str]:
    """RULED BQ-1: the spec at most 600 lines; §9 at most ten."""
    n = t.spec.count("\n") + (0 if t.spec.endswith("\n") else 1)
    bad = [f"the spec has {n} lines > {SPEC_LINE_BUDGET}"] if n > SPEC_LINE_BUDGET else []
    if not pending(t.spec, "9. Summary"):
        body = [ln for ln in section(t.spec, "9. Summary").split("\n")[1:] if ln.strip()]
        if len(body) > SUMMARY_LINES:
            bad.append(f"§9 has {len(body)} lines > {SUMMARY_LINES}")
    return one("G-BUDGET", bad)


HAND_SECTIONS = ("§A", "§B", "§C", "§D", "§E", "§F")
HAND_C = ("C.1 A-1", "C.2 A-2", "C.3 A-3", "C.4 A-4", "C.5 Table A", "C.6 The `16` block")


def g_handoff(t: Texts) -> list[str]:
    """RULED BQ-1: one hand-off file, §A–§F in order, §C's six blocks."""
    heads = re.findall(r"^## (§[A-Z]) ", t.hand, MULTI)
    bad = [] if heads == list(HAND_SECTIONS) else [f"hand-off sections {heads}"]
    bad += [f"hand-off §C has no {h}" for h in HAND_C if not section(t.hand, h)]
    return one("G-HANDOFF", bad)


def g_untouched(t: Texts) -> list[str]:
    """RULED BQ-2: `15` and `16` byte-identical to the base, in the tree and on the branch; the
    measured inputs (token JSON, the two helpers) too."""
    bad: list[str] = []
    if t.p15 != at_base(P15_REL):
        bad.append("`15` differs from the base")
    if t.p16 != at_base(P16_REL):
        bad.append("`16` differs from the base")
    bad += [f"{rel} differs from the base" for rel, text in t.inputs if text != at_base(rel)]
    bad += [f"{n} changed on the branch" for n in t.diff_names if n in MEASURED]
    return one("G-UNTOUCHED", bad)


def g_placeholder(t: Texts) -> list[str]:
    """No `> **To write (` line is left (the skeleton's sections)."""
    bad: list[str] = []
    for name, text in (("spec", t.spec), ("hand-off", t.hand)):
        lines = text.split("\n")
        fence = fenced(lines)
        current = "preamble"
        for i, ln in enumerate(lines):
            m = HEADING.match(ln)
            if m and not fence[i]:
                current = m[2][:28]
            if PLACEHOLDER.match(ln):
                bad.append(f"{name} {current}")
    return one("G-PLACEHOLDER", [f"{len(bad)} sections to write: " + ", ".join(bad)] if bad else [])


def mutation_groups() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for mu in MUTATIONS:
        groups.setdefault(mu.gate, []).append(mu.mid)
    return groups


def g_mutlist(t: Texts) -> list[str]:
    """§8.2 lists every gate with exactly the mutations the tool applies to it."""
    if pending(t.spec, "8.2 The gate tool"):
        return []
    listed: dict[str, list[str]] = {}
    for r in gate_rows(t.spec):
        gate = re.sub(r"[`*]", "", col(r, "Gate")).strip()
        listed[gate] = re.findall(r"\bM\d+(?:\.\d+)?\b", col(r, "Mutations"))
    want = mutation_groups()
    bad = [f"§8.2 has no row for {g}" for g in GATE_TAGS if g not in listed]
    bad += [f"§8.2 lists {g}, which the tool does not have" for g in listed if g not in GATE_TAGS]
    for g, mids in want.items():
        if g in listed and listed[g] != mids:
            bad.append(f"§8.2 {g} lists {len(listed[g])} mutations; the tool has {len(mids)}")
    return one("G-MUTLIST", bad)


# ---- motion (RULED BQ-9, BQ-10, BQ-11)

MOVE_VERBS = (
    r"cross ?fad\w*|\bfad(?:e|es|ed|ing)\b|\btween\w*|\beas(?:e|es|ed|ing)\b|\bslid(?:e|es|ing)\b"
    r"|\bscal(?:e|es|ed|ing)\b(?! of)|\bsweep\w*|\bmov(?:e|es|ed|ing)\b|\btranslat\w*|\bglid\w*"
    r"|\banimat\w*|\bdrift\w*|\binterpolat\w*|\bbounc\w*|\bzoom\w*|\bdissolv\w*|\bblend\w*"
    r"|\bmorph\w*|\bwip(?:e|es|ed|ing) (?:in|down|out)\b|\broll(?:s|ed|ing)? (?:in|down|out)\b"
    r"|\bgrow(?:s|n|ing)?\b|\bshrink\w*|\bpops? in\b|\bspin\w*|\brotat\w*"
)
TIMED = (
    r"\b(?!0 )\d[\d,]*(?:\.\d+)? ?(?:ms|milliseconds?)\b|\bmilliseconds?\b"
    r"|motion\.duration\.(?:fast|normal|slow)\b|\beas(?:e|es|ed|ing)\b|\bbezier\b|motion\.easing"
    r"|\blinear\b|\bover (?:the )?(?:motion\.duration\.)?(?:fast|normal|slow)\b"
    r"|\b(?:fast|normal|slow) / (?:standard|decelerate|accelerate)\b|\bgradual\w*|\bsmooth\w*"
)
TWIN = "prefers-reduced-motion"
TWIN_NULL = (
    r"\bnone\b|\bn ?/ ?a\b|\bsame as (?:the )?(?:motion )?safe\b|\bunchanged\b|\bas above\b"
    r"|\bno (?:reduced (?:motion )?|prefers reduced motion )?(?:variant|twin|reading)\b|\btb[dc]\b"
)
TWIN_OK = (
    r"\bframe 0\b|\bsteps?\b|\binstant\w*|\bstatic\b|\bno flash\b|\bno highlight\b|\bcut\b"
    r"|\bswaps?\b|\bat once\b|\bno motion\b|\bper cmp \d{3}\b|\bnone moves\b"
)
TWIN_MISSING = (
    r"\b(?:no|without|lacks?|lacking|missing)\s+(?:a |an |its |any )?"
    r"(?:reduced(?: motion)? |prefers reduced motion |motion reduce )?(?:variant|twin|reading)\b"
)
CARRIER = (
    r"\bwords?\b|\bglyphs?\b|\btext\b|\bsign\b|\bmarkers?\b|\bdelta\b|\bvalues?\b|\btags?\b"
    r"|▲|▼|\blabels?\b|\bthe change\b"
)
# where a reduced reading starts in a raw sentence: what follows it must not move
RAW_REDUCED = re.compile(
    r"\bunder (?:the )?(?:reduced? motion|reduce|prefers-reduced-motion)\b|\breduced motion\b"
    r"|\b(?:its |the |a |every |each )?(?:reduced? |motion )?twins?\b"
    r"|prefers-reduced-motion|data-motion=\"?reduce|\breduce mode\b|\bwhen (?:motion is )?reduced\b",
    re.IGNORECASE,
)
NON_COMPOSITOR = (
    r"\b(?:height|width|top|left|right|bottom|margins?|padding|box shadow|shadows?|filter"
    r"|clip path|border(?: width| colou?r)?|outline|font size|line height|inset|max height"
    r"|layout|reflow|background(?: colou?r| position)?)\b|\bcolou?r tweens?\b"
)
PROPERTY_OK = re.compile(r"^(?:opacity|transform(?:: ?[a-z]+(?:\([^)]*\))?)?|none|by reference)\b")
DATA_ROW = r"\b(?:data )?rows?\b|\bcells?\b|\bgrid\b|\bblotter\b|\bcmp 11[456]\b|\bbadges?\b"
EASING_WORDS = (
    r"\blinear\b|\bease in\b|\bease out\b|\bease in out\b|\bsteps\(|\bspring\w*|\bbounce\w*"
    r"|cubic bezier"
)
LONG = (
    r"motion\.duration\.slow|\bover (?:the )?(?:(\d[\d,]*) ?ms|(\d+(?:\.\d+)?) ?s)\b"
    r"|\b(?:lasts?|lasting|takes?|runs?(?: for)?) (?:for )?(\d[\d,]*) ?ms\b"
)


def ms_of(text: str) -> list[float]:
    """Every duration a cell binds, in ms: shipped tokens and hand-typed figures."""
    prim = ds_file("primitives")
    plain = _HIDDEN.sub(" ", text)
    out = [
        float(str(prim[f"motion.duration.{k}"]).removesuffix("ms"))
        for k in re.findall(r"motion\.duration\.([a-z-]+)", plain)
        if f"motion.duration.{k}" in prim
    ]
    out += [float(x.replace(",", "")) for x in re.findall(r"(\d[\d,]*(?:\.\d+)?) ?ms\b", plain)]
    out += [1000 * float(x) for x in re.findall(r"(\d+(?:\.\d+)?) ?s\b", plain)]
    return out


def motion_ready(t: Texts) -> bool:
    return not pending(t.spec, "3.2 The motion table")


def g_row200(t: Texts) -> list[str]:
    """RULED BQ-9 / BQ-12: no motion row longer than `motion.duration.normal`; `slow` never on a
    row; no sentence gives a data row a longer motion."""
    cap = float(t.values["motion.duration.normal"])
    bad: list[str] = []
    if motion_ready(t):
        for k, r in mo_rows(t.spec).items():
            cells = " ".join(col(r, c) for c in ("Property", "Duration", "Easing"))
            if "motion.duration.slow" in cells:
                bad.append(f"{k} binds `motion.duration.slow`")
            longest = max(ms_of(cells) or [0.0])
            if longest > cap:
                bad.append(f"{k} runs {longest:g} ms > {cap:g} ms")
            easing = col(r, "Easing")
            curves = re.findall(r"motion\.easing\.[a-z-]+", easing)
            if any(c not in ds_names() for c in curves) or live(easing, EASING_WORDS):
                bad.append(f"{k} eases on a curve that is not shipped")
    for text in (without(x, "3.2 The motion table", "C.6 The `16` block") for x in swept(t)):
        for u in units(text):
            for s in sentences(u):
                b = blanked(s)
                for m in re.finditer(LONG, b):
                    ms, sec = m[1] or m[3], m[2]
                    long_one = m[0].startswith("motion.duration.slow") or bool(
                        (ms and float(ms.replace(",", "")) > cap)
                        or (sec and 1000 * float(sec) > cap)
                    )
                    around = b[max(0, m.start() - 48) : m.end() + 48]
                    if long_one and re.search(DATA_ROW, around):
                        bad.append(f"claim: {b[:60]!r}")
                        break
    return one("G-ROW-200", bad)


def g_compositor(t: Texts) -> list[str]:
    """T Perf / RULED BQ-9: Property is opacity, a transform or none (a cut); no sentence
    animates a layout or paint property."""
    bad: list[str] = []
    if motion_ready(t):
        for k, r in mo_rows(t.spec).items():
            prop = norm_text(col(r, "Property"))
            if not PROPERTY_OK.match(prop) or re.search(NON_COMPOSITOR, prop):
                bad.append(f"{k} Property {col(r, 'Property')[:30]!r}")
    texts = [without(x, "3.2 The motion table", "C.6 The `16` block") for x in swept(t)]
    moving = MOVE_VERBS + "|" + TIMED + r"|\btransition\w*"
    for c in pair_claims(texts, NON_COMPOSITOR, moving, 4):
        bad.append(f"claim: {c!r}")
    return one("G-COMPOSITOR", bad)


def twin_body(cell: str) -> str | None:
    m = re.match(r"\s*`?prefers-reduced-motion`?:\s*(.*)$", cell.strip(), re.DOTALL)
    return m[1] if m else None


def twin_ok(cell: str) -> bool:
    """A twin states its instant reading; a twin that moves is G-REDUCE-INSTANT's."""
    body = twin_body(cell)
    if body is None or nullish(body):
        return False
    if live(body, MOVE_VERBS) or live(body, TIMED):
        return True
    n = norm_text(unquote(body))
    return re.search(TWIN_NULL, n) is None and re.search(TWIN_OK, n) is not None


def g_twin(t: Texts) -> list[str]:
    """AC2 / RULED BQ-9: every motion row and every `16`-block row has its twin, and an animated
    row's twin names what still carries the change."""
    bad: list[str] = []
    if motion_ready(t):
        rows = mo_rows(t.spec)
        if not rows:
            bad.append("§3.2 has no motion rows")
        for k, r in rows.items():
            twin = col(r, TWIN)
            body = twin_body(twin) or ""
            moving = live(body, MOVE_VERBS) or live(body, TIMED)  # G-REDUCE-INSTANT's
            if not twin_ok(twin):
                bad.append(f"{k}: no `prefers-reduced-motion` twin")
            elif animated(r) and not moving and not live(body, CARRIER):
                bad.append(f"{k}: the twin does not name what carries the change")
        table = table_with(section(t.spec, "3.2 The motion table"), "Property")
        bad += [f"{col(r, 'Mo')[:12]!r} is not a motion-row id" for r in table
                if not re.fullmatch(MO_ID, col(r, "Mo"))]  # fmt: skip
    if not pending(t.hand, "C.6 The `16` block"):
        rows16 = block16_rows(t.hand)
        if not rows16:
            bad.append("the `16` block has no rows")
        for r in rows16:
            enter = col(r, "Enter")
            m = re.search(r"`?prefers-reduced-motion`?:\s*([^;|]*)", enter)
            if m is None or not twin_ok(f"{TWIN}: {m[1]}"):
                bad.append(f"`16` block {col(r, 'Surface')[:24]!r}: no twin in Enter")
    for text in swept(t):
        for u in units(text):
            for s in sentences(u):
                n = norm_text(s)
                if re.search(TWIN_MISSING, n) and not re.search(r"\bthe tool\b|\bfails?\b", n):
                    bad.append(f"claim: {n[:60]!r}")
    return one("G-TWIN", bad)


def g_reduce_instant(t: Texts) -> list[str]:
    """AC2 / RULED BQ-9: every twin is instant; nothing moves under reduced motion."""
    bad: list[str] = []
    if motion_ready(t):
        for k, r in mo_rows(t.spec).items():
            body = twin_body(col(r, TWIN)) or ""
            if live(body, MOVE_VERBS) or live(body, TIMED):
                bad.append(f"{k}: the twin moves")
        if "every twin is instant" not in norm_text(section(t.spec, "3.6 Reduced motion")):
            bad.append("§3.6 does not state that every twin is instant")
    for r in block16_rows(t.hand):
        for m in re.finditer(r"`?prefers-reduced-motion`?:\s*([^;|]*)", col(r, "Enter")):
            if live(m[1], MOVE_VERBS) or live(m[1], TIMED):
                bad.append(f"`16` block {col(r, 'Surface')[:24]!r}: the twin moves")
    texts = [without(x, "3.2 The motion table", "C.6 The `16` block") for x in swept(t)]
    for text in texts:
        for u in units(text):
            for s in sentences(u):
                at = RAW_REDUCED.search(s)
                if at and (live(s[at.start() :], MOVE_VERBS) or live(s[at.start() :], TIMED)):
                    bad.append(f"claim: {norm_text(s)[:60]!r}")
    return one("G-REDUCE-INSTANT", bad)


KIND = (
    r"status words?|state words?|labels?|glyphs?|icons?"
    r"|(?:state|status|tag|chip|pill|tier|marker|badge|background) fills?|fill colou?rs?"
    r"|fill tones?|pills?|tags?|badges?|markers?|protection chips?|chips?"
    r"|liq(?:uidation)? tiers?|tiers?|t2|lock(?: glyph)?|enabled|disabled|demo|live(?! regions?)"
    r"|environment pills?|env pills?|states?|status"
)
# a frame whose id names a state (a status, a liq tier, a chip state, T2, the display or the
# toggle): its Motion names a cut row only
SWAP_FRAME = re.compile(r"/(?:status|liq|sl|t2|display|toggle|amend|env)-")
SWAP_ROW = (
    r"\bstate (?:swaps?|changes?|transitions?|flips?)\b|\bstatus (?:swaps?|changes?|transitions?)\b"
    r"|↔|\bswaps?\b"
)


def g_instant(t: Texts) -> list[str]:
    """RULED BQ-11: every state swap is a cut at frame 0 in both modes — status words, glyphs,
    fills, pills, the liq tier, the protection chip, T2 ↔ enabled and DEMO / LIVE —
    `motion.duration.instant`, no easing; no sentence or row animates one."""
    bad: list[str] = []
    if motion_ready(t):
        swaps = 0
        for k, r in mo_rows(t.spec).items():
            subject = norm_text(col(r, "Component") + " " + col(r, "Trigger"))
            if not re.search(SWAP_ROW, subject):
                continue
            swaps += 1
            if not norm_text(col(r, "Property")).startswith("none"):
                bad.append(f"{k} (a state swap) has Property {col(r, 'Property')[:20]!r}")
            dur = col(r, "Duration")
            names = set(re.findall(r"motion\.duration\.[a-z-]+", dur))
            if names != {"motion.duration.instant"} or any(ms_of(dur)):
                bad.append(f"{k} (a state swap) binds {sorted(names) or dur[:20]!r}")
            easing = col(r, "Easing")
            if "motion.easing" in easing or live(easing, MOVE_VERBS + "|" + TIMED):
                bad.append(f"{k} (a state swap) eases")
        if not swaps:
            bad.append("§3.2 has no state-swap row (a cut)")
    if not pending(t.spec, "3.3 State swaps"):
        s33 = norm_text(section(t.spec, "3.3 State swaps"))
        bad += [f"§3.3 does not name {k}" for k, rx in SWAP_KINDS.items() if not re.search(rx, s33)]
        for phrase in ("frame 0", "both modes", "no easing"):
            if phrase not in s33:
                bad.append(f"§3.3 does not say {phrase!r}")
    rows = mo_rows(t.spec) if motion_ready(t) else {}
    cuts = {k for k, r in rows.items() if norm_text(col(r, "Property")).startswith("none")}
    for head, r in all_state_rows(t.spec):
        if pending(t.spec, head):
            continue
        frame, motion = col(r, "Frame"), col(r, "Motion")
        if live(motion, MOVE_VERBS) or live(motion, TIMED):
            bad.append(f"{frame[:32]}: a state frame that moves ({motion[:24]!r})")
        refs = [row_key(x) for x in re.findall(r"\bMo[- ]\d+\b", motion)]
        if rows and any(x not in rows for x in refs):
            bad.append(f"{frame[:32]}: names a motion row §3.2 does not have")
        if rows and SWAP_FRAME.search(frame) and any(x not in cuts for x in refs):
            bad.append(f"{frame[:32]}: a state swap that names an animated row")
    for r in block16_rows(t.hand):
        enter = col(r, "Enter")
        if re.search(SWAP_ROW, norm_text(col(r, "Surface"))) and (
            "frame 0" not in norm_text(enter) or live(enter, MOVE_VERBS) or live(enter, TIMED)
        ):
            bad.append(f"`16` block {col(r, 'Surface')[:24]!r} (a state swap) is not a cut")
    texts = [without(x, "3.2 The motion table", "C.6 The `16` block") for x in swept(t)]
    bad += [f"claim: {c!r}" for c in pair_claims(texts, KIND, MOVE_VERBS + "|" + TIMED, 3)]
    return one("G-INSTANT", bad)


LOOP_WORDS = (
    r"shimmer\w*|\bpuls(?:e|es|ed|ing|at\w*)\b|\bloop\w*|\bthrob\w*|\bblink\w*|\bflicker\w*"
    r"|\bstrob(?:e|es|ing|oscop\w*)\b|\bbreath(?:e|es|ed|ing)\b|\bglimmer\w*|\btwinkl\w*"
    r"|\bsparkl\w*|\boscillat\w*|\binfinite\w*"
)
TICKET_UNIT = r"\bticket'?s?\b|\bt scope\b|\bdl 7\b"


def g_loop(t: Texts) -> list[str]:
    """RULED BQ-10: no shimmer, pulse or loop anywhere (case-insensitive) — only the ticket's own
    word, quoted where its departure is recorded."""
    bad = [f"claim: {c!r}" for c in claims(swept(t), LOOP_WORDS)]
    for text in swept(t):
        for u in units(text):
            for q in QUOTED.findall(u):
                if re.search(LOOP_WORDS, norm_text(q)) and not re.search(TICKET_UNIT, norm_text(u)):
                    bad.append(f"quoted {norm_text(q)[:40]!r} outside the ticket's departure")
    return one("G-LOOP", bad)


PER_TICK = (
    r"\b(?:per|every|each|on|with|at|for)\s+(?:each\s+|every\s+|a\s+|the\s+|single\s+)?"
    r"(?:(?:price|mark|market|ws|data|value|feed|book|order|row)\s+)*"
    r"(?:ticks?|updates?|messages?|prints?|trades?|deltas?)\b"
    r"|\bper ?tick\b|\btick by tick\b|\btick rate\b|\btick driven\b"
)
MOTIONISH = (
    MOVE_VERBS + r"|\bflash\w*|\bhighlight\w*|\boverlays?\b|\btransition\w*|\bpuls\w*|\bblink\w*"
)
LIMIT_OK = r"between starts|\bonce\b|\bone shot\b|\bat most\b|≤|\bno repeat\b"
NUMBERISH = (
    r"\b(?:digits?|numbers?|numerals?|prices?|sizes?|values?|figures?|pnl|quantit\w*|qty|totals?)\b"
)
TWEEN = (
    r"count(?:s|ing|ed)? (?:up|down)|\btween\w*|interpolat\w*|roll(?:s|ing)? (?:up|over)|odometer"
)


def g_tick(t: Texts) -> list[str]:
    """RULED BQ-9 / BQ-11: nothing animates per tick or per price update; every animated row
    states its limit, the flash at most `05`'s rate."""
    bad = [f"claim: {c!r}" for c in pair_claims(swept(t), MOTIONISH, PER_TICK, 4)]
    cap = float(t.values["cited.05.flash-max-per-s"])
    if motion_ready(t):
        for k, r in mo_rows(t.spec).items():
            if not animated(r):
                continue
            limit = norm_text(_HIDDEN.sub(" ", col(r, "Limit")))
            if not re.search(LIMIT_OK, limit):
                bad.append(f"{k} animates with no stated limit")
            for gap in re.findall(r"≥ ?(\d[\d,]*) ?ms between starts", limit):
                if 1000 / float(gap.replace(",", "")) > cap:
                    bad.append(f"{k} starts more often than {cap:g} per second")
    bad += [f"claim (tween): {c!r}" for c in pair_claims(swept(t), NUMBERISH, TWEEN, 4)]
    s34 = section(t.spec, "3.4 Never per tick")
    if not pending(t.spec, "3.4 Never per tick") and "per tick" not in norm_text(s34):
        bad.append("§3.4 does not state the per-tick rule")
    return one("G-TICK", bad)


# ---- the components (RULED BQ-5, BQ-7, BQ-8, BQ-14)

PENDING_NEAR = r"\bpending\b|\bamend(?:ing|s)?\b|\boptimistic\w*|\bunconfirmed\b|\bin flight\b"
AS_CONFIRMED = (
    r"\b(?:as|like) (?:if )?(?:confirmed|applied|accepted|final|filled|committed|done)\b"
    r"|\boptimistically\b|\bbefore (?:the |an? |bybit'?s? )?(?:ack\w*|acknowledg\w*|confirmation)\b"
    r"|\bpaints? the new (?:price|value)\b"
)


def g_pending(t: Texts) -> list[str]:
    """RULED BQ-5: a pending or optimistic row is a state — the ⟳ marker, the tag and the
    "still live" words — never drawn as confirmed."""
    bad: list[str] = []
    if not pending(t.spec, "2.2 CMP-115"):
        rows = [r for r in state_rows(t.spec, "2.2 CMP-115") if re.search(
            r"\bpending\b|\boptimistic", norm_text(col(r, "State")))]  # fmt: skip
        if not rows:
            bad.append("§2.2 has no pending frame")
        for r in rows:
            f = col(r, "Frame")[:32]
            if "still live" not in col(r, "Word"):
                bad.append(f'{f}: the Word does not keep the live value ("still live")')
            if "⟳" not in col(r, "Glyph") and "refresh" not in col(r, "Glyph"):
                bad.append(f"{f}: no ⟳ marker")
            if "color.status.info.subtle" not in col(r, "Fill"):
                bad.append(f"{f}: the tag is not on `color.status.info.subtle`")
            if live(" | ".join(r.values()), r"\bconfirmed\b|\bapplied\b"):
                bad.append(f"{f}: drawn as confirmed")
    for head, r in all_state_rows(t.spec):
        if pending(t.spec, head) or head.startswith("2.2 "):
            continue
        if not re.search(r"\bpending\b|\boptimistic", norm_text(col(r, "State") + col(r, "Frame"))):
            continue
        word = norm_text(col(r, "Word"))
        if not re.search(r"\bpending\b|\bstill live\b|\bchecking\b|⟳", word) or live(
            " | ".join(r.values()), r"\bconfirmed\b|\bapplied\b"
        ):
            bad.append(f"{col(r, 'Frame')[:32]}: a pending frame drawn as confirmed")
    bad += [f"claim: {c!r}" for c in pair_claims(swept(t), PENDING_NEAR, AS_CONFIRMED, 6)]
    return one("G-PENDING", bad)


FLATTEN_NEAR = r"\bflatten\w*|\bcmp 123\b|\bflattenallbutton\b|\bclose all\b|\bcancel all\b"
LIVE_ENV = r"\blive\b(?! regions?)"
HOLD_ONLY = (
    r"\bhold (?:or|/) (?:a |the )?typed\b|\btyped (?:or|/) (?:a |the )?hold\b"
    r"|\b(?:hold|typed)[- ]only\b|\b(?:hold|typed)(?: confirm\w*| word)? (?:alone|only)\b"
    r"|\bonly (?:a |the )?(?:hold|typed)\b|\beither (?:a |the )?(?:hold|typed)\b"
    r"|\bwithout (?:a |the )?(?:hold|typed)\b|\b(?:drops?|skips?|omits?) (?:a |the )?(?:hold|typed)\b"
)
HOLD_HOSTS = (
    "2.1 ",
    "2.2 ",
    "2.3 ",
    "2.5 ",
    "2.6 ",
    "2.7 ",
    "2.8",
    "2.9 ",
    "2.10 ",
    "3. The motion spec",
    "4. T2",
    "6. Copy keys",
)


def g_flatten(t: Texts) -> list[str]:
    """RULED BQ-7 / AC3: CMP-123's confirm is a composite — hold AND typed on LIVE — defined
    once in §2.4; no host restates its hold."""
    bad: list[str] = []
    if not pending(t.spec, "2.4 CMP-123"):
        rows = table_with(section(t.spec, "2.4 CMP-123"), "Environment", "Confirm")
        lives = [r for r in rows if "LIVE" in col(r, "Environment")]
        if not lives:
            bad.append("§2.4 has no LIVE confirm row")
        for r in lives:
            c = norm_text(col(r, "Confirm"))
            both = re.search(r"\bhold\b.*\b(?:and|\+|plus|then|with)\b.*\btyped\b", c) or re.search(
                r"\btyped\b.*\b(?:and|\+|plus|then|with)\b.*\bhold\b", c
            )
            if not both or re.search(r"\bhold\b[^|]*\bor\b[^|]*\btyped\b|\beither\b", c):
                bad.append("the LIVE confirm is not hold and typed")
        if not any("DEMO" in col(r, "Environment") and "hold" in col(r, "Confirm") for r in rows):
            bad.append("§2.4 has no DEMO hold row")
    for text in swept(t):
        for u in units(text):
            for s in sentences(u):
                n = DOUBLE_NEG.sub(" ", norm_text(unquote(s)))
                if (
                    re.search(FLATTEN_NEAR, n)
                    and re.search(LIVE_ENV, n)
                    and re.search(HOLD_ONLY, n)
                ):
                    bad.append(f"claim: {n[:60]!r}")
    hold = t.values.get("cited.cmp044.hold-ms", "")
    for head in HOLD_HOSTS:
        block = section(t.spec, head)
        if not block or pending(t.spec, head):
            continue
        if "audit:cited.cmp044.hold-ms=" in block or re.search(rf"\b{hold}\s*ms\b", visible(block)):
            bad.append(f"§{head.split(' ')[0].rstrip('.')} restates the hold (AC3: §2.4 only)")
    return one("G-FLATTEN", bad)


CONTROL_ROLE = (
    r"\brole ?= ?\W?(?:radio(?:group)?|button|switch|checkbox|option|menuitem\w*|tab|slider"
    r"|spinbutton|combobox|listbox|textbox)\b|\btabindex\b|\btab stop\b|\bfocusable\b"
    r"|\baria (?:checked|pressed|disabled|selected)\b|\bcontrol role\b|\bradiogroup\b"
)
T2_TERMS = r"\bt2\b|\block\b|\baria disabled\b|\bcmp 079\b|\bnot_available\b|\brbac\.\w+"
DISPLAY_NEAR = r"\bdisplay (?:variant|frames?|mode)\b|\bread only display\b|cmp 129/display"


def g_display(t: Texts) -> list[str]:
    """RULED BQ-8: CMP-129's `display` variant has no control role and no T2."""
    bad: list[str] = []
    if not pending(t.spec, "2.5 CMP-129"):
        rows = [r for r in state_rows(t.spec, "2.5 CMP-129") if "/display" in col(r, "Frame")]
        if not rows:
            bad.append("§2.5 has no display frame")
        for r in rows:
            f = col(r, "Frame")[:32]
            if not nullish(col(r, "T2")):
                bad.append(f"{f}: T2 {col(r, 'T2')[:20]!r}")
            cells = " | ".join(v for k, v in r.items() if k != "T2")
            if live(cells, CONTROL_ROLE) or live(cells, T2_TERMS):
                bad.append(f"{f}: a control role or the T2 look")
    terms = CONTROL_ROLE + "|" + T2_TERMS
    bad += [
        f"claim: {c!r}" for c in pair_claims(swept(t), DISPLAY_NEAR, terms, 6, keep_quotes=True)
    ]
    return one("G-DISPLAY", bad)


# ---- T2, view-as, environment (RULED BQ-13)


def leg_rank(leg: str) -> int:
    """The server's leg order (E09-D09 §2.1): view-as, permission, scope / grant, `rbac.env`,
    then the client states."""
    if leg == "rbac.view_as":
        return 0
    if leg in ("rbac.permission", "rbac.owner_only"):
        return 1
    if leg in ("rbac.account", "rbac.account_read_only"):
        return 2
    if leg == "rbac.env":
        return 3
    return 4


LEG_WORDS: tuple[tuple[str, int], ...] = (
    (r"\bview ?as\b|rbac\.view_as", 0),
    (r"\bpermission\b|rbac\.permission|\bowner only\b|rbac\.owner_only", 1),
    (r"\baccount scope\b|\bread only grant\b|rbac\.account(?:_read_only)?\b", 2),
    (r"rbac\.env\b", 3),
    (r"\bclient states?\b|\bfrozen\b|\blockout\b|recon\.|feed\.|arm\.", 4),
)
HIDDEN_FOR = r"\bhidden\b|\bhid(?:e|es|ing)\b|\bnot_shown\b|\bnot_offered\b|\babsent\b"
HIDDEN_NEAR = r"\bviewer\w*\b|\bview ?as\b|\bmanagers?\b(?! (?:is|are) not offered)"


def legs_of(cell: str) -> list[str]:
    return re.findall(r"`([a-z][a-z_]*(?:\.[a-z_{}*]+)+|frozen|lockout)`", cell)


def g_viewas(t: Texts) -> list[str]:
    """RULED BQ-13: every gated control's legs start at view-as and follow the server's order;
    no sentence orders them otherwise; nothing is hidden from a Viewer."""
    bad: list[str] = []
    if not pending(t.spec, "4.1 The gated controls"):
        rows = gated_rows(t.spec)
        if not rows:
            bad.append("§4.1 has no gated controls")
        for r in rows:
            legs = legs_of(col(r, "Legs"))
            if not legs:
                continue
            name = col(r, "Control")[:24]
            if legs[0] != "rbac.view_as":
                bad.append(f"{name}: the first leg is {legs[0]}, not view-as")
            ranks = [leg_rank(k) for k in legs]
            if ranks != sorted(ranks):
                bad.append(f"{name}: the legs are out of the server's order")
    for text in swept(t):
        for u in units(text):
            for s in sentences(u):
                n = norm_text(s)
                found = sorted(
                    (m.start(), rank) for rx, rank in LEG_WORDS for m in re.finditer(rx, n)
                )
                ranks = [r for _p, r in found]
                if ("→" in n or " then " in n) and len(set(ranks)) > 1 and ranks != sorted(ranks):
                    bad.append(f"claim (order): {n[:60]!r}")
                if re.search(
                    r"\b(?:permission|account scope|env\w*)\b[^.;|]*\b(?:before|ahead of)\b"
                    r"[^.;|]*\bview ?as\b|\bview ?as\b[^.;|]*\b(?:comes? |is )?(?:last|after "
                    r"(?:the )?(?:permission|account|env\w*))",
                    n,
                ):
                    bad.append(f"claim (order): {n[:60]!r}")
            for chain_m in re.finditer(r"`[a-z][a-z_.*{}]*`(?:\s*→\s*`[a-z][a-z_.*{}]*`)+", u):
                chain_legs = re.findall(r"`([^`]+)`", chain_m[0])
                if not any(x.startswith("rbac.") for x in chain_legs):
                    continue
                ranks = [leg_rank(x) for x in chain_legs]
                if chain_legs[0] != "rbac.view_as" or ranks != sorted(ranks):
                    shown = " → ".join(chain_legs)[:60]
                    bad.append(f"legs out of order or without view-as: {shown}")
    bad += [
        f"claim (hidden): {c!r}"
        for c in pair_claims(swept(t), HIDDEN_NEAR, HIDDEN_FOR, 4, unless=r"\bgroup by\b|\badmin\b")
    ]
    return one("G-VIEWAS", bad)


EXIT_WORDS = (
    r"\bcancel\w*|\bclos(?:e|es|ing)\b|\bflatten\w*|\bqty down\b|\breduc(?:e|es|ing)\b"
    r"|\btighten\w*|\btake profit\b|\bexits?\b"
)
NOT_EXIT = r"\b(?:closes|completes) #\d+|\bclosing keyword"
GATED = (
    r"\bt2\b|\bgated\b|\bgat(?:e|es|ing)\b|\block(?:s|ed|ing)?\b|\bdisabled\b|\bunavailable\b"
    r"|\bblocked\b|\baria disabled\b|\bnot_available\b"
)
STATE_GATE = (
    r"rbac\.env|\bfrozen\b|\blockout\b|\barm(?:ed|ing)?\b|\barm\.\w+|refusal\.\w+|recon\.\w+"
    r"|feed\.\w+|\bkill switch\b|\breconcil\w+|\bdesync\w*|\bstale\b|\bmaintenance\b"
    r"|\brate limit\w*|\b429\b"
)
EXCEPTION = (
    r"\boffline\b|\bunreachable\b|\bod 11\b|\bmanagers?\b[^.;|]*\bkill switch\b"
    r"|\bkill switch\b[^.;|]*\bmanagers?\b"
)
EXIT_FORBIDDEN = re.compile(
    r"^(?:rbac\.env|frozen|lockout|arm\..*|refusal\..*|recon\..*|feed\..*)$"
)


def g_exits(t: Texts) -> list[str]:
    """RULED BQ-13: exits are never gated by a state key or `rbac.env` (the two drawn
    exceptions aside); no sentence gates one."""
    bad: list[str] = []
    if not pending(t.spec, "4.1 The gated controls"):
        for r in gated_rows(t.spec):
            if "exit" not in norm_text(col(r, "Kind")):
                continue
            for k in legs_of(col(r, "Legs")):
                if EXIT_FORBIDDEN.match(k):
                    bad.append(f"{col(r, 'Control')[:24]} (an exit) takes `{k}`")
    for head, r in all_state_rows(t.spec):
        if pending(t.spec, head):
            continue
        who = norm_text(" ".join(col(r, c) for c in ("Frame", "State", "Word")))
        if not re.search(EXIT_WORDS, who) and not col(r, "Frame").startswith("`CMP-123/"):
            continue
        if re.search(EXCEPTION, norm_text(" | ".join(r.values()))):
            continue
        for k in legs_of(col(r, "T2")):
            if EXIT_FORBIDDEN.match(k):
                bad.append(f"{col(r, 'Frame')[:32]} (an exit frame) takes `{k}`")
    bad += [
        f"claim: {c!r}"
        for c in pair_claims(
            swept(t), EXIT_WORDS, GATED, 6, unless=EXCEPTION + "|" + NOT_EXIT, need=STATE_GATE
        )
    ]
    return one("G-EXITS", bad)


SUMMED = (
    r"\bsum(?:s|med|ming)?\b|\badd(?:s|ed)? up\b|\bcombin\w*|\bblend\w*|\baggregat\w*"
    r"|\bacross (?:both |the )?environments\b|\bmixed totals?\b|\bone total\b"
)
COLOUR_ONLY = (
    r"\b(?:colou?rs?|fills?|hues?|tints?|borders?) (?:alone|only)\b"
    r"|\bonly (?:by |through |via |with )?(?:its |the |a )?(?:\w+ )?(?:colou?r|fill|hue|tint)s?\b"
)
ENV_NEAR = r"\benv\w*\b|\bdemo\b|\blive\b(?! regions?)|\bpills?\b"


def g_env(t: Texts) -> list[str]:
    """C-2.11 / RULED BQ-13: totals per environment, never summed; the environment never by
    colour alone; a mixed view's row name leads with its environment."""
    totals = r"\btotals?\b|\bpnl\b|\bp&l\b"
    bad = [f"claim (summed): {c!r}" for c in pair_claims(swept(t), totals, SUMMED, 4)]
    bad += [f"claim (colour): {c!r}" for c in pair_claims(swept(t), ENV_NEAR, COLOUR_ONLY, 6)]
    if not pending(t.spec, "4.3 Environment"):
        s43 = norm_text(section(t.spec, "4.3 Environment"))
        if "leads with its environment" not in s43:
            bad.append("§4.3 does not say the row name leads with its environment")
        if "never summed" not in s43:
            bad.append("§4.3 does not say the totals are never summed")
    return one("G-ENV", bad)


# ---- a11y, tokens, copy (RULED BQ-12, BQ-13, BQ-14)

A11Y_LINES = ("Keyboard:", "Accessible name:", "Live region:")
A11Y_ENTRIES = STATE_HEADS
A11Y_HAND = ("C.1 A-1", "C.2 A-2", "C.3 A-3", "C.4 A-4")
A11Y_TABLE_A = ("CMP-123", "CMP-049")
ROW_UPDATE = (
    r"\brow updates?\b|\beach row\b|\bevery row\b|\bper row\b|\brow by row\b"
    r"|\bindividual rows?\b|\bevery (?:price |value )?update\b|\beach update\b"
)
ANNOUNCE = (
    r"\bannounc\w*|\baria live\b|\b(?:to|into|in|through) (?:the |a )?live regions?\b|\bspoken\b"
    r"|\bspeaks?\b|\bread (?:out|aloud)\b|\bpolite\w*|\bassertive\w*"
)


def g_a11y(t: Texts) -> list[str]:
    """RULED BQ-14: every entry carries the three a11y lines (keyboard model, accessible-name
    composition, live-region policy); row updates are never announced individually."""
    bad: list[str] = []
    for head in A11Y_ENTRIES:
        if pending(t.spec, head):
            continue
        block = section(t.spec, head)
        if not block:
            bad.append(f"§{head.split(' ')[0]} is missing")
            continue
        for label in A11Y_LINES:
            line = bullet(block, label)
            if not line or nullish(line.split(":**", 1)[-1]):
                bad.append(f"§{head.split(' ')[0]} has no {label[:-1]} line")
    for head in A11Y_HAND:
        if pending(t.hand, head):
            continue
        line = bullet(section(t.hand, head), "A11y")
        bad += [f"{head} A11y has no {lab[:-1]}" for lab in A11Y_LINES if lab not in line]
    if not pending(t.hand, "C.5 Table A"):
        rows = table_a(t.hand)
        for cmp in A11Y_TABLE_A:
            news = [col(r, "New") for r in rows
                    if cmp in col(r, "Component") and col(r, "Field").startswith("A11y")]  # fmt: skip
            if not news or not all(lab in news[0] for lab in A11Y_LINES):
                bad.append(f"Table A {cmp} has no A11y row with the three lines")
    bad += [f"claim: {c!r}" for c in pair_claims(swept(t), ROW_UPDATE, ANNOUNCE, 4)]
    return one("G-A11Y", bad)


DS_FAMILIES = (
    "color", "space", "size", "type", "radius", "elevation", "opacity", "motion", "border",
    "shadow", "z", "zindex", "font",
)  # fmt: skip
DS_SHAPED = re.compile(
    rf"(?<![\w./@#-])((?:{'|'.join(DS_FAMILIES)})\.[a-z0-9-]+(?:\.[a-z0-9{{}},*-]+)*)(?![\w(])",
    re.IGNORECASE,
)
DS_NAME = re.compile(
    r"`((?:color|space|size|type|radius|elevation|opacity|motion|border|font)\.[a-z0-9.{},*-]+)`"
)


def drop_column(text: str, head_word: str) -> str:
    """The text with every table column whose header starts with `head_word` blanked."""
    lines = text.split("\n")
    out: list[str] = []
    drop: set[int] = set()
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("|"):
            if i + 1 < len(lines) and is_rule(lines[i + 1]):
                drop = {
                    j for j, h in enumerate(split_row(ln)) if norm_text(h).startswith(head_word)
                }
            elif drop and not is_rule(ln):
                cells = split_row(ln)
                ln = join_row(["" if j in drop else c for j, c in enumerate(cells)])
        else:
            drop = set()
        out.append(ln)
    return "\n".join(out)


def recorded_names(t: Texts) -> set[str]:
    """Names recorded as missing or PROPOSED: §5's register, §7.4's Bound cells."""
    names = proposed_names(t.spec)
    for d in drift_rows(t.spec).values():
        names |= {n.lower() for n in DS_NAME.findall(col(d, "Bound"))}
    return names


def g_name(t: Texts) -> list[str]:
    """RULED BQ-12: no new design-system name — every name (backticked or bare, any case, or a
    CSS variable) is shipped, or recorded in §5's PROPOSED register or a §7.4 row."""
    known = ds_names()
    css_known = {n.replace(".", "-") for n in known}
    recorded = recorded_names(t)
    bad: list[str] = []
    for name, text in (("spec", t.spec), ("hand-off", t.hand)):
        body = drop_column(visible(text), "old")  # Table A's Old cells: `15` verbatim
        for n in sorted({m.lower() for m in DS_SHAPED.findall(body)}):
            if all(x in known for x in expand(n, known)) or n in recorded:
                continue
            bad.append(f"{name}: `{n}` is neither shipped nor recorded")
        for m in re.finditer(r"--(?:cv-)?([a-z][a-z0-9-]*)", body.lower()):
            if m[1].split("-")[0] in DS_FAMILIES and m[1] not in css_known:
                bad.append(f"{name}: `--{m[1]}` is not a shipped name's variable")
    return one("G-TOKEN", bad)


REASON_MAX = 60
REASON_FAMILIES = ("rbac", "recon", "blotter", "guard", "feed", "notice", "inflight", "panel")


def g_copy(t: Texts) -> list[str]:
    """RULED BQ-13: T2 only with registered keys; every other key PROPOSED with its owner;
    every new reason one sentence of at most sixty characters with a full stop."""
    bad: list[str] = []
    reg = registered_reasons()
    proposed: set[str] = set()
    if not pending(t.spec, "6. Copy keys"):
        rows = copy_rows(t.spec)
        if not rows:
            bad.append("§6 has no copy-key rows")
        for r in rows:
            idents = re.findall(r"`([^`]+)`", col(r, "Key"))
            if not idents:
                continue
            ident, status = idents[0], norm_text(col(r, "Status"))
            if status.startswith("registered") and ident not in reg:
                bad.append(f"`{ident}` is not registered at the base")
            elif status.startswith("proposed"):
                proposed.add(ident)
                if nullish(col(r, "Owner")):
                    bad.append(f"`{ident}` is PROPOSED with no owner")
            elif not status.startswith(("registered", "proposed")):
                bad.append(f"`{ident}`: status {col(r, 'Status')[:16]!r}")
            strings = QUOTED.findall(col(r, "String"))
            if ident.split(".")[0] in REASON_FAMILIES and status.startswith("proposed") and strings:
                s = strings[0].strip('"“”')
                if len(s) > REASON_MAX or not s.endswith("."):
                    bad.append(f"`{ident}`: the reason is not one sentence of ≤ {REASON_MAX}")
    if not pending(t.spec, "4.1 The gated controls"):
        for r in gated_rows(t.spec):
            for k in legs_of(col(r, "Legs")):
                if k not in reg and k not in proposed and not k.endswith("*"):
                    bad.append(f"`{k}` (§4.1) is neither registered nor PROPOSED in §6")
    return one("G-COPY", bad)


# ---- the security text, pinned default-deny (RULED BQ-16)
# A clause of the spec or the hand-off (a heading, a table cell, a prose sentence, a fenced line)
# is security-bearing when it names, case-insensitive at a word boundary: view-as; flatten or a
# bulk exit; the kill switch or a freeze; a native stop, NO SL or a stop-loss; liquidation;
# reduce-only; read-only; `aria-disabled`; audit; keys, signatures, withdrawals, transfers or
# `ret_msg`; and, case-sensitive, a fixture account (Main, Sub-n) or an environment word.
BEARING = re.compile(
    r"\bview(?:ing)?[- ]as\b|\brbac\.view_as\b"
    r"|\bflatten\w*|\bclose[- ]all\b|\bcancel[- ]all\b|\bcancelallorders\b|\bcloseallpositions\b"
    r"|\bflattenallbutton\b|\bCMP-(?:123|211)\b|\bpanic\b"
    r"|\bkill[- ]switch\b|\bfrozen\b|\bfreeze\b|\bhold[- ]to[- ]confirm\b|\btyped (?:confirm\w*|word)\b"
    r"|\bnative[- ](?:stop|sl)\b|\bno sl\b|\bstop[- ]loss\b|\bliquidat\w*|\breduce[- ]only\b"
    r"|\bread[- ]only\b|\baria-disabled\b|\baudit\w*|\bdestructive\b"
    r"|\bapi[- ]?keys?\b|\bkey (?:material|ids?|vault)\b|\bsignatures?\b|\bwithdraw\w*"
    r"|\btransfers?\b|\bret_msg\b|\bcredentials?\b",
    re.IGNORECASE,
)
BEARING_CASED = re.compile(
    r"\b(?:LIVE|DEMO|TESTNET|Demo|Testnet|Main)\b|\bLive\b(?! regions?)|\bSub-\d+\b"
)
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")
PIN_SPLIT = re.compile(r"(?<=[.!?])\s+")
PIN_SEP = " ‖ "
PIN_WIDTH = 96
Clause = tuple[str, str, str, int]


def one_space(text: str) -> str:
    return " ".join(text.split())


def text_clauses(name: str, text: str) -> list[Clause]:
    """Every clause of one document as (section, where, text, line): a heading; each cell of a
    table row (where: the header's ordinal, or the row's first cell and the cell's column); each
    sentence of a prose paragraph; each line of a fenced block. HTML comments and placeholder
    lines are dropped; whitespace is normalised; the section is its heading, cut at 48."""
    out: list[Clause] = []
    sec, seen = f"{name} preamble", {f"{name} preamble": 1}
    head: list[str] = []
    para: list[tuple[int, str]] = []
    fence = False

    def flush() -> None:
        joined = " ".join(one_space(x) for _n, x in para)
        starts, at = [], 0
        for num, x in para:
            starts.append((at, num))
            at += len(one_space(x)) + 1
        pos = 0
        for sentence in PIN_SPLIT.split(joined) if para else []:
            pos = joined.find(sentence, pos)
            line = max(n for a, n in starts if a <= pos)
            out.append((sec, "prose", sentence, line))
            pos += len(sentence)
        para.clear()

    lines = text.split("\n")
    for num, raw in enumerate(lines, 1):
        line = _HIDDEN.sub("", raw)
        stripped = line.strip()
        if PLACEHOLDER.match(raw):
            flush()
            continue
        if stripped.startswith("```"):
            flush()
            fence = not fence
        elif fence:
            if stripped:
                out.append((sec, "code", one_space(stripped), num))
        elif line.startswith("#"):
            flush()
            label = one_space(line.lstrip("#"))[:48].rstrip()
            seen[label] = seen.get(label, 0) + 1
            sec = label if seen[label] == 1 else f"{label} #{seen[label]}"
            out.append((sec, "heading", one_space(line), num))
        elif stripped.startswith("|"):
            flush()
            if is_rule(stripped):
                continue
            row = split_row(stripped)
            if not (num > 1 and lines[num - 2].strip().startswith("|")):
                head = row
                out += [(sec, f"head {i}", one_space(c), num) for i, c in enumerate(row, 1)]
                continue
            rid = one_space(row[0])[:40].rstrip() if row else ""
            for i, cell in enumerate(row):
                column = one_space(head[i])[:24].rstrip() if i < len(head) else str(i + 1)
                out.append((sec, f"row {rid}{PIN_SEP}{column}", one_space(cell), num))
        else:
            if not stripped or LIST_ITEM.match(line):
                flush()
            if stripped:
                para.append((num, stripped))
    flush()
    return out


def bearing(clause: str) -> bool:
    return BEARING.search(clause) is not None or BEARING_CASED.search(clause) is not None


def bearing_clauses(name: str, text: str) -> list[Clause]:
    return [c for c in text_clauses(name, text) if bearing(c[2])]


def render_pins(spec: str, hand: str) -> str:
    """The pinned table as `--repin-security` prints it and SEC_PIN_TXT holds it: a
    `§ doc ‖ section` line per section, an `@ where` line per clause, its text wrapped at spaces
    on lines indented two spaces (joined, they are the clause again)."""
    lines: list[str] = []
    for name, text in (("spec", spec), ("hand-off", hand)):
        last = ""
        for sec, where, clause, _num in bearing_clauses(name, text):
            if sec != last:
                lines.append(f"§ {name}{PIN_SEP}{sec}")
                last = sec
            lines.append(f"@ {where}")
            lines += [
                "  " + part
                for part in textwrap.wrap(
                    clause, PIN_WIDTH, break_long_words=False, break_on_hyphens=False
                )
            ]
    return "\n".join(lines)


def pin_rows(table: str) -> list[tuple[str, str, str, str]]:
    """A pinned table parsed: (doc, section, where, text) in document order."""
    rows: list[tuple[str, str, str, str]] = []
    doc, sec, where = "", "", ""
    parts: list[str] = []
    for line in [*table.strip("\n").split("\n"), "@ end"]:
        if line.startswith(("§ ", "@ ")) and parts:
            rows.append((doc, sec, where, " ".join(parts)))
            parts = []
        if line.startswith("§ "):
            doc, sec = line[2:].split(PIN_SEP, 1)
        elif line.startswith("@ "):
            where = line[2:]
        elif line.startswith("  "):
            parts.append(line[2:])
    return rows


def clip(text: str, width: int = 60) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def g_sec_pin(t: Texts) -> list[str]:
    """RULED BQ-16: every security-bearing clause equals its pinned entry, in order; a clause
    that is new, changed, moved or duplicated, and a pinned clause gone, FAIL."""
    pinned = pin_rows(t.pins)
    bad: list[str] = []
    for name, text in (("spec", t.spec), ("hand-off", t.hand)):
        want = [(s, w, x) for d, s, w, x in pinned if d == name]
        now = bearing_clauses(name, text)
        have = [(s, w, x) for s, w, x, _n in now]
        match = SequenceMatcher(None, want, have, autojunk=False)
        for tag, i1, i2, j1, j2 in match.get_opcodes():
            if tag == "equal":
                continue
            pairs = min(i2 - i1, j2 - j1) if tag == "replace" else 0
            for (s, w, x, num), (_s, _w, was) in zip(
                now[j1 : j1 + pairs], want[i1 : i1 + pairs], strict=True
            ):
                bad.append(f"{name}:{num} {s} · {w}: changed from {clip(was)!r} to {clip(x)!r}")
            for s, w, x, num in now[j1 + pairs : j2]:
                bad.append(
                    f"{name}:{num} {s} · {w}: not pinned (new, moved or duplicated) {clip(x)!r}"
                )
            for s, w, x in want[i1 + pairs : i2]:
                bad.append(f"{name} {s} · {w}: a pinned clause is gone {clip(x)!r}")
    return one("G-SEC-PIN", bad)


# ---- the inventory, contrast, CVD, drift (AC1, RULED BQ-3, BQ-12, BQ-14)


def g_states(t: Texts) -> list[str]:
    """AC1 / RULED BQ-5: §2.2 draws D01 D2's fifteen statuses; §2.1 the liq tiers and the B8
    protection-chip states (D02 §5.3, §5.4); every state frame shows its word."""
    bad: list[str] = []
    if not pending(t.spec, "2.2 CMP-115"):
        words = " ".join(col(r, "Word") for r in state_rows(t.spec, "2.2 CMP-115"))
        bad += [
            f"§2.2 does not draw {w!r}" for w in statuses() if not re.search(rf"\b{w}\b", words)
        ]
    if not pending(t.spec, "2.1 CMP-114"):
        rows = state_rows(t.spec, "2.1 CMP-114")
        words = " ".join(col(r, "Word") for r in rows)
        states = " ".join(col(r, "State") for r in rows)
        tiers, b8 = tiers_and_b8()
        bad += [
            f"§2.1 does not draw the {w} tier" for w in tiers if not re.search(rf"\b{w}\b", words)
        ]
        bad += [f"§2.1 has no `{s}` state" for s in b8 if f"`{s}`" not in states]
    if not pending(t.spec, "2.1 CMP-114") and not pending(t.spec, "2.2 CMP-115"):
        rows_text = section(t.spec, "2.1 CMP-114") + section(t.spec, "2.2 CMP-115")
        bad += [
            f"§2.1–§2.2 do not draw the marker {m!r}" for m in row_markers() if m not in rows_text
        ]
    for head, r in all_state_rows(t.spec):
        if not pending(t.spec, head) and nullish(col(r, "Word")):
            bad.append(f"{col(r, 'Frame')[:32]}: no word (never colour alone)")
    return one("G-STATES", bad)


def g_orphan(t: Texts) -> list[str]:
    """AC1 / RULED BQ-3: every CMP id SCR-063 and SCR-078 name maps in §2.10, and D02 gap 8's
    elements are named parts of a parent entry."""
    if pending(t.spec, "2.10 The AC1 map"):
        return []
    rows = table_with(section(t.spec, "2.10 The AC1 map"), "CMP", "Role")
    mapped = {m for r in rows for m in re.findall(r"CMP-\d{3}", col(r, "CMP"))}
    bad = [f"{c} is not mapped" for c in inventory() if c not in mapped]
    joined = [" | ".join(r.values()) for r in rows]
    for part in GAP8:
        hit = [x for x in joined if part.lower() in x.lower()]
        if not hit or not any(re.search(r"CMP-\d{3}", x) for x in hit):
            bad.append(f"{part!r} is not a named part of a parent entry")
    return one("G-ORPHAN", bad)


def g_contrast(t: Texts) -> list[str]:
    """RULED BQ-14: §5's rows are the tool's pairs, and each gated pair meets its bar in dark,
    light and high contrast."""
    if pending(t.spec, "5. Tokens and contrast"):
        return []
    bars = {
        "text": float(t.values["contrast.bar.text"]),
        "non-text": float(t.values["contrast.bar.non-text"]),
    }
    peak = float(t.values["cited.16.flash-peak-opacity"])
    every = {**PAIRS, **MEASURED_ONLY}
    rows = {re.sub(r"[`*]", "", col(r, "Pair")).strip(): r for r in contrast_rows(t.spec)}
    bad: list[str] = []
    if set(rows) != set(every):
        bad.append(f"§5 rows {sorted(set(rows) ^ set(every))[:4]} differ from the tool's pairs")
    for name, r in rows.items():
        want = every.get(name)
        cells = tuple(re.sub(r"`", "", col(r, c)).strip() for c in ("fg", "bg", "Role"))
        if want is not None and cells != want:
            bad.append(f"§5 {name}: fg / bg / role differ from the tool's")
    for name, (fg, bg, role) in PAIRS.items():
        for theme in THEMES:
            measured = ratio(theme, fg, bg, peak)
            if measured + 1e-9 < bars[role]:
                bad.append(f"{name} {THEME_SHORT[theme]} {measured:.2f} < {bars[role]:g}")
    return one("G-CONTRAST", bad)


def g_cvd_port(t: Texts) -> list[str]:
    """The ported Brettel constants equal `cvd_simulate.py` at the base."""
    src = at_base(CVD_REL)
    block = src[src.index("RGB_TO_LMS = (") : src.index("def matvec")]
    nums = [float(x) for x in re.findall(r"-?\d+\.\d+(?:e-?\d+)?", block)]
    mine = [*flat3(RGB_TO_LMS), *flat3(LMS_TO_RGB)]
    for sim in SIMS:
        mine += list(PROJECTIONS[sim])
    port = [x for x in mine if x not in (0.0, 1.0)]
    theirs = [x for x in nums if x not in (0.0, 1.0)]
    return one("G-CVD-PORT", [] if port == theirs else ["the port differs from cvd_simulate.py"])


UNRESOLVED = (
    r"\bunresolved\b|\bstill open\b|\bnot (?:yet )?(?:resolved|answered|corrected)\b|\btb[dc]\b"
    r"|\bno owner\b|\bno replacement\b"
)


def drift_problems(k: str, d: dict[str, str]) -> list[str]:
    """Why ledger row `k` is not resolved (empty when it is)."""
    bad: list[str] = []
    if norm_text(col(d, "Class")) not in ("a", "b", "c", "d"):
        bad.append(f"{k}: class {col(d, 'Class')!r}")
    for c in ("Source", "Bound", "Replacement", "Owner"):
        if nullish(col(d, c)):
            bad.append(f"{k}: no {c}")
    rep = col(d, "Replacement")
    if not (DS_NAME.search(rep) or "Deliberate exception" in rep) or live(rep, UNRESOLVED):
        bad.append(f"{k}: the Replacement names no exact name")
    if norm_text(col(d, "Verdict")) not in ("corrected", "justified"):
        bad.append(f"{k}: verdict {col(d, 'Verdict')!r} (unresolved)")
    return bad


def g_drift(t: Texts) -> list[str]:
    """RULED BQ-12: every drift row has its class, an exact replacement, an owner and a verdict;
    no sentence leaves a row open."""
    if pending(t.spec, "7.4 Drift ledger"):
        return []
    rows = drift_rows(t.spec)
    bad: list[str] = []
    for k, d in rows.items():
        if not re.fullmatch(DR_ID, k):
            bad.append(f"{k[:12]!r} is not a ledger id")
        bad += drift_problems(k, d)
    if not rows:
        bad.append("§7.4 has no rows")
    near = r"\bdr \d+\b|\bdrift (?:rows?|ledger)\b"
    bad += [f"claim: {c!r}" for c in pair_claims(swept(t), near, UNRESOLVED, 6)]
    return one("G-DRIFT", bad)


# ---------------------------------------------------------------------------- the audit

GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-VALUE": g_value,
    "G-CITE": g_cite,
    "G-PIN": g_pin,
    "G-RULED": g_ruled,
    "G-OWNER": g_owner,
    "G-AC": g_ac,
    "G-CROW": g_crow,
    "G-BOARDS": g_boards,
    "G-BUDGET": g_budget,
    "G-HANDOFF": g_handoff,
    "G-UNTOUCHED": g_untouched,
    "G-PLACEHOLDER": g_placeholder,
    "G-MUTLIST": g_mutlist,
    "G-ROW-200": g_row200,
    "G-COMPOSITOR": g_compositor,
    "G-TWIN": g_twin,
    "G-REDUCE-INSTANT": g_reduce_instant,
    "G-INSTANT": g_instant,
    "G-LOOP": g_loop,
    "G-TICK": g_tick,
    "G-PENDING": g_pending,
    "G-FLATTEN": g_flatten,
    "G-DISPLAY": g_display,
    "G-VIEWAS": g_viewas,
    "G-EXITS": g_exits,
    "G-ENV": g_env,
    "G-A11Y": g_a11y,
    "G-TOKEN": g_name,
    "G-COPY": g_copy,
    "G-SEC-PIN": g_sec_pin,
    "G-STATES": g_states,
    "G-ORPHAN": g_orphan,
    "G-CONTRAST": g_contrast,
    "G-CVD-PORT": g_cvd_port,
    "G-DRIFT": g_drift,
}
GATE_TAGS = tuple(GATES)
# §8.2's Rule column: what each gate holds, and the ruling it holds it for
GATE_RULES: dict[str, str] = {
    "G-VALUE": "every figure is a marker the tool re-derives (condition)",
    "G-CITE": "cites, quoted fragments and Table A's Old cells hold at the base (condition)",
    "G-PIN": "merged texts at their merge shas (condition)",
    "G-RULED": "RULED cites the #823 ruling; BQ-1 to BQ-16 (BQ-1)",
    "G-OWNER": "the owner-level rows are marked (BQ-2, BQ-10, BQ-11, BQ-12)",
    "G-AC": "AC1, AC3 and DoD 1-2 met as copy-ready A-rows (BQ-2)",
    "G-CROW": "every departure has its C-row (BQ-2, BQ-5, BQ-9 to BQ-12)",
    "G-BOARDS": "at most ten boards, at most three light twins (BQ-15)",
    "G-BUDGET": "the spec at most 600 lines, §9 at most ten (BQ-1)",
    "G-HANDOFF": "one hand-off, §A to §F (BQ-1)",
    "G-UNTOUCHED": "`15` and `16` byte-identical to the base (BQ-2)",
    "G-PLACEHOLDER": "no section left to write",
    "G-MUTLIST": "this table lists the tool's mutations (BQ-16)",
    "G-ROW-200": "no motion row past `motion.duration.normal`; never `slow` (BQ-9, BQ-12)",
    "G-COMPOSITOR": "Property is opacity, a transform or none (BQ-9)",
    "G-TWIN": "a `prefers-reduced-motion` twin on every row (BQ-9; AC2)",
    "G-REDUCE-INSTANT": "every twin instant (BQ-9; AC2)",
    "G-INSTANT": "the eight kinds of state swap at frame 0 in both modes (BQ-11)",
    "G-LOOP": "no shimmer, pulse or loop word, any case (BQ-10)",
    "G-TICK": "nothing per tick or update; the flash rate (BQ-9)",
    "G-PENDING": "pending is a state, never drawn as confirmed (BQ-5)",
    "G-FLATTEN": "hold and typed on LIVE, defined once (BQ-7; AC3)",
    "G-DISPLAY": "CMP-129's display variant: no control role, no T2 (BQ-8)",
    "G-VIEWAS": "the legs in order, view-as first; nothing hidden (BQ-13)",
    "G-EXITS": "exits never gated by a state key or `rbac.env` (BQ-13)",
    "G-ENV": "totals per environment; never colour alone (BQ-13)",
    "G-A11Y": "the three a11y lines on every entry (BQ-14)",
    "G-TOKEN": "no new token name (BQ-12)",
    "G-COPY": "registered keys, or PROPOSED with an owner (BQ-13)",
    "G-SEC-PIN": "the security text pinned, default-deny (BQ-16)",
    "G-STATES": "D01 D2's statuses, D02's tiers and chip states, the markers (AC1; BQ-5)",
    "G-ORPHAN": "every SCR-063 and SCR-078 component mapped (AC1; BQ-3)",
    "G-CONTRAST": "the tool's pairs, each at its bar in three themes (BQ-14)",
    "G-CVD-PORT": "the CVD port equals `cvd_simulate.py` (BQ-16)",
    "G-DRIFT": "every drift row resolved (BQ-12)",
}


def audit(t: Texts) -> tuple[list[str], list[str]]:
    """Every gate over one pair of texts: (FAIL lines, WARN lines)."""
    fails: list[str] = []
    for tag, gate in GATES.items():
        try:
            got = gate(t)
        except SystemExit as exc:
            got = [f"[{tag}] {exc}"]
        bad = [x for x in got if not x.startswith(f"[{tag}]")]
        fails += got if not bad else [f"[{tag}] reported under another tag: {bad[0][:60]}"]
    _f, warns, _n = cite_problems({"spec": t.spec, "hand-off": t.hand}, git_show)
    return fails, warns


def read_inputs() -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for rel in MEASURED:
        if rel in (P15_REL, P16_REL):
            continue
        path = ROOT / rel
        out.append((rel, path.read_bytes().decode("utf-8") if path.exists() else ""))
    return tuple(out)


def diff_names() -> tuple[str, ...]:
    return tuple(n for n in git_out("diff", "--name-only", BASE).split("\n") if n)


# ---------------------------------------------------------------------------- the fixture fill

Block = str | Callable[[], str]


def fill_placeholders(text: str, fixture: dict[str, Block]) -> str:
    """Each heading whose own body (to the next heading of any level) still holds a placeholder
    gets the fixture block of its heading prefix instead; the rest is kept byte for byte."""
    lines = text.split("\n")
    fence = fenced(lines)
    out: list[str] = []
    i = 0
    while i < len(lines):
        out.append(lines[i])
        m = HEADING.match(lines[i])
        if m and not fence[i]:
            j = i + 1
            while j < len(lines) and not (HEADING.match(lines[j]) and not fence[j]):
                j += 1
            body = lines[i + 1 : j]
            prefix = next((k for k in fixture if m[2].startswith(k)), None)
            if prefix is not None and any(PLACEHOLDER.match(b) for b in body):
                block = fixture[prefix]
                content = block() if callable(block) else block
                out += ["", *content.strip("\n").split("\n"), ""]
                i = j
                continue
        i += 1
    return "\n".join(out)


# ---------------------------------------------------------------------------- mutation helpers

Edit = Callable[[str, Values], str]


def join_row(cells: list[str]) -> str:
    return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"


def edit_row(
    head: str,
    words: tuple[str, ...],
    pick: Callable[[dict[str, str]], bool],
    column: str,
    fn: Callable[[str], str],
) -> Edit:
    """The `column` cell of the first row `pick` chooses, in the first table of section `head`
    whose header holds `words`."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i in range(len(lines) - 1):
            if not (lines[i].lstrip().startswith("|") and is_rule(lines[i + 1])):
                continue
            header = split_row(lines[i])
            if not all(w.lower() in " | ".join(header).lower() for w in words):
                continue
            ci = next((k for k, h in enumerate(header) if h.lower().startswith(column.lower())), -1)
            j = i + 2
            while ci >= 0 and j < len(lines) and lines[j].lstrip().startswith("|"):
                cells = split_row(lines[j])
                if pick(dict(zip(header, cells, strict=False))) and ci < len(cells):
                    cells[ci] = fn(cells[ci])
                    lines[j] = join_row(cells)
                    return text.replace(block, "\n".join(lines), 1)
                j += 1
            return text
        return text

    return run


def drop_row(head: str, words: tuple[str, ...], pick: Callable[[dict[str, str]], bool]) -> Edit:
    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i in range(len(lines) - 1):
            if not (lines[i].lstrip().startswith("|") and is_rule(lines[i + 1])):
                continue
            header = split_row(lines[i])
            if not all(w.lower() in " | ".join(header).lower() for w in words):
                continue
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                if pick(dict(zip(header, split_row(lines[j]), strict=False))):
                    del lines[j]
                    return text.replace(block, "\n".join(lines), 1)
                j += 1
            return text
        return text

    return run


def add_row(head: str, words: tuple[str, ...], row: str) -> Edit:
    """Append `row` at the end of the first table of `head` whose header holds `words`."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i in range(len(lines) - 1):
            if not (lines[i].lstrip().startswith("|") and is_rule(lines[i + 1])):
                continue
            if not all(w.lower() in lines[i].lower() for w in words):
                continue
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            lines.insert(j, row)
            return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def prose_at(head: str, sentence: str | Callable[[Values], str]) -> Edit:
    """Append a paragraph at the end of the section `head`."""

    def run(text: str, v: Values) -> str:
        block = section(text, head)
        if not block:
            return text
        body = sentence(v) if callable(sentence) else sentence
        return text.replace(block, block.rstrip("\n") + "\n\n" + body + "\n", 1)

    return run


def sub_in(head: str, old: str, new: str) -> Edit:
    """Replace the first `old` inside the section `head` (or the whole text when head is "")."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head) if head else text
        return text.replace(block, block.replace(old, new, 1), 1) if old in block else text

    return run


def line_edit(prefix: str, old: str, new: str) -> Edit:
    """Replace `old` with `new` in the first line starting with `prefix` that holds it."""

    def run(text: str, _v: Values) -> str:
        out = text.split("\n")
        for i, ln in enumerate(out):
            if ln.startswith(prefix) and old in ln:
                out[i] = ln.replace(old, new, 1)
                break
        return "\n".join(out)

    return run


def chain(*edits: Edit) -> Edit:
    def run(text: str, v: Values) -> str:
        for e in edits:
            text = e(text, v)
        return text

    return run


def to(value: str) -> Callable[[str], str]:
    return lambda _c: value


def appended(extra: str) -> Callable[[str], str]:
    return lambda c: c + extra


def marker(v: Values, name: str) -> str:
    return f"{v[name]} <!-- audit:{name}={v[name]} -->"


def is_mo(pred: Callable[[dict[str, str]], bool]) -> Callable[[dict[str, str]], bool]:
    return lambda r: re.fullmatch(MO_ID, row_key(col(r, "Mo"))) is not None and pred(r)


def swap_legs(cell: str) -> str:
    legs = re.findall(r"`[^`]+`", cell)
    if len(legs) < 2:
        return cell
    return cell.replace(legs[0], "\0", 1).replace(legs[1], legs[0], 1).replace("\0", legs[1], 1)


def overrun(text: str, _v: Values) -> str:
    return text + "filler\n" * (SPEC_LINE_BUDGET - text.count("\n") + 5)


def crlf(text: str) -> str:
    return text.replace("\n", "\r\n")


def nudge_projection() -> Callable[[], None]:
    """Move one ported Brettel constant by a ten-thousandth (G-CVD-PORT); returns the undo."""
    sim = SIMS[0]
    old = PROJECTIONS[sim]
    PROJECTIONS[sim] = (old[0], old[1] * 1.0001, *old[2:])
    return lambda: PROJECTIONS.__setitem__(sim, old)


FIXTURES_SENTENCE = "No key material, signature, full order id or real balance appears"


def move_fixture_sentence(text: str, _v: Values) -> str:
    """M18.2: the pinned Fixtures sentence moved from the header to §8.1."""
    line = next((ln for ln in text.split("\n") if ln.startswith("**Fixtures.**")), "")
    m = re.search(rf"{re.escape(FIXTURES_SENTENCE)}[^.]*\.", line)
    if not m:
        return text
    text = text.replace(line, line.replace(" " + m[0], ""), 1)
    return prose_at("8.1 ", m[0])(text, _v)


def duplicate_fixture_sentence(text: str, _v: Values) -> str:
    """M18.3: the pinned Fixtures sentence copied into the Deviations."""
    line = next((ln for ln in text.split("\n") if ln.startswith("**Fixtures.**")), "")
    m = re.search(rf"{re.escape(FIXTURES_SENTENCE)}[^.]*\.", line)
    return prose_at("Deviations", m[0])(text, _v) if m else text


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str  # the gate tag that must trip
    ruled: str  # the ruled sentence it trips
    spec: Edit | None = None
    hand: Edit | None = None
    p15: Callable[[str], str] | None = None
    p16: Callable[[str], str] | None = None
    patch: Callable[[], Callable[[], None]] | None = None  # moves tool state; returns the undo
    pinned: bool = False  # True: held to the baseline's pins (a G-SEC-PIN mutation)


# ---------------------------------------------------------------------------- the fixture
# A minimal passing body for every section the skeleton leaves to its writers: `--self-test`
# fills each section that still holds a placeholder with its block, so every gate runs on a whole
# document from the first commit; once a section is written, the written text is used instead.
# Every row shape here is the shape the gates read (skeleton.md names them).

FIX_STATES_114 = """
| Frame | State | Word | Glyph | Fill | Motion | T2 | Board |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CMP-114/row-new` | a new row | "New" | — | `color.surface.raised` | Mo-1 | — | 01 |
| `CMP-114/liq-watch` | the Watch tier | "△ Watch 2.1" | △ | `color.surface.raised` | Mo-8 | — | 01 |
| `CMP-114/liq-near` | the Near tier | "! Near 1.2" | ! | `color.surface.raised` | Mo-8 | — | 01 |
| `CMP-114/liq-critical` | the Critical tier | "!! Critical 0.5" | !! | `color.status.danger.strong` (the leading accent) | Mo-8 | — | 01 |
| `CMP-114/sl-protected` | `protected` | "SL ✓ 63,880.0" | ✓ `check` | `color.surface.raised` | Mo-8 | — | 01 |
| `CMP-114/sl-attaching` | `attaching` | "SL attaching…" | — | `color.surface.raised` | Mo-8 | — | 01 |
| `CMP-114/sl-verifying` | `verifying` | "SL sent — verifying" | — | `color.surface.raised` | Mo-8 | — | 01 |
| `CMP-114/sl-amending` | `amending` | "SL 63,880.0 → 63,950.0" | ⟳ `refresh` | `color.status.info.subtle` | Mo-8 | — | 01 |
| `CMP-114/sl-naked` | `naked` | "NO SL ! 12 s" | ! | `color.status.danger.subtle` | Mo-8 | — | 01 |
| `CMP-114/sl-naked-unrecoverable` | `naked_unrecoverable` | "NO SL — owner paged" | ! | `color.status.danger.subtle` | Mo-8 | — | 01 |
| `CMP-114/sl-frozen` | `amend_lock.frozen` | "· frozen" | — | `color.surface.raised` | Mo-8 | — | 01 |

Row markers, each a tag in the status cell (D02:414; D03:327–344): "Verifying", "Stop put back", "SL auto-attached", "Corrected", "Updated from Bybit", "Rejected — not found on Bybit", "Gone from Bybit", "Rejected — history expired", "Unknown — checking", "Untracked — not placed by CandleViewer", "Anomaly", "Held — owner review", "Unpaired fill", "Stop restored", "Stop not restored", "Tighter stop kept", "Untracked stop — not placed by CandleViewer".

- **Keyboard:** A treegrid with one roving stop: arrows move between cells, `Enter` or `F2` edits, `Space` selects and `Escape` cancels an edit (D02:447).
- **Accessible name:** In a mixed view the environment leads, then symbol, side, size, account and the status word (D02:222).
- **Live region:** Row updates are never announced individually. The focused row's changed values speak politely, at most once per {{audit:cited.05.polite-gap-s}} s per field (D02:465).
"""

FIX_STATES_115 = """
| Frame | State | Word | Glyph | Fill | Motion | T2 | Board |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CMP-115/status-sending` | sending | "Sending" | `loader` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/status-working` | working | "Working" | `clock` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/status-triggered` | triggered | "Triggered" | `zap` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/status-partial` | partially filled | "Partial 0.200/0.500" | `circle-half` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/status-cancelling` | cancelling | "Cancelling" | `refresh` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/status-amending` | amending | "Amending" | `refresh` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/status-unknown` | unknown | "Unknown — checking" | `help-circle` | `color.status.warning.subtle` | Mo-8 | — | 02 |
| `CMP-115/status-quarantined` | quarantined | "Quarantined" | `octagon-alert` | `color.status.danger.subtle` | Mo-8 | — | 02 |
| `CMP-115/status-held` | held | "Held — owner review" | `lock` | `color.status.danger.subtle` | Mo-8 | — | 02 |
| `CMP-115/status-untracked` | untracked | "Untracked — not placed by CandleViewer" | `link-off` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/status-filled` | filled | "Filled" | `check` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/status-cancelled` | cancelled | "Cancelled" | `slash` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/status-rejected` | rejected | "Rejected" | `x` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/status-expired` | expired | "Expired" | `clock-strike` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/status-killed` | killed | "Killed (kill switch)" | `stop-square` | `color.surface.raised` | Mo-8 | — | 02 |
| `CMP-115/amend-pending` | pending (not applied) | "Amending → 2,495.00 · 2,500.00 still live" | ⟳ `refresh` | `color.status.info.subtle` (the tag) | Mo-8 | — | 02 |
| `CMP-115/amend-unconfirmed` | unconfirmed | "Unknown — checking · 2,500.00 may still be live" | `help-circle` | `color.status.warning.subtle` | Mo-8 | — | 02 |
| `CMP-115/amend-rejected` | a rejected amend | "⚠ Amend rejected — your order is unchanged" | ⚠ `alert-triangle` | `color.status.warning.subtle` | Mo-8 | — | 02 |

- **Keyboard:** The order rows share CMP-114's treegrid model; `Enter` or `F2` opens the cell editor and commits on `Enter` only (D02:303).
- **Accessible name:** The status word leads, then type with purpose, price, quantity and account (D01:170).
- **Live region:** Filled and rejected are assertive, once. Every other status change is silent (D02:465).
"""

FIX_STATES_116 = """
| Frame | State | Word | Glyph | Fill | Motion | T2 | Board |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CMP-116/bar-profit` | profit | "+8.00 USDT" | — | `color.buy.default` (the accent bar) | Mo-3 | — | 03 |
| `CMP-116/bar-loss` | loss | "−3.49 USDT" | — | `color.sell.default` (the accent bar) | Mo-3 | — | 03 |
| `CMP-116/r-null` | R unavailable | "—", read as "R unavailable: no stop price" | — | `color.surface.raised` | — | — | 03 |

- **Keyboard:** None: the badge is not interactive.
- **Accessible name:** The sign and the value in words as visually hidden text ("profit 8.00 USDT"), never an `aria-label` (D02:184).
- **Live region:** None of its own. The host's policy applies (§2.1).
"""

FIX_STATES_123 = """
| Environment | Confirm | Discrete keyboard path | prefers-reduced-motion | Source |
| --- | --- | --- | --- | --- |
| DEMO | CMP-044 `hold` for {{audit:cited.cmp044.hold-ms}} ms | a second `Enter` | the percentage text, static | D02:353 |
| LIVE | CMP-044 `hold` and the typed word | a second `Enter`, then the typed word | the percentage text, static | D02:353 "Live adds the typed confirm" |

| Frame | State | Word | Glyph | Fill | Motion | T2 | Board |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CMP-123/default` | default | "Flatten account…" | — | `color.surface.raised` | Mo-8 | — | 04 |
| `CMP-123/holding` | holding | "Hold to flatten Sub-1 · LIVE" | — | `color.status.danger.default` | Mo-7 | — | 04 |
| `CMP-123/t2-view-as` | T2 under view-as | "Flatten account…" | `lock` | `color.surface.raised` | Mo-8 | `rbac.view_as` | 04 |

- **Keyboard:** A hold with a second `Enter` as the discrete path; `Escape` disarms.
- **Accessible name:** Scope and effect: "Flatten account — Sub-1 · LIVE".
- **Live region:** The result line is polite, once.
"""

FIX_STATES_129 = """
| Frame | State | Word | Glyph | Fill | Motion | T2 | Board |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `CMP-129/display-one-way` | display, one-way | "One-way" | — | `color.surface.raised` | — | — | 05 |
| `CMP-129/display-hedge` | display, hedge | "Hedge" | — | `color.surface.raised` | — | — | 05 |
| `CMP-129/toggle-confirm` | toggle, the confirm open | "Switch to Hedge?" | — | `color.surface.overlay` | Mo-8 | — | 05 |
| `CMP-129/toggle-t2-owner-only` | toggle, T2 | "Position mode" | `lock` | `color.surface.raised` | Mo-8 | `rbac.owner_only` | 05 |

- **Keyboard:** The display variant is not a Tab stop. The toggle is CMP-003's radio group: arrows browse and the confirm commits (E05-D02 D5).
- **Accessible name:** The mode as text, "One-way" or "Hedge".
- **Live region:** None of its own: the mode never speaks.
"""

FIX_MOTION = """
| Mo | Component | Trigger | Property | Duration | Easing | prefers-reduced-motion twin | Limit | Board |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mo-1 | CMP-114 / CMP-115 row insert | a row joins its group | opacity | `motion.duration.fast` ({{audit:motion.duration.fast}} ms) | `motion.easing.standard` | prefers-reduced-motion: the row is there at frame 0 with its "New" marker | once per row | 06, 07 |
| Mo-2 | CMP-114 / CMP-115 row exit after the linger | the linger ends | opacity | `motion.duration.fast` ({{audit:motion.duration.fast}} ms) | `motion.easing.accelerate` | prefers-reduced-motion: the row leaves at frame 0; its marker word was the change | once per row | 06, 07 |
| Mo-3 | the value-change flash on a numeric cell (CMP-114, CMP-115, CMP-116) | a settled value differs from the last one | opacity (an overlay above the cell) | `motion.duration.fast` ({{audit:motion.duration.fast}} ms) | `motion.easing.standard` | prefers-reduced-motion: no flash; the signed text and the ▲ / ▼ glyph are the change | ≥ {{audit:cited.16.flash-gap-ms}} ms between starts per cell | 06, 07 |
| Mo-4 | the correction highlight on a reconciled row | a "Corrected" marker arrives | opacity (an overlay above the row) | `motion.duration.fast` ({{audit:motion.duration.fast}} ms) | `motion.easing.standard` | prefers-reduced-motion: no highlight; the marker word is the change | once per marker | 06, 07 |
| Mo-5 | skeleton rows (a panel state, not a data row) | the first load | by reference (CMP-015) | by reference | by reference | prefers-reduced-motion: static two-tone, per CMP-015 | per CMP-015 | — |
| Mo-6 | the SCR-078 drawer (CMP-046 in CMP-209) | open and close | transform: translateX | `motion.duration.normal` ({{audit:motion.duration.normal}} ms) | `motion.easing.decelerate` | prefers-reduced-motion: open at frame 0; its title text is the change | once per open | 06, 07 |
| Mo-7 | CMP-123's hold ring | a hold | by reference (§2.4) | by reference | by reference | prefers-reduced-motion: static percentage text at frame 0, per CMP-123 | per CMP-123 | 04 |
| Mo-8 | a state swap (status word, glyph, fill, pill, liq tier, protection chip, T2 ↔ enabled, DEMO / LIVE) | the state changes | none (a cut) | `motion.duration.instant` ({{audit:motion.duration.instant}} ms) | none | prefers-reduced-motion: the same cut at frame 0 | — | 06, 07 |
"""

ROLE_HERE = {
    "CMP-114": "contributed",
    "CMP-115": "contributed",
    "CMP-116": "contributed",
    "CMP-129": "contributed",
    "CMP-123": "amended",
    "CMP-049": "amended",
    "CMP-105": "reused by contract",
}
GAP8_PARENT = {
    "pending tag": "CMP-115",
    "protection chip": "CMP-114",
    "liquidation tier cell": "CMP-114",
    "correction markers": "CMP-114",
    "Updates paused": "CMP-114",
    "Fills Type toggle chips": "CMP-011",
    "group header row": "CMP-114",
    "totals row": "CMP-114",
}


def fix_map() -> str:
    rows = ["| CMP | Name | Role here | Section |", "| --- | --- | --- | --- |"]
    for c in inventory():
        rows.append(f"| {c} | (catalogued) | {ROLE_HERE.get(c, 'consumed')} | §2 |")
    for part, parent in GAP8_PARENT.items():
        rows.append(
            f"| {parent} | the {part} (a named part) | {ROLE_HERE.get(parent, 'consumed')} | §2 |"
        )
    return "\n".join(rows)


def fix_contrast() -> str:
    rows = [
        "| Pair | fg | bg | Role | Dark | Light | HC |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, (fg, bg, role) in {**PAIRS, **MEASURED_ONLY}.items():
        bgs = " over ".join(f"`{x}`" for x in bg.split(" over "))
        vals = " | ".join(f"{{{{audit:contrast.{name}.{t}}}}}" for t in ("dark", "light", "hc"))
        rows.append(f"| `{name}` | `{fg}` | {bgs} | {role} | {vals} |")
    rows += [
        "",
        (
            "The buy and sell accent bars are ΔE76 {{audit:cvd.bar-buy-sell.deutan.dark}} apart"
            " under deuteranopia in dark, against the floor ΔE76 {{audit:cvd.jnd}}."
        ),
        "",
        "| Name | Owner (cited) | Used for |",
        "| --- | --- | --- |",
        (
            "| `motion.duration.hold-confirm` | E39-D03 G12, PENDING its owner's approval"
            " | the hold of §2.4 |"
        ),
    ]
    return "\n".join(rows)


def fix_gates() -> str:
    rows = ["| Gate | Rule (RULED) | Mutations |", "| --- | --- | --- |"]
    groups = mutation_groups()
    for tag in GATES:
        rows.append(f"| {tag} | {GATE_RULES[tag]} | {' · '.join(groups.get(tag, []))} |")
    return "\n".join(rows)


FIXTURE_SPEC: dict[str, Block] = {
    "1. ": """
| Input | Where | Used for |
| --- | --- | --- |
| D01 D2's fifteen lifecycle labels | D01:174 | §2.2 |
| D02's tiers and protection-chip states | D02:211, :224 | §2.1 |
| The flash constants of `16` §7.1 | `16`:199 | §3.5 |

Pending is a state, never drawn as confirmed (D02:325 "never optimistically as confirmed").
""",
    "2. ": """
Contributed whole: CMP-114, CMP-115, CMP-116 and CMP-129; amended: CMP-123 and CMP-049; reused by contract: CMP-105; routed deltas in §2.8; the rest consumed (§2.9; RULED BQ-3).
""",
    "2.1 ": FIX_STATES_114,
    "2.2 ": FIX_STATES_115,
    "2.3 ": FIX_STATES_116,
    "2.4 ": FIX_STATES_123,
    "2.5 ": FIX_STATES_129,
    "2.6 ": """
Delta only (E30-D04:351): the filter use passes the server-scoped list and omits `onEditProfile`; a Manager sees assigned accounts only and no T2 sits on a filter.

- **Keyboard:** As E30-D04 §8 (E30-D04:351).
- **Accessible name:** The chip reads its account, "Account: Sub-1".
- **Live region:** The result count is polite, once.
""",
    "2.7 ": """
The base contract E05-D02 G12 waits for: treegrid rows, a sticky first column and the expandable detail lines.

- **Keyboard:** One roving stop; arrows move between cells; `Enter` expands a detail line.
- **Accessible name:** Each row's first cell names it.
- **Live region:** Sort, filter and selection results are polite, once each.
""",
    "2.8 ": """
The components D02 §15 and D03 §11.2 route to E29-D04 beyond the five, each answered by a delta or a change request to its owner, cited.
""",
    "2.8.": """
A delta or a change request routed here (D02:608), cited to its owner; nothing is redefined.
""",
    "2.9 ": """
CMP-079 RbacGate (every T2), CMP-019 Icon (the `lock`), CMP-044 ConfirmDialog (the hold) and CMP-020 NumericText (the numerals): reused, never redefined.
""",
    "2.10 ": fix_map,
    "3. ": """
The blotter rows' motion is defined once here; tokens by name only, none added; reduced motion has one source (§3.6).
""",
    "3.1 ": """
Every motion row binds at most `motion.duration.normal` ({{audit:motion.duration.normal}} ms) on opacity or a transform; nothing moves under the pointer (D01:406).
""",
    "3.2 ": FIX_MOTION,
    "3.3 ": """
Status words, glyphs, fills, pills, the liq tier, the protection chip, T2 ↔ enabled and DEMO / LIVE swap at frame 0 in both modes: `motion.duration.instant` ({{audit:motion.duration.instant}} ms), no easing (Mo-8).
""",
    "3.4 ": """
Nothing animates per tick or per price update: ages, counters and the NO SL timer repaint without motion (D02:465).
""",
    "3.5 ": """
The flash starts at most once per cell every {{audit:cited.16.flash-gap-ms}} ms, on at most {{audit:cited.16.flash-cells-per-frame}} cells per frame, and stops for a cell changing at {{audit:cited.16.flash-stop-hz}} Hz or more for {{audit:cited.16.flash-stop-after-s}} s (`16`:199). The signed text and the ▲ / ▼ glyph pair with every flash (T Tech).
""",
    "3.6 ": """
`data-motion` on the root is the one source, written before first paint (`16`:183); `theme.css` cuts every transition under it (`packages/ui/src/theme/theme.css`:56). Every twin is instant; no component reads the media query.
""",
    "4. ": """
Every gated control takes CMP-079's `allowed` + `reason` and keeps its native role; the UI is never the control: "Every treatment in this document is presentation." (E09-D09:410; C-2.12, C-12.4).
""",
    "4.1 ": """
| Control | Component | Kind | Legs (in order) | Drawn exceptions | Renders | Source |
| --- | --- | --- | --- | --- | --- | --- |
| Close ▾ | CMP-114 | exit | `rbac.view_as` → `rbac.permission` → `rbac.account_read_only` | offline with REST unreachable; a Manager under the kill switch (OD-11 pending) | 2a | D02:427 |
| Reverse… | CMP-114 | new exposure | `rbac.view_as` → `rbac.permission` → `rbac.account_read_only` → `rbac.env` → `frozen` | — | 2a | D02:427 |
| Cancel ▾ | CMP-115 | exit | `rbac.view_as` → `rbac.permission` → `rbac.account_read_only` | offline with REST unreachable | 2a | D02:427 |
| Flatten account… | CMP-123 | exit | `rbac.view_as` → `rbac.permission` → `rbac.account_read_only` | offline with REST unreachable; a Manager under the kill switch (OD-11 pending) | 2a | D02:353 |
""",
    "4.2 ": """
Exits (cancel, close, flatten account, qty down, a stop's tighten) are never gated by a state key or `rbac.env`. Filters, sort, group, select, Columns, density and Export carry no T2 (D02:433).
""",
    "4.3 ": """
The environment is the text pill "LIVE" or "DEMO" with a `color.env.live` or `color.env.demo` border, never colour alone. In a mixed view a row's name leads with its environment. Totals are per environment and never summed (D02:156).
""",
    "5. ": fix_contrast,
    "6. ": """
| Key | String | Status | Owner | Used on |
| --- | --- | --- | --- | --- |
| `rbac.view_as` | "Read-only while viewing as {user}." | registered | E09-D09 | §4.1 |
| `rbac.permission` | "Your role can't change positions." | registered | E09-D09 | §4.1 |
| `rbac.account_read_only` | "You can view this account, not trade it." | registered | E09-D09 | §4.1 |
| `recon.stale` | "Stale — new orders locked until the owner resolves it." | PROPOSED | E29-D03 (D03:311), for E09-D09's owner | §4.1 |
""",
    "7. ": """
A-rows are the hand-off's §C; the C-rows, G-rows and the drift ledger follow.
""",
    "7.1 ": """
| A | Component | Form |
| --- | --- | --- |
| A-1 | CMP-114 PositionsGrid | the whole entry (hand-off §C.1) |
""",
    "7.2 ": """
| C | Ticket or source says | Resolution | Owner |
| --- | --- | --- | --- |
| D04-C1 | T DoD 1–2: "`15` updated", "Motion spec merged into `16` addendum" | copy-ready A-rows in the hand-off; E29-T09 applies them (RULED BQ-2; owner approval pending (#2701)) | the owner (#823) |
| D04-C2 | T Scope: "pending/optimistic and rejected variants" | pending is a state, never drawn as confirmed (D02:325) | E29-D02 (merged) |
| D04-C3 | `16`:179 "colour-only momentary text tint" | not adopted: no flash under reduce; the text delta is the change | E05-D03 (#3174) |
| D04-C4 | T Scope: "pending shimmer" | none: pending is a state at frame 0 (RULED BQ-10; owner approval pending (#2701)) | the owner (#823) |
| D04-C5 | a reading of T Scope that times a state change | every state swap at frame 0, `motion.duration.instant`, no easing (RULED BQ-11; owner approval pending (#2701)) | the owner (#823) |
| D04-C6 | the token names D02 and D03 bind that are not shipped | corrected by A-rows to their owners, no new token name (RULED BQ-12; owner approval pending (#2701)) | the owner (#823) |
""",
    "7.3 ": """
| G | Gap | Owner |
| --- | --- | --- |
| D04-G1 | `groupBy` lacks `trade_group` (D02:611) | E29-T07 |
""",
    "7.4 ": """
| DR | Source (merged at) | Bound | Class | Replacement (exact) | Owner | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| DR-1 | `15`:1305 | `color.text.buy` | b | `color.buy.default` through CMP-020's sign rule | E05-D03 (#3174) | corrected |
| DR-2 | `15`:1408 | `color.status.danger` | b | `color.status.danger.default` | E29-T09 (with E33-D04 A-6, PENDING) | corrected |
""",
    "8. ": """
Ticket items, screens, stories and the gate tool's mutation list.
""",
    "8.1 ": """
| Item | SCR | CMP | US |
| --- | --- | --- | --- |
| The positions grid | SCR-063 | CMP-114 | US-POS-006 |
""",
    "8.2 ": fix_gates,
    "9. ": """
Text-first E29-D04: four entries written whole, two amended and one reuse contract, the motion table and the gate tool; the drawn frames follow in the boards PR.
""",
}

FIXTURE_HAND: dict[str, Block] = {
    "§A ": """
| A | Component | Form | Placement in `15` |
| --- | --- | --- | --- |
| A-1 | CMP-114 PositionsGrid | the whole entry (§C.1) | in place (`15`:1240) |
| A-5 | CMP-123 FlattenAllButton | Old → New (§C.5) | in place (`15`:1403) |
| — | the `16` block | new block (§C.6), routed to E05-D03 (#3174) | after `16` §7.1 (`16`:185) |
""",
    "§B ": """
| Entry | dark compact | dark comfortable | light compact | light comfortable | high contrast |
| --- | --- | --- | --- | --- | --- |
| CMP-114 | board 01 | on request | board 08 | on request | measured (§5) |
""",
    "§C ": """
Whole entries in `15` §0.1 bullet order; field deltas in Table A, each Old cell verbatim at its `15` line.
""",
    "C.1 ": """
```markdown
### CMP-114 PositionsGrid

- **Tier**: Organism (trading) · **Purpose**: the cross-account positions grid (extends CMP-049) with the liq-proximity warning rows.
- **A11y**: Keyboard: a treegrid with one roving stop; Accessible name: the environment leads in a mixed view; Live region: row updates are never announced individually.
```
""",
    "C.2 ": """
```markdown
### CMP-115 OrderRow

- **Tier**: Molecule (trading) · **Purpose**: one row of the working-orders grid.
- **A11y**: Keyboard: CMP-114's treegrid model; Accessible name: the status word leads; Live region: filled and rejected are assertive, once.
```
""",
    "C.3 ": """
```markdown
### CMP-116 PnLBadge

- **Tier**: Atom (trading) · **Purpose**: a signed PnL value with its accent bar.
- **A11y**: Keyboard: none, not interactive; Accessible name: the sign and the value in words; Live region: none of its own.
```
""",
    "C.4 ": """
```markdown
### CMP-129 PositionModeToggle (One-Way/Hedge)

- **Tier**: Molecule (trading) · **Purpose**: the position mode, shown read-only or changed behind a confirm.
- **A11y**: Keyboard: the display variant is not a Tab stop; Accessible name: the mode as text; Live region: none of its own.
```
""",
    "C.5 ": """
| A | Component | Field (`15`:line) | Old (verbatim) | New |
| --- | --- | --- | --- | --- |
| A-5.1 | CMP-123 | Tokens (`15`:1408) | `color.status.danger`. | `color.status.danger.default`. |
| A-5.2 | CMP-123 | A11y (`15`:1407) | CMP-044 composition, always keyboard-operable (never a mouse-hold-only gate). | Keyboard: the hold with a second `Enter`; Accessible name: scope and effect; Live region: the result line, polite once. |
| A-6.1 | CMP-049 | A11y (`15`:530) | semantic `<table>` with `scope` on headers even when virtualized | Keyboard: one roving stop; Accessible name: each row's first cell; Live region: results polite, once each. |
""",
    "C.6 ": """
```markdown
### 7.n Blotter row motion (E29-D04; PROPOSED until the owner's approval)

Spec: `docs/design/E29/E29-D04.md` §3. Tokens used by name, none added: `motion.duration.{instant,fast,normal}` and `motion.easing.{standard,decelerate,accelerate}`.

| Surface | Enter | Hold / clear | Source |
| --- | --- | --- | --- |
| row insert (CMP-114, CMP-115) | opacity over `fast`; `prefers-reduced-motion`: at frame 0 with its marker | the "New" marker for {{audit:cited.d01.new-marker-s}} s | E29-D04 §3 Mo-1 |
| value-change flash (numeric cells) | an opacity overlay decaying over `fast`; `prefers-reduced-motion`: no flash, the signed text is the change | ≥ {{audit:cited.16.flash-gap-ms}} ms between starts per cell | E29-D04 §3 Mo-3 |
| state swap | at frame 0; `prefers-reduced-motion`: the same cut at frame 0 | none | E29-D04 §3 Mo-8 |
```
""",
    "§D ": """
| Entry | Stories |
| --- | --- |
| CMP-114 | Default, LiqWarningRows, ProtectionStates, ReducedMotion |
""",
    "§E ": """
| Entry | Tests |
| --- | --- |
| CMP-114 | axe, the keyboard model, the live-region cadence, the reduced-motion twin |
""",
    "§F ": """
- **Q-1** The ADL rank column waits for its data contract (D02:611); its owner is E29-T07.
""",
}


# ---------------------------------------------------------------------------- the mutations

MO_WORDS = ("Mo", "Property")
STATE_WORDS = ("Frame", "State", "Word")
GATED_WORDS = ("Control", "Legs")


def with_values(build: Callable[[Values], Edit]) -> Edit:
    return lambda text, v: build(v)(text, v)


def drop_line(head: str, prefix: str) -> Edit:
    """Delete the first line of the section `head` starting with `prefix`."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith(prefix):
                del lines[i]
                return text.replace(block, "\n".join(lines), 1)
        return text

    return run


def mo_edit(pick: Callable[[dict[str, str]], bool], column: str, fn: Callable[[str], str]) -> Edit:
    return edit_row("3.2 The motion table", MO_WORDS, is_mo(pick), column, fn)


def swap_row(r: dict[str, str]) -> bool:
    return re.search(SWAP_ROW, norm_text(col(r, "Component") + " " + col(r, "Trigger"))) is not None


def first(_r: dict[str, str]) -> bool:
    return True


def eleven(text: str, v: Values) -> str:
    row = "| 11 | `E29-D04 / 11 extra-light` | light twin of 05 | PENDING: drawn in the boards PR |"
    return add_row("0. Planned boards", ("#", "Board"), row)(text, v)


def board_07(r: dict[str, str]) -> bool:
    return col(r, "#").strip() == "07"


LONG_REASON = '"Stale — new orders stay locked until the owner of the account resolves the lock."'

MUTATIONS: tuple[Mutation, ...] = (
    # M1, M2 — a motion row longer than `motion.duration.normal`; `slow` on a row
    Mutation(
        "M1",
        "G-ROW-200",
        "BQ-9",
        spec=with_values(
            lambda v: mo_edit(animated, "Duration", to(f"{marker(v, 'motion.duration.slow')} ms"))
        ),
    ),
    Mutation(
        "M1.2",
        "G-ROW-200",
        "BQ-9",
        spec=prose_at(
            "3.1 ", lambda v: f"A new row fades in over {marker(v, 'motion.duration.slow')} ms."
        ),
    ),
    Mutation(
        "M2", "G-ROW-200", "BQ-12", spec=mo_edit(animated, "Duration", to("`motion.duration.slow`"))
    ),
    # M3 — a Property outside opacity, transform and none
    Mutation("M3", "G-COMPOSITOR", "BQ-9", spec=mo_edit(animated, "Property", to("`height`"))),
    Mutation(
        "M3.2",
        "G-COMPOSITOR",
        "T Perf",
        spec=prose_at("3.1 ", "The row grows its height over `motion.duration.fast`."),
    ),
    # M4 — a row without its reduce twin
    Mutation("M4", "G-TWIN", "BQ-9", spec=mo_edit(first, TWIN, to(""))),
    Mutation("M4.2", "G-TWIN", "AC2", spec=prose_at("3.6 ", "Mo-3 has no reduced twin.")),
    Mutation(
        "M4.3",
        "G-TWIN",
        "BQ-2",
        hand=edit_row(
            "C.6 The `16` block",
            ("Surface", "Enter"),
            first,
            "Enter",
            lambda c: c.split("`prefers-reduced-motion`")[0].rstrip("; "),
        ),
    ),
    # M5 — a twin that is not instant
    Mutation(
        "M5",
        "G-REDUCE-INSTANT",
        "BQ-9",
        spec=mo_edit(
            animated,
            TWIN,
            to("prefers-reduced-motion: the row fades in over `motion.duration.fast`"),
        ),
    ),
    Mutation(
        "M5.2",
        "G-REDUCE-INSTANT",
        "AC2",
        spec=prose_at("3.6 ", "Under reduced motion the row still slides in."),
    ),
    # M6 — a state swap animated, one mutation per kind (RULED BQ-11)
    Mutation(
        "M6.1",
        "G-INSTANT",
        "BQ-11 status words",
        spec=prose_at("3.3 ", "The status word cross-fades from Working to Filled."),
    ),
    Mutation(
        "M6.2",
        "G-INSTANT",
        "BQ-11 glyphs",
        spec=edit_row(
            "2.2 CMP-115",
            STATE_WORDS,
            first,
            "Motion",
            to("the glyph fades over `motion.duration.fast`"),
        ),
    ),
    Mutation(
        "M6.3",
        "G-INSTANT",
        "BQ-11 fills",
        spec=prose_at("3.3 ", "The tag fill eases to its new tone over `motion.duration.normal`."),
    ),
    Mutation(
        "M6.4",
        "G-INSTANT",
        "BQ-11 pills",
        spec=prose_at("4.3 ", "The status pill slides in when the status changes."),
    ),
    Mutation(
        "M6.5",
        "G-INSTANT",
        "BQ-11 liq tier",
        spec=mo_edit(swap_row, "Duration", to("`motion.duration.fast`")),
    ),
    Mutation(
        "M6.6",
        "G-INSTANT",
        "BQ-11 protection chip",
        spec=prose_at("2.1 ", "The protection chip animates from attaching to protected."),
    ),
    Mutation(
        "M6.7",
        "G-INSTANT",
        "BQ-11 T2 ↔ enabled",
        spec=prose_at("4.2 ", "T2 ↔ enabled fades over `motion.duration.fast`."),
    ),
    Mutation(
        "M6.8",
        "G-INSTANT",
        "BQ-11 DEMO / LIVE",
        spec=prose_at("4.3 ", "The DEMO ↔ LIVE pill cross-fades."),
    ),
    # M7 — a shimmer, pulse or loop word anywhere, any case
    Mutation("M7.1", "G-LOOP", "BQ-10", spec=prose_at("2.2 ", "The pending tag shows a Shimmer.")),
    Mutation(
        "M7.2", "G-LOOP", "BQ-10", spec=mo_edit(animated, "Trigger", appended(" (the row PULSES)"))
    ),
    Mutation(
        "M7.3", "G-LOOP", "BQ-10", hand=prose_at("§D ", "Each story shows the looping highlight.")
    ),
    # M8 — an animation per tick or per update
    Mutation(
        "M8.1",
        "G-TICK",
        "BQ-9",
        spec=prose_at("2.3 ", "The PnL badge flashes on every price update."),
    ),
    Mutation(
        "M8.2",
        "G-TICK",
        "BQ-9",
        spec=mo_edit(lambda r: "between starts" in col(r, "Limit"), "Trigger", to("each tick")),
    ),
    # M9 — a pending row drawn as confirmed
    Mutation(
        "M9.1",
        "G-PENDING",
        "BQ-5",
        spec=edit_row(
            "2.2 CMP-115",
            STATE_WORDS,
            lambda r: "pending" in norm_text(col(r, "State")),
            "Word",
            to('"Working"'),
        ),
    ),
    Mutation(
        "M9.2", "G-PENDING", "BQ-5", spec=prose_at("2.2 ", "A pending amend is drawn as confirmed.")
    ),
    # M10 — the flatten confirm losing hold or typed on LIVE; the hold restated by a host
    Mutation(
        "M10.1",
        "G-FLATTEN",
        "BQ-7",
        spec=edit_row(
            "2.4 CMP-123",
            ("Environment", "Confirm"),
            lambda r: "LIVE" in col(r, "Environment"),
            "Confirm",
            to("CMP-044 `hold`"),
        ),
    ),
    Mutation(
        "M10.2",
        "G-FLATTEN",
        "BQ-7",
        spec=prose_at("2.4 ", "On LIVE, flatten takes the typed word only."),
    ),
    Mutation(
        "M10.3",
        "G-FLATTEN",
        "AC3",
        spec=prose_at(
            "2.1 ",
            lambda v: f"Flatten account holds for {marker(v, 'cited.cmp044.hold-ms')} ms.",
        ),
    ),
    # M11 — CMP-129's display variant given a control role or a T2
    Mutation(
        "M11.1",
        "G-DISPLAY",
        "BQ-8",
        spec=edit_row(
            "2.5 CMP-129",
            STATE_WORDS,
            lambda r: "/display" in col(r, "Frame"),
            "T2",
            to("`rbac.owner_only`"),
        ),
    ),
    Mutation(
        "M11.2",
        "G-DISPLAY",
        "BQ-8",
        spec=prose_at("2.5 ", 'The display variant takes `role="radiogroup"`.'),
    ),
    # M12 — a T2 leg out of order, view-as missing, a control hidden
    Mutation(
        "M12.1",
        "G-VIEWAS",
        "BQ-13",
        spec=edit_row(
            "4.1 The gated controls",
            GATED_WORDS,
            lambda r: len(legs_of(col(r, "Legs"))) >= 2,
            "Legs",
            swap_legs,
        ),
    ),
    Mutation(
        "M12.2",
        "G-VIEWAS",
        "BQ-13",
        spec=edit_row(
            "4.1 The gated controls",
            GATED_WORDS,
            lambda r: "rbac.view_as" in col(r, "Legs"),
            "Legs",
            lambda c: c.replace("`rbac.view_as` → ", "", 1),
        ),
    ),
    Mutation("M12.3", "G-VIEWAS", "BQ-13", spec=prose_at("4.2 ", "Close is hidden for a Viewer.")),
    # M13 — an exit gated
    Mutation(
        "M13.1",
        "G-EXITS",
        "BQ-13",
        spec=edit_row(
            "4.1 The gated controls",
            GATED_WORDS,
            lambda r: "exit" in norm_text(col(r, "Kind")),
            "Legs",
            appended(" → `rbac.env`"),
        ),
    ),
    Mutation(
        "M13.2",
        "G-EXITS",
        "BQ-13",
        spec=prose_at("4.2 ", "Cancel is T2 while the account is reconciling."),
    ),
    # M14 — an a11y line missing; a row update announced
    Mutation("M14.1", "G-A11Y", "BQ-14", spec=drop_line("2.3 ", "- **Live region:**")),
    Mutation(
        "M14.2", "G-A11Y", "BQ-14", spec=prose_at("2.1 ", "Each row update is announced politely.")
    ),
    # M15 — `15` or `16` touched
    Mutation("M15.1", "G-UNTOUCHED", "BQ-2", p15=lambda x: x + " "),
    Mutation("M15.2", "G-UNTOUCHED", "BQ-2", p16=crlf),
    # M16 — a value not reproduced by `--json`
    Mutation(
        "M16.1",
        "G-VALUE",
        "condition",
        spec=sub_in("0. Planned boards", "audit:count.boards=10 -->", "audit:count.boards=11 -->"),
    ),
    Mutation(
        "M16.2", "G-VALUE", "condition", spec=prose_at("5. ", "The tag sits 16 px from the edge.")
    ),
    # M17 — a new design-system name (backticked, any case, a CSS variable)
    Mutation(
        "M17.1",
        "G-TOKEN",
        "BQ-12",
        spec=prose_at("3.5 ", "The overlay binds `color.blotter.flash`."),
    ),
    Mutation(
        "M17.2", "G-TOKEN", "BQ-12", spec=prose_at("3.5 ", "The overlay binds Color.Blotter.Flash.")
    ),
    Mutation(
        "M17.3",
        "G-TOKEN",
        "BQ-12",
        spec=prose_at("3.5 ", "The overlay binds `--cv-color-blotter-flash`."),
    ),
    # M18, M19 — the security text: edited, moved, duplicated; an environment word changed
    Mutation(
        "M18.1",
        "G-SEC-PIN",
        "BQ-16",
        spec=line_edit("**Fixtures.**", "No key material", "No key matter"),
        pinned=True,
    ),
    Mutation("M18.2", "G-SEC-PIN", "BQ-16", spec=move_fixture_sentence, pinned=True),
    Mutation("M18.3", "G-SEC-PIN", "BQ-16", spec=duplicate_fixture_sentence, pinned=True),
    Mutation(
        "M19",
        "G-SEC-PIN",
        "BQ-16",
        spec=line_edit("**Fixtures.**", "and shows LIVE", "and shows DEMO"),
        pinned=True,
    ),
    # the structural gates
    Mutation(
        "M20",
        "G-RULED",
        "condition",
        spec=line_edit("## The sixteen", f"comment {RULING_ID}", "comment 6397030902"),
    ),
    Mutation("M21", "G-OWNER", "BQ-10", spec=line_edit("| BQ-10 ", f"; {OWNER_MARK}", "")),
    Mutation("M22", "G-AC", "BQ-2", spec=line_edit("| AC1 —", "met as copy-ready A-rows; ", "")),
    Mutation(
        "M23",
        "G-CROW",
        "BQ-10",
        spec=drop_row(
            "7.2 Contradictions", ("C", "Resolution"), lambda r: "shimmer" in " ".join(r.values())
        ),
    ),
    Mutation("M24.1", "G-BOARDS", "BQ-15", spec=eleven),
    Mutation(
        "M24.2",
        "G-BOARDS",
        "BQ-15",
        spec=chain(
            edit_row(
                "0. Planned boards",
                ("#", "Board"),
                board_07,
                "Board",
                to("`E29-D04 / 07 motion-reduced-twins-light`"),
            ),
            edit_row(
                "0. Planned boards", ("#", "Board"), board_07, "Draws", to("light twin of 06")
            ),
        ),
    ),
    Mutation("M25.1", "G-BUDGET", "BQ-1", spec=overrun),
    Mutation(
        "M25.2",
        "G-BUDGET",
        "BQ-1",
        spec=prose_at("9. Summary", "\n".join(f"Line {i}." for i in range(SUMMARY_LINES + 1))),
    ),
    Mutation("M26", "G-HANDOFF", "BQ-1", hand=line_edit("## §B ", "## §B ", "## §G ")),
    Mutation(
        "M27",
        "G-PLACEHOLDER",
        "BQ-1",
        spec=prose_at("1. Inputs", "> **To write (assembler):** again."),
    ),
    Mutation(
        "M28",
        "G-MUTLIST",
        "BQ-16",
        spec=edit_row(
            "8.2 The gate tool",
            ("Gate", "Mutations"),
            first,
            "Mutations",
            lambda c: c[c.find(" ") :],
        ),
    ),
    Mutation(
        "M29.1", "G-CITE", "condition", spec=line_edit("**Fixtures.**", "(D03:46)", "(D03:9999)")
    ),
    Mutation(
        "M29.2",
        "G-CITE",
        "condition",
        hand=edit_row("C.5 Table A", ("Field", "Old"), first, "Old", appended(" (edited)")),
    ),
    Mutation(
        "M30",
        "G-PIN",
        "condition",
        spec=line_edit("**Start.**", "#4114 (`c4270ba93`)", "#4114 (`75a33c164`)"),
    ),
    Mutation(
        "M31",
        "G-STATES",
        "BQ-5",
        spec=drop_row("2.2 CMP-115", STATE_WORDS, lambda r: "Quarantined" in col(r, "Word")),
    ),
    Mutation(
        "M32",
        "G-ORPHAN",
        "AC1",
        spec=drop_row("2.10 The AC1 map", ("CMP", "Role"), lambda r: "CMP-099" in col(r, "CMP")),
    ),
    Mutation(
        "M33",
        "G-CONTRAST",
        "BQ-14",
        spec=edit_row(
            "5. Tokens and contrast",
            ("Pair", "fg", "bg"),
            lambda r: col(r, "Pair").strip("`") == "digits",
            "fg",
            to("`color.text.secondary`"),
        ),
    ),
    Mutation("M34", "G-CVD-PORT", "BQ-16", patch=nudge_projection),
    Mutation(
        "M35",
        "G-DRIFT",
        "BQ-12",
        spec=edit_row("7.4 Drift ledger", ("DR", "Verdict"), first, "Verdict", to("")),
    ),
    Mutation(
        "M36",
        "G-ENV",
        "BQ-13",
        spec=prose_at("4.3 ", "The footer shows totals across environments."),
    ),
    Mutation(
        "M37.1",
        "G-COPY",
        "BQ-13",
        spec=edit_row(
            "6. Copy keys",
            ("Key", "Status"),
            lambda r: "recon." in col(r, "Key"),
            "Status",
            to("registered"),
        ),
    ),
    Mutation(
        "M37.2",
        "G-COPY",
        "BQ-13",
        spec=edit_row(
            "6. Copy keys",
            ("Key", "Status"),
            lambda r: "recon." in col(r, "Key"),
            "String",
            to(LONG_REASON),
        ),
    ),
)


# ---------------------------------------------------------------------------- --self-test


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(x.encode("utf-8")).hexdigest() for x in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    """The sha256 of each file's bytes as read from disk now (the restore check's evidence)."""
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def baseline(spec: str, hand: str) -> tuple[str, str, Values, list[str]]:
    """The skeleton's placeholders filled from FIXTURE, then every `{{audit:NAME}}` filled; the
    values frozen at that filled text."""
    s0 = fill_placeholders(spec, FIXTURE_SPEC)
    h0 = fill_placeholders(hand, FIXTURE_HAND)
    values = compute(s0)[0]
    s1, unknown = fill(s0, values)
    h1, unknown_h = fill(h0, values)
    return s1, h1, compute(s1)[0], unknown + unknown_h


def selftest(
    spec: str, hand: str, p15: str, p16: str, paths: tuple[Path, ...]
) -> tuple[bool, list[str]]:
    on_disk = digest(paths)
    s1, h1, values, unknown = baseline(spec, hand)
    used = s1 != fill(spec, values)[0] or h1 != fill(hand, values)[0]
    inputs, names = read_inputs(), diff_names()
    base_t = Texts(s1, h1, p15, p16, inputs, values, names, render_pins(s1, h1))
    base_fails, base_warns = audit(base_t)
    where = "the skeleton with FIXTURE filling its placeholders" if used else "the spec on disk"
    lines = [f"baseline: {where}: {len(base_fails)} FAIL, {len(base_warns)} WARN"]
    lines += [f"  baseline FAIL {x[:170]}" for x in base_fails]
    lines += [f"  unknown value {{{{audit:{u}}}}}" for u in unknown]
    ok = not base_fails and not unknown
    gated = {mu.gate for mu in MUTATIONS}
    for tag in GATE_TAGS:
        if tag not in gated:
            ok = False
            lines.append(f"  {tag} has no mutation (every gate needs one)")
    pristine = digest_texts(s1, h1, p15, p16)
    for mu in MUTATIONS:
        s = mu.spec(s1, values) if mu.spec else s1
        h = mu.hand(h1, values) if mu.hand else h1
        q15 = mu.p15(p15) if mu.p15 else p15
        q16 = mu.p16(p16) if mu.p16 else p16
        if (s, h, q15, q16) == (s1, h1, p15, p16) and mu.patch is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (its target is not in the text)")
            continue
        undo = mu.patch() if mu.patch else None
        try:
            pins = base_t.pins if mu.pinned else render_pins(s, h)
            fails, _w = audit(Texts(s, h, q15, q16, inputs, values, names, pins))
        finally:
            if undo:
                undo()
        new = [x for x in fails if x not in base_fails]
        named = [x for x in new if x.startswith(f"[{mu.gate}]")]
        hit = bool(named) and len(new) == 1
        restored = digest_texts(s1, h1, p15, p16) == pristine and digest(paths) == on_disk
        ok = ok and hit and restored
        shown = (named or new or ["nothing new"])[0][:130]
        lines.append(
            f"  {mu.mid} [{mu.gate}] {'ok' if hit else 'MISSED'} "
            f"({len(new)} new{'' if restored else ', NOT RESTORED'}) — {shown}"
        )
        if not hit:
            lines += [f"      new: {x[:170]}" for x in new]
    again, _w = audit(base_t)
    if again:
        ok = False
        lines.append(f"  restore: the baseline fails again ({len(again)} FAIL)")
    else:
        lines.append("  restore: the baseline audits clean (rc 0) and every file is byte-identical")
    return ok, lines


# ---------------------------------------------------------------------------- main


def read_texts() -> tuple[str, str, str, str]:
    spec = (ROOT / SPEC_REL).read_text(encoding="utf-8")
    hand = (ROOT / HAND_REL).read_text(encoding="utf-8")
    # `15` / `16` as bytes, so a line-ending change is a change (G-UNTOUCHED)
    p15 = (ROOT / P15_REL).read_bytes().decode("utf-8")
    p16 = (ROOT / P16_REL).read_bytes().decode("utf-8")
    return spec, hand, p15, p16


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="E29-D04 DS and motion audit (module docstring)")
    ap.add_argument("--check", action="store_true", help="audit the spec and the hand-off")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="fill {{audit:NAME}}, then check")
    ap.add_argument("--self-test", "--selftest", dest="selftest", action="store_true")
    ap.add_argument("--repin-security", dest="repin", action="store_true")
    ap.add_argument("--fixture", metavar="HEADING", help="print FIXTURE's block for a heading")
    args = ap.parse_args(argv)
    spec, hand, p15, p16 = read_texts()
    if args.fixture:
        blocks = {**FIXTURE_SPEC, **FIXTURE_HAND}
        prefix = next((k for k in blocks if k.strip() == args.fixture.strip()), None)
        if prefix is None:
            print(
                f"no fixture block {args.fixture!r}; one of: {', '.join(repr(k) for k in blocks)}"
            )
            return 1
        block = blocks[prefix]
        text = block() if callable(block) else block
        print(fill(text.strip("\n"), baseline(spec, hand)[2])[0])
        return 0
    if args.repin:
        print(render_pins(spec, hand))
        return 0
    if args.selftest:
        paths = tuple(ROOT / r for r in (SPEC_REL, HAND_REL, P15_REL, P16_REL))
        ok, lines = selftest(spec, hand, p15, p16, paths)
        print("\n".join(lines))
        print(f"--self-test: {'ok' if ok else 'FAIL'} — {len(MUTATIONS)} mutations, in memory")
        return 0 if ok else 1
    values, extra = compute(spec)
    if args.fill:
        spec, unknown = fill(spec, values)
        hand, unknown_h = fill(hand, values)
        (ROOT / SPEC_REL).write_text(spec, encoding="utf-8")
        (ROOT / HAND_REL).write_text(hand, encoding="utf-8")
        for u in unknown + unknown_h:
            print(f"FAIL --fill: no value for {{{{audit:{u}}}}}")
        values, extra = compute(spec)
    doc: dict[str, object] = {"base": BASE, "values": values, **extra}
    if args.json and not (args.check or args.fill):
        print(json.dumps(doc, ensure_ascii=False, indent=1))
        return 0
    t = Texts(spec, hand, p15, p16, read_inputs(), values, diff_names(), SEC_PIN_TXT)
    fails, warns = audit(t)
    if args.json:
        doc.update({"fails": fails, "warnings": warns})
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print(f"## E29-D04 audit of {SPEC_REL} (+ the hand-off) at base {BASE}")
        print(f"values: {len(values)}; gates: {len(GATES)}; mutations: {len(MUTATIONS)}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK — every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(warns)} WARN")
    return 1 if fails else 0


# ---------------------------------------------------------------------------- the pinned table
# The security-bearing clauses of the spec and the hand-off (§ doc ‖ section, @ where, the text
# indented two spaces). `--repin-security` prints this table from the current text; a reviewer
# reads the diff and commits it here. `--check` never re-pins.
SEC_PIN_TXT = r"""
§ spec ‖ E29-D04 — Design-system contributions and motion
@ prose
  **Scope** (the ticket): the five catalogued components SCR-063 and SCR-078 introduce or extend —
  CMP-114 PositionsGrid, CMP-115 OrderRow, CMP-116 PnLBadge, CMP-123 FlattenAllButton and CMP-129
  PositionModeToggle — and the reuse contract for CMP-105 AccountMultiSelect, made design-system
  entries with props, states, tokens and the three a11y lines; and the motion spec for the blotter
  rows (row insert and remove, the value-change flash, the correction highlight), nothing longer
  than `motion.duration.normal` on a data row.
@ prose
  **Numbers.** Every token, motion, distance, contrast and count figure carries an `audit` marker
  (an HTML comment `NAME=VALUE`) that `docs/design/_tools/e29_d04_ds_motion_audit.py` re-derives
  from its `--json` under `--check` (RULED BQ-16); no figure with a unit is typed by hand.
@ prose
  **Fixtures.** Every example uses the fixture accounts Main, Sub-1 and Sub-2 and shows LIVE, as
  D02's boards do; E29 runs on DEMO until R4, where the same frames carry DEMO with identical copy
  (D03:46).
@ prose
  No key material, signature, full order id or real balance appears in this file, the hand-off or
  a board.
§ spec ‖ Acceptance-criteria trace (#823)
@ row AC3 — The destructive control is specifi ‖ Ticket item
  AC3 — The destructive control is specified once: FlattenAllButton's confirm is defined in the
  design system and referenced, not redefined, by E30, E31 and E39
@ row Scope — CMP-123 FlattenAllButton (destru ‖ Ticket item
  Scope — CMP-123 FlattenAllButton (destructive, hold-to-confirm)
@ row Scope — CMP-123 FlattenAllButton (destru ‖ Where
  §2.4: hold and typed on LIVE (RULED BQ-7)
@ row Scope — CMP-129 PositionModeToggle (one- ‖ Where
  §2.5: the read-only `display` variant and the toggle (RULED BQ-8)
§ spec ‖ The sixteen questions — RULED (orchestrator, com
@ row BQ-3 ‖ Built here
  contributed CMP-114, CMP-115, CMP-116 and CMP-129; amended CMP-123 and CMP-049; CMP-105 a reuse
  contract; the routed ones answered by delta or change request (§2.8); the rest consumed (§2.9);
  D02 gap 8's elements are named parts of their parent entries (§2.10)
@ row BQ-7 ‖ Question
  CMP-123: the flatten confirm specified once
@ row BQ-7 ‖ Built here
  §2.4: a composite, hold and typed on LIVE, composing E33-D04 A-6 (PENDING, by name); E30, E31
  and E39 reference it
@ row BQ-8 ‖ Built here
  §2.5: the read-only `display` variant, with no control role and no T2, and arrow-browsing never
  writes; §2.6
@ row BQ-11 ‖ Built here
  §3.3: status words, glyphs, fills, pills, the liq tier, the protection chip, T2 ↔ enabled and
  DEMO / LIVE swap at frame 0 in both modes; no token CR; owner approval pending (#2701)
@ row BQ-13 ‖ Question
  T2, view-as, environment and the copy keys
@ row BQ-13 ‖ Built here
  §4: CMP-079's `allowed` + `reason`; the legs view-as → permission → account scope or read-only
  grant → `rbac.env` → client states; exits never gated; no string redefined (§6)
§ spec ‖ Deviations (recorded, not hidden)
@ prose
  **The tool's helpers.** The tool measures contrast through the repo's design helpers,
  `contrast_check.contrast_ratio()` and the `verify_tokens.py` loader, loaded read-only (the
  E29-D02 and E30-D04 tools' method); it runs no other repo code, and its CVD projection is a port
  gated against `docs/research/_tools/cvd_simulate.py` (RULED BQ-16).
§ spec ‖ 0. Planned boards (PENDING; ten: seven dark, thr
@ row 02 ‖ Draws
  `CMP-115/*`: the fifteen statuses, each glyph + word; the amend moments (editing, pending,
  unconfirmed, rejected); the native-stop row
@ row 04 ‖ Board
  `E29-D04 / 04 flatten-confirm`
@ row 04 ‖ Draws
  `CMP-123/*`: default, holding, armed, the typed word on LIVE, busy, the T2 frames, offline
@ row 10 ‖ Board
  `E29-D04 / 10 flatten-confirm-light`
§ spec ‖ 1. Inputs and decisions
@ row D01 D7 (D01:274); D02 gap 13 (D02:622 "a ‖ Row (cited)
  D01 D7 (D01:274); D02 gap 13 (D02:622 "a Live flatten needs hold and typed")
@ row D01 D7 (D01:274); D02 gap 13 (D02:622 "a ‖ Asked of E29-D04
  the flatten confirm: a hold with a discrete second press, and on LIVE the typed confirm as well
@ row D01 D7 (D01:274); D02 gap 13 (D02:622 "a ‖ Answered
  §2.4, CMP-123's composite, defined once (RULED BQ-7; A-5)
@ row D02 gap 13 (D02:622) ‖ Asked of E29-D04
  CMP-028's tone; CMP-105 as a filter picker; CMP-129's read-only display; CMP-019
@ row E39-D03 C9 (E39-D03:383); E33-D03 D03-A2 ‖ Asked of E29-D04
  CMP-123's data contract; a CMP-123 sentence routed to E33-D04
§ spec ‖ 2. The component contributions
@ prose
  Contributed whole (hand-off A-1 to A-4): CMP-114 PositionsGrid, CMP-115 OrderRow, CMP-116
  PnLBadge and CMP-129 PositionModeToggle; amended field by field in Table A: CMP-123
  FlattenAllButton (A-5) and the CMP-049 base table (A-6); reused by contract: CMP-105
  AccountMultiSelect (A-7); answered by a delta or a change request to their owners: the
  components D02 §15 and D03 §11.2 route here (§2.8), CMP-209's drawer motion among them as A-8;
  consumed as catalogued: the rest (§2.9); D02 gap 8's elements are named parts of their parent
  entries, never new ids (§2.10; RULED BQ-3).
§ spec ‖ 2.1 CMP-114 PositionsGrid
@ prose
  Proposal (hand-off A-1; RULED BQ-4): CMP-049's `treegrid` (§2.7) with D02 D-1's levels
  (D02:142); `PositionRow` gains `env`, `rPnlToday`, `r` (null without a stop), `protection` (the
  B8 state and its `frozen` flag), `positionMode`, `adlRank` (null: on no frame yet, a contract
  gap) and `marginMode` cross, isolated or portfolio, every money field the generated
  `packages/protocol` decimal string, never `number`; `groupBy` gains `trade_group`, and Group by
  Manager stays the Owner's view choice, never T2 (D02:374); `rowActions` take CMP-079's `allowed`
  + `reason` (`15`:814), never a role prop (E09-D09:34).
@ prose
  Variants: `density`; `groupBy`; one environment or mixed (the Env column only while the account
  scope spans both, D02:146; the LIVE block, then the DEMO block, D02:441); the narrow dock at 360
  px (D02:469).
@ row `CMP-114/t2-viewer` ‖ State
  T2: a Viewer's Close ▾, `aria-disabled`, its reason the panel notice (D02:433)
@ row `CMP-114/env-mixed-view` ‖ Word
  "LIVE"
@ row `CMP-114/sl-naked` ‖ Word
  "NO SL ! 12 s"
@ row `CMP-114/sl-naked-unrecoverable` ‖ State
  `naked_unrecoverable`: the row keeps a reduce-only Close
@ row `CMP-114/sl-naked-unrecoverable` ‖ Word
  "NO SL — owner paged"
@ row `CMP-114/sl-frozen` ‖ Frame
  `CMP-114/sl-frozen`
@ row `CMP-114/sl-frozen` ‖ State
  `amend_lock.frozen`: a tighten is still sent (D02:234)
@ row `CMP-114/sl-frozen` ‖ Word
  "· frozen"
@ row `CMP-114/group-header` ‖ Word
  "▾ Main · LIVE · One-way · 1 position · uPnL +8.00 · rPnL today +37.40"
@ row `CMP-114/totals-row` ‖ Word
  "LIVE total"
@ row `CMP-114/updates-paused-chip` ‖ Fill
  `color.neutral.subtle`; `color.status.danger.subtle` while a held row carries NO SL
@ prose
  - **Keyboard:** A treegrid with one roving stop (D02:447): `↑` / `↓` rows, `←` / `→` cells (on a
  group header `→` expands and `←` collapses), `Home` / `End`, `PageUp` / `PageDown`; `Space`
  toggles the row's selection, `Shift+↑` / `Shift+↓` extend it and `Ctrl+A` selects all in view;
  `Enter` opens SCR-064 on a row; `Shift+F10` or `Menu` opens the row menu; `Ctrl+Delete` acts on
  the D01 D9 targets and confirms whenever they exclude the focused row (D02:457); `Ctrl+Shift+F`
  opens Flatten account (§2.4), its owner still open (D02:667).
@ prose
  - **Accessible name:** A row's name is its environment in a mixed view, then symbol, side, size
  and account ("LIVE · BTCUSDT · Long · 0.250 BTC · Main"); the tier cell reads the D5 label with
  the share and the distance ("Critical — near liquidation: 14 % of the entry buffer left, 0.5 %
  from liquidation", D02:222); a chip, tag or marker reads its word, its glyph named once; a T2
  control keeps its full label and its reason is the description, never the name (E09-D09:49).
@ prose
  The polite region speaks the focused row's changed values and the environment totals, at most
  once per 2 s per field, and the selection count and Near crossings once each; filled, rejected,
  offline and reconnected, NO SL and Critical crossings are assertive, once (D02:465;
  `05`:147–148).
@ prose
  Ages, "Last update", the NO SL timer and Mo-3 never speak.
§ spec ‖ 2.2 CMP-115 OrderRow
@ prose
  Proposal (hand-off A-2; RULED BQ-5): `status` widens to D01 D2's fifteen labels (D01:174–191),
  each a word with the CMP-019 glyph name D01 proposes (D01:170), drawn meanwhile as the text
  glyph; null or unmapped reads "Working — state not reported" (D02:274); `purpose` joins the type
  ("Limit · Take profit", D02:160); the sections are Working and "Conditional — not triggered"
  (D02:281); the native-stop row's Cancel takes its `sl.note` sentence (D02:291).
@ prose
  A Cancel sent behind an amend is busy, "Cancelling…" with `aria-busy`, never T2; a native stop's
  tighten in flight reads E32-D01's "Moving the stop to 63,980.0 — waiting for Bybit…" on the same
  tag (D02:320).
@ row `CMP-115/status-killed` ‖ State
  killed by the kill switch
@ row `CMP-115/status-killed` ‖ Word
  "Killed (kill switch)"
@ row `CMP-115/native-stop-row` ‖ Frame
  `CMP-115/native-stop-row`
@ row `CMP-115/native-stop-row` ‖ State
  a native-stop row: Cancel is T2 with its `sl.note` sentence (D02:291)
@ row `CMP-115/native-stop-row` ‖ Word
  "Market · Stop loss"
@ row `CMP-115/cancel-t2-held` ‖ State
  Cancel on a held order: T2, `aria-disabled`, the reason as the item's second line
§ spec ‖ 2.4 CMP-123 FlattenAllButton (the flatten confir
@ heading
  ### 2.4 CMP-123 FlattenAllButton (the flatten confirm, defined once)
@ prose
  Gap: D02 gap 13 (D02:622), and CMP-044 and CMP-211 each describe a hold of their own
  (`15`:476–478, :2506).
@ prose
  Proposal (hand-off A-5; RULED BQ-7): this entry owns the flatten confirm as a composite, defined
  once here.
@ prose
  `scope: "account"` is SCR-063's Flatten account… in each account group header's ⋯ menu
  (D02:155): `cancelAllOrders` for the account with `exclude_reduce_only: true`, then
  `closeAllPositions` with `cancel_open_orders: false`, in one confirmed gesture with an
  `Idempotency-Key` each; the dialog restates the account, its environment, the positions it
  closes and the orders it cancels, lists stops as "cancelled with the position" and ends in one
  `BulkAccountResult` line per account with "Retry failed" (D02:353, :349).
@ prose
  `scope: "all-accounts"` is the shell's FLATTEN ALL…, whose button is CMP-211 and whose dialog is
  this definition.
@ prose
  The confirm is the table below: CMP-044 `hold` with its discrete second press, and on LIVE the
  typed word first, which CMP-044 already allows, as its `typedConfirmValue` gates a `hold`
  Confirm (`15`:476; `docs/design/E05/E05-D02-feedback-overlays.md`:286–287).
@ prose
  Flatten account… leaves the ⋯ menu while its account's snapshot failed, nothing being loaded to
  act on (D02:389).
@ prose
  The word typed on LIVE is its copy owner's: D02 routes bulk words to D03's deck ("CLOSE",
  D02:349) and names none for Flatten account (D02:353), so it stays an open item, never chosen
  here.
@ row DEMO ‖ Environment
  DEMO
@ row LIVE ‖ Environment
  LIVE
@ row LIVE ‖ Confirm
  CMP-044 `hold` and the typed word (`typedConfirmValue` gates the hold, `15`:476)
@ row LIVE ‖ Discrete keyboard path
  the typed word, then a second `Enter`
@ row LIVE ‖ Source
  D02:353 "Live adds the typed confirm"
@ row `CMP-123/default` ‖ Frame
  `CMP-123/default`
@ row `CMP-123/default` ‖ Word
  "Flatten account…"
@ row `CMP-123/hover` ‖ Frame
  `CMP-123/hover`
@ row `CMP-123/hover` ‖ Word
  "Flatten account…"
@ row `CMP-123/focus-visible` ‖ Frame
  `CMP-123/focus-visible`
@ row `CMP-123/focus-visible` ‖ Word
  "Flatten account…"
@ row `CMP-123/holding` ‖ Frame
  `CMP-123/holding`
@ row `CMP-123/armed` ‖ Frame
  `CMP-123/armed`
@ row `CMP-123/typed-live` ‖ Frame
  `CMP-123/typed-live`
@ row `CMP-123/typed-live` ‖ State
  LIVE: the typed field comes first and the hold starts on a match (`15`:476)
@ row `CMP-123/typed-live` ‖ Word
  the typed word (open: its copy owner)
@ row `CMP-123/busy` ‖ Frame
  `CMP-123/busy`
@ row `CMP-123/busy` ‖ Word
  "Flatten account…"
@ row `CMP-123/t2-view-as` ‖ Frame
  `CMP-123/t2-view-as`
@ row `CMP-123/t2-view-as` ‖ State
  T2 under view-as, the panel notice its reason (D02:435)
@ row `CMP-123/t2-view-as` ‖ Word
  "Flatten account…"
@ row `CMP-123/t2-view-as` ‖ T2
  `rbac.view_as`
@ row `CMP-123/t2-viewer` ‖ Frame
  `CMP-123/t2-viewer`
@ row `CMP-123/t2-viewer` ‖ Word
  "Flatten account…"
@ row `CMP-123/t2-read-only` ‖ Frame
  `CMP-123/t2-read-only`
@ row `CMP-123/t2-read-only` ‖ State
  T2 on a read-only grant, the account header's notice
@ row `CMP-123/t2-read-only` ‖ Word
  "Flatten account…"
@ row `CMP-123/t2-manager-kill-switch` ‖ Frame
  `CMP-123/t2-manager-kill-switch`
@ row `CMP-123/t2-manager-kill-switch` ‖ State
  T2 for a Manager under the kill switch while OD-11 is open (D02:421)
@ row `CMP-123/t2-manager-kill-switch` ‖ Word
  "Flatten account…"
@ row `CMP-123/t2-manager-kill-switch` ‖ T2
  E39-D01's "Frozen — the owner closes or releases"
@ row `CMP-123/offline-rest-unreachable` ‖ Frame
  `CMP-123/offline-rest-unreachable`
@ row `CMP-123/offline-rest-unreachable` ‖ Word
  "Flatten account…"
@ prose
  - **Keyboard:** The ⋯ item opens CMP-044 with focus on Cancel; the confirm takes a held `Enter`
  or a second `Enter` within CMP-044's window, after the typed word on LIVE; `Escape` or blur
  disarms and key repeat never confirms (`15`:478); `Ctrl+Shift+F` opens it for one account, its
  owner still open (D02:667).
@ prose
  - **Accessible name:** Scope and effect, "Flatten account — Sub-1 · LIVE"; a T2 item keeps that
  name and its reason is the description (E09-D09:49).
§ spec ‖ 2.5 CMP-129 PositionModeToggle
@ prose
  Gap: SCR-063 shows the mode as text in the account group header (D02:238, :590), CMP-129 has no
  read-only form (D02:622), and a radio group writes on every arrow key (E05-D02:464–467).
@ prose
  `toggle` is CMP-003's radio group with the change held behind its own CMP-044 `standard`
  confirm, so arrow-browsing never writes; `disabled?` / `disabledReason?` give way to CMP-079's
  `allowed` + `reason`, and its reasons are the view-as leg first, then the permission leg, which
  E09-D09's chooser reads as `rbac.owner_only` "Only the owner can change account settings."
  because no other role holds `accounts:write` (E09-D09:90; `15`:1479; D02:353).
§ spec ‖ 2.6 CMP-105 AccountMultiSelect (reuse contract)
@ prose
  Each chosen account becomes a CMP-055 chip, "Account: Sub-1 ✕", its remove a labelled
  IconButton; the use adds no new variant and no T2 ever sits on a filter (D02:433).
@ prose
  - **Accessible name:** A chip reads its filter, "Account: Sub-1", and its remove "Remove filter
  Account: Sub-1" (D02:375).
§ spec ‖ 2.7 CMP-049 Table (the base contract E05-D02 G12
@ prose
  - **Accessible name:** The caption names the table; a row is named by its `rowheader` cell (the
  Symbol in SCR-063, D02:142) with its level and position; a totals row by its label ("LIVE
  total").
§ spec ‖ 2.8 The routed components (deltas and change req
@ prose
  - **2.8.6 CMP-075 EnvBadgeLocal (D02 gap 7).** A compact per-row pill: "LIVE" or "DEMO" in
  `color.text.primary` on `color.surface.raised` with a `color.env.live` or `color.env.demo`
  border, LIVE in `font.weight.bold`, `type.ui.caption` and `radius.badge`, never colour alone
  (D02:516; D03:392); its 16 px height waits for a token (D02:619).
@ prose
  The record stays a contract gap: an export reaches no server, so SR-098's audit record waits for
  G7's path (D03:478; D02:605).
@ prose
  Registered keys bind as they stand: `rbac.*`, `notice.*`, `inflight.*`, `panel.*` and E30-D02's
  `frozen`, `lockout`, `arm.*`, `refusal.*` and `guard.mismatch`.
§ spec ‖ 2.9 Consumed components (reuse only)
@ prose
  Used as catalogued, never redefined: CMP-001 Button, CMP-002 IconButton, CMP-009 Select (Group
  by), CMP-011 Tag (chips; the Fills Type toggle chips take a `toggle` variant with `aria-pressed`
  at control height, D02:299, :495, a change request to E05's owner, D02:617, and are never drawn
  as CMP-042 tabs), CMP-015 Skeleton, CMP-016 Tooltip (the T2 echo), CMP-017 Popover (the slot's
  expansion), CMP-020 NumericText, CMP-026 EmptyState, CMP-027 ErrorState, CMP-036 KeyValueRow,
  CMP-038 InlineSpinnerText, CMP-043 Dialog, CMP-044 ConfirmDialog, CMP-045 Toast, CMP-063
  DensityToggle, CMP-076 ConnectionStatus, CMP-077 ReconnectOverlay, CMP-092 DegradedModeBanner,
  CMP-093 AuditActionTrigger, CMP-100 PriceInput, CMP-101 QtyInput, CMP-117 RiskLockoutBanner,
  CMP-139 EnvironmentAwareOrderGuard and CMP-211 PanicButtons (the shell's FLATTEN ALL…, whose
  dialog is CMP-123's, §2.4); CMP-079 RbacGate wraps every T2 control and CMP-019 Icon gives it
  its `lock`, "Not available".
§ spec ‖ 2.10 The AC1 map (every SCR-063 and SCR-078 elem
@ row CMP-114 ‖ Name
  its named parts: the liquidation tier cell, the protection chip, the correction markers, the
  group header row, the totals row and the "Updates paused" chip
@ row CMP-123, CMP-211 ‖ CMP
  CMP-123, CMP-211
@ row CMP-123, CMP-211 ‖ Name
  FlattenAllButton, PanicButtons
@ row CMP-123, CMP-211 ‖ Role here
  amended (A-5): Flatten account… and its dialog; CMP-211 consumed: the shell's FLATTEN ALL…
  button
@ row CMP-036, CMP-038, CMP-043, CMP-044, CMP- ‖ Name
  KeyValueRow, InlineSpinnerText, Dialog, ConfirmDialog, Toast, ConnectionStatus,
  ReconnectOverlay, DegradedModeBanner, AuditActionTrigger, PriceInput, QtyInput,
  RiskLockoutBanner
@ row CMP-036, CMP-038, CMP-043, CMP-044, CMP- ‖ Role here
  consumed: SCR-078's summary and running export, the confirms, the cancel toast, the connection
  and account states, every write's audit, the cell editor
§ spec ‖ 3.1 Data-row rules
@ prose
  Live data never moves focus (`05`:96), a focused row never leaves (D01:408), and a focused
  control never sits inside a fading element (`docs/design/E05/E05-D02-feedback-overlays.md`:165).
§ spec ‖ 3.2 The motion table
@ row Mo-7 ‖ Component
  CMP-123's hold ring (the flatten confirm, §2.4)
@ row Mo-7 ‖ prefers-reduced-motion t
  prefers-reduced-motion: static percentage text at frame 0, per CMP-123
@ row Mo-7 ‖ Limit
  per CMP-123: dialog motion, not a data row
@ row Mo-8 ‖ Component
  a state swap (status word, glyph, fill, pill, liq tier, protection chip, T2 ↔ enabled, DEMO /
  LIVE)
@ row Mo-11 ‖ Component
  CMP-123's confirm dialog (CMP-044 on CMP-043)
§ spec ‖ 3.3 State swaps are instant (RULED BQ-11; owner
@ prose
  Status words, glyphs, fills, pills, the liq tier, the protection chip, T2 ↔ enabled and DEMO /
  LIVE swap at frame 0 in both modes (Mo-8): `motion.duration.instant` (0 ms), no easing; the
  word, the glyph, the fill and a control's availability change in the same frame (E30-D04:553;
  E09-D08:220; E11-D06:359).
§ spec ‖ 3.4 Never per tick
@ prose
  Nothing animates per tick or per price update (D02:465 "Never per tick"): ages and the "Last
  update" counter repaint as text at most once a second (D02:272), the NO SL timer swaps its
  digits as text, the account line and the row markers change only on a notice (D03:477), and no
  tab carries a count (D02:158).
§ spec ‖ 4. T2, view-as and environment on the components
@ heading
  ## 4. T2, view-as and environment on the components
@ prose
  The T2 anatomy is E09-D09's, stated once in each merged spec and only pointed to here
  (E09-D09:49; D02:429; D03:208): `aria-disabled="true"`, never the `disabled` attribute, so the
  control stays in the Tab order and the roving grid; the reason node in the DOM at mount, named
  by `aria-describedby` and swapped in place (E09-D09:236); the CMP-019 `lock` named "Not
  available" leading the label (2a) or badging the control (2b); the label in
  `color.text.tertiary`, the reason in `color.text.secondary`, a filled control on
  `color.surface.raised` with a `color.border.default` hairline, never `color.text.disabled` or
  `opacity.disabled` (the selected row's label is §5's measured exception).
@ prose
  While `GET /auth/session/view-as` reports a context, `rbac.view_as` is checked ahead of every
  other leg and one panel-header notice describes every write; reads answer as the target, so the
  target's own read-side reasons still render (D02:435; E09-D09:95).
@ prose
  The shell's view-as banner, its Exit and its countdown are E42-D02 D10's, cited and never
  restated here (E42-D02:136, :415); the countdown sits outside the live region (E42-D02:424) and
  never animates (§3.3).
@ prose
  Account labels are the fixtures' "Main", "Sub-1" and "Sub-2", ellipsised with the full label in
  the tooltip and the accessible name (D02:149).
@ prose
  No `ret_msg` and no server `message` reach the DOM; a rejected amend shows D02's own line, and
  the exchange's text lives only behind the audited diagnostics (D02:152; D03:78, :80).
@ prose
  The server authorises every request against the 4-tuple of `24` §15.2 and answers `403` with a
  stable code and an audit record (`rbac.denied`) regardless of what the UI showed — a disabled
  button, a hidden route or a missing palette command is never relied on to prevent anything
  (C-2.12, C-12.4, `04` §7.3, E09-X01 D1-shared).
§ spec ‖ 4.1 The gated controls (legs in order)
@ prose
  Legs follow the server's order of E09-D09 §2.1, view-as first (E09-D09:40); a key that is not
  registered is PROPOSED with its owner on its row and in §6; a control's own drawn cases that are
  not legs sit under Drawn exceptions.
@ prose
  **Renderings** (E09-D09:49; D02:429, :431): 2a is inline, beside a toolbar button or as a menu
  item's second line; 2b, the tooltip echo, sits only on a row's text SplitButton and only for the
  row's own reason, always repeated in the row menu, D02's extension of E09-D09 §2.2 (OQ-S,
  D02:668); a reason that covers a scope renders once as a notice that every gated control of the
  scope points at — the panel header for a Viewer, for view-as and offline, the other
  environment's section row, the account header for a read-only grant.
@ row "Close ▾" and its items "Close 25 %", "C ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only`
@ row "Close ▾" and its items "Close 25 %", "C ‖ Drawn exceptions
  offline with REST unreachable; a Manager under the kill switch, E39-D01's "Frozen — the owner
  closes or releases" (OD-11 pending); the other environment's rows, `guard.mismatch.row`
  (PROPOSED, E30-D02)
@ row "Reverse…" ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only` → `rbac.env` (a LIVE row) → client
  states: `frozen`, `recon.*`, `feed.*`, `refusal.trading_disabled.*`, `arm.locked`,
  `blotter.close_in_flight`, E39-D01's lockout line, E17-D01's feed lines
@ row "Edit price", "Edit trigger" and a quant ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only` → `rbac.env` (a risk-increasing
  amend on a LIVE row) → client states: `frozen`, `recon.*`, `feed.*`, `blotter.amend_in_flight`,
  E39-D01's lockout line
@ row "Cancel ▾" (the primary) ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only`
@ row "Cancel ▾" (the primary) ‖ Drawn exceptions
  offline with REST unreachable; the other environment's rows, `guard.mismatch.row` (PROPOSED,
  E30-D02); the order's own kind, never an account state: a native-stop row, `sl.note`'s first
  sentence (PROPOSED to E32-D01), and Untracked, Held and Unknown orders, `blotter.untracked`,
  `blotter.held` and `blotter.unknown` (PROPOSED, E29-D03)
@ row "Edit qty" lowering the quantity; a reco ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only`
@ row "Close selected" and "Close all in view… ‖ Control
  "Close selected" and "Close all in view…" (CMP-114); "Cancel selected" and "Cancel all in view…"
  (CMP-115)
@ row "Close selected" and "Close all in view… ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only`
@ row "Close selected" and "Close all in view… ‖ Drawn exceptions
  offline with REST unreachable; a Manager's closes under the kill switch (OD-11 pending); every
  target keeps its own row's gates
@ row "Flatten account…" (the account header's ‖ Control
  "Flatten account…" (the account header's ⋯ and `Ctrl+Shift+F`)
@ row "Flatten account…" (the account header's ‖ Component
  CMP-123 (`scope: account`)
@ row "Flatten account…" (the account header's ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only`
@ row "Flatten account…" (the account header's ‖ Drawn exceptions
  offline with REST unreachable; a Manager under the kill switch, E39-D01's "Frozen — the owner
  closes or releases" (OD-11 pending)
@ row "Edit risk caps…" (the account header's ‖ Legs (in order)
  `rbac.view_as` → `rbac.owner_only`
@ row "Resolve…" on the account line ‖ Legs (in order)
  `rbac.view_as` → `rbac.owner_only` with the verb "resolve the lock" (PROPOSED, an E09-D09 §3.2
  amendment)
@ row the row checkbox ‖ Legs (in order)
  none: a Viewer and view-as keep it
§ spec ‖ 4.2 Never gated
@ prose
  - **Exits keep their legs and nothing more.** Cancel, close and its items, the bulk closes and
  cancels, Flatten account…, a quantity cut and a recorded take-profit's edit and Cancel are never
  gated by a state key or `rbac.env`: in every account state of D02 §10.2 and §10.3, and under the
  kill switch for the Owner, they take only the legs of §4.1 (D02:412, :420; D03:82).
@ prose
  Two drawn exceptions remain: offline with REST unreachable, where every write is T2 (D02:333,
  :431), and a Manager's closes and Flatten account… under the kill switch, E39-D01's "Frozen —
  the owner closes or releases" while OD-11 is pending; a Manager's Cancel stays sendable there
  (D02:421; E39-D01:66, :687).
@ prose
  A Cancel's own reasons — a native-stop row, an Untracked, Held or Unknown order (§4.1) — name
  what the order is, never the account's state, and a Cancel sent while the order's amend is in
  flight stays busy, "Cancelling…", until it resolves (D02:345).
@ prose
  - **The C-2.6 carve-out.** A stop's tighten — a native stop's through `setPositionTpSl`, an
  ordinary stop order's through `amendOrder`, an attach and a re-stamp — is never T2 by view-as,
  by the kill switch, by a lockout or by a `recon.*` state: it takes the session's permission and
  trade grant, under view-as the target's, and a loosen is refused inline for every role,
  E32-D01's `sl.loosen.refused` (D02:435; D03:222; C-2.6).
@ prose
  SL/TP… and `Enter` into SCR-064 never take view-as, the kill switch, a lockout, a `recon.*`
  state or a pending TP/SL write, because they only open SCR-064, which applies those gates
  itself; they are T2 only for a Viewer, a read-only grant, the other environment's rows and
  offline with REST unreachable (D02:338).
@ prose
  Export CSV builds its file client-side, a read that stays T1; should G7's path become a
  write-method operation, it takes `rbac.view_as` alone, in 2b in the drawer's title bar (D03:181,
  :519).
@ prose
  - **Busy and form validity are not T2** (E09-D09:231): a close in flight ("Closing…"), a cancel
  held behind an amend ("Cancelling…"), an account loading, its Flatten account… included, and an
  export running take CMP-001's loading state, `aria-busy="true"` with the ⟳ glyph leading the
  label, no `lock`, no reason node and no CMP-079; a second press does nothing (D02:341, :345,
  :353, :388; D03:181).
@ prose
  "Close all in view…" and "Cancel all in view…" leave the toolbar while nothing is in view
  (D02:380), and the mandatory Columns read "Always shown" as helper text, with no `lock` and no
  reason (D02:376).
@ prose
  - **A T2 press is quiet to the server, and its swaps are cuts:** `Enter`, `Space`, `F2` or the
  bound hotkey sends nothing and re-shows the reason inline with one polite announcement, and it
  emits no audit and no analytics (E09-D09:49, :243; D02:429).
§ spec ‖ 4.3 Environment
@ prose
  The environment is the text pill "LIVE" or "DEMO" (CMP-075): `color.text.primary` on
  `color.surface.raised` with a `color.env.live` or `color.env.demo` border, never colour alone
  (`14`:81; D02:516); CMP-075's grammar, its weight, dot and border included, is E30-D04 D7's
  (E30-D04:141), and its compact per-row form is §2.8.6's change request (D02:616).
@ prose
  In a mixed view every row's accessible name leads with its environment, group headers read "Main
  · DEMO" and the panel is named "Positions and orders — LIVE and DEMO" (D02:441).
@ prose
  Totals are per environment and never summed: one totals row per environment, its rowheader "LIVE
  total" (D02:142, :156).
@ prose
  The other environment's rows stay visible and read-only behind their block's notice,
  `guard.mismatch.row` (PROPOSED, E30-D02), and `Ctrl+A`, "all in view" and every bulk dialog take
  the session environment's rows only (D02:145; C-2.11).
@ prose
  DEMO ↔ LIVE is a frame-0 cut in both modes, and the pill never animates (§3.3).
§ spec ‖ 5. Tokens and contrast (measured; every number f
@ row `flatten-confirm-label` ‖ Pair
  `flatten-confirm-label`
@ prose
  **Read from the table.** The closest margins pass: `bar-sell-selected` at 3.13 in dark and 3.70
  in light, `env-demo-border` at 3.64 in dark, `bar-buy-selected` at 3.84 and `no-sl-glyph` at
  3.85 in light, and `flatten-confirm-label` at 4.54 in high contrast; none of them carries
  meaning alone, since a word, a sign or a glyph does (§2).
@ prose
  LIVE and DEMO stay ΔE76 91.9 or more apart under every simulation and ΔL* 2.4 in greyscale on
  light, so the words LIVE and DEMO carry the environment (§4.3; `14`:81).
§ spec ‖ 6. Copy keys
@ row `rbac.view_as` ‖ Key
  `rbac.view_as`
@ row `rbac.view_as` ‖ String
  "Read-only while viewing as {user}."
@ row `rbac.account`, `rbac.account_read_only` ‖ Used on
  a refused write after `403 account_scope_denied`, sticky (E09-D09:55); §4.1: every write of an
  account held with a read-only grant, through its header's notice (D02:433)
@ row `rbac.env` ‖ String
  "Live trading isn't enabled for you."
@ row `rbac.env` ‖ Used on
  §4.1: Reverse… and a risk-increasing amend on a LIVE row, never an exit (D02:95)
@ row `notice.panel_read_only`, `glyph.name`, ‖ String
  "Read-only — {rbac sentence, first letter lower-cased}"; "Not available"; "No longer shown —
  access to {account} was withdrawn."; "Not sent — your access changed. {reason}"; "Not sent —
  read-only after three wrong codes."
@ row `notice.panel_read_only`, `glyph.name`, ‖ Used on
  the panel-header notice for a Viewer, for view-as and offline (D02:431); the name of the CMP-019
  `lock` on every T2 control; a revoked account's rows (D02:400); the refusal at the point of
  action after a role or grant change, and after three wrong codes, where the control stays T1
  (D02:437)
@ row `frozen` ‖ Key
  `frozen`
@ row `frozen` ‖ String
  "Trading frozen by the owner at {hh:mm} UTC — new orders off. Cancel and close still work."
@ row `frozen` ‖ Used on
  §4.1: the Owner's Reverse… and entry edits under the kill switch (D02:420)
@ row `arm.locked`, `arm.refused`, `refusal.tr ‖ String
  "One-click trading is locked" (`arm.refused`; `arm.locked`'s description reads "one-click off —
  Ctrl+Shift+T to arm"); "Order entry is paused for maintenance"; "{account} has no active API
  key"; "Order is for a LIVE account while the workspace is DEMO"
@ row `arm.locked`, `arm.refused`, `refusal.tr ‖ Used on
  §4.1: Reverse… on a Live account, before a press and after one (D02:337); new exposure under
  maintenance, and with no active key, held once by the account header (D02:395); CMP-139's
  reason, whose row form is PROPOSED below
@ row E39-D01's control string and lockout lin ‖ String
  "Frozen — the owner closes or releases"; "Locked · daily loss limit · until 00:00 UTC · closing
  and reducing still work"
@ row E39-D01's control string and lockout lin ‖ Used on
  §4.1: a Manager's closes and Flatten account… under the kill switch, OD-11 pending (D02:421);
  new exposure under a risk lockout (D02:423)
@ row `recon.reconciling`, `recon.desync`, `re ‖ String
  "Reconciling with Bybit — new orders are paused."; "Data being verified — new orders are
  paused."; "Stale — new orders locked until the owner resolves it."; "After the kill switch — new
  orders locked until resolved."
@ row `recon.reconciling`, `recon.desync`, `re ‖ Used on
  §4.1: every new-exposure control of an account that is reconciling, being verified, on a stale
  lock or on the lock the kill switch leaves
@ row `guard.mismatch.row` ‖ String
  "DEMO rows are read-only in a LIVE session."
@ row `guard.mismatch.row` ‖ Status
  PROPOSED (D02:145; OQ-L, D02:661), with its converse "LIVE rows are read-only in a DEMO
  session."
@ row `blotter.amend_in_flight` ‖ Used on
  §4.1: an entry's edits and a quantity cut while an amend is in flight; a native stop's edit and
  a recorded take-profit's edit and Cancel while a TP/SL write for the position is pending
@ row `sl.note`, its first sentence ‖ String
  "Every position keeps a native stop — you can move it, not delete it."
@ row `sl.note`, its first sentence ‖ Used on
  §4.1: Cancel on a native-stop row (C-2.6)
§ spec ‖ 7.1 A-rows
@ row A-5 ‖ Component
  CMP-123 FlattenAllButton
§ spec ‖ 7.2 Contradictions (C-rows)
@ row D04-C5 ‖ Resolution
  Every state swap is a cut: status words, glyphs, fills, pills, the liq tier, the protection
  chip, T2 ↔ enabled and DEMO / LIVE change at frame 0 in both modes, `motion.duration.instant`,
  no easing (§3.3; Mo-8, Mo-10, Mo-12); no token CR (RULED BQ-11; owner approval pending (#2701))
§ spec ‖ 7.3 Contract gaps (G-rows)
@ row D04-G4 ‖ Gap
  `closeAllPositions` states neither the order of its close and cancel nor that a failed close
  keeps its stop (D02:620): A-5.6 names the routes and shapes neither
@ row D04-G5 ‖ Gap
  CSV export has no endpoint, permission, audit action or size limit (D03:519, G7): CMP-099's
  export writes no server record yet
@ row D04-G7 ‖ Gap
  CMP-211 offers a `group` scope (`15`:2505) and CMP-123 has none; SCR-063 draws Flatten account…
  alone (D02:155)
@ row D04-G7 ‖ Owner
  E39-D03's owner (CMP-211), with E29-T09
§ spec ‖ 7.4 Drift ledger (RULED BQ-12; owner approval pe
@ row DR-3 ‖ Bound
  CMP-123 `color.status.danger`
§ spec ‖ 8.1 Ticket, stories and screens
@ row The flatten confirm, defined once (§2.4; ‖ Item
  The flatten confirm, defined once (§2.4; AC3)
@ row The flatten confirm, defined once (§2.4; ‖ SCR
  SCR-063; the shell's FLATTEN ALL…
@ row The flatten confirm, defined once (§2.4; ‖ CMP
  CMP-123, CMP-044, CMP-211
§ spec ‖ 8.2 The gate tool: gates and mutations
@ row G-FLATTEN ‖ Gate
  G-FLATTEN
@ row G-FLATTEN ‖ Rule (RULED)
  hold and typed on LIVE, defined once (BQ-7; AC3)
@ row G-VIEWAS ‖ Rule (RULED)
  the legs in order, view-as first; nothing hidden (BQ-13)
§ spec ‖ 9. Summary for #823 (at most ten lines)
@ prose
  - Four entries are written whole (CMP-114, CMP-115, CMP-116, CMP-129), three amended field by
  field (CMP-123, CMP-049, CMP-209) and one reused by contract (CMP-105); hand-off §C holds them
  copy-ready for E29-T09, and `15` and `16` stay byte-identical (RULED BQ-2; owner approval
  pending (#2701)).
@ prose
  - CMP-123 owns the flatten confirm once, CMP-044's hold with the typed word added on LIVE; E30,
  E31 and E39 reference it (AC3; RULED BQ-7).
@ prose
  - CMP-129 gains a read-only `display` variant with no control role, and its toggle writes only
  behind a confirm (RULED BQ-8).
@ prose
  - Every gated control takes CMP-079's `allowed` + `reason` with view-as first, and exits are
  never gated by a state key (RULED BQ-13); §5 measures 27 pairs in three themes.
§ hand-off ‖ E29-D04 — Per-component hand-off (`16` §11.4; th
@ prose
  Four entries written whole — CMP-114 PositionsGrid, CMP-115 OrderRow, CMP-116 PnLBadge and
  CMP-129 PositionModeToggle — and the field deltas to CMP-123 FlattenAllButton, the CMP-049 base
  table, the CMP-105 reuse contract and CMP-209 RightRail's drawer motion, plus the `16` motion
  block.
@ prose
  Every figure carries its `audit` marker from the tool's `--json`; E29-T09 keeps the value and
  drops the marker when it pastes a block.
§ hand-off ‖ §A Placement
@ row A-5 ‖ Component
  CMP-123 FlattenAllButton
@ prose
  E29-T09 pastes each block verbatim after the owner's approval (RULED BQ-2; owner approval
  pending (#2701)), keeping every value and dropping its `audit` marker.
§ hand-off ‖ §B Density and theme matrix
@ row CMP-123 FlattenAllButton ‖ Entry
  CMP-123 FlattenAllButton
§ hand-off ‖ §C Copy-ready `15` entries and the `16` block (P
@ prose
  Whole entries C.1 to C.4 in `15` §0.1's order as `15`'s trading entries apply it (Tier ·
  Purpose, Props, Variants, States, A11y, Tokens, API sketch, Data contract, Storybook, Tests,
  Motion spec, Design), the A11y bullet holding Keyboard, Accessible name and Live region on one
  line; the field deltas to CMP-123, CMP-049, CMP-105 and CMP-209 in Table A (C.5), each Old cell
  verbatim at its `15` line; the `16` block is C.6.
@ prose
  E29-T09 replaces an entry from its heading to its last bullet, keeps each figure and drops its
  `audit` marker.
§ hand-off ‖ C.1 A-1 — CMP-114 PositionsGrid
@ code
  - **Tier**: Organism (trading) · **Purpose**: the cross-account positions grid of SCR-063, a
  CMP-049 `treegrid` whose named parts are the liquidation tier cell, the protection chip, the row
  markers, the group header row, the totals row and the "Updates paused" chip; CMP-115 OrderRow is
  its Working-orders sibling and CMP-123 the account header's Flatten account….
@ code
  - **Variants**: compact and comfortable, 24 and 32 px rows; grouped by account (default),
  symbol, trade group or manager; one environment or mixed (the Env column and the LIVE, then DEMO
  blocks); the narrow dock at 360 px (Symbol · Side · Size · uPnL · Status).
@ code
  - **States**: rows: default, hover, selected (the CMP-005 box, `color.surface.selected`,
  `aria-selected`), focused cell (the 2 px inset ring), new ("New" for 5 s), closing (Close in
  CMP-001's loading state with its label kept and `aria-busy`, not T2), lingering closed ("Closed
  +12.40 USDT" for about 5 s), stale (CMP-078's grid-row variant). The other environment's block
  is read-only behind `guard.mismatch.row` (PROPOSED to E30-D02), and a gated control is T2 per
  E09-D09 §2.2. The liquidation tier cell: none, Watch, Near, Critical (with a 2 px leading
  accent). The protection chip: the B8 states with `amend_lock.frozen` (`flat` leaves the frame).
  The row markers of E29-D02 and E29-D03; the group header row with its state marker and ⋯ menu;
  the totals row, one per environment, never summed; the "Updates paused" chip, critical while a
  held row carries NO SL; the panel states of E29-D02 §10.1, by name.
@ code
  - **A11y**: Keyboard: a treegrid with one roving stop; arrows by row and cell, `→` and `←`
  expand and collapse a group header, `Space` selects, `Enter` opens SCR-064, `Shift+F10` the row
  menu, `Ctrl+Delete` the D01 D9 targets with a confirm whenever they exclude the focused row;
  Accessible name: the environment leads in a mixed view, then symbol, side, size and account; a
  tier, chip or marker reads its word with its glyph named once; a T2 control keeps its full label
  and its reason is the description; Live region: row updates are never announced individually;
  the focused row's changed values and the environment totals speak politely at most once per 2 s
  per field; filled, rejected, offline and reconnected, NO SL and Critical crossings are
  assertive, once.
@ code
  - **API sketch**: `interface PositionRow { id: string; accountId: string; env: "live" | "demo";
  symbol: string; side: "long" | "short"; positionIdx: 0 | 1 | 2; size: string; entryPrice:
  string; markPrice: string; liqPrice: string | null; unrealizedPnl: string; rPnlToday: string; r:
  string | null; leverage: string; marginMode: "cross" | "isolated" | "portfolio"; positionMode:
  "one-way" | "hedge"; protection: { state: "protected" | "attaching" | "verifying" | "amending" |
  "naked" | "naked_unrecoverable"; frozen: boolean }; adlRank: number | null; liqTier: "none" |
  "watch" | "near" | "critical" }`; money and price fields are the generated `packages/protocol`
  decimal strings, never `number`.
@ code
  - **Data contract**: `positions` from the private `positions` WS topic (`23` §15.2
  `PositionUpdate`) merged with the REST position-list snapshot; `positionMode` from
  `ExchangeAccount.position_mode`; the tier derived client-side from the mark, the liquidation
  price and the entry buffer (E29-D02 §5.3); `adlRank` is on no frame yet and its column stays out
  of view (a contract gap).
@ code
  - **Tests**: unit, visual, axe, keyboard row and cell navigation, the treegrid roles, levels and
  indices on a 500-row fixture, the live-region cadence (never per tick), the T2 tests (view-as
  first, `aria-disabled`, no audit or analytics on a T2 press), busy is never T2, performance
  (1,000 rows at the frame budget).
§ hand-off ‖ C.2 A-2 — CMP-115 OrderRow
@ code
  - **Variants**: compact and comfortable, as CMP-114; the sections Working and "Conditional — not
  triggered"; the native-stop row, whose Cancel is T2 with its `sl.note` sentence (PROPOSED to
  E32-D01); the narrow dock, where the purpose folds into the state word ("Working · Stop loss").
@ code
  - **States**: the fifteen D01 D2 words, each with its glyph: Sending, Working, Triggered,
  Partial, Cancelling, Amending, Unknown — checking, Quarantined, Held — owner review, Untracked —
  not placed by CandleViewer, Filled, Cancelled, Rejected, Expired, Killed (kill switch). Null or
  unmapped reads "Working — state not reported". The amend moments: editing ("Editing — 2,500.00
  is live"); `pending`, a state ("Amending → 2,495.00 · 2,500.00 still live", the ⟳ marker and the
  tag on `color.status.info.subtle`, the value cell keeping the live value); unconfirmed ("Unknown
  — checking · 2,500.00 may still be live"); rejected ("⚠ Amend rejected — your order is
  unchanged" with Dismiss). A Cancel sent behind an amend is busy ("Cancelling…", `aria-busy`),
  never T2. The T2 reasons `blotter.untracked`, `blotter.held`, `blotter.unknown` and
  `blotter.amend_in_flight` are PROPOSED with E29-D03 as their owner. Filled and Cancelled linger
  about 5 s.
@ code
  - **Data contract**: the private `orders` WS topic (`23` §15.1 `OrderUpdate`, never throttled)
  merged with the REST open-orders snapshot; `lifecycle_state` maps to the D01 D2 word, null or
  unmapped to "Working — state not reported"; a pending amend waits for the `change: "amend"`
  frame and a native stop's edit for the read that shows it; the exchange's text never reaches the
  row (`getOrderDiagnostics` only).
§ hand-off ‖ C.4 A-4 — CMP-129 PositionModeToggle
@ code
  - **Variants**: `display`: the word as text, read-only, outside the Tab order, with neither a
  control role nor a reason. `toggle`: CMP-003's radio group, its change held behind a CMP-044
  `standard` confirm, so arrow-browsing never writes.
@ code
  - **States**: `display`: one-way, hedge. `toggle`: default, hover, focus-visible, an option
  arrowed but unwritten, the confirm open, T2 (the view-as leg first, then the permission leg,
  read as `rbac.owner_only` for `accounts:write`; the open-positions reason PROPOSED to E30-D02's
  owner, no key bound), busy while the write is in flight.
§ hand-off ‖ C.5 Table A — Old (verbatim at `6fc8aacc6`) → Ne
@ row A-5.1 ‖ Component
  CMP-123
@ row A-5.1 ‖ Old (verbatim)
  **Tier**: Molecule (trading, risk-critical) · **Purpose**: global panic-button — closes all
  positions and cancels all working orders for the active scope, gated by ConfirmDialog `hold` or
  `typed` variant.
@ row A-5.1 ‖ New
  the Old text, then (after E33-D04 A-6.1's sentence once that row has landed; PENDING): Two
  scopes: `account`, SCR-063's Flatten account… in each account group header's ⋯ menu, and
  `all-accounts`, the shell's FLATTEN ALL…, whose button is CMP-211 and whose dialog is this
  entry's. Its confirm, CMP-044 `hold` with the typed word added where E29-D04 §2.4's table asks
  for it, is defined once here and referenced, never restated, by E30, E31 and E39.
@ row A-5.2 ‖ Component
  CMP-123
@ row A-5.3 ‖ Component
  CMP-123
@ row A-5.3 ‖ New
  the Old text, then two new bullets. **Variants**: `account` (SCR-063's Flatten account…) and
  `all-accounts` (the shell's FLATTEN ALL…, its button CMP-211), each on DEMO or LIVE (E29-D04
  §2.4's confirm table). **States**: default, hover, focus-visible; the CMP-044 dialog restating
  the account, its environment, the positions it closes and the orders it cancels, stops
  "cancelled with the position"; holding (CMP-044's ring with its percentage text); armed ("Press
  again to …"); the typed word on LIVE; busy while the account loads (`aria-busy`, never T2); out
  of the ⋯ menu while the account's snapshot failed; T2 for view-as, a Viewer and a read-only
  grant, and for a Manager under the kill switch while OD-11 is open; offline with REST
  unreachable (T2); the result, one `BulkAccountResult` line per account with "Retry failed".
@ row A-5.4 ‖ Component
  CMP-123
@ row A-5.4 ‖ New
  the Old text, then: Keyboard: the item opens CMP-044 with focus on Cancel; the confirm takes a
  held `Enter` or a second `Enter` within CMP-044's window, after the typed word where E29-D04
  §2.4 asks for it; `Escape` or blur disarms and key repeat never confirms. Accessible name: scope
  and effect, "Flatten account — {account} · {environment}"; a T2 item keeps it and its reason is
  the description. Live region: the result is polite, once; nothing speaks while the hold runs.
@ row A-5.5 ‖ Component
  CMP-123
@ row A-5.6 ‖ Component
  CMP-123
@ row A-5.6 ‖ Old (verbatim)
  Bybit `/v5/order/cancel-all` + market-close per position
@ row A-5.6 ‖ New
  the server's routes, their names E39-D03 C9's content fix (its owner's, E39-D03:383): for
  `scope: "account"`, `cancelAllOrders` for the account with `exclude_reduce_only: true`, then
  `closeAllPositions` with `cancel_open_orders: false`, in one confirmed gesture with an
  `Idempotency-Key` each; stops end with their position, never as separate cancels, and a failed
  cancel does not hold the close back
@ row A-5.7 ‖ Component
  CMP-123
@ row A-5.8 ‖ Component
  CMP-123
@ row A-5.8 ‖ New
  the Old text, then: on LIVE the hold starts once the typed word matches; key repeat never
  confirms; view-as is the first leg; a T2 press emits no audit or analytics; busy is never T2;
  the reduced-motion twin shows the percentage text, static. Then two new bullets. **Motion
  spec**: Mo-7, CMP-044's ring by reference (E29-D04 §3.2). **Design (DS spec):** E29-D04 §2.4
  (E29-D04; owner approval pending).
@ row A-7.1 ‖ New
  the Old text, then: Also SCR-063's account-filter picker, reused by contract (E29-D04 §2.6):
  `mode="account"` over the server-scoped account list, without `profileSummary`, `onEditProfile`,
  group rows or leg rows; each chosen account becomes a CMP-055 chip, "Account: Sub-1 ✕".
§ hand-off ‖ C.6 The `16` block (copy-ready; recipe owner E05
@ code
  | state swap (status word, glyph, fill, pill, liq tier, protection chip, T2 ↔ enabled, DEMO /
  LIVE; a disclosure; a row's busy glyph) | at frame 0; `prefers-reduced-motion`: the same cut at
  frame 0 | none | E29-D04 Mo-8, Mo-10, Mo-12 |
§ hand-off ‖ §D Storybook stories per entry
@ row CMP-115 OrderRow ‖ Stories
  §C.2's Storybook line (RULED BQ-5): one story per status family, the pending, unconfirmed and
  rejected amend, the editor, the native-stop row, the T2 Held order and the reduced-motion
  readings
@ row CMP-123 FlattenAllButton ‖ Entry
  CMP-123 FlattenAllButton
@ row CMP-123 FlattenAllButton ‖ Stories
  Table A's Storybook row (§C.5; RULED BQ-7): the `15` two (`15`:1410), the DEMO hold, the LIVE
  hold and typed word, armed, busy, every T2 frame of spec §2.4, offline, the result and the
  reduced-motion reading
§ hand-off ‖ §E Test hooks
@ row CMP-123 FlattenAllButton ‖ Entry
  CMP-123 FlattenAllButton
@ row CMP-123 FlattenAllButton ‖ Tests
  axe; the keyboard-only confirm path of spec §2.4, key repeat never confirming; the result line
  polite once; the exits test: sendable for the Owner in every account state (spec §4.2); the T2
  test of spec §4.1's flatten row; the hold's `prefers-reduced-motion` reading (spec §3.2)
@ prose
  **The T2 test** (every row of spec §4.1): the legs fire in their order, view-as first; the
  control keeps its role and its full label with `aria-disabled="true"`, never the `disabled`
  attribute; its reason node is in the DOM at mount; a press sends nothing, re-shows the reason
  once, politely, and emits no audit or analytics (E09-D09:228, :243; `15`:819).
@ prose
  **The exits test** (spec §4.2): in every account state of D02 §10.2 and §10.3 the Owner's
  Cancel, Close, the bulk closes and cancels and Flatten account… send; the two drawn exceptions
  are the only T2 on an exit (D02:412).
§ hand-off ‖ §F Open items
@ prose
  - **Q-5** `sl.note`'s first sentence as the native-stop row's Cancel reason (D02:345).
@ prose
  - **Q-7** CMP-129's open-positions reason: a key and its string, asked of E30-D02's owner (RULED
  BQ-8); until it is registered the toggle's T2 frames show `rbac.view_as` and `rbac.owner_only`
  only (spec §4.1), and no E29 surface hosts the toggle (D02:622).
@ prose
  - **Q-9** A Manager's closes under the kill switch read E39-D01's "Frozen — the owner closes or
  releases" until OD-11 rules (E39-D01:687; D02:654).
@ prose
  - **Q-10** CSV export for a Viewer (OQ-G, D02:656), and SR-098's identity watermark and audit
  record, which need G7's server path (D03:519, :619).
@ prose
  - **Q-11** `Ctrl+Shift+F`: Flatten account in the Positions context, or E39-D03's global flatten
  (OQ-R, D02:667), stays open; CMP-123 cites it and decides nothing (spec §2.4).
@ prose
  - **Q-12** CMP-123's Table A rows compose with E33-D04 A-6 (PENDING, by name): whichever lands
  first applies the shared Tokens row, and the other is then a no-op.
@ prose
  - **Q-16** The assertive NO SL, Critical-crossing and amend-rejected announcements are proposed
  for E29-D05 (D02:465); the entries' live-region lines follow D02 until its review rules.
@ prose
  - **Q-17** The typed word that Flatten account… asks on LIVE is named in no merged text: D02:353
  names none, D02:349 routes the bulk words to D03's deck, which has none, and CMP-044 offers
  fixed words for a scope without a name (`15`:476); spec §2.4 draws the field with its copy open.
"""


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
