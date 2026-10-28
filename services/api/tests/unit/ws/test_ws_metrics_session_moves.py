"""E17-T06 (#571), test plan "Integration": after a scripted WS session (connect, subscribe, resync,
overflow, close) every expected metric moved (the label audits: the `_labels` module).

The session is `_ws_metrics_session.run_session_once` (five connections, once for this module).
The script is deterministic and every assertion is a delta between a scrape before it and one
after, so each count is pinned exactly; a byte size is only asserted positive, as it belongs to
the codec and not to the script.

Deliverable of #571 (Scope / Deliverables) -> series asserted:

* connection count and class gauges: `cv_ws_connections_in_use`, `cv_ws_connection_class{state}`
  (up while open, back down after the close; `cv_ws_clients` is the ticket's name for the first);
* `cv_ws_topics_per_client` -> `cv_ws_client_topics_depth` (one observation per subscribe step);
* `cv_ws_resync_total{reason}` -> `client_resync` (the client's `resync`) and `backpressure`;
* `cv_ws_overflow_total{reason}` -> `drop`, `resnapshot`, `close_budget`, `withdrawn`;
* `cv_ws_conflated_total{topic_family}` -> `cv_ws_conflated_total{topic}` (`book`), and the
  `cv_ws_coalesced_count` histogram -> `cv_ws_coalesced_updates`;
* `cv_ws_frame_encode_seconds{kind}`, `cv_ws_frame_bytes{kind}` -> `json`, `msgpack`, and the CVWB
  `kind` of a binary book snapshot; `cvwb_frames_encoded_total`, `cvwb_bytes_encoded_total`;
* `cv_ws_snapshot_build_seconds{topic_family}`, `cv_ws_snapshot_bytes{topic_family}` -> `topic`
  `book`, `trades`, `orders` (one public of each shape and a private family);
* `cv_ws_fanout_seconds` (the budget #6 histogram, weighted 1 in `SAMPLE_EVERY`);
* `cv_ws_queue_bytes`, `cv_ws_queue_frames`, `cv_ws_rtt_seconds` (one observation per
  classification, flag on, the probe answered with a `pong`);
* `cv_ws_closes_total{reason}` -> `shutdown`, `slow_consumer`; `cv_ws_auth_failures_total{reason}`;
  `cv_ws_revoked_total{reason}` -> `permission_revoked`; `cv_ws_clock_skew_ms`, and the E17-S01
  (#377) / E17-S02 (#378) `cv_ws_handshake_seconds` and `cv_ws_subscribe_total{topic,result}`.

Not coverable here, each named so nobody reads the gap as an oversight:

* `cv_ws_errors_total{code}`: counted in process only and not served (not on the SR-125 label
  allow-list, #2747), so no scrape shows it; `tests/unit/ws/test_error_registry_runtime.py` owns it.
* `cv_ws_sequence_gaps_detected_total`: the server guarantees it stays zero; it is asserted
  unmoved here, which is its contract.
* `cv_ws_upstream_consumers_in_use{symbol,topic}`, `cv_ws_stale_topics_in_use`: they need the
  ingestion-side `UpstreamRefs` wiring; the rig's refs are inert. The label audit still covers
  whatever such a series holds.
* `cv_ws_overflow_total{drop_share,unmergeable,close_redrop,close_flush_deadline}` and
  `cv_ws_resync_total{upstream_desync,...}`: each needs a different fault (a shared budget, an
  unmergeable window, a second overflow, an expired flush, an upstream gap); the per-series unit
  tests (`test_pipeline_ladder.py`, `test_sequencing.py`) own them. The label audit pins the sets.
* The Grafana panels, the alerts and a frontend mark: other deliverables of the ticket.
"""

from __future__ import annotations

import pytest

from candleviewer.ws._generated.cvwb_layout import KINDS
from candleviewer.ws.lifecycle import CLOSE_REASONS, OTHER_CLOSE_REASON
from candleviewer.ws.metrics import SAMPLE_EVERY
from candleviewer.ws.pacing import ConnectionClass
from tests.unit.ws._ws_metrics_session import Run, run_session_once

#: Frames the sampler stamps: one in `SAMPLE_EVERY` per subscription, weighted by it.
_DELTAS = 2 * SAMPLE_EVERY


@pytest.fixture(scope="module")
def run() -> Run:
    """The scripted session, once for the module: a scrape before, one while connection 1 is open,
    and one after every connection has closed. Every test only reads it."""
    return run_session_once()


def test_connection_gauges_rise_while_open_and_return_after_close(run: Run) -> None:
    """Connection count and class gauges (the ticket's `cv_ws_clients`, the classes)."""
    assert run.up("cv_ws_connections_in_use") == 1
    assert run.up("cv_ws_connection_class", state="healthy") == 1
    assert run.delta("cv_ws_connections_in_use") == 0
    assert all(run.delta("cv_ws_connection_class", state=c.value) == 0 for c in ConnectionClass)


def test_handshake_and_clock_skew_are_observed(run: Run) -> None:
    """E17-S01: a handshake is timed at each `auth_ok` (connections 1, 2, 3 and the flag-off one:
    4); the clock skew at each `hello`, so the failed-auth connection adds one (5)."""
    assert run.delta("cv_ws_handshake_seconds_count") == 4
    assert run.delta("cv_ws_clock_skew_ms_count") == 5


def test_topics_depth_is_one_observation_per_subscribe_step(run: Run) -> None:
    """`cv_ws_topics_per_client`: connection 1 subscribes three topics (depth 1, 2, 3, read while
    it is open); over the session: connection 1 again after its `unsub` (2), connection 3 (1, 2)
    and the flag-off one (1): 7 observations of 12."""
    assert run.up("cv_ws_client_topics_depth_count") == 3
    assert run.up("cv_ws_client_topics_depth_sum") == 1 + 2 + 3
    assert run.delta("cv_ws_client_topics_depth_count") == 7
    assert run.delta("cv_ws_client_topics_depth_sum") == (1 + 2 + 3) + 2 + (1 + 2) + 1


@pytest.mark.parametrize(
    ("topic", "ok"),
    [("book", 3), ("trades", 1), ("orders", 2)],
    ids=lambda v: str(v),
)
def test_subscribe_results_count_each_topic_family(run: Run, topic: str, ok: int) -> None:
    """E17-S02 `cv_ws_subscribe_total{topic,result}`: `book` on connections 1, 3 and the flag-off
    one, `trades` on connection 1, `orders` on connections 1 and 3; nothing was refused."""
    assert run.delta("cv_ws_subscribe_total", topic=topic, result="ok") == ok


@pytest.mark.parametrize(
    ("topic", "builds", "sized"),
    [("book", 3, 5), ("trades", 1, 1), ("orders", 2, 2)],
)
def test_snapshots_are_timed_and_sized_by_topic_family(
    run: Run, topic: str, builds: int, sized: int
) -> None:
    """`cv_ws_snapshot_build_seconds{topic}` and `cv_ws_snapshot_bytes{topic}`: a build per
    subscribe; the book is sized two more times, by the client's `resync` and the ladder's
    `backpressure` re-snapshot, which re-send a cached body and build nothing."""
    assert run.delta("cv_ws_snapshot_build_seconds_count", topic=topic) == builds
    assert run.delta("cv_ws_snapshot_bytes_count", topic=topic) == sized
    assert run.delta("cv_ws_snapshot_bytes_sum", topic=topic) > 0  # the size is the codec's


def test_fanout_is_observed_in_sample_weights(run: Run) -> None:
    """Budget #6 `cv_ws_fanout_seconds`: one frame in `SAMPLE_EVERY` is stamped and observed with
    that weight: the 64 deltas of connection 1 stamp two, the flag-off connection's one. The
    fake clock does not move between a stamp and the write, so the observed time is exactly 0."""
    assert run.delta("cv_ws_fanout_seconds_count") == _DELTAS + SAMPLE_EVERY
    assert run.delta("cv_ws_fanout_seconds_sum") == 0


@pytest.mark.parametrize(("kind", "frames"), [("json", _DELTAS), ("msgpack", SAMPLE_EVERY)])
def test_frame_encode_time_and_size_are_observed_per_codec(
    run: Run, kind: str, frames: int
) -> None:
    """`cv_ws_frame_encode_seconds{kind}` and `cv_ws_frame_bytes{kind}`: `json` from connection 1
    (the pipeline's one encode per sampled delta, weighted), `msgpack` from the flag-off one (the
    writer's)."""
    assert run.delta("cv_ws_frame_encode_seconds_count", kind=kind) == frames
    assert run.delta("cv_ws_frame_bytes_count", kind=kind) == frames
    assert run.delta("cv_ws_frame_bytes_sum", kind=kind) > 0  # the size is the codec's


def test_cvwb_binary_frames_are_counted_by_kind(run: Run) -> None:
    """`cvwb_frames_encoded_total{kind}` and `cvwb_bytes_encoded_total{kind}`: the one binary book
    snapshot encodes one `book_snapshot` part and no other kind."""
    moved = {v.name: run.delta("cvwb_frames_encoded_total", kind=v.name) for v in KINDS.values()}
    assert {k: n for k, n in moved.items() if n} == {"book_snapshot": 1}
    size = run.delta("cvwb_bytes_encoded_total", kind="book_snapshot")
    assert size > 0  # the size is the codec's; the frame series sees the same bytes
    assert run.delta("cv_ws_frame_bytes_sum", kind="book_snapshot") == size
    assert run.delta("cv_ws_frame_encode_seconds_count", kind="book_snapshot") == 1


def test_resyncs_count_by_reason(run: Run) -> None:
    """`cv_ws_resync_total{reason}`: the client's `resync` and the ladder's `backpressure`; the
    routine `initial` attach is not counted (it has no series)."""
    assert run.delta("cv_ws_resync_total", reason="client_resync") == 1
    assert run.delta("cv_ws_resync_total", reason="backpressure") == 1
    assert ("cv_ws_resync_total", frozenset({("reason", "initial")})) not in run.after


@pytest.mark.parametrize(
    ("reason", "moved"),
    [("drop", 1), ("resnapshot", 1), ("close_budget", 1), ("withdrawn", 3)],
)
def test_overflow_counts_each_ladder_step_by_reason(run: Run, reason: str, moved: int) -> None:
    """`cv_ws_overflow_total{reason}`: the drop and the re-snapshot of the parked writer, the
    budget close of the slow consumer, and the three `orders` frames a withdrawal dropped."""
    assert run.delta("cv_ws_overflow_total", reason=reason) == moved


def test_merged_window_is_counted_as_conflated_and_coalesced(run: Run) -> None:
    """`cv_ws_conflated_total{topic}` (the ticket's `topic_family`): a window of three book
    deltas conflates two; `cv_ws_coalesced_updates` observes it once, with three updates."""
    assert run.delta("cv_ws_conflated_total", topic="book") == 2
    assert run.delta("cv_ws_coalesced_updates_count") == 1
    assert run.delta("cv_ws_coalesced_updates_sum") == 3


def test_queue_depth_and_rtt_are_observed_once_per_classification(run: Run) -> None:
    """`cv_ws_queue_bytes`, `cv_ws_queue_frames` and `cv_ws_rtt_seconds`: one observation per
    classification of a flag-on connection, so all three move together: the 64 deltas, the
    re-snapshot's and the overflow's classifications, and the closing ones: 66."""
    assert run.delta("cv_ws_rtt_seconds_count") == 66
    assert run.delta("cv_ws_queue_bytes_count") == 66
    assert run.delta("cv_ws_queue_frames_count") == 66


def test_closes_count_by_reason(run: Run) -> None:
    """`cv_ws_closes_total{reason}`: the planned shutdowns (connection 1 and the flag-off one)
    and the slow consumer; no other reason moved (the two client disconnects count none)."""
    assert run.delta("cv_ws_closes_total", reason="shutdown") == 2
    assert run.delta("cv_ws_closes_total", reason="slow_consumer") == 1
    others = {*CLOSE_REASONS, OTHER_CLOSE_REASON} - {"shutdown", "slow_consumer"}
    assert {r for r in others if run.delta("cv_ws_closes_total", reason=r)} == set()


def test_failed_auth_and_withdrawn_grant_are_counted_by_reason(run: Run) -> None:
    """`cv_ws_auth_failures_total{reason}` and `cv_ws_revoked_total{reason}`."""
    assert run.delta("cv_ws_auth_failures_total", reason="missing_token") == 1
    assert run.delta("cv_ws_revoked_total", reason="permission_revoked") == 1


def test_server_sequence_gaps_stay_at_zero(run: Run) -> None:
    """`cv_ws_sequence_gaps_detected_total` is the server's guarantee: a clean session leaves it."""
    assert ("cv_ws_sequence_gaps_detected_total", frozenset()) in run.after  # served, not absent
    assert run.delta("cv_ws_sequence_gaps_detected_total") == 0
