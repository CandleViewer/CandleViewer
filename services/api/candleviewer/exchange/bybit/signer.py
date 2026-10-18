"""Bybit v5 REST request signing through the M2 signing capability (C-2.7, #2339).

This module owns the venue's string-to-sign (`docs/plan/24-internal-schemas.md` §14.3 "Auth
(REST)"): `timestamp + api_key + recv_window + payload`, where `payload` is the query string for
`GET` and the raw JSON body for `POST`. It never holds the API secret. It sends the message to M2
with `KEY_ID_SLOT` where the key goes; M2 computes the lowercase hex HMAC-SHA256 and returns it
with the key id for the `X-BAPI-API-KEY` header.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from candleviewer.secrets import KEY_ID_SLOT

if TYPE_CHECKING:
    from candleviewer.secrets import Purpose, SigningCapability


@dataclass(frozen=True, slots=True)
class BybitSignature:
    """Header values for one signed request. `repr` renders neither value (#1895)."""

    api_key: str = field(repr=False)
    signature: str = field(repr=False)


class BybitSigner:
    """Signs requests for one credential through an M2 capability: a stored key (`api_keys.id`)
    through the borrower, or a candidate key M2 holds for one import (#836) through its signer.

    Holds the capability, the credential id and the borrow purpose, never key material, so
    `repr` and tracebacks cannot show a key or a secret."""

    __slots__ = ("_credential_id", "_credentials", "_purpose")

    def __init__(
        self,
        credentials: SigningCapability,
        credential_id: UUID,
        *,
        purpose: Purpose = "sign_rest",
    ) -> None:
        self._credentials = credentials
        self._credential_id = credential_id
        self._purpose: Purpose = purpose

    async def sign(self, *, timestamp_ms: int, recv_window_ms: int, payload: str) -> BybitSignature:
        """Sign one request. `payload` must be the exact bytes sent: the query string (no
        leading `?`) for `GET`/`DELETE`, the JSON body string for `POST`. M2 errors propagate
        unchanged (`CredentialUnavailable`, `KekUnavailable`, and `WithdrawPermissionRejected` or
        its subclass `SnapshotInvalid` when the borrow's C-2.8 re-check refuses the stored row,
        SR-E27-14): a request is never sent unsigned.
        """
        message = (
            str(timestamp_ms).encode(),
            KEY_ID_SLOT,
            str(recv_window_ms).encode(),
            payload.encode("utf-8"),
        )
        signed = await self._credentials.sign(self._credential_id, message, purpose=self._purpose)
        # The key id M2 returns is the X-BAPI-API-KEY header value (the one reviewed reveal).
        return BybitSignature(api_key=signed.api_key.reveal(), signature=signed.signature)

    def __repr__(self) -> str:
        return f"BybitSigner(credential_id={self._credential_id}, purpose={self._purpose})"
