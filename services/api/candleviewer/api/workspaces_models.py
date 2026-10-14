"""Request validation for ``/workspaces`` and ``/layouts`` (E15-T01; pane models: spec D1-D7).

WHY a pure module: the router, the repository and the OpenAPI contract must agree on one
definition of "a valid workspace/layout". No I/O, router or storage import lives here, so the
rules are unit- and property-tested exhaustively and reused unchanged by POST and PUT.

Security posture (C-12.1, ticket Security notes): every model is closed and frozen; names are
length-checked raw and sanitised (control/bidi characters removed) before storage; ``icon_token``
is a closed allow-list, never a URL; ``pane_config`` is bounded (<=32 keys, <=4096 bytes, scalars
only) so a pane cannot become a blob store. Existence and ownership of referenced rows is the
router's job. ``sanitize_text`` comes from ``drawings_models`` (one definition); the router imports
``format_errors`` and ``MAX_JSON_DEPTH`` from there directly.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from decimal import Decimal
from typing import Annotated, Any, Final, Literal, get_args
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainValidator,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

from candleviewer.api.drawings_models import sanitize_text

# --- enums: each Literal is pinned to the DB CHECK list by a unit test ------------------------
PaneKind = Literal[
    "chart", "dom", "tape", "profile", "cvd", "oi", "deep_stats", "regime",
    "positions", "journal", "watchlist", "alerts",
]  # fmt: skip
PaneScaleMode = Literal["auto", "linked", "manual", "log"]
LayoutGridPreset = Literal["1x1", "2x1", "1x2", "2x2", "1+3", "3x3", "custom"]
WorkspaceIconToken = Literal["workspace.default"]

DEFAULT_ICON: Final[WorkspaceIconToken] = "workspace.default"
PANE_KINDS: Final[tuple[str, ...]] = get_args(PaneKind)
SCALE_MODES: Final[tuple[str, ...]] = get_args(PaneScaleMode)
GRID_PRESETS: Final[tuple[str, ...]] = get_args(LayoutGridPreset)
WORKSPACE_ICON_TOKENS: Final[frozenset[str]] = frozenset(get_args(WorkspaceIconToken))
#: Kinds bound to a market; account kinds must leave symbol/interval null (D3, `ix_lp_symbol`).
MARKET_PANE_KINDS: Final = frozenset(PANE_KINDS[:8])

MAX_WORKSPACES: Final = 32
MAX_LAYOUTS: Final = 32
MAX_PANES: Final = 16
MAX_PANE_CONFIG_BYTES: Final = 4096
MAX_TREE_DEPTH: Final = 6
MAX_TREE_NODES: Final = 64
MAX_WORKSPACE_BODY_BYTES: Final = 4 * 1024
MAX_LAYOUT_BODY_BYTES: Final = 128 * 1024
NAME_MAX: Final = 40
_MAX_SETTINGS: Final = 32
_MAX_STR: Final = 256

#: The contract pattern for `PaneIntervalCode` (D4), mirrored exactly from #2400. The volume/delta
#: fraction is canonical (`(\.[0-9]{0,11}[1-9])?`: no trailing zero, so `0.50` and `1.0` are
#: refused); the server rule value > 0 (`interval_not_positive`) only ever fires on `0`.
INTERVAL_CODE_PATTERN: Final = (
    r"^(time|heikin_ashi):(1|3|5|15|30|60|120|240|360|720|D|W|M)$"
    r"|^(tick|range):[1-9][0-9]{0,8}$"
    r"|^(volume|delta):(0|[1-9][0-9]{0,10})(\.[0-9]{0,11}[1-9])?$"
    r"|^renko:([1-9][0-9]{0,8}|atr:[1-9][0-9]{0,2})$"
    r"|^pnf:[1-9][0-9]{0,8}:[1-9][0-9]{0,2}$"
)
INTERVAL_CODE_RE: Final = re.compile(INTERVAL_CODE_PATTERN)
SYMBOL_PATTERN: Final = r"^[A-Z0-9]{2,16}USDT$"
_SETTING_KEY_RE: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")

_CFG: Final = ConfigDict(frozen=True, extra="forbid")


def sanitize_name(value: str) -> str:
    """Sanitise then trim (D8). WHY the trim: names are identifiers with case-insensitive
    uniqueness, so "Scalping" and "Scalping " must not both exist."""
    return sanitize_text(value, allow_newline=False).strip()


def canonical_json(value: object) -> str:
    """Compact, key-sorted JSON; numbers are never normalised (``1`` stays ``1``, ``1.0`` stays
    ``1.0``) so equality and the 4096-byte cap see exactly what is stored (D6, D13)."""
    return json.dumps(
        value, separators=(",", ":"), ensure_ascii=False, sort_keys=True, allow_nan=False
    )


def _fail(errors: Iterable[tuple[tuple[str | int, ...], str, str]]) -> None:
    """Raise one ValidationError carrying several rule-named line errors (all collected)."""
    raise ValidationError.from_exception_data(
        "request",
        [
            InitErrorDetails(type=PydanticCustomError(rule, msg), loc=loc, input=None)
            for loc, rule, msg in errors
        ],
    )


def _no_null(value: object) -> object:
    """Non-nullable optionals may be omitted, never explicitly null (lossless round trip)."""
    if value is None:
        raise PydanticCustomError("null_not_allowed", "Value must be omitted rather than null")
    return value


def _name_in(value: object) -> object:
    """Raw max length first (the schema's maxLength applies as sent), lone surrogates, then
    sanitise + trim; min length is checked on the stored text by the field constraint."""
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
    if not clean:  # custom error so the rule name is the contract's `string_too_short`
        raise PydanticCustomError("string_too_short", "String must have at least 1 character")
    return clean


_NN = BeforeValidator(_no_null)
Name = Annotated[StrictStr, BeforeValidator(_name_in), Field(min_length=1, max_length=NAME_MAX)]
_Flag = Annotated[StrictBool, _NN]


# --- workspace -----------------------------------------------------------------------------
class WorkspaceIn(BaseModel):
    """`WorkspaceInput` (D9): the four columns a client may set."""

    model_config = _CFG
    name: Name
    is_default: _Flag = False
    icon_token: Annotated[WorkspaceIconToken, _NN] = DEFAULT_ICON
    sort_order: Annotated[StrictInt, _NN, Field(ge=0, le=32767)] = 0

    def db_values(self) -> dict[str, Any]:
        """Keys equal the repository's `WorkspaceFields`."""
        return {
            "name": self.name,
            "is_default": self.is_default,
            "icon_token": self.icon_token,
            "sort_order": self.sort_order,
        }


# --- pane config (D6) ----------------------------------------------------------------------
_MAX_NUMBER: Final = 10**15


def _setting_scalar(value: object) -> bool | int | float | str:
    """One scalar setting: bool, int, finite float or sanitised string; never coerced.

    WHY a plain validator: pydantic's union validation reports one error per branch per value,
    which let a small body fan out into tens of thousands of errors, and it left strings
    unsanitised (a NUL reaches Postgres as a raw driver error, a 500). One value now yields at
    most one error. Strings follow the name rules: raw length, lone surrogate, strip, trim.
    ``bool`` is tested before ``int`` (it is an ``int`` subclass); ints and floats keep their
    kind (``1`` stays ``1``, ``1.0`` stays ``1.0``); ``-0.0`` is stored as ``0.0``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            raise PydanticCustomError("finite_number", "Number must be finite")
        if abs(value) > _MAX_NUMBER:
            raise PydanticCustomError("number_out_of_range", "Number must be within +-1e15")
        return 0.0 if isinstance(value, float) and value == 0 else value
    if isinstance(value, str):
        if len(value) > _MAX_STR:
            raise PydanticCustomError(
                "string_too_long", "String must be at most {n} characters", {"n": _MAX_STR}
            )
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise PydanticCustomError(
                "invalid_unicode", "String is not valid Unicode (lone surrogate)"
            ) from None
        return sanitize_name(value)  # same strip set + trim as names (#2400 r3); empty is kept
    raise PydanticCustomError("setting_value_type", "Value must be a string, number or boolean")


def _cap(limit: int) -> BeforeValidator:
    """Refuse a container over ``limit`` entries BEFORE any entry is validated (so the cost of a
    hostile body is bounded by the cap, not by its size)."""

    def check(value: object) -> object:
        if isinstance(value, dict | list | tuple) and len(value) > limit:
            raise PydanticCustomError("too_long", "Must have at most {n} entries", {"n": limit})
        return value

    return BeforeValidator(check)


def _setting_value(value: object) -> object:
    """A setting: null, a scalar, or a flat array of scalars (<=32, first bad item reported).

    WHY one validator instead of a pydantic union: a union reports an error per branch per
    value, and a callable discriminator leaks its tags into the field path. Here a bad value is
    exactly one error at a clean path (``settings.k`` or ``settings.k.<i>``), and an array stops
    at its first bad item, so a hostile body cannot fan out into thousands of errors.
    """
    if value is None:
        return None
    if isinstance(value, list):
        if len(value) > _MAX_SETTINGS:
            raise PydanticCustomError(
                "too_long", "Must have at most {n} entries", {"n": _MAX_SETTINGS}
            )
        out: list[bool | int | float | str] = []
        for i, item in enumerate(value):
            try:
                out.append(_setting_scalar(item))
            except PydanticCustomError as exc:
                _fail([((i,), exc.type, exc.message())])
        return out
    return _setting_scalar(value)


SettingValue = Annotated[Any, PlainValidator(_setting_value)]


class PaneConfigIn(BaseModel):
    """`PaneConfig`: closed; `settings` is a flat, bounded map (never nested objects)."""

    model_config = _CFG
    sync_group: Literal["A", "B", "C"] | None = None
    settings: Annotated[dict[str, SettingValue], _cap(_MAX_SETTINGS), _NN] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def _keys(self) -> PaneConfigIn:
        bad = [k for k in self.settings if not _SETTING_KEY_RE.fullmatch(k)]
        if bad:
            # The key is client text: it is only echoed as a path segment, which `format_errors`
            # sanitises and clips to 64 characters; the message never contains it.
            _fail(
                (("settings", k), "invalid_setting_key", "Setting key must match [a-z][a-z0-9_]*")
                for k in bad
            )
        return self

    def to_json(self) -> dict[str, Any]:
        """Normalised stored form: null `sync_group` and empty `settings` are omitted, so
        omitted, `{}` and explicit-empty bodies are equal (no spurious write, D13)."""
        out: dict[str, Any] = {}
        if self.sync_group is not None:
            out["sync_group"] = self.sync_group
        if self.settings:
            out["settings"] = dict(self.settings)
        return out


# --- pane ----------------------------------------------------------------------------------
class LayoutPaneIn(BaseModel):
    """`LayoutPaneInput` (D1-D4, D7). Cross-field rules collect every violation."""

    model_config = _CFG
    slot_index: StrictInt = Field(ge=0, le=15)
    pane_kind: PaneKind
    symbol: Annotated[StrictStr, Field(pattern=SYMBOL_PATTERN)] | None = None
    interval_code: (
        Annotated[StrictStr, Field(pattern=INTERVAL_CODE_PATTERN, max_length=36)] | None
    ) = None
    chart_template_id: UUID | None = None
    indicator_preset_ids: Annotated[
        list[UUID],
        _cap(16),
        _NN,
        Field(max_length=16),
    ] = Field(default_factory=list)
    pane_config: Annotated[PaneConfigIn, _NN] = Field(default_factory=PaneConfigIn)
    scale_mode: Annotated[PaneScaleMode, _NN] = "auto"

    @model_validator(mode="after")
    def _rules(self) -> LayoutPaneIn:
        errs: list[tuple[tuple[str | int, ...], str, str]] = []
        if len(set(self.indicator_preset_ids)) != len(self.indicator_preset_ids):
            errs.append((("indicator_preset_ids",), "non_unique_items", "Items must be unique"))
        if self.pane_kind not in MARKET_PANE_KINDS:
            for key in ("symbol", "interval_code"):
                if getattr(self, key) is not None:
                    errs.append(
                        ((key,), "property_not_allowed_for_kind", f"{key} needs a market pane kind")
                    )
        code = self.interval_code
        if code is not None and code.startswith(("volume:", "delta:")):
            if Decimal(code.partition(":")[2]) <= 0:
                errs.append((("interval_code",), "interval_not_positive", "Threshold must be > 0"))
        if self.chart_template_id is not None:  # D7: refused until chart_templates exists
            errs.append(
                (("chart_template_id",), "chart_template_not_found", "No such chart template")
            )
        if self.indicator_preset_ids:  # D7: refused until E13-T03
            errs.append(
                (
                    ("indicator_preset_ids",),
                    "indicator_preset_not_found",
                    "No such indicator preset",
                )
            )
        if len(canonical_json(self.pane_config.to_json()).encode()) > MAX_PANE_CONFIG_BYTES:
            errs.append(
                (("pane_config",), "pane_config_too_large", "pane_config exceeds 4096 bytes")
            )
        if errs:
            _fail(errs)
        return self

    def db_values(self) -> dict[str, Any]:
        """Keys equal the repository's `PaneFields` (ids as strings, list as tuple)."""
        return {
            "slot_index": self.slot_index,
            "pane_kind": self.pane_kind,
            "symbol": self.symbol,
            "interval_code": self.interval_code,
            "chart_template_id": (
                None if self.chart_template_id is None else str(self.chart_template_id)
            ),
            "indicator_preset_ids": tuple(str(i) for i in self.indicator_preset_ids),
            "pane_config": self.pane_config.to_json(),
            "scale_mode": self.scale_mode,
        }
