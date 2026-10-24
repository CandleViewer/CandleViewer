"""#492 S1: the fake behind the recording tests.

`FakeRecorder` mirrors #2188's `PolicyControlSurface` member for member (`surface_mismatches`:
names, signatures, sync versus async); the read-only accessors S3 adds are held to the
signatures agreed on 2026-10-23 (`_Agreed`). It keeps the policy's rules: the cap, a re-add of a
manual entry that changes and records nothing, the depth and stream check before any record, pin
and unpin, a stop that lingers and keeps its pin, an update only of a manual entry (none when it
changes nothing), a user actor on every manual change, and the policy's records."""

from __future__ import annotations

import inspect
from datetime import datetime
from typing import Any, Protocol

import pytest

from candleviewer.recorder.errors import InvalidRecorderActorError, RecorderSymbolLimitError
from candleviewer.recorder.errors import RecorderInvalidUpdateError as InvalidUpdate
from candleviewer.recorder.errors import RecorderSymbolNotManualError as NotManual
from candleviewer.recorder.models import SYSTEM_ACTOR, Actor
from candleviewer.recorder.policy import PolicyControlSurface, RefusalCause
from tests.unit.recorder import _control_fakes as fakes
from tests.unit.recorder._fakes import surface_mismatches

USER = Actor(kind="user", id="u-1")


class _Agreed(Protocol):  # #2188 S3's read-only accessors on `PolicyControlSurface`
    def linger_until(self, symbol: str) -> datetime | None: ...
    def start_refusal(self, symbol: str) -> RefusalCause | None: ...
    def chart_open(self, symbol: str) -> bool: ...


def test_the_fake_mirrors_the_policy_control_surface() -> None:
    assert surface_mismatches(fakes.FakeRecorder, PolicyControlSurface) == []


@pytest.mark.parametrize("name", [n for n in vars(_Agreed) if not n.startswith("_")])
def test_the_fake_mirrors_each_agreed_s3_accessor(name: str) -> None:
    ours, theirs = getattr(fakes.FakeRecorder, name), getattr(_Agreed, name)
    assert inspect.iscoroutinefunction(ours) == inspect.iscoroutinefunction(theirs)
    assert inspect.signature(ours, eval_str=True) == inspect.signature(theirs, eval_str=True)


class _Sink(list[tuple[str, dict[str, Any]]]):
    async def emit(self, action: str, **record: Any) -> None:
        self.append((action, record))


async def test_the_cap_an_idempotent_re_add_and_an_update_only_of_a_manual_entry() -> None:
    fake = fakes.FakeRecorder(max_symbols=1)
    await fake.add_manual("BTCUSDT", USER, ("trades",), 50)
    first = fake.entries["BTCUSDT"]
    await fake.add_manual("BTCUSDT", USER, ("trades",), 50)
    assert fake.entries["BTCUSDT"] == first and (first.reason, first.depth) == ("manual", 50)
    with pytest.raises(RecorderSymbolLimitError):
        await fake.add_manual("ETHUSDT", USER)
    with pytest.raises(InvalidRecorderActorError):
        await fake.add_manual("BTCUSDT", SYSTEM_ACTOR)
    await fake.update_manual("BTCUSDT", USER, streams=("tickers",))
    assert fake.entries["BTCUSDT"].streams == ("tickers",)
    with pytest.raises(NotManual):
        await fake.update_manual(fake.put("ETHUSDT", "chart_open").symbol, USER, depth=1)


async def test_pin_unpin_and_a_stop_that_lingers_keeping_its_pin() -> None:
    fake = fakes.FakeRecorder()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        await fake.add_manual(symbol, USER)
    await fake.set_pin("BTCUSDT", True, USER)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        await fake.remove_manual(symbol, USER)
    stopped = fake.entries["BTCUSDT"]
    assert stopped.pinned and stopped.lingering
    assert stopped.linger_until == fakes.NOW + fakes.GRACE == fake.linger_until("BTCUSDT")
    for symbol in ("BTCUSDT", "ETHUSDT"):
        fake.lapse(symbol)  # a pinned row is demoted and kept; an unpinned one is soft-removed
    assert (list(fake.entries), fake.entries["BTCUSDT"].state) == (["BTCUSDT"], "stopped")
    await fake.set_pin("BTCUSDT", False, USER)  # unpinning the idle row soft-removes it
    assert fake.entries == {} and fake.linger_until("BTCUSDT") is None


@pytest.mark.parametrize("depth", [True, 50.0, 7])
async def test_a_depth_the_table_refuses_raises_before_any_record(depth: Any) -> None:
    fake, sink = fakes.FakeRecorder(), _Sink()
    fake.audit, entry = sink, fake.put("BTCUSDT")
    for change in (fake.add_manual("ETHUSDT", USER, (), depth),
                   fake.update_manual("BTCUSDT", USER, depth=depth),
                   fake.update_manual("BTCUSDT", USER, streams=("quotes",))):  # fmt: skip
        with pytest.raises(InvalidUpdate):
            await change
    assert (fake.entries, sink) == ({"BTCUSDT": entry}, [])


async def test_no_op_changes_record_nothing_and_every_manual_change_needs_a_user() -> None:
    fake, sink = fakes.FakeRecorder(), _Sink()
    fake.audit = sink
    await fake.add_manual("BTCUSDT", USER, ("trades",), 50)
    first = fake.entries["BTCUSDT"]
    await fake.add_manual("BTCUSDT", USER, ("tickers",), 500)  # already manual
    await fake.update_manual("BTCUSDT", USER, streams=("trades",), depth=50)  # nothing changes
    for change in (fake.remove_manual("BTCUSDT", SYSTEM_ACTOR),
                   fake.set_pin("BTCUSDT", True, SYSTEM_ACTOR),
                   fake.update_manual("BTCUSDT", SYSTEM_ACTOR, depth=1)):  # fmt: skip
        with pytest.raises(InvalidRecorderActorError):
            await change
    assert fake.entries == {"BTCUSDT": first} and [a for a, _ in sink] == ["recorder.start"]


async def test_the_update_and_stop_records_are_the_policys() -> None:
    fake, sink = fakes.FakeRecorder(), _Sink()
    fake.audit = sink
    await fake.add_manual("BTCUSDT", USER, ("trades",), 200)
    await fake.update_manual("BTCUSDT", USER, depth=50)
    await fake.remove_manual("BTCUSDT", Actor(kind="user", id="u-2"))
    (_, update), (_, stop) = sink[1:]
    assert (update["before_state"], update["after_state"]["depth"]) == (
        {"streams": "trades", "depth": "200"}, "50")  # fmt: skip
    assert (stop["after_state"]["trigger_ref"], stop["actor_user_id"]) == ("manual:u-1", "u-2")
