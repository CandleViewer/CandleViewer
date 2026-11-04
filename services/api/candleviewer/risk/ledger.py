"""Headroom reservation for in-flight orders (E39-T01, M17; SR-E39-04, BQ-7).

`admit` evaluates an order on the counters' snapshot plus every reservation still in flight, and
reserves its headroom in the same synchronous step: there is no `await` between the two, so on the
single asyncio loop two submits near a cap cannot both pass it. A reservation holds the order's
pending notional, an open-position slot when it opens one, a concurrent-order slot and an
orders-per-minute slot. It converts as fills arrive (`on_fill`; the fill itself reaches the
counters) and is released on a refusal, a cancel or any terminal state (`release`). An
acknowledgement keeps it: a working order still holds its slot and its unfilled notional. Headroom
stays reserved until the fill converts it or a terminal outcome releases it.

Idempotent by reference: `admit` with a reference already holding a reservation returns that
reservation's verdict and reserves nothing more (a C-2.10 retry re-entering the gate), so there is
no "already admitted" refusal for a refusal handler to mistake for its own and release. The retry
must be the same order: a held reference re-entering with another account, environment, paper
flag, acting user, symbol, side, quantity, notional, reduce-only flag or effect is refused closed
(`risk_state_unavailable` on the cap `order_ref`, m8, l15) and the held reservation is kept, so an
amended intent never rides an earlier verdict. Exempt first (SR-E39-02): an exempt close is never
refused, a held reference included; it is recorded only when the reference holds nothing, so a held
opening reservation is neither replaced (freeing its headroom) nor charged twice.

Reconciled (BQ-7): `reconcile` takes the venue's open-order references read at `as_of` and
releases every reservation admitted at least `RECONCILE_GRACE` before it that is no longer open,
so a release missed on one terminal path cannot hold headroom for ever; it releases nothing still
open or too young to be seen open, or whose filled notional the read does not carry, so it never
loosens a cap. It releases on absence, so the read must be complete (the caller contract on
`reconcile`, m12); a read the caller cannot vouch for is passed `complete=False` and releases
nothing.

A released reservation that still holds unconverted notional is cleared only by `on_fill`:
`reconcile` skips it and a later `release` never lowers it, so a backfill of missed executions
(slice 3) routes them through `on_fill`; until it does, the hold stays (fail closed).

Malformed figures fail closed: a filled notional that is not a finite, non-negative `Decimal`
changes nothing, so the reservation is kept whole. `on_fill` is idempotent by execution id, as the
counters are: a repeated `exec_id` changes nothing. A reservation remembers at most
`MAX_FILLS` ids, dropped with it; a fill past them changes nothing either (fail closed): the part
left unconverted stays held for the reservation's life, until slice 3's rebuild or a restart.

Bounded: past `max_pending` reservations or `max_submits` sends in the trailing 60 s an opening
order is refused `risk_state_unavailable`; an exempt close is never refused and is recorded only
while there is room (SR-E39-02).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from candleviewer.domain.primitives import AccountId, Environment, Side, UserId
from candleviewer.risk.caps import ResolvedCaps
from candleviewer.risk.counters import AccountCounters
from candleviewer.risk.evaluator import DEFAULT_MAX_AGE, RiskEvaluation, evaluate
from candleviewer.risk.inputs import RiskFigures, RiskOrder
from candleviewer.risk.models import RiskDecision, RiskRefusal

MAX_PENDING: Final = 512
MAX_SUBMITS: Final = 4096
MAX_FILLS: Final = 1024
#: An order admitted this recently may not be on the venue's open-order read yet: kept.
RECONCILE_GRACE: Final = timedelta(seconds=60)
_WINDOW: Final = timedelta(seconds=60)
_ZERO: Final = Decimal(0)


def _amount(value: Decimal) -> bool:
    """A usable filled notional: finite and not negative (NaN never reaches the comparison)."""
    return value.is_finite() and value >= _ZERO


_Fingerprint = tuple[
    AccountId, Environment, bool, UserId | None, str, Side, Decimal, Decimal, bool, bool, bool
]


def _fingerprint(order: RiskOrder) -> _Fingerprint:
    return (
        order.account_id,
        order.environment,
        order.paper,
        order.user_id,  # judged under this user's manager caps (l15)
        order.symbol,
        order.side,
        order.qty,
        order.notional,
        order.reduce_only,
        order.opens_exposure,
        order.opens_position,
    )  # the exemption is derived from the last three


@dataclass(slots=True)
class _Reservation:
    symbol: str
    notional: Decimal
    opens_position: bool
    evaluation: RiskEvaluation
    fingerprint: _Fingerprint
    admitted_at: datetime
    converted: Decimal = _ZERO
    done: bool = False  # a terminal outcome released it
    fills: set[str] = field(default_factory=set)  # the exec ids converted, at most MAX_FILLS


class ReservationLedger:
    """One account's in-flight reservations and its trailing-minute sends."""

    def __init__(self, *, max_pending: int = MAX_PENDING, max_submits: int = MAX_SUBMITS) -> None:
        self._max_pending = max_pending
        self._max_submits = max_submits
        self._pending: dict[str, _Reservation] = {}
        self._sent: deque[datetime] = deque()

    def __contains__(self, order_ref: str) -> bool:
        return order_ref in self._pending

    def verdict(self, order_ref: str) -> RiskEvaluation | None:
        """The verdict an order's reservation was admitted with; None when it holds none."""
        held = self._pending.get(order_ref)
        return None if held is None or held.done else held.evaluation

    def holds_same(self, order_ref: str, order: RiskOrder) -> bool:
        """Whether `order_ref`'s reservation was admitted for this same order (m8)."""
        held = self._pending.get(order_ref)
        return held is not None and held.fingerprint == _fingerprint(order)

    @property
    def reserved_notional(self) -> Decimal:
        return sum((r.notional for r in self._pending.values()), _ZERO)

    def _prune(self, now: datetime) -> None:
        while self._sent and now - self._sent[0] >= _WINDOW:
            self._sent.popleft()

    def full(self, now: datetime) -> bool:
        self._prune(now)
        return len(self._pending) >= self._max_pending or len(self._sent) >= self._max_submits

    def overlay(self, figures: RiskFigures, now: datetime) -> RiskFigures:
        """`figures` with every in-flight reservation and the trailing minute's sends added."""
        self._prune(now)
        notional = dict(figures.symbol_notional)
        for r in self._pending.values():
            notional[r.symbol] = notional.get(r.symbol, _ZERO) + r.notional
        return replace(
            figures,
            symbol_notional=notional,
            open_orders=figures.open_orders + sum(not r.done for r in self._pending.values()),
            open_positions=figures.open_positions
            + sum(r.opens_position for r in self._pending.values()),
            orders_last_minute=figures.orders_last_minute + len(self._sent),
        )

    def reserve(
        self, order_ref: str, order: RiskOrder, now: datetime, evaluation: RiskEvaluation
    ) -> bool:
        """Hold the order's headroom; False when full (the caller has checked the reference)."""
        if self.full(now):
            return False
        notional = _ZERO if order.exempt else order.notional
        self._pending[order_ref] = _Reservation(
            order.symbol, notional, order.opens_position, evaluation, _fingerprint(order), now
        )
        self._sent.append(now)
        return True

    def reconcile(
        self,
        open_refs: Collection[str],
        as_of: datetime,
        *,
        complete: bool,
        filled: Mapping[str, Decimal],
    ) -> tuple[str, ...]:
        """Release what the venue no longer holds open at `as_of` (module docstring); the refs
        released are a missed release hook each, for the service to log and count.

        Caller contract (slice 3, m12): `open_refs` is every open order of this account, across
        every page and every order filter (untriggered conditional orders included), keyed by the
        `order_ref` the gate admitted (the client order id, never the venue's own id), read within
        one cycle. `complete=True` vouches for exactly that; on a failed, partial or filtered read
        the caller passes `complete=False` (or skips the cycle) and nothing is released, since an
        open order missing from the set would have its headroom freed. `filled` maps each order
        the read no longer holds open to its cumulative opening filled notional (`release`'s); one
        it does not carry, or carries a malformed figure for, is kept whole."""
        if not complete:
            return ()
        gone = tuple(
            ref
            for ref, held in self._pending.items()
            if not held.done
            and ref not in open_refs
            and ref in filled
            and _amount(filled[ref])
            and held.admitted_at <= as_of - RECONCILE_GRACE
        )
        for ref in gone:
            self.release(ref, filled_notional=filled[ref])
        return gone

    def on_fill(self, order_ref: str, exec_id: str, filled_notional: Decimal) -> None:
        """Convert filled notional: the position now carries it, so the reservation drops it.

        Only opening notional converts: the binding (slice 4) passes what a fill opened and 0 for
        a closing fill, so a flip's closing leg does not drain the reservation before its opening
        leg reaches the position, and the open-position slot is dropped only when opening
        notional converts (a positive figure). A malformed figure, an `exec_id` already converted
        or one past `MAX_FILLS` changes nothing."""
        held = self._pending.get(order_ref)
        if held is None or not _amount(filled_notional) or exec_id in held.fills:
            return
        if len(held.fills) >= MAX_FILLS:  # past the bound: kept whole, never converted twice
            return
        held.fills.add(exec_id)
        held.converted += filled_notional
        held.notional = max(_ZERO, held.notional - filled_notional)
        if filled_notional > _ZERO:
            held.opens_position = False
        if held.done and not held.notional:
            del self._pending[order_ref]

    def release(self, order_ref: str, *, filled_notional: Decimal) -> bool:
        """Refused, cancelled, rejected or terminal: free the rest of the headroom; True when the
        reference held a live reservation and the figure was usable.

        Required: the caller passes the order's cumulative opening filled notional (`on_fill`'s
        units), and 0 only when the order truly filled nothing. The unconverted part stays held
        until `on_fill` converts it (module docstring). A malformed figure changes nothing."""
        held = self._pending.get(order_ref)
        if held is None or not _amount(filled_notional):
            return False
        unconverted = max(_ZERO, filled_notional - held.converted)
        live = not held.done
        held.notional = unconverted if live else max(unconverted, held.notional)
        held.done = True
        if not held.notional:
            del self._pending[order_ref]
        return live


_REUSED: Final = "the order reference is held by a different order"
_RELEASED: Final = "the order reference belongs to a released order whose fills are still held"


def _refused(now: datetime, cap: str, message: str) -> RiskEvaluation:
    return RiskEvaluation(
        RiskDecision(
            allowed=False,
            code=RiskRefusal.RISK_STATE_UNAVAILABLE,
            cap=cap,
            message=message,
            evaluated_at=now,
        )
    )


def _unavailable(now: datetime) -> RiskEvaluation:
    return _refused(now, "risk_state", "risk state is unavailable")


def admit(
    order_ref: str,
    order: RiskOrder,
    caps: ResolvedCaps,
    counters: AccountCounters,
    ledger: ReservationLedger,
    *,
    now: datetime,
    lockout_active: bool = False,
    kill_switch_engaged: bool = False,
    max_age: timedelta = DEFAULT_MAX_AGE,
    extra_loss_usd: Decimal = _ZERO,
) -> RiskEvaluation:
    """Evaluate and reserve in one synchronous step (SR-E39-04); `order_ref` is the order's id.

    A reference already holding a reservation gets its earlier verdict back, or a refusal when it
    was admitted for a different order, unless the order is exempt (module docstring).
    `extra_loss_usd` is `evaluate`'s, and the caller's to bound: nothing in `risk/` does, so slice
    3's `RiskService` refuses closed an allowance above `risk_policy.override_extra_loss_max_usd`
    (E39-S02, BQ-3) before it calls `admit`."""
    held = ledger.verdict(order_ref)
    if order.exempt:  # never refused, whatever the reference holds (M3, SR-E39-02)
        if held is not None and ledger.holds_same(order_ref, order):
            return held
        allowed = RiskEvaluation(RiskDecision(allowed=True, evaluated_at=now))
        if order_ref not in ledger:  # recorded on a free reference while there is room
            ledger.reserve(order_ref, order, now, allowed)
        return allowed
    if held is not None:
        return held if ledger.holds_same(order_ref, order) else _refused(now, "order_ref", _REUSED)
    if order_ref in ledger:  # held by a released order
        return _refused(now, "order_ref", _RELEASED)
    snapshot = counters.figures(now)
    if snapshot is None or ledger.full(now):
        return _unavailable(now)
    figures = replace(
        ledger.overlay(snapshot, now),
        lockout_active=lockout_active,
        kill_switch_engaged=kill_switch_engaged,
    )
    evaluation = evaluate(
        order, figures, caps, now=now, max_age=max_age, extra_loss_usd=extra_loss_usd
    )
    if evaluation.decision.allowed and not ledger.reserve(order_ref, order, now, evaluation):
        return _unavailable(now)  # never admitted unreserved
    return evaluation
