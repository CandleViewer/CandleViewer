"""#4777: which tests get a bound other than the suite's per-test default (pyproject.toml)."""

from __future__ import annotations

import os

import pytest

# The nightly-only heavy lanes run long by design; their jobs' `timeout-minutes` bound them.
NIGHTLY_ONLY_MARKERS: frozenset[str] = frozenset({"fuzz", "harness", "roundtrip"})


def suite_default_s(config: pytest.Config) -> float | None:
    """The per-test default pytest-timeout applies, resolved as it does: `--timeout`, then
    `PYTEST_TIMEOUT`, then the ini. None when the plugin is off or the default is unset or 0."""
    if not config.pluginmanager.hasplugin("timeout"):
        return None
    option = config.getoption("timeout", default=None)
    raw = option
    if raw is None:
        raw = os.environ.get("PYTEST_TIMEOUT") or config.getini("timeout")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def timeout_override(
    markers: frozenset[str], *, is_hypothesis: bool, default_s: float | None
) -> pytest.MarkDecorator | None:
    """The timeout mark a test gets instead of the default, or None to keep the default.

    A test's own `timeout` mark always wins. `chaos` is lifted only with `integration`: that pair
    is what the PR lanes exclude (`_job-py.yml`), and the other chaos tests run there. Hypothesis
    treats the signal method's failure as a failing example and replays it with no timer armed,
    so a property test is bounded with the thread method, which ends the run instead of hanging.
    """
    if "timeout" in markers:
        return None
    if markers & NIGHTLY_ONLY_MARKERS or {"chaos", "integration"} <= markers:
        return pytest.mark.timeout(0)
    if is_hypothesis and default_s is not None:
        return pytest.mark.timeout(default_s, method="thread")
    return None
