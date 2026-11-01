"""E49-Q01 (#1335): tools/ga/shard_plan.py (duration-balanced shards, the 45-minute budget) and
tools/ga/coverage_map.py (Must stories to pack scenarios, declared gaps, the generated map)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ga import coverage_map, shard_plan, specs, surfaces

# --- shard_plan -----------------------------------------------------------------------------


def test_plan_is_longest_first_to_the_lightest_shard() -> None:
    seconds = {"a": 50, "b": 40, "c": 30, "d": 20, "e": 10}
    assert shard_plan.plan(list(seconds), seconds, 2) == [["a", "d", "e"], ["b", "c"]]


def test_plan_places_every_file_once_and_is_independent_of_input_order() -> None:
    files = [f"f{i}.spec.ts" for i in range(23)]
    seconds = {f: float((i * 7) % 11 + 1) for i, f in enumerate(files)}
    a = shard_plan.plan(files, seconds, 4)
    b = shard_plan.plan(list(reversed(files)) + files[:3], seconds, 4)
    assert a == b
    assert sorted(f for s in a for f in s) == sorted(files)
    loads = [shard_plan.shard_seconds(s, seconds) for s in a]
    assert max(loads) - min(loads) <= max(seconds.values())  # LPT's bound


def test_plan_charges_an_unmeasured_file_the_default_so_it_still_lands() -> None:
    shards = shard_plan.plan(["new.spec.ts", "old.spec.ts"], {"old.spec.ts": 1.0}, 2)
    assert shards == [["new.spec.ts"], ["old.spec.ts"]]
    assert shard_plan.shard_seconds(["new.spec.ts"], {}) == shard_plan.DEFAULT_SECONDS


def test_plan_rejects_zero_shards_and_leaves_extra_shards_empty() -> None:
    with pytest.raises(ValueError):
        shard_plan.plan(["a"], {}, 0)
    assert shard_plan.plan(["a"], {}, 3) == [["a"], [], []]


def test_budget_holds_the_heaviest_shard_plus_setup_to_45_minutes() -> None:
    assert shard_plan.BUDGET_SECONDS == 2700
    setup = shard_plan.SETUP_SECONDS
    fits = {"web-chromium": [["a"], ["b"]]}
    durations = {"web-chromium": {"a": 2700 - setup, "b": 10.0}}
    assert shard_plan.budget_findings(fits, durations) == []
    durations["web-chromium"]["a"] += 1
    (finding,) = shard_plan.budget_findings(fits, durations)
    assert finding.startswith("web-chromium: heaviest shard") and "2700 s budget" in finding


def test_the_repository_plan_fits_the_budget_and_covers_every_pack_file() -> None:
    plans, durations = shard_plan.all_plans(ROOT)
    assert shard_plan.budget_findings(plans, durations) == []
    tests = specs.scan(ROOT)
    for lane, shards in plans.items():
        assert len(shards) == shard_plan.SHARDS[lane]
        assert sorted(f for s in shards for f in s) == specs.pack_files(tests, lane)


def test_durations_table_names_only_existing_spec_files() -> None:
    for lane, table in shard_plan.load_durations().items():
        for rel in table:
            assert (ROOT / specs.APPS[lane] / rel).is_file(), f"{lane}: {rel}"


def test_cli_prints_one_shard_and_checks_the_budget(capsys: pytest.CaptureFixture[str]) -> None:
    assert shard_plan.main(["web-chromium", "1", "4"]) == 0
    printed = capsys.readouterr().out.split()
    assert printed and all(p.startswith("e2e/") and p.endswith(".spec.ts") for p in printed)
    assert shard_plan.main(["--check"]) == 0
    assert "web-chromium:" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        shard_plan.main(["web-chromium", "5", "4"])


# --- coverage_map ---------------------------------------------------------------------------

STORIES = """# stories
#### US-ONB-001 — Password sign-in · Must
#### US-ONB-002 — TOTP · Must/Should
#### US-ONB-003 — Later · Should
#### US-ORD-001 — Order ticket · Must
"""


MATRIX = """| Story | Pri | Screens |
|---|---|---|
| **US-ORD-001** Order ticket | Must | SCR-060 |
| **US-SET-005** Colours | Must | SCR-116 |

| Screen | Name | Route |
|---|---|---|
| **SCR-060** | Order ticket | _(hosted)_ |
| **SCR-071** | Risk | R-150 |
| **SCR-116** | Appearance | _(hosted)_ |
"""
TREE = """function elementFor(routeId: string, owner: string | null) {
  if (routeId === "R-203") return <AppearanceScreen />;
  if (routeId === "R-101") {
    return <StubRoute routeId={routeId} owner={owner} />;
  }
  if (owner === null) return <PlaceholderRoute />;
  return <StubRoute routeId={routeId} owner={owner} />;
}
"""


def _root(tmp_path: Path, gaps: list[dict[str, Any]]) -> Path:
    (tmp_path / "docs/plan").mkdir(parents=True)
    (tmp_path / "docs/qa").mkdir(parents=True)
    (tmp_path / "docs/plan/11-user-stories.md").write_text(STORIES, encoding="utf-8")
    (tmp_path / surfaces.MATRIX).write_text(MATRIX, encoding="utf-8")
    _src(tmp_path, surfaces.TREE, TREE)
    (tmp_path / coverage_map.GAPS).write_text(json.dumps({"gaps": gaps}), encoding="utf-8")
    return tmp_path


def _src(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


def _gap(story: str, **extra: Any) -> dict[str, Any]:
    return {
        "story": story,
        "owner_epic": "E30",
        "surface": {"kind": "unbuilt"},
        "risk_acceptance_ref": "PROPOSED: owner acceptance pending",
    } | extra


def _t(
    tags: str, modifier: str | None = None, path: str = "apps/web/e2e/a.spec.ts"
) -> specs.SpecTest:
    return specs.SpecTest("web-chromium", path, 1, tuple(tags.split()), modifier)


COVERING = [_t("@ga-regression @ga-area-primary @story-US-ONB-001 @story-US-ONB-002")]


def _check(root: Path, tests: list[specs.SpecTest]) -> list[str]:
    (root / coverage_map.MAP).write_text(
        coverage_map.render(root, tests, coverage_map.load_gaps(root)), encoding="utf-8"
    )
    return coverage_map.check(root, tests)


def test_every_must_story_covered_or_declared_passes(tmp_path: Path) -> None:
    root = _root(tmp_path, [_gap("US-ORD-001")])
    assert _check(root, COVERING) == []
    text = (root / coverage_map.MAP).read_text(encoding="utf-8")
    assert "Must stories: 3. Covered by a runnable pack scenario: 2. Declared gaps: 1" in text
    assert "of which 1 are **pending owner acceptance** and 0 accepted" in text
    assert (
        "| US-ORD-001 | Order ticket | gap, pending owner acceptance | Not built: no source"
        " implements SCR-060; joins when E30 ships it.;" in text
    )
    assert coverage_map.pending(root) == ["US-ORD-001"]


def test_an_accepted_gap_is_not_pending(tmp_path: Path) -> None:
    root = _root(tmp_path, [_gap("US-ORD-001", risk_acceptance_ref="#9999 owner, 2026-11-02")])
    assert _check(root, COVERING) == [] and coverage_map.pending(root) == []
    assert "| US-ORD-001 | Order ticket | gap | Not built" in (root / coverage_map.MAP).read_text(
        encoding="utf-8"
    )


def test_an_undeclared_must_story_fails(tmp_path: Path) -> None:
    root = _root(tmp_path, [])
    assert _check(root, COVERING) == [
        "US-ORD-001: Must story neither covered by the pack nor a declared gap"
    ]


def test_a_fixme_stub_or_a_non_pack_test_covers_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path, [_gap("US-ORD-001")])
    tests = [
        _t("@ga-regression @ga-area-primary @story-US-ONB-001", "fixme"),
        _t("@story-US-ONB-002"),
    ]
    found = _check(root, tests)
    assert {f.split(":")[0] for f in found} == {"US-ONB-001", "US-ONB-002"}


@pytest.mark.parametrize(
    ("gap", "needle"),
    [
        (_gap("US-ONB-001"), "is covered by the pack; delete its gap entry"),
        (_gap("US-ONB-003"), "is not a Must story"),
        (_gap("US-ORD-001", surface=""), "lacks surface"),
        (_gap("US-ORD-001", surface={"kind": "maybe"}), "surface.kind"),
        (_gap("US-ORD-001", risk_acceptance_ref=" "), "lacks risk_acceptance_ref"),
        (_gap("US-ORD-001", stub="apps/web/e2e/ga/carried.spec.ts"), "has no fixme pack test"),
    ],
)
def test_bad_gap_entries_fail(tmp_path: Path, gap: dict[str, Any], needle: str) -> None:
    gaps = [gap] if gap["story"] == "US-ORD-001" else [gap, _gap("US-ORD-001")]
    found = _check(_root(tmp_path, gaps), COVERING)
    assert len(found) == 1 and needle in found[0], found


def test_a_gap_declared_twice_fails(tmp_path: Path) -> None:
    found = _check(_root(tmp_path, [_gap("US-ORD-001"), _gap("US-ORD-001")]), COVERING)
    assert found == [f"{coverage_map.GAPS}: US-ORD-001 is declared twice"]


def test_a_named_stub_that_holds_the_story_passes(tmp_path: Path) -> None:
    stub = "apps/web/e2e/ga/carried.spec.ts"
    root = _root(tmp_path, [_gap("US-ORD-001", stub=stub)])
    tests = [*COVERING, _t("@ga-regression @ga-area-primary @story-US-ORD-001", "fixme", stub)]
    assert _check(root, tests) == []


def test_a_stale_map_fails_and_write_regenerates_it(tmp_path: Path) -> None:
    root = _root(tmp_path, [_gap("US-ORD-001")])
    _check(root, COVERING)
    (root / coverage_map.MAP).write_text("edited by hand\n", encoding="utf-8")
    assert coverage_map.check(root, COVERING)[-1].endswith("coverage_map.py --write")


def test_an_unreadable_gaps_file_is_one_finding(tmp_path: Path) -> None:
    root = _root(tmp_path, [])
    (root / coverage_map.GAPS).write_text(json.dumps({"gaps": {}}), encoding="utf-8")
    (finding,) = coverage_map.check(root, COVERING)
    assert "unreadable" in finding


def test_the_repository_map_is_current_and_complete() -> None:
    assert coverage_map.check(ROOT) == []
    assert coverage_map.main(["--root", str(ROOT)]) == 0


def test_the_ticket_named_flows_are_declared_gaps_with_stubs() -> None:
    gaps = {g["story"]: g for g in coverage_map.load_gaps(ROOT)}
    for story in ("US-ORD-001", "US-ORD-013", "US-ALGO-001", "US-RULE-006", "US-RPL-004"):
        assert gaps[story]["stub"] == "apps/web/e2e/ga/carried.spec.ts"
    assert gaps["US-LAY-005"]["stub"] == "apps/desktop/e2e/ga-carried.spec.ts"


# --- durations, file filters ---------------------------------------------------------------


def test_a_durations_key_naming_no_pack_file_is_stale() -> None:
    files = {"web-chromium": ["e2e/a.spec.ts"], "electron": []}
    durations = {"web-chromium": {"e2e/a.spec.ts": 3.0, "e2e/gone.spec.ts": 9.0}, "electron": {}}
    (found,) = shard_plan.duration_findings(files, durations)
    assert "e2e/gone.spec.ts" in found and "web-chromium" in found
    notes = shard_plan.duration_notes({"electron": ["e2e/x.spec.ts"]}, {"electron": {}})
    assert notes == [
        "electron: 1 of 1 pack files have no measured seconds; the planned budget counts 30 s"
        " each (provisional until a nightly's ga-durations artefact is committed)"
    ]


def test_a_file_filter_matching_another_pack_path_is_a_finding() -> None:
    assert shard_plan.filter_overlaps(["e2e/a.spec.ts", "e2e/b.spec.ts"]) == []
    (found,) = shard_plan.filter_overlaps(["e2e/login.spec.ts", "e2e/auth/e2e/login.spec.ts"])
    assert found.startswith("shard file filter e2e/login.spec.ts also matches")
    # "." is a wildcard in Playwright's filter: x.spec.ts also selects xyspec.ts.
    assert shard_plan.filter_overlaps(["e2e/x.spec.ts", "e2e/x_spec.ts"])


def test_the_repository_durations_and_filters_are_clean() -> None:
    tests = specs.scan(ROOT)
    files = {lane: specs.pack_files(tests, lane) for lane in specs.APPS}
    assert shard_plan.duration_findings(files, shard_plan.load_durations()) == []
    for lane_files in files.values():
        assert shard_plan.filter_overlaps(lane_files) == []


# --- surfaces: a gap's reason is checked against the code ---------------------------------


def _code_root(tmp_path: Path) -> Path:
    root = _root(tmp_path, [])
    _src(root, "apps/web/src/main.tsx", 'import { App } from "./App";\n')
    _src(root, "apps/web/src/App.tsx", 'import { AppearanceScreen } from "./features/ap/Screen";\n')
    _src(root, "apps/web/src/features/ap/Screen.tsx", "/** SCR-116 palette. */\n")
    _src(root, "apps/web/src/features/ticket/Ticket.tsx", "/** SCR-060 order ticket. */\n")
    _src(root, "apps/web/src/features/ticket/Ticket.test.tsx", "// SCR-116 in a test\n")
    return root


def _surface_findings(root: Path, story: str, surface: dict[str, Any]) -> list[str]:
    return surfaces.findings(_gap(story, surface=surface), surfaces.Code(root))


def test_code_reads_screens_routes_mounts_and_citations(tmp_path: Path) -> None:
    code = surfaces.Code(_code_root(tmp_path))
    assert code.story_screens["US-ORD-001"] == ["SCR-060"]
    assert code.screen_routes["SCR-071"] == ["R-150"]
    assert code.real_routes == {"R-203"}  # R-101 renders a stub inside its block
    assert code.mounted == {
        "apps/web/src/main.tsx",
        "apps/web/src/App.tsx",
        "apps/web/src/features/ap/Screen.tsx",
    }
    assert code.citing["SCR-116"] == ["apps/web/src/features/ap/Screen.tsx"]  # tests excluded


def test_a_shipped_surface_cannot_be_declared_unbuilt(tmp_path: Path) -> None:
    root = _code_root(tmp_path)
    (found,) = _surface_findings(root, "US-SET-005", {"kind": "unbuilt"})
    assert "features/ap/Screen.tsx cites SCR-116, so it is built" in found
    assert _surface_findings(root, "US-SET-005", {"kind": "shipped", "where": "R-203"}) == []
    assert (
        _surface_findings(
            root, "US-SET-005", {"kind": "shipped", "where": "apps/web/src/features/ap/Screen.tsx"}
        )
        == []
    )
    (stub,) = _surface_findings(root, "US-SET-005", {"kind": "shipped", "where": "R-101"})
    assert "R-101 is not in the build" in stub


def test_built_but_unmounted_code_is_unmounted_not_unbuilt(tmp_path: Path) -> None:
    root = _code_root(tmp_path)
    module = "apps/web/src/features/ticket"
    assert _surface_findings(root, "US-ORD-001", {"kind": "unbuilt"})  # it cites SCR-060
    assert _surface_findings(root, "US-ORD-001", {"kind": "unmounted", "module": module}) == []
    _src(root, "apps/web/src/App.tsx", 'import { Ticket } from "./features/ticket/Ticket.js";\n')
    found = _surface_findings(root, "US-ORD-001", {"kind": "unmounted", "module": module})
    assert any("is mounted by the app" in f for f in found)
    entry = {"kind": "unmounted", "module": module, "entry": "openTicket"}
    assert _surface_findings(root, "US-ORD-001", entry) == []
    _src(root, "apps/web/src/Shell.tsx", "openTicket();\n")
    assert any("references openTicket" in f for f in _surface_findings(root, "US-ORD-001", entry))


def test_incidental_screens_need_a_reason_and_must_be_the_storys(tmp_path: Path) -> None:
    root = _code_root(tmp_path)
    ok = {"kind": "unbuilt", "incidental": {"SCR-060": "a comment names it"}}
    assert _surface_findings(root, "US-ORD-001", ok) == []
    bad = {"kind": "unbuilt", "incidental": {"SCR-060": " ", "SCR-999": "x"}}
    found = _surface_findings(root, "US-ORD-001", bad)
    assert any("SCR-999 is not one of its screens" in f for f in found)
    assert any("SCR-060 gives no reason" in f for f in found)


def test_partial_below_e2e_and_unknown_stories(tmp_path: Path) -> None:
    root = _code_root(tmp_path)
    partial = {"kind": "partial", "shipped": ["R-203"]}
    assert any("needs a `note`" in f for f in _surface_findings(root, "US-SET-005", partial))
    below = {"kind": "below-e2e", "verified_by": ["docs/plan/11-user-stories.md", "nope.py"]}
    assert _surface_findings(root, "US-ORD-001", below) == [
        "US-ORD-001: verified_by nope.py does not exist"
    ]
    assert _surface_findings(root, "US-ORD-001", {"kind": "below-e2e"})
    (none,) = _surface_findings(root, "US-ONB-001", {"kind": "unbuilt"})
    assert "no row in docs/plan/18-traceability-matrix.md" in none


def test_reasons_are_rendered_from_the_surface(tmp_path: Path) -> None:
    code = surfaces.Code(_code_root(tmp_path))

    def reason(story: str, surface: dict[str, Any]) -> str:
        return surfaces.reason(_gap(story, surface=surface), code)

    assert reason("US-ORD-001", {"kind": "unmounted", "module": "m", "entry": "e"}).startswith(
        "Built, not mounted: `m` exists but nothing outside it calls `e` (SCR-060)"
    )
    assert reason("US-SET-005", {"kind": "shipped", "where": "R-203"}) == (
        "Shipped at R-203; spec not yet written - E30 (a person is assigned at claim)."
    )
    assert "verified below E2E by `t.py`" in reason(
        "US-ORD-001", {"kind": "below-e2e", "verified_by": ["t.py"]}
    )


def test_the_repository_gaps_name_the_built_surfaces_the_qa_lens_found() -> None:
    gaps = {g["story"]: g["surface"] for g in coverage_map.load_gaps(ROOT)}
    # Built in apps/web/src/features but mounted by nothing: not "not shipped".
    assert gaps["US-MKT-002"]["kind"] == "unmounted"  # symbol-search, no opener bound
    assert gaps["US-CHART-007"]["kind"] == "unmounted"  # chart-price-scale
    assert gaps["US-ALRT-001"]["kind"] == "unmounted"  # alerts store, no UI
    # Shipped (R-203) and now covered by pack specs: no longer gaps.
    assert "US-SET-005" not in gaps and "US-SET-007" not in gaps
    # Every "verified below E2E" row cites test paths that exist (checked by surfaces.findings).
    below = [s for s, v in gaps.items() if v["kind"] == "below-e2e"]
    assert below and all(gaps[s]["verified_by"] for s in below)
    # The shipped SCR-116 screen cannot be declared unbuilt against the real code.
    code = surfaces.Code(ROOT)
    assert surfaces.findings(_gap("US-SET-005", surface={"kind": "unbuilt"}), code)
