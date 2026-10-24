"""#2188 S3c: a `restricted` caller may not relax a row a hidden cause holds (ruling 2026-10-24,
C-12.4): `relax_allowed`, the unpin and the lower retention, their records, and `restricted`."""

from __future__ import annotations

import copy
import inspect
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from candleviewer.audit.redact import redact
from candleviewer.observability.context import bind_context
from candleviewer.recorder import policy as policy_module
from candleviewer.recorder.errors import (
    InvalidRecordedSymbolError,
    InvalidRecorderActorError,
    RecorderInvalidUpdateError,
    RecorderRelaxRefusedError,
    RecorderSymbolNotRecordedError,
)
from candleviewer.recorder.models import SYSTEM_ACTOR, Actor
from candleviewer.recorder.policy import PolicyControlSurface, RecordingPolicy, user_actor
from candleviewer.settings import Settings
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, Mem

OWNER, MANAGER = user_actor("owner-1"), user_actor("mgr-2")
REFUSAL = "Only the owner can unpin this row or lower its retention"
Call = Coroutine[Any, Any, None]


async def _held(
    policy: RecordingPolicy, *, hidden: bool = True, days: int | None = None, pinned: bool = False
) -> None:
    """BTCUSDT recorded for a position (a hidden cause) or by hand, with its days and pin."""
    if hidden:
        await policy.on_position_opened("BTCUSDT", "p1")
    else:
        await policy.add_manual("BTCUSDT", MANAGER)
    if days is not None:
        await policy.set_retention("BTCUSDT", days, OWNER, restricted=False)
    if pinned:
        await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)


def _kept(store: Mem) -> tuple[Any, Any]:
    row = store.active("BTCUSDT") or {}
    return row.get("pinned"), row.get("retention_days")


async def _denied(audit: FakeAudit, trace: list[str], call: Call) -> dict[str, Any]:
    """Run the refused `call`: it raises, writes nothing, and its one record is the denied twin."""
    audit.records.clear()
    trace.clear()
    with pytest.raises(RecorderRelaxRefusedError, match=f"^{REFUSAL}$"):
        await call
    assert trace == ["get_by_symbol", "audit:retention.change"]  # the twin, and no write
    ((action, kw),) = audit.records
    assert (action, kw["outcome"]) == ("retention.change", "denied")
    return kw


async def test_relax_allowed_is_true_for_an_unrestricted_view_only_if_exactly_false(
    policy: RecordingPolicy,
) -> None:
    await _held(policy)  # a hidden cause holds it, which only a restricted view lacks
    not_a_bool: Any = None
    assert policy.relax_allowed("BTCUSDT", restricted=False)
    assert not policy.relax_allowed("BTCUSDT", restricted=not_a_bool)  # anything else fails closed


async def test_relax_allowed_is_true_when_restricted_and_only_visible_causes_hold(
    policy: RecordingPolicy,
) -> None:
    await _held(policy, hidden=False)
    await policy.on_chart_opened("BTCUSDT", "c1")
    assert policy.relax_allowed("BTCUSDT", restricted=True)
    assert policy.relax_allowed("ETHUSDT", restricted=True)  # nothing holds an unknown symbol


async def test_relax_allowed_is_false_while_a_hidden_cause_holds(policy: RecordingPolicy) -> None:
    await _held(policy, hidden=False)
    await policy.on_position_opened("BTCUSDT", "p1")  # a visible cause holds it too
    assert not policy.relax_allowed("BTCUSDT", restricted=True)
    await policy.on_position_closed("BTCUSDT", "p1")
    assert policy.relax_allowed("BTCUSDT", restricted=True)


async def test_relax_allowed_is_false_while_the_warm_up_gate_is_closed(
    clock: FakeClock, bus: FakeBus, audit: FakeAudit, store: Mem
) -> None:
    cold = RecordingPolicy(
        disk_refuses=bool, bus=bus, audit=audit, env="demo", now=clock, recorded=store
    )  # the position cache may not be authoritative yet: a position may be held, unseen
    assert not cold.relax_allowed("BTCUSDT", restricted=True)


async def test_relax_allowed_counts_a_hidden_cause_it_cannot_see_as_held(
    policy: RecordingPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(policy_module, "HIDDEN_CAUSES", frozenset({"rule_dependency"}))
    assert not policy.relax_allowed("BTCUSDT", restricted=True)


async def test_relax_allowed_is_sync_and_changes_nothing(
    policy: RecordingPolicy, audit: FakeAudit, trace: list[str]
) -> None:
    await _held(policy)
    before, records, calls = copy.deepcopy(policy._syms), list(audit.records), list(trace)
    answer = policy.relax_allowed("BTCUSDT", restricted=True)
    assert not inspect.iscoroutinefunction(policy.relax_allowed) and answer is False
    assert (policy._syms, audit.records, trace) == (before, records, calls)


async def test_a_restricted_unpin_of_a_hidden_held_row_raises_before_any_write_and_is_recorded(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit, trace: list[str]
) -> None:
    await _held(policy, pinned=True)
    rid, call = uuid.uuid4(), policy.set_pin("BTCUSDT", False, MANAGER, restricted=True)
    with bind_context(request_id=rid):
        kw = await _denied(audit, trace, call)
    assert (kw["reason"], kw["before_state"], kw["request_id"]) == ("relax_refused", None, rid)
    assert (kw["actor_label"], kw["object_id"], kw["env"]) == ("user:mgr-2", "BTCUSDT", "demo")
    assert kw["after_state"] == {"symbol": "BTCUSDT", "reason": "relax_refused", "actor": "mgr-2"}
    assert _kept(store) == (True, None) and policy.effective_set()["BTCUSDT"].pinned  # ids only


@pytest.mark.parametrize(("restricted", "hidden"), [(False, True), (True, False)])
async def test_an_unpin_succeeds_unless_a_restricted_caller_meets_a_hidden_cause(
    policy: RecordingPolicy, store: Mem, restricted: bool, hidden: bool
) -> None:
    await _held(policy, hidden=hidden, pinned=True)
    await policy.set_pin("BTCUSDT", False, MANAGER, restricted=restricted, retention_days=7)
    assert _kept(store) == (False, 7) and not policy.effective_set()["BTCUSDT"].pinned


async def test_pinning_is_never_refused(policy: RecordingPolicy, store: Mem) -> None:
    await _held(policy)
    await policy.set_pin("BTCUSDT", True, MANAGER, restricted=True)  # not a relaxation
    assert _kept(store)[0] is True


@pytest.mark.parametrize(
    ("held", "pinned", "new"),
    [(30, False, 10), (None, True, 3650), (365, False, None)],
    ids=["a smaller number", "a finite value where it was forever", "the default it restores"],
)
async def test_a_restricted_lower_is_refused_on_a_hidden_held_row(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit, trace: list[str],
    held: int | None, pinned: bool, new: int | None,
) -> None:  # fmt: skip
    await _held(policy, days=held, pinned=pinned)
    before = _kept(store)
    kw = await _denied(audit, trace, policy.set_retention("BTCUSDT", new, MANAGER, restricted=True))
    assert (kw["reason"], kw["after_state"]["actor"]) == ("relax_refused", "mgr-2")
    assert _kept(store) == before


@pytest.mark.parametrize(
    ("held", "new"), [(30, 90), (7, None), (None, 3650)],
    ids=["a bigger number", "the default it restores, above", "a number above the default"],
)  # fmt: skip
async def test_a_raise_is_never_refused(
    policy: RecordingPolicy, store: Mem, held: int | None, new: int | None
) -> None:
    await _held(policy, days=held)
    await policy.set_retention("BTCUSDT", new, MANAGER, restricted=True)
    assert _kept(store) == (False, new)


@pytest.mark.parametrize(("restricted", "hidden"), [(False, True), (True, False)])
async def test_a_lower_succeeds_and_writes_the_row_unless_restricted_and_hidden_held(
    policy: RecordingPolicy, store: Mem, restricted: bool, hidden: bool
) -> None:
    await _held(policy, hidden=hidden, days=30)
    await policy.set_retention("BTCUSDT", 10, MANAGER, restricted=restricted)
    assert _kept(store) == (False, 10)


async def test_a_retention_change_to_nothing_writes_nothing(
    policy: RecordingPolicy, audit: FakeAudit, trace: list[str]
) -> None:
    await _held(policy, days=30)
    audit.records.clear()
    trace.clear()
    await policy.set_retention("BTCUSDT", 30, MANAGER, restricted=True)
    assert (audit.records, trace) == ([], ["get_by_symbol"])


async def test_both_writes_record_retention_change_ahead_of_the_store_with_the_request(
    policy: RecordingPolicy, audit: FakeAudit, trace: list[str]
) -> None:
    await _held(policy, hidden=False)
    audit.records.clear()
    trace.clear()
    rid = uuid.uuid4()
    with bind_context(request_id=rid):
        await policy.set_retention("BTCUSDT", 30, OWNER, restricted=False)
        await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
        await policy.set_pin("BTCUSDT", False, OWNER, restricted=False, retention_days=90)
    read, record = "get_by_symbol", "audit:retention.change"
    assert trace == [read, record, "set_retention",  # the days
                     read, record, "set_pinned", "set_retention",  # the pin, then its days nulled
                     read, record, "set_retention", "set_pinned"]  # fmt: skip  # days, then unpin
    assert [kw["reason"] for _, kw in audit.records] == ["retention", "pin", "unpin"]
    assert {kw["request_id"] for _, kw in audit.records} == {rid}
    states = [(kw["before_state"], kw["after_state"]) for _, kw in audit.records]
    assert [(b, a["retention_days"]) for b, a in states] == [
        ({"retention_days": None}, "30"),
        ({"pinned": False, "retention_days": "30"}, None),  # a pin nulls the days (22)
        ({"pinned": True, "retention_days": None}, "90"),
    ]
    assert all(redact(dict(b or {})) == b for b, _ in states)  # the real writer stores them so


async def test_a_pin_writes_the_pin_then_nulls_the_stored_days(
    policy: RecordingPolicy, store: Mem, trace: list[str]
) -> None:
    await _held(policy, hidden=False, days=30)
    trace.clear()
    await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    assert trace == ["get_by_symbol", "audit:retention.change", "set_pinned", "set_retention"]
    assert _kept(store) == (True, None)  # 22: `pinned: true` nulls `retention_days`


async def test_a_pin_of_a_row_already_holding_null_writes_no_second_statement(
    policy: RecordingPolicy, trace: list[str]
) -> None:
    await _held(policy, hidden=False)
    trace.clear()
    await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    assert trace == ["get_by_symbol", "audit:retention.change", "set_pinned"]


async def test_a_failure_after_the_pin_leaves_a_pinned_row_whose_number_is_inert(
    policy: RecordingPolicy, store: Mem
) -> None:
    await _held(policy, hidden=False, days=30)
    store.fail.add("set_retention")
    with pytest.raises(OSError, match="pg down"):
        await policy.set_pin("BTCUSDT", True, OWNER, restricted=False)
    assert _kept(store) == (True, 30)  # the pin went first: no unpinned row ever lost its days


async def test_a_restricted_retention_reset_of_a_pinned_hidden_held_row_is_no_refusal(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit, trace: list[str]
) -> None:
    await _held(policy, days=30, pinned=True)  # the pin nulls the 30: the reset changes nothing
    audit.records.clear()
    trace.clear()
    await policy.set_retention("BTCUSDT", None, MANAGER, restricted=True)
    assert (audit.records, trace, _kept(store)) == ([], ["get_by_symbol"], (True, None))


@pytest.mark.parametrize("days", [None, 7])
@pytest.mark.parametrize(("restricted", "hidden"), [(False, False), (True, True)])
async def test_an_unpin_of_an_unpinned_row_writes_and_records_nothing(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit, trace: list[str],
    restricted: bool, hidden: bool, days: int | None,
) -> None:  # fmt: skip
    await _held(policy, hidden=hidden, days=30)
    audit.records.clear()
    trace.clear()
    await policy.set_pin("BTCUSDT", False, MANAGER, restricted=restricted, retention_days=days)
    assert (audit.records, trace, _kept(store)) == ([], [], (False, 30))  # not even refused


@pytest.mark.parametrize("op", ["pin", "unpin", "retention", "refusal"])
async def test_an_audit_failure_writes_nothing(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit, monkeypatch: pytest.MonkeyPatch, op: str
) -> None:
    calls: dict[str, Callable[[], Call]] = {
        "pin": lambda: policy.set_pin("BTCUSDT", True, OWNER, restricted=False),
        "unpin": lambda: policy.set_pin("BTCUSDT", False, OWNER, restricted=False),
        "retention": lambda: policy.set_retention("BTCUSDT", 10, OWNER, restricted=False),
        "refusal": lambda: policy.set_retention("BTCUSDT", 10, MANAGER, restricted=True),
    }
    await _held(policy, days=30, pinned=op == "unpin")
    before = (_kept(store), policy.effective_set()["BTCUSDT"].pinned)

    async def down(action: str, **kw: Any) -> None:
        raise OSError("audit down")

    monkeypatch.setattr(audit, "emit", down)
    with pytest.raises(OSError, match="audit down"):  # a refusal's own record fails the same way
        await calls[op]()
    assert (_kept(store), policy.effective_set()["BTCUSDT"].pinned) == before


@pytest.mark.parametrize("bad", [0, 3651, True, 7.0])
@pytest.mark.parametrize("op", ["set_pin", "set_retention"])
async def test_a_retention_the_table_refuses_raises_before_any_audit_or_write(
    policy: RecordingPolicy, audit: FakeAudit, trace: list[str], op: str, bad: Any
) -> None:
    await _held(policy, hidden=False)
    audit.records.clear()
    trace.clear()
    with pytest.raises(RecorderInvalidUpdateError):
        if op == "set_pin":
            await policy.set_pin("BTCUSDT", False, OWNER, restricted=False, retention_days=bad)
        else:
            await policy.set_retention("BTCUSDT", bad, OWNER, restricted=False)
    assert (audit.records, trace) == ([], [])


@pytest.mark.parametrize(
    ("symbol", "actor", "recorded", "refusal"),
    [
        ("BTCUSDT", SYSTEM_ACTOR, True, InvalidRecorderActorError),
        ("btc", OWNER, True, InvalidRecordedSymbolError),
        ("BTCUSDT", OWNER, False, RecorderSymbolNotRecordedError),
    ],
    ids=["a non-user actor", "a malformed symbol", "no active row"],
)
async def test_set_retention_refuses_before_any_audit_or_write(
    policy: RecordingPolicy, audit: FakeAudit, trace: list[str],
    symbol: str, actor: Actor, recorded: bool, refusal: type[Exception],
) -> None:  # fmt: skip
    if recorded:
        await _held(policy, hidden=False)
    audit.records.clear()
    trace.clear()
    with pytest.raises(refusal):
        await policy.set_retention(symbol, 30, actor, restricted=False)
    assert audit.records == [] and "set_retention" not in trace  # a read is all it may make


async def test_set_retention_of_a_row_gone_between_read_and_write_raises_after_its_record(
    policy: RecordingPolicy, store: Mem, audit: FakeAudit, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def row_gone(recorded_id: str, days: int | None) -> bool:
        return False

    await _held(policy, hidden=False)
    monkeypatch.setattr(store, "set_retention", row_gone)
    with pytest.raises(RecorderSymbolNotRecordedError):
        await policy.set_retention("BTCUSDT", 30, OWNER, restricted=False)
    assert _kept(store) == (False, None)
    assert audit.actions().count("retention.change") == 1  # the record stands: write-ahead


@pytest.mark.parametrize("owner", [RecordingPolicy, PolicyControlSurface])
@pytest.mark.parametrize("name", ["set_pin", "set_retention", "relax_allowed"])
def test_restricted_is_keyword_only_and_has_no_default(owner: type, name: str) -> None:
    restricted = inspect.signature(getattr(owner, name)).parameters["restricted"]
    assert (restricted.kind, restricted.default) == (
        inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.empty,
    )  # fmt: skip


def test_the_default_retention_is_the_settings_default() -> None:
    default = Settings.model_fields["recorder_retention_days"].default
    assert policy_module.PolicyConfig().default_retention_days == default  # wiring passes it
