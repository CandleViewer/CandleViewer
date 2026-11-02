"""`api/hotkey_profiles_models.py` (E10-T05, #5211): the body judged whole, its schema refusals
named as 22 names an entry (`bindings[2].keys`), U+0000 refused before Postgres sees it, the profile
dumped as 22's closed `HotkeyProfile`, its weak ETag, and the rewrite header sent only when one
applies.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from candleviewer.api._generated.openapi_models import HotkeyProfile
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.hotkey_profiles_models import (
    MAX_BODY_BYTES,
    REWRITTEN_HEADER,
    dump,
    etag,
    judge_body,
    rewritten_header,
)
from candleviewer.api.hotkey_rules import HotkeyBindingConflict, HotkeyBindingsInvalid
from candleviewer.storage.repositories.hotkey_profiles import HotkeyProfileRow

_SPEC: Any = load_openapi_spec()
_SUBMIT = {"action": "ticket.submit", "keys": "Ctrl+Enter", "scope": "ticket"}


def _raw(bindings: list[dict[str, Any]], **body: Any) -> bytes:
    return json.dumps({"name": "Scalping", "bindings": bindings, **body}).encode("utf-8")


def _refused(raw: bytes) -> list[tuple[str, str]]:
    with pytest.raises(HotkeyBindingsInvalid) as invalid:
        judge_body(raw)
    return [(e["field"], e["rule"]) for e in invalid.value.errors]


def test_the_body_cap_is_22s_64_kib() -> None:
    assert MAX_BODY_BYTES == 64 * 1024


def test_a_body_is_judged_into_what_a_write_stores_and_what_it_rewrote() -> None:
    judged = judge_body(_raw([{**_SUBMIT, "keys": "ctrl+enter", "requires_arm": False}]))
    assert judged.fields.name == "Scalping"
    assert judged.fields.bindings == {"ticket.submit": "Ctrl+Enter"}
    assert judged.rewritten == ("ticket.submit",)


@pytest.mark.parametrize(
    ("raw", "refused"),
    [
        (b"{", [("", "json_invalid")]),
        (b"[]", [("", "model_type")]),
        (_raw([], extra=True), [("extra", "extra_forbidden")]),
        (_raw([{**_SUBMIT, "is_active": True}]), [("bindings[0].is_active", "extra_forbidden")]),
        (_raw([{**_SUBMIT, "scope": "nowhere"}]), [("bindings[0].scope", "literal_error")]),
        (_raw([{**_SUBMIT, "requires_arm": None}]), [("bindings[0].requires_arm", "value_error")]),
        (_raw([{**_SUBMIT, "confirm": "yes"}]), [("bindings[0].confirm", "bool_type")]),
        (_raw([_SUBMIT] * 201), [("bindings", "too_long")]),
        (_raw([], name=""), [("name", "string_too_short")]),
        (_raw([], name="n" * 81), [("name", "string_too_long")]),
        (_raw([{**_SUBMIT, "keys": "K" * 61}]), [("bindings[0].keys", "string_too_long")]),
        (json.dumps({"bindings": []}).encode(), [("name", "missing")]),
    ],
)
def test_a_body_off_the_schema_is_refused_by_the_check_it_fails(
    raw: bytes, refused: list[tuple[str, str]]
) -> None:
    """22: a member that breaks its schema is refused with the rule of the check it fails, before
    any rule of `bindings`; an entry is named as 22 names it."""
    assert _refused(raw) == refused


def test_schema_refusals_are_at_most_twenty() -> None:
    bindings = [{**_SUBMIT, "scope": "nowhere"} for _ in range(30)]
    assert len(_refused(_raw(bindings))) == 20


def test_u0000_is_refused_in_the_name_and_in_keys_before_any_rule() -> None:
    raw = _raw([_SUBMIT, {**_SUBMIT, "action": "no.such", "keys": "Ctrl+\x00"}], name="a\x00")
    assert _refused(raw) == [
        ("name", "invalid_character"),
        ("bindings[1].keys", "invalid_character"),
    ]
    with pytest.raises(HotkeyBindingsInvalid) as invalid:
        judge_body(raw)
    assert "\x00" not in json.dumps(invalid.value.errors)


def test_a_lone_surrogate_is_refused_by_the_parser() -> None:
    raw = b'{"name": "a\\ud800", "bindings": []}'
    assert _refused(raw) == [("", "json_invalid")]


def test_the_rules_of_bindings_and_the_conflict_run_after_the_schema() -> None:
    assert _refused(_raw([{**_SUBMIT, "keys": "Q"}])) == [
        ("bindings[0].keys", "bare_letter_dangerous")
    ]
    with pytest.raises(HotkeyBindingConflict):
        judge_body(_raw([{"action": "ticket.side_buy", "keys": "S", "scope": "ticket"}]))


def _row(**kw: Any) -> HotkeyProfileRow:
    created = datetime(2026, 10, 31, 12, 0, 0, 123456, tzinfo=UTC)
    stored = {"ticket.submit": "Ctrl+Enter", "chart.teleport": "F1", "global.palette": "Ctrl+K"}
    row = HotkeyProfileRow(uuid.UUID(int=7), uuid.UUID(int=8), "Scalping", True, stored, 3,
                           created, created + timedelta(seconds=1))  # fmt: skip
    return replace(row, **kw)


def test_dump_is_22s_closed_profile_with_bindings_derived_on_read() -> None:
    body = dump(_row())
    assert HotkeyProfile.model_validate(body).version == 3  # every member, no other
    assert set(body) == set(_SPEC["components"]["schemas"]["HotkeyProfile"]["required"])
    assert body["id"] == str(uuid.UUID(int=7)) and body["owner_user_id"] == str(uuid.UUID(int=8))
    assert [b["action"] for b in body["bindings"]] == ["global.palette", "ticket.submit"]
    submit = {"action": "ticket.submit", "keys": "Ctrl+Enter", "scope": "ticket",
              "requires_arm": True, "confirm": True}  # fmt: skip
    assert body["bindings"][1] == submit
    assert (body["created_at"], body["updated_at"]) == (
        "2026-10-31T12:00:00.123456Z", "2026-10-31T12:00:01.123456Z")  # fmt: skip


def test_dump_answers_utc_whatever_the_rows_offset() -> None:
    eastern = datetime(2026, 10, 31, 7, 0, tzinfo=timezone(timedelta(hours=-5)))
    body = dump(_row(created_at=eastern, updated_at=eastern, bindings={}))
    assert body["created_at"] == "2026-10-31T12:00:00.000000Z" and body["bindings"] == []


def test_etag_is_22s_weak_tag_of_the_id_and_the_version() -> None:
    pid = uuid.UUID("17000000-0000-4000-8000-000000000001")
    pattern = _SPEC["components"]["headers"]["HotkeyProfileETag"]["schema"]["pattern"]
    assert etag(pid, 3) == f'W/"{pid}:3"'
    assert re.fullmatch(pattern, etag(pid, 3))


def test_the_rewrite_header_names_each_action_once_and_is_sent_only_for_a_rewrite() -> None:
    created = _SPEC["paths"]["/settings/hotkeys"]["post"]["responses"]["201"]["headers"]
    assert created[REWRITTEN_HEADER] == {"$ref": "#/components/headers/HotkeyBindingsRewritten"}
    assert rewritten_header(()) == {}
    assert rewritten_header(("ticket.submit", "dom.cancel_all")) == {
        "Hotkey-Bindings-Rewritten": "ticket.submit, dom.cancel_all"
    }
