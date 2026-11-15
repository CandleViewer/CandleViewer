"""#5993 (E35): what a rule version holds, read (`getRuleVersion`) and listed (`listRuleVersions`).

`ir`, `ir_hash` and `graph_layout` are answered on `getRuleVersion`; listing versions answers
`RuleVersion` items without `ir` and `graph_layout`.
"""

from __future__ import annotations

import copy
import uuid
from typing import cast

from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleRow
from tests.contract._admin_support import validate_example
from tests.rules.test_rules_routes import _Env, _ir

DETAIL_SCHEMA = "/components/schemas/RuleVersionDetail"
VERSION_SCHEMA = "/components/schemas/RuleVersion"
CORE = {"ir_version", "trigger", "conditions", "actions", "scope", "limits"}
LOADED = {"c1": {"x": 0, "y": 0}}
MOVED = {"c1": {"x": 240, "y": 120}}
VALID_UUID = str(uuid.UUID(int=1))


def _row(e: _Env, rid: str) -> RuleRow:
    return cast(InMemoryRuleStore, e.mgr._s)._rows[rid]


def test_get_rule_version_answers_the_rule_version_detail_22_declares() -> None:
    e = _Env(uid=VALID_UUID)
    rid = e.create()
    (v1,) = _row(e, rid).versions
    got = e.c.get(f"/rules/{rid}/versions/{v1.id}").json()

    assert got["id"] == v1.id
    assert got["rule_id"] == rid
    assert got["version"] == 1
    assert got["ir_hash"] == v1.ir_hash
    assert got["is_active"] is True
    assert got["created_by"] == VALID_UUID
    assert "created_at" in got
    assert got["graph_layout"] == LOADED
    assert set(got["ir"]) == CORE
    assert not {"author", "notes", "compiler_version"} & set(got)
    validate_example(DETAIL_SCHEMA, got)


def test_list_rule_versions_answers_rule_version_items() -> None:
    e = _Env(uid=VALID_UUID)
    rid = e.create()
    put_res = e.c.put(
        f"/rules/{rid}",
        json={"ir": _ir("66000.00", graph_layout=MOVED), "note": "v2 update"},
        headers={"If-Match": "1"},
    )
    assert put_res.status_code == 200

    listed = e.c.get(f"/rules/{rid}/versions").json()
    items = listed["items"]
    assert len(items) == 2

    for item in items:
        validate_example(VERSION_SCHEMA, item)
        assert {"id", "rule_id", "version", "ir_hash", "is_active"} <= set(item)
        assert not {"ir", "graph_layout", "author", "notes", "compiler_version"} & set(item)


async def test_rule_version_detail_is_a_copy_never_mutating_stored_version() -> None:
    e = _Env(uid=VALID_UUID)
    rid = e.create()
    (v1,) = _row(e, rid).versions
    held = copy.deepcopy(v1.ir)
    detail = await e.mgr.version_for(
        rid, v1.id, Actor(VALID_UUID, "s1", frozenset({"rules:read"}), is_owner=True)
    )
    assert detail["ir"] is not None
    detail["ir"]["actions"][0]["params"]["template"] = "changed"
    assert detail["graph_layout"] is not None
    detail["graph_layout"]["c1"]["x"] = 999
    assert v1.ir == held


def test_quarantined_version_omits_ir_and_nulls_graph_layout() -> None:
    e = _Env(uid=VALID_UUID)
    rid = e.create()
    row = _row(e, rid)
    row.versions[0].ir["conditions"] = {"corrupt": True}
    v1_id = row.versions[0].id

    detail = e.c.get(f"/rules/{rid}/versions/{v1_id}").json()
    assert detail["id"] == v1_id
    assert detail["graph_layout"] is None
    assert "ir" not in detail
