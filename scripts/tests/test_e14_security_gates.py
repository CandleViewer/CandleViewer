"""E14-X03 (#549): the drawings persistence rules. Each names its DR and SR ids, is scoped to the
drawings files and has a section in docs/plan/security/ci-gates-e14.md. On the production tree they
are quiet, and without `nosemgrep` fire on exactly the four reviewed exceptions of
tools/ci/drawings-exception-sites.json, each by its path and statement: a fifth unscoped statement
must be listed there (an annotation moved to another statement of its file fails the job, in the
pin or the whole-tree scan). The scan needs the
`semgrep` binary: CI's governance shards have none, so that test skips there (as
test_e12_security_gates.py), the annotations are checked against the list without it, and the
`semgrep-bandit` job runs the script. The fixtures are proven by
tools/ci/check_semgrep_rule_tests.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.ci.check_drawings_exception_sites as pin  # noqa: E402 - sys.path first (#549)
import tools.ci.security_gate as gate  # noqa: E402 - sys.path first (#549)

DOC = ROOT / "docs" / "plan" / "security" / "ci-gates-e14.md"
RULE = "cv-drawings-query-missing-owner-filter"
needs_semgrep = pytest.mark.skipif(not shutil.which("semgrep"), reason="semgrep not installed")


@pytest.mark.parametrize("rule", pin.RULES)
def test_rule_names_its_threat_rows_doc_section_and_scope(rule: str) -> None:
    (loaded,) = yaml.safe_load((ROOT / ".semgrep" / f"{rule}.yml").read_text("utf-8"))["rules"]
    meta = loaded["metadata"]
    assert loaded["id"] == meta["rule-id"] == rule
    assert loaded["severity"] == "ERROR"
    assert meta["dr"] and all(str(row).startswith("DR") for row in meta["dr"])
    assert str(meta["sr"]).startswith("SR-") and meta["references"]
    assert f"ci-gates-e14.md#{rule}" in loaded["message"]
    assert f"## {rule}\n" in DOC.read_text("utf-8")
    assert all(p.startswith("services/api/candleviewer/") for p in loaded["paths"]["include"])


@pytest.mark.parametrize(
    ("line", "named"),
    [
        ("_PURGE = sa.text(", "_PURGE"),
        ("_COUNT_LIVE: Final = sa.text(", "_COUNT_LIVE"),
        ("_Q: Final[sa.TextClause] = sa.text(", "_Q"),
        ("    await conn.execute(sa.text(", "line 7"),  # a call, not an assignment
        ("if _PURGE == sa.text(", "line 7"),
        ("_PURGE == 1", "line 7"),  # a comparison
    ],
)
def test_a_statement_is_named_by_its_assigned_constant_else_by_its_line(
    line: str, named: str
) -> None:
    assert pin.statement(line, 7) == named


def _site(path: str, name: str, rule: str = RULE) -> pin.Site:
    return (rule, path, name)


def test_the_listed_statements_pass_wherever_they_sit_in_their_files() -> None:
    listed = [_site("a.py", "_PURGE"), _site("b.py", "_COUNT")]
    assert pin.compare(listed, listed) == []
    assert pin.compare(listed[::-1], listed) == []  # the order is not the pin


def test_a_site_swapped_inside_a_file_fails_where_a_count_of_files_and_rules_passes() -> None:
    """PR-1's pin counted (file, rule) pairs: moving the annotation from one statement of a file to
    another kept the count (#4364's N5). The statement is the key now."""
    listed = [_site("a.py", "_PURGE"), _site("b.py", "_COUNT")]
    swapped = [_site("a.py", "_OTHER"), _site("b.py", "_COUNT")]
    assert Counter((r, p) for r, p, _ in swapped) == Counter((r, p) for r, p, _ in listed)
    problems = pin.compare(swapped, listed)
    assert len(problems) == 2
    assert "a.py: _OTHER:" in problems[0] and "does not: fix the statement" in problems[0]
    assert "a.py: _PURGE:" in problems[1] and "no longer reports it" in problems[1]


@pytest.mark.parametrize(
    ("found", "text"),
    [
        ([_site("a.py", "_PURGE"), _site("a.py", "_NEW")], "a.py: _NEW:"),  # a fifth site
        ([_site("a.py", "_PURGE"), _site("a.py", "line 40")], "a.py: line 40:"),
        ([_site("a.py", "_PURGE")], "b.py: _COUNT:"),  # a listed site no rule reports now
        ([_site("a.py", "_PURGE"), _site("b.py", "_COUNT", "cv-drawings-owner-from-body")], "b.py"),
        ([_site("a.py", "_PURGE")] * 2 + [_site("b.py", "_COUNT")], "a.py: _PURGE:"),  # twice
    ],
)
def test_any_other_set_of_sites_fails_naming_the_statement(
    found: list[pin.Site], text: str
) -> None:
    listed = [_site("a.py", "_PURGE"), _site("b.py", "_COUNT")]
    assert any(text in problem for problem in pin.compare(found, listed))


def test_found_sites_read_the_statement_each_result_opens(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/m.py").write_text(
        "x = 1\n_PURGE = sa.text(\n    '...'\n)\nrun(sa.text(\n", "utf-8"
    )
    results = [
        {"check_id": f"home.x.semgrep.{RULE}", "path": "pkg/m.py", "start": {"line": 2}},
        {"check_id": "a.cv-drawings-pixel-geometry", "path": "pkg/m.py", "start": {"line": 5}},
    ]
    assert pin.found_sites(results, tmp_path) == [
        ("cv-drawings-pixel-geometry", "pkg/m.py", "line 5"),
        (RULE, "pkg/m.py", "_PURGE"),
    ]


def test_the_committed_list_names_four_statements_each_with_its_reviewed_annotation() -> None:
    listed = pin.load_sites(ROOT / pin.SITES)
    assert len(listed) == 4 and {rule for rule, _, _ in listed} == {RULE}
    assert (RULE, "services/api/candleviewer/storage/repositories/workspaces_sqlalchemy.py",
            "_PURGE_LAYOUTS") in listed  # fmt: skip
    annotated = []
    for path in sorted((ROOT / pin.TARGET).rglob("*.py")):
        lines = path.read_text("utf-8").splitlines()
        for number, line in enumerate(lines[:-1], start=1):
            if f"nosemgrep: {RULE} " in line:
                rel = path.relative_to(ROOT).as_posix()
                annotated.append((RULE, rel, pin.statement(lines[number], number + 1)))
    assert sorted(annotated) == listed


@needs_semgrep
def test_the_reviewed_exceptions_are_exactly_the_listed_statements() -> None:
    """The CI step, run here: the five rules with `nosemgrep` disabled over the service."""
    found = pin.found_sites(pin.scan(ROOT), ROOT)
    assert pin.compare(found, pin.load_sites(ROOT / pin.SITES)) == []


@pytest.mark.parametrize(
    ("names", "listed", "code", "text"),
    [
        (["_PURGE"], ["_PURGE"], 0, "OK: 1 reviewed exception site"),
        (["_PURGE", "_NEW"], ["_PURGE"], 1, "_NEW"),
        (["_PURGE"], ["_PURGE", "_GONE"], 1, "_GONE"),
    ],
)
def test_main_exits_0_when_the_scan_matches_the_list_and_1_when_it_does_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    names: list[str],
    listed: list[str],
    code: int,
    text: str,
) -> None:
    (tmp_path / "m.py").write_text("".join(f"{n} = 1\n" for n in names), "utf-8")
    results = [
        {"check_id": RULE, "path": "m.py", "start": {"line": i}} for i, _ in enumerate(names, 1)
    ]
    monkeypatch.setattr(pin, "scan", lambda root: results)
    sites = tmp_path / "sites.json"
    sites.write_text(
        json.dumps({"rule": RULE, "sites": [{"path": "m.py", "statement": n} for n in listed]})
    )
    assert pin.main(["--root", str(tmp_path), "--sites", str(sites)]) == code
    captured = capsys.readouterr()
    assert text in captured.out + captured.err


def _scanned(errors: list[object] | None = None, **paths: object) -> object:
    """`subprocess.run` answering Semgrep's `--json --verbose` report with `paths` and `errors`."""
    report = json.dumps({"errors": errors or [], "results": [], "paths": paths})
    return lambda *a, **k: subprocess.CompletedProcess(a, 0, report, "")


@pytest.mark.parametrize(
    "failure",
    [
        "no semgrep",
        "bad list",
        "semgrep failed",
        "a result past the file",
        "nothing scanned",
        "a target left unread",
        "no skipped list",
        "semgrep reported errors",
    ],
)
def test_main_exits_2_when_the_scan_or_the_list_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    sites = tmp_path / "sites.json"
    sites.write_text("{}" if failure == "bad list" else json.dumps({"rule": RULE, "sites": []}))
    if failure == "no semgrep":
        monkeypatch.setenv("PATH", str(tmp_path))  # no `semgrep` on it: FileNotFoundError
    if failure == "a result past the file":  # a stale line: fail, never a traceback
        (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
        stale = [{"check_id": RULE, "path": "m.py", "start": {"line": 9}}]
        monkeypatch.setattr(pin, "scan", lambda root: stale)
    if failure == "semgrep failed":
        monkeypatch.setattr(
            pin.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 7, "", "boom")
        )
    if failure == "nothing scanned":  # a wrong root: Semgrep matches no target and says so
        monkeypatch.setattr(pin.subprocess, "run", _scanned(scanned=[], skipped=[]))
    if failure == "semgrep reported errors":  # a rule or a target Semgrep could not run
        error = {"type": "Rule parse error", "message": "bad pattern"}
        monkeypatch.setattr(pin.subprocess, "run", _scanned([error], scanned=["a.py"], skipped=[]))
    if failure == "no skipped list":  # no --verbose: a skipped target would go unseen
        monkeypatch.setattr(pin.subprocess, "run", _scanned(scanned=["a.py"]))
    if failure == "a target left unread":  # a file over the size cap, unread, sites unseen
        big = {"path": "services/api/candleviewer/big.py", "reason": "exceeded_size_limit"}
        monkeypatch.setattr(pin.subprocess, "run", _scanned(scanned=["a.py"], skipped=[big]))
    assert pin.main(["--root", str(tmp_path), "--sites", str(sites)]) == 2


def test_a_skip_configuration_explains_does_not_fail_the_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ignored = {"path": "services/api/candleviewer/x.py", "reason": "semgrepignore_patterns_match"}
    monkeypatch.setattr(pin.subprocess, "run", _scanned(scanned=["a.py"], skipped=[ignored]))
    assert pin.scan(ROOT) == []


def test_the_pin_scans_the_five_persistence_rules() -> None:
    assert pin.RULES == (
        "cv-drawings-query-missing-owner-filter",
        "cv-drawings-owner-from-body",
        "cv-drawings-unbounded-geometry",
        "cv-drawings-batch-unvalidated-ids",
        "cv-drawings-pixel-geometry",
    )


def test_a_site_listed_twice_and_found_once_is_named() -> None:
    listed = [_site("a.py", "_PURGE")] * 2 + [_site("b.py", "_COUNT")]
    found = [_site("a.py", "_PURGE"), _site("b.py", "_COUNT")]
    gone = f"listed in {pin.SITES}, but {RULE} no longer reports it: remove it from there"
    assert pin.compare(found, listed) == [f"a.py: _PURGE: {gone}"]


def test_the_configured_skips_are_the_security_gates() -> None:
    assert pin.CONFIGURED_SKIPS == gate._CONFIGURED_SKIPS
