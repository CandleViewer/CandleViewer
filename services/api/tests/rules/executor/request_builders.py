"""Builders for the dispatch envelope (24 §11.9), for the rules tests that need a request."""

from __future__ import annotations

import uuid
from typing import Any

from candleviewer.rules.ir.models import Action, RuleScope
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef


def action_request(
    scope: RuleScope, owner: uuid.UUID, instance: ScopeInstanceRef, **over: Any
) -> ActionRequest:
    """An armed fire's `flatten_position` request on `instance`; `over` replaces any field."""
    fields: dict[str, Any] = {
        "rule_scope": scope,
        "owner": owner,
        "environment": "demo",
        "instance": instance,
        "action_type": "flatten_position",
        "payload": Action(node_id="a1", type="flatten_position", params={}),
        "mode": "armed",
        "rule_id": str(uuid.UUID(int=7)),
        "version": 1,
        "ir_hash": "0" * 64,
        "run_id": uuid.UUID(int=8),
        "armed_by": str(owner),
    }
    return ActionRequest(**(fields | over))
