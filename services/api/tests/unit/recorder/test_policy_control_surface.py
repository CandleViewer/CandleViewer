"""What #492's REST binding calls on the policy: the signatures pinned (its fake is held to the
same `PolicyControlSurface`, so a rename on either side fails a test), `update_manual`, and the
validation it shares with `add_manual`."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import CheckConstraint

from candleviewer.audit.actions import validate_action
from candleviewer.audit.redact import redact
from candleviewer.db.models import recorded_symbols, stream_kind
from candleviewer.recorder.errors import (
    InvalidRecorderActorError,
    RecorderInvalidUpdateError,
    RecorderSymbolNotManualError,
)
from candleviewer.recorder.models import ORDERBOOK_DEPTHS, STREAM_KINDS, SYSTEM_ACTOR, Actor
from candleviewer.recorder.policy import (
    PolicyControlSurface,
    RecordingPolicy,
    RefusalCause,
    StartRefused,
    user_actor,
)
from candleviewer.recorder.sessions import DEFAULT_STREAMS
from tests.unit.recorder._fakes import FakeAudit, Mem, surface_mismatches

OWNER, MANAGER = user_actor("owner-1"), user_actor("mgr-2")


def test_recording_policy_satisfies_the_control_surface(policy: RecordingPolicy) -> None:
    surface: PolicyControlSurface = policy  # mypy: structurally satisfied
    assert isinstance(surface, PolicyControlSurface)
    assert surface_mismatches(RecordingPolicy, PolicyControlSurface) == []


def test_the_comparison_catches_a_rename_a_changed_default_and_a_sync_async_swap() -> None:
    class Drifted:
        def add_manual(  # sync where the surface is async
            self,
            symbol: str,
            actor: Actor,
            streams: tuple[str, ...] = (),
            depth: int | None = None,
            *,
            held_hidden: bool = False,
        ) -> None: ...
        async def remove_manual(self, symbol: str, who: Actor) -> None: ...
        async def set_pin(
            self,
            symbol: str,
            pinned: bool,
            actor: Actor,
            *,
            restricted: bool,
            retention_days: int | None = None,
        ) -> None: ...
        async def set_retention(
            self, symbol: str, retention_days: int | None, actor: Actor, *, restricted: bool
        ) -> None: ...
        async def update_manual(
            self,
            symbol: str,
            actor: Actor,
            *,
            streams: tuple[str, ...] | None = None,
            depth: int | None = 5,
        ) -> None: ...
        async def position_open(self, symbol: str) -> bool:  # async where it is sync
            return True

        async def linger_until(self, symbol: str) -> datetime | None: ...  # likewise
        def start_refusal(self, symbol: str) -> RefusalCause | None: ...  # as the surface has it
        def start_refused(self) -> tuple[StartRefused, ...]:  # likewise
            return ()

        def chart_open(self, sym: str) -> bool:  # a renamed parameter
            return False

        def relax_allowed(self, symbol: str, *, restricted: bool) -> bool:  # as the surface has it
            return True

    assert surface_mismatches(Drifted, PolicyControlSurface) == [
        "add_manual", "remove_manual", "update_manual", "position_open", "linger_until",
        "chart_open",
    ]  # fmt: skip


def test_the_comparison_reports_a_missing_member_and_an_annotation_it_cannot_resolve() -> None:
    class Partial:
        async def remove_manual(self, symbol: str, actor: Actor) -> None: ...

        remove_manual.__annotations__["actor"] = "NoSuchType"  # no name resolves it

    assert surface_mismatches(Partial, PolicyControlSurface) == [
        "add_manual", "remove_manual", "set_pin", "set_retention", "update_manual", "position_open",
        "linger_until", "start_refusal", "start_refused", "chart_open", "relax_allowed",
    ]  # fmt: skip


def test_the_policy_accepts_what_the_table_accepts() -> None:
    (rs_depth,) = (
        c
        for c in recorded_symbols.constraints
        if isinstance(c, CheckConstraint) and str(c.name).endswith("rs_depth")  # naming convention
    )
    assert ORDERBOOK_DEPTHS == {int(n) for n in re.findall(r"\d+", str(rs_depth.sqltext))}
    assert STREAM_KINDS == set(stream_kind.enums)


async def test_update_manual_refuses_a_non_user_actor(policy: RecordingPolicy) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    with pytest.raises(InvalidRecorderActorError):
        await policy.update_manual("BTCUSDT", SYSTEM_ACTOR, depth=50)


@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT"])
async def test_update_manual_refuses_a_symbol_that_is_not_manual(
    policy: RecordingPolicy, symbol: str
) -> None:
    await policy.on_position_opened("BTCUSDT", "p1")  # recorded, but not by hand
    with pytest.raises(RecorderSymbolNotManualError):
        await policy.update_manual(symbol, OWNER, depth=50)


async def test_update_manual_keeps_what_it_is_not_given(
    policy: RecordingPolicy, store: Mem
) -> None:
    await policy.add_manual("BTCUSDT", OWNER, ("trades",), 50)
    row = store.active("BTCUSDT") or {}

    def held() -> tuple[object, ...]:  # the row and the entry, side by side
        entry = policy.effective_set()["BTCUSDT"]
        return row["streams"], entry.streams, row["orderbook_depth"], entry.depth

    await policy.update_manual("BTCUSDT", MANAGER, depth=200)  # no streams: they stay
    assert held() == (["trades"], ("trades",), 200, 200)
    await policy.update_manual("BTCUSDT", MANAGER, streams=("tickers",))  # no depth: it stays
    assert held() == (["tickers"], ("tickers",), 200, 200)
    await policy.update_manual("BTCUSDT", MANAGER, streams=())  # empty streams: they stay
    assert held() == (["tickers"], ("tickers",), 200, 200)
    assert row["added_by"] == "owner-1"


async def test_update_manual_leaves_the_entrys_adder_in_memory(
    policy: RecordingPolicy, audit: FakeAudit
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    await policy.update_manual("BTCUSDT", MANAGER, depth=200)
    await policy.remove_manual("BTCUSDT", MANAGER)  # its record names the entry's adder
    assert audit.records[-1][1]["after_state"]["trigger_ref"] == "manual:owner-1"


async def test_an_update_that_changes_nothing_writes_nothing(
    policy: RecordingPolicy, audit: FakeAudit, trace: list[str]
) -> None:
    await policy.add_manual("BTCUSDT", OWNER, ("trades",), 50)
    audit.records.clear()
    trace.clear()
    await policy.update_manual("BTCUSDT", MANAGER, streams=("trades",), depth=50)
    assert (audit.records, trace) == ([], [])


async def test_a_refused_update_write_leaves_the_record_and_changes_nothing(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit
) -> None:
    await policy.add_manual("BTCUSDT", OWNER, ("trades",), 50)
    audit.records.clear()
    store.fail.add("upsert_manual")
    with pytest.raises(OSError, match="pg down"):
        await policy.update_manual("BTCUSDT", OWNER, streams=("tickers",), depth=500)
    entry = policy.effective_set()["BTCUSDT"]
    assert (entry.streams, entry.depth) == (("trades",), 50)
    assert audit.actions() == ["recorder.update"]  # write-ahead: the record stands


@pytest.mark.parametrize("op", ["add", "update"])
@pytest.mark.parametrize(
    "bad",
    [
        {"depth": 0},
        {"depth": 100},
        {"depth": 501},
        {"depth": True},
        {"depth": 50.0},
        {"streams": ("bars",)},
        {"streams": ("trades", "funding_rates")},
        {"streams": ("TRADES",)},
    ],
)
async def test_a_bad_depth_or_stream_raises_before_any_audit_or_write(
    policy: RecordingPolicy, audit: FakeAudit, trace: list[str], op: str, bad: dict[str, Any]
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    audit.records.clear()
    trace.clear()
    with pytest.raises(RecorderInvalidUpdateError):
        if op == "add":
            await policy.add_manual("ETHUSDT", OWNER, **bad)
        else:
            await policy.update_manual("BTCUSDT", OWNER, **bad)
    assert (audit.records, trace) == ([], [])


async def test_update_manual_audits_then_writes_then_reconciles(
    policy: RecordingPolicy, trace: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    trace.clear()
    real = policy._reconcile

    async def spy(symbol: str) -> None:
        trace.append("reconcile")
        await real(symbol)

    monkeypatch.setattr(policy, "_reconcile", spy)
    await policy.update_manual("BTCUSDT", MANAGER, depth=500)
    assert trace == ["audit:recorder.update", "upsert_manual", "reconcile"]


async def test_the_update_record_names_the_updater_and_the_entry_before_and_after(
    policy: RecordingPolicy, audit: FakeAudit
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    audit.records.clear()
    await policy.update_manual("BTCUSDT", MANAGER, depth=500)
    action, kw = audit.records[-1]
    assert (action, kw["actor_label"], kw["reason"]) == ("recorder.update", "user:mgr-2", "manual")
    streams = ",".join(DEFAULT_STREAMS)
    assert kw["before_state"] == {"streams": streams, "depth": None}
    assert kw["after_state"] == {
        "symbol": "BTCUSDT", "reason": "manual", "actor": "mgr-2",
        "streams": streams, "depth": "500",
    }  # fmt: skip  # the updater only: the adder's id is not repeated


async def test_the_update_record_survives_the_real_redactor(
    policy: RecordingPolicy, audit: FakeAudit
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    await policy.update_manual("BTCUSDT", MANAGER, depth=500)
    kw = audit.records[-1][1]
    assert redact(dict(kw["before_state"])) == kw["before_state"]  # the real writer stores both
    assert redact(dict(kw["after_state"])) == kw["after_state"]  # as they are


def test_the_update_audit_action_is_registered() -> None:
    assert validate_action("recorder.update") == "recorder.update"  # the real writer refuses others
