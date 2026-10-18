"""Candidate-key verification inside M2 (E27-T03 slice 2b3, #836: SR-E27-01, decision 7).

Key import hands M2 the pasted key pair, and M2 keeps it in memory for that one request only. No
`pending` row exists before the check passes, so a refused key leaves neither a row nor a
ciphertext: 0024 takes DELETE away, so a destroyed row would keep the refused key's ciphertext.

- While the hold lasts, the pair signs the verification calls through `CandidateSigner`, the
  exchange adapter's view of it: `key_verify` messages for the candidate's own id only. M2 computes
  the MAC (C-2.7) and audits each signing write-ahead, as for a stored key's borrow (C-2.9), with
  the acting Owner as the actor (SR-E27-09). The adapter sends the calls to the host of the
  candidate's environment, which is M2's own (C-2.11).
- The caller's check returns the verified key-info snapshot on a pass and `None` on a refusal. On a
  pass M2 stores the pair `pending` with that snapshot on `store()`'s path, so the C-2.8 allow-list
  and deny-list apply once more, with the Owner as the actor (#2267 item 15) and the id M2 minted
  when the hold started, which the calls were signed under (#2336: no caller chooses it).
- A refusal, an error, a cancellation or the end of the hold's bound (`CANDIDATE_HOLD_S`) drops the
  pair: nothing is stored, the signer refuses from then on and the pair's wrappers are invalidated.

The pair never leaves M2: no return value, log, repr, exception or audit record carries it
(C-12.6). Only the key id goes back, for the request header, as for a stored key.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final, final
from uuid import UUID, uuid4

from candleviewer.observability.secret_type import Secret as Pasted
from candleviewer.secrets import _metrics as m
from candleviewer.secrets.broker import CredentialBroker, Purpose, _m2_only
from candleviewer.secrets.errors import CredentialUnavailable, SnapshotInvalid
from candleviewer.secrets.models import StoredCredential
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.signing import (
    RequestSignature,
    SigningMessage,
    check_message,
    message_sha256,
    request_signature,
)

#: The bound on one hold: the ticket's 12 s overall deadline for a key check (two 5 s calls).
CANDIDATE_HOLD_S: Final = 12.0
#: A pasted field: 1 to 128 visible ASCII characters, so no space or control character can reach
#: the request header the key id goes into. Nothing else about the venue's format is assumed.
_FIELD: Final = re.compile(r"[\x21-\x7e]{1,128}")
_PURPOSE: Final = "key_verify"
_BORROWED: Final = "security.credential_borrowed"

#: The caller's check: given the candidate's signer, the verified key-info snapshot on a pass and
#: `None` on a refusal.
CandidateCheck = Callable[["CandidateSigner"], Awaitable[Mapping[str, Any] | None]]
_SignFn = Callable[[UUID, SigningMessage, Purpose], Awaitable[RequestSignature]]


def _held(value: object) -> Secret[str]:
    """M2's own wrapper around one pasted field, or a refusal that echoes nothing."""
    if not isinstance(value, Pasted) or not isinstance(value.reveal(), str):
        raise CredentialUnavailable("credential_shape_invalid")
    if _FIELD.fullmatch(value.reveal()) is None:
        raise CredentialUnavailable("credential_shape_invalid")
    return Secret(value.reveal())


@final
class CandidateSigner:
    """One candidate's signing capability, for the exchange adapter. While the hold lasts, M2 MACs
    a `key_verify` message for this candidate's own id with the pasted pair and returns the key id
    and the hex MAC, never the secret (C-2.7). It holds a closure, its environment and its id."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("__env", "__key_id", "__sign")

    def __init__(self, sign: _SignFn, env: str, key_id: UUID) -> None:
        self.__sign, self.__env, self.__key_id = sign, env, key_id

    @property
    def env(self) -> str:
        """M2's environment: the adapter sends the candidate's calls to its host only (C-2.11)."""
        return self.__env

    @property
    def key_id(self) -> UUID:
        """The candidate's id: it signs for this id only, and a pass stores it under this id."""
        return self.__key_id

    async def sign(
        self, key_id: UUID, message: SigningMessage, *, purpose: Purpose
    ) -> RequestSignature:
        return await self.__sign(key_id, message, purpose)


@final
class CandidateKeys:
    """Key import's M2 capability (#836), minted once in `admin.wiring`: verify a pasted key pair
    inside M2 and store it only after the check passes. It holds a closure only (C-3.2)."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("__run",)

    def __init__(self, run: Callable[..., Awaitable[StoredCredential | None]]) -> None:
        self.__run = run

    async def store_if_verified(
        self,
        env: str,
        account_id: UUID,
        label: str,
        api_key: Pasted[str],
        api_secret: Pasted[str],
        check: CandidateCheck,
        *,
        actor_user_id: str,
        actor_role: str,
    ) -> StoredCredential | None:
        """Hold the pair for `check`; store it only if `check` returns a snapshot. Returns the
        stored metadata on a pass and `None` on a refusal. Anything else stores nothing and
        raises: the check's own error, `credential_shape_invalid`, `environment_mismatch`,
        `candidate_timeout` at the hold's bound, or a `store()` refusal (C-2.8)."""
        return await self.__run(
            env, account_id, label, api_key, api_secret, check, actor_user_id, actor_role
        )


async def hold_candidate(
    broker: CredentialBroker,
    caller: str,
    hold_s: float,
    env: str,
    account_id: UUID,
    label: str,
    api_key: object,
    api_secret: object,
    check: CandidateCheck,
    actor_user_id: str,
    actor_role: str,
) -> StoredCredential | None:
    """The one hold behind `CandidateKeys.store_if_verified` (module docstring)."""
    if not actor_role or not isinstance(actor_user_id, str) or not actor_user_id:
        raise ValueError("key import needs the acting user and role (SR-E27-09)")
    UUID(actor_user_id)  # the audit log's actor column is a user id
    if env != broker._env:
        raise CredentialUnavailable("environment_mismatch")
    pair = (_held(api_key), _held(api_secret))
    key_id, live = uuid4(), [True]
    fields = {
        "key_id": str(key_id),
        "exchange_account_id": str(account_id),
        "env": env,
        "actor_kind": "user",
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "caller_module": caller,
        "purpose": _PURPOSE,
        "candidate": "true",
    }

    async def sign(kid: UUID, message: SigningMessage, purpose: Purpose) -> RequestSignature:
        parts, result = check_message(message), "error"
        try:
            if not live[0] or kid != key_id or purpose != _PURPOSE:
                raise CredentialUnavailable("candidate_unavailable")
            record = {**fields, "message_sha256": message_sha256(parts)}
            await broker._audit(_BORROWED, record)  # write-ahead (C-2.9)
            try:
                if not live[0]:  # the hold ended while the record was written
                    raise CredentialUnavailable("candidate_unavailable")
                signed = request_signature(*pair, parts)  # the stored key's wrapper, frames cleared
            except BaseException as exc:
                await broker._sign_failed(record, exc)  # closes the record as a stored key's does
                raise
            result = "ok"
            return signed
        finally:  # counted as a stored key's borrow is (`cv_credential_borrow_total`)
            m.credential_candidate_sign_total.labels(stage=caller, result=result).inc()

    try:
        try:
            async with asyncio.timeout(hold_s) as bound:
                snapshot = await check(CandidateSigner(sign, env, key_id))
        except TimeoutError:
            if bound.expired():
                raise CredentialUnavailable("candidate_timeout") from None
            raise
        finally:
            live[0] = False  # the check is over: nothing is signed from here on
        if bound.expired():  # a check that swallowed the bound's cancellation: refused all the same
            raise CredentialUnavailable("candidate_timeout")
        if snapshot is None:
            return None
        if not isinstance(snapshot, Mapping):
            raise SnapshotInvalid("snapshot_invalid")
        actor = ("user", actor_role, actor_user_id)
        return await broker._seal_new(key_id, env, account_id, label, *pair, snapshot, actor)
    finally:
        for held in pair:
            held.invalidate()
