#!/usr/bin/env python3
"""E47-D08 (#1307) audit: reduced-motion variants and flash-rate safety (text first).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the plan texts and the design texts the spec cites (E47-D03
at its merge commit, E47-D05 and E47-D04 at their PR heads), the motion exception register, the
flash calibration note, the coalescer's defaults and the synthetic tick fixture's presets; and,
from the working tree, the spec `docs/design/E47/E47-D08.md`, its hand-off and the pins file. Its
form follows the E47-D04 tool (the same modes, anchored values, default-deny pins and mutations).

1. **Values.** Every `{{KIND:key}}` placeholder is written by `--fill` as `VALUE<!--=KIND:key-->`:
   COUNT (rows of the spec's and the hand-off's own tables) and SIM (the 40 Hz `burst` preset run
   through the spec's §4 rules: per source, all sources without the arbiter, and with it).
   `--check` re-derives each anchored value (G-ANCHOR) and FAILs a placeholder left behind or a
   stray HTML comment (G-MARKER). `--fill` also writes the mutation rows ({{MUTATIONS}}).
2. **Cites.** Every `NN`:line and KEY:line cite of both documents resolves to a non-blank line at
   its pin (G-CITE); every "verbatim" copy string occurs on its cited line (G-QUOTE); every Old
   fragment of the hand-off's A-rows occurs verbatim on its cited line (G-AROW).
3. **Gates.** One FAIL line per gate: G-BOTH (the spec opens with the both-modes sentence; R-1
   states it; every §5 carrier has a hold), G-PENDING (BQ-0 ... BQ-17 once each, each "RULED" with
   the ruling's comment 6570059961 and none "ruling pending"; the heading names the ruling), G-PIN (the header names only the four
   pinned commits, each present in the object store), G-BOARDS (at most ten boards, twins at most a
   third, every board pending, the not-drawn paragraph), G-INV (every inventory row: both variants
   in every tier, "unchanged" only on a static row, a canvas row's calm cell equals its reduced
   cell, a DOM row's calm cell is "as full", the owner a cite or a G-row of §18.2, every backticked
   token of the full cell on the owner's line, AC3's surfaces present), G-BUDGET (the simulation
   from the spec's constants: each source at most 2, the bubble 0, the combined region within FR-3
   and below the FR-7 gate, FR-1 equal to the coalescer's default), G-REG (every MX id exists in the
   register; no register row copied), G-PAUSE (every §8 row: a pause, an announced state, "the feed
   keeps running"; follow-live never says "Paused"), G-SAFETY (every §11 row: a static carrier and
   "never" flashes), G-T2 (§12 states the T2 paragraph once with its clauses; §8, §9 and §11 cite
   §12; the hand-off's component line names CMP-079 and CMP-019), G-HEUR, G-WALK (at most ten
   items), G-OWNER (owners are tickets or the owner, never an agent), G-PUBLIC (no URL, host, local
   path), G-KEYWORD (no closing keyword followed by an issue number in either text,
   the pins or this file), G-UNTOUCHED (only this ticket's files and boards differ from the merge
   base with origin/main), G-LINES (600 spec lines, 150 hand-off lines), G-MUTLIST (§17's rows
   equal the tool's list).
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of both documents
   (each heading, table row by its lead cell and prose line, by heading path and occurrence, with a
   line-shape tag per region) in `e47_d08_ruled_pins.txt`. Anchored values are cut out of the pinned
   text (G-ANCHOR owns them). `--repin-ruled` is the only writer and refuses while a placeholder is
   unfilled. A pin finding in a region another gate already FAILs prints as NOTE.
5. **--self-test** applies every mutation (M-n) and pin probe (P-n) in memory with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names; the texts
   on disk are checked byte-identical afterwards (sha256). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e47_d08_motion_audit.py --check [--fill]
  python3 -I docs/design/_tools/e47_d08_motion_audit.py --self-test
  python3 -I docs/design/_tools/e47_d08_motion_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import math
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "85b6b6c1c"  # origin/main when the spec was written; every cite is read here
D03_MERGE = "73fefc62b"  # E47-D03 (#1302), PR #5392 merged
D05_HEAD = "3987edc89"  # E47-D05 (#1304), PR #5417 head; re-pins at its merge
D04_HEAD = "1ff5d8cb9"  # E47-D04 (#1303), PR #5387 head; re-pins at its merge
PINNED = (BASE, D03_MERGE, D05_HEAD, D04_HEAD)

SPEC_REL = "docs/design/E47/E47-D08.md"
HAND_REL = "docs/design/E47/E47-D08-handoff.md"
TOOL_REL = "docs/design/_tools/e47_d08_motion_audit.py"
PIN_REL = "docs/design/_tools/e47_d08_ruled_pins.txt"
OWN = (SPEC_REL, HAND_REL, TOOL_REL, PIN_REL)
OWN_BOARDS = re.compile(
    r"docs/design/E47/img/E47-D08-\d\d-[a-z0-9-]+\.png|\.prettierignore"
    r"|docs/design/_tools/sheets/(?:e47-d08/[A-Za-z0-9._/-]+|MANIFEST\.sha256)"
)
PENDING_CELL = "pending: drawn later in this PR"
SPEC_LINES = 600
HAND_LINES = 150

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
}
CITE_FILES = {
    "E05D03": "docs/design/E05/E05-D03.md",
    "E11D06": "docs/design/E11/E11-D06.md",
    "E26D02": "docs/design/E26/E26-D02.md",
    "E22D04": "docs/design/E22/E22-D04.md",
    "E08D11": "docs/design/E08/E08-D11.md",
    "E40D02": "docs/design/E40/E40-D02.md",
    "E15D14": "docs/design/E15/E15-D14.md",
    "D09E09": "docs/design/E09/E09-D09.md",
    "E11R": "docs/design/research/e11-chart-navigation-research.md",
    "E17D02": "docs/design/E17/E17-D02.md",
    "CAT": "docs/plan/a11y/47-audit-catalogue.md",
    "D03": "docs/design/E47/E47-D03.md",
    "D04": "docs/design/E47/E47-D04.md",
    "D05": "docs/design/E47/E47-D05.md",
    "REG": "docs/qa/a11y/e47-motion-exception-register.md",
    "CAL": "docs/qa/a11y/e47-flash-calibration.md",
    "MODEL": "apps/web/src/features/a11y-preferences/model.ts",
    "COAL": "packages/ui/src/components/flashCoalescer.ts",
    "TICKS": "packages/fixtures/src/synthetic-ticks.mjs",
}
FILE_BASE = {
    CITE_FILES["D03"]: D03_MERGE,
    CITE_FILES["D05"]: D05_HEAD,
    CITE_FILES["D04"]: D04_HEAD,
}

BQ_LIST_ID = "6569517623"
RULING_ID = "6570059961"  # the orchestrator's ruling of record on the BQ list
BQ_IDS = tuple(f"BQ-{n}" for n in range(18))  # BQ-17 is the one the ruling adds
BQ_PENDING = "ruling pending"
BOTH = (
    "**The single most important sentence (T Tech).** The flash-rate budget applies in both"
    " motion modes"
)
AC3_SURFACES = ("Heatmap trail", "bubble", "Value flash", "Panel", "Toast", "Rule-graph", "Replay")
LAYERS = ("DOM", "canvas")
T2_PARA = "**The T2 paragraph (G-T2;"
T2_NAMES = (
    "CMP-079 RbacGate",
    "CMP-019 Icon `lock`",
    "rendering 2a",
    "in the DOM at mount",
    "`aria-describedby`",
    '`aria-disabled="true"`',
    "`Space`",
    "hotkey",
    "one polite announcement",
    "`↑` / `↓`",
)
T2_CITERS = ("## 8.", "## 9.", "## 11.")
FEED = "the feed keeps running"
AGENT_RE = re.compile(r"worker|orchestrator|\bagent\b|\blane\b", re.IGNORECASE)
OWNER_OK_RE = re.compile(r"\bE\d\d-[A-Z]+\d\d\b|\bowner")
PUBLIC_RE = re.compile(
    r"https?://|www\.|/home/|localhost|\.local\b|\b[a-z0-9-]+\.(?:com|io|org|net)\b",
    re.IGNORECASE,
)
KEYWORD_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[\s:]*#\d+", re.IGNORECASE)
MX_RE = re.compile(r"\bMX-(\d\d)\b")
SHA_RE = re.compile(r"`([0-9a-f]{9})`")
TOKEN_RE = re.compile(r"`([^`]+)`")

Finding = tuple[str, str, str, str]  # gate, message, doc, region
Values = dict[str, str]


# ---------------------------------------------------------------------------- git and files


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )


def git(*args: str) -> str:
    done = run_git(*args)
    if done.returncode != 0:
        raise SystemExit(f"FAIL git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


@functools.lru_cache(maxsize=64)
def at_base(rel: str) -> str:
    return git("show", f"{FILE_BASE.get(rel, BASE)}:{rel}")


@functools.lru_cache(maxsize=64)
def base_lines(rel: str) -> tuple[str, ...]:
    return tuple(at_base(rel).split("\n"))


@functools.lru_cache(maxsize=8)
def has_commit(sha: str) -> bool:
    return run_git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def changed_paths() -> tuple[str, ...]:
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
        return {"spec": self.spec, "hand": self.hand}[name]


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


def body(text: str, prefix: str) -> list[str]:
    s, e, _ = section(text, prefix)
    return text.split("\n")[s:e]


def cells(line: str) -> list[str]:
    inner = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def is_rule_row(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


def tables(text: str, prefix: str) -> list[list[list[str]]]:
    out: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for line in body(text, prefix):
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


# ---------------------------------------------------------------------------- anchors

ANCHOR_RE = re.compile(
    r"(?<![0-9A-Za-z.,])([0-9A-Za-z.,]+)<!--=([A-Z]+):([a-z0-9.\-]+)-->", re.DOTALL
)
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z]+):([a-z0-9.\-]+)\}\}")
ANCHOR_TAG_RE = re.compile(r"<!--=[A-Z]+:[a-z0-9.\-]+-->", re.DOTALL)
COMMENT_RE = re.compile(r"<!--", re.DOTALL)


def cut_anchors(text: str) -> str:
    return ANCHOR_RE.sub(lambda m: f"<!--={m.group(2)}:{m.group(3)}-->", text)


def unanchor(text: str) -> str:
    """The text as read: each anchor reduced to its value."""
    return ANCHOR_TAG_RE.sub("", text)


# ---------------------------------------------------------------------------- the inventory


@dataclass(frozen=True)
class Row:
    rid: str
    surface: str
    layer: str
    klass: str
    full: str
    calm: str
    reduced: str
    owner: str


def inventory(spec: str) -> list[Row]:
    out: list[Row] = []
    for r in first_table(spec, "## 3.")[1:]:
        if len(r) != 9:
            out.append(Row(r[0] if r else "?", "", "", "", "", "", "", ""))
            continue
        out.append(Row(r[0], r[1], r[3], r[4], r[5], r[6], r[7], r[8]))
    return out


def g_rows(spec: str) -> set[str]:
    return {r[0] for r in first_table(spec, "### 18.2")[1:] if r}


# ---------------------------------------------------------------------------- the simulation


def fr_value(spec: str, fr: str) -> str:
    for r in first_table(spec, "### 4.1")[1:]:
        if r and r[0] == fr and len(r) > 2:
            return unanchor(r[2])
    return ""


def per_window_interval(value: str) -> int | None:
    """'1 per 1 000 ms' -> 1000; '2 per 1 000 ms' -> 500 (the minimum interval it implies)."""
    m = re.fullmatch(r"(\d+) per ([\d ]+) ms", value)
    if not m or int(m.group(1)) == 0:
        return None
    return int(m.group(2).replace(" ", "")) // int(m.group(1))


def max_window(starts: list[int], window: int = 1000) -> int:
    """The most starts in any half-open window [s, s + window)."""
    xs = sorted(starts)
    best = 0
    for i, s in enumerate(xs):
        n = sum(1 for x in xs[i:] if x < s + window)
        best = max(best, n)
    return best


@dataclass(frozen=True)
class Sim:
    ticks: int
    price: int
    liq: int
    heat: int
    bubble: int
    naive: int
    combined: int
    frames: int
    cell_ms: int
    coal_ms: int
    region_cap: int
    gate: int


def simulate(spec: str) -> Sim | None:
    preset = re.search(
        r"burst: Object\.freeze\(\{ rateHz: (\d+), durationMs: (\d+) \}\)",
        at_base(CITE_FILES["TICKS"]),
    )
    coal = re.search(r"windowMs: (\d+)", at_base(CITE_FILES["COAL"]))
    cadence = re.search(r"(\d+)ms cadence", base_lines(PLAN["06"])[37])
    cell = re.fullmatch(r"(\d+) ms", fr_value(spec, "FR-1"))
    region = re.fullmatch(r"\d+", fr_value(spec, "FR-3"))
    gate = re.fullmatch(r"\d+", fr_value(spec, "FR-7"))
    liq_ms = per_window_interval(fr_value(spec, "FR-5"))
    heat_ms = per_window_interval(fr_value(spec, "FR-6"))
    if not (preset and coal and cadence and cell and region and gate and liq_ms and heat_ms):
        return None
    rate, dur = int(preset.group(1)), int(preset.group(2))
    count = (dur * rate) // 1000
    ticks = [math.floor(i * 1000 / rate + 0.5) for i in range(count)]
    step = int(cadence.group(1))
    heat_ticks = list(range(0, dur, step))
    cell_ms = int(cell.group(1))
    cap = int(region.group(0))
    interval = {"liq": liq_ms, "price": cell_ms, "heat": heat_ms}
    requests = {"liq": ticks, "price": ticks, "heat": heat_ticks}

    def alone(src: str) -> list[int]:
        out: list[int] = []
        for t in requests[src]:
            if not out or t - out[-1] >= interval[src]:
                out.append(t)
        return out

    solo = {src: alone(src) for src in interval}
    naive = max_window([t for src in interval for t in solo[src]])
    last: dict[str, int | None] = {src: None for src in interval}
    admitted: list[int] = []
    for t in sorted(set(ticks) | set(heat_ticks)):
        for src in ("liq", "price", "heat"):  # FR-9: liquidation, the focused symbol, the rest
            if t not in requests[src]:
                continue
            prev = last[src]
            if prev is not None and t - prev < interval[src]:
                continue
            if sum(1 for s in admitted if s > t - 1000) >= cap:
                continue
            admitted.append(t)
            last[src] = t
    return Sim(
        ticks=count,
        price=max_window(solo["price"]),
        liq=max_window(solo["liq"]),
        heat=max_window(solo["heat"]),
        bubble=0,  # bubbles never flash (DNA-3; REG MX-12): no request is made
        naive=naive,
        combined=max_window(admitted),
        frames=cell_ms * 60 // 1000,
        cell_ms=cell_ms,
        coal_ms=int(coal.group(1)),
        region_cap=cap,
        gate=int(gate.group(0)),
    )


# ---------------------------------------------------------------------------- values


THEME_RE = re.compile(r"dark(?: \+ (light|hc))?")
FRAME_THEME_RE = re.compile(r"· (dark|light|hc)`")


def board_themes(cell: str) -> set[str] | None:
    """The themes a §0 Theme cell plans: dark, plus at most one twin; None if malformed."""
    m = THEME_RE.fullmatch(cell)
    return None if m is None else {"dark"} | ({m.group(1)} if m.group(1) else set())


def frame_themes(hand: str) -> dict[str, set[str]]:
    """Board number -> the themes of its frames in the hand-off's §H."""
    return {
        r[0]: set(FRAME_THEME_RE.findall(r[1]))
        for r in first_table(hand, "## §H")[1:]
        if len(r) > 1
    }


def count_values(t: Texts) -> Values:
    rows = first_table(t.spec, "## 0.")[1:]
    inv = inventory(t.spec)
    return {
        "COUNT:boards": str(len(rows)),
        "COUNT:boards.twins": str(sum(1 for r in rows if len(r) > 3 and " + " in r[3])),
        "COUNT:inv.rows": str(len(inv)),
        "COUNT:inv.animated": str(sum(1 for r in inv if r.klass.endswith("animated"))),
        "COUNT:inv.static": str(sum(1 for r in inv if r.klass.endswith("static"))),
        "COUNT:inv.canvas": str(sum(1 for r in inv if r.layer == "canvas")),
        "COUNT:heuristics": str(len(first_table(t.spec, "## 16.")[1:])),
        "COUNT:walkthrough": str(sum(1 for ln in body(t.hand, "## §E") if ln.startswith("- ["))),
    }


def sim_values(spec: str) -> Values:
    s = simulate(spec)
    if s is None:
        return {}
    return {
        "SIM:ticks": str(s.ticks),
        "SIM:price": str(s.price),
        "SIM:liq": str(s.liq),
        "SIM:heat": str(s.heat),
        "SIM:bubble": str(s.bubble),
        "SIM:naive": str(s.naive),
        "SIM:combined": str(s.combined),
        "SIM:frames": str(s.frames),
    }


def compute_values(t: Texts) -> Values:
    return {**sim_values(t.spec), **count_values(t)}


# ---------------------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    mid: str
    what: str
    gate: str
    doc: str  # "spec", "hand" or "changed"
    where: str  # a heading prefix; "" = the whole document; "<eof>" = append
    old: str
    new: str


KW = "Clo" + "ses"  # assembled so that this file never carries the keyword itself

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1",
        "drop the both-modes sentence from the opening",
        "G-BOTH",
        "spec",
        "",
        "The flash-rate budget applies in both motion modes:",
        "The flash-rate budget applies:",
    ),
    Mutation(
        "M-2",
        "mark BQ-5 pending after the ruling",
        "G-PENDING",
        "spec",
        "## The questions",
        "(E05D03:109, :270) — RULED (6570059961)",
        "(E05D03:109, :270) — default built; ruling pending",
    ),
    Mutation(
        "M-3",
        "re-pin E47-D05 to an unknown commit in the start line",
        "G-PIN",
        "spec",
        "",
        "read at its head `3987edc89` (R6)",
        "read at its head `3987edc80` (R6)",
    ),
    Mutation(
        "M-4",
        "draw an eleventh board in §0",
        "G-BOARDS",
        "spec",
        "## 0.",
        "| 10  | `E47-D08 / 10 forced-reduce`",
        "| 11  | `E47-D08 / 11 extra` | more | dark | pending: drawn later in this PR |\n"
        "| 10  | `E47-D08 / 10 forced-reduce`",
    ),
    Mutation(
        "M-5",
        "misnumber board 05's name",
        "G-BOARDS",
        "spec",
        "## 0.",
        "`E47-D08 / 05 liquidation`",
        "`E47-D08 / 06 liquidation`",
    ),
    Mutation(
        "M-6",
        "resolve the drawer's reduced variant to unchanged",
        "G-INV",
        "spec",
        "## 3.",
        "none: open at frame 0",
        "unchanged",
    ),
    Mutation(
        "M-7",
        "blank the momentum coast's reduced cell",
        "G-INV",
        "spec",
        "## 3.",
        "| off: the pan stops where pointer-up left it                      |",
        "|                                                                  |",
    ),
    Mutation(
        "M-8",
        "put a token on I-1 that its owner row lacks",
        "G-INV",
        "spec",
        "## 3.",
        "`translateY(8px)` → 0; `motion.duration.fast`",
        "`translateY(8px)` → 0; `motion.duration.slow`",
    ),
    Mutation(
        "M-9",
        "calm the value flash under canvas calm",
        "G-INV",
        "spec",
        "## 3.",
        "`motion.easing.accelerate` | as full ",
        "`motion.easing.accelerate` | none    ",
    ),
    Mutation(
        "M-10",
        "point the heatmap rows at a G-row that does not exist",
        "G-INV",
        "spec",
        "## 3.",
        "no age fade                     | D08-G1",
        "no age fade                     | D08-G9",
    ),
    Mutation(
        "M-11",
        "raise the region cap FR-3 to 3",
        "G-BUDGET",
        "spec",
        "### 4.1",
        "| 2           | AC2; CAL:11",
        "| 3           | AC2; CAL:11",
    ),
    Mutation(
        "M-12",
        "set the cell interval FR-1 off the coalescer's default",
        "G-BUDGET",
        "spec",
        "### 4.1",
        "| 500 ms      | E05D03:105 (HS-1); COAL:81",
        "| 400 ms      | E05D03:105 (HS-1); COAL:81",
    ),
    Mutation(
        "M-13",
        "cite a register row that does not exist",
        "G-REG",
        "spec",
        "### 4.2",
        "none (no flash; REG MX-12)",
        "none (no flash; REG MX-19)",
    ),
    Mutation(
        "M-14",
        "announce follow-live as paused",
        "G-PAUSE",
        "spec",
        "## 8.",
        "W-4 off and W-10 on, once, politely;",
        "Paused at hh:mm, once, politely;",
    ),
    Mutation(
        "M-15",
        "drop the feed line from the tape row",
        "G-PAUSE",
        "spec",
        "## 8.",
        "the feed keeps running; the chip counts new prints",
        "the chip counts new prints",
    ),
    Mutation(
        "M-16",
        "let the freeze banner flash",
        "G-SAFETY",
        "spec",
        "## 11.",
        "identical; a cut on appearance | never",
        "identical; a cut on appearance | once ",
    ),
    Mutation(
        "M-17",
        "drop the reason-at-mount clause from §12",
        "G-T2",
        "spec",
        "## 12.",
        "The reason node is in the DOM at mount,",
        "The reason node is rendered,",
    ),
    Mutation(
        "M-18",
        "drop §11's pointer to §12",
        "G-T2",
        "spec",
        "## 11.",
        "ARMED with its timer; T2 per §12",
        "ARMED with its timer; T2 below",
    ),
    Mutation(
        "M-19",
        "point a §1.3 cite past the end of the register",
        "G-CITE",
        "spec",
        "### 1.3",
        "REG:5–6",
        "REG:5–96",
    ),
    Mutation(
        "M-20",
        "re-word W-1",
        "G-QUOTE",
        "spec",
        "## 15.",
        '"Reduced motion on"         ',
        '"Reduced motion is on"      ',
    ),
    Mutation(
        "M-21",
        "re-word D08-A5's Old fragment",
        "G-AROW",
        "hand",
        "## §C",
        "| (§7.4) ",
        "| (§7.5) ",
    ),
    Mutation(
        "M-22",
        "drop `(heuristic)` from H-3",
        "G-HEUR",
        "spec",
        "## 16.",
        "| H-3 | (heuristic) Visibility",
        "| H-3 | Visibility",
    ),
    Mutation(
        "M-23",
        "add a walkthrough item in the hand-off's §E",
        "G-WALK",
        "hand",
        "## §E",
        "- [ ] Record `approved` on #1307",
        "- [ ] One more.\n- [ ] Record `approved` on #1307",
    ),
    Mutation(
        "M-24",
        "name an agent as D08-G3's owner",
        "G-OWNER",
        "spec",
        "### 18.2",
        "| E47-S04 (#1318)               | E08-S08 (#4702)",
        "| the motion worker             | E08-S08 (#4702)",
    ),
    Mutation(
        "M-25",
        "write a host beside the Penpot page in §0",
        "G-PUBLIC",
        "spec",
        "## 0.",
        "page `E47-D08 — Motion`, cited",
        "page `E47-D08 — Motion` at design.example.com, cited",
    ),
    Mutation(
        "M-26",
        "put a closing keyword in the hand-off summary",
        "G-KEYWORD",
        "hand",
        "## §I",
        "boards pending, drawn later in this PR.",
        f"boards pending, drawn later in this PR. {KW} #1307.",
    ),
    Mutation(
        "M-27",
        "change the boards count in the header",
        "G-ANCHOR",
        "spec",
        "",
        "**Status:** text first; the 10<!--=COUNT:boards-->",
        "**Status:** text first; the 9<!--=COUNT:boards-->",
    ),
    Mutation(
        "M-28",
        "leave a placeholder unfilled",
        "G-MARKER",
        "spec",
        "<eof>",
        "",
        "\n{{COUNT:boards}}\n",
    ),
    Mutation(
        "M-29",
        "touch `22` in the working tree",
        "G-UNTOUCHED",
        "changed",
        "",
        "",
        "docs/plan/22-api-openapi.yaml",
    ),
    Mutation(
        "M-30",
        "pad the spec past its line budget",
        "G-LINES",
        "spec",
        "<eof>",
        "",
        "\n" * SPEC_LINES,
    ),
    Mutation(
        "M-31",
        "replace a mutation row's gate in §17",
        "G-MUTLIST",
        "spec",
        "## 17.",
        "| M-1 | drop the both-modes sentence from the opening | G-BOTH |",
        "| M-1 | drop the both-modes sentence from the opening | G-PIN |",
    ),
    Mutation(
        "M-32",
        "drop board 09's dark frame in the hand-off's §H",
        "G-BOARDS",
        "hand",
        "## §H",
        "`safety/reduced · dark`, `safety/reduced · hc`",
        "`safety/reduced · hc`",
    ),
)

PROBES: tuple[Mutation, ...] = (
    Mutation(
        "P-1",
        "flip a prose sentence in §4.5",
        "G-RULED-PIN",
        "spec",
        "### 4.5",
        "never flashes faster",
        "rarely flashes faster",
    ),
    Mutation(
        "P-2",
        "re-word a hand-off summary item",
        "G-RULED-PIN",
        "hand",
        "## §I",
        "checked against its owning spec row",
        "matched to its owning spec row",
    ),
)


def mutation_rows(ms: tuple[Mutation, ...] = MUTATIONS) -> str:
    return "\n".join(f"| {m.mid} | {m.what} | {m.gate} |" for m in ms)


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
        # runs of spaces match any run, so table padding from the formatter never breaks a target
        found = re.search(re.sub(r"(?:\\ )+", "[ ]+", re.escape(m.old)), span)
        if found is None:
            raise SystemExit(f"FAIL {m.mid}: its target text is not in {m.doc} {m.where!r}")
        k = found.start() + offset
        new_text = text[:k] + m.new + text[k + len(found.group(0)) :]
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
            if COMMENT_RE.search(ANCHOR_TAG_RE.sub("", line)):
                out.append(("G-MARKER", f"a stray HTML comment on line {i + 1}", doc, regions[i]))
    return out


CITE_RE = re.compile(
    r"(?:`(\d\d)`|\b(" + "|".join(CITE_FILES) + r"))" r"(:\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
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


def resolves(rel: str, n: int) -> bool:
    lines = base_lines(rel)
    return 1 <= n <= len(lines) and bool(lines[n - 1].strip())


def g_cite(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            for rel, n in cite_targets(line):
                if rel.startswith("?"):
                    out.append(("G-CITE", f"unknown cite key {rel[1:]}", doc, regions[i]))
                elif not resolves(rel, n):
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
    _, _, region = section(t.spec, "## 15.")
    for row in first_table(t.spec, "## 15.")[1:]:
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
        if not cite_targets(row[2]) or row[3].replace("\\|", "|") not in cited_text(row[2]):
            out.append(("G-AROW", f"{row[0]}'s Old is not verbatim on its line", "hand", region))
    return out


def g_both(t: Texts) -> list[Finding]:
    bad: list[str] = []
    paras = [ln for ln in t.spec.split("\n")[1:] if ln.strip()]
    if not paras or not paras[0].startswith(BOTH):
        bad.append("the spec does not open with the both-modes sentence")
    r1 = [ln for ln in body(t.spec, "### 1.4") if ln.startswith("- **R-1 ")]
    if len(r1) != 1 or "under `safe` and `reduce` alike" not in r1[0]:
        bad.append("R-1 does not bind the budget in both modes")
    for r in first_table(t.spec, "## 5.")[1:]:
        if len(r) < 3 or not r[1].strip() or not r[2].strip():
            bad.append(f"§5 carrier {r[0] if r else '?'} has no hold or source")
    return [("G-BOTH", b, "spec", "") for b in bad]


def g_pending(t: Texts) -> list[Finding]:
    s, e, region = section(t.spec, "## The questions")
    head = t.spec.split("\n")[s - 1] if s else ""
    lines = t.spec.split("\n")[s:e]
    bad: list[str] = []
    if f"RULED (comment {RULING_ID})" not in head:
        bad.append("the heading does not name the ruling of record")
    if BQ_LIST_ID not in "\n".join(lines):
        bad.append("the section does not name the BQ list")
    for bq in BQ_IDS:
        rows = [ln for ln in lines if ln.startswith(f"- **{bq}**")]
        if len(rows) != 1:
            bad.append(f"{bq} appears {len(rows)} times")
        elif RULING_ID not in rows[0] or "RULED" not in rows[0] or BQ_PENDING in rows[0]:
            bad.append(f"{bq} is not marked RULED with comment {RULING_ID}")
    if any(
        re.match(r"- \*\*BQ-(\d+)\*\*", ln) and ln[4:9].rstrip("*") not in BQ_IDS for ln in lines
    ):
        bad.append("a BQ outside BQ-0 ... BQ-17")
    return [("G-PENDING", b, "spec", region) for b in bad]


def g_pin(t: Texts) -> list[Finding]:
    head = "\n".join(t.spec.split("\n")[: section(t.spec, "## Acceptance")[0]])
    seen = set(SHA_RE.findall(head))
    bad = [f"`{s}` is not a pinned commit" for s in sorted(seen - set(PINNED))]
    bad += [f"`{s}` is not named in the header" for s in PINNED if s not in seen]
    bad += [f"`{s}` is not in the object store; fetch it" for s in PINNED if not has_commit(s)]
    for name in ("#5417", "#5387"):
        if name not in head:
            bad.append(f"the in-flight PR {name} is not named")
    return [("G-PIN", b, "spec", "") for b in bad]


def g_boards(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 0.")
    rows = first_table(t.spec, "## 0.")[1:]
    bad: list[str] = []
    if not 1 <= len(rows) <= 10:
        bad.append(f"{len(rows)} boards")
    twins = [r for r in rows if len(r) > 3 and " + " in r[3]]
    if 3 * len(twins) > len(rows):
        bad.append(f"{len(twins)} twins of {len(rows)} boards")
    frames = frame_themes(t.hand)
    _, _, h_region = section(t.hand, "## §H")
    off: list[Finding] = []
    for k, r in enumerate(rows, 1):
        themes = board_themes(r[3]) if len(r) >= 5 else None
        if themes is None:
            bad.append(f"board {r[0] if r else '?'} has no theme")
            continue
        if frames.get(r[0]) != themes:
            msg = f"board {r[0]}'s §H frames are not its themes {sorted(themes)}"
            off.append(("G-BOARDS", msg, "hand", h_region))
        name = re.fullmatch(r"`E47-D08 / (\d\d) ([a-z0-9-]+)`", r[1])
        if not name or name.group(1) != r[0] or r[0] != f"{k:02d}":
            bad.append(f"board {r[0]} is misnamed")
        if r[4] != PENDING_CELL:
            bad.append(f"board {r[0]} is not pending")
    if not any("**Not drawn (the text is binding)**" in ln for ln in body(t.spec, "## 0.")):
        bad.append("no 'not drawn' paragraph")
    return [("G-BOARDS", b, "spec", region) for b in bad] + off


def g_inv(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 3.")
    rows = inventory(t.spec)
    grows = g_rows(t.spec)
    bad: list[str] = []
    for k, r in enumerate(rows, 1):
        if r.rid != f"I-{k}":
            bad.append(f"row {r.rid} is out of order")
        if not all((r.surface, r.full, r.calm, r.reduced, r.owner)):
            bad.append(f"{r.rid} has an empty cell")
            continue
        if r.layer not in LAYERS or not re.fullmatch(
            r"(data-rate|interaction) (animated|static)", r.klass
        ):
            bad.append(f"{r.rid} has no layer or class")
            continue
        static = r.klass.endswith("static")
        for tier, cell in (("calm", r.calm), ("reduced", r.reduced)):
            if cell.startswith("unchanged") and not static:
                bad.append(f"{r.rid}'s {tier} variant is unchanged on an animated row")
        if not static and r.reduced == r.full:
            bad.append(f"{r.rid}'s reduced variant repeats the full one")
        if r.layer == "canvas" and r.calm != r.reduced:
            bad.append(f"{r.rid} is canvas but its calm and reduced cells differ")
        if r.layer == "DOM" and r.calm != "as full":
            bad.append(f"{r.rid} is DOM but its calm cell is not 'as full'")
        if re.fullmatch(r"D08-G\d+", r.owner):
            if r.owner not in grows:
                bad.append(f"{r.rid}'s owner {r.owner} is not in §18.2")
            continue
        targets = cite_targets(r.owner)
        if len(targets) != 1 or targets[0][0].startswith("?") or not resolves(*targets[0]):
            bad.append(f"{r.rid}'s owner {r.owner} is not one resolvable cite")
            continue
        line = cited_text(r.owner)
        bad += [
            f"{r.rid}'s token `{tok}` is not on {r.owner}"
            for tok in TOKEN_RE.findall(r.full)
            if f"`{tok}`" not in line and tok not in line
        ]
    for want in AC3_SURFACES:
        if not any(want.lower() in r.surface.lower() for r in rows):
            bad.append(f"AC3's {want} has no row")
    return [("G-INV", b, "spec", region) for b in bad]


def g_budget(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 4.1")
    s = simulate(t.spec)
    if s is None:
        return [("G-BUDGET", "the simulation inputs do not parse", "spec", region)]
    bad: list[str] = []
    if s.cell_ms != s.coal_ms:
        bad.append(f"FR-1 {s.cell_ms} ms differs from the coalescer's {s.coal_ms} ms")
    for name, v in (("price", s.price), ("liquidation", s.liq), ("heatmap", s.heat)):
        if v > 2:
            bad.append(f"{name} starts {v} in a window")
    if s.bubble != 0:
        bad.append("the bubble flashes")
    if s.combined > s.region_cap or s.combined >= s.gate or s.region_cap >= s.gate:
        bad.append(f"the region starts {s.combined} (cap {s.region_cap}, gate {s.gate})")
    return [("G-BUDGET", b, "spec", region) for b in bad]


def g_reg(t: Texts) -> list[Finding]:
    reg = at_base(CITE_FILES["REG"])
    known = set(re.findall(r"^\| MX-(\d\d) ", reg, flags=re.MULTILINE))
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            if line.startswith("| MX-"):
                out.append(("G-REG", f"a register row is copied on line {i + 1}", doc, regions[i]))
            new_rows = doc == "hand" and "insert row after" in line
            for mx in MX_RE.findall(line):
                if mx not in known and not new_rows:
                    out.append(("G-REG", f"MX-{mx} is not in the register", doc, regions[i]))
    return out


def g_pause(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 8.")
    rows = first_table(t.spec, "## 8.")[1:]
    bad: list[str] = []
    for want in ("Replay", "Tape", "Follow-live"):
        if not any(r and r[0].startswith(want) for r in rows):
            bad.append(f"no {want} row")
    for r in rows:
        if len(r) < 4 or not r[1] or not r[2]:
            bad.append(f"'{r[0] if r else '?'}' has no pause or no announced state")
            continue
        if FEED not in r[3]:
            bad.append(f"'{r[0]}' does not say {FEED}")
        if r[0].startswith("Follow-live") and "Paused" in r[2]:
            bad.append("follow-live announces 'Paused'")
    for r in first_table(t.spec, "## 15.")[1:]:
        if r and r[0] == "W-4" and "Paused" in r[1]:
            bad.append("W-4 says 'Paused'")
    return [("G-PAUSE", b, "spec", region) for b in bad]


def g_safety(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 11.")
    rows = first_table(t.spec, "## 11.")[1:]
    bad: list[str] = []
    if len(rows) < 5:
        bad.append(f"{len(rows)} safety rows")
    for r in rows:
        if len(r) < 5 or r[4] != "never":
            bad.append(f"'{r[0] if r else '?'}' may flash")
        elif not re.search(r"glyph|word|frame|border", r[2]) or not r[3]:
            bad.append(f"'{r[0]}' has no static carrier")
    return [("G-SAFETY", b, "spec", region) for b in bad]


def g_t2(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    s, e, region = section(t.spec, "## 12.")
    para = [ln for ln in t.spec.split("\n")[s:e] if T2_PARA in ln]
    if len(para) != 1:
        out.append(("G-T2", f"§12 states the T2 paragraph {len(para)} times", "spec", region))
    else:
        out += [
            ("G-T2", f"§12's T2 paragraph does not name {n}", "spec", region)
            for n in T2_NAMES
            if n not in para[0]
        ]
    for prefix in T2_CITERS:
        _, _, reg = section(t.spec, prefix)
        if "§12" not in "\n".join(body(t.spec, prefix)):
            out.append(("G-T2", f"{prefix} does not cite §12", "spec", reg))
    lines, regions = t.hand.split("\n"), line_regions(t.hand)
    comp = [i for i, ln in enumerate(lines) if ln.startswith("Components: ")]
    if len(comp) != 1 or not all(x in lines[comp[0]] for x in ("CMP-079 RbacGate", "CMP-019")):
        reg = regions[comp[0]] if len(comp) == 1 else ""
        out.append(("G-T2", "the hand-off's component list omits CMP-079 or CMP-019", "hand", reg))
    return out


def g_heur(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 16.")
    return [
        ("G-HEUR", f"{r[0]} lacks (heuristic)", "spec", region)
        for r in first_table(t.spec, "## 16.")[1:]
        if len(r) < 2 or not r[1].startswith("(heuristic) ")
    ]


def g_walk(t: Texts) -> list[Finding]:
    _, _, region = section(t.hand, "## §E")
    n = sum(1 for ln in body(t.hand, "## §E") if ln.startswith("- ["))
    return [] if 1 <= n <= 10 else [("G-WALK", f"{n} walkthrough items", "hand", region)]


def g_owner(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for prefix, col in (("### 18.2", 3), ("### 18.3", 3)):
        _, _, region = section(t.spec, prefix)
        for r in first_table(t.spec, prefix)[1:]:
            owner = r[col] if len(r) > col else ""
            if AGENT_RE.search(owner) or not OWNER_OK_RE.search(owner):
                out.append(("G-OWNER", f"{r[0]}'s owner {owner!r}", "spec", region))
    return out


def g_lines(t: Texts, gate: str, test: Callable[[str], bool], what: str) -> list[Finding]:
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            if test(line):
                out.append((gate, f"{what} on line {i + 1}", doc, regions[i]))
    return out


def g_keyword(t: Texts) -> list[Finding]:
    out = g_lines(t, "G-KEYWORD", lambda ln: bool(KEYWORD_RE.search(ln)), "a closing keyword")
    for rel in (TOOL_REL, PIN_REL):
        path = ROOT / rel
        if path.exists() and KEYWORD_RE.search(path.read_text(encoding="utf-8")):
            out.append(("G-KEYWORD", f"a closing keyword in {rel}", "", ""))
    return out


def g_untouched(t: Texts) -> list[Finding]:
    extra = [p for p in t.changed if p not in OWN and not OWN_BOARDS.fullmatch(p)]
    return [("G-UNTOUCHED", f"{p} differs from the base", "", "") for p in extra]


def g_size(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc, cap in (("spec", SPEC_LINES), ("hand", HAND_LINES)):
        if t.doc(doc).count("\n") > cap:
            out.append(("G-LINES", f"{doc} has more than {cap} lines", "", ""))
    return out


def g_mutlist(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 17.")
    rows = [(r[0], r[1], r[2]) for r in first_table(t.spec, "## 17.")[1:] if len(r) > 2]
    if rows != [(m.mid, m.what, m.gate) for m in MUTATIONS]:
        return [("G-MUTLIST", "§17 differs from the tool's list", "spec", region)]
    return []


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
        text_line = re.sub(r"\s+", " ", cut_anchors(line)).strip()
        if not text_line:
            continue
        if re.match(r"^#{1,6} ", line):
            shape[reg] += "h"
            out.append((doc, reg, "heading", text_line))
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
            out.append((doc, reg, f"l{prose[reg]}", text_line))
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
    if PLACEHOLDER_RE.search(t.spec + t.hand) or "{{MUTATIONS" in t.spec:
        print("FAIL --repin-ruled refuses while a placeholder is unfilled")
        return 1
    rows = all_units(t)
    head = (
        "# E47-D08 pins (every unit of the spec and the hand-off): doc, region (heading path"
        f" #occurrence), location, exact normalised text; {len(rows)} units.\n"
        "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit; G-RULED-PIN).\n"
    )
    text = "".join(f"{d}\t{r}\t{loc}\t{x}\n" for d, r, loc, x in rows)
    old = read_pins()
    new = {(d, r, loc): x for d, r, loc, x in rows}
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            print(f"REPIN {key[0]} {key[2]} in {key[1][:60]}".encode("ascii", "replace").decode())
    (ROOT / PIN_REL).write_text(head + text, encoding="utf-8")
    print(f"wrote {PIN_REL}: {len(rows)} units")
    return 0


# ---------------------------------------------------------------------------- run


def findings(t: Texts, values: Values) -> list[Finding]:
    out: list[Finding] = []
    out += g_anchor(t, values) + g_marker(t) + g_cite(t) + g_quote(t) + g_arow(t)
    out += g_both(t) + g_pending(t) + g_pin(t) + g_boards(t) + g_inv(t) + g_budget(t)
    out += g_reg(t) + g_pause(t) + g_safety(t) + g_t2(t) + g_heur(t) + g_walk(t) + g_owner(t)
    out += g_lines(t, "G-PUBLIC", lambda ln: bool(PUBLIC_RE.search(ln)), "a URL, host or name")
    out += g_keyword(t) + g_untouched(t) + g_size(t) + g_mutlist(t) + g_pins(t)
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
        if f[0] == "G-RULED-PIN" and any(
            (d == f[2] or not d) and (related(r, f[3]) or not r) for d, r in other
        ):
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
    t = replace(t, spec=t.spec.replace("{{MUTATIONS}}", mutation_rows()))
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
    total = len(MUTATIONS) + len(PROBES)
    print(f"self-test: {total - bad} of {total} ok")
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
