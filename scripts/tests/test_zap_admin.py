"""E42-X03: the ZAP admin profile's scripts (`security/zap/admin_requests.py`, `mint_sessions.py`,
`check_admin_denials.py`, `check_artefact_secrets.py`, and the scan gate's wording in
`check_liveness.py`), its template and its nightly workflow. No network and no ZAP: each script is
driven with fakes, files in `tmp_path` and the repo's own matrix and template."""

from __future__ import annotations

import base64
import functools
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar
from urllib.parse import quote

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/dast-admin-nightly.yml"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"zap_{name}", ROOT / "security/zap" / f"{name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


plans = _load("admin_requests")
mint = _load("mint_sessions")
denials = _load("check_admin_denials")
artefacts = _load("check_artefact_secrets")
liveness = _load("check_liveness")
MATRIX = yaml.safe_load(plans.MATRIX.read_text(encoding="utf-8"))
TEMPLATE = yaml.safe_load(plans.TEMPLATE.read_text(encoding="utf-8"))
TARGET = "http://127.0.0.1:8000"
SESSION_SCRIPT = ROOT / "security/zap/role_session.js"
API_FILE = "/zap/wrk/zap-work/admin-openapi.yaml"


# --- admin_requests.py -------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["http://127.0.0.1:8000", "http://localhost:18000/"])
def test_a_loopback_target_is_admitted(target: str) -> None:
    assert plans.check_target(target) == target.rstrip("/")


@pytest.mark.parametrize(
    "target",
    [
        "https://candleviewer.tailnet.internal",  # the contract's production server
        "http://candleviewer.tailnet.internal:8000",
        "http://box.example.ts.net:8000",
        "http://10.0.0.5:8000",
        "https://127.0.0.1:8000",
        "http://127.0.0.1:8000/api/v1",
        "http://user:pw@127.0.0.1:8000",
        "http://127.0.0.1:8000/?x=1",
        "file:///etc/passwd",
    ],
)
def test_any_other_target_is_refused(target: str) -> None:
    with pytest.raises(plans.TargetRefused):
        plans.check_target(target)


_HIDDEN = "pw-" + "never-shown"  # built here, so no credential-shaped literal is committed


@pytest.mark.parametrize("check", [plans.check_target, mint.check_target])
@pytest.mark.parametrize(
    "target",
    [
        f"http://zap:{_HIDDEN}@127.0.0.1:8000",
        f"http://:{_HIDDEN}@127.0.0.1:8000",
        f"http://127.0.0.1:8000/?token={_HIDDEN}",
        f"http://127.0.0.1:8000/{_HIDDEN}",
    ],
)
def test_a_refused_target_is_named_by_scheme_host_and_port_only(check: Any, target: str) -> None:
    with pytest.raises((plans.TargetRefused, mint.MintFailed)) as refused:
        check(target)
    assert _HIDDEN not in str(refused.value) and "zap" not in str(refused.value)
    assert "'http://127.0.0.1:8000'" in str(refused.value)


def _planned(role: str) -> dict[str, dict[str, Any]]:
    return {item["operation"]: item for item in plans.denial_requests(MATRIX, role, TARGET)}


def test_the_manager_plan_holds_what_the_matrix_refuses_a_manager_and_nothing_it_allows() -> None:
    planned = _planned("manager")
    allowed = {"GET /admin/audit", "POST /admin/recorder/compact", "POST /admin/recorder/import"}
    assert allowed.isdisjoint(planned)
    assert "GET /admin/backups/{backupId}/download/{token}" not in planned  # public: the link
    assert planned["GET /admin/overview"]["expected"] == 403
    assert planned["POST /users/{userId}/mfa/reset"]["expected"] == 403
    for key in planned:
        row = MATRIX["operations"][key]
        assert row["outcomes"]["manager_without_grant"] == "403"
        assert row["state"] in ("executed", "not_executable")


@pytest.mark.parametrize("role", sorted(plans.ROLES))
def test_no_operation_the_matrix_marks_not_mounted_is_planned(role: str) -> None:
    states = {key: MATRIX["operations"][key]["state"] for key in _planned(role)}
    assert "not_mounted" not in states.values()


def test_the_viewer_plan_holds_the_audit_read_and_the_recorder() -> None:
    planned = _planned("viewer")
    for key in ("GET /admin/audit", "POST /admin/recorder/compact", "POST /admin/recorder/import"):
        assert planned[key]["expected"] == 403 and planned[key]["recorded"] is True


def test_a_reviewed_deviation_is_planned_with_its_own_status_and_no_record() -> None:
    item = _planned("manager")["PUT /admin/log-level"]
    assert (item["expected"], item["recorded"]) == (501, False)
    assert item["deviation"].startswith("X03-F5")
    assert set(plans.DEVIATIONS) <= set(MATRIX["operations"])


def test_each_request_is_whole_with_a_fresh_uuid4_correlation_id() -> None:
    planned = _planned("manager")
    ids = [item["correlation_id"] for item in planned.values()]
    assert len(set(ids)) == len(ids)
    assert all(uuid.UUID(value).version == 4 for value in ids)
    assert planned["DELETE /users/{userId}"]["body"] is None
    assert planned["POST /users/{userId}/invite"]["body"] == "{}"
    tier = planned["PUT /admin/capacity/subaccount-tier"]
    assert json.loads(tier["body"]) == {"tier": "business_kyc"}
    export = planned["GET /admin/statecharts/{machineKey}/export"]
    assert export["url"] == f"{TARGET}/admin/statecharts/kill_switch/export"
    assert planned["GET /admin/backups/{backupId}"]["url"].endswith(plans.FILLER)
    assert all("{" not in item["url"] for item in planned.values())


def test_the_denial_plan_is_the_session_script_and_one_requestor_of_the_planned_requests() -> None:
    requests = plans.denial_requests(MATRIX, "viewer", TARGET)
    plan = plans.denial_plan(TEMPLATE, "viewer", requests)
    assert plan["env"] == TEMPLATE["env"]
    session, requestor = plan["jobs"]
    assert session["type"] == "script" and requestor["type"] == "requestor"
    assert len(requestor["requests"]) == len(requests)
    for entry, item in zip(requestor["requests"], requests, strict=True):
        assert entry["headers"][:2] == [
            f"X-Correlation-Id: {item['correlation_id']}",
            f"X-Request-Id: {item['correlation_id']}",  # the admin principal reads this one
        ]
        assert entry["responseCode"] == item["expected"]
        assert ("data" in entry) is (item["body"] is not None)


def test_both_plans_load_the_session_script_first_and_write_no_token() -> None:
    """ZAP expands no `${VAR}` inside a replacer rule, so the role's session comes from an
    httpsender script that reads it from the environment: no plan names a token or its variable."""
    requests = plans.denial_requests(MATRIX, "viewer", TARGET)
    denial = plans.denial_plan(TEMPLATE, "viewer", requests)
    for plan in (denial, plans.scan_plan(TEMPLATE, "viewer", API_FILE)):
        script = plan["jobs"][0]  # before any request
        assert script["type"] == "script" and script["parameters"]["type"] == "httpsender"
        assert script["parameters"]["action"] == "add"
        source = script["parameters"]["source"]  # the checkout is mounted at /zap/wrk
        assert ROOT / source.removeprefix("/zap/wrk/") == SESSION_SCRIPT
        text = yaml.safe_dump(plan)
        assert not re.search(r"replacer|ZAP_AUTH_TOKEN|ZAP_CSRF_TOKEN|Bearer", text)


def test_the_scan_plan_is_the_template_with_the_roles_report() -> None:
    plan = plans.scan_plan(TEMPLATE, "manager", API_FILE)
    report = [job for job in plan["jobs"] if job["type"] == "report"]
    assert report[0]["parameters"]["reportFile"] == "admin-surface-manager"
    (imported,) = [job for job in plan["jobs"] if job["type"] == "openapi"]
    assert imported["parameters"]["apiFile"] == API_FILE
    assert [job["type"] for job in plan["jobs"]] == [job["type"] for job in TEMPLATE["jobs"]]
    assert TEMPLATE["jobs"][-1]["parameters"]["reportFile"] == "admin-surface"  # not mutated


def test_the_passive_config_comes_before_the_first_request() -> None:
    """A job applies from where it runs, so the config comes before any request."""
    plan = plans.scan_plan(TEMPLATE, "viewer", API_FILE)
    assert [job["type"] for job in plan["jobs"]] == [
        "script",  # the session, before any request
        "passiveScan-config",  # before the first response is scanned
        "requestor",  # admin-probe-after-config: the session reaches the surface, refused
        "requestor",  # session-live-before-scan
        "openapi",
        "passiveScan-wait",
        "activeScan",
        "requestor",  # session-live-after-scan
        "report",
    ]


def test_the_passive_config_sets_no_rule_threshold() -> None:
    """ZAP 2.17.0 logs a threshold this job sets and never applies it, as run 39600018445's probe
    showed (#3991), so the config sets none."""
    plan = plans.scan_plan(TEMPLATE, "viewer", API_FILE)
    (config,) = [job for job in plan["jobs"] if job["type"] == "passiveScan-config"]
    assert config["parameters"]["scanOnlyInScope"] is True
    assert "rules" not in config


@pytest.fixture(scope="module")
def written_plans(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One real run of `main` (it parses the whole contract), in a checkout of its own."""
    checkout = tmp_path_factory.mktemp("checkout")
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(checkout)  # ZAP mounts the working directory, so `--out` is relative
        assert plans.main(["--target", TARGET, "--out", "ok"]) == 0
    return checkout / "ok"


def test_main_writes_both_roles_plans_and_the_cut_contract(written_plans: Path) -> None:
    names = sorted(path.name for path in written_plans.iterdir())
    assert names == [
        "admin-openapi.yaml",
        *(
            f"{role}-{kind}"
            for role in ("manager", "viewer")
            for kind in ("denials.yaml", "requests.json", "scan.yaml")
        ),
    ]


@pytest.mark.parametrize("role", sorted(plans.ROLES))
def test_main_points_the_scan_at_the_cut_contract_where_zap_sees_the_checkout(
    written_plans: Path, role: str
) -> None:
    scan = yaml.safe_load((written_plans / f"{role}-scan.yaml").read_text(encoding="utf-8"))
    (imported,) = [job for job in scan["jobs"] if job["type"] == "openapi"]
    assert imported["parameters"]["apiFile"] == "/zap/wrk/ok/admin-openapi.yaml"


def test_main_refuses_a_production_target_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert plans.main(["--target", "https://candleviewer.tailnet.internal", "--out", "no"]) == 2
    assert not (tmp_path / "no").exists()


@pytest.mark.parametrize("out", ["../x", "a/../../x", "a/.."])
def test_main_refuses_an_out_directory_that_climbs_out_of_the_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    out: str,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.chdir(checkout)
    assert plans.main(["--target", TARGET, "--out", out]) == 2
    assert "relative" in capsys.readouterr().err
    assert list(checkout.iterdir()) == [] and not (tmp_path / "x").exists()  # nothing written


def test_main_refuses_an_absolute_out_directory_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert plans.main(["--target", TARGET, "--out", str(tmp_path / "abs")]) == 2
    assert "relative" in capsys.readouterr().err
    assert not (tmp_path / "abs").exists()


@functools.cache
def _contract() -> dict[str, Any]:
    contract: dict[str, Any] = yaml.safe_load(plans.CONTRACT.read_text(encoding="utf-8"))
    return contract


def _refs(node: object) -> set[str]:
    if isinstance(node, dict):
        found = {node["$ref"]} if isinstance(node.get("$ref"), str) else set()
        return found.union(*(_refs(value) for value in node.values()))
    return set().union(*(_refs(value) for value in node)) if isinstance(node, list) else set()


def test_the_admin_contract_is_the_surface_and_what_it_reaches_with_no_cycle() -> None:
    """ZAP's import resolves each schema in full, and the contract's recursive condition tree
    passed its nesting limit: the scan imports the surface, which reaches no cycle."""
    contract = _contract()
    cut = plans.admin_contract(contract)
    surface = {path for path in contract["paths"] if path.startswith(plans.SURFACE)}
    assert set(cut["paths"]) == surface
    graph = {
        f"#/components/{kind}/{name}": _refs(node)
        for kind, items in cut["components"].items()
        for name, node in items.items()
    }
    assert _refs(cut["paths"]) <= set(graph)
    assert all(refs <= set(graph) for refs in graph.values())  # every reference resolves in the cut
    while leaves := {node for node, refs in graph.items() if not refs}:
        graph = {node: refs - leaves for node, refs in graph.items() if node not in leaves}
    assert graph == {}  # nothing left that refers back to itself


def test_the_cut_keeps_the_contracts_version_security_requirement_and_schemes() -> None:
    """The import needs the document's version and info, and each operation's requirement names a
    scheme that nothing references, so the schemes stay whole."""
    contract = _contract()
    cut = plans.admin_contract(contract)
    assert {"openapi", "info", "paths", "components"} <= set(cut)
    assert (cut["openapi"], cut["info"]) == (contract["openapi"], contract["info"])
    assert cut["security"] == contract["security"]
    assert cut["components"]["securitySchemes"] == contract["components"]["securitySchemes"]


def test_the_template_holds_no_credential_and_scans_the_admin_surface_only() -> None:
    text = plans.TEMPLATE.read_text(encoding="utf-8")
    assert set(re.findall(r"\$\{(\w+)\}", text)) == {"ZAP_TARGET"}
    (context,) = TEMPLATE["env"]["contexts"]
    # ZAP includes everything under each url: the whole host would make the rest a no-op
    assert context["urls"] == ["${ZAP_TARGET}/admin", "${ZAP_TARGET}/users"]
    assert context["includePaths"] == ["${ZAP_TARGET}/admin(/.*)?", "${ZAP_TARGET}/users(/.*)?"]
    assert context["excludePaths"] == ["${ZAP_TARGET}/auth/logout.*", "${ZAP_TARGET}/me/sessions.*"]
    script = SESSION_SCRIPT.read_text(encoding="utf-8")
    names = {"ZAP_TARGET", "ZAP_AUTH_TOKEN", "ZAP_CSRF_TOKEN"}
    assert set(re.findall(r'getenv\("(\w+)"\)', script)) == names
    assert set(re.findall(r'setHeader\("([\w-]+)"', script)) == {
        "Authorization",
        "X-CSRF-Token",
        "Cookie",
    }
    # the whole guard: with any value missing nothing is added, and only the target's own host
    assert 'if (!TARGET || !BEARER || !CSRF || url.indexOf(TARGET + "/") !== 0) return;' in script
    assert "if (!SURFACE.test(rest) || DOT_SEGMENT.test(rest)) return;" in script  # both rules
    (active,) = [job for job in TEMPLATE["jobs"] if job["type"] == "activeScan"]
    rules = {rule["id"] for rule in active["policyDefinition"]["rules"]}
    assert rules == {40018, 40012, 40014, 90020, 6, 90035}


def _session_rule(name: str) -> re.Pattern[str]:
    """A regex literal of the session script (`var NAME = /.../;`), as JS `test` reads it."""
    script = SESSION_SCRIPT.read_text(encoding="utf-8")
    (literal,) = re.findall(rf"^var {name} = /(.+)/;$", script, re.MULTILINE)
    return re.compile(literal.replace("\\/", "/"))


@pytest.mark.parametrize(
    ("path", "sent"),
    [
        ("/admin/overview", True),
        ("/admin", True),
        ("/admin?x=1", True),
        ("/users/00000000-0000-4000-8000-0000000000ff/sessions?limit=1", True),
        ("/me", True),
        ("/me?x=1", True),
        ("/me/", False),
        ("/me/sessions/00000000-0000-4000-8000-0000000000ff", False),
        ("/auth/logout", False),
        ("/auth/logout?next=/admin", False),  # a surface path inside the query: the `^` anchor
        ("/other/admin", False),  # and a surface name deeper down: the `^` anchor again
        ("/administrators", False),
        ("/health/live", False),
    ],
)
def test_the_session_goes_only_to_the_admin_surface_and_the_liveness_check(
    path: str, sent: bool
) -> None:
    assert bool(_session_rule("SURFACE").search(path)) is sent


@pytest.mark.parametrize(
    ("path", "sent"),
    [
        ("/admin/../auth/logout", False),
        ("/admin/./overview", False),
        ("/admin/.", False),
        ("/users/..", False),
        ("/users/../me/sessions/x?limit=1", False),
        ("/admin/..?x=1", False),
        ("/admin/%2e%2E/auth/logout", False),  # a URI may write a dot as %2e
        ("/admin/.%2e", False),
        ("/admin/audit?path=../../etc/passwd", True),  # the scan's traversal payloads: a query
        ("/admin/audit?next=/../x", True),
        ("/admin/v1.0/audit..json", True),  # dots in a name are no dot segment
        ("/admin/..hidden", True),
        ("/admin/a../b", True),
    ],
)
def test_the_session_is_withheld_from_a_path_with_a_dot_segment_and_from_nothing_else(
    path: str, sent: bool
) -> None:
    """`/admin/../auth/logout` is on the surface by its prefix, and a server that resolved the dots
    would send it elsewhere: no session goes along a dot segment of the path, not of the query."""
    surface, dots = _session_rule("SURFACE"), _session_rule("DOT_SEGMENT")
    assert bool(surface.search(path) and not dots.search(path)) is sent


def test_the_import_and_both_scans_fit_in_one_12_minute_bearer() -> None:
    jobs = {job["type"]: job for job in TEMPLATE["jobs"]}
    passive = jobs["passiveScan-wait"]["parameters"]["maxDuration"]
    active = jobs["activeScan"]["parameters"]["maxScanDurationInMins"]
    assert passive + active <= 10  # two minutes left for start-up, the import and /me (ADR-0020)


# --- mint_sessions.py ---------------------------------------------------------------------------

_SEED = base64.b32encode(b"12345678901234567890").decode()  # RFC 6238 appendix B, SHA-1


@pytest.mark.parametrize(("at", "code"), [(59, "94287082"), (1111111109, "07081804")])
def test_totp_meets_rfc_6238(at: int, code: str) -> None:
    assert mint.totp(_SEED, at, digits=8) == code
    assert mint.totp(_SEED, at) == code[-6:]


class _Api:
    """A fake API: each call's answer by path, and the calls in order."""

    def __init__(self, **answers: Any) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str, Any, dict[str, str]]] = []

    def __call__(self, method: str, url: str, body: Any, headers: dict[str, str]) -> Any:
        self.calls.append((method, url, body, headers))
        return self.answers[url.removeprefix(TARGET)]


def _ok_api() -> _Api:
    return _Api(
        **{
            "/auth/login": mint.Answer(200, {"status": "mfa_required", "mfa_token": "m"}, {}),
            "/auth/mfa/verify": mint.Answer(
                200,
                {"status": "authenticated", "tokens": {"access_token": "b"}},
                {mint.CSRF_COOKIE: "c"},
            ),
            "/me": mint.Answer(200, {}, {}),
        }
    )


def test_mint_waits_for_a_fresh_totp_step_and_proves_the_session() -> None:
    now, slept, api = [1000.0], [], _ok_api()

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    bearer, csrf = mint.mint(
        TARGET, "zap-manager", "pw", _SEED, send=api, clock=lambda: now[0], sleep=sleep
    )
    assert (bearer, csrf) == ("b", "c")
    assert slept == [20.5]  # 1000 s is 10 s into its step: the next one starts in 20 s
    (_, _, login, _), (_, _, verify, _), (_, _, _, me) = api.calls
    assert login == {"identifier": "zap-manager", "password": "pw"}
    assert verify["code"] == mint.totp(_SEED, 1020.5) and verify["method"] == "totp"
    assert me == {"Authorization": "Bearer b"}


@pytest.mark.parametrize(
    ("path", "answer", "step"),
    [
        ("/auth/login", mint.Answer(401, {"code": "unauthenticated"}, {}), "login"),
        ("/auth/mfa/verify", mint.Answer(401, {"code": "mfa_invalid"}, {}), "mfa verify"),
        ("/auth/mfa/verify", mint.Answer(200, {"tokens": {"access_token": "b"}}, {}), "mfa verify"),
        ("/me", mint.Answer(401, {}, {}), "session check"),
    ],
)
def test_mint_names_the_step_that_failed_and_never_a_credential(
    path: str, answer: Any, step: str
) -> None:
    api = _ok_api()
    api.answers[path] = answer
    with pytest.raises(mint.MintFailed, match=f"^{step}: HTTP") as failed:
        mint.mint(
            TARGET,
            "zap-viewer",
            "hunter2-pw",
            _SEED,
            send=api,
            clock=lambda: 0.0,
            sleep=lambda s: None,
        )
    assert "hunter2-pw" not in str(failed.value) and _SEED not in str(failed.value)


def test_write_env_masks_first_and_keeps_the_file_private(tmp_path: Path) -> None:
    out, said = tmp_path / "manager.env", []
    out.write_text("old", encoding="ascii")
    out.chmod(0o644)
    mint.write_env(
        out, "bearer-x", "csrf-y", announce=lambda line: said.append((line, out.read_text()))
    )
    assert said == [("::add-mask::bearer-x", "old"), ("::add-mask::csrf-y", "old")]
    assert out.read_text(encoding="ascii") == "ZAP_AUTH_TOKEN=bearer-x\nZAP_CSRF_TOKEN=csrf-y\n"
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_mint_main_refuses_a_remote_target_and_an_empty_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = tmp_path / "totp"
    secret.write_text(_SEED, encoding="ascii")
    args = ["--username", "u", "--password-env", "ZAP_PW", "--totp-secret-file", str(secret)]
    monkeypatch.setenv("ZAP_PW", "pw")
    assert mint.main(["--target", "http://10.0.0.5:8000", *args, "--out", str(tmp_path / "a")]) == 1
    monkeypatch.setenv("ZAP_PW", "")
    assert mint.main(["--target", TARGET, *args, "--out", str(tmp_path / "b")]) == 1
    assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists()
    assert "pw" not in capsys.readouterr().out.replace("--password-env", "")


class _Response:
    def __init__(self, status: int, body: bytes, cookies: list[str]) -> None:
        self.status, self.body = status, body
        self.reads: list[int] = []
        self.headers = _Headers(cookies)

    def read(self, size: int) -> bytes:
        self.reads.append(size)
        return self.body[:size]


class _Headers:
    def __init__(self, cookies: list[str]) -> None:
        self.cookies = cookies

    def get_all(self, name: str) -> list[str] | None:
        return self.cookies if name == "Set-Cookie" and self.cookies else None


class _Connection:
    """A fake `http.client.HTTPConnection`: answers by path, records what was sent, no socket."""

    made: ClassVar[list[_Connection]] = []
    answers: ClassVar[dict[str, _Response]] = {}

    def __init__(self, host: str, port: int | None, timeout: float) -> None:
        self.target, self.closed = (host, port, timeout), False
        self.sent: list[tuple[str, str, bytes | None, dict[str, str]]] = []
        _Connection.made.append(self)

    def request(self, method: str, path: str, body: bytes | None, headers: dict[str, str]) -> None:
        self.sent.append((method, path, body, headers))

    def getresponse(self) -> _Response:
        return self.answers[self.sent[-1][1]]

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch) -> type[_Connection]:
    _Connection.made, _Connection.answers = [], {}
    monkeypatch.setattr(mint.http.client, "HTTPConnection", _Connection)
    return _Connection


def test_exchange_reads_the_csrf_cookie_and_the_json_answer(connection: type[_Connection]) -> None:
    connection.answers["/auth/mfa/verify"] = _Response(
        200,
        b'{"tokens": {"access_token": "b"}}',
        [
            "__Host-cv_csrf=c1; Path=/; Secure; SameSite=Strict",
            "cv_refresh=r1; Path=/auth; Secure; HttpOnly",
        ],
    )
    answer = mint.exchange("POST", f"{TARGET}/auth/mfa/verify", {"code": "123456"}, {"X": "y"})
    assert answer == mint.Answer(
        200, {"tokens": {"access_token": "b"}}, {mint.CSRF_COOKIE: "c1", "cv_refresh": "r1"}
    )
    (made,) = connection.made
    assert made.target == ("127.0.0.1", 8000, mint.TIMEOUT_S) and made.closed
    method, path, body, headers = made.sent[0]
    assert (method, path, json.loads(body or b"")) == (
        "POST",
        "/auth/mfa/verify",
        {"code": "123456"},
    )
    assert headers == {"Content-Type": "application/json", "X": "y"}


@pytest.mark.parametrize("raw", [b"<html>502</html>", b"[1, 2]", b"", b"\xff\xfa"])
def test_exchange_answers_an_empty_body_for_anything_but_a_json_object(
    connection: type[_Connection], raw: bytes
) -> None:
    connection.answers["/me"] = _Response(502, raw, [])
    assert mint.exchange("GET", f"{TARGET}/me", None, {}) == mint.Answer(502, {}, {})
    assert connection.made[0].sent[0][2] is None  # a GET sends no body


def test_exchange_reads_at_most_its_bound_and_closes_even_on_an_error(
    connection: type[_Connection],
) -> None:
    connection.answers["/me"] = _Response(200, b"{}" + b" " * (2 * mint.MAX_BODY_BYTES), [])
    mint.exchange("GET", f"{TARGET}/me", None, {})
    assert connection.answers["/me"].reads == [mint.MAX_BODY_BYTES]
    with pytest.raises(KeyError):  # no answer for this path: getresponse raises
        mint.exchange("GET", f"{TARGET}/nowhere", None, {})
    assert all(made.closed for made in connection.made)


_MINTED = {"bearer": "b" * 24, "csrf": "c" * 24}  # low-entropy stand-ins, not session values


def test_mint_main_mints_masks_and_writes_the_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    connection: type[_Connection],
) -> None:
    connection.answers.update(
        {
            "/auth/login": _Response(200, b'{"status": "mfa_required", "mfa_token": "m"}', []),
            "/auth/mfa/verify": _Response(
                200,
                json.dumps({"tokens": {"access_token": _MINTED["bearer"]}}).encode(),
                [f"__Host-cv_csrf={_MINTED['csrf']}; Path=/; Secure"],
            ),
            "/me": _Response(200, b"{}", []),
        }
    )
    real_mint = mint.mint
    monkeypatch.setattr(
        mint, "mint", lambda *a, **k: real_mint(*a, clock=lambda: 0.0, sleep=lambda s: None, **k)
    )
    secret, out = tmp_path / "totp", tmp_path / "manager.env"
    secret.write_text(_SEED, encoding="ascii")
    monkeypatch.setenv("ZAP_PW", "pw-not-printed")
    args = ["--target", TARGET, "--username", "zap-manager", "--password-env", "ZAP_PW"]
    assert mint.main([*args, "--totp-secret-file", str(secret), "--out", str(out)]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed == [
        f"::add-mask::{_MINTED['bearer']}",
        f"::add-mask::{_MINTED['csrf']}",
        "mint_sessions: zap-manager: session minted and verified",
    ]
    assert out.read_text(encoding="ascii") == (
        f"ZAP_AUTH_TOKEN={_MINTED['bearer']}\nZAP_CSRF_TOKEN={_MINTED['csrf']}\n"
    )
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert [made.sent[0][1] for made in connection.made] == [
        "/auth/login",
        "/auth/mfa/verify",
        "/me",
    ]


@pytest.mark.parametrize(("bearer", "csrf"), [("b\nZAP_X=1", "c"), ("b", ""), ("b", "c\r")])
def test_write_env_refuses_a_value_that_would_split_the_file(
    tmp_path: Path, bearer: str, csrf: str
) -> None:
    said: list[str] = []
    with pytest.raises(mint.MintFailed, match="not written"):
        mint.write_env(tmp_path / "x.env", bearer, csrf, announce=said.append)
    assert said == [] and not (tmp_path / "x.env").exists()


# --- check_admin_denials.py ---------------------------------------------------------------------

_LOG = "Job requestor started\n...\nJob requestor finished\n"


def test_the_log_must_show_the_requestor_ran_and_every_status_was_planned() -> None:
    assert denials.log_problems("manager", _LOG) == []
    assert denials.log_problems("manager", "Job requestor started\n") == [
        "manager: the denial requestor did not run to its end"
    ]
    mismatch = _LOG + "Job requestor warning: response code 200 does not match 403\n"
    assert denials.log_problems("viewer", mismatch) == ["viewer: response code 200 does not match"]
    zap_2_17 = (
        "Difference in response code values for message GET /admin Expected : 403 Received : 401"
    )
    twice = f"{_LOG}{zap_2_17}\nAutomation plan warnings:\n\t{zap_2_17}\n"  # ZAP repeats it
    assert denials.log_problems("manager", twice) == [f"manager: {zap_2_17}"]
    assert denials.log_problems("viewer", _LOG + "Automation plan failures:\n") == [
        "viewer: ZAP reported automation plan failures"
    ]


def _request(operation: str, recorded: bool = True) -> dict[str, Any]:
    return {"operation": operation, "correlation_id": str(uuid.uuid4()), "recorded": recorded}


def _row(
    request_id: str | None, outcome: str = "denied", action: str = "admin.area_entered"
) -> dict[str, Any]:
    return {"username": "u", "request_id": request_id, "action": action, "outcome": outcome}


def _step_up(item: dict[str, Any]) -> dict[str, Any]:
    return _row(item["correlation_id"], action="auth.step_up_required")


def test_planned_refusals_pass_with_their_records_and_the_rows_the_gate_ignores() -> None:
    by_id, step_up, silent = (
        _request("GET /admin/overview"),
        _request("POST /admin/recorder/purge"),
        _request("GET /admin/support-bundle/{job_id}"),
    )
    skipped = _request("PUT /admin/log-level", recorded=False)
    rows = [_row(by_id["correlation_id"]), _step_up(step_up)]
    rows.append(_row(str(uuid.uuid4()), outcome="success"))
    assert denials.audit_problems("manager", [by_id, step_up, silent, skipped], rows) == []


def test_csrf_refusals_fail_the_gate_and_answer_for_no_request() -> None:
    """The scan lost its CSRF pair: three unsafe requests, three nameless CSRF refusals."""
    planned = [_request(op) for op in ("POST /admin/a", "PUT /admin/b", "DELETE /admin/c")]
    rows = [_row(None, action=denials.CSRF_REFUSED) for _ in planned]
    problems = denials.audit_problems("manager", planned, rows)
    assert problems[0] == (
        "manager: 3 auth.csrf_refused record(s): the scan lost its CSRF pair, so those requests "
        "never reached RBAC"
    )
    assert problems[1:] == [
        f"manager: {op['operation']} was refused with no audit record" for op in planned
    ]


def test_a_csrf_refusal_that_names_the_request_does_not_answer_for_it_either() -> None:
    item = _request("POST /admin/a")
    problems = denials.audit_problems(
        "viewer", [item], [_row(item["correlation_id"], action=denials.CSRF_REFUSED)]
    )
    assert problems[-1] == "viewer: POST /admin/a was refused with no audit record"
    assert len(problems) == 2


@pytest.mark.parametrize(
    "action", ["auth.step_up_required", "rbac.denied", "admin.area_entered", "auth.login_failed"]
)
def test_a_denied_record_without_its_request_id_answers_for_none_and_fails_the_gate(
    action: str,
) -> None:
    """Since #3990 every refusal record names its request (the step-up and invites stand-ins are
    gone), so a nameless one is a regression, whatever its action."""
    item = _request("POST /admin/a")
    assert denials.audit_problems("viewer", [item], [_row(None, action=action)]) == [
        "viewer: 1 denied record(s) carry no request id: a refusal record lost its request's id "
        "(#3990)",
        "viewer: POST /admin/a was refused with no audit record",
    ]


def test_the_apis_log_of_a_csrf_refusal_fails_the_gate_whatever_its_renderer() -> None:
    assert denials.api_log_problems('{"event":"auth.startup"}\n') == []
    assert denials.api_log_problems('{"event":"auth_csrf_refused_total"}') == []
    logged = '{"event":"auth.csrf_refused","reason":"missing"}\n'
    throttled = "2026-10-20 [warning] auth.csrf_refused.unaudited reason=mismatch\n"
    assert denials.api_log_problems(logged + throttled) == [
        "the API logged 2 auth.csrf_refused event(s): the scan lost its CSRF pair"
    ]


def test_a_silent_refusal_fails_and_a_known_silent_one_that_is_recorded_now_fails_too() -> None:
    lost, silent = _request("GET /admin/overview"), _request("GET /admin/support-bundle/{job_id}")
    assert denials.audit_problems("viewer", [lost], [_row(None, outcome="success")]) == [
        "viewer: GET /admin/overview was refused with no audit record"
    ]
    assert denials.audit_problems("viewer", [silent], [_row(silent["correlation_id"])]) == [
        "viewer: GET /admin/support-bundle/{job_id} is recorded now: drop it from KNOWN_SILENT"
    ]


def _denial_dir(tmp_path: Path, log: str, rows: list[dict[str, Any]]) -> list[str]:
    request = _request("GET /admin/overview")
    tmp_path.mkdir(parents=True)
    (tmp_path / "manager-requests.json").write_text(json.dumps([request]), encoding="utf-8")
    (tmp_path / "manager-denials.log").write_text(log, encoding="utf-8")
    for row in rows:
        row["request_id"] = row["request_id"] or request["correlation_id"]
    (tmp_path / "audit-rows.json").write_text(json.dumps(rows), encoding="utf-8")
    return [
        "--dir",
        str(tmp_path),
        "--audit",
        str(tmp_path / "audit-rows.json"),
        "--user",
        "manager=u",
    ]


def test_check_main_passes_fails_and_refuses_unreadable_input(tmp_path: Path) -> None:
    assert denials.main(_denial_dir(tmp_path / "pass", _LOG, [_row(None)])) == 0
    assert denials.main(_denial_dir(tmp_path / "fail", _LOG, [])) == 1
    broken = _denial_dir(tmp_path / "broken", _LOG, [])
    (tmp_path / "broken" / "audit-rows.json").write_text("{not json", encoding="utf-8")
    assert denials.main(broken) == 2


def test_check_main_fails_on_a_csrf_refusal_in_the_apis_log(tmp_path: Path) -> None:
    args = _denial_dir(tmp_path / "csrf", _LOG, [_row(None)])
    api_log = tmp_path / "api.log"
    api_log.write_text('{"event":"auth.csrf_refused","reason":"mismatch"}\n', encoding="utf-8")
    assert denials.main([*args, "--api-log", str(api_log)]) == 1
    api_log.write_text('{"event":"ws authenticated"}\n', encoding="utf-8")
    assert denials.main([*args, "--api-log", str(api_log)]) == 0
    assert denials.main([*args, "--api-log", str(tmp_path / "missing.log")]) == 2


# --- check_liveness.py --------------------------------------------------------------------------

_REPORT = '{"site": []}'
_REQUESTOR = "Job requestor started\nJob requestor finished, time taken: 00:00:00\n"


def test_the_scan_gate_reads_zap_2_17s_wrong_status_once_though_zap_repeats_it() -> None:
    """ZAP 2.17 words a requestor's wrong status `Difference in response code values ...` and
    repeats it under `Automation plan warnings:`; neither is `Job requestor warning`. A scan that
    lost its session mid-way still writes its report, so the gate reads the line itself and names
    the loss, once per message (ZAP's own exit code is the other signal)."""
    lost = (
        f"Difference in response code values for message GET {TARGET}/me "
        "Expected : 200 Received : 401"
    )
    assert liveness.check(_REQUESTOR * 2, _REPORT) == []
    after = f"Job requestor started\n{lost}\nJob requestor finished, time taken: 00:00:00\n"
    log = f"{_REQUESTOR}Job activeScan finished\n{after}Automation plan warnings:\n\t{lost}\n"
    assert liveness.check(log, _REPORT) == [f"requestor failure: {lost}"]


def test_the_scan_gate_counts_every_requestor_of_the_plan(tmp_path: Path) -> None:
    """The refused-page probe is a third requestor. The gate counts the plan's own, so the probe and
    the first /me cannot stand in for a /me after the scan that never ran."""
    count = sum(job["type"] == "requestor" for job in TEMPLATE["jobs"])
    gate = next(
        step["run"] for name, step in _steps().items() if name.startswith("The scans stayed")
    )
    assert f"check_liveness.py --requestors {count} " in gate
    assert liveness.check(_REQUESTOR * count, _REPORT, count) == []
    ran = count - 1
    assert liveness.check(_REQUESTOR * ran, _REPORT, count) == [
        f"requestors (the /v1/auth/me liveness checks among them) ran {ran}/{count}, finished {ran}"
    ]
    log, report = tmp_path / "scan.log", tmp_path / "zap.json"
    log.write_text(_REQUESTOR * ran, encoding="utf-8")
    report.write_text(_REPORT, encoding="utf-8")
    assert liveness.main(["check_liveness.py", "--requestors", str(count), str(log), str(report)])
    assert liveness.main(["check_liveness.py", str(log), str(report)]) == 0  # the /me pair


# --- check_artefact_secrets.py ------------------------------------------------------------------

_BEARER, _CSRF = "bearer-" + "7" * 40, "csrf/" + "9" * 40  # not secrets: made for this test


def _session_dir(tmp_path: Path, text: str | None = None) -> Path:
    env_dir = tmp_path / "cv"
    env_dir.mkdir()
    body = text if text is not None else f"ZAP_AUTH_TOKEN={_BEARER}\nZAP_CSRF_TOKEN={_CSRF}\n"
    (env_dir / "manager-scan.env").write_text(body, encoding="utf-8")
    (env_dir / "manager.totp").write_text("short", encoding="ascii")  # not an env file
    return env_dir


@pytest.mark.parametrize(
    "written",
    [_BEARER, _CSRF, json.dumps(_CSRF)[1:-1].replace("/", "\\/"), "csrf%2F" + "9" * 40],
)
def test_a_session_value_in_any_artefact_file_fails_and_is_never_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], written: str
) -> None:
    env_dir, work = _session_dir(tmp_path), tmp_path / "zap-work"
    (work / "deep").mkdir(parents=True)
    (work / "manager-scan.log").write_text("clean\n", encoding="utf-8")
    (work / "deep" / "report.json").write_text(f'{{"evidence": "{written}"}}', encoding="utf-8")
    assert artefacts.main(["--env-dir", str(env_dir), str(work), str(tmp_path / "absent")]) == 1
    out = capsys.readouterr().out
    assert "report.json" in out and "manager-scan.env:ZAP_" in out
    assert _BEARER not in out and _CSRF not in out and "9" * 40 not in out


def test_clean_artefacts_pass_and_no_env_file_means_nothing_to_look_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_dir, work = _session_dir(tmp_path), tmp_path / "zap-work"
    work.mkdir()
    (work / "api.log").write_text('{"event":"ws authenticated"}\n', encoding="utf-8")
    assert artefacts.main(["--env-dir", str(env_dir), str(work)]) == 0
    assert "none of 2 session values" in capsys.readouterr().out
    assert artefacts.main(["--env-dir", str(tmp_path / "never-made"), str(work)]) == 0


@pytest.mark.parametrize(
    "text",
    ["ZAP_AUTH_TOKEN=\n", "ZAP_AUTH_TOKEN=short\n", "not a pair\n", "=" + "x" * 40 + "\n"],
)
def test_an_env_file_it_cannot_search_by_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    env_dir, work = _session_dir(tmp_path, text), tmp_path / "zap-work"
    work.mkdir()
    assert artefacts.main(["--env-dir", str(env_dir), str(work)]) == 2
    assert "cannot run" in capsys.readouterr().out


def test_comments_and_blank_lines_in_an_env_file_are_skipped(tmp_path: Path) -> None:
    env_dir = _session_dir(tmp_path, f"# made by mint_sessions.py\n\nZAP_AUTH_TOKEN={_BEARER}\n")
    assert artefacts.env_values(env_dir) == {"manager-scan.env:ZAP_AUTH_TOKEN": _BEARER}


# The run's other secrets: the generated passwords, pepper and keys (read from the environment) and
# the TOTP secret files `seed_fixture_user.py` writes. Stand-ins made for these tests.
_PASSWORD = 'pw/"quoted" ' + "7" * 20  # a slash, quotes and a space: each encoded form differs
_SEED_FILE = "TOTP" * 8  # 32 base32 characters, as the seed script writes


def _artefact_log(tmp_path: Path, text: str) -> Path:
    work = tmp_path / "zap-work"
    work.mkdir()
    (work / "api.log").write_text(text, encoding="utf-8")
    return work


@pytest.mark.parametrize(
    "written",
    [
        _PASSWORD,
        json.dumps(_PASSWORD)[1:-1],
        json.dumps(_PASSWORD)[1:-1].replace("/", "\\/"),
        quote(_PASSWORD, safe=""),
    ],
)
def test_a_run_password_in_the_artefact_fails_by_its_name_and_is_never_printed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    written: str,
) -> None:
    monkeypatch.setenv("ZAP_MANAGER_PASSWORD", _PASSWORD)
    work = _artefact_log(tmp_path, f'{{"detail": "{written}"}}\n')
    args = ["--env-dir", str(_session_dir(tmp_path)), "--env", "ZAP_MANAGER_PASSWORD", str(work)]
    assert artefacts.main(args) == 1
    shown = capsys.readouterr()
    assert "env:ZAP_MANAGER_PASSWORD" in shown.out and "api.log" in shown.out
    assert "7" * 20 not in shown.out + shown.err and "quoted" not in shown.out + shown.err


def test_a_totp_secret_in_the_artefact_fails_by_its_file_name_and_is_never_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_dir = _session_dir(tmp_path)
    (env_dir / "viewer.totp").write_text(f"{_SEED_FILE}\n", encoding="ascii")  # stripped
    work = _artefact_log(tmp_path, f"enrolled {_SEED_FILE}\n")
    args = ["--env-dir", str(env_dir), "--secret-file", str(env_dir / "v*.totp"), str(work)]
    assert artefacts.main(args) == 1
    shown = capsys.readouterr()
    assert "file:viewer.totp" in shown.out and "api.log" in shown.out
    assert _SEED_FILE not in shown.out + shown.err


def test_a_secret_file_name_two_directories_share_still_has_each_content_searched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, seed in (("a", "AAAA" * 8), ("b", "BBBB" * 8)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "x.totp").write_text(seed, encoding="ascii")
    work = _artefact_log(tmp_path, "AAAA" * 8 + " and " + "BBBB" * 8 + "\n")
    glob = str(tmp_path / "*" / "x.totp")
    args = ["--env-dir", str(tmp_path / "no"), "--secret-file", glob, str(work)]
    assert artefacts.main(args) == 1
    assert capsys.readouterr().out.count("api.log") == 2  # one finding for each file


def test_an_unset_or_empty_variable_and_a_glob_with_no_file_hold_nothing_to_search_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The check runs `if: always()`, also when an earlier step failed before it made a secret."""
    monkeypatch.delenv("ZAP_VIEWER_PASSWORD", raising=False)
    monkeypatch.setenv("ZAP_OWNER_PASSWORD", "")
    monkeypatch.setenv("ZAP_MANAGER_PASSWORD", _PASSWORD)
    env_dir = _session_dir(tmp_path, "")
    (env_dir / "empty.totp").write_text("\n", encoding="ascii")  # a seed that was never written
    work = _artefact_log(tmp_path, '{"event":"ws authenticated"}\n')
    args = ["--env-dir", str(env_dir), "--secret-file", str(env_dir / "empty*.totp")]
    args += ["--secret-file", str(tmp_path / "nowhere" / "*.totp")]
    for name in ("ZAP_VIEWER_PASSWORD", "ZAP_OWNER_PASSWORD", "ZAP_MANAGER_PASSWORD"):
        args += ["--env", name]
    assert artefacts.main([*args, str(work)]) == 0
    assert "none of 0 session values and 1 run secrets" in capsys.readouterr().out


def test_every_kind_of_needle_is_searched_together_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--env` is a prefix of `--env-dir`, so a parser that abbreviated it would swallow the
    session values' directory: both are counted here."""
    monkeypatch.setenv("ZAP_MANAGER_PASSWORD", _PASSWORD)
    env_dir = _session_dir(tmp_path)
    (env_dir / "viewer.totp").write_text(_SEED_FILE, encoding="ascii")
    work = _artefact_log(tmp_path, '{"event":"ws authenticated"}\n')
    args = ["--env-dir", str(env_dir), "--env", "ZAP_MANAGER_PASSWORD"]
    args += ["--secret-file", str(env_dir / "v*.totp"), str(work)]
    assert artefacts.main(args) == 0
    assert "none of 2 session values and 2 run secrets" in capsys.readouterr().out


@pytest.mark.parametrize("how", ["variable", "file"])
def test_a_run_secret_too_short_to_search_for_fails_closed_without_its_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    how: str,
) -> None:
    (tmp_path / "x.totp").write_text("t1ny-s3cr3t", encoding="ascii")
    monkeypatch.setenv("ZAP_MANAGER_PASSWORD", "t1ny-s3cr3t")
    option = {
        "variable": ["--env", "ZAP_MANAGER_PASSWORD"],
        "file": ["--secret-file", str(tmp_path / "x.totp")],
    }[how]
    work = _artefact_log(tmp_path, "clean\n")
    assert artefacts.main(["--env-dir", str(tmp_path / "no"), *option, str(work)]) == 2
    shown = capsys.readouterr()
    assert "cannot run" in shown.out and "too short" in shown.out
    assert "t1ny-s3cr3t" not in shown.out + shown.err


# --- the nightly workflow -----------------------------------------------------------------------


def test_the_workflow_runs_nightly_and_by_hand_never_on_a_pull_request() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow[True]  # YAML 1.1 reads the `on` key as True
    assert set(triggers) == {"schedule", "workflow_dispatch"}  # never pull_request (#3915 booted)
    assert triggers["schedule"] == [{"cron": "27 3 * * *"}]
    assert triggers["workflow_dispatch"] in (None, {})  # no input can move the target
    assert workflow["permissions"] == {"contents": "read"}


def _steps() -> dict[str, dict[str, Any]]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return {
        step.get("name", step.get("uses", "")): step
        for step in workflow["jobs"]["zap-admin"]["steps"]
    }


def test_nothing_is_uploaded_unless_no_session_value_reached_the_artefact() -> None:
    names = list(_steps())
    scrub = next(name for name in names if name.startswith("No session value"))
    upload = next(name for name in names if name.startswith("Upload the plans"))
    keep_log = next(name for name in names if name.startswith("Keep the API's log"))
    assert names.index(keep_log) < names.index(scrub) == names.index(upload) - 1
    steps = _steps()
    assert steps[scrub]["id"] == "scrub" and steps[scrub]["if"] == "always()"
    assert 'check_artefact_secrets.py --env-dir "$RUNNER_TEMP/cv"' in steps[scrub]["run"]
    assert steps[upload]["if"] == "${{ always() && steps.scrub.outcome == 'success' }}"


def test_the_artefact_check_searches_every_secret_the_run_makes_and_the_totp_seeds() -> None:
    steps = _steps()
    made = next(step["run"] for name, step in steps.items() if name.startswith("Make this run's"))
    (listed,) = re.findall(r"for name in ([A-Z_\s\\]+); do secret", made)
    generated = set(listed.replace("\\", " ").split())  # each one is in $GITHUB_ENV, masked
    scrub = next(step["run"] for name, step in steps.items() if name.startswith("No session value"))
    assert generated == {
        "POSTGRES_PASSWORD",
        "CV_AUTH_PEPPER",
        "CV_AUTH_TOTP_KEY_HEX",
        "CV_AUTH_RECOVERY_HMAC_KEY_HEX",
        "CV_AUTH_CSRF_KEY_HEX",
        "ZAP_OWNER_PASSWORD",
        "ZAP_MANAGER_PASSWORD",
        "ZAP_VIEWER_PASSWORD",
    }
    assert set(re.findall(r"--env (\w+)", scrub)) == generated  # none left out, none misspelt
    assert '--secret-file "$RUNNER_TEMP/cv/*.totp"' in scrub  # where seed_fixture_user.py writes
    assert '--secret-file "$RUNNER_TEMP/cv-lane/lane.key"' in scrub  # the audit lane key
    assert not re.search(r"\$\{?(" + "|".join(generated) + r")\b", scrub)  # names, never values


def test_each_phase_keeps_its_own_sessions_and_runs_both_roles_before_failing() -> None:
    steps = _steps()
    for phase, kind in (("Phase A", "denials"), ("Phase B", "scan")):
        run = next(step["run"] for name, step in steps.items() if name.startswith(phase))
        assert f'envfile="$RUNNER_TEMP/cv/$role-{kind}.env"' in run
        assert "|| rc=1" in run and run.rstrip().endswith('exit "$rc"')
    check = next(step["run"] for name, step in steps.items() if name.startswith("The scans stayed"))
    assert check.count("|| rc=1") == 2
    denial_gate = next(
        step["run"] for name, step in steps.items() if name.startswith("Every refusal")
    )
    assert '--api-log "$RUNNER_TEMP/cv/api.log"' in denial_gate


def test_the_workflow_runs_uv_frozen_and_stops_waiting_for_an_api_that_exited() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.findall(r"uv run(?! --frozen)", text) == []
    start = next(step["run"] for name, step in _steps().items() if name.startswith("Start the API"))
    assert "api=$!" in start and 'kill -0 "$api"' in start
    # an API still alive but silent has no exit code: the message said `(exit 0)` for it once
    assert 'state="still running, not answering"' in start and 'state="exit ${code}"' in start


def test_the_workflow_pins_every_action_and_image_and_uses_no_repository_secret() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    uses = re.findall(r"uses:\s*(\S+)", text)
    assert uses and all(
        use.startswith("./.github/workflows/")
        or re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", use)
        for use in uses
    )
    assert re.search(r"zaproxy:[\d.]+@sha256:[0-9a-f]{64}", text)
    assert re.findall(r"\bsecrets\.\w+", text) == []  # synthetic credentials only, made per run
    assert re.search(r"ZAP_TARGET: http://127\.0\.0\.1:\d+\n", text)


_FAKE_DOCKER = """\
import os
import re
import sys
from pathlib import Path

role = re.search(r"zap-(\\w+)-scan", " ".join(sys.argv[2:]))
with open(os.environ["DOCKER_CALLS"], "a", encoding="utf-8") as calls:
    calls.write(f"{sys.argv[1]} {role.group(1) if role else '?'}\\n")
if sys.argv[1] in os.environ["DOCKER_FAILS"].split():
    sys.exit(1)
if sys.argv[1] == "cp":
    Path(sys.argv[3]).write_text("zap.log\\n", encoding="utf-8")
"""
_FAKE_MINT = """\
import os
import sys
from pathlib import Path

if os.environ["MINT_FAILS"]:
    sys.exit(1)
Path(sys.argv[sys.argv.index("--out") + 1]).write_text("ZAP_AUTH_TOKEN=t\\n", encoding="utf-8")
"""
_BOTH = ["run manager", "cp manager", "rm manager", "run viewer", "cp viewer", "rm viewer"]


def _phase_b(tmp_path: Path, docker_fails: str, mint_fails: str) -> tuple[int, list[str]]:
    """Run Phase B's script as the runner does (`bash -e`) in tmp_path, with a stand-in `docker`
    and mint script and no network: its exit code and the docker calls, `<command> <role>` each."""
    if not shutil.which("bash"):  # CI must run these proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    bin_dir, zap = tmp_path / "bin", tmp_path / "security/zap"
    for folder in (bin_dir, zap, tmp_path / "zap-work", tmp_path / "cv"):
        folder.mkdir(parents=True)
    (bin_dir / "docker").write_text(f"#!{sys.executable}\n{_FAKE_DOCKER}", encoding="utf-8")
    (bin_dir / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    for tool in ("docker", "python3"):
        (bin_dir / tool).chmod(0o755)
    (zap / "mint_sessions.py").write_text(_FAKE_MINT, encoding="utf-8")
    calls = tmp_path / "calls"
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "RUNNER_TEMP": str(tmp_path),
        "WORK": "zap-work",
        "ZAP_TARGET": TARGET,
        "ZAP_IMAGE": "zap",
        "ZAP_MANAGER_USER": "manager-user",
        "ZAP_VIEWER_USER": "viewer-user",
        "DOCKER_CALLS": str(calls),
        "DOCKER_FAILS": docker_fails,
        "MINT_FAILS": mint_fails,
    }
    run = _steps()["Phase B, the passive and active scan, as each role"]["run"]
    proc = subprocess.run(
        ["bash", "-e", "-c", run],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc.returncode, calls.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    ("docker_fails", "mint_fails", "code", "calls"),
    [
        ("", "", 0, _BOTH),
        ("run", "", 1, _BOTH),  # a failed scan's log is still copied and its container removed
        ("cp", "", 1, _BOTH),  # a log that cannot be copied fails the step; the container goes
        ("rm", "", 0, _BOTH),  # a removal that fails is not the scan's failure
        ("", "1", 1, [call for call in _BOTH if not call.startswith("run")]),  # no session, no scan
    ],
)
def test_the_scan_copies_zaps_log_out_then_removes_its_container_for_both_roles(
    tmp_path: Path, docker_fails: str, mint_fails: str, code: int, calls: list[str]
) -> None:
    """ZAP's `zap.log` (its errors and insights, #3996's R2-S5) is copied out of the container
    before it is removed, into the work directory the scrub reads, whatever the scan did; both
    roles run before the step fails."""
    assert "--rm" not in _steps()["Phase B, the passive and active scan, as each role"]["run"]
    assert _phase_b(tmp_path, docker_fails, mint_fails) == (code, calls)
    copied = sorted(path.name for path in (tmp_path / "zap-work").glob("*-zap.log"))
    assert copied == (
        [] if docker_fails == "cp" else ["manager-scan-zap.log", "viewer-scan-zap.log"]
    )


def test_zap_makes_no_unsolicited_request_and_no_scan_container_outlives_the_job() -> None:
    """`-silent`: no update check or call-home leaves the runner. A scan container that
    `docker rm` could not remove, with ZAP's session store in it, goes at tear-down."""
    runs = re.findall(r"zap\.sh -cmd[^\n]*", WORKFLOW.read_text(encoding="utf-8"))
    assert len(runs) == 2 and all(" -silent " in run for run in runs)
    teardown = _steps()["Tear down"]
    assert teardown["if"] == "always()"
    assert "docker rm -f zap-manager-scan zap-viewer-scan" in teardown["run"]


def test_the_scrub_reads_every_path_the_upload_sends() -> None:
    """Both phases write into $WORK and ZAP's reports into zap-reports: the scrub reads exactly the
    paths the upload sends, so nothing reaches the artefact unread."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = _steps()
    scrub = next(step["run"] for name, step in steps.items() if name.startswith("No session value"))
    upload = next(step for name, step in steps.items() if name.startswith("Upload the plans"))
    assert scrub.split()[-2:] == ['"$WORK"', "zap-reports"]
    work = workflow["jobs"]["zap-admin"]["env"]["WORK"]
    assert upload["with"]["path"].split() == [f"{work}/", "zap-reports/"]


def test_the_session_reaches_the_admin_surface_and_is_refused_before_the_scan() -> None:
    """403, not 401: the role's session is live on the admin surface and RBAC refuses it."""
    jobs = TEMPLATE["jobs"]
    kinds = [job["type"] for job in jobs]
    (probe,) = [job for job in jobs if job.get("name") == "admin-probe-after-config"]
    assert kinds.index("passiveScan-config") < jobs.index(probe) < kinds.index("openapi")
    assert probe["requests"] == [
        {"url": "${ZAP_TARGET}/admin/overview", "method": "GET", "responseCode": 403}
    ]
    row = MATRIX["operations"]["GET /admin/overview"]["outcomes"]
    assert {row["viewer"], row["manager_without_grant"]} == {"403"}
