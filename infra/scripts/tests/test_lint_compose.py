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


@pytest.mark.parametrize(
    ("value", "flagged"),
    [("0" * 32, True), ("g" * 43, True), ("0" * 31, False), ("g" * 42, False)],
    ids=["hex-32", "base64-43", "hex-31", "base64-42"],
)
def test_rule_5_reads_key_material_from_32_hex_digits_or_43_base64_characters(
    value: str, flagged: bool
) -> None:
    """16 bytes written as hex, or 32 as unpadded base64; one character fewer is no key."""
    compose = {"services": {"x": {"environment": {"CV_SEED": value}}}}
    assert bool(lint_compose.check_no_kek_in_environment(compose)) is flagged


def test_lint_applies_rule_5_to_the_file_it_reads(tmp_path: Path) -> None:
    base = tmp_path / "docker-compose.yml"
    base.write_text(
        "services:\n  api:\n    healthcheck: {test: [CMD, 'true']}\n"
        "    environment:\n      CV_KEK_VALUE: x\n",
        encoding="utf-8",
    )
    assert any("environment CV_KEK_VALUE names a KEK" in error for error in lint(base))


#: A secret from the environment, mounted where cv-api reads its KEK (the M1 probes).
ENV_KEK = {"cv_kek_hex": {"environment": "CV_KEK_HEX"}}
NEUTRAL = {"master": {"environment": "CV_MASTER"}}  # a name and a variable that hold no KEK
FILE_KEK = {"cv_kek": {"file": "${CV_KEK_FILE:?x}"}}
KEK_ENV = {"CV_KEK_SOURCE": "file", "CV_KEK_HANDLE": "/run/secrets/master", "CV_KEK_VERSION": "1"}


def _with_secrets(declared: dict[str, Any], service: dict[str, Any]) -> dict[str, Any]:
    return {"secrets": declared, "services": {"api": service}}


@pytest.mark.parametrize(
    ("compose", "why"),
    [
        (_with_secrets(ENV_KEK, {"secrets": ["cv_kek_hex"]}), "secret 'cv_kek_hex'"),
        (_with_secrets({"master": {"environment": "CV_KEK_HEX"}}, {}), "secret 'master'"),
        (_with_secrets({"cv_kek": {"environment": "CV_MASTER"}}, {}), "secret 'cv_kek'"),
        (_with_secrets(NEUTRAL, {"environment": KEK_ENV, "secrets": ["master"]}),
         "mounts its KEK from secret 'master'"),
        (_with_secrets(NEUTRAL, {"secrets": [{"source": "master", "target": "cv_kek"}]}),
         "mounts its KEK from secret 'master'"),
        (_with_secrets({"old": {"environment": "CV_OLD"}},
                       {"environment": {"CV_KEK_PREV_HANDLE": "/run/secrets/old"},
                        "secrets": ["old"]}), "mounts its KEK from secret 'old'"),
        (_with_secrets(FILE_KEK, {"environment": {"CV_KEK_HANDLE": "/run/secrets/elsewhere"}}),
         "CV_KEK_HANDLE names a /run/secrets/ file this file does not mount"),
        (_with_secrets({"cv_owner_dsn": {"environment": "CV_PG_OWNER_DSN"}},
                       {"secrets": ["cv_owner_dsn"]}), "the owner role's DSN"),
        (_with_secrets({"db": {"environment": "CV_PG_OWNER_DSN"}}, {}), "the owner role's DSN"),
    ],
    ids=["kek-secret-mounted", "kek-variable", "kek-name", "handle-from-environment",
         "default-handle-from-environment", "previous-handle-from-environment",
         "handle-not-mounted", "owner-dsn-secret", "owner-dsn-variable"],
)  # fmt: skip
def test_rule_5_takes_a_kek_from_a_file_secret_only(compose: dict[str, Any], why: str) -> None:
    """e27-kek.md §3: a secret from the environment puts the key back in `.env` (M1). The secret
    behind a KEK handle is a file this file declares; the owner DSN never comes as a secret. No
    message repeats a handle or a mount target, which are values."""
    errors = lint_compose.check_no_kek_in_environment(compose)
    assert any(why in error for error in errors), errors
    assert not any("elsewhere" in error for error in errors)


@pytest.mark.parametrize(
    "compose",
    [
        {"secrets": {"alert_deadman_url": {"environment": "CV_ALERT_DEADMAN_URL"}},
         "services": {"alertmanager": {"secrets": ["alert_deadman_url"]}}},
        _with_secrets(FILE_KEK, {"environment": {**KEK_ENV, "CV_KEK_HANDLE": "/run/secrets/cv_kek"},
                                 "secrets": ["cv_kek"]}),
    ],
    ids=["base-webhook-secret", "file-kek-at-its-handle"],
)  # fmt: skip
def test_rule_5_keeps_a_secret_from_the_environment_that_holds_no_kek(
    compose: dict[str, Any],
) -> None:
    assert lint_compose.check_no_kek_in_environment(compose) == []


HEX_64 = "0" * 64


@pytest.mark.parametrize(
    ("compose", "why"),
    [
        ({"services": {"x": {"labels": {"cv.kek": "x"}}}}, "label cv.kek names a KEK"),
        ({"services": {"x": {"labels": [f"seed={HEX_64}"]}}}, "label seed holds inline key"),
        ({"services": {"x": {"build": {"context": ".", "args": {"KEK_HEX": "x"}}}}},
         "build arg KEK_HEX names a KEK"),
        ({"services": {"x": {"build": {"context": ".", "args": [f"SEED={HEX_64}"]}}}},
         "build arg SEED holds inline key"),
        ({"x-defaults": {"environment": {"CV_KEK_VALUE": "x"}}}, "CV_KEK_VALUE names a KEK"),
        ({"x-seed": HEX_64}, "x-seed holds inline key"),
        ({"services": {"x": {"x-env": [f"CV_KEK={HEX_64}"]}}}, "CV_KEK names a KEK"),
    ],
    ids=["label-name", "label-material", "build-arg-name", "build-arg-material",
         "extension-name", "extension-material", "service-extension"],
)  # fmt: skip
def test_rule_5_reads_labels_build_args_and_extensions_too(
    compose: dict[str, Any], why: str
) -> None:
    errors = lint_compose.check_no_kek_in_environment(compose)
    assert any(why in error for error in errors), errors
    assert not any(HEX_64 in error for error in errors)


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
    """And the two every overlay command needs, which `bootstrap-owner` requires with `:?`."""
    example = "\n" + ENV_EXAMPLE.read_text(encoding="utf-8")
    listed = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", example, re.MULTILINE))
    assert HOST_NAMES | {"CV_ENVIRONMENT", "CV_PG_DSN"} <= listed
    assert [name for name in sorted(BLANK) if f"\n{name}=\n" not in example] == []


ENV = "services.api.environment"
KEK_MOUNT = {"source": "cv_kek", "target": "cv_kek", "uid": "10001", "gid": "10001", "mode": 0o400}
LANE_MOUNT = KEK_MOUNT | {"source": "cv_audit_lane_key", "target": "cv_audit_lane_key"}
BIND = {"type": "none", "o": "bind", "device": "/srv/cv-data"}  # a host bind in disguise (L3)


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
        (f"{ENV}.CV_AUTH_PEPPER", "${CV_AUTH_PEPPER:-}", "CV_AUTH_PEPPER is committed here"),
        (f"{ENV}.CV_EGRESS_IP", "${CV_EGRESS_IP:-}", "CV_EGRESS_IP is committed here"),
        (f"{ENV}.CV_STORAGE_BACKEND", "${CV_STORAGE_BACKEND:-}", "CV_STORAGE_BACKEND is committed"),
        (f"{ENV}.CV_MESH_CIDRS_CSV", "${CV_MESH_CIDRS_CSV:-}", "CV_MESH_CIDRS_CSV is committed"),
        (f"{ENV}.CV_AUTH_CSRF_KEY_HEX", "${CV_AUTH_TOTP_KEY_HEX:?x}",
         "CV_AUTH_CSRF_KEY_HEX is committed here"),
        (f"{ENV}.CV_KEK_HANDLE", "/run/secrets/other", "CV_KEK_HANDLE is not /run/secrets/cv_kek"),
        (f"{ENV}.CV_KEK_HANDLE", None, "CV_KEK_HANDLE is not /run/secrets/cv_kek"),
        ("secrets.cv_kek", {"file": "${CV_KEK_FILE:-/etc/kek.bin}"}, "secret 'cv_kek' is not"),
        ("secrets.cv_kek", {"file": "${CV_KEK_FILE}"}, "secret 'cv_kek' is not"),
        ("secrets.cv_kek", {"file": "./kek.bin"}, "secret 'cv_kek' is not"),
        ("secrets.cv_kek", {"environment": "CV_KEK_FILE"}, "secret 'cv_kek' is not"),
        ("secrets.cv_kek", None, "secret 'cv_kek' is not"),
        ("secrets.cv_audit_lane_key", {"file": "${CV_AUDIT_LANE_MAC_SOURCE:-/dev/null}"},
         "secret 'cv_audit_lane_key' is not"),
        ("secrets.cv_audit_lane_key", None, "secret 'cv_audit_lane_key' is not"),
        ("secrets.cv_kek_hex", {"environment": "CV_KEK_HEX"}, "declares only cv_kek and"),
        ("secrets.cv_owner_dsn", {"environment": "CV_PG_OWNER_DSN"}, "declares only cv_kek and"),
        ("services.api.secrets", [KEK_MOUNT | {"mode": 0o444}], "does not mount cv_kek"),
        ("services.api.secrets", [KEK_MOUNT | {"uid": "0"}], "does not mount cv_kek"),
        ("services.api.secrets", [KEK_MOUNT, KEK_MOUNT], "does not mount cv_kek"),
        ("services.api.secrets", None, "does not mount cv_kek"),
        ("services.api.secrets", [KEK_MOUNT, {"source": "cv_kek_hex"}], "mounts a secret that"),
        ("services.api.secrets", [KEK_MOUNT, {"source": "cv_kek_hex", "target": "cv_kek"}],
         "mounts a secret that"),
        ("services.api.secrets", [KEK_MOUNT, LANE_MOUNT | {"mode": 0o444}], "mounts a secret that"),
        ("services.api.ulimits", {"core": -1}, "ulimits.core"),
        ("services.api.ulimits", None, "ulimits.core"),
        ("services.api.volumes", ["/srv/cv-data:/data"], "never a bind mount"),
        ("services.api.volumes", [{"type": "bind", "source": "/srv", "target": "/data"}], "never"),
        ("services.api.volumes", ["undeclared:/data"], "this file declares"),
        ("services.api.volumes", ["cv-api-data:/data", "/etc/candleviewer:/x:ro"], "alone"),
        ("services.api.volumes", None, "alone"),
        ("volumes.cv-api-data", {"driver_opts": BIND}, "not cv-api-data alone with no option"),
        ("volumes.cv-api-data", {"driver": "local"}, "not cv-api-data alone with no option"),
        ("volumes.cv-api-data", {"external": True}, "not cv-api-data alone with no option"),
        ("volumes.cv-audit-data", {"driver_opts": BIND}, "not cv-api-data alone with no option"),
        ("services.migrate.environment.CV_PG_DSN", "${CV_PG_DSN:?x}", "CV_PG_DSN is not"),
        (f"{ENV}.CV_PG_OWNER_DSN", "${CV_PG_OWNER_DSN:?x}", "only migrate may"),
    ],
    ids=["other-service", "top-level-key", "api-build", "api-writable-root", "migrate-entrypoint",
         "wildcard-port", "bare-port", "committed-secret", "committed-default",
         "pepper-may-be-empty", "egress-may-be-empty", "backend-may-be-empty", "mesh-may-be-empty",
         "swapped-variable", "other-handle", "no-handle", "kek-file-default", "kek-file-optional",
         "kek-file-literal", "kek-environment-secret", "no-kek-secret", "lane-key-default",
         "no-lane-key", "extra-kek-secret", "owner-dsn-secret", "kek-mode-0444", "kek-uid-0",
         "kek-twice", "kek-not-mounted", "api-extra-secret", "api-secret-onto-the-handle",
         "api-lane-mode-0444", "core-unlimited", "no-ulimits", "data-bind", "data-bind-long",
         "data-undeclared", "extra-bind", "no-data", "data-driver-opts", "data-driver",
         "data-external", "audit-volume-redeclared", "migrate-app-dsn", "api-owner-dsn"],
)  # fmt: skip
def test_demo_host_overlay_lint_refuses(path: str, value: object, why: str) -> None:
    errors = lint_compose.check_demo_host_overlay(_demo_host(path, value))
    assert any(why in error for error in errors), errors


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("services.api.secrets", [KEK_MOUNT, LANE_MOUNT]),
        (f"{ENV}.CV_ALLOWED_ORIGINS", "${CV_ALLOWED_ORIGINS:?x}"),
        ("volumes.cv-api-data", {}),
    ],
    ids=["api-restates-the-lane-key", "origins-required", "data-volume-empty-mapping"],
)
def test_demo_host_overlay_lint_accepts(path: str, value: object) -> None:
    """api reads the base file's lane key, so the overlay may restate that mount exactly."""
    assert lint_compose.check_demo_host_overlay(_demo_host(path, value)) == []


# DC-4479-02: #4479's CLI prints the Owner's invite token once; it runs in its own service, whose
# output no logging driver keeps, never as `run ... api`.
BOOT = "services.bootstrap-owner"
#: The orchestrator's ruling (b): what the CLI reads, and nothing else (no lane key, no egress
#: address, no auth keys).
BOOT_ENV = {"CV_ENVIRONMENT", "CV_PG_DSN", "CV_KEK_SOURCE", "CV_KEK_HANDLE", "CV_KEK_VERSION",
            "CV_AUDIT_WAL_PATH"}  # fmt: skip


def test_the_bootstrap_owner_service_is_cvapis_twin_for_the_cli_and_logs_nothing() -> None:
    boot = _demo_host()["services"]["bootstrap-owner"]
    assert boot["logging"] == {"driver": "none"} and boot["profiles"] == ["bootstrap-owner"]
    assert boot["entrypoint"] == ["python", "-m", "candleviewer.bootstrap_owner"]
    assert "ports" not in boot and boot["secrets"] == [KEK_MOUNT]
    assert set(boot["environment"]) == BOOT_ENV
    # cv-api's database role (the CLI's probe looks for its other sessions), never the owner's
    assert boot["environment"]["CV_PG_DSN"].startswith("${CV_PG_DSN:?")


def test_the_bootstrap_shares_cv_apis_audit_wal_on_its_volume() -> None:
    """The CLI's journal and the run lock it shares with cv-api sit beside cv-api's audit WAL:
    one path (absolute, no `..`) on the one volume both mount (vw2)."""
    api = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))["services"]["api"]
    boot = _demo_host()["services"]["bootstrap-owner"]
    wal = api["environment"]["CV_AUDIT_WAL_PATH"]
    assert boot["environment"]["CV_AUDIT_WAL_PATH"] == wal == f"{lint_compose.AUDIT_DIR}/audit.wal"
    assert wal.startswith("/") and ".." not in wal.split("/")
    mount = f"cv-audit-data:{wal.rpartition('/')[0]}"
    assert mount in api["volumes"] and boot["volumes"] == [mount]


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
         "mounts a secret that is not"),
        (f"{BOOT}.secrets", [KEK_MOUNT | {"mode": 0o444}], "mounts a secret that is not"),
        (f"{BOOT}.secrets", [LANE_MOUNT], "mounts a secret that is not"),
        (f"{BOOT}.secrets", [KEK_MOUNT, LANE_MOUNT], "mounts a secret that is not"),
        (f"{BOOT}.build", {"context": "../..", "dockerfile": "x"}, "the api's image from this"),
        (f"{BOOT}.pull_policy", "missing", "the api's image from this checkout"),
        (f"{BOOT}.read_only", False, "read_only is not true"),
        (f"{BOOT}.ulimits", None, "ulimits.core"),
        (f"{BOOT}.volumes", ["/srv/audit:/var/lib/candleviewer/audit"], "the audit volume alone"),
        (f"{BOOT}.volumes", ["cv-other:/var/lib/candleviewer/audit"], "the audit volume alone"),
        (f"{BOOT}.volumes", None, "the audit volume alone"),
        (f"{BOOT}.environment.CV_PG_DSN", "${CV_PG_OWNER_DSN:?x}", "only migrate may"),
        (f"{BOOT}.environment.CV_PG_DSN", "postgresql+asyncpg://postgres/cv", "committed here"),
        (f"{BOOT}.environment.CV_AUTH_PEPPER", "${CV_AUTH_PEPPER:?x}", "environment is not"),
        (f"{BOOT}.environment.CV_EGRESS_IP", "${CV_EGRESS_IP:?x}", "environment is not"),
        (f"{BOOT}.environment.CV_KEK_VERSION", None, "environment is not"),
        (f"{BOOT}.environment.CV_AUDIT_WAL_PATH", "${CV_AUDIT_WAL_PATH:?x}",
         "CV_AUDIT_WAL_PATH is not cv-api's"),
    ],
    ids=["missing", "json-file-log", "no-logging", "no-profile", "core-profile", "port",
         "server-entrypoint", "no-entrypoint", "command", "foreign-secret", "kek-mode-0444",
         "no-kek", "lane-key", "other-dockerfile", "pulled-image", "writable-root", "no-ulimits",
         "audit-bind", "other-audit-volume", "no-audit-volume", "owner-dsn", "committed-dsn",
         "auth-pepper", "egress-address", "no-kek-version", "own-wal-path"],
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


def test_main_lints_a_named_overlay_by_its_own_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """N1: `lint_compose.py <file>` applies rule 4 or rule 6 when the name is an overlay's."""
    assert lint_compose.main([str(DEMO_HOST_PATH)]) == 0
    assert lint_compose.main([str(DEPLOY_OVERLAY_PATH)]) == 0
    broken = tmp_path / "docker-compose.demo-host.yml"
    broken.write_text("services:\n  api:\n    privileged: true\n", encoding="utf-8")
    assert lint_compose.main([str(broken)]) == 1
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
