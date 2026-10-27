"""#4777: the suite-level per-test timeout (pytest-timeout) is configured, a hung await fails only
its own test, with a traceback, while the run goes on, and the overrides go only where they must."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._suite_timeout import timeout_override

_HUNG_THEN_HEALTHY = """\
import asyncio


async def test_hangs() -> None:
    await asyncio.Event().wait()


def test_after() -> None:
    assert True
"""

# A developer's own pytest settings must not reach the inner run.
_SCRUBBED = ("PYTEST_ADDOPTS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD")


def test_suite_timeout_is_120s_with_the_signal_method(pytestconfig: pytest.Config) -> None:
    assert str(pytestconfig.getini("timeout")) == "120"
    assert pytestconfig.getini("timeout_method") == "signal"


def test_suite_timeout_fails_a_hung_await_and_the_run_goes_on(tmp_path: Path) -> None:
    (tmp_path / "test_inner.py").write_text(_HUNG_THEN_HEALTHY)
    env = {name: value for name, value in os.environ.items() if name not in _SCRUBBED}
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
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    out = run.stdout + run.stderr
    assert run.returncode == 1, out
    assert "1 failed, 1 passed" in out, out
    assert "Timeout" in out, out


@pytest.mark.parametrize(
    ("markers", "is_hypothesis", "expected"),
    [
        (set(), False, None),
        ({"integration"}, False, None),
        ({"chaos"}, False, None),
        ({"fuzz"}, False, ((0,), {})),
        ({"harness"}, False, ((0,), {})),
        ({"roundtrip"}, False, ((0,), {})),
        ({"chaos", "integration"}, False, ((0,), {})),
        ({"fuzz", "timeout"}, False, None),
        (set(), True, ((120.0,), {"method": "thread"})),
        ({"timeout"}, True, None),
        ({"harness"}, True, ((0,), {})),
    ],
)
def test_timeout_override_bounds_only_the_tests_that_need_it(
    markers: set[str],
    is_hypothesis: bool,
    expected: tuple[tuple[float, ...], dict[str, str]] | None,
) -> None:
    override = timeout_override(frozenset(markers), is_hypothesis=is_hypothesis, default_s=120.0)
    if expected is None:
        assert override is None
    else:
        assert override is not None
        assert (override.mark.args, dict(override.mark.kwargs)) == expected
