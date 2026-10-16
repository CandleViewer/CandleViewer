"""Node-id stability of `test_csrf_double_submit.py` (#2717).

A parametrize value that differs per process (a `uuid.uuid4()`, a clock read) is part of the
pytest node id, so two collections of the same module list different ids. That breaks
`pytest --lf` and node-id reruns, forces masking in any tool that diffs two collections, and
would make pytest-xdist refuse the session (every worker must collect the same ids, in order).

A second collection in this process would not see it: the module is imported once and cached. So
the module is collected in two fresh interpreters and the ordered node-id lists are compared.
Nothing is run, the module is not imported into this process, and there is no network.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[3]  # services/api, the pytest rootdir
_MODULE = "tests/security/auth/test_csrf_double_submit.py"
# The test whose two path parameters carried a `uuid.uuid4()` before #2717.
_PATH_PARAMETRIZED = "test_every_unsafe_method_without_token_is_refused"


def _collect_node_ids() -> list[str]:
    """Node ids that `pytest --collect-only` lists for `_MODULE` in a fresh interpreter, in order.

    `-p no:randomly` keeps a shuffling plugin from reordering an otherwise identical list;
    `--no-cov` and `-p no:cacheprovider` keep the child from writing coverage or cache files.
    """
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, no untrusted input (#2717)
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-cov",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            _MODULE,
        ],
        cwd=_API_ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return [line for line in proc.stdout.splitlines() if line.startswith(f"{_MODULE}::")]


def test_csrf_double_submit_node_ids_are_identical_across_two_fresh_collections() -> None:
    first = _collect_node_ids()
    second = _collect_node_ids()

    # Not vacuous: the parametrized test the regression came from was really listed.
    assert any(node.startswith(f"{_MODULE}::{_PATH_PARAMETRIZED}[") for node in first), first
    unstable = sorted(set(first) ^ set(second))
    assert not unstable, f"node ids differ between two collections of {_MODULE}: {unstable}"
    assert first == second, "same node ids but a different order: pytest-xdist needs both equal"
