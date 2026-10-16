"""E17-T06 (#571): the series the WS alerts read exist at zero from process start.

An alert on `increase()` needs a sample to subtract from. A labelled series created by its first
event is a single sample, so the first `slow_consumer` close or `upstream_desync` re-snapshot after
every restart would never alert (#2264 found the same for the CSRF counter). Every closed reason is
bound at import instead. A fresh interpreter proves it: another test in this process may already
have created a series, which would make an in-process check vacuous.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from candleviewer.ws.lifecycle import CLOSE_REASONS
from candleviewer.ws.sequencing import SNAP_REASONS

_API_ROOT = Path(__file__).resolve().parents[3]
_PROBE = """
import json
from prometheus_client import REGISTRY
from candleviewer.ws import gateway, sequencing  # noqa: F401  (importing them binds the series)


def values(name):
    return {
        s.labels.get("reason", ""): s.value
        for family in REGISTRY.collect()
        for s in family.samples
        if s.name == name
    }


print(
    json.dumps(
        {
            name: values(name)
            for name in (
                "cv_ws_closes_total",
                "cv_ws_resync_total",
                "cv_ws_sequence_gaps_detected_total",
            )
        }
    )
)
"""


@pytest.fixture(scope="module")
def fresh() -> dict[str, dict[str, float]]:
    """What the first scrape of a new process sees."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(_API_ROOT)
    done = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter and a literal probe
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=_API_ROOT,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    parsed: dict[str, dict[str, float]] = json.loads(done.stdout)
    return parsed


def test_every_close_reason_and_the_other_bucket_start_at_zero(
    fresh: dict[str, dict[str, float]],
) -> None:
    """`WsSlowConsumerClosed` and `WsOriginRefusalsHigh` read `cv_ws_closes_total` through
    `increase()`: `slow_consumer` and `origin_forbidden` must already be series."""
    assert fresh["cv_ws_closes_total"] == {r: 0.0 for r in (*CLOSE_REASONS, "other")}


def test_every_counted_resync_reason_starts_at_zero(
    fresh: dict[str, dict[str, float]],
) -> None:
    """`initial` is a routine attach, never counted; every other snapshot reason is."""
    counted = {r for r in SNAP_REASONS if r != "initial"}
    assert "upstream_desync" in counted
    assert fresh["cv_ws_resync_total"] == {r: 0.0 for r in counted}


def test_the_sequence_gap_counter_starts_at_zero(fresh: dict[str, dict[str, float]]) -> None:
    assert fresh["cv_ws_sequence_gaps_detected_total"] == {"": 0.0}
