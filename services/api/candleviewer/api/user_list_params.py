"""`GET /users`' query string and cursor (#5478, 22 `listUsers`).

The query string is read here, after RBAC, never by FastAPI before the route runs: a caller without
`users:read` gets its one `403` whatever it sends, and a query 22 refuses is the route's
`400 validation_failed`, naming each field and rule that failed (`FieldError`), never a value
(C-12.6). Each of `limit`, `cursor`, `status`, `role` and `q` is read at most once, and an
undeclared parameter is ignored, as on every list. The values read pass a frozen model of 22's
bounds (`UserListQuery`): `limit` 1 to 500 (100 when absent) in at most four digits, so `00500`
is refused and a long run of digits never reaches `int()`, `status` and `role` one of 22's
`UserStatus` and `RoleName` values, `q` at most 120 characters and no NUL (Postgres `text` holds
none), `cursor` at most 512 characters. This mirrors `api.oms_read_params`, which imports the OMS's
types and so is not imported here.

A cursor is the trade-group lists' (`api.trade_group_cursor`): opaque, bound to `listUsers`, the
caller and `status`, `role` and `q` as sent, for one hour, and unsigned: a caller can make only a
position, read in its own scope. Its position is the last row's `created_at`, in microseconds since
the epoch, and its id: no username, e-mail or display name. One that is malformed, longer than 512
characters, expired, or issued to another caller or for other filters is `CursorInvalid`, the
route's `400 invalid_cursor`.
"""

from __future__ import annotations

import re
import struct
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.datastructures import QueryParams

from candleviewer.api.trade_group_cursor import MAX_CURSOR, decode_cursor, encode_cursor

__all__ = [
    "DEFAULT_LIMIT", "MAX_LIMIT", "MAX_Q", "OPERATION", "PARAMS", "CursorInvalid", "FieldError",
    "ParamsInvalid", "UserListQuery", "next_cursor", "position_of", "read_after",
    "user_list_query",
]  # fmt: skip

OPERATION: Final = "listUsers"
DEFAULT_LIMIT: Final = 100
MAX_LIMIT: Final = 500
MAX_Q: Final = 120
#: 22's query parameters of `listUsers`, each read at most once.
PARAMS: Final = ("limit", "cursor", "status", "role", "q")
_DIGITS: Final = re.compile(r"[0-9]{1,4}")
_POSITION: Final = struct.Struct(">q16s")  # microseconds since the epoch, then the id
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_US: Final = timedelta(microseconds=1)
#: Each field's rule, in words that name no value (C-12.6).
_MESSAGES: Final = {
    "limit": f"An integer from 1 to {MAX_LIMIT}.",
    "status": "One of 22's `UserStatus` values.",
    "role": "One of 22's `RoleName` values.",
    "q": f"At most {MAX_Q} characters, with no NUL character.",
}
#: The rule each pydantic error type is named by.
_RULES: Final = {
    "greater_than_equal": "range",
    "less_than_equal": "range",
    "literal_error": "enum",
    "string_too_long": "max_length",
    "value_error": "nul",
}

UserStatusName = Literal["invited", "active", "disabled", "locked"]  # 22 `UserStatus`
RoleNameValue = Literal["owner", "manager", "viewer"]  # 22 `RoleName`


@dataclass(frozen=True, slots=True)
class FieldError:
    """One rule a parameter failed: its name, the rule and a message, never its value."""

    field: str
    rule: str
    message: str


class ParamsInvalid(Exception):
    """A query string 22 refuses: `400 validation_failed` with each rule that failed."""

    def __init__(self, errors: Sequence[FieldError]) -> None:
        super().__init__("validation_failed")
        self.errors = tuple(errors)


class CursorInvalid(Exception):
    """A cursor that is malformed, expired, or another caller's or query's: `400 invalid_cursor`."""


class UserListQuery(BaseModel):
    """22 `listUsers`' parameters as read: frozen, closed and strict (module docstring)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    status: UserStatusName | None = None
    role: RoleNameValue | None = None
    q: Annotated[str, Field(max_length=MAX_Q)] | None = None
    cursor: Annotated[str, Field(max_length=MAX_CURSOR)] | None = None

    @field_validator("q")
    @classmethod
    def _no_nul(cls, q: str | None) -> str | None:
        if q is not None and "\x00" in q:
            raise ValueError("a NUL character")
        return q

    @property
    def binding(self) -> tuple[str | None, str | None, str | None]:
        """The filters a cursor is bound to, as sent; the page size is not one."""
        return self.status, self.role, self.q


def _refused(error: Mapping[str, Any]) -> FieldError:
    field, kind = str(error["loc"][0]), str(error["type"])
    return FieldError(field, _RULES.get(kind, kind), _MESSAGES.get(field, "Not valid here."))


def user_list_query(params: QueryParams) -> UserListQuery:
    """22 `listUsers`' parameters, else `ParamsInvalid`; a cursor longer than 512 characters, and
    nothing else wrong, is `CursorInvalid`, as any malformed cursor is."""
    errors: list[FieldError] = []
    read: dict[str, str | int] = {}
    for name in PARAMS:
        values = params.getlist(name)
        if len(values) > 1:
            errors.append(FieldError(name, "single", f"Send `{name}` at most once."))
        elif values:
            read[name] = values[0]
    if isinstance(limit := read.get("limit"), str):
        if _DIGITS.fullmatch(limit) is None:
            errors.append(FieldError("limit", "range", _MESSAGES["limit"]))
            del read["limit"]
        else:
            read["limit"] = int(limit)
    try:
        query = UserListQuery.model_validate(read)
    except ValidationError as exc:
        errors += [e for e in map(_refused, exc.errors()) if e.field != "cursor"]
        if errors:
            raise ParamsInvalid(errors) from None
        raise CursorInvalid from None
    if errors:
        raise ParamsInvalid(errors)
    return query


def read_after(
    query: UserListQuery, caller: uuid.UUID, now: int
) -> tuple[datetime, uuid.UUID] | None:
    """The page's start: None for the first page, else the cursor's position; `CursorInvalid`
    for one that is malformed, expired, or another caller's or query's (module docstring)."""
    if query.cursor is None:
        return None
    raw = decode_cursor(query.cursor, OPERATION, caller, query.binding, now)
    if raw is None or len(raw) != _POSITION.size:
        raise CursorInvalid
    micros, key = _POSITION.unpack(raw)
    try:
        return _EPOCH + micros * _US, uuid.UUID(bytes=key)
    except OverflowError:  # a position no `datetime` holds: forged
        raise CursorInvalid from None


def position_of(user: Mapping[str, object]) -> tuple[datetime, uuid.UUID]:
    """A listed user's place in the list's order, as the store maps it: `created_at`, then `id`."""
    return datetime.fromisoformat(str(user["created_at"])), uuid.UUID(str(user["id"]))


def next_cursor(
    query: UserListQuery, caller: uuid.UUID, last: tuple[datetime, uuid.UUID], now: int
) -> str:
    """The cursor of the page after `last`, bound as `read_after` reads it."""
    at, key = last
    position = _POSITION.pack((at - _EPOCH) // _US, key.bytes)
    return encode_cursor(OPERATION, caller, query.binding, position, now)
