"""Guards for the ``e40_regression`` pytest marker (E40-Q02 alert regression pack, #1203).

`qa/plans/e40-regression-pack.md` says which automated tests protect the alerts; the marker is how
a QA run selects them (`pytest -m e40_regression`). The two must agree, so these tests run real
`pytest --collect-only` sessions under the repo's own strict config and fail when the pack cites a
test the marker does not select, when the marker over the whole tree selects an item the default
lane deselects in the pack paths (or misses one it selects), when the pack's path list and the
code's differ in either direction, when a pack path disappears, and when the marker stops being
applied end to end. Same checks as the E08 guard, through `tests/_regression_pack_guard.py`.
"""

from __future__ import annotations

import re
from typing import Final

import pytest

from tests._e40_regression_pack import (
    API_ROOT,
    MARKER,
    NIGHTLY_ONLY_MARKERS,
    PACK_PATHS,
    is_pack_path,
    is_tagged,
)
from tests._regression_pack_guard import CITATION, cited_tests, collect, section, uncovered

PACK_DOC: Final = API_ROOT.parents[1] / "qa" / "plans" / "e40-regression-pack.md"
COVERAGE_HEADING: Final = "### Marker coverage"
_DESELECTED: Final = "/".join(sorted(NIGHTLY_ONLY_MARKERS))

# The module fixtures collect the whole tree in a child pytest; see the E08 guard (#4777).
pytestmark = pytest.mark.timeout(900)


@pytest.fixture(scope="module")
def selected_by_marker() -> frozenset[str]:
    return collect(API_ROOT, MARKER)


@pytest.fixture(scope="module")
def selected_by_default_lane() -> frozenset[str]:
    return collect(API_ROOT, None, *PACK_PATHS)


def _pack_citations() -> list[tuple[str, str | None]]:
    markdown = PACK_DOC.read_text(encoding="utf-8")
    return cited_tests(markdown.replace(section(markdown, COVERAGE_HEADING), ""))


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
        ("tests/alerts/test_alert_gating.py", set(), True),
        ("tests/alerts/test_alert_evaluator.py", set(), True),
        ("tests/alerts/test_alert_evaluator_r2.py", set(), False),
        ("tests/alerts/test_alert_gating.py", {"perf"}, False),
        ("tests/alerts/test_alert_gating.py", {"flaky"}, False),
        ("tests/alerts/test_alert_compiler_property.py", {"fuzz"}, False),
        ("tests/rules/test_scope.py", set(), False),
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


def test_pack_document_cites_the_four_ticket_cases() -> None:
    assert len({relative for relative, _ in _pack_citations()}) >= len(PACK_PATHS)


def test_pack_document_lists_exactly_the_paths_the_marker_covers() -> None:
    body = section(PACK_DOC.read_text(encoding="utf-8"), COVERAGE_HEADING)
    documented = set(re.findall(r"^- `([^`]+)`", body, flags=re.MULTILINE))

    assert documented == set(PACK_PATHS), (
        f"only in the pack: {sorted(documented - set(PACK_PATHS))}; "
        f"only in PACK_PATHS: {sorted(set(PACK_PATHS) - documented)}"
    )


def test_pack_run_command_selects_by_the_marker() -> None:
    how_to_run = PACK_DOC.read_text(encoding="utf-8").split("## How to run", 1)[1]
    command = re.search(r"```\n(.*?)```", how_to_run, flags=re.DOTALL)

    assert command is not None
    assert f"-m {MARKER}" in command.group(1)


def test_every_test_the_pack_cites_exists_and_is_selected_by_the_marker(
    selected_by_marker: frozenset[str],
) -> None:
    cited = _pack_citations()
    problems = [
        f"{relative}: cite a test file, file:line or file::test, not this"
        for relative, _ in cited
        if not CITATION.match(relative)
    ]
    well_formed = [(relative, name) for relative, name in cited if CITATION.match(relative)]
    problems += [
        f"{relative}: file does not exist"
        for relative in {relative for relative, _ in well_formed}
        if not (API_ROOT / relative).is_file()
    ]
    problems += [
        f"{what}: not selected by -m {MARKER} (no such test, a {_DESELECTED} item, or outside "
        "the pack paths)"
        for what in uncovered(well_formed, selected_by_marker, {})
    ]

    assert not problems, "\n".join(sorted(set(problems)))


def test_marker_over_the_whole_tree_selects_what_the_default_lane_selects_in_the_pack_paths(
    selected_by_marker: frozenset[str], selected_by_default_lane: frozenset[str]
) -> None:
    leaked = sorted(selected_by_marker - selected_by_default_lane)
    missed = sorted(selected_by_default_lane - selected_by_marker)

    assert selected_by_marker
    assert not leaked, f"selected by -m {MARKER} but not by the default -m: {leaked}"
    assert not missed, f"selected by the default -m in the pack paths, not by -m {MARKER}: {missed}"


def test_marker_selects_pack_files_and_nothing_else_through_a_real_collect_only_run() -> None:
    selected = collect(
        API_ROOT,
        MARKER,
        "tests/alerts/test_alert_gating.py",
        "tests/qa/test_e40_regression_pack.py",
    )

    assert selected
    assert all(node_id.startswith("tests/alerts/test_alert_gating.py::") for node_id in selected)
