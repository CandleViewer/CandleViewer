#!/usr/bin/env python3
"""E47-D09 (#1308) audit: keyboard operability (the drag equivalents, SCR-012 / SCR-013, SCR-113).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at pinned commits (`git show`): the plan texts and merged design texts the spec cites at the
base, E47-D04 at its PR head, the SCR-012 host files at their PR head, `14` at the base, the keymap
registry and the E47-D02 register; and, from the working tree, the spec
`docs/design/E47/E47-D09.md`, its hand-off, the `05` section this PR edits and the pins file. Its
form follows the E47-D04 tool (the same modes, anchored values, default-deny pins and mutations).

1. **Values.** Every `{{KIND:key}}` placeholder is written by `--fill` as `VALUE<!--=KIND:key-->`:
   COUNT (rows of the spec's and the hand-off's own tables, the `14` lines that name a drag or a
   hover, the registry's commands and pointer chords). `--check` re-derives each anchored value
   (G-ANCHOR) and FAILs a placeholder left behind or a stray HTML comment (G-MARKER). `--fill`
   also writes the mutation rows ({{MUTATIONS}}) from this file's constants.
2. **Cites.** Every `NN`:line and KEY:line cite of both documents resolves to a non-blank line at
   its pinned commit (G-CITE); every "verbatim" copy string occurs on its cited line (G-QUOTE);
   every Old fragment of the hand-off's A-rows occurs verbatim on its cited line (G-AROW).
3. **Gates.** One FAIL line per gate: G-RULED (the heading names the ruling 6566806943 and the
   list 6566521186; the ruling's sentence verbatim, bold dropped), G-PENDING (BQ-0 ... BQ-15 once
   each, the nine the ruling pins "ruled as the default, pinned", the other seven "ruled as the
   default"), G-BOARDS (at most ten
   boards, twins at most a third, each pending or drawn with its id and PNG, the not-drawn
   paragraph), G-GRAMMAR (the four phases; every census row states select, adjust with a unit or
   "none:", commit and cancel; every unit row filled), G-CENSUS (every `14` line naming a drag or a
   hover maps to a census row or to the exempt list, never both, and nothing else is mapped),
   G-CHORD (every registry pointer chord is named by id in the census), G-ORDER (in the order-line
   table only `Enter` sends, and it names US-SET-003; `Esc` sends nothing), G-COALESCE (the three
   D5 parameters in §6 equal E06-D03's line), G-PALETTE (K-8 in §8; QA-1 enumerates the registry),
   G-FINDINGS (the rows equal the register's E47-D09 rows, each with a disposition), G-T2 (the T2
   paragraph names its parts; §3, §4 and §8 cite it; the hand-off lists CMP-079 and CMP-019),
   G-NORM (`05` §3.5 carries every K-n of §1.4 and points here; `05`:36 and `05`:88 fixed; §3.2
   byte-identical to the base), G-HEUR, G-WALK (at most ten items), G-OWNER (G-ledger owners are
   tickets, never an agent), G-UNMERGED, G-URL, G-UNTOUCHED (only this ticket's files, `05` and the
   boards differ from the merge base with origin/main), G-BUDGET, G-MUTLIST.
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of both documents
   (each heading, table row by its lead cell and prose line, by heading path and occurrence, with
   a line-shape tag per region) in `e47_d09_ruled_pins.txt`. Anchored values are cut out of the
   pinned text (G-ANCHOR owns them). `--repin-ruled` is the only writer and refuses while a
   placeholder is unfilled. A pin finding in a region another gate already FAILs prints as NOTE.
5. **--self-test** applies every mutation (M-n) and pin probe (P-n) in memory with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names; the
   texts on disk are checked byte-identical afterwards (sha256). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e47_d09_keyboard_audit.py --check [--fill]
  python3 -I docs/design/_tools/e47_d09_keyboard_audit.py --self-test
  python3 -I docs/design/_tools/e47_d09_keyboard_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "4c662fd5b"  # origin/main of the BQ list; every cite is read here unless pinned below
D04_PIN = "1ff5d8cb9"  # E47-D04, PR #5387 head; re-pinned at merge
PAL_PIN = "73bfdb08a"  # E10-S05, PR #5280 head (the SCR-012 host as built there)

SPEC_REL = "docs/design/E47/E47-D09.md"
HAND_REL = "docs/design/E47/E47-D09-handoff.md"
TOOL_REL = "docs/design/_tools/e47_d09_keyboard_audit.py"
PIN_REL = "docs/design/_tools/e47_d09_ruled_pins.txt"
NORM_REL = "docs/plan/05-accessibility-standard.md"  # §3.5 and three lines are edited (BQ-12)
OWN = (SPEC_REL, HAND_REL, TOOL_REL, PIN_REL, NORM_REL)
OWN_BOARDS = re.compile(r"docs/design/E47/img/E47-D09-\d\d-[a-z0-9-]+\.png")
DRAWN_CELL = re.compile(
    r"drawn: board id `[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}`, "
    r"`docs/design/E47/img/E47-D09-(?P<nn>\d\d)-(?P<slug>[a-z0-9-]+)\.png` \(\d+ × \d+\)"
)
PENDING_CELL = "pending: drawn later in this PR"
SPEC_BUDGET = 450
HAND_BUDGET = 160

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
}
KEYMAP = "apps/web/src/keymap"
PALETTE = "apps/web/src/features/command-palette"
CITE_FILES = {
    "D04H": "docs/design/E47/E47-D04-handoff.md",
    "D04": "docs/design/E47/E47-D04.md",
    "D03E06": "docs/design/E06/E06-D03.md",
    "D07E11": "docs/design/E11/E11-D07.md",
    "D02E14": "docs/design/E14/E14-D02.md",
    "D10E14": "docs/design/E14/E14-D10.md",
    "D15": "docs/design/E15/E15-D15.md",
    "D05E32": "docs/design/E32/E32-D05.md",
    "D02E37": "docs/design/E37/E37-D02.md",
    "D03E10": "docs/design/E10/E10-D03.md",
    "D09E09": "docs/design/E09/E09-D09.md",
    "D12E08": "docs/design/E08/E08-D12.md",
    "CAT": "docs/plan/a11y/47-audit-catalogue.md",
    "E47J": "docs/plan/backlog/E47.json",
    "KMAP": f"{KEYMAP}/keymap.json",
    "DISP": f"{KEYMAP}/dispatcher.ts",
    "HOST": f"{KEYMAP}/KeymapHost.tsx",
    "VAL": f"{KEYMAP}/validate.ts",
    "RES": f"{KEYMAP}/reserved-keys.json",
    "CHS": f"{KEYMAP}/Cheatsheet.tsx",
    "ANA": f"{KEYMAP}/analytics.ts",
    "HKE": f"{KEYMAP}/HotkeyEditor.tsx",
    "PSRC": f"{PALETTE}/sources.ts",
    "PCOPY": f"{PALETTE}/copy.ts",
    "PEV": f"{PALETTE}/paletteEvents.ts",
}
REGISTER_REL = "docs/plan/a11y/47-audit-register.json"
FILE_BASE = {
    CITE_FILES["D04"]: D04_PIN,
    CITE_FILES["D04H"]: D04_PIN,
    CITE_FILES["PSRC"]: PAL_PIN,
    CITE_FILES["PCOPY"]: PAL_PIN,
    CITE_FILES["PEV"]: PAL_PIN,
}
UNMERGED_PATHS = (
    *(f"E47-D{n:02d}.md" for n in (1, 3, 5, 6, 7, 8, 10, 11)),
    "E31-D01.md",
    "E37-D04.md",
)

RULING_ID = "6566806943"  # the rulings of record on #1308 (2026-11-02 01:20Z)
BQ_LIST_ID = "6566521186"  # the BQ list on #1308
BQ_DEFAULT = "ruled as the default"
BQ_PINNED = "ruled as the default, pinned (the ruled sentence above)"
BQ_IDS = tuple(f"BQ-{n}" for n in range(16))
BQ_PINNED_IDS = tuple(f"BQ-{n}" for n in (2, 3, 5, 6, 7, 8, 9, 10, 11))
# The ruling of record, its bold marks dropped (one paragraph).
RULED = (
    "Rulings of record — E47-D09 (#1308) BQ-0..BQ-11 (orchestrator, 01:20Z 2026-11-02, under "
    "the owner's 2026-10-29 delegation): all ORCH-defaults as proposed (6566521186). Pins: "
    "BQ-2 — the shipped key wins where it shipped; `?` is a PROPOSED alias A-row (scoped, "
    "remappable); the seven-row drift is a C-row table, no §3.2 cell edits. BQ-3 — the "
    "K-rules stated once (unit, `Shift` ×10, `PageUp` / `PageDown` ×100, `Enter` commits, "
    "`Esc` restores, the pending value shown and spoken); merged twins mapped as instances, "
    "divergences C-rows, KB-14 stands. BQ-5 — the order line: arrows move a pending price "
    "that sends nothing; `Enter` commits through the drop's own path (SCR-040's confirm "
    "choice, US-SET-003's policy, the wrong-side refusal); stops tighten only; never one "
    "amend per keypress; Live never weaker than Demo — handed to E31-D01 as PROPOSED. BQ-6 — "
    "adopt E06-D03 D6 / D5 by cite; the `05` :36 cite is fixed in this PR as D04's ruling "
    "fixed :63. BQ-7 — D5's three parameters for every adjustment, one polite region, state "
    "updated once per frame. BQ-8 — E37-D02 §13 by cite + node Move mode only; keys as A-rows "
    "for E37-S05. BQ-9 — E09-D09 governs (T2 writes, admin absent); every registry command "
    'listed, "unbound" as the word; A-rows to E10-S05. BQ-10 — deltas on E10-D03\'s chassis '
    "only; the grouping C-row. BQ-11 — keep the shipped inert-binding mechanism; the PROPOSED "
    "copy as an A-row. `Refs #1308` + `Partial:` until #5387 merges, then the closing keyword for this ticket goes in the boards PR."
)

PHASES = ("Select", "Adjust", "Commit", "Cancel")
DRAG_HOVER_RE = re.compile(r"\b(?:drag|hover)", re.IGNORECASE)
CHORD_RE = re.compile(r"drag|click|wheel", re.IGNORECASE)
UNIT_RE = re.compile(r"\b(?:tick|bar|level|step|position|zone|port)s?\b|\d %|^none: ")
D5_PARAMS = (
    ("`leadDelay` 0 ms", "`leadDelay` = 0 ms"),
    ("`repeatWindow` 500 ms", "`repeatWindow` = 500 ms"),
    ("`trailingFlush` ≤ 250 ms", "`trailingFlush` ≤ 250 ms"),
)
T2_PARA = "**The T2 paragraph (G-T2;"
T2_NAMES = (
    "CMP-079 RbacGate",
    "CMP-019 Icon `lock`",
    "rendering 2a",
    "in the DOM at mount",
    "one polite announcement",
    "CMP-041 menu",
)
AGENT_RE = re.compile(r"worker|orchestrator|\bagent\b|anvil|claude|codex|lane\b", re.IGNORECASE)
OWNER_OK_RE = re.compile(r"\bE\d\d-[A-Z]+\d\d\b|\bowner")
URL_RE = re.compile(
    r"https?://|www\.|/home/|localhost|\.local\b|\b[a-z0-9-]+\.(?:com|io|org|net)\b"
)

Finding = tuple[str, str, str, str]  # gate, message, doc, region
Values = dict[str, str]


# ---------------------------------------------------------------------------- git and files


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, encoding="utf-8", check=True
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


# ---------------------------------------------------------------------------- anchors

ANCHOR_RE = re.compile(
    r"(?<![0-9A-Za-z.,])([0-9A-Za-z.,]+)<!--=([A-Z]+):([a-z0-9.\-]+)-->", re.DOTALL
)
ANCHOR_TAG_RE = re.compile(r"<!--=[A-Z]+:[a-z0-9.\-]+-->", re.DOTALL)
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z]+):([a-z0-9.\-]+)\}\}")


def cut_anchors(text: str) -> str:
    return ANCHOR_RE.sub(lambda m: f"<!--={m.group(2)}:{m.group(3)}-->", text)


# ---------------------------------------------------------------------------- sources


@functools.lru_cache(maxsize=1)
def keymap_commands() -> tuple[tuple[str, str], ...]:
    data = json.loads(at_base(CITE_FILES["KMAP"]))
    cmds = data.get("commands") if isinstance(data, dict) else None
    if not isinstance(cmds, list):
        raise SystemExit("FAIL the keymap has no command list")
    return tuple(
        (str(c.get("id")), str(c.get("defaultBinding", ""))) for c in cmds if isinstance(c, dict)
    )


def chord_ids() -> list[str]:
    return [cid for cid, binding in keymap_commands() if CHORD_RE.search(binding)]


@functools.lru_cache(maxsize=1)
def drag_hover_lines() -> tuple[int, ...]:
    lines = base_lines(PLAN["14"])
    return tuple(i + 1 for i, ln in enumerate(lines) if DRAG_HOVER_RE.search(ln))


def register_findings() -> list[dict[str, object]]:
    data = json.loads(at_base(REGISTER_REL))
    fs = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(fs, list):
        return []
    return [f for f in fs if isinstance(f, dict) and f.get("designOwner") == "E47-D09"]


def census_rows(spec: str) -> list[list[str]]:
    return [r for r in first_table(spec, "## 3.")[1:] if r and r[0].startswith("DE-")]


def line_numbers(cell: str) -> list[int]:
    return [int(n) for n in re.findall(r":(\d+)", cell)]


def exempt_numbers(spec: str) -> list[int]:
    paras = [ln for ln in body(spec, "## 3.") if ln.startswith("**Exempt (not an interaction)**")]
    return [int(n) for p in paras for n in re.findall(r"`14`:(\d+)", p)]


def count_values(t: Texts) -> Values:
    spec, hand = t.spec, t.hand
    boards = first_table(spec, "## 0.")[1:]
    return {
        "COUNT:boards": str(len(boards)),
        "COUNT:boards.twins": str(sum(1 for r in boards if len(r) > 3 and r[3] in ("light", "hc"))),
        "COUNT:census": str(len(census_rows(spec))),
        "COUNT:census.lines": str(len(drag_hover_lines())),
        "COUNT:chords": str(len(chord_ids())),
        "COUNT:registry": str(len(keymap_commands())),
        "COUNT:palette": str(sum(1 for cid, _ in keymap_commands() if cid != "global.palette")),
        "COUNT:walkthrough": str(sum(1 for ln in body(hand, "## §E") if ln.startswith("- ["))),
    }


def compute_values(t: Texts) -> Values:
    return count_values(t)


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
        "| dark | pending: drawn later in this PR |",
        "| dark | — |",
    ),
    Mutation(
        "M-2",
        "draw an eleventh board in §0",
        "G-BOARDS",
        "spec",
        "## 0.",
        "| 10 | `E47-D09 / 10 palette-hc`",
        "| 11 | `E47-D09 / 11 extra` | more | dark | pending: drawn later in this PR |\n"
        "| 10 | `E47-D09 / 10 palette-hc`",
    ),
    Mutation(
        "M-3",
        "empty DE-14's cancel cell in §3",
        "G-GRAMMAR",
        "spec",
        "## 3.",
        "| the picker's Cancel |",
        "| — |",
    ),
    Mutation(
        "M-4",
        "unmap `14`:662 from DE-14 in §3",
        "G-CENSUS",
        "spec",
        "## 3.",
        "| SCR-026 | :662 |",
        "| SCR-026 | — |",
    ),
    Mutation(
        "M-5",
        "drop `chart.zoom_price` from DE-06",
        "G-CHORD",
        "spec",
        "## 3.",
        " (`chart.zoom_price`)",
        "",
    ),
    Mutation(
        "M-6",
        "let `Esc` send an amend in §4",
        "G-ORDER",
        "spec",
        "## 4.",
        "the price at selection is restored (K-5) | nothing |",
        "the price at selection is restored (K-5) | one amend |",
    ),
    Mutation(
        "M-7",
        "halve the repeat window in §6",
        "G-COALESCE",
        "spec",
        "## 6.",
        "**`repeatWindow` 500 ms**",
        "**`repeatWindow` 250 ms**",
    ),
    Mutation(
        "M-8",
        "drop K-8 from §8's completeness bullet",
        "G-PALETTE",
        "spec",
        "## 8.",
        "**Completeness (K-8).**",
        "**Completeness.**",
    ),
    Mutation(
        "M-9",
        "rename F-02's row in §14",
        "G-FINDINGS",
        "spec",
        "## 14.",
        "| A11Y-R-E14-D10-F-02 |",
        "| A11Y-R-E14-D10-F-99 |",
    ),
    Mutation(
        "M-10",
        "drop CMP-079 from §12's T2 paragraph",
        "G-T2",
        "spec",
        "## 12.",
        "wrapped by CMP-079 RbacGate",
        "wrapped by a gate",
    ),
    Mutation(
        "M-11",
        "edit a `05` §3.2 cell",
        "G-NORM",
        "norm",
        "",
        "Opens searchable command list",
        "Opens a command list",
    ),
    Mutation(
        "M-12",
        "point a §1.3 cite past the end of D15",
        "G-CITE",
        "spec",
        "### 1.3",
        "D15:195, :196, :52",
        "D15:99999, :196, :52",
    ),
    Mutation(
        "M-13",
        "re-word W-14",
        "G-QUOTE",
        "spec",
        "## 16.",
        "Every binding is back to its default.",
        "Every binding is back to default.",
    ),
    Mutation(
        "M-14",
        "re-word D09-A15's Old fragment",
        "G-AROW",
        "hand",
        "## §C",
        "| is reserved by |",
        "| is refused by |",
    ),
    Mutation(
        "M-15",
        "mark the pinned BQ-7 as an unpinned default",
        "G-PENDING",
        "spec",
        "## The questions",
        "a hand-off row to E47-D07 — ruled as the default, pinned (the ruled sentence above)",
        "a hand-off row to E47-D07 — ruled as the default",
    ),
    Mutation(
        "M-16",
        "drop `(heuristic)` from H-3",
        "G-HEUR",
        "spec",
        "## 17.",
        "| H-3 | (heuristic) Consistency",
        "| H-3 | Consistency",
    ),
    Mutation(
        "M-17",
        "add two walkthrough items in the hand-off's §E",
        "G-WALK",
        "hand",
        "## §E",
        "- [ ] Board 03:",
        "- [ ] Extra one.\n- [ ] Extra two.\n- [ ] Board 03:",
    ),
    Mutation(
        "M-18",
        "name an agent as D09-G6's owner",
        "G-OWNER",
        "spec",
        "### 19.2",
        "E37-D04, the node editor's review",
        "the worker lane",
    ),
    Mutation(
        "M-19",
        "link E31-D01's unmerged file in the start line",
        "G-UNMERGED",
        "spec",
        "",
        "E31-D01 (the chart trading layer)",
        "E31-D01 (`docs/design/E31/E31-D01.md`)",
    ),
    Mutation(
        "M-20",
        "write a host beside the Penpot page in §0",
        "G-URL",
        "spec",
        "## 0.",
        "page `E47-D09`, cited",
        "page `E47-D09` at penpot.example.com, cited",
    ),
    Mutation(
        "M-21",
        "change the boards count in the header",
        "G-ANCHOR",
        "spec",
        "",
        "the 10<!--=COUNT:boards--> boards of §0",
        "the 11<!--=COUNT:boards--> boards of §0",
    ),
    Mutation(
        "M-22",
        "leave a placeholder unfilled",
        "G-MARKER",
        "spec",
        "<eof>",
        "",
        "{{COUNT:boards}}\n",
    ),
    Mutation(
        "M-23",
        "pad the spec past its line budget",
        "G-BUDGET",
        "spec",
        "<eof>",
        "",
        "\n" * 100,
    ),
    Mutation(
        "M-24",
        "touch `22` in the working tree",
        "G-UNTOUCHED",
        "changed",
        "",
        "",
        "docs/plan/22-api-openapi.yaml",
    ),
    Mutation(
        "M-25",
        "replace a mutation row's gate in §18",
        "G-MUTLIST",
        "spec",
        "## 18.",
        "| M-1 | blank board 01's status in §0 | G-BOARDS |",
        "| M-1 | blank board 01's status in §0 | G-CITE |",
    ),
    Mutation(
        "M-26",
        "map an exempt `14` line to a census row",
        "G-CENSUS",
        "spec",
        "## 3.",
        "| :1214 |",
        "| :1214, :85 |",
    ),
    Mutation(
        "M-27",
        "drop K-12 from `05` §3.5",
        "G-NORM",
        "norm",
        "",
        "- K-12 A bare letter",
        "- A bare letter",
    ),
    Mutation(
        "M-28",
        "drop 'Live never weaker than Demo' from the ruled BQ-5 sentence",
        "G-RULED",
        "spec",
        "## The questions",
        "never one amend per keypress; Live never weaker than Demo — handed",
        "never one amend per keypress — handed",
    ),
)

PROBES: tuple[Mutation, ...] = (
    Mutation(
        "P-1",
        "flip a prose sentence in §5",
        "G-RULED-PIN",
        "spec",
        "## 5.",
        "a view change announces nothing",
        "a view change announces its range",
    ),
    Mutation(
        "P-2",
        "re-word a hand-off summary item",
        "G-RULED-PIN",
        "hand",
        "## §I",
        "through the drag's confirm path",
        "through a confirm path",
    ),
)


def mutation_rows() -> str:
    return "\n".join(f"| {m.mid} | {m.what} | {m.gate} |" for m in MUTATIONS)


def loose(old: str) -> str:
    """A pattern for `old` in which every run of spaces matches any run (table padding)."""
    return re.sub(r"(?:\\ | )+", "[ ]+", re.escape(old))


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
        found = re.search(loose(m.old), span, re.DOTALL)
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
            if "<!--" in ANCHOR_TAG_RE.sub("", line):
                out.append(("G-MARKER", f"a stray HTML comment on line {i + 1}", doc, regions[i]))
    return out


CITE_RE = re.compile(
    r"(?:`(\d\d)`|\b("
    + "|".join(sorted(CITE_FILES, key=len, reverse=True))
    + r"))(:\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
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
    _, _, region = section(t.spec, "## 16.")
    for row in first_table(t.spec, "## 16.")[1:]:
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


def g_ruled(t: Texts) -> list[Finding]:
    s, e, region = section(t.spec, "## The questions")
    head = t.spec.split("\n")[s - 1] if s else ""
    lines = t.spec.split("\n")[s:e]
    bad: list[str] = []
    if f"RULED (orchestrator, comment {RULING_ID}, on the BQ list {BQ_LIST_ID})" not in head:
        bad.append("the heading does not name the ruling and the list")
    if RULED not in lines:
        bad.append("the ruled sentence is not verbatim")
    return [("G-RULED", b, "spec", region) for b in bad]


def g_pending(t: Texts) -> list[Finding]:
    s, e, region = section(t.spec, "## The questions")
    lines = t.spec.split("\n")[s:e]
    bad: list[str] = []
    for bq in BQ_IDS:
        rows = [ln for ln in lines if ln.startswith(f"- **{bq}**")]
        want = BQ_PINNED if bq in BQ_PINNED_IDS else BQ_DEFAULT
        if len(rows) != 1:
            bad.append(f"{bq} appears {len(rows)} times")
        elif want not in rows[0] or (want == BQ_DEFAULT and BQ_PINNED in rows[0]):
            bad.append(f"{bq} is not marked '{want}'")
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
        name = re.fullmatch(r"`E47-D09 / (\d\d) ([a-z0-9-]+)`", r[1])
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


def filled(cell: str) -> bool:
    return bool(cell.strip()) and cell.strip() not in ("—", "-", "–")


def g_grammar(t: Texts) -> list[Finding]:
    bad: list[tuple[str, str]] = []
    _, _, r2 = section(t.spec, "## 2.")
    phases = [r[0] for r in first_table(t.spec, "## 2.")[1:]]
    if tuple(phases) != PHASES:
        bad.append((r2, f"the grammar's phases are {phases}"))
    for r in first_table(t.spec, "### 2.1")[1:]:
        if len(r) < 5 or not all(filled(c) for c in r):
            bad.append((section(t.spec, "### 2.1")[2], f"unit row '{r[0]}' has an empty cell"))
    _, _, r3 = section(t.spec, "## 3.")
    for r in census_rows(t.spec):
        if len(r) < 9 or not all(filled(c) for c in r[4:8]):
            bad.append((r3, f"{r[0]} lacks select, adjust, commit or cancel"))
        elif not UNIT_RE.search(r[5]):
            bad.append((r3, f"{r[0]}'s adjust states no unit and no 'none:'"))
    return [("G-GRAMMAR", msg, "spec", reg) for reg, msg in bad]


def g_census(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 3.")
    want = set(drag_hover_lines())
    mapped = {n for r in census_rows(t.spec) if len(r) > 3 for n in line_numbers(r[3])}
    exempt = set(exempt_numbers(t.spec))
    bad: list[str] = []
    for n in sorted(want - mapped - exempt):
        bad.append(f"`14`:{n} names a drag or a hover and is unmapped")
    for n in sorted(mapped & exempt):
        bad.append(f"`14`:{n} is both mapped and exempt")
    for n in sorted((mapped | exempt) - want):
        bad.append(f"`14`:{n} names no drag or hover")
    return [("G-CENSUS", b, "spec", region) for b in bad]


def g_chord(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 3.")
    text = "\n".join(" | ".join(r) for r in census_rows(t.spec))
    return [
        ("G-CHORD", f"the pointer chord {cid} is not named in §3", "spec", region)
        for cid in chord_ids()
        if f"`{cid}`" not in text
    ]


def g_order(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 4.")
    rows = first_table(t.spec, "## 4.")[1:]
    bad: list[str] = []
    sending = [r for r in rows if len(r) > 2 and r[2] != "nothing"]
    if len(sending) != 1 or sending[0][0] != "`Enter`" or "US-SET-003" not in sending[0][2]:
        bad.append("only `Enter` may send, once, under US-SET-003")
    esc = [r for r in rows if r and r[0].startswith("`Esc`, or focus")]
    if len(esc) != 1 or esc[0][2] != "nothing":
        bad.append("`Esc` before a commit must send nothing")
    return [("G-ORDER", b, "spec", region) for b in bad]


def g_coalesce(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 6.")
    text = "\n".join(body(t.spec, "## 6."))
    src = base_lines(CITE_FILES["D03E06"])[104]
    return [
        ("G-COALESCE", f"§6 or D03E06:105 lacks {mine}", "spec", region)
        for mine, theirs in D5_PARAMS
        if mine not in text or theirs not in src
    ]


def g_palette(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.spec, "## 8.")
    first = [ln for ln in body(t.spec, "## 8.") if ln.startswith("- **Completeness")]
    if len(first) != 1 or "(K-8)" not in first[0] or "COUNT:palette" not in first[0]:
        out.append(("G-PALETTE", "§8's completeness bullet lacks K-8 or its count", "spec", region))
    _, _, hreg = section(t.hand, "## §G")
    qa1 = [r for r in first_table(t.hand, "## §G")[1:] if r and r[0] == "QA-1"]
    if len(qa1) != 1 or "`keymap.json` minus `global.palette`" not in qa1[0][1]:
        out.append(("G-PALETTE", "QA-1 does not enumerate the registry", "hand", hreg))
    return out


def g_findings(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 14.")
    rows = {r[0]: r for r in first_table(t.spec, "## 14.")[1:] if len(r) > 2}
    bad: list[str] = []
    reg = {str(f.get("id")): f for f in register_findings()}
    if set(rows) != set(reg):
        bad.append(f"§14 lists {sorted(rows)}, the register {sorted(reg)}")
    for fid, f in reg.items():
        r = rows.get(fid)
        screens = f.get("screens")
        if r is None:
            continue
        if not isinstance(screens, list) or r[1] != ", ".join(str(s) for s in screens):
            bad.append(f"{fid}'s screens differ from the register")
        if not filled(r[2]):
            bad.append(f"{fid} has no disposition")
    return [("G-FINDINGS", b, "spec", region) for b in bad]


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
    for prefix in ("## 4.", "## 8."):
        _, _, reg = section(t.spec, prefix)
        if "§12" not in "\n".join(body(t.spec, prefix)):
            out.append(("G-T2", f"{prefix} does not cite §12", "spec", reg))
    lines, regions = t.hand.split("\n"), line_regions(t.hand)
    comp = [i for i, ln in enumerate(lines) if ln.startswith("Components: ")]
    if len(comp) != 1 or not all(x in lines[comp[0]] for x in ("CMP-079 RbacGate", "CMP-019")):
        reg = regions[comp[0]] if len(comp) == 1 else ""
        out.append(("G-T2", "the hand-off's component list omits CMP-079 or CMP-019", "hand", reg))
    return out


def rule_ids(spec: str) -> list[str]:
    return re.findall(r"^- \*\*(K-\d+) ", "\n".join(body(spec, "### 1.4")), re.MULTILINE)


def norm_section(text: str, prefix: str) -> list[str]:
    return body(text, prefix)


def g_norm(t: Texts) -> list[Finding]:
    bad: list[str] = []
    sec = norm_section(t.norm, "### 3.5 Keyboard equivalents (E47-D09)")
    if not sec:
        bad.append("`05` §3.5 is missing")
    else:
        if not any(SPEC_REL in ln for ln in sec):
            bad.append("`05` §3.5 does not point at the spec")
        got = [m.group(1) for ln in sec if (m := re.match(r"- (K-\d+) ", ln))]
        if got != rule_ids(t.spec):
            bad.append("`05` §3.5's rules differ from the spec's §1.4")
    if not any(ln.startswith("7. Chart pan") and "E06-D03 D6" in ln for ln in t.norm.split("\n")):
        bad.append("`05` §3.1 item 7 does not cite E06-D03 D6")
    if "once that screen is specced" in t.norm or "E37-D02.md` §13" not in t.norm:
        bad.append("the `05` §3.3 node-graph pointer is not fixed")
    if norm_section(t.norm, "### 3.2 ") != norm_section(at_base(NORM_REL), "### 3.2 "):
        bad.append("`05` §3.2 (the locked keymap) differs from the base")
    return [("G-NORM", b, "norm", "") for b in bad]


def g_heur(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 17.")
    return [
        ("G-HEUR", f"{r[0]} lacks (heuristic)", "spec", region)
        for r in first_table(t.spec, "## 17.")[1:]
        if len(r) < 2 or not r[1].startswith("(heuristic) ")
    ]


def g_walk(t: Texts) -> list[Finding]:
    _, _, region = section(t.hand, "## §E")
    n = sum(1 for ln in body(t.hand, "## §E") if ln.startswith("- ["))
    return [] if 1 <= n <= 10 else [("G-WALK", f"{n} walkthrough items", "hand", region)]


def g_owner(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 19.2")
    out: list[Finding] = []
    for r in first_table(t.spec, "### 19.2")[1:]:
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
    _, _, region = section(t.spec, "## 18.")
    rows = [(r[0], r[1], r[2]) for r in first_table(t.spec, "## 18.")[1:] if len(r) > 2]
    want = [(m.mid, m.what, m.gate) for m in MUTATIONS]
    return (
        [] if rows == want else [("G-MUTLIST", "§18 differs from the tool's list", "spec", region)]
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
        "# E47-D09 pins (every unit of the spec and the hand-off): doc, region (heading path"
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
    out += g_ruled(t) + g_pending(t) + g_boards(t) + g_grammar(t) + g_census(t) + g_chord(t)
    out += g_order(t) + g_coalesce(t) + g_palette(t) + g_findings(t) + g_t2(t) + g_norm(t)
    out += g_heur(t) + g_walk(t) + g_owner(t)
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
