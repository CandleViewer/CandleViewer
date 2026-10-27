#!/usr/bin/env python3
"""E12-D04 (#240) audit: SCR-041's bar-mode half and the hotkey ladder (spec + hand-off).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base `d6597cbcf7` (`git show`): the token JSON (`themes.json` layering:
dark = primitives + semantic-dark, light = + semantic-light, hc = + semantic-hc), the plan texts
`05`, `11`, `13`, `14`, `15`, `16`, `22`, `23`, the merged design docs the spec cites, the shipped
keymap files (`keymap.json`, `reserved-keys.json`, as JSON, never imported); then this ticket's
spec and hand-off from the working tree, and the working-tree `05`, `14`, `15`, `16`, `22` and the
two keymap files (which must equal the fork point; no other path may differ from it but this
ticket's).

1. **Values (RULED 6430117981, BQ-1).** Every `{{KIND:key}}` outside a code span is COMPUTED:
   BUDGET (the open, keystroke, switch, first-paint, strip, count and probe budgets, the widths,
   rows, targets and the checked outline, parsed from the cited lines), RULE (the probe bound the
   ruling states), COUNT (the `KM` commands and `RK` keys, the query cap, the ranked, recent and
   windowing counts, boards, twins, frames, pairs, the line budgets), HEX (every bound token in
   dark / light / hc) and CONTRAST (WCAG 2.x, truncated to two decimals). `--fill` writes
   `VALUE<!--=KIND:key-->`; `--check` re-derives every anchored value and FAILs on a difference,
   a `{{` left outside a code span, a hand-typed figure with a unit or a hand-typed hex, and a
   digit typed against an anchored value's left edge.
2. **The comment strip.** One pattern over the whole text, `re.DOTALL`: `<!--` closes at `-->` or
   `--!>`, `<!-->` and `<!--->` close at once, and an unclosed comment runs to the end. Every
   comment must be a value anchor the tool computes (G-MARKER); the lexicon gates read rendered
   text only.
3. **Cites.** Every `NN`:line, `D0n`/`D0nh`:line, `Exx-Dyy`:line and `KM`/`RK`/`DSP`/`KMT`/`VAL`/
   `PRF`/`AUD`/`SEED`/`INS`:line cite is read at the base (FAIL when the line is gone or blank;
   WARN when it drifted at `origin/main`), and the load-bearing fragments in CITED must sit on the
   cited line.
4. **Gates.** Lexicon gates first (each reads rows cell by cell and prose after the comment strip,
   NFKC, markup dropped, dashes to spaces and lower case; a claim is read per clause; a negation
   covers its own term within five words and a list coordinated after it; quoted copy, §18.2's
   mutation rows and the hand-off's Old cells are not claims; each ruled behaviour is read with its
   synonyms), then the measured gates (the strip parity against D02 and D03, the key-conflict
   matrix over `KM` and `RK`, the reused-copy diff against E08-D05, the carry table, the frame
   register column by column, the contrast pairs, the boards, the budgets, G-UNTOUCHED against
   `git merge-base HEAD origin/main`; besides this ticket's four files it admits only the ten
   board PNGs and the committed board script set `sheets/e12-d04/`), then the pins. Each gate
   reports one FAIL line. The boards gate reads each §0 Status cell against its PNG's header and
   the board script's sha256 against the file.
5. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over EVERY unit of both docs,
   in RULED_PIN_TXT (`e12_d04_ruled_pins.txt`): each heading, table row (by its lead cell), rule
   line, prose sentence (`s<k>`) and fenced block, by doc, region (heading path plus occurrence
   `#n`), location and exact text (NFKC, whitespace collapsed). Anchored values are pinned with
   their values cut out (G-ANCHOR re-derives them). Each region pins its line shape (line-shape
   tags: `.` blank, `h` heading, `t` row, `r` rule, `b` bullet, `n` numbered item, `p` prose, `f`
   fence; a prose, bullet or numbered tag carries its sentence count, the line-form tag; `>n` an
   n-column indent). A unit changed, moved, duplicated, deleted or added FAILs by location.
   `--repin-ruled` is the only writer (it refuses while a placeholder is unfilled); `--check`
   writes nothing. Pins fold NFKC but never `…` (so "More…" and "More..." pin apart), and
   G-CHARSET FAILs any compatibility character but `…`, a spelled-out "...", any control character
   but a tab, a line or paragraph separator, any space but U+0020, any CR and any trailing
   whitespace: a change the pins cannot see is not allowed in. NOTE demotion:
   when a lexicon or measured gate already FAILs a section, that section's pin findings print as
   NOTE lines, so one wrong form yields one FAIL.
6. **--self-test** (alias `--selftest`) applies every §18.2 mutation in memory, plus the tool's own
   X-n and P-n (one per pin class) and the N-n probes (which must trip nothing), with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names, and every
   text is restored byte-identically (sha256 in memory and on disk). Its output is ASCII only.

Usage (from the repo root):
  python3 -I docs/design/_tools/e12_d04_switcher_audit.py --check [SPEC] [--handoff F] [--json]
  python3 -I docs/design/_tools/e12_d04_switcher_audit.py --check --fill
  python3 -I docs/design/_tools/e12_d04_switcher_audit.py --self-test
  python3 -I docs/design/_tools/e12_d04_switcher_audit.py --repin-ruled
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
import struct
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "d6597cbcf7"  # every cite was read here (the spec's Inputs line; #4682 read a1479b371d)
HEAD = "origin/main"  # drift is reported against this ref (WARN, never FAIL)
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E12/E12-D04.md"
HAND_REL = "docs/design/E12/E12-D04-handoff.md"
RULED_PIN_TXT = "docs/design/_tools/e12_d04_ruled_pins.txt"
DS_SRC_REL = "packages/ui/tokens"
UNTOUCHED = ("05", "14", "15", "16", "22")  # RULED BQ-4: never edited by this ticket
UNTOUCHED_DOCS = ("KM", "RK")  # RULED BQ-4: the keymap files stay untouched (G-rows instead)
# the only paths this ticket may add or change against the fork point
OWN_PATHS = (
    "docs/design/E12/E12-D04.md",
    "docs/design/E12/E12-D04-handoff.md",
    "docs/design/_tools/e12_d04_switcher_audit.py",
    "docs/design/_tools/e12_d04_ruled_pins.txt",
)
# the boards PR's committed board script set (`sheets/e12-d04/`: the `.js.txt` scripts, HANDOFF.md
# and expect.txt), never read by this tool but the board script's sha256 (G-BOARDS)
OWN_SHEETS = re.compile(r"docs/design/_tools/sheets/(?:e12-d04/[A-Za-z0-9._-]+|MANIFEST\.sha256)")
CITE_FILES: dict[str, str] = {
    "D01": "docs/design/E12/E12-D01.md",
    "D02": "docs/design/E12/E12-D02.md",
    "D03": "docs/design/E12/E12-D03.md",
    "D05": "docs/design/E12/E12-D05.md",
    "D06": "docs/design/E12/E12-D06.md",
    "D03h": "docs/design/E12/E12-D03-handoff.md",
    "D05h": "docs/design/E12/E12-D05-handoff.md",
    "D06h": "docs/design/E12/E12-D06-handoff.md",
    "KM": "apps/web/src/keymap/keymap.json",
    "RK": "apps/web/src/keymap/reserved-keys.json",
    "DSP": "apps/web/src/keymap/dispatcher.ts",
    "KMT": "apps/web/src/keymap/keymap.ts",
    "VAL": "apps/web/src/keymap/validate.ts",
    "PRF": "apps/web/src/keymap/profile.ts",
    "AUD": "apps/web/src/keymap/audit.ts",
    "SEED": "services/api/candleviewer/auth/rbac_seed.json",
    "INS": "services/api/candleviewer/api/instruments.py",
}
CODE_IDS = frozenset({"KM", "RK", "DSP", "KMT", "VAL", "PRF", "AUD", "SEED", "INS"})
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SEMANTIC = ("semantic-dark", "semantic-light", "semantic-hc")

# ---- the ruling and the fixed facts
RULING_ID = "6430117981"
BQ_LIST_ID = "6430006948"
RULED_IDS = (RULING_ID, BQ_LIST_ID)  # the allow-list: every comment id the docs cite
OWNER_PENDING = "owner approval pending (#2701)"  # RULED: BQ-9 and BQ-12 are the owner's
PROBE_S = "1"  # RULED BQ-9 (the ruling's addition): the coverage probe is bounded at 1 s
MAX_BOARDS = 10  # RULED BQ-23 (lever 4): at most ten boards
TWIN_SHARE = Fraction(1, 3)  # twins at most a third of the boards (lever 4)
TWINS = {"comfortable twin of 01", "light twin of 02", "high-contrast twin of 01"}  # BQ-23
SPEC_LINE_BUDGET = 600  # standing condition: "about 600 lines"
HAND_LINE_BUDGET = 150  # standing condition: "about 150 lines"
STORIES = ("E12-S11 (#451)", "E12-S12 (#535)", "E11-S13 (#520)", "E10-S02 (#305)")
E08_BOARDS = ("B15", "B16", "B17", "B18", "B19", "B20", "B21", "B22", "B23", "B26")
# the bound tokens of §16 (slot rows) and the measured pairs: key -> (fg, bg, bar kind)
BOUND = (
    "surface.overlay",
    "surface.app",
    "surface.selected",
    "surface.raised",
    "action.selected",
    "border.selected",
    "text.primary",
    "text.secondary",
    "text.tertiary",
    "focus.ring",
)
PAIRS: dict[str, tuple[str, str, str]] = {
    "primary-overlay": ("text.primary", "surface.overlay", "text"),
    "secondary-overlay": ("text.secondary", "surface.overlay", "text"),
    "tertiary-overlay": ("text.tertiary", "surface.overlay", "text"),
    "primary-selected": ("text.primary", "surface.selected", "text"),
    "secondary-selected": ("text.secondary", "surface.selected", "text"),
    "bar-selected": ("border.selected", "surface.selected", "mark"),
    "primary-checked": ("text.primary", "action.selected", "text"),
    "outline-checked": ("border.selected", "action.selected", "mark"),
    "secondary-raised": ("text.secondary", "surface.raised", "text"),
    "primary-raised": ("text.primary", "surface.raised", "text"),
    "primary-app": ("text.primary", "surface.app", "text"),
    "ring-overlay": ("focus.ring", "surface.overlay", "mark"),
    "ring-selected": ("focus.ring", "surface.selected", "mark"),
    "ring-checked": ("focus.ring", "action.selected", "mark"),
    "ring-raised": ("focus.ring", "surface.raised", "mark"),
}
# names a doc may cite that are not shipped tokens: proposals and routed names, each with its row
NOT_SHIPPED = {"color.text.accent": "A-D05-3, routed to E12-D09 (#244)"}
# §10.2's tab order (E08-D05:293; Record is T2 and focusable for others, E09-D09:228)
TAB_ORDER = (
    "input",
    "strip",
    "More…",
    "Record (when shown, T2 for others)",  # PR 2 ruling: only beside the not-recorded line
    "out, closing without commit",
)
# the frames that draw a status-strip notice: D02's NC-1, never a CMP-028 callout (D02:406)
STRIP_FRAMES = (
    "`fallback/strip-notice · dark`",
    "`switch/loading · dark`",
    "`switch/failed · dark`",
)
# §1.3: a locked input's first cite must sit on the line that holds its fragment (G-LOCKED)
LOCKED_FRAG = {"D01": "§3 (vocabulary)", "D05": "never chart type or bar mode"}
LOCKED_LEADS = ("E08-D05", "D02", "D03", "D05", "D06", "D01")
# compatibility characters the docs may hold (NFKC would fold them); any other one FAILs (G-CHARSET)
CHARSET_ALLOW = frozenset("…")
# a time interval's `PaneIntervalCode` and its spoken name, for the ladder's labels (D03:67)
TIME_CODES = {"m": 1, "h": 60}
UNIT_WORD = {"m": "minute", "h": "hour", "D": "day"}
# load-bearing fragments: (cite id, line at the base, text the line must hold)
CITED: tuple[tuple[str, int, str], ...] = (
    ("14", 1006, "bar modes are E12-D04's"),
    ("14", 1007, "no request per keystroke"),
    ("14", 1012, "swaps subscriptions with a single WS frame"),
    ("14", 1013, "source: 'quick-switcher'"),
    ("14", 1023, "<=600 ms for the visible window"),
    ("14", 367, "_current_ bindings"),
    ("13", 748, "Old bars topic unsubscribed at the swap"),
    ("13", 900, "symbol never recorded"),
    ("11", 730, "≤50 ms"),
    ("11", 961, "one keystroke apart"),
    ("11", 975, "switch ≤200 ms from cache"),
    ("05", 47, "Open Watchlist / symbol search"),
    ("05", 55, "Cycle timeframe"),
    ("05", 83, "global/navigation bindings cannot be overridden"),
    ("05", 85, "permanently reserved"),
    ("05", 96, "Focus is never silently stolen"),
    ("05", 125, "≥4.5:1"),
    ("05", 126, "≥3:1"),
    ("15", 211, "in a non-modal popover Tab past its last control closes it"),
    ("15", 259, "`font.mono`"),
    ("15", 520, "500 ms after the last keystroke"),
    ("15", 2586, "combobox pattern"),
    ("15", 2595, "`favourites: Interval[]`"),
    ("16", 113, "Compact"),
    ("16", 114, "32px"),
    ("16", 210, "1280×800px"),
    ("22", 3787, "maxLength: 32"),
    ("22", 4834, "/market/data-coverage:"),
    ("22", 12122, "settings:write"),
    ("22", 18213, "funding_interval_minutes"),
    ("22", 18248, "recording_started_at"),
    ("22", 18270, "turnover_24h"),  # the ticker field §8.2 cites beside D-8 (BQ-13)
    ("22", 21136, "default_bar_type"),
    ("23", 593, "`topics`, `snapshot` and `replay_session_id`"),
    ("23", 685, "a key other than `topics`"),
    ("D02", 25, "after 600 ms the strip says both"),
    ("D02", 75, "`color.surface.raised`"),
    ("D02", 35, "to the chart region when it was opened by hotkey"),
    ("D02", 39, "a symbol change disarms"),
    ("D02", 182, "`1` 1m, `2` 3m"),
    ("D02", 183, "`3` 5m"),
    ("D02", 282, "One polite live region per chart panel"),
    ("D02", 378, "`source, cache`"),
    ("D02", 343, "Every role changes symbols, intervals, modes and chart types"),
    ("D02", 431, "typed interval"),
    ("D02", 481, "E12-D04 (#240) with a contract PR"),
    ("D02", 494, "the skeleton is bootstrap-only"),
    ("D03", 48, "only an explicit act may start one"),
    ("D03", 50, "`Enter`, `Space` or `→` changes nothing and announces the reason once"),
    ("D03", 54, "slot N is digit N"),
    ("D03", 56, "the last value used for that symbol and mode"),
    ("D03", 62, "CMP-220 and SCR-041 (E12-D04) use it too"),
    ("D03", 129, "400 wide"),
    ("D03", 132, "`color.border.selected` inside"),
    ("D03", 280, "E12-D04 renders it unchanged"),
    ("D03", 285, "the default ladder is read-only"),
    ("D03", 306, "in one commit (NC-10"),
    ("D03", 446, "No audit record"),
    ("D05", 220, "never chart type or bar mode"),
    ("D05", 237, "**Tick, Range and Renko** apply the same number everywhere"),
    ("D06", 565, "Switch to time bars"),
    ("E08-D05", 53, "E12-D04 amends the same frames for bar modes"),
    ("E08-D05", 71, '"—", name "not available"'),
    ("E08-D05", 89, "| T1   |"),
    ("E08-D05", 121, "560 px wide, clamped to the window"),
    ("E08-D05", 264, "min(560, window − 32 px)"),
    ("E08-D05", 293, "no trap"),
    ("E08-D05", 295, "check the nth favourite"),
    ("E08-D05", 317, '`radiogroup` "Interval"'),
    ("E08-D05", 555, "D05 base, E12-D04 amends"),
    ("E08-D05", 559, "a per-user list in preferences"),
    ("E08-D05", 325, 'CMP-026 `error` `role="alert"`'),
    ("E08-D05", 571, "**A-D05-7**"),
    ("E09-D09", 228, "Tab order kept"),
    ("E09-D09", 236, "The reason node is rendered at mount"),
    ("D01", 39, "§3 (vocabulary)"),
    ("E09-D09", 115, '`settings:write` → "change settings"'),
    ("E11-D07", 343, "`rules.move_up/down`"),
    ("E15-D06", 218, "**storage pending**"),
    ("E16-D05", 107, "Only the owner can change recording."),
    ("KM", 197, '"defaultBinding": "1..9"'),
    ("KM", 198, '"destructive": false'),
    ("KM", 203, '"command": "ticket.qty_preset"'),
    ("KM", 84, '"defaultBinding": "Alt+1..9"'),
    ("RK", 18, '"Ctrl+1..9"'),
    ("DSP", 38, "bound(c) === got"),
    ("KMT", 84, r"(\d)\.\.(\d)$"),
    ("PRF", 3, "Rebinds take effect without reload"),
    ("AUD", 35, "destructive"),
    ("INS", 302, '"recording_started_at": iso_us(started)'),  # #4691 (D04-G2)
    ("SEED", 239, '"viewer": ['),
)
# copy the spec quotes verbatim from a merged line: (cite id, line, text, the section quoting it)
VERBATIM: tuple[tuple[str, int, str, str], ...] = (
    ("E08-D05", 312, "Change symbol and interval, Chart 1", "15. Copy deck"),
    ("D03", 332, "Keys 1 to 9 on the chart", "3.1 The parity"),
    ("E08-D05", 224, "Not recorded — a chart kept open for 60 s starts recording it.", "15. Copy"),
    ("E08-D05", 176, "No USDT perpetual matches 'xyzzy'.", "13.1 States"),
    ("E08-D05", 176, "v1 supports Bybit USDT linear perpetuals only.", "13.1 States"),
    ("E08-D05", 187, "Chart 1 now shows ETHUSDT, 1 minute.", "15. Copy deck"),
    ("E08-D05", 260, "BTCUSDT is not trading on Bybit — choose another symbol.", "15. Copy"),
    ("E08-D05", 168, "2 results", "15. Copy deck"),
    ("E08-D05", 169, "Loading the instrument list…", "15. Copy deck"),
    ("E08-D05", 170, "Couldn't load the instrument list.", "15. Copy deck"),
    ("E08-D05", 177, "LUNAUSDT is not trading on Bybit.", "15. Copy deck"),
    ("E09-D09", 73, "Only the owner can start recording.", "15. Copy deck"),
    ("E09-D09", 95, "Read-only while viewing as {user}.", "15. Copy deck"),
    ("D03", 214, "Checking recorded prints…", "6.2 The probe"),
    ("D03", 227, "No favourite on {3}", "4. Commit"),
)
# the deck rows the copy-deck gate (G-REUSE) diffs: S-n -> (cite id, line)
REUSED: dict[str, tuple[str, int]] = {
    "S-1": ("E08-D05", 312),
    "S-2": ("D03", 332),
    "S-10": ("E08-D05", 224),
    "S-11": ("E08-D05", 176),
    "S-12": ("E08-D05", 199),
    "S-13": ("E09-D09", 73),
    "S-14": ("E09-D09", 95),
    "S-15": ("E08-D05", 187),
    "S-18": ("E08-D05", 242),
    "S-19": ("E08-D05", 260),
    "S-20": ("E08-D05", 168),
    "S-21": ("E08-D05", 169),
    "S-22": ("E08-D05", 170),
    "S-23": ("E08-D05", 177),
}

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z0-9]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
FIGURE = re.compile(
    r"(?<![\w.,:#/>{-])(\d+(?:[.,]\d+)*)\s?(ms|s|hz|px|%|:1)(?![\w])", re.IGNORECASE
)
CITE_GROUP = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:D0[1-6]h?|E\d\d-D\d\d)\b)) ?"
    r":(?P<first>\d+(?:[–-]\d+)?)(?P<more>(?:(?:\s*\([^()\n]*\))?,\s*:\d+(?:[–-]\d+)?)*)"
)
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]", re.IGNORECASE)
COMMENT_ID = re.compile(r"(?<![\w-])(\d{8,})(?![\w-])")

Values = dict[str, str]
Fetch = Callable[[str, str], str | None]
# a gate finding: (gate tag, message, doc, section); doc / section None for a repo-level finding
Finding = tuple[str, str, str | None, str | None]

# tool-state levers the self-test moves (each mutation restores them)
MARK_MIN_OVERRIDE: list[Decimal] = []


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
    return git_show(rev, rel)


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


SEC_NUM = re.compile(r"(§[A-Z]|\d+(?:\.\d+)*\.?)(?=\s|$)")


def find_heading(lines: list[str], fence: list[bool], head: str) -> int:
    """The index of the heading that starts with `head` (outside fences). A reworded or a
    renumbered heading is still found (#4682 lens carry 4): failing the exact prefix, the one
    heading with the same section number, else the one heading with the same words after its
    number. So a gate keeps reading its section and only the pins report the new heading."""
    heads = [(i, m[2]) for i, ln in enumerate(lines) if (m := HEADING.match(ln)) and not fence[i]]
    hit = next((i for i, h in heads if h.startswith(head)), -1)
    num = SEC_NUM.match(head)
    if hit >= 0 or num is None:
        return hit
    same = [i for i, h in heads if (n := SEC_NUM.match(h)) and n[1] == num[1]]
    rest = head[num.end() :].strip()
    if len(same) != 1 and rest:
        same = [
            i for i, h in heads if (n := SEC_NUM.match(h)) and h[n.end() :].strip().startswith(rest)
        ]
    return same[0] if len(same) == 1 else -1


def section(text: str, head: str) -> str:
    """From the heading starting with `head` (outside fences; `find_heading`) to the next heading
    of the same or a higher level outside a fence."""
    lines = text.split("\n")
    fence = fenced(lines)
    start = find_heading(lines, fence, head)
    if start < 0:
        return ""
    m = HEADING.match(lines[start])
    level = len(m[1]) if m else 0
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
    """The exact text, NFKC with whitespace collapsed (Prettier's table padding is not a change).
    A CHARSET_ALLOW character is never folded, so "More…" and "More..." pin apart (#240 lens)."""
    parts = re.split("([" + "".join(sorted(CHARSET_ALLOW)) + "])", text)
    kept = "".join(p if p in CHARSET_ALLOW else unicodedata.normalize("NFKC", p) for p in parts)
    return " ".join(kept.split())


def sec_id(heading: str) -> str:
    """A `##` section's key: the first three words of its rendered heading (values and anchors
    dropped), the same for the lexicon units, the gates and the pin regions."""
    text = PLACEHOLDER.sub(" ", strip_comments(heading)).lstrip("# ")
    return " ".join(pin_norm(text).split()[:3]) or "(top)"


def h2_of(text: str, head: str) -> str:
    """The `##` section key of the heading that starts with `head`."""
    lines = text.split("\n")
    fence = fenced(lines)
    at = find_heading(lines, fence, head)
    return h2_at(text, at + 1) if at >= 0 else "(top)"


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


MUTATION_HEAD = "18.2 The mutation list"  # its rows describe the violations they plant


def lex_units(doc: str, text: str) -> list[LexUnit]:
    """Every unit a lexicon gate reads, rendered: each table row (cells joined by " | "), each
    bullet or numbered item, each paragraph and each heading, with its `##` section. Skipped: the
    spec's §18.2 rows (they name the violations they plant) and Table A's Old cells in the
    hand-off (verbatim text at the base, not this ticket's claims)."""
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
            skip = doc == "spec" and m[2].startswith(MUTATION_HEAD)
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


# ---------------------------------------------------------------------------- the keymap files


@functools.lru_cache(maxsize=1)
def km_commands() -> tuple[tuple[str, str, str], ...]:
    """`KM`'s commands at the base: (id, context, default binding)."""
    data = json.loads(at_base(CITE_FILES["KM"]))
    return tuple(
        (str(c["id"]), str(c["context"]), str(c["defaultBinding"])) for c in data["commands"]
    )


@functools.lru_cache(maxsize=1)
def rk_keys() -> frozenset[str]:
    return frozenset(json.loads(at_base(CITE_FILES["RK"])))


def expand(binding: str) -> frozenset[str]:
    """A binding with a digit range (`1..9`, `Alt+1..9`) as its single keys; else itself."""
    m = re.fullmatch(r"(.*?)(\d)\.\.(\d)", binding)
    if not m:
        return frozenset({binding})
    return frozenset(f"{m[1]}{d}" for d in range(int(m[2]), int(m[3]) + 1))


def sharing(binding: str) -> list[tuple[str, str, str]]:
    """Every `KM` command whose binding shares a key with `binding`."""
    keys = expand(binding)
    return [c for c in km_commands() if expand(c[2]) & keys]


def reserved(binding: str) -> bool:
    keys = expand(binding)
    return any(expand(k) & keys for k in rk_keys())


# ---------------------------------------------------------------------------- the ladder


def ladder() -> list[str]:
    """D02:182-183's default ladder, slot order: the labels `1m` … `1D`."""
    text = base_line("D02", 182) + " " + base_line("D02", 183)
    got = re.findall(r"`(\d)` (\d+[mhD])", text)
    if [int(n) for n, _ in got] != list(range(1, 10)):
        raise SystemExit("FAIL parse: D02:182-183 is not the nine-slot ladder")
    return [lab for _n, lab in got]


def ladder_lines() -> dict[str, int]:
    """The D02 line each default slot sits on (D02:182 holds `1` and `2`, D02:183 the rest)."""
    out: dict[str, int] = {}
    for n in (182, 183):
        for d, _lab in re.findall(r"`(\d)` (\d+[mhD])", base_line("D02", n)):
            out[d] = n
    return out


def code_of(label: str) -> str:
    """A time label's `PaneIntervalCode` (`1m` → `1`, `1h` → `60`, `1D` → `D`)."""
    n, u = int(label[:-1]), label[-1]
    if u == "D":
        return "D" if n == 1 else f"{n}D"
    return str(n * TIME_CODES[u])


def name_of(label: str) -> str:
    n, u = int(label[:-1]), label[-1]
    return f"{n} {UNIT_WORD[u]}" + ("" if n == 1 else "s")


def served_codes() -> list[str]:
    """D03:67's served time codes (the Bounds cell of the Time row)."""
    cell = split_row(base_line("D03", 67))[5]
    return re.findall(r"\b(\d+|D)\b(?=,|\s\()", cell)


def hero() -> tuple[str, str]:
    """D03's non-time hero slot: the chip `[9 Vol 50]` (D03:96) and its name (D03:333)."""
    chip = grab(r"(\[9 Vol \d+\])", base_line("D03", 96), "D03:96 hero chip")
    name = grab(r'"(Volume, \d+ BTC per bar)"', base_line("D03", 333), "D03:333 chip name")
    return chip, name


# ---------------------------------------------------------------------------- budgets and counts


def budget_values() -> Values:
    w, h = re.findall(r"(\d+)×(\d+)px", base_line("16", 210))[0]
    compact, comfortable = re.findall(r"\| (\d+) / (\d+)\s*\|\s*$", base_line("E08-D05", 123))[0]
    return {
        "BUDGET:viewport.w": w,
        "BUDGET:viewport.h": h,
        "BUDGET:open": grab(r"<=(\d+) ms", base_line("14", 1012), "14:1012"),
        "BUDGET:keystroke": grab(r"≤(\d+) ms", base_line("11", 730), "11:730"),
        "BUDGET:switch.cache": grab(r"≤(\d+) ms", base_line("11", 975), "11:975"),
        "BUDGET:first-paint": grab(r"<=(\d+) ms", base_line("14", 1023), "14:1023"),
        "BUDGET:strip.after": grab(r"after (\d+) ms the strip", base_line("D02", 25), "D02:25"),
        "BUDGET:count.rest": grab(
            r"after a (\d+) ms rest", base_line("E08-D05", 130), "E08-D05:130"
        ),
        "BUDGET:count.cmp048": grab(r"(\d+) ms after the last", base_line("15", 520), "15:519"),
        "BUDGET:width": grab(r"\| (\d+) px wide, clamped", base_line("E08-D05", 121), "E08:121"),
        "BUDGET:width.margin": grab(r"window − (\d+) px", base_line("E08-D05", 264), "E08:264"),
        "BUDGET:width.scr042": grab(r"\| (\d+) wide \(", base_line("D03", 129), "D03:129"),
        "BUDGET:rows.compact": compact,
        "BUDGET:rows.comfortable": comfortable,
        "BUDGET:target.min": grab(r"≥(\d+)×\d+ CSS px", base_line("05", 100), "05:100"),
        "BUDGET:row.comfortable": grab(r"\|\s*(\d+)px", base_line("16", 114), "16:114"),
        "BUDGET:outline": grab(r"\+ (\d+) px \(`border\.thick`\)", base_line("D03", 132), "D03"),
        "RULE:probe.s": PROBE_S,
    }


def board_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "0. Status")) if re.fullmatch(r"\d{2}", r[0])]


def is_twin(row: list[str]) -> bool:
    return "twin of" in row[2]


BOARD_SCRIPT = "docs/design/_tools/sheets/e12-d04/e12-d04-board.js.txt"  # the r2 script §0 names
DRAWN_CELL = re.compile(
    r"drawn \(r2\): board id `[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}`, "
    r"`(?P<png>[^`]+)` \((?P<w>\d+) × (?P<h>\d+)\)"
)
FRAME_HEAD = "18.1 The frame register"
FR_COLS = ("Frame", "Board", "Theme", "State", "Components", "Copy", "Tokens", "Status")


def frames(spec: str) -> list[dict[str, str]]:
    rows = [r for r in table_rows(section(spec, FRAME_HEAD)) if r and r[0].startswith("`")]
    return [dict(zip(FR_COLS, r, strict=False)) for r in rows]


def pair_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "16. Tokens")) if " on " in r[0]]


def count_values(spec: str) -> Values:
    bd = board_rows(spec)
    twins = [r for r in bd if is_twin(r)]
    return {
        "COUNT:boards": str(len(bd)),
        "COUNT:boards.dark": str(len(bd) - len(twins)),
        "COUNT:boards.twins": str(len(twins)),
        "COUNT:boards.max": str(MAX_BOARDS),
        "COUNT:twins.max-share": "one third" if TWIN_SHARE == Fraction(1, 3) else str(TWIN_SHARE),
        "COUNT:frames.drawn": str(len(frames(spec))),
        "COUNT:lines.budget": str(SPEC_LINE_BUDGET),
        "COUNT:lines.budget-handoff": str(HAND_LINE_BUDGET),
        "COUNT:pairs": str(len(PAIRS)),
        "COUNT:km.commands": str(len(km_commands())),
        "COUNT:rk.keys": str(len(rk_keys())),
        "COUNT:query.max": grab(r"maxLength: (\d+)", base_line("22", 3787), "22:3690"),
        "COUNT:ranked": grab(r"≤ (\d+) ranked results", base_line("E08-D05", 45), "E08:45"),
        "COUNT:recent": grab(r"\*\*Recents\*\* \((\d+)\)", base_line("E08-D05", 50), "E08:50"),
        "COUNT:windowed": grab(r"above (\d+); ≤", base_line("E08-D05", 126), "E08:126"),
    }


# ---- colour


def theme_hex(theme: str, name: str) -> str:
    return hex_of(load_theme(theme), f"color.{name}")


def mark_min_base() -> Decimal:
    return Decimal(grab(r"≥(\d+(?:\.\d+)?):1", base_line("05", 126), "05:126"))


def mark_min() -> Decimal:
    return MARK_MIN_OVERRIDE[-1] if MARK_MIN_OVERRIDE else mark_min_base()


def text_min() -> Decimal:
    return Decimal(grab(r"≥(\d+(?:\.\d+)?):1", base_line("05", 125), "05:125"))


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


def conflict_matrix() -> dict[str, dict[str, object]]:
    """For every key §9.1 binds: the `KM` commands sharing it and whether `RK` reserves it."""
    out: dict[str, dict[str, object]] = {}
    for key in ("1..9", "/", "I", "Alt+↑", "Alt+↓", "Esc"):
        out[key] = {
            "sharing": [f"{c[0]} ({c[1]}: {c[2]})" for c in sharing(key)],
            "reserved": reserved(key),
        }
    return out


@functools.lru_cache(maxsize=4)
def compute_cached(spec: str, hand: str) -> tuple[tuple[tuple[str, str], ...], str]:
    del hand  # the hand-off adds no computed key of its own
    v: Values = {}
    v |= budget_values()
    v |= count_values(spec)
    v |= colour_values()
    chip, name = hero()
    extra = {
        "ladder": [
            {"slot": i + 1, "label": lab, "code": code_of(lab), "name": name_of(lab)}
            for i, lab in enumerate(ladder())
        ],
        "hero": {"chip": chip, "name": name},
        "served_codes": served_codes(),
        "key_conflicts": conflict_matrix(),
        "contrast": {
            t: {k: round(r, 3) for k, r in row.items()} for t, row in contrast_grid().items()
        },
        "themes_json": themes_json_names(),
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


def anch(text: str) -> str:
    """Every placeholder written as its anchor (the gates read filled and unfilled docs alike)."""
    return PLACEHOLDER.sub(lambda m: f"<!--={m[1]}-->", text)


# copy columns a figure may sit in: (section, column) — Table A's Old cell (verbatim at the base)
# and the copy deck's String cell (copy, its numbers part of the words)
COPY_CELLS = (("Table A", 3), ("15. Copy deck", 2))


def bare_figures(text: str, values: Values) -> list[tuple[int, str]]:
    """Figures with a unit typed by hand: outside an anchor, a quote, a code span, a cite and the
    copy cells of `COPY_CELLS`."""
    hits: list[tuple[int, str]] = []
    blank: dict[str, int] = {}
    for head, col in COPY_CELLS:
        for ln in section(text, head).split("\n"):
            if ln.startswith("|") and not is_rule(ln):
                blank[ln] = col
    for i, line in enumerate(text.split("\n"), 1):
        work = line
        if line in blank:
            cells = split_row(line)
            work = " | ".join(c for j, c in enumerate(cells) if j != blank[line])
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
    bad: list[Finding] = []
    for i, line in enumerate(text.split("\n"), 1):
        sec = h2_at(text, i)
        for m in PLACEHOLDER.finditer(CODE.sub("", line)):
            bad.append(("G-ANCHOR", f"{doc}:{i} placeholder {{{{{m[1]}}}}} not filled", doc, sec))
        spans = code_spans(line)
        for m in ANCHOR.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue  # an anchor quoted as code (the format's description)
            want = values.get(m[1])
            if want is None:
                bad.append(("G-ANCHOR", f"{doc}:{i} {m[1]} is not a computed value", doc, sec))
            elif not line[: m.start()].endswith(want) or re.search(
                r"[\w.,]$", line[: m.start() - len(want)]
            ):
                got = re.split(r"[ |*(]", line[: m.start()])[-1]
                msg = f"{doc}:{i} {m[1]} reads {got!r}; the tool computes {want!r}"
                bad.append(("G-ANCHOR", msg, doc, sec))
    for i, fig in bare_figures(text, values):
        bad.append(
            ("G-ANCHOR", f"{doc}:{i} {fig!r} is a figure typed by hand", doc, h2_at(text, i))
        )
    return bad


def g_marker_doc(doc: str, text: str, values: Values) -> list[Finding]:
    """RULED BQ-1 (a): every HTML comment (the one strip pattern) is a value anchor the tool
    computes; a hidden note, an unknown key or an unclosed comment FAILs."""
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
            bad.append(("G-MARKER", f"{doc}:{i + 1} an unclosed comment hides the rest", doc, sec))
        elif am is None or am[1] not in values:
            bad.append(("G-MARKER", f"{doc}:{i + 1} a hidden comment {m[0][:40]!r}", doc, sec))
    return bad


def g_hex_doc(doc: str, text: str) -> list[Finding]:
    """BQ-17: a hex is the tool's (an anchored value), never typed by hand."""
    bad: list[Finding] = []
    for i, line in enumerate(text.split("\n"), 1):
        work = CODE.sub(lambda c: " " * len(c[0]), line)
        for m in HEXLIT.finditer(work):
            if not re.match(r"<!--=(?:HEX|TINT):", line[m.end() :]):
                msg = f"{doc}:{i} {m[0]} typed by hand (not the tool's value)"
                bad.append(("G-HEX", msg, doc, h2_at(text, i)))
    return bad


# ---------------------------------------------------------------------------- cites


def cite_findings(docs: dict[str, str], fetch: Fetch) -> tuple[list[Finding], list[str], int]:
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
                if m["a"] and not (re.fullmatch(r"\d{2}", cid) or cid in CODE_IDS or "/" in cid):
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
    for cid, n, frag in CITED:
        rel = cite_path(cid)
        base = lines_of(BASE, rel) if rel else None
        if base is None or n > len(base) or frag not in base[n - 1]:
            hits = [i + 1 for i, ln in enumerate(base or []) if frag in ln]
            msg = f'`{cid}`:{n} "{frag[:40]}" not on the line (found {hits[:4]})'
            fails.append(("G-CITE", msg, None, None))
    return fails, warns, len(done) + len(CITED)


# ---------------------------------------------------------------------------- the texts


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    plans: tuple[tuple[str, str], ...]  # working-tree `05` `14` `15` `16` `22` `KM` `RK`
    values: Values = field(default_factory=dict)


@functools.lru_cache(maxsize=64)
def lex_cached(doc: str, text: str) -> tuple[LexUnit, ...]:
    return tuple(lex_units(doc, text))


def lex(t: Texts) -> list[LexUnit]:
    return [*lex_cached("spec", t.spec), *lex_cached("hand", t.hand)]


def spec_sec(t: Texts, head: str) -> str:
    return h2_of(t.spec, head)


def hand_sec(t: Texts, head: str) -> str:
    return h2_of(t.hand, head)


def F(tag: str, msg: str, doc: str | None, sec: str | None) -> Finding:
    return (tag, msg, doc, sec)


def lexicon(
    tag: str, what: str, term: str, near: str = "", unless: str = "", head: str = ""
) -> Callable[[Texts], list[Finding]]:
    """No clause asserts `term` (naming `near`); `head` restricts it to one spec section."""

    def run(t: Texts) -> list[Finding]:
        units = lex(t)
        if head:
            sec = spec_sec(t, head)
            units = [u for u in units if u.doc == "spec" and u.sec == sec]
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
            F(tag, f"§{head.split(' ')[0]} lacks {n!r}", doc, sec) for n in needles if n not in body
        ]

    return run


def both(*gates: Callable[[Texts], list[Finding]]) -> Callable[[Texts], list[Finding]]:
    def run(t: Texts) -> list[Finding]:
        return [x for gate in gates for x in gate(t)]

    return run


def g_unbuilt(t: Texts) -> list[Finding]:
    """BQ-1: §0 states the chart UI is unbuilt and names the implementing stories."""
    sec = spec_sec(t, "0. Status")
    raw = section(t.spec, "0. Status")
    body = norm_text(raw)
    bad = [
        F("G-UNBUILT", f"§0 lacks {n!r}", "spec", sec)
        for n in ("the chart ui is unbuilt", "this spec is the implementation contract")
        if n not in body
    ]
    bad += [
        F("G-UNBUILT", f"§0 does not name {s}", "spec", sec)
        for s in STORIES
        if not re.search(re.escape(s[:-1]) + r"[,)]", raw)
    ]
    if OWNER_PENDING.split(" (")[0] not in norm_text(t.spec.split("\n## ")[0]):
        bad.append(
            F("G-UNBUILT", "the status line lacks 'owner approval pending'", "spec", "(top)")
        )
    return bad


def g_trace(t: Texts) -> list[Finding]:
    """BQ-1: the trace has one row per acceptance criterion."""
    rows = table_rows(section(t.spec, "Acceptance-criteria trace"))
    have = {m[1] for r in rows if (m := re.match(r"(AC\d)\b", r[0]))}
    sec = spec_sec(t, "Acceptance-criteria trace")
    return [
        F("G-TRACE", f"no {a} row", "spec", sec)
        for a in ("AC1", "AC2", "AC3", "AC4", "AC5")
        if a not in have
    ]


def g_boards(t: Texts) -> list[Finding]:
    """BQ-23: at most MAX_BOARDS boards, twins at most TWIN_SHARE, the three ruled twins, each
    board's theme cell matching its kind, each frame a window on a board canvas."""
    sec = spec_sec(t, "0. Status")
    rows = board_rows(t.spec)
    bad: list[Finding] = []
    twins = [r for r in rows if is_twin(r)]
    if len(rows) > MAX_BOARDS:
        bad.append(F("G-BOARDS", f"{len(rows)} boards > {MAX_BOARDS}", "spec", sec))
    if rows and Fraction(len(twins), len(rows)) > TWIN_SHARE:
        bad.append(F("G-BOARDS", f"{len(twins)} twins of {len(rows)} > one third", "spec", sec))
    if {r[2] for r in twins} != TWINS:
        bad.append(F("G-BOARDS", "the twins are not comfortable 01, light 02, hc 01", "spec", sec))
    if "every board is a canvas of frames, each frame a" not in norm_text(
        section(t.spec, "0. Status")
    ):
        bad.append(F("G-BOARDS", "§0 does not make each frame a window on a canvas", "spec", sec))
    if "a refinement of bq 23 within lever 4" not in norm_text(section(t.spec, "20.2 Deviations")):
        msg = "§20.2 does not record the added frames as a refinement of BQ-23"
        bad.append(F("G-BOARDS", msg, "spec", spec_sec(t, "20.2 Deviations")))
    for r in rows:
        want = "light" if r[2].startswith("light") else "hc" if "high-contrast" in r[2] else "dark"
        if len(r) < 5 or r[3] != want or not drawn_cell_ok(r):
            bad.append(F("G-BOARDS", f"board {r[0]}: theme or status cell", "spec", sec))
    script = ROOT / BOARD_SCRIPT
    sha = hashlib.sha256(script.read_bytes()).hexdigest() if script.exists() else "missing"
    if f"board script r2, sha256 `{sha}`" not in section(t.spec, "0. Status"):
        bad.append(F("G-BOARDS", f"§0 does not name {BOARD_SCRIPT}'s sha256", "spec", sec))
    # #4682 lens carry: a twin board draws one frame, "as NN" of its source board; no other frame
    # is a twin (so no extra light, high-contrast or comfortable twin hides in the register)
    fsec = spec_sec(t, FRAME_HEAD)
    src = {r[0]: m[1] for r in twins if (m := re.search(r"twin of (\d{2})\b", r[2]))}
    on: dict[str, list[dict[str, str]]] = {}
    for fr in frames(t.spec):
        on.setdefault(fr.get("Board", ""), []).append(fr)
        as_of = re.fullmatch(r"as (\d{2})\b.*", fr.get("State", ""))
        if as_of and src.get(fr.get("Board", "")) != as_of[1]:
            msg = f"{fr['Frame']}: a twin frame off its twin board"
            bad.append(F("G-BOARDS", msg, "spec", fsec))
    for b, of in src.items():
        got = [fr.get("State", "") for fr in on.get(b, [])]
        if len(got) != 1 or not re.fullmatch(rf"as {of}\b.*", got[0]):
            msg = f"twin board {b} draws {len(got)} frames, not one 'as {of}'"
            bad.append(F("G-BOARDS", msg, "spec", fsec))
    return bad


def png_size(rel: str) -> tuple[int, int] | None:
    """Width and height from a working-tree PNG's IHDR, else None."""
    path = ROOT / rel
    head = path.read_bytes()[:24] if path.is_file() else b""
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return int(w), int(h)


def drawn_cell_ok(row: list[str]) -> bool:
    """A §0 Status cell reads `drawn (r2): board id `<uuid>`, `<its export path>` (W × H)`, the
    path the board's own slug names and W × H its PNG header (the boards PR)."""
    slug = re.fullmatch(rf"`E12-D04 / {row[0]} ([a-z0-9-]+)`", row[1])
    m = DRAWN_CELL.fullmatch(row[4])
    if not slug or not m:
        return False
    want = f"docs/design/E12/img/E12-D04-{row[0]}-{slug[1]}.png"
    return m["png"] == want and png_size(want) == (int(m["w"]), int(m["h"]))


def g_penpot(t: Texts) -> list[Finding]:
    """BQ-1, BQ-23: the Penpot page by name + id only: no URL, no host."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if URL.search(line):
                bad.append(F("G-PENPOT", f"{doc}:{i} a URL", doc, h2_at(text, i)))
    return bad


def g_split(t: Texts) -> list[Finding]:
    """BQ-3 (confirmed): E08-D05's symbol half is consumed, its boards cited, never redrawn."""
    sec = spec_sec(t, "0. Status")
    raw = section(t.spec, "0. Status")
    body = norm_text(raw)
    bad = [
        F("G-SPLIT", f"§0 does not cite E08-D05's {b}", "spec", sec)
        for b in E08_BOARDS
        if not re.search(rf"\({b}\)", raw)
    ]
    for n in (
        "cited, not redrawn",
        "redraws an e08 d05 frame only where a bar mode element changes it",
    ):
        if n not in body:
            bad.append(F("G-SPLIT", f"§0 lacks {n!r}", "spec", sec))
    hits = claims(
        lex(t),
        r"\bredraw(?:s|n)?\b|\bdraws? (?:scr 041 )?whole\b",
        near=r"\bsymbol half\b|\bscr 041 whole\b|\be08 d05's (?:boards?|frames?)\b",
        unless=r"\bonly where\b|\balternative\b",
    )
    return bad + as_findings("G-SPLIT", "the symbol half redrawn", hits)


def g_locked(t: Texts) -> list[Finding]:
    """BQ-2: §1.3 holds a cited row for each parent."""
    sec = spec_sec(t, "1.3 Locked")
    rows = table_rows(section(t.spec, "1.3 Locked"))
    bad: list[Finding] = []
    for lead in LOCKED_LEADS:
        hit = [r for r in rows if r[0].startswith(lead + " ")]
        if not hit or not all(CITE_GROUP.search(r[1]) for r in hit):
            bad.append(F("G-LOCKED", f"§1.3 has no cited {lead} row", "spec", sec))
            continue
        frag = LOCKED_FRAG.get(lead)
        m = CITE_GROUP.search(hit[0][1])
        if frag and m:
            lo = int(re.split(r"[–-]", m["first"])[0])
            rel = cite_path(m["a"] or m["b"])
            first = (git_show(BASE, rel) or "").split("\n")[lo - 1 : lo] if rel else []
            if not any(frag in ln for ln in first):
                msg = f"§1.3 {lead} row's cite :{m['first']} does not hold {frag!r}"
                bad.append(F("G-LOCKED", msg, "spec", sec))
    return bad


def a_rows(hand: str) -> dict[str, list[str]]:
    rows = table_rows(section(hand, "Table A"))
    return {r[0]: r for r in rows if re.fullmatch(r"A-\d+", r[0])}


def g_arow(t: Texts) -> list[Finding]:
    """BQ-4: Table A runs A-1 … A-n without a gap, and every A-n the spec names exists."""
    have = a_rows(t.hand)
    sec = hand_sec(t, "§C Copy-ready")
    bad: list[Finding] = []
    nums = sorted(int(k[2:]) for k in have)
    if nums != list(range(1, len(nums) + 1)) or len(nums) < 8:
        bad.append(F("G-AROW", f"Table A is not A-1 … A-8: {nums}", "hand", sec))
    named = set(re.findall(r"(?<![\w-])A-(\d+)\b", strip_comments(t.spec)))
    for n in sorted(named, key=int):
        if f"A-{n}" not in have:
            bad.append(F("G-AROW", f"A-{n} is named but not in Table A", "hand", sec))
    return bad


def _flat(text: str) -> str:
    t = text.replace("\\|", "|")
    t = re.sub(r"[`*]", "", t)
    return " ".join(unicodedata.normalize("NFKC", t).split())


def whole_runs(value: str) -> set[str]:
    """Every run of whole parts of a list item's value: the parts are split at " · " (props) and
    before a checkbox "[ ]"; an Old cell must be one such run, so applying its New leaves no stale
    remainder of the same part."""
    cuts = sorted({0, len(value), *(m.end() for m in re.finditer(r" · | (?=\[[ x]\] )", value))})
    return {value[a:b].strip().removesuffix(" ·").strip() for a in cuts for b in cuts if b > a}


def g_old(t: Texts) -> list[Finding]:
    """BQ-4: every Old cell of Table A is verbatim on its cited line at the base, whole parts."""
    sec = hand_sec(t, "§C Copy-ready")
    bad: list[Finding] = []
    for aid, r in a_rows(t.hand).items():
        old = r[3]
        if old in ("—", ""):
            continue
        m = CITE_GROUP.search(r[2])
        if not m:
            bad.append(F("G-OLD", f"{aid}: no cite in its Field cell", "hand", sec))
            continue
        cid = m["a"] or m["b"]
        nums = [int(x) for x in re.split(r"[–-]", m["first"])]
        more = [int(x) for x in re.findall(r":(\d+)", m["more"])]
        lo, hi = min(nums + more), max(nums + more)
        rel = cite_path(cid)
        base = (git_show(BASE, rel) or "").split("\n") if rel else []
        lines = [_flat(x) for x in base[lo - 1 : hi]]
        item = re.match(r"^- \*\*[^*]+\*\*:?\s*", base[lo - 1]) if lo == hi and base else None
        if item and _flat(old) not in whole_runs(_flat(base[lo - 1][item.end() :])):
            bad.append(F("G-OLD", f"{aid}: Old is not whole parts of `{cid}`:{lo}", "hand", sec))
            continue
        if _flat(old) not in " ".join(lines):
            bad.append(F("G-OLD", f"{aid}: Old not verbatim at `{cid}`:{lo}", "hand", sec))
    return bad


# ---- the strip (BQ-6) and the stores (BQ-12)


def parity_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "3.1 The parity")) if re.match(r"\d", r[0])]


def g_parity(t: Texts) -> list[Finding]:
    """BQ-6: the strip's nine rows are D02:182-183's ladder in slot order, each code a served one
    (D03:67), each chip `[N label]`, each name the spoken interval; the hero row is D03's."""
    sec = spec_sec(t, "3.1 The parity")
    rows = parity_rows(t.spec)
    bad: list[Finding] = []
    lab = ladder()
    served = set(served_codes())
    slots = [r for r in rows if re.fullmatch(r"\d", r[0])]
    if [r[0] for r in slots] != [str(i) for i in range(1, 10)]:
        bad.append(F("G-PARITY", f"slots {[r[0] for r in slots]} are not 1 … 9", "spec", sec))
    for r, want in zip(slots, lab, strict=False):
        code = code_of(want)
        if len(r) < 4 or r[1] != f"`{code}`" or code not in served:
            bad.append(F("G-PARITY", f"slot {r[0]} entry {r[1]!r} != `{code}`", "spec", sec))
        elif r[2] != f"`[{r[0]} {want}]`":
            bad.append(F("G-PARITY", f"slot {r[0]} chip {r[2]!r} != [{r[0]} {want}]", "spec", sec))
        elif r[3] != f'"{name_of(want)}"':
            bad.append(F("G-PARITY", f"slot {r[0]} name {r[3]} != {name_of(want)!r}", "spec", sec))
    src = ladder_lines()
    for r in slots:
        if len(r) < 5 or r[4] != f"D02:{src.get(r[0], 0)}":
            got = r[4] if len(r) > 4 else ""
            msg = f"slot {r[0]} source {got!r} != D02:{src.get(r[0], 0)}"
            bad.append(F("G-PARITY", msg, "spec", sec))
    chip, name = hero()
    hr = [r for r in rows if r[0].startswith("9 (")]
    if not hr or hr[0][2] != f"`{chip}`" or hr[0][3] != f'"{name}"':
        bad.append(F("G-PARITY", f"the hero row is not D03's {chip} {name!r}", "spec", sec))
    body = section(t.spec, "3.1 The parity")
    if 'named "Favourites"' not in body or 'named "Interval"' in body:
        bad.append(
            F("G-PARITY", 'the strip group is not named "Favourites" (D03:332)', "spec", sec)
        )
    for n in ("each with its own digit and no renumbering", "only the roles differ"):
        if n not in norm_text(body):
            bad.append(F("G-PARITY", f"§3.1 lacks {n!r}", "spec", sec))
    return bad


g_onelist = both(
    require("G-ONELIST", "1.4 Rules", ("the strip is the same nine slots scr 042 edits",)),
    lexicon(
        "G-ONELIST",
        "a second favourites list",
        r"\b(?:second|separate|another|parallel|own|local) (?:favourites? |interval )?"
        r"(?:list|ladder|store|copy)\b",
        near=r"\bfavourites?\b|\bstrip\b|\bladder\b|\bslots?\b",
    ),
)
g_units = require(
    "G-UNITS", "3.2 Units", ('"volume, 50 eth per bar"', "keeps its literal parameter")
)
g_store = both(
    require(
        "G-STORE",
        "3.3 The stores",
        (
            "contract first (c 6.1) by e12 s11 (#451), not by a contract pr from this ticket",
            "e08 d05 d 9's fallback",
            "d03's read only default ladder",
            "viewer: no write",
            "nothing is written",
        ),
    ),
    lexicon(
        "G-STORE",
        "this ticket landing the store's contract",
        r"\b(?:this ticket|e12 d04|pr 1|this spec) (?:opens|lands|files|ships|adds|carries) "
        r"(?:the |a )?(?:store'?s? )?contract(?: pr)?\b",
    ),
    lexicon(
        "G-STORE",
        "a Viewer writing the stores",
        r"\b(?:a |the )?viewers? (?:writes|can write|may write|saves|can save|edits|can edit)\b",
        unless=r"\balternatives?\b|\bowner's\b",
    ),
)


g_t2 = both(
    require(
        "G-T2",
        "3.2 Units",
        (
            "a t2 slot never takes aria checked",
            "the reason renders in the preview's mode line, the one aria describedby target",
        ),
    ),
    lexicon(
        "G-T2",
        "a T2 slot checked",
        r"\b(?:takes?|gets?|keeps?|receives?) aria checked\b"
        r"|\b(?:checks?|selects?) (?:it|the t2 slot|that slot)\b|\bis checked\b",
        near=r"\bt2 slots?\b",
        unless=r"\bcurrent mode\b",
    ),
)


# ---- commit (BQ-7), carry (BQ-8), validity (BQ-9)


def commit_rows(spec: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in table_rows(section(spec, "4. Commit")):
        out.setdefault(r[0], r)
    return out


def g_commit(t: Texts) -> list[Finding]:
    """BQ-7: the commit table's rows: Enter in the input, the strip's check and Enter, a slot that
    needs a build, an unavailable slot, an empty digit, Shift+Enter, Esc."""
    sec = spec_sec(t, "4. Commit")
    rows = commit_rows(t.spec)
    want = {
        "`Enter`": "commits the active symbol",
        "`Enter` on a slot that needs a build for the active symbol": "no commit: scr 042 opens",
        "`Enter` on a slot unavailable for the active symbol": "changes nothing",
        "a digit with no favourite": "changes nothing",
        "`Shift+Enter`": "opens the active symbol in a new chart",
        "`Esc`": "restores symbol and setting, sends nothing",
    }
    bad: list[Finding] = []
    for lead, needle in want.items():
        r = rows.get(lead)
        if r is None or needle not in norm_text(" ".join(r[1:])):
            bad.append(F("G-COMMIT", f"§4 row {lead!r} lacks {needle!r}", "spec", sec))
    if "no confirm: every act is reversible view state" not in norm_text(
        section(t.spec, "1.4 Rules")
    ):
        bad.append(F("G-COMMIT", "R-6 lacks 'no confirm'", "spec", spec_sec(t, "1.4 Rules")))
    strip = [r for r in table_rows(section(t.spec, "4. Commit")) if r[0] == "`Enter`"]
    if len(strip) < 2 or "together" not in norm_text(strip[1][2]):
        bad.append(F("G-COMMIT", "§4 has no strip Enter committing both together", "spec", sec))
    hits = claims(
        lex(t),
        r"\bcommits?\b|\bstarts? (?:a |the )?build(?:ing)?\b|\bkicks? off (?:a |the )?build\b"
        r"|\bappl(?:y|ies) (?:it|the slot|the mode|the interval)\b"
        r"|\bbuilds? (?:at once|immediately|right away|on (?:highlight|check|arrow)\w*)\b",
        near=r"\bneeds? a build\b|\bcheck(?:s|ing)? (?:a |the )?slot\b|\bhighlighting\b"
        r"|\barrowing\b|\barrows?\b",
        unless=r"\bno commit\b|\bbefore g 2\b|\bexplicit\b|\bnever\b|\beditor\b",
    )
    hits += claims(
        lex(t), r"\besc\b[^.;]*\b(?:commits|applies|keeps the (?:highlighted|new) \w+)\b"
    )
    return bad + as_findings("G-COMMIT", "a build or commit without the explicit act", hits)


def g_carry(t: Texts) -> list[Finding]:
    """BQ-8 (confirmed): Time the same interval; Tick, Range, Renko the same number; Volume, Delta
    the new symbol's D3-11 value."""
    sec = spec_sec(t, "5. Carry")
    rows = {r[0]: r for r in table_rows(section(t.spec, "5. Carry"))}
    want = {
        "Time": ("the same interval", "D02:39"),
        "Tick, Range, Renko": ("the same number", "D05:237"),
        "Volume, Delta": ("the new symbol's d3 11 value", "D03:56"),
    }
    bad: list[Finding] = []
    for lead, (needle, cite) in want.items():
        r = rows.get(lead)
        if r is None or needle not in norm_text(r[1]) or cite not in r[2]:
            bad.append(F("G-CARRY", f"§5 {lead}: not {needle!r} ({cite})", "spec", sec))
    if len(rows) != 3:
        bad.append(F("G-CARRY", f"§5 has {len(rows)} mode rows, not 3", "spec", sec))
    body = norm_text(section(t.spec, "5. Carry"))
    for n in ("never silent", "only a carried mode takes d3 11's swap", 'the "→" is aria hidden'):
        if n not in body:
            bad.append(F("G-CARRY", f"§5 lacks {n!r}", "spec", sec))
    hits = claims(
        lex(t),
        r"\bsilent(?:ly)?\b|\bunannounced\b|\bquietly\b"
        r"|\bwithout (?:naming|saying|a word|notice|warning|telling)\b",
        near=r"\bswap\b|\bparameter\b|\bd3 11\b|\bcarried\b|\bfallback\b",
    )
    hits += claims(lex(t), r"\bresets? to time\b", unless=r"\balternative\b")
    return bad + as_findings("G-CARRY", "a carried value changed silently", hits)


g_probe_text = require(
    "G-PROBE",
    "6.2 The probe",
    (
        "only when the chart's mode is non time",
        "one get /market/data coverage",
        "one in flight, cached for the session",
        f"bounded at {PROBE_S} s",
        "the state is unknown, no claim is made, and the commit falls through to f bar 5",
        "never delays the commit of a time mode chart",
        "on a time mode chart a non time slot therefore makes no t2 claim for missing prints",
        "enter before the answer sends the probe at once",
        "holds the commit up to the bound",
    ),
)
g_probe = both(
    g_probe_text,
    lexicon(
        "G-PROBE",
        "a probe for a time-mode chart",
        r"\b(?:runs?|fires?|is sent|sends?|waits?|delays?)\b[^.;]*\btime mode\b"
        r"|\btime mode (?:charts?|commits?)\b[^.;]*\b(?:probe|wait\w*|delay\w*)\b",
        near=r"\bprobe\b|\bcoverage\b",
    ),
    # #4682 lens carry: a time-mode chart claims "no recorded prints" (T2, C-24) with no answer
    lexicon(
        "G-PROBE",
        "a missing-prints claim on a time-mode chart",
        r"\btime mode\b[^.;]*\b(?:no recorded prints|missing prints|c 24|t2|unavailable"
        r"|can'?t be built)\b|\b(?:no recorded prints|c 24|t2|unavailable)\b[^.;]*\btime mode\b",
        near=r"\bslots?\b|\bprints\b|\bc 24\b|\bvolume\b|\bdelta\b|\bmode\b",
        unless=r"\bsession cached?\b|\bunless\b|\bno t2 claim\b",
    ),
    # a slot reads unavailable at once, before the bounded probe answers
    lexicon(
        "G-PROBE",
        "a slot unavailable before the probe answers",
        r"\b(?:unavailable|greyed|grayed|disabled|dimmed|struck|marked)\b[^.;]*\b(?:straight away"
        r"|immediately|at once|instantly|right away|without waiting)\b|\b(?:straight away"
        r"|immediately|at once|instantly|right away)\b[^.;]*\b(?:unavailable|greyed|grayed"
        r"|disabled)\b",
        near=r"\bslots?\b|\bprobe\b|\bcoverage\b",
        unless=r"\bsession cached?\b|\bunless\b|\bno t2 claim\b|\bnever\b",
    ),
)
g_fallback = both(
    require(
        "G-FALLBACK",
        "6.3 The fallback",
        (
            "the panel's last time interval before it entered the non time mode",
            "default_bar_type / default_param when that is time",
            "slot 1 of the default ladder",
            "never a build",
        ),
    ),
    lexicon(
        "G-FALLBACK",
        "an automatic return to the mode",
        r"\b(?:restores?|returns? to|switch(?:es)? back to|brings? back|re ?applies) the "
        r"(?:non time |\w+ )?mode\b|\bbrings? (?:the )?(?:\w+ )?mode back\b"
        # #4682 lens carry: the same return with other verbs, or naming the mode itself
        r"|\b(?:restores?|returns?|switch(?:es)?|reverts?|goes|go|puts?|flips?|changes?|resumes?"
        r"|brings?|re ?applies)(?: \w+){0,3}? (?:back )?(?:to )?(?:the )?(?:non time |previous "
        r"|earlier |carried )?(?:mode|volume|delta|tick|range|renko)(?: bars| mode)?\b"
        r"(?: \w+){0,3}? (?:back|again|on its own|by itself|automatically)\b"
        r"|\b(?:reverts?|goes|go|switch(?:es)?|flips?) (?:\w+ ){0,2}?back to (?:the )?(?:\w+ )?"
        r"(?:mode|volume|delta|tick|range|renko)\b"
        r"|\breverts? (?:\w+ ){0,2}?to (?:the )?(?:\w+ )?(?:mode|volume|delta|tick|range|renko)\b"
        r"|\bauto ?returns?\b",
        near=r"\brecorded\b|\bswitching back\b|\breturn\b|\bback\b|\bagain\b",
    ),
    # the mode named after the verb, "again" before it or "without asking" after it
    lexicon(
        "G-FALLBACK",
        "an automatic return to the mode",
        r"\b(?:returns?|reverts?|reinstates?|restores?|resumes?)\b[^.;]*\b(?:volume|delta|tick"
        r"|range|renko)(?: bars| mode)?\b",
        near=r"\brecorded again\b|\bagain\b|\bwithout (?:the user |anyone )?ask\w*\b"
        r"|\bon its own\b|\bautomatically\b",
    ),
    lexicon(
        "G-FALLBACK",
        "a fallback that builds",
        r"\b(?:starts?|runs?|triggers?|kicks? off)\b (?:a |the )?build",
        near=r"\bfallback\b|\bfalls? back\b",
    ),
)
g_words = require(
    "G-WORDS",
    "6.4 The words",
    (
        "the two cases kept apart",
        "s 6, \"ethfiusdt has no recorded prints, so volume bars can't be built for it.",
        's 7, "volume bars need recorded prints · showing 1m" with dismiss',
        's 8, "chart 1 now shows ethfiusdt, 1 minute.',
        "never an unmerged text",
        "a 1..9 hotkey on the chart",
        "j5 stays for deep links and restored panes",
        "or for an unknown lot size s 25",
        "for the lot case, s 26 and s 27",
        "s 7 and s 26 offer only dismiss",
    ),
)


# ---- switching (BQ-10)


g_retain = both(
    require(
        "G-RETAIN",
        "7.1 Frame by frame",
        ("over the retained frame", "no skeleton and no blank canvas on a switch"),
    ),
    lexicon(
        "G-RETAIN",
        "a blank or skeleton frame on a switch",
        r"\bblank (?:canvas|pane|chart|frame)\b|\bskeleton\b|\bempty (?:pane|chart|canvas)\b"
        r"|\bclears? the (?:pane|chart|canvas|frame)\b|\bwhite flash\b"
        r"|\b(?:goes|turns|is left) (?:blank|empty|white)\b|\bblanks? (?:the|out)\b|\bempties\b"
        r"|\b(?:drops?|discards?|removes?|unmounts?) the (?:previous|old|retained) frame\b"
        r"|\bspinner\b|\b(?:previous|old|retained) frame (?:is |gets )?(?:dropped|discarded|removed"
        r"|cleared|unmounted)\b",
        unless=r"\bbootstrap\b|\bno white flash\b",
    ),
)
g_centre = require(
    "G-CENTRE",
    "7.2 Centre",
    (
        "a paused chart keeps its visible time centre and a live chart keeps following",
        "on a symbol change the same holds for time bars, by time (proposed",
    ),
)
# the verbs that end the old topics and start the new ones (G-SUBS, the #4682 lens carry)
_END = r"(?:unsub\w*|releases?|drops?|leaves?|closes?|cancels?|ends?|stops?|tears? down)"
_START = r"(?:sub(?:s|scribes?)?|requests?|joins?|opens?|adds?|starts?)"
g_subs = both(
    require(
        "G-SUBS",
        "7.2 Centre",
        (
            "sub the new topics first, keep the old ones and the frame",
            "until the new snapshot paints, then unsub the old ones",
        ),
    ),
    lexicon(
        "G-SUBS",
        "the old topics unsubscribed first or in one frame",
        r"\bunsub\w*\b(?: \w+){0,3}? (?:first|before (?:the )?sub\w*|at the sub\b"
        r"|immediately|at once|with the sub\w*)"
        r"|\b(?:swaps?|changes?|replaces?) (?:the )?subscriptions? (?:with|in) (?:one|a single) "
        r"(?:ws )?frame\b|\b(?:one|a single) (?:ws )?frame (?:swaps?|carries|does|holds) "
        r"(?:the |both )?(?:subscriptions?|sub and unsub|both)\b",
    ),
    # #4682 lens carry: the old topics end before the new ones start, in other words
    lexicon(
        "G-SUBS",
        "the old topics ended before the new ones start",
        rf"\b{_END}\b(?: \w+){{0,2}}? old (?:topics?|subscriptions?|streams?|ones)\b[^.;]*"
        rf"\b(?:then|before|followed by|first|after which|and only then)\b[^.;]*\b{_START}\b"
        rf"|\bbefore (?:it |the client |we )?{_START}\b[^.;]*\bnew\b[^.;]*\b{_END}\b[^.;]*\bold\b"
        rf"|\b{_START}\b[^.;]*\bnew\b[^.;]*\b(?:after|once)\b(?: \w+){{0,3}}? {_END}\b"
        rf"(?: \w+){{0,2}}? old\b",
    ),
)
g_keepchart = both(
    require(
        "G-KEEPCHART", "7.2 Centre", ("a failed switch keeps the working chart", "never scr 048")
    ),
    lexicon(
        "G-KEEPCHART",
        "a failed switch that replaces the chart",
        r"\bscr 048\b|\b(?:removes?|replaces?|drops?) the (?:working )?chart\b",
        near=r"\bfail\w*\b",
    ),
)


# ---- search and preview (BQ-11, BQ-13)


g_rank = require(
    "G-RANK",
    "8.1 Search",
    (
        "the tie break order inside a tier",
        "the strip's slots never enter the symbol ranking",
        "cited, not restated",
    ),
)
g_preview = both(
    require(
        "G-PREVIEW",
        "8.2 The preview",
        (
            "has no funding rate",
            "24 h turnover from a ticker the client already holds",
            "never ?q= per keystroke",
            "no network round trip for a cached symbol",
        ),
    ),
    lexicon(
        "G-PREVIEW",
        "a per-symbol fetch for the preview",
        r"\b(?:fetch|request|send|call|quer(?:y|ies))(?:es|s|ed|ing)?\b[^.;]*"
        r"\b(?:ticker|instruments?\b|q=)",
        near=r"\bpreview\b|\bhighlight\w*\b|\bactive option\b|\bkeystroke\b",
        unless=r"\bnever\b|\blocal index\b|\bno network\b",
    ),
    # #4682 lens carry: `Instrument` holds only the funding interval, never a rate (D04-C8)
    lexicon(
        "G-PREVIEW",
        "a funding rate in the preview",
        r"\bfunding (?:rates?|%|percent\w*|fees?|amounts?|values?)\b"
        r"|\b(?:current|predicted|next|live|estimated|latest) funding\b"
        r"|\bfunding\b[^.;]*\b(?:rates?|%|percent\w*|bps|basis points)\b"
        r"|\b(?:rates?|%|percent\w*)\b[^.;]*\bfunding\b",
    ),
)


# ---- keys (BQ-14) and rebinding (BQ-15)


def key_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "9.1 Keys")) if r and r[0].startswith("`")]


def g_keys(t: Texts) -> list[Finding]:
    """BQ-14: the conflict column is the computed matrix: every `KM` command sharing a key in
    another context is named; a same-context share is the row's own command; a free key says so;
    an `RK` key is cited; a surface row stops the key at its root."""
    sec = spec_sec(t, "9.1 Keys")
    bad: list[Finding] = []
    rows = key_rows(t.spec)
    have = [r[0].strip("`") for r in rows]
    for want in ("1..9", "/", "I", "Alt+↑", "Alt+↓", "Esc"):
        if want not in have:
            bad.append(F("G-KEYS", f"§9.1 has no {want} row", "spec", sec))
    for r in rows:
        key, ctx, action, check = r[0].strip("`"), r[1], r[2], r[3] if len(r) > 3 else ""
        shared = sharing(key)
        if ctx.startswith("SCR-"):
            if "stopped at the root" not in check:
                bad.append(F("G-KEYS", f"{key} in {ctx}: not stopped at the root", "spec", sec))
            continue
        context = "Chart" if ctx.startswith("Chart") else ctx
        own = re.findall(r"`([a-z]+\.[a-z_]+)`", action)
        for cid, cctx, _b in shared:
            if cid in own:
                continue
            if cctx == context and "shadows" not in check:
                msg = f"{key}: {cid} binds it in {cctx} with no declared shadow"
                bad.append(F("G-KEYS", msg, "spec", sec))
            if f"`{cid}`" not in check and cid.replace("_up", "_up/down") not in check:
                bad.append(F("G-KEYS", f"{key}: {cid} ({cctx}) is not named", "spec", sec))
        others = [c for c in shared if c[0] not in own]
        if not others and "free in `KM`" not in check and not own:
            bad.append(F("G-KEYS", f"{key}: free in `KM` but not said so", "spec", sec))
        if others and "free in `KM`" in check:
            bad.append(F("G-KEYS", f"{key}: called free but `KM` binds it", "spec", sec))
        if reserved(key) and "`RK`" not in check:
            bad.append(F("G-KEYS", f"{key}: reserved in `RK`, not cited", "spec", sec))
        if not reserved(key) and "free in `KM` and `RK`" not in check and "`RK`" in check:
            bad.append(F("G-KEYS", f"{key}: cites `RK` but is not reserved", "spec", sec))
        if key.startswith("Alt+") and "no wrap" not in action:
            bad.append(F("G-KEYS", f"{key}: the step does not say 'no wrap'", "spec", sec))
        if key == "1..9" and "one keystroke" not in action:
            bad.append(F("G-KEYS", "1..9: not 'one keystroke'", "spec", sec))
    body = norm_text(section(t.spec, "9.1 Keys"))
    for n in ("is not adopted in r1", "recorded as rejected with that reason"):
        if n not in body:
            bad.append(F("G-KEYS", f"§9.1 lacks {n!r}", "spec", sec))
    hits = claims(
        lex(t),
        r"\b(?:adopt(?:s|ed)?|accept(?:s|ed)?|binds?|bound)\b|\bopens? on (?:a )?digits?\b",
        near=r"\bh7\b|\btyped intervals?\b",
        unless=r"\bscr 042's custom interval\b",
    )
    hits += claims(
        lex(t),
        r"\b(?:ctrl|alt)\+(?:\d|digit)\b|\b(?:ctrl|alt)\+1\.\.9\b",
        near=r"\bladder\b|\bfavourites?\b|\bslots?\b",
        unless=r"\bnav_rail\b|\breserved\b|\bno ctrl\b",
    )
    return bad + as_findings("G-KEYS", "a rejected key form adopted", hits)


g_rebind = both(
    require(
        "G-REBIND",
        "9.2 Rebinding",
        (
            "rebinding the ladder rebinds its modifier for all nine digits",
            "never per slot",
            "render the active profile's binding",
            "every slot is reachable without its key",
            "a ladder rebind is not audited",
        ),
    ),
    lexicon(
        "G-REBIND",
        "per-slot key bindings",
        r"\bper slot (?:keys?|bindings?|commands?|rebind\w*)\b|\bnine (?:separate )?commands\b"
        r"|\beach slot (?:its own|has its own) (?:key|binding)\b|\bslot by slot\b"
        r"|\bone slot at a time\b",
        unless=r"\balternative\b",
    ),
)


# ---- focus (BQ-16), sync (BQ-17), roles (BQ-18)


g_focus = require(
    "G-FOCUS",
    "10.3 Close",
    (
        "focus returns to the trigger when scr 041 was opened from it",
        "to the chart region when it was opened by /",
        "never to body",
        "a system event never moves focus",
    ),
)
g_contain = both(
    require(
        "G-CONTAIN",
        "10.2 Order",
        (
            "arrows never cross between them",
            "no trap",
            "the strip is one stop with arrows inside",
            "in the strip ↑ / ↓ move as ← / → do, and arrows wrap within the filled slots",
        ),
    ),
    lexicon(
        "G-CONTAIN",
        "focus trapped or arrows crossing",
        r"\btraps? focus\b|\bfocus (?:is )?trapped\b|\barrows?(?: keys?)? (?:cross|move|jump|pass"
        r"|travel)\w* (?:\w+ ){0,2}?(?:from|between|into|across)\b",
        near=r"\bscr 041\b|\bstrip\b|\blistbox\b|\bpopover\b",
        unless=r"\bscr 102\b",
    ),
)


def g_order(t: Texts) -> list[Finding]:
    """BQ-16: §10.2's tab order is the stated sequence."""
    line = next(
        (ln for ln in section(t.spec, "10.2 Order").split("\n") if "**Tab order:**" in ln), ""
    )
    m = re.search(r"\*\*Tab order:\*\* (.*?) \(E08-D05", line)
    got = tuple(x.strip() for x in m[1].split("→")) if m else ()
    if got != TAB_ORDER:
        return [F("G-ORDER", f"the tab order reads {got[:4]}…", "spec", spec_sec(t, "10.2 Order"))]
    return []


g_sync = both(
    require(
        "G-SYNC",
        "11. Sync",
        (
            "interval and bar mode never propagate",
            "disarms on a symbol change, announced",
            "an interval or mode change keeps the arm",
            "it joins no group",
        ),
    ),
    lexicon(
        "G-SYNC",
        "an interval or bar mode propagated",
        r"\b(?:bar modes?|intervals?|chart types?)\b[^.;]*\b(?:syncs|synced|propagates?|follows?"
        r"|shared (?:with|across) (?:the )?(?:group|panels)|copied to (?:the )?(?:group|panels))\b",
        unless=r"\bnever\b|\boff by default\b|\bsymbol on\b",
    ),
)


def g_rbac(t: Texts) -> list[Finding]:
    """BQ-18: E09-D09's sentences verbatim; the server enforces Record; view-as first."""
    body = section(t.spec, "12. Roles")
    sec = spec_sec(t, "12. Roles")
    bad = [
        F("G-RBAC", f"§12 lacks {w!r}", "spec", sec)
        for w in ("Only the owner can start recording.", "Read-only while viewing as {user}.")
        if f'"{w}"' not in body
    ]
    flat = norm_text(body)
    for n in (
        "none of it is t2",
        "first on record",
        "scr 041 has no store write control",
        "the record button as t2 (full label, aria disabled, focusable",
        "hiding the button is not the control",
        "the server enforces recording:write",
    ):
        if n not in flat:
            bad.append(F("G-RBAC", f"§12 lacks {n!r}", "spec", sec))
    hits = claims(
        lex(t),
        r"\b(?:hidden|hiding|hides?)\b[^.;]*\b(?:is )?(?:enough|sufficient|the control)\b",
        unless=r"\bnot\b",
    )
    return bad + as_findings("G-RBAC", "hiding as the control", hits)


# ---- states and budgets (BQ-19), accessibility (BQ-20), tokens (BQ-21), events (BQ-22)


def g_empty(t: Texts) -> list[Finding]:
    """BQ-19, AC5: no clause leaves the no-match state as an empty list. The state's own name
    starts with "no", which the negation reader would take as a negation, so this reads it here."""
    hits: list[tuple[str, str, str]] = []
    for u in lex(t):
        for c in clauses(u.text):
            n = norm_text(unquote(c))
            if re.search(
                r"\b(?:no match\w*|no results?)\b[^.;]*\b(?:leaves?|shows?|is|becomes?|renders?) "
                r"(?:an? |the )?(?:empty|blank) (?:list|listbox)\b|\bdead end\b",
                n,
            ) and not re.search(r"\b(?:never|not)\b", n):
                hits.append((n[:70], u.doc, u.sec))
    return as_findings("G-STATES", "an empty list with no route back", hits)


g_states = both(
    require(
        "G-STATES",
        "13.1 States",
        ("clear search", "reused verbatim", "no chip and no mode claim"),
    ),
    g_empty,
)


def g_budgets(t: Texts) -> list[Finding]:
    """BQ-19: §13.2 states each budget with the tool's key and its source."""
    sec = spec_sec(t, "13.2 Budgets")
    rows = table_rows(section(t.spec, "13.2 Budgets"))
    want = {
        "BUDGET:open": "`14`:1012",
        "BUDGET:keystroke": "`11`:730",
        "BUDGET:switch.cache": "`11`:975",
        "BUDGET:first-paint": "`14`:1023",
    }
    bad: list[Finding] = []
    for key, cite in want.items():
        if not any(key in anch(r[1]) and cite in r[2] for r in rows if len(r) > 2):
            bad.append(F("G-BUDGETS", f"§13.2 has no {key} row cited to {cite}", "spec", sec))
    if (
        "06 has no type ahead row: a d05 7 (e08 d05:571 572) is cited, not repeated"
        not in norm_text(section(t.spec, "17. Analytics"))
    ):
        msg = "§17 does not cite A-D05-7 for `06`'s type-ahead row"
        bad.append(F("G-BUDGETS", msg, "spec", spec_sec(t, "17. Analytics")))
    sym = [r for r in rows if r[0].startswith("a symbol's first paint")]
    if not sym or "PROPOSED" not in sym[0][0]:
        bad.append(F("G-BUDGETS", "the symbol first paint is not marked PROPOSED", "spec", sec))
    return bad


# what a live region says, and what a user types (G-REGIONS, the #4682 lens carry)
_SAY = r"(?:announced|announces?|spoken|speaks?|voiced|voices?|reads?(?: out| aloud)?|says?)"
_TYPED = r"(?:keystrokes?|key ?press(?:es)?|keys?|letters?|characters?|chars?|glyphs?|inputs?)"
g_regions = both(
    require(
        "G-REGIONS",
        "14. Accessibility",
        (
            "one polite region per surface",
            "never a streamed value or a per letter announcement",
            "the mode line is never announced on each highlight change",
            "skips its switch result line for that commit",
            'role="alert"',
        ),
    ),
    lexicon(
        "G-REGIONS",
        "an announcement per keystroke or highlight",
        r"\b(?:announced|spoken|speaks?|reads?)\b[^.;]*\b(?:every|each|per) "
        r"(?:keystroke|letter|highlight|arrow)"
        r"|\b(?:every|each|per) (?:keystroke|letter|highlight\w*|arrow\w*)\b[^.;]*"
        r"\b(?:announced|spoken|read(?: out)?)\b"
        # #4682 lens carry: the same with a character, a key press, voicing or as one types
        rf"|\b{_SAY}\b[^.;]*\b(?:every|each|per) (?:typed )?{_TYPED}"
        rf"|\b(?:every|each|per) (?:typed )?{_TYPED}\b[^.;]*\b{_SAY}\b"
        rf"|\b{_SAY}\b[^.;]*\b(?:as|while|whenever) (?:the user|you|they|one|someone) types?\b"
        rf"|\b(?:as|while|whenever) (?:the user|you|they|one|someone) types?\b[^.;]*\b{_SAY}\b",
    ),
)
g_density = both(
    require("G-DENSITY", "16. Tokens", ("the hero is the default density, compact",)),
    lexicon(
        "G-DENSITY",
        "comfortable as the hero",
        r"\bcomfortable(?: density)? (?:by default|(?:is|as) the (?:hero|default))\b"
        r"|\bhero is comfortable\b|\bdefaults? to comfortable\b",
    ),
)
g_tokenuse = require(
    "G-TOKENUSE",
    "16. Tokens",
    ("never font.mono", "never on the checked fill", "the offset, not the hue"),
)


def g_search_props(t: Texts) -> list[Finding]:
    """#4682 lens carry: `symbol.searched` carries exactly `surface: "scr-041"`, never the query
    under any property name (E08-D05:439-440)."""
    sec = spec_sec(t, "17. Analytics")
    for r in table_rows(section(t.spec, "17. Analytics")):
        if "`symbol.searched`" in r[0] and len(r) > 1:
            props = re.findall(r"`([^`]*)`", r[1].split(";")[0])
            if props != ['surface: "scr-041"']:
                return [F("G-EVENTS", f"symbol.searched carries {props}", "spec", sec)]
            return []
    return [F("G-EVENTS", "§17 has no `symbol.searched` row", "spec", sec)]


g_events = both(
    require(
        "G-EVENTS",
        "17. Analytics",
        (
            "never the query",
            "no symbol, no parameter value",
            "no audit record",
            "keys only",
            "proposed for chart.bar_mode_changed",
        ),
    ),
    lexicon(
        "G-EVENTS",
        "an event carrying the query, a value or an account",
        r"\b(?:carr(?:y|ies)|sends?|logs?|includes?|records?)\b[^.;]*\b(?:the query|the symbol|"
        r"a symbol|parameter values?|account ids?|the account)\b"
        r"|\b(?:query|account_id)\b(?: \w+){0,2} (?:property|field)\b",
        near=r"\bevents?\b|_fallback\b|\bsymbol\.searched\b|\banalytics\b",
    ),
    lexicon(
        "G-EVENTS",
        "an audited view change",
        r"\baudit(?:ed|s)?\b|\baudit record\b",
        near=r"\brebind\b|\bstore writes?\b|\bswitch\b|\bcommit\b|\bfavourite\b|\bview state\b",
        unless=r"\bdestructive\b",
    ),
    g_search_props,
)


g_route = both(
    require(
        "G-ROUTE",
        "2.1 The three",
        (
            "only through the strip of nine favourites",
            "in one commit",
            "keeps its own width",
            "no parameter editor sits inside scr 041",
            "chart type stays on the toolbar",
            "takes d06 q1's callout instead of a commit",
        ),
    ),
    lexicon(
        "G-ROUTE",
        "SCR-041 changing the chart type",
        r"\b(?:changes?|sets?|switch(?:es)?) the chart type\b|\bchart type (?:can be |is )?"
        r"(?:changed|set|switched) (?:from|in|by)\b",
        near=r"\bscr 041\b|\bswitcher\b|\bstrip\b",
    ),
    # #4682 lens carry: a chart-type control (a chip row, a picker) or a pick of a type in SCR-041
    lexicon(
        "G-ROUTE",
        "a chart-type control in SCR-041",
        r"\bchart types? (?:chips?|picker|radios?|radiogroup|buttons?|toggles?|controls?|selectors?"
        r"|menus?|choices?|rows?|switch(?:es|er)?|segments?|tabs?|options?|slots?)\b"
        r"|\b(?:picks?|chooses?|selects?|sets?|switch(?:es)?|changes?|toggles?)\b(?: \w+){0,3}? "
        r"(?:to )?(?:line|candles?|hollow candles?|area|baseline|ohlc|columns?)"
        r"(?: or (?:line|candles?|hollow candles?|area|baseline|ohlc|columns?))?\b",
        near=r"\bscr 041\b|\bswitcher\b|\bstrip\b|\bpopover\b|\bpreview\b|\bslots?\b|\bchips?\b",
    ),
)


def g_owner(t: Texts) -> list[Finding]:
    """BQ-9, BQ-12 (OWNER): each owner item is marked PROPOSED, owner approval pending."""
    bad: list[Finding] = []
    marker = f"PROPOSED, {OWNER_PENDING}"
    for head in ("3.3 The stores", "6. Cross-symbol"):
        level = "###" if head[0] == "3" else "##"
        line = next((ln for ln in t.spec.split("\n") if ln.startswith(f"{level} {head}")), "")
        if marker not in line:
            msg = f"§{head.split()[0]} heading lacks the marker"
            bad.append(F("G-OWNER", msg, "spec", spec_sec(t, head)))
    seg = section(t.spec, "19.2")
    for q in ("D04-Q1", "D04-Q2", "D04-G1"):
        if OWNER_PENDING not in row_segment(seg, q):
            bad.append(F("G-OWNER", f"{q} lacks {OWNER_PENDING!r}", "spec", spec_sec(t, "19.2")))
    return bad + g_owner_granted(t)


# #4682 lens carry: no clause says the owner approved BQ-9 (the fallback) or BQ-12 (the stores)
_OWNER_NEAR = r"\bbq 9\b|\bbq 12\b|\bd04 q[12]\b|\b2701\b|\bfallback\b|\bstores?\b"
g_owner_granted = both(
    lexicon(
        "G-OWNER",
        "an owner item claimed approved",
        r"\bcleared\b[^.;]*\bfinal\b|\bsign(?:ed|s)\b[^.;]*\boff\b|\bendors(?:ed|es?)\b"
        r"|\baccepted\b",
        near=_OWNER_NEAR + r"|\bowner\b",
        unless=r"\bpending\b",
    ),
    lexicon(
        "G-OWNER",
        "an owner item claimed approved",
        r"\b(?:owner )?approved\b|\bapprovals? (?:is |was |has been )?(?:granted|given|received"
        r"|recorded|in hand|obtained)\b|\b(?:granted|given|received) (?:the )?(?:owner'?s? )?"
        r"approval\b|\bsign(?:ed|s)? off\b|\bgo ahead\b|\bratified\b|\bconfirmed by the owner\b",
        near=_OWNER_NEAR,
        unless=r"\bpending\b",
    ),
)


def row_segment(body: str, rid: str) -> str:
    """The text of the G- or Q-row `rid`: from its bold id to the next bold row id or line end."""
    m = re.search(rf"\*\*{re.escape(rid)}\*\*(.*?)(?=\*\*D04-[GQ]\d+\*\*|\n|\Z)", body)
    return m[1] if m else ""


def g_grows(t: Texts) -> list[Finding]:
    """BQ-4, BQ-12, BQ-14: the G-rows and Q-rows run without a gap; G3 is the dispatcher."""
    body = section(t.spec, "19.2")
    sec = spec_sec(t, "19.2")
    bad: list[Finding] = []
    for kind, n in (("G", 7), ("Q", 3)):
        for i in range(1, n + 1):
            if f"**D04-{kind}{i}**" not in body:
                bad.append(F("G-GROWS", f"D04-{kind}{i} missing", "spec", sec))
    g3 = row_segment(body, "D04-G3")
    if g3 and ("`DSP`:38" not in g3 or "not fixed here" not in g3):
        bad.append(F("G-GROWS", "D04-G3 is not the dispatcher defect, unfixed", "spec", sec))
    return bad


def g_crows(t: Texts) -> list[Finding]:
    """BQ-3 … BQ-19: the C-rows run D04-C1 … C23 without a gap; C4 records the BQ-8 split; C22
    records D02 OQ-3's routing (BQ-12)."""
    rows = table_rows(section(t.spec, "19.1"))
    sec = spec_sec(t, "19.1")
    ids = [r[0] for r in rows if r[0].startswith("D04-C")]
    nums = [int(i[5:]) for i in ids]
    bad: list[Finding] = []
    if nums != list(range(1, len(nums) + 1)) or len(nums) < 23:
        bad.append(F("G-CROWS", f"the C-rows are {ids[:3]}…, not D04-C1 … C23", "spec", sec))
    c4 = next((r for r in rows if r[0] == "D04-C4"), None)
    if c4 is None or "D05:237" not in c4[2] or "D03:56" not in c4[1]:
        bad.append(F("G-CROWS", "D04-C4 does not record D3-11 vs D05:237", "spec", sec))
    c5 = next((r for r in rows if r[0] == "D04-C5"), None)
    if c5 is None or "#2701" not in c5[3]:
        bad.append(F("G-CROWS", "D04-C5 (F-BAR-5) is not routed to the owner", "spec", sec))
    c22 = next((r for r in rows if r[0] == "D04-C22"), None)
    if c22 is None or "D02:481" not in c22[1] or "#2701" not in c22[3]:
        bad.append(
            F("G-CROWS", "D04-C22 does not record D02 OQ-3's routing (D02:481)", "spec", sec)
        )
    return bad


def g_verbatim(t: Texts) -> list[Finding]:
    """R-7: the cited copy appears verbatim in the section that quotes it."""
    return [
        F("G-VERBATIM", f"`{cid}`:{n} {text[:40]!r} not quoted verbatim", "spec", spec_sec(t, head))
        for cid, n, text, head in VERBATIM
        if text not in " ".join(section(t.spec, head).split())
    ]


def g_verbatim_src(t: Texts) -> list[Finding]:
    """The VERBATIM strings sit on their cited lines at the base."""
    del t
    bad: list[Finding] = []
    for cid, n, text, _head in VERBATIM:
        if " ".join(text.split()) not in " ".join(base_line(cid, n).split()):
            bad.append(F("G-CITE", f"`{cid}`:{n} does not hold {text[:40]!r}", None, None))
    return bad


def deck(spec: str) -> dict[str, list[str]]:
    return {r[0]: r for r in table_rows(section(spec, "15. Copy deck")) if r[0].startswith("S-")}


def g_reuse(t: Texts) -> list[Finding]:
    """R-7 (BQ-1 (c)): every deck row marked verbatim is E08-D05's / D03's / E09-D09's text on its
    cited line, part by part; every other row is PROPOSED copy or a cited form."""
    sec = spec_sec(t, "15. Copy deck")
    rows = deck(t.spec)
    bad: list[Finding] = []
    nums = [int(k[2:]) for k in rows]
    if nums != list(range(1, len(nums) + 1)):
        bad.append(F("G-REUSE", f"the deck is not S-1 … S-n: {nums[:5]}…", "spec", sec))
    for sid, (cid, n) in REUSED.items():
        r = rows.get(sid)
        if r is None or "(verbatim)" not in r[1] or f"{cid}:{n}" not in r[3]:
            bad.append(F("G-REUSE", f"{sid} is not marked verbatim from {cid}:{n}", "spec", sec))
            continue
        src = " ".join(base_line(cid, n).split())
        for part in r[2].split(" · "):
            if part.strip() and part.strip() not in src:
                bad.append(F("G-REUSE", f"{sid} {part[:40]!r} is not on {cid}:{n}", "spec", sec))
    for sid, r in rows.items():
        if "(verbatim)" in r[1] and sid not in REUSED:
            bad.append(F("G-REUSE", f"{sid} claims verbatim with no diff", "spec", sec))
    return bad


def g_marked(t: Texts) -> list[Finding]:
    """BQ-1: PROPOSED items stay marked as proposals."""
    bad: list[Finding] = []
    for head, needle in (
        ("3.2 Units", "### 3.2"),
        ("3.2 Units", "the docs are silent"),
        ("5. Carry", "**Named before commit**"),
        ("6.3 The fallback", "### 6.3"),
        ("6.4 The words", "### 6.4"),
        ("7.2 Centre", "**Centre.**"),
        ("9.1 Keys", "| `Alt+↑`"),
        ("9.1 Keys", "| `Alt+↓`"),
        ("9.2 Rebinding", "`VAL` had no range rule"),
        ("11. Sync", "sync A: 2 more panels follow"),
        ("15. Copy deck", "## 15."),
        ("17. Analytics", "`chart.bar_mode_fallback`"),
        ("12. Roles", "| Viewer, persistence"),
    ):
        line = next((ln for ln in section(t.spec, head).split("\n") if needle in ln), "")
        if not re.search(r"PROPOSED|\(proposed\)", line):
            bad.append(
                F("G-MARKED", f"{needle!r} is not marked PROPOSED", "spec", spec_sec(t, head))
            )
    return bad


def g_close(t: Texts) -> list[Finding]:
    """A text-first doc names no closing keyword before an issue number (PR 1 is `Refs #240`)."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if re.search(
                r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d",
                norm_text(line),
            ):
                bad.append(F("G-CLOSE", f"{doc}:{i} a closing keyword", doc, h2_at(text, i)))
    return bad


D03_DECK_HEAD = "5. Copy deck"


@functools.lru_cache(maxsize=1)
def d03_deck() -> dict[str, str]:
    """D03 §5's strings by id (C-1 … C-42)."""
    out: dict[str, str] = {}
    for cells in table_rows(section(at_base(CITE_FILES["D03"]), D03_DECK_HEAD)):
        if re.fullmatch(r"C-\d+", cells[0]) and len(cells) > 2:
            out[cells[0]] = cells[2]
    return out


def g_frame(t: Texts) -> list[Finding]:
    """BQ-23: the frame register, column by column."""
    sec = spec_sec(t, FRAME_HEAD)
    boards = {r[0]: r for r in board_rows(t.spec)}
    cmps = set(re.findall(r"^### (CMP-\d{3})\b", plan("15"), MULTI))
    copy_ids = set(deck(t.spec)) | set(d03_deck())
    bad: list[Finding] = []
    for fr in frames(t.spec):
        fid = fr["Frame"]
        theme = fid.rsplit("· ", 1)[-1].rstrip("`")
        b = boards.get(fr.get("Board", ""))
        if b is None or b[3] != fr.get("Theme") or theme != fr.get("Theme"):
            bad.append(F("G-FRAME", f"{fid}: Board / Theme", "spec", sec))
        comps = fr.get("Components", "")
        for c in re.findall(r"CMP-\d+", comps):
            if c not in cmps:
                bad.append(F("G-FRAME", f"{fid}: {c} is not a catalogue entry", "spec", sec))
        for nc in re.findall(r"D02 (NC-\d+)", comps):
            if not re.search(rf"^\| {nc} +\|", at_base(CITE_FILES["D02"]), MULTI):
                bad.append(F("G-FRAME", f"{fid}: D02 {nc} is not a D02 candidate", "spec", sec))
        if fid in STRIP_FRAMES and ("D02 NC-1" not in comps or "CMP-028" in comps):
            bad.append(F("G-FRAME", f"{fid}: a strip notice is D02 NC-1, not CMP-028", "spec", sec))
        for c in re.findall(r"\b[SC]-\d+\b", fr.get("Copy", "")):
            if c not in copy_ids:
                bad.append(F("G-FRAME", f"{fid}: copy {c} is not defined", "spec", sec))
        for tok in re.findall(r"`([a-z][a-z0-9.*-]+)`", fr.get("Tokens", "")):
            if any(resolve(load_theme(th), tok) == "MISSING" for th in THEMES):
                bad.append(F("G-FRAME", f"{fid}: {tok} does not resolve", "spec", sec))
        if fr.get("Status") != "drawn":
            bad.append(F("G-FRAME", f"{fid}: status {fr.get('Status')!r}", "spec", sec))
        # PR 2 ruling (a): a frame on a recorded symbol never carries S-10, the not-recorded line
        state = fr.get("State", "")
        recorded = re.search(r"\brecorded symbol\b", state) and not re.search(
            r"\b(?:not|no|never|un)[ -]?recorded\b", state
        )
        if recorded and "S-10" in re.findall(r"\bS-\d+\b", fr.get("Copy", "")):
            bad.append(F("G-FRAME", f"{fid}: a recorded symbol with S-10's words", "spec", sec))
    need = {
        "`typing/unavailable · dark`",
        "`fallback/strip-notice · dark`",
        "`states/no-match · dark`",
    }
    have = {fr["Frame"] for fr in frames(t.spec)}
    for fid in sorted(need - have):
        bad.append(F("G-FRAME", f"the AC frame {fid} is not drawn", "spec", sec))
    return bad


TOKEN_NAME = re.compile(
    r"`((?:color|space|radius|opacity|elevation|size|type|border|motion)\.[a-z0-9.*-]+)`"
)


def g_token(t: Texts) -> list[Finding]:
    """BQ-21: every token named outside the frame register resolves, or is a routed /
    PROPOSED name with its row."""
    names = all_token_names()
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        skip = {
            ln
            for head in (FRAME_HEAD, MUTATION_HEAD)
            for ln in (section(text, head).split("\n") if doc == "spec" else [])
            if ln.startswith("|")
        }
        for i, line in enumerate(text.split("\n"), 1):
            if line in skip:
                continue
            for name in TOKEN_NAME.findall(line):
                star = name.endswith(".*") and any(n.startswith(name[:-1]) for n in names)
                aliased = f"color.{name}" in names  # a pair cell drops the `color.` prefix
                if name not in names and not star and not aliased and name not in NOT_SHIPPED:
                    msg = f"{doc}:{i} {name} neither resolves nor is routed"
                    bad.append(F("G-TOKEN", msg, doc, h2_at(text, i)))
    return bad


def g_contrast(t: Texts) -> list[Finding]:
    """BQ-21: §16 lists every pair once, with the bar of its kind; each clears its bar in all
    three themes."""
    sec = spec_sec(t, "16. Tokens")
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
        if row is None or row[4] != kind:
            bad.append(F("G-CONTRAST", f"{key}: missing or wrong bar", "spec", sec))
            continue
        bar = text_min() if kind == "text" else mark_min()
        for th in THEMES:
            if Decimal(str(math.floor(grid[th][key] * 100) / 100)) < bar:
                bad.append(F("G-CONTRAST", f"{key} {th} under {bar}:1", "spec", sec))
    if len(rows) != len(PAIRS):
        bad.append(F("G-CONTRAST", f"{len(rows)} pair rows != {len(PAIRS)}", "spec", sec))
    return bad


def odd_char(c: str) -> bool:
    """A character the pins would fold or `str.split()` would collapse: a compatibility character
    beyond CHARSET_ALLOW, a control character but a tab, a line or paragraph separator, or a space
    other than U+0020 (each is NFKC-stable but whitespace to `split()`; the #240 lens)."""
    if c in CHARSET_ALLOW or c in "\t\r":
        return False
    cat = unicodedata.category(c)
    if cat in ("Cc", "Zl", "Zp") or (cat == "Zs" and c != " "):
        return True
    return unicodedata.normalize("NFKC", c) != c


def g_charset(t: Texts) -> list[Finding]:
    """Rendered text is what the pins hold: no character `odd_char` names (a superscript or
    full-width digit, a no-break or ogham space, U+2028, a unit separator), no "..." standing for
    `…` (the pins keep `…` apart), no CR, no trailing whitespace (a hard line break)."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            odd = [c for c in line if odd_char(c)]
            whys = [f"U+{ord(c):04X}" for c in odd[:1]]
            whys += ['"..." (write U+2026)'] if "..." in line else []
            whys += ["a CR"] if "\r" in line else []
            whys += ["trailing whitespace"] if line != line.rstrip() else []
            why = ", ".join(whys)
            if why:
                bad.append(F("G-CHARSET", f"{doc}:{i} {why}", doc, h2_at(text, i)))
    return bad


def quoted_ids(cells: list[str]) -> list[str]:
    """The comment ids a Table A row's Old cell quotes from its cited line at the base."""
    if len(cells) < 4 or not (m := CITE_GROUP.search(cells[2])):
        return []
    rel = cite_path(m["a"] or m["b"])
    src = (git_show(BASE, rel) or "").split("\n") if rel else []
    first = int(re.split(r"[–-]", m["first"])[0])
    at = src[first - 1] if 1 <= first <= len(src) else ""
    return [x for x in COMMENT_ID.findall(cells[3]) if x in COMMENT_ID.findall(at)]


def g_ruled(t: Texts) -> list[Finding]:
    """Ruling form: the RULED heading cites the ruling and the BQ list; its paragraph states the
    two confirmations, the two owner items and BQ-9's two additions; every comment id the docs name
    is on the allow-list."""
    bad: list[Finding] = []
    sec = spec_sec(t, "The twenty-three questions")
    head = next((ln for ln in t.spec.split("\n") if ln.startswith("## The twenty-three")), "")
    if f"comment {RULING_ID}, on the BQ list {BQ_LIST_ID}" not in head:
        bad.append(F("G-RULED", "the RULED heading does not cite the ruling", "spec", sec))
    body = norm_text(section(t.spec, "The twenty-three questions"))
    for n in (
        "bq 3 (the split with e08 d05) is confirmed",
        "bq 8 is confirmed as the orch precedent",
        "bq 9 and bq 12 are the owner's",
        f"proposed, {OWNER_PENDING}",
        f"bounded at {PROBE_S} s",
        "the probe never delays the commit of a time mode chart",
    ):
        if n not in body:
            bad.append(F("G-RULED", f"the RULED paragraph lacks {n!r}", "spec", sec))
    # an id inside a Table A Old cell that its cited line holds at the base is quoted, not cited
    # (#4719's "RULED 6438042003" in A-6's Old): only that cell is read without it
    rows = a_rows(t.hand)
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            cells = split_row(line) if doc == "hand" and line.startswith("|") else []
            if cells and cells[0] in rows and len(cells) > 3:
                kept = [x for x in COMMENT_ID.findall(cells[3]) if x not in quoted_ids(cells)]
                line = line.replace(cells[3], " ".join(kept), 1)
            for cid in COMMENT_ID.findall(line):
                if cid not in RULED_IDS:
                    bad.append(F("G-RULED", f"{cid} is not a ruling comment", doc, h2_at(text, i)))
    return bad


@functools.lru_cache(maxsize=1)
def merge_base() -> str:
    return git_out("merge-base", "HEAD", "origin/main").strip()


def fork_point() -> str:
    """The commit this branch forked from main (`git merge-base HEAD origin/main`), else BASE (a
    WARN): `05`, `14`, `15`, `16`, `22`, `KM` and `RK` move on main under other PRs, so the working
    tree is compared with the fork point, never with a fixed sha that main has left."""
    return merge_base() or BASE


# levers for the self-test: paths pretended changed (never set outside `selftest`)
EXTRA_PATHS: list[str] = []


@functools.lru_cache(maxsize=1)
def own_pngs() -> frozenset[str]:
    """The ten PNGs the spec's §0 board rows name (`E12-D04 / NN slug`), as `drawn_cell_ok` reads
    them; any other `E12-D04-*.png` is not this ticket's."""
    spec = (ROOT / SPEC_REL).read_bytes().decode("utf-8")
    out = set()
    for row in table_rows(section(spec, "0. Status")):
        if len(row) < 2 or not re.fullmatch(r"\d\d", row[0]):
            continue
        slug = re.fullmatch(rf"`E12-D04 / {row[0]} ([a-z0-9-]+)`", row[1])
        if slug:
            out.add(f"docs/design/E12/img/E12-D04-{row[0]}-{slug[1]}.png")
    return frozenset(out)


@functools.lru_cache(maxsize=1)
def changed_paths() -> tuple[str, ...]:
    """Paths changed against the fork point: committed, staged, working tree or untracked."""
    names = git_out("diff", "--name-only", fork_point()).split("\n")
    names += git_out("ls-files", "--others", "--exclude-standard").split("\n")
    return tuple(names)


def stray_paths() -> tuple[str, ...]:
    """The changed paths that are not this ticket's own."""
    names = (*changed_paths(), *EXTRA_PATHS)
    own = own_pngs()
    return tuple(
        sorted(
            {
                n
                for n in names
                if n and n not in OWN_PATHS and n not in own and not OWN_SHEETS.fullmatch(n)
            }
        )
    )


def g_untouched(t: Texts) -> list[Finding]:
    """BQ-4: `05`, `14`, `15`, `16`, `22`, `KM` and `RK` in the working tree equal the fork point;
    no other path but this ticket's differs from it."""
    bad: list[Finding] = []
    ref = fork_point()
    for nn, text in t.plans:
        rel = cite_path(nn)
        if rel is None or text != (git_show(ref, rel) or at_base(rel)):
            bad.append(F("G-UNTOUCHED", f"`{nn}` differs from {ref[:10]}", None, None))
    bad += [F("G-UNTOUCHED", f"{p} is not this ticket's path", None, None) for p in stray_paths()]
    return bad


# a "§" reference: a section number or a hand-off letter (G-SECREF)
SEC_REF = re.compile(r"(?<![\w§])§(\d+(?:\.\d+)*|[A-Z])\b")
# what makes a "§" reference another document's: a doc id, a file, a code span right before it
FOREIGN_REF = re.compile(r"(?:\bE\d\d-D\d\d|\bD0\dh?|\bfile's|`[^`]*`|\b\d\d)\s*$")
OWN_REF = re.compile(r"(?:\bE12-D04|E12-D04\.md\)`|\bspec)\s*$")


def g_secref(t: Texts) -> list[Finding]:
    """#4682 lens carry 3: every "§" reference to this spec names one of its headings, and every
    "§A" … "§E" one of the hand-off's; another document's "§" (after its id, its file or a code
    span) is not read. Table A's Old cells are verbatim text at the base, so they are not read."""

    def numbers(text: str) -> set[str]:
        lines = text.split("\n")
        fence = fenced(lines)
        out = set()
        for i, ln in enumerate(lines):
            m = HEADING.match(ln)
            if m and not fence[i] and (n := SEC_NUM.match(m[2])):
                out.add(n[1].rstrip("."))
        return out

    own = numbers(t.spec) | numbers(t.hand)
    rows = a_rows(t.hand)
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, raw in enumerate(strip_comments(text).split("\n"), 1):
            line = raw
            cells = split_row(raw) if doc == "hand" and raw.startswith("|") else []
            if cells and cells[0] in rows and len(cells) > 3:
                line = raw.replace(cells[3], "", 1)
            for m in SEC_REF.finditer(line):
                before = line[: m.start()]
                if FOREIGN_REF.search(before) and not OWN_REF.search(before):
                    continue
                ref = m[1] if m[1][0].isdigit() else "§" + m[1]
                if ref not in own:
                    msg = f"{doc}:{i} §{m[1]} names no heading"
                    bad.append(F("G-SECREF", msg, doc, h2_at(text, i)))
    return bad


def g_budget(t: Texts) -> list[Finding]:
    """BQ-1: the spec within SPEC_LINE_BUDGET lines, the hand-off within its own."""
    bad: list[Finding] = []
    for doc, text, cap in (("spec", t.spec, SPEC_LINE_BUDGET), ("hand", t.hand, HAND_LINE_BUDGET)):
        n = text.count("\n") + (0 if text.endswith("\n") else 1)
        if n > cap:
            bad.append(
                F(
                    "G-BUDGET",
                    f"the {doc} has {n} lines > {cap}",
                    doc,
                    h2_at(text, len(text.split("\n"))),
                )
            )
    return bad


# lexicon gates first, then the measured gates; the pins (G-RULED-PIN) run last, in `audit`
LEXICON_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_penpot,
    g_unbuilt,
    g_trace,
    g_ruled,
    g_close,
    g_charset,
    g_split,
    g_onelist,
    g_route,
    g_store,
    g_t2,
    g_carry,
    g_fallback,
    g_retain,
    g_subs,
    g_preview,
    g_rebind,
    g_contain,
    g_sync,
    g_regions,
    g_density,
    g_events,
)
MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_boards,
    g_locked,
    g_arow,
    g_old,
    g_parity,
    g_units,
    g_commit,
    g_probe,
    g_words,
    g_centre,
    g_keepchart,
    g_rank,
    g_keys,
    g_focus,
    g_order,
    g_rbac,
    g_states,
    g_budgets,
    g_tokenuse,
    g_owner,
    g_grows,
    g_crows,
    g_verbatim,
    g_verbatim_src,
    g_reuse,
    g_marked,
    g_frame,
    g_token,
    g_contrast,
    g_untouched,
    g_secref,
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
        "# E12-D04 pins (every unit of both docs): doc, region (heading path #occurrence), "
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
    return [
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


def demote_key(sec: str | None) -> str | None:
    """The key NOTE demotion compares: a numbered `##` section by its number alone, so a pin
    finding under a reworded `##` heading (its old key and its new one) still meets the gate that
    fires in that section (#4682 lens carry 4); an unnumbered section by its whole key."""
    m = SEC_NUM.match(sec or "")
    return m[1] if m else sec


def audit(t: Texts, fetch: Fetch) -> tuple[list[str], list[str], list[str], int]:
    """(FAIL lines, NOTE lines, WARN lines, cites checked). One FAIL line per gate; a pin finding
    in a section another gate already FAILs is demoted to a NOTE line."""
    found: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        found += g_anchor_doc(doc, text, t.values)
        found += g_marker_doc(doc, text, t.values)
        found += g_hex_doc(doc, text)
    for gate in LEXICON_GATES:
        found += gate(t)
    cf, warns, n = cite_findings({"spec": t.spec, "hand": t.hand}, fetch)
    if not merge_base():
        warns.append(f"[G-UNTOUCHED] no merge-base with origin/main; compared with BASE {BASE}")
    found += cf
    for gate in MEASURED_GATES:
        found += gate(t)
    flagged = {(f[2], demote_key(f[3])) for f in found if f[2] is not None}
    pins = pin_findings(t)
    notes = [
        f"NOTE [G-RULED-PIN] {p[1][:150]}" for p in pins if (p[2], demote_key(p[3])) in flagged
    ]
    found += [p for p in pins if (p[2], demote_key(p[3])) not in flagged]
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
    p15: Callable[[str], str] | None = None  # edits the working-tree `15`
    pkm: Callable[[str], str] | None = None  # edits the working-tree `KM`
    patch: Callable[[], Callable[[], None]] | None = None  # moves tool state; returns the undo


def add_board(text: str, _v: Values) -> str:
    rows = [ln for ln in section(text, "0. Status").split("\n") if ln.startswith("| 10 ")]
    if not rows:
        return text
    extra = (
        "| 11 | `E12-D04 / 11 typing-hc` | high-contrast twin of 02 | hc | PENDING: drawn in PR 2 |"
    )
    return text.replace(rows[0], rows[0] + "\n" + extra, 1)


def overrun(text: str, _v: Values) -> str:
    n = text.count("\n")
    return text + "filler\n" * (SPEC_LINE_BUDGET - n + 5)


def drop_row_prefix(head: str, prefix: str) -> Edit:
    """Drop the row of the section `head` whose first cell starts with `prefix`."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        kept = [
            ln
            for ln in block.split("\n")
            if not (ln.startswith("|") and split_row(ln)[0].startswith(prefix))
        ]
        return text.replace(block, "\n".join(kept), 1)

    return run


def km_edit(text: str) -> str:
    return text.replace('"defaultBinding": "1..9"', '"defaultBinding": "1..8"', 1)


D05_ROW = (
    "D05 — sync never carries chart type or bar mode; the fan-out's unit reasoning; the Viewer row"
)
G7_ROW = " **D04-G7** `/market/data-coverage` reports only the last 90 days as built (D02:96)"
NEEDS_BUILD = "`Enter` on a slot that needs a build for the active symbol"
SYMBOL_PAINT = "a symbol's first paint (PROPOSED: the same visible-window target)"

T2_CLAIM = (
    "On a time-mode chart a non-time slot therefore makes no T2 claim for missing prints unless"
    " the session cache holds that symbol's answer: its availability is unknown, and `Enter` on it"
    " commits and falls through to F-BAR-5. "
)
HOLD = (
    "On a non-time chart, `Enter` before the answer sends the probe at once if the rest has not"
    " passed and holds the commit up to the bound, with C-29 shown; the commit then proceeds as"
    " known, or as unknown under F-BAR-5's words (SCR-047; `13`:900–901). "
)
LOT_WORDS = (
    ", or for an unknown lot size S-25, \"ETHFIUSDT's lot size isn't known yet, so Volume bars"
    " can't be built for it. It opens on 1m time bars.\""
)
REASON_NODE = (
    " The reason renders in the preview's mode line, the one `aria-describedby` target, in the DOM"
    " at mount (E09-D09:236)."
)
RECORD_T2 = (
    "the Record button as T2 (full label, `aria-disabled`, focusable; E09-D09:228) in CMP-079 with"
    " the CMP-019 `lock`, the reason beside it"
)
STRIP_ARROWS = (
    " in the strip `↑` / `↓` move as `←` / `→` do, and arrows wrap within the filled slots (APG"
    " radio group; PROPOSED: E08-D05:294 is silent);"
)
S5_TEXT = (
    ' The "→" is `aria-hidden`; the line\'s accessible text reads "Volume 50 BTC becomes Volume'
    ' 1,000 ETH per bar".'
)
A_D05_7 = (
    " `06` has no type-ahead row: A-D05-7 (E08-D05:571–572) is cited, not repeated (RULED BQ-4,"
    " BQ-19)."
)
NO_CONFIRM = " no confirm: every act is reversible view state and a build is cancellable (D02:29);"

# one per ruled sentence (§18.2); the gate named is the one that must trip, alone
MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1",
        "G-PENPOT",
        "BQ-1, BQ-23",
        spec=sub_in(
            "0. Status",
            "page `E12-D04 SCR-041 bar modes`",
            "page `E12-D04 SCR-041 bar modes` (https://design.example/x)",
        ),
    ),
    Mutation(
        "M-2",
        "G-UNBUILT",
        "BQ-1",
        spec=sub_in("0. Status", "**this spec is the implementation contract**", "**the spec**"),
    ),
    Mutation(
        "M-3",
        "G-UNBUILT",
        "BQ-1",
        spec=sub_in("0. Status", " and E10-S02 (#305, the `/` dispatcher rule)", ""),
    ),
    Mutation("M-4", "G-CITE", "BQ-1", spec=sub_in("1.1 What", "(E08-D05:53;", "(E08-D05:99999;")),
    Mutation("M-5", "G-UNTOUCHED", "BQ-1, BQ-4", p15=lambda x: x + "extra\n"),
    Mutation("M-6", "G-UNTOUCHED", "BQ-4", pkm=km_edit),
    Mutation("M-7", "G-BUDGET", "BQ-1", spec=overrun),
    Mutation("M-8", "G-BOARDS", "BQ-1, BQ-23", spec=add_board),
    Mutation("M-9", "G-HEX", "BQ-1, BQ-21", spec=say_in("16. Tokens", "The card is #11151A.")),
    Mutation("M-10", "G-TRACE", "BQ-1", spec=drop_row_prefix("Acceptance-criteria", "AC2 —")),
    Mutation(
        "M-11",
        "G-CLOSE",
        "BQ-1",
        spec=sub_in("20.2 Deviations", "PR 2 completes #240", "PR 2 closes #240"),
    ),
    Mutation(
        "M-12",
        "G-RULED",
        "BQ-9",
        spec=sub_in(
            "The twenty-three questions",
            ", and the probe never delays the commit of a time-mode chart",
            "",
        ),
    ),
    Mutation("M-13", "G-LOCKED", "BQ-2", spec=drop_row("1.3 Locked", D05_ROW)),
    Mutation("M-14", "G-SPLIT", "BQ-3", spec=sub_in("0. Status", " (B19),", ",")),
    Mutation(
        "M-15",
        "G-SPLIT",
        "BQ-3",
        spec=say_in("1.1 What", "This ticket redraws the symbol half as well."),
    ),
    Mutation("M-16", "G-AROW", "BQ-4", hand=drop_row("Table A", "A-2")),
    Mutation(
        "M-17",
        "G-OLD",
        "BQ-4",
        hand=row_edit("Table A", "A-6", 3, to("`radius.xs`, `font.mono`.")),
    ),
    Mutation("M-18", "G-CROWS", "BQ-4, BQ-10", spec=drop_row_prefix("19.1", "D04-C2")),
    Mutation(
        "M-19",
        "G-ROUTE",
        "BQ-5",
        spec=say_in("2.2 Composition", "The switcher also sets the chart type."),
    ),
    Mutation(
        "M-20",
        "G-ROUTE",
        "BQ-5",
        spec=sub_in(
            "2.1 The three",
            "No parameter editor sits inside SCR-041: a size change is SCR-042's editor (D03:48). ",
            "",
        ),
    ),
    Mutation("M-21", "G-PARITY", "BQ-6", spec=row_edit("3.1 The parity", "4", 1, to("`10`"))),
    Mutation(
        "M-22",
        "G-PARITY",
        "BQ-6",
        spec=sub_in("3.1 The parity", 'named "Favourites"', 'named "Interval"'),
    ),
    Mutation(
        "M-23",
        "G-ONELIST",
        "BQ-6",
        spec=say_in("3.2 Units", "SCR-041 keeps its own favourites list."),
    ),
    Mutation(
        "M-24",
        "G-UNITS",
        "BQ-6",
        spec=sub_in("3.2 Units", '"Volume, 50 ETH per bar"', '"Volume, 50 BTC per bar"'),
    ),
    Mutation(
        "M-25",
        "G-MARKED",
        "BQ-6",
        spec=line_edit("### 3.2", " (PROPOSED)", ""),
    ),
    Mutation(
        "M-26",
        "G-OWNER",
        "BQ-12",
        spec=line_edit("### 3.3", f"PROPOSED, {OWNER_PENDING}; ", ""),
    ),
    Mutation(
        "M-27",
        "G-STORE",
        "BQ-12",
        spec=say_in("3.3 The stores", "This ticket opens the contract PR for the store."),
    ),
    Mutation(
        "M-28",
        "G-STORE",
        "BQ-12",
        spec=say_in("3.3 The stores", "A Viewer writes its own favourites."),
    ),
    Mutation("M-29", "G-GROWS", "BQ-4", spec=sub_in("19.2", G7_ROW, "")),
    Mutation(
        "M-30",
        "G-COMMIT",
        "BQ-7",
        spec=row_edit("4. Commit", NEEDS_BUILD, 2, to("commits and starts the build at once")),
    ),
    Mutation(
        "M-31",
        "G-COMMIT",
        "BQ-7",
        spec=prose_at("4. Commit", "Checking a slot starts a build."),
    ),
    Mutation(
        "M-32",
        "G-COMMIT",
        "BQ-7, AC4",
        spec=sub_in("4. Commit", "restores symbol and setting, sends nothing,", "restores both,"),
    ),
    Mutation(
        "M-33",
        "G-CARRY",
        "BQ-8",
        spec=row_edit("5. Carry", "Volume, Delta", 1, to("carried, the same number")),
    ),
    Mutation(
        "M-34",
        "G-CARRY",
        "BQ-8",
        spec=say_in("5. Carry", "The D3-11 swap is applied silently."),
    ),
    Mutation(
        "M-35",
        "G-MARKED",
        "BQ-8",
        spec=sub_in("5. Carry", " (PROPOSED copy), so", ", so"),
    ),
    Mutation(
        "M-36",
        "G-CROWS",
        "BQ-8",
        spec=row_edit("19.1", "D04-C4", 2, to("D3-11 (§5)")),
    ),
    Mutation(
        "M-37",
        "G-OWNER",
        "BQ-9",
        spec=line_edit("## 6.", f" (PROPOSED, {OWNER_PENDING}; RULED BQ-9)", " (RULED BQ-9)"),
    ),
    Mutation(
        "M-38",
        "G-PROBE",
        "BQ-9",
        spec=sub_in("6.2 The probe", "one in flight, cached for the session", "several in flight"),
    ),
    Mutation(
        "M-39",
        "G-PROBE",
        "BQ-9",
        spec=sub_in(
            "6.2 The probe",
            "The probe never delays the commit of a time-mode chart: it does not run for one. ",
            "",
        ),
    ),
    Mutation(
        "M-40",
        "G-PROBE",
        "BQ-9",
        spec=with_values(
            lambda v: sub_in(
                "6.2 The probe", "is bounded at " + av(v, "RULE:probe.s") + " s", "waits"
            )
        ),
    ),
    Mutation(
        "M-41",
        "G-FALLBACK",
        "BQ-9",
        spec=sub_in(
            "6.3 The fallback",
            "The panel's last time interval before it entered the non-time mode; else ",
            "",
        ),
    ),
    Mutation("M-42", "G-FALLBACK", "BQ-9", spec=sub_in("6.3 The fallback", " Never a build.", "")),
    Mutation(
        "M-43",
        "G-FALLBACK",
        "BQ-9",
        spec=sub_in("6.4 The words", "does not restore the mode", "restores the mode"),
    ),
    Mutation(
        "M-44",
        "G-WORDS",
        "BQ-9",
        spec=sub_in("6.4 The words", "so Volume bars can't be built for it.", "so it falls back."),
    ),
    Mutation(
        "M-45",
        "G-WORDS",
        "BQ-9",
        spec=sub_in("6.4 The words", "; J5 stays for deep links and restored panes", ""),
    ),
    Mutation("M-46", "G-CROWS", "BQ-9", spec=row_edit("19.1", "D04-C5", 3, to("—"))),
    Mutation(
        "M-47",
        "G-VERBATIM",
        "BQ-9",
        spec=sub_in("6.2 The probe", '"Checking recorded prints…"', '"Checking prints…"'),
    ),
    Mutation(
        "M-48",
        "G-RETAIN",
        "BQ-10, AC3",
        spec=say_in("7.1 Frame by frame", "During a switch the pane shows a skeleton."),
    ),
    Mutation(
        "M-49",
        "G-CENTRE",
        "BQ-10",
        spec=sub_in("7.2 Centre", "a paused chart keeps its visible time centre and ", ""),
    ),
    Mutation(
        "M-50",
        "G-SUBS",
        "BQ-10",
        spec=say_in("7.2 Centre", "Then `unsub` the old topics first."),
    ),
    Mutation(
        "M-51",
        "G-SUBS",
        "BQ-10",
        hand=row_edit(
            "Table A",
            "A-2",
            4,
            to("Opens fast; switching symbol swaps subscriptions with a single WS frame."),
        ),
    ),
    Mutation(
        "M-52",
        "G-KEEPCHART",
        "BQ-10",
        spec=sub_in("7.2 Centre", "D02:323–327), never SCR-048.", "D02:323–327), then SCR-048."),
    ),
    Mutation(
        "M-53",
        "G-RANK",
        "BQ-11",
        spec=sub_in("8.1 Search", " The strip's slots never enter the symbol ranking.", ""),
    ),
    Mutation(
        "M-54",
        "G-PREVIEW",
        "BQ-13",
        spec=say_in(
            "8.2 The preview", "The preview fetches the ticker for the highlighted symbol."
        ),
    ),
    Mutation(
        "M-55",
        "G-PREVIEW",
        "BQ-13",
        spec=sub_in("8.2 The preview", "has no funding rate", "has a funding rate"),
    ),
    Mutation(
        "M-56",
        "G-KEYS",
        "BQ-14",
        spec=sub_in("9.1 Keys", "it shadows `ticket.qty_preset`, ", ""),
    ),
    Mutation(
        "M-57",
        "G-KEYS",
        "BQ-14",
        spec=sub_in("9.1 Keys", "`rules.move_up` in Rules, never co-active", "free in `KM`"),
    ),
    Mutation(
        "M-58",
        "G-KEYS",
        "BQ-14",
        spec=sub_in(
            "9.1 Keys", "next filled favourite slot, no wrap", "next filled favourite slot"
        ),
    ),
    Mutation(
        "M-59",
        "G-KEYS",
        "BQ-14",
        spec=sub_in("9.1 Keys", "is not adopted in R1", "is adopted in R1"),
    ),
    Mutation(
        "M-60",
        "G-KEYS",
        "BQ-14",
        spec=say_in("9.1 Keys", "The ladder may also use `Alt+1..9`."),
    ),
    Mutation(
        "M-61",
        "G-MARKED",
        "BQ-14",
        spec=sub_in("9.1 Keys", "no wrap (PROPOSED; `05`:55", "no wrap (`05`:55"),
    ),
    Mutation(
        "M-62",
        "G-GROWS",
        "BQ-14",
        spec=sub_in(
            "19.2", "confirms the ladder on it, not fixed here.", "confirms the ladder on it."
        ),
    ),
    Mutation(
        "M-63",
        "G-REBIND",
        "BQ-15",
        spec=say_in("9.2 Rebinding", "Each slot has its own key binding in SCR-113."),
    ),
    Mutation(
        "M-64",
        "G-REBIND",
        "BQ-15, T a11y",
        spec=sub_in("9.2 Rebinding", "Every slot is reachable without its key:", "Slots:"),
    ),
    Mutation(
        "M-65",
        "G-EVENTS",
        "BQ-15, BQ-22",
        spec=say_in("17. Analytics", "A store write is audited."),
    ),
    Mutation(
        "M-66",
        "G-ORDER",
        "BQ-16",
        spec=sub_in("10.2 Order", "input → strip → More…", "input → More… → strip"),
    ),
    Mutation(
        "M-67",
        "G-CONTAIN",
        "BQ-16",
        spec=say_in("10.2 Order", "Arrows cross from the listbox into the strip."),
    ),
    Mutation(
        "M-68",
        "G-FOCUS",
        "BQ-16, AC4",
        spec=sub_in("10.3 Close", " (D02 D-11, D02:35), never to `body`;", " (D02 D-11, D02:35);"),
    ),
    Mutation(
        "M-69",
        "G-SYNC",
        "BQ-17",
        spec=say_in("11. Sync", "The bar mode follows the group."),
    ),
    Mutation("M-70", "G-SYNC", "BQ-17", spec=sub_in("11. Sync", "; it joins no group", "")),
    Mutation(
        "M-71",
        "G-MARKED",
        "BQ-17",
        spec=sub_in("11. Sync", "(**PROPOSED** for SCR-041, ", "(for SCR-041, "),
    ),
    Mutation(
        "M-72",
        "G-RBAC",
        "BQ-18",
        spec=row_edit(
            "12. Roles",
            "Manager, Viewer",
            1,
            to('`rbac.owner_only` "Only the owner can change recording." (E09-D09:73)'),
        ),
    ),
    Mutation(
        "M-73",
        "G-RBAC",
        "BQ-18, T Sec",
        spec=sub_in("12. Roles", "Hiding the button is not the control: the", "The"),
    ),
    Mutation(
        "M-74",
        "G-RBAC",
        "BQ-18",
        spec=sub_in("12. Roles", " first on Record (E09-D09:95)", " on Record (E09-D09:95)"),
    ),
    Mutation(
        "M-75",
        "G-STATES",
        "BQ-19, AC5",
        spec=sub_in("13.1 States", "the no-match deck with **Clear search**", "the no-match deck"),
    ),
    Mutation(
        "M-76",
        "G-VERBATIM",
        "BQ-19, AC5",
        spec=sub_in(
            "13.1 States", "\"No USDT perpetual matches 'xyzzy'.\"", "\"No match for 'xyzzy'.\""
        ),
    ),
    Mutation(
        "M-77",
        "G-BUDGETS",
        "BQ-19",
        spec=drop_row_prefix("13.2 Budgets", "keystroke → painted list"),
    ),
    Mutation(
        "M-78",
        "G-BUDGETS",
        "BQ-19",
        spec=row_edit("13.2 Budgets", SYMBOL_PAINT, 0, to("a symbol's first paint")),
    ),
    Mutation(
        "M-79",
        "G-REUSE",
        "BQ-19, R-7",
        spec=row_edit(
            "15. Copy deck",
            "S-11",
            2,
            to("No USDT perpetual matches 'xyzzy'. · v1 supports linear perpetuals only."),
        ),
    ),
    Mutation(
        "M-80",
        "G-REGIONS",
        "BQ-20",
        spec=say_in("14. Accessibility", "The mode line is announced on each highlight change."),
    ),
    Mutation(
        "M-81",
        "G-DENSITY",
        "BQ-21",
        spec=say_in("16. Tokens", "Comfortable is the hero for this popover."),
    ),
    Mutation(
        "M-82",
        "G-TOKENUSE",
        "BQ-21",
        spec=sub_in("16. Tokens", ", never on the checked fill", ""),
    ),
    Mutation(
        "M-83",
        "G-CONTRAST",
        "BQ-21",
        spec=drop_row("16. Tokens", "`focus.ring` on `action.selected`"),
    ),
    Mutation(
        "M-84",
        "G-TOKEN",
        "BQ-21",
        spec=say_in("16. Tokens", "Errors use `color.text.error`."),
    ),
    Mutation(
        "M-85",
        "G-EVENTS",
        "BQ-22",
        spec=say_in("17. Analytics", "`chart.bar_mode_fallback` also carries the symbol."),
    ),
    Mutation(
        "M-86",
        "G-EVENTS",
        "BQ-22",
        spec=sub_in("17. Analytics", "- **No audit record**, stated on the frames: view", "- View"),
    ),
    Mutation("M-87", "G-FRAME", "BQ-23", spec=reg("idle/preview · dark", "Board", to("11"))),
    Mutation(
        "M-88",
        "G-FRAME",
        "BQ-23",
        spec=reg("idle/preview · dark", "Components", to("CMP-017, CMP-999")),
    ),
    Mutation("M-89", "G-FRAME", "BQ-23", spec=reg("idle/preview · dark", "Copy", to("S-99"))),
    Mutation(
        "M-90",
        "G-FRAME",
        "BQ-23",
        spec=reg("idle/preview · dark", "Tokens", to("`color.preview.line`")),
    ),
    Mutation("M-91", "G-FRAME", "BQ-23", spec=reg("idle/preview · dark", "Status", to("PENDING"))),
    Mutation(
        "M-92",
        "G-FRAME",
        "BQ-23, BQ-9",
        spec=reg("fallback/strip-notice · dark", "Components", to("CMP-028, CMP-001")),
    ),
    Mutation(
        "M-93",
        "G-FRAME",
        "BQ-23, AC2",
        spec=drop_row(FRAME_HEAD, "`typing/unavailable · dark`"),
    ),
    Mutation(
        "M-94",
        "G-BOARDS",
        "BQ-23",
        spec=sub_in(
            "0. Status",
            "Every board is a canvas of frames, each frame a",
            "Every board is a",
        ),
    ),
    Mutation(
        "M-95",
        "G-PROBE",
        "BQ-9",
        spec=sub_in("6.2 The probe", T2_CLAIM, ""),
    ),
    Mutation("M-96", "G-PROBE", "BQ-9", spec=sub_in("6.2 The probe", HOLD, "")),
    Mutation("M-97", "G-WORDS", "BQ-9, T Tech", spec=sub_in("6.4 The words", LOT_WORDS, "")),
    Mutation(
        "M-98",
        "G-T2",
        "BQ-6, BQ-20",
        spec=say_in("3.2 Units", "Arrowing onto a T2 slot checks it."),
    ),
    Mutation("M-99", "G-T2", "BQ-20", spec=sub_in("3.2 Units", REASON_NODE, "")),
    Mutation(
        "M-100",
        "G-REGIONS",
        "BQ-20",
        spec=sub_in(
            "14. Accessibility",
            "skips its switch-result line for that commit",
            "also speaks its switch-result line",
        ),
    ),
    Mutation(
        "M-101",
        "G-REGIONS",
        "BQ-19, BQ-20",
        spec=sub_in("14. Accessibility", ' with `role="alert"`', ""),
    ),
    Mutation(
        "M-102",
        "G-RBAC",
        "BQ-18",
        spec=sub_in(
            "12. Roles", RECORD_T2, "CMP-079 with the CMP-019 `lock`, beside where it would be"
        ),
    ),
    Mutation(
        "M-103",
        "G-ORDER",
        "BQ-16, BQ-18",
        spec=sub_in("10.2 Order", "Record (when shown, T2 for others)", "Record (owner)"),
    ),
    Mutation("M-104", "G-CONTAIN", "BQ-16", spec=sub_in("10.2 Order", STRIP_ARROWS, "")),
    Mutation("M-105", "G-CARRY", "BQ-8, BQ-20", spec=sub_in("5. Carry", S5_TEXT, "")),
    Mutation("M-106", "G-BUDGETS", "BQ-4, BQ-19", spec=sub_in("17. Analytics", A_D05_7, "")),
    Mutation(
        "M-107",
        "G-CROWS",
        "BQ-12",
        spec=row_edit("19.1", "D04-C22", 1, lambda c: c.replace("D02:481 routes", "D02 routes")),
    ),
    Mutation("M-108", "G-PARITY", "BQ-6", spec=row_edit("3.1 The parity", "3", 4, to("D02:182"))),
    Mutation(
        "M-109",
        "G-EVENTS",
        "BQ-22",
        spec=sub_in("17. Analytics", ", proposed for `chart.bar_mode_changed` (D04-G6)", ""),
    ),
    Mutation("M-110", "G-COMMIT", "BQ-7", spec=sub_in("1.4 Rules", NO_CONFIRM, "")),
    Mutation(
        "M-111",
        "G-WORDS",
        "BQ-9",
        spec=sub_in(
            "6.4 The words", "S-7 and S-26 offer only `Dismiss`", "S-7 and S-26 offer `Retry`"
        ),
    ),
    Mutation(
        "M-112",
        "G-BOARDS",
        "BQ-23",
        spec=sub_in("20.2 Deviations", "a refinement of BQ-23 within lever 4", "an addition"),
    ),
    Mutation("M-113", "G-LOCKED", "BQ-2", spec=sub_in("1.3 Locked", "| D01:39 ", "| D01:49 ")),
    Mutation("M-114", "G-MARKED", "BQ-18", spec=sub_in("12. Roles", ", PROPOSED in D05)", ")")),
    # the tool's own: the comment strip, the anchors, the allow-list, the tool-state gates
    Mutation(
        "X-1",
        "G-RULED",
        "RULED cites only 6430117981 (+ the BQ list)",
        hand=line_edit("Components:", f"comment {RULING_ID}", "comment 6430117999"),
    ),
    Mutation(
        "X-2",
        "G-ANCHOR",
        "BQ-1: an anchored value differs",
        spec=with_values(
            lambda v: sub_in("13.2 Budgets", av(v, "BUDGET:open"), "90<!--=BUDGET:open-->")
        ),
    ),
    Mutation(
        "X-3",
        "G-ANCHOR",
        "BQ-1: a figure typed by hand",
        spec=say_in("8.2 The preview", "The line is 7 px from the edge."),
    ),
    Mutation(
        "X-4",
        "G-MARKER",
        "BQ-1: a hidden comment",
        spec=sub_in("1.4 Rules", "- **R-2", "- <!-- the strip builds on check -->**R-2"),
    ),
    Mutation(
        "X-5",
        "G-MARKER",
        "BQ-1: an unclosed comment",
        spec=say_in("21. Summary", "<!-- an unclosed note"),
    ),
    Mutation(
        "X-6",
        "G-ANCHOR",
        "BQ-1: a placeholder left unfilled",
        spec=say_in("17. Analytics", "The cap is {{COUNT:pairs}}."),
    ),
    Mutation(
        "X-7",
        "G-CONTRAST",
        "BQ-21: marks clear the bar",
        patch=pushed(MARK_MIN_OVERRIDE, Decimal(20)),
    ),
    Mutation(
        "X-8",
        "G-CHARSET",
        "#241 lens: a superscript cite folds to ASCII in the pins",
        spec=sub_in("6.1 Unavailable", "(D3-4, D03:49)", "(D3-4, D03:⁴⁹)"),
    ),
    Mutation(
        "X-9",
        "G-CHARSET",
        "#241 lens: a full-width digit in a cite",
        spec=sub_in("1.4 Rules", "(D3-3, D03:48)", "(D3-3, D03:４８)"),
    ),
    Mutation(
        "X-10",
        "G-CHARSET",
        "#241 lens: a no-break space",
        spec=sub_in("1.2 Method", "Desk work at the base", "Desk work at\u00a0the base"),
    ),
    Mutation(
        "X-11",
        "G-CHARSET",
        "#241 lens: a CR line ending",
        spec=sub_in("21. Summary", "(at most ten lines)\n", "(at most ten lines)\r\n"),
    ),
    Mutation(
        "X-12",
        "G-CHARSET",
        "#241 lens: a trailing two-space hard break",
        spec=in_lines(
            "1.2 Method", lambda ls: [x + "  " if x.startswith("Desk work") else x for x in ls]
        ),
    ),
    Mutation(
        "X-13",
        "G-ANCHOR",
        "#241 lens: a digit typed against an anchored value's left edge",
        spec=with_values(
            lambda v: sub_in(
                "13.2 Budgets", "≤ " + av(v, "BUDGET:open"), "≤ 1" + av(v, "BUDGET:open")
            )
        ),
    ),
    Mutation(
        "X-14",
        "G-CLOSE",
        "#241 lens: a closing keyword in the hand-off",
        hand=say_in("§E Owner", "This fixes #240."),
    ),
    # paraphrases of ruled sentences, in table cells and with synonyms (the #241 lens lesson)
    Mutation(
        "X-15",
        "G-RETAIN",
        "BQ-10 paraphrase in a cell: the pane goes blank",
        spec=row_edit(
            "7.1 Frame by frame", "first data", 1, to("the pane clears the frame, then paints")
        ),
    ),
    Mutation(
        "X-16",
        "G-SUBS",
        "BQ-10 paraphrase: unsubscribe at once",
        spec=say_in("7.2 Centre", "The old topics are dropped: `unsub` them at once."),
    ),
    Mutation(
        "X-17",
        "G-COMMIT",
        "BQ-7 paraphrase in a cell: arrowing commits",
        spec=sub_in(
            "4. Commit", "check a slot without committing", "arrowing to a slot commits it"
        ),
    ),
    Mutation(
        "X-18",
        "G-SYNC",
        "BQ-17 paraphrase: the interval propagates",
        spec=say_in("11. Sync", "The interval propagates to the group."),
    ),
    Mutation(
        "X-19",
        "G-ONELIST",
        "BQ-6 paraphrase: a separate ladder",
        spec=say_in("3.1 The parity", "The strip stores a separate ladder."),
    ),
    Mutation(
        "X-20",
        "G-REBIND",
        "BQ-15 paraphrase: nine commands",
        spec=say_in("9.2 Rebinding", "SCR-113 lists nine commands for the ladder."),
    ),
    # the #240 lens: what NFKC or `str.split()` used to hide from the pins
    Mutation(
        "X-21",
        "G-CHARSET",
        "#240 lens: U+2026 spelled as three dots in quoted copy",
        spec=sub_in("12. Roles", "Record this symbol…", "Record this symbol..."),
    ),
    Mutation(
        "X-22",
        "G-CHARSET",
        "#240 lens: U+2028 added to a whitespace run",
        spec=sub_in("7.1 Frame by frame", "bootstrap only (OQ-16)", "bootstrap only \u2028(OQ-16)"),
    ),
    Mutation(
        "X-23",
        "G-CHARSET",
        "#240 lens: U+001F for a space",
        spec=sub_in("7.1 Frame by frame", "bootstrap only (OQ-16)", "bootstrap only\x1f(OQ-16)"),
    ),
    Mutation(
        "X-24",
        "G-CHARSET",
        "#240 lens: U+1680 for a space in the hand-off",
        hand=sub_in("§E Owner", "Record `approved` on #240", "Record\u1680`approved` on #240"),
    ),
    # the #4682 lens carry 1: ten ruled classes the pins alone stopped, each now a named gate
    Mutation(
        "X-25",
        "G-ROUTE",
        "#4682 lens: a chart-type chip row in SCR-041",
        spec=say_in(
            "2.2 Composition", "A row of chart-type chips (Candles, Hollow, Line) sits under it."
        ),
    ),
    Mutation(
        "X-26",
        "G-PREVIEW",
        "#4682 lens: a funding rate in the preview",
        spec=sub_in(
            "8.2 The preview",
            'funding as the interval, "funding every 8 h", from',
            "funding as the current rate per 8 h, from",
        ),
    ),
    Mutation(
        "X-27",
        "G-EVENTS",
        "#4682 lens: the query on `symbol.searched`",
        spec=row_edit(
            "17. Analytics",
            "`symbol.searched`, `symbol.search_result_opened`",
            1,
            lambda c: c.replace('`surface: "scr-041"`', '`surface: "scr-041"`, `q`'),
        ),
    ),
    Mutation(
        "X-28",
        "G-BOARDS",
        "#4682 lens: an extra light twin",
        spec=in_lines(
            FRAME_HEAD,
            lambda ls: [
                (
                    (
                        "| `typing/carried · light` | 09 | light | as 02 | CMP-048, CMP-213 | S-5 |"
                        " `color.text.secondary` | drawn |"
                    )
                    if x.startswith("| `typing/carried · dark`")
                    else x
                )
                for x in ls
            ],
        ),
    ),
    Mutation(
        "X-29",
        "G-OWNER",
        "#4682 lens: owner approval granted on BQ-9",
        spec=say_in("6.4 The words", "The owner approved BQ-9's fallback on #2701."),
    ),
    Mutation(
        "X-30",
        "G-OWNER",
        "#4682 lens: owner approval granted on BQ-12",
        spec=sub_in(
            "3.3 The stores",
            "- **Until it lands:**",
            "- **Owner-approved (BQ-12). Until it lands:**",
        ),
    ),
    Mutation(
        "X-31",
        "G-FALLBACK",
        "#4682 lens: an auto-return of the mode",
        spec=sub_in(
            "6.4 The words",
            "does not restore the mode: that would be an unseen build (R-2).",
            "reverts the chart to Volume on its own.",
        ),
    ),
    Mutation(
        "X-32",
        "G-PROBE",
        "#4682 lens: a time-mode no-recorded-prints claim",
        spec=say_in(
            "3.2 Units",
            "On a time-mode chart a Volume slot for a symbol with no recorded prints is T2.",
        ),
    ),
    Mutation(
        "X-33",
        "G-SUBS",
        "#4682 lens: `unsub` before `sub`",
        spec=say_in(
            "7.2 Centre", "The client drops the old topics, then subscribes to the new ones."
        ),
    ),
    Mutation(
        "X-34",
        "G-REGIONS",
        "#4682 lens: a per-letter announcement",
        spec=say_in("14. Accessibility", "Each typed character is voiced by the region."),
    ),
    # the #4682 lens carries 3 and 4, and the PR 2 board-script ruling (a)
    Mutation(
        "X-35",
        "G-RULED-PIN",
        "#4682 lens: a reworded heading is one FAIL (the gates still read its section)",
        spec=sub_in("6.2 The probe", "### 6.2 The probe", "### 6.2 The coverage probe"),
    ),
    Mutation(
        "X-36",
        "G-SUBS",
        "#4682 lens: a gate firing under a reworded `##` heading demotes its pins to NOTE",
        spec=lambda text, v: sub_in(
            "7.2 Centre", "- **Failure:** a", "- **Failure:** `unsub` the old topics at once; a"
        )(text.replace("## 7. Switching behaviour", "## 7. Switch behaviour", 1), v),
    ),
    Mutation(
        "X-37",
        "G-SECREF",
        "#4682 lens: a dangling § reference",
        spec=sub_in("Acceptance-criteria", "| §14, §9.2 ", "| §14, §9.3 "),
    ),
    Mutation(
        "X-38",
        "G-FRAME",
        "PR 2 ruling: the recorded `idle/preview` frame with S-10's words",
        spec=reg("idle/preview · dark", "Copy", to("S-10")),
    ),
    Mutation(
        "X-39",
        "G-UNTOUCHED",
        "an `E12-D04-NN` PNG no §0 board row names (committed or untracked)",
        patch=pushed(EXTRA_PATHS, "docs/design/E12/img/E12-D04-11-extra.png"),
    ),
    Mutation(
        "X-40",
        "G-OWNER",
        "owner clearance, final",
        spec=say_in("6.4 The words", "The owner cleared BQ-9 and it is final."),
    ),
    Mutation(
        "X-41",
        "G-OWNER",
        "owner accepted the stores",
        spec=say_in("6.4 The words", "The owner has accepted the stores (BQ-12)."),
    ),
    Mutation(
        "X-42",
        "G-OWNER",
        "owner signed the fallback off",
        spec=say_in("6.4 The words", "The owner signed BQ-9's fallback off."),
    ),
    Mutation(
        "X-43",
        "G-OWNER",
        "owner accepted on #2701",
        spec=say_in("6.4 The words", "On #2701 the owner accepted the fallback."),
    ),
    Mutation(
        "X-44",
        "G-FALLBACK",
        "a return to Volume when recorded again",
        spec=say_in(
            "6.4 The words", "When the symbol is recorded again, the chart returns to Volume."
        ),
    ),
    Mutation(
        "X-45",
        "G-FALLBACK",
        "Volume reinstated unasked",
        spec=say_in("6.4 The words", "The chart reinstates Volume bars without the user asking."),
    ),
    Mutation(
        "X-46",
        "G-PROBE",
        "a slot unavailable straight away",
        spec=say_in(
            "3.2 Units",
            "On a 1m chart, a Volume slot for such a symbol reads as unavailable straight away.",
        ),
    ),
    Mutation(
        "X-47",
        "G-PROBE",
        "a slot greyed immediately",
        spec=say_in(
            "3.2 Units",
            "A Range slot is greyed immediately when the symbol lacks any trade history.",
        ),
    ),
    Mutation(
        "X-48",
        "G-SECREF",
        "a hand-off letter that is no heading",
        spec=say_in("6.4 The words", "See hand-off §F."),
    ),
    # one per pin class (G-RULED-PIN only)
    Mutation(
        "P-1",
        "G-RULED-PIN",
        "a frame row changed",
        spec=reg("idle/redlines · dark", "State", to("widths, rows, targets, the ring (sic)")),
    ),
    Mutation(
        "P-2",
        "G-RULED-PIN",
        "a frame row moved",
        spec=in_lines(FRAME_HEAD, swap_rows("`switch/pending · dark`", "`switch/loading · dark`")),
    ),
    Mutation(
        "P-3", "G-RULED-PIN", "a sentence added to a paragraph", spec=say_in("1.2 Method", "Ok.")
    ),
    Mutation(
        "P-4",
        "G-RULED-PIN",
        "a bullet duplicated",
        spec=squeezed(in_lines("1.4 Rules", dup_line("- **R-7")), 2),
    ),
    Mutation(
        "P-5", "G-RULED-PIN", "a sentence deleted", spec=in_lines("1.4 Rules", drop_line("- **R-5"))
    ),
    Mutation(
        "P-6",
        "G-RULED-PIN",
        "a new heading",
        spec=squeezed(prose_at("10.1 Open", "### 10.4 Notes\n\nSee §10.1."), 6),
    ),
    Mutation("P-7", "G-RULED-PIN", "blank lines squeezed", spec=squeezed(None, 3)),
    Mutation(
        "P-8",
        "G-RULED-PIN",
        "a hand-off row changed",
        hand=row_edit("§D Storybook", "CMP-022 Kbd", 1, appended(" (cited)")),
    ),
    Mutation(
        "P-9",
        "G-RULED-PIN",
        "a bullet turned into prose",
        spec=line_edit("- **R-7", "- **R-7", "**R-7"),
    ),
    Mutation(
        "P-10", "G-RULED-PIN", "a line indented", spec=in_lines("1.4 Rules", indented("- **R-5", 2))
    ),
    Mutation("P-11", "G-RULED-PIN", "a duplicated section", spec=squeezed(shadow("10.1 Open"), 6)),
    # probes that must trip nothing
    Mutation(
        "N-1",
        "",
        "Prettier re-pads a table row",
        spec=in_lines(
            FRAME_HEAD,
            lambda ls: [
                re.sub(r" {2,}", " ", x) if "`idle/preview · dark`" in x else x for x in ls
            ],
        ),
    ),
)


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def plan_paths() -> tuple[tuple[str, Path], ...]:
    """The working-tree files G-UNTOUCHED compares: UNTOUCHED (`05`, `14`, `15`, `16`, `22`) and
    UNTOUCHED_DOCS (`KM`, `RK`)."""
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
    lines += [f"  baseline FAIL {x[:160]}" for x in base_fails]
    ok = not base_fails
    probe = fence_pin_probe()
    if pin_norm("More…") == pin_norm("More..."):
        probe.append("fold probe: the pins fold U+2026 into three dots")
    lines.append(f"  fence probe: {'ok' if not probe else 'FAIL'}")
    lines += [f"    {x}" for x in probe]
    ok = ok and not probe
    listed = [r[0] for r in table_rows(section(spec_f, MUTATION_HEAD)) if r[0].startswith("M-")]
    built = [mu.mid for mu in MUTATIONS if mu.mid.startswith("M-")]
    if listed != built:
        ok = False
        lines.append(
            f"  18.2 lists {len(listed)} M-rows, the tool builds {len(built)}: they differ"
        )
    pristine = digest_texts(spec_f, hand_f, *(x for _n, x in plans))
    for mu in MUTATIONS:
        s = mu.spec(spec_f, values) if mu.spec else spec_f
        h = mu.hand(hand_f, values) if mu.hand else hand_f
        p15, pkm = dict(plans)["15"], dict(plans)["KM"]
        q = mu.p15(p15) if mu.p15 else p15
        q2 = mu.pkm(pkm) if mu.pkm else pkm
        if (s, h, q, q2) == (spec_f, hand_f, p15, pkm) and mu.patch is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        edited = {"15": q, "KM": q2}
        new_plans = tuple((nn, edited.get(nn, x)) for nn, x in plans)
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
        first = (named or new or ["nothing new"])[0][:110]
        lines.append(
            f"  {mu.mid} [{mu.gate or 'none'}] {'ok' if hit else 'MISSED'} ({len(new)} new"
            f"{'' if restored else ', NOT RESTORED'}) - {first}"
        )
        if not hit:
            lines += [f"      new: {x[:200]}" for x in new]
    return ok, lines


# ---------------------------------------------------------------------------- main


def write_text(path: Path, text: str) -> None:
    """Every writer opens its file with newline="\\n"."""
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def ascii_only(line: str) -> str:
    """The self-test prints ASCII only, so a cp1252 console never fails on a character."""
    return line.encode("ascii", "backslashreplace").decode("ascii")


def main(argv: list[str]) -> int:
    # the reports print `→`, `§` and `…`: a cp1252 (or any non-UTF-8) console must not crash them,
    # and `python3 -I` ignores PYTHONIOENCODING, so the tool sets the stream itself (as E12-D05's)
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="E12-D04 switcher audit (module docstring)")
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
        print("\n".join(ascii_only(x) for x in lines))
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
        print(f"## E12-D04 audit of {shown} (+ the hand-off) at base {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(notes))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK - every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(notes)} NOTE, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
