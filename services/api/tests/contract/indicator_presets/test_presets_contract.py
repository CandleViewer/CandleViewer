"""E13-T03 (#427): the four `/indicator-presets*` operations through the real app (session,
CSRF, RBAC, the router and its service over an in-memory store) answer only what
22-api-openapi.yaml documents, with schema-valid bodies, at each status the tests below reach.
Three declared statuses are not reached here. `404` on the two collection operations cannot
occur: no collection operation reads a stored preset by id. `401` on a write: the pack's
unauthenticated actor has no session, so the CSRF guard answers first (`403`
`csrf_token_invalid`); an expired bearer of a live session would reach the route's `401`, and
the pack mints none. `403` on the list: every role holds `workspaces:read`. The router tests
check those two by status (`tests/indicator_presets/test_presets_api_rbac.py`)."""

from __future__ import annotations

from _presets_contract import MISSING, Api, preset

from tests.contract.rbac.rbac_harness import user_id_of
from tests.indicator_presets._presets_env import EMA9


def _statuses(*responses: object) -> list[int]:
    return [int(getattr(r, "status_code", 0)) for r in responses]


def test_list_indicator_presets_conforms_at_200_401_422_and_503(api: Api) -> None:
    mine = api.create("manager_with_grant")
    listed = api.send("manager_with_grant", "listIndicatorPresets")
    ids = [item["id"] for item in listed.json()["items"]]
    assert EMA9 in ids and mine["id"] in ids and len(ids) == 19
    assert ids.index(EMA9) < ids.index(mine["id"])  # built-ins first
    other = api.send("owner", "listIndicatorPresets").json()["items"]
    assert mine["id"] not in {item["id"] for item in other}  # whatever the caller's role
    unauthenticated = api.send("unauthenticated", "listIndicatorPresets")
    query = api.send("viewer", "listIndicatorPresets", params={"owner_user_id": MISSING})
    api.world.app.state.indicator_presets_repository = None
    down = api.send("viewer", "listIndicatorPresets")
    assert _statuses(listed, unauthenticated, query, down) == [200, 401, 422, 503]


def test_create_indicator_preset_conforms_at_every_reachable_status(api: Api) -> None:
    made = api.send("manager_with_grant", "createIndicatorPreset", preset())
    owner = str(user_id_of("manager_with_grant"))
    assert (made.json()["is_builtin"], made.json()["owner_user_id"]) == (False, owner)
    taken = api.send("manager_with_grant", "createIndicatorPreset", preset(name="atr 14"))
    assert taken.json()["errors"][0]["rule"] == "name_taken"
    viewer = api.send("viewer", "createIndicatorPreset", preset(name="v"))
    assert viewer.json()["required_permissions"] == ["workspaces:write"]
    csrf = api.send("unauthenticated", "createIndicatorPreset", preset(name="u"))
    huge = api.send("manager_with_grant", "createIndicatorPreset",
                    content=b"{" + b" " * (16 * 1024) + b"}",
                    headers={"content-type": "application/json"})  # fmt: skip
    invalid = api.send("manager_with_grant", "createIndicatorPreset",
                       preset(is_builtin=True), invalid=True)  # fmt: skip
    api.world.app.state.indicator_presets_repository = None
    down = api.send("manager_with_grant", "createIndicatorPreset", preset(name="d"))
    assert _statuses(made, taken, viewer, csrf, huge, invalid, down) == [
        201, 409, 403, 403, 413, 422, 503,
    ]  # fmt: skip


def test_update_indicator_preset_conforms_at_every_reachable_status(api: Api) -> None:
    mine = api.create("manager_with_grant")
    api.create("manager_with_grant", name="Other")
    pid = mine["id"]
    ok = api.send("manager_with_grant", "updateIndicatorPreset", preset(name="Renamed"),
                  preset_id=pid)  # fmt: skip
    assert ok.json()["name"] == "Renamed" and ok.json()["id"] == pid
    foreign = api.send("owner", "updateIndicatorPreset", preset(), preset_id=pid)
    missing = api.send("manager_with_grant", "updateIndicatorPreset", preset(), preset_id=MISSING)
    assert foreign.content == missing.content  # another user's preset reads as a missing one
    builtin = api.send("manager_with_grant", "updateIndicatorPreset",
                       preset(indicator_code="ema", params={"n": 9}), preset_id=EMA9)  # fmt: skip
    assert builtin.json()["errors"][0]["rule"] == "builtin_immutable"
    taken = api.send("manager_with_grant", "updateIndicatorPreset", preset(name="OTHER"),
                     preset_id=pid)  # fmt: skip
    immutable = api.send("manager_with_grant", "updateIndicatorPreset",
                         preset(indicator_code="ema", params={"n": 9}), preset_id=pid)  # fmt: skip
    assert immutable.json()["errors"][0]["rule"] == "immutable_field"
    bad_id = api.send("manager_with_grant", "updateIndicatorPreset", preset(), preset_id="x")
    viewer = api.send("viewer", "updateIndicatorPreset", preset(), preset_id=pid)
    huge = api.send("manager_with_grant", "updateIndicatorPreset", preset_id=pid,
                    content=b"{" + b" " * (16 * 1024) + b"}",
                    headers={"content-type": "application/json"})  # fmt: skip
    api.world.app.state.indicator_presets_repository = None
    down = api.send("manager_with_grant", "updateIndicatorPreset", preset(), preset_id=pid)
    assert _statuses(ok, foreign, missing, builtin, taken, immutable, bad_id, viewer, huge,
                     down) == [200, 404, 404, 403, 409, 422, 422, 403, 413, 503]  # fmt: skip


def test_delete_indicator_preset_conforms_at_every_reachable_status(api: Api) -> None:
    mine = api.create("manager_with_grant")
    pid = mine["id"]
    viewer = api.send("viewer", "deleteIndicatorPreset", preset_id=pid)
    foreign = api.send("owner", "deleteIndicatorPreset", preset_id=pid)
    builtin = api.send("manager_with_grant", "deleteIndicatorPreset", preset_id=EMA9)
    bad_id = api.send("manager_with_grant", "deleteIndicatorPreset", preset_id="x")
    query = api.send("manager_with_grant", "deleteIndicatorPreset", preset_id=pid,
                     params={"hard": "true"})  # fmt: skip
    deleted = api.send("manager_with_grant", "deleteIndicatorPreset", preset_id=pid)
    again = api.send("manager_with_grant", "deleteIndicatorPreset", preset_id=pid)
    assert pid in api.repo.rows and pid in api.repo.deleted  # soft: the row stays
    api.world.app.state.indicator_presets_repository = None
    down = api.send("manager_with_grant", "deleteIndicatorPreset", preset_id=pid)
    assert _statuses(viewer, foreign, builtin, bad_id, query, deleted, again, down) == [
        403, 404, 403, 422, 422, 204, 404, 503,
    ]  # fmt: skip


def test_422_conforms_to_unprocessable_entity_and_names_each_field(api: Api) -> None:
    cases = [
        (preset(params={"n": 0}), "params.n", "minimum"),
        (preset(params={"n": 14, "x": 1}), "params", "additionalProperties"),
        (preset(indicator_code="nope"), "indicator_code", "unknown_indicator"),
        (preset(style={"line": "#ff0000"}), "style", "style_not_allowed"),
        (preset(params={"k": "v" * 5000}), "params", "params_too_large"),
    ]
    for body, field, rule in cases:
        schema_valid = rule in ("minimum", "additionalProperties", "unknown_indicator",
                                "params_too_large")  # fmt: skip
        r = api.send("manager_with_grant", "createIndicatorPreset", body, invalid=not schema_valid)
        assert r.status_code == 422
        assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [(field, rule)]
    assert not any(name == "create" for name, _ in api.repo.calls)  # nothing was stored


def test_writes_leave_their_audit_records_in_the_app_sink(api: Api) -> None:
    mine = api.create("manager_with_grant")
    api.send("manager_with_grant", "deleteIndicatorPreset", preset_id=mine["id"])
    api.send("manager_with_grant", "deleteIndicatorPreset", preset_id=EMA9)
    actions = [r["action"] for r in api.world.audit.records]
    assert "indicator_preset.created" in actions and "indicator_preset.deleted" in actions
    assert actions.count("rbac.denied") == 1
