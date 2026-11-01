"""#2893's closure: the fixture stack's real-backend overlay (rule 8 of `lint_compose.py`).

`infra/compose/docker-compose.account-fixture-real.yml` puts the real backend under the fixture
stack's api and adds the run's two one-shots, `fixture-init` (the seed's `init`) and
`fixture-drive` (the driver). These tests hold it to its rules, statically, with no Docker and no
network: it is opt-in, the api keeps the app's own entrypoint so the S8 boot guard runs first, every
generated value is the run's own variable, the KEK and the audit lane key are file secrets from the
run directory, the one-shots build the builder stage and publish no port, and `fixture-init`'s one
writable mount is the run directory (T2 at the compose level). `lint_compose.py` rule 8 is the CI
form of the same shape.
"""

from __future__ import annotations

import ast
import copy
import re
import sys
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

REPO: Final = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "infra" / "scripts"))

import lint_compose  # noqa: E402  (after the path insert, as test_compose_fixture_override.py does)

COMPOSE: Final = REPO / "infra" / "compose"
OVERLAY_PATH: Final = COMPOSE / "docker-compose.account-fixture-real.yml"
OVERLAY: Final[dict[str, Any]] = yaml.safe_load(OVERLAY_PATH.read_text(encoding="utf-8"))
SERVICES: Final[dict[str, Any]] = OVERLAY["services"]
API: Final[dict[str, Any]] = SERVICES["api"]
ONE_SHOTS: Final = ("fixture-init", "fixture-drive")
#: What a default stack, a workflow or a task runner reads (AGENTS.md section 4, `make up`).
DEFAULT_PATHS: Final = (
    REPO / "infra" / "docker-compose.dev.yml",
    COMPOSE / "docker-compose.yml",
    COMPOSE / "docker-compose.dev.yml",
    COMPOSE / "docker-compose.account-fixture.yml",
    REPO / "package.json",
)
#: The values this overlay commits; every other one is the run's `${NAME:?...}` or rule 7's.
COMMITTED: Final = {
    "real", "203.0.113.10", "file", "/run/secrets/cv_kek", "1", "/data/parquet", "demo",
    "synthetic", "/var/lib/candleviewer/account-fixture",
}  # fmt: skip
RUN_VARIABLE: Final = re.compile(r"\$\{(?P<name>[A-Z_]+):\?[^}]*\}")


def _environment(service: dict[str, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in (service.get("environment") or {}).items()}


def test_the_real_overlay_passes_rule_8() -> None:
    assert lint_compose.lint(OVERLAY_PATH, account_fixture_real_overlay=True) == []


def test_it_is_opt_in() -> None:
    """No default compose path, workflow or task runner names it."""
    readers = [*DEFAULT_PATHS, *(REPO / ".github" / "workflows").glob("*.y*ml")]
    readers += [path for path in (REPO / "Makefile",) if path.exists()]
    for path in readers:
        assert OVERLAY_PATH.name not in path.read_text(encoding="utf-8"), path.name


def test_it_keeps_the_apps_entrypoint_so_the_boot_guard_runs_first() -> None:
    """The S8 guard runs in the app's lifespan before any module starts: the api here replaces
    neither the entrypoint nor the command, builds nothing and names no image."""
    assert {"entrypoint", "command", "build", "image", "ports", "env_file"}.isdisjoint(API)


def test_it_pins_demo_synthetic_and_no_exchange_key_or_test_clock() -> None:
    """The api keeps rule 7's pins (this file sets none of the fixture's four names), and each
    one-shot is armed on demo and the synthetic feed; no exchange key or test clock anywhere."""
    text = yaml.safe_dump(OVERLAY)  # the parsed file: its header comment names what it omits
    assert "CV_BYBIT_API_" not in text and "CV_TEST_CLOCK" not in text
    fixture_names = {"CV_ENVIRONMENT", "CV_FEED", "CV_ACCOUNT_FIXTURE", "CV_ACCOUNT_FIXTURE_DIR"}
    assert fixture_names.isdisjoint(_environment(API))
    for name in ONE_SHOTS:
        env = _environment(SERVICES[name])
        assert (env["CV_ENVIRONMENT"], env["CV_FEED"]) == ("demo", "synthetic"), name
        assert env["CV_ACCOUNT_FIXTURE_DIR"] == lint_compose.FIXTURE_DIR, name


def test_the_kek_and_lane_key_are_file_secrets_from_the_runs_variables() -> None:
    """Both come from the run directory as host files, with no default; the api reads the KEK at
    its handle, and the lane key where the base file mounts it."""
    secrets = OVERLAY["secrets"]
    assert set(secrets) == {"cv_kek", "cv_audit_lane_key"}
    assert re.fullmatch(r"\$\{CV_KEK_FILE:\?[^}]*\}", secrets["cv_kek"]["file"])
    lane = secrets["cv_audit_lane_key"]["file"]
    assert re.fullmatch(r"\$\{CV_AUDIT_LANE_MAC_SOURCE:\?[^}]*\}", lane)
    assert all(set(entry) == {"file"} for entry in secrets.values())
    env = _environment(API)
    assert (env["CV_KEK_SOURCE"], env["CV_KEK_HANDLE"]) == ("file", "/run/secrets/cv_kek")
    assert API["secrets"] == ["cv_kek"]
    base = yaml.safe_load((COMPOSE / "docker-compose.yml").read_text(encoding="utf-8"))
    targets = [entry["target"] for entry in base["services"]["api"]["secrets"]]
    assert targets == ["cv_audit_lane_key"]  # /run/secrets/cv_audit_lane_key, the loader's default


def test_it_commits_no_generated_value() -> None:
    """Every environment value is a committed constant, rule 7's scenario or the run's own
    `${NAME:?...}` for that very name; no value holds 43 base64 characters, and no run of 32 hex
    digits sits anywhere in the file, its comments included."""
    for name, service in SERVICES.items():
        for key, value in _environment(service).items():
            variable = RUN_VARIABLE.fullmatch(value)
            scenario = key == "CV_ACCOUNT_FIXTURE" and value == "${CV_ACCOUNT_FIXTURE:-compliant}"
            assert value in COMMITTED or scenario or (variable and variable["name"] == key), (
                name,
                key,
            )
            assert not re.search(r"[A-Za-z0-9+/_-]{43,}", value), (name, key)
    assert not re.search(r"[0-9A-Fa-f]{32,}", OVERLAY_PATH.read_text(encoding="utf-8"))


def test_its_egress_is_the_packs() -> None:
    """The key import and the self-check hold a key's allowlist to `CV_EGRESS_IP`, and the pack's
    scenarios answer `pack.EGRESS_IP`: the two stay one address (an RFC 5737 one)."""
    pack = REPO / "services" / "api" / "cvdev" / "account_fixture" / "pack.py"
    tree = ast.parse(pack.read_text(encoding="utf-8"))
    egress = next(
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "EGRESS_IP"
        and isinstance(node.value, ast.Constant)
    )
    assert _environment(API)["CV_EGRESS_IP"] == egress == lint_compose.FIXTURE_EGRESS_IP
    assert egress.startswith(("192.0.2.", "198.51.100.", "203.0.113."))


def test_the_one_shots_build_the_builder_stage_and_publish_no_port() -> None:
    for name in ONE_SHOTS:
        service = SERVICES[name]
        assert service["build"]["target"] == "builder", name
        assert {"image", "ports", "env_file", "secrets", "pull_policy"}.isdisjoint(service), name
        assert service["profiles"] == [name], name  # `up` never starts it
        assert service["read_only"] is True and "tmpfs" not in service, name
        assert service["ulimits"] == {"core": 0}, name


def test_fixture_init_writes_only_the_run_dir() -> None:
    """T2 at the compose level: on a read-only root, `fixture-init`'s one writable mount is the run
    directory; `fixture-drive` reads it, and writes only its session volume."""
    init, drive = (SERVICES[name]["volumes"] for name in ONE_SHOTS)
    assert [m for m in init if not m.endswith(":ro")] == [init[-1]]
    assert re.fullmatch(r"\$\{CV_ACCTFIX_RUN_DIR:\?[^}]*\}:/run-dir", init[-1])
    assert [m for m in drive if not m.endswith(":ro")] == [
        f"{lint_compose.SESSION_VOLUME}:/session"
    ]
    assert re.fullmatch(r"\$\{CV_ACCTFIX_RUN_DIR:\?[^}]*\}:/run-dir:ro", drive[1])
    assert SERVICES["fixture-init"]["command"] == ["init", "--run-dir", "/run-dir"]


def _mutated(path: tuple[str, ...], value: object) -> dict[str, Any]:
    overlay = copy.deepcopy(OVERLAY)
    node = overlay
    for key in path[:-1]:
        node = node[key]
    if value is None:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return overlay


_API, _INIT, _DRIVE = (
    ("services", "api"),
    ("services", "fixture-init"),
    ("services", "fixture-drive"),
)
_ENV = "environment"
_RUN = "${CV_ACCTFIX_RUN_DIR:?x}"
#: The one-shots' own mounts: a case that swaps the run directory's access keeps their count, so
#: the access alone is what rule 8 refuses.
_INIT_MOUNTS: Final[list[str]] = SERVICES["fixture-init"]["volumes"]
_DRIVE_MOUNTS: Final[list[str]] = SERVICES["fixture-drive"]["volumes"]


@pytest.mark.parametrize(
    ("path", "value", "why"),
    [
        ((*_API, "entrypoint"), ["sh"], "not entrypoint"),
        ((*_API, "command"), ["x"], "not command"),
        ((*_API, "image"), "ghcr.io/o/img@sha256:" + "a" * 64, "not image"),
        ((*_API, "build"), {"target": "runtime"}, "not build"),
        ((*_API, "ports"), ["127.0.0.1:8000:8000"], "not ports"),
        ((*_API, "env_file"), ["stack.env"], "not env_file"),
        ((*_API, _ENV, "CV_STORAGE_BACKEND"), "fake", "CV_STORAGE_BACKEND is not real"),
        ((*_API, _ENV, "CV_EGRESS_IP"), "198.51.100.7", "CV_EGRESS_IP is not"),
        ((*_API, _ENV, "CV_KEK_SOURCE"), "handle", "CV_KEK_SOURCE is not file"),
        ((*_API, _ENV, "CV_AUTH_PEPPER"), "inline-pepper", "CV_AUTH_PEPPER is not the run's own"),
        ((*_API, _ENV, "CV_AUTH_CSRF_KEY_HEX"), "${CV_OTHER:?x}", "CV_AUTH_CSRF_KEY_HEX is not"),
        ((*_API, _ENV, "CV_BYBIT_API_KEY"), "${CV_BYBIT_API_KEY:-}", "CV_BYBIT_API_KEY"),
        ((*_API, _ENV, "CV_TEST_CLOCK"), "true", "CV_TEST_CLOCK"),
        ((*_API, "secrets"), None, "secrets are not cv_kek alone"),
        ((*_API, "volumes"), ["cv-api-data:/data"], "volumes are not cv-api-data alone"),
        ((*_API, "ulimits"), None, "ulimits is not core: 0"),
        (("secrets", "cv_kek"), {"file": "kek.bin"}, "secret 'cv_kek' is not file"),
        (("secrets", "cv_kek"), {"environment": "CV_KEK_HEX"}, "secret 'cv_kek' is not file"),
        (
            ("secrets", "cv_audit_lane_key"),
            {"file": "${CV_AUDIT_LANE_MAC_SOURCE:-/dev/null}"},
            "secret 'cv_audit_lane_key' is not file",
        ),
        (("secrets", "extra"), {"file": "${CV_EXTRA:?x}"}, "top-level secrets"),
        ((*_INIT, _ENV, "CV_ENVIRONMENT"), "live", "CV_ENVIRONMENT is off rule 7"),
        ((*_INIT, _ENV, "CV_FEED"), "bybit", "CV_FEED is off rule 7"),
        ((*_INIT, _ENV, "CV_ACCOUNT_FIXTURE"), "../x", "CV_ACCOUNT_FIXTURE is off rule 7"),
        ((*_INIT, _ENV, "CV_ACCOUNT_FIXTURE_DIR"), "/var/lib/x", "CV_ACCOUNT_FIXTURE_DIR is off"),
        ((*_INIT, _ENV, "CV_BYBIT_API_SECRET"), "${CV_BYBIT_API_SECRET:-}", "CV_BYBIT_API_SECRET"),
        ((*_INIT, _ENV, "CV_PG_DSN"), "postgresql+asyncpg://cv@pg/x_test", "CV_PG_DSN is not"),
        ((*_INIT, _ENV, "CV_ACCTFIX_RUN_UID"), "0", "CV_ACCTFIX_RUN_UID is not the run's own"),
        (
            (*_INIT, "volumes"),
            [*_INIT_MOUNTS[:-1], f"{_RUN}:/run-dir:ro"],
            "volumes are not exactly its mounts (the run directory read-write)",
        ),
        ((*_INIT, "ports"), ["127.0.0.1:9:9"], "does not set ports on it"),
        ((*_INIT, "profiles"), None, "profiles is not [fixture-init]"),
        ((*_INIT, "read_only"), None, "read_only is not the one-shot's"),
        ((*_INIT, "build"), {"context": "../..", "target": "runtime"}, "build is not"),
        ((*_INIT, "entrypoint"), ["sh"], "entrypoint is not the one this overlay runs"),
        ((*_INIT, "command"), ["users", "--run-dir", "/run-dir"], "command is not"),
        (
            (*_DRIVE, "volumes"),
            [_DRIVE_MOUNTS[0], f"{_RUN}:/run-dir", _DRIVE_MOUNTS[2]],
            "the run directory read-only",
        ),
        (
            (*_DRIVE, "volumes"),
            [*_DRIVE_MOUNTS, "../../packages/fixtures:/build/packages/fixtures:ro"],
            "volumes are not exactly its mounts",
        ),
        ((*_DRIVE, "secrets"), ["cv_kek"], "does not set secrets on it"),
        ((*_DRIVE, _ENV, "CV_TEST_CLOCK"), "true", "CV_TEST_CLOCK"),
        ((*_DRIVE, _ENV, "CV_ENVIRONMENT"), "live", "'fixture-drive': CV_ENVIRONMENT is off"),
        ((*_DRIVE, "build"), {"context": "../..", "target": "runtime"}, "'fixture-drive': build"),
        ((*_DRIVE, "profiles"), None, "'fixture-drive': profiles is not [fixture-drive]"),
        (("services", "migrate"), {}, "service 'migrate'"),
        (("volumes",), {"cv-api-data": {"driver_opts": {"o": "bind"}}}, "top-level volumes"),
        (("networks",), {}, "top-level 'networks'"),
    ],
    ids=lambda p: p if isinstance(p, str) else None,
)
def test_rule_8_refuses(path: tuple[str, ...], value: object, why: str) -> None:
    errors = lint_compose.check_account_fixture_real_overlay(_mutated(path, value))
    assert any(why in error for error in errors), errors
    shown = "\n".join(errors)  # a value is never repeated
    assert all(v not in shown for v in ("inline-pepper", "198.51.100.7", "CV_BYBIT_API_KEY:-"))


def test_main_lints_the_real_overlay_by_rule_8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert lint_compose.main([str(OVERLAY_PATH)]) == 0
    broken = tmp_path / OVERLAY_PATH.name
    broken.write_text("services:\n  api:\n    entrypoint: [sh]\n", encoding="utf-8")
    assert lint_compose.main([str(broken)]) == 1
    monkeypatch.setattr(lint_compose, "ACCOUNT_FIXTURE_REAL_OVERLAY", broken)
    capsys.readouterr()
    assert lint_compose.main([]) == 1
    assert "not entrypoint" in capsys.readouterr().err
