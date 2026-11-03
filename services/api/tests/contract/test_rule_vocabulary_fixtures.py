"""Server-written rule vocabulary fixtures (E37-S02, #1068): what `GET /rules/vocabulary` serves.

``packages/fixtures/golden/rule-graph/vocabulary/<persona>.json`` holds, per persona, the body
``build_vocabulary(default_registry(), ...)`` builds for that caller, which the route serves as is:
the node-graph editor's model (``apps/web/src/features/rule-builder-graph/model/vocabulary/``) is
tested on these, so no client test writes a vocabulary by hand. The personas are the permission
sets the route probes (``api/rules.py`` ``_ADVISORY_PERMISSIONS``), read from the seeded roles: the
Owner, the seeded Manager, a role without ``orders:write``, and the Manager scoped to a symbol that
is not recorded. Regenerate from ``services/api`` and review the diff (nothing is written
otherwise): ``CV_REGEN_GOLDEN=1 uv run pytest tests/contract/test_rule_vocabulary_fixtures.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.rules import make_rules_router
from candleviewer.rules.vocabulary import build_vocabulary, default_registry
from candleviewer.rules.vocabulary.catalogue import ARM_LIVE_PERMISSION

GOLDEN = Path(__file__).resolve().parents[4] / "packages/fixtures/golden/rule-graph/vocabulary"
SEED = json.loads(
    (Path(__file__).parents[2] / "candleviewer/auth/rbac_seed.json").read_text(encoding="utf-8")
)
REGEN = os.environ.get("CV_REGEN_GOLDEN") == "1"
REGEN_CMD = "CV_REGEN_GOLDEN=1 uv run pytest tests/contract/test_rule_vocabulary_fixtures.py"
#: The permissions the route probes; the rest of a role's grants never reach the vocabulary.
PROBED = ("orders:write", ARM_LIVE_PERMISSION)
#: The recorded-symbol list of the symbol-scoped persona: SOLUSDT is not on it.
RECORDED = ("BTCUSDT",)


def granted(role: str) -> tuple[str, ...]:
    """The probed permissions a seeded role holds (the Owner's ``*`` holds them all)."""
    perms = SEED["role_permissions"][role]
    return tuple(p for p in PROBED if p in perms or "*" in perms)


#: persona -> (the principal's grants, the request's symbol).
PERSONAS: dict[str, tuple[tuple[str, ...], str | None]] = {
    "owner": (granted("owner"), None),
    "manager": (granted("manager"), None),
    "no-orders-write": (granted("viewer"), None),
    "unrecorded-solusdt": (granted("manager"), "SOLUSDT"),
}


def built(persona: str) -> dict[str, Any]:
    perms, symbol = PERSONAS[persona]
    return build_vocabulary(
        default_registry(), permissions=perms, symbol=symbol, recorded_symbols=RECORDED
    )


def compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def text_of(body: dict[str, Any]) -> str:
    """The file: the top-level keys sorted, each list one compact entry per line (the hash vectors'
    layout, so a changed entry is a changed line), LF and a final newline on every platform."""
    parts = []
    for key in sorted(body):
        value = body[key]
        if isinstance(value, list) and value:
            rows = ",\n    ".join(compact(item) for item in value)
            parts.append(f"  {json.dumps(key)}: [\n    {rows}\n  ]")
        else:
            parts.append(f"  {json.dumps(key)}: {compact(value)}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


class _Principal:
    def __init__(self, perms: tuple[str, ...]) -> None:
        self.perms = {"rules:read", *perms}

    def has(self, perm: str) -> bool:
        return perm in self.perms


class _Resolver:
    def __init__(self, principal: _Principal) -> None:
        self.principal = principal

    def resolve(self, request: object) -> _Principal:
        return self.principal


def test_the_personas_are_the_seeded_roles_grants() -> None:
    assert {p: perms for p, (perms, _) in PERSONAS.items()} == {
        "owner": ("orders:write", "rules:arm_live"),
        "manager": ("orders:write",),
        "no-orders-write": (),
        "unrecorded-solusdt": ("orders:write",),
    }


@pytest.mark.parametrize("persona", sorted(PERSONAS))
def test_each_vocabulary_fixture_is_what_the_server_builds(persona: str) -> None:
    path, text = GOLDEN / f"{persona}.json", text_of(built(persona))
    if REGEN:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.read_bytes() == text.encode(), f"{persona}: regenerate with `{REGEN_CMD}`"


@pytest.mark.parametrize("persona", sorted(PERSONAS))
def test_the_route_serves_each_fixture_to_its_persona(persona: str) -> None:
    perms, symbol = PERSONAS[persona]
    app = FastAPI()
    router = make_rules_router(
        default_registry,
        principal_resolver=_Resolver(_Principal(perms)),
        recorded_symbols=lambda: frozenset(RECORDED),
    )
    app.include_router(router)
    params = {} if symbol is None else {"symbol": symbol}
    response = TestClient(app).get("/rules/vocabulary", params=params)
    assert response.status_code == 200
    assert response.json() == json.loads((GOLDEN / f"{persona}.json").read_text(encoding="utf-8"))


def test_the_fixtures_differ_where_the_personas_do() -> None:
    by = {p: json.loads((GOLDEN / f"{p}.json").read_text(encoding="utf-8")) for p in PERSONAS}
    gated = {
        p: sorted(a["id"] for a in body["actions"] if not a["available"]) for p, body in by.items()
    }
    assert gated["owner"] == []
    assert gated["manager"] == gated["unrecorded-solusdt"] == ["resume_new_orders"]
    simulate = sorted(a["id"] for a in by["no-orders-write"]["actions"] if a["simulate_only"])
    assert simulate == sorted(a["id"] for a in by["owner"]["actions"] if a["places_orders"])
    unavailable = [s for s in by["unrecorded-solusdt"]["signals"] if not s["available"]]
    assert unavailable and all(s["missing_dependency"]["symbol"] == "SOLUSDT" for s in unavailable)
    assert all(s["available"] for p in ("owner", "manager") for s in by[p]["signals"])
