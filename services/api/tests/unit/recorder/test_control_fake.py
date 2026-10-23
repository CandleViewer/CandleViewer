"""#492 S1: the fake behind the recording tests.

`FakeRecorder` mirrors #2188's `PolicyControlSurface` member for member: the members
`RecordingPolicy` has are compared with it, the four S2b and S3 add with the signatures agreed on
2026-10-23 (`_Agreed`; once they land, with `recorder.policy.PolicyControlSurface` instead). It
keeps the rules: the cap, an idempotent re-add, pin and unpin, a stop that lingers and keeps its
pin, an update only of a manual entry and by a user."""

from __future__ import annotations

import inspect
from datetime import datetime
from typing import Protocol

import pytest

from candleviewer.recorder.errors import InvalidRecorderActorError, RecorderSymbolLimitError
from candleviewer.recorder.models import SYSTEM_ACTOR, Actor
from candleviewer.recorder.policy import RecordingPolicy, RefusalCause
from tests.unit.recorder import _control_fakes as fakes

USER = Actor(kind="user", id="u-1")


class _Agreed(Protocol):  # #2188's S2b and S3 additions to `PolicyControlSurface`
    async def update_manual(self, symbol: str, actor: Actor, *,
                            streams: tuple[str, ...] | None = None,
                            depth: int | None = None) -> None: ...  # fmt: skip
    def linger_until(self, symbol: str) -> datetime | None: ...
    def start_refusal(self, symbol: str) -> RefusalCause | None: ...
    def chart_open(self, symbol: str) -> bool: ...


_HAS = ("add_manual", "remove_manual", "set_pin", "position_open")  # on `RecordingPolicy` today
_SURFACE: dict[str, type[object]] = dict.fromkeys(_HAS, RecordingPolicy)
_SURFACE |= {name: _Agreed for name in vars(_Agreed) if not name.startswith("_")}


@pytest.mark.parametrize("name", sorted(_SURFACE))
def test_the_fake_mirrors_each_policy_control_surface_member(name: str) -> None:
    ours, theirs = getattr(fakes.FakeRecorder, name), getattr(_SURFACE[name], name)
    assert inspect.iscoroutinefunction(ours) == inspect.iscoroutinefunction(theirs)
    assert inspect.signature(ours, eval_str=True) == inspect.signature(theirs, eval_str=True)


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
    with pytest.raises(fakes.RecorderSymbolNotManualError):
        await fake.update_manual(fake.put("ETHUSDT", "chart_open").symbol, USER, depth=1)


async def test_pin_unpin_and_a_stop_that_lingers_keeping_its_pin() -> None:
    fake = fakes.FakeRecorder()
    await fake.add_manual("BTCUSDT", USER)
    await fake.set_pin("BTCUSDT", True, USER)
    await fake.remove_manual("BTCUSDT", USER)
    stopped = fake.entries["BTCUSDT"]
    assert stopped.pinned and stopped.lingering
    assert stopped.linger_until == fakes.NOW + fakes.GRACE == fake.linger_until("BTCUSDT")
    await fake.set_pin("BTCUSDT", False, USER)
    assert not fake.entries["BTCUSDT"].pinned and fake.linger_until("ETHUSDT") is None
