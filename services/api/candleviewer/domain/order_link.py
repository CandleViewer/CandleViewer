"""Shapes of a stored `order_link_id` (`docs/plan/24-internal-schemas.md` §8.3).

`OUR_ID` and `EXT_ID` are the two arms of the `orders.ord_link_fmt` CHECK
(`docs/plan/21-database-schema.md` §3.3.4), and `ext_key` derives the key an
adopted exchange order is stored under when its own id is empty or foreign.
They live here, beside the `OrderLinkId` primitive, because the exchange
adapter (M4) applies them and may not import the OMS (M14, CONSTITUTION.md §3).

Apply both patterns with `re.fullmatch`: `re.match` with `$` also accepts a
trailing newline, and Postgres `~` does not.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final

from .primitives import OrderLinkId

__all__ = ["EXT_ID", "OUR_ID", "ext_key"]

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
