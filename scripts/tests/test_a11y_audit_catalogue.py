"""E47-D02 (#1301): the audit catalogue tool joins, maps, routes and gates correctly.

Stdlib + pytest only (the governance lane has no candleviewer package). Synthetic cases run on a
fixture tree under tmp_path; the real-input cases read the committed register and reviews.
"""

import copy
import importlib.util
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "a11y_catalogue", ROOT / "docs" / "plan" / "a11y" / "_tools" / "catalogue.py"
)
assert _spec and _spec.loader
cat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cat)

REVIEW = """# Review

| F    | Class         | Severity | Clause              | Sentence · replacement | Owner |
| ---- | ------------- | -------- | ------------------- | ---------------------- | ----- |
| F-1  | screen reader | Blocker  | `6.5`; 4.1.2; 2.5.3 | SCR-001 six boxes · one input | E09-D03 |
| F-2  | contrast      | Minor    | 1.4.3               | no screen named here · fix it | E09-D03 |
| F-3  | copy          | Info     | 3.3.1               | SCR-002 and SCR-003 \\| pipe · reword | E09-D03 |

Not a table row.
"""
SCREENS = """# 14

### SCR-001 — Login

- **A11y:** canvas has `role="img"` and a label; a mirror table below.
- **Design sign-off acceptance checklist:** [x] one [ ] two [ ] three **Stories:** US-1.

### SCR-002 — Second

- **A11y:** plain form.
- **Sign-off checklist:** [ ] a.

### SCR-003 — Third

- **A11y:** the overlay is not a canvas.
"""


def _t01_finding(
    fid: str, scr: str, sev: str, sc: str = "2.4.3", **kw: Any
) -> dict[str, Any]:
    return {
        "id": fid, "screenId": scr, "wcagSc": sc, "level": "A", "severity": sev,
        "title": kw.get("title", "t"), "observed": kw.get("observed", ""),
        "expected": "fix", "owningTicket": "#1", **kw,
    }  # fmt: skip


def make_tree(tmp: Path, findings: list[dict[str, Any]] | None = None) -> Path:
    real = json.loads((ROOT / cat.ROUTING_REL).read_text(encoding="utf-8"))
    real["reviews"] = [{"key": "E00-D00", "path": "docs/design/review.md"}]
    real["pendingReviews"] = ["E99-D99"]
    real["overrides"] = {}
    (tmp / "docs/plan/a11y").mkdir(parents=True)
    (tmp / "docs/design").mkdir(parents=True)
    (tmp / "docs/plan/backlog").mkdir(parents=True)
    (tmp / cat.ROUTING_REL).write_text(json.dumps(real), encoding="utf-8")
    (tmp / "docs/design/review.md").write_text(REVIEW, encoding="utf-8")
    (tmp / cat.CATALOGUE_REL).write_text(SCREENS, encoding="utf-8")
    shots = []
    for scr in cat.SCR_IDS:
        cov = (
            "reserved: no screen"
            if scr not in ("SCR-001", "SCR-002", "SCR-003")
            else "covered"
        )
        if scr == "SCR-003":
            cov = "unreachable: not built"
        shots.append({"id": scr, "name": scr, "coverage": cov, "owningTicket": "x"})
    doc = {"auditedSha": "abc", "screens": shots, "findings": findings or []}
    (tmp / cat.FINDINGS_REL).write_text(json.dumps(doc), encoding="utf-8")
    (tmp / cat.E47_REL).write_text(
        json.dumps([{"key": f"E47-D{n:02d}"} for n in range(3, 11)]), encoding="utf-8"
    )
    return tmp


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    return make_tree(tmp_path, [_t01_finding("A11Y-F-0001", "SCR-001", "serious")])


def test_review_table_parser_reads_rows_and_skips_prose() -> None:
    rows = cat.parse_review_table(REVIEW)
    assert [r["f"] for r in rows] == ["F-1", "F-2", "F-3"]
    assert rows[2]["sentence · replacement"].startswith("SCR-002 and SCR-003 \\| pipe")


def test_review_findings_extract_screens_sc_and_replacement() -> None:
    smap = {"blocker": "blocker", "minor": "minor", "info": "info", "major": "major"}
    got = cat.review_findings("E00-D00", REVIEW, smap)
    assert got[0]["screens"] == ["SCR-001"] and got[0]["sc"] == ["4.1.2", "2.5.3"]
    assert got[0]["remedy"] == "one input" and got[0]["severity"] == "blocker"
    assert got[1]["screens"] == []  # unattributed, never dropped
    assert got[2]["screens"] == ["SCR-002", "SCR-003"]


def test_review_unmapped_severity_fails() -> None:
    with pytest.raises(cat.CatalogueError, match="no mapping"):
        cat.review_findings("E00-D00", REVIEW, {"blocker": "blocker"})


def test_screen_facts_checklist_surface_and_layers() -> None:
    s = cat.parse_screens(SCREENS)
    assert s["SCR-001"]["signoff"] == {
        "line": "Design sign-off acceptance checklist", "checked": 1, "unchecked": 2,
    }  # fmt: skip
    assert s["SCR-001"]["surface"] == "canvas"
    assert s["SCR-001"]["canvasLayers"]["canvasRole"] == "present"
    assert (
        s["SCR-002"]["signoff"]["unchecked"] == 1
        and s["SCR-002"]["surface"] == "chrome"
    )
    assert s["SCR-003"]["signoff"] is None and s["SCR-003"]["canvasLayers"] is None


def test_duplicate_screen_in_catalogue_fails() -> None:
    with pytest.raises(cat.CatalogueError, match="twice"):
        cat.parse_screens(SCREENS + "\n### SCR-001 — Again\n")


@pytest.mark.parametrize(
    ("sev", "task", "want"),
    [("serious", "", "major"), ("moderate", "", "minor"), ("minor", "", "minor"),
     ("serious", "this is task-blocking for keyboard", "blocker")],
)  # fmt: skip
def test_t01_severity_map(tmp_path: Path, sev: str, task: str, want: str) -> None:
    root = make_tree(
        tmp_path, [_t01_finding("A11Y-F-0001", "SCR-001", sev, observed=task)]
    )
    got = cat.build(root)["findings"][0]
    assert got["severity"] == want and got["sourceSeverity"] == sev


def test_t01_unmapped_severity_fails(tmp_path: Path) -> None:
    root = make_tree(tmp_path, [_t01_finding("A11Y-F-0001", "SCR-001", "catastrophic")])
    with pytest.raises(cat.CatalogueError, match="no mapping"):
        cat.build(root)


def test_join_keeps_t01_ids_and_attaches_review_rows(tree: Path) -> None:
    reg = cat.build(tree)
    s1 = next(s for s in reg["screens"] if s["id"] == "SCR-001")
    assert "A11Y-F-0001" in s1["findings"] and "A11Y-R-E00-D00-F-1" in s1["findings"]
    assert s1["verdict"] == "findings"
    assert [f["id"] for f in reg["unattributed"]] == ["A11Y-R-E00-D00-F-2"]
    assert reg["derivedFrom"]["pendingReviews"] == ["E99-D99"]
    assert reg["findings"][0]["surface"] == "both"


def test_verdicts_reserved_unreachable_and_no_findings(tree: Path) -> None:
    by = {s["id"]: s for s in cat.build(tree)["screens"]}
    assert by["SCR-007"]["verdict"] == "n/a (reserved)"
    assert by["SCR-003"]["verdict"] == "findings"  # review row F-3 names it
    root_doc = json.loads((tree / cat.FINDINGS_REL).read_text(encoding="utf-8"))
    root_doc["screens"][2]["coverage"] = "unreachable: not built"
    (tree / "docs/design/review.md").write_text("# none\n", encoding="utf-8")
    (tree / cat.FINDINGS_REL).write_text(json.dumps(root_doc), encoding="utf-8")
    by = {s["id"]: s for s in cat.build(tree)["screens"]}
    assert by["SCR-003"]["verdict"] == "not auditable at sha"
    assert by["SCR-002"]["verdict"] == "no findings at sha"
    assert by["SCR-002"]["auditor"] and by["SCR-002"]["date"]


def test_routing_exactly_one_owner_and_reason(tree: Path) -> None:
    reg = cat.build(tree)
    assert cat.validate(reg, {f"E47-D{n:02d}" for n in range(3, 11)}) == []
    for f in reg["findings"]:
        assert f["designOwner"] == cat.ENGINEERING_ONLY or f["designOwner"].startswith(
            "E47-D"
        )
        assert f["ownerReason"]


def test_validate_rejects_missing_screen_empty_owner_and_bad_owner(tree: Path) -> None:
    reg = cat.build(tree)
    bad = copy.deepcopy(reg)
    del bad["screens"][5]
    assert any("SCR-006 appears 0 times" in p for p in cat.validate(bad))
    bad = copy.deepcopy(reg)
    bad["screens"].append(copy.deepcopy(bad["screens"][0]))
    assert any("SCR-001 appears 2 times" in p for p in cat.validate(bad))
    bad = copy.deepcopy(reg)
    bad["findings"][0]["designOwner"] = ""
    assert any("not D03..D10" in p for p in cat.validate(bad))
    bad = copy.deepcopy(reg)
    bad["findings"][0]["ownerReason"] = ""
    assert any("no reason" in p for p in cat.validate(bad))
    bad = copy.deepcopy(reg)
    bad["findings"][0]["designOwner"] = "E47-D03"
    assert any("does not resolve" in p for p in cat.validate(bad, {"E47-D04"}))
    bad = copy.deepcopy(reg)
    s = next(x for x in bad["screens"] if x["verdict"] == "n/a (reserved)")
    s["verdict"] = "no findings at sha"
    s["date"] = ""
    assert any("auditor and a date" in p for p in cat.validate(bad))
    bad = copy.deepcopy(reg)
    bad["findings"][0]["severity"] = "serious"
    assert any("outside the map" in p for p in cat.validate(bad))


def test_every_rule_owner_is_a_design_ticket_or_engineering_only() -> None:
    routing = json.loads((ROOT / cat.ROUTING_REL).read_text(encoding="utf-8"))
    for rule in [*routing["rules"], *routing["overrides"].values()]:
        assert (
            rule["owner"] == cat.ENGINEERING_ONLY or rule["owner"] in routing["owners"]
        )
        assert rule["reason"]


def test_render_is_idempotent_and_normalise_ignores_padding(tree: Path) -> None:
    reg = cat.build(tree)
    assert cat.render(reg) == cat.render(cat.build(tree))
    assert cat.normalise("| a   | b |\n| ----- | --- |\n") == cat.normalise(
        "| a | b |\n| - | ---- |\n"
    )


def test_check_mode_passes_then_fails_on_stale_and_missing(tree: Path) -> None:
    assert cat.main(["--root", str(tree)]) == 0
    assert cat.main(["--root", str(tree), "--check"]) == 0
    md = tree / cat.CATALOGUE_OUT_REL
    md.write_text(md.read_text(encoding="utf-8") + "\nstale edit\n", encoding="utf-8")
    assert cat.main(["--root", str(tree), "--check"]) == 1
    cat.main(["--root", str(tree)])
    reg = tree / cat.REGISTER_REL
    doc = json.loads(reg.read_text(encoding="utf-8"))
    doc["counts"]["findings"] = 99
    reg.write_text(json.dumps(doc), encoding="utf-8")
    assert cat.main(["--root", str(tree), "--check"]) == 1
    reg.unlink()
    assert cat.main(["--root", str(tree), "--check"]) == 1


def test_check_mode_fails_when_a_screen_is_missing_from_the_inputs(tree: Path) -> None:
    doc = json.loads((tree / cat.FINDINGS_REL).read_text(encoding="utf-8"))
    doc["screens"] = [s for s in doc["screens"] if s["id"] != "SCR-159"]
    (tree / cat.FINDINGS_REL).write_text(json.dumps(doc), encoding="utf-8")
    cat.main(["--root", str(tree)])
    # SCR-159 has no catalogue section and no T01 row: it must still be present, as reserved.
    reg = json.loads((tree / cat.REGISTER_REL).read_text(encoding="utf-8"))
    assert [s["id"] for s in reg["screens"]] == cat.SCR_IDS
    reg["screens"].pop()
    (tree / cat.REGISTER_REL).write_text(json.dumps(reg), encoding="utf-8")
    assert cat.main(["--root", str(tree), "--check"]) == 1


# ---- real inputs (committed register and merged reviews)


@pytest.mark.parametrize(
    ("path", "count"),
    [("docs/design/E09/E09-D10.md", 51), ("docs/design/E08/E08-D12.md", 8)],
)
def test_real_review_tables_parse_to_the_documented_count(
    path: str, count: int
) -> None:
    rows = cat.parse_review_table((ROOT / path).read_text(encoding="utf-8"))
    assert len(rows) == count
    ids = [r.get("f") or r.get("id") for r in rows]
    assert len(set(ids)) == count


def test_real_register_covers_every_screen_and_matches_the_committed_output() -> None:
    reg = cat.build(ROOT)
    assert [s["id"] for s in reg["screens"]] == cat.SCR_IDS
    assert cat.validate(reg, cat.e47_keys(ROOT)) == []
    assert sum(s["verdict"] == "n/a (reserved)" for s in reg["screens"]) == 10
    t01 = json.loads((ROOT / cat.FINDINGS_REL).read_text(encoding="utf-8"))
    mine = {f["id"] for f in reg["findings"] if f["source"] == "E47-T01 register"}
    assert mine == {f["id"] for f in t01["findings"]}
    assert all(
        re.fullmatch(r"A11Y-(F-\d{4}|R-[A-Z0-9]+-D\d+-F-\d+)", f["id"])
        for f in reg["findings"]
    )
    assert cat.main(["--check"]) == 0


def test_real_reserved_rows_are_the_unused_ids() -> None:
    reg = cat.build(ROOT)
    reserved = {s["id"] for s in reg["screens"] if s["verdict"] == "n/a (reserved)"}
    assert reserved == {
        "SCR-007", "SCR-008", "SCR-009", "SCR-105", "SCR-106",
        "SCR-107", "SCR-108", "SCR-109", "SCR-138", "SCR-139",
    }  # fmt: skip


def test_fixture_helper_copies_cleanly(tmp_path: Path) -> None:
    shutil.rmtree(make_tree(tmp_path / "x") / "docs")
