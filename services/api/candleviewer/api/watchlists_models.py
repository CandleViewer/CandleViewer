"""`WatchlistInput` (22) for `/watchlists` (E08-T07, #4706): the closed body and its list rules.

Pure: no I/O. `WatchlistIn` is the body's shape, every rule that needs no instrument catalogue:
`extra="forbid"` and strict types; a `name` trimmed of leading and trailing white space first
(`str.strip()`, Unicode white space), as 22 and E08-D07 §4.3 compare names, then of 1 to 80
characters holding no control or format character (Unicode Cc or Cf: U+0000, which Postgres
`text` cannot hold, among them), by the account-profile name's rule (`profile_body.name_errors`,
D2-c R1S-06), rule `not_allowed`; each symbol of the `Symbol` pattern,
over `MAX_SYMBOLS` of them `too_many_symbols`, judged before the items, so it is the one error a
long list gets; `columns` at most 32 ids of 22's pattern, none twice (`duplicate_column`), left
out or `null` meaning `DEFAULT_COLUMNS`, E08-D07 §4.1's nine defaults. `duplicate_errors` is the
last rule of shape. `unknown_errors` is the one rule that needs the catalogue, asked only of the
symbols a list does not hold yet. The list rules are on `symbols`, as 22 names them, each message
naming its symbol, which the `Symbol` pattern has already held to `[A-Z0-9]`. A body past
`MAX_BODY_BYTES` is the router's `413`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Annotated, Final

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, StrictStr
from pydantic_core import PydanticCustomError

from candleviewer.api.profile_body import name_errors

MAX_SYMBOLS: Final = 200
NAME_MAX: Final = 80
MAX_COLUMNS: Final = 32
#: 22's body cap on `createWatchlist` and `updateWatchlist`: past it, `413 payload_too_large`.
MAX_BODY_BYTES: Final = 64 * 1024
#: 22 `Symbol`: a USDT-quoted linear symbol.
SYMBOL_PATTERN: Final = r"^[A-Z0-9]{2,20}USDT$"
#: 22 `WatchlistInput.columns` items: a lowercase snake_case id of at most 32 characters.
COLUMN_PATTERN: Final = r"^[a-z][a-z0-9_]*$"
#: What `columns` left out or `null` stores: E08-D07 §4.1's nine defaults that have an id, in order.
DEFAULT_COLUMNS: Final = (
    "symbol", "last", "chg_24h_pct", "turnover_24h", "funding_rate", "next_funding",
    "oi_chg_24h_pct", "spread_bps", "rec",
)  # fmt: skip
_MAX_ERRORS: Final = 20


def _trimmed(value: object) -> object:
    """A name as 22 and E08-D07 §4.3 compare it: without leading or trailing white space."""
    return value.strip() if isinstance(value, str) else value


def _shown(value: str) -> str:
    """No control or format character (Unicode Cc or Cf) in the trimmed name: the account-profile
    name's rule and words, from `profile_body.name_errors`."""
    if refused := name_errors({"name": value}):
        raise PydanticCustomError(refused[0].rule, refused[0].message)
    return value


def _at_most_max(value: object) -> object:
    if isinstance(value, list) and len(value) > MAX_SYMBOLS:
        raise PydanticCustomError("too_many_symbols", "A watchlist holds at most 200 symbols.")
    return value


def _each_once(value: list[str]) -> list[str]:
    if len(set(value)) != len(value):
        raise PydanticCustomError("duplicate_column", "A column id may appear once.")
    return value


_Symbol = Annotated[StrictStr, Field(pattern=SYMBOL_PATTERN)]
_Column = Annotated[StrictStr, Field(max_length=32, pattern=COLUMN_PATTERN)]
_Columns = Annotated[list[_Column], Field(max_length=MAX_COLUMNS), AfterValidator(_each_once)]


class WatchlistIn(BaseModel):
    """22 `WatchlistInput`, closed; `version` is never in a body (it comes as `If-Match`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[
        StrictStr,
        Field(min_length=1, max_length=NAME_MAX),
        BeforeValidator(_trimmed),
        AfterValidator(_shown),
    ]
    symbols: Annotated[list[_Symbol], BeforeValidator(_at_most_max)]
    columns: _Columns | None = None

    def stored_columns(self) -> tuple[str, ...]:
        """What a create or a replace stores: the columns sent, else the defaults."""
        return DEFAULT_COLUMNS if self.columns is None else tuple(self.columns)


def _entry(rule: str, message: str) -> dict[str, str]:
    return {"field": "symbols", "rule": rule, "message": message}


def duplicate_errors(symbols: Sequence[str]) -> list[dict[str, str]]:
    """`duplicate_symbol` for each repeat, in list order, at most 20 entries."""
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for symbol in symbols:
        if symbol in seen:
            errors.append(_entry("duplicate_symbol", f"{symbol} is on the list twice."))
        seen.add(symbol)
    return errors[:_MAX_ERRORS]


def unknown_errors(symbols: Sequence[str], listed: Callable[[str], bool]) -> list[dict[str, str]]:
    """`unknown_symbol` for each symbol `listed` refuses, in order, at most 20 entries."""
    message = "{} is not a trading USDT perpetual of the instrument catalogue."
    unknown = [s for s in symbols if not listed(s)]
    return [_entry("unknown_symbol", message.format(s)) for s in unknown][:_MAX_ERRORS]


__all__ = [
    "COLUMN_PATTERN", "DEFAULT_COLUMNS", "MAX_BODY_BYTES", "MAX_COLUMNS", "MAX_SYMBOLS",
    "NAME_MAX", "WatchlistIn", "duplicate_errors", "unknown_errors",
]  # fmt: skip
