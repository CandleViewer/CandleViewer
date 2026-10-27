"""The `trade_groups` WS topic (E28-T05 #909, slice S4a; 23-ws-protocol.md §6.2, §8.2, §15.5): the
accounts module's read model of the active trade groups, its `SnapshotSource` for the family, and
the deltas the OMS's committed group writes publish on it. Plain code, never a statechart (C-2.20).

The accounts module may import neither `ws` nor `auth` (CONSTITUTION §3), so the topic is typed
structurally, as `wallet_topic` is: a subscription by the fields read here, and the hub's
`publish`, the gateway's body constructor and `viewer_for`, which reads a WS principal's grants,
injected by the composition root.

- **Model.** The active groups (`OPEN_GROUP_STATUSES`: `submitting`, `partially_open`, `open`,
  `closing`), each with every leg. `seed` loads them once, as stored at start; before it, `build`
  gives `None` and a subscription stays `snapshot_pending` (§7.7). An event may come first: its
  group is held, and the seed neither replaces a held group nor holds one that recently ended.
- **Deltas.** `created`, `leg_changed` and `group_changed`, each a committed write as stored,
  update the model and publish one delta, never merged (§8.2): `id`, `status`, `updated_at_ms`
  (the latest write on the group or a leg), `totals` (`group_totals`) and the changed legs, each
  whole. A created group is sent whole, as a snapshot item: every member is new. A group that
  leaves the active statuses leaves the model before its frame goes out, so a terminal frame is
  its last. The ids of the `ENDED_MAX` groups that most recently reached a final status are kept
  (C-2.18): a seed entry or a creation for one is refused, and a later change finds no group, so a
  late event sends nothing. A `draft` group is not held and nothing of it is sent; its updates are
  no end, so it can still be handed over whole (`created`) once it is active.
- **Scope (SR-E28-21).** A group is only ever sent whole. A delta names its first leg's account to
  the hub (`publish(account=)`) and asks, when it is sent, `select` whether the subscription's
  accounts (narrowed in place on every grant change, §9.5) hold every leg's and whether its
  `status` option lists the group's status before or after the change (a value outside
  `TradeGroupStatus` matches nothing), and `viewer` whether the connection's principal, as it is
  then, may see every leg's account. A grant withdrawn mid-stream stops the group at its next
  frame, the terminal one included.
- **Snapshot.** The held groups whose every leg's account the subscription holds and whose status
  its `status` option lists, oldest first, each whole. Private: never cached (generation 0), and
  no continuity (§7.6 forces a snapshot).
- **Members.** Never `client_group_ref`, `created_by` or `note`: the `v: 1` schema still declares
  `client_group_ref`, and §15.5 forbids it. `intent` is not stored, and `atomicity` is left out for
  `abort_on_first`, which its enum cannot name. A leg's `error` is `null`, or its stored code and
  message, an empty string standing for one not stored.
- **No flag.** `trading.trade_groups` does not gate the topic: with the flag off it shows the groups
  written while it was on, and `placeOrder`'s one-leg groups.
- **Failure.** A delta that fails is logged by its error type (never its message, C-12.6) and its
  path, at most once per `LOG_INTERVAL_S` with the count held back, and goes no further: the OMS
  neither waits on the topic nor sees it fail.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.trade_groups import (
    TradeGroup,
    TradeGroupLeg,
    TradeGroupWithLegs,
    group_totals,
)
from candleviewer.storage.repositories.trade_groups import OPEN_GROUP_STATUSES

#: Private topics are flat, scoped by their `exchange_account_ids` option (§6.2).
TRADE_GROUPS: Final = "trade_groups"
#: B2's final states: a group in one has ended for good.
_FINAL: Final = frozenset({"closed", "failed", "cancelled"})
#: How many recently ended group ids are kept, the oldest forgotten first.
ENDED_MAX: Final = 1024
#: A failed delta is logged at most once in this many seconds, the ones held back counted on the
#: next line: a hub that keeps failing never floods the log.
LOG_INTERVAL_S: Final = 60.0

type Item = dict[str, object]


class TradeGroupsSub(Protocol):
    """The fields of a WS `Subscription` read here: its accounts, narrowed to the caller's grants
    at `sub` and on every grant change (§6.2, §9.5), and its options after clamping."""

    @property
    def accounts(self) -> frozenset[UUID]: ...
    @property
    def effective(self) -> Mapping[str, Any]: ...


class Publish[P](Protocol):
    """`SequencingHub.publish`: one delta to the subscriptions in `account`'s scope that `select`
    accepts, on the connections whose principal `viewer` accepts."""

    def __call__(
        self,
        ch: str,
        body: Mapping[str, Any],
        *,
        account: UUID,
        select: Callable[[TradeGroupsSub], bool],
        viewer: Callable[[P], bool],
    ) -> int: ...


@dataclass(slots=True)
class _Held:
    """An active group and every leg, by id in fan-out order."""

    group: TradeGroup
    legs: dict[UUID, TradeGroupLeg]

    def accounts(self) -> frozenset[UUID]:
        return frozenset(leg.account_id for leg in self.legs.values())


def _plain(value: Decimal | None) -> str | None:
    """Every digit, no exponent and no trailing fractional zero, as the REST projection writes."""
    if value is None:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _leg_item(leg: TradeGroupLeg) -> Item:
    code, message, profile = leg.rejection_code, leg.rejection_message, leg.account_profile_id
    stored = code is not None or message is not None
    return {
        "id": str(leg.leg_id), "exchange_account_id": str(leg.account_id),
        "account_profile_id": None if profile is None else str(profile),
        "sequence_no": leg.sequence_no, "status": leg.status,
        "target_qty": _plain(leg.target_qty), "filled_qty": _plain(leg.filled_qty),
        "avg_entry_price": _plain(leg.avg_entry_price),
        "avg_exit_price": _plain(leg.avg_exit_price),
        "native_sl_confirmed": leg.native_sl_confirmed, "risk_usd": _plain(leg.risk_usd),
        "realised_pnl": _plain(leg.realised_pnl), "fees_paid": _plain(leg.fees_paid),
        "error": {"code": code or "", "message": message or ""} if stored else None,
    }  # fmt: skip


def _head(held: _Held) -> Item:
    """What every frame of a group holds: its id, status, latest write and totals."""
    group, legs = held.group, held.legs.values()
    totals = group_totals(legs)
    latest = max([group.updated_at, *(leg.updated_at for leg in legs)])
    return {
        "id": str(group.group_id), "status": group.status, "updated_at_ms": latest // 1000,
        "totals": {
            "requested_legs": totals.requested_legs, "submitted_legs": totals.submitted_legs,
            "rejected_legs": totals.rejected_legs, "filled_qty": _plain(totals.filled_qty),
            "target_qty": _plain(totals.target_qty), "realised_pnl": _plain(totals.realised_pnl),
        },
    }  # fmt: skip


def _whole(held: _Held) -> Item:
    """A snapshot item, and a created group's frame: every member §15.5 serves, every leg."""
    group = held.group
    item = _head(held) | {
        "symbol": group.symbol, "side": group.side, "algo_kind": group.algo,
        "rule_id": None if group.rule_id is None else str(group.rule_id),
        "legs": [_leg_item(leg) for leg in held.legs.values()],
    }  # fmt: skip
    if group.leg_failure_policy != "abort_on_first":
        item["atomicity"] = group.leg_failure_policy
    return item


def _covers(sub: TradeGroupsSub, accounts: frozenset[UUID]) -> bool:
    """SR-E28-21: the subscription's accounts, as they are now, hold every leg's."""
    return accounts <= sub.accounts


def _lists(sub: TradeGroupsSub, *statuses: str | None) -> bool:
    """The `status` option is absent, or lists one of `statuses` (before and after a change)."""
    wanted = sub.effective.get("status")
    return wanted is None or any(status in wanted for status in statuses)


class TradeGroupTopic[B, P]:
    """The `trade_groups` topic's read model, snapshot source and publisher (see the module
    docstring), for the event loop that serves the gateway: no locks."""

    def __init__(
        self,
        publish: Publish[P],
        body: Callable[[Mapping[str, Any]], B],
        viewer_for: Callable[[frozenset[UUID]], Callable[[P], bool]],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._publish, self._body, self._viewer_for, self._clock = publish, body, viewer_for, clock
        self._groups: dict[UUID, _Held] = {}
        self._ended: dict[UUID, None] = {}  # insertion order: the oldest is forgotten first
        self._seeded = False
        self._log_from = 0.0  # `_contained`: the clock reading from which a failure is logged again
        self._suppressed = 0  # and how many it held back since its last line

    def seed(self, groups: Iterable[TradeGroupWithLegs]) -> None:
        """Hold the active groups as stored at start, once."""
        if self._seeded:
            raise ValueError("the trade_groups topic is already seeded")
        for record in groups:
            self._hold(record)
        self._seeded = True

    # -- SnapshotSource

    def build(self, sub: TradeGroupsSub) -> B | None:
        if not self._seeded:
            return None
        held = sorted(self._groups.values(), key=lambda h: (h.group.created_at, h.group.group_id))
        items = [
            _whole(h) for h in held if _covers(sub, h.accounts()) and _lists(sub, h.group.status)
        ]
        return self._body({"trade_groups": items})

    def generation(self, sub: TradeGroupsSub) -> int:
        return 0  # a private family's snapshot is never cached (SR-190)

    def continuity(self, sub: TradeGroupsSub, from_ts_ms: int | None) -> bool:
        return False  # no delta history: `snapshot: false` is always `snapshot_forced`

    # -- deltas, one per committed write

    def created(self, record: TradeGroupWithLegs) -> None:
        """A group was stored: held, and sent whole, when it is active and not yet held."""
        with self._contained("created"):
            if (held := self._hold(record)) is not None:
                self._to_hub(held, None, _whole(held))

    def leg_changed(self, leg: TradeGroupLeg) -> None:
        """A leg was updated: its group's frame, with that leg alone."""
        with self._contained("leg_changed"):
            if (held := self._groups.get(leg.group_id)) is not None:
                held.legs[leg.leg_id] = leg
                self._to_hub(held, held.group.status, _head(held) | {"legs": [_leg_item(leg)]})

    def group_changed(self, group: TradeGroup) -> None:
        """A group was updated: its frame, with no leg."""
        with self._contained("group_changed"):
            held = self._groups.get(group.group_id)
            if group.status not in OPEN_GROUP_STATUSES:
                self._leave(group)
            if held is not None:
                before, held.group = held.group.status, group
                self._to_hub(held, before, _head(held))

    def _hold(self, record: TradeGroupWithLegs) -> _Held | None:
        """Hold an active group not held yet, nor recently ended. One with no leg is not held: it
        would be no one's to see whole, and no frame of it could name an account."""
        group = record.group
        gid = group.group_id
        if gid in self._groups or gid in self._ended or group.status not in OPEN_GROUP_STATUSES:
            return None
        if not record.legs:
            return None
        held = self._groups[gid] = _Held(group, {leg.leg_id: leg for leg in record.legs})
        return held

    def _leave(self, group: TradeGroup) -> None:
        """Out of the model; an end (a final status, not a `draft`) is remembered."""
        self._groups.pop(group.group_id, None)
        if group.status in _FINAL:
            self._ended[group.group_id] = None
            if len(self._ended) > ENDED_MAX:
                del self._ended[next(iter(self._ended))]

    def _to_hub(self, held: _Held, before: str | None, item: Item) -> None:
        """One delta in the first leg's account's scope, judged on every leg when it is sent."""
        accounts, after = held.accounts(), held.group.status

        def select(sub: TradeGroupsSub) -> bool:
            return _covers(sub, accounts) and _lists(sub, before, after)

        first = next(iter(held.legs.values())).account_id
        viewer = self._viewer_for(accounts)
        self._publish(
            TRADE_GROUPS, {"trade_groups": [item]}, account=first, select=select, viewer=viewer
        )

    @contextmanager
    def _contained(self, path: str) -> Iterator[None]:
        """A delta that fails stays here, logged by its error type (never its message, C-12.6)
        and path, at most once per `LOG_INTERVAL_S`, with the count of those held back since the
        last line; a cancellation still propagates."""
        try:
            yield
        except Exception as exc:
            now = self._clock()
            if now < self._log_from:
                self._suppressed += 1
                return
            held, self._suppressed, self._log_from = self._suppressed, 0, now + LOG_INTERVAL_S
            structlog.get_logger(__name__).error(
                "trade_group_topic.publish_failed",
                path=path,
                error=type(exc).__name__,
                suppressed=held,
            )
