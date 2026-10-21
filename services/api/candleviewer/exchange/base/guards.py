"""The neutral refusals of every `TradingPort` (24 §14.2 rules 11 and 12; G-8, #2877).

Each runs before anything is sent, and each refuses with `ValueError`: the exchange adapter and
`FakeTradingPort` call the same checks, so the in-memory port refuses exactly what the real one
does. No exchange vocabulary: the ids are this product's (`domain.order_link`).
"""

from __future__ import annotations

from uuid import UUID

from candleviewer.domain.order_link import (
    ENV_LETTER,
    EXT_ID,
    OUR_ID,
    account_tag,
    ext_key,
    link_owner,
)
from candleviewer.domain.primitives import OrderLinkId, TsUs

from .models import AccountRef

__all__ = ["check_create_id", "check_exit_ids", "check_key_ref", "check_lookup_id", "check_window"]


def check_key_ref(account: AccountRef) -> UUID:
    """Ruling R13: `key_ref` is the canonical form of the account's active key's `api_keys.id`
    (lower-case 8-4-4-4-12), its id returned; any other shape is refused with `ValueError`
    before anything is taken, signed or sent, by every call that names the account."""
    try:
        parsed = UUID(account.key_ref)
    except (ValueError, AttributeError, TypeError):
        parsed = None
    if parsed is None or str(parsed) != account.key_ref:
        raise ValueError("key_ref is not an api_keys id")
    return parsed


def check_create_id(account: AccountRef, link: str) -> None:
    """A create carries an id the generator made for this account and its environment: an
    `ext-` key or a foreign id never goes on the wire, and a row the reads would drop as
    another account's is never created (24 §14.2 rules 11 and 12). `ValueError` otherwise."""
    owner = link_owner(link)
    if owner is None:
        raise ValueError("a create carries a generated order_link_id")
    letter, tag = owner
    if letter != ENV_LETTER[account.environment] or tag != account_tag(account.account_id):
        raise ValueError("the order_link_id belongs to another account or environment")


def check_exit_ids(link: str | None, exchange_order_id: str | None) -> None:
    """An amend or a cancel names its order: an `ext-` key only by `exchange_order_id`, which
    must then be present and be the order the key derives from (24 §14.2 rule 11, §8.3).
    `ValueError` otherwise."""
    if exchange_order_id:
        if link is not None and EXT_ID.fullmatch(link) and link != ext_key(exchange_order_id):
            raise ValueError("the ext- key names another exchange order")
        return
    if link is None or EXT_ID.fullmatch(link) is not None or OUR_ID.fullmatch(link) is None:
        raise ValueError("this order can only be named by its exchange_order_id")


def check_lookup_id(link: OrderLinkId | None) -> None:
    """A lookup by id names a generated id: an `ext-` key is looked up by `exchange_order_id`
    (24 §8.5), and no other shape is ever on a row (§14.2 rule 11)."""
    if link is not None and OUR_ID.fullmatch(link) is None:
        raise ValueError("an order_link_id filter is a generated id; look ext- keys up by orderId")


def check_window(start: TsUs | None, end: TsUs | None) -> None:
    if start is not None and end is not None and start > end:
        raise ValueError("start is after end")
