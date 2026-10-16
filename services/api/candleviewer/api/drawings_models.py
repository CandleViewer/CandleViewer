"""Request validation for the ``/drawings`` API (E14-T01, #357; decision record on the ticket).

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

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal, get_args
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    FailFast,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

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

MAX_BATCH_OPS: Final = 200
MAX_SINGLE_BODY_BYTES: Final = 64 * 1024
MAX_BATCH_BODY_BYTES: Final = 1024 * 1024
MAX_JSON_DEPTH: Final = 16

_TEXT_TOOLS: Final = frozenset({"text", "callout"})
_LEVEL_TOOLS: Final = frozenset({"fib_retracement", "fib_extension", "fib_timezone"})
_BAND_TOOLS: Final = frozenset({"anchored_vwap"})
_MAX_TEXT: Final = 1000
_MAX_LABEL: Final = 120
_TAGS: Final = frozenset({"create", "update", "delete"})

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


def _clean(value: object, *, allow_newline: bool, max_len: int) -> object:
    """Before-validator: enforce the RAW max length, reject lone surrogates, then sanitise.

    WHY the raw check comes first: the contract's JSON Schema ``maxLength`` applies to the string
    as sent. If only the sanitised length were checked, a 121-character label holding one control
    character would be schema-invalid yet accepted. (The post-sanitise min/max checks stay, as the
    sanitised text is what is stored.) Non-strings pass through to the type check.
    """
    if not isinstance(value, str):
        return value
    if len(value) > max_len:
        raise PydanticCustomError(
            "string_too_long", "String must be at most {n} characters", {"n": max_len}
        )
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


def _fail(errors: Iterable[tuple[tuple[str | int, ...], str, str]], title: str) -> None:
    """Raise one ValidationError carrying several rule-named line errors."""
    raise ValidationError.from_exception_data(
        title,
        [
            InitErrorDetails(type=PydanticCustomError(rule, msg), loc=loc, input=None)
            for loc, rule, msg in errors
        ],
    )


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
    check so every count violation reports the same ``tool_point_count`` rule. The sequences are
    ``FailFast``: validation stops at the first bad item, so a 1 MiB body of bad items yields a
    handful of errors instead of one (or two) per item (#357 review: error amplification).
    """

    model_config = _CFG
    points: Annotated[tuple[DrawingPointIn, ...], FailFast()]
    extend_left: StrictBool | None = None
    extend_right: StrictBool | None = None
    levels: (
        Annotated[
            tuple[
                Annotated[StrictFloat | StrictInt, Field(ge=-1000, le=1000, allow_inf_nan=False)],
                ...,
            ],
            FailFast(),
        ]
        | None
    ) = None
    bands: Annotated[tuple[Annotated[StrictInt, Field(ge=1, le=3)], ...], FailFast()] | None = None
    text: StrictStr | None = None

    _none_guard = field_validator(
        "extend_left", "extend_right", "levels", "bands", "text", mode="before"
    )(staticmethod(_no_null))

    @field_validator("text", mode="before")
    @classmethod
    def _clean_text(cls, v: object) -> object:
        return _clean(v, allow_newline=True, max_len=_MAX_TEXT)

    @field_validator("text", mode="after")
    @classmethod
    def _text_length(cls, v: str | None) -> str | None:
        if v is not None and not v:
            raise PydanticCustomError("text_required", "Text must not be empty")
        return v  # max already enforced on the raw string; sanitising only shortens

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


# --- drawing --------------------------------------------------------------------------------
class DrawingIn(BaseModel):
    """A full drawing as sent on create/update (PUT is full replacement)."""

    model_config = _CFG
    symbol: Annotated[StrictStr, Field(pattern=r"^[A-Z0-9]{2,16}USDT$")]
    tool: Tool
    layout_id: UUID | None = None
    geometry: DrawingGeometryIn
    style: DrawingStyleIn = Field(default_factory=DrawingStyleIn)
    label: StrictStr | None = None
    locked: StrictBool = False
    visible: StrictBool = True
    z_index: Annotated[StrictInt, Field(ge=-32768, le=32767)] = 0

    @field_validator("label", mode="before")
    @classmethod
    def _clean_label(cls, v: object) -> object:
        return _clean(v, allow_newline=False, max_len=_MAX_LABEL)

    @field_validator("label", mode="after")
    @classmethod
    def _label_length(cls, v: str | None) -> str | None:
        if v is not None and not v:
            raise PydanticCustomError(
                "string_too_short", "Label must be at least 1 character after sanitising"
            )
        return v  # max already enforced on the raw string; sanitising only shortens

    @model_validator(mode="after")
    def _tool_rules(self) -> DrawingIn:
        """Cross-field rules: point count and tool-specific keys depend on ``tool``."""
        geo, tool = self.geometry, self.tool
        errs: list[tuple[tuple[str | int, ...], str, str]] = []
        lo, hi = POINT_COUNTS[tool]
        if not lo <= len(geo.points) <= hi:
            want = f"exactly {lo}" if lo == hi else f"{lo} to {hi}"
            errs.append((("geometry", "points"), "tool_point_count", f"{tool} needs {want} points"))
        if tool in _TEXT_TOOLS:
            if geo.text is None:
                errs.append((("geometry", "text"), "text_required", f"{tool} requires text"))
        elif geo.text is not None:
            errs.append(_not_allowed("text", tool))
        if geo.levels is not None and tool not in _LEVEL_TOOLS:
            errs.append(_not_allowed("levels", tool))
        if geo.bands is not None and tool not in _BAND_TOOLS:
            errs.append(_not_allowed("bands", tool))
        if errs:
            _fail(errs, "DrawingIn")
        return self

    def db_values(self) -> dict[str, Any]:
        """Column values for the repository's ``DrawingFields`` (keys are exactly those fields).

        ``geometry`` holds only the keys the client sent, with ``p``/``t`` as the original
        strings, so reads return precisely what was written (no float round-trip of prices).
        """
        geo = self.geometry
        geometry: dict[str, Any] = {"points": [{"t": p.t, "p": p.p} for p in geo.points]}
        for key in ("extend_left", "extend_right", "text"):
            if getattr(geo, key) is not None:
                geometry[key] = getattr(geo, key)
        if geo.levels is not None:
            geometry["levels"] = list(geo.levels)
        if geo.bands is not None:
            geometry["bands"] = list(geo.bands)
        start, end = anchors(geo.points)
        return {
            "symbol": self.symbol,
            "layout_id": self.layout_id,
            "tool": self.tool,
            "geometry": geometry,
            "style": self.style.model_dump(exclude_unset=True),
            "label": self.label,
            "locked": self.locked,
            "visible": self.visible,
            "z_index": self.z_index,
            "anchor_start": start,
            "anchor_end": end,
        }


def _not_allowed(key: str, tool: str) -> tuple[tuple[str | int, ...], str, str]:
    return (
        ("geometry", key),
        "property_not_allowed_for_tool",
        f"{key} is not allowed for {tool}",
    )


# --- batch ----------------------------------------------------------------------------------
_TOKEN_RE: Final = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")


def _token_str(v: object) -> object:
    """Require ``if_match`` to be the exact server token: 6 fractional digits and ``Z``.

    WHY: the token is the row's ``updated_at`` as the server serialises it. Accepting other
    spellings (milliseconds, ``+00:00``, unix epoch numbers) would let a client send a value
    that parses to the same instant yet is not what the server issued, blurring the contract.
    The pattern is checked on the raw string; pydantic then parses it to an aware datetime.
    """
    if not isinstance(v, str):
        raise PydanticCustomError("string_type", "Input should be a string")
    if not _TOKEN_RE.fullmatch(v):
        raise PydanticCustomError(
            "string_pattern_mismatch", "if_match must look like YYYY-MM-DDTHH:MM:SS.ffffffZ"
        )
    return v


class BatchCreateIn(BaseModel):
    """Create op; the id is optional (the server mints one when absent)."""

    model_config = _CFG
    op: Literal["create"]
    id: UUID | None = None
    drawing: DrawingIn


class BatchUpdateIn(BaseModel):
    """Update op: full replacement guarded by the previous ``updated_at`` token."""

    model_config = _CFG
    op: Literal["update"]
    id: UUID
    if_match: AwareDatetime
    drawing: DrawingIn

    _str_only = field_validator("if_match", mode="before")(staticmethod(_token_str))


class BatchDeleteIn(BaseModel):
    """Delete op, guarded by the previous ``updated_at`` token."""

    model_config = _CFG
    op: Literal["delete"]
    id: UUID
    if_match: AwareDatetime

    _str_only = field_validator("if_match", mode="before")(staticmethod(_token_str))


type BatchOp = Annotated[BatchCreateIn | BatchUpdateIn | BatchDeleteIn, Field(discriminator="op")]


class BatchIn(BaseModel):
    """``POST /drawings/batch`` body: 1..200 ops, each id used at most once."""

    model_config = _CFG
    operations: tuple[BatchOp, ...]

    @field_validator("operations", mode="after")
    @classmethod
    def _count(cls, v: tuple[Any, ...]) -> tuple[Any, ...]:
        """1..200 ops (after-validator so one bad op is not also reported as 'too short')."""
        if not v:
            raise PydanticCustomError("too_short", "At least 1 operation is required")
        if len(v) > MAX_BATCH_OPS:
            raise PydanticCustomError(
                "too_long", "At most {n} operations are allowed", {"n": MAX_BATCH_OPS}
            )
        return v

    @model_validator(mode="after")
    def _unique_ids(self) -> BatchIn:
        """An id may appear once per batch: two ops on one row have no defined order of effect."""
        seen: set[UUID] = set()
        errs: list[tuple[tuple[str | int, ...], str, str]] = []
        for i, op in enumerate(self.operations):
            if op.id is None:
                continue
            if op.id in seen:
                errs.append((("operations", i, "id"), "duplicate_id", "Id used more than once"))
            seen.add(op.id)
        if errs:
            _fail(errs, "BatchIn")
        return self


# --- error formatting -----------------------------------------------------------------------
_MAX_SEGMENT: Final = 64
_MAX_MESSAGE: Final = 200
_TAG_MESSAGE: Final = "op must be one of create, update, delete"


def _clip(value: str, limit: int) -> str:
    """Sanitise (no newline) then cut to ``limit`` code points, marking the cut with an ellipsis."""
    clean = sanitize_text(value, allow_newline=False)
    return clean if len(clean) <= limit else clean[:limit] + "\u2026"


def format_errors(
    exc: ValidationError, *, limit: int = 20, prefix: str = ""
) -> list[dict[str, str]]:
    """Map a ValidationError to the API's ``errors[]`` entries (``field``, ``rule``, ``message``).

    WHY: the problem+json body must be bounded (``limit``) and must not reflect client input.
    Client-chosen text can reach an error in two places: an unknown key becomes a path segment,
    and pydantic's discriminator messages quote the offending ``op`` value. So each string
    segment is sanitised and cut to 64 code points, union-tag errors use a fixed message, and
    every message is sanitised and cut to 200. pydantic also puts the discriminator tag
    (``create``/``update``/``delete``) into ``loc`` after the list index; it is internal, so it
    is dropped to give ``operations.3.drawing.tool``.
    """
    out: list[dict[str, str]] = []
    for err in exc.errors(include_url=False, include_context=False, include_input=False)[:limit]:
        parts: list[str] = [prefix] if prefix else []
        prev: object = None
        for tok in err["loc"]:
            if not (isinstance(prev, int) and tok in _TAGS):
                parts.append(_clip(tok, _MAX_SEGMENT) if isinstance(tok, str) else str(tok))
            prev = tok
        rule = err["type"]
        msg = _TAG_MESSAGE if rule in ("union_tag_invalid", "union_tag_not_found") else err["msg"]
        out.append({"field": ".".join(parts), "rule": rule, "message": _clip(msg, _MAX_MESSAGE)})
    return out
