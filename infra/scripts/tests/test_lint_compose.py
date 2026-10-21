"""Tests for infra/scripts/lint_compose.py (E02-T08 acceptance criteria)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lint_compose import check_healthchecks, check_image_digests, check_port_bindings, lint

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = REPO_ROOT / "infra" / "compose" / "docker-compose.yml"


def test_committed_compose_file_passes_lint() -> None:
    errors = lint(COMPOSE_PATH)
    assert errors == []


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


def test_postgres_logs_an_error_without_its_row_values() -> None:
    """#2748 (C-12.6, C-5.9): the server log keeps an error's message, not its DETAIL (`Failing
    row contains (...)`, `Key (col)=(val)`) nor its bound parameters. The base file is the one the
    dev stack and the VPS deploy both extend, and neither override sets the command."""
    import yaml

    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    command = compose["services"]["postgres"]["command"]
    assert command[0] == "postgres"
    flags, values = command[1::2], command[2::2]
    assert len(flags) == len(values) and set(flags) == {"-c"}
    settings = dict(value.split("=", 1) for value in values)
    assert settings["log_error_verbosity"] == "terse"
    assert settings["log_parameter_max_length_on_error"] == "0"
    for override in ("docker-compose.dev.yml", "docker-compose.vps.yml"):
        layer = yaml.safe_load((COMPOSE_PATH.parent / override).read_text(encoding="utf-8"))
        assert "command" not in (layer.get("services") or {}).get("postgres", {})
