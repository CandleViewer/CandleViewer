"""#2748 (e) (C-12.6, C-5.9): Postgres's own log keeps an error's message, not its row values.

The base compose file starts Postgres with `log_error_verbosity=terse`, which drops an error's
DETAIL, HINT, QUERY and CONTEXT (`Failing row contains (...)`, `Key (col)=(val)`), and pins
`log_parameter_max_length_on_error=0`. The deploys start it with the deploy overlay
(`tools/ci/deploy_dev.py`), and the dev and VPS overrides exist too: no override may replace the
command or the entrypoint. Pure unit test: it reads the committed files; no docker.
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
