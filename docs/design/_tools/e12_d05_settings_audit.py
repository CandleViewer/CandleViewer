#!/usr/bin/env python3
"""E12-D05 (#241) audit: SCR-031's General tab (spec + hand-off).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base `15ba8bbc1b` (`git show`): the token JSON (`themes.json` layering:
dark = primitives + semantic-dark, light = + semantic-light, hc = + semantic-hc), the plan texts
`05`, `11`, `14`, `15`, `16`, `22`, the merged design docs the spec cites, `bars/limits.py` and
`bars/spec.py` (as syntax trees, never imported) and the recorded instrument fixture; then this
ticket's spec and hand-off from the working tree, and the working-tree `14`, `15`, `16`, `22` and
E12-D02.md (which must equal the fork point; no other path may differ from it but this ticket's).

1. **Values (RULED 6426302306, BQ-1).** Every `{{KIND:key}}` outside a code span is COMPUTED:
   LIM (the parameter bounds of `LIM`:62-74 and `BSPEC`:36, evaluated from the syntax tree),
   D03 (the first-use defaults of D03's per-mode table and the estimate delay of D03:245),
   FIX (BTCUSDT's tick, qty step and volume floor from the instrument fixture, minimal exact form),
   BUDGET (the window, the type-switch and build budgets, the target and row sizes, the parameter
   length, parsed from the cited lines), COUNT (boards, twins, frames, types, modes, pairs, the line
   budgets), HEX (every bound token in dark / light / hc) and CONTRAST (WCAG 2.x, truncated to two
   decimals). `--fill` writes `VALUE<!--=KIND:key-->`; `--check` re-derives every anchored value and
   FAILs on a difference, a `{{` left outside a code span, a hand-typed figure with a unit or a
   hand-typed hex.
2. **The comment strip.** One pattern over the whole text, `re.DOTALL`: `<!--` closes at `-->` or
   `--!>`, `<!-->` and `<!--->` close at once, and an unclosed comment runs to the end. Every
   comment must be a value anchor the tool computes (G-MARKER); the lexicon gates read rendered text
   only.
3. **Cites.** Every `NN`:line, `D0n`/`D0nh`/`SEED`/`LIM`/`BSPEC`/`E05-FO`:line and `Exx-Dyy`:line
   cite is read at the base (FAIL when the line is gone or blank; WARN when it drifted at
   `origin/main`), and the load-bearing fragments in CITED must sit on the cited line.
4. **Gates.** Lexicon gates first (each reads rows and prose after the comment strip, NFKC, markup
   dropped, dashes to spaces and lower case; a claim is read per clause; a negation covers its own
   term within five words and a list coordinated after it; quoted copy, §15.2's mutation rows and
   the hand-off's Old cells are not claims), then the measured gates (the D03 parity matrix, the
   chart-type set, the frame register column by column, the contrast pairs, the boards, the budgets,
   G-UNTOUCHED against `git merge-base HEAD origin/main`), then the pins. Each gate reports one FAIL
   line.
5. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over EVERY unit of both docs, in
   RULED_PIN_TXT (`e12_d05_ruled_pins.txt`): each heading, table row (by its lead cell), rule line,
   prose sentence (`s<k>`) and fenced block, by doc, region (heading path plus occurrence `#n`),
   location and exact text (NFKC, whitespace collapsed). Anchored values are pinned with their
   values cut out (G-ANCHOR re-derives them). Each region pins its line shape (line-shape tags: `.`
   blank, `h` heading, `t` row, `r` rule, `b` bullet, `n` numbered item, `p` prose, `f` fence; a
   prose, bullet or numbered tag carries its sentence count, the line-form tag; `>n` an n-column
   indent). A unit changed, moved, duplicated, deleted or added FAILs by location. `--repin-ruled`
   is the only writer (it refuses while a placeholder is unfilled); `--check` writes nothing. Pins
   fold NFKC, so G-CHARSET FAILs any compatibility character but `…`, any CR and any trailing
   whitespace: a change the pins cannot see is not allowed in. NOTE demotion: when a lexicon or
   measured gate already FAILs a section, that section's pin findings print as NOTE lines, so one
   wrong form yields one FAIL.
6. **--self-test** (alias `--selftest`) applies every §15.2 mutation M-1 … M-88 in memory, plus the
   tool's own X-n (X-16 … X-21: PR #4669's six paraphrases, each FAILed by its own gate) and P-n
   (one per pin class) and the N-n probes (which must trip nothing), with the values frozen at the
   filled baseline; each must add exactly one FAIL, from the gate it names, and every text is
   restored byte-identically (sha256 in memory and on disk).

Usage (from the repo root):
  python3 -I docs/design/_tools/e12_d05_settings_audit.py --check [SPEC] [--handoff F] \
      [--json] [--fill]
  python3 -I docs/design/_tools/e12_d05_settings_audit.py --self-test
  python3 -I docs/design/_tools/e12_d05_settings_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import ast
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
BASE = "15ba8bbc1b"  # every cite was read here (the spec's Inputs line)
HEAD = "origin/main"  # drift is reported against this ref (WARN, never FAIL)
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E12/E12-D05.md"
HAND_REL = "docs/design/E12/E12-D05-handoff.md"
RULED_PIN_TXT = "docs/design/_tools/e12_d05_ruled_pins.txt"
DS_SRC_REL = "packages/ui/tokens"
INSTR_REL = "packages/fixtures/bybit/2026-10-05/rest/instruments_after.json"
UNTOUCHED = ("14", "15", "16", "22")  # RULED BQ-3: never edited by this ticket
# merged design docs this ticket reaches through a hand-off row: also never edited (A-8 targets D02)
UNTOUCHED_DOCS = ("D02",)
# the only paths this ticket may add or change against the fork point
OWN_PATHS = (
    "docs/design/E12/E12-D05.md",
    "docs/design/E12/E12-D05-handoff.md",
    "docs/design/_tools/e12_d05_settings_audit.py",
    "docs/design/_tools/e12_d05_ruled_pins.txt",
)
OWN_IMG = re.compile(r"docs/design/E12/img/E12-D05-\d{2}-[a-z0-9-]+\.png")
# the boards PR's committed board script set (`sheets/e12-d05/`) and the four shared helpers it
# runs (`sheets/common/`), plus the folder's regenerated MANIFEST.sha256: never read by this tool
OWN_SHEETS = re.compile(
    r"docs/design/_tools/sheets/(?:e12-d05/[A-Za-z0-9._-]+"
    r"|common/(?:listexp|openpage|pull/export_to_storage|pull/read_chunk)\.js\.txt"
    r"|MANIFEST\.sha256)"
)
CITE_FILES: dict[str, str] = {
    "D01": "docs/design/E12/E12-D01.md",
    "D02": "docs/design/E12/E12-D02.md",
    "D03": "docs/design/E12/E12-D03.md",
    "D06": "docs/design/E12/E12-D06.md",
    "D03h": "docs/design/E12/E12-D03-handoff.md",
    "D06h": "docs/design/E12/E12-D06-handoff.md",
    "E05-FO": "docs/design/E05/E05-D02-feedback-overlays.md",
    "SEED": "services/api/candleviewer/auth/rbac_seed.json",
    "LIM": "services/api/candleviewer/bars/limits.py",
    "BSPEC": "services/api/candleviewer/bars/spec.py",
}
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SEMANTIC = ("semantic-dark", "semantic-light", "semantic-hc")

# ---- the ruling and the fixed facts
RULING_ID = "6426302306"
BQ_LIST_ID = "6426217026"
RULED_IDS = (RULING_ID, BQ_LIST_ID)  # the allow-list: every comment id the docs cite
OWNER_PENDING = "owner approval pending (#2701)"  # BQ-8, BQ-12, BQ-16
MAX_BOARDS = 10  # RULED BQ-20 (lever 4): at most ten boards
TWIN_SHARE = Fraction(1, 3)  # twins at most a third of the boards (lever 4)
TWINS = {"light twin of 01", "light twin of 04", "high-contrast twin of 01"}  # RULED BQ-20
SPEC_LINE_BUDGET = 600  # standing condition: "about 600 lines"
HAND_LINE_BUDGET = 150  # standing condition: "about 150 lines"
STORIES = ("E12-S07 (#533)", "E12-S11 (#451)", "E12-S12 (#535)", "E11-S05 (#386)")
# the bound tokens of §13 (slot rows) and the measured pairs: key -> (fg, bg, bar kind)
BOUND = (
    "surface.overlay",
    "surface.app",
    "surface.sunken",
    "text.primary",
    "text.secondary",
    "text.tertiary",
    "action.primary.default",
    "focus.ring",
    "status.danger.strong",
)
PAIRS: dict[str, tuple[str, str, str]] = {
    "primary-overlay": ("text.primary", "surface.overlay", "text"),
    "secondary-overlay": ("text.secondary", "surface.overlay", "text"),
    "tertiary-overlay": ("text.tertiary", "surface.overlay", "text"),
    "primary-app": ("text.primary", "surface.app", "text"),
    "tertiary-app": ("text.tertiary", "surface.app", "text"),
    "ring-overlay": ("focus.ring", "surface.overlay", "mark"),
    "ring-app": ("focus.ring", "surface.app", "mark"),
    "action-overlay": ("action.primary.default", "surface.overlay", "mark"),
    "onaction-action": ("text.on-action", "action.primary.default", "text"),
    "danger-overlay": ("status.danger.strong", "surface.overlay", "mark"),
    "primary-info": ("text.primary", "status.info.subtle", "text"),
    "infostrong-info": ("status.info.strong", "status.info.subtle", "mark"),
    "primary-selected": ("text.primary", "surface.selected", "text"),
    "secondary-raised": ("text.secondary", "surface.raised", "text"),
    "tertiary-raised": ("text.tertiary", "surface.raised", "text"),
    "secondary-sunken": ("text.secondary", "surface.sunken", "text"),
    "tertiary-sunken": ("text.tertiary", "surface.sunken", "text"),
    "ring-raised": ("focus.ring", "surface.raised", "mark"),
    "ring-selected": ("focus.ring", "surface.selected", "mark"),
    "danger-sunken": ("status.danger.strong", "surface.sunken", "mark"),
}
# names a doc may cite that are not shipped tokens: proposals and routed names, each with its row
NOT_SHIPPED = {
    "color.border.field": "E11-D03:445 PROPOSED",
    "space.tabs.*": "routed to E12-D09 (A-12)",
}
# the D02:236 sketch's names -> CMP-181 `chartType` keys (D06h A-1.1)
SKETCH_KEYS = {
    "Candles": "candle",
    "Bars": "bar",
    "Hollow": "hollow",
    "Line": "line",
    "Area": "area",
    "Baseline": "baseline",
    "Heikin-Ashi": "heikin-ashi",
}
OPTION_LABELS = {
    "candle": "Candles",
    "bar": "Bars (OHLC)",
    "hollow": "Hollow candles",
    "line": "Line",
    "area": "Area",
    "baseline": "Baseline",
    "heikin-ashi": "Heikin-Ashi",
    "equi-volume": "Equi-volume",
    "delta-volume": "Delta-volume",
}
MODE_NAMES = {"time", "tick", "volume", "range", "delta", "renko"}
UNIT_NAME = {"tick": "trades", "volume": "BTC", "range": "ticks", "delta": "BTC", "renko": "ticks"}
BOUND_KEYS = {"tick": "tick", "volume": "qty", "range": "range", "delta": "qty", "renko": "renko"}
TAB_ORDER = (
    "tabs",
    "×",
    "Chart type",
    "the callout's two buttons, while shown",
    "Baseline base fields, with Price",
    "Bar mode",
    "the interval select or spinbutton",
    "Magnet",
    "Readout",
    "Go to Scales",
    "Apply to",
    "Reset General…",
    "Reset all…",
    "Cancel",
    "Save",
    "`Retry`, while shown",
)
# the frames that draw a status-strip notice: D02's NC-1, never a CMP-028 callout (D02:406)
STRIP_FRAMES = ("`scope/outcome · dark`", "`scope/default-notice · dark`")
# E11-D03:273's scope clause, quoted verbatim by §9.1 (G-RESET)
SCOPE_CLAUSE = "for {this panel | all panels in this workspace | your defaults and this panel}"
# §1.3: a locked input's first cite must sit on the line that holds its fragment (G-LOCKED)
LOCKED_FRAG = {"D01": "bar-mode vocabulary"}
# compatibility characters the docs may hold (NFKC would fold them); any other one FAILs (G-CHARSET)
CHARSET_ALLOW = frozenset("…")
# load-bearing fragments: (cite id, line at the base, text the line must hold)
CITED: tuple[tuple[str, int, str], ...] = (
    ("14", 770, "Candlestick"),
    ("14", 782, "Renko brick > 0"),
    ("14", 783, "units in the label"),
    ("14", 787, "no audit record"),
    ("14", 788, "live preview against a real chart"),
    ("14", 875, "SCR-035 — Indicator settings dialog"),
    ("16", 114, "32px"),
    ("16", 210, "1280×800px"),
    ("05", 100, "≥24×24 CSS px"),
    ("05", 125, "≥4.5:1"),
    ("05", 126, "≥3:1"),
    ("11", 906, "client-side with no refetch"),
    ("11", 915, "type switch ≤100 ms"),
    ("22", 4112, "maxLength: 24"),
    ("22", 4064, "`heikin_ashi`"),
    ("22", 20542, "^[a-z][a-z0-9_]{0,31}$"),
    ("D02", 236, "(*) Candles ( ) Bars ( ) Hollow"),
    ("D02", 254, '"all panels" belongs to the layouts epic and is not drawn.'),
    ("D02", 370, "10 s per 1 M prints"),
    ("D03", 62, "Order: Time, then Tick, Volume, Range, Delta, Renko"),
    ("D03", 237, "Recent"),
    ("D03", 245, "Requested 300 ms after the last keystroke"),
    ("D06", 312, "· width mapping off"),
    ("D06", 565, "Switch to time bars"),
    ("E11-D02", 116, "default off"),
    ("E11-D03", 272, "This chart panel only. Other panels and future panels are unchanged."),
    ("E14-D02", 332, "weak (12 CSS px, default)"),
    ("BSPEC", 36, "PARAM_MAX_LEN"),
    ("BSPEC", 116, "heikin_ashi"),
    ("D01", 49, "bar-mode vocabulary"),
    ("D02", 31, "clears on the next successful switch or build of that panel"),
    ("D02", 282, "One polite live region per chart panel, pre-rendered and text-swapped"),
    ("D02", 406, "| NC-1  | Chart status strip"),
    ("D03", 50, "`Enter`, `Space` or `→` changes nothing and announces the reason once"),
    ("D03", 211, "Favourite slot reason"),
    ("E11-D03", 242, "Cancel reverts everything applied since open"),
    ("E11-D03", 273, "afterwards focus returns to the Reset Scales… button"),
    ("E11-D03", 486, "stays in the Tab order and its reason is read"),
    ("E11-D09", 1106, "`workspaces:write`"),
    ("15", 103, "reachable by the arrows but never checked"),
    ("15", 2610, "CMP-222 ChartTypeToggle"),
    ("22", 9826, "`_meta.overridden` lists which keys came from the user"),
    ("22", 9896, "Sending `null` for a leaf resets it"),
    ("22", 12120, "operationId: updateMyPreferences"),
)
# copy the spec quotes verbatim from a merged line:
# (cite id, line, text, the spec section quoting it)
VERBATIM: tuple[tuple[str, int, str, str], ...] = (
    (
        "D02",
        279,
        (
            "Footprint needs a real-price bar type. Heikin-Ashi recomputes each bar's open and "
            "close, so footprint cells would not line up with traded prices."
        ),
        "3.4 Unsupported",
    ),
    ("E15-D02", 507, "Discard your changes to these settings?", "9.2 The dirty"),
    ("E11-D03", 279, "Preview unavailable — no bars loaded", "8. The preview"),
    ("E11-D03", 280, "Preview unavailable — chart error; settings still apply", "8. The preview"),
    (
        "E11-D03",
        858,
        (
            "Defaults for the other fields are stored per panel until the settings contract"
            " carries them"
        ),
        "7.2 The scope",
    ),
    ("E11-D02", 302, "Crosshair magnet: weak", "2.2 Crosshair"),
    ("E09-D09", 95, "Read-only while viewing as {user}.", "10.1 Roles"),
)

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z0-9]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
FIGURE = re.compile(
    r"(?<![\w.,:#/>{-])(\d+(?:[.,]\d+)*)\s?(ms|s|hz|px|%|:1)(?![\w])", re.IGNORECASE
)
CITE_GROUP = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:D0[1236]h?|SEED|LIM|BSPEC|E05-FO|E\d\d-D\d\d)\b)) ?"
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


MUTATION_HEAD = "15.2 The mutation list"  # its rows describe the violations they plant


def lex_units(doc: str, text: str) -> list[LexUnit]:
    """Every unit a lexicon gate reads, rendered: each table row (cells joined by " | "), each
    bullet or numbered item, each paragraph and each heading, with its `##` section. Skipped: the
    spec's §15.2 rows (they name the violations they plant) and Table A's Old cells in the
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


# ---------------------------------------------------------------------------- numbers


def grouped(n: int) -> str:
    """Whole numbers with commas (D03:58, D3-13)."""
    return f"{n:,}"


def minimal(x: str) -> str:
    """Minimal exact form (E08-D06:220): trailing fractional zeros dropped, no float."""
    d = Decimal(x)
    s = format(d.normalize(), "f")
    return s


def ast_value(node: ast.expr, names: dict[str, object]) -> object:
    """A tiny evaluator for the constants of `limits.py` / `spec.py`: numbers, tuples, names
    already bound, `+ - * **` (the syntax tree only; nothing is imported or executed)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(ast_value(e, names) for e in node.elts)
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise SystemExit(f"FAIL parse: {node.id} is not bound before use")
        return names[node.id]
    if isinstance(node, ast.BinOp):
        a, b = ast_value(node.left, names), ast_value(node.right, names)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            ops: dict[type[ast.operator], Callable[[float, float], float]] = {
                ast.Add: lambda x, y: x + y,
                ast.Sub: lambda x, y: x - y,
                ast.Mult: lambda x, y: x * y,
                ast.Pow: lambda x, y: x**y,
            }
            fn = ops.get(type(node.op))
            if fn is not None:
                return fn(a, b)
    raise SystemExit(f"FAIL parse: unsupported expression {ast.dump(node)[:60]}")


@functools.lru_cache(maxsize=4)
def module_constants(rel: str) -> dict[str, object]:
    """Every top-level constant of a module, read from its syntax tree at the base."""
    tree = ast.parse(at_base(rel))
    names: dict[str, object] = {}
    for stmt in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        if isinstance(target, ast.Name) and value is not None:
            try:
                names[target.id] = ast_value(value, names)
            except SystemExit:
                continue
    return names


def lim(name: str) -> object:
    consts = module_constants(CITE_FILES["LIM"])
    if name not in consts:
        raise SystemExit(f"FAIL parse: {name} not in {CITE_FILES['LIM']} at {BASE}")
    return consts[name]


def lim_values() -> Values:
    v: Values = {}
    for key, name in (
        ("tick", "TICK_PARAM_RANGE"),
        ("range", "RANGE_TICKS_RANGE"),
        ("renko", "RENKO_TICKS_RANGE"),
    ):
        pair = lim(name)
        if not (isinstance(pair, tuple) and len(pair) == 2):
            raise SystemExit(f"FAIL parse: {name} is not a pair")
        lo, hi = pair[0], pair[1]
        if not (isinstance(lo, int) and isinstance(hi, int)):
            raise SystemExit(f"FAIL parse: {name} is not a pair of whole numbers")
        v[f"LIM:{key}.min"], v[f"LIM:{key}.max"] = grouped(lo), grouped(hi)
    qmax, steps = lim("QTY_PARAM_MAX"), lim("QTY_PARAM_MIN_STEPS")
    if not (isinstance(qmax, int) and isinstance(steps, int)):
        raise SystemExit("FAIL parse: the qty bounds are not whole numbers")
    v["LIM:qty.max"], v["LIM:qty.min-steps"] = grouped(qmax), grouped(steps)
    return v


def param_max_len() -> int:
    n = module_constants(CITE_FILES["BSPEC"]).get("PARAM_MAX_LEN")
    if not isinstance(n, int):
        raise SystemExit("FAIL parse: PARAM_MAX_LEN not found in bars/spec.py")
    return n


# ---- D03's per-mode table and copy deck, read as text at the base

D03_TABLE_HEAD = "2. Per-mode specification"
D03_DECK_HEAD = "5. Copy deck"


@functools.lru_cache(maxsize=1)
def d03_rows() -> dict[str, list[str]]:
    """D03 §2's rows by `bar_type`: [mode, row, description, field, default, bounds, msg, rule]."""
    out: dict[str, list[str]] = {}
    for cells in table_rows(section(at_base(CITE_FILES["D03"]), D03_TABLE_HEAD)):
        m = re.search(r"\(`([a-z_]+)`\)", cells[0])
        if m:
            out[m[1]] = cells
    return out


@functools.lru_cache(maxsize=1)
def d03_deck() -> dict[str, str]:
    """D03 §5's strings by id (C-1 … C-42)."""
    out: dict[str, str] = {}
    for cells in table_rows(section(at_base(CITE_FILES["D03"]), D03_DECK_HEAD)):
        if re.fullmatch(r"C-\d+", cells[0]) and len(cells) > 2:
            out[cells[0]] = cells[2]
    return out


def d03_order() -> list[str]:
    line = base_line("D03", 62)
    names = grab(r"Order: (Time, then [A-Za-z, ]+?) \(", line, "D03:62 order")
    return [n.strip().lower() for n in re.split(r",|then", names) if n.strip()]


def d03_values() -> Values:
    v: Values = {}
    for mode in ("tick", "volume", "range", "delta", "renko"):
        cell = d03_rows()[mode][4]
        v[f"D03:default.{mode}"] = grab(r"^([\d,]+)", cell, f"D03 default for {mode}")
    v["D03:estimate-delay"] = grab(
        r"Requested (\d+) ms after the last keystroke", base_line("D03", 245), "D03:245"
    )
    return v


# ---- the fixture, the budgets and the counts


def fix_values() -> Values:
    data = json.loads(at_base(INSTR_REL))
    rows = data["result"]["list"] if "result" in data else data
    btc = next(r for r in rows if r.get("symbol") == "BTCUSDT")
    tick = minimal(btc["priceFilter"]["tickSize"])
    step = minimal(btc["lotSizeFilter"]["qtyStep"])
    floor = max(math.ceil(Decimal(step) * int(str(lim("QTY_PARAM_MIN_STEPS")))), 1)
    return {"FIX:btc.tick": tick, "FIX:btc.qty-step": step, "FIX:btc.floor": str(floor)}


def budget_values() -> Values:
    w, h = re.findall(r"(\d+)×(\d+)px", base_line("16", 210))[0]
    return {
        "BUDGET:viewport.w": w,
        "BUDGET:viewport.h": h,
        "BUDGET:type-switch": grab(r"type switch ≤(\d+) ms", base_line("11", 915), "11:915"),
        "BUDGET:build-per-m": grab(r"(\d+) s per 1 M prints", base_line("D02", 370), "D02:370"),
        "BUDGET:param.max-len": str(param_max_len()),
        "BUDGET:target.min": grab(r"≥(\d+)×\d+ CSS px", base_line("05", 100), "05:100"),
        "BUDGET:row.comfortable": grab(r"\|\s*(\d+)px", base_line("16", 114), "16:114"),
    }


def board_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "0. Status")) if re.fullmatch(r"\d{2}", r[0])]


def is_twin(row: list[str]) -> bool:
    return "twin of" in row[2]


BOARD_SCRIPT = "docs/design/_tools/sheets/e12-d05/e12-d05-board.js.txt"  # the r2 script §0 names
DRAWN_CELL = re.compile(
    r"drawn \(r2\): board id `[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}`, "
    r"`(?P<png>[^`]+)` \((?P<w>\d+) × (?P<h>\d+)\)"
)
FRAME_HEAD = "15.1 The frame register"
FR_COLS = ("Frame", "Board", "Theme", "State", "Components", "Copy", "Tokens", "Status")


def frames(spec: str) -> list[dict[str, str]]:
    rows = [r for r in table_rows(section(spec, FRAME_HEAD)) if r and r[0].startswith("`")]
    return [dict(zip(FR_COLS, r, strict=False)) for r in rows]


def d06_type_count() -> int:
    rows = table_rows(section(at_base(CITE_FILES["D06"]), "3.2 The type table"))
    return len([r for r in rows if r and r[0]])


def pair_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "13. Tokens")) if " on " in r[0]]


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
        "COUNT:types": str(d06_type_count()),
        "COUNT:modes": str(len(d03_order())),
        "COUNT:pairs": str(len(PAIRS)),
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


@functools.lru_cache(maxsize=4)
def compute_cached(spec: str, hand: str) -> tuple[tuple[tuple[str, str], ...], str]:
    del hand  # the hand-off adds no computed key of its own
    v: Values = {}
    v |= lim_values()
    v |= d03_values()
    v |= fix_values()
    v |= budget_values()
    v |= count_values(spec)
    v |= colour_values()
    extra = {
        "parity": {m: d03_rows()[m][3:7] for m in ("tick", "volume", "range", "delta", "renko")},
        "d03_order": d03_order(),
        "chart_types": chart_type_union(),
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
COPY_CELLS = (("Table A", 3),)


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
                if m["a"] and not (re.fullmatch(r"\d{2}|ENG|E\d\d-D\d\d", cid) or "/" in cid):
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
    plans: tuple[tuple[str, str], ...]  # the working-tree `14`, `15`, `16`, `22`, D02 (G-UNTOUCHED)
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


# ---------------------------------------------------------------------------- the gates
#
# Each gate returns findings (tag, message, doc, section). A lexicon gate reads rendered clauses
# (comments stripped, NFKC, markup dropped, lower case); quoted copy is not a claim.


def chart_type_union() -> list[str]:
    """D06h A-1.1's `chartType` union (the New cell of D06h:43), in its order."""
    line = base_line("D06h", 43)
    new = split_row(line)[4]
    m = re.search(r'`chartType: ((?:"[a-z-]+"\\?\|?)+)`', new)
    if not m:
        raise SystemExit("FAIL parse: D06h:43 has no chartType union")
    return re.findall(r'"([a-z-]+)"', m[1])


def expected_type_order() -> list[str]:
    """D02:236's order of the sketch's names, then the rest of A-1.1's union (width-mapped)."""
    names = re.findall(r"\(\*?\s?\)?\s*([A-Z][A-Za-z-]+)", base_line("D02", 236))
    keys = [SKETCH_KEYS[n] for n in names if n in SKETCH_KEYS]
    return keys + [k for k in chart_type_union() if k not in keys]


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
    """BQ-1 (M-2): §0 states the chart UI is unbuilt and names the implementing stories."""
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
    """BQ-1 (M-56): the trace has one row per acceptance criterion."""
    rows = table_rows(section(t.spec, "Acceptance-criteria trace"))
    have = {m[1] for r in rows if (m := re.match(r"(AC\d)\b", r[0]))}
    sec = spec_sec(t, "Acceptance-criteria trace")
    return [
        F("G-TRACE", f"no {a} row", "spec", sec)
        for a in ("AC1", "AC2", "AC3", "AC4", "AC5")
        if a not in have
    ]


def g_boards(t: Texts) -> list[Finding]:
    """BQ-20 (M-6): at most MAX_BOARDS boards, twins at most TWIN_SHARE, the three ruled twins,
    each board's theme cell matching its kind."""
    sec = spec_sec(t, "0. Status")
    rows = board_rows(t.spec)
    bad: list[Finding] = []
    twins = [r for r in rows if is_twin(r)]
    if len(rows) > MAX_BOARDS:
        bad.append(F("G-BOARDS", f"{len(rows)} boards > {MAX_BOARDS}", "spec", sec))
    if rows and Fraction(len(twins), len(rows)) > TWIN_SHARE:
        bad.append(F("G-BOARDS", f"{len(twins)} twins of {len(rows)} > one third", "spec", sec))
    if {r[2] for r in twins} != TWINS:
        bad.append(F("G-BOARDS", "the twins are not light 01, light 04, hc 01", "spec", sec))
    if "every board is a canvas of frames, each frame a" not in norm_text(
        section(t.spec, "0. Status")
    ):
        bad.append(F("G-BOARDS", "§0 does not make each frame a window on a canvas", "spec", sec))
    for r in rows:
        want = "dark" if not is_twin(r) else ("hc" if "high-contrast" in r[2] else "light")
        if len(r) < 5 or r[3] != want or not drawn_cell_ok(r):
            bad.append(F("G-BOARDS", f"board {r[0]}: theme or status cell", "spec", sec))
    script = ROOT / BOARD_SCRIPT
    sha = hashlib.sha256(script.read_bytes()).hexdigest() if script.exists() else "missing"
    if f"board script r2, sha256 `{sha}`" not in section(t.spec, "0. Status"):
        bad.append(F("G-BOARDS", f"§0 does not name {BOARD_SCRIPT}'s sha256", "spec", sec))
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
    slug = re.fullmatch(rf"`E12-D05 / {row[0]} ([a-z0-9-]+)`", row[1])
    m = DRAWN_CELL.fullmatch(row[4])
    if not slug or not m:
        return False
    want = f"docs/design/E12/img/E12-D05-{row[0]}-{slug[1]}.png"
    return m["png"] == want and png_size(want) == (int(m["w"]), int(m["h"]))


def g_penpot(t: Texts) -> list[Finding]:
    """BQ-20 (M-1): the Penpot page by name + id only: no URL, no host."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if URL.search(line):
                bad.append(F("G-PENPOT", f"{doc}:{i} a URL", doc, h2_at(text, i)))
    return bad


def g_locked(t: Texts) -> list[Finding]:
    """BQ-2 (M-8): §1.3 holds a cited row for each parent: D01, D02, D03, D06 and E11-D03."""
    sec = spec_sec(t, "1.3 Locked")
    rows = table_rows(section(t.spec, "1.3 Locked"))
    bad: list[Finding] = []
    for lead in ("D01", "D02", "D03", "D06", "E11-D03"):
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
    """BQ-3 (M-9): Table A runs A-1 … A-n without a gap, and every A-n the docs name exists."""
    have = a_rows(t.hand)
    sec = hand_sec(t, "§C Copy-ready")
    bad: list[Finding] = []
    nums = sorted(int(k[2:]) for k in have)
    if nums != list(range(1, len(nums) + 1)):
        bad.append(F("G-AROW", f"Table A is not contiguous: {nums}", "hand", sec))
    named = set(re.findall(r"\bA-(\d+)\b", strip_comments(t.spec)))
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
    remainder of the same part (lens finding: a cut-off Validation line)."""
    cuts = sorted({0, len(value), *(m.end() for m in re.finditer(r" · | (?=\[[ x]\] )", value))})
    return {value[a:b].strip().removesuffix(" ·").strip() for a in cuts for b in cuts if b > a}


# a Table A row a merged `15` change already applied: its Old cell is exactly this marker, the PR
# is a commit on the cited file at the base, and every code span of its New is on the cited line
CLOSED_ROW = re.compile(r"applied by #(\d+) \(closed\)")


def closed_resolves(pr: str, cite: re.Match[str], new: str) -> bool:
    """A closed A-row's cite resolves: `#pr` merged into the cited file by the base, and the New
    cell quotes (as code spans) only what the cited line holds at the base."""
    rel = cite_path(cite["a"] or cite["b"])
    nums = [int(x) for x in re.split(r"[–-]", cite["first"])]
    if not rel or len(nums) != 1 or cite["more"]:
        return False
    log = git_out("log", "--format=%s", BASE, "--", rel)
    if not re.search(rf"\(#{pr}\)$", log, flags=re.MULTILINE):
        return False
    line = (git_show(BASE, rel) or "").split("\n")
    spans = CODE.findall(new)
    if not spans or nums[0] > len(line):
        return False
    held = line[nums[0] - 1]  # spans compared whole, backticks and `*` kept (`_flat` drops both)
    return all(x.replace("\\|", "|") in held for x in spans)


def g_old(t: Texts) -> list[Finding]:
    """BQ-3: every Old cell of Table A is verbatim on its cited line at the base."""
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
        shut = CLOSED_ROW.fullmatch(old)
        if shut or "closed" in old.lower():
            if not shut or not closed_resolves(shut[1], m, r[4] if len(r) > 4 else ""):
                bad.append(F("G-OLD", f"{aid}: its closed marker does not resolve", "hand", sec))
            continue
        cid = m["a"] or m["b"]
        first = m["first"]
        nums = [int(x) for x in re.split(r"[–-]", first)]
        more = [int(x) for x in re.findall(r":(\d+)", m["more"])]
        lo, hi = min(nums + more), max(nums + more)
        rel = cite_path(cid)
        base = (git_show(BASE, rel) or "").split("\n") if rel else []
        lines = [_flat(x) for x in base[lo - 1 : hi]]
        item = re.match(r"^- \*\*[^*]+\*\*:?\s*", base[lo - 1]) if lo == hi and base else None
        if item and _flat(old) not in whole_runs(_flat(base[lo - 1][item.end() :])):
            bad.append(F("G-OLD", f"{aid}: Old is not whole parts of `{cid}`:{lo}", "hand", sec))
            continue
        spans = CODE.findall(old)
        if spans and all(s.startswith("`\\|") for s in spans):
            miss = [s for s in spans if _flat(s) not in lines]
        else:
            miss = [old] if _flat(old) not in " ".join(lines) else []
        if miss:
            bad.append(F("G-OLD", f"{aid}: Old not verbatim at `{cid}`:{lo}", "hand", sec))
    return bad


# a setting R-1 homes elsewhere, as §2.1 may name it in any cell (the crosshair's own magnet is
# General's, so a bare "magnet" counts only in the lead cell)
ELSEWHERE = (
    r"\bdecimals?\b|\bprecision\b|\bcount ?down\b|\bbar close timer\b|\bdrawing magnet\b"
    r"|\bsnap(?:ping)? to (?:ohlc|price)\b|\bcolou?rs?\b|\bdensity\b|\bup ?/ ?down\b"
)


def g_home(t: Texts) -> list[Finding]:
    """BQ-4 (M-10, M-11): General points to precision and the countdown and names the drawing
    magnet; it hosts none of them (R-1). Every cell of §2.1's table is read (lens r1 P01), and a
    clause hosting, holding, carrying, offering or containing one of them FAILs."""
    sec = spec_sec(t, "2.1 Layout")
    bad: list[Finding] = []
    for r in table_rows(section(t.spec, "2.1 Layout")):
        hit = re.search(r"magnet", r[0], re.IGNORECASE) or re.search(
            ELSEWHERE, norm_text(" | ".join(r))
        )
        if hit:
            bad.append(F("G-HOME", f"§2.1 {r[0]!r} hosts {hit[0]!r}", "spec", sec))
    hits = claims(
        lex(t),
        r"\b(?:host|hold|carr(?:y|ie)|offer|contain)(?:s|ed|ing)?\b",
        near=r"drawing magnet|precision|decimals?\b|count ?down",
    )
    return bad + as_findings("G-HOME", "a hosted setting", hits)


def g_crosshair(t: Texts) -> list[Finding]:
    """BQ-4 (M-12): magnet Off (default) / Weak / Strong; readout Follow (default) / Docked /
    Off."""
    body = section(t.spec, "2.2 Crosshair")
    sec = spec_sec(t, "2.2 Crosshair")
    return [
        F("G-CROSSHAIR", f"§2.2 lacks {n!r}", "spec", sec)
        for n in (
            "**Magnet:** Off (default) · Weak · Strong",
            "**Readout:** Follow (default) · Docked · Off",
        )
        if n not in body
    ]


def type_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "3.1 The nine")) if len(r) >= 5]


def g_types(t: Texts) -> list[Finding]:
    """BQ-5 (M-13, M-14, M-17): D06's nine in D02's order, width-mapped last, each named in
    text with one quoted description."""
    sec = spec_sec(t, "3.1 The nine")
    rows = type_rows(t.spec)
    keys = [r[1].strip("`") for r in rows]
    bad: list[Finding] = []
    want = expected_type_order()
    if keys != want or len(want) != d06_type_count():
        bad.append(F("G-TYPES", f"§3.1 types {keys} != {want}", "spec", sec))
    for r in rows:
        key = r[1].strip("`")
        if OPTION_LABELS.get(key) != r[0]:
            bad.append(F("G-TYPES", f"{key}: option label {r[0]!r}", "spec", sec))
        if not re.fullmatch(r'"[^"]{8,}"', r[2]):
            bad.append(F("G-TYPES", f"{key}: no descriptive line", "spec", sec))
    return bad


WIRE_VERB = (
    r"(?:sen[dt]s?|sending|post(?:s|ed|ing)?|request(?:s|ed|ing)?|transmit\w*|pass(?:es|ed))"
)
g_wire = lexicon(
    "G-WIRE",
    "heikin_ashi sent as a wire bar_type or interval_code",
    r"\bsends?\b[^.;]*\bheikin_ashi\b|\bheikin_ashi\b[^.;]*\b(?:as|in) (?:the |a |an )?"
    r"(?:bar_type|interval_code)\b|\binterval_code\b[^.;]*\bheikin_ashi:"
    # lens r1 P05: a passive or synonym verb before the wire field, or §3.1's row as the subject
    rf"|\b{WIRE_VERB}\b(?: \S+){{0,3}}? (?:as|in|via|through) (?:the |a |an )?(?:wire )?"
    r"(?:bar_type|interval_code)\b[^.;]*\bheikin(?:_| )ashi\b"
    rf"|^heikin ashi \|[^|]*\b{WIRE_VERB}\b(?: \S+){{0,3}}? (?:as|in|via|through) "
    r"(?:the |a |an )?(?:wire )?(?:bar_type|interval_code)\b",
)
g_base = require("G-BASE", "3.2 Baseline", ("first visible close (default)",))


def g_grows(t: Texts) -> list[Finding]:
    """BQ-1 / BQ-5 (M-18): the G-rows and Q-rows run without a gap; G6 is the volume sub-pane."""
    body = section(t.spec, "16.2")
    sec = spec_sec(t, "16.2")
    bad: list[Finding] = []
    for kind, n in (("G", 9), ("Q", 5)):
        for i in range(1, n + 1):
            if f"**D05-{kind}{i}**" not in body:
                bad.append(F("G-GROWS", f"D05-{kind}{i} missing", "spec", sec))
    g6 = row_segment(body, "D05-G6")
    if g6 and "volume sub-pane" not in g6:
        bad.append(F("G-GROWS", "D05-G6 is not the volume sub-pane", "spec", sec))
    return bad


def row_segment(body: str, rid: str) -> str:
    """The text of the G- or Q-row `rid`: from its bold id to the next bold row id or line end."""
    m = re.search(rf"\*\*{re.escape(rid)}\*\*(.*?)(?=\*\*D05-[GQ]\d+\*\*|\n|\Z)", body)
    return m[1] if m else ""


def g_crows(t: Texts) -> list[Finding]:
    """BQ-3 / BQ-6 (M-23): the C-rows run without a gap; C7 records `14`:783."""
    rows = table_rows(section(t.spec, "16.1"))
    sec = spec_sec(t, "16.1")
    ids = [r[0] for r in rows if r[0].startswith("D05-C")]
    nums = [int(i[5:]) for i in ids]
    bad: list[Finding] = []
    if nums != list(range(1, len(nums) + 1)) or len(nums) < 22:
        bad.append(F("G-CROWS", f"the C-rows are {ids[:3]}…, not D05-C1 … C22", "spec", sec))
    c7 = next((r for r in rows if r[0] == "D05-C7"), None)
    if c7 is None or "`14`:783" not in c7[1]:
        bad.append(F("G-CROWS", "D05-C7 does not record `14`:783", "spec", sec))
    elif len(c7) < 4 or "the owner" not in c7[3]:
        bad.append(
            F("G-CROWS", "D05-C7 (an intended difference) is not routed to the owner", "spec", sec)
        )
    return bad


def parity_rows(spec: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in table_rows(section(spec, "4.1 The parity")):
        m = re.search(r"\(`([a-z_]+)`\)", r[0])
        if m:
            out[m[1]] = r
    return out


def g_parity(t: Texts) -> list[Finding]:
    """BQ-6 (M-19, M-20): every non-time row equals D03's in label, unit, accessible name, default
    key, bound keys and messages (ids and strings verbatim)."""
    sec = spec_sec(t, "4.1 The parity")
    rows = parity_rows(t.spec)
    deck = d03_deck()
    bad: list[Finding] = []
    for mode in ("tick", "volume", "range", "delta", "renko"):
        r = rows.get(mode)
        if r is None or len(r) < 7:
            bad.append(F("G-PARITY", f"no {mode} row", "spec", sec))
            continue
        d = d03_rows()[mode]
        label = grab(r'^"([^"]+)"', d[3], f"D03 {mode} label")
        unit = d[3].split(",")[1].strip()
        if r[1] != f'"{label}"':
            bad.append(F("G-PARITY", f"{mode} label {r[1]} != {label!r}", "spec", sec))
        if r[2] != unit:
            bad.append(F("G-PARITY", f"{mode} unit {r[2]!r} != {unit!r}", "spec", sec))
        if r[3] != f'"{label}, {UNIT_NAME[mode]}"':
            bad.append(F("G-PARITY", f"{mode} accessible name {r[3]}", "spec", sec))
        if f"D03:default.{mode}" not in r[4]:
            bad.append(F("G-PARITY", f"{mode} default is not D03's", "spec", sec))
        bk = BOUND_KEYS[mode]
        if mode != "delta" and not all(
            f"LIM:{bk}.{x}" in anch(r[5])
            for x in (("min", "max") if bk != "qty" else ("min-steps", "max"))
        ):
            bad.append(F("G-PARITY", f"{mode} bounds are not LIM's", "spec", sec))
        want = re.findall(r"C-\d+", d[6])
        got = re.findall(r'(C-\d+) "([^"]+)"', r[6])
        if [g[0] for g in got] != want:
            bad.append(
                F("G-PARITY", f"{mode} messages {[g[0] for g in got]} != {want}", "spec", sec)
            )
        for cid, text in got:
            if deck.get(cid) != text:
                bad.append(F("G-PARITY", f"{mode} {cid} is not verbatim", "spec", sec))
    return bad


def g_modes(t: Texts) -> list[Finding]:
    """BQ-6 (M-21): §4.1's rows are D03's six modes in D03:62's order; no P&F, no HA."""
    sec = spec_sec(t, "4.1 The parity")
    got = list(parity_rows(t.spec))
    want = d03_order()
    if got != want or set(got) - MODE_NAMES:
        return [F("G-MODES", f"§4.1 modes {got} != {want}", "spec", sec)]
    return []


g_diff = require("G-DIFF", "4.1 The parity", ("shows no recent row", "recorded on #241"))
g_live = both(
    lexicon(
        "G-LIVE",
        "a bar mode applied live",
        r"\b(?:applies|apply|applied|commits?|committed|rebuilds?|takes effect)"
        r"(?: \w+){0,2}? (?:live|instantly|immediately|at once|on change|as you type)\b"
        r"|\blive\b[^.;]*\bbar mode\b"
        # lens r1 P20: a row led by the bar mode whose cell reads live
        r"|\bbar mode\b[^|.;]*\|\s*(?:\S+\s+){0,2}?(?:live|instantly|immediately|at once)\b",
        near=r"\bbar mode\b|\bparameter\b",
        unless=r"\bchart type\b|\bcrosshair\b",
    ),
    require("G-LIVE", "5. Apply model", ("| on save only (r 2) |",)),
)
g_enter = lexicon(
    "G-ENTER",
    "Enter saving the dialog",
    # lens r1 P02: the synonyms of saving (verbs only: "to Save, `Enter`" names the button)
    r"\b(?:saves|saved|commits|committed|submits|submitted|persists|persisted)\b",
    near=r"\benter\b",
)
g_rebuild = require("G-REBUILD", "5. Apply model", ("needs a build", "rebuilds the chart on save"))


def g_owner(t: Texts) -> list[Finding]:
    """BQ-8, BQ-12, BQ-16 (M-27): each owner item is marked PROPOSED, owner approval pending."""
    bad: list[Finding] = []
    marker = f"PROPOSED, {OWNER_PENDING}"
    for head in ("2.3 Session", "3.4 Unsupported", "7.4 As new default"):
        line = next((ln for ln in t.spec.split("\n") if ln.startswith(f"### {head}")), "")
        if marker not in line:
            bad.append(
                F(
                    "G-OWNER",
                    f"§{head.split()[0]} heading lacks the marker",
                    "spec",
                    spec_sec(t, head),
                )
            )
    for q in ("D05-Q1", "D05-Q2", "D05-Q3", "D05-G7"):
        if OWNER_PENDING not in row_segment(section(t.spec, "16.2"), q):
            bad.append(F("G-OWNER", f"{q} lacks {OWNER_PENDING!r}", "spec", spec_sec(t, "16.2")))
    return bad


g_refuse = lexicon(
    "G-REFUSE",
    "a footprint refusal beyond Heikin-Ashi",
    r"\brefus\w*",
    near=r"\bfootprint\b",
    unless=r"\balternatives?\b|\bheikin\b",
)


def g_verbatim(t: Texts) -> list[Finding]:
    """BQ-8, BQ-14 (M-29): the cited copy appears verbatim in the section that quotes it."""
    return [
        F("G-VERBATIM", f"`{cid}`:{n} {text[:40]!r} not quoted verbatim", "spec", spec_sec(t, head))
        for cid, n, text, head in VERBATIM
        if f'"{text}' not in " ".join(section(t.spec, head).split())
    ]


def g_verbatim_src(t: Texts) -> list[Finding]:
    """The VERBATIM strings sit on their cited lines at the base."""
    del t
    bad: list[Finding] = []
    for cid, n, text, _head in VERBATIM:
        if " ".join(text.split()) not in " ".join(base_line(cid, n).split()):
            bad.append(F("G-CITE", f"`{cid}`:{n} does not hold {text[:40]!r}", None, None))
    return bad


g_precision = lexicon(
    "G-PRECISION",
    "float arithmetic on contract values",
    r"\btofixed\b|\bparsefloat\b|\bfloat(?:ing)?(?: point)? arithmetic\b|\bas a float\b",
)


def g_marked(t: Texts) -> list[Finding]:
    """BQ-9 (M-31): PROPOSED items stay marked as proposals."""
    bad: list[Finding] = []
    for head, needle in (
        ("6. Precision", "round half-even"),
        ("6. Precision", "**Mirror and SCR-045**"),
        ("7.3 All panels", "### 7.3"),
        ("12. Copy deck", "## 12."),
        ("3.1 The nine", "| Option"),
        ("3.2 Baseline", "`baseline?`"),
        ("8. The preview", "D03-CR-3"),
    ):
        line = next((ln for ln in section(t.spec, head).split("\n") if needle in ln), "")
        if "PROPOSED" not in line:
            bad.append(
                F("G-MARKED", f"{needle!r} is not marked PROPOSED", "spec", spec_sec(t, head))
            )
    return bad


g_haanchor = lexicon(
    "G-HAANCHOR",
    "Heikin-Ashi values as an anchor",
    r"\banchors?\b",
    near=r"\bheikin\b|\bderived\b",
    head="6. Precision",
)


def g_keys(t: Texts) -> list[Finding]:
    """BQ-10 (M-33): the PROPOSED `PaneConfig.settings` keys match `22`'s key pattern, and the
    hand-off's A-15 names the same keys."""
    pat = grab(r"`(\^\[a-z\][^`]+)`", base_line("22", 20542), "22:20542 key pattern")
    sec = spec_sec(t, "7.1 Where")
    spec_keys = [
        k
        for r in table_rows(section(t.spec, "7.1 Where"))
        if "PROPOSED" in r[1]
        for k in re.findall(r"`([a-zA-Z_]+)`", r[1])
        if k not in ("PaneConfig", "settings")
    ]
    bad = [
        F("G-KEYS", f"{k!r} does not match {pat}", "spec", sec)
        for k in spec_keys
        if not re.fullmatch(pat, k)
    ]
    a15 = a_rows(t.hand).get("A-15")
    hand_keys = re.findall(r"`([a-zA-Z_]+)` \(", a15[4]) if a15 else []
    if sorted(hand_keys) != sorted(spec_keys):
        bad.append(F("G-KEYS", f"A-15 keys {hand_keys} != §7.1 {spec_keys}", "spec", sec))
    return bad


g_sync = lexicon(
    "G-SYNC",
    "chart type or bar mode synced",
    r"\b(?:chart types?|bar modes?)\b[^.;]*\b(?:syncs|synced|is synchronised)\b",
)


def g_savestates(t: Texts) -> list[Finding]:
    """BQ-10, BQ-14 (M-35): §9.3 draws saving, saved and failed (the PATCH failure included)."""
    rows = table_rows(section(t.spec, "9.3 Saving"))
    leads = [r[0] for r in rows]
    sec = spec_sec(t, "9.3 Saving")
    want = (
        "Saving",
        "Saved",
        "Save with an invalid or held parameter",
        "Failed (the `PATCH /me/preferences`)",
    )
    return [F("G-SAVESTATES", f"§9.3 lacks {w!r}", "spec", sec) for w in want if w not in leads]


g_partial = both(
    lexicon(
        "G-PARTIAL",
        "the same number for Volume or Delta",
        r"\bsame number\b",
        near=r"\bvolume\b|\bdelta\b",
    ),
    require(
        "G-PARTIAL",
        "7.3 All panels",
        (
            "each panel's own per symbol value",
            "applies to 3 of 4 chart panels",
            "nothing is skipped silently",
            "then one line per panel, changed first",
            "the outcome shows in each panel's status strip",
            "reused for a panel",
        ),
    ),
)
g_notice = both(
    require(
        "G-NOTICE",
        "7.4 As new default",
        (
            "with undo and dismiss",
            "no timer",
            "w 13 is posted once that build ends",
            "null where the leaf was not overridden",
        ),
    ),
    lexicon(
        "G-NOTICE",
        "the notice posted while the build runs",
        r"\bwhile (?:it|the build|that build|a build) (?:runs|is running)\b"
        r"|\bwhen (?:the|a) build starts\b",
        near=r"\bw 13\b|\bnotice\b|\bposted\b|\bundo\b",
        unless=r"\bclears\b",
    ),
)
g_preview = require("G-PREVIEW", "8. The preview", ("sample bars: not this chart", "changes:"))
g_fetch = lexicon(
    "G-FETCH",
    "a preview that fetches",
    r"\b(?:re)?fetch(?:es|ed|ing)?\b",
    near=r"\bpreview\b|\btile\b",
)


def g_reset(t: Texts) -> list[Finding]:
    """BQ-14 (M-41): each confirm's title names its scope and the body lists old → new."""
    rows = {r[0]: r for r in table_rows(section(t.spec, "9.1 Reset"))}
    sec = spec_sec(t, "9.1 Reset")
    bad: list[Finding] = []
    for lead, scope in (
        ("Reset General…", "Reset General to defaults?"),
        ("Reset all…", "Reset all chart settings to defaults?"),
    ):
        r = rows.get(lead)
        if r is None or f'"{scope}"' not in r[1] or "old → new" not in r[2]:
            bad.append(
                F("G-RESET", f"{lead} does not name its scope or list old → new", "spec", sec)
            )
        elif '"Rebuilds the chart on Save."' not in r[2] or "the scope clause" not in r[2]:
            bad.append(F("G-RESET", f"{lead}: the rebuild line or the scope clause", "spec", sec))
    body = " ".join(section(t.spec, "9.1 Reset").split())
    if f'"{SCOPE_CLAUSE}"' not in body:
        bad.append(F("G-RESET", "§9.1 does not quote E11-D03:273's scope clause", "spec", sec))
    if "focus returns to the reset button pressed" not in norm_text(body):
        bad.append(F("G-RESET", "§9.1 does not return focus to the Reset button", "spec", sec))
    hits = claims(
        lex(t),
        r"\bcommits?\b|\b(?:saves?|saved|persists?|writes?)\b(?: \w+){0,2}? "
        r"(?:at once|immediately|right away|on (?:its own|confirm\w*))",
        near=r"\breset\b",
    )
    return bad + w25_scope(t) + as_findings("G-RESET", "a confirmed Reset that commits", hits)


W25_SCOPE = re.compile(
    r" for (?:this panel|all panels in this workspace|your defaults and this panel)$"
)
W25_LEAD = re.compile(r"^(?:General|All chart settings) reset\b")


def w25_scope(t: Texts) -> list[Finding]:
    """Lens r1 P10: W-25 names its scope, in §12's row and in each copy §9.1 quotes."""
    bad: list[Finding] = []
    rows = {r[0]: r for r in table_rows(section(t.spec, "12. Copy deck"))}
    w25 = rows.get("W-25")
    items = [x.strip() for x in w25[2].split(" · ")] if w25 and len(w25) > 2 else []
    if len(items) != 2 or not all(W25_SCOPE.search(x) for x in items):
        sec = spec_sec(t, "12. Copy deck")
        bad.append(F("G-RESET", f"§12 W-25 without its scope: {items}", "spec", sec))
    body = " ".join(section(t.spec, "9.1 Reset").split())
    quoted = [q.strip('"“”') for q in QUOTED.findall(body)]
    said = [q for q in quoted if W25_LEAD.match(q)]
    if len(said) != 2 or not all(W25_SCOPE.search(q) for q in said):
        sec = spec_sec(t, "9.1 Reset")
        bad.append(F("G-RESET", f"§9.1 quotes W-25 without its scope: {said}", "spec", sec))
    return bad


g_guard = require("G-GUARD", "9.2 The dirty", ("keep editing focused",))


def g_rbac(t: Texts) -> list[Finding]:
    """BQ-15 (M-43): E09-D09's reasons, verbatim, in §10.1."""
    body = section(t.spec, "10.1 Roles")
    sec = spec_sec(t, "10.1 Roles")
    want = (
        "Your role can't save workspaces.",
        "Your role can't change settings.",
        "Read-only while viewing as {user}.",
    )
    bad = [F("G-RBAC", f"§10.1 lacks {w!r}", "spec", sec) for w in want if f'"{w}"' not in body]
    flat = norm_text(body)
    for n in (
        "on save, the as new default segment, the bar mode radios and both resets",
        "last only while the dialog is open",
    ):
        if n not in flat:
            bad.append(F("G-RBAC", f"§10.1 lacks {n!r}", "spec", sec))
    return bad


g_absent = require("G-ABSENT", "10.2 States", ("the option is absent, never offered and refused",))
g_t2 = require("G-T2", "10.2 States", ("an arrow moves focus onto one without checking it",))
g_reading = require(
    "G-READING", "2.1 Layout", ("column major, the first five options down the left",)
)
g_pending = both(
    require(
        "G-PENDING",
        "3.4 Unsupported",
        (
            "is pending",
            "without moving focus",
            "arrowing to another option withdraws heikin ashi",
        ),
    ),
    lexicon(
        "G-PENDING",
        "Heikin-Ashi with footprint applied before the choice",
        r"\bappl(?:y|ies|ied)\b",
        near=r"\bheikin\b[^.;]*\bfootprint\b|\bfootprint\b[^.;]*\bheikin\b",
    ),
)
g_esc = require(
    "G-ESC",
    "11. Keyboard",
    (
        "with focus in a callout esc chooses its keep button",
        "the first esc chooses keep and a second one goes on",
    ),
)
g_region = require("G-REGION", "11. Keyboard", ("speak in the panel's own polite region",))
g_tokenuse = require(
    "G-TOKENUSE", "13. Tokens", ("marks only the ✕ glyph", "never on the save fill")
)


def g_close(t: Texts) -> list[Finding]:
    """A text-first doc names no closing keyword before an issue number (PR 1 is `Refs #241`)."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if re.search(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d", norm_text(line)):
                bad.append(F("G-CLOSE", f"{doc}:{i} a closing keyword", doc, h2_at(text, i)))
    return bad


def g_charset(t: Texts) -> list[Finding]:
    """Rendered text is what the pins hold: no compatibility character that NFKC would fold (a
    superscript or full-width digit, a no-break space) beyond CHARSET_ALLOW, no CR, no trailing
    whitespace (a hard line break)."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            odd = [
                c for c in line if c not in CHARSET_ALLOW and unicodedata.normalize("NFKC", c) != c
            ]
            whys = [f"U+{ord(c):04X}" for c in odd[:1]]
            whys += ["a CR"] if "\r" in line else []
            whys += ["trailing whitespace"] if line != line.rstrip() else []
            why = ", ".join(whys)
            if why:
                bad.append(F("G-CHARSET", f"{doc}:{i} {why}", doc, h2_at(text, i)))
    return bad


g_session = lexicon(
    "G-SESSION",
    "a session link",
    r"\blinks? to\b|\blinked to\b|\blinks? (?:the|a)\b",
    near=r"\bsession\b|\bboundary\b|\brow\b",
)


def g_order(t: Texts) -> list[Finding]:
    """BQ-17 (M-46): §11's tab order is the stated sequence."""
    line = next(
        (ln for ln in section(t.spec, "11. Keyboard").split("\n") if "**Tab order:**" in ln), ""
    )
    m = re.search(r"\*\*Tab order:\*\* (.*?)\. ", line)
    got = tuple(x.strip() for x in m[1].split("→")) if m else ()
    if got != TAB_ORDER:
        return [
            F("G-ORDER", f"the tab order reads {got[:4]}…", "spec", spec_sec(t, "11. Keyboard"))
        ]
    return []


g_announce = lexicon(
    "G-ANNOUNCE",
    "the estimate announced while typing",
    r"\bannounced\b|\bspoken\b|\bspeaks?\b",
    near=r"\bestimate\b",
)
g_density = both(
    require("G-DENSITY", "13. Tokens", ("density is comfortable",)),
    lexicon(
        "G-DENSITY", "compact by default", r"\bcompact by default\b|\bdefaults? (?:to|is) compact\b"
    ),
)
SETTINGS_PROPS = ("section", "key", "scope")  # E11-D03:393: keys only, no values


def g_event_props(t: Texts) -> list[Finding]:
    """Lens r1 P09: §14's `chart.settings_changed` row carries exactly {section, key, scope}."""
    sec = spec_sec(t, "14. Analytics")
    for r in table_rows(section(t.spec, "14. Analytics")):
        if r[0] == "`chart.settings_changed`":
            m = re.search(r"\{([^{}]*)\}", r[1]) if len(r) > 1 else None
            props = tuple(x.split(":")[0].strip(" `") for x in m[1].split(",")) if m else ()
            if props != SETTINGS_PROPS:
                return [F("G-EVENTS", f"settings_changed carries {props}", "spec", sec)]
            return []
    return [F("G-EVENTS", "§14 has no `chart.settings_changed` row", "spec", sec)]


g_events = both(
    lexicon(
        "G-EVENTS",
        "an event carrying values",
        r"\bvalues?\b|\bparam\w*|\b(?:old|new|previous|before|after)\b",
        near=r"settings_changed",
    ),
    require("G-EVENTS", "14. Analytics", ("no audit record", 'source: "settings"')),
    g_event_props,
)


def g_frame(t: Texts) -> list[Finding]:
    """BQ-20 (M-48, M-52 … M-55): the frame register, column by column."""
    sec = spec_sec(t, FRAME_HEAD)
    boards = {r[0]: r for r in board_rows(t.spec)}
    cmps = set(re.findall(r"^### (CMP-\d{3})\b", plan("15"), MULTI))
    copy_ids = {r[0] for r in table_rows(section(t.spec, "12. Copy deck")) if r[0].startswith("W-")}
    copy_ids |= set(d03_deck())
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
        for c in re.findall(r"\b[WC]-\d+\b", fr.get("Copy", "")):
            if c not in copy_ids:
                bad.append(F("G-FRAME", f"{fid}: copy {c} is not defined", "spec", sec))
        for tok in re.findall(r"`([a-z][a-z0-9.*-]+)`", fr.get("Tokens", "")):
            if any(resolve(load_theme(th), tok) == "MISSING" for th in THEMES):
                bad.append(F("G-FRAME", f"{fid}: {tok} does not resolve", "spec", sec))
        if fr.get("Status") != "drawn":
            bad.append(F("G-FRAME", f"{fid}: status {fr.get('Status')!r}", "spec", sec))
    return bad


TOKEN_NAME = re.compile(
    r"`((?:color|space|radius|opacity|elevation|size|type|border|motion)\.[a-z0-9.*-]+)`"
)


def g_token(t: Texts) -> list[Finding]:
    """BQ-18 (X-10): every token named outside the frame register resolves, or is a routed /
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
                if name not in names and not star and name not in NOT_SHIPPED:
                    bad.append(
                        F(
                            "G-TOKEN",
                            f"{doc}:{i} {name} neither resolves nor is routed",
                            doc,
                            h2_at(text, i),
                        )
                    )
    return bad


def g_contrast(t: Texts) -> list[Finding]:
    """BQ-18 (X-7): §13 lists every pair once, with the bar of its kind; each clears its bar in
    all three themes."""
    sec = spec_sec(t, "13. Tokens")
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


def table_a_quoted_ids(hand: str) -> set[tuple[str, str, str]]:
    """Comment ids a Table A row quotes from its cited `15` line at the base (another ticket's
    ruling, copied verbatim into Old / New), keyed by the hand-off line that carries them."""
    out: set[tuple[str, str, str]] = set()
    for ln in section(hand, "Table A").split("\n"):
        if not ln.startswith("| A-"):
            continue
        m = CITE_GROUP.search(split_row(ln)[2])
        rel = cite_path(m["a"] or m["b"]) if m else None
        if not m or not rel:
            continue
        no = int(re.split(r"[–-]", m["first"])[0])
        base = (git_show(BASE, rel) or "").split("\n")
        held = base[no - 1] if 0 < no <= len(base) else ""
        out |= {("hand", ln, cid) for cid in COMMENT_ID.findall(ln) if cid in held}
    return out


def g_ruled(t: Texts) -> list[Finding]:
    """Ruling form: the RULED heading cites the ruling and the BQ list; every comment id the docs
    name is on the allow-list."""
    bad: list[Finding] = []
    head = next((ln for ln in t.spec.split("\n") if ln.startswith("## The twenty questions")), "")
    if f"comment {RULING_ID}, on the BQ list {BQ_LIST_ID}" not in head:
        bad.append(
            F(
                "G-RULED",
                "the RULED heading does not cite the ruling",
                "spec",
                "The twenty questions",
            )
        )
    quoted = table_a_quoted_ids(t.hand)
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            for cid in COMMENT_ID.findall(line):
                if cid not in RULED_IDS and (doc, line, cid) not in quoted:
                    bad.append(F("G-RULED", f"{cid} is not a ruling comment", doc, h2_at(text, i)))
    return bad


@functools.lru_cache(maxsize=1)
def merge_base() -> str:
    return git_out("merge-base", "HEAD", "origin/main").strip()


def fork_point() -> str:
    """The commit this branch forked from main (`git merge-base HEAD origin/main`), else BASE (a
    WARN): `14` / `15` / `16` / `22` move on main under other PRs, so the working tree is compared
    with the fork point, never with a fixed sha that main has left."""
    return merge_base() or BASE


@functools.lru_cache(maxsize=1)
def stray_paths() -> tuple[str, ...]:
    """Paths changed against the fork point (committed, staged, working tree or untracked) that are
    not this ticket's own."""
    ref = fork_point()
    names = git_out("diff", "--name-only", ref).split("\n")
    names += git_out("ls-files", "--others", "--exclude-standard").split("\n")
    return tuple(
        sorted(
            {
                n
                for n in names
                if n
                and n not in OWN_PATHS
                and not OWN_IMG.fullmatch(n)
                and not OWN_SHEETS.fullmatch(n)
            }
        )
    )


def g_untouched(t: Texts) -> list[Finding]:
    """BQ-3 (M-4): `14`, `15`, `16` and `22` in the working tree equal the fork point."""
    bad: list[Finding] = []
    ref = fork_point()
    for nn, text in t.plans:
        rel = cite_path(nn)
        if rel is None or text != (git_show(ref, rel) or at_base(rel)):
            bad.append(F("G-UNTOUCHED", f"`{nn}` differs from {ref[:10]}", None, None))
    bad += [F("G-UNTOUCHED", f"{p} is not this ticket's path", None, None) for p in stray_paths()]
    return bad


def g_budget(t: Texts) -> list[Finding]:
    """BQ-1 (M-5): the spec within SPEC_LINE_BUDGET lines, the hand-off within its own."""
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
    g_home,
    g_wire,
    g_live,
    g_enter,
    g_refuse,
    g_precision,
    g_haanchor,
    g_sync,
    g_partial,
    g_fetch,
    g_session,
    g_announce,
    g_density,
    g_events,
    g_ruled,
    g_pending,
    g_close,
    g_charset,
)
MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_boards,
    g_locked,
    g_arow,
    g_old,
    g_crosshair,
    g_types,
    g_base,
    g_grows,
    g_crows,
    g_parity,
    g_modes,
    g_diff,
    g_rebuild,
    g_owner,
    g_verbatim,
    g_verbatim_src,
    g_marked,
    g_keys,
    g_savestates,
    g_notice,
    g_preview,
    g_reset,
    g_guard,
    g_rbac,
    g_absent,
    g_t2,
    g_reading,
    g_esc,
    g_region,
    g_tokenuse,
    g_order,
    g_frame,
    g_token,
    g_contrast,
    g_untouched,
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
        "# E12-D05 pins (every unit of both docs): doc, region (heading path #occurrence), "
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
    p15: Callable[[str], str] | None = None
    p02: Callable[[str], str] | None = None  # edits the working-tree D02 (a hand-off target)
    patch: Callable[[], Callable[[], None]] | None = None  # moves tool state; returns the undo


def add_board(text: str, _v: Values) -> str:
    rows = [ln for ln in section(text, "0. Status").split("\n") if ln.startswith("| 10 ")]
    if not rows:
        return text
    extra = (
        "| 11 | `E12-D05 / 11 types-hc` | high-contrast twin of 02 | hc | PENDING: drawn in PR 2 |"
    )
    return text.replace(rows[0], rows[0] + "\n" + extra, 1)


def overrun(text: str, _v: Values) -> str:
    n = text.count("\n")
    return text + "filler\n" * (SPEC_LINE_BUDGET - n + 5)


PRECISION_ROW = "| Precision (decimals) | Auto · 0 · 1 · … | CMP-006 | E11-D03:253 |"
PNF_ROW = '| Point & Figure (`pnf`) | "Box size" | ticks | "Box size, ticks" | — | — | — |'

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1",
        "G-PENPOT",
        "BQ-1, BQ-20",
        spec=sub_in(
            "0. Status",
            "page `E12-D05 SCR-031 General`",
            "page `E12-D05 SCR-031 General` (https://design.example/x)",
        ),
    ),
    Mutation(
        "M-2",
        "G-UNBUILT",
        "BQ-1",
        spec=sub_in("0. Status", "**this spec is the implementation contract**", "**the spec**"),
    ),
    Mutation("M-3", "G-CITE", "BQ-1", spec=sub_in("4.1 The parity", "(D03:237)", "(D03:99999)")),
    Mutation("M-4", "G-UNTOUCHED", "BQ-1, BQ-3", p15=lambda x: x + "extra\n"),
    Mutation("M-5", "G-BUDGET", "BQ-1", spec=overrun),
    Mutation("M-6", "G-BOARDS", "BQ-1, BQ-20", spec=add_board),
    Mutation("M-7", "G-HEX", "BQ-1, BQ-18", spec=say_in("13. Tokens", "The card is #11151A.")),
    Mutation(
        "M-8",
        "G-LOCKED",
        "BQ-2",
        spec=drop_row(
            "1.3 Locked",
            "E11-D03 — the scope control (D10), the confirmed Reset (D11), the live preview"
            " (D12); precision and countdown on Scales (X-10); the chrome split (X-14); the"
            " crosshair section received here (X-7); the default interim (CG-3)",
        ),
    ),
    Mutation("M-9", "G-AROW", "BQ-3", hand=drop_row("Table A", "A-2")),
    Mutation(
        "M-10", "G-HOME", "BQ-4", spec=add_row_after("2.1 Layout", "Crosshair", PRECISION_ROW)
    ),
    Mutation(
        "M-11",
        "G-HOME",
        "BQ-4",
        spec=say_in("2.2 Crosshair", "The section hosts the drawing magnet."),
    ),
    Mutation(
        "M-12",
        "G-CROSSHAIR",
        "BQ-4",
        spec=sub_in(
            "2.2 Crosshair", "Off (default) · Weak · Strong", "Off · Weak (default) · Strong"
        ),
    ),
    Mutation("M-13", "G-TYPES", "BQ-5", spec=drop_row("3.1 The nine", "Area")),
    Mutation(
        "M-14", "G-TYPES", "BQ-5", spec=in_lines("3.1 The nine", swap_rows("Line", "Bars (OHLC)"))
    ),
    Mutation(
        "M-15",
        "G-WIRE",
        "BQ-5",
        spec=say_in("3.3 Heikin-Ashi", "The dialog sends `heikin_ashi` as the `bar_type`."),
    ),
    Mutation(
        "M-16",
        "G-BASE",
        "BQ-5",
        spec=sub_in("3.2 Baseline", "First visible close (default)", "First visible close"),
    ),
    Mutation("M-17", "G-TYPES", "BQ-5", spec=row_edit("3.1 The nine", "Line", 2, to("—"))),
    Mutation(
        "M-18",
        "G-GROWS",
        "BQ-5",
        spec=sub_in(
            "16.2",
            "**D05-G6** The volume sub-pane toggle has no design home (`11`:907–909): to E12-D09"
            " (#244). ",
            "",
        ),
    ),
    Mutation(
        "M-19",
        "G-PARITY",
        "BQ-6",
        spec=row_edit("4.1 The parity", "Volume (`volume`)", 1, to('"Volume per bar (BTC)"')),
    ),
    Mutation(
        "M-20",
        "G-PARITY",
        "BQ-6",
        spec=row_edit(
            "4.1 The parity", "Range (`range`)", 6, to('C-11 "Enter 2 to 99,999 ticks."')
        ),
    ),
    Mutation(
        "M-21", "G-MODES", "BQ-6", spec=add_row_after("4.1 The parity", "Renko (`renko`)", PNF_ROW)
    ),
    Mutation(
        "M-22",
        "G-DIFF",
        "BQ-6",
        spec=sub_in("4.1 The parity", "SCR-031 shows no Recent row (D03:237): ", ""),
    ),
    Mutation("M-23", "G-CROWS", "BQ-3, BQ-6", spec=drop_row("16.1", "D05-C7")),
    Mutation("M-24", "G-LIVE", "BQ-7", spec=say_in("5. Apply model", "The bar mode applies live.")),
    Mutation(
        "M-25",
        "G-ENTER",
        "BQ-7",
        spec=say_in("5. Apply model", "`Enter` in the field saves the dialog."),
    ),
    Mutation(
        "M-26",
        "G-REBUILD",
        "BQ-7",
        spec=sub_in("5. Apply model", 'C-30\'s "Needs a build" tag', "C-30's tag"),
    ),
    Mutation(
        "M-27",
        "G-OWNER",
        "BQ-8",
        spec=line_edit("### 3.4 Unsupported", f"PROPOSED, {OWNER_PENDING}; ", ""),
    ),
    Mutation(
        "M-28",
        "G-REFUSE",
        "BQ-8",
        spec=say_in("3.4 Unsupported", "Footprint is refused with Line."),
    ),
    Mutation(
        "M-29",
        "G-VERBATIM",
        "BQ-8, BQ-14",
        spec=sub_in(
            "3.4 Unsupported",
            "would not line up with traded prices",
            "would not match traded prices",
        ),
    ),
    Mutation(
        "M-30",
        "G-PRECISION",
        "BQ-9",
        spec=say_in("6. Precision", "Labels are formatted with `toFixed`."),
    ),
    Mutation(
        "M-31",
        "G-MARKED",
        "BQ-9",
        spec=sub_in(
            "6. Precision",
            "display only — **PROPOSED**: the docs are silent for prices",
            "display only: the docs are silent for prices",
        ),
    ),
    Mutation(
        "M-32",
        "G-HAANCHOR",
        "BQ-9",
        spec=say_in("6. Precision", "Heikin-Ashi values are offered as a drawing anchor."),
    ),
    Mutation("M-33", "G-KEYS", "BQ-10", spec=sub_in("7.1 Where", "`chart_type`", "`chartType`")),
    Mutation(
        "M-34",
        "G-SYNC",
        "BQ-10",
        spec=say_in("7.1 Where", "The chart type syncs across the sync group."),
    ),
    Mutation(
        "M-35",
        "G-SAVESTATES",
        "BQ-10, BQ-14",
        spec=drop_row("9.3 Saving", "Failed (the `PATCH /me/preferences`)"),
    ),
    Mutation(
        "M-36",
        "G-PARTIAL",
        "BQ-11",
        spec=say_in("7.3 All panels", "Volume and Delta apply the same number everywhere."),
    ),
    Mutation(
        "M-37",
        "G-PARTIAL",
        "BQ-11",
        spec=sub_in("7.3 All panels", '"Applies to 3 of 4 chart panels", ', ""),
    ),
    Mutation(
        "M-38",
        "G-NOTICE",
        "BQ-12",
        spec=sub_in("7.4 As new default", "with `Undo` and `Dismiss`", "with `Dismiss`"),
    ),
    Mutation(
        "M-39",
        "G-PREVIEW",
        "BQ-13",
        spec=sub_in(
            "8. The preview",
            'W-19, "Sample bars: not this chart" (PROPOSED; D05-G5)',
            "W-19 (D05-G5)",
        ),
    ),
    Mutation(
        "M-40", "G-FETCH", "BQ-13", spec=say_in("8. The preview", "The preview fetches the bars.")
    ),
    Mutation(
        "M-41",
        "G-RESET",
        "BQ-14",
        spec=sub_in("9.1 Reset", '"Reset General to defaults?"', '"Reset?"'),
    ),
    Mutation(
        "M-42", "G-GUARD", "BQ-14", spec=sub_in("9.2 The dirty", ", Keep editing focused (", " ((")
    ),
    Mutation(
        "M-43",
        "G-RBAC",
        "BQ-15",
        spec=sub_in("10.1 Roles", ' T2 with "Your role can\'t change settings."', " T2"),
    ),
    Mutation(
        "M-44",
        "G-ABSENT",
        "BQ-15",
        spec=sub_in(
            "10.2 States",
            "the option is absent, never offered and refused",
            "the option is shown disabled",
        ),
    ),
    Mutation(
        "M-45",
        "G-SESSION",
        "BQ-16",
        spec=say_in("2.3 Session", "The row links to the day-boundary control."),
    ),
    Mutation(
        "M-46",
        "G-ORDER",
        "BQ-17",
        spec=sub_in("11. Keyboard", "Reset all… → Cancel → Save", "Save → Cancel → Reset all…"),
    ),
    Mutation(
        "M-47",
        "G-ANNOUNCE",
        "BQ-17",
        spec=say_in("11. Keyboard", "The estimate is announced on every keystroke."),
    ),
    Mutation(
        "M-48",
        "G-FRAME",
        "BQ-18",
        spec=reg("general/populated · dark", "Tokens", appended(", `space.tabs.md`")),
    ),
    Mutation("M-49", "G-DENSITY", "BQ-18", spec=say_in("13. Tokens", "Compact by default.")),
    Mutation(
        "M-50",
        "G-EVENTS",
        "BQ-19",
        spec=say_in("14. Analytics", "`chart.settings_changed` carries the new value."),
    ),
    Mutation(
        "M-51",
        "G-EVENTS",
        "BQ-19",
        spec=sub_in("14. Analytics", "- **No audit record**, stated", "- Stated"),
    ),
    Mutation("M-52", "G-FRAME", "BQ-20", spec=reg("types/radio-list · dark", "Board", to("11"))),
    Mutation(
        "M-53", "G-FRAME", "BQ-20", spec=reg("types/radio-list · dark", "Components", to("CMP-999"))
    ),
    Mutation("M-54", "G-FRAME", "BQ-20", spec=reg("types/radio-list · dark", "Copy", to("W-99"))),
    Mutation(
        "M-55", "G-FRAME", "BQ-20", spec=reg("types/radio-list · dark", "Status", to("PENDING"))
    ),
    Mutation(
        "M-56",
        "G-TRACE",
        "BQ-1",
        spec=drop_row(
            "Acceptance-criteria trace",
            "AC3 — all panels where a symbol lacks recorded tape: which panels changed, which"
            " did not and why; never skipped silently, never blocking the whole apply",
        ),
    ),
    Mutation(
        "M-57",
        "G-BOARDS",
        "BQ-20",
        spec=sub_in("0. Status", "a canvas of frames, each frame a ", "a "),
    ),
    Mutation(
        "M-58",
        "G-READING",
        "BQ-17",
        spec=sub_in("2.1 Layout", "two columns column-major, the first", "two columns, the first"),
    ),
    Mutation(
        "M-59",
        "G-PENDING",
        "BQ-8",
        spec=say_in("5. Apply model", "Heikin-Ashi with footprint on applies live."),
    ),
    Mutation(
        "M-60",
        "G-PENDING",
        "BQ-8",
        spec=sub_in(
            "3.4 Unsupported",
            " Arrowing to another option withdraws Heikin-Ashi and removes the callout.",
            "",
        ),
    ),
    Mutation(
        "M-61",
        "G-PARTIAL",
        "BQ-11",
        spec=sub_in(
            "7.3 All panels",
            'then one line per panel, changed first, "BTCUSDT · Time 1m → Volume 50 BTC", then each'
            " unchanged panel",
            "then one line per unchanged panel",
        ),
    ),
    Mutation(
        "M-62",
        "G-PARTIAL",
        "BQ-11",
        spec=sub_in(
            "7.3 All panels",
            "the outcome shows in each panel's status strip (D02:31)",
            "the outcome shows in the dialog",
        ),
    ),
    Mutation(
        "M-63",
        "G-PARTIAL",
        "BQ-11",
        spec=sub_in("7.3 All panels", " reused for a panel (D05-C22)", " (D05-C22)"),
    ),
    Mutation(
        "M-64",
        "G-NOTICE",
        "BQ-12",
        spec=say_in("7.4 As new default", "W-13 is shown while the build runs."),
    ),
    Mutation(
        "M-65",
        "G-NOTICE",
        "BQ-12",
        spec=sub_in(
            "7.4 As new default",
            ", `null` where the leaf was not overridden (`_meta.overridden`, `22`:9826)",
            "",
        ),
    ),
    Mutation(
        "M-66",
        "G-RESET",
        "BQ-14",
        spec=sub_in(
            "9.1 Reset",
            "Both bodies name the current scope with E11-D03:273's clause, verbatim, "
            f'"{SCOPE_CLAUSE}". ',
            "",
        ),
    ),
    Mutation(
        "M-67",
        "G-RESET",
        "BQ-7, BQ-14",
        spec=row_edit(
            "9.1 Reset",
            "Reset all…",
            2,
            lambda c: c.replace('"Rebuilds the chart on Save."', '"Rebuilds the chart."'),
        ),
    ),
    Mutation(
        "M-68", "G-RESET", "BQ-14", spec=say_in("9.1 Reset", "A confirmed Reset saves at once.")
    ),
    Mutation(
        "M-69",
        "G-RESET",
        "BQ-14",
        spec=sub_in(
            "9.1 Reset",
            "Afterwards focus returns to the Reset button pressed and one",
            "Afterwards one",
        ),
    ),
    Mutation(
        "M-70",
        "G-SAVESTATES",
        "BQ-14",
        spec=drop_row("9.3 Saving", "Save with an invalid or held parameter"),
    ),
    Mutation(
        "M-71",
        "G-RBAC",
        "BQ-15",
        spec=sub_in(
            "10.1 Roles", ", the bar-mode radios and both Resets;", " and the bar-mode radios;"
        ),
    ),
    Mutation(
        "M-72",
        "G-RBAC",
        "BQ-15",
        spec=sub_in("10.1 Roles", "last only while the dialog is open", "last"),
    ),
    Mutation(
        "M-73",
        "G-T2",
        "BQ-15",
        spec=sub_in("10.2 States", "an arrow moves focus onto one without checking it, and", "and"),
    ),
    Mutation(
        "M-74", "G-ORDER", "BQ-17", spec=sub_in("11. Keyboard", "tabs → × → Chart", "tabs → Chart")
    ),
    Mutation(
        "M-75",
        "G-ESC",
        "BQ-17",
        spec=sub_in(
            "11. Keyboard",
            "the first `Esc` chooses Keep and a second one goes on",
            "`Esc` opens the prompt",
        ),
    ),
    Mutation(
        "M-76",
        "G-REGION",
        "BQ-17",
        spec=sub_in(
            "11. Keyboard",
            "speak in the panel's own polite region",
            "speak in the dialog's region",
        ),
    ),
    Mutation(
        "M-77",
        "G-CONTRAST",
        "BQ-18",
        spec=drop_row("13. Tokens", "`focus.ring` on `surface.raised`"),
    ),
    Mutation(
        "M-78", "G-TOKENUSE", "BQ-18", spec=sub_in("13. Tokens", ", never on the Save fill", "")
    ),
    Mutation(
        "M-79", "G-TOKENUSE", "BQ-18", spec=sub_in("13. Tokens", "marks only the ✕", "marks the ✕")
    ),
    Mutation(
        "M-80",
        "G-MARKED",
        "BQ-1",
        spec=sub_in("3.1 The nine", "(D06h A-1.1, PROPOSED)", "(D06h A-1.1)"),
    ),
    Mutation(
        "M-81",
        "G-MARKED",
        "BQ-1",
        spec=sub_in("8. The preview", "(PROPOSED, not in `15`:2675; E11-D03:443)", "(E11-D03:443)"),
    ),
    Mutation(
        "M-82",
        "G-MARKED",
        "BQ-1",
        spec=sub_in("3.2 Baseline", "A-1.1's PROPOSED `baseline?`", "A-1.1's `baseline?`"),
    ),
    Mutation("M-83", "G-CLOSE", "BQ-1", spec=say_in("17.3 Deviations", "PR 1 closes #241.")),
    Mutation("M-84", "G-UNTOUCHED", "BQ-3", p02=lambda x: x + "extra\n"),
    Mutation(
        "M-85",
        "G-LOCKED",
        "BQ-2",
        spec=sub_in("1.3 Locked", "D01:49–50, carried", "D01:48–49, carried"),
    ),
    Mutation(
        "M-86",
        "G-OLD",
        "BQ-3",
        hand=row_edit(
            "Table A",
            "A-5",
            3,
            lambda c: c.split(" (Superseded")[0],
        ),
    ),
    Mutation(
        "M-87",
        "G-FRAME",
        "BQ-12, BQ-20",
        spec=reg("scope/outcome · dark", "Components", to("CMP-028")),
    ),
    Mutation("M-88", "G-CROWS", "BQ-6", spec=row_edit("16.1", "D05-C7", 3, to("—"))),
    # the tool's own: the comment strip, the anchors, the allow-list, the tool-state gates
    Mutation(
        "X-1",
        "G-RULED",
        "RULED cites only 6426302306 (+ the BQ list)",
        hand=line_edit("Components:", f"comment {RULING_ID}", "comment 6426302399"),
    ),
    Mutation(
        "X-2",
        "G-ANCHOR",
        "BQ-1: an anchored value differs",
        spec=with_values(
            lambda v: sub_in("4.1 The parity", av(v, "LIM:tick.min"), "99<!--=LIM:tick.min-->")
        ),
    ),
    Mutation(
        "X-3",
        "G-ANCHOR",
        "BQ-1: a figure typed by hand",
        spec=say_in("8. The preview", "The tile is 7 px from the edge."),
    ),
    Mutation(
        "X-4",
        "G-MARKER",
        "BQ-1: a hidden comment",
        spec=sub_in("1.4 Rules", "- **R-2", "- <!-- the bar mode applies live -->**R-2"),
    ),
    Mutation(
        "X-5",
        "G-MARKER",
        "BQ-1: an unclosed comment",
        spec=say_in("18. Summary", "<!-- an unclosed note"),
    ),
    Mutation(
        "X-6",
        "G-ANCHOR",
        "BQ-1: a placeholder left unfilled",
        spec=say_in("14. Analytics", "The cap is {{COUNT:pairs}}."),
    ),
    Mutation(
        "X-7",
        "G-CONTRAST",
        "BQ-18: marks clear the bar",
        patch=pushed(MARK_MIN_OVERRIDE, Decimal(20)),
    ),
    Mutation(
        "X-8",
        "G-OLD",
        "BQ-3: Old cells verbatim at the base",
        hand=row_edit("Table A", "A-12", 3, to("`color.action.selected`, `space.inset.*`.")),
    ),
    Mutation(
        "X-9",
        "G-TOKEN",
        "BQ-18: names resolve or are routed",
        spec=say_in("13. Tokens", "Errors use `color.text.error`."),
    ),
    Mutation(
        "X-10",
        "G-CHARSET",
        "lens 2 #33: a superscript cite folds to ASCII in the pins",
        spec=sub_in("3.2 Baseline", "(E30-D02:131,", "(E30-D02:¹³¹,"),
    ),
    Mutation(
        "X-11",
        "G-CHARSET",
        "lens 2 #32: a full-width digit in a cite",
        spec=sub_in(
            "1.4 Rules", "nothing commits on blur (D03:48)", "nothing commits on blur (D03:４８)"
        ),
    ),
    Mutation(
        "X-12",
        "G-CHARSET",
        "lens 2 #36: a no-break space",
        spec=sub_in("1.2 Method", "Desk work at the base", "Desk work at\u00a0the base"),
    ),
    Mutation(
        "X-13",
        "G-CHARSET",
        "lens 2 #35: a CR line ending",
        spec=sub_in("18. Summary", "(at most ten lines)\n", "(at most ten lines)\r\n"),
    ),
    Mutation(
        "X-14",
        "G-CHARSET",
        "lens 2 #34: a trailing two-space hard break",
        spec=in_lines(
            "1.2 Method", lambda ls: [x + "  " if x.startswith("Desk work") else x for x in ls]
        ),
    ),
    Mutation(
        "X-15",
        "G-ANCHOR",
        "lens 2 #26: a digit typed before an anchored value",
        spec=with_values(
            lambda v: sub_in(
                "5. Apply model",
                "within " + av(v, "BUDGET:type-switch"),
                "within 1" + av(v, "BUDGET:type-switch"),
            )
        ),
    ),
    # PR #4669 text lens r1: the six paraphrases the pins alone stopped; each now FAILs by its gate
    Mutation(
        "X-16",
        "G-HOME",
        "lens r1 P01: a Decimals radio group in §2.1's Session row",
        spec=row_edit(
            "2.1 Layout",
            "Session",
            1,
            to('the read-only row, a "Decimals" radio group and the pointer to Scales'),
        ),
    ),
    Mutation(
        "X-17",
        "G-ENTER",
        "lens r1 P02: `Enter` commits the dialog",
        spec=sub_in(
            "5. Apply model",
            "validates and, when invalid, speaks the message once; it never saves (R-2)",
            "validates, then commits the dialog (R-2)",
        ),
    ),
    Mutation(
        "X-18",
        "G-WIRE",
        "lens r1 P05: sent as `bar_type` `heikin_ashi` in §3.1's Kind cell",
        spec=row_edit(
            "3.1 The nine",
            "Heikin-Ashi",
            3,
            to("client transform over time bars, sent as `bar_type` `heikin_ashi`"),
        ),
    ),
    Mutation(
        "X-19",
        "G-EVENTS",
        "lens r1 P09: a `param` property on `chart.settings_changed`",
        spec=row_edit(
            "14. Analytics",
            "`chart.settings_changed`",
            1,
            lambda c: c.replace("key, scope}", "key, scope, param}"),
        ),
    ),
    Mutation(
        "X-20",
        "G-RESET",
        "lens r1 P10: W-25 without its scope",
        spec=row_edit(
            "12. Copy deck",
            "W-25",
            2,
            to("General reset to defaults · All chart settings reset to defaults"),
        ),
    ),
    Mutation(
        "X-21",
        "G-LIVE",
        "lens r1 P20: **live** in §5's bar-mode row",
        spec=row_edit("5. Apply model", "Bar mode, parameter", 1, to("**live**")),
    ),
    Mutation(
        "X-22",
        "G-OLD",
        "Table A refresh: a closed marker citing a PR that never touched `15`",
        hand=row_edit("Table A", "A-11", 3, to("applied by #4718 (closed)")),
    ),
    Mutation(
        "X-23",
        "G-OLD",
        "Table A refresh: a closed marker on a row whose New is not on `15`",
        hand=row_edit("Table A", "A-12", 3, to("applied by #4719 (closed)")),
    ),
    Mutation(
        "X-24",
        "G-OLD",
        "Table A refresh: a near-miss closed marker",
        hand=row_edit("Table A", "A-11", 3, to("closed by #4719")),
    ),
    # one per pin class (G-RULED-PIN only)
    Mutation(
        "P-1",
        "G-RULED-PIN",
        "a frame row changed",
        spec=reg("preview/live · dark", "State", to("a chart type, live (sic)")),
    ),
    Mutation(
        "P-2",
        "G-RULED-PIN",
        "a frame row moved",
        spec=in_lines(FRAME_HEAD, swap_rows("`preview/live · dark`", "`preview/cached · dark`")),
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
        "P-5", "G-RULED-PIN", "a sentence deleted", spec=in_lines("1.4 Rules", drop_line("- **R-6"))
    ),
    Mutation(
        "P-6",
        "G-RULED-PIN",
        "a new heading",
        spec=squeezed(prose_at("3.3 Heikin-Ashi", "### 3.6 Notes\n\nSee §3.1."), 6),
    ),
    Mutation("P-7", "G-RULED-PIN", "blank lines squeezed", spec=squeezed(None, 3)),
    Mutation(
        "P-8",
        "G-RULED-PIN",
        "a hand-off row changed",
        hand=row_edit("§D Storybook", "CMP-069 InfoPanel", 1, appended(" (cited)")),
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
    Mutation(
        "P-11", "G-RULED-PIN", "a duplicated section", spec=squeezed(shadow("3.3 Heikin-Ashi"), 6)
    ),
    # probes that must trip nothing
    Mutation(
        "N-1",
        "",
        "Prettier re-pads a table row",
        spec=in_lines(
            FRAME_HEAD,
            lambda ls: [
                re.sub(r" {2,}", " ", x) if "`preview/live · dark`" in x else x for x in ls
            ],
        ),
    ),
)


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def plan_paths() -> tuple[tuple[str, Path], ...]:
    """The working-tree files G-UNTOUCHED compares: `14`, `15`, `16`, `22` and UNTOUCHED_DOCS."""
    out = []
    for nn in (*UNTOUCHED, *UNTOUCHED_DOCS):
        rel = cite_path(nn)
        if rel is None:
            raise SystemExit(f"FAIL parse: docs/plan/{nn}-* missing")
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
    lines.append(f"  fence probe: {'ok' if not probe else 'FAIL'}")
    lines += [f"    {x}" for x in probe]
    ok = ok and not probe
    listed = [r[0] for r in table_rows(section(spec_f, MUTATION_HEAD)) if r[0].startswith("M-")]
    built = [mu.mid for mu in MUTATIONS if mu.mid.startswith("M-")]
    if listed != built:
        ok = False
        lines.append(
            f"  §15.2 lists {len(listed)} M-rows, the tool builds {len(built)}: they differ"
        )
    pristine = digest_texts(spec_f, hand_f, *(x for _n, x in plans))
    for mu in MUTATIONS:
        s = mu.spec(spec_f, values) if mu.spec else spec_f
        h = mu.hand(hand_f, values) if mu.hand else hand_f
        p15, d02 = dict(plans)["15"], dict(plans)["D02"]
        q = mu.p15(p15) if mu.p15 else p15
        q2 = mu.p02(d02) if mu.p02 else d02
        if (s, h, q, q2) == (spec_f, hand_f, p15, d02) and mu.patch is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        edited = {"15": q, "D02": q2}
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
            f"{'' if restored else ', NOT RESTORED'}) — {first}"
        )
        if not hit:
            lines += [f"      new: {x[:200]}" for x in new]
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
    ap = argparse.ArgumentParser(description="E12-D05 settings audit (module docstring)")
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
        print(f"--self-test: {'ok' if ok else 'FAIL'} — {len(MUTATIONS)} mutations in memory")
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
        print(f"## E12-D05 audit of {shown} (+ the hand-off) at base {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(notes))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK — every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(notes)} NOTE, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
