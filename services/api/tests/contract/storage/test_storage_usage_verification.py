"""E07-D02 (#223): the shipped `StorageUsage` payload against the E07-D01 operator content model.

Target path: services/api/tests/contract/storage/test_storage_usage_verification.py  # (RULED BQ-02)

The payload under test is the one E16-T08's route serves (`GET /recording/storage`), built by the
real `DiskBudget.sample_once()` on a `FakeMeter` and read through the real `create_app()` as the
Owner (the RBAC pack's world). It is never the `22` example and never `build_storage_usage`
(D01 section 5, handoff section C item 2).  # (RULED BQ-06)

Ids are D01's, cited as written: CK (field), ST (state), EM (empty and error state), DL (decision),
F (finding), D01-Gn / D04-Gn (gap), X (accepted exception), U (unit rule). A gap that the payload
cannot express today is pinned by a closed-world test whose name carries the gap id. When an owner
closes the gap the pin goes red and forces an update of this file and the report.  # (RULED BQ-07)
There is no skip, no xfail and no flag in this file (AGENTS.md section 8 rule 4).

The baseline fixture is rewritten only on purpose, by one command run from `services/api`:
`python -m tests.contract.storage.test_storage_usage_verification --write-baseline`.
(RULED BQ-06)
The fixture lives in the shared TS + Python golden directory `packages/fixtures/golden/storage/`
(gated by `packages/fixtures/scripts/verify.mjs`); it holds figures from a fake meter, not a
measurement.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from prometheus_client import REGISTRY

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.recorder.budget import (
    US_PER_DAY,
    BudgetConfig,
    DiskBudget,
    project_full_at,
)
from candleviewer.storage.cold import exporter as _cold_exporter  # registers the export metrics
from candleviewer.storage.retention import reaper as _reaper  # registers the retention metrics
from candleviewer.storage.retention.usage import build_storage_usage
from tests.contract._admin_support import validate_example
from tests.contract.rbac.rbac_harness import MATRIX_PATH, World, bearer, build_world
from tests.unit.api.test_recording_reports import _Budget, _Env, _recorder, _usage
from tests.unit.recorder._budget_fakes import CAP, GB, NOW, TOTAL, FakeEvents, FakeMeter
from tests.unit.recorder._fakes import FakeBus
from tests.unit.recorder._session_fakes import UsClock

ROOT = Path(__file__).resolve().parents[5]
BASELINE = ROOT / "packages/fixtures/golden/storage/storage_usage_baseline.golden.json"
REPORT = ROOT / "docs" / "qa" / "e07-d02-storageusage-verification.md"
D01_TOOL = ROOT / "docs" / "design" / "_tools" / "e07_d01_storage_model_audit.py"
_SPEC: Any = load_openapi_spec()
_SCHEMA: dict[str, Any] = _SPEC["components"]["schemas"]["StorageUsage"]["properties"]
_STORAGE = "/recording/storage"
_OK = "/paths/~1recording~1storage/get/responses/200/content/application~1json/schema"
_ROLES = ["owner", "manager_with_grant", "manager_without_grant", "viewer"]
_FIELDS = tuple(_SCHEMA)  # the 13 names, in schema order (CK-01..CK-13)


# --- worlds and helpers -------------------------------------------------------------------------


class _Mono:
    """The sampler's monotonic clock: the stale gate ages on it (budget.py `sample_stale`)."""

    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


@dataclass
class _CountingMeter(FakeMeter):
    volume_calls: int = 0
    breakdown_calls: int = 0

    async def volume(self) -> tuple[int, int]:
        self.volume_calls += 1
        return await super().volume()

    async def breakdown(self) -> Any:
        self.breakdown_calls += 1
        return await super().breakdown()


def _meter(**kw: Any) -> FakeMeter:
    """The baseline meter: 300 GB recorded, half the volume free, two symbols."""
    kw.setdefault("used", 300 * GB)
    kw.setdefault("symbols", {"BTCUSDT": 200 * GB, "ETHUSDT": 100 * GB})
    return FakeMeter(**kw)


def _budget(
    meter: FakeMeter,
    *,
    mono: _Mono | None = None,
    refused: bool = False,
    pinned: frozenset[str] = frozenset({"BTCUSDT"}),
) -> DiskBudget:
    async def pins() -> frozenset[str]:
        return pinned

    return DiskBudget(
        meter=meter,
        events=FakeEvents(),
        bus=FakeBus(),
        env="demo",
        config=BudgetConfig(cap_bytes=CAP),
        now_us=UsClock(NOW),
        pinned=pins,
        monotonic=mono or _Mono(),
        recording_refused=refused,
    )


def _sampled(meter: FakeMeter, **kw: Any) -> DiskBudget:
    budget = _budget(meter, **kw)
    asyncio.run(budget.sample_once())
    return budget


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        w = build_world(mp)
        mp.setattr(w.app.state, "recording_control", _recorder(), raising=False)
        mp.setattr(w.app.state, "disk_budget", None, raising=False)
        yield w
    finally:
        mp.undo()


@contextmanager
def _serving(w: World, budget: DiskBudget | None) -> Iterator[None]:
    held = w.app.state.disk_budget
    w.app.state.disk_budget = budget
    try:
        yield
    finally:
        w.app.state.disk_budget = held


def _get(w: World, budget: DiskBudget | None, actor: str = "owner") -> Any:
    with _serving(w, budget):
        return w.client.get(_STORAGE, headers=bearer(actor))


def _body(w: World, budget: DiskBudget, actor: str = "owner") -> dict[str, Any]:
    resp = _get(w, budget, actor)
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    return body


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


@pytest.fixture(scope="module")
def baseline(world: World) -> dict[str, Any]:
    return _body(world, _sampled(_meter()))


# --- the frozen baseline (RULED BQ-06) ------------------------------------------------------------


# (RULED BQ-06)
def test_baseline_equals_the_frozen_fixture_bytes(baseline: dict[str, Any]) -> None:
    assert BASELINE.read_text(encoding="utf-8") == json.dumps(baseline, indent=2) + "\n"


def test_baseline_validates_against_the_openapi_schema(baseline: dict[str, Any]) -> None:
    validate_example(_OK, baseline)
    api.StorageUsage.model_validate(baseline)


def test_baseline_field_set_is_exactly_the_schema_fields(baseline: dict[str, Any]) -> None:
    assert tuple(baseline) == _FIELDS and len(_FIELDS) == 13


# --- CK rows (RULED BQ-05) ------------------------------------------------------------------------

_CK = [  # (id, field, python type of the value, unit by name per D01 section 4.1)  # (RULED BQ-05)
    ("CK-01", "disk_total_bytes", int, "bytes"),
    ("CK-02", "disk_used_bytes", int, "bytes"),
    ("CK-03", "disk_free_bytes", int, "bytes"),
    ("CK-04", "projected_full_at", type(None), "date-time UTC"),
    ("CK-05", "daily_growth_bytes", int, "bytes per day"),
    ("CK-06", "tiers", list, "tier rows"),
    ("CK-07", "symbols", list, "symbol rows"),
    ("CK-08", "generated_at", str, "date-time UTC"),
    ("CK-09", "cap_bytes", int, "bytes"),
    ("CK-10", "level", int, "enum 0..3"),
    ("CK-11", "write_gate", str, "enum"),
    ("CK-12", "write_gate_reason", type(None), "enum or null"),
    ("CK-13", "accelerate_retention", bool, "bool"),
]


@pytest.mark.parametrize(("ck", "field", "kind", "unit"), _CK, ids=[c[0] for c in _CK])
def test_baseline_field_has_its_schema_type(
    baseline: dict[str, Any], ck: str, field: str, kind: type, unit: str
) -> None:
    value = baseline[field]
    assert isinstance(value, kind), (ck, unit)
    if kind is int:
        assert not isinstance(value, bool)


def test_nullable_fields_are_exactly_the_schema_nullable_fields() -> None:
    top = {f for f, s in _SCHEMA.items() if "null" in s.get("type", [])}
    row = _SCHEMA["tiers"]["items"]["properties"]["retention_days"]
    assert top == {"projected_full_at", "write_gate_reason"}
    assert row["type"] == ["integer", "null"]


def test_baseline_timestamps_are_utc_date_times(baseline: dict[str, Any]) -> None:
    stamp = datetime.fromisoformat(baseline["generated_at"].replace("Z", "+00:00"))
    offset = stamp.utcoffset()
    assert offset is not None and offset.total_seconds() == 0  # (RULED BQ-05)


def test_baseline_disk_used_is_total_minus_free_x1(baseline: dict[str, Any]) -> None:
    assert baseline["disk_used_bytes"] == baseline["disk_total_bytes"] - baseline["disk_free_bytes"]


def test_baseline_cap_bytes_is_at_least_one(baseline: dict[str, Any]) -> None:
    assert baseline["cap_bytes"] >= 1 and _SCHEMA["cap_bytes"]["minimum"] == 1


def test_baseline_tier_rows_follow_the_tier_order(baseline: dict[str, Any]) -> None:
    assert [t["tier"] for t in baseline["tiers"]] == ["questdb", "parquet", "postgres"]
    assert _SCHEMA["tiers"]["items"]["properties"]["tier"]["enum"] == [
        "questdb",
        "parquet",
        "postgres",
    ]


def test_baseline_retention_days_are_7_30_and_null(baseline: dict[str, Any]) -> None:
    assert [t["retention_days"] for t in baseline["tiers"]] == [7, 30, None]


def test_baseline_symbols_are_sorted_largest_first(baseline: dict[str, Any]) -> None:
    sizes = [s["used_bytes"] for s in baseline["symbols"]]
    assert sizes == sorted(sizes, reverse=True) and len(sizes) == 2


_SYMBOL_KEYS = ["symbol", "used_bytes", "daily_growth_bytes", "pinned"]


def test_baseline_symbol_rows_carry_the_pinned_flag_ck_07_pinned(baseline: dict[str, Any]) -> None:
    items = _SCHEMA["symbols"]["items"]["properties"]
    assert list(items) == _SYMBOL_KEYS and items["pinned"]["type"] == "boolean"
    for row in baseline["symbols"]:
        assert list(row) == _SYMBOL_KEYS and isinstance(row["pinned"], bool)
    assert {r["symbol"]: r["pinned"] for r in baseline["symbols"]} == {
        "BTCUSDT": True,
        "ETHUSDT": False,
    }


def test_pinned_flag_follows_the_pin_source_ck_07_pinned(world: World) -> None:
    none = _body(world, _sampled(_meter(), pinned=frozenset()))
    both = _body(world, _sampled(_meter(), pinned=frozenset({"BTCUSDT", "ETHUSDT"})))
    assert [r["pinned"] for r in none["symbols"]] == [False, False]
    assert [r["pinned"] for r in both["symbols"]] == [True, True]


def test_level_three_payload_has_no_pinned_exemption_field_d01_c_c_not_expressible(
    world: World,
) -> None:  # AC4, D01 section 18 item 7: level 3 says nothing about pinned symbols
    body = _body(world, _sampled(_meter(free=TOTAL * 4 // 100)))
    assert body["level"] == 3 and body["write_gate"] == "closed"
    assert [r["pinned"] for r in body["symbols"]] == [True, False]  # the flag only, no exemption
    keys = {k for k in {*body, *(k for r in body["symbols"] for k in r)} if "exempt" in k}
    assert keys == set() and not [f for f in _SCHEMA if "pin" in f or "exempt" in f]


def test_symbols_are_capped_at_64_largest_first_x2(world: World) -> None:
    many = {f"S{i:02d}USDT": (i + 1) * GB for i in range(70)}
    body = _body(world, _sampled(_meter(symbols=many)))
    sizes = [s["used_bytes"] for s in body["symbols"]]
    assert len(sizes) == 64 and sizes == sorted(sizes, reverse=True) and sizes[0] == 70 * GB


@pytest.mark.parametrize(
    ("field", "allowed"),
    [("level", {0, 1, 2, 3}), ("write_gate", {"open", "closed"}),
     ("write_gate_reason", {"disk_halt", "volume_refused", None})],
)  # fmt: skip
def test_baseline_enum_values_are_in_the_schema_set(
    baseline: dict[str, Any], field: str, allowed: set[Any]
) -> None:
    assert baseline[field] in allowed
    assert set(_SCHEMA[field]["enum"]) == allowed


# --- DL rows: every decision maps to fields or to a recorded gap (T AC1) -------------------------

_GAPS = {"D01-G1", "D01-G2", "D01-G3", "D01-G4", "D01-G5", "D01-G6", "D01-G7",
         "D04-G1", "D04-G7", "D04-G8"}  # fmt: skip
_DL: dict[str, tuple[set[str], set[str]]] = {  # id -> (fields, gaps)  # (RULED BQ-05)
    "DL-01": ({"level", "disk_free_bytes", "disk_total_bytes", "cap_bytes", "daily_growth_bytes",
               "tiers", "projected_full_at"}, set()),
    "DL-02": ({"level", "write_gate", "write_gate_reason", "accelerate_retention"}, set()),
    "DL-03": (set(), {"D04-G7"}),
    "DL-04": (set(), {"D04-G1"}),
    "DL-05": ({"symbols"}, set()),
    "DL-06": ({"symbols"}, set()),
    "DL-07": ({"generated_at"}, set()),
    "DL-08": (set(), {"D01-G1"}),
    "DL-09": ({"daily_growth_bytes"}, {"D04-G1"}),
    "DL-10": ({"tiers"}, set()),
}  # fmt: skip


@pytest.mark.parametrize("dl", sorted(_DL))
def test_decision_row_names_real_fields_or_a_recorded_gap(dl: str) -> None:
    fields, gaps = _DL[dl]
    assert fields <= set(_FIELDS) and gaps <= _GAPS and (fields or gaps)


# --- ST rows: the states the sampler can reach (RULED BQ-07) --------------------------------------

_STATES = [  # (id, meter kwargs, refused, (level, gate, reason, accelerate))
    ("ST-01", {}, False, (0, "open", None, False)),
    ("ST-02", {"used": 500 * GB}, False, (1, "open", None, False)),
    ("ST-03", {"free": TOTAL // 10}, False, (2, "open", None, True)),
    ("ST-04", {"free": TOTAL * 4 // 100}, False, (3, "closed", "disk_halt", True)),
    ("ST-05", {}, True, (3, "closed", "volume_refused", False)),
]  # fmt: skip


def _state_budgets() -> Iterator[tuple[str, DiskBudget]]:
    for st, kw, refused, _ in _STATES:
        yield st, _sampled(_meter(**kw), refused=refused)


@pytest.mark.parametrize(("st", "kw", "refused", "want"), _STATES, ids=[s[0] for s in _STATES])
def test_state_payload_names_level_gate_reason_and_flag(
    world: World, st: str, kw: dict[str, Any], refused: bool, want: tuple[Any, ...]
) -> None:
    body = _body(world, _sampled(_meter(**kw), refused=refused))
    got = (
        body["level"],
        body["write_gate"],
        body["write_gate_reason"],
        body["accelerate_retention"],
    )
    assert got == want, st
    validate_example(_OK, body)


def test_stale_sample_reads_level_three_with_the_old_generated_at_st06(
    world: World, baseline: dict[str, Any]
) -> None:
    mono = _Mono()
    budget = _sampled(_meter(), mono=mono)
    mono.t += 3 * 60 + 1  # past 3 x 60 s with no new pass (budget.py STALE_AFTER_INTERVALS)
    body = _body(world, budget)
    assert (body["level"], body["write_gate"]) == (3, "closed")
    assert body["generated_at"] == baseline["generated_at"]


def test_no_sample_yet_is_a_503_problem_without_figures_st12_em01(world: World) -> None:
    resp = _get(world, _budget(_meter()))  # built, never sampled
    body = resp.json()
    assert (resp.status_code, resp.headers["content-type"]) == (503, "application/problem+json")
    assert body["code"] == "store_unavailable"
    assert not set(body) & set(_FIELDS) and not re.search(r"\d", body["detail"])


def test_no_budget_is_the_same_503_problem_em02(world: World) -> None:
    resp = _get(world, None)
    assert (resp.status_code, resp.json()["code"]) == (503, "store_unavailable")


def test_no_recorded_symbols_gives_an_empty_symbols_list_em07(world: World) -> None:
    assert _body(world, _sampled(_meter(symbols={})))["symbols"] == []


# --- unreachable versus empty (RULED BQ-08) -------------------------------------------------------


def test_failed_first_breakdown_gives_empty_tiers_with_valid_free_space_fields_d02_f1(
    world: World,
) -> None:  # (RULED BQ-08)
    body = _body(world, _sampled(_meter(breakdown_fail=True)))
    assert body["tiers"] == [] and body["symbols"] == []
    assert body["disk_free_bytes"] == TOTAL // 2 and body["level"] == 0
    validate_example(_OK, body)


def test_failed_later_breakdown_keeps_the_last_tier_sizes(world: World) -> None:
    meter = _meter()
    budget = _sampled(meter)
    first = _body(world, budget)["tiers"]
    meter.breakdown_fail = True
    asyncio.run(budget.sample_once())
    assert _body(world, budget)["tiers"] == first


def test_failed_volume_read_gives_no_report(world: World) -> None:
    budget = _budget(_meter(fail=True))
    with pytest.raises(OSError):
        asyncio.run(budget.sample_once())
    assert _get(world, budget).status_code == 503


# --- the projection (RULED BQ-09) -----------------------------------------------------------------


def test_first_sample_has_no_projection_and_zero_growth_em08_f04(baseline: dict[str, Any]) -> None:
    assert (baseline["projected_full_at"], baseline["daily_growth_bytes"]) == (None, 0)


def _full_at(*, used: int, cap: int, free: int, growth: int | None) -> int | None:
    return project_full_at(used=used, cap=cap, free=free, daily_growth=growth, now_us=NOW)[0]


def test_projection_is_null_when_growth_is_unknown_or_not_positive_u05() -> None:
    assert [_full_at(used=1, cap=CAP, free=TOTAL, growth=g) for g in (None, 0, -5)] == [None] * 3


def test_projection_is_null_beyond_one_hundred_years_u05() -> None:
    assert _full_at(used=0, cap=36_501, free=TOTAL, growth=1) is None


def test_projection_is_a_date_at_exactly_one_hundred_years() -> None:
    assert _full_at(used=0, cap=36_500, free=TOTAL, growth=1) == NOW + 36_500 * US_PER_DAY


def test_projection_names_the_nearer_wall_u03() -> None:
    cap_near = _full_at(used=0, cap=10, free=1_000, growth=1)
    free_near = _full_at(used=0, cap=1_000, free=10, growth=1)
    assert cap_near == free_near == NOW + 10 * US_PER_DAY


def test_route_marks_no_estimate_field_the_word_is_the_clients_u08(
    baseline: dict[str, Any],
) -> None:
    assert not [k for k in baseline if "estimate" in k]  # met by D01 Q-01 and U-08, a client rule


# --- gap pins: closed-world, named with the gap id (RULED BQ-07) ----------------------------------


def test_payload_has_no_tier_alerts_d01_g1_not_expressible(baseline: dict[str, Any]) -> None:
    assert "tier_alerts" not in baseline and "tier_alerts" not in _SCHEMA  # ST-07, ST-08, DL-08


def test_write_gate_reason_stays_in_the_closed_set_d01_g1_not_expressible(world: World) -> None:
    seen = {_body(world, b)["write_gate_reason"] for _, b in _state_budgets()}
    assert seen == {None, "disk_halt", "volume_refused"}


def test_openapi_names_no_storage_tier_code_d01_g2_not_expressible() -> None:
    text = json.dumps(_SPEC)
    codes = ("STORAGE_TIER_UNAVAILABLE", "STORAGE_EXPORT_VERIFY_FAILED", "STORAGE_SCHEMA_DRIFT")
    assert [c for c in codes if c in text] == []  # F-03


def test_daily_growth_is_never_null_d01_g3_not_expressible(baseline: dict[str, Any]) -> None:
    assert (
        _SCHEMA["daily_growth_bytes"]["type"] == "integer" and baseline["daily_growth_bytes"] == 0
    )


def test_no_tier_migration_route_d01_g4_not_expressible() -> None:
    assert [p for p in _SPEC["paths"] if re.search(r"tier.?migrat", p)] == []


def test_symbols_schema_has_no_cap_d01_g5_not_expressible() -> None:
    assert "maxItems" not in _SCHEMA["symbols"]


def test_pg_migration_pending_is_not_registered_d01_g6_not_expressible() -> None:  # (RULED BQ-13)
    assert "pg_migration_pending" not in _metric_names()


def test_payload_has_no_projection_wall_d01_g7_not_expressible(baseline: dict[str, Any]) -> None:
    assert "projection_wall" not in baseline and "projection_wall" not in _SCHEMA


def test_tier_rows_carry_no_growth_d04_g1_not_expressible(baseline: dict[str, Any]) -> None:
    assert all(set(t) == {"tier", "used_bytes", "retention_days"} for t in baseline["tiers"])


def test_payload_has_no_migration_field_d04_g7_not_expressible(baseline: dict[str, Any]) -> None:
    assert not [k for k in baseline if re.search(r"migrat|schema_version", k)]  # ST-10, DL-03


def test_no_vacuum_route_d04_g8_not_expressible() -> None:
    assert [p for p in _SPEC["paths"] if "vacuum" in p] == []


def test_build_storage_usage_is_the_eight_field_shape_f05() -> None:
    out = build_storage_usage(
        total=10,
        used=4,
        daily_growth=1,
        tiers=[],
        symbols=[],
        now=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
    )
    assert set(out) == set(_FIELDS) - {
        "cap_bytes",
        "level",
        "write_gate",
        "write_gate_reason",
        "accelerate_retention",
    }


# --- the no-path scan (RULED BQ-11) ---------------------------------------------------------------


def _d01_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("e07_d01_storage_model_audit", D01_TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_nopath_patterns_load_from_the_d01_tool() -> None:  # (RULED BQ-11)
    tool = _d01_tool()
    assert callable(tool.nopath_hits) and len(tool.NOPATH_PATTERNS) == 8


def _scan(value: Any) -> list[tuple[str, list[str]]]:
    hits = _d01_tool().nopath_hits
    return [(s, found) for s in _strings(value) if (found := hits(s))]


def test_baseline_strings_have_no_path_or_credential_shape(baseline: dict[str, Any]) -> None:
    assert _scan(baseline) == []  # the token-shaped rule must pass an ISO date-time (UNVERIFIED)


def test_every_state_payload_has_no_path_or_credential_shape(world: World) -> None:
    for st, budget in _state_budgets():
        assert _scan(_body(world, budget)) == [], st


def test_503_problem_has_no_path_or_credential_shape(world: World) -> None:
    assert _scan(_get(world, _budget(_meter())).json()) == []


# --- RBAC (RULED BQ-12): recording:read for all four roles; a reduced symbols[] for non-Owners ----


@pytest.mark.parametrize("actor", _ROLES)
# (RULED BQ-12)
def test_every_role_reads_storage_with_recording_read(world: World, actor: str) -> None:
    resp = _get(world, _sampled(_meter()), actor)
    assert resp.status_code == 200
    validate_example(_OK, resp.json())


def test_owner_sees_every_recorded_symbol(world: World) -> None:
    syms = {"BTCUSDT": 3 * GB, "ETHUSDT": 2 * GB, "XRPUSDT": GB}
    body = _body(world, _sampled(_meter(symbols=syms)))
    assert {s["symbol"] for s in body["symbols"]} == set(syms)


@pytest.mark.parametrize("actor", _ROLES[1:])
def test_non_owner_sees_no_symbol_held_only_by_a_hidden_cause(world: World, actor: str) -> None:
    syms = {"BTCUSDT": 3 * GB, "ETHUSDT": 2 * GB, "XRPUSDT": GB}  # XRPUSDT: position_open only
    body = _body(world, _sampled(_meter(symbols=syms)), actor)
    assert {s["symbol"] for s in body["symbols"]} == {"BTCUSDT", "ETHUSDT"}


def test_unauthenticated_storage_read_is_a_401_problem(world: World) -> None:
    resp = _get(world, _sampled(_meter()), "unauthenticated")
    assert (resp.status_code, resp.headers["content-type"]) == (401, "application/problem+json")


async def test_storage_without_recording_read_is_403_and_audited() -> None:
    env = _Env("recording:write", budget=_Budget(_usage()))
    status, _ = await env.get(_STORAGE)
    assert status == 403 and env.audit  # RPT: "403, audited"


def test_compaction_is_owner_only_in_the_route_matrix() -> (
    None
):  # the only audited action with a route
    with MATRIX_PATH.open(encoding="utf-8") as fh:
        row = yaml.safe_load(fh)["operations"]["POST /admin/recorder/compact"]
    assert row["permissions"] == ["recording:write"]
    assert row["outcomes"] == {"owner": "allow", "manager_with_grant": "403",
                               "manager_without_grant": "403", "viewer": "403",
                               "unauthenticated": "401"}  # fmt: skip


# --- metric and event names (RULED BQ-13) ---------------------------------------------------------

_METRICS = [  # D01 section 11: "exists" and "exists, not listed"
    "storage_export_rows", "storage_export_duration_seconds", "storage_export_verify_failures",
    "storage_retention_dropped_bytes", "storage_disk_free_ratio", "questdb_write_seconds",
    "recorder_disk_budget_breakdown_age_seconds", "disk_budget_sample_failed",
]  # fmt: skip


# (RULED BQ-13) accessor: the default registry plus the metric catalogue
def _metric_names() -> set[str]:
    """Names the process can emit: registered by their owner module (counters drop `_total`) or
    declared in `observability/metrics_catalogue.py` (`questdb_write_seconds` is only there)."""
    assert _cold_exporter is not None and _reaper is not None
    registered = {m.name.removesuffix("_total") for m in REGISTRY.collect()}
    return registered | {spec.name.removesuffix("_total") for spec in CATALOGUE}


@pytest.mark.parametrize("name", _METRICS)
def test_listed_metric_name_is_registered(world: World, name: str) -> None:  # (RULED BQ-13)
    assert name in _metric_names()


@pytest.mark.parametrize("name", ["recorder.import", "retention.purge"])
def test_audit_name_is_in_the_openapi_document(name: str) -> None:  # (RULED BQ-13)
    assert name in json.dumps(_SPEC)


# --- cadence (RULED BQ-14) ------------------------------------------------------------------------


def test_route_serves_the_last_sample_without_measuring(world: World) -> None:
    meter = _CountingMeter(used=300 * GB, symbols={"BTCUSDT": GB})
    budget = _sampled(meter)
    first, second = _body(world, budget), _body(world, budget)
    assert (meter.volume_calls, meter.breakdown_calls) == (1, 1)
    assert first["generated_at"] == second["generated_at"]


# --- the report links to the tests (RULED BQ-02) --------------------------------------------------

_ROW = re.compile(
    r"^\|\s*(CK|ST|F)-\d\d[^|]*\|(?:[^|]*\|){0,4}\s*(?P<tests>[^|]*?)\s*\|\s*(?:PENDING|PASS|FAIL)\s*\|",
    re.M,
)


def test_every_report_row_names_a_test_that_exists() -> None:  # (RULED BQ-02)
    names = {n for n in globals() if n.startswith("test_")}
    rows = list(_ROW.finditer(REPORT.read_text(encoding="utf-8")))
    assert len(rows) >= 13 + 10  # at least the CK rows and the ST rows
    for row in rows:
        cell = row.group("tests")
        listed = [t.strip().split("[")[0] for t in cell.split(",")]
        assert all(t in names for t in listed) or cell.startswith("n/a"), row.group(0)
        assert not (row.group(1) in {"CK", "ST"} and cell.startswith("n/a")), row.group(0)


# --- baseline writer: the one documented command (RULED BQ-06) ------------------------------------


def _write_baseline() -> None:  # pragma: no cover
    mp = pytest.MonkeyPatch()
    try:
        w = build_world(mp)
        mp.setattr(w.app.state, "recording_control", _recorder(), raising=False)
        mp.setattr(w.app.state, "disk_budget", None, raising=False)
        body = _body(w, _sampled(_meter()))
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    finally:
        mp.undo()


if __name__ == "__main__" and "--write-baseline" in sys.argv:  # pragma: no cover
    _write_baseline()
