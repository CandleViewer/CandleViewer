"""Driver-free scanner-presets repository surface (E08-T09 PR 2a, #4708; migration
`0054_scanner_presets`, 21 section 3.8.7).

The `api` module may not import a storage driver (ADR-0003), so the router and its service type
against `ScannerPresetRepository` and these frozen dataclasses; `scanner_presets_sqlalchemy.py`
is the implementation.

Owner scoping (C-12.4): every method takes the caller's `owner` and the SQL re-checks it, so a
router or service bug can never read or write another user's preset. The one exception is
`is_foreign`: whether another user's row holds an id (the API answers it as a missing one, 404,
and audits the probe), and nothing else about the row.

A delete is a hard delete. A preset never stores results: `filter` is the `ScannerFilter` as
written, so a criterion the server later stops knowing stays in the row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Protocol

#: 22 `listScannerPresets`: a user holds at most this many presets (`409 limit_reached`).
MAX_PRESETS: Final = 100
#: `sp_name_len` and the API's `name` bound.
NAME_MAX: Final = 80
#: `sp_filter_shape` and the API's `filter` bound: bytes of the filter as Postgres prints jsonb.
FILTER_MAX_BYTES: Final = 4096

ConflictRule = Literal["name_taken", "limit_reached", "conflict"]


class ScannerPresetNotFoundError(Exception):
    """The preset is missing, deleted or another user's: identical here."""


class ScannerPresetConflictError(Exception):
    """409: `name_taken` (`ux_sp_name`: the owner has a preset with this name, by Postgres's
    `lower()`), `limit_reached` (`MAX_PRESETS`) or `conflict` (the owner's default is not the
    one the caller expected, or a racing default still trips `ux_sp_default` after one retry)."""

    def __init__(self, rule: ConflictRule) -> None:
        super().__init__(rule)
        self.rule: ConflictRule = rule
        self.field: str | None = "name" if rule == "name_taken" else None


class ScannerPresetShapeError(Exception):
    """`sp_filter_shape` refused the write: the backstop of the API's own size check (422)."""


@dataclass(frozen=True, slots=True)
class ScannerPresetFields:
    """Writable columns, already validated by `api.scanner_presets_models`."""

    name: str
    filter: dict[str, Any]
    sort: str
    is_default: bool


@dataclass(frozen=True, slots=True)
class ScannerPresetRow:
    """One stored preset (the `filter` as written, unknown criteria included)."""

    id: str
    user_id: str
    name: str
    filter: dict[str, Any]
    sort: str
    is_default: bool
    version: int
    created_at: datetime
    updated_at: datetime

    def fields(self) -> ScannerPresetFields:
        return ScannerPresetFields(self.name, self.filter, self.sort, self.is_default)


@dataclass(frozen=True, slots=True)
class ExpectedDefault:
    """The owner's default a write expects to clear: its id and the `version` its write-ahead
    record was built from. The store clears that row at that version or refuses `conflict`, so
    the record and the row cannot disagree (24 section 15.5)."""

    id: str
    version: int


@dataclass(frozen=True, slots=True)
class ScannerPresetWrite:
    """A committed create or update: the row, and the owner's previous default as the same
    transaction left it (flag cleared, `version` raised), if the write cleared one."""

    row: ScannerPresetRow
    cleared: ScannerPresetRow | None


class ScannerPresetRepository(Protocol):
    async def list_own(self, owner: str) -> list[ScannerPresetRow]:
        """The owner's presets by case-insensitive name, then id (at most `MAX_PRESETS`)."""
        ...

    async def get_own(self, owner: str, preset_id: str) -> ScannerPresetRow | None:
        """The owner's preset with this id; None for anything else."""
        ...

    async def get_default(self, owner: str) -> ScannerPresetRow | None:
        """The owner's default preset, if any."""
        ...

    async def is_foreign(self, owner: str, preset_id: str) -> bool:
        """Whether another user's preset holds this id. Unscoped by design; no row data."""
        ...

    async def occupancy(
        self, owner: str, name: str | None = None, *, exclude_id: str | None = None
    ) -> tuple[int, bool]:
        """(the owner's preset count, whether a preset other than `exclude_id` holds `name` by
        Postgres's `lower()`). A read, not a lock: the writes decide again."""
        ...

    async def create(
        self,
        owner: str,
        preset_id: str,
        fields: ScannerPresetFields,
        *,
        expected_default: ExpectedDefault | None = None,
    ) -> ScannerPresetWrite:
        """Insert under the owner's advisory lock: `limit_reached` at the cap, `name_taken` on
        `ux_sp_name`, `ScannerPresetShapeError` on `sp_filter_shape`. With `is_default`, the
        owner's other default, which must be `expected_default` at its `version` (else
        `conflict`), is cleared in the same transaction."""
        ...

    async def update(
        self,
        owner: str,
        preset_id: str,
        fields: ScannerPresetFields,
        *,
        expected_default: ExpectedDefault | None = None,
    ) -> ScannerPresetWrite:
        """Full replacement of the owner's preset, `version` raised; `ScannerPresetNotFoundError`
        when it is gone; the default and the refusals as `create`."""
        ...

    async def delete(self, owner: str, preset_id: str) -> bool:
        """Hard-delete the owner's preset under the owner's advisory lock; False when there was
        none."""
        ...


__all__ = [
    "FILTER_MAX_BYTES", "MAX_PRESETS", "NAME_MAX", "ConflictRule", "ExpectedDefault",
    "ScannerPresetConflictError",
    "ScannerPresetFields", "ScannerPresetNotFoundError", "ScannerPresetRepository",
    "ScannerPresetRow", "ScannerPresetShapeError", "ScannerPresetWrite",
]  # fmt: skip
