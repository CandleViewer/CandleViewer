"""#2893 S14: the account fixture compose override (ADR-0036, Enforcement "Compose (S14)").

`infra/compose/docker-compose.account-fixture.yml` arms the dev-only fixture on the demo stub
stack. These tests hold it to its rules, statically, with no Docker and no network: it builds the
builder stage only and names no image, it is demo and synthetic only with no exchange key or test
clock, it is opt-in (no default compose path reads it), and it keeps the app's own entrypoint, so
the S8 boot guard still runs first. `lint_compose.py` rule 7 is the CI form of the same shape.
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

REPO: Final = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "infra" / "scripts"))

import lint_compose  # noqa: E402  (after the path insert, as test_deploy_dev.py does)

COMPOSE: Final = REPO / "infra" / "compose"
OVERLAY_PATH: Final = COMPOSE / "docker-compose.account-fixture.yml"
OVERLAY: Final[dict[str, Any]] = yaml.safe_load(OVERLAY_PATH.read_text(encoding="utf-8"))
API: Final[dict[str, Any]] = OVERLAY["services"]["api"]
#: The compose files a default stack reads (AGENTS.md section 4, `make up`).
DEFAULT_PATHS: Final = (
    REPO / "infra" / "docker-compose.dev.yml",
    COMPOSE / "docker-compose.yml",
    COMPOSE / "docker-compose.dev.yml",
)


def test_the_overlay_passes_rule_7() -> None:
    assert lint_compose.lint(OVERLAY_PATH, account_fixture_overlay=True) == []


def test_it_builds_the_builder_stage_only_and_names_no_image() -> None:
    assert API["build"] == {"target": "builder"}
    assert all("image" not in service for service in OVERLAY["services"].values())


def test_it_arms_the_fixture_on_demo_and_the_synthetic_feed_only() -> None:
    env = API["environment"]
    assert (env["CV_ENVIRONMENT"], env["CV_FEED"]) == ("demo", "synthetic")
    assert re.fullmatch(r"\$\{CV_ACCOUNT_FIXTURE:-[a-z0-9_]{1,64}\}", env["CV_ACCOUNT_FIXTURE"])
    state = Path(env["CV_ACCOUNT_FIXTURE_DIR"])
    assert state.is_absolute() and ".." not in state.parts


def test_it_carries_no_exchange_key_test_clock_or_env_file() -> None:
    text = yaml.safe_dump(OVERLAY)  # the parsed file: its header comment names what it omits
    assert "CV_BYBIT_API_" not in text and "CV_TEST_CLOCK" not in text
    assert "env_file" not in API and "secrets" not in API and "secrets" not in OVERLAY


def test_it_keeps_the_apps_entrypoint_so_the_boot_guard_runs_first() -> None:
    """The S8 guard runs in the app's lifespan before any module starts; an overlay that replaced
    the entrypoint or command could start something else first."""
    assert {"entrypoint", "command"}.isdisjoint(API)


def test_cvdev_and_the_fixtures_package_are_mounted_read_only_under_the_working_directory() -> None:
    mounts = {m.split(":")[1]: m for m in API["volumes"]}
    workdir = API["working_dir"]
    assert mounts[f"{workdir}/cvdev"].endswith(":ro")
    assert mounts[f"{workdir}/packages/fixtures"].endswith(":ro")  # pack.PACK_ROOT's parent
    state = API["environment"]["CV_ACCOUNT_FIXTURE_DIR"]
    assert mounts[state] == f"{lint_compose.FIXTURE_VOLUME}:{state}"  # a volume, not a host path


def test_it_publishes_no_port() -> None:
    assert all("ports" not in service for service in OVERLAY["services"].values())


def test_the_override_is_opt_in() -> None:
    """No default compose path reads it or arms the fixture."""
    for path in DEFAULT_PATHS:
        text = path.read_text(encoding="utf-8")
        assert "account-fixture" not in text and "CV_ACCOUNT_FIXTURE" not in text, path.name


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


_ENV = ("services", "api", "environment")


@pytest.mark.parametrize(
    ("path", "value", "why"),
    [
        (("services", "api", "image"), "ghcr.io/o/img@sha256:" + "a" * 64, "not image"),
        (("services", "api", "build"), {"target": "runtime"}, "build is not target: builder"),
        (("services", "api", "build"), None, "build is not target: builder"),
        ((*_ENV, "CV_ENVIRONMENT"), "live", "CV_ENVIRONMENT is off rule 7"),
        ((*_ENV, "CV_FEED"), "bybit", "CV_FEED is off rule 7"),
        ((*_ENV, "CV_BYBIT_API_KEY"), "${CV_BYBIT_API_KEY:-}", "CV_BYBIT_API_KEY"),
        ((*_ENV, "CV_TEST_CLOCK"), "true", "CV_TEST_CLOCK"),
        ((*_ENV, "CV_ACCOUNT_FIXTURE_DIR"), "state", "CV_ACCOUNT_FIXTURE_DIR is off rule 7"),
        ((*_ENV, "CV_ACCOUNT_FIXTURE"), "../x", "CV_ACCOUNT_FIXTURE is off rule 7"),
        (("services", "api", "env_file"), [".env"], "not env_file"),
        (("services", "api", "ports"), ["127.0.0.1:8000:8000"], "not ports"),
        (("services", "api", "entrypoint"), ["sh"], "not entrypoint"),
        (("services", "api", "volumes"), ["../..:/build"], "volumes are not exactly"),
        (("services", "migrate"), {}, "service 'migrate'"),
        (("volumes",), {"cv-account-fixture": {"driver_opts": {"o": "bind"}}}, "no option"),
        (("networks",), {}, "top-level 'networks'"),
    ],
    ids=lambda p: p if isinstance(p, str) else None,
)
def test_rule_7_refuses(path: tuple[str, ...], value: object, why: str) -> None:
    errors = lint_compose.check_account_fixture_overlay(_mutated(path, value))
    assert any(why in error for error in errors), errors
    assert all("CV_BYBIT_API_KEY:-" not in error for error in errors)  # a value is never repeated


def test_main_lints_the_overlay_by_rule_7(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert lint_compose.main([str(OVERLAY_PATH)]) == 0
    broken = tmp_path / OVERLAY_PATH.name
    broken.write_text("services:\n  api:\n    image: x\n", encoding="utf-8")
    monkeypatch.setattr(lint_compose, "ACCOUNT_FIXTURE_OVERLAY", broken)
    assert lint_compose.main([]) == 1
    assert "build is not target: builder" in capsys.readouterr().err
