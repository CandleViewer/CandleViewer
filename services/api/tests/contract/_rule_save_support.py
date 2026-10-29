"""The `/rules` save-body contract tests' own world (#4835), so they import no other test module:
two account ids, a 22-shaped rule IR, bodies validated before they are sent, an Owner's client."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.contract._admin_support import validate_example

A, B = (uuid.UUID(int=i) for i in (10, 11))
#: The one member the server's IR needs beyond 22's `RuleIr`, set aside when a body is validated.
SERVER_ONLY = frozenset({"version"})


def rule_ir(threshold: str = "65000.50", **scope: Any) -> dict[str, Any]:
    """An IR as 22's `RuleIr` shapes it, plus `SERVER_ONLY`: `scope` is the IR's scope."""
    left = {"metric": "price", "params": {"n": 14}}
    action = {"channel": "ui", "severity": "info", "template": "x"}
    return {
        "ir_version": 1,
        "version": 1,
        "trigger": {"type": "on_price_update"},
        "conditions": {"node_id": "c1", "op": "gt", "left": left, "right": {"const": threshold}},
        "actions": [{"node_id": "a1", "type": "send_notification", "params": action}],
        "scope": scope,
    }


def save_body(schema: str, name: str, ir: dict[str, Any]) -> dict[str, Any]:
    """A body holding every member `schema` requires, validated against it before it is sent."""
    body = {"name": name, "scope": ir["scope"]["level"], "ir": ir}
    in_contract = {k: v for k, v in ir.items() if k not in SERVER_ONLY}
    validate_example(f"/components/schemas/{schema}", {**body, "ir": in_contract})
    return body


def owner_client() -> TestClient:
    """The save routes over an empty in-memory store, for an Owner who may read and write rules."""
    mgr = RulesManager(InMemoryRuleStore(), default_registry())
    perms = frozenset({"rules:read", "rules:write"})
    owner = Actor(str(uuid.UUID(int=1)), "s1", perms, is_owner=True)
    app = FastAPI()
    app.include_router(make_rules_crud_router(lambda: mgr, lambda _request: owner))
    return TestClient(app)
