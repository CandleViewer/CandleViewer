"""What #492's REST binding calls on the policy: the signatures pinned (its fake is held to the
same `PolicyControlSurface`, so a rename on either side fails a test) and `update_manual`."""

from __future__ import annotations

import pytest

from candleviewer.audit.actions import validate_action
from candleviewer.audit.redact import redact
from candleviewer.recorder.errors import InvalidRecorderActorError, RecorderSymbolNotManualError
from candleviewer.recorder.models import SYSTEM_ACTOR, Actor
from candleviewer.recorder.policy import PolicyControlSurface, RecordingPolicy, user_actor
from candleviewer.recorder.sessions import DEFAULT_STREAMS
from tests.unit.recorder._fakes import FakeAudit, Mem, surface_mismatches

OWNER, MANAGER = user_actor("owner-1"), user_actor("mgr-2")


def test_recording_policy_satisfies_the_control_surface(policy: RecordingPolicy) -> None:
    surface: PolicyControlSurface = policy  # mypy: structurally satisfied
    assert isinstance(surface, PolicyControlSurface)
    assert surface_mismatches(RecordingPolicy, PolicyControlSurface) == []


def test_the_comparison_catches_a_rename_a_changed_default_and_a_missing_member() -> None:
    class Drifted:
        async def add_manual(self, symbol, actor, streams=(), depth=None) -> None: ...  # type: ignore[no-untyped-def]
        async def remove_manual(self, symbol: str, who: Actor) -> None: ...
        async def set_pin(self, symbol: str, pinned: bool, actor: Actor) -> None: ...
        async def update_manual(
            self,
            symbol: str,
            actor: Actor,
            *,
            streams: tuple[str, ...] | None = None,
            depth: int | None = 5,
        ) -> None: ...

    assert surface_mismatches(Drifted, PolicyControlSurface) == [
        "add_manual", "remove_manual", "update_manual", "position_open",
    ]  # fmt: skip


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
    await policy.update_manual("BTCUSDT", MANAGER, depth=200)
    await policy.update_manual("BTCUSDT", MANAGER, streams=("tickers",))
    row, entry = store.active("BTCUSDT") or {}, policy.effective_set()["BTCUSDT"]
    assert (row["streams"], row["orderbook_depth"]) == (["tickers"], 200)
    assert (entry.streams, entry.depth, row["added_by"]) == (("tickers",), 200, "owner-1")


async def test_a_failed_update_write_changes_nothing_and_audits_nothing(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit
) -> None:
    await policy.add_manual("BTCUSDT", OWNER, ("trades",), 50)
    audit.records.clear()
    store.fail.add("upsert_manual")
    with pytest.raises(OSError, match="pg down"):
        await policy.update_manual("BTCUSDT", OWNER, streams=("tickers",), depth=500)
    entry = policy.effective_set()["BTCUSDT"]
    assert (entry.streams, entry.depth, audit.records) == (("trades",), 50, [])


async def test_update_manual_writes_audits_then_reconciles(
    policy: RecordingPolicy, audit: FakeAudit, trace: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await policy.add_manual("BTCUSDT", OWNER)
    trace.clear()
    real = policy._reconcile

    async def spy(symbol: str) -> None:
        trace.append("reconcile")
        await real(symbol)

    monkeypatch.setattr(policy, "_reconcile", spy)
    await policy.update_manual("BTCUSDT", MANAGER, depth=500)
    assert trace == ["upsert_manual", "audit:recorder.update", "reconcile"]
    action, kw = audit.records[-1]
    assert (action, kw["actor_label"], kw["reason"]) == ("recorder.update", "user:mgr-2", "manual")
    assert kw["after_state"] == {
        "symbol": "BTCUSDT", "reason": "manual", "actor": "mgr-2",
        "streams": ",".join(DEFAULT_STREAMS), "depth": "500",
    }  # fmt: skip  # the updater only: the adder's id is not repeated
    assert redact(dict(kw["after_state"])) == kw["after_state"]  # the real writer stores it as is
    assert policy.effective_set()["BTCUSDT"].depth == 500


def test_the_update_audit_action_is_registered() -> None:
    assert validate_action("recorder.update") == "recorder.update"  # the real writer refuses others
