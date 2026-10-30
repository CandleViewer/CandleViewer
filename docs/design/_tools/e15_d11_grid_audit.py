#!/usr/bin/env python3
"""E15-D11 (#365) audit: the multi-chart grid pack (SCR-049), its spec and its hand-off.

Stdlib only, offline (`python3 -I -B`). It reads AS TEXT at the pinned base (`git show BASE:<path>`)
the plan texts, the merged E15 design texts (E15-D13's pack among them, merged as #5055, its §C
applied to `15` by #5073) and the token JSON; then the pack (`E15-D11.md`), the spec, the hand-off
and the pins from the working tree. It imports, never copies, the shared
functions: `contrast_check.contrast_ratio()` for every WCAG ratio, the research CVD script's
`simulate()`, `verify_tokens.merged_set()` / `resolve()` for the theme layering, and E15-D03's
`line_w()` for the header's text widths (the boards' per-character Inter advances).

Values. Every `{{KIND:key}}` outside a code span is COMPUTED: BUDGET (a geometry figure from the
tokens and E15-D03's anchored budget), CR (a WCAG ratio, two decimals), COUNT (the pack's own rows
and the tool's own lists). `--fill` writes `VALUE<!--=KIND:key-->`; `--check` re-derives every
anchored value. The gates, each FAIL led by its code:

- [G-ANCHOR] every anchored value equals the tool's; no placeholder left unfilled.
- [G-FIGURE] no ratio or size typed by hand outside an anchor (the bars 3:1, 4.5:1 and 7:1 and
  the window sizes excepted).
- [G-CITE] every `KEY`:line cite resolves at its revision to a non-blank line; every load-bearing
  cite (CITED) and every cite into `14` or `15` (files that move under the queue) holds its pinned
  words on that line, and a moved cite names the line now holding them (cites by content).
- [G-PIN] every sha, comment id and version reference in the documents is a known one (PINNED).
- [G-UNTOUCHED] PR 1: only the pack's five files differ from `git merge-base HEAD origin/main`.
  PR 2 (no document, tool or spec differs): `14` and `15` equal the merge-base with every §C row
  applied, each re-pointed by content, plus at most a byte-exact pins rewrite; nothing else.
  Fails closed when git cannot answer.
- [G-AROW] §C: rows A-1 ... A-n in order, each with its target file, line, a known op and its
  Old (or anchor) equal to that line, unique in its scope; `14` rows against the base, `15` rows
  against the base too (E15-D13's §C is merged into it); a table row keeps every column's width.
- [G-LEDGER] §2: dispositions from the vocabulary, the counts, every "Here" reference present.
- [G-BUDGET] each arrangement's cells from E15-D03's dock areas in both densities, 1280 and 1920
  and the 698 px Scalping column; cells, dividers and frame fill the slot; 1+3's large cell at
  A-17's 0.6.
- [G-HEADER] the disclosure steps never widen; the never-dropped five stay at the minimum; the
  DOM-node and interactive-element budgets; each hostile case's verdict (a step, or the switcher)
  follows from the minimums, and so does the switcher's one cell (a step, or "scrolls").
- [G-FOCUS] the plot rectangle is equal with and without the active-cell marker in every case;
  the marker sits inside the row; it never uses `color.focus.ring`.
- [G-CUE] the measured cues: the divider thinner than the gutter, one move handle against the
  dock's four, and at least two non-hue cues in every theme and density.
- [G-CONTRAST] the marker, the cell-row text and the grid-header text meet their bars in three
  themes; the sync edges on the canvas reproduce E15-D13 P-4 ... P-6 to the hundredth.
- [G-NAME] every name in the hand-off's name table: the interval spelled, never a short form, never
  the sync group; the width never in a name.
- [G-COPY] the copy deck: ids in order, a known level each, the ruled sentences verbatim, every
  frame time labelled measured or estimated, no subsystem word, no verdict word.
- [G-AC1] the token audit over the pack, the spec and the hand-off: every hex, px or ms value is
  anchored, names a token in its clause, or stands in §16's exception table; no exception stale.
- [G-RULED] the stamps in their exact forms at their sites; the ruled words (RULING_PINS); with
  `--source NAME=FILE` each pin also stands in that saved copy.
- [G-RULED-PIN] a default-deny pin set over every unit of the three documents in
  `e15_d11_ruled_pins.txt`, anchored values cut out. `--repin-ruled` is its only writer. When
  another gate FAILs, every G-RULED-PIN finding prints as a NOTE; the exit status stays 1.
- [G-PUBLIC] no word on the public-text list (matched by pattern), no local path, host, uuid, URL,
  agent name or closing keyword.
- [G-CROWS] §17's C-rows C-1 ... C-20 in order, each with a reading and an owner, and the ruled
  ledger rows cited where the ruling names them.
- [G-ENTRY] CMP-253 carries every §0.1 field plus Forbidden, Performance, Motion spec and "Why a
  new entry, not a variant", and its Storybook tree.
- [G-DEPUTY] the deputy's runs (lesson 3): §21 cites the dry run's run of record (DRYRUN_ID) and
  its AC row and DoD line read MET citing it; the blind check, which the record does not cover,
  stays the deputy's, its AC and DoD lines `[ ]`; the brief stands in the appendix.
- [G-MUTLIST] §19 lists the tool's mutations, one per gate, by name.
- [G-ARM] the C-2.6 carve-out sentence stands verbatim in the spec, the pack and the hand-off
  (LOCKED covers entry and arming only; cancel, close, flatten and a stop change never gated); the
  maximised cell's arm state, the "Disarming" moment and the disarm-failure path stand in the spec,
  their strings in the deck and their stories in the hand-off and A-8; the carve-out sentence
  quoted in A-8's Forbidden field; the maximised row's budget.

`--a-rows` prints §C as JSON, one record per row with its target file; `--self-test` applies one
mutation per gate (MUTATIONS) and the probes (PROBES) to an in-memory copy and passes only when each
adds exactly one new FAIL with its gate's code, a re-run reproduces the base result and no file on
disk changed.

Usage (from the repo root):
  python3 -I -B docs/design/_tools/e15_d11_grid_audit.py --check [--json] [--fill]
  python3 -I -B docs/design/_tools/e15_d11_grid_audit.py --self-test
  python3 -I -B docs/design/_tools/e15_d11_grid_audit.py --repin-ruled
  python3 -I -B docs/design/_tools/e15_d11_grid_audit.py --a-rows
  python3 -I -B docs/design/_tools/e15_d11_grid_audit.py --check --source R365=FILE --source A4346=FILE
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
BASE = "31ad848823"  # `git merge-base HEAD origin/main` at the round-1 fold (#5072's merge)
BQ_BASE = "d7f9ca3557"  # the BQ list's base (#5058's merge); no cited design text moved since
D13_PACK = "docs/design/E15/E15-D13.md"
SPEC_REL = "docs/design/specs/e15-multichart-grid.md"
PACK_REL = "docs/design/E15/E15-D11.md"
HAND_REL = "docs/design/E15/E15-D11-handoff.md"
TOOL_REL = "docs/design/_tools/e15_d11_grid_audit.py"
PINS_REL = "docs/design/_tools/e15_d11_ruled_pins.txt"
OWN_PATHS = (PACK_REL, SPEC_REL, HAND_REL, TOOL_REL, PINS_REL)
SCREENS_REL = "docs/plan/14-screens-catalogue.md"
CAT_REL = "docs/plan/15-component-catalogue.md"
TARGETS = {"14": SCREENS_REL, "15": CAT_REL}
RULING_ID = "6523105862"  # #365's ruling of record
LEDGER_ID = "6523075376"  # #2701 ledger addendum A rows A43 ... A46
BQ_ID = "6522925619"  # #365's BQ list
D12_RULING = "6522684771"  # #366's ruling of record (E15-D12)
DELEGATION_ID = "6490317249"  # the 2026-10-29 delegation directive on #2701
D13_RULING = "6519042539"  # #367's ruling of record (E15-D13)
DRYRUN_ID = "6525266596"  # #365: the deputy's dry run, the run of record (lesson 3)
D12_SPEC_SHA = "28aecd3609"  # E15-D12's PR 1, merged as #5071: its spec is read there
E15 = "docs/design/E15/E15-"
KEYS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": SCREENS_REL,
    "15": CAT_REL,
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "26": "docs/plan/26-chart-engine-design.md",
    "D02": E15 + "D02.md",
    "D03": E15 + "D03.md",
    "D04": E15 + "D04.md",
    "D05": E15 + "D05.md",
    "D06": E15 + "D06.md",
    "D07": E15 + "D07.md",
    "D09": E15 + "D09.md",
    "D13": D13_PACK,
    "D15": E15 + "D15.md",
    "E11D02": "docs/design/E11/E11-D02.md",
    "E05D03": "docs/design/E05/E05-D03.md",
    "E30D05": "docs/design/E30/E30-D05.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "D12spec": "docs/design/specs/e15-responsive-and-degraded.md",
    "M0": "docs/plan/spikes/E06-M0-report.md",
    "keymap": "apps/web/src/keymap/keymap.json",
    "E15.json": "docs/plan/backlog/E15.json",
}
TOKENS_DIR = "packages/ui/tokens"
THEMES = ("dark", "light", "high-contrast")
THEME_KEY = {"dark": "dark", "light": "light", "high-contrast": "hc"}


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(ROOT / TOKENS_DIR / "tests"))
VERIFY = _load(ROOT / TOKENS_DIR / "tests" / "verify_tokens.py", "verify_tokens")
CONTRAST = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
CVD = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")
D03TOOL = _load(ROOT / "docs" / "design" / "_tools" / "e15_d03_workspace_audit.py", "e15_d03")


# ---------------------------------------------------------------------------- git and text


def git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, check=False, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8")


@cache
def at_rev(rev: str, rel: str) -> str | None:
    return git("show", f"{rev}:{rel}")


def at_base(rel: str) -> str | None:
    return at_rev(BASE, rel)


# A key read at its own merge, not at BASE (it merged after the base; cited by content).
KEY_REV: dict[str, str] = {"D12spec": D12_SPEC_SHA}


def key_text(key: str) -> str:
    return at_rev(KEY_REV.get(key, BASE), KEYS[key]) or ""


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def lines(text: str) -> list[str]:
    return text.split("\n")


HEADING = re.compile(r"^(#{1,6}) (.*)$")
RULE_ROW = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
FENCE = re.compile(r"^```")
ANCHOR = re.compile(r"<!--=([A-Z]+:[^>]+?)-->")
PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+)\}\}")
ANCHORED = re.compile(r"([^\s|(/·]*?)<!--=([A-Z]+:[^>]+?)-->")


def split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [c.strip() for c in cells[1:-1]]


def unfence(text: str) -> str:
    """The text with fenced blocks blanked (line count kept)."""
    out, inside = [], False
    for ln in lines(text):
        if FENCE.match(ln):
            inside = not inside
            out.append("")
            continue
        out.append("" if inside else ln)
    return "\n".join(out)


def section(text: str, title: str) -> str:
    """The body of the `## ` section whose heading starts with `title`."""
    out: list[str] = []
    on, fenced = False, False
    for ln in lines(text):
        if FENCE.match(ln):
            fenced = not fenced
        elif ln.startswith("## ") and not fenced:
            on = ln[3:].startswith(title)
            continue
        if on:
            out.append(ln)
    return "\n".join(out)


def table_rows(block: str) -> list[list[str]]:
    rows = []
    for ln in lines(block):
        if ln.startswith("|") and not RULE_ROW.match(ln):
            rows.append(split_row(ln))
    return rows[1:] if rows else []


def norm(text: str) -> str:
    return " ".join(text.replace("`", "").replace("**", "").split())


# ---------------------------------------------------------------------------- tokens and colour


@cache
def theme_set(theme: str) -> dict[str, Any]:
    files = [VERIFY.PRIMITIVES, *VERIFY.THEMES[theme]]
    merged: dict[str, Any] = VERIFY.merged_set(files)
    return merged


@cache
def token_names() -> frozenset[str]:
    out: set[str] = set()
    for t in THEMES:
        out |= set(theme_set(t))
    return frozenset(out)


def value(name: str, theme: str = "dark") -> Any:
    t = theme_set(theme)
    return VERIFY.resolve(t[name]["$value"], t)


def px(name: str) -> int:
    return int(value(name))


def font(style: str) -> tuple[int, int]:
    """(size px, weight) of a typography token."""
    v = value(style)
    return int(v["fontSize"]), int(v["fontWeight"])


# E15-D13 T-7 (`D13`:176): the sync hues are palette references per theme (light its own).
SYNC_REF: dict[str, dict[str, str]] = {
    "a": {"dark": "palette.cyan.300", "light": "palette.light.cyan.300"},
    "b": {"dark": "palette.amber.300", "light": "palette.light.amber.300"},
    "c": {"dark": "palette.purple.500", "light": "palette.purple.600"},
}
# E15-D13's additions (T-1, T-2, T-6, T-7; `D13`:170-176): bound here, shipped by its PR 2T.
D13_TOKENS = frozenset(
    {
        "space.dockgrid.gutter",
        "space.panelheader.height.compact",
        "space.panelheader.height.comfortable",
        "border.panel.focus",
        "color.sync.a",
        "color.sync.b",
        "color.sync.c",
    }
)


def hexof(name: str, theme: str) -> str:
    if name.startswith("color.sync."):
        ref = SYNC_REF[name.rsplit(".", 1)[1]]["light" if theme == "light" else "dark"]
        return str(value(ref, theme)).upper()
    return str(value(name, theme)).upper()


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(a: str, b: str) -> float:
    r: float = CONTRAST.contrast_ratio(rgb(a), rgb(b))
    return r


def grey(h: str) -> str:
    r, g, b = rgb(h)
    y = round(0.299 * r + 0.587 * g + 0.114 * b)
    return f"#{y:02X}{y:02X}{y:02X}"


def sim(h: str, kind: str) -> str:
    s: str = CVD.simulate(h, kind)
    return s.upper()


def f2(x: float) -> str:
    return f"{x:.2f}"


# ---------------------------------------------------------------------------- geometry (BQ-05)


def parent_anchor(doc: str, key: str) -> str:
    """A value a parent anchors at its revision, read from its text ('' when absent)."""
    m = re.search(
        r"(\d[\d×.]*(?: / \d[\d×.]*)*)(?: px)?<!--=" + re.escape(key) + r"-->", key_text(doc)
    )
    return m.group(1) if m else ""


def pair(text: str) -> tuple[int, int]:
    a, _, b = text.partition("×")
    return int(a or 0), int(b or 0)


DENSITIES = ("compact", "comfortable")
# The slots a grid panel is drawn in: the dock area at 1280 and 1920 (E15-D03 §3.2), the Scalping
# chart column at 1280 (E15-D03 §3.3, `populated-owner`) and the 1280x800 window at 200 % zoom.
SLOTS = ("1280", "1920", "col", "z200")
# Arrangement: (rows, columns) or "1p3" (A-17: the large cell left at 0.6, three equal rows right).
ARRANGEMENTS: dict[str, tuple[int, int]] = {
    "1x2": (1, 2),
    "2x2": (2, 2),
    "3x3": (3, 3),
    "1p3": (3, 2),
    "custom": (2, 3),  # the custom example drawn: two rows by three columns
}
LARGE = 0.6  # E15-D02 A-17 (`D02`:830)
ARR_LABELS = {"1x2": "1×2", "2x2": "2×2", "3x3": "3×3", "1p3": "1+3", "custom": "Custom 2×3"}


def ctl(dens: str) -> int:
    return px(f"size.control.{dens}")


def slot(name: str, dens: str) -> tuple[int, int]:
    """The grid panel's box (W x H) in a slot."""
    dock = pair(parent_anchor("D03", f"BUDGET:dock.1280.{dens}"))
    if name == "1280":
        return dock
    if name == "1920":
        return pair(parent_anchor("D03", f"BUDGET:dock.1920.{dens}"))
    if name == "col":
        return (
            int(parent_anchor("D03", f"BUDGET:scalping.split.1280.{dens}").split(" / ")[0]),
            dock[1],
        )
    # 200 %: the 1280x800 window is 640x400 CSS px, E15-D12's W3 · H3 frame under the tabbed
    # collapse: its canvas less the workspace tab strip and the dock tab row (the grid is one tab)
    w, h = z200_canvas()
    tabs = int(parent_anchor("D03", f"BUDGET:v.tabstrip.{dens}"))
    return w, h - tabs - switcher_h(dens)


def z200_canvas() -> tuple[int, int]:
    """The 640x400 canvas: the window less the NavRail, the RightRail strip, the TopBar and the
    StatusBar (E15-D03's budget), which E15-D12 measures as 528x272 (`D12spec`:34)."""
    nav, rail = (
        int(parent_anchor("D03", "BUDGET:h.navrail")),
        int(parent_anchor("D03", "BUDGET:h.rightrail-strip")),
    )
    top, bottom = (
        int(parent_anchor("D03", "BUDGET:v.topbar")),
        int(parent_anchor("D03", "BUDGET:v.statusbar")),
    )
    return 1280 // 2 - nav - rail, 800 // 2 - top - bottom


def frame() -> int:
    return int(parent_anchor("D03", "BUDGET:focus.frame-px"))


def price_gutter() -> int:
    """The chart's price axis width, from E15-D03's 2x2 cell and plot (cell - plot - frame)."""
    cell = pair(parent_anchor("D03", "BUDGET:cell2x2.1280.compact"))
    plot = pair(parent_anchor("D03", "BUDGET:plot2x2.1280.compact"))
    return cell[0] - plot[0] - 2 * frame()


def inner(name: str, dens: str) -> tuple[int, int]:
    """The grid body: the box less the frame on four sides and the one grid header."""
    w, h = slot(name, dens)
    return w - 2 * frame(), h - 2 * frame() - ctl(dens)


def cells(arr: str, name: str, dens: str) -> tuple[tuple[int, int], tuple[int, int]]:
    """(largest cell, smallest cell); the leading cells take any spare pixel."""
    w, h = inner(name, dens)
    d = px("border.hairline")
    if arr == "1p3":
        span = w - d
        large = round(LARGE * span)
        small = (span - large, (h - 2 * d) // 3)
        return (large, h), small
    r, c = ARRANGEMENTS[arr]
    cw, ch = (w - (c - 1) * d) / c, (h - (r - 1) * d) / r
    return (math.ceil(cw), math.ceil(ch)), (math.floor(cw), math.floor(ch))


def plot(cell: tuple[int, int], dens: str, marker: bool) -> tuple[int, int]:
    """The plot inside a cell: less the header row, the time strip and the price axis. The marker
    draws inside the header row's bottom edge (BQ-09), so it takes nothing from the plot."""
    row = ctl(dens)  # the row's height is the same with and without the marker
    if marker:
        row = max(row, px("border.thick"))
    return cell[0] - price_gutter(), cell[1] - row - ctl(dens)


def wh(p: tuple[int, int]) -> str:
    return f"{p[0]}×{p[1]}"


def switcher_h(dens: str) -> int:
    """The switcher row: CMP-251's row (`space.panelheader.height.*`) and its bottom hairline."""
    return px(f"space.panelheader.height.{dens}") + px("border.hairline")


def one_cell(name: str, dens: str) -> tuple[int, int]:
    """The one cell the switcher shows: the grid body less the switcher row."""
    w, h = inner(name, dens)
    return w, h - switcher_h(dens)


# ---------------------------------------------------------------------------- the cell header


SYMBOL, INTERVAL, LETTER, AXES, COUNT_WORD, NUMBER = (
    "BTCUSDT",
    "15m",
    "A",
    "· symbol, crosshair",
    "· 2",
    "9",
)
ENV_WORDS = ("LIVE", "DEMO")
STEPS = (0, 1, 2, 3, 4)  # full; number goes; axes become a count; carets go; letter only
NEVER_DROPPED = ("symbol", "interval", "sync letter", "environment badge", "cell menu")


def line_w(text: str, size: int, weight: int, safe: bool) -> int:
    return math.ceil(float(D03TOOL.line_w(text, size, weight, safe)))


def header_parts(dens: str, step: int) -> list[tuple[str, int]]:
    """The row's elements at a step, each with its width from tokens (E15-D03 §3.6's method)."""
    s1, s2 = px("space.1"), px("space.2")
    label, medium = font("type.ui.label")
    cap, _ = font("type.ui.caption")
    bold, semibold = px("font.weight.bold"), px("font.weight.semibold")
    caret = px("size.icon.sm")
    icon = px("size.icon.md")

    def chip(text: str) -> int:  # a caption in a chip: SAFE + 2 px of side bearings (E15-D03)
        return line_w(text, cap, int(value("type.ui.caption")["fontWeight"]), True) + 2

    def picker(text: str) -> int:
        return line_w(text, label, medium, False) + (0 if step >= 3 else s1 + caret)

    words = None if step >= 4 else (COUNT_WORD if step >= 2 else AXES)
    badge = 2 * s2 + chip(LETTER) + 2 + (s1 + chip(words) if words else 0)
    env = max(2 * s2 + line_w(w, label, semibold, False) + 2 + s1 + icon for w in ENV_WORDS)
    parts = [
        ("number", line_w(NUMBER, cap, bold, False)),
        ("symbol", picker(SYMBOL)),
        ("interval", picker(INTERVAL)),
        ("sync letter", badge),
        ("environment badge", env),
        ("cell menu", ctl(dens)),
    ]
    return [p for p in parts if not (p[0] == "number" and step >= 1)]


def gap(dens: str) -> int:
    return px("space.2") if dens == "compact" else px("space.3")


def header_w(dens: str, step: int) -> int:
    parts = header_parts(dens, step)
    return 2 * px("space.2") + sum(w for _, w in parts) + gap(dens) * (len(parts) - 1)


def min_h(dens: str) -> int:
    """The cell's height minimum: the row, the time strip and four legible price rows."""
    return 2 * ctl(dens) + 4 * px(f"size.row.{dens}")


def verdict(cell: tuple[int, int], dens: str) -> str:
    """The first step whose row fits the cell, or the switcher (BQ-07's fallback)."""
    if cell[1] < min_h(dens):
        return "switcher"
    for s in STEPS:
        if header_w(dens, s) <= cell[0]:
            return str(s)
    return "switcher"


def one_verdict(name: str, dens: str) -> str:
    """The switcher's one cell: the first step whose row fits, or "scrolls" when the one cell is
    itself under either minimum (it keeps its minimum and the grid body scrolls to it)."""
    cell = one_cell(name, dens)
    got = verdict(cell, dens)
    return "scrolls" if got == "switcher" else got


# (element, DOM nodes, interactive elements) of one cell header row at its fullest (BQ-08)
ANATOMY: tuple[tuple[str, int, int], ...] = (
    ("the row (`role` none; the marker is its bottom border)", 1, 0),
    ("the cell number", 1, 0),
    ("the symbol picker: button, label, caret", 3, 1),
    ("the interval picker: button, label, caret", 3, 1),
    ("the sync badge: button, tile, letter, glyph, words", 5, 1),
    ("the environment badge (CMP-075): container, word, glyph", 3, 0),
    ("the cell menu: button, glyph", 2, 1),
)
NODE_BUDGET, INTERACTIVE_BUDGET = 24, 7
# a maximised cell's row adds the chart panel's arm control (A44; E15-D03 row 9)
# CMP-229 counts as status, not an action, as a chart panel's header counts it (`D03`:305)
ARM_PART = ("the arm state (CMP-229, maximised only): pill, glyph, word, countdown", 4, 0)
ANATOMY_MAX = (*ANATOMY, ARM_PART)
# its T2 form (rendering 2b): no countdown (it cannot arm), the CMP-019 `lock` badge and the
# reason node in the DOM at mount; `aria-disabled` keeps it in the Tab order (G-T2.1b)
ARM_RO_PART = ("the arm state, T2 (2b): pill, glyph, word, `lock` badge, reason node", 5, 1)
ANATOMY_RO = (*ANATOMY, ARM_RO_PART)


# (case, arrangement, slot, density): the hostile cases the pack draws (BQ-07)
CASES: tuple[tuple[str, str, str, str], ...] = (
    ("dock1280", "3x3", "1280", "compact"),
    ("dock1280c", "3x3", "1280", "comfortable"),
    ("col", "3x3", "col", "compact"),
    ("colc", "3x3", "col", "comfortable"),
    ("z200", "2x2", "z200", "compact"),
    ("z200c", "2x2", "z200", "comfortable"),
)


def budget_values() -> dict[str, str]:
    v: dict[str, str] = {
        "BUDGET:frame": str(frame()),
        "BUDGET:divider": str(px("border.hairline")),
        "BUDGET:gutter": str(px("space.1")),
        "BUDGET:marker": str(px("border.thick")),
        "BUDGET:price": str(price_gutter()),
        "BUDGET:large": f"{LARGE:.1f}",
        "BUDGET:nodes": str(sum(n for _, n, _ in ANATOMY)),
        "BUDGET:interactive": str(sum(i for _, _, i in ANATOMY)),
        "BUDGET:node.budget": str(NODE_BUDGET),
        "BUDGET:interactive.budget": str(INTERACTIVE_BUDGET),
        "BUDGET:nodes.max": str(sum(n for _, n, _ in ANATOMY_MAX)),
        "BUDGET:interactive.max": str(sum(i for _, _, i in ANATOMY_MAX)),
        "BUDGET:nodes.ro": str(sum(n for _, n, _ in ANATOMY_RO)),
        "BUDGET:interactive.ro": str(sum(i for _, _, i in ANATOMY_RO)),
        "BUDGET:canvas.z200": wh(z200_canvas()),
        "BUDGET:col.width": str(slot("col", "compact")[0]),
    }
    for dens in DENSITIES:
        v[f"BUDGET:row.{dens}"] = str(ctl(dens))
        v[f"BUDGET:switcher.{dens}"] = str(switcher_h(dens))
        v[f"BUDGET:minh.{dens}"] = str(min_h(dens))
        for s in STEPS:
            v[f"BUDGET:hdr.s{s}.{dens}"] = str(header_w(dens, s))
        v[f"BUDGET:hdr.min.{dens}"] = str(header_w(dens, STEPS[-1]))
        for name in SLOTS:
            v[f"BUDGET:slot.{name}.{dens}"] = wh(slot(name, dens))
            for arr in ARRANGEMENTS:
                big, small = cells(arr, name, dens)
                v[f"BUDGET:cell.{arr}.{name}.{dens}"] = wh(small)
                if arr == "1p3":
                    v[f"BUDGET:large.{arr}.{name}.{dens}"] = wh(big)
                v[f"BUDGET:plot.{arr}.{name}.{dens}"] = wh(plot(small, dens, False))
    for case, arr, name, dens in CASES:
        small = cells(arr, name, dens)[1]
        v[f"BUDGET:case.{case}.cell"] = wh(small)
        v[f"BUDGET:case.{case}.step"] = verdict(small, dens)
        v[f"BUDGET:case.{case}.one"] = wh(one_cell(name, dens))
        v[f"BUDGET:case.{case}.onestep"] = one_verdict(name, dens)
    return v


def budget_problems() -> list[str]:
    bad: list[str] = []
    d, f = px("border.hairline"), frame()
    for dens in DENSITIES:
        if slot("1280", dens) != pair(parent_anchor("D03", f"BUDGET:dock.1280.{dens}")):
            bad.append(f"the 1280 {dens} slot is not E15-D03's dock area")
    if wh(z200_canvas()) != parent_anchor("D12spec", "BUDGET:f.640x400.canvas"):
        bad.append("the 200 % canvas is not E15-D12's 640 × 400 measurement")
    for dens in DENSITIES:
        for name in SLOTS:
            w, h = slot(name, dens)
            for arr, (r, c) in ARRANGEMENTS.items():
                big, small = cells(arr, name, dens)
                if min(small) < 1:
                    bad.append(f"{arr} in {name} {dens}: an empty cell")
                if arr == "1p3":
                    used_w = big[0] + d + small[0]
                    share = big[0] / (used_w - d)
                    if abs(share - LARGE) > 0.005:
                        bad.append(
                            f"1+3 in {name} {dens}: the large cell is {share:.3f}, not A-17's"
                        )
                    used_h = h - 2 * f - ctl(dens)
                    if 3 * small[1] + 2 * d > used_h:
                        bad.append(f"1+3 in {name} {dens}: the right column overflows")
                    continue
                cols_w = small[0] * c + (c - 1) * d
                rows_h = small[1] * r + (r - 1) * d
                if (
                    not 0 <= (w - 2 * f) - cols_w < c
                    or not 0 <= (h - 2 * f - ctl(dens)) - rows_h < r
                ):
                    bad.append(f"{arr} in {name} {dens}: cells, dividers and frame do not fill it")
    return bad


def header_problems() -> list[str]:
    bad: list[str] = []
    for dens in DENSITIES:
        widths = [header_w(dens, s) for s in STEPS]
        if any(b > a for a, b in itertools.pairwise(widths)):
            bad.append(f"{dens}: a disclosure step widens the row {widths}")
        names = [n for n, _ in header_parts(dens, STEPS[-1])]
        for keep in NEVER_DROPPED:
            if keep not in names:
                bad.append(f"{dens}: {keep} is dropped at the minimum")
    if sum(n for _, n, _ in ANATOMY) > NODE_BUDGET:
        bad.append("the cell header is over its DOM-node budget")
    if sum(i for _, _, i in ANATOMY) > INTERACTIVE_BUDGET:
        bad.append("the cell header is over its interactive-element budget")
    if sum(n for _, n, _ in ANATOMY_MAX) > NODE_BUDGET:
        bad.append("the maximised cell's row is over its DOM-node budget")
    if sum(i for _, _, i in ANATOMY_MAX) > INTERACTIVE_BUDGET:
        bad.append("the maximised cell's row is over its interactive-element budget")
    if sum(n for _, n, _ in ANATOMY_RO) > NODE_BUDGET:
        bad.append("the read-only maximised cell's row is over its DOM-node budget")
    if sum(i for _, _, i in ANATOMY_RO) > INTERACTIVE_BUDGET:
        bad.append("the read-only maximised cell's row is over its interactive-element budget")
    for case, arr, name, dens in CASES:
        small = cells(arr, name, dens)[1]
        got = verdict(small, dens)
        fits = small[1] >= min_h(dens) and small[0] >= header_w(dens, STEPS[-1])
        if (got == "switcher") == fits:
            bad.append(f"{case}: the verdict {got} does not follow from the minimums")
        one, step = one_cell(name, dens), one_verdict(name, dens)
        if one[0] < small[0] or one[1] < small[1]:
            bad.append(f"{case}: the switcher's one cell is smaller than a grid cell")
        one_fits = one[1] >= min_h(dens) and one[0] >= header_w(dens, STEPS[-1])
        if (step == "scrolls") == one_fits:
            bad.append(f"{case}: the one cell's verdict {step} does not follow from the minimums")
    return bad


def focus_problems() -> list[str]:
    bad: list[str] = []
    for dens in DENSITIES:
        label, _ = font("type.ui.label")
        box = math.ceil(label * float(value("type.ui.label")["lineHeight"]))
        if px("border.thick") > (ctl(dens) - box) / 2:
            bad.append(f"{dens}: the marker does not fit under the row's text")
        for name in SLOTS:
            for arr in ARRANGEMENTS:
                for cell in cells(arr, name, dens):
                    if plot(cell, dens, True) != plot(cell, dens, False):
                        bad.append(f"{arr} {name} {dens}: the marker changes the plot")
    for role in MARKER_ROLES.values():
        if role == "color.focus.ring":
            bad.append("the active-cell marker uses the panel focus colour")
    return bad


# ---------------------------------------------------------------------------- cue and contrast

CANVAS, RAISED = "color.surface.canvas", "color.surface.raised"
MARKER_ROLES = {"focused": "color.text.primary", "unfocused": "color.text.secondary"}
HANDLES = {"dock": 4, "grid": 1}  # move handles on a 2x2 dock preset and on a 2x2 grid
FILL_STEP = 1.1  # a luminance step counted as a cue only at or above this ratio
# (key, foreground, background): every pair is measured per theme; BARS gates (absent = reported)
PAIRS: tuple[tuple[str, str, str], ...] = (
    ("marker.focused", MARKER_ROLES["focused"], CANVAS),
    ("marker.unfocused", MARKER_ROLES["unfocused"], CANVAS),
    ("number", "color.text.secondary", CANVAS),
    ("symbol", "color.text.primary", CANVAS),
    ("gridheader", "color.text.primary", RAISED),
    ("divider", "color.border.default", CANVAS),
    ("cue.fill", RAISED, CANVAS),
    ("sync.a.canvas", "color.sync.a", CANVAS),
    ("sync.b.canvas", "color.sync.b", CANVAS),
    ("sync.c.canvas", "color.sync.c", CANVAS),
)
BARS: dict[str, float] = {
    "marker.focused": 3.0,
    "marker.unfocused": 3.0,
    "number": 4.5,
    "symbol": 4.5,
    "gridheader": 4.5,
    "sync.a.canvas": 3.0,
    "sync.b.canvas": 3.0,
    "sync.c.canvas": 3.0,
}
CVD_KINDS = {"deutan": "deuteranopia", "protan": "protanopia", "tritan": "tritanopia"}


def colour_values() -> dict[str, str]:
    v: dict[str, str] = {}
    for theme in THEMES:
        k = THEME_KEY[theme]
        for key, fg, bg in PAIRS:
            v[f"CR:{key}.{k}"] = f2(ratio(hexof(fg, theme), hexof(bg, theme)))
        fg, bg = hexof(MARKER_ROLES["focused"], theme), hexof(CANVAS, theme)
        v[f"CR:marker.grey.{k}"] = f2(ratio(grey(fg), grey(bg)))
        for short, kind in CVD_KINDS.items():
            v[f"CR:marker.{short}.{k}"] = f2(ratio(sim(fg, kind), sim(bg, kind)))
    return v


def cue_values() -> dict[str, str]:
    v = {"COUNT:handles.dock": str(HANDLES["dock"]), "COUNT:handles.grid": str(HANDLES["grid"])}
    for theme in THEMES:
        v[f"COUNT:cues.{THEME_KEY[theme]}"] = str(len(cues(theme)))
    return v


def cues(theme: str) -> list[str]:
    """The non-hue cues that hold in a theme (every density: none depends on density)."""
    out = []
    if px("border.hairline") < px("space.1"):
        out.append("divider")
    if HANDLES["grid"] < HANDLES["dock"]:
        out.append("handles")
    if ratio(hexof(RAISED, theme), hexof(CANVAS, theme)) >= FILL_STEP:
        out.append("fill")
    return out


def cue_problems() -> list[str]:
    bad = []
    if px("border.hairline") >= px("space.1"):
        bad.append("the grid's divider is not thinner than the dock's gutter")
    if HANDLES["grid"] >= HANDLES["dock"]:
        bad.append("the grid shows as many move handles as the dock")
    for theme in THEMES:
        if len(cues(theme)) < 2:
            bad.append(f"{theme}: fewer than two non-hue cues")
    return bad


def contrast_problems() -> list[str]:
    bad: list[str] = []
    v = colour_values()
    for theme in THEMES:
        k = THEME_KEY[theme]
        for key, bar in BARS.items():
            if float(v[f"CR:{key}.{k}"]) < bar:
                bad.append(f"{key} in {theme}: {v[f'CR:{key}.{k}']} under {bar}:1")
        for short in CVD_KINDS:
            if float(v[f"CR:marker.{short}.{k}"]) < 3.0:
                bad.append(f"the marker under {short} in {theme} is under 3:1")
    for letter in "abc":
        for k in ("dark", "light", "hc"):
            parent = parent_anchor("D13", f"CR:sync.{letter}.canvas.{k}")
            if parent != v[f"CR:sync.{letter}.canvas.{k}"]:
                bad.append(f"sync {letter} on the canvas in {k} is not E15-D13's {parent!r}")
    return bad


# ---------------------------------------------------------------------------- §C rows


@dataclass(frozen=True)
class ARow:
    aid: str
    entry: str
    fld: str
    file: str  # "14" or "15"
    line: int
    op: str
    src: str
    old: str  # the line (replace), a fragment of it (replace fragment) or the anchor line
    new: str


OPS = ("replace", "replace fragment", "insert after")
ROW_HEAD = re.compile(r"^#### (A-\d+) · (.+?) · (.+)$")
ROW_META = re.compile(r"^`(14|15|16)`:(\d+) · ([a-z ]+?) · from (.+?)(?: · HELD for (.+))?$")


def a_rows(spec: str) -> tuple[list[ARow], list[str]]:
    """§C's rows and the parse problems (E15-D13's row form, so its own §C parses too)."""
    body = section(spec, "§C")
    rows: list[ARow] = []
    bad: list[str] = []
    ls = lines(body)
    i = 0
    while i < len(ls):
        m = ROW_HEAD.match(ls[i])
        if not m:
            i += 1
            continue
        aid, entry, fld = m.groups()
        meta = ROW_META.match(ls[i + 2]) if i + 2 < len(ls) else None
        blocks: list[tuple[str, list[str]]] = []
        j = i + 3
        while j < len(ls) and not ROW_HEAD.match(ls[j]) and len(blocks) < 2:
            if ls[j].startswith("```") and len(ls[j]) > 3:
                kind, k = ls[j][3:], j + 1
                buf: list[str] = []
                while k < len(ls) and ls[k] != "```":
                    buf.append(ls[k])
                    k += 1
                blocks.append((kind, buf))
                j = k
            j += 1
        if not meta or len(blocks) != 2:
            bad.append(f"{aid}: no meta line or not two fenced blocks")
            i = j
            continue
        file, line, op, src, held = meta.groups()
        (k1, old), (k2, new) = blocks
        want = "anchor" if op == "insert after" else "old"
        if k1 != want or k2 != "new" or len(old) != 1:
            bad.append(f"{aid}: the blocks are not ```{want} (one line) then ```new")
        if not held:
            rows.append(
                ARow(
                    aid, entry, fld, file, int(line), op, src, old[0] if old else "", "\n".join(new)
                )
            )
        i = j
    return rows, bad


def scope_heading(base_lines: list[str], idx: int) -> str:
    for k in range(min(idx, len(base_lines) - 1), -1, -1):
        if HEADING.match(base_lines[k]):
            return base_lines[k]
    return ""


def locate(cur: list[str], base_lines: list[str], row: ARow) -> int | None:
    """Re-point a row by content: its scope heading (the heading above it in the text it names),
    then the one line equal to its Old (or holding its fragment) inside that scope."""
    frag = row.op == "replace fragment"
    if HEADING.match(row.old) and not frag:
        same = [k for k, ln in enumerate(cur) if ln == row.old]
        return same[0] if len(same) == 1 else None
    head = scope_heading(base_lines, row.line - 1)
    starts = [k for k, ln in enumerate(cur) if ln == head]
    if len(starts) != 1:
        return None
    hm = HEADING.match(head)
    level = len(hm.group(1)) if hm else 7
    hits: list[int] = []
    for k in range(starts[0] + 1, len(cur)):
        m = HEADING.match(cur[k])
        if m and len(m.group(1)) <= level:
            break
        if (row.old in cur[k]) if frag else (cur[k] == row.old):
            hits.append(k)
    return hits[0] if len(hits) == 1 else None


def apply_rows(text: str, named: str, rows: list[ARow], file: str) -> str | None:
    """`text` with every row for `file` applied, each re-pointed by content against `named` (the
    text its line numbers name); None when a row cannot be re-pointed."""
    cur, base_lines = lines(text), lines(named)
    edits: list[tuple[int, int, ARow]] = []
    for r in rows:
        if r.file != file:
            continue
        k = locate(cur, base_lines, r)
        if k is None:
            return None
        edits.append((k, 0 if r.op == "insert after" else 1, r))
    for k, _, r in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        if r.op == "replace fragment":
            cur[k] = cur[k].replace(r.old, r.new, 1)
        elif r.op == "replace":
            cur[k : k + 1] = lines(r.new)
        else:
            cur[k + 1 : k + 1] = lines(r.new)
    return "\n".join(cur)


@cache
def queue_base(file: str) -> str | None:
    """The text this ticket's rows name: `14` and `15` at the base (E15-D13's §C merged as #5073,
    so the queue base is the base itself); kept as a seam so a row ahead in the queue re-points by
    content at PR 2's open."""
    return at_base(TARGETS[file])


def export(rows: list[ARow]) -> list[dict[str, object]]:
    return [
        {
            "id": r.aid,
            "target_file": TARGETS[r.file],
            "line": r.line,
            "op": r.op,
            "entry": r.entry,
            "field": r.fld,
            "from": r.src,
            "anchor" if r.op == "insert after" else "old": r.old,
            "new": r.new,
        }
        for r in rows
    ]


def table_widths(base_lines: list[str], idx: int) -> list[int]:
    j = idx
    while j > 0 and base_lines[j - 1].startswith("|"):
        j -= 1
    k = idx
    while k + 1 < len(base_lines) and base_lines[k + 1].startswith("|"):
        k += 1
    rows = [split_row(x) for x in base_lines[j : k + 1] if not RULE_ROW.match(x)]
    return [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]


def arow_problems(rows: list[ARow], parse_bad: list[str]) -> list[str]:
    bad = list(parse_bad)
    for n, r in enumerate(rows, 1):
        if r.aid != f"A-{n}":
            bad.append(f"{r.aid}: out of order (expected A-{n})")
        if r.op not in OPS or r.file not in TARGETS:
            bad.append(f"{r.aid}: unknown op {r.op!r} or a target outside `14` / `15`")
            continue
        named = queue_base(r.file)
        if named is None:
            bad.append(f"{r.aid}: `{r.file}`'s queue base is unreadable (at {BASE})")
            continue
        bl = lines(named)
        at = bl[r.line - 1] if 1 <= r.line <= len(bl) else ""
        if (at.count(r.old) != 1) if r.op == "replace fragment" else (at != r.old):
            bad.append(f"{r.aid}: the Old is not `{r.file}`:{r.line} (or once in it)")
            continue
        if locate(bl, bl, r) != r.line - 1:
            bad.append(f"{r.aid}: the Old is not unique in its scope")
        if r.old.startswith("|") and r.op == "replace":
            w = table_widths(bl, r.line - 1)
            for c, (o, nw, ww) in enumerate(zip(split_row(r.old), split_row(r.new), w)):
                if len(nw) > ww or (len(o) == ww and len(nw) != ww):
                    bad.append(f"{r.aid}: cell {c} changes its column's width (prettier re-pads)")
    return bad


# ---------------------------------------------------------------------------- ledger, C-rows, entry

DISPOSITIONS = ("applied as amended", "applied", "routed", "closed")


def disposition(cell: str) -> str:
    for d in DISPOSITIONS:
        if cell.startswith(d):
            return d
    return ""


def ledger(pack: str) -> list[list[str]]:
    return [r for r in table_rows(section(pack, "2.")) if re.fullmatch(r"L-\d+", r[0])]


REF = re.compile(r"(spec |hand-off )?§(\d+|C)|\bA-(\d+)\b")


def ledger_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    ids = {r.aid for r in a_rows(t.pack)[0]}
    heads = {
        "": {m.group(1) for m in re.finditer(r"(?m)^## (\d+)\.", t.pack)} | {"C"},
        "spec ": {m.group(1) for m in re.finditer(r"(?m)^## (\d+)\.", t.spec)},
        "hand-off ": {m.group(1) for m in re.finditer(r"(?m)^## (\d+)\.", t.hand)},
    }
    for n, r in enumerate(ledger(t.pack), 1):
        if r[0] != f"L-{n}" or len(r) != 4:
            bad.append(f"{r[0]}: out of order or not four columns")
            continue
        if not disposition(r[2]):
            bad.append(f"{r[0]}: the disposition {r[2][:30]!r} is not in the vocabulary")
        refs = list(REF.finditer(r[3]))
        if not refs:
            bad.append(f"{r[0]}: no reference in Here")
        for m in refs:
            if m.group(3):
                if f"A-{m.group(3)}" not in ids:
                    bad.append(f"{r[0]}: A-{m.group(3)} is not a §C row")
            elif m.group(2) not in heads[m.group(1) or ""]:
                bad.append(f"{r[0]}: {m.group(0)} is not a section")
    return bad


def ledger_counts(pack: str) -> dict[str, str]:
    rows = ledger(pack)
    out = {"COUNT:ledger": str(len(rows))}
    for d in DISPOSITIONS:
        out[f"COUNT:ledger.{d.split()[-1]}"] = str(sum(disposition(r[2]) == d for r in rows))
    return out


def crows(pack: str) -> list[list[str]]:
    return [r for r in table_rows(section(pack, "17.")) if re.fullmatch(r"C-\d+", r[0])]


CROW_CITES = {"C-4": "A43", "C-8": "A44", "C-9": "A44", "C-12": "A46", "C-16": "A45", "C-17": "A45"}
N_CROWS = 20  # BQ-23's twenty, as ruled


def crow_problems(pack: str) -> list[str]:
    bad: list[str] = []
    rows = crows(pack)
    if len(rows) != N_CROWS:
        bad.append(f"{len(rows)} C-rows (BQ-23 rules {N_CROWS})")
    for n, r in enumerate(rows, 1):
        if r[0] != f"C-{n}" or len(r) != 4 or not r[2].strip() or not r[3].strip():
            bad.append(f"{r[0]}: out of order, or no reading or owner")
        elif r[0] in CROW_CITES and CROW_CITES[r[0]] not in " ".join(r):
            bad.append(f"{r[0]}: does not cite {CROW_CITES[r[0]]}")
    return bad


NEW_ID, NEW_NAME = "CMP-253", "MultiChartGrid"
ENTRY_FIELDS = (
    "**Tier**",
    "**Purpose**",
    "**Props**",
    "**Variants**",
    "**States**",
    "**A11y**",
    "**Tokens**",
    "**Storybook**",
    "**Tests**",
    "**Forbidden**",
    "**Performance**",
    "**Motion spec**",
    "**Why a new entry, not a variant**",
)


def entry_problems(pack: str) -> list[str]:
    rows = [r for r in a_rows(pack)[0] if r.entry == NEW_ID]
    if len(rows) != 1:
        return [f"no single §C row holds {NEW_ID}"]
    body = rows[0].new
    bad = [f"{NEW_ID}: no {f.strip('*')} field" for f in ENTRY_FIELDS if f not in body]
    if f"### {NEW_ID} {NEW_NAME}" not in body:
        bad.append(f"{NEW_ID}: its heading is not `### {NEW_ID} {NEW_NAME} ...`")
    if f"`Organisms/Dock/{NEW_NAME}`" not in body:
        bad.append(f"{NEW_ID}: its Storybook tree is not `Organisms/Dock/{NEW_NAME}`")
    return bad


# ---------------------------------------------------------------------------- names and copy


def name_rows(hand: str) -> list[list[str]]:
    return [r for r in table_rows(section(hand, "3.")) if len(r) == 4 and r[0]]


SHORT_INTERVAL = re.compile(r"\b\d+\s?[mhdwHDW]\b")
SPELLED = re.compile(r"\b\d+ (?:minutes?|hours?|days?|weeks?)\b")
WIDTH_WORDS = re.compile(
    r"\b(?:narrow|step \d|collapsed|switcher|compact|comfortable)\b", re.IGNORECASE
)


def name_problems(hand: str) -> list[str]:
    bad: list[str] = []
    rows = name_rows(hand)
    if not rows:
        return ["the hand-off's name table (§3) is empty"]
    for r in rows:
        if r[1] not in ("`region`", "`tab`"):
            continue
        name = r[2]
        if SHORT_INTERVAL.search(name):
            bad.append(f"{r[0]}: a short interval in the name {name!r}")
        if "sync" in name.lower():
            bad.append(f"{r[0]}: the sync group in the name {name!r}")
        if WIDTH_WORDS.search(name):
            bad.append(f"{r[0]}: a width word in the name {name!r}")
        if name.startswith('"Chart, ') and not SPELLED.search(name):
            bad.append(f"{r[0]}: the interval is not spelled in {name!r}")
    return bad


def deck(spec: str) -> list[list[str]]:
    return [r for r in table_rows(section(spec, "14.")) if re.fullmatch(r"CP-\d+", r[0])]


LEVELS = ("visible", "polite", "assertive", "none")
PRECEDENCE = "Each chart follows its own sync group."
RULED_STRINGS = (
    PRECEDENCE,
    "Maximise this chart to trade.",
    "One-click trading disarmed: chart returned to the grid.",
    "Chart, BTCUSDT 4 hours, Live, maximised.",
    "Grid restored, 4 charts.",
)
SUBSYSTEM = re.compile(r"\b(?:WebGL|GPU|context|worker|scissor\w*|React|shader)\b", re.IGNORECASE)
VERDICT = re.compile(r"\b(?:smoothly|too slow|can't handle|struggl\w*|laggy)\b", re.IGNORECASE)


def copy_problems(spec: str) -> list[str]:
    bad: list[str] = []
    rows = deck(spec)
    if not rows:
        return ["the copy deck (spec §14) is empty"]
    strings = [r[1] for r in rows]
    for n, r in enumerate(rows, 1):
        if r[0] != f"CP-{n:02d}" or len(r) != 4:
            bad.append(f"{r[0]}: out of order or not four columns")
            continue
        if r[3] not in LEVELS:
            bad.append(f"{r[0]}: the level {r[3]!r} is not one of {LEVELS}")
        s = r[1]
        if "ms per frame" in s and not ("p95" in s and ("measured" in s or "estimated" in s)):
            bad.append(f"{r[0]}: a frame time without p95 and measured / estimated")
        for rx, what in ((SUBSYSTEM, "a subsystem word"), (VERDICT, "a verdict word")):
            hit = rx.search(s)
            if hit:
                bad.append(f"{r[0]}: {what} ({hit.group(0)!r})")
    for want in RULED_STRINGS:
        if not any(want in s for s in strings):
            bad.append(f"the ruled string {want!r} is not in the deck")
    if spec.count(PRECEDENCE) < 2:
        bad.append("the precedence sentence is not stated as a rule outside the deck")
    return bad


# ---------------------------------------------------------------------------- the documents


@dataclass(frozen=True)
class Texts:
    pack: str
    spec: str
    hand: str
    pins: str
    changed: tuple[str, ...] | None
    now: tuple[tuple[str, str], ...]  # `14` / `15` in the working tree
    mbase: tuple[tuple[str, str], ...]  # `14` / `15` at `git merge-base HEAD origin/main`
    sources: tuple[tuple[str, str], ...]


def docs(t: Texts) -> list[tuple[str, str]]:
    return [("pack", t.pack), ("spec", t.spec), ("hand-off", t.hand)]


# ---------------------------------------------------------------------------- AC1 (BQ-19)

LITERAL = re.compile(r"(?<![\w.#-])(\d+(?:\.\d+)?) ?(px|ms)\b|(?<![\w&])#[0-9A-Fa-f]{6}\b")
TOKEN_SPAN = re.compile(r"`([a-z][a-z0-9-]*(?:\.[a-z0-9*-]+)+)`")
CLAUSE_SEP = re.compile(r"; |\|| · |(?<=[a-z)])\. (?=[A-Z])")


def is_token(name: str) -> bool:
    known = token_names() | D13_TOKENS
    if name.endswith(".*"):
        return any(k.startswith(name[:-1]) for k in known)
    return name in known


def literal(m: re.Match[str]) -> str:
    return f"{m.group(1)} {m.group(2)}" if m.group(1) else m.group(0).upper()


def exceptions(pack: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in table_rows(section(pack, "16.")):
        if re.fullmatch(r"X-\d+", r[0]) and len(r) == 3:
            out[r[0]] = [norm(v) for v in r[1].split(" · ")]
    return out


def ac1_scan(t: Texts) -> tuple[dict[str, int], list[str]]:
    """(counts, problems): every literal hex, px or ms value outside an anchor."""
    allowed = {v: x for x, vs in exceptions(t.pack).items() for v in vs}
    used: set[str] = set()
    counts = {"token": 0, "residual": 0, "anchored": 0}
    bad: list[str] = []
    for name, text in docs(t):
        for key in re.findall(r"(?:<!--=|\{\{)(BUDGET:[^>}]+)(?:-->|\}\})", text):
            counts["anchored"] += not re.search(r"step|large$|nodes|interactive|budget", key)
        for ln in lines(unfill(text)):
            if FENCE.match(ln):
                continue
            cuts = [0, *[m.end() for m in CLAUSE_SEP.finditer(ln)], len(ln) + 1]
            for m in LITERAL.finditer(ln):
                lo = max(c for c in cuts if c <= m.start())
                hi = min(c for c in cuts if c > m.start())
                clause = ln[lo:hi]
                lit = literal(m)
                if any(is_token(x.group(1)) for x in TOKEN_SPAN.finditer(clause)):
                    counts["token"] += 1
                elif lit in allowed:
                    counts["residual"] += 1
                    used.add(lit)
                else:
                    bad.append(
                        f"{name}: {lit!r} names no token and is no exception ({clause[:50]!r})"
                    )
    for v, x in allowed.items():
        if v not in used:
            bad.append(f"{x}: {v!r} is stale (no longer in the documents)")
    return counts, bad


# ---------------------------------------------------------------------------- cites and pins

CITE = re.compile(
    r"`("
    + "|".join(sorted((re.escape(k) for k in KEYS), key=len, reverse=True))
    + r")`:(\d+)(?:[–-](\d+))?((?:, :\d+(?:[–-]\d+)?)*)"
)
CONT = re.compile(r":(\d+)(?:[–-](\d+))?")
MOVING = ("14", "15")  # files that move under the `15` queue: every cite into them is by content
# Load-bearing words: each stands on the line its cite names (at BASE).
CITED: dict[tuple[str, int], str] = {
    ("14", 1141): "- **Type:** Panel hosting 2–9 chart instances",
    ("14", 1151): "one shared WebGL context with scissored viewports",
    ("14", 1152): "`Ctrl+Alt+1..9` focuses a sub-chart",
    ("14", 1153): "CMP-217 LayoutPresetMenu, CMP-218 SyncMenu",
    ("14", 1157): "[ ] maximise-cell and restore",
    ("14", 3201): "SCR-030, SCR-032, SCR-049 and SCR-050 additionally require",
    ("15", 31): "241–242 and 244–247 unassigned",
    ("15", 902): "### CMP-081 DockGrid / Layout Manager",
    ("15", 2527): "### CMP-196 MultiChartLinker",
    ("15", 2782): "### CMP-217 LayoutPresetMenu",
    ("15", 2784): '("3×1" out)',
    ("15", 2791): "### CMP-218 SyncMenu",
    ("15", 2824): "### CMP-221 ChartToolbar",
    ("15", 2892): "### CMP-227 EstimatedBadge",
    ("15", 2921): '"Arm state unknown — submit off", fails closed',
    ("15", 2922): "announces the change assertively",
    ("15", 3120): "a long label truncates with its full name in the accessible name",
    ("15", 3160): "**246 — E08-D04, E36-D05, E12-D09, E15-D13 addenda (below)**",
    ("D02", 150): 'no separate "propagate symbol" toggle',
    ("D02", 532): "its env badge when chart trading can act from it",
    ("D02", 534): "`Esc` never restores",
    ("D02", 826): "the cells' own sync groups only",
    ("D02", 830): "1+3 = the large cell left at 0.6",
    ("D02", 858): "`Esc` never restores a maximised panel or cell",
    ("D03", 166): "The focus affordance is drawn inside a constant frame.",
    ("D03", 168): "The kind, symbol, **interval**",
    ("D03", 169): "by kind and never by role",
    ("D03", 176): "Cancel focused",
    ("D03", 305): "| 9   | Arm state",
    ("D03", 323): "CMP-229's attention pill",
    ("D04", 227): "`Esc` never restores",
    ("D04", 234): "the arm state (`LOCKED`)",
    ("D06", 118): "the words become a count",
    ("D06", 557): "E15-D02 D-32 / A-13 removed the toggle",
    ("D06", 585): '"a cell\'s workspace group governs it"',
    ("D13", 307): "the §8 count lock",
    ("D13", 310): "SCR-027, 049, 150 and 153 carry the check on their own tickets",
    ("D15", 197): "out of scope — E15-D11",
    ("D15", 285): "published for E15-D11",
    ("M0", 36): "**Custom engine: GO.**",
    ("M0", 38): "rest on a harness page, not the engine",
    ("26", 129): "rendering into their own canvases in sequence",
    ("22", 21585): "PaneKind:",
    ("05", 85): "`Esc` (universal cancel)",
    ("05", 47): "Only active when focus is not inside a text input",
    ("05", 95): "**Roving tabindex** within composite widgets",
    ("E05D03", 74): "| 6   | Loading shimmer",
    ("E05D03", 90): "The static two-tone fill from the first frame",
    ("E30D05", 59): "cancels, closes and protective stop changes never do",
    ("E30D05", 75): "**R-4 R5 (arm carve-out",
    ("keymap", 303): '"dom.cancel_all"',
    ("keymap", 523): '"positions.close"',
    ("keymap", 535): '"positions.close_all"',
    ("keymap", 139): '"workspace.fullscreen_panel"',
    ("E11D02", 127): "The E06 spike gate is not met",
    ("E15.json", 470): '"key": "E15-K01"',
    ("E15.json", 822): '"key": "E15-S06"',
    ("14", 85): "rendered **disabled with a visible reason**",
    ("14", 734): "drag an SL/TP line to amend",
    ("D03", 321): "the arm toggle T2 `rbac.permission`",
    ("D03", 598): "a viewer's DOM arm toggle and order affordances",
    ("D03", 600): "a manager's DOM arm toggle on an unassigned account",
    ("D15", 69): "row **A36** (the environment in order-capable panel regions' _names_",
    ("D15", 282): "never a live value",
    ("E09D09", 32): "### 2.1 The decision rule",
    ("E09D09", 49): "**(2b) tooltip echo**",
    ("D12spec", 34): "| 640 × 400   | W3 · H3 | collapse",
    ("D12spec", 143): "### 6.4 Never shed",
}


def cites_in(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in CITE.finditer(text):
        key, a, b, rest = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2)), m.group(4)
        out.append((key, a, b))
        for c in CONT.finditer(rest or ""):
            out.append((key, int(c.group(1)), int(c.group(2) or c.group(1))))
    return out


def cite_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    seen: set[tuple[str, int]] = set()
    for name, text in docs(t):
        prose = "\n".join("" if ROW_META.match(ln) else ln for ln in lines(unfence(text)))
        for key, a, b in cites_in(prose):  # §C's meta lines name the queue base (G-AROW's)
            bl = lines(key_text(key))
            if len(bl) < 2:
                bad.append(f"{name}: `{key}` is unreadable at {BASE}")
                continue
            for n in sorted({a, b}):
                seen.add((key, n))
                if not 1 <= n <= len(bl) or not bl[n - 1].strip() or b < a:
                    bad.append(f"{name}: `{key}`:{n} is past the end or blank")
    for key, n in sorted(seen):
        if key in MOVING and (key, n) not in CITED:
            bad.append(f"`{key}`:{n} is not pinned by content (add its words to CITED)")
    for (key, n), words in CITED.items():
        bl = lines(key_text(key))
        if (key, n) not in seen:
            bad.append(f"the load-bearing cite `{key}`:{n} is not in the documents")
        elif not 1 <= n <= len(bl) or words not in bl[n - 1]:
            now = [k + 1 for k, ln in enumerate(bl) if words in ln]
            where = f"now at :{now[0]}" if len(now) == 1 else "found nowhere once"
            bad.append(f"`{key}`:{n} no longer holds {words!r} ({where})")
    return bad


SHA_OR_ID = re.compile(r"(?<![\w#/-])([0-9a-f]{10})(?![\w-])")
D13_TOKENS_SHA = "18d92caf3f"  # E15-D13's token PR, merged as #5075 (2026-10-30 14:15Z)
KNOWN_SHAS = frozenset({BASE, BQ_BASE, D13_TOKENS_SHA, D12_SPEC_SHA})
KNOWN_IDS = frozenset(
    {RULING_ID, LEDGER_ID, BQ_ID, D12_RULING, DELEGATION_ID, D13_RULING, DRYRUN_ID}
)


def pin_ref_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    for name, text in docs(t):
        for m in SHA_OR_ID.finditer(unfill(text)):
            ref = m.group(1)
            known = KNOWN_IDS if ref.isdigit() else KNOWN_SHAS
            if ref not in known:
                bad.append(f"{name}: {ref} is not a pinned sha or comment id")
    return bad


Unit = tuple[str, str, str]
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")


def pin_norm(text: str) -> str:
    return " ".join(text.split())


def unfill(text: str) -> str:
    """The text with each anchored value cut out (the pins never see a value)."""
    return ANCHORED.sub(lambda m: f"<!--={m.group(2)}-->", text)


def units(text: str, doc: str) -> list[Unit]:
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    region, k, fence = f"{doc}:(top)#1", 0, -1
    rows: dict[str, int] = {}
    buf: list[str] = []
    for raw in lines(unfill(text)):
        if fence >= 0:
            if raw == "```":
                digest = hashlib.sha256("\n".join(buf).encode("utf-8")).hexdigest()[:16]
                out.append((region, f"fence {fence}", f"{len(buf)} lines sha256:{digest}"))
                fence, buf = -1, []
            else:
                buf.append(raw)
            continue
        if FENCE.match(raw):
            k += 1
            fence = k
            continue
        m = HEADING.match(raw)
        if m:
            level = len(m.group(1))
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m.group(2)))]
            key = f"{doc}:" + " › ".join(p[1] for p in path)
            seen[key] = seen.get(key, 0) + 1
            region, k, rows = f"{key}#{seen[key]}", 0, {}
            out.append((region, "heading", pin_norm(raw)))
            continue
        if not raw.strip() or RULE_ROW.match(raw):
            continue
        if raw.lstrip().startswith("|"):
            cells = split_row(raw)
            lead = pin_norm(cells[0]) if cells else "(blank)"
            rows[lead] = rows.get(lead, 0) + 1
            loc = f"row {lead}" + (f"#{rows[lead]}" if rows[lead] > 1 else "")
            out.append((region, loc, " | ".join(pin_norm(c) for c in cells)))
            continue
        for x in FULL_STOP.split(raw.strip()):
            if x.strip():
                k += 1
                out.append((region, f"s{k}", pin_norm(x)))
    return out


def all_units(t: Texts) -> list[Unit]:
    return units(t.pack, "pack") + units(t.spec, "spec") + units(t.hand, "hand")


def write_pins(us: list[Unit]) -> str:
    head = (
        "# E15-D11 pins (every unit of the pack, the spec and the hand-off): region, location, "
        f"the exact normalised text; {len(us)} units.\n# Written by `--repin-ruled` only; "
        "`--check` reads it (never hand-edit; see the tool's G-RULED-PIN).\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in us)


def parse_pins(text: str) -> list[Unit]:
    out: list[Unit] = []
    for ln in lines(text):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def pin_problems(pinned: list[Unit], current: list[Unit]) -> list[str]:
    """One message per region that differs."""
    if not pinned:
        return ["the pins file is empty or missing (run --repin-ruled)"]
    bad: list[str] = []
    by_old: dict[str, list[tuple[str, str]]] = {}
    by_new: dict[str, list[tuple[str, str]]] = {}
    for r, loc, txt in pinned:
        by_old.setdefault(r, []).append((loc, txt))
    for r, loc, txt in current:
        by_new.setdefault(r, []).append((loc, txt))
    for r in by_new:
        if r not in by_old:
            bad.append(f"region '{r[-60:]}' is unpinned (new)")
    for r in by_old:
        if r not in by_new:
            bad.append(f"region '{r[-60:]}' deleted or renamed")
    for r, now_units in by_new.items():
        if r in by_old and now_units != by_old[r]:
            was = dict(by_old[r])
            what = "units moved or reordered"
            for loc, txt in now_units:
                if was.get(loc) != txt:
                    what = f"{loc} changed: {txt[:40]!r}"
                    break
            bad.append(f"'{r[-48:]}' {what}")
    return bad


# ---------------------------------------------------------------------------- public text

# The lane's public-text list, held reversed so this file never spells a word it forbids.
_HIDDEN = (
    "kael",
    "desopxe",
    "ssapyb",
    "tiolpxe",
    "kcatta",
    "elcaro",
    "laever",
    "dednuobnu",
    "doolf",
    "llats",
    "yrosivda",
    "ashg",
    "htua-erp",
)
BANNED = re.compile(
    "|".join(re.escape(w[::-1]) for w in _HIDDEN) + r"|\b" + "sod"[::-1] + r"\b", re.IGNORECASE
)
LOCAL_PATH = re.compile("/" + "(?:home|Users|mnt|tmp)" + r"/[^\s`)]+")
HOSTNAME = re.compile(r"\b[a-z0-9-]+\.(?:com|net|org|io)\b|\bpenpot\.[a-z0-9-]+\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
URL = re.compile(r"https?://", re.IGNORECASE)
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*(?:[\w-]+/[\w-]+)?#\d+", re.IGNORECASE
)
AGENTS = re.compile(r"\b(?:hpe|hcl)-worker-\d\b|\bsession [0-9a-f]{8}", re.IGNORECASE)


def public_problems(name: str, text: str) -> list[str]:
    bad: list[str] = []
    for rx, what in (
        (BANNED, "a word on the public-text list"),
        (LOCAL_PATH, "a local path"),
        (HOSTNAME, "a host name"),
        (UUID, "a uuid"),
        (URL, "a URL"),
        (CLOSING, "a closing keyword"),
        (AGENTS, "an agent or session name"),
    ):
        for m in rx.finditer(text):
            bad.append(f"{name}: {what} ({m.group(0)[:3]}…, offset {m.start()})")
    return bad


# ---------------------------------------------------------------------------- ruled words

STAMP_R365 = f"RULED (orchestrator, 2026-10-30, #365 ruling of record — {RULING_ID})"


def stamp_a(n: int) -> str:
    return f"RULED (orchestrator, 2026-10-30, #2701 ledger addendum A row A{n})"


# Every stamp site: a line of the pack opening with these words carries that stamp.
STAMP_SITES: dict[str, str] = {
    "- **BQ-01 / BQ-02.**": STAMP_R365,
    "- **BQ-03.**": STAMP_R365,
    "- **BQ-04 (A43).**": stamp_a(43),
    "- **BQ-05.**": STAMP_R365,
    "- **BQ-06.**": STAMP_R365,
    "- **BQ-07.**": STAMP_R365,
    "- **BQ-08.**": STAMP_R365,
    "- **BQ-09.**": STAMP_R365,
    "- **BQ-10.**": STAMP_R365,
    "- **BQ-11.**": STAMP_R365,
    "- **BQ-12 (A44).**": stamp_a(44),
    "- **BQ-13 / BQ-14.**": STAMP_R365,
    "- **BQ-15.**": STAMP_R365,
    "- **BQ-16 (A45).**": stamp_a(45),
    "- **BQ-17.**": STAMP_R365,
    "- **BQ-18 (A46).**": stamp_a(46),
    "- **BQ-19 / BQ-20 / BQ-21.**": STAMP_R365,
    "- **BQ-22.**": STAMP_R365,
    "- **BQ-23.**": STAMP_R365,
}
STAMP_ANY = re.compile(r"RULED \(orchestrator[^)]*\)")
STAMP_R20 = "RULED (orchestrator, 2026-10-30, #365 lane ruling R20)"
STAMPS = frozenset({STAMP_R365, STAMP_R20, *(stamp_a(n) for n in (43, 44, 45, 46))})
# The ruled words, by source (R365 = #365's ruling of record; A4346 = #2701 ledger addendum A rows
# A43 ... A46): each stands in the pack, and in the saved copy given with --source.
RULING_PINS: dict[str, tuple[str, ...]] = {
    "R365": (
        "the one-cell-at-a-time switcher (a CMP-042 tablist) as a display transform",
        "the chooser as CMP-217's cell-mode list with word names, never the dock's preset gallery",
        "≤ 7 interactive elements and 24 DOM nodes per cell header, counted by the tool",
        "the one-chrome-layer rendering as a recommendation with its reason",
        "never `color.focus.ring`, never a frame, never a box change",
        "`Esc` never restores",
        "E15-D12's threshold / window / copy rules / never-shed list cited, never re-decided",
        (
            "the dry run (rebuild a cell header from the spec alone) and the blind check by a "
            "reader outside E15"
        ),
        "no new token (PR 3 binds the dock tokens only after E15-D13's PR 2T merges)",
        "the spike gate recorded not met, SCR-049's sign-off line withheld, PR 3 still closes",
    ),
    "A4346": (
        "Each chart follows its own sync group.",
        "one linking model, not two",
        "Maximise this chart to trade.",
        "trading hotkeys never act on a non-maximised cell",
        "One-click trading disarmed: chart returned to the grid.",
        "a build never starts on SCR-049 without the multi-chart reading",
        "the tally 246 → 247 under the count lock's rule",
        '"CMP-081 in cell mode" (E15-S06\'s wording) and a CMP-221 `cell` variant are rejected',
    ),
}


def ruled_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    seen: dict[str, int] = {}
    for ln in lines(t.pack):
        for lead, stamp in STAMP_SITES.items():
            if ln.startswith(lead):
                seen[lead] = seen.get(lead, 0) + 1
                if stamp not in ln:
                    bad.append(f"{lead.strip('- *')}: the stamp is not {stamp!r}")
    for _, text in docs(t):
        for m in STAMP_ANY.finditer(text):
            if m.group(0) not in STAMPS:
                bad.append(f"a stamp in no ruled form: {m.group(0)!r}")
    for lead in STAMP_SITES:
        if seen.get(lead) != 1:
            bad.append(f"{lead.strip('- *')}: {seen.get(lead, 0)} sites (want 1)")
    src = dict(t.sources)
    flat = norm(t.pack)
    for name, pins in RULING_PINS.items():
        for pin in pins:
            if norm(pin) not in flat:
                bad.append(f"{name}: the ruled words {pin!r} are not in the pack")
            if name in src and norm(pin) not in norm(src[name]):
                bad.append(f"{name}: {pin!r} is not in the saved copy")
    return bad


# The spec's normative sentences the geometry gates stand behind (G-HEADER, G-FOCUS, G-CUE).
DISCLOSURE = (
    "1. the cell number goes",
    "2. the sync badge's axes words become a count",
    "3. the symbol and interval pickers drop their carets",
    "4. the sync badge shows its letter only",
)
NEVER = (
    "The symbol, the interval, the sync letter, the environment badge and the cell menu never drop."
)
FOCUS_RULE = (
    "The active cell is marked by a `border.thick` underline across its header row and its cell "
    "number in `font.weight.bold`, never by `color.focus.ring`, a frame round the cell or a change "
    "of the cell's box."
)
CUE_RULES = (
    "**One frame, no gutter.**",
    "**One header, light cell rows.**",
    "**Only the grid moves.**",
)


def in_order(text: str, phrases: tuple[str, ...]) -> bool:
    flat, at = norm(text), -1
    for p in phrases:
        nxt = flat.find(norm(p), at + 1)
        if nxt <= at:
            return False
        at = nxt
    return True


# ---------------------------------------------------------------------------- the deputy (lesson 3)

DEPUTY_LINE = (
    "still to be run by the orchestrator's deputy (a reader outside E15), requested at PR 3's READY"
)
DRYRUN_LINE = f"The run of record is #365 comment {DRYRUN_ID}"
DRYRUN_MET = f"MET: the deputy's run of record, #365 comment {DRYRUN_ID}"
APPENDIX = "## Appendix — the dry-run brief"
BLIND_WORDS = re.compile(r"blind check", re.IGNORECASE)
DRY_WORDS = re.compile(r"dry run", re.IGNORECASE)


def deputy_problems(pack: str) -> list[str]:
    """The dry run is recorded (the run of record cited, its lines MET); the blind check, which the
    record does not cover, stays open and the deputy's."""
    bad: list[str] = []
    s21 = norm(section(pack, "21."))
    if norm(DEPUTY_LINE) not in s21:
        bad.append("§21 does not leave the blind check to the deputy")
    if norm(DRYRUN_LINE) not in s21:
        bad.append("§21 does not cite the dry run's run of record")
    met = 0
    for ln in lines(section(pack, "20.")):
        if BLIND_WORDS.search(ln):
            if ln.startswith("- [x]"):
                bad.append(f"a DoD line on the blind check is ticked: {ln[:50]!r}")
        elif DRY_WORDS.search(ln) and ln.startswith("- ["):
            met += 1
            if not ln.startswith("- [x]") or norm(DRYRUN_MET) not in norm(ln):
                bad.append(f"the dry run's DoD line is not MET citing the record: {ln[:50]!r}")
    if met != 1:
        bad.append(f"{met} DoD lines on the dry run (want 1)")
    for r in table_rows(section(pack, "Acceptance")):
        row = " ".join(r)
        if BLIND_WORDS.search(row):
            if "[ ]" not in r[-1]:
                bad.append(f"the AC row {r[0][:30]!r} is not left open `[ ]`")
        elif DRY_WORDS.search(row) and norm(DRYRUN_MET) not in norm(r[-1]):
            bad.append(f"the AC row {r[0][:30]!r} is not MET citing the record")
    body = pack.split(APPENDIX, 1)
    if len(body) != 2 or "```text" not in body[1]:
        bad.append("the appendix with the verbatim brief is missing")
    return bad


# ---------------------------------------------------------------------------- PR modes


def pr2_text(t: Texts, file: str) -> str | None:
    named = queue_base(file)
    if named is None:
        return None
    return apply_rows(dict(t.mbase).get(file, ""), named, a_rows(t.pack)[0], file)


def untouched_problems(t: Texts) -> list[str]:
    if t.changed is None:
        return ["git cannot name the changed paths (fail closed)"]
    if any(p in t.changed for p in OWN_PATHS if p != PINS_REL):  # PR 1
        return [
            f"PR 1 changes {p}, not one of the pack's five" for p in t.changed if p not in OWN_PATHS
        ]
    allowed = (*TARGETS.values(), PINS_REL)
    bad = [f"PR 2 changes {p}, not `14`, `15` or the pins" for p in t.changed if p not in allowed]
    now = dict(t.now)
    for key, rel in TARGETS.items():
        if rel not in t.changed:
            continue
        want = pr2_text(t, key)
        if want is None:
            bad.append(f"PR 2: a §C row for `{key}` cannot be re-pointed at the merge-base")
        elif now.get(key) != want:
            bad.append(f"PR 2: `{key}` is not the merge-base with §C applied, byte for byte")
    if PINS_REL in t.changed and t.pins != write_pins(all_units(t)):
        bad.append("PR 2: the pins rewrite is not byte-exact (--repin-ruled)")
    return bad


# ---------------------------------------------------------------------------- values


def count_values(t: Texts) -> dict[str, str]:
    rows = a_rows(t.pack)[0]
    ac1, _ = ac1_scan(t)
    v = {
        "COUNT:arows": str(len(rows)),
        "COUNT:arows.14": str(sum(r.file == "14" for r in rows)),
        "COUNT:arows.15": str(sum(r.file == "15" for r in rows)),
        "COUNT:crows": str(len(crows(t.pack))),
        "COUNT:gates": str(len(GATES)),
        "COUNT:mutations": str(len(MUTATIONS)),
        "COUNT:probes": str(len(PROBES)),
        "COUNT:copy": str(len(deck(t.spec))),
        "COUNT:names": str(len(name_rows(t.hand))),
        "COUNT:ac1.values": str(sum(ac1.values())),
        "COUNT:ac1.anchored": str(ac1["anchored"]),
        "COUNT:ac1.token": str(ac1["token"]),
        "COUNT:ac1.residual": str(ac1["residual"]),
        "COUNT:ac1.exceptions": str(len(exceptions(t.pack))),
    }
    v.update(ledger_counts(t.pack))
    return v


@cache
def fixed_values() -> tuple[tuple[str, str], ...]:
    v = budget_values()
    v.update(colour_values())
    v.update(cue_values())
    return tuple(sorted(v.items()))


def compute(t: Texts) -> dict[str, str]:
    v = dict(fixed_values())
    v.update(count_values(t))
    return v


def code_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"`[^`\n]*`", line)]


def fill(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []
    out = []
    for ln in lines(text):
        spans = code_spans(ln)
        pieces, last = [], 0
        for m in PLACEHOLDER.finditer(ln):
            if any(a <= m.start() < b for a, b in spans):
                continue
            pieces.append(ln[last : m.start()])
            key = m.group(1)
            if key in values:
                pieces.append(f"{values[key]}<!--={key}-->")
            else:
                missing.append(key)
                pieces.append(m.group(0))
            last = m.end()
        pieces.append(ln[last:])
        out.append("".join(pieces))
    return "\n".join(out), missing


def anchored(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in ANCHORED.finditer(unfence(text))]


# ---------------------------------------------------------------------------- findings and gates


@dataclass(frozen=True)
class Finding:
    gate: str
    level: str
    msg: str


def fails(gate: str, problems: list[str]) -> list[Finding]:
    return [Finding(gate, "FAIL", p) for p in problems]


def g_anchor(t: Texts) -> list[Finding]:
    v = compute(t)
    bad: list[str] = []
    for name, text in docs(t):
        for m in PLACEHOLDER.finditer(re.sub(r"`[^`\n]*`", "", unfence(text))):
            bad.append(f"{name}: {{{{{m.group(1)}}}}} is not filled (run --fill)")
        for got, key in anchored(text):
            want = v.get(key)
            if want is None:
                bad.append(f"{name}: {key} is not a value the tool computes")
            elif got != want:
                bad.append(f"{name}: {key} reads {got!r}, the tool computes {want!r}")
    return fails("G-ANCHOR", bad)


RATIO = re.compile(r"(?<![\w.])\d+\.\d+:1\b")
BAR_FIGURES = ("3:1", "4.5:1", "7:1")
GEOMETRY = re.compile(r"(?<![\w.])\d{2,4}×\d{2,4}(?![\w.])")
WINDOWS = ("1280×800", "1920×1080", "640×400")  # window sizes, not measurements


def g_figure(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for name, text in docs(t):
        plain = ANCHOR.sub("", ANCHORED.sub("", unfence(text)))
        for m in RATIO.finditer(plain):
            if m.group(0) not in BAR_FIGURES:
                bad.append(f"{name}: the ratio {m.group(0)} is typed by hand (anchor it)")
        for m in GEOMETRY.finditer(plain):
            if m.group(0) not in WINDOWS:
                bad.append(f"{name}: the size {m.group(0)} is typed by hand (anchor it)")
    return fails("G-FIGURE", bad)


def g_budget(t: Texts) -> list[Finding]:
    bad = budget_problems()
    keys = {k for _, k in anchored(t.pack)}
    leads = {r[0] for r in table_rows(section(t.pack, "3."))}
    for arr, label in ARR_LABELS.items():
        if label not in leads:
            bad.append(f"the pack's §3 tables have no row {label!r} ({arr})")
        for name in SLOTS:
            for dens in DENSITIES:
                key = f"BUDGET:cell.{arr}.{name}.{dens}"
                if key not in keys:
                    bad.append(f"the pack does not anchor {key}")
    return fails("G-BUDGET", bad)


def g_header(t: Texts) -> list[Finding]:
    bad = header_problems()
    if not in_order(t.spec, DISCLOSURE):
        bad.append("the spec does not state the four disclosure steps in order")
    if norm(NEVER) not in norm(t.spec):
        bad.append("the spec does not state the never-dropped five")
    return fails("G-HEADER", bad)


def g_focus(t: Texts) -> list[Finding]:
    bad = focus_problems()
    if norm(FOCUS_RULE) not in norm(t.spec):
        bad.append("the spec does not state the active-cell rule")
    return fails("G-FOCUS", bad)


def g_cue(t: Texts) -> list[Finding]:
    bad = cue_problems()
    if not in_order(t.spec, CUE_RULES):
        bad.append("the spec does not state the three cues in order")
    return fails("G-CUE", bad)


GATES: tuple[tuple[str, Callable[[Texts], list[Finding]]], ...] = (
    ("G-ANCHOR", g_anchor),
    ("G-FIGURE", g_figure),
    ("G-CITE", lambda t: fails("G-CITE", cite_problems(t))),
    ("G-PIN", lambda t: fails("G-PIN", pin_ref_problems(t))),
    ("G-UNTOUCHED", lambda t: fails("G-UNTOUCHED", untouched_problems(t))),
    ("G-AROW", lambda t: fails("G-AROW", arow_problems(*a_rows(t.pack)))),
    ("G-LEDGER", lambda t: fails("G-LEDGER", ledger_problems(t))),
    ("G-BUDGET", g_budget),
    ("G-HEADER", g_header),
    ("G-FOCUS", g_focus),
    ("G-CUE", g_cue),
    ("G-CONTRAST", lambda t: fails("G-CONTRAST", contrast_problems())),
    ("G-NAME", lambda t: fails("G-NAME", name_problems(t.hand))),
    ("G-COPY", lambda t: fails("G-COPY", copy_problems(t.spec))),
    ("G-AC1", lambda t: fails("G-AC1", ac1_scan(t)[1])),
    ("G-RULED", lambda t: fails("G-RULED", ruled_problems(t))),
    (
        "G-RULED-PIN",
        lambda t: fails("G-RULED-PIN", pin_problems(parse_pins(t.pins), all_units(t))),
    ),
    (
        "G-PUBLIC",
        lambda t: fails("G-PUBLIC", [p for n, x in docs(t) for p in public_problems(n, x)]),
    ),
    ("G-CROWS", lambda t: fails("G-CROWS", crow_problems(t.pack))),
    ("G-ENTRY", lambda t: fails("G-ENTRY", entry_problems(t.pack))),
    ("G-DEPUTY", lambda t: fails("G-DEPUTY", deputy_problems(t.pack))),
    ("G-MUTLIST", lambda t: fails("G-MUTLIST", mutlist_problems(t.pack))),
    ("G-ARM", lambda t: fails("G-ARM", arm_problems(t))),
    ("G-DESC", lambda t: fails("G-DESC", desc_problems(t))),
    ("G-T2", lambda t: fails("G-T2", t2_problems(t))),
)


# E15-D15 R-5 item 2 (`D15`:282): a description is never a live value. A cell's description is
# its position, its sync group and axes, the feed's state word only when degraded, and its state
# words: after the position sentence no number, no mark and no last, no healthy feed word ("Live",
# which collides with the environment word; RULED, #365 lane ruling R20); the environment word
# only in the name.
DESC_RULE = "- **The description, assembled in one order:**"
DESC_QUOTE = re.compile(r'"(Chart [^"]*)"')
POSITION = re.compile(r"Chart (?:\{position\} of \{count\}|\d of \d)\. ")
LIVE_VALUE = re.compile(r"\d|\bmark\b|\blast\b|\bDemo\b|\bMixed\b|\bLive\b", re.IGNORECASE)


def descriptions(t: Texts) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for ln in lines(t.spec):
        if ln.startswith(DESC_RULE):
            out += [("spec §6", d) for d in DESC_QUOTE.findall(ln)]
    for r in name_rows(t.hand):
        if r[1] == "`region`":
            out += [(f"hand-off {r[0]}", d) for d in DESC_QUOTE.findall(r[3])]
    return out


def desc_problems(t: Texts) -> list[str]:
    got = descriptions(t)
    bad: list[str] = []
    for where in ("spec §6", "hand-off"):
        if sum(w.startswith(where) for w, _ in got) < 2:
            bad.append(f"{where}: fewer than two cell descriptions to check")
    for where, d in got:
        m = POSITION.match(d)
        if m is None:
            bad.append(f"{where}: the description does not open with the position: {d[:40]!r}")
            continue
        hit = LIVE_VALUE.search(d[m.end() :])
        if hit:
            bad.append(f"{where}: {hit.group(0)!r} after the position (a live value): {d[:50]!r}")
    return bad


# G-T2 (`.claude/rules/32-design-specs.md`): the maximised cell's CMP-229 has its read-only form
# for the role legs, `14` §0.5 rule 5 and E09-D09 §2.1 cited, rendering 2b named, and the
# component rows naming CMP-229, CMP-079 and CMP-019's `lock`.
T2_WORDS = (
    "`14` §0.5 rule 5",
    "E09-D09 §2.1",
    "rendering 2b",
    "CMP-079 RbacGate",
    "CMP-019 `lock`",
    "CMP-016",
    'aria-disabled="true"',
    "in the DOM at mount",
    "one grid-header notice",
    "`rbac.view_as`",
    "`rbac.permission`",
    "`rbac.account`",
)
T2_ROWS = ("A-4", "A-8", "A-11")
T2_COMPONENTS = ("CMP-229", "CMP-079", "CMP-019", "`lock`")


def t2_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    s8 = section(t.spec, "8.")
    for w in T2_WORDS:
        if w not in s8:
            bad.append(f"spec §8: the T2 form lacks {w!r}")
    if "T2" not in section(t.hand, "3."):
        bad.append("hand-off §3: no T2 row for the maximised cell's arm control")
    for row in T2_ROWS:
        block = t.pack.split(f"#### {row} ", 1)[-1].split("#### A-", 1)[0]
        for c in T2_COMPONENTS:
            if c not in block:
                bad.append(f"{row}: {c} is not named (G-T2.6)")
    return bad


CARVE_OUT = (
    "LOCKED covers order entry and arming only: cancel, close, flatten and setting or tightening a "
    "stop are never gated, hidden or blocked by the grid or by any cell's state, maximised or not "
    "(they live on the positions and orders surfaces, and their own hotkeys keep working in every "
    "grid state)."
)
ARM_RULES = (
    "**Protective actions are never gated**",
    "**The maximised cell arms as a chart panel does.**",
    "**Restore while armed.**",
    "**If the disarm fails**",
)
ARM_STRINGS = ("Disarming chart trading…", "Chart trading is still armed on chart 3.")
ARM_STORIES = ("MaximisedArmed", "Disarming", "DisarmFailed")


def arm_problems(t: Texts) -> list[str]:
    bad: list[str] = []
    for name, text in docs(t):
        if norm(CARVE_OUT) not in norm(text):
            bad.append(f"{name}: the C-2.6 carve-out sentence is missing or weakened")
    if not in_order(t.spec, ARM_RULES):
        bad.append(
            "the spec does not state the carve-out, the maximised arm, the restore and the failure"
        )
    strings = [r[1] for r in deck(t.spec)]
    for want in ARM_STRINGS:
        if not any(want in x for x in strings):
            bad.append(f"the arm string {want!r} is not in the deck")
    a8 = t.pack.split("#### A-8 ", 1)[-1].split("#### A-9 ", 1)[0]
    forbidden = [ln for ln in lines(a8) if ln.startswith("- **Forbidden**:")]
    if len(forbidden) != 1 or norm(CARVE_OUT) not in norm(forbidden[0]):
        bad.append("A-8: the C-2.6 carve-out sentence is not quoted in CMP-253's Forbidden field")
    for name, text in (("hand-off", section(t.hand, "5.")), ("A-8", a8)):
        for story in ARM_STORIES:
            if not re.search(rf"\b{story}\b", text):
                bad.append(f"{name}: the story {story} is missing")
    return bad


def mutation_paragraph() -> str:
    parts = [f"**{g}:** M-{n} {d}" for n, (g, d, _) in enumerate(MUTATIONS, 1)]
    return "; ".join(parts) + "."


def mutlist_problems(pack: str) -> list[str]:
    return [] if mutation_paragraph() in pack else ["§19 is not the tool's mutation list (--fill)"]


def run(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for _, fn in GATES:
        out += fn(t)
    if any(f.level == "FAIL" and f.gate != "G-RULED-PIN" for f in out):
        out = [replace(f, level="NOTE") if f.gate == "G-RULED-PIN" else f for f in out]
    return out


def changed_paths() -> tuple[str, ...] | None:
    mb = git("merge-base", "HEAD", "origin/main")
    if mb is None:
        return None
    committed = git("diff", "--name-only", mb.strip(), "--")
    status = git("status", "--porcelain", "--untracked-files=all")
    if committed is None or status is None:
        return None
    paths = {p for p in committed.split("\n") if p}
    for ln in status.split("\n"):
        if ln.strip():
            paths.add(ln[3:].split(" -> ")[-1].strip('"'))
    return tuple(sorted(paths))


def load(sources: tuple[tuple[str, str], ...] = ()) -> Texts:
    mb = git("merge-base", "HEAD", "origin/main")
    mbase = (
        tuple((k, git("show", f"{mb.strip()}:{rel}") or "") for k, rel in TARGETS.items())
        if mb
        else ()
    )
    return Texts(
        pack=read(PACK_REL),
        spec=read(SPEC_REL),
        hand=read(HAND_REL),
        pins=read(PINS_REL),
        changed=changed_paths(),
        now=tuple((k, read(rel)) for k, rel in TARGETS.items()),
        mbase=mbase,
        sources=sources,
    )


# ---------------------------------------------------------------------------- the self-test


def _sub(field_name: str, old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, field_name)
        if text.count(old) < 1:
            raise SystemExit(f"self-test: {old[:50]!r} not found in {field_name}")
        return replace(t, **{field_name: text.replace(old, new, 1)})

    return f


_MISSING = object()
_PATCHES: list[tuple[dict[Any, Any], Any, object]] = []


def _patch(target: dict[Any, Any], key: Any, val: Any) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        _PATCHES.append((target, key, target.get(key, _MISSING)))
        target[key] = val
        return t

    return f


def _restore() -> None:
    while _PATCHES:
        target, key, old = _PATCHES.pop()
        if old is _MISSING:
            target.pop(key, None)
        else:
            target[key] = old


_WORD = "kael"[::-1]
_CLOSE = "Clo" + "ses #365"

MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    (
        "G-ANCHOR",
        "hand-edit the 3×3 dock case's step",
        _sub("pack", "<!--=BUDGET:case.dock1280.step-->", "9<!--=BUDGET:case.dock1280.step-->"),
    ),
    (
        "G-FIGURE",
        "type a ratio by hand in §6",
        _sub("pack", "**The measurement.**", "**The measurement (2.50:1 typed).**"),
    ),
    (
        "G-CITE",
        "move the §5.13 cite past the end of E15-D02",
        _sub("pack", "`D02`:530", "`D02`:99530"),
    ),
    ("G-PIN", "name an unpinned sha in §0", _sub("pack", f"`{BASE}`", "`0123abcdef`")),
    (
        "G-UNTOUCHED",
        "simulate an edit to `16` in PR 1",
        lambda t: replace(t, changed=(t.changed or ()) + ("docs/plan/16-design-system-brief.md",)),
    ),
    (
        "G-AROW",
        "alter one byte of A-1's Old",
        _sub(
            "pack", 'and a "propagate symbol" toggle; used', 'and a "propagate symbol" toggle, used'
        ),
    ),
    (
        "G-LEDGER",
        "point a ledger row at a §C row that does not exist",
        _sub("pack", "| A-1   ", "| A-99  "),
    ),
    (
        "G-BUDGET",
        "relabel the custom arrangement's row",
        _sub("pack", "| Custom 2×3 ", "| Custom 3×2 "),
    ),
    (
        "G-HEADER",
        "swap the disclosure order in the spec",
        _sub("spec", DISCLOSURE[0], "1. the sync badge shows its letter only"),
    ),
    (
        "G-FOCUS",
        "mark the active cell with the focus colour in the spec",
        _sub(
            "spec", "never by `color.focus.ring`, a frame", "by `color.focus.ring`, never a frame"
        ),
    ),
    ("G-CUE", "drop the third cue from the spec", _sub("spec", CUE_RULES[2], "**The grid.**")),
    ("G-CONTRAST", "gate the reported divider at a bar of 1.4", _patch(BARS, "divider", 1.4)),
    (
        "G-NAME",
        "shorten an interval in the name table",
        _sub("hand", '"Chart, BTCUSDT 4 hours, Live"', '"Chart, BTCUSDT 4 hours 4h, Live"'),
    ),
    (
        "G-COPY",
        "drop p95 and its source from the running line",
        _sub("spec", "(p95, last minute, measured)", "(last minute)"),
    ),
    (
        "G-AC1",
        "type an unbound px value in the spec",
        _sub("spec", "## 2. ", "## 2. (a 5 px gap) "),
    ),
    (
        "G-RULED",
        "drop A44's stamp from BQ-12",
        _sub(
            "pack",
            "(A44).** RULED (orchestrator, 2026-10-30, #2701 ledger addendum A row A44):",
            "(A44).**",
        ),
    ),
    (
        "G-RULED-PIN",
        "reword a sentence of the hand-off",
        _sub("hand", "Builders read the spec first.", "Builders read the spec."),
    ),
    (
        "G-PUBLIC",
        "paste a word on the list into the spec",
        _sub("spec", "## 1. ", f"## 1. ({_WORD}) "),
    ),
    ("G-CROWS", "renumber C-15", _sub("pack", "| C-15 |", "| C-51 |")),
    (
        "G-ENTRY",
        "drop CMP-253's Motion spec field name",
        _sub("pack", "- **Motion spec**:", "- **Motion**:"),
    ),
    (
        "G-DEPUTY",
        "tick the blind check's DoD line",
        _sub("pack", "- [ ] The blind check", "- [x] The blind check"),
    ),
    ("G-MUTLIST", "edit §19's list", _sub("pack", "**G-ANCHOR:** M-1", "**G-ANCHOR:** M-0")),
    (
        "G-ARM",
        "remove the C-2.6 carve-out sentence from the spec",
        _sub("spec", CARVE_OUT, "LOCKED covers every chart action."),
    ),
    (
        "G-DESC",
        "put the mark back into the spec's description copy",
        _sub(
            "spec", "A: symbol and crosshair. Chart trading", "A: symbol. Feed: Live. Chart trading"
        ),
    ),
    (
        "G-T2",
        "drop rendering 2b from the spec's T2 form",
        _sub("spec", "rendering 2b", "a rendering"),
    ),
)


def _pr2_extra(t: Texts) -> Texts:
    now = dict(t.now)
    now["14"] = (pr2_text(t, "14") or "") + " "
    return replace(t, changed=(SCREENS_REL,), now=tuple(now.items()))


def _pr2_pins(t: Texts) -> Texts:
    now = dict(t.now)
    now["14"] = pr2_text(t, "14") or ""
    return replace(t, changed=(SCREENS_REL, PINS_REL), now=tuple(now.items()), pins=t.pins + "\n")


def _source_short(t: Texts) -> Texts:
    return replace(t, sources=(("A4346", " ".join(RULING_PINS["A4346"][:-1])),))


PROBES: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-UNTOUCHED", "PR 2 with one byte more than §C in `14`", _pr2_extra),
    ("G-UNTOUCHED", "PR 2 with a pins rewrite that is not byte-exact", _pr2_pins),
    ("G-UNTOUCHED", "git cannot name the changed paths", lambda t: replace(t, changed=None)),
    ("G-PUBLIC", "a closing keyword in §20", _sub("pack", "## 20. ", f"## 20. ({_CLOSE}) ")),
    ("G-ANCHOR", "an unfilled placeholder in §3", _sub("pack", "## 3. ", "## 3. {{COUNT:arows}} ")),
    ("G-RULED", "a saved copy of A43 ... A46 lacking one ruled phrase", _source_short),
    (
        "G-CITE",
        "a cite into `15` that is not pinned by content",
        _sub("pack", "## 15. ", "## 15. (`15`:2770) "),
    ),
    (
        "G-CITE",
        "a pinned cite whose words moved",
        _patch(CITED, ("14", 1141), "propagate the symbol"),
    ),
    (
        "G-DEPUTY",
        "§21 no longer leaves the blind check to the deputy",
        _sub("pack", DEPUTY_LINE, "run"),
    ),
    (
        "G-DEPUTY",
        "the dry run's DoD line drops the record id",
        _sub(
            "pack",
            f"- [x] The dry run rebuilding a cell header from the spec alone: {DRYRUN_MET}",
            "- [x] The dry run rebuilding a cell header from the spec alone: MET",
        ),
    ),
    ("G-DEPUTY", "§21 drops the run of record", _sub("pack", DRYRUN_LINE, "The run")),
    (
        "G-ARM",
        "drop the carve-out from A-8's Forbidden field",
        _sub("pack", f'(C-2.6): "{CARVE_OUT}"', "(C-2.6)"),
    ),
    ("G-COPY", "a subsystem word in a deck string", _sub("spec", "this device", "this GPU")),
    (
        "G-ARM",
        "weaken the carve-out in the hand-off",
        _sub(
            "hand", "are never gated, hidden or blocked", "are not usually gated, hidden or blocked"
        ),
    ),
    ("G-ARM", "drop the Disarming story from the hand-off", _sub("hand", ", Disarming,", ",")),
    (
        "G-ARM",
        "drop the disarm-failure path from the spec",
        _sub("spec", "**If the disarm fails**", "**Later**"),
    ),
    (
        "G-DESC",
        "a demo cell's description repeats its environment",
        _sub("hand", "Sync group B: interval and crosshair.", "Demo. Sync group B: interval."),
    ),
    (
        "G-T2",
        "A-4 drops CMP-079",
        _sub("pack", "CMP-079 RbacGate (the maximised", "(the maximised"),
    ),
    (
        "G-NAME",
        "the sync group in a cell's name",
        _sub("hand", '"Chart, BTCUSDT 4 hours, Live"', '"Chart, BTCUSDT 4 hours, sync group A"'),
    ),
)


def fail_keys(fs: list[Finding]) -> list[tuple[str, str]]:
    return [(f.gate, f.msg) for f in fs if f.level == "FAIL"]


def digests() -> dict[str, str]:
    return {p: hashlib.sha256(read(p).encode("utf-8")).hexdigest() for p in OWN_PATHS}


def self_test(t: Texts) -> list[str]:
    before = digests()
    base = fail_keys(run(t))
    bad: list[str] = []
    for label, items in (("M", MUTATIONS), ("P", PROBES)):
        for n, (gate, desc, fn) in enumerate(items, 1):
            try:
                got = fail_keys(run(fn(t)))
            finally:
                _restore()
            new = [k for k in got if k not in base]
            if len(new) != 1 or new[0][0] != gate:
                shown = ", ".join(f"{g}: {m[:60]}" for g, m in new[:4]) or "none"
                bad.append(f"{label}-{n} ({gate}, {desc}): {len(new)} new FAIL(s) [{shown}]")
    if fail_keys(run(t)) != base:
        bad.append("self-test: a re-run does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


# ---------------------------------------------------------------------------- main


def parse_sources(items: list[str]) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for item in items:
        name, _, path = item.partition("=")
        if name not in RULING_PINS or not path:
            raise SystemExit(f"--source takes NAME=FILE with NAME one of {sorted(RULING_PINS)}")
        out.append((name, Path(path).read_text(encoding="utf-8")))
    return tuple(out)


def write_if_changed(rel: str, text: str) -> bool:
    if read(rel) == text:
        return False
    (ROOT / rel).write_text(text, encoding="utf-8")
    return True


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--json", action="store_true", help="print the values and findings as JSON")
    ap.add_argument("--fill", action="store_true", help="fill the placeholders and §19's list")
    ap.add_argument("--self-test", action="store_true", help="one mutation per gate, the probes")
    ap.add_argument("--repin-ruled", action="store_true", help="rewrite the pins file")
    ap.add_argument("--a-rows", action="store_true", help="print §C as JSON, a target per row")
    ap.add_argument("--source", action="append", default=[], help="NAME=FILE, a saved ruling")
    args = ap.parse_args(argv)
    if any(not key_text(k) for k in KEYS):
        print(f"FAIL [G-CITE] the inputs are unreadable at {BASE} (fetch first)")
        return 1
    t = load(parse_sources(args.source))
    if args.a_rows:
        print(json.dumps(export(a_rows(t.pack)[0]), ensure_ascii=False, indent=1))
        return 0
    if args.fill:
        for rel in (PACK_REL, SPEC_REL, HAND_REL):
            text = ANCHORED.sub(lambda m: "{{" + m.group(2) + "}}", read(rel))
            text = re.sub(r"(?m)^\*\*G-ANCHOR:\*\* M-\d .*$", mutation_paragraph(), text)
            write_if_changed(rel, text)
        t = load(t.sources)
        v = compute(t)
        for rel in (PACK_REL, SPEC_REL, HAND_REL):
            text, missing = fill(read(rel), v)
            for key in missing:
                print(f"no value for {key} in {rel}")
            write_if_changed(rel, text)
        t = load(t.sources)
    if args.repin_ruled:
        if any(PLACEHOLDER.search(re.sub(r"`[^`\n]*`", "", unfence(x))) for _, x in docs(t)):
            print("refused: a placeholder is unfilled (run --fill first)")
            return 1
        write_if_changed(PINS_REL, write_pins(all_units(t)))
        t = load(t.sources)
    found = run(t)
    st = self_test(t) if args.self_test else []
    if args.json:
        payload: dict[str, object] = {
            "values": compute(t),
            "findings": [f"{f.level} [{f.gate}] {f.msg}" for f in found],
        }
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        out = [f"{f.level} [{f.gate}] {f.msg}" for f in found]
        n_fail = sum(f.level == "FAIL" for f in found)
        n_warn = sum(f.level == "WARN" for f in found)
        rows = a_rows(t.pack)[0]
        out.append(
            f"gates: {len(GATES)}; FAIL {n_fail}, WARN {n_warn}; §C rows {len(rows)} "
            f"({sum(r.file == '14' for r in rows)} to `14`, {sum(r.file == '15' for r in rows)} "
            "to `15`)"
        )
        if args.self_test:
            out += [f"FAIL [self-test] {x}" for x in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (one per "
                f"gate) and {len(PROBES)} probes, each one new FAIL from its gate; a re-run "
                "reproduces the base result; files on disk unchanged"
            )
        print("\n".join(out))
    failed = any(f.level == "FAIL" for f in found) or bool(st)
    return 1 if failed and (args.check or args.self_test) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
