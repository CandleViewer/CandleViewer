"""Guards for the ``e09_regression`` pytest marker (E09-Q06 regression pack, #2148).

`qa/plans/e09-regression-pack.md` says which automated tests protect E09; the marker is how a QA
run or a CI lane selects them (`pytest -m e09_regression`). The two must agree, so these tests fail
when the pack cites a test the marker would not select, when a pack path disappears, or when the
marker stops being applied end to end (conftest hook, `--strict-markers`, `-m`).
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

from tests._e09_regression_pack import API_ROOT, MARKER, PACK_PATHS, is_pack_path, is_tagged

PACK_DOC = API_ROOT.parents[1] / "qa" / "plans" / "e09-regression-pack.md"
# Cited as evidence but needs the docker stack; the CI `integration` job runs it, not the marker.
RUN_BY_OTHER_LANE = ("tests/integration/",)
_SPAN = re.compile(r"`([^`\n]+)`")
# `tests/x.py`, `tests/x.py:163`, `tests/x.py::test_name`, `tests/x.py::test_name[param]`
_CITATION = re.compile(r"^(tests/\S+?\.py)(?::\d+)?(?:::(\w+)(?:\[.*\])?)?$")
_CONTINUATION = re.compile(r"^::(\w+)(?:\[.*\])?$")


def _cited_tests(markdown: str) -> list[tuple[str, str | None]]:
    """Every `tests/...` the pack cites; `::name` continues the file named earlier in the same row.

    A `tests/` span in none of the forms above is returned whole as a "file", so the existence
    check reports it instead of the guard silently skipping a citation it cannot read.
    """
    prose = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    cited: list[tuple[str, str | None]] = []
    for line in prose.splitlines():
        current: str | None = None
        for span in _SPAN.findall(line):
            if span.startswith("tests/"):
                match = _CITATION.match(span)
                current, name = (match.group(1), match.group(2)) if match else (span, None)
                cited.append((current, name))
            elif current is not None and (match := _CONTINUATION.match(span)):
                cited.append((current, match.group(1)))
    return cited


@cache
def _defined_names(file: Path) -> frozenset[str]:
    tree = ast.parse(file.read_text(encoding="utf-8"))
    return frozenset(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    )


def test_marker_is_registered_so_strict_markers_accepts_it(pytestconfig: pytest.Config) -> None:
    registered = {line.split(":", 1)[0].strip() for line in pytestconfig.getini("markers")}

    assert MARKER in registered


@pytest.mark.parametrize("entry", PACK_PATHS)
def test_pack_path_exists_so_a_rename_cannot_silently_shrink_the_pack(entry: str) -> None:
    target = API_ROOT / entry

    assert target.is_dir() if entry.endswith("/") else target.is_file(), f"{entry} is gone"


@pytest.mark.parametrize(
    ("relative", "markers", "expected"),
    [
        ("tests/unit/auth/test_mfa_service.py", set(), True),
        ("tests/unit/auth/nested/test_deep.py", set(), True),
        ("tests/unit/authz/test_other.py", set(), False),
        ("tests/unit/test_ws_permissions.py", set(), True),
        ("tests/unit/test_ws_permissions_extra.py", set(), False),
        ("tests/unit/bars/test_bar_builder.py", set(), False),
        ("tests/chaos/auth/test_auth_chaos.py", {"chaos", "integration"}, True),
        ("tests/unit/audit/test_verify_perf.py", {"perf"}, False),
        ("tests/unit/ws/test_cvwb_fuzz.py", {"fuzz"}, False),
        ("tests/unit/api/test_heavy.py", {"harness"}, False),
        ("tests/integration/audit/test_audit_repository.py", {"integration"}, False),
    ],
)
def test_is_tagged_follows_pack_paths_and_skips_nightly_only_items(
    relative: str, markers: set[str], expected: bool
) -> None:
    assert is_tagged(relative, markers) is expected


def test_is_pack_path_rejects_paths_outside_the_pack() -> None:
    assert not is_pack_path("scripts/tests/test_anything.py")


def test_cited_tests_reads_file_line_param_and_continuation_forms() -> None:
    markdown = (
        "| A | x | `tests/unit/auth/test_a.py::test_one`, `::test_two[p-1]`, `::test_three` |\n"
        "| B | y | `tests/chaos/auth/test_b.py:163` and `apps/web/e2e/auth/x.spec.ts` |\n"
        "| C | z | `tests/unit/auth/` and `services/api/tests/conftest.py` |\n"
        "| D | w | `::orphan` |\n"
        "```\nuv run pytest `tests/unit/auth/fenced.py`\n```\n"
    )

    assert _cited_tests(markdown) == [
        ("tests/unit/auth/test_a.py", "test_one"),
        ("tests/unit/auth/test_a.py", "test_two"),
        ("tests/unit/auth/test_a.py", "test_three"),
        ("tests/chaos/auth/test_b.py", None),
        ("tests/unit/auth/", None),
    ]


def test_pack_document_cites_a_plausible_number_of_tests() -> None:
    assert len(_cited_tests(PACK_DOC.read_text(encoding="utf-8"))) >= 60


def test_every_test_the_pack_cites_exists_and_is_selected_by_the_marker() -> None:
    problems: list[str] = []
    for relative, name in _cited_tests(PACK_DOC.read_text(encoding="utf-8")):
        if not _CITATION.match(relative):
            problems.append(f"{relative}: cite a test file, file:line or file::test, not this")
            continue
        file = API_ROOT / relative
        if not file.is_file():
            problems.append(f"{relative}: file does not exist")
            continue
        if name is not None and name not in _defined_names(file):
            problems.append(f"{relative}::{name}: no such test")
        if not relative.startswith(RUN_BY_OTHER_LANE) and not is_pack_path(relative):
            problems.append(f"{relative}: cited by the pack but not selected by -m {MARKER}")

    assert not problems, "\n".join(sorted(set(problems)))


def test_pack_run_command_selects_by_the_marker() -> None:
    section = PACK_DOC.read_text(encoding="utf-8").split("## How to run", 1)[1]
    command = re.search(r"```\n(.*?)```", section, flags=re.DOTALL)

    assert command is not None
    assert f"-m {MARKER}" in command.group(1)


def test_marker_selects_pack_files_and_nothing_else_through_a_real_collect_only_run() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-cov",
            "-p",
            "no:cacheprovider",
            "-m",
            "e09_regression",
            "tests/qa/test_e09_dryrun_group_a.py",
            "tests/qa/test_e09_regression_pack.py",
        ],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    selected = [line for line in result.stdout.splitlines() if "::" in line]
    assert result.returncode == 0, result.stdout + result.stderr
    assert selected
    assert all(line.startswith("tests/qa/test_e09_dryrun_group_a.py::") for line in selected)
