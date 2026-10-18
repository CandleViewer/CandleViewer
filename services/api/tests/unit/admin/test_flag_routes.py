"""The feature-flag routes (E42-T03) over the real service and writer with a fake store, audit,
user directory and step-up: what each answer carries, and the audit every refusal past the admin
guard leaves (the guard's own records are E42-T01's)."""

from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from candleviewer.admin.flags import FLAGS, FlagConflictError, FlagsWriteDenied, StoredFlag
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import assert_spec_is_valid
from candleviewer.api.step_up import StepUpRefused
from candleviewer.api.step_up_challenge import request_fingerprint
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.storage.errors import StorageTierUnavailable
from tests.unit.admin._flag_route_fakes import KEY, KNOWN, OWNER_ONLY, client, put, write
from tests.unit.admin.flag_fakes import T0, FakeAudit, FakeStepUp


def _changes(audit: FakeAudit) -> list[dict[str, Any]]:
    return [kw for action, kw in audit.records if action == "flags.change"]


def _with(value: str) -> bytes:
    """A write whose `value` is the raw JSON text `value`."""
    return json.dumps(write(value="@")).replace('"@"', value).encode()


def test_the_write_declares_its_path_parameter_so_the_document_validates() -> None:
    app = client()[0].app
    assert isinstance(app, FastAPI)
    assert_spec_is_valid(app.openapi())  # `flagKey` declared, unconstrained: its 404 is audited


def test_the_list_resolves_every_flag_for_the_caller() -> None:
    body = client()[0].get("/admin/feature-flags", headers={"x-role": "owner"}).json()
    assert body["resolution"] == "stored" and len(body["items"]) == len(FLAGS)
    flag = next(i for i in body["items"] if i["key"] == OWNER_ONLY)  # the owner sees it
    assert (flag["value"], flag["updated_at"]) == (True, "2026-10-15T08:00:00Z")
    assert api.FeatureFlag.model_validate(flag).model_dump(mode="json", exclude_unset=True) == flag


def test_a_store_outage_lists_fail_closed_values_only() -> None:
    body = client(down=True)[0].get("/admin/feature-flags", headers={"x-role": "owner"}).json()
    assert body["resolution"] == "fail_closed"
    assert {k for i in body["items"] for k in i} == {"key", "kind", "description", "value"}


def test_a_write_answers_the_committed_flag_after_its_audit() -> None:
    c, audit = client(step_up=(step_up := FakeStepUp()))
    body = write(overrides=[{"user_id": str(KNOWN), "value": True}])
    response = put(c, body)
    assert response.status_code == 200
    target = f"/admin/feature-flags/{KEY}".encode()  # the step-up binds to this request
    assert step_up.fingerprints == [request_fingerprint("PUT", target, body)]
    assert response.json() | {"overrides": None} == response.json() | {
        "key": KEY, "value": False, "default_value": False, "overrides": None,
        "updated_at": "2026-10-15T08:00:01Z",
    }  # fmt: skip
    assert response.json()["overrides"] == [{"user_id": str(KNOWN), "value": True}]
    assert [kw["after_state"].get("phase") for kw in _changes(audit)] == ["intent", "outcome"]


@pytest.mark.parametrize("query", ["?a=1", "?b=%7E&a=1"], ids=["query", "query-as-received"])
def test_the_step_up_binds_to_the_request_target_as_received_query_string_included(
    query: str,
) -> None:
    c, _ = client(step_up=(step_up := FakeStepUp()))
    body = write()
    assert put(c, body, query=query).status_code == 200
    target = f"/admin/feature-flags/{KEY}{query}".encode()  # never `request.url.path` alone
    assert step_up.fingerprints == [request_fingerprint("PUT", target, body)]


@pytest.mark.parametrize(
    ("key", "role", "object_id"),
    [
        ("no.such", "owner", "no.such"),
        ("Bad Key", "owner", "<invalid>"),
        ("a." + "b" * 79, "owner", "<invalid>"),  # 81 characters: past the contract's 80
        (OWNER_ONLY, "writer", OWNER_ONLY),
    ],
)
def test_a_key_the_caller_cannot_see_is_404_and_audited(
    key: str, role: str, object_id: str
) -> None:
    c, audit = client()
    response = put(c, write(), key, role)
    assert (response.status_code, response.json()["code"]) == (404, "not_found")
    assert response.json() == put(client()[0], write(), "no.such").json()  # one body for all
    [record] = _changes(audit)
    assert (record["object_id"], record["reason"], record["after_state"]) == (
        object_id, "not_found", {"result": "not_found"}
    )  # fmt: skip


def test_the_body_cap_is_exact_and_past_it_is_422_body_too_large() -> None:
    c, audit = client()
    body = json.dumps(write()).encode()
    at_cap = body + b" " * (16 * 1024 - len(body))
    assert put(c, at_cap).status_code == 200
    over = put(c, at_cap + b" ")
    assert over.status_code == 422
    assert over.json()["errors"] == [{"field": "", "rule": "body_too_large"}]
    assert _changes(audit)[-1]["after_state"] == {"result": "body_too_large"}  # never the body


@pytest.mark.parametrize(
    ("body", "field", "rule"),
    [
        (b"{", "", "json_invalid"),
        ({"reason": "x"}, "value", "missing"),
        (write(extra=1), "extra", "extra_forbidden"),
        (write(reason="r" * 281), "reason", "string_too_long"),
        (write(expected_updated_at="2026-10-15T08:00:00"), "expected_updated_at", "timezone_aware"),
        (
            write(overrides=[{"user_id": str(KNOWN), "value": True}] * 2),
            "overrides",
            "duplicate_user",
        ),
        (write(reason="a\x00b"), "", "invalid_character"),
        (write(value="a\x00"), "", "invalid_character"),
        (write(evidence_url="https://x.example/\x00"), "", "invalid_character"),
        (write(overrides=[{"user_id": str(KNOWN), "value": "\x00"}]), "", "invalid_character"),
        (write(overrides=[{"user_id": "\x00", "value": True}]), "", "invalid_character"),
        (write(expected_updated_at="2026-10-15T08:00:00+00:00\x00"), "", "invalid_character"),
        (write(**{"a\x00": 1}), "", "invalid_character"),  # in a key
        (_with('"\\ud800"'), "", "invalid_character"),  # a lone surrogate: no UTF-8
        (_with('"\\udfff"'), "", "invalid_character"),  # ...at the other edge of its range
        *((_with(c), "", "json_invalid") for c in ("NaN", "Infinity", "-Infinity", "1e999")),
        (_with("[" * 8 + "]" * 8), "value", "kind_mismatch"),  # as deep as the walk goes
        *((_with("[" * n + "]" * n), "", "json_invalid") for n in (9, 1000, 8000)),
        (write(**{"x" * 200: 1}), "x" * 128, "extra_forbidden"),  # the echoed name, cut
    ],
)
def test_a_body_the_contract_refuses_is_422_and_audited(
    body: object, field: str, rule: str
) -> None:
    c, audit = client()
    response = put(c, body)
    assert (response.status_code, response.json()["errors"]) == (
        422,
        [{"field": field, "rule": rule}],
    )
    assert _changes(audit)[-1]["reason"] == rule


#: What `api.feature_flags._REFUSED` refuses: both edges of each of its ranges, a mid-point of the
#: C1 and Tags ranges, DEL, and the characters the contract names: `\t`, `\n` and `\r` (a multi-line
#: reason), ZWNJ and ZWJ (an emoji sequence). Numbers, not escapes, so that no source line of this
#: file can hold an invisible character.
_REFUSED_CODES = (
    0x0000,  # NUL
    0x0009,  # tab
    0x000A,  # LF
    0x000D,  # CR
    0x001F,  # the C0 range's last
    0x007F,  # DEL
    0x0080,  # the C1 range's first
    0x0090,  # ...the mid-point
    0x009F,  # ...and its last
    0x061C,  # ARABIC LETTER MARK
    0x200B,  # ZERO WIDTH SPACE
    0x200C,  # ZWNJ
    0x200D,  # ZWJ
    0x200F,  # RIGHT-TO-LEFT MARK
    0x2028,  # LINE SEPARATOR
    0x2029,  # PARAGRAPH SEPARATOR
    0x202A,  # LEFT-TO-RIGHT EMBEDDING
    0x202E,  # RIGHT-TO-LEFT OVERRIDE
    0x2066,  # LEFT-TO-RIGHT ISOLATE
    0x2069,  # POP DIRECTIONAL ISOLATE
    0xFEFF,  # BYTE ORDER MARK
    0xE0000,  # the Tags block's first
    0xE0040,  # ...the mid-point (TAG COMMERCIAL AT)
    0xE007F,  # ...and its last (CANCEL TAG)
)


def _as_the_reason(text: str) -> dict[str, Any]:
    return write(reason=text)


def _as_a_member_name(text: str) -> dict[str, Any]:
    return write(**{text: 1})  # a member the request does not define: still refused as a name


@pytest.mark.parametrize(
    "where", [_as_the_reason, _as_a_member_name], ids=["reason", "member-name"]
)
@pytest.mark.parametrize("code", _REFUSED_CODES, ids=lambda code: f"U+{code:04X}")
def test_a_refused_character_in_a_reason_or_a_member_name_is_422_and_audited(
    code: int, where: Callable[[str], dict[str, Any]]
) -> None:
    c, audit = client()
    response = put(c, where(f"a{chr(code)}b"))
    assert (response.status_code, response.json()["errors"]) == (
        422,
        [{"field": "", "rule": "invalid_character"}],
    )  # `invalid_character`, never `extra_forbidden`: the walk runs before the schema
    assert _changes(audit)[-1]["reason"] == "invalid_character"


@pytest.mark.parametrize(
    ("value", "audited"),
    [
        ("x" * 256, "x" * 256),
        ("x" * 1000, "x" * 256 + "…"),
        (10**3999, {"type": "int", "len": 4000}),  # the parser takes up to 4,300 digits
        (-(10**3999), {"type": "int", "len": 4001}),
        (1.5, {"type": "float", "len": 3}),
        (101, {"type": "int", "len": 3}),
        (100, 100),  # a percentage's edge: a flag value's shape
        ([1] * 2500, {"type": "list", "len": 2500}),
        ({"a": {"b": 1}}, {"type": "dict", "len": 1}),
    ],
)
def test_the_writers_refusals_keep_their_rule_and_audit_a_bounded_value(
    value: object, audited: object
) -> None:
    c, audit = client()
    response = put(c, write(value=value, overrides=[{"user_id": str(KNOWN), "value": value}]))
    assert response.json()["errors"] == [{"field": "value", "rule": "kind_mismatch"}]
    [record] = _changes(audit)  # recorded by the writer: never a large raw value
    assert record["after_state"]["value"] == audited
    assert record["after_state"]["overrides"] == {str(KNOWN): audited}


def test_live_enablement_carries_its_reason_and_its_evidence_as_sent() -> None:
    c, audit = client()
    url = "https://H.EXAMPLE/pt-1"  # as sent: the model would normalise the host
    body = write(value=True, reason="pen test passed", evidence_url=url)
    assert put(c, body, "trading.live_enabled").status_code == 200
    intent = _changes(audit)[0]
    assert (intent["reason"], intent["after_state"]["evidence_url"]) == ("pen test passed", url)


def test_a_reader_lists_for_its_role_and_the_guard_refuses_its_write() -> None:
    c, audit = client()
    listed = c.get("/admin/feature-flags", headers={"x-role": "reader"}).json()["items"]
    assert OWNER_ONLY not in {item["key"] for item in listed}  # resolved for its role, no owner
    response = put(c, write(), role="reader")
    assert (response.status_code, response.json()["code"]) == (403, "forbidden")
    assert [(a, kw["outcome"]) for a, kw in audit.records][-1:] == [
        ("admin.area_entered", AuditOutcome.DENIED)
    ]  # the guard's record only: no rbac.denied, no flags.change


def test_a_stale_write_is_409_with_the_flag_as_it_stands() -> None:
    c, _ = client()
    assert put(c, write()).status_code == 200
    response = put(c, write())  # read before the first write
    assert response.status_code == 409
    conflict = api.FeatureFlagConflict.model_validate(response.json())
    assert conflict.current.updated_at is not None and conflict.code == "conflict"


def test_a_conflict_answers_the_current_flag_resolved_for_the_callers_role() -> None:
    async def stale(*_args: Any, **_kwargs: Any) -> Any:
        raise FlagConflictError(StoredFlag(False, role_overrides={"owner": True}, updated_at=T0))

    response = put(client(SimpleNamespace(set=stale))[0], write())
    assert (response.status_code, response.json()["current"]["value"]) == (409, True)


def test_a_store_outage_is_503_and_says_when_to_retry() -> None:
    response = put(client(down=True)[0], write())
    assert (response.status_code, response.json()["code"]) == (503, "store_unavailable")
    assert (response.headers["retry-after"], response.json()["retry_after_seconds"]) == ("5", 5)


async def _refuse(principal: AuditPrincipal, action_class: str, change: object, fp: object) -> None:
    raise StepUpRefused(JSONResponse({"code": "step_up_required"}, status_code=403))


def test_a_refused_step_up_answers_the_refusal_and_writes_nothing() -> None:
    c, audit = client(step_up=_refuse)
    response = put(c, write())
    assert (response.status_code, response.json()) == (403, {"code": "step_up_required"})
    assert _changes(audit) == []  # no intent: the auth module audits the challenge


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (FlagsWriteDenied("flags:write"), 403, "forbidden"),
        (AuditUnavailable("down"), 503, "audit_unavailable"),
        (StorageTierUnavailable("users"), 503, "store_unavailable"),  # under the row lock
        (ConnectionRefusedError("sessions"), 503, "store_unavailable"),
        (OperationalError("SELECT 1", None, Exception("gone")), 503, "store_unavailable"),
    ],
)
def test_a_writer_failure_maps_to_its_problem(error: Exception, status: int, code: str) -> None:
    async def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    c, audit = client(SimpleNamespace(set=fail))
    response = put(c, write())
    assert (response.status_code, response.json()["code"]) == (status, code)
    denied = [kw["outcome"] for action, kw in audit.records if action == "rbac.denied"]
    assert denied == [AuditOutcome.DENIED] * (status == 403)


class _FlagAuditDown(FakeAudit):
    """The guard's record lands; the route's own `flags.change` or `rbac.denied` cannot."""

    async def emit(self, action: str, **kwargs: Any) -> None:
        if action != "admin.area_entered":
            raise AuditUnavailable("down")
        await super().emit(action, **kwargs)


async def _deny(*_args: Any, **_kwargs: Any) -> Any:
    raise FlagsWriteDenied("flags:write")


@pytest.mark.parametrize(
    ("key", "body", "writer"),
    [("no.such", write(), None), (KEY, b"{", None), (KEY, write(), SimpleNamespace(set=_deny))],
)
def test_a_refusal_the_route_cannot_audit_is_503(key: str, body: object, writer: Any) -> None:
    response = put(client(writer, audit=_FlagAuditDown())[0], body, key)
    assert (response.status_code, response.json()["code"]) == (503, "audit_unavailable")
    assert response.headers["retry-after"] == "5"
