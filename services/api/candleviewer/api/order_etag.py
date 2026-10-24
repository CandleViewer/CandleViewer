"""The order routes' `ETag` (E29-T04 slice 4, ruling Q5; 22 `OrderETag` and `IfMatch`).

`order_etag(order_id, seq)` is the strong tag `"<orderId>:<seq>"` of an order at a version, the
facade's `version()`: the `event_seq` of its last committed lifecycle row, which a final order, or
one in a resync window, does not have. `expected_seq(if_match, order_id)` reads `amendOrder`'s
`If-Match`: None when it is absent, so the amend applies to the order as it stands (last write
wins, the S4-A decision D3); the seq it names when it is one strong tag of this order, written as
`order_etag` writes it; else `NO_VERSION`, which no version equals: `*`, a list, a weak or
malformed tag and another order's tag alike, so the exit service answers it `412 version_conflict`
where it compares the version, after the scope (404), the state (422) and the body (400), with
nothing sent. A plain module with no router, as `api/order_acceptance.py` is.
"""

from __future__ import annotations

import re
from typing import Final
from uuid import UUID

__all__ = ["NO_VERSION", "expected_seq", "order_etag"]

#: The version an `If-Match` naming no version of the order expects: no `event_seq` is negative.
NO_VERSION: Final = -1
#: One strong tag, the order's id as `str(UUID)` writes it and a bigint's digits, no leading zero.
_TAG: Final = re.compile(
    r'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):(0|[1-9][0-9]{0,18})"'
)


def order_etag(order_id: UUID, seq: int) -> str:
    """The strong tag of `order_id` at version `seq` (22 `OrderETag`)."""
    if isinstance(seq, bool) or seq < 0:
        raise ValueError("a version is an event_seq, an int of 0 or more")
    return f'"{order_id}:{seq}"'


def expected_seq(if_match: str | None, order_id: UUID) -> int | None:
    """The version an amend's `If-Match` expects (module docstring)."""
    if if_match is None:
        return None
    tag = _TAG.fullmatch(if_match.strip(" \t"))
    if tag is None or tag[1] != str(order_id):
        return NO_VERSION
    return int(tag[2])
