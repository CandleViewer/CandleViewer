"""#4777: the suite-level per-test timeout (pytest-timeout) is configured, and a hung await fails
only its own test, with a traceback, while the run goes on."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_HUNG_THEN_HEALTHY = """\
import asyncio


async def test_hangs() -> None:
    await asyncio.Event().wait()


def test_after() -> None:
    assert True
"""


def test_suite_timeout_is_120s_with_the_signal_method(pytestconfig: pytest.Config) -> None:
    assert str(pytestconfig.getini("timeout")) == "120"
    assert pytestconfig.getini("timeout_method") == "signal"


def test_suite_timeout_fails_a_hung_await_and_the_run_goes_on(tmp_path: Path) -> None:
    (tmp_path / "test_inner.py").write_text(_HUNG_THEN_HEALTHY)
    # The inner run's own 1 s bound stands in for the suite's 120 s; the outer test needs none.
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-o",
            "asyncio_mode=auto",
            "--timeout=1",
            "--timeout-method=signal",
            "-q",
            "test_inner.py",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    out = run.stdout + run.stderr
    assert run.returncode == 1, out
    assert "1 failed, 1 passed" in out, out
    assert "Timeout" in out, out
