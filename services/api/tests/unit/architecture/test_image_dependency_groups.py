"""#4814 guards: the API image installs the runtime dependencies and no dependency group.

`[tool.uv] default-groups` in `services/api/pyproject.toml` names `dev` and `test`, so a `uv sync`
that drops only `dev` (`--no-dev`) still puts the test tooling (pytest, hypothesis,
testcontainers, respx and the rest) into the image. These tests read the checkout:

- Every `uv sync` and `uv run` in `infra/images/Dockerfile.api` passes `--no-default-groups` and no
  flag that adds a group back; a `uv run --no-sync` installs nothing.
- The builder pins uv exactly, to a release of a series that CI's `astral-sh/setup-uv` steps
  install.
- What the image installs, every package `services/api/uv.lock` reaches from
  `[project.dependencies]`, provides each third-party module the runtime package imports and the
  driver of each Postgres DSN it names, and none of the test-only modules the image check refuses.

`tools/ci/check_image_no_dev_modules.py` checks the built image itself (CI-IMG-006).

Limits: these read the source, so the following are NOT caught.
- A `uv` global option before the subcommand (`uv --offline sync`), a heredoc `RUN`, and installs
  through another tool (`uv pip install`, `pip install`).
- Dynamic imports (`importlib.import_module`, `__import__`), and a driver named other than in a
  `postgresql+<driver>://` literal.
- The lock's markers: a package counts as installed if any platform installs it.
"""

from __future__ import annotations

import ast
import json
import re
import shlex
import sys
import tomllib
import warnings
from collections.abc import Iterator, Mapping
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest
import yaml

import candleviewer

PACKAGE = Path(candleviewer.__file__).resolve().parent
#: The repository root (`tests/unit/architecture/` is five levels down).
REPO = Path(__file__).resolve().parents[5]
DOCKERFILE = REPO / "infra" / "images" / "Dockerfile.api"
LOCK = REPO / "services" / "api" / "uv.lock"
IMAGE_CHECK = REPO / "tools" / "ci" / "check_image_no_dev_modules.py"
WORKFLOWS = REPO / ".github" / "workflows"
#: The project's own entry in the lock.
PROJECT = "candleviewer-api"
#: Flags that add a dependency group back on top of `--no-default-groups`. In uv 0.9 none of them
#: has an environment variable (only the flags that drop a group do), so only a flag can.
ADDS_A_GROUP = frozenset({"--group", "--only-group", "--all-groups", "--dev", "--only-dev"})


def _run_commands(dockerfile: str) -> Iterator[list[str]]:
    """The words of each simple command of each `RUN`, continuations joined: split at the shell's
    `&&`, `||`, `;` and `|`, quotes respected. An exec-form `RUN [...]` is one command."""
    for line in dockerfile.replace("\\\n", " ").splitlines():
        instruction, _, rest = line.strip().partition(" ")
        if instruction.upper() != "RUN":
            continue
        if rest.strip().startswith("["):
            yield [str(word) for word in json.loads(rest)]
            continue
        lexer = shlex.shlex(rest, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        command: list[str] = []
        for word in lexer:
            if set(word) <= set("&|;"):
                yield command
                command = []
            else:
                command.append(word)
        yield command


def _uv_commands(dockerfile: str) -> list[list[str]]:
    """Each `uv sync` and `uv run`, from `uv` on, however `uv` is spelled (`/usr/local/bin/uv`)."""
    found: list[list[str]] = []
    for command in _run_commands(dockerfile):
        for i, word in enumerate(command[:-1]):
            if word.rpartition("/")[2] == "uv" and command[i + 1] in ("sync", "run"):
                found.append(command[i:])
                break
    return found


def _installs_a_group(command: list[str]) -> bool:
    """Whether the `uv sync` or `uv run` in `command` can install a dependency group."""
    flags = {word.partition("=")[0] for word in command if word.startswith("--")}
    if command[1] == "run" and "--no-sync" in flags:
        return False
    return "--no-default-groups" not in flags or bool(flags & ADDS_A_GROUP)


@pytest.mark.parametrize(
    "instruction",
    [
        # #4814: `--no-dev` drops `dev` only, and `test` is a default group too.
        "RUN uv sync --frozen --no-dev --no-install-project",
        "RUN uv sync --frozen",
        # Every group named today, but a default group added later would install.
        "RUN uv sync --frozen --no-group dev --no-group test",
        "RUN uv sync --frozen --no-default-groups --group test",
        "RUN uv sync --frozen --no-default-groups --group=test",
        "RUN uv sync --frozen --no-default-groups --all-groups",
        "RUN uv sync --frozen --no-default-groups --only-group test",
        "RUN uv sync --frozen --no-default-groups --dev",
        "RUN uv sync --frozen --no-default-groups --only-dev",
        "RUN pip install uv && uv sync --frozen --no-dev",
        "RUN uv sync \\\n    --frozen --no-dev",
        "RUN /usr/local/bin/uv sync --frozen",
        "RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen",
        'RUN ["uv", "sync", "--frozen"]',
        # `uv run` syncs the default groups before it runs the command.
        "RUN uv run python -m compileall /build",
        "run uv sync --frozen",
    ],
)
def test_a_uv_command_that_installs_a_group_is_found(instruction: str) -> None:
    assert [c for c in _uv_commands(instruction) if _installs_a_group(c)] != []


@pytest.mark.parametrize(
    "instruction",
    [
        "RUN uv sync --frozen --no-default-groups --no-install-project",
        "RUN uv sync --frozen --no-dev --no-default-groups",
        "RUN uv run --no-sync python -m compileall /build",
        "RUN uv run --frozen --no-default-groups python -V",
        'RUN pip install --no-cache-dir "pip==26.2.1" "uv==0.9.30"',
        "RUN python -c \"import sys; print('uv sync')\"",
    ],
)
def test_a_uv_command_that_installs_no_group_is_allowed(instruction: str) -> None:
    assert [c for c in _uv_commands(instruction) if _installs_a_group(c)] == []


def test_every_uv_sync_in_the_image_installs_no_dependency_group() -> None:
    commands = _uv_commands(DOCKERFILE.read_text(encoding="utf-8"))
    assert any(command[1] == "sync" for command in commands), "found no `uv sync` in the image"
    offenders = [" ".join(command) for command in commands if _installs_a_group(command)]
    assert offenders == [], (
        f"infra/images/Dockerfile.api installs a dependency group: {offenders}. Pass "
        "`--no-default-groups` to every `uv sync` and `uv run` (`--no-dev` drops `dev` only, and "
        "`test` is a default group too), and never `--group`, `--only-group` or `--all-groups`."
    )


def _setup_uv_series() -> set[str]:
    """The `major.minor` of each `version` an `astral-sh/setup-uv` step of a workflow names."""
    series: set[str] = set()
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.CSafeLoader)
        if not isinstance(workflow, dict):
            continue
        for job in (workflow.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                if not str(step.get("uses", "")).startswith("astral-sh/setup-uv@"):
                    continue
                version = re.match(r"(\d+\.\d+)\.", str((step.get("with") or {}).get("version")))
                if version:
                    series.add(version[1])
    return series


def test_the_builder_pins_uv_exactly_in_a_series_ci_installs() -> None:
    """The builder pinned uv 0.4.27 while CI's setup-uv steps install 0.9.x. An exact release of
    CI's series installs the image with the uv that CI syncs and tests the lock with."""
    pins = re.findall(r"(?<![\w.-])uv==([^\s\"']+)", DOCKERFILE.read_text(encoding="utf-8"))
    assert len(pins) == 1, f"the builder must install uv once, as `uv==X.Y.Z`: {pins}"
    exact = re.fullmatch(r"(\d+\.\d+)\.\d+", pins[0])
    assert exact, f"the builder must pin uv exactly (`uv==X.Y.Z`), not `uv=={pins[0]}`"
    series = _setup_uv_series()
    assert series, "no astral-sh/setup-uv step in .github/workflows names a version"
    assert exact[1] in series, (
        f"the builder pins uv=={pins[0]}, outside the series CI's setup-uv steps install "
        f"({', '.join(f'{s}.x' for s in sorted(series))})"
    )


def _norm(name: str) -> str:
    """A distribution name as `uv.lock` writes it (PEP 503: lower case, `-` for runs of `-_.`)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _reach(lock: Mapping[str, Any]) -> set[str]:
    """What `uv sync --no-default-groups` can install: the distributions the project's own
    dependencies reach, through each extra they ask for, on any platform."""
    entries: dict[str, list[Mapping[str, Any]]] = {}
    for package in lock["package"]:
        entries.setdefault(package["name"], []).append(package)
    (project,) = entries[PROJECT]

    def edges(deps: list[Mapping[str, Any]]) -> list[tuple[str, str]]:
        return [(dep["name"], extra) for dep in deps for extra in ("", *dep.get("extra", ()))]

    seen: set[tuple[str, str]] = set()
    todo = edges(project["dependencies"])
    while todo:
        edge = todo.pop()
        if edge in seen:
            continue
        seen.add(edge)
        name, extra = edge
        for package in entries[name]:
            if extra:
                todo += edges(package.get("optional-dependencies", {}).get(extra, []))
            else:
                todo += edges(package.get("dependencies", []))
    return {name for name, _ in seen}


@pytest.fixture(scope="module")
def runtime() -> set[str]:
    with LOCK.open("rb") as f:
        return _reach(tomllib.load(f))


def test_the_runtime_set_follows_dependencies_and_extras(runtime: set[str]) -> None:
    """`pydantic-core` is reached through `pydantic`, `httptools` through `uvicorn[standard]`."""
    assert {"fastapi", "pydantic-core", "httptools"} <= runtime
    assert PROJECT not in runtime


def _image_check_tuple(name: str) -> tuple[str, ...]:
    """A tuple-of-strings constant of the image check, read from its source, never imported."""
    tree = ast.parse(IMAGE_CHECK.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and [ast.unparse(t) for t in node.targets] == [name]:
            value = ast.literal_eval(node.value)
            assert isinstance(value, tuple) and all(isinstance(v, str) for v in value), name
            return value
    raise AssertionError(f"{IMAGE_CHECK.name} defines no {name}")


def test_the_runtime_dependencies_reach_no_test_only_module(runtime: set[str]) -> None:
    """The image check refuses each of these modules, so no runtime dependency may pull one in,
    and none may be a runtime dependency itself: the check leaves no test-group package out."""
    providers = metadata.packages_distributions()
    reached = {
        module: sorted(dists)
        for module in _image_check_tuple("TEST_ONLY_MODULES")
        if (dists := {_norm(dist) for dist in providers.get(module, [])} & runtime)
    }
    assert reached == {}, (
        f"runtime dependencies in services/api/uv.lock install test-only modules: {reached}. "
        "Keep test tooling in the `test` dependency group, out of the image."
    )


@pytest.fixture(scope="module")
def owners() -> dict[str, set[str]]:
    """Each module an installed distribution's RECORD lists, to the distributions listing it:
    `a/b.py` and `a/b/__init__.py` are `a.b`, `a/_c.cpython-312-x86_64-linux-gnu.so` is `a._c`."""
    found: dict[str, set[str]] = {}
    for dist in metadata.distributions():
        name = _norm(dist.metadata["Name"])
        for file in dist.files or ():
            if file.suffix not in (".py", ".so", ".pyd"):
                continue
            parts = [*file.parts[:-1], file.name.partition(".")[0]]
            if parts[-1] == "__init__":
                parts.pop()
            if parts and all(part.isidentifier() for part in parts):
                found.setdefault(".".join(parts), set()).add(name)
    return found


def _owners_of(name: str, owners: Mapping[str, set[str]]) -> set[str]:
    """The distributions providing the longest installed prefix of the dotted `name`."""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        if found := owners.get(".".join(parts[:end])):
            return found
    return set()


#: Imports the runtime never runs: the dev-only contract helpers validate the whole OpenAPI
#: document for the generator and the tests (#2616), and `test_image_boot_path.py` keeps every
#: runtime module off them.
DEV_ONLY_IMPORTS = {"candleviewer.api.contract_conformance": frozenset({"openapi_spec_validator"})}
FIRST_PARTY = frozenset({"candleviewer", "cvdev"})


@pytest.fixture(scope="module")
def sources() -> dict[str, tuple[Path, str]]:
    """The runtime package's modules: dotted name to (path, source)."""
    modules: dict[str, tuple[Path, str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        name = ".".join(("candleviewer", *path.relative_to(PACKAGE).with_suffix("").parts))
        modules[name.removesuffix(".__init__")] = (path, path.read_text(encoding="utf-8"))
    return modules


def _third_party_imports(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """(line, dotted name) of each absolute import of neither the stdlib nor this repository;
    `from a import b` gives `a.b`, since `b` may be a module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            base = node.module
            names = [base if a.name == "*" else f"{base}.{a.name}" for a in node.names]
        else:
            continue
        for name in names:
            if name.partition(".")[0] not in FIRST_PARTY | sys.stdlib_module_names:
                yield node.lineno, name


def test_the_image_installs_every_module_the_runtime_imports(
    runtime: set[str], owners: dict[str, set[str]], sources: dict[str, tuple[Path, str]]
) -> None:
    """The image installs no dependency group, so each module the runtime imports, at import time
    or later, must come from `[project.dependencies]`. On `main` asyncpg, psutil and the
    OpenTelemetry API came from the `test` group only."""
    offenders: list[str] = []
    for module, (path, source) in sources.items():
        with warnings.catch_warnings():
            # Only applied migrations, which must never be edited (C-5.4), may carry one.
            warnings.filterwarnings(
                "ignore", category=SyntaxWarning, module=r".*[/\\]migrations[/\\]versions[/\\]"
            )
            tree = ast.parse(source, filename=str(path))
        for line, name in _third_party_imports(tree):
            if name.partition(".")[0] in DEV_ONLY_IMPORTS.get(module, ()):
                continue
            dists = _owners_of(name, owners)
            if not dists & runtime:
                provider = ", ".join(sorted(dists)) or "no installed distribution"
                offenders.append(f"{path.relative_to(PACKAGE)}:{line} {name} ({provider})")
    assert offenders == [], (
        f"the runtime imports modules the image does not install: {offenders}. Declare their "
        "distributions in [project.dependencies] of services/api/pyproject.toml, then `uv lock`."
    )


#: What a `postgresql+<driver>://` DSN needs installed: SQLAlchemy imports the driver itself, so
#: no `import` names it. psycopg needs its binary build, since the slim base image has no libpq.
DSN_DRIVERS = {
    "asyncpg": frozenset({"asyncpg"}),
    "psycopg": frozenset({"psycopg", "psycopg-binary"}),
    "psycopg_async": frozenset({"psycopg", "psycopg-binary"}),
}


def test_the_image_installs_the_driver_of_every_postgres_dsn_the_runtime_names(
    runtime: set[str], sources: dict[str, tuple[Path, str]]
) -> None:
    """On `main` both came from the `test` group only: asyncpg, the API's own driver, and
    psycopg, which Alembic runs on in the image's migrate step."""
    drivers = {
        driver
        for _, source in sources.values()
        for driver in re.findall(r"postgres(?:ql)?\+(\w+)://", source)
    }
    assert drivers, "found no `postgresql+<driver>://` DSN under candleviewer/"
    assert drivers <= DSN_DRIVERS.keys(), f"add {sorted(drivers - DSN_DRIVERS.keys())} here"
    missing = {d: sorted(DSN_DRIVERS[d] - runtime) for d in drivers if DSN_DRIVERS[d] - runtime}
    assert missing == {}, (
        f"the image does not install the drivers of these DSNs: {missing}. Declare them in "
        "[project.dependencies] of services/api/pyproject.toml, then `uv lock`."
    )
