"""#5992 (E35): validate and compile answer a stop value no rule can hold as a save does.

Validate and compile consult the validator before the content hash in the canonical saves' order,
sharing validate_and_hash, so no order drift can occur across the four routes.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from typing import Any, Final

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.rules import make_rules_router
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.rules.ir.canonical import NOT_FINITE, OUT_OF_RANGE
from candleviewer.rules.issues import MAX_RETURNED_ISSUES
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RulesManager
from candleviewer.rules.scope import ScopeResolver
from candleviewer.rules.scope_state import SnapshotScopeState
from candleviewer.rules.vocabulary import default_registry
from tests.rules._check_limiter import unthrottled
from tests.rules.test_rule_never_loosens_a_stop import _compile_body
from tests.rules.test_rules_routes import _ir
from tests.rules.test_validator_endpoints import RULE_ID

REG = default_registry()
_JSON: Final = {"content-type": "application/json"}
OWNER_ID, MANAGER_ID = uuid.UUID(int=1), uuid.UUID(int=2)
A, C = uuid.UUID(int=10), uuid.UUID(int=12)

#: JSON numbers no rule can hold: the float or int value, and the content hash reason.
NO_RULE_HOLDS: Final = {
    "nan": (float("nan"), NOT_FINITE),
    "infinity": (float("inf"), NOT_FINITE),
    "minus_infinity": (float("-inf"), NOT_FINITE),
    "over_range": (1e70, OUT_OF_RANGE),
    "under_range": (1e-70, OUT_OF_RANGE),
    "wide_integer": (10**64, OUT_OF_RANGE),
}


def _raw(body: dict[str, Any]) -> bytes:
    """`body` as JSON text, keeping NaN / Infinity tokens intact."""
    return json.dumps(body).encode()


def _order(**params: Any) -> dict[str, Any]:
    base = {
        "side": "buy",
        "order_type": "market",
        "qty_mode": "explicit",
        "stop_loss": {"unit": "atr", "value": 1.5},
    }
    return {"node_id": "a1", "type": "place_order", "params": {**base, **params}}


def _notify(**params: Any) -> dict[str, Any]:
    base = {"channel": "ui", "severity": "info", "template": "x"}
    return {"node_id": "a1", "type": "send_notification", "params": {**base, **params}}


def _rule_with_action(action: dict[str, Any], **over: Any) -> dict[str, Any]:
    return _ir(actions=[action], **over)


def _scoped_rule(account: uuid.UUID, action: dict[str, Any] | None = None) -> dict[str, Any]:
    act = action or _order()
    return _ir(
        scope={
            "level": "account",
            "account_ids": [str(account)],
            "environments": ["demo"],
        },
        actions=[act],
    )


class _AppFixture:
    """Sets up both check routes (/rules/validate, /rules/{id}/compile) and CRUD routes (/rules)."""

    def __init__(
        self,
        actor: Actor | None = None,
        granted: Iterable[uuid.UUID] = (A,),
    ) -> None:
        self.granted = list(granted)
        self.actor = actor or Actor(
            str(OWNER_ID),
            "s-owner",
            frozenset({"rules:read", "rules:write"}),
            is_owner=True,
        )
        self.user_id = uuid.UUID(self.actor.user_id)
        self.audits: list[tuple[str, dict[str, Any]]] = []
        self.denials: list[tuple[str, dict[str, str]]] = []
        self.state = SnapshotScopeState(self, "demo")
        self.resolver = ScopeResolver(self.state, self._deny)
        self.mgr = RulesManager(InMemoryRuleStore(), REG, audit=self._audit)

        crud = FastAPI()
        crud.include_router(
            make_rules_crud_router(
                lambda: self.mgr,
                lambda _request: self.actor,
                scope_resolver=lambda: self.resolver,
                scope_refresh=self._refresh,
            )
        )
        checks = FastAPI()
        checks.include_router(
            make_rules_router(
                lambda: REG,
                principal_resolver=self,
                scope_resolver=self.resolver,
                scope_refresh=self._refresh,
                check_limiter=unthrottled(),
            )
        )
        self.crud, self.checks = TestClient(crud), TestClient(checks)

    def has(self, permission: str) -> bool:
        return permission in self.actor.perms

    def resolve(self, request: Request) -> _AppFixture:
        return self

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        return [(a, True, False) for a in self.granted]

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        return self.actor.perms

    async def _audit(self, action: str, payload: dict[str, Any]) -> None:
        self.audits.append((action, payload))

    async def _deny(self, event: str, data: dict[str, str]) -> None:
        self.denials.append((event, data))

    async def _refresh(self, owner: uuid.UUID) -> None:
        await self.state.refresh(owner)


# ==================================================================================================
# Scenario Outline 1: validate answers a stop value no rule can hold as a save does
# ==================================================================================================


@pytest.mark.parametrize("held", sorted(NO_RULE_HOLDS))
def test_validate_answers_a_stop_value_no_rule_can_hold_as_a_save_does(held: str) -> None:
    val, _ = NO_RULE_HOLDS[held]
    action = _order(stop_loss={"unit": "price", "value": val})
    doc = _rule_with_action(action)
    raw_doc = _raw({"ir": doc})

    app = _AppFixture()
    v_res = app.checks.post("/rules/validate", content=raw_doc, headers=_JSON)
    assert v_res.status_code == 200, v_res.text
    body = v_res.json()
    assert body["valid"] is False
    assert len(body["errors"]) == 1
    err = body["errors"][0]
    assert err["code"] == "native_stop_violation"
    assert err["class"] == "safety"
    assert err["path"] == "actions[0]"

    # Verify it matches the issue POST /rules answers for the identical document
    s_res = app.crud.post("/rules", content=raw_doc, headers=_JSON)
    assert s_res.status_code == 422
    assert s_res.json()["code"] == "rule_ir_invalid"
    save_err = s_res.json()["errors"][0]
    assert save_err == {"field": err["path"], "rule": err["code"], "message": err["message"]}


# ==================================================================================================
# Scenario Outline 2: compile answers it as a save does
# ==================================================================================================


@pytest.mark.parametrize("held", sorted(NO_RULE_HOLDS))
def test_compile_answers_a_stop_value_no_rule_can_hold_as_a_save_does(held: str) -> None:
    val, _ = NO_RULE_HOLDS[held]
    action = _order(stop_loss={"unit": "price", "value": val})
    doc = _rule_with_action(action)
    raw_model = _raw(_compile_body(doc))

    app = _AppFixture()
    c_res = app.checks.post(f"/rules/{RULE_ID}/compile", content=raw_model, headers=_JSON)
    assert c_res.status_code == 422, c_res.text
    body = c_res.json()
    assert body["code"] == "rule_ir_invalid"
    assert "ir_hash" not in body
    assert len(body["errors"]) == 1
    err = body["errors"][0]
    assert err["rule"] == "native_stop_violation"
    assert err["field"] == "actions[0]"


# ==================================================================================================
# Scenario 3: a value only the content hash refuses keeps the hash's answer
# ==================================================================================================


@pytest.mark.parametrize(
    ("untyped_val", "expected_msg_sub"),
    [
        (float("nan"), "finite number"),
        (1e70, "outside the range"),
    ],
)
def test_a_value_only_the_content_hash_refuses_keeps_the_hash_answer(
    untyped_val: Any, expected_msg_sub: str
) -> None:
    """An untyped action param with an unhashable value keeps schema_error across all routes."""
    action = _notify(w=untyped_val)
    doc = _rule_with_action(action)
    raw_doc = _raw({"ir": doc})
    raw_model = _raw(_compile_body(doc))

    app = _AppFixture()

    # 1. POST /rules/validate
    v_res = app.checks.post("/rules/validate", content=raw_doc, headers=_JSON)
    assert v_res.status_code == 200, v_res.text
    v_body = v_res.json()
    assert v_body["valid"] is False
    assert len(v_body["errors"]) == 1
    v_err = v_body["errors"][0]
    assert v_err["code"] == "schema_error"
    assert v_err["class"] == "syntax"
    assert v_err["path"] == "actions[0].params.w"
    assert expected_msg_sub in v_err["message"]

    # 2. POST /rules/{ruleId}/compile
    c_res = app.checks.post(f"/rules/{RULE_ID}/compile", content=raw_model, headers=_JSON)
    assert c_res.status_code == 422, c_res.text
    c_body = c_res.json()
    assert c_body["code"] == "rule_ir_invalid"
    assert "ir_hash" not in c_body
    assert len(c_body["errors"]) == 1
    assert c_body["errors"][0]["rule"] == "schema_error"
    assert c_body["errors"][0]["field"] == "actions[0].params.w"

    # 3. POST /rules (create save)
    s_res = app.crud.post("/rules", content=raw_doc, headers=_JSON)
    assert s_res.status_code == 422, s_res.text
    s_body = s_res.json()
    assert s_body["code"] == "rule_ir_invalid"
    assert s_body["path"] == "/actions/0/params/w"
    assert expected_msg_sub in s_body["detail"]

    # 4. PUT /rules/{ruleId} (update save)
    valid_doc = _ir()
    create_ok = app.crud.post("/rules", json={"ir": valid_doc})
    assert create_ok.status_code == 201, create_ok.text
    rid = create_ok.json()["id"]

    u_res = app.crud.put(f"/rules/{rid}", content=raw_doc, headers={**_JSON, "If-Match": "1"})
    assert u_res.status_code == 422, u_res.text
    u_body = u_res.json()
    assert u_body["code"] == "rule_ir_invalid"
    assert u_body["path"] == "/actions/0/params/w"
    assert expected_msg_sub in u_body["detail"]


# ==================================================================================================
# Scenario 4: the four routes share one order
# ==================================================================================================


def test_the_four_routes_share_one_order() -> None:
    """Validate, compile, create and update answer identical first issue for any refusal class."""
    documents: list[tuple[str, dict[str, Any], bytes, bytes, str, str, str]] = []

    # Case A: unholdable stop numbers -> native_stop_violation at actions[0]
    for held in ("nan", "over_range", "wide_integer"):
        val = NO_RULE_HOLDS[held][0]
        act = _order(stop_loss={"unit": "price", "value": val})
        d = _rule_with_action(act)
        documents.append(
            (
                f"unholdable_stop_{held}",
                d,
                _raw({"ir": d}),
                _raw(_compile_body(d)),
                "actions[0]",
                "native_stop_violation",
                "actions[0]",
            )
        )

    # Case B: empty native stop -> native_stop_violation at actions[0]
    empty_stop_act = {
        "node_id": "a1",
        "type": "place_order",
        "params": {
            "side": "buy",
            "order_type": "market",
            "qty_mode": "explicit",
            "stop_loss": {},
        },
    }
    d_empty = _rule_with_action(empty_stop_act)
    documents.append(
        (
            "empty_stop",
            d_empty,
            _raw({"ir": d_empty}),
            _raw(_compile_body(d_empty)),
            "actions[0]",
            "native_stop_violation",
            "actions[0]",
        )
    )

    # Case C: value only the content hash refuses -> schema_error at actions[0].params.w
    d_hash = _rule_with_action(_notify(w=float("nan")))
    documents.append(
        (
            "hash_only_refusal",
            d_hash,
            _raw({"ir": d_hash}),
            _raw(_compile_body(d_hash)),
            "actions[0].params.w",
            "schema_error",
            "/actions/0/params/w",
        )
    )

    # Case D: document with BOTH an unholdable stop and an untyped unhashable param.
    # The validator runs first and catches native_stop_violation at actions[0];
    # this test FAILS if any route consults the content hash before the validator!
    both_act = {
        "node_id": "a1",
        "type": "place_order",
        "params": {
            "side": "buy",
            "order_type": "market",
            "qty_mode": "explicit",
            "stop_loss": {"unit": "price", "value": float("nan")},
            "w": float("nan"),
        },
    }
    d_both = _rule_with_action(both_act)
    documents.append(
        (
            "both_validator_and_hash_issues",
            d_both,
            _raw({"ir": d_both}),
            _raw(_compile_body(d_both)),
            "actions[0]",
            "native_stop_violation",
            "actions[0]",
        )
    )

    app = _AppFixture()
    # Create base rule for update tests
    create_ok = app.crud.post("/rules", json={"ir": _ir()})
    assert create_ok.status_code == 201
    rid = create_ok.json()["id"]

    for (
        name,
        _doc,
        raw_doc,
        raw_model,
        expected_field,
        expected_rule,
        expected_save_path,
    ) in documents:
        # 1. validate
        v = app.checks.post("/rules/validate", content=raw_doc, headers=_JSON)
        assert v.status_code == 200, f"{name}: {v.text}"
        first_v = v.json()["errors"][0]
        assert (first_v["path"], first_v["code"]) == (expected_field, expected_rule), (
            f"validate {name}: expected ({expected_field}, {expected_rule}), got {first_v}"
        )

        # 2. compile
        c = app.checks.post(f"/rules/{RULE_ID}/compile", content=raw_model, headers=_JSON)
        c_body = c.json()
        if c.status_code == 422:
            first_c = c_body["errors"][0]
            assert (first_c["field"], first_c["rule"]) == (expected_field, expected_rule), (
                f"compile {name}: expected ({expected_field}, {expected_rule}), got {first_c}"
            )
        else:
            assert c.status_code == 200, f"compile {name}: {c.text}"
            first_c_issue = c_body["issues"][0]
            issue_match = (first_c_issue["path"], first_c_issue["code"])
            assert issue_match == (expected_field, expected_rule), (
                f"compile {name}: expected ({expected_field}, {expected_rule}), got {first_c_issue}"
            )

        # 3. create
        cr = app.crud.post("/rules", content=raw_doc, headers=_JSON)
        assert cr.status_code == 422, f"{name}: {cr.text}"
        cr_body = cr.json()
        if "errors" in cr_body:
            first_cr = cr_body["errors"][0]
            assert (first_cr["field"], first_cr["rule"]) == (expected_field, expected_rule), (
                f"create {name}: expected ({expected_field}, {expected_rule}), got {first_cr}"
            )
        else:
            assert cr_body.get("path") == expected_save_path

        # 4. update
        u = app.crud.put(f"/rules/{rid}", content=raw_doc, headers={**_JSON, "If-Match": "1"})
        assert u.status_code == 422, f"{name}: {u.text}"
        u_body = u.json()
        if "errors" in u_body:
            first_u = u_body["errors"][0]
            assert (first_u["field"], first_u["rule"]) == (expected_field, expected_rule), (
                f"update {name}: expected ({expected_field}, {expected_rule}), got {first_u}"
            )
        else:
            assert u_body.get("path") == expected_save_path


# ==================================================================================================
# Scenario 5: refusals and bounds stay as they are
# ==================================================================================================


def test_refusals_and_bounds_stay_as_they_are() -> None:
    # 1. Caller without rules:read gets 403 on validate and compile
    no_read_actor = Actor(str(OWNER_ID), "s1", frozenset({"orders:write"}), is_owner=True)
    app_no_read = _AppFixture(actor=no_read_actor)
    doc = _ir()
    assert app_no_read.checks.post("/rules/validate", json={"ir": doc}).status_code == 403
    assert (
        app_no_read.checks.post(f"/rules/{RULE_ID}/compile", json=_compile_body(doc)).status_code
        == 403
    )

    # 2. Caller without rules:write gets 403 on create and update
    read_only_actor = Actor(str(OWNER_ID), "s2", frozenset({"rules:read"}), is_owner=True)
    app_read_only = _AppFixture(actor=read_only_actor)
    assert app_read_only.crud.post("/rules", json={"ir": doc}).status_code == 403
    assert (
        app_read_only.crud.put(
            f"/rules/{RULE_ID}", json={"ir": doc}, headers={"If-Match": "1"}
        ).status_code
        == 403
    )

    # 3. Caller with ungranted account gets 403 on valid document
    manager_actor = Actor(
        str(MANAGER_ID),
        "s-manager",
        frozenset({"rules:read", "rules:write"}),
        granted_accounts=frozenset({str(A)}),
        is_owner=False,
    )
    app_scope = _AppFixture(actor=manager_actor, granted=[A])
    out_of_scope_doc = _scoped_rule(C)
    val_out = app_scope.checks.post("/rules/validate", json={"ir": out_of_scope_doc})
    assert val_out.status_code == 403
    assert (
        app_scope.checks.post(
            f"/rules/{RULE_ID}/compile", json=_compile_body(out_of_scope_doc)
        ).status_code
        == 403
    )
    assert app_scope.crud.post("/rules", json={"ir": out_of_scope_doc}).status_code == 403

    # 4. Bounded answer: at most 50 issues returned, issues_total counts all (#5971)
    # Build 60 condition comparisons with unknown metrics
    def _any_of(prefix: str, n: int) -> dict[str, Any]:
        return {
            "node_id": prefix,
            "op": "any_of",
            "children": [
                {
                    "node_id": f"{prefix}{i}",
                    "op": "gt",
                    "left": {"metric": f"unknown_metric_{prefix}_{i}"},
                    "right": {"const": i},
                }
                for i in range(n)
            ],
        }

    many_doc = _ir()
    many_doc["conditions"] = {
        "node_id": "root",
        "op": "all_of",
        "children": [_any_of("u", 30), _any_of("v", 30)],
    }
    app = _AppFixture()
    v_res = app.checks.post("/rules/validate", json={"ir": many_doc})
    assert v_res.status_code == 200, v_res.text
    body = v_res.json()
    assert body["valid"] is False
    assert len(body["errors"]) == MAX_RETURNED_ISSUES  # exactly 50
    assert body["issues_total"] >= 60


# ==================================================================================================
# Scenario 6: the scope check comes first
# ==================================================================================================


def test_the_scope_check_comes_first() -> None:
    """Body that names ungranted account AND holds unholdable stop answers 403 before validation."""
    manager_actor = Actor(
        str(MANAGER_ID),
        "s-manager",
        frozenset({"rules:read", "rules:write"}),
        granted_accounts=frozenset({str(A)}),
        is_owner=False,
    )
    app_scope = _AppFixture(actor=manager_actor, granted=[A])

    # Unholdable stop value (NaN) with out-of-scope account C
    unholdable_act = _order(stop_loss={"unit": "price", "value": float("nan")})
    unholdable_doc = _scoped_rule(C, unholdable_act)
    raw_doc = _raw({"ir": unholdable_doc})
    raw_model = _raw(_compile_body(unholdable_doc))

    # Validate answers 403 Forbidden, not 200 with native_stop_violation or 422
    v_res = app_scope.checks.post("/rules/validate", content=raw_doc, headers=_JSON)
    assert v_res.status_code == 403, f"Expected 403, got {v_res.status_code}: {v_res.text}"

    # Compile answers 403 Forbidden, not 422 rule_ir_invalid
    c_res = app_scope.checks.post(f"/rules/{RULE_ID}/compile", content=raw_model, headers=_JSON)
    assert c_res.status_code == 403, f"Expected 403, got {c_res.status_code}: {c_res.text}"

    # Save answers 403 Forbidden as well
    s_res = app_scope.crud.post("/rules", content=raw_doc, headers=_JSON)
    assert s_res.status_code == 403, f"Expected 403, got {s_res.status_code}: {s_res.text}"
