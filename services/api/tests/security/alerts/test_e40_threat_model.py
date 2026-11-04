"""E40-X01 (#1204) Part A: the alert and notification threat model holds the ticket's scenarios.

`docs/security/threat-models/e40-alerts.md` is read as a document: the flows of its section 2, the
six STRIDE tables of section 3 and the coverage matrix (3.7), the notify-only layers (4), the limits
(7), the control-to-ticket map (11) and the findings register (12.1), with the abuse-case seeds of
`docs/security/abuse-cases/e40-alerts.md`. Every test file a COVERED seed or the elevation row cites
must exist and define the test it names, so a claim the model makes stays a claim a test proves.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parents[5]
_MODEL: Final = _ROOT / "docs/security/threat-models/e40-alerts.md"
_SEEDS: Final = _ROOT / "docs/security/abuse-cases/e40-alerts.md"
_API: Final = _ROOT / "services/api"
_BACKLOG: Final = _ROOT / "docs/plan/backlog/all-tickets.json"

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
_RANK: Final = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
#: Section 3's tables, one per STRIDE category, by their heading number.
_CATEGORIES: Final = {"3.1": "S", "3.2": "T", "3.3": "R", "3.4": "I", "3.5": "D", "3.6": "E"}
#: Every element and boundary of section 2, each a row of the coverage matrix.
_ELEMENTS: Final = frozenset(
    [f"E{n}" for n in range(1, 9)]
    + [f"P{n}" for n in range(1, 15)]
    + [f"DS{n}" for n in range(1, 9)]
    + [f"TB-AL{n}" for n in range(1, 10)]
)
_THREAT: Final = re.compile(r"\bAL-[STRIDE]\d{2}\b")
_SEED: Final = re.compile(r"\bAC-AL-\d{2}\b")
_OWNER: Final = re.compile(r"\bE\d{2}(?:-[A-Z]\d{2})?\b|#\d+|\bG-\d+\b")  # an epic, a key, an issue
_KEY: Final = re.compile(r"\bE\d{2}-[A-Z]\d{2}\b|#\d+")
_R3_SPRINT: Final = re.compile(r"\bS1[4-9]\b")  # R3 runs S14 to S19 (`30-release-roadmap.md`)
_TICKED: Final = re.compile(r"`([^`]+)`")
_BLANK: Final = frozenset({"", "-", "—"})


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body under the heading that starts with `heading`, to the next heading of its level."""
    level = len(heading.split(" ", 1)[0])
    start = re.search(rf"^{re.escape(heading)} .*$", text, re.M)
    assert start is not None, f"no heading {heading!r}"
    stop = re.compile(rf"^#{{2,{level}}} ", re.M).search(text, start.end())
    return text[start.end() : stop.start() if stop else len(text)]


def _rows(table: str, first: str) -> dict[str, list[str]]:
    """The rows of the tables in `table` whose first cell matches `first`: the other cells."""
    out: dict[str, list[str]] = {}
    for line in table.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and re.fullmatch(first, cells[0]):
            assert cells[0] not in out, f"{cells[0]} twice"
            out[cells[0]] = cells[1:]
    return out


def _threats() -> dict[str, dict[str, list[str]]]:
    """Section 3's rows by category letter: element, threat, L, I, risk, control, gap, owner,
    verify, disposition, residual."""
    text = _text(_MODEL)
    return {
        letter: _rows(_section(text, f"### {number}"), _THREAT.pattern)
        for number, letter in _CATEGORIES.items()
    }


def _all_threats() -> dict[str, list[str]]:
    return {rid: cells for rows in _threats().values() for rid, cells in rows.items()}


def _seeds() -> dict[str, list[str]]:
    """The seed rows: rows, action, expected, the test that proves it, verdict."""
    return _rows(_text(_SEEDS), _SEED.pattern)


@cache
def _defined(path: Path) -> frozenset[str]:
    """The test functions `path` defines."""
    return frozenset(re.findall(r"^\s*(?:async )?def (test_\w+)\(", _text(path), re.M))


def _missing_citations(cell: str) -> list[str]:
    """The backticked `tests/...` paths and `::test_name`s in `cell` that do not resolve under
    `services/api` (a bare `::name` belongs to the file named before it)."""
    missing: list[str] = []
    current: Path | None = None
    for item in _TICKED.findall(cell):
        path, _, name = item.partition("::")
        if path:
            if not path.startswith("tests/"):
                continue
            current = _API / path
            if not current.exists():
                missing.append(item)
                continue
        if name and (current is None or current.suffix != ".py" or name not in _defined(current)):
            missing.append(item)
    return missing


def test_threat_model_every_stride_category_has_rated_rows_with_a_control_or_a_gap() -> None:
    """Scenario: Every element and flow is analysed
    When the model is reviewed against the data-flow diagram
    Then each element and each flow has a STRIDE row, or an explicit "not applicable" with a reason
    """
    threats = _threats()
    assert sum(map(len, threats.values())) >= 39  # the tables held 39 rows when this was written
    for letter, rows in threats.items():
        assert rows, f"no {letter} threat"
        for rid, cells in rows.items():
            assert rid[3] == letter and len(cells) == 11, rid
            element, threat, _l, _i, _risk, control, gap, owner, verify, disp, res = cells
            named = set(re.split(r",\s*", element))
            assert named and named <= _ELEMENTS, f"{rid}: element {element!r}"
            assert threat not in _BLANK, f"{rid}: no threat"
            assert control not in _BLANK or gap not in _BLANK, f"{rid}: no control, no gap"
            assert _OWNER.search(owner), f"{rid}: no control owner"
            assert _SEED.search(verify) or (
                verify.startswith("NOT RUN:") and _OWNER.search(verify)
            ), f"{rid}: Verify names no seed and no owner it waits for"
            assert set(re.split(r",\s*", disp)) <= {"Q", "C", "R"}, f"{rid}: disposition"
            assert res.split(" ", 1)[0] in _RANK, f"{rid}: residual"


def test_threat_model_risk_follows_the_rating_matrix() -> None:
    """Scenario: Every element and flow is analysed
    When the model is reviewed against the data-flow diagram
    Then each element and each flow has a STRIDE row, or an explicit "not applicable" with a reason

    (Rated: each risk is the model's L x I matrix, never a free choice.)
    """
    for rid, cells in _all_threats().items():
        likelihood, impact, risk = cells[2], cells[3], cells[4]
        assert (likelihood, impact) in _RISK, f"{rid}: L and I are L, M or H"
        assert risk.split(" ", 1)[0] == _RISK[likelihood, impact], (
            f"{rid}: {likelihood} x {impact} is not {risk}"
        )


def test_threat_model_coverage_matrix_names_a_row_or_a_reason_in_every_cell() -> None:
    """Scenario: Every element and flow is analysed
    When the model is reviewed against the data-flow diagram
    Then each element and each flow has a STRIDE row, or an explicit "not applicable" with a reason
    """
    text = _text(_MODEL)
    threats = set(_all_threats())
    matrix = _rows(_section(text, "### 3.7"), r"(?:E|P|DS|TB-AL)\d+ .+")
    assert {element.split(" ", 1)[0] for element in matrix} == _ELEMENTS
    for element, cells in matrix.items():
        assert len(cells) == 6, element
        for letter, cell in zip("STRIDE", cells, strict=True):
            named = set(_THREAT.findall(cell))
            assert re.match(r"n/a: \S+ \S+", cell) or (named and named <= threats), (
                f"{element} / {letter}: neither a known row nor a reasoned n/a: {cell!r}"
            )
    assert re.findall(r"\bn/a\b(?!: \S+ \S+)", text) == [], "an n/a with no written reason"
    flows_section = _section(text, "## 2.")
    for element in _ELEMENTS:  # every matrix row is an element or boundary section 2 defines
        assert re.search(rf"\*\*{element}\b", flows_section), f"{element} is not in section 2"
    flows = _rows(flows_section, r"F\d+")
    diagram = flows_section.split("```", 2)[1]
    assert flows and set(re.findall(r"\|(F\d+)\|", diagram)) == set(flows)
    for flow, (_route, what, boundary) in flows.items():
        assert what not in _BLANK, flow
        crossed = set(re.findall(r"\bTB-AL\d\b", boundary))
        assert crossed and crossed <= _ELEMENTS, f"{flow}: analysed on no boundary of 3.7"


def test_threat_model_elevation_row_is_rated_and_traced_to_tested_e40_t02_controls() -> None:
    """Scenario: The elevation path is treated as the primary threat
    Then the "an alert can act" threat is rated and traced to a named, testable control in
    E40-T02, not merely to a design intention
    """
    row = _all_threats()["AL-E01"]
    _element, _threat, likelihood, impact, risk, control, _gap, owner, verify, _disp, _res = row
    assert (likelihood, impact, risk) == ("M", "H", "High")
    assert "E40-T02" in control and "E40-T02" in owner
    cited = re.findall(r"`(tests/[\w/.-]+\.py)[:`]", control)
    assert len(cited) >= 3 and all((_API / p).is_file() for p in cited), cited
    assert {"AC-AL-01", "AC-AL-02", "AC-AL-03"} <= set(_SEED.findall(verify))
    invariant = _section(_text(_MODEL), "## 4.")
    layers = _rows(invariant, r"L\d")
    assert sorted(layers) == [f"L{n}" for n in range(1, 9)]
    for layer, (_holds, where, proof) in layers.items():
        assert where not in _BLANK and proof not in _BLANK, layer
    for layer in ("L2", "L3", "L4", "L5"):  # E40-T02's own controls, each with a test that exists
        tests = re.findall(r"`(tests/[\w/.-]+\.py)[:`]", layers[layer][2])
        assert tests and all((_API / t).is_file() for t in tests), layer
    assert "**Verdict.**" in invariant and "AL-E01" in invariant.split("**Verdict.**", 1)[1]


def test_abuse_seeds_name_rows_an_action_an_expectation_a_test_and_a_verdict() -> None:
    """Scenario: Abuse cases are executable (edge)
    Then each abuse case is written concretely enough that E40-X01 can automate it without
    further interpretation
    """
    seeds = _seeds()
    threats = set(_all_threats())
    assert sorted(seeds) == [f"AC-AL-{n:02d}" for n in range(1, len(seeds) + 1)]
    assert len(seeds) >= 26  # AC-AL-01 to AC-AL-26 when this was written
    for sid, cells in seeds.items():
        assert len(cells) == 5, sid
        rows, action, expected, proof, verdict = cells
        named = set(_THREAT.findall(rows))
        assert named and named <= threats, f"{sid}: rows {rows!r}"
        assert not _BLANK.intersection([action, expected, proof]), f"{sid}: an empty cell"
        assert re.search(r"\b(?:COVERED|NEW|WAITING)\b", verdict), f"{sid}: verdict"
        if "WAITING" in verdict:
            assert _KEY.search(verdict), f"{sid}: WAITING names no ticket"


def test_every_seed_the_model_names_has_its_row_and_each_covered_test_exists() -> None:
    """Scenario: Abuse cases are executable (edge)
    Then each abuse case is written concretely enough that E40-X01 can automate it without
    further interpretation

    (A seed the model names has its row, every seed row answers to the model, and a COVERED
    seed cites tests that exist on `main`.)
    """
    seeds = _seeds()
    assert set(_SEED.findall(_text(_MODEL))) == set(seeds), "model and seeds disagree"
    for sid, (_rows_cell, _action, _expected, proof, verdict) in seeds.items():
        if "COVERED" not in verdict:
            continue
        assert "COVERED:" in proof, f"{sid}: COVERED with no cited test"
        covered = re.split(r"\b(?:NEW|WAITING):", proof.split("COVERED:", 1)[1], maxsplit=1)[0]
        assert re.search(r"`tests/", covered), f"{sid}: COVERED cites no test file"
        assert _missing_citations(covered) == [], f"{sid}: {_missing_citations(covered)}"


def test_threat_model_high_and_critical_findings_have_an_r3_owner_or_an_accepted_risk_record() -> (
    None
):
    """Scenario: An unmitigated High is escalated (failure)
    Given a High finding with no control landing in R3
    Then it is recorded as accepted risk with Owner sign-off, or the epic scope changes; it is
    not left silently open
    """
    text = _text(_MODEL)
    threats = _all_threats()
    findings = _rows(_section(text, "### 12.1"), r"F-\d{2}")
    assert len(findings) >= 19  # F-01 to F-19 when this was written
    for fid, (rows, severity, owning, note) in findings.items():
        named = _THREAT.findall(rows)
        assert named and set(named) <= set(threats), f"{fid}: rows {rows!r}"
        worst = max((threats[r][4].split(" ", 1)[0] for r in named), key=_RANK.__getitem__)
        assert severity == worst, f"{fid}: {severity} is not its rows' {worst}"
        if severity in ("High", "Critical"):
            assert _KEY.search(owning), f"{fid}: no owning ticket"
            r5_residual = "R5" in owning and "Low in R3" in note
            assert _R3_SPRINT.search(owning) or r5_residual or re.search(r"\bRR-\d+\b", owning), (
                f"{fid}: no R3 sprint, no R5 residual and no accepted-risk record"
            )
    registered = {rid for cells in findings.values() for rid in _THREAT.findall(cells[0])}
    for rid, cells in threats.items():
        if cells[4].split(" ", 1)[0] in ("High", "Critical"):
            assert rid in registered, f"{rid}: a High or Critical row with no finding"


def test_threat_model_limits_table_states_a_number_and_a_source_per_row() -> None:
    """The ticket's Performance notes: "Denial-of-service findings must state numeric limits
    (alerts per user, evaluation queue depth, ack-all batch size) so the implementing tickets have
    a target rather than an adjective." (Part A DoD: Numeric DoS limits stated.)
    """
    lines = [line for line in _section(_text(_MODEL), "## 7.").splitlines() if line.startswith("|")]
    limits = {
        cells[0]: cells[1:]
        for cells in ([c.strip() for c in line.strip("|").split("|")] for line in lines[2:])
    }
    assert len(limits) >= 20 and lines[0].split("|")[1].strip() == "Limit"
    for limit, cells in limits.items():
        assert len(cells) == 3, limit
        value, status, source = cells
        assert re.search(r"\d", value), f"{limit}: no number"
        assert status not in _BLANK and source not in _BLANK, f"{limit}: no status or source"
    for named in ("Armed alerts per user", "Evaluation queue", "`ack-all`"):
        assert named in limits, f"the ticket's {named} limit is missing"


def test_threat_model_ticket_map_is_the_first_ticket_heading_and_names_every_e40_key() -> None:
    """Part A DoD: "Every Critical/High has an owner, a target ticket and a testable control."
    The control-to-ticket map is the section GOV-008 reads (the first heading holding "ticket"),
    and it names every E40 ticket that is not retired.
    """
    text = _text(_MODEL)
    headings = re.findall(r"^#{2,3} .*$", text, re.M)
    first = next(h for h in headings if "ticket" in h.lower())
    assert first == "## 11. Control-to-ticket map", first
    tickets = json.loads(_BACKLOG.read_text(encoding="utf-8"))
    keys = {
        t["key"]
        for t in tickets
        if re.fullmatch(r"E40-[A-Z]\d{2}", t["key"]) and "retired" not in (t.get("labels") or [])
    }
    mapped = set(_rows(_section(text, "## 11."), r"E40-[A-Z]\d{2}"))
    assert len(keys) >= 15 and keys <= mapped, sorted(keys - mapped)


def test_threat_model_every_cited_source_file_exists() -> None:
    """Scenario: The elevation path is treated as the primary threat
    Then the "an alert can act" threat is rated and traced to a named, testable control in
    E40-T02, not merely to a design intention

    (Every `cv/`, `tests/` and `services/api/` path the model cites resolves, the SSRF corpus
    included, so no row rests on a file that moved.)
    """
    cited = re.findall(r"`((?:cv|tests|services/api)/[^`:\s]+)", _text(_MODEL))
    base = {"cv": _API / "candleviewer", "tests": _API / "tests", "services": _ROOT / "services"}
    missing = [
        path for path in cited if not (base[path.split("/", 1)[0]] / path.split("/", 1)[1]).exists()
    ]
    assert len(cited) >= 100 and missing == [], missing
    assert "services/api/tests/security/alerts/ssrf_corpus.json" in cited
