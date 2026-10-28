"""Shared checks behind a regression-pack guard (E08-Q06, #283).

A regression pack is a pytest marker applied by path (`tests/_e08_regression_pack.py`) plus a
document that cites the tests guarding each case. These helpers read the citations out of such a
document and run real `pytest --collect-only` sessions, so a guard can compare what the document
claims with what the marker selects. `tests/qa/test_e08_regression_pack.py` uses them. The E09
guard (`tests/qa/test_e09_regression_pack.py`) predates this module and keeps its own copies; it
is left as it is so this ticket does not change another epic's gate.

No helper is named `test_*`: a guard module imports them, and pytest would collect such a name.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

_SPAN: Final = re.compile(r"`([^`\n]+)`")
# `tests/x.py`, `tests/x.py:163`, `tests/x.py::test_name`, `tests/x.py::test_name[param]`
CITATION: Final = re.compile(r"^(tests/\S+?\.py)(?::\d+)?(?:::(\w+)(?:\[.*\])?)?$")
_CONTINUATION: Final = re.compile(r"^::(\w+)(?:\[.*\])?$")
_NODE_ID: Final = re.compile(r"^tests/\S+\.py::\S")

Citation = tuple[str, str | None]


def cited_tests(markdown: str) -> list[Citation]:
    """Every `tests/...` the document cites; `::name` continues the file named earlier in the row.

    Fenced code blocks are skipped. A `tests/` span in none of the forms above is returned whole as
    a "file", so the existence check reports it instead of silently skipping a citation.
    """
    prose = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    cited: list[Citation] = []
    for line in prose.splitlines():
        current: str | None = None
        for span in _SPAN.findall(line):
            if span.startswith("tests/"):
                match = CITATION.match(span)
                current, name = (match.group(1), match.group(2)) if match else (span, None)
                cited.append((current, name))
            elif current is not None and (match := _CONTINUATION.match(span)):
                cited.append((current, match.group(1)))
    return cited


def section(markdown: str, heading: str) -> str:
    """The body under `heading` (a whole heading line), up to the next heading of any level."""
    match = re.search(
        rf"^{re.escape(heading)}\n(.*?)(?=^#|\Z)", markdown, flags=re.DOTALL | re.MULTILINE
    )
    assert match is not None, f"{heading!r} is missing from the pack document"
    return match.group(1)


def node_name(node_id: str) -> str:
    """`a.py::TestX::test_y[p]` -> `test_y`."""
    return node_id.split("[", 1)[0].rsplit("::", 1)[-1]


def matching(node_ids: Iterable[str], relative: str, name: str | None) -> list[str]:
    """The node ids a citation (`file` or `file::test`) refers to."""
    in_file = [node_id for node_id in node_ids if node_id.startswith(f"{relative}::")]
    return in_file if name is None else [i for i in in_file if node_name(i) == name]


def lane_key(lanes: Mapping[str, str], relative: str, name: str | None) -> str | None:
    """The `lanes` key covering this citation: a path prefix (trailing slash) or `file::test`."""
    cited = relative if name is None else f"{relative}::{name}"
    return next(
        (key for key in lanes if cited == key or (key.endswith("/") and cited.startswith(key))),
        None,
    )


def uncovered(
    cited: Iterable[Citation], selected: Iterable[str], lanes: Mapping[str, str]
) -> list[str]:
    """The citations `selected` (node ids a real marker run returned) does not cover.

    A citation is covered when it refers to at least one selected node id (a file is covered by any
    test in it) or when `lanes` hands it to another lane. Returned as `file` or `file::test`.
    """
    chosen = list(selected)
    return [
        relative if name is None else f"{relative}::{name}"
        for relative, name in cited
        if lane_key(lanes, relative, name) is None and not matching(chosen, relative, name)
    ]


def collect(api_root: Path, expression: str | None, *targets: str) -> frozenset[str]:
    """Node ids of a real `pytest --collect-only -m <expression> <targets>` run from `api_root`.

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
        cwd=api_root,
        env={**os.environ, "PYTEST_ADDOPTS": shlex.join([*options, *targets])},
        capture_output=True,
        text=True,
        # A whole-tree collect takes about 240 s on a quiet hosted runner and past 300 s when the
        # runners are saturated (2026-10-28); the module's own pytest timeout is 900 s.
        timeout=600,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode in (0, 5), "\n".join(output.splitlines()[-40:])
    return frozenset(line for line in result.stdout.splitlines() if _NODE_ID.match(line))
