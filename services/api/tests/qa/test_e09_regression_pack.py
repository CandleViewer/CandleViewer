"""Guards for the ``e09_regression`` pytest marker (E09-Q06 regression pack, #2148).

`qa/plans/e09-regression-pack.md` says which automated tests protect E09; the marker is how a QA
run selects them (`pytest -m e09_regression`). The two must agree, so these tests run real
`pytest --collect-only` sessions under the repo's own strict config and fail when the pack cites a
test the marker does not select (unless another lane runs it, see `RUN_BY_OTHER_LANE`), when the
marker, run over the whole tree as QA runs it, selects an item the default lane deselects in the
pack paths (a perf test, or a test tagged by hand outside them) or misses one it selects, when the
pack's path list and the code's differ in either direction, when a pack path disappears, and when
the marker stops being applied end to end (conftest hook, `--strict-markers`, `-m`).
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable, Mapping
from typing import Final

import pytest

from tests._e09_regression_pack import (
    API_ROOT,
    MARKER,
    NIGHTLY_ONLY_MARKERS,
    PACK_PATHS,
    is_pack_path,
    is_tagged,
)

PACK_DOC = API_ROOT.parents[1] / "qa" / "plans" / "e09-regression-pack.md"
COVERAGE_HEADING = "### Marker coverage"
_A07_TIMING_TEST: Final = (
    "tests/unit/auth/test_login_timing_enumeration.py::"
    "test_login_timing_unknown_vs_wrong_password_indistinguishable_over_1000_samples"
)
# Cited by the pack as evidence the marker does not select because another lane runs it. Key: a
# path prefix (trailing slash) or one `file::test`. Value: the marker that lane selects by (the CI
# `integration` job runs `pytest -m integration`, the CI `py-perf` job runs `pytest -m perf`).
RUN_BY_OTHER_LANE: Final[Mapping[str, str]] = {
    "tests/integration/": "integration",
    _A07_TIMING_TEST: "perf",
}
_SPAN = re.compile(r"`([^`\n]+)`")
# `tests/x.py`, `tests/x.py:163`, `tests/x.py::test_name`, `tests/x.py::test_name[param]`
_CITATION = re.compile(r"^(tests/\S+?\.py)(?::\d+)?(?:::(\w+)(?:\[.*\])?)?$")
_CONTINUATION = re.compile(r"^::(\w+)(?:\[.*\])?$")
_NODE_ID = re.compile(r"^tests/\S+\.py::\S")


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


def _section(markdown: str, heading: str) -> str:
    """The body under `heading` (a whole heading line), up to the next heading."""
    match = re.search(
        rf"^{re.escape(heading)}\n(.*?)(?=^#|\Z)", markdown, flags=re.DOTALL | re.MULTILINE
    )
    assert match is not None, f"{heading!r} is missing from {PACK_DOC.name}"
    return match.group(1)


def _pack_citations() -> list[tuple[str, str | None]]:
    """The pack's test citations; the path list under "Marker coverage" is not one of them."""
    markdown = PACK_DOC.read_text(encoding="utf-8")
    return _cited_tests(markdown.replace(_section(markdown, COVERAGE_HEADING), ""))


def _lane_key(relative: str, name: str | None) -> str | None:
    """The `RUN_BY_OTHER_LANE` key covering this citation, if any."""
    cited = relative if name is None else f"{relative}::{name}"
    return next(
        (
            key
            for key in RUN_BY_OTHER_LANE
            if cited == key or (key.endswith("/") and cited.startswith(key))
        ),
        None,
    )


def _test_name(node_id: str) -> str:
    """`a.py::TestX::test_y[p]` -> `test_y`."""
    return node_id.split("[", 1)[0].rsplit("::", 1)[-1]


def _matching(node_ids: Iterable[str], relative: str, name: str | None) -> list[str]:
    """The node ids a citation (`file` or `file::test`) refers to."""
    in_file = [node_id for node_id in node_ids if node_id.startswith(f"{relative}::")]
    return in_file if name is None else [i for i in in_file if _test_name(i) == name]


def _uncovered(cited: Iterable[tuple[str, str | None]], selected: Iterable[str]) -> list[str]:
    """The citations `selected` (node ids a real `-m e09_regression` run returned) does not cover.

    A citation is covered when it refers to at least one selected node id (a file is covered by any
    test in it) or when `RUN_BY_OTHER_LANE` hands it to another lane. Returned as `file` or
    `file::test`.
    """
    chosen = list(selected)
    return [
        relative if name is None else f"{relative}::{name}"
        for relative, name in cited
        if _lane_key(relative, name) is None and not _matching(chosen, relative, name)
    ]


def _collect(expression: str | None, *targets: str) -> frozenset[str]:
    """Node ids of a real `pytest --collect-only -m <expression> <targets>` run from services/api.

    `None` keeps the repo's default `-m` expression from `addopts`; exit code 5 means nothing was
    selected. The argv stays a literal list (ruff S603); the variable part travels in
    PYTEST_ADDOPTS, which also drops any addopts the outer session was started with.
    """
    options = [] if expression is None else ["-m", expression]
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
        ],
        cwd=API_ROOT,
        env={**os.environ, "PYTEST_ADDOPTS": shlex.join([*options, *targets])},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode in (0, 5), "\n".join(output.splitlines()[-40:])
    return frozenset(line for line in result.stdout.splitlines() if _NODE_ID.match(line))


@pytest.fixture(scope="module")
def selected_by_marker() -> frozenset[str]:
    """What the pack's QA command, `pytest -m e09_regression` with no paths, selects in the tree."""
    return _collect(MARKER)


@pytest.fixture(scope="module")
def selected_by_default_lane() -> frozenset[str]:
    return _collect(None, *PACK_PATHS)


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


def test_nightly_only_markers_are_the_ones_addopts_deselects_by_default(
    pytestconfig: pytest.Config,
) -> None:
    addopts = pytestconfig.getini("addopts")
    assert "-m" in addopts, "addopts sets no default -m expression; revisit NIGHTLY_ONLY_MARKERS"

    deselected = set(re.findall(r"\bnot (\w+)", addopts[addopts.index("-m") + 1]))

    assert deselected == NIGHTLY_ONLY_MARKERS


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
    assert len(_pack_citations()) >= 60


_SELECTED = frozenset(
    {
        "tests/unit/auth/test_a.py::test_one",
        "tests/unit/auth/test_a.py::test_param[p-1]",
        "tests/unit/auth/test_a.py::TestGroup::test_nested",
        "tests/unit/auth/test_a.py::test_one_more",
    }
)


@pytest.mark.parametrize(
    ("cited", "uncovered"),
    [
        pytest.param([("tests/unit/auth/test_a.py", "test_one")], [], id="test"),
        pytest.param([("tests/unit/auth/test_a.py", "test_param")], [], id="parameter-suffix"),
        pytest.param([("tests/unit/auth/test_a.py", "test_nested")], [], id="class-member"),
        pytest.param([("tests/unit/auth/test_a.py", None)], [], id="file-any-test-selected"),
        pytest.param(
            [("tests/unit/auth/test_timing.py", "test_slow")],
            ["tests/unit/auth/test_timing.py::test_slow"],
            id="collected-but-withheld-perf-test",
        ),
        pytest.param(
            [("tests/unit/auth/test_a.py", "helper")],
            ["tests/unit/auth/test_a.py::helper"],
            id="not-a-test",
        ),
        pytest.param(
            [("tests/unit/auth/test_a.py", "test_on")],
            ["tests/unit/auth/test_a.py::test_on"],
            id="name-prefix-is-not-a-match",
        ),
        pytest.param(
            [("tests/unit/auth/test_other.py", None)],
            ["tests/unit/auth/test_other.py"],
            id="file-nothing-selected",
        ),
        pytest.param(
            [("tests/integration/audit/test_x.py", "test_y")], [], id="other-lane-by-prefix"
        ),
        pytest.param(
            [("tests/integrationx/test_z.py", "test_z")],
            ["tests/integrationx/test_z.py::test_z"],
            id="other-lane-prefix-needs-the-slash",
        ),
    ],
)
def test_uncovered_flags_cited_tests_the_marker_run_does_not_select(
    cited: list[tuple[str, str | None]], uncovered: list[str]
) -> None:
    assert _uncovered(cited, _SELECTED) == uncovered


def test_pack_document_lists_exactly_the_paths_the_marker_covers() -> None:
    body = _section(PACK_DOC.read_text(encoding="utf-8"), COVERAGE_HEADING)
    documented = set(re.findall(r"^- `([^`]+)`", body, flags=re.MULTILINE))

    assert documented == set(PACK_PATHS), (
        f"only in the pack: {sorted(documented - set(PACK_PATHS))}; "
        f"only in PACK_PATHS: {sorted(set(PACK_PATHS) - documented)}"
    )


def test_pack_run_command_selects_by_the_marker() -> None:
    section = PACK_DOC.read_text(encoding="utf-8").split("## How to run", 1)[1]
    command = re.search(r"```\n(.*?)```", section, flags=re.DOTALL)

    assert command is not None
    assert f"-m {MARKER}" in command.group(1)


def test_every_test_the_pack_cites_exists_and_is_selected_by_the_marker(
    selected_by_marker: frozenset[str],
) -> None:
    cited = _pack_citations()
    well_formed = [(relative, name) for relative, name in cited if _CITATION.match(relative)]
    problems = [
        f"{relative}: cite a test file, file:line or file::test, not this"
        for relative, _ in cited
        if not _CITATION.match(relative)
    ]
    problems += [
        f"{relative}: file does not exist"
        for relative in {relative for relative, _ in well_formed}
        if not (API_ROOT / relative).is_file()
    ]
    problems += [
        f"{what}: not selected by -m {MARKER} (no such test, a perf/fuzz/harness test, or outside "
        "the pack paths)"
        for what in _uncovered(well_formed, selected_by_marker)
    ]

    assert not problems, "\n".join(sorted(set(problems)))


@pytest.mark.parametrize("key", sorted(RUN_BY_OTHER_LANE), ids=lambda key: RUN_BY_OTHER_LANE[key])
def test_other_lane_exemption_is_cited_unselected_by_the_marker_and_selected_by_its_lane(
    key: str, selected_by_marker: frozenset[str]
) -> None:
    lane_marker = RUN_BY_OTHER_LANE[key]
    exempt = [
        (relative, name) for relative, name in _pack_citations() if _lane_key(relative, name) == key
    ]
    assert exempt, f"the pack no longer cites anything under {key}: drop the exemption"

    in_lane = _collect(lane_marker, *sorted({relative for relative, _ in exempt}))
    problems = []
    for relative, name in exempt:
        what = relative if name is None else f"{relative}::{name}"
        if _matching(selected_by_marker, relative, name):
            problems.append(f"{what}: -m {MARKER} selects it now, drop the exemption")
        if not _matching(in_lane, relative, name):
            problems.append(f"{what}: -m {lane_marker} no longer selects it")

    assert not problems, "\n".join(problems)


def test_marker_over_the_whole_tree_selects_what_the_default_lane_selects_in_the_pack_paths(
    selected_by_marker: frozenset[str], selected_by_default_lane: frozenset[str]
) -> None:
    leaked = sorted(selected_by_marker - selected_by_default_lane)
    missed = sorted(selected_by_default_lane - selected_by_marker)

    assert selected_by_marker
    assert not leaked, (
        f"selected by -m {MARKER} but not by the default -m in the pack paths (a test tagged by "
        f"hand outside them, or a perf/fuzz/harness item): {leaked}"
    )
    assert not missed, f"selected by the default -m in the pack paths, not by -m {MARKER}: {missed}"


def test_marker_selects_pack_files_and_nothing_else_through_a_real_collect_only_run() -> None:
    selected = _collect(
        MARKER, "tests/qa/test_e09_dryrun_group_a.py", "tests/qa/test_e09_regression_pack.py"
    )

    assert selected
    assert all(node_id.startswith("tests/qa/test_e09_dryrun_group_a.py::") for node_id in selected)
