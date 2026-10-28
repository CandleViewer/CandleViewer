"""#898 B3b1 (E27-S04): the exposure gate, one decision for the revoke of an account's last
signable key, its disable and its delete (22 `OpenExposure`, SR-E27-07, C-2.6).

Every branch of 22's choice table, a Hypothesis run against a reference model written from 22's
prose, and the flatten port: the null `Flattener` leaves every non-flat account refused, a real
one that reports the account flat lets the operation proceed. Pure, no I/O.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, get_args
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.accounts.consequences import AccountConsequences
from candleviewer.accounts.exposure import ExchangePosition, ExposureFailed, ExposureUnknown
from candleviewer.accounts.exposure_gate import (
    Choice,
    Flatten,
    Operation,
    Proceed,
    Refuse,
    decide,
    gate,
)
from candleviewer.accounts.flatten import NoFlatten
from candleviewer.accounts.profile_repository import ArmedRule

ACC = UUID("a1000000-0000-4000-8000-000000000001")
OWNER = UUID("00000000-0000-4000-8000-0000000000aa")
K1, K2 = UUID(int=1), UUID(int=2)
ERRORS = ((K1, "auth_error"), (K2, "auth_error"))
OPS: tuple[Operation, ...] = get_args(Operation.__value__)
CHOICES: tuple[Choice, ...] = (None, "leave_positions", "flatten_first")
NOT_DELETE = [op for op in OPS if op != "delete"]
GO = Proceed(False, ())
NO_CHOICE = Refuse("open_exposure", 409, why="no_choice")
NO_STOP = Refuse("open_exposure", 409, why="native_stop_missing")
NOT_FLAT = Refuse("open_exposure", 409, why="still_not_flat")


def _position(*, stop: bool) -> ExchangePosition:
    return ExchangePosition(
        symbol="BTCUSDT", position_idx=0, side="long", size=Decimal("1"),
        avg_price=Decimal("60000"), mark_price=None, liq_price=None, leverage=Decimal("5"),
        unrealised_pnl=Decimal("0"), take_profit=Decimal("70000"),
        stop_loss=Decimal("50000") if stop else None, trailing_stop=None, updated_at_us=1,
    )  # fmt: skip


def _read(*positions: ExchangePosition, orders: int = 0, algos: int = 0) -> AccountConsequences:
    rule = ArmedRule(UUID(int=9), "r")
    return AccountConsequences(ACC, positions, orders, algos, (), (rule,))


FLAT = _read()
STOPPED = _read(_position(stop=True))
UNSTOPPED = _read(_position(stop=True), _position(stop=False))
DEAD = ExposureUnknown("leave_positions", ERRORS)
FIXABLE = ExposureUnknown("fix_key", ((K1, "ip_not_allowed"),))
DOWN = ExposureFailed(503, "timeout", None, ((K1, "timeout"),))
ERRED = ExposureFailed(502, "rate_limited", 10006, ((K1, "rate_limited"),))


class _Flat:
    """A flattener that reports the account flat, and what it was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[UUID, UUID]] = []

    async def flatten(self, account_id: UUID, *, actor: UUID) -> bool:
        self.asked.append((account_id, actor))
        return True


# -- the branches --


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("choice", CHOICES)
def test_a_failed_read_fails_closed_with_its_own_status_whatever_the_choice(
    op: Operation, choice: Choice
) -> None:
    if op == "delete" and choice == "leave_positions":
        return
    assert decide(op, DOWN, choice, last_signable=True) == Refuse("exchange_unavailable", 503)
    erred = Refuse("exchange_error", 502, ret_code=10006)
    assert decide(op, ERRED, choice, last_signable=True) == erred


@pytest.mark.parametrize("choice", [None, "flatten_first"])
@pytest.mark.parametrize("unknown", [DEAD, FIXABLE])
def test_a_delete_of_unknown_exposure_is_always_exposure_unknown(
    choice: Choice, unknown: ExposureUnknown
) -> None:
    refused = Refuse("exposure_unknown", 409, remedy=unknown.remedy)
    assert decide("delete", unknown, choice, last_signable=True) == refused


@pytest.mark.parametrize("op", NOT_DELETE)
def test_a_dead_account_proceeds_only_with_leave_positions_the_stop_refusal_lifted(
    op: Operation,
) -> None:
    assert decide(op, DEAD, "leave_positions", last_signable=True) == Proceed(True, ERRORS)
    refused = Refuse("exposure_unknown", 409, remedy="leave_positions")
    for choice in (None, "flatten_first"):
        assert decide(op, DEAD, choice, last_signable=True) == refused


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("choice", CHOICES)
def test_a_fixable_refusal_is_always_exposure_unknown_fix_key(
    op: Operation, choice: Choice
) -> None:
    if op == "delete" and choice == "leave_positions":
        return
    refused = Refuse("exposure_unknown", 409, remedy="fix_key")
    assert decide(op, FIXABLE, choice, last_signable=True) == refused


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("choice", CHOICES)
def test_a_flat_account_proceeds_and_the_choice_is_ignored(op: Operation, choice: Choice) -> None:
    if op == "delete" and choice == "leave_positions":
        return
    assert decide(op, FLAT, choice, last_signable=True) == GO


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize(
    "read", [STOPPED, _read(orders=1), _read(algos=1)], ids=["position", "order", "algo"]
)
def test_any_exposure_without_a_choice_is_open_exposure(
    op: Operation, read: AccountConsequences
) -> None:
    assert decide(op, read, None, last_signable=True) == NO_CHOICE


@pytest.mark.parametrize("op", NOT_DELETE)
def test_leave_positions_proceeds_while_every_position_carries_a_native_stop(
    op: Operation,
) -> None:
    assert decide(op, STOPPED, "leave_positions", last_signable=True) == GO
    assert decide(op, _read(orders=2), "leave_positions", last_signable=True) == GO


@pytest.mark.parametrize("op", NOT_DELETE)
def test_leave_positions_with_a_position_without_a_native_stop_is_refused(op: Operation) -> None:
    """C-2.6: once the last key is revoked or the account disabled nothing re-asserts it."""
    assert decide(op, UNSTOPPED, "leave_positions", last_signable=True) == NO_STOP


@pytest.mark.parametrize("op", OPS)
def test_flatten_first_on_a_non_flat_account_asks_the_flattener(op: Operation) -> None:
    assert decide(op, UNSTOPPED, "flatten_first", last_signable=True) == Flatten(ACC)


@pytest.mark.parametrize("read", [None, FLAT, UNSTOPPED, DEAD, FIXABLE, DOWN])
@pytest.mark.parametrize("choice", CHOICES)
def test_a_revoke_of_a_key_that_is_not_the_last_signable_one_reads_no_exposure(
    read: Any, choice: Choice
) -> None:
    """22: `flatten_first` is then a recorded no-op, and the revoke proceeds."""
    assert decide("revoke", read, choice, last_signable=False) == GO


def test_a_delete_with_leave_positions_never_reaches_the_gate() -> None:
    with pytest.raises(ValueError, match="flatten_first"):
        decide("delete", FLAT, "leave_positions", last_signable=True)


@pytest.mark.parametrize("op", OPS)
def test_a_decision_without_the_read_is_refused(op: Operation) -> None:
    with pytest.raises(ValueError, match="consequence read"):
        decide(op, None, None, last_signable=True)


# -- the flatten port --


@pytest.mark.parametrize("op", OPS)
async def test_the_null_flattener_leaves_a_non_flat_account_refused(op: Operation) -> None:
    got = await gate(
        op, UNSTOPPED, "flatten_first", last_signable=True, flattener=NoFlatten(), actor=OWNER
    )
    assert got == NOT_FLAT


async def test_a_flattener_that_reports_the_account_flat_lets_it_proceed() -> None:
    flat = _Flat()
    got = await gate(
        "disable", UNSTOPPED, "flatten_first", last_signable=True, flattener=flat, actor=OWNER
    )
    assert got == Proceed(False, (), flattened=True) and flat.asked == [(ACC, OWNER)]


async def test_the_gate_asks_no_flattener_for_any_other_decision() -> None:
    flat = _Flat()
    for read, choice in ((FLAT, "flatten_first"), (DEAD, "leave_positions"), (STOPPED, None)):
        await gate("revoke", read, choice, last_signable=True, flattener=flat, actor=OWNER)
    assert flat.asked == []


# -- the property: 22's table as a reference model --


def _model(op: str, read: Any, choice: Choice, last: bool) -> Proceed | Refuse | Flatten:
    """22 `OpenExposure`, read row by row, independently of the module's order."""
    if op == "revoke" and not last:
        return GO
    if isinstance(read, ExposureFailed):
        unavailable = read.status == 503
        kind = "exchange_unavailable" if unavailable else "exchange_error"
        return Refuse(kind, read.status, ret_code=None if unavailable else read.ret_code)
    if isinstance(read, ExposureUnknown):
        lift = op in {"disable", "revoke"} and read.remedy == "leave_positions"
        if lift and choice == "leave_positions":
            return Proceed(True, read.key_errors)
        return Refuse("exposure_unknown", 409, remedy=read.remedy)
    exposed = bool(read.open_positions) or read.working_orders > 0 or read.running_algos > 0
    if not exposed:
        return GO
    if choice == "flatten_first":
        return Flatten(read.account_id)
    if choice == "leave_positions" and all(p.native_stop_present for p in read.open_positions):
        return GO
    return NO_STOP if choice == "leave_positions" else NO_CHOICE


_positions = st.lists(st.booleans().map(lambda s: _position(stop=s)), max_size=3).map(tuple)
_known = st.builds(
    lambda ps, o, a: _read(*ps, orders=o, algos=a),
    _positions,
    st.integers(0, 2),
    st.integers(0, 2),
)
_unknown = st.sampled_from([DEAD, FIXABLE, ExposureUnknown("leave_positions", ())])
_failed = st.sampled_from([DOWN, ERRED, ExposureFailed(502, "exchange_unknown", None, ())])


@given(
    op=st.sampled_from(OPS),
    read=st.one_of(_known, _unknown, _failed),
    choice=st.sampled_from(CHOICES),
    last=st.booleans(),
)
def test_the_gate_matches_the_reference_model(
    op: Operation, read: Any, choice: Choice, last: bool
) -> None:
    if op == "delete" and choice == "leave_positions":
        with pytest.raises(ValueError):
            decide(op, read, choice, last_signable=last)
        return
    assert decide(op, read, choice, last_signable=last) == _model(op, read, choice, last)
