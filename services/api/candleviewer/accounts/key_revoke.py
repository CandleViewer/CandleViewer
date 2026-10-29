"""A stored key's local revoke (E27-S04 B3d, #898; 22 `revokeApiKey`, 24 §8.4.1, §14.2 rule 13 and
§15.5).

An M13 module (C-3.1): the store is the accounts repository, and M2's destroyer, the key standing,
the WS revoke, the rule disarm and the private-stream close are ports the composition root binds;
it never imports `secrets` (C-3.2). The route decides RBAC, the `422`, the `404`, the step-up, the
repeat and the exposure, under the account's lock (`AccountLocks`, shared with the delete), and
writes the records; this module carries the revoke out, in ruling item 4's order (hold, WS revoke,
disarm, then the bounded close), so an overrun leaves only the close pending:

- **First revoke** (`revoke`): the key is destroyed through M2 (fenced, recorded, revoked), then
  the standing's revoke hold leaves it out of the account's keys; when no other key of the account
  is signable, the WS revoke (`key_revoked`) and the rule disarm (`key_revoked`) follow; then the
  close of its private streams (`key_revoked`, permanent), bounded by the adapter at 2 s. An
  overrun (`PrivateStreamCloseOverran`) is raised for the route to answer, never caught here.
- **Repeat** (`complete`: the key reads `revoked`): nothing is destroyed or recorded ahead again;
  the effects still pending are done once more, each idempotent, and the close is awaited again,
  joining one in flight.

Either way the route then writes the completion record `api_key.revoked`, keyed by the key's id
(`KEYED_ACTIONS`), so it lands once whatever the number of calls (R7). Its payload (`Completion`)
is the first call's, kept per key in a bounded memo (C-2.18) so a repeat after an overrun writes
the same; a repeat whose memo is gone (a restart) derives it from the same inputs: `flattened` is
false (the null flattener acts on nothing), `reason` is `other_key_signable` for a `flatten_first`
while another key of the account is signable, and `accounts_closed` names the key's account (one
key serves one account; the close returns a subset of it).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from candleviewer.accounts.lifecycle import (
    Disarmer,
    KeyDestroyerPort,
    Standings,
    Streams,
    Subscriptions,
    destroy_key,
)
from candleviewer.accounts.locks import AccountLocks
from candleviewer.accounts.models import ApiKeyMetadata, KeyStatus

__all__ = ["MEMO_KEYS", "Completion", "KeyRevoke", "completion", "last_signable"]

#: How many keys' completion payloads the memo keeps, oldest dropped first (C-2.18).
MEMO_KEYS: Final = 1024
_SIGNABLE: Final = frozenset({KeyStatus.ACTIVE, KeyStatus.ROTATING})
type Choice = Literal["leave_positions", "flatten_first"] | None


@dataclass(frozen=True, slots=True)
class Completion:
    """`api_key.revoked`'s payload (22 `revokeApiKey`, Audit): whether the flatten acted, the
    no-op's reason, and the accounts whose streams on the key the close covers."""

    flattened: bool
    reason: Literal["other_key_signable"] | None
    accounts_closed: tuple[UUID, ...]

    def state(self, account_id: UUID) -> dict[str, object]:
        """The record's `after_state`."""
        shown: dict[str, object] = {
            "exchange_account_id": str(account_id),
            "flattened": self.flattened,
            "accounts_closed": [str(a) for a in self.accounts_closed],
        }
        if self.reason is not None:
            shown["reason"] = self.reason
        return shown


def last_signable(keys: Iterable[ApiKeyMetadata], key_id: UUID) -> bool:
    """Whether revoking `key_id` leaves the account with no signable key: no other key of it is
    `active` or `rotating` (22: a `rotating` key still signs and streams)."""
    return not any(k.id != key_id and k.status in _SIGNABLE for k in keys)


def completion(
    account_id: UUID, *, choice: Choice, last: bool, flattened: bool = False
) -> Completion:
    """The payload from the stable inputs (module docstring)."""
    noop = choice == "flatten_first" and not last
    return Completion(flattened, "other_key_signable" if noop else None, (account_id,))


class KeyRevoke:
    """Carries a key's revoke out over its ports (module docstring). `locks` is the delete's
    table, so a revoke and a delete of one account never interleave."""

    def __init__(
        self,
        standings: Standings,
        subscriptions: Subscriptions,
        disarmer: Disarmer,
        streams: Streams,
        destroyer: KeyDestroyerPort,
        *,
        locks: AccountLocks,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        memo_keys: int = MEMO_KEYS,
    ) -> None:
        self._standings, self._subscriptions, self._disarmer = standings, subscriptions, disarmer
        self._streams, self._destroyer, self._clock = streams, destroyer, clock
        self.locks, self._memo_keys = locks, memo_keys
        self._memo: OrderedDict[UUID, Completion] = OrderedDict()

    async def revoke(
        self,
        account_id: UUID,
        key_id: UUID,
        *,
        last: bool,
        payload: Completion,
        actor: UUID,
        role: str,
    ) -> Completion:
        """The first revoke, its ahead record written: destroy, hold, then (the last signable
        key) the WS revoke and the disarm, then the bounded close. `KeyDestroyFailedError` when M2
        did not destroy it (nothing after ran); an overrun is raised once the payload is kept."""
        await destroy_key(self._destroyer, account_id, key_id, actor, role)
        self._remember(key_id, payload)
        await self._effects(account_id, key_id, last=last, actor=actor, role=role)
        return payload

    async def complete(
        self,
        account_id: UUID,
        key_id: UUID,
        *,
        keys: Iterable[ApiKeyMetadata],
        choice: Choice,
        actor: UUID,
        role: str,
    ) -> Completion:
        """A repeat (the key reads `revoked`): the pending effects again, the close awaited again;
        the first call's payload, or the one derived from the same inputs once it is gone.
        `last` is read from the key set now: a non-last key repeated after the account's other
        keys were revoked reads as last and re-runs the WS revoke and the disarm, both idempotent
        and both already due for a keyless account (round-1 Minor)."""
        last = last_signable(keys, key_id)
        payload = self._memo.get(key_id) or completion(account_id, choice=choice, last=last)
        await self._effects(account_id, key_id, last=last, actor=actor, role=role)
        return payload

    async def _effects(
        self, account_id: UUID, key_id: UUID, *, last: bool, actor: UUID, role: str
    ) -> None:
        self._standings.revoke(account_id, key_id)
        if last:  # the account is keyless: its subscriptions end and its rules stop
            await self._subscriptions.account_revoked(account_id, "key_revoked")
            await self._disarmer.disarm(
                account_id, lifecycle="key_revoked", actor=actor, role=role, at=self._clock()
            )
        await self._streams.close_private_streams(str(key_id), reason="key_revoked")

    def _remember(self, key_id: UUID, payload: Completion) -> None:
        self._memo[key_id] = payload
        self._memo.move_to_end(key_id)
        while len(self._memo) > self._memo_keys:
            self._memo.popitem(last=False)
