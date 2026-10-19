"""#3558: C-9.1 #11's Dependabot alert gate (`security_gate.py --tool dependabot`) and the
`dependabot-alerts` job of `pr.yml`. The open alerts on `main` are recorded `gh api` listings
(scripts/tests/fixtures/dependabot-alerts/), planted at a higher severity or with another range
where a test needs one; the tree under test and its merge base are commits of a scratch git
repository. No network."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci.security_gate import (
    AcceptedRisk,
    Finding,
    SecurityGateError,
    evaluate_findings,
    main,
    parse_dependabot_alerts,
    resolved_versions,
)

ALERTS = Path(__file__).resolve().parent / "fixtures" / "dependabot-alerts"
RECORDED = (ALERTS / "gh-2.67.0-main.json").read_text(encoding="utf-8")
TAURI, VITEST = "GHSA-7gmj-67g7-phm9", "GHSA-82fw-gwwq-j7x9"
TAURI_DIR = "packages/chart-engine/bench/matrix/tauri/src-tauri"
REGISTER = "security/accepted-risks.yaml"
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
GIT_ENV |= {f"GIT_{who}_{key}": "t" for who in ("AUTHOR", "COMMITTER") for key in ("NAME", "EMAIL")}
# pnpm 12's lockfile, cut down: a document for pnpm itself, then the workspace's.
LOCK = """---
lockfileVersion: '9.0'

packages:
  pnpm@12.5.1: {}
---
lockfileVersion: '9.0'

importers:
  .: {}
  apps/web: {}

packages:
  '@vitest/mocker@3.2.7': {}
  tinypool@2.2.0: {}
  vitest@3.2.7: {}

snapshots:
  vitest@3.2.7(@types/node@22.20.5): {}
"""
Files = Mapping[str, str | PurePosixPath | None]  # path -> text, a symlink's target, or None
MAIN: Files = {"pnpm-lock.yaml": LOCK}
FIX = {"pnpm-lock.yaml": LOCK.replace("vitest@3.2.7", "vitest@4.1.11")}  # fixes alert 37
UNRELATED = {"pnpm-lock.yaml": LOCK.replace("tinypool@2.2.0", "tinypool@2.2.1")}  # not vitest
OK = "security_gate[dependabot]: OK\n"
FIXED = "fixed here: dependabot alert 37 ({}, {}), npm:vitest in pnpm-lock.yaml: 3.2.7 -> 4.1.11\n"
KEPT = " (this tree leaves it at 3.2.7 in pnpm-lock.yaml)\n"
Gate = Callable[..., tuple[int, str, str]]


def _git(repo: Path, *args: str) -> str:
    env = os.environ | GIT_ENV
    run = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, check=True)
    return run.stdout.decode().strip()


def _commit(repo: Path, files: Files) -> str:
    for name, text in files.items():
        path = repo / name
        if text is None:
            path.unlink()
        elif isinstance(text, PurePosixPath):  # in place of the file or directory there
            shutil.rmtree(path, ignore_errors=True)
            path.unlink(missing_ok=True)
            path.symlink_to(text)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "change")
    return _git(repo, "rev-parse", "HEAD")


def _checkout(tmp_path: Path, main_tree: Files, *prs: Files) -> tuple[Path, str]:
    """The job's checkout: HEAD is `main` plus the PR (in a merge group, the entries queued ahead
    of it, then it), `origin/main` their merge base."""
    repo = tmp_path / "ws"
    repo.mkdir()
    _git(repo, "init", "-q")
    base = _commit(repo, {REGISTER: "entries: []\n", **main_tree})
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    for pr in prs:
        _commit(repo, pr)
    return repo, base


def _alert(number: int, severity: str = "critical", **moved: str) -> dict[str, Any]:
    """Recorded alert `number`, planted at `severity`, moved to another `ecosystem`, package
    `name` or `manifest_path`."""
    alert: dict[str, Any] = next(a for a in json.loads(RECORDED)[0] if a["number"] == number)
    alert["security_advisory"]["severity"] = severity
    if "manifest_path" in moved:
        alert["dependency"]["manifest_path"] = moved.pop("manifest_path")
    alert["dependency"]["package"].update(moved)
    return alert


def _ranged(alert: dict[str, Any], vulnerable: str, first: str | None) -> dict[str, Any]:
    """`alert` with another vulnerable range and first patched version (None: none yet)."""
    patched = first and {"identifier": first}
    alert["security_vulnerability"] |= {
        "vulnerable_version_range": vulnerable,
        "first_patched_version": patched,
    }
    return alert


@pytest.fixture
def gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Gate:
    """`security_gate.py --tool dependabot` run in the checkout, as the step runs it."""

    def run(alerts: list[Any], pr: Files, main_tree: Files = MAIN, base: str | None = None) -> Any:
        repo, merge_base = _checkout(tmp_path, main_tree, pr)
        report = tmp_path / "alerts.json"
        report.write_text(json.dumps([alerts]), encoding="utf-8")
        for name, value in GIT_ENV.items():
            monkeypatch.setenv(name, value)
        monkeypatch.chdir(repo)  # the register and HEAD are the PR's own tree
        argv = ["--tool", "dependabot", "--report", str(report), "--run-date", "2026-10-19"]
        rc = main(argv + ([] if base == "" else ["--base", base or merge_base]))
        return (rc, *capsys.readouterr())

    return run


@pytest.mark.parametrize(
    ("severity", "pr", "entry", "verdict"),
    [
        pytest.param("critical", FIX, None, "fixed", id="critical-and-a-fix-pr-green"),
        pytest.param("critical", UNRELATED, None, "CI-SEC-001", id="critical-unrelated-pr-red"),
        pytest.param("high", UNRELATED, None, "CI-SEC-001", id="high-red"),
        pytest.param("high", FIX, None, "fixed", id="high-and-a-fix-pr-green"),
        pytest.param("high", {}, ("HIGH", "2026-11-20"), "accepted", id="dated-entry-green"),
        pytest.param("high", {}, ("HIGH", "2026-11-20", "npm-audit"), "accepted", id="any-tool"),
        pytest.param("high", {}, ("HIGH", "2026-10-19"), "CI-SEC-004", id="expired-entry-red"),
        pytest.param("high", {}, ("MEDIUM", "2026-11-20"), "CI-SEC-001", id="entry-caps-severity"),
        pytest.param("critical", {}, ("HIGH", "2026-11-20"), "CI-SEC-001", id="critical-no-entry"),
        pytest.param("high", FIX, ("HIGH", "2026-10-19"), "fixed", id="fix-needs-no-live-entry"),
        pytest.param("medium", UNRELATED, None, "ok", id="medium-not-blocking"),
        pytest.param("low", UNRELATED, None, "ok", id="low-not-blocking"),
    ],
)
def test_alert_blocks_from_high_unless_this_tree_fixes_it_or_its_entry_accepts_it(
    gate: Gate, severity: str, pr: Files, entry: tuple[str, ...] | None, verdict: str
) -> None:
    files = dict(pr)
    if entry:  # the PR adds the entry
        fields = dict(zip(("severity", "expires", "tool"), (*entry, "dependabot"), strict=False))
        fields |= {"id": VITEST, "reason": "test", "approver": "basiltt"}
        files[REGISTER] = yaml.safe_dump({"entries": [fields]})
    rc, out, err = gate([_alert(37, severity)], files)
    if verdict == "fixed":
        assert (rc, out, err) == (0, FIXED.format(VITEST, severity.upper()) + OK, "")
    elif verdict == "accepted":
        assert (rc, err, out.endswith(OK)) == (0, "", True)
        assert out.startswith(f"accepted risk: dependabot finding {VITEST} (HIGH) until 2026-11-20")
    elif verdict == "ok":
        assert (rc, out, err) == (0, OK, "")
    else:
        assert (rc, out, err.startswith(f"{verdict}: ")) == (1, "", True)
        assert err.endswith(f"\nsecurity_gate[dependabot]: BLOCKED ({verdict})\n")
        if verdict == "CI-SEC-001":  # names the alert, its manifest and what this tree resolves
            assert " — alert 37, npm:vitest in apps/web/package.json: Vitest: Path " in err
            assert KEPT in err


TOML = '[dependencies]\ntauri = { version = "=2.1.1", features = [] }\n'
TOML += '\n[build-dependencies]\ntauri-build = "=2.0.3"\n'
CARGO_LOCK = '[[package]]\nname = "tauri"\nversion = "2.1.1"\n'
UV_LOCK = 'version = 1\n\n[[package]]\nname = "pyyaml"\nversion = "6.0.2"\n'
PINS = "PyYAML==6.0.2 \\\n    --hash=sha256:00\n"
PYYAML = {"ecosystem": "pip", "name": "PyYAML"}
CARGO, REQS = f"{TAURI_DIR}/Cargo.toml", "scripts/requirements-ci.txt"
TAURI_LOCK = f"{TAURI_DIR}/Cargo.lock"
PINNED = _ranged(_alert(37, manifest_path=REQS, **PYYAML), "< 6.0.3", "6.0.3")
# Case -> the alert, main's files, the fix PR, an unrelated PR, and the change the fix makes.
MAPPINGS: dict[str, tuple[dict[str, Any], Files, Files, Files, str]] = {
    "cargo-toml-without-a-lock": (
        _alert(55),
        {CARGO: TOML},
        {CARGO: TOML.replace('"=2.1.1"', '"=2.11.1"')},
        {CARGO: TOML.replace("=2.0.3", "=2.0.4")},
        f"{CARGO}: =2.1.1 -> =2.11.1",
    ),
    "cargo-lock-beside-it": (
        _alert(55),
        {CARGO: TOML, TAURI_LOCK: CARGO_LOCK},
        {
            TAURI_LOCK: CARGO_LOCK.replace("2.1.1", "2.11.1"),
            CARGO: TOML.replace("=2.1.1", "=2.11.1"),
        },
        {CARGO: TOML.replace('"=2.1.1"', '"2"')},
        f"{TAURI_LOCK}: 2.1.1 -> 2.11.1",
    ),
    "uv-lock-of-a-pyproject": (
        _alert(37, manifest_path="services/api/pyproject.toml", **PYYAML),
        {"services/api/uv.lock": UV_LOCK},
        {"services/api/uv.lock": UV_LOCK.replace("6.0.2", "6.0.3")},
        {"services/api/pyproject.toml": "[project]\n"},
        "services/api/uv.lock: 6.0.2 -> 6.0.3",
    ),
    "requirements-file": (
        PINNED,
        {REQS: PINS},
        {REQS: PINS.replace("6.0.2", "6.0.3")},
        {REQS: PINS.replace(":00", ":11")},
        f"{REQS}: ==6.0.2 -> ==6.0.3",
    ),
    "npm-package-removed": (
        _alert(37),
        MAIN,
        {"pnpm-lock.yaml": LOCK.replace("  vitest@3.2.7: {}\n", "")},
        UNRELATED,
        "pnpm-lock.yaml: 3.2.7 -> removed",
    ),
}


@pytest.mark.parametrize("case", sorted(MAPPINGS))
@pytest.mark.parametrize("fixed", [True, False], ids=["fix-pr", "unrelated-pr"])
def test_each_ecosystem_judges_the_alerts_package_in_its_lockfile(
    gate: Gate, case: str, fixed: bool
) -> None:
    alert, main_tree, fix, unrelated, change = MAPPINGS[case]
    rc, out, err = gate([alert], fix if fixed else unrelated, main_tree)
    package = "{ecosystem}:{name}".format(**alert["dependency"]["package"])
    if fixed:
        assert (rc, err) == (0, "")
        assert out.startswith(f"fixed here: dependabot alert {alert['number']} (")
        assert out.endswith(f"), {package} in {change}\n{OK}")
    else:
        path, versions = change.split(": ")[0], change.split(": ")[1].split(" -> ")[0]
        assert (rc, out, f" (this tree leaves it at {versions} in {path})\n" in err) == (
            1,
            "",
            True,
        )


MOVED = "(this tree moves it to {} in {}, which no audit step reads: "
# No audit step reads these files, so a change is a fix only if each version it leaves is an exact
# release at or above the first patched one and outside the vulnerable range (tauri's are 2.11.1
# and >= 2.0.0, <= 2.11.0): case -> the alert, main's files, the PR, and the fix or why it is none.
UNAUDITED: dict[str, tuple[dict[str, Any], Files, Files, str]] = {
    "pin-respelt": (
        PINNED,
        {REQS: PINS},
        {REQS: PINS.replace("==", " == ")},
        f"at ==6.0.2 in {REQS})",
    ),
    "pin-to-another-affected": (
        PINNED,
        {REQS: PINS},
        {REQS: PINS.replace("6.0.2", "6.0.1")},
        MOVED.format("==6.0.1", REQS),
    ),
    "pin-to-a-range": (
        PINNED,
        {REQS: PINS},
        {REQS: PINS.replace("==6.0.2", ">=6.0.3")},
        MOVED.format(">=6.0.3", REQS),
    ),
    "toml-within-the-range": (
        _alert(55),
        {CARGO: TOML},
        {CARGO: TOML.replace("=2.1.1", "=2.5.0")},
        MOVED.format("=2.5.0", CARGO),
    ),
    "downgrade-below-the-range": (
        _alert(55),
        {CARGO: TOML},
        {CARGO: TOML.replace("=2.1.1", "=1.8.0")},
        MOVED.format("=1.8.0", CARGO),
    ),
    "patched-but-in-the-range": (
        _ranged(_alert(55), ">= 2.0.0", "2.11.1"),
        {CARGO: TOML},
        {CARGO: TOML.replace("=2.1.1", "=2.11.1")},
        MOVED.format("=2.11.1", CARGO),
    ),
    "lock-added-at-the-same-version": (
        _alert(55),
        {CARGO: TOML},
        {TAURI_LOCK: CARGO_LOCK},
        MOVED.format(f"2.1.1 in {TAURI_LOCK} and =2.1.1", CARGO),
    ),
    "lock-deleted": (
        _alert(55),
        {CARGO: TOML, TAURI_LOCK: CARGO_LOCK},
        {TAURI_LOCK: None},
        MOVED.format("=2.1.1", CARGO),
    ),
    "no-patched-release": (
        _ranged(_alert(55), ">= 2.0.0", None),
        {CARGO: TOML},
        {CARGO: TOML.replace("=2.1.1", "=2.11.1")},
        MOVED.format("=2.11.1", CARGO) + "a fix there is removing it, as no release is patched",
    ),
    "lock-added-at-the-patched-version": (
        _alert(55),
        {CARGO: TOML},
        {
            CARGO: TOML.replace("=2.1.1", "=2.11.1"),
            TAURI_LOCK: CARGO_LOCK.replace("2.1.1", "2.11.1"),
        },
        f"fixed in {CARGO}: =2.1.1 -> {TAURI_LOCK}: 2.11.1",
    ),
    "unreadable-range": (
        _ranged(_alert(55), "~> 2.0", "2.11.1"),
        {CARGO: TOML},
        {CARGO: TOML.replace("=2.1.1", "=2.11.1")},
        "CI-SEC-005: dependabot: alert 55's advisory gives no vulnerable range '~> 2.0' and first ",
    ),
    "requirement-indented": (PINNED, {REQS: PINS}, {REQS: f"  {PINS}"}, f"at ==6.0.2 in {REQS})"),
    "lock-patched-beside-an-old-pin": (
        _alert(55),
        {CARGO: TOML, TAURI_LOCK: CARGO_LOCK},
        {TAURI_LOCK: CARGO_LOCK.replace("2.1.1", "2.11.1")},
        MOVED.format(f"2.11.1 in {TAURI_LOCK} and =2.1.1", CARGO),
    ),
    "lock-patched-beside-a-range": (
        _alert(55),
        {CARGO: TOML, TAURI_LOCK: CARGO_LOCK},
        {TAURI_LOCK: CARGO_LOCK.replace("2.1.1", "2.11.1"), CARGO: TOML.replace("=2.1.1", "2")},
        MOVED.format(f"2.11.1 in {TAURI_LOCK} and 2", CARGO),
    ),
    "manifest-symlinked": (
        PINNED,
        {REQS: PINS, "scripts/vendored.txt": PINS},
        {REQS: PurePosixPath("vendored.txt")},
        f"CI-SEC-005: dependabot: cannot read {REQS} at HEAD: {REQS} has git mode 120000, not a ",
    ),
    "directory-symlinked": (
        PINNED,
        {REQS: PINS, "vendor/requirements-ci.txt": PINS},
        {"scripts": PurePosixPath("vendor")},
        f"CI-SEC-005: dependabot: cannot read {REQS} at HEAD: scripts has git mode 120000, not a ",
    ),
    "absent-at-the-merge-base": (
        PINNED,
        {REQS: "requests==2.32.4\n"},
        {REQS: "requests==2.32.4\nPyYAML==6.0.3\n"},
        f"CI-SEC-005: dependabot: alert 37: {REQS} resolves PyYAML to no version at the merge base",
    ),
}


@pytest.mark.parametrize("case", sorted(UNAUDITED))
def test_change_no_audit_step_reads_fixes_only_to_an_exact_patched_release(
    gate: Gate, case: str
) -> None:
    alert, main_tree, pr, says = UNAUDITED[case]
    rc, out, err = gate([alert], pr, main_tree)
    if says.startswith("fixed in "):
        assert (rc, err, out.endswith(f" {says.removeprefix('fixed ')}\n{OK}")) == (0, "", True)
    elif says.startswith("CI-SEC-005: "):
        assert (rc, out, err.startswith(says)) == (1, "", True)
    else:
        assert (rc, out, err.startswith("CI-SEC-001: "), says in err) == (1, "", True, True)


@pytest.mark.parametrize(
    ("moved", "pr", "base", "says"),
    [
        ({"manifest_path": "yarn.lock"}, FIX, None, "alert 37 is on yarn.lock (npm), which the "),
        ({"manifest_path": "tools/x/pnpm-lock.yaml"}, FIX, None, "alert 37 is on tools/x/pnpm-"),
        ({"manifest_path": "tools/style-dictionary/package.json"}, FIX, None, "alert 37 is on "),
        ({**PYYAML, "manifest_path": "tools/x/pyproject.toml"}, {}, None, "alert 37 is on tools/x"),
        ({"ecosystem": "go", "manifest_path": "go.mod"}, FIX, None, "alert 37 is on go.mod (go), "),
        (
            {"name": "left-pad"},
            FIX,
            None,
            "alert 37: pnpm-lock.yaml resolves left-pad to no version at the merge base",
        ),
        ({}, {"pnpm-lock.yaml": None, "pnpm-lock.yaml/x": ""}, None, "cannot read pnpm-lock.yaml "),
        ({}, {"pnpm-lock.yaml": "packages: [\n"}, None, "pnpm-lock.yaml at HEAD is not a lockfile"),
        ({}, {}, "", "--base (the merge base of HEAD and main, a full commit id) is required"),
        ({}, {}, "main", "--base 'main' is no full commit id"),
        ({}, {}, "0" * 40, f"{'0' * 40} is not a commit in this checkout"),
    ],
    ids=[
        "unmapped",
        "nested-lock",
        "outside-the-workspace",
        "pip-outside-services-api",
        "ecosystem",
        "no-version",
        "not-a-file",
        "unparsable",
        "no-base",
        "ref",
        "gone",
    ],
)
def test_blocking_alert_the_gate_cannot_judge_fails_closed_with_ci_sec_005(
    gate: Gate, moved: dict[str, str], pr: Files, base: str | None, says: str
) -> None:
    # Never as "no alerts" or as a fix: an unreadable lockfile is no removal of the package.
    rc, out, err = gate([_alert(37, **moved)], pr, base=base)
    assert (rc, out, err.startswith(f"CI-SEC-005: dependabot: {says}")) == (1, "", True)


def test_no_open_alert_passes(gate: Gate) -> None:
    # gh writes `[[]]` for no open alert: one page, empty. Only a listing that is no list of pages
    # fails closed.
    assert gate([], {}) == (0, OK, "")


def test_audited_lock_that_keeps_an_alerted_version_is_left_to_its_audit(gate: Gate) -> None:
    # pnpm audit judges every version the lock resolves, so the note says the change is passed on,
    # not that it fixed the alert.
    both = LOCK.replace("  vitest@3.2.7: {}\n", "  vitest@3.2.7: {}\n  vitest@4.1.11: {}\n")
    rc, out, err = gate([_alert(37)], {"pnpm-lock.yaml": both})
    assert (rc, err) == (0, "")
    assert out == (
        f"changed here, for npm-audit to judge: dependabot alert 37 ({VITEST}, CRITICAL), "
        f"npm:vitest in pnpm-lock.yaml: 3.2.7 -> 3.2.7, 4.1.11\n{OK}"
    )


def test_alert_below_high_is_never_mapped(gate: Gate) -> None:
    alert = _alert(37, "medium", ecosystem="go", manifest_path="go.mod")
    assert gate([alert], {}) == (0, OK, "")


def test_recorded_alerts_on_main_give_one_finding_per_alert_on_any_page_split(
    tmp_path: Path,
) -> None:
    alerts = parse_dependabot_alerts(ALERTS / "gh-2.67.0-main.json")
    found = [(a.finding.finding_id, a.finding.severity, a.finding.package) for a in alerts]
    assert found == [(TAURI, "MEDIUM", "rust:tauri"), *[(VITEST, "MEDIUM", "npm:vitest")] * 7]
    assert alerts[0].finding.detail == (
        f"alert 55, rust:tauri in {CARGO}: Tauri has an Origin Confusion Issue that Allows Remote "
        "Pages to Invoke Local-Only IPC Commands"
    )
    (page,) = json.loads(RECORDED)
    split = tmp_path / "alerts.json"
    split.write_text(json.dumps([page[:3], page[3:], []]), encoding="utf-8")
    assert parse_dependabot_alerts(split) == alerts


NOT_FOUND = (ALERTS / "gh-2.67.0-not-found.json").read_text(encoding="utf-8")
NO_READ = '[{"message":"Resource not accessible by integration","status":"403"}]'


def _edited(change: Callable[[dict[str, Any]], object]) -> str:
    alert = _alert(37, "medium")
    change(alert)
    return json.dumps([[alert]])


UNREADABLE = {
    "": "is empty: the alerts API call wrote nothing",
    "[[": "is not JSON: ",
    NOT_FOUND: f"is not a list of pages of alerts: {NOT_FOUND}",
    NO_READ: f"is not a list of pages of alerts: {NO_READ}",
    "[]": "is not a list of pages of alerts: []",
    _edited(lambda a: a.update(state="dismissed")): "alert 37 is 'dismissed': the step lists ",
    _edited(lambda a: a.update(number="37")): "has an alert without a number",
    _edited(lambda a: a["security_advisory"].update(severity="moderate")): "alert 37 has no known",
    _edited(lambda a: a["security_advisory"].pop("ghsa_id")): "alert 37 has no GHSA id",
    _edited(lambda a: a["dependency"].pop("manifest_path")): "alert 37 has no package ecosystem",
    _edited(lambda a: a["dependency"].update(manifest_path="../package.json")): (
        "alert 37's manifest '../package.json' is not a path in the repo"
    ),
}


@pytest.mark.parametrize("body", sorted(UNREADABLE))
def test_listing_that_is_not_pages_of_open_complete_alerts_raises_ci_sec_005(
    tmp_path: Path, body: str
) -> None:
    report = tmp_path / "alerts.json"
    report.write_text(body, encoding="utf-8")
    with pytest.raises(SecurityGateError) as exc_info:
        parse_dependabot_alerts(report)
    assert exc_info.value.code == "CI-SEC-005"
    assert exc_info.value.message.startswith(f"dependabot: {report} {UNREADABLE[body]}")


def test_a_dependabot_entry_covers_no_other_tools_finding() -> None:
    # One way only: an alert takes its GHSA's entry whatever the entry's tool (register ids are
    # unique), but a finding pnpm reports still needs an entry of its own tool.
    risk = AcceptedRisk(TAURI, "dependabot", "HIGH", "why", "basiltt", date(2099, 1, 1))
    finding = Finding(tool="npm-audit", finding_id=TAURI, severity="HIGH", package="x")
    result = evaluate_findings([finding], [risk], run_date=date(2026, 10, 19))
    assert (result.blocked, result.code) == (True, "CI-SEC-001")


def test_the_repositorys_own_lockfiles_parse() -> None:
    # Each name is read from its lock, so no dependency change elsewhere breaks this test.
    pnpm = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")  # two YAML documents
    key = str(next(iter(list(yaml.safe_load_all(pnpm))[-1]["packages"])))
    assert resolved_versions("pnpm-lock.yaml", "npm", key[: key.index("@", 1)], pnpm)
    uv = (ROOT / "services/api/uv.lock").read_text(encoding="utf-8")
    name = tomllib.loads(uv)["package"][0]["name"]
    assert resolved_versions("services/api/uv.lock", "pip", name, uv)


def test_requirement_without_a_specifier_takes_none_from_the_next_line() -> None:
    text = "PyYAML\nrequests==2.32.4\nidna == 3.10 ; python_version >= '3.12'\n"
    assert resolved_versions(REQS, "pip", "pyyaml", text) == frozenset({""})
    assert resolved_versions(REQS, "pip", "idna", text) == frozenset({"==3.10"})


@pytest.mark.parametrize("name", sorted(p.name for p in ALERTS.glob("*.json")))
def test_dependabot_alert_fixtures_keep_ghs_own_formatting(name: str) -> None:
    # gh writes compact JSON with no final newline; .prettierignore keeps it so.
    raw = (ALERTS / name).read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), separators=(",", ":"), ensure_ascii=False)


GH_ARGS = "api --paginate --slurp repos/o/r/dependabot/alerts?state=open&per_page=100"
PLANTED = json.dumps([[_alert(37, "critical")]])
WORKFLOWS = ROOT / ".github" / "workflows"
JOBS: dict[str, Any] = yaml.safe_load((WORKFLOWS / "pr.yml").read_text(encoding="utf-8"))["jobs"]
GATE_INSTALL = "python -I -m pip install --require-hashes --only-binary=:all: --no-deps -r "


def test_alerts_job_alone_reads_the_alerts_and_installs_only_the_gates_wheel() -> None:
    # Every PR and merge group, a docs-only one too: the alerts describe `main`, not the PR's
    # paths. Only this job's token reads them, and no PR package is installed or run beside it.
    job = JOBS["dependabot-alerts"]
    assert job["permissions"] == {"contents": "read", "vulnerability-alerts": "read"}
    assert ("if" in job, "needs" in job) == (False, False)
    checkout, setup, install, step = job["steps"]
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    # The CPython whose wheel tools/ci/requirements-security-gate.txt pins by hash, as codeql's.
    version = yaml.safe_load((WORKFLOWS / "_job-security.yml").read_text("utf-8"))["env"]
    assert (setup["uses"].split("@")[0], setup["with"]) == (
        "actions/setup-python",
        {"python-version": version["PYTHON_VERSION"]},
    )
    assert install["run"] == GATE_INSTALL + "tools/ci/requirements-security-gate.txt"
    assert set(install) == {"name", "run"}
    assert (step["id"], step["env"]) == ("dependabot-alerts", {"GH_TOKEN": "${{ github.token }}"})
    # No other job, in this workflow or another, holds the read.
    assert "vulnerability-alerts" not in json.dumps({**JOBS, "dependabot-alerts": None})
    held = [
        p.name for p in WORKFLOWS.glob("*.yml") if "vulnerability-alerts" in p.read_text("utf-8")
    ]
    assert held == ["pr.yml"]


def _step(tmp_path: Path, listing: str, status: int, *prs: Files, main: bool = True) -> Any:
    """The dependabot-alerts step as the runner runs it (`bash -e`) in the job's checkout, with a
    stand-in `gh` that prints `listing` and exits with `status`, as gh does."""
    step = JOBS["dependabot-alerts"]["steps"][-1]
    repo, _ = _checkout(tmp_path, MAIN, *prs)
    if not main:
        _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    (repo / "tools").symlink_to(ROOT / "tools")  # untracked: after the commits
    (tmp_path / "listing.json").write_text(listing, encoding="utf-8")
    gh, python = tmp_path / "bin" / "gh", tmp_path / "bin" / "python"
    gh.parent.mkdir()
    gh.write_text(
        f'#!/bin/sh\n[ "$*" = "{GH_ARGS}" ] || exit 99\ncat ../listing.json\nexit {status}\n'
    )
    # -B: no bytecode in tools/. The token stays with gh: the gate's own code never sees it.
    python.write_text(
        f'#!/bin/sh\n[ -z "${{GH_TOKEN+x}}" ] || exit 98\nexec "{sys.executable}" -B "$@"\n'
    )
    for exe in (gh, python):
        exe.chmod(0o755)
    env = GIT_ENV | {"PATH": f"{gh.parent}{os.pathsep}{os.environ['PATH']}"}
    run = ["bash", "-e", "-c", step["run"]]
    env |= {"GITHUB_REPOSITORY": "o/r", "GH_TOKEN": "stand-in"}  # as the step's env sets it
    proc = subprocess.run(run, cwd=repo, env=env, capture_output=True, timeout=120, check=False)
    return proc.returncode, proc.stdout.decode(), proc.stderr.decode()


@pytest.mark.parametrize(
    ("listing", "pr", "fixed"),
    [("[[]]", {}, None), (RECORDED, {}, None), (PLANTED, FIX, True), (PLANTED, UNRELATED, False)],
    ids=[
        "no-open-alert",
        "recorded-mediums",
        "planted-critical-fix-pr",
        "planted-critical-unrelated",
    ],
)
def test_alerts_step_judges_the_alerts_against_the_merge_base_with_main(
    tmp_path: Path, listing: str, pr: Files, fixed: bool | None
) -> None:
    rc, out, err = _step(tmp_path, listing, 0, pr)
    if fixed is None:  # none, or the recorded ones, all Medium
        assert (rc, out, err) == (0, OK, "")
    elif fixed:
        assert (rc, out, err) == (0, FIXED.format(VITEST, "CRITICAL") + OK, "")
    else:
        assert (rc, out, KEPT in err) == (1, "", True)


def test_alerts_step_counts_a_fix_queued_ahead_in_the_merge_group(tmp_path: Path) -> None:
    # A merge group's HEAD is main, the entries queued ahead and this one; its base is still the
    # merge base with main, never merge_group.base_sha (#3433), so the alert a fix ahead of this
    # entry clears does not block it.
    behind = {"pnpm-lock.yaml": FIX["pnpm-lock.yaml"].replace("tinypool@2.2.0", "tinypool@2.2.1")}
    rc, out, err = _step(tmp_path, PLANTED, 0, FIX, behind)
    assert (rc, out, err) == (0, FIXED.format(VITEST, "CRITICAL") + OK, "")


API_FAILED = (
    "CI-SEC-005: dependabot: the alerts API call failed (gh's error above): a token without "
    "vulnerability-alerts: read (GitHub may withhold it from a fork's pull request) or an "
    "API outage\n"
)


@pytest.mark.parametrize("body", [NOT_FOUND, NO_READ], ids=["api-error", "token-without-the-read"])
def test_alerts_step_fails_closed_when_the_api_call_fails(tmp_path: Path, body: str) -> None:
    # A fork's pull request may get a token without vulnerability-alerts: read: gh exits 1 on the
    # 403 as on any API error, and the step names that cause rather than passing as "no alerts".
    assert _step(tmp_path, body, 1, {}) == (1, "", API_FAILED)


def test_alerts_step_fails_closed_without_a_merge_base_with_main(tmp_path: Path) -> None:
    rc, out, err = _step(tmp_path, RECORDED, 0, {}, main=False)
    assert (rc, out) == (1, "")
    assert err.endswith(
        "CI-SEC-005: dependabot: this checkout has no merge base with origin/main\n"
    )
