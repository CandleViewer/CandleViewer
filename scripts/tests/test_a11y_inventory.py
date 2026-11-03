"""Meta-tests for tools/a11y/inventory.py and gate A11Y-G008 (E47-Q04): injected defect fails, clean passes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.a11y import gates, inventory

ROOT = Path(__file__).resolve().parents[2]


def _rows(*specs: tuple[str, str, str]) -> list[inventory.Row]:
    """(id, status, route) rows; an empty route means a hosted screen."""
    return [
        inventory.Row(i, f"name {i}", st, "E99-S01 #1", (rt,) if rt else ()) for i, st, rt in specs
    ]


PR = frozenset({"R-001", "R-201"})


def test_missing_mounted_screen_fails_naming_screen_and_route() -> None:
    rows = _rows(("SCR-001", "mounted", "R-001"), ("SCR-112", "mounted", "R-201"))
    msgs = inventory.check_inventory({"screens": {"R-001": {}}}, rows, PR)
    assert len(msgs) == 1
    assert "A11Y-G008" in msgs[0] and "SCR-112" in msgs[0] and "R-201" in msgs[0]


def test_present_mounted_screen_passes_by_route_or_screen_id() -> None:
    rows = _rows(("SCR-001", "mounted", "R-001"), ("SCR-112", "mounted", "R-201"))
    assert inventory.check_inventory({"screens": {"R-001": {}, "SCR-112": {}}}, rows, PR) == []


def test_pending_row_passes_even_when_absent() -> None:
    rows = _rows(("SCR-060", "pending", ""), ("SCR-001", "mounted", "R-001"))
    assert inventory.check_inventory({"screens": {"R-001": {}}}, rows, PR) == []


def test_hosted_and_reserved_rows_are_not_failed() -> None:
    rows = _rows(("SCR-005", "mounted", ""), ("SCR-007", "reserved", ""))
    assert inventory.check_inventory({"screens": {}}, rows, PR) == []


def test_nightly_only_route_is_required_only_in_the_full_tier() -> None:
    rows = _rows(("SCR-004", "mounted", "R-007"))
    assert inventory.check_inventory({"screens": {}}, rows, PR, "pr") == []
    assert "SCR-004" in inventory.check_inventory({"screens": {}}, rows, PR, "full")[0]


def test_report_without_screens_object_is_an_error() -> None:
    with pytest.raises(inventory.InventoryError):
        inventory.check_inventory({}, [], PR)


def test_real_inventory_parses_and_counts_every_non_reserved_row() -> None:
    manifest = inventory.load_manifest()
    rows = inventory.load_rows(manifest=manifest)
    c = inventory.summary(rows)
    assert len(rows) == 159
    assert c["rows"] + c["reserved"] == 159 and c["mounted"] + c["pending"] == c["rows"]
    assert c["mounted"] > 0 and c["pending"] > 0
    assert {"R-001", "R-901", "R-201"} <= inventory.pr_scan_ids()
    assert {"R-001", "R-100", "R-301"} <= set(manifest)


def test_real_inventory_passes_when_the_pr_scan_set_is_reported() -> None:
    report = {"screens": {rid: {"violations": []} for rid in inventory.pr_scan_ids()}}
    assert gates.check_inventory(report, "pr") == []


def test_real_inventory_fails_when_the_report_drops_a_scanned_mounted_route() -> None:
    ids = inventory.pr_scan_ids() - {"R-901"}
    msgs = gates.check_inventory({"screens": {rid: {} for rid in ids}}, "pr")
    assert msgs and all("A11Y-G008" in m for m in msgs) and any("SCR-155" in m for m in msgs)


def test_cli_inventory_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps({"screens": {r: {} for r in inventory.pr_scan_ids()}}), encoding="utf-8")
    bad.write_text(json.dumps({"screens": {}}), encoding="utf-8")
    assert gates.main(["inventory", str(good)]) == 0
    assert "pending" in capsys.readouterr().out  # the counted line
    assert gates.main(["inventory", str(bad)]) == 1
    assert gates.main(["inventory", str(tmp_path / "absent.json")]) == 3


def test_every_lighthouse_screen_is_in_the_inventory_and_unmounted_ones_are_pending() -> None:
    manifest = inventory.load_manifest()
    rows = inventory.load_rows(manifest=manifest)
    plan = {e["screen"]: e for e in inventory.lighthouse_plan(rows, manifest)["screens"]}
    assert len(plan) == 10  # the ticket's eight, plus the two always scored
    assert {"SCR-030", "SCR-060", "SCR-063", "SCR-121", "SCR-093", "SCR-100", "SCR-110", "SCR-090"} <= set(plan)
    assert "pending" not in plan["SCR-001"] and "pending" not in plan["SCR-155"]
    assert plan["SCR-060"]["pending"].startswith("pending E30-S01")


def test_lighthouse_plan_marks_a_mounted_guarded_route_pending_for_a_session() -> None:
    manifest = inventory.load_manifest()
    rows = [
        inventory.Row(s, "n", "mounted", "E1 #1", ()) for s, _ in inventory.LIGHTHOUSE_SCREENS
    ]
    plan = {e["screen"]: e for e in inventory.lighthouse_plan(rows, manifest)["screens"]}
    assert "pending" not in plan["SCR-001"]
    assert "session" in plan["SCR-121"]["pending"]


# --- hosted rows, broken inventories (A11Y-INFRA) ------------------------------------------------


def _findings(tmp_path: Path, *screens: dict) -> Path:
    f = tmp_path / "findings.json"
    f.write_text(json.dumps({"screens": list(screens)}), encoding="utf-8")
    return f


def _scr(sid: str, coverage: str, reason: str = "", ticket: str = "E1-S1 #1") -> dict:
    return {"id": sid, "name": "n", "coverage": coverage, "coverageReason": reason, "owningTicket": ticket}


MANIFEST = inventory.load_manifest()


def test_hosted_row_requires_its_host_in_the_report(tmp_path: Path) -> None:
    f = _findings(tmp_path, _scr("SCR-005", "covered", "App.tsx:33 (SessionLockHost)"))
    rows = inventory.load_rows(f, MANIFEST, {"SCR-005": "R-201"})
    assert rows[0].hosts == ("R-201",) and rows[0].required_routes == ("R-201",)
    msgs = inventory.check_inventory({"screens": {}}, rows, PR)
    assert len(msgs) == 1 and "SCR-005" in msgs[0] and "hosted by R-201" in msgs[0]
    assert inventory.check_inventory({"screens": {"R-201": {}}}, rows, PR) == []


def test_hosted_row_may_be_hosted_by_a_routed_screen(tmp_path: Path) -> None:
    f = _findings(
        tmp_path,
        _scr("SCR-017", "covered", "tree.tsx:39 (R-009 -> InviteAcceptScreen)"),
        _scr("SCR-003", "partial", "inside SCR-017"),
    )
    rows = inventory.load_rows(f, MANIFEST, {"SCR-003": "SCR-017"})
    assert rows[1].hosts == ("R-009",)
    assert "SCR-003" in inventory.check_inventory({"screens": {}}, rows, PR, "full")[0] + "SCR-003"


@pytest.mark.parametrize("hosts", [{}, {"SCR-005": ""}, {"SCR-005": "R-999"}, {"SCR-005": "SCR-777"}])
def test_hosted_row_without_a_resolvable_host_is_infra(tmp_path: Path, hosts: dict) -> None:
    f = _findings(tmp_path, _scr("SCR-005", "covered", "App.tsx:33"))
    with pytest.raises(inventory.InventoryError, match="A11Y-INFRA.*SCR-005"):
        inventory.load_rows(f, MANIFEST, hosts)


def test_host_that_is_itself_unrouted_is_infra(tmp_path: Path) -> None:
    f = _findings(tmp_path, _scr("SCR-003", "partial", "x"), _scr("SCR-017", "covered", "no route"))
    with pytest.raises(inventory.InventoryError, match="SCR-003"):
        inventory.load_rows(f, MANIFEST, {"SCR-003": "SCR-017", "SCR-017": "R-001"})


def test_route_id_missing_from_the_manifest_is_infra(tmp_path: Path) -> None:
    f = _findings(tmp_path, _scr("SCR-050", "covered", "tree.tsx:9 (R-998 -> Foo)"))
    with pytest.raises(inventory.InventoryError, match="R-998.*manifest"):
        inventory.load_rows(f, MANIFEST, {})
    # a mention in a pending row's reason counts too: the reason must not name a route that is gone
    f = _findings(tmp_path, _scr("SCR-051", "unreachable: not built", "was R-998"))
    with pytest.raises(inventory.InventoryError, match="R-998"):
        inventory.load_rows(f, MANIFEST, {})


@pytest.mark.parametrize("cov", ["", "mounted", "Covered", "reserved", "unreachable", "done"])
def test_unknown_coverage_value_is_infra(tmp_path: Path, cov: str) -> None:
    f = _findings(tmp_path, _scr("SCR-050", cov))
    with pytest.raises(inventory.InventoryError, match="unknown coverage"):
        inventory.load_rows(f, MANIFEST, {})


@pytest.mark.parametrize("ticket", ["", "  ", "unassigned"])
def test_pending_row_without_an_owning_ticket_is_infra(tmp_path: Path, ticket: str) -> None:
    f = _findings(tmp_path, _scr("SCR-050", "unreachable: not built", ticket=ticket))
    with pytest.raises(inventory.InventoryError, match="owningTicket"):
        inventory.load_rows(f, MANIFEST, {})


def test_reserved_row_needs_no_ticket(tmp_path: Path) -> None:
    f = _findings(tmp_path, _scr("SCR-007", "reserved: no screen", ticket="unassigned"))
    assert inventory.load_rows(f, MANIFEST, {})[0].status == "reserved"


def test_inventory_error_reaches_the_cli_as_infra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = _findings(tmp_path, _scr("SCR-050", "bogus"))
    monkeypatch.setattr(inventory, "FINDINGS", f)
    monkeypatch.setattr(inventory.load_rows, "__defaults__", (f, None, None))
    rep = tmp_path / "axe.json"
    rep.write_text(json.dumps({"screens": {}}), encoding="utf-8")
    assert gates.main(["inventory", str(rep)]) == 3


def test_real_hosts_file_names_a_host_for_every_hosted_row() -> None:
    rows = inventory.load_rows()
    hosted = [r for r in rows if r.status == "mounted" and not r.routes]
    assert hosted and all(r.hosts for r in hosted)


def test_lighthouse_plan_is_built_from_the_inventory() -> None:
    rows = inventory.load_rows()
    plan = inventory.lighthouse_plan(rows, MANIFEST)["screens"]
    assert len(plan) == 10 and all("route" in e and "path" in e for e in plan)
