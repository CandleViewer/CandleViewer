"""E37-X01 (#1073): the node-graph editor's STRIDE threat model holds the ticket's scenarios.

`docs/security/threat-models/e37-rule-graph-editor.md` is read as a document: the six STRIDE tables
of its section 3, the coverage matrix (3.7), the gap table (7), the findings register (11.1) and the
two verifications (4 and 5), with the abuse-case seeds of `docs/security/abuse-cases/
e37-rule-graph.md`. A table is read by its header names. Scenarios 2 and 4 are proven by their own
tests (`test_presentation_block_is_inert.py`, `arming-boundary.test.ts`); here their record is
read, and every Python test the model or a seed names must exist but the `test_x02_*` ones, which
E37-X02 builds (their seeds are WAITING).
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parents[5]
_MODEL: Final = _ROOT / "docs/security/threat-models/e37-rule-graph-editor.md"
_SEEDS: Final = _ROOT / "docs/security/abuse-cases/e37-rule-graph.md"
_API_TESTS: Final = _ROOT / "services/api/tests"

#: The rating matrix the model's 1.4 takes from `E29-oms.md` 1.3: (likelihood, impact) -> risk.
_RISK: Final = {
    ("H", "H"): "Critical",
    ("M", "H"): "High",
    ("H", "M"): "High",
    ("M", "M"): "Medium",
    ("L", "H"): "Medium",
    ("H", "L"): "Medium",
    ("L", "M"): "Low",
    ("M", "L"): "Low",
    ("L", "L"): "Low",
}
_LEVELS: Final = ("Low", "Medium", "High", "Critical")
#: Section 3's tables, one per STRIDE category, by their heading number.
_CATEGORIES: Final = {"3.1": "S", "3.2": "T", "3.3": "R", "3.4": "I", "3.5": "D", "3.6": "E"}
_GAP: Final = "Gap → mitigation"
_OWNER: Final = "Owner (sprint)"
_KEY: Final = re.compile(r"\bE\d{2}-[A-Z]\d{2}\b")
_TICKET: Final = re.compile(rf"{_KEY.pattern}|#\d+")
_R3_SPRINT: Final = re.compile(r"\bS1[4-9]\b")  # R3 runs S14 to S19 (`30-release-roadmap.md`)
_THREAT: Final = re.compile(r"\bRG-[STRIDE]\d{2}\b")
_SEED: Final = re.compile(r"\bAC-RG-\d{2}\b")
_NAMED_TEST: Final = re.compile(r"\btest_[a-z0-9_]+\b(?!\.)")
_BLANK: Final = frozenset({"", "-", "—"})


def _text(path: Path = _MODEL) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body under the heading that starts with `heading`, to the next heading of its level."""
    level = len(heading.split(" ", 1)[0])
    start = re.search(rf"^{re.escape(heading)} .*$", text, re.M)
    assert start is not None, f"no heading {heading!r}"
    stop = re.compile(rf"^#{{2,{level}}} ", re.M).search(text, start.end())
    return text[start.end() : stop.start() if stop else len(text)]


def _rows(table: str, first: str) -> dict[str, dict[str, str]]:
    """The rows of the tables in `table` whose first cell matches `first`, each a map from its
    table's header names to its cells. A pipe a backslash escapes is text, not a border."""
    out: dict[str, dict[str, str]] = {}
    header: list[str] = []
    for line in table.splitlines():
        if not line.startswith("|"):
            header = []
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if not header:
            header = cells
        elif re.fullmatch(first, cells[0]):
            assert cells[0] not in out, f"{cells[0]} twice"
            assert len(cells) == len(header), f"{cells[0]}: {len(cells)} cells, {len(header)} heads"
            out[cells[0]] = dict(zip(header, cells, strict=True))
    return out


def _threats() -> dict[str, dict[str, dict[str, str]]]:
    """Section 3's rows by category letter, each by its column names."""
    text = _text()
    return {
        letter: _rows(_section(text, f"### {number}"), _THREAT.pattern)
        for number, letter in _CATEGORIES.items()
    }


def _all_threats() -> dict[str, dict[str, str]]:
    return {rid: row for rows in _threats().values() for rid, row in rows.items()}


@cache
def _raci() -> frozenset[str]:
    """The role codes of `33-raci.md` section 2."""
    roles = _section(_text(_ROOT / "docs/plan/33-raci.md"), "## 2.")
    return frozenset(re.findall(r"^\| \*\*([A-Z0-9]+)\*\* \|", roles, re.M))


@cache
def _defined_tests() -> frozenset[str]:
    """Every test function defined under `services/api/tests`."""
    found = re.compile(r"^(?:async )?def (test_\w+)\(", re.M)
    return frozenset(
        name
        for path in _API_TESTS.rglob("test_*.py")
        for name in found.findall(path.read_text(encoding="utf-8"))
    )


def test_threat_model_every_stride_category_has_a_rated_row_with_a_control_or_a_gap() -> None:
    """Scenario: Every STRIDE category is addressed
    When the model is reviewed
    Then each of the six categories has at least one enumerated, rated threat with named controls
    or a recorded gap, and no category is dismissed without a written reason
    """
    threats = _threats()
    assert sum(map(len, threats.values())) >= 28  # the tables held 28 rows when this was written
    for letter, rows in threats.items():
        assert rows, f"no {letter} threat"
        for rid, row in rows.items():
            assert rid[3] == letter, rid
            blank = [
                h for h in ("Element / boundary", "Threat", "Verify", "Res.") if row[h] in _BLANK
            ]
            assert not blank, f"{rid}: {blank} left blank"
            assert row["Existing control"] not in _BLANK or row[_GAP] not in _BLANK, (
                f"{rid}: no control, no gap"
            )
            assert set(re.split(r",\s*", row["Disp."])) <= {"Q", "C", "R"}, f"{rid}: disposition"


def test_threat_model_risk_follows_the_rating_matrix() -> None:
    """Scenario: Every STRIDE category is addressed
    When the model is reviewed
    Then each of the six categories has at least one enumerated, rated threat with named controls
    or a recorded gap, and no category is dismissed without a written reason

    (Rated: each risk is the model's L x I matrix, never a free choice.)
    """
    for rid, row in _all_threats().items():
        likelihood, impact, risk = row["L"], row["I"], row["Risk"]
        assert (likelihood, impact) in _RISK, f"{rid}: L and I are L, M or H"
        assert risk == _RISK[likelihood, impact], f"{rid}: {likelihood} x {impact} is not {risk}"


def test_threat_model_no_category_or_cell_is_dismissed_without_a_reason() -> None:
    """Scenario: Every STRIDE category is addressed
    When the model is reviewed
    Then each of the six categories has at least one enumerated, rated threat with named controls
    or a recorded gap, and no category is dismissed without a written reason
    """
    text, threats = _text(), _threats()
    matrix = _rows(_section(text, "### 3.7"), r"(?:E|P|DS|TB-G)\d+ .+")
    dfd = _section(text, "## 2.")
    elements = set(re.findall(r"\*\*(TB-G\d+)\b", dfd))
    for kind, first, last in re.findall(r"\*\*(E|P|DS)(\d+) to \1(\d+)\*\*", dfd):
        elements |= {f"{kind}{n}" for n in range(int(first), int(last) + 1)}
    assert len(elements) >= 23  # the DFD held 23 elements and boundaries when this was written
    missing = elements - {name.split(" ", 1)[0] for name in matrix}
    assert not missing, f"section 2's elements with no matrix row: {sorted(missing)}"
    for element, row in matrix.items():
        cells = [row[letter] for letter in "STRIDE"]
        assert not _BLANK.intersection(cells), f"{element}: a category left empty"
        unknown = sorted(
            {rid for rid in _THREAT.findall(" ".join(cells)) if rid not in threats[rid[3]]}
        )
        assert not unknown, f"{element}: no such row in its category's table: {unknown}"
    bare = [m.start() for m in re.finditer(r"\bn/a\b(?!: \S+ \S+)", text)]
    assert bare == [], "an n/a with no written reason"


def test_threat_model_every_gap_names_a_ticket_an_owner_and_a_due_sprint() -> None:
    """Scenario: Gaps become tickets
    Given any control gap
    Then it is filed against a specific ticket with an owner and a due sprint, not left as prose in
    the model
    """
    gaps, raci = _rows(_section(_text(), "## 7."), r"G-\d+"), _raci()
    assert len(gaps) >= 5 and len(raci) >= 13
    for gid, gap in gaps.items():
        assert gap["Requirement or work"] not in _BLANK, gid
        assert _TICKET.search(gap["Ticket"]), f"{gid}: no ticket"
        owners = set(re.findall(r"[A-Z0-9]+", gap["Owner"]))
        assert owners and owners <= raci, f"{gid}: {sorted(owners - raci)} is no 33-raci.md role"
        assert _R3_SPRINT.search(gap["Sprint"]), f"{gid}: no R3 sprint"
    for rid, row in _all_threats().items():
        owner = row[_OWNER]
        assert set(re.findall(r"\bG-\d+\b", row[_GAP])) <= set(gaps), f"{rid}: a gap not filed"
        if "Q" in row["Disp."]:  # a fix is owed: its ticket, owner and sprint are named
            assert _TICKET.search(owner) and _R3_SPRINT.search(owner), rid
            assert raci.intersection(re.findall(r"[A-Z0-9]+", owner)), rid
        if row["Risk"] in ("High", "Critical") and "C" not in row["Disp."]:
            # Nothing on `main` holds it: the work it waits on has an R3 sprint or an RR.
            assert _R3_SPRINT.search(owner) or re.search(r"\bRR-\d+\b", owner), f"{rid}: no sprint"


def test_threat_model_every_ticket_it_names_is_in_the_backlog() -> None:
    """Scenario: Gaps become tickets
    Given any control gap
    Then it is filed against a specific ticket with an owner and a due sprint, not left as prose in
    the model
    """
    backlog = json.loads((_ROOT / "docs/plan/backlog/all-tickets.json").read_text(encoding="utf-8"))
    keys = {ticket["key"] for ticket in backlog}
    for path in (_MODEL, _SEEDS):
        unknown = sorted(set(_KEY.findall(_text(path))) - keys)
        assert not unknown, f"{path.name}: {unknown} not in all-tickets.json"


def test_threat_model_every_seed_it_names_has_a_row_in_the_seed_file() -> None:
    """Scenario: Gaps become tickets
    Given any control gap
    Then it is filed against a specific ticket with an owner and a due sprint, not left as prose in
    the model

    (A claim waiting on its control has a seed for E37-X02 that names the ticket building it.)
    """
    seeds = _rows(_text(_SEEDS), _SEED.pattern)
    named = set(_SEED.findall(_text()))
    assert named and named <= set(seeds), f"no seed row: {sorted(named - set(seeds))}"
    threats = _all_threats()
    for sid, seed in seeds.items():
        rows = set(_THREAT.findall(seed["Rows"]))
        assert rows and rows <= set(threats), f"{sid}: {sorted(rows - set(threats))}"
        assert not _BLANK.intersection(
            [seed["Action"], seed["Expected"], seed["Test that proves it"]]
        ), sid
        assert re.search(r"\b(?:COVERED|NEW|WAITING)\b", seed["Verdict"]), sid
        if "WAITING" in seed["Verdict"]:
            assert _TICKET.search(seed["Verdict"]) or re.search(r"\bG-\d+\b", seed["Verdict"]), sid


def test_threat_model_rows_and_seeds_name_each_other() -> None:
    """Scenario: Gaps become tickets
    Given any control gap
    Then it is filed against a specific ticket with an owner and a due sprint, not left as prose in
    the model

    (A seed's Rows and the Verify cells of those rows agree, both ways.)
    """
    threats = _all_threats()
    for sid, seed in _rows(_text(_SEEDS), _SEED.pattern).items():
        rows = set(_THREAT.findall(seed["Rows"]))
        verify = {rid for rid, row in threats.items() if sid in _SEED.findall(row["Verify"])}
        assert rows == verify, f"{sid}: its Rows {sorted(rows)}, the Verify cells {sorted(verify)}"


def test_threat_model_every_high_or_critical_finding_has_an_r3_fix_or_an_accepted_risk_record() -> (
    None
):
    """Scenario: A Critical/High finding is open at train close (failure)
    Then the epic cannot be Done; the finding is either fixed or carries an Owner-signed
    accepted-risk record per the R3 security gate
    """
    findings = _rows(_section(_text(), "### 11.1"), r"F-\d{2}")
    rows = _all_threats()
    for fid, finding in findings.items():
        named = set(_THREAT.findall(finding["Rows"]))
        assert named and named <= set(rows), fid
        highest = max((rows[rid]["Risk"] for rid in named), key=_LEVELS.index)
        rated = finding["Severity (unmitigated)"]
        assert rated == highest, f"{fid}: rated {rated}, its highest row {highest}"
        owning = finding["Owning ticket (sprint)"]
        if highest in ("High", "Critical"):
            assert _TICKET.search(owning), f"{fid}: no owning ticket"
            assert _R3_SPRINT.search(owning) or re.search(r"\bRR-\d+\b", owning), fid
    registered = {rid for finding in findings.values() for rid in _THREAT.findall(finding["Rows"])}
    for rid, row in rows.items():
        if row["Risk"] in ("High", "Critical") and "Q" in row["Disp."]:
            assert rid in registered, f"{rid}: a High row whose fix is owed has no finding"


def test_threat_model_records_the_presentation_and_arming_verifications() -> None:
    """Scenario: Presentation cannot carry semantics
    Given the graph_layout / comment / collapsed-state block
    When it is analysed against the evaluator's inputs
    Then it is demonstrated that no field in it reaches evaluation, or the finding is raised as a
    blocking gap against E35/E37-T01

    Scenario: Arming cannot be reached from the editor (security edge)
    Then it is verified by inspection and by test that no editor interaction, hotkey or API call
    path sets rule mode without the SCR-085 step-up flow
    """
    text = _text()
    block, arming = _section(text, "## 4."), _section(text, "## 5.")
    assert "test_presentation_block_is_inert.py" in block and "**Verdict.**" in block
    assert "arming-boundary.test.ts" in arming and "eslint.config.mjs" in arming
    assert "**By inspection.**" in arming and "**Verdict.**" in arming
    assert _NAMED_TEST.search(block) and _NAMED_TEST.search(arming)
    cited = _section(text, "## 3.") + block + arming + _text(_SEEDS)
    named = set(_NAMED_TEST.findall(cited)) - {
        "test_evaluator_ignores_layout_fields"
    }  # E35's (G-3)
    unknown = sorted(n for n in named - _defined_tests() if not n.startswith("test_x02_"))
    assert not unknown, f"named tests that do not exist: {unknown}"
