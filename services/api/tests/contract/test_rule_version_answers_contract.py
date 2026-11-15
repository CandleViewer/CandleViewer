"""#5993 (E35): `getRuleVersion` and `listRuleVersions` answer the `RuleVersionDetail` and
`RuleVersion` 22 declares.

A read answers the version with its `RuleIr` (closed), its `version`, `is_active`, `rule_id`,
`created_by`, `created_at`, `note` and `graph_layout`; listing versions answers `RuleVersion` items
without `ir` and `graph_layout`, and without old members `author`, `notes` or `compiler_version`.
Each answer is validated against the route's own 200 schema in 22 through `validate_example`.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.rules.ir.models import Rule
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.contract._admin_support import validate_example
from tests.contract._rule_save_support import owner_client, rule_ir, save_body

_SPEC: Any = load_openapi_spec()
RULE_IR = frozenset(_SPEC["components"]["schemas"]["RuleIr"]["properties"])
_CORPUS = {
    path.stem: json.loads(path.read_text(encoding="utf-8"), parse_float=str)
    for path in sorted((Path(__file__).parents[1] / "fixtures/rule_ir").glob("*.json"))
}
OWNER_ID = str(uuid.UUID(int=1))
OWNER = Actor(OWNER_ID, "s1", frozenset({"rules:read", "rules:write"}), is_owner=True)

GET_VERSION_SCHEMA = (
    "/paths/~1rules~1{ruleId}~1versions~1{versionId}"
    "/get/responses/200/content/application~1json/schema"
)
LIST_VERSIONS_SCHEMA = (
    "/paths/~1rules~1{ruleId}~1versions/get/responses/200/content/application~1json/schema"
)


def _rebuilt(stored: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    """What the server's model reads from an answered detail's `ir` and `graph_layout` and the
    stored version's other members: what it reads from the stored version when the answer drops
    nothing."""
    envelope = {k: v for k, v in stored.items() if k not in RULE_IR | {"graph_layout"}}
    answered = {**envelope, **detail["ir"], "graph_layout": detail["graph_layout"]}
    return Rule.model_validate(answered).model_dump(mode="json")


def test_get_rule_version_answers_the_rule_version_detail_22_declares() -> None:
    """Scenario: the version read answers the RuleVersionDetail 22 declares."""
    client = owner_client()
    made = client.post("/rules", json=save_body("RuleInput", "v1", rule_ir(level="global")))
    assert made.status_code == 201, made.text
    rid = made.json()["id"]

    layout = {"n1": {"x": 100, "y": 200}, "comment": "node layout"}
    v2_ir = rule_ir("2", level="global")
    saved = client.put(
        f"/rules/{rid}",
        json={
            **save_body("RuleUpdateInput", "v2", v2_ir),
            "graph_layout": layout,
            "note": "second",
        },
        headers={"If-Match": '"1"'},
    )
    assert saved.status_code == 200, saved.text
    v2_id = saved.json()["active_version_id"]

    # Read the newer version with GET /rules/{ruleId}/versions/{versionId}
    got = client.get(f"/rules/{rid}/versions/{v2_id}")
    assert got.status_code == 200, got.text
    body = got.json()

    # Validate against 22 schema
    validate_example(GET_VERSION_SCHEMA, body)

    # Carries id, rule_id, version, ir_hash, is_active, created_by, created_at, note
    assert body["id"] == v2_id
    assert body["rule_id"] == rid
    assert body["version"] == 2
    assert "ir_hash" in body
    assert body["is_active"] is True
    assert body["created_by"] == OWNER_ID
    assert "created_at" in body
    assert body["note"] == "second"

    # ir holds only RuleIr's members
    assert set(body["ir"]).issubset(RULE_IR)
    assert not {"name", "mode", "enabled", "version", "rule_id"} & set(body["ir"])

    # graph_layout is a top-level member holding the saved layout
    assert body["graph_layout"] == layout

    # And neither author, notes nor compiler_version is answered
    assert not {"author", "notes", "compiler_version"} & set(body)


@pytest.mark.parametrize("shape", list(_CORPUS))
async def test_every_stored_ir_shape_reads_as_22s_rule_version_detail_and_loses_nothing(
    shape: str,
) -> None:
    """Scenario Outline: nothing a version stored is lost."""
    m = RulesManager(InMemoryRuleStore(), default_registry())
    rid = (await m.create({**rule_ir(level="global"), "name": "shape"}, OWNER))["id"]
    stored = copy.deepcopy(_CORPUS[shape])
    row = await m._s.get(rid)
    assert row is not None
    row.versions[0].ir = stored
    vid = row.versions[0].id

    detail = await m.version_for(rid, vid, OWNER)
    validate_example(GET_VERSION_SCHEMA, detail)
    assert _rebuilt(stored, detail) == Rule.model_validate(stored).model_dump(mode="json")


def test_list_rule_versions_answers_rule_version_items() -> None:
    """Scenario: listRuleVersions agrees."""
    client = owner_client()
    made = client.post("/rules", json=save_body("RuleInput", "v1", rule_ir(level="global")))
    assert made.status_code == 201, made.text
    rid = made.json()["id"]

    saved = client.put(
        f"/rules/{rid}",
        json={**save_body("RuleUpdateInput", "v2", rule_ir("2", level="global")), "note": "rev2"},
        headers={"If-Match": '"1"'},
    )
    assert saved.status_code == 200, saved.text

    listed = client.get(f"/rules/{rid}/versions")
    assert listed.status_code == 200, listed.text
    data = listed.json()

    validate_example(LIST_VERSIONS_SCHEMA, data)
    items = data["items"]
    assert len(items) == 2

    for item in items:
        assert {
            "id",
            "rule_id",
            "version",
            "ir_hash",
            "is_active",
            "created_by",
            "created_at",
        } <= set(item)
        assert not {"ir", "graph_layout", "author", "notes", "compiler_version"} & set(item)


async def test_is_active_created_by_and_created_at_semantics() -> None:
    """Scenario: is_active, created_by and created_at."""
    m = RulesManager(InMemoryRuleStore(), default_registry())
    rid = (await m.create({**rule_ir(level="global"), "name": "active-test"}, OWNER, notes="init"))[
        "id"
    ]
    row = await m._s.get(rid)
    assert row is not None
    v1 = row.versions[0]

    # Move to simulate mode so subsequent save keeps running previous active version
    await m.set_mode(rid, "simulate", OWNER, "key-sim")

    # Create v2 without activating it
    v2_ir = rule_ir("2", level="global")
    await m.update(rid, v2_ir, 1, OWNER, notes="second-ver")
    row = await m._s.get(rid)
    assert row is not None
    assert len(row.versions) == 2
    v2 = row.versions[-1]

    # Add v3 whose stored document records no author id and no time
    raw_doc = Rule.model_validate(
        {
            **rule_ir("3", level="global"),
            "name": "v3",
            "rule_id": rid,
            "mode": "disabled",
            "enabled": False,
        }
    ).model_dump(mode="json")
    raw_doc.pop("created_by", None)
    raw_doc.pop("created_at", None)
    raw_doc.pop("updated_at", None)
    v3 = copy.deepcopy(v1)
    v3.id = str(uuid.uuid4())
    v3.version = 3
    v3.author = ""  # no author id
    v3.notes = ""
    v3.ir = raw_doc  # no created_by or updated_at
    row.versions.append(v3)
    row.latest_version = 3

    # Read versions through version_for / versions_for
    v1_view = await m.version_for(rid, v1.id, OWNER)
    v2_view = await m.version_for(rid, v2.id, OWNER)
    v3_view = await m.version_for(rid, v3.id, OWNER)

    # is_active is true for the active version only
    assert v1_view["is_active"] is True
    assert v2_view["is_active"] is False
    assert v3_view["is_active"] is False

    # created_by is the writing user's id as a UUID
    assert v1_view["created_by"] == OWNER_ID
    assert v2_view["created_by"] == OWNER_ID
    # version recording no author id leaves created_by out, never null
    assert "created_by" not in v3_view

    # created_at is RFC 3339 UTC to microsecond
    assert v1_view["created_at"].endswith("Z")
    assert "created_at" in v2_view
    # version recording no time leaves created_at out, never null
    assert "created_at" not in v3_view

    # notes left out when not recorded
    assert "note" not in v3_view


async def test_a_version_the_engine_cannot_read() -> None:
    """Scenario: a version the engine cannot read."""
    m = RulesManager(InMemoryRuleStore(), default_registry())
    rid = (await m.create({**rule_ir(level="global"), "name": "quarantine-test"}, OWNER))["id"]
    row = await m._s.get(rid)
    assert row is not None
    # Corrupt version document
    row.versions[0].ir["conditions"] = {"bogus": 1}
    vid = row.versions[0].id

    detail = await m.version_for(rid, vid, OWNER)
    assert "ir" not in detail
    assert detail["graph_layout"] is None
    assert detail["id"] == vid
    assert detail["version"] == 1


def test_scope_and_refusals_stay_as_they_are() -> None:
    """Scenario: scope and refusals stay as they are."""
    mgr = RulesManager(InMemoryRuleStore(), default_registry())

    def resolve(request: Request) -> Actor | None:
        auth = request.headers.get("authorization", "")
        if auth == "Bearer owner":
            return Actor(OWNER_ID, "s1", frozenset({"rules:read", "rules:write"}), is_owner=True)
        if auth == "Bearer no-read":
            return Actor("u2", "s2", frozenset({"orders:write"}))
        return None

    app = FastAPI()
    app.include_router(make_rules_crud_router(lambda: mgr, resolve))
    client = TestClient(app, headers={"authorization": "Bearer owner"})

    made = client.post("/rules", json=save_body("RuleInput", "scope-test", rule_ir(level="global")))
    assert made.status_code == 201, made.text
    rid = made.json()["id"]
    vid = made.json()["active_version_id"]

    missing_rid = str(uuid.uuid4())
    missing_vid = str(uuid.uuid4())

    # 404 of missing rule
    assert client.get(f"/rules/{missing_rid}/versions").status_code == 404
    assert client.get(f"/rules/{missing_rid}/versions/{missing_vid}").status_code == 404

    # 404 of missing version on real rule
    res = client.get(f"/rules/{rid}/versions/{missing_vid}")
    assert res.status_code == 404, res.text
    assert res.json()["detail"] == "That version does not exist."

    # Unauthenticated / unauthorized
    anon = TestClient(app)
    assert anon.get(f"/rules/{rid}/versions").status_code == 401
    assert anon.get(f"/rules/{rid}/versions/{vid}").status_code == 401

    no_read = TestClient(app, headers={"authorization": "Bearer no-read"})
    assert no_read.get(f"/rules/{rid}/versions").status_code == 403
    assert no_read.get(f"/rules/{rid}/versions/{vid}").status_code == 403
