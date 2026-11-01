#!/usr/bin/env python3
"""E08-D10 (#178) audit: SCR-151's E08 variants, empty and backfill states (text first).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the plan texts and merged design texts the spec cites,
CMP-026's `variant` enum, E08-D04's states and the token JSON; and, from the working tree, the spec
`docs/design/E08/E08-D10.md`, its hand-off, the pins file and the one `14` pointer line. Its form
follows the E12-D07 tool (the same modes, the anchored values, the default-deny pins, the mutations).

1. **Values.** Every `{{KIND:key}}` placeholder is written by `--fill` as `VALUE<!--=KIND:key-->`:
   COUNT (rows of the spec's and the hand-off's own tables), CITE (a figure parsed from the cited
   line at the base), PROP (this tool's PROPOSED constants) and CONTRAST (a WCAG 2.x ratio over the
   resolved tokens). `--check` re-derives each anchored value (G-ANCHOR) and FAILs a placeholder
   left behind or a stray HTML comment (G-MARKER). `--fill` also writes the mutation rows.
2. **Cites.** Every `NN`:line and KEY:line cite of both documents resolves to a non-blank line at
   the base (G-CITE); every "verbatim" copy string occurs on its cited line (G-QUOTE); every Old
   fragment of the hand-off's A-rows occurs verbatim on its cited line (G-AROW).
3. **Gates.** One FAIL line per gate: G-RULED (the BQ heading names the ruling's comment id, the
   ruled sentences stand verbatim, and every row reads RULED, "with a change" exactly for BQ-2,
   BQ-10 and BQ-11), G-BQ (the BQ ids are BQ-0 … BQ-15 and every "Built in" section exists), G-BOARDS (at
   most ten boards, twins at most a third, each PENDING or drawn with its id, PNG and own gate, none drawing
   the chart canvas or E16-D05's role legs), G-VARIANT (each variant table has the nine rows in
   order; its W-n exist; its `color.*` tokens resolve in every theme; its announcement row carries
   a `max_rate`), G-MAP (the variant map uses CMP-026's enum at the base, E08-D04's states and the
   closed `reason` set; the coverage table maps every state to one variant), G-REASON (§12's enum
   and events), G-COPY (no banned word or internal cause in the deck; PROPOSED strings at most 80
   characters), G-TIMING (no bare number in §7's Value column), G-CONTRAST (the pairs and their
   bars), G-HEUR, G-WALK (at most ten items), G-OWNER (G-ledger owners are tickets or spec
   owners, never an agent), G-DRYRUN, G-UNMERGED, G-URL, G-UNTOUCHED (only this ticket's files,
   the one `14` line and the later boards differ from the merge base), G-POINTER (exactly one
   added `14` line, inside SCR-151), G-BUDGET (600 spec lines, 150 hand-off lines), G-MUTLIST.
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of both documents
   (each heading, table row by its lead cell and prose line, by heading path and occurrence, with a
   line-shape tag per region) in `e08_d10_ruled_pins.txt`. Anchored values are cut out of the
   pinned text (G-ANCHOR owns them). `--repin-ruled` is the only writer and refuses while a
   placeholder is unfilled. A pin finding in a region another gate already FAILs prints as NOTE.
5. **--self-test** applies every mutation (M-n) and pin probe (P-n) in memory with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names; the
   texts on disk are checked byte-identical afterwards (sha256). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e08_d10_empty_backfill_audit.py --check [--fill]
  python3 -I docs/design/_tools/e08_d10_empty_backfill_audit.py --self-test
  python3 -I docs/design/_tools/e08_d10_empty_backfill_audit.py --repin-ruled
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
BASE = "fef3148c5"  # origin/main when the spec was written; every cite is read here

SPEC_REL = "docs/design/E08/E08-D10.md"
HAND_REL = "docs/design/E08/E08-D10-handoff.md"
TOOL_REL = "docs/design/_tools/e08_d10_empty_backfill_audit.py"
PIN_REL = "docs/design/_tools/e08_d10_ruled_pins.txt"
CAT_REL = "docs/plan/14-screens-catalogue.md"
OWN = (SPEC_REL, HAND_REL, TOOL_REL, PIN_REL, CAT_REL)
# the boards' later paths: the PNGs, a sheet kit and its manifest lines, an ignore entry
OWN_BOARDS = re.compile(
    r"docs/design/E08/img/E08-D10-\d\d-[a-z0-9-]+\.png|\.prettierignore"
    r"|docs/design/_tools/sheets/(?:e08-d10/[A-Za-z0-9._/-]+|MANIFEST\.sha256)"
)
DRAWN_CELL = re.compile(
    r"drawn: board id `[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}`, "
    r"`docs/design/E08/img/E08-D10-(?P<nn>\d\d)-[a-z0-9-]+\.png` \(\d+ × \d+\), "
    r"\d+ frames?, [\d,]+ shapes / [\d,]+ text nodes; (?P<gate>dark|light|high-contrast) gate PASS "
    r"\((?:own [\d,]+ px, other [\d,]+ px|hc primary [\d,]+ px, light [\d,]+ px)\)"
)
# a drawn cell's gate is its row's theme
GATE_OF = {"dark": "dark", "light": "light", "hc": "high-contrast"}
PENDING_CELL = "PENDING — drawn later in this PR"
POINTER_HEAD = "- **Hi-fi, the E08 variants (E08-D10, #178):**"
SPEC_BUDGET = 600
HAND_BUDGET = 150

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "13": "docs/plan/13-user-flows.md",
    "14": CAT_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
}
CITE_FILES = {
    "D02E12": "docs/design/E12/E12-D02.md",
    "D07E12": "docs/design/E12/E12-D07.md",
    "D04E11": "docs/design/E11/E11-D04.md",
    "D09E09": "docs/design/E09/E09-D09.md",
    "D03E22": "docs/design/E22/E22-D03.md",
    "E16D5": "docs/design/E16/E16-D05.md",
    "E16D6": "docs/design/E16/E16-D06.md",
    "D02": "docs/design/E08/E08-D02.md",
    "D04": "docs/design/E08/E08-D04.md",
    "D05": "docs/design/E08/E08-D05.md",
    "D09": "docs/design/E08/E08-D09.md",
    "D11": "docs/design/E08/E08-D11.md",
    "D12": "docs/design/E08/E08-D12.md",
    "D13": "docs/design/E08/E08-D13.md",
    "KC": "services/api/candleviewer/ingestion/kline_coverage.py",
    "E08J": "docs/plan/backlog/E08.json",
}
UNMERGED_PATHS = ("E08-D14.md",)
DS_SRC_REL = "packages/ui/tokens"
THEMES: dict[str, tuple[str, ...]] = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}

BQ_LIST_ID = "6552539904"
RULING_ID = "6552807966"
PENDING_HEAD = f"## The questions BQ-0 … BQ-15 — RULED (orchestrator, comment {RULING_ID})"
PENDING_STATUS = "RULED as the default"
CHANGED_STATUS = "RULED with a change"
CHANGED_BQ = ("BQ-2", "BQ-10", "BQ-11")
# The ruled sentences of comment 6552807966, bold marks dropped (G-RULED checks them verbatim).
RULED: tuple[str, ...] = (
    (
        "Twelve as the defaults (incl. BQ-0: the standing rules, one PR, the branch deviation noted). Three change, each checked against the cited merged text by an independent pre-screen:"
    ),
    (
        "BQ-2 — themes: E16-D05 board 10 (`E16-D05.md:67`) light-twins only `SCR-151/sentence-form`, so it does not meet the DoD's \"all variants in both themes\" for the other SCR-151 frames. Do not claim it does: record the text-only exception for the remaining light variants explicitly in the status block + the PR body (the ruled-exception form), cite E16-D05's drawn states and never redraw them (your default), and list the light variants not drawn as C rows to the next boards touch."
    ),
    (
        "BQ-10 — reason key: `no_filter_matches` duplicates the merged `empty_state_shown` reason `no_matches` (`E08-D05.md:441`) — reuse `no_matches`; no new key."
    ),
    (
        "BQ-11 — the backfill note's hold: a ≥ 1 s hold after fetch-complete contradicts merged D11 M22 (`E08-D11.md:140`: \"the content replaces it as a cut\", `instant`; `14`:753). Keep only the 600 ms constant as merged; if you believe the hold is needed, route it as a C row to D11's owner — do not state it in this pack."
    ),
    (
        "Cite fix: `22`:4232 is Bybit `confirm` text — the DataMeta block is `22`:18053–18081. Build on these."
    ),
)
BQ_IDS = tuple(f"BQ-{n}" for n in range(16))
PROP: dict[str, str] = {}  # none since BQ-11's ruling: the merged cut, no minimum display

TICKET_VARIANTS = (
    "`backfill-in-progress`",
    "`backfill-throttled`",
    "`recording-not-started`",
    "`coverage-gap`",
    "`nothing-created-yet`",
    "`no-filter-matches`",
    "(role-restricted)",
)
REASONS = ("nothing_created", "no_matches", "not_recorded", "role_restricted")
EVENTS = ("history.backfill_started", "history.backfill_throttled", "history.backfill_finished")
VARIANT_SECTIONS = ("## 3.", "## 4.", "### 5.1", "## 6.")
VARIANT_ROWS = (
    "Surface",
    "Trigger",
    "Copy",
    "Tokens",
    "Roles",
    "Keyboard and focus",
    "Announcement",
    "Analytics",
    "Data-confidence marker",
)
BANNED = re.compile(
    r"\bNo data\b|\berror\b|unfortunately|\bsorry\b|\b100\d\d\b|rate.?limit|\bHTTP\b|/v5|"
    r"endpoint|remaining|\bpage \d|%",
    re.IGNORECASE,
)
PROPOSED_MAX = 80
AGENT_RE = re.compile(r"worker|orchestrator|\bagent\b|anvil|claude|codex|lane\b", re.IGNORECASE)
OWNER_OK_RE = re.compile(r"\bE\d\d-[A-Z]+\d\d\b|\bowner|\bepic E\d\d \(#\d+\)")
URL_RE = re.compile(
    r"https?://|www\.|/home/|localhost|\.local\b|\b[a-z0-9-]+\.(?:com|io|org|net)\b"
)
CONTRAST_PAIRS: dict[str, tuple[str, str, str]] = {
    "heading": ("color.text.primary", "color.surface.raised", "text"),
    "cause": ("color.text.secondary", "color.surface.raised", "text"),
    "bf-text": ("color.data-confidence.backfilling.text", "color.surface.raised", "text"),
    "bf-ind": ("color.data-confidence.backfilling.indicator", "color.surface.raised", "non-text"),
    "gap-text": ("color.data-confidence.gapped.text", "color.surface.raised", "text"),
    "gap-ind": ("color.data-confidence.gapped.indicator", "color.surface.raised", "non-text"),
    "fill-track": ("color.action.primary.default", "color.surface.hover", "non-text"),
    "fill-panel": ("color.action.primary.default", "color.surface.raised", "non-text"),
    "sep": ("color.text.secondary", "color.surface.hover", "text"),
    "chip": ("color.text.primary", "color.status.info.subtle", "text"),
    "ring": ("color.focus.ring", "color.surface.raised", "non-text"),
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
    return git("show", f"{BASE}:{rel}")


@functools.lru_cache(maxsize=64)
def base_lines(rel: str) -> tuple[str, ...]:
    return tuple(at_base(rel).split("\n"))


def fork_point() -> str:
    return git("merge-base", "HEAD", "origin/main").strip()


def changed_paths() -> tuple[str, ...]:
    # compared with the merge base on origin/main, so only this PR's own diff counts
    tracked = git("diff", "--name-only", fork_point()).split()
    untracked = git("ls-files", "--others", "--exclude-standard").split()
    return tuple(sorted(set(tracked) | set(untracked)))


def pointer_diff() -> tuple[tuple[str, ...], int, str]:
    """The lines this PR adds to `14`, the count it removes, and the section of the first add."""
    diff = git("diff", "-U0", fork_point(), "--", CAT_REL).split("\n")
    added = tuple(ln[1:] for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))
    section_name = ""
    if added:
        lines = (ROOT / CAT_REL).read_text(encoding="utf-8").split("\n")
        if added[0] in lines:
            for ln in reversed(lines[: lines.index(added[0])]):
                if ln.startswith("### "):
                    section_name = ln
                    break
    return added, removed, section_name


# ---------------------------------------------------------------------------- markdown model


@dataclass(frozen=True)
class Texts:
    spec: str
    hand: str
    changed: tuple[str, ...]
    ptr: tuple[str, ...]
    ptr_removed: int
    ptr_section: str

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


def own_table(text: str, prefix: str) -> list[list[str]]:
    """The first table before any sub-heading of the section."""
    start, end, _ = section(text, prefix)
    lines = text.split("\n")[start:end]
    cut = next((i for i, ln in enumerate(lines) if ln.startswith("#")), len(lines))
    rows = [cells(ln) for ln in lines[:cut] if ln.strip().startswith("|") and not is_rule_row(ln)]
    return rows


def plain(cell: str) -> str:
    return cell.replace("`", "").strip()


def body_text(text: str, prefix: str) -> str:
    s, e, _ = section(text, prefix)
    return "\n".join(text.split("\n")[s:e])


# ---------------------------------------------------------------------------- anchors

ANCHOR_RE = re.compile(r"(?<![0-9A-Za-z.,])([0-9A-Za-z.,]+)<!--=([A-Z]+):([a-z0-9.\-]+)-->")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z]+):([a-z0-9.\-]+)\}\}")


def cut_anchors(text: str) -> str:
    return ANCHOR_RE.sub(lambda m: f"<!--={m.group(2)}:{m.group(3)}-->", text)


# ---------------------------------------------------------------------------- base facts


@functools.lru_cache(maxsize=1)
def cmp026_variants() -> frozenset[str]:
    line = base_lines(PLAN["15"])[312]
    m = re.search(r"`variant: ([^`]+)`", line)
    if not m:
        raise SystemExit("FAIL CMP-026's variant enum moved at the base (`15`:313)")
    return frozenset(re.findall(r'"([a-z-]+)"', m.group(1)))


@functools.lru_cache(maxsize=1)
def d04_states() -> frozenset[str]:
    rows = base_lines(CITE_FILES["D04"])[40:48]
    out = {m.group(1) for r in rows if (m := re.match(r"^\| `([a-z]+)` \|", r))}
    if len(out) != 8:
        raise SystemExit("FAIL E08-D04's eight states moved at the base (D04:41-48)")
    return frozenset(out)


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


def resolve(theme: str, name: str) -> str | None:
    tokens = load_theme(theme)
    value: object = tokens.get(name)
    hops = 0
    while isinstance(value, str) and value.startswith("{") and value.endswith("}") and hops < 12:
        value, hops = tokens.get(value[1:-1]), hops + 1
    if isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return value.upper()
    return None


def hex_of(theme: str, name: str) -> str:
    value = resolve(theme, name)
    if value is None:
        raise SystemExit(f"FAIL token {name} ({theme}) does not resolve to an opaque colour")
    return value


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
    def grab(rel: str, n: int, pattern: str) -> str:
        m = re.search(pattern, base_lines(rel)[n - 1])
        if not m:
            raise SystemExit(f"FAIL {rel}:{n} no longer states {pattern!r} at the base")
        return m.group(1)

    return {
        "CITE:t.cache": grab(PLAN["11"], 850, r"≤(\d+) ms to first paint"),
        "CITE:t.slow": grab(PLAN["14"], 753, r"after (\d+) ms"),
        "CITE:t.hz": grab(CITE_FILES["D11"], 125, r"each ≤ (\d+) Hz"),
        "CITE:t.region": grab(CITE_FILES["D12"], 361, r"≤ 1 ambient announcement per (\d+) s"),
        "CITE:t.slowlabel": grab(PLAN["15"], 446, r"after (\d+) s\)"),
    }


def contrast_values() -> Values:
    out: Values = {}
    low = {"text": 99.0, "non-text": 99.0}
    for key, (fg, bg, role) in CONTRAST_PAIRS.items():
        for theme in THEMES:
            r = contrast(hex_of(theme, fg), hex_of(theme, bg))
            out[f"CONTRAST:{key}.{theme}"] = show_ratio(r)
            low[role] = min(low[role], r)
    out["CONTRAST:min.text"] = show_ratio(low["text"])
    out["CONTRAST:min.nontext"] = show_ratio(low["non-text"])
    return out


def needs_rows(hand: str) -> list[list[str]]:
    t = first_table(hand, "## §G")
    return t[1:] if t else []


def count_values(t: Texts) -> Values:
    spec, hand = t.spec, t.hand
    boards = first_table(spec, "## 0.")[1:]
    ev = tables(spec, "## 12.")
    out: Values = {
        "COUNT:boards": str(len(boards)),
        "COUNT:boards.twins": str(sum(1 for r in boards if len(r) > 3 and r[3] in ("light", "hc"))),
        "COUNT:variants": str(len(own_table(spec, "## 2.")[1:])),
        "COUNT:map": str(len(first_table(spec, "### 2.1")[1:])),
        "COUNT:copy": str(len(first_table(spec, "## 13.")[1:])),
        "COUNT:findings": str(len(first_table(spec, "## 14.")[1:])),
        "COUNT:reasons": str(len(ev[0][1:]) if ev else 0),
        "COUNT:events": str(len(ev[1][1:]) if len(ev) > 1 else 0),
        "COUNT:items": str(len(first_table(spec, "### 10.1")[1:])),
        "COUNT:announce": str(len(first_table(spec, "### 10.2")[1:])),
        "COUNT:arows": str(len(first_table(hand, "## §C")[1:])),
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
    return {**cite_values(), **PROP, **contrast_values(), **count_values(t)}


# ---------------------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    mid: str
    what: str
    gate: str
    doc: str  # "spec", "hand", "changed" or "ptr"
    where: str  # a heading prefix; "" = the whole document
    old: str
    new: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1",
        "mark board 01 drawn without its id or PNG",
        "G-BOARDS",
        "spec",
        "## 0.",
        "drawn: board id `e4de416d-a820-8072-8008-e095c001a84f`, "
        "`docs/design/E08/img/E08-D10-01-backfill-in-progress.png`",
        "drawn",
    ),
    Mutation(
        "M-2",
        "draw the redlines on the chart canvas",
        "G-BOARDS",
        "spec",
        "## 0.",
        "the tokens of §11 on boards 01–03",
        "the tokens of §11 on the chart canvas",
    ),
    Mutation(
        "M-3",
        "rename §3's Announcement row",
        "G-VARIANT",
        "spec",
        "## 3.",
        "| Announcement",
        "| Announce",
    ),
    Mutation(
        "M-4",
        "bind §4's Partial chip to an unshipped token",
        "G-VARIANT",
        "spec",
        "## 4.",
        "`color.status.info.subtle`",
        "`color.status.info.faint`",
    ),
    Mutation(
        "M-5",
        "map no-filter-matches to a CMP-026 value that does not exist",
        "G-MAP",
        "spec",
        "## 2.",
        "`filtered-empty`",
        "`filtered`",
    ),
    Mutation(
        "M-6",
        "rename `role_restricted` in §12's enum",
        "G-REASON",
        "spec",
        "## 12.",
        "| `role_restricted`",
        "| `restricted`",
    ),
    Mutation(
        "M-7",
        "name the rate limit in W-6",
        "G-COPY",
        "spec",
        "## 13.",
        "the exchange asked us to slow down",
        "the exchange rate limit hit us",
    ),
    Mutation(
        "M-8",
        "lengthen W-2 past 80 characters",
        "G-COPY",
        "spec",
        "## 13.",
        '"Older bars are on their way from the exchange."',
        '"Older bars are on their way from the exchange and appear here once they have arrived."',
    ),
    Mutation(
        "M-9",
        "point T-2's cite past the end of `14`",
        "G-CITE",
        "spec",
        "## 7.",
        "`14`:753",
        "`14`:99753",
    ),
    Mutation(
        "M-10",
        "re-word W-12",
        "G-QUOTE",
        "spec",
        "## 13.",
        '"Reconstructed after gap"',
        '"Reconstructed after a gap"',
    ),
    Mutation(
        "M-11",
        "re-word D10-A7's Old fragment",
        "G-AROW",
        "hand",
        "## §C",
        "| have no hi-fi text",
        "| has no hi-fi text",
    ),
    Mutation(
        "M-12",
        "mark a changed BQ pending after the ruling",
        "G-RULED",
        "spec",
        "## The questions",
        CHANGED_STATUS,
        "default built; ruling pending",
    ),
    Mutation(
        "M-13",
        "renumber BQ-15",
        "G-BQ",
        "spec",
        "## The questions",
        "| BQ-15 |",
        "| BQ-16 |",
    ),
    Mutation(
        "M-14",
        "drop `(heuristic)` from H-4",
        "G-HEUR",
        "spec",
        "## 14.",
        "(heuristic) Consistency",
        "Consistency",
    ),
    Mutation(
        "M-15",
        "add two walkthrough items in the hand-off's §E",
        "G-WALK",
        "hand",
        "## §E",
        "- [ ] Boards 08–09:",
        "- [ ] Extra one.\n- [ ] Extra two.\n- [ ] Boards 08–09:",
    ),
    Mutation(
        "M-16",
        "name an agent as D10-G1's owner",
        "G-OWNER",
        "spec",
        "### 17.2",
        "epic E08 (#35): no ticket names the live fetcher yet",
        "a worker agent",
    ),
    Mutation(
        "M-17",
        "link E08-D14's unmerged file in the start line",
        "G-UNMERGED",
        "spec",
        "",
        "E08-D14 (#277)",
        "docs/design/E08/E08-D14.md (#277)",
    ),
    Mutation(
        "M-18",
        "write a page URL beside the Penpot page in §0",
        "G-URL",
        "spec",
        "## 0.",
        "cited by name and page id only",
        "cited by name and page id only (https://penpot.example.org/p)",
    ),
    Mutation(
        "M-19",
        "change the boards count in the header",
        "G-ANCHOR",
        "spec",
        "",
        "9<!--=COUNT:boards-->",
        "10<!--=COUNT:boards-->",
    ),
    Mutation(
        "M-20", "pad the spec past its line budget", "G-BUDGET", "spec", "<eof>", "", "\n" * 300
    ),
    Mutation(
        "M-21", "touch `22` in the working tree", "G-UNTOUCHED", "changed", "", "", PLAN["22"]
    ),
    Mutation(
        "M-22",
        "leave a placeholder unfilled",
        "G-MARKER",
        "spec",
        "",
        "9<!--=COUNT:boards-->",
        "{{COUNT:boards}}",
    ),
    Mutation(
        "M-23",
        "bind the focus ring to `color.text.tertiary`",
        "G-CONTRAST",
        "spec",
        "## 11.",
        "`color.focus.ring`",
        "`color.text.tertiary`",
    ),
    Mutation(
        "M-24",
        "rename the first dry-run role in the hand-off",
        "G-DRYRUN",
        "hand",
        "## §G",
        "story: E16-S05 (#487)",
        "story: E16-S04 (#486)",
    ),
    Mutation(
        "M-25",
        "replace a mutation row's gate in §16",
        "G-MUTLIST",
        "spec",
        "## 16.",
        "| G-WALK",
        "| G-WALKS",
    ),
    Mutation(
        "M-26",
        "add a second line to `14`",
        "G-POINTER",
        "ptr",
        "",
        "",
        "- **Hi-fi (E08-D10):** a second pointer.",
    ),
    Mutation(
        "M-27",
        "write T-4's rate as a bare number",
        "G-TIMING",
        "spec",
        "## 7.",
        "1<!--=CITE:t.hz-->",
        "2",
    ),
    Mutation(
        "M-28",
        "drop 'no new key' from the BQ-10 ruled sentence",
        "G-RULED",
        "spec",
        "## The questions",
        "`no_matches`; no new key.",
        "`no_matches`.",
    ),
)
PROBES: tuple[Mutation, ...] = (
    Mutation(
        "P-1",
        "flip a prose sentence in §4",
        "G-RULED-PIN",
        "spec",
        "## 4.",
        "No manual retry exists while the client backs off",
        "A manual retry exists while the client backs off",
    ),
    Mutation(
        "P-2",
        "re-word a hand-off summary item",
        "G-RULED-PIN",
        "hand",
        "## §I",
        "never merged, never emptying the panel",
        "merged, never emptying the panel",
    ),
)


def mutation_rows() -> str:
    head = "| M | Mutation | Gate |\n| --- | --- | --- |\n"
    return head + "\n".join(f"| {m.mid} | {m.what} | {m.gate} |" for m in MUTATIONS)


def apply_mutation(t: Texts, m: Mutation) -> Texts:
    if m.doc == "changed":
        return replace(t, changed=(*t.changed, m.new))
    if m.doc == "ptr":
        return replace(t, ptr=(*t.ptr, m.new))
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
    r"(?:`(\d\d)`|\b(" + "|".join(sorted(CITE_FILES, key=len, reverse=True)) + r"))"
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
            if line in RULED:  # the ruling's own cites, read at the list's base (spec, BQ section)
                continue
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


def copy_rows(spec: str) -> list[list[str]]:
    return [r for r in first_table(spec, "## 13.")[1:] if len(r) >= 5]


def g_quote(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.spec, "## 13.")
    for row in copy_rows(t.spec):
        if not row[4].startswith("verbatim"):
            continue
        s = row[2].strip().strip('"')
        if s not in cited_text(row[3]):
            out.append(("G-QUOTE", f"{row[0]} is not verbatim on {row[3]}", "spec", region))
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


def bq_rows(spec: str) -> list[list[str]]:
    return first_table(spec, "## The questions")[1:]


def g_ruled(t: Texts) -> list[Finding]:
    s, _, region = section(t.spec, "## The questions")
    out: list[Finding] = []
    head = t.spec.split("\n")[s - 1] if s else ""
    if head != PENDING_HEAD:
        out.append(("G-RULED", "the BQ heading does not name the ruling", "spec", region))
    body = body_text(t.spec, "## The questions").split("\n")
    for k, para in enumerate(RULED, 1):
        if para not in body:
            out.append(("G-RULED", f"ruled sentence {k} is not verbatim", "spec", region))
    for r in bq_rows(t.spec):
        want = CHANGED_STATUS if r[0] in CHANGED_BQ else PENDING_STATUS
        if len(r) < 4 or r[3] != want:
            out.append(("G-RULED", f"{r[0]} does not read '{want}'", "spec", region))
    return out


def g_bq(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## The questions")
    rows = bq_rows(t.spec)
    bad: list[str] = []
    ids = tuple(r[0] for r in rows)
    if ids != BQ_IDS:
        bad.append(f"the BQ ids read {ids}")
    heads = {m.group(1) for m in re.finditer(r"^#{2,3} (\d+(?:\.\d+)?)\.? ", t.spec, re.MULTILINE)}
    for r in rows:
        for ref in re.findall(r"§(\d+(?:\.\d+)?)", r[2] if len(r) > 2 else ""):
            if ref not in heads:
                bad.append(f"{r[0]} is built in §{ref}, which does not exist")
    return [("G-BQ", b, "spec", region) for b in bad]


def g_boards(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 0.")
    rows = first_table(t.spec, "## 0.")[1:]
    bad: list[str] = []
    if not 1 <= len(rows) <= 10:
        bad.append(f"{len(rows)} boards")
    twins = [r for r in rows if len(r) > 3 and r[3] in ("light", "hc")]
    if 3 * len(twins) > len(rows):
        bad.append(f"{len(twins)} twins of {len(rows)} boards")
    for r in rows:
        if len(r) < 5 or r[3] not in ("dark", "light", "hc"):
            bad.append(f"board {r[0]} has no theme")
            continue
        drawn = DRAWN_CELL.fullmatch(r[4])
        if r[4] != PENDING_CELL and not drawn:
            bad.append(f"board {r[0]} is neither PENDING nor drawn with its id and PNG")
        elif drawn and (drawn["nn"] != r[0] or drawn["gate"] != GATE_OF[r[3]]):
            bad.append(f"board {r[0]}'s drawn cell names another board's PNG or theme's gate")
        if re.search(r"canvas|view-as|sentence-form", r[2]):
            bad.append(f"board {r[0]} draws a cited-only frame")
    if "**Not drawn — the text is binding**" not in body_text(t.spec, "## 0."):
        bad.append("no 'not drawn — the text is binding' paragraph")
    return [("G-BOARDS", b, "spec", region) for b in bad]


def copy_ids(spec: str) -> set[str]:
    return {r[0] for r in copy_rows(spec)}


def g_variant(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    ws = copy_ids(t.spec)
    for prefix in VARIANT_SECTIONS:
        _, _, region = section(t.spec, prefix)
        table = own_table(t.spec, prefix)
        bad: list[str] = []
        leads = tuple(r[0] for r in table[1:])
        if leads != VARIANT_ROWS:
            bad.append(f"rows read {leads}")
        if table and len(table[0]) < 3:
            bad.append("fewer than two forms")
        for r in table[1:]:
            text = " ".join(r[1:])
            for w in re.findall(r"\bW-\d+\b", text):
                if w not in ws:
                    bad.append(f"{w} is not in the copy deck")
            if r[0] == "Tokens":
                for tok in re.findall(r"`(color\.[a-z0-9.\-]+)`", text):
                    if any(resolve(th, tok) is None for th in THEMES):
                        bad.append(f"token {tok} does not resolve")
            if r[0] == "Announcement" and not re.search(r"`max_rate` (?:≤ \d+ per \d+ s|0)", r[1]):
                bad.append("the announcement row has no numeric `max_rate`")
        out += [("G-VARIANT", f"{prefix} {b}", "spec", region) for b in bad]
    return out


def g_map(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 2.")
    rows = own_table(t.spec, "## 2.")[1:]
    bad: list[str] = []
    if tuple(r[0] for r in rows) != TICKET_VARIANTS:
        bad.append("the ticket variants differ")
    enum, states = cmp026_variants(), d04_states()
    for r in rows:
        if len(r) < 6:
            bad.append(f"{r[0]} has {len(r)} cells")
            continue
        v = re.match(r"`([a-z-]+)`", r[1])
        if r[1] != "—" and (not v or v.group(1) not in enum):
            bad.append(f"{r[0]}: {r[1]} is not a CMP-026 variant")
        if r[2] != "—" and plain(r[2]) not in states:
            bad.append(f"{r[0]}: {r[2]} is not an E08-D04 state")
        if r[4] != "—" and plain(r[4]) not in REASONS:
            bad.append(f"{r[0]}: {r[4]} is not a reason")
    names = {plain(x) for x in TICKET_VARIANTS}
    for r in first_table(t.spec, "### 2.1")[1:]:
        hits = [n for n in re.findall(r"`([a-z-]+)`", r[-1]) if n in names]
        if len(hits) != 1 and not r[-1].startswith("none"):
            bad.append(f"coverage state {r[0]!r} maps to {len(hits)} variants")
    return [("G-MAP", b, "spec", region) for b in bad]


def g_reason(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 12.")
    ts = tables(t.spec, "## 12.")
    bad: list[str] = []
    reasons = tuple(plain(r[0]) for r in ts[0][1:]) if ts else ()
    events = tuple(plain(r[0]) for r in ts[1][1:]) if len(ts) > 1 else ()
    if reasons != REASONS:
        bad.append(f"the reason enum reads {reasons}")
    if events != EVENTS:
        bad.append(f"the events read {events}")
    return [("G-REASON", b, "spec", region) for b in bad]


def g_copy(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 13.")
    bad: list[str] = []
    rows = copy_rows(t.spec)
    if tuple(r[0] for r in rows) != tuple(f"W-{n}" for n in range(1, len(rows) + 1)):
        bad.append("the W ids are not consecutive")
    for r in rows:
        s = r[2].strip().strip('"')
        if BANNED.search(s):
            bad.append(f"{r[0]} carries a banned word or an internal cause")
        if r[4].startswith("PROPOSED") and len(s) > PROPOSED_MAX:
            bad.append(f"{r[0]} is {len(s)} characters")
    return [("G-COPY", b, "spec", region) for b in bad]


def g_timing(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 7.")
    rows = first_table(t.spec, "## 7.")[1:]
    bad: list[str] = []
    if tuple(r[0] for r in rows) != tuple(f"T-{n}" for n in range(1, len(rows) + 1)) or not rows:
        bad.append("the T ids are not consecutive")
    for r in rows:
        if len(r) < 3:
            continue
        if re.search(r"\d", ANCHOR_RE.sub("", r[2])):
            bad.append(f"{r[0]}'s value carries a bare number")
    return [("G-TIMING", b, "spec", region) for b in bad]


def g_contrast(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.spec, "## 11.")
    rows = first_table(t.spec, "## 11.")[1:]
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
    _, _, region = section(t.spec, "## 14.")
    return [
        ("G-HEUR", f"{r[0]} lacks (heuristic)", "spec", region)
        for r in first_table(t.spec, "## 14.")[1:]
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
    extra = [p for p in t.changed if p not in OWN and not OWN_BOARDS.fullmatch(p)]
    return [("G-UNTOUCHED", f"{p} differs from the base", "", "") for p in extra]


def g_pointer(t: Texts) -> list[Finding]:
    bad: list[str] = []
    if len(t.ptr) != 1 or t.ptr_removed:
        bad.append(f"`14` gains {len(t.ptr)} line(s) and loses {t.ptr_removed}")
    elif not t.ptr[0].startswith(POINTER_HEAD) or "E08-D10.md" not in t.ptr[0]:
        bad.append("the `14` line is not the E08-D10 pointer")
    elif not t.ptr_section.startswith("### SCR-151 "):
        bad.append(f"the pointer sits under {t.ptr_section!r}")
    return [("G-POINTER", b, "", "") for b in bad]


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
    if PLACEHOLDER_RE.search(t.spec + t.hand) or "{{MUTATIONS}}" in t.spec:
        print("FAIL --repin-ruled refuses while a placeholder is unfilled")
        return 1
    rows = all_units(t)
    head = (
        "# E08-D10 pins (every unit of the spec and the hand-off): doc, region (heading path"
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
    out += g_ruled(t) + g_bq(t) + g_boards(t) + g_variant(t) + g_map(t) + g_reason(t)
    out += g_copy(t) + g_timing(t) + g_contrast(t) + g_heur(t) + g_walk(t) + g_owner(t)
    out += g_dryrun(t)
    out += g_lines(t, "G-UNMERGED", lambda ln: any(p in ln for p in UNMERGED_PATHS), "a path")
    out += g_lines(t, "G-URL", lambda ln: bool(URL_RE.search(ln)), "a URL, host or local path")
    out += g_untouched(t) + g_pointer(t) + g_budget(t) + g_mutlist(t) + g_pins(t)
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
    ptr, removed, sect = pointer_diff()
    return Texts(
        spec=(ROOT / SPEC_REL).read_text(encoding="utf-8"),
        hand=(ROOT / HAND_REL).read_text(encoding="utf-8"),
        changed=changed_paths(),
        ptr=ptr,
        ptr_removed=removed,
        ptr_section=sect,
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
