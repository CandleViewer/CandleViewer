#!/usr/bin/env python3
"""E47-D04 (#1303) audit: the focus order, focus visibility and landmark model (text first).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the plan texts and merged design texts the spec cites,
`14`'s `### SCR` headings and their Type lines, the E47-D02 register (at its merge commit) and the
token JSON; and, from the working tree, the spec `docs/design/E47/E47-D04.md`, its hand-off, the
`05` section this PR edits and the pins file. Its form follows the E12-D07 tool (the same modes,
the anchored values, the default-deny pins and the mutations).

1. **Values.** Every `{{KIND:key}}` placeholder is written by `--fill` as `VALUE<!--=KIND:key-->`:
   COUNT (rows of the spec's and the hand-off's own tables, the map, the register join) and
   CONTRAST (a WCAG 2.x ratio over the resolved tokens). `--check` re-derives each anchored value
   (G-ANCHOR) and FAILs a placeholder left behind or a stray HTML comment (G-MARKER). `--fill`
   also writes the mutation rows ({{MUTATIONS}}) from this file's constants.
2. **Cites.** Every `NN`:line and KEY:line cite of both documents resolves to a non-blank line at
   the base, the D02 catalogue's at its merge commit (G-CITE); every "verbatim" copy string occurs
   on its cited line (G-QUOTE); every Old fragment of the hand-off's A-rows occurs verbatim on its
   cited line (G-AROW).
3. **Gates.** One FAIL line per gate: G-PENDING (the BQ section names the BQ comment and carries
   BQ-0 … BQ-10 once each, each "default built; ruling pending" until a ruling flips it),
   G-BOARDS (at most ten boards, twins at most a third, every board pending or drawn with its id
   and PNG, the not-drawn paragraph), G-ARCH (the five archetype columns, every cell filled, the
   ring table's archetypes), G-MAP (every `14` id exactly once; the reserved ids are exactly those
   without a heading and the register's reserved screens; each row's Type equals the first word
   of each id's Type line), G-FINDINGS (the rows equal the register's E47-D04 rows: ids, screens,
   SC, status, remediation; each closed by an R-n of §1.4), G-RETAIN (every event class names a
   destination that is never the body, and an announcement cell), G-SAFE (no initial target is a
   destructive or committing control), G-CONTRAST (12 backgrounds incl. the brightest heatmap
   cells and the canvas; ring-halo pair and edge at least 3:1 in every theme), G-NORM (`05` §3.4
   item 11 carries every R-n of §1.4 and points here; the dead `05`:46 pointer is gone), G-HEUR,
   G-WALK (at most ten items), G-OWNER (G-ledger owners are tickets or owners, never an agent),
   G-UNMERGED, G-URL, G-UNTOUCHED (only this ticket's files, `05` and the boards differ from the
   merge base with origin/main), G-BUDGET (600 spec lines, 150 hand-off lines), G-MUTLIST.
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of both documents
   (each heading, table row by its lead cell and prose line, by heading path and occurrence, with
   a line-shape tag per region) in `e47_d04_ruled_pins.txt`. Anchored values are cut out of the
   pinned text (G-ANCHOR owns them). `--repin-ruled` is the only writer and refuses while a
   placeholder is unfilled. A pin finding in a region another gate already FAILs prints as NOTE.
5. **--self-test** applies every mutation (M-n) and pin probe (P-n) in memory with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names; the
   texts on disk are checked byte-identical afterwards (sha256). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e47_d04_focus_model_audit.py --check [--fill]
  python3 -I docs/design/_tools/e47_d04_focus_model_audit.py --self-test
  python3 -I docs/design/_tools/e47_d04_focus_model_audit.py --repin-ruled
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
BASE = "95a4f2765"  # origin/main when the spec was written; every cite is read here
D02_MERGE = "2a5bf8fd2"  # E47-D02 (#5248): its catalogue and register are read here

SPEC_REL = "docs/design/E47/E47-D04.md"
HAND_REL = "docs/design/E47/E47-D04-handoff.md"
TOOL_REL = "docs/design/_tools/e47_d04_focus_model_audit.py"
PIN_REL = "docs/design/_tools/e47_d04_ruled_pins.txt"
NORM_REL = "docs/plan/05-accessibility-standard.md"  # §3.4 item 11 is edited by this PR (BQ-2)
OWN = (SPEC_REL, HAND_REL, TOOL_REL, PIN_REL, NORM_REL)
OWN_BOARDS = re.compile(r"docs/design/E47/img/E47-D04-\d\d-[a-z0-9-]+\.png")
DRAWN_CELL = re.compile(
    r"drawn: board id `[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}`, "
    r"`docs/design/E47/img/E47-D04-(?P<nn>\d\d)-(?P<slug>[a-z0-9-]+)\.png` \(\d+ × \d+\)"
)
PENDING_CELL = "pending: drawn later in this PR"
SPEC_BUDGET = 600
HAND_BUDGET = 150

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "26": "docs/plan/26-chart-engine-design.md",
}
A11Y_PREFS = "apps/web/src/features/a11y-preferences"
CITE_FILES = {
    "D05E11": "docs/design/E11/E11-D05.md",
    "D04E11": "docs/design/E11/E11-D04.md",
    "D03E06": "docs/design/E06/E06-D03.md",
    "D09E09": "docs/design/E09/E09-D09.md",
    "D10E09": "docs/design/E09/E09-D10.md",
    "D01E29": "docs/design/E29/E29-D01.md",
    "D05E29": "docs/design/E29/E29-D05.md",
    "D15": "docs/design/E15/E15-D15.md",
    "D13": "docs/design/E15/E15-D13.md",
    "S07": "docs/design/E47/E47-S07.md",
    "Q01": "qa/plans/e47-accessibility-test-plan.md",
    "CAT": "docs/plan/a11y/47-audit-catalogue.md",
    "E47J": "docs/plan/backlog/E47.json",
    "PCX": f"{A11Y_PREFS}/PreferencesContext.tsx",
    "MODEL": f"{A11Y_PREFS}/model.ts",
    "ASS": f"{A11Y_PREFS}/AccessibilitySettingsScreen.tsx",
}
REGISTER_REL = "docs/plan/a11y/47-audit-register.json"
FILE_BASE = {CITE_FILES["CAT"]: D02_MERGE, REGISTER_REL: D02_MERGE}
UNMERGED_PATHS = tuple(f"E47-D{n:02d}.md" for n in (1, 3, 5, 6, 7, 9, 10))
DS_SRC_REL = "packages/ui/tokens"
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}

BQ_COMMENT = "6552540452"  # the BQ list on #1303; no ruling yet
BQ_PENDING_HEAD = "defaults built; ruling pending (the BQ comment on #1303)"
BQ_PENDING = "default built; ruling pending"
BQ_IDS = tuple(f"BQ-{n}" for n in range(11))

ARCHS = ("workspace", "full-page form", "dialog", "overlay / palette", "dense grid")
ARCH_KEYS = {
    "workspace": "workspace",
    "full-page form": "full-page-form",
    "dialog": "dialog",
    "overlay / palette": "overlay",
    "dense grid": "dense-grid",
}
RESERVED = "n/a (reserved)"
AC_ASPECTS = ("Tab sequence", "Roving zones", "Entry and exit keys", "Initial target")
RING = "color.focus.ring"
HALO = "color.surface.canvas"
BG_KEYS = (
    "hm-bid5",
    "hm-ask5",
    "cvd-bid5",
    "cvd-ask5",
    "hm-bid1",
    "hm-ask1",
    "hm-zero",
    "canvas",
    "raised",
    "selected",
    "buy",
    "sell",
)
BG_REQUIRED = ("color.heatmap.bid.5", "color.heatmap.ask.5", "color.surface.canvas")
BAR = 3.0  # non-text contrast (SC 1.4.11)
DESTRUCTIVE_RE = re.compile(
    r"\b(?:Confirm|Flatten|Cancel all|Delete|Disable|Revoke|Freeze|Submit|Save|Send|Next|Finish)\b"
)
BODY_RE = re.compile(r"\bbody\b", re.IGNORECASE)
AGENT_RE = re.compile(r"worker|orchestrator|\bagent\b|lane\b", re.IGNORECASE)
OWNER_OK_RE = re.compile(r"\bE\d\d-[A-Z]+\d\d\b|\bowner")
URL_RE = re.compile(
    r"https?://|www\.|/home/|localhost|\.local\b|\b[a-z0-9-]+\.(?:com|io|org|net)\b"
)

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
    # but on a rebased head only this PR's own diff counts.
    fork = git("merge-base", "HEAD", "origin/main").strip()
    tracked = git("diff", "--name-only", fork).split()
    untracked = git("ls-files", "--others", "--exclude-standard").split()
    return tuple(sorted(set(tracked) | set(untracked)))


# ---------------------------------------------------------------------------- markdown model


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    norm: str
    changed: tuple[str, ...]

    def doc(self, name: str) -> str:
        return {"spec": self.spec, "hand": self.hand, "norm": self.norm}[name]


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
    """Every table in the section: a list of rows (header first), each a list of cells."""
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


def plain(cell: str) -> str:
    return cell.replace("`", "").strip()


# ---------------------------------------------------------------------------- anchors

ANCHOR_RE = re.compile(r"(?<![0-9A-Za-z.,])([0-9A-Za-z.,]+)<!--=([A-Z]+):([a-z0-9.\-]+)-->")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z]+):([a-z0-9.\-]+)\}\}")


def cut_anchors(text: str) -> str:
    return ANCHOR_RE.sub(lambda m: f"<!--={m.group(2)}:{m.group(3)}-->", text)


def unanchor(text: str) -> str:
    """The text as read: each anchor reduced to its value."""
    return re.sub(r"<!--=[A-Z]+:[a-z0-9.\-]+-->", "", text)


# ---------------------------------------------------------------------------- the screens


@functools.lru_cache(maxsize=1)
def screen_kinds() -> dict[str, tuple[str, int]]:
    """Each `14` id with a heading: the first word of its Type line and that line's number."""
    out: dict[str, tuple[str, int]] = {}
    cur = ""
    for i, line in enumerate(base_lines(PLAN["14"]), 1):
        m = re.match(r"^### (SCR-\d{3})\b", line)
        if m:
            cur = m.group(1)
            continue
        if cur and cur not in out and line.startswith("- **Type:**"):
            w = re.match(r"[A-Za-z/\-]+", line.removeprefix("- **Type:**").strip())
            out[cur] = (w.group(0) if w else "?", i)
    return out


@functools.lru_cache(maxsize=1)
def register() -> dict[str, object]:
    data = json.loads(at_base(REGISTER_REL))
    if not isinstance(data, dict):
        raise SystemExit("FAIL the D02 register is not an object")
    return data


def register_screens() -> list[dict[str, str]]:
    screens = register().get("screens")
    return [s for s in screens if isinstance(s, dict)] if isinstance(screens, list) else []


def register_findings() -> list[dict[str, object]]:
    fs = register().get("findings")
    if not isinstance(fs, list):
        return []
    return [f for f in fs if isinstance(f, dict) and f.get("designOwner") == "E47-D04"]


def expand_ids(cell: str) -> list[str]:
    out: list[str] = []
    for a, b in re.findall(r"SCR-(\d{3})(?:–(\d{3}))?", cell):
        lo, hi = int(a), int(b or a)
        out += [f"SCR-{n:03d}" for n in range(lo, hi + 1)]
    return out


def map_rows(spec: str) -> list[list[str]]:
    t = first_table(spec, "## 5.")
    return t[1:] if t else []


# ---------------------------------------------------------------------------- contrast


def token_file(name: str) -> dict[str, object]:
    data = json.loads(at_base(f"{DS_SRC_REL}/{name}.tokens.json"))
    return {k: v.get("$value") for k, v in data.items() if isinstance(v, dict)}


@functools.lru_cache(maxsize=4)
def load_theme(name: str) -> dict[str, object]:
    merged: dict[str, object] = {}
    for f in THEMES[name]:
        merged.update(token_file(f))
    return merged


def hex_of(theme: str, name: str) -> str | None:
    tokens = load_theme(theme)
    value: object = tokens.get(name)
    hops = 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1]), hops + 1
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return None
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


def bg_rows(spec: str) -> list[list[str]]:
    t = first_table(spec, "### 7.6")
    return t[1:] if t else []


def bg_token(row: list[str]) -> str:
    return plain(row[1]) if len(row) > 1 else ""


def ring_measures(theme: str, token: str) -> tuple[float, float, float] | None:
    """(pair, ring vs the background, edge) or None when a token does not resolve."""
    ring, halo, bg = hex_of(theme, RING), hex_of(theme, HALO), hex_of(theme, token)
    if ring is None or halo is None or bg is None:
        return None
    r = contrast(ring, bg)
    return contrast(ring, halo), r, max(r, contrast(halo, bg))


def contrast_values(spec: str) -> Values:
    out: Values = {}
    lo_ring, lo_edge = 99.0, 99.0
    for theme in THEMES:
        ring, halo = hex_of(theme, RING), hex_of(theme, HALO)
        if ring and halo:
            out[f"CONTRAST:pair.{theme}"] = show_ratio(contrast(ring, halo))
    for key, row in zip(BG_KEYS, bg_rows(spec)):
        for theme in THEMES:
            m = ring_measures(theme, bg_token(row))
            if m is None:
                continue
            out[f"CONTRAST:{key}.{theme}.ring"] = show_ratio(m[1])
            out[f"CONTRAST:{key}.{theme}.edge"] = show_ratio(m[2])
            lo_ring, lo_edge = min(lo_ring, m[1]), min(lo_edge, m[2])
    out["CONTRAST:min.ring"] = show_ratio(lo_ring)
    out["CONTRAST:min.edge"] = show_ratio(lo_edge)
    return out


# ---------------------------------------------------------------------------- values


def count_values(t: Texts) -> Values:
    spec, hand = t.spec, t.hand
    boards = first_table(spec, "## 0.")[1:]
    rows = map_rows(spec)
    ids = [i for r in rows for i in expand_ids(r[0])]
    reserved = [i for r in rows if len(r) > 2 and r[2] == RESERVED for i in expand_ids(r[0])]
    fs = register_findings()
    out: Values = {
        "COUNT:boards": str(len(boards)),
        "COUNT:boards.twins": str(sum(1 for r in boards if len(r) > 3 and r[3] in ("light", "hc"))),
        "COUNT:map.ids": str(len(ids)),
        "COUNT:map.reserved": str(len(reserved)),
        "COUNT:map.rows": str(len(rows)),
        "COUNT:findings": str(len(fs)),
        "COUNT:findings.open": str(sum(1 for f in fs if str(f.get("status")).startswith("open"))),
        "COUNT:findings.fixed": str(sum(1 for f in fs if str(f.get("status")).startswith("fixed"))),
        "COUNT:copy": str(len(first_table(spec, "## 15.")[1:])),
        "COUNT:heuristics": str(len(first_table(spec, "## 16.")[1:])),
        "COUNT:walkthrough": str(sum(1 for ln in body(hand, "## §E") if ln.startswith("- ["))),
    }
    for arch, key in ARCH_KEYS.items():
        n = sum(len(expand_ids(r[0])) for r in rows if len(r) > 2 and r[2] == arch)
        out[f"COUNT:arch.{key}"] = str(n)
    return out


def compute_values(t: Texts) -> Values:
    return {**contrast_values(t.spec), **count_values(t)}


# ---------------------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    mid: str
    what: str
    gate: str
    doc: str  # "spec", "hand", "norm" or "changed"
    where: str  # a heading prefix; "" = the whole document; "<eof>" = append
    old: str
    new: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1",
        "blank board 01's status in §0",
        "G-BOARDS",
        "spec",
        "## 0.",
        "| dark  | pending: drawn later in this PR       |",
        "| dark  | —       |",
    ),
    Mutation(
        "M-2",
        "draw an eleventh board in §0",
        "G-BOARDS",
        "spec",
        "## 0.",
        "| 10  | `E47-D04 / 10 ring-hc-thick`",
        "| 11  | `E47-D04 / 11 extra` | more | dark | pending: drawn later in this PR |\n"
        "| 10  | `E47-D04 / 10 ring-hc-thick`",
    ),
    Mutation(
        "M-3",
        "empty the dialog's initial target in §4",
        "G-ARCH",
        "spec",
        "## 4.",
        "a form dialog's first field; a destructive confirm's Cancel; an informational dialog's"
        " safe button (R-6; §9.1)",
        "—",
    ),
    Mutation(
        "M-4",
        "map SCR-045 twice in §5",
        "G-MAP",
        "spec",
        "## 5.",
        "| SCR-050, SCR-063, SCR-070",
        "| SCR-045, SCR-050, SCR-063, SCR-070",
    ),
    Mutation(
        "M-5",
        "give SCR-021 the wrong Type in §5",
        "G-MAP",
        "spec",
        "## 5.",
        "| Interaction   |",
        "| Panel         |",
    ),
    Mutation(
        "M-6",
        "drop a D02 finding's closing rule in §14",
        "G-FINDINGS",
        "spec",
        "## 14.",
        "| R-12           | E47-T01 #1323",
        "| —              | E47-T01 #1323",
    ),
    Mutation(
        "M-7",
        "send a removed row's focus to the body in §8",
        "G-RETAIN",
        "spec",
        "## 8.",
        "else the previous, else the grid's empty-state stop ",
        "else the previous, else the document body ",
    ),
    Mutation(
        "M-8",
        "open the destructive confirm on Confirm in §9.1",
        "G-SAFE",
        "spec",
        "### 9.1",
        "| Cancel (`15`:525)            |",
        "| Confirm (`15`:525)           |",
    ),
    Mutation(
        "M-9",
        "measure a primary hover fill as background 5",
        "G-CONTRAST",
        "spec",
        "### 7.6",
        "| `color.heatmap.bid.1`      |",
        "| `color.action.primary.hover` |",
    ),
    Mutation(
        "M-10",
        "point a §1.3 cite past the end of D15",
        "G-CITE",
        "spec",
        "### 1.3",
        "D15:277, :189, :298",
        "D15:277, :189, :9298",
    ),
    Mutation(
        "M-11",
        "re-word W-1",
        "G-QUOTE",
        "spec",
        "## 15.",
        '"{name}, focused"',
        '"{name} focused"',
    ),
    Mutation(
        "M-12",
        "re-word D04-A3's Old fragment",
        "G-AROW",
        "hand",
        "## §C",
        "`aria-describedby`, focus-trap,",
        "`aria-describedby`, a focus trap,",
    ),
    Mutation(
        "M-13",
        "mark BQ-4 settled without a ruling",
        "G-PENDING",
        "spec",
        "## The questions",
        "never cancels an order — default built; ruling pending",
        "never cancels an order — accepted",
    ),
    Mutation(
        "M-14",
        "drop `(heuristic)` from H-3",
        "G-HEUR",
        "spec",
        "## 16.",
        "| (heuristic) Error prevention: focus landing",
        "| Error prevention: focus landing",
    ),
    Mutation(
        "M-15",
        "add two walkthrough items in the hand-off's §E",
        "G-WALK",
        "hand",
        "## §E",
        "- [ ] Board 01:",
        "- [ ] Extra one.\n- [ ] Extra two.\n- [ ] Board 01:",
    ),
    Mutation(
        "M-16",
        "name an agent as D04-G3's owner",
        "G-OWNER",
        "spec",
        "### 18.2",
        "E15-T02 (#403), the layout owner       | E47-S05 (#1319)                |\n| D04-G4",
        "the layout agent       | E47-S05 (#1319)                |\n| D04-G4",
    ),
    Mutation(
        "M-17",
        "link E47-D03's unmerged file in the start line",
        "G-UNMERGED",
        "spec",
        "",
        "E47-D03 (#1302),",
        "E47-D03 (#1302, `docs/design/E47/E47-D03.md`),",
    ),
    Mutation(
        "M-18",
        "write a host beside the Penpot page in §0",
        "G-URL",
        "spec",
        "## 0.",
        "page `E47-D04 — Focus model`, cited",
        "page `E47-D04 — Focus model` (design.example.com), cited",
    ),
    Mutation(
        "M-19",
        "change the boards count in the header",
        "G-ANCHOR",
        "spec",
        "",
        "10<!--=COUNT:boards--> boards of §0",
        "11<!--=COUNT:boards--> boards of §0",
    ),
    Mutation(
        "M-20", "pad the spec past its line budget", "G-BUDGET", "spec", "<eof>", "", "\n" * 600
    ),
    Mutation(
        "M-21",
        "touch `22` in the working tree",
        "G-UNTOUCHED",
        "changed",
        "",
        "",
        "docs/plan/22-api-openapi.yaml",
    ),
    Mutation(
        "M-22",
        "leave a placeholder unfilled",
        "G-MARKER",
        "spec",
        "## 0.",
        "**Not drawn (the text is binding)**",
        "**Not drawn (the text is binding)** {{COUNT:boards}}",
    ),
    Mutation(
        "M-23",
        "drop R-7 from `05` §3.4 item 11",
        "G-NORM",
        "norm",
        "",
        "- R-7 Every close path",
        "- Every close path",
    ),
    Mutation(
        "M-24",
        "replace a mutation row's gate in §17",
        "G-MUTLIST",
        "spec",
        "## 17.",
        "| G-WALK",
        "| G-WALKS",
    ),
)
PROBES: tuple[Mutation, ...] = (
    Mutation(
        "P-1",
        "flip a prose sentence in §6.1",
        "G-RULED-PIN",
        "spec",
        "### 6.1",
        "It never advances one row.",
        "It may advance one row.",
    ),
    Mutation(
        "P-2",
        "re-word a hand-off summary item",
        "G-RULED-PIN",
        "hand",
        "## §I",
        "enclosed by its halo",
        "ringed by its halo",
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
        # runs of spaces match any run, so table padding from the formatter never breaks a target
        found = re.search(re.sub(r"(?:\\ )+", "[ ]+", re.escape(m.old)), span)
        if found is None:
            raise SystemExit(f"FAIL {m.mid}: its target text is not in {m.doc} {m.where!r}")
        k = found.start() + offset
        new_text = text[:k] + m.new + text[k + len(found.group(0)) :]
    if m.doc == "spec":
        return replace(t, spec=new_text)
    if m.doc == "hand":
        return replace(t, hand=new_text)
    return replace(t, norm=new_text)


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
        if row[3].replace("\\|", "|") not in cited_text(row[2]):
            out.append(("G-AROW", f"{row[0]}'s Old is not verbatim on its line", "hand", region))
    return out


def g_pending(t: Texts) -> list[Finding]:
    s, e, region = section(t.spec, "## The questions")
    head = t.spec.split("\n")[s - 1] if s else ""
    lines = t.spec.split("\n")[s:e]
    bad: list[str] = []
    if BQ_PENDING_HEAD not in head:
        bad.append("the heading does not say the defaults are built and the ruling pending")
    if not any(BQ_COMMENT in ln for ln in lines):
        bad.append(f"the BQ comment {BQ_COMMENT} is not named")
    for bq in BQ_IDS:
        rows = [ln for ln in lines if ln.startswith(f"- **{bq}**")]
        if len(rows) != 1:
            bad.append(f"{bq} appears {len(rows)} times")
        elif BQ_PENDING not in rows[0]:
            bad.append(f"{bq} is not marked '{BQ_PENDING}'")
    return [("G-PENDING", b, "spec", region) for b in bad]


def g_boards(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 0.")
    rows = first_table(t.spec, "## 0.")[1:]
    bad: list[str] = []
    if not 1 <= len(rows) <= 10:
        bad.append(f"{len(rows)} boards")
    twins = [r for r in rows if len(r) > 3 and r[3] in ("light", "hc")]
    if 3 * len(twins) > len(rows):
        bad.append(f"{len(twins)} twins of {len(rows)} boards")
    for k, r in enumerate(rows, 1):
        if len(r) < 5 or r[3] not in ("dark", "light", "hc"):
            bad.append(f"board {r[0]} has no theme")
            continue
        name = re.fullmatch(r"`E47-D04 / (\d\d) ([a-z0-9-]+)`", r[1])
        if not name or name.group(1) != r[0] or r[0] != f"{k:02d}":
            bad.append(f"board {r[0]} is misnamed")
        drawn = DRAWN_CELL.fullmatch(r[4])
        if r[4] != PENDING_CELL and not (
            drawn and name and (drawn["nn"], drawn["slug"]) == name.groups()
        ):
            bad.append(f"board {r[0]} is neither pending nor drawn")
    if not any(
        ln.startswith("**Not drawn (the text is binding)**") for ln in body(t.spec, "## 0.")
    ):
        bad.append("no 'not drawn' paragraph")
    return [("G-BOARDS", b, "spec", region) for b in bad]


def g_arch(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 4.")
    table = first_table(t.spec, "## 4.")
    bad: list[str] = []
    if not table or tuple(table[0][1:]) != ARCHS:
        bad.append("the archetype columns are not the five")
    aspects = {r[0]: r[1:] for r in table[1:]}
    for a in AC_ASPECTS:
        if a not in aspects:
            bad.append(f"no '{a}' row")
    for a, row in aspects.items():
        if len(row) != len(ARCHS):
            bad.append(f"'{a}' has {len(row)} cells")
        for arch, c in zip(ARCHS, row):
            if not c or (a in AC_ASPECTS and c in ("—", "-", "n/a")):
                bad.append(f"'{a}' is empty for {arch}")
        if a == "Restore on exit" and any(BODY_RE.search(c) for c in row):
            bad.append("a restore lands on the body")
    ring = [r[0] for r in first_table(t.spec, "## 3.")[1:]]
    if tuple(ring) != ARCHS:
        bad.append("the ring table's archetypes are not the five")
    return [("G-ARCH", b, "spec", region) for b in bad]


def g_map(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 5.")
    kinds = screen_kinds()
    universe = [str(s.get("id")) for s in register_screens()]
    reg_reserved = {
        str(s.get("id"))
        for s in register_screens()
        if str(s.get("coverage")).startswith("reserved")
    }
    bad: list[str] = []
    if universe != [f"SCR-{n:03d}" for n in range(1, len(universe) + 1)] or not universe:
        bad.append("the register's screens are not SCR-001 … in order")
    seen: dict[str, int] = {}
    for r in map_rows(t.spec):
        if len(r) < 4:
            bad.append(f"a short row {r[:1]}")
            continue
        ids, typ, arch = expand_ids(r[0]), r[1], r[2]
        if not ids:
            bad.append(f"a row without ids ({r[0][:30]})")
        if arch not in (*ARCHS, RESERVED):
            bad.append(f"unknown archetype {arch!r}")
        for i in ids:
            seen[i] = seen.get(i, 0) + 1
            if arch == RESERVED:
                if i in kinds or typ != "(reserved)":
                    bad.append(f"{i} is not reserved")
            elif kinds.get(i, ("(none)", 0))[0] != typ:
                bad.append(f"{i}'s Type is {kinds.get(i, ('(none)', 0))[0]}, not {typ}")
    for i in universe:
        if seen.get(i, 0) != 1:
            bad.append(f"{i} is mapped {seen.get(i, 0)} times")
    extra = sorted(set(seen) - set(universe))
    if extra:
        bad.append(f"ids outside the register: {extra[:3]}")
    reserved = {i for i in universe if i not in kinds}
    if reserved != reg_reserved:
        bad.append("the ids without a `14` heading are not the register's reserved screens")
    return [("G-MAP", b, "spec", region) for b in bad]


def rule_ids(spec: str) -> list[str]:
    return [m.group(1) for ln in body(spec, "### 1.4") if (m := re.match(r"- \*\*(R-\d+) ", ln))]


def g_findings(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 14.")
    rows = {r[0]: r for r in first_table(t.spec, "## 14.")[1:] if r}
    rules = set(rule_ids(t.spec))
    bad: list[str] = []
    want = {str(f.get("id")): f for f in register_findings()}
    if set(rows) != set(want) or not want:
        bad.append(f"the rows differ from the register's E47-D04 rows ({len(rows)} / {len(want)})")
    for fid, f in want.items():
        r = rows.get(fid)
        if r is None or len(r) < 6:
            continue
        screens = f.get("screens")
        sc = f.get("sc")
        exp_screens = ", ".join(map(str, screens)) if isinstance(screens, list) else ""
        exp_sc = ", ".join(map(str, sc)) if isinstance(sc, list) and sc else "—"
        if r[1] != exp_screens or r[2] != exp_sc or r[3] != f.get("status"):
            bad.append(f"{fid}'s screens, SC or status differ from the register")
        if r[5] != f.get("remediation"):
            bad.append(f"{fid}'s remediation differs from the register")
        named = re.findall(r"\bR-\d+\b", r[4])
        if not named or any(n not in rules for n in named):
            bad.append(f"{fid} is closed by no rule of §1.4")
    return [("G-FINDINGS", b, "spec", region) for b in bad]


def g_retain(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 8.")
    rows = first_table(t.spec, "## 8.")[1:]
    bad: list[str] = []
    if sum(1 for r in rows if r and "re-seeds" in r[0]) < 2:
        bad.append("the two re-seed rows of T AC4 are missing")
    for r in rows:
        if len(r) < 4 or not r[1] or r[1] == "—" or not r[2]:
            bad.append(f"'{r[0]}' has no destination or announcement")
        elif BODY_RE.search(r[1]):
            bad.append(f"'{r[0]}' sends focus to the body")
    return [("G-RETAIN", b, "spec", region) for b in bad]


def g_safe(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.spec, "### 9.1")
    for r in first_table(t.spec, "### 9.1")[1:]:
        if len(r) < 3 or not r[1] or DESTRUCTIVE_RE.search(r[1]):
            out.append(("G-SAFE", f"'{r[0][:40]}' opens on {r[1][:30]!r}", "spec", region))
    _, _, region = section(t.spec, "## 4.")
    for r in first_table(t.spec, "## 4.")[1:]:
        if r and r[0] == "Initial target":
            for c in r[1:]:
                if DESTRUCTIVE_RE.search(c):
                    out.append(("G-SAFE", f"an archetype opens on {c[:30]!r}", "spec", region))
    return out


def g_contrast(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 7.6")
    rows = bg_rows(t.spec)
    tokens = [bg_token(r) for r in rows]
    bad: list[str] = []
    if len(rows) != len(BG_KEYS) or len(set(tokens)) != len(tokens):
        bad.append(f"{len(rows)} backgrounds, {len(set(tokens))} distinct; 12 wanted")
    for need in BG_REQUIRED:
        if need not in tokens:
            bad.append(f"{need} is not measured")
    for tok in tokens:
        for theme in THEMES:
            m = ring_measures(theme, tok)
            if m is None:
                bad.append(f"{tok} does not resolve in {theme}")
            elif m[0] < BAR or m[2] < BAR:
                bad.append(f"{tok} in {theme}: pair {show_ratio(m[0])}, edge {show_ratio(m[2])}")
    return [("G-CONTRAST", b, "spec", region) for b in bad]


def g_norm(t: Texts) -> list[Finding]:
    lines = t.norm.split("\n")
    bad: list[str] = []
    item = [i for i, ln in enumerate(lines) if ln.startswith("11. **Focus model (E47-D04).**")]
    if len(item) != 1 or SPEC_REL not in lines[item[0]]:
        bad.append("`05` §3.4 item 11 is missing or does not point at the spec")
    else:
        got = []
        for ln in lines[item[0] + 1 :]:
            m = re.match(r"\s+- (R-\d+) ", ln)
            if not m:
                break
            got.append(m.group(1))
        if got != rule_ids(t.spec):
            bad.append("`05` §3.4 item 11's rules differ from the spec's §1.4")
    if "§4.2 landmark model" in t.norm:
        bad.append("the dead `05`:46 pointer is still there")
    return [("G-NORM", b, "norm", "") for b in bad]


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
    _, _, region = section(t.spec, "### 18.2")
    out: list[Finding] = []
    for r in first_table(t.spec, "### 18.2")[1:]:
        owner = r[3] if len(r) > 3 else ""
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


def g_untouched(t: Texts) -> list[Finding]:
    extra = [p for p in t.changed if p not in OWN and not OWN_BOARDS.fullmatch(p)]
    return [("G-UNTOUCHED", f"{p} differs from the base", "", "") for p in extra]


def g_budget(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    for doc, cap in (("spec", SPEC_BUDGET), ("hand", HAND_BUDGET)):
        if t.doc(doc).count("\n") > cap:
            out.append(("G-BUDGET", f"{doc} has more than {cap} lines", "", ""))
    return out


def g_mutlist(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 17.")
    rows = [(r[0], r[1], r[2]) for r in first_table(t.spec, "## 17.")[1:] if len(r) > 2]
    want = [(m.mid, m.what, m.gate) for m in MUTATIONS]
    return (
        [] if rows == want else [("G-MUTLIST", "§17 differs from the tool's list", "spec", region)]
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
    if PLACEHOLDER_RE.search(t.spec + t.hand) or "{{MUTATIONS}}" in t.spec:
        print("FAIL --repin-ruled refuses while a placeholder is unfilled")
        return 1
    rows = all_units(t)
    head = (
        "# E47-D04 pins (every unit of the spec and the hand-off): doc, region (heading path"
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
    out += g_pending(t) + g_boards(t) + g_arch(t) + g_map(t) + g_findings(t)
    out += g_retain(t) + g_safe(t) + g_contrast(t) + g_norm(t) + g_heur(t) + g_walk(t)
    out += g_owner(t)
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
        norm=(ROOT / NORM_REL).read_text(encoding="utf-8"),
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
    digest = hashlib.sha256((t.spec + t.hand + t.norm).encode()).hexdigest()
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
    if hashlib.sha256((after.spec + after.hand + after.norm).encode()).hexdigest() != digest:
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
