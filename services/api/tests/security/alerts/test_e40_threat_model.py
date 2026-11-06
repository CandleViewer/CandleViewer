"""E40-X01 (#1204) Part A: the alert and notification threat model holds the ticket's scenarios.

`docs/security/threat-models/e40-alerts.md` is read as a document, each section found by its title:
the data-flow section, the six STRIDE tables and the coverage matrix, the notify-only layers, the
limits, the gaps, the requirements, the control-to-ticket map and the findings, with the abuse-case
seeds of `docs/security/abuse-cases/e40-alerts.md` and RSK-093 in `docs/plan/32-risk-register.md`.
Every id the documents name resolves: a ticket key is one the backlog lists live (`_KEYS`), and a
requirement, a gap
and an accepted-risk record are defined; every test a COVERED seed or a layer cites exists and
defines the test it names, so a claim the model makes stays a claim a test proves.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parents[5]
_MODEL: Final = _ROOT / "docs/security/threat-models/e40-alerts.md"
_SEEDS: Final = _ROOT / "docs/security/abuse-cases/e40-alerts.md"
_REGISTER: Final = _ROOT / "docs/plan/32-risk-register.md"
_PROGRAMME: Final = _ROOT / "docs/plan/04-security-program.md"
_RACI: Final = _ROOT / "docs/plan/33-raci.md"
_API: Final = _ROOT / "services/api"

#: The backlog keys the model and its seeds name, epics and tickets, and every E40 ticket: the keys
#: `docs/plan/backlog/all-tickets.json` lists with no `retired` label, as of 2026-11-05. The export
#: is not read here (the `py` lane's path filter does not watch it): a key the documents start to
#: name, or an E40 ticket the backlog adds, is added to this set from the backlog.
_KEYS: Final = frozenset(
    {
        "E01", "E02", "E03", "E04", "E05", "E06", "E07", "E09", "E12", "E14",
        "E17", "E27", "E29", "E35", "E36", "E39", "E40", "E42", "E43", "E44",
        "E27-X02", "E35-T13", "E42-D02",
        "E40-D01", "E40-D02", "E40-D03", "E40-K01", "E40-Q01", "E40-Q02", "E40-S01",
        "E40-S02", "E40-S03", "E40-T01", "E40-T02", "E40-T03", "E40-T04", "E40-T05",
        "E40-X01",
    }
)  # fmt: skip

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
#: Section 3's tables, one per STRIDE category, by their titles.
_CATEGORIES: Final = {
    "Spoofing": "S",
    "Tampering": "T",
    "Repudiation": "R",
    "Information disclosure": "I",
    "Denial of service": "D",
    "Elevation of privilege": "E",
}
#: Every element and boundary of section 2, each a row of the coverage matrix.
_ELEMENTS: Final = frozenset(
    [f"E{n}" for n in range(1, 9)]
    + [f"P{n}" for n in range(1, 15)]
    + [f"DS{n}" for n in range(1, 9)]
    + [f"TB-AL{n}" for n in range(1, 10)]
)
_THREAT: Final = re.compile(r"\bAL-[STRIDE]\d{2}\b")
_SEED: Final = re.compile(r"\bAC-AL-\d{2}\b")
_KEY: Final = re.compile(r"\bE\d{2}-[A-Z]\d{2}\b")  # a ticket key
_OWNER: Final = re.compile(
    r"\bE\d{2}(?:-[A-Z]\d{2})?\b|#\d+|\bG-\d+\b"
)  # an epic, a key, an issue, a gap
_TICKET: Final = re.compile(r"\bE\d{2}-[A-Z]\d{2}\b|#\d+")
_SR: Final = re.compile(r"\bSR-E40-\d{2}\b")
_GAP: Final = re.compile(r"\bG-\d+\b")
_RR: Final = re.compile(r"\bRR-\d+\b")
_R3_SPRINT: Final = re.compile(r"\bS1[4-9]\b")  # R3 runs S14 to S19 (`31-sprint-plan.md`)
_TICKED: Final = re.compile(r"`([^`]+)`")
#: An id inside a limit's value (a requirement, a ticket, a decision, an issue): not its number.
_ID: Final = re.compile(r"#\d+|\b(?:[A-Z]+-)*[A-Z]+-?\d+(?:[-.]\d+)*\b")
_BLANK: Final = frozenset({"", "-", "—"})


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, title: str) -> str:
    """The body under the heading titled `title` (its number aside), to the next heading of its
    level or above."""
    start = re.search(rf"^(#+) (?:\d+(?:\.\d+)*\.? )?{re.escape(title)}\b.*$", text, re.M)
    assert start is not None, f"no heading titled {title!r}"
    stop = re.compile(rf"^#{{1,{len(start[1])}}} ", re.M).search(text, start.end())
    return text[start.end() : stop.start() if stop else len(text)]


def _cells(line: str) -> list[str]:
    """A table row's cells, split on the pipes GFM does not escape, each `\\|` read as `|`."""
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip()[1:-1])]


def _tables(section: str) -> list[list[list[str]]]:
    """The tables in `section`, in order, each its body rows (the header and rule rows left out)."""
    tables: list[list[list[str]]] = []
    block: list[str] = []
    for line in [*section.splitlines(), ""]:
        if line.startswith("|"):
            block.append(line)
        elif block:
            tables.append([_cells(row) for row in block[2:]])
            block = []
    return tables


def _rows(section: str, first: str, width: int) -> dict[str, list[str]]:
    """The rows of the tables in `section` whose first cell matches `first`: their `width` other
    cells, by first cell."""
    out: dict[str, list[str]] = {}
    for row in (row for table in _tables(section) for row in table):
        if re.fullmatch(first, row[0]):
            assert row[0] not in out, f"{row[0]} twice"
            assert len(row) == width + 1, f"{row[0]}: {len(row) - 1} cells, not {width}"
            out[row[0]] = row[1:]
    return out


def _threats() -> dict[str, dict[str, list[str]]]:
    """Section 3's rows by category letter: element, threat, L, I, risk, control, gap, owner,
    verify, disposition, residual."""
    text = _text(_MODEL)
    return {
        letter: _rows(_section(text, title), _THREAT.pattern, 11)
        for title, letter in _CATEGORIES.items()
    }


def _all_threats() -> dict[str, list[str]]:
    return {rid: cells for rows in _threats().values() for rid, cells in rows.items()}


def _matrix() -> dict[str, list[str]]:
    """The coverage matrix by element or boundary id: the S, T, R, I, D and E cells."""
    rows = _rows(_section(_text(_MODEL), "Coverage matrix"), r"(?:E|P|DS|TB-AL)\d+ .+", 6)
    return {element.split(" ", 1)[0]: cells for element, cells in rows.items()}


def _seeds() -> dict[str, list[str]]:
    """The seed rows: rows, action, expected, the test that proves it, verdict."""
    return _rows(_text(_SEEDS), _SEED.pattern, 5)


def _requirements() -> dict[str, list[str]]:
    """Section 10's requirements: the requirement, its rows, its owner."""
    return _rows(_section(_text(_MODEL), "Requirements added by this model"), _SR.pattern, 3)


@cache
def _gaps() -> frozenset[str]:
    """The gaps section 8 assigns in writing."""
    return frozenset(_rows(_section(_text(_MODEL), "The boundary with other models"), r"G-\d+", 2))


def _owns(cell: str) -> bool:
    """`cell` names an owner that resolves: a live backlog key, an issue or a defined gap."""
    return any(
        token in _KEYS or token.startswith("#") or token in _gaps()
        for token in _OWNER.findall(cell)
    )


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
    assert sum(map(len, threats.values())) >= 41  # the tables held 41 rows when this was written
    for letter, rows in threats.items():
        assert rows, f"no {letter} threat"
        for rid, cells in rows.items():
            assert rid[3] == letter, rid
            element, threat, _l, _i, _risk, control, gap, owner, verify, disp, res = cells
            named = set(re.split(r",\s*", element))
            assert named and named <= _ELEMENTS, f"{rid}: element {element!r}"
            assert not _BLANK.intersection([threat, control, gap]), f"{rid}: a blank cell"
            assert not control.startswith("None") or _SR.search(gap), (
                f"{rid}: no control on `main` and no requirement"
            )
            assert _owns(owner), f"{rid}: no control owner that resolves"
            assert _SEED.search(verify) or (verify.startswith("NOT RUN:") and _owns(verify)), (
                f"{rid}: Verify names no seed and no owner it waits for"
            )
            assert set(re.split(r",\s*", disp)) <= {"Q", "C", "R"}, f"{rid}: disposition"
            assert res.split(" ", 1)[0] in _RANK, f"{rid}: residual"


def test_threat_model_risk_follows_the_rating_matrix() -> None:
    """Scenario: Every element and flow is analysed
    When the model is reviewed against the data-flow diagram
    Then each element and each flow has a STRIDE row, or an explicit "not applicable" with a reason

    (Rated: each risk is the model's L x I matrix, never a free choice, and no residual is above
    its row's risk.)
    """
    for rid, cells in _all_threats().items():
        likelihood, impact, risk, residual = cells[2], cells[3], cells[4], cells[10]
        assert (likelihood, impact) in _RISK, f"{rid}: L and I are L, M or H"
        assert risk.split(" ", 1)[0] == _RISK[likelihood, impact], (
            f"{rid}: {likelihood} x {impact} is not {risk}"
        )
        assert _RANK[residual.split(" ", 1)[0]] <= _RANK[_RISK[likelihood, impact]], (
            f"{rid}: residual {residual} above its risk"
        )


def test_threat_model_coverage_matrix_names_a_row_or_a_reason_in_every_cell() -> None:
    """Scenario: Every element and flow is analysed
    When the model is reviewed against the data-flow diagram
    Then each element and each flow has a STRIDE row, or an explicit "not applicable" with a reason
    """
    threats = set(_all_threats())
    matrix = _matrix()
    assert set(matrix) == _ELEMENTS
    for element, cells in matrix.items():
        for letter, cell in zip("STRIDE", cells, strict=True):
            named = set(_THREAT.findall(cell))
            assert re.match(r"n/a: \S+ \S+", cell) or (named and named <= threats), (
                f"{element} / {letter}: neither a known row nor a reasoned n/a: {cell!r}"
            )


def test_threat_model_coverage_matrix_gives_a_reason_for_every_n_a() -> None:
    """Scenario: Every element and flow is analysed
    Then each element and each flow has a STRIDE row, or an explicit "not applicable" with a reason
    """
    matrix = _section(_text(_MODEL), "Coverage matrix")
    assert re.findall(r"\bn/a\b(?!: \S+ \S+)", matrix) == [], "an n/a with no written reason"


def test_threat_model_every_matrix_element_is_defined_in_the_data_flow_section() -> None:
    """Scenario: Every element and flow is analysed against the data-flow diagram, so each matrix
    row is an element or a boundary the data-flow section defines."""
    flows_section = _section(_text(_MODEL), "Data-flow diagram and trust boundaries")
    for element in _ELEMENTS:
        assert re.search(rf"\*\*{element}\b", flows_section), f"{element} is not in section 2"


def test_threat_model_every_flow_is_drawn_and_crosses_a_boundary_of_the_matrix() -> None:
    """Scenario: Every element and flow is analysed
    When the model is reviewed against the data-flow diagram
    Then each element and each flow has a STRIDE row, or an explicit "not applicable" with a reason
    """
    flows_section = _section(_text(_MODEL), "Data-flow diagram and trust boundaries")
    flows = _rows(flows_section, r"F\d+", 3)
    diagram = flows_section.split("```", 2)[1]
    assert flows and set(re.findall(r"\|(F\d+)\|", diagram)) == set(flows)
    for flow, (_route, what, boundary) in flows.items():
        assert what not in _BLANK, flow
        crossed = set(re.findall(r"\bTB-AL\d\b", boundary))
        assert crossed and crossed <= _ELEMENTS, f"{flow}: analysed on no boundary of 3.7"


def test_threat_model_every_row_is_named_in_the_matrix_row_of_each_element_it_lists() -> None:
    """Scenario: Every element and flow is analysed: a row's elements and the matrix agree, so a
    row cannot analyse an element whose matrix row leaves it out."""
    matrix = _matrix()
    for rid, cells in _all_threats().items():
        for element in re.split(r",\s*", cells[0]):
            assert rid in _THREAT.findall(" ".join(matrix[element])), (
                f"{rid} lists {element}, whose matrix row leaves it out"
            )


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
    invariant = _section(_text(_MODEL), "The notify-only invariant")
    layers = _rows(invariant, r"L\d", 3)
    assert sorted(layers) == [f"L{n}" for n in range(1, 9)]
    for layer, (_holds, where, proof) in layers.items():
        assert where not in _BLANK and proof not in _BLANK, layer
        if proof.startswith("NEW"):  # a test Part B writes, under its seed
            assert _SEED.search(proof), f"{layer}: NEW names no seed"
        elif layer != "L1":  # L1 is the contract, which the `contract` check diffs
            assert "::test_" in proof, f"{layer}: no test named"
            assert _missing_citations(proof) == [], f"{layer}: {_missing_citations(proof)}"
    for layer in ("L2", "L3", "L5"):  # E40-T02's own controls, each proved by a test on `main`
        assert not layers[layer][2].startswith("NEW"), layer
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
    for sid, (rows, action, expected, proof, verdict) in seeds.items():
        named = set(_THREAT.findall(rows))
        assert named and named <= threats, f"{sid}: rows {rows!r}"
        assert not _BLANK.intersection([action, expected, proof]), f"{sid}: an empty cell"
        assert re.search(r"\b(?:COVERED|NEW|WAITING)\b", verdict), f"{sid}: verdict"
        if "WAITING" in verdict:
            assert _TICKET.search(verdict), f"{sid}: WAITING names no ticket"


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


def test_threat_model_every_seed_a_row_verifies_with_lists_that_row() -> None:
    """Scenario: Abuse cases are executable (edge): a row's Verify seed is a seed written for that
    row, so the seed that proves a row names it."""
    seeds = _seeds()
    for rid, cells in _all_threats().items():
        for sid in _SEED.findall(cells[8]):
            assert rid in _THREAT.findall(seeds[sid][0]), (
                f"{rid} cites {sid}, whose Rows leave it out"
            )


def test_threat_model_high_and_critical_findings_have_an_r3_owner_or_an_accepted_risk_record() -> (
    None
):
    """Scenario: An unmitigated High is escalated (failure)
    Given a High finding with no control landing in R3
    Then it is recorded as accepted risk with Owner sign-off, or the epic scope changes; it is
    not left silently open
    """
    threats = _all_threats()
    findings = _rows(_section(_text(_MODEL), "Findings register"), r"F-\d{2}", 4)
    assert len(findings) >= 20  # F-01 to F-20 when this was written
    for fid, (rows, severity, owning, note) in findings.items():
        named = _THREAT.findall(rows)
        assert named and set(named) <= set(threats), f"{fid}: rows {rows!r}"
        worst = max((threats[r][4].split(" ", 1)[0] for r in named), key=_RANK.__getitem__)
        assert severity == worst, f"{fid}: {severity} is not its rows' {worst}"
        if severity in ("High", "Critical"):
            assert _TICKET.search(owning), f"{fid}: no owning ticket"
            r5_residual = "R5" in owning and "Low in R3" in note
            assert _R3_SPRINT.search(owning) or r5_residual or _RR.search(owning), (
                f"{fid}: no R3 sprint, no R5 residual and no accepted-risk record"
            )
    registered = {rid for cells in findings.values() for rid in _THREAT.findall(cells[0])}
    for rid, cells in threats.items():
        if cells[4].split(" ", 1)[0] in ("High", "Critical"):
            assert rid in registered, f"{rid}: a High or Critical row with no finding"
            assert _R3_SPRINT.search(cells[7]) or "R5" in cells[7], f"{rid}: owner has no sprint"


def test_threat_model_limits_table_states_a_number_and_a_source_per_row() -> None:
    """The ticket's Performance notes: "Denial-of-service findings must state numeric limits
    (alerts per user, evaluation queue depth, ack-all batch size) so the implementing tickets have
    a target rather than an adjective." (Part A DoD: Numeric DoS limits stated.)
    """
    limits = _rows(_section(_text(_MODEL), "Limits and rates"), r".+", 3)
    assert len(limits) >= 35  # the table held 35 rows when this was written
    for limit, (value, status, source) in limits.items():
        assert re.search(r"\d", _ID.sub("", value)), f"{limit}: no number beside its ids"
        assert status not in _BLANK and source not in _BLANK, f"{limit}: no status or source"
    for named in ("Armed alerts per user", "Evaluation queue", "`ack-all`"):
        assert named in limits, f"the ticket's {named} limit is missing"


def test_threat_model_os_notification_cap_never_refuses_or_counts_an_override_kind() -> None:
    """The ticket's Performance notes ask for numeric limits, and no limit may hold back what
    E40-D02 6.2 locks on ("always delivered"): the OS-notification cap in the limits and in
    SR-E40-09 counts alert deliveries and test fires only and exempts every override kind,
    SR-E40-09 answers AL-E04 (an override kind held back), and AC-AL-17 raises a kill-switch
    notification with the cap reached.
    """
    exempt = (
        "counts alert deliveries and test fires only and never refuses or counts an override kind"
    )
    limits = _rows(_section(_text(_MODEL), "Limits and rates"), r".+", 3)
    requirement, rows, _owner = _requirements()["SR-E40-09"]
    assert exempt in limits["OS notifications raised"][0], "the cap holds an override kind back"
    assert exempt in requirement and "AL-E04" in _THREAT.findall(rows), "SR-E40-09"
    seed_rows, action, expected, _proof, _verdict = _seeds()["AC-AL-17"]
    assert "AL-E04" in _THREAT.findall(seed_rows)
    assert "20 alert notifications raised" in action and "a kill-switch notification" in action
    assert "with 20 raised, a kill-switch notification still shows" in expected


def test_threat_model_ticket_map_is_the_first_ticket_heading_and_names_every_e40_key() -> None:
    """Part A DoD: "Every Critical/High has an owner, a target ticket and a testable control."
    The control-to-ticket map is the section GOV-008 reads (the first heading holding "ticket"),
    and it names every E40 ticket that is not retired.
    """
    text = _text(_MODEL)
    first = next(h for h in re.findall(r"^#{2,3} .*$", text, re.M) if "ticket" in h.lower())
    assert re.fullmatch(r"#{2,3} (?:[\d.]+ )?Control-to-ticket map", first), first
    keys = {key for key in _KEYS if re.fullmatch(r"E40-[A-Z]\d{2}", key)}
    mapped = set(_rows(_section(text, "Control-to-ticket map"), r"E40-[A-Z]\d{2}", 1))
    assert len(keys) >= 15 and keys <= mapped, sorted(keys - mapped)


def test_threat_model_every_ticket_key_it_names_is_live_in_the_backlog() -> None:
    """Part A DoD: "Every Critical/High has an owner, a target ticket and a testable control."
    A key that names no ticket, or a retired one, owns nothing."""
    named = set(_KEY.findall(_text(_MODEL) + _text(_SEEDS)))
    assert named and named <= _KEYS, sorted(named - _KEYS)


def test_threat_model_every_requirement_gap_and_accepted_risk_it_names_is_defined() -> None:
    """Part A DoD: "Every Critical/High has an owner, a target ticket and a testable control."
    A requirement, a gap or an accepted-risk record named anywhere is one the documents define."""
    text = _text(_MODEL) + _text(_SEEDS)
    for named, defined in (
        (set(_SR.findall(text)), set(_requirements())),
        (set(_GAP.findall(text)), set(_gaps())),
        (set(_RR.findall(text)), set(re.findall(r"^\| (RR-\d+) ", _text(_PROGRAMME), re.M))),
    ):
        assert named <= defined, sorted(named - defined)


def test_threat_model_requirements_and_the_rows_they_answer_name_each_other() -> None:
    """Part A DoD: "Every Critical/High has an owner, a target ticket and a testable control."
    A requirement lists the rows it answers, and each of those rows names it as its gap."""
    threats, requirements = _all_threats(), _requirements()
    for sr, (_requirement, rows, _owner) in requirements.items():
        for rid in _THREAT.findall(rows):
            assert sr in threats[rid][6], f"{sr} answers {rid}, whose gap does not name it"
    for rid, cells in threats.items():
        for sr in _SR.findall(cells[6]):
            assert sr in requirements, f"{rid} names {sr}, which section 10 does not define"
            assert rid in _THREAT.findall(requirements[sr][1]), f"{rid} names {sr}; it omits {rid}"


def test_threat_model_names_each_private_finding_by_id_class_and_severity_under_its_row() -> None:
    """Part A: a finding about code on `main` goes to the private process and is named here by
    id, class and severity only, under the row that carries its requirement."""
    routed = " ".join(_section(_text(_MODEL), "Routed to the private advisory process").split())
    found = re.findall(r"PF-(\d+) \(([^,()]+), ([^,()]+), under (AL-[STRIDE]\d{2})\)", routed)
    assert [int(n) for n, *_ in found] == list(range(1, len(found) + 1)) and len(found) >= 6
    threats = _all_threats()
    for n, _class, _severity, rid in found:
        assert f"PF-{n} (§12.2)" in threats[rid][5], f"PF-{n}: its row {rid} does not name it"


def test_threat_model_and_its_register_entry_are_owned_by_a_raci_role() -> None:
    """Part A DoD: the model and its register entry name their owner, a role of `33-raci.md`."""
    roles = {row[1] for row in _tables(_section(_text(_RACI), "Roles"))[0]}
    header = re.search(r"Owner: ([^(.]+?) \(", _text(_MODEL))
    entry = re.search(r"Owner \*\*([^*]+)\*\*", _section(_text(_REGISTER), "RSK-093"))
    assert header and entry and {header[1], entry[1]} <= roles, roles


def test_risk_register_partitions_count_every_entry_exactly_once() -> None:
    """Part A DoD: the register gains RSK-093 and keeps its own invariant (`32-risk-register.md`
    10.1.1): the `### RSK-nnn` headings equal the total, and the score bands, the categories and
    the `Risk` values each count every entry exactly once."""
    text = _text(_REGISTER)
    entries = sorted(re.findall(r"^### RSK-(\d{3}) ", text, re.M))
    assert len(entries) == len(set(entries)) >= 88
    for title, first in (
        ("Register summary", r"\*\*(?:Critical|High|Medium) .+"),
        ("Risks by category", r"(?!\*\*).+"),
        ("Risks by `Risk` field value", r"R\d+ .+"),
    ):
        table = _tables(_section(text, title))[0]
        parts = [row for row in table if re.fullmatch(first, row[0])]
        ids = sorted(n for row in parts for n in re.findall(r"(?:RSK-)?(\d{3})\b", row[2]))
        assert ids == entries, f"{title}: not every entry exactly once"
        total = next(row[1] for row in table if row[0].startswith("**Total"))
        assert sum(int(row[1]) for row in parts) == int(total.strip("*")) == len(entries), title


def test_risk_register_rsk_093_is_a_high_r6_entry_that_gates_r3_and_lists_its_findings() -> None:
    """Part A DoD: RSK-093 under R6 (the ruling's BQ-3), scored High, gating R3, and naming every
    finding the model files under it."""
    text = _text(_REGISTER)
    entry = _section(text, "RSK-093")
    assert "`Risk: R6` · Category **Security** · L 3 · I 4 · **Score 12 — High**" in entry
    gating = _rows(_section(text, "Risks gating each release train"), r"R\d", 1)
    assert "RSK-093" in gating["R3"][0]
    distinct = {n for (cell,) in gating.values() for n in re.findall(r"RSK-(\d{3})", cell)}
    stated = re.search(r"Distinct IDs referenced at least once as a gating item: (\d+) of", text)
    assert stated and int(stated[1]) == len(distinct)
    findings = _rows(_section(_text(_MODEL), "Findings register"), r"F-\d{2}", 4)
    filed = {fid for fid, cells in findings.items() if "RSK-093" in cells[3]}
    assert filed and filed <= set(re.findall(r"\bF-\d{2}\b", entry)), sorted(filed)


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
    assert len(cited) >= 173 and missing == [], missing  # 173 citations when this was written
    assert "services/api/tests/security/alerts/ssrf_corpus.json" in cited
