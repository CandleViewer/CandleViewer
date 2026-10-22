"""#3991: the low-privilege ZAP nightlies (`dast-rules-nightly.yml`, `dast-market-nightly.yml`, both
through `_dast-low-priv.yml`): `security/zap/nightly_plans.py`, the two templates, the session
script's surfaces and the workflows. No network and no ZAP: the script runs on the repo's own
contract and templates, and on files in `tmp_path`."""

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
CALLED = ROOT / ".github/workflows/_dast-low-priv.yml"
CALLERS = {
    "rules": ROOT / ".github/workflows/dast-rules-nightly.yml",
    "market": ROOT / ".github/workflows/dast-market-nightly.yml",
}
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


# --- the templates ------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", sorted(plans.PROFILES))
def test_each_template_loads_the_session_script_first_and_names_no_token(profile: str) -> None:
    template = TEMPLATES[profile]
    first = template["jobs"][0]
    assert first["type"] == "script"
    assert first["parameters"]["source"] == "/zap/wrk/security/zap/role_session.js"
    text = yaml.safe_dump(template)  # every job and parameter ZAP reads; comments are not read
    assert not re.search(r"replacer|ZAP_LOWPRIV_TOKEN|ZAP_AUTH_TOKEN|ZAP_CSRF_TOKEN|Bearer", text)


@pytest.mark.parametrize("profile", sorted(plans.PROFILES))
def test_each_template_checks_the_session_before_and_after_the_scan(profile: str) -> None:
    jobs = TEMPLATES[profile]["jobs"]
    kinds = [job["type"] for job in jobs]
    before, after = kinds.index("requestor"), len(kinds) - 1 - kinds[::-1].index("requestor")
    assert before < kinds.index("openapi") and after > kinds.index("activeScan")
    for job in (jobs[before], jobs[after]):
        assert job["requests"] == [
            {"url": "${ZAP_TARGET}/me", "method": "GET", "responseCode": 200}
        ]


@pytest.mark.parametrize("profile", sorted(plans.PROFILES))
def test_each_scan_fits_in_one_12_minute_bearer(profile: str) -> None:
    jobs = {job["type"]: job for job in TEMPLATES[profile]["jobs"]}
    passive = jobs["passiveScan-wait"]["parameters"]["maxDuration"]
    active = jobs["activeScan"]["parameters"]["maxScanDurationInMins"]
    assert passive + active <= 10  # two minutes left for start-up, the import and /me (ADR-0020)


@pytest.mark.parametrize(
    ("profile", "include"),
    [
        ("rules", ["${ZAP_TARGET}/rules([/?].*)?", "${ZAP_TARGET}/schemas/rule-ir\\.json"]),
        ("market", ["${ZAP_TARGET}/market/klines([/?].*)?", "${ZAP_TARGET}/market/bars([/?].*)?"]),
    ],
)
def test_each_context_is_its_surface(profile: str, include: list[str]) -> None:
    (context,) = TEMPLATES[profile]["env"]["contexts"]
    assert context["includePaths"] == include
    assert all(url.startswith("${ZAP_TARGET}/") for url in context["urls"])


def test_the_market_filters_apply_before_the_first_request_and_name_no_absent_rule() -> None:
    jobs = TEMPLATES["market"]["jobs"]
    kinds = [job["type"] for job in jobs]
    assert kinds.index("alertFilter") < kinds.index("requestor")
    (filters,) = [job["alertFilters"] for job in jobs if job["type"] == "alertFilter"]
    assert [entry["ruleId"] for entry in filters] == [90022]  # 10049 is not in ZAP 2.17.0


def test_the_rules_filter_ends_one_false_positive_and_no_other_traversal() -> None:
    """Rule 6 flagged `?symbol=vocabulary` (the URL's own name) once: only that attack on that
    parameter is a false positive; any other payload on `symbol` is still reported."""
    jobs = TEMPLATES["rules"]["jobs"]
    kinds = [job["type"] for job in jobs]
    assert kinds.index("alertFilter") < kinds.index("requestor")
    (filters,) = [job["alertFilters"] for job in jobs if job["type"] == "alertFilter"]
    assert filters == [
        {
            "ruleId": 6,
            "newRisk": "False Positive",
            "url": ".*/rules/vocabulary([?].*)?",
            "urlRegex": True,
            "parameter": "symbol",
            "attack": "vocabulary",
        }
    ]


def test_no_plan_names_a_rule_the_pinned_image_lacks() -> None:
    """ZAP 2.17.0 exits non-zero on a plan that names a rule it does not have (#3991, run 1)."""
    absent = {10049, 40024}
    for template in TEMPLATES.values():
        for job in template["jobs"]:
            named = {rule["id"] for rule in job.get("policyDefinition", {}).get("rules", [])}
            named |= {entry["ruleId"] for entry in job.get("alertFilters", [])}
            assert not named & absent


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


# --- the workflows ------------------------------------------------------------------------------


@pytest.mark.parametrize("profile", sorted(CALLERS))
def test_each_nightly_calls_the_low_privilege_workflow_with_its_profile(profile: str) -> None:
    workflow = yaml.safe_load(CALLERS[profile].read_text(encoding="utf-8"))
    triggers = workflow[True]  # YAML 1.1 reads the `on` key as True
    assert set(triggers) == {"schedule", "workflow_dispatch"}  # never a pull request
    assert triggers["workflow_dispatch"] in (None, {})  # no input can move the target
    assert workflow["permissions"] == {"contents": "read"}
    (job,) = workflow["jobs"].values()
    assert job["uses"] == "./.github/workflows/_dast-low-priv.yml"
    assert job["with"]["profile"] == profile
    assert (ROOT / job["with"]["baseline"]).is_file()
    (report,) = [entry for entry in TEMPLATES[profile]["jobs"] if entry["type"] == "report"]
    assert report["parameters"]["reportFile"] == job["with"]["report"]


def _steps() -> dict[str, dict[str, Any]]:
    workflow = yaml.safe_load(CALLED.read_text(encoding="utf-8"))
    (job,) = workflow["jobs"].values()
    return {step.get("name", step.get("uses", "")): step for step in job["steps"]}


def test_the_low_privilege_workflow_is_only_called_and_pins_everything() -> None:
    text = CALLED.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert set(workflow[True]) == {"workflow_call"}
    assert workflow["permissions"] == {"contents": "read"}
    uses = re.findall(r"uses:\s*(\S+)", text)
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", use) for use in uses)
    assert re.search(r"zaproxy:2\.17\.0@sha256:[0-9a-f]{64}", text)
    assert re.findall(r"\bsecrets\.\w+", text) == []  # synthetic credentials only, made per run
    assert re.search(r"ZAP_TARGET: http://127\.0\.0\.1:\d+\n", text)
    assert re.findall(r"uv run(?! --frozen)", text) == []


def test_the_scan_signs_in_as_the_viewer_and_passes_only_its_profile() -> None:
    steps = _steps()
    scan = steps["The passive and active scan, as the Viewer"]["run"]
    assert "security/zap/mint_sessions.py" in scan and '--username "$ZAP_VIEWER_USER"' in scan
    assert '--env-file "$envfile" -e ZAP_TARGET -e ZAP_PROFILE' in scan
    gates = steps["The scan stayed signed in, and no new medium+ alert"]
    assert gates["if"] == "${{ !cancelled() }}"
    assert "check_liveness.py" in gates["run"] and "baseline_gate.py" in gates["run"]


def test_zap_makes_no_unsolicited_request() -> None:
    """`-silent`: no update check and no call home leave the runner (C-13.5), as the admin
    nightly runs (#4031)."""
    scan = _steps()["The passive and active scan, as the Viewer"]["run"]
    assert "zap.sh -cmd -silent -autorun" in scan


def test_no_scan_container_outlives_the_job_and_the_checkout_holds_no_token() -> None:
    """The container ZAP mounts the checkout into is removed (`--rm`), and the checkout
    keeps no token (`persist-credentials: false`), so the mount hands ZAP none."""
    steps = _steps()
    assert "docker run --rm " in steps["The passive and active scan, as the Viewer"]["run"]
    checkout = next(
        s for s in steps.values() if str(s.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] is False


def test_the_artefact_check_searches_every_secret_the_run_makes_before_any_upload() -> None:
    steps = _steps()
    made = steps["Make this run's synthetic credentials (masked, never echoed)"]["run"]
    generated = re.search(r"for name in (.+?); do secret", made, re.DOTALL)
    assert generated is not None
    names = set(generated.group(1).replace("\\", " ").split())
    scrub = steps["No session value in the plan, logs or report (else nothing is uploaded)"]
    assert set(re.findall(r"--env (\w+)", scrub["run"])) == names
    files = re.findall(r'--secret-file "([^"]+)"', scrub["run"])
    assert files == ["$RUNNER_TEMP/cv/*.totp", "$RUNNER_TEMP/cv-lane/lane.key"]
    upload = steps["Upload the plan, logs and report (the session in them died with the stack)"]
    assert upload["if"] == "${{ always() && steps.scrub.outcome == 'success' }}"
    scrubbed = scrub["run"].split("\\\n")[-1].split()[-2:]
    assert scrubbed == ['"$WORK"', "zap-reports"]
    assert upload["with"]["path"].split() == ["zap-work/", "zap-reports/"]
