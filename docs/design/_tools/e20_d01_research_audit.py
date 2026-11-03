#!/usr/bin/env python3
"""E20-D01 (#573) check: the Deep Stats UX-research memo (text leg; boards pending).

Standalone, stdlib only, offline and default-deny. The BQ ruling of record (comment 6608089429)
keeps the shared audit helper out of this PR until it is on `main`, so this file carries its own
small primitives. It reads, AS TEXT at the pinned base, the plan, design, backlog and fixture
texts the memo cites, and, from the working tree, the memo. It runs no other repo code.

Gates: G-CITE, G-QUOTE, G-AC, G-CARDS, G-DEFAULT, G-COMPACT, G-THRESH, G-TESTABLE, G-HEUR,
G-PROPOSED, G-NOINVENT, G-COMP, G-BOARDS, G-BQ, G-HANDOFF, G-AMEND, G-PIN, G-NOCLOSE, G-PUBLIC
and G-MUTLIST (section 14.2 equals this tool's list). G-COMP checks only that a vendor row carries a URL and a fetched date,
or says "unsourced observation": the accuracy of a vendor quote is checked by hand.

Usage (from the repo root):
  python3 -I docs/design/_tools/e20_d01_research_audit.py --check | --self-test
  python3 -I docs/design/_tools/e20_d01_research_audit.py --fill   (writes section 14.2)
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
BASE = "b81479ab01109ee1efc6cdedb411bd5f75ecdd66"  # origin/main when the ruling was folded
BQ_LIST = "6599274288"  # the BQ list on #573
RULING = "6608089429"  # the ruling of record on #573
TICKET = "E20-D01"
VERDICTS = {0: "AMEND", 5: "AMEND", 8: "AMEND"}  # every other BQ: AGREE

MEMO_REL = "docs/design/research/e20-deep-stats.md"
TOOL_REL = "docs/design/_tools/e20_d01_research_audit.py"
OWN = (MEMO_REL, TOOL_REL)
BACKLOG_REL = "docs/plan/backlog/E20.json"
KEYED = {
    "README": "docs/design/README.md",
    "E18-D02": "docs/design/E18/E18-D02.md",
    "E20.json": BACKLOG_REL,
    "R32": ".claude/rules/32-design-specs.md",
    "D04": "docs/research/digests/04-deepcharts-deepchart.digest.md",
    "D09": "docs/design/E47/E47-D09.md",
    "D23": "docs/research/digests/23-views-and-screens.digest.md",
    "FXR": "packages/fixtures/bybit/2026-10-05/README.trades.md",
    "MAN": "packages/fixtures/bybit/2026-10-05/manifest.json",
}
# Source pins: (document, line, text that must stand on it at BASE).
SOURCE_PINS = (
    ("24", 1207, "**Deep Stats rows (per-bar statistics strip)**"),
    ("24", 1308, "(21 rows)"),
    ("11", 1914, "Delta% > 60"),
    ("14", 870, "threshold 0–100 %"),
    ("15", 2598, "overflow after 12 rows"),
    ("15", 2938, "12 rows update budget"),
    ("20", 871, "demo has no separate public feed"),
    ("D09", 173, "Deep Stats rows"),
)

BQ_HEADING = "## 1. Brief questions"
BQ_HEADING_LINE = f"{BQ_HEADING} (BQ list, issue #573 comment {BQ_LIST})"
BQ_STATUS = f"Status: **RULED (comment {RULING})**."
BQ_ID = re.compile(r"- \*\*(BQ-\d+)")
RULES = tuple(f"({n}) " for n in range(1, 8))
HANDOFF_ROWS = ("`16`:743 (item 7)", "`16`:659 (§11.5)", "checklist posted on #573")
STATUSES = ("done (text)", "done", "heuristic-only", "open", "design approval pending")
AC3_VERDICTS = ("refuted as written", "confirmed")
VERDICT_RE = re.compile(r"^\*\*Verdict \(AC 3\): ([a-z ]+)\.\*\*$", re.MULTILINE)
CURLY_RE = re.compile(r"“([^”]+)”")
QUOTE_MIN = 12
OWNER_RE = re.compile(r"\bE20-[A-Z]\d\d #\d+\b")
HEX40 = re.compile(r"\b[0-9a-f]{40}\b")
FINDINGS = 21  # F-1..F-21, every one heuristic: no session was run
PROPOSED_HEADS = (
    "### 6.1 Default row set (PROPOSED)",
    "### 6.2 Compact row set (PROPOSED)",
    "## 9. Proposed decisions AD-1..AD-8 (ranked; heuristic, PROPOSED)",
)
# Session data the memo must never carry: a participant count, a share of traders, a percentage
# in brackets after a count.
INVENTED_RE = re.compile(
    r"\b\d+ (?:of \d+ )?(?:traders|participants|respondents|users|sessions)\b|\(\d+ ?%\)"
)
FETCHED_RE = re.compile(r"<https://\S+> · fetched 20\d\d-\d\d-\d\d")
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
def show(rel: str) -> tuple[str, ...] | None:
    text = git("show", f"{BASE}:{rel}")
    return None if text is None else tuple(text.split("\n"))


@functools.cache
def doc_lines(key: str) -> tuple[str, ...] | None:
    if key in KEYED:
        return show(KEYED[key])
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


@functools.cache
def catalogue() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """`24` §7's Deep Stats rows at the pin: (row label, metric names)."""
    lines = doc_lines("24") or ()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("**Deep Stats rows"))
    got = table_rows("\n".join(lines[start : start + 40]))
    return tuple((r[0], names_of(r[1])) for r in got if len(r) > 1)


@functools.cache
def scenario_names() -> tuple[str, ...]:
    tickets = json.loads("\n".join(show(BACKLOG_REL) or ("[]",)))
    body = next(str(t.get("body", "")) for t in tickets if t.get("key") == TICKET)
    return tuple(n.strip() for n in re.findall(r"Scenario: (.+)", body))


def names_of(cell: str) -> tuple[str, ...]:
    return tuple(re.findall(r"`([a-z_]+)`", cell))


# ---------- the tree gates read -------------------------------------------------------------------
@dataclass(frozen=True)
class Tree:
    spec: str
    changed: tuple[str, ...] = ()

    def rows(self, heading: str) -> list[list[str]]:
        return table_rows(section(self.spec, heading))

    def defaults(self) -> list[str]:
        return [r[1] for r in self.rows("### 6.1 Default row set") if len(r) > 1]


# ---------- gates ---------------------------------------------------------------------------------
def g_cite(t: Tree) -> list[str]:
    got = cites(t.spec)
    bad = [] if len(got) >= 40 else [f"only {len(got)} cites parsed"]
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
    names, trace = scenario_names(), t.rows("## Acceptance-criteria trace")
    bad = [] if len(names) == 3 else [f"{len(names)} scenarios at the pin"]
    for i, name in enumerate(names, 1):
        if not any(r[0].startswith(f'AC {i} "{name}"') for r in trace):
            bad.append(f"AC {i} not verbatim")
    return bad + [f"status of {r[0][:30]}" for r in trace if len(r) < 4 or r[2] not in STATUSES]


def g_cards(t: Tree) -> list[str]:
    got = t.rows("## 5. The row catalogue")
    want = set(catalogue())
    have = {(r[1], names_of(r[2])) for r in got if len(r) > 2}
    bad = [] if len(want) == 20 else [f"{len(want)} catalogue rows at the pin"]
    if have != want or len(got) != len(want):
        bad.append(f"cards differ from `24` §7: {sorted(x[0] for x in have ^ want)}")
    if [r[0] for r in got] != [str(i) for i in range(1, len(got) + 1)]:
        bad.append("ranks not 1..n")
    return bad


def g_default(t: Tree) -> list[str]:
    got, cat = t.rows("### 6.1 Default row set"), dict(catalogue())
    bad = [] if 4 <= len(got) <= 6 else [f"{len(got)} default rows"]
    for r in got:
        if len(r) < 5 or cat.get(r[1]) != names_of(r[2]):
            bad.append(f"row {r[1] if len(r) > 1 else '?'} is not a `24` §7 label + metric")
        elif not re.search(r"\bN\d", r[3]) or not re.search(r"\bF-\d+", r[3]):
            bad.append(f"row {r[1]} has no N-id and F-id")
    tier1 = [r[1] for r in t.rows("## 5. The row catalogue") if len(r) > 4 and r[4] == "1"]
    return bad + ([] if tier1 == t.defaults() else ["§5 tier 1 differs from the default set"])


def g_compact(t: Tree) -> list[str]:
    got = [r[1] for r in t.rows("### 6.2 Compact row set") if len(r) > 1]
    if not 2 <= len(got) <= 3:
        return [f"{len(got)} compact rows"]
    return [] if got == t.defaults()[: len(got)] else ["compact set is not the default prefix"]


def g_thresh(t: Tree) -> list[str]:
    found = VERDICT_RE.findall(section(t.spec, "## 8. Threshold semantics"))
    if len(found) != 1 or found[0] not in AC3_VERDICTS:
        return [f"verdict lines {found}"]
    ac3 = [r for r in t.rows("## Acceptance-criteria trace") if r[0].startswith("AC 3 ")]
    said = [m.group(1) for r in ac3 for m in re.finditer(r"verdict: ([a-z ]+?);", " ".join(r))]
    return [] if said == [found[0]] else [f"AC 3 trace says {said}, §8 says {found[0]}"]


def g_testable(t: Tree) -> list[str]:
    got = t.rows("## 9. Proposed decisions")
    bad = [] if 5 <= len(got) <= 8 else [f"{len(got)} decisions"]
    if [r[0] for r in got] != [f"AD-{i}" for i in range(1, len(got) + 1)]:
        bad.append("ids not AD-1..AD-n")
    for r in got:
        if len(r) != 6 or not r[1]:
            bad.append(f"{r[0]} cells")
        elif not r[2].startswith("satisfies if ") or not r[3].startswith("violates if "):
            bad.append(f"{r[0]} lacks a satisfies or violates clause")
        elif not re.search(r"\bF-\d+", r[4]) or not OWNER_RE.search(r[5]):
            bad.append(f"{r[0]} lacks a finding or an owner ticket")
    return bad


def g_heur(t: Tree) -> list[str]:
    got = t.rows("## 3. Heuristic evaluation")
    bad = [] if len(got) == FINDINGS else [f"{len(got)} findings"]
    if [r[0] for r in got] != [f"F-{i}" for i in range(1, len(got) + 1)]:
        bad.append("ids not F-1..F-n")
    return bad + [
        f"{r[0]} is not `(heuristic)`" for r in got if not r[1].startswith("`(heuristic)` ")
    ]


def g_proposed(t: Tree) -> list[str]:
    lines = t.spec.split("\n")
    bad = [f"heading {h[:30]}" for h in PROPOSED_HEADS if h not in lines]
    block = section(t.spec, "## 9. Proposed decisions").split("\n")
    head = next((ln for ln in block if ln.startswith("|")), "")
    return bad + ([] if "| Decision (PROPOSED) " in head else ["AD header lacks PROPOSED"])


def g_noinvent(t: Tree) -> list[str]:
    return [f"session data: {m.group(0)}" for m in INVENTED_RE.finditer(t.spec)]


def g_comp(t: Tree) -> list[str]:
    got = t.rows("## 10. Competitive review")
    bad = [] if got else ["no rows"]
    return bad + [
        f"{r[0][:40]} has no URL and fetched date"
        for r in got
        if not FETCHED_RE.search(r[-1]) and r[-1] != "unsourced observation"
    ]


def g_boards(t: Tree) -> list[str]:
    got = t.rows("## 0. Research boards")
    bad = [] if 0 < len(got) <= 10 else [f"{len(got)} boards"]
    for r in got:
        if len(r) < 5 or r[4] != "PENDING" or not r[1].startswith(f"`{TICKET} / {r[0]} "):
            bad.append(f"board {r[0] if r else '?'}")
        elif "light" in r[3]:
            bad.append(f"board {r[0]} is a light twin")
    if "**Not drawn — the text is binding**" not in t.spec:
        bad.append("not-drawn paragraph")
    return bad


def g_bq(t: Tree) -> list[str]:
    body = section(t.spec, BQ_HEADING)
    bad = [] if BQ_HEADING_LINE in t.spec.split("\n") else ["heading"]
    if BQ_STATUS not in body:
        bad.append("the RULED status line")
    bullets = [ln for ln in body.split("\n") if BQ_ID.match(ln)]
    ids = [m.group(1) for b in bullets if (m := BQ_ID.match(b))]
    if ids != [f"BQ-{n}" for n in range(10)]:
        bad.append(f"ids {ids}")
    for n, b in enumerate(bullets):
        if f"RULED: {VERDICTS.get(n, 'AGREE')}. Built as:" not in b:
            bad.append(f"BQ-{n} ruling")
    return bad + (["a default still pending"] if "Default built" in body else [])


def g_handoff(t: Tree) -> list[str]:
    body = section(t.spec, BQ_HEADING)
    rules = body[body.find("**Hand-off-pack rules") :]
    bad = [f"rule {r.strip()}" for r in RULES if r not in rules]
    if "**Added by the ruling (missed).**" not in body:
        bad.append("the missed riders")
    trace = " ".join(r[0] for r in t.rows("## Acceptance-criteria trace"))
    return bad + [f"trace row {h}" for h in HANDOFF_ROWS if h not in trace]


def g_amend(t: Tree) -> list[str]:
    return [p for p in t.changed if p not in OWN]


def g_pin(t: Tree) -> list[str]:
    bad = [] if f"**Inputs pinned:** `main` `{BASE[:12]}`;" in t.spec else ["pin line"]
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
    return [] if t.rows("### 14.2 Mutations") == want else ["§14.2 differs from the tool"]


Gate = tuple[str, Callable[[Tree], list[str]]]
GATES: tuple[Gate, ...] = tuple(
    ("G-" + f.__name__[2:].upper(), f)
    for f in (
        g_cite, g_quote, g_ac, g_cards, g_default, g_compact, g_thresh, g_testable, g_heur,
        g_proposed, g_noinvent, g_comp, g_boards, g_bq, g_handoff, g_amend, g_pin, g_noclose,
        g_public, g_mutlist,
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
    changed: bool = False  # add `repl` to the changed paths instead of editing the memo

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
    _M("M-1", "G-CITE", "a cite past the end of `11`", "`11`:1880–1882", "`11`:99999"),
    _M("M-2", "G-QUOTE", "a quote reworded off its line", "“Compact mode [x]”", "“Compact mode [on]”"),
    _M("M-3", "G-AC", "a scenario name shortened",
       'AC 2 "Narrow-bar behaviour has a decided answer"', 'AC 2 "Narrow-bar behaviour"'),
    _M("M-4", "G-CARDS", "an SCR-033 extra replaces a `24` §7 card",
       r"\| CumΔ Change +\| `cvd_bar_change`", "| Big-trade count | `cvd_bar_change`", True),
    _M("M-5", "G-DEFAULT", "a default row renamed off `24` §7",
       r"# Trades( +\| `bar_trade_count` +\| N8; F-8)", r"Number of Trades\1", True),
    _M("M-6", "G-COMPACT", "the compact set leaves the default prefix",
       r"(\| 3 +\| )Total Volume( +\| `bar_volume` +\| Vol)", r"\1# Trades\2", True),
    _M("M-7", "G-THRESH", "the verdict word drifts from the trace",
       "**Verdict (AC 3): refuted as written.**", "**Verdict (AC 3): confirmed.**"),
    _M("M-8", "G-TESTABLE", "AD-6 loses its violates clause",
       "violates if a strong negative bar", "fails if a strong negative bar"),
    _M("M-9", "G-HEUR", "a finding loses `(heuristic)`",
       r"(\| F-2 +\| )`\(heuristic\)` ", r"\1", True),
    _M("M-10", "G-PROPOSED", "the AD header drops PROPOSED", "| Decision (PROPOSED) ",
       "| Decision            "),
    _M("M-11", "G-NOINVENT", "an invented session count", "## 4. Persona walkthrough\n",
       "## 4. Persona walkthrough\n\n5 of 8 traders (62 %) chose the default set.\n"),
    _M("M-12", "G-COMP", "a vendor row loses its fetched date",
       "<https://deepcharts.com/features/deepchart> · fetched 2026-11-03",
       "<https://deepcharts.com/features/deepchart>"),
    _M("M-13", "G-BOARDS", "a board marked drawn in the text leg",
       r"(`E20-D01 / 05 narrow-bar-collapse-readout`[^\n]*\| )PENDING", r"\1DRAWN", True),
    _M("M-14", "G-BQ", "an AMEND bullet recorded as AGREE",
       "standing rules.** RULED: AMEND.", "standing rules.** RULED: AGREE."),
    _M("M-15", "G-HANDOFF", "a hand-off rule dropped", "(6) `16`:743", "`16`:743"),
    _M("M-16", "G-AMEND", "an owner document edited", "", "docs/plan/11-user-stories.md",
       changed=True),
    _M("M-17", "G-PIN", "the pin line loses its short sha", "`main` `b81479ab0110`;",
       "`main` `b81479a`;"),
    _M("M-18", "G-NOCLOSE", "a closing keyword", "## 15. References\n",
       "## 15. References\n\nClo" + "ses #573.\n"),
    _M("M-19", "G-PUBLIC", "a local path", "Companion check:",
       "Companion check (" + "/" + "home/x):"),
    _M("M-20", "G-MUTLIST", "the list drifts", r"(\| M-1 +\| )G-CITE", r"\1G-AC", True),
)  # fmt: skip


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> Tree:
    return Tree((ROOT / MEMO_REL).read_text(encoding="utf-8"), changed_paths())


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
    p = ROOT / MEMO_REL
    spec = p.read_text(encoding="utf-8")
    a = max(len(m.mid) for m in MUTATIONS)
    b = max(len(m.gate) for m in MUTATIONS)
    c = max(len(m.what) for m in MUTATIONS)
    table = f"| {'M':<{a}} | {'Gate':<{b}} | {'Mutation':<{c}} |\n| {'-' * a} | {'-' * b} | "
    table += f"{'-' * c} |\n" + "\n".join(
        f"| {m.mid:<{a}} | {m.gate:<{b}} | {m.what:<{c}} |" for m in MUTATIONS
    )
    start = spec.index("\n", spec.index("### 14.2 Mutations")) + 1
    end = spec.index("\n## 15. References")
    p.write_text(spec[:start] + "\n" + table + "\n" + spec[end:], encoding="utf-8", newline="\n")
    print("section 14.2 written")
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
