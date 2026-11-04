"""E40-Q02 alert chaos 6, outbox poller stall: the poller stalls while firings keep committing,
the depth builds, the `AlertOutboxBacklog` condition holds for its `for`, and on resume the poller
catches up without a duplicate.

- In-process (local): the real dispatcher's own poll loop, over the in-memory dispatch store, with
  every claim failing (the stall) while each poll samples `cv_outbox_depth` on an injected 15 s
  clock. The rule is read from `infra/prometheus/alerts/system_ticket.yml` and its condition is
  evaluated on the sampled series (promtool, `system_alerts.test.yml`, proves such a series fires
  it). A second case stalls a poller inside a send while it holds a leased batch: another poller
  takes the batch after the lease, and the stalled one, resumed, wins no settle.
- Postgres (CI-only, `chaos and integration`): the same lease case with a real process paused by
  SIGSTOP while it holds a batch on the compose Postgres, then resumed by SIGCONT.
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
from pathlib import Path
from typing import Any

import pytest
import yaml

from candleviewer.alerts.dispatcher import idempotency_key
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.alerts._dispatch_env import Clock, Job, MemStore
from tests.chaos.alerts import _pg
from tests.chaos.alerts._rig import Relay, Wins, dispatch
from tests.chaos.storage import _stack as st

pytestmark = pytest.mark.chaos
RULES = Path(__file__).resolve().parents[5] / "infra/prometheus/alerts/system_ticket.yml"
STEP_S, BACKLOG = 15, 150  # the gauge's sampling period; rows committed during the stall


def backlog_rule() -> tuple[float, float]:
    """`AlertOutboxBacklog`'s threshold and `for` (seconds), as the rule file states them."""
    rules = [r for g in yaml.safe_load(RULES.read_text())["groups"] for r in g["rules"]]
    (rule,) = [r for r in rules if r.get("alert") == "AlertOutboxBacklog"]
    expr = 'max by (env) (cv_outbox_depth{topic="alert.deliver"}) > '
    assert rule["expr"].startswith(expr), rule["expr"]
    hold = re.fullmatch(r"(\d+)m", rule["for"])
    assert hold is not None
    return float(rule["expr"].removeprefix(expr)), int(hold[1]) * 60.0


class StalledStore(MemStore):
    """Every claim fails while `stalled` (firings keep committing, ten a poll); `idle` is set by
    the first claim that finds nothing once resumed."""

    def __init__(self, clock: Clock) -> None:
        super().__init__(clock)
        self.stalled, self.idle = True, asyncio.Event()

    async def claim(self, **kw: Any) -> list[Job]:
        if self.stalled:
            if len(self.rows) < BACKLOG:
                self.fire(["in_app"] * 10)
            raise OSError("claim timed out")
        jobs = await super().claim(**kw)
        if not jobs:
            self.idle.set()
        return jobs


async def test_a_stalled_poller_fires_the_backlog_condition_and_catches_up_once() -> None:
    threshold, hold_s = backlog_rule()
    clock, ticks = Clock(), iter(range(0, 10**7, STEP_S))  # each loop's sample is due
    store, wins, depth = StalledStore(clock), Wins(), list[float]()
    held, since = asyncio.Event(), list[int]()  # since: when the current run over it began

    def metric(name: str, labels: tuple[str, ...]) -> Any:
        if name != "cv_outbox_depth":
            return wins(name, labels)

        class _G:
            def set(self, value: float) -> None:
                depth.append(value)
                at = (len(depth) - 1) * STEP_S
                if value <= threshold:
                    since.clear()
                elif not since:
                    since.append(at)
                elif at - since[0] >= hold_s:  # over the threshold for the rule's `for`
                    held.set()

        return _G()

    d = dispatch(store, None, worker="w", metric=metric, interval_s=0.001,
                 monotonic=lambda: float(next(ticks)))  # fmt: skip
    d.start()
    try:
        async with asyncio.timeout(30):
            await held.wait()  # the stall: depth over the threshold for the rule's `for`
        assert max(depth) == BACKLOG and all(r.status == "queued" for r in store.rows.values())
        store.stalled = False  # resume
        async with asyncio.timeout(30):
            await store.idle.wait()
    finally:
        await d.stop()
    assert [r.status for r in store.rows.values()] == ["sent"] * BACKLOG
    assert all(o.processed and o.attempts == 1 for o in store.outbox.values())
    assert wins.sent == BACKLOG == store.calls.count("sent")  # each once: no duplicate


async def test_a_poller_stalled_holding_a_batch_resumes_without_a_duplicate() -> None:
    clock, wins = Clock(), Wins()
    store = MemStore(clock)
    store.fire(["email"] * 12)
    stalled, release, sent = asyncio.Event(), asyncio.Event(), list[str]()

    class Stall:
        async def send(self, *, idempotency_key: str, **_: Any) -> None:
            sent.append(idempotency_key)
            stalled.set()
            await release.wait()

    a = dispatch(store, Stall(), worker="a", batch=8)
    first = asyncio.ensure_future(a.run_once())
    async with asyncio.timeout(5):
        await stalled.wait()  # `a` holds 8 leased rows, stuck in its first send
    relay = Relay()
    b = dispatch(store, relay, worker="b", metric=wins)
    await b.run_once()
    assert len(relay.keys) == 4  # the 4 rows `a` did not lease; its 8 are still leased
    clock.advance(61)  # `a`'s lease runs out
    await b.run_once()
    release.set()  # `a` resumes: its send returns, its settle and the rest of its batch lose
    async with asyncio.timeout(5):
        assert await first == 8
    assert [r.status for r in store.rows.values()] == ["sent"] * 12 and wins.sent == 12
    assert sorted(relay.keys) == sorted(set(relay.keys)) and len(relay.keys) == 12
    assert sent == [relay.keys[4]]  # only the in-flight send went out twice, the same key


@pytest.mark.integration
async def test_a_sigstopped_poller_holding_a_batch_resumes_without_a_duplicate() -> None:
    await st.ensure_up("postgres", st.pg_up)
    user, alert = await _pg.seeded("{email}")
    repo = SqlAlchemyRelationalRepository(st.pg_dsn(), "alert-chaos-stall")
    relay, wins = Relay(), Wins()
    try:
        store = _pg.firing_store(repo)
        for _ in range(BACKLOG):
            await _pg.fire(store, user, alert, ("email",))
        child = await _pg.Child.spawn({"mode": "stall", "lease_s": 1})
        try:
            in_flight = (await child.until("send ")).removeprefix("send ")
            os.kill(child.proc.pid, signal.SIGSTOP)  # paused, holding a leased batch of 8
            assert await _pg.depth(alert) >= BACKLOG > backlog_rule()[0]
            d = _pg.dispatcher(repo, relay, worker="parent", metric=wins)

            async def caught_up() -> bool:
                await d.run_once()
                return await _pg.depth(alert) == 0

            await st.until(caught_up, "the other poller drained the backlog", timeout_s=_pg.WAIT_S)
            os.kill(child.proc.pid, signal.SIGCONT)
            await child.say("go")  # one in-flight send is blocked on stdin; the rest were skipped
            assert await child.until("done ") == "done won=0"
        finally:
            await child.kill()
    finally:
        await repo.dispose()
    rows = (await _pg.ledger(alert))["rows"]
    assert len(rows) == BACKLOG and all(r["status"] == "sent" and r["ob"] == 1 for r in rows)
    mine = {idempotency_key(int(r["id"])) for r in rows}
    keys = [k for k in relay.keys if k in mine]  # this test's deliveries only
    assert wins.sent >= BACKLOG and len(keys) == len(set(keys)) == BACKLOG
    assert in_flight in keys  # sent twice, the same key: the relay dedupes on it
