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
from candleviewer.orderflow.indicators.catalogue import SERVER_DEFINITIONS, V1_INDICATORS
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
from candleviewer.rules.vocabulary.catalogue import ACTIONS, OPERATORS, RETIRED_ACTIONS, TRIGGERS
from candleviewer.rules.vocabulary.metrics import kernel_params_schema
from candleviewer.rules.vocabulary.registry import DuplicateMetricError
from tests.rules._check_limiter import unthrottled

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
            lambda: reg,
            principal_resolver=_Resolver(principal),
            recorded_symbols=lambda: recorded,
            check_limiter=unthrottled(),
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
    full = {a["id"]: a for a in _vocab(permissions={"orders:write"})["actions"]}
    assert full["place_order"]["simulate_only"] is False


def test_no_action_offers_to_loosen_a_stop() -> None:
    """No rule loosens a stop (24-internal-schemas.md section 8.8 rule 5): `widen_stop` is not
    offered, and no action is flagged, gated or described as a way to loosen one."""
    acts = _vocab(permissions={"*"})["actions"]
    assert "widen_stop" not in {a["id"] for a in acts}
    assert [a["id"] for a in acts if a["loosens_risk"]] == []
    assert [a["id"] for a in acts if "loosen_stop" in json.dumps(a)] == []


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


#: E13-T02: the rule metrics an M9 server kernel computes, and the indicator output each reads.
KERNEL_BOUND = {
    "delta": ("delta", "delta"), "cvd": ("cvd", "cvd"), "bar_volume": ("volume", "volume"),
    "atr": ("atr", "atr"), "ema": ("ema", "ema"), "sma": ("sma", "sma"), "rsi": ("rsi", "rsi"),
    "swing_high": ("zigzag", "swing_high"), "swing_low": ("zigzag", "swing_low"),
    "adx": ("adx", "adx"), "vwap": ("vwap", "vwap"), "vwap_band_sigma": ("vwap", "band_sigma"),
}  # fmt: skip
#: The kernel-bound metrics read from the order flow or the traded volume of tape-built bars:
#: they keep the `trades` input, so they need the symbol on the recorded-symbol list, as `delta`,
#: `cvd`, `vwap` and `vwap_band_sigma` did before E13-T02 (and as the Deep Stats `bar_volume` row
#: of 24 §7.2 does).
TAPE_BOUND = {"delta", "cvd", "bar_volume", "vwap", "vwap_band_sigma"}


def test_kernel_bound_metrics_take_their_facts_from_the_indicator_catalogue() -> None:
    """E13-T02: unit, params, warmup, inputs, cadence, nullable_when and confidence come from
    the indicator catalogue, and the signal's params_schema is the indicator's own."""
    signals = {s["id"]: s for s in _vocab()["signals"]}
    for metric, (indicator, output) in KERNEL_BOUND.items():
        d, definition = default_registry().get(metric), SERVER_DEFINITIONS[indicator]
        assert d is not None
        assert d.params == {k: str(v) for k, v in definition.json_defaults().items()}, metric
        assert d.unit == definition.output_unit(output), metric
        inputs = ("bars", "trades") if metric in TAPE_BOUND else ("bars",)
        facts = (d.warmup_bars, d.inputs, d.cadence, d.nullable_when, d.confidence)
        want = (definition.warmup_bars(), inputs, "on_bar_close", definition.nullable_when)
        assert facts == (*want, "exact"), metric
        assert signals[metric]["params_schema"] == definition.params_schema(), metric
        assert signals[metric]["requires_recording"] is (metric in TAPE_BOUND), metric


def test_tape_bound_metrics_are_unavailable_for_a_symbol_that_is_not_recorded() -> None:
    """The order-flow and volume metrics keep their recorded-trades dependency: for a symbol
    off the recorded-symbol list they are unavailable with the recorder action, as before
    E13-T02, while the price-only kernel metrics stay available."""
    by = {s["id"]: s for s in _vocab(symbol="DOGEUSDT", recorded_symbols={"BTCUSDT"})["signals"]}
    for metric in sorted(TAPE_BOUND):
        s = by[metric]
        assert (s["available"], s["requires_recording"]) == (False, True), metric
        assert s["missing_dependency"] == {
            "kind": "recording",
            "symbol": "DOGEUSDT",
            "inputs": ["trades"],
        }, metric
        assert s["recorder_action"]["path"] == "/api/v1/recording/symbols", metric
    for metric in sorted(set(KERNEL_BOUND) - TAPE_BOUND):
        assert by[metric]["available"] is True, metric
    recorded = _vocab(symbol="BTCUSDT", recorded_symbols={"BTCUSDT"})["signals"]
    assert all(s["available"] for s in recorded if s["id"] in TAPE_BOUND)


def test_kernel_bound_metrics_are_exactly_the_bound_set() -> None:
    bound = {n for n in default_registry().names() if kernel_params_schema(n) is not None}
    assert bound == set(KERNEL_BOUND)
    assert kernel_params_schema("tape_speed") is None


def test_kernel_bound_metric_units_are_unchanged_and_are_their_outputs_units() -> None:
    units = {m: getattr(default_registry().get(m), "unit", None) for m in KERNEL_BOUND}
    assert units == {
        "delta": "qty", "cvd": "qty", "bar_volume": "qty", "atr": "price", "ema": "price",
        "sma": "price", "rsi": "pct", "swing_high": "price", "swing_low": "price",
        "adx": "ratio", "vwap": "price", "vwap_band_sigma": "zscore",
    }  # fmt: skip
    from_catalogue = {m: SERVER_DEFINITIONS[i].output_unit(o) for m, (i, o) in KERNEL_BOUND.items()}
    assert units == from_catalogue


def test_swing_metrics_keep_the_24_7_2_swing_and_ema_sma_gain_defaults() -> None:
    """E13-T02 renames the swing depth from `n` to ZigZag's `depth` and adds `deviation_pct`
    (default 0, the plain pivot), a vocabulary change no stored rule used (24 §7.2)."""
    reg = default_registry()
    swing_high, swing_low = reg.get("swing_high"), reg.get("swing_low")
    assert swing_high is not None and swing_low is not None
    assert swing_high.params == swing_low.params == {"depth": "5", "deviation_pct": "0"}
    assert swing_high.warmup_bars == swing_low.warmup_bars == 11
    defaults = {m: getattr(reg.get(m), "params", None) for m in ("sma", "ema", "rsi")}
    assert defaults == {
        "sma": {"n": "20", "source": "close", "offset": "0"},
        "ema": {"n": "21", "source": "close", "offset": "0"},
        "rsi": {"n": "14"},
    }
    assert getattr(reg.get("rsi"), "warmup_bars", None) == 15  # n + 1 closes


def test_a_binding_to_an_output_its_indicator_lacks_is_refused_at_import() -> None:
    from candleviewer.rules.vocabulary import metrics

    with pytest.raises(ValueError, match="atr has no output upper_1"):
        metrics._bound(("atr_band", "atr", "upper_1", "ATR band", False, "", ""))


def test_rule_eligibility_is_server_placement_and_no_client_worker_name_is_a_metric() -> None:
    """ADR-0034 rule 2 and #426's ruling D3: every server indicator backs a rule metric, and none of
    the 20 client_worker indicators enters the rule vocabulary."""
    assert {i for i, _ in KERNEL_BOUND.values()} == set(SERVER_DEFINITIONS)
    client_worker = {d.id for d in V1_INDICATORS if d.compute == "client_worker"}
    assert len(client_worker) == 20
    assert client_worker & set(default_registry().names()) == set()


def test_every_enum_member_is_described() -> None:
    # `widen_stop` is retired: the IR still parses it (stored rules keep their hashes), and the
    # vocabulary never offers it.
    assert set(typing.get_args(ActionType)) - {a.type for a in ACTIONS} == RETIRED_ACTIONS
    assert {a.type for a in ACTIONS} < set(typing.get_args(ActionType)) and len(ACTIONS) == 24
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
    app.include_router(make_rules_router(default_registry, check_limiter=unthrottled()))
    assert TestClient(app).get("/rules/vocabulary").status_code == 501


def test_engine_offline_is_503() -> None:
    r = _client(_P("rules:read"), registry=MetricRegistry()).get("/rules/vocabulary")
    assert r.status_code == 503 and r.json()["title"] == "Service unavailable"
    app = FastAPI()
    app.include_router(
        make_rules_router(
            lambda: None, principal_resolver=_Resolver(_P("*")), check_limiter=unthrottled()
        )
    )
    assert TestClient(app).get("/rules/vocabulary").status_code == 503


def test_rule_ir_schema_endpoint() -> None:
    c = _client(_P("rules:read"))
    r = c.get("/schemas/rule-ir.json")
    assert r.status_code == 200 and r.json() == json.loads(json.dumps(to_json_schema()))
    assert _client(_P()).get("/schemas/rule-ir.json").status_code == 403


class _RealSessions:
    async def authenticate_access_token(self, token: str, *, touch: bool = False) -> typing.Any:
        import uuid
        from types import SimpleNamespace

        from candleviewer.auth.errors import SessionNotFound

        if token not in ("trader", "viewer"):
            raise SessionNotFound("nope")
        return SimpleNamespace(view_as=None, id=uuid.uuid4(), user_id=token)


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
    app.include_router(
        make_rules_router(
            default_registry, principal_resolver=resolver, check_limiter=unthrottled()
        )
    )
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


# E13-S02 BQ-02 rider (b) / BQ-03 rider (c): `source` and `offset` join sma / ema in the rule
# vocabulary because it derives them from the catalogue, and a stored rule that names sma or ema
# without them must keep its canonical IR and ir_hash.
_STORED_SMA_EMA_HASHES = {
    "sma_default": "1da04b6e44ca03bbd536a9d6f88e805d75017aa9aa8832e19a687038d5a99fb2",
    "sma_n": "8ed6dd7d579cd468e6c0fdb69b3f34ed7ad464adaad674a3812074df4a43ee49",
    "ema_default": "6bbe9941a6056cedae8443414272bde0ae7f0bfe933a398d5d9dcad949b50e44",
    "ema_n": "4e7f207a4afa794bcdea7d42a0180737bcfd0f7e635202c4b61f56ba898df577",
    "ema_n50": "64fa55a7426688a13ef6e8ddc06c63ccdb1db5533b3f6e13f5499c9da768c37a",
}
_STORED_LEFT: dict[str, dict[str, typing.Any]] = {
    "sma_default": {"metric": "sma"},
    "sma_n": {"metric": "sma", "params": {"n": 20}},
    "ema_default": {"metric": "ema"},
    "ema_n": {"metric": "ema", "params": {"n": 21}},
    "ema_n50": {"metric": "ema", "params": {"n": 50}},
}


def _stored_rule(case: str) -> typing.Any:
    from candleviewer.rules.ir import Rule

    fixture = Path(__file__).parents[1] / "fixtures/rule_ir/form_simple_0.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"), parse_float=str)
    raw["conditions"]["left"] = _STORED_LEFT[case]
    return Rule.model_validate(raw)


@pytest.mark.parametrize("case", sorted(_STORED_SMA_EMA_HASHES))
def test_a_stored_sma_or_ema_rule_keeps_its_ir_hash_and_compiles_to_the_same_ir(case: str) -> None:
    """The hashes are literals computed on the contract-slice base (95795a705), before the
    catalogue gained `source` and `offset`; both editors still compile to that exact IR."""
    from candleviewer.rules.compiler import (
        compile_form,
        compile_graph,
        to_form_model,
        to_graph_model,
    )
    from candleviewer.rules.ir import ir_hash
    from candleviewer.rules.validator import validate_rule

    rule = _stored_rule(case)
    expected = _STORED_SMA_EMA_HASHES[case]
    assert ir_hash(rule) == expected
    assert ir_hash(compile_graph(to_graph_model(rule), rule.rule_id)) == expected
    assert ir_hash(compile_form(to_form_model(rule), rule.rule_id)) == expected
    errors = validate_rule(rule, default_registry()).errors  # the fixture's action is incomplete
    assert [e for e in errors if e.path.startswith("conditions")] == []


def test_source_and_offset_are_rule_vocabulary_params_of_sma_and_ema_only() -> None:
    reg = default_registry()
    for name in ("sma", "ema"):
        params = getattr(reg.get(name), "params", None)
        assert isinstance(params, dict)
        assert {"source", "offset"} <= set(params)
        assert (params["source"], params["offset"]) == ("close", "0")
    assert set(getattr(reg.get("rsi"), "params", {})) == {"n"}


@pytest.mark.parametrize("case", sorted(_STORED_SMA_EMA_HASHES))
def test_the_validator_accepts_a_stored_bare_sma_or_ema_metric(case: str) -> None:
    """BQ-02 rider (b): a stored rule that names sma / ema without `source` / `offset` (only the
    old `n`, or nothing) validates clean in its conditions; the new params are optional."""
    from candleviewer.rules.validator import validate_rule

    result = validate_rule(_stored_rule(case), default_registry())
    assert [e for e in result.errors if e.path.startswith("conditions")] == []
    assert not any(e.code == "unknown_metric" for e in result.errors)


def test_the_registry_requires_neither_source_nor_offset_of_sma_or_ema() -> None:
    from candleviewer.rules.vocabulary.metrics import kernel_params_schema

    for name in ("sma", "ema"):
        schema = kernel_params_schema(name)
        assert schema is not None
        assert {"source", "offset"} <= set(typing.cast(dict[str, typing.Any], schema["properties"]))
        required = set(typing.cast(list[str], schema.get("required", [])))
        assert required.isdisjoint({"source", "offset"})
        assert required == set()


def test_the_catalogue_accepts_a_bare_sma_or_ema_param_object() -> None:
    from candleviewer.orderflow.indicators.catalogue import SERVER_DEFINITIONS, validate_params

    for name in ("sma", "ema"):
        assert validate_params(SERVER_DEFINITIONS[name], {"n": 20})["offset"] == 0
        assert validate_params(SERVER_DEFINITIONS[name], {})["source"] == "close"
