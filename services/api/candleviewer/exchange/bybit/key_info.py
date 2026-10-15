"""Key-verification replies (E27-T03, #836): key info, the signed probe and refusal classes.

`GET /v5/user/query-api` (key info) and the signed no-op probe `GET /v5/account/wallet-balance`
are parsed into the venue-neutral facts the M13 pipeline judges (`accounts.verification`). The
facts satisfy its `KeyFacts` and `ProbeFacts` protocols structurally, so neither module imports
the other (C-3.1). Field semantics follow the E27 threat model §5 item 3: write access from
`readOnly`, UTA from `uta` (`unified` is deprecated). The reply's own key id and secret fields are
never read, and a malformed reply leaves as `UnknownStateError` with no cause or context, so no
traceback carries reply content (C-2.7, SR-E27-08). Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from candleviewer.exchange.base.errors import AuthError, ExchangeError, UnknownStateError

KEY_INFO_PATH: Final = "/v5/user/query-api"
PROBE_PATH: Final = "/v5/account/wallet-balance"

#: Refusals that are a verdict about the key: code -> (M13 `Refusal` value, the error classes the
#: REST client's taxonomy may give that code). 33004 (key expired) is not in `mapping.py` yet, so
#: it arrives as `UnknownStateError`. Everything else, a refused signature (10004) and clock
#: drift (10002) included, is inconclusive (SR-E27-18).
_VERDICTS: Final[Mapping[int, tuple[str, tuple[type[ExchangeError], ...]]]] = {
    10003: ("unknown_key", (AuthError,)),
    10005: ("permission_denied", (AuthError,)),
    10010: ("ip_not_allowed", (AuthError,)),
    33004: ("key_expired", (AuthError, UnknownStateError)),
}
#: The verdict vocabulary. M13's `Refusal` holds exactly these values (a parity test pins it).
VERDICT_REASONS: Final = frozenset(reason for reason, _ in _VERDICTS.values())
#: Plausible exchange clock (ms): 2020-01-01 to 2100-01-01.
_MS_MIN, _MS_MAX = 1_577_836_800_000, 4_102_444_800_000


@dataclass(frozen=True, slots=True)
class ApiKeyFacts:
    uid: str
    unified: bool
    read_only: bool
    permissions: Mapping[str, object]
    ip_whitelist: tuple[str, ...]
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProbeFacts:
    server_time_ms: int
    sent_at_ms: int
    received_at_ms: int


class _KeyInfo(BaseModel):
    """The `result` fields the gate reads (SR-030a); every other field is ignored, unread."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)

    userID: str
    readOnly: Literal[0, 1]
    uta: Literal[0, 1] = 0
    permissions: dict[str, Any]
    ips: list[str] = []
    expiredAt: datetime | None = None

    @field_validator("userID", mode="before")
    @classmethod
    def _uid(cls, value: object) -> str:
        text = str(value) if type(value) is int else value
        if not isinstance(text, str) or not (text.isascii() and text.isdigit()):
            raise ValueError("userID must be ASCII digits")
        return text

    @field_validator("expiredAt", mode="before")
    @classmethod
    def _expiry(cls, value: object) -> datetime | None:
        if value is None or value == "":
            return None
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
        if parsed is None or parsed.utcoffset() is None:
            raise ValueError("expiredAt must be a timezone-aware ISO 8601 time")
        return parsed


def parse_key_info(body: Mapping[str, Any]) -> ApiKeyFacts:
    """Key facts from a key-info reply body; a malformed one is `UnknownStateError`."""
    try:
        info: _KeyInfo | None = _KeyInfo.model_validate(body["result"])
    except (KeyError, TypeError, ValueError):
        info = None
    if info is None:
        # Raised outside the handler, so not even `__context__` holds the validation error,
        # whose input is the reply itself.
        raise UnknownStateError("malformed key-info reply")
    return ApiKeyFacts(
        uid=info.userID,
        unified=info.uta == 1,
        read_only=info.readOnly == 1,
        permissions=info.permissions,
        ip_whitelist=tuple(info.ips),
        expires_at=info.expiredAt,
    )


def parse_probe(body: Mapping[str, Any], *, sent_at_ms: int, received_at_ms: int) -> ProbeFacts:
    """The probe's success reply carries the exchange's epoch-ms clock (`time`); with the local
    send and receive times it gives the clock offset."""
    server = body.get("time")
    if body.get("retCode") != 0 or type(server) is not int or not _MS_MIN <= server <= _MS_MAX:
        raise UnknownStateError("malformed probe reply")
    return ProbeFacts(server, sent_at_ms, received_at_ms)


def refusal(error: ExchangeError) -> tuple[str, int] | None:
    """`(reason, code)` when a signed call's refusal is a verdict about the key, else `None`."""
    code = error.exchange_ret_code
    if code is None or code not in _VERDICTS:
        return None
    reason, classes = _VERDICTS[code]
    return (reason, code) if isinstance(error, classes) else None
