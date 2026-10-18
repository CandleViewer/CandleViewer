"""#3185 (WS-D15 follow-up): a per-connection budget for the `ws.subscribe.denied` records.

A connection writes at most `DENIAL_AUDITS_PER_WINDOW` records in any sliding
`DENIAL_AUDIT_WINDOW_S` on the injected clock (`SubscriptionServices.clock`); a record leaves the
window once it is a full window old (`23-ws-protocol.md` §4.3). Past that a frame's record is not
written: it counts once in `cv_ws_subscribe_denied_unaudited_total`, the frame's `sub_ok` is
unchanged, and a warning is logged for a connection's first record kept back in a window. A
record kept back takes no place in the budget. A frame refused whole, or one without a refusal
the audit keeps, spends none.

Fake sink and clock only: no timing, no sleeps, no network.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.ws.limits import (
    DENIAL_AUDIT_WINDOW_S,
    DENIAL_AUDITS_PER_WINDOW,
    MAX_TOPICS_PER_SUB,
    REBUILD_MAX_PER_TOPIC,
)
from candleviewer.ws.metrics import (
    CV_WS_NAMES,
    cv_ws_audit_failures_total,
    cv_ws_subscribe_denied_unaudited_total,
)
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    SubscriptionServices,
    handle_sub,
    handle_unsub,
)

N, W = DENIAL_AUDITS_PER_WINDOW, DENIAL_AUDIT_WINDOW_S
SKIPPED = "cv_ws_subscribe_denied_unaudited_total"
VIEWER = uuid.UUID(int=0x3185)
#: `forbidden` for a market-data-only principal: refusals the audit keeps (§5.2).
KEPT, KEPT_TOO = "orders", "wallet"
#: Public and refused `unknown_topic`: a refusal the audit does not keep.
NOT_KEPT = "nope.BTCUSDT"
#: Public streams the churn test cycles through: each restarts within its topic's share of the
#: rebuild budget (SR-193, 23 §7.5), so only the denial budget is under test.
CHURN = tuple(f"ticker.{base}USDT" for base in ("BTC", "ETH", "SOL", "XRP"))
_PROTOCOL = Path(__file__).resolve().parents[5] / "docs" / "plan" / "23-ws-protocol.md"


class _Clock:
    """The injected monotonic clock: the test sets `now`; nothing reads the host's."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Sink:
    """The audit sink: each `emit` is one append. With `fail`, every append raises."""

    def __init__(self, *, fail: bool = False) -> None:
        self.records: list[dict[str, Any]] = []
        self.calls = 0
        self.fail = fail

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls += 1
        if self.fail:
            raise OSError("audit WAL unavailable")
        self.records.append({"action": action, **kw})


def _conn(sink: _Sink, clock: _Clock | None = None) -> ConnectionAuthz:
    perms = frozenset({Permission.MARKETDATA_READ})
    principal = PrincipalSnapshot(VIEWER, frozenset({"viewer"}), perms)
    return ConnectionAuthz(principal, SubscriptionServices(audit=sink, clock=clock or _Clock()))


async def _sub(conn: ConnectionAuthz, *topics: str) -> dict[str, Any]:
    """One `sub` frame through `handle_sub`, which sends exactly one reply."""
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    await handle_sub(conn, {"t": "sub", "id": "s", "p": {"topics": list(topics)}}, send, now_ms=1)
    (reply,) = sent
    return reply


def _skipped() -> float:
    (family,) = cv_ws_subscribe_denied_unaudited_total.collect()
    return next(s.value for s in family.samples if s.name == SKIPPED)


def _failures() -> dict[str, float]:
    (family,) = cv_ws_audit_failures_total.collect()
    return {s.labels["reason"]: s.value for s in family.samples if s.name.endswith("_total")}


async def test_the_budget_writes_the_nth_record_and_counts_the_next_one() -> None:
    """The boundary, in one window: `N` frames with a kept refusal write `N` records; the next
    reaches no writer and counts one record kept back, which is no audit failure."""
    sink, clock = _Sink(), _Clock()
    conn = _conn(sink, clock)
    before, failed = _skipped(), _failures()
    for i in range(N):
        clock.now = i * 0.5
        await _sub(conn, KEPT)
    assert (len(sink.records), _skipped()) == (N, before)
    await _sub(conn, KEPT)
    assert (sink.calls, _skipped() - before, _failures()) == (N, 1, failed)


async def test_the_reply_past_the_budget_is_the_reply_within_it() -> None:
    sink = _Sink()
    conn = _conn(sink)
    first = await _sub(conn, KEPT, KEPT_TOO, NOT_KEPT)
    for _ in range(N - 1):
        await _sub(conn, KEPT)
    over = await _sub(conn, KEPT, KEPT_TOO, NOT_KEPT)
    assert len(sink.records) == N and over == first
    codes = [r["error"]["code"] for r in over["p"]["results"]]
    assert codes == ["forbidden", "forbidden", "unknown_topic"]


async def test_a_record_kept_back_counts_once_however_many_refusals_it_holds() -> None:
    sink = _Sink()
    conn = _conn(sink)
    for _ in range(N):
        await _sub(conn, KEPT)
    before = _skipped()
    private = ["orders", "positions", "executions", "wallet"]
    reply = await _sub(conn, *(private * MAX_TOPICS_PER_SUB)[:MAX_TOPICS_PER_SUB])
    assert len(reply["p"]["results"]) == MAX_TOPICS_PER_SUB
    assert (len(sink.records), _skipped() - before) == (N, 1)


async def test_the_window_slides_on_the_injected_clock() -> None:
    """Records at 0, 1, ..., N-1 s. Just short of a window after the first, the next is kept
    back. A full window after it the first has left, so one more is written, and then one a
    second as the others age out."""
    sink, clock = _Sink(), _Clock()
    conn = _conn(sink, clock)
    for i in range(N):
        clock.now = float(i)
        await _sub(conn, KEPT)
    before = _skipped()
    clock.now = W - 1e-6
    await _sub(conn, KEPT)
    assert (len(sink.records), _skipped() - before) == (N, 1)
    clock.now = W
    await _sub(conn, KEPT)
    assert len(sink.records) == N + 1
    await _sub(conn, KEPT)  # the record of 1 s is still in the window
    assert (len(sink.records), _skipped() - before) == (N + 1, 2)
    clock.now = W + 1.0
    await _sub(conn, KEPT)
    assert len(sink.records) == N + 2


async def test_a_record_kept_back_takes_no_place_in_the_budget() -> None:
    """A full window after the written records the whole budget is back, however many records
    were kept back in between: a connection past it cannot lengthen its own wait."""
    sink, clock = _Sink(), _Clock()
    conn = _conn(sink, clock)
    for _ in range(N):
        await _sub(conn, KEPT)
    clock.now = W / 2
    for _ in range(5):
        await _sub(conn, KEPT)
    clock.now = W
    for _ in range(N):
        await _sub(conn, KEPT)
    assert len(sink.records) == 2 * N


async def test_a_sub_refused_whole_writes_nothing_and_spends_no_budget() -> None:
    sink = _Sink()
    conn = _conn(sink)
    before = _skipped()
    for _ in range(N + 1):
        reply = await _sub(conn, *[KEPT] * (MAX_TOPICS_PER_SUB + 1))
        assert (reply["t"], reply["p"]["code"]) == ("err", "too_many_topics")
    assert (sink.records, _skipped()) == ([], before)
    for _ in range(N):
        await _sub(conn, KEPT)
    assert len(sink.records) == N


async def test_a_frame_without_a_kept_refusal_spends_no_budget() -> None:
    sink = _Sink()
    conn = _conn(sink)
    for _ in range(N + 1):
        await _sub(conn, NOT_KEPT)
    for _ in range(N):
        await _sub(conn, KEPT)
    assert len(sink.records) == N


async def test_without_an_audit_sink_the_budget_is_never_spent_counted_or_logged() -> None:
    """The budget is spent only when the audit sink is wired: with none, no record is written, so
    none is kept back, counted or logged, however many refused frames come."""
    perms = frozenset({Permission.MARKETDATA_READ})
    principal = PrincipalSnapshot(VIEWER, frozenset({"viewer"}), perms)
    conn = ConnectionAuthz(principal, SubscriptionServices(audit=None, clock=_Clock()))
    before = _skipped()
    with capture_logs() as logs:
        for _ in range(N + 1):
            await _sub(conn, KEPT)
    assert (_skipped() - before, logs, len(conn._denial_audits)) == (0, [], 0)


async def test_a_record_handed_to_the_writer_spends_its_place_whether_or_not_it_lands() -> None:
    """The budget is taken before the bounded emit: a write that fails still spent its place and
    counts `error`, as before, and past the budget nothing reaches the writer."""
    sink = _Sink(fail=True)
    conn = _conn(sink)
    failed = _failures()["error"]
    for _ in range(N + 3):
        await _sub(conn, KEPT)
    assert (sink.calls, _failures()["error"] - failed) == (N, N)


async def test_the_budget_is_the_connections_and_survives_unsub_and_sub_churn() -> None:
    """Per connection, not per subscription: subscribing and dropping a topic between the denied
    frames leaves the budget as it is; another connection of the same user has its own. The
    churn goes round `CHURN`, so no topic restarts more than its rebuild share allows."""
    assert len(CHURN) * REBUILD_MAX_PER_TOPIC >= N
    sink = _Sink()
    conn = _conn(sink)
    for i in range(N):
        public = CHURN[i % len(CHURN)]
        await _sub(conn, KEPT)
        (held,) = (await _sub(conn, public))["p"]["results"]
        unsub = {"t": "unsub", "id": "u", "p": {"topics": [public]}}
        ended = {"ch": public, "ok": True, "ended": [{"sub_id": held["sub_id"]}]}  # §5.3, #3218
        assert (held["ok"], handle_unsub(conn, unsub, 1)["p"]["results"]) == (True, [ended])
    await _sub(conn, KEPT)
    assert len(sink.records) == N
    await _sub(_conn(sink), KEPT)
    assert len(sink.records) == N + 1


async def test_the_warning_is_logged_for_a_connections_first_record_kept_back_in_a_window() -> None:
    sink, clock = _Sink(), _Clock()
    conn = _conn(sink, clock)
    for _ in range(N):
        await _sub(conn, KEPT)
    with capture_logs() as logs:
        for _ in range(3):
            await _sub(conn, KEPT)  # kept back at 0 s: the one warning of this window
        clock.now = W - 1.0
        await _sub(conn, KEPT)  # kept back, same window: no line
        clock.now = W
        for _ in range(N + 1):
            await _sub(conn, KEPT)  # the budget is back; the last is kept back: a new window
    lines = [
        (e["log_level"], e["connection_id"], e["actor_user_id"], e["limit"], e["window_s"])
        for e in logs
        if e["event"] == "ws subscribe-denied audit over budget"
    ]
    assert lines == [("warning", conn.connection_id, VIEWER, N, W)] * 2


def test_the_contract_states_the_budget_and_its_window() -> None:
    """§4.3 gives both in prose, so a change to either constant has to change the contract."""
    text = _PROTOCOL.read_text(encoding="utf-8")
    assert f"at most {N} `ws.subscribe.denied` records (§5.2) in any sliding {W:g} s window" in text


def test_the_counter_is_catalogued_live_unlabelled_and_served_by_ws() -> None:
    (spec,) = [s for s in CATALOGUE if s.name == SKIPPED]
    assert (spec.kind, spec.labels, spec.status, spec.exported) == ("counter", (), "live", True)
    assert SKIPPED in CV_WS_NAMES


#: Mostly short gaps, so a window fills; sometimes a window's length or more, so it slides.
_GAPS = st.one_of(
    st.just(0.0),
    st.floats(0.0, 3.0, allow_nan=False),
    st.sampled_from([W - 1e-6, W, W + 1e-6]),
    st.floats(0.0, 2 * W, allow_nan=False),
)
#: Most frames hold a kept refusal; the list is longer than the budget.
_FRAMES = st.tuples(st.sampled_from([True, True, True, False]), _GAPS)


@given(st.lists(_FRAMES, min_size=N + 1, max_size=4 * N))
def test_the_budget_matches_a_brute_force_sliding_window(steps: list[tuple[bool, float]]) -> None:
    """Any run of frames, with or without a kept refusal, at any spacing: a frame's record is
    written exactly when fewer than `N` written ones are under a window old, each other frame with
    a kept refusal counts one kept back, and the connection never holds more than `N` stamps."""
    sink, clock = _Sink(), _Clock()
    conn = _conn(sink, clock)
    written: list[float] = []
    kept_back, before = 0, _skipped()

    async def run() -> None:
        nonlocal kept_back
        for kept, gap in steps:
            clock.now += gap
            await _sub(conn, KEPT if kept else NOT_KEPT)
            if kept and sum(1 for t in written if clock.now - t < W) < N:
                written.append(clock.now)
            elif kept:
                kept_back += 1
            assert len(sink.records) == len(written)
            assert len(conn._denial_audits) <= N  # C-2.18: bounded state

    asyncio.run(run())
    assert _skipped() - before == kept_back
