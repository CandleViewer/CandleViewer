"""Request validation for ``/workspaces`` (E15-T01 slice S2a; spec D1, D8-D11, D17).

WHY a pure module: the router, the repository and the OpenAPI contract must agree on one
definition of "a valid workspace". No I/O, router or storage import lives here, so the rules are
unit-tested exhaustively and reused unchanged by POST and PUT. The layout models arrive in S2b.

Security posture (C-12.1, ticket Security notes): every model is closed and frozen; names are
length-checked raw and sanitised (control/bidi characters removed) before storage; ``icon_token``
is a closed allow-list, never a URL. Existence and ownership are the router's job.
``sanitize_text`` comes from ``drawings_models`` (one definition); the router imports
``format_errors`` and ``MAX_JSON_DEPTH`` from there directly.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal, get_args

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, StrictStr
from pydantic_core import PydanticCustomError

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

_CFG: Final = ConfigDict(frozen=True, extra="forbid")


def sanitize_name(value: str) -> str:
    """Sanitise then trim (D8). WHY the trim: names are identifiers with case-insensitive
    uniqueness, so "Scalping" and "Scalping " must not both exist."""
    return sanitize_text(value, allow_newline=False).strip()


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
