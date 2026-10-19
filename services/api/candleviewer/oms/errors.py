"""Domain errors for the oms module (M14)."""

from __future__ import annotations

from typing import Final

#: Codes the OMS raises itself, never mapped from an exchange answer (24 Sec.8.6).
ILLEGAL_TRANSITION: Final = "ILLEGAL_TRANSITION"
POST_TERMINAL_PUSH: Final = "POST_TERMINAL_PUSH"


class OmsError(Exception):
    """Base exception for the M14 `oms` module."""


class IllegalTransition(OmsError):
    """A command, or a step, that B1's static table does not list for the order's state (24
    Sec.8.2): refused before anything is sent or written. `attempted` is the event, or the state a
    step would enter."""

    code: Final = ILLEGAL_TRANSITION

    def __init__(self, state: str, attempted: str) -> None:
        super().__init__(f"{attempted} is not a transition of {state} (B1)")
        self.state = state
        self.attempted = attempted


class ReconcileAnomaly(OmsError):
    """S6: an exchange push for an order that is final, or a fill for one that is held, changes
    nothing. It is audited ahead (`oms.reconcile_anomaly`) and counted before this is raised."""

    code: Final = POST_TERMINAL_PUSH

    def __init__(self, state: str, event: str) -> None:
        super().__init__(f"{event} for an order that is {state} changes nothing (24 Sec.8.2 S6)")
        self.state = state
        self.event = event


class OrderStepRefused(OmsError):
    """B1 rolled the step back (24 Sec.8.2 S7, S11): its write-ahead row was refused or an action
    failed, so the order is as it was and nothing was sent. `failure` is the error's class."""

    def __init__(self, event: str, failure: str) -> None:
        super().__init__(f"the order did not take {event}: {failure}")
        self.event = event
        self.failure = failure


class OrderHistoryRefused(OmsError):
    """An order's `order_events` do not rebuild its row, or do not replay on B1 (threat model
    OM-T03; 24 Sec.8.2 "Recovery"): the order is not hydrated, nothing is written, and the facade
    pages. Names the fault in the history, never a value from it."""


class OrderNotLoaded(OmsError):
    """No machine in this process holds the order, and its stored row is not final (or the account
    holds no such order): nothing was sent."""


class OrderMachinesFull(OmsError):
    """The process holds `MAX_MACHINES` live order machines (C-2.18). A live machine is never
    evicted, so the new order is refused before anything is written."""


class OrderBufferFull(OmsError):
    """The order's reorder buffer holds `MAX_HELD` pushes (C-2.18): this one is refused, so the
    caller must resync it (24 Sec.8.5 step 2 applies every execution again)."""


class InvalidOrderLinkId(OmsError):
    """A string the §8.3 generator cannot produce, or parts that cannot render one."""


class UnsupportedExecutionMode(OmsError):
    """`replay` has no §8.3 environment letter, so generation fails closed (#846 Q4)."""


class OrderLinkIdExhausted(OmsError):
    """§8.3 rule 5: still colliding after 16 `seq2` increments, or at `seq2` = 3843."""

    def __init__(self, *, first: str, last: str) -> None:
        super().__init__(f"no free order_link_id from {first} to {last}")
        self.first = first
        self.last = last


class InvalidHistoryRetention(OmsError, ValueError):
    """An exchange order retention under 2 days: §8.3 rule 6 expires an id after the
    retention less one day, so 1 day or less would expire every id on creation."""


class ExecutionRefused(OmsError, ValueError):
    """An execution the order cannot absorb, hostile or malformed exchange data (OM-T04): a fill
    past `qty`, a qty or price of zero or less, a fee past `MAX_FEE_RATE` or against its rate, or a
    total numeric(38,18) cannot hold. Never clamped; the message names the rule, never a value."""


class DuplicateOrderLinkId(OmsError):
    """`ux_orders_link` already holds this id, so the order was not stored (#845 Gherkin).

    The rule 5 collision check runs before the insert; this is the race it cannot see. The id is
    taken: the caller never sends under it, and allocates again (24 Sec.8.3 rule 5)."""

    def __init__(self, order_link_id: str) -> None:
        super().__init__(f"order_link_id {order_link_id} is already stored")
        self.order_link_id = order_link_id
