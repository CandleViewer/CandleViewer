"""E29-X01 AC-07 run again with the real emitters (SR-E29-10), as
`tests/security/ws/test_account_notices.py` hands it to E29-X02 (#982): an account notice reaches
only the sockets granted the account it names. The notices are no longer broadcast by hand:
E29-T05's `StreamNotices` (the private stream's `oms.account_resyncing`) and E29-T06's
`ReconcileNoticesBinding` (reconciliation's `oms.account_stale`, `oms.account_synced`) build each
from the closed table, stamp it with its transition time (`changed_at_ms`, here a fixed clock),
check it and offer it to the gateway on the serving loop (`oms_lane.Serving.notify`), as the OMS
runtime composes them.

A Manager (M) granted account A only is sent no frame that names or counts B when B resynchronises
and goes stale, while a connection granted B (N) is sent each notice, its `exchange_account_ids`
naming B alone; a grant withdrawn from a live socket stops B's notices that follow it while A's
still arrive, and the `s` of its `system` frames stays gap-free (S3). In process on the
conformance gateway, under both subprotocols; `Client.recv` schema-validates every frame.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from functools import partial
from typing import Any
from uuid import UUID

import pytest
from structlog.contextvars import merge_contextvars
from structlog.processors import format_exc_info
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.reconcile_report import STALE_NOTICE, Notice
from candleviewer.oms_lane import Serving
from candleviewer.oms_reconcile_wiring import ReconcileNoticesBinding
from candleviewer.oms_stream_wiring import StreamNotices, account_notice
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.metrics import WITHHELD_REASONS
from tests.contract.ws._harness import OFFERS, reset_wire, use_wire
from tests.security.ws._raw import RawWorld, authenticated, delta, drained, naming, raw_connect
from tests.security.ws.test_account_notices import CHANGED, MARK, _system
from tests.unit.ws._seq_support import ACC_A, ACC_B

NAME = "cv_ws_system_frames_withheld_total"
B = AccountId(ACC_B)  # as the OMS names an account


@pytest.fixture(params=list(OFFERS))
def wire(request: pytest.FixtureRequest) -> Iterator[str]:
    """Each socket's subprotocol, both offers (`tests/security/ws/conftest.py`'s)."""
    token = use_wire(str(request.param))
    try:
        yield str(request.param)
    finally:
        reset_wire(token)


@pytest.fixture
def raw(
    wire: str, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> Iterator[RawWorld]:
    """The conformance gateway's world, its client running (`tests/security/ws/conftest.py`'s)."""
    caplog.set_level(logging.DEBUG)
    w = RawWorld(caplog, capsys, BackpressureConfig())
    with capture_logs(processors=[merge_contextvars, format_exc_info]) as events, w.client:
        w.events = events
        yield w


def _emitters(world: RawWorld) -> tuple[StreamNotices, ReconcileNoticesBinding]:
    """Both producers over the gateway, offering on its loop as the runtime's serving loop, each
    stamping its notices with one fixed transition time."""
    serving = Serving(world.call(asyncio.get_running_loop), Metrics("demo"))
    at = partial(int, CHANGED)
    return (
        StreamNotices(world.gateway, serving, now_ms=at),
        ReconcileNoticesBinding(world.gateway, serving, now_ms=at),
    )


def _notice(account: UUID, reason: Any, severity: Any = None) -> dict[str, Any]:
    return account_notice(account, reason, severity, changed_at_ms=CHANGED)


def _marked(world: RawWorld) -> None:
    """The marker, after every notice already offered: the loop runs its callbacks in order."""
    world.call(world.gateway.broadcast_system, MARK)


def test_e29_ac_07_the_emitted_notices_of_b_never_reach_a_manager_granted_a(raw: RawWorld) -> None:
    m, n = raw.login("m", ACC_A), raw.login("n", ACC_B)
    stream, reconcile = _emitters(raw)
    resyncing = _notice(ACC_B, "oms.account_resyncing")
    stale = _notice(ACC_B, STALE_NOTICE.reason, STALE_NOTICE.severity)
    counted = {reason: delta(NAME, reason=reason) for reason in WITHHELD_REASONS}
    with raw_connect(raw) as cm, raw_connect(raw) as cn:
        authenticated(cm, m)
        authenticated(cn, n)
        drained(cm)
        drained(cn)
        stream.publish(B, reason="oms.account_resyncing")  # E29-T05's producer
        reconcile.publish(B, STALE_NOTICE)  # E29-T06's, as B19 locks the account
        _marked(raw)
        got_m, got_n = _system(drained(cm)), _system(drained(cn))
    assert got_m == [(2, MARK)]  # B's notices took no `s` here (S3); `s` 1 is the snap
    assert naming(cm.seen, ACC_B) == []  # not one frame of M's whole stream
    assert got_n == [(2, resyncing), (3, stale), (4, MARK)]
    rest: list[dict[str, Any]] = [{k: v for k, v in p.items() if k != "exchange_account_ids"}
                                  for _, p in got_n]  # fmt: skip
    assert naming(rest, ACC_B) == []  # the account is in the list alone
    assert {reason: count() for reason, count in counted.items()} == dict.fromkeys(
        WITHHELD_REASONS, 0
    )


def test_e29_a_withdrawn_grant_stops_the_emitted_notices_of_b_and_s_has_no_gap(
    raw: RawWorld,
) -> None:
    n = raw.login("n", ACC_A, ACC_B)
    stream, reconcile = _emitters(raw)
    synced = Notice("oms.account_synced", "info")
    with raw_connect(raw) as c:
        authenticated(c, n)
        drained(c)
        stream.publish(B, reason="oms.account_resyncing")  # N may view B now
        _marked(raw)
        first = _system(drained(c))
        raw.call(partial(raw.amended, n, drop=(ACC_B,)))
        assert "permission_change" in [f["t"] for f in drained(c)]
        mark = len(c.seen)
        reconcile.publish(B, synced)  # B alone: not sent, takes no `s`
        reconcile.publish(AccountId(ACC_A), synced)  # A's, still granted
        _marked(raw)
        later = _system(drained(c))
    assert first == [(2, _notice(ACC_B, "oms.account_resyncing")), (3, MARK)]
    assert later == [(4, _notice(ACC_A, synced.reason, synced.severity)), (5, MARK)]
    assert naming(c.seen[mark:], ACC_B) == []
