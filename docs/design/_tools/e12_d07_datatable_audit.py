#!/usr/bin/env python3
"""E12-D07 (#242) audit: SCR-045, the data-table alternative for every bar mode (text first).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the plan texts and merged design texts the spec cites,
`22`'s `Bar` and `BarType`, `23`'s bars item, and the token JSON; and, from the working tree, the
spec `docs/design/E12/E12-D07.md`, its hand-off and the pins file. Its form follows the E08-D08 and
E33-D06 tools (the same modes, the anchored values, the default-deny pins and the mutations).

1. **Values.** Every `{{KIND:key}}` placeholder is written by `--fill` as `VALUE<!--=KIND:key-->`:
   COUNT (rows of the spec's and the hand-off's own tables), CITE (a figure parsed from the cited
   line at the base), WIDTH (a width derived from E11-D04's measured metrics and the spec's column
   table) and CONTRAST (a WCAG 2.x ratio over the resolved tokens). `--check` re-derives each
   anchored value (G-ANCHOR) and FAILs a placeholder left behind or a stray HTML comment
   (G-MARKER). `--fill` also writes the ruled paragraphs ({{RULING}}) and the mutation rows
   ({{MUTATIONS}}) from this file's constants.
2. **Cites.** Every `NN`:line and KEY:line cite of both documents resolves to a non-blank line at
   the base, E12-D08's at its merge commit (G-CITE); every "verbatim" copy string occurs on its
   cited line (G-QUOTE); every Old fragment of the hand-off's A-rows occurs verbatim on its cited
   line (G-AROW).
3. **Gates.** One FAIL line per gate: G-RULED (the ruling's paragraphs verbatim in the RULED
   section), G-PENDING (BQ-13 and D07-Q1 carry the later RULED stamp), G-BOARDS (at most ten
   boards, at most three light twins, every board PENDING, P&F and Heikin-Ashi on no board),
   G-COLUMNS (the mode columns equal `22`'s `BarType` without `pnf` and `heikin_ashi`; each cell
   marked tier + field / derived or "—"; every named field exists in `22`'s `Bar` and `23`'s
   bars item; a field cell names exactly one field), G-STATE (the ruled lowercase vocabulary, in
   order; no capitalised state word outside the C-rows), G-CONTRAST (the pairs and their bars),
   G-HEUR (every finding marked `(heuristic)`), G-WALK (at most ten walkthrough items), G-OWNER
   (G-ledger owners are tickets or spec owners, never an agent), G-DRYRUN (the dry-run roles of
   the spec and the hand-off agree), G-UNMERGED (no path into an unmerged sibling), G-URL (no URL,
   host or local path), G-UNTOUCHED (only this ticket's four files differ from the merge base
   with origin/main), G-BUDGET (600 spec lines, 150 hand-off lines) and G-MUTLIST (the spec's §16
   equals this tool's list).
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of both documents
   (each heading, table row by its lead cell and prose line, by heading path and occurrence, with
   a line-shape tag per region) in `e12_d07_ruled_pins.txt`. Anchored values are cut out of the
   pinned text (G-ANCHOR owns them). `--repin-ruled` is the only writer and refuses while a
   placeholder is unfilled. A pin finding in a region another gate already FAILs prints as NOTE.
5. **--self-test** applies every mutation (M-n) and pin probe (P-n) in memory with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names; the
   texts on disk are checked byte-identical afterwards (sha256). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e12_d07_datatable_audit.py --check [--fill]
  python3 -I docs/design/_tools/e12_d07_datatable_audit.py --self-test
  python3 -I docs/design/_tools/e12_d07_datatable_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "83f18fd4c"  # origin/main when the spec was written; every cite is read here

SPEC_REL = "docs/design/E12/E12-D07.md"
HAND_REL = "docs/design/E12/E12-D07-handoff.md"
TOOL_REL = "docs/design/_tools/e12_d07_datatable_audit.py"
PIN_REL = "docs/design/_tools/e12_d07_ruled_pins.txt"
OWN = (SPEC_REL, HAND_REL, TOOL_REL, PIN_REL)
SPEC_BUDGET = 600
HAND_BUDGET = 150

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
}
CITE_FILES = {
    "D04E11": "docs/design/E11/E11-D04.md",
    "D07E11": "docs/design/E11/E11-D07.md",
    "D02": "docs/design/E12/E12-D02.md",
    "D03": "docs/design/E12/E12-D03.md",
    "D05": "docs/design/E12/E12-D05.md",
    "D06": "docs/design/E12/E12-D06.md",
    "D08": "docs/design/E12/E12-D08.md",
    "D09": "docs/design/E12/E12-D09.md",
    "E12J": "docs/plan/backlog/E12.json",
    "E11J": "docs/plan/backlog/E11.json",
}
UNMERGED_PATHS = ("E12-D10.md", "E12-D11.md")
# E12-D08 merged after the base (#4933): its cites are read at its merge commit, every other at BASE.
FILE_BASE = {"docs/design/E12/E12-D08.md": "80e45841d"}
DS_SRC_REL = "packages/ui/tokens"
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}

RULING_ID = "6487163429"
BQ_LIST_ID = "6486938979"
# BQ-13 was PROPOSED in the ruling of record and ruled later (the round-1 review on #4955).
BQ13_RULED = (
    "RULED (orchestrator, 2026-10-29 13:58Z, the round-1 review record on #4955, under the owner"
    " directive of 07:05Z, #2701 comment 6490317249)"
)
# The ruling of record, its bold marks dropped (comment 6487163429, 2026-10-29 03:34Z).
RULED: tuple[str, ...] = (
    (
        "Ruling on BQ-0..BQ-13 (issuecomment-6486938979, cited at `728b4254d`) — orchestrator,"
        " 2026-10-29 03:34Z. This comment is the ruling of record; the list is the question text."
    ),
    (
        "Bulk: BQ-0 confirmed as written (text first, `Refs #242` + `Partial: PR 1 of 2`; E12-D08 /"
        ' D10 / D11 named only with their ruled points cited "ruled, not merged" + a late-change'
        " line; stale cites re-pinned by content; the E11-D04 anatomy consumed and cited, never"
        " redrawn; the standing rules). Every ORCH default (BQ-1 … BQ-12) is accepted as proposed,"
        " with these precisions: BQ-1 no aggregated rows — the merged `14`:739 / E11-D04 :255 rule"
        " wins over the ticket's AC4 wording, recorded as a C-row with both cites and the existing"
        " owner pointer (O-11 / E11-D01 O6); BQ-2 units in the caption (merged) with the C-row"
        " against AC1; BQ-3 the row header = open time to the millisecond +"
        ' "bar k of n", rows keyed `(generation, index)`, no visible raw index,'
        ' the C-row against "lead with close time" —'
        " the close-time slot stays a column as E11-D04 §6 places it; BQ-4 the seam separator row"
        ' ("Series restarted 09:15 UTC") built on E11-D04\'s band-row form, "bar k of n" never'
        ' spanning a seam; BQ-5 the per-mode "quantity that closed it" cells each marked field /'
        ' derived / "—" with no column the canvas series lacks, the G-row to the `22` / `23` owners'
        " naming an existing ticket (filing freeze); BQ-6 the column set by chart type × bar mode,"
        " listing which D06 §13 cells join each mode; BQ-7 one lowercase `state` vocabulary"
        " (`forming`, `corrected`, `stale`, `width capped`, `no range`, `Est.`, `POC`, `—`; closed"
        " unmarked) — the three disagreeing lists (`14`:734–735, E11-D04 :183, D06 :358) as one"
        " C-row and a copy-ready A-row to `14`'s owner proposing the alignment; BQ-8 `stale` in the"
        ' affected rows\' `state` cell plus the caption clause; BQ-9 "—" with a reason on'
        " kline-backfilled bars, never `0`, the partial-history separator at the first bar with"
        ' delta; BQ-10 "corrected" for live amends only, the loss after a history page stated and'
        " G-row'd to the `22` owner; BQ-11 the A-row to E11-D04's owner adding `bar_type` + `param`"
        " to the open event (market data; no account context, D14 kept); BQ-12 lever 4 — ≤ 10"
        " boards, three light twins at most, mode variants sharing boards, P&F and Heikin-Ashi"
        ' text-only, the row states on one board, every other cell "specified (drawn on request)"'
        " in §0 (E15-D03's wording), the boards a Penpot lane's PR 2."
    ),
    (
        'OWNER → PROPOSED, "owner approval pending (#2701)": BQ-13 — the design-ahead waiver (the'
        " text built ahead of E12-D08 / D10 / D11 merging, with late-change lines), the alternative"
        " recorded beside it; I post the owner pointer on #2701 when PR 1 opens."
    ),
    (
        "Riders: (a) the `(heuristic)` marker on every finding; the walkthrough ≤ 10 items; the dry"
        ' run with the synonym search before any "not found"; (b) the G-ledger\'s owner lanes are'
        " tickets / spec owners, never an agent; (c) nothing of #243 / #245 / #312 / #4853's"
        " unmerged successors pinned or quoted — if any merges before PR 1 opens, cite it at the"
        " base and record the late change in the version line; (d) PR 1 title `docs(chart-engine):"
        " E12-D07 hi-fi of the data-table alternative for every bar mode` (≤ 100), labels"
        " `type/design`, `design`, `area/chart-engine`, `priority/p0`, `a11y`; `large-pr-approved`"
        " asked on the READY line if the spec passes the size line. Write."
    ),
)

STATES = ("forming", "corrected", "stale", "width capped", "no range", "Est.", "POC", "—")
MODES = ("time", "tick", "volume", "range", "delta", "renko")
NOT_IN_TABLE = ("pnf", "heikin_ashi")  # held text (§3.3) and a chart type (§4)
AGENT_RE = re.compile(r"worker|orchestrator|\bagent\b|anvil|claude|codex|lane\b", re.IGNORECASE)
OWNER_OK_RE = re.compile(r"\bE\d\d-[A-Z]+\d\d\b|\bowner")
URL_RE = re.compile(
    r"https?://|www\.|/home/|localhost|\.local\b|\b[a-z0-9-]+\.(?:com|io|org|net)\b"
)
CONTRAST_PAIRS: dict[str, tuple[str, str, str]] = {
    "sep": ("color.text.secondary", "color.surface.hover", "text"),
    "state-odd": ("color.text.primary", "color.surface.canvas", "text"),
    "state-even": ("color.text.primary", "color.surface.raised", "text"),
    "forming-even": ("color.text.secondary", "color.surface.raised", "text"),
    "forming-sel": ("color.text.secondary", "color.surface.selected", "text"),
    "ring-sep": ("color.focus.ring", "color.surface.hover", "non-text"),
}
BARS = {"text": 4.5, "non-text": 3.0}

Finding = tuple[str, str, str, str]  # gate, message, doc, region
Values = dict[str, str]


# ---------------------------------------------------------------------------- git and files


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


@functools.lru_cache(maxsize=64)
def at_base(rel: str) -> str:
    return git("show", f"{FILE_BASE.get(rel, BASE)}:{rel}")


@functools.lru_cache(maxsize=64)
def base_lines(rel: str) -> tuple[str, ...]:
    return tuple(at_base(rel).split("\n"))


def changed_paths() -> tuple[str, ...]:
    # G-UNTOUCHED compares with the merge base on origin/main, not BASE: the cites stay at BASE,
    # but on a rebased head, the merge tree or main after the merge, only this PR's own diff counts.
    fork = git("merge-base", "HEAD", "origin/main").strip()
    tracked = git("diff", "--name-only", fork).split()
    untracked = git("ls-files", "--others", "--exclude-standard").split()
    return tuple(sorted(set(tracked) | set(untracked)))


# ---------------------------------------------------------------------------- markdown model


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    changed: tuple[str, ...]

    def doc(self, name: str) -> str:
        return self.spec if name == "spec" else self.hand


def line_regions(text: str) -> list[str]:
    """The heading path (with an occurrence suffix) of every line; a heading belongs to itself."""
    stack: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    current = "(top)#1"
    out: list[str] = []
    for line in text.split("\n"):
        m = re.match(r"^(#{1,6}) (.*)$", line)
        if m:
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            path = " > ".join(t for _, t in stack)
            seen[path] = seen.get(path, 0) + 1
            current = f"{path}#{seen[path]}"
        out.append(current)
    return out


def section(text: str, prefix: str) -> tuple[int, int, str]:
    """(first body line index, end index, region) of the heading starting with `prefix`."""
    lines = text.split("\n")
    regions = line_regions(text)
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            level = len(line) - len(line.lstrip("#"))
            end = len(lines)
            for j in range(i + 1, len(lines)):
                m = re.match(r"^(#{1,6}) ", lines[j])
                if m and len(m.group(1)) <= level:
                    end = j
                    break
            return i + 1, end, regions[i]
    return 0, 0, f"(missing {prefix})"


def cells(line: str) -> list[str]:
    body = line.strip()
    body = body.removeprefix("|")
    body = body.removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def is_rule_row(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


def tables(text: str, prefix: str) -> list[list[list[str]]]:
    """Every table in the section: a list of rows (header first), each a list of cells."""
    start, end, _ = section(text, prefix)
    lines = text.split("\n")[start:end]
    out: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for line in lines:
        if line.strip().startswith("|"):
            if not is_rule_row(line):
                cur.append(cells(line))
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def first_table(text: str, prefix: str) -> list[list[str]]:
    ts = tables(text, prefix)
    return ts[0] if ts else []


def plain(cell: str) -> str:
    return cell.replace("`", "").strip()


# ---------------------------------------------------------------------------- anchors

ANCHOR_RE = re.compile(r"(?<![0-9A-Za-z.,])([0-9A-Za-z.,]+)<!--=([A-Z]+):([a-z0-9.\-]+)-->")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z]+):([a-z0-9.\-]+)\}\}")


def cut_anchors(text: str) -> str:
    return ANCHOR_RE.sub(lambda m: f"<!--={m.group(2)}:{m.group(3)}-->", text)


# ---------------------------------------------------------------------------- contracts


@functools.lru_cache(maxsize=1)
def bar_props() -> frozenset[str]:
    lines = base_lines(PLAN["22"])
    start = lines.index("    Bar:")
    props: set[str] = set()
    for line in lines[start + 1 :]:
        if re.match(r"^    \S", line):
            break
        m = re.match(r"^        ([a-z_]+):", line)
        if m and m.group(1) not in ("type", "required", "properties"):
            props.add(m.group(1))
    return frozenset(props)


@functools.lru_cache(maxsize=1)
def ws_bar_props() -> frozenset[str]:
    lines = base_lines(PLAN["23"])
    start = next(
        i for i, ln in enumerate(lines) if '"required": ["generation", "index", "t_ms"' in ln
    )
    props: set[str] = set()
    for line in lines[start + 1 :]:
        if '"additionalProperties": false' in line:
            break
        m = re.match(r'^ {10}"([a-z_]+)": ', line)
        if m:
            props.add(m.group(1))
    return frozenset(props)


@functools.lru_cache(maxsize=1)
def bar_types() -> tuple[str, ...]:
    lines = base_lines(PLAN["22"])
    i = lines.index("    BarType:")
    for line in lines[i + 1 : i + 4]:
        m = re.search(r"enum: \[([^\]]+)\]", line)
        if m:
            return tuple(x.strip() for x in m.group(1).split(","))
    raise SystemExit("FAIL BarType enum not found at the base")


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


def hex_of(theme: str, name: str) -> str:
    tokens = load_theme(theme)
    value: object = tokens.get(name, "MISSING")
    hops = 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1], "MISSING"), hops + 1
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise SystemExit(f"FAIL token {name} ({theme}) does not resolve to an opaque colour")
    return value.upper()


def luminance(hex6: str) -> float:
    def lin(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.04045 else float(((x + 0.055) / 1.055) ** 2.4)

    h = hex6.lstrip("#")
    r, g, b = (lin(int(h[i : i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def show_ratio(r: float) -> str:
    """Two decimals, truncated, never rounded up across a bar."""
    return f"{math.floor(r * 100) / 100:.2f}"


# ---------------------------------------------------------------------------- values


def cite_values() -> Values:
    d04 = base_lines(CITE_FILES["D04E11"])
    method, row, panel = d04[195], d04[199], d04[115]
    m_chars = re.search(
        r"time (\d+), four prices (\d+), volume (\d+), delta (\d+), state (\d+)", method
    )
    m_adv = re.search(r"(0\.\d+) em advance", method)
    m_panel = re.search(r"\*\*(\d+) CSS px of panel width\*\*", panel)
    c = cells(row)
    m_base = re.match(r"(\d+) px", c[4]) if len(c) > 4 else None
    if not (m_chars and m_adv and m_panel and m_base and c[:2] == ["compact", "100 %"]):
        raise SystemExit("FAIL the E11-D04 width lines moved at the base")
    t, p, v, dl, s = (int(x) for x in m_chars.groups())
    return {
        "CITE:w.base": m_base.group(1),
        "CITE:w.font": c[2],
        "CITE:w.pad": c[3],
        "CITE:w.adv": m_adv.group(1),
        "CITE:w.chars": str(t + 4 * p + v + dl + s),
        "CITE:w.cols": "8",
        "CITE:w.panel": m_panel.group(1),
    }


def column_rows(spec: str) -> list[list[str]]:
    t = first_table(spec, "### 3.1")
    return t[1:] if t else []


def mode_chars(row: list[str], mode: str) -> int:
    parts = [int(x) for x in re.findall(r"\d+", row[1])]
    if not parts:
        return 0
    return parts[0] if mode == "time" or len(parts) == 1 else parts[1]


def width_values(spec: str, cv: Values) -> Values:
    base, font = float(cv["CITE:w.base"]), float(cv["CITE:w.font"])
    adv = round(font * float(cv["CITE:w.adv"]), 4)
    col = 2 * int(cv["CITE:w.pad"])
    c0, k0, panel = int(cv["CITE:w.chars"]), int(cv["CITE:w.cols"]), float(cv["CITE:w.panel"])
    out: Values = {"WIDTH:adv": f"{adv:g}", "WIDTH:col": str(col)}
    rows = column_rows(spec)

    def width(chars: int, cols: int) -> float:
        return round(base + adv * (chars - c0) + col * (cols - k0), 1)

    for i, mode in enumerate(MODES):
        prim = [r for r in rows if len(r) > 2 + i and r[2 + i].startswith("P ")]
        auto = [r for r in rows if len(r) > 2 + i and r[2 + i].startswith("A ")]
        ch = sum(mode_chars(r, mode) for r in prim)
        px = width(ch, len(prim))
        px_auto = width(ch + sum(mode_chars(r, mode) for r in auto), len(prim) + len(auto))
        out[f"WIDTH:{mode}.chars"] = str(ch)
        out[f"WIDTH:{mode}.cols"] = str(len(prim))
        out[f"WIDTH:{mode}.px"] = f"{px:.1f}"
        out[f"WIDTH:{mode}.fit"] = "fits" if px <= panel else "stacked"
        out[f"WIDTH:{mode}.auto"] = f"{px_auto:.1f}"
        if mode == "time":
            state = next((r for r in prim if plain(r[0]) == "state"), None)
            extra = 12 - mode_chars(state, mode) if state else 0
            out["WIDTH:equi.px"] = f"{width(ch + extra, len(prim)):.1f}"
    return out


def contrast_values() -> Values:
    out: Values = {}
    lowest = 99.0
    for key, (fg, bg, role) in CONTRAST_PAIRS.items():
        for theme in THEMES:
            r = contrast(hex_of(theme, fg), hex_of(theme, bg))
            out[f"CONTRAST:{key}.{theme}"] = show_ratio(r)
            if role == "text":
                lowest = min(lowest, r)
    out["CONTRAST:min.text"] = show_ratio(lowest)
    return out


def needs_rows(hand: str) -> list[list[str]]:
    t = first_table(hand, "## §G")
    return t[1:] if t else []


def count_values(t: Texts) -> Values:
    spec, hand = t.spec, t.hand
    boards = first_table(spec, "## 0.")[1:]
    out: Values = {
        "COUNT:boards": str(len(boards)),
        "COUNT:boards.light": str(sum(1 for r in boards if len(r) > 3 and r[3] == "light")),
        "COUNT:boards.dark": str(sum(1 for r in boards if len(r) > 3 and r[3] == "dark")),
        "COUNT:columns": str(len(column_rows(spec))),
        "COUNT:states": str(len(first_table(spec, "## 6.")[1:])),
        "COUNT:separators": str(len(first_table(spec, "### 7.1")[1:])),
        "COUNT:parity": str(len(first_table(spec, "### 9.2")[1:])),
        "COUNT:copy": str(len(first_table(spec, "## 13.")[1:])),
        "COUNT:findings": str(len(first_table(spec, "## 15.")[1:])),
    }
    s, e, _ = section(hand, "## §E")
    walk = [ln for ln in hand.split("\n")[s:e] if ln.startswith("- [")]
    out["COUNT:walkthrough"] = str(len(walk))
    for i, row in enumerate(needs_rows(hand), 1):
        cell = row[1] if len(row) > 1 else ""
        n, nf = cell.count("→"), cell.count("(not found)")
        out[f"COUNT:dry.{i}.needs"] = str(n)
        out[f"COUNT:dry.{i}.found"] = str(n - nf)
        out[f"COUNT:dry.{i}.notfound"] = str(nf)
    return out


def compute_values(t: Texts) -> Values:
    cv = cite_values()
    return {**cv, **width_values(t.spec, cv), **contrast_values(), **count_values(t)}


# ---------------------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    mid: str
    what: str
    gate: str
    doc: str  # "spec", "hand" or "changed"
    where: str  # a heading prefix; "" = the whole document
    old: str
    new: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1", "mark board 01 drawn in §0", "G-BOARDS", "spec", "## 0.", "PENDING (PR 2)", "drawn"
    ),
    Mutation(
        "M-2",
        "draw the Heikin-Ashi cells on board 06",
        "G-BOARDS",
        "spec",
        "## 0.",
        "baseline `vs base`, delta-volume",
        "Heikin-Ashi `HA close`, baseline `vs base`, delta-volume",
    ),
    Mutation(
        "M-3",
        "rename the REST field `trades` in §3.1",
        "G-COLUMNS",
        "spec",
        "### 3.1",
        "`trades`",
        "`trade_count`",
    ),
    Mutation(
        "M-4",
        "mark range's derived cell a field",
        "G-COLUMNS",
        "spec",
        "### 3.1",
        "P derived",
        "P field",
    ),
    Mutation(
        "M-5", "capitalise `forming` in §6", "G-STATE", "spec", "## 6.", "`forming`", "`Forming`"
    ),
    Mutation(
        "M-6",
        "point a §6.2 cite past the end of `23`",
        "G-CITE",
        "spec",
        "### 6.2",
        "`23`:2915",
        "`23`:99915",
    ),
    Mutation(
        "M-7",
        "re-word W-1",
        "G-QUOTE",
        "spec",
        "## 13.",
        '"Series restarted 09:15 UTC"',
        '"Series restarted at 09:15 UTC"',
    ),
    Mutation(
        "M-8",
        "drop 'no' from the ruled BQ-1 sentence",
        "G-RULED",
        "spec",
        "## The questions",
        "BQ-1 no aggregated rows",
        "BQ-1 aggregated rows",
    ),
    Mutation(
        "M-9",
        "cut the date and time from BQ-13's RULED stamp",
        "G-PENDING",
        "spec",
        "## The questions",
        "RULED (orchestrator, 2026-10-29 13:58Z,",
        "RULED (orchestrator,",
    ),
    Mutation(
        "M-10",
        "drop `(heuristic)` from H-3",
        "G-HEUR",
        "spec",
        "## 15.",
        "(heuristic) Consistency",
        "Consistency",
    ),
    Mutation(
        "M-11",
        "add two walkthrough items in the hand-off's §E",
        "G-WALK",
        "hand",
        "## §E",
        "- [ ] Boards 09–10:",
        "- [ ] Extra one.\n- [ ] Extra two.\n- [ ] Boards 09–10:",
    ),
    Mutation(
        "M-12",
        "name an agent as D07-G2's owner",
        "G-OWNER",
        "spec",
        "### 17.2",
        "E12-T05 (#398); the `22` owner",
        "a worker agent",
    ),
    Mutation(
        "M-13",
        "link E12-D10's unmerged file in the start line",
        "G-UNMERGED",
        "spec",
        "",
        "E12-D10 (#245)",
        "docs/design/E12/E12-D10.md (#245)",
    ),
    Mutation(
        "M-14",
        "write a page URL beside the Penpot page in §0",
        "G-URL",
        "spec",
        "## 0.",
        "cited by name and page id only",
        "cited by name and page id only (https://penpot.example.org/p)",
    ),
    Mutation(
        "M-15",
        "change the boards count in the header",
        "G-ANCHOR",
        "spec",
        "",
        "10<!--=COUNT:boards-->",
        "11<!--=COUNT:boards-->",
    ),
    Mutation(
        "M-16", "pad the spec past its line budget", "G-BUDGET", "spec", "<eof>", "", "\n" * 300
    ),
    Mutation(
        "M-17", "touch `22` in the working tree", "G-UNTOUCHED", "changed", "", "", PLAN["22"]
    ),
    Mutation(
        "M-18",
        "leave a placeholder unfilled",
        "G-MARKER",
        "spec",
        "",
        "10<!--=COUNT:boards-->",
        "{{COUNT:boards}}",
    ),
    Mutation(
        "M-19",
        "re-word D07-A4's Old fragment",
        "G-AROW",
        "hand",
        "## §C",
        "`Bar.close_t`",
        "`Bar.closeTime`",
    ),
    Mutation(
        "M-20",
        "bind the separator text to `color.text.tertiary`",
        "G-CONTRAST",
        "spec",
        "## 14.",
        "`color.text.secondary`",
        "`color.text.tertiary`",
    ),
    Mutation(
        "M-21",
        "rename the first dry-run role in the hand-off",
        "G-DRYRUN",
        "hand",
        "## §G",
        "story: E11-S14 (#521)",
        "story: E11-S13 (#520)",
    ),
    Mutation(
        "M-22",
        "replace a ruled-mutation row's gate in §16",
        "G-MUTLIST",
        "spec",
        "## 16.",
        "| G-WALK",
        "| G-WALKS",
    ),
)
PROBES: tuple[Mutation, ...] = (
    Mutation(
        "P-1",
        "flip a prose sentence in §2.2",
        "G-RULED-PIN",
        "spec",
        "### 2.2",
        "It is never a raw `index`",
        "It is at times a raw `index`",
    ),
    Mutation(
        "P-2",
        "re-word a hand-off summary item",
        "G-RULED-PIN",
        "hand",
        "## §I",
        "band-row form",
        "banner form",
    ),
)


def mutation_rows() -> str:
    return "\n".join(f"| {m.mid} | {m.what} | {m.gate} |" for m in MUTATIONS)


def apply_mutation(t: Texts, m: Mutation) -> Texts:
    if m.doc == "changed":
        return replace(t, changed=(*t.changed, m.new))
    text = t.doc(m.doc)
    if m.where == "<eof>":
        new_text = text + m.new
    else:
        if m.where:
            s, e, _ = section(text, m.where)
            lines = text.split("\n")
            offset = len("\n".join(lines[:s])) + (1 if s else 0)
            span = "\n".join(lines[s:e])
        else:
            offset, span = 0, text
        k = span.find(m.old)
        if k < 0:
            raise SystemExit(f"FAIL {m.mid}: its target text is not in {m.doc} {m.where!r}")
        k += offset
        new_text = text[:k] + m.new + text[k + len(m.old) :]
    return replace(t, spec=new_text) if m.doc == "spec" else replace(t, hand=new_text)


# ---------------------------------------------------------------------------- gates


def g_anchor(t: Texts, values: Values) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            for m in ANCHOR_RE.finditer(line):
                key = f"{m.group(2)}:{m.group(3)}"
                want = values.get(key)
                if want is None:
                    out.append(("G-ANCHOR", f"unknown anchor {key}", doc, regions[i]))
                elif m.group(1) != want:
                    out.append(
                        ("G-ANCHOR", f"{key} reads {m.group(1)}, derives {want}", doc, regions[i])
                    )
    return out


def g_marker(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            if "{{" in line:
                out.append(("G-MARKER", f"unfilled placeholder on line {i + 1}", doc, regions[i]))
            stray = re.sub(r"<!--=[A-Z]+:[a-z0-9.\-]+-->", "", line)
            if "<!--" in stray:
                out.append(("G-MARKER", f"a stray HTML comment on line {i + 1}", doc, regions[i]))
    return out


CITE_RE = re.compile(
    r"(?:`(\d\d)`|\b(D04E11|D07E11|D02|D03|D05|D06|D08|D09|E12J|E11J))"
    r"(:\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
)


def cite_targets(line: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for m in CITE_RE.finditer(line):
        rel = PLAN.get(m.group(1) or "") or CITE_FILES.get(m.group(2) or "")
        if rel is None:
            out.append((f"?{m.group(1)}", 0))
            continue
        for a, b in re.findall(r":(\d+)(?:–(\d+))?", m.group(3)):
            out.append((rel, int(a)))
            if b:
                out.append((rel, int(b)))
    return out


def g_cite(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            for rel, n in cite_targets(line):
                if rel.startswith("?"):
                    out.append(("G-CITE", f"unknown cite key {rel[1:]}", doc, regions[i]))
                    continue
                lines = base_lines(rel)
                if not (1 <= n <= len(lines)) or not lines[n - 1].strip():
                    out.append(("G-CITE", f"{rel}:{n} is not a non-blank line", doc, regions[i]))
    return out


def cited_text(cite_cell: str) -> str:
    return "\n".join(
        base_lines(rel)[n - 1]
        for rel, n in cite_targets(cite_cell)
        if not rel.startswith("?") and 1 <= n <= len(base_lines(rel))
    )


def g_quote(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.spec, "## 13.")
    for row in first_table(t.spec, "## 13.")[1:]:
        if len(row) < 4 or not row[3].startswith("verbatim"):
            continue
        s = row[1].strip().strip('"')
        if s not in cited_text(row[2]):
            out.append(("G-QUOTE", f"{row[0]} is not verbatim on {row[2]}", "spec", region))
    return out


def g_arow(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.hand, "## §C")
    for row in first_table(t.hand, "## §C")[1:]:
        if len(row) < 5:
            continue
        if row[3].replace("\\|", "|") not in cited_text(row[2]):
            out.append(("G-AROW", f"{row[0]}'s Old is not verbatim on its line", "hand", region))
    return out


def g_ruled(t: Texts) -> list[Finding]:
    s, e, region = section(t.spec, "## The questions")
    body = t.spec.split("\n")[s:e]
    out: list[Finding] = []
    head = "\n".join(t.spec.split("\n")[s - 1 : s])
    if RULING_ID not in head or BQ_LIST_ID not in head:
        out.append(("G-RULED", "the heading does not name the ruling and the list", "spec", region))
    for k, para in enumerate(RULED, 1):
        if para not in body:
            out.append(("G-RULED", f"ruled paragraph {k} is not verbatim", "spec", region))
    return out


def g_pending(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    s, e, region = section(t.spec, "## The questions")
    built = [ln for ln in t.spec.split("\n")[s:e] if ln.startswith("**Where each is built.**")]
    if not built or not re.search(r"\*\*BQ-13\*\*[^*]*" + re.escape(BQ13_RULED), built[0]):
        out.append(("G-PENDING", "BQ-13 is not marked " + BQ13_RULED, "spec", region))
    s, e, region = section(t.spec, "### 17.3")
    q1 = [ln for ln in t.spec.split("\n")[s:e] if "D07-Q1" in ln]
    if not q1 or BQ13_RULED not in q1[0]:
        out.append(("G-PENDING", "D07-Q1 is not marked " + BQ13_RULED, "spec", region))
    return out


def g_boards(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 0.")
    rows = first_table(t.spec, "## 0.")[1:]
    bad: list[str] = []
    if not 1 <= len(rows) <= 10:
        bad.append(f"{len(rows)} boards")
    light = [r for r in rows if len(r) > 3 and r[3] == "light"]
    if len(light) > 3:
        bad.append(f"{len(light)} light twins")
    for r in rows:
        if len(r) < 5 or r[3] not in ("dark", "light", "hc"):
            bad.append(f"board {r[0]} has no theme")
        elif not r[4].startswith("PENDING"):
            bad.append(f"board {r[0]} is not PENDING")
        if len(r) > 2 and re.search(r"P&F|Heikin|\bHA\b", r[2]):
            bad.append(f"board {r[0]} draws a text-only type")
    s, e, _ = section(t.spec, "## 0.")
    body = "\n".join(t.spec.split("\n")[s:e])
    if "**Specified (drawn on request)**" not in body:
        bad.append("no 'specified (drawn on request)' paragraph")
    return [("G-BOARDS", b, "spec", region) for b in bad]


def g_columns(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 3.1")
    table = first_table(t.spec, "### 3.1")
    bad: list[str] = []
    if not table:
        return [("G-COLUMNS", "no column table", "spec", region)]
    want = tuple(b for b in bar_types() if b not in NOT_IN_TABLE)
    if tuple(plain(c) for c in table[0][2:8]) != want or want != MODES:
        bad.append(f"mode columns {table[0][2:8]} != {want}")
    rest, ws = bar_props(), ws_bar_props()
    for r in table[1:]:
        if len(r) != 11:
            bad.append(f"row {r[0]} has {len(r)} cells")
            continue
        kinds: set[str] = set()
        for c in r[2:8]:
            if c == "—":
                continue
            m = re.fullmatch(r"(P|A|E) (field|derived)", c)
            if not m:
                bad.append(f"row {r[0]}: cell {c!r}")
                continue
            kinds.add(m.group(2))
        names_rest = re.findall(r"`([a-z_]+)`", r[8])
        names_ws = re.findall(r"`([a-z_]+)`", r[9])
        for n in names_rest:
            if n not in rest:
                bad.append(f"row {r[0]}: `{n}` not in 22 Bar")
        for n in names_ws:
            if n not in ws:
                bad.append(f"row {r[0]}: `{n}` not in the 23 bars item")
        if not names_rest and not names_ws:
            bad.append(f"row {r[0]} names no field")
        if len(kinds) > 1:
            bad.append(f"row {r[0]} mixes field and derived")
        if "field" in kinds and (len(names_rest) != 1 or len(names_ws) != 1):
            bad.append(f"row {r[0]}: a field cell must name exactly one field per surface")
    held = "\n".join(t.spec.split("\n")[slice(*section(t.spec, "### 3.3")[:2])])
    if "`pnf`" not in held:
        bad.append("§3.3 does not hold `pnf`")
    if not any(plain(r[0]) == "Heikin-Ashi" for r in first_table(t.spec, "## 4.")[1:]):
        bad.append("§4 has no Heikin-Ashi row")
    return [("G-COLUMNS", b, "spec", region) for b in bad]


def g_state(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.spec, "## 6.")
    words = tuple(plain(r[0]) for r in first_table(t.spec, "## 6.")[1:])
    if words != STATES:
        out.append(("G-STATE", f"the state words read {words}", "spec", region))
    regions = line_regions(t.spec)
    for i, line in enumerate(t.spec.split("\n")):
        if "17.1" in regions[i] or "The questions" in regions[i]:
            continue
        if re.search(r'"Forming"|"Closed"|Closed, corrected|`Forming`', line):
            out.append(("G-STATE", f"a capitalised state word on line {i + 1}", "spec", regions[i]))
    return out


def g_contrast(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.spec, "## 14.")
    rows = first_table(t.spec, "## 14.")[1:]
    seen: set[str] = set()
    for r in rows:
        keys = {
            m.group(1)
            for m in re.finditer(r"<!--=CONTRAST:([a-z\-]+)\.(?:dark|light|hc)-->", " ".join(r))
        }
        if len(keys) != 1:
            out.append(("G-CONTRAST", f"row {r[0]} carries {len(keys)} pair keys", "spec", region))
            continue
        key = keys.pop()
        seen.add(key)
        fg, bg, role = CONTRAST_PAIRS.get(key, ("?", "?", "?"))
        if (plain(r[1]), plain(r[2]), r[3]) != (fg, bg, role):
            out.append(
                ("G-CONTRAST", f"row {r[0]} binds other tokens than pair {key}", "spec", region)
            )
    if seen != set(CONTRAST_PAIRS):
        out.append(("G-CONTRAST", "the table and the pair list differ", "spec", region))
    for key, (fg, bg, role) in CONTRAST_PAIRS.items():
        for theme in THEMES:
            if contrast(hex_of(theme, fg), hex_of(theme, bg)) < BARS[role]:
                out.append(("G-CONTRAST", f"{key} {theme} is below its bar", "spec", region))
    return out


def g_heur(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 15.")
    return [
        ("G-HEUR", f"{r[0]} lacks (heuristic)", "spec", region)
        for r in first_table(t.spec, "## 15.")[1:]
        if len(r) < 2 or not r[1].startswith("(heuristic) ")
    ]


def g_walk(t: Texts) -> list[Finding]:
    s, e, region = section(t.hand, "## §E")
    n = sum(1 for ln in t.hand.split("\n")[s:e] if ln.startswith("- ["))
    return [] if 1 <= n <= 10 else [("G-WALK", f"{n} walkthrough items", "hand", region)]


def g_owner(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 17.2")
    out: list[Finding] = []
    for r in first_table(t.spec, "### 17.2")[1:]:
        owner = r[3] if len(r) > 3 else ""
        if AGENT_RE.search(owner) or not OWNER_OK_RE.search(owner):
            out.append(("G-OWNER", f"{r[0]}'s owner {owner!r}", "spec", region))
    return out


def g_dryrun(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 18.")
    spec_roles = [r[1] for r in first_table(t.spec, "## 18.")[1:] if len(r) > 1]
    hand_roles = [r[0] for r in needs_rows(t.hand)]
    if spec_roles != hand_roles or not spec_roles:
        msg = "the roles of spec §18 and hand-off §G differ"
        return [
            ("G-DRYRUN", msg, "spec", region),
            ("G-DRYRUN", msg, "hand", section(t.hand, "## §G")[2]),
        ]
    return []


def g_lines(t: Texts, gate: str, test: Callable[[str], bool], what: str) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            if test(line):
                out.append((gate, f"{what} on line {i + 1}", doc, regions[i]))
    return out


def g_untouched(t: Texts) -> list[Finding]:
    extra = [p for p in t.changed if p not in OWN]
    return [("G-UNTOUCHED", f"{p} differs from the base", "", "") for p in extra]


def g_budget(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc, cap in (("spec", SPEC_BUDGET), ("hand", HAND_BUDGET)):
        if t.doc(doc).count("\n") > cap:
            out.append(("G-BUDGET", f"{doc} has more than {cap} lines", "", ""))
    return out


def g_mutlist(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 16.")
    rows = [(r[0], r[2]) for r in first_table(t.spec, "## 16.")[1:] if len(r) > 2]
    want = [(m.mid, m.gate) for m in MUTATIONS]
    return (
        [] if rows == want else [("G-MUTLIST", "§16 differs from the tool's list", "spec", region)]
    )


# ---------------------------------------------------------------------------- pins


def units(doc: str, text: str) -> list[tuple[str, str, str, str]]:
    """(doc, region, location, normalised text) for every unit; one shape unit per region."""
    out: list[tuple[str, str, str, str]] = []
    regions = line_regions(text)
    shape: dict[str, str] = {}
    prose: dict[str, int] = {}
    leads: dict[tuple[str, str], int] = {}
    order: list[str] = []
    for i, line in enumerate(text.split("\n")):
        reg = regions[i]
        if reg not in shape:
            shape[reg] = ""
            order.append(reg)
        body = re.sub(r"\s+", " ", cut_anchors(line)).strip()
        if not body:
            continue
        if re.match(r"^#{1,6} ", line):
            shape[reg] += "h"
            out.append((doc, reg, "heading", body))
        elif line.strip().startswith("|"):
            if is_rule_row(line):
                shape[reg] += "r"
                continue
            shape[reg] += "t"
            c = cells(cut_anchors(line))
            lead = re.sub(r"\s+", " ", c[0]) if c else ""
            leads[(reg, lead)] = leads.get((reg, lead), 0) + 1
            loc = f"row {lead}" + (f" #{leads[(reg, lead)]}" if leads[(reg, lead)] > 1 else "")
            out.append((doc, reg, loc, " | ".join(re.sub(r"\s+", " ", x) for x in c)))
        else:
            shape[reg] += "p"
            prose[reg] = prose.get(reg, 0) + 1
            out.append((doc, reg, f"l{prose[reg]}", body))
    for reg in order:
        out.append((doc, reg, "shape", shape[reg] or "(empty)"))
    return out


def all_units(t: Texts) -> list[tuple[str, str, str, str]]:
    return units("spec", t.spec) + units("hand", t.hand)


def read_pins() -> dict[tuple[str, str, str], str]:
    path = ROOT / PIN_REL
    if not path.exists():
        return {}
    pins: dict[tuple[str, str, str], str] = {}
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line or line.startswith("#"):
            continue
        doc, reg, loc, text = line.split("\t", 3)
        pins[(doc, reg, loc)] = text
    return pins


def g_pins(t: Texts) -> list[Finding]:
    pins = read_pins()
    if not pins:
        return [("G-RULED-PIN", "no pins file; run --repin-ruled", "", "")]
    have = {(d, r, loc): x for d, r, loc, x in all_units(t)}
    out: list[Finding] = []
    for key in sorted(set(pins) | set(have)):
        if key not in have:
            out.append(("G-RULED-PIN", f"unit removed: {key[2]}", key[0], key[1]))
        elif key not in pins:
            out.append(("G-RULED-PIN", f"unit added: {key[2]}", key[0], key[1]))
        elif pins[key] != have[key]:
            out.append(("G-RULED-PIN", f"unit changed: {key[2]}", key[0], key[1]))
    return out


def repin(t: Texts) -> int:
    if PLACEHOLDER_RE.search(t.spec + t.hand) or "{{RULING}}" in t.spec:
        print("FAIL --repin-ruled refuses while a placeholder is unfilled")
        return 1
    rows = all_units(t)
    head = (
        "# E12-D07 pins (every unit of the spec and the hand-off): doc, region (heading path"
        f" #occurrence), location, exact normalised text; {len(rows)} units.\n"
        "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit; G-RULED-PIN).\n"
    )
    body = "".join(f"{d}\t{r}\t{loc}\t{x}\n" for d, r, loc, x in rows)
    old = read_pins()
    new = {(d, r, loc): x for d, r, loc, x in rows}
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            print(f"REPIN {key[0]} {key[2]} in {key[1][:60]}".encode("ascii", "replace").decode())
    (ROOT / PIN_REL).write_text(head + body, encoding="utf-8")
    print(f"wrote {PIN_REL}: {len(rows)} units")
    return 0


# ---------------------------------------------------------------------------- run


def findings(t: Texts, values: Values) -> list[Finding]:
    out: list[Finding] = []
    out += g_anchor(t, values) + g_marker(t) + g_cite(t) + g_quote(t) + g_arow(t)
    out += g_ruled(t) + g_pending(t) + g_boards(t) + g_columns(t) + g_state(t)
    out += g_contrast(t) + g_heur(t) + g_walk(t) + g_owner(t) + g_dryrun(t)
    out += g_lines(t, "G-UNMERGED", lambda ln: any(p in ln for p in UNMERGED_PATHS), "a path")
    out += g_lines(t, "G-URL", lambda ln: bool(URL_RE.search(ln)), "a URL, host or local path")
    out += g_untouched(t) + g_budget(t) + g_mutlist(t) + g_pins(t)
    return out


def related(a: str, b: str) -> bool:
    if not a or not b:
        return False
    a0, b0 = a.rsplit("#", 1)[0], b.rsplit("#", 1)[0]
    return a0 == b0 or a0.startswith(b0 + " > ") or b0.startswith(a0 + " > ")


def report(fs: list[Finding], quiet: bool = False) -> list[str]:
    """One FAIL line per gate; pin findings in a region another gate FAILs become NOTE."""
    other = [(d, r) for g, _, d, r in fs if g != "G-RULED-PIN"]
    lines: list[str] = []
    gates: dict[str, list[Finding]] = {}
    for f in fs:
        if f[0] == "G-RULED-PIN" and any(d == f[2] and related(r, f[3]) for d, r in other):
            if not quiet:
                lines.append(f"NOTE G-RULED-PIN {f[1]} ({f[2]}; another gate FAILs here)")
            continue
        gates.setdefault(f[0], []).append(f)
    for gate, items in gates.items():
        lines.append(
            f"FAIL {gate}: {len(items)} finding(s); first: {items[0][1]} [{items[0][3][:70]}]"
        )
    return [ln.encode("ascii", "replace").decode() for ln in lines]


def read_texts() -> Texts:
    return Texts(
        spec=(ROOT / SPEC_REL).read_text(encoding="utf-8"),
        hand=(ROOT / HAND_REL).read_text(encoding="utf-8"),
        changed=changed_paths(),
    )


def fill(t: Texts) -> Texts:
    spec = t.spec.replace("{{RULING}}", "\n\n".join(RULED)).replace(
        "{{MUTATIONS}}", mutation_rows()
    )
    t = replace(t, spec=spec)
    values = compute_values(t)

    def placeholder(m: re.Match[str]) -> str:
        key = f"{m.group(1)}:{m.group(2)}"
        return f"{values[key]}<!--={key}-->"

    def anchor(m: re.Match[str]) -> str:
        key = f"{m.group(2)}:{m.group(3)}"
        return f"{values.get(key, m.group(1))}<!--={key}-->"

    def sub(text: str) -> str:
        return ANCHOR_RE.sub(anchor, PLACEHOLDER_RE.sub(placeholder, text))

    t = replace(t, spec=sub(t.spec), hand=sub(t.hand))
    (ROOT / SPEC_REL).write_text(t.spec, encoding="utf-8")
    (ROOT / HAND_REL).write_text(t.hand, encoding="utf-8")
    return t


def check(do_fill: bool) -> int:
    t = read_texts()
    if do_fill:
        t = fill(t)
    lines = report(findings(t, compute_values(t)))
    for ln in lines:
        print(ln)
    fails = sum(1 for ln in lines if ln.startswith("FAIL"))
    print(f"{fails} FAIL")
    return 1 if fails else 0


def self_test() -> int:
    t = read_texts()
    digest = hashlib.sha256((t.spec + t.hand).encode()).hexdigest()
    values = compute_values(t)
    base = [ln for ln in report(findings(t, values), quiet=True) if ln.startswith("FAIL")]
    if base:
        print("FAIL self-test: the baseline is not clean:", *base, sep="\n  ")
        return 1
    bad = 0
    for m in (*MUTATIONS, *PROBES):
        mt = apply_mutation(t, m)
        got = [ln for ln in report(findings(mt, values), quiet=True) if ln.startswith("FAIL")]
        ok = len(got) == 1 and got[0].startswith(f"FAIL {m.gate}:")
        print(
            f"{'ok  ' if ok else 'BAD '} {m.mid} {m.gate} <- {m.what}".encode(
                "ascii", "replace"
            ).decode()
        )
        if not ok:
            bad += 1
            for g in got:
                print(f"       {g}")
    after = read_texts()
    if hashlib.sha256((after.spec + after.hand).encode()).hexdigest() != digest:
        print("FAIL self-test: the texts on disk changed")
        return 1
    print(f"self-test: {len(MUTATIONS) + len(PROBES) - bad} of {len(MUTATIONS) + len(PROBES)} ok")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--fill", action="store_true", help="with --check: write values first")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.repin_ruled:
        return repin(read_texts())
    return check(args.fill)


if __name__ == "__main__":
    sys.exit(main())
