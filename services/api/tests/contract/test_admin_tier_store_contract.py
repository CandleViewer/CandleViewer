"""Contract (E42-T01): the real `create_app` reports the recorded sub-account tier from the
`settings` store (US-ADMIN-014: "an explicit recorded fact, never inferred"). The store is the
in-memory fake behind the app's `build_system_settings` seam (the RBAC pack's world: identity and
backend faked, no network); its counts port is unwired, so only the usage part of the slice is
`unavailable`. Every body validates against the contract schema and the generated model."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import jsonschema
import pytest

import candleviewer.app as appmod
from candleviewer.admin.overview.ports import SUBACCOUNT_TIER_KEY
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.storage.repositories.system_settings import StoredSetting
from tests.contract.rbac.rbac_harness import bearer, build_world
from tests.unit.storage.fakes_system_settings import FakeSystemSettings

_SPEC: Any = load_openapi_spec()
_REPORT = {"$ref": "#/components/schemas/CapacityReport", "components": _SPEC["components"]}
_FIELDS = ("tier", "cap", "tier_source", "recorded_at")


def _subaccounts(monkeypatch: pytest.MonkeyPatch, store: FakeSystemSettings) -> dict[str, Any]:
    monkeypatch.setattr(appmod, "build_system_settings", lambda _settings: store)
    response = build_world(monkeypatch).client.get("/admin/capacity", headers=bearer("owner"))
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    jsonschema.validate(body, _REPORT)
    lossless = api.CapacityReport.model_validate(body).model_dump(mode="json", exclude_unset=True)
    assert lossless == body
    sub: dict[str, Any] = body["subaccounts"]
    return sub


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("regular", ("regular", 5, "recorded", "2026-10-01T09:00:00Z")),
        ("business_kyc", ("business_kyc", 20, "recorded", "2026-10-01T09:00:00Z")),
        (None, (None, None, "unrecorded", None)),
    ],
    ids=["regular", "business-kyc", "unrecorded"],
)
def test_the_real_app_reports_the_recorded_tier_its_cap_or_that_none_was_recorded(
    monkeypatch: pytest.MonkeyPatch, word: str | None, expected: tuple[Any, ...]
) -> None:
    store = FakeSystemSettings()
    if word is not None:
        store.rows[SUBACCOUNT_TIER_KEY] = StoredSetting(word, datetime(2026, 10, 1, 9, tzinfo=UTC))
    sub = _subaccounts(monkeypatch, store)
    assert tuple(sub[k] for k in _FIELDS) == expected
    assert store.calls == [("get", SUBACCOUNT_TIER_KEY)]  # read, never written


def test_the_real_app_never_defaults_the_tier_when_the_store_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeSystemSettings()
    store.down = True
    sub = _subaccounts(monkeypatch, store)
    assert (sub["status"], sub["detail"]) == ("error", "tier: source failed")
    assert not set(_FIELDS) & set(sub)  # omitted, not defaulted
