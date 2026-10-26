"""E16-X02 (#494): the recorder Semgrep rules.

Each rule is one `.semgrep/cv-recorder-*.yml` file, proven on its positive (`# ruleid:`) and
negative (`# ok:`) fixture lines by tools/ci/check_semgrep_rule_tests.py, and must report zero
findings on the production tree. The planted-defect check (the ticket's "a branch that writes a
Parquet file using an unvalidated path fails the build"): a recorder module that writes Parquet
through a caller-supplied directory makes `semgrep scan --error` exit 1, and the same tree
without it exits 0. Semgrep tests skip when the binary is absent (neighbour convention:
test_e12_security_gates.py). No network: semgrep runs with --metrics=off on local files only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci.check_semgrep_rule_tests import (  # noqa: E402 - sys.path first (#494)
    actual_lines,
    check_tree,
    expected_lines,
    find_fixture,
    find_fixture_tree,
)

E16_RULES = (
    "cv-recorder-fs-write-unvalidated-path",
    "cv-recorder-archive-extract-unvalidated",
    "cv-recorder-no-subprocess",
    "cv-recorder-destructive-outside-retention",
    "cv-recorder-no-path-delete",
)
WRITE_RULE = "cv-recorder-fs-write-unvalidated-path"
PLANTED = '''"""A Parquet write through a caller-supplied directory."""
from pathlib import Path

import pyarrow.parquet as pq


async def export_symbol(table, symbol: str, archive_path: str) -> None:
    target = Path(archive_path) / f"{symbol}.parquet"
    pq.write_table(table, target)
'''
# The same defect with the unchecked path held in a local named like a registry-resolved target:
# a variable name is no proof of where the path came from.
PLANTED_RENAMED = PLANTED.replace("target", "dest")
CLEAN = '''"""A Parquet write through the registry-resolved partition directory."""
import pyarrow.parquet as pq


async def export_symbol(table, paths) -> None:
    pq.write_table(table, paths.partition_dir / "part-0000.parquet")
'''
needs_semgrep = pytest.mark.skipif(not shutil.which("semgrep"), reason="semgrep not installed")


def _rule(rule: str) -> dict[str, object]:
    (loaded,) = yaml.safe_load((ROOT / ".semgrep" / f"{rule}.yml").read_text("utf-8"))["rules"]
    assert isinstance(loaded, dict)
    return loaded


def _scan_error(rule: str, cwd: Path, *targets: str) -> subprocess.CompletedProcess[str]:
    """`semgrep scan --error` on `targets` (relative to `cwd`). Outside a git checkout Semgrep
    enumerates no files of a directory target, so each file is named (as the fixture checker)."""
    return subprocess.run(
        ["semgrep", "scan", "--metrics=off", "--quiet", "--error", "--json", "--no-git-ignore",
         "--config", str(ROOT / ".semgrep" / f"{rule}.yml"), *targets],
        capture_output=True, text=True, encoding="utf-8", check=False, cwd=cwd,
    )  # fmt: skip


def test_the_recorder_rules_are_the_five_files_of_the_pack() -> None:
    found = sorted(p.stem for p in (ROOT / ".semgrep").glob("cv-recorder-*.yml"))
    assert found == sorted(E16_RULES)


@pytest.mark.parametrize("rule", E16_RULES)
def test_rule_is_one_error_id_named_by_its_file_and_scoped_to_the_backend(rule: str) -> None:
    loaded = _rule(rule)
    meta = loaded["metadata"]
    assert isinstance(meta, dict)
    assert loaded["id"] == meta["rule-id"] == rule
    assert loaded["severity"] == "ERROR"
    assert meta["ticket"] == "E16-X02"
    assert str(meta["sr"]).startswith("SR-")
    paths = loaded["paths"]
    assert isinstance(paths, dict)
    product = [p for p in paths["include"] if not p.startswith("**/")]
    assert product and all(p.startswith("services/api/candleviewer/") for p in product)
    assert f"**/{rule}*" in paths["include"]  # the fixture is in scope where it is staged


@pytest.mark.parametrize("rule", E16_RULES)
def test_rule_fixture_has_positive_and_negative_lines(rule: str) -> None:
    tree = find_fixture_tree(rule)
    sources = list(tree.rglob("*.py")) if tree else [find_fixture(rule)]
    marks = [expected_lines(source, rule) for source in sources]
    assert any(fire for fire, _ in marks) and any(clean for _, clean in marks)


@needs_semgrep
@pytest.mark.parametrize("rule", E16_RULES)
def test_rule_fires_on_positive_and_not_on_negative(rule: str) -> None:
    rule_yaml = ROOT / ".semgrep" / f"{rule}.yml"
    tree = find_fixture_tree(rule)
    if tree is not None:
        assert check_tree(rule_yaml, rule, tree) == []
        return
    fixture = find_fixture(rule)
    must_fire, must_not = expected_lines(fixture, rule)
    hit = actual_lines(rule_yaml, fixture)
    assert must_fire <= hit
    assert not (hit & must_not)


@needs_semgrep
@pytest.mark.parametrize("rule", E16_RULES)
def test_rule_is_clean_on_production_tree(rule: str) -> None:
    proc = subprocess.run(
        ["semgrep", "scan", "--metrics=off", "--quiet", "--json",
         "--config", str(ROOT / ".semgrep" / f"{rule}.yml"), "services/api/candleviewer"],
        capture_output=True, text=True, encoding="utf-8", check=False, cwd=ROOT,
    )  # fmt: skip
    assert proc.returncode in (0, 1), proc.stderr
    data = json.loads(proc.stdout)
    assert not data["errors"], data["errors"]
    found = [(r["path"], r["start"]["line"]) for r in data["results"]]
    assert found == []


@needs_semgrep
@pytest.mark.parametrize("planted_source", [PLANTED, PLANTED_RENAMED], ids=["target", "dest"])
def test_a_planted_unvalidated_parquet_write_fails_the_scan(
    tmp_path: Path, planted_source: str
) -> None:
    recorder = tmp_path / "services" / "api" / "candleviewer" / "recorder"
    recorder.mkdir(parents=True)
    clean_file = "services/api/candleviewer/recorder/clean_export.py"
    planted_file = "services/api/candleviewer/recorder/export_hook.py"
    (tmp_path / clean_file).write_text(CLEAN, encoding="utf-8")
    clean = _scan_error(WRITE_RULE, tmp_path, clean_file)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert json.loads(clean.stdout)["paths"]["scanned"] == [clean_file]  # scanned, and quiet

    (tmp_path / planted_file).write_text(planted_source, encoding="utf-8")
    planted = _scan_error(WRITE_RULE, tmp_path, clean_file, planted_file)
    assert planted.returncode == 1, planted.stderr
    found = [(r["path"], r["start"]["line"]) for r in json.loads(planted.stdout)["results"]]
    assert found == [(planted_file, 9)]
