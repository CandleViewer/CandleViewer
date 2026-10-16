"""Contract (E42-T01): `PUT /admin/capacity/subaccount-tier` on the real `create_app` (the RBAC
pack's world, the settings store the in-memory fake behind `build_system_settings`). The 200
validates against the schema and the generated model, the owner's write is audited with the tier
before and after, every other caller is refused before the store is touched, CSRF is enforced
(SR-041), the next capacity read shows the new tier, and the closed body matches the contract."""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest

import candleviewer.app as appmod
from candleviewer.admin.overview.capacity import TIER_CAPS
from candleviewer.admin.overview.ports import SUBACCOUNT_TIER_KEY
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.admin_capacity import TierRequest
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.ws._generated.error_codes import ErrorCode
from tests.contract.rbac.rbac_harness import World, bearer, build_world
from tests.unit.storage.fakes_system_settings import FakeSystemSettings

_SPEC: Any = load_openapi_spec()
_OP: dict[str, Any] = _SPEC["paths"]["/admin/capacity/subaccount-tier"]["put"]
_PATH = "/admin/capacity/subaccount-tier"
_ONCE = (
    "6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b"  # a client-generated UUIDv4, as the header would carry
)


def _schema(name: str) -> dict[str, Any]:
    return {"$ref": f"#/components/schemas/{name}", "components": _SPEC["components"]}


def _world(mp: pytest.MonkeyPatch, store: FakeSystemSettings | None) -> World:
    mp.setattr(appmod, "build_system_settings", lambda _settings: store)
    return build_world(mp)


def _changes(world: World) -> list[dict[str, Any]]:
    return [r for r in world.audit.records if r["action"] == "settings.change"]


def test_the_owner_records_the_tier_and_the_real_app_audits_before_and_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeSystemSettings()
    world = _world(monkeypatch, store)
    headers = bearer("owner") | {"Idempotency-Key": _ONCE}  # ignored by the contract
    response = world.client.put(_PATH, json={"tier": "business_kyc"}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    jsonschema.validate(body, _schema("SubaccountCapacity"))
    assert (
        api.SubaccountCapacity.model_validate(body).model_dump(mode="json", exclude_unset=True)
        == body
    )  # lossless through the generated model
    # the app's counts port is unwired here: `used` is `unavailable`, the tier is not
    assert (body["status"], body["tier"], body["cap"], body["tier_source"]) == (
        "unavailable", "business_kyc", 20, "recorded",
    )  # fmt: skip
    assert "used" not in body and store.rows[SUBACCOUNT_TIER_KEY].value == "business_kyc"
    (change,) = _changes(world)
    assert (change["object_kind"], change["object_id"]) == ("setting", SUBACCOUNT_TIER_KEY)
    assert change["before_state"] == {"tier": None}
    assert change["after_state"] == {"tier": "business_kyc"}
    actions = [r["action"] for r in world.audit.records]
    assert actions[-2:] == ["admin.area_entered", "settings.change"]
    # read-after-write on the real app: the next capacity read shows the new tier at once
    sub = world.client.get("/admin/capacity", headers=bearer("owner")).json()["subaccounts"]
    assert (sub["tier"], sub["cap"]) == ("business_kyc", 20)


@pytest.mark.parametrize(
    ("actor", "status", "code"),
    [
        ("manager_with_grant", 403, "forbidden"),
        ("manager_without_grant", 403, "forbidden"),
        ("viewer", 403, "forbidden"),
        # SR-041: an unsafe call with no session is refused by the CSRF guard before any route
        # runs, which is stricter than the 401 the guard itself would give (a unit test pins that)
        ("unauthenticated", 403, "csrf_token_invalid"),
    ],
)
def test_every_other_caller_is_refused_before_the_store_is_touched(
    monkeypatch: pytest.MonkeyPatch, actor: str, status: int, code: str
) -> None:
    store = FakeSystemSettings()
    world = _world(monkeypatch, store)
    response = world.client.put(_PATH, json={"tier": "business_kyc"}, headers=bearer(actor))
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert store.calls == [] and _changes(world) == []
    denied = [r for r in world.audit.records if r["action"] == "admin.area_entered"]
    assert [r["outcome"].value for r in denied] == (
        [] if actor == "unauthenticated" else ["denied"]
    )


def test_a_write_without_the_csrf_pair_is_refused_before_any_route_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeSystemSettings()
    world = _world(monkeypatch, store)
    headers = {"Authorization": bearer("owner")["Authorization"]}  # a bearer is no exemption
    response = world.client.put(_PATH, json={"tier": "business_kyc"}, headers=headers)
    assert (response.status_code, response.json()["code"]) == (403, "csrf_token_invalid")
    assert store.calls == [] and _changes(world) == []


def test_the_request_model_is_the_contracts_closed_body_and_its_example_validates() -> None:
    body = _OP["requestBody"]["content"]["application/json"]
    schema = TierRequest.model_json_schema()
    del schema["title"], schema["properties"]["tier"]["title"]
    assert schema == body["schema"]  # type object, closed, `tier` required, the two words
    assert body["schema"]["properties"]["tier"]["enum"] == list(TIER_CAPS)  # the caps' own keys
    example = body["examples"]["businessKyc"]["value"]
    assert TierRequest.model_validate(example).tier == "business_kyc"


@pytest.mark.parametrize("code", ["store_unavailable", "audit_unavailable"])
def test_the_503_codes_it_emits_are_registered(code: str) -> None:
    entry = next(e for e in _SPEC["x-error-codes"] if e["code"] == code)
    assert entry["status"] == 503 and ErrorCode(code).value == code
    assert any(e["code"] == "validation_failed" for e in _SPEC["x-error-codes"])  # the 422's code
