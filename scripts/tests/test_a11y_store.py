"""Meta-tests for the QA gate and trend results store (E47-Q04, BQ-02): schema, replace-not-duplicate, redaction."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.a11y import store

ROOT = Path(__file__).resolve().parents[2]
DAY = dt.date(2026, 11, 3)  # sprint 6 (Fri 2026-10-30 to Thu 2026-11-05)
BUILD = "abcdef1234567"


def _r(**kw: object) -> dict:
    base = {"source": "Q04", "kind": "axe", "screen": "R-001", "outcome": "pass",
            "metrics": {"serious": 0}, "tags": ["epic:E47", "criterion:1.4.3"], "build": BUILD,
            "recorded": DAY.isoformat()}
    return {**base, **kw}


def test_sprint_calendar_matches_the_one_week_fri_thu_calendar() -> None:
    assert store.sprint_of(dt.date(2026, 9, 25)) == 1 and store.sprint_of(dt.date(2026, 10, 1)) == 1
    assert store.sprint_of(dt.date(2026, 10, 2)) == 2 and store.sprint_of(DAY) == 6
    assert store.sprint_range(6) == (dt.date(2026, 10, 30), dt.date(2026, 11, 5))


def test_valid_result_passes_and_each_defect_is_named() -> None:
    assert store.validate_result(_r()) == []
    bad = {
        "source": "Q99", "kind": "x", "outcome": "green", "screen": "login", "metrics": {"a": "1"},
        "tags": ["criterion:1.4.3"], "build": "xyz", "recorded": "soon",
    }
    errs = store.validate_result({**_r(), **bad})
    for word in ("source", "kind", "outcome", "screen", "metrics", "tags", "build", "recorded"):
        assert any(word in e for e in errs), word
    assert "missing build" in store.validate_result({k: v for k, v in _r().items() if k != "build"})
    assert "unknown field" in store.validate_result({**_r(), "defect": "A11Y-F-0001"})[0]


def test_schema_file_agrees_with_the_validator() -> None:
    sch = json.loads((ROOT / "qa/evidence/e47/results.schema.json").read_text(encoding="utf-8"))
    item = sch["properties"]["results"]["items"]
    assert tuple(item["required"]) == store.FIELDS
    assert tuple(item["properties"]["source"]["enum"]) == store.SOURCES
    assert tuple(item["properties"]["kind"]["enum"]) == store.KINDS
    assert tuple(item["properties"]["outcome"]["enum"]) == store.OUTCOMES


def test_append_creates_the_sprint_file_and_replaces_the_same_identity(tmp_path: Path) -> None:
    path = store.append_results(tmp_path, [_r(), _r(screen="R-901")], DAY)
    assert path.name == "sprint-06.json"
    store.append_results(tmp_path, [_r(outcome="fail", metrics={"serious": 2})], DAY)
    doc = store.load_sprint(path)
    assert doc["start"] == "2026-10-30" and doc["end"] == "2026-11-05"
    assert len(doc["results"]) == 2  # re-recording replaced, did not double count
    first = next(r for r in doc["results"] if r["screen"] == "R-001")
    assert first["outcome"] == "fail" and first["metrics"] == {"serious": 2}
    store.append_results(tmp_path, [_r(build="1234567")], DAY)  # another build is another result
    assert len(store.load_sprint(path)["results"]) == 3


def test_append_refuses_invalid_future_or_mixed_sprint_results(tmp_path: Path) -> None:
    with pytest.raises(store.StoreError):
        store.append_results(tmp_path, [_r(outcome="green")], DAY)
    with pytest.raises(store.StoreError, match="future"):
        store.append_results(tmp_path, [_r(recorded="2026-11-04")], DAY)
    with pytest.raises(store.StoreError, match="one sprint"):
        store.append_results(tmp_path, [_r(), _r(recorded="2026-10-20")], DAY)
    with pytest.raises(store.StoreError):
        store.append_results(tmp_path, [], DAY)
    assert not list(tmp_path.glob("*.json"))


def test_seeded_secret_never_reaches_the_store(tmp_path: Path) -> None:
    email = "trader.one" + "@" + "example.com"
    # redaction runs before validation: the tag no longer fits the schema, so nothing is written at all
    with pytest.raises(store.StoreError, match="tags"):
        store.append_results(tmp_path, [_r(screen="R-001", tags=["epic:E47", f"note:{email}"])], DAY)
    assert not list(tmp_path.glob("*.json"))


def test_load_store_rejects_a_misnamed_or_malformed_file(tmp_path: Path) -> None:
    store.append_results(tmp_path, [_r()], DAY)
    (tmp_path / "sprint-06.json").rename(tmp_path / "sprint-07.json")
    with pytest.raises(store.StoreError, match="does not match"):
        store.load_store(tmp_path)
    (tmp_path / "sprint-07.json").write_text('{"schemaVersion": 2}', encoding="utf-8")
    with pytest.raises(store.StoreError):
        store.load_store(tmp_path)


def _reports(d: Path) -> None:
    node = {"target": ["#a"]}
    (d / "axe.json").write_text(json.dumps({"screens": {
        "R-001": {"violations": [{"id": "label", "impact": "serious", "nodes": [node, node]},
                                 {"id": "region", "impact": "moderate", "nodes": [node]}]},
        "R-901": {"violations": []}}}), encoding="utf-8")
    (d / "lighthouse.json").write_text(json.dumps({"scores": {"SCR-001": 0.98, "SCR-155": 0.9},
                                                   "pending": {"SCR-030": "pending E11"}}), encoding="utf-8")
    (d / "keyboard.json").write_text(json.dumps({"mouseEvents": 0, "steps": [{"name": "a", "ok": True}]}), encoding="utf-8")


def test_results_from_reports_counts_nodes_and_outcomes(tmp_path: Path) -> None:
    _reports(tmp_path)
    res = {(r["kind"], r["screen"]): r for r in store.results_from_reports(tmp_path, BUILD, DAY)}
    assert all(store.validate_result(r) == [] for r in res.values())
    assert res["axe", "R-001"]["outcome"] == "fail" and res["axe", "R-001"]["metrics"]["serious"] == 2
    assert res["axe", "R-001"]["metrics"]["moderate"] == 1 and res["axe", "R-901"]["outcome"] == "pass"
    assert res["lighthouse", "SCR-001"]["outcome"] == "pass" and res["lighthouse", "SCR-155"]["outcome"] == "fail"
    assert res["lighthouse", "SCR-030"]["outcome"] == "pending" and res["keyboard", "*"]["outcome"] == "pass"


def test_cli_record_and_missing_reports_is_infra(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rep, out = tmp_path / "rep", tmp_path / "out"
    rep.mkdir()
    today = dt.date.today().isoformat()
    assert store.main(["record", str(rep), "--build", BUILD, "--date", today, "--store", str(out)]) == 3
    _reports(rep)
    assert store.main(["record", str(rep), "--build", BUILD, "--date", today, "--store", str(out)]) == 0
    assert len(store.load_store(out)) == 1
