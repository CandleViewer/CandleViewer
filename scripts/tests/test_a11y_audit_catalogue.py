"""E47-D02 (#1301): the audit catalogue tool joins, maps, routes and gates correctly.

Stdlib + pytest only (the governance lane has no candleviewer package). Synthetic cases run on a
fixture tree under tmp_path; the real-input cases read the committed register and reviews.
"""

import copy
import importlib.util
import json
import re
import shutil
from collections import Counter
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

Not a table row. <!-- audit:f=3/1/0/1/1 -->
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
    real["attribution"] = {}
    real["citedReviews"] = []
    real["extraFindings"] = []
    real["vehicles"] = {}
    real["remedyNotes"] = {}
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
    assert s["SCR-001"]["canvasLayers"]["canvasRole"] == "mentioned in 14"
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
     ("blocker", "", "blocker"),
     ("serious", "this is task-blocking for keyboard", "major")],
)  # fmt: skip
def test_t01_severity_map(tmp_path: Path, sev: str, task: str, want: str) -> None:
    """T01 never yields a blocker from free text; only its own severity maps."""
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
    (tree / "docs/design/review.md").write_text(
        "# none\n<!-- audit:f=0/0/0/0/0 -->\n", encoding="utf-8"
    )
    (tree / cat.FINDINGS_REL).write_text(json.dumps(root_doc), encoding="utf-8")
    by = {s["id"]: s for s in cat.build(tree)["screens"]}
    assert by["SCR-003"]["verdict"] == "not auditable at sha"
    # the verdict follows the T01 coverage, never the sign-off ticks (SCR-002 has none ticked)
    assert by["SCR-002"]["signoff"]["checked"] == 0
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


def test_build_fails_when_a_screen_is_missing_from_the_t01_register(tree: Path) -> None:
    doc = json.loads((tree / cat.FINDINGS_REL).read_text(encoding="utf-8"))
    doc["screens"] = [s for s in doc["screens"] if s["id"] != "SCR-159"]
    (tree / cat.FINDINGS_REL).write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(cat.CatalogueError, match="screen set"):
        cat.build(tree)
    assert cat.main(["--root", str(tree), "--check"]) == 2


def test_build_fails_when_14_and_t01_disagree_on_reserved_ids(tree: Path) -> None:
    doc = json.loads((tree / cat.FINDINGS_REL).read_text(encoding="utf-8"))
    next(s for s in doc["screens"] if s["id"] == "SCR-159")["coverage"] = "covered"
    (tree / cat.FINDINGS_REL).write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(cat.CatalogueError, match="reserved ids"):
        cat.build(tree)
    doc = json.loads((tree / cat.FINDINGS_REL).read_text(encoding="utf-8"))
    next(s for s in doc["screens"] if s["id"] == "SCR-159")["coverage"] = "reserved: x"
    next(s for s in doc["screens"] if s["id"] == "SCR-002")["coverage"] = "reserved: x"
    (tree / cat.FINDINGS_REL).write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(cat.CatalogueError, match="reserved ids"):
        cat.build(tree)


def test_check_mode_fails_when_the_register_drops_a_screen(tree: Path) -> None:
    cat.main(["--root", str(tree)])
    reg = json.loads((tree / cat.REGISTER_REL).read_text(encoding="utf-8"))
    reg["screens"].pop()
    (tree / cat.REGISTER_REL).write_text(json.dumps(reg), encoding="utf-8")
    assert cat.main(["--root", str(tree), "--check"]) == 1


def test_malformed_table_rows_raise() -> None:
    short = REVIEW.replace(
        "| F-2  | contrast      | Minor    | 1.4.3               | no screen named here · fix it | E09-D03 |",
        "| F-2  | contrast |",
    )
    with pytest.raises(cat.CatalogueError, match="malformed"):
        cat.parse_review_table(short)
    bad_id = REVIEW.replace("| F-2  |", "| X-2  |")
    with pytest.raises(cat.CatalogueError, match="malformed"):
        cat.parse_review_table(bad_id)
    dup = REVIEW.replace("| F-3  |", "| F-2  |")
    with pytest.raises(cat.CatalogueError, match="duplicate"):
        cat.parse_review_table(dup)


def test_count_marker_mismatch_and_missing_marker_raise() -> None:
    smap = {"blocker": "blocker", "minor": "minor", "info": "info", "major": "major"}
    with pytest.raises(cat.CatalogueError, match="differ"):
        cat.review_findings("E00-D00", REVIEW.replace("=3/1/0/1/1", "=4/1/0/1/1"), smap)
    with pytest.raises(cat.CatalogueError, match="differ"):  # severity split off by one
        cat.review_findings("E00-D00", REVIEW.replace("=3/1/0/1/1", "=3/0/1/1/1"), smap)
    # a blank line inside the table truncates it: the count then disagrees
    trunc = REVIEW.replace("| F-2  |", "\n| F-2  |", 1)
    with pytest.raises(cat.CatalogueError, match="differ"):
        cat.review_findings("E00-D00", trunc, smap)
    with pytest.raises(cat.CatalogueError, match="no finding count marker"):
        cat.review_findings(
            "E00-D00", REVIEW.replace("<!-- audit:f=3/1/0/1/1 -->", ""), smap
        )
    e09 = REVIEW.replace(
        "<!-- audit:f=3/1/0/1/1 -->",
        "3<!--=COUNT:findings--> 1<!--=COUNT:findings.blocker--> 0<!--=COUNT:findings.major--> "
        "1<!--=COUNT:findings.minor--> 1<!--=COUNT:findings.info-->",
    )
    assert len(cat.review_findings("E00-D00", e09, smap)) == 3


def test_attribution_applies_only_without_row_text_screen(tmp_path: Path) -> None:
    smap = {"blocker": "blocker", "minor": "minor", "info": "info", "major": "major"}
    att = {
        "A11Y-R-E00-D00-F-1": {"screens": ["SCR-009"], "cite": "x"},
        "A11Y-R-E00-D00-F-2": {"screens": ["SCR-002"], "cite": "review §1 L2"},
    }
    got = cat.review_findings("E00-D00", REVIEW, smap, att)
    assert got[0]["screens"] == ["SCR-001"] and got[0]["screenSource"] == "row text"
    assert got[1]["screens"] == ["SCR-002"]
    assert got[1]["screenSource"].endswith("review §1 L2")
    root = make_tree(tmp_path, [])
    routing = json.loads((root / cat.ROUTING_REL).read_text(encoding="utf-8"))
    routing["attribution"] = {
        "A11Y-R-E00-D00-F-99": {"screens": ["SCR-002"], "cite": "x"}
    }
    (root / cat.ROUTING_REL).write_text(json.dumps(routing), encoding="utf-8")
    with pytest.raises(cat.CatalogueError, match="attribution"):
        cat.build(root)
    routing["attribution"] = {
        "A11Y-R-E00-D00-F-2": {"screens": ["SCR-002"], "cite": "c"}
    }
    (root / cat.ROUTING_REL).write_text(json.dumps(routing), encoding="utf-8")
    reg = cat.build(root)
    assert reg["unattributed"] == [] and reg["counts"]["attributedByRouting"] == 1


# ---- real inputs (committed register and merged reviews)


@pytest.mark.parametrize(
    ("path", "count"),
    [
        ("docs/design/E09/E09-D10.md", 51),
        ("docs/design/E08/E08-D12.md", 8),
        ("docs/design/E32/E32-D07-a11y.md", 11),
        ("docs/design/E12/E12-D11.md", 9),
        ("docs/design/E14/E14-D10.md", 17),
    ],
)
def test_real_review_tables_parse_to_the_documented_count(
    path: str, count: int
) -> None:
    rows = cat.parse_review_table((ROOT / path).read_text(encoding="utf-8"))
    assert len(rows) == count
    assert (
        cat.expected_counts(path, (ROOT / path).read_text(encoding="utf-8"))["total"]
        == count
    )
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
        re.fullmatch(r"A11Y-(F-\d{4}|R-[A-Z0-9]+-D\d+-F-\d+|D02-T2-SCR-\d{3})", f["id"])
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


def test_real_attribution_leaves_only_the_unmapped_finding_and_no_blocker() -> None:
    reg = cat.build(ROOT)
    assert sorted(f["id"] for f in reg["unattributed"]) == [
        "A11Y-R-E09-D10-F-48",
        "A11Y-R-E12-D11-F-07",
        "A11Y-R-E12-D11-F-08",
        "A11Y-R-E14-D10-F-12",
        "A11Y-R-E14-D10-F-14",
        "A11Y-R-E14-D10-F-15",
        "A11Y-R-E14-D10-F-16",
    ]
    assert reg["counts"]["unattributedBlockers"] == 0
    assert reg["counts"]["bySeverity"]["blocker"] == 4  # E09-D10's four Blockers
    routing = json.loads((ROOT / cat.ROUTING_REL).read_text(encoding="utf-8"))
    assert all(a["cite"] and a["screens"] for a in routing["attribution"].values())


def test_verdict_for_follows_coverage_and_live_findings() -> None:
    assert cat.verdict_for("covered", 0)[0] == "no findings at sha"
    assert cat.verdict_for("partial", 0)[1].startswith("partial coverage")
    assert cat.verdict_for("covered", 2)[0] == "findings"
    assert cat.verdict_for("unreachable: not built", 0)[0] == "not auditable at sha"
    # fixed rows are not live: all-fixed is a clean screen that still names the fixes
    v, why = cat.verdict_for("covered", 0, 3)
    assert v == "no findings at sha" and "3 T01 finding(s) fixed" in why


def test_render_carries_the_three_lens_notes(tree: Path) -> None:
    md = cat.render(cat.build(tree))
    assert "Multi-screen findings are counted on each screen" in md
    assert "Canvas four-layer verification, and the missing-layer blocker rule" in md
    assert "static, text pass" not in md
    assert "never on the design sign-off ticks" in md


def test_fixed_t01_rows_are_not_live_and_status_is_carried(tmp_path: Path) -> None:
    fixed = _t01_finding("A11Y-F-0001", "SCR-001", "serious", status="fixed")
    open_ = _t01_finding("A11Y-F-0002", "SCR-002", "serious", status="open")
    reg = cat.build(make_tree(tmp_path, [fixed, open_]))
    by = {f["id"]: f for f in reg["findings"]}
    assert (
        by["A11Y-F-0001"]["status"] == "fixed" and by["A11Y-F-0002"]["status"] == "open"
    )
    assert reg["counts"]["fixed"] == 1
    s1 = next(s for s in reg["screens"] if s["id"] == "SCR-001")
    assert "A11Y-F-0001" in s1["findings"]
    assert "A11Y-R-E00-D00-F-1" in s1["findings"]  # the review row stays open
    md = cat.render(reg)
    assert "| fixed |" in md
    assert reg["counts"]["bySeverity"]["major"] == 1  # only the open serious row


def test_levels_and_sc_reasons_are_derived_or_explained() -> None:
    assert cat.levels_for(["4.1.2", "1.4.3"]) == "A / AA"
    assert cat.levels_for(["9.9.9"]) is None
    f = {"sc": [], "level": None, "clause": "6.5", "class": "copy"}
    assert "`05` clause 6.5" in cat.sc_reason(f)
    assert cat.sc_reason(
        {"sc": [], "level": None, "clause": "", "class": "copy"}
    ).startswith("class copy")
    assert cat.sc_reason({"sc": ["1.4.3"], "level": "AA"}) == ""


def test_review_severity_suffix_and_wcag_column_and_screen_column() -> None:
    text = """| Id | Sev (p) | Screen | WCAG | Merged sentence (cite) | Replacement | Owner; target |
| -- | -- | -- | -- | -- | -- | -- |
| F-01 | Minor (p2) | SCR-065 | 1.3.1; 4.1.2 | names SCR-063 too | fix | E32-D04; S06 |
| F-02 | Info (p3) | all three | 2.1.1 | x | none | Q07 |

<!--=COUNT:f.total-->2<!--=COUNT:f.blocking-->0<!--=COUNT:f.major-->0<!--=COUNT:f.minor-->1<!--=COUNT:f.info-->
"""
    text = (
        "2<!--=COUNT:f.total--> 0<!--=COUNT:f.blocking--> 0<!--=COUNT:f.major--> "
        "1<!--=COUNT:f.minor--> 1<!--=COUNT:f.info-->\n" + text
    )
    smap = {"minor": "minor", "info": "info", "major": "major", "blocker": "blocker"}
    got = cat.review_findings("E00-D01", text, smap)
    assert got[0]["screens"] == [
        "SCR-065"
    ]  # the Screen column only, not SCR-063 in prose
    assert got[0]["sc"] == ["1.3.1", "4.1.2"] and got[0]["sourceSeverity"] == "Minor"
    assert got[0]["remediation"] == "E32-D04; S06"
    assert got[1]["screens"] == []  # "all three" needs a routing attribution


def test_cited_review_counts_come_from_its_own_table(tmp_path: Path) -> None:
    (tmp_path / "r.md").write_text(
        "# E00-D09 \u2014 A review of things\n\n**Ticket:** E00-D09 (#77)\n\n"
        "| F | Severity | Clause |\n| - | - | - |\n"
        "| F-01 | Blocking | 1 |\n| F-02 | Major | 2 |\n| F-03 | Minor | 3 |\n",
        encoding="utf-8",
    )
    got = cat.cited_review(tmp_path, {"key": "E00-D09", "path": "r.md"})
    assert got and got["issue"] == "77" and got["scope"] == "A review of things"
    assert (got["total"], got["blocker"], got["major"], got["minor"], got["info"]) == (
        3,
        1,
        1,
        1,
        0,
    )
    assert cat.cited_review(tmp_path, {"key": "x", "path": "missing.md"}) is None


def test_real_cited_reviews_and_e32_d07_are_in_the_register() -> None:
    reg = cat.build(ROOT)
    keys = {c["key"] for c in reg["derivedFrom"]["citedReviews"]}
    assert keys >= {
        "E15-D15",
        "E16-D06",
        "E22-D04",
        "E29-D05",
        "E30-D05",
        "E33-D05",
        "E35-D04",
    }
    assert reg["derivedFrom"]["pendingReviews"] == []
    assert {"E32-D07", "E12-D11", "E14-D10"} <= set(reg["derivedFrom"]["reviews"])
    assert not {"E12-D11", "E14-D10"} & keys  # joined row by row, no longer only cited
    e15 = next(c for c in reg["derivedFrom"]["citedReviews"] if c["key"] == "E15-D15")
    assert (e15["total"], e15["blocker"]) == (
        12,
        3,
    )  # its Blocking rows are never hidden
    assert "E15-D15 (#369)" in cat.render(reg)


def test_real_blockers_name_the_fix_vehicle_and_held_review() -> None:
    reg = cat.build(ROOT)
    blockers = [f for f in reg["findings"] if f["severity"] == "blocker"]
    assert len(blockers) == 4
    for f in blockers:
        assert "#5254" in f["vehicle"] and "#193" in f["vehicle"]


def test_real_g_t2_rows_and_f32_note() -> None:
    reg = cat.build(ROOT)
    by = {f["id"]: f for f in reg["findings"]}
    note = by["A11Y-R-E09-D10-F-32"]["remedyNote"]
    for token in ("CMP-079", "CMP-019", "lock", "reason node", "rbac.read_only"):
        assert token in note
    for scr in ("SCR-001", "SCR-112"):
        row = by[f"A11Y-D02-T2-{scr}"]
        assert row["screens"] == [scr] and "CMP-079" in row["title"]


def test_real_routing_reasons_and_levels() -> None:
    reg = cat.build(ROOT)
    for f in reg["findings"]:
        if f["designOwner"] == cat.ENGINEERING_ONLY:
            assert "no override gives it a reason" not in f["ownerReason"], f["id"]
        assert f["level"] or not f["sc"] or f["scReason"], f["id"]
        assert f["sc"] or f["scReason"], f["id"]


def test_canvas_text_routes_to_e47_d06() -> None:
    routing = json.loads((ROOT / cat.ROUTING_REL).read_text(encoding="utf-8"))
    f = {"id": "x", "screens": ["SCR-030"], "sc": [], "class": None, "pattern": None,
         "title": "the canvas has no DOM mirror", "remedy": ""}  # fmt: skip
    assert cat.route(f, routing)[0] == "E47-D06"


def test_check_pins_14_and_findings_so_main_drift_is_a_warning(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cat.main(["--root", str(tree)]) == 0
    reg = json.loads((tree / cat.REGISTER_REL).read_text(encoding="utf-8"))
    pins = reg["derivedFrom"]["inputs"]
    assert set(pins) == {cat.CATALOGUE_REL, cat.FINDINGS_REL}
    old14 = (tree / cat.CATALOGUE_REL).read_text(encoding="utf-8")
    by_blob = {cat.blob_sha(old14.encode()): old14}
    monkeypatch.setattr(cat, "git_show", lambda _root, blob: by_blob.get(blob))
    # another lane ticks a sign-off in 14: pending WARN, still exit 0
    (tree / cat.CATALOGUE_REL).write_text(
        old14.replace("[ ] two", "[x] two"), encoding="utf-8"
    )
    assert cat.main(["--root", str(tree), "--check"]) == 0
    assert "WARN pending" in capsys.readouterr().err
    # but a stale committed output is still a failure against the pinned base
    md = tree / cat.CATALOGUE_OUT_REL
    md.write_text(md.read_text(encoding="utf-8") + "\nstale edit\n", encoding="utf-8")
    assert cat.main(["--root", str(tree), "--check"]) == 1


def test_check_without_the_pinned_blob_checks_consistency_only(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cat.main(["--root", str(tree)])
    monkeypatch.setattr(cat, "git_show", lambda _root, _blob: None)
    p = tree / cat.CATALOGUE_REL
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert cat.main(["--root", str(tree), "--check"]) == 0
    assert "not in this checkout" in capsys.readouterr().err
    md = tree / cat.CATALOGUE_OUT_REL
    md.write_text(md.read_text(encoding="utf-8") + "\nstale edit\n", encoding="utf-8")
    assert cat.main(["--root", str(tree), "--check"]) == 1


def test_e12_and_e14_reviews_are_joined_row_by_row() -> None:
    reg = cat.build(ROOT)
    src = Counter(f["source"] for f in reg["findings"])
    assert (src["review E12-D11"], src["review E14-D10"]) == (7, 13)
    # the rows no review screen mapping covers stay listed, never dropped
    assert {f["id"] for f in reg["unattributed"]} >= {
        "A11Y-R-E12-D11-F-07",
        "A11Y-R-E14-D10-F-12",
    }
    for f in reg["findings"]:
        if f["source"] in ("review E12-D11", "review E14-D10"):
            assert f["screens"] and f["designOwner"]


def test_audit_count_markers_without_a_slash_form_are_read() -> None:
    text = (
        "F 3 <!-- audit:f=3 --> <!-- audit:f.blocking=1 --> <!-- audit:f.major=0 -->"
        " <!-- audit:f.minor=1 --> <!-- audit:f.info=1 -->"
    )
    assert cat.expected_counts("X", text) == {
        "total": 3, "blocker": 1, "major": 0, "minor": 1, "info": 1,
    }  # fmt: skip


def test_status_overrides_flip_open_rows_and_drop_out_when_the_register_says_fixed() -> (
    None
):
    sha = "9684b740138f8ec163884fb2b6644834e12782a8"
    routing = {
        "statusOverrides": {"A11Y-F-1": {"status": "fixed", "sha": sha, "pr": 5214}}
    }
    f = {"id": "A11Y-F-1", "status": "open"}
    assert cat.status_for(f, routing) == f"fixed (#5214, {sha[:12]})"
    assert cat.status_for({"id": "A11Y-F-1", "status": "fixed"}, routing) == "fixed"
    assert cat.status_for({"id": "A11Y-F-2", "status": "open"}, routing) == "open"
    bad = {"statusOverrides": {"A11Y-F-1": {"status": "fixed", "sha": "abc", "pr": 1}}}
    with pytest.raises(cat.CatalogueError):
        cat.status_for(f, bad)


def test_real_status_overrides_name_register_findings_with_a_full_sha() -> None:
    routing = json.loads((ROOT / cat.ROUTING_REL).read_text(encoding="utf-8"))
    register = json.loads(
        (ROOT / "docs/plan/a11y/findings.json").read_text(encoding="utf-8")
    )
    ids = {f["id"] for f in register["findings"]}
    assert len(routing["statusOverrides"]) == 9
    for fid, ov in routing["statusOverrides"].items():
        assert fid in ids and re.fullmatch(r"[0-9a-f]{40}", ov["sha"])


def test_real_nine_level_a_rows_are_fixed_by_the_override() -> None:
    reg = cat.build(ROOT)
    by = {f["id"]: f for f in reg["findings"]}
    ids = [f"A11Y-F-{n:04d}" for n in (3, 6, 10, 11, 12, 25, 26, 27, 28)]
    for i in ids:
        # "fixed (#52…, sha)" while the override carries it; plain "fixed" once the register does
        assert by[i]["status"] == "fixed" or by[i]["status"].startswith("fixed (#52"), i
    counts = reg["counts"]
    assert counts["fixed"] >= 13 and counts["fixed"] + counts["open"] == 121


def test_real_md_carries_the_sweep_carry_and_the_ci_correction() -> None:
    md = cat.render(cat.build(ROOT))
    assert "kappa 0.61 (n = 96" in md
    assert "does run in CI, in the `governance` lane" in md
    assert "#5254" in md and "#193" in md
