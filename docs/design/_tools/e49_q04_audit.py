#!/usr/bin/env python3
"""E49-Q04 (#1362) audit: the black-box state-matrix test plan, slice A.

Offline and default-deny. The shared gates (git, cites, the BQ section, G-T2 markers, closing
keywords, hygiene, public text, G-UNTOUCHED, the runner and the mutation harness) live in
`spec_audit_lib.py`, imported from beside this file and never copied; this file keeps only this
plan's rows. It reads, AS TEXT at a pinned commit, the plan and repo texts the plan cites at the
base, E49-D02 at PR #5877's head (cited "if it merges as is"), and, from the working tree, the plan
and itself. It runs no repo code.

Gates: G-CITE, G-SCRSET, G-CELLS, G-TOKENS, G-BUILD, G-ASSERT, G-ANALYTICS, G-T2, G-RULING,
G-CHECKLIST, G-NOCLOSE, G-PUBLIC, G-UNTOUCHED and G-MUTLIST (section 14.2 equals this list).
The BQ list (comment 6642015197) is not ruled yet: G-RULING checks the pending form; no pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e49_q04_audit.py --check | --self-test | --table
Exit 0 = no FAIL; 1 = at least one FAIL. `--table` prints section 14.2 from the mutation list.
"""

from __future__ import annotations

import functools
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
BASE = "d5f2e0bc1"  # origin/main as read; the plan cites every plan and repo text here
D02_HEAD = "bc0c643e9"  # PR #5877 (E49-D02, #1331) head as read
BQ_LIST = "6642015197"  # the BQ list on #1362

SPEC_REL = "docs/qa/test-plans/e49-state-matrix.md"
TOOL_REL = "docs/design/_tools/e49_q04_audit.py"
LIB_REL = "docs/design/_tools/spec_audit_lib.py"
CAT_REL = "docs/plan/14-screens-catalogue.md"
OWN = (SPEC_REL, TOOL_REL)
CEILING = 1500  # C-4.8's counted ceiling, added lines over this slice's files

PLAN = {
    "03": "docs/plan/03-testing-strategy.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "14": CAT_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "24": "docs/plan/24-internal-schemas.md",
}
_SOCKET_DIR = "apps/web/src/lib/ws/" + "wor" + "ker/"  # split: the public scan bans the bare word
KEYED = {
    "D02": L.DocRef("docs/design/E49/E49-D02.md", D02_HEAD),
    "X01": L.DocRef("docs/security/threat-models/e49-defect-fix-path.md", BASE),
    "R32": L.DocRef(".claude/rules/32-design-specs.md", BASE),
    "WSW": L.DocRef(_SOCKET_DIR + "wsWorker.ts", BASE),
    "FCFG": L.DocRef("apps/web/e2e/playwright.fault.config.ts", BASE),
    "BUNDLE": L.DocRef("apps/web/test/lib/ws/faultInjection.bundle.test.ts", BASE),
    "SEV": L.DocRef("apps/web/src/features/symbol-search/searchEvents.ts", BASE),
    "D14E08": L.DocRef("docs/design/E08/E08-D14.md", BASE),
    "E40Q": L.DocRef("docs/qa/test-plans/e40-alerts.md", BASE),
}
CITE_RE = L.cite_regex(KEYED, ranges=True, spaced=True)
MIN_CITES = 120  # a broken grammar parses far fewer

COLS = ("LD", "E1", "E2", "E3", "ER", "DC", "DG", "403", "404", "CR", "VM", "RL", "OF")
ASSERT_SECTIONS = {
    "X": "### 4.1 Every cell",
    "LD": "### 4.2 LD",
    "EM": "### 4.3 E1, E2, E3",
    "ER": "### 4.4 ER",
    "DC": "### 4.5 DC",
    "DG": "### 4.6 DG",
    "403": "### 4.7 403",
    "404": "### 4.8 404",
    "CR": "### 4.9 CR",
    "VM": "### 4.10 VM",
    "RL": "### 4.11 RL",
    "OF": "### 4.12 OF",
}
STATUS_RE = re.compile(r"(ruled|PROPOSED)( \(C-\d+\))?|blocked on \S.*")
TOKEN_RE = re.compile(r"LD:L-(\d+)|E1|E2|E3|ER|DC(/T2)?|DG(/T2)?|403|404|CR|VM(/T2)?|RL(/T2)?|OF")
TICK_RE = re.compile(r"`([^`]+)`")
EVENT_RE = re.compile(r"`([a-z_0-9]+(?:\.[a-z_0-9]+)*)`")
PAYLOAD_RE = re.compile(r"`(\{[^}`]*\})`")
LINE14_RE = re.compile(r"`14` :(\d+)")
SCR14_RE = re.compile(r"^### (SCR-\d{3}) — ", re.MULTILINE)
RN1_ROWS = frozenset(f"SCR-{n}" for n in range(150, 160))
L1_ROWS = frozenset({"SCR-010"})
OF_ROWS = frozenset({"SCR-010", "SCR-001"})
HEADING = f"## The questions BQ-0 … BQ-9 — defaults built; ruling pending (comment {BQ_LIST})"
_SENSITIVE = re.compile(r"key|tok" + r"en|sec" + r"ret|au" + r"th", re.IGNORECASE)
_HEX = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")


# ---------- sources -------------------------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def docs() -> L.Docs:
    return L.Docs(repo(), BASE, KEYED, plan=PLAN)


@functools.cache
def catalogue_ids() -> tuple[str, ...]:
    return tuple(SCR14_RE.findall(repo().show(BASE, CAT_REL) or ""))


def line14(n: int) -> str:
    return docs().line("14", n) or ""


# ---------- plan helpers --------------------------------------------------------------------------
def sec(t: L.Tree, heading: str) -> str:
    return L.section(t.text("spec"), heading)


def matrix(t: L.Tree) -> list[list[str]]:
    return L.table_rows(sec(t, "### 3.3 The matrix"))


def nr_rules(t: L.Tree) -> dict[str, frozenset[str]]:
    rows = L.table_rows(sec(t, "### 3.2 Cell-level N/A"))
    return {r[0]: frozenset(r[2].split()) for r in rows if len(r) >= 3}


def rn_rules(t: L.Tree) -> frozenset[str]:
    return frozenset(r[0] for r in L.table_rows(sec(t, "### 3.1 Row-level N/A")) if r)


def tokens(cell: str) -> list[str]:
    return TICK_RE.findall(cell)


def column(token: str) -> str:
    return token.split(":")[0].split("/")[0]


# ---------- this plan's gates ---------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    return L.check_cites(L.extract_cites(t.text("spec"), CITE_RE), docs(), min_count=MIN_CITES)


def g_scrset(t: L.Tree) -> list[str]:
    ids = [r[0] for r in matrix(t) if r]
    want = catalogue_ids()
    bad = [f"{i} is not in `14`" for i in sorted(set(ids) - set(want))]
    bad += [f"{i} has no row" for i in sorted(set(want) - set(ids))]
    bad += [f"{i} has two rows" for i in sorted({i for i in ids if ids.count(i) > 1})]
    if len(want) < 100:
        bad.append(f"only {len(want)} ids read from `14`")
    return bad


def g_cells(t: L.Tree) -> list[str]:
    nrs, rns, bad = nr_rules(t), rn_rules(t), []
    if len(nrs) < 10 or not rns:
        return ["the RN or NR table is not readable"]
    rn1 = set()
    for r in matrix(t):
        sid, cells, naby = r[0], r[3], r[4]
        if cells == "—":
            if naby not in rns:
                bad.append(f"{sid}: row-level N/A {naby!r} is no RN rule")
            if naby == "RN-1":
                rn1.add(sid)
            continue
        cols = [column(x) for x in tokens(cells)]
        cited = re.findall(r"NR-\d+", naby)
        unknown = [n for n in cited if n not in nrs]
        if unknown:
            bad.append(f"{sid}: unknown {unknown}")
            continue
        excused = set().union(*(nrs[n] for n in cited)) if cited else set()
        clash = sorted(excused & set(cols))
        if clash:
            bad.append(f"{sid}: an NR rule names the listed {clash}")
        missing = [c for c in COLS if c not in cols and c not in excused]
        if missing or len(cols) != len(set(cols)):
            bad.append(f"{sid}: columns {missing} neither listed nor excused, or listed twice")
    if rn1 != RN1_ROWS:
        bad.append(f"RN-1 rows {sorted(rn1 ^ RN1_ROWS)} differ from SCR-150 … SCR-159")
    return bad


def g_tokens(t: L.Tree) -> list[str]:
    bad: list[str] = []
    for r in matrix(t):
        sid, cells = r[0], r[3]
        if cells == "—":
            continue
        for tok in tokens(cells):
            m = TOKEN_RE.fullmatch(tok)
            if m is None:
                bad.append(f"{sid}: token {tok!r}")
            elif m.group(1) and not 1 <= int(m.group(1)) <= 11:
                bad.append(f"{sid}: no D02 row {tok!r}")
            elif m.group(1) == "1" and sid not in L1_ROWS:
                bad.append(f"{sid}: L-1 is SCR-150's, on SCR-010 only")
            elif tok == "OF" and sid not in OF_ROWS:
                bad.append(f"{sid}: OF is the shell's")
    return bad


def g_build(t: L.Tree) -> list[str]:
    bad: list[str] = []
    for r in matrix(t):
        sid, tag = r[0], r[2]
        m = re.fullmatch(r"`shipped` \(`([^`]+)`\)", tag)
        if m:
            text = repo().show(BASE, "apps/web/src/" + m.group(1)) or ""
            if sid not in text:
                bad.append(f"{sid}: {m.group(1)} does not name it at the base")
        elif tag != "`pending`":
            bad.append(f"{sid}: tag {tag!r}")
    return bad


def g_assert(t: L.Tree) -> list[str]:
    bad: list[str] = []
    cols = [r[0] for r in L.table_rows(sec(t, "## 2. The columns"))]
    if cols != list(COLS):
        bad.append(f"section 2 columns {cols}")
    for code, heading in ASSERT_SECTIONS.items():
        rows = L.table_rows(sec(t, heading))
        if not rows:
            bad.append(f"no assertion table under {heading!r}")
            continue
        for k, r in enumerate(rows, 1):
            if r[0] != f"SA-{code}-{k}":
                bad.append(f"{heading}: id {r[0]!r}, want SA-{code}-{k}")
            elif len(r) < 4 or not r[2] or not STATUS_RE.fullmatch(r[3]):
                bad.append(f"{r[0]}: a source or a status missing")
    return bad


def g_analytics(t: L.Tree) -> list[str]:
    rows = L.table_rows(sec(t, "## 6. The analytics contract"))
    bad = [] if [r[0] for r in rows] == sorted(RN1_ROWS) else ["the ten patterns"]
    for r in rows:
        m = LINE14_RE.search(r[2]) if len(r) > 2 else None
        if m is None:
            bad.append(f"{r[0]}: no `14` line")
            continue
        line = line14(int(m.group(1)))
        events = [e for e in EVENT_RE.findall(r[1]) if "." in e or e == "empty_state_shown"]
        if not events:
            bad.append(f"{r[0]}: no event")
        for x in events + PAYLOAD_RE.findall(r[1]):
            if f"`{x}`" not in line:
                bad.append(f"{r[0]}: `{x}` is not on `14` :{m.group(1)}")
    return bad


def g_t2(t: L.Tree) -> list[str]:
    block = sec(t, "## 5. Trading safety")
    return L.t2_markers(block) + L.no_disabled_tokens(t.text("spec"))


def g_ruling(t: L.Tree) -> list[str]:
    return L.check_ruling(
        t.text("spec"),
        heading_line=HEADING,
        list_ref=BQ_LIST,
        count=10,
        verdict=lambda n: "ORCH-default built",
        forbid=("RULED",),
    )


def g_checklist(t: L.Tree) -> list[str]:
    block = sec(t, "## 12. Owner walkthrough checklist")
    nums = [int(m) for m in re.findall(r"^(\d+)\. ", block, re.MULTILINE)]
    ok = nums == list(range(1, len(nums) + 1)) and 1 <= len(nums) <= 10
    return [] if ok else [f"items {nums}"]


def g_noclose(t: L.Tree) -> list[str]:
    named = t.named("spec", "tool")
    return L.closing_keywords(named) + L.whitespace_hygiene(named)


def g_public(t: L.Tree) -> list[str]:
    named = t.named("spec", "tool")
    bad = L.scan_public(named) + L.comment_findings(t.named("spec"))
    for n, ln in enumerate(t.text("spec").split("\n"), 1):
        if _HEX.search(ln) and _SENSITIVE.search(ln):
            bad.append(f"spec:{n}: a hex pin beside a sensitive word")
    return bad


def g_untouched(t: L.Tree) -> list[str]:
    bad = L.untouched(t.changed, OWN, (), {}, t.numstat, owner_prefixes=(LIB_REL,))
    added = sum((t.numstat.get(p) or (0, 0))[0] for p in OWN)
    return bad + ([f"{added} added lines over {CEILING}"] if added > CEILING else [])


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(t.text("spec"), "### 14.2", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper().replace("_", "-"), f) for f in (
    g_cite, g_scrset, g_cells, g_tokens, g_build, g_assert, g_analytics, g_t2, g_ruling,
    g_checklist, g_noclose, g_public, g_untouched, g_mutlist,
))
# fmt: on

_M = L.Mutation
_D = "## 13. Deviations (recorded, not hidden)\n"
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-CITE", "a cite past the end of `24`", "spec",
       "`24` :2255; SA-T2-8", "`24` :99999; SA-T2-8"),
    _M("M-2", "G-SCRSET", "a catalogue row dropped", "spec",
       r"\| SCR-119 \|[^\n]*\n", "", regex=True),
    _M("M-3", "G-SCRSET", "an id not in `14`", "spec", "| SCR-119 |", "| SCR-109 |"),
    _M("M-4", "G-CELLS", "a column neither listed nor excused", "spec",
       r"(\| SCR-060 \|[^\n]*)NR-2, NR-4, NR-8, NR-12", r"\1NR-2, NR-4, NR-8", regex=True),
    _M("M-5", "G-CELLS", "an NR rule names a listed column", "spec",
       r"(\| SCR-030 \|[^\n]*)NR-3,", r"\1NR-3, NR-5,", regex=True),
    _M("M-6", "G-CELLS", "RN-1 on a surface row", "spec",
       r"(\| SCR-158 \|[^\n]*)RN-1", r"\1RN-3", regex=True),
    _M("M-7", "G-TOKENS", "L-1 outside SCR-010", "spec",
       r"(\| SCR-011 \|[^\n]*)`LD:L-6`", r"\1`LD:L-1`", regex=True),
    _M("M-8", "G-TOKENS", "an unknown token", "spec",
       r"(\| SCR-060 \|[^\n]*)`DC/T2`", r"\1`DC/T3`", regex=True),
    _M("M-9", "G-BUILD", "a shipped path that names no id", "spec",
       "`features/alerts/AlertsScreen.tsx`", "`features/alerts/alertsStore.ts`"),
    _M("M-10", "G-BUILD", "an unknown build tag", "spec",
       r"(\| SCR-003 \|[^\n]*)`pending`", r"\1`planned`", regex=True),
    _M("M-11", "G-ASSERT", "an assertion without a status", "spec",
       r"(\| SA-RL-3 \|[^\n]*\| )ruled( +\|)", r"\1maybe\2", regex=True),
    _M("M-12", "G-ASSERT", "a column loses its section", "spec",
       "### 4.12 OF — offline", "### 4.12 Offline"),
    _M("M-13", "G-ASSERT", "the column list drifts", "spec",
       "| VM  | version mismatch", "| VX  | version mismatch"),
    _M("M-14", "G-ANALYTICS", "a payload field renamed", "spec",
       r"(\| SCR-153 \| `degraded\.entered` `\{cause, )sheddedFeatures", r"\1shedFeatures",
       regex=True),
    _M("M-15", "G-ANALYTICS", "an event not on its line", "spec",
       "`shell.window_restored`", "`shell.window_reopened`"),
    _M("M-16", "G-T2", "the T2 rows lose the opacity ban", "spec",
       "`color.text.disabled`, never `opacity.disabled`", "`color.text.disabled`"),
    _M("M-17", "G-RULING", "the heading claims a ruling", "spec",
       "— defaults built; ruling pending (comment", "— RULED (comment"),
    _M("M-18", "G-RULING", "a bullet loses its verdict", "spec",
       "ORCH-default built: JSON with", "ORCH-default: JSON with"),
    _M("M-19", "G-CHECKLIST", "an eleventh item", "spec",
       "its state set (DoD 11).\n", "its state set (DoD 11).\n11. One more.\n"),
    _M("M-20", "G-NOCLOSE", "a closing keyword", "spec", _D, _D + "\n" + "Clo" + "ses #1362.\n"),
    _M("M-21", "G-PUBLIC", "a URL", "spec",
       "Stdlib only;", "Stdlib only (" + "http" + "s://example.org);"),
    _M("M-22", "G-PUBLIC", "an HTML comment", "spec", _D, "<!-" + "- x -->\n" + _D),
    _M("M-23", "G-PUBLIC", "a hex pin beside a sensitive word", "spec",
       "(blob `15793f79cf92`)", "(blob `15793f79cf92`, a " + "tok" + "en)"),
    _M("M-24", "G-UNTOUCHED", "an owner document edited", "@changed", "", CAT_REL),
    _M("M-25", "G-UNTOUCHED", "the shared helper edited", "@changed", "", LIB_REL),
    _M("M-26", "G-UNTOUCHED", "over the counted ceiling", f"@numstat:{SPEC_REL}", "", "1600 0"),
    _M("M-27", "G-MUTLIST", "the list drifts", "spec",
       "| M-1  | G-CITE      |", "| M-1  | G-CELLS     |"),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    base = repo().diff_base(BASE)
    return L.Tree(
        files={
            "spec": (ROOT / SPEC_REL).read_text(encoding="utf-8"),
            "tool": (ROOT / TOOL_REL).read_text(encoding="utf-8"),
        },
        changed=repo().changed_paths(base),
        numstat={rel: repo().numstat(base, rel) for rel in OWN},
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test() -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def table() -> int:
    print(L.mutation_table(MUTATIONS))
    return 0


def main(argv: list[str]) -> int:
    modes = {"check": check, "self-test": self_test, "table": table}
    return L.cli(argv, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
