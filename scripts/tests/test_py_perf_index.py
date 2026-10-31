"""#5193: `py-perf` runs in shards of a committed perf-test index, and no perf test is lost.

`tools/ci/py-perf-index.json` lists the node ids `pytest -m "perf and not flaky"` collects from
services/api, with the measured seconds of each test file; `tools/ci/py_perf_index.py` splits them
into the `py-perf (N/3)` matrix of `.github/workflows/_job-py.yml`, and `py-perf-index` checks the
index against a live collection on every run. These tests pin that the index equals the live
collection (the drift test), that the shards partition the index (a new file too), that the split
follows the weights, that every shard is expected well under 10 minutes, and the workflow's shape:
its matrix, its selection flags and the hang guard the script computes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.ci import py_perf_index as ppi  # noqa: E402 - the repo root is on sys.path above

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "_job-py.yml"
API_PYTHON = ppi.API_ROOT / ".venv" / "bin" / "python"
SELECTION = '-m "perf and not flaky" --no-cov -p no:cacheprovider -p no:randomly --durations=0'


def _jobs() -> dict[str, Any]:
    jobs: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return jobs


def _total() -> int:
    total: int = _jobs()["py-perf"]["strategy"]["matrix"]["total"][0]
    return total


def _runs(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


@pytest.mark.skipif(
    not API_PYTHON.exists(),
    reason="needs services/api's synced environment (uv sync) and about 5 minutes; CI runs the "
    "same check in _job-py.yml's py-perf-index job",
)
def test_the_index_equals_the_live_perf_collection() -> None:
    """The drift test: a perf test the index misses would run in no shard."""
    problem = ppi.drift(ppi.load(), ppi.collect([str(API_PYTHON)]))
    assert problem == "", problem


def test_drift_names_each_missing_and_stale_test_and_how_to_regenerate() -> None:
    index = ppi.Index(ppi.MARKER, ("tests/a/test_x.py::t1", "tests/a/test_y.py::t2"), {}, 1.0)
    assert ppi.drift(index, list(index.tests)) == ""
    problem = ppi.drift(index, ["tests/a/test_x.py::t1", "tests/b/test_new.py::t3[p 1]"])
    assert "not in the index: tests/b/test_new.py::t3[p 1]" in problem
    assert "no longer collected: tests/a/test_y.py::t2" in problem
    assert ppi.REGENERATE in problem and "py_perf_index.py write" in ppi.REGENERATE


def test_the_index_is_the_perf_selection_sorted_and_weighted() -> None:
    index = ppi.load()
    assert index.marker == "perf and not flaky"
    assert len(index.tests) >= 150 and list(index.tests) == sorted(set(index.tests))
    assert set(index.weights) == set(index.files)  # every indexed file was timed
    # The three heaviest tests of run 41171217151 (job 124449801043), with their files.
    heavy = {
        "tests/unit/auth/test_login_timing_enumeration.py": 110,
        "tests/unit/accounts/test_sizer_perf.py": 75,
        "tests/security/auth/test_credential_abuse.py": 57,
    }
    for name, seconds in heavy.items():
        assert index.weights[name] >= seconds, name
    doc = " ".join((ppi.__doc__ or "").split())
    assert "124449801043" in doc and "41171217151" in doc  # the weights cite their source


def test_the_shards_partition_the_index_by_whole_files() -> None:
    index = ppi.load()
    parts = ppi.split(index, _total())
    assert len(parts) == _total() and all(parts)
    flat = [test for part in parts for test in part]
    assert len(flat) == len(set(flat))  # disjoint
    assert sorted(flat) == list(index.tests)  # exhaustive: the union is the index
    owners = [{ppi.file_of(t) for t in part} for part in parts]
    assert sum(len(files) for files in owners) == len(index.files)  # no file split


def test_a_new_perf_file_lands_in_exactly_one_shard_at_the_default_weight() -> None:
    index = ppi.load()
    new = "tests/unit/zz_new/test_new_perf.py::test_budget[a b]"
    grown = ppi.Index(index.marker, (*index.tests, new), index.weights, index.default_weight)
    parts = ppi.split(grown, _total())
    assert sum(part.count(new) for part in parts) == 1
    assert sorted(t for part in parts for t in part) == sorted(grown.tests)
    assert grown.weight("tests/unit/zz_new/test_new_perf.py") == index.default_weight > 0


def test_the_split_balances_the_measured_weights() -> None:
    index = ppi.load()
    loads = [ppi.shard_seconds(index, part) for part in ppi.split(index, _total())]
    heaviest_file = max(index.weights.values())
    # Greedy, heaviest first: no shard is more than the heaviest file above the lightest.
    assert max(loads) - min(loads) <= heaviest_file
    assert abs(sum(loads) - sum(index.weight(f) for f in index.files)) < 1e-6


def test_every_shard_is_expected_well_under_ten_minutes() -> None:
    """#5193's acceptance: each shard < 10 min at p95 (the weights are the slowest measured run)."""
    expected = ppi.expected_seconds(ppi.load(), _total())
    assert all(seconds < 8 * 60 for seconds in expected), expected


def test_py_perf_is_a_matrix_of_index_shards_with_the_lane_flags() -> None:
    jobs = _jobs()
    shard = jobs["py-perf"]
    assert shard["name"] == "py-perf (${{ matrix.shard }}/${{ matrix.total }})"
    assert shard["strategy"] == {
        "fail-fast": False,
        "matrix": {"shard": list(range(1, _total() + 1)), "total": [3]},
    }
    runs = _runs(shard)
    assert 'python ../../tools/ci/py_perf_index.py shard "$SHARD" "$TOTAL"' in runs
    assert f'uv run pytest "${{ids[@]}}" {SELECTION}' in runs
    assert "set -euo pipefail" in runs
    check = jobs["py-perf-index"]
    assert check["name"] == "py-perf-index"
    assert "uv run python ../../tools/ci/py_perf_index.py check" in _runs(check)


def test_each_shard_sets_the_hang_guard_the_script_computes() -> None:
    jobs = _jobs()
    index = ppi.load()
    minutes = ppi.timeout_minutes(index, _total())
    assert jobs["py-perf"]["timeout-minutes"] == minutes
    heaviest = max(ppi.expected_seconds(index, _total()))
    assert minutes * 60 >= heaviest * ppi.TIMEOUT_FACTOR  # at least 1.5x the expected p95
    assert minutes * 60 >= heaviest + ppi.PREPULL_WORST_S  # a worst-case pre-pull still fits
    assert isinstance(jobs["py-perf-index"]["timeout-minutes"], int)


def test_parse_collection_keeps_node_ids_only() -> None:
    out = "tests/a/test_x.py::t[1 2]\ntests/a/test_x.py::t0\n\n3/9 tests collected in 1.0s\n"
    assert ppi.parse_collection(out) == [
        "tests/a/test_x.py::t0",
        "tests/a/test_x.py::t[1 2]",
    ]


def test_log_weights_sums_each_files_phases_and_refuses_a_log_without_durations() -> None:
    log = (
        "2026-10-31T05:30:01.3632288Z ===== slowest durations =====\n"
        "2026-10-31T05:30:01.3633351Z 110.11s call     tests/a/test_x.py::t[a b]\n"
        "2026-10-31T05:30:01.3633351Z 0.50s setup    tests/a/test_x.py::t[a b]\n"
        "2026-10-31T05:30:01.3633351Z 2.00s teardown tests/b/test_y.py::u\n"
        "(336 durations < 0.005s hidden.  Use -vv to show these durations.)\n"
    )
    assert ppi.log_weights(log) == pytest.approx(
        {"tests/a/test_x.py": 110.61, "tests/b/test_y.py": 2.0}
    )
    with pytest.raises(ppi.PerfIndexError):
        ppi.log_weights("no report here")


def test_load_refuses_a_malformed_index(tmp_path: Path) -> None:
    bad = tmp_path / "index.json"
    for text in (
        "{",
        '{"marker": "perf", "tests": [], "weights": {}, "default_weight": 1}',
        json.dumps(
            {
                "marker": "perf and not flaky",
                "tests": ["tests/b/test_b.py::x", "tests/a/test_a.py::y"],  # unsorted
                "weights": {},
                "default_weight": 1,
            }
        ),
        '{"marker": "perf and not flaky", "tests": [], "weights": {}, "default_weight": 0}',
    ):
        bad.write_text(text, encoding="utf-8")
        with pytest.raises(ppi.PerfIndexError):
            ppi.load(bad)


def test_the_cli_prints_one_shard_and_refuses_bad_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ppi.main(["shard", "2", "3"]) == 0
    assert capsys.readouterr().out.splitlines() == ppi.split(ppi.load(), 3)[1]
    assert ppi.main(["plan", "3"]) == 0
    assert "timeout-minutes:" in capsys.readouterr().out
    for bad in (
        ["shard", "0", "3"],
        ["shard", "4", "3"],
        ["shard", "x", "3"],
        ["plan"],
        [],
        ["x"],
    ):
        assert ppi.main(bad) == 2, bad
