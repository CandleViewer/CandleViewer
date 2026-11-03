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


def test_pa11y_config_lists_only_mounted_public_routes_with_the_chrome_path() -> None:
    manifest = inventory.load_manifest()
    rows = inventory.load_rows(manifest=manifest)
    cfg = inventory.pa11y_config(rows, manifest, "http://127.0.0.1:4173/", "/opt/chrome")
    urls = {u["_route"]: u["url"] for u in cfg["urls"]}
    assert urls["R-001"] == "http://127.0.0.1:4173/login"
    assert all(manifest[r].public for r in urls)
    assert "R-201" not in urls  # guarded: a bare visit is bounced to /login
    assert cfg["defaults"]["chromeLaunchConfig"]["executablePath"] == "/opt/chrome"
    assert cfg["defaults"]["standard"] == "WCAG2AA"

