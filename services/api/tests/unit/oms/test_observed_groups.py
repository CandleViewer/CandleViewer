"""E28-T05 (#909, slice S4b): the order lane's handoff to the `trade_groups` topic
(`oms_wiring.ObservedGroups`, `ObservedSubmissions`, `OmsRuntime._seeded`; 23 §15.5): each
committed write, as stored, on the serving loop, never awaited; the seed before `ready`, retried,
and counted when every read fails."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, call

import pytest
from prometheus_client import generate_latest
from structlog.testing import capture_logs

from candleviewer.accounts import errors
from candleviewer.accounts.trade_groups import GroupReplay, GroupUpdate, record_from_rows
from candleviewer.domain.primitives import GroupId
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.repository import WriteTimer
from candleviewer.oms_lane import Serving
from candleviewer.oms_wiring import (
    SEED_ATTEMPTS,
    SEED_FAILURES,
    SWEEP_RETRY_S,
    GroupStores,
    ObservedGroups,
    ObservedSubmissions,
    OmsRuntime,
    OmsStores,
)
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import trade_groups as tgs
from candleviewer.storage.repositories.submissions import FirstPersisted
from tests.unit.accounts.test_trade_group_repository import (
    _CALLS,
    _GROUP,
    _GROUP_ROW,
    _LEG_ROW,
    _RECORD,
    _hook,
    _Store,
)
from tests.unit.oms.test_oms_runtime import World, started, until

_LIVE = replace(_RECORD, group=replace(_GROUP_ROW, env="live"))  # never a demo process's (C-2.11)
_WHOLE = record_from_rows(_RECORD)


class _Groups(_Store):
    """`_Store`, whose `load_group` reads `_RECORD`, or nothing once `gone`."""

    gone = False

    async def load_group(self, group_id: Any) -> Any:
        self.calls.append(("load_group", (group_id,), {}))
        return None if self.gone else _RECORD


def _observed(answer: object = None) -> tuple[ObservedGroups, _Groups, Mock, Mock]:
    """The facade, its store, topic and serving loop, where a notice waits (`_run`) and nothing is
    awaited (`call` refuses)."""
    store, topic = _Groups(answer), Mock(spec=["seed", "created", "leg_changed", "group_changed"])
    serving = Mock(spec=["notify", "call"], call=Mock(side_effect=AssertionError("awaited")))
    return ObservedGroups(store, topic, cast(Serving, serving)), store, topic, serving


def _run(serving: Mock) -> None:
    """The serving loop's turn: each notice, in the order made."""
    for notice in serving.notify.call_args_list:
        notice.args[0](*notice.args[1:], **notice.kwargs)


_ENTRY = {"create": "created", "update_leg": "leg_changed", "update_group": "group_changed"}


@pytest.mark.parametrize("write", list(_ENTRY))
async def test_a_committed_write_is_handed_over_as_stored_on_the_serving_loop(write: str) -> None:
    stored_as = {"create": tgs.GroupCreated(_RECORD), "update_leg": _LEG_ROW}
    observed, _, topic, serving = _observed(stored_as.get(write, _GROUP_ROW))
    stored = await _CALLS[write](observed)
    assert topic.mock_calls == [] and serving.notify.call_count == 1  # nothing ran on the lane
    _run(serving)
    assert topic.mock_calls == [getattr(call, _ENTRY[write])(stored)]


@pytest.mark.parametrize(
    ("write", "answer", "raised"),
    [
        ("create", tgs.GroupExists(tgs.GroupAnchor(_GROUP, True)), None),  # a replay
        ("create", tgs.GroupExists(tgs.GroupAnchor(_GROUP, False)), errors.TradeGroupKeyReuseError),
        ("update_leg", tgs.TradeGroupStoreStaleError(), errors.TradeGroupStaleError),
        ("update_leg", None, errors.AccountNotFoundError),
        ("update_group", StorageTierUnavailable("down"), StorageTierUnavailable),
    ],
)
async def test_a_replay_a_key_reuse_or_a_failed_write_hands_over_nothing(
    write: str, answer: object, raised: type[Exception] | None
) -> None:
    observed, _, _, serving = _observed(answer)
    if raised is None:
        assert isinstance(await _CALLS[write](observed), GroupReplay)
    else:
        with pytest.raises(raised):
            await _CALLS[write](observed)
    assert serving.notify.call_count == 0


async def test_a_notice_the_closed_serving_loop_cannot_take_is_counted_never_raised() -> None:
    closed, metrics = asyncio.new_event_loop(), Metrics("demo")
    closed.close()
    observed = ObservedGroups(_Store(_LEG_ROW), Mock(), Serving(closed, metrics))
    with capture_logs() as logs:
        assert await _CALLS["update_leg"](observed) == _WHOLE.legs[0]  # the write's own answer
    lost = 'oms_lane_notices_failed_total{env="demo",reason="lost"} 1.0'
    assert lost in generate_latest(metrics.registry).decode()
    assert [e["event"] for e in logs] == ["oms_lane_notice_lost"]


@pytest.mark.parametrize("group", [_RECORD, None])  # an entry's group; a reduce-only order's none
async def test_the_first_persist_hands_over_an_entrys_group_adapted_on_the_serving_loop(
    group: Any,
) -> None:
    observed, _, topic, serving = _observed()
    row = SimpleNamespace(order_link_id="l", id=_GROUP, exchange_account_id=_GROUP, state="v")
    persisted = FirstPersisted(cast(Any, row), _GROUP, group, ())
    store = Mock(spec=["create_first"], create_first=AsyncMock(return_value=persisted))
    persists = ObservedSubmissions(store, WriteTimer(), observed)
    first = cast(Any, SimpleNamespace(write_ahead=_hook))
    assert await persists.create_first(first, cast(Any, None), cast(Any, None)) is persisted
    assert topic.mock_calls == []
    _run(serving)
    assert topic.mock_calls == ([call.created(_WHOLE)] if group else [])


@pytest.mark.parametrize("case", ["left", "gone", "stays"])
async def test_a_group_that_leaves_draft_is_handed_over_whole_or_not_at_all(case: str) -> None:
    """A group leaving `draft` is read and handed over as created (the topic holds no draft); a
    failed read is logged and the write still answers; a draft staying one is a plain change."""
    draft = replace(_GROUP_ROW, status="draft")
    observed, store, topic, serving = _observed(draft if case == "stays" else _GROUP_ROW)
    store.gone = case == "gone"
    with capture_logs() as logs:
        group = await observed.update_group(
            GroupId(_GROUP), GroupUpdate(status="submitting"), expected_status="draft"
        )
    _run(serving)
    assert group.status == ("draft" if case == "stays" else "submitting")
    reads = [name for name, _, _ in store.calls if name == "load_group"]
    expected = {"left": [call.created(_WHOLE)], "gone": [], "stays": [call.group_changed(group)]}
    assert topic.mock_calls == expected[case] and len(reads) == (case != "stays")
    failed = {"event": "oms_trade_group_handover_failed", "log_level": "error"}
    why = {"trade_group_id": str(_GROUP), "error": "AccountNotFoundError"}
    assert logs == ([why | failed] if case == "gone" else [])


class _Flaky(_Store):
    """`_Store`, whose open groups' first `failures` reads fail."""

    failures = reads = 0

    async def list_open_groups(self) -> Any:
        self.reads += 1
        if self.reads <= self.failures:
            raise StorageTierUnavailable("down")
        return await super().list_open_groups()


class _SeededWorld(World):
    """The runtime's world, its group store answering the open groups after `failures` reads."""

    failures = 0
    groups: _Flaky

    def stores(self) -> OmsStores:
        self.groups = _Flaky((_RECORD, _LIVE))
        self.groups.failures = self.failures
        return replace(super().stores(), groups=cast(GroupStores, self.groups))


@pytest.mark.parametrize("failures", [0, 1, SEED_ATTEMPTS])
async def test_the_runtime_seeds_the_topic_before_it_is_ready_and_a_failed_seed_never_blocks_it(
    failures: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a submit, admitted once ready, writes a group: the seed is handed over before `ready`,
    so before any write, and its count logged. A failed read is tried again after the sweep's
    first backoff; a seed whose every read fails is counted and logged at critical, and the OMS
    gets ready all the same (R1S-04, R1C-05). One sweep bound wraps every read (RC-03b)."""
    world, ready_at_seed, topic = _SeededWorld(), list[bool](), Mock()
    world.failures = failures
    spans = list[tuple[int, int]]()  # each bounded call's open-group reads, at its start and end
    bounded = OmsRuntime._bounded

    async def spied(oms: OmsRuntime, step: Awaitable[Any]) -> Any:
        reads = world.groups.reads
        try:
            return await bounded(oms, step)
        finally:
            spans.append((reads, world.groups.reads))

    monkeypatch.setattr(OmsRuntime, "_bounded", spied)
    runtime = world.runtime(trade_groups=topic)
    topic.seed.side_effect = lambda _groups: ready_at_seed.append(runtime._ready.is_set())
    with capture_logs() as logs:
        async with started(runtime):
            for flag in world.flags:
                flag.read()
            await until(lambda: runtime.state == "ok")
            parts = runtime._composed()
            assert isinstance(parts.groups, ObservedGroups)
            assert parts.submission._deps.groups is parts.groups
            persists = parts.machines._ports.steps._submissions
            assert isinstance(persists, ObservedSubmissions) and persists._groups is parts.groups
    seeds = [e for e in logs if e["event"].startswith("oms_trade_groups_")]
    text = generate_latest(world.metrics.registry).decode()
    counted = f'{SEED_FAILURES}{{env="demo"}} 1.0' in text
    assert world.groups.reads == min(failures + 1, SEED_ATTEMPTS) and SEED_ATTEMPTS == 3  # 20 §6.2
    assert [(a, b) for a, b in spans if a != b] == [(0, world.groups.reads)]  # one bound for all
    assert world.clock.slept.count(SWEEP_RETRY_S[0]) == min(failures, SEED_ATTEMPTS - 1)
    if failures == SEED_ATTEMPTS:
        failed = {"event": "oms_trade_groups_unseeded", "error": "StorageTierUnavailable"}
        assert topic.mock_calls == [] and seeds == [failed | {"log_level": "critical"}] and counted
    else:  # `_LIVE` is another environment's
        assert topic.mock_calls == [call.seed((_WHOLE,))] and ready_at_seed == [False]
        assert seeds == [{"event": "oms_trade_groups_seeded", "count": 1, "log_level": "info"}]
        assert not counted


async def test_a_cancelled_seed_is_never_held_back() -> None:
    """A cancellation (the stop's) leaves the seed at once: never retried, counted or logged."""
    lane = Mock(spec=["call"], call=AsyncMock(side_effect=asyncio.CancelledError))
    parts = SimpleNamespace(groups=Mock(spec=["seed"]), lane=lane)
    with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
        await World().runtime(trade_groups=Mock())._seeded(cast(Any, parts))
    assert lane.call.await_count == 1 and logs == []
