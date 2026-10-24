"""#492 S1: the fake behind the recording tests.

`FakeRecorder` mirrors #2188's `PolicyControlSurface` member for member (`surface_mismatches`:
names, signatures, sync versus async) as S3c leaves it (`control_runtime.RuntimePolicy` until S3c
is on main): the S3b accessors, `set_pin` and `set_retention` with the view, `relax_allowed`. It
keeps the policy's rules: the cap, a re-add of a
manual entry that changes and records nothing, the depth and stream check before any record, pin
and unpin, a stop that lingers and keeps its pin, an update only of a manual entry (none when it
changes nothing), a user actor on every manual change, and the policy's records."""

from __future__ import annotations

from typing import Any

import pytest
from candleviewer.recorder.control_runtime import RuntimePolicy

from candleviewer.recorder.errors import (
    InvalidRecorderActorError,
    RecorderRelaxRefusedError,
    RecorderSymbolLimitError,
)
from candleviewer.recorder.errors import RecorderInvalidUpdateError as InvalidUpdate
from candleviewer.recorder.errors import RecorderSymbolNotManualError as NotManual
from candleviewer.recorder.models import SYSTEM_ACTOR, Actor
from tests.unit.recorder import _control_fakes as fakes
from tests.unit.recorder._fakes import surface_mismatches

USER = Actor(kind="user", id="u-1")


def test_the_fake_mirrors_the_policy_control_surface() -> None:
    assert surface_mismatches(fakes.FakeRecorder, RuntimePolicy) == []


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
    await fake.set_pin("BTCUSDT", True, USER, restricted=False)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        await fake.remove_manual(symbol, USER)
    stopped = fake.entries["BTCUSDT"]
    assert stopped.pinned and stopped.lingering
    assert stopped.linger_until == fakes.NOW + fakes.GRACE == fake.linger_until("BTCUSDT")
    for symbol in ("BTCUSDT", "ETHUSDT"):
        fake.lapse(symbol)  # a pinned row is demoted and kept; an unpinned one is soft-removed
    assert (list(fake.entries), fake.entries["BTCUSDT"].state) == (["BTCUSDT"], "stopped")
    await fake.set_pin("BTCUSDT", False, USER, restricted=False)  # an idle row unpinned goes
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
                   fake.set_pin("BTCUSDT", True, SYSTEM_ACTOR, restricted=False),
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


async def test_a_restricted_relax_of_a_hidden_held_entry_is_refused_as_the_policy_does() -> None:
    fake, sink = fakes.FakeRecorder(), _Sink()
    fake.audit = sink
    held = fake.put("BTCUSDT", "manual", "position_open", pinned=True)
    assert fake.relax_allowed("BTCUSDT", restricted=False)
    assert not fake.relax_allowed("BTCUSDT", restricted=True)
    for relax in (fake.set_pin("BTCUSDT", False, USER, restricted=True),
                  fake.set_retention("BTCUSDT", 7, USER, restricted=True)):  # fmt: skip
        with pytest.raises(RecorderRelaxRefusedError):
            await relax
    assert fake.entries == {"BTCUSDT": held}  # the denied twins are all it wrote
    assert [(a, r["outcome"], r["reason"]) for a, r in sink] == [
        ("retention.change", "denied", "relax_refused")] * 2  # fmt: skip
    await fake.set_retention("BTCUSDT", 7, USER, restricted=False)
    await fake.set_pin("BTCUSDT", False, USER, restricted=False, retention_days=9)
    assert fake.entries["BTCUSDT"].retention_days == 9 and not fake.entries["BTCUSDT"].pinned


async def test_a_pin_nulls_the_entrys_days_as_the_policy_does() -> None:
    fake = fakes.FakeRecorder()
    fake.put("BTCUSDT", "manual", retention_days=30)
    await fake.set_pin("BTCUSDT", True, USER, restricted=False)
    assert fake.entries["BTCUSDT"].retention_days is None


async def test_a_relax_a_hidden_cause_holds_is_refused_with_the_policys_denied_record() -> None:
    fake, sink = fakes.FakeRecorder(), _Sink()
    fake.audit = sink
    fake.put("ETHUSDT", "manual", "position_open", pinned=True)
    fake.put("BTCUSDT", "manual", "position_open", retention_days=60)
    for change in (fake.set_pin("ETHUSDT", False, USER, restricted=True),
                   fake.set_retention("BTCUSDT", 7, USER, restricted=True)):  # fmt: skip
        with pytest.raises(RecorderRelaxRefusedError):
            await change
    assert [(a, r["outcome"]) for a, r in sink] == [("retention.change", "denied")] * 2
    await fake.set_retention("BTCUSDT", 90, USER, restricted=True)  # raising is no relax
    await fake.set_pin("ETHUSDT", False, USER, restricted=False, retention_days=7)  # the Owner
    assert (fake.entries["BTCUSDT"].retention_days, fake.entries["ETHUSDT"].retention_days) == (
        90, 7)  # fmt: skip
