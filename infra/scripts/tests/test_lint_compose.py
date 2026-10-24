"""Tests for infra/scripts/lint_compose.py (E02-T08 acceptance criteria)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lint_compose
from lint_compose import check_healthchecks, check_image_digests, check_port_bindings, lint

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "infra" / "compose" / "docker-compose.yml"
DEPLOY_OVERLAY_PATH = REPO_ROOT / "infra" / "compose" / "docker-compose.deploy.yml"
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
    import yaml

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
