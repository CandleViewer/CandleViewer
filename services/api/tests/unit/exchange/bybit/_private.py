"""Shared pieces of the G-8b private-stream tests (#3963): the docs-transcribed frames of the corpus
(`ws/private-*.jsonl`, ruling 11) and the rows tests derive from them. A derived row is a test
input built on a transcribed shape, never a venue fact: the documented order sample is an
option's and the wallet sample holds a BTC row, so a linear USDT row is derived in-test. No
network (C-13.5).
"""

from __future__ import annotations

import json
from typing import Any

from tests._corpus import frames

#: The transcriptions, by the name after `ws/private-`.
NAMES = (
    "auth-ok",
    "subscribe-ok",
    "pong",
    "order",
    "execution",
    "execution-fast",
    "position",
    "wallet",
)


def raw(name: str) -> str:
    """The one documented frame of `ws/private-<name>.jsonl`, as transcribed."""
    [frame] = frames(f"ws/private-{name}.jsonl")
    return frame


def frame(name: str) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(raw(name))
    return decoded


def row(name: str) -> dict[str, Any]:
    """The documented push's only row."""
    [first] = frame(name)["data"]
    assert isinstance(first, dict)
    return dict(first)


def linear_order(**fields: Any) -> dict[str, Any]:
    """The documented order row as a linear USDT one: its category, a USDT symbol and the
    remaining quantity a filled order states (the option sample leaves it empty)."""
    base = row("order") | {"category": "linear", "symbol": "BTCUSDT", "leavesQty": "0"}
    return base | fields


def usdt_wallet(**fields: Any) -> dict[str, Any]:
    """The documented unified wallet with its coin row as USDT's."""
    account = row("wallet")
    [coin] = account["coin"]
    return account | {"coin": [coin | {"coin": "USDT"}]} | fields


def push(topic: str, *rows: dict[str, Any], created: int | None = None) -> str:
    """A push frame of `topic` holding `rows`, compact as the venue sends it; its creation time
    is the documented order push's unless given."""
    when = frame("order")["creationTime"] if created is None else created
    body = {"topic": topic, "creationTime": when, "data": list(rows)}
    return json.dumps(body, separators=(",", ":"))


def reply(name: str, **fields: Any) -> str:
    """A documented reply with `fields` changed (a refused `auth` is `success` false: no page
    shows one, so it is derived)."""
    return json.dumps(frame(name) | fields, separators=(",", ":"))
