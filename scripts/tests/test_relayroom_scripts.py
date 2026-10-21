"""Unit tests for the RelayRoom client scripts: the doctor and the credential entry.

Everything here is synthetic: FAKE connect codes, tokens and URLs, written into pytest temp
directories next to a throw-away ``git init`` repository so ``check-ignore`` / ``ls-files``
behave as they do in the real checkout. No network, and nothing reads a real
``.claude/settings.local.json`` or any ``.claude/relayroom/`` file.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCRIPTS_DIR.parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


doctor = _load("relayroom_main_doctor", "relayroom-main-doctor.py")
creds = _load("relayroom_enter_credentials", "relayroom-enter-credentials.py")

FAKE_CODE = "FAKECODE123"


@pytest.fixture(autouse=True)
def _never_touch_the_real_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`creds.TARGET` resolves at import to the checkout's live settings.local.json; point it at a
    non-existent tmp file for every test so a test that forgets the `target` fixture cannot write there."""
    monkeypatch.setattr(creds, "TARGET", tmp_path / "unset" / "settings.local.json")
FAKE_TOKEN = "FAKETOKENxyz"
# The hub origin is private configuration, never a committed literal: every test supplies a
# synthetic one through CANDLEVIEWER_RELAYROOM_ORIGIN (see the autouse fixture below).
HUB_HOST = "hub.example.test"
HUB = f"https://{HUB_HOST}"
ORIGIN_ENV = "CANDLEVIEWER_RELAYROOM_ORIGIN"
FAKE_URL = f"{HUB}/mcp/{FAKE_CODE}?part=main-orchestrator"
FAKE_LABEL = "cv-test-machine-l01"
FAKE_UUID = "11111111-2222-4333-8444-555555555555"
# What must never reach stdout/stderr: the fake secrets, any secret-bearing URL path and the origin.
LEAKS = (FAKE_CODE, FAKE_TOKEN, "/mcp/", HUB_HOST)

ENV_URL = "CANDLEVIEWER_RELAYROOM_MCP_URL"
ENV_KEY = "CANDLEVIEWER_RELAYROOM_API_KEY"
ENV_LABEL = "CANDLEVIEWER_RELAYROOM_MACHINE_LABEL"

MCP_TEMPLATE = {
    "mcpServers": {
        "candleviewer-relayroom": {
            "type": "http",
            "url": "${" + ENV_URL + "}",
            "headers": {
                "Authorization": "Bearer ${" + ENV_KEY + "}",
                "X-Machine-Label": "${" + ENV_LABEL + "}",
            },
        }
    }
}
GITIGNORE = ".claude/relayroom/\n.claude/settings.local.json\n"
DEFAULT = object()  # "use the valid default" (None / [] / "" are legitimate raw values)


@pytest.fixture(autouse=True)
def hermetic_git(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Keep the developer's git setup out of the git-backed checks.

    A global ignore file (Claude Code adds `.claude/settings.local.json` to one) or a hook's
    GIT_DIR would otherwise change what `check-ignore` / `ls-files` report in the synthetic repos.
    """
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg")))


@pytest.fixture(autouse=True)
def hub_origin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test against the synthetic hub; the unset / descriptor tests delete the variable."""
    monkeypatch.setenv(ORIGIN_ENV, HUB)


@pytest.fixture
def cfg_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    # A neutral directory name: the doctor refuses an identity whose text contains words like
    # "token" or "connect", and tmp_path embeds the test name.
    return tmp_path_factory.mktemp("cfgroot")


def git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)


def valid_env() -> dict[str, str]:
    return {ENV_URL: FAKE_URL, ENV_KEY: FAKE_TOKEN, ENV_LABEL: FAKE_LABEL}


def valid_identity(root: Path) -> dict[str, object]:
    return {
        "project": "candleviewer",
        "part": "main-orchestrator",
        "persona": "Atlas",
        "mcpServer": "candleviewer-relayroom",
        "expectedIsMain": True,
        "clientInstanceId": FAKE_UUID,
        "configRoot": str(root.resolve()),
        "machineLabel": FAKE_LABEL,
    }


def write(path: Path, value: object) -> None:
    """Write `value` as JSON; a `str` is written verbatim (to model malformed files)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, indent=2)
    path.write_text(text, encoding="utf-8")


def make_root(
    root: Path,
    *,
    mcp: object = DEFAULT,
    ident: object = DEFAULT,
    settings: object = DEFAULT,
    runs: bool = True,
    gitignore: str | None = GITIGNORE,
    init_git: bool = True,
) -> Path:
    """Build a synthetic RelayRoom config root: git repo + template + private files.

    Pass a value for `mcp` / `ident` / `settings` to replace the valid default, or `None`
    to leave that file out. `gitignore=None` writes no .gitignore at all.
    """
    if init_git:
        subprocess.run(["git", "init", "-q", str(root)], capture_output=True, check=True)
    if gitignore is not None:
        (root / ".gitignore").write_text(gitignore, encoding="utf-8")
    if mcp is not None:
        write(root / ".mcp.json", MCP_TEMPLATE if mcp is DEFAULT else mcp)
    if ident is not None:
        value = valid_identity(root) if ident is DEFAULT else ident
        write(root / ".claude" / "relayroom" / "identity.local.json", value)
    if settings is not None:
        value = {"env": valid_env()} if settings is DEFAULT else settings
        write(root / ".claude" / "settings.local.json", value)
    if runs:
        write(root / ".claude" / "relayroom" / "runs" / "x.json", {"runLabel": "x"})
    return root


class Outcome:
    def __init__(self, code: int, out: str, err: str) -> None:
        self.code, self.out, self.err = code, out, err

    @property
    def lines(self) -> list[str]:
        return [ln for ln in self.out.splitlines() if ln.strip()]


def run_doctor(root: Path, capsys: pytest.CaptureFixture[str]) -> Outcome:
    code = doctor.main(["--config-root", str(root)])
    captured = capsys.readouterr()
    return Outcome(code, captured.out, captured.err)


def assert_no_leak(outcome: Outcome) -> None:
    for needle in LEAKS:
        assert needle not in outcome.out, f"stdout leaked {needle!r}"
        assert needle not in outcome.err, f"stderr leaked {needle!r}"


def assert_allowlisted(outcome: Outcome) -> None:
    """Every printed line is a PASS/FAIL result or the summary line (blank lines aside)."""
    for line in outcome.lines:
        assert line.startswith(("PASS", "FAIL", "relayroom-main-doctor:")), line


def assert_fail(outcome: Outcome, expected: str) -> None:
    assert outcome.code == 1, outcome.out
    assert f"FAIL  {expected}" in outcome.out
    assert "READY" not in outcome.out
    assert_allowlisted(outcome)
    assert_no_leak(outcome)


# =============================== doctor: valid root =================================


def test_doctor_valid_root_reports_ready_and_exits_zero(cfg_root, capsys):
    outcome = run_doctor(make_root(cfg_root), capsys)

    assert outcome.code == 0, outcome.out
    assert "relayroom-main-doctor: READY" in outcome.out
    assert "FAIL" not in outcome.out
    assert_allowlisted(outcome)


def test_doctor_valid_root_never_prints_secrets(cfg_root, capsys):
    outcome = run_doctor(make_root(cfg_root), capsys)

    assert outcome.code == 0
    assert_no_leak(outcome)
    assert_allowlisted(outcome)


def test_doctor_second_run_in_same_process_does_not_accumulate_results(cfg_root, capsys):
    root = make_root(cfg_root)
    first = run_doctor(root, capsys)
    second = run_doctor(root, capsys)

    assert first.lines == second.lines
    assert second.code == 0


def test_doctor_reads_config_root_from_argv_when_not_given(cfg_root, capsys, monkeypatch):
    root = make_root(cfg_root)
    monkeypatch.setattr(sys, "argv", ["relayroom-main-doctor.py", "--config-root", str(root)])

    assert doctor.main() == 0
    assert "READY" in capsys.readouterr().out


def test_doctor_committed_mcp_template_satisfies_the_template_check(cfg_root, capsys):
    # The tracked, secret-free template must stay in step with what the doctor expects.
    template_path = REPO_ROOT / "docs/ops/relayroom-mcp.template.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    outcome = run_doctor(make_root(cfg_root, mcp=template), capsys)

    assert outcome.code == 0, outcome.out


# ============================ doctor: env / URL failures ============================

URL_NO_QUERY = FAKE_URL.split("?")[0]
ENV_FAIL_CASES = [
    pytest.param(
        {ENV_URL: f"{HUB}/mcp/<CODE>?part=main-orchestrator"},
        f"env.{ENV_URL} has no placeholder",
        id="placeholder-angle-brackets-in-url",
    ),
    pytest.param(
        {ENV_KEY: "${" + ENV_KEY + "}"},
        f"env.{ENV_KEY} has no placeholder",
        id="placeholder-unexpanded-env-reference",
    ),
    pytest.param(
        {ENV_KEY: "FRESH_TOKEN_GOES_HERE"},
        f"env.{ENV_KEY} has no placeholder",
        id="placeholder-fresh-marker",
    ),
    pytest.param(
        {ENV_LABEL: "changeme"}, f"env.{ENV_LABEL} has no placeholder", id="placeholder-changeme"
    ),
    pytest.param(
        {ENV_KEY: FAKE_TOKEN + " "}, f"env.{ENV_KEY} has no whitespace", id="whitespace-trailing"
    ),
    pytest.param(
        {ENV_KEY: "\t" + FAKE_TOKEN}, f"env.{ENV_KEY} has no whitespace", id="whitespace-leading"
    ),
    pytest.param(
        {ENV_KEY: "FAKE TOKENxyz"}, f"env.{ENV_KEY} has no whitespace", id="whitespace-inside"
    ),
    pytest.param(
        {ENV_URL: FAKE_URL + "\n"}, f"env.{ENV_URL} has no whitespace", id="whitespace-newline-url"
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace(HUB_HOST, "other.example.org")},
        "MCP URL origin is the hub (https, exact host)",
        id="origin-wrong-host",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace("https:", "http:")},
        "MCP URL origin is the hub (https, exact host)",
        id="origin-scheme-downgrade",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace(HUB_HOST, HUB_HOST + ":8443")},
        "MCP URL origin is the hub (https, exact host)",
        id="origin-extra-port",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace(HUB_HOST, HUB_HOST + ".evil.example")},
        "MCP URL origin is the hub (https, exact host)",
        id="origin-suffix-attack",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace(HUB_HOST, "evil." + HUB_HOST)},
        "MCP URL origin is the hub (https, exact host)",
        id="origin-prefix-attack",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace(HUB_HOST, HUB_HOST.replace(".", "-", 1))},
        "MCP URL origin is the hub (https, exact host)",
        id="origin-lookalike-separator",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace("//" + HUB_HOST, "//user:pw@" + HUB_HOST)},
        "MCP URL origin is the hub (https, exact host)",
        id="origin-userinfo",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace("part=main-orchestrator", "part=worker-1")},
        "MCP URL query is exactly part=main-orchestrator",
        id="part-mismatch",
    ),
    pytest.param(
        {ENV_URL: URL_NO_QUERY},
        "MCP URL query is exactly part=main-orchestrator",
        id="part-missing",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL + "&extra=1"},
        "MCP URL query is exactly part=main-orchestrator",
        id="part-extra-query",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace(FAKE_CODE, "FAKE%25CODE123")},
        "MCP URL connect code is not double-encoded",
        id="code-double-encoded",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace("/mcp/", "/other/")},
        "MCP URL path is the MCP prefix plus one connect-code segment",
        id="path-wrong-prefix",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace(FAKE_CODE, "FAKE/CODE123")},
        "MCP URL path is the MCP prefix plus one connect-code segment",
        id="path-extra-segment",
    ),
    pytest.param(
        {ENV_LABEL: "some-other-machine"},
        "env machine label == identity.machineLabel",
        id="label-differs-from-identity",
    ),
    pytest.param({ENV_KEY: ""}, f"env.{ENV_KEY} present", id="token-empty"),
    pytest.param({ENV_KEY: 12345}, f"env.{ENV_KEY} present", id="token-not-a-string"),
]


@pytest.mark.parametrize(("override", "expected"), ENV_FAIL_CASES)
def test_doctor_env_value_problem_fails_with_exit_one(cfg_root, capsys, override, expected):
    env = {**valid_env(), **override}
    outcome = run_doctor(make_root(cfg_root, settings={"env": env}), capsys)

    assert_fail(outcome, expected)


@pytest.mark.parametrize("key", [ENV_URL, ENV_KEY, ENV_LABEL])
def test_doctor_missing_env_key_reports_pending_activation(cfg_root, capsys, key):
    env = valid_env()
    del env[key]
    outcome = run_doctor(make_root(cfg_root, settings={"env": env}), capsys)

    assert_fail(outcome, f"env.{key} present — pending (activation blocked)")


# ================= doctor: hub origin (private configuration, fail closed) ==================

NOT_CONFIGURED = (
    "hub origin resolved — not configured — "
    f"set {ORIGIN_ENV} or `hubOrigin` in the private descriptor"
)
INVALID_IN_ENV = (
    f"hub origin resolved — invalid in env {ORIGIN_ENV} — "
    "expected https://host[:port] and nothing else"
)
INVALID_IN_DESCRIPTOR = (
    "hub origin resolved — invalid in identity.hubOrigin — "
    "expected https://host[:port] and nothing else"
)
URL_ORIGIN_CHECK = "MCP URL origin is the hub (https, exact host)"
OTHER_HUB = "https://other.example.test"
# Values that are not a bare `https://host[:port]`; the code and token are fake secrets that must
# never be echoed back, and the last two are lookalikes that would send the code to another host.
INVALID_ORIGINS = [
    pytest.param("http://" + HUB_HOST, id="http-scheme"),
    pytest.param(HUB_HOST, id="no-scheme"),
    pytest.param(f"{HUB}/mcp/{FAKE_CODE}", id="path-with-connect-code"),
    pytest.param(f"{HUB}/path", id="path"),
    pytest.param(f"{HUB}?part=x", id="query"),
    pytest.param(f"{HUB}#frag", id="fragment"),
    pytest.param("https://user:" + FAKE_TOKEN + "@" + HUB_HOST, id="userinfo-with-token"),
    pytest.param(f"{HUB}@evil.example", id="userinfo-lookalike"),
    pytest.param(f"https://evil.example\\@{HUB_HOST}", id="backslash-lookalike"),
    pytest.param("https://", id="empty-host"),
    pytest.param("https://exa mple.test", id="space-in-host"),
    pytest.param("https://*.example.test", id="wildcard-host"),
    pytest.param(f"{HUB}:", id="empty-port"),
    pytest.param(f"{HUB}:123456", id="port-too-long"),
    pytest.param(f"{HUB}//", id="double-trailing-slash"),
    pytest.param("*", id="any-origin"),
]


def test_doctor_without_a_hub_origin_fails_closed(cfg_root, capsys, monkeypatch):
    monkeypatch.delenv(ORIGIN_ENV)
    outcome = run_doctor(make_root(cfg_root), capsys)  # the descriptor has no hubOrigin key

    assert_fail(outcome, NOT_CONFIGURED)
    # No origin means no match, never "any origin": the stored URL fails its origin check too.
    assert f"FAIL  {URL_ORIGIN_CHECK}" in outcome.out


def test_doctor_without_a_hub_origin_or_a_descriptor_fails_closed(cfg_root, capsys, monkeypatch):
    monkeypatch.delenv(ORIGIN_ENV)

    outcome = run_doctor(make_root(cfg_root, ident=None), capsys)

    assert_fail(outcome, NOT_CONFIGURED)
    assert f"FAIL  {URL_ORIGIN_CHECK}" in outcome.out


def test_doctor_reads_the_hub_origin_from_the_descriptor_when_the_env_is_absent(
    cfg_root, capsys, monkeypatch
):
    monkeypatch.delenv(ORIGIN_ENV)
    ident = {**valid_identity(cfg_root), "hubOrigin": HUB}

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert outcome.code == 0, outcome.out
    assert "PASS  hub origin resolved — via identity.hubOrigin" in outcome.out
    assert_allowlisted(outcome)
    assert_no_leak(outcome)  # only the source is reported, never the origin itself


@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
def test_doctor_blank_env_origin_counts_as_unset(cfg_root, capsys, monkeypatch, blank):
    monkeypatch.setenv(ORIGIN_ENV, blank)
    ident = {**valid_identity(cfg_root), "hubOrigin": HUB}

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert outcome.code == 0, outcome.out
    assert "PASS  hub origin resolved — via identity.hubOrigin" in outcome.out


def test_doctor_env_origin_takes_precedence_over_the_descriptor(cfg_root, capsys):
    ident = {**valid_identity(cfg_root), "hubOrigin": OTHER_HUB}  # the env (HUB) matches the URL

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert outcome.code == 0, outcome.out
    assert f"PASS  hub origin resolved — via env {ORIGIN_ENV}" in outcome.out


def test_doctor_env_origin_wins_even_when_it_disagrees_with_the_stored_url(
    cfg_root, capsys, monkeypatch
):
    monkeypatch.setenv(ORIGIN_ENV, OTHER_HUB)
    ident = {**valid_identity(cfg_root), "hubOrigin": HUB}  # would match, but the env wins

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert_fail(outcome, URL_ORIGIN_CHECK)


@pytest.mark.parametrize("bad", INVALID_ORIGINS)
def test_doctor_invalid_env_origin_fails_without_echoing_it(cfg_root, capsys, monkeypatch, bad):
    monkeypatch.setenv(ORIGIN_ENV, bad)

    outcome = run_doctor(make_root(cfg_root), capsys)

    assert_fail(outcome, INVALID_IN_ENV)
    assert f"FAIL  {URL_ORIGIN_CHECK}" in outcome.out


def test_doctor_invalid_env_origin_is_not_rescued_by_a_valid_descriptor_origin(
    cfg_root, capsys, monkeypatch
):
    monkeypatch.setenv(ORIGIN_ENV, "http://" + HUB_HOST)
    ident = {**valid_identity(cfg_root), "hubOrigin": HUB}  # valid, and the stored URL matches it

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert_fail(outcome, INVALID_IN_ENV)  # no silent fall back to the descriptor
    assert f"FAIL  {URL_ORIGIN_CHECK}" in outcome.out


@pytest.mark.parametrize("bad", INVALID_ORIGINS)
def test_doctor_invalid_descriptor_origin_fails_without_echoing_it(
    cfg_root, capsys, monkeypatch, bad
):
    monkeypatch.delenv(ORIGIN_ENV)
    ident = {**valid_identity(cfg_root), "hubOrigin": bad}

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert_fail(outcome, INVALID_IN_DESCRIPTOR)
    assert f"FAIL  {URL_ORIGIN_CHECK}" in outcome.out


@pytest.mark.parametrize(
    "bad",
    [7, True, ["https://x.example.test"], {"url": "x"}],
    ids=["number", "bool", "list", "object"],
)
def test_doctor_non_string_descriptor_origin_fails_closed(cfg_root, capsys, monkeypatch, bad):
    monkeypatch.delenv(ORIGIN_ENV)
    ident = {**valid_identity(cfg_root), "hubOrigin": bad}

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert_fail(outcome, INVALID_IN_DESCRIPTOR)


def test_doctor_origin_comparison_includes_the_port(cfg_root, capsys, monkeypatch):
    monkeypatch.setenv(ORIGIN_ENV, f"{HUB}:8443")

    # The stored URL has no port: same host, different origin.
    assert_fail(run_doctor(make_root(cfg_root), capsys), URL_ORIGIN_CHECK)


def test_doctor_origin_with_a_port_matches_a_url_with_that_port(cfg_root, capsys, monkeypatch):
    monkeypatch.setenv(ORIGIN_ENV, f"{HUB}:8443")
    env = {**valid_env(), ENV_URL: FAKE_URL.replace(HUB_HOST, HUB_HOST + ":8443")}

    outcome = run_doctor(make_root(cfg_root, settings={"env": env}), capsys)

    assert outcome.code == 0, outcome.out


def test_doctor_descriptor_origin_is_not_mistaken_for_a_secret_by_its_hostname(
    cfg_root, capsys, monkeypatch
):
    # The identity check rejects the words "token" / "connect"; a validated origin is exempt.
    monkeypatch.delenv(ORIGIN_ENV)
    host = "connect.token.example.test"
    ident = {**valid_identity(cfg_root), "hubOrigin": f"https://{host}"}
    env = {**valid_env(), ENV_URL: FAKE_URL.replace(HUB_HOST, host)}

    outcome = run_doctor(make_root(cfg_root, ident=ident, settings={"env": env}), capsys)

    assert outcome.code == 0, outcome.out
    assert "FAIL" not in outcome.out


# The descriptor's hubOrigin is exempt from the identity secret scan only when it is a valid origin,
# and a present hubOrigin that is not one fails the doctor whichever of the env var and the
# descriptor wins in hub_origin().
SCAN = "identity carries no token/url/connect-code"
ORIGIN_VALID = "identity.hubOrigin is a bare https origin"
ORIGIN_PRESENT_INVALID = f"{ORIGIN_VALID} — descriptor hubOrigin present but invalid"
SCAN_WORDS = ("bearer", "/mcp/", "token", "connect")
SECRET_BEARING_ORIGINS = [
    pytest.param(FAKE_URL, id="mcp-url-with-connect-code"),
    pytest.param("Bearer " + FAKE_TOKEN, id="bearer-token"),
    pytest.param("token=" + FAKE_TOKEN, id="token-assignment"),
]
# Invalid values that carry none of the words the scan looks for: only the origin check can catch them.
KEYWORD_FREE_INVALID_ORIGINS = [
    pytest.param(FAKE_CODE, id="raw-code"),
    pytest.param("https://user:" + "pw1234" + "@" + HUB_HOST, id="userinfo-password"),
    pytest.param("http://" + HUB_HOST, id="http-scheme"),
]


@pytest.mark.parametrize("secret", SECRET_BEARING_ORIGINS)
def test_doctor_secret_in_the_descriptor_origin_fails_even_when_the_env_origin_wins(
    cfg_root, capsys, secret
):
    ident = {**valid_identity(cfg_root), "hubOrigin": secret}  # the env (HUB) is set and wins

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert_fail(outcome, SCAN)  # exit 1, no READY, allowlisted lines, the value is not echoed
    # Two value-free FAIL lines: the scan catches the secret, the origin check the invalid value.
    assert [ln for ln in outcome.lines if ln.startswith("FAIL")] == [
        f"FAIL  {SCAN}",
        f"FAIL  {ORIGIN_PRESENT_INVALID}",
    ]
    assert f"PASS  hub origin resolved — via env {ORIGIN_ENV}" in outcome.out


@pytest.mark.parametrize("env_set", [True, False], ids=["env-set", "env-unset"])
@pytest.mark.parametrize(
    "host", [HUB_HOST, "connect.token.example.test"], ids=["plain-host", "scan-word-host"]
)
def test_doctor_valid_descriptor_origin_passes_the_scan_whichever_source_wins(
    cfg_root, capsys, monkeypatch, env_set, host
):
    origin = f"https://{host}"
    if env_set:
        monkeypatch.setenv(ORIGIN_ENV, origin)
    else:
        monkeypatch.delenv(ORIGIN_ENV)
    ident = {**valid_identity(cfg_root), "hubOrigin": origin}
    env = {**valid_env(), ENV_URL: FAKE_URL.replace(HUB_HOST, host)}

    outcome = run_doctor(make_root(cfg_root, ident=ident, settings={"env": env}), capsys)

    source = f"env {ORIGIN_ENV}" if env_set else "identity.hubOrigin"
    assert outcome.code == 0, outcome.out
    assert f"PASS  {SCAN}" in outcome.out
    assert f"PASS  {ORIGIN_VALID}" in outcome.out
    assert f"PASS  hub origin resolved — via {source}" in outcome.out
    assert_allowlisted(outcome)
    assert_no_leak(outcome)


def test_doctor_descriptor_origin_is_the_one_the_stored_url_is_compared_with(
    cfg_root, capsys, monkeypatch
):
    monkeypatch.delenv(ORIGIN_ENV)
    ident = {**valid_identity(cfg_root), "hubOrigin": OTHER_HUB}  # valid, but not the URL's origin

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert_fail(outcome, URL_ORIGIN_CHECK)
    assert f"PASS  {SCAN}" in outcome.out
    assert "PASS  hub origin resolved — via identity.hubOrigin" in outcome.out


def test_keyword_free_invalid_origins_really_carry_no_scan_word():
    for param in KEYWORD_FREE_INVALID_ORIGINS:
        assert not any(word in param.values[0].lower() for word in SCAN_WORDS), param.id


@pytest.mark.parametrize("bad", KEYWORD_FREE_INVALID_ORIGINS)
def test_doctor_keyword_free_invalid_descriptor_origin_fails_when_the_env_origin_wins(
    cfg_root, capsys, bad
):
    ident = {**valid_identity(cfg_root), "hubOrigin": bad}  # the env (HUB) is set and wins

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert_fail(outcome, ORIGIN_PRESENT_INVALID)  # not READY, though the scan sees nothing wrong
    assert [ln for ln in outcome.lines if ln.startswith("FAIL")] == [
        f"FAIL  {ORIGIN_PRESENT_INVALID}"
    ]
    assert f"PASS  {SCAN}" in outcome.out
    assert f"PASS  hub origin resolved — via env {ORIGIN_ENV}" in outcome.out


@pytest.mark.parametrize("bad", KEYWORD_FREE_INVALID_ORIGINS)
def test_doctor_keyword_free_invalid_descriptor_origin_fails_when_the_env_is_unset(
    cfg_root, capsys, monkeypatch, bad
):
    monkeypatch.delenv(ORIGIN_ENV)
    ident = {**valid_identity(cfg_root), "hubOrigin": bad}

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert_fail(outcome, ORIGIN_PRESENT_INVALID)
    # The descriptor is the source here, so the hub origin itself is unresolved too.
    assert f"FAIL  {INVALID_IN_DESCRIPTOR}" in outcome.out


@pytest.mark.parametrize("blank", [None, "", "  "], ids=["null", "empty", "spaces"])
def test_doctor_blank_descriptor_origin_counts_as_absent(cfg_root, capsys, blank):
    ident = {**valid_identity(cfg_root), "hubOrigin": blank}  # the env (HUB) is set and wins

    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert outcome.code == 0, outcome.out
    assert "identity.hubOrigin" not in outcome.out  # no origin line at all, as in hub_origin()


# ============================ doctor: identity failures =============================

IDENTITY_FAIL_CASES = [
    pytest.param({"part": "worker-1"}, "identity.part == main-orchestrator", id="part"),
    pytest.param({"project": "other-project"}, "identity.project == candleviewer", id="project"),
    pytest.param({"persona": "Mallory"}, "identity.persona == Atlas", id="persona"),
    pytest.param(
        {"mcpServer": "other-alias"}, "identity.mcpServer == candleviewer-relayroom", id="alias"
    ),
    pytest.param({"expectedIsMain": False}, "identity.expectedIsMain is true", id="not-main"),
    pytest.param({"expectedIsMain": "true"}, "identity.expectedIsMain is true", id="main-string"),
    pytest.param(
        {"clientInstanceId": "not-a-uuid"}, "identity.clientInstanceId is a UUID", id="bad-uuid"
    ),
    pytest.param(
        {"configRoot": "/somewhere/else"},
        "identity.configRoot matches this checkout",
        id="other-config-root",
    ),
    pytest.param(
        {"machineLabel": "another-machine"},
        "env machine label == identity.machineLabel",
        id="machine-label",
    ),
    pytest.param(
        {"note": f"token {FAKE_TOKEN}"},
        "identity carries no token/url/connect-code",
        id="secret-in-identity-token-word",
    ),
    pytest.param(
        {"endpoint": f"{HUB}/mcp/{FAKE_CODE}"},
        "identity carries no token/url/connect-code",
        id="secret-in-identity-url",
    ),
]


@pytest.mark.parametrize(("override", "expected"), IDENTITY_FAIL_CASES)
def test_doctor_identity_mismatch_fails_with_exit_one(cfg_root, capsys, override, expected):
    ident = {**valid_identity(cfg_root), **override}
    outcome = run_doctor(make_root(cfg_root, ident=ident), capsys)

    assert_fail(outcome, expected)


def test_doctor_missing_config_root_fails_even_when_cwd_is_the_root(cfg_root, capsys, monkeypatch):
    ident = valid_identity(cfg_root)
    del ident["configRoot"]
    root = make_root(cfg_root, ident=ident)
    monkeypatch.chdir(root)  # Path("").resolve() is the cwd: it must not count as a match

    assert_fail(run_doctor(root, capsys), "identity.configRoot matches this checkout")


def test_doctor_empty_identity_object_fails_instead_of_being_skipped(cfg_root, capsys):
    outcome = run_doctor(make_root(cfg_root, ident={}), capsys)

    assert_fail(outcome, "identity.part == main-orchestrator")
    assert "FAIL  identity.expectedIsMain is true" in outcome.out


# ======================= doctor: template / files / git hygiene ====================


def test_doctor_literal_secret_in_template_fails_without_echoing_it(cfg_root, capsys):
    leaky = {
        "mcpServers": {
            "candleviewer-relayroom": {
                "url": FAKE_URL,
                "headers": {"Authorization": f"Bearer {FAKE_TOKEN}"},
            }
        }
    }
    outcome = run_doctor(make_root(cfg_root, mcp=leaky), capsys)

    assert_fail(outcome, "template uses env placeholders only (no literal secret)")


def test_doctor_alias_missing_from_template_fails(cfg_root, capsys):
    other = {
        "mcpServers": {"some-other-alias": MCP_TEMPLATE["mcpServers"]["candleviewer-relayroom"]}
    }
    outcome = run_doctor(make_root(cfg_root, mcp=other), capsys)

    assert_fail(outcome, "alias candleviewer-relayroom present")


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        pytest.param({"mcp": None}, ".mcp.json parses as a JSON object", id="no-template"),
        pytest.param(
            {"ident": None}, "identity.local.json parses as a JSON object", id="no-identity"
        ),
        pytest.param(
            {"settings": None}, "settings.local.json parses as a JSON object", id="no-settings"
        ),
        pytest.param({"runs": False}, "at least one run record exists", id="no-runs"),
        pytest.param({"mcp": "{ not json"}, ".mcp.json parses as a JSON object", id="bad-json"),
    ],
)
def test_doctor_missing_or_unparseable_file_fails(cfg_root, capsys, kwargs, expected):
    assert_fail(run_doctor(make_root(cfg_root, **kwargs), capsys), expected)


def test_doctor_without_gitignore_fails_every_ignore_check(cfg_root, capsys):
    outcome = run_doctor(make_root(cfg_root, gitignore=None), capsys)

    assert_fail(outcome, "identity.local.json git-ignored")
    assert "FAIL  settings.local.json git-ignored" in outcome.out
    assert "FAIL  runs/ git-ignored" in outcome.out


def test_doctor_tracked_settings_file_fails(cfg_root, capsys):
    root = make_root(cfg_root)
    assert git(root, "add", "-f", ".claude/settings.local.json").returncode == 0

    assert_fail(run_doctor(root, capsys), "settings.local.json NOT tracked")


def test_doctor_root_that_is_not_a_git_repo_fails(cfg_root, capsys):
    root = make_root(cfg_root, init_git=False)
    if git(root, "rev-parse", "--git-dir").returncode == 0:
        pytest.skip("pytest's temp directory sits inside a git repository")

    outcome = run_doctor(root, capsys)

    assert_fail(outcome, "settings.local.json git-ignored")
    assert "FAIL  identity.local.json git-ignored" in outcome.out


# ============================== doctor: crash safety ================================


def test_doctor_unparseable_url_fails_cleanly_without_echoing_it(cfg_root, capsys):
    env = {**valid_env(), ENV_URL: "https://[" + FAKE_CODE}  # urlsplit raises ValueError
    outcome = run_doctor(make_root(cfg_root, settings={"env": env}), capsys)

    assert_fail(outcome, "MCP URL parses")
    assert "doctor crashed" not in outcome.out


@pytest.mark.parametrize("raw", ["[]", "[1, 2]", '"text"', "42", "null", "true"])
@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("mcp", ".mcp.json parses as a JSON object"),
        ("ident", "identity.local.json parses as a JSON object"),
        ("settings", "settings.local.json parses as a JSON object"),
    ],
)
def test_doctor_non_object_json_fails_instead_of_crashing(cfg_root, capsys, field, expected, raw):
    outcome = run_doctor(make_root(cfg_root, **{field: raw}), capsys)

    assert_fail(outcome, expected)
    assert "doctor crashed" not in outcome.out


@pytest.mark.parametrize(
    "mcp",
    [
        pytest.param({"mcpServers": []}, id="servers-is-a-list"),
        pytest.param({"mcpServers": {"candleviewer-relayroom": "text"}}, id="alias-is-text"),
        pytest.param(
            {"mcpServers": {"candleviewer-relayroom": {"url": "x", "headers": ["y"]}}},
            id="headers-is-a-list",
        ),
    ],
)
def test_doctor_malformed_template_structure_fails_instead_of_crashing(cfg_root, capsys, mcp):
    outcome = run_doctor(make_root(cfg_root, mcp=mcp), capsys)

    assert outcome.code == 1
    assert "doctor crashed" not in outcome.out
    assert_allowlisted(outcome)


@pytest.mark.parametrize("env", [["a"], "text", None, 7], ids=["list", "text", "null", "number"])
def test_doctor_non_object_env_block_reports_every_key_missing(cfg_root, capsys, env):
    outcome = run_doctor(make_root(cfg_root, settings={"env": env}), capsys)

    assert_fail(outcome, f"env.{ENV_KEY} present — pending (activation blocked)")
    assert "doctor crashed" not in outcome.out


def _boom(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError(f"internal detail {FAKE_TOKEN} {FAKE_CODE}")


def test_doctor_unexpected_error_exits_two_naming_only_the_exception_class(
    cfg_root, capsys, monkeypatch
):
    root = make_root(cfg_root)
    monkeypatch.setattr(doctor, "git_ignored", _boom)

    outcome = run_doctor(root, capsys)

    assert outcome.code == 2
    assert outcome.lines == ["FAIL  doctor crashed: RuntimeError"]
    assert_no_leak(outcome)


def test_doctor_crash_does_not_poison_the_next_run(cfg_root, capsys, monkeypatch):
    root = make_root(cfg_root)
    with monkeypatch.context() as patch:
        patch.setattr(doctor, "git_ignored", _boom)
        assert run_doctor(root, capsys).code == 2

    after = run_doctor(root, capsys)

    assert after.code == 0
    assert "doctor crashed" not in after.out


def test_doctor_keyboard_interrupt_is_not_swallowed(cfg_root, monkeypatch):
    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    root = make_root(cfg_root)
    monkeypatch.setattr(doctor, "git_ignored", interrupt)

    with pytest.raises(KeyboardInterrupt):
        doctor.main(["--config-root", str(root)])


def _copy_script_into(root: Path, name: str) -> Path:
    """Copy a script to <root>/scripts/ so its default root (parents[1]) is the synthetic one."""
    (root / "scripts").mkdir(exist_ok=True)
    target = root / "scripts" / name
    shutil.copy2(SCRIPTS_DIR / name, target)
    return target


def test_doctor_script_entry_point_uses_its_own_root_and_exits_zero(cfg_root):
    script = _copy_script_into(make_root(cfg_root), "relayroom-main-doctor.py")

    proc = subprocess.run(
        [sys.executable, "-I", str(script)], capture_output=True, text=True, check=False
    )

    assert proc.returncode == 0, proc.stdout
    assert "READY" in proc.stdout
    for needle in LEAKS:
        assert needle not in proc.stdout + proc.stderr


# =========================== credentials: masked entry script ========================

EXISTING_SETTINGS = {
    "permissions": {"allow": ["Bash(ls:*)"]},
    "model": "sonnet",
    "env": {"KEEP_ME": "1", ENV_LABEL: "stale-label"},
}


@pytest.fixture
def target(cfg_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A synthetic settings.local.json that the credential script is pointed at."""
    path = cfg_root / ".claude" / "settings.local.json"
    write(path, EXISTING_SETTINGS)
    monkeypatch.setattr(creds, "TARGET", path)
    return path


def as_tty(monkeypatch: pytest.MonkeyPatch, *, stdin: bool = True, stdout: bool = True) -> None:
    """Make the (captured) standard streams report whether they are a terminal."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout, raising=False)


def type_answers(
    monkeypatch: pytest.MonkeyPatch, *, code: str, token: str, label: str = ""
) -> None:
    """Answer the two masked prompts, then the visible machine-label prompt."""
    secrets = iter([code, token])
    monkeypatch.setattr(creds.getpass, "getpass", lambda prompt="": next(secrets))
    monkeypatch.setattr("builtins.input", lambda prompt="": label)


def leftovers(path: Path) -> list[str]:
    """Names next to `path` other than `path` itself (a stray temp file would show up here)."""
    return sorted(p.name for p in path.parent.iterdir() if p.name != path.name)


def enter(monkeypatch: pytest.MonkeyPatch, *, code: str, token: str, label: str = "") -> None:
    as_tty(monkeypatch)
    type_answers(monkeypatch, code=code, token=token, label=label)
    creds.main()


def assert_text_has_no_secret(text: str, *secrets: str) -> None:
    for needle in (*LEAKS, *secrets):
        if needle.strip():
            assert needle not in text, f"leaked {needle!r}"


@pytest.mark.parametrize(
    ("stdin", "stdout"),
    [(False, False), (True, False), (False, True)],
    ids=["neither", "stdout-redirected", "stdin-piped"],
)
def test_credentials_refuse_without_a_real_tty(target, capsys, monkeypatch, stdin, stdout):
    as_tty(monkeypatch, stdin=stdin, stdout=stdout)
    monkeypatch.setattr(
        creds.getpass, "getpass", lambda *_a, **_k: pytest.fail("prompted without a TTY")
    )
    before = target.read_bytes()

    with pytest.raises(SystemExit) as exc:
        creds.main()

    assert exc.value.code == 2
    assert "refused: a real TTY is required" in capsys.readouterr().err
    assert target.read_bytes() == before


def test_credentials_refuse_when_the_settings_file_does_not_exist(cfg_root, capsys, monkeypatch):
    missing = cfg_root / ".claude" / "settings.local.json"
    monkeypatch.setattr(creds, "TARGET", missing)
    as_tty(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        creds.main()

    assert exc.value.code == 2
    assert "does not exist" in capsys.readouterr().err
    assert not missing.exists()  # never creates the private file on its own


REFUSALS = [
    pytest.param("", FAKE_TOKEN, "empty value", id="empty-code"),
    pytest.param(FAKE_CODE, "", "empty value", id="empty-token"),
    pytest.param("   ", FAKE_TOKEN, "empty value", id="blank-code"),
    pytest.param(FAKE_CODE, "Bearer " + FAKE_TOKEN, "without the 'Bearer ' prefix", id="bearer"),
    pytest.param(FAKE_CODE, "bEaReR " + FAKE_TOKEN, "without the 'Bearer ' prefix", id="BEARER"),
    pytest.param("FAKE CODE123", FAKE_TOKEN, "whitespace in a secret value", id="space-in-code"),
    pytest.param(FAKE_CODE, "FAKE\tTOKEN", "whitespace in a secret value", id="tab-in-token"),
    pytest.param("<paste-code-here>", FAKE_TOKEN, "placeholder text", id="placeholder-code"),
    pytest.param(FAKE_CODE, "${" + ENV_KEY + "}", "placeholder text", id="placeholder-token"),
    pytest.param("FAKE%25CODE", FAKE_TOKEN, "already URL-encoded", id="percent-encoded"),
    pytest.param("FAKE%2FCODE", FAKE_TOKEN, "already URL-encoded", id="percent-encoded-slash"),
]


@pytest.mark.parametrize(("code", "token", "message"), REFUSALS)
def test_credentials_refuse_bad_values_and_write_nothing(
    target, capsys, monkeypatch, code, token, message
):
    before = target.read_bytes()

    with pytest.raises(SystemExit) as exc:
        enter(monkeypatch, code=code, token=token)

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert captured.err.startswith("refused: ")
    assert message in captured.err
    assert target.read_bytes() == before
    assert leftovers(target) == []
    assert_text_has_no_secret(captured.out + captured.err, code, token)


def test_credentials_merge_exactly_three_env_keys_and_keep_everything_else(
    target, capsys, monkeypatch
):
    enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN, label=FAKE_LABEL)

    text = target.read_text(encoding="utf-8")
    data = json.loads(text)
    assert set(data) == set(EXISTING_SETTINGS)
    assert data["permissions"] == EXISTING_SETTINGS["permissions"]
    assert data["model"] == "sonnet"
    assert data["env"] == {
        "KEEP_ME": "1",  # an unrelated env entry survives
        ENV_URL: FAKE_URL,
        ENV_KEY: FAKE_TOKEN,
        ENV_LABEL: FAKE_LABEL,  # replaces the stale value
    }
    assert text.endswith("}\n")
    assert leftovers(target) == []


def test_credentials_success_output_never_shows_the_values(target, capsys, monkeypatch):
    enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN, label=FAKE_LABEL)

    captured = capsys.readouterr()
    assert "written: 3 env keys merged" in captured.out
    assert_text_has_no_secret(captured.out + captured.err)


def test_credentials_blank_label_falls_back_to_the_default(target, monkeypatch):
    enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN, label="")

    env = json.loads(target.read_text(encoding="utf-8"))["env"]
    assert env[ENV_LABEL] == creds.DEFAULT_LABEL


def test_credentials_trim_whitespace_around_the_pasted_values(target, monkeypatch):
    enter(monkeypatch, code=f"  {FAKE_CODE}\n", token=f"\t{FAKE_TOKEN} ", label=f" {FAKE_LABEL} ")

    env = json.loads(target.read_text(encoding="utf-8"))["env"]
    assert (env[ENV_URL], env[ENV_KEY], env[ENV_LABEL]) == (FAKE_URL, FAKE_TOKEN, FAKE_LABEL)


def test_credentials_percent_encode_reserved_characters_in_the_code_once(target, monkeypatch):
    enter(monkeypatch, code="FAKE/CODE?x=1", token=FAKE_TOKEN)

    url = json.loads(target.read_text(encoding="utf-8"))["env"][ENV_URL]
    assert url == f"{HUB}/mcp/FAKE%2FCODE%3Fx%3D1?part=main-orchestrator"


def test_credentials_output_is_accepted_by_the_doctor(cfg_root, capsys, monkeypatch):
    root = make_root(cfg_root, settings={"model": "sonnet"})
    monkeypatch.setattr(creds, "TARGET", root / ".claude" / "settings.local.json")

    enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN, label=FAKE_LABEL)
    capsys.readouterr()
    outcome = run_doctor(root, capsys)

    assert outcome.code == 0, outcome.out
    assert_no_leak(outcome)


# ---- hub origin: private configuration, resolved before any secret is asked for ----


def descriptor_path(target: Path) -> Path:
    return target.parent / "relayroom" / "identity.local.json"


def refuse_without_prompting(target: Path, capsys, monkeypatch) -> str:
    """Run the script expecting an up-front refusal: exit 2, no prompt, nothing written."""
    as_tty(monkeypatch)
    monkeypatch.setattr(
        creds.getpass, "getpass", lambda *_a, **_k: pytest.fail("asked for a secret")
    )
    before = target.read_bytes()

    with pytest.raises(SystemExit) as exc:
        creds.main()

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert captured.out == ""
    assert target.read_bytes() == before
    assert not [p.name for p in target.parent.iterdir() if p.name.startswith(creds.TMP_PREFIX)]
    assert_text_has_no_secret(captured.err)
    return captured.err


@pytest.mark.parametrize(
    "descriptor",
    [None, {}, {"project": "candleviewer"}, {"hubOrigin": None}, {"hubOrigin": "  "}, "{ no", "[]"],
    ids=["absent", "empty-object", "no-key", "null", "blank", "malformed", "not-an-object"],
)
def test_credentials_without_a_hub_origin_refuse_before_prompting(
    target, capsys, monkeypatch, descriptor
):
    monkeypatch.delenv(ORIGIN_ENV)
    if descriptor is not None:
        write(descriptor_path(target), descriptor)

    err = refuse_without_prompting(target, capsys, monkeypatch)

    assert err == (
        f"refused: hub origin not configured — set {ORIGIN_ENV} or `hubOrigin` "
        "in the private descriptor\n"
    )


@pytest.mark.parametrize("bad", INVALID_ORIGINS)
@pytest.mark.parametrize("source", ["env", "descriptor"])
def test_credentials_refuse_an_invalid_hub_origin_before_prompting(
    target, capsys, monkeypatch, source, bad
):
    if source == "env":
        monkeypatch.setenv(ORIGIN_ENV, bad)
    else:
        monkeypatch.delenv(ORIGIN_ENV)
        write(descriptor_path(target), {"hubOrigin": bad})

    err = refuse_without_prompting(target, capsys, monkeypatch)

    where = f"env {ORIGIN_ENV}" if source == "env" else "identity.hubOrigin"
    assert err == (
        f"refused: hub origin invalid in {where} — expected https://host[:port] and nothing else\n"
    )


def test_credentials_invalid_env_origin_is_not_rescued_by_a_valid_descriptor_origin(
    target, capsys, monkeypatch
):
    monkeypatch.setenv(ORIGIN_ENV, "http://" + HUB_HOST)
    write(descriptor_path(target), {"hubOrigin": HUB})  # valid, but the env value is what counts

    err = refuse_without_prompting(target, capsys, monkeypatch)

    assert err == (
        f"refused: hub origin invalid in env {ORIGIN_ENV} — "
        "expected https://host[:port] and nothing else\n"
    )


def test_credentials_use_the_descriptor_hub_origin_when_the_env_is_absent(target, monkeypatch):
    monkeypatch.delenv(ORIGIN_ENV)
    write(descriptor_path(target), {"hubOrigin": HUB})

    enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN, label=FAKE_LABEL)

    assert json.loads(target.read_text(encoding="utf-8"))["env"][ENV_URL] == FAKE_URL


def test_credentials_env_hub_origin_takes_precedence_over_the_descriptor(target, monkeypatch):
    write(descriptor_path(target), {"hubOrigin": OTHER_HUB})  # the env (HUB) wins

    enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN, label=FAKE_LABEL)

    assert json.loads(target.read_text(encoding="utf-8"))["env"][ENV_URL] == FAKE_URL


@pytest.mark.parametrize(
    ("configured", "canonical"),
    [
        pytest.param(f"  {HUB} ", HUB, id="whitespace"),
        pytest.param(f"{HUB}/", HUB, id="trailing-slash"),
        pytest.param("https://Hub.Example.TEST", HUB, id="host-case-insensitive"),
        pytest.param(f"{HUB}:8443", f"{HUB}:8443", id="port-kept"),
    ],
)
def test_credentials_build_the_url_from_the_canonical_configured_origin(
    target, monkeypatch, configured, canonical
):
    monkeypatch.setenv(ORIGIN_ENV, configured)

    enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN, label=FAKE_LABEL)

    url = json.loads(target.read_text(encoding="utf-8"))["env"][ENV_URL]
    assert url == f"{canonical}/mcp/{FAKE_CODE}?part=main-orchestrator"


def test_credentials_output_is_accepted_by_the_doctor_with_a_descriptor_only_origin(
    cfg_root, capsys, monkeypatch
):
    monkeypatch.delenv(ORIGIN_ENV)
    ident = {**valid_identity(cfg_root), "hubOrigin": HUB}
    root = make_root(cfg_root, ident=ident, settings={"model": "sonnet"})
    monkeypatch.setattr(creds, "TARGET", root / ".claude" / "settings.local.json")

    enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN, label=FAKE_LABEL)
    capsys.readouterr()
    outcome = run_doctor(root, capsys)

    assert outcome.code == 0, outcome.out
    assert "PASS  hub origin resolved — via identity.hubOrigin" in outcome.out
    assert_no_leak(outcome)


# ---- atomic write: no temp file may survive any failure (it would hold the secrets) ----


def fail_replace(monkeypatch: pytest.MonkeyPatch, path: Path, exc: BaseException) -> None:
    """Make os.replace raise `exc` for `path` only; any other replace still works."""
    real_replace = os.replace

    def replace(src, dst, *args, **kwargs):
        if Path(dst) == path:
            raise exc
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(creds.os, "replace", replace)


@pytest.mark.parametrize(
    "exc",
    [OSError("disk full"), KeyboardInterrupt()],
    ids=["oserror", "keyboard-interrupt"],
)
def test_credentials_failed_replace_leaves_no_temp_file_and_keeps_the_original(
    target, capsys, monkeypatch, exc
):
    before = target.read_bytes()
    fail_replace(monkeypatch, target, exc)

    with pytest.raises(type(exc)):
        enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN, label=FAKE_LABEL)

    assert leftovers(target) == []
    assert target.read_bytes() == before
    captured = capsys.readouterr()
    assert_text_has_no_secret(captured.out + captured.err)


def test_credentials_failed_json_dump_leaves_no_temp_file(target, monkeypatch):
    def dump(*_args, **_kwargs):
        raise TypeError("cannot serialise")

    monkeypatch.setattr(creds.json, "dump", dump)
    before = target.read_bytes()

    with pytest.raises(TypeError):
        enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN)

    assert leftovers(target) == []
    assert target.read_bytes() == before


def test_credentials_fdopen_failure_closes_the_descriptor_and_removes_the_temp_file(
    target, monkeypatch
):
    made: list[int] = []
    closed: list[int] = []
    real_mkstemp, real_close = tempfile.mkstemp, os.close

    def spy_mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        made.append(fd)
        return fd, name

    def spy_close(fd):
        closed.append(fd)
        real_close(fd)

    def fdopen(*_args, **_kwargs):
        raise OSError("fdopen failed")

    monkeypatch.setattr(creds.tempfile, "mkstemp", spy_mkstemp)
    monkeypatch.setattr(creds.os, "close", spy_close)
    monkeypatch.setattr(creds.os, "fdopen", fdopen)

    with pytest.raises(OSError, match="fdopen failed"):
        enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN)

    assert len(made) == 1
    assert made[0] in closed
    assert leftovers(target) == []


def test_credentials_temp_file_name_matches_the_gitignore_pattern_prefix_and_suffix():
    assert creds.TMP_PREFIX == ".settings.local."
    assert creds.TMP_SUFFIX == ".tmp"


def test_repo_gitignore_covers_the_private_files_and_the_atomic_write_temp_file(cfg_root):
    subprocess.run(["git", "init", "-q", str(cfg_root)], capture_output=True, check=True)
    shutil.copy2(REPO_ROOT / ".gitignore", cfg_root / ".gitignore")
    claude = cfg_root / ".claude"
    (claude / "relayroom" / "runs").mkdir(parents=True)
    skill_dir = claude / "skills" / "candleviewer-relayroom-check"
    skill_dir.mkdir(parents=True)
    fd, tmp_name = tempfile.mkstemp(dir=claude, prefix=creds.TMP_PREFIX, suffix=creds.TMP_SUFFIX)
    os.close(fd)
    private = [
        claude / "settings.local.json",
        claude / "relayroom" / "identity.local.json",
        claude / "relayroom" / "runs" / "x.json",
        cfg_root / ".mcp.json",
        cfg_root / ".mcp.json.tmp",
        skill_dir / "SKILL.md",
    ]
    for path in private:
        path.write_text("{}", encoding="utf-8")

    for path in [*private, Path(tmp_name)]:
        rel = path.relative_to(cfg_root).as_posix()
        assert git(cfg_root, "check-ignore", "-q", rel).returncode == 0, f"{rel} not ignored"
    for shared in (
        ".claude/settings.json",
        ".claude/skills/other-skill/SKILL.md",  # the skill entry is narrow, not all of skills/
        "docs/ops/relayroom-check-skill.template.md",
        "docs/ops/relayroom-mcp.template.json",
    ):
        assert git(cfg_root, "check-ignore", "-q", shared).returncode == 1, f"{shared} ignored"


# ------------------------------ entry points and contracts ------------------------------


def test_credentials_script_entry_point_refuses_when_not_run_from_a_terminal(cfg_root):
    settings = cfg_root / ".claude" / "settings.local.json"
    write(settings, EXISTING_SETTINGS)
    script = _copy_script_into(cfg_root, "relayroom-enter-credentials.py")
    before = settings.read_bytes()

    proc = subprocess.run(
        [sys.executable, "-I", str(script)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "refused: a real TTY is required" in proc.stderr
    assert settings.read_bytes() == before


def test_credentials_docstring_states_the_windows_permission_caveat():
    doc = creds.__doc__ or ""

    assert "NTFS" in doc
    assert "0600" in doc


def test_doctor_docstring_documents_all_three_exit_codes():
    doc = doctor.__doc__ or ""

    assert all(f"{code} =" in doc for code in (0, 1, 2))


def test_project_settings_deny_reads_of_the_relayroom_secret_files():
    """Two deny rules, both on the secret-bearing file only: the nonsecret identity/run records
    under `.claude/relayroom/` stay readable because the skill and the worker policy read them."""
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    permissions = settings["permissions"]

    for rule in (
        "Read(./.claude/settings.local.json)",
        "Bash(*settings.local.json*)",
    ):
        assert rule in permissions["deny"]
    assert permissions["ask"] == []  # owner policy: deny rules only, never prompts
    assert permissions["defaultMode"] == "bypassPermissions"


# ============= hub origin resolver: one contract, kept in step across both scripts ==========


@pytest.fixture(params=[doctor, creds], ids=["doctor", "credentials"])
def script(request):
    return request.param


def test_hub_origin_resolver_prefers_env_then_descriptor_and_has_no_default(script):
    descriptor = {"hubOrigin": OTHER_HUB}

    assert script.hub_origin({}) == (HUB, f"env {ORIGIN_ENV}")  # reads os.environ by default
    assert script.hub_origin(descriptor, {ORIGIN_ENV: HUB}) == (HUB, f"env {ORIGIN_ENV}")
    assert script.hub_origin(descriptor, {}) == (OTHER_HUB, "identity.hubOrigin")
    assert script.hub_origin(descriptor, {ORIGIN_ENV: "  "}) == (OTHER_HUB, "identity.hubOrigin")
    for identity in (None, {}, [], "text", {"hubOrigin": None}, {"hubOrigin": ""}):
        with pytest.raises(ValueError, match="^not configured — set "):
            script.hub_origin(identity, {})


@pytest.mark.parametrize("bad", INVALID_ORIGINS)
def test_hub_origin_resolver_rejects_invalid_values_without_echoing_them(script, bad):
    suffix = "expected https://host[:port] and nothing else"

    with pytest.raises(ValueError) as from_env:
        script.hub_origin({}, {ORIGIN_ENV: bad})
    with pytest.raises(ValueError) as from_descriptor:
        script.hub_origin({"hubOrigin": bad}, {})

    assert str(from_env.value) == f"invalid in env {ORIGIN_ENV} — {suffix}"
    assert str(from_descriptor.value) == f"invalid in identity.hubOrigin — {suffix}"


@pytest.mark.parametrize("bad", INVALID_ORIGINS)
def test_hub_origin_resolver_does_not_fall_back_when_the_env_value_is_invalid(script, bad):
    # A valid descriptor must not rescue an invalid env value: the env takes precedence, refused.
    with pytest.raises(ValueError) as exc:
        script.hub_origin({"hubOrigin": HUB}, {ORIGIN_ENV: bad})

    assert str(exc.value) == (
        f"invalid in env {ORIGIN_ENV} — expected https://host[:port] and nothing else"
    )


def test_hub_origin_parsing_is_identical_in_both_scripts():
    samples = [HUB, f"{HUB}/", f" {HUB}:8443 ", "https://Hub.Example.TEST", None, 7, "", "  "]
    samples += [param.values[0] for param in INVALID_ORIGINS]

    assert doctor.ORIGIN_RE.pattern == creds.ORIGIN_RE.pattern
    assert (doctor.ORIGIN_ENV, doctor.ORIGIN_KEY) == (creds.ORIGIN_ENV, creds.ORIGIN_KEY)
    assert (creds.ORIGIN_ENV, creds.ORIGIN_KEY) == (ORIGIN_ENV, "hubOrigin")
    assert [doctor.parse_origin(s) for s in samples] == [creds.parse_origin(s) for s in samples]


@pytest.mark.parametrize("filename", ["relayroom-main-doctor.py", "relayroom-enter-credentials.py"])
def test_scripts_commit_no_hub_origin_literal(filename):
    tree = ast.parse((SCRIPTS_DIR / filename).read_text(encoding="utf-8"))
    strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]

    assert [s for s in strings if doctor.parse_origin(s) is not None] == []
