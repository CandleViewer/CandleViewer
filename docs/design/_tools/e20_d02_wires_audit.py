#!/usr/bin/env python3
"""E20-D02 (#574) check: the Deep Stats wireframe spec (text leg; boards pending).

Standalone, stdlib only, offline and default-deny. The BQ list's ORCH-default (comment
6609419059, BQ-0) keeps the shared audit helper out of this PR until it is on `main`, so this
file carries its own small primitives. It reads, AS TEXT, the plan, design and backlog texts the
spec cites at the pinned base, the E20-D01 memo at its pinned PR head, and the spec from the
working tree. It runs no other repo code.

Gates: G-CITE, G-QUOTE, G-AC, G-ROWS, G-MEMO, G-KEYS, G-GREY, G-SRC, G-BOARDS, G-BQ, G-AMEND,
G-PIN, G-NOCLOSE, G-PUBLIC and G-MUTLIST (section 18.2 equals this tool's list).

Usage (from the repo root):
  python3 -I docs/design/_tools/e20_d02_wires_audit.py --check | --self-test
  python3 -I docs/design/_tools/e20_d02_wires_audit.py --fill   (writes section 18.2)
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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = "b81479ab01109ee1efc6cdedb411bd5f75ecdd66"  # origin/main when the BQ list was written
MEMO_HEAD = "57e01caf284be44b5e0f527e8f042432a0fe9aa7"  # PR 5640 head; re-pin at its merge
BQ_LIST = "6609419059"  # the BQ list on #574
TICKET = "E20-D02"

SPEC_REL = "docs/design/E20/E20-D02.md"
TOOL_REL = "docs/design/_tools/e20_d02_wires_audit.py"
OWN = (SPEC_REL, TOOL_REL)
BACKLOG_REL = "docs/plan/backlog/E20.json"
MEMO_REL = "docs/design/research/e20-deep-stats.md"
KEYED = {
    "README": ("docs/design/README.md", BASE),
    "E18-D02": ("docs/design/E18/E18-D02.md", BASE),
    "E20.json": (BACKLOG_REL, BASE),
    "R32": (".claude/rules/32-design-specs.md", BASE),
    "E47-D04": ("docs/design/E47/E47-D04.md", BASE),
    "E47-D08": ("docs/design/E47/E47-D08.md", BASE),
    "E47-D09": ("docs/design/E47/E47-D09.md", BASE),
    "E09-D09": ("docs/design/E09/E09-D09.md", BASE),
    "MEMO": (MEMO_REL, MEMO_HEAD),
}
# Source pins: (document, line, text that must stand on it at its pinned revision).
SOURCE_PINS = (
    ("24", 1207, "**Deep Stats rows (per-bar statistics strip)**"),
    ("14", 870, "at least one row selected"),
    ("14", 875, "chart.deepstats_rows_changed"),
    ("15", 2937, "Empty(no recording)"),
    ("15", 2938, "12 rows update budget"),
    ("15", 2598, "overflow after 12 rows"),
    ("20", 871, "demo has no separate public feed"),
    ("22", 13303, "/admin/jobs/{jobId}"),
    ("E47-D09", 140, "Move up / Move down"),
    ("E47-D09", 173, "Deep Stats rows"),
    ("MEMO", 232, "refuted as written"),
    ("MEMO", 250, "| AD-1 "),
    ("MEMO", 257, "| AD-8 "),
)

BQ_HEADING = "## The questions BQ-0"
BQ_HEADING_LINE = f"{BQ_HEADING} … BQ-9 — defaults built; ruling pending (comment {BQ_LIST})"
BQ_STATUS = f"Status: **defaults built; ruling pending (comment {BQ_LIST})**."
BQ_ID = re.compile(r"- \*\*(BQ-\d+)")
STATUSES = ("done", "text-only", "pending (boards)", "owner approval pending")
KEYS_NEEDED = ("`Alt+↑`", "`Alt+↓`", "Move up", "Move down", "E47-D04", "keeps focus")
SIGN_GLYPHS = ("▲", "▼")
SRC_OK = ("footprint + trades", "`/market/footprint`", "`/market/metrics`", "D02-G")
METRICS_RE = re.compile(r"`/market/metrics` `([a-z_]+)` \(`22`:(\d+)\)")
CURLY_RE = re.compile(r"“([^”]+)”")
QUOTE_MIN = 12
HEX40 = re.compile(r"\b[0-9a-f]{40}\b")
_KW = "|".join(("clo" + "se[sd]?", "fi" + "x(?:e[sd])?", "reso" + "lve[sd]?"))
CLOSING_RE = re.compile(rf"\b(?:{_KW}):?\s*#\d+", re.IGNORECASE)
# Paths and hosts, assembled from fragments so this file never matches its own scan.
PUBLIC_RE = re.compile(
    "|".join(("/" + "home/", "/" + "tmp/", r"\.lo" + r"cal\b", "scr" + "atch-", r"\.can" + "dle")),
    re.IGNORECASE,
)
# sha256[:16] of the lower-cased words that name a person, a lane or a role on this project.
IDENT_SHA16 = frozenset(
    {
        "741484060af219a6",
        "acfe8450840b3967",
        "d7aba0f660c463d8",
        "50bc66d8aae5ae90",
        "87eba76e7f316453",
        "ff41d3fde1448a0e",
    }
)
COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
CITE_RE = re.compile(
    r"(?:`(?P<nn>\d\d)`|(?<![A-Za-z0-9-])(?P<named>"
    + "|".join(re.escape(k) for k in sorted(KEYED, key=len, reverse=True))
    + r")):(?P<first>\d+)(?:–(?P<end>\d+))?(?P<more>(?:, :\d+(?:–\d+)?)*)"
)
MORE_RE = re.compile(r":(\d+)(?:–(\d+))?")


class AuditError(Exception):
    """A setup failure (a missing commit, a mutation anchor): never a silent PASS."""


# ---------- git (read-only) -----------------------------------------------------------------------
def git(*args: str) -> str | None:
    res = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False
    )
    return res.stdout if res.returncode == 0 else None


@functools.cache
def show(rel: str, rev: str = BASE) -> tuple[str, ...] | None:
    text = git("show", f"{rev}:{rel}")
    return None if text is None else tuple(text.split("\n"))


@functools.cache
def doc_lines(key: str) -> tuple[str, ...] | None:
    if key in KEYED:
        return show(*KEYED[key])
    for line in (git("ls-tree", "--name-only", BASE, "docs/plan/") or "").splitlines():
        name = line.rsplit("/", 1)[-1]
        if name.startswith(key + "-") and name.endswith((".md", ".yaml")):
            return show(line)
    return None


def changed_paths() -> tuple[str, ...]:
    """Paths that differ from the merge-base with origin/main (the newest of HEAD's and, during a
    simulated merge, MERGE_HEAD's), plus untracked, unignored files."""
    bases = [
        b.strip()
        for ref in ("HEAD", "MERGE_HEAD")
        if git("rev-parse", "-q", "--verify", ref) and (b := git("merge-base", ref, "origin/main"))
    ]
    if not bases:
        raise AuditError("no merge-base with origin/main")
    base = bases[0]
    for b in bases[1:]:
        if git("merge-base", "--is-ancestor", base, b) is not None:
            base = b
    out = (git("diff", "--name-only", base, "--") or "") + (
        git("ls-files", "--others", "--exclude-standard") or ""
    )
    return tuple(sorted({p for p in out.splitlines() if p}))


# ---------- markdown ------------------------------------------------------------------------------
def section(text: str, prefix: str) -> str:
    """The body under the first heading starting with `prefix`, up to the next heading of the
    same or a higher level."""
    level = len(prefix) - len(prefix.lstrip("#"))
    out: list[str] = []
    inside = False
    for line in text.split("\n"):
        if not inside:
            inside = line.startswith(prefix)
            continue
        if re.match(rf"^#{{1,{level}}} ", line):
            break
        out.append(line)
    return "\n".join(out)


def table_rows(block: str) -> list[list[str]]:
    """The body rows of the first table in `block`."""
    out: list[list[str]] = []
    seen_rule = False
    for line in block.split("\n"):
        if not line.startswith("|"):
            if seen_rule and out:
                break
            continue
        if re.fullmatch(r"\|[\s:|-]+\|", line.strip()):
            seen_rule = True
        elif seen_rule:
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def cites(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in CITE_RE.finditer(text):
        key = m.group("nn") or m.group("named")
        lo = int(m.group("first"))
        out.append((key, lo, int(m.group("end") or lo)))
        out += [(key, int(a), int(b or a)) for a, b in MORE_RE.findall(m.group("more") or "")]
    return out


def names_of(cell: str) -> tuple[str, ...]:
    return tuple(re.findall(r"`([a-z_]+)`", cell))


@functools.cache
def catalogue() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """`24` §7's Deep Stats rows at the pin: (row label, metric names), in order."""
    lines = doc_lines("24") or ()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("**Deep Stats rows"))
    got = table_rows("\n".join(lines[start : start + 40]))
    return tuple((r[0], names_of(r[1])) for r in got if len(r) > 1)


@functools.cache
def ticket_body() -> str:
    tickets = json.loads("\n".join(show(BACKLOG_REL) or ("[]",)))
    return next(str(t.get("body", "")) for t in tickets if t.get("key") == TICKET)


def scenario_names() -> tuple[str, ...]:
    return tuple(n.strip() for n in re.findall(r"Scenario: (.+)", ticket_body()))


def ac1_states() -> tuple[str, ...]:
    m = re.search(r"Then a frame exists for (.+)", ticket_body())
    if not m:
        raise AuditError("AC 1's frame list not found at the pin")
    return tuple(s.strip() for s in re.split(r", | and ", m.group(1).strip()))


def memo_labels(heading: str) -> list[str]:
    memo = "\n".join(doc_lines("MEMO") or ())
    return [r[1] for r in table_rows(section(memo, heading)) if len(r) > 1]


# ---------- the tree gates read -------------------------------------------------------------------
@dataclass(frozen=True)
class Tree:
    spec: str
    changed: tuple[str, ...] = ()

    def rows(self, heading: str) -> list[list[str]]:
        return table_rows(section(self.spec, heading))


# ---------- gates ---------------------------------------------------------------------------------
def g_cite(t: Tree) -> list[str]:
    got = cites(t.spec)
    bad = [] if len(got) >= 60 else [f"only {len(got)} cites parsed"]
    for key, lo, hi in got:
        lines = doc_lines(key)
        if lines is None or not 1 <= lo <= hi <= len(lines):
            bad.append(f"{key}:{lo} unresolved")
        elif not all(lines[i - 1].strip() for i in range(lo, hi + 1)):
            bad.append(f"{key}:{lo} blank")
    for key, n, needle in SOURCE_PINS:
        lines = doc_lines(key) or ()
        if not (1 <= n <= len(lines) and needle in lines[n - 1]):
            bad.append(f"{key}:{n} no longer carries {needle!r}")
    return sorted(set(bad))


def g_quote(t: Tree) -> list[str]:
    bad: list[str] = []
    for line in t.spec.split("\n"):
        quotes = [q for q in CURLY_RE.findall(line) if len(q) >= QUOTE_MIN]
        hay = [
            norm(" ".join((doc_lines(k) or ())[lo - 1 : hi]))
            for k, lo, hi in (cites(line) if quotes else [])
        ]
        bad += [q[:50] for q in quotes if not any(norm(q) in h for h in hay)]
    return [f"not on a cited line: {b}" for b in bad]


def g_ac(t: Tree) -> list[str]:
    names, states, trace = scenario_names(), ac1_states(), t.rows("## Acceptance-criteria trace")
    bad = [] if len(names) == 3 and len(states) == 9 else [f"{len(names)}/{len(states)} at pin"]
    for i, name in enumerate(names, 1):
        if not any(r[0].startswith(f'AC {i} "{name}"') for r in trace):
            bad.append(f"AC {i} not verbatim")
    ac1 = " ".join(r[0] for r in trace if r[0].startswith("AC 1 "))
    boards = section(t.spec, "## 0. Status and the boards")
    for s in states:
        if s not in ac1:
            bad.append(f"AC 1 row lacks {s}")
        if f"`SCR-030/strip-{s}`" not in boards:
            bad.append(f"no frame for {s}")
    return bad + [f"status of {r[0][:30]}" for r in trace if len(r) < 4 or r[2] not in STATUSES]


def g_rows(t: Tree) -> list[str]:
    cat = dict(catalogue())
    bad = [] if len(cat) == 20 else [f"{len(cat)} catalogue rows at the pin"]
    for heading in ("### 3.2", "### 3.3", "### 3.4", "### 6.1"):
        for r in t.rows(heading):
            if len(r) < 3 or cat.get(r[1]) != names_of(r[2]):
                bad.append(f"{heading[4:]} row {r[1] if len(r) > 1 else '?'} not a §7 label")
    full = [r[1] for r in t.rows("### 6.1") if len(r) > 1]
    if full != [label for label, _ in catalogue()]:
        bad.append("§6.1 is not the full §7 catalogue in order")
    if len(t.rows("### 3.3")) != 12:
        bad.append("AllRows is not 12 rows")
    return bad


def g_memo(t: Tree) -> list[str]:
    if doc_lines("MEMO") is None:
        return [f"{MEMO_REL} not readable at {MEMO_HEAD[:12]} (fetch the memo PR head)"]
    bad: list[str] = []
    for mine, theirs in (("### 3.2", "### 6.1 Default row set"), ("### 3.4", "### 6.2 Compact")):
        if [r[1] for r in t.rows(mine) if len(r) > 1] != memo_labels(theirs):
            bad.append(f"{mine[4:]} differs from MEMO {theirs[4:7]}")
    memo = "\n".join(doc_lines("MEMO") or ())
    got = t.rows("## 14. Memo trace")
    if [r[0] for r in got] != [f"AD-{i}" for i in range(1, 9)]:
        bad.append("trace ids not AD-1..AD-8")
    for r in got:
        if f"| {r[0]} |" not in memo:
            bad.append(f"{r[0]} not in the memo")
        if len(r) < 4 or not r[3].startswith("honoured"):
            bad.append(f"{r[0]} re-decided")
    return bad


def g_keys(t: Tree) -> list[str]:
    body = section(t.spec, "### 6.3")
    return [f"§6.3 lacks {k}" for k in KEYS_NEEDED if k not in body]


def g_grey(t: Tree) -> list[str]:
    got = [r for r in t.rows("### 3.6") if len(r) > 5 and r[2] == "breached"]
    bad = [] if len(got) >= 2 else [f"{len(got)} breached rows"]
    for r in got:
        word, glyph = r[5], r[4]
        if word in ("", "—") or glyph in ("", "—") or any(g in glyph for g in SIGN_GLYPHS):
            bad.append(f"{r[0]} {r[1]} lacks a word or a distinct glyph")
    if "`SCR-030/strip-ThresholdsBreached-greyscale`" not in t.spec:
        bad.append("no greyscale frame")
    return bad


def g_src(t: Tree) -> list[str]:
    got = t.rows("## 9. Data sources")
    want = [label for label, _ in catalogue()]
    bad = [] if sorted(r[0] for r in got) == sorted(want) else ["rows differ from `24` §7"]
    for r in got:
        if len(r) < 4 or not all(any(ok in c for ok in SRC_OK) for c in r[1:4]):
            bad.append(f"{r[0]} has a cell with no source")
            continue
        for code, n in METRICS_RE.findall(r[3]):
            lines = doc_lines("22") or ()
            if not (1 <= int(n) <= len(lines) and lines[int(n) - 1].strip() == f"- {code}"):
                bad.append(f"{r[0]}: `{code}` is not at `22`:{n}")
    return bad


def g_boards(t: Tree) -> list[str]:
    got = t.rows("## 0. Status and the boards")
    bad = [] if 0 < len(got) <= 10 else [f"{len(got)} boards"]
    for r in got:
        if len(r) < 4 or r[3] != "PENDING" or not r[1].startswith(f"`{TICKET} / {r[0]} "):
            bad.append(f"board {r[0] if r else '?'}")
    if "**Not drawn — the text is binding**" not in t.spec:
        bad.append("not-drawn paragraph")
    return bad


def g_bq(t: Tree) -> list[str]:
    body = section(t.spec, BQ_HEADING)
    bad = [] if BQ_HEADING_LINE in t.spec.split("\n") else ["heading"]
    if BQ_STATUS not in body:
        bad.append("the status line")
    bullets = [ln for ln in body.split("\n") if BQ_ID.match(ln)]
    ids = [m.group(1) for b in bullets if (m := BQ_ID.match(b))]
    if ids != [f"BQ-{n}" for n in range(10)]:
        bad.append(f"ids {ids}")
    bad += [f"BQ-{n} default" for n, b in enumerate(bullets) if "ORCH-default built." not in b]
    return bad + (["RULED before a ruling"] if "RULED:" in body else [])


def g_amend(t: Tree) -> list[str]:
    return [p for p in t.changed if p not in OWN]


def g_pin(t: Tree) -> list[str]:
    bad = [] if f"**Inputs pinned.** Base `origin/main` `{BASE[:12]}`" in t.spec else ["base"]
    if f"`{MEMO_HEAD[:12]}`" not in t.spec or "re-pins to its merge commit" not in t.spec:
        bad.append("memo pin")
    return bad + ["a 40-hex string" for _ in HEX40.finditer(t.spec)]


def g_noclose(t: Tree) -> list[str]:
    return [m.group(0) for m in CLOSING_RE.finditer(t.spec)]


def g_public(t: Tree) -> list[str]:
    bad = [m.group(0) for m in PUBLIC_RE.finditer(t.spec)]
    words = {w.lower() for w in re.findall(r"[A-Za-z0-9]+", t.spec)}
    bad += ["an identity word" for w in words if sha16(w) in IDENT_SHA16]
    return bad + [f"comment {m.group(0)[:20]}" for m in COMMENT_RE.finditer(t.spec)]


def sha16(word: str) -> str:
    return hashlib.sha256(word.encode("utf-8")).hexdigest()[:16]


def g_mutlist(t: Tree) -> list[str]:
    want = [[m.mid, m.gate, m.what] for m in MUTATIONS]
    return [] if t.rows("### 18.2 Mutations") == want else ["§18.2 differs from the tool"]


Gate = tuple[str, Callable[[Tree], list[str]]]
GATES: tuple[Gate, ...] = tuple(
    ("G-" + f.__name__[2:].upper(), f)
    for f in (
        g_cite, g_quote, g_ac, g_rows, g_memo, g_keys, g_grey, g_src, g_boards, g_bq, g_amend,
        g_pin, g_noclose, g_public, g_mutlist,
    )
)  # fmt: skip


def run(t: Tree) -> list[tuple[str, list[str]]]:
    """Default-deny: a gate that raises FAILs with the exception named."""
    out: list[tuple[str, list[str]]] = []
    for name, fn in GATES:
        try:
            out.append((name, fn(t)))
        except (AuditError, IndexError, KeyError, ValueError, TypeError, StopIteration) as exc:
            out.append((name, [f"raised {type(exc).__name__}: {exc}"]))
    return out


# ---------- mutations -----------------------------------------------------------------------------
@dataclass(frozen=True)
class Mutation:
    mid: str
    gate: str
    what: str
    find: str
    repl: str
    regex: bool = False
    changed: bool = False  # add `repl` to the changed paths instead of editing the spec

    def apply(self, t: Tree) -> Tree:
        if self.changed:
            return replace(t, changed=(*t.changed, self.repl))
        if self.regex:
            new, n = re.subn(self.find, self.repl, t.spec, count=1)
        else:
            n, new = t.spec.count(self.find), t.spec.replace(self.find, self.repl, 1)
        if n < 1:
            raise AuditError(f"{self.mid}: anchor not found")
        return replace(t, spec=new)


_M = Mutation
MUTATIONS: tuple[Mutation, ...] = (
    _M("M-1", "G-CITE", "a cite past the end of `15`", "props (`15`:2933)", "props (`15`:99999)"),
    _M("M-2", "G-QUOTE", "a quote reworded off its line", "“at least one row selected”",
       "“at least one row is selected”"),
    _M("M-3", "G-AC", "a scenario name shortened",
       'AC 2 "Keyboard reorder is designed, not assumed"', 'AC 2 "Keyboard reorder is designed"'),
    _M("M-4", "G-ROWS", "a catalogue row renamed off §7", r"(\| 15 +\| )Speed( +\| `tape_speed`)",
       r"\1Speed of tape\2", True),
    _M("M-5", "G-MEMO", "a memo decision re-decided", r"(\| AD-3 +\|[^\n]*\| )honoured( +\|)",
       r"\1re-decided\2", True),
    _M("M-6", "G-KEYS", "the reorder keys dropped", "`Alt+↑` / `Alt+↓` on the focused row move it",
       "Arrow keys on the focused row move it"),
    _M("M-7", "G-GREY", "a breached cell loses its word", r"(breach-glyph slot +\| )Strong",
       r"\1—", True),
    _M("M-8", "G-SRC", "a row loses its source line", r"\n\| Range +\|[^\n]*", "", True),
    _M("M-9", "G-BOARDS", "a board marked drawn in the text leg",
       r"(`E20-D02 / 03 narrow-bar-readout`[^\n]*\| )PENDING", r"\1DRAWN", True),
    _M("M-10", "G-BQ", "a default recorded as ruled", "the ceiling.** ORCH-default built.",
       "the ceiling.** RULED: AGREE."),
    _M("M-11", "G-AMEND", "an owner document edited", "", "docs/plan/14-screens-catalogue.md",
       changed=True),
    _M("M-12", "G-PIN", "the base pin loses its short sha", "Base `origin/main` `b81479ab0110`",
       "Base `origin/main` `b81479a`"),
    _M("M-13", "G-NOCLOSE", "a closing keyword", "### 17.1 DoD\n",
       "### 17.1 DoD\n\nClo" + "ses #574.\n"),
    _M("M-14", "G-PUBLIC", "a local path", "### 17.2 Hand-offs (by name)",
       "### 17.2 Hand-offs (by name, " + "/" + "home/x)"),
    _M("M-15", "G-MUTLIST", "the list drifts", r"(\| M-1 +\| )G-CITE", r"\1G-AC", True),
)  # fmt: skip


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> Tree:
    return Tree((ROOT / SPEC_REL).read_text(encoding="utf-8"), changed_paths())


def report(results: Sequence[tuple[str, list[str]]]) -> int:
    fails = [(n, d) for n, d in results if d]
    for name, detail in results:
        line = f"FAIL {name}: {'; '.join(detail)}" if detail else f"PASS {name}"
        print(line.encode("ascii", "backslashreplace").decode("ascii"))
    print(f"FAIL {len(fails)}")
    return 1 if fails else 0


def check() -> int:
    return report(run(read_tree()))


def self_test() -> int:
    """The clean tree passes; each mutation FAILs its own gate and no other; disk unchanged."""
    before = [(ROOT / rel).read_bytes() for rel in OWN]
    loose = [k for k, v in globals().items() if isinstance(v, re.Pattern) and "<!--" in v.pattern]
    if any(not globals()[k].flags & re.DOTALL for k in loose):
        print("self-test: a comment regex lacks re.DOTALL")
        return 1
    tree = read_tree()
    base = [n for n, d in run(tree) if d]
    if base:
        print(f"self-test: baseline not clean: {base}")
        return 1
    if {m.gate for m in MUTATIONS} != {n for n, _ in GATES} or len(MUTATIONS) != len(GATES):
        print("self-test: not one mutation per gate")
        return 1
    bad = 0
    for m in MUTATIONS:
        try:
            failed = [n for n, d in run(m.apply(tree)) if d]
        except AuditError as exc:
            failed = [f"setup: {exc}"]
        ok = failed == [m.gate]
        bad += 0 if ok else 1
        print(f"{'ok ' if ok else 'BAD'} {m.mid} {m.gate}: {m.what} -> {failed}")
    if [(ROOT / rel).read_bytes() for rel in OWN] != before:
        print("self-test: files on disk changed")
        return 1
    print(f"self-test: {len(MUTATIONS) - bad} of {len(MUTATIONS)} mutations caught by their gate")
    return 1 if bad else 0


def fill() -> int:
    p = ROOT / SPEC_REL
    spec = p.read_text(encoding="utf-8")
    a = max(len(m.mid) for m in MUTATIONS)
    b = max(len(m.gate) for m in MUTATIONS)
    c = max(len(m.what) for m in MUTATIONS)
    table = f"| {'M':<{a}} | {'Gate':<{b}} | {'Mutation':<{c}} |\n| {'-' * a} | {'-' * b} | "
    table += f"{'-' * c} |\n" + "\n".join(
        f"| {m.mid:<{a}} | {m.gate:<{b}} | {m.what:<{c}} |" for m in MUTATIONS
    )
    start = spec.index("\n", spec.index("### 18.2 Mutations")) + 1
    p.write_text(spec[:start] + "\n" + table + "\n", encoding="utf-8", newline="\n")
    print("section 18.2 written")
    return 0


def main(argv: Sequence[str]) -> int:
    modes = {"check": check, "self-test": self_test, "fill": fill}
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    grp = ap.add_mutually_exclusive_group(required=True)
    for name in modes:
        grp.add_argument(f"--{name}", action="store_true")
    args = vars(ap.parse_args(list(argv)))
    return next(fn() for name, fn in modes.items() if args[name.replace("-", "_")])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
