"""The WS subscription quota (E21-X02, #652; `23-ws-protocol.md` §5.4, §6.1, §16.2): G-01, the
cost-weighted quota per connection and per user, and G-02's user leg, a user's distinct heatmap
specs. Every value is interim until the Owner ratifies it (`ws/limits.py`).

- **Weights.** A subscription is weighed from its validated, effective options
  (`effective_options`), never from a value the client states, in points of
  `orderflow.heatmap.QUOTA_ROWS_PER_POINT` wire rows a second. A `heatmap.*` one weighs its columns
  at the faster of its effective throttle and its bucket (`column_points`), floored at
  `MIN_THROTTLE_MS`: a throttle above the bucket still sends one frame per column. A deep `book.*`
  (depth 200 or 500) weighs the measured rows of one depth-200 publish
  (`DEEP_BOOK_ROWS_PER_PUBLISH`), scaled by depth, at its publisher's rate. Every other family
  weighs 0 and is bounded by its own caps; `system` is never charged. `WEIGHTS` names every
  family of the catalogue, 0 included, so a family added without a weight fails its test, and a
  lookup of a family it lacks raises (never read as 0).
- **Ledgers.** `ConnectionQuota` holds a connection's points and `heatmap.*` subscriptions;
  `UserQuota`, one per process, the same per user across the user's connections, and the user's
  distinct specs, each counted once however many subscriptions hold it. The user is the acting one
  (`ConnectionAuthz.actor_user_id`: the viewer during view-as, 23 §9.6), so a viewer spends its own.
- **Refusals.** `refusal` names the first limit a charge would pass, in the order of 23 §16.2:
  `heatmap.*` per connection, per user, the user's distinct specs, of them those of one symbol,
  points per connection, per user; a charge that adds nothing is never refused. The caller
  answers `subscription_limit` with `MESSAGES[reason]`, which names the limit and its remedy,
  never another user's subscriptions or specs (HM-I04). Each refusal of the quota family, the
  deep-book cap's and the spec caps' too, counts once in
  `cv_ws_subscription_quota_rejections_total{reason}` and logs one line under the connection's
  refusal-log budget (`refused`); none writes an audit row (the model's AR-2).
- **Placement (BQ-5).** The gateway checks and charges in one synchronous step before anything is
  held upstream (`permissions.ConnectionAuthz._quota_refusal`), so no `sub` or `ctl` passes a
  budget another is spending, and a refused one takes nothing. This module never reads or spends an
  exchange rate-limit budget: it imports nothing from the exchange adapter.
- **Bounds (C-2.18).** A connection's ledger is two integers and a refusal-log limiter; a user is
  kept only while it holds a charge, so `UserQuota` holds at most the users with one.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal, get_args

import structlog

from candleviewer.observability.metrics import Counter
from candleviewer.orderflow.heatmap import (
    QUOTA_ROWS_PER_POINT,
    HeatmapSpec,
    column_points,
    spec_of,
)
from candleviewer.ws.lifecycle import RefusalLog, RefusalLogLimiter
from candleviewer.ws.limits import (
    DEEP_BOOK_MEASURED_DEPTH,
    DEEP_BOOK_MIN_DEPTH,
    DEEP_BOOK_PUBLISHES_PER_S,
    DEEP_BOOK_ROWS_PER_PUBLISH,
    MAX_HEATMAP_SPECS_PER_USER,
    MAX_HEATMAP_SPECS_PER_USER_SYMBOL,
    MAX_HEATMAP_SUBSCRIPTIONS,
    MAX_HEATMAP_SUBSCRIPTIONS_PER_USER,
    MIN_THROTTLE_MS,
    QUOTA_POINTS_PER_CONNECTION,
    QUOTA_POINTS_PER_USER,
)

if TYPE_CHECKING:
    from candleviewer.ws.topics import ParsedTopic

#: Every limit of the quota family, the `reason` of its refusals: the six of this module, the
#: deep-book cap (E21-T01) and the heatmap spec caps and points of the server (E21-T02, E21-X02).
QuotaReason = Literal[
    "deep_book_connection",
    "heatmap_connection",
    "heatmap_user",
    "points_connection",
    "points_user",
    "heatmap_specs_user",
    "heatmap_specs_user_symbol",
    "heatmap_specs_symbol",
    "heatmap_specs_server",
    "points_server",
]
REASONS: Final[tuple[QuotaReason, ...]] = get_args(QuotaReason)
#: The `HeatmapSpecCapError.cap` of a spec refused by `HeatmapTopic`, as the reason it counts under.
SPEC_CAP_REASONS: Final[Mapping[str, QuotaReason]] = {
    "symbol": "heatmap_specs_symbol",
    "server": "heatmap_specs_server",
    "points": "points_server",
}
#: The one message of each limit this module checks (23 §16.2): the limit and its remedy, never
#: another user's subscriptions or specs (HM-I04). The other reasons keep their own caps' messages.
MESSAGES: Final[Mapping[QuotaReason, str]] = {
    "heatmap_connection": (
        f"At most {MAX_HEATMAP_SUBSCRIPTIONS} heatmap subscriptions per connection; "
        "unsubscribe one."
    ),
    "heatmap_user": (
        f"At most {MAX_HEATMAP_SUBSCRIPTIONS_PER_USER} heatmap subscriptions per user, across "
        "connections; unsubscribe one."
    ),
    "heatmap_specs_user": (
        f"At most {MAX_HEATMAP_SPECS_PER_USER} distinct heatmap specs per user; reuse one or "
        "unsubscribe one."
    ),
    "heatmap_specs_user_symbol": (
        f"At most {MAX_HEATMAP_SPECS_PER_USER_SYMBOL} distinct heatmap specs of one symbol per "
        "user; reuse one or unsubscribe one."
    ),
    "points_connection": (
        f"Subscription quota of {QUOTA_POINTS_PER_CONNECTION} points per connection reached; "
        "unsubscribe one, or use a shallower depth or a slower bucket or throttle."
    ),
    "points_user": (
        f"Subscription quota of {QUOTA_POINTS_PER_USER} points per user reached; unsubscribe one, "
        "or use a shallower depth or a slower bucket or throttle."
    ),
}

cv_ws_subscription_quota_rejections_total = Counter(
    "cv_ws_subscription_quota_rejections_total",
    "WS sub entries and ctl frames the subscription quota family refused (23 section 16.2), by "
    "limit.",
    labelnames=("reason",),
)
#: Each child bound at import, so every series exists at 0 and a refusal does no label lookup.
_REFUSED: Final = {r: cv_ws_subscription_quota_rejections_total.labels(reason=r) for r in REASONS}


@dataclass(frozen=True, slots=True)
class Charge:
    """What one subscription holds of the quota: its points, and a `heatmap.*` one's spec."""

    points: int = 0
    spec: HeatmapSpec | None = None


#: The charge of a subscription that weighs nothing.
FREE: Final = Charge()


def _free(topic: ParsedTopic, effective: Mapping[str, Any]) -> Charge:
    return FREE


def _book(topic: ParsedTopic, effective: Mapping[str, Any]) -> Charge:
    """A deep `book.*`: ⌈rows x publishes a second ÷ the point⌉, its rows the measured depth-200
    ones scaled by depth."""
    depth = topic.depth or 0
    if depth < DEEP_BOOK_MIN_DEPTH:
        return FREE
    rows_per_s = DEEP_BOOK_ROWS_PER_PUBLISH * depth * DEEP_BOOK_PUBLISHES_PER_S
    return Charge(-(-rows_per_s // (DEEP_BOOK_MEASURED_DEPTH * QUOTA_ROWS_PER_POINT)))


def _heatmap(topic: ParsedTopic, effective: Mapping[str, Any]) -> Charge:
    """A `heatmap.*`: its columns at the faster of its effective throttle and its bucket."""
    spec = spec_of(topic.symbol or "", effective)
    period = max(MIN_THROTTLE_MS, min(int(effective["throttle_ms"]), spec.time_bucket_ms))
    return Charge(column_points(spec.depth, period), spec)


#: Each family of the catalogue (`topics.FAMILIES`) and its weight, 0 included (`_free`).
WEIGHTS: Final[Mapping[str, Callable[[ParsedTopic, Mapping[str, Any]], Charge]]] = {
    "book": _book,
    "heatmap": _heatmap,
    "trades": _free,
    "bars": _free,
    "footprint": _free,
    "indicators": _free,
    "profile": _free,
    "metrics": _free,
    "ticker": _free,
    "liquidations": _free,
    "orders": _free,
    "positions": _free,
    "executions": _free,
    "wallet": _free,
    "trade_groups": _free,
    "rules": _free,
    "alerts": _free,
    "recorder": _free,
    "system": _free,
    "machines": _free,
}


def charge_of(topic: ParsedTopic, effective: Mapping[str, Any]) -> Charge:
    """The charge of a subscription of `topic` with these validated, effective options. A family
    `WEIGHTS` lacks raises `KeyError`: it is a gap in the table, never a weight of 0."""
    return WEIGHTS[topic.family.family](topic, effective)


@dataclass
class _Held:
    """One user's charges: points, `heatmap.*` subscriptions and, per spec, how many hold it."""

    points: int = 0
    heatmaps: int = 0
    specs: dict[HeatmapSpec, int] = field(default_factory=dict)


class UserQuota:
    """The quota of each user, one per process (`SubscriptionServices.user_quota`), which every
    connection of the user charges too (module doc). Bounded (C-2.18): a user is kept only while it
    holds a charge."""

    def __init__(
        self,
        *,
        points: int = QUOTA_POINTS_PER_USER,
        heatmaps: int = MAX_HEATMAP_SUBSCRIPTIONS_PER_USER,
        specs: int = MAX_HEATMAP_SPECS_PER_USER,
        specs_per_symbol: int = MAX_HEATMAP_SPECS_PER_USER_SYMBOL,
    ) -> None:
        self.points, self.heatmaps, self.specs = points, heatmaps, specs
        self.specs_per_symbol = specs_per_symbol
        self._users: dict[uuid.UUID, _Held] = {}

    def __len__(self) -> int:
        """The users kept: those holding a charge."""
        return len(self._users)

    def held(self, user: uuid.UUID) -> tuple[int, int, dict[HeatmapSpec, int]]:
        """`user`'s points, `heatmap.*` subscriptions and subscriptions per spec (a copy)."""
        h = self._users.get(user, _Held())
        return h.points, h.heatmaps, dict(h.specs)

    def refusal(self, user: uuid.UUID, new: Charge, old: Charge = FREE) -> QuotaReason | None:
        """The first of `user`'s limits that `new` in place of `old` would pass, else None."""
        h = self._users.get(user, _Held())
        heatmaps = h.heatmaps + (new.spec is not None) - (old.spec is not None)
        if heatmaps > h.heatmaps and heatmaps > self.heatmaps:
            return "heatmap_user"
        if new.spec is not None and new.spec != old.spec and new.spec not in h.specs:
            # a spec this one moves off goes too if it is the user's last subscription on it
            leaving = old.spec if old.spec is not None and h.specs.get(old.spec) == 1 else None
            if len(h.specs) - (leaving is not None) + 1 > self.specs:
                return "heatmap_specs_user"
            symbol = new.spec.symbol
            mine = sum(1 for s in h.specs if s.symbol == symbol and s != leaving)
            if mine + 1 > self.specs_per_symbol:
                return "heatmap_specs_user_symbol"
        points = h.points - old.points + new.points
        if points > h.points and points > self.points:
            return "points_user"
        return None

    def move(self, user: uuid.UUID, new: Charge, old: Charge = FREE) -> None:
        """Move `user`'s charge from `old` to `new`; forget the user once it holds nothing."""
        h = self._users.setdefault(user, _Held())
        h.points += new.points - old.points
        h.heatmaps += (new.spec is not None) - (old.spec is not None)
        if old.spec is not None:
            if (left := h.specs.get(old.spec, 1) - 1) > 0:
                h.specs[old.spec] = left
            else:
                h.specs.pop(old.spec, None)
        if new.spec is not None:
            h.specs[new.spec] = h.specs.get(new.spec, 0) + 1
        if h.points <= 0 and h.heatmaps <= 0 and not h.specs:
            del self._users[user]


class ConnectionQuota:
    """One connection's quota (`ConnectionAuthz.quota`), its user's in `users` (module doc). Each
    check and the charge it admits run in one synchronous step of the caller's, with no await."""

    def __init__(
        self,
        users: UserQuota,
        user: uuid.UUID,
        *,
        clock: Callable[[], float],
        points: int = QUOTA_POINTS_PER_CONNECTION,
        heatmaps: int = MAX_HEATMAP_SUBSCRIPTIONS,
    ) -> None:
        self.users, self.user, self._clock = users, user, clock
        self.max_points, self.max_heatmaps = points, heatmaps
        self.points = 0  # the connection's charged points
        self.heatmaps = 0  # its charged `heatmap.*` subscriptions
        self._logs = RefusalLogLimiter()  # the refusal line, capped per reason

    def refusal(self, new: Charge, old: Charge = FREE) -> QuotaReason | None:
        """The first limit, of the connection's and its user's, that `new` in place of `old` would
        pass, in the order of 23 §16.2; None when each holds. A limit is passed only by a charge
        that raises what it counts, so a change that adds nothing is never refused."""
        heatmaps = self.heatmaps + (new.spec is not None) - (old.spec is not None)
        if heatmaps > self.heatmaps and heatmaps > self.max_heatmaps:
            return "heatmap_connection"
        user = self.users.refusal(self.user, new, old)
        if user is not None and user != "points_user":
            return user
        points = self.points - old.points + new.points
        if points > self.points and points > self.max_points:
            return "points_connection"
        return user

    def charge(self, new: Charge, old: Charge = FREE) -> None:
        """Move the connection's and its user's charge from `old` to `new` (a `refusal` passed)."""
        self.points += new.points - old.points
        self.heatmaps += (new.spec is not None) - (old.spec is not None)
        self.users.move(self.user, new, old)

    def credit(self, held: Charge) -> None:
        """Give back what an ended subscription held."""
        self.charge(FREE, held)

    def refused(self, reason: QuotaReason, ch: str, connection_id: str) -> None:
        """Count one refusal of the quota family under `reason`, and log it within the
        connection's refusal-log budget: the first `REFUSAL_LOG_LIMIT` a window per reason, then
        one flagged `capped`, then none. The line names the connection, the acting user and the
        topic, which no metric label may carry."""
        _REFUSED[reason].inc()
        if (verdict := self._logs.admit(reason, self._clock())) is RefusalLog.NONE:
            return
        line: dict[str, Any] = {"reason": reason, "ch": ch, "connection_id": connection_id}
        if verdict is RefusalLog.SUMMARY:
            line["capped"] = True
        structlog.get_logger(__name__).warning(
            "ws subscription quota refused", user_id=str(self.user), **line
        )
