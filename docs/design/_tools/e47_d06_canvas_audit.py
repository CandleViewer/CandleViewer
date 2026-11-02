#!/usr/bin/env python3
"""E47-D06 (#1305) audit: the canvas accessibility layers (text first; boards drawn later).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at a pinned commit (`git show`): the plan and merged design texts the spec cites at the
base, the E47-D02 catalogue and register at their merge commit, and the in-flight E47 packs at
their PR heads; and, from the working tree, the spec `docs/design/E47/E47-D06.md`, its hand-off
and the pins file. Its form follows the E47-D03 and E47-D04 tools (the same modes, the anchored
values, the default-deny pins and the mutations).

1. **Values.** Every `{{KIND:key}}` placeholder is written by `--fill` as `VALUE<!--=KIND:key-->`:
   COUNT (rows of the spec's and the hand-off's own tables; the register's E47-D06 rows; the
   inventory screens the register tags `chrome`); no cap is summed (BQ-4 as ruled). `--check` re-derives each anchored value (G-ANCHOR) and FAILs a
   placeholder left behind or a stray HTML comment (G-MARKER). `--fill` also writes the mutation
   rows ({{MUTATIONS}}) from this file's constants.
2. **Cites.** Every `NN`:line and KEY:line cite of both documents resolves to a non-blank line at
   its pinned commit (G-CITE); every "verbatim" copy string occurs on its cited line (G-QUOTE);
   every Old fragment of the hand-off's A-rows occurs verbatim on its cited line (G-AROW).
3. **Gates.** One FAIL line per gate: G-PENDING (the BQ heading carries the RULED stamp with the
   ruling's and the BQ list's comments; BQ-0 ... BQ-15 once each, each stamped RULED), G-PIN (the start line
   and the version line name every in-flight pack's PR and pinned sha and say they re-pin),
   G-BOARDS (at most ten boards, light twins at most a third, each PENDING, the not-drawn
   paragraph), G-INV (every inventory row fills its four layers, names a grammar, claims no
   exemption; every screen the register tags `canvas` is in the inventory), G-PARITY (every oracle
   row is complete and names an inventory surface; P-1 ... P-5 are AC2's five footprint columns;
   every surface designed here has a row), G-COLS (the footprint, profile and ladder sets equal
   `05`'s first column at the base), G-CAP (every figure of §4 occurs on its cited line; each row is
   merged or PROPOSED; no cap is added), G-T2 (§10 states the T2 paragraph; §7 cites it; the hand-off names CMP-079 and
   CMP-019), G-FINDINGS (§12 equals the register's E47-D06 rows), G-NOCLAIM (no conformance claim
   for the canvas alone), G-PUBLIC (no URL, host or local path), G-UNMERGED (no link to
   an unmerged pack), G-KEYWORD (no closing keyword followed by an issue number), G-HEUR, G-WALK
   (at most ten items), G-OWNER (G-ledger owners are tickets or owners, never an agent),
   G-UNTOUCHED (only this ticket's files differ from the merge base with origin/main), G-BUDGET,
   G-MUTLIST (§15 equals this tool's list) and G-APPLY (the hand-off's §B is a three-column table
   whose rows name every §C A-row exactly once, each with a ticket or the owner as its applier).
4. **Pins (G-RULED).** Every non-blank line of the BQ section is pinned in
   `e47_d06_ruled_pins.txt`; `--repin-ruled` is the only writer and refuses while a placeholder
   is unfilled. A pin finding while another gate FAILs in the BQ section prints as NOTE.
5. **--self-test** applies every mutation (M-n) in memory with the values frozen at the filled
   baseline; each must add exactly one FAIL, from the gate it names; the texts on disk are checked
   byte-identical afterwards (sha256). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e47_d06_canvas_audit.py --check [--fill]
  python3 -I docs/design/_tools/e47_d06_canvas_audit.py --self-test
  python3 -I docs/design/_tools/e47_d06_canvas_audit.py --repin-ruled
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
BASE = "85b6b6c1c"  # origin/main when the spec was written; every plan cite is read here
D02_MERGE = "2a5bf8fd2"  # E47-D02's catalogue and register (#5248)
SPEC_REL = "docs/design/E47/E47-D06.md"
HAND_REL = "docs/design/E47/E47-D06-handoff.md"
TOOL_REL = "docs/design/_tools/e47_d06_canvas_audit.py"
PIN_REL = "docs/design/_tools/e47_d06_ruled_pins.txt"
BOARD_PREFIX = "docs/design/E47/img/E47-D06-"
OWN = (SPEC_REL, HAND_REL, TOOL_REL, PIN_REL)
SPEC_BUDGET = 490  # a deliberate ratchet: about 20 lines over the spec; raise it only with a reason
HAND_BUDGET = 150

# The in-flight packs (read at their PR heads, re-pinned at their merges) and E47-D03's merge.
INFLIGHT: dict[str, tuple[str, str, str]] = {
    "D04": ("docs/design/E47/E47-D04.md", "1ff5d8cb9", "5387"),
    "D05": ("docs/design/E47/E47-D05.md", "3987edc89", "5417"),
    "D09": ("docs/design/E47/E47-D09.md", "260bb0caf", "5418"),
    "D13": ("docs/design/E47/E47-D13.md", "91e9bde44", "5419"),
}
D03_MERGE = ("73fefc62b", "5392")
PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "26": "docs/plan/26-chart-engine-design.md",
}
CITE_FILES = {
    "D03E06": "docs/design/E06/E06-D03.md",
    "D04E11": "docs/design/E11/E11-D04.md",
    "D07E11": "docs/design/E11/E11-D07.md",
    "D09E09": "docs/design/E09/E09-D09.md",
    "D03E47": "docs/design/E47/E47-D03.md",
    "CAT": "docs/plan/a11y/47-audit-catalogue.md",
    "KM": "apps/web/src/keymap/keymap.json",
    "E47J": "docs/plan/backlog/E47.json",
    "R32": ".claude/rules/32-design-specs.md",
    "PW": "apps/web/src/chart/a11y/politeWriter.ts",
    "README": "docs/design/README.md",
    **{k: v[0] for k, v in INFLIGHT.items()},
}
REGISTER_REL = "docs/plan/a11y/47-audit-register.json"
FILE_BASE = {
    CITE_FILES["CAT"]: D02_MERGE,
    REGISTER_REL: D02_MERGE,
    **{v[0]: v[1] for v in INFLIGHT.values()},
    PLAN["26"]: "720684e7f",  # #5386 moved `26`'s lines; its cites are re-pinned by content here
}

BQ_LIST_ID = "6569517180"  # the BQ list on #1305
RULING_ID = "6570047499"  # the orchestrator's ruling of record on it
BQ_HEAD = (
    f"## The questions BQ-0 … BQ-15 — RULED (orchestrator, comment {RULING_ID},"
    f" on the BQ list {BQ_LIST_ID})"
)
RULED_STAMP = f"RULED ({RULING_ID}"
CAP_STATUS = ("merged", "PROPOSED")
BQ_IDS = tuple(f"BQ-{n}" for n in range(16))
GRAMMARS = ("cursor-window", "sparse set", "native DOM")
AC2_COLS = ("Bid vol", "Ask vol", "Delta", "Imbalance flag", "Estimated badge")
COL_LINES = {"footprint": (164, 169), "profile": (175, 179), "ladder": (185, 189)}
T2_TOKENS = (
    "CMP-079",
    "CMP-019",
    "`lock`",
    "2a inline",
    "one-notice",
    'aria-disabled="true"',
    "at mount",
    "one polite announcement",
    "`↑` / `↓`",
    "never `inert`",
)
CLAIM_RE = re.compile(
    r"\b(?:the )?canvas (?:itself |alone )?is (?:now |fully )?accessible\b|\bfully accessible\b",
    re.IGNORECASE,
)
_KW = "|".join(("clo" + "se[sd]?", "fix" + "(?:e[sd])?", "resol" + "ve[sd]?"))
KEYWORD_RE = re.compile(rf"\b(?:{_KW}):?\s*#\d+", re.IGNORECASE)
URL_RE = re.compile(r"https?://|\bwww\.|/home/|\.local\b|\bpenpot\.[a-z]", re.IGNORECASE)
AGENT_RE = re.compile(r"worker|\bagent\b|\blane\b", re.IGNORECASE)
OWNER_OK_RE = re.compile(r"\bE\d\d-[A-Z]+\d\d\b|\bowner\b|\blead\b")
UNMERGED_RE = re.compile(r"\]\((?:\.\./E47/)?E47-D(?:04|05|09|13)[^)]*\)")

Finding = tuple[str, str, str, str]  # gate, message, doc, region
Values = dict[str, str]


# ---------------------------------------------------------------------------- git and files


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=True,
    ).stdout


@functools.lru_cache(maxsize=64)
def at_base(rel: str) -> str:
    return git("show", f"{FILE_BASE.get(rel, BASE)}:{rel}")


@functools.lru_cache(maxsize=64)
def base_lines(rel: str) -> tuple[str, ...]:
    return tuple(at_base(rel).split("\n"))


def changed_paths() -> tuple[str, ...]:
    fork = git("merge-base", "HEAD", "origin/main").strip()
    tracked = git("diff", "--name-only", fork).split()
    untracked = git("ls-files", "--others", "--exclude-standard").split()
    return tuple(sorted(set(tracked) | set(untracked)))


@functools.lru_cache(maxsize=1)
def register() -> dict[str, object]:
    data = json.loads(at_base(REGISTER_REL))
    assert isinstance(data, dict)
    return data


def register_rows(key: str) -> list[dict[str, object]]:
    rows = register()[key]
    assert isinstance(rows, list)
    return [r for r in rows if isinstance(r, dict)]


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


ANCHOR_RE = re.compile(r"([0-9][0-9,]*)<!--=([A-Z]+):([a-z0-9.\-]+)-->", re.DOTALL)
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z]+):([a-z0-9.\-]+)\}\}")
STRAY_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def cut_anchors(text: str) -> str:
    return ANCHOR_RE.sub(lambda m: f"<{m.group(2)}:{m.group(3)}>", text)


# ---------------------------------------------------------------------------- values


def inv_rows(spec: str) -> list[list[str]]:
    return first_table(spec, "## 2.")[1:]


def inv_screens(spec: str) -> list[str]:
    ids: list[str] = []
    for row in inv_rows(spec):
        for sid in re.findall(r"SCR-\d{3}", row[2] if len(row) > 2 else ""):
            if sid not in ids:
                ids.append(sid)
    return ids


def surface_of() -> dict[str, str]:
    return {str(r["id"]): str(r.get("surface")) for r in register_rows("screens")}


def d06_findings() -> list[dict[str, object]]:
    return [r for r in register_rows("findings") if r.get("designOwner") == "E47-D06"]


def cap_rows(spec: str) -> list[list[str]]:
    return first_table(spec, "## 4.")[1:]


def walk_items(hand: str) -> list[str]:
    return [ln for ln in body(hand, "## §E") if ln.startswith("- [ ]")]


def compute_values(t: Texts) -> Values:
    boards = first_table(t.spec, "## 0.")[1:]
    v: Values = {
        "COUNT:boards": str(len(boards)),
        "COUNT:boards.twins": str(sum(1 for r in boards if len(r) > 3 and r[3] != "dark")),
        "COUNT:inv": str(len(inv_rows(t.spec))),
        "COUNT:parity": str(len(first_table(t.spec, "## 9.")[1:])),
        "COUNT:findings": str(len(d06_findings())),
        "COUNT:heur": str(len(first_table(t.spec, "## 14.")[1:])),
        "COUNT:arows": str(len(first_table(t.hand, "## §C")[1:])),
    }
    surf = surface_of()
    v["COUNT:cat.chrome"] = str(sum(1 for s in inv_screens(t.spec) if surf.get(s) == "chrome"))
    return v


# ---------------------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str
    what: str
    doc: str  # "spec", "hand" or "changed"
    old: str
    new: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        "M-1", "G-ANCHOR", "change the inventory count in §2", "spec", "<!--=COUNT:inv-->", ""
    ),
    Mutation("M-2", "G-MARKER", "leave a stray HTML comment in §1.1", "spec", "One treatment", ""),
    Mutation("M-3", "G-CITE", "point §3.3's cite past the end of D07E11", "spec", "", ""),
    Mutation("M-4", "G-QUOTE", "re-word W-2", "spec", '"Showing 6 of 40', '"Showing 7 of 40'),
    Mutation(
        "M-5",
        "G-AROW",
        "re-word D06-A4's Old fragment",
        "hand",
        "| press Alt+T to refresh to current ",
        "| press Alt+T to refresh now ",
    ),
    Mutation(
        "M-6",
        "G-PENDING",
        "drop BQ-6's RULED stamp",
        "spec",
        "- **BQ-6 — table alternatives per surface.** RULED (6570047499)",
        "- **BQ-6 — table alternatives per surface.** Default built",
    ),
    Mutation("M-7", "G-RULED", "re-word BQ-0's default", "spec", "pre-staged under", "built under"),
    Mutation(
        "M-8",
        "G-PIN",
        "give E47-D05's head a wrong sha in the start line",
        "spec",
        "PR #5417 at `3987edc89` (D05)",
        "PR #5417 at `3987edc88` (D05)",
    ),
    Mutation("M-9", "G-BOARDS", "blank board 01's status in §0", "spec", "", ""),
    Mutation("M-10", "G-INV", "blank IV-5's table alternative in §2", "spec", "", ""),
    Mutation("M-11", "G-INV", "exempt IV-10 on density in §2", "spec", "", ""),
    Mutation("M-12", "G-PARITY", "blank P-3's table column in §9", "spec", "", ""),
    Mutation(
        "M-13",
        "G-COLS",
        "rename the profile column % of POC",
        "spec",
        "| % of POC    |",
        "| Pct of POC  |",
    ),
    Mutation("M-14", "G-CAP", "raise the drawing-surrogate figure in §4", "spec", "", ""),
    Mutation(
        "M-15",
        "G-CAP",
        "drop the no-new-cap sentence of §4",
        "spec",
        "No cap is added (D04:340). ",
        "",
    ),
    Mutation(
        "M-16",
        "G-T2",
        "drop CMP-019 from §10's T2 paragraph",
        "spec",
        "the CMP-019 Icon `lock` glyph",
        "the `lock` glyph",
    ),
    Mutation(
        "M-17",
        "G-T2",
        "drop CMP-079 from the hand-off's component list",
        "hand",
        "**CMP-079 RbacGate** with",
        "RbacGate with",
    ),
    Mutation(
        "M-18",
        "G-NOCLAIM",
        "write a conformance claim for the canvas in §1.1",
        "spec",
        "One treatment for",
        "The canvas is accessible: one treatment for",
    ),
    Mutation(
        "M-19",
        "G-PUBLIC",
        "write a URL in §1.2",
        "spec",
        "Desk work at the base",
        "Desk work at https://example.org",
    ),
    Mutation(
        "M-20",
        "G-KEYWORD",
        "write a closing keyword in §17.3",
        "spec",
        "never the closing keyword;",
        "never Clo" + "ses #1305;",
    ),
    Mutation(
        "M-21",
        "G-FINDINGS",
        "change F-09's remediation in §12",
        "spec",
        "`E14-D05 · area/charting-ui`",
        "`E14-D06 · area/charting-ui`",
    ),
    Mutation(
        "M-22",
        "G-HEUR",
        "drop (heuristic) from H-3",
        "spec",
        "| H-3 | (heuristic) Error",
        "| H-3 | Error",
    ),
    Mutation(
        "M-23",
        "G-WALK",
        "add three walkthrough items in the hand-off's §E",
        "hand",
        "- [ ] Record `approved`",
        "- [ ] one more.\n- [ ] and another.\n- [ ] and a third.\n- [ ] Record `approved`",
    ),
    Mutation(
        "M-24",
        "G-OWNER",
        "name an agent as D06-G3's owner",
        "spec",
        "E21-S01 (#648); the chart-engine lead",
        "the design agent",
    ),
    Mutation(
        "M-25",
        "G-UNTOUCHED",
        "touch `22` in the working tree",
        "changed",
        "",
        "docs/plan/22-api-openapi.yaml",
    ),
    Mutation("M-26", "G-BUDGET", "pad the spec past its line budget", "spec", "", ""),
    Mutation(
        "M-27",
        "G-MUTLIST",
        "replace a mutation row's gate in §15",
        "spec",
        "| M-22 | drop (heuristic) from H-3",
        "| M-22 | drop the tag from H-3",
    ),
    Mutation(
        "M-28",
        "G-UNMERGED",
        "link E47-D04's unmerged file in the start line",
        "spec",
        "re-pinned to its merge commit when it merges",
        "re-pinned to its merge commit when it merges ([E47-D04](E47-D04.md))",
    ),
    Mutation("M-29", "G-APPLY", "paste §C cells into D06-A16's §B row", "hand", "", ""),
)


def mutation_rows(ms: tuple[Mutation, ...] = MUTATIONS) -> str:
    head = "| M    | Mutation | Gate |\n| ---- | -------- | ---- |\n"
    return head + "\n".join(f"| {m.mid} | {m.what} | {m.gate} |" for m in ms)


def row_sub(text: str, lead: str, col: int, value: str) -> str:
    """Set cell `col` of the first table row whose first cell is `lead`."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and cells(line)[0] == lead:
            c = cells(line)
            c[col] = value
            lines[i] = "| " + " | ".join(c) + " |"
            return "\n".join(lines)
    raise AssertionError(f"no row {lead}")


def apply_mutation(t: Texts, m: Mutation) -> Texts:
    if m.doc == "changed":
        return replace(t, changed=(*t.changed, m.new))
    text = t.doc(m.doc)
    if m.mid == "M-1":
        text = re.sub(r"\d+(<!--=COUNT:inv-->)", r"99\1", text, count=1)
    elif m.mid == "M-2":
        text = text.replace("One treatment", "<!-- note --> One treatment", 1)
    elif m.mid == "M-3":
        text = text.replace("(D07E11:139). Two overlapping", "(D07E11:99999). Two overlapping", 1)
    elif m.mid == "M-9":
        text = row_sub(text, "01", 4, "")
    elif m.mid == "M-10":
        text = row_sub(text, "IV-5", 5, "")
    elif m.mid == "M-11":
        text = row_sub(text, "IV-10", 7, "exempt on density")
    elif m.mid == "M-12":
        text = row_sub(text, "P-3", 4, "")
    elif m.mid == "M-14":
        text = re.sub(r"(\| chart +\| drawing surrogates +\| )200 ", r"\g<1>300 ", text, count=1)
    elif m.mid == "M-29":
        text = row_sub(text, "D06-A16", 2, '`context` | "validWhen": "chart panel focused"')
    elif m.mid == "M-26":
        text = text + "\n" * (SPEC_BUDGET + 1)
    else:
        if m.old not in text:
            raise AssertionError(f"{m.mid}: target not found")
        text = text.replace(m.old, m.new, 1)
    return replace(t, spec=text) if m.doc == "spec" else replace(t, hand=text)


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
                        ("G-ANCHOR", f"{key} reads {m.group(1)}, not {want}", doc, regions[i])
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
            if STRAY_RE.search(ANCHOR_RE.sub("", line)):
                out.append(("G-MARKER", f"a stray HTML comment on line {i + 1}", doc, regions[i]))
    return out


_KEYS = sorted(CITE_FILES, key=len, reverse=True)
CITE_RE = re.compile(
    r"(?:`(\d\d)`|\b(" + "|".join(_KEYS) + r"))(:\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
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
            out.append(("G-AROW", f"{row[0]} has too few cells", "hand", region))
            continue
        if row[3].replace("\\|", "|") not in cited_text(row[2]):
            out.append(("G-AROW", f"{row[0]}'s Old is not verbatim on its line", "hand", region))
    return out


def bq_lines(spec: str) -> list[str]:
    return [ln for ln in body(spec, "## The questions") if ln.strip()]


def g_pending(t: Texts) -> list[Finding]:
    s, _, region = section(t.spec, "## The questions")
    head = t.spec.split("\n")[s - 1] if s else ""
    lines = bq_lines(t.spec)
    bad: list[str] = []
    if head != BQ_HEAD:
        bad.append("the heading lacks the RULED stamp or its comment ids")
    for bq in BQ_IDS:
        rows = [ln for ln in lines if ln.startswith(f"- **{bq} — ")]
        if len(rows) != 1:
            bad.append(f"{bq} appears {len(rows)} times")
        elif not rows[0].split(".** ", 1)[-1].startswith(RULED_STAMP):
            bad.append(f"{bq} is not stamped {RULED_STAMP})")
    return [("G-PENDING", b, "spec", region) for b in bad]


def read_pins() -> list[str]:
    path = ROOT / PIN_REL
    if not path.exists():
        return []
    return [
        ln for ln in path.read_text(encoding="utf-8").split("\n") if ln and not ln.startswith("#")
    ]


def g_ruled(t: Texts) -> list[Finding]:
    have, pins = bq_lines(t.spec), read_pins()
    _, _, region = section(t.spec, "## The questions")
    if not pins:
        return [("G-RULED", "no pins file; run --repin-ruled", "spec", region)]
    if have != pins:
        n = sum(1 for a, b in zip(have, pins, strict=False) if a != b) + abs(len(have) - len(pins))
        return [("G-RULED", f"{n} BQ line(s) differ from the pins", "spec", region)]
    return []


def g_pin(t: Texts) -> list[Finding]:
    lines = t.spec.split("\n")
    regions = line_regions(t.spec)
    out: list[Finding] = []
    for tag in ("**Start.**", "**Version line.**"):
        idx = [i for i, ln in enumerate(lines) if tag in ln]
        if len(idx) != 1:
            out.append(("G-PIN", f"{tag} appears {len(idx)} times", "spec", "(top)#1"))
            continue
        ln, reg = lines[idx[0]], regions[idx[0]]
        pairs = [(sha, pr) for _, sha, pr in INFLIGHT.values()] + [D03_MERGE]
        for sha, pr in pairs:
            if f"PR #{pr}" not in ln or f"`{sha}`" not in ln:
                out.append(("G-PIN", f"{tag} lacks PR #{pr} at {sha}", "spec", reg))
        if "re-pinned" not in ln:
            out.append(("G-PIN", f"{tag} does not say the heads re-pin", "spec", reg))
    for key, (rel, sha, _) in INFLIGHT.items():
        if FILE_BASE.get(rel) != sha:
            out.append(("G-PIN", f"{key} is not read at its head", "spec", "(tool)"))
    return out


def g_boards(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 0.")
    rows = first_table(t.spec, "## 0.")[1:]
    bad: list[str] = []
    if not 1 <= len(rows) <= 10:
        bad.append(f"{len(rows)} boards")
    twins = sum(1 for r in rows if len(r) > 3 and r[3] != "dark")
    if twins * 3 > len(rows):
        bad.append(f"{twins} twins exceed a third")
    for r in rows:
        if len(r) < 5 or r[4] != "PENDING":
            bad.append(f"board {r[0]} is not PENDING")
    if "**Not drawn — the text is binding**" not in "\n".join(body(t.spec, "## 0.")):
        bad.append("no not-drawn paragraph")
    return [("G-BOARDS", b, "spec", region) for b in bad]


def g_inv(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 2.")
    rows = inv_rows(t.spec)
    bad: list[str] = []
    for k, r in enumerate(rows, 1):
        if len(r) != 8 or r[0] != f"IV-{k}":
            bad.append(f"row {k} is malformed")
            continue
        if any(not c for c in r):
            bad.append(f"{r[0]} has an empty cell")
        if not any(g in r[3] for g in GRAMMARS):
            bad.append(f"{r[0]} names no grammar")
        if any(re.search(r"\bexempt", c, re.IGNORECASE) for c in r):
            bad.append(f"{r[0]} claims an exemption")
    text = "\n".join(body(t.spec, "## 2."))
    for sid, surf in sorted(surface_of().items()):
        if surf == "canvas" and sid not in text:
            bad.append(f"{sid} (canvas in the register) is not in the inventory")
    return [("G-INV", b, "spec", region) for b in bad]


def g_parity(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 9.")
    rows = first_table(t.spec, "## 9.")[1:]
    ivs = {r[0]: r for r in inv_rows(t.spec) if r}
    bad: list[str] = []
    for r in rows:
        if len(r) != 7 or any(not c for c in r):
            bad.append(f"{r[0] if r else '?'} is incomplete")
        elif r[1] not in ivs:
            bad.append(f"{r[0]} names an unknown surface {r[1]}")
    head = [r for r in rows[:5] if len(r) == 7]
    if [r[1] for r in head] != ["IV-2"] * 5 or tuple(r[4] for r in head) != AC2_COLS:
        bad.append("P-1 ... P-5 are not AC2's five footprint columns")
    covered = {r[1] for r in rows if len(r) > 1}
    for iv, r in ivs.items():
        if len(r) == 8 and r[7].startswith("designed here") and iv not in covered:
            bad.append(f"{iv} is designed here but has no oracle row")
    return [("G-PARITY", b, "spec", region) for b in bad]


def g_cols(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 6.2")
    ts = tables(t.spec, "### 6.2")
    lines = base_lines(PLAN["05"])
    bad: list[str] = []
    for k, (name, (a, b)) in enumerate(COL_LINES.items()):
        want = [cells(lines[n - 1])[0] for n in range(a, b + 1)]
        have = [plain(r[0]) for r in ts[k][1:]] if k < len(ts) else []
        if have != want:
            bad.append(f"the {name} set differs from `05`:{a}–{b}")
    return [("G-COLS", b, "spec", region) for b in bad]


def g_cap(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 4.")
    bad: list[str] = []
    for r in cap_rows(t.spec):
        if len(r) != 5 or not re.fullmatch(r"[0-9][0-9,]*", r[2]) or r[4] not in CAP_STATUS:
            bad.append(f"cap row {r[:2]} is malformed")
            continue
        src = cited_text(r[3])
        if not src or not re.search(rf"(?<![\d,]){re.escape(r[2])}(?![\d,])", src):
            bad.append(f"{r[0]} {r[1]}: {r[2]} is not on {r[3]}")
    if "No cap is added" not in "\n".join(body(t.spec, "## 4.")):
        bad.append("the no-new-cap sentence is missing")
    return [("G-CAP", b, "spec", region) for b in bad]


def g_t2(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    _, _, region = section(t.spec, "## 10.")
    paras = [ln for ln in body(t.spec, "## 10.") if ln.startswith("**The T2 paragraph")]
    if len(paras) != 1:
        out.append(("G-T2", "the T2 paragraph is not stated once", "spec", region))
    else:
        for tok in T2_TOKENS:
            if tok not in paras[0]:
                out.append(("G-T2", f"the T2 paragraph lacks {tok}", "spec", region))
    if "§10" not in "\n".join(body(t.spec, "## 7.")):
        out.append(("G-T2", "§7 does not cite §10", "spec", section(t.spec, "## 7.")[2]))
    head = t.hand.split("\n## ")[0]
    for tok in ("**CMP-079 RbacGate**", "**CMP-019 Icon** `lock`"):
        if tok not in head:
            out.append(("G-T2", f"the hand-off's component list lacks {tok}", "hand", "(top)#1"))
    return out


def g_findings(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 12.")
    have = {r[0]: r for r in first_table(t.spec, "## 12.")[1:] if r}
    bad: list[str] = []
    want = d06_findings()
    if set(have) != {str(f["id"]) for f in want}:
        bad.append("the rows are not the register's E47-D06 rows")
    for f in want:
        r = have.get(str(f["id"]))
        if r is None or len(r) != 5:
            continue
        screens = f["screens"]
        assert isinstance(screens, list)
        if r[1] != ", ".join(str(s) for s in screens) or r[2] != f["status"]:
            bad.append(f"{f['id']} differs in screens or status")
        if r[4] != f["remediation"] or not r[3]:
            bad.append(f"{f['id']} differs in remediation or has no closing section")
    return [("G-FINDINGS", b, "spec", region) for b in bad]


def g_heur(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 14.")
    rows = first_table(t.spec, "## 14.")[1:]
    return [
        ("G-HEUR", f"{r[0]} is not marked (heuristic)", "spec", region)
        for r in rows
        if len(r) < 2 or not r[1].startswith("(heuristic)")
    ]


def g_walk(t: Texts) -> list[Finding]:
    n = len(walk_items(t.hand))
    if not 1 <= n <= 10:
        return [("G-WALK", f"{n} walkthrough items", "hand", section(t.hand, "## §E")[2])]
    return []


def g_owner(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 16.2")
    out: list[Finding] = []
    for r in first_table(t.spec, "### 16.2")[1:]:
        if len(r) < 4 or AGENT_RE.search(r[3]) or not OWNER_OK_RE.search(r[3]):
            out.append(("G-OWNER", f"{r[0]}'s owner is not a ticket or an owner", "spec", region))
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
            out.append(("G-KEYWORD", f"a closing keyword in {rel}", "spec", "(file)"))
    return out


def g_untouched(t: Texts) -> list[Finding]:
    bad = [p for p in t.changed if p not in OWN and not p.startswith(BOARD_PREFIX)]
    return [("G-UNTOUCHED", f"{p} differs from the merge base", "spec", "(tree)") for p in bad]


def g_budget(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    if t.spec.count("\n") > SPEC_BUDGET:
        out.append(("G-BUDGET", f"the spec exceeds {SPEC_BUDGET} lines", "spec", "(file)"))
    if t.hand.count("\n") > HAND_BUDGET:
        out.append(("G-BUDGET", f"the hand-off exceeds {HAND_BUDGET} lines", "hand", "(file)"))
    return out


def g_mutlist(t: Texts) -> list[Finding]:
    have = [r[:3] for r in first_table(t.spec, "## 15.")[1:]]
    want = [[m.mid, m.what, m.gate] for m in MUTATIONS]
    if have != want:
        return [
            ("G-MUTLIST", "§15 differs from the tool's list", "spec", section(t.spec, "## 15.")[2])
        ]
    return []


APPLY_HEAD = ["A", "Target", "Applied by"]


def a_ids(cell: str) -> list[str]:
    """The A-row ids of a §B cell: `D06-A1 … D06-A7, D06-A12` expands the range."""
    out: list[str] = []
    for part in cell.split(","):
        m = re.fullmatch(r"\s*D06-A(\d+)(?:\s*…\s*D06-A(\d+))?\s*", part)
        if not m:
            return [f"?{part.strip()}"]
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        out += [f"D06-A{n}" for n in range(lo, hi + 1)]
    return out


def g_apply(t: Texts) -> list[Finding]:
    _, _, region = section(t.hand, "## §B")
    rows = first_table(t.hand, "## §B")
    bad: list[str] = []
    if not rows or rows[0] != APPLY_HEAD:
        bad.append("the §B header is not A | Target | Applied by")
    want = [r[0] for r in first_table(t.hand, "## §C")[1:]]
    seen: list[str] = []
    for r in rows[1:]:
        if len(r) != 3:
            bad.append(f"the §B row {r[0]} has {len(r)} cells, not 3")
            continue
        seen += a_ids(r[0])
        if AGENT_RE.search(r[2]) or not OWNER_OK_RE.search(r[2]):
            bad.append(f"the §B row {r[0]} names no ticket or owner as its applier")
    if sorted(seen) != sorted(want):
        bad.append("§B does not name every §C A-row exactly once")
    return [("G-APPLY", b, "hand", region) for b in bad]


def findings(t: Texts, values: Values) -> list[Finding]:
    out: list[Finding] = []
    out += g_anchor(t, values) + g_marker(t) + g_cite(t) + g_quote(t) + g_arow(t)
    out += g_pending(t) + g_ruled(t) + g_pin(t) + g_boards(t) + g_inv(t) + g_parity(t)
    out += g_cols(t) + g_cap(t) + g_t2(t) + g_findings(t)
    out += g_lines(t, "G-NOCLAIM", lambda ln: bool(CLAIM_RE.search(ln)), "a canvas claim")
    out += g_lines(t, "G-PUBLIC", lambda ln: bool(URL_RE.search(ln)), "a URL, host or path")
    out += g_lines(t, "G-UNMERGED", lambda ln: bool(UNMERGED_RE.search(ln)), "an unmerged link")
    out += g_keyword(t) + g_heur(t) + g_walk(t) + g_owner(t) + g_untouched(t)
    out += g_budget(t) + g_mutlist(t) + g_apply(t)
    return out


# ---------------------------------------------------------------------------- run


def report(fs: list[Finding], quiet: bool = False) -> list[str]:
    """One FAIL line per gate; a pin finding while another gate FAILs in the BQ section is NOTE."""
    others = {r for g, _, _, r in fs if g != "G-RULED"}
    lines: list[str] = []
    gates: dict[str, list[Finding]] = {}
    for f in fs:
        if f[0] == "G-RULED" and f[3] in others:
            if not quiet:
                lines.append(f"NOTE G-RULED {f[1]} (another gate FAILs here)")
            continue
        gates.setdefault(f[0], []).append(f)
    for gate, items in gates.items():
        lines.append(
            f"FAIL {gate}: {len(items)} finding(s); first: {items[0][1]} [{items[0][3][:60]}]"
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
    s, e, _ = section(t.spec, "## 15.")
    lines = t.spec.split("\n")
    table = [i for i in range(s, e) if lines[i].startswith("|")]
    if table:
        lines[table[0] : table[-1] + 1] = mutation_rows().split("\n")
        t = replace(t, spec="\n".join(lines))
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


def repin(t: Texts) -> int:
    if PLACEHOLDER_RE.search(t.spec + t.hand) or "{{MUTATIONS" in t.spec:
        print("FAIL --repin-ruled refuses while a placeholder is unfilled")
        return 1
    rows = bq_lines(t.spec)
    head = (
        f"# E47-D06 pins: the BQ section of the spec, verbatim, in order; {len(rows)} lines.\n"
        "# Written by `--repin-ruled` only; `--check` reads it (never hand-edit; G-RULED).\n"
    )
    (ROOT / PIN_REL).write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"wrote {PIN_REL}: {len(rows)} lines")
    return 0


def self_test() -> int:
    t = read_texts()
    digest = hashlib.sha256((t.spec + t.hand).encode()).hexdigest()
    values = compute_values(t)
    base = [ln for ln in report(findings(t, values), quiet=True) if ln.startswith("FAIL")]
    if base:
        print("FAIL self-test: the baseline is not clean:", *base, sep="\n  ")
        return 1
    bad = 0
    for m in MUTATIONS:
        try:
            mt = apply_mutation(t, m)
        except AssertionError as exc:
            print(f"BAD  {m.mid} {m.gate} <- {m.what}: {exc}")
            bad += 1
            continue
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
    print(f"self-test: {len(MUTATIONS) - bad} of {len(MUTATIONS)} ok")
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
