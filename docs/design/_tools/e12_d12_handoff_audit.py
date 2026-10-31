#!/usr/bin/env python3
"""E12-D12 (#313) audit: the engineering hand-off pack for the bar-builder and series-rendering
band (SCR-030, SCR-031, SCR-041, SCR-042, SCR-045, SCR-047, SCR-048).

Standalone, offline, stdlib only; it runs under `python3 -I` and executes no repo code. It reads AS
TEXT at the pinned base `BASE` (`git show`): the plan texts, the merged E12 design docs (D02 ... D09,
the hand-offs and the bar-mode registry), the E11 and E16 packs the file cites, the token JSON, the
RBAC seed, the calendar and the E11 / E12 backlog JSON; then the pack (`E12-D12.md`), the deck
(`E12-D12-copy.json`), `14` and the pins from the working tree. Nothing unmerged is read.

Values. Every `{{KIND:key}}` outside a code span is computed and `--fill` writes it as
`VALUE<!--=KIND:key-->`; a `{{COPY:key}}` line becomes the source block between
`<!-- COPY:key -->` and `<!-- /COPY:key -->`, byte-equal to its source at the base. `--check`
re-derives every anchored value and every copied block; no placeholder may remain.

Gates (one mutation each in `--self-test`; each is caught by a content gate):
  G-VALUES     the anchored SHA, STATUS and CITE values; a CITE is read from its defining line.
  G-LIFT       every HASH anchor equals the sha256 (12 hex) of its lifted spans, whitespace-normalised.
  G-COPY       every COPY block equals its source block (a section body or one line) at the base.
  G-CITE       every `KEY`:line cite is in range at the base and its ends are non-blank.
  G-VERSION    every cited line stands at `origin/main` (moved = WARN, gone = FAIL).
  G-MODES      the per-mode table against the registry cell by cell, and its rows against `22`'s
               `BarType` enum (its own definition line); the recorded-prints column from the ruled
               vocabulary.
  G-BIND       the binding audit: every named source is found at its own definition line (a REST
               schema property, a `getBars` parameter, a `BarsBatch` item property); the Served
               column is derived; a partial or absent source names a gap held in the register, and
               an absent one is never handed over as buildable.
  G-SURFACES   the seven entries carry the nine rows; every E11-D09 row range cited is a set of
               rows of that screen; every page name is a parent's page.
  G-STORYBOOK  the component index against `15`'s headings and D09's story counts; the token
               manifest through `themes.json`; every token the pack names is shipped or listed with
               an owner.
  G-DECK       the deck equals the derivation from the five parents' deck tables (each entry
               anchored at its own row); every deck reference resolves.
  G-BUDGETS    each budget's numbers stand on its cited defining line, in the ruled units; each gate
               is a `26` §13 id on its own table row, a ruled story, or "no gate yet" with a G-row;
               the 58-fps row cites `26` and names C-14.2, which the constitution defines.
  G-MOTION     each motion row cites merged rows or reads "no merged source" with a held G-row; the
               comment line for #245 is unposted and names exactly the rows without a source.
  G-EVENTS     each event name stands in backticks on its cited parent line; every `T`-named event is
               present; nothing is marked emitted; the export row carries its G-row.
  G-ROLES      the role matrix is frozen (a changed cell FAILs); the permission codes are the seed's;
               every `rbac.*` key and quoted verb stands on its cited lines; S-1 and S-3 read their
               values from the defining lines of `22`.
  G-T2         the T2 rule's terms (G-T2.1c, .1d, .6) and CMP-079 RbacGate with the CMP-019 `lock` on
               SCR-041 and on every entry whose control is gated.
  G-AHEAD      the sprint, date, margin and reading values from the calendar and the backlog JSON.
  G-OPENROWS   every register range's ends are rows of the cited parent lines; every D12 id the pack
               names is a row of §16.2 with a ruled grade and a non-agent owner.
  G-UNTOUCHED  PR-1 mode: the tree differs from the merge-base only in this pack's files and `14`,
               and `14` equals the merge-base with the pointer lines and the ticks applied by
               content. Post-merge mode: `14` is untouched.
  G-TICKS      every tick's evidence resolves at its source (a section heading, a board, a deck row)
               and the pack's evidence table lists exactly the ticks applied.
  G-FROZEN     post-merge mode: every merged version row stands; a new row is v1.N above the last.
  G-RULED      the ruling stamp, the ruling id, BQ-01..BQ-23, the owner-approval line.
  G-HYGIENE    no placeholder, stray HTML comment, closing keyword outside a code span, local path,
               agent name, host, URL or public-text word.
  G-RULED-PIN  a default-deny pin set over every unit of the pack (values cut out, copies
               collapsed), every deck entry and every cite's line hash; only `--repin-ruled` writes
               it. Its findings print as NOTE while another gate FAILs.

Usage (from the repo root):
  python3 -I docs/design/_tools/e12_d12_handoff_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e12_d12_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e12_d12_handoff_audit.py --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "16d70feed9"  # the base of record: every cite was read here (the version line)
HEAD_REF = "origin/main"
VERSION_DATE = datetime.date(2026, 10, 31)  # v1's date: the design-ahead readings count from it
ISSUE = "313"
RULING_ID = "6548253695"
STAMP = "RULED (orchestrator, 2026-10-31, #313 ruling of record — 6548253695)"
BQ_TOTAL = 23

SPEC_REL = "docs/design/E12/E12-D12.md"
DECK_REL = "docs/design/E12/E12-D12-copy.json"
TOOL_REL = "docs/design/_tools/e12_d12_handoff_audit.py"
PIN_REL = "docs/design/_tools/e12_d12_ruled_pins.txt"
PLAN14_REL = "docs/plan/14-screens-catalogue.md"
OWN_PATHS = (SPEC_REL, DECK_REL, TOOL_REL, PIN_REL, PLAN14_REL)
DS_SRC = "packages/ui/tokens"
IMG_REL = "docs/design/E12/img"
CONSTITUTION_REL = "CONSTITUTION.md"

PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": PLAN14_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "26": "docs/plan/26-chart-engine-design.md",
    "30": "docs/plan/30-release-roadmap.md",
    "D02": "docs/design/E12/E12-D02.md",
    "D03": "docs/design/E12/E12-D03.md",
    "D03H": "docs/design/E12/E12-D03-handoff.md",
    "D04": "docs/design/E12/E12-D04.md",
    "D04H": "docs/design/E12/E12-D04-handoff.md",
    "D05": "docs/design/E12/E12-D05.md",
    "D05H": "docs/design/E12/E12-D05-handoff.md",
    "D06": "docs/design/E12/E12-D06.md",
    "D06H": "docs/design/E12/E12-D06-handoff.md",
    "D07": "docs/design/E12/E12-D07.md",
    "D07H": "docs/design/E12/E12-D07-handoff.md",
    "D08": "docs/design/E12/E12-D08.md",
    "D08H": "docs/design/E12/E12-D08-handoff.md",
    "D09": "docs/design/E12/E12-D09.md",
    "REG": "docs/design/E12/E12-D09-barmodes.json",
    "E11D04": "docs/design/E11/E11-D04.md",
    "E11D06": "docs/design/E11/E11-D06.md",
    "E11P": "docs/design/E11/E11-D09.md",
    "E16D06": "docs/design/E16/E16-D06.md",
    "SEED": "services/api/candleviewer/auth/rbac_seed.json",
    "CAL": "docs/plan/backlog/_tools/calendar_cv.py",
    "E12J": "docs/plan/backlog/E12.json",
    "E11J": "docs/plan/backlog/E11.json",
}
PARENTS = ("D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09")
THEMES = ("dark", "light", "hc")

# the blocks copied byte for byte: key -> (source, "head" | "line", the heading or line prefix)
COPIES: dict[str, tuple[str, str, str]] = {
    "d03.s2": ("D03", "head", "## 2. "),
    "d06.s5": ("D06", "head", "## 5. "),
    "d06.s63": ("D06", "head", "### 6.3 "),
    "d08.s91": ("D08", "head", "### 9.1 "),
    "d08.s3": ("D08", "head", "## 3. "),
    "23.confirm": ("23", "line", "- **Unconfirmed bars.**"),
    "d08.s72": ("D08", "head", "### 7.2 "),
    "d02.s10": ("D02", "head", "## 10. "),
}
# the blocks lifted by hash: key -> spans (source, start heading or "" for the whole file, end)
LIFTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "d02.s7_8": (("D02", "## 7. ", "## 9. "),),
    "d06.s3_4": (("D06", "## 3. ", "## 5. "),),
    "d06.s7": (("D06", "## 7. ", ""),),
    "d06.s13": (("D06", "## 13. ", ""),),
    "d06.s14": (("D06", "## 14. ", ""),),
    "a11y.parents": (("D03", "## 8. ", ""), ("D04", "## 14. ", ""), ("D05", "## 11. ", ""),
                     ("D07", "## 11. ", ""), ("D08", "## 10. ", "")),
    "d07.s6": (("D07", "## 6. ", ""),),
    "d09.s5_7": (("D09", "## 5. ", "## 8. "),),
    "d09.s10_11": (("D09", "## 10. ", "## 12. "),),
    "reg": (("REG", "", ""),),
    "handoffs": tuple((k, "", "") for k in ("D03H", "D04H", "D05H", "D06H", "D07H", "D08H")),
}  # fmt: skip
# CITE values: key -> (source, the defining line's needle, the figure's pattern)
CITES: dict[str, tuple[str, str, str]] = {
    **{f"stories.cmp{n}": ("D09", f"<!--=COUNT:stories.cmp{n}-->",
                           rf"(\d+)<!--=COUNT:stories\.cmp{n}-->")
       for n in ("181", "220", "222", "226", "248")},
    "d09.log": ("D09", "<!--=COUNT:log.ids-->", r"(\d+)<!--=COUNT:log\.ids-->"),
}  # fmt: skip
# the backlog keys whose sprints the design-ahead record reads: key -> (backlog, value key)
SPRINT_KEYS: dict[str, tuple[str, str]] = {
    "E12-S06": ("E12J", "s06"), "E12-S10": ("E12J", "s10"), "E12-S09": ("E12J", "s09"),
    "E12-S11": ("E12J", "s11"), "E12-D13": ("E12J", "d13"), "E12-S07": ("E12J", "s07"),
    "E12-S08": ("E12J", "s08"), "E12-S12": ("E12J", "s12"), "E12-Q03": ("E12J", "q03"),
    "E12-Q07": ("E12J", "q07"), "E12-D12": ("E12J", "d12"), "E11-S13": ("E11J", "e11s13"),
    "E11-S14": ("E11J", "e11s14"),
}  # fmt: skip
CONSUMERS = ("s06", "s10", "s09", "s11", "d13", "s07", "s08", "s12", "q03", "q07", "e11s13",
             "e11s14")  # fmt: skip
# the five parent decks: id prefix -> (source, heading prefix, owner of every entry)
DECKS: dict[str, tuple[str, str, str]] = {
    "d03": ("D03", "## 5. ", "E12-D03 (#201)"),
    "d04": ("D04", "## 15. ", "E12-D04 (#240)"),
    "d05": ("D05", "## 12. ", "E12-D05 (#241)"),
    "d07": ("D07", "## 13. ", "E12-D07 (#242)"),
    "d08": ("D08", "## 11. ", "E12-D08 (#243)"),
}

# the `14` lines (RULED BQ-22): one pointer at the end of each of the seven entries, and the ticks
# applied by content to each entry's design sign-off checklist line (a tick only with evidence)
POINTER = (
    "- **Hand-off pack (E12 bar series):** [E12-D12.md](../design/E12/E12-D12.md) v1 (E12-D12; "
    "owner approval pending)."
)
SCREENS = ("SCR-030", "SCR-031", "SCR-041", "SCR-042", "SCR-045", "SCR-047", "SCR-048")
CHECKLIST_PREFIX = "- **Design sign-off acceptance checklist:** "
TICKS: dict[str, tuple[tuple[str, str], ...]] = {
    "SCR-045": (("column set and sorting drawn", "E12-D07 §3; boards 01, 02, 03"),),
    "SCR-047": (
        (("three distinct reasons drawn (never recorded / no data in this range / instrument not "
          "trading)"), "E12-D02 §8; boards 31, 35, 36; E12-D08 §2.2"),
        ("owner CTA to SCR-140 and non-owner explanatory copy both drawn",
         "E12-D02 §8; boards 33, 34; E12-D08 §2.3"),
        ("live-data-still-works note present where true", "E12-D08 §2.4; W-12"),
        ("no infinite spinner path", "E12-D08 §1.4, §2.4"),
    ),
    "SCR-048": (
        ("distinct copy for engine/WebGL failure, data-feed failure and backend failure",
         "E12-D08 §4.1; E12-D02 §8; boards 38, 39"),
        ("correlation id copyable", "E12-D08 §4.2"),
        ("retry + 'open diagnostics' actions", "E12-D08 §4.1, §5, §10.4"),
        ("the rest of the workspace remains usable", "E12-D08 §4.3"),
    ),
}  # fmt: skip
TICK_DOCS = {f"E12-D0{n}": f"D0{n}" for n in range(2, 10)}

# the per-mode table's ruled vocabulary (RULED BQ-07)
PRINTS = {"time": "no"}  # every other offered mode reads "yes"; a mode not offered reads "—"
# the binding audit's Served vocabulary
SERVED = ("REST and WS", "REST only", "WS only", "neither")
# the budgets' ruled units and gates (RULED BQ-15)
UNITS = ("fps", "ms", "s", "MB", "draws")
GATE_STORIES = ("E12-S06", "E12-S07", "E12-S11", "E12-S12", "E12-T07", "E11-S14")
# the analytics events `T Scope` names (RULED BQ-17)
T_EVENTS = (
    "chart.interval_changed", "chart.bar_mode_changed", "chart.symbol_changed",
    "chart.settings_changed", "chart.empty_state_shown", "chart.error_shown",
    "chart.data_table_opened", "chart.data_table_exported", "chart.bar_rebuild_started",
    "chart.bar_rebuild_completed", "chart.bar_rebuild_cancelled",
)  # fmt: skip
# the surface entries: heading prefix -> (screen, the E11-D09 surface word)
SURFACES: dict[str, str] = {
    "### 2.1 ": "SCR-030", "### 2.2 ": "SCR-031", "### 2.3 ": "SCR-041", "### 2.4 ": "SCR-042",
    "### 2.5 ": "SCR-045", "### 2.6 ": "SCR-047", "### 2.7 ": "SCR-048",
}  # fmt: skip
SURFACE_ROWS = ("Build source of record", "Frames", "States with precedence", "Tokens",
                "A11y and axe", "Budgets", "Analytics", "Acceptance notes", "Components")  # fmt: skip
GRADES = {"Blocking": "p0", "Major": "p1", "Minor": "p2", "Info": "p3"}
OWNER_PENDING = "owner approval pending (#2701)"
COMMENT_245 = "**Comment for #245, to post at this pack's merge (not posted here):**"
T2_TERMS = ('`aria-disabled="true"`', "never `disabled`", "`aria-describedby`", "CMP-079 RbacGate",
            "CMP-019 `lock`", "`decorative={false}`", '"Not available"', "in the DOM at mount")  # fmt: skip

PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+?)\}\}")
# a value is one code span or one run of value characters: never a leading bracket or quote, so a
# refresh cannot eat the punctuation in front of a value
ANCHORED = re.compile(r"(`[^`\n]*`|[^\s<|`(\[\"']+)<!--=([A-Z]+:[^>]+?)-->")
COPY_LINE = re.compile(r"^\{\{COPY:([a-z0-9._]+)\}\}$")
COPY_BLOCK = re.compile(
    r"^<!-- COPY:([a-z0-9._]+) -->\n.*?\n<!-- /COPY:\1 -->$", re.MULTILINE | re.DOTALL
)
CODE = re.compile(r"`[^`\n]*`")
HEADING = re.compile(r"^(#{1,6}) (.+)$")
RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
CITE = re.compile(r"`(" + "|".join(re.escape(k) for k in sorted(PATHS, key=len, reverse=True))
                  + r")`:(\d+)(?:[–-](\d+))?")  # fmt: skip
CONT = re.compile(r"^(?:,\s*|\s+and\s+):(\d+)(?:[–-](\d+))?")
DECK_REF = re.compile(r"`(d0[3-8]:[A-Z]+-\d+(?:#\d+)?)`")
TOKEN_NAME = re.compile(
    r"^(?:color|size|space|radius|type|opacity|border|elevation|motion|dash|pattern)\.[a-z0-9.\-]+$"
)
D12_ID = re.compile(r"\bD12-[GC]\d+\b")
RANGE = re.compile(r"(?<![\w-])([A-Z][A-Z0-9-]*\d)\.\.([A-Z][A-Z0-9-]*\d)(?![\w-])")
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
# assembled, so the patterns never spell the strings they refuse
LOCAL_PATH = re.compile("/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b")
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-" + "worker" + r"-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
_W = ("le" + "ak", "expo" + "sed", "by" + "pass", "expl" + "oit", "att" + "ack", "ora" + "cle",
      "rev" + "eal", "unbou" + "nded", "flo" + "od", "sta" + "ll", "d" + "os", "advi" + "sory",
      "gh" + "sa", "pre-" + "auth")  # fmt: skip
WORDS = re.compile("|".join(_W), re.IGNORECASE)


# ---------------------------------------------------------------------------- git and caches


def git_raw(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def git_ok(*args: str) -> bool:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return False
    return r.returncode == 0


def merge_base() -> str | None:
    out = git_raw("merge-base", "HEAD", HEAD_REF)
    return out.strip() if out and re.fullmatch(r"[0-9a-f]{40}\s*", out) else None


def changed_paths(base: str) -> list[str] | None:
    """Committed and uncommitted paths that differ from the merge-base; None when git fails."""
    a = git_raw("diff", "--name-only", base)
    b = git_raw("status", "--porcelain", "--untracked-files=all")
    if a is None or b is None:
        return None
    out = {p for p in a.split("\n") if p}
    for ln in b.split("\n"):
        if len(ln) > 3:
            out.add(ln[3:].split(" -> ")[-1].strip('"'))
    return sorted(out)


@dataclass
class Env:
    base: str  # the full sha of BASE
    mb: str  # the merge-base with origin/main
    memo: dict[str, object]

    def show(self, rev: str, rel: str) -> str | None:
        key = f"show:{rev}:{rel}"
        if key not in self.memo:
            self.memo[key] = git_raw("show", f"{rev}:{rel}")
        v = self.memo[key]
        return v if isinstance(v, str) else None

    def at_base(self, rel: str) -> str:
        t = self.show(self.base, rel)
        if t is None:
            raise SystemExit(f"{rel} is missing at the base {self.base[:10]}")
        return t

    def lines(self, rev: str, rel: str) -> list[str]:
        t = self.show(rev, rel)
        return t.split("\n") if t is not None else []

    def tree(self, rev: str, prefix: str) -> list[str]:
        key = f"tree:{rev}:{prefix}"
        if key not in self.memo:
            out = git_raw("ls-tree", "-r", "--name-only", rev, "--", prefix) or ""
            self.memo[key] = [p for p in out.split("\n") if p]
        v = self.memo[key]
        return v if isinstance(v, list) else []

    def grep(self, rev: str, pattern: str, paths: tuple[str, ...]) -> bool:
        key = f"grep:{rev}:{pattern}:{paths}"
        if key not in self.memo:
            out = git_raw("grep", "-l", "-F", "-e", pattern, rev, "--", *paths)
            self.memo[key] = bool(out and out.strip())
        return bool(self.memo[key])


def read_raw(rel: str) -> str:
    with open(ROOT / rel, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(rel: str, text: str) -> None:
    with open(ROOT / rel, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ---------------------------------------------------------------------------- text helpers


def pin_norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def split_row(line: str) -> list[str]:
    body = line.strip().removeprefix("|")
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def tables(block: str) -> list[list[tuple[int, list[str]]]]:
    """The tables of a block, each a list of (0-based line index in the block, cells), rule rows
    dropped, the header row kept first."""
    out: list[list[tuple[int, list[str]]]] = []
    cur: list[tuple[int, list[str]]] = []
    for i, ln in enumerate(block.split("\n")):
        if ln.lstrip().startswith("|"):
            if not RULE.match(ln):
                cur.append((i, split_row(ln)))
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def table_after(block: str, header0: str) -> list[list[str]]:
    """The body rows of the first table whose first header cell is `header0`."""
    for t in tables(block):
        if t and t[0][1] and t[0][1][0] == header0:
            return [c for _, c in t[1:]]
    return []


def header_of(block: str, header0: str) -> list[str]:
    for t in tables(block):
        if t and t[0][1] and t[0][1][0] == header0:
            return t[0][1]
    return []


def span(lines: list[str], head: str, end: str = "") -> tuple[int, int]:
    """[start, stop) of the section whose heading starts with `head`: up to `end`'s heading when
    given, else to the next heading of the same or a higher level; (-1, -1) when absent."""
    if not head:
        return 0, len(lines)
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if m and ln.startswith(head):
            level = len(m[1])
            j = i + 1
            while j < len(lines):
                m2 = HEADING.match(lines[j])
                if end and lines[j].startswith(end):
                    break
                if not end and m2 and len(m2[1]) <= level:
                    break
                j += 1
            return i, j
    return -1, -1


def section(text: str, head: str) -> str:
    ls = text.split("\n")
    a, b = span(ls, head)
    return "\n".join(ls[a:b]) if a >= 0 else ""


def own_section(text: str, head: str) -> str:
    """A section of this pack with its copied blocks collapsed (a copy may hold a heading)."""
    return section(collapse_copies(text), head)


def body_of(text: str, head: str) -> str | None:
    """A section's body: the lines after its heading, leading and trailing blank lines cut."""
    ls = text.split("\n")
    a, b = span(ls, head)
    if a < 0:
        return None
    body = ls[a + 1 : b]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body)


def without_code(text: str) -> str:
    return CODE.sub("`…`", text)


def collapse_copies(text: str) -> str:
    return COPY_BLOCK.sub(lambda m: "{{COPY:" + m[1] + "}}", text)


def unfill(text: str) -> str:
    """The text with every anchored value back to its placeholder and every copy collapsed."""
    text = collapse_copies(text)
    return ANCHORED.sub(lambda m: "{{" + m[2] + "}}", text)


def anchored(text: str) -> list[tuple[str, str, int]]:
    text = collapse_copies(text)
    return [
        (m[1], m[2], i) for i, ln in enumerate(text.split("\n"), 1) for m in ANCHORED.finditer(ln)
    ]


def unfilled(text: str) -> list[str]:
    """Every placeholder outside a code span and outside a filled copy (a COPY line included)."""
    text = COPY_BLOCK.sub("", text)
    return [m[1] for ln in text.split("\n") for m in PLACEHOLDER.finditer(without_code(ln))]


def strip_value(cell: str) -> str:
    """A cell with its anchors cut back to the bare value."""
    return re.sub(r"<!--=[A-Z]+:[^>]+?-->", "", cell).strip()


def word_in(needle: str, text: str) -> bool:
    """`needle` as whole words in `text` (no letter or digit on either side)."""
    return bool(re.search(r"(?<![\w])" + re.escape(needle) + r"(?![\w])", text))


# ---------------------------------------------------------------------------- tokens


def layering(env: Env) -> dict[str, tuple[str, ...]]:
    data = json.loads(env.at_base(f"{DS_SRC}/themes.json"))
    out: dict[str, tuple[str, ...]] = {}
    for th in data.get("themes", []) if isinstance(data, dict) else []:
        if isinstance(th, dict) and th.get("group") == "theme":
            name = {"high-contrast": "hc"}.get(str(th.get("name")), str(th.get("name")))
            out[name] = tuple(str(x) for x in th.get("sets", []))
    return out


def theme(env: Env, name: str) -> dict[str, str]:
    key = f"theme:{name}"
    if key not in env.memo:
        merged: dict[str, str] = {}
        for f in layering(env).get(name, ()):
            data = json.loads(env.at_base(f"{DS_SRC}/{f}.tokens.json"))
            for k, v in data.items() if isinstance(data, dict) else []:
                if isinstance(v, dict) and "$value" in v:
                    merged[k] = v["$value"] if isinstance(v["$value"], str) else "(composite)"
        env.memo[key] = merged
    out = env.memo[key]
    return out if isinstance(out, dict) else {}


def token_status(env: Env, name: str) -> str:
    """`shipped` when the name resolves in every theme through the layering, else `absent`."""
    themes = layering(env)
    if not themes:
        return "absent"
    return "shipped" if all(name in theme(env, t) for t in THEMES if t in themes) else "absent"


# ---------------------------------------------------------------------------- the texts


@dataclass(frozen=True)
class Texts:
    env: Env
    spec: str
    deck: str
    pins: str
    plan14: str
    changed: list[str] | None
    values: dict[str, str]
    ticks: dict[str, tuple[tuple[str, str], ...]]  # a field, so a mutation can move them


def doc_text(t: Texts, key: str) -> str:
    return t.env.at_base(PATHS[key])


# ---------------------------------------------------------------------------- cites


def cites_in(text: str) -> list[tuple[str, int, int, int]]:
    """(key, first, last, 1-based line in the text) of every cite outside the copied blocks."""
    out: list[tuple[str, int, int, int]] = []
    text = collapse_copies(text)
    for n, ln in enumerate(text.split("\n"), 1):
        for m in CITE.finditer(ln):
            a = int(m[2])
            out.append((m[1], a, int(m[3]) if m[3] else a, n))
            pos = m.end()
            while True:
                c = CONT.match(ln[pos:])
                if not c:
                    break
                a2 = int(c[1])
                out.append((m[1], a2, int(c[2]) if c[2] else a2, n))
                pos += c.end()
    return out


def cited_text(t: Texts, cell: str) -> str:
    """The lines a cell cites, at the base, joined."""
    parts: list[str] = []
    for key, a, b, _ in cites_in(cell):
        ls = t.env.lines(t.env.base, PATHS[key])
        parts.extend(ls[a - 1 : b])
    return "\n".join(parts)


# ---------------------------------------------------------------------------- values


def calendar(env: Env) -> tuple[datetime.date | None, int | None]:
    src = env.at_base(PATHS["CAL"])
    m = re.search(r"SPRINT01_START\s*=\s*datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)", src)
    d = re.search(r"^SPRINT_DAYS\s*=\s*(\d+)", src, re.MULTILINE)
    return (datetime.date(int(m[1]), int(m[2]), int(m[3])) if m else None, int(d[1]) if d else None)


def sprints(env: Env) -> dict[str, int]:
    out: dict[str, int] = {}
    for src in ("E12J", "E11J"):
        data = json.loads(env.at_base(PATHS[src]))
        items = data if isinstance(data, list) else []
        for it in items:
            if not isinstance(it, dict):
                continue
            hit = SPRINT_KEYS.get(str(it.get("key")))
            if hit and hit[0] == src:
                m = re.search(r"(\d+)", str(it.get("sprint", "")))
                if m:
                    out[hit[1]] = int(m[1])
    return out


def ahead_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    start, days = calendar(env)
    sp = sprints(env)
    if not start or not days:
        return vals
    passed = 0
    for k, n in sp.items():
        vals[f"SPRINT:{k}"] = f"{n:02d}"
        first = start + datetime.timedelta(days=(n - 1) * days)
        ahead = first - datetime.timedelta(days=2 * days)
        vals[f"DATE:{k}.start"] = first.isoformat()
        vals[f"DATE:{k}.ahead"] = ahead.isoformat()
        vals[f"DAYS:margin.{k}"] = str((first - VERSION_DATE).days)
        vals[f"AHEAD:{k}"] = "passed" if ahead < VERSION_DATE else "open"
        if k in CONSUMERS and ahead < VERSION_DATE:
            passed += 1
    vals["COUNT:ahead.passed"] = str(passed)
    return vals


def cite_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    for key, (src, needle, pat) in CITES.items():
        hits = [ln for ln in env.lines(env.base, PATHS[src]) if needle in ln]
        found = [m[1] for ln in hits for m in [re.search(pat, ln)] if m]
        if len(found) == 1:
            vals[f"CITE:{key}"] = found[0]
    return vals


def cmp_heading(env: Env, n: str) -> str | None:
    """`15`'s heading line for CMP-n at the base (its own definition), or None."""
    for ln in env.lines(env.base, PATHS["15"]):
        if re.match(rf"^#{{2,4}} CMP-{n} ", ln):
            return ln
    return None


def status_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    vals["STATUS:engine.candle"] = (
        "present"
        if env.grep(env.base, "CandleSeries", ("packages/chart-engine/src",))
        else "absent"
    )
    vals["STATUS:engine.layers"] = str(len(env.tree(env.base, "packages/chart-engine/src/layers")))
    feats = {
        p.split("/")[4] for p in env.tree(env.base, "apps/web/src/features") if p.count("/") > 4
    }
    e12 = sorted(
        f for f in feats if re.search(r"settings|bar-?mode|interval|series|data-?table", f)
    )
    vals["STATUS:web.e12"] = "present" if e12 else "absent"
    vals["STATUS:web.errors"] = "present" if "chart-errors" in feats else "absent"
    for k, rel in (("d11.file", "docs/design/E12/E12-D11.md"),
                   ("d10.file", "docs/design/E12/E12-D10.md")):  # fmt: skip
        vals[f"STATUS:{k}"] = "present" if env.show(env.base, rel) is not None else "absent"
    pngs = [p for p in env.tree(env.base, IMG_REL) if p.rsplit("/", 1)[-1].startswith("E12-D08-")]
    vals["STATUS:d08.boards"] = str(len(pngs))
    for n in ("181", "220", "222", "226", "248", "079", "019", "041", "069", "008"):
        vals[f"STATUS:cmp.{n}"] = "listed" if cmp_heading(env, n) else "absent"
    return vals


def lift_hash(t: Texts, key: str) -> str | None:
    parts: list[str] = []
    for src, head, end in LIFTS[key]:
        ls = t.env.at_base(PATHS[src]).split("\n")
        a, b = span(ls, head, end)
        if a < 0:
            return None
        parts.append("\n".join(pin_norm(x) for x in ls[a:b]))
    return sha12("\n".join(parts))  # whitespace-normalised: a table re-padded keeps its hash


def token_names(text: str) -> list[str]:
    names: list[str] = []
    for m in re.finditer(r"`([a-z][a-z0-9.\-]+)`", collapse_copies(text)):
        if TOKEN_NAME.match(m[1]):
            names.append(m[1])
    return list(dict.fromkeys(names))


def walk_items(spec: str) -> int:
    return sum(1 for ln in own_section(spec, "### 17.1 ").split("\n") if re.match(r"^\d+\. ", ln))


def checklist_items(env: Env, plan14: str) -> int:
    """The design sign-off items of the seven entries in a `14` text."""
    n = 0
    for scr in SCREENS:
        a, b = entry_span(plan14.split("\n"), scr)
        for ln in plan14.split("\n")[a:b] if a >= 0 else []:
            if ln.startswith(CHECKLIST_PREFIX):
                n += len(re.findall(r"\[[ x]\] ", ln))
    return n


def entry_span(ls: list[str], scr: str) -> tuple[int, int]:
    a = next((i for i, ln in enumerate(ls) if ln.startswith(f"### {scr} ")), -1)
    if a < 0:
        return -1, -1
    b = next((i for i in range(a + 1, len(ls)) if ls[i].startswith(("### ", "## "))), len(ls))
    return a, b


def compute(t: Texts) -> dict[str, str]:
    env = t.env
    vals: dict[str, str] = {"SHA:base": env.base[:10]}
    vals.update(status_values(env))
    vals.update(cite_values(env))
    vals.update(ahead_values(env))
    for k in LIFTS:
        h = lift_hash(t, k)
        if h:
            vals[f"HASH:{k}"] = h
    for name in token_names(t.spec):
        vals[f"TOKEN:{name}"] = token_status(env, name)
    reg = registry(env)
    vals["COUNT:modes.offered"] = str(sum(bool(m.get("offered")) for m in reg))
    rows = bind_rows(t.spec)
    served = {r[0]: served_value(env, r) for r in rows if len(r) >= 8}
    for fid, v in served.items():
        vals[f"BIND:{fid.lower().replace('-', '')}"] = v
    vals["COUNT:bind.rows"] = str(len(rows))
    plain = [v.strip("`") for v in served.values()]
    vals["COUNT:bind.both"] = str(plain.count("REST and WS"))
    vals["COUNT:bind.one"] = str(plain.count("REST only") + plain.count("WS only"))
    vals["COUNT:bind.none"] = str(plain.count("neither"))
    ev = event_rows(t.spec)
    vals["COUNT:events.rows"] = str(len(ev))
    vals["COUNT:events.ticket"] = str(sum(len(r) > 3 and r[3] == "T" for r in ev))
    vals["COUNT:events.parent"] = str(sum(len(r) > 3 and r[3] == "parent" for r in ev))
    vals["COUNT:deck.total"] = str(len(deck_entries(env)))
    vals["COUNT:walk.items"] = str(walk_items(t.spec))
    vals["COUNT:ticks.here"] = str(sum(len(v) for v in t.ticks.values()))
    vals["COUNT:ticks.items"] = str(checklist_items(env, env.show(env.mb, PLAN14_REL) or ""))
    return vals


# ---------------------------------------------------------------------------- the registry


def registry(env: Env) -> list[dict[str, object]]:
    data = json.loads(env.at_base(PATHS["REG"]))
    modes = data.get("modes", []) if isinstance(data, dict) else []
    return [m for m in modes if isinstance(m, dict)]


def bar_types(env: Env) -> list[str]:
    """`22`'s `BarType` enum, read from the enum line under its own schema heading."""
    ls = env.lines(env.base, PATHS["22"])
    a = next((i for i, ln in enumerate(ls) if ln == "    BarType:"), -1)
    for ln in ls[a + 1 : a + 4] if a >= 0 else []:
        m = re.match(r"^\s+enum: \[(.*)\]\s*$", ln)
        if m:
            return [x.strip() for x in m[1].split(",")]
    return []


def mode_rows(spec: str) -> list[list[str]]:
    return table_after(own_section(spec, "## 4. "), "`bar_type`")


# ---------------------------------------------------------------------------- the deck


def derive_deck(env: Env) -> dict[str, object]:
    key = "deck:derived"
    if key in env.memo:
        v = env.memo[key]
        return v if isinstance(v, dict) else {}
    entries: dict[str, dict[str, object]] = {}
    for prefix, (src, head, owner) in DECKS.items():
        text = env.at_base(PATHS[src])
        a, _ = span(text.split("\n"), head)
        block = section(text, head)
        for tb in tables(block):
            hdr = tb[0][1]
            if "String" not in hdr:
                continue
            col = {h: i for i, h in enumerate(hdr)}
            for idx, cells in tb[1:]:
                ident = cells[0]

                def cell(
                    name: str, cells: list[str] = cells, col: dict[str, int] = col
                ) -> str | None:
                    i = col.get(name)
                    return (
                        cells[i].replace("\\|", "|") if i is not None and i < len(cells) else None
                    )

                entry: dict[str, object] = {"text": cell("String") or "",
                                            "source": f"{src}:{a + idx + 1}", "owner": owner}  # fmt: skip
                for name, field in (("Where", "where"), ("Source", "source_cell"),
                                    ("Status", "status"), ("Tag", "tag")):  # fmt: skip
                    v = cell(name)
                    if v is not None:
                        entry[field] = v
                eid, n = f"{prefix}:{ident}", 1
                while eid in entries:  # an id a parent repeats on a second row
                    n += 1
                    eid = f"{prefix}:{ident}#{n}"
                entries[eid] = entry
            break
    out: dict[str, object] = {
        "pack": "E12-D12",
        "version": "v1",
        "base": BASE,
        "note": (
            "The copy deck of the E12-D12 hand-off pack: every row of the five parents' decks "
            "(E12-D03 §5, E12-D04 §15, E12-D05 §12, E12-D07 §13, E12-D08 §11) under the id "
            "`<parent>:<row id>` (`#2` on an id the parent repeats), the String cell verbatim, the "
            "source row, the parent's own Where, Source, Status or Tag cell where it has one, and "
            "the owner: the parent ticket, which owns every PROPOSED string it wrote. Checked by "
            "docs/design/_tools/e12_d12_handoff_audit.py (G-DECK)."
        ),
        "entries": entries,
    }
    env.memo[key] = out
    return out


def deck_entries(env: Env) -> dict[str, dict[str, object]]:
    ent = derive_deck(env).get("entries", {})
    return (
        {str(k): v for k, v in ent.items() if isinstance(v, dict)} if isinstance(ent, dict) else {}
    )


# ---------------------------------------------------------------------------- the binding audit


def bind_rows(spec: str) -> list[list[str]]:
    return table_after(own_section(spec, "## 10. "), "F")


def block_lines(ls: list[str], start: str, stop: str) -> list[str]:
    """The lines from the one equal to `start` to the next line matching `stop`."""
    a = next((i for i, ln in enumerate(ls) if ln == start), -1)
    if a < 0:
        return []
    b = next((i for i in range(a + 1, len(ls)) if re.match(stop, ls[i])), len(ls))
    return ls[a:b]


def source_found(env: Env, name: str) -> bool:
    """A named source at its own definition line at the base."""
    owner, _, field = name.partition(".")
    if not field:
        return False
    if owner == "BarsBatch":
        ls = env.lines(env.base, PATHS["23"])
        a, b = span(ls, "### 14.3 ")
        return a >= 0 and any(re.match(rf'^\s*"{re.escape(field)}": ', ln) for ln in ls[a:b])
    ls = env.lines(env.base, PATHS["22"])
    if owner == "getBars":
        blk = block_lines(ls, "  /market/bars:", r"^  /")
        return any(re.match(rf"^\s+- name: {re.escape(field)}\s*$", ln) for ln in blk)
    if owner in ("Bar", "Instrument", "InstrumentDetail"):
        blk = block_lines(ls, f"    {owner}:", r"^    \S")
        return any(re.match(rf"^\s+{re.escape(field)}:", ln) for ln in blk)
    return False


def names_in(cell: str) -> list[str]:
    return re.findall(r"`([A-Za-z]+\.[a-z_]+)`", cell)


def served_value(env: Env, row: list[str]) -> str:
    rest, ws = names_in(row[3]), names_in(row[4])
    r_ok = bool(rest) and all(source_found(env, n) for n in rest)
    w_ok = bool(ws) and all(source_found(env, n) for n in ws)
    v = {(True, True): SERVED[0], (True, False): SERVED[1], (False, True): SERVED[2],
         (False, False): SERVED[3]}[(r_ok, w_ok)]  # fmt: skip
    return f"`{v}`"


# ---------------------------------------------------------------------------- other tables


def event_rows(spec: str) -> list[list[str]]:
    return table_after(own_section(spec, "## 13. "), "Event")


def role_rows(spec: str) -> list[list[str]]:
    return table_after(own_section(spec, "### 14.1 "), "R")


def budget_rows(spec: str) -> list[list[str]]:
    return table_after(own_section(spec, "## 11. "), "B")


def motion_rows(spec: str) -> list[list[str]]:
    return table_after(own_section(spec, "## 9. "), "M")


def own_rows(spec: str) -> list[list[str]]:
    return table_after(own_section(spec, "### 16.2 "), "Id")


def evidence_rows(spec: str) -> list[list[str]]:
    return table_after(own_section(spec, "### 20.2 "), "Screen")


def register_ids(spec: str) -> tuple[set[str], list[tuple[str, str, str]]]:
    """The ids §16 holds: its own rows' ids and the parents' ranges (prefix, low, high)."""
    ids = {r[0] for r in own_rows(spec)}
    ranges: list[tuple[str, str, str]] = []
    for r in table_after(own_section(spec, "### 16.1 "), "Ids"):
        for lo, hi in RANGE.findall(r[0]):
            p = re.sub(r"\d+$", "", lo)
            ranges.append((p, lo, hi))
        ids |= set(re.findall(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-?\d+\b", r[0]))
    return ids, ranges


def in_register(spec: str, ident: str) -> bool:
    ids, ranges = register_ids(spec)
    if ident in ids:
        return True
    m = re.fullmatch(r"(.*?)(\d+)", ident)
    if not m:
        return False
    for p, lo, hi in ranges:
        if p == m[1] and re.sub(r"\d+$", "", hi) == p:
            a, b = int(lo[len(p) :]), int(hi[len(p) :])
            if a <= int(m[2]) <= b:
                return True
    return False


# ---------------------------------------------------------------------------- placeholders


def fill(text: str, values: dict[str, str], copies: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []
    out: list[str] = []
    for ln in collapse_copies(text).split("\n"):
        m = COPY_LINE.match(ln)
        if m:
            if m[1] in copies:
                out.append(f"<!-- COPY:{m[1]} -->\n\n{copies[m[1]]}\n\n<!-- /COPY:{m[1]} -->")
            else:
                missing.append(f"COPY:{m[1]}")
                out.append(ln)
            continue

        def refresh(mm: re.Match[str]) -> str:
            return f"{values[mm[2]]}<!--={mm[2]}-->" if mm[2] in values else mm[0]

        ln = ANCHORED.sub(refresh, ln)
        spans = [(c.start(), c.end()) for c in CODE.finditer(ln)]

        def ph(mm: re.Match[str], spans: list[tuple[int, int]] = spans) -> str:
            if any(a <= mm.start() < b for a, b in spans):
                return mm[0]
            if mm[1] not in values:
                missing.append(mm[1])
                return mm[0]
            return f"{values[mm[1]]}<!--={mm[1]}-->"

        out.append(PLACEHOLDER.sub(ph, ln))
    return "\n".join(out), missing


def copy_sources(env: Env) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, (src, kind, loc) in COPIES.items():
        text = env.at_base(PATHS[src])
        if kind == "head":
            body = body_of(text, loc)
            if body is not None:
                out[k] = body
        else:
            hits = [ln for ln in text.split("\n") if ln.startswith(loc)]
            if len(hits) == 1:
                out[k] = hits[0]
    return out


def apply14(base14: str, ticks: dict[str, tuple[tuple[str, str], ...]]) -> tuple[str, list[str]]:
    """The merge-base's `14` with the ticks and the seven pointer lines applied by content."""
    ls = base14.split("\n")
    bad: list[str] = []
    for scr in SCREENS:
        a, b = entry_span(ls, scr)
        if a < 0:
            bad.append(f"`14` has no {scr} entry")
            continue
        ck = [i for i in range(a, b) if ls[i].startswith(CHECKLIST_PREFIX)]
        for item, ev in ticks.get(scr, ()):
            box = f"[ ] {item}"
            if len(ck) != 1 or ls[ck[0]].count(box) != 1:
                bad.append(f"{scr}: the unticked item {item[:40]!r} is not found once in `14`")
                continue
            ls[ck[0]] = ls[ck[0]].replace(box, f"[x] {item} ({ev})")
        last = max((i for i in range(a, b) if ls[i].strip()), default=a)
        ls.insert(last + 1, POINTER)
    return "\n".join(ls), bad


# ---------------------------------------------------------------------------- pins

Unit = tuple[str, str, str]


def units(text: str, doc: str) -> list[Unit]:
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    region, k, shape = f"{doc}:(top)#1", 0, ""
    rows: dict[str, int] = {}
    for raw in unfill(text).split("\n"):
        m = HEADING.match(raw)
        if m:
            out.append((region, "shape", shape))
            level = len(m[1])
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m[2]))]
            key = f"{doc}:" + " > ".join(p[1] for p in path)
            seen[key] = seen.get(key, 0) + 1
            region, k, shape, rows = f"{key}#{seen[key]}", 0, "h", {}
            out.append((region, "heading", pin_norm(raw)))
            continue
        if not raw.strip():
            shape += "."
        elif RULE.match(raw):
            shape += "r"
        elif raw.lstrip().startswith("|"):
            shape += "t"
            cells = split_row(raw)
            lead = pin_norm(cells[0]) or "(blank)"
            rows[lead] = rows.get(lead, 0) + 1
            loc = f"row {lead}" + (f"#{rows[lead]}" if rows[lead] > 1 else "")
            out.append((region, loc, " | ".join(pin_norm(c) for c in cells)))
        else:
            sents = [x for x in FULL_STOP.split(raw.strip()) if x.strip()]
            shape += f"p{len(sents)}"
            for x in sents:
                k += 1
                out.append((region, f"s{k}", pin_norm(x)))
    out.append((region, "shape", shape))
    return out


def deck_units(deck: str) -> list[Unit]:
    try:
        data = json.loads(deck)
    except json.JSONDecodeError:
        return [("deck", "json", "unparseable")]
    out: list[Unit] = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k != "entries":
                out.append(("deck", k, pin_norm(json.dumps(v, ensure_ascii=False, sort_keys=True))))
        ent = data.get("entries", {})
        for k, v in ent.items() if isinstance(ent, dict) else []:
            out.append(
                ("deck:entries", k, pin_norm(json.dumps(v, ensure_ascii=False, sort_keys=True)))
            )
    return out


def cite_units(t: Texts) -> list[Unit]:
    out: dict[str, str] = {}
    for key, a, b, _ in cites_in(t.spec):
        ls = t.env.lines(t.env.base, PATHS[key])
        if 0 < a <= b <= len(ls):
            lab = f"{key}:{a}" if a == b else f"{key}:{a}-{b}"
            out[lab] = sha12(pin_norm(ls[a - 1]) + "\n" + pin_norm(ls[b - 1]))
    return [("cite", k, v) for k, v in sorted(out.items())]


def all_units(t: Texts) -> list[Unit]:
    return units(t.spec, "spec") + deck_units(t.deck) + cite_units(t)


def write_pins(us: list[Unit]) -> str:
    head = (
        f"# E12-D12 pins: {len(us)} units (region, location, the normalised text; values cut out, "
        "copied blocks collapsed), the deck entries and the cites' line hashes at the base.\n"
        "# Written by `--repin-ruled` only; `--check` reads it (G-RULED-PIN). Never hand-edit.\n"
    )
    return head + "".join("\t".join(u) + "\n" for u in us)


def parse_pins(text: str) -> list[Unit]:
    out: list[Unit] = []
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def pin_problems(pinned: list[Unit], current: list[Unit]) -> list[str]:
    bad: list[str] = []
    was = {(u[0], u[1]): u[2] for u in pinned}
    now = {(u[0], u[1]): u[2] for u in current}
    for k, v in now.items():
        if k not in was:
            bad.append(f"unpinned unit {k[0][-50:]} / {k[1]}: {v[:40]!r}")
        elif was[k] != v:
            bad.append(f"changed unit {k[0][-50:]} / {k[1]}: {v[:40]!r}")
    for k in was:
        if k not in now:
            bad.append(f"deleted unit {k[0][-50:]} / {k[1]}")
    if not bad and [u[:2] for u in pinned] != [u[:2] for u in current]:
        bad.append("the pinned units moved (the order changed)")
    return bad


# ---------------------------------------------------------------------------- findings


@dataclass(frozen=True)
class Finding:
    level: str
    gate: str
    msg: str


def one(gate: str, problems: list[str], level: str = "FAIL") -> list[Finding]:
    return [Finding(level, gate, p) for p in problems]


ANCHOR_GATE = (
    ("HASH:", "G-LIFT"),
    ("COUNT:modes", "G-MODES"),
    ("BIND:", "G-BIND"), ("COUNT:bind", "G-BIND"),
    ("TOKEN:", "G-STORYBOOK"), ("STATUS:cmp.", "G-STORYBOOK"), ("CITE:stories", "G-STORYBOOK"),
    ("COUNT:deck", "G-DECK"),
    ("COUNT:events", "G-EVENTS"),
    ("SPRINT:", "G-AHEAD"), ("DATE:", "G-AHEAD"), ("DAYS:", "G-AHEAD"), ("AHEAD:", "G-AHEAD"),
    ("COUNT:ahead", "G-AHEAD"),
    ("COUNT:ticks", "G-TICKS"),
    ("COUNT:walk", "G-OPENROWS"),
)  # fmt: skip


def anchor_gate(key: str) -> str:
    for prefix, gate in ANCHOR_GATE:
        if key.startswith(prefix):
            return gate
    return "G-VALUES"


def anchor_problems(t: Texts, gate: str) -> list[str]:
    bad: list[str] = []
    for value, key, ln in anchored(t.spec):
        if anchor_gate(key) != gate:
            continue
        want = t.values.get(key)
        if want is None:
            bad.append(f"spec:{ln} anchors `{key}`, which the tool does not compute")
        elif want != value:
            bad.append(f"spec:{ln} `{key}` reads {value}; the tool derives {want}")
    return bad


# ---------------------------------------------------------------------------- gates


def g_values(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-VALUES")
    for key in CITES:
        if f"CITE:{key}" not in t.values:
            bad.append(f"CITE:{key}: its defining line is not found once at the base")
    return one("G-VALUES", bad)


def g_lift(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-LIFT")
    for k in LIFTS:
        if f"HASH:{k}" not in t.values:
            bad.append(f"HASH:{k}: a lifted span is missing at the base")
    return one("G-LIFT", bad)


def g_copy(t: Texts) -> list[Finding]:
    bad: list[str] = []
    want = copy_sources(t.env)
    for m in COPY_BLOCK.finditer(t.spec):
        key = m[1]
        body = m[0].split("\n", 1)[1].rsplit("\n", 1)[0].strip("\n")
        if key not in want:
            bad.append(f"COPY:{key} has no source at the base")
        elif body != want[key]:
            bad.append(f"COPY:{key} differs from its source at the base")
    keys = [m[1] for m in COPY_BLOCK.finditer(t.spec)]
    for k in COPIES:
        if keys.count(k) != 1:
            bad.append(f"COPY:{k} appears {keys.count(k)} times (once expected)")
    return one("G-COPY", bad)


def g_cite(t: Texts) -> list[Finding]:
    bad: list[str] = []
    if not git_ok("merge-base", "--is-ancestor", t.env.base, "HEAD"):
        bad.append(f"the base {BASE} is not an ancestor of HEAD")
    for key, a, b, n in cites_in(t.spec):
        ls = t.env.lines(t.env.base, PATHS[key])
        if not (0 < a <= b <= len(ls)):
            bad.append(f"spec:{n} `{key}`:{a}-{b} is out of range ({len(ls)} lines)")
        elif not ls[a - 1].strip() or not ls[b - 1].strip():
            bad.append(f"spec:{n} `{key}`:{a}-{b} ends on a blank line")
    return one("G-CITE", bad)


def g_version(t: Texts) -> list[Finding]:
    out: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    for key, a, b, n in cites_in(t.spec):
        base = t.env.lines(t.env.base, PATHS[key])
        head = t.env.lines(HEAD_REF, PATHS[key])
        for k in sorted({a, b}):
            if (key, k) in seen or not (0 < k <= len(base)):
                continue
            seen.add((key, k))
            line = base[k - 1]
            if k <= len(head) and head[k - 1] == line:
                continue
            if line in head:
                out.append(Finding("WARN", "G-VERSION", f"`{key}`:{k} moved at {HEAD_REF}"))
            else:
                out.append(
                    Finding("FAIL", "G-VERSION", f"spec:{n} `{key}`:{k} is gone at {HEAD_REF}")
                )
    return out


def g_modes(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-MODES")
    rows = {r[0].strip("`"): r for r in mode_rows(t.spec) if len(r) >= 10}
    enum = bar_types(t.env)
    if not enum:
        bad.append("`22`'s `BarType` enum is not found at its definition")
    if sorted(rows) != sorted(enum):
        bad.append(f"the table's rows {sorted(rows)} are not `22`'s BarType {sorted(enum)}")
    deck = deck_entries(t.env)
    for m in registry(t.env):
        k = str(m.get("key"))
        r = rows.get(k)
        if r is None:
            bad.append(f"REG's `{k}` has no row")
            continue
        if not m.get("offered"):
            want = [str(m.get("label")), "not offered", "—", "—", "—", "—", "—",
                    "refused by the server", "—"]  # fmt: skip
        else:
            raw = m.get("message_keys")
            keys = [str(x) for x in raw] if isinstance(raw, list) else []
            want = [str(m.get("label")), str(m.get("description_key")), str(m.get("field_label")),
                    str(m.get("unit") or "—"), str(m.get("first_use_default")), ", ".join(keys),
                    PRINTS.get(k, "yes"), f"`bar_type={k}` + `param`", f"`.{k}.`"]  # fmt: skip
            for ck in [str(m.get("description_key")), *keys]:
                if f"d03:{ck}" not in deck:
                    bad.append(f"`{k}`: {ck} is not a row of D03's deck")
        for col, (have, w) in enumerate(zip(r[1:10], want, strict=True), 1):
            if have != w:
                bad.append(f"`{k}` column {col}: {have!r}; REG and the ruled vocabulary give {w!r}")
    ha = rows.get("heikin_ashi")
    if ha is not None and (ha[1] != "a chart type" or ha[8] != "refused as a bar type"):
        bad.append("`heikin_ashi` is not the chart-type row")
    return one("G-MODES", bad)


def g_bind(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-BIND")
    for r in bind_rows(t.spec):
        if len(r) < 8:
            bad.append(f"{r[0]}: malformed")
            continue
        for n in names_in(r[3]) + names_in(r[4]):
            if not source_found(t.env, n):
                bad.append(f"{r[0]}: `{n}` has no definition line at the base")
        served = strip_value(r[5]).strip("`")
        gap = r[7]
        rest_route = served == "REST only" and r[4] == "— (a REST route)"
        if served != "REST and WS" and gap == "—" and not rest_route:
            bad.append(f"{r[0]}: served `{served}` with no gap id")
        if gap != "—" and not in_register(t.spec, gap):
            bad.append(f"{r[0]}: the gap {gap} is not held in the register (§16)")
        if served == "neither" and not r[6].startswith(("pending ", "derived ")):
            bad.append(f"{r[0]}: no source, yet handed over as {r[6]!r}")
        if r[6].startswith("pending ") and r[6].split(" ", 1)[1] != gap:
            bad.append(f"{r[0]}: pending names {r[6].split(' ', 1)[1]}, the gap is {gap}")
    return one("G-BIND", bad)


def g_surfaces(t: Texts) -> list[Finding]:
    bad: list[str] = []
    e11 = {c[0]: c[1] for c in table_after(section(doc_text(t, "E11P"), "### 7.1 "), "Id")
           if len(c) > 1}  # fmt: skip
    parent_text = "\n".join(doc_text(t, p) for p in PATHS if re.fullmatch(r"D0\dH?", p))
    for head, scr in (*SURFACES.items(), ("### 2.8 ", "SCR-046")):
        sec = own_section(t.spec, head)
        if not sec:
            bad.append(f"{scr}: no entry {head.strip()}")
            continue
        rows = {c[0]: c[1] for c in table_after(sec, "Row") if len(c) > 1}
        if scr != "SCR-046" and list(rows) != list(SURFACE_ROWS):
            bad.append(f"{scr}: the rows are {list(rows)}, not the nine of the ruling")
        for lo, hi in re.findall(r"S-(\d{3})\.\.S-(\d{3})", sec):
            for n in range(int(lo), int(hi) + 1):
                cell = e11.get(f"S-{n:03d}")
                if cell is None or not cell.startswith(scr):
                    bad.append(f"{scr}: E11-D09 S-{n:03d} is not a row of {scr} ({cell!r})")
        for page in re.findall(r"page `([^`]+)`", rows.get("Frames", "")):
            if f"page `{page}`" not in parent_text:
                bad.append(f"{scr}: the page `{page}` is no parent's page")
    return one("G-SURFACES", bad)


def g_storybook(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-STORYBOOK")
    for r in table_after(own_section(t.spec, "## 3. "), "CMP"):
        n = r[0].removeprefix("CMP-")
        head = cmp_heading(t.env, n)
        if head is None or not head.split(" ", 2)[2].startswith(r[1]):
            bad.append(f"{r[0]}: `15` has no heading `CMP-{n} {r[1]}` at the base")
        if not r[4].strip():
            bad.append(f"{r[0]}: no Storybook cell")
    if "**required, not built**" not in own_section(t.spec, "## 3. "):
        bad.append("§3 does not state that every story is required, not built")
    manifest = {r[0].strip("`"): r for r in table_after(own_section(t.spec, "## 12. "), "Token")}
    for name in token_names(t.spec):
        status = t.values.get(f"TOKEN:{name}")
        row = manifest.get(name)
        if status == "absent" and (row is None or row[3] in ("", "—")):
            bad.append(f"`{name}` is absent at the base and has no manifest row with an owner")
    for name, row in manifest.items():
        if t.values.get(f"TOKEN:{name}") == "shipped" and row[3] != "—":
            bad.append(f"`{name}` is shipped; its owner cell must read —")
    return one("G-STORYBOOK", bad)


def g_deck(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-DECK")
    try:
        data = json.loads(t.deck)
    except json.JSONDecodeError as e:
        return one("G-DECK", [f"the deck is not JSON: {e}"])
    want = derive_deck(t.env)
    ent = data.get("entries", {}) if isinstance(data, dict) else {}
    wnt = deck_entries(t.env)
    for k, v in ent.items() if isinstance(ent, dict) else []:
        if isinstance(v, dict) and not v.get("owner"):
            bad.append(f"deck {k}: an entry with no owner")
        if k not in wnt:
            bad.append(f"deck {k}: no such row in the parents' decks")
        elif v != wnt[k]:
            bad.append(f"deck {k}: differs from its source row ({wnt[k].get('source')})")
    for k in wnt:
        if not isinstance(ent, dict) or k not in ent:
            bad.append(f"deck {k}: missing")
    if isinstance(data, dict):
        for k in ("pack", "version", "base", "note"):
            if data.get(k) != want.get(k):
                bad.append(f"deck field `{k}` differs from the derivation")
    for m in DECK_REF.finditer(collapse_copies(t.spec)):
        if m[1] not in wnt:
            bad.append(f"`{m[1]}` is not a deck row")
    return one("G-DECK", bad)


def number_tokens(cell: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", cell)


def g_budgets(t: Texts) -> list[Finding]:
    bad: list[str] = []
    b26 = section(doc_text(t, "26"), "## 13. ")
    b_ids = {c[0] for c in table_after(b26, "ID")}
    own = {r[0] for r in own_rows(t.spec)}
    for r in budget_rows(t.spec):
        if len(r) < 7:
            bad.append(f"{r[0]}: malformed")
            continue
        unit = r[2].split()[-1] if r[2].split() else ""
        if unit not in UNITS:
            bad.append(f"{r[0]}: the unit {unit!r} is outside the ruled set {UNITS}")
        line = cited_text(t, r[4])
        if not line:
            bad.append(f"{r[0]}: no source cite")
        for num in number_tokens(r[2]):
            if not re.search(rf"(?<![\d.]){re.escape(num)}(?![\d])", line):
                bad.append(f"{r[0]}: {num} does not stand on its cited line")
        gate = r[5]
        ids = re.findall(r"\bB\d+\b", gate)
        stories = [g for g in GATE_STORIES if g in gate]
        held = D12_ID.findall(gate)
        if gate.startswith("`26`"):
            for b in ids:
                if b not in b_ids:
                    bad.append(f"{r[0]}: `26` §13 has no row {b}")
            if not ids:
                bad.append(f"{r[0]}: `26` names no benchmark id")
        elif gate.startswith("no gate yet"):
            if not held or any(h not in own for h in held):
                bad.append(f"{r[0]}: 'no gate yet' without a G-row held in §16.2")
        elif not stories or gate not in stories:
            bad.append(f"{r[0]}: the gate {gate!r} is not a `26` id, a ruled story or no gate yet")
    fps = next((r for r in budget_rows(t.spec) if "fps" in r[2] and "58" in r[2]), None)
    const = t.env.at_base(CONSTITUTION_REL)
    if fps is None or not fps[5].startswith("`26`") or fps[6] != "C-14.2":
        bad.append("the 58-fps row does not cite `26` and name C-14.2 as its owner")
    if "**C-14.2**" not in const:
        bad.append("C-14.2 is not defined in the constitution at the base")
    return one("G-BUDGETS", bad)


NO_SOURCE = "no merged source"


def g_motion(t: Texts) -> list[Finding]:
    bad: list[str] = []
    own = {r[0] for r in own_rows(t.spec)}
    rows = motion_rows(t.spec)
    nosrc: list[str] = []
    for r in rows:
        if len(r) < 6:
            bad.append(f"{r[0]}: malformed")
            continue
        if any(NO_SOURCE in c for c in r[2:5]):
            nosrc.append(r[0])
            held = D12_ID.findall(r[5])
            if not held or any(h not in own for h in held) or cites_in(r[5]):
                bad.append(f"{r[0]}: {NO_SOURCE!r} needs a held G-row and no cite")
        elif not cites_in(r[5]):
            bad.append(f"{r[0]}: a decided moment with no merged cite")
    for word in ("switch", "bar close", "rebuild", "LOD"):
        if not any(word in r[1] for r in rows):
            bad.append(f"E12-D10's moment {word!r} has no row")
    sec = own_section(t.spec, "## 9. ")
    m = re.search(re.escape(COMMENT_245) + r"(.*?)(?:\n\n|\Z)", sec, re.DOTALL)
    if not m:
        bad.append("the comment line for #245 is missing or reads as posted")
    else:
        named = set(re.findall(r"M-\d\d", m[1]))
        if not set(nosrc) <= named:
            bad.append(f"the #245 comment does not name {sorted(set(nosrc) - named)}")
    return one("G-MOTION", bad)


def g_events(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-EVENTS")
    own = {r[0] for r in own_rows(t.spec)}
    names: dict[str, list[str]] = {}
    for r in event_rows(t.spec):
        if len(r) < 6:
            bad.append(f"{r[0]}: malformed")
            continue
        name = r[0].strip("`")
        names[name] = r
        line = cited_text(t, r[4])
        if not re.search(r"`" + re.escape(name) + r"[` ]", line):
            bad.append(f"`{name}` does not stand in backticks on its cited parent line")
        if not r[5].startswith("named, unsourced"):
            bad.append(f"`{name}`: status {r[5]!r} is not 'named, unsourced'")
        if r[3] not in ("T", "parent"):
            bad.append(f"`{name}`: Named by {r[3]!r}")
    for n in T_EVENTS:
        if n not in names or names[n][3] != "T":
            bad.append(f"`T`'s `{n}` is not a row named by T")
    ex = names.get("chart.data_table_exported")
    if ex is None or not [h for h in D12_ID.findall(ex[5]) if h in own]:
        bad.append("the export row carries no held G-row")
    if "**No event is emitted by this pack" not in own_section(t.spec, "## 13. "):
        bad.append("§13 does not state that no event is emitted by this pack")
    return one("G-EVENTS", bad)


# the role matrix as frozen at v1 (RULED BQ-19): one string per row, cells joined by " | " and
# whitespace-normalised; a changed cell FAILs G-ROLES (a new version row and a new set are due)
ROLE_FROZEN: tuple[tuple[str, ...], ...] = (
    (
        "R-01",
        "change symbol, interval and bar mode (SCR-041, SCR-042)",
        "`marketdata:read`",
        "enabled",
        "enabled",
        "enabled",
        "enabled; recents and favourites not written",
        "—",
        "`D04`:260-263",
    ),
    (
        "R-02",
        '"Record this symbol..." (SCR-041)',
        "`recording:write`",
        "enabled",
        "T2 `rbac.owner_only`",
        "T2 `rbac.owner_only`",
        "T2 `rbac.view_as`",
        '`rbac.owner_only` · "start recording" · CMP-079 RbacGate, CMP-019 `lock`',
        "`D04`:261-263",
    ),
    (
        "R-03",
        "the recorder CTA (SCR-047)",
        "`recording:write`",
        "enabled",
        "sentence `rbac.owner_only`",
        "sentence `rbac.owner_only`",
        "sentence `rbac.view_as`",
        '`rbac.owner_only` · "change recording" · CMP-079 RbacGate sentence form, no `lock`',
        "`D08`:139",
    ),
    (
        "R-04",
        "`Open diagnostics` (SCR-048)",
        "none named (D08-Q4)",
        "enabled",
        "T2 `rbac.owner_only`",
        "T2 `rbac.owner_only`",
        "not stated",
        '`rbac.owner_only` · "inspect the chart engine" (PROPOSED) · CMP-079 RbacGate, CMP-019 `lock`',
        "`D08`:313",
    ),
    (
        "R-05",
        "`Retry Volume 75`, `Build earlier bars` (SCR-030)",
        "not named; who may build is X-3",
        "not gated (X-3)",
        "not gated (X-3)",
        "not gated (X-3)",
        "T2 `rbac.view_as`",
        "`rbac.view_as` · — · CMP-079 RbacGate, CMP-019 `lock`",
        "`D08`:313",
    ),
    (
        "R-06",
        "`Cancel` a build (SCR-030 strip)",
        "the rebuild registry's owner check",
        "enabled, any build",
        "own build only",
        "own build only",
        "not stated",
        "—",
        "`D08`:264",
    ),
    (
        "R-07",
        "Save, the bar-mode radios and both Resets (SCR-031)",
        "`workspaces:write`",
        "enabled",
        "enabled",
        "T2",
        "T2 (W-26)",
        '"Your role can\'t save workspaces."; W-26 · CMP-079 RbacGate, CMP-019 `lock`',
        "`D05`:291-293",
    ),
    (
        "R-08",
        "chart type and crosshair (SCR-031)",
        "none: view state",
        "enabled",
        "enabled",
        "live as view state",
        "live as view state",
        "—",
        "`D05`:292-293",
    ),
)


def seed_codes(env: Env) -> set[str]:
    data = json.loads(env.at_base(PATHS["SEED"]))
    perms = data.get("permissions", []) if isinstance(data, dict) else []
    return {str(p.get("code")) for p in perms if isinstance(p, dict)}


def g_roles(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rows = role_rows(t.spec)
    now = [tuple(pin_norm(c) for c in r) for r in rows]
    if len(now) != len(ROLE_FROZEN):
        bad.append(f"the matrix has {len(now)} rows; {len(ROLE_FROZEN)} are frozen")
    for was, cur in zip(ROLE_FROZEN, now, strict=False):
        for i in range(max(len(was), len(cur))):
            if was[i : i + 1] != cur[i : i + 1]:
                bad.append(f"{cur[0] if cur else '?'}: the frozen cell {i} changed")
    codes = seed_codes(t.env)
    for r in rows:
        if len(r) < 9:
            continue
        for code in re.findall(r"`([a-z]+:[a-z]+)`", " ".join(r[:8])):
            if code not in codes:
                bad.append(f"{r[0]}: `{code}` is not a permission of the seed")
        src = cited_text(t, r[8])
        if not src:
            bad.append(f"{r[0]}: no source cite")
        for key in set(re.findall(r"`(rbac\.[a-z_]+)`", " ".join(r[3:8]))):
            if f"`{key}`" not in src:
                bad.append(f"{r[0]}: `{key}` does not stand on its cited lines")
        for q in re.findall(r'"([^"]+)"', r[7]):
            if not word_in(q, src):
                bad.append(f"{r[0]}: {q!r} does not stand on its cited lines")
    sec = own_section(t.spec, "### 14.2 ")
    ls = t.env.lines(t.env.base, PATHS["22"])
    blk = block_lines(ls, "  /market/bars:", r"^  /")
    rbac = [ln for ln in blk if "x-rbac:" in ln]
    s1 = re.search(r"`22`:(\d+)", sec[sec.find("S-1") : sec.find("S-2")])
    if not rbac or "marketdata:read" not in rbac[0] or not s1 or ls[int(s1[1]) - 1] != rbac[0]:
        bad.append("S-1 does not cite `getBars`'s own x-rbac line")
    s3 = sec[sec.find("S-3") : sec.find("S-4")]
    pline = re.search(r"at most (\d+) characters, `22`:(\d+)", s3)
    if not pline or f"maxLength: {pline[1]}" not in ls[int(pline[2]) - 1]:
        bad.append("S-3's 24 characters do not stand on the cited `param` definition line")
    elif not any(re.match(r"^\s+- name: param\s*$", ls[i]) for i in range(int(pline[2]) - 5,
                                                                          int(pline[2]) - 1)):  # fmt: skip
        bad.append("S-3 cites a line that is not `getBars`'s `param`")
    return one("G-ROLES", bad)


def g_t2(t: Texts) -> list[Finding]:
    bad: list[str] = []
    rule = " ".join(own_section(t.spec, "### 14.3 ").split())
    for term in T2_TERMS:
        if term not in rule:
            bad.append(f"§14.3 does not state {term}")
    for head, scr in SURFACES.items():
        comp = {c[0]: c[1] for c in table_after(own_section(t.spec, head), "Row")}.get(
            "Components", ""
        )
        if "CMP-079 RbacGate" not in comp:
            bad.append(f"{scr}: the component list does not name CMP-079 RbacGate")
        if scr != "SCR-047" and "CMP-019 `lock`" not in comp:
            bad.append(f"{scr}: the component list does not name CMP-019 `lock`")
    cmp = {r[0] for r in table_after(own_section(t.spec, "## 3. "), "CMP")}
    for c in ("CMP-079", "CMP-019"):
        if c not in cmp:
            bad.append(f"§3 does not list {c}")
    return one("G-T2", bad)


def g_ahead(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-AHEAD")
    for k in CONSUMERS:
        if f"SPRINT:{k}" not in t.values:
            bad.append(f"no sprint for {k} in the backlog JSON")
    if "reports, claims and promises nothing" not in own_section(t.spec, "## 15. "):
        bad.append("§15 does not state that it reports only")
    return one("G-AHEAD", bad)


def g_openrows(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-OPENROWS")
    for r in table_after(own_section(t.spec, "### 16.1 "), "Ids"):
        text = cited_text(t, r[1])
        if not text:
            bad.append(f"{r[0][:30]}: no parent cite")
            continue
        for lo, hi in RANGE.findall(r[0]):
            for ident in (lo, hi):
                if not re.search(rf"(?<![\w-]){re.escape(ident)}(?![\w-])", text):
                    bad.append(f"{ident} is not a row of {r[1]}")
    own = own_rows(t.spec)
    ids = [r[0] for r in own]
    if len(set(ids)) != len(ids):
        bad.append("a §16.2 id repeats")
    for r in own:
        m = re.fullmatch(r"(Blocking|Major|Minor|Info) \((p[0-3])\)", r[2] if len(r) > 2 else "")
        if not m or GRADES[m[1]] != m[2]:
            bad.append(f"{r[0]}: grade {r[2] if len(r) > 2 else ''!r} is not a ruled grade")
        if len(r) < 6 or not r[4].strip() or AGENT_NAME.search(r[4]):
            bad.append(f"{r[0]}: no owner lane, or an agent for one")
    for ref in set(D12_ID.findall(collapse_copies(t.spec))):
        if ref not in ids:
            bad.append(f"the pack names {ref}, which §16.2 does not hold")
    return one("G-OPENROWS", bad)


def post_merge(t: Texts) -> bool:
    return t.env.show(t.env.mb, SPEC_REL) is not None


def g_untouched(t: Texts) -> list[Finding]:
    bad: list[str] = []
    if t.changed is None:
        return one("G-UNTOUCHED", ["git did not list the changed paths"])
    for p in t.changed:
        if p not in OWN_PATHS:
            bad.append(f"{p} differs from the merge-base (not this pack's)")
    base14 = t.env.show(t.env.mb, PLAN14_REL) or ""
    if post_merge(t):
        if t.plan14 != base14:
            bad.append("`14` changed after the pack merged")
    else:
        want, problems = apply14(base14, t.ticks)
        bad += problems
        if t.plan14 != want:
            bad.append("`14` differs from the merge-base with the pointer lines and ticks applied")
    return one("G-UNTOUCHED", bad)


def has_section(text: str, n: str) -> bool:
    return bool(re.search(rf"^#{{2,3}} (?:§)?{re.escape(n)}[. ]", text, re.MULTILINE))


def has_board(text: str, n: str) -> bool:
    """A board of a parent: a row `| NN |` of its board table, or a PNG name of its board list
    (`E12-D0n-NN-`), a line naming two PNGs with "…" between them holding the range."""
    if re.search(rf"^\|\s*{n}\s*\|", text, re.MULTILINE):
        return True
    for ln in text.split("\n"):
        nums = [int(x) for x in re.findall(r"E12-D0\d-(\d\d)-", ln)]
        if int(n) in nums or ("…" in ln and len(nums) >= 2 and min(nums) <= int(n) <= max(nums)):
            return True
    return False


def tick_problems(t: Texts, scr: str, ev: str) -> list[str]:
    """Every part of a tick's evidence: a `§n` is a heading of the named parent at the base, a
    board a board of it, a `W-n` a row of its deck table."""
    bad: list[str] = []
    doc: str | None = None
    for part in re.split(r";\s*|,\s*", ev):
        part = part.strip()
        m = re.match(r"(E12-D0\d)\s*(.*)$", part)
        if m:
            doc = TICK_DOCS.get(m[1])
            part = m[2].strip()
            if doc is None:
                bad.append(f"{scr}: {m[1]} is not a known evidence source")
                continue
            if not part:
                continue
        if doc is None:
            bad.append(f"{scr}: {part!r} names no source")
            continue
        text = doc_text(t, doc)
        if (s := re.fullmatch(r"§(\d+(?:\.\d+)?)", part)) is not None:
            if not has_section(text, s[1]):
                bad.append(f"{scr}: {doc} has no §{s[1]}")
        elif (b := re.fullmatch(r"(?:boards? )?(\d\d)", part)) is not None:
            if not has_board(text, b[1]):
                bad.append(f"{scr}: {doc} has no board {b[1]}")
        elif re.fullmatch(r"W-\d+", part):
            if not re.search(rf"^\|\s*{re.escape(part)}\s*\|", text, re.MULTILINE):
                bad.append(f"{scr}: {doc} has no deck row {part}")
        else:
            bad.append(f"{scr}: {part!r} is not a section, a board or a deck row")
    return bad


def g_ticks(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-TICKS")
    for scr, items in t.ticks.items():
        for _, ev in items:
            bad += tick_problems(t, scr, ev)
    listed = sorted((r[0], r[2]) for r in evidence_rows(t.spec) if len(r) > 3
                    and r[3] == "ticked here")  # fmt: skip
    applied = sorted((scr, ev) for scr, items in t.ticks.items() for _, ev in items)
    if listed != applied:
        bad.append("the evidence table's 'ticked here' rows are not the ticks applied to `14`")
    for r in evidence_rows(t.spec):
        if len(r) > 3 and r[3] == "open" and not r[2].startswith("open"):
            bad.append(f"{r[0]} '{r[1][:30]}': an open item with evidence")
    return one("G-TICKS", bad)


def version_rows(spec: str) -> list[list[str]]:
    return table_after(own_section(spec, "## 19. "), "Version")


def g_frozen(t: Texts) -> list[Finding]:
    if not post_merge(t):
        return []
    merged = t.env.show(t.env.mb, SPEC_REL) or ""
    old = [" | ".join(r) for r in version_rows(unfill(merged))]
    now = [" | ".join(r) for r in version_rows(unfill(t.spec))]
    bad = [f"a merged version row changed or went: {r[:50]!r}" for r in old if r not in now]
    last = max((int(m[1]) for r in old for m in [re.match(r"v1\.(\d+)", r)] if m), default=0)
    for r in now:
        if r not in old:
            m = re.match(r"v1\.(\d+) ", r)
            if not m or int(m[1]) <= last:
                bad.append(f"a new version row is not v1.N above v1.{last}: {r[:40]!r}")
    return one("G-FROZEN", bad)


def g_ruled(t: Texts) -> list[Finding]:
    bad: list[str] = []
    heads = [ln for ln in t.spec.split("\n") if ln.startswith("## ") and "The questions" in ln]
    if len(heads) != 1 or STAMP not in heads[0]:
        bad.append("the questions heading does not carry the ruling stamp")
    if RULING_ID not in t.spec:
        bad.append(f"the ruling id {RULING_ID} is not named")
    if "<!-- BQ-" in t.spec:
        bad.append("a BQ marker is left")
    if OWNER_PENDING not in t.spec.lower():
        bad.append(f'"{OWNER_PENDING}" is not stated')
    for n in range(1, BQ_TOTAL + 1):
        if f"BQ-{n:02d}" not in t.spec:
            bad.append(f"BQ-{n:02d} is not named")
    return one("G-RULED", bad)


def g_hygiene(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for doc, text in (("spec", t.spec), ("deck", t.deck)):
        for k in unfilled(text) if doc == "spec" else []:
            bad.append(f"{doc}: `{{{{{k}}}}}` is unfilled")
        plain = collapse_copies(text)
        for m in re.finditer(r"<!--(.*?)-->", plain, re.DOTALL):
            if not re.fullmatch(r"=[A-Z]+:[^>]+", m[1]):
                bad.append(f"{doc}: a stray HTML comment {m[0][:40]!r}")
        for ln in plain.split("\n"):
            if CLOSING.search(without_code(ln)):
                bad.append(f"{doc}: a closing keyword outside a code span: {ln[:50]!r}")
        for rx, what in ((LOCAL_PATH, "a local path"), (AGENT_NAME, "an agent name"),
                         (URL_OR_HOST, "a URL or host"), (WORDS, "a public-text word")):  # fmt: skip
            m2 = rx.search(plain if doc == "spec" else text)
            if m2:
                bad.append(f"{doc}: {what} ({m2[0]!r})")
    return one("G-HYGIENE", bad)


def g_pins(t: Texts) -> list[Finding]:
    pinned = parse_pins(t.pins)
    if not pinned:
        return one("G-RULED-PIN", [f"{PIN_REL} is empty or missing (run --repin-ruled)"])
    return one("G-RULED-PIN", pin_problems(pinned, all_units(t)))


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_values, g_lift, g_copy, g_cite, g_version, g_modes, g_bind, g_surfaces, g_storybook, g_deck,
    g_budgets, g_motion, g_events, g_roles, g_t2, g_ahead, g_openrows, g_untouched, g_ticks,
    g_frozen, g_ruled, g_hygiene,
)  # fmt: skip


def gate_name(g: Callable[[Texts], list[Finding]]) -> str:
    return "G-" + g.__name__[2:].upper()


def audit(t: Texts, timings: dict[str, float] | None = None) -> list[Finding]:
    found: list[Finding] = []
    for g in GATES:
        t0 = time.perf_counter()
        found += g(t)
        if timings is not None:
            timings[gate_name(g)] = time.perf_counter() - t0
    pins = g_pins(t)
    if any(f.level == "FAIL" for f in found):
        pins = [replace(f, level="NOTE") for f in pins]
    return found + pins


def load() -> Texts:
    mb = merge_base()
    full = (git_raw("rev-parse", "--verify", f"{BASE}^{{commit}}") or "").strip()
    if mb is None or not full:
        raise SystemExit(f"`git merge-base HEAD {HEAD_REF}` or the base {BASE} does not resolve")
    env = Env(full, mb, {})
    pins = read_raw(PIN_REL) if (ROOT / PIN_REL).exists() else ""
    deck = read_raw(DECK_REL) if (ROOT / DECK_REL).exists() else "{}"
    t = Texts(env, read_raw(SPEC_REL), deck, pins, read_raw(PLAN14_REL), changed_paths(mb), {},
              dict(TICKS))  # fmt: skip
    return replace(t, values=compute(t))


# ---------------------------------------------------------------------------- self-test


@dataclass(frozen=True)
class Mutation:
    gate: str
    what: str
    apply: Callable[[Texts], Texts]


def flex(old: str) -> re.Pattern[str]:
    """`old` with every run of spaces matching any run of spaces (prettier re-pads tables)."""
    return re.compile(r"\s+".join(re.escape(p) for p in old.split(" ") if p != ""))


def subst(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        m = flex(old).search(t.spec)
        if not m:
            raise SystemExit(f"self-test: the spec lacks {old[:60]!r}")
        return replace(t, spec=t.spec[: m.start()] + new + t.spec[m.end() :])

    return f


def anchor_edit(key: str, new_value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        m = re.search(rf"([^\s<|`(\[\"']+|`[^`\n]*`)<!--={re.escape(key)}-->", t.spec)
        if not m:
            raise SystemExit(f"self-test: the spec has no anchored {key}")
        return replace(
            t, spec=t.spec[: m.start()] + f"{new_value}<!--={key}-->" + t.spec[m.end() :]
        )

    return f


def with_text(t: Texts, rev: str, rel: str, text: str) -> Texts:
    memo = {k: v for k, v in t.env.memo.items() if k != f"show:{rev}:{rel}"}
    memo[f"show:{rev}:{rel}"] = text
    return replace(t, env=Env(t.env.base, t.env.mb, memo))


def copy_edit(t: Texts) -> Texts:
    m = re.search(r"<!-- COPY:d06\.s63 -->\n+(.)", t.spec)
    if not m:
        raise SystemExit("self-test: the spec has no COPY:d06.s63 block")
    i = m.start(1)
    return replace(t, spec=t.spec[:i] + ("X" if t.spec[i] != "X" else "Y") + t.spec[i + 1 :])


def head_gone(t: Texts) -> Texts:
    rel = PATHS["D06"]
    ls = t.env.lines(t.env.base, rel)
    ls[263] = ls[263] + " (edited)"
    return with_text(t, HEAD_REF, rel, "\n".join(ls))


def deck_edit(t: Texts) -> Texts:
    data = json.loads(t.deck)
    data["entries"]["d03:C-24"]["text"] = data["entries"]["d03:C-24"]["text"] + " "
    return replace(t, deck=json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def parent_changed(t: Texts) -> Texts:
    return replace(t, changed=[*(t.changed or []), PATHS["D08"]])


def tick_moved(t: Texts) -> Texts:
    """One tick's evidence pointed at a section its parent lacks, in the tool's ticks, in `14` and
    in the pack's evidence table alike (so the three agree and only the evidence is wrong)."""
    old, new = "E12-D08 §4.3", "E12-D08 §4.9"
    ticks = {k: tuple((i, e.replace(old, new)) for i, e in v) for k, v in t.ticks.items()}
    if f"({old})" not in t.plan14 or f"| {old} " not in t.spec:
        raise SystemExit("self-test: the SCR-048 tick evidence is not found")
    return replace(t, ticks=ticks, plan14=t.plan14.replace(f"({old})", f"({new})"),
                   spec=t.spec.replace(f"| {old} ", f"| {new} "))  # fmt: skip


def merged_and_edited(t: Texts) -> Texts:
    """A merge-base that already holds this pack and its `14` lines (a simulated later PR)."""
    sim = "simulated-merge-base"
    memo = dict(t.env.memo)
    memo[f"show:{sim}:{SPEC_REL}"] = t.spec
    memo[f"show:{sim}:{PLAN14_REL}"] = t.plan14
    t2 = replace(t, env=Env(t.env.base, sim, memo))
    row = next(ln for ln in t.spec.split("\n") if ln.startswith("| v1 ") and "first version" in ln)
    return replace(t2, spec=t.spec.replace(row, row.replace("first version", "first draft"), 1))


MUTATIONS: tuple[Mutation, ...] = (
    Mutation("G-VALUES", "claim E12-D11's file is at the base", anchor_edit("STATUS:d11.file", "present")),
    Mutation("G-LIFT", "alter a lifted block's hash", anchor_edit("HASH:d06.s14", "000000000000")),
    Mutation("G-COPY", "change one byte inside the copied D06 §6.3", copy_edit),
    Mutation("G-CITE", "point a cite past the end of its file",
             subst("`D08`:111 (R-3)", "`D08`:99999 (R-3)")),
    Mutation("G-VERSION", "edit D06's forming line at origin/main", head_gone),
    Mutation("G-MODES", "rename tick's field label", subst("| Trades per bar    |", "| Trades per brick  |")),
    Mutation("G-BIND", "name a REST field that does not exist", subst("`Bar.trades`", "`Bar.tradez`")),
    Mutation("G-SURFACES", "widen SCR-045's E11-D09 rows into another screen's",
             subst("S-079..S-087, cited", "S-078..S-087, cited")),
    Mutation("G-STORYBOOK", "type a Storybook count by hand", anchor_edit("CITE:stories.cmp181", "34")),
    Mutation("G-DECK", "alter one deck string", deck_edit),
    Mutation("G-BUDGETS", "type the frame rate by hand", subst("| ≥58 fps        |", "| ≥59 fps        |")),
    Mutation("G-MOTION", "mark the #245 comment as posted",
             subst("to post at this pack's merge (not posted here):", "posted:")),
    Mutation("G-EVENTS", "point an event at another event's parent line",
             subst("| `D02`:379              |", "| `D02`:380              |")),
    Mutation("G-ROLES", "let a Manager cancel any build",
             subst("| own build only           | own build only", "| any build                | own build only")),
    Mutation("G-T2", "drop the reason node's `aria-describedby` link",
             subst("linked by `aria-describedby`;", "linked to the control;")),
    Mutation("G-AHEAD", "type a margin by hand", anchor_edit("DAYS:margin.s06", "1")),
    Mutation("G-OPENROWS", "widen a parent's range past its last row",
             subst("| D07-G1..D07-G7 ", "| D07-G1..D07-G8 ")),
    Mutation("G-UNTOUCHED", "edit a parent in the same tree", parent_changed),
    Mutation("G-TICKS", "point a tick's evidence at a missing section (tool, 14 and pack)", tick_moved),
    Mutation("G-FROZEN", "post-merge: edit a merged v1 row", merged_and_edited),
    Mutation("G-RULED", "drop the stamp's date from the questions heading",
             subst("## The questions BQ-01..BQ-23 — RULED (orchestrator, 2026-10-31,",
                   "## The questions BQ-01..BQ-23 — RULED (orchestrator,")),
    Mutation("G-HYGIENE", "write a closing keyword outside a code span",
             subst("The PR body carries `Closes #313`.", "The PR body carries Closes #313.")),
    Mutation("G-RULED-PIN", "re-word a pinned sentence no other gate reads",
             subst("Nothing on these surfaces is built: the pack is the build's input.",
                   "Nothing on these surfaces is built yet: the pack is the build's input.")),
)  # fmt: skip


def digest(t: Texts) -> str:
    return hashlib.sha256(f"{t.spec}\0{t.deck}\0{t.pins}\0{t.plan14}".encode()).hexdigest()


def ascii_line(s: str) -> str:
    for a, b in (("→", "->"), ("…", "..."), ("—", "-"), ("–", "-"), ("×", "x"), ("§", "S"),
                 ("·", "|"), ("≤", "<="), ("≥", ">=")):  # fmt: skip
        s = s.replace(a, b)
    return s.encode("ascii", "replace").decode()[:110]


def selftest() -> tuple[bool, list[str]]:
    t0 = time.perf_counter()
    base = load()
    disk = [hashlib.sha256(read_raw(r).encode()).hexdigest() for r in OWN_PATHS
            if (ROOT / r).exists()]  # fmt: skip
    before = digest(base)
    base_fails = [f for f in audit(base) if f.level == "FAIL"]
    out = [f"self-test: baseline {len(base_fails)} FAIL"]
    ok = not base_fails
    for f in base_fails:
        out.append(ascii_line(f"  baseline {f.gate}: {f.msg}"))
    gates_hit: set[str] = set()
    for i, m in enumerate(MUTATIONS, 1):
        found = audit(m.apply(base))
        fails = sorted({f.gate for f in found if f.level == "FAIL"})
        good = fails == [m.gate]
        ok &= good
        if good:
            gates_hit.add(m.gate)
        out.append(ascii_line(f"{'ok  ' if good else 'FAIL'} M-{i} {m.gate}: {m.what} -> "
                              f"{', '.join(fails) or 'none'}"))  # fmt: skip
    every = {gate_name(g) for g in GATES} | {"G-RULED-PIN"}
    missed = sorted(every - gates_hit)
    ok &= not missed
    restored = digest(base) == before and disk == [
        hashlib.sha256(read_raw(r).encode()).hexdigest() for r in OWN_PATHS if (ROOT / r).exists()
    ]
    ok &= restored
    out.append(f"self-test: {len(MUTATIONS)} mutations over {len(every)} gates, caught "
               f"{len(gates_hit)}, missed {', '.join(missed) or 'none'}; texts restored: "
               f"{'yes' if restored else 'NO'}")  # fmt: skip
    out.append(f"self-test: {'PASS' if ok else 'FAIL'} in {time.perf_counter() - t0:.1f} s")
    return ok, out


# ---------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="the default mode")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    ap.add_argument("--json", action="store_true", help="--check's dump")
    ap.add_argument("--fill", action="store_true", help="fill the values, the copies and the deck")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.repin_ruled:
        if unfilled(t.spec):
            print("refused: the spec has an unfilled placeholder (run --check --fill)")
            return 1
        other = [f for f in audit(t) if f.level == "FAIL" and f.gate != "G-RULED-PIN"]
        if other:
            print(f"refused: {len(other)} FAIL outside the pins (first: {other[0].gate}); fix them")
            return 1
        write_text(PIN_REL, write_pins(all_units(t)))
        print(f"wrote {PIN_REL}")
        return 0
    if a.fill:
        copies = copy_sources(t.env)
        deck = json.dumps(derive_deck(t.env), ensure_ascii=False, indent=2) + "\n"
        write_text(DECK_REL, deck)
        t = replace(t, deck=deck)
        missing: list[str] = []
        for _ in range(2):  # counts that read the spec's own tables settle on the second pass
            t = replace(t, values=compute(t))
            spec, missing = fill(t.spec, t.values, copies)
            write_text(SPEC_REL, spec)
            t = replace(t, spec=spec)
        for m in missing:
            print(f"unfilled: {m}")
        t = load()
    timings: dict[str, float] = {}
    found = audit(t, timings)
    fails = [f for f in found if f.level == "FAIL"]
    if a.json:
        dump = {"base": t.env.base, "merge_base": t.env.mb, "post_merge": post_merge(t),
                "values": t.values, "timings": {k: round(v, 3) for k, v in timings.items()},
                "findings": [{"level": f.level, "gate": f.gate, "msg": f.msg} for f in found]}  # fmt: skip
        print(json.dumps(dump, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for f in found:
            print(ascii_line(f"{f.level} {f.gate}: {f.msg}"))
        warns = sum(f.level == "WARN" for f in found)
        notes = sum(f.level == "NOTE" for f in found)
        mode = "post-merge" if post_merge(t) else "PR-1"
        print(
            f"{len(fails)} FAIL / {warns} WARN / {notes} NOTE ({len(GATES) + 1} gates, {mode} mode)"
        )
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
