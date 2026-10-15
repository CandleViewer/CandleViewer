"""Unit tests for the RelayRoom client scripts: the doctor and the credential entry.

Everything here is synthetic: FAKE connect codes, tokens and URLs, written into pytest temp
directories next to a throw-away ``git init`` repository so ``check-ignore`` / ``ls-files``
behave as they do in the real checkout. No network, and nothing reads a real
``.claude/settings.local.json`` or any ``.claude/relayroom/`` file.
"""

from __future__ import annotations

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
FAKE_TOKEN = "FAKETOKENxyz"
FAKE_URL = f"https://relay.candleviewer.com/mcp/{FAKE_CODE}?part=main-orchestrator"
FAKE_LABEL = "cv-test-machine-l01"
FAKE_UUID = "11111111-2222-4333-8444-555555555555"
# What must never reach stdout/stderr: the fake secrets and any secret-bearing URL path.
LEAKS = (FAKE_CODE, FAKE_TOKEN, "/mcp/")

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
    template = json.loads((REPO_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    outcome = run_doctor(make_root(cfg_root, mcp=template), capsys)

    assert outcome.code == 0, outcome.out


# ============================ doctor: env / URL failures ============================

URL_NO_QUERY = FAKE_URL.split("?")[0]
ENV_FAIL_CASES = [
    pytest.param(
        {ENV_URL: "https://relay.candleviewer.com/mcp/<CODE>?part=main-orchestrator"},
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
        {ENV_URL: FAKE_URL.replace("relay.candleviewer.com", "relay.example.org")},
        "MCP URL origin is the hub (https, exact host)",
        id="origin-wrong-host",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace("https:", "http:")},
        "MCP URL origin is the hub (https, exact host)",
        id="origin-scheme-downgrade",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace("candleviewer.com", "candleviewer.com:8443")},
        "MCP URL origin is the hub (https, exact host)",
        id="origin-extra-port",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace("candleviewer.com", "candleviewer.com.evil.example")},
        "MCP URL origin is the hub (https, exact host)",
        id="origin-suffix-attack",
    ),
    pytest.param(
        {ENV_URL: FAKE_URL.replace("//relay", "//user:pw@relay")},
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
        {"endpoint": f"https://relay.candleviewer.com/mcp/{FAKE_CODE}"},
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
    assert url == "https://relay.candleviewer.com/mcp/FAKE%2FCODE%3Fx%3D1?part=main-orchestrator"


def test_credentials_output_is_accepted_by_the_doctor(cfg_root, capsys, monkeypatch):
    root = make_root(cfg_root, settings={"model": "sonnet"})
    monkeypatch.setattr(creds, "TARGET", root / ".claude" / "settings.local.json")

    enter(monkeypatch, code=FAKE_CODE, token=FAKE_TOKEN, label=FAKE_LABEL)
    capsys.readouterr()
    outcome = run_doctor(root, capsys)

    assert outcome.code == 0, outcome.out
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
    fd, tmp_name = tempfile.mkstemp(dir=claude, prefix=creds.TMP_PREFIX, suffix=creds.TMP_SUFFIX)
    os.close(fd)
    private = [
        claude / "settings.local.json",
        claude / "relayroom" / "identity.local.json",
        claude / "relayroom" / "runs" / "x.json",
    ]
    for path in private:
        path.write_text("{}", encoding="utf-8")

    for path in [*private, Path(tmp_name)]:
        rel = path.relative_to(cfg_root).as_posix()
        assert git(cfg_root, "check-ignore", "-q", rel).returncode == 0, f"{rel} not ignored"
    for shared in (".claude/settings.json", ".claude/skills/candleviewer-relayroom-check/SKILL.md"):
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
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    permissions = settings["permissions"]

    for rule in (
        "Read(./.claude/settings.local.json)",
        "Read(./.claude/relayroom/**)",
        "Bash(cat ./.claude/settings.local.json)",
    ):
        assert rule in permissions["deny"]
    assert permissions["ask"] == []  # owner policy: deny rules only, never prompts
    assert permissions["defaultMode"] == "bypassPermissions"
