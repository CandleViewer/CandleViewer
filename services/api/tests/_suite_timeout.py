"""#4777: which tests get a bound other than the suite's per-test default (pyproject.toml)."""

from __future__ import annotations

import pytest

# The nightly-only heavy lanes run long by design; their jobs' `timeout-minutes` bound them.
NIGHTLY_ONLY_MARKERS: frozenset[str] = frozenset({"fuzz", "harness", "roundtrip"})


def timeout_override(
    markers: frozenset[str], *, is_hypothesis: bool, default_s: float
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
    if is_hypothesis:
        return pytest.mark.timeout(default_s, method="thread")
    return None
