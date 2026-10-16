"""The `order_link_id` value object: generator and parser (E29-T02, #846).

`{prefix}{env}-{group22}-{acct4}-{seq2}{suffix}`, 36 chars, as defined by
`docs/plan/24-internal-schemas.md` §8.3, the owner of the format. Pure and
total: no I/O, no clock, no process-wide setting; the collision check is in
`order_link_allocator`.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field, replace
from typing import Final, Literal, cast
from uuid import UUID

from candleviewer.domain.order_link import OUR_ID
from candleviewer.domain.primitives import (
    AccountId,
    Environment,
    ExecutionMode,
    GroupId,
    OrderLinkId,
)

from .errors import InvalidOrderLinkId, UnsupportedExecutionMode

__all__ = [
    "BASE62",
    "PURPOSE_TAG",
    "SEQ_MAX",
    "EnvLetter",
    "OrderLinkIdParts",
    "OrderPurpose",
    "PurposeTag",
    "account_tag",
    "env_letter",
]

OrderPurpose = Literal[
    "entry", "stop_loss", "take_profit", "scale_in", "scale_out", "flatten", "reverse", "algo_child"
]
"""`OrderIntent.purpose` (§8.1)."""

EnvLetter = Literal["l", "d", "t", "p"]
PurposeTag = Literal["en", "sl", "tp", "sc", "fl", "ac"]

BASE62: Final = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
"""Base62 digits in value order."""

SEQ_MAX: Final = 62**2 - 1
"""The largest `seq2`, 3843: two base62 digits."""

PURPOSE_TAG: Final[dict[OrderPurpose, PurposeTag]] = {
    "entry": "en",
    "reverse": "en",  # a reverse opens the new side, so it carries the native SL (C-2.6)
    "stop_loss": "sl",
    "take_profit": "tp",
    "scale_in": "sc",
    "scale_out": "sc",
    "flatten": "fl",
    "algo_child": "ac",
}

_ENV_LETTER: Final[dict[Environment, EnvLetter]] = {"live": "l", "demo": "d", "testnet": "t"}
_DIGIT: Final = {char: value for value, char in enumerate(BASE62)}


def _base62(value: int, width: int) -> str:
    digits = ""
    while value:
        value, digit = divmod(value, 62)
        digits = BASE62[digit] + digits
    return digits.rjust(width, "0")


def _decode(text: str) -> int:
    value = 0
    for char in text:
        value = value * 62 + _DIGIT[char]
    return value


def env_letter(mode: ExecutionMode, environment: Environment) -> EnvLetter:
    """The order's own letter: `exchange` takes the account's environment, `paper` takes
    `p`, and `replay` has none, so it fails closed (#846 Q4)."""
    if mode == "exchange":
        return _ENV_LETTER[environment]
    if mode == "paper":
        return "p"
    raise UnsupportedExecutionMode(f"execution mode {mode!r} has no order_link_id letter")


def account_tag(account_id: AccountId) -> str:
    """`acct4`: crc32 of the lowercase account id, mod 62^4. A diagnostic tag only;
    uniqueness comes from `group22`, `seq2` and the collision check."""
    return _base62(zlib.crc32(str(account_id).lower().encode("ascii")) % 62**4, 4)


@dataclass(frozen=True, slots=True)
class OrderLinkIdParts:
    """The value object behind one id; `value` is its 36-char rendering. Parts
    that do not render an `OUR_ID` raise `InvalidOrderLinkId`, so any instance is valid."""

    env: EnvLetter
    group_id: GroupId
    account_tag: str
    seq: int
    tag: PurposeTag
    value: OrderLinkId = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not 0 <= self.seq <= SEQ_MAX:
            raise InvalidOrderLinkId(f"seq2 {self.seq} is outside 0..{SEQ_MAX}")
        group = _base62(self.group_id.int, 22)
        value = f"cv{self.env}-{group}-{self.account_tag}-{_base62(self.seq, 2)}{self.tag}"
        if OUR_ID.fullmatch(value) is None:
            raise InvalidOrderLinkId(f"parts do not render an order_link_id: {value!r}")
        object.__setattr__(self, "value", value)

    @classmethod
    def generate(
        cls,
        *,
        mode: ExecutionMode,
        environment: Environment,
        group_id: GroupId,
        account_id: AccountId,
        seq: int,
        purpose: OrderPurpose,
    ) -> OrderLinkIdParts:
        """The id for one order of a trade group; the same inputs give the same id."""
        return cls(
            env=env_letter(mode, environment),
            group_id=group_id,
            account_tag=account_tag(account_id),
            seq=seq,
            tag=PURPOSE_TAG[purpose],
        )

    @classmethod
    def parse(cls, value: str) -> OrderLinkIdParts:
        """Decompose a stored id for diagnostics; an `ext-` key is not decomposable."""
        if OUR_ID.fullmatch(value) is None:
            raise InvalidOrderLinkId(f"not a generated order_link_id: {value[:64]!r}")
        group = _decode(value[4:26])
        if group >> 128:
            raise InvalidOrderLinkId(f"group segment exceeds 128 bits: {value!r}")
        return cls(
            env=cast(EnvLetter, value[2]),
            group_id=GroupId(UUID(int=group)),
            account_tag=value[27:31],
            seq=_decode(value[32:34]),
            tag=cast(PurposeTag, value[34:]),
        )

    def with_seq(self, seq: int) -> OrderLinkIdParts:
        """The same id with another `seq2`."""
        return replace(self, seq=seq)
