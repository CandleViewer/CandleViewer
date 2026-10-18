"""#2424: the services/api pytest lanes of the `py` CI job cover every test file exactly once.

`tools/ci/py-test-lanes.json` splits the suite that `.github/workflows/_job-py.yml` used to run in
one job. A test file that no lane runs would drop out of CI without a red check, and one that two
lanes run wastes runner time, so these tests pin the partition, the workflow matrix and the
combined-coverage wiring (the floor moves from each lane to the combined data, never away).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci.py_test_lanes import (  # noqa: E402 - the repo root must be importable first
    DATA_FILE_TEMPLATE,
    LaneManifestError,
    check,
    collects,
    data_files,
    fail_under,
    load_manifest,
    main,
    partition_problems,
    pytest_args,
    suite_files,
)

API_ROOT = ROOT / "services" / "api"
WORKFLOW = ROOT / ".github" / "workflows" / "_job-py.yml"


def _jobs() -> dict[str, Any]:
    jobs: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return jobs


def _runs(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def _pytest_calls(run: str) -> list[list[str]]:
    """The arguments of each pytest call in a step's script. Continuation lines are joined and each
    line is split at the shell's control operators, so `pytest a && pytest b` is two calls."""
    calls: list[list[str]] = []
    for line in run.replace("\\\n", " ").splitlines():
        if "pytest" not in line:
            continue
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)  # drops `#` comments
        lexer.whitespace_split = True
        command: list[str] = []
        for word in [*lexer, ";"]:
            core = word.strip("()")  # a subshell or a `$(...)` stays inside its command
            if not core or core.strip(";&|"):
                command.append(word)
                continue
            names = [Path(each).name for each in command]  # `pytest`, `.venv/bin/pytest`
            if "pytest" in names:
                calls.append(command[names.index("pytest") + 1 :])
            command = []
    return calls


def _marker_expressions(args: list[str]) -> list[str]:
    """Every marker expression of a pytest call, in each spelling (`-m X`, `-mX`, `--markexpr X`,
    `--markexpr=X`). pytest applies the last one, so the pin checks them all."""
    found: list[str] = []
    for arg, following in zip(args, [*args[1:], ""], strict=True):
        if arg in ("-m", "--markexpr"):
            found.append(following)
        elif arg.startswith("--markexpr="):
            found.append(arg.removeprefix("--markexpr="))
        elif arg.startswith("-m"):
            found.append(arg.removeprefix("-m"))
    return found


def _leaves_flaky_out(expression: str) -> bool:
    """True when `not flaky` is an operand of the expression's outermost `and`: pytest then
    deselects every `flaky` test, whatever its other marks."""
    top = expression
    while (flat := re.sub(r"\([^()]*\)", " group ", top)) != top:  # drop parenthesised groups
        top = flat
    top = " ".join(top.split())  # pytest splits words at parentheses as well as at spaces
    return " or " not in top and "not flaky" in top.split(" and ")


def _keeps_flaky_out(args: list[str]) -> bool:
    """A pytest call deselects `flaky` tests. With no marker expression it runs the pyproject
    addopts selection, which keeps them."""
    expressions = _marker_expressions(args)
    return bool(expressions) and all(_leaves_flaky_out(each) for each in expressions)


def _fake_api(tmp_path: Path, files: list[str]) -> Path:
    api = tmp_path / "api"
    for relative in files:
        path = api / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_x() -> None:\n    pass\n", encoding="utf-8")
    return api


def _manifest(tmp_path: Path, lanes: dict[str, list[str]], rest: str = "rest") -> Path:
    path = tmp_path / "lanes.json"
    path.write_text(json.dumps({"rest_lane": rest, "lanes": lanes}), encoding="utf-8")
    return path


# --- the committed manifest against the real suite ---------------------------------------------


def test_every_services_api_test_file_runs_in_exactly_one_lane() -> None:
    manifest = load_manifest()
    assert check(manifest, API_ROOT) == []
    files = suite_files(API_ROOT)
    assert len(files) > 500, "suite_files found too few test modules; is the glob broken?"
    lane_args = {lane: pytest_args(manifest, lane) for lane in manifest.names}
    for test_file in files:
        assert sum(collects(args, test_file) for args in lane_args.values()) == 1, test_file
    assert lane_args[manifest.rest_lane] == [
        "tests",
        *(f"--ignore={p}" for p in manifest.listed_paths),
    ]
    # suite_files assumes pytest's default python_files; a configured pattern would need it too.
    pyproject = tomllib.loads((API_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "python_files" not in pyproject["tool"]["pytest"]["ini_options"]


def test_workflow_matrix_names_the_manifest_lanes_in_order() -> None:
    lanes = _jobs()["py-tests"]["strategy"]["matrix"]["lane"]
    assert lanes == load_manifest().names
    for name, job in _jobs().items():
        assert "timeout-minutes" in job, name


def test_each_lane_runs_the_ci_selection_on_its_own_paths_with_coverage() -> None:
    job = _jobs()["py-tests"]
    assert job["strategy"]["fail-fast"] is False
    assert job["timeout-minutes"] == "${{ fromJSON(vars.CV_CI_PY_TIMEOUT_MINUTES || 30) }}"
    (step,) = [s for s in job["steps"] if "uv run pytest" in s.get("run", "")]
    assert step["env"]["HYPOTHESIS_PROFILE"] == "ci"
    run = step["run"]
    assert "py_test_lanes.py pytest-args" in run
    assert '-m "not exchange_smoke and not (chaos and integration)' in run
    for flag in ("-p no:cacheprovider", "--durations=10", "--cov ", "--cov-fail-under=0"):
        assert flag in run, flag
    (upload,) = [s for s in job["steps"] if s.get("uses", "").startswith("actions/upload-art")]
    assert upload["with"]["name"] == "py-lane-cov-${{ matrix.lane }}"
    assert upload["with"]["path"] == "services/api/" + DATA_FILE_TEMPLATE.format(
        lane="${{ matrix.lane }}"
    )


def test_no_py_job_runs_a_test_quarantined_as_flaky() -> None:
    """C-9.3 (#3091): a test quarantined with the `flaky` marker runs in no job of this required
    workflow, so a known-flaky test cannot turn the `py` check red."""
    calls = {
        name: [args for step in job["steps"] for args in _pytest_calls(step.get("run", ""))]
        for name, job in _jobs().items()
    }
    assert calls["py-tests"] and calls["py-perf"], calls  # the lane step and the perf budgets
    for name, job_calls in calls.items():
        for args in job_calls:
            assert _keeps_flaky_out(args), (name, args)


def test_py_job_combines_every_lane_and_keeps_the_floor_and_the_gate_artifact() -> None:
    jobs = _jobs()
    py = jobs["py"]
    assert set(py["needs"]) == {"py-checks", "py-tests"}
    runs = _runs(py)
    assert "py_test_lanes.py data-files lane-coverage" in runs
    assert "uv run coverage combine" in runs
    # Relative paths in the lane data: the combine must not depend on each job's checkout path.
    pyproject = tomllib.loads((API_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["coverage"]["run"]["relative_files"] is True
    # The lanes switch --cov-fail-under off; only this step may stand in for it.
    assert "py_test_lanes.py fail-under" in runs
    assert 'uv run coverage report --fail-under="$floor"' in runs
    assert "uv run coverage xml -o coverage.xml" in runs
    assert "uv build" in runs
    (upload,) = [s for s in py["steps"] if s.get("with", {}).get("name") == "py-coverage"]
    assert upload["with"]["path"] == "services/api/coverage.xml"
    assert '[ "$CHECKS_RESULT" = success ] && [ "$TESTS_RESULT" = success ]' in runs
    assert "uv run lint-imports" in _runs(jobs["py-checks"])


def test_fail_under_is_the_addopts_floor() -> None:
    pyproject = tomllib.loads((API_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]
    match = re.search(r"--cov-fail-under=(\S+)", addopts)
    assert match is not None
    assert fail_under(API_ROOT) == match.group(1)


# --- the checker fails on the cases it exists for ----------------------------------------------


def test_check_flags_a_file_two_lanes_would_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = _fake_api(tmp_path, ["tests/unit/bars/test_a.py", "tests/unit/test_b.py"])
    manifest_path = _manifest(tmp_path, {"a": ["tests/unit/bars"], "b": ["tests/unit"]})
    problems = check(load_manifest(manifest_path), api)
    assert (
        "tests/unit/bars and tests/unit overlap: list a path once, never inside another" in problems
    )
    assert "tests/unit/bars/test_a.py would run in 2 lanes (a, b)" in problems
    assert main(["--manifest", str(manifest_path), "--api-root", str(api), "check"]) == 1
    assert "would run in 2 lanes (a, b)" in capsys.readouterr().err


def test_check_flags_a_listed_path_that_is_gone(tmp_path: Path) -> None:
    api = _fake_api(tmp_path, ["tests/unit/bars_renamed/test_a.py"])
    manifest = load_manifest(_manifest(tmp_path, {"a": ["tests/unit/bars"]}))
    assert check(manifest, api) == ["tests/unit/bars: listed but missing (renamed or deleted?)"]


def test_check_flags_a_listed_path_without_test_files(tmp_path: Path) -> None:
    api = _fake_api(tmp_path, ["tests/unit/test_a.py"])
    (api / "tests" / "fixtures").mkdir()
    (api / "tests" / "fixtures" / "data.json").write_text("{}", encoding="utf-8")
    manifest = load_manifest(_manifest(tmp_path, {"a": ["tests/fixtures"]}))
    assert check(manifest, api) == ["tests/fixtures: listed but holds no test file"]


def test_partition_flags_a_file_no_lane_runs() -> None:
    lane_args = {"a": ["tests/unit"], "b": ["tests", "--ignore=tests/unit", "--ignore=tests/qa"]}
    assert partition_problems(lane_args, ["tests/qa/test_c.py", "tests/unit/test_d.py"]) == [
        "tests/qa/test_c.py would run in no lane"
    ]


def test_a_new_test_directory_runs_in_the_rest_lane(tmp_path: Path) -> None:
    api = _fake_api(
        tmp_path, ["tests/unit/bars/test_a.py", "tests/brand_new/test_new.py", "tests/conftest.py"]
    )
    manifest = load_manifest(_manifest(tmp_path, {"a": ["tests/unit/bars"]}))
    assert check(manifest, api) == []
    assert suite_files(api) == ["tests/brand_new/test_new.py", "tests/unit/bars/test_a.py"]
    assert collects(pytest_args(manifest, "rest"), "tests/brand_new/test_new.py")
    assert not collects(pytest_args(manifest, "a"), "tests/brand_new/test_new.py")


def test_collects_rejects_options_other_than_ignore() -> None:
    with pytest.raises(LaneManifestError, match="unexpected pytest option"):
        collects(["tests", "-k", "x"], "tests/test_a.py")


@pytest.mark.parametrize(
    ("expression", "leaves_out"),
    [
        ("perf and not flaky", True),
        ("not (chaos or harness) and not flaky", True),
        ("(perf)and not flaky", True),
        ("not exchange_smoke and not perf", False),
        ("perf or chaos and not flaky", False),  # `and` binds first: a flaky perf test still runs
        ("perf or(chaos) and not flaky", False),  # pytest splits words at parentheses too
        ("(perf)or chaos and not flaky", False),
        ("not (flaky and perf)", False),
    ],
)
def test_leaves_flaky_out_needs_not_flaky_under_the_outermost_and(
    expression: str, leaves_out: bool
) -> None:
    assert _leaves_flaky_out(expression) is leaves_out


@pytest.mark.parametrize(
    ("run", "kept_out"),
    [
        ('uv run pytest -p no:cacheprovider -m "perf and not flaky" \\\n  --no-cov tests', [True]),
        ("# pytest -m perf", []),
        ('lanes=$(python tools/ci/py_test_lanes.py pytest-args "$LANE")', []),
        ('pytest -m "perf and not flaky" tests -m perf', [False]),  # pytest applies the last -m
        ('pytest -m "not flaky" a --markexpr=perf', [False]),
        ('pytest -m "not flaky" a && pytest b', [True, False]),  # b runs the addopts selection
        ('python -m pytest -m"not flaky" a; .venv/bin/pytest --markexpr "perf" b', [True, False]),
        ('pytest -m "not flaky" $(cat paths) -m perf', [False]),
        ('(cd a && pytest -m "not flaky" t)&&pytest b', [True, False]),
    ],
)
def test_the_flaky_pin_reads_every_pytest_call_and_marker_expression(
    run: str, kept_out: list[bool]
) -> None:
    assert [_keeps_flaky_out(args) for args in _pytest_calls(run)] == kept_out


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"lanes": {"a": ["tests/x"]}}, "rest_lane"),
        ({"rest_lane": "rest", "lanes": {}}, "non-empty"),
        ({"rest_lane": "rest", "lanes": {"rest": ["tests/x"]}}, "other than the rest lane"),
        ({"rest_lane": "rest", "lanes": {"a": []}}, "at least one path"),
        ({"rest_lane": "rest", "lanes": {"a": ["tests/unit/*"]}}, "plain path"),
        ({"rest_lane": "rest", "lanes": {"a": ["tests/../x"]}}, "plain path"),
        ({"rest_lane": "rest", "lanes": {"a": ["tests"]}}, "plain path"),
        ([], "object"),
    ],
)
def test_load_manifest_rejects_a_malformed_manifest(
    tmp_path: Path, raw: object, message: str
) -> None:
    path = tmp_path / "lanes.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(LaneManifestError, match=re.escape(message)):
        load_manifest(path)


# --- the combine job's completeness check ------------------------------------------------------


def test_data_files_needs_exactly_one_file_per_lane(tmp_path: Path) -> None:
    manifest = load_manifest(_manifest(tmp_path, {"a": ["tests/x"], "b": ["tests/y"]}))
    data = tmp_path / "lane-coverage"
    data.mkdir()
    for lane in ("a", "rest"):
        (data / DATA_FILE_TEMPLATE.format(lane=lane)).write_bytes(b"x")
    files, problems = data_files(manifest, data)
    assert problems == ["lane 'b' left no coverage data (py-lane-b.coverage)"]

    (data / DATA_FILE_TEMPLATE.format(lane="b")).write_bytes(b"x")
    (data / "py-lane-old.coverage").write_bytes(b"x")
    files, problems = data_files(manifest, data)
    assert problems == ["unexpected file py-lane-old.coverage (no lane writes it)"]

    (data / "py-lane-old.coverage").unlink()
    files, problems = data_files(manifest, data)
    assert problems == []
    assert [f.name for f in files] == [
        "py-lane-a.coverage",
        "py-lane-b.coverage",
        "py-lane-rest.coverage",
    ]
    # Nothing downloaded at all (every lane failed before writing data): one finding per lane.
    assert data_files(manifest, tmp_path / "absent") == (
        [],
        [
            "lane 'a' left no coverage data (py-lane-a.coverage)",
            "lane 'b' left no coverage data (py-lane-b.coverage)",
            "lane 'rest' left no coverage data (py-lane-rest.coverage)",
        ],
    )


def test_fail_under_rejects_a_pyproject_without_exactly_one_floor(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = ["--cov", "--cov-fail-under=90"]\n',
        encoding="utf-8",
    )
    assert fail_under(tmp_path) == "90"
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "--cov"\n', encoding="utf-8"
    )
    with pytest.raises(LaneManifestError, match="one --cov-fail-under"):
        fail_under(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[tool.other]\n", encoding="utf-8")
    with pytest.raises(LaneManifestError, match="cannot read the pytest addopts"):
        fail_under(tmp_path)


# --- the CLI the workflow calls ----------------------------------------------------------------


def test_cli_prints_lane_arguments_and_the_floor(capsys: pytest.CaptureFixture[str]) -> None:
    manifest = load_manifest()
    assert main(["pytest-args", manifest.names[0]]) == 0
    assert capsys.readouterr().out.split() == pytest_args(manifest, manifest.names[0])
    assert main(["fail-under"]) == 0
    assert capsys.readouterr().out.strip() == fail_under(API_ROOT)
    assert main(["check"]) == 0
    assert "lanes partition" in capsys.readouterr().out
    assert main(["pytest-args", "nope"]) == 2


def test_cli_data_files_annotates_and_fails_when_a_lane_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = _manifest(tmp_path, {"a": ["tests/x"]})
    data = tmp_path / "lane-coverage"
    data.mkdir()
    (data / "py-lane-a.coverage").write_bytes(b"x")
    assert main(["--manifest", str(manifest_path), "data-files", str(data)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # the workflow captures stdout: an annotation there is never shown
    assert captured.err == (
        "::error title=CI-COV-003 incomplete py lane coverage::"
        "lane 'rest' left no coverage data (py-lane-rest.coverage)\n"
    )
    (data / "py-lane-rest.coverage").write_bytes(b"x")
    assert main(["--manifest", str(manifest_path), "data-files", str(data)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        str(data / "py-lane-a.coverage"),
        str(data / "py-lane-rest.coverage"),
    ]


def test_combine_step_shows_the_annotation_when_a_lane_left_no_data(tmp_path: Path) -> None:
    """The real `py` combine step, run as the runner runs a step with no `shell:` (`bash -e`), on
    a copy of the CLI and manifest: CI-COV-003 must reach the step log, not the stdout capture."""
    (run,) = [s["run"] for s in _jobs()["py"]["steps"] if "data-files" in s.get("run", "")]
    ci = tmp_path / "tools" / "ci"
    ci.mkdir(parents=True)
    for name in ("py_test_lanes.py", "py-test-lanes.json"):
        shutil.copy(ROOT / "tools" / "ci" / name, ci / name)
    shims = tmp_path / "bin"
    shims.mkdir()
    for tool, body in (("python", f'exec {shlex.quote(sys.executable)} "$@"'), ("uv", 'echo "$*"')):
        (shims / tool).write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        (shims / tool).chmod(0o755)
    data = tmp_path / "services" / "api" / "lane-coverage"
    data.mkdir(parents=True)
    first, *others = load_manifest().names
    for lane in others:
        (data / DATA_FILE_TEMPLATE.format(lane=lane)).write_bytes(b"x")
    env = {**os.environ, "PATH": f"{shims}{os.pathsep}{os.environ.get('PATH', os.defpath)}"}

    def step() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-e", "-c", run], cwd=data.parent, env=env, capture_output=True, text=True
        )

    missing = step()
    assert (missing.returncode, missing.stdout) == (1, "")
    assert missing.stderr == (
        "::error title=CI-COV-003 incomplete py lane coverage::"
        f"lane '{first}' left no coverage data ({DATA_FILE_TEMPLATE.format(lane=first)})\n"
    )
    (data / DATA_FILE_TEMPLATE.format(lane=first)).write_bytes(b"x")
    combined = step()
    files = " ".join(f"lane-coverage/{DATA_FILE_TEMPLATE.format(lane=n)}" for n in [first, *others])
    assert (combined.returncode, combined.stdout) == (0, f"run coverage combine {files}\n")
