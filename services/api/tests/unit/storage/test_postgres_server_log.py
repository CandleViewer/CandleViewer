"""#2748 (e) (C-12.6, C-5.9): Postgres's own log keeps an error's message, not its row values.

The base compose file starts Postgres with `log_error_verbosity=terse`, which drops an error's
DETAIL, HINT, QUERY and CONTEXT (`Failing row contains (...)`, `Key (col)=(val)`), and pins
`log_parameter_max_length_on_error=0`. The deploys start it with the deploy overlay
(`tools/ci/deploy_dev.py`), and the dev and VPS overrides exist too: no override may replace the
command or the entrypoint. E42-X02 (#1220) BQ-10: the same files, and the shipped SQL, keep a
refused statement's ERROR and STATEMENT lines in that log. Pure unit test: it reads the committed
files; no docker.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_COMPOSE_DIR = Path(__file__).resolve().parents[5] / "infra" / "compose"
_OVERRIDES = sorted(p.name for p in _COMPOSE_DIR.glob("*.y*ml") if p.name != "docker-compose.yml")


def _postgres(name: str) -> dict[str, Any]:
    doc = yaml.safe_load((_COMPOSE_DIR / name).read_text(encoding="utf-8")) or {}
    service: dict[str, Any] = (doc.get("services") or {}).get("postgres") or {}
    return service


def test_the_base_file_starts_postgres_with_terse_error_lines() -> None:
    command = _postgres("docker-compose.yml")["command"]
    assert command[0] == "postgres", "the command is a list: `postgres`, then `-c` pairs"
    flags, values = command[1::2], command[2::2]
    pairs = len(flags) == len(values) and set(flags) == {"-c"}
    assert pairs, "write each setting as its own `-c`, `name=value` pair"
    settings = dict(value.split("=", 1) for value in values)
    assert settings["log_error_verbosity"] == "terse"
    assert settings["log_parameter_max_length_on_error"] == "0"


def test_every_override_is_checked() -> None:
    assert {"docker-compose.dev.yml", "docker-compose.vps.yml"} <= set(_OVERRIDES)


def test_the_dev_pointer_only_includes_the_checked_files() -> None:
    pointer = yaml.safe_load((_COMPOSE_DIR.parent / "docker-compose.dev.yml").read_text("utf-8"))
    included = {Path(path).name for entry in pointer["include"] for path in entry["path"]}
    assert "services" not in pointer and included <= {"docker-compose.yml", *_OVERRIDES}


@pytest.mark.parametrize("override", _OVERRIDES)
def test_no_override_replaces_the_postgres_command(override: str) -> None:
    replaced = {"command", "entrypoint"} & set(_postgres(override))
    assert not replaced, f"{override} must not replace the base file's postgres {replaced}"


#: Postgres's message levels, least severe first (`log_min_messages`, `log_min_error_statement`).
_LEVELS = (
    "debug5", "debug4", "debug3", "debug2", "debug1",
    "info", "notice", "warning", "error", "log", "fatal", "panic",
)  # fmt: skip
#: An ERROR line, and its STATEMENT line, reach the server log only while the setting is at most
#: `error`; unset, Postgres's defaults (`warning`, `error`) keep both.
_KEEPS_AN_ERROR = frozenset(_LEVELS[: _LEVELS.index("error") + 1])
_LOG_LEVELS = ("log_min_messages", "log_min_error_statement")
_ROOT = _COMPOSE_DIR.parents[1]
#: Where a level could be set for every session outside the compose command.
_SQL_SOURCES = (
    _ROOT / "infra" / "scripts" / "pg_bootstrap.sql",
    *sorted((_ROOT / "services" / "api" / "candleviewer" / "migrations" / "versions").glob("*.py")),
)


def _settings(name: str) -> dict[str, str]:
    command = _postgres(name).get("command") or ["postgres"]
    return dict(value.split("=", 1) for value in command[2::2])


@pytest.mark.parametrize("name", ["docker-compose.yml", *_OVERRIDES])
def test_a_refused_statement_keeps_its_error_and_statement_lines(name: str) -> None:
    """E42-X02 BQ-10 (US-ADMIN-008 "the attempt is itself recorded"): a refused UPDATE, DELETE or
    TRUNCATE on an audit table rolls back and leaves nothing in the chain; its record is the
    server log's ERROR line and STATEMENT line, kept only while each level is at most `error`."""
    settings = _settings(name)
    for level in _LOG_LEVELS:
        assert settings.get(level, "error").lower() in _KEEPS_AN_ERROR, f"{name}: {level}"


@pytest.mark.parametrize("name", ["docker-compose.yml", *_OVERRIDES])
def test_no_compose_file_turns_off_the_postgres_log_output(name: str) -> None:
    driver = (_postgres(name).get("logging") or {}).get("driver", "json-file")
    assert driver != "none", f"{name} turns off the postgres service's log output"


@pytest.mark.parametrize("path", _SQL_SOURCES, ids=lambda p: p.name)
def test_no_shipped_sql_sets_a_server_log_level(path: Path) -> None:
    text = path.read_text(encoding="utf-8").lower()
    assert not [level for level in _LOG_LEVELS if level in text], path.name
