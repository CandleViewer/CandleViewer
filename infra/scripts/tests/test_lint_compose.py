"""Tests for infra/scripts/lint_compose.py (E02-T08 acceptance criteria)."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lint_compose
from lint_compose import check_healthchecks, check_image_digests, check_port_bindings, lint

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "infra" / "compose" / "docker-compose.yml"
DEPLOY_OVERLAY_PATH = REPO_ROOT / "infra" / "compose" / "docker-compose.deploy.yml"
DEMO_HOST_PATH = REPO_ROOT / "infra" / "compose" / "docker-compose.demo-host.yml"
ENV_EXAMPLE = REPO_ROOT / "infra" / "compose" / ".env.example"
DOCKERFILE = REPO_ROOT / "infra" / "images" / "Dockerfile.api"
PINNED = "${CV_API_IMAGE_REF:?set by the deploy}@${CV_IMAGE_DIGEST:?set by the deploy}"
API = {"image": PINNED, "pull_policy": "always", "read_only": True}  # the accepted api


def test_committed_compose_file_passes_lint() -> None:
    errors = lint(COMPOSE_PATH)
    assert errors == []


def _overlay(**api: object) -> dict[str, object]:
    """A deploy overlay whose api service is `API` with `api`'s keys set (None drops one)."""
    service = {**API, **api}
    return {"services": {"api": {k: v for k, v in service.items() if v is not None}}}


def test_committed_deploy_overlay_passes_lint() -> None:
    assert lint_compose.lint(DEPLOY_OVERLAY_PATH, deploy_overlay=True) == []


@pytest.mark.parametrize("policy", ["always", "missing"])
def test_deploy_overlay_accepts_an_api_pinned_by_digest_with_a_pull_policy(policy: str) -> None:
    assert lint_compose.check_deploy_overlay(_overlay(pull_policy=policy)) == []


SOURCE_MOUNT = "../../services/api/candleviewer:/app/candleviewer:ro"
RELOAD = ["python", "-m", "candleviewer.server", "--reload"]


@pytest.mark.parametrize(
    ("overlay", "why"),
    [
        pytest.param(_overlay(build={"context": "../.."}), "builds locally", id="build"),
        pytest.param(_overlay(volumes=[SOURCE_MOUNT]), "mounts", id="source-mount"),
        pytest.param(_overlay(entrypoint=RELOAD), "--reload", id="reload-entrypoint"),
        pytest.param(_overlay(command=["--reload"]), "replaces the image's command", id="command"),
        pytest.param(_overlay(read_only=False), "read_only", id="writable-root"),
        pytest.param(_overlay(read_only=None), "read_only", id="no-read-only"),
        pytest.param(_overlay(image="ghcr.io/o/img:dev"), "not pinned", id="tag"),
        pytest.param(
            _overlay(image="${CV_API_IMAGE_REF}@${CV_IMAGE_DIGEST}"),
            "not pinned",
            id="variables-without-a-required-check",
        ),
        pytest.param(_overlay(pull_policy="build"), "pull_policy", id="pull-build"),
        pytest.param(_overlay(pull_policy="never"), "pull_policy", id="pull-never"),
        pytest.param(_overlay(pull_policy=None), "pull_policy", id="no-pull-policy"),
        pytest.param(_overlay(ports=["127.0.0.1:8000:8000"]), "ports", id="ports"),
        pytest.param({"services": {"api": API, "migrate": {}}}, "migrate", id="second-service"),
        pytest.param({**_overlay(), "networks": {"cv-internal": {}}}, "networks", id="networks"),
    ],
)
def test_deploy_overlay_lint_refuses(overlay: dict[str, object], why: str) -> None:
    errors = lint_compose.check_deploy_overlay(overlay)
    assert len(errors) == 1 and why in errors[0], errors


def test_main_without_arguments_also_lints_the_deploy_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "docker-compose.deploy.yml"
    broken.write_text("services:\n  api:\n    build: ../..\n", encoding="utf-8")
    monkeypatch.setattr(lint_compose, "DEPLOY_OVERLAY", broken)
    assert lint_compose.main([]) == 1
    assert "builds locally" in capsys.readouterr().err


def test_check_port_bindings_flags_wildcard_bind() -> None:
    compose = {"services": {"api": {"ports": ["0.0.0.0:8000:8000"]}}}
    errors = check_port_bindings(compose)
    assert len(errors) == 1
    assert "127.0.0.1" in errors[0]


def test_check_port_bindings_flags_bare_port_form() -> None:
    compose = {"services": {"api": {"ports": ["8000:8000"]}}}
    errors = check_port_bindings(compose)
    assert len(errors) == 1


def test_check_port_bindings_accepts_loopback_bind() -> None:
    compose = {"services": {"api": {"ports": ["127.0.0.1:8000:8000"]}}}
    assert check_port_bindings(compose) == []


def test_check_image_digests_flags_bare_tag() -> None:
    compose = {"services": {"postgres": {"image": "postgres:16"}}}
    errors = check_image_digests(compose)
    assert len(errors) == 1
    assert "digest" in errors[0]


def test_check_image_digests_flags_latest_tag() -> None:
    compose = {"services": {"postgres": {"image": "postgres:latest"}}}
    errors = check_image_digests(compose)
    assert len(errors) == 1


def test_check_image_digests_accepts_pinned_digest() -> None:
    compose = {
        "services": {
            "postgres": {"image": "postgres@sha256:" + "a" * 64},
        }
    }
    assert check_image_digests(compose) == []


def test_check_healthchecks_flags_missing_block() -> None:
    compose = {"services": {"api": {"image": "x@sha256:" + "a" * 64}}}
    errors = check_healthchecks(compose)
    assert len(errors) == 1
    assert "healthcheck" in errors[0]


def test_check_healthchecks_accepts_present_block() -> None:
    compose = {"services": {"api": {"healthcheck": {"test": ["CMD", "true"]}}}}
    assert check_healthchecks(compose) == []


def test_questdb_healthcheck_uses_tool_present_in_image() -> None:
    """Regression for #276: questdb/questdb's final stage is debian:bookworm-slim without
    curl/wget, so a curl probe exits 127 and the service is permanently `unhealthy`.
    The probe must use bash's /dev/tcp and the SQL /exec readiness path."""
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    health = compose["services"]["questdb"]["healthcheck"]
    test = health["test"]
    assert test[:3] == ["CMD", "bash", "-c"]
    script = test[3]
    assert "curl" not in script and "wget" not in script
    assert "/dev/tcp/127.0.0.1/9000" in script
    assert "/exec?query=select" in script
    assert "start_period" in health
    # api must still gate on questdb health (the CI work-around is gone).
    assert compose["services"]["api"]["depends_on"]["questdb"] == {"condition": "service_healthy"}


# --- rule 5 (every compose file): no environment carries a KEK -----------------------------------


def test_every_committed_compose_file_keeps_the_kek_out_of_its_environment() -> None:
    paths = sorted((REPO_ROOT / "infra" / "compose").glob("docker-compose*.yml"))
    assert DEMO_HOST_PATH in paths
    for path in paths:
        compose = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert lint_compose.check_no_kek_in_environment(compose) == [], path.name


@pytest.mark.parametrize(
    ("key", "value", "why"),
    [
        ("CV_KEK_VALUE", "${CV_KEK_VALUE:?x}", "names a KEK"),
        ("CV_KEK", "${CV_KEK:?x}", "names a KEK"),
        ("cv_kek_hex", "${CV_KEK_HEX:?x}", "names a KEK"),
        ("KEK_B64", "${KEK_B64:?x}", "names a KEK"),
        ("CV_KEK_SOURCE", "${CV_KEK_SOURCE:-file}", "is not file or handle"),
        ("CV_KEK_HANDLE", "/tmp/cv_kek", "is not a /run/secrets/ path"),
        ("CV_KEK_VERSION", "0x2a", "is not an integer"),
        ("CV_SEED_HEX", "0" * 64, "inline key material"),
        ("CV_SEED", "A" * 43, "inline key material"),
    ],
    ids=["value-name", "bare-name", "lowercase", "other-prefix", "source-default", "handle-path",
         "version-hex", "hex-literal", "base64-literal"],
)  # fmt: skip
@pytest.mark.parametrize("form", ["mapping", "list"])
def test_no_compose_environment_may_carry_a_kek(key: str, value: str, why: str, form: str) -> None:
    environment: object = {key: value} if form == "mapping" else [f"{key}={value}"]
    compose = {"services": {"x": {"environment": environment}}}
    errors = lint_compose.check_no_kek_in_environment(compose)
    assert len(errors) == 1 and why in errors[0], errors
    assert value not in errors[0]  # a message names the setting, never its value


# --- rule 6: the demo-host overlay ---------------------------------------------------------------

#: The names the demo host's infra/compose/.env was provisioned with (#3180, 2026-10-25).
HOST_NAMES = {
    "CV_STORAGE_BACKEND", "CV_EGRESS_IP", "CV_KEK_FILE", "CV_KEK_VERSION", "CV_AUTH_PEPPER",
    "CV_AUTH_CSRF_KEY_HEX", "CV_AUTH_TOTP_KEY_HEX", "CV_AUTH_RECOVERY_HMAC_KEY_HEX",
    "CV_MESH_CIDRS_CSV", "CV_ALLOWED_ORIGINS", "CV_AUDIT_LANE_MAC_SOURCE", "CV_PG_OWNER_DSN",
}  # fmt: skip
#: Of those, the ones whose committed placeholder is blank (unset): a secret, a path or an address.
BLANK = HOST_NAMES - {"CV_KEK_VERSION", "CV_MESH_CIDRS_CSV"}


def _demo_host(path: str = "", value: object = None) -> dict[str, Any]:
    """The committed demo-host overlay, with the node at a dotted `path` set (None deletes it)."""
    doc: dict[str, Any] = yaml.safe_load(DEMO_HOST_PATH.read_text(encoding="utf-8"))
    if path:
        *parents, leaf = path.split(".")
        node = doc
        for name in parents:
            node = node[name]
        if value is None:
            del node[leaf]
        else:
            node[leaf] = value
    return doc


def test_committed_demo_host_overlay_passes_lint() -> None:
    assert lint_compose.lint(DEMO_HOST_PATH, demo_host_overlay=True) == []


def test_the_demo_host_overlay_reads_the_names_the_host_was_provisioned_with() -> None:
    """And the two `bootstrap-owner` shares with the base file's api, which `.env.example` held."""
    read = re.findall(r"\$\{([A-Z][A-Z0-9_]*)", DEMO_HOST_PATH.read_text(encoding="utf-8"))
    assert set(read) == HOST_NAMES | {"CV_ENVIRONMENT", "CV_PG_DSN"}


def test_env_example_lists_every_one_and_leaves_the_sensitive_ones_blank() -> None:
    example = "\n" + ENV_EXAMPLE.read_text(encoding="utf-8")
    assert HOST_NAMES <= set(re.findall(r"^([A-Z][A-Z0-9_]*)=", example, re.MULTILINE))
    assert [name for name in sorted(BLANK) if f"\n{name}=\n" not in example] == []


ENV = "services.api.environment"
KEK_MOUNT = {"source": "cv_kek", "target": "cv_kek", "uid": "10001", "gid": "10001", "mode": 0o400}


@pytest.mark.parametrize(
    ("path", "value", "why"),
    [
        ("services.postgres", {"image": "postgres"}, "touches only api, migrate and bootstrap"),
        ("networks", {"cv-internal": {}}, "top-level 'networks'"),
        ("services.api.build", {"context": "../.."}, "build is not set by the demo-host overlay"),
        ("services.api.read_only", False, "read_only is not set by the demo-host overlay"),
        ("services.migrate.entrypoint", ["sh"], "entrypoint is not set by the demo-host overlay"),
        ("services.api.ports", ["0.0.0.0:8000:8000"], "not explicitly bound to 127.0.0.1"),
        ("services.api.ports", ["8000:8000"], "not explicitly bound to 127.0.0.1"),
        (f"{ENV}.CV_AUTH_PEPPER", "pepper-in-the-repo", "CV_AUTH_PEPPER is committed here"),
        (f"{ENV}.CV_EGRESS_IP", "${CV_EGRESS_IP:-unset}", "CV_EGRESS_IP is committed here"),
        (f"{ENV}.CV_KEK_HANDLE", "/run/secrets/other", "CV_KEK_HANDLE is not /run/secrets/cv_kek"),
        (f"{ENV}.CV_KEK_HANDLE", None, "CV_KEK_HANDLE is not /run/secrets/cv_kek"),
        ("secrets.cv_kek", {"file": "${CV_KEK_FILE:-/etc/kek.bin}"}, "secret 'cv_kek' is not"),
        ("secrets.cv_kek", {"file": "${CV_KEK_FILE}"}, "secret 'cv_kek' is not"),
        ("secrets.cv_kek", {"file": "./kek.bin"}, "secret 'cv_kek' is not"),
        ("secrets.cv_kek", {"environment": "CV_KEK_FILE"}, "secret 'cv_kek' is not"),
        ("secrets.cv_kek", None, "secret 'cv_kek' is not"),
        ("services.api.secrets", [KEK_MOUNT | {"mode": 0o444}], "does not mount cv_kek"),
        ("services.api.secrets", [KEK_MOUNT | {"uid": "0"}], "does not mount cv_kek"),
        ("services.api.secrets", [KEK_MOUNT, KEK_MOUNT], "does not mount cv_kek"),
        ("services.api.secrets", None, "does not mount cv_kek"),
        ("services.api.ulimits", {"core": -1}, "ulimits.core"),
        ("services.api.ulimits", None, "ulimits.core"),
        ("services.api.volumes", ["/srv/cv-data:/data"], "never a bind mount"),
        ("services.api.volumes", [{"type": "bind", "source": "/srv", "target": "/data"}], "never"),
        ("services.api.volumes", ["undeclared:/data"], "this file declares"),
        ("services.api.volumes", ["cv-api-data:/data", "/etc/candleviewer:/x:ro"], "alone"),
        ("services.api.volumes", None, "alone"),
        ("services.migrate.environment.CV_PG_DSN", "${CV_PG_DSN:?x}", "CV_PG_DSN is not"),
        (f"{ENV}.CV_PG_OWNER_DSN", "${CV_PG_OWNER_DSN:?x}", "only migrate may"),
    ],
    ids=["other-service", "top-level-key", "api-build", "api-writable-root", "migrate-entrypoint",
         "wildcard-port", "bare-port", "committed-secret", "committed-default", "other-handle",
         "no-handle", "kek-file-default", "kek-file-optional", "kek-file-literal",
         "kek-environment-secret", "no-kek-secret", "kek-mode-0444", "kek-uid-0", "kek-twice",
         "kek-not-mounted", "core-unlimited", "no-ulimits", "data-bind", "data-bind-long",
         "data-undeclared", "extra-bind", "no-data", "migrate-app-dsn", "api-owner-dsn"],
)  # fmt: skip
def test_demo_host_overlay_lint_refuses(path: str, value: object, why: str) -> None:
    errors = lint_compose.check_demo_host_overlay(_demo_host(path, value))
    assert any(why in error for error in errors), errors


# DC-4479-02: #4479's CLI prints the Owner's invite token once; it runs in its own service, whose
# output no logging driver keeps, never as `run ... api`.
BOOT = "services.bootstrap-owner"
LANE_MOUNT = KEK_MOUNT | {"source": "cv_audit_lane_key", "target": "cv_audit_lane_key"}


def test_the_bootstrap_owner_service_is_cvapis_twin_for_the_cli_and_logs_nothing() -> None:
    boot = _demo_host()["services"]["bootstrap-owner"]
    assert boot["logging"] == {"driver": "none"} and boot["profiles"] == ["bootstrap-owner"]
    assert boot["entrypoint"] == ["python", "-m", "candleviewer.bootstrap_owner"]
    assert "ports" not in boot and boot["secrets"] == [KEK_MOUNT, LANE_MOUNT]
    # cv-api's database role (the CLI's probe looks for its other sessions), never the owner's
    assert boot["environment"]["CV_PG_DSN"].startswith("${CV_PG_DSN:?")


@pytest.mark.parametrize(
    ("path", "value", "why"),
    [
        (BOOT, None, "service 'bootstrap-owner' is missing"),
        (f"{BOOT}.logging", {"driver": "json-file"}, "logging is not {driver: none}"),
        (f"{BOOT}.logging", None, "logging is not {driver: none}"),
        (f"{BOOT}.profiles", None, "profiles is not [bootstrap-owner]"),
        (f"{BOOT}.profiles", ["core"], "profiles is not [bootstrap-owner]"),
        (f"{BOOT}.ports", ["127.0.0.1:8001:8000"], "ports is not set by the demo-host overlay"),
        (f"{BOOT}.entrypoint", ["python", "-m", "candleviewer.server"], "entrypoint is not"),
        (f"{BOOT}.entrypoint", None, "entrypoint is not"),
        (f"{BOOT}.command", ["--owner", "owner@example.invalid"], "command is not set"),
        (f"{BOOT}.secrets", [KEK_MOUNT, LANE_MOUNT, {"source": "alert_deadman_url"}],
         "a secret that is not one of the api's"),
        (f"{BOOT}.secrets", [KEK_MOUNT | {"mode": 0o444}], "a secret that is not one of the api's"),
        (f"{BOOT}.secrets", [LANE_MOUNT], "a secret that is not one of the api's"),
        (f"{BOOT}.build", {"context": "../..", "dockerfile": "x"}, "the api's image from this"),
        (f"{BOOT}.pull_policy", "missing", "the api's image from this checkout"),
        (f"{BOOT}.read_only", False, "read_only is not true"),
        (f"{BOOT}.ulimits", None, "ulimits.core"),
        (f"{BOOT}.volumes", ["/srv/audit:/var/lib/candleviewer/audit"], "the audit volume alone"),
        (f"{BOOT}.volumes", None, "the audit volume alone"),
        (f"{BOOT}.environment.CV_PG_DSN", "${CV_PG_OWNER_DSN:?x}", "only migrate may"),
        (f"{BOOT}.environment.CV_PG_DSN", "postgresql+asyncpg://postgres/cv", "committed here"),
    ],
    ids=["missing", "json-file-log", "no-logging", "no-profile", "core-profile", "port",
         "server-entrypoint", "no-entrypoint", "command", "foreign-secret", "kek-mode-0444",
         "no-kek", "other-dockerfile", "pulled-image", "writable-root", "no-ulimits",
         "audit-bind", "no-audit-volume", "owner-dsn", "committed-dsn"],
)  # fmt: skip
def test_demo_host_overlay_lint_refuses_a_bootstrap_owner_that(
    path: str, value: object, why: str
) -> None:
    errors = lint_compose.check_demo_host_overlay(_demo_host(path, value))
    assert any(why in error for error in errors), errors


def test_main_without_arguments_also_lints_the_demo_host_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "docker-compose.demo-host.yml"
    broken.write_text("services:\n  api:\n    privileged: true\n", encoding="utf-8")
    monkeypatch.setattr(lint_compose, "DEMO_HOST_OVERLAY", broken)
    assert lint_compose.main([]) == 1
    assert "privileged is not set by the demo-host overlay" in capsys.readouterr().err


def test_main_without_arguments_reads_every_compose_file_for_a_kek(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    extra = tmp_path / "docker-compose.extra.yml"
    extra.write_text("services:\n  api:\n    environment:\n      CV_KEK_VALUE: x\n", "utf-8")
    monkeypatch.setattr(lint_compose, "COMPOSE_DIR", tmp_path)
    assert lint_compose.main([]) == 1
    assert "docker-compose.extra.yml: service 'api': environment CV_KEK_VALUE names a KEK" in (
        capsys.readouterr().err
    )


def test_the_image_seeds_the_data_volume_for_its_runtime_user() -> None:
    """The overlay's /data is a named volume, which Docker fills from the image's /data on first
    mount: the runtime stage creates /data/parquet (the cold tier's root, which the real backend
    never creates) owned by uid 10001, as it does the audit directory, before `USER`."""
    stage = DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ").split("\nFROM ")[-1]
    run = next(line for line in stage.splitlines() if line.startswith("RUN mkdir -p /data/"))
    assert "mkdir -p /data/parquet" in run and "chown -R 10001:10001 /data" in run
    assert "chmod 0700 /data /data/parquet" in run
    assert stage.index(run) < stage.index("\nUSER 10001:10001")
