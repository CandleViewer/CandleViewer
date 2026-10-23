"""E37-T01 (#951): compile answers the client's hash for each body a JS client sends.

Each ``js`` vector of ``packages/fixtures/golden/rule-ir/hash_vectors.json``, which the client
mirror in ``packages/rule-graph`` is held to, goes through the real compile route as the graph
editor sends it: ``editor: graph``, the server's ``to_graph_model`` of the body, and numbers as
``JSON.stringify`` writes them. The route must answer the vector's ``ir_hash``. In-process
(``TestClient``): no network.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.rules import make_rules_router
from candleviewer.rules.compiler import to_graph_model
from candleviewer.rules.ir import Rule
from candleviewer.rules.scope import AccountState, ScopeResolver, ScopeState
from candleviewer.rules.vocabulary import default_registry

VECTORS = Path(__file__).resolve().parents[4] / "packages/fixtures/golden/rule-ir/hash_vectors.json"
#: The bodies a JS client sends the same values in (``js``) that the server hashes.
SENT = [v for v in json.loads(VECTORS.read_text("utf-8"))["vectors"] if v["js"] and "ir_hash" in v]
ACCOUNTS = frozenset(
    UUID(a) for v in SENT for a in json.loads(v["ir"])["scope"].get("account_ids", [])
)
#: The caller may use every account the vectors name: scope is not what this test checks. No vector
#: names the live environment, so compile's scope check reads only these two.
GRANTS = SimpleNamespace(
    granted_accounts=lambda _: ACCOUNTS, account=lambda *_: AccountState("demo")
)


def js(value: Any) -> Any:
    """``value`` as JSON.stringify writes it: a whole number as an integer, any other number as a
    float, never as text (``default=str`` would send a Decimal const as a string const)."""
    if isinstance(value, dict):
        return {key: js(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [js(item) for item in value]
    if isinstance(value, Decimal | float):
        return int(value) if value == int(value) else float(value)
    return str(value) if isinstance(value, UUID) else value


class Caller:
    user_id = UUID(int=1)

    def has(self, permission: str) -> bool:
        return permission == "rules:read"

    def resolve(self, request: object) -> Caller:
        return self


async def _audit(action: str, detail: dict[str, str]) -> None:
    return None


APP = FastAPI()
APP.include_router(
    make_rules_router(
        default_registry,
        principal_resolver=Caller(),
        scope_resolver=ScopeResolver(cast(ScopeState, GRANTS), _audit),
    )
)
CLIENT = TestClient(APP)


def test_js_writes_numbers_as_json_stringify_does() -> None:
    sent = {"a": Decimal("1.50"), "b": 2.0, "c": Decimal("1E-7"), "d": [Decimal("1E+2"), True]}
    assert json.dumps(js(sent)) == '{"a": 1.5, "b": 2, "c": 1e-07, "d": [100, true]}'


def test_the_vectors_sent_cover_the_whole_corpus() -> None:
    assert sum(v["kind"] == "corpus" for v in SENT) == 30


@pytest.mark.parametrize("vector", SENT, ids=[v["name"] for v in SENT])
def test_compile_answers_the_vector_ir_hash_for_the_graph_editor(vector: dict[str, Any]) -> None:
    doc = json.loads(vector["ir"])  # as the route reads a body: a fraction is a float
    model = js(to_graph_model(Rule.model_validate(doc)))
    sent = CLIENT.post(f"/rules/{doc['rule_id']}/compile", json={"editor": "graph", "model": model})
    assert sent.status_code == 200, sent.text
    assert sent.json()["ir_hash"] == vector["ir_hash"]
