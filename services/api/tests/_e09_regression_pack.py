"""Selection rule for the ``e09_regression`` marker (E09-Q06 regression pack, #2148).

`qa/plans/e09-regression-pack.md` says why each test is in the pack; this module is the one place
that says which paths the marker covers, and `tests/conftest.py` applies it at collection time.
Tagging by path, not by a decorator per test, leaves the ~100 test modules other PRs edit untouched
and lets a new test dropped into a pack directory join the pack without anyone remembering to tag
it. `tests/qa/test_e09_regression_pack.py` fails when this list and the pack document drift apart.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from functools import cache
from pathlib import Path
from typing import Final

import pytest

MARKER: Final = "e09_regression"
API_ROOT: Final = Path(__file__).resolve().parents[1]

# A trailing slash means a directory, anything else one file. The first group is the pack's "How to
# run" subset; the second is cited by the pack as evidence but lives outside those directories.
PACK_PATHS: Final[tuple[str, ...]] = (
    "tests/unit/auth/",
    "tests/unit/audit/",
    "tests/unit/api/",
    "tests/unit/ws/",
    "tests/unit/test_ws_permissions.py",
    "tests/contract/rbac/",
    "tests/security/auth/",
    "tests/qa/test_e09_dryrun_group_a.py",
    "tests/chaos/auth/",
    "tests/unit/observability/test_redaction.py",
    "tests/unit/migrations/test_0003_audit_log.py",
)

# `addopts` in pyproject.toml deselects these by default (nightly or wall-clock-budget lanes). A
# bare `-m e09_regression` replaces that default expression, so the marker is withheld from them
# instead of leaving every QA run to repeat "and not perf and not fuzz and not harness".
NIGHTLY_ONLY_MARKERS: Final = frozenset({"fuzz", "harness", "perf"})


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
