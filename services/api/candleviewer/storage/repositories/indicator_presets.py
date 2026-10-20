"""Driver-free indicator-presets repository surface (E13-T03, #427; migration
`0040_indicator_presets`).

The `api` module may not import a storage driver (ADR-0003), so the router and its service type
against `IndicatorPresetRepository` and these frozen dataclasses;
`indicator_presets_sqlalchemy.py` is the implementation.

Owner scoping (C-12.4; E13 threat model IR-01, SR-051): every method takes the caller's `owner`
and the SQL re-checks it, so a router or service bug can never read or write another user's
preset. Reads see the caller's rows and the built-ins (`owner_user_id = :owner OR owner_user_id
IS NULL`); writes touch only the caller's own rows, never a built-in (`owner_user_id = :owner AND
NOT is_builtin`; a built-in has no owner, `ip_builtin_owner`). The one exception is
`other_class`: for an id that is not the caller's live preset it says whether a live built-in or
another user's live preset holds it (the API answers 403 and 404, and audits both), and nothing
else about the row.

Nothing here deletes a row: `soft_delete` sets `deleted_at` and the row stays (no purge job).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Protocol

#: SR-E13-07: live presets per user. Storage may not import `orderflow`, so this copies
#: `orderflow/indicators/limits.PRESETS_PER_USER_MAX`; a unit test pins the two equal.
MAX_LIVE_PRESETS: Final = 500
#: SR-E13-07: presets in one bundle import (`limits.BUNDLE_IMPORT_PRESETS_MAX`, pinned alike).
MAX_IMPORT_PRESETS: Final = 200
#: `ip_name_len` and the API's `name` bound (`limits.PRESET_NAME_MAX`, pinned the same way).
NAME_MAX: Final = 80

OtherClass = Literal["builtin", "foreign"]
ConflictRule = Literal["name_taken", "limit_reached"]


class PresetNotFoundError(Exception):
    """The preset is missing, soft-deleted, another user's or a built-in: identical here."""


class PresetConflictError(Exception):
    """409: `name_taken` (`ux_ip_name`: the owner has a live preset with this `indicator_code`
    and name, case-insensitive) or `limit_reached` (`MAX_LIVE_PRESETS` live presets)."""

    def __init__(self, rule: ConflictRule) -> None:
        super().__init__(rule)
        self.rule: ConflictRule = rule
        self.field: str | None = "name" if rule == "name_taken" else None


class PresetShapeError(Exception):
    """A CHECK on the stored JSON (`ip_params_shape` / `ip_style_shape`) refused the write: the
    API's own size check is the first line, so this is its backstop (422, never a 500)."""

    def __init__(self, field: Literal["params", "style"]) -> None:
        super().__init__(field)
        self.field: Literal["params", "style"] = field


@dataclass(frozen=True, slots=True)
class PresetFields:
    """Writable columns, already validated by `api.indicator_presets_models`: `params` complete
    and canonical, `style` within the closed vocabulary, `name` sanitised and trimmed."""

    indicator_code: str
    name: str
    params: dict[str, Any]
    style: dict[str, Any]
    pane_target: Literal["overlay", "subpane"]
    is_favourite: bool


@dataclass(frozen=True, slots=True)
class PresetRow:
    """One live preset as `IndicatorPreset` serves it (`deleted_at` is never read)."""

    id: str
    owner_user_id: str | None
    indicator_code: str
    name: str
    params: dict[str, Any]
    style: dict[str, Any]
    pane_target: Literal["overlay", "subpane"]
    is_builtin: bool
    is_favourite: bool
    created_at: datetime
    updated_at: datetime

    def fields(self) -> PresetFields:
        return PresetFields(
            self.indicator_code, self.name, self.params, self.style, self.pane_target,
            self.is_favourite,
        )  # fmt: skip


@dataclass(frozen=True, slots=True)
class Occupancy:
    """The owner's live presets, and whether one of them already holds a name."""

    live_presets: int
    name_taken: bool


class IndicatorPresetRepository(Protocol):
    async def list_visible(self, owner: str) -> list[PresetRow]:
        """The built-ins and the owner's live presets: built-ins first, then by
        `indicator_code`, case-insensitive `name` and `id` (at most 18 + `MAX_LIVE_PRESETS`)."""
        ...

    async def get_own(self, owner: str, preset_id: str) -> PresetRow | None:
        """The owner's live preset with this id; None for anything else (a built-in included)."""
        ...

    async def other_class(self, owner: str, preset_id: str) -> OtherClass | None:
        """For an id that is not the owner's: `builtin` or `foreign` when a live row holds it,
        else None (missing or deleted). Unscoped by design; returns no row data."""
        ...

    async def occupancy(
        self, owner: str, name_key: tuple[str, str] | None = None, *, exclude_id: str | None = None
    ) -> Occupancy:
        """The owner's live preset count and, for `name_key` (`indicator_code`, name), whether
        a live preset other than `exclude_id` holds that name, case-insensitive. A read, not a
        lock: `create` and `update` decide again under the unique index and the owner lock."""
        ...

    async def create(self, owner: str, preset_id: str, fields: PresetFields) -> PresetRow:
        """Insert under the owner's advisory lock; `PresetConflictError` past the cap or on
        `ux_ip_name`, `PresetShapeError` on a JSON CHECK."""
        ...

    async def update(self, owner: str, preset_id: str, fields: PresetFields) -> PresetRow:
        """Full replacement of the owner's live preset (never its `indicator_code`);
        `PresetNotFoundError` when it is gone, `PresetConflictError` on `ux_ip_name`."""
        ...

    async def soft_delete(self, owner: str, preset_id: str) -> bool:
        """Set `deleted_at` on the owner's live preset; False when there was none."""
        ...

    async def import_many(
        self, owner: str, items: Sequence[tuple[str, PresetFields]]
    ) -> list[PresetRow]:
        """Insert every item or none, in one transaction under the owner's advisory lock: past
        the cap is `PresetConflictError("limit_reached")`; a name the owner (or an earlier item)
        already holds for that indicator gets the first free ` (2)`, ` (3)`, ... suffix, cut so
        the name stays within `NAME_MAX` characters. Never overwrites."""
        ...

    async def count_live_by_builtin(self) -> dict[bool, int]:
        """Live presets of all owners by `is_builtin` (the `indicator_presets_total` gauge)."""
        ...


def unique_name(name: str, taken: set[str]) -> str:
    """`name`, or the first `name (n)` (n = 2, 3, ...) whose lower case `taken` lacks, the name
    cut first so the result fits `NAME_MAX` characters; trailing spaces of the cut are dropped
    (a stored name is trimmed). `taken` holds lower-cased names."""
    if name.lower() not in taken:
        return name
    n = 2
    while True:
        suffix = f" ({n})"
        candidate = name[: NAME_MAX - len(suffix)].rstrip() + suffix
        if candidate.lower() not in taken:
            return candidate
        n += 1


__all__ = [
    "MAX_IMPORT_PRESETS", "MAX_LIVE_PRESETS", "NAME_MAX", "ConflictRule",
    "IndicatorPresetRepository", "Occupancy", "OtherClass", "PresetConflictError",
    "PresetFields", "PresetNotFoundError", "PresetRow", "PresetShapeError", "unique_name",
]  # fmt: skip
