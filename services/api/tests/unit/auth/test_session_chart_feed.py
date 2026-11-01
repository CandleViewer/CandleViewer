"""E17-T08: `SessionChart` feeds `machines.session:{id}.state` (23 §6.4). The entry is bound to the
session's user from its row, a stopped chart takes its live entry with it, and a revoked session's
last state stays for the retention (60 s). The registry is the real one; no interpreter is read."""

from __future__ import annotations

import os
import uuid
from typing import Any, cast

from candleviewer.auth.env_keyring import EnvMfaKeyring
from candleviewer.auth.service import AuthService
from candleviewer.auth.session_chart import SessionChart
from candleviewer.ws.topics import EntityScope
from tests.unit.ws._feed_support import Feed

from .auth_fakes import FakeUserRepository
from .mfa_fakes import FakeMfaRepository
from .session_fakes import FakeSessionRepository
from .test_step_up import _T0, _session


def _ch(session_id: uuid.UUID) -> str:
    return f"machines.session:{session_id}.state"


async def test_a_session_chart_publishes_its_entry_bound_to_its_user() -> None:
    feed, row = Feed(), _session(uuid.uuid4())
    chart = SessionChart(feed=feed.port)
    try:
        await chart.record(row, _T0, "REQUEST", replay=True)  # built, then hydrated from the row
        assert feed.registry.scope(_ch(row.id)) == EntityScope(user=row.user_id)
        served = feed.served(_ch(row.id))
        assert served is not None and served["state"] == "active"
        assert served["context_summary"] == {"mfa_satisfied": True, "step_up_failures": 0}
        assert feed.scope_missing() == 0
    finally:
        await chart.stop()
    assert feed.served(_ch(row.id)) is None


class _Refusing:
    """A port whose `bind` raises: a wiring defect on the feed's side."""

    environment, now_ms = "demo", staticmethod(lambda: 1)

    def bind(self, binding: object) -> object:
        raise ValueError("no public entity")


async def test_a_feed_that_cannot_bind_leaves_the_session_chart_working() -> None:
    """No auth behaviour changes: the chart is built, hydrated and driven, and nothing is fed."""
    row = _session(uuid.uuid4())
    chart = SessionChart(feed=cast(Any, _Refusing()))
    try:
        await chart.record(row, _T0, "REQUEST", replay=True)
        assert chart.in_state(str(row.id), "active")
    finally:
        await chart.stop()


async def test_a_revoked_session_keeps_its_last_state_for_60_s() -> None:
    feed, row = Feed(), _session(uuid.uuid4())
    await SessionChart(feed=feed.port).revoke(row, _T0, "admin")  # REVOKE, then the chart stops
    served = feed.served(_ch(row.id))
    assert served is not None and "terminal" in served["tags"]
    assert served["regions"] == {"auth": "revoked", "elevation": "dead"}  # the last terminal step
    assert feed.scope_missing() == 0
    feed.expire()
    assert feed.served(_ch(row.id)) is None


async def test_an_evicted_chart_leaves_no_entry_and_a_rebuilt_one_has_its_own() -> None:
    feed, first, second = Feed(), _session(uuid.uuid4()), _session(uuid.uuid4())
    chart = SessionChart(max_charts=1, feed=feed.port)
    try:
        for row in (first, second):
            await chart.record(row, _T0, "REQUEST", replay=True)
        assert feed.served(_ch(first.id)) is None and feed.served(_ch(second.id)) is not None
        await chart.record(first, _T0, "REQUEST", replay=True)  # rebuilt from its row, evicting
        assert feed.served(_ch(first.id)) is not None and feed.served(_ch(second.id)) is None
        assert len(feed.registry) == 1 and feed.scope_missing() == 0  # one live machine per entity
    finally:
        await chart.stop()


async def test_the_auth_service_gives_its_step_up_charts_the_feed_attached_before_start() -> None:
    feed, row = Feed(), _session(uuid.uuid4())
    service = AuthService(
        FakeUserRepository(),
        pepper="pepper",
        mfa_repository=FakeMfaRepository(),
        mfa_keyring=EnvMfaKeyring(os.urandom(32), os.urandom(32)),
        session_repository=FakeSessionRepository(),
    )
    service.attach_machine_feed(feed.port)
    await service.start(cast(Any, None))  # the key is given: the context is not read
    try:
        await service.step_up.chart.record(row, _T0, "REQUEST", replay=True)
        assert feed.registry.scope(_ch(row.id)) == EntityScope(user=row.user_id)
        assert feed.scope_missing() == 0
    finally:
        await service.stop(1.0)
    assert feed.served(_ch(row.id)) is None  # the chart stopped with the module
