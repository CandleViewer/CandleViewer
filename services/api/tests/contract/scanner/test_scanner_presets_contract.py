"""E08-T09 (#4708) PR 2a: `/scanner/criteria` and the four `/scanner/presets*` operations through
the real app (session, CSRF, RBAC, the router and its service over an in-memory store) answer
only what 22-api-openapi.yaml documents, with schema-valid bodies, at each status reached below.
Not reached here: `401` on a write (the pack's unauthenticated actor has no session, so the CSRF
guard answers `403 csrf_token_invalid` first; the router tests check the route's own `401`),
`403` on the reads (every role holds `marketdata:read`; the router tests check it) and `503` on
`listScannerCriteria` (a static catalogue reads no store)."""

from __future__ import annotations

from _scanner_contract import MISSING, Api, preset

from tests.scanner_presets._scanner_env import USER_A


def _statuses(*responses: object) -> list[int]:
    return [int(getattr(r, "status_code", 0)) for r in responses]


def _huge(api: Api, op: str, preset_id: str = "") -> object:
    return api.send("manager_with_grant", op, preset_id=preset_id,
                    content=b"{" + b" " * (8 * 1024) + b"}",
                    headers={"content-type": "application/json"})  # fmt: skip


def test_list_scanner_criteria_conforms_at_200_401_and_422(api: Api) -> None:
    ok = api.send("viewer", "listScannerCriteria")
    assert len(ok.json()["items"]) == 8
    unauthenticated = api.send("unauthenticated", "listScannerCriteria")
    query = api.send("viewer", "listScannerCriteria", params={"x": "1"})
    assert _statuses(ok, unauthenticated, query) == [200, 401, 422]


def test_list_scanner_presets_conforms_at_200_401_422_and_503(api: Api) -> None:
    mine = api.create("manager_with_grant")
    listed = api.send("manager_with_grant", "listScannerPresets")
    assert [item["id"] for item in listed.json()["items"]] == [mine["id"]]
    other = api.send("owner", "listScannerPresets").json()["items"]
    assert other == []  # never another user's preset, whatever the caller's role
    unauthenticated = api.send("unauthenticated", "listScannerPresets")
    query = api.send("viewer", "listScannerPresets", params={"user_id": str(USER_A)})
    api.world.app.state.scanner_presets_repository = None
    down = api.send("viewer", "listScannerPresets")
    assert _statuses(listed, unauthenticated, query, down) == [200, 401, 422, 503]


def test_create_scanner_preset_conforms_at_every_reachable_status(api: Api) -> None:
    made = api.send("manager_with_grant", "createScannerPreset", preset())
    assert (made.json()["version"], made.json()["unavailable_criteria"]) == (1, [])
    taken = api.send("manager_with_grant", "createScannerPreset", preset(name="MOMENTUM"))
    assert taken.json()["errors"][0]["rule"] == "name_taken"
    viewer = api.send("viewer", "createScannerPreset", preset(name="v"))
    assert viewer.json()["required_permissions"] == ["workspaces:write"]
    csrf = api.send("unauthenticated", "createScannerPreset", preset(name="u"))
    huge = _huge(api, "createScannerPreset")
    invalid = api.send("manager_with_grant", "createScannerPreset", preset(version=1),
                       invalid=True)  # fmt: skip
    backwards = {"funding_rate": {"min": "0.01", "max": "0.001"}}
    inverted = api.send("manager_with_grant", "createScannerPreset", preset(filter=backwards))
    assert inverted.json()["errors"][0]["field"] == "filter.funding_rate"
    api.world.app.state.scanner_presets_repository = None
    down = api.send("manager_with_grant", "createScannerPreset", preset(name="d"))
    assert _statuses(made, taken, viewer, csrf, huge, invalid, inverted, down) == [
        201, 409, 403, 403, 413, 422, 422, 503,
    ]  # fmt: skip


def test_update_scanner_preset_conforms_at_every_reachable_status(api: Api) -> None:
    mine = api.create("manager_with_grant")
    api.create("manager_with_grant", name="Other")
    pid = mine["id"]
    ok = api.send("manager_with_grant", "updateScannerPreset", preset(name="Renamed"),
                  preset_id=pid)  # fmt: skip
    assert (ok.json()["name"], ok.json()["version"]) == ("Renamed", 2)
    foreign = api.send("owner", "updateScannerPreset", preset(), preset_id=pid)
    missing = api.send("manager_with_grant", "updateScannerPreset", preset(), preset_id=MISSING)
    assert foreign.content == missing.content  # another user's preset reads as a missing one
    taken = api.send("manager_with_grant", "updateScannerPreset", preset(name="OTHER"),
                     preset_id=pid)  # fmt: skip
    bad_id = api.send("manager_with_grant", "updateScannerPreset", preset(), preset_id="x")
    viewer = api.send("viewer", "updateScannerPreset", preset(), preset_id=pid)
    huge = _huge(api, "updateScannerPreset", pid)
    api.world.app.state.scanner_presets_repository = None
    down = api.send("manager_with_grant", "updateScannerPreset", preset(), preset_id=pid)
    assert _statuses(ok, foreign, missing, taken, bad_id, viewer, huge, down) == [
        200, 404, 404, 409, 422, 403, 413, 503,
    ]  # fmt: skip


def test_delete_scanner_preset_conforms_at_every_reachable_status(api: Api) -> None:
    pid = api.create("manager_with_grant")["id"]
    viewer = api.send("viewer", "deleteScannerPreset", preset_id=pid)
    foreign = api.send("owner", "deleteScannerPreset", preset_id=pid)
    bad_id = api.send("manager_with_grant", "deleteScannerPreset", preset_id="x")
    query = api.send("manager_with_grant", "deleteScannerPreset", preset_id=pid,
                     params={"hard": "true"})  # fmt: skip
    deleted = api.send("manager_with_grant", "deleteScannerPreset", preset_id=pid)
    again = api.send("manager_with_grant", "deleteScannerPreset", preset_id=pid)
    assert pid not in api.repo.rows  # hard delete
    api.world.app.state.scanner_presets_repository = None
    down = api.send("manager_with_grant", "deleteScannerPreset", preset_id=pid)
    assert _statuses(viewer, foreign, bad_id, query, deleted, again, down) == [
        403, 404, 422, 422, 204, 404, 503,
    ]  # fmt: skip


def test_writes_leave_their_audit_records_in_the_app_sink(api: Api) -> None:
    mine = api.create("manager_with_grant")
    api.send("owner", "deleteScannerPreset", preset_id=mine["id"])  # another user's: denied
    api.send("manager_with_grant", "deleteScannerPreset", preset_id=mine["id"])
    actions = [r["action"] for r in api.world.audit.records]
    assert "scanner_preset.created" in actions and "scanner_preset.deleted" in actions
    assert actions.count("rbac.denied") == 1
