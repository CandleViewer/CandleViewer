"""The profile writes' request edge (E28-T02 #906, slice D2-3; the D2 spec, Sec.6.3): the body
under its cap, its JSON, the generated model's entries, the `name` code-point check, `If-Match`,
the `Idempotency-Key`, and the codes the writes answer. No I/O: a request is a bare ASGI scope
whose body a scripted `receive` hands over chunk by chunk.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from pydantic import BaseModel, ValidationError, field_validator

from candleviewer.accounts.profile_input import ProfileFieldError, schema_errors
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.profile_body import (
    MAX_BINDING_BODY_BYTES,
    MAX_PROFILE_BODY_BYTES,
    MODEL_ERRORS_SHOWN,
    BodyTooLarge,
    IfMatchMissing,
    IfMatchRefused,
    Refused,
    decode,
    idempotency,
    if_match_version,
    model_errors,
    name_errors,
    read_capped,
    refused,
)
from candleviewer.api.profiles import problem
from tests.contract._admin_support import SPEC

_PROFILE = UUID("0b5f6d0e-28a1-4c1e-9e01-000000000001")
_BINDING = "7d3c9a10-28a1-4c1e-9e01-0000000000a1:default"
_PLANTED = "AbCdEfGhIjKlMnOpQrSt12"  # key-shaped: `redact_text` masks it
_VALID = {"name": "Swing", "leverage": "2", "sizing": {"mode": "fixed_qty", "qty": "1"}}


def _request(
    *headers: tuple[str, str], chunks: Sequence[bytes] = (b"",)
) -> tuple[Request, list[int]]:
    """A request with `headers` whose body arrives as `chunks`; the list grows with each read."""
    reads: list[int] = []

    async def receive() -> dict[str, Any]:
        reads.append(len(reads))
        more = len(reads) < len(chunks)
        return {"type": "http.request", "body": chunks[len(reads) - 1], "more_body": more}

    pairs = [(name.encode(), value.encode()) for name, value in headers]
    return Request({"type": "http", "method": "PUT", "headers": pairs}, receive), reads


@pytest.mark.parametrize("cap", [MAX_PROFILE_BODY_BYTES, MAX_BINDING_BODY_BYTES])
async def test_a_body_past_its_cap_is_refused_before_it_is_buffered(cap: int) -> None:
    """413 (22: over 64 KiB for a profile, over 1 KiB for the binding): a declared length past the
    cap is refused unread, a stream at the chunk that passes it; exactly the cap is read whole."""
    declared, reads = _request(("content-length", str(cap + 1)), chunks=[b"{}"])
    with pytest.raises(BodyTooLarge) as ei:
        await read_capped(declared, cap)
    assert ei.value.cap == cap and reads == []
    half = b" " * (cap // 2)
    streamed, reads = _request(chunks=[half, half, b"x", b"never read"])
    with pytest.raises(BodyTooLarge):
        await read_capped(streamed, cap)
    assert len(reads) == 3
    exact, _ = _request(("content-length", str(cap)), chunks=[half, half])
    assert await read_capped(exact, cap) == half * 2


@pytest.mark.parametrize(
    ("raw", "rule"),
    [
        (b'{"name": "\xff"}', "json_invalid"),
        (b"{", "json_invalid"),
        (b'{"leverage": NaN}', "json_invalid"),
        (b'{"leverage": Infinity}', "json_invalid"),
        (b'{"leverage": -Infinity}', "json_invalid"),
        (b'{"slippage_tolerance_bps": ' + b"1" * 5000 + b"}", "json_invalid"),
        (b"[" * 9 + b"]" * 9, "json_too_deep"),
        (b"[" * 100_000, "json_too_deep"),  # past the recursion limit: never decoded
    ],
    ids=["not-utf8", "truncated", "nan", "infinity", "minus-infinity", "5000-digits", "depth-9",
         "depth-100000"],
)  # fmt: skip
def test_a_body_that_is_not_utf8_json_or_nests_too_deep_is_refused_with_one_entry(
    raw: bytes, rule: str
) -> None:
    """C1, U2 and B2: one entry at the body (the binding's is `body`), naming no value."""
    for field, noun in (("", "member"), ("body", "field")):
        with pytest.raises(Refused) as ei:
            decode(raw, field=field)
        assert [(e.field, e.rule) for e in ei.value.errors] == [(field, rule)]
        assert ei.value.detail == f"1 {noun} failed validation."
    assert decode(b"[" * 8 + b"]" * 8) == [[[[[[[[]]]]]]]]
    assert decode('{"name": "Zürich"}'.encode()) == {"name": "Zürich"}


def test_the_models_entries_are_capped_and_echo_no_value() -> None:
    """B1 Sec.3: the model's first 20 entries, then B1's own (`native_stop_mandatory`), never
    cut; no planted value reaches an entry."""
    raw = {**_VALID, "name": _PLANTED * 4, "leverage": _PLANTED, "margin_mode": _PLANTED,
           "allowed_symbols": [_PLANTED] * 30, "require_native_stop": False}  # fmt: skip
    with pytest.raises(ValidationError) as ei:
        api.AccountProfileInput.model_validate(raw)
    shown = model_errors(ei.value)
    assert ei.value.error_count() > 30 and len(shown) == MODEL_ERRORS_SHOWN
    entries = refused(schema_errors(raw, shown)).errors
    assert len(entries) == MODEL_ERRORS_SHOWN + 1
    assert (entries[-1].field, entries[-1].rule) == ("require_native_stop", "native_stop_mandatory")
    assert _PLANTED not in json.dumps([e.to_dict() for e in entries])


class _Echoes(BaseModel):
    """A validator that writes its input into its message, as a `value_error` may."""

    key: str

    @field_validator("key")
    @classmethod
    def _refuse(cls, value: str) -> str:
        raise ValueError(f"cannot take {value}")


def test_every_model_message_passes_the_redaction_rules() -> None:
    """C-12.6: a message that carries its input is redacted before it is answered."""
    with pytest.raises(ValidationError) as ei:
        _Echoes.model_validate({"key": _PLANTED})
    (entry,) = model_errors(ei.value, prefix="body")
    assert (entry.field, entry.rule) == ("body.key", "value_error")
    assert _PLANTED not in entry.message and "[redacted:key-shape]" in entry.message


def test_an_unknown_member_is_named_at_its_parent_never_by_its_key() -> None:
    """#4147 R1S-02: the key is the client's own text, so its entry names the member that holds
    it; a 100 000-character key leaves a problem body under 4 KB."""
    key = "k" * 100_000
    nested = {**_VALID, "stop_loss": {"unit": "ticks", "value": "1", key: 1}}
    cases: list[tuple[type[BaseModel], dict[str, Any], str, str]] = [
        (api.AccountProfileInput, {**_VALID, key: 1}, "", ""),
        (api.AccountProfileInput, nested, "", "stop_loss"),
        (api.AccountDefaultBindingInput, {"profile_id": str(uuid4()), key: 1}, "body", "body"),
    ]
    for model, raw, prefix, field in cases:
        with pytest.raises(ValidationError) as ei:
            model.model_validate(raw)
        entries = model_errors(ei.value, prefix=prefix)
        assert [(e.field, e.rule) for e in entries] == [(field, "extra_forbidden")]
        errors = [e.to_dict() for e in entries]
        answer = problem("validation_failed", refused(entries, noun="field").detail, errors=errors)
        assert len(answer.body) < 4096 and key.encode() not in answer.body
    with pytest.raises(ValidationError) as named:
        api.AccountDefaultBindingInput.model_validate({"profile_id": "Swing"})
    put = SPEC["paths"]["/exchange-accounts/{accountId}/default-profile"]["put"]
    example = put["responses"]["422"]["content"]["application/problem+json"]["examples"]
    assert [e.to_dict() for e in model_errors(named.value, prefix="body")] == example[
        "notAProfileId"
    ]["value"]["errors"]


_TAG = f'W/"{_PROFILE}:3"'


@pytest.mark.parametrize(
    ("sent", "resource", "answer"),
    [
        ([], str(_PROFILE), IfMatchMissing),
        ([_TAG], str(_PROFILE), 3),
        ([f"  {_TAG} "], str(_PROFILE), 3),
        ([f'W/"{_PROFILE}:{"9" * 19}"'], str(_PROFILE), int("9" * 19)),
        ([f'W/"{_BINDING}:7"'], _BINDING, 7),
        (["*"], str(_PROFILE), IfMatchRefused),
        ([f'{_TAG}, W/"{_PROFILE}:4"'], str(_PROFILE), IfMatchRefused),
        ([_TAG, _TAG], str(_PROFILE), IfMatchRefused),
        ([f'"{_PROFILE}:3"'], str(_PROFILE), IfMatchRefused),
        ([f'w/"{_PROFILE}:3"'], str(_PROFILE), IfMatchRefused),
        ([f'W/"{uuid4()}:3"'], str(_PROFILE), IfMatchRefused),
        ([f'W/"{_PROFILE}:default:3"'], str(_PROFILE), IfMatchRefused),
        ([f'W/"{_BINDING.removesuffix(":default")}:3"'], _BINDING, IfMatchRefused),
        ([f'W/"{uuid4()}:default:3"'], _BINDING, IfMatchRefused),
        ([f'W/"{_PROFILE}:0"'], str(_PROFILE), IfMatchRefused),
        ([f'W/"{_PROFILE}:03"'], str(_PROFILE), IfMatchRefused),
        ([f'W/"{_PROFILE}:{"9" * 20}"'], str(_PROFILE), IfMatchRefused),
        ([f'{_TAG}x'], str(_PROFILE), IfMatchRefused),
        ([f'W/"{str(_PROFILE).upper()}:3"'], str(_PROFILE), IfMatchRefused),
        ([""], str(_PROFILE), IfMatchRefused),
    ],
    ids=["missing", "tag", "padded", "19-digits", "binding", "star", "list", "two-headers",
         "strong", "lower-w", "another-profile", "binding-tag-to-profile", "profile-tag-to-binding",
         "another-account", "version-0", "leading-zero", "20-digits", "trailing", "upper-hex",
         "empty"],
)  # fmt: skip
def test_if_match_names_one_version_of_this_resource(
    sent: list[str], resource: str, answer: int | type[Exception]
) -> None:
    """U1, D1 and B1: 428 without the header; 412 for anything but one weak tag of this resource
    (`IfMatchRequired`), so a tag never matches another resource's version."""
    request, _ = _request(*(("if-match", value) for value in sent))
    if isinstance(answer, int):
        assert if_match_version(request, resource) == answer
    else:
        with pytest.raises(answer):
            if_match_version(request, resource)


def test_the_idempotency_key_is_a_uuid_or_refused_unechoed() -> None:
    """H6: `operationId:<uuid>` in its canonical form, `None` without a key, 422 for another."""
    key = uuid4()
    request, _ = _request(("idempotency-key", str(key).upper()))
    assert idempotency(request, "createAccountProfile") == f"createAccountProfile:{key}"
    assert idempotency(_request()[0], "createAccountProfile") is None
    with pytest.raises(Refused) as ei:
        idempotency(_request(("idempotency-key", _PLANTED))[0], "createAccountProfile")
    assert [(e.field, e.rule) for e in ei.value.errors] == [("Idempotency-Key", "uuid_parsing")]
    assert ei.value.detail == "1 field failed validation." and _PLANTED not in str(ei.value.errors)


@pytest.mark.parametrize(
    "name",
    ["Alpha\x7f", "Alpha\x85", "Al\u200bpha", "\u202eAlpha", "\ufeffAlpha"],
    ids=["del", "c1-nel", "zero-width-space", "right-to-left-override", "byte-order-mark"],
)
def test_a_name_holding_a_control_or_format_code_point_is_refused(name: str) -> None:
    """D2-c R1S-06 (the note of 2026-10-23 12:28Z): Unicode's Cc and Cf categories, which the
    contract's pattern cannot name; such a name can pass for another on the Owner's screens."""
    (entry,) = name_errors({**_VALID, "name": name})
    assert (entry.field, entry.rule) == ("name", "not_allowed") and name not in entry.message
    assert name_errors({**_VALID, "name": "Alice — 0.5R, Zürich"}) == []


@pytest.mark.parametrize(
    ("errors", "limits", "detail"),
    [
        ([("leverage", "range"), ("leverage", "precision")], False, "1 member failed validation."),
        ([("leverage", "max_leverage"), ("sizing.qty", "qty_step")], True,
         "2 members break an exchange limit."),
        ([("leverage", "max_leverage")], True, "1 member breaks an exchange limit."),
    ],
)  # fmt: skip
def test_a_refusals_detail_counts_its_distinct_members(
    errors: list[tuple[str, str]], limits: bool, detail: str
) -> None:
    """Sec.3: `detail` counts distinct fields, each phase in its own words."""
    entries = [ProfileFieldError(field, rule, "m") for field, rule in errors]
    assert refused(entries, limits=limits).detail == detail


@pytest.mark.parametrize(
    ("code", "status"),
    [("validation_failed", 422), ("conflict", 409), ("idempotency_key_reuse", 409),
     ("version_conflict", 412), ("precondition_required", 428), ("payload_too_large", 413),
     ("audit_unavailable", 503), ("instrument_cache_unavailable", 503)],
)  # fmt: skip
def test_each_code_the_writes_answer_is_registered_at_its_status(code: str, status: int) -> None:
    """D1c's `problem` answers each at its `x-error-codes` status, but `validation_failed`, which
    `ProfileRejected` answers as 422; a 503 says when to retry."""
    registered = {entry["code"]: entry["status"] for entry in SPEC["x-error-codes"]}
    answer = problem(code, "d")
    assert answer.status_code == json.loads(bytes(answer.body))["status"] == status
    assert status == registered[code] or code == "validation_failed"
    assert ("retry-after" in answer.headers) is (status == 503)
