"""Contract (#3085, contract slice): read-only view-as, finding AD-F03 of the E42 threat model
(#890). Three operations: the start on `/admin/view-as` (`users:write`, step-up class `users`),
and the read and the end on `/auth/session/view-as`, the caller's own session (SR-026). The
session-wide rules (the viewer's own operations, read-only, protective writes, scope, expiry and
hold, the actor, the refusal budget) live in the "View-as session" section of `info.description`,
the WebSocket rules in `23-ws-protocol.md` §9.6. Five problem codes and three audit actions are
registered. Additive (C-6.3); the routes stay pending until the server slice serves them."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.step_up import DANGEROUS_PATH_PATTERN, HANDLER_GATED_ROUTES
from candleviewer.audit.actions import AUDIT_ACTIONS, validate_action
from candleviewer.auth.step_up import ACTION_CLASSES, NO_GRACE_ACTION_CLASSES
from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES, ErrorCode
from tests.contract import _admin_support as support
from tests.contract._admin_support import ROOT, SPEC, text

_START, _SELF_PATH = "/admin/view-as", "/auth/session/view-as"
_PATH = {"get": _SELF_PATH, "post": _START, "delete": _SELF_PATH}
_TAG = {"get": "auth", "post": "admin", "delete": "auth"}
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_TESTS = ROOT / "services/api/tests"
_MATRIX = yaml.safe_load((_TESTS / "contract/rbac/matrix.yaml").read_text(encoding="utf-8"))
_ALLOWLIST = _TESTS / "unit/architecture/composition_allowlist.json"
_PENDING = json.loads(_ALLOWLIST.read_text(encoding="utf-8"))["openapi_pending"]
_WS = (ROOT / "docs/plan/23-ws-protocol.md").read_text(encoding="utf-8")
_EVERYONE = {**{actor: "allow" for actor in support.OWNER_ONLY}, "unauthenticated": "401"}
_SELF = {"permissions": [], "scope": "self"}
#: method -> (operationId, exact statuses, x-rbac, x-idempotency, RBAC matrix outcomes)
_OPS: dict[str, tuple[str, set[str], dict[str, Any], str | None, dict[str, str]]] = {
    "get": ("getViewAs", {"200", "204", "401", "403", "503"}, _SELF, None, _EVERYONE),
    "post": (
        "startViewAs",
        {"201", "401", "403", "404", "409", "422", "503"},
        {"permissions": ["users:write"], "scope": "none"},
        "ignored",
        support.OWNER_ONLY,
    ),
    "delete": ("endViewAs", {"204", "401", "403", "503"}, _SELF, "ignored", _EVERYONE),
}
_SHARED = {"401": "Unauthorized", "403": "Forbidden", "404": "NotFound", "409": "Conflict"}
_SHARED |= {"422": "UnprocessableEntity", "503": "ServiceUnavailable"}
#: code -> (status, surfaces). `step_up_required` is reused, not added.
_CODES = {
    "view_as_read_only": (403, ("rest", "ws")),
    "view_as_expired": (403, ("rest",)),
    "view_as_self_target": (403, ("rest",)),
    "view_as_owner_target": (403, ("rest",)),
    "view_as_active": (409, ("rest",)),
}
_ACTIONS = {"admin.view_as_started", "admin.view_as_ended", "admin.view_as_refused"}
_BODY = SPEC["paths"][_START]["post"]["requestBody"]["content"]["application/json"]
_EXAMPLES = support.example_cases([(_PATH[method], method) for method in _OPS]) + [
    ("post request alex", "/components/schemas/StartViewAsRequest", value["value"])
    for value in _BODY["examples"].values()
]
_UUID = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002"


def _op(method: str) -> dict[str, Any]:
    operation: dict[str, Any] = SPEC["paths"][_PATH[method]][method]
    return operation


def _desc(method: str) -> str:
    return text(_op(method)["description"])


def _session_section() -> str:
    info = SPEC["info"]["description"]
    head = info.index("### View-as session (read-only, #3085)")
    return text(info[head : info.index("\n### ", head + 1)])


def _ws_section(heading: str) -> str:
    head = _WS.index(heading)
    return text(_WS[head : _WS.index("\n#", head + 1)])


@pytest.mark.parametrize("method", list(_OPS))
def test_operation_declares_exactly_its_statuses_rbac_and_idempotency(method: str) -> None:
    operation = _op(method)
    operation_id, statuses, rbac, idempotency, _ = _OPS[method]
    assert (operation["operationId"], operation["tags"]) == (operation_id, [_TAG[method]])
    assert set(operation["responses"]) == statuses
    assert operation["x-rbac"] == rbac
    assert operation.get("x-idempotency") == idempotency
    for status, response in operation["responses"].items():
        if status in _SHARED:
            assert response == {"$ref": f"#/components/responses/{_SHARED[status]}"}, status


def test_state_changing_operations_take_the_csrf_token_and_the_read_takes_nothing() -> None:
    for method in ("post", "delete"):
        assert _op(method)["parameters"] == [{"$ref": "#/components/parameters/CsrfToken"}]
    assert "parameters" not in _op("get") and "requestBody" not in _op("get")
    assert "requestBody" not in _op("delete")
    assert {(m, p) for p in {*_PATH.values()} for m in SPEC["paths"][p]} == {*_PATH.items()}


@pytest.mark.parametrize("method", list(_OPS))
def test_operation_is_pending_and_has_its_rbac_matrix_row(method: str) -> None:
    key = f"{method.upper()} {_PATH[method]}"
    assert _PENDING[key]["ticket"] == "#3085"
    row = _MATRIX["operations"][key]
    _, _, rbac, _, outcomes = _OPS[method]
    assert (row["state"], row["outcomes"]) == ("not_mounted", outcomes)
    assert (row["permissions"], row["scope"]) == (rbac["permissions"], rbac["scope"])


def test_start_cites_the_step_up_section_for_class_users() -> None:
    assert "users" in ACTION_CLASSES
    step_up = SPEC["paths"]["/auth/step-up"]["post"]["requestBody"]["content"]
    assert "users" in step_up["application/json"]["schema"]["properties"]["action_class"]["enum"]
    start, cite = _desc("post"), "(`POST /auth/step-up` defines the step-up rules)."
    assert start.startswith(f"Requires `users:write` and step-up class `users` {cite}")
    # A grace class (#3088): the step-up section's rules apply and are not restated (C-16.5).
    assert "users" not in NO_GRACE_ACTION_CLASSES, "no-grace now: say the grant is bound (#2304)"
    assert "grace" not in start and "bound to" not in start
    assert "needs no permission and no step-up" in _desc("delete")
    assert "needs no permission" in _desc("get") and "step-up" not in _desc("get")


def test_start_is_handler_gated_and_the_self_operations_are_not_swept() -> None:
    """L3: pre-registered so the registry test catches an ungated mount of the start."""
    assert ("POST", _START, "users") in HANDLER_GATED_ROUTES
    assert DANGEROUS_PATH_PATTERN.match(_START) and not DANGEROUS_PATH_PATTERN.match(_SELF_PATH)


@pytest.mark.parametrize("code", sorted(_CODES))
def test_every_new_problem_code_is_registered_with_its_status(code: str) -> None:
    status, surfaces = _CODES[code]
    (entry,) = [e for e in SPEC["x-error-codes"] if e["code"] == code]
    assert (entry["status"], entry["retryable"]) == (status, False)
    assert tuple(entry.get("surface", ["rest"])) == surfaces
    meta = ERROR_META[ErrorCode(code)]
    assert (meta.surfaces, meta.retryable) == (surfaces, False)
    assert (ErrorCode(code) in WS_ERROR_CODES) == ("ws" in surfaces)
    assert f'"{code}"' in (ROOT / "packages/protocol/src/errorCodes.ts").read_text("utf-8")
    assert (f"| `{code}` |" in _ws_section("### 10.2 Catalogue")) == ("ws" in surfaces)


def test_no_other_view_as_code_and_step_up_is_reused() -> None:
    catalogue = _ws_section("### 10.2 Catalogue")
    assert "`view_as_expired` is absent for the same reason" in catalogue
    assert "| `view_as_read_only` | request | no | = |" in catalogue  # class, retryable, REST
    registered = {e["code"] for e in SPEC["x-error-codes"] if e["code"].startswith("view_as")}
    assert registered == set(_CODES)
    assert "step_up_required" in {e["code"] for e in SPEC["x-error-codes"]}


def test_view_as_audit_actions_are_registered_by_exact_name() -> None:
    assert {a for a in AUDIT_ACTIONS if a.startswith("admin.view_as")} == _ACTIONS
    assert {validate_action(action) for action in _ACTIONS} == _ACTIONS


def test_request_and_context_schemas() -> None:
    request, context = _SCHEMAS["StartViewAsRequest"], _SCHEMAS["ViewAsContext"]
    assert request["required"] == ["target_user_id", "reason"]
    assert request["additionalProperties"] is False
    assert set(request["properties"]) == {"target_user_id", "reason"}  # no client-set expiry
    reason, labels = request["properties"]["reason"], context["properties"]
    assert (reason["minLength"], reason["maxLength"]) == (1, 500) and "\\u200B" in reason["pattern"]
    assert [labels[f"target_{k}"]["maxLength"] for k in ("username", "display_name")] == [40, 80]
    assert set(context["required"]) == set(labels) == set(api.ViewAsContext.model_fields)
    assert labels["read_only"]["const"] is True and labels["state"]["enum"] == ["active", "expired"]
    assert _BODY["schema"] == {"$ref": "#/components/schemas/StartViewAsRequest"}
    ref = {"$ref": "#/components/schemas/ViewAsContext"}
    for method, status in (("get", "200"), ("post", "201")):
        assert _op(method)["responses"][status]["content"]["application/json"]["schema"] == ref
    invisible = " \t\u00ad\u034f\u061c\u115f\u180e\u200b\u3164\ufe0f\uffa0\ufff9"  # common ones
    for bad in ({"reason": invisible}, {"reason": "x", "expires_at": "2026-09-14T11:00:00Z"}):
        with pytest.raises(ValidationError):
            api.StartViewAsRequest.model_validate({"target_user_id": _UUID, **bad})


@pytest.mark.parametrize(("case", "pointer", "value"), _EXAMPLES, ids=[c[0] for c in _EXAMPLES])
def test_every_example_validates_against_its_response_schema(
    case: str, pointer: str, value: Any
) -> None:
    support.validate_example(pointer, value)


def test_session_section_states_the_session_wide_rules() -> None:
    section = _session_section()
    own = (
        "`POST /admin/view-as`, `GET` and `DELETE /auth/session/view-as`, `GET /auth/session`, "
        "`POST /auth/refresh`, `POST /auth/logout`, `POST /auth/session/extend` and "
        "`POST /auth/unlock` act on the viewer's own session, as the viewer, and "
        "`POST /telemetry/frontend` carries only bucket counts. None of the rules below applies "
        "to them, so leaving view-as is one call that nothing refuses."
    )
    for method, path in re.findall(r"`(GET|POST|DELETE) (/[a-z/-]+)`", own):
        assert method.lower() in SPEC["paths"][path], path
    for claim in (
        own,
        "Every other state-changing request, except the protective writes below, answers "
        "`403 view_as_read_only` and changes nothing. State-changing means the method",
        "a refresh rotation (`POST /auth/refresh`) carries it to the successor session unchanged",
        "The server also ends it at once when the viewer's session no longer holds `users:write`, "
        "or when the target becomes an Owner or is disabled.",
        "Except on the operations the protective writes below pass to their handlers, the refusal "
        "is decided after authentication, the CSRF check (SR-041) and the session state "
        "(enrolment-only, the idle lock, `session_read_only`), and before authorisation, request "
        "validation and the step-up gate, so it is never a step-up challenge and binds no "
        "idempotency key.",
        "the target's role permissions (`x-permissions`) and account grants decide `x-rbac`",
        "no owner-only permission, flag or datum is reachable",
        "The server sets `expires_at` to `started_at` plus 30 minutes; the client cannot set or "
        "extend it",
        "the context ends on the server's clock, whether or not a request arrives",
        "every operation except the viewer's own ones and the protective writes answers "
        "`403 view_as_expired`, whatever its method, and changes nothing, reads included",
        "never waits on its `admin.view_as_ended`: one that cannot be written then stays pending "
        "on the session row until its record is written, late (`recorded_late`)",
        "names the viewer and the viewer's session as the actor. The target is only ever the "
        "object, never the actor.",
        "and each refused WebSocket action frame writes one `admin.view_as_refused` ahead of its "
        "answer",
        'They are counted per user by the mechanism of "Audit budget" in `queryAuditLog`, with '
        "its `suppressed` count, under their own hourly cap, `view_as_refusal_budget_per_hour` "
        "(default 120), and never use a slot of the `/admin/audit*` budget.",
        "Each refusal is also counted in `auth_view_as_refused_total{reason}`.",
        "A due record that cannot be written turns a REST refusal into `503 audit_unavailable`",
        "(AD-D06; requirement 1, #2836)",
        "(C-12.4, C-2.21)",
        "(C-4.14)",
    ):
        assert claim in section, claim
    assert section.count('"Audit budget"') == 1  # cited once, not restated (C-16.5)
    budget = text(SPEC["paths"]["/admin/audit"]["get"]["description"])
    assert "the next record written for the user carries the count (`suppressed`)" in budget
    reads = sorted(
        op["operationId"]
        for item in SPEC["paths"].values()
        for method, op in item.items()
        if method in {"post", "put", "patch", "delete"}
        and all(p.endswith(":read") for p in op["x-rbac"]["permissions"] or ["-"])
    )
    listed = re.search(r"need only a `\*:read` permission \(([^)]*)\)", section)
    assert listed and sorted(re.findall(r"`([A-Za-z]+)`", listed.group(1))) == reads
    binding = text(SPEC["info"]["description"]).split("**Binding point (#2304).**", 1)[1]
    assert "`view_as_read_only` and `view_as_expired` of #3085" in binding.split(". ", 1)[0]
    forbidden = text(SPEC["components"]["responses"]["Forbidden"]["description"])
    assert "`code: view_as_read_only`" in forbidden and "`code: view_as_expired`" in forbidden


def test_protective_writes_are_decided_by_their_handlers() -> None:
    section = _session_section()
    for claim in (
        "Neither the read-only rule nor the hold refuses the writes the C-2.6 carve-out of the "
        "`Forbidden` response names, or engaging the kill switch on an account set "
        "(`setKillSwitch` with `engaged: true`, `scope: accounts`; releasing it and "
        "`scope: global` stay refused: the viewer leaves view-as first).",
        "Both pass `setKillSwitch`, `amendOrder`, `amendTradeGroup`, `setPositionTpSl` (the "
        "`trading-stop` write) and `setRuleMode` (the rule re-arm) to their handlers, which "
        "decide after validation by the classification of 24-internal-schemas.md section 8.10: "
        "a request with any non-protective component is refused `view_as_read_only` (or "
        "`view_as_expired`) there, before any effect, binds no key and writes its refusal record.",
        "A protective write runs as the viewer, is audited with the viewer as the actor, and is "
        "admitted only when both the viewer's own RBAC and the target's `x-rbac` allow it; in the "
        "hold it runs in the viewer's own scope.",
    ):
        assert claim in section, claim
    assert "native SL" not in section  # the carve-out is pointed at, not restated (C-16.5)
    handed = section.split("Both pass ", 1)[1].split(" to their handlers", 1)[0]
    assert all(support.x_rbac(op) for op in re.findall(r"`([A-Za-z]+)`", handed))  # each exists
    assert _SCHEMAS["SetKillSwitchRequest"]["properties"]["scope"]["enum"] == ["global", "accounts"]
    gate = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
    assert "### 8.10 Order-entry gate" in gate and "or re-arming a protective trigger is" in gate
    forbidden = text(SPEC["components"]["responses"]["Forbidden"]["description"])
    assert "re-arming a protective trigger is never refused" in forbidden  # the gate's list
    honour = "while viewing, the writes it names and engaging the kill switch on an account set"
    assert f"Both honour the C-2.6 carve-out below: {honour} are not refused" in forbidden
    state = text(_SCHEMAS["ViewAsContext"]["properties"]["state"]["description"])
    assert "every operation but the viewer's own ones and the protective writes answers" in state


def test_start_states_its_refusal_order_audit_and_notification() -> None:
    start = _desc("post")
    order = [
        "`422 validation_failed`",
        "`409 view_as_active`",
        "`403 view_as_self_target`",
        "`404 not_found`",
        "`409 conflict`",
        "`403 view_as_owner_target`",
    ]
    positions = [start.index(code) for code in order]
    assert positions == sorted(positions)
    for claim in (
        "in this order and before the step-up gate, so a refused start is never a step-up "
        "challenge",
        "A caller without `users:write` is refused `403 forbidden` by the admin-area guard and "
        "recorded as `admin.area_entered` with outcome `denied` (E42-T01); no "
        "`admin.view_as_refused` is written for it.",
        "one conditional write on the session row, as `consume_single_use` is (#2895)",
        "A `step_up_required` refusal is recorded once, as `auth.step_up_required`",
        "outcome `denied`, severity `warning`, reason the problem code",
        "`admin.view_as_started`, outcome `success`, severity `warning`",
        "`after_state` `{target_user_id, started_at, expires_at, reason}`",
        "names the viewer by username and the window (`started_at` to `expires_at`), never "
        "`reason`",
        "If either cannot be recorded, nothing starts",
        "`409 conflict` when the target is `invited` or `disabled` (a `locked` user is only "
        "locked out of signing in, and can be viewed as)",
        "ends with `bye` `view_as_changed`, and reconnects into the target's scope",
    ):
        assert claim in start, claim


def test_end_is_idempotent_and_audited_once_per_context() -> None:
    end = _desc("delete")
    for claim in (
        "On a session that holds none it changes nothing and still answers `204`, so ending is "
        "idempotent",
        "Each context gets exactly one `admin.view_as_ended` record, written when it ends: "
        "outcome `success`, severity `warning`",
        "`after_state` `{ended_at}` (plus `recorded_late: true`, only when late)",
        "reason `ended` (this operation), `expired` (at `expires_at`), `viewer_ineligible`",
        "`target_ineligible` (the target became an Owner or was disabled) or `session_ended`",
        "Leaving never fails on that record",
        "Clearing a held context writes no record of its own",
    ):
        assert claim in end, claim


def test_ws_section_9_6_classifies_every_client_frame_and_closes_on_each_switch() -> None:
    section = _ws_section("### 9.6 View-as sessions (read-only, #3085)")
    envelope = _WS[_WS.index("### 3.1 The envelope") : _WS.index("### 3.2 ")]
    client = set(re.findall(r"^\| `([a-z_]+)` +\|[^|]+\| (?:C→S|both) +\|", envelope, re.M))
    assert {"hello", "auth", "sub", "ping"} <= client  # the parser found the §3.1 table
    listed = re.search(r"Every client frame type of §3\.1 \(([^)]*)\)", section)
    assert listed and set(re.findall(r"`([a-z_]+)`", listed.group(1))) == client
    for claim in (
        "`cv.v1` has no action frame.",
        "the server answers every action frame with `err` `view_as_read_only` (§10.2)",
        "within the viewer's refusal record budget",
        "If that record is due and cannot be written, the `err` is sent anyway.",
        "sends `bye` `view_as_changed` with `reconnect: true` and closes `4401`",
        "but with `bye` `view_as_expired` (`reconnect: false`) and close `4403`",
        "A re-`auth` whose session's view-as state differs from the socket's (it holds no "
        "context, or another one) gets `bye` `view_as_changed` and close `4401` instead of "
        "`auth_ok`.",
        "names the viewer and the viewer's session as the actor, never the target",
        "View-as is the one audited exception to §6.4's rule that a user-scoped kind stays "
        "self-scoped for every role",
    ):
        assert claim in section, claim
    must = text(_WS.split("**Server MUST:**", 1)[1].split("**Client MUST:**", 1)[0])
    assert "| S16 | On a view-as session, authorise every `sub` in the target's scope" in must
    assert "bye` with reason `view_as_expired`, close `4403`" in text(_WS)


def test_security_program_row_40b_and_sr_025() -> None:
    cells = support.capability_rows()["40b"]
    operations = {"startViewAs", "getViewAs", "endViewAs"}
    assert support.grants(cells[1]) == ({"users:write"}, operations)
    assert support.x_rbac("startViewAs") == ["users:write"]
    assert support.x_rbac("getViewAs") == support.x_rbac("endViewAs") == []
    assert cells[2:] == ["✔(step-up)", "✖", "✖"]
    doc = (ROOT / "docs/plan/04-security-program.md").read_text(encoding="utf-8")
    (sr025,) = [line for line in doc.splitlines() if line.startswith("| SR-025 |")]
    assert "creating/deleting users, starting a view-as session (SCR-124)," in sr025
