"""Request validation for `/indicator-presets` (E13-T03, #427): 22 `IndicatorPresetInput`.

Pure (no I/O, no routing): the router, the service and the bundle import share this one
definition of a valid preset, so the HTTP path and an import cannot drift (IR-06, IR-10).

1. `PresetInput` is the closed, frozen DTO: `extra="forbid"` refuses `id`, `owner_user_id`,
   `is_builtin`, `created_at`, `updated_at`, `deleted_at` and every other unknown property
   (IR-10, AC-04). `name` is at most 80 characters as sent, refused with a lone surrogate, then
   sanitised and trimmed as a workspace name is (`workspaces_models.sanitize_name`); empty
   after that is `string_too_short`. An `indicator_code` outside `^[a-z0-9_]{2,32}$` is
   `invalid_indicator_code`, whose message never echoes the value (AC-06). `pane_target` is
   `overlay` or `subpane`; `style` defaults to `{}`, `is_favourite` to false.
2. `preset_fields()` checks what needs the catalogue, one error per field at most:
   - the SR-E13-06 bounds of `params` and `style` (keys, then nesting depth, then bytes as
     Postgres prints jsonb, the text the CHECKs `ip_params_shape` / `ip_style_shape` measure),
     first, on the values as sent: a NaN, an infinity or a 1e400 is measured, never encoded;
   - registry membership (`unknown_indicator`, IR-08), then `validate_params` (SR-E13-01: the
     first defect in the descriptor's order, never clamped, IR-07), which a `params` past its
     bounds never reaches: a catalogue's parameters are a few flat scalars, so after
     `validate_params` no `params_too_*` rule could fire;
   - the closed style vocabulary (`style_not_allowed`, SR-E13-08).
   It returns the `PresetFields` the store keeps: `params` complete and canonical (an omitted
   parameter at its default, so a later default change never alters a saved preset).

Messages name the bound and the parameter's title (SCR-035: "Period must be between 1 and
5000."), never a submitted value or key (IR-24); `field` is `params.<name>` for a parameter.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator
from pydantic_core import PydanticCustomError

from candleviewer.api.indicator_style_vocabulary import style_defect
from candleviewer.api.workspaces_models import sanitize_name
from candleviewer.orderflow.errors import InvalidParamsError
from candleviewer.orderflow.indicators.catalogue import (
    IndicatorCatalogue,
    IndicatorDef,
    ParamSpec,
    json_params,
    validate_params,
)
from candleviewer.orderflow.indicators.limits import (
    PRESET_JSON_MAX_BYTES,
    PRESET_JSON_MAX_DEPTH,
    PRESET_JSON_MAX_KEYS,
    PRESET_NAME_MAX,
)
from candleviewer.storage.repositories.indicator_presets import PresetFields

#: 22 `IndicatorPresetInput.indicator_code.pattern` and the CHECK `ip_code`.
INDICATOR_CODE_PATTERN: Final = r"^[a-z0-9_]{2,32}$"
_CODE: Final = re.compile(INDICATOR_CODE_PATTERN)
_CFG: Final = ConfigDict(frozen=True, extra="forbid")

PaneTarget = Literal["overlay", "subpane"]


class PresetInvalidError(Exception):
    """422 `validation_failed`; `errors` are the contract's `{field, rule, message}` items."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__(f"{len(errors)} invalid preset field(s)")
        self.errors = errors


class PresetInput(BaseModel):
    """22 `IndicatorPresetInput`: a whole preset as a create, a replace (`PUT` is a full
    replacement: an omitted field takes its default) or a bundle item sends it."""

    model_config = _CFG
    name: StrictStr
    indicator_code: StrictStr
    params: dict[str, Any]
    style: dict[str, Any] = Field(default_factory=dict)
    pane_target: PaneTarget = "overlay"
    is_favourite: StrictBool = False

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value: object) -> object:
        """The raw length first (the contract's `maxLength` applies as sent), then a lone
        surrogate, then sanitise and trim; a non-string passes on to the type check."""
        if not isinstance(value, str):
            return value
        if len(value) > PRESET_NAME_MAX:
            raise PydanticCustomError(
                "string_too_long", "String must be at most {n} characters", {"n": PRESET_NAME_MAX}
            )
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise PydanticCustomError(
                "invalid_unicode", "String is not valid Unicode (lone surrogate)"
            ) from None
        clean = sanitize_name(value)
        if not clean:  # the contract's rule name, not pydantic's own
            raise PydanticCustomError("string_too_short", "String must have at least 1 character")
        return clean

    @field_validator("indicator_code", mode="before")
    @classmethod
    def _code_shape(cls, value: object) -> object:
        if isinstance(value, str) and not _CODE.fullmatch(value):
            raise PydanticCustomError(
                "invalid_indicator_code",
                "indicator_code must be 2 to 32 lowercase letters, digits or underscores",
            )
        return value


def jsonb_text_bytes(value: object) -> int:
    """`octet_length(<value>::text)` of `value` stored as jsonb: Postgres prints an object with
    `", "` and `": "` separators and non-ASCII as UTF-8. A non-finite number or a lone surrogate
    (possible in a bundle item decoded by `json.loads`) is measured, not refused: validation
    refuses it."""
    text = json.dumps(value, ensure_ascii=False, separators=(", ", ": "), allow_nan=True)
    return len(text.encode("utf-8", "surrogatepass"))


def json_depth(value: object) -> int:
    """Nesting depth: a scalar is 0, an object or an array one more than its deepest member.
    Iterative, so a deeply nested bundle item cannot exhaust the stack."""
    deepest, stack = 0, [(value, 1)]
    while stack:
        node, level = stack.pop()
        if isinstance(node, dict):
            members: Any = node.values()
        elif isinstance(node, list):
            members = node
        else:
            continue
        deepest = max(deepest, level)
        stack.extend((member, level + 1) for member in members)
    return deepest


def _bound_breached(value: Mapping[str, object]) -> tuple[str, str] | None:
    """(rule suffix, what the field must be) of the first SR-E13-06 bound `value` breaks:
    keys, then depth, then bytes."""
    if len(value) > PRESET_JSON_MAX_KEYS:
        return "too_many_keys", f"have at most {PRESET_JSON_MAX_KEYS} keys"
    if json_depth(value) > PRESET_JSON_MAX_DEPTH:
        return "too_deep", f"nest at most {PRESET_JSON_MAX_DEPTH} levels deep"
    if jsonb_text_bytes(value) > PRESET_JSON_MAX_BYTES:
        return "too_large", f"be at most {PRESET_JSON_MAX_BYTES} bytes"
    return None


def _rule(field: str, rule: str, message: str) -> dict[str, str]:
    return {"field": field, "rule": rule, "message": message}


def _param_message(spec: ParamSpec, rule: str) -> str:
    """SCR-035's wording, by the parameter's title: the bound, never the value."""
    if rule in ("minimum", "maximum"):
        return f"{spec.title} must be between {spec.minimum} and {spec.maximum}."
    if rule == "multipleOf":
        return f"{spec.title} must be a multiple of {spec.multiple_of}."
    if rule == "enum":
        return f"{spec.title} must be one of: {', '.join(spec.enum)}."
    return f"{spec.title} must be a {'whole number' if spec.type == 'integer' else 'number'}."


def _param_error(
    definition: IndicatorDef, exc: InvalidParamsError, at: Callable[[str], str]
) -> dict[str, str]:
    """The catalogue's first defect as an error item: a pointer `/<name>` names a declared
    parameter (`params.<name>`); `""` is the object as a whole (an undeclared key), whose
    message lists the declared parameters, never the submitted key."""
    name = exc.pointer.removeprefix("/")
    if not name:
        return _rule(at("params"), exc.rule, str(exc))
    spec = next(p for p in definition.params if p.name == name)
    return _rule(at(f"params.{name}"), exc.rule, _param_message(spec, exc.rule))


def preset_fields(
    body: PresetInput, catalogue: IndicatorCatalogue, *, prefix: str = ""
) -> PresetFields:
    """`body` checked against the catalogue and the vocabulary (module docstring, step 2), as
    the store keeps it; `PresetInvalidError` with every field's first defect otherwise. `prefix`
    roots each `field` (`indicator_presets.<i>` for a bundle item)."""

    def at(field: str) -> str:
        return f"{prefix}.{field}" if prefix else field

    errors: list[dict[str, str]] = []
    params_bound = _bound_breached(body.params)
    if params_bound is not None:
        suffix, must = params_bound
        errors.append(_rule(at("params"), f"params_{suffix}", f"params must {must}."))
    definition = catalogue.get(body.indicator_code)
    params: dict[str, Any] = {}
    if definition is None:
        message = "indicator_code names no indicator of the catalogue."
        errors.append(_rule(at("indicator_code"), "unknown_indicator", message))
    elif params_bound is None:
        try:
            params = json_params(validate_params(definition, body.params))
        except InvalidParamsError as exc:
            errors.append(_param_error(definition, exc, at))
    style_bound = _bound_breached(body.style)
    style_problem = f"style must {style_bound[1]}." if style_bound else style_defect(body.style)
    if style_problem is not None:
        errors.append(_rule(at("style"), "style_not_allowed", style_problem))
    if errors:
        raise PresetInvalidError(errors)
    return PresetFields(
        body.indicator_code, body.name, params, dict(body.style), body.pane_target,
        body.is_favourite,
    )  # fmt: skip


__all__ = [
    "INDICATOR_CODE_PATTERN", "PaneTarget", "PresetInput", "PresetInvalidError", "json_depth",
    "jsonb_text_bytes", "preset_fields",
]  # fmt: skip
