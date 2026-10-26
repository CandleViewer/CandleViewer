#!/usr/bin/env python3
"""E29-D04 (#823) audit: the blotter design-system contributions and the motion spec.

Standalone, offline, stdlib only. It reads AS TEXT at the pinned base `6fc8aacc6` (`git show`):
the plan texts `05`, `14`, `15`, `16`, the merged E29-D01 / E29-D02 / E29-D03 texts, E09-D09,
E30-D02, `theme.css`, `tools/contrast/pairs.mjs`, the CVD port's source
`docs/research/_tools/cvd_simulate.py` and the E11-D05 tool's JND floor; then this ticket's spec
and hand-off and the working-tree `15` and `16`, which must equal the base. It executes no repo
code (RULED BQ-1): the WCAG ratio of `docs/design/_tools/contrast_check.py` and the theme
layering, `over()` and CIELAB ΔE of `packages/ui/tokens/tests/verify_tokens.py` are ported and
read only as text (G-CONTRAST-PORT re-reads their numbers and the layering at the base), as the
CVD projection of `cvd_simulate.py` is (G-CVD-PORT). The branch may change the spec, the
hand-off, this tool and the ticket's board PNGs, nothing else (G-UNTOUCHED).

1. **Values.** Every token, motion, distance, contrast and count figure is COMPUTED and printed
   by `--json` (`values`): durations and easings from the primitives; the flash, loop, polite,
   linger, hold, skeleton, size and row-count constants parsed from their cited lines
   (CITED_VALUES); contrast per theme (dark, light, high contrast) through the ported helpers;
   CVD as CIE76 ΔE after the Brettel / Viénot projection of `cvd_simulate.py` (ported verbatim;
   G-CVD-PORT re-reads its constants) and the greyscale CIELAB L* gap; the counts from the spec's
   own tables. A figure in the spec is written `VALUE <!-- audit:NAME=VALUE -->`; `--check`
   re-derives every marker and the number in front of it, and FAILs on a figure with a unit
   outside a marker (typed, spelled, in a code span or in a quote no cite verifies), a one- or
   two-decimal number, a bare count beside what it counts, a Δ value, an HTML comment that is no
   marker (it hides text from every gate) and an unfilled `{{audit:NAME}}`; `--fill` writes the
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
   spaces, lower case; quoted copy removed whole where a gate reads claims). WHOLE-UNIT reading:
   a table row is one sentence across all its cells, a sentence runs across `;`, `—` and
   parentheses and ends at a full stop (a bold run included), and a sentence or a clause that
   opens on a pronoun or a conjunction, or follows its subject's colon, reads that subject in its
   place. A negation covers only its own fragment (it stops at `;`, `—`, a parenthesis, a colon, a
   cell, and a comma or a conjunction that opens a new clause); a negation chain ("never fails
   to", "never … without") asserts its term; a name that holds a negation word ("NO SL", "Not
   available", "sees no") is never one. A gate pairs a subject with a claim within a few words or
   inside one clause; the structured tables (the motion table, the state tables of §2, §4.1's
   legs, the `16` block) are read by column, frame by frame. The structured cells are read
   closed-world: a motion row's Property, Duration and Easing are a shipped token with its marker,
   `none` or `by reference` (only the owners' recipes Mo-5, Mo-7, Mo-11 and Mo-13), only Mo-1, 2,
   3, 4, 6 and 9 animate, a frame's Motion names one motion row or none, only the listed frames
   name an animated row, a T2 frame carries the leg its id names, and an exit is known by its
   control's name; every table of a section is read, and a second motion or frame table or a
   repeated id fails. The prose of a motion section is swept like the rest. Vocabulary lists are
   case-insensitive, camelCase split. G-SAFETY reads the security invariants (no withdrawal, no
   key shown, no action without its audit, no write under view-as) so they hold after a careless
   re-pin. A section whose body still holds a `> **To write (` line is skipped by its gates and
   fails G-PLACEHOLDER alone.
4. **Pins (default-deny).** A heading, table cell, prose sentence or fenced line that names
   view-as, a fixture account (Main, Sub-n), an environment or its word or token (LIVE / DEMO,
   `env`, `color.env.*`), a role (Owner, Manager, Viewer), a permission, a scope, T2 and its
   keys (`rbac.*`, `recon.*`, `blotter.*`, …), flatten or a bulk exit, the kill switch or a
   freeze, a native stop or NO SL, liquidation, reduce-only, read-only, `aria-disabled`, audit, a
   fixture money value, or keys and their kin is security-bearing, and so is every clause of
   §2.4, §2.5, §4 and §6 and every T2 cell, whatever it names; each must equal,
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
import io
import json
import math
import re
import subprocess
import sys
import textwrap
import tokenize
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "6fc8aacc6"  # every cite was read here (the spec's Inputs line)
HEAD = "origin/main"  # drift is reported against this ref (WARN, never FAIL)
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E29/E29-D04.md"
HAND_REL = "docs/design/E29/E29-D04-handoff.md"
TOOL_REL = "docs/design/_tools/e29_d04_ds_motion_audit.py"
# the only paths the branch may change (G-UNTOUCHED): the three files and the ticket's PNGs
ALLOWED_REL = (SPEC_REL, HAND_REL, TOOL_REL)
ALLOWED_PREFIX = "docs/design/E29/img/E29-D04-"
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
    "c99ad48d7": ("#4073", "docs/design/E09/E09-D08.md"),
    "16661c7bd": ("#3957", "docs/design/E11/E11-D06.md"),
    "da7b0f8a9": ("#3905", "docs/design/E17/E17-D01.md"),
    "c31b67c22": ("#4102", "docs/design/E17/E17-D01.md"),
    "f798a64e6": ("#3923", "docs/design/E30/E30-D02.md"),
    "88839ea33": ("#4375", "docs/design/E33/E33-D03.md"),
    "05aa6fba1": ("#4402", "docs/design/E33/img/"),
    "1e6c15a1a": ("#3920", "docs/design/E39/E39-D01.md"),
    "e0bf7db3e": ("#3926", "docs/design/E42/E42-D02.md"),
    "9b5c0d8bf": ("#4193", "docs/design/E42/E42-D04.md"),
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
    "c99ad48d7": "e09 d08",
    "16661c7bd": "e11 d06",
    "da7b0f8a9": "e17 d01",
    "c31b67c22": "e17 d01",
    "f798a64e6": "e30 d02",
    "88839ea33": "e33 d03",
    "05aa6fba1": "e33 d03",
    "1e6c15a1a": "e39 d01",
    "e0bf7db3e": "e42 d02",
    "9b5c0d8bf": "e42 d04",
}
DOC_IDS = (
    r"\b(e29 d01|e29 d02|e29 d03|e30 d04|e30 d02|e09 d09|e09 d08|e39 d03|e39 d01|e05 d02|e11 d06"
    r"|e17 d01|e33 d03|e42 d02|e42 d04|d01|d02|d03)\b"
)
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
    "cited.15.virtualized-rows": ("15", 527, r"default true above (\d+) rows"),
    "cited.d01.virtualise-rows": ("D01", 284, r"Virtualise at ≥(\d+ \d{3}) rows"),
    "cited.d02.fixture-rows": ("D02", 142, r"on a (\d+)-row fixture"),
    "cited.d03.fixture-fills": ("D03", 72, r"a ([\d,]+)-fill fixture"),
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


@functools.lru_cache(maxsize=8192)
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


def rows_with(block: str, *words: str) -> list[dict[str, str]]:
    """The rows of EVERY table of `block` whose header holds every word of `words`
    (case-insensitive), in document order, as dicts keyed by the header cells."""
    out: list[dict[str, str]] = []
    for head, body in tables(block):
        joined = " | ".join(head).lower()
        if all(w.lower() in joined for w in words):
            out += [dict(zip(head, r, strict=False)) for r in body]
    return out


def doc_tables(text: str) -> list[tuple[str, list[str], int]]:
    """Every table of `text` outside a fence: (its section heading, its header cells, its number
    of body rows); the heading is the nearest one above it outside a fence ("" before any)."""
    out: list[tuple[str, list[str], int]] = []
    lines = text.split("\n")
    fence = fenced(lines)
    heading = ""
    i = 0
    while i < len(lines):
        m = HEADING.match(lines[i])
        if m and not fence[i]:
            heading = m[2]
        if (
            not fence[i]
            and re.match(r"^\s*\|", lines[i])
            and i + 1 < len(lines)
            and is_rule(lines[i + 1])
        ):
            j = i + 2
            while j < len(lines) and re.match(r"^\s*\|", lines[j]):
                j += 1
            out.append((heading, split_row(lines[i]), j - i - 2))
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


@functools.lru_cache(maxsize=262144)
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
HARD = re.compile(r";\s*|\s+[—–]\s+|[()\[\]]|:\s+|\s\|\s|(?:(?<=[^\s!][.!?])|(?<=[.!?]\*\*))\s+")
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
# "never … without X" / "no … without X" asserts X (and what stands between): both words go
NEG_WITHOUT = re.compile(r"\b(never|not|no|nothing|none)\b((?:\W+\w+){0,6}?\W+)without\b")
NEG_REACH = 8  # words a negation covers inside its fragment


def unnegate(t: str) -> str:
    """`t` with each "never … without" pair blanked, keeping its length and the words between."""
    return NEG_WITHOUT.sub(lambda m: " " * len(m[1]) + m[2] + " " * len("without"), t)


# phrases whose negation word is part of a name or of the asserted claim, never a negation
PROTECT: tuple[tuple[str, str], ...] = (
    (r"\bno sl\b", "no_sl"),
    (r"\bnot shown\b", "not_shown"),
    (r"\bnot offered\b", "not_offered"),
    (r"\bnot available\b", "not_available"),
    (r"\bnot rendered\b", "not_rendered"),
    (r"\bnot displayed\b", "not_displayed"),
    (r"\bnot visible\b", "not_visible"),
    (r"\b(sees?|gets?) no\b", r"\1_no"),
    (r"\b(?:does not|doesn't|do not|don't|cannot|can't) see\b", "not_see"),
    (r"\bno (\w+) (button|control|item)\b", r"no_\1_\2"),
)


def protect(t: str) -> str:
    for pattern, name in PROTECT:
        t = re.sub(pattern, name, t)
    return t


SENTENCE_END = re.compile(r"(?:(?<=[.!?])|(?<=[.!?]\*\*))\s+(?=[A-Z0-9`\"“*(])")
PRONOUN = re.compile(
    r"^(?:it|its|they|their|them|this|these|that|those|which|both|each|either|neither|such|"
    r"then|also|so|and|or|but|while|whose|here|there)\b"
)


@functools.lru_cache(maxsize=131072)
def fragments(raw: str) -> tuple[str, ...]:
    return tuple(f for f in HARD.split(raw) if f.strip())


@functools.lru_cache(maxsize=524288)
def _asserts(raw_fragment: str, term: str, keep_quotes: bool) -> bool:
    t = norm_text(raw_fragment if keep_quotes else unquote(raw_fragment))
    t = protect(DOUBLE_NEG.sub(" ", unnegate(t)))
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
    asserts its term. A quote is dropped whole first, so a dash inside it splits nothing."""
    src = raw if keep_quotes else unquote(raw)
    return any(_asserts(f, term, keep_quotes) for f in fragments(src))


@functools.lru_cache(maxsize=256)
def units(text: str) -> tuple[str, ...]:
    """Every unit a gate reads: each table row (its cells joined by " | "), each bullet, each
    prose paragraph and each heading; fenced copy-ready lines are read like the rest; HTML
    comments and placeholder lines are dropped."""
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(" ".join(para))
            para.clear()

    lines = visible(text).split("\n")
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("```"):
            flush()
        elif re.match(r"^\s*\|", ln):
            flush()
            header = i + 1 < len(lines) and is_rule(lines[i + 1])
            if not is_rule(ln) and not header:  # a header row names columns, it claims nothing
                out.append(" | ".join(split_row(s)))
        elif re.match(r"^\s*(?:[-*+]|\d+\.) ", ln) or s.startswith("#"):
            flush()
            out.append(s)
        elif s:
            para.append(s)
        else:
            flush()
    flush()
    return tuple(out)


@functools.lru_cache(maxsize=131072)
def sentences(unit: str) -> tuple[str, ...]:
    """A table row is one sentence across all its cells; prose splits at a sentence end only
    (never at a semicolon, a dash or a parenthesis)."""
    if " | " in unit:
        return (unit,)
    return tuple(s for s in SENTENCE_END.split(unit) if s.strip())


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


@functools.lru_cache(maxsize=262144)
def blanked(raw: str, keep_quotes: bool = False) -> str:
    """The sentence normalised, each fragment's negated words blanked, fragments joined by " ¦ "
    (so a term and its subject may sit in different fragments of one sentence)."""
    parts: list[str] = []
    for f in fragments(raw if keep_quotes else unquote(raw)):
        t = protect(DOUBLE_NEG.sub(" ", unnegate(norm_text(f if keep_quotes else unquote(f)))))
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
                m = re.search(a, blanked(s, keep_quotes))  # a negated mention is no subject
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


def clause_claims(
    texts: list[str],
    a: str,
    b: str,
    keep_quotes: bool = False,
    unless: str = "",
    prep: Callable[[str], str] | None = None,
) -> list[str]:
    """Every clause (a fragment of a sentence: a row's cell, a part between `;`, `—`, a colon or
    parentheses) where `a` and `b` are both asserted; a clause or a sentence that opens on a
    pronoun or a conjunction reads the last subject (the phrase that matched `a`) in its place."""
    hits: list[str] = []
    for text in texts:
        for u in units(text):
            subject = ""
            for s in sentences(u):
                raw = prep(s) if prep else s
                carry = False
                for frag in blanked(raw, keep_quotes).split(" ¦ "):
                    m = re.search(a, frag)
                    led = False
                    if m:
                        subject = m[0]
                    elif subject and (carry or PRONOUN.match(frag)):
                        frag, led = subject + " " + frag, True
                    # "`display`: the word as text, …": a subject alone before a colon leads in
                    carry = (
                        m is not None
                        and len(frag.split()) <= 3
                        and re.search(re.escape(m[0]) + r"\W{0,3}:", norm_text(raw)) is not None
                    )
                    if unless and re.search(unless, frag):
                        continue
                    if (led or re.search(a, frag)) and re.search(b, frag):
                        hits.append(frag[:72])
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
# Ported, never executed (RULED BQ-1: the tool executes no repo code). The WCAG ratio of
# `contrast_check.py` (`_linearize`, `relative_luminance`, `contrast_ratio`) and, from
# `verify_tokens.py`, the theme layering (`THEMES` over `merged_set`, `resolve`), `hex_to_rgb`,
# `over`, `rgb_to_lab` and `delta_e76` keep their numbers here as named constants, in the order
# their source writes them; G-CONTRAST-PORT re-reads those functions at the base and fails when a
# number, its order or the layering differs. The token JSON and `themes.json` are read at the base.

WCAG_KNEE = 0.03928
WCAG_SLOPE = 12.92
WCAG_OFFSET = 0.055
WCAG_SCALE = 1.055
WCAG_GAMMA = 2.4
WCAG_LUMA = (0.2126, 0.7152, 0.0722)
WCAG_FLARE = 0.05
HEX_LEN = 6
HEX_SLICES = ((0, 2), (2, 4), (4, 6))
HEX_RADIX = 16
LAB_KNEE = 0.04045
LAB_RGB_TO_XYZ = ((0.4124, 0.3576, 0.1805), (0.2126, 0.7152, 0.0722), (0.0193, 0.1192, 0.9505))
LAB_WHITE = (0.95047, 1.0, 1.08883)
LAB_EPSILON = 0.008856
LAB_KAPPA = 7.787
LAB_SCALE = (116, 16, 500, 200)
OVER_ROUND = 0.5


def _wcag_linearize(channel: int) -> float:
    c = channel / 255
    return c / WCAG_SLOPE if c <= WCAG_KNEE else ((c + WCAG_OFFSET) / WCAG_SCALE) ** WCAG_GAMMA


def wcag_luminance(rgb3: tuple[int, int, int]) -> float:
    r, g, b = rgb3
    kr, kg, kb = WCAG_LUMA
    return kr * _wcag_linearize(r) + kg * _wcag_linearize(g) + kb * _wcag_linearize(b)


def wcag_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = wcag_luminance(a), wcag_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + WCAG_FLARE) / (darker + WCAG_FLARE)


def rgb(hex6: str) -> tuple[int, int, int]:
    """`verify_tokens.hex_to_rgb`: the first six hex digits as (r, g, b)."""
    h = hex6.lstrip("#")[:HEX_LEN]
    (a0, a1), (b0, b1), (c0, c1) = HEX_SLICES
    return int(h[a0:a1], HEX_RADIX), int(h[b0:b1], HEX_RADIX), int(h[c0:c1], HEX_RADIX)


def rgb_to_lab(rgb3: tuple[int, int, int]) -> tuple[float, float, float]:
    def chan(c: int) -> float:
        v = c / 255.0
        return ((v + WCAG_OFFSET) / WCAG_SCALE) ** WCAG_GAMMA if v > LAB_KNEE else v / WCAG_SLOPE

    r, g, b = (chan(c) for c in rgb3)
    (xr, xg, xb), (yr, yg, yb), (zr, zg, zb) = LAB_RGB_TO_XYZ
    x = (r * xr + g * xg + b * xb) / LAB_WHITE[0]
    y = (r * yr + g * yg + b * yb) / LAB_WHITE[1]
    z = (r * zr + g * zg + b * zb) / LAB_WHITE[2]

    def f(t: float) -> float:
        return t ** (1 / 3) if t > LAB_EPSILON else (LAB_KAPPA * t) + (16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    k116, k16, k500, k200 = LAB_SCALE
    return (k116 * fy) - k16, k500 * (fx - fy), k200 * (fy - fz)


def delta_e(a: str, b: str) -> float:
    """`verify_tokens.delta_e76`: CIE76 ΔE between two hex colours."""
    la, aa, ba = rgb_to_lab(rgb(a))
    lb, ab, bb = rgb_to_lab(rgb(b))
    return math.sqrt((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2)


def over(fg: str, bg: str, alpha: float) -> str:
    """`verify_tokens.over`: `fg` at `alpha` over opaque `bg`, per channel, rounded half up."""
    mix = [
        math.floor(alpha * f + (1 - alpha) * b + OVER_ROUND)
        for f, b in zip(rgb(fg), rgb(bg), strict=True)
    ]
    return "#" + "".join(f"{c:02X}" for c in mix)


def resolve(value: object, entries: dict[str, dict[str, object]], seen: frozenset[str]) -> object:
    """`verify_tokens.resolve`: a DTCG `{token.path}` reference, resolved recursively."""
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        ref = value[1:-1]
        if ref in seen:
            raise SystemExit(f"FAIL parse: circular reference {ref}")
        if ref not in entries:
            raise SystemExit(f"FAIL parse: unset variable {ref}")
        return resolve(entries[ref]["$value"], entries, seen | {ref})
    if isinstance(value, dict):
        return {k: resolve(v, entries, seen) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, entries, seen) for v in value]
    return value


@functools.lru_cache(maxsize=8)
def ds_set_file(name: str) -> dict[str, dict[str, object]]:
    """One token set at the base: name → its entry."""
    data = json.loads(at_base(f"{DS_DIR_REL}/{name}.tokens.json"))
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


@functools.lru_cache(maxsize=8)
def ds_file(name: str) -> dict[str, object]:
    """One token file at the base: name → its raw `$value`."""
    return {k: v.get("$value") for k, v in ds_set_file(name).items()}


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


@functools.lru_cache(maxsize=1)
def theme_sets() -> dict[str, tuple[str, ...]]:
    """`themes.json` at the base: each theme's token sets in layering order."""
    data = json.loads(at_base(f"{DS_DIR_REL}/themes.json"))
    return {str(t["name"]): tuple(str(s) for s in t["sets"]) for t in data["themes"]}


@functools.lru_cache(maxsize=4)
def theme_colours(theme: str) -> dict[str, str]:
    """Every colour name → its resolved hex in `theme`: the sets layered in `themes.json`'s order,
    a later set overriding an earlier one (`verify_tokens.merged_set`)."""
    layered: dict[str, dict[str, object]] = {}
    for s in theme_sets()[theme]:
        layered.update(ds_set_file(s))
    out: dict[str, str] = {}
    for name, entry in layered.items():
        if entry.get("$type") == "color":
            out[name] = str(resolve(entry["$value"], layered, frozenset()))
    return out


def hex_of(theme: str, name: str) -> str:
    value = theme_colours(theme).get(name, "MISSING")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?", value):
        raise SystemExit(f"FAIL parse: {name} does not resolve to a colour in {theme} ({value})")
    if len(value) == 9:  # an alpha colour, painted over the raised surface of the same theme
        alpha = int(value[7:9], 16) / 255
        return over(value[:7], hex_of(theme, "color.surface.raised"), alpha).upper()
    return value.upper()


def paint(theme: str, spec: str, peak: float) -> str:
    """A background: a colour name, or "X over Y" (X at the flash peak over Y)."""
    if " over " in spec:
        top, under = spec.split(" over ", 1)
        return over(hex_of(theme, top), hex_of(theme, under), peak).upper()
    return hex_of(theme, spec)


def ratio(theme: str, fg: str, bg: str, peak: float) -> float:
    return wcag_ratio(rgb(hex_of(theme, fg)), rgb(paint(theme, bg, peak)))


def lightness(hex6: str) -> float:
    return rgb_to_lab(rgb(hex6))[0]


# each ported function: (helper, function, the numbers its source writes, in order)
PORTED: tuple[tuple[str, str, Callable[[], tuple[float, ...]]], ...] = (
    (
        RATIO_REL,
        "_linearize",
        lambda: (255, WCAG_SLOPE, WCAG_KNEE, WCAG_OFFSET, WCAG_SCALE, WCAG_GAMMA),
    ),
    (RATIO_REL, "relative_luminance", lambda: WCAG_LUMA),
    (RATIO_REL, "contrast_ratio", lambda: (WCAG_FLARE, WCAG_FLARE)),
    (
        LOADER_REL,
        "hex_to_rgb",
        lambda: (HEX_LEN, *(x for s in HEX_SLICES for x in (*s, HEX_RADIX))),
    ),
    (
        LOADER_REL,
        "rgb_to_lab",
        lambda: (
            255.0,
            WCAG_OFFSET,
            WCAG_SCALE,
            WCAG_GAMMA,
            LAB_KNEE,
            WCAG_SLOPE,
            *(x for i in range(3) for x in (*LAB_RGB_TO_XYZ[i], LAB_WHITE[i])),
            1,
            3,
            LAB_EPSILON,
            LAB_KAPPA,
            16,
            116,
            *LAB_SCALE,
        ),
    ),
    (LOADER_REL, "delta_e76", lambda: (2, 2, 2)),
    (LOADER_REL, "over", lambda: (1, OVER_ROUND)),
)


def source_numbers(src: str, func: str) -> list[float] | None:
    """The numeric literals of `def func` in `src`, in order (tokenized, so strings and comments
    never count); None when the function is not there."""
    m = re.search(rf"^def {re.escape(func)}\(.*?(?=^\S|\Z)", src, re.MULTILINE | re.DOTALL)
    if m is None:
        return None
    toks = tokenize.generate_tokens(io.StringIO(m[0]).readline)
    return [float(t.string) for t in toks if t.type == tokenize.NUMBER]


def helper_layering() -> dict[str, tuple[str, ...]]:
    """`verify_tokens.THEMES` at the base, each theme's sets with `PRIMITIVES` first."""
    src = at_base(LOADER_REL)
    prim = grab(r'^PRIMITIVES = "([^"]+)"', src, "verify_tokens.PRIMITIVES")
    block = grab(r"^THEMES = \{(.*?)^\}", src, "verify_tokens.THEMES", MULTI | re.DOTALL)
    out: dict[str, tuple[str, ...]] = {}
    for name, files in re.findall(r'"([a-z-]+)": \[([^\]]*)\]', block):
        sets = [prim, *re.findall(r'"([^"]+)"', files)]
        out[name] = tuple(s.removesuffix(".tokens.json") for s in sets)
    return out


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


# ---------------------------------------------------------------------------- the spec's tables

MO_ID = r"Mo-\d+"


def boards(spec: str) -> list[dict[str, str]]:
    rows = table_with(section(spec, "0. Planned boards"), "#", "Board")
    return [r for r in rows if re.fullmatch(r"\d\d", col(r, "#").strip())]


def is_light(board: dict[str, str]) -> bool:
    return re.search(r"-light`?$", col(board, "Board").strip()) is not None


def mo_list(spec: str) -> list[tuple[str, dict[str, str]]]:
    """Every row of every motion table of §3.2, in order, keyed by its Mo id (a repeated id is
    kept, so a later copy never shadows an earlier one)."""
    rows = rows_with(section(spec, "3.2 The motion table"), "Mo", "Property")
    return [(row_key(col(r, "Mo")), r) for r in rows]


def mo_rows(spec: str) -> dict[str, dict[str, str]]:
    """The motion rows by id (for lookups; the gates read `mo_list`)."""
    return dict(mo_list(spec))


def state_rows(spec: str, head: str) -> list[dict[str, str]]:
    return rows_with(section(spec, head), "Frame", "State", "Word")


MO_HEAD = ("Mo", "Property")
FRAME_HEAD = ("Frame", "State", "Word")


def table_places(spec: str, words: tuple[str, ...]) -> list[str]:
    """The section heading of every table of the spec whose header holds `words`."""
    return [
        h
        for h, head, _n in doc_tables(spec)
        if all(w.lower() in " | ".join(head).lower() for w in words)
    ]


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
    return rows_with(section(spec, "4.1 The gated controls"), "Control", "Legs")


def contrast_rows(spec: str) -> list[dict[str, str]]:
    return table_with(section(spec, "5. Tokens and contrast"), "Pair", "fg", "bg")


def proposed_names(spec: str) -> set[str]:
    rows = table_with(section(spec, "5. Tokens and contrast"), "Name", "Owner")
    return {n.lower() for r in rows for n in re.findall(r"`([^`]+)`", col(r, "Name"))}


def copy_rows(spec: str) -> list[dict[str, str]]:
    return rows_with(section(spec, "6. Copy keys"), "Key", "String", "Status")


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
    return rows_with(section(hand, "C.6 The `16` block"), "Surface", "Enter")


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
    out["ds.size.target.min"] = str(prim["size.target.min"])
    for name, (cid, n, pattern) in CITED_VALUES.items():
        out[name] = re.sub(r"[,\s]", "", grab(pattern, base_line(cid, n), f"{cid}:{n} {name}"))
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
    mos = dict(mo_list(spec))
    drs = drift_rows(spec)
    verdicts = [norm_text(col(d, "Verdict")) for d in drs.values()]
    unresolved = [k for k, d in drs.items() if drift_problems(k, d)]
    return {
        "count.boards": str(len(bd)),
        "count.boards-light": str(len([b for b in bd if is_light(b)])),
        "count.boards-dark": str(len([b for b in bd if not is_light(b)])),
        "count.motion-rows": str(len(mo_list(spec))),
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
        "count.pairs-measured": str(len(MEASURED_ONLY)),
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
    r"(?<![\w.,:#/>{-])(\d+(?:[.,]\d+)*)\s?-?\s?(ms|s|hz|px|%|:1|milliseconds?|seconds?|pixels?"
    r"|hertz|percent|mins?|minutes?|h|hrs?|hours?)(?![\w])",
    re.IGNORECASE,
)
# a spelled figure with a unit ("eight seconds", "half a second", "four hundred milliseconds")
SPELLED_FIGURE = re.compile(
    r"\b(?:(?:one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|thirty|forty"
    r"|fifty|sixty|hundred|thousand|half|tenth|quarter)[\s-]+(?:and[\s-]+|of[\s-]+|a[\s-]+)*)+"
    r"(?:milliseconds?|seconds|minutes|hours|pixels?|hertz)\b|\b(?:half|tenth|quarter)[\s-]+(?:of[\s-]+)?a[\s-]+second\b",
    re.IGNORECASE,
)
TWO_DP = re.compile(r"(?<![\w.,:#/-])\d+\.\d{1,2}(?!\d|\.\d)")
# a bare count beside what it counts or a measure word beside its number
BARE_COUNT = re.compile(
    r"(?<![\w.,:#/>{-])\d[\d,]*(?:\.\d+)?\s+(?:cells?|rows?|starts?|times (?:a|per) second"
    r"|per second|fps)\b|\b(?:peak|bar|ratio|opacity|floor)\s+(?:of\s+)?\d+(?:\.\d+)?(?![\w.])",
    re.IGNORECASE,
)
TIME_UNIT = re.compile(
    r"\d+(?:[.,]\d+)*\s?-?\s?(?:ms|milliseconds?|seconds?|s|mins?|minutes?|h|hrs?|hours?)\b",
    re.IGNORECASE,
)
# a quoted fragment G-CITE verifies: right after a `file`:line cite
CITED_QUOTE = re.compile(r':\d+(?:[–-]\d+)?(?:, :\d+(?:[–-]\d+)?)* "[^"\n]+"')
DELTA = re.compile(r"Δ[EL]\*?(?:76)?\s+(?:of\s+)?(?:about |around |roughly |some |nearly |~)?\d")
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
        # a quote holds copy, never a measurement, but a time in a quote no cite verifies does
        loose = [q for q in QUOTED.findall(CITED_QUOTE.sub(" ", work)) if TIME_UNIT.search(q)]
        spans = [c[0] for c in CODE.finditer(work) if FIGURE.search(c[0])]
        work = QUOTED.sub(" ", CODE.sub(" ", work))
        work = re.sub(r"#\d+|(?:`[^`\n]+`|\b[A-Za-z][A-Za-z0-9./-]*):\d+(?:[–-]\d+)?", " ", work)
        work = re.sub(r"§\s?\d+(?:\.\d+)*|^#+\s+\d+(?:\.\d+)*", " ", work)  # section numbers
        found = [m[0] for m in FIGURE.finditer(work)] + TWO_DP.findall(work)
        found += [m[0] for m in DELTA.finditer(work)] + [
            m[0] for m in SPELLED_FIGURE.finditer(work)
        ]
        found += [m[0] for m in BARE_COUNT.finditer(work)] + loose + spans
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
        for m in re.finditer(r"<!--(.*?)-->", line):
            if not MARKER.fullmatch(m[0]):
                bad.append(
                    f"{name}:{i} a comment that is no audit marker hides text from every gate"
                )
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


@functools.lru_cache(maxsize=256)
def split_lines_cached(text: str) -> tuple[str, ...]:
    return tuple(text.split("\n"))


def split_lines(text: str | None) -> list[str] | None:
    return None if text is None else list(split_lines_cached(text))


def cite_problems(texts: dict[str, str], fetch: Fetch) -> tuple[list[str], list[str], int]:
    fails: list[str] = []
    warns: list[str] = []
    done: set[tuple[str, int]] = set()

    def lines_of(rev: str, rel: str) -> list[str] | None:
        return split_lines(fetch(rev, rel))

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
    their mutations) and the hand-off without Table A's Old cells (`15` verbatim, G-CITE's)."""
    spec = t.spec.replace(section(t.spec, "8.2 The gate tool"), "")
    return [drop_column(spec, "old"), drop_column(t.hand, "old")]


def without(text: str, *heads: str) -> str:
    """The text with the table rows of the sections `heads` dropped (their cells are read cell by
    cell by the row checks); every prose line of those sections stays in the sweep."""
    for h in heads:
        block = section(text, h)
        if block:
            lines = block.split("\n")
            rows: set[int] = set()
            for i in range(len(lines) - 1):
                if re.match(r"^\s*\|", lines[i]) and is_rule(lines[i + 1]) and i not in rows:
                    j = i
                    while j < len(lines) and re.match(r"^\s*\|", lines[j]):
                        rows.add(j)
                        j += 1
            kept = [ln for i, ln in enumerate(lines) if i not in rows]  # a stray row stays swept
            text = text.replace(block, "\n".join(kept), 1)
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


# `16` §11.4's thirteen checklist lines (`16`:483 onwards), in order, as hand-off §B holds them
CHECKLIST_LINES = (
    "Final Penpot link", "Variants × States", "Keyboard table", "Accessible name and role",
    "Live data", "Motion pair", "Density notes", "Essential exceptions", "Tokens used",
    "Data contract confirmed", "Contrast and CVD",
    "Design QA (`16` §12) and a11y AC (`05` §10)", "Sign-off",
)  # fmt: skip
CHECK_BOX = ("[x]", "[ ]", "N/A")


def checklist_problems(t: Texts) -> list[str]:
    """Hand-off §B: the thirteen lines present in order, every box `[x]`, `[ ]` or N/A; Sign-off
    open on every entry with the owner mark (an approval only the owner gives); the Penpot line
    open while §0's boards are PENDING."""
    block = section(t.hand, "§B ")
    if not block:
        return []  # a missing §B is G-HANDOFF's
    rows = table_with(block, "`16` §11.4 line", "Evidence")
    lines = [col(r, "`16` §11.4 line") for r in rows]
    if lines != list(CHECKLIST_LINES):
        return ["hand-off §B does not hold `16` §11.4's thirteen lines in order"]
    bad: list[str] = []
    for r in rows:
        line = col(r, "`16` §11.4 line")
        boxes = [v.strip() for c, v in r.items() if c.startswith("CMP-")]
        if len(boxes) != 7 or any(not b.startswith(CHECK_BOX) for b in boxes):
            bad.append(f"§B {line!r}: a box that is not [x], [ ] or N/A")
        if line == "Sign-off" and (set(boxes) != {"[ ]"} or OWNER_MARK not in col(r, "Evidence")):
            bad.append("§B Sign-off is ticked or lacks the owner mark")
        pending_boards = any("PENDING" in col(b, "Status") for b in boards(t.spec))
        if line == "Final Penpot link" and pending_boards and set(boxes) != {"[ ]"}:
            bad.append("§B Final Penpot link is ticked while §0's boards are PENDING")
    return bad


def g_owner(t: Texts) -> list[str]:
    """BQ-2 / BQ-10 / BQ-11 / BQ-12 are owner-level: marked wherever they depart; hand-off §B
    never ticks the owner's sign-off (`16` §11.4)."""
    rows = table_with(section(t.spec, "The sixteen questions"), "#", "Question")
    bq = {row_key(col(r, "#")): " | ".join(r.values()) for r in rows}
    bad = [f"{k} lacks the owner mark" for k in OWNER_BQS if OWNER_MARK not in bq.get(k, "")]
    for prefix in ("### 3.3 ", "### 7.4 "):
        heading = next((ln for ln in t.spec.split("\n") if ln.startswith(prefix)), "")
        if OWNER_MARK not in heading:
            bad.append(f"the {prefix.strip('# ')} heading lacks the owner mark")
    bad += checklist_problems(t)
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
    """RULED BQ-2 and the binding conditions: `15` and `16` byte-identical to the base (a
    missing file is a change), the measured inputs (token JSON, the helpers read as text) too;
    and the branch, committed or not, tracked or not, changes nothing but the spec, the hand-off,
    this tool and the ticket's board PNGs (`14`, `05`, the merged specs and every plan text
    stay as they are)."""
    bad: list[str] = []
    if t.p15 != at_base(P15_REL):
        bad.append("`15` is missing or differs from the base")
    if t.p16 != at_base(P16_REL):
        bad.append("`16` is missing or differs from the base")
    bad += [f"{rel} differs from the base" for rel, text in t.inputs if text != at_base(rel)]
    bad += [
        f"{n} changed on the branch"
        for n in t.diff_names
        if n not in ALLOWED_REL and not n.startswith(ALLOWED_PREFIX)
    ]
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


def mutation_key(mid: str) -> tuple[int, ...]:
    """`M1.10` → (1, 10): ids in their natural order."""
    return tuple(int(x) for x in re.findall(r"\d+", mid))


def mutation_groups() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for mu in MUTATIONS:
        groups.setdefault(mu.gate, []).append(mu.mid)
    return {g: sorted(ids, key=mutation_key) for g, ids in groups.items()}


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
    r"|\banimat\w*|\bdrift(?:s|ed|ing)?\b(?! ledger| rows?\b)|\binterpolat\w*|\bbounc\w*|\bzoom\w*"
    r"|\bdissolv\w*|\bblend\w*"
    r"|\bmorph\w*|\bwip(?:e|es|ed|ing) (?:in|down|out)\b|\broll(?:s|ed|ing)? (?:in|down|out)\b"
    r"|\bgrow(?:s|n|ing)?\b|\bshrink\w*|\bpops? in\b|\bspin\w*|\brotat\w*|\baccordion\w*"
    r"|\bunfold\w*|\bwobbl\w*|\bjiggl\w*|\bshak(?:e|es|ing)\b"
)
TIMED = (
    r"\b(?!0 )\d[\d,]*(?:\.\d+)? ?(?:ms|milliseconds?)\b|\bmilliseconds?\b"
    r"|motion\.duration\.(?:fast|normal|slow)\b|\beas(?:e|es|ed|ing)\b|\bbezier\b|motion\.easing"
    r"|\blinear\b|\bover (?:the )?(?:motion\.duration\.)?(?:fast|normal|slow)\b"
    r"|\b(?:fast|normal|slow) / (?:standard|decelerate|accelerate)\b|\bgradual\w*|\bsmooth\w*"
)
SLOW = r"\bslow(?:er|est|ly)?\b|motion\.duration\.slow"
# motion no row of this spec has (only opacity and translateX move): denied in any sentence
OFF_VOCAB = (
    r"\bbounc\w*|\bspring(?:s|y|ing|ed)?\b|\bsprang\b|\bsprung\b|\bwobbl\w*|\bjiggl\w*"
    r"|\bshak(?:e|es|ing)\b|\bspin\w*|\brotat\w*|\bzoom\w*|\bmorph\w*|\bswoop\w*|\bwhoosh\w*"
    r"|\bwiggl\w*|\bjitter\w*|\bvibrat\w*|\bshudder\w*|\bquiver\w*|\bovershoot\w*|\belastic\w*"
    r"|\brecoil\w*|\bbob(?:s|bing|bed)?\b|\bfl(?:y|ies|ying|ew) (?:in|out|up|down|off)\b"
    r"|\bpops? (?:in|out|up)\b|\baccordion\w*|\bunfold\w*|\bflip(?:s|ped|ping)? (?:in|over)\b"
)
# a motion verb, or a span timed by a speed (a figure alone times a counter or a gap, and a
# bare `motion.duration.*` is a cap or a binding, not a motion)
MOTION_VERB = MOVE_VERBS + "|" + OFF_VOCAB
UNFIGURED_TIMED = (
    r"\b(?:over|across|during|through|within|for) (?:the |a )?(?:motion\.duration\.)?(?:fast|normal|slow)\b"
    r"|\beas(?:e|es|ed|ing)\b|\bbezier\b|\bgradual\w*|\bsmooth\w*"
)
# the rows a motion sentence may cite: the animated rows and the owners' recipes
CITABLE = r"\bMo-(?:1|2|3|4|5|6|7|9|11|13)\b"
# the three general rules that name motion without a row, and the ledger's noun (exact)
MOTION_RULES = (
    r"\bevery animation has a defined non animated equivalent\b"
    r"|\bsets every transition and animation to 0\.01 ms\b"
    r"|\bonly opacity and transform animate on a blotter row\b|\bdrift corrected by\b"
)
CITABLE_N = r"\bmo (?:1|2|3|4|5|6|7|9|11|13)\b"  # CITABLE, as norm_text writes it
# a motion name that is not a duration (`motion.easing.standard`, CMP-046's `motion.slide`)
MOTION_NAME = re.compile(r"`?motion\.(?!duration\.)[a-z]+(?:\.[a-z0-9{},*_-]+)*`?")


def numbers_claims(texts: list[str]) -> list[str]:
    """RULED BQ-11, the numbers never tween: every clause (a row: each cell) naming a figure that
    moves or is timed by a speed, whichever word is its subject ("the row animates the price"); a
    clause naming a glyph, a word or a state too is G-INSTANT's (KIND), which reads it."""
    moving = MOTION_VERB + "|" + UNFIGURED_TIMED
    hits = clause_claims(texts, NUMBERISH, moving, prep=as_names)
    return [c for c in hits if not re.search(KIND, c)]


def owned_elsewhere(s: str, cap: float) -> bool:
    """A moving sentence another gate reads by its own rule: a timing past the cap or `slow`
    (G-ROW-200), a layout or paint property or the pointer (G-COMPOSITOR), a reduced reading
    (G-REDUCE-INSTANT), a figure, a tick or a tween (G-TICK), a loop (G-LOOP) or a quoted figure
    (G-VALUE). motion_claims leaves it to that gate, so each breach reports once."""
    n = norm_text(unquote(s))
    moving = MOVE_VERBS + "|" + TIMED + r"|\btransition\w*"
    pointer = r"\bunder (?:the )?(?:pointer|cursor|mouse)\b"
    return bool(
        long_claims([s], cap)
        or adjacent(s, NON_COMPOSITOR, moving, 4)
        or live(s, LAYOUT_MOTION)
        or adjacent(s, pointer, MOVE_VERBS, 4)
        or RAW_REDUCED.search(s)
        or numbers_claims([s])
        or adjacent(s, MOTIONISH, PER_TICK, 6)
        or adjacent(s, NUMBERISH, TWEEN, 4)
        or re.search(LOOP_WORDS, n)
        or any(re.search(r"\d", q) for q in QUOTED.findall(s))
    )


def motion_claims(texts: list[str], cap: float) -> list[str]:
    """RULED BQ-9: a sentence (a row: across its cells) asserting motion cites the row it is —
    an animated row or an owner's recipe — or is one of MOTION_RULES; a sentence opening on a
    pronoun carries the previous sentence's row. Motion no row has (OFF_VOCAB) is denied in any
    sentence, cited or not. A name is no claim: `motion.easing.*` and the design-system names
    read as "a token"."""
    hits: list[str] = []
    for text in texts:
        for u in units(text):
            cited = False
            for s in sentences(u):
                n = norm_text(unquote(s))
                cited = re.search(CITABLE_N, n) is not None or (cited and bool(PRONOUN.match(n)))
                raw = as_names(s)
                frags = [re.sub(MOTION_RULES, " ", f) for f in blanked(raw).split(" ¦ ")]
                read = " ¦ ".join(frags)
                if owned_elsewhere(s, cap):
                    continue
                if re.search(OFF_VOCAB, read):
                    hits.append(f"(no row moves so) {read[:64]!r}")
                elif not cited and re.search(MOTION_VERB + "|" + UNFIGURED_TIMED, read):
                    hits.append(f"(cites no motion row) {read[:64]!r}")
    return hits


TWIN = "prefers-reduced-motion"
TWIN_NULL = (
    r"\bnone\b|\bn ?/ ?a\b|\bsame as (?:the )?(?:motion )?safe\b|\bunchanged\b|\bas above\b"
    r"|\bno (?:reduced (?:motion )?|prefers reduced motion )?(?:variant|twin|reading)\b|\btb[dc]\b"
)
TWIN_OK = (
    r"\bframe 0\b|\binstant\w*|\bstatic\b|\bno flash\b|\bno highlight\b|\bthe same cut\b"
    r"|\bat once\b|\bno motion\b|\bper cmp \d{3}\b"
)
TWIN_MISSING = (
    r"\b(?:no|without|lacks?|lacking|missing|needs? no)\s+(?:a |an |its |any )?"
    r"(?:reduced(?: motion)? |prefers reduced motion |motion reduce |non animated )?"
    r"(?:variant|twin|reading|equivalent|handling)\b"
    r"|\b(?:drops?|dropped|omits?|omitted|skips?|skipped|loses?|lost|removes?|removed)\s+"
    r"(?:its |the |a |every |each )?(?:reduced motion |non animated )?(?:twin|equivalent|variant)s?\b"
    r"|\btwins? (?:is |are )?(?:omitted|dropped|skipped|removed|missing|optional)\b"
    r"|\breduced motion (?:is |are )?(?:ignored|skipped|bypassed|not applied|off)\b"
    r"|\bexempt\w* from (?:the )?reduced motion\b"
)
CARRIER = (
    r"\bwords?\b|\bglyphs?\b|\btext\b|\bsign\b|\bmarkers?\b|\bdelta\b|\bvalues?\b|\btags?\b"
    r"|▲|▼|\blabels?\b|\bthe change\b"
)
# where a reduced reading starts in a raw sentence: what follows it must not move
RAW_REDUCED = re.compile(
    r"\bunder (?:the )?(?:reduced? motion|reduce|prefers-reduced-motion)\b|\breduced motion\b"
    r"|(?<![\w-])(?<!light )(?:its |the |a |every |each )?(?<!light )(?:reduced? |motion )?twins?\b"
    r"(?![-\w]| of the server)"
    r"|prefers-reduced-motion|data-motion=\"?reduce|\breduce mode\b|\bwhen (?:motion is )?reduced\b",
    re.IGNORECASE,
)
# what a sentence naming the reduced reading must say: it is a cut, static or at frame 0
REDUCED_SAYS = (
    r"\bframe 0\b|\binstant\w*|\bstatic\b|\bno flash\b|\bno highlight\b|\bat once\b|\bno motion\b"
    r"|\bthe same cut\b|\bone source\b|\bno transition runs\b|\bnone moves\b|\bevery twin\b"
)
# reduced readings that still move, in words no verb list holds
REDUCED_MOVES = (
    r"\bhalf strength\b|\bplays?\b|\bstill (?:dims?|fades?|moves?|animates?|runs?)\b|\bshorter\b"
    r"|\bshorten\w*|\bsofter\b|\bsubtler\b|\bdimmer\b|\bfainter\b|\bgentler\b|\bquick(?:er|ly)\b"
    r"|\bkeeps? (?:the )?(?:flash|fade|animat\w*|sweep\w*|ring)\b|\bover a moment\b|\bturns?\b"
)
NON_COMPOSITOR = (
    r"\b(?:height|width|top|left|right|bottom|margins?|padding|box shadow|shadows?|filter|blur"
    r"|clip path|border(?: width| colou?r)?|outline|font size|font weight|line height|inset"
    r"|max height|layout|reflow|flex(?: basis)?|grid template(?: rows| columns)?"
    r"|letter spacing|text decoration|background(?: colou?r| position)?)\b|\bcolou?r tweens?\b"
)
# a layout animation named by its effect rather than its property
LAYOUT_MOTION = (
    r"\baccordion\w*|\bunfold\w*|\bmake room\b|\bpush(?:es|ed)? (?:the )?(?:rows?|neighbou?rs?)\b"
    r"|\bneighbou?rs? (?:slide|move|shift|animate|glide|drift)\w*|\brows? (?:below|above) "
    r"(?:slide|move|shift|animate)\w*|\breflows? (?:smoothly|gradually|over)\b"
    r"|\b(?:fades?|slides?|moves?|glides?|animates?|drifts?) (?:in)?to (?:the |its )?(?:closed today|block"
    r"|group|section|list|other tab)\b"
)
PROPERTY_CELL = re.compile(
    r"^(?:opacity(?: \(an overlay above the (?:cell|row)\))?"
    r"|transform(?:: ?(?:translate[xyz]?|scale[xy]?|rotate)(?:\([^)]*\))?)?"
    r"|none \(a cut\)"
    r"|by reference \((?:cmp \d{3}|§\d+(?:\.\d+)*)\))$"
)
DURATION_CELL = re.compile(
    r"^`motion\.duration\.(instant|fast|normal)` \((\d+) <!-- audit:motion\.duration\.\1=\2 --> ms\)$"
)
EASING_CELL = re.compile(
    r"^(?:none|motion\.easing\.(?:standard|decelerate|accelerate)"
    r"(?: to (?:open|close)(?:, motion\.easing\.(?:standard|decelerate|accelerate) to (?:open|close))?)?)$"
)
# the owners' recipes a row may cite by reference (Property, Duration, Easing): id → the owner
# its Component and Property must name; never a row on CMP-114, CMP-115 or CMP-116
BY_REF: dict[str, tuple[str, ...]] = {
    "Mo-5": ("cmp 015",),
    "Mo-7": ("cmp 123", "§2.4"),
    "Mo-11": ("cmp 043",),
    "Mo-13": ("cmp 028",),
}
DATA_CMP = r"\bcmp 11[456]\b"
# RULED BQ-9: the rows that move under motion-safe; every other row is a cut or by reference
ANIMATED_IDS = ("Mo-1", "Mo-2", "Mo-3", "Mo-4", "Mo-6", "Mo-9")
DATA_ROW = r"\b(?:data )?rows?\b|\bcells?\b|\bgrid\b|\bblotter\b|\bcmp 11[456]\b|\bbadges?\b"
# what moves, for a duration claim: a moving verb or the motion nouns of this spec
MOTION_WORD = (
    MOVE_VERBS + r"|\bflash\w*|\boverlays?\b|\bhighlights?\b|\btransitions?\b|\banimations?\b"
    r"|\binserts?\b|\bexits?\b|\bfades?\b|\bslides?\b|\bmotion\b|\bsweeps?\b|\bopacity\b|\btransform\b"
)
SPELLED = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100, "thousand": 1000,
}  # fmt: skip
FRACTION = {"half": 0.5, "quarter": 0.25, "tenth": 0.1, "fifth": 0.2, "third": 1 / 3}
UNIT_MS = r"(?:ms|msecs?|milliseconds?)"
UNIT_S = r"(?:s|secs?|seconds?)"
# a spelled duration counts in a duration phrase: after over / for / in / lasts / takes / runs,
# or before the motion it times ("a half second fade")
DURATION_LEAD = r"\b(?:over|for|in|within|lasts?|lasting|takes?|taking|runs?|running|of)\s+(?:about |roughly |some |nearly |almost |around )?"
WORD_NUM = r"(?:(?:" + "|".join(SPELLED) + r"|and)\s+){1,5}"


def _spelled_value(words: str) -> float | None:
    total, current = 0.0, 0.0
    for w in words.split():
        if w == "and":
            continue
        v = SPELLED.get(w)
        if v is None:
            return None
        if v in (100, 1000):
            current = (current or 1) * v
            if v == 1000:
                total, current = total + current, 0.0
        else:
            current += v
    return total + current


# a motion token said to run more than once: "twice", "two times", "× 3", "3 times"
REPEAT_WORDS = {"twice": 2.0, "thrice": 3.0, "two": 2.0, "three": 3.0, "four": 4.0, "double": 2.0}
REPEAT = (
    r"(?:(twice|thrice|double)\b|(?:times|x|×|\*) ?(two|three|four|\d+)\b"
    r"|(two|three|four|\d+) times\b|(?:repeated|played|run) (twice|thrice)\b)"
)


def durations(text: str, anywhere: bool = False) -> list[float]:
    """Every duration a text states, in ms, inside a duration phrase (after over / for / in /
    lasts / takes / runs, or before the motion it times: "a 400 ms fade") or, with `anywhere`,
    wherever a typed figure stands: typed (`400 ms`, `0.4 s`, `400-ms`, `1,200 milliseconds`) and
    spelled (`two seconds`, `half a second`, `four hundred ms`, `a tenth of a second`) figures,
    `motion.duration.*` tokens, `twice` and `× 2`. "About 5 s after" times nothing."""
    plain = norm_text(_HIDDEN.sub(" ", text)).replace("`", "")
    out: list[float] = []
    typed = rf"(\d[\d,]*(?:\.\d+)?)\s*({UNIT_MS}|{UNIT_S})\b"
    shapes = (
        [rf"(?<![\w.]){typed}"]
        if anywhere
        else [
            rf"{DURATION_LEAD}{typed}",
            rf"(?<![\w.]){typed}\s+(?:{MOTION_WORD})",
        ]
    )
    for shape in shapes:
        for m in re.finditer(shape, plain):
            v = float(m[1].replace(",", ""))
            out.append(v if re.fullmatch(UNIT_MS, m[2]) else 1000 * v)
    lead = rf"(?:{DURATION_LEAD}|\b)"
    for m in re.finditer(
        rf"{lead}(?:(a|one) )?(half|quarter|tenth|fifth|third)(?: of)?(?: a| an)?\s+{UNIT_S}\b",
        plain,
    ):
        out.append(1000 * FRACTION[m[2]])
    for m in re.finditer(rf"{lead}(?:a |one )?half\s+a\s+{UNIT_S}\b|\ba half {UNIT_S}\b", plain):
        out.append(500.0)
    spelled = (
        rf"{DURATION_LEAD}({WORD_NUM})({UNIT_MS}|{UNIT_S})\b",
        rf"\b({WORD_NUM})({UNIT_MS}|{UNIT_S})\s+(?:{MOTION_WORD})",
    )
    for shape in spelled:
        for m in re.finditer(shape, plain):
            w = _spelled_value(m[1])
            if w:
                out.append(w if re.fullmatch(UNIT_MS, m[2]) else 1000 * w)
    prim = ds_file("primitives")
    for m in re.finditer(rf"motion\.duration\.([a-z-]+)(?:[,;]?\s*{REPEAT})?", plain):
        if f"motion.duration.{m[1]}" in prim:
            v = float(str(prim[f"motion.duration.{m[1]}"]).removesuffix("ms"))
            times = next((float(g) for g in m.groups()[1:] if g and g[0].isdigit()), 0.0)
            word = next((g for g in m.groups()[1:] if g and not g[0].isdigit()), "")
            out.append(v * (times or REPEAT_WORDS.get(word, 1.0)))
    return out


MARKED = re.compile(r"\d[\d,.]*\s*<!-- audit:[A-Za-z0-9_.\-]+=[^ >]+ -->")


def motion_ready(t: Texts) -> bool:
    return not pending(t.spec, "3.2 The motion table")


def is_cut(r: dict[str, str]) -> bool:
    return norm_text(col(r, "Property")).startswith("none")


def by_ref_ok(k: str, r: dict[str, str]) -> bool:
    """`by reference` is allowed: one of the owners' recipes, naming its owner, on no data row."""
    comp = norm_text(col(r, "Component"))
    owners = BY_REF.get(k, ())
    return any(o in comp for o in owners) and not re.search(DATA_CMP, comp)


def mo_structure(spec: str) -> list[str]:
    """One motion table, in §3.2, and no repeated Mo id (a later copy never shadows another)."""
    bad: list[str] = []
    places = table_places(spec, MO_HEAD)
    if places != ["3.2 The motion table"]:
        bad.append(f"the motion tables sit in {places[:3]}, not once in §3.2")
    ids = [k for k, _r in mo_list(spec)]
    bad += [f"{k} is repeated" for k in sorted({k for k in ids if ids.count(k) > 1})]
    return bad


def long_claims(texts: list[str], cap: float) -> list[str]:
    """Sentences (a row: across its cells) that time a motion past `cap` or bind `slow`."""
    hits: list[str] = []
    for text in texts:
        for u in units(text):
            for s in sentences(u):
                b = blanked(s)
                if re.search(SLOW, b):
                    hits.append(f"claim (slow): {b[:60]!r}")
                    continue
                for frag in b.split(" ¦ "):
                    if any(d > cap for d in durations(frag)) and re.search(MOTION_WORD, frag):
                        hits.append(f"claim: {frag[:60]!r}")
                        break
    return hits


def g_row200(t: Texts) -> list[str]:
    """RULED BQ-9 / BQ-12: no motion row longer than `motion.duration.normal`, `slow` nowhere:
    one motion table, each row's Duration a shipped token with its marker and its Easing a
    shipped curve or none (`by reference` only for an owner's recipe); no free cell, frame,
    sentence or `16`-block cell times a motion past the cap; the `16` block's Enter cells are
    ENTER_PINS, exact (no repeat, no added property)."""
    cap = float(t.values["motion.duration.normal"])
    bad: list[str] = []
    if motion_ready(t):
        bad += mo_structure(t.spec)
        for k, r in mo_list(t.spec):
            row = " | ".join(r.values())
            if live(row, SLOW):
                bad.append(f"{k} binds `slow`")
            dur = " ".join(col(r, "Duration").split())
            easing = norm_text(col(r, "Easing"))
            if dur.startswith("by reference") or easing.startswith("by reference"):
                if not by_ref_ok(k, r):
                    bad.append(f"{k} is no owner's recipe and cannot be by reference")
                elif not (dur.startswith("by reference") and easing.startswith("by reference")):
                    bad.append(f"{k} mixes a recipe by reference with its own timing")
                elif durations(MARKED.sub(" ", dur), anywhere=True):
                    bad.append(f"{k} times its owner's recipe in a figure the owner does not cite")
                continue
            m = DURATION_CELL.match(dur)
            if m is None:
                bad.append(f"{k} Duration {dur[:30]!r} is not one shipped token with its marker")
            elif float(m[2]) > cap:
                bad.append(f"{k} runs {m[2]} ms > {cap:g} ms")
            if not EASING_CELL.match(easing):
                bad.append(f"{k} Easing {easing[:30]!r} is not a shipped curve or none")
            for c in ("Component", "Trigger", "Limit"):
                if any(d > cap for d in durations(blanked(col(r, c)))):
                    bad.append(f"{k} {c} times it past {cap:g} ms")
    for r in block16_rows(t.hand):
        name = col(r, "Surface")[:24]
        for c in ("Enter", "Hold"):
            cell = norm_text(col(r, c)).replace("`", "")
            if live(cell, SLOW):
                bad.append(f"`16` block {name!r} {c}: `slow`")
            names = re.findall(r"motion\.duration\.([a-z-]+)", cell)
            names += re.findall(r"\bover (?:the )?([a-z]+)\b(?= /|;|,|$)", cell)
            if any(x not in ("instant", "fast", "normal") for x in names if x in SPEED_WORDS):
                bad.append(
                    f"`16` block {name!r} {c}: a duration that is not instant, fast or normal"
                )
        if any(d > cap for d in durations(col(r, "Enter"), anywhere=True)):
            bad.append(f"`16` block {name!r}: its motion runs past {cap:g} ms")
        bad += [f"`16` block {name!r}: {h}" for h in long_claims([col(r, "Hold / clear")], cap)]
    bad += enter_pins(t.hand)
    texts = [without(x, "3.2 The motion table", "C.6 The `16` block") for x in swept(t)]
    bad += long_claims(texts, cap)
    return one("G-ROW-200", bad)


SPEED_WORDS = ("instant", "fast", "normal", "slow", "slower", "medium", "long", "short")


def g_compositor(t: Texts) -> list[str]:
    """T Perf / RULED BQ-9: a motion row's Property is opacity, a transform or none (a cut), read
    whole (`opacity + color` fails); no sentence animates a layout or paint property, moves rows
    under the pointer or lets neighbours make room."""
    bad: list[str] = []
    if motion_ready(t):
        for k, r in mo_list(t.spec):
            prop = norm_text(col(r, "Property"))
            if not PROPERTY_CELL.match(prop) or re.search(NON_COMPOSITOR, prop):
                bad.append(f"{k} Property {col(r, 'Property')[:30]!r}")
            elif prop.startswith("by reference") and not (
                by_ref_ok(k, r) and any(o in prop for o in BY_REF.get(k, ()))
            ):
                bad.append(f"{k} Property by reference names no owner of its own")
        s31 = norm_text(section(t.spec, "3.1 Data-row rules"))
        for phrase in (
            "nothing moves under the pointer",
            "live data never moves focus",
            'wait behind the "updates paused" chip',
        ):
            if not pending(t.spec, "3.1 Data-row rules") and phrase not in s31:
                bad.append(f"§3.1 does not say {phrase!r}")
    texts = [without(x, "3.2 The motion table", "C.6 The `16` block") for x in swept(t)]
    moving = MOVE_VERBS + "|" + TIMED + r"|\btransition\w*"
    bad += [f"claim: {c!r}" for c in pair_claims(texts, NON_COMPOSITOR, moving, 4)]
    bad += [f"claim (layout): {c!r}" for c in claims(texts, LAYOUT_MOTION)]
    pointer = r"\bunder (?:the )?(?:pointer|cursor|mouse)\b"
    bad += [f"claim (pointer): {c!r}" for c in pair_claims(texts, pointer, MOVE_VERBS, 4)]
    for r in block16_rows(t.hand):
        enter = col(r, "Enter").split("prefers-reduced-motion")[0]
        name = col(r, "Surface")[:24]
        if adjacent(enter, NON_COMPOSITOR, moving, 2) or live(enter, LAYOUT_MOTION):
            bad.append(f"`16` block {name!r}: a layout or paint property moves")
        if not live(enter, r"\bopacity\b|\btransform\b|\bframe 0\b"):
            bad.append(f"`16` block {name!r}: Enter names neither opacity, a transform nor frame 0")
    return one("G-COMPOSITOR", bad)


def twin_body(cell: str) -> str | None:
    m = re.match(r"\s*`?prefers-reduced-motion`?:\s*(.*)$", cell.strip(), re.DOTALL)
    return m[1] if m else None


def twin_ok(cell: str) -> bool:
    """A twin states its instant reading; a twin that moves is G-REDUCE-INSTANT's."""
    body = twin_body(cell)
    if body is None or nullish(body):
        return False
    if moves(body):
        return True
    n = norm_text(unquote(body))
    return re.search(TWIN_NULL, n) is None and re.search(TWIN_OK, n) is not None


def moves(text: str) -> bool:
    """`text` asserts motion: a moving verb, a timing word or a reduced reading that still moves."""
    return live(text, MOVE_VERBS) or live(text, TIMED) or live(text, REDUCED_MOVES)


def is_flash(r: dict[str, str]) -> bool:
    return re.search(r"\bflash\w*|\bvalue change\b", norm_text(col(r, "Component"))) is not None


def g_twin(t: Texts) -> list[str]:
    """AC2 / RULED BQ-9: every motion row and every `16`-block row has its twin, an animated row's
    twin names what still carries the change (the flash's: the sign or ▲ / ▼, T Tech); no
    sentence drops, omits or exempts a twin; §3.5 pairs the flash with a text or glyph delta."""
    bad: list[str] = []
    if motion_ready(t):
        rows = mo_list(t.spec)
        if not rows:
            bad.append("§3.2 has no motion rows")
        for k, r in rows:
            twin = col(r, TWIN)
            body = twin_body(twin) or ""
            if not twin_ok(twin):
                bad.append(f"{k}: no `prefers-reduced-motion` twin")
            elif animated(r) and not moves(body) and not live(body, CARRIER):
                bad.append(f"{k}: the twin does not name what carries the change")
            elif is_flash(r) and not live(body, r"▲|▼|\bsign(?:ed)?\b"):
                bad.append(f"{k}: the flash's twin names neither the sign nor ▲ / ▼")
        table = rows_with(section(t.spec, "3.2 The motion table"), "Property")
        bad += [f"{col(r, 'Mo')[:12]!r} is not a motion-row id" for r in table
                if not re.fullmatch(MO_ID, col(r, "Mo"))]  # fmt: skip
    if not pending(t.spec, "3.5 The flash"):
        s35 = norm_text(section(t.spec, "3.5 The flash"))
        if "pairs with a text or glyph delta" not in s35:
            bad.append("§3.5 does not pair the flash with a text or glyph delta")
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
    flash_alone = (
        r"\b(?:colou?rs?|hues?|tints?) (?:alone|only)\b|\bonly (?:by |through |with )?(?:its |the |a )?"
        r"(?:colou?r|hue|tint)s?\b|\bcolou?r only\b"
    )
    bad += [f"claim (colour): {c!r}" for c in pair_claims(swept(t), r"\bflash\w*", flash_alone, 6)]
    return one("G-TWIN", bad)


def g_reduce_instant(t: Texts) -> list[str]:
    """AC2 / RULED BQ-9: every twin is instant; a sentence naming the reduced reading says it is
    static, a cut or at frame 0, and nothing in it moves; `data-motion` is the one source and the
    in-app setting wins (§3.6)."""
    bad: list[str] = []
    if motion_ready(t):
        for k, r in mo_list(t.spec):
            body = twin_body(col(r, TWIN)) or ""
            if moves(body):
                bad.append(f"{k}: the twin moves")
        s36 = norm_text(section(t.spec, "3.6 Reduced motion"))
        for phrase in (
            "every twin is instant",
            "in app setting wins",
            "no component reads the media",
        ):
            if phrase not in s36:
                bad.append(f"§3.6 does not say {phrase!r}")
    for r in block16_rows(t.hand):
        for m in re.finditer(r"`?prefers-reduced-motion`?:\s*([^;|]*)", col(r, "Enter")):
            if moves(m[1]):
                bad.append(f"`16` block {col(r, 'Surface')[:24]!r}: the twin moves")
    texts = [without(x, "3.2 The motion table", "C.6 The `16` block") for x in swept(t)]
    for text in texts:
        for u in units(text):
            for s in sentences(u):
                at = RAW_REDUCED.search(s)
                if not at:
                    continue
                rest = s[at.start() :]
                pre = s[max(0, at.start() - 24) : at.start()]  # "a shortened twin"
                if re.search(TWIN_MISSING, norm_text(s)):
                    continue  # a twin said to be missing is G-TWIN's
                if (
                    moves(rest)
                    or live(pre, REDUCED_MOVES)
                    or not re.search(REDUCED_SAYS, norm_text(s))
                ):
                    bad.append(f"claim: {norm_text(s)[:60]!r}")
    source = (
        r"\b(?:os|system) (?:signal|setting|preference) wins\b|\bcomponents? reads? the media query"
    )
    bad += [f"claim (source): {c!r}" for c in claims(texts, source)]
    return one("G-REDUCE-INSTANT", bad)


KIND = (
    r"status words?|state words?|labels?|glyphs?|icons?|words?|text|tints?|accents?|colou?rs?"
    r"|tones?|backgrounds?|(?:state|status|tag|chip|pill|tier|marker|badge|background) fills?"
    r"|fill colou?rs?|fill tones?|fills?|pills?|tags?|badges?|markers?|protection chips?|chips?"
    r"|liq(?:uidation)? tiers?|tiers?|t2|lock(?: glyph)?|enabled|disabled|demo|live(?! regions?)"
    r"|environment pills?|env pills?|states?|status|no_sl|✓|⟳|⚠|△"
    # the glyphs this spec draws (§2's Glyph columns): the delta and Side ▲ / ▼, a disclosure's
    # ▸ / ▾ (Mo-10), the Near and Critical tiers' ! and !!; and their names
    r"|[▲▼▸▾△▽▴▾▶◀►◄]|(?<![!\w])!!?(?![!\w])|\bchevrons?\b|\bcarets?\b|\barrows?\b"
    r"|\bdisclosures?\b|\btriangles?\b"
)
# a frame whose id names a state (a status, a liq tier, a chip state, T2, the display or the
# toggle): its Motion names a cut row only
SWAP_FRAME = re.compile(r"/(?:status|liq|sl|t2|display|toggle|amend|env)-")
SWAP_ROW = (
    r"\bstate (?:swaps?|changes?|transitions?|flips?)\b|\bstatus (?:swaps?|changes?|transitions?)\b"
    r"|↔|\bswaps?\b"
)
# the only frames that may name an animated row (default-deny): frame → its row
FRAME_ANIMATED: dict[str, str] = {
    "CMP-114/row-new": "Mo-1",
    "CMP-114/row-lingering-closed": "Mo-2",
    "CMP-114/marker-corrected": "Mo-4",
    "CMP-116/bar-profit": "Mo-3",
    "CMP-116/bar-loss": "Mo-3",
    "CMP-123/holding": "Mo-7",
}
FRAME_MOTION = re.compile(r"^(?:—|Mo-\d+)$")


def g_instant(t: Texts) -> list[str]:
    """RULED BQ-11: every state swap is a cut at frame 0 in both modes — status words, glyphs,
    fills, pills, the liq tier, the protection chip, T2 ↔ enabled and DEMO / LIVE —
    `motion.duration.instant`, no easing. Default-deny: only Mo-1, 2, 3, 4, 6 and 9 animate; a
    frame's Motion names one row or —, only FRAME_ANIMATED's frames name an animated row, and no
    other frame cell, cut row or sentence animates a state; a sentence that moves cites its row
    and no sentence names motion no row has (motion_claims)."""
    bad: list[str] = []
    rows = mo_list(t.spec) if motion_ready(t) else []
    if rows:
        swaps = 0
        for k, r in rows:
            subject = norm_text(col(r, "Component") + " " + col(r, "Trigger"))
            animated_row = not is_cut(r) and not (
                by_ref_ok(k, r) and col(r, "Property").startswith("by")
            )
            if animated_row and k not in ANIMATED_IDS:
                bad.append(f"{k} animates but is not one of RULED BQ-9's animated rows")
            if re.search(SWAP_ROW, subject):
                swaps += 1
                if not is_cut(r):
                    bad.append(f"{k} (a state swap) has Property {col(r, 'Property')[:20]!r}")
            if is_cut(r):
                dur = col(r, "Duration")
                if set(re.findall(r"motion\.duration\.[a-z-]+", dur)) != {
                    "motion.duration.instant"
                }:
                    bad.append(f"{k} (a cut) binds {dur[:24]!r}")
                cells = " | ".join(v for c, v in r.items() if not c.lower().startswith("prefers"))
                if live(_HIDDEN.sub(" ", cells), MOVE_VERBS + "|" + TIMED):
                    bad.append(f"{k} (a cut) moves or eases")
        if not swaps:
            bad.append("§3.2 has no state-swap row (a cut)")
    if not pending(t.spec, "3.3 State swaps"):
        s33 = norm_text(section(t.spec, "3.3 State swaps"))
        bad += [f"§3.3 does not name {k}" for k, rx in SWAP_KINDS.items() if not re.search(rx, s33)]
        for phrase in ("frame 0", "both modes", "no easing"):
            if phrase not in s33:
                bad.append(f"§3.3 does not say {phrase!r}")
    byid = dict(rows)
    cuts = {k for k, r in rows if is_cut(r)}
    places = table_places(t.spec, FRAME_HEAD)
    for h in sorted(set(places)):
        if not h.startswith(STATE_HEADS) or places.count(h) > 1:
            bad.append(f"a frame table in {h[:28]!r} (one per entry of §2)")
    frames = [col(r, "Frame") for _h, r in all_state_rows(t.spec)]
    bad += [f"{f[:32]} is repeated" for f in sorted({f for f in frames if frames.count(f) > 1})]
    for head, r in all_state_rows(t.spec):
        if pending(t.spec, head):
            continue
        frame, motion = col(r, "Frame").strip("`"), col(r, "Motion").strip()
        if not FRAME_MOTION.match(motion):
            bad.append(f"{frame[:32]}: Motion {motion[:24]!r} is not one motion row or —")
            continue
        others = " | ".join(v for c, v in r.items() if c not in ("Frame", "Motion", "Word"))
        if live(others, MOVE_VERBS):
            bad.append(f"{frame[:32]}: a state frame that moves outside its Motion cell")
        if motion == "—" or not byid:
            continue
        if motion not in byid:
            bad.append(f"{frame[:32]}: names a motion row §3.2 does not have")
        elif motion not in cuts and FRAME_ANIMATED.get(frame) != motion:
            bad.append(f"{frame[:32]}: names the animated {motion}, which only FRAME_ANIMATED may")
    for r in block16_rows(t.hand):
        enter = col(r, "Enter")
        if re.search(SWAP_ROW, norm_text(col(r, "Surface"))) and (
            "frame 0" not in norm_text(enter) or live(enter, MOVE_VERBS) or live(enter, TIMED)
        ):
            bad.append(f"`16` block {col(r, 'Surface')[:24]!r} (a state swap) is not a cut")
    texts = [without(x, "3.2 The motion table", "C.6 The `16` block") for x in swept(t)]
    moving = MOVE_VERBS + "|" + TIMED + r"|\btransition(?:s|ed|ing)? (?:from|to|between|into)\b"
    hits = clause_claims(texts, KIND, moving, prep=neutral_names)
    bad += [f"claim: {c!r}" for c in hits]
    cap = float(t.values["motion.duration.normal"])
    bad += [f"claim {c}" for c in motion_claims(swept(t), cap)]
    return one("G-INSTANT", bad)


def as_names(s: str) -> str:
    """`s` with every design-system name but a duration read as "a token" (neutral_names, then
    MOTION_NAME), so `motion.easing.standard` is no easing claim, and CMP-038's name
    (InlineSpinnerText) read as "a component"."""
    s = re.sub(r"\binline ?spinner ?text\b", " a component ", s, flags=re.IGNORECASE)
    return MOTION_NAME.sub(" a token ", neutral_names(s))


def neutral_names(s: str) -> str:
    """A sentence with every design-system token but the motion ones read as "a token", so a
    state word inside a name (`color.status.info.subtle`) is no subject."""
    return re.sub(r"`?(?<![\w.])(?!motion\.)[a-z]+(?:\.[a-z0-9_*{}-]+)+`?", " a token ", s)


LOOP_WORDS = (
    r"shimmer\w*|\bpuls(?:e|es|ed|ing|at\w*)\b|\bloop\w*|\bthrob\w*|\bblink\w*|\bflicker\w*"
    r"|\bstrob(?:e|es|ing|oscop\w*)\b|\bbreath(?:e|es|ed|ing)\b|\bglimmer\w*|\btwinkl\w*"
    r"|\bsparkl\w*|\boscillat\w*|\binfinite\w*|\bsheen\b|\bshin(?:e|es|ing)\b|\bglow\w*"
    r"|\bheartbeat\w*|\bmarquee\w*|\bripple\w*|\bwav(?:e|es|ing)\b|\brepeat(?:s|ing)\b"
    r"|\bcycl(?:e|es|ed|ing)\b|\bcontinuous\w*|\bforever\b|\bendless\w*|\bperpetual\w*"
    r"|\bindeterminate\b|\bping(?:s|ing)?\b|\bover and over\b|\bon repeat\b"
)
# where the ticket's own word "pending shimmer" may stand, quoted: the departure records
TICKET_SECTIONS = (
    "Acceptance-criteria trace",
    "The sixteen questions",
    "Deviations",
    "7.2 Contradictions",
)
TICKET_UNIT = r"\bticket'?s?\b|\bt scope\b|\bdl 7\b"


# a Latin word with a Cyrillic letter in it reads as a Latin word and evades every list
MIXED_SCRIPT = re.compile(r"\b(?=\w*[A-Za-z])(?=\w*[\u0400-\u04ff])\w+\b")


def decamel(text: str) -> str:
    """`pulseOnPending` → `pulse On Pending`, so an identifier keeps its words."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)


def g_loop(t: Texts) -> list[str]:
    """RULED BQ-10: no shimmer, pulse or loop anywhere (case-insensitive, camelCase split, no
    Cyrillic letter inside a Latin word) — only the ticket's own word, quoted where its departure
    is recorded."""
    texts = [decamel(x) for x in swept(t)]
    bad = [f"claim: {c!r}" for c in claims(texts, LOOP_WORDS)]
    for text in texts:
        bad += [f"a word mixing scripts: {w!r}" for w in MIXED_SCRIPT.findall(visible(text))]
    for name, text in (("spec", texts[0]), ("hand-off", texts[1])):
        allowed = set()
        if name == "spec":
            allowed = {u for h in TICKET_SECTIONS for u in units(section(text, h))}
        for u in units(text):
            for s in sentences(u):
                for q in QUOTED.findall(s):
                    if not re.search(LOOP_WORDS, norm_text(q)):
                        continue
                    if re.search(TICKET_UNIT, norm_text(u)) and u in allowed:
                        continue
                    bad.append(f"quoted {norm_text(q)[:40]!r} outside the ticket's departure")
    return one("G-LOOP", bad)


PER_TICK = (
    r"\b(?:per|every|each|on|with|at|for)\s+(?:each\s+|every\s+|a\s+|the\s+|single\s+)?"
    r"(?:(?:new|latest|incoming|fresh|price|mark|market|ws|data|value|feed|book|order|row)\s+)*"
    r"(?:ticks?|updates?|messages?|prints?|trades?|deltas?|changes?|refresh\w*|repaints?"
    r"|fills?|executions?|quotes?)\b"
    r"|\bas (?:the )?(?:new )?(?:prices?|quotes?|values?|ticks?|trades?|data|marks?|updates?) "
    r"(?:stream|arrive|come|pour|flow|tick|update|change)s?\b|\bstream(?:s|ed|ing)? in\b"
    r"|\b(?:every|each|on every|on each|at every|at each) (?:ws |data |animation |painted )?frames?\b"
    r"|\bper ?tick\b|\btick by tick\b|\btick rate\b|\btick driven\b"
    r"|\bwhenever (?:the |a |its |any )?(?:price|value|mark|figure|number|cell|quantity)s? "
    r"(?:changes?|moves?|updates?|ticks?)\b|\b\w+ times (?:a|per) second\b"
    r"|\b(?:each|every|any) (?:price |value |mark )?(?:change|update|tick|fill|refresh|repaint)\b"
    r"|\b(?:each|every) time (?:the |a |its )?(?:mark |last )?(?:price|value|quote|mark|figure)s? "
    r"(?:moves?|changes?|ticks?|updates?)\b|\bwhenever (?:a |the )?(?:new )?(?:quote|price|tick|trade"
    r"|print|update|fill)s? (?:arrives?|lands?|comes in)\b"
)
MOTIONISH = (
    MOVE_VERBS + r"|\bflash\w*|\bhighlight\w*|\boverlays?\b|\btransition\w*|\bpuls\w*|\bblink\w*"
    r"|\breplay\w*|\btriggers? a\b|\bre ?fir\w*|\bfires?\b"
)
LIMIT_OK = r"between starts|\bonce\b|\bone shot\b|\bat most\b|≤|\bno repeat\b"
NUMBERISH = (
    r"\b(?:digits?|numbers?|numerals?|prices?|sizes?|values?|figures?|pnl|quantit\w*|qty|totals?"
    r"|timers?|counters?|countdowns?|ages?)\b"
)
TWEEN = (
    r"count(?:s|ing|ed)? (?:up|down)|\btween\w*|interpolat\w*|roll(?:s|ing)? (?:up|over|to)"
    r"|odometer|\bglid\w*|\banimat\w* to\b|\bticks? (?:up|down)\b"
)


# a `16`-block row that runs per frame, without a limit or with `16` §7.1's limits set aside
TICK_DENY = (
    r"\bno limit\w*|\bunlimited\b|\bwithout (?:a |any )?limit\w*|\blimitless\b"
    r"|\bonce (?:per|a|every|each) (?:painted |animation |ws )?frames?\b"
    r"|\bper (?:painted |animation |ws )?frames?\b|\bevery update\b|\bper ?tick\b"
    r"|\blimits? (?:are |is )?(?:waived|lifted|suspended|ignored|relaxed|off|dropped|removed)\b"
    r"|\b(?:waiv|suspend|lift|ignor|relax|overrid|exempt)\w* (?:\S+ ){0,3}limits?\b"
    r"|\bstale (?:cells?|values?|rows?|figures?) (?:flash|take|get|keep)\w*|\bfull opacity\b"
)
# the flash row of the `16` block: its Enter and Hold / clear cells, exact (default-deny)
FLASH_ENTER_PIN = (
    "an opacity overlay of `color.status.info.subtle` above the cell at `16` §7.1's peak, "
    "decaying over `fast`; `prefers-reduced-motion`: no flash, the signed text and ▲ / ▼ are "
    "the change"
)
FLASH_HOLD_PIN = (
    "`16` §7.1's limits for the value-change emphasis, unchanged and not restated (`16`:199); "
    "latest wins; never while stale"
)


# every Enter cell of the `16` block, in order, exact (default-deny: R02's Property and R04's
# one shot are held at the copy E29-T09 pastes, as the flash row's are; a change here is a
# deliberate edit of this table, never something `--check` takes)
ENTER_PINS: tuple[str, ...] = (
    (
        "the row's own opacity over `fast` / `standard`; `prefers-reduced-motion`: at frame 0 "
        'with its "New" marker'
    ),
    (
        "the row's opacity over `fast` / `accelerate`, `pointer-events: none` from its first "
        "frame; `prefers-reduced-motion`: gone at frame 0, its word was the change"
    ),
    FLASH_ENTER_PIN,
    (
        "the same opacity overlay once, above the row; `prefers-reduced-motion`: no highlight, "
        "the marker word is the change"
    ),
    (
        "the row's own opacity over `fast` / `standard`, at the list's top only; "
        "`prefers-reduced-motion`: at frame 0, its time and side word are the change"
    ),
    (
        "`transform: translateX` over `normal`, `decelerate` to open, `accelerate` to close; "
        "`prefers-reduced-motion`: at frame 0, its heading text is the change"
    ),
    "at frame 0; `prefers-reduced-motion`: the same cut at frame 0",
)


def enter_owned(enter: str) -> bool:
    """An Enter cell another gate reads by its own rule: its twin missing or moving (G-TWIN,
    G-REDUCE-INSTANT), a layout or paint property or no opacity / transform / frame 0
    (G-COMPOSITOR), a tick, a frame or a dropped limit (G-TICK)."""
    twins = re.findall(r"`?prefers-reduced-motion`?:\s*([^;|]*)", enter)
    pre = enter.split("prefers-reduced-motion")[0]
    moving = MOVE_VERBS + "|" + TIMED + r"|\btransition\w*"
    return bool(
        not twins
        or not twin_ok(f"{TWIN}: {twins[0]}")
        or any(moves(x) for x in twins)
        or adjacent(pre, NON_COMPOSITOR, moving, 2)
        or live(pre, LAYOUT_MOTION)
        or not live(pre, r"\bopacity\b|\btransform\b|\bframe 0\b")
        or live(enter, PER_TICK)
        or re.search(TICK_DENY, norm_text(enter))
    )


def enter_pins(hand: str) -> list[str]:
    """The `16` block's Enter cells against ENTER_PINS, by row: changed, added or dropped. The
    flash row is G-TICK's (FLASH_ENTER_PIN) and a cell another gate reads is left to it
    (enter_owned), so each breach reports once."""
    rows = block16_rows(hand)
    if not rows:
        return []
    got = [one_space(col(r, "Enter")) for r in rows]
    bad = [
        f"`16` block row {i + 1} Enter {g[:40]!r} is not its pinned text"
        for i, (g, want) in enumerate(zip(got, ENTER_PINS))
        if g != want and want != FLASH_ENTER_PIN and not enter_owned(g)
    ]
    if len(got) != len(ENTER_PINS):
        bad.append(f"the `16` block has {len(got)} Enter cells, the pins {len(ENTER_PINS)}")
    return bad


def tick_16_block(hand: str) -> list[str]:
    """The `16` block's rows, each read whole (R10 at the copy E29-T09 pastes): no row runs per
    tick, per update or per frame, none drops its limit, a stale cell never flashes; the flash
    row keeps `16` §7.1's peak and limits, its pointer and "never while stale", exact."""
    bad: list[str] = []
    rows = block16_rows(hand)
    flash = [r for r in rows if re.search(r"\bflash", norm_text(col(r, "Surface")))]
    if rows and len(flash) != 1:
        bad.append(f"the `16` block has {len(flash)} flash rows, not one")
    for r in rows:
        name = col(r, "Surface")[:24]
        # the pinned flash Hold is held exact below ("for the value-change emphasis" names
        # `16` §7.1's subject, no trigger); every other cell is read here
        row = decamel(
            " | ".join(one_space(v) for v in r.values() if one_space(v) != FLASH_HOLD_PIN)
        )
        n = norm_text(row).replace("never while stale", " ")
        if live(row, PER_TICK) or re.search(TICK_DENY, n) or re.search(r"\bstale\b", n):
            bad.append(f"`16` block {name!r} runs per tick, per frame or past its limit")
    for r in flash:
        if one_space(col(r, "Enter")) != FLASH_ENTER_PIN:
            bad.append("the `16` block's flash Enter is not `16` §7.1's peak, exact")
        if one_space(col(r, "Hold / clear")) != FLASH_HOLD_PIN:
            bad.append("the `16` block's flash Hold is not `16` §7.1's limits (`16`:199), exact")
    return bad


def g_tick(t: Texts) -> list[str]:
    """RULED BQ-9 / BQ-11: nothing animates per tick or per price update; every animated row
    states its limit; the value flash starts on a settled value at most once per `16`'s gap; the
    numbers never tween — no clause naming a figure moves or is timed, whatever its subject."""
    texts = [decamel(x) for x in swept(t)]
    bad = [f"claim: {c!r}" for c in pair_claims(texts, MOTIONISH, PER_TICK, 6)]
    cap = float(t.values["cited.05.flash-max-per-s"])
    gap = t.values["cited.16.flash-gap-ms"]
    if motion_ready(t):
        for k, r in mo_list(t.spec):
            if is_cut(r):
                continue
            limit = norm_text(_HIDDEN.sub(" ", col(r, "Limit")))
            if not re.search(LIMIT_OK, limit) and not col(r, "Property").startswith("by"):
                bad.append(f"{k} animates with no stated limit")
            for g in re.findall(r"≥ ?(\d[\d,]*) ?ms between starts", limit):
                if 1000 / float(g.replace(",", "")) > cap:
                    bad.append(f"{k} starts more often than {cap:g} per second")
            if live(" | ".join(r.values()), PER_TICK):
                bad.append(f"{k} runs per tick or per update")
            if is_flash(r):
                marker = f"≥ {gap} <!-- audit:cited.16.flash-gap-ms={gap} --> ms between starts"
                if marker not in col(r, "Limit"):
                    bad.append(f"{k}: the flash's Limit is not `16`'s gap between starts")
                if not re.search(r"\bsettled\b", norm_text(col(r, "Trigger"))):
                    bad.append(f"{k}: the flash starts on something other than a settled value")
    bad += [f"claim (tween): {c!r}" for c in pair_claims(texts, NUMBERISH, TWEEN, 4)]
    bad += [f"claim (numbers move): {c!r}" for c in numbers_claims(texts)]
    bad += tick_16_block(t.hand)
    s34 = section(t.spec, "3.4 Never per tick")
    if not pending(t.spec, "3.4 Never per tick") and "per tick" not in norm_text(s34):
        bad.append("§3.4 does not state the per-tick rule")
    return one("G-TICK", bad)


# ---- the components (RULED BQ-5, BQ-7, BQ-8, BQ-14)

# an order-side pending subject: a pending amend, row or value, an amend, an unconfirmed or
# in-flight write ("PENDING" alone is a document status and never one)
PENDING_NEAR = (
    r"\bpending (?:amend\w*|rows?|orders?|moments?|tags?|values?|frames?|states?|edits?|prices?)\b"
    r"|\bamend(?:ing|s|ed)?\b|\boptimistic\w*|\bunconfirmed\b|\bin flight\b|\bunacknowledged\b"
)
AS_CONFIRMED = (
    r"\b(?:as|like) (?:if )?(?:confirmed|applied|accepted|final|filled|committed|done)\b"
    r"|\boptimistically\b|\bbefore (?:the |an? |bybit'?s? )?(?:ack\w*|acknowledg\w*|confirm\w*)\b"
    r"|\b(?:paints?|shows?|keeps?|draws?) the new (?:price|value)\b|\bat once\b|\bas soon as\b"
    r"|\breplac(?:es|ed|ing) the (?:old|live|confirmed) (?:one|value|price)\b|\bdims?\b|\bdimmed\b"
    r"|\breads? (?:working|confirmed|amended|filled)\b|\bdrawn like\b|\b(?:tag|marker) (?:is )?dropped\b"
    r"|\bthe grid updates\b|\bupdates optimistically\b"
)
# drawn as confirmed in words that need no pending subject
PENDING_STRONG = (
    r"\b(?:paints?|shows?|draws?|displays?) the new (?:price|value|quantity)\b[^.;]*\bbefore\b"
    r"|\bbefore (?:the |an? )?(?:bybit'?s? |exchange'?s? )?(?:ack\w*|acknowledg\w*|confirm\w*)\b"
    r"|\b(?:drawn|shown|painted|reads?) as (?:working|confirmed|amended|filled|done)\b"
    r"|\b(?:on|at|upon|after) (?:send\w*|submit\w*|click\w*|the press|enter|commit\w*)\b[^.;]*"
    r"\b(?:takes?|shows?|paints?|draws?|displays?|gets?|reads?|swaps? to|jumps? to) the new "
    r"(?:price|value|quantity|qty|size|trigger)\b"
    r"|\bvalue cell (?:show|keep|paint|hold|tak)(?:s|es|ing)? the new (?:value|price)\b"
    r"|\b(?:disappears?|vanish\w*|is (?:removed|dropped|cleared)|clears?)\b[^.;]*"
    r"\b(?:the moment|as soon as)\b[^.;]*\b(?:sent|submitted)\b"
)
# the pending state itself said to be absent
PENDING_ABSENT = (
    r"\bno pending (?:tag|marker|state|frame)\b|\bwithout (?:a |the |its )?pending (?:tag|marker)\b"
    r"|\bthe pending (?:tag|marker) is (?:dropped|removed|hidden|omitted)\b"
)
# a frame that draws an unacknowledged write: by its B-state, not by a word in it
PENDING_FRAME = re.compile(
    r"/(?:status-(?:sending|amending|cancelling|unknown)|amend-(?:pending|unconfirmed)"
    r"|sl-(?:amending|attaching|verifying)|marker-verifying|row-closing|(?:closed-today-)?provisional)$"
)
PENDING_STATE = r"\b(?:submitting|amend_pending|cancel_pending|amending|pending|unconfirmed|verifying|attaching)\b"
IN_FLIGHT_WORD = (
    r"\bpending\b|\bstill live\b|\bmay still be live\b|\bchecking\b|\bsending\b|\bamending\b"
    r"|\bcancelling\b|\bverifying\b|\battaching\b|\bclosing\b|…|\bunknown\b|→"
)
CONFIRMED_LOOK = (
    r"✓|\bcheck\b|\bconfirmed\b|\bapplied\b|\bamended\b|\baccepted\b|\bdone\b|\bfilled\b"
)


def g_pending(t: Texts) -> list[str]:
    """RULED BQ-5: a pending or optimistic row is a state — the ⟳ marker, the tag and the
    "still live" words — never drawn as confirmed. Every frame of an unacknowledged write (by its
    B-state) keeps an in-flight word and shows no confirmed word or ✓; no sentence draws one as
    confirmed."""
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
        if pending(t.spec, head):
            continue
        frame = col(r, "Frame").strip("`")
        if not (PENDING_FRAME.search(frame) or live(col(r, "State"), PENDING_STATE)):
            continue
        word = col(r, "Word")
        if not re.search(IN_FLIGHT_WORD, norm_text(word)):
            bad.append(f"{frame[:32]}: a pending frame's Word has no in-flight word")
        if live(word, CONFIRMED_LOOK, keep_quotes=True) or live(col(r, "Glyph"), CONFIRMED_LOOK):
            bad.append(f"{frame[:32]}: a pending frame drawn as confirmed")
        if "amend" in frame and re.search(r"\bpending\b|\bstill live\b", norm_text(word)):
            if "color.status.info.subtle" not in col(r, "Fill"):
                bad.append(f"{frame[:32]}: its pending tag is not on `color.status.info.subtle`")
            if "⟳" not in col(r, "Glyph") and "refresh" not in col(r, "Glyph"):
                bad.append(f"{frame[:32]}: its pending amend has no ⟳")
    bad += [f"claim: {c!r}" for c in pair_claims(swept(t), PENDING_NEAR, AS_CONFIRMED, 12)]
    bad += [f"claim: {c!r}" for c in claims(swept(t), PENDING_STRONG)]
    for text in swept(t):
        for u in units(text):
            for s in sentences(u):
                if re.search(PENDING_ABSENT, norm_text(unquote(s))):
                    bad.append(f"claim (no pending state): {norm_text(s)[:60]!r}")
    return one("G-PENDING", bad)


FLATTEN_NEAR = r"\bflatten\w*|\bcmp 123\b|\bflattenallbutton\b|\bclose all\b|\bcancel all\b"
LIVE_ENV = r"\blive\b(?! regions?)"
HOLD_ONLY = (
    r"\bhold (?:or|/) (?:a |the )?typed\b|\btyped (?:or|/) (?:a |the )?hold\b"
    r"|\b(?:hold|typed)[- ]only\b|\b(?:hold|typed)(?: confirm\w*| word)? (?:alone|only)\b"
    r"|\bonly (?:a |the )?(?:hold|typed)\b|\beither (?:a |the )?(?:hold|typed)\b"
    r"|\bwithout (?:a |the )?(?:hold|typed)\b|\b(?:drops?|skips?|omits?) (?:a |the )?(?:hold|typed)\b"
    r"|\b(?:no|not|without) (?:a |the |its )?(?:typed|hold)\w*"
    r"|\b(?:typed|hold)\w*(?: word| confirm\w*| ring| step)? (?:is |are |stays |becomes )?"
    r"(?:optional|waived|dropped|skipped|not required|not needed)\b"
    r"|\bsingle (?:enter|press|click|activation)\b|\b(?:a|one) (?:click|tap)\b"
    r"|\bconfirm\w* (?:by|with) (?:a |one )?(?:single )?(?:click|enter|press|tap)\b"
    r"|\breplaces? the (?:hold|typed)\w*"
)
# a confirm whose typed word or hold depends on who or what
CONDITIONAL = (
    r"\bfor the \w+s? only\b|\bonly for\b|\bif the\b|\bif (?:it|its|they)\b|\bwhen the (?:account"
    r"|order|size|notional|position)\b|\bunless\b|\bdepending on\b"
)
# the typed word moved to DEMO ("a typed word on DEMO"; never "`hold` in DEMO and `typed` in LIVE")
DEMO_TYPED = (
    r"\b(?:on|in) demo\b[^.;¦|]{0,12}\btyped\b(?! (?:word )?(?:on|in) live)"
    r"|\btyped\b(?: word| confirm\w*)? (?:on|in) demo\b"
)
# the confirm said to be skipped whatever the environment
NO_CONFIRM = r"\bno confirm\w*|\bwithout (?:a |any )?confirm\w*|\bconfirm\w* (?:is |are )?(?:optional|skipped|waived)\b"
# the subjects a hold-only claim names without a flatten word: the typed word, the hold
CONFIRM_SUBJECT = r"\btyped (?:word|confirm\w*)\b|\bthe hold\b|\bhold ring\b"
# the frames §2.4 must draw for the composite (default-deny on deletion)
FLATTEN_FRAMES = ("CMP-123/holding", "CMP-123/armed", "CMP-123/typed-live", "CMP-123/t2-view-as")
WAIVED = (
    r"\boptional\w*|\bmay (?:skip|omit|drop)\b|\bskip\w*|\bwaiv\w*|\bnot required\b|\bdropped\b"
    r"|\bsingle (?:enter|press|click|activation)\b|\b(?:a|one) click\b"
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
    """RULED BQ-7 / AC3: CMP-123's confirm is a composite — hold AND typed on LIVE (asserted,
    neither negated nor waived), hold alone on DEMO — defined once in §2.4; no sentence of the
    flatten context drops either on LIVE; no host restates the hold, in figures or words."""
    bad: list[str] = []
    if not pending(t.spec, "2.4 CMP-123"):
        rows = rows_with(section(t.spec, "2.4 CMP-123"), "Environment", "Confirm")
        lives = [r for r in rows if "LIVE" in col(r, "Environment")]
        if not lives:
            bad.append("§2.4 has no LIVE confirm row")
        for r in lives:
            raw = col(r, "Confirm")
            c = norm_text(raw)
            both = re.search(r"\bhold\b.*\b(?:and|\+|plus|then|with)\b.*\btyped\b", c) or re.search(
                r"\btyped\b.*\b(?:and|\+|plus|then|with)\b.*\bhold\b", c
            )
            asserted = live(raw, r"\bhold\b") and live(raw, r"\btyped\b")
            if (
                not both
                or not asserted
                or re.search(r"\bhold\b[^|]*\bor\b[^|]*\btyped\b|\beither\b", c)
            ):
                bad.append("the LIVE confirm is not hold and typed")
            elif live(raw, WAIVED) or re.search(CONDITIONAL, c) or re.search(r"\bdemo\b", c):
                bad.append(
                    "the LIVE confirm waives, conditions or moves its hold or its typed word"
                )
        demos = [r for r in rows if "DEMO" in col(r, "Environment")]
        if not any("hold" in col(r, "Confirm") for r in demos):
            bad.append("§2.4 has no DEMO hold row")
        if any(live(col(r, "Confirm"), r"\btyped\b") for r in demos):
            bad.append("the DEMO confirm takes the typed word, which LIVE alone adds")
        frames = {col(r, "Frame").strip("`") for r in state_rows(t.spec, "2.4 CMP-123")}
        bad += [f"§2.4 does not draw {f}" for f in FLATTEN_FRAMES if f not in frames]
    context = set(units(section(t.spec, "2.4 CMP-123")))
    for text in swept(t):
        for u in units(text):
            flatten_ctx = u in context or u.startswith("A-5.")
            for s in sentences(u):
                n = DOUBLE_NEG.sub(" ", norm_text(unquote(s)))
                near = flatten_ctx or re.search(FLATTEN_NEAR, n)
                if (
                    (near or re.search(CONFIRM_SUBJECT, n))
                    and re.search(LIVE_ENV, n)
                    and re.search(HOLD_ONLY, n)
                ):
                    bad.append(f"claim: {n[:60]!r}")
                elif near and (re.search(DEMO_TYPED, n) or re.search(NO_CONFIRM, n)):
                    bad.append(f"claim (DEMO or no confirm): {n[:60]!r}")
    hold = float(t.values.get("cited.cmp044.hold-ms", "0") or 0)
    for head in HOLD_HOSTS:
        block = section(t.spec, head)
        if not block or pending(t.spec, head):
            continue
        restated = "audit:cited.cmp044.hold-ms=" in block
        for u in units(block):
            for s in sentences(u):
                if live(s, r"\bhold\w*") and (hold in durations(s, anywhere=True) or durations(s)):
                    restated = True
        if restated:
            bad.append(f"§{head.split(' ')[0].rstrip('.')} restates the hold (AC3: §2.4 only)")
    return one("G-FLATTEN", bad)


CONTROL_ROLE = (
    r"\brole ?= ?\W?(?:radio(?:group)?|button|switch|checkbox|option|menuitem\w*|tab|slider"
    r"|spinbutton|combobox|listbox|textbox)\b|\btabindex\b|\btab stop\b|\bfocusable\b"
    r"|\baria (?:checked|pressed|disabled|selected)\b|\bcontrol role\b|\bradiogroup\b"
    r"|\bbuttons?\b|\bradio (?:buttons?|groups?)\b|\boperable\b|\bclickable\b|\binteractive\b"
    r"|\bmenus?\b|\bdisabled with a reason\b|\b(?:carries|takes|shows|has) a reason\b"
    r"|\bopens? (?:the |a )?(?:confirm|menu|dialog)\b|\bon (?:click|enter|press)\b"
    r"|\b(?:is|as) a control\b|\bselectable\b|\bpressable\b"
)
T2_TERMS = r"\bt2\b|\block\b|\baria disabled\b|\bcmp 079\b|\bnot_available\b|\brbac\.\w+"
DISPLAY_NEAR = (
    r"\bdisplay (?:variant|frames?|mode|is|has|gets|takes)\b|\bread only display\b|cmp 129/display"
    r"|\bthe display\b|\bdisplay:|(?:^|\s)display$"
)


def g_display(t: Texts) -> list[str]:
    """RULED BQ-8: CMP-129's `display` variant has no control role and no T2: its frames carry
    no glyph, motion or T2 and no word of interaction (quotes read too)."""
    bad: list[str] = []
    if not pending(t.spec, "2.5 CMP-129"):
        rows = [r for r in state_rows(t.spec, "2.5 CMP-129") if "/display" in col(r, "Frame")]
        if not rows:
            bad.append("§2.5 has no display frame")
        for r in rows:
            f = col(r, "Frame")[:32]
            for c in ("Glyph", "Motion", "T2"):
                if not nullish(col(r, c)):
                    bad.append(f"{f}: {c} {col(r, c)[:20]!r}")
            cells = " | ".join(v for k, v in r.items() if k not in ("Frame", "Word"))
            if live(cells, CONTROL_ROLE, keep_quotes=True) or live(
                cells, T2_TERMS, keep_quotes=True
            ):
                bad.append(f"{f}: a control role or the T2 look")
    terms = CONTROL_ROLE + "|" + T2_TERMS
    hits = clause_claims(swept(t), DISPLAY_NEAR, terms, keep_quotes=True)
    bad += [f"claim: {c!r}" for c in hits]
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
# a leg written in words, for a Legs cell that names no key (in the order of LEG_WORDS)
LEG_KEYS = ("rbac.view_as", "rbac.permission", "rbac.account_read_only", "rbac.env", "frozen")
HIDDEN_FOR = (
    r"\bhidden\b|\bhid(?:e|es|ing)\b|\bnot_shown\b|\bnot_offered\b|\babsent\b|\binvisible\b"
    r"|\bremoved\b|\bnot_rendered\b|\bnot_displayed\b|\bnot_visible\b|\bomitted\b"
    r"|\bsees?_no\b|\bgets?_no\b|\bno_\w+_(?:button|control|item)\b|\bwithheld from\b|\bnot_see\b"
    r"|\bsees? only\b"
)
HIDDEN_NEAR = r"\bviewer\w*\b|\bview ?as\b|\bmanagers?\b(?! (?:is|are) not offered)"
LEG_KEY = re.compile(
    r"(?<![\w./])((?:rbac|recon|feed|arm|refusal|blotter|guard|sl)\.[a-z_.*{}]*[a-z_*}])"
    r"|(?<![\w.])(frozen|lockout)(?![\w])"
)
# the frames whose id names their T2 leg: the leg their T2 cell must carry (default-deny)
FRAME_LEG: tuple[tuple[str, str], ...] = (
    ("t2-view-as", "rbac.view_as"),
    ("t2-viewer", "rbac.permission"),
    ("t2-read-only", "rbac.account_read_only"),
    ("owner-only", "rbac.owner_only"),
    ("t2-held", "blotter.held"),
)
ORDER_BEFORE = r"\b(?:before|ahead of|in front of|prior to|then)\b|→"
ORDER_AFTER = r"\b(?:after|behind|later than)\b"


def legs_of(cell: str) -> list[str]:
    """The legs a cell names, in order: every key (backticked or not), else, for a chain written
    in words (`view-as → permission → …`), the words read as their keys."""
    keys = [m[1] or m[2] for m in LEG_KEY.finditer(cell)]
    if keys or "→" not in cell:
        return keys
    found = sorted(
        (m.start(), rank) for rx, rank in LEG_WORDS for m in re.finditer(rx, norm_text(cell))
    )
    return [LEG_KEYS[rank] for _p, rank in found]


def order_claims(n: str) -> list[str]:
    """The ordering errors of one normalised sentence: a leg said to come before a later one,
    after an earlier one, first while it is not view-as, or legs in any order."""
    found = sorted((m.start(), m.end(), r) for rx, r in LEG_WORDS for m in re.finditer(rx, n))
    bad: list[str] = []
    if re.search(r"\bin any order\b|\bany order\b|\bunordered\b", n) and (
        len(found) > 1 or re.search(r"\blegs?\b", n)
    ):
        bad.append("legs in any order")
    if not found:
        return bad
    for m in re.finditer(r"\blast\b", n):
        left = [r for _s, e, r in found if 0 <= m.start() - e <= 24]
        if left and left[-1] != 4:
            bad.append("a leg other than the client states last")
    if re.search(
        r"\b(?:rbac\.)?view[ _]?as\b[^.;¦]{0,40}\b(?:after|behind) (?:every|all|the) other legs?\b",
        n,
    ):
        bad.append("view-as after the other legs")
    for cue, after in ((ORDER_BEFORE, False), (ORDER_AFTER, True)):
        for m in re.finditer(cue, n):
            left = [r for _s, e, r in found if e <= m.start()]
            right = [r for s, _e, r in found if s >= m.end()]
            if left and right and (left[-1] < right[0] if after else left[-1] > right[0]):
                bad.append("legs out of the server's order")
    for m in re.finditer(r"\bfirst\b", n):
        left = [r for _s, e, r in found if 0 <= m.start() - e <= 24]
        if left and left[-1] != 0:
            bad.append("a leg other than view-as first")
    return bad


def g_viewas(t: Texts) -> list[str]:
    """RULED BQ-13: every gated control's legs start at view-as and follow the server's order;
    every T2 frame whose id names its leg carries exactly that leg; no sentence orders the legs
    otherwise or in any order; nothing is hidden from a Viewer."""
    bad: list[str] = []
    if not pending(t.spec, "4.1 The gated controls"):
        rows = gated_rows(t.spec)
        if not rows:
            bad.append("§4.1 has no gated controls")
        for r in rows:
            legs = legs_of(col(r, "Legs"))
            name = col(r, "Control")[:24]
            if not legs:
                if not norm_text(col(r, "Legs")).startswith("none"):
                    bad.append(f"{name}: no legs")
                continue
            if legs[0] != "rbac.view_as":
                bad.append(f"{name}: the first leg is {legs[0]}, not view-as")
            ranks = [leg_rank(k) for k in legs]
            if ranks != sorted(ranks):
                bad.append(f"{name}: the legs are out of the server's order")
    for head, r in all_state_rows(t.spec):
        if pending(t.spec, head):
            continue
        frame = col(r, "Frame").strip("`")
        want = next((k for part, k in FRAME_LEG if part in frame), None)
        if want is not None and legs_of(col(r, "T2"))[:1] != [want]:
            bad.append(f"{frame[:32]}: its T2 is not {want}")
    for text in swept(t):
        for u in units(text):
            for s in sentences(u):
                n = blanked(s)
                bad += [f"claim (order): {x}: {n[:60]!r}" for x in order_claims(n)]
            for chain_m in re.finditer(r"`[a-z][a-z_.*{}]*`(?:\s*→\s*`[a-z][a-z_.*{}]*`)+", u):
                chain_legs = re.findall(r"`([^`]+)`", chain_m[0])
                if not any(x.startswith("rbac.") for x in chain_legs):
                    continue
                ranks = [leg_rank(x) for x in chain_legs]
                if chain_legs[0] != "rbac.view_as" or ranks != sorted(ranks):
                    shown = " → ".join(chain_legs)[:60]
                    bad.append(f"legs out of order or without view-as: {shown}")
    hidden = clause_claims(swept(t), HIDDEN_NEAR, HIDDEN_FOR, unless=r"\bgroup by\b|\badmin\b")
    bad += [f"claim (hidden): {c!r}" for c in hidden]
    anatomy = r"\b(?:the |a )?disabled attribute\b|\bnative disabled\b"
    bad += [f"claim (T2 anatomy): {c!r}" for c in claims(swept(t), anatomy)]
    s42 = norm_text(section(t.spec, "4.2 Never gated"))
    if not pending(t.spec, "4.2 Never gated") and "emits no audit and no analytics" not in s42:
        bad.append("§4.2 does not say a T2 press emits no audit and no analytics")
    return one("G-VIEWAS", bad)


EXIT_WORDS = (
    r"\bcancel\w*|\bclos(?:e|es|ing)\b|\bflatten\w*|\bqty down\b|\breduc(?:e|es|ing)\b"
    r"|\btighten\w*|\btake profit\b|\bexits?\b"
)
NOT_EXIT = r"\b(?:closes|completes) #\d+|\bclosing keyword"
GATED = (
    r"\bt2\b|\bgated\b|\bgat(?:e|es|ing)\b|\block(?:s|ed|ing)?\b|\bdisabled\b|\bunavailable\b"
    r"|\bblocked\b|\baria disabled\b|\bnot_available\b|\bgre[ay]ed\b|\binactive\b|\bwithheld\b"
    r"|\bsuspended\b|\bdimmed\b|\b(?:turned|switched) off\b|\brejected\b|\brefused\b"
    r"|\bwaits? (?:for|behind|on)\b|\bpaused\b|\bheld back\b|\bnot_offered\b|\bdisallowed\b"
    r"|\bdenied\b|\btakes? the \S+ leg\b|\b(?:shows?|carries|takes) a reason\b|\bwith a reason\b"
    r"|\btakes? (?:the )?(?:rbac|recon|feed|arm|refusal)\.|\btakes? (?:the )?(?:frozen|lockout)\b"
    r"|\bis off\b|\bread only\b|\bneeds? (?:a |the )?(?:fresh|live|current|healthy)\b"
)
STATE_GATE = (
    r"rbac\.env|\bfrozen\b|\blockout\b|\barm(?:ed|ing)?\b|\barm\.\w+|refusal\.\w+|recon\.\w+"
    r"|feed\.\w+|\bkill switch\b|\breconcil\w+|\bdesync\w*|\bstale\b|\bmaintenance\b"
    r"|\brate limit\w*|\b429\b|\breconnect\w*|\bverif(?:y|ied|ying)\b|\bfeed (?:state|status)\b"
    r"|\bfresh feed\b|\bstate keys?\b"
)
EXCEPTION = (
    r"\boffline\b|\bunreachable\b|\bod 11\b|\bmanagers?\b[^.;|¦]*\bkill switch\b"
    r"|\bkill switch\b[^.;|¦]*\bmanagers?\b"
)
EXIT_FORBIDDEN = re.compile(
    r"^(?:rbac\.env|frozen|lockout|arm\..*|refusal\..*|recon\..*|feed\..*)$"
)
# a gated control that is an exit by its name, whatever its Kind cell says
EXIT_CONTROL = r"\bclose\b|\bcancel\b|\bflatten\b|\blowering the quantity\b|\bquantity cut\b"
NOT_EXIT_CONTROL = r"\breverse\b|\bedit price\b|\bedit trigger\b|\bquantity up\b|\bresolve\b"


def is_exit_control(r: dict[str, str]) -> bool:
    name = norm_text(unquote(col(r, "Control")) + " " + col(r, "Control"))
    return re.search(EXIT_CONTROL, name) is not None and not re.search(NOT_EXIT_CONTROL, name)


def g_exits(t: Texts) -> list[str]:
    """RULED BQ-13: exits are never gated by a state key or `rbac.env` (the drawn exceptions
    aside): an exit is known by its control's name, whatever its Kind says; no clause gates one."""
    bad: list[str] = []
    if not pending(t.spec, "4.1 The gated controls"):
        for r in gated_rows(t.spec):
            kind_exit = "exit" in norm_text(col(r, "Kind"))
            if is_exit_control(r) and not kind_exit:
                bad.append(f"{col(r, 'Control')[:24]} is an exit and its Kind says otherwise")
            if not (kind_exit or is_exit_control(r)):
                continue
            for k in legs_of(col(r, "Legs")):
                if EXIT_FORBIDDEN.match(k):
                    bad.append(f"{col(r, 'Control')[:24]} (an exit) takes `{k}`")
            for clause in blanked(col(r, "Drawn")).split(" ¦ "):
                if re.search(STATE_GATE, clause) and not re.search(EXCEPTION, clause):
                    bad.append(
                        f"{col(r, 'Control')[:24]} (an exit) is drawn gated: {clause[:40]!r}"
                    )
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
    for text in swept(t):
        for u in units(text):
            for s in sentences(u):
                for frag in blanked(s).split(" ¦ "):
                    if (
                        re.search(EXIT_WORDS, frag)
                        and re.search(GATED, frag)
                        and re.search(STATE_GATE, frag)
                        and not re.search(EXCEPTION + "|" + NOT_EXIT, frag)
                    ):
                        bad.append(f"claim: {frag[:60]!r}")
    return one("G-EXITS", bad)


SUMMED = (
    r"\bsum(?:s|med|ming)?\b|\badd(?:s|ed)? up\b|\bcombin\w*|\bblend\w*|\baggregat\w*"
    r"|\bacross (?:both |the )?environments\b|\bmixed totals?\b|\bone total\b"
)
COLOUR_ONLY = (
    r"\b(?:colou?rs?|fills?|hues?|tints?|borders?) (?:alone|only)\b"
    r"|\bonly (?:by |through |via |with )?(?:its |the |a )?(?:\w+ )?(?:colou?r|fill|hue|tint|border)s?\b"
)
ENV_NEAR = r"\benv\w*\b|\bdemo\b|\blive\b(?! regions?)|\bpills?\b"
# C-2.11: the blotter switches no environment, and a trade group carries one
# the environment by a colour name, `rbac.env` on a DEMO row, the other block made writable,
# LIVE and DEMO summed in words
ENV_WRONG = (
    r"\b(?:live|demo)\b[^.;¦|]{0,40}\b(?:red|green|grey|gray|greyer|grayer|amber|blue|orange|yellow)\b"
    r"|\b(?:red|green|grey|gray|greyer|grayer|amber|blue|orange|yellow)\b[^.;¦|]{0,40}\b(?:live|demo)\b"
    r"|rbac\.env\b[^.;¦|]{0,24}\bdemo\b"
    r"|\bother environment'?s? (?:rows?|block|controls?)\b[^.;¦|]{0,30}\b(?:editable|writable|tradable"
    r"|sendable|act(?:s|ive)?)\b"
    r"|\bone (?:total|figure|sum) for (?:live|demo) and (?:live|demo)\b|\badds? (?:live|demo) and (?:live|demo)\b"
    r"|\binto one (?:figure|total|sum)\b|\bsums? (?:live|demo) (?:and|with) (?:live|demo)\b"
)
ENV_SWITCH = (
    r"\benvironment switch\w*|\bswitch(?:es|ing)? (?:the |its )?environments?\b|\bhotkey switches\b"
    r"|\b(?:trade groups?|groups?|rows?|totals?) (?:may |can |does |do |will )?mix(?:es)? (?:the )?environments\b"
    r"|\bmixes environments\b|\btwo (?:environment )?pills\b"
    r"|\bboth pills\b|\bcarries both environments\b"
)


def g_env(t: Texts) -> list[str]:
    """C-2.11 / RULED BQ-13: totals per environment, never summed; the environment never by
    colour or a border alone; no environment switch, no trade group across environments; a
    LIVE word never drawn with `color.env.demo` alone, nor DEMO with `color.env.live`; a mixed
    view's row name leads with its environment."""
    totals = r"\btotals?\b|\bpnl\b|\bp&l\b"
    bad = [f"claim (summed): {c!r}" for c in pair_claims(swept(t), totals, SUMMED, 4)]
    bad += [f"claim (colour): {c!r}" for c in pair_claims(swept(t), ENV_NEAR, COLOUR_ONLY, 6)]
    bad += [f"claim (C-2.11): {c!r}" for c in claims(swept(t), ENV_SWITCH)]
    bad += [f"claim (environment): {c!r}" for c in claims(swept(t), ENV_WRONG)]
    for text in swept(t):
        for u in units(text):
            if re.search(r"rbac\.env\b\W{0,4}\(?a demo row", norm_text(unquote(u))):
                bad.append(f"`rbac.env` on a DEMO row: {u[:40]!r}")
    for text in swept(t):
        for u in units(text):
            raw = _HIDDEN.sub(" ", u)
            env_names = set(re.findall(r"color\.env\.(live|demo)\b", raw))
            words = {w.lower() for w in re.findall(r"\b(LIVE|DEMO)\b", unquote(raw) + " " + raw)}
            if len(env_names) == 1 and words and not (env_names & words):
                bad.append(f"`color.env.{env_names.pop()}` drawn for {sorted(words)}: {u[:40]!r}")
    if not pending(t.spec, "4.3 Environment"):
        s43 = norm_text(section(t.spec, "4.3 Environment"))
        if "leads with its environment" not in s43:
            bad.append("§4.3 does not say the row name leads with its environment")
        if "never summed" not in s43:
            bad.append("§4.3 does not say the totals are never summed")
        if 'the text pill "live" or "demo"' not in s43:
            bad.append('§4.3 does not name the pill "LIVE" or "DEMO"')
    return one("G-ENV", bad)


# the security invariants no sentence may contradict, whatever re-pin a careless edit carries
SAFETY_CLAIMS: tuple[tuple[str, str], ...] = (
    ("a withdrawal (C-2.8)", r"\bwithdraw\w*|\btransfers? (?:funds|money|between accounts)\b"),
    (
        "a key shown (C-12.2)",
        (
            r"\b(?:api )?keys?\b[^.;¦]{0,30}\b(?:shown|displayed|visible|printed|logged)\b"
            r"|\b(?:shows?|displays?|prints?|logs?) (?:the |an? )?(?:api )?(?:keys?|secrets?)\b"
        ),
    ),
    (
        "an action without its audit (C-2.9)",
        (
            r"\b(?:runs?|goes|is sent|sends?|happens|works|closes|cancels|flattens)\b[^.;¦]{0,24}"
            r"\bwithout (?:an? |its |any )?audit\b|\bskips? (?:the |its )?audit\b"
            r"|\baudit (?:is |are )?(?:skipped|optional|bypassed|off)\b"
        ),
    ),
    (
        "the kill switch bypassed",
        (
            r"\bkill switch\b[^.;¦]{0,30}\b(?:bypass\w*|ignored|skipped|overridden)\b"
            r"|\bbypass\w* the kill switch\b"
        ),
    ),
    (
        "real data in a fixture",
        (
            r"\breal (?:balances?|accounts?|keys?|order ids?)\b[^.;¦]{0,30}\b(?:shown|appears?|displayed|used)\b"
            r"|\b(?:shows?|displays?|uses?) (?:a |the )?real (?:balances?|accounts?|keys?)\b"
        ),
    ),
    (
        "a write under view-as",
        (
            r"\b(?:available|allowed|enabled|sendable|writes?)\b[^.;¦]{0,30}\bwhile viewing as\b"
            r"|\bview ?as (?:may|can) (?:write|send|trade|place)\b"
        ),
    ),
    (
        "a Viewer's write",
        r"\bviewers? (?:may|can) (?:use|send|press|flatten|close|cancel|trade|place|amend|write)\b",
    ),
    (
        "RBAC on the client (C-12.4)",
        r"\b(?:rbac|narrows?|scop\w*|permission\w*)\b[^.;¦]{0,40}\bclient side\b",
    ),
    (
        "a Manager beyond the assigned accounts",
        (
            r"\bmanagers?'?s? (?:account filter|filter|options?|rows?|headings?|totals?|footer)\b[^.;¦]{0,120}"
            r"\b(?:every|all) (?:accounts?|legs?)\b|\b(?:every|any|each) managers? (?:holds?|has) \S*write\b"
        ),
    ),
)


def g_safety(t: Texts) -> list[str]:
    """C-2.8, C-2.9, C-12.2, C-12.4 and the binding conditions: no sentence contradicts a
    security invariant — no withdrawal, no key shown, no action without its audit, the kill switch
    never bypassed, fixtures only, no write under view-as or by a Viewer, RBAC server-side, a
    Manager's scope the assigned accounts — so the pinned text holds after a careless re-pin."""
    bad: list[str] = []
    for what, rx in SAFETY_CLAIMS:
        bad += [f"claim ({what}): {c!r}" for c in claims(swept(t), rx)]
    # an absence said outright ("runs without an audit") is read before any negation is blanked
    absent = SAFETY_CLAIMS[2][1]
    for text in swept(t):
        for u in units(text):
            for s in sentences(u):
                n = norm_text(unnegate(unquote(s)))
                if re.search(absent, n) and not re.search(
                    r"\b(?:never|not|no)\b[^.;]{0,12}\bwithout\b", n
                ):
                    bad.append(f"claim (an action without its audit (C-2.9)): {n[:60]!r}")
    return one("G-SAFETY", bad)


# ---- a11y, tokens, copy (RULED BQ-12, BQ-13, BQ-14)

A11Y_LINES = ("Keyboard:", "Accessible name:", "Live region:")
A11Y_ENTRIES = STATE_HEADS
A11Y_HAND = ("C.1 A-1", "C.2 A-2", "C.3 A-3", "C.4 A-4")
A11Y_TABLE_A = ("CMP-123", "CMP-049", "CMP-105")
A11Y_MIN_WORDS = 6
A11Y_PLACEHOLDER = (
    r"\b(?:see above|see below|as above|to follow|to be (?:written|defined|decided)|tb[dc]|todo"
    r"|fill in|later)\b"
)
ROW_UPDATE = (
    r"\brow (?:updates?|changes?)\b|\beach row\b|\bevery row\b|\bper row\b|\brow by row\b"
    r"|\bindividual rows?\b|\b(?:every|each|any) (?:price |value )?(?:update|change)\b"
    r"|\bvalue changes\b|\b(?:every|each) fill\b|\brows\b(?= (?:announce|speak|read))"
    r"|\b(?:their|its) own updates\b"
)
ANNOUNCE = (
    r"\bannounc\w*|\baria live\b|\b(?:to|into|in|through) (?:the |a )?live regions?\b|\bspoken\b"
    r"|\bspeaks?\b|\bread (?:out|aloud)\b|\bpolite\w*|\bassertive\w*|\bvoiced\b|\bnarrat\w*"
)


def a11y_problem(text: str) -> str:
    """Why an a11y line says nothing: blank, a placeholder, or fewer than six words."""
    if nullish(text):
        return "is blank"
    n = norm_text(text)
    if re.search(A11Y_PLACEHOLDER, n):
        return "is a placeholder"
    if len(re.findall(r"[\w`+↑↓←→]+", n)) < A11Y_MIN_WORDS:
        return f"has fewer than {A11Y_MIN_WORDS} words"
    return ""


def g_a11y(t: Texts) -> list[str]:
    """RULED BQ-14: every entry carries the three a11y lines (keyboard model, accessible-name
    composition, live-region policy), each a real line, never a placeholder; row updates are
    never announced individually."""
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
            why = a11y_problem(line.split(":**", 1)[-1]) if line else "is missing"
            if why:
                bad.append(f"§{head.split(' ')[0]} {label[:-1]} line {why}")
    for head in A11Y_HAND:
        if pending(t.hand, head):
            continue
        line = bullet(section(t.hand, head), "A11y")
        bad += [f"{head} A11y has no {lab[:-1]}" for lab in A11Y_LINES if lab not in line]
        for lab in A11Y_LINES:
            part = re.split(r"(?:Keyboard|Accessible name|Live region):", line.split(lab, 1)[-1])[0]
            words = re.findall(r"[\w`+↑↓←→]+", norm_text(part))
            if lab in line and (re.search(A11Y_PLACEHOLDER, norm_text(part)) or len(words) < 4):
                bad.append(f"{head} A11y {lab[:-1]} is a placeholder or empty")
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
    "shadow", "z", "zindex", "font", "icon", "duration", "easing", "spacing",
)  # fmt: skip
DS_SHAPED = re.compile(
    rf"(?<![\w./@#-])((?:{'|'.join(DS_FAMILIES)})\.[a-z0-9-]+(?:\.[a-z0-9{{}},*-]+)*)(?![\w(])",
    re.IGNORECASE,
)
DS_NAME = re.compile(
    r"`((?:color|space|size|type|radius|elevation|opacity|motion|border|font)\.[a-z0-9.{},*-]+)`"
)
# a backticked dotted name with a design-system word in any segment (`flash.opacity.peak`)
DS_ANY_SEGMENT = re.compile(
    rf"`([a-z][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:{'|'.join(DS_FAMILIES)})(?:\.[a-z0-9-]+)*)`"
)
# a family written kebab, camel or upper-snake (`color-blotter-flash`, `colorBlotterFlash`,
# `COLOR_BLOTTER_FLASH`, `bg-…`, `text-…`): a design-system name in another spelling
DS_KEBAB = re.compile(rf"`((?:{'|'.join(DS_FAMILIES)}|bg|text)-[a-z0-9]+(?:-[a-z0-9]+)*)`")
DS_CAMEL = re.compile(rf"\b((?:{'|'.join(DS_FAMILIES)}|bg|text)(?:[A-Z][a-z0-9]+)+)\b")
DS_UPPER = re.compile(
    rf"\b((?:{'|'.join(f.upper() for f in DS_FAMILIES)}|BG|TEXT)(?:_[A-Z0-9]+)+)\b"
)
DS_PREFIX = re.compile(
    r"\b(?:tokens|theme)\.(?=(?:" + "|".join(DS_FAMILIES) + r")\.)", re.IGNORECASE
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
    """RULED BQ-12: no new design-system name — every name (backticked or bare, any case, a
    `tokens.` / `theme.` prefix dropped, any segment, kebab, camel or upper-snake, or a CSS
    variable) is shipped, recorded in §5's PROPOSED register or a §7.4 row, or a name `15`
    already uses."""
    known = ds_names()
    css_known = {n.replace(".", "-") for n in known}
    recorded = recorded_names(t)
    p15 = at_base(P15_REL)
    bad: list[str] = []
    for name, text in (("spec", t.spec), ("hand-off", t.hand)):
        body = DS_PREFIX.sub("", drop_column(visible(text), "old"))  # Old cells: `15` verbatim
        shaped = {m.lower() for m in DS_SHAPED.findall(body)}
        shaped |= {m.lower() for m in DS_ANY_SEGMENT.findall(body.lower())}
        for n in sorted(shaped):
            if all(x in known for x in expand(n, known)) or n in recorded:
                continue
            bad.append(f"{name}: `{n}` is neither shipped nor recorded")
        for n in DS_KEBAB.findall(body):
            if n not in css_known:
                bad.append(f"{name}: `{n}` spells a design-system name that is not shipped")
        for n in DS_CAMEL.findall(body) + DS_UPPER.findall(body):
            if n not in p15:
                bad.append(f"{name}: `{n}` spells a design-system name that is not shipped")
        css = (
            r"var\(\s*--(?:cv-)?([a-z][a-z0-9-]*)|--cv-([a-z][a-z0-9-]*)|--((?:"
            + "|".join(DS_FAMILIES)
            + r")-[a-z0-9-]+)"
        )
        for m in re.finditer(css, body.lower()):
            v = m[1] or m[2] or m[3]
            if v not in css_known:
                bad.append(f"{name}: `--{v}` is not a shipped name's variable")
    return one("G-TOKEN", bad)


REASON_MAX = 60
REASON_FAMILIES = ("rbac", "recon", "blotter", "guard", "feed", "notice", "inflight", "panel")
COPY_KEY = re.compile(r"`((?:" + "|".join(REASON_FAMILIES) + r")\.[a-z_.*{}]*[a-z_*}])`")


def g_copy(t: Texts) -> list[str]:
    """RULED BQ-13: T2 only with registered keys; every other key PROPOSED with its owner, on a
    §4.1 leg and on a frame's T2 alike; every reason key the texts name is registered, in §6 or
    in the §7.4 ledger; every new reason one sentence of at most sixty characters with a full
    stop."""
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
            if status.startswith("registered") and not all(i in reg for i in idents):
                bad.append(f"`{ident}` is not registered at the base")
            elif status.startswith("proposed"):
                proposed |= set(idents)
                if nullish(col(r, "Owner")):
                    bad.append(f"`{ident}` is PROPOSED with no owner")
            elif not status.startswith(("registered", "proposed")):
                bad.append(f"`{ident}`: status {col(r, 'Status')[:16]!r}")
            strings = QUOTED.findall(col(r, "String"))
            if ident.split(".")[0] in REASON_FAMILIES and status.startswith("proposed") and strings:
                s = strings[0].strip('"“”')
                if len(s) > REASON_MAX or not s.endswith("."):
                    bad.append(f"`{ident}`: the reason is not one sentence of ≤ {REASON_MAX}")
    known = reg | proposed
    if not pending(t.spec, "4.1 The gated controls"):
        for r in gated_rows(t.spec):
            for k in legs_of(col(r, "Legs")):
                if k not in known and not k.endswith("*"):
                    bad.append(f"`{k}` (§4.1) is neither registered nor PROPOSED in §6")
    for head, r in all_state_rows(t.spec):
        for k in legs_of(col(r, "T2")):
            if k not in known and not k.endswith("*"):
                bad.append(f"`{k}` ({col(r, 'Frame')[:28]}) is neither registered nor PROPOSED")
    recorded = known | set(COPY_KEY.findall(section(t.spec, "6. Copy keys")))
    recorded |= set(COPY_KEY.findall(section(t.spec, "7.4 Drift ledger")))
    families = {k.split(".")[0] for k in recorded}
    for name, text in (("spec", t.spec), ("hand-off", t.hand)):
        for k in sorted(set(COPY_KEY.findall(visible(text)))):
            wild = k.endswith("*") and k.split(".")[0] in families
            if k not in recorded and not wild:
                bad.append(f"{name}: `{k}` is neither registered nor in §6 or §7.4")
    return one("G-COPY", bad)


# ---- the security text, pinned default-deny (RULED BQ-16)
# A clause of the spec or the hand-off (a heading, a table cell, a prose sentence, a fenced line)
# is security-bearing when it names, case-insensitive at a word boundary: view-as; flatten or a
# bulk exit; the kill switch or a freeze; a native stop, NO SL or a stop-loss; liquidation;
# reduce-only; read-only; `aria-disabled`; audit; keys, signatures, secrets, withdrawals,
# transfers, `ret_msg`, a balance, an order id or a uid; the environment (`environment`, `env`,
# `color.env.*`, the `"live"` / `"demo"` enums); T2 and its reason keys (`rbac.*`, `recon.*`,
# `blotter.*`, `guard.mismatch*`, `inflight.*`, `notice.*`, `panel.*`, `feed.*`, `arm.*`,
# `refusal.*`), CMP-079, "Not available", the `lock`, hiding, `403`, `account_scope_denied`,
# stickiness, the C-2.6 carve-out, a C-2 / C-12 rule, a `x:write` permission, a permission, a
# role, a scope, a Viewer or a Manager; a fixture money value (USDT, BTC, PnL); the CSV export and
# its watermark; and, case-sensitive, a fixture account (Main, Sub-n), the Owner or an environment
# word (LIVE, DEMO). Every clause of the sections SECURE_SECTIONS names, and every T2 cell, is
# security-bearing whatever it names (pinned by location).
BEARING = re.compile(
    r"\bview(?:ing)?[- ]as\b|\brbac\.\w+"
    r"|\bflatten\w*|\bclose[- ]all\b|\bcancel[- ]all\b|\bcancelallorders\b|\bcloseallpositions\b"
    r"|\bflattenallbutton\b|\bCMP-(?:123|211|079|075|139)\b|\bpanic\b"
    r"|\bkill[- ]switch\b|\bfrozen\b|\bfreeze\b|\bhold[- ]to[- ]confirm\b|\btyped (?:confirm\w*|word)\b"
    r"|\bnative[- ](?:stop|sl)\b|\bno sl\b|\bstop[- ]loss\b|\bliquidat\w*|\breduce[- ]only\b"
    r"|\bread[- ]only\b|\baria-disabled\b|\baudit\w*|\bdestructive\b"
    r"|\bapi[- ]?keys?\b|\bkey (?:material|ids?|vault)\b|\bsignatures?\b|\bwithdraw\w*"
    r"|\btransfers?\b|\bret_msg\b|\bcredentials?\b|\bsecrets?\b|\bpass(?:word|phrase)s?\b"
    r"|\b(?:session|auth\w*|access|bearer|api) tokens?\b|\bbalances?\b|\border ids?\b|\buids?\b"
    r"|\benvironments?\b|\benv\b|\bcolor\.env\.\w+|\"(?:live|demo|testnet)\""
    r"|\brecon\.|\bblotter\.|\bguard\.mismatch|\binflight\.|\bnotice\.|\bpanel\.|\bfeed\.|\barm\."
    r"|\brefusal\.|\bt2\b|\brbacgate\b|\bnot available\b|\block\b|\bhidden\b|\bhid(?:e|es|ing)\b"
    r"|\b403\b|\baccount_scope_denied\b|\bsticky\b|\bcarve-out\b|\bC-(?:2|12)\.\d+\b"
    r"|\b\w+:(?:write|read)\b|\bpermissions?\b|\broles?\b|\bscop(?:e|es|ed|ing)\b"
    r"|\bviewers?\b|\bmanagers?\b|\bUSDT\b|\bBTC\b|\b[ur]?PnL\b|\bP&L\b|\bCSV\b|\bwatermark\w*",
    re.IGNORECASE,
)
BEARING_CASED = re.compile(
    r"\b(?:LIVE|DEMO|TESTNET|Demo|Testnet|Main|Owners?)\b|\bLive\b(?! regions?)|\bSub-\d+\b"
)
# pinned by location: every clause of these sections, whatever it names (RULED BQ-16)
SECURE_SECTIONS: dict[str, tuple[str, ...]] = {
    "spec": ("2.4 CMP-123", "2.5 CMP-129", "4. T2", "4.1 ", "4.2 ", "4.3 ", "6. Copy keys"),
    "hand-off": ("C.4 A-4", "C.5 Table A"),
}
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


def secured(name: str, sec: str, where: str) -> bool:
    """A clause pinned by its place: a section of SECURE_SECTIONS, or any table's T2 cell."""
    return sec.startswith(SECURE_SECTIONS.get(name, ())) or where.endswith(f"{PIN_SEP}T2")


def bearing_clauses(name: str, text: str) -> list[Clause]:
    return [c for c in text_clauses(name, text) if bearing(c[2]) or secured(name, c[0], c[1])]


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


def g_contrast_port(t: Texts) -> list[str]:
    """RULED BQ-1 / BQ-16: the ported contrast helpers equal their source at the base, read as
    text and never run: each function's numbers in order, and the theme layering of
    `verify_tokens.THEMES` equal to `themes.json`'s."""
    bad: list[str] = []
    for rel, func, mine in PORTED:
        theirs = source_numbers(at_base(rel), func)
        if theirs is None:
            bad.append(f"{rel} has no `{func}` at {BASE}")
        elif [float(x) for x in mine()] != theirs:
            bad.append(f"the port of `{func}` differs from {rel}")
    if helper_layering() != theme_sets():
        bad.append("the theme layering differs from `verify_tokens.THEMES`")
    return one("G-CONTRAST-PORT", bad)


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
    exact = DS_NAME.search(rep) or COPY_KEY.search(rep) or re.search(r"\bCMP-\d{3}\b", rep)
    if not (exact or "Deliberate exception" in rep) or live(rep, UNRESOLVED):
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
    "G-SAFETY": g_safety,
    "G-A11Y": g_a11y,
    "G-TOKEN": g_name,
    "G-COPY": g_copy,
    "G-SEC-PIN": g_sec_pin,
    "G-STATES": g_states,
    "G-ORPHAN": g_orphan,
    "G-CONTRAST": g_contrast,
    "G-CVD-PORT": g_cvd_port,
    "G-CONTRAST-PORT": g_contrast_port,
    "G-DRIFT": g_drift,
}
GATE_TAGS = tuple(GATES)
# §8.2's Rule column: what each gate holds, and the ruling it holds it for
GATE_RULES: dict[str, str] = {
    "G-VALUE": "every figure is a marker the tool re-derives (condition)",
    "G-CITE": "cites, quoted fragments and Table A's Old cells hold at the base (condition)",
    "G-PIN": "merged texts at their merge shas (condition)",
    "G-RULED": "RULED cites the #823 ruling; BQ-1 to BQ-16 (BQ-1)",
    "G-OWNER": "the owner-level rows marked; §B's Sign-off never ticked (BQ-2, BQ-10 to BQ-12)",
    "G-AC": "AC1, AC3 and DoD 1-2 met as copy-ready A-rows (BQ-2)",
    "G-CROW": "every departure has its C-row (BQ-2, BQ-5, BQ-9 to BQ-12)",
    "G-BOARDS": "at most ten boards, at most three light twins (BQ-15)",
    "G-BUDGET": "the spec at most 600 lines, §9 at most ten (BQ-1)",
    "G-HANDOFF": "one hand-off, §A to §F (BQ-1)",
    "G-UNTOUCHED": "`15` and `16` byte-identical; the branch changes its three files only (BQ-2)",
    "G-PLACEHOLDER": "no section left to write",
    "G-MUTLIST": "this table lists the tool's mutations (BQ-16)",
    "G-ROW-200": "no motion past `motion.duration.normal`, never `slow`; one table (BQ-9, BQ-12)",
    "G-COMPOSITOR": "Property is opacity, a transform or none; no layout motion (BQ-9)",
    "G-TWIN": "a `prefers-reduced-motion` twin on every row (BQ-9; AC2)",
    "G-REDUCE-INSTANT": "every twin instant (BQ-9; AC2)",
    "G-INSTANT": "state swaps at frame 0; six rows and six frames animate (BQ-9, BQ-11)",
    "G-LOOP": "no shimmer, pulse or loop word, any case (BQ-10)",
    "G-TICK": "nothing per tick or update; the flash rate; the `16` block (BQ-9)",
    "G-PENDING": "pending is a state, never drawn as confirmed (BQ-5)",
    "G-FLATTEN": "hold and typed on LIVE, defined once (BQ-7; AC3)",
    "G-DISPLAY": "CMP-129's display variant: no control role, no T2 (BQ-8)",
    "G-VIEWAS": "the legs in order, view-as first; nothing hidden (BQ-13)",
    "G-EXITS": "exits never gated by a state key or `rbac.env` (BQ-13)",
    "G-ENV": "totals per environment; never colour alone; no switch (BQ-13; C-2.11)",
    "G-SAFETY": "no sentence contradicts a security invariant (C-2.8, C-2.9, C-12.4)",
    "G-A11Y": "the three a11y lines on every entry (BQ-14)",
    "G-TOKEN": "no new token name, in any spelling (BQ-12)",
    "G-COPY": "registered keys or PROPOSED with an owner, legs and frames (BQ-13)",
    "G-SEC-PIN": "the security text pinned by word and by place, default-deny (BQ-16)",
    "G-STATES": "D01 D2's statuses, D02's tiers and chip states, the markers (AC1; BQ-5)",
    "G-ORPHAN": "every SCR-063 and SCR-078 component mapped (AC1; BQ-3)",
    "G-CONTRAST": "the tool's pairs, each at its bar in three themes (BQ-14)",
    "G-CVD-PORT": "the CVD port equals `cvd_simulate.py` (BQ-16)",
    "G-CONTRAST-PORT": "the contrast port equals its two helpers; no repo code runs (BQ-1)",
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
    """Every path the branch changes against the base: committed, staged, in the tree or new and
    untracked (G-UNTOUCHED)."""
    changed = git_out("diff", "--name-only", BASE).split("\n")
    changed += git_out("ls-files", "--others", "--exclude-standard").split("\n")
    return tuple(sorted({n for n in changed if n}))


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


def insert_before(
    head: str,
    words: tuple[str, ...],
    pick: Callable[[dict[str, str]], bool],
    row: Callable[[dict[str, str]], str],
) -> Edit:
    """Insert `row(r)` before the first row `pick` chooses in the first table of `head` whose
    header holds `words` (a copy of a row placed ahead of it, for a repeated id)."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        lines = block.split("\n")
        for i in range(len(lines) - 1):
            if not (lines[i].lstrip().startswith("|") and is_rule(lines[i + 1])):
                continue
            header = split_row(lines[i])
            if not all(w.lower() in " | ".join(header).lower() for w in words):
                continue
            for j in range(i + 2, len(lines)):
                if not lines[j].lstrip().startswith("|"):
                    break
                r = dict(zip(header, split_row(lines[j]), strict=False))
                if pick(r):
                    lines.insert(j, row(r))
                    return text.replace(block, "\n".join(lines), 1)
            return text
        return text

    return run


def slow_cell(v: Values, _cell: str) -> str:
    """A Duration cell binding `motion.duration.slow` with its marker (M1.3)."""
    return f"`motion.duration.slow` ({marker(v, 'motion.duration.slow')} ms)"


def nudge_knee() -> Callable[[], None]:
    """Move the ported WCAG knee to `verify_tokens`' sRGB knee (G-CONTRAST-PORT); returns the
    undo. No token channel lies between the two knees, so no ratio moves."""
    global WCAG_KNEE
    old = WCAG_KNEE
    WCAG_KNEE = LAB_KNEE

    def undo() -> None:
        global WCAG_KNEE
        WCAG_KNEE = old

    return undo


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
    names: Callable[[tuple[str, ...]], tuple[str, ...]] | None = None  # the branch's changed paths


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
        spec=with_values(
            lambda v: mo_edit(
                swap_row,
                "Duration",
                to(f"`motion.duration.fast` ({marker(v, 'motion.duration.fast')} ms)"),
            )
        ),
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
    # ---- round 1 (the lenses' frame-level cases; each trips its gate alone)
    # G-ROW-200: one motion table, no repeated id, a closed Duration / Easing grammar, `16`, prose
    Mutation(
        "M1.3",
        "G-ROW-200",
        "BQ-9 (a repeated id)",
        spec=with_values(
            lambda v: insert_before(
                "3.2 The motion table",
                MO_WORDS,
                lambda r: row_key(col(r, "Mo")) == "Mo-3",
                lambda r: join_row(
                    [slow_cell(v, c) if k.startswith("Duration") else c for k, c in r.items()]
                ),
            )
        ),
    ),
    Mutation(
        "M1.4",
        "G-ROW-200",
        "BQ-9 (a second table)",
        spec=with_values(
            lambda v: prose_at(
                "3.2 The motion table",
                "| Mo | Component | Trigger | Property | Duration | Easing | "
                "prefers-reduced-motion twin | Limit | Board |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| Mo-14 | a state swap of the row menu | the state changes | none (a cut) | "
                f"`motion.duration.instant` ({marker(v, 'motion.duration.instant')} ms) | none | "
                "prefers-reduced-motion: the same cut at frame 0 | — | 06, 07 |",
            )
        ),
    ),
    Mutation(
        "M1.5",
        "G-ROW-200",
        "BQ-9 (by reference)",
        spec=mo_edit(lambda r: row_key(col(r, "Mo")) == "Mo-3", "Duration", to("by reference")),
    ),
    Mutation(
        "M1.6",
        "G-ROW-200",
        "BQ-9 (`16` block)",
        hand=with_values(
            lambda v: sub_in(
                "C.6 The `16` block",
                "own opacity over `fast` /",
                f"own opacity over {marker(v, 'motion.duration.slow')} milliseconds /",
            )
        ),
    ),
    Mutation(
        "M1.7",
        "G-ROW-200",
        "BQ-9 (a spelled unit)",
        spec=with_values(
            lambda v: mo_edit(
                lambda r: row_key(col(r, "Mo")) == "Mo-1",
                "Duration",
                to(f"{marker(v, 'motion.duration.slow')} milliseconds"),
            )
        ),
    ),
    Mutation(
        "M1.8",
        "G-ROW-200",
        "BQ-9 (prose)",
        spec=prose_at(
            "3.1 ",
            lambda v: f"A new row fades in over {marker(v, 'motion.duration.slow')} milliseconds.",
        ),
    ),
    Mutation(
        "M1.9",
        "G-ROW-200",
        "BQ-9 (no Duration)",
        spec=mo_edit(lambda r: row_key(col(r, "Mo")) == "Mo-1", "Duration", to("")),
    ),
    Mutation(
        "M1.10",
        "G-ROW-200",
        "BQ-12 (an Easing not shipped)",
        spec=mo_edit(lambda r: row_key(col(r, "Mo")) == "Mo-1", "Easing", to("easeOutBack")),
    ),
    Mutation(
        "M2.2",
        "G-ROW-200",
        "BQ-12 (`16` block)",
        hand=sub_in("C.6 The `16` block", "own opacity over `fast` /", "own opacity over `slow` /"),
    ),
    Mutation(
        "M2.3",
        "G-ROW-200",
        "BQ-12 (any case)",
        spec=mo_edit(
            lambda r: row_key(col(r, "Mo")) == "Mo-1", "Duration", to("`motion.duration.Slow`")
        ),
    ),
    Mutation(
        "M2.4",
        "G-ROW-200",
        "BQ-12 (prose)",
        spec=prose_at("3.1 ", "Mo-2 binds `motion.duration.slow`."),
    ),
    Mutation(
        "M2.5",
        "G-ROW-200",
        "BQ-12 (a free cell)",
        spec=mo_edit(
            lambda r: row_key(col(r, "Mo")) == "Mo-2",
            "Limit",
            appended(" over `motion.duration.slow`"),
        ),
    ),
    # G-COMPOSITOR: the Property grammar, the `16` block, the §3.2 tail, layout words, the pointer
    Mutation(
        "M3.3",
        "G-COMPOSITOR",
        "BQ-9 (by reference)",
        spec=mo_edit(
            lambda r: row_key(col(r, "Mo")) == "Mo-1", "Property", to("by reference (CMP-015)")
        ),
    ),
    Mutation(
        "M3.4",
        "G-COMPOSITOR",
        "T Perf (`16` block)",
        hand=sub_in(
            "C.6 The `16` block", "the row's own opacity over", "the row's own height over"
        ),
    ),
    Mutation(
        "M3.5",
        "G-COMPOSITOR",
        "T Perf (the §3.2 tail)",
        spec=prose_at("3.2 The motion table", "The docked drawer animates the canvas width."),
    ),
    Mutation(
        "M3.6",
        "G-COMPOSITOR",
        "BQ-9 (a Property read whole)",
        spec=mo_edit(lambda r: row_key(col(r, "Mo")) == "Mo-1", "Property", to("opacity + color")),
    ),
    Mutation(
        "M3.7",
        "G-COMPOSITOR",
        "T Perf (a layout word)",
        spec=prose_at("3.1 ", "A collapsing group accordions shut."),
    ),
    Mutation(
        "M3.8",
        "G-COMPOSITOR",
        "D01:406 (the pointer)",
        spec=prose_at("3.1 ", "Rows move under the pointer."),
    ),
    # G-TWIN, G-REDUCE-INSTANT: wording, the paired delta, one source
    Mutation(
        "M4.4",
        "G-TWIN",
        "AC2 (wording)",
        spec=prose_at("3.6 ", "Mo-3 has no reduced-motion equivalent."),
    ),
    Mutation(
        "M4.5",
        "G-TWIN",
        "T Tech (the paired delta)",
        spec=sub_in(
            "3.5 ", "Every flash pairs with a text or glyph delta", "A flash may be colour only"
        ),
    ),
    Mutation(
        "M5.3",
        "G-REDUCE-INSTANT",
        "AC2 (wording)",
        spec=prose_at("3.6 ", "Reduced motion keeps the flash at half strength."),
    ),
    Mutation(
        "M5.4",
        "G-REDUCE-INSTANT",
        "AC2 (one source)",
        spec=sub_in(
            "3.6 ",
            "the in-app setting wins over the OS signal",
            "the OS signal wins over the in-app setting",
        ),
    ),
    # G-INSTANT: default-deny frames and rows, the §3.2 tail, clause reading, one frame table
    Mutation(
        "M6.9",
        "G-INSTANT",
        "BQ-11 (the §3.2 tail)",
        spec=prose_at(
            "3.2 The motion table", "The status word cross-fades from Working to Filled."
        ),
    ),
    Mutation(
        "M6.10",
        "G-INSTANT",
        "BQ-11 (a frame default-deny)",
        spec=edit_row(
            "2.1 CMP-114",
            STATE_WORDS,
            lambda r: col(r, "Frame") == "`CMP-114/marker-verifying`",
            "Motion",
            to("Mo-1"),
        ),
    ),
    Mutation(
        "M6.11",
        "G-INSTANT",
        "BQ-11 (a bare word)",
        spec=prose_at("3.3 ", "The word fades from Working to Filled."),
    ),
    Mutation(
        "M6.12",
        "G-INSTANT",
        "BQ-9 (a row default-deny)",
        spec=with_values(
            lambda v: add_row(
                "3.2 The motion table",
                MO_WORDS,
                "| Mo-14 | the protection chip (B8 state) | the chip's state is re-read | opacity | "
                f"`motion.duration.fast` ({marker(v, 'motion.duration.fast')} ms) | "
                "`motion.easing.standard` | prefers-reduced-motion: the chip is there at frame 0; "
                "its word is the change | once per re-read | 06, 07 |",
            )
        ),
    ),
    Mutation(
        "M6.13",
        "G-INSTANT",
        "BQ-8 (a second frame table)",
        spec=prose_at(
            "2.5 CMP-129",
            "| Frame | State | Word | Glyph | Fill | Motion | T2 | Board |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
            '| `CMP-129/display-hedge` | `display`, hedge | "Hedge" | — | `color.surface.canvas` | — '
            "| — | 05 |",
        ),
    ),
    # G-LOOP: the widened words, camelCase, a double negation
    Mutation(
        "M7.4", "G-LOOP", "BQ-10 (a word)", spec=prose_at("2.2 ", "The pending tag shows a sheen.")
    ),
    Mutation(
        "M7.5",
        "G-LOOP",
        "BQ-10 (camelCase)",
        hand=sub_in(
            "C.2 A-2",
            "- **Props**: `order: OrderRowData` ·",
            "- **Props**: `order: OrderRowData` · `pulseOnPending?: boolean` ·",
        ),
    ),
    Mutation(
        "M7.6",
        "G-LOOP",
        "BQ-10 (a double negation)",
        spec=prose_at("2.2 ", "A pending row is never drawn without its shimmer."),
    ),
    # G-TICK: per update in words; the flash's Trigger and Limit
    Mutation(
        "M8.3",
        "G-TICK",
        "BQ-9 (whenever)",
        spec=prose_at("2.3 ", "The flash fires whenever the price changes."),
    ),
    Mutation(
        "M8.4",
        "G-TICK",
        "BQ-9 (the flash's Trigger)",
        spec=mo_edit(is_flash, "Trigger", to("every price change")),
    ),
    Mutation(
        "M8.5",
        "G-TICK",
        "BQ-9 (the flash's Limit)",
        spec=mo_edit(is_flash, "Limit", to("at most one start per painted batch")),
    ),
    # G-PENDING: by B-state, the confirmed look, the widened claims
    Mutation(
        "M9.3",
        "G-PENDING",
        "BQ-5 (a pending frame's glyph)",
        spec=edit_row(
            "2.1 CMP-114",
            STATE_WORDS,
            lambda r: col(r, "Frame") == "`CMP-114/sl-amending`",
            "Glyph",
            to("✓ `check`"),
        ),
    ),
    Mutation(
        "M9.4",
        "G-PENDING",
        "BQ-5 (a claim)",
        spec=prose_at("2.2 ", "A pending amend shows the new price at once."),
    ),
    # G-FLATTEN: negation read; the flatten context carried
    Mutation(
        "M10.4",
        "G-FLATTEN",
        "BQ-7 (a negated typed word)",
        spec=edit_row(
            "2.4 CMP-123",
            ("Environment", "Confirm"),
            lambda r: "LIVE" in col(r, "Environment"),
            "Confirm",
            to("CMP-044 `hold` with no typed word"),
        ),
    ),
    Mutation(
        "M10.5",
        "G-FLATTEN",
        "BQ-7 (the §2.4 context)",
        spec=prose_at("2.4 ", "On LIVE the typed word is optional."),
    ),
    # G-DISPLAY: quotes read, the widened roles
    Mutation(
        "M11.3",
        "G-DISPLAY",
        "BQ-8 (a quoted role)",
        spec=edit_row(
            "2.5 CMP-129",
            STATE_WORDS,
            lambda r: col(r, "Frame") == "`CMP-129/display-hedge`",
            "State",
            appended('; takes role="button"'),
        ),
    ),
    Mutation(
        "M11.4",
        "G-DISPLAY",
        "BQ-8 (a claim)",
        spec=prose_at("2.5 ", "The display variant is a button."),
    ),
    # G-VIEWAS: a frame's T2 leg, hiding words, an ordinal order
    Mutation(
        "M12.4",
        "G-VIEWAS",
        "BQ-13 (a frame's leg)",
        spec=edit_row(
            "2.1 CMP-114",
            STATE_WORDS,
            lambda r: col(r, "Frame") == "`CMP-114/t2-viewer`",
            "T2",
            to("`rbac.owner_only`"),
        ),
    ),
    Mutation(
        "M12.5",
        "G-VIEWAS",
        "BQ-13 (hiding)",
        spec=prose_at("4.2 ", "A Viewer sees no Close button."),
    ),
    Mutation(
        "M12.6",
        "G-VIEWAS",
        "BQ-13 (an ordinal)",
        spec=prose_at("4.1 ", "Client states are checked first."),
    ),
    # G-EXITS: clause reading, the Kind trick, an unbackticked leg
    Mutation(
        "M13.3",
        "G-EXITS",
        "BQ-13 (a gating word)",
        spec=prose_at("4.2 ", "Cancel is greyed out while the account is stale."),
    ),
    Mutation(
        "M13.4",
        "G-EXITS",
        "BQ-13 (the Kind cell)",
        spec=edit_row(
            "4.1 The gated controls",
            GATED_WORDS,
            lambda r: col(r, "Control").startswith('"Close ▾"'),
            "Kind",
            to("new exposure"),
        ),
    ),
    Mutation(
        "M13.5",
        "G-EXITS",
        "BQ-13 (an unbackticked leg)",
        spec=edit_row(
            "4.1 The gated controls",
            GATED_WORDS,
            lambda r: col(r, "Control").startswith('"Close ▾"'),
            "Legs",
            appended(" → rbac.env"),
        ),
    ),
    # G-A11Y: a placeholder line; an announcement in other words
    Mutation(
        "M14.3",
        "G-A11Y",
        "BQ-14 (a placeholder)",
        spec=line_edit(
            "- **Live region:** Row updates are never announced individually (T a11y).",
            "- **Live region:**",
            "- **Live region:** later. Was:",
        ),
    ),
    Mutation(
        "M14.4",
        "G-A11Y",
        "BQ-14 (read aloud)",
        spec=prose_at("2.1 ", "Row changes are read aloud."),
    ),
    # G-UNTOUCHED: the branch's file list; a missing `16`
    Mutation(
        "M15.3",
        "G-UNTOUCHED",
        "condition (`14`)",
        names=lambda n: (*n, "docs/plan/14-screens-catalogue.md"),
    ),
    Mutation(
        "M15.4",
        "G-UNTOUCHED",
        "condition (a merged spec)",
        names=lambda n: (*n, "docs/design/E29/E29-D03.md"),
    ),
    Mutation("M15.5", "G-UNTOUCHED", "BQ-2 (`16` missing)", p16=lambda _x: ""),
    # G-VALUE: a quoted time, a spelled unit, a marker dropped
    Mutation(
        "M16.3",
        "G-VALUE",
        "condition (a quote)",
        spec=prose_at("5. ", 'The fade is "120 ms" long.'),
    ),
    Mutation(
        "M16.4",
        "G-VALUE",
        "condition (a spelled unit)",
        spec=prose_at("5. ", "Rows are 26 pixels high."),
    ),
    Mutation(
        "M16.5",
        "G-VALUE",
        "condition (a marker dropped)",
        spec=sub_in(
            "3.5 ",
            "at peak 0.25 <!-- audit:cited.16.flash-peak-opacity=0.25 -->",
            "at peak 0.25",
        ),
    ),
    # G-TOKEN: any segment, kebab
    Mutation(
        "M17.4",
        "G-TOKEN",
        "BQ-12 (any segment)",
        spec=prose_at("3.5 ", "The overlay binds `flash.opacity.peak`."),
    ),
    Mutation(
        "M17.5",
        "G-TOKEN",
        "BQ-12 (kebab)",
        spec=prose_at("3.5 ", "The overlay binds `color-blotter-flash`."),
    ),
    # G-SEC-PIN: a T2 cell, the C-2.11 sentence, the Manager scope, an environment token order
    Mutation(
        "M18.4",
        "G-SEC-PIN",
        "BQ-16 (a T2 cell)",
        spec=edit_row(
            "2.4 CMP-123",
            STATE_WORDS,
            lambda r: col(r, "Frame") == "`CMP-123/t2-manager-kill-switch`",
            "T2",
            to("—"),
        ),
        pinned=True,
    ),
    Mutation(
        "M18.5",
        "G-SEC-PIN",
        "BQ-16 (C-2.11)",
        spec=sub_in(
            "4.3 ",
            " The blotter offers no environment switch, and no hotkey switches the environment "
            "(C-2.11; E30-D02:267).",
            "",
        ),
        pinned=True,
    ),
    Mutation(
        "M18.6",
        "G-SEC-PIN",
        "BQ-16 (a fixture account)",
        spec=sub_in("4. T2", '"Sub-1" and "Sub-2"', '"Sub-1" and "Alice-prod"'),
        pinned=True,
    ),
    Mutation(
        "M19.2",
        "G-SEC-PIN",
        "BQ-16 (an environment token)",
        hand=sub_in(
            "C.1 A-1",
            "the environment pill `color.env.live` / `color.env.demo`",
            "the environment pill `color.env.demo` / `color.env.live`",
        ),
        pinned=True,
    ),
    # G-ENV: C-2.11 in words; a token against its word
    Mutation(
        "M36.2",
        "G-ENV",
        "C-2.11 (a switch)",
        spec=prose_at("4.3 ", "The blotter offers an environment switch."),
    ),
    Mutation(
        "M36.3",
        "G-ENV",
        "BQ-13 (a token against its word)",
        spec=edit_row(
            "2.1 CMP-114",
            STATE_WORDS,
            lambda r: col(r, "Frame") == "`CMP-114/env-mixed-view`",
            "State",
            lambda c: c.replace("`color.env.live`", "`color.env.demo`"),
        ),
    ),
    # G-COPY: a frame's T2 key
    Mutation(
        "M37.3",
        "G-COPY",
        "BQ-13 (a frame's key)",
        spec=edit_row(
            "2.4 CMP-123",
            STATE_WORDS,
            lambda r: col(r, "Frame") == "`CMP-123/offline-rest-unreachable`",
            "T2",
            to("`rbac.managers_ok`"),
        ),
    ),
    # G-CONTRAST-PORT: a ported number moved
    Mutation("M38", "G-CONTRAST-PORT", "BQ-1", patch=nudge_knee),
    # G-SAFETY: the security invariants, held after a careless re-pin
    Mutation(
        "M39.1",
        "G-SAFETY",
        "C-2.8",
        spec=prose_at("2.4 ", "A withdrawal control may be added later."),
    ),
    Mutation(
        "M39.2",
        "G-SAFETY",
        "C-12.2",
        spec=prose_at("2.1 ", "The API key is shown in the account header."),
    ),
    Mutation(
        "M39.3",
        "G-SAFETY",
        "C-2.9",
        spec=prose_at("4.2 ", "Cancel all runs without an audit record."),
    ),
    Mutation(
        "M39.4",
        "G-SAFETY",
        "BQ-13 (view-as)",
        spec=prose_at("4.2 ", "Reverse is available while viewing as another user."),
    ),
    Mutation(
        "M39.5",
        "G-SAFETY",
        "C-12.4",
        spec=sub_in(
            "4.2 ",
            "RBAC narrows a filter's options server-side",
            "RBAC narrows a filter's options client-side",
        ),
    ),
    # round 1, the lenses' pin-only cases made semantic
    Mutation(
        "M10.6",
        "G-FLATTEN",
        "BQ-7 (a condition)",
        spec=edit_row(
            "2.4 CMP-123",
            ("Environment", "Confirm"),
            lambda r: "LIVE" in col(r, "Environment"),
            "Confirm",
            appended(", the typed word only for the Owner"),
        ),
    ),
    Mutation(
        "M10.7",
        "G-FLATTEN",
        "BQ-7 (a frame deleted)",
        spec=drop_row(
            "2.4 CMP-123", STATE_WORDS, lambda r: col(r, "Frame") == "`CMP-123/typed-live`"
        ),
    ),
    Mutation(
        "M12.7",
        "G-VIEWAS",
        "BQ-13 (last)",
        spec=prose_at("4.1 ", "View-as is checked last."),
    ),
    Mutation(
        "M13.6",
        "G-EXITS",
        "BQ-13 (a drawn exception)",
        spec=edit_row(
            "4.1 The gated controls",
            GATED_WORDS,
            lambda r: col(r, "Control").startswith('"Cancel ▾"'),
            "Drawn",
            appended("; the account is reconciling"),
        ),
    ),
    Mutation(
        "M36.4",
        "G-ENV",
        "BQ-13 (a colour name)",
        spec=prose_at("4.3 ", "LIVE rows are told apart by a red fill."),
    ),
    Mutation(
        "M36.5",
        "G-ENV",
        "BQ-13 (`rbac.env` on DEMO)",
        spec=sub_in("4.1 The gated controls", "`rbac.env` (a LIVE row)", "`rbac.env` (a DEMO row)"),
    ),
    Mutation(
        "M12.8",
        "G-VIEWAS",
        "BQ-13 (any order)",
        hand=sub_in(
            "§E ", "the legs fire in their order, view-as first", "the legs fire in any order"
        ),
    ),
    Mutation(
        "M12.9",
        "G-VIEWAS",
        "BQ-13 (view-as after)",
        spec=sub_in(
            "4. T2", "is checked ahead of every other leg", "is checked after every other leg"
        ),
    ),
    Mutation(
        "M13.7",
        "G-EXITS",
        "BQ-13 (a state key)",
        spec=sub_in(
            "4.2 ",
            "are never gated by a state key or `rbac.env`",
            "are gated by a state key",
        ),
    ),
    Mutation(
        "M9.5",
        "G-PENDING",
        "BQ-5 (the value cell)",
        hand=sub_in(
            "C.2 A-2",
            "the value cell keeping the live value",
            "the value cell showing the new value",
        ),
    ),
    Mutation(
        "M11.5",
        "G-DISPLAY",
        "BQ-8 (a lead-in)",
        hand=sub_in(
            "C.4 A-4", "with neither a control role nor a reason", "with a button role and a reason"
        ),
    ),
    Mutation(
        "M39.6",
        "G-SAFETY",
        "BQ-13 (a Manager's scope)",
        spec=sub_in(
            "4. T2",
            "name and count only the Manager's own accounts and legs",
            "name and count every account and leg",
        ),
    ),
    Mutation(
        "M14.5",
        "G-A11Y",
        "BQ-14 (a hand-off line emptied)",
        hand=lambda text, _v: re.sub(
            r"(- \*\*A11y\*\*: Keyboard: ).*?(; Accessible name:)", r"\1\2", text, count=1
        ),
    ),
    Mutation(
        "M16.6",
        "G-VALUE",
        "condition (a hidden comment)",
        spec=prose_at("3.3 ", "<!-- a shimmer, drawn after all -->"),
    ),
    # delta r1 MAJOR-1 (R10 at the `16` block): every block row read whole, the flash pinned
    Mutation(
        "M8.6",
        "G-TICK",
        "BQ-9 (`16` block: the flash Hold per tick)",
        hand=sub_in(
            "C.6 The `16` block",
            FLASH_HOLD_PIN,
            "on each tick, no limit (`16`:199); latest wins; never while stale",
        ),
    ),
    Mutation(
        "M8.7",
        "G-TICK",
        "BQ-9 (`16` block: another row)",
        hand=sub_in(
            "C.6 The `16` block",
            "the marker, until the account's banner is dismissed",
            "the marker, once per frame, no limit",
        ),
    ),
    Mutation(
        "M8.8",
        "G-TICK",
        "BQ-9 (`16` block: another case)",
        hand=sub_in(
            "C.6 The `16` block", FLASH_HOLD_PIN, "PER TICK; Latest Wins; Never While Stale"
        ),
    ),
    Mutation(
        "M8.9",
        "G-TICK",
        "BQ-9 (`16` block: the peak)",
        hand=sub_in("C.6 The `16` block", "at `16` §7.1's peak", "at full opacity"),
    ),
    Mutation(
        "M8.10",
        "G-TICK",
        "BQ-9 (`16` block: stale)",
        hand=sub_in(
            "C.6 The `16` block",
            "latest wins; never while stale",
            "latest wins; stale cells flash too",
        ),
    ),
    # delta r1 m1 (R10): streams and quotes
    Mutation(
        "M8.11",
        "G-TICK",
        "BQ-9 (a stream)",
        spec=prose_at("3.4 ", "The cells flash as prices stream in."),
    ),
    Mutation(
        "M8.12",
        "G-TICK",
        "BQ-9 (a quote)",
        hand=prose_at("§E ", "The cell flashes on each new quote."),
    ),
    Mutation(
        "M8.13",
        "G-TICK",
        "BQ-9 (any case)",
        spec=prose_at("2.1 ", "THE CELL FLASHES ON EACH NEW QUOTE."),
    ),
    # delta r1 MAJOR-2 (R08 at KIND): the spec's own glyphs are state-swap subjects
    Mutation(
        "M6.14",
        "G-INSTANT",
        "BQ-11 (the delta glyph, §3.5)",
        spec=sub_in(
            "3.5 ",
            "swapped by a Mo-8 cut and never animated",
            "sliding in over `motion.duration.fast`",
        ),
    ),
    Mutation(
        "M6.15",
        "G-INSTANT",
        "BQ-11 (a disclosure glyph, the hand-off)",
        hand=sub_in(
            "C.1 A-1",
            "Mo-4 (the correction highlight) and Mo-8",
            "Mo-4 (the correction highlight), the ▸ / ▾ rotating over `motion.duration.fast`, and Mo-8",
        ),
    ),
    Mutation(
        "M6.16",
        "G-INSTANT",
        "BQ-11 (a glyph's name, any case)",
        spec=prose_at("3.3 ", "The Chevron Rotates A Quarter Turn When A Group Expands."),
    ),
    Mutation(
        "M6.17",
        "G-INSTANT",
        "BQ-11 (the Critical tier glyph)",
        spec=prose_at("2.1 ", "The !! fades in over `motion.duration.fast`."),
    ),
    # delta r1 m1 (R11): the new value painted on send
    Mutation(
        "M9.6",
        "G-PENDING",
        "BQ-5 (on send)",
        spec=prose_at("2.2 ", "On send, the cell takes the new price."),
    ),
    Mutation(
        "M9.7",
        "G-PENDING",
        "BQ-5 (on submit, the hand-off)",
        hand=prose_at("§E ", "On submit, the row shows the new quantity."),
    ),
    Mutation(
        "M9.8",
        "G-PENDING",
        "BQ-5 (any case)",
        spec=prose_at("3.3 ", "ON SEND, THE CELL TAKES THE NEW PRICE."),
    ),
    # delta r1 m1 (R16): minutes and hours
    Mutation(
        "M16.7",
        "G-VALUE",
        "condition (minutes)",
        spec=prose_at("2.1 ", "A closed row lingers for 3 minutes."),
    ),
    Mutation(
        "M16.8",
        "G-VALUE",
        "condition (hours, the hand-off)",
        hand=prose_at("§E ", "The chip clears after 2 hours."),
    ),
    Mutation(
        "M16.9",
        "G-VALUE",
        "condition (any case)",
        spec=prose_at("3.4 ", "A closed row lingers for 3 MIN."),
    ),
    # delta r1 m1 (R04): a token run more than once
    Mutation(
        "M1.11",
        "G-ROW-200",
        "BQ-9 (twice)",
        spec=prose_at("3.1 ", "A new row fades in over `motion.duration.normal`, twice."),
    ),
    Mutation(
        "M1.12",
        "G-ROW-200",
        "BQ-9 (two times, the hand-off)",
        hand=prose_at("§E ", "The drawer slides in over `motion.duration.normal` two times."),
    ),
    Mutation(
        "M1.13",
        "G-ROW-200",
        "BQ-9 (any case)",
        spec=prose_at("2.1 ", "A NEW ROW FADES IN OVER `motion.duration.normal`, TWICE."),
    ),
    # delta r1 m2: hand-off §B, the owner's sign-off and the Penpot line
    Mutation(
        "M21.2", "G-OWNER", "BQ-2 (§B Sign-off ticked)", hand=line_edit("| Sign-off", "[ ]", "[x]")
    ),
    Mutation(
        "M21.3",
        "G-OWNER",
        "BQ-15 (§B Penpot ticked)",
        hand=line_edit("| Final Penpot link", "[ ]", "[x]"),
    ),
    Mutation("M21.4", "G-OWNER", "BQ-2 (§B any case)", hand=line_edit("| Sign-off", "[ ]", "[X]")),
    Mutation(
        "M21.5",
        "G-OWNER",
        "BQ-2 (§B a line gone)",
        hand=lambda text, _v: "\n".join(
            ln for ln in text.split("\n") if not ln.startswith("| Contrast and CVD")
        ),
    ),
    # delta r2 MAJOR-1 (BQ-11): the numbers never tween, whatever word is the subject
    Mutation(
        "M8.14",
        "G-TICK",
        "BQ-11 (the price animates)",
        spec=prose_at("3.1 ", "The price animates over `motion.duration.fast`."),
    ),
    Mutation(
        "M8.15",
        "G-TICK",
        "BQ-11 (the row animates the price)",
        spec=prose_at("3.1 ", "The row animates the price."),
    ),
    Mutation("M8.16", "G-TICK", "BQ-11 (no subject)", spec=prose_at("3.4 ", "Animates the price.")),
    Mutation(
        "M8.17",
        "G-TICK",
        "BQ-11 (a quantity, the hand-off)",
        hand=prose_at("§E ", "The quantity slides to its new value."),
    ),
    Mutation(
        "M8.18", "G-TICK", "BQ-11 (any case)", spec=prose_at("2.1 ", "THE ROW ANIMATES THE PRICE.")
    ),
    # delta r2 MINOR-1 (BQ-9): motion no row has, and a moving sentence that cites no row
    Mutation("M6.18", "G-INSTANT", "BQ-9 (bounces)", spec=prose_at("3.1 ", "The row bounces in.")),
    Mutation("M6.19", "G-INSTANT", "BQ-9 (springs)", spec=prose_at("3.1 ", "The row springs in.")),
    Mutation(
        "M6.20", "G-INSTANT", "BQ-9 (eases, no row)", spec=prose_at("3.4 ", "The panel eases in.")
    ),
    Mutation("M6.21", "G-INSTANT", "BQ-9 (wobbles)", spec=prose_at("3.6 ", "The row wobbles.")),
    Mutation(
        "M6.22",
        "G-INSTANT",
        "BQ-9 (a toast timed, no row)",
        spec=prose_at("3.6 ", "The toast eases in over `motion.duration.normal`."),
    ),
    Mutation(
        "M6.23",
        "G-INSTANT",
        "BQ-9 (slides, no row)",
        spec=prose_at("3.6 ", "The tab underline slides."),
    ),
    Mutation(
        "M6.24",
        "G-INSTANT",
        "BQ-9 (slides, the hand-off)",
        hand=prose_at("§E ", "The tab underline slides."),
    ),
    Mutation(
        "M6.25",
        "G-INSTANT",
        "BQ-9 (any case, a row cited)",
        spec=prose_at("3.3 ", "THE ROW BOUNCES IN (MO-1)."),
    ),
    # delta r2 MINOR-2 (BQ-9): the `16` block's Enter cells, exact
    Mutation(
        "M1.14",
        "G-ROW-200",
        "BQ-9 (`16` block: Mo-1 twice)",
        hand=sub_in(
            "C.6 The `16` block",
            "the row's own opacity over `fast` / `standard`;",
            "the row's own opacity over `fast` / `standard`, twice;",
        ),
    ),
    Mutation(
        "M1.15",
        "G-ROW-200",
        "BQ-9 (`16` block: the drawer adds a colour)",
        hand=sub_in(
            "C.6 The `16` block",
            "`accelerate` to close;",
            "`accelerate` to close, then `color` over `fast`;",
        ),
    ),
    Mutation(
        "M1.16",
        "G-ROW-200",
        "BQ-9 (`16` block: another row, any case)",
        hand=sub_in(
            "C.6 The `16` block",
            "over `fast` / `standard`, at the list's top only;",
            "over `FAST` / `STANDARD`, TWICE, at the list's top only;",
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
        qnames = mu.names(names) if mu.names else names
        if (s, h, q15, q16, qnames) == (s1, h1, p15, p16, names) and mu.patch is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (its target is not in the text)")
            continue
        undo = mu.patch() if mu.patch else None
        try:
            pins = base_t.pins if mu.pinned else render_pins(s, h)
            fails, _w = audit(Texts(s, h, q15, q16, inputs, values, qnames, pins))
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


def read_bytes_text(rel: str) -> str:
    """A file as bytes decoded, so a line-ending change is a change; "" when it is missing (a
    missing `15` or `16` is G-UNTOUCHED's FAIL, never a traceback)."""
    path = ROOT / rel
    return path.read_bytes().decode("utf-8", errors="replace") if path.is_file() else ""


def read_texts() -> tuple[str, str, str, str]:
    spec = (ROOT / SPEC_REL).read_text(encoding="utf-8")
    hand = (ROOT / HAND_REL).read_text(encoding="utf-8")
    return spec, hand, read_bytes_text(P15_REL), read_bytes_text(P16_REL)


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
  **Owner approval pending** (agent-delivery adaptations, owner decision 2026-09-25): the owner's
  `approved` comment on #823 stands in for "Design-system team accepted ownership; CDO sign-off
  recorded"; nothing here claims that approval.
@ prose
  **Scope** (the ticket): the five catalogued components SCR-063 and SCR-078 introduce or extend —
  CMP-114 PositionsGrid, CMP-115 OrderRow, CMP-116 PnLBadge, CMP-123 FlattenAllButton and CMP-129
  PositionModeToggle — and the reuse contract for CMP-105 AccountMultiSelect, made design-system
  entries with props, states, tokens and the three a11y lines; and the motion spec for the blotter
  rows (row insert and remove, the value-change flash, the correction highlight), nothing longer
  than `motion.duration.normal` on a data row.
@ prose
  **Key.** `NN`:line = `docs/plan/NN-*.md`; `D01`:line, `D02`:line and `D03`:line =
  `docs/design/E29/E29-D0n.md`; `Exx-Dyy`:line = `docs/design/Exx/Exx-Dyy.md`; `PRIM`:line =
  `packages/ui/tokens/primitives.tokens.json`; `T` = the ticket text (#823: `T Scope`, `T AC1` to
  `T AC3`, `T DoD`, `T Tech`, `T a11y`, `T Perf`).
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
@ row Scope — CMP-114 PositionsGrid with the l ‖ Ticket item
  Scope — CMP-114 PositionsGrid with the liq-proximity warning rows
@ row Scope — CMP-115 OrderRow with its pendin ‖ Ticket item
  Scope — CMP-115 OrderRow with its pending and rejected variants
@ row Scope — CMP-116 PnLBadge (sign, currency ‖ Ticket item
  Scope — CMP-116 PnLBadge (sign, currency, R-multiple)
@ row Scope — CMP-123 FlattenAllButton (destru ‖ Ticket item
  Scope — CMP-123 FlattenAllButton (destructive, hold-to-confirm)
@ row Scope — CMP-123 FlattenAllButton (destru ‖ Where
  §2.4: hold and typed on LIVE (RULED BQ-7)
@ row Scope — CMP-129 PositionModeToggle (one- ‖ Ticket item
  Scope — CMP-129 PositionModeToggle (one-way / hedge, disabled with a reason)
@ row Scope — CMP-129 PositionModeToggle (one- ‖ Where
  §2.5: the read-only `display` variant and the toggle (RULED BQ-8)
@ row Scope — the CMP-105 AccountMultiSelect r ‖ Ticket item
  Scope — the CMP-105 AccountMultiSelect reuse contract
@ row Scope — the ticket's motion list: "row i ‖ Ticket item
  Scope — the ticket's motion list: "row insert/remove, value-change flash …, pending shimmer,
  correction flash on a reconciled row"
@ row Out of scope — implementation and Storyb ‖ Ticket item
  Out of scope — implementation and Storybook code
§ spec ‖ The sixteen questions — RULED (orchestrator, com
@ prose
  BQ-2, BQ-10, BQ-11 and BQ-12 are owner-level and are marked "owner approval pending (#2701)"
  wherever they depart from the ticket's AC, DoD or Scope text; the twelve others are the
  orchestrator's.
@ row BQ-3 ‖ Built here
  contributed CMP-114, CMP-115, CMP-116 and CMP-129; amended CMP-123 and CMP-049; CMP-105 a reuse
  contract; the routed ones answered by delta or change request (§2.8); the rest consumed (§2.9);
  D02 gap 8's elements are named parts of their parent entries (§2.10)
@ row BQ-4 ‖ Built here
  §2.1; row actions take CMP-079's `allowed` + `reason`, never a role prop
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
@ heading
  ## Deviations (recorded, not hidden)
§ spec ‖ 0. Planned boards (PENDING; ten: seven dark, thr
@ row 02 ‖ Draws
  `CMP-115/*`: the fifteen statuses, each glyph + word; the amend moments (editing, pending,
  unconfirmed, rejected); the native-stop row
@ row 03 ‖ Board
  `E29-D04 / 03 pnl-badge-numerics`
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
@ row D02 gap 1 (D02:610); D03 CR-4; E05-D02 G ‖ Asked of E29-D04
  treegrid roles, one roving stop, detail lines and the virtualisation thresholds
@ row D02 gaps 5, 6 and 7 (D02:614–616); D02:3 ‖ Asked of E29-D04
  T2 and busy on CMP-041, CMP-005 and CMP-057; CMP-055, CMP-056 and CMP-042; CMP-075's row pill;
  CMP-139 on row actions
@ row D02 gap 12 (D02:621); D03 CR-2 ‖ Asked of E29-D04
  CMP-078's account scope; the stale tokens
@ row D02 gap 13 (D02:622) ‖ Asked of E29-D04
  CMP-028's tone; CMP-105 as a filter picker; CMP-129's read-only display; CMP-019
@ row D03 CR-1, CR-3, CR-6, CR-8, CR-9 and CR- ‖ Asked of E29-D04
  CMP-028's account line; CMP-239's states; the drawer motion names; registering
  `color.text.primary` on `color.status.success.subtle` (D03:396); CMP-099's CSV form; CMP-079's
  reason keys
@ row D02 OQ-C, OQ-L, OQ-R and OQ-S (D02:652, ‖ Asked of E29-D04
  coloured digits; the row form of `guard.mismatch`; `Ctrl+Shift+F`; 2b on a text SplitButton
@ row E39-D03 C9 and C14 (E39-D03:383, :388); ‖ Asked of E29-D04
  CMP-123's data contract; the one-gate reading of FLATTEN ALL; a CMP-123 sentence routed to
  E33-D04
§ spec ‖ 2. The component contributions
@ prose
  Contributed whole (hand-off A-1 to A-4): CMP-114 PositionsGrid, CMP-115 OrderRow, CMP-116
  PnLBadge and CMP-129 PositionModeToggle; amended field by field in Table A: CMP-123
  FlattenAllButton (A-5) and the CMP-049 base table (A-6); reused by contract: CMP-105
  AccountMultiSelect (A-7); answered by a delta or a change request to their owners: the
  components D02 §15 and D03 §11.2 route here (§2.8), CMP-209's drawer motion among them as A-8;
  consumed as catalogued: the rest (§2.9); D02 gap 8's elements are named parts of their parent
  entries, never new ids (§2.10; RULED BQ-3).
@ prose
  Every state table reads Frame, State, Word, Glyph, Fill, Motion, T2 and Board: the Word is the
  merged copy, cited and never redefined (RULED BQ-13); Motion names a §3.2 row, and a state swap
  names only a cut, Mo-8 (Mo-12 for a row's busy glyph; RULED BQ-11); T2 is "—" or the reason key
  the control shows.
@ prose
  Forced colours (`forced-colors: active`): the hue-only carriers, CMP-116's accent bar, the
  Critical accent, the environment pill's border and the T2 fill and hairline, take D02:527's
  system colours, and every state they mark keeps its word, glyph or `aria-*`.
§ spec ‖ 2.1 CMP-114 PositionsGrid
@ prose
  `15` today (`15`:1240–1272): props `positions`, `groupBy` symbol, account or manager, `columns`
  and `onFlatten`; a `PositionRow` with money as `number`, two margin modes and no environment, R,
  rPnL today, protection or position mode; an A11y line that defers to CMP-049; a Tokens line
  naming two bare status families (`15`:1245); no Variants, States or Motion line.
@ prose
  Proposal (hand-off A-1; RULED BQ-4): CMP-049's `treegrid` (§2.7) with D02 D-1's levels
  (D02:142); `PositionRow` gains `env`, `rPnlToday`, `r` (null without a stop), `protection` (the
  B8 state and its `frozen` flag), `positionMode`, `adlRank` (null: on no frame yet, a contract
  gap) and `marginMode` cross, isolated or portfolio, every money field the generated
  `packages/protocol` decimal string, never `number`; `groupBy` gains `trade_group`, and Group by
  Manager stays the Owner's view choice, never T2 (D02:374); `rowActions` take CMP-079's `allowed`
  + `reason` (`15`:814), never a role prop (E09-D09:34).
@ prose
  Named parts, no new ids: `LiqTierCell`, `ProtectionChip`, `RowMarker`, `GroupHeaderRow`,
  `TotalsRow`, `UpdatesPausedChip` and `ClosedTodayLine` (D02 §5.6: one per environment block,
  collapsed by default; expanded, its own CMP-049 table of closed positions, `role="table"`, whose
  Net is a CMP-116 badge, D02:244); their props are hand-off C.1's `AccountGroup` and `markers`.
@ prose
  Variants: `density`; `groupBy`; one environment or mixed (the Env column only while the account
  scope spans both, D02:146; the LIVE block, then the DEMO block, D02:441); the narrow dock at 360
  px (D02:469).
@ head 7
  T2
@ row `CMP-114/row-default` ‖ Word
  "BTCUSDT ▲ Long 0.250 BTC"
@ row `CMP-114/row-default` ‖ T2
  —
@ row `CMP-114/row-hover` ‖ Word
  "BTCUSDT ▲ Long 0.250 BTC"
@ row `CMP-114/row-hover` ‖ T2
  —
@ row `CMP-114/row-selected` ‖ T2
  —
@ row `CMP-114/cell-focused` ‖ T2
  —
@ row `CMP-114/row-new` ‖ T2
  —
@ row `CMP-114/row-closing` ‖ State
  a close in flight: Close in CMP-001's loading state with its label kept, `aria-busy`, not T2
  (D02:341)
@ row `CMP-114/row-closing` ‖ T2
  —
@ row `CMP-114/row-lingering-closed` ‖ Word
  "Closed +12.40 USDT"
@ row `CMP-114/row-lingering-closed` ‖ T2
  —
@ row `CMP-114/row-stale` ‖ T2
  —
@ row `CMP-114/t2-viewer` ‖ Frame
  `CMP-114/t2-viewer`
@ row `CMP-114/t2-viewer` ‖ State
  T2: a Viewer's Close ▾, `aria-disabled`, its reason the panel notice (D02:433)
@ row `CMP-114/t2-viewer` ‖ Glyph
  `lock` "Not available"
@ row `CMP-114/t2-viewer` ‖ T2
  `rbac.permission`
@ row `CMP-114/env-mixed-view` ‖ Frame
  `CMP-114/env-mixed-view`
@ row `CMP-114/env-mixed-view` ‖ State
  a mixed view: the row's name leads with its environment; the pill is text in a `color.env.live`
  border (D02:441, :516)
@ row `CMP-114/env-mixed-view` ‖ Word
  "LIVE"
@ row `CMP-114/env-mixed-view` ‖ T2
  —
@ row `CMP-114/liq-watch` ‖ T2
  —
@ row `CMP-114/liq-near` ‖ T2
  —
@ row `CMP-114/liq-critical` ‖ T2
  —
@ row `CMP-114/sl-protected` ‖ T2
  —
@ row `CMP-114/sl-attaching` ‖ T2
  —
@ row `CMP-114/sl-verifying` ‖ T2
  —
@ row `CMP-114/sl-amending` ‖ T2
  —
@ row `CMP-114/sl-naked` ‖ Word
  "NO SL ! 12 s"
@ row `CMP-114/sl-naked` ‖ T2
  —
@ row `CMP-114/sl-naked-unrecoverable` ‖ State
  `naked_unrecoverable`: the row keeps a reduce-only Close
@ row `CMP-114/sl-naked-unrecoverable` ‖ Word
  "NO SL — owner paged"
@ row `CMP-114/sl-naked-unrecoverable` ‖ T2
  —
@ row `CMP-114/sl-frozen` ‖ Frame
  `CMP-114/sl-frozen`
@ row `CMP-114/sl-frozen` ‖ State
  `amend_lock.frozen`: a tighten is still sent (D02:234)
@ row `CMP-114/sl-frozen` ‖ Word
  "· frozen"
@ row `CMP-114/sl-frozen` ‖ T2
  —
@ row `CMP-114/marker-verifying` ‖ T2
  —
@ row `CMP-114/marker-corrected` ‖ T2
  —
@ row `CMP-114/group-header` ‖ Word
  "▾ Main · LIVE · One-way · 1 position · uPnL +8.00 · rPnL today +37.40"
@ row `CMP-114/group-header` ‖ T2
  —
@ row `CMP-114/totals-row` ‖ State
  the totals row, one per environment, a trailing `rowgroup` (D02:142, :156)
@ row `CMP-114/totals-row` ‖ Word
  "LIVE total"
@ row `CMP-114/totals-row` ‖ T2
  —
@ row `CMP-114/closed-today-collapsed` ‖ State
  the Closed today line, collapsed by default, one per environment block, `aria-expanded="false"`
  (D02:244)
@ row `CMP-114/closed-today-collapsed` ‖ Word
  "▸ Closed today (since 00:00 UTC) · 3 · net +40.20 USDT · incl. provisional"
@ row `CMP-114/closed-today-collapsed` ‖ T2
  —
@ row `CMP-114/closed-today-expanded` ‖ Word
  "▾ Closed today (since 00:00 UTC) · 3 · net +40.20 USDT · incl. provisional"
@ row `CMP-114/closed-today-expanded` ‖ T2
  —
@ row `CMP-114/closed-today-none` ‖ T2
  —
@ row `CMP-114/closed-today-provisional` ‖ T2
  —
@ row `CMP-114/closed-today-divergent` ‖ T2
  —
@ row `CMP-114/updates-paused-chip` ‖ Fill
  `color.neutral.subtle`; `color.status.danger.subtle` while a held row carries NO SL
@ row `CMP-114/updates-paused-chip` ‖ T2
  —
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
  ("Limit · Take profit", D02:160, OQ-O pending); the sections are Working and "Conditional — not
  triggered" (D02:281); the native-stop row's Cancel takes its `sl.note` sentence (D02:291).
@ prose
  A Cancel sent behind an amend is busy, "Cancelling…" with `aria-busy`, never T2; a native stop's
  tighten in flight reads E32-D01's "Moving the stop to 63,980.0 — waiting for Bybit…" on the same
  tag (D02:320).
@ head 7
  T2
@ row `CMP-115/status-sending` ‖ T2
  —
@ row `CMP-115/status-working` ‖ T2
  —
@ row `CMP-115/status-triggered` ‖ T2
  —
@ row `CMP-115/status-partial` ‖ T2
  —
@ row `CMP-115/status-cancelling` ‖ T2
  —
@ row `CMP-115/status-amending` ‖ T2
  —
@ row `CMP-115/status-unknown` ‖ T2
  `blotter.unknown` (PROPOSED; E29-D03 owns it)
@ row `CMP-115/status-quarantined` ‖ T2
  —
@ row `CMP-115/status-held` ‖ Glyph
  `lock`
@ row `CMP-115/status-held` ‖ T2
  `blotter.held` (PROPOSED; E29-D03 owns it)
@ row `CMP-115/status-untracked` ‖ T2
  `blotter.untracked` (PROPOSED; E29-D03 owns it)
@ row `CMP-115/status-filled` ‖ T2
  —
@ row `CMP-115/status-cancelled` ‖ T2
  —
@ row `CMP-115/status-rejected` ‖ T2
  —
@ row `CMP-115/status-expired` ‖ T2
  —
@ row `CMP-115/status-killed` ‖ State
  killed by the kill switch
@ row `CMP-115/status-killed` ‖ Word
  "Killed (kill switch)"
@ row `CMP-115/status-killed` ‖ T2
  —
@ row `CMP-115/amend-editing` ‖ T2
  —
@ row `CMP-115/amend-pending` ‖ State
  pending (not applied): the value cell keeps the live value; Edit takes `blotter.amend_in_flight`
@ row `CMP-115/amend-pending` ‖ T2
  `blotter.amend_in_flight` (PROPOSED; E29-D03 owns it)
@ row `CMP-115/amend-unconfirmed` ‖ State
  unconfirmed (`unknown`): amend and an unpressed Cancel take `blotter.unknown`
@ row `CMP-115/amend-unconfirmed` ‖ T2
  `blotter.unknown` (PROPOSED; E29-D03 owns it)
@ row `CMP-115/amend-rejected` ‖ T2
  —
@ row `CMP-115/native-stop-row` ‖ Frame
  `CMP-115/native-stop-row`
@ row `CMP-115/native-stop-row` ‖ State
  a native-stop row: Cancel is T2 with its `sl.note` sentence (D02:291)
@ row `CMP-115/native-stop-row` ‖ Word
  "Market · Stop loss"
@ row `CMP-115/native-stop-row` ‖ T2
  `sl.note` (its D02 sentence PROPOSED to E32-D01)
@ row `CMP-115/cancel-t2-held` ‖ Frame
  `CMP-115/cancel-t2-held`
@ row `CMP-115/cancel-t2-held` ‖ State
  Cancel on a held order: T2, `aria-disabled`, the reason as the item's second line
@ row `CMP-115/cancel-t2-held` ‖ Glyph
  `lock` "Not available"
@ row `CMP-115/cancel-t2-held` ‖ T2
  `blotter.held` (PROPOSED; E29-D03 owns it)
@ prose
  - **Accessible name:** In a mixed view the environment leads (§4.3), then the state word with
  its glyph named once, then the type with its purpose, price, quantity and account; the State
  cell's whole line is the description, a pending amend's included ("Amend to 2,495.00 sent to
  Bybit.
@ prose
  The order is still at 2,500.00 until Bybit confirms.", D02:320); a T2 control keeps its full
  label, its reason the description.
§ spec ‖ 2.3 CMP-116 PnLBadge
@ head 7
  T2
@ row `CMP-116/bar-profit` ‖ Word
  "+8.00 USDT"
@ row `CMP-116/bar-profit` ‖ T2
  —
@ row `CMP-116/bar-loss` ‖ Word
  "−121.50 USDT"
@ row `CMP-116/bar-loss` ‖ T2
  —
@ row `CMP-116/bar-flat` ‖ Word
  "0.00 USDT"
@ row `CMP-116/bar-flat` ‖ T2
  —
@ row `CMP-116/r-null` ‖ T2
  —
@ row `CMP-116/fee-paid` ‖ Word
  "−3.49 USDT", read as "fee paid 3.49 USDT"
@ row `CMP-116/fee-paid` ‖ T2
  —
@ row `CMP-116/funding-received` ‖ Word
  "+0.84 USDT", read as "funding received 0.84 USDT"
@ row `CMP-116/funding-received` ‖ T2
  —
@ row `CMP-116/provisional` ‖ T2
  —
@ row `CMP-116/divergent` ‖ T2
  —
@ row `CMP-116/strip-greyscale` ‖ T2
  —
@ row `CMP-116/strip-deuteranopia` ‖ T2
  —
@ prose
  - **Accessible name:** The sign and the value in words as visually hidden text, never an
  `aria-label` on the span (`15`:238): "profit 8.00 USDT", "loss 121.50 USDT", "fee paid 3.49
  USDT", "funding received 0.84 USDT"; a null R reads "R unavailable: no stop price"
  (D02:184–185); the bar is `aria-hidden`.
§ spec ‖ 2.4 CMP-123 FlattenAllButton (the flatten confir
@ heading
  ### 2.4 CMP-123 FlattenAllButton (the flatten confirm, defined once)
@ prose
  `15` today (`15`:1403–1411): `scope` account or all-accounts and `onConfirm`; a Purpose that
  picks one ConfirmDialog variant (`15`:1405); a bare danger family in Tokens (`15`:1408); a Data
  contract naming Bybit's routes and blind to stops (E39-D03:383).
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
  E30, E31 and E39 reference this section and restate neither its hold nor a confirm step (AC3;
  D01:522).
@ prose
  The confirm is the table below: CMP-044 `hold` with its discrete second press, and on LIVE the
  typed word first, which CMP-044 already allows, as its `typedConfirmValue` gates a `hold`
  Confirm (`15`:476; `docs/design/E05/E05-D02-feedback-overlays.md`:286–287).
@ prose
  The ring, its percentage text, the armed label, the window and the key-repeat rule are CMP-044's
  and E39-D03's, cited and never restated (`15`:478; E39-D03:118–123); the ring is dialog motion,
  never a data row's, so the data-row cap of §3 does not bind it (Mo-7, by reference).
@ prose
  Flatten account… leaves the ⋯ menu while its account's snapshot failed, nothing being loaded to
  act on (D02:389).
@ prose
  On LIVE the word typed for `all-accounts` is `FLATTEN`, the catalogue's fixed word (`15`:476,
  :2506; `14`:296; E39-D03:123), and E39-D03's one-gate reading of FLATTEN ALL meets this
  composite in D04-C9; the word for `account` is its copy owner's and stays open (hand-off Q-17):
  CMP-044's rule names "the object's own name", here the account label (`15`:476), and D02 routes
  the bulk words to D03's deck ("CLOSE", D02:349).
@ prose
  Composition with E33-D04 A-6 (PENDING, by name): A-5.1 replaces the Purpose's "`hold` or
  `typed`" choice with this composite and appends after E33-D04 A-6.1's sentence, whichever lands
  first, and A-5.5 is E33-D04 A-6.2's own replacement, so the second to land is a no-op; the route
  names stay E39-D03 C9's.
@ head 1
  Environment
@ head 2
  Confirm
@ head 3
  Discrete keyboard path
@ head 4
  prefers-reduced-motion
@ head 5
  Source
@ row DEMO ‖ Environment
  DEMO
@ row DEMO ‖ Confirm
  CMP-044 `hold` for 800 ms (PROPOSED `motion.duration.hold-confirm`, E39-D03:407; a 300 –2,000 ms
  setting, `15`:476)
@ row DEMO ‖ Discrete keyboard path
  a second `Enter`, CMP-044's armed press
@ row DEMO ‖ prefers-reduced-motion
  the percentage text, static
@ row DEMO ‖ Source
  D01:274; D02:353
@ row LIVE ‖ Environment
  LIVE
@ row LIVE ‖ Confirm
  CMP-044 `hold` and the typed word (`typedConfirmValue` gates the hold, `15`:476)
@ row LIVE ‖ Discrete keyboard path
  the typed word, then a second `Enter`
@ row LIVE ‖ prefers-reduced-motion
  the percentage text, static
@ row LIVE ‖ Source
  D02:353 "Live adds the typed confirm"
@ head 1
  Frame
@ head 2
  State
@ head 3
  Word
@ head 4
  Glyph
@ head 5
  Fill
@ head 6
  Motion
@ head 7
  T2
@ head 8
  Board
@ row `CMP-123/default` ‖ Frame
  `CMP-123/default`
@ row `CMP-123/default` ‖ State
  default: the item in the account header's ⋯ menu (D02:238)
@ row `CMP-123/default` ‖ Word
  "Flatten account…"
@ row `CMP-123/default` ‖ Glyph
  —
@ row `CMP-123/default` ‖ Fill
  `color.surface.overlay`
@ row `CMP-123/default` ‖ Motion
  —
@ row `CMP-123/default` ‖ T2
  —
@ row `CMP-123/default` ‖ Board
  04
@ row `CMP-123/hover` ‖ Frame
  `CMP-123/hover`
@ row `CMP-123/hover` ‖ State
  hover
@ row `CMP-123/hover` ‖ Word
  "Flatten account…"
@ row `CMP-123/hover` ‖ Glyph
  —
@ row `CMP-123/hover` ‖ Fill
  `color.surface.hover`
@ row `CMP-123/hover` ‖ Motion
  —
@ row `CMP-123/hover` ‖ T2
  —
@ row `CMP-123/hover` ‖ Board
  04
@ row `CMP-123/focus-visible` ‖ Frame
  `CMP-123/focus-visible`
@ row `CMP-123/focus-visible` ‖ State
  focus-visible: CMP-041's inset ring
@ row `CMP-123/focus-visible` ‖ Word
  "Flatten account…"
@ row `CMP-123/focus-visible` ‖ Glyph
  —
@ row `CMP-123/focus-visible` ‖ Fill
  `color.surface.overlay`
@ row `CMP-123/focus-visible` ‖ Motion
  —
@ row `CMP-123/focus-visible` ‖ T2
  —
@ row `CMP-123/focus-visible` ‖ Board
  04
@ row `CMP-123/holding` ‖ Frame
  `CMP-123/holding`
@ row `CMP-123/holding` ‖ State
  holding: the ring with its percentage text (`15`:478)
@ row `CMP-123/holding` ‖ Word
  "40 %"
@ row `CMP-123/holding` ‖ Glyph
  —
@ row `CMP-123/holding` ‖ Fill
  `color.status.danger.default` (the ring)
@ row `CMP-123/holding` ‖ Motion
  Mo-7
@ row `CMP-123/holding` ‖ T2
  —
@ row `CMP-123/holding` ‖ Board
  04
@ row `CMP-123/armed` ‖ Frame
  `CMP-123/armed`
@ row `CMP-123/armed` ‖ State
  armed after the first discrete press (`15`:478)
@ row `CMP-123/armed` ‖ Word
  "Press again to …"
@ row `CMP-123/armed` ‖ Glyph
  —
@ row `CMP-123/armed` ‖ Fill
  `color.status.danger.default` (the outline)
@ row `CMP-123/armed` ‖ Motion
  —
@ row `CMP-123/armed` ‖ T2
  —
@ row `CMP-123/armed` ‖ Board
  04
@ row `CMP-123/typed-live` ‖ Frame
  `CMP-123/typed-live`
@ row `CMP-123/typed-live` ‖ State
  LIVE: the typed field comes first and the hold starts on a match (`15`:476)
@ row `CMP-123/typed-live` ‖ Word
  the typed word: `FLATTEN` for all accounts (`15`:2506); one account's word open (Q-17)
@ row `CMP-123/typed-live` ‖ Glyph
  —
@ row `CMP-123/typed-live` ‖ Fill
  `color.surface.raised`
@ row `CMP-123/typed-live` ‖ Motion
  —
@ row `CMP-123/typed-live` ‖ T2
  —
@ row `CMP-123/typed-live` ‖ Board
  04
@ row `CMP-123/busy` ‖ Frame
  `CMP-123/busy`
@ row `CMP-123/busy` ‖ State
  busy while its account loads: `aria-busy`, ⟳ leading the label, not T2 (D02:388)
@ row `CMP-123/busy` ‖ Word
  "Flatten account…"
@ row `CMP-123/busy` ‖ Glyph
  ⟳ `refresh`
@ row `CMP-123/busy` ‖ Fill
  `color.surface.overlay`
@ row `CMP-123/busy` ‖ Motion
  —
@ row `CMP-123/busy` ‖ T2
  —
@ row `CMP-123/busy` ‖ Board
  04
@ row `CMP-123/t2-view-as` ‖ Frame
  `CMP-123/t2-view-as`
@ row `CMP-123/t2-view-as` ‖ State
  T2 under view-as, the panel notice its reason (D02:435)
@ row `CMP-123/t2-view-as` ‖ Word
  "Flatten account…"
@ row `CMP-123/t2-view-as` ‖ Glyph
  `lock` "Not available"
@ row `CMP-123/t2-view-as` ‖ Fill
  `color.surface.overlay`
@ row `CMP-123/t2-view-as` ‖ Motion
  Mo-8
@ row `CMP-123/t2-view-as` ‖ T2
  `rbac.view_as`
@ row `CMP-123/t2-view-as` ‖ Board
  04
@ row `CMP-123/t2-viewer` ‖ Frame
  `CMP-123/t2-viewer`
@ row `CMP-123/t2-viewer` ‖ State
  T2 for a Viewer (`positions:write`)
@ row `CMP-123/t2-viewer` ‖ Word
  "Flatten account…"
@ row `CMP-123/t2-viewer` ‖ Glyph
  `lock` "Not available"
@ row `CMP-123/t2-viewer` ‖ Fill
  `color.surface.overlay`
@ row `CMP-123/t2-viewer` ‖ Motion
  Mo-8
@ row `CMP-123/t2-viewer` ‖ T2
  `rbac.permission`
@ row `CMP-123/t2-viewer` ‖ Board
  04
@ row `CMP-123/t2-read-only` ‖ Frame
  `CMP-123/t2-read-only`
@ row `CMP-123/t2-read-only` ‖ State
  T2 on a read-only grant, the account header's notice
@ row `CMP-123/t2-read-only` ‖ Word
  "Flatten account…"
@ row `CMP-123/t2-read-only` ‖ Glyph
  `lock` "Not available"
@ row `CMP-123/t2-read-only` ‖ Fill
  `color.surface.overlay`
@ row `CMP-123/t2-read-only` ‖ Motion
  Mo-8
@ row `CMP-123/t2-read-only` ‖ T2
  `rbac.account_read_only`
@ row `CMP-123/t2-read-only` ‖ Board
  04
@ row `CMP-123/t2-manager-kill-switch` ‖ Frame
  `CMP-123/t2-manager-kill-switch`
@ row `CMP-123/t2-manager-kill-switch` ‖ State
  T2 for a Manager under the kill switch while OD-11 is open (D02:421)
@ row `CMP-123/t2-manager-kill-switch` ‖ Word
  "Flatten account…"
@ row `CMP-123/t2-manager-kill-switch` ‖ Glyph
  `lock` "Not available"
@ row `CMP-123/t2-manager-kill-switch` ‖ Fill
  `color.surface.overlay`
@ row `CMP-123/t2-manager-kill-switch` ‖ Motion
  Mo-8
@ row `CMP-123/t2-manager-kill-switch` ‖ T2
  E39-D01's "Frozen — the owner closes or releases"
@ row `CMP-123/t2-manager-kill-switch` ‖ Board
  04
@ row `CMP-123/offline-rest-unreachable` ‖ Frame
  `CMP-123/offline-rest-unreachable`
@ row `CMP-123/offline-rest-unreachable` ‖ State
  offline with REST unreachable: every write T2 (D02:397)
@ row `CMP-123/offline-rest-unreachable` ‖ Word
  "Flatten account…"
@ row `CMP-123/offline-rest-unreachable` ‖ Glyph
  `lock` "Not available"
@ row `CMP-123/offline-rest-unreachable` ‖ Fill
  `color.surface.overlay`
@ row `CMP-123/offline-rest-unreachable` ‖ Motion
  Mo-8
@ row `CMP-123/offline-rest-unreachable` ‖ T2
  E17-D01's "Cannot reach server" notice
@ row `CMP-123/offline-rest-unreachable` ‖ Board
  04
@ prose
  - **Keyboard:** The ⋯ item opens CMP-044 with focus on Cancel; the confirm takes a held `Enter`
  or a second `Enter` within CMP-044's window, after the typed word on LIVE; `Escape` or blur
  disarms and key repeat never confirms (`15`:478); `Ctrl+Shift+F` opens it for one account, its
  owner still open (D02:667).
@ prose
  - **Accessible name:** Scope and effect, "Flatten account — Sub-1 · LIVE"; a T2 item keeps that
  name and its reason is the description (E09-D09:49).
@ prose
  - **Live region:** The result is polite, once, a change the user asked for; nothing speaks while
  the hold runs.
§ spec ‖ 2.5 CMP-129 PositionModeToggle
@ heading
  ### 2.5 CMP-129 PositionModeToggle
@ prose
  `15` today (`15`:1474–1481): `value` one-way or hedge, `onChange` and `disabled?` /
  `disabledReason?`; Tokens inherit CMP-003; no A11y, Variants or States line.
@ prose
  Gap: SCR-063 shows the mode as text in the account group header (D02:238, :590), CMP-129 has no
  read-only form (D02:622), and a radio group writes on every arrow key (E05-D02:464–467).
@ prose
  Proposal (hand-off A-4; RULED BQ-8): two variants.
@ prose
  `display` is the mode as text, "One-way" or "Hedge" (the hedge Side adds " · hedge", D02:180);
  it is no control and carries no reason.
@ prose
  `toggle` is CMP-003's radio group with the change held behind its own CMP-044 `standard`
  confirm, so arrow-browsing never writes; `disabled?` / `disabledReason?` give way to CMP-079's
  `allowed` + `reason`, and its reasons are the view-as leg first, then the permission leg, which
  E09-D09's chooser reads as `rbac.owner_only` "Only the owner can change account settings."
  because no other role holds `accounts:write` (E09-D09:90; `15`:1479; D02:353).
@ prose
  The open-positions state has no registered key: PROPOSED to E30-D02's owner, never bound to T2
  until merged.
@ prose
  The mode never animates: a change is a cut (Mo-8).
@ head 1
  Frame
@ head 2
  State
@ head 3
  Word
@ head 4
  Glyph
@ head 5
  Fill
@ head 6
  Motion
@ head 7
  T2
@ head 8
  Board
@ row `CMP-129/display-one-way` ‖ Frame
  `CMP-129/display-one-way`
@ row `CMP-129/display-one-way` ‖ State
  `display`, one-way: text in the group header
@ row `CMP-129/display-one-way` ‖ Word
  "One-way"
@ row `CMP-129/display-one-way` ‖ Glyph
  —
@ row `CMP-129/display-one-way` ‖ Fill
  `color.surface.canvas`
@ row `CMP-129/display-one-way` ‖ Motion
  —
@ row `CMP-129/display-one-way` ‖ T2
  —
@ row `CMP-129/display-one-way` ‖ Board
  05
@ row `CMP-129/display-hedge` ‖ Frame
  `CMP-129/display-hedge`
@ row `CMP-129/display-hedge` ‖ State
  `display`, hedge
@ row `CMP-129/display-hedge` ‖ Word
  "Hedge"
@ row `CMP-129/display-hedge` ‖ Glyph
  —
@ row `CMP-129/display-hedge` ‖ Fill
  `color.surface.canvas`
@ row `CMP-129/display-hedge` ‖ Motion
  —
@ row `CMP-129/display-hedge` ‖ T2
  —
@ row `CMP-129/display-hedge` ‖ Board
  05
@ row `CMP-129/toggle-confirm` ‖ Frame
  `CMP-129/toggle-confirm`
@ row `CMP-129/toggle-confirm` ‖ State
  `toggle`: an arrow lands on Hedge and nothing is written until the CMP-044 `standard` confirm
@ row `CMP-129/toggle-confirm` ‖ Word
  "Hedge"
@ row `CMP-129/toggle-confirm` ‖ Glyph
  —
@ row `CMP-129/toggle-confirm` ‖ Fill
  `color.surface.overlay` (the confirm)
@ row `CMP-129/toggle-confirm` ‖ Motion
  Mo-8
@ row `CMP-129/toggle-confirm` ‖ T2
  —
@ row `CMP-129/toggle-confirm` ‖ Board
  05
@ row `CMP-129/toggle-t2-owner-only` ‖ Frame
  `CMP-129/toggle-t2-owner-only`
@ row `CMP-129/toggle-t2-owner-only` ‖ State
  `toggle`, T2 for a Manager or a Viewer
@ row `CMP-129/toggle-t2-owner-only` ‖ Word
  "One-way"
@ row `CMP-129/toggle-t2-owner-only` ‖ Glyph
  `lock` "Not available"
@ row `CMP-129/toggle-t2-owner-only` ‖ Fill
  `color.surface.raised` with a `color.border.default` hairline
@ row `CMP-129/toggle-t2-owner-only` ‖ Motion
  Mo-8
@ row `CMP-129/toggle-t2-owner-only` ‖ T2
  `rbac.owner_only`
@ row `CMP-129/toggle-t2-owner-only` ‖ Board
  05
@ row `CMP-129/toggle-t2-open-positions` ‖ Frame
  `CMP-129/toggle-t2-open-positions`
@ row `CMP-129/toggle-t2-open-positions` ‖ State
  `toggle`, T2 while the account holds open positions
@ row `CMP-129/toggle-t2-open-positions` ‖ Word
  "Hedge"
@ row `CMP-129/toggle-t2-open-positions` ‖ Glyph
  `lock` "Not available"
@ row `CMP-129/toggle-t2-open-positions` ‖ Fill
  `color.surface.raised` with a `color.border.default` hairline
@ row `CMP-129/toggle-t2-open-positions` ‖ Motion
  Mo-8
@ row `CMP-129/toggle-t2-open-positions` ‖ T2
  PROPOSED to E30-D02's owner (no key bound)
@ row `CMP-129/toggle-t2-open-positions` ‖ Board
  05
@ prose
  - **Keyboard:** The `display` variant takes no Tab stop.
@ prose
  The `toggle` variant is CMP-003's radio group: arrows browse, `Enter` or `Space` opens the
  confirm, only the confirm writes and `Escape` keeps the old mode (E05-D02:464–467).
@ prose
  - **Accessible name:** The mode as text, "One-way" or "Hedge"; the toggle's radio group takes
  its host's label, and a T2 option's reason is its description, never its name.
@ prose
  - **Live region:** None of its own: the mode never speaks, and a confirmed change is its host's
  polite line, once.
§ spec ‖ 2.6 CMP-105 AccountMultiSelect (reuse contract)
@ prose
  SCR-063's account filter uses it as the picker behind "+ Filter" (D02:375): `mode="account"`
  over the server-scoped account list, a Manager's assigned accounts only, set server-side, so no
  option shows a reason; none of `profileSummary`, `onEditProfile`, the group rows or the leg
  rows.
@ prose
  Each chosen account becomes a CMP-055 chip, "Account: Sub-1 ✕", its remove a labelled
  IconButton; the use adds no new variant and no T2 ever sits on a filter (D02:433).
@ prose
  Frames on board 05: `CMP-105/filter-picker`, `CMP-105/filter-chips` and
  `CMP-105/filter-manager-scope`; hand-off A-7 adds the use to its Purpose, Props, A11y, API
  sketch, Storybook and Tests, `profileSummary` and `onEditProfile` becoming optional.
@ prose
  - **Accessible name:** A chip reads its filter, "Account: Sub-1", and its remove "Remove filter
  Account: Sub-1" (D02:375).
§ spec ‖ 2.7 CMP-049 Table (the base contract E05-D02 G12
@ prose
  Proposal (hand-off A-6): a `treegrid` variant, implied by `treegrid: true`, whose rows carry
  `level` (outermost first) and, when they hold others, `expanded`, with totals in a trailing
  `rowgroup` (D02:142); `stickyFirstColumn?: boolean|number` (`true` pins the first column,
  E11-D04's ask; a number pins that many leading columns, SCR-063's select, Env, Account and
  Symbol) and `stickyLastColumn?` (the actions column, D02:170); a `detail` line under a row,
  opened by `→` and closed by `←` (D03:130, :445).
@ prose
  Windowing stays on from 50 rows, so D01 D8's 1,000 rows (D01:284) and D03 CR-4's default sit
  inside it; the two budgets become the variant's tests: the roles, levels and indices on a 500
  -row fixture (D02:142) and a 1,000 -row window painted with no per-row layout read (D03:72).
@ prose
  - **Accessible name:** The caption names the table; a row is named by its `rowheader` cell (the
  Symbol in SCR-063, D02:142) with its level and position; a totals row by its label ("LIVE
  total").
§ spec ‖ 2.8 The routed components (deltas and change req
@ prose
  - **2.8.1 CMP-028 Callout (D03 CR-1).** Answered by the entry as it stands: `live?: "off"`
  mounts the account line with no live role, the slot's shared regions its only voices, and
  `actions?` takes Details, Review and Resolve… (`15`:314, :317; D03:472); the Purpose already
  names CMP-074 (`15`:313).
@ prose
  The reconciling, desync and locked lines are the info, warning and danger tones (D03:393–395);
  Resolve… is T2 `rbac.owner_only` for a Manager or a Viewer (D03:220).
@ prose
  - **2.8.2 CMP-078 StaleDataShade (D03 CR-2; D02 gap 12).** The grid-row variant exists
  (`15`:803); the delta is an account scope and a reason line that names the account once ("Not up
  to date · as of 14:02:11 UTC", D02:398), a change request to the owners of E17-D02 and E08-D11.
@ prose
  - **2.8.4 CMP-041 Menu, CMP-005 Checkbox and CMP-057 SplitButton (D02 gap 5).** CMP-041 already
  has the T2 item and the busy item (`15`:448–449), and CMP-005's disabled-with-reason defers to
  E09-D09 §2.2 (`15`:93), so the other environment's row checkbox is T2 inside CMP-079 (D02:145).
@ prose
  CMP-057 has no States line and its `primary` carries neither a reason nor a busy state
  (`15`:602): a change request to E05's owner for `allowed` + `reason` on the primary and a busy
  primary that keeps its label ("Closing…", "Cancelling…": `aria-busy`, the ⟳ leading it, never
  T2), with 2b for a row's own reason (D02:668, OQ-S).
@ prose
  The tertiary T2 label measures 3.98 on a dark selected row, so there it takes
  `color.text.secondary` (D02:614): a deliberate exception for the §7.4 ledger (DR-10).
@ prose
  CMP-056 gains per-tab sets, locked columns that read "Always shown" as helper text, outside the
  T2 grammar, and "Reset to default" (D02:376).
@ prose
  - **2.8.6 CMP-075 EnvBadgeLocal (D02 gap 7).** A compact per-row pill: "LIVE" or "DEMO" in
  `color.text.primary` on `color.surface.raised` with a `color.env.live` or `color.env.demo`
  border, LIVE in `font.weight.bold`, `type.ui.caption` and `radius.badge`, never colour alone
  (D02:516; D03:392); its 16 px height waits for a token (D02:619).
@ prose
  In a row the pill is `aria-hidden`, as the row's name already leads with its environment.
@ prose
  A change request to E05's owner; CMP-139 wraps the other environment's row actions with
  `guard.mismatch.row`, PROPOSED to E30-D02 (D02:616).
@ prose
  ⚠ ✓ and never a colour emoji: the statuses' `loader`, `clock`, `zap`, `circle-half`, `refresh`,
  `help-circle`, `octagon-alert`, `lock`, `link-off`, `check`, `slash`, `x`, `clock-strike` and
  `stop-square`; the tiers' `triangle` and `alert-circle`; the tags' `alert-triangle` and `flag`;
  SCR-078's `copy` and `external-link`; and a delta glyph for the price-like cells distinct from
  the Side column's ▲ / ▼ and from CMP-001's arrows (§3.5).
@ prose
  - **2.8.9 CMP-099 PrintExportBar (D03 CR-9).** SCR-078 uses the CSV form, `formats: ["csv"]`;
  running is CMP-038's busy form (`aria-busy`, the label kept), never T2; the file's first line is
  the watermark naming the exporting identity, the accounts and the time (D03:181; D03:79).
@ prose
  The record stays a contract gap: an export reaches no server, so SR-098's audit record waits for
  G7's path (D03:478; D02:605).
@ prose
  A change request to E05's owner for the progress line and the watermark.
@ prose
  - **2.8.10 CMP-079 RbacGate (D03 CR-11).** Its `reason` is a key of E09-D09 §3 (`15`:814).
@ prose
  Registered keys bind as they stand: `rbac.*`, `notice.*`, `inflight.*`, `panel.*` and E30-D02's
  `frozen`, `lockout`, `arm.*`, `refusal.*` and `guard.mismatch`.
@ prose
  `recon.*` (D03:311), `blotter.*`, `guard.mismatch.row`, `feed.*` and the `sl.note` sentence of a
  Cancel stay PROPOSED with their owners until E09-D09's owner registers them (§6; RULED BQ-13);
  no string is redefined here.
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
@ head 3
  Role here
@ row CMP-114 ‖ Name
  PositionsGrid, with its named parts the liquidation tier cell, the protection chip, the
  correction markers, the group header row, the totals row, the "Updates paused" chip and the
  Closed today line
@ row CMP-123, CMP-211 ‖ CMP
  CMP-123, CMP-211
@ row CMP-123, CMP-211 ‖ Name
  FlattenAllButton, PanicButtons
@ row CMP-123, CMP-211 ‖ Role here
  amended (A-5): Flatten account… and its dialog; CMP-211 consumed: the shell's FLATTEN ALL…
  button
@ row CMP-075, CMP-139, CMP-019 ‖ CMP
  CMP-075, CMP-139, CMP-019
@ row CMP-075, CMP-139, CMP-019 ‖ Role here
  consumed: the per-row pill, the other environment's block, the glyph names
@ row CMP-099 ‖ Role here
  consumed: SCR-078's Export CSV
@ row CMP-079 ‖ CMP
  CMP-079
@ row CMP-079 ‖ Name
  RbacGate
@ row CMP-079 ‖ Role here
  consumed: every T2
@ row CMP-001, CMP-002, CMP-009, CMP-015, CMP- ‖ Name
  Button, IconButton, Select, Skeleton, Tooltip, EmptyState, ErrorState, DensityToggle,
  KeyValueRow, InlineSpinnerText, Dialog, ConfirmDialog, Toast, ConnectionStatus,
  ReconnectOverlay, DegradedModeBanner, AuditActionTrigger, PriceInput, QtyInput,
  RiskLockoutBanner
@ row CMP-001, CMP-002, CMP-009, CMP-015, CMP- ‖ Role here
  consumed: Export CSV, the selection bar, the "N new fills" pill, Group by, the panel states, the
  T2 echo, density; SCR-078's summary and running export, the confirms, the cancel toast, the
  connection and account states, every write's audit, the cell editor
§ spec ‖ 3.1 Data-row rules
@ prose
  Every §3.2 row this spec specifies runs at most `motion.duration.normal` (200 ms), the ticket's
  cap on a data row (T Scope; D01:125 "E29-D04 caps data-row motion at 200 ms"), and never
  `motion.duration.slow`; Mo-5, Mo-7, Mo-11 and Mo-13 are their owners' recipes, cited by
  reference, and none of them is a data row's.
@ prose
  Live data never moves focus (`05`:96), a focused row never leaves (D01:408), and a focused
  control never sits inside a fading element (`docs/design/E05/E05-D02-feedback-overlays.md`:165).
§ spec ‖ 3.2 The motion table
@ row Mo-2 ‖ prefers-reduced-motion t
  prefers-reduced-motion: the row is gone at frame 0; its word ("Closed +12.40 USDT", "Filled",
  "Cancelled") was the change
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
@ prose
  It covers an order's pending → working → filled or rejected steps (the ⟳ marker, the tag and the
  "still live" words of a pending amend arrive and leave at frame 0, D02:320), a liq-tier crossing
  and the Critical row's leading accent, every B8 state of the protection chip, a PnL sign and its
  accent bar's hue, the hover, selection and focus treatments, a disclosure (Mo-10), the busy
  glyph (Mo-12), the "Updates paused" chip, the "3 new fills" pill, CMP-129's mode word and every
  T2 reason.
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
  Every gated control of §2 takes CMP-079's `allowed` + `reason` (`15`:814) and keeps its native
  role and its full label; no entry offers a `role` prop or a per-role variant, because the rule
  branches on what the session carries, never on a role name (E09-D09:34).
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
  The C-2.6 carve-out stays sendable where the target's own permission and grant allow it (§4.2).
@ prose
  The shell's view-as banner, its Exit and its countdown are E42-D02 D10's, cited and never
  restated here (E42-D02:136, :415); the countdown sits outside the live region (E42-D02:424) and
  never animates (§3.3).
@ prose
  Account labels are the fixtures' "Main", "Sub-1" and "Sub-2", ellipsised with the full label in
  the tooltip and the accessible name (D02:149).
@ prose
  A reason never repeats the account, which is named once, in its header marker and line
  (D03:321).
@ prose
  A Manager's rows, filter options, headings, totals, footer and CSV watermark name and count only
  the Manager's own accounts and legs (D02:92; D03:76).
@ prose
  After `403 account_scope_denied` the refused control is T2 `rbac.account`, sticky until the next
  `permission_change` or `GET /me` re-read, and the page echoes only an id the client itself sent
  (E09-D09:55, :158).
@ prose
  No `ret_msg` and no server `message` reach the DOM; a rejected amend shows D02's own line, and
  the exchange's text lives only behind the audited diagnostics (D02:152; D03:78, :80).
@ prose
  E09-D09's security statement holds for every entry, density, theme and story: "Every treatment
  in this document is presentation.
@ prose
  The server authorises every request against the 4-tuple of `24` §15.2 and answers `403` with a
  stable code and an audit record (`rbac.denied`) regardless of what the UI showed — a disabled
  button, a hidden route or a missing palette command is never relied on to prevent anything
  (C-2.12, C-12.4, `04` §7.3, E09-X01 D1-shared).
@ prose
  No flag, density, theme or role variant changes this (C-4.14)." (E09-D09:410; C-2.12, C-12.4)
§ spec ‖ 4.1 The gated controls (legs in order)
@ heading
  ### 4.1 The gated controls (legs in order)
@ prose
  One row per gated control of §2.
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
@ head 1
  Control
@ head 2
  Component
@ head 3
  Kind
@ head 4
  Legs (in order)
@ head 5
  Drawn exceptions
@ head 6
  Renders
@ head 7
  Source
@ row "Close ▾" and its items "Close 25 %", "C ‖ Control
  "Close ▾" and its items "Close 25 %", "Close 50 %", "Close custom size…" and "Close at limit…"
@ row "Close ▾" and its items "Close 25 %", "C ‖ Component
  CMP-114 (CMP-057 per row)
@ row "Close ▾" and its items "Close 25 %", "C ‖ Kind
  exit
@ row "Close ▾" and its items "Close 25 %", "C ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only`
@ row "Close ▾" and its items "Close 25 %", "C ‖ Drawn exceptions
  offline with REST unreachable; a Manager under the kill switch, E39-D01's "Frozen — the owner
  closes or releases" (OD-11 pending); the other environment's rows, `guard.mismatch.row`
  (PROPOSED, E30-D02)
@ row "Close ▾" and its items "Close 25 %", "C ‖ Renders
  2b on the row's SplitButton, repeated as the row menu item's second line; a scope's reason
  through its notice
@ row "Close ▾" and its items "Close 25 %", "C ‖ Source
  D02:333, :421, :429
@ row "Reverse…" ‖ Control
  "Reverse…"
@ row "Reverse…" ‖ Component
  CMP-114 (a row menu item)
@ row "Reverse…" ‖ Kind
  new exposure
@ row "Reverse…" ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only` → `rbac.env` (a LIVE row) → client
  states: `frozen`, `recon.*`, `feed.*`, `refusal.trading_disabled.*`, `arm.locked`,
  `blotter.close_in_flight`, E39-D01's lockout line, E17-D01's feed lines
@ row "Reverse…" ‖ Drawn exceptions
  —
@ row "Reverse…" ‖ Renders
  2a, the item's second line
@ row "Reverse…" ‖ Source
  D02:337, :431; PROPOSED: `recon.*` (E29-D03), `feed.*` (E17-D01), `blotter.close_in_flight`
  (E29-D03), §6
@ row "Edit price", "Edit trigger" and a quant ‖ Control
  "Edit price", "Edit trigger" and a quantity-up commit (the inline editors)
@ row "Edit price", "Edit trigger" and a quant ‖ Component
  CMP-115 (CMP-100 or CMP-101 in the cell)
@ row "Edit price", "Edit trigger" and a quant ‖ Kind
  new exposure (an entry order's amend)
@ row "Edit price", "Edit trigger" and a quant ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only` → `rbac.env` (a risk-increasing
  amend on a LIVE row) → client states: `frozen`, `recon.*`, `feed.*`, `blotter.amend_in_flight`,
  E39-D01's lockout line
@ row "Edit price", "Edit trigger" and a quant ‖ Drawn exceptions
  —
@ row "Edit price", "Edit trigger" and a quant ‖ Renders
  2a under the editor; a T2 cell keeps its value with no glyph among the numerals
@ row "Edit price", "Edit trigger" and a quant ‖ Source
  D02:345, :149; D03:208; PROPOSED: `recon.*` (E29-D03), `feed.*` (E17-D01),
  `blotter.amend_in_flight` (E29-D03), §6
@ row "Cancel ▾" (the primary) ‖ Control
  "Cancel ▾" (the primary)
@ row "Cancel ▾" (the primary) ‖ Component
  CMP-115 (CMP-057 per row)
@ row "Cancel ▾" (the primary) ‖ Kind
  exit
@ row "Cancel ▾" (the primary) ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only`
@ row "Cancel ▾" (the primary) ‖ Drawn exceptions
  offline with REST unreachable; the other environment's rows, `guard.mismatch.row` (PROPOSED,
  E30-D02); the order's own kind, never an account state: a native-stop row, `sl.note`'s first
  sentence (PROPOSED to E32-D01), and Untracked, Held and Unknown orders, `blotter.untracked`,
  `blotter.held` and `blotter.unknown` (PROPOSED, E29-D03)
@ row "Cancel ▾" (the primary) ‖ Renders
  2b on the row's SplitButton, repeated as the row menu item's second line
@ row "Cancel ▾" (the primary) ‖ Source
  D02:345, :429
@ row "Edit qty" lowering the quantity; a reco ‖ Control
  "Edit qty" lowering the quantity; a recorded take-profit's edit and Cancel
@ row "Edit qty" lowering the quantity; a reco ‖ Component
  CMP-115 (CMP-101 in the cell; the take-profit row, through `setPositionTpSl`)
@ row "Edit qty" lowering the quantity; a reco ‖ Kind
  exit (a quantity cut; a protective write)
@ row "Edit qty" lowering the quantity; a reco ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only`
@ row "Edit qty" lowering the quantity; a reco ‖ Drawn exceptions
  offline with REST unreachable; while an amend of the order, or another TP/SL write for the
  position, is in flight: `blotter.amend_in_flight` (PROPOSED, E29-D03), the twin of the server's
  refusal of a second amend and of one write per position at a time
@ row "Edit qty" lowering the quantity; a reco ‖ Renders
  2a under the editor; 2b on the take-profit row, repeated as its menu item's second line
@ row "Edit qty" lowering the quantity; a reco ‖ Source
  D02:345, :431, :435; D03:208, :222
@ row "Close selected" and "Close all in view… ‖ Control
  "Close selected" and "Close all in view…" (CMP-114); "Cancel selected" and "Cancel all in view…"
  (CMP-115)
@ row "Close selected" and "Close all in view… ‖ Component
  CMP-114 and CMP-115 (the selection bar and the toolbar, CMP-001)
@ row "Close selected" and "Close all in view… ‖ Kind
  exit (bulk)
@ row "Close selected" and "Close all in view… ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only`
@ row "Close selected" and "Close all in view… ‖ Drawn exceptions
  offline with REST unreachable; a Manager's closes under the kill switch (OD-11 pending); every
  target keeps its own row's gates
@ row "Close selected" and "Close all in view… ‖ Renders
  2a beside the button; a scope's reason through its notice
@ row "Close selected" and "Close all in view… ‖ Source
  D02:349, :433
@ row "Flatten account…" (the account header's ‖ Control
  "Flatten account…" (the account header's ⋯ and `Ctrl+Shift+F`)
@ row "Flatten account…" (the account header's ‖ Component
  CMP-123 (`scope: account`)
@ row "Flatten account…" (the account header's ‖ Kind
  exit (bulk, one account)
@ row "Flatten account…" (the account header's ‖ Legs (in order)
  `rbac.view_as` → `rbac.permission` → `rbac.account_read_only`
@ row "Flatten account…" (the account header's ‖ Drawn exceptions
  offline with REST unreachable; a Manager under the kill switch, E39-D01's "Frozen — the owner
  closes or releases" (OD-11 pending)
@ row "Flatten account…" (the account header's ‖ Renders
  2a, the menu item's second line
@ row "Flatten account…" (the account header's ‖ Source
  D02:353, :421
@ row "Edit risk caps…" (the account header's ‖ Control
  "Edit risk caps…" (the account header's ⋯); the position-mode `toggle`
@ row "Edit risk caps…" (the account header's ‖ Component
  CMP-041 item in CMP-114's group header; CMP-129
@ row "Edit risk caps…" (the account header's ‖ Kind
  an account setting (`accounts:write`; the position-mode write)
@ row "Edit risk caps…" (the account header's ‖ Legs (in order)
  `rbac.view_as` → `rbac.owner_only`
@ row "Edit risk caps…" (the account header's ‖ Drawn exceptions
  —
@ row "Edit risk caps…" (the account header's ‖ Renders
  2a, the item's second line, its admin link dropped (E09-D09:44); 2a beside the radio group, the
  open-positions reason waiting for its owner's key (§6)
@ row "Edit risk caps…" (the account header's ‖ Source
  D02:97, :353, :622; E09-D09:76, :104; `15`:1479
@ row "Resolve…" on the account line ‖ Control
  "Resolve…" on the account line
@ row "Resolve…" on the account line ‖ Component
  CMP-028 (the account line, §2.8.1)
@ row "Resolve…" on the account line ‖ Kind
  an owner action (the B19 lock)
@ row "Resolve…" on the account line ‖ Legs (in order)
  `rbac.view_as` → `rbac.owner_only` with the verb "resolve the lock" (PROPOSED, an E09-D09 §3.2
  amendment)
@ row "Resolve…" on the account line ‖ Drawn exceptions
  drawn "pending route": out of the build until its route exists
@ row "Resolve…" on the account line ‖ Renders
  2a, the reason beside it
@ row "Resolve…" on the account line ‖ Source
  D03:220, :321
@ row the row checkbox ‖ Control
  the row checkbox
@ row the row checkbox ‖ Component
  CMP-005 in CMP-114 and CMP-115
@ row the row checkbox ‖ Kind
  selection (sends nothing)
@ row the row checkbox ‖ Legs (in order)
  none: a Viewer and view-as keep it
@ row the row checkbox ‖ Drawn exceptions
  the other environment's rows, `guard.mismatch.row` (PROPOSED, E30-D02)
@ row the row checkbox ‖ Renders
  the block's section-row notice
@ row the row checkbox ‖ Source
  D02:145, :433
§ spec ‖ 4.2 Never gated
@ heading
  ### 4.2 Never gated
@ prose
  - **Exits keep their legs and nothing more.** Cancel, close and its items, the bulk closes and
  cancels, Flatten account…, a quantity cut and a recorded take-profit's edit and Cancel are never
  gated by a state key or `rbac.env`: in every account state of D02 §10.2 and §10.3, and under the
  kill switch for the Owner, they take only the legs of §4.1 (D02:412, :420; D03:82).
@ prose
  The drawn exceptions are two account states and one environment: offline with REST unreachable,
  where every write is T2 (D02:333, :431); a Manager's closes and Flatten account… under the kill
  switch, E39-D01's "Frozen — the owner closes or releases" while OD-11 is pending, a Manager's
  Cancel staying sendable there (D02:421; E39-D01:66, :687); and the other environment's rows,
  read-only behind `guard.mismatch.row` (D-4, D02:145).
@ prose
  A Cancel's own reasons — a native-stop row, an Untracked, Held or Unknown order (§4.1) — name
  what the order is, and an exit's own write in flight, `blotter.amend_in_flight` on a quantity
  cut or a recorded take-profit's edit and Cancel (§4.1), names that write; neither is the
  account's state, and a Cancel sent while the order's amend is in flight stays busy,
  "Cancelling…", until it resolves (D02:345).
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
  - **Reads and view choices carry no T2 for any role:** sorting, grouping, the FilterBar's chips,
  "+ Filter" and "Clear all", the CMP-105 account filter, selecting the session environment's
  rows, Columns, density, Chart and opening SCR-078 (D02:339, :433).
@ prose
  RBAC narrows a filter's options server-side and shows no reason there: a Manager's account
  filter lists the assigned accounts only (D02:375; RULED BQ-8).
@ prose
  Export CSV builds its file client-side, a read that stays T1; should G7's path become a
  write-method operation, it takes `rbac.view_as` alone, in 2b in the drawer's title bar (D03:181,
  :519).
@ prose
  **Nothing is hidden.** A Viewer sees every control, each write T2 with its reason (`14`:85;
  D02:433); hiding belongs to admin navigation alone (E09-D09:44).
@ prose
  The one choice not offered is Group by: Manager, for a Manager and a Viewer, a view choice, not
  a capability (D02:374).
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
@ prose
  T2 ↔ enabled and a change of reason are frame-0 cuts in both modes with no motion row (§3.3); a
  permission change re-renders every gated control where it stands, and focus stays (D02:400).
§ spec ‖ 4.3 Environment
@ heading
  ### 4.3 Environment
@ prose
  The environment is the text pill "LIVE" or "DEMO" (CMP-075): `color.text.primary` on
  `color.surface.raised` with a `color.env.live` or `color.env.demo` border, never colour alone
  (`14`:81; D02:516); CMP-075's grammar, its weight, dot and border included, is E30-D04 D7's
  (E30-D04:141), and its compact per-row form is §2.8.6's change request (D02:616).
@ prose
  In a mixed view every row's accessible name leads with its environment, group headers read "Main
  · DEMO" and the panel is named "Positions and orders — LIVE and DEMO" (D02:441).
@ prose
  The session environment's block comes first, each block with its section row, its account
  groups, its Closed today line and its own pinned totals row; a trade group never mixes
  environments, so its row carries one pill (D02:441).
@ prose
  Totals are per environment and never summed: one totals row per environment, its rowheader "LIVE
  total" (D02:142, :156).
@ prose
  The other environment's rows stay visible and read-only behind their block's notice,
  `guard.mismatch.row` (PROPOSED, E30-D02), and `Ctrl+A`, "all in view" and every bulk dialog take
  the session environment's rows only (D02:145; C-2.11).
@ prose
  The Env column exists while the session's account scope spans both environments, decided on a
  scope change and never on a row's arrival (D02:146); in a one-environment view a row carries no
  pill and its name does not lead with its environment, so the CMP-075 badge in the tab strip
  carries it (D02:146), with the group header ("Main · LIVE", D02:238) and the totals row ("LIVE
  total", D02:142).
@ prose
  The blotter offers no environment switch, and no hotkey switches the environment (C-2.11;
  E30-D02:267).
@ prose
  DEMO ↔ LIVE is a frame-0 cut in both modes, and the pill never animates (§3.3).
§ spec ‖ 5. Tokens and contrast (measured; every number f
@ head 4
  Role
@ row `t2-label` ‖ Pair
  `t2-label`
@ row `t2-reason` ‖ Pair
  `t2-reason`
@ row `t2-label-selected` ‖ Pair
  `t2-label-selected`
@ row `env-live-border` ‖ Pair
  `env-live-border`
@ row `env-live-border` ‖ fg
  `color.env.live`
@ row `env-demo-border` ‖ Pair
  `env-demo-border`
@ row `env-demo-border` ‖ fg
  `color.env.demo`
@ row `flatten-confirm-label` ‖ Pair
  `flatten-confirm-label`
@ row `t2-label-selected-tertiary` ‖ Pair
  `t2-label-selected-tertiary`
@ prose
  **Read from the table.** The closest margins pass: `bar-sell-selected` at 3.13 in dark and 3.70
  in light, `env-demo-border` at 3.64 in dark, `bar-buy-selected` at 3.84 and `no-sl-glyph` at
  3.85 in light, and `flatten-confirm-label` at 4.54 in high contrast; none of them carries
  meaning alone, since a word, a sign or a glyph does (§2).
@ prose
  On a selected row `color.text.tertiary` measures 3.98 in dark, under the text bar, so a T2 label
  on a selected row takes `color.text.secondary` at 6.24 (D02:614): the one deliberate exception
  to E09-D09's tertiary label (E09-D09:49), recorded in §7.4 and routed to E09-D09's owner.
@ prose
  LIVE and DEMO stay ΔE76 91.9 or more apart under every simulation and ΔL* 2.4 in greyscale on
  light, so the words LIVE and DEMO carry the environment (§4.3; `14`:81).
@ head 2
  Owner (cited)
§ spec ‖ 6. Copy keys
@ heading
  ## 6. Copy keys
@ prose
  Every reason and notice string the entries carry is its owner's, cited at its line; this spec
  writes no string of its own (RULED BQ-13).
@ prose
  Registered keys are E09-D09's (E09-D09:89–95, :263–273), E30-D02's state keys and the state
  vocabularies E09-D09 registers beside them, E39-D01's and E17-D01's (E09-D09:85; D02:431).
@ prose
  A PROPOSED key carries its owner on its row, here and in §4.1, and binds no T2 until its owner
  registers it, because CMP-079's `reason` is a key of E09-D09's vocabulary (`15`:814; D03:536).
@ prose
  A PROPOSED reason is one data-free sentence of at most sixty characters with a full stop
  (E09-D09:85); `sl.note`'s sentence keeps its owner's words.
@ prose
  D02 §10.2 and §10.3 still print `blotter.reconciling`, `blotter.verifying`,
  `blotter.stale_locked` and `blotter.locked_after_kill` (D02:408–410, :422); D03 replaced them
  with the `recon.*` keys (D03:552), so the entries bind `recon.*` alone, and the merged D02 text
  is its owner's to correct, never edited here (hand-off §F).
@ prose
  D03's fifth key, `recon.reduce`, sits on SCR-060's Submit alone (D03:319), on no component of
  this spec.
@ prose
  No reason names an account, a symbol, a price or a count, and none restates a registered string
  in other words (E09-D09:85; D03:321).
@ head 1
  Key
@ head 2
  String
@ head 3
  Status
@ head 4
  Owner
@ head 5
  Used on
@ row `rbac.view_as` ‖ Key
  `rbac.view_as`
@ row `rbac.view_as` ‖ String
  "Read-only while viewing as {user}."
@ row `rbac.view_as` ‖ Status
  registered (E09-D09:95)
@ row `rbac.view_as` ‖ Owner
  E09-D09
@ row `rbac.view_as` ‖ Used on
  §4.1: the first leg of every write; the panel-header notice while viewing (D02:435)
@ row `rbac.permission` ‖ Key
  `rbac.permission`
@ row `rbac.permission` ‖ String
  "Your role can't {verb}." with the verbs "change positions" and "place orders"
@ row `rbac.permission` ‖ Status
  registered (E09-D09:89, :110)
@ row `rbac.permission` ‖ Owner
  E09-D09
@ row `rbac.permission` ‖ Used on
  §4.1: the Viewer's panel-header notice, "Your role can't change positions." and "Your role can't
  place orders." (D02:433)
@ row `rbac.owner_only` ‖ Key
  `rbac.owner_only`
@ row `rbac.owner_only` ‖ String
  "Only the owner can {verb}." with the verb "change account settings"
@ row `rbac.owner_only` ‖ Status
  registered (E09-D09:90, :104)
@ row `rbac.owner_only` ‖ Owner
  E09-D09
@ row `rbac.owner_only` ‖ Used on
  §4.1: "Edit risk caps…" and CMP-129's toggle
@ row `rbac.owner_only` with the verb "resolve ‖ Key
  `rbac.owner_only` with the verb "resolve the lock"
@ row `rbac.owner_only` with the verb "resolve ‖ String
  "Only the owner can resolve the lock."
@ row `rbac.owner_only` with the verb "resolve ‖ Status
  PROPOSED: the verb, an amendment to E09-D09 §3.2 (D03:321)
@ row `rbac.owner_only` with the verb "resolve ‖ Owner
  E29-D03, for E09-D09's owner
@ row `rbac.owner_only` with the verb "resolve ‖ Used on
  §4.1: "Resolve…" on the account line
@ row `rbac.account`, `rbac.account_read_only` ‖ Key
  `rbac.account`, `rbac.account_read_only`
@ row `rbac.account`, `rbac.account_read_only` ‖ String
  "This account isn't assigned to you."; "You can view this account, not trade it."
@ row `rbac.account`, `rbac.account_read_only` ‖ Status
  registered (E09-D09:91, :92)
@ row `rbac.account`, `rbac.account_read_only` ‖ Owner
  E09-D09
@ row `rbac.account`, `rbac.account_read_only` ‖ Used on
  a refused write after `403 account_scope_denied`, sticky (E09-D09:55); §4.1: every write of an
  account held with a read-only grant, through its header's notice (D02:433)
@ row `rbac.env` ‖ Key
  `rbac.env`
@ row `rbac.env` ‖ String
  "Live trading isn't enabled for you."
@ row `rbac.env` ‖ Status
  registered (E09-D09:93)
@ row `rbac.env` ‖ Owner
  E09-D09
@ row `rbac.env` ‖ Used on
  §4.1: Reverse… and a risk-increasing amend on a LIVE row, never an exit (D02:95)
@ row `notice.panel_read_only`, `glyph.name`, ‖ Key
  `notice.panel_read_only`, `glyph.name`, `panel.no_longer_shown`, `inflight.not_sent`,
  `inflight.read_only`
@ row `notice.panel_read_only`, `glyph.name`, ‖ String
  "Read-only — {rbac sentence, first letter lower-cased}"; "Not available"; "No longer shown —
  access to {account} was withdrawn."; "Not sent — your access changed. {reason}"; "Not sent —
  read-only after three wrong codes."
@ row `notice.panel_read_only`, `glyph.name`, ‖ Status
  registered (E09-D09:263, :264, :269, :270, :273)
@ row `notice.panel_read_only`, `glyph.name`, ‖ Owner
  E09-D09
@ row `notice.panel_read_only`, `glyph.name`, ‖ Used on
  the panel-header notice for a Viewer, for view-as and offline (D02:431); the name of the CMP-019
  `lock` on every T2 control; a revoked account's rows (D02:400); the refusal at the point of
  action after a role or grant change, and after three wrong codes, where the control stays T1
  (D02:437)
@ row `frozen` ‖ Key
  `frozen`
@ row `frozen` ‖ String
  "Trading frozen by the owner at {hh:mm} UTC — new orders off. Cancel and close still work."
@ row `frozen` ‖ Status
  registered (E30-D02:422)
@ row `frozen` ‖ Owner
  E30-D02
@ row `frozen` ‖ Used on
  §4.1: the Owner's Reverse… and entry edits under the kill switch (D02:420)
@ row `arm.locked`, `arm.refused`, `refusal.tr ‖ Key
  `arm.locked`, `arm.refused`, `refusal.trading_disabled.maintenance`,
  `refusal.trading_disabled.no_active_key`, `guard.mismatch`
@ row `arm.locked`, `arm.refused`, `refusal.tr ‖ String
  "One-click trading is locked" (`arm.refused`; `arm.locked`'s description reads "one-click off —
  Ctrl+Shift+T to arm"); "Order entry is paused for maintenance"; "{account} has no active API
  key"; "Order is for a LIVE account while the workspace is DEMO"
@ row `arm.locked`, `arm.refused`, `refusal.tr ‖ Status
  registered (E30-D02:405, :406, :431, :436, :438)
@ row `arm.locked`, `arm.refused`, `refusal.tr ‖ Owner
  E30-D02
@ row `arm.locked`, `arm.refused`, `refusal.tr ‖ Used on
  §4.1: Reverse… on a Live account, before a press and after one (D02:337); new exposure under
  maintenance, and with no active key, held once by the account header (D02:395); CMP-139's
  reason, whose row form is PROPOSED below
@ row E39-D01's control string and lockout lin ‖ Key
  E39-D01's control string and lockout line (no key)
@ row E39-D01's control string and lockout lin ‖ String
  "Frozen — the owner closes or releases"; "Locked · daily loss limit · until 00:00 UTC · closing
  and reducing still work"
@ row E39-D01's control string and lockout lin ‖ Status
  registered with E39-D01's vocabulary (E09-D09:85; D02:431)
@ row E39-D01's control string and lockout lin ‖ Owner
  E39-D01 (E39-D01:66, :508)
@ row E39-D01's control string and lockout lin ‖ Used on
  §4.1: a Manager's closes and Flatten account… under the kill switch, OD-11 pending (D02:421);
  new exposure under a risk lockout (D02:423)
@ row E17-D01's feed and offline lines (no key ‖ Key
  E17-D01's feed and offline lines (no key)
@ row E17-D01's feed and offline lines (no key ‖ String
  "Price feed stale Ns"; "Rate limited — retry in N s"; "Cannot reach server"
@ row E17-D01's feed and offline lines (no key ‖ Status
  registered with E17-D01's vocabulary (E09-D09:85)
@ row E17-D01's feed and offline lines (no key ‖ Owner
  E17-D01 (E17-D01:179, :194, :197)
@ row E17-D01's feed and offline lines (no key ‖ Used on
  §4.1: new exposure on a stale symbol and in the 429 window (D02:393, :394); every write while
  offline with REST unreachable (D02:397)
@ row `recon.reconciling`, `recon.desync`, `re ‖ Key
  `recon.reconciling`, `recon.desync`, `recon.stale`, `recon.killlock`
@ row `recon.reconciling`, `recon.desync`, `re ‖ String
  "Reconciling with Bybit — new orders are paused."; "Data being verified — new orders are
  paused."; "Stale — new orders locked until the owner resolves it."; "After the kill switch — new
  orders locked until resolved."
@ row `recon.reconciling`, `recon.desync`, `re ‖ Status
  PROPOSED (D03:315–318)
@ row `recon.reconciling`, `recon.desync`, `re ‖ Owner
  E29-D03, for E09-D09's owner (D03:536)
@ row `recon.reconciling`, `recon.desync`, `re ‖ Used on
  §4.1: every new-exposure control of an account that is reconciling, being verified, on a stale
  lock or on the lock the kill switch leaves
@ row `guard.mismatch.row` ‖ Key
  `guard.mismatch.row`
@ row `guard.mismatch.row` ‖ String
  "DEMO rows are read-only in a LIVE session."
@ row `guard.mismatch.row` ‖ Status
  PROPOSED (D02:145; OQ-L, D02:661), with its converse "LIVE rows are read-only in a DEMO
  session."
@ row `guard.mismatch.row` ‖ Owner
  E30-D02
@ row `guard.mismatch.row` ‖ Used on
  §4.1 and §4.3: the other environment's block notice, its controls and its checkboxes
@ row `feed.clock_drift`, `feed.system_unknown ‖ Key
  `feed.clock_drift`, `feed.system_unknown`
@ row `feed.clock_drift`, `feed.system_unknown ‖ String
  "New orders wait until the clock is back in sync."; "New orders wait until the trading status is
  known."
@ row `feed.clock_drift`, `feed.system_unknown ‖ Status
  PROPOSED (D02:395)
@ row `feed.clock_drift`, `feed.system_unknown ‖ Owner
  E17-D01
@ row `feed.clock_drift`, `feed.system_unknown ‖ Used on
  §4.1: new exposure while the clock is out of sync, and while `system` is unknown
@ row `blotter.close_in_flight` ‖ Key
  `blotter.close_in_flight`
@ row `blotter.close_in_flight` ‖ String
  "A close for this position is already in flight."
@ row `blotter.close_in_flight` ‖ Status
  PROPOSED (D02:341); named for E29-D03, which registers none (D03:311)
@ row `blotter.close_in_flight` ‖ Owner
  E29-D03, the D02 and D03 author, for E09-D09's owner
@ row `blotter.close_in_flight` ‖ Used on
  §4.1: Reverse… and the close items while a close of the position is in flight
@ row `blotter.amend_in_flight` ‖ Key
  `blotter.amend_in_flight`
@ row `blotter.amend_in_flight` ‖ String
  "An amend is already in flight."
@ row `blotter.amend_in_flight` ‖ Status
  PROPOSED (D02:345, :431)
@ row `blotter.amend_in_flight` ‖ Owner
  E29-D03, the D02 and D03 author, for E09-D09's owner
@ row `blotter.amend_in_flight` ‖ Used on
  §4.1: an entry's edits and a quantity cut while an amend is in flight; a native stop's edit and
  a recorded take-profit's edit and Cancel while a TP/SL write for the position is pending
@ row `blotter.untracked`, `blotter.held`, `bl ‖ Key
  `blotter.untracked`, `blotter.held`, `blotter.unknown`
@ row `blotter.untracked`, `blotter.held`, `bl ‖ String
  "Not placed by CandleViewer — manage it on Bybit."; "Held for owner review — nothing can be
  sent."; "We could not confirm this order with Bybit; checking."
@ row `blotter.untracked`, `blotter.held`, `bl ‖ Status
  PROPOSED (D02:345; D01:183, :186)
@ row `blotter.untracked`, `blotter.held`, `bl ‖ Owner
  E29-D03, the D02 and D03 author, for E09-D09's owner
@ row `blotter.untracked`, `blotter.held`, `bl ‖ Used on
  §4.1: Cancel on an Untracked, a Held or an Unknown order, and an amend on an Unknown one
@ row `sl.note`, its first sentence ‖ Key
  `sl.note`, its first sentence
@ row `sl.note`, its first sentence ‖ String
  "Every position keeps a native stop — you can move it, not delete it."
@ row `sl.note`, its first sentence ‖ Status
  PROPOSED as a Cancel's reason (D02:345); its owner's words, outside the sixty-character bound
@ row `sl.note`, its first sentence ‖ Owner
  E32-D01
@ row `sl.note`, its first sentence ‖ Used on
  §4.1: Cancel on a native-stop row (C-2.6)
@ row the open-positions reason (no key yet) ‖ Key
  the open-positions reason (no key yet)
@ row the open-positions reason (no key yet) ‖ String
  none written here
@ row the open-positions reason (no key yet) ‖ Status
  PROPOSED: a key and its string, asked of E30-D02's owner (RULED BQ-8)
@ row the open-positions reason (no key yet) ‖ Owner
  E30-D02
@ row the open-positions reason (no key yet) ‖ Used on
  `CMP-129/toggle-t2-open-positions` (§2.5); no T2 binds it until it is registered
§ spec ‖ 7.1 A-rows
@ prose
  A-1 to A-4 are the whole entries of CMP-114 PositionsGrid, CMP-115 OrderRow, CMP-116 PnLBadge
  and CMP-129 PositionModeToggle (hand-off C.1 to C.4); A-5 (CMP-123 FlattenAllButton, A-5.1 to
  A-5.8, composing E33-D04 A-6, PENDING, by name), A-6 (CMP-049 Table, A-6.1 to A-6.7), A-7
  (CMP-105 AccountMultiSelect, A-7.1 to A-7.6) and A-8 (CMP-209 RightRail, one row; DR-7) are Old
  → New rows (hand-off C.5); the `16` block is a new block (hand-off C.6), its recipe owner
  E05-D03 (#3174).
§ spec ‖ 7.2 Contradictions (C-rows)
@ head 4
  Owner
@ row D04-C2 ‖ Ticket or source says
  T Scope: CMP-115 "incl. pending/optimistic and rejected variants"
@ row D04-C4 ‖ Ticket or source says
  T Scope: the ticket's motion list names a "pending shimmer"
@ row D04-C5 ‖ Ticket or source says
  T Scope times the row motion ("row insert/remove, value-change flash … correction flash") and
  leaves a state change untimed; `16`:173 counts "state change" among what transitions communicate
@ row D04-C5 ‖ Resolution
  Every state swap is a cut: status words, glyphs, fills, pills, the liq tier, the protection
  chip, T2 ↔ enabled and DEMO / LIVE change at frame 0 in both modes, `motion.duration.instant`,
  no easing (§3.3; Mo-8, Mo-10, Mo-12); no token CR (RULED BQ-11; owner approval pending (#2701))
@ row D04-C9 ‖ Ticket or source says
  E39-D03:123 and :388 (C14) read FLATTEN ALL as one gate per action, `hold` in DEMO and `typed`
  in LIVE: E39-D03:388 "in LIVE the typed word replaces the hold"; `14`:294 "plus a typed confirm
  in Live" asks for both
@ row D04-C9 ‖ Resolution
  §2.4 composes them on LIVE, the typed word first and then the hold (RULED BQ-7; `15`:476), C14's
  compose branch, said so, in the other order (typed, then hold); `FLATTEN` stays the word for
  `all-accounts` (`15`:2506), and CMP-211's `confirmMode` takes CMP-123's dialog (D04-G7)
@ row D04-C10 ‖ Resolution
  Widened by `05`:148 and D02:465 to the discrete safety events nobody requested: Near and
  Critical crossings, NO SL, a fill, a rejection, offline and reconnected (§2.1, §2.2); a row
  update is still never announced individually
§ spec ‖ 7.3 Contract gaps (G-rows)
@ head 3
  Owner
@ row D04-G4 ‖ Gap
  `closeAllPositions` states neither the order of its close and cancel nor that a failed close
  keeps its stop (D02:620): A-5.6 names the routes and shapes neither
@ row D04-G5 ‖ Gap
  CSV export has no endpoint, permission, audit action or size limit (D03:519, G7): CMP-099's
  export writes no server record yet
@ row D04-G6 ‖ Gap
  No route for "Resolve…" and no server refusal while reconciling or desync (D03:522, G10):
  CMP-028's Resolve… is drawn "pending route", and the `recon.*` pause binds this client only
@ row D04-G7 ‖ Gap
  CMP-211 offers a `group` scope (`15`:2505) and CMP-123 has none; SCR-063 draws Flatten account…
  alone (D02:155); `confirmMode` is one-valued (`15`:2505), so CMP-211 cannot carry hold and typed
  together on LIVE (D04-C9)
@ row D04-G7 ‖ Owner
  E39-D03's owner (CMP-211), with E29-T09
@ row D04-G8 ‖ Gap
  E17-D01 §6 counts an entry's price change as a risk-increasing amend and `24` §8.10 does not
  (D02:669, OQ-T): the `rbac.env` leg on "Edit price" follows E17-D01 until it rules
@ row D04-G9 ‖ Gap
  `position.reversed`, `grid.exported` and `order.diagnostics_viewed` are not in `24` §15.5
  (D02:620; `14`:1478; D03:521, G9): Reverse…, Export CSV and the diagnostics read emit no
  registered audit action yet
§ spec ‖ 7.4 Drift ledger (RULED BQ-12; owner approval pe
@ head 6
  Owner
@ row DR-3 ‖ Bound
  CMP-123 `color.status.danger`
@ row DR-10 ‖ Bound
  E09-D09's T2 label `color.text.tertiary` on a dark selected row
@ row DR-10 ‖ Replacement (exact)
  Deliberate exception (DR-10): `color.text.secondary` there, 6.24 against the 4.5 text bar, where
  tertiary measures 3.98 (§5, `t2-label-selected`)
@ row DR-12 ‖ Bound
  the reason keys `blotter.reconciling`, `blotter.verifying`, `blotter.stale_locked` and
  `blotter.locked_after_kill`, which D03 superseded, and the five `blotter.*` names D02 leaves to
  E29-D03, registered nowhere (D02:341, :345, :431)
@ row DR-12 ‖ Replacement (exact)
  `recon.reconciling`, `recon.desync`, `recon.stale` and `recon.killlock` (D03:552) in place of
  the four, bound alone here (§6); the five registered or replaced by their owner, the Old → New
  pair in hand-off Q-2
§ spec ‖ 8.1 Ticket, stories and screens
@ row The flatten confirm, defined once (§2.4; ‖ Item
  The flatten confirm, defined once (§2.4; AC3)
@ row The flatten confirm, defined once (§2.4; ‖ SCR
  SCR-063; the shell's FLATTEN ALL…
@ row The flatten confirm, defined once (§2.4; ‖ CMP
  CMP-123, CMP-044, CMP-211
@ row The fills drawer: its treegrid, its host ‖ Item
  The fills drawer: its treegrid, its host and its CSV export (§2.7, §2.8.8, §2.8.9)
§ spec ‖ 8.2 The gate tool: gates and mutations
@ row G-FLATTEN ‖ Gate
  G-FLATTEN
@ row G-FLATTEN ‖ Rule (RULED)
  hold and typed on LIVE, defined once (BQ-7; AC3)
@ row G-DISPLAY ‖ Rule (RULED)
  CMP-129's display variant: no control role, no T2 (BQ-8)
@ row G-VIEWAS ‖ Rule (RULED)
  the legs in order, view-as first; nothing hidden (BQ-13)
@ row G-EXITS ‖ Rule (RULED)
  exits never gated by a state key or `rbac.env` (BQ-13)
@ row G-ENV ‖ Gate
  G-ENV
@ row G-ENV ‖ Rule (RULED)
  totals per environment; never colour alone; no switch (BQ-13; C-2.11)
@ row G-SAFETY ‖ Rule (RULED)
  no sentence contradicts a security invariant (C-2.8, C-2.9, C-12.4)
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
  never gated by a state key (RULED BQ-13); §5 measures 27 gated pairs and 2 measured ones in
  three themes.
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
§ hand-off ‖ §B The `16` §11.4 checklist, density and themes
@ head 5
  CMP-123 (A-5)
@ row Accessible name and role ‖ `16` §11.4 line
  Accessible name and role
@ row Accessible name and role ‖ Evidence
  each entry's Accessible name line; roles `treegrid`, `row`, `rowheader` and the trailing totals
  `rowgroup` (A-6.5), CMP-044's `alertdialog` (`15`:478), CMP-003's radio group for the `toggle`,
  and none for `display` and CMP-116
@ row Live data ‖ `16` §11.4 line
  Live data
@ row Live data ‖ Evidence
  polite at most once per 2 s per field, the latest value; assertive once for a fill, a rejection,
  offline and reconnected, NO SL and a Critical crossing; never per tick (spec §2.1, §2.2;
  D02:465); CMP-116 N/A: the host's region speaks for it (spec §2.3)
@ row Motion pair ‖ Evidence
  the spec §3.2 rows and their instant twins: CMP-114 and CMP-115 Mo-1, Mo-2, Mo-3, Mo-4, Mo-8,
  Mo-10 and Mo-12; CMP-116 none of its own, the host's Mo-3; CMP-123 Mo-7 and Mo-11 by reference;
  CMP-129 Mo-8 alone; CMP-049 the consumer's Mo-1 and Mo-2 (A-6.4); CMP-105 unchanged (`15`:1100)
§ hand-off ‖ Density and theme matrix
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
  markers, the group header row, the totals row, the "Updates paused" chip and the Closed today
  line; CMP-115 OrderRow is its Working-orders sibling and CMP-123 the account header's Flatten
  account….
@ code
  - **Props**: `positions: PositionRow[]` · `groupBy: "account" | "symbol" | "trade_group" |
  "manager"` (default `account`; Group by Manager is the Owner's view choice, never T2) ·
  `columns: ColumnId[]` (per tab; select, Env, Account and Symbol always shown) · `envScope: "one"
  | "mixed"` (from the account list, never from the rows in view) · `density: "compact" |
  "comfortable"` · `selectedRowIds: string[]` · `onSelectionChange` · `rowActions:
  Record<RowActionId, { allowed: boolean; reason?: string; busy?: boolean }>` (CMP-079's pair;
  never a role prop) · `held?: { newRows: number; closedRows: number; noSl: boolean }` (the
  "Updates paused" chip) · `accounts: AccountGroup[]` (the group header rows, the totals rows and
  each block's Closed today line) · `onRowOpen(rowId)` · `onFlattenAccount(accountId)`.
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
  held row carries NO SL; the Closed today line per environment block, collapsed ("▸ Closed today
  (since 00:00 UTC) · 3 · net +40.20 USDT · incl. provisional"), expanded (its own table,
  `role="table"`, Net a CMP-116 badge), "· none" (does not expand), and a row's Net provisional or
  divergent; the panel states of E29-D02 §10.1, by name.
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
  - **Tokens**: rows `size.row.compact` / `size.row.comfortable`; cells `space.inset.sm` /
  `space.inset.md`; words `type.ui.body`, numerals `type.num.base`, chips and tags
  `type.ui.caption` with `radius.badge` and `space.inset.xs` (Deliberate exception (DR-9): no
  height token, E29-D04 §7.4); fills `color.surface.raised`, `color.surface.hover` and
  `color.surface.selected`, group headers `color.surface.canvas`, totals `color.surface.overlay`;
  focus `color.focus.ring` with `border.focus`; the tier glyphs `color.text.secondary`,
  `color.status.warning.strong` and `color.status.danger.strong`; tags `color.status.info.subtle`,
  `color.status.warning.subtle` and `color.status.danger.subtle` under `color.text.primary`; stale
  rows `color.data-confidence.stale.surface` and `color.data-confidence.stale.text`; the
  environment pill `color.env.live` / `color.env.demo`; the T2 look per CMP-079, its label
  `color.text.secondary` on a dark selected row (Deliberate exception (DR-10), E29-D04 §7.4); the
  Closed today line `color.surface.canvas`; forced colours per E29-D02 §12 (D02:527). (Replaces
  the two bare status families of the old Tokens line.)
@ code
  - **API sketch**: `interface PositionRow { id: string; accountId: string; env: "live" | "demo";
  symbol: string; side: "long" | "short"; positionIdx: 0 | 1 | 2; size: string; entryPrice:
  string; markPrice: string; liqPrice: string | null; unrealizedPnl: string; rPnlToday: string; r:
  string | null; leverage: string; marginMode: "cross" | "isolated" | "portfolio"; positionMode:
  "one-way" | "hedge"; protection: { state: "protected" | "attaching" | "verifying" | "amending" |
  "naked" | "naked_unrecoverable"; frozen: boolean }; adlRank: number | null; liqTier: "none" |
  "watch" | "near" | "critical"; markers?: RowMarkerId[]; closed?: { net: string } }`, `closed`
  set on a lingering closed row with its realised net (D01:408), `RowMarkerId` being the seventeen
  row markers of E29-D02 and E29-D03; `interface AccountGroup { id: string; label: string; env:
  "live" | "demo"; positionMode: "one-way" | "hedge"; state?: string; rPnlToday: string;
  closedToday?: { count: number; net: string; provisional: boolean } }`, `state` being the
  account's D02 §10.2 marker key; money and price fields are the generated `packages/protocol`
  decimal strings, never `number`.
@ code
  - **Data contract**: `positions` from the private `positions` WS topic (`23` §15.2
  `PositionUpdate`) merged with the REST position-list snapshot; `positionMode` from
  `ExchangeAccount.position_mode`; the tier derived client-side from the mark, the liquidation
  price and the entry buffer (E29-D02 §5.3); `adlRank` is on no frame yet and its column stays out
  of view (a contract gap).
@ code
  - **Tests**: unit, visual, axe, keyboard row and cell navigation, the treegrid roles, levels and
  indices on a 500 -row fixture, the live-region cadence (never per tick), the T2 tests (view-as
  first, `aria-disabled`, no audit or analytics on a T2 press), busy is never T2, performance
  (1,000 rows at the frame budget).
§ hand-off ‖ C.2 A-2 — CMP-115 OrderRow
@ code
  - **Props**: `order: OrderRowData` · `rowActions: Record<"cancel" | "editPrice" | "editTrigger"
  | "editQty", { allowed: boolean; reason?: string; busy?: boolean }>` (CMP-079's pair) ·
  `onCancel` · `onAmend(field, value)` · `amend?: { moment: "editing" | "pending" | "unconfirmed"
  | "rejected"; value: string }` · `onDismissRejected`.
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
  - **A11y**: Keyboard: CMP-114's treegrid model; `Enter`, `F2` or a double-click opens the cell
  editor (CMP-100 or CMP-101 in the cell), `↑` / `↓` step a tick or a lot, `Enter` alone commits
  and `Escape`, `Tab` or a click elsewhere restores the live value; Accessible name: in a mixed
  view the environment leads, then the state word with its glyph named once, then the type with
  its purpose, price, quantity and account, the State cell's whole line in the description; Live
  region: row updates are never announced individually; filled and rejected are assertive, once,
  and so is a rejected amend; "Amend confirmed: price 2,495.00." is polite, once; the pending tag,
  the age and the counters never speak.
@ code
  - **API sketch**: `interface OrderRowData { id: string; accountId: string; env: "live" | "demo";
  symbol: string; side: "buy" | "sell"; type: string; purpose: string; price: string | null;
  triggerPrice: string | null; qty: string; filledQty: string; avgFillPrice: string | null;
  timeInForce: string; reduceOnly: boolean; closeOnTrigger: boolean; createdAt: string | null;
  parent: string | null; status: OrderStatus; nativeStop: boolean; markers?: RowMarkerId[] }`,
  `OrderStatus` being the fifteen D01 D2 states (`submitting`, `submitted`, `triggered`,
  `partially_filled`, `cancel_pending`, `amend_pending`, `unknown`, `quarantined`, `held`,
  `untracked`, `filled`, `cancelled`, `rejected`, `expired`, `killed`); decimals as the generated
  `packages/protocol` strings.
@ code
  - **Data contract**: the private `orders` WS topic (`23` §15.1 `OrderUpdate`, never throttled)
  merged with the REST open-orders snapshot; `lifecycle_state` maps to the D01 D2 word, null or
  unmapped to "Working — state not reported"; a pending amend waits for the `change: "amend"`
  frame and a native stop's edit for the read that shows it; the exchange's text never reaches the
  row (`getOrderDiagnostics` only).
@ code
  - **Tests**: unit (the fifteen-word map; null reads "Working — state not reported"), visual,
  axe, keyboard (the editor commits on `Enter` alone), the pending test (the live value and "still
  live" stay until the frame), the T2 and busy tests, the live-region cadence.
§ hand-off ‖ C.3 A-3 — CMP-116 PnLBadge
@ code
  - **Tier**: Atom (trading) · **Purpose**: a signed money value (unrealised and realised PnL, R,
  fees, funding) whose digits stay neutral and whose sign is text; its hue rides on a 2 px accent
  bar.
@ code
  - **A11y**: Keyboard: none, the badge is not interactive; Accessible name: the sign and the
  value in words as visually hidden text, never an `aria-label` on the span: "profit 8.00 USDT",
  "loss 121.50 USDT", "fee paid 3.49 USDT", "funding received 0.84 USDT", a null R "R unavailable:
  no stop price"; the bar is `aria-hidden`; Live region: none of its own; the host's polite region
  at most once per 2 s per field, latest value only, never per tick.
@ code
  - **Data contract**: the host passes the server's figure (unrealised PnL from the position
  frame, realised PnL from E29-S06's composition, fees and funding from `executions`); the badge
  formats and computes nothing.
§ hand-off ‖ C.4 A-4 — CMP-129 PositionModeToggle
@ heading
  ### C.4 A-4 — CMP-129 PositionModeToggle
@ prose
  Replaces `15`:1474–1481 (D02 gap 13 and E05-D02 D5; spec §2.5).
@ code
  ### CMP-129 PositionModeToggle (One-Way/Hedge)
@ code
  - **Tier**: Molecule (trading) · **Purpose**: the account's position mode, shown as text in
  SCR-063's account group header, or changed behind its own confirm.
@ code
  - **Props**: `value: "one-way" | "hedge"` · `variant: "display" | "toggle"` (default `display`)
  · `allowed?: boolean` · `reason?: string` (CMP-079's pair, `toggle` only) ·
  `onRequestChange(value)` · `onConfirm`.
@ code
  - **Variants**: `display`: the word as text, read-only, outside the Tab order, with neither a
  control role nor a reason. `toggle`: CMP-003's radio group, its change held behind a CMP-044
  `standard` confirm, so arrow-browsing never writes.
@ code
  - **States**: `display`: one-way, hedge. `toggle`: default, hover, focus-visible, an option
  arrowed but unwritten, the confirm open, T2 (the view-as leg first, then the permission leg,
  read as `rbac.owner_only` for `accounts:write`; the open-positions reason PROPOSED to E30-D02's
  owner, no key bound), busy while the write is in flight.
@ code
  - **A11y**: Keyboard: `display` takes no Tab stop; `toggle` is CMP-003's radio group, where
  arrows browse, `Enter` or `Space` opens the confirm, only the confirm writes and `Escape` keeps
  the old mode; Accessible name: the mode as text, "One-way" or "Hedge"; the radio group takes its
  host's label and a T2 option's reason is its description; Live region: none of its own; a
  confirmed change is the host's polite line, once.
@ code
  - **Tokens**: `display`: `type.ui.body` in `color.text.primary` on the header's
  `color.surface.canvas`. `toggle`: CMP-003's, with the T2 look per CMP-079
  (`color.text.tertiary`, `color.text.secondary`, `color.surface.raised`, `color.border.default`),
  never `opacity.disabled`.
@ code
  - **Data contract**: reads the position mode from `ExchangeAccount.position_mode` (REST); the
  `toggle` writes it through the account-config endpoint after the confirm, the Owner's alone
  (`accounts:write`).
@ code
  - **Storybook**: DisplayOneWay, DisplayHedge, ToggleConfirm, T2OwnerOnly, T2OpenPositions (its
  reason PROPOSED); each dark and light × compact and comfortable.
@ code
  - **Tests**: unit, visual, axe (`display` exposes no role), keyboard (arrows never write; only
  the confirm sends), the T2 test.
@ code
  - **Motion spec**: none: a mode change is a cut at frame 0 (E29-D04 §3.2, Mo-8), the same under
  `prefers-reduced-motion`.
@ code
  - **Design (DS spec):** [E29-D04.md](../design/E29/E29-D04.md) §2.5 (E29-D04; owner approval
  pending).
§ hand-off ‖ C.5 Table A — Old (verbatim at `6fc8aacc6`) → Ne
@ heading
  ### C.5 Table A — Old (verbatim at `6fc8aacc6`) → New, field by field
@ prose
  A-5 composes with E33-D04 A-6 (PENDING, by name; RULED BQ-7): A-5.1 replaces the Old Purpose's
  "`hold` or `typed`" choice with the composite and appends after E33-D04 A-6.1's sentence,
  whichever lands first, and A-5.5 is E33-D04 A-6.2's own replacement, so the second to land is a
  no-op.
@ prose
  A "new bullet" row inserts the bullet after the line its Old cell sits on.
@ head 1
  A
@ head 2
  Component
@ head 3
  Field (`15`:line)
@ head 4
  Old (verbatim)
@ head 5
  New
@ row A-5.1 ‖ A
  A-5.1
@ row A-5.1 ‖ Component
  CMP-123
@ row A-5.1 ‖ Field (`15`:line)
  Tier · Purpose (`15`:1405)
@ row A-5.1 ‖ Old (verbatim)
  **Tier**: Molecule (trading, risk-critical) · **Purpose**: global panic-button — closes all
  positions and cancels all working orders for the active scope, gated by ConfirmDialog `hold` or
  `typed` variant.
@ row A-5.1 ‖ New
  the Old text with "gated by ConfirmDialog `hold` or `typed` variant" replaced by "gated by
  CMP-044 `hold`, and on LIVE by the typed word as well (E29-D04 §2.4)", then (after E33-D04
  A-6.1's sentence once that row has landed; PENDING): Two scopes: `account`, SCR-063's Flatten
  account… in each account group header's ⋯ menu, and `all-accounts`, the shell's FLATTEN ALL…,
  whose button is CMP-211 and whose dialog is this entry's. Its confirm, CMP-044 `hold` with the
  typed word first on LIVE (`FLATTEN` for `all-accounts`), is defined once here and referenced,
  never restated, by E30, E31 and E39.
@ row A-5.2 ‖ A
  A-5.2
@ row A-5.2 ‖ Component
  CMP-123
@ row A-5.2 ‖ Field (`15`:line)
  Props (`15`:1406)
@ row A-5.2 ‖ Old (verbatim)
  `scope: "account"|"all-accounts"`
@ row A-5.2 ‖ New
  `scope: "account" | "all-accounts"` · `env: "live" | "demo"` (the account's; E29-D04 §2.4's
  confirm keys on it) · `allowed: boolean` · `reason?: string` (CMP-079's pair; never a role prop)
  · `busy?: boolean` (the account loading: `aria-busy`, never T2)
@ row A-5.3 ‖ A
  A-5.3
@ row A-5.3 ‖ Component
  CMP-123
@ row A-5.3 ‖ Field (`15`:line)
  Variants, States (new bullets after `15`:1406)
@ row A-5.3 ‖ Old (verbatim)
  `onConfirm`.
@ row A-5.3 ‖ New
  the Old text, then two new bullets. **Variants**: `account` (SCR-063's Flatten account…) and
  `all-accounts` (the shell's FLATTEN ALL…, its button CMP-211), each on DEMO or LIVE (E29-D04
  §2.4's confirm table). **States**: default, hover, focus-visible; the CMP-044 dialog restating
  the account, its environment, the positions it closes and the orders it cancels, stops
  "cancelled with the position"; holding (CMP-044's ring with its percentage text); armed ("Press
  again to …"); the typed word on LIVE (`FLATTEN` for `all-accounts`); busy while the account
  loads (`aria-busy`, never T2); out of the ⋯ menu while the account's snapshot failed; T2 for
  view-as, a Viewer and a read-only grant, and for a Manager under the kill switch while OD-11 is
  open; offline with REST unreachable (T2); the result, one `BulkAccountResult` line per account
  with "Retry failed".
@ row A-5.4 ‖ A
  A-5.4
@ row A-5.4 ‖ Component
  CMP-123
@ row A-5.4 ‖ Field (`15`:line)
  A11y (`15`:1407)
@ row A-5.4 ‖ Old (verbatim)
  CMP-044 composition, always keyboard-operable (never a mouse-hold-only gate).
@ row A-5.4 ‖ New
  the Old text, then: Keyboard: the item opens CMP-044 with focus on Cancel; the confirm takes a
  held `Enter` or a second `Enter` within CMP-044's window, after the typed word where E29-D04
  §2.4 asks for it; `Escape` or blur disarms and key repeat never confirms. Accessible name: scope
  and effect, "Flatten account — {account} · {environment}"; a T2 item keeps it and its reason is
  the description. Live region: the result is polite, once; nothing speaks while the hold runs.
@ row A-5.5 ‖ A
  A-5.5
@ row A-5.5 ‖ Component
  CMP-123
@ row A-5.5 ‖ Field (`15`:line)
  Tokens (`15`:1408)
@ row A-5.5 ‖ Old (verbatim)
  `color.status.danger`.
@ row A-5.5 ‖ New
  `color.status.danger.default`. (The same replacement as E33-D04 A-6.2, PENDING: whichever lands
  first applies and the other is then a no-op.)
@ row A-5.6 ‖ A
  A-5.6
@ row A-5.6 ‖ Component
  CMP-123
@ row A-5.6 ‖ Field (`15`:line)
  Data contract (`15`:1409)
@ row A-5.6 ‖ Old (verbatim)
  Bybit `/v5/order/cancel-all` + market-close per position
@ row A-5.6 ‖ New
  the server's routes, their names E39-D03 C9's content fix (its owner's, E39-D03:383): for
  `scope: "account"`, `cancelAllOrders` for the account with `exclude_reduce_only: true`, then
  `closeAllPositions` with `cancel_open_orders: false`, in one confirmed gesture with an
  `Idempotency-Key` each; stops end with their position, never as separate cancels, and a failed
  cancel does not hold the close back
@ row A-5.7 ‖ A
  A-5.7
@ row A-5.7 ‖ Component
  CMP-123
@ row A-5.7 ‖ Field (`15`:line)
  Storybook (`15`:1410)
@ row A-5.7 ‖ Old (verbatim)
  AccountScope, AllAccountsScope.
@ row A-5.7 ‖ New
  AccountScope, AllAccountsScope, DemoHold, LiveHoldAndTyped, Armed, Busy, T2ViewAs, T2Viewer,
  T2ReadOnly, T2ManagerKillSwitch, OfflineRestUnreachable, Result, ReducedMotion; each dark and
  light × compact and comfortable.
@ row A-5.8 ‖ A
  A-5.8
@ row A-5.8 ‖ Component
  CMP-123
@ row A-5.8 ‖ Field (`15`:line)
  Tests (`15`:1411), then Motion spec and Design
@ row A-5.8 ‖ Old (verbatim)
  unit, visual, axe, keyboard-only confirm path test.
@ row A-5.8 ‖ New
  the Old text, then: on LIVE the hold starts once the typed word matches; key repeat never
  confirms; view-as is the first leg; a T2 press emits no audit or analytics; busy is never T2;
  the reduced-motion twin shows the percentage text, static. Then two new bullets. **Motion
  spec**: Mo-7, CMP-044's ring by reference (E29-D04 §3.2). **Design (DS spec):** E29-D04 §2.4
  (E29-D04; owner approval pending).
@ row A-6.1 ‖ A
  A-6.1
@ row A-6.1 ‖ Component
  CMP-049
@ row A-6.1 ‖ Field (`15`:line)
  Tier · Purpose (`15`:526)
@ row A-6.1 ‖ Old (verbatim)
  PositionsGrid (CMP-107)
@ row A-6.1 ‖ New
  PositionsGrid (CMP-114)
@ row A-6.2 ‖ A
  A-6.2
@ row A-6.2 ‖ Component
  CMP-049
@ row A-6.2 ‖ Field (`15`:line)
  Props (`15`:527)
@ row A-6.2 ‖ Old (verbatim)
  `caption: string` · `loading?: boolean` · `error?: {message, onRetry}`.
@ row A-6.2 ‖ New
  the Old text, then: `treegrid?: boolean` (implies `grid`; rows carry `level`, outermost first,
  and a row that holds others `expanded`) · `stickyFirstColumn?: boolean | number` (`true` pins
  the first column; a number pins that many leading columns) · `stickyLastColumn?: boolean` (an
  actions column) · `detail?: (row: T) => ReactNode` (a detail line under a row, opened by `→`)
@ row A-6.3 ‖ A
  A-6.3
@ row A-6.3 ‖ Component
  CMP-049
@ row A-6.3 ‖ Field (`15`:line)
  Variants (`15`:528)
@ row A-6.3 ‖ Old (verbatim)
  forced by `grid` for a static table).
@ row A-6.3 ‖ New
  the Old text, then: treegrid (the APG Treegrid pattern: rows nest by `level`, `→` expands and
  `←` collapses a row that holds others, a detail line opens under its row; implied by `treegrid`;
  SCR-063, SCR-078 and E11-D04's chart table).
@ row A-6.4 ‖ A
  A-6.4
@ row A-6.4 ‖ Component
  CMP-049
@ row A-6.4 ‖ Field (`15`:line)
  States (`15`:529)
@ row A-6.4 ‖ Old (verbatim)
  or badges an inline IconButton, 2b).
@ row A-6.4 ‖ New
  the Old text, then: with `treegrid`, a row that holds others is expanded or collapsed
  (`aria-expanded`), a detail line is open or closed and totals sit in a trailing `rowgroup`; the
  base has no row motion, a consumer's insert and exit being E29-D04 Mo-1 and Mo-2.
@ row A-6.5 ‖ A
  A-6.5
@ row A-6.5 ‖ Component
  CMP-049
@ row A-6.5 ‖ Field (`15`:line)
  A11y (`15`:530)
@ row A-6.5 ‖ Old (verbatim)
  one polite live region for sort, filter, selection and load results.
@ row A-6.5 ‖ New
  the Old text, then: with `treegrid`, `role="treegrid"`, `aria-level` per layer, `aria-expanded`
  on a row that holds others, `aria-rowcount` and `aria-rowindex` across the window, the first
  cell a `rowheader` and totals in a trailing `rowgroup`. Keyboard: one roving stop; arrows by row
  and cell, `→` expands and `←` collapses, `Home` / `End`, `PageUp` / `PageDown`, `Space` selects,
  `Enter` opens a detail line or activates the cell's control, `Shift+F10` the row menu.
  Accessible name: the caption names the table, a row its `rowheader` cell with its level and
  position. Live region: a consumer's row updates are never announced individually; the base keeps
  its one polite region for results.
@ row A-6.6 ‖ A
  A-6.6
@ row A-6.6 ‖ Component
  CMP-049
@ row A-6.6 ‖ Field (`15`:line)
  Storybook (`15`:532)
@ row A-6.6 ‖ Old (verbatim)
  FilteredEmpty, Reflow.
@ row A-6.6 ‖ New
  FilteredEmpty, Reflow, Treegrid, TreegridExpanded, StickyLeadColumns, DetailLines,
  TotalsRowgroup.
@ row A-6.7 ‖ A
  A-6.7
@ row A-6.7 ‖ Component
  CMP-049
@ row A-6.7 ‖ Field (`15`:line)
  Tests (`15`:533), then Design
@ row A-6.7 ‖ Old (verbatim)
  performance test (scroll 10k rows @60fps).
@ row A-6.7 ‖ New
  the Old text, then: with `treegrid`, the roles, levels and indices asserted on a 500 -row
  fixture, a 1,000 -row window painted with no per-row layout read, and expand and collapse by
  keyboard. Then a new bullet: **Design (DS spec):** E29-D04 §2.7 (E29-D04; owner approval
  pending).
@ row A-7.1 ‖ A
  A-7.1
@ row A-7.1 ‖ Component
  CMP-105
@ row A-7.1 ‖ Field (`15`:line)
  Tier · Purpose (`15`:1091)
@ row A-7.1 ‖ Old (verbatim)
  the account / trade-group selector of SCR-061 (E30-D03 §8).
@ row A-7.1 ‖ New
  the Old text, then: Also SCR-063's account-filter picker, reused by contract (E29-D04 §2.6):
  `mode="account"` over the server-scoped account list, without `profileSummary`, `onEditProfile`,
  group rows or leg rows; each chosen account becomes a CMP-055 chip, "Account: Sub-1 ✕".
@ row A-7.2 ‖ A
  A-7.2
@ row A-7.2 ‖ Component
  CMP-105
@ row A-7.2 ‖ Field (`15`:line)
  Storybook (`15`:1099)
@ row A-7.2 ‖ Old (verbatim)
  HighContrast, ReducedMotion.
@ row A-7.2 ‖ New
  HighContrast, ReducedMotion, FilterPicker, FilterManagerScope.
@ row A-7.3 ‖ A
  A-7.3
@ row A-7.3 ‖ Component
  CMP-105
@ row A-7.3 ‖ Field (`15`:line)
  Tests (`15`:1100)
@ row A-7.3 ‖ Old (verbatim)
  unit (cap enforcement), visual, axe, keyboard multi-select
@ row A-7.3 ‖ New
  the Old text, then: the filter use (a Manager's options are the assigned accounts only, set
  server-side; no T2 on a filter)
@ row A-7.4 ‖ A
  A-7.4
@ row A-7.4 ‖ Component
  CMP-105
@ row A-7.4 ‖ Field (`15`:line)
  Props (`15`:1092)
@ row A-7.4 ‖ Old (verbatim)
  `accounts: {id,label,badge:ProfileBadgeProps,selected,profileSummary}[]` · `onToggle` ·
  `onSelectAll` · `onEditProfile(accountId)`
@ row A-7.4 ‖ New
  `accounts: {id,label,badge:ProfileBadgeProps,selected,profileSummary?}[]` · `onToggle` ·
  `onSelectAll` · `onEditProfile?(accountId)` (`profileSummary` and `onEditProfile` optional:
  SCR-063's account-filter picker passes neither, E29-D04 §2.6)
@ row A-7.5 ‖ A
  A-7.5
@ row A-7.5 ‖ Component
  CMP-105
@ row A-7.5 ‖ Field (`15`:line)
  A11y (`15`:1095)
@ row A-7.5 ‖ Old (verbatim)
  `aria-describedby` → the shared reason).
@ row A-7.5 ‖ New
  the Old text, then: the account-filter use (E29-D04 §2.6). Keyboard: `Alt+↓` or `Enter` opens,
  `↑` / `↓`, `Home` / `End`, `Space` toggles, `Escape` closes and returns focus, and each chip's
  remove is its own IconButton. Accessible name: a chip reads "Account: Sub-1" and its remove
  "Remove filter Account: Sub-1". Live region: none of its own; the table's one polite region
  speaks the filtered result once.
@ row A-7.6 ‖ A
  A-7.6
@ row A-7.6 ‖ Component
  CMP-105
@ row A-7.6 ‖ Field (`15`:line)
  API sketch (`15`:1097)
@ row A-7.6 ‖ Old (verbatim)
  profileSummary: string }>; onToggle: (id: string) => void; onSelectAll: () => void;
  onEditProfile: (id: string) => void;
@ row A-7.6 ‖ New
  profileSummary?: string }>; onToggle: (id: string) => void; onSelectAll: () => void;
  onEditProfile?: (id: string) => void;
@ row A-8 ‖ A
  A-8
@ row A-8 ‖ Component
  CMP-209
@ row A-8 ‖ Field (`15`:line)
  Tokens (`15`:2489)
@ row A-8 ‖ Old (verbatim)
  `motion.drawer`
@ row A-8 ‖ New
  `motion.duration.normal` with `motion.easing.decelerate` to open and `motion.easing.accelerate`
  to close, as CMP-046 (`15`:499); a docked drawer that reflows its host arrives in one frame;
  `prefers-reduced-motion`: at frame 0 (DR-7; E29-D04 Mo-6)
§ hand-off ‖ C.6 The `16` block (copy-ready; recipe owner E05
@ code
  | state swap (status word, glyph, fill, pill, liq tier, protection chip, T2 ↔ enabled, DEMO /
  LIVE; a disclosure; a row's busy glyph) | at frame 0; `prefers-reduced-motion`: the same cut at
  frame 0 | none | E29-D04 Mo-8, Mo-10, Mo-12 |
§ hand-off ‖ §D Storybook stories per entry
@ row CMP-114 PositionsGrid ‖ Stories
  §C.1's Storybook line (RULED BQ-4): the default and grouped grids, the mixed environments, the
  liq tiers, the protection chip, the row markers, selection, the paused chip, the Closed today
  line, the narrow dock, the empty and loading panels, the Viewer's T2 and the reduced-motion
  readings
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
@ row CMP-123 FlattenAllButton ‖ Built in
  E29-S01 for `scope: account`; the shell's host of `scope: all-accounts` (E39)
@ row CMP-129 PositionModeToggle ‖ Stories
  §C.4's Storybook line (RULED BQ-8): the two display stories, the toggle's confirm and its T2
  frames, the open-positions one with its reason PROPOSED
@ prose
  A T2 story shows the reason node and the `lock` and never the `disabled` attribute (spec §4); a
  ReducedMotion story sets `data-motion="reduce"` and shows every reading at frame 0 (spec §3.6).
@ prose
  The story code belongs to the implementing stories (T Out of scope).
§ hand-off ‖ §E Test hooks
@ row CMP-114 PositionsGrid ‖ Tests
  axe with no serious or critical violation (`15`:41); the treegrid's accessibility tree, its
  roles, levels and indices on a 500 -row fixture (D02:142); the keyboard model of D02 §11.1
  (D02:447); the live-region cadence: the focused row's changed values and the environment totals
  at most once per 2 s per field, and row updates never announced individually (D02:465); the
  environment test: totals per environment never summed, the Env column only on a scope change
  (D02:146, :156); the exits test of spec §4.2; the T2 test of spec §4.1; every
  `prefers-reduced-motion` reading at frame 0 (spec §3.2)
@ row CMP-115 OrderRow ‖ Tests
  axe; CMP-114's treegrid keyboard, `Enter` or `F2` opening the editor and only `Enter` committing
  (D02:303); the live-region cadence: filled and rejected assertive once, every other status
  change silent (D02:465); the environment (in a mixed view), then the status word, leading the
  row's name; pending never drawn as confirmed, the confirmed value staying with "still live"
  until Bybit answers (D02:320, :325); the T2 test of spec §4.1; every `prefers-reduced-motion`
  reading at frame 0
@ row CMP-116 PnLBadge ‖ Tests
  axe; the accessible reading as visually hidden text, never an `aria-label` (spec §2.3); the sign
  as text in greyscale and under deuteranopia (spec §5); no live region of its own
@ row CMP-123 FlattenAllButton ‖ Entry
  CMP-123 FlattenAllButton
@ row CMP-123 FlattenAllButton ‖ Tests
  axe; the keyboard-only confirm path of spec §2.4, key repeat never confirming; the result line
  polite once; the exits test: sendable for the Owner in every account state (spec §4.2); the T2
  test of spec §4.1's flatten row; the hold's static `prefers-reduced-motion` reading (spec §3.2)
@ row CMP-129 PositionModeToggle ‖ Tests
  axe; the display variant is no Tab stop and has no control role (spec §2.5); arrows browse the
  toggle and only its confirm writes (E05-D02 D5); the toggle's T2 frames as spec §4.1's toggle
  row
@ row CMP-105 AccountMultiSelect, the filter u ‖ Tests
  E30-D04's tests, unchanged (E30-D04:366), and the filter use: a Manager's options are the
  assigned accounts only, set server-side, and no T2 sits on a filter (Table A A-7.3; spec §4.2)
@ row CMP-049 Table ‖ Tests
  the `15` tests, unchanged (`15`:533), and with `treegrid` the roles, levels and indices on a 500
  -row fixture, a 1,000 -row window painted with no per-row layout read, and expand and collapse
  by keyboard (Table A A-6.7)
@ prose
  **The T2 test** (every row of spec §4.1): the legs fire in their order, view-as first; the
  control keeps its role and its full label with `aria-disabled="true"`, never the `disabled`
  attribute; its reason node is in the DOM at mount; a press sends nothing, re-shows the reason
  once, politely, and emits no audit or analytics (E09-D09:228, :243; `15`:819).
@ prose
  **The exits test** (spec §4.2): in every account state of D02 §10.2 and §10.3 the Owner's
  Cancel, Close, the bulk closes and cancels and Flatten account… send; the drawn exceptions of
  spec §4.2 are the only T2 on an exit (D02:412).
§ hand-off ‖ §F Open items
@ prose
  - **Q-1** The `recon.*` keys (D03:315–319) wait for E09-D09's owner to register them beside
  E30-D02's (D03:536, :619); until then they stay PROPOSED on every row that names them, and
  CMP-079 cannot carry them (`15`:814).
@ prose
  Owner: E09-D09's owner, with E29-D03 as the vocabulary owner.
@ prose
  - **Q-2** The five `blotter.*` keys D02 names for E29-D03 (D02:341, :345, :431) are registered
  nowhere, since D03 registers only `recon.*` (D03:311); D02's four superseded keys still print at
  D02:408–410 and :422 (D03:552).
@ prose
  The copy-ready pair for that author (spec DR-12): in D02 §10.2 and §10.3, `blotter.reconciling`
  → `recon.reconciling`, `blotter.verifying` → `recon.desync`, `blotter.stale_locked` →
  `recon.stale` and `blotter.locked_after_kill` → `recon.killlock`, each with D03's string
  (D03:315–318).
@ prose
  Owner: the E29-D02 and E29-D03 author, to register or replace them with E09-D09's owner and to
  correct the merged D02 text.
@ prose
  - **Q-3** `guard.mismatch.row` and its converse, the other environment's block notice (D02:145):
  a row form of `guard.mismatch` (OQ-L, D02:661).
@ prose
  Owner: E30-D02's owner.
@ prose
  - **Q-4** `feed.clock_drift` and `feed.system_unknown` (D02:395, :620).
@ prose
  Owner: E17-D01's owner.
@ prose
  - **Q-5** `sl.note`'s first sentence as the native-stop row's Cancel reason (D02:345).
@ prose
  Owner: E32-D01's owner.
@ prose
  - **Q-6** The verb "resolve the lock" for `rbac.owner_only` (D03:321), and Resolve…'s route,
  which G10 records as missing (D03:522).
@ prose
  Owners: E09-D09's owner for the verb; D03's §11.1 owners, E29-T05, E29-T06, E29-T07 and E45, for
  the route (D03:619).
@ prose
  - **Q-7** CMP-129's open-positions reason: a key and its string, asked of E30-D02's owner (RULED
  BQ-8); until it is registered the toggle's T2 frames show `rbac.view_as` and `rbac.owner_only`
  only (spec §4.1), and no E29 surface hosts the toggle (D02:622).
@ prose
  Owner: E30-D02's owner.
@ prose
  - **Q-8** Rendering 2b on a row's text SplitButton (OQ-S, D02:668) and the selected-row T2 label
  in `color.text.secondary` (spec §5; D02:614), both extensions of E09-D09 §2.2.
@ prose
  Owner: E09-D09's owner.
@ prose
  - **Q-9** A Manager's closes under the kill switch read E39-D01's "Frozen — the owner closes or
  releases" until OD-11 rules (E39-D01:687; D02:654).
@ prose
  Owner: E39-D01's owner (OD-11).
@ prose
  - **Q-10** CSV export for a Viewer (OQ-G, D02:656), and SR-098's identity watermark and audit
  record, which need G7's server path (D03:519, :619).
@ prose
  Owners: the owner for OQ-G; E29-S04 for the record.
@ prose
  - **Q-11** `Ctrl+Shift+F`: Flatten account in the Positions context, or E39-D03's global flatten
  (OQ-R, D02:667), stays open; CMP-123 cites it and decides nothing (spec §2.4).
@ prose
  Owner: the owner, who rules OQ-R with E39-D03's owner.
@ prose
  - **Q-12** CMP-123's Table A rows compose with E33-D04 A-6 (PENDING, by name): whichever lands
  first applies the shared Tokens row, and the other is then a no-op; if A-5.1 lands first,
  A-6.1's Old cell no longer matches the Purpose it quotes, and A-6.1 is re-based on A-5.1's New.
@ prose
  Owner: E29-T09, after the owner's approval (owner approval pending (#2701)).
@ prose
  Owner: E05-D03 (#3174) as recipe owner; E29-T09 applies it.
@ prose
  Owner: the E05 token lane.
@ prose
  Owner: E05's owner.
@ prose
  - **Q-16** The assertive NO SL, Critical-crossing and amend-rejected announcements are proposed
  for E29-D05 (D02:465); the entries' live-region lines follow D02 until its review rules, a
  widening of the ticket's a11y note recorded as spec D04-C10.
@ prose
  Owner: E29-D05.
@ prose
  - **Q-17** The typed word on LIVE: for `all-accounts` it is `FLATTEN` (`15`:476, :2506;
  `14`:296; E39-D03:123); for `account` no merged text names it: D02:353 names none and D02:349
  routes the bulk words to D03's deck ("CLOSE"), which has none.
@ prose
  Owner: E29-D03's owner, the copy deck's.
@ prose
  Owners: as spec §7.3 names them; E29-D06.
@ prose
  Owner: E29-T09, with E29-D03's owner and the `/tools/` owners.
@ prose
  Owner: E29-T09, which applies A-6, with E05's owner.
@ head 2
  Owner
@ row CMP-078 StaleDataShade (spec §2.8.2) ‖ Change
  an account scope and a reason line; the stale surface's black in dark and high contrast
@ row CMP-075 EnvBadgeLocal (spec §2.8.6) ‖ CR
  CMP-075 EnvBadgeLocal (spec §2.8.6)
@ row CMP-139 EnvironmentAwareOrderGuard (spec ‖ CR
  CMP-139 EnvironmentAwareOrderGuard (spec §2.8.6)
@ row CMP-139 EnvironmentAwareOrderGuard (spec ‖ Change
  the row form `guard.mismatch.row` (Q-3)
@ row CMP-099 PrintExportBar (spec §2.8.9) ‖ Change
  the progress line and the watermark
"""


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
