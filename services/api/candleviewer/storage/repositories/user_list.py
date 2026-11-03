"""The user list's read (#5478, 22 `listUsers`): what `SqlAlchemyUserAdminStore.list_users` is
asked for, and the `ILIKE` pattern of a `q`.

`UserListFilter` names one page's read: the filters as the route validated them (`None` matches
every row), the position the page starts after (`created_at`, then `id`: the list's order), and how
many rows to read, the page size plus one, so the extra row says a next page exists. A client's `q`
reaches the statement only as a bound pattern built here, with `\\`, `%` and `_` escaped, so the
text matches itself and never acts as a wildcard.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

__all__ = ["UserListFilter", "like_pattern"]


@dataclass(frozen=True, slots=True)
class UserListFilter:
    """One page's read of the user list (module docstring)."""

    status: str | None
    role: str | None
    pattern: str | None
    after: tuple[datetime, uuid.UUID] | None
    limit: int


def like_pattern(q: str) -> str:
    """`q` as a substring pattern for `ILIKE ... ESCAPE '\\'`: each `\\`, `%` and `_` in it is
    escaped by a `\\`, so it matches itself, and the whole is wrapped in `%`."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
