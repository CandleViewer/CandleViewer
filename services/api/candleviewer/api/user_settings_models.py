"""The `/settings` leaves (E02-T13, #5181): 22's `Settings` as a closed table of leaves, a patch
judged whole against it before anything is written, and the effective document served.

The leaves are read off the generated `Settings` model (`api/_generated`), so they are exactly
22's, and a later contract change reaches them through `make gen`. A leaf is a member of one of
`Settings`' groups, its dotted path the row's `key` (`appearance.theme`); a free-form member such as
`notifications.quiet_hours` is one leaf, its whole object the value. `_meta` is computed from the
caller's rows and never stored, and `trading.one_click_armed` is set only through
`armOneClickTrading` (SR-043), so a patch naming either is refused, as is a leaf 22's `Settings`
does not declare (E22-S02's `bigtrade` block included, until its contract lands).

A patch is a JSON object of groups, each a JSON object of leaves. A leaf's value is checked by its
generated model (type, enum, range) and stored as that model writes it; `null` resets the leaf to
the deployment default, which deletes the caller's override. The body passes the input hygiene
first: no NaN or infinity, no nesting past `_MAX_DEPTH`, and no U+0000 or lone surrogate in a
string or a key, which `jsonb` cannot store. Every refusal is listed (at most `_MAX_ERRORS`), a key
the client sent echoed only when it has a leaf name's shape, and never a value.

Reading Q1 of #5181: no deployment default set exists, so the effective settings are the caller's
overrides alone and the client applies its built-in default to every other leaf. `effective()` is
the one place a default set would be overlaid. A stored row that 22's `Settings` no longer accepts
(a later contract delta) is left out of the answer and logged by its key, never served.

Q3 of #5181, as ruled: `notifications.webhook_url` is a credential-bearing URL that may embed a
token (21 Sec.12), stored as a plain row and answered in full to its owner only. `masked()` is
the one place its value is reduced, to its scheme and host: for the `settings.change` record's
before and after, and for a view-as read, whose reader is not the owner.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, get_args
from urllib.parse import urlsplit

import structlog
from pydantic import BaseModel, ValidationError

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.drawings_models import format_errors
from candleviewer.domain.text import unpaired_surrogate
from candleviewer.observability.redaction import redact_structure
from candleviewer.storage.repositories.user_settings import UserSetting

#: The whole `Settings` object is far below this; anything over it is no settings patch.
MAX_BODY_BYTES: Final = 16 * 1024
#: The body, a group, a leaf, and a free-form value's own nesting below it.
_MAX_DEPTH: Final = 8
_MAX_ERRORS: Final = 20
META: Final = "_meta"
#: 22 `updateSettings`: set only through `armOneClickTrading` (SR-043), never through a patch.
READ_ONLY: Final = frozenset({"trading.one_click_armed"})
#: The credential-class leaves (21 Sec.12): their values leave their owner only as `masked()`.
MASKED_LEAVES: Final = frozenset({"notifications.webhook_url"})
#: A masked value's elided part, and the whole of a value with no scheme and host to keep.
ELIDED: Final = "…"
_NAME: Final = re.compile(r"[a-z0-9_]{1,64}")


@dataclass(frozen=True, slots=True)
class Leaf:
    """A leaf of 22's `Settings`: the generated group model that checks it, and its member."""

    model: type[BaseModel]
    field: str


def _group_model(annotation: object) -> type[BaseModel]:
    """The generated model of a `Settings` group (`Appearance | None` is `Appearance`)."""
    for candidate in (annotation, *get_args(annotation)):
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    raise TypeError(f"a Settings group that is no object: {annotation!r}")  # fails at import


def _declared() -> dict[str, Leaf]:
    found: dict[str, Leaf] = {}
    for name, member in api.Settings.model_fields.items():
        group = member.alias or name
        if group != META:
            model = _group_model(member.annotation)
            found |= {f"{group}.{leaf}": Leaf(model, leaf) for leaf in model.model_fields}
    return found


#: Every leaf 22's `Settings` declares, by dotted path.
LEAVES: Final[Mapping[str, Leaf]] = MappingProxyType(_declared())
GROUPS: Final = frozenset(key.partition(".")[0] for key in LEAVES)


class PatchRefused(Exception):
    """The patch breaks 22's `Settings`: `errors` are the contract's `errors[]` entries."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("the settings patch is invalid")
        self.errors = errors


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.user_settings")


def _error(field: str, rule: str, message: str) -> dict[str, str]:
    return {"field": field, "rule": rule, "message": message}


def _refused(rule: str, message: str) -> PatchRefused:
    return PatchRefused([_error("", rule, message)])


def _shown(*names: str) -> str:
    """The dotted path of names the client sent, cut at the first that has no leaf name's shape."""
    shown: list[str] = []
    for name in names:
        if not _NAME.fullmatch(name):
            break
        shown.append(name)
    return ".".join(shown)


def _hygiene(doc: object) -> str | None:
    """The input-hygiene rule a parsed body breaks, if any, walked with an explicit stack."""
    stack: list[tuple[object, int]] = [(doc, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > _MAX_DEPTH or (isinstance(node, float) and not math.isfinite(node)):
            return "json_invalid"  # `1e999` parses to infinity
        if isinstance(node, str) and ("\x00" in node or unpaired_surrogate(node)):
            return "invalid_character"
        if isinstance(node, dict):
            stack += [(part, depth + 1) for item in node.items() for part in item]
        elif isinstance(node, list):
            stack += [(part, depth + 1) for part in node]
    return None


def _no_constant(name: str) -> object:
    raise ValueError(name)  # NaN, Infinity and -Infinity are not JSON (RFC 8259)


def canonical(leaf: Leaf, value: object) -> object:
    """`value` as the leaf's generated model writes it; `ValidationError` when it refuses it."""
    return leaf.model.model_validate({leaf.field: value}).model_dump(mode="json")[leaf.field]


def _judge_group(group: str, members: dict[str, object], out: dict[str, object]) -> list[Any]:
    errors: list[Any] = []
    for name, value in members.items():
        key, leaf = f"{group}.{name}", LEAVES.get(f"{group}.{name}")
        if leaf is None:
            errors.append(_error(_shown(group, name), "extra_forbidden", "Not a leaf of Settings."))
        elif key in READ_ONLY:
            errors.append(_error(key, "read_only", "Set through POST /settings/arm only."))
        elif value is None:
            out[key] = None  # reset to the deployment default
        else:
            try:
                out[key] = canonical(leaf, value)
            except ValidationError as exc:
                errors += redact_structure(format_errors(exc, prefix=group))
    return errors


def judge_patch(raw: bytes) -> dict[str, object]:
    """The patch as leaf path -> the value to store, or `None` to reset it; `PatchRefused` with
    every refusal when anything in it is wrong, so nothing of it is written."""
    try:
        doc: object = json.loads(raw, parse_constant=_no_constant)
    except (ValueError, RecursionError):  # the parser's own nesting limit included
        raise _refused("json_invalid", "The body is not a JSON document.") from None
    if (rule := _hygiene(doc)) is not None:
        raise _refused(rule, "The body holds a value no setting can store.")
    if not isinstance(doc, dict):
        raise _refused("model_type", "The body must be a JSON object of settings groups.")
    errors: list[Any] = []
    out: dict[str, object] = {}
    for group, members in doc.items():
        if group == META:
            errors.append(_error(META, "read_only", "Computed by the server, never written."))
        elif group not in GROUPS:
            errors.append(_error(_shown(group), "extra_forbidden", "Not a group of Settings."))
        elif not isinstance(members, dict):
            errors.append(_error(group, "model_type", "A group must be a JSON object."))
        else:
            errors += _judge_group(group, members, out)
    if errors:
        raise PatchRefused(errors[:_MAX_ERRORS])
    return out


def masked(key: str, value: object) -> object:
    """`value` of leaf `key` as it may leave its owner. A leaf outside `MASKED_LEAVES`, `None` (no
    override) and `""` are as they are. Any other value of a credential-class leaf keeps only its
    scheme and host, as `scheme://host/…` (the host as `urlsplit` reads it, lower case, an IPv6
    host in its brackets), so its userinfo, port, path, query and fragment, where a token sits,
    never leave; a value with no scheme or no host, or not a string, is `…`."""
    if key not in MASKED_LEAVES or value is None or value == "":
        return value
    if not isinstance(value, str):
        return ELIDED
    try:
        parts = urlsplit(value)
        host = parts.hostname
    except ValueError:  # an unclosed `[` or a bracketed host that is no IP address
        return ELIDED
    if not parts.scheme or not host:
        return ELIDED
    return f"{parts.scheme}://{f'[{host}]' if ':' in host else host}/{ELIDED}"


def effective(rows: Iterable[UserSetting], *, viewing: bool) -> dict[str, Any]:
    """22's `Settings` from the caller's rows (reading Q1: no default set to overlay them on), with
    `_meta`: the leaves that came from the caller, and the latest write among them. `viewing`: the
    reader views as the rows' owner and is not them, so each credential-class leaf is `masked()`."""
    groups: dict[str, dict[str, object]] = {}
    overridden: list[str] = []
    latest: datetime | None = None
    for row in rows:
        leaf = LEAVES.get(row.key)
        try:
            if leaf is None or row.value is None:
                raise LookupError(row.key)
            value = canonical(leaf, row.value)
        except (LookupError, ValidationError):
            _log().warning("user_settings_row_not_served", key=row.key)  # the key, never a value
            continue
        group, _, name = row.key.partition(".")
        groups.setdefault(group, {})[name] = masked(row.key, value) if viewing else value
        overridden.append(row.key)
        latest = row.updated_at if latest is None else max(latest, row.updated_at)
    meta: dict[str, object] = {"overridden": sorted(overridden)}
    if latest is not None:
        meta["updated_at"] = latest
    shown = api.Settings.model_validate({**groups, META: meta})
    return shown.model_dump(mode="json", by_alias=True, exclude_unset=True)
