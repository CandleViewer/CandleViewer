"""Selection rule for the ``e40_regression`` marker (E40-Q02 alert regression pack, #1203).

`qa/plans/e40-regression-pack.md` says why each file is in the pack; this module is the one place
that says which paths the marker covers, and `tests/conftest.py` applies it at collection time,
next to the E08 and E09 packs' rules. Same design as `tests/_e08_regression_pack.py`: tagging by
path, not by a decorator per test, leaves the suites other PRs edit untouched.
`tests/qa/test_e40_regression_pack.py` fails when this list and the pack document's "Marker
coverage" list differ in either direction, when the pack cites a test the marker does not select,
and when the marker selects anything the default lane deselects.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from functools import cache
from pathlib import Path
from typing import Final

import pytest

MARKER: Final = "e40_regression"
API_ROOT: Final = Path(__file__).resolve().parents[1]

# A trailing slash means a directory, anything else one file. The pack document's "Marker
# coverage" section lists the same paths. The pack is the four permanent regression cases the
# E40-Q02 ticket names (BQ-10): an alert cannot act, the critical-override matrix,
# exactly-once under restart, and storm conservation.
PACK_PATHS: Final[tuple[str, ...]] = (
    "tests/alerts/test_alert_compiler.py",
    "tests/alerts/test_alert_compiler_property.py",
    "tests/alerts/test_alert_gating.py",
    "tests/alerts/test_alert_dispatcher_restart.py",
    "tests/alerts/test_alert_evaluator.py",
)

# `addopts` in pyproject.toml deselects these by default; a bare `-m e40_regression` replaces that
# expression, so the marker is withheld from them. The guard fails when this set and that
# expression differ.
NIGHTLY_ONLY_MARKERS: Final = frozenset({"flaky", "fuzz", "harness", "perf"})


def is_pack_path(relative: str) -> bool:
    """`relative` is a POSIX path relative to services/api."""
    return any(
        relative.startswith(entry) if entry.endswith("/") else relative == entry
        for entry in PACK_PATHS
    )


def is_tagged(relative: str, marker_names: Collection[str]) -> bool:
    return is_pack_path(relative) and NIGHTLY_ONLY_MARKERS.isdisjoint(marker_names)


@cache
def _relative_to_api_root(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(API_ROOT).as_posix()
    except ValueError:
        return None


def tag_pack(items: Iterable[pytest.Item]) -> None:
    for item in items:
        relative = _relative_to_api_root(item.path)
        if relative is not None and is_tagged(relative, {m.name for m in item.iter_markers()}):
            item.add_marker(getattr(pytest.mark, MARKER))
