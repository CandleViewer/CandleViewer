#!/usr/bin/env python3
"""E12-D06 (#202) audit: the price-series visual language (spec + hand-off).

Standalone, offline, stdlib only; it executes no repo code and runs under `python -I`. It reads,
AS TEXT at the pinned base `89fd1f1555` (`git show`): the token JSON (`themes.json` layering:
dark = primitives + semantic-dark, light = + semantic-light, hc = + semantic-hc), the plan texts
`05`, `11`, `14`, `15`, `16`, `26`, the ticket JSON (`docs/plan/backlog/E12.json`), the merged
design docs the spec cites, the E11-D05 tool's JND floor and the recorded fixtures; then this
ticket's spec and hand-off from the working tree, and the working-tree `14`, `15`, `16`, `26`
(which must equal the base).

1. **Values (RULED 6415375587, BQ-1).** Every `{{KIND:key}}` outside a code span is COMPUTED:
   GEOM (the body ladder `clamp(roundHalfUp(0.7 s), 1, 35)` odd-forced from 4, the wick weights
   `max(1, round(body / 24))` and twice that (on `min(w, 35)` for an equi / delta bar of drawn
   width w), the OHLC ticks `clamp(floor(body / 2), 1, floor((s - 3) / 2))` drawn from s = 5,
   the equi / delta width `clamp(roundHalfUp(14 r), 6, 48)`, doji, zero-range `max(body, 3)` x 2,
   the notch, the P&F floor), LADDER and TIER (the sample steps on `26`'s tiers and hysteresis,
   parsed at the base), TINT (opaque `a c + (1 - a) canvas` per theme), HEX (every bound token in
   dark / light / hc), CONTRAST (WCAG 2.x), CVD (CIE76 ΔE after the Brettel / Viénot projection,
   minimum over the three themes; greyscale as the CIELAB L* gap), COUNT and BUDGET (parsed from
   the cited texts and the docs' own tables). `color.chart.line` is CHOSEN here (RULED BQ-17):
   among the chromatic primitives (a hue, A-12), the one that clears 3:1 on the canvas in all
   three themes with the largest minimum ΔE76 (three simulations, three themes) from
   `color.order.line`, `color.focus.ring`, `color.candle.up` / `.down` and `color.cvd.buy` /
   `.sell`. `--fill` writes `VALUE<!--=KIND:key-->`; `--check` re-derives every anchored value and
   FAILs on a difference, a `{{` left outside a code span, a hand-typed figure with a unit or a
   hand-typed hex.
2. **The comment strip (RULED BQ-1 a).** One pattern over the whole text, `re.DOTALL`: `<!--`
   closes at `-->` or `--!>`, `<!-->` and `<!--->` close at once, and an unclosed comment runs to
   the end. `_HIDDEN`, the marker rule (G-MARKER: every comment is a value anchor the tool
   computes) and the clause split all use it; the lexicon and a11y gates read rendered text only.
3. **Cites.** Every `NN`:line, `D01`/`D02`/`D03`/`ENG`:line and `Exx-Dyy`:line cite is read at
   the base (FAIL when the line is gone or blank; WARN when it drifted at `origin/main`), and the
   load-bearing fragments in CITED must sit on the cited line.
4. **Gates.** Lexicon gates first (each reads rows and prose after the comment strip, NFKC, markup
   dropped, dashes to spaces and lower case; a claim is read per clause, split at "; ", " — " and
   a sentence end; a negation covers its own term within five words and a list coordinated after
   it; quoted copy and §17.2's mutation rows are not claims), then the measured gates, then the
   pins. Each gate reports at most one FAIL line and the section(s) it found the problem in.
5. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over EVERY unit of both docs, in
   RULED_PIN_TXT (`e12_d06_ruled_pins.txt`, committed): each heading, table row (by its lead
   cell), rule line, prose sentence (`s<k>`) and fenced block, by doc, region (heading path plus
   occurrence `#n`), location and exact text (NFKC, whitespace collapsed; a fenced block is
   pinned verbatim, its fence kind and length read from the marker after the indent). Anchored
   values are pinned with their values cut out (G-ANCHOR re-derives them). Each region pins its
   line shape, one tag per line (`.` blank, `h` heading, `t` row, `r` rule, `b` bullet, `n`
   numbered item, `p` prose, `f` fence), a prose, bullet or numbered tag followed by its sentence
   count and any tag led by `>n` for an n-column indent, so squeezing blank lines, turning a
   bullet into prose, moving a sentence across a line, paragraph or table boundary (order kept)
   or indenting a line (a nested bullet, a code block) changes a pin. A unit changed, moved, duplicated, deleted or added FAILs by location; a
   repeated heading is a duplicated region and a repeated location FAILs (the first copy is
   kept), so a shadow copy cannot mask an edit. `--repin-ruled` is the only writer (it refuses
   while a placeholder is unfilled); `--check` writes nothing. NOTE demotion: when a lexicon or
   measured gate already FAILs a section, the pin findings of that section print as NOTE lines,
   so one wrong form yields one FAIL.
6. **--selftest** (alias `--self-test`) applies every §17.2 mutation M-1 … M-54 in memory, plus
   the tool's own X-n (the RULED allow-list, the predecessor shingle, the dash meanings, the
   comment strip, the anchors, the tool-state gates) and P-n (one per pin class), with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names (the
   N-n probes must add none), and every text is restored byte-identically (sha256 in memory and
   on disk). It also runs the CVD port's pinned self-test and the fence probe.

Usage (from the repo root):
  python3 -I docs/design/_tools/e12_d06_series_audit.py --check [--fill] [--json]
  python3 -I docs/design/_tools/e12_d06_series_audit.py --selftest
  python3 -I docs/design/_tools/e12_d06_series_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import difflib
import functools
import hashlib
import json
import math
import re
import statistics
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "89fd1f1555"  # every cite was read here (the spec's Inputs line)
HEAD = "origin/main"  # drift is reported against this ref (WARN, never FAIL)
MULTI = re.MULTILINE

SPEC_REL = "docs/design/E12/E12-D06.md"
HAND_REL = "docs/design/E12/E12-D06-handoff.md"
RULED_PIN_TXT = "docs/design/_tools/e12_d06_ruled_pins.txt"
TICKETS_REL = "docs/plan/backlog/E12.json"
DS_SRC_REL = "packages/ui/tokens"
ENG_REL = "apps/web/src/features/appearance/chartColorMode.ts"
JND_REL = "docs/design/_tools/e11_d05_ds_audit.py"
KLINE_RELS = tuple(
    f"packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page{i}.json" for i in range(3)
)
TRADE_REL = "packages/fixtures/bybit/2026-10-05/ws/clean_publicTrade_BTCUSDT.jsonl"
UNTOUCHED = ("14", "15", "16", "26")  # RULED BQ-2: never edited by this ticket
CITE_FILES: dict[str, str] = {
    "D01": "docs/design/E12/E12-D01.md",
    "D02": "docs/design/E12/E12-D02.md",
    "D03": "docs/design/E12/E12-D03.md",
    "ENG": ENG_REL,
}
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
SEMANTIC = ("semantic-dark", "semantic-light", "semantic-hc")
SIMS = ("protanopia", "deuteranopia", "tritanopia")
SIM_KEY = {"protanopia": "protan", "deuteranopia": "deutan", "tritanopia": "tritan"}

# ---- the ruling and the fixed facts
RULING_ID = "6415375587"
BQ_LIST_ID = "6415040959"
RULED_IDS = (RULING_ID, BQ_LIST_ID)  # the allow-list: every comment id the docs may cite
PREDECESSOR = "#2324"  # the closed, unmerged first attempt: named once in §0, never quoted
# the predecessor's last commit, read ONLY to prove that no run of its text is quoted (G-PREDECESSOR)
PREDECESSOR_REF = "e1b08be2e9"
PREDECESSOR_REL = "docs/design/E12/E12-D06.md"
SHINGLE = 10  # words: a run this long shared with the predecessor is a quote
MAX_BOARDS = 10  # RULED BQ-20 (lever 4): at most ten boards
TWIN_SHARE = Fraction(1, 3)  # twins at most a third of the boards (lever 4)
SPEC_LINE_BUDGET = 600  # standing condition: "≈600 lines"
HAND_LINE_BUDGET = 150  # the hand-off's budget (the spec's §17 states it)
REF_DPR = 2  # RULED BQ-4: the 2560 x 1440 reference is the 1280 x 720 layout at DPR 2

# ---- the spec's own decisions (the BQ list's defaults, RULED 6415375587), in CSS px unless noted
DESIGN: dict[str, str] = {
    "body.factor": "0.7",  # BQ-5: body = clamp(roundHalfUp(0.7 s), 1, 35)
    "body.min": "1",
    "body.cap": "35",  # BQ-5: the cap C-row against T Tech's example (D06-C1)
    "body.odd-from": "4",  # an even body ≥ 4 is forced odd so the wick sits on the centre column
    "wick.divisor": "24",  # BQ-5: wick_up = max(1, round(body / 24))
    "outline": "1",  # the up body's outline (a hairline)
    "up.outline-min": "2",  # BQ-8: outline-only where the body is ≥ 2 px, else the up span
    "ohlc.tick-min": "1",  # ticks clamp(floor(body / 2), 1, floor((s - 3) / 2)): inside the slot
    "ohlc.gap": "1",  # the free column an OHLC bar leaves in its slot (extent <= s - 1)
    "line.stroke": "2",
    "line.disc-r": "3.5",
    "dash.on": "1",  # BQ-9: dash.1-1, PROPOSED (A-14)
    "dash.off": "1",
    "dot": "1",  # BQ-13: the L1 / L2 neutral dot
    "ring.weight": "1",  # BQ-11: the static dash.2-2 ring, a hairline
    "ring.offset": "1",  # BQ-11: 1 px outside the mark
    "corrected.square": "3",  # BQ-11: the 3 x 3 px square
    "corrected.lift": "2",  # BQ-11: 2 px above the high
    "doji.h": "2",  # BQ-13
    "doji.h-small": "1",
    "doji.small-below": "8",
    "zero.w-min": "3",  # BQ-13: max(body, 3)
    "equi.factor": "14",  # BQ-14: w0 = clamp(roundHalfUp(14 r), 6, 48)
    "equi.min": "6",
    "equi.cap": "48",
    "equi.gap": "1",
    "notch.w": "5",  # BQ-14: the 5 x 3 px cap notch
    "notch.h": "3",
    "delta.label-slot": "24",  # BQ-14: signed labels only where the slot is ≥ 24 px
    "axis.label-thin": "64",  # BQ-15: open-time labels thinned at 64 px
    "pnf.stroke": "1.5",  # BQ-15: the held P&F specimen
    "pnf.min-body": "5",
    "pnf.min-h": "6",
    "vol.height-ratio": "0.2",  # BQ-16
}
TINTS = {"body": "42", "area": "16", "baseline": "22"}  # BQ-17: opaque tints, percent of the ink
SAMPLES = ("12", "6", "3", "1.5", "0.6")  # BQ-7: one sample step inside each of the five bands
BANDS = ((8, None), (4, 8), (2, 4), (1, 2), (None, 1))  # T Scope's bands, [lo, hi) in CSS px
CVD_L1_SAMPLE = "2"  # BQ-19: the L1 density of board 07 (s = 12 L0, 2 L1, 0.6 L2)
QUADS = {"candle": 2, "ohlc": 3}  # body + wick; stem + two ticks (4 vertices per quad)
EQUI_BYTES = {"cumulative x (float32)": 4, "w0 (uint8)": 1}  # BQ-14: + B per bar
LINE_NEIGHBOURS = (
    "color.order.line",
    "color.focus.ring",
    "color.candle.up",
    "color.candle.down",
    "color.cvd.buy",
    "color.cvd.sell",
)
NEUTRAL_FAMILIES = ("palette.neutral.", "palette.light.neutral.", "palette.white", "palette.black")
# the CVD port's pinned self-test (RULED BQ-19): two known hex inputs and their simulations,
# computed ONCE with `docs/research/_tools/cvd_simulate.py` at the base (protan, deutan, tritan)
CVD_PINNED = {
    "#2EBD59": ("#B4B458", "#A3A35D", "#8E8EFF"),
    "#E5484D": ("#6B6B4E", "#8F8F44", "#ADAD00"),
}
# load-bearing fragments: (cite id, line at the base, text the line must hold)
CITED: tuple[tuple[str, int, str], ...] = (
    ("26", 196, "[0.05, 200]"),
    ("26", 205, "`barSpacing ≥ 3 px` → L0; `≥ 1.5 px` → L1"),
    ("26", 205, "L1 bodies only"),
    ("26", 212, "min-low, max-high, first-open, last-close"),
    ("26", 214, "±15 %"),
    ("26", 301, "1 instanced quad for bodies + 1 for wicks"),
    ("26", 312, "≤ 18 draw calls per pane"),
    ("26", 528, "lodCandles"),
    ("14", 717, "2560×1440 with 100 k bars"),
    ("14", 717, "≤450 MB per chart panel"),
    ("14", 732, "never the hollow-candle encoding"),
    ("14", 736, "Not recorded 17:02–09:14 UTC: no order flow"),
    ("14", 736, "Series restarted 09:15 UTC"),
    ("14", 737, "L1 keeps hairline wicks"),
    ("05", 125, "≥4.5:1"),
    ("05", 128, "3:1 against the chart background"),
    ("D02", 94, "20 bars per CSS pixel"),
    ("D02", 276, "No bars for 17:02–09:14 UTC"),
    ("E06-D03", 87, "**60 rows"),
    ("E06-D03", 87, "Cap stays 200 rows"),
    ("E11-D05", 315, "`pattern.hatch.gap`"),
    ("E11-D05", 338, "`dash.2-2` | the forming-bar ring"),
    ("E11-D05", 339, "`dash.4-3` | `pattern.dashed.estimated`"),
)

PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
HEXLIT = re.compile(r"(?<![\w&])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")
FIGURE = re.compile(
    r"(?<![\w.,:#/>{-])(\d+(?:[.,]\d+)*)\s?(ms|s|hz|px|%|:1)(?![\w])", re.IGNORECASE
)
CITE_GROUP = re.compile(
    r"(?:`(?P<a>[A-Za-z0-9._/-]+)`|(?P<b>\b(?:D0[123]|ENG|E\d\d-D\d\d)\b)) ?"
    r":(?P<first>\d+(?:[–-]\d+)?)(?P<more>(?:(?:\s*\([^()\n]*\))?,\s*:\d+(?:[–-]\d+)?)*)"
)
URL = re.compile(r"\bhttps?://|\bwww\.[a-z]", re.IGNORECASE)
COMMENT_ID = re.compile(r"(?<![\w-])(\d{8,})(?![\w-])")

Values = dict[str, str]
Fetch = Callable[[str, str], str | None]
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
    if " | " not in text:
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


MUTATION_HEAD = "17.2 The mutation list"  # its rows describe the violations they plant


def lex_units(doc: str, text: str) -> list[LexUnit]:
    """Every unit a lexicon gate reads, rendered: each table row (cells joined by " | "), each
    bullet or numbered item, each paragraph and each heading, with its `##` section. Skipped: the
    spec's §17.2 rows (they name the violations they plant) and Table A's Old cells in the
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


def show_tenths(x: float) -> str:
    """ΔE76 and ΔL* to one decimal, truncated (never rounded up across a floor; §2)."""
    return f"{math.floor(x * 10 + 1e-9) / 10:.1f}"


def mix(c: str, under: str, pct: str) -> str:
    """The opaque tint `a c + (1 - a) under` per sRGB channel, rounded half up."""
    a = Decimal(pct) / 100
    out = []
    for x, y in zip(rgb(c), rgb(under), strict=True):
        v = (a * x + (1 - a) * y).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        out.append(f"{int(v):02X}")
    return "#" + "".join(out)


# The Brettel (1997) / Viénot projection, carried as constants (RULED BQ-19: no import).
# Provenance: `docs/research/_tools/cvd_simulate.py` at 89fd1f1555 (RGB_TO_LMS, LMS_TO_RGB,
# PROJECTIONS, srgb/linear transfer and the rounding of `rgb_to_hex`); CVD_PINNED is the self-test.
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


def linear_to_srgb(c: float) -> float:
    s = c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
    return max(0.0, min(1.0, s)) * 255.0


def simulate(hex6: str, deficiency: str) -> str:
    lin = tuple(srgb_to_linear(v) for v in rgb(hex6))
    lms = matvec(flat3(RGB_TO_LMS), (lin[0], lin[1], lin[2]))
    lin2 = matvec(flat3(LMS_TO_RGB), matvec(PROJECTIONS[deficiency], lms))
    return "#" + "".join(f"{max(0, min(255, round(linear_to_srgb(c)))):02X}" for c in lin2)


def lab(hex6: str) -> tuple[float, float, float]:
    r, g, b = (srgb_to_linear(v) for v in rgb(hex6))
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e76(a: str, b: str) -> float:
    la, lb = lab(a), lab(b)
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(la, lb, strict=True)))


def cvd_port_problems() -> list[str]:
    """The pinned self-test: two known hex inputs simulate to the values the research tool gave."""
    bad: list[str] = []
    for src, want in CVD_PINNED.items():
        got = tuple(simulate(src, s) for s in SIMS)
        if got != want:
            bad.append(f"{src} simulates to {got}, pinned {want}")
    return bad


# ---------------------------------------------------------------------------- geometry


def dec(x: str | float | Decimal) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def rhu(x: Decimal) -> int:
    """roundHalfUp."""
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_d(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_FLOOR))


def fmt(x: Decimal | float | str) -> str:
    """A number as written: no trailing zeros, no exponent."""
    d = dec(x).normalize()
    s = format(d, "f")
    return s


def g(key: str) -> Decimal:
    return dec(DESIGN[key])


def body_px(s: Decimal) -> int:
    """§3.1: clamp(roundHalfUp(0.7 s), 1, 35), forced odd from 4: an even width takes the next
    odd value when it is ≤ s − 1, else the previous one."""
    b = max(int(g("body.min")), min(int(g("body.cap")), rhu(g("body.factor") * s)))
    if b >= int(g("body.odd-from")) and b % 2 == 0:
        b = b + 1 if b + 1 <= s - 1 else b - 1
    return b


def wick_up_px(body: int) -> int:
    return max(1, rhu(dec(body) / g("wick.divisor")))


def ohlc_slot_less() -> int:
    """The columns an OHLC bar keeps off its ticks: the 2 px down stem plus the free column."""
    return 2 * wick_up_px(int(g("body.cap"))) + int(g("ohlc.gap"))


def tick_px(body: int, s: Decimal, slot_less: int | None = None) -> int:
    """§3.2: clamp(floor(body / 2), tick-min, floor((s - slot_less) / 2)); 0 = no room for a tick
    (below the OHLC tick floor the bar draws the candle mark)."""
    less = ohlc_slot_less() if slot_less is None else slot_less
    room = floor_d((s - less) / 2)
    want = max(int(g("ohlc.tick-min")), floor_d(dec(body) / 2))
    return min(want, room) if room >= int(g("ohlc.tick-min")) else 0


def equi_wick_up_px(w: int, clamp: int | None) -> int:
    """§10.1: the §3.1 formula on min(w, clamp), w the drawn width k × w0 (None: no clamp)."""
    return wick_up_px(min(w, clamp) if clamp is not None else w)


def equi_width_max() -> int:
    """The widest drawn equi / delta bar: w0's cap × the largest zoom scale k = (s − gap) / mean
    w0, at the widest spacing and the narrowest mean."""
    t = tiers()
    k = (t.s_max - g("equi.gap")) / g("equi.min")
    return int((g("equi.cap") * k).to_integral_value(rounding=ROUND_FLOOR))


def equi_w0(r: Decimal) -> int:
    return max(int(g("equi.min")), min(int(g("equi.cap")), rhu(g("equi.factor") * r)))


def doji_h(s: Decimal) -> int:
    return int(g("doji.h-small")) if s < g("doji.small-below") else int(g("doji.h"))


@dataclass(frozen=True)
class Tiers:
    l0: Decimal
    l1: Decimal
    hyst: Decimal
    s_min: Decimal
    s_max: Decimal


@functools.lru_cache(maxsize=1)
def tiers() -> Tiers:
    """`26`:205 (thresholds), :214 (hysteresis) and :196 (the barSpacing clamp), at the base."""
    row = base_line("26", 205)
    l0 = grab(r"`barSpacing ≥ ([\d.]+) px` → L0", row, "26:205 L0")
    l1 = grab(r"`≥ ([\d.]+) px` → L1", row, "26:205 L1")
    hyst = grab(r"±(\d+) %", base_line("26", 214), "26:214 hysteresis")
    lo, hi = re.findall(r"\[([\d.]+), ([\d.]+)\]", base_line("26", 196))[0]
    return Tiers(dec(l0), dec(l1), dec(hyst), dec(lo), dec(hi))


def tier_of(s: Decimal) -> str:
    t = tiers()
    return "L0" if s >= t.l0 else "L1" if s >= t.l1 else "L2"


def tier_from_above(s: Decimal) -> str:
    """Reached by zooming out from a finer tier: each tier holds down to its coarser edge."""
    t, h = tiers(), tiers().hyst / 100
    return "L0" if s >= t.l0 * (1 - h) else "L1" if s >= t.l1 * (1 - h) else "L2"


def tier_from_below(s: Decimal) -> str:
    """Reached by zooming in from a coarser tier: each tier holds up to the finer edge above it."""
    t, h = tiers(), tiers().hyst / 100
    return "L0" if s >= t.l0 * (1 + h) else "L1" if s >= t.l1 * (1 + h) else "L2"


def grid(lo: Decimal, hi: Decimal, step: Decimal = Decimal("0.01")) -> list[Decimal]:
    out, x = [], lo
    while x < hi:
        out.append(x)
        x += step
    return out


def ticket_example() -> tuple[str, str]:
    """T Tech's example cap and wick divisor, from the ticket body at the base."""
    for t in json.loads(at_base(TICKETS_REL)):
        if isinstance(t, dict) and t.get("key") == "E12-D06":
            body = str(t.get("body", ""))
            cap = grab(r"clamp\(round\(spacing × 0\.7\), 1, (\d+)\) px", body, "T Tech cap")
            div = grab(r"round\(bodyWidth / (\d+)\)", body, "T Tech wick")
            return cap, div
    raise SystemExit("FAIL parse: E12-D06 not in the ticket JSON")


# ---------------------------------------------------------------------------- spec structure

FR_COLS = ("Frame", "Board", "Type", "Tier", "Channel", "Ink", "Dash", "Words", "Status")
DIR_COLS = ("Type", "L0", "L1", "L2")
TYPE_COLS = ("Type", "Geometry", "Weight", "Ink")
FRAME_HEAD = "17.1 The frame register"


def frames(spec: str) -> list[dict[str, str]]:
    return [dict(zip(FR_COLS, r, strict=False)) for r in table_rows(section(spec, FRAME_HEAD))]


def frame_id(cell: str) -> str:
    return cell.strip("`* ")


def board_rows(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "0. Status")) if re.fullmatch(r"\d{2}", r[0])]


def is_twin(row: list[str]) -> bool:
    return re.search(r"\btwin of\b", row[2] if len(row) > 2 else "") is not None


def direction_rows(spec: str) -> list[dict[str, str]]:
    block = section(spec, "4.1 The direction table")
    return [dict(zip(DIR_COLS, r, strict=False)) for r in table_rows(block)]


def type_rows(spec: str) -> list[dict[str, str]]:
    return [dict(zip(TYPE_COLS, r, strict=False)) for r in table_rows(section(spec, "3.2 The"))]


def table_a(hand: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in table_rows(section(hand, "Table A")):
        out.setdefault(row_key(r[0]), r)
    return out


def story_items(cell: str) -> list[str]:
    return [x.strip() for x in re.split(r"\s·\s", cell) if x.strip()]


def top_commas(cell: str) -> list[str]:
    """Split at commas outside parentheses."""
    out, depth, cur = [], 0, ""
    for ch in cell:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [x for x in [*out, cur.strip()] if x]


def story_counts(hand: str) -> dict[str, int]:
    rows = {row_key(r[0]).split(" ")[0]: r for r in table_rows(section(hand, "§D Storybook"))}
    a6 = table_a(hand).get("A-6.1", ["", "", "", "", ""])
    added = rows.get("CMP-226", ["", ""])[1]
    return {
        "cmp181": len(story_items(rows.get("CMP-181", ["", ""])[1])),
        "cmp222": len(top_commas(a6[4] if len(a6) > 4 else "")),
        "cmp226-added": len(top_commas(added.split("+", 1)[1])) if "+" in added else 0,
    }


# ---------------------------------------------------------------------------- values


def theme_hex(theme: str, name: str) -> str:
    return hex_of(load_theme(theme), name)


def theme_keys() -> tuple[str, ...]:
    return tuple(THEMES)


def mark_min() -> Decimal:
    return dec(grab(r"(\d+(?:\.\d+)?):1 against the chart background", base_line("05", 128), "05"))


def text_min() -> Decimal:
    return dec(grab(r"≥(\d+(?:\.\d+)?):1 against their background", base_line("05", 125), "05"))


MARK_MIN_OVERRIDE: list[Decimal] = []  # the self-test's tool-state lever for G-CONTRAST
JND_OVERRIDE: list[float] = []  # the self-test's tool-state lever for G-CVD
FIXTURE_OVERRIDE: list[str] = []  # the self-test's tool-state lever for G-FIXTURE


def bar_mark() -> Decimal:
    return MARK_MIN_OVERRIDE[-1] if MARK_MIN_OVERRIDE else mark_min()


def jnd_floor() -> float:
    if JND_OVERRIDE:
        return JND_OVERRIDE[-1]
    return float(grab(r"^JND = ([\d.]+)", at_base(JND_REL), "E11-D05 JND"))


@functools.lru_cache(maxsize=1)
def line_choice() -> tuple[str, list[tuple[float, str, str]]]:
    """RULED BQ-17: the chromatic primitive that clears the mark minimum on the canvas in all three
    themes with the largest minimum ΔE76 (three simulations x three themes) from the neighbours;
    the ranking's head for `--json`."""
    floor = float(mark_min())
    ranked: list[tuple[float, str, str]] = []
    for name, v in sorted(token_file("primitives").items()):
        if not isinstance(v, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            continue
        if name.startswith(NEUTRAL_FAMILIES):
            continue
        h = v.upper()
        if any(contrast(h, theme_hex(t, "color.surface.canvas")) < floor for t in THEMES):
            continue
        score = min(
            delta_e76(simulate(h, s), simulate(theme_hex(t, n), s))
            for t in THEMES
            for n in LINE_NEIGHBOURS
            for s in SIMS
        )
        ranked.append((round(score, 3), name, h))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    if not ranked:
        raise SystemExit("FAIL color.chart.line: no chromatic primitive clears the minimum")
    return ranked[0][1], ranked[:5]


def inks(theme: str) -> dict[str, str]:
    """The series inks of one theme, `color.chart.line` the chosen primitive."""
    tok = load_theme(theme)
    out = {
        k: hex_of(tok, f"color.{k}")
        for k in ("candle.up", "candle.down", "candle.wick", "surface.canvas", "axis.text")
    }
    out |= {n: hex_of(tok, n) for n in LINE_NEIGHBOURS}
    out["chart.line"] = hex_of(token_file("primitives"), line_choice()[0])
    canvas = out["surface.canvas"]
    out["tint.up"] = mix(out["candle.up"], canvas, TINTS["body"])
    out["tint.down"] = mix(out["candle.down"], canvas, TINTS["body"])
    out["tint.neutral"] = mix(out["candle.wick"], canvas, TINTS["body"])
    return out


CVD_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "up-down.solid": (("candle.up", "candle.down"),),
    "tint-down": (("tint.up", "candle.down"),),
    "outline-down": (("candle.up", "candle.down"),),  # the outline's ink IS color.candle.up
    "line-order": (("chart.line", "color.order.line"),),
    "line-focus": (("chart.line", "color.focus.ring"),),
    "line-cvd": (("chart.line", "color.cvd.buy"), ("chart.line", "color.cvd.sell")),
}


def cvd_grid() -> dict[str, dict[str, dict[str, float]]]:
    """pair → sim (or `grey`) → theme → the pair's smallest ΔE76 (ΔL* for grey)."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for key, pairs in CVD_PAIRS.items():
        out[key] = {}
        for sim in (*SIMS, "grey"):
            out[key][sim] = {}
            for t in THEMES:
                ink = inks(t)
                vals = []
                for a, b in pairs:
                    if sim == "grey":
                        vals.append(abs(lab(ink[a])[0] - lab(ink[b])[0]))
                    else:
                        vals.append(delta_e76(simulate(ink[a], sim), simulate(ink[b], sim)))
                out[key][sim][t] = round(min(vals), 4)
    return out


def contrast_grid() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for t in THEMES:
        ink = inks(t)
        c = ink["surface.canvas"]
        out[t] = {
            "up": contrast(ink["candle.up"], c),
            "down": contrast(ink["candle.down"], c),
            "wick": contrast(ink["candle.wick"], c),
            "line": contrast(ink["chart.line"], c),
            "axis-text": contrast(ink["axis.text"], c),
            "outline-on-tint": contrast(ink["candle.up"], ink["tint.up"]),
        }
    return out


def ladder() -> list[dict[str, object]]:
    """Every integer s in [1, 60] plus the sample steps: the §3.1 ladder."""
    steps = sorted({dec(x) for x in range(1, 61)} | {dec(x) for x in SAMPLES})
    out: list[dict[str, object]] = []
    for s in steps:
        b = body_px(s)
        out.append(
            {
                "s": fmt(s),
                "tier": tier_of(s),
                "body": b,
                "wick_up": wick_up_px(b),
                "wick_down": 2 * wick_up_px(b),
                "ohlc_tick": tick_px(b, s),  # 0: the candle mark (below the tick floor)
                "tier_from_above": tier_from_above(s),
                "tier_from_below": tier_from_below(s),
                "doji_h": doji_h(s),
                "zero_w": max(b, int(g("zero.w-min"))),
            }
        )
    return out


def geom_values() -> Values:
    v: Values = {f"GEOM:{k}": DESIGN[k] for k in DESIGN}
    bodies = {body_px(dec(s)) for s in range(1, 61)}
    ups = {wick_up_px(b) for b in bodies}
    v["GEOM:wick.up"] = str(min(ups))
    v["GEOM:wick.down"] = str(2 * min(ups))
    cap, div = ticket_example()
    v["GEOM:ticket.cap"], v["GEOM:ticket.wick-divisor"] = cap, div
    o = int(g("outline"))
    v["GEOM:outline.full-from"] = str(2 * o + 1)  # an outline each side and one tint column
    span = int(g("dash.on")) + int(g("dash.off")) + int(g("dash.on"))  # on, off, on
    v["GEOM:tint.span-min"] = str(max(2 * o + 1, span))
    t = tiers()
    l1 = [body_px(s) for s in grid(t.l1, t.l0)]
    v["GEOM:dash11.max-width"] = str(max(max(l1), 1))  # L1 bodies and the L2 column
    v["GEOM:notch.min-w"] = str(int(g("notch.w")) + 2 * o)
    v["GEOM:notch.min-body-h"] = str(int(g("notch.h")) + 2 * o)
    v["GEOM:zero.h"] = str(2 * o)  # `2 × floor(dpr)` device px: twice the hairline
    v["GEOM:pnf.min-s"] = str(
        next(s for s in range(1, 201) if body_px(dec(s)) >= int(g("pnf.min-body")))
    )
    v["GEOM:ohlc.slot-less"] = str(ohlc_slot_less())
    v["GEOM:ohlc.ticks-from"] = fmt(ohlc_ticks_from())
    return v


def ohlc_ticks_from() -> Decimal:
    """The smallest spacing (0.01 px grid) from which every OHLC bar has room for its ticks."""
    t = tiers()
    xs = grid(t.l0 * (1 - t.hyst / 100), t.s_max + Decimal("0.01"))
    first = len(xs)
    for i in range(len(xs) - 1, -1, -1):
        if tick_px(body_px(xs[i]), xs[i]) < int(g("ohlc.tick-min")):
            break
        first = i
    return xs[first]


def tier_values() -> Values:
    t = tiers()
    h = t.hyst / 100
    return {
        "TIER:l0": fmt(t.l0),
        "TIER:l1": fmt(t.l1),
        "TIER:hysteresis-pct": fmt(t.hyst),
        "TIER:l0.coarser": fmt(t.l0 * (1 - h)),
        "TIER:l1.coarser": fmt(t.l1 * (1 - h)),
        "TIER:l0.finer": fmt(t.l0 * (1 + h)),
        "TIER:l1.finer": fmt(t.l1 * (1 + h)),
        "TIER:spacing.min": fmt(t.s_min),
        "TIER:spacing.max": fmt(t.s_max),
        "TIER:max-bars-per-px": fmt(1 / t.s_min),
    }


def ladder_values() -> Values:
    v: Values = {f"LADDER:sample-{i}": s for i, s in enumerate(SAMPLES, 1)}
    for i, s in enumerate(SAMPLES[:3], 1):
        v[f"LADDER:body.at-sample-{i}"] = str(body_px(dec(s)))
    cap = int(g("body.cap"))
    v["LADDER:body.cap-reached-at"] = str(next(s for s in range(1, 201) if body_px(dec(s)) == cap))
    t = tiers()
    l1 = [body_px(s) for s in grid(t.l1, t.l0)]
    v["LADDER:l1.body-min"], v["LADDER:l1.body-max"] = str(min(l1)), str(max(l1))
    v["LADDER:cvd.l1"] = CVD_L1_SAMPLE
    return v


def budget_values() -> Values:
    row = base_line("14", 717)
    w, h = grab(r"(\d{3,5})×\d{3,5}", row, "14:717 w"), grab(r"\d{3,5}×(\d{3,5})", row, "14:717")
    us = plan("11")
    us1 = us[us.index("#### US-CHART-001") :]
    us1 = us1[: us1.index("\n#### ", 5)]
    cells = split_row(base_line("26", 301))
    return {
        "BUDGET:ref.w": w,
        "BUDGET:ref.h": h,
        "BUDGET:ref.dpr": str(REF_DPR),
        "BUDGET:ref.css-w": str(int(w) // REF_DPR),
        "BUDGET:ref.css-h": str(int(h) // REF_DPR),
        "BUDGET:candle.draws": cells[3],
        "BUDGET:pane.draws": grab(r"≤ (\d+) draw calls per pane", base_line("26", 312), "26:312"),
        "BUDGET:scr030.fps": grab(r"≥(\d+) fps", row, "14:717 fps"),
        "BUDGET:scr030.bars": grab(r"with (\d+ k) bars", row, "14:717 bars"),
        "BUDGET:scr030.mb": grab(r"≤(\d+) MB per chart panel", row, "14:717 MB"),
        "BUDGET:us001.fps": grab(r"NFR: ≥(\d+) fps", us1, "US-CHART-001 fps"),
        "BUDGET:us001.gpu-mb": grab(r"GPU memory ≤(\d+) MB", us1, "US-CHART-001 GPU"),
        "BUDGET:candle.verts": str(4 * QUADS["candle"]),
        "BUDGET:ohlc.verts": str(4 * QUADS["ohlc"]),
        "BUDGET:equi.bytes": str(sum(EQUI_BYTES.values())),
    }


def count_values(spec: str, hand: str) -> Values:
    bd = board_rows(spec)
    twins = [r for r in bd if is_twin(r)]
    row = base_line("E06-D03", 87)
    stories = story_counts(hand)
    return {
        "COUNT:boards": str(len(bd)),
        "COUNT:boards.dark": str(len(bd) - len(twins)),
        "COUNT:boards.twins": str(len(twins)),
        "COUNT:boards.max": str(MAX_BOARDS),
        "COUNT:twins.max-share": "one third" if TWIN_SHARE == Fraction(1, 3) else str(TWIN_SHARE),
        "COUNT:frames.drawn": str(len(frames(spec))),
        "COUNT:lines.budget": str(SPEC_LINE_BUDGET),
        "COUNT:lines.budget-handoff": str(HAND_LINE_BUDGET),
        "COUNT:mirror.window": grab(r"\*\*(\d+) rows", row, "E06-D03:87 window"),
        "COUNT:mirror.cap": grab(r"Cap stays (\d+) rows", row, "E06-D03:87 cap"),
        "COUNT:stories.cmp181": str(stories["cmp181"]),
        "COUNT:stories.cmp222": str(stories["cmp222"]),
        "COUNT:stories.cmp226-added": str(stories["cmp226-added"]),
    }


def colour_values() -> Values:
    v: Values = {}
    for t in THEMES:
        ink = inks(t)
        for k in ("candle.up", "candle.down", "candle.wick", "surface.canvas", "axis.text"):
            v[f"HEX:{k}.{t}"] = ink[k]
        v[f"HEX:chart.line.{t}"] = ink["chart.line"]
        v[f"TINT:up.{t}"], v[f"TINT:down.{t}"] = ink["tint.up"], ink["tint.down"]
        v[f"TINT:neutral.{t}"] = ink["tint.neutral"]
    v["HEX:chart.line.primitive"] = line_choice()[0]
    v |= {f"TINT:{k}": f"{p} %" for k, p in TINTS.items()}
    v["CONTRAST:mark.min"] = fmt(mark_min())
    v["CONTRAST:text.min"] = fmt(text_min())
    for t, row in contrast_grid().items():
        for k, r in row.items():
            v[f"CONTRAST:{k}.{t}"] = show_ratio(r)
    v["CVD:de.min"] = f"ΔE76 {jnd_floor():.1f}"
    for key, sims in cvd_grid().items():
        for sim, by_theme in sims.items():
            name = SIM_KEY.get(sim, sim)
            v[f"CVD:{key}.{name}"] = show_tenths(min(by_theme.values()))
    return v


def fixture_extra() -> dict[str, object]:
    """The recorded fixtures at the base (RULED BQ-19): present, and the equi-volume width
    mapping run on the kline pages (the cap, the floor and the zero-range bars)."""
    rels = FIXTURE_OVERRIDE or [*KLINE_RELS, TRADE_REL]
    present = {r: git_show(BASE, r) is not None for r in rels}
    out: dict[str, object] = {"present": present}
    vols: list[Decimal] = []
    flat = 0
    for r in KLINE_RELS:
        text = git_show(BASE, r)
        if text is None:
            continue
        for row in json.loads(text)["result"]["list"]:
            vols.append(dec(row[5]))
            flat += len({row[1], row[2], row[3], row[4]}) == 1
    if vols:
        base = max(statistics.median(vols), min(x for x in vols if x > 0))
        w = [equi_w0(x / base) for x in vols]
        out |= {
            "bars": len(vols),
            "median_volume": fmt(statistics.median(vols)),
            "capped": sum(x == int(g("equi.cap")) for x in w),
            "at_floor": sum(x == int(g("equi.min")) for x in w),
            "mean_w0": round(statistics.mean(w), 2),
            "zero_range_bars": flat,
        }
    return out


@functools.lru_cache(maxsize=4)
def compute_cached(spec: str, hand: str) -> tuple[tuple[tuple[str, str], ...], str]:
    v: Values = {}
    v |= geom_values()
    v |= tier_values()
    v |= ladder_values()
    v |= budget_values()
    v |= count_values(spec, hand)
    v |= colour_values()
    extra = {
        "ladder": ladder(),
        "contrast": {
            t: {k: round(r, 3) for k, r in row.items()} for t, row in contrast_grid().items()
        },
        "cvd": cvd_grid(),
        "line_choice": [list(x) for x in line_choice()[1]],
        "inks": {t: inks(t) for t in THEMES},
        "fixtures": fixture_extra(),
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


def plain(text: str, values: Values) -> str:
    """The text with every anchor dropped and every placeholder replaced by its value."""
    return PLACEHOLDER.sub(lambda m: values.get(m[1], m[0]), ANCHOR.sub("", text))


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
            elif not line[: m.start()].endswith(want):
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


def text_keys(text: str) -> set[str]:
    bare = CODE.sub("", text)
    return set(PLACEHOLDER.findall(bare)) | set(ANCHOR.findall(bare))


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
    plans: tuple[tuple[str, str], ...]  # the working-tree `14`, `15`, `16`, `26` (G-UNTOUCHED)
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


# ---------------------------------------------------------------------------- lexicon gates
#
# Each gate returns findings (tag, message, doc, section). A lexicon gate reads rendered clauses
# (comments stripped, NFKC, markup dropped, lower case); quoted copy is not a claim.

NINE_TYPES = (
    "Candle",
    "Hollow candle",
    "OHLC bar",
    "Heikin-Ashi",
    "Line",
    "Area",
    "Baseline",
    "Equi-volume",
    "Delta-volume",
)
LINE_TYPES = ("line", "area", "baseline")


def g_type(t: Texts) -> list[Finding]:
    """BQ-1 / BQ-5 (M-1): every type row of §3.2 has a geometry, a weight and an ink."""
    sec = spec_sec(t, "3.2 The")
    rows = {r["Type"]: r for r in type_rows(t.spec)}
    bad: list[Finding] = []
    for name in NINE_TYPES:
        r = rows.get(name)
        if r is None:
            bad.append(F("G-TYPE", f"§3.2 has no {name} row", "spec", sec))
            continue
        for col in ("Geometry", "Weight", "Ink"):
            if len(norm_text(r.get(col, ""))) < 2:
                bad.append(F("G-TYPE", f"§3.2 {name}: no {col.lower()}", "spec", sec))
        ink = r.get("Ink", "")
        if "color." not in ink and "as candle" not in norm_text(ink) and "line" not in ink:
            bad.append(F("G-TYPE", f"§3.2 {name}: the ink names no token", "spec", sec))
    return bad


TOKEN_SEQ = re.compile(r"`((?:color|dash|pattern)\.[a-z0-9.-]+|\.[a-z0-9-]+)`")


def names_in(cell: str) -> list[str]:
    """Token names of a cell, a shorthand `.down` expanded from the name before it."""
    out: list[str] = []
    for m in TOKEN_SEQ.finditer(cell):
        n = m[1]
        if n.startswith(".") and out:
            n = out[-1].rsplit(".", 1)[0] + n
        if not n.startswith("."):
            out.append(n.rstrip("."))
    return out


@functools.lru_cache(maxsize=1)
def dash_registry() -> frozenset[str]:
    """E11-D05 §7.2's dash ids at the base."""
    text = section(at_base("docs/design/E11/E11-D05.md"), "7.2 Line-dash vocabulary")
    return frozenset(re.findall(r"^\| `(dash\.\d+-\d+)`", text, MULTI))


def proposed(t: Texts) -> set[str]:
    """Names a hand-off A-row PROPOSES (A-12 the line token, A-14 the dash)."""
    a = table_a(t.hand)
    out: set[str] = set()
    for k in ("A-12", "A-14"):
        if k in a:
            out |= set(
                re.findall(r"`((?:color|dash)\.[a-z0-9.-]+)`", a[k][4] if len(a[k]) > 4 else "")
            )
    return out


def g_token(t: Texts) -> list[Finding]:
    """BQ-1 / BQ-17 (M-2): a bound token resolves at the base or has a PROPOSED A-row; a dash is
    in E11-D05 §7.2 or PROPOSED; `pattern.hatch.gap` is E11-D05's (cited)."""
    known = all_token_names() | dash_registry() | {"pattern.hatch.gap"} | proposed(t)
    cells: list[tuple[str, str, str]] = []
    fsec = spec_sec(t, FRAME_HEAD)
    cells += [(f["Ink"], "spec", fsec) for f in frames(t.spec) if "Ink" in f]
    cells += [(r.get("Ink", ""), "spec", spec_sec(t, "3.2 The")) for r in type_rows(t.spec)]
    tok_sec = spec_sec(t, "14.1 Bound")
    cells += [
        (r[1], "spec", tok_sec) for r in table_rows(section(t.spec, "14.1 Bound")) if len(r) > 1
    ]
    a3 = table_a(t.hand).get("A-3")
    if a3 and len(a3) > 4:
        cells.append((a3[4], "hand", hand_sec(t, "§C Copy-ready")))
    bad: list[Finding] = []
    for cell, doc, sec in cells:
        for n in names_in(cell):
            if n.startswith("color.chart.baseline"):
                continue  # G-BASEFILL's
            if n not in known:
                bad.append(F("G-TOKEN", f"`{n}` neither resolves nor is PROPOSED", doc, sec))
    return bad


DIR_ROW_FOR = {
    "candle": ("Candle,",),
    "heikin-ashi": ("Candle,",),
    "equi-volume": ("Candle,",),
    "range bars": ("Candle,",),
    "tick bars": ("Candle,",),
    "volume bars": ("Candle,",),
    "delta bars": ("Candle,",),
    "delta-volume": ("Candle,", "Delta sign"),
    "hollow": ("Hollow candle",),
    "ohlc": ("OHLC bar",),
    "renko": ("Renko",),
    "line": ("Line, area",),
    "area": ("Line, area",),
    "baseline": ("Baseline",),
    "volume sub-pane": ("Volume sub-pane",),
}
NEUTRAL_WORDS = re.compile(r"\bunchanged\b|\bno range\b")
CHANNEL_VOCAB = re.compile(r"\b(?:fill|weight|outline|span|position|word|shape|none|as candle)\b")
COLOUR_WORD = re.compile(r"\bcolou?rs?\b|\bhues?\b")
PNF = re.compile(r"\bp ?& ?f\b|point.?and.?figure|\bpnf\b", re.IGNORECASE)


def tiers_of(cell: str) -> list[str] | None:
    c = norm_text(cell)
    if re.fullmatch(r"l[012]", c):
        return [c.upper()]
    if re.fullmatch(r"l0 l2", c):
        return ["L0", "L1", "L2"]
    return None


def dir_cell(by: dict[str, dict[str, str]], r: dict[str, str], tier: str) -> str:
    """A direction cell, an "as candle" cell resolved to the candle row's cell for the tier."""
    c = norm_text(r.get(tier, ""))
    if c.startswith("as candle"):
        m = re.match(r"as candle (l[012])", c)
        cand = next((v for k, v in by.items() if k.startswith("candle,")), {})
        c += " " + norm_text(cand.get(m[1].upper() if m else tier, ""))
    return c


def g_channel(t: Texts) -> list[Finding]:
    """BQ-6 (M-5): the direction table is the never-colour-only source: every cell leads with a
    non-colour channel, and every frame's Channel cell names channels the table gives its type
    and tier ("word" only on neutral marks); never colour."""
    sec_d, sec_f = spec_sec(t, "4.1 The direction"), spec_sec(t, FRAME_HEAD)
    rows = direction_rows(t.spec)
    bad: list[Finding] = []
    for r in rows:
        for tier in ("L0", "L1", "L2"):
            c = norm_text(r.get(tier, ""))
            if COLOUR_WORD.match(c) or not CHANNEL_VOCAB.search(c):
                bad.append(
                    F(
                        "G-CHANNEL",
                        f"§4.1 {r['Type'][:24]} {tier}: no non-colour channel",
                        "spec",
                        sec_d,
                    )
                )
    by = {norm_text(r["Type"]): r for r in rows}
    for f in frames(t.spec):
        typ, chan = f.get("Type", "").lower(), f.get("Channel", "")
        if PNF.search(typ) or norm_text(chan).startswith("as "):
            continue
        if COLOUR_WORD.search(norm_text(chan)):
            bad.append(
                F("G-CHANNEL", f"{frame_id(f['Frame'])}: colour as the channel", "spec", sec_f)
            )
            continue
        tiers_ = tiers_of(f.get("Tier", ""))
        if tiers_ is None or typ == "all nine":
            continue
        neutral = NEUTRAL_WORDS.search(norm_text(f.get("Words", ""))) is not None
        heads = ("Doji, zero-range",) if neutral else DIR_ROW_FOR.get(typ, ())
        cells = " ".join(
            dir_cell(by, r, tier)
            for h in heads
            for k, r in by.items()
            if k.startswith(norm_text(h))
            for tier in tiers_
        )
        if not cells:
            bad.append(
                F(
                    "G-CHANNEL",
                    f"{frame_id(f['Frame'])}: no direction row for {typ!r}",
                    "spec",
                    sec_f,
                )
            )
            continue
        for tok in re.split(r"[+;,×]| and ", re.sub(r"\([^)]*\)", " ", norm_text(chan))):
            tok = re.sub(r"\s+below l0$", "", tok.strip())
            if tok and tok not in cells:
                bad.append(
                    F("G-CHANNEL", f"{frame_id(f['Frame'])}: {tok!r} not in §4.1", "spec", sec_f)
                )
            if tok == "word" and not neutral:
                bad.append(
                    F(
                        "G-CHANNEL",
                        f"{frame_id(f['Frame'])}: word on a directional mark",
                        "spec",
                        sec_f,
                    )
                )
    return bad


STATE_WORD = {
    "forming": "forming",
    "stale": "stale",
    "corrected": "corrected",
    "doji": "unchanged",
    "zero-range": "no range",
}


def g_words(t: Texts) -> list[Finding]:
    """BQ-1 / BQ-11 (M-27): a state frame carries its word (never colour or motion alone)."""
    sec = spec_sec(t, FRAME_HEAD)
    bad: list[Finding] = []
    for f in frames(t.spec):
        fid = frame_id(f.get("Frame", ""))
        for key, word in STATE_WORD.items():
            if re.search(rf"\b{key}\b", fid) and word not in norm_text(f.get("Words", "")):
                bad.append(F("G-WORDS", f"{fid}: no {word!r} in Words", "spec", sec))
    return bad


def g_dash(t: Texts) -> list[Finding]:
    """BQ-9 (M-14): `dash.1-1` only on marks ≤ the L1 width (L1 / L2 frames), never on a line,
    area or baseline row; `dash.2-2` keeps the forming ring (forming / stale rows only);
    `dash.4-3` keeps estimated / tested (no series frame); `dash.4-4` the hatch edges only."""
    sec = spec_sec(t, FRAME_HEAD)
    reg = dash_registry() | proposed(t)
    bad: list[Finding] = []
    for f in frames(t.spec):
        fid, typ = frame_id(f.get("Frame", "")), f.get("Type", "").lower()
        words = norm_text(f.get("Words", ""))
        for d in re.findall(r"dash\.\d+-\d+", f.get("Dash", "")):
            if d not in reg:
                bad.append(F("G-DASH", f"{fid}: {d} is not registered or PROPOSED", "spec", sec))
            if d == "dash.1-1" and typ in LINE_TYPES:
                bad.append(F("G-DASH", f"{fid}: dash.1-1 on a {typ} row", "spec", sec))
            elif d == "dash.1-1" and not set(tiers_of(f.get("Tier", "")) or ["L0"]) <= {"L1", "L2"}:
                bad.append(F("G-DASH", f"{fid}: dash.1-1 on a mark wider than L1", "spec", sec))
            if d == "dash.2-2" and not re.search(r"\bforming\b|\bstale\b", f"{fid} {words}"):
                bad.append(F("G-DASH", f"{fid}: dash.2-2 off the forming ring", "spec", sec))
            if d == "dash.4-3":
                bad.append(
                    F("G-DASH", f"{fid}: dash.4-3 (estimated / tested) on a series", "spec", sec)
                )
            if d == "dash.4-4" and "pattern.hatch.gap" not in f.get("Ink", ""):
                bad.append(F("G-DASH", f"{fid}: dash.4-4 without the hatch", "spec", sec))
    return bad


def lexicon(
    tag: str, what: str, term: str, near: str = "", unless: str = ""
) -> Callable[[Texts], list[Finding]]:
    def run(t: Texts) -> list[Finding]:
        return as_findings(tag, what, claims(lex(t), term, near=near, unless=unless))

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


def g_wick_numeric(t: Texts) -> list[Finding]:
    """BQ-5 (M-3): wick_up is the stated up weight for every L0 body below and at the cap."""
    want = int(t.values.get("GEOM:wick.up", "1"))
    tl = tiers()
    ups = {wick_up_px(body_px(dec(s))) for s in range(int(tl.l0), 201)}
    if ups != {want}:
        return [
            F(
                "G-WICK",
                f"wick_up over L0 bodies is {sorted(ups)}, not {want}",
                "spec",
                spec_sec(t, "3.1"),
            )
        ]
    # L-1: equi / delta bars are drawn k × w0 wide (up to equi_width_max()); §10.1's wick rule,
    # read from the text, keeps the same weights at every drawn width
    m = re.search(r"min\(w, (\d+)\)", plain(section(t.spec, "10.1 Width"), t.values))
    clamp = int(m[1]) if m else None
    wide = {equi_wick_up_px(w, clamp) for w in range(1, equi_width_max() + 1)}
    if wide != {want}:
        return [
            F(
                "G-WICK",
                f"§10.1: equi / delta wick_up over drawn widths 1–{equi_width_max()} px is "
                f"{sorted(wide)[:4]}, not {want}",
                "spec",
                spec_sec(t, "10.1 Width"),
            )
        ]
    return []


OHLC_RULE = re.compile(
    r"clamp\(floor\(body / 2\), (\d+), floor\(\(s − (\d+)\) / 2\)\).*?from s = ([\d.]+)"
)


def g_ohlc(t: Texts) -> list[Finding]:
    """L-2: §3.2's OHLC ticks are bounded by the slot. Read from the OHLC row, swept over every L0
    spacing on a 0.01 px grid (from L0's coarser edge): where ticks are drawn the bar's extent,
    the 2 px down stem plus two ticks, stays ≤ s − 1, and below the stated floor the bar draws
    the candle mark."""
    sec = spec_sec(t, "3.2 The")
    row = next((r for r in type_rows(t.spec) if r["Type"].startswith("OHLC")), None)
    if row is None or not row.get("Geometry", "").strip():
        return []  # no OHLC geometry at all is G-TYPE's finding
    m = OHLC_RULE.search(plain(row["Geometry"], t.values))
    if m is None:
        return [F("G-OHLC", "§3.2's OHLC ticks are not bounded by the slot", "spec", sec)]
    lo_tick, less, start = int(m[1]), int(m[2]), dec(m[3])
    tl = tiers()
    stem = 2 * wick_up_px(int(g("body.cap")))
    for s in grid(tl.l0 * (1 - tl.hyst / 100), tl.s_max + Decimal("0.01")):
        if s < start:
            continue
        b = body_px(s)
        tick = min(max(lo_tick, floor_d(dec(b) / 2)), floor_d((s - less) / 2))
        if tick < lo_tick or stem + 2 * tick > s - int(g("ohlc.gap")):
            return [
                F(
                    "G-OHLC",
                    f"§3.2 OHLC at s = {fmt(s)}: extent {stem + 2 * tick} px in a {fmt(s)} px slot",
                    "spec",
                    sec,
                )
            ]
    return []


def g_cap(t: Texts) -> list[Finding]:
    """BQ-5 (M-4): §3.1's body formula caps at the tool's cap, not T Tech's example, and the
    D06-C1 row records the departure."""
    sec = spec_sec(t, "3.1 The body")
    body = plain(section(t.spec, "3.1 The body"), t.values)
    m = re.search(r"clamp\(roundHalfUp\(([\d.]+) × s\), (\d+), (\d+)\)", body)
    bad: list[Finding] = []
    if m is None:
        return [F("G-CAP", "§3.1 states no body formula", "spec", sec)]
    if m[3] != DESIGN["body.cap"] or m[3] == t.values.get("GEOM:ticket.cap"):
        bad.append(
            F("G-CAP", f"§3.1 caps the body at {m[3]}, not {DESIGN['body.cap']}", "spec", sec)
        )
    c1 = [r for r in table_rows(section(t.spec, "18.1")) if row_key(r[0]) == "D06-C1"]
    c1_text = anch(" ".join(c1[0])) if c1 else ""
    if "GEOM:ticket.cap" not in c1_text or "GEOM:body.cap" not in c1_text:
        bad.append(F("G-CAP", "no D06-C1 row against T Tech's cap", "spec", spec_sec(t, "18.")))
    return bad


def g_ladder(t: Texts) -> list[Finding]:
    """BQ-7 (M-8): five sample steps, one inside each ticket band, on `26`'s three tiers."""
    sec = spec_sec(t, "5.2 The ticket")
    rows = table_rows(section(t.spec, "5.2 The ticket"))
    bad: list[Finding] = []
    if len(rows) != len(SAMPLES):
        bad.append(
            F("G-LADDER", f"§5.2 has {len(rows)} sample steps, not {len(SAMPLES)}", "spec", sec)
        )
    for r in rows:
        k = ANCHOR.search(anch(r[1])) if len(r) > 1 else None
        if k is None or not k[1].startswith("LADDER:sample-"):
            bad.append(F("G-LADDER", f"§5.2 {r[0]}: the sample is not the tool's", "spec", sec))
            continue
        i = int(k[1].rsplit("-", 1)[1])
        s = dec(SAMPLES[i - 1])
        lo, hi = BANDS[i - 1]
        if (lo is not None and s < lo) or (hi is not None and s >= hi):
            bad.append(F("G-LADDER", f"sample {fmt(s)} outside its band", "spec", sec))
        down, up = tier_from_above(s), tier_from_below(s)
        cell = norm_text(r[2])
        if down == up:
            ok = cell.startswith(down.lower())
        else:  # L-3: a sample inside a dead band names its tier per approach direction
            ok = cell.startswith(f"{down.lower()} when reached from above") and (
                f"{up.lower()} when reached from below" in cell
            )
        if not ok:
            want = down if down == up else f"{down} from above / {up} from below"
            bad.append(
                F("G-LADDER", f"sample {fmt(s)} is {want}, the row says {r[2][:24]!r}", "spec", sec)
            )
    frames_ = {f"ladder/sample-{i}": dec(x) for i, x in enumerate(SAMPLES, 1)}
    for fr in frames(t.spec):
        fid = frame_id(fr.get("Frame", ""))
        x = frames_.get(fid.split(" ")[0])
        if x is not None and norm_text(fr.get("Tier", "")) != tier_from_above(x).lower():
            bad.append(
                F(
                    "G-LADDER",
                    f"frame {fid}: not the zoomed-out tier {tier_from_above(x)}",
                    "spec",
                    spec_sec(t, "17. The frame"),
                )
            )
    if "reached by zooming out" not in norm_text(plain(section(t.spec, "0. Status"), t.values)):
        bad.append(
            F(
                "G-LADDER",
                "§0 does not say the sample frames are reached by zooming out",
                "spec",
                spec_sec(t, "0. Status"),
            )
        )
    return bad


def g_arow(t: Texts) -> list[Finding]:
    """BQ-2 / BQ-8 / BQ-11 / BQ-17 (M-13, M-29, M-42): A-1 … A-15 are copy-ready rows in the
    hand-off's Table A (A-7 to CMP-226, A-11 to `26` §3.6, A-13 to `ENGINE_TOKENS`), and every
    A-row the spec names exists."""
    sec = hand_sec(t, "§C Copy-ready")
    a = table_a(t.hand)
    have = {k.split(".")[0] for k in a}
    bad = [
        F("G-AROW", f"A-{i} missing from Table A", "hand", sec)
        for i in range(1, 16)
        if f"A-{i}" not in have
    ]
    targets = {"A-7": "CMP-226", "A-11.1": "§3.6", "A-13": "ENGINE_TOKENS"}
    for k, want in targets.items():
        if k in a and want not in a[k][1]:
            bad.append(F("G-AROW", f"{k} does not target {want}", "hand", sec))
    for n in sorted(set(re.findall(r"\bA-(\d+)\b", plain(t.spec, t.values))), key=int):
        if f"A-{n}" not in have and not bad:
            bad.append(F("G-AROW", f"the spec names A-{n}; Table A has none", "spec", "(top)"))
    return bad


def g_survivors(t: Texts) -> list[Finding]:
    """BQ-14 (M-34): §E lists the two survivors outside `26` §3.6 with the A-row to E12-S09."""
    sec = hand_sec(t, "§E Renderability")
    rows = [norm_text(" | ".join(r)) for r in table_rows(section(t.hand, "§E Renderability"))]
    ok = any("volume max" in r and "delta min / max" in r and "a 11.2" in r for r in rows)
    return [] if ok else [F("G-SURVIVORS", "§E lacks the two-survivor row (A-11.2)", "hand", sec)]


def g_boards(t: Texts) -> list[Finding]:
    """BQ-20 (M-47): at most ten boards, twins at most a third of them."""
    sec = spec_sec(t, "0. Status")
    bd = board_rows(t.spec)
    tw = [r for r in bd if is_twin(r)]
    bad: list[Finding] = []
    if len(bd) > MAX_BOARDS:
        bad.append(F("G-BOARDS", f"{len(bd)} boards > {MAX_BOARDS}", "spec", sec))
    if bd and Fraction(len(tw), len(bd)) > TWIN_SHARE:
        bad.append(
            F("G-BOARDS", f"{len(tw)} twins of {len(bd)} boards > {TWIN_SHARE}", "spec", sec)
        )
    if any(PNF.search(" ".join(r)) for r in bd):
        bad.append(F("G-BOARDS", "a P&F board", "spec", sec))
    return bad


def g_sheet(t: Texts) -> list[Finding]:
    """BQ-19 (M-46): board 07 is generated by the audit tool, not drawn."""
    sec = spec_sec(t, "0. Status")
    r = next((r for r in board_rows(t.spec) if r[0] == "07"), None)
    cell = norm_text(r[2]) if r and len(r) > 2 else ""
    bad: list[Finding] = []
    if "generated by the audit tool, not drawn" not in cell:
        bad.append(
            F("G-SHEET", "board 07 is not 'generated by the audit tool, not drawn'", "spec", sec)
        )
    if r and live(r[2], r"\bdrawn in penpot\b|\bdrawn by hand\b|\bhand drawn\b"):
        bad.append(F("G-SHEET", "board 07 drawn in Penpot", "spec", sec))
    return bad


def g_pnf(t: Texts) -> list[Finding]:
    """BQ-15 (M-36): P&F is a held text specimen: no frame, no board."""
    sec = spec_sec(t, FRAME_HEAD)
    return [
        F("G-PNF", f"{frame_id(f['Frame'])}: a P&F frame", "spec", sec)
        for f in frames(t.spec)
        if PNF.search(f.get("Type", "") + " " + f.get("Frame", ""))
    ]


def g_copy(t: Texts) -> list[Finding]:
    """BQ-12 (M-24): the gap copy is `14`:736 / D02:276 verbatim, never re-worded."""
    sec = spec_sec(t, "8.1 Coverage")
    src = base_line("14", 736) + base_line("D02", 276)
    body = section(t.spec, "8.1 Coverage")
    bad: list[Finding] = []
    for need in ("Not recorded 17:02–09:14 UTC: no order flow", "No bars for 17:02–09:14 UTC"):
        if f'"{need}"' not in body:
            bad.append(F("G-COPY", f"§8.1 lacks {need!r} verbatim", "spec", sec))
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            for q in re.findall(
                r'"((?:Not recorded|No bars for|Series restarted|Recording gap)[^"]*)"', line
            ):
                if q not in src:
                    bad.append(
                        F("G-COPY", f"{q[:40]!r} is not the merged copy", doc, h2_at(text, i))
                    )
    return bad


def g_haorder(t: Texts) -> list[Finding]:
    """BQ-18 (M-43): Heikin-Ashi announces real OHLCV first, then the derived HA close."""
    sec = spec_sec(t, "13. The DOM")
    row = next(
        (r for r in table_rows(section(t.spec, "13. The DOM")) if r[0] == "Heikin-Ashi"), None
    )
    cell = norm_text(row[3]) if row and len(row) > 3 else ""
    real, ha = cell.find("real ohlcv first"), cell.find("heikin ashi close")
    if real < 0 or ha < 0 or real > ha or "(derived)" not in cell:
        return [F("G-HAORDER", "the Heikin-Ashi summary is not real OHLCV first", "spec", sec)]
    return []


def g_statewords(t: Texts) -> list[Finding]:
    """BQ-18 (M-44): the state words are appended (forming, stale, corrected, width capped, no
    range)."""
    sec = spec_sec(t, "13. The DOM")
    line = next(
        (ln for ln in section(t.spec, "13. The DOM").split("\n") if "State words" in ln), ""
    )
    words = ("forming", "stale", "corrected", "width capped", "no range")
    return [
        F("G-STATEWORDS", f"§13 state words lack {w!r}", "spec", sec)
        for w in words
        if f'"{w}' not in line
    ]


def g_zero(t: Texts) -> list[Finding]:
    """BQ-1 / BQ-13 (M-30): the zero-range row states its height in px."""
    sec = spec_sec(t, "9. Doji")
    row = next(
        (r for r in table_rows(section(t.spec, "9. Doji")) if r[0].startswith("Zero-range")), None
    )
    ok = row is not None and re.search(r"<!--=GEOM:zero\.h-->\s*px tall", anch(row[1])) is not None
    return [] if ok else [F("G-ZERO", "the zero-range row states no height in px", "spec", sec)]


def g_volneutral(t: Texts) -> list[Finding]:
    """BQ-16 (M-38): the sub-pane's L1 / L2 column is the neutral maximum per column."""
    sec = spec_sec(t, "12. The volume")
    row = next(
        (r for r in table_rows(section(t.spec, "12. The volume")) if r[0].startswith("L1")), None
    )
    cell = norm_text(row[1]) if row and len(row) > 1 else ""
    if (
        "color.candle.wick" not in cell
        or "neutral" not in cell
        or re.search(r"up and down|color\.candle\.(?:up|down)", cell)
    ):
        return [F("G-VOLNEUTRAL", "the L1 / L2 volume column is not neutral", "spec", sec)]
    return []


def g_g1(t: Texts) -> list[Finding]:
    """BQ-2 (M-53): the CMP-181 enum gap is a visible G-row, blocking until its A-row lands."""
    sec = spec_sec(t, "18.2")
    line = next((ln for ln in section(t.spec, "18.2").split("\n") if "D06-G1" in ln), "")
    if "blocking until the CMP-181 A-row lands" not in line:
        return [F("G-G1", "D06-G1 is not 'blocking until the CMP-181 A-row lands'", "spec", sec)]
    return []


def g_unbuilt(t: Texts) -> list[Finding]:
    """BQ-1 (M-50): the body states the chart UI is unbuilt, so the spec is the contract, and
    that owner approval is pending."""
    sec = spec_sec(t, "0. Status")
    body = norm_text(section(t.spec, "0. Status"))
    bad = [
        F("G-UNBUILT", f"§0 lacks {n!r}", "spec", sec)
        for n in ("the chart ui is unbuilt", "this spec is the implementation contract")
        if n not in body
    ]
    if "owner approval pending" not in norm_text(t.spec.split("\n## ")[0]):
        bad.append(
            F("G-UNBUILT", "the status line lacks 'owner approval pending'", "spec", "(top)")
        )
    return bad


def g_ruled(t: Texts) -> list[Finding]:
    """Ruling form: "RULED" cites the allow-list only (the ruling 6415375587 and the BQ list
    6415040959), in any form; the RULED heading cites both; nothing cites a lane thread."""
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
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            for cid in COMMENT_ID.findall(line):
                if cid not in RULED_IDS:
                    bad.append(F("G-RULED", f"{cid} is not a ruling comment", doc, h2_at(text, i)))
            for m in re.finditer(r"\bRULED \(([^)]*\d[^)]*)\)", line):
                ids = re.findall(r"\d{8,}", m[1])
                if ids and set(ids) - set(RULED_IDS):
                    bad.append(
                        F("G-RULED", f"RULED ({m[1][:30]}) cites a foreign id", doc, h2_at(text, i))
                    )
            if (
                re.search(r"\bLANE-[A-Za-z0-9-]+|\bthread\b", line, re.IGNORECASE)
                and "RULED" in line
            ):
                bad.append(F("G-RULED", "RULED cites a thread", doc, h2_at(text, i)))
    return bad


@functools.lru_cache(maxsize=1)
def predecessor_grams() -> frozenset[tuple[str, ...]] | None:
    text = git_show(PREDECESSOR_REF, PREDECESSOR_REL)
    if text is None:
        return None
    words = re.findall(r"[\w'’.:/%-]+", norm_text(text))
    return frozenset(tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1))


def g_predecessor(t: Texts) -> list[Finding]:
    """BQ-3 (M-49): the closed predecessor is named once, in §0's history line; no run of
    SHINGLE words of its text is quoted; no round-1 ruling is cited."""
    bad: list[Finding] = []
    hits = [
        (doc, i, text)
        for doc, text in (("spec", t.spec), ("hand", t.hand))
        for i, ln in enumerate(text.split("\n"), 1)
        if PREDECESSOR in ln
    ]
    s0 = spec_sec(t, "0. Status")
    if len(hits) != 1 or hits[0][0] != "spec" or h2_at(t.spec, hits[0][1]) != s0:
        for doc, i, text in hits:
            if (doc, h2_at(text, i)) != ("spec", s0) or len(hits) > 1:
                bad.append(
                    F("G-PREDECESSOR", f"{PREDECESSOR} named at {doc}:{i}", doc, h2_at(text, i))
                )
        if not hits:
            bad.append(F("G-PREDECESSOR", f"§0 lacks the {PREDECESSOR} history line", "spec", s0))
    grams = predecessor_grams()
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for u in lex_cached(doc, text):
            if re.search(r"\bR1 [DC]\d+\b|\bround 1b?\b", norm_text(u.text), re.IGNORECASE):
                bad.append(F("G-PREDECESSOR", "a round-1 ruling cited", doc, u.sec))
            if grams is None:
                continue
            # the tool's values are cut first (a re-derived figure is not quoted text)
            words = re.findall(r"[\w'’.:/%-]+", norm_text(unvalued(u.text, t.values)))
            for i in range(len(words) - SHINGLE + 1):
                if tuple(words[i : i + SHINGLE]) in grams:
                    bad.append(
                        F(
                            "G-PREDECESSOR",
                            f"quotes the predecessor: {' '.join(words[i : i + 6])!r}",
                            doc,
                            u.sec,
                        )
                    )
                    break
    return bad


@functools.lru_cache(maxsize=1)
def fork_point() -> str:
    """The commit this branch forked from main: the merge-base with origin/main, else BASE.

    `14` / `15` / `16` / `26` move on main under other PRs; this PR must not edit them, so the
    working tree is compared with the fork point, never with a fixed sha that main has left."""
    mb = git_out("merge-base", "HEAD", "origin/main").strip()
    return mb or BASE


def g_untouched(t: Texts) -> list[Finding]:
    """BQ-2 (M-52): `14`, `15`, `16` and `26` in the working tree equal the fork point."""
    bad: list[Finding] = []
    ref = fork_point()
    for nn, text in t.plans:
        rel = plan_rel(nn)
        if rel is None or text != (git_show(ref, rel) or at_base(rel)):
            bad.append(F("G-UNTOUCHED", f"`{nn}` differs from {ref[:10]}", None, None))
    return bad


def g_budget(t: Texts) -> list[Finding]:
    """BQ-1 (M-54): the spec within SPEC_LINE_BUDGET lines, the hand-off within its own."""
    bad: list[Finding] = []
    for doc, text, cap in (("spec", t.spec, SPEC_LINE_BUDGET), ("hand", t.hand, HAND_LINE_BUDGET)):
        n = text.count("\n") + (0 if text.endswith("\n") else 1)
        if n > cap:
            last = h2_at(text, len(text.split("\n")))
            bad.append(F("G-BUDGET", f"the {doc} has {n} lines > {cap}", doc, last))
    return bad


def g_penpot(t: Texts) -> list[Finding]:
    """BQ-20 (M-48): the Penpot page by name + id only: no URL, no host."""
    bad: list[Finding] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for i, line in enumerate(text.split("\n"), 1):
            if URL.search(line):
                bad.append(F("G-PENPOT", f"{doc}:{i} a URL", doc, h2_at(text, i)))
    return bad


def g_notch(t: Texts) -> list[Finding]:
    """BQ-14 (M-32): the cap has its notch and the mirror text."""
    sec = spec_sec(t, "10.2 The cap")
    body = anch(section(t.spec, "10.2 The cap"))
    bad: list[Finding] = []
    if not re.search(r"<!--=GEOM:notch\.w-->\s*×\s*\S*<!--=GEOM:notch\.h-->\s*px notch", body):
        bad.append(F("G-NOTCH", "§10.2 has no cap notch", "spec", sec))
    if '", width capped (N × median)"' not in body:
        bad.append(F("G-NOTCH", "§10.2 has no 'width capped' mirror text", "spec", sec))
    return bad


def g_cvd_self(t: Texts) -> list[Finding]:
    """BQ-19 (M-45): the CVD matrices are carried as constants; nothing imports the research tool
    (the docs say so; the tool's own port is G-CVD-PORT)."""
    return as_findings(
        "G-CVDSELF",
        "an import of the research tool",
        claims(lex(t), r"\bimport\w*", near=r"cvd_?simulat|research tool|that file"),
    )


def g_cvd_port(_t: Texts) -> list[Finding]:
    """BQ-19: the ported Brettel / Viénot constants reproduce the pinned self-test."""
    return [F("G-CVD-PORT", p, None, None) for p in cvd_port_problems()]


def g_contrast(t: Texts) -> list[Finding]:
    """BQ-19: every mark ≥ the `05`:128 minimum on the canvas in all three themes (the up outline
    on its tint too), axis text ≥ the `05`:125 minimum."""
    sec = spec_sec(t, "15. Contrast")
    mark, text_ = float(bar_mark()), float(text_min())
    bad: list[Finding] = []
    rows = {norm_text(r[0]): r for r in table_rows(section(t.spec, "15.1 Contrast"))}
    tint_row = next((k for k in rows if k.startswith("up outline on the up tint")), "")
    after = norm_text(plain(section(t.spec, "15.1 Contrast"), t.values))
    for theme, row in contrast_grid().items():
        for k, r in row.items():
            need = text_ if k == "axis-text" else mark
            if k == "outline-on-tint" and r < need:
                # L-4: under the mark minimum the row is informative only, and the text names the
                # binding pair (the outline's outer edge on the canvas, the `up` row)
                if (
                    "informative" in tint_row
                    and "is the mark" not in tint_row
                    and ("binding pair" in after and "outer edge" in after)
                ):
                    continue
                bad.append(
                    F(
                        "G-CONTRAST",
                        f"{k} {theme} {r:.2f}:1 < {need:g}:1 and §15.1 calls it the mark "
                        "(no binding pair named)",
                        "spec",
                        sec,
                    )
                )
            elif r < need:
                bad.append(F("G-CONTRAST", f"{k} {theme} {r:.2f}:1 < {need:g}:1", "spec", sec))
    return bad


def g_cvd(t: Texts) -> list[Finding]:
    """BQ-19: a pair under the JND floor passes only when its non-colour channel differs, read from
    the direction table (§4.1, the candle row at L0); the line's pairs (its choice criterion) must
    clear the floor."""
    sec = spec_sec(t, "15. Contrast")
    floor = jnd_floor()
    grid_ = cvd_grid()
    rows = {norm_text(r[0]): r for r in table_rows(section(t.spec, "15.2 CVD"))}
    lead = next(
        (norm_text(r["L0"]) for r in direction_rows(t.spec) if r["Type"].startswith("Candle,")), ""
    )
    names = {
        "up-down.solid": "up solid vs down solid",
        "tint-down": "up tint vs down solid",
        "outline-down": "up outline vs down solid",
        "line-order": "line vs color.order.line",
        "line-focus": "line vs color.focus.ring",
        "line-cvd": "line vs color.cvd.buy / .sell (minimum)",
    }
    bad: list[Finding] = []
    for key, label in names.items():
        low = min(min(v.values()) for s, v in grid_[key].items() if s != "grey")
        if low >= floor:
            continue
        r = rows.get(label)
        chan = norm_text(r[-1]) if r else ""
        if key.startswith("line-cvd") or not chan or chan.startswith("—"):
            bad.append(
                F("G-CVD", f"{label} ΔE76 {low:.1f} < {floor:.1f} with no channel", "spec", sec)
            )
        elif key.startswith(("up", "tint", "outline")) and not all(
            w.strip() in lead for w in chan.split(",")
        ):
            bad.append(F("G-CVD", f"{label}: channel {chan!r} not in §4.1", "spec", sec))
    return bad


LINE_OVERRIDE: list[str] = []  # the self-test's tool-state lever for G-LINE


def g_line(t: Texts) -> list[Finding]:
    """BQ-17: `color.chart.line` is the tool's choice, chromatic, ≥ the mark minimum on the canvas
    in all three themes, and not the interim blue of `color.order.line` / `color.focus.ring`."""
    sec = spec_sec(t, "14. Tokens")
    name = LINE_OVERRIDE[-1] if LINE_OVERRIDE else t.values.get("HEX:chart.line.primitive", "")
    best = line_choice()[0]
    bad: list[Finding] = []
    if name != best:
        bad.append(
            F("G-LINE", f"the line primitive {name} is not the tool's choice {best}", "spec", sec)
        )
    if name.startswith(NEUTRAL_FAMILIES):
        bad.append(F("G-LINE", f"{name} is not a hue", "spec", sec))
    v = resolve(token_file("primitives"), name)
    if v.upper() in {
        theme_hex(th, n).upper()
        for th in THEMES
        for n in ("color.order.line", "color.focus.ring", "color.text.link")
    }:
        bad.append(F("G-LINE", f"{name} reuses the order-line / focus-ring blue", "spec", sec))
    return bad


def g_fixture(t: Texts) -> list[Finding]:
    """BQ-19: the recorded fixtures the spec cites exist at the base."""
    present = fixture_extra()["present"]
    assert isinstance(present, dict)
    sec = spec_sec(t, "0. Status")
    bad = [
        F("G-FIXTURE", f"{r} absent at {BASE}", "spec", sec) for r, ok in present.items() if not ok
    ]
    if TRADE_REL not in t.spec and "kline-derived" not in t.spec:
        bad.append(
            F("G-FIXTURE", "delta is neither trade-built nor labelled kline-derived", "spec", sec)
        )
    return bad


# ---------------------------------------------------------------------------- the gate list

g_wick = both(
    lexicon(
        "G-WICK",
        "a growing wick",
        r"\bwicks? (?:grows?|grew|growing|widens?|thickens?|scales?)\b|\bgrow\w* wicks?\b",
        unless=r"\bt tech\b|example cap|\bticket\b",
    ),
    g_wick_numeric,
)
g_neutral = lexicon("G-NEUTRAL", "a remapped neutral", r"\bremap\w*", near=r"\bwick\b|\bneutral\b")
g_convention = lexicon(
    "G-CONVENTION",
    "the convention / palette swapping a non-colour channel",
    r"\bswap\w* (?:the )?(?:fill|outline|weight|span|shape)",
    near=r"\bconvention\b|\bpalette\b",
)
g_l2 = both(
    lexicon("G-L2", "a logical-px L2 column", r"\b(?:logical|css) (?:px|pixel) columns?\b"),
    require("G-L2", "5.4 The L2", ("one device pixel column",)),
)
g_draws = lexicon(
    "G-DRAWS", "a per-bar draw", r"\b(?:an? )?per bar draws?\b|\bper bar draw calls?\b"
)
g_l1wick = both(
    lexicon("G-L1WICK", "L1 bodies only", r"\bbodies only\b"),
    require("G-L1WICK", "5.3 The L1", ("hairline wick",)),
)
g_l1channel = both(
    lexicon(
        "G-L1CHANNEL",
        "wick weight as the L1 channel",
        r"\bwick weight (?:is|as|becomes|stays) (?:the |a )?(?:l1 )?channel\b",
    ),
    require("G-L1CHANNEL", "5.3 The L1", ("wick weight is not a channel at l1",)),
)
g_fallback = require("G-FALLBACK", "4.3 Dash", ("declines it, the up span is outline only",))
g_chip = lexicon(
    "G-CHIP",
    "a new chip",
    r"\b(?:series|legend(?: row)?|new|second|separate|own) (?:lod )?chips?\b",
)
g_scr046 = lexicon(
    "G-SCR046",
    "a new SCR-046 field",
    r"\bnew scr 046 fields?\b|\bscr 046 (?:gains|gets|adds) (?:a )?(?:new )?fields?\b",
)
g_bridge = lexicon("G-BRIDGE", "a bridged gap", r"\bbridg\w*|\binterpolat\w*")
g_quiet = both(
    lexicon(
        "G-QUIET",
        "a quiet slot connected",
        r"\b(?:connect\w*|join\w*|link\w*) (?:across|through|over)\b",
    ),
    require("G-QUIET", "8.2 Seams", ("an empty slot",)),
)
g_beneath = lexicon(
    "G-BENEATH", "the band above the series", r"\b(?:above|over|on top of) the series\b"
)
g_hatch = lexicon(
    "G-HATCH", "pattern.hatch.gap as shipped", r"\bshipped\b", near=r"pattern\.hatch\.gap"
)
g_motion = lexicon(
    "G-MOTION",
    "motion in the series layer",
    r"\bpuls\w*|\bblink\w*|\bflash\w*|\bthrob\w*|\bglow\w*|\bfad(?:e|es|ed|ing)\b|\banimat\w*"
    r"|\btween\w*|\btransition\w*",
)
g_corrected = both(
    lexicon(
        "G-CORRECTED",
        "a per-bar text marker",
        r"\bper bar text\b|\btext labels?\b",
        near=r"\bcorrect\w*|\bmarker\b",
    ),
    require("G-CORRECTED", "7.3 Stale", ("square", "flag bit")),
)
g_doji = lexicon("G-DOJI", "a coloured doji", r"\bcolor\.candle\.(?:up|down)\b", near=r"\bdoji\b")
g_suspend = both(
    lexicon(
        "G-SUSPEND",
        "the width mapping below L0",
        r"\bmapping (?:continues|stays on|applies|holds|is kept|remains on)\b",
    ),
    require("G-SUSPEND", "10.2 The cap", ("mapping is suspended",)),
)
g_axis = lexicon("G-AXIS", "index ticks", r"\b(?:bar )?index ticks\b|\bindex labels\b")
g_volrenko = both(
    lexicon("G-VOLRENKO", "the volume pane for Renko", r"\bshown for renko\b"),
    require("G-VOLRENKO", "12. The volume", ("not shown for renko",)),
)
g_basefill = lexicon("G-BASEFILL", "a baseline token", r"\bcolor\.chart\.baseline\b")
g_opaque = lexicon(
    "G-OPAQUE", "alpha in the series", r"\balpha\b|\bopacity\b|\btranslucen\w*|\btransparen\w*"
)
g_baseline = lexicon(
    "G-BASELINE", "a dashed base line", r"\bdash\w*|\bdotted\b", near=r"\bbase line\b"
)
g_forming_line = lexicon(
    "G-FORMING-LINE",
    "a dashed forming segment",
    r"\bsegments? (?:is |are )?(?:dash\w*|dotted)\b|\b(?:dash\w*|dotted) (?:last )?segments?\b",
)

# lexicon gates first, then the measured gates; the pins (G-RULED-PIN) run last, in `audit`
LEXICON_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_type,
    g_token,
    g_channel,
    g_words,
    g_dash,
    g_wick,
    g_ohlc,
    g_cap,
    g_neutral,
    g_convention,
    g_ladder,
    g_l2,
    g_draws,
    g_l1wick,
    g_l1channel,
    g_arow,
    g_baseline,
    g_forming_line,
    g_fallback,
    g_chip,
    g_scr046,
    g_bridge,
    g_quiet,
    g_beneath,
    g_copy,
    g_hatch,
    g_motion,
    g_corrected,
    g_zero,
    g_doji,
    g_notch,
    g_suspend,
    g_survivors,
    g_axis,
    g_pnf,
    g_volrenko,
    g_volneutral,
    g_basefill,
    g_opaque,
    g_haorder,
    g_statewords,
    g_cvd_self,
    g_sheet,
    g_boards,
    g_penpot,
    g_predecessor,
    g_unbuilt,
    g_g1,
    g_ruled,
)
MEASURED_GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_cvd_port,
    g_contrast,
    g_cvd,
    g_line,
    g_fixture,
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
        "# E12-D06 pins (every unit of both docs): doc, region (heading path #occurrence), "
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


def cut_between(head: str, start: str, end: str) -> Edit:
    """Delete, inside the section `head`, from `start` through the first `end` after it."""

    def run(text: str, _v: Values) -> str:
        block = section(text, head)
        i = block.find(start)
        j = block.find(end, i + 1) if i >= 0 else -1
        if i < 0 or j < 0:
            return text
        return text.replace(block, block[:i] + block[j + len(end) :], 1)

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


def add_board(text: str, _v: Values) -> str:
    rows = [ln for ln in section(text, "0. Status").split("\n") if ln.startswith("| 10 ")]
    if not rows:
        return text
    extra = "| 11 | `E12-D06 / 11 ladder-hc` | high-contrast twin of 01 | PENDING: drawn in PR 2 |"
    return text.replace(rows[0], rows[0] + "\n" + extra, 1)


def overrun(text: str, _v: Values) -> str:
    n = text.count("\n")
    return text + "filler\n" * (SPEC_LINE_BUDGET - n + 5)


def nudge_projection() -> Callable[[], None]:
    sim = SIMS[0]
    old = PROJECTIONS[sim]
    PROJECTIONS[sim] = (old[0], old[1] * 1.001, *old[2:])
    return lambda: PROJECTIONS.__setitem__(sim, old)


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
    patch: Callable[[], Callable[[], None]] | None = None  # moves tool state; returns the undo


PRED_QUOTE = (
    "Every rule is arithmetic on bar spacing `s`, on tokens, or on quantities the renderer "
    "already has, so it can be implemented without the artwork."
)
P_ROW = (
    "| `types/pnf · dark` | 02 | P&F | L0 | shape | `color.candle.up`, `.down` | — | — | PENDING |"
)
NEUTRAL_HEAD = "neutral (wick, doji, ring, corrected square, zero line, L1 / L2 volume, base line)"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation("M-1", "G-TYPE", "BQ-1", spec=row_edit("3.2 The", "OHLC bar", 1, to(""))),
    Mutation(
        "M-2",
        "G-TOKEN",
        "BQ-1, BQ-17",
        spec=reg("types/line · dark", "Ink", to("`color.chart.grid`")),
    ),
    Mutation("M-3", "G-WICK", "BQ-5", spec=say_in("3.1 The body", "The wick grows with the body.")),
    Mutation(
        "M-4",
        "G-CAP",
        "BQ-5",
        spec=with_values(
            lambda v: sub_in("3.1 The body", av(v, "GEOM:body.cap"), av(v, "GEOM:ticket.cap"))
        ),
    ),
    Mutation(
        "M-5", "G-CHANNEL", "BQ-6", spec=reg("marks/candle-L2 · dark", "Channel", to("colour"))
    ),
    Mutation(
        "M-6",
        "G-NEUTRAL",
        "BQ-6",
        spec=row_edit("14.1 Bound", NEUTRAL_HEAD, 1, appended(", remapped to `color.cvd.buy`")),
    ),
    Mutation(
        "M-7",
        "G-CONVENTION",
        "BQ-6",
        spec=sub_in(
            "4.3 Dash",
            "swap hues only",
            "swap hues only; the inverted convention swaps fill and outline",
        ),
    ),
    Mutation("M-8", "G-LADDER", "BQ-7", spec=drop_row("5.2 The ticket", '"1–2 px"')),
    Mutation(
        "M-9",
        "G-L2",
        "BQ-7",
        spec=sub_in(
            "5.4 The L2", "One **device-pixel** column per pixel", "One logical-px column per pixel"
        ),
    ),
    Mutation(
        "M-10",
        "G-DRAWS",
        "BQ-7",
        spec=sub_in(
            "5.5 Line types", "(`26`:301);", "(`26`:301), plus a per-bar draw for the up span;"
        ),
    ),
    Mutation("M-11", "G-L1WICK", "BQ-8", spec=say_in("5.3 The L1", "L1 draws bodies only.")),
    Mutation(
        "M-12",
        "G-L1CHANNEL",
        "BQ-8",
        spec=say_in("5.3 The L1", "The wick weight is the L1 channel."),
    ),
    Mutation("M-13", "G-AROW", "BQ-8", hand=in_lines("Table A", drop_line("| A-11."))),
    Mutation("M-14", "G-DASH", "BQ-9", spec=reg("types/line · dark", "Dash", to("`dash.1-1`"))),
    Mutation(
        "M-15",
        "G-BASELINE",
        "BQ-9",
        spec=row_edit(
            "3.2 The",
            "Baseline",
            1,
            lambda c: c.replace("base line a solid hairline", "base line dashed 4 / 3"),
        ),
    ),
    Mutation(
        "M-16",
        "G-FORMING-LINE",
        "BQ-9",
        spec=sub_in("7.1 Forming", "the segment stays solid", "the last segment is dashed"),
    ),
    Mutation(
        "M-17",
        "G-FALLBACK",
        "BQ-9",
        spec=cut_between("4.3 Dash", "If E12-D09 declines it", "known limit)."),
    ),
    Mutation(
        "M-18",
        "G-CHIP",
        "BQ-10",
        spec=add_row_after("6.1 Wording", "L1", "| L1 | series LOD chip in the legend row | — |"),
    ),
    Mutation(
        "M-19",
        "G-SCR046",
        "BQ-10",
        spec=sub_in("6.3 One value", "No new SCR-046 field:", "A new SCR-046 field:"),
    ),
    Mutation(
        "M-20",
        "G-BRIDGE",
        "BQ-12",
        spec=say_in("8.2 Seams", "The line may interpolate across the hole."),
    ),
    Mutation(
        "M-21",
        "G-BRIDGE",
        "BQ-12",
        spec=row_edit("5.5 Line types", "Line, area, baseline", 1, appended("; bridge")),
    ),
    Mutation(
        "M-22",
        "G-QUIET",
        "BQ-12",
        spec=say_in("8.2 Seams", "The line may connect across quiet slots."),
    ),
    Mutation(
        "M-23",
        "G-BENEATH",
        "BQ-12",
        spec=sub_in(
            "8.1 Coverage", "drawn **beneath** the series layer", "drawn above the series layer"
        ),
    ),
    Mutation(
        "M-24",
        "G-COPY",
        "BQ-12",
        spec=sub_in(
            "8.1 Coverage", '"Not recorded 17:02–09:14 UTC: no order flow"', '"no data 17:02–09:14"'
        ),
    ),
    Mutation(
        "M-25",
        "G-HATCH",
        "BQ-12",
        spec=sub_in(
            "8.1 Coverage",
            "the PROPOSED `pattern.hatch.gap` band",
            "the `pattern.hatch.gap` (shipped) band",
        ),
    ),
    Mutation("M-26", "G-MOTION", "BQ-11", spec=say_in("7.1 Forming", "It is a pulsing ring.")),
    Mutation(
        "M-27", "G-WORDS", "BQ-1, BQ-11", spec=reg("states/forming-1s · dark", "Words", to("—"))
    ),
    Mutation(
        "M-28",
        "G-CORRECTED",
        "BQ-11",
        spec=say_in("7.3 Stale", "The corrected marker is a per-bar text label."),
    ),
    Mutation("M-29", "G-AROW", "BQ-11", hand=in_lines("Table A", drop_line("| A-7 "))),
    Mutation(
        "M-30",
        "G-ZERO",
        "BQ-1, BQ-13",
        spec=with_values(lambda v: sub_in("9. Doji", f"× {av(v, 'GEOM:zero.h')} px tall ", "")),
    ),
    Mutation("M-31", "G-DOJI", "BQ-13", spec=say_in("9. Doji", "The doji in `color.candle.up`.")),
    Mutation(
        "M-32", "G-NOTCH", "BQ-14", spec=cut_between("10.2 The cap", "a bar with ", "tall). ")
    ),
    Mutation(
        "M-33", "G-SUSPEND", "BQ-14", spec=say_in("10.2 The cap", "The mapping continues below L0.")
    ),
    Mutation("M-34", "G-SURVIVORS", "BQ-14", hand=drop_row("§E Renderability", "E-5")),
    Mutation(
        "M-35",
        "G-AXIS",
        "BQ-15",
        spec=say_in("11.2 The time", "The label strategy is bar-index ticks."),
    ),
    Mutation(
        "M-36",
        "G-PNF",
        "BQ-15",
        spec=add_row_after(FRAME_HEAD, "`types/delta-volume · dark`", P_ROW),
    ),
    Mutation(
        "M-37",
        "G-VOLRENKO",
        "BQ-16",
        spec=sub_in("12. The volume", "not shown for Renko", "shown for Renko"),
    ),
    Mutation(
        "M-38",
        "G-VOLNEUTRAL",
        "BQ-16",
        spec=row_edit("12. The volume", "L1 / L2", 1, appended("; up and down colours")),
    ),
    Mutation(
        "M-39",
        "G-HEX",
        "BQ-17",
        spec=with_values(lambda v: sub_in("14.1 Bound", av(v, "HEX:chart.line.dark"), "#6EA1F5")),
    ),
    Mutation(
        "M-40",
        "G-BASEFILL",
        "BQ-17",
        spec=add_row_after(
            "14.1 Bound",
            "baseline fills",
            "| baseline up fill | `color.chart.baseline.up` | — | — | — | PROPOSED |",
        ),
    ),
    Mutation(
        "M-41",
        "G-OPAQUE",
        "BQ-17",
        spec=with_values(
            lambda v: say_in("14.2 Tints", f"The up tint is drawn at {av(v, 'TINT:body')} alpha.")
        ),
    ),
    Mutation("M-42", "G-AROW", "BQ-17", hand=in_lines("Table A", drop_line("| A-13 "))),
    Mutation(
        "M-43",
        "G-HAORDER",
        "BQ-1, BQ-18",
        spec=row_edit(
            "13. The DOM",
            "Heikin-Ashi",
            3,
            to('"Heikin-Ashi close 64,206 (derived), up" first, then real OHLCV'),
        ),
    ),
    Mutation(
        "M-44", "G-STATEWORDS", "BQ-18", spec=line_edit("- **State words**", '"forming", ', "")
    ),
    Mutation(
        "M-45", "G-CVDSELF", "BQ-19", spec=say_in("1.2 Method", "The tool imports `cvd_simulate`.")
    ),
    Mutation(
        "M-46",
        "G-SHEET",
        "BQ-19",
        spec=row_edit("0. Status", "07", 2, appended(", drawn in Penpot")),
    ),
    Mutation("M-47", "G-BOARDS", "BQ-1, BQ-20", spec=add_board),
    Mutation(
        "M-48",
        "G-PENPOT",
        "BQ-20",
        spec=sub_in(
            "0. Status",
            "Page `E12-D06 series visual language`,",
            "Page `E12-D06 series visual language` (https://design.penpot.app/#/workspace),",
        ),
    ),
    Mutation(
        "M-49",
        "G-PREDECESSOR",
        "BQ-3",
        spec=line_edit("1. Text-first series spec", "PENDING", f"PENDING (after {PREDECESSOR})"),
    ),
    Mutation(
        "M-50",
        "G-UNBUILT",
        "BQ-1",
        spec=sub_in("0. Status", "**this spec is the implementation contract**", "**the spec**"),
    ),
    Mutation("M-51", "G-CITE", "BQ-1", spec=sub_in("7.3 Stale", "`23`:1257", "`23`:99999")),
    Mutation("M-52", "G-UNTOUCHED", "BQ-1, BQ-2", p15=lambda x: x + "extra\n"),
    Mutation(
        "M-53",
        "G-G1",
        "BQ-2",
        spec=line_edit("- **D06-G1**", "**blocking until the CMP-181 A-row lands**", "blocking"),
    ),
    Mutation("M-54", "G-BUDGET", "BQ-1", spec=overrun),
    # the tool's own: the ruled sentences §17.2 does not list, and the tool-state gates
    Mutation(
        "X-1",
        "G-RULED",
        "RULED cites only 6415375587 (+ the BQ list)",
        hand=line_edit("Components:", f"comment {RULING_ID}", "comment 6415375599"),
    ),
    Mutation(
        "X-2",
        "G-PREDECESSOR",
        "BQ-3: nothing from the predecessor quoted",
        spec=say_in("1.1 What", PRED_QUOTE),
    ),
    Mutation(
        "X-3",
        "G-DASH",
        "BQ-9: dash.1-1 only on marks ≤ the L1 width",
        spec=reg("types/candle · dark", "Dash", to("`dash.1-1`")),
    ),
    Mutation(
        "X-4",
        "G-DASH",
        "BQ-9: dash.4-3 keeps estimated / tested",
        spec=reg("states/corrected · dark", "Dash", to("`dash.4-3`")),
    ),
    Mutation(
        "X-5",
        "G-DASH",
        "BQ-9: dash.2-2 keeps the forming ring",
        spec=reg("types/ohlc · dark", "Dash", to("`dash.2-2`")),
    ),
    Mutation("X-6", "G-CVD-PORT", "BQ-19: the matrices' pinned self-test", patch=nudge_projection),
    Mutation(
        "X-7",
        "G-ANCHOR",
        "BQ-1: an anchored value differs",
        spec=with_values(lambda v: sub_in("5.1 Tiers", av(v, "TIER:l0"), "4<!--=TIER:l0-->")),
    ),
    Mutation(
        "X-8",
        "G-ANCHOR",
        "BQ-1: a figure typed by hand",
        spec=say_in("11.1 Slots", "Bricks keep a 7 px gap."),
    ),
    Mutation(
        "X-9",
        "G-MARKER",
        "BQ-1 (a): a hidden comment",
        spec=sub_in(
            "3.1 The body",
            "- **Body width:**",
            "- <!-- the line interpolates across the hole -->**Body width:**",
        ),
    ),
    Mutation(
        "X-10",
        "G-MARKER",
        "BQ-1 (a): an unclosed comment",
        spec=say_in("20. Summary", "<!-- an unclosed note"),
    ),
    Mutation(
        "X-11",
        "G-CONTRAST",
        "BQ-19: marks ≥ the minimum",
        patch=pushed(MARK_MIN_OVERRIDE, Decimal(8)),
    ),
    Mutation(
        "X-12",
        "G-CVD",
        "BQ-19: a pair under the floor needs its channel",
        patch=pushed(JND_OVERRIDE, 500.0),
    ),
    Mutation(
        "X-13",
        "G-FIXTURE",
        "BQ-19: the fixture exists at the base",
        patch=pushed(FIXTURE_OVERRIDE, "packages/fixtures/bybit/missing.json"),
    ),
    Mutation(
        "X-14",
        "G-LINE",
        "BQ-17: the tool's line choice",
        patch=pushed(LINE_OVERRIDE, "palette.blue.300"),
    ),
    Mutation(
        "X-15",
        "G-ANCHOR",
        "BQ-1: a placeholder left unfilled",
        spec=say_in("16. Renderability", "The cap is {{BUDGET:pane.draws}} draws."),
    ),
    Mutation(
        "X-16",
        "G-CHANNEL",
        "BQ-6: a direction cell led by colour",
        spec=row_edit("4.1 The direction", "Line, area", 1, to("colour only")),
    ),
    # the fold of the lens findings (L-1 … L-4): each new sweep trips on the old text
    Mutation(
        "X-17",
        "G-WICK",
        "L-1: equi / delta wicks keep 1 px / 2 px at every drawn width",
        spec=in_lines(
            "10.1 Width",
            lambda ls: [
                "- Wicks follow §3.1 on the bar's own width." if x.startswith("- Wicks") else x
                for x in ls
            ],
        ),
    ),
    Mutation(
        "X-18",
        "G-OHLC",
        "L-2: OHLC ticks bounded by the slot (extent ≤ s − 1)",
        spec=sub_in("3.2 The", "clamp(floor(body / 2), ", "max(floor(body / 2), "),
    ),
    Mutation(
        "X-19",
        "G-LADDER",
        "L-3: a sample inside a dead band names its tier per approach direction",
        spec=row_edit("5.2 The ticket", '"2–4 px"', 2, to("L0")),
    ),
    Mutation(
        "X-20",
        "G-CONTRAST",
        "L-4: an outline-on-tint row under 3:1 is informative, the binding pair named",
        spec=row_edit(
            "15.1 Contrast",
            "up outline on the up tint (informative; the binding pair is the first row)",
            0,
            to("up outline on the up tint (the outline is the mark)"),
        ),
    ),
    # one per pin class (G-RULED-PIN only)
    Mutation(
        "P-1",
        "G-RULED-PIN",
        "a frame row changed",
        spec=reg("types/area · dark", "Words", to("(sic)")),
    ),
    Mutation(
        "P-2",
        "G-RULED-PIN",
        "a frame row moved",
        spec=in_lines(FRAME_HEAD, swap_rows("`types/line · dark`", "`types/area · dark`")),
    ),
    Mutation(
        "P-3",
        "G-RULED-PIN",
        "a sentence added to a paragraph",
        spec=line_edit("The pixels the series layer draws", "(§18.1).", "(§18.1). Ok."),
    ),
    Mutation(
        "P-4",
        "G-RULED-PIN",
        "a bullet duplicated",
        spec=squeezed(in_lines("1.5 Rules", dup_line("- **R-8")), 2),
    ),
    Mutation(
        "P-5",
        "G-RULED-PIN",
        "a ruled sentence deleted",
        spec=in_lines("1.5 Rules", drop_line("- **R-3")),
    ),
    Mutation(
        "P-6",
        "G-RULED-PIN",
        "a new heading",
        spec=squeezed(prose_at("7.3 Stale", "### 7.4 Notes\n\nSee §7.1."), 6),
    ),
    Mutation(
        "P-7",
        "G-RULED-PIN",
        "a new unit outside the old spans",
        spec=squeezed(prose_at("18.2", "- See §7.1."), 3),
    ),
    Mutation(
        "P-8", "G-RULED-PIN", "a duplicated section", spec=squeezed(shadow("1.4 Input ledger"), 20)
    ),
    Mutation(
        "P-9",
        "G-RULED-PIN",
        "a shadow copy",
        spec=squeezed(
            shadow(
                "1.4 Input ledger",
                lambda b: b.replace("| D02 D-14 (D02:38) ", "| D02 D-14 (D02:38) (cited) ", 1),
            ),
            20,
        ),
    ),
    Mutation("P-10", "G-RULED-PIN", "blank lines squeezed", spec=squeezed(None, 3)),
    Mutation(
        "P-11",
        "G-RULED-PIN",
        "a hand-off row changed",
        hand=row_edit("§E Renderability", "E-9", 3, appended(" (cited)")),
    ),
    Mutation(
        "P-12",
        "G-RULED-PIN",
        "an anchor swapped for one of equal value",
        spec=with_values(
            lambda v: sub_in(
                "3.2 The",
                f"wick {av(v, 'GEOM:wick.up')} px up",
                f"wick {av(v, 'GEOM:outline')} px up",
            )
        ),
    ),
    Mutation(
        "P-13",
        "G-RULED-PIN",
        "a bullet turned into prose (line form)",
        spec=line_edit("- **R-8", "- **R-8", "**R-8"),
    ),
    Mutation(
        "P-14",
        "G-RULED-PIN",
        "a sentence moved across a line or table boundary, order kept",
        spec=in_lines("15.2 CVD", migrate("Pairwise ΔE between", "Board 07 is the rendered")),
    ),
    Mutation(
        "P-15",
        "G-RULED-PIN",
        "a line indented (a nested bullet, a code block)",
        spec=in_lines("8.2 Seams", indented("- **R-2:**", 2)),
    ),
    # probes that must trip nothing
    Mutation(
        "N-1",
        "",
        "Prettier re-pads a table row",
        spec=in_lines(
            FRAME_HEAD,
            lambda ls: [re.sub(r" {2,}", " ", x) if "`types/line · dark`" in x else x for x in ls],
        ),
    ),
)


def digest_texts(*texts: str) -> list[str]:
    return [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]


def digest(paths: tuple[Path, ...]) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "" for p in paths]


def plan_paths() -> tuple[tuple[str, Path], ...]:
    out = []
    for nn in UNTOUCHED:
        rel = plan_rel(nn)
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
    port = cvd_port_problems()
    lines.append(f"  CVD port self-test (two pinned hex inputs): {'ok' if not port else 'FAIL'}")
    ok = ok and not probe and not port
    pristine = digest_texts(spec_f, hand_f, *(x for _n, x in plans))
    for mu in MUTATIONS:
        if mu.gate == "G-PREDECESSOR" and mu.mid.startswith("X") and predecessor_grams() is None:
            lines.append(f"  {mu.mid} [{mu.gate}] skipped ({PREDECESSOR_REF} is not in this clone)")
            continue
        s = mu.spec(spec_f, values) if mu.spec else spec_f
        h = mu.hand(hand_f, values) if mu.hand else hand_f
        p15 = dict(plans)["15"]
        q = mu.p15(p15) if mu.p15 else p15
        if (s, h, q) == (spec_f, hand_f, p15) and mu.patch is None:
            ok = False
            lines.append(f"  {mu.mid} [{mu.gate}] NOT APPLIED (the target text moved)")
            continue
        new_plans = tuple((nn, q if nn == "15" else x) for nn, x in plans)
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
        restored = restored and digest(paths) == on_disk and not cvd_port_problems()
        restored = restored and not (
            MARK_MIN_OVERRIDE or JND_OVERRIDE or FIXTURE_OVERRIDE or LINE_OVERRIDE
        )
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
    """Every writer opens its file with newline="\\n" (RULED BQ-1 c)."""
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E12-D06 series audit (module docstring)")
    ap.add_argument("--check", action="store_true", help="audit the spec and the hand-off")
    ap.add_argument("--json", action="store_true", help="print every computed value as JSON")
    ap.add_argument("--fill", action="store_true", help="replace placeholders, then check")
    ap.add_argument("--selftest", "--self-test", action="store_true", help="apply every mutation")
    ap.add_argument("--repin-ruled", action="store_true", help=f"rewrite {RULED_PIN_TXT}")
    args = ap.parse_args(argv)
    spec_path, hand_path = ROOT / SPEC_REL, ROOT / HAND_REL
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
    if args.selftest:
        paths = (spec_path, hand_path, ROOT / RULED_PIN_TXT, *(p for _n, p in plan_paths()))
        ok, lines = selftest(spec, hand, paths)
        print("\n".join(lines))
        print(f"--selftest: {'ok' if ok else 'FAIL'} — {len(MUTATIONS)} mutations in memory")
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
        print(f"## E12-D06 audit of {SPEC_REL} (+ the hand-off) at base {BASE}")
        print(f"values computed: {len(values)}; cites checked: {n}; gates: {gates}")
        print(
            f"color.chart.line: {values['HEX:chart.line.primitive']} {values['HEX:chart.line.dark']}"
        )
        print("\n".join(f"WARN {w}" for w in warns))
        print("\n".join(notes))
        print("\n".join(f"FAIL {x}" for x in fails) or "OK — every gate passed")
        print(f"summary: {len(fails)} FAIL, {len(notes)} NOTE, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
