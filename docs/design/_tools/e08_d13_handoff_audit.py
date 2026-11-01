#!/usr/bin/env python3
"""E08-D13 (#181) audit: the design hand-off pack for the E08 market-data surfaces.

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the plan texts, the merged E08 design docs (D03..D12 and
the hand-off twins), E17-D02, E16-D05 / D06, the ticket JSON, the calendar, the role seed, the
token file and the committed PNGs; then the pack and its copy deck from the working tree.

1. **Values.** Every `{{KIND:key}}` outside a code span is COMPUTED: CITE (a figure parsed from
   its line at the base, found by content), COUNT (the pack's tables, the deck, the parents'
   row ids, the `14` checklists), HASH (sha256 of a lifted block, 12 hex), SPRINT (the
   calendar), STATUS (a contract, tree, catalogue or seed probe at the base). `--fill` writes
   `VALUE<!--=KIND:key-->`; `--check` re-derives every anchored value (G-ANCHOR; HASH as G-HASH).
2. **Generated blocks.** A line `<!-- GEN:key -->` is replaced by `--fill` with a block the tool
   builds from the base: the byte copies of D12 §6.1, §7, §8.1, §8.2 and D11 §5 (G-COPY), the
   state enumeration table and D03's frame map (G-STATES), the role matrix (G-RBAC, frozen with
   the never-rendered list, G-FROZEN), the token names per screen (G-REDLINE). The deck file is
   built the same way (G-DECK). `--check` rebuilds each block and compares it cell by cell.
3. **Cites.** Every `DOC:line` or `` `NN`:line `` cite outside the copied blocks is read at the
   base (G-CITE); G-VERSION is content based (in PR-1 mode each cited range stands at
   `origin/main`; post-merge, every cite is judged at its frozen base `BASE`, the base the merged
   pack records, so a moved main does not FAIL it) and reads the version line. G-QUOTE: every quoted string of QUOTE_MIN+ characters is verbatim in
   a source the line cites, the deck, a core source or the ruling's own words.
4. **Gates.** Row-id indexes (G-INDEX), components in `15` (G-CMP), the `14` checklists item by
   item (G-CHECKLIST), budgets (G-BUDGET), the per-story table and the story-text deltas
   (G-STORY), the design-ahead rows (G-AHEAD), the open-rows log (G-OPENROWS), `14` = the nine
   pointer lines and nothing else in PR-1 mode, nothing in post-merge mode, where a sibling
   design tool may change in the same bundle (G-UNTOUCHED), the
   dry-run table (G-WALK), PNGs (G-PNG), §0's status cells (G-STATUS), the ruling (G-RULED),
   hygiene (G-HEX, G-PENPOT, G-NAMES, G-CLOSE, G-WORDS, G-SESSION, G-MARKER).
5. **Pins (G-RULED-PIN).** A default-deny pin set over every unit of the pack and every deck
   entry, in PIN_REL; `--repin-ruled` is its only writer.
6. **--self-test** applies one mutation per gate; each must add exactly one FAIL, from the gate
   it names, and every text is restored byte-identically. Runtime: each mutation is a full
   audit (about 10 s), so the run takes about 6 to 8 minutes on a laptop. It is a LOCAL check
   for the writer and the reviewer, not a CI gate; `--check` (about 11 s) is the CI-sized run.

Usage (from the repo root):
  python3 -I docs/design/_tools/e08_d13_handoff_audit.py --check [SPEC] [--json] [--fill]
  python3 -I docs/design/_tools/e08_d13_handoff_audit.py --check --strict-walk
  python3 -I docs/design/_tools/e08_d13_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e08_d13_handoff_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import codecs
import datetime
import functools
import hashlib
import io
import json
import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

_T = TypeVar("_T")

ROOT = Path(__file__).resolve().parents[3]
BASE = "fbb73c70de"  # every cite was read here (the pack's Inputs line)
HEAD = "origin/main"  # G-VERSION: a cited range edited at origin/main FAILs

SPEC_REL = "docs/design/E08/E08-D13.md"
DECK_REL = "docs/design/E08/E08-D13-copy.json"
TOOL_REL = "docs/design/_tools/e08_d13_handoff_audit.py"
PIN_REL = "docs/design/_tools/e08_d13_ruled_pins.txt"
PLAN14_REL = "docs/plan/14-screens-catalogue.md"
OWN_PATHS = (SPEC_REL, DECK_REL, TOOL_REL, PIN_REL, PLAN14_REL)
IMG_DIRS = ("docs/design/E08/img", "docs/design/E16/img")

CITE_FILES: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": PLAN14_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "20": "docs/plan/20-architecture.md",
    "21": "docs/plan/21-database-schema.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
    "D03": "docs/design/E08/E08-D03.md",
    "D04": "docs/design/E08/E08-D04.md",
    "D05": "docs/design/E08/E08-D05.md",
    "D05H": "docs/design/E08/E08-D05-handoff.md",
    "D06": "docs/design/E08/E08-D06.md",
    "D06H": "docs/design/E08/E08-D06-handoff.md",
    "D07": "docs/design/E08/E08-D07.md",
    "D07H": "docs/design/E08/E08-D07-handoff.md",
    "D08": "docs/design/E08/E08-D08.md",
    "D08H": "docs/design/E08/E08-D08-handoff.md",
    "D09": "docs/design/E08/E08-D09.md",
    "D09H": "docs/design/E08/E08-D09-handoff.md",
    "D11": "docs/design/E08/E08-D11.md",
    "D12": "docs/design/E08/E08-D12.md",
    "E17D2": "docs/design/E17/E17-D02.md",
    "E16D5": "docs/design/E16/E16-D05.md",
    "E16D6": "docs/design/E16/E16-D06.md",
    "E08J": "docs/plan/backlog/E08.json",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "TOK": "packages/ui/tokens/semantic-dark.tokens.json",
    "SEED": "services/api/candleviewer/auth/rbac_seed.json",
    "QAP": "qa/plans/e08-market-data-test-plan.md",
    "README": "docs/design/README.md",
}
DOC_KEYS = tuple(k for k in CITE_FILES if not k.isdigit())
# the inputs held byte-equal to the merge-base (G-UNTOUCHED); `14` only by its nine lines
UNTOUCHED = ("02", "05", "11", "15", "16", "20", "21", "22", "23", "24")
UNTOUCHED_DOCS = tuple(k for k in DOC_KEYS if k not in ("README",)) + ("README",)
TICKET_KEY = "E08-D13"
RULING_ID = "6544763601"
STAMP = "RULED (orchestrator, 2026-10-31, #181 ruling of record — 6544448256's answer)"
BQ_TOTAL = 23
PINNED_DOCS = {
    "D03": "0621057537",
    "D04": "a899ca1760",
    "D05": "d117dc7328",
    "D06": "33bb920225",
    "D07": "daeafcb465",
    "D08": "cf08d4c272",
    "D09": "5c4e35ed94",
    "D11": "5867d450cc",
    "D12": "22f9cabffc",
    "E17D2": "6e9207db6d",
    "E16D5": "627f351407",
    "E16D6": "0ab68e66cb",
    "14": "8addd87a73",
    "15": "00d2418ed2",
    "D07H": "f768fbab80",
    "E08J": "fa25280b39",
    "SEED": "8f282aa07d",
    "TOK": "aef2cc150b",
}
NAMED_ONLY = ("#5146", "#178", "DS-CR-1")
# the ruling's and the parents' own words (G-QUOTE accepts them verbatim)
RULING_QUOTES = (
    "Hand-off pack:",
    "filled at READY by the orchestrator's deputy",
    "re-sync needed",
    "no merged source",
    "no SCR-103 frame is drawn",
    "no walkthrough session was held or recorded, and none is claimed",
    "a written protocol replaces it",
    "named, unsourced",
    "none at the base",
)
REPORT_WIDTH = 100
QUOTE_MIN = 12

# the nine `14` pointer lines (RULED BQ-21): each directly after the entry's D12 a11y line
A11Y_PREFIX = "- **A11y review (E08-D12):**"
CHECKLIST_PREFIX = "- **Design sign-off acceptance checklist:**"
SCREENS = (
    "SCR-041",
    "SCR-100",
    "SCR-101",
    "SCR-102",
    "SCR-103",
    "SCR-104",
    "SCR-147",
    "SCR-151",
    "SCR-152",
)
POINTER_CLAUSES = {
    "SCR-041": "the built quick-switcher's acceptance record, its rows to E08-Q05",
    "SCR-100": "states with backend triggers, the role matrix, F-01's build rule, Q-01 and Q-02",
    "SCR-101": "states, the copy deck and the gated controls, beside E08-D07's hand-off checklist",
    "SCR-102": "the built search's acceptance record, the forced-colours rendering to E08-Q05",
    "SCR-103": "states, E08-D06's ten test ids and forced states, boards pending with E08-D06",
    "SCR-104": "states, the rate as a number, the gated actions and the pane name",
    "SCR-147": "E08-D09's merged text and its §17 rows, boards pending with E08-D09",
    "SCR-151": "E16's pattern rows and the backfill variant, the rest with E08-D10",
    "SCR-152": "E17-D02 the text of record, E08-D03's boards for the E08 states",
}


def pointer_line(scr: str) -> str:
    return (
        "- **Hand-off pack:** [E08-D13.md](../design/E08/E08-D13.md) v1 (E08-D13; "
        f"{POINTER_CLAUSES[scr]}; owner approval pending; a11y contract: E08-D12)."
    )


POINTERS = {s: pointer_line(s) for s in SCREENS}

# the byte copies (G-COPY): key -> (doc, heading prefix whose body is copied)
COPIES = {
    "d12s61": ("D12", "### 6.1 The script table"),
    "d12s7": ("D12", "## 7. The announcement budget"),
    "d12s81": ("D12", "### 8.1 The T2 table"),
    "d12s82": ("D12", "### 8.2 The safety disclosures"),
}
# the hash-lifts (G-HASH): key -> (doc, heading prefix whose body is hashed)
LIFTS = {
    "d04s3": ("D04", "## 3. States matrix"),
    "d05s6": ("D05", "## 6. SCR-102 Symbol search"),
    "d05s7": ("D05", "## 7. SCR-041 Quick-switcher"),
    "d05s8": ("D05", "## 8. Keyboard map"),
    "d06s3": ("D06", "## 3. Anatomy"),
    "d06s4": ("D06", "## 4. Field catalogue"),
    "d06s5": ("D06", "## 5. Number formatting"),
    "d06s6": ("D06", "## 6. States × bands"),
    "d06s8": ("D06", "## 8. RBAC"),
    "d07s41": ("D07", "### 4.1 SCR-100 anatomy"),
    "d07s42": ("D07", "### 4.2 SCR-100 states"),
    "d07s43": ("D07", "### 4.3 SCR-101 watchlist manager"),
    "d07s44": ("D07", "### 4.4 Import and export format"),
    "d07s5": ("D07", "## 5. Component contract changes"),
    "d07s6": ("D07", "## 6. Keyboard model and focus"),
    "d08s2": ("D08", "## 2. The panel"),
    "d08s9": ("D08", "## 9. The result states"),
    "d08s11": ("D08", "## 11. Result actions and roles"),
    "d08s12": ("D08", "## 12. Keyboard, focus and announcements"),
    "d09s5": ("D09", "## 5. Failure origins and the state register"),
    "d09s13": ("D09", "## 13. Roles, the gate and barred content"),
    "d09s17": ("D09", "## 17. Accessibility"),
    "d11s3": ("D11", "## 3. The hysteresis / debounce table"),
    # D11 §5 is lifted, not copied: its merged text carries a word the public-text rule bars
    "d11s5": ("D11", "## 5. Reduced motion, designed per element"),
    "d11s4": ("D11", "## 4. The motion spec table"),
    "d12s31": ("D12", "### 3.1 One table, one row per binding"),
    "d12s32": ("D12", "### 3.2 The pointer-parity table"),
    "d12s4": ("D12", "## 4. The focus model"),
    "d12s5": ("D12", "## 5. The region and landmark map"),
    "d12s9": ("D12", "## 9. R1–R7 per surface"),
    "d12s101b": ("D12", "### 10.1b The per-surface checklist"),
    "d12s13": ("D12", "## 13. The screen-reader script for E08-Q05"),
    "d12s14": ("D12", "## 14. The keyboard-only walkthrough"),
    "e17s2": ("E17D2", "## 2. The state matrix"),
    "e17s11": ("E17D2", "## 11. Announcement policy"),
    "e17s13": ("E17D2", "## 13. Keyboard, focus and targets"),
}
# the D12 row-id families (G-INDEX): prefix -> the lift that holds them
D12_FAMILIES = {
    "KB": "d12s31",
    "PP": "d12s32",
    "FM": "d12s4",
    "RG": "d12s5",
    "SR": "d12s61",
    "BG": "d12s7",
    "T2": "d12s81",
    "SD": "d12s82",
}
# D12's structure rows superseded by D09 §17 for SCR-147 (D13-C-5)
SUPERSEDED = ("KB-30", "PP-11", "T2-19", "SR-45")

# the state registers (G-STATES): (screens, doc, heading prefix, id column or -1 for a slug,
# name column, trigger column or -1 when the trigger is the name cell's parenthesis)
REGISTERS: tuple[tuple[str, str, str, int, int, int], ...] = (
    ("SCR-102, SCR-041", "D05", "### 6.2 States and the copy deck", -1, 0, 1),
    ("SCR-103", "D06", "## 6. States × bands", -1, 0, -1),
    ("SCR-100", "D07", "### 4.2 SCR-100 states", -1, 0, 1),
    ("SCR-101", "D07", "### 4.3 SCR-101 watchlist manager", -1, 0, -2),
    ("SCR-104", "D08", "## 9. The result states", -1, 0, 1),
    ("SCR-147", "D09", "### 5.2 The register", 0, 1, 6),
    ("SCR-151", "E16D5", "## 5. SCR-151", -1, 0, 1),
    ("SCR-152", "E17D2", "## 2. The state matrix", 0, 1, 1),
)
# D04's precedence (`D04`:50-51): the word a state name carries -> its rank
RANKS = (
    ("delisted", 1),
    ("disconnected", 2),
    ("reconnecting", 3),
    ("resync", 4),
    ("gap", 5),
    ("backfill", 6),
    ("stale", 7),
)
# the per-screen announcement rows (D12 §15.1's hand-offs; D09 §17.4 for SCR-147)
ANNOUNCE = {
    "SCR-102": "SR-10..SR-19; BG-07",
    "SCR-103": "SR-20..SR-26; BG-06",
    "SCR-100": "SR-27..SR-36; BG-02..BG-04",
    "SCR-101": "SR-30, SR-34; BG-04",
    "SCR-104": "SR-37..SR-44; BG-05",
    "SCR-147": "D09 §17.4",
    "SCR-151": "SR-46; BG-14",
    "SCR-152": "SR-01..SR-09; BG-08..BG-11",
}
# D03's eight frames (`D03` §3) -> the word that finds E17-D02's §2 rows (BQ-04)
D03_FRAMES = (
    ("disconnected", "disconnected"),
    ("reconnecting", "reconnecting"),
    ("degraded", "degraded"),
    ("disconnected-long-outage", "outage"),
    ("resyncing", "resync"),
    ("backfilling", "backfill"),
    ("clock-skew", "clock"),
    ("recovered", "recover"),
)
# the deck's sources (G-DECK): (prefix, doc, heading prefix, id column or -1 for a slug,
# string column or -1 for every quoted string in the row, status rule)
DECK_TABLES: tuple[tuple[str, str, str, int, int, str], ...] = (
    ("d05", "D05", "### 6.2 States and the copy deck", -1, 2, "verbatim"),
    ("d06", "D06", "## 6. States × bands", -1, -1, "verbatim"),
    ("d07", "D07", "### 4.2 SCR-100 states", -1, 3, "verbatim"),
    ("d07m", "D07", "### 4.3 SCR-101 watchlist manager", -1, 2, "verbatim"),
    ("d08", "D08", "## 13. Copy deck", 0, 2, "source"),
    ("d09", "D09", "## 15. Copy deck", 0, 2, "source"),
    ("e16d5", "E16D5", "## 14. Copy deck", 0, 1, "source-new"),
)
# single lines the deck lifts (D12 Q-01, Q-02): key -> (doc, the string, status)
DECK_LINES = {
    "d07.q01.stale-exit": ("D07", "Watchlist prices live again.", "PROPOSED"),
    "d07.q01.removal": ("D07", "Removed SOLUSDT. Undo is in the footer.", "PROPOSED"),
    "d07.q02.region": ("D07", "Watchlist Majors", "PROPOSED"),
}
E17_DECK_HEAD = "## 10. Copy deck"
DECK_BANNED = re.compile(r"\blorem\b|\bTBD\b|\bTODO\b|\bXXX\b", re.IGNORECASE)
# the token sections per screen (G-REDLINE): screen -> ((doc, heading prefix), ...)
TOKEN_SOURCES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("all (D04)", (("D04", "## 3. States matrix"),)),
    (
        "SCR-102, SCR-041",
        (("D05", "### 9.4 High contrast"), ("D05", "## 13. Component contract changes")),
    ),
    ("SCR-103", (("D06", "## 13. Contrast and colour independence"),)),
    ("SCR-100, SCR-101", (("D07", "### 7.1 Token map"),)),
    ("SCR-104", (("D08", "## 14. Tokens, density and contrast"),)),
    ("SCR-147", (("D09", "## 16. Tokens, themes and contrast"),)),
    ("SCR-151", (("E16D5", "## 11. Tokens and redlines"),)),
    ("SCR-152", (("E17D2", "## 14. Themes and densities"),)),
)
TOKEN = re.compile(
    r"`((?:color|opacity|space|size|type|font|motion|radius|border|elevation|duration|easing)"
    r"(?:\.[A-Za-z0-9-]+)+)`"
)
# the role matrix (G-RBAC): the D12 T2 rows, D09's gate and the SCR-152 Details split
ROLES = ("owner", "manager", "viewer")
# the frozen security-bearing set (G-FROZEN, RULED BQ-11): sha256 of §6's two generated or
# hand-written bodies, normalised; changed only with a design and security read and a re-pin
FROZEN_HEADS = ("6.1 The role matrix", "6.2 What is never rendered")
FROZEN_SHA = {
    "6.1 The role matrix": "5a7a78f1e6165fea",
    "6.2 What is never rendered": "e1be4a08f3dd986e",
}
# the contract, tree, catalogue and seed probes (STATUS): key -> (kind, where, needle, yes, no)
STATUS_PROBES: dict[str, tuple[str, str, str, str, str]] = {
    "web.watchlist": ("tree", "apps/web/src/features", "watchlist", "present", "absent"),
    "web.symbolinfo": ("tree", "apps/web/src/features", "symbol-info", "present", "absent"),
    "web.scanner": ("tree", "apps/web/src/features", "scanner", "present", "absent"),
    "web.symbolsearch": ("tree", "apps/web/src/features", "symbol-search", "present", "absent"),
    "web.connectivity": ("tree", "apps/web/src/features", "connectivity", "present", "absent"),
    "m3m7.in20": ("rx", "20", r"\bM[3-7](?:/M[3-7])? [A-Z][a-z]", "present", "absent"),
    "cmp239": ("rx", "15", r"^### CMP-239 ", "applied", "open"),
    "cmp026.backfill": ("cmp", "CMP-026", "backfill-in-progress", "applied", "open"),
    "cmp028.tones": ("cmp", "CMP-028", "connection-reconnecting", "applied", "open"),
    "cmp227.marker": ("cmp", "CMP-227", "CMP-239", "applied", "open"),
    "cmp161": ("rx", "15", r"^### CMP-161 ", "applied", "open"),
    "cmp162": ("rx", "15", r"^### CMP-162 ", "applied", "open"),
    "cmp213.onlist": ("cmp", "CMP-213", "on list", "applied", "open"),
    "cmp049.virtualize": ("cmp", "CMP-049", "virtualizeAbove", "applied", "open"),
    "d06.a2": ("cmp", "CMP-036", "unit?", "applied", "open"),
    "d06.a5": ("cmp", "CMP-126", "nextFundingTimeMs", "applied", "open"),
    "d06.a6": ("cmp", "CMP-177", "RecordingState", "applied", "open"),
    "d06.a8": ("cmp", "CMP-020", "value: string", "applied", "open"),
    "d08.a9": ("cmp", "CMP-055", "`space.filterbar.*`", "applied", "open"),
    "d08.a10": ("cmp", "CMP-008", "largeStep", "applied", "open"),
    "d08.a11": ("cmp", "CMP-024", "colorBySign", "applied", "open"),
    "d07.c1": ("yaml", "22:/watchlists/{watchlistId}", "If-Match|ETag|version", "served", "open"),
    "d07.c2": ("rx", "23", r"`stale`[^\n]{0,80}\b(?:means|is set|true when)", "served", "open"),
    "d07.c3": ("yaml", "22:WatchlistInput", r"^\s+(?:position|is_default):", "served", "open"),
    "d07.c4": ("rx", "21", r"CREATE TABLE (?:\w+\.)?watchlists\b", "served", "open"),
    "d07.c11": ("rx", "22", r"/market/tickers\b", "served", "open"),
    "d08.g1": ("yaml", "22:ScannerFilter", r"\S", "served", "open"),
    "d08.g2": ("yaml", "22:ScannerRow", r"turnover", "served", "open"),
    "d08.g3": ("yaml", "22:/scanner", r"turnover", "served", "open"),
    "d08.g4": ("yaml", "22:/scanner", r"\bcapped\b", "served", "open"),
    "d08.g5": ("yaml", "22:DataMeta", r"stale", "served", "open"),
    "d08.g6": ("yaml", "22:/scanner", r"'422'", "served", "open"),
    "d08.g7": ("rx", "22", r"/scanner/presets\b", "served", "open"),
    "d08.g8": ("rx", "23", r"`scanner[.\w{}]*`", "served", "open"),
    "d08.g9": ("rx", "22", r"/scanner/criteria\b", "served", "open"),
    "d08.g10": ("yaml", "22:PaneKind", r"\bscanner\b", "served", "open"),
    "seed.manager.recording": ("seed", "manager", "recording:write", "holds", "lacks"),
    "seed.nonowner.admin": ("seed", "manager,viewer", "admin:read", "holds", "lacks"),
    "tok.f01": ("tok", "", "", "equal", "distinct"),
    "e08s12": ("story", "E08-S12", "", "filed", "pending"),
}
# the banned words (G-WORDS), rot13 so this public file never spells them
BANNED_ROT13 = (
    "yrnx",
    "rkcbfrq",
    "olcnff",
    "rkcybvg",
    "nggnpx",
    "benpyr",
    "erirny",
    "haobhaqrq",
    "sybbq",
    "fgnyy",
    "qbf",
    "nqivfbel",
    "tufn",
    "cer-nhgu",
    "gur frpergf fpna",
)

# the pack's section heads (the first words of each heading; `section()` matches by prefix)
RULED_HEAD = "The questions BQ-01..BQ-23"
STATUS_HEAD = "0. Status and evidence"
LIFTTAB_HEAD = "1.3 Lift, copy or cite"
FRAME_HEAD = "2. The frame register"
STORY_HEAD = "3.1 What each consumer builds"
DELTA_HEAD = "3.2 Story-text deltas"
COMP_HEAD = "4.1 Components"
NEW_HEAD = "4.2 New from E08"
STATES_HEAD = "5.4 The state table"
D03MAP_HEAD = "5.5 D03's frames"
MATRIX_HEAD = "6.1 The role matrix"
NEVER_HEAD = "6.2 What is never rendered"
INDEX_HEAD = "7.8 Lifted by hash"
REDLINE_HEAD = "8.2 Token names per screen"
TICKED_HEAD = "9.1 Ticked at the base"
OPENCL_HEAD = "9.2 Open"
BUDGET_HEAD = "10.1 Budgets"
AHEAD_HEAD = "11.1 Design-ahead per consumer"
OPEN_HEAD = "13.1 The parents' rows"
OWNROWS_HEAD = "13.2 This pack's rows"
PROTO_HEAD = "14.2 The walkthrough"
WALK_HEAD = "14.3 The outside dry run"
VERSION_HEAD = "15. Versions and deltas"
SIGN_HEAD = "16. Sign-off"
AROWS_HEAD = "17. The nine `14` pointer lines"
GEN_HEADS = {
    "d12s61": "7.2 The announcement script",
    "d12s7": "7.3 The announcement budget",
    "d12s81": "6.3 The T2 table",
    "d12s82": "6.4 The safety disclosures",
    "states": STATES_HEAD,
    "d03map": D03MAP_HEAD,
    "matrix": MATRIX_HEAD,
    "redline": REDLINE_HEAD,
    "copycites": "7.4a The `14` cites inside the copies",
    "qacases": "5.6 QA cases per screen",
    "components": COMP_HEAD,
    "forced": "5.7 Forced states per screen",
    "smap": "5.8 SCR-147's states against D09's gap ledger",
}
WALK_ROLES = (
    "E08-S10",
    "E08-S11",
    "E08-S08",
    "E08-S12",
    "FE-lead read",
    "QA-lead read",
)
WALK_PENDING = "filled at READY by the orchestrator's deputy"

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z0-9]+:[^>]+?)-->")
ANCHOR_VALUE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|[a-f0-9]{12}|\d+\.\d+|served|open|applied|absent|present|holds|lacks|equal"
    r"|distinct|filed|pending|\d+)$"
)
GEN_MARK = re.compile(r"^<!-- GEN:([a-z0-9]+) -->$")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"([^"\n]*)"')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]|\b[a-z0-9-]+\.(?:com|net|org|io|dev)\b", re.IGNORECASE)
UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
NAMES = re.compile(
    r"\b(?:hpe|hcl)-\w|\bworker-\d\b|\w+-orchestrator\b|\bAgent [A-Z]\b|/home/\w|/mnt/c/|userToken"
    r"|team id|file id `|\bsession [0-9a-f]{8}|\b(?:Sonnet|Opus|Fable)\b",
    re.IGNORECASE,
)
PENPOT_WORDS = re.compile(r"workspace URL|team/[0-9a-f]|/view\?|/workspace/", re.IGNORECASE)
CLOSING = re.compile(r"\b(?:Closes|Fixes|Resolves)\s+#\d+", re.IGNORECASE)
SESSION_WORDS = re.compile(
    r"(?<![Nn]o )\bsession (?:was )?held\b|\bengineers met\b|\bmet with the\b"
    r"|\bwalked through with the (?:FE|engineering) lead\b|\bin the session the\b",
    re.IGNORECASE,
)
PNG_NAME = re.compile(r"`((?:E08-D0\d-\d\d|scr-\d{3}|cmp-\d{3}|E16-D05-\d\d)[a-z0-9-]*\.png)`")
KEY_TOKEN = re.compile(
    r"(?<![\w-])(?:`(\d\d)`|(" + "|".join(sorted(DOC_KEYS, key=len, reverse=True)) + r"))(?![\w-])"
)
REF_TOKEN = re.compile(r"(?<=[\s`\)\(])(?<!\d):(\d{1,5})(?:[–-](\d{1,5}))?(?![\d:])")
KEY_REF = re.compile(KEY_TOKEN.pattern + r":(\d{1,5})(?:[–-](\d{1,5}))?(?![\d:])")
CLAUSE_SPLIT = re.compile(r"\s\|\s|;\s|\)\s—\s")

Values = dict[str, str]
Finding = tuple[str, str, str | None, str | None]  # (gate, message, doc, section)
Unit = tuple[str, str, str, str]  # (doc, region, loc, text)
EXTRA_PATHS: list[str] = []  # self-test lever: paths pretended changed (G-UNTOUCHED)
PLAN_OVERRIDE: list[tuple[str, str]] = []  # self-test lever: a working-tree plan text (id, text)
PIN_UNITS_OVERRIDE: list[tuple[Unit, ...]] = []  # self-test lever: re-pinned units
HEAD_OVERRIDE: list[tuple[str, str]] = []  # self-test lever: (rel, text) pretended at origin/main
IMG_OVERRIDE: list[frozenset[str]] = []  # self-test lever: the PNG folders' names
STRICT_WALK: list[bool] = []  # --strict-walk: a pending dry-run row FAILs
POST_MERGE_OVERRIDE: list[bool] = []  # self-test lever: force one mode (True = post-merge)
VERSION_AT_HEAD: list[bool] = []  # self-test lever: judge G-VERSION at origin/main post-merge


def banned_words() -> tuple[str, ...]:
    return tuple(codecs.decode(w, "rot13") for w in BANNED_ROT13)


# ---------------------------------------------------------------------------- git and sources


def git_ok(*args: str) -> tuple[bool, str]:
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return False, ""
    return p.returncode == 0, p.stdout


def git_out(*args: str) -> str:
    return git_ok(*args)[1]


@functools.lru_cache(maxsize=256)
def git_show(rev: str, rel: str) -> str | None:
    ok, out = git_ok("show", f"{rev}:{rel}")
    return out if ok else None


def base_lines(cid: str) -> list[str]:
    rel = CITE_FILES.get(cid)
    text = git_show(BASE, rel) if rel else None
    return (text or "").split("\n")


def base_line(cid: str, n: int) -> str:
    lines = base_lines(cid)
    return lines[n - 1] if 1 <= n <= len(lines) else ""


@functools.cache
def line_of(cid: str, needle: str, start: int = 0) -> int:
    """The 1-based number of the first line at the base, from `start`, holding `needle`
    (0 when none): the anchors are found by content, never by a fixed line."""
    for i, ln in enumerate(base_lines(cid)[start:], start + 1):
        if needle in ln:
            return i
    return 0


@functools.cache
def source_text(cid: str) -> str:
    return "\n".join(base_lines(cid))


@functools.cache
def head_ok() -> bool:
    return bool(git_out("rev-parse", "--verify", "--quiet", f"{HEAD}^{{commit}}").strip())


@functools.cache
def under_base(sha: str) -> bool:
    full = git_out("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").strip()
    return bool(full) and git_out("merge-base", full, BASE).strip() == full


@functools.cache
def last_touch(cid: str) -> str:
    return git_out("log", "-1", "--format=%h", "--abbrev=10", BASE, "--", CITE_FILES[cid]).strip()


def merge_base() -> str:
    return git_out("merge-base", "HEAD", HEAD).strip()


def post_merge() -> bool:
    """Post-merge mode, by content: the pack and `14`'s nine pointer lines already ship at the merge-base
    (PR 1 is merged), so a later PR is a versioned delta on the pack's own files only."""
    if POST_MERGE_OVERRIDE:
        return POST_MERGE_OVERRIDE[-1]
    ref = merge_base()
    if not ref:
        return False
    spec = git_show(ref, SPEC_REL)
    plan = git_show(ref, PLAN14_REL)
    if spec is None or plan is None:
        return False
    lines = plan.split("\n")
    return all(p in lines for p in POINTERS.values())


def delta_rows(rows: list[list[str]]) -> tuple[list[list[str]], list[list[str]]]:
    return [r for r in rows if r[0] == "v1"], [r for r in rows if r[0] != "v1"]


def post_merge_version_problems(spec: str) -> list[str]:
    ref = merge_base()
    old_spec = git_show(ref, SPEC_REL) or ""
    old_rows = rows_of(old_spec, VERSION_HEAD)
    now = rows_of(spec, VERSION_HEAD)
    v1, later = delta_rows(now)
    bad: list[str] = []
    if now[: len(old_rows)] != old_rows:
        bad.append("a row merged at the merge-base differs (post-merge: merged rows are frozen)")
    if now[: len(v1)] != v1:
        bad.append("a later row sits among the v1 rows")
    last = 0
    for r in later:
        m = re.fullmatch(r"v1\.(\d+)", r[0])
        if not m or int(m[1]) <= last:
            bad.append(f"version {r[0]!r} is not a v1.N with N above {last}")
            continue
        last = int(m[1])
        if r[1] != f"`{BASE}`":
            bad.append(f"{r[0]} does not name the base {BASE}")
        if len(r) < 5 or not r[3].strip() or not r[4].strip():
            bad.append(f"{r[0]} lacks affected stories or an owner")
    return bad


@functools.cache
def tree_paths(prefix: str) -> tuple[str, ...]:
    ok, out = git_ok("ls-tree", "-r", "--name-only", BASE, "--", prefix)
    return tuple(p for p in out.split("\n") if p) if ok else ()


# ---------------------------------------------------------------------------- markdown helpers

COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^(#{1,6}) (.*)$")
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[A-Z_*`\"(])")


def strip_comments(text: str) -> str:
    return COMMENT.sub("", text)


def fenced(lines: list[str]) -> list[bool]:
    out: list[bool] = []
    open_, mark = False, ""
    for ln in lines:
        m = FENCE_OPEN.match(ln)
        if m and not open_:
            open_, mark = True, m[1]
            out.append(True)
        elif m and open_ and ln.strip().startswith(mark):
            out.append(True)
            open_ = False
        else:
            out.append(open_)
    return out


def section(text: str, head: str) -> str:
    """The body under the heading whose text starts with `head`, up to the next heading of the
    same or a higher level."""
    lines = text.split("\n")
    fence = fenced(lines)
    start: int | None = None
    level = 9
    for i, ln in enumerate(lines):
        m = HEADING.match(ln) if not fence[i] else None
        if m and start is None and m[2].startswith(head):
            start, level = i, len(m[1])
        elif m and start is not None and len(m[1]) <= level:
            return "\n".join(lines[start + 1 : i])
    return "\n".join(lines[start + 1 :]) if start is not None else ""


def h2_at(text: str, line_no: int) -> str:
    cur = "(top)"
    for i, ln in enumerate(text.split("\n"), 1):
        m = HEADING.match(ln)
        if m and len(m[1]) == 2:
            cur = m[2]
        if i == line_no:
            return cur
    return cur


def h2_of(text: str, head: str) -> str:
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if m and m[2].startswith(head):
            return m[2] if len(m[1]) == 2 else h2_at(text, i + 1)
    return "(top)"


def split_row(line: str) -> list[str]:
    body = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def is_rule(line: str) -> bool:
    cells = split_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def table_rows(block: str) -> list[list[str]]:
    rows = []
    for ln in block.split("\n"):
        if ln.lstrip().startswith("|") and not is_rule(ln):
            rows.append(split_row(strip_comments(ln)))
    return rows[1:] if rows else []  # drop the header row


def rows_of(text: str, head: str) -> list[list[str]]:
    return table_rows(section(text, head))


def raw_rows(text: str, head: str) -> list[list[str]]:
    """The table rows under a heading with their value anchors kept (split, not stripped)."""
    rows = [split_row(ln) for ln in section(text, head).split("\n") if ln.lstrip().startswith("|")]
    return [r for r in rows if not all(re.fullmatch(r":?-{3,}:?", c) for c in r)][1:]


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", strip_comments(s))
    s = re.sub(r"[*`_]", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def pin_norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


def loose(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[‐-―−]", "-", s).replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def ascii_line(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def report(line: str) -> str:
    s = ascii_line(line)
    return s if len(s) <= REPORT_WIDTH else s[: REPORT_WIDTH - 3] + "..."


def F(tag: str, msg: str, doc: str | None, sec: str | None) -> Finding:
    return (tag, msg, doc, sec)


def expand_ids(cell: str) -> set[str]:
    """Every id a cell names: single ids and inclusive ranges `X1–X9` with one prefix."""
    out: set[str] = set()
    for part in re.split(r",\s*|;\s*", strip_comments(cell)):
        part = part.strip().strip("`")
        m = re.fullmatch(r"([A-Za-z0-9-]*?)(\d+)–([A-Za-z0-9-]*?)(\d+)", part)
        if m and (m[3] in ("", m[1])):
            width = len(m[2])
            for n in range(int(m[2]), int(m[4]) + 1):
                out.add(f"{m[1]}{n:0{width}d}")
        elif part:
            out.add(part)
    return out


@dataclass(frozen=True)
class Texts:
    spec: str
    deck: str
    plans: tuple[tuple[str, str], ...]  # (cite id, working-tree text) for every untouched input
    vals: tuple[tuple[str, str], ...]

    @property
    def values(self) -> Values:
        return dict(self.vals)


def spec_sec(t: Texts, head: str) -> str:
    return h2_of(t.spec, head)


def deck_data(deck: str) -> dict[str, object]:
    try:
        d = json.loads(deck)
    except json.JSONDecodeError:
        return {}
    return d if isinstance(d, dict) else {}


def deck_entries(deck: str) -> dict[str, dict[str, object]]:
    s = deck_data(deck).get("strings")
    if not isinstance(s, dict):
        return {}
    return {str(k): v for k, v in s.items() if isinstance(v, dict)}


def str_list(v: object) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else []


# ---------------------------------------------------------------------------- base blocks


@functools.cache
def base_block(cid: str, head: str) -> tuple[int, int]:
    """(first, last) 1-based lines of the body under the heading that starts with `head` at the
    base, blank lines trimmed at both ends; (0, 0) when the heading is missing."""
    lines = base_lines(cid)
    fence = fenced(lines)
    start, level = 0, 9
    for i, ln in enumerate(lines):
        m = HEADING.match(ln) if not fence[i] else None
        if m and not start and ln.startswith(head):
            start, level = i + 1, len(m[1])
        elif m and start and len(m[1]) <= level:
            end = i
            break
    else:
        end = len(lines)
    if not start:
        return 0, 0
    a, b = start + 1, end
    while a <= b and not lines[a - 1].strip():
        a += 1
    while b >= a and not lines[b - 1].strip():
        b -= 1
    return a, b


def block_text(cid: str, head: str) -> str:
    a, b = base_block(cid, head)
    return "\n".join(base_lines(cid)[a - 1 : b]) if a else ""


def first_table(cid: str, head: str) -> list[tuple[int, list[str]]]:
    """(line, cells) of the first table under a heading at the base (fenced art skipped), the
    header row and the rule dropped."""
    a, b = base_block(cid, head)
    lines = base_lines(cid)
    fence = fenced(lines)
    out: list[tuple[int, list[str]]] = []
    started = False
    for n in range(a, b + 1):
        ln = lines[n - 1]
        if fence[n - 1]:
            if started:
                break
            continue
        if ln.lstrip().startswith("|"):
            started = True
            if not is_rule(ln):
                out.append((n, split_row(ln)))
        elif started:
            break
    return out[1:]


def lift_text(key: str) -> str:
    cid, head = {**LIFTS, **COPIES}[key]
    return block_text(cid, head)


def lift_range(key: str) -> tuple[str, int, int]:
    cid, head = {**LIFTS, **COPIES}[key]
    a, b = base_block(cid, head)
    return cid, a, b


# ---------------------------------------------------------------------------- values


def figure_at(cid: str, needle: str, pattern: str) -> tuple[int, str]:
    n = line_of(cid, needle)
    m = re.search(pattern, strip_comments(base_line(cid, n))) if n else None
    return n, (m[1] if m else "?")


# CITE key -> (cite id, needle that finds the line, pattern that captures the figure)
CITES: dict[str, tuple[str, str, str]] = {
    "b100.hz": ("14", "ticker updates coalesced to 4 Hz", r"coalesced to (\d+) Hz"),
    "b100.rows": ("14", "ticker updates coalesced to 4 Hz", r"virtualised beyond (\d+) rows"),
    "b102.ms": ("14", "results appear within", r"within (\d+) ms of a keystroke"),
    "b041.ms": ("14", "Opens in <=", r"Opens in <=(\d+) ms"),
    "b104.hz": ("14", "full-universe scan returns in", r"polls at <=([\d.]+) Hz"),
    "b104.scan": ("14", "full-universe scan returns in", r"returns in <=(\d+) s"),
    "b147.hz": ("14", "backend's own rate-limit accounting", r"sampled at (\d+) Hz"),
    "b152.usable": ("14", "target time-to-usable", r"outage is <=(\d+) s"),
    "virt.default": ("15", "virtualizeAbove?: number", r"default (\d+); SCR-100"),
    "virt.d09": ("D09", "**D09-Q3**", r"threshold: (\d+) rows"),
    "d08.g13.due": ("D08", "**D08-G13**", r"D08-G13\*\*[^\n]*?due (\d{4}-\d{2}-\d{2})"),
}


def cite_values() -> Values:
    return {k: figure_at(c, n, p)[1] for k, (c, n, p) in CITES.items()}


@functools.cache
def cal_start() -> datetime.date:
    m = re.search(
        r"SPRINT01_START = datetime\.date\((\d{4}), (\d{1,2}), (\d{1,2})\)", source_text("CAL")
    )
    return datetime.date(int(m[1]), int(m[2]), int(m[3])) if m else datetime.date(2026, 9, 25)


@functools.cache
def cal_days() -> int:
    m = re.search(r"SPRINT_DAYS = (\d+)", source_text("CAL"))
    return int(m[1]) if m else 7


def sprint_start(n: int) -> datetime.date:
    return cal_start() + datetime.timedelta(days=(n - 1) * cal_days())


def sprint_end(n: int) -> datetime.date:
    return sprint_start(n + 1) - datetime.timedelta(days=1)


def sprint_values() -> Values:
    out: Values = {}
    for n in (2, 4, 6, 8):
        out[f"s{n:02d}.start"] = sprint_start(n).isoformat()
        out[f"s{n:02d}.end"] = sprint_end(n).isoformat()
    return out


def hash_values() -> Values:
    return {k: hashlib.sha256(lift_text(k).encode("utf-8")).hexdigest()[:12] for k in LIFTS}


def cmp_block(cmp: str) -> str:
    lines = base_lines("15")
    start = line_of("15", f"### {cmp} ")
    if not start:
        return ""
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("### ")), len(lines))
    return "\n".join(lines[start - 1 : end])


def yaml_block(cid: str, name: str) -> str:
    """The block of a `22` schema (`    Name:`) or path (`  /path:`) at the base."""
    lines = base_lines(cid)
    pat = f"  {name}:" if name.startswith("/") else f"    {name}:"
    start = next((i for i, ln in enumerate(lines) if ln == pat), -1)
    if start < 0:
        return ""
    indent = len(pat) - len(pat.lstrip())
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) <= indent
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


@functools.cache
def seed_roles() -> dict[str, tuple[str, ...]]:
    try:
        data = json.loads(source_text("SEED"))
    except json.JSONDecodeError:
        return {}
    rp = data.get("role_permissions", {}) if isinstance(data, dict) else {}
    return {str(k): tuple(str(p) for p in v) for k, v in rp.items() if isinstance(v, list)}


def role_holds(role: str, perm: str) -> bool:
    held = seed_roles().get(role, ())
    return "*" in held or perm in held


@functools.cache
def ticket_index() -> dict[str, dict[str, object]]:
    try:
        data = json.loads(source_text("E08J"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, list):
        return {}
    return {str(t.get("key")): t for t in data if isinstance(t, dict)}


def tok_value(name: str) -> str:
    try:
        data = json.loads(source_text("TOK"))
    except json.JSONDecodeError:
        return ""
    v = data.get(name) if isinstance(data, dict) else None
    return str(v.get("$value", "")) if isinstance(v, dict) else ""


def probe(kind: str, where: str, needle: str) -> bool:
    if kind == "tree":
        return any(needle in p.lower() for p in tree_paths(where))
    if kind == "rx":
        return bool(re.search(needle, source_text(where), re.MULTILINE))
    if kind == "cmp":
        return needle in cmp_block(where)
    if kind == "yaml":
        cid, name = where.split(":", 1)
        block = yaml_block(cid, name)
        return bool(block) and bool(re.search(needle, block, re.MULTILINE))
    if kind == "seed":
        return any(role_holds(r, needle) for r in where.split(","))
    if kind == "tok":
        live = tok_value("color.data-confidence.live.text")
        return bool(live) and all(
            tok_value(f"color.data-confidence.{s}.text") == live
            for s in ("disconnected", "reconnecting")
        )
    if kind == "story":
        return where in ticket_index()
    return False


def status_values() -> Values:
    return {
        key: (yes if probe(kind, where, needle) else no)
        for key, (kind, where, needle, yes, no) in STATUS_PROBES.items()
    }


@functools.cache
def checklist_14() -> dict[str, tuple[int, int, int]]:
    """screen -> (line, ticked, open) of its sign-off checklist line at the base."""
    lines = base_lines("14")
    out: dict[str, tuple[int, int, int]] = {}
    cur = ""
    for i, ln in enumerate(lines, 1):
        m = re.match(r"^### (SCR-\d{3}) ", ln)
        if m:
            cur = m[1]
        elif cur in SCREENS and ln.startswith(CHECKLIST_PREFIX) and cur not in out:
            out[cur] = (i, ln.count("[x]"), ln.count("[ ]"))
    return out


def family_ids(prefix: str) -> list[str]:
    key = D12_FAMILIES[prefix]
    out: list[str] = []
    for ln in lift_text(key).split("\n"):
        m = re.match(rf"^\| ({prefix}-\d\d) ", ln)
        if m and m[1] not in out:
            out.append(m[1])
    return out


def numbered_items(spec: str, head: str) -> int:
    return len([ln for ln in section(spec, head).split("\n") if re.match(r"^\d{1,2}\. ", ln)])


def count_values(spec: str, deck: str) -> Values:
    cl = checklist_14()
    entries = deck_entries(deck)
    rows = state_rows()
    out: Values = {
        "checklist.items": str(sum(t + o for _l, t, o in cl.values())),
        "checklist.ticked": str(sum(t for _l, t, _o in cl.values())),
        "checklist.open": str(sum(o for _l, _t, o in cl.values())),
        "deck.total": str(len(entries)),
        "deck.proposed": str(sum(1 for e in entries.values() if e.get("status") == "PROPOSED")),
        "deck.slotted": str(sum(1 for e in entries.values() if e.get("slots"))),
        "deck.static": str(sum(1 for e in entries.values() if e.get("kind") == "static-example")),
        "states.total": str(len(rows)),
        "walk.items": str(numbered_items(spec, PROTO_HEAD)),
    }
    for kind in ("wire", "client", "inherited", "G-row"):
        out[f"states.{kind}"] = str(sum(1 for r in rows if r.emitter.startswith(kind)))
    for prefix in D12_FAMILIES:
        out[f"d12.{prefix.lower()}"] = str(len(family_ids(prefix)))
    return out


def compute(spec: str, deck: str) -> Values:
    out: Values = {}
    for kind, vals in (
        ("CITE", cite_values()),
        ("COUNT", count_values(spec, deck)),
        ("HASH", hash_values()),
        ("SPRINT", sprint_values()),
        ("STATUS", status_values()),
    ):
        out.update({f"{kind}:{k}": v for k, v in vals.items()})
    return out


def in_code(line: str, pos: int) -> bool:
    return any(m.start() <= pos < m.end() for m in CODE.finditer(line))


def regen_sections(text: str) -> str:
    """Put each generated block back to its GEN marker, so `--fill` rebuilds it from the base
    (a later delta re-renders the block instead of hand-editing it)."""
    lines = text.split("\n")
    out: list[str] = []
    skip_level = 0
    for ln in lines:
        m = HEADING.match(ln)
        if skip_level and m and len(m[1]) <= skip_level:
            skip_level = 0
        if skip_level:
            continue
        out.append(ln)
        if m:
            key = next((k for k, h in GEN_HEADS.items() if m[2].startswith(h)), None)
            if key:
                out += ["", f"<!-- GEN:{key} -->", ""]
                skip_level = len(m[1])
    return "\n".join(out)


def unanchor(text: str) -> str:
    """Turn every `VALUE<!--=KEY-->` back into `{{KEY}}` so `--fill` re-derives it."""
    vals = ANCHOR_VALUE.pattern.removesuffix(")$").removeprefix("(")
    return re.sub(rf"(?:{vals})<!--=([A-Z0-9]+:[^>]+?)-->", r"{{\1}}", text)


def fill(text: str, values: Values) -> tuple[str, list[str]]:
    text = unanchor(regen_sections(text))
    unknown: list[str] = []
    out = []
    for ln in text.split("\n"):
        g = GEN_MARK.match(ln)
        if g:
            block = gen_block(g[1])
            if block is None:
                unknown.append(f"GEN:{g[1]}")
                out.append(ln)
            else:
                out.append(block)
            continue
        pieces, last = [], 0
        for m in PLACEHOLDER.finditer(ln):
            if in_code(ln, m.start()):
                continue
            pieces.append(ln[last : m.start()])
            if m[1] in values:
                pieces.append(f"{values[m[1]]}<!--={m[1]}-->")
            else:
                unknown.append(m[1])
                pieces.append(m[0])
            last = m.end()
        pieces.append(ln[last:])
        out.append("".join(pieces))
    return "\n".join(out), unknown


# ---------------------------------------------------------------------------- generated blocks


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "row"


def clean_name(cell: str) -> str:
    s = strip_comments(cell)
    m = re.match(r"^\*\*(.+?)\*\*", s)
    if m:
        s = m[1]
    s = s.split(" · ")[0]
    s = re.sub(r"\s*\(.*\)\s*$", "", s)
    s = s.replace("`", "").replace("**", "").strip()
    s = s.removeprefix("SCR-151/")
    return s


def esc(cell: str) -> str:
    return cell.replace("|", "\\|")


def unesc(cell: str) -> str:
    return re.sub(r"\\([_*\[\]<>|])", r"\1", cell)


WIRE_DOCS = ("23", "22", "24")
CLIENT_WORDS = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:ms|s|%|rows?|symbols|subscriptions|min)\b|\bquery\b|\buser\b"
    r"|\bclient\b|\bpress|\bopen|\bfocus|\bclick|\bdrag|\bpaste|\btyp|\bscroll|\bhover"
    r"|\bmenu\b|\bdialog\b|\brows?\b|\blist\b|\bin flight\b|\bresponse\b|\banswer"
    r"|\breturns?\b|\berrors?\b|\bfail|\breads?\b|\bdensity\b|\bmanual order\b"
    r"|\bsession\b|\bage\b|\bT[12]\b|\bstore\b|\bwindow\b|\bfilter|\bmatches\b|\babsence\b",
    re.IGNORECASE,
)
INHERIT = re.compile(
    r"E17-D01|E17-D02|E09-D09|E16-D02|E08-D0\d|CMP-\d{3}|\bD-\d+\b|\bR-I\d\b"
    r"|D09-[GQ]\d+|\bS-\d\d\b|`D01`"
)
HTTP_STATUS = re.compile(
    r"(?<![\w.,×-])(200|201|202|400|401|403|404|409|412|422|429|500|503)(?![\w.,]|\s?(?:%|×|symbols"
    r"|subscriptions|rows|s\b|ms\b|per\b))"
)


def find_line(cid: str, pat: re.Pattern[str]) -> int:
    return next((i for i, ln in enumerate(base_lines(cid), 1) if pat.search(ln)), 0)


@functools.cache
def def_patterns(name: str) -> dict[str, list[re.Pattern[str]]]:
    """The anchored definition forms of `name` (BQ-07): a `22` schema, property or enum line,
    or a `23` / `24` table first cell, heading or typed field. A bare mention never counts."""
    e = re.escape(name)
    table = re.compile(rf"^\|\s*`?{e}`?\s*\|")
    head = re.compile(rf"^#{{2,6}} .*`{e}`")
    schema_keys = r"type|enum|\$ref|items|oneOf|anyOf|const|description|properties"
    field = re.compile(rf"^\s+\"{e}\": \{{\s*(?:$|\"(?:{schema_keys})\")|^\s+{e}\??: [^;=]+;\s*$")
    return {
        "22": [
            re.compile(rf"^ {{4}}{e}:\s*$"),
            re.compile(rf"^ {{6,}}{e}:\s*(?:$|\{{\s*(?:\$ref|type)|#)"),
            re.compile(rf"^\s+- {e}\s*$"),
            re.compile(rf"^\s+['\"]{e}['\"]:"),
            re.compile(rf"^ {{6,}}\w+: \{{ type: string, enum: \[[^\]]*\b{e}\b"),
        ],
        "23": [table, head, field],
        "24": [table, head, field],
    }


def strong_name(tok: str) -> str | None:
    """The identifier a token defines: an HTTP path, a numeric code, or a snake_case, CamelCase
    or dotted name (its strongest segment); a plain lower-case word is never an emitter."""
    t = tok.strip()
    if re.match(r"^(?:GET|POST|PUT|DELETE|PATCH) /", t):
        return t.split(" ", 1)[1].split("?")[0].split(" ")[0]
    t = t.split(" ")[0]
    if re.fullmatch(r"\d{3,5}", t):
        return t
    if not re.fullmatch(r"[A-Za-z_][\w]*(?:[.:][\w{}]+)*", t):
        return None
    segs = [x for x in re.split(r"[.:]", t) if x]
    strong = [x for x in segs if "_" in x or re.search(r"[a-z][A-Z]", x) or x[:1].isupper()]
    return max(strong, key=len) if strong else None


def defines(cid: str, n: int, name: str) -> bool:
    ln = base_line(cid, n)
    if name.startswith("/"):
        return cid == "22" and ln == f"  {name}:"
    return any(p.search(ln) for p in def_patterns(name).get(cid, []))


@functools.cache
def wire_hit(tok: str) -> tuple[str, int, str] | None:
    name = strong_name(tok)
    if not name:
        return None
    for cid in WIRE_DOCS:
        for i, ln in enumerate(base_lines(cid), 1):
            if name in ln and defines(cid, i, name):
                return cid, i, name
    return None


THRESHOLD = re.compile(
    r"\b\d{1,3}(?: \d{3})*(?:\.\d+)?\s?(?:ms|s|%|rows?|symbols|subscriptions|min)\b"
    r"|\b\d+s\b|\bT[12]\b"
)
CLAUSE = re.compile(r";\s|,\s(?=or\b|and\b)|\s—\s|\s\(|\)\s?")


def clip(part: str) -> str:
    part = re.sub(r"^(?:or|and|a|the)\s+", "", part.strip(" .,;:"))
    words = part.split()
    return " ".join(words[:14]) + (" …" if len(words) > 14 else "")


def first_clause(plain: str) -> str:
    """The parent's own condition, its first clause, when it states no threshold."""
    text = re.sub(r"`([^`]*)`", r"\1", strip_comments(plain)).replace("**", "")
    parts = [p.strip(" .,;:") for p in CLAUSE.split(text) if p.strip(" .,;:")]
    out: list[str] = []
    for p in parts:
        out.append(p)
        if len(" ".join(out).split()) >= 5:
            break
    return clip("; ".join(out)) if out else "the parent's rule"


def condition_of(plain: str) -> str:
    """The WHOLE condition holding the first threshold (round-2 read U2): the clause it sits in,
    with any comparison, range or duration around it ("503s for 60 s", "> 2 000 ms", "180 to
    199 symbols"), never the first number and unit alone."""
    text = re.sub(r"`([^`]*)`", r"\1", plain)
    for part in CLAUSE.split(text):
        if THRESHOLD.search(part):
            return clip(part)
    return ""


def classify(trigger: str, screen: str) -> str:
    plain = strip_comments(trigger)
    toks = [
        m[1] for m in re.finditer(r"`([^`]+)`", plain) if not plain[: m.start()].endswith("no ")
    ]
    toks += re.findall(r"\b[A-Z][a-z]+[A-Z]\w+\b", re.sub(r"`[^`]*`", "", plain))
    for tok in toks:
        hit = wire_hit(tok)
        if hit:
            return f"wire: `{hit[2]}` (`{hit[0]}`:{hit[1]})"
    st = HTTP_STATUS.search(re.sub(r"`[^`]*`", "", plain))
    if st:
        n = find_line("22", re.compile(rf"^\s+['\"]{st[1]}['\"]:"))
        if n:
            return f"wire: HTTP {st[1]} (`22`:{n})"
    cond = condition_of(plain)
    if cond:
        return f"client-computed: {cond}"
    if screen == "SCR-101" and plain == "(user-reached)":
        return "client-computed: a user action reaches the view"
    if CLIENT_WORDS.search(plain):
        return f"client-computed: {first_clause(plain)}"
    m = INHERIT.search(plain)
    if m:
        return f"inherited: {m[0].strip('`')}"
    return "G-row: D13-G-6"


# the rows whose emitter the generic reading gets wrong, each with its reason (RULED BQ-07;
# round-1 lens F1 / F2): a wire entry names the field and the file, and the tool finds and
# re-checks its definition line; a client entry says what the client computes
EMITTER_MAP: dict[str, tuple[str, str, str]] = {
    "SCR-102/checking-a-symbol": ("client", "300 ms after the last keystroke", ""),
    "SCR-152/2": ("client", "the transport state (no served field)", ""),
    "SCR-152/3": ("client", "the transport's retry schedule", ""),
    "SCR-152/5": ("wire", "connection_quality", "23"),
    "SCR-152/7": ("client", "the shell's connection state", ""),
    "SCR-152/12": ("wire", "snap", "23"),
    "SCR-152/14": ("wire", "snap", "23"),
    "SCR-152/18": ("client", "the client's `system` stream state", ""),
}


def emitter_of(rid: str, trigger: str, screen: str) -> str:
    kind, what, cid = EMITTER_MAP.get(rid, ("", "", ""))
    if kind == "client":
        return f"client-computed: {what}"
    if kind == "wire":
        n = next(
            (i for i, ln in enumerate(base_lines(cid), 1) if what in ln and defines(cid, i, what)),
            0,
        )
        return f"wire: `{what}` (`{cid}`:{n})" if n else "G-row: D13-G-6"
    return classify(trigger, screen)


def rank_of(name: str) -> str:
    low = name.lower()
    for word, n in RANKS:
        if word in low:
            return str(n)
    return "8" if low in ("live", "connected") or low.startswith("live ") else "n/a"


@dataclass(frozen=True)
class StateRow:
    rid: str
    name: str
    cite: str
    emitter: str
    rank: str
    copy: str
    announce: str
    handle: str


# states a parent names in its own section rather than its register table (round-2 read: the
# SCR-104 dry run): (screen, doc, heading prefix, state name)
EXTRA_STATES: tuple[tuple[str, str, str, str], ...] = (
    ("SCR-104", "D08", "### 5.2 The cap and its note", "Capped"),
    ("SCR-104", "D08", "### 7.3 The stale scan", "Stale scan"),
    ("SCR-104", "D08", "### 7.4 Stale inputs", "Inputs stale"),
    ("SCR-104", "D08", "### 7.5 Pause", "Paused"),
)
# the root component a state's `data-cmp` names, per screen (PROPOSED; from §4.1's lists)
HANDLE_ROOT = {
    "SCR-102": "CMP-043",
    "SCR-041": "CMP-017",
    "SCR-103": "CMP-046",
    "SCR-100": "CMP-049",
    "SCR-101": "CMP-043",
    "SCR-104": "CMP-049",
    "SCR-147": "CMP-087",
    "SCR-151": "CMP-026",
    "SCR-152": "CMP-077",
}


def handle_of(first: str, rid: str, copy: str) -> str:
    base = f'`data-cmp="{HANDLE_ROOT.get(first, "?")}"` `data-state="{rid}"`'
    if copy == "—":
        return base
    text = str(build_deck()["strings"][copy].get("text", ""))
    name = f'"{text}"' if len(text) <= 60 and '"' not in text else f"deck `{copy}`"
    return f"accessible name {name}; else {base}"


@functools.cache
def deck_keys() -> tuple[str, ...]:
    return tuple(build_deck()["strings"])


@functools.cache
def state_rows() -> tuple[StateRow, ...]:
    keys = deck_keys()
    out: list[StateRow] = []
    for screens, cid, head, idc, namec, trigc in REGISTERS:
        first = screens.split(",")[0].strip()
        seen: dict[str, int] = {}
        prefix = next(
            (p for p, c, h, _i, _s, _r in DECK_TABLES if c == cid and h == head), cid.lower()
        )
        for line, cells in first_table(cid, head):
            if len(cells) <= max(namec, idc, trigc):
                continue
            name = clean_name(cells[namec])
            if not name:
                continue
            if idc >= 0:
                rid = cells[idc].strip("` ")
            else:
                s = slug(name)
                seen[s] = seen.get(s, 0) + 1
                rid = s + (f"-{seen[s]}" if seen[s] > 1 else "")
            if trigc >= 0:
                trigger = cells[trigc]
            elif trigc == -1:
                m = re.search(r"\((.*)\)\s*$", cells[namec])
                trigger = m[1] if m else cells[namec]
            else:
                trigger = "(user-reached)"
            wn = re.findall(r"\bW-\d+\b", " ".join(cells))
            copy = "—"
            if wn and f"{cid.lower()}.{wn[0]}" in keys:
                copy = f"{cid.lower()}.{wn[0]}"
            elif f"{prefix}.{rid}.1" in keys:
                copy = f"{prefix}.{rid}.1"
            handle = handle_of(first, rid, copy)
            out.append(
                StateRow(
                    rid=f"{first}/{rid}",
                    name=name,
                    cite=f"`{cid}`:{line}",
                    emitter=emitter_of(f"{first}/{rid}", trigger, first),
                    rank=rank_of(name),
                    copy=copy,
                    announce=ANNOUNCE.get(first, "—"),
                    handle=handle,
                )
            )
    for scr, cid, head, name in EXTRA_STATES:
        a, _b = base_block(cid, head)
        trigger = base_line(cid, a)
        rid = slug(name)
        wn = re.findall(r"\bW-\d+\b", trigger)
        copy = f"{cid.lower()}.{wn[0]}" if wn and f"{cid.lower()}.{wn[0]}" in keys else "—"
        out.append(
            StateRow(
                rid=f"{scr}/{rid}",
                name=name,
                cite=f"`{cid}`:{a}",
                emitter=emitter_of(f"{scr}/{rid}", trigger, scr),
                rank=rank_of(name),
                copy=copy,
                announce=ANNOUNCE.get(scr, "—"),
                handle=handle_of(scr, rid, copy),
            )
        )
    return tuple(out)


def table(head: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    out += ["| " + " | ".join(esc(c) if "`" not in c else c for c in r) + " |" for r in rows]
    return "\n".join(out)


def gen_states() -> str:
    head = ["Test id", "State", "Trigger", "Emitted by", "Rank", "Copy key", "Announce", "Handle"]
    rows = [
        [f"`{r.rid}`", r.name, r.cite, r.emitter, r.rank, r.copy, r.announce, r.handle]
        for r in state_rows()
    ]
    return table(head, rows)


def e17_rows() -> list[tuple[str, str]]:
    return [(c[0].strip(), c[1]) for _n, c in first_table("E17D2", "## 2. The state matrix")]


def d03_frame_line(frame: str) -> int:
    a, b = base_block("D03", "## 3. State variants")
    for n in range(a, b + 1):
        if base_line("D03", n).startswith(f"| `{frame}`"):
            return n
    return 0


def gen_d03map() -> str:
    rows = []
    for frame, word in D03_FRAMES:
        hits = [rid for rid, text in e17_rows() if word in text.lower()]
        n = d03_frame_line(frame)
        reading = "mapped" if hits else "no E17-D02 row: D13-C-10"
        rows.append([f"`{frame}`", f"`D03`:{n}" if n else "—", ", ".join(hits) or "—", reading])
    return table(["D03 frame", "Line", "E17-D02 §2 rows", "Reading"], rows)


T2_KEY = re.compile(r"`([a-z]+\.[a-z_.]+)`")


def matrix_cells(legs: str, keys: list[str], cls: str = "T2") -> tuple[list[str], str]:
    """BQ-11's cell vocabulary from the parent row's class: `absence` hides (T3) with the
    parent's words; `validity` is n/a; `sentence` keeps the sentence form (lens F4)."""
    if cls == "validity":
        return ["n/a (validity)"] * 4, "input validity"
    perms = re.findall(r"`([a-z]+:[a-z]+)`", legs)
    if "/admin" in legs:
        perms.append("admin:read")
    state = bool(re.search(r"step 4|the state|validity|feed state", legs))
    view_as = "rbac.view_as" in legs
    perm_keys = [k for k in keys if k.startswith("rbac.") and k != "rbac.view_as"]
    state_keys = [k for k in keys if not k.startswith("rbac.")]
    reason = f"T2 `{perm_keys[0]}`" if perm_keys else "T2"
    if cls == "absence":
        reason = "hidden (T3); the sentence replaces the link"
    elif cls == "sentence":
        reason += " (the sentence form)"
    cells: list[str] = []
    for role in ROLES:
        if perms and not all(role_holds(role, p) for p in perms):
            cells.append(reason)
        elif state:
            sk = f" `{state_keys[0]}`" if state_keys else ""
            cells.append(("enabled; " if perms else "") + f"T2{sk} by state")
        else:
            cells.append("enabled")
    # E09-D09 step 3a makes every write T2 under view-as (round-2 read U7), whether or not the
    # D12 row's legs repeat it (D13-C-13)
    writes = any(p.endswith(":write") for p in perms)
    view = "T2 `rbac.view_as`" if view_as or writes else cells[0]
    return [*cells, view], ", ".join(f"`{p}`" for p in perms) or "a data state"


def gen_matrix() -> str:
    rows: list[list[str]] = []
    for line, c in first_table("D12", "### 8.1 The T2 table"):
        if len(c) < 4 or not c[0].startswith("T2-"):
            continue
        if c[0] in SUPERSEDED:
            rows.append([c[0], f"`D12`:{line}", "n/a", "n/a", "n/a", "n/a", "superseded"])
            continue
        cls = c[4].strip() if len(c) > 4 else "T2"
        cells, gate = matrix_cells(c[2], T2_KEY.findall(c[3]), cls)
        rows.append([c[0], f"`D12`:{line}", *cells, gate])
    gate_line = line_of("D09", "- **The gate.**")
    nonowner = "hidden (T3)" if not probe("seed", "manager,viewer", "admin:read") else "CHECK"
    rows.append(
        [
            "D09 gate",
            f"`D09`:{gate_line}",
            "enabled",
            nonowner,
            nonowner,
            "enabled for the read; writes T2 `rbac.view_as`",
            "`admin:read`",
        ]
    )
    rows.append(
        [
            "SD-01",
            f"`D03`:{line_of('D03', '## 4. RBAC content split')}",
            "enabled (the payload)",
            "the plain sentence",
            "the plain sentence",
            "not stated by the parent",
            "the Owner role",
        ]
    )
    head = ["Row", "Parent line", "Owner", "Manager", "Viewer", "Owner viewing as", "Gate"]
    return table(head, rows)


def gen_redline() -> str:
    rows = []
    for screen, srcs in TOKEN_SOURCES:
        names: list[str] = []
        cites = []
        for cid, head in srcs:
            a, b = base_block(cid, head)
            cites.append(f"`{cid}`:{a}–{b}")
            for t in TOKEN.findall(block_text(cid, head)):
                if t not in names:
                    names.append(t)
        rows.append([screen, ", ".join(cites), str(len(names)), ", ".join(f"`{n}`" for n in names)])
    return table(
        ["Screen", "Token section", "Names", "Token names (as the parent binds them)"], rows
    )


D12_BASE = "6298e962e"  # the base D12 read `14` at (`D12` D-7); its copies keep those numbers


def copied_14_cites() -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for key in COPIES:
        for ln in lift_text(key).split("\n"):
            for m in re.finditer(r"`14`:(\d+)((?:[–-]:?\d+|, :\d+)*)", ln):
                for n in [int(m[1]), *(int(x) for x in re.findall(r"\d+", m[2]))]:
                    if (key, n) not in out:
                        out.append((key, n))
    return out


def refind_14(n: int) -> int:
    """D12's `14` line n, re-found by content at the base (0 when not unique)."""
    old = (git_show(D12_BASE, PLAN14_REL) or "").split("\n")
    text = old[n - 1] if 1 <= n <= len(old) else ""
    hits = [i for i, ln in enumerate(base_lines("14"), 1) if text.strip() and ln == text]
    if len(hits) == 1:
        return hits[0]
    # a line its owner has since reworded: the same field of the same screen (by label)
    want = field_key(old, n)
    lines = base_lines("14")
    same = [i for i in range(1, len(lines) + 1) if want[1] and field_key(lines, i) == want]
    return same[0] if len(same) == 1 else 0


def field_key(lines: list[str], n: int) -> tuple[str, str]:
    scr = next(
        (m[1] for i in range(n, 0, -1) if (m := re.match(r"^### (SCR-\d{3}) ", lines[i - 1]))),
        "",
    )
    f = re.match(r"^- \*\*([^*]+?)\*\*", lines[n - 1]) if 1 <= n <= len(lines) else None
    return scr, f[1] if f else ""


def line_label(n: int) -> str:
    lines = base_lines("14")
    scr = next(
        (m[1] for i in range(n, 0, -1) if (m := re.match(r"^### (SCR-\d{3}) ", lines[i - 1]))),
        "the `14` preamble",
    )
    f = re.match(r"^\d*\.? ?(?:- )?\*\*([^*]+?):?\*\*", lines[n - 1].lstrip())
    label = f[1].rstrip(":").rstrip(".") if f else "the line"
    return f"{scr}, {label}"


def gen_copycites() -> str:
    rows = []
    for key, n in copied_14_cites():
        new = refind_14(n)
        now = f"`14`:{new}" if new else "not re-found"
        rows.append(
            [
                f"§{GEN_HEADS[key].split(' ')[0]}",
                f"{n} (D12's base)",
                now,
                line_label(new) if new else "—",
            ]
        )
    return table(["Copy", "`14` line in the copy", "Now at", "The line"], rows)


def qa_cases(screen: str) -> list[str]:
    out: list[str] = []
    for ln in base_lines("QAP"):
        m = re.match(r"^\| (E08-TC-[A-Z]\d+) ", ln)
        if m and re.search(rf"\b{screen}\b", ln) and m[1] not in out:
            out.append(m[1])
    return out


def gen_qacases() -> str:
    rows = []
    for scr in SCREENS:
        ids = qa_cases(scr)
        rows.append([scr, ", ".join(ids) if ids else "none at the base"])
    return table(["Screen", "QA cases in `QAP` naming the screen"], rows)


# what §4.1 adds to a screen's `14` Components line, from D12 or a parent
ADDED_CMP = {
    "SCR-104": "CMP-079 RbacGate, CMP-019 Icon `lock` (F-03, T2-17); `14`'s line stays its owner's",
    "SCR-147": "the gate and view-as rows of `D09` §13.1; `D09H` §D's list",
    "SCR-151": "CMP-023 Progress Bar for `backfill-in-progress` (`D11`:125)",
    "SCR-152": "CMP-092 DegradedModeBanner (`E17D2` §8); the chip is CMP-076 (§4.4)",
}


def components_line(scr: str) -> int:
    lines = base_lines("14")
    cur = ""
    for i, ln in enumerate(lines, 1):
        m = re.match(r"^### (SCR-\d{3}) ", ln)
        if m:
            cur = m[1]
        elif cur == scr and ln.startswith("- **Components:**"):
            return i
    return 0


def gen_components() -> str:
    rows = []
    for scr in SCREENS:
        n = components_line(scr)
        ids = re.findall(r"CMP-\d{3}", base_line("14", n))
        rows.append([scr, f"`14`:{n}", ", ".join(ids), ADDED_CMP.get(scr, "none")])
    return table(
        ["Screen", "Components line", "`15` ids (each an entry at the base)", "Added"], rows
    )


# the forced-state list each screen's parent names (round-2 read: E08-D14's matrix)
FORCED = {
    "SCR-103": "`D06`:752–761 (D06 §17.3)",
    "SCR-104": "`D08`:418 (D08's frame register)",
    "SCR-147": "`D09`:255–284 (D09 §5.2, by S-id)",
}


def gen_forced() -> str:
    rows = []
    for scr in SCREENS:
        if scr in FORCED:
            rows.append([scr, FORCED[scr], "the parent's list"])
        else:
            rows.append([scr, "the trigger condition of each §5.4 row", "no parent list: D13-G-7"])
    return table(["Screen", "Forced states", "Source"], rows)


def gen_smap() -> str:
    rows = []
    for line, c in first_table("D09", "### 5.2 The register"):
        g = sorted(set(re.findall(r"D09-G\d+", " ".join(c))), key=lambda x: int(x[5:]))
        rows.append(
            [c[0], f"`D09`:{line}", ", ".join(g) if g else "none named in the row: D13-G-8"]
        )
    return table(["S-id", "Line", "G-rows the row names"], rows)


def gen_block(key: str) -> str | None:
    if key in COPIES:
        return lift_text(key)
    gens: dict[str, Callable[[], str]] = {
        "states": gen_states,
        "d03map": gen_d03map,
        "matrix": gen_matrix,
        "redline": gen_redline,
        "copycites": gen_copycites,
        "qacases": gen_qacases,
        "components": gen_components,
        "forced": gen_forced,
        "smap": gen_smap,
    }
    fn = gens.get(key)
    return fn() if fn else None


# ---------------------------------------------------------------------------- the deck


SLOT_NAME = re.compile(r"[^{}\n]*[A-Za-z][^{}\n]*")
# the owner lane of each source's PROPOSED strings (RULED BQ-09: "PROPOSED + owner")
DECK_OWNERS = {
    "d05": "E08-D05 (#126)",
    "d06": "E08-D06 (#174)",
    "d07": "E08-D07 (#175)",
    "d07m": "E08-D07 (#175)",
    "d08": "E08-D08 (#176)",
    "d09": "E08-D09 (#177)",
    "e16d5": "E16-D05 (#373)",
    "e17d2": "E17-D02 (#325)",
    "d07.q0": "E08-D13 (#181), taken as written from D12 Q-01 / Q-02",
}


def braced(text: str) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"\{([^{}\n]{1,30})\}|<([a-z][a-z ]{0,20})>", text):
        name = m[1] or m[2]
        if name not in out:
            out.append(name)
    return out


def slots_of(text: str) -> list[str]:
    """The named variables of a string; a braced worked value with no letter (a number, a
    time, a date) is an example, not a variable (round-1 lens F6)."""
    return [n for n in braced(text) if SLOT_NAME.fullmatch(n)]


def examples_of(text: str) -> list[str]:
    return [n for n in braced(text) if not SLOT_NAME.fullmatch(n)]


def unmark(text: str) -> str:
    """The rendered string: the parent's enclosing quotes or code span removed."""
    t = text.strip()
    for q in ('"', "`"):
        if len(t) > 1 and t.startswith(q) and t.endswith(q) and q not in t[1:-1]:
            return t[1:-1]
    return t


def owner_of(key: str) -> str:
    return next(
        (
            o
            for p, o in sorted(DECK_OWNERS.items(), key=lambda kv: -len(kv[0]))
            if key.startswith(p)
        ),
        "",
    )


# the literal values D06's strings carry, named as slots with their format (round-2 read U6):
# (slot name, pattern); the format is D06 §5's number-formatting rules
D06_LITERALS: tuple[tuple[str, str], ...] = (
    ("symbol", r"\b[A-Z0-9]{2,}USDT\b"),
    ("user", r"(?<=viewing as )[a-z]\w*"),
    ("time", r"\b\d{2}:\d{2}(?::\d{2})?(?: UTC)?"),
    ("duration", r"\b\d+(?:\.\d+)? ?(?:ms|s|min|h)\b"),
    ("value", r"(?<![\w.])[-+]?\d+(?:[.,]\d+)*%?(?![\w.])"),
)


def d06_slots(text: str) -> tuple[list[str], list[str]]:
    names: list[str] = []
    examples: list[str] = []
    rest = text
    for name, pat in D06_LITERALS:
        for m in re.finditer(pat, rest):
            if name not in names:
                names.append(name)
            examples.append(m[0])
        rest = re.sub(pat, " ", rest)
    return names, examples


def deck_entry(
    key: str, text: str, cid: str, line: int, status: str, var_line: int
) -> dict[str, object]:
    entry: dict[str, object] = {"text": text, "source": f"`{cid}`:{line}", "status": status}
    if status == "PROPOSED":
        entry["owner"] = owner_of(key)
    slots, examples = slots_of(text), examples_of(text)
    if key.startswith("d06."):
        slots, examples = d06_slots(text)
        lo, _hi = base_block("D06", "## 5. Number formatting")
        var_line = lo
    if slots:
        fmt = f"`{cid}`:{var_line}" if var_line else "not stated by the parent (D13-G-5)"
        entry["slots"] = [{"name": x, "format": fmt} for x in slots]
        entry["plural"] = "none stated by the parent (D13-G-5)"
    if examples:
        entry["examples"] = examples
        if not slots:
            entry["kind"] = "static-example"
    return entry


@functools.cache
def build_deck() -> dict[str, dict[str, dict[str, object]]]:
    strings: dict[str, dict[str, object]] = {}

    def put(key: str, text: str, cid: str, line: int, status: str, var_line: int) -> None:
        strings[key] = deck_entry(key, text, cid, line, status, var_line)

    for prefix, cid, head, idc, strc, rule in DECK_TABLES:
        a, b = base_block(cid, head)
        var_line = next(
            (n for n in range(a, b + 1) if base_line(cid, n).startswith("Variables:")), 0
        )
        seen: dict[str, int] = {}
        for line, cells in first_table(cid, head):
            if idc >= 0:
                rid = cells[idc].strip("` ") if cells else ""
            else:
                s = slug(clean_name(cells[0])) if cells else "row"
                seen[s] = seen.get(s, 0) + 1
                rid = s + (f"-{seen[s]}" if seen[s] > 1 else "")
            if not rid:
                continue
            row_text = " | ".join(cells)
            if rule in ("source", "source-new") and len(cells) > strc:
                cell = cells[strc].strip()
                if not cell or cell == "—":
                    continue
                if rule == "source":
                    status = "verbatim" if "verbatim" in row_text.lower() else "PROPOSED"
                else:
                    status = "PROPOSED" if re.search(r"`new`", row_text) else "verbatim"
                quoted = [q for q in QUOTED.findall(cell) if q.strip()]
                if rule == "source-new" and quoted:
                    for n, q in enumerate(quoted, 1):
                        put(f"{prefix}.{rid}.{n}", q, cid, line, status, var_line)
                else:
                    put(f"{prefix}.{rid}", unmark(cell), cid, line, status, var_line)
                continue
            src = cells[strc] if 0 <= strc < len(cells) else row_text
            for n, q in enumerate(QUOTED.findall(src), 1):
                if not q.strip():
                    continue
                status = "PROPOSED" if f'"{q}" (proposed)'.lower() in src.lower() else rule
                put(f"{prefix}.{rid}.{n}", q, cid, line, status, 0)
    a, b = base_block("E17D2", E17_DECK_HEAD)
    for n in range(a, b + 1):
        ln = base_line("E17D2", n)
        m = re.match(r"^\*\*([A-Z])\.", ln)
        if not m:
            continue
        for k, q in enumerate(QUOTED.findall(ln), 1):
            status = "PROPOSED" if f'"{q}" (PROPOSED)' in ln else "verbatim"
            put(f"e17d2.{m[1]}.{k}", q, "E17D2", n, status, 0)
    for key, (cid, text, status) in DECK_LINES.items():
        put(key, text, cid, line_of(cid, text), status, 0)
    return {"strings": strings}


def deck_document() -> str:
    data = {
        "pack": TICKET_KEY,
        "version": "v1",
        "base": BASE,
        "ruling": RULING_ID,
        "rule": "one entry per parent string, keyed by the parent's row id; built by the tool",
        "strings": build_deck()["strings"],
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------- anchors, markers


def anchored(line: str) -> list[tuple[str, str, int]]:
    out = []
    for m in ANCHOR.finditer(line):
        v = ANCHOR_VALUE.search(line[: m.start()])
        out.append((m[1], v[1] if v else "", m.start()))
    return out


def gen_lines(spec: str, keys: tuple[str, ...]) -> frozenset[int]:
    """0-based indexes of the spec lines under the generated headings named by `keys`."""
    heads = tuple(GEN_HEADS[k] for k in keys)
    out: set[int] = set()
    cur = False
    for i, ln in enumerate(spec.split("\n")):
        m = HEADING.match(ln)
        if m:
            cur = any(m[2].startswith(h) for h in heads)
        elif cur:
            out.add(i)
    return frozenset(out)


def copied_lines(spec: str) -> frozenset[int]:
    return gen_lines(spec, tuple(COPIES))


def all_gen_lines(spec: str) -> frozenset[int]:
    return gen_lines(spec, tuple(GEN_HEADS))


def g_anchor_doc(text: str, values: Values) -> list[Finding]:
    bad: list[Finding] = []
    skip = copied_lines(text)
    for i, ln in enumerate(text.split("\n"), 1):
        if i - 1 in skip:
            continue
        for key, val, _pos in anchored(ln):
            tag = "G-HASH" if key.startswith("HASH:") else "G-ANCHOR"
            if key not in values:
                bad.append(F(tag, f"line {i}: no computed value for {key}", "spec", h2_at(text, i)))
            elif val != values[key]:
                msg = f"line {i}: {key} reads {val!r}, computed {values[key]!r}"
                bad.append(F(tag, msg, "spec", h2_at(text, i)))
        for m in PLACEHOLDER.finditer(ln):
            if not in_code(ln, m.start()):
                msg = f"line {i}: unfilled placeholder {m[0]}"
                bad.append(F("G-ANCHOR", msg, "spec", h2_at(text, i)))
    return bad


def g_marker_doc(text: str) -> list[Finding]:
    bad: list[Finding] = []
    skip = copied_lines(text)
    for i, ln in enumerate(text.split("\n"), 1):
        if i - 1 in skip:
            continue
        for m in COMMENT.finditer(ln):
            if not ANCHOR.fullmatch(m[0]) and not m[0].startswith("<!-- BQ-"):
                msg = f"line {i}: an HTML comment that is not a value anchor"
                bad.append(F("G-MARKER", msg, "spec", h2_at(text, i)))
    return bad


# ---------------------------------------------------------------------------- cites


def cite_refs(line: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for clause in CLAUSE_SPLIT.split(strip_comments(line)):
        events: list[tuple[int, str, str, int, int]] = []
        for m in KEY_TOKEN.finditer(clause):
            events.append((m.start(), "key", m[1] or m[2], 0, 0))
        for m in KEY_REF.finditer(clause):
            a = int(m[3])
            events.append((m.end() - 1, "ref", "", a, int(m[4]) if m[4] else a))
        for m in REF_TOKEN.finditer(clause):
            a = int(m[1])
            events.append((m.start(), "ref", "", a, int(m[2]) if m[2] else a))
        events.sort(key=lambda e: e[0])
        cur: str | None = None
        for _pos, kind, key, a, b in events:
            if kind == "key":
                cur = key
            elif cur is not None and cur in CITE_FILES:
                out.append((cur, a, b))
    return out


def unique_block(base: list[str], a: int, b: int) -> list[str]:
    lo, hi = a - 1, b
    while base[lo:hi] and base.count(base[lo]) > 1 and (lo > 0 or hi < len(base)):
        lo, hi = max(0, lo - 1), min(len(base), hi + 1)
    return base[lo:hi]


@functools.cache
def head_joined_git(rel: str) -> str:
    return "\n" + (git_show(HEAD, rel) or "") + "\n"


def head_joined(rel: str) -> str:
    for r, text in reversed(HEAD_OVERRIDE):
        if r == rel:
            return "\n" + text + "\n"
    return head_joined_git(rel)


def spec_cite_lines(spec: str) -> list[tuple[int, str]]:
    skip = copied_lines(spec)
    return [(i, ln) for i, ln in enumerate(spec.split("\n"), 1) if i - 1 not in skip]


def cite_findings(t: Texts) -> tuple[list[Finding], int]:
    fails: list[Finding] = []
    done: set[tuple[str, int, int]] = set()
    # post-merge, every cite is judged at its frozen base, not at the moving main
    at_head = not post_merge() or bool(VERSION_AT_HEAD)
    if at_head and not head_ok():
        fails.append(F("G-VERSION", f"{HEAD} does not resolve: no range compared", None, None))
    deck_lines = [str(e.get("source", "")) for e in deck_entries(t.deck).values()]
    sources = [
        ("spec", [(i, ln, h2_at(t.spec, i)) for i, ln in spec_cite_lines(t.spec)]),
        ("deck", [(i, " " + ln, "(deck)") for i, ln in enumerate(deck_lines, 1)]),
    ]
    for doc, rows in sources:
        for _i, ln, sec in rows:
            for cid, a, b in cite_refs(ln):
                if (cid, a, b) in done:
                    continue
                done.add((cid, a, b))
                lines = base_lines(cid)
                if lines == [""]:
                    fails.append(F("G-CITE", f"{cid} is not readable at the base", doc, sec))
                    continue
                if a < 1 or b > len(lines) or b < a:
                    msg = f"{cid}:{a}-{b} is outside the file ({len(lines)} lines)"
                    fails.append(F("G-CITE", msg, doc, sec))
                    continue
                if not lines[a - 1].strip() or not lines[b - 1].strip():
                    msg = f"{cid}:{a}-{b} starts or ends on a blank line"
                    fails.append(F("G-CITE", msg, doc, sec))
                if at_head and head_ok():
                    block = unique_block(lines, a, b)
                    if ("\n" + "\n".join(block) + "\n") not in head_joined(CITE_FILES[cid]):
                        msg = f"{cid}:{a}-{b} was edited at {HEAD}"
                        fails.append(F("G-VERSION", msg, doc, sec))
    return fails, len(done)


@functools.cache
def loose_source(cid: str) -> str:
    return loose(source_text(cid))


@functools.cache
def core_sources() -> str:
    keys = ("D03", "D04", "D05", "D06", "D07", "D08", "D09", "D11", "D12", "E17D2", "E16D5")
    return loose("\n".join(source_text(c) for c in (*keys, "14", "15", "02", "E08J")))


def g_quote(t: Texts) -> list[Finding]:
    entries = deck_entries(t.deck)
    deck_text = loose("\n".join(str(e.get("text", "")) for e in entries.values()))
    ruled = loose("\n".join(RULING_QUOTES))
    skip = all_gen_lines(t.spec)
    bad: list[Finding] = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if i - 1 in skip:
            continue
        cited = tuple(dict.fromkeys(c for c, _a, _b in cite_refs(ln)))
        for q in QUOTED.findall(strip_comments(ln)):
            q = q.strip()
            if len(q) < QUOTE_MIN or "…" in q or "<" in q:
                continue
            lq = loose(q)
            if (
                lq in deck_text
                or lq in ruled
                or any(lq in loose_source(c) for c in cited)
                or lq in core_sources()
            ):
                continue
            msg = f"line {i}: {q[:60]!r} is in no cited source, the deck or the ruling"
            bad.append(F("G-QUOTE", msg, "spec", h2_at(t.spec, i)))
    return bad


def g_version(t: Texts) -> list[Finding]:
    lines = t.spec.split("\n")
    i = next((n for n, ln in enumerate(lines) if ln.startswith("**Start.**")), None)
    if i is None:
        return [F("G-VERSION", "no **Start.** line", "spec", "(top)")]
    line, sec = lines[i], h2_at(t.spec, i + 1)
    bad: list[Finding] = []
    if f"**v1 at base `{BASE}`.**" not in line:
        bad.append(F("G-VERSION", "the version line does not name v1 at the base", "spec", sec))
    bad += [
        F("G-VERSION", f"`{s}` is not a commit under the base", "spec", sec)
        for s in re.findall(r"`([0-9a-f]{10})`", line)
        if not under_base(s)
    ]
    pinned = line.split("**Pinned at their last touch at the base:**", 1)[-1].split("**", 1)[0]
    for cid, sha in PINNED_DOCS.items():
        last = last_touch(cid)
        if last != sha or f"`{sha}`" not in pinned:
            bad.append(F("G-VERSION", f"{cid} pinned at {sha}, last touched {last}", "spec", sec))
    named = line.split("**Named only, never pinned or quoted:**", 1)[-1].split("**", 1)[0]
    bad += [
        F("G-VERSION", f"{n} is not in the named-only list", "spec", sec)
        for n in NAMED_ONLY
        if not re.search(re.escape(n) + r"(?![\w-])", named)
    ]
    inputs = next((ln for ln in lines if ln.startswith("**Inputs pinned.**")), "")
    if inputs.count(BASE) < 2:
        bad.append(F("G-VERSION", f"the Inputs line does not name {BASE} twice", "spec", sec))
    vsec = spec_sec(t, VERSION_HEAD)
    rows = rows_of(t.spec, VERSION_HEAD)
    if post_merge():
        bad += [F("G-VERSION", m, "spec", vsec) for m in post_merge_version_problems(t.spec)]
    elif not rows or any(r[0] != "v1" or r[1] != f"`{BASE}`" for r in rows):
        bad.append(F("G-VERSION", "a versions row is not v1 at the base", "spec", vsec))
    body = norm_text(section(t.spec, VERSION_HEAD))
    for need in ("re-sync needed", "posted once on each affected consumer", "affected story"):
        if need not in body:
            bad.append(F("G-VERSION", f"§15 lacks {need!r}", "spec", vsec))
    d = deck_data(t.deck)
    if d.get("base") != BASE or d.get("version") != "v1" or d.get("pack") != TICKET_KEY:
        msg = "the deck's pack, base or version is not E08-D13 v1 at the base"
        bad.append(F("G-VERSION", msg, "deck", "(deck)"))
    return bad


# ---------------------------------------------------------------------------- generated blocks


def g_copy(t: Texts) -> list[Finding]:
    bad: list[Finding] = gen_findings(t, ("copycites",), "G-COPY")
    if any(refind_14(n) == 0 for _k, n in copied_14_cites()):
        bad.append(F("G-COPY", "a `14` cite inside a copy is not re-found", "spec", None))
    joined = "\n" + t.spec + "\n"
    for key in COPIES:
        cid, a, b = lift_range(key)
        block = lift_text(key)
        sec = spec_sec(t, GEN_HEADS[key])
        n = joined.count("\n" + block + "\n") if block else 0
        if n != 1:
            msg = f"{cid}:{a}-{b} ({key}) is present {n} times byte for byte, not once"
            bad.append(F("G-COPY", msg, "spec", sec))
        elif section(t.spec, GEN_HEADS[key]).strip("\n") != block:
            bad.append(F("G-COPY", f"{key} is not the whole body of its heading", "spec", sec))
    return bad


def norm_rows(block: str) -> list[list[str]]:
    return [[unesc(c) for c in r] for r in table_rows(block)]


def gen_findings(t: Texts, keys: tuple[str, ...], tag: str) -> list[Finding]:
    bad: list[Finding] = []
    for key in keys:
        head = GEN_HEADS[key]
        sec = spec_sec(t, head)
        want = norm_rows(gen_block(key) or "")
        have = norm_rows(section(t.spec, head))
        if not want:
            bad.append(F(tag, f"{key}: the generator built nothing", "spec", sec))
        elif have != want:
            diff = next(
                (i for i, (x, y) in enumerate(zip(have, want, strict=False)) if x != y),
                min(len(have), len(want)),
            )
            msg = f"{key}: row {diff + 1} differs from the base ({len(have)} vs {len(want)} rows)"
            bad.append(F(tag, msg, "spec", sec))
    return bad


def wire_cell_problems(spec: str) -> list[str]:
    """Every `wire:` cell of the state table names a field and the line that DEFINES it (a
    `22` schema, property or enum line; a `23` / `24` table first cell, heading or typed
    field; an HTTP path or status key); a bare mention fails (round-1 lens F1, F2)."""
    out: list[str] = []
    for r in table_rows(section(spec, STATES_HEAD)):
        if len(r) < 4 or not r[3].startswith("wire:"):
            continue
        m = re.match(r"wire: (?:`([^`]+)`|HTTP (\d{3})) \(`(\d\d)`:(\d+)\)", unesc(r[3]))
        if not m:
            out.append(f"{r[0]}: an unreadable wire cell")
            continue
        cid, n = m[3], int(m[4])
        if m[2]:
            ok = bool(re.match(rf"^\s+['\"]{m[2]}['\"]:", base_line(cid, n)))
        else:
            ok = defines(cid, n, m[1])
        if not ok:
            out.append(f"{r[0]}: `{cid}`:{n} does not define {m[1] or m[2]}")
    return out


def g_states(t: Texts) -> list[Finding]:
    bad = gen_findings(t, ("states", "d03map", "qacases", "forced", "smap"), "G-STATES")
    sec = spec_sec(t, STATES_HEAD)
    bad += [F("G-STATES", m, "spec", sec) for m in wire_cell_problems(t.spec)]
    body = norm_text(section(t.spec, "5.3 Test identifiers"))
    for need in ("PROPOSED", "scr103-drawer", "the accessible name"):
        if need not in body:
            msg = f"§5.3 lacks {need!r}"
            bad.append(F("G-STATES", msg, "spec", spec_sec(t, "5.3 Test identifiers")))
    return bad


def g_rbac(t: Texts) -> list[Finding]:
    return gen_findings(t, ("matrix",), "G-RBAC")


def g_redline(t: Texts) -> list[Finding]:
    return gen_findings(t, ("redline",), "G-REDLINE")


def frozen_digest(spec: str, head: str) -> str:
    body = "\n".join(
        " | ".join(unesc(c) for c in split_row(ln)) if ln.lstrip().startswith("|") else ln.strip()
        for ln in section(spec, head).split("\n")
        if ln.strip() and not is_rule(ln)
    )
    return hashlib.sha256(norm_text(body).encode("utf-8")).hexdigest()[:16]


def g_frozen(t: Texts) -> list[Finding]:
    """The frozen set: a changed matrix cell is G-RBAC's (the block no longer equals the base);
    G-FROZEN catches the never-rendered list and a matrix that changed with its parents."""
    bad: list[Finding] = []
    for head in FROZEN_HEADS:
        if head == MATRIX_HEAD and gen_findings(t, ("matrix",), "G-RBAC"):
            continue
        got = frozen_digest(t.spec, head)
        if got != FROZEN_SHA[head]:
            msg = f"the frozen set {head!r} reads {got}, frozen {FROZEN_SHA[head]}"
            bad.append(F("G-FROZEN", msg, "spec", spec_sec(t, head)))
    return bad


def g_deck(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    entries = deck_entries(t.deck)
    want = build_deck()["strings"]
    if entries != want:
        diff = sorted(set(entries) ^ set(want)) or [k for k in want if entries.get(k) != want[k]]
        msg = f"the deck differs from the parents at {', '.join(diff[:3])}"
        bad.append(F("G-DECK", msg, "deck", "(deck)"))
    for key, e in entries.items():
        text = str(e.get("text", ""))
        if DECK_BANNED.search(text):
            bad.append(F("G-DECK", f"{key}: a placeholder word", "deck", "(deck)"))
        refs = cite_refs(" " + str(e.get("source", "")))
        src_line = base_line(refs[0][0], refs[0][1]) if refs else ""
        if not refs or text.replace("\\|", "|") not in src_line.replace("\\|", "|"):
            bad.append(F("G-DECK", f"{key}: not verbatim at its source line", "deck", "(deck)"))
        if e.get("status") == "PROPOSED" and not str(e.get("owner", "")).strip():
            bad.append(F("G-DECK", f"{key}: PROPOSED with no owner", "deck", "(deck)"))
        raw = e.get("slots", [])
        slots = raw if isinstance(raw, list) else []
        declared = [str(s.get("name")) for s in slots if isinstance(s, dict)]
        if any(s not in declared for s in slots_of(text)):
            bad.append(F("G-DECK", f"{key}: a slot is used and not defined", "deck", "(deck)"))
    return bad


# ---------------------------------------------------------------------------- tables against sources


ID_RANGE = re.compile(r"\b([A-Z][A-Z0-9]?)-(\d\d)(?:\.\.|–)(?:\1-)?(\d\d)\b")
ID_ONE = re.compile(r"\b(KB|PP|FM|RG|SR|BG|T2|SD)-\d\d\b")


def named_ids(text: str) -> set[str]:
    out = {m[0] for m in ID_ONE.finditer(text)}
    for m in ID_RANGE.finditer(text):
        if m[1] in D12_FAMILIES:
            for n in range(int(m[2]), int(m[3]) + 1):
                out.add(f"{m[1]}-{n:02d}")
    return out


def g_index(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, INDEX_HEAD)
    index = strip_comments(section(t.spec, INDEX_HEAD))
    chapter = strip_comments(section(t.spec, "7. The accessibility"))
    known = {i for p in D12_FAMILIES for i in family_ids(p)}
    for rid in sorted(named_ids(index) - known):
        bad.append(F("G-INDEX", f"{rid} is named in §7.6 and is not a D12 row", "spec", sec))
    for p in D12_FAMILIES:
        if p == "SD":
            continue
        for rid in family_ids(p):
            if rid not in named_ids(index) and not (rid in SUPERSEDED and rid in chapter):
                bad.append(F("G-INDEX", f"{rid} is missing from the §7.6 index", "spec", sec))
    return bad


def g_cmp(t: Texts) -> list[Finding]:
    bad: list[Finding] = gen_findings(t, ("components",), "G-CMP")
    for head in (COMP_HEAD, NEW_HEAD):
        sec = spec_sec(t, head)
        for cmp in sorted(set(re.findall(r"CMP-\d{3}", strip_comments(section(t.spec, head))))):
            if not line_of("15", f"### {cmp} "):
                bad.append(F("G-CMP", f"{cmp} is not an entry of `15` at the base", "spec", sec))
    sec = spec_sec(t, COMP_HEAD)
    for r in rows_of(t.spec, COMP_HEAD):
        refs = cite_refs(" " + r[1]) if len(r) > 1 else []
        if not refs:
            bad.append(F("G-CMP", f"{r[0]}: no `14` Components cite", "spec", sec))
            continue
        cid, n, _b = refs[0]
        above = max(
            (i for i in range(1, n) if base_line("14", i).startswith("### SCR-")), default=0
        )
        if cid != "14" or not base_line("14", n).startswith("- **Components:**"):
            bad.append(F("G-CMP", f"{r[0]}: {cid}:{n} is not a Components line", "spec", sec))
        elif not base_line("14", above).startswith(f"### {r[0]} "):
            bad.append(F("G-CMP", f"{r[0]}: `14`:{n} is another screen's line", "spec", sec))
    return bad


def g_checklist(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    cl = checklist_14()
    ticked = rows_of(t.spec, TICKED_HEAD)
    opened = rows_of(t.spec, OPENCL_HEAD)
    for scr in SCREENS:
        if scr not in cl:
            bad.append(F("G-CHECKLIST", f"{scr} has no checklist line in `14`", None, None))
            continue
        line, tk, op = cl[scr]
        num = scr.removeprefix("SCR-")
        nt = sum(1 for r in ticked if r[0].startswith(f"{num}-"))
        no = sum(1 for r in opened if r[0].startswith(f"{num}-"))
        if (nt, no) != (tk, op):
            msg = f"{scr}: §9 lists {nt} ticked / {no} open, `14`:{line} has {tk} / {op}"
            bad.append(F("G-CHECKLIST", msg, "spec", spec_sec(t, TICKED_HEAD)))
    return bad


def g_budget(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    body = section(t.spec, BUDGET_HEAD)
    for key in CITES:
        if key.startswith("b") and f"<!--=CITE:{key}-->" not in body:
            msg = f"the budget {key} has no CITE anchor in §10.1"
            bad.append(F("G-BUDGET", msg, "spec", spec_sec(t, BUDGET_HEAD)))
    for key in ("virt.default", "virt.d09"):
        if f"<!--=CITE:{key}-->" not in t.spec:
            bad.append(F("G-BUDGET", f"{key} is not anchored", "spec", spec_sec(t, BUDGET_HEAD)))
    return bad


STORY_KEYS = re.compile(r"\bE08-[SDQT]\d\d\b")


def g_story(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, STORY_HEAD)
    idx = ticket_index()
    for r in rows_of(t.spec, STORY_HEAD):
        for key in STORY_KEYS.findall(r[0]):
            pending = "pending" in r[0]
            if key not in idx and not pending:
                bad.append(F("G-STORY", f"{key} is not in the ticket JSON", "spec", sec))
            if key in idx and pending:
                msg = f"{key} is filed: its row must stop reading pending"
                bad.append(F("G-STORY", msg, "spec", sec))
    deltas = norm_text(section(t.spec, DELTA_HEAD))
    for key in ("E08-S08", "E08-S10", "E08-S11", "E08-Q05", "E08-D14"):
        body = str(idx.get(key, {}).get("body", ""))
        for m in re.finditer(r"once merged, `(docs/design/[^`]+)`", body):
            path = m[1]
            if git_show(BASE, path) is not None and key not in deltas:
                msg = f"{key}'s body says 'once merged' for a merged file; no C-row"
                bad.append(F("G-STORY", msg, "spec", spec_sec(t, DELTA_HEAD)))
    return bad


def g_ahead(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, AHEAD_HEAD)
    idx = ticket_index()
    rows = rows_of(t.spec, AHEAD_HEAD)
    if not rows:
        bad.append(F("G-AHEAD", "§11.1 has no table", "spec", sec))
    for r in rows:
        keys = STORY_KEYS.findall(r[0])
        if not keys or len(r) < 2:
            continue
        sprint = str(idx.get(keys[0], {}).get("sprint", ""))
        if keys[0] in idx and sprint.removeprefix("Sprint ") not in r[1]:
            bad.append(F("G-AHEAD", f"{keys[0]}: the sprint cell is not {sprint!r}", "spec", sec))
    return bad


OPEN_ID = re.compile(r"`(?:(?:[A-Z0-9]+):)?([A-Za-z0-9-]+)`")


def g_openrows(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, OPEN_HEAD)
    for r in rows_of(t.spec, OPEN_HEAD):
        if len(r) < 2:
            continue
        refs = cite_refs(" " + r[1])
        ids = OPEN_ID.findall(r[0].split("(")[0])
        if not refs or not ids:
            continue
        cid, a, b = refs[0]
        text = "\n".join(base_lines(cid)[a - 1 : b])
        for rid in ids:
            if not re.search(rf"(?<![\w-]){re.escape(rid)}(?![\w])", text):
                msg = f"{rid} is not in {cid}:{a}-{b}"
                bad.append(F("G-OPENROWS", msg, "spec", sec))
    return bad


def pointer_problems(text: str, base: str) -> list[str]:
    lines = text.split("\n")
    out: list[str] = []
    ptrs = set(POINTERS.values())
    if [ln for ln in lines if ln not in ptrs] != base.split("\n"):
        out.append("`14` differs from the merge-base beyond the nine pointer lines")
    for scr, ptr in POINTERS.items():
        at = [i for i, ln in enumerate(lines) if ln == ptr]
        if len(at) != 1:
            out.append(f"{scr}'s pointer line appears {len(at)} times, not once")
            continue
        head = max(
            (i for i, ln in enumerate(lines[: at[0]]) if ln.startswith("### SCR-")), default=-1
        )
        prev = lines[at[0] - 1] if at[0] else ""
        if head < 0 or not lines[head].startswith(f"### {scr} "):
            out.append(f"{scr}'s pointer line is not under {scr}")
        elif not prev.startswith(A11Y_PREFIX):
            out.append(f"{scr}'s pointer line is not directly after its D12 a11y line")
    if any("[x]" in ln for ln in lines if ln.startswith(CHECKLIST_PREFIX)) != any(
        "[x]" in ln for ln in base.split("\n") if ln.startswith(CHECKLIST_PREFIX)
    ):
        out.append("a checklist tick changed")
    return out


def own_paths() -> tuple[str, ...]:
    return tuple(p for p in OWN_PATHS if p != PLAN14_REL) if post_merge() else OWN_PATHS


def stray_paths_at(ref: str) -> tuple[str, ...] | None:
    ok_diff, diff = git_ok("diff", "--name-only", ref)
    ok_new, new = git_ok("ls-files", "--others", "--exclude-standard")
    if not (ok_diff and ok_new):
        return None
    names = [*diff.split("\n"), *new.split("\n")]
    post = post_merge()  # post-merge, a fix to this tool may ship with its sibling design tools
    return tuple(
        sorted(
            {
                n
                for n in names
                if n and n not in own_paths() and not (post and n.startswith("docs/design/_tools/"))
            }
        )
    )


def g_untouched(t: Texts) -> list[Finding]:
    ref = merge_base()
    if not ref:
        return [F("G-UNTOUCHED", f"no merge-base with {HEAD}: nothing compared", None, None)]
    bad: list[Finding] = []
    post = post_merge()
    override = dict(PLAN_OVERRIDE)
    for cid, text in t.plans:
        text = override.get(cid, text)
        base = git_show(ref, CITE_FILES[cid])
        if base is None:
            bad.append(F("G-UNTOUCHED", f"{cid} is not readable at {ref[:10]}", None, None))
        elif cid == "14" and not post:
            bad += [F("G-UNTOUCHED", m, None, None) for m in pointer_problems(text, base)]
        elif text != base:
            bad.append(F("G-UNTOUCHED", f"{cid} differs from {ref[:10]}", None, None))
    strays = stray_paths_at(ref)
    if strays is None:
        return [*bad, F("G-UNTOUCHED", "a git call failed: no path compared", None, None)]
    bad += [
        F("G-UNTOUCHED", f"{p} is not this PR's path", None, None)
        for p in sorted({*strays, *EXTRA_PATHS})
    ]
    return bad


def g_walk(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, WALK_HEAD)
    rows = rows_of(t.spec, WALK_HEAD)
    if len(rows) != len(WALK_ROLES) or any(
        not r[0].startswith(role) for r, role in zip(rows, WALK_ROLES, strict=False)
    ):
        bad.append(F("G-WALK", f"§14.3 does not list the {len(WALK_ROLES)} roles", "spec", sec))
    for r in rows:
        pending = r[-1] == WALK_PENDING
        if pending and STRICT_WALK:
            bad.append(F("G-WALK", f"{r[0][:20]}: still pending at READY", "spec", sec))
        if not pending and not all(re.fullmatch(r"\d+|—", c) for c in r[2:6]):
            bad.append(F("G-WALK", f"{r[0][:20]}: counts are not numbers", "spec", sec))
    return bad


def img_names() -> frozenset[str]:
    if IMG_OVERRIDE:
        return IMG_OVERRIDE[-1]
    out: set[str] = set()
    for d in IMG_DIRS:
        folder = ROOT / d
        if folder.is_dir():
            out |= {p.name for p in folder.glob("*.png")}
    return frozenset(out)


def g_png(t: Texts) -> list[Finding]:
    have = img_names()
    sec = spec_sec(t, FRAME_HEAD)
    names = set(PNG_NAME.findall(t.spec))
    bad = [F("G-PNG", f"{n} is not committed", "spec", sec) for n in sorted(names - have)]
    if not names:
        bad.append(F("G-PNG", "no board PNG is named", "spec", sec))
    return bad


def g_status(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    sec = spec_sec(t, STATUS_HEAD)
    rows = raw_rows(t.spec, STATUS_HEAD)
    if not rows:
        bad.append(F("G-STATUS", "§0 has no status table", "spec", sec))
    for r in rows:
        if len(r) < 4:
            continue
        built = r[3]
        if built.startswith("yes") and "present<!--=STATUS:" not in built:
            bad.append(F("G-STATUS", f"{r[0][:24]}: 'yes' with no present probe", "spec", sec))
        if built.startswith("no") and "present<!--=STATUS:" in built:
            bad.append(F("G-STATUS", f"{r[0][:24]}: 'no' while the probe is present", "spec", sec))
    return bad


def g_ruled(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    first = next((ln for ln in t.spec.split("\n") if ln.startswith("**Ticket:**")), "")
    if STAMP not in first:
        bad.append(F("G-RULED", "the header does not carry the ruling stamp", "spec", "(top)"))
    sec = spec_sec(t, RULED_HEAD)
    body = section(t.spec, RULED_HEAD)
    for n in range(1, BQ_TOTAL + 1):
        if f"BQ-{n:02d}" not in body:
            bad.append(F("G-RULED", f"BQ-{n:02d} is not in the ruled section", "spec", sec))
    if RULING_ID not in body:
        bad.append(F("G-RULED", "the ruled section does not cite the ruling", "spec", sec))
    if re.search(r"<!--\s*BQ-\d\d", t.spec):
        bad.append(F("G-RULED", "a draft BQ marker is left", "spec", sec))
    return bad


def scan(t: Texts, tag: str, hit: Callable[[str], bool], what: str) -> list[Finding]:
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            if hit(ln):
                where = h2_at(text, i) if doc == "spec" else "(deck)"
                bad.append(F(tag, f"{doc} line {i}: {what}", doc, where))
    return bad


def g_hex(t: Texts) -> list[Finding]:
    return scan(t, "G-HEX", lambda ln: bool(HEXLIT.search(ln)), "a hex colour literal")


def g_penpot(t: Texts) -> list[Finding]:
    return scan(
        t,
        "G-PENPOT",
        lambda ln: bool(URL.search(ln) or UUID.search(ln) or PENPOT_WORDS.search(ln)),
        "a URL, hostname, UUID or workspace word",
    )


def g_names(t: Texts) -> list[Finding]:
    return scan(t, "G-NAMES", lambda ln: bool(NAMES.search(ln)), "an agent, user or host name")


def g_words(t: Texts) -> list[Finding]:
    words = banned_words()
    return scan(t, "G-WORDS", lambda ln: any(w in ln.lower() for w in words), "a banned word")


def g_close(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    hits = [(i, m[0]) for i, ln in enumerate(t.spec.split("\n"), 1) for m in CLOSING.finditer(ln)]
    ok_secs = ("(top)", spec_sec(t, RULED_HEAD), spec_sec(t, SIGN_HEAD))
    allowed = [h for h in hits if h[1] == "Closes #181" and h2_at(t.spec, h[0]) in ok_secs]
    for i, word in hits:
        if (i, word) not in allowed:
            msg = f"line {i}: {word!r} outside the header, the ruled section and §16"
            bad.append(F("G-CLOSE", msg, "spec", h2_at(t.spec, i)))
    if len(allowed) > 3:
        bad.append(F("G-CLOSE", "`Closes #181` is stated more than three times", "spec", "(top)"))
    for i, ln in enumerate(t.deck.split("\n"), 1):
        if CLOSING.search(ln):
            bad.append(F("G-CLOSE", f"deck line {i}: a closing keyword", "deck", "(deck)"))
    return bad


def g_session(t: Texts) -> list[Finding]:
    bad: list[Finding] = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if SESSION_WORDS.search(ln) and "none is claimed" not in ln:
            msg = f"line {i}: a session or meeting is claimed"
            bad.append(F("G-SESSION", msg, "spec", h2_at(t.spec, i)))
    need = "no walkthrough session was held or recorded, and none is claimed"
    if need not in norm_text(section(t.spec, PROTO_HEAD)).lower():
        msg = "§14.2 does not say that no session was held"
        bad.append(F("G-SESSION", msg, "spec", spec_sec(t, PROTO_HEAD)))
    return bad


# ---------------------------------------------------------------------------- pins (G-RULED-PIN)


def unvalued(line: str, values: Values) -> str:
    out = line
    for key, val, _pos in anchored(line):
        if val and val == values.get(key, val):
            out = out.replace(f"{val}<!--={key}-->", f"<!--={key}-->", 1)
    return out


def line_form(line: str) -> str:
    s = line.lstrip()
    if s.startswith(("- ", "* ")):
        return "b"
    if re.match(r"^\d{1,2}\. ", s):
        return "n"
    return "p"


def spec_units(text: str, values: Values) -> list[Unit]:
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
            key = " > ".join(p[1] for p in path)
            count[key] = count.get(key, 0) + 1
            region, k, seen, shape, nf = f"{key}#{count[key]}", 0, {}, "h", 0
            out.append(("spec", region, "heading", pin_norm(ln)))
            continue
        indent = "i" if raw.startswith((" ", "\t")) else ""
        if not ln.strip():
            shape += "."
        elif is_rule(ln):
            shape += "r"
            rule = pin_norm(re.sub(r"-+", "-", ln))
            out.append(("spec", region, f"rule {shape.count('r')}", rule))
        elif re.match(r"^ {0,3}\|", ln):
            shape += indent + "t"
            rid = pin_norm(split_row(ln)[0])[:60] or "(blank)"
            seen[rid] = seen.get(rid, 0) + 1
            loc = f"row {rid}" + (f"#{seen[rid]}" if seen[rid] > 1 else "")
            out.append(("spec", region, loc, " | ".join(pin_norm(c) for c in split_row(ln))))
        else:
            sents = [x for x in FULL_STOP.split(ln.strip()) if x.strip()]
            shape += f"{indent}{line_form(ln)}{len(sents)}"
            for s in sents:
                k += 1
                out.append(("spec", region, f"s{k}", pin_norm(s)))
    out.append(("spec", region, "shape", shape))
    return out


def deck_units(deck: str) -> list[Unit]:
    data = deck_data(deck)
    meta = {k: v for k, v in data.items() if k != "strings"}
    out: list[Unit] = [
        ("deck", "(meta)#1", "meta", json.dumps(meta, ensure_ascii=False, sort_keys=True))
    ]
    for key, e in deck_entries(deck).items():
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
        "# E08-D13 pins (every unit of the pack and every deck entry): doc, region (heading path"
        f" #occurrence), location, the exact normalised text; {len(units)} units.\n# Written by "
        "`--repin-ruled` only; `--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in units)


def sec_of_region(spec: str, region: str) -> str:
    parts = region.rsplit("#", 1)[0].split(" > ")
    heads = [
        pin_norm(m[2]) for ln in spec.split("\n") if (m := HEADING.match(ln)) and len(m[1]) == 2
    ]
    return next((p for p in parts if p in heads), "(top)")


def pin_findings(t: Texts) -> list[Finding]:
    path = ROOT / PIN_REL
    if not path.exists():
        return [F("G-RULED-PIN", f"{PIN_REL} is missing: run --repin-ruled", None, None)]
    text = path.read_text(encoding="utf-8")
    m = re.search(r"; (\d+) units\.", text.split("\n", 1)[0])
    pinned = parse_pins(text)
    bad: list[Finding] = []
    if not m or int(m[1]) != len(pinned):
        msg = "the pins header count does not match the parsed units"
        bad.append(F("G-RULED-PIN", msg, None, None))
    if PIN_UNITS_OVERRIDE:
        pinned = PIN_UNITS_OVERRIDE[-1]
    current = set(ruled_units(t.spec, t.deck, t.values))
    pinned_set = set(pinned)
    for what, units in (
        ("not pinned (changed or new)", current - pinned_set),
        ("pinned unit gone", pinned_set - current),
    ):
        for doc, region, loc, _text in sorted(units):
            sec = sec_of_region(t.spec, region) if doc == "spec" else "(deck)"
            bad.append(F("G-RULED-PIN", f"{doc} {region[:40]} {loc[:30]}: {what}", doc, sec))
    return bad


# ---------------------------------------------------------------------------- audit

MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_version,
    g_quote,
    g_copy,
    g_states,
    g_rbac,
    g_frozen,
    g_redline,
    g_deck,
    g_index,
    g_cmp,
    g_checklist,
    g_budget,
    g_story,
    g_ahead,
    g_openrows,
    g_untouched,
    g_walk,
    g_png,
    g_status,
    g_ruled,
    g_hex,
    g_penpot,
    g_names,
    g_close,
    g_words,
    g_session,
)
GATE_NAMES = (
    "G-ANCHOR",
    "G-HASH",
    "G-MARKER",
    "G-CITE",
    "G-VERSION",
    "G-QUOTE",
    "G-COPY",
    "G-STATES",
    "G-RBAC",
    "G-FROZEN",
    "G-REDLINE",
    "G-DECK",
    "G-INDEX",
    "G-CMP",
    "G-CHECKLIST",
    "G-BUDGET",
    "G-STORY",
    "G-AHEAD",
    "G-OPENROWS",
    "G-UNTOUCHED",
    "G-WALK",
    "G-PNG",
    "G-STATUS",
    "G-RULED",
    "G-HEX",
    "G-PENPOT",
    "G-NAMES",
    "G-CLOSE",
    "G-WORDS",
    "G-SESSION",
    "G-RULED-PIN",
)


def audit(t: Texts) -> tuple[list[str], list[str], int]:
    """(FAIL lines, WARN lines, cites checked). One FAIL line per gate; a pin finding in a
    section another gate already FAILs is demoted to a WARN line."""
    found: list[Finding] = []
    found += g_anchor_doc(t.spec, t.values)
    found += g_marker_doc(t.spec)
    cf, n = cite_findings(t)
    found += cf
    for gate in MEASURED_GATES:
        found += gate(t)
    flagged = {(f[2], f[3]) for f in found if f[2] is not None}
    pins = pin_findings(t)
    warns = [f"WARN [G-RULED-PIN] {p[1][:150]}" for p in pins if (p[2], p[3]) in flagged]
    found += [p for p in pins if (p[2], p[3]) not in flagged]
    merged: dict[str, list[str]] = {}
    for tag, msg, _d, _s in found:
        merged.setdefault(tag, []).append(msg)
    fails = []
    for tag, msgs in merged.items():
        msgs = list(dict.fromkeys(msgs))
        more = f" (+{len(msgs) - 4} more)" if len(msgs) > 4 else ""
        fails.append(f"[{tag}] " + "; ".join(m[:150] for m in msgs[:4]) + more)
    return fails, warns, n


# ---------------------------------------------------------------------------- self-test

Edit = Callable[[str], str]


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str
    what: str
    spec: Edit | None = None
    deck: Edit | None = None
    lever: Callable[[], Callable[[], None]] | None = None


def sub(old: str, new: str) -> Edit:
    def edit(text: str) -> str:
        return text.replace(old, new, 1) if old in text else text

    return edit


def rx_sub(pattern: str, new: str) -> Edit:
    def edit(text: str) -> str:
        return re.sub(pattern, new, text, count=1, flags=re.MULTILINE)

    return edit


def cell_set(prefix: str, col: int, new: str) -> Edit:
    """Rewrite cell `col` (0-based) of the first table row whose lead cell starts with `prefix`."""

    def edit(text: str) -> str:
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            cells = split_row(ln) if ln.startswith("|") else []
            if cells and cells[0].startswith(prefix) and col < len(cells):
                cells[col] = new
                lines[i] = "| " + " | ".join(cells) + " |"
                return "\n".join(lines)
        return text

    return edit


def deck_edit(fn: Callable[[dict[str, dict[str, object]]], None]) -> Edit:
    def edit(deck: str) -> str:
        data = json.loads(deck)
        fn(data["strings"])
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    return edit


def deck_text(key: str, text: str) -> Edit:
    def fn(s: dict[str, dict[str, object]]) -> None:
        s[key]["text"] = text

    return deck_edit(fn)


def popper(lst: list[_T]) -> Callable[[], None]:
    def undo() -> None:
        lst.pop()

    return undo


def lever_extra_path() -> Callable[[], None]:
    EXTRA_PATHS.append("docs/plan/22-api-openapi.yaml")
    return popper(EXTRA_PATHS)


def lever_plan14_edit() -> Callable[[], None]:
    """Post-merge mode: `14` carries one stray line over the merge-base."""
    POST_MERGE_OVERRIDE.append(True)
    text = (ROOT / PLAN14_REL).read_text(encoding="utf-8")
    PLAN_OVERRIDE.append(("14", text + "\nA stray line.\n"))

    def undo() -> None:
        PLAN_OVERRIDE.pop()
        POST_MERGE_OVERRIDE.pop()

    return undo


def lever_pointer_moved() -> Callable[[], None]:
    """PR-1 mode: the SCR-104 pointer line sits after the checklist instead of the a11y line."""
    lines = (ROOT / PLAN14_REL).read_text(encoding="utf-8").split("\n")
    ptr = POINTERS["SCR-104"]
    if ptr in lines:
        i = lines.index(ptr)
        lines.pop(i)
        lines.insert(i - 2, ptr)
    PLAN_OVERRIDE.append(("14", "\n".join(lines)))
    return popper(PLAN_OVERRIDE)


def lever_head_edit() -> Callable[[], None]:
    rel = CITE_FILES["D07"]
    text = (git_show(BASE, rel) or "").split("\n")
    n = line_of("D07", "### 4.6 Live window")
    text[n] = text[n] + " (edited)"
    HEAD_OVERRIDE.append((rel, "\n".join(text)))
    VERSION_AT_HEAD.append(True)  # PR-1 judgement in either mode
    undo_head, undo_judge = popper(HEAD_OVERRIDE), popper(VERSION_AT_HEAD)

    def undo() -> None:
        undo_head()
        undo_judge()

    return undo


def frozen_base_problems(t: Texts) -> list[str]:
    """Post-merge cites freeze at the recorded base: a moved main must not move them."""
    out: list[str] = []
    undo = lever_head_edit()
    VERSION_AT_HEAD.pop()  # a main that moved on since the pack merged, judged as the mode says
    try:
        for post, want in ((True, False), (False, True)):
            POST_MERGE_OVERRIDE.append(post)
            try:
                got = any(f[0] == "G-VERSION" for f in cite_findings(t)[0])
            finally:
                POST_MERGE_OVERRIDE.pop()
            if got != want:
                mode = "post-merge" if post else "PR-1"
                out.append(f"{mode}: a moved main {'FAILs' if got else 'passes'} G-VERSION")
    finally:
        VERSION_AT_HEAD.append(True)
        undo()
    if f"**v1 at base `{BASE}`.**" not in t.spec:
        out.append(f"the pack does not record the base {BASE} the tool reads at")
    if git_show("0" * 40, CITE_FILES["D07"]) is not None:
        out.append("an unresolvable base was read (G-CITE must find no text)")
    return out


def lever_png_missing() -> Callable[[], None]:
    IMG_OVERRIDE.append(frozenset(n for n in img_names() if "scr-102-idle.png" not in n))
    return popper(IMG_OVERRIDE)


def lever_strict_walk() -> Callable[[], None]:
    STRICT_WALK.append(True)
    return popper(STRICT_WALK)


def hash_mutation() -> Edit:
    return rx_sub(r"[0-9a-f]{12}(<!--=HASH:d07s5-->)", r"0a0b0c0d0e0f\1")


def word_mutation() -> Edit:
    word = banned_words()[1]
    return sub("No new page and no boards", f"No new page, nothing {word}, and no boards")


def drop_owner(s: dict[str, dict[str, object]]) -> None:
    s["d07.q01.removal"].pop("owner", None)


def first_deck_key(prefix: str) -> str:
    return next((k for k in build_deck()["strings"] if k.startswith(prefix)), "")


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-01", "G-ANCHOR", "a budget figure", spec=rx_sub(r"\d+(<!--=CITE:b102\.ms-->)", r"40\1")
    ),
    Mutation("M-02", "G-HASH", "a lifted block's hash", spec=hash_mutation()),
    Mutation(
        "M-03",
        "G-MARKER",
        "a draft comment left",
        spec=sub("## 1. Locked", "<!-- note -->\n\n## 1. Locked"),
    ),
    Mutation(
        "M-04", "G-CITE", "a cite past the file's end", spec=sub("`D05`:237–265", "`D05`:237–9265")
    ),
    Mutation("M-05", "G-VERSION", "a cited range edited at origin/main", lever=lever_head_edit),
    Mutation(
        "M-06",
        "G-QUOTE",
        "an invented quoted string",
        spec=sub("words carry the state", 'words carry the state ("Prices are paused for now")'),
    ),
    Mutation(
        "M-07",
        "G-COPY",
        "a byte of D12 §7 changed",
        spec=sub(
            "**polling therefore speaks at most once per 5 s scan**",
            "**polling therefore speaks at most once per 4 s scan**",
        ),
    ),
    Mutation(
        "M-08",
        "G-STATES",
        "an emitter cell rewritten",
        spec=cell_set("`SCR-147/S-04`", 3, "client-computed (the parent's rule)"),
    ),
    Mutation("M-09", "G-RBAC", "a Viewer cell enabled", spec=cell_set("T2-02", 4, "enabled")),
    Mutation(
        "M-10",
        "G-FROZEN",
        "a never-rendered line reworded",
        spec=sub("no raw exchange body", "a raw exchange body only in Details"),
    ),
    Mutation(
        "M-11",
        "G-REDLINE",
        "a token name added",
        spec=rx_sub(r"(\| SCR-104 +\| `D08`:333–387 +\| )13 ", r"\g<1>14 "),
    ),
    Mutation(
        "M-12",
        "G-DECK",
        "a deck string reworded",
        deck=deck_text(first_deck_key("d09.W-02"), "Exchange links"),
    ),
    Mutation(
        "M-13",
        "G-INDEX",
        "an id dropped from the index",
        spec=rx_sub(r"(\| SCR-104 +\| )KB-23\.\.KB-25", r"\g<1>KB-23..KB-24"),
    ),
    Mutation(
        "M-14",
        "G-CMP",
        "a component id that is not in `15`",
        spec=sub(
            "CMP-079 RbacGate, CMP-019 Icon `lock` (F-03, T2-17)",
            "CMP-079 RbacGate, CMP-999 Icon `lock` (F-03, T2-17)",
        ),
    ),
    Mutation("M-15", "G-CHECKLIST", "an open item dropped", spec=rx_sub(r"^\| 101-6 \|.*\n", "")),
    Mutation(
        "M-16", "G-BUDGET", "a budget anchor dropped", spec=rx_sub(r"\d+<!--=CITE:b147\.hz-->", "1")
    ),
    Mutation(
        "M-17",
        "G-STORY",
        "E08-S12 marked pending again",
        spec=sub("| E08-S12 #5207 (open)", "| E08-S12 #5207 (pending)"),
    ),
    Mutation(
        "M-18",
        "G-AHEAD",
        "a sprint cell changed",
        spec=rx_sub(r"(\| E08-D14 #277 +\| )Sprint 04", r"\g<1>Sprint 05"),
    ),
    Mutation(
        "M-19", "G-OPENROWS", "an id not in its parent", spec=sub("`D05:Q1`–`Q8`", "`D05:Q1`–`Q38`")
    ),
    Mutation("M-20", "G-UNTOUCHED", "a stray path", lever=lever_extra_path),
    Mutation("M-21", "G-UNTOUCHED", "a pointer line moved", lever=lever_pointer_moved),
    Mutation("M-22", "G-UNTOUCHED", "post-merge: `14` edited again", lever=lever_plan14_edit),
    Mutation(
        "M-23",
        "G-WALK",
        "a dry-run row back to pending under --strict-walk",
        spec=cell_set("E08-S10 #4704 (SCR-103)", 6, "filled at READY by the orchestrator's deputy"),
        lever=lever_strict_walk,
    ),
    Mutation("M-24", "G-PNG", "a named PNG missing", lever=lever_png_missing),
    Mutation(
        "M-25",
        "G-STATUS",
        "an unbuilt surface called built",
        spec=rx_sub(r"\| no; E08-S08 #4702 in progress", "| yes; E08-S08 #4702 in progress"),
    ),
    Mutation(
        "M-26",
        "G-RULED",
        "a draft marker left",
        spec=sub("## 0. Status and evidence", "## 0. Status and evidence <!-- BQ-02 -->"),
    ),
    Mutation(
        "M-27",
        "G-HEX",
        "a raw colour",
        spec=sub("token names only", "token names only (not #1A2B3C)"),
    ),
    Mutation(
        "M-28",
        "G-PENPOT",
        "a URL",
        spec=sub("never a host or URL", "never a host or URL like https://x.example.com"),
    ),
    Mutation(
        "M-29",
        "G-NAMES",
        "an agent name",
        spec=sub(
            "The orchestrator's deputy reads at READY",
            "The orchestrator's deputy, " + "work" + "er-2, reads at READY",
        ),
    ),
    Mutation(
        "M-30",
        "G-CLOSE",
        "a second closing keyword",
        spec=sub("## 2. The frame register", "Fixes #182.\n\n## 2. The frame register"),
    ),
    Mutation("M-31", "G-WORDS", "a banned word", spec=word_mutation()),
    Mutation(
        "M-32",
        "G-SESSION",
        "a session claimed",
        spec=sub("**Protocol**", "The session was held with the leads. **Protocol**"),
    ),
    Mutation(
        "M-34",
        "G-STATES",
        "lens F1: a bare-token wire cell (a word on an unrelated line)",
        spec=cell_set("`SCR-102/loading`", 3, "wire: `code` (`22`:11962)"),
    ),
    Mutation(
        "M-35",
        "G-STATES",
        "lens F2: a wire cell citing a scope sentence, not a definition",
        spec=cell_set("`SCR-102/checking-a-symbol`", 3, "wire: `USDT` (`23`:4)"),
    ),
    Mutation(
        "M-36",
        "G-DECK",
        "lens F3: a PROPOSED entry with no owner",
        deck=deck_edit(drop_owner),
    ),
    Mutation(
        "M-37",
        "G-COPY",
        "lens F8: a re-found `14` cite moved",
        spec=rx_sub(r"(\| §6\.3 +\| 2329 \(D12's base\) +\| `14`:)2334", r"\g<1>2335"),
    ),
    Mutation(
        "M-38",
        "G-RBAC",
        "lens F4: a hidden (T3) cell read as T2",
        spec=rx_sub(
            r"(\| T2-08 .*?\| enabled +\| )hidden \(T3\); the sentence replaces the link",
            r"\g<1>T2",
        ),
    ),
    Mutation(
        "M-39",
        "G-STATES",
        "read U2: a first-match threshold instead of the whole condition",
        spec=cell_set("`SCR-102/load-failed`", 3, "client-computed: 503s"),
    ),
    Mutation(
        "M-33",
        "G-RULED-PIN",
        "a ruled sentence edited without a re-pin",
        spec=sub("do not fit a design pack", "do not suit a design pack"),
    ),
)


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(x.encode("utf-8")).hexdigest() for x in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def plan_paths() -> tuple[tuple[str, Path], ...]:
    return tuple((cid, ROOT / CITE_FILES[cid]) for cid in (*UNTOUCHED, "14", *UNTOUCHED_DOCS))


def read_plans() -> tuple[tuple[str, str], ...]:
    return tuple(
        (cid, p.read_text(encoding="utf-8") if p.exists() else "") for cid, p in plan_paths()
    )


def selftest(spec: str, deck: str, paths: tuple[Path, ...]) -> tuple[bool, list[str]]:
    on_disk = digest(paths)
    plans = read_plans()
    values = compute(spec, deck)
    spec_f, _ = fill(spec, values)
    values = compute(spec_f, deck)
    vt = tuple(sorted(values.items()))
    base_fails, _w, _n = audit(Texts(spec_f, deck, plans, vt))
    lines = [f"baseline (filled in memory): {len(base_fails)} FAIL"]
    lines += [f"  baseline FAIL {x}" for x in base_fails]
    ok = not base_fails
    pristine = digest_texts(spec_f, deck)
    for mu in MUTATIONS:
        s = mu.spec(spec_f) if mu.spec else spec_f
        d = mu.deck(deck) if mu.deck else deck
        if (s, d) == (spec_f, deck) and mu.lever is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        undo = mu.lever() if mu.lever else None
        repin = mu.gate != "G-RULED-PIN"
        if repin:
            PIN_UNITS_OVERRIDE.append(tuple(ruled_units(s, d, values)))
        try:
            fails, _w2, _n2 = audit(Texts(s, d, plans, vt))
        finally:
            if undo:
                undo()
            if repin:
                PIN_UNITS_OVERRIDE.pop()
        new = [x for x in fails if x not in base_fails]
        named = [x for x in new if x.startswith(f"[{mu.gate}]")]
        hit = bool(named) and len(new) == 1
        levers = EXTRA_PATHS or PLAN_OVERRIDE or PIN_UNITS_OVERRIDE or HEAD_OVERRIDE
        restored = (
            digest_texts(spec_f, deck) == pristine
            and digest(paths) == on_disk
            and not (levers or IMG_OVERRIDE or STRICT_WALK or POST_MERGE_OVERRIDE)
        )
        ok = ok and hit and restored
        first = (named or new or ["nothing new"])[0]
        state = ("ok" if hit else "MISSED") + ("" if restored else ", NOT RESTORED")
        lines.append(f"  {mu.mid} [{mu.gate}] {state} ({len(new)} new) - {first}")
        if not hit:
            lines += [f"      new: {x}" for x in new]
    frozen = frozen_base_problems(Texts(spec_f, deck, plans, vt))
    ok = ok and not frozen
    lines += [f"  frozen base FAIL: {x}" for x in frozen]
    lines.append(f"  frozen base: {'ok' if not frozen else 'MISSED'} (a moved main, both modes)")
    gates = {mu.gate for mu in MUTATIONS}
    missing = [g for g in GATE_NAMES if g not in gates]
    if missing:
        ok = False
        lines.append(f"  gates with no mutation: {', '.join(missing)}")
    return ok, [report(x) for x in lines]


# ---------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    global HEAD
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="E08-D13 hand-off pack audit (module docstring)")
    ap.add_argument("--check", nargs="?", const=SPEC_REL, default=None, metavar="SPEC")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="fill placeholders and blocks, then check")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="apply every mutation")
    ap.add_argument("--repin-ruled", action="store_true", help=f"rewrite {PIN_REL}")
    ap.add_argument("--strict-walk", action="store_true", help="a pending dry-run row FAILs")
    ap.add_argument(
        "--head", default=HEAD, help="the ref G-VERSION compares against (default origin/main)"
    )
    args = ap.parse_args(argv)
    HEAD = args.head
    if args.strict_walk:
        STRICT_WALK.append(True)
    spec_path = ROOT / (args.check or SPEC_REL)
    deck_path = ROOT / DECK_REL
    spec = spec_path.read_bytes().decode("utf-8")
    if args.fill:
        deck_path.write_text(deck_document(), encoding="utf-8", newline="\n")
    deck = deck_path.read_bytes().decode("utf-8") if deck_path.exists() else "{}"
    if args.repin_ruled:
        left = [
            m
            for ln in spec.split("\n")
            for m in PLACEHOLDER.finditer(ln)
            if not in_code(ln, m.start())
        ]
        if left or any(GEN_MARK.match(ln) for ln in spec.split("\n")):
            print("FAIL --repin-ruled: unfilled placeholders or blocks; run --fill first")
            return 1
        units = ruled_units(spec, deck, compute(spec, deck))
        (ROOT / PIN_REL).write_text(write_pins(units), encoding="utf-8", newline="\n")
        print(f"--repin-ruled: {len(units)} units pinned in {PIN_REL}")
        return 0
    if args.self_test:
        paths = (spec_path, deck_path, ROOT / PIN_REL, *(p for _n, p in plan_paths()))
        ok, lines = selftest(spec, deck, paths)
        print("\n".join(lines))
        print(report(f"--self-test: {'ok' if ok else 'FAIL'} - {len(MUTATIONS)} mutations"))
        return 0 if ok else 1
    values = compute(spec, deck)
    if args.fill:
        spec, unknown = fill(spec, values)
        spec_path.write_text(spec, encoding="utf-8", newline="\n")
        for u in unknown:
            print(f"FAIL --fill: no value for {{{{{u}}}}}")
        values = compute(spec, deck)
    if args.json and not (args.check or args.fill):
        print(json.dumps({"values": values}, ensure_ascii=False, indent=1))
        return 0
    t = Texts(spec, deck, read_plans(), tuple(sorted(values.items())))
    fails, warns, n = audit(t)
    if args.json:
        out = {"values": values, "fails": fails, "warns": warns, "cites": n}
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        shown = spec_path.relative_to(ROOT) if spec_path.is_relative_to(ROOT) else spec_path
        print(f"## E08-D13 audit of {shown} (+ the deck) at base {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {len(GATE_NAMES)}")
        print("\n".join(report(w) for w in warns))
        print("\n".join(report(f"FAIL {x}") for x in fails) or "OK - every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
