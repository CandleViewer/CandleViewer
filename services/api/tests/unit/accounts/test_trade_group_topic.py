"""E28-T05 (#909, slice S4a): the `trade_groups` topic (`accounts/trade_group_topic.py`; 23 §15.5).

A snapshot holds the covered active groups, each whole. A change reaches a subscription the group
enters (it is created, or its status after is listed and its status before was not) as the whole
item, and one whose view held it as a delta with the changed legs only, never both; a terminal
frame is the group's last and a late event is dropped; SR-E28-21 holds on every frame and snapshot
(AC 9), also when a grant is withdrawn between two frames; no frame carries a private field; a
failing publish is contained, a cancellation is not. Every payload is validated against 23's
`v: 1` schema. The hub records each publish with its `select` and `viewer`, which a test asks as
the hub does, after the hub's own `account` check; the viewer factory is the one the composition
root binds (the Owner, or a grant on every leg's account).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts import trade_group_topic
from candleviewer.accounts.trade_group_topic import LOG_INTERVAL_S, TradeGroupsSub, TradeGroupTopic
from candleviewer.accounts.trade_groups import TradeGroup, TradeGroupLeg, TradeGroupWithLegs
from candleviewer.api.profile_projection import plain
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot, scoped_account_ids
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from tests.unit.accounts.test_trade_groups import _GROUP_BASE, _LEG_BASE, _US
from tests.unit.ws._seq_support import Clock, validate

_A, _B, _C = UUID(int=0xA), UUID(int=0xB), UUID(int=0xC)
_REF, _CREATOR, _NOTE = UUID(int=0xBEEF), UUID(int=0xC0FFEE), "planted note"
_ECHO = "echoed hub text: key abc123"  # what a failing hub's message may carry
_PRIVATE = {"client_group_ref", "created_by", "note", "intent"}
_DELTA = {"id", "status", "updated_at_ms", "totals"}  # a group-only delta's members
_FINALS = ("closed", "failed", "cancelled")  # B2's final states

type Topic = TradeGroupTopic[SnapshotBody, PrincipalSnapshot]


def _manager(*grants: UUID) -> PrincipalSnapshot:
    rows = tuple(AccountGrant(account, True, False, False) for account in grants)
    reads = frozenset({Permission.ORDERS_READ})
    return PrincipalSnapshot(UUID(int=0x100), frozenset({"manager"}), reads, rows)


def _grants_cover(accounts: frozenset[UUID]) -> Callable[[PrincipalSnapshot], bool]:
    """The composition root's viewer factory, as 23 §15.5 reads it."""
    return lambda principal: principal.is_owner or accounts <= scoped_account_ids(principal)


def _group(n: int, status: str = "open", **over: Any) -> TradeGroup:
    private = {"client_group_ref": _REF, "created_by": _CREATOR, "note": _NOTE}
    ids = {"group_id": UUID(int=n), "status": status}
    return TradeGroup.model_validate(_GROUP_BASE | private | ids | over)


def _leg(n: int, seq: int, account: UUID, **over: Any) -> TradeGroupLeg:
    ids = {"leg_id": UUID(int=0x100 * n + seq), "group_id": UUID(int=n), "account_id": account}
    return TradeGroupLeg.model_validate(_LEG_BASE | ids | {"sequence_no": seq} | over)


def _stored(n: int, *accounts: UUID, status: str = "open", **over: Any) -> TradeGroupWithLegs:
    legs = tuple(_leg(n, seq, account) for seq, account in enumerate(accounts))
    return TradeGroupWithLegs(group=_group(n, status, **over), legs=legs)


@dataclass
class _Sub:
    accounts: frozenset[UUID]
    effective: dict[str, Any] = field(default_factory=dict)


def _valid(t: str, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The payload's items, once 23's schema has passed its frame."""
    validate({"t": t, "ch": "trade_groups", "s": 1, "ts": 1, "e": "j", "p": dict(payload)})
    items: list[dict[str, Any]] = payload["trade_groups"]
    return items


@dataclass(frozen=True)
class _Frame:
    item: dict[str, Any]
    account: UUID
    select: Callable[[TradeGroupsSub], bool]
    viewer: Callable[[PrincipalSnapshot], bool]

    def reaches(self, sub: _Sub, principal: PrincipalSnapshot) -> bool:
        """As the hub delivers: the account's scope, then `select`, then `viewer`."""
        return self.account in sub.accounts and self.select(sub) and self.viewer(principal)


class _Hub(list[_Frame]):
    """A hub's `publish` that records each delta, one item each (never merged), or raises."""

    error: BaseException | None = None

    def __call__(
        self,
        ch: str,
        body: Mapping[str, Any],
        *,
        account: UUID,
        select: Callable[[TradeGroupsSub], bool],
        viewer: Callable[[PrincipalSnapshot], bool],
    ) -> int:
        if self.error is not None:
            raise self.error
        assert ch == "trade_groups"
        [item] = _valid("d", body)
        self.append(_Frame(item, account, select, viewer))
        return 1

    def to(self, sub: _Sub) -> list[_Frame]:
        """The frames `sub` receives, on a connection granted its accounts alone."""
        return [frame for frame in self if frame.reaches(sub, _manager(*sub.accounts))]


def _topic(*seed: TradeGroupWithLegs, clock: Clock | None = None) -> tuple[Topic, _Hub]:
    hub = _Hub()
    topic: Topic = TradeGroupTopic(hub, SnapshotBody, _grants_cover, clock=clock or Clock())
    topic.seed(seed)
    return topic, hub


def _snap(topic: Topic, sub: _Sub) -> list[dict[str, Any]]:
    body = topic.build(sub)
    assert body is not None
    return _valid("snap", body.structured)


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return [item["id"] for item in items]


def _sub(*accounts: UUID, **effective: Any) -> _Sub:
    return _Sub(frozenset(accounts), effective)


_G1, _G2 = str(UUID(int=1)), str(UUID(int=2))


def test_a_snapshot_holds_the_covered_active_groups_with_every_leg() -> None:
    """Oldest first, then by id, each with every leg; a group on C is not covered, and a closed one
    is not held. `abort_on_first` has no `atomicity` value (§15.5's enum names two)."""
    topic, _ = _topic(
        _stored(3, _C),
        _stored(1, _A, _B),
        _stored(
            2, _A, status="submitting", leg_failure_policy="abort_on_first", created_at=_US - 1
        ),
        _stored(4, _A, status="closed"),
    )
    older, newer = _snap(topic, _sub(_A, _B))
    assert _ids([older, newer]) == [_G2, _G1]
    assert [leg["exchange_account_id"] for leg in newer["legs"]] == [str(_A), str(_B)]
    assert newer["atomicity"] == "best_effort" and "atomicity" not in older
    assert older["status"] == "submitting" and len(older["legs"]) == 1


def test_an_item_renders_every_member_from_its_own_value() -> None:
    d = Decimal
    leg = _leg(
        1, 0, _A, account_profile_id=UUID(int=0xD1), status="partially_filled",
        target_qty=d("3.30"), filled_qty=d("1.1"), avg_entry_price=d("101.5"),
        avg_exit_price=d("99.25"), native_sl_confirmed=False, native_sl_confirmed_at=None,
        risk_usd=d("7.75"), realised_pnl=d("-2.5"), fees_paid=d("0.125"),
        rejection_message="a stored note on the leg", updated_at=_US + 9_000,
    )  # fmt: skip
    group = _group(
        1, symbol="ETHUSDT", side="sell", algo="twap", rule_id=UUID(int=0xD2),
        leg_failure_policy="all_or_none",
    )  # fmt: skip
    topic, _ = _topic(TradeGroupWithLegs(group=group, legs=(leg,)))
    [item] = _snap(topic, _sub(_A))
    assert item == {
        "id": _G1, "symbol": "ETHUSDT", "side": "sell", "status": "open",
        "atomicity": "all_or_none", "algo_kind": "twap", "rule_id": str(UUID(int=0xD2)),
        "updated_at_ms": (_US + 9_000) // 1000,
        "totals": {
            "requested_legs": 1, "submitted_legs": 1, "rejected_legs": 0, "filled_qty": "1.1",
            "target_qty": "3.3", "realised_pnl": "-2.5",
        },
        "legs": [{
            "id": str(leg.leg_id), "exchange_account_id": str(_A),
            "account_profile_id": str(UUID(int=0xD1)), "sequence_no": 0,
            "status": "partially_filled", "target_qty": "3.3", "filled_qty": "1.1",
            "avg_entry_price": "101.5", "avg_exit_price": "99.25", "native_sl_confirmed": False,
            "risk_usd": "7.75", "realised_pnl": "-2.5", "fees_paid": "0.125",
            "error": {"code": "", "message": "a stored note on the leg"},
        }],
    }  # fmt: skip


def test_a_group_with_a_leg_outside_the_subscription_is_never_sent() -> None:
    """SR-E28-21, AC 9: a subscription with A alone, and a manager granted A alone, never learn of a
    group on A and B, in a snapshot or in any frame: its creation, one about A's own leg, or the
    whole item a subscription gets when the group enters its view."""
    topic, hub = _topic(_stored(1, _A, _B))
    assert _snap(topic, _sub(_A)) == [] and _ids(_snap(topic, _sub(_A, _B))) == [_G1]
    topic.created(_stored(2, _A, _B))
    topic.leg_changed(_leg(1, 0, _A, filled_qty=Decimal("0.006")))
    topic.group_changed(_group(1, "closed"))  # whole where `closed` is listed and `open` is not
    for frame, options in zip(hub, [{}, {}, {"status": ["closed"]}, {}], strict=True):
        assert not frame.select(_sub(_A, **options)) and not frame.viewer(_manager(_A))
        assert frame.reaches(_sub(_A, _B, **options), _manager(_A, _B))


def test_a_grant_withdrawn_between_two_frames_stops_the_group_at_once() -> None:
    """§9.5 swaps the narrower principal in first, then narrows the subscription in place: each
    frame is judged on the lists as they are when it is sent, so neither the frame after the
    withdrawal nor the group's terminal frames are sent."""
    topic, hub = _topic(_stored(1, _A, _B))
    sub = _sub(_A, _B)
    topic.leg_changed(_leg(1, 0, _A, filled_qty=Decimal("0.005")))
    assert hub[-1].reaches(sub, _manager(_A, _B))
    withdrawn = _manager(_A)  # B's grant is withdrawn
    topic.leg_changed(_leg(1, 0, _A, filled_qty=Decimal("0.006")))
    assert hub[-1].select(sub) and not hub[-1].reaches(sub, withdrawn)  # the viewer stops it
    sub.accounts = frozenset({_A})  # then the subscription narrows
    topic.group_changed(_group(1, "closed"))  # the whole item and the delta
    assert not any(frame.select(sub) or frame.viewer(withdrawn) for frame in hub[2:])
    assert len(hub) == 4 and _snap(topic, sub) == []


def test_a_delta_carries_only_the_changed_legs_and_totals() -> None:
    """Its time is the latest write on the group or a leg; it names the first leg's account."""
    topic, hub = _topic(_stored(1, _A, _B, _C))
    later = _US + 7_000
    changed = _leg(
        1, 1, _B, status="rejected", filled_qty=Decimal(0), rejection_code="risk_limit_breached",
        updated_at=later,
    )  # fmt: skip
    topic.leg_changed(changed)
    topic.group_changed(_group(1, "partially_open", updated_at=_US + 3_000))
    topic.group_changed(_group(1, "closing", updated_at=_US + 20_000))
    leg_frame, group_frame, closing = hub.to(_sub(_A, _B, _C))
    [leg] = leg_frame.item["legs"]
    assert set(leg_frame.item) == _DELTA | {"legs"}
    assert leg["id"] == str(changed.leg_id) and leg["status"] == "rejected"
    assert leg["error"] == {"code": "risk_limit_breached", "message": ""}
    assert leg_frame.item["totals"] == {
        "requested_legs": 3, "submitted_legs": 3, "rejected_legs": 1, "filled_qty": "0.008",
        "target_qty": "0.03", "realised_pnl": "0",
    }  # fmt: skip
    assert set(group_frame.item) == _DELTA and group_frame.item["status"] == "partially_open"
    assert leg_frame.item["updated_at_ms"] == group_frame.item["updated_at_ms"] == later // 1000
    assert closing.item["updated_at_ms"] == (_US + 20_000) // 1000  # the group's write, latest
    assert {frame.account for frame in hub} == {_A}


def test_a_created_group_is_sent_whole_as_its_first_frame() -> None:
    """Every member is new, so it is a snapshot item; it has no status before."""
    topic, hub = _topic()
    topic.created(_stored(1, _A, _B, status="submitting"))
    [frame] = hub
    assert frame.item == _snap(topic, _sub(_A, _B))[0]
    assert frame.select(_sub(_A, _B)) and frame.select(_sub(_A, _B, status=["submitting"]))
    assert not frame.select(_sub(_A, _B, status=["open"]))


@pytest.mark.parametrize(
    ("before", "after", "wanted", "got"),
    [
        ("submitting", "open", ["open"], "whole"),  # the group enters the view: sent whole
        ("open", "closing", ["open"], "delta"),  # it leaves the view: a plain delta
        ("open", "closing", ["open", "closing"], "delta"),  # it stays in it
        ("closing", "closed", ["open"], None),  # neither status is listed
        ("open", "closed", None, "delta"),  # no option keeps every change, as a delta
        ("open", "open", ["OPEN", "draft"], None),  # another status, or none at all
    ],
)
def test_the_status_filter_reads_the_status_before_or_after(
    before: str, after: str, wanted: list[str] | None, got: str | None
) -> None:
    """At most one frame per subscription and change, from two publishes on disjoint `select`s:
    the whole item where only the status after is listed (the subscription never received the
    group), else the delta where the status before is."""
    topic, hub = _topic(_stored(1, _A, status=before))
    topic.group_changed(_group(1, after))
    sub = _sub(_A) if wanted is None else _sub(_A, status=wanted)
    received = [frame.item if "legs" in frame.item else set(frame.item) for frame in hub.to(sub)]
    assert received == {"whole": _snap(topic, sub), "delta": [_DELTA], None: []}[got]


def test_a_snapshot_keeps_the_statuses_its_subscription_lists() -> None:
    topic, _ = _topic(_stored(1, _A), _stored(2, _A, status="closing"))
    assert _ids(_snap(topic, _sub(_A, status=["closing", "bogus"]))) == [_G2]
    assert _snap(topic, _sub(_A, status=[])) == []


def test_a_terminal_frame_is_the_groups_last() -> None:
    """The group leaves the model with it: a later write on its leg, or a repeat, sends nothing."""
    topic, hub = _topic(_stored(1, _A))
    topic.group_changed(_group(1, "failed"))
    topic.leg_changed(_leg(1, 0, _A, status="error"))
    topic.group_changed(_group(1, "failed"))
    [last] = hub.to(_sub(_A))
    assert last.item["status"] == "failed" and len(hub) == 2 and _snap(topic, _sub(_A)) == []


@pytest.mark.parametrize("final", _FINALS)
def test_a_seed_read_before_an_end_never_revives_the_group_and_the_ended_ids_are_bounded(
    final: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three groups end before a seed read earlier arrives (C-2.18: two ids are kept here): the two
    remembered stay out, and the oldest, forgotten, is held again. Every final status is an end."""
    monkeypatch.setattr(trade_group_topic, "ENDED_MAX", 2)
    hub = _Hub()
    topic: Topic = TradeGroupTopic(hub, SnapshotBody, _grants_cover)
    for n in (1, 2, 3):
        topic.group_changed(_group(n, final))
    topic.seed([_stored(n, _A) for n in (1, 2, 3)])
    assert _ids(_snap(topic, _sub(_A))) == [_G1]
    topic.leg_changed(_leg(2, 0, _A))
    assert hub == []


@pytest.mark.parametrize("case", ["held", *_FINALS, "draft", "legless"])
def test_a_creation_held_already_ended_draft_or_legless_sends_nothing(case: str) -> None:
    """A held group is never replaced, nor one that ended (in any final status) revived; a group
    with no leg would be no one's to see whole."""
    topic, hub = _topic(_stored(1, _A))
    record = _stored(2, _A)
    if case == "held":
        record = _stored(1, _A, _B)
    elif case in _FINALS:
        topic.group_changed(_group(2, case))
    elif case == "draft":
        record = _stored(2, _A, status="draft")
    else:
        record = TradeGroupWithLegs(group=_group(2), legs=())
    topic.created(record)
    [item] = _snap(topic, _sub(_A, _B))
    assert hub == [] and item["id"] == _G1 and len(item["legs"]) == 1


def test_a_draft_is_not_held_and_its_updates_are_no_end() -> None:
    """Nothing of it is sent, and it can still be handed over whole once it is active."""
    topic, hub = _topic()
    topic.created(_stored(1, _A, status="draft"))
    topic.group_changed(_group(1, "draft", note="edited"))
    assert hub == []
    topic.created(_stored(1, _A, status="submitting"))
    assert [frame.item["status"] for frame in hub] == ["submitting"]


def test_no_frame_carries_a_private_field() -> None:
    """The `v: 1` schema still declares `client_group_ref`, so the frames are checked, not the
    schema: no key and no value of `client_group_ref`, `created_by` or `note`, in any snapshot item
    or delta; `intent` is not stored, so never sent."""
    topic, hub = _topic(_stored(1, _A))
    topic.created(_stored(2, _A, _B))
    topic.leg_changed(_leg(2, 1, _B, rejection_code="c", rejection_message="m"))
    topic.group_changed(_group(2, "closing"))
    topic.group_changed(_group(2, "closed"))
    items = [frame.item for frame in hub] + _snap(topic, _sub(_A, _B))
    assert len(items) == 7  # two status changes: each the whole item and a delta
    for item in items:
        text = json.dumps(item)
        assert not _PRIVATE & set(item)
        assert str(_REF) not in text and str(_CREATOR) not in text and _NOTE not in text


def test_before_its_seed_there_is_no_snapshot() -> None:
    """On a real hub, which no connection is registered with: an event may come before the seed and
    its group is held; the snapshot waits for the seed, which is taken once. Private: never cached,
    no continuity."""
    topic: Topic = TradeGroupTopic(SequencingHub().publish, SnapshotBody, _grants_cover)
    sub = _sub(_A)
    with capture_logs() as logs:
        topic.created(_stored(2, _A))
    assert logs == [] and topic.build(sub) is None
    topic.seed([_stored(1, _A)])
    assert _ids(_snap(topic, sub)) == [_G1, _G2]
    assert topic.generation(sub) == 0 and topic.continuity(sub, 1) is False
    with pytest.raises(ValueError, match="already seeded"):
        topic.seed([])


def test_a_failing_publish_is_contained() -> None:
    """Logged by its error type, never its message, at most once a minute with the count held back;
    never raised. The model moved first, so the group that ended left it all the same."""
    clock = Clock()
    topic, hub = _topic(_stored(1, _A), clock=clock)
    hub.error = RuntimeError(_ECHO)
    with capture_logs() as logs:
        topic.leg_changed(_leg(1, 0, _A))
        topic.leg_changed(_leg(1, 0, _A))
        clock.now = LOG_INTERVAL_S
        topic.group_changed(_group(1, "closed"))
    line = {"event": "trade_group_topic.publish_failed", "error": "RuntimeError"}
    assert logs == [
        line | {"path": "leg_changed", "suppressed": 0, "log_level": "error"},
        line | {"path": "group_changed", "suppressed": 1, "log_level": "error"},
    ]
    hub.error = None
    assert _snap(topic, _sub(_A)) == []
    topic.created(_stored(2, _A))
    assert [frame.item["id"] for frame in hub] == [_G2]


@pytest.mark.parametrize("side", ["hub", "viewer_for"])
def test_a_cancellation_is_not_contained_whichever_side_raises_it(side: str) -> None:
    """The containment holds back an `Exception`, never a cancellation."""

    def cancelled(accounts: frozenset[UUID]) -> Callable[[PrincipalSnapshot], bool]:
        raise asyncio.CancelledError

    hub = _Hub()
    hub.error = asyncio.CancelledError() if side == "hub" else None
    topic: Topic = TradeGroupTopic(hub, SnapshotBody, cancelled if side != "hub" else _grants_cover)
    with pytest.raises(asyncio.CancelledError):
        topic.created(_stored(1, _A))


def test_the_every_leg_rule_fails_closed_on_a_set_with_no_account() -> None:
    """A group with no leg is never held; were one, no subscription would cover it, not even one
    with no account."""
    assert not trade_group_topic._covers(_sub(), frozenset())


@pytest.mark.parametrize("text", ["-0", "1E+2", "100.000", "1E-18"])
def test_a_decimal_is_written_as_the_rest_projection_writes_it(text: str) -> None:
    """`accounts` may not import `api`, so the topic renders with a private copy of REST's rule."""
    assert trade_group_topic._plain(Decimal(text)) == plain(Decimal(text))
