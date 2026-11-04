"""Fixture-driven unit tests for tests/toolchain/pack.py (E02-Q03).

Each acceptance scenario in the ticket gets a positive case (the pack must
pass on the merged scaffold) and a negative case (an injected violation must
be caught, naming the rule id / file). Positive cases run against the real
repo tree (`REPO_ROOT`); negative cases build a minimal temp tree so the
pack's own failure path is proven correct, per the ticket's "Unit" test
plan.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.toolchain import pack

# --- Assertion 3 / C-9.4: coverage thresholds --------------------------------


def test_coverage_floors_passes_on_real_repo() -> None:
    assert pack.check_coverage_floors(pack.REPO_ROOT) == []


def test_coverage_floors_fails_when_lowered(tmp_path: Path) -> None:
    (tmp_path / "quality-gates.json").write_text(
        """{
  "coverage": {
    "services/api": {"lines": 70.0, "branches": 75.0},
    "packages/chart-engine": {"lines": 85.0, "branches": 75.0},
    "apps/web": {"lines": 80.0, "branches": 70.0},
    "packages/ui": {"lines": 80.0, "branches": 70.0}
  }
}""",
        encoding="utf-8",
    )
    violations = pack.check_coverage_floors(tmp_path)
    assert any("services/api" in str(v) and "C-9.4" in str(v) for v in violations)


# --- Assertion 4 / C-9.4: omit provenance -------------------------------------


def test_coverage_omit_provenance_passes_on_real_repo() -> None:
    assert pack.check_coverage_omit_provenance(pack.REPO_ROOT) == []


def test_coverage_omit_provenance_fails_without_ticket_ref(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.coverage.run]\n"
        "# no ticket reference here\n"
        'omit = [\n  "candleviewer/foo/*",\n]\n',
        encoding="utf-8",
    )
    violations = pack.check_coverage_omit_provenance(tmp_path)
    assert any("no ticket reference" in str(v) for v in violations)
    assert any("no dated reference" in str(v) for v in violations)


def test_coverage_omit_provenance_fails_when_expired(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
    (tmp_path / "pyproject.toml").write_text(
        "[tool.coverage.run]\n"
        f"# OF-1 2026-01-01 expires: {old}\n"
        'omit = [\n  "candleviewer/foo/*",\n]\n',
        encoding="utf-8",
    )
    violations = pack.check_coverage_omit_provenance(tmp_path)
    assert any("expired on" in str(v) for v in violations)


# --- Assertion 5 / E02-T06: architecture contract exceptions ------------------


def test_architecture_contracts_passes_on_real_repo() -> None:
    assert pack.check_architecture_contracts(pack.REPO_ROOT) == []


def test_architecture_contracts_fails_on_undocumented_ignore_imports(tmp_path: Path) -> None:
    api_dir = tmp_path / "services" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / ".importlinter").write_text(
        "[importlinter]\nroot_package = candleviewer\n\n"
        "[importlinter:contract:forbidden-M1]\n"
        "name = M1\ntype = forbidden\n"
        "ignore_imports =\n    candleviewer.settings -> candleviewer.audit\n",
        encoding="utf-8",
    )
    (tmp_path / ".dependency-cruiser.js").write_text(
        'module.exports = { forbidden: [{ name: "x" }] };\n', encoding="utf-8"
    )
    violations = pack.check_architecture_contracts(tmp_path)
    assert any(
        "ignore_imports" in str(v) and "no preceding ADR reference" in str(v) for v in violations
    )


def test_architecture_contracts_passes_with_adr_reference(tmp_path: Path) -> None:
    api_dir = tmp_path / "services" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / ".importlinter").write_text(
        "[importlinter]\nroot_package = candleviewer\n\n"
        "[importlinter:contract:forbidden-M1]\n"
        "name = M1\ntype = forbidden\n"
        "# ADR-0099 authorises this exception\n"
        "ignore_imports =\n    candleviewer.settings -> candleviewer.audit\n",
        encoding="utf-8",
    )
    (tmp_path / ".dependency-cruiser.js").write_text(
        'module.exports = { forbidden: [{ name: "x" }] };\n', encoding="utf-8"
    )
    violations = pack.check_architecture_contracts(tmp_path)
    assert violations == []


# --- Assertion 6 / C-9.3: flaky quarantine age --------------------------------


def test_flaky_quarantine_age_passes_on_real_repo() -> None:
    assert pack.check_flaky_quarantine_age(pack.REPO_ROOT) == []


def test_flaky_quarantine_age_fails_when_older_than_ten_working_days(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
    (tmp_path / "test_thing.py").write_text(
        "import pytest\n"
        f"@pytest.mark.flaky  # ticket: OF-42 quarantined: {old}\n"
        "def test_x():\n    assert True\n",
        encoding="utf-8",
    )
    violations = pack.check_flaky_quarantine_age(tmp_path)
    assert any("C-9.3" in str(v) and "OF-42" in str(v) for v in violations)


def test_flaky_quarantine_age_passes_within_window(tmp_path: Path) -> None:
    recent = datetime.now(timezone.utc).date().isoformat()
    (tmp_path / "test_thing.py").write_text(
        "import pytest\n"
        f"@pytest.mark.flaky  # ticket: OF-42 quarantined: {recent}\n"
        "def test_x():\n    assert True\n",
        encoding="utf-8",
    )
    assert pack.check_flaky_quarantine_age(tmp_path) == []


def test_flaky_quarantine_age_reads_the_playwright_title_tag(tmp_path: Path) -> None:
    # E49-Q01 (#1335, BQ-5): the `@flaky` title tag of a Playwright spec, same markers.
    old = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
    (tmp_path / "x.spec.ts").write_text(
        f'// ticket: E49-1 quarantined: {old} owner: qa\ntest("x @flaky", () => {{}});\n'
        'test("y @flaky", () => {});\n',
        encoding="utf-8",
    )
    found = [str(v) for v in pack.check_flaky_quarantine_age(tmp_path)]
    assert any("x.spec.ts:2" in v and "E49-1" in v for v in found)
    assert any("x.spec.ts:3" in v and "no `ticket: <KEY>`" in v for v in found)


# --- Assertion 7: compose invariants ------------------------------------------


def test_compose_invariants_passes_on_real_repo() -> None:
    assert pack.check_compose_invariants(pack.REPO_ROOT) == []


def test_compose_invariants_fails_on_mutable_tag_and_missing_healthcheck(tmp_path: Path) -> None:
    compose_dir = tmp_path / "infra" / "compose"
    compose_dir.mkdir(parents=True)
    (compose_dir / "docker-compose.yml").write_text(
        "services:\n"
        "  broken:\n"
        "    image: postgres:16.4\n"
        '    ports:\n      - "5432:5432"\n',
        encoding="utf-8",
    )
    violations = pack.check_compose_invariants(tmp_path)
    joined = " ".join(str(v) for v in violations)
    assert "not pinned by sha256 digest" in joined
    assert "not explicitly bound to" in joined
    assert "missing healthcheck" in joined


# --- Assertion 1 / C-9.1: gate registration -----------------------------------


def test_gate_registration_passes_on_real_repo() -> None:
    assert pack.check_gate_registration(pack.REPO_ROOT) == []


# --- Assertion 2 / AGENTS.md §4: commands task graph --------------------------


def test_agents_commands_passes_on_real_repo() -> None:
    assert pack.check_agents_commands(pack.REPO_ROOT) == []


# --- Bug #1576 (E02-Q03-B1): runtime budget --------------------------------
#
# The pack blew its own 3-minute budget (measured 3m56s-4m11s) because
# check_flaky_quarantine_age / check_coverage_omit_provenance walked the
# *entire* tree with Path.rglob("...")/Path.glob("**/...") -- which descends
# into every node_modules/.venv/.git directory before any per-path filter
# runs -- and only filtered matched paths afterwards. `_walk_files` prunes
# ignored directories at `os.walk` time instead, so it must never descend
# into a pruned directory even when that directory holds millions of
# matching-suffix files.


def test_walk_files_prunes_ignored_directories(tmp_path: Path) -> None:
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "test_thing.py").write_text("def test_x(): pass\n", encoding="utf-8")

    pruned = tmp_path / "node_modules" / "some_pkg"
    pruned.mkdir(parents=True)
    (pruned / "test_should_be_ignored.py").write_text("def test_y(): pass\n", encoding="utf-8")

    also_pruned = tmp_path / ".venv" / "lib"
    also_pruned.mkdir(parents=True)
    (also_pruned / "test_should_be_ignored_too.py").write_text(
        "def test_z(): pass\n", encoding="utf-8"
    )

    found = pack._walk_files(tmp_path, (".py",))
    rel_names = {p.relative_to(tmp_path).as_posix() for p in found}
    assert rel_names == {"keep/test_thing.py"}


def test_walk_files_does_not_descend_into_pruned_directories(tmp_path: Path) -> None:
    # A pruned directory containing a file pytest cannot read (permission-
    # like sentinel via a directory named as a file suffix trap) must never
    # be opened -- proving pruning happens at os.walk time, not via a
    # post-hoc filter that still incurs the descend cost this bug reported.
    import os

    trap_dir = tmp_path / "node_modules" / ("x" * 40)
    trap_dir.mkdir(parents=True)
    for i in range(50):
        (trap_dir / f"test_trap_{i}.py").write_text("def test_x(): pass\n", encoding="utf-8")

    visited: list[str] = []
    for dirpath, dirnames, _ in os.walk(tmp_path):
        dirnames[:] = [d for d in dirnames if d not in pack._PRUNED_DIR_NAMES]
        visited.append(dirpath)
    assert not any("node_modules" in v for v in visited)

    found = pack._walk_files(tmp_path, (".py",))
    assert found == []


# --- Runner / report -----------------------------------------------------------


def test_run_all_returns_every_registered_check() -> None:
    results = pack.run_all(pack.REPO_ROOT)
    assert set(results) == {name for name, _ in pack.ALL_CHECKS}


def test_write_report_emits_json(tmp_path: Path) -> None:
    results = {"gate-x": []}
    report_path = pack.write_report(results, tmp_path)
    assert report_path.exists()
    assert report_path == tmp_path / "reports" / "toolchain-regression.json"
    import json

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["overall"] == "pass"
    assert payload["gates"]["gate-x"]["status"] == "pass"


def test_main_exits_nonzero_when_a_gate_fails(tmp_path: Path, monkeypatch) -> None:
    # Build a minimal broken tree that fails the compose check but has none
    # of the other files, so other checks report "not found" -- still a
    # non-zero exit, proving `main()` propagates any failure.
    exit_code = pack.main(["--repo-root", str(tmp_path)])
    assert exit_code == 1
