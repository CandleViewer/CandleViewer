"""`HotkeyProfileInput` and `HotkeyProfile` (22) for `/settings/hotkeys` (E10-T05, #5211): the
closed body a create or a replace is judged by, and the closed profile every answer carries.

Pure: no I/O. The body's shape is 22's own generated `HotkeyProfileInput` (`api/_generated`, closed
since BQ-1, so a member it does not declare is `extra_forbidden`), as the settings leaves read
theirs; a body that breaks it is refused with the rule of the check it fails, at most 20 items,
before any rule of `bindings` (`hotkey_rules`) is judged. `name` and each binding's `keys` must hold
no U+0000, which Postgres `text` and `jsonb` cannot store (`invalid_character`; the parser already
refuses a lone surrogate). The `errors[]` fields name an entry as 22 does, `bindings[2].keys`. A
body past `MAX_BODY_BYTES` is the router's `413`, refused before it is parsed.

`dump` is 22's `HotkeyProfile`, every member answered, the bindings derived on read; `etag` is
`HotkeyProfileETag`; `rewritten_header` is `Hotkey-Bindings-Rewritten`, sent only when the judge
rewrote an action's `requires_arm` or `confirm` (BQ-3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from pydantic import ValidationError

from candleviewer.api._generated.openapi_models import HotkeyProfileInput
from candleviewer.api.drawings_models import format_errors
from candleviewer.api.hotkey_rules import (
    HotkeyBindingsInvalid,
    Judged,
    Vocabulary,
    judge,
    read_bindings,
)
from candleviewer.observability.redaction import redact_structure
from candleviewer.storage.repositories.hotkey_profiles import HotkeyProfileFields, HotkeyProfileRow

#: 22's body cap on `createHotkeyProfile` and `updateHotkeyProfile`: past it, `413`.
MAX_BODY_BYTES: Final = 64 * 1024
#: 22 `HotkeyBindingsRewritten`: the response header naming the rewritten actions.
REWRITTEN_HEADER: Final = "Hotkey-Bindings-Rewritten"
_INDEX: Final = re.compile(r"\.([0-9]+)(?=\.|$)")
_UNSTORABLE: Final = "Must not hold U+0000."


@dataclass(frozen=True, slots=True)
class JudgedProfile:
    """What a create inserts or a replace sets, and the actions the judge rewrote (BQ-3)."""

    fields: HotkeyProfileFields
    rewritten: tuple[str, ...]


def _bracketed(field: str) -> str:
    """`bindings.2.keys` as 22 names it, `bindings[2].keys`."""
    return _INDEX.sub(r"[\1]", field)


def judge_body(raw: bytes, vocabulary: Vocabulary | None = None) -> JudgedProfile:
    """The body as what a write stores; `HotkeyBindingsInvalid` (`422`) when its shape, its text or
    a rule of `bindings` refuses it, `HotkeyBindingConflict` (`409 binding_conflict`) when two of
    its bindings share a key while both can be live (`hotkey_rules.judge`)."""
    try:
        body = HotkeyProfileInput.model_validate_json(raw)
    except ValidationError as exc:
        found = redact_structure(format_errors(exc))
        raise HotkeyBindingsInvalid(
            [{**item, "field": _bracketed(item["field"])} for item in found]
        ) from None
    unstorable = [
        {"field": field, "rule": "invalid_character", "message": _UNSTORABLE}
        for field, text in [("name", body.name)]
        + [(f"bindings[{n}].keys", b.keys) for n, b in enumerate(body.bindings)]
        if "\x00" in text
    ]
    if unstorable:
        raise HotkeyBindingsInvalid(unstorable[:20])
    judged: Judged = judge(body.bindings, vocabulary)
    return JudgedProfile(HotkeyProfileFields(body.name, judged.stored), judged.rewritten)


def rewritten_header(rewritten: tuple[str, ...]) -> dict[str, str]:
    """`Hotkey-Bindings-Rewritten` when the judge rewrote at least one action, else nothing."""
    return {REWRITTEN_HEADER: ", ".join(rewritten)} if rewritten else {}


def etag(profile_id: UUID, version: int) -> str:
    """22 `HotkeyProfileETag`."""
    return f'W/"{profile_id}:{version}"'


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def dump(row: HotkeyProfileRow, vocabulary: Vocabulary | None = None) -> dict[str, Any]:
    """22 `HotkeyProfile`: exactly its members, the bindings as `read_bindings` derives them."""
    return {
        "id": str(row.id), "owner_user_id": str(row.owner_user_id), "name": row.name,
        "bindings": read_bindings(row.bindings, vocabulary), "is_active": row.is_active,
        "version": row.version, "created_at": _stamp(row.created_at),
        "updated_at": _stamp(row.updated_at),
    }  # fmt: skip


__all__ = [
    "MAX_BODY_BYTES", "REWRITTEN_HEADER", "JudgedProfile", "dump", "etag", "judge_body",
    "rewritten_header",
]  # fmt: skip
