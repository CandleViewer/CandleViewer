"""#3991: the low-privilege ZAP nightlies' plan writer (`security/zap/nightly_plans.py`) and the
session script's surfaces (`security/zap/role_session.js`). No network and no ZAP: the script runs
on the repo's own contract and templates, and on files in `tmp_path`."""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SESSION_SCRIPT = ROOT / "security/zap/role_session.js"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"zap_{name}", ROOT / "security/zap" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


plans = _load("nightly_plans")
CONTRACT = yaml.safe_load(plans.CONTRACT.read_text(encoding="utf-8"))
TEMPLATES = {
    name: yaml.safe_load(path.read_text(encoding="utf-8"))
    for name, (path, _) in plans.PROFILES.items()
}


def _refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from [value] if key == "$ref" else _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def _component(api: dict[str, Any], ref: str) -> Any:
    _, _, kind, name = ref.split("/", 3)
    return api["components"][kind][name]


def _has_cycle(api: dict[str, Any]) -> bool:
    graph = {
        f"#/components/{kind}/{name}": set(_refs(node))
        for kind, group in api["components"].items()
        for name, node in group.items()
    }
    state: dict[str, int] = {}

    def cyclic(ref: str) -> bool:
        state[ref] = 1
        targets = graph.get(ref, set())  # a ref to another kind of component ends here
        found = any(state.get(to) == 1 or (to not in state and cyclic(to)) for to in targets)
        state[ref] = 2
        return found

    return any(cyclic(ref) for ref in sorted(graph) if ref not in state)


# --- nightly_plans.py ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "kept"),
    [
        ("/rules", True),
        ("/rules/{ruleId}/versions", True),
        ("/schemas/rule-ir.json", True),
        ("/rulesets", False),  # the same letters, another path
        ("/schemas/rule-ir.json.bak", False),
        ("/market/klines", False),
    ],
)
def test_a_path_is_on_the_surface_only_by_whole_segments(path: str, kept: bool) -> None:
    assert plans.on_surface(path, plans.PROFILES["rules"][1]) is kept


@pytest.mark.parametrize("profile", sorted(plans.PROFILES))
def test_each_cut_keeps_its_surface_whole_and_every_ref_resolves(profile: str) -> None:
    surface = plans.PROFILES[profile][1]
    api, _ = plans.cut_contract(CONTRACT, surface)
    expected = {path for path in CONTRACT["paths"] if plans.on_surface(path, surface)}
    assert set(api["paths"]) == expected and expected
    for ref in _refs(api):
        assert _component(api, ref) is not None  # nothing the import reads is missing
    assert api["components"]["securitySchemes"] == CONTRACT["components"]["securitySchemes"]


def test_the_rules_cut_ends_each_cycle_of_the_rule_ir_and_names_it() -> None:
    """The Rule IR's condition and operand trees refer to themselves: whole, they pass the nesting
    limit of ZAP's import, as the full contract did (#1026)."""
    api, edges = plans.cut_contract(CONTRACT, plans.PROFILES["rules"][1])
    assert edges and not _has_cycle(api)
    assert all(re.fullmatch(r"#/components/\S+ -> #/components/\S+", edge) for edge in edges)
    assert _has_cycle({"components": {"schemas": CONTRACT["components"]["schemas"]}})


def test_the_market_cut_has_no_cycle_to_end() -> None:
    api, edges = plans.cut_contract(CONTRACT, plans.PROFILES["market"][1])
    assert edges == [] and not _has_cycle(api)


def test_a_cycle_is_cut_at_the_reference_that_closes_it_and_nothing_else_moves() -> None:
    a, b, c = (f"#/components/schemas/{name}" for name in "ABC")
    contract = {
        "openapi": "3.0.3",
        "paths": {"/rules": {"get": {"responses": {"200": {"$ref": c}}}}},
        "components": {
            "schemas": {
                "A": {"properties": {"b": {"$ref": b}}},
                "B": {"properties": {"a": {"$ref": a}}, "items": {"type": "string"}},
                "C": {"properties": {"a": {"$ref": a}}},
            }
        },
    }
    api, edges = plans.cut_contract(contract, ("/rules",))
    assert edges == [f"{b} -> {a}"]
    assert api["components"]["schemas"]["B"]["properties"]["a"] == plans.OPEN
    assert api["components"]["schemas"]["A"]["properties"]["b"] == {"$ref": b}
    assert api["components"]["schemas"]["B"]["items"] == {"type": "string"}
    assert contract["components"]["schemas"]["B"]["properties"]["a"] == {"$ref": a}  # a copy


def test_the_plan_imports_the_cut_contract_and_leaves_the_template_alone() -> None:
    template = TEMPLATES["rules"]
    before = yaml.safe_dump(template)
    plan = plans.scan_plan(template, "/zap/wrk/zap-work/rules-openapi.yaml")
    (job,) = [job for job in plan["jobs"] if job["type"] == "openapi"]
    assert job["parameters"]["apiFile"] == "/zap/wrk/zap-work/rules-openapi.yaml"
    assert yaml.safe_dump(template) == before


def test_main_writes_the_cut_and_the_plan_inside_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert plans.main(["--profile", "rules", "--out", "zap-work"]) == 0
    api = yaml.safe_load((tmp_path / "zap-work/rules-openapi.yaml").read_text(encoding="utf-8"))
    plan = yaml.safe_load((tmp_path / "zap-work/rules-scan.yaml").read_text(encoding="utf-8"))
    assert not _has_cycle(api)
    (job,) = [job for job in plan["jobs"] if job["type"] == "openapi"]
    assert job["parameters"]["apiFile"] == "/zap/wrk/zap-work/rules-openapi.yaml"
    assert "cut the cycle at" in capsys.readouterr().out


@pytest.mark.parametrize("out", ["/tmp/zap-work", "../zap-work", "zap-work/../.."])
def test_main_refuses_an_out_outside_the_checkout_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, out: str
) -> None:
    monkeypatch.chdir(tmp_path)
    assert plans.main(["--profile", "market", "--out", out]) == 2
    assert list(tmp_path.iterdir()) == []


# --- role_session.js ----------------------------------------------------------------------------


def _session_rule(name: str) -> re.Pattern[str]:
    """A regex literal of the session script (`var NAME = /.../;`), as JS `test` reads it."""
    script = SESSION_SCRIPT.read_text(encoding="utf-8")
    (literal,) = re.findall(rf"^var {name} = /(.+)/;$", script, re.MULTILINE)
    return re.compile(literal.replace("\\/", "/"))


@pytest.mark.parametrize(
    ("surface", "path", "sent"),
    [
        ("RULES", "/rules", True),
        ("RULES", "/rules/0f4c/versions?limit=1", True),
        ("RULES", "/schemas/rule-ir.json", True),
        ("RULES", "/me", True),
        ("RULES", "/rulesets", False),
        ("RULES", "/schemas/rule-ir.jsonx", False),
        ("RULES", "/admin/overview", False),
        ("RULES", "/auth/logout?next=/rules", False),
        ("MARKET", "/market/klines?symbol=BTCUSDT&interval=1", True),
        ("MARKET", "/market/bars", True),
        ("MARKET", "/me?x=1", True),
        ("MARKET", "/market/orderbook", False),
        ("MARKET", "/market", False),
        ("MARKET", "/rules", False),
    ],
)
def test_the_session_goes_only_to_the_profiles_surface_and_the_liveness_check(
    surface: str, path: str, sent: bool
) -> None:
    assert bool(_session_rule(surface).search(path)) is sent


def test_the_profile_picks_the_surface_and_any_other_name_gets_none() -> None:
    script = SESSION_SCRIPT.read_text(encoding="utf-8")
    assert 'var PROFILE = System.getenv("ZAP_PROFILE") || "admin";' in script
    choice = re.search(r"var SURFACE =\s+(.+);", script)
    assert choice is not None
    assert choice.group(1) == (
        'PROFILE === "admin" ? ADMIN : PROFILE === "rules" ? RULES : '
        'PROFILE === "market" ? MARKET : null'
    )
    assert set(plans.PROFILES) == {"rules", "market"}  # each has its surface above
