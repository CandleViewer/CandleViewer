"""E35-T03: rule vocabulary registry projection and GET /rules/vocabulary."""

from __future__ import annotations

import json
import typing
from pathlib import Path

import jsonschema
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.rules import make_rules_router
from candleviewer.rules.ir.models import ActionType, ComparisonOp, TriggerType
from candleviewer.rules.ir.schema import to_json_schema
from candleviewer.rules.vocabulary import (
    MetricDescriptor,
    MetricRegistry,
    build_vocabulary,
    default_registry,
    etag_for,
    undescribed_metrics,
)
from candleviewer.rules.vocabulary import build as vbuild
from candleviewer.rules.vocabulary.catalogue import ACTIONS, OPERATORS, TRIGGERS
from candleviewer.rules.vocabulary.registry import DuplicateMetricError

GOLDEN = Path(__file__).parents[2] / "candleviewer/rules/vocabulary/metric_names.golden.txt"
SPEC = Path(__file__).parents[4] / "docs/plan/22-api-openapi.yaml"
UNITS = {"price", "qty", "notional", "ratio", "pct", "bps", "count", "ms", "zscore", "enum", "bool"}


class _P:
    def __init__(self, *perms: str) -> None:
        self.perms = set(perms)

    def has(self, p: str) -> bool:
        return "*" in self.perms or p in self.perms


class _Resolver:
    def __init__(self, principal: _P | None) -> None:
        self.principal = principal

    def resolve(self, request: object) -> _P | None:
        return self.principal


def _client(
    principal: _P | None,
    registry: MetricRegistry | None = None,
    recorded: frozenset[str] = frozenset(),
) -> TestClient:
    app = FastAPI()
    reg = default_registry() if registry is None else registry
    app.include_router(
        make_rules_router(
            lambda: reg, principal_resolver=_Resolver(principal), recorded_symbols=lambda: recorded
        )
    )
    return TestClient(app)


def _vocab(**kw: typing.Any) -> dict[str, typing.Any]:
    return build_vocabulary(default_registry(), **kw)


def test_catalogue_is_complete() -> None:
    """Scenario: The documented catalogue is complete"""
    ids = {s["id"] for s in _vocab()["signals"]}
    need = {
        "price", "unrealised_r_multiple", "atr", "ema", "sma", "swing_high", "swing_low", "cvd",
        "cvd_divergence", "delta_divergence", "delta", "stacked_imbalance_zone", "absorption",
        "stop_run_detected", "iceberg_present_at_level", "tape_speed_zscore", "book_speed",
        "market_regime", "spread_bps", "funding_rate", "time_to_funding_ms", "open_interest_delta",
        "time_in_trade_ms", "unrealised_pnl", "account_equity", "drawdown_pct",
    }  # fmt: skip
    assert need <= ids
    for s in _vocab()["signals"]:
        assert s["unit"] in UNITS and s["description"]


def test_estimated_metrics_are_badged() -> None:
    """Scenario: Estimated metrics are badged"""
    by = {s["id"]: s for s in _vocab()["signals"]}
    for name in ("iceberg_present_at_level", "stop_run_detected", "absorption", "market_regime"):
        assert by[name]["estimated"] is True
    assert by["atr"]["estimated"] is False
    for d in default_registry():
        assert by[d.name]["estimated"] == (d.confidence != "exact")


def test_unavailable_metric_names_dependency() -> None:
    """Scenario: Unavailable metric names its dependency (edge case)"""
    voc = _vocab(symbol="DOGEUSDT", recorded_symbols={"BTCUSDT"})
    by = {s["id"]: s for s in voc["signals"]}
    s = by["tape_speed"]
    assert s["available"] is False and s["requires_recording"] is True
    assert s["missing_dependency"]["symbol"] == "DOGEUSDT"
    assert s["recorder_action"]["path"] == "/api/v1/recording/symbols"
    assert by["atr"]["available"] is True
    voc2 = _vocab(symbol="BTCUSDT", recorded_symbols={"BTCUSDT"})
    assert {s["id"]: s for s in voc2["signals"]}["tape_speed"]["available"] is True


def test_actions_declare_permission_simulate_only() -> None:
    """Scenario: Actions declare their permission (failure case)"""
    acts = {a["id"]: a for a in _vocab(permissions=())["actions"]}
    po = acts["place_order"]
    assert po["simulate_only"] is True and po["available"] is False
    assert "simulate" in po["restriction"]
    assert acts["widen_stop"]["loosens_risk"] is True
    full = {
        a["id"]: a for a in _vocab(permissions={"orders:write", "rules.loosen_stop"})["actions"]
    }
    assert full["place_order"]["simulate_only"] is False and full["widen_stop"]["available"]


def test_registry_is_single_source() -> None:
    """Scenario: The registry is the single source (regression guard)"""
    assert undescribed_metrics(default_registry()) == []
    reg = default_registry()
    reg.register(MetricDescriptor(name="brand_new_metric", title="X", unit="count"))
    assert undescribed_metrics(reg) == ["brand_new_metric"]
    with pytest.raises(DuplicateMetricError):
        reg.register(MetricDescriptor(name="brand_new_metric", title="X", unit="count"))


def test_metric_names_match_golden() -> None:
    golden = GOLDEN.read_text().split()
    assert golden == default_registry().names(), "renamed/removed metric needs an IR upcaster"


def test_every_enum_member_is_described() -> None:
    assert {a.type for a in ACTIONS} == set(typing.get_args(ActionType)) and len(ACTIONS) == 25
    assert set(TRIGGERS) == set(typing.get_args(TriggerType)) and len(TRIGGERS) == 13
    assert set(OPERATORS) == set(typing.get_args(ComparisonOp))
    for a in ACTIONS:
        jsonschema.Draft202012Validator.check_schema(a.params_schema)


def test_operator_unit_compatibility() -> None:
    assert "enum" not in OPERATORS["gt"][1]
    assert OPERATORS["in_set"][1] == ("enum",) and OPERATORS["not_in_set"][1] == ("enum",)
    assert OPERATORS["is_true"][1] == ("bool",)


def test_every_metric_has_unit_and_enum_values() -> None:
    for d in default_registry():
        assert d.unit in UNITS
        assert bool(d.enum_values) == (d.unit == "enum")


def test_etag_stable_and_changes() -> None:
    a, b = _vocab(), _vocab()
    assert etag_for(a, set(), None) == etag_for(b, set(), None)
    assert etag_for(a, {"orders:write"}, None) != etag_for(a, set(), None)
    reg = default_registry()
    reg.register(MetricDescriptor(name="zz", title="Z", unit="count"))
    assert etag_for(build_vocabulary(reg), set(), None) != etag_for(a, set(), None)
    assert vbuild.content_hash(default_registry()) == vbuild.content_hash(default_registry())


def test_response_validates_against_contract() -> None:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    schema = {"components": spec["components"], **spec["components"]["schemas"]["RuleVocabulary"]}
    jsonschema.Draft202012Validator(schema).validate(_vocab())


def test_endpoint_headers_etag_and_304() -> None:
    c = _client(_P("rules:read"))
    r = c.get("/rules/vocabulary")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "private, max-age=60"
    r2 = c.get("/rules/vocabulary", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304
    r3 = _client(_P("rules:read", "orders:write")).get("/rules/vocabulary")
    assert r3.headers["etag"] != r.headers["etag"]


def test_endpoint_symbol_scope() -> None:
    c = _client(_P("rules:read"), recorded=frozenset({"BTCUSDT"}))
    body = c.get("/rules/vocabulary", params={"symbol": "ethusdt"}).json()
    assert any(not s["available"] for s in body["signals"])
    assert c.get("/rules/vocabulary", params={"symbol": "x!"}).status_code == 400


def test_endpoint_rbac_fail_closed() -> None:
    assert _client(None).get("/rules/vocabulary").status_code == 401
    assert _client(_P()).get("/rules/vocabulary").status_code == 403
    app = FastAPI()
    app.include_router(make_rules_router(default_registry))
    assert TestClient(app).get("/rules/vocabulary").status_code == 501


def test_engine_offline_is_503() -> None:
    r = _client(_P("rules:read"), registry=MetricRegistry()).get("/rules/vocabulary")
    assert r.status_code == 503 and r.json()["title"] == "Service unavailable"
    app = FastAPI()
    app.include_router(make_rules_router(lambda: None, principal_resolver=_Resolver(_P("*"))))
    assert TestClient(app).get("/rules/vocabulary").status_code == 503


def test_rule_ir_schema_endpoint() -> None:
    c = _client(_P("rules:read"))
    r = c.get("/schemas/rule-ir.json")
    assert r.status_code == 200 and r.json() == json.loads(json.dumps(to_json_schema()))
    assert _client(_P()).get("/schemas/rule-ir.json").status_code == 403


class _RealSessions:
    async def authenticate_access_token(self, token: str) -> typing.Any:
        import uuid
        from types import SimpleNamespace

        from candleviewer.auth.errors import SessionNotFound

        if token not in ("trader", "viewer"):
            raise SessionNotFound("nope")
        return SimpleNamespace(id=uuid.uuid4(), user_id=token)


class _RealIdentity:
    async def user(self, user_id: str) -> dict[str, typing.Any]:
        return {"username": user_id, "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, typing.Any]:
        perms = ["rules:read", "orders:write"] if user_id == "trader" else ["rules:read"]
        return {"permissions": perms}


def test_simulate_only_through_real_session_resolver() -> None:
    from candleviewer.api.audit_principal import SessionAuditPrincipalResolver

    app = FastAPI()
    resolver = SessionAuditPrincipalResolver(lambda: _RealSessions(), _RealIdentity())
    app.include_router(make_rules_router(default_registry, principal_resolver=resolver))
    c = TestClient(app)

    def actions(tok: str) -> list[dict[str, typing.Any]]:
        r = c.get("/rules/vocabulary", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        return r.json()["actions"]

    assert any(a["simulate_only"] for a in actions("viewer"))
    assert not any(a["simulate_only"] for a in actions("trader"))
    assert c.get("/rules/vocabulary").status_code == 401


def test_rules_service_registry_reflects_engine_state() -> None:
    import asyncio

    from candleviewer.rules.service import RulesService

    svc = RulesService()
    assert svc.registry() is None  # not started -> router answers 503
    asyncio.run(svc.start(typing.cast(typing.Any, None)))
    assert svc.registry() is not None and len(svc.registry() or ()) > 0
    asyncio.run(svc.stop(1.0))
    assert svc.registry() is None


def test_recorder_service_recorded_symbols_default_empty() -> None:
    from candleviewer.recorder.service import RecorderService

    assert RecorderService().recorded_symbols() == frozenset()
