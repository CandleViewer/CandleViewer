#!/usr/bin/env python3
"""E19-D04 (#439) audit: the profile preset, period-anchoring and drawing-anchor flow spec.

Offline and default-deny. The shared gates (git, cites, pins, G-T2 vocabulary, closing keywords,
hygiene, public text, R7, G-UNTOUCHED, the runner and the mutation harness) live in
`spec_audit_lib.py`; this file keeps only E19-D04's rows. It reads, AS TEXT at a pinned commit,
the plan and design texts the spec cites at the base, E19-D02's spec at PR #5487's head and
E19-D03's at PR #5517's head, and, from the working tree, the spec, the pins file and itself. It
runs no repo code.

Gates: G-CITE, G-QUOTE, G-VERSION, G-AC, G-PRESET-OPS, G-MATRIX, G-ENV, G-KEYS, G-DELETE,
G-PAYLOAD, G-STATES, G-BOARDS, G-T2, G-TOKENS, G-PENPOT, G-RULING, G-RULED, G-NOCLOSE, G-PUBLIC,
G-UNTOUCHED and G-MUTLIST (section 15.2 equals this tool's list).
Pins (G-RULED): each BQ bullet's sha256[:16] in `e19_d04_ruled_pins.txt`; `--repin-ruled` is the
only writer. The BQ list 6582998807 has no ruling yet: G-RULING checks the "defaults built;
ruling pending" form and flips to the RULED form when the ruling of record is folded.

Usage (from the repo root):
  python3 -I docs/design/_tools/e19_d04_audit.py --check | --self-test | --repin-ruled
Exit 0 = no FAIL; 1 = at least one FAIL.
"""

from __future__ import annotations

import functools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_audit_lib as L  # the shared helper sits beside this file

ROOT = Path(__file__).resolve().parents[3]
BASE = "d23ec8bd7"  # origin/main at the BQ list; every plan and keyed cite is read here
D02_HEAD = "bed73afaa"  # PR #5487 (E19-D02, #416) head; re-pinned to its merge commit
D03_HEAD = "811292427"  # PR #5517 (E19-D03, #438) head read; re-pinned to its merge commit
D02_PR, D03_PR = "#5487", "#5517"
BQ_LIST = "6582998807"  # the BQ list on #439; no ruling of record yet

SPEC_REL = "docs/design/E19/E19-D04.md"
TOOL_REL = "docs/design/_tools/e19_d04_audit.py"
LIB_REL = "docs/design/_tools/spec_audit_lib.py"
PIN_REL = "docs/design/_tools/e19_d04_ruled_pins.txt"
CAT_REL = "docs/plan/14-screens-catalogue.md"
OWN = (SPEC_REL, TOOL_REL, LIB_REL, PIN_REL)
BACKLOG_REL = "docs/plan/backlog/E19.json"

PLAN = {
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "14": CAT_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "24": "docs/plan/24-internal-schemas.md",
    "26": "docs/plan/26-chart-engine-design.md",
    "30": "docs/plan/30-release-roadmap.md",
}
KEYED = {
    "D02": L.DocRef("docs/design/E19/E19-D02.md", D02_HEAD),
    "D03": L.DocRef("docs/design/E19/E19-D03.md", D03_HEAD),
    "MEMO": L.DocRef("docs/design/research/e19-profiles.md", BASE),
    "D02E14": L.DocRef("docs/design/E14/E14-D02.md", BASE),
    "D07E14": L.DocRef("docs/design/E14/E14-D07.md", BASE),
    "D09E47": L.DocRef("docs/design/E47/E47-D09.md", BASE),
    "D08E08": L.DocRef("docs/design/E08/E08-D08.md", BASE),
    "D02E17": L.DocRef("docs/design/E17/E17-D02.md", BASE),
    "D09E09": L.DocRef("docs/design/E09/E09-D09.md", BASE),
    "KM": L.DocRef("apps/web/src/keymap/keymap.json", BASE),
    "R32": L.DocRef(".claude/rules/32-design-specs.md", BASE),
    "README": L.DocRef("docs/design/README.md", BASE),
    "E19J": L.DocRef(BACKLOG_REL, BASE),
}
CITE_RE = L.cite_regex(KEYED, ranges=True, spaced=True)
MIN_CITES = 150  # a broken grammar parses far fewer

PRESET_ITEMS = (
    "`Session value` (W-2), then the user's presets",
    '"No saved presets yet" (W-10)',
    "`Save as new…` (W-3)",
    "`Save changes to {name}` (W-4)",
    "`Rename…` (W-5)",
    "`Delete…` (W-6)",
    "`Reset to {name}` (W-7)",
    "`Restore previous settings` (W-18)",
)
WRITES = frozenset(PRESET_ITEMS[2:6])  # the four writes: T2 under view-as (section 1.4)
OWNERS = ("Chart", "Drawing", "Profile", "Trading")
CURSORS = frozenset(
    {"default", "grab", "grabbing", "crosshair", "move", "ew-resize", "ns-resize", "pointer"}
)
MATRIX_COLS = ("No tool", "Drawing tool armed", "Profile range mode", "Chart trading armed")
CELL_RE = re.compile(r"\*\*(\w+)\*\* · `([a-z-]+)` — \S")
MODIFIER_RE = re.compile(r"`(?:Shift|Ctrl|Alt)\b")
CAPABILITIES = (
    "Create a fixed range",
    "Adjust a range edge",
    "Anchor a profile",
    "Convert to anchored",
    "Remove an anchor",
    "Restore the previous range",
    "Attach to a drawing",
    "Detach from a drawing",
    "Apply a preset",
    "Undo an apply",
    "Save, rename or delete a preset",
)
DELETE_TOAST = "Drawing deleted — profile kept as a fixed range · Undo"  # BQ-9's default, verbatim
PAYLOAD_BAN = re.compile(
    r"\b(?:symbol|name|id|ts|time|timestamp|account|user|env\w*)\b", re.IGNORECASE
)
UNDECIDED_RE = re.compile(r"undecided|TBD|\?", re.IGNORECASE)
NO_KEYS_RE = re.compile(r"\bnone\b|mouse", re.IGNORECASE)
TOKEN_RE = re.compile(
    r"`((?:color|space|size|type|font|opacity|border|motion|elevation|radius)"
    r"\.[A-Za-z0-9.*\-]+?)(\.\.\d+)?(\[\])?`"
)
FRAME_RE = re.compile(r"`(SCR-03[89]/[a-z0-9-]+)`")


# ---------- sources -------------------------------------------------------------------------------
@functools.cache
def repo() -> L.Repo:
    return L.Repo(ROOT)


@functools.cache
def docs() -> L.Docs:
    return L.Docs(repo(), BASE, KEYED, plan=PLAN)


def line_of(key: str, n: int) -> str:
    return docs().line(key, n) or ""


@functools.cache
def d09_keys() -> dict[str, str]:
    return L.d09_keys("\n".join(docs().lines("D09E09") or ()))


# ---------- spec helpers --------------------------------------------------------------------------
def rows(block: str) -> list[list[str]]:
    return L.table_rows(block)


def sec(t: L.Tree, heading: str) -> str:
    return L.section(t.text("spec"), heading)


def copy_deck(spec: str) -> dict[str, list[str]]:
    return {r[0]: r for r in rows(L.section(spec, "## 9. Copy deck"))}


def board_rows(spec: str) -> list[list[str]]:
    return rows(L.section(spec, "## 0. Status"))


def not_drawn(spec: str) -> set[str]:
    para = next((ln for ln in spec.split("\n") if ln.startswith("**Not drawn")), "")
    return set(FRAME_RE.findall(para))


# ---------- this spec's gates ---------------------------------------------------------------------
def g_cite(t: L.Tree) -> list[str]:
    bad = L.check_cites(L.extract_cites(t.text("spec"), CITE_RE), docs(), min_count=MIN_CITES)
    return [f"unresolved cites: {', '.join(b.split(' (')[0] for b in bad)}"] if bad else []


def g_quote(t: L.Tree) -> list[str]:
    bad = []
    for r in copy_deck(t.text("spec")).values():
        if len(r) < 4 or not r[3].startswith("verbatim"):
            continue
        c = L.extract_cites(r[2], CITE_RE)
        if not c or L.unquote(r[1]) not in line_of(c[0].doc, c[0].lo):
            bad.append(r[0])
    return [f"not on the cited line: {', '.join(bad)}"] if bad else []


def g_version(t: L.Tree) -> list[str]:
    spec, v = t.text("spec"), sec(t, "### 14.3 Deviations")
    need = (BASE, D02_HEAD, D03_HEAD, D02_PR, D03_PR, "re-pinned to its merge commit", BQ_LIST)
    miss = [n for n in need if n not in v]
    if f"Base `origin/main` `{BASE}`" not in spec:
        miss.append("Inputs pinned base")
    for head, pr in ((D02_HEAD, D02_PR), (D03_HEAD, D03_PR)):
        if f"head `{head}`" not in spec or f"if {pr} merges as is" not in spec:
            miss.append(f"Start pin {pr}")
    return [f"missing: {', '.join(miss)}"] if miss else []


def g_ac(t: L.Tree) -> list[str]:
    tickets = json.loads(repo().show(BASE, BACKLOG_REL) or "[]")
    body = next(str(x.get("body", "")) for x in tickets if x.get("key") == "E19-D04")
    names = [n.strip() for n in re.findall(r"Scenario: (.+)", body)]
    spec, trace = t.text("spec"), sec(t, "## Acceptance-criteria and DoD trace")
    miss = [n for n in names if f'AC "{n}"' not in trace or spec.count(f'(AC "{n}"') != 1]
    return [f"scenario names not verbatim: {miss or names}"] if len(names) != 6 or miss else []


def g_preset_ops(t: L.Tree) -> list[str]:
    got = rows(sec(t, "### 2.2"))
    bad = [] if [r[0] for r in got] == list(PRESET_ITEMS) else ["menu items or their order"]
    bad += [f"{r[0]} T2 cell" for r in got if (r[3] == "under view-as") != (r[0] in WRITES)]
    s21, s24 = sec(t, "### 2.1"), sec(t, "### 2.4")
    if "immutable: no Save, Rename or Delete is offered on it" not in s21:
        bad.append("the built-in is not immutable")
    if "offers both `Save changes to {name}` (overwrite) and `Save as new…`" not in s24:
        bad.append("Modified does not offer overwrite and save as new")
    if "never silent" not in t.text("spec") or "never a silent replace" not in sec(t, "### 2.3"):
        bad.append("the conflict may be silent")
    if "until dismissed or until the next settings change" not in sec(t, "### 2.6"):
        bad.append("the undo lifetime is not stated")
    return bad


def matrix(t: L.Tree) -> list[list[str]]:
    return rows(sec(t, "## 5. The gesture-conflict matrix"))


def g_matrix(t: L.Tree) -> list[str]:
    block = sec(t, "## 5. The gesture-conflict matrix")
    head = next((ln for ln in block.split("\n") if ln.startswith("| #")), "")
    bad = [] if tuple(L.cells(head)[2:]) == MATRIX_COLS else ["the columns"]
    got = matrix(t)
    if len(got) < 16:
        bad.append(f"{len(got)} input rows")
    for r in got:
        for col, cell in zip(MATRIX_COLS, r[2:], strict=True):
            m = CELL_RE.match(cell)
            if not m or m.group(1) not in OWNERS or m.group(2) not in CURSORS:
                bad.append(f"row {r[0]} {col}: no single owner and cursor")
            elif UNDECIDED_RE.search(cell) or len(CELL_RE.findall(cell)) > 1:
                bad.append(f"row {r[0]} {col}: undecided")
            elif m.group(1) == "Profile" and MODIFIER_RE.search(r[1]):
                bad.append(f"row {r[0]}: a modifier is a profile gesture")
    return bad


def g_env(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    r1 = next((ln for ln in spec.split("\n") if ln.startswith("- **R-1 ")), "")
    need = ("C-2.11, a hard constraint", "carry no environment", "reads, mixes or switches")
    bad = [n for n in need if n not in r1]
    s5 = sec(t, "## 5. The gesture-conflict matrix")
    return bad + [n for n in ("identical in DEMO and LIVE", "(R-1, C-2.11)") if n not in s5]


def g_keys(t: L.Tree) -> list[str]:
    got = {r[0]: r for r in rows(sec(t, "## 6. Keyboard paths"))}
    deck = copy_deck(t.text("spec"))
    bad = [c for c in CAPABILITIES if c not in got]
    for r in got.values():
        if len(r) < 4 or "`" not in r[2] or NO_KEYS_RE.search(r[2]):
            bad.append(f"{r[0]}: no keyboard path")
        elif r[3] not in deck:
            bad.append(f"{r[0]}: announcement {r[3]} not in the copy deck")
    return bad


def g_delete(t: L.Tree) -> list[str]:
    got = rows(sec(t, "### 4.4"))
    bad = [] if len(got) == 3 else [f"{len(got)} outcome rows"]
    for r in got:
        if not r[1].startswith("converted to ") or re.search(r"removed|blocked", r[1]):
            bad.append(f"{r[0]}: not a conversion")
    if L.unquote(copy_deck(t.text("spec")).get("W-35", ["", ""])[1]) != DELETE_TOAST:
        bad.append("W-35 differs from BQ-9")
    if "never removed and never blocked" not in sec(t, "### 4.4"):
        bad.append("the outcome sentence")
    return bad


def g_payload(t: L.Tree) -> list[str]:
    got = {r[0]: r for r in rows(sec(t, "## 10. Observability"))}
    bad = [f"{k}: {r[2]}" for k, r in got.items() if len(r) < 3 or PAYLOAD_BAN.search(r[2])]
    if got.get("`profile.preset_applied`", ["", "", ""])[2] != "`{builtin, host}`":
        bad.append("the preset event payload")
    need = ("`profile.period_changed`", "`profile.mode_changed`", "`profile.settings_changed`")
    return bad + [f"{n} not annotated" for n in need if n not in got]


def g_states(t: L.Tree) -> list[str]:
    spec = t.text("spec")
    boards = {r[0]: r[2] for r in board_rows(spec) if len(r) > 2}
    undrawn, frames, bad = not_drawn(spec), set(), []
    for r in rows(sec(t, "## 8. States")):
        names = FRAME_RE.findall(r[0])
        if not names or len(r) < 7:
            bad.append(r[0])
            continue
        frames |= set(names)
        for f in names:
            ok = f in undrawn if r[6] == "not drawn" else f"`{f}`" in boards.get(r[6], "")
            if not ok:
                bad.append(f"{f} not on board {r[6]}")
    drawn = {f for b in boards.values() for f in FRAME_RE.findall(b)}
    return bad + [f"{d} has no state row" for d in sorted((drawn | undrawn) - frames)]


def g_boards(t: L.Tree) -> list[str]:
    return L.board_cap(board_rows(t.text("spec")), "E19-D04", t.text("spec"))


def g_t2(t: L.Tree) -> list[str]:
    spec, s14 = t.text("spec"), sec(t, "### 1.4")
    bad = L.t2_markers(s14) + L.t2_reason_keys(s14, d09_keys()) + L.no_disabled_tokens(spec)
    if L.unquote(copy_deck(spec).get("W-20", ["", ""])[1]) != d09_keys().get("rbac.view_as"):
        bad.append("W-20 is not `rbac.view_as`'s string")
    for r in rows(sec(t, "## 8. States")):
        gated = "view-as" in r[0] or "SCR-039/preset-menu" in r[0]
        if gated != (len(r) > 5 and r[5] == "**T2 (§1.4)**"):
            bad.append(f"{r[0]} T2 cell")
    if "**T2 (§1.4)**" not in " ".join(r[2] for r in board_rows(spec) if r[0] == "10"):
        bad.append("board 10 does not name T2")
    return bad


def g_tokens(t: L.Tree) -> list[str]:
    bad = L.check_token_refs(t.text("spec"), L.token_names(repo(), BASE), TOKEN_RE)
    return [f"unknown: {', '.join(bad)}"] if bad else []


def g_penpot(t: L.Tree) -> list[str]:
    return L.r7_findings(
        t.named("spec", "pins", "tool"), ("page `E19-D04`", "page id"), sec(t, "## 0. Status")
    )


def g_ruling(t: L.Tree) -> list[str]:
    pending = f"Default built (ruling pending, comment {BQ_LIST})."
    return L.check_ruling(
        t.text("spec"),
        heading_line=f"## The questions BQ-0 … BQ-15 — defaults built; ruling pending "
        f"(comment {BQ_LIST})",
        list_ref=f"comment {BQ_LIST} on #439",
        count=16,
        verdict=lambda _n: pending,
        need=("ORCH-default:", "Built as:"),
        forbid=("RULED:",),
    )


def g_ruled(t: L.Tree) -> list[str]:
    return L.check_hash_pins(t.text("spec"), t.text("pins"))


def g_noclose(t: L.Tree) -> list[str]:
    named = t.named("spec", "pins", "tool")
    return L.closing_keywords(named) + L.whitespace_hygiene(named)


def g_public(t: L.Tree) -> list[str]:
    named = t.named("spec", "pins", "tool")
    return L.scan_public(named) + L.comment_findings(t.named("spec"))


def g_untouched(t: L.Tree) -> list[str]:
    globs = ("docs/design/E19/img/E19-D04-*.png",)
    return L.untouched(t.changed, OWN, globs, {CAT_REL: (1, 0)}, t.numstat)


def g_mutlist(t: L.Tree) -> list[str]:
    return L.check_mutlist(t.text("spec"), "### 15.2", MUTATIONS)


# fmt: off
GATES = tuple(L.Gate("G-" + f.__name__[2:].upper().replace("_", "-"), f) for f in (
    g_cite, g_quote, g_version, g_ac, g_preset_ops, g_matrix, g_env, g_keys, g_delete,
    g_payload, g_states, g_boards, g_t2, g_tokens, g_penpot, g_ruling, g_ruled, g_noclose,
    g_public, g_untouched, g_mutlist,
))
# fmt: on

_M = L.Mutation
_V = "### 14.3 Deviations\n"
# fmt: off
MUTATIONS: tuple[L.Mutation, ...] = (
    _M("M-1", "G-CITE", "a cite past the end of `11`", "spec", "`11`:1730;", "`11`:99999;"),
    _M("M-2", "G-QUOTE", "W-24 reworded off its line", "spec",
       '"Click a bar to anchor the profile"', '"Click a bar to anchor it"'),
    _M("M-3", "G-VERSION", "the version line drops the D03 re-pin", "spec",
       "`811292427`, each re-pinned to its merge commit", "`811292427`, kept as read"),
    _M("M-4", "G-AC", "a scenario name reworded", "spec",
       '(AC "A preset name collides"', '(AC "A preset name clashes"'),
    _M("M-5", "G-PRESET-OPS", "Rename loses its T2 cell", "spec",
       r"(\| `Rename…` \(W-5\) +\|[^|]*\|[^|]*\| )under view-as", r"\1no           ",
       regex=True),
    _M("M-6", "G-PRESET-OPS", "the undo lifetime dropped", "spec",
       "until dismissed or until the next settings change", "until dismissed"),
    _M("M-7", "G-MATRIX", "a cell marked undecided", "spec",
       "**Chart** · `grab` — pans as a plain drag", "undecided"),
    _M("M-8", "G-MATRIX", "a modifier made a profile gesture", "spec",
       "**Trading** · `default` — never a profile gesture", "**Profile** · `crosshair` — range"),
    _M("M-9", "G-MATRIX", "an unknown cursor", "spec",
       "**Profile** · `ew-resize` — moves that edge", "**Profile** · `col-resize` — moves it"),
    _M("M-10", "G-ENV", "the matrix differs by environment", "spec",
       "**identical in DEMO and LIVE**", "**the same in DEMO**"),
    _M("M-11", "G-KEYS", "a capability without a keyboard path", "spec",
       "| Remove an anchor ", "| Remove the anchor "),
    _M("M-12", "G-DELETE", "a delete removes the profile", "spec",
       "| converted to a Fixed range at the drawing's last two times",
       "| removed with the drawing; nothing kept"),
    _M("M-13", "G-DELETE", "the delete toast reworded", "spec",
       r'(\| W-35 \| )"Drawing deleted — profile kept as a fixed range · Undo"',
       r'\1"Drawing deleted · Undo"', regex=True),
    _M("M-14", "G-PAYLOAD", "a symbol in the preset event", "spec",
       r"(`profile\.preset_applied` +\|[^|\n]*\| )`\{builtin, host\}`",
       r"\1`{builtin, host, symbol}`", regex=True),
    _M("M-15", "G-STATES", "a drawn frame loses its state row", "spec",
       "| `SCR-038/attached-dark`  ", "| `SCR-038/attach-done-dark`"),
    _M("M-16", "G-BOARDS", "a fourth light twin", "spec",
       r"(`E19-D04 / 02 preset-save`[^\n]*\| )dark( +\| PENDING)", r"\1light twin\2",
       regex=True),
    _M("M-17", "G-T2", "the T2 statement loses the opacity ban", "spec",
       "never `color.text.disabled`, never `opacity.disabled` on the label",
       "never `color.text.disabled` on the label"),
    _M("M-18", "G-T2", "the view-as frame loses T2", "spec",
       r"(`SCR-038/preset-view-as-dark` +\|[^\n]*?\| )\*\*T2 \(§1\.4\)\*\*", r"\1—",
       regex=True),
    _M("M-19", "G-TOKENS", "an unshipped motion token", "spec",
       "a cut, `motion.duration.instant`", "a cut, `motion.duration.none`"),
    _M("M-20", "G-PENPOT", "a Penpot file id", "spec",
       "page `E19-D04`, cited", "page `E19-D04` (" + "file" + "-id=0), cited"),
    _M("M-21", "G-RULING", "the heading claims a ruling", "spec",
       "BQ-15 — defaults built; ruling pending (comment", "BQ-15 — RULED (comment"),
    _M("M-22", "G-RULED", "a BQ default edited without a re-pin", "spec",
       "ORCH-default: 10 boards on D03's", "ORCH-default: 9 boards on D03's"),
    _M("M-23", "G-NOCLOSE", "a closing keyword", "spec", _V, _V + "\n" + "Clo" + "ses #439.\n"),
    _M("M-24", "G-NOCLOSE", "a forbidden heading", "spec", "## 13. Heuristic evaluation",
       "## " + "What" + " this spec " + "fix" + "es\n\n## 13. Heuristic evaluation"),
    _M("M-25", "G-PUBLIC", "a URL", "spec", "Penpot file `E19-D04 boards`",
       "Penpot file (" + "http" + "s://example.org) `E19-D04 boards`"),
    _M("M-26", "G-PUBLIC", "an HTML comment", "spec", "## 11. Tokens", "<!-- x -->\n## 11. Tokens"),
    _M("M-27", "G-UNTOUCHED", "an owner document edited", "@changed",
       "", "docs/plan/05-accessibility-standard.md"),
    _M("M-28", "G-UNTOUCHED", "a second catalogue line", f"@numstat:{CAT_REL}", "", "2 0"),
    _M("M-29", "G-MUTLIST", "the list drifts", "spec", "| M-1  | G-CITE ", "| M-1  | G-AC   "),
)
# fmt: on


# ---------- modes ---------------------------------------------------------------------------------
def read_tree() -> L.Tree:
    pins = ROOT / PIN_REL
    base = repo().diff_base(BASE)
    return L.Tree(
        files={
            "spec": (ROOT / SPEC_REL).read_text(encoding="utf-8"),
            "pins": pins.read_text(encoding="utf-8") if pins.exists() else "",
            "tool": (ROOT / TOOL_REL).read_text(encoding="utf-8"),
        },
        changed=repo().changed_paths(base),
        numstat={CAT_REL: repo().numstat(base, CAT_REL)},
    )


def check() -> int:
    return L.report(L.run_gates(GATES, read_tree()))


def self_test() -> int:
    disk = [ROOT / rel for rel in OWN]
    return L.self_test(read_tree(), GATES, MUTATIONS, disk, namespace=globals())


def repin() -> int:
    lines = L.bq_hash_pins((ROOT / SPEC_REL).read_text(encoding="utf-8"))
    head = "# E19-D04 ruled pins: sha256[:16] of each BQ bullet; written by --repin-ruled only"
    L.write_pins(ROOT / PIN_REL, "\n".join([head, *lines]))
    print(f"pinned {len(lines)} BQ lines")
    return 0


def main(argv: list[str]) -> int:
    modes = {"check": check, "self-test": self_test, "repin-ruled": repin}
    return L.cli(argv, modes, __doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
