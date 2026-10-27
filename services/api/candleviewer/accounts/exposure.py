"""The exposure read: an account's positions and working orders, read with its signable keys and
decided in `OpenExposure`'s order (E27-S04 B2a, #898; 22 `OpenExposure`, SR-E27-07).

One definition of the read, so `getAccountConsequences` and the revoke, disable and delete 409s
decide alike. An M13 module: it imports no M2, M4 or rules module (C-3.1, C-3.2); the composition
root (`exposure_wiring`) binds `ExposureReader` to the adapter, so no venue word appears here
(C-2.2). The decision, as 22 states it:

1. Only `active` and `rotating` keys are signable; any other key is never read. An account with no
   signable key is unknown and dead (`leave_positions`): "no key" is never "no exposure".
2. A key that reads both its positions and its open orders decides, whatever another key answers.
3. Else any failed read fails closed: `503` when any key answered `timeout`, `transport_error` or
   `vault_refused` (keys that fail both ways give the `503`), else `502` with the deciding key's
   exchange code when it sent one. The deciding key is the lowest key id of the deciding group.
4. Else any `ip_not_allowed` or `permission_denied` refusal: unknown, `fix_key`.
5. Else every key answered `auth_error`: unknown and dead, `leave_positions`.

A key's two calls combine by the same order, so a key is never judged dead on half its evidence.
`ExposureRead` starts every signable key at once (at most `MAX_KEYS` in flight, C-2.18) and
returns with the first key that reads both, cancelling the rest; only while no key has read does it
wait for the others, up to one deadline, and a key still pending then is a `timeout`. The deadline
is injected, so tests fire it by an event and never by wall time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.errors import AccountsError
from candleviewer.accounts.models import ApiKeyMetadata, ExchangeAccount, KeyStatus
from candleviewer.observability import spawn_child

__all__ = [
    "DEAD",
    "EXCHANGE_ERROR",
    "FIXABLE",
    "MAX_KEYS",
    "PROBE_ERRORS",
    "READ_DEADLINE_S",
    "REQUEST_BUDGET_S",
    "SIGNABLE",
    "UNAVAILABLE",
    "ExchangePosition",
    "ExposureFailed",
    "ExposureKnown",
    "ExposureOutcome",
    "ExposureRead",
    "ExposureReader",
    "ExposureUnknown",
    "KeyExposure",
    "KeyReadFailed",
    "combine",
    "decide",
]

#: The keys that read the exposure (21 §3.2.3a; the same set as `key_test`'s).
SIGNABLE: Final = frozenset({KeyStatus.ACTIVE, KeyStatus.ROTATING})
#: `KeyProbeError` (22), in four groups that partition it (a contract test pins them).
DEAD: Final = frozenset({"auth_error"})
FIXABLE: Final = frozenset({"ip_not_allowed", "permission_denied"})
UNAVAILABLE: Final = frozenset({"timeout", "transport_error", "vault_refused"})
EXCHANGE_ERROR: Final = frozenset(
    {"clock_drift", "rate_limited", "service_unavailable", "exchange_unknown"}
)
PROBE_ERRORS: Final = DEAD | FIXABLE | UNAVAILABLE | EXCHANGE_ERROR
#: SCR-129's budget for the consequence read; the exposure read gets what is left of it, at most
#: `READ_DEADLINE_S` (the adapter's own 5 s bounds never bind first).
REQUEST_BUDGET_S: Final = 1.0
READ_DEADLINE_S: Final = 0.9
#: Keys read at once (C-2.18): an account has one `active` key and at most one `rotating` one.
MAX_KEYS: Final = 8
#: A key's failure ranks by its group: a failed read first, then a fixable refusal, then dead.
_RANK: Final[Mapping[str, int]] = {
    **dict.fromkeys(UNAVAILABLE, 0),
    **dict.fromkeys(EXCHANGE_ERROR, 1),
    **dict.fromkeys(FIXABLE, 2),
    **dict.fromkeys(DEAD, 3),
}

Remedy = Literal["leave_positions", "fix_key"]
#: A failed read's answer by group, in 22's order: the `503` group decides before the `502` one.
_FAILED_READS: Final[tuple[tuple[frozenset[str], Literal[502, 503]], ...]] = (
    (UNAVAILABLE, 503),
    (EXCHANGE_ERROR, 502),
)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExchangePosition:
    """One position as the exchange reports it, in M13's words (22 `Position`)."""

    symbol: str
    position_idx: int
    side: Literal["long", "short", "flat"]
    size: Decimal
    avg_price: Decimal | None
    mark_price: Decimal | None
    liq_price: Decimal | None
    leverage: Decimal
    unrealised_pnl: Decimal
    take_profit: Decimal | None
    stop_loss: Decimal | None
    trailing_stop: Decimal | None
    updated_at_us: int

    @property
    def native_stop_present(self) -> bool:
        """The position carries an exchange stop-loss (C-2.6). A take-profit, a trailing stop or
        a Partial-mode stop order alone reads `False`, so the stop-loss refusal asks for
        `flatten_first` (fail-safe)."""
        return self.stop_loss is not None


@dataclass(frozen=True, slots=True)
class KeyExposure:
    """What one key read: the account's positions and the number of its working orders."""

    positions: tuple[ExchangePosition, ...]
    working_orders: int


class KeyReadFailed(AccountsError):
    """One key's read failed: its `KeyProbeError` word and, for an exchange error, the exchange's
    code when it sent one. Never exchange text (SR-E27-08)."""

    def __init__(self, probe_error: str, ret_code: int | None = None) -> None:
        if probe_error not in PROBE_ERRORS:
            raise ValueError("not a KeyProbeError")
        super().__init__(probe_error)
        self.probe_error, self.ret_code = probe_error, ret_code


@dataclass(frozen=True, slots=True)
class ExposureKnown:
    """A signable key read the exposure; `key_id` is the key that did."""

    key_id: UUID
    positions: tuple[ExchangePosition, ...]
    working_orders: int


@dataclass(frozen=True, slots=True)
class ExposureUnknown:
    """Every signable key was refused, or there is none: `409 exposure_unknown` with `remedy`.
    `key_errors` holds each signable key's word, by key id, for the Dead branch's record."""

    remedy: Remedy
    key_errors: tuple[tuple[UUID, str], ...]


@dataclass(frozen=True, slots=True)
class ExposureFailed:
    """No key read the exposure and one failed to: `503 exchange_unavailable` or
    `502 exchange_error` (`ret_code` on a 502 only, `None` when the exchange sent none)."""

    status: Literal[502, 503]
    probe_error: str
    ret_code: int | None
    key_errors: tuple[tuple[UUID, str], ...]


ExposureOutcome = ExposureKnown | ExposureUnknown | ExposureFailed


class ExposureReader(Protocol):
    """One key's read of an account's positions and open orders (bound in `exposure_wiring`).
    Raises `KeyReadFailed` for a failure the contract names; anything else is a defect."""

    async def read(self, account: ExchangeAccount, key_id: UUID) -> KeyExposure: ...


def _ranked(failure: KeyReadFailed) -> tuple[int, str, int]:
    code = -1 if failure.ret_code is None else failure.ret_code
    return _RANK[failure.probe_error], failure.probe_error, code


def combine(failures: Iterable[KeyReadFailed]) -> KeyReadFailed:
    """The failure that speaks for a key whose calls failed differently: a failed read before a
    fixable refusal before `auth_error`; ties by word, then by code (deterministic)."""
    ranked = sorted(failures, key=_ranked)
    if not ranked:
        raise ValueError("no failure to combine")
    return ranked[0]


def decide(outcomes: Mapping[UUID, KeyExposure | KeyReadFailed]) -> ExposureOutcome:
    """22's Order over each signable key's outcome; the first key that read, in `outcomes`'
    order, decides a read. `outcomes` must cover the registry's complete signable-key list: a
    caller that cannot read it answers 503 before calling; an empty mapping means the account has
    no signable key and is read as `leave_positions` (22)."""
    for key_id, got in outcomes.items():
        if isinstance(got, KeyExposure):
            return ExposureKnown(key_id, got.positions, got.working_orders)
    failed = sorted(
        (key_id, got) for key_id, got in outcomes.items() if isinstance(got, KeyReadFailed)
    )
    key_errors = tuple((key_id, got.probe_error) for key_id, got in failed)
    for group, status in _FAILED_READS:
        deciding = [got for _, got in failed if got.probe_error in group]
        if deciding:
            first = deciding[0]
            code = first.ret_code if status == 502 else None
            return ExposureFailed(status, first.probe_error, code, key_errors)
    if any(got.probe_error in FIXABLE for _, got in failed):
        return ExposureUnknown("fix_key", key_errors)
    return ExposureUnknown("leave_positions", key_errors)


class _Won(Exception):
    """A key read the exposure: the task group cancels the others."""


class _Watch:
    """The keys' progress for the parent: `settled` once a key won or every key is done."""

    def __init__(self, keys: int) -> None:
        self.remaining, self.won = keys, False
        self.settled = asyncio.Event()


class ExposureRead:
    """Reads an account's exposure with its signable keys, first key wins (22 Order (1)).

    `keys` must be the registry's complete signable-key list; a caller that cannot read it
    answers 503 before calling. An empty list means the account has no signable key and is read
    as `leave_positions` (22)."""

    def __init__(
        self,
        reader: ExposureReader,
        *,
        env: str,
        deadline_s: float = READ_DEADLINE_S,
        max_keys: int = MAX_KEYS,
        deadline: Callable[[float], AbstractAsyncContextManager[object]] = asyncio.timeout,
    ) -> None:
        if not deadline_s > 0 or max_keys < 1:
            raise ValueError("a positive deadline and at least one key at once")
        self._reader, self._env = reader, env
        self._deadline_s, self._max_keys, self._deadline = deadline_s, max_keys, deadline

    async def read(
        self,
        account: ExchangeAccount,
        keys: Sequence[ApiKeyMetadata],
        *,
        within_s: float | None = None,
    ) -> ExposureOutcome:
        """The exposure of `account` (of this process's environment, C-2.11) read with its
        signable `keys`, cut at `min(deadline_s, within_s)`. Cancellation propagates."""
        if account.env.value != self._env:
            raise ValueError("the account belongs to another environment")
        if any(key.exchange_account_id != account.id for key in keys):
            raise ValueError("a key of another account")
        signable = sorted({key.id for key in keys if key.status in SIGNABLE})
        outcomes: dict[UUID, KeyExposure | KeyReadFailed] = {}
        limit = self._deadline_s if within_s is None else min(self._deadline_s, within_s)
        if signable and limit > 0:
            if len(signable) > self._max_keys:
                _log().warning(
                    "exposure_read_many_keys", account_id=str(account.id), keys=len(signable)
                )
            gate = asyncio.Semaphore(self._max_keys)
            watch = _Watch(len(signable))
            task = asyncio.current_task()
            before = task.cancelling() if task is not None else 0
            try:
                async with self._deadline(limit), asyncio.TaskGroup() as group:
                    for key_id in signable:
                        one = self._one(account, key_id, gate, outcomes, watch)
                        spawn_child(group, one, name=f"exposure-read-{key_id}")
                    # The win is raised here, by the parent, not by a child: a child's error
                    # makes the group cancel its parent, which leaves a stale cancel count.
                    await watch.settled.wait()
                    if watch.won:
                        raise _Won
            except* _Won:
                pass
            except* TimeoutError:
                # also a reader's own TimeoutError: mapped to `timeout`, fail-closed (readers
                # raise only KeyReadFailed by Protocol)
                pass
            if task is not None and task.cancelling() > before:
                # a caller's cancel that coincides with a win is never swallowed
                raise asyncio.CancelledError
        for key_id in signable:
            outcomes.setdefault(key_id, KeyReadFailed("timeout"))
        return decide(outcomes)

    async def _one(
        self,
        account: ExchangeAccount,
        key_id: UUID,
        gate: asyncio.Semaphore,
        outcomes: dict[UUID, KeyExposure | KeyReadFailed],
        watch: _Watch,
    ) -> None:
        try:
            async with gate:
                try:
                    got = await self._reader.read(account, key_id)
                except KeyReadFailed as failed:
                    outcomes[key_id] = KeyReadFailed(failed.probe_error, failed.ret_code)
                    return
            outcomes[key_id] = got
            watch.won = True
        finally:
            watch.remaining -= 1
            if watch.won or watch.remaining == 0:
                watch.settled.set()
