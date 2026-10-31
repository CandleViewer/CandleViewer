"""E47-K01 / E47-T01: the a11y findings files validate against the finding-record schema.

v1 (E47-K01) files still validate unchanged; v2 (E47-T01, BQ-12 of the #1323 ruling of record) adds the
per-screen rows, pattern groups and the rules below. The register `docs/plan/a11y/findings.json` is
checked here too, with the cross-document rules a JSON Schema cannot express (unique ids, exactly one
row per SCR-001..159, references resolve). No workflow runs this file yet (a row for E47-Q08).
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

jsonschema = pytest.importorskip("jsonschema")

A11Y = Path(__file__).resolve().parents[2] / "docs" / "plan" / "a11y"
SCR_IDS = [f"SCR-{n:03d}" for n in range(1, 160)]
UNREACHABLE = (
    "unreachable: not built",
    "unreachable: built, not mounted",
    "unreachable: needs a state the harness cannot induce",
)
V1_DOC: dict[str, Any] = {
    "schemaVersion": 1,
    "build": "EXAMPLE-NOT-A-REAL-FINDING",
    "findings": [
        {
            "id": "A11Y-F-0001",
            "screenId": "SCR-152",
            "state": "disconnected",
            "componentId": "none",
            "wcagSc": "4.1.3",
            "level": "A",
            "severity": "serious",
            "reproduction": "Illustrative v1 record (E47-K01's shape).",
            "detection": {"source": "manual", "tool": "nvda", "heuristic": True},
            "owningTicket": "unassigned",
            "status": "open",
        }
    ],
}


def _load(name: str) -> Any:
    return json.loads((A11Y / name).read_text(encoding="utf-8"))


def _schema() -> Any:
    return _load("finding-record.schema.json")


def _validate(doc: Any) -> None:
    jsonschema.Draft202012Validator(_schema()).validate(doc)


def _rejected(doc: Any) -> None:
    with pytest.raises(jsonschema.ValidationError):
        _validate(doc)


def _example() -> Any:
    return copy.deepcopy(_load("findings.example.json"))


def test_schema_is_a_valid_draft_2020_12_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(_schema())


def test_example_findings_file_validates_against_schema() -> None:
    _validate(_load("findings.example.json"))


def test_v1_document_still_validates() -> None:
    _validate(copy.deepcopy(V1_DOC))


def test_v1_document_with_v2_screens_is_rejected() -> None:
    doc = copy.deepcopy(V1_DOC)
    doc["screens"] = []
    _rejected(doc)


def test_unknown_schema_version_is_rejected() -> None:
    doc = _example()
    doc["schemaVersion"] = 3
    _rejected(doc)


def test_v2_document_without_screens_is_rejected() -> None:
    doc = _example()
    del doc["screens"]
    _rejected(doc)


def test_finding_with_invalid_wcag_level_is_rejected() -> None:
    doc = _example()
    doc["findings"][0]["level"] = "AAA"
    _rejected(doc)


def test_finding_missing_required_field_is_rejected() -> None:
    doc = _example()
    del doc["findings"][0]["owningTicket"]
    _rejected(doc)


def test_level_a_finding_with_exception_nomination_is_rejected() -> None:
    doc = _example()
    doc["findings"][0]["level"] = "A"
    doc["findings"][0]["priority"] = "P1"
    _rejected(doc)


def test_level_a_finding_owned_by_this_task_is_rejected() -> None:
    doc = _example()
    f = doc["findings"][0]
    del f["exception"]
    f.update(level="A", priority="P1", owningTicket="E47-T01 #1323")
    _rejected(doc)


def test_level_a_finding_owned_by_an_epic_is_rejected() -> None:
    doc = _example()
    f = doc["findings"][0]
    del f["exception"]
    f.update(level="A", priority="P1", owningTicket="E10 (epic) #37")
    _rejected(doc)


def test_level_a_finding_with_p2_priority_is_rejected() -> None:
    doc = _example()
    f = doc["findings"][0]
    del f["exception"]
    f.update(level="A", priority="P2")
    _rejected(doc)


def test_level_a_finding_in_the_needs_filing_go_table_validates() -> None:
    doc = _example()
    f = doc["findings"][0]
    del f["exception"]
    f.update(level="A", priority="P1", owningTicket="needs-filing-go", needsFilingGo=True)
    doc["patterns"][0]["owningTicket"] = "needs-filing-go"
    _validate(doc)


def test_needs_filing_go_owner_without_the_flag_is_rejected() -> None:
    doc = _example()
    doc["findings"][0]["owningTicket"] = "needs-filing-go"
    _rejected(doc)


def test_aa_finding_owned_by_an_epic_is_rejected() -> None:
    doc = _example()
    doc["findings"][0]["owningTicket"] = "E10 (epic) #37"
    _rejected(doc)


def test_epic_owner_on_a_covered_screen_row_is_rejected() -> None:
    doc = _example()
    doc["screens"][0]["owningTicket"] = "E17 (epic) #48"
    _rejected(doc)


def test_epic_owner_on_an_unreachable_screen_row_validates() -> None:
    doc = _example()
    assert doc["screens"][1]["coverage"] in UNREACHABLE
    _validate(doc)


def test_pass_on_an_unreachable_row_is_rejected() -> None:
    doc = _example()
    doc["screens"][1]["wcag22"]["2.5.8"]["verdict"] = "pass"
    _rejected(doc)


def test_n_a_on_an_unreachable_row_is_rejected() -> None:
    doc = _example()
    doc["screens"][1]["wcag22"]["3.3.8"]["verdict"] = "n/a (no authentication)"
    _rejected(doc)


def test_pass_evidence_on_an_unreachable_row_is_rejected() -> None:
    doc = _example()
    doc["screens"][1]["evidence"]["automated"]["verdict"] = "pass"
    _rejected(doc)


def test_covered_state_on_an_unreachable_row_is_rejected() -> None:
    doc = _example()
    doc["screens"][1]["states"][0]["status"] = "covered"
    _rejected(doc)


def test_partial_row_verdict_without_scope_is_rejected() -> None:
    doc = _example()
    del doc["screens"][0]["wcag22"]["2.4.11"]["scope"]
    _rejected(doc)


def test_verdict_outside_the_four_values_is_rejected() -> None:
    doc = _example()
    doc["screens"][0]["wcag22"]["2.4.11"]["verdict"] = "n/a"
    _rejected(doc)


def test_builtin_wcag_exception_is_a_pass_value() -> None:
    doc = _example()
    doc["screens"][0]["wcag22"]["2.5.8"]["verdict"] = "pass (exception: spacing)"
    _validate(doc)


def test_unreachable_state_without_reason_is_rejected() -> None:
    doc = _example()
    del doc["screens"][0]["states"][1]["reason"]
    _rejected(doc)


def test_sr_column_owner_is_e47_t04() -> None:
    doc = _example()
    doc["screens"][0]["evidence"]["sr"]["owner"] = "E47-T01"
    _rejected(doc)


# --------------------------------------------------------------------------- the register itself


def _register() -> Any:
    path = A11Y / "findings.json"
    assert path.is_file(), "docs/plan/a11y/findings.json (the E47-T01 register) must exist"
    return json.loads(path.read_text(encoding="utf-8"))


def test_register_validates_against_schema() -> None:
    doc = _register()
    assert doc["schemaVersion"] == 2
    _validate(doc)


def test_register_has_exactly_one_row_per_screen_id() -> None:
    ids = [s["id"] for s in _register()["screens"]]
    assert sorted(ids) == SCR_IDS
    assert len(ids) == len(set(ids)) == 159


def test_register_ids_are_unique() -> None:
    doc = _register()
    for key in ("findings", "patterns"):
        ids = [x["id"] for x in doc[key]]
        assert len(ids) == len(set(ids)), f"duplicate {key} ids"


def test_register_references_resolve() -> None:
    doc = _register()
    rows = {s["id"]: s for s in doc["screens"]}
    findings = {f["id"]: f for f in doc["findings"]}
    patterns = {p["id"]: p for p in doc["patterns"]}
    for f in doc["findings"]:
        for scr in [f["screenId"], *f.get("alsoOn", [])]:
            assert scr in rows, f"{f['id']}: unknown screen {scr}"
            assert rows[scr]["coverage"] in (
                "covered",
                "partial",
            ), f"{f['id']}: {scr} is not audited"
            assert rows[scr]["noFindings"] is False, f"{f['id']}: {scr} claims no findings"
        assert f["screenId"] not in f.get("alsoOn", []), f"{f['id']}: screenId repeated in alsoOn"
        if "pattern" in f:
            assert f["pattern"] in patterns, f"{f['id']}: unknown pattern"
            listed = patterns[f["pattern"]]["findings"]
            assert f["id"] in listed, f"{f['id']}: not listed in its pattern"
    for p in doc["patterns"]:
        for fid in p["findings"]:
            assert fid in findings, f"{p['id']}: unknown finding {fid}"
            named = findings[fid].get("pattern")
            assert named == p["id"], f"{p['id']}: {fid} names another pattern"
        for scr in p["screenIds"]:
            assert scr in rows, f"{p['id']}: unknown screen {scr}"
    for s in doc["screens"]:
        cells = [
            s["evidence"][k]
            for k in ("automated", "keyboard", "deep", "spot")
            if k in s["evidence"]
        ]
        cells += list(s.get("wcag22", {}).values())
        for cell in cells:
            for fid in cell.get("findings", []):
                assert fid in findings, f"{s['id']}: unknown finding {fid}"


def test_register_no_findings_rows_are_audited_and_clean() -> None:
    doc = _register()
    named = {scr for f in doc["findings"] for scr in [f["screenId"], *f.get("alsoOn", [])]}
    for s in doc["screens"]:
        if s["noFindings"]:
            assert s["coverage"] in ("covered", "partial"), s["id"]
            assert s["id"] not in named, s["id"]
