"""Request validation for `/scanner/presets*` (E08-T09 PR 2a, #4708): 22 `ScannerPresetInput`.

Pure (no I/O, no routing).

1. `ScannerPresetInput` is the closed, frozen DTO: `extra="forbid"` refuses `id`, `version`,
   `unavailable_criteria`, the timestamps, results and every other unknown property. `name` is at
   most 80 characters as sent, refused with a lone surrogate, then sanitised and trimmed as a
   workspace name is (`workspaces_models.sanitize_name`); empty after that is
   `string_too_short`. `filter` must be a JSON object; `sort` a `ScannerSortKey`
   (`turnover_24h` when omitted); `is_default` false when omitted.
2. `preset_fields()` checks the filter: at most `FILTER_MAX_BYTES` as Postgres prints jsonb
   (`filter_too_large`, the bound `sp_filter_shape` holds too), measured first, on the value as
   sent; then `scanner_criteria.check_filter` with `field` `filter.<criterion id>`, and
   `scanner_criteria.sort_defect` on `sort` (both refuse `criterion_unavailable`, reported
   together). It returns the `ScannerPresetFields` the store keeps: the filter as written.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, field_validator
from pydantic_core import PydanticCustomError

from candleviewer.api.indicator_presets_models import jsonb_text_bytes
from candleviewer.api.scanner_criteria import FilterInvalidError, check_filter, sort_defect
from candleviewer.api.workspaces_models import sanitize_name
from candleviewer.storage.repositories.scanner_presets import (
    FILTER_MAX_BYTES,
    NAME_MAX,
    ScannerPresetFields,
)

#: 22 `createScannerPreset`: a body over this many bytes is `413`, refused before parsing.
SCANNER_PRESET_BODY_MAX_BYTES: Final = 8 * 1024

#: 22 `ScannerSortKey` (`scanner_criteria.SORT_KEYS`, pinned equal by a unit test).
ScannerSortKey = Literal[
    "volume_24h", "price_change_pct_24h", "cvd", "tape_speed", "open_interest",
    "liquidation_intensity", "turnover_24h", "funding_rate", "spread_bps", "range_pct_24h",
    "tape_speed_zscore", "oi_change_pct_24h",
]  # fmt: skip


class ScannerPresetInvalidError(Exception):
    """422 `validation_failed`; `errors` are the contract's `{field, rule, message}` items."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__(f"{len(errors)} invalid preset field(s)")
        self.errors = errors


class ScannerPresetInput(BaseModel):
    """22 `ScannerPresetInput`: a whole preset as a create or a replace (`PUT` is a full
    replacement: an omitted field takes its default) sends it."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: StrictStr
    filter: dict[str, Any]
    sort: ScannerSortKey = "turnover_24h"
    is_default: StrictBool = False

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value: object) -> object:
        """The raw length first (the contract's `maxLength` applies as sent), then a lone
        surrogate, then sanitise and trim; a non-string passes on to the type check."""
        if not isinstance(value, str):
            return value
        if len(value) > NAME_MAX:
            raise PydanticCustomError(
                "string_too_long", "String must be at most {n} characters", {"n": NAME_MAX}
            )
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise PydanticCustomError(
                "invalid_unicode", "String is not valid Unicode (lone surrogate)"
            ) from None
        clean = sanitize_name(value)
        if not clean:
            raise PydanticCustomError("string_too_short", "String must have at least 1 character")
        return clean


def preset_fields(body: ScannerPresetInput) -> ScannerPresetFields:
    """`body` as the store keeps it (module docstring, step 2), else `ScannerPresetInvalidError`."""
    if jsonb_text_bytes(body.filter) > FILTER_MAX_BYTES:
        message = f"filter must be at most {FILTER_MAX_BYTES} bytes."
        raise ScannerPresetInvalidError(
            [{"field": "filter", "rule": "filter_too_large", "message": message}]
        )
    errors: list[dict[str, str]] = []
    try:
        flt = check_filter(body.filter, root="filter")
    except FilterInvalidError as exc:
        errors = exc.errors
    sort_error = sort_defect(body.sort)
    if sort_error is not None:
        errors = [*errors, sort_error]
    if errors:
        raise ScannerPresetInvalidError(errors)
    return ScannerPresetFields(body.name, flt, body.sort, body.is_default)


__all__ = [
    "SCANNER_PRESET_BODY_MAX_BYTES", "ScannerPresetInput", "ScannerPresetInvalidError",
    "ScannerSortKey", "preset_fields",
]  # fmt: skip
