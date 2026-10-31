"""#3897, #4014: what the API image, the compose file and the runbook recipe carry for the migrate
step.

Static, like `tests/unit/architecture/test_image_boot_path.py`: no docker, no network. The image
copies `backend/db/questdb` to the path `candleviewer.storage.migrate` hands the runner, root-owned
and not writable (the runtime user reads the DDL and cannot change it). The compose `migrate`
service is a one-shot in the `core` and `migrate` profiles that is rebuilt from the API's
definition and takes the owner role's DSN from its own variable (never the one `api` reads). `api`
waits for it to complete successfully, so the API never starts after a schema step that failed. The
runbook recipe is the one `up` that runs it first, as this checkout's build, with the owner DSN on
that one command.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml

from candleviewer.storage.migrate import QUESTDB_DDL_DIR

_ROOT = Path(__file__).resolve().parents[5]
_COMPOSE = _ROOT / "infra" / "compose" / "docker-compose.yml"
_RUNBOOK = _ROOT / "docs" / "ops" / "runbooks" / "storage-migrate.md"
_DDL_SOURCE = "backend/db/questdb"
_OWNER_DSN = "CV_PG_OWNER_DSN"  # `Settings.pg_owner_dsn`: the cv_owner login


def _runtime_stage() -> str:
    """The Dockerfile's last stage: what the image runs, as opposed to what builds it."""
    dockerfile = (_ROOT / "infra" / "images" / "Dockerfile.api").read_text(encoding="utf-8")
    return dockerfile.replace("\\\n", " ").split("\nFROM ")[-1]


def _ddl_copy() -> list[str]:
    """The words of the runtime stage's `COPY` of the DDL directory."""
    lines = [line.split() for line in _runtime_stage().splitlines()]
    copies = [words for words in lines if words[:1] == ["COPY"] and _DDL_SOURCE in words]
    assert len(copies) == 1, f"Dockerfile.api must COPY {_DDL_SOURCE} once, found {len(copies)}"
    return copies[0]


def test_the_image_copies_the_ddl_where_the_command_reads_it_root_owned_and_not_writable() -> None:
    copy, stage, target = _ddl_copy(), _runtime_stage(), QUESTDB_DDL_DIR.as_posix()
    assert PurePosixPath(copy[-1]) == PurePosixPath(target)
    assert list((_ROOT / _DDL_SOURCE).glob("*.sql")), "the copied directory holds the DDL files"
    assert not [word for word in copy if word.startswith("--chown")]  # root-owned
    # The mode comes from the build host's checkout (a permissive umask, DrvFs): normalise it.
    chmod = f"RUN chmod -R a+rX,go-w {target}"
    assert stage.count(chmod) == 1 and stage.index(" ".join(copy)) < stage.index(chmod)
    user = re.findall(r"^USER\s+(\S+)", stage, re.MULTILINE)[-1]
    assert user.partition(":")[0] not in ("0", "root")


@pytest.fixture(scope="module")
def services() -> dict[str, Any]:
    return dict(yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))["services"])


def test_migrate_is_a_one_shot_in_core_and_migrate_rebuilt_from_the_api_definition_on_its_stores(
    services: dict[str, Any],
) -> None:
    migrate, api = services["migrate"], services["api"]
    assert migrate["profiles"] == ["core", "migrate"]  # an `up` of `core` runs it, as `api` waits
    assert migrate["build"] == api["build"]  # one Dockerfile and context: the recipe builds both
    # Always rebuilt, and never a tag it shares with `api`: dev builds api's `builder` target.
    assert migrate["pull_policy"] == "build" and "image" not in migrate
    assert migrate["entrypoint"] == ["python", "-m", "candleviewer.storage.migrate"]
    assert (migrate.get("restart", "no"), migrate["read_only"]) == ("no", True)
    assert "ports" not in migrate
    assert migrate["environment"]["CV_QUESTDB_PG"] == api["environment"]["CV_QUESTDB_PG"]
    healthy = {"condition": "service_healthy"}
    assert migrate["depends_on"] == {"postgres": healthy, "questdb": healthy}


def test_the_owner_dsn_reaches_migrate_through_its_own_variable_and_never_api(
    services: dict[str, Any],
) -> None:
    dsn = services["migrate"]["environment"]["CV_PG_DSN"]
    assert dsn.startswith("${" + _OWNER_DSN + ":-")  # the dev default stays after `:-`
    assert "${CV_PG_DSN" not in dsn  # never the variable `api` reads (the app role's)
    assert [name for name, service in services.items() if _OWNER_DSN in str(service)] == ["migrate"]


def _bash_blocks() -> list[str]:
    """The runbook's fenced bash blocks, continuation lines joined."""
    text = _RUNBOOK.read_text(encoding="utf-8")
    return [
        block.replace("\\\n", " ") for block in re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
    ]


def test_the_recipe_rebuilds_both_images_and_gives_the_owner_dsn_to_the_one_command() -> None:
    recipe = _bash_blocks()[0]  # the run recipe: the runbook's first fenced bash block
    prefix, _, command = recipe.partition("$C")
    # One `up`: `api` waits for the step, so there is no second command to run it before. `--build`
    # makes `api` this checkout's build; `migrate` rebuilds itself on every `up` (`pull_policy`).
    assert "up -d --build api" in command and "&&" not in recipe and "run --rm" not in recipe
    assert f"{_OWNER_DSN}=" in prefix  # a prefix of that one command
    assert "export" not in recipe  # never left in the shell's environment


def test_the_rehearsal_runs_the_step_alone_with_the_owner_dsn_on_its_command() -> None:
    rehearsal = _bash_blocks()[1]  # the second block: `run` returns the step's exit status
    assert "--profile core run --rm --build migrate" in rehearsal
    assert rehearsal.lstrip().startswith(f"{_OWNER_DSN}=") and "export" not in rehearsal


def test_api_waits_for_migrate_to_complete_successfully(services: dict[str, Any]) -> None:
    healthy = {"condition": "service_healthy"}  # the stores stay as `api` waited for them
    assert services["api"]["depends_on"] == {
        "postgres": healthy,
        "questdb": healthy,
        "migrate": {"condition": "service_completed_successfully"},
    }


def test_every_service_api_depends_on_runs_under_a_profile_api_runs_under(
    services: dict[str, Any],
) -> None:
    """Compose refuses an `api` that depends on a service of an inactive profile (`depends on
    undefined service`, measured on v5.6.0), so every profile `api` runs under starts them all."""
    api = services["api"]
    for profile in api["profiles"]:
        left_out = [
            name
            for name in api["depends_on"]
            if services[name].get("profiles") and profile not in services[name]["profiles"]
        ]
        assert left_out == [], f"`--profile {profile}` leaves {left_out} out, which compose refuses"
