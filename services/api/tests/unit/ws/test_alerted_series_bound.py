"""E17-T06 (#571): the series the WS alerts read exist at zero from process start, and a bound
zero does not hide an event that happens.

An alert on `increase()` needs a sample to subtract from. A labelled series created by its first
event is a single sample, so the first close or re-snapshot under a reason after every restart is
invisible to it (#2264 found the same for the CSRF counter). Every closed reason is bound at import
instead. A fresh interpreter proves it: another test in this process may already have created a
series, which would make an in-process check vacuous. That interpreter blocks the gateway before
its first import, so an import of it, direct or transitive, fails the probe: `export_ws_metrics`
must serve the close series without it.

The two closes that happened but were never counted (a refused subprotocol, a connection fault)
are pinned as counted, so their bound zero is a real zero. A fault after a close counts under both
reasons, and that is pinned too.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, get_args

import pytest
from prometheus_client import REGISTRY
from starlette.websockets import WebSocketDisconnect

from candleviewer.ws.lifecycle import CLOSE_REASONS, OTHER_CLOSE_REASON
from candleviewer.ws.sequencing import (
    COUNTED_SNAP_REASONS,
    INCIDENT_REASONS,
    SNAP_REASONS,
    SnapReason,
)
from tests.unit.ws.test_lifecycle_socket import _closed, _no_sleep
from tests.unit.ws.test_token_expiry import _JSON, _USER, _Bare, _bare_gateway, _Clock, _open

_API_ROOT = Path(__file__).resolve().parents[3]
_PROBE = """
import json
import sys

sys.modules["candleviewer.ws.gateway"] = None  # first: any import of it, however indirect, raises
from candleviewer.observability.metrics import CollectorRegistry
from candleviewer.ws.metrics import export_ws_metrics

scraped = CollectorRegistry()
export_ws_metrics(scraped, env="demo")


def values(name):
    return {
        s.labels.get("reason", ""): s.value
        for family in scraped.collect()
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
    """`WsOriginRefusalsHigh` reads `cv_ws_closes_total` through `increase()`, as #571's alerts
    will: `origin_forbidden`, `slow_consumer` and the rest must already be series."""
    assert fresh["cv_ws_closes_total"] == {r: 0.0 for r in (*CLOSE_REASONS, OTHER_CLOSE_REASON)}


def test_every_counted_resync_reason_starts_at_zero(
    fresh: dict[str, dict[str, float]],
) -> None:
    """`initial` is a routine attach, never counted; every other snapshot reason is, the incident
    reasons among them."""
    assert "initial" not in COUNTED_SNAP_REASONS
    assert INCIDENT_REASONS <= set(COUNTED_SNAP_REASONS)
    assert fresh["cv_ws_resync_total"] == {r: 0.0 for r in COUNTED_SNAP_REASONS}


def test_snap_reason_type_and_tuple_name_the_same_reasons() -> None:
    """`snapshot`/`resnapshot` rely on the `SnapReason` type to keep the counter's labels closed,
    and the bound series come from `SNAP_REASONS`: the two hand-kept lists must not drift."""
    assert set(get_args(SnapReason)) == set(SNAP_REASONS)


def test_the_sequence_gap_counter_starts_at_zero(fresh: dict[str, dict[str, float]]) -> None:
    assert fresh["cv_ws_sequence_gaps_detected_total"] == {"": 0.0}


# -- the zeros are truthful: a bound reason whose event happens is counted ----------------------


def _closes(reason: str) -> float:
    value = REGISTRY.get_sample_value("cv_ws_closes_total", {"reason": reason})
    assert value is not None, f"cv_ws_closes_total{{reason={reason!r}}} is not bound"
    return value


def test_a_client_offering_no_supported_subprotocol_is_counted_as_unsupported_protocol() -> None:
    """Refused before `accept`, so not through `close_with`: it counts itself, as the origin
    refusal does."""
    before = _closes("unsupported_protocol")
    client = _bare_gateway(None, _Clock()).client  # refused before auth: never asked
    with client, pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/ws", subprotocols=["cv.v2.json"]):
            pass
    assert refused.value.code == 1002
    assert _closes("unsupported_protocol") == before + 1


def test_a_connection_fault_is_counted_as_internal_error() -> None:
    """An authenticator that reports no tz-aware expiry is a server fault: `bye` and 1011."""
    before = _closes("internal_error")
    client = _bare_gateway(("sess", _USER), _Clock()).client
    with client, client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        bye = _open(ws, "any")
        code = _closed(ws)
    assert (bye["p"]["reason"], code) == ("internal_error", 1011)
    assert _closes("internal_error") == before + 1


def test_a_fault_after_a_close_counts_under_both_reasons() -> None:
    """A fault after a `close_with` counts both: that close was initiated, and the fault's own
    `bye` and 1011 supersede it on the wire. The sum over reasons is not a socket-close count, so
    alerts (#571) key on `reason="internal_error"`."""
    closed_by_hub, faulted = _closes("shutdown"), _closes("internal_error")
    bare: _Bare

    async def close_then_report_no_expiry(_token: str) -> Any:
        # `GatewayHub.shutdown` ends in `close_with("shutdown")` for every live socket, this one
        # included. Nothing suspends before the fault below, so the writer never flushes that `bye`.
        await bare.hub.shutdown(sleep=_no_sleep)
        return ("sess", _USER)  # no expiry: the server fault of the test above

    bare = _bare_gateway(close_then_report_no_expiry, _Clock())
    with bare.client, bare.client.websocket_connect("/ws", subprotocols=_JSON) as ws:
        bye = _open(ws, "any")
        code = _closed(ws)
    assert (bye["p"]["reason"], code) == ("internal_error", 1011)  # the one close the wire shows
    assert (_closes("shutdown"), _closes("internal_error")) == (closed_by_hub + 1, faulted + 1)
