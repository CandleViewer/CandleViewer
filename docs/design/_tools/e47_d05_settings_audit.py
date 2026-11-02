#!/usr/bin/env python3
"""E47-D05 (#1304) audit: the SCR-117 accessibility settings hi-fi spec (text first).

Standalone, offline, stdlib only; it executes no repo code and runs under `python3 -I`. It reads,
AS TEXT at the pinned base (`git show`): the plan texts, the shipped a11y-preferences slice and the
merged design texts the spec cites; the two in-flight blockers (E47-D03, E47-D04) at their pinned PR
heads; and, from the working tree, the spec `docs/design/E47/E47-D05.md`, its hand-off and the pins
file. Its form follows the E47-D04 tool (the same modes, anchored values, default-deny pins and
mutations).

1. **Values.** Every `{{KIND:key}}` placeholder is written by `--fill` as `VALUE<!--=KIND:key-->`
   (COUNT only: rows of the spec's and the hand-off's own tables). `--check` re-derives each
   anchored value (G-ANCHOR) and FAILs a placeholder left behind or a stray HTML comment
   (G-MARKER). `--fill` also writes the mutation rows ({{MUTATIONS}}) from this file's constants.
2. **Cites.** Every `NN`:line and KEY:line cite resolves to a non-blank line at the base, D03 / D04
   at their pinned heads (G-CITE); every "verbatim" copy string occurs on its cited line (G-QUOTE);
   every Old fragment of the hand-off's A-rows occurs verbatim on its cited line (G-AROW).
3. **Gates** (BQ-12 first, then the form): G-PIN (the start line names both pinned heads and their
   PRs; each commit exists and holds its file; a branch tip that moved past an unmerged pin FAILs),
   G-KEYS (the key list holds `22`'s eight keys with `22`'s values and the model's defaults, an
   Applies and a Consumer cell; every other key is PROPOSED with its default among its values),
   G-DESC (every key of §3 has a §4 row: a label, a description of at least six words that is not
   the label and does not start with it; a shipped key's label is a string on the shipped screen),
   G-STATES (the eleven states of BQ-9 exactly, each with what shows), G-COMP (every CMP id names
   a `15` heading, and its name word matches), G-CLASSES (§7.2's rows equal the six classes, each
   verbatim on `05`:152), G-T2 (the T2 paragraph once in §5.4 with every standing-gate element;
   every §0 / §8 / §10 / §11 line naming T2 cites §5.4; the hand-off's component line names CMP-079
   and CMP-019), G-PUBLIC (no URL, host, local path, worker name or secret-shaped string), G-PENDING
   (the heading names the ruling; BQ-0 … BQ-13 once each, "default built"; BQ-0 … BQ-10 open with
   "RULED (<ruling>)", BQ-11 … BQ-13 never say RULED), G-BOARDS
   (at most ten, every board pending, twins at most a third, the not-drawn paragraph, the hand-off's
   board plan the same boards), G-HEUR, G-WALK (at most ten), G-OWNER (G-ledger owners are tickets
   or owners, never an agent), G-UNTOUCHED (only this ticket's files differ from the merge base with
   origin/main), G-BUDGET, G-MUTLIST.
4. **Pins (G-RULED-PIN).** A whole-document default-deny pin set over every unit of both documents
   (heading, table row by lead cell, prose line, by heading path and occurrence, plus a line-shape
   unit per region) in `e47_d05_ruled_pins.txt`. Anchored values are cut out (G-ANCHOR owns them).
   `--repin-ruled` is the only writer and refuses while a placeholder is unfilled. A pin finding in
   a region another gate already FAILs prints as NOTE.
5. **--self-test** applies every mutation (M-n, spec §17) and pin probe (P-n, PROBES here) in memory with the values
   frozen at the filled baseline; each must add exactly one FAIL, from the gate it names; the texts
   on disk are checked byte-identical afterwards (sha256). Output is ASCII.

Usage (from the repo root):
  python3 -I docs/design/_tools/e47_d05_settings_audit.py --check [--fill]
  python3 -I docs/design/_tools/e47_d05_settings_audit.py --self-test
  python3 -I docs/design/_tools/e47_d05_settings_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "4c662fd5b"  # origin/main when the spec was written; every cite is read here

SPEC_REL = "docs/design/E47/E47-D05.md"
HAND_REL = "docs/design/E47/E47-D05-handoff.md"
TOOL_REL = "docs/design/_tools/e47_d05_settings_audit.py"
PIN_REL = "docs/design/_tools/e47_d05_ruled_pins.txt"
OWN = (SPEC_REL, HAND_REL, TOOL_REL, PIN_REL)
OWN_BOARDS = re.compile(r"docs/design/E47/img/E47-D05-\d\d-[a-z0-9-]+\.png")
SPEC_BUDGET = 460
HAND_BUDGET = 150


@dataclass(frozen=True)
class Pin:
    key: str
    sha: str
    rel: str
    branch: str
    pr: int


# The in-flight blockers, read at their PR heads (R6); re-pinned to the merge commit at merge.
PINS = (
    Pin("D03", "10eb2a345", "docs/design/E47/E47-D03.md", "design/e47-themes-contrast", 5392),
    Pin("D04", "1ff5d8cb9", "docs/design/E47/E47-D04.md", "design/e47-d04-focus-landmarks", 5387),
)

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "12": "docs/plan/12-sitemap.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
}
A11Y_PREFS = "apps/web/src/features/a11y-preferences"
CITE_FILES = {
    "D09E09": "docs/design/E09/E09-D09.md",
    "MODEL": f"{A11Y_PREFS}/model.ts",
    "ASS": f"{A11Y_PREFS}/AccessibilitySettingsScreen.tsx",
    "PCX": f"{A11Y_PREFS}/PreferencesContext.tsx",
    "MTS": "apps/web/e2e/motion-toggle.spec.ts",
    "S07": "docs/design/E47/E47-S07.md",
    "CAT": "docs/plan/a11y/47-audit-catalogue.md",
    "README": "docs/design/README.md",
    "D03": PINS[0].rel,
    "D04": PINS[1].rel,
}
FILE_BASE = {p.rel: p.sha for p in PINS}

BQ_COMMENT = "6566520929"  # the BQ list on #1304
RULING = "6566806435"  # the orchestrator's rulings of record on BQ-0 … BQ-10
BQ_HEAD = f"RULED (comment {RULING}, on the BQ list {BQ_COMMENT})"
BQ_IDS = tuple(f"BQ-{n}" for n in range(14))
BQ_RULED = frozenset(f"BQ-{n}" for n in range(11))  # the ruling names BQ-0 … BQ-10 only
BQ_DEFAULT = "default built"
PENDING_CELL = "pending: drawn later in this PR"
THEMES = ("dark", "light", "hc", "mixed")

KEYS_SPAN = (23351, 23358)  # `22`'s accessibility subtree at BASE
MODEL_DEFAULTS_SPAN = (19, 28)  # MODEL's DEFAULT_PREFERENCES at BASE
CLASSES_LINE = 152  # `05`:152, the assertive classes
CLASSES = (
    "order filled",
    "order rejected",
    "position auto-flattened by risk engine",
    "rule triggered",
    "WS disconnected/reconnected",
    "Demo/Live environment switch confirmed",
)
STATES = (
    "default",
    "following-system",
    "os-changed-while-open",
    "modified",
    "section-reset-preview",
    "search-results",
    "forced-colours",
    "loading",
    "load-error",
    "save-failed",
    "saved",
)
T2_LEAD = "**The T2 paragraph"
T2_NAMES = (
    "CMP-079 RbacGate",
    "CMP-019 Icon `lock`",
    "rendering 2a",
    "full label",
    '`aria-disabled="true"`',
    "never `disabled`",
    "in the DOM at mount",
    "`aria-describedby`",
    "one polite announcement",
    "`↑` / `↓`",
)
T2_CITERS = ("## 0.", "## 8.", "## 10.", "## 11.")

AGENT_RE = re.compile(r"worker|orchestrator|\bagent\b|\blane\b", re.IGNORECASE)
OWNER_OK_RE = re.compile(r"\bE\d\d-[A-Z]+\d\d \(#\d+\)|\bowner")
PUBLIC_RE = re.compile(
    r"https?://|www\.|/home/|/tmp/|localhost|\.local\b|\b[a-z0-9-]+\.(?:com|io|org|net|dev)\b"
    r"|hcl-worker|hpe-worker|\bAnvil\b|main-orchestrator|scratch-anvil|relayroom"
    r"|ghp_|github_pat_|\bsk-[A-Za-z0-9]{8}|\bAKIA[0-9A-Z]{8}",
    re.IGNORECASE,
)

Finding = tuple[str, str, str, str]  # gate, message, doc, region
Values = dict[str, str]


# ---------------------------------------------------------------------------- git and files


def git(*args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=check,
    ).stdout


def git_ok(*args: str) -> bool:
    return (
        subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        ).returncode
        == 0
    )


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


def plain(cell: str) -> str:
    return cell.replace("`", "").strip()


# ---------------------------------------------------------------------------- anchors

ANCHOR_RE = re.compile(
    r"(?<![0-9A-Za-z.,])([0-9A-Za-z.,]+)<!--=([A-Z]+):([a-z0-9.\-]+)-->", re.DOTALL
)
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z]+):([a-z0-9.\-]+)\}\}")
ANCHOR_TAG_RE = re.compile(r"<!--=[A-Z]+:[a-z0-9.\-]+-->", re.DOTALL)


def cut_anchors(text: str) -> str:
    return ANCHOR_RE.sub(lambda m: f"<!--={m.group(2)}:{m.group(3)}-->", text)


# ---------------------------------------------------------------------------- derived facts


@functools.lru_cache(maxsize=1)
def contract_keys() -> dict[str, tuple[str, ...]]:
    """`22`'s accessibility keys and their values (booleans as true / false)."""
    out: dict[str, tuple[str, ...]] = {}
    lines = base_lines(PLAN["22"])[KEYS_SPAN[0] - 1 : KEYS_SPAN[1]]
    for ln in lines:
        m = re.match(r"^\s+(\w+): \{ type: (\w+)(?:, enum: \[([^\]]*)\])? \}", ln)
        if not m:
            continue
        if m.group(2) == "boolean":
            out[m.group(1)] = ("true", "false")
        else:
            out[m.group(1)] = tuple(v.strip().strip('"') for v in (m.group(3) or "").split(","))
    return out


@functools.lru_cache(maxsize=1)
def model_defaults() -> dict[str, str]:
    out: dict[str, str] = {}
    lines = base_lines(CITE_FILES["MODEL"])[MODEL_DEFAULTS_SPAN[0] - 1 : MODEL_DEFAULTS_SPAN[1]]
    for ln in lines:
        m = re.match(r'^\s+(\w+): "?([\w]+)"?,', ln)
        if m:
            out[m.group(1)] = m.group(2)
    return out


@functools.lru_cache(maxsize=1)
def cmp_names() -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in base_lines(PLAN["15"]):
        m = re.match(r"^### (CMP-\d{3}) (\S+)", ln)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def key_rows(spec: str) -> list[list[str]]:
    return [r for r in first_table(spec, "## 3.")[1:] if len(r) >= 6]


def desc_rows(spec: str) -> list[list[str]]:
    return [r for r in first_table(spec, "## 4.")[1:] if len(r) >= 3]


def board_rows(spec: str) -> list[list[str]]:
    return [r for r in first_table(spec, "## 0.")[1:] if len(r) >= 5]


def count_values(t: Texts) -> Values:
    keys = key_rows(t.spec)
    boards = board_rows(t.spec)
    return {
        "COUNT:boards": str(len(boards)),
        "COUNT:boards.twins": str(sum(1 for r in boards if r[3] != "dark")),
        "COUNT:keys": str(len(keys)),
        "COUNT:keys.shipped": str(sum(1 for r in keys if r[5] == "shipped")),
        "COUNT:keys.proposed": str(sum(1 for r in keys if r[5].startswith("PROPOSED"))),
        "COUNT:classes": str(len(first_table(t.spec, "### 7.2")[1:])),
        "COUNT:states": str(len(first_table(t.spec, "## 10.")[1:])),
        "COUNT:copy": str(len(first_table(t.spec, "## 15.")[1:])),
        "COUNT:heuristics": str(len(first_table(t.spec, "## 16.")[1:])),
        "COUNT:walkthrough": str(sum(1 for ln in body(t.hand, "## §E") if ln.startswith("- ["))),
    }


def compute_values(t: Texts) -> Values:
    return count_values(t)


# ---------------------------------------------------------------------------- mutations


@dataclass(frozen=True)
class Mutation:
    mid: str
    what: str
    gate: str
    doc: str  # spec | hand | changed
    where: str  # a heading prefix, "" for the whole text, "<eof>" to append
    old: str
    new: str


def _m(mid: str, what: str, gate: str, doc: str, where: str, old: str, new: str) -> Mutation:
    return Mutation(mid, what, gate, doc, where, old, new)


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "M-1",
        "draw an eleventh board in §0",
        "G-BOARDS",
        "spec",
        "## 0.",
        "| 10  | `E47-D05 / 10",
        "| 11  | `E47-D05 / 11 extra` | x | dark | pending: drawn later in this PR |\n"
        "| 10  | `E47-D05 / 10",
    ),
    _m(
        "M-2",
        "mark board 03 drawn in §0",
        "G-BOARDS",
        "spec",
        "## 0.",
        "| hc    | pending: drawn later in this PR",
        "| hc    | drawn",
    ),
    _m(
        "M-3",
        "drop the `verbosity` row from §3",
        "G-KEYS",
        "spec",
        "## 3.",
        "| `verbosity`",
        "| `verbosity_x`",
    ),
    _m(
        "M-4",
        "give `announce_prices` the default `off` in §3",
        "G-KEYS",
        "spec",
        "## 3.",
        "| `significant` | `shouldAnnounce`",
        "| `off` | `shouldAnnounce`",
    ),
    _m(
        "M-5",
        "make `keyboard_only`'s description its label in §4",
        "G-DESC",
        "spec",
        "## 4.",
        "Drag handles stop responding to the mouse; each shows fields and step buttons you use "
        "from the keyboard instead. Orders still ask you to confirm.",
        "Keyboard-only mode",
    ),
    _m(
        "M-6",
        "drop the search-results state from §10",
        "G-STATES",
        "spec",
        "## 10.",
        "| `SCR-117/search-results`",
        "| `SCR-117/search`",
    ),
    _m(
        "M-7",
        "name CMP-069 a Toggle in §14",
        "G-COMP",
        "spec",
        "## 14.",
        "CMP-069 InfoPanel",
        "CMP-069 Toggle",
    ),
    _m(
        "M-8",
        "re-word a significant class in §7.2",
        "G-CLASSES",
        "spec",
        "### 7.2",
        "| rule triggered",
        "| rule fired",
    ),
    _m(
        "M-9",
        "drop CMP-079 from §5.4's T2 paragraph",
        "G-T2",
        "spec",
        "### 5.4",
        "wrapped by CMP-079 RbacGate",
        "wrapped by a gate",
    ),
    _m(
        "M-10",
        "drop §5.4's cite from §10's forced-colours row",
        "G-T2",
        "spec",
        "## 10.",
        "the contrast row as T2 per §5.4's T2 paragraph",
        "the contrast row as T2",
    ),
    _m(
        "M-11",
        "drop CMP-019 from the hand-off's component list",
        "G-T2",
        "hand",
        "",
        "**CMP-019 Icon** `lock` glyph",
        "lock glyph",
    ),
    _m(
        "M-12",
        "write a host beside the Penpot file in §0",
        "G-PUBLIC",
        "spec",
        "## 0.",
        "Penpot file `E47-D05 boards` (README:14)",
        "Penpot file `E47-D05 boards` at design.example.com (README:14)",
    ),
    _m(
        "M-13",
        "unmark BQ-4's ruling",
        "G-PENDING",
        "spec",
        "## The questions",
        f"- **BQ-4** RULED ({RULING}): ",
        "- **BQ-4** ",
    ),
    _m(
        "M-14",
        "point a cite past the end of S07",
        "G-CITE",
        "spec",
        "## 0.",
        "(S07:3, :29–34)",
        "(S07:3, :29–340)",
    ),
    _m(
        "M-15",
        "re-word W-7",
        "G-QUOTE",
        "spec",
        "## 15.",
        '"Increase focus-ring thickness"',
        '"Increase focus ring thickness"',
    ),
    _m(
        "M-16",
        "re-word D05-A6's Old fragment",
        "G-AROW",
        "hand",
        "## §C",
        "| Theme, density, colour convention override, a11y prefs ",
        "| Theme, density, colour override, a11y prefs ",
    ),
    _m(
        "M-17",
        "change the D04 pin in the start line",
        "G-PIN",
        "spec",
        "",
        "`1ff5d8cb9` (E47-D04, PR #5387)",
        "`1ff5d8cb8` (E47-D04, PR #5387)",
    ),
    _m(
        "M-18",
        "drop `(heuristic)` from H-3",
        "G-HEUR",
        "spec",
        "## 16.",
        "| H-3 | (heuristic) Error",
        "| H-3 | Error",
    ),
    _m(
        "M-19",
        "add two walkthrough items in the hand-off's §E",
        "G-WALK",
        "hand",
        "## §E",
        "- [ ] Record `approved`",
        "- [ ] extra one.\n- [ ] extra two.\n- [ ] Record `approved`",
    ),
    _m(
        "M-20",
        "name an agent as D05-G5's owner",
        "G-OWNER",
        "spec",
        "### 18.2",
        "| E47-D13 (#1311)",
        "| the design worker",
    ),
    _m("M-21", "touch `22` in the working tree", "G-UNTOUCHED", "changed", "", "", PLAN["22"]),
    _m("M-22", "pad the spec past its line budget", "G-BUDGET", "spec", "<eof>", "", "\n" * 120),
    _m(
        "M-23",
        "change the boards count in the header",
        "G-ANCHOR",
        "spec",
        "",
        "10<!--=COUNT:boards--> boards of §0",
        "9<!--=COUNT:boards--> boards of §0",
    ),
    _m(
        "M-24",
        "leave a placeholder unfilled",
        "G-MARKER",
        "spec",
        "## 3.",
        "11<!--=COUNT:keys--> keys",
        "{{COUNT:keys}} keys",
    ),
    _m(
        "M-25",
        "replace a mutation row's gate in §17",
        "G-MUTLIST",
        "spec",
        "## 17.",
        "| M-1  | draw an eleventh board in §0 | G-BOARDS |",
        "| M-1  | draw an eleventh board in §0 | G-STATES |",
    ),
)
PROBES: tuple[Mutation, ...] = (
    _m(
        "P-1",
        "flip a prose sentence in §5.3",
        "G-RULED-PIN",
        "spec",
        "### 5.3",
        "keeps it and gets the line",
        "loses it and gets the line",
    ),
    _m(
        "P-2",
        "re-word a hand-off summary item",
        "G-RULED-PIN",
        "hand",
        "## §I",
        "never a live region",
        "rarely a live region",
    ),
)


def mutation_rows(ms: tuple[Mutation, ...] = MUTATIONS) -> str:
    head = "| M    | Mutation | Gate |\n| ---- | -------- | ---- |\n"
    return head + "\n".join(f"| {m.mid} | {m.what} | {m.gate} |" for m in ms)


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
            if "<!--" in ANCHOR_TAG_RE.sub("", line):
                out.append(("G-MARKER", f"a stray HTML comment on line {i + 1}", doc, regions[i]))
    return out


CITE_RE = re.compile(
    r"(?:`(\d\d)`|\b(" + "|".join(CITE_FILES) + r"))(:\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)"
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


def g_pin(t: Texts) -> list[Finding]:
    lines, regions = t.spec.split("\n"), line_regions(t.spec)
    start = [i for i, ln in enumerate(lines) if ln.startswith("**Start.**")]
    region = regions[start[0]] if len(start) == 1 else "(top)#1"
    line = lines[start[0]] if len(start) == 1 else ""
    bad: list[str] = []
    ticket = {"D03": "E47-D03", "D04": "E47-D04"}
    for p in PINS:
        if f"`{p.sha}` ({ticket[p.key]}, PR #{p.pr})" not in line:
            bad.append(f"the start line does not pin {p.key} at {p.sha} (PR #{p.pr})")
        if not git_ok("cat-file", "-e", f"{p.sha}:{p.rel}"):
            bad.append(f"{p.sha}:{p.rel} is not readable")
            continue
        merged = git_ok("merge-base", "--is-ancestor", p.sha, "origin/main")
        for ref in (f"refs/remotes/origin/{p.branch}", f"refs/heads/{p.branch}"):
            tip = git("rev-parse", "--verify", "-q", ref, check=False).strip()
            if tip and not tip.startswith(p.sha) and not merged:
                bad.append(f"{p.key}'s branch moved past {p.sha}; re-pin (R6)")
                break
    return [("G-PIN", b, "spec", region) for b in bad]


def g_keys(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 3.")
    rows = {plain(r[0]): r for r in key_rows(t.spec)}
    want, defaults = contract_keys(), model_defaults()
    bad: list[str] = []
    if len(want) != 8:
        bad.append(f"`22` yields {len(want)} keys, not eight")
    for key, values in want.items():
        r = rows.get(key)
        if r is None:
            bad.append(f"`22`'s {key} has no row")
            continue
        got = tuple(plain(v) for v in r[1].split(" / "))
        if set(got) != set(values):
            bad.append(f"{key}'s values {got} are not `22`'s {values}")
        if plain(r[2]) != defaults.get(key):
            bad.append(f"{key}'s default {plain(r[2])} is not the model's {defaults.get(key)}")
        if not r[3] or not r[4] or r[5] != "shipped":
            bad.append(f"{key} lacks Applies, Consumer or the shipped status")
    for key, r in rows.items():
        if key in want:
            continue
        got = tuple(plain(v) for v in r[1].split(" / "))
        if not r[5].startswith("PROPOSED") or plain(r[2]) not in got or not r[3] or not r[4]:
            bad.append(f"{key} is not a complete PROPOSED row")
    return [("G-KEYS", b, "spec", region) for b in bad]


def g_desc(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 4.")
    rows = {plain(r[0]): r for r in desc_rows(t.spec)}
    shipped = at_base(CITE_FILES["ASS"])
    bad: list[str] = []
    for r in key_rows(t.spec):
        key = plain(r[0])
        if key not in contract_keys() and not r[5].startswith("PROPOSED"):
            continue  # G-KEYS owns a row that is neither `22`'s nor PROPOSED
        d = rows.get(key)
        if d is None:
            bad.append(f"{key} has no description row")
            continue
        label, desc = d[1].strip(), d[2].strip()
        if not label or len(desc.split()) < 6:
            bad.append(f"{key} lacks a label or a description")
        elif desc.lower() == label.lower() or desc.lower().startswith(label.lower()):
            bad.append(f"{key}'s description restates its label")
        if r[5] == "shipped" and f'"{label}"' not in shipped:
            bad.append(f"{key}'s label is not the shipped string")
    return [("G-DESC", b, "spec", region) for b in bad]


def g_states(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 10.")
    rows = first_table(t.spec, "## 10.")[1:]
    got = tuple(plain(r[0]).removeprefix("SCR-117/") for r in rows)
    bad: list[str] = []
    if got != STATES:
        bad.append(f"the states are {got}, not BQ-9's")
    bad += [f"{r[0]} shows nothing" for r in rows if len(r) < 3 or not r[1]]
    return [("G-STATES", b, "spec", region) for b in bad]


def g_comp(t: Texts) -> list[Finding]:
    names = cmp_names()
    out: list[Finding] = []
    for doc in ("spec", "hand"):
        text = t.doc(doc)
        regions = line_regions(text)
        for i, line in enumerate(text.split("\n")):
            for m in re.finditer(r"\b(CMP-\d{3})(?:(?:\*\*)? (?:\*\*)?([A-Z][A-Za-z]+))?", line):
                cid, name = m.group(1), m.group(2)
                if cid not in names:
                    out.append(("G-COMP", f"{cid} has no `15` heading", doc, regions[i]))
                elif name and not (names[cid].startswith(name) or name.startswith(names[cid])):
                    out.append(("G-COMP", f"{cid} is {names[cid]}, not {name}", doc, regions[i]))
    return out


def g_classes(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "### 7.2")
    got = tuple(r[0] for r in first_table(t.spec, "### 7.2")[1:])
    source = base_lines(PLAN["05"])[CLASSES_LINE - 1]
    bad: list[str] = []
    if got != CLASSES:
        bad.append("§7.2's classes differ from `05`:152's six")
    bad += [f"{c!r} is not on `05`:152" for c in CLASSES if c not in source]
    return [("G-CLASSES", b, "spec", region) for b in bad]


def g_t2(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    s, e, region = section(t.spec, "### 5.4")
    para = [ln for ln in t.spec.split("\n") if T2_LEAD in ln]
    inside = [ln for ln in t.spec.split("\n")[s:e] if T2_LEAD in ln]
    if len(para) != 1 or len(inside) != 1:
        out.append(("G-T2", f"the T2 paragraph is stated {len(para)} times", "spec", region))
    else:
        out += [
            ("G-T2", f"the T2 paragraph does not name {n}", "spec", region)
            for n in T2_NAMES
            if n not in para[0]
        ]
    for prefix in T2_CITERS:
        s2, e2, reg = section(t.spec, prefix)
        for ln in t.spec.split("\n")[s2:e2]:
            if re.search(r"\bT2\b", ln) and "§5.4" not in ln:
                out.append(("G-T2", f"a {prefix} line shows T2 without citing §5.4", "spec", reg))
    lines, regions = t.hand.split("\n"), line_regions(t.hand)
    comp = [i for i, ln in enumerate(lines) if ln.startswith("Components: ")]
    if len(comp) != 1 or not all(x in lines[comp[0]] for x in ("CMP-079 RbacGate", "CMP-019")):
        reg = regions[comp[0]] if len(comp) == 1 else ""
        out.append(("G-T2", "the hand-off's component line omits CMP-079 or CMP-019", "hand", reg))
    return out


def g_pending(t: Texts) -> list[Finding]:
    s, e, region = section(t.spec, "## The questions")
    head = t.spec.split("\n")[s - 1] if s else ""
    lines = t.spec.split("\n")[s:e]
    bad: list[str] = []
    if BQ_HEAD not in head:
        bad.append("the heading does not name the ruling and the BQ list")
    for bq in BQ_IDS:
        rows = [ln for ln in lines if ln.startswith(f"- **{bq}**")]
        if len(rows) != 1:
            bad.append(f"{bq} appears {len(rows)} times")
        elif BQ_DEFAULT not in rows[0]:
            bad.append(f"{bq} is not marked '{BQ_DEFAULT}'")
        elif bq in BQ_RULED and not rows[0].startswith(f"- **{bq}** RULED ({RULING}): “"):
            bad.append(f"{bq} does not open with its ruling, quoted")
        elif bq not in BQ_RULED and re.search(r"\bRULED\b|ruled as", rows[0]):
            bad.append(f"{bq} is outside the ruling but marked ruled")
    return [("G-PENDING", b, "spec", region) for b in bad]


def g_boards(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 0.")
    rows = board_rows(t.spec)
    bad: list[str] = []
    if not 1 <= len(rows) <= 10:
        bad.append(f"{len(rows)} boards")
    if [r[0] for r in rows] != [f"{n:02d}" for n in range(1, len(rows) + 1)]:
        bad.append("the boards are not numbered 01 onward")
    for r in rows:
        if r[3] not in THEMES or r[4] != PENDING_CELL or not r[2]:
            bad.append(f"board {r[0]} is not a pending board with a theme and a draw list")
    if 3 * sum(1 for r in rows if r[3] != "dark") > len(rows):
        bad.append("twins exceed a third")
    if not any(
        ln.startswith("**Not drawn — the text is binding**") for ln in body(t.spec, "## 0.")
    ):
        bad.append("the not-drawn paragraph is missing")
    plan = [r[0] for r in first_table(t.hand, "## §H")[1:]]
    if plan != [r[0] for r in rows]:
        bad.append("the hand-off's board plan differs from §0")
    return [("G-BOARDS", b, "spec", region) for b in bad]


def g_heur(t: Texts) -> list[Finding]:
    _, _, region = section(t.spec, "## 16.")
    return [
        ("G-HEUR", f"{r[0]} is not marked (heuristic)", "spec", region)
        for r in first_table(t.spec, "## 16.")[1:]
        if len(r) < 2 or not r[1].startswith("(heuristic)")
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
        "# E47-D05 pins (every unit of the spec and the hand-off): doc, region (heading path"
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
    out += g_anchor(t, values) + g_marker(t) + g_cite(t) + g_quote(t) + g_arow(t) + g_pin(t)
    out += g_keys(t) + g_desc(t) + g_states(t) + g_comp(t) + g_classes(t) + g_t2(t)
    out += g_lines(t, "G-PUBLIC", lambda ln: bool(PUBLIC_RE.search(ln)), "a host, path or name")
    out += g_pending(t) + g_boards(t) + g_heur(t) + g_walk(t) + g_owner(t)
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
