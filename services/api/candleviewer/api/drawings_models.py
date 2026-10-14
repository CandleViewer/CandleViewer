"""Request validation primitives for ``/drawings`` (E14-T01, #357).

WHY this is its own pure module: the router, the repository and the OpenAPI contract all have to
agree on exactly one definition of "a valid drawing". Keeping the rules here, with no I/O, no
storage and no FastAPI routing, lets them be unit-tested exhaustively (including property tests)
and reused unchanged by the single-write and batch paths, so the two can never drift apart.

Security posture: every model is closed (``extra="forbid"``) and frozen; prices (``p``) are never
converted to a float - the validated decimal string is stored and returned verbatim; control and
bidi-override characters are stripped from user text *before* length checks so a payload cannot
hide in, or inflate past, a limit; ``layout_id`` is only typed here - existence/ownership is the
router's job (E15 owns layouts), because it needs storage.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)
from pydantic_core import PydanticCustomError

Tool = Literal[
    "trendline",
    "horizontal_line",
    "vertical_line",
    "ray",
    "extended_line",
    "parallel_channel",
    "rectangle",
    "ellipse",
    "triangle",
    "fib_retracement",
    "fib_extension",
    "fib_timezone",
    "pitchfork",
    "gann_fan",
    "text",
    "arrow",
    "callout",
    "measure",
    "long_position",
    "short_position",
    "price_range",
    "date_range",
    "brush",
    "polyline",
    "anchored_vwap",
]
#: The 25 tools, in contract order (OpenAPI enum, DB CHECK and this Literal share one list).
TOOLS: Final[tuple[str, ...]] = get_args(Tool)

#: tool -> (min, max) number of points, inclusive.
POINT_COUNTS: Final[dict[str, tuple[int, int]]] = {
    **dict.fromkeys(("horizontal_line", "vertical_line", "text", "anchored_vwap"), (1, 1)),
    **dict.fromkeys(
        (
            "trendline",
            "ray",
            "extended_line",
            "rectangle",
            "ellipse",
            "fib_retracement",
            "fib_timezone",
            "gann_fan",
            "arrow",
            "callout",
            "measure",
            "price_range",
            "date_range",
        ),
        (2, 2),
    ),
    **dict.fromkeys(
        (
            "parallel_channel",
            "triangle",
            "fib_extension",
            "pitchfork",
            "long_position",
            "short_position",
        ),
        (3, 3),
    ),
    "brush": (2, 500),
    "polyline": (2, 100),
}

_MAX_TEXT: Final = 1000
_CFG: Final = ConfigDict(frozen=True, extra="forbid")

# --- sanitising -----------------------------------------------------------------------------
_STRIP: Final[frozenset[int]] = frozenset(
    {
        *range(0x00, 0x20),
        *range(0x7F, 0xA0),
        0x2028,
        0x2029,
        0x061C,
        0x200E,
        0x200F,
        *range(0x202A, 0x202F),
        *range(0x2066, 0x206A),
    }
)
_TABLE: Final = dict.fromkeys(_STRIP)
_TABLE_KEEP_LF: Final = dict.fromkeys(_STRIP - {0x0A})


def sanitize_text(value: str, *, allow_newline: bool) -> str:
    """Strip control, line-separator and bidi-override characters; change nothing else.

    WHY: such characters enable log injection and "Trojan Source" style spoofing of what a
    trader sees on the chart. No trimming or Unicode normalisation is done on purpose: the
    stored text must be exactly what the user typed minus the dangerous characters, and the
    function must be idempotent. ``allow_newline`` keeps U+000A (chart text may be multi-line;
    labels may not).
    """
    return value.translate(_TABLE_KEEP_LF if allow_newline else _TABLE)


def _clean(value: object, *, allow_newline: bool) -> object:
    """Before-validator: reject lone surrogates, then sanitise; non-strings pass to type check."""
    if not isinstance(value, str):
        return value
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise PydanticCustomError(
            "invalid_unicode", "String is not valid Unicode (lone surrogate)"
        ) from None
    return sanitize_text(value, allow_newline=allow_newline)


def _no_null(value: object) -> object:
    """Optional keys may be omitted but never explicitly null (keeps the round-trip lossless)."""
    if value is None:
        raise PydanticCustomError("null_not_allowed", "Value must be omitted rather than null")
    return value


# --- points ---------------------------------------------------------------------------------
_T_PATTERN: Final = (
    r"^20[0-9]{2}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
    r"T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,3})?Z$"
)
_P_PATTERN: Final = r"^-?(0|[1-9][0-9]{0,14})(\.[0-9]{1,12})?$"


def _parse_t(t: str) -> datetime:
    """Parse an already pattern-checked ``t`` into an aware UTC datetime (calendar-checked)."""
    date_part, _, rest = t[:-1].partition("T")
    hms, _, frac = rest.partition(".")
    year, month, day = (int(x) for x in date_part.split("-"))
    hour, minute, second = (int(x) for x in hms.split(":"))
    micro = int(frac.ljust(6, "0")) if frac else 0
    return datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)


class DrawingPointIn(BaseModel):
    """One chart coordinate: UTC time ``t`` and price ``p`` (both kept as the original strings)."""

    model_config = _CFG
    t: Annotated[StrictStr, Field(pattern=_T_PATTERN)]
    p: Annotated[StrictStr, Field(pattern=_P_PATTERN)]

    @field_validator("t", mode="after")
    @classmethod
    def _real_calendar(cls, v: str) -> str:
        """The regex allows day 31 in every month; reject dates that do not exist (Feb 30)."""
        try:
            _parse_t(v)
        except ValueError:
            raise PydanticCustomError("invalid_timestamp", "Timestamp is not a real date") from None
        return v


def anchors(points: Iterable[DrawingPointIn]) -> tuple[datetime, datetime]:
    """(earliest, latest) point time as aware UTC datetimes - the indexed anchor columns."""
    times = [_parse_t(p.t) for p in points]
    return min(times), max(times)


# --- geometry / style -----------------------------------------------------------------------
def _bounded(v: tuple[Any, ...], hi: int) -> None:
    """Length bounds as an after-validator: Field(min_length) on a tuple also fires a spurious
    ``too_short`` when an *item* failed, which would double-report one mistake."""
    if len(v) < 1:
        raise PydanticCustomError("too_short", "At least 1 item is required")
    if len(v) > hi:
        raise PydanticCustomError("too_long", "At most {n} items are allowed", {"n": hi})


class DrawingGeometryIn(BaseModel):
    """Tool-independent geometry shape. Per-tool rules need the tool, so ``DrawingIn`` applies them.

    ``points`` deliberately has no Field bounds: the 1..500 cap is the per-tool ``POINT_COUNTS``
    check so every count violation reports the same ``tool_point_count`` rule.
    """

    model_config = _CFG
    points: tuple[DrawingPointIn, ...]
    extend_left: StrictBool | None = None
    extend_right: StrictBool | None = None
    levels: (
        tuple[
            Annotated[StrictFloat | StrictInt, Field(ge=-1000, le=1000, allow_inf_nan=False)], ...
        ]
        | None
    ) = None
    bands: tuple[Annotated[StrictInt, Field(ge=1, le=3)], ...] | None = None
    text: StrictStr | None = None

    _none_guard = field_validator(
        "extend_left", "extend_right", "levels", "bands", "text", mode="before"
    )(staticmethod(_no_null))

    @field_validator("text", mode="before")
    @classmethod
    def _clean_text(cls, v: object) -> object:
        return _clean(v, allow_newline=True)

    @field_validator("text", mode="after")
    @classmethod
    def _text_length(cls, v: str | None) -> str | None:
        if v is not None and not v:
            raise PydanticCustomError("text_required", "Text must not be empty")
        if v is not None and len(v) > _MAX_TEXT:
            raise PydanticCustomError(
                "string_too_long", "Text must be at most {n} characters", {"n": _MAX_TEXT}
            )
        return v

    @field_validator("levels", mode="after")
    @classmethod
    def _unique_levels(cls, v: tuple[float, ...]) -> tuple[float, ...]:
        _bounded(v, 24)
        if len(set(v)) != len(v):
            raise PydanticCustomError("duplicate_level", "Levels must be unique")
        return v

    @field_validator("bands", mode="after")
    @classmethod
    def _unique_bands(cls, v: tuple[int, ...]) -> tuple[int, ...]:
        _bounded(v, 3)
        if len(set(v)) != len(v):
            raise PydanticCustomError("duplicate_band", "Bands must be unique")
        return v


class DrawingStyleIn(BaseModel):
    """Closed style bag; every key optional. ``label`` lives on the drawing, not here."""

    model_config = _CFG
    colour: Annotated[StrictStr, Field(pattern=r"^#[0-9a-fA-F]{6}$")] | None = None
    fill_colour: Annotated[StrictStr, Field(pattern=r"^#[0-9a-fA-F]{6}$")] | None = None
    fill_opacity: (
        Annotated[StrictFloat | StrictInt, Field(ge=0, le=1, allow_inf_nan=False)] | None
    ) = None
    width: Annotated[StrictInt, Field(ge=1, le=8)] | None = None
    dash: Literal["solid", "dashed", "dotted"] | None = None
    font_size: Annotated[StrictInt, Field(ge=8, le=48)] | None = None

    @field_validator("colour", "fill_opacity", "width", "dash", "font_size", mode="before")
    @classmethod
    def _no_null_style(cls, v: object) -> object:
        return _no_null(v)  # only fill_colour may be an explicit null (= "no fill")
