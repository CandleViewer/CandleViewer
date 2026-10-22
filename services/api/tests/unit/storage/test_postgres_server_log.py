"""#2748 (e) (C-12.6, C-5.9): Postgres's own log keeps an error's message, not its row values.

The base compose file starts Postgres with `log_error_verbosity=terse`, which drops an error's
DETAIL, HINT, QUERY and CONTEXT (`Failing row contains (...)`, `Key (col)=(val)`), and pins
`log_parameter_max_length_on_error=0`. The deploys start it with the dev override
(`tools/ci/deploy_dev.py`), and the VPS override exists too: neither may replace the command.
Pure unit test: it reads the committed files; no docker.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_COMPOSE_DIR = Path(__file__).resolve().parents[5] / "infra" / "compose"


def _postgres(name: str) -> dict[str, Any]:
    doc = yaml.safe_load((_COMPOSE_DIR / name).read_text(encoding="utf-8")) or {}
    service: dict[str, Any] = (doc.get("services") or {}).get("postgres") or {}
    return service


def test_the_base_file_starts_postgres_with_terse_error_lines() -> None:
    command = _postgres("docker-compose.yml")["command"]
    assert command[0] == "postgres"
    flags, values = command[1::2], command[2::2]
    assert len(flags) == len(values) and set(flags) == {"-c"}
    settings = dict(value.split("=", 1) for value in values)
    assert settings["log_error_verbosity"] == "terse"
    assert settings["log_parameter_max_length_on_error"] == "0"


@pytest.mark.parametrize("override", ["docker-compose.dev.yml", "docker-compose.vps.yml"])
def test_no_override_replaces_the_postgres_command(override: str) -> None:
    assert "command" not in _postgres(override)
