"""The exposure gate: one decision for revoking an account's last signable key, disabling the
account or deleting it, from its consequence read and the caller's `open_exposure` choice
(E27-S04 B3b1, #898; 22 `OpenExposure`, SR-E27-07, C-2.6).

An M13 module (C-3.1): it reads `ConsequenceRead`'s answer and asks the `Flattener` port, and
nothing else. `decide` is pure; `gate` adds the flatten `flatten_first` asks for. In 22's words:

- A failed read (`ExposureFailed`) fails closed with its own `503 exchange_unavailable` or
  `502 exchange_error`, whatever the choice: nothing is revoked, disabled or deleted.
- Unknown exposure (`ExposureUnknown`): a delete is always `409 exposure_unknown`; so is a
  `fix_key` remedy for every choice. A dead account (`leave_positions` remedy) is disabled, or
  its last key revoked, only with `leave_positions`, which proceeds with the stop-loss refusal
  lifted (`lifted`) and each signable key's `KeyProbeError` for the write-ahead record.
- A known, flat account (no open position, working order or running algo) proceeds, the
  choice ignored.
- A known account that is not flat: no choice is `409 open_exposure`; `leave_positions` while any
  open position has no native stop-loss is `409 open_exposure` (C-2.6); `flatten_first` asks the
  `Flattener`, and an account still not flat is `409 open_exposure`. The null flattener flattens
  nothing, so until E29/E39's lands `flatten_first` on a non-flat account is always refused.
- A revoke of a key that is not the account's last signable one is no exposure decision:
  `flatten_first` is a recorded no-op and the revoke proceeds (22 `OpenExposure`).

A delete takes only `flatten_first` (22 `deleteExchangeAccount`): its route answers any other
choice with `422` before this gate, which refuses `leave_positions` on a delete (`ValueError`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from candleviewer.accounts.consequences import AccountConsequences
from candleviewer.accounts.exposure import ExposureFailed, ExposureUnknown, Remedy
from candleviewer.accounts.flatten import Flattener

__all__ = [
    "Choice",
    "Flatten",
    "Operation",
    "Proceed",
    "Refuse",
    "decide",
    "gate",
]

type Operation = Literal["disable", "delete", "revoke"]
type Choice = Literal["leave_positions", "flatten_first"] | None
type Read = AccountConsequences | ExposureUnknown | ExposureFailed
type RefuseKind = Literal[
    "open_exposure", "exposure_unknown", "exchange_unavailable", "exchange_error"
]
#: Why an `open_exposure` refusal is given: no choice, a position without a native stop-loss
#: under `leave_positions`, or an account still not flat after `flatten_first`.
type OpenWhy = Literal["no_choice", "native_stop_missing", "still_not_flat"]

_NO_ERRORS: Final[tuple[tuple[UUID, str], ...]] = ()


@dataclass(frozen=True, slots=True)
class Proceed:
    """Carry the operation out. `lifted`: a dead account's stop-loss refusal was lifted, and
    `key_errors` holds each signable key's `KeyProbeError` for the record (22 Dead); `flattened`:
    the flattener reported the account flat first."""

    lifted: bool
    key_errors: tuple[tuple[UUID, str], ...]
    flattened: bool = False


@dataclass(frozen=True, slots=True)
class Refuse:
    """Refuse the operation and change nothing: `kind` is the problem code and `status` its HTTP
    status; `why` is set on `open_exposure`, `remedy` on `exposure_unknown`, and `ret_code` on
    `exchange_error` when the exchange sent one."""

    kind: RefuseKind
    status: Literal[409, 502, 503]
    why: OpenWhy | None = None
    remedy: Remedy | None = None
    ret_code: int | None = None


@dataclass(frozen=True, slots=True)
class Flatten:
    """`flatten_first` on a known account that is not flat: the `Flattener` decides (`gate`)."""

    account_id: UUID


def _open(why: OpenWhy) -> Refuse:
    return Refuse("open_exposure", 409, why=why)


def _flat(read: AccountConsequences) -> bool:
    return not read.open_positions and read.working_orders == 0 and read.running_algos == 0


def decide(
    op: Operation, outcome: Read | None, choice: Choice, *, last_signable: bool
) -> Proceed | Refuse | Flatten:
    """22 `OpenExposure` for `op` on the consequence read `outcome` (module docstring).
    `last_signable` says whether a revoke takes the account's last signable key; it is ignored
    for a disable and a delete, which switch every key off. `outcome` may be `None` only for a
    revoke of a key that is not the last signable one, which reads no exposure."""
    if op == "delete" and choice == "leave_positions":
        raise ValueError("a delete takes only flatten_first: its route answers 422 first")
    if op == "revoke" and not last_signable:
        return Proceed(False, _NO_ERRORS)
    if outcome is None:
        raise ValueError("an exposure decision needs the consequence read")
    if isinstance(outcome, ExposureFailed):
        if outcome.status == 503:
            return Refuse("exchange_unavailable", 503)
        return Refuse("exchange_error", 502, ret_code=outcome.ret_code)
    if isinstance(outcome, ExposureUnknown):
        if outcome.remedy == "leave_positions" and choice == "leave_positions":  # not a delete
            return Proceed(True, outcome.key_errors)
        return Refuse("exposure_unknown", 409, remedy=outcome.remedy)
    if _flat(outcome):
        return Proceed(False, _NO_ERRORS)
    if choice is None:
        return _open("no_choice")
    if choice == "leave_positions":
        if any(not p.native_stop_present for p in outcome.open_positions):
            return _open("native_stop_missing")
        return Proceed(False, _NO_ERRORS)
    return Flatten(outcome.account_id)


async def gate(
    op: Operation,
    outcome: Read | None,
    choice: Choice,
    *,
    last_signable: bool,
    flattener: Flattener,
    actor: UUID,
) -> Proceed | Refuse:
    """`decide`, then for `flatten_first` on a non-flat account the `flattener` as `actor`: a flat
    account proceeds (`flattened`), one still not flat is `409 open_exposure`."""
    decision = decide(op, outcome, choice, last_signable=last_signable)
    if not isinstance(decision, Flatten):
        return decision
    if await flattener.flatten(decision.account_id, actor=actor):
        return Proceed(False, _NO_ERRORS, flattened=True)
    return _open("still_not_flat")
