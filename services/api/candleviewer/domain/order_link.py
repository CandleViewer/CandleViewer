"""Shapes of a stored `order_link_id` (`docs/plan/24-internal-schemas.md` §8.3).

`OUR_ID` and `EXT_ID` are the two arms of the `orders.ord_link_fmt` CHECK
(`docs/plan/21-database-schema.md` §3.3.4), and `ext_key` derives the key an
adopted exchange order is stored under when its own id is empty or foreign.
The environment letters, `account_tag` (`acct4`) and `link_owner` let the
adapter check that a row it reads under one of our ids belongs to the account
and environment of its call (SR-E29-02, #2877 ruling R12).
They live here, beside the `OrderLinkId` primitive, because the exchange
adapter (M4) applies them and may not import the OMS (M14, CONSTITUTION.md §3).

Apply both patterns with `re.fullmatch`: `re.match` with `$` also accepts a
trailing newline, and Postgres `~` does not.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal, cast

from .primitives import AccountId, Environment, OrderLinkId

__all__ = [
    "BASE62",
    "ENV_LETTER",
    "EXT_ID",
    "OUR_ID",
    "EnvLetter",
    "account_tag",
    "base62",
    "ext_key",
    "link_owner",
]

EnvLetter = Literal["l", "d", "t", "p"]
"""The `{env}` letter of an id: live, demo, testnet, or `p` for paper (§8.3)."""

BASE62: Final = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
"""Base62 digits in value order."""

ENV_LETTER: Final[Mapping[Environment, EnvLetter]] = MappingProxyType(
    {"live": "l", "demo": "d", "testnet": "t"}
)
"""The letter of an exchange order of each environment; paper's `p` is never on an exchange."""

OUR_ID: Final = re.compile(
    r"^cv[ldtp]-[0-7][0-9A-Za-z]{21}-[0-9A-Za-z]{4}-[0-9A-Za-z]{2}(en|sl|tp|sc|fl|ac)$"
)
"""An id the §8.3 generator produces."""

EXT_ID: Final = re.compile(r"^ext-[0-9a-f]{32}$")
"""The key of an adopted exchange order; never sent to the exchange."""

_CANONICAL_UUID: Final = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)


def ext_key(exchange_order_id: str) -> OrderLinkId:
    """`ext-` plus 32 lowercase hex digits naming one exchange order.

    A canonical 8-4-4-4-12 UUID gives its own digits, lowercased, without the
    hyphens; anything else gives the first 32 hex digits of the SHA-256 of its
    UTF-8 bytes. The key depends on the exchange order id alone, so one
    exchange order always maps to the same key.

    Total over `str`. Real exchange order ids are ASCII, but a decoded payload can carry a lone
    surrogate (a JSON escape such as `\\ud800`), which strict UTF-8 refuses. It encodes as
    its own three bytes (`errors="surrogatepass"`), so the adapter's id normalisation
    (§14.2 rule 11) never raises on it, and no two ids share a key by way of a replacement
    character. Text without a surrogate encodes exactly as it always did.
    """
    if _CANONICAL_UUID.fullmatch(exchange_order_id) is not None:
        return "ext-" + exchange_order_id.lower().replace("-", "")
    digest = hashlib.sha256(exchange_order_id.encode("utf-8", errors="surrogatepass"))
    return "ext-" + digest.hexdigest()[:32]


def base62(value: int, width: int) -> str:
    """`value` in base62, left-padded with `0` to `width` digits. Total over the non-negative
    values and widths it is meant for: anything else is refused (`ValueError`), never looped on."""
    if value < 0 or width < 0:
        raise ValueError("base62 takes a non-negative value and width")
    digits = ""
    while value:
        value, digit = divmod(value, 62)
        digits = BASE62[digit] + digits
    return digits.rjust(width, "0")


def account_tag(account_id: AccountId) -> str:
    """`acct4`: crc32 of the lowercase account id, mod 62^4. A diagnostic tag only;
    uniqueness comes from `group22`, `seq2` and the collision check."""
    return base62(zlib.crc32(str(account_id).lower().encode("ascii")) % 62**4, 4)


def link_owner(link: str) -> tuple[EnvLetter, str] | None:
    """The `(env letter, acct4)` an `OUR_ID` names, or `None` for any other id (an `ext-`
    key or a foreign id names no account of ours)."""
    if OUR_ID.fullmatch(link) is None:
        return None
    return cast(EnvLetter, link[2]), link[27:31]
