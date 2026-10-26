"""#4605: the merge queue's Postgres/QuestDB integration suite runs in shards; `integration` judges.

The suite step of `_job-integration.yml` grew to 18-28 minutes in one job against a 30-minute hang
guard, and a cancel at 30:00 ejected a PR from the queue. `integration-shard` now runs it in a
matrix split by measured per-file duration (`tools/ci/integration_shards.py`), `integration-stack`
runs what must run once (the fixture pipeline, the SR-047 probe, storage chaos, the Grafana render
suite) beside them, and `integration`, the check `ci-required` reads, fails unless all of them
passed. These tests pin that nothing falls out of the shards (every file pytest collects from
`tests/integration` lands in exactly one, a new file too), that the split follows the weight
table, that the report files run in the shard that uploads their report, the per-shard summary,
and each job's own timeout.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.ci import governance_shards as gs  # noqa: E402 - the repo root is on sys.path above
from tools.ci import integration_shards as ints  # noqa: E402 - the repo root is on sys.path above

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "_job-integration.yml"
SUITE_MARKERS = '-m "integration and not perf and not flaky" --no-cov -rA'
PR_SKIP = "${{ github.event_name != 'pull_request' }}"


def _jobs() -> dict[str, Any]:
    jobs: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return jobs


def _runs(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def _total() -> int:
    total: int = _jobs()["integration-shard"]["strategy"]["matrix"]["total"][0]
    return total


def _load(files: list[str]) -> float:
    return sum(ints.WEIGHTS.get(name, ints.DEFAULT_WEIGHT) for name in files)


def test_every_collected_integration_test_file_lands_in_exactly_one_shard() -> None:
    files = ints.suite_files()
    parts = ints.split(files, _total())
    assert len(parts) == _total() and all(parts)
    flat = [name for part in parts for name in part]
    assert len(flat) == len(set(flat))  # disjoint
    assert sorted(flat) == files  # exhaustive
    assert ints.split(files, _total()) == parts  # deterministic
    assert "tests/integration/storage/test_restore_drill.py" in files


def test_a_new_file_the_table_does_not_know_still_lands_in_one_shard() -> None:
    new = ["tests/integration/zz/test_brand_new_pg.py", "tests/integration/aa/test_other_pg.py"]
    files = sorted([*ints.suite_files(), *new])
    parts = ints.split(files, _total())
    assert sorted(name for part in parts for name in part) == files
    for name in new:
        assert sum(name in part for part in parts) == 1


def test_the_suite_files_are_exactly_the_files_pytest_collects(tmp_path: Path) -> None:
    # The old step ran `pytest tests/integration` from services/api; a file the shards missed
    # would never run. Real pytest, the real pyproject (addopts off: its coverage floor would
    # fail an empty tree), a tiny tree.
    wanted = [
        "tests/integration/test_top.py",
        "tests/integration/storage/test_store_pg.py",
        "tests/integration/deep/er/suffix_test.py",
    ]
    ignored = [
        "tests/integration/.hidden/test_dot.py",
        "tests/integration/__pycache__/test_cache.py",
        "tests/integration/_helper.py",
        "tests/integration/conftest.py",
    ]
    for name in [*wanted, *ignored]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_ok():\n    pass\n", encoding="utf-8")
    pyproject = (ints.API_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
        + ["-o", "addopts=", ints.SUITE],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_ADDOPTS": ""},
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    collected = {line.split("::")[0] for line in run.stdout.splitlines() if "::" in line}
    assert collected == set(wanted) == set(ints.suite_files(tmp_path))


def test_the_split_is_balanced_by_the_measured_weights() -> None:
    loads = [_load(part) for part in ints.split(ints.suite_files(), _total())]
    # Greedy, heaviest first: the shards differ by at most the heaviest single file.
    assert max(loads) - min(loads) <= max(ints.WEIGHTS.values())


def test_the_weight_table_is_measured_seconds_with_a_median_default() -> None:
    assert set(ints.WEIGHTS) <= set(ints.suite_files())  # a renamed heavy file would go unweighed
    assert all(weight >= 0.5 for weight in ints.WEIGHTS.values())
    assert len(ints.WEIGHTS) >= 100
    ordered = sorted(ints.WEIGHTS.values())
    quarter = len(ordered) // 4
    assert ordered[quarter] <= ints.DEFAULT_WEIGHT <= ordered[-quarter]
    doc = " ".join((ints.__doc__ or "").split())
    for run in ("40314689824", "40313441542", "40311572348", "40309804896", "40309420588"):
        assert run in doc, run  # the source runs are cited


def test_the_report_files_run_in_the_shard_that_uploads_their_report() -> None:
    shard = _jobs()["integration-shard"]
    uploads = {
        step["with"]["name"]: step
        for step in shard["steps"]
        if "upload-artifact" in step.get("uses", "")
    }
    reports = {
        "tests/integration/storage/test_restore_drill.py": ("restore-drill-report", "error"),
        "tests/integration/storage/test_storage_perf_harness.py": ("storage-perf", "warn"),
    }
    assert set(ints.PINNED) == set(reports)
    parts = ints.split(ints.suite_files(), _total())
    for name, (artifact, missing) in reports.items():
        index = ints.PINNED[name][0]
        assert name in parts[index - 1]
        step = uploads[artifact]
        assert step["if"] == f"${{{{ always() && matrix.shard == {index} }}}}"
        assert step["with"]["if-no-files-found"] == missing
        assert Path(step["with"]["path"]).name in (ints.API_ROOT / name).read_text(encoding="utf-8")


def test_a_pin_outside_the_shards_is_refused() -> None:
    with pytest.raises(ValueError):
        gs.shards(["a", "b"], 2, pinned={"a": 3})
    assert gs.shards(["a", "b", "c"], 2, weights={"c": 9.0}, pinned={"a": 2}) == [["c"], ["a", "b"]]


def test_integration_runs_shards_a_stack_job_and_a_judge() -> None:
    jobs = _jobs()
    assert list(jobs) == [
        "integration-shard",
        "integration-stack",
        "integration",
        "audit-query-plan",
    ]
    shard = jobs["integration-shard"]
    assert shard["strategy"] == {
        "fail-fast": False,
        "matrix": {"shard": list(range(1, _total() + 1)), "total": [4]},
    }
    assert shard["name"] == "integration-shard (${{ matrix.shard }}/${{ matrix.total }})"
    assert shard["if"] == jobs["integration-stack"]["if"] == PR_SKIP
    runs = _runs(shard)
    assert 'integration_shards.py "$SHARD" "$TOTAL"' in runs
    assert f'uv run pytest "${{files[@]}}" {SUITE_MARKERS} || status=$?' in runs
    assert 'exit "$status"' in runs
    judge = jobs["integration"]
    assert judge["name"] == "integration"  # the check `ci-required` reads keeps its name
    assert judge["needs"] == ["integration-shard", "integration-stack"]
    assert judge["if"] == "${{ github.event_name != 'pull_request' && !cancelled() }}"
    verdict = next(
        s for s in judge["steps"] if s.get("name") == "Every shard and the stack job passed"
    )
    assert verdict["if"] == "always()"
    assert verdict["env"] == {
        "SHARDS": "${{ needs.integration-shard.result }}",
        "STACK": "${{ needs.integration-stack.result }}",
    }
    assert '[ "$SHARDS" = success ] && [ "$STACK" = success ]' in verdict["run"]


def test_what_runs_once_runs_in_the_stack_job_only() -> None:
    jobs = _jobs()
    stack, shard = _runs(jobs["integration-stack"]), _runs(jobs["integration-shard"])
    once = [
        "verify_fixture_manifest.py",
        "uv run pytest tests/integration/pipeline",
        "tests/integration/security/test_sr047_listener_probe.py",
        'uv run pytest tests/chaos -m "chaos and integration and not flaky"',
        "tests/chaos/storage/test_stack_scenarios.py",
        "infra/grafana/tests/test_live_render.py",
    ]
    for command in once:
        assert command in stack and command not in shard, command
        assert command not in _runs(jobs["integration"]), command


def test_each_shard_reports_its_duration_and_the_judge_tabulates_them() -> None:
    jobs = _jobs()
    steps = jobs["integration-shard"]["steps"]
    assert steps[0]["id"] == "start" and "start_s=" in steps[0]["run"]
    pytest_step = next(s for s in steps if s.get("id") == "pytest")
    assert "pytest_s=" in pytest_step["run"] and "GITHUB_OUTPUT" in pytest_step["run"]
    summary, upload = steps[-2], steps[-1]
    assert summary["if"] == upload["if"] == "always()"
    assert summary["env"]["PYTEST_S"] == "${{ steps.pytest.outputs.pytest_s }}"
    assert 'echo "$row" > "shard-timing/shard-${SHARD}.md"' in summary["run"]
    assert "GITHUB_STEP_SUMMARY" in summary["run"]
    assert upload["with"]["name"] == "integration-shard-timing-${{ matrix.shard }}"
    assert upload["with"]["path"] == "shard-timing/shard-${{ matrix.shard }}.md"
    judge = jobs["integration"]["steps"]
    assert judge[0]["with"]["pattern"] == "integration-shard-timing-*"
    table = next(s for s in judge if s.get("name") == "Per-shard durations (job summary)")
    assert '"$TIMING_DIR"/shard-*.md' in table["run"] and "GITHUB_STEP_SUMMARY" in table["run"]


def test_each_job_sets_its_own_timeout_from_the_measured_durations() -> None:
    jobs = _jobs()
    # The heaviest shard at the slowest measured run's pace, plus the job's overhead, plus 10.
    assert jobs["integration-shard"]["timeout-minutes"] == ints.timeout_minutes(_total()) == 19
    assert jobs["integration-stack"]["timeout-minutes"] == 13  # about 3 minutes measured, plus 10
    assert jobs["integration"]["timeout-minutes"] == 5
    assert all("vars." not in str(job["timeout-minutes"]) for job in jobs.values())


def test_the_cli_prints_one_shard_and_refuses_a_bad_index(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ints.main(["2", "4"]) == 0
    assert capsys.readouterr().out.split() == ints.split(ints.suite_files(), 4)[1]
    for bad in (["0", "4"], ["5", "4"], ["x", "4"], ["1"], [], ["weigh"]):
        assert ints.main(bad) == 2, bad


def test_an_empty_shard_fails_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    only = "tests/integration/test_a.py"
    monkeypatch.setattr(ints, "suite_files", lambda api_root=ints.API_ROOT: [only])
    assert ints.main(["2", "2"]) == 1


def test_weigh_takes_the_median_per_file_over_the_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def log(name: str, a: float, b: float) -> str:
        path = tmp_path / name
        path.write_text(
            "2026-10-26T11:00:00.0000000Z collected 3 items\n"
            f"2026-10-26T11:00:{a:09.6f}0Z tests/integration/test_a.py ..   [ 50%]\n"
            f"2026-10-26T11:00:{a + b:09.6f}0Z tests/integration/test_b.py .   [100%]\n",
            encoding="utf-8",
        )
        return str(path)

    logs = [log("1.log", 10, 2), log("2.log", 20, 4), log("3.log", 30, 6)]
    assert ints.weigh(logs) == {
        "tests/integration/test_a.py": 20.0,
        "tests/integration/test_b.py": 4.0,
    }
    assert ints.main(["weigh", *logs]) == 0
    assert capsys.readouterr().out.splitlines() == [
        '    "tests/integration/test_a.py": 20.0,',
        '    "tests/integration/test_b.py": 4.0,',
    ]
