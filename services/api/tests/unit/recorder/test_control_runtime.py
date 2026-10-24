"""#492 S9: `RuntimeRecordingControl` over the real `RecordingPolicy` (in memory), its rows read
back from the policy's store, a relax guard standing in for #2188 S3c's, and a fake feed. Status
entries carry the stored streams and depth, the live reasons, `start_refusal` first in
`refusals`, `linger_until` from the policy's wall clock, and rolling-hour counts; a join is
`held_hidden` and keeps the row's settings; an unpin or a lower retention the view does not cover
is refused before any record or write."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from candleviewer.api.recording_writes import make_recording_writes_router
from candleviewer.app import bind_recording_runtime
from candleviewer.audit.access import AuditPrincipal
from candleviewer.observability.context import bind_context
from candleviewer.recorder import control as rc
from candleviewer.recorder.control_runtime import HourWindows, RuntimeRecordingControl
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy, user_actor
from candleviewer.recorder.status import Budget
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, Mem
from tests.unit.recorder._s3c_policy import S3cPolicy

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
OWNER, USER = user_actor("00000000-0000-4000-8000-000000000001"), user_actor("u-2")
CONFIG = PolicyConfig(max_symbols=5)


class _Rows:
    """The row port over the policy's in-memory store, as `SqlAlchemyRecordingReads` reads it."""

    def __init__(self, store: Mem) -> None:
        self.store, self.states, self.writes = store, dict[str, str](), list[Any]()

    def _out(self, r: dict[str, Any]) -> dict[str, Any]:
        state = self.states.get(r["symbol"])
        return dict(id=r["id"], symbol=r["symbol"], reason=r["reason"], pinned=r["pinned"],
                    streams=r["streams"], depth=r["orderbook_depth"] or 200,
                    retention_days=r.get("retention_days"), added_by=r["added_by"],
                    session_state=state, session_started_at=NOW if state else None)  # fmt: skip

    async def recorded_page(
        self, *, env: str, after: tuple[str, str] | None, limit: int, hidden: tuple[str, ...],
        **filters: Any,
    ) -> list[dict[str, Any]]:  # fmt: skip
        live = [r for r in self.store.rows.values() if r["env"] == env and not r["removed"]]
        keyed = sorted((r["symbol"], r["id"], r) for r in live if r["reason"] not in hidden)
        return [self._out(r) for s, i, r in keyed if after is None or (s, i) > after][:limit]

    async def recorded_row(self, entry_id: str, *, env: str) -> dict[str, Any] | None:
        r = self.store.rows.get(entry_id)
        return None if r is None or r["removed"] or r["env"] != env else self._out(r)


@dataclass(frozen=True)
class _Wiring:  # #2188 S4b's `RecorderWiring`, field for field
    policy: S3cPolicy
    rows: _Rows
    budget: Budget | None
    env: str


@pytest.fixture
async def env(clock: FakeClock, bus: FakeBus, audit: FakeAudit, store: Mem) -> AsyncIterator[Any]:
    clock.t = NOW.timestamp()  # the policy's wall-clock seconds
    disk = [False]
    policy = RecordingPolicy(bus=bus, audit=audit, env="demo", now=clock, recorded=store,
                             disk_refuses=lambda: disk[0], config=CONFIG)  # fmt: skip
    policy.positions_reloaded()
    rows = _Rows(store)

    async def days(row_id: str, value: int | None) -> bool:
        rows.writes.append((row_id, value))
        store.rows[row_id]["retention_days"] = value
        return True

    p = S3cPolicy(policy, days, default_days=30)
    control = RuntimeRecordingControl(
        _Wiring(p, rows, None, "demo"), config=CONFIG, default_retention_days=30,
        now=lambda: datetime.fromtimestamp(clock.t, UTC),
    )  # fmt: skip
    yield SimpleNamespace(p=p, rows=rows, c=control, clock=clock, audit=audit, disk=disk)
    await policy.stop()


async def _one(c: RuntimeRecordingControl, symbol: str) -> rc.RecordedEntry:
    return next(e for e in (await c.status()).entries if e.symbol == symbol)


async def test_status_carries_the_stored_settings_the_policy_and_a_stop_that_lingers(
    env: Any,
) -> None:
    entry, prior = await env.c.add("BTCUSDT", rc.EntrySpec(("trades",), 50), OWNER,
                                   restricted=False)  # fmt: skip
    assert prior is None and (entry.streams, entry.depth, entry.reasons) == (
        ("trades",), 50, ("manual",))  # fmt: skip
    status = await env.c.status()
    assert status.policy == CONFIG and status.entries == (entry,)
    stopped = await env.c.remove(entry.id, OWNER)
    assert env.rows.store.active("BTCUSDT") is None  # the store dropped the unpinned row
    assert stopped == await _one(env.c, "BTCUSDT")  # yet the status lists it while it lingers
    assert stopped is not None
    until = NOW + timedelta(seconds=CONFIG.autostop_grace_s)
    assert (stopped.lingering, stopped.linger_until, stopped.streams) == (True, until, ("trades",))
    assert await env.c.get(entry.id) == stopped  # readable by id while it lingers
    env.clock.advance(CONFIG.autostop_grace_s)
    await env.p.tick()  # the lifespan's tick: the grace ends, the session stops
    assert (await env.c.status()).entries == () and await env.c.get(entry.id) is None


async def test_a_live_chart_adds_its_reason_and_refuses_a_stop_unless_forced(env: Any) -> None:
    entry, _ = await env.c.add("BTCUSDT", rc.EntrySpec(), OWNER, restricted=False)
    await env.p.on_chart_opened("BTCUSDT", "c1")
    held = await _one(env.c, "BTCUSDT")
    assert (held.reasons, held.refusals) == (("manual", "chart_open"), ("chart_open",))
    before = env.audit.actions()
    with pytest.raises(rc.StopRefused) as refused:
        await env.c.remove(entry.id, OWNER)
    assert refused.value.causes == ("chart_open",) and env.audit.actions() == before
    await env.c.remove(entry.id, OWNER, force=True)
    assert env.audit.actions() == [*before, "recorder.stop"]


async def test_a_start_refusal_heads_the_refusals_of_a_stored_row(env: Any) -> None:
    env.rows.store._new("SOLUSDT", "demo", "chart_open")  # a row from a past run
    env.disk[0] = True
    await env.p.on_chart_opened("SOLUSDT", "c1")
    env.clock.advance(CONFIG.autostart_delay_s)
    await env.p.tick()
    assert (await _one(env.c, "SOLUSDT")).refusals == ("disk_pressure", "chart_open")


async def test_a_restricted_add_onto_a_row_a_position_holds_is_a_join(env: Any) -> None:
    await env.p.on_position_opened("ETHUSDT", "p1")
    row = env.rows.store.active("ETHUSDT")
    row.update(streams=["trades", "tickers"], orderbook_depth=50, retention_days=90)
    asked = rc.EntrySpec(("liquidations",), 500, pinned=False, retention_days=1)
    joined, prior = await env.c.add("ETHUSDT", asked, USER, restricted=True)
    assert prior is not None and joined.reasons == ("manual", "position_open")
    assert (joined.streams, joined.depth, joined.retention_days, joined.pinned) == (
        ("trades", "tickers"), 50, 90, False)  # fmt: skip
    start = env.audit.records[-1][1]["after_state"]
    assert (env.audit.actions()[-1], start["held_hidden"]) == ("recorder.start", True)
    assert env.rows.writes == []


@pytest.mark.parametrize("change", ["unpin", "lower_by_pin", "lower_by_update", "lower_by_re_add"])
async def test_a_relax_a_restricted_view_does_not_cover_is_refused_before_any_record(
    env: Any, change: str
) -> None:
    entry, _ = await env.c.add("ETHUSDT", rc.EntrySpec(), OWNER, restricted=False)
    await env.c.pin(entry.id, change == "unpin", OWNER, restricted=False, retention_days=60)
    await env.p.on_position_opened("ETHUSDT", "p1")
    records, writes = list(env.audit.records), list(env.rows.writes)
    lower = rc.EntrySpec(retention_days=7)
    with pytest.raises(rc.RelaxRefused) as refused:
        if change in ("unpin", "lower_by_pin"):
            await env.c.pin(entry.id, False, USER, restricted=True, retention_days=7)
        elif change == "lower_by_update":
            await env.c.update(entry.id, lower, USER, restricted=True)
        else:  # the manual cause keeps the row visible: a re-add, not a join
            await env.c.add("ETHUSDT", lower, USER, restricted=True)
    assert (env.audit.records, env.rows.writes) == (records, writes)
    assert not refused.value.recorded  # the route writes the one denied record
    owner = await env.c.pin(entry.id, False, OWNER, restricted=False, retention_days=7)
    assert owner is not None and (owner.pinned, owner.retention_days) == (False, 7)


async def test_a_restricted_view_may_raise_retention_and_relax_a_row_it_fully_sees(
    env: Any,
) -> None:
    entry, _ = await env.c.add("BTCUSDT", rc.EntrySpec(), OWNER, restricted=False)
    raised = await env.c.update(entry.id, rc.EntrySpec(retention_days=90), USER, restricted=True)
    assert raised is not None and raised.retention_days == 90
    lowered = await env.c.update(entry.id, rc.EntrySpec(retention_days=7), USER, restricted=True)
    assert lowered is not None and lowered.retention_days == 7
    kept = await env.c.pin(entry.id, False, USER, restricted=True)  # already unpinned: kept
    assert kept is not None and kept.retention_days == 7 and env.rows.writes[-1] == (entry.id, 7)
    pinned = await env.c.pin(entry.id, True, OWNER, restricted=False, retention_days=9)
    assert pinned is not None and (pinned.pinned, pinned.retention_days) == (True, None)


async def test_update_maps_the_policys_refusals_and_an_unknown_id_is_none(env: Any) -> None:
    await env.p.on_position_opened("ETHUSDT", "p1")
    auto = await _one(env.c, "ETHUSDT")
    with pytest.raises(rc.ChangeRefused) as refused:
        await env.c.update(auto.id, rc.EntrySpec(depth=50), OWNER, restricted=False)
    assert refused.value.rule == "not_manual"
    entry, _ = await env.c.add("BTCUSDT", rc.EntrySpec(), OWNER, restricted=False)
    with pytest.raises(rc.ChangeRefused) as invalid:
        await env.c.update(entry.id, rc.EntrySpec(depth=7), OWNER, restricted=False)
    assert (invalid.value.rule, invalid.value.field) == ("depth_allowed", "depth")
    changed = await env.c.update(entry.id, rc.EntrySpec(("tickers",)), OWNER, restricted=False)
    assert changed is not None and changed.streams == ("tickers",)
    gone = "e1000000-0000-4000-8000-000000000099"
    assert await env.c.update(gone, rc.EntrySpec(depth=50), OWNER, restricted=False) is None
    assert await env.c.pin(gone, True, OWNER, restricted=False) is None
    assert await env.c.remove(gone, OWNER) is None


async def test_list_and_status_carry_the_feeds_rolling_hour(env: Any) -> None:
    for symbol in ("BTCUSDT", "ETHUSDT"):
        await env.c.add(symbol, rc.EntrySpec(), OWNER, restricted=False)
    env.rows.states["BTCUSDT"] = "recording"
    env.c.note("BTCUSDT", rows=40)
    env.clock.advance(1800)
    env.c.note("BTCUSDT", rows=2, resyncs=1)
    page = await env.c.list(rc.EntryQuery(limit=1))
    btc = page.items[0]
    assert page.has_more and (btc.state, btc.rows_last_hour, btc.resyncs_last_hour) == (
        "recording", 42, 1)  # fmt: skip
    assert btc.last_event_at == NOW + timedelta(seconds=1800)
    env.clock.advance(1900)  # the first minute has left the hour
    assert (await _one(env.c, "BTCUSDT")).rows_last_hour == 2


def test_the_hour_windows_are_bounded() -> None:
    at = [NOW]
    windows = HourWindows(lambda: at[0], max_symbols=2)
    for minute in range(90):
        at[0] = NOW + timedelta(minutes=minute)
        windows.note("BTCUSDT", rows=1)
    windows.note("ETHUSDT", resyncs=1)
    windows.note("SOLUSDT", rows=1)  # BTC, the least recently seen, goes
    assert len(windows) == 2 and windows.totals("BTCUSDT") == (0, 0, None)
    assert windows.totals("ETHUSDT") == (0, 1, None)


def test_the_composition_binds_the_runtime_only_when_the_wiring_exists(env: Any) -> None:
    state = SimpleNamespace(recording_control="stored", recording_writer=None,
                            recording_runtime=None)  # fmt: skip
    bind_recording_runtime(state, None, CONFIG, 30)
    assert vars(state) == dict(recording_control="stored", recording_writer=None,
                               recording_runtime=None)  # fmt: skip
    bind_recording_runtime(state, _Wiring(env.p, env.rows, None, "demo"), CONFIG, 30)
    bound = state.recording_writer
    assert isinstance(bound, RuntimeRecordingControl)
    assert state.recording_control is bound is state.recording_runtime


async def test_a_relax_the_policy_refuses_after_the_check_is_recorded_by_the_policy(
    env: Any,
) -> None:
    """The view changed between the port's check and the write: the policy's denied record."""
    entry, _ = await env.c.add("ETHUSDT", rc.EntrySpec(), OWNER, restricted=False)
    await env.c.pin(entry.id, True, OWNER, restricted=False)
    await env.p.on_position_opened("ETHUSDT", "p1")
    answers = iter([True, False])  # the port's check passes; the policy's own refuses
    env.p.relax_allowed = lambda symbol, *, restricted: next(answers)
    with pytest.raises(rc.RelaxRefused) as refused:
        await env.c.pin(entry.id, False, USER, restricted=True)
    assert refused.value.recorded and env.audit.records[-1][0] == "retention.change"
    assert env.audit.records[-1][1]["outcome"] == "denied" and env.rows.store.active("ETHUSDT")[
        "pinned"]  # fmt: skip


async def test_a_fresh_add_whose_row_a_hidden_cause_holds_by_then_refuses_before_the_retention(
    env: Any,
) -> None:
    """No row at the first read; by the second a cause outside the view holds it: the port's
    check runs again before the retention write, so the policy writes no retention record."""
    env.p.relax_allowed = lambda symbol, *, restricted: not restricted
    with pytest.raises(rc.RelaxRefused) as refused:
        await env.c.add("BTCUSDT", rc.EntrySpec(retention_days=7), USER, restricted=True)
    assert not refused.value.recorded and env.rows.writes == []
    actions = env.audit.actions()  # the add landed (the narrow race), recorded; no retention
    assert "recorder.start" in actions and "retention.change" not in actions


async def test_a_row_of_another_env_is_none_to_every_lookup_and_write(env: Any) -> None:
    """C-2.11: the control reads and writes only its wiring's env; another env's id is unknown."""
    row = env.rows.store._new("ETHUSDT", "live", "manual")
    for call in (env.c.get(row["id"]),
                 env.c.pin(row["id"], True, OWNER, restricted=False),
                 env.c.update(row["id"], rc.EntrySpec(retention_days=90), OWNER, restricted=False),
                 env.c.remove(row["id"], OWNER, force=True)):  # fmt: skip
        assert await call is None
    assert (env.rows.writes, env.audit.records) == ([], [])
    assert (row["pinned"], row.get("retention_days"), row["removed"]) == (False, None, False)


class _Caller:
    """The route's resolver and audit for one Owner session with a request id."""

    def __init__(self) -> None:
        user = uuid.UUID(OWNER.id)
        perms = frozenset({"recording:read", "recording:write"})
        self.p = AuditPrincipal(user, "owner", perms, is_owner=True, request_id=uuid.uuid4())
        self.records: list[tuple[str, dict[str, Any]]] = []

    async def resolve(self, request: Any) -> AuditPrincipal:
        return self.p

    async def emit(self, action: str, **record: Any) -> None:
        self.records.append((action, record))


async def test_the_policys_records_through_the_route_carry_the_request_and_the_actor(
    env: Any,
) -> None:
    """POST through the bound runtime: the policy's `recorder.start` and `retention.change` name
    the request the middleware bound and the session's user."""
    caller, app = _Caller(), FastAPI()

    async def elevated(_session: Any) -> None:
        return None

    app.include_router(make_recording_writes_router(lambda: env.c, caller, caller, elevated,
                                                    lambda _symbol: True))  # fmt: skip
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    with bind_context(request_id=caller.p.request_id):
        added = await http.post("/recording/symbols", json={"symbol": "BTCUSDT",
                                                             "retention_days": 90})  # fmt: skip
    assert added.status_code == 201
    mine = [(a, r) for a, r in env.audit.records if r["actor_user_id"] is not None]
    assert [a for a, _ in mine] == ["recorder.start", "retention.change"]
    assert {(r["request_id"], r["actor_user_id"]) for _, r in mine} == {
        (caller.p.request_id, OWNER.id)}  # fmt: skip
