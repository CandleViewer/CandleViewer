"""Guards for the ``e08_regression`` pytest marker (E08-Q06 regression pack, #283).

`qa/plans/e08-regression-pack.md` says which automated tests protect E08 and maps every P0/P1
defect fixed in the epic to a regression case; the marker is how a QA run selects them
(`pytest -m e08_regression`). The two must agree, so these tests run real `pytest --collect-only`
sessions under the repo's own strict config and fail when the pack cites a test the marker does
not select (unless another lane runs it, see `RUN_BY_OTHER_LANE`), when the marker, run over the
whole tree as QA runs it, selects an item the default lane deselects in the pack paths or misses
one it selects, when the pack's path list and the code's differ in either direction, when a pack
path disappears, when a fixed P0/P1 defect row cites no case or the defect table and its
"Result:" line disagree, and when the marker stops being applied end to end (conftest hook,
`--strict-markers`, `-m`). Same checks as the E09 guard (`tests/qa/test_e09_regression_pack.py`),
through the shared helpers in `tests/_regression_pack_guard.py`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

import pytest

from tests._e08_regression_pack import (
    API_ROOT,
    MARKER,
    NIGHTLY_ONLY_MARKERS,
    PACK_PATHS,
    WITHHELD_MARKERS,
    is_pack_path,
    is_tagged,
)
from tests._regression_pack_guard import (
    CITATION,
    Citation,
    cited_tests,
    collect,
    lane_key,
    matching,
    section,
    uncovered,
)

PACK_DOC: Final = API_ROOT.parents[1] / "qa" / "plans" / "e08-regression-pack.md"
COVERAGE_HEADING: Final = "### Marker coverage"
DEFECTS_HEADING: Final = "## B. Fixed P0 and P1 defects and their regression cases"
# Cited by the pack as evidence the marker does not select because another lane runs it. Key: a
# path prefix (trailing slash) or one `file::test`. Value: the marker that lane selects by (the CI
# `integration` job runs `pytest -m integration`, the CI `py-perf` job runs `pytest -m perf`).
RUN_BY_OTHER_LANE: Final[Mapping[str, str]] = {
    "tests/integration/": "integration",
    "tests/unit/observability/test_latency_overhead.py::"
    "test_stage_recorder_overhead_within_one_percent_cpu": "perf",
    "tests/security/ingestion/test_resource_exhaustion.py::"
    "test_huge_exponent_levels_rejected_cheaply": "perf",
}
# For failure messages: the markers the default -m deselects, every marker the pack withholds, and
# those it withholds although the default -m selects them (today exchange_smoke).
_DESELECTED: Final = "/".join(sorted(NIGHTLY_ONLY_MARKERS))
_WITHHELD: Final = "/".join(sorted(WITHHELD_MARKERS))
_WITHHELD_ONLY: Final = "/".join(sorted(WITHHELD_MARKERS - NIGHTLY_ONLY_MARKERS))
_DEFECT_ROW: Final = re.compile(r"^\|\s*#(\d+)\s*\|\s*(P\d)\s*\|")
_DEFECT_RESULT: Final = re.compile(
    r"^Result: (\d+) fixed P0/P1 defects \((\d+) P0, (\d+) P1\)", flags=re.MULTILINE
)


def _pack_citations() -> list[Citation]:
    """The pack's test citations; the path list under "Marker coverage" is not one of them."""
    markdown = PACK_DOC.read_text(encoding="utf-8")
    return cited_tests(markdown.replace(section(markdown, COVERAGE_HEADING), ""))


def _defect_table() -> tuple[list[tuple[str, str, list[Citation]]], list[str], str]:
    """The fixed-defect table: (issue, severity, citations) per row, the rows that do not parse
    as `| #NNNN | Pn |`, and the section body."""
    body = section(PACK_DOC.read_text(encoding="utf-8"), DEFECTS_HEADING)
    table = [line for line in body.splitlines() if line.startswith("|")][2:]  # past the header
    rows = []
    unparsed = []
    for line in table:
        if match := _DEFECT_ROW.match(line):
            rows.append((match.group(1), match.group(2), cited_tests(line)))
        else:
            unparsed.append(line[:60])
    return rows, unparsed, body


# #4777: the module fixtures collect the whole tree in a child pytest (about 240 s on CI), which
# the suite's 120 s per-test default would cut short; 900 s keeps a bound with headroom.
pytestmark = pytest.mark.timeout(900)


@pytest.fixture(scope="module")
def selected_by_marker() -> frozenset[str]:
    """What the pack's QA command, `pytest -m e08_regression` with no paths, selects in the tree."""
    return collect(API_ROOT, MARKER)


@pytest.fixture(scope="module")
def selected_by_default_lane() -> frozenset[str]:
    return collect(API_ROOT, None, *PACK_PATHS)


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
        ("tests/unit/ingestion/test_trade_stream.py", set(), True),
        ("tests/unit/exchange/bybit/test_rest_client.py", set(), True),
        ("tests/unit/ingestionx/test_other.py", set(), False),
        ("tests/unit/bars/test_kline_rows.py", set(), True),
        ("tests/unit/bars/test_time_builder.py", set(), False),
        ("tests/xstate_contract/test_b13_ws_conn.py", set(), True),
        ("tests/xstate_contract/test_b01_order.py", set(), False),
        ("tests/chaos/ingestion/test_s03_book_sequence_gap.py", {"chaos"}, True),
        ("tests/unit/ingestion/test_kline_backfill_perf.py", {"perf"}, False),
        ("tests/security/ingestion/test_fuzz_parsers.py", {"fuzz"}, False),
        ("tests/unit/ingestion/test_ingestion_soak_bench.py", {"harness"}, False),
        ("tests/unit/bus/test_bus.py", {"flaky"}, False),
        ("tests/unit/exchange/bybit/test_rest_client.py", {"exchange_smoke"}, False),
        ("tests/integration/storage/test_questdb_hot_tier.py", {"integration"}, False),
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
        "| A | x | `tests/unit/book/test_a.py::test_one`, `::test_two[p-1]`, `::test_three` |\n"
        "| B | y | `tests/chaos/ingestion/test_b.py:163` and `apps/web/e2e/x.spec.ts` |\n"
        "| C | z | `tests/unit/book/` and `services/api/tests/conftest.py` |\n"
        "| D | w | `::orphan` |\n"
        "```\nuv run pytest `tests/unit/ingestion/fenced.py`\n```\n"
    )

    assert cited_tests(markdown) == [
        ("tests/unit/book/test_a.py", "test_one"),
        ("tests/unit/book/test_a.py", "test_two"),
        ("tests/unit/book/test_a.py", "test_three"),
        ("tests/chaos/ingestion/test_b.py", None),
        ("tests/unit/book/", None),
    ]


_SELECTED: Final = frozenset(
    {
        "tests/unit/book/test_a.py::test_one",
        "tests/unit/book/test_a.py::test_param[p-1]",
        "tests/unit/book/test_a.py::TestGroup::test_nested",
        "tests/unit/book/test_a.py::test_one_more",
    }
)


@pytest.mark.parametrize(
    ("cited", "missing"),
    [
        pytest.param([("tests/unit/book/test_a.py", "test_one")], [], id="test"),
        pytest.param([("tests/unit/book/test_a.py", "test_param")], [], id="parameter-suffix"),
        pytest.param([("tests/unit/book/test_a.py", "test_nested")], [], id="class-member"),
        pytest.param([("tests/unit/book/test_a.py", None)], [], id="file-any-test-selected"),
        pytest.param(
            [("tests/unit/book/test_a.py", "test_on")],
            ["tests/unit/book/test_a.py::test_on"],
            id="name-prefix-is-not-a-match",
        ),
        pytest.param(
            [("tests/unit/book/test_other.py", None)],
            ["tests/unit/book/test_other.py"],
            id="file-nothing-selected",
        ),
        pytest.param(
            [("tests/integration/storage/test_x.py", "test_y")], [], id="other-lane-by-prefix"
        ),
        pytest.param(
            [("tests/integrationx/test_z.py", "test_z")],
            ["tests/integrationx/test_z.py::test_z"],
            id="other-lane-prefix-needs-the-slash",
        ),
    ],
)
def test_uncovered_flags_cited_tests_the_marker_run_does_not_select(
    cited: list[Citation], missing: list[str]
) -> None:
    assert uncovered(cited, _SELECTED, RUN_BY_OTHER_LANE) == missing


def test_pack_document_cites_a_plausible_number_of_tests() -> None:
    assert len(_pack_citations()) >= 60


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


def test_every_fixed_p0_p1_defect_row_cites_at_least_one_case() -> None:
    """Ticket AC "no fix ships without a regression case": a row with no case blocks sign-off.

    Every table row must parse and the rows must add up to the section's "Result:" line, so a
    reformatted row cannot drop out of this check unseen."""
    rows, unparsed, body = _defect_table()
    result = _DEFECT_RESULT.search(body)
    caseless = [f"#{issue}" for issue, _, cited in rows if not cited]
    wrong_severity = [f"#{issue} ({sev})" for issue, sev, _ in rows if sev not in ("P0", "P1")]
    counted = (len(rows), sum(s == "P0" for _, s, _ in rows), sum(s == "P1" for _, s, _ in rows))

    assert not unparsed, f"fixed-defect rows not in the `| #NNNN | Pn |` form: {unparsed}"
    assert result is not None, "section B lost its 'Result: N fixed P0/P1 defects' line"
    expected = tuple(map(int, result.groups()))
    assert counted == expected, f"the table counts {counted} (all, P0, P1), Result: says {expected}"
    assert not caseless, f"fixed P0/P1 defects with no regression case: {caseless}"
    assert not wrong_severity, f"rows in the P0/P1 table with another severity: {wrong_severity}"


def test_every_test_the_pack_cites_exists_and_is_selected_by_the_marker(
    selected_by_marker: frozenset[str],
) -> None:
    cited = _pack_citations()
    well_formed = [(relative, name) for relative, name in cited if CITATION.match(relative)]
    problems = [
        f"{relative}: cite a test file, file:line or file::test, not this"
        for relative, _ in cited
        if not CITATION.match(relative)
    ]
    problems += [
        f"{relative}: file does not exist"
        for relative in {relative for relative, _ in well_formed}
        if not (API_ROOT / relative).is_file()
    ]
    problems += [
        f"{what}: not selected by -m {MARKER} (no such test, a {_WITHHELD} item, or outside the "
        "pack paths)"
        for what in uncovered(well_formed, selected_by_marker, RUN_BY_OTHER_LANE)
    ]

    assert not problems, "\n".join(sorted(set(problems)))


@pytest.mark.parametrize("key", sorted(RUN_BY_OTHER_LANE), ids=lambda key: RUN_BY_OTHER_LANE[key])
def test_other_lane_exemption_is_cited_unselected_by_the_marker_and_selected_by_its_lane(
    key: str, selected_by_marker: frozenset[str]
) -> None:
    lane_marker = RUN_BY_OTHER_LANE[key]
    exempt = [
        (relative, name)
        for relative, name in _pack_citations()
        if lane_key(RUN_BY_OTHER_LANE, relative, name) == key
    ]
    assert exempt, f"the pack no longer cites anything under {key}: drop the exemption"

    in_lane = collect(API_ROOT, lane_marker, *sorted({relative for relative, _ in exempt}))
    problems = []
    for relative, name in exempt:
        what = relative if name is None else f"{relative}::{name}"
        if matching(selected_by_marker, relative, name):
            problems.append(f"{what}: -m {MARKER} selects it now, drop the exemption")
        if not matching(in_lane, relative, name):
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
        f"hand outside them, or a {_DESELECTED} item): {leaked}"
    )
    assert not missed, (
        f"selected by the default -m in the pack paths, not by -m {MARKER} (a {_WITHHELD_ONLY} "
        f"item, which the marker withholds, or a test the tagging hook missed): {missed}"
    )


def test_marker_selects_pack_files_and_nothing_else_through_a_real_collect_only_run() -> None:
    selected = collect(
        API_ROOT,
        MARKER,
        "tests/unit/test_ingestion_service.py",
        "tests/qa/test_e08_regression_pack.py",
    )

    assert selected
    assert all(node_id.startswith("tests/unit/test_ingestion_service.py::") for node_id in selected)
