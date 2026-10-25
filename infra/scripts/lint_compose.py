"""infra/scripts/lint_compose.py — E02-T08 compose-lint gate.

Enforces the rules that are checkable by static inspection of the compose
YAML, without needing Docker installed. Rules 1-3 apply to the base file:

1. Every published host port is bound to ``127.0.0.1`` — never ``0.0.0.0``
   or a bare ``"<port>:<port>"`` form (trust boundary B2,
   ``docs/plan/20-architecture.md`` Sec.2.2).
2. Every image reference is pinned by digest (``name@sha256:<64 hex>``) —
   a bare tag (including ``:latest``) fails, citing the supply-chain control
   from the E02 STRIDE model (``docs/plan/security/E02-threat-model.md`` R4).
3. Every service defines a ``healthcheck``.

Rule 4 applies to the deploy overlay, ``docker-compose.deploy.yml``, which
``tools/ci/deploy_dev.py`` applies over the base file and runs with ``--no-build``:

4. It sets only the ``api`` service, and only its image, pinned to the
   verified ``${CV_API_IMAGE_REF:?...}@${CV_IMAGE_DIGEST:?...}``, a pull policy
   (``always`` or ``missing``) and ``read_only: true``. ``build``, mounts,
   ``entrypoint``, ``command`` and any other key, service or top-level entry
   are refused: the deploy runs the image it verified, with that image's own
   entrypoint and code.

Rule 5 applies to every compose file (``docker-compose*.yml``):

5. Nothing in it carries a KEK (``docs/plan/spikes/e27-kek.md`` §3, C5
   rejected): no ``environment:``, ``labels:``, ``build.args:`` or ``x-`` field.
   A name holding ``KEK`` must be one of §4's settings, each with a value that
   cannot be key material: ``CV_KEK_SOURCE`` ``file`` or ``handle``,
   ``CV_KEK_HANDLE`` a ``/run/secrets/`` path, ``CV_KEK_VERSION`` an integer or
   its own variable. No value, and no config's ``content:``, holds a run of 32
   hex digits or 43 base64 characters. A KEK reaches a service only from a host
   file, as a secret or a config: no secret or config that is not ``file:``
   alone has a name or a variable (its ``environment:``, or one its
   ``content:`` interpolates) holding ``KEK``, and what a service mounts where
   it reads its KEK (``CV_KEK_HANDLE`` or ``CV_KEK_PREV_HANDLE``, which the
   file must mount, or else Settings' ``/run/secrets/cv_kek``, or a source or
   target holding ``KEK``) is a secret or config the same file declares with
   ``file:`` alone. ``api``, ``migrate`` and ``bootstrap-owner`` take no
   ``env_file:``, where a KEK, a handle or the owner DSN would pass unread, and
   no service takes the operator's ``.env`` as one. The owner role's DSN
   (``CV_PG_OWNER_DSN``) reaches ``migrate`` alone, as its ``CV_PG_DSN``: no
   other environment entry or field of a service names it, and no secret or
   config that is not a host file carries it. No message repeats a value.

Rule 6 applies to the demo-host overlay, ``docker-compose.demo-host.yml``,
which ``docs/ops/runbooks/demo-host.md`` applies after the base and VPS files:

6. It touches only ``api``, ``migrate`` and ``bootstrap-owner`` (api:
   ``environment``, ``secrets``, ``volumes``, ``ulimits``, ``ports``; migrate:
   ``environment``) and the top-level ``secrets`` and ``volumes``; a port is
   bound to ``127.0.0.1`` (rule 1). Every environment value is the operator's
   own variable for that name, ``${NAME:?...}`` (migrate's ``CV_PG_DSN`` reads
   ``CV_PG_OWNER_DSN``), never a value committed here; only
   ``CV_ALLOWED_ORIGINS`` may be ``${CV_ALLOWED_ORIGINS:-}``. The committed
   values are ``CV_KEK_SOURCE=file``, ``CV_KEK_HANDLE=/run/secrets/cv_kek`` and
   the bootstrap's ``CV_AUDIT_WAL_PATH``, cv-api's. The top-level secrets are
   ``cv_kek`` and ``cv_audit_lane_key`` alone, ``file: ${CV_KEK_FILE:?...}``
   and ``file: ${CV_AUDIT_LANE_MAC_SOURCE:?...}``, with no default; api mounts
   ``cv_kek`` once (uid and gid 10001, mode 0400), and at most the base file's
   lane key besides, as the base file mounts it. ``ulimits.core`` is 0.
   ``/data`` is ``cv-api-data``, the one volume this file declares, with no
   option, never a bind mount. ``migrate``'s ``CV_PG_DSN`` is
   ``${CV_PG_OWNER_DSN:?...}``, and no other service takes
   ``CV_PG_OWNER_DSN``. ``bootstrap-owner``, the one-shot #4479's CLI runs in
   (DC-4479-02: it prints the Owner's invite token once, which a logging driver
   would keep), has ``logging: {driver: none}``, the profile
   ``bootstrap-owner`` alone (``up`` never starts it), no port, the CLI as its
   entrypoint, the api's image built from this checkout, a read-only root, no
   core dumps, ``cv-audit-data`` alone at cv-api's audit directory, ``cv_kek``
   alone as the api mounts it, and exactly the environment the CLI reads:
   ``CV_ENVIRONMENT``, ``CV_PG_DSN``, the KEK trio and ``CV_AUDIT_WAL_PATH``.

Run as a script (``python infra/scripts/lint_compose.py``, which checks the base
file, both overlays and rule 5 over every compose file; ``python
infra/scripts/lint_compose.py <file>`` applies an overlay's own rule when the file
has its name) or imported by ``infra/scripts/tests/test_lint_compose.py``.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

_DIGEST_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
_PORT_TOKEN = r"(?:\d+|\$\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\})"
_LOOPBACK_PORT_RE = re.compile(rf"^127\.0\.0\.1:{_PORT_TOKEN}:{_PORT_TOKEN}(/(tcp|udp))?$")

BASE_FILE = Path(__file__).parent.parent / "compose" / "docker-compose.yml"
DEPLOY_OVERLAY = Path(__file__).parent.parent / "compose" / "docker-compose.deploy.yml"
# `:?` makes compose refuse to start while the variable is unset or empty.
_DEPLOY_IMAGE_RE = re.compile(r"^\$\{CV_API_IMAGE_REF:\?[^}]+\}@\$\{CV_IMAGE_DIGEST:\?[^}]+\}$")
_DEPLOY_PULL_POLICIES = ("always", "missing")
_DEPLOY_API_KEYS = frozenset({"image", "pull_policy", "read_only"})
_DEPLOY_REFUSED = {  # any other key outside _DEPLOY_API_KEYS: "is not set by the deploy overlay"
    "build": "builds locally; the deploy runs the image it verified",
    "volumes": "mounts {value!r}; the deploy runs the image's own code",
    "entrypoint": "replaces the image's entrypoint ({value!r})",
    "command": "replaces the image's command ({value!r})",
}

COMPOSE_DIR = Path(__file__).parent.parent / "compose"
DEMO_HOST_OVERLAY = COMPOSE_DIR / "docker-compose.demo-host.yml"
#: Rule 5: e27-kek.md §4's settings an environment may hold, and the shape of each value.
_KEK_SETTINGS: dict[str, tuple[re.Pattern[str], str]] = {
    "CV_KEK_SOURCE": (re.compile(r"file|handle"), "file or handle"),
    "CV_KEK_HANDLE": (re.compile(r"/run/secrets/[a-z0-9_]+"), "a /run/secrets/ path"),
    "CV_KEK_VERSION": (
        re.compile(r"[1-9][0-9]{0,5}|\$\{CV_KEK_VERSION(?::\?[^}]*)?\}"),
        "an integer or ${CV_KEK_VERSION:?...}",
    ),
}
#: A key written out: 16 bytes or more as hex, 32 bytes as base64 (43 characters, unpadded).
_KEY_MATERIAL = re.compile(r"[0-9A-Fa-f]{32,}|[A-Za-z0-9+/_-]{43,}")
#: Rule 5: where a service reads its KEK, `/run/secrets/<target>`: a handle's, else Settings'.
_KEK_HANDLES = ("CV_KEK_HANDLE", "CV_KEK_PREV_HANDLE")
_SECRETS_DIR = "/run/secrets/"
_DEFAULT_KEK_TARGET = "cv_kek"
#: Rule 5 (D-2): where compose mounts a secret or a config whose target is missing or relative.
_MOUNT_DIRS = {"secret": _SECRETS_DIR, "config": "/"}
#: A variable a config's `content:` interpolates, `${NAME...}` or `$NAME`.
_VARIABLE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
_OWNER_DSN_NAME = "CV_PG_OWNER_DSN"
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
#: Rule 6: what the demo-host overlay may set.
_DEMO_TOP_LEVEL = ("services", "secrets", "volumes")
BOOTSTRAP_OWNER = "bootstrap-owner"
#: Rule 5 (D-2): the services that take each setting by name, in `environment:`, never from an
#: env_file, which rule 5 cannot read.
_NO_ENV_FILE = ("api", "migrate", BOOTSTRAP_OWNER)
_DEMO_SERVICE_KEYS = {
    "api": frozenset({"environment", "secrets", "volumes", "ulimits", "ports"}),
    "migrate": frozenset({"environment"}),
    BOOTSTRAP_OWNER: frozenset({
        "build", "pull_policy", "profiles", "entrypoint", "logging", "environment", "read_only",
        "tmpfs", "volumes", "secrets", "ulimits", "healthcheck", "networks",
    }),
}  # fmt: skip
KEK_HANDLE = "/run/secrets/cv_kek"
DATA_DIR = "/data"
DATA_VOLUME = "cv-api-data"
AUDIT_DIR = "/var/lib/candleviewer/audit"  # the base file's audit volume, and CV_AUDIT_WAL_PATH's
AUDIT_VOLUME = "cv-audit-data"
AUDIT_WAL = f"{AUDIT_DIR}/audit.wal"  # the base file's api's CV_AUDIT_WAL_PATH
_RUNTIME_ID = "10001"  # infra/images/Dockerfile.api's USER
_KEK_FIXED = {"CV_KEK_SOURCE": "file", "CV_KEK_HANDLE": KEK_HANDLE}
#: The only values the overlay commits, by service; every other one is the operator's variable.
_DEMO_FIXED = {
    "api": _KEK_FIXED,
    BOOTSTRAP_OWNER: _KEK_FIXED | {"CV_AUDIT_WAL_PATH": AUDIT_WAL},
}
#: The ruling (LANE-51, b): what #4479's CLI reads, and nothing else.
_BOOTSTRAP_ENV = frozenset(
    "CV_ENVIRONMENT CV_PG_DSN CV_KEK_SOURCE CV_KEK_HANDLE CV_KEK_VERSION CV_AUDIT_WAL_PATH".split()
)
#: #4479's CLI, and the api's image as the base file builds it.
_BOOTSTRAP_CLI = ["python", "-m", "candleviewer.bootstrap_owner"]
_API_BUILD = {"context": "../..", "dockerfile": "infra/images/Dockerfile.api"}
#: A name reads its own variable; migrate's CV_PG_DSN reads the owner role's.
_SOURCES = {("migrate", "CV_PG_DSN"): "CV_PG_OWNER_DSN"}
#: The one name that may default to empty: no browser origin (fail closed).
_MAY_BE_EMPTY = frozenset({"CV_ALLOWED_ORIGINS"})
_OWNER_DSN = re.compile(r"\$\{CV_PG_OWNER_DSN:\?[^}]*\}")
#: The overlay's secrets, each the host file its variable names, with no default.
_DEMO_SECRETS = {"cv_kek": "CV_KEK_FILE", "cv_audit_lane_key": "CV_AUDIT_LANE_MAC_SOURCE"}
#: The api's secret mounts: this file's `cv_kek` and the base file's audit lane key.
_API_MOUNTS: dict[str, dict[str, object]] = {
    name: {"source": name, "target": name, "uid": _RUNTIME_ID, "gid": _RUNTIME_ID, "mode": 0o400}
    for name in _DEMO_SECRETS
}
#: `lint_compose.py <file>`: an overlay's own rule, by its file name (N1).
_RULES_BY_NAME = {
    "docker-compose.deploy.yml": {"deploy_overlay": True},
    "docker-compose.demo-host.yml": {"demo_host_overlay": True},
}


class ComposeLintError(Exception):
    """Raised with every violation found, joined into one message."""


def _services(compose: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return compose.get("services", {}) or {}


def _pairs(raw: Any) -> dict[str, str]:
    """An `environment:`, `labels:` or `build.args:` block, mapping or list form, as names to
    strings."""
    raw = raw or {}
    if isinstance(raw, dict):
        return {str(k): "" if v is None else str(v) for k, v in raw.items()}
    return {k: v for k, _, v in (str(item).partition("=") for item in raw)}


def _environment(service: dict[str, Any]) -> dict[str, str]:
    """A service's `environment:`, mapping or list form, as names to strings."""
    return _pairs(service.get("environment"))


def _extension_pairs(node: Any, name: str) -> list[tuple[str, str]]:
    """Every scalar under an `x-` field, named by the key above it, or by its own `NAME=`."""
    if isinstance(node, dict):
        return [pair for key, value in node.items() for pair in _extension_pairs(value, str(key))]
    if isinstance(node, list):
        return [pair for item in node for pair in _extension_pairs(item, name)]
    if node is None:
        return []
    key, sep, value = str(node).partition("=")
    return [(key, value)] if sep and _NAME.fullmatch(key) else [(name, str(node))]


def _secret_ends(entry: Any) -> tuple[str, str]:
    """A service's `secrets:` entry, short or long form, as (source, target in /run/secrets)."""
    if not isinstance(entry, dict):
        return str(entry), str(entry)
    source = str(entry.get("source", ""))
    return source, str(entry.get("target") or source).removeprefix(_SECRETS_DIR)


def _mount(entry: Any) -> tuple[str, str, str]:
    """A `volumes:` entry, short or long syntax, as (type, source, target)."""
    if isinstance(entry, dict):
        kind, source = str(entry.get("type", "volume")), str(entry.get("source", ""))
        return kind, source, str(entry.get("target", ""))
    source, sep, rest = str(entry).partition(":")
    if not sep:
        return "volume", "", source  # anonymous
    kind = "bind" if source.startswith(("/", ".", "~", "$")) else "volume"
    return kind, source, rest.partition(":")[0]


def check_port_bindings(compose: dict[str, Any]) -> list[str]:
    """Every `ports:` entry must be an explicit `127.0.0.1:<port>:<port>` string."""
    errors: list[str] = []
    for name, service in _services(compose).items():
        for port in service.get("ports", []) or []:
            if not isinstance(port, str) or not _LOOPBACK_PORT_RE.match(port):
                errors.append(
                    f"service '{name}': port binding {port!r} is not explicitly bound to "
                    "127.0.0.1 (B2, docs/plan/20-architecture.md Sec.2.2)"
                )
    return errors


def check_image_digests(compose: dict[str, Any]) -> list[str]:
    """Every `image:` must be pinned by digest, not a mutable tag."""
    errors: list[str] = []
    for name, service in _services(compose).items():
        image = service.get("image")
        if image is None:
            continue
        if not _DIGEST_RE.match(image):
            errors.append(
                f"service '{name}': image {image!r} is not pinned by sha256 digest "
                "(supply-chain control, docs/plan/security/E02-threat-model.md R4)"
            )
    return errors


def check_healthchecks(compose: dict[str, Any]) -> list[str]:
    """Every service must declare a `healthcheck:` block."""
    errors: list[str] = []
    for name, service in _services(compose).items():
        if "healthcheck" not in service:
            errors.append(f"service '{name}': missing healthcheck block")
    return errors


def check_deploy_overlay(compose: dict[str, Any]) -> list[str]:
    """Rule 4: only the api service's verified image, a pull policy and a read-only root."""
    compose = compose or {}  # an empty file: every required key is missing
    services = _services(compose)
    extra = [f"top-level '{key}'" for key in compose if key != "services"]
    extra += [f"service '{name}'" for name in services if name != "api"]
    errors = [f"{what}: the deploy overlay sets only services.api" for what in extra]
    api = services.get("api") or {}
    for key in sorted(set(api) - _DEPLOY_API_KEYS):
        why = _DEPLOY_REFUSED.get(key, "is not set by the deploy overlay")
        errors.append(f"service 'api': {key} {why.format(value=api[key])}")
    if api.get("read_only") is not True:
        errors.append(f"service 'api': read_only is {api.get('read_only')!r}, not true")
    image, policy = api.get("image"), api.get("pull_policy")
    if not isinstance(image, str) or not _DEPLOY_IMAGE_RE.match(image):
        pin = "${CV_API_IMAGE_REF:?...}@${CV_IMAGE_DIGEST:?...}"
        errors.append(f"service 'api': image {image!r} is not pinned to {pin}")
    if policy not in _DEPLOY_PULL_POLICIES:
        errors.append(f"service 'api': pull_policy {policy!r} is neither always nor missing")
    return errors


def check_no_kek_in_environment(compose: dict[str, Any]) -> list[str]:
    """Rule 5: no value carries a KEK, a KEK comes only from a host file, and the owner DSN
    reaches migrate alone. Messages name settings, secrets, configs and services, never a value."""
    compose = compose or {}
    errors: list[str] = []
    for name, service in _services(compose).items():
        service = service or {}
        build = service.get("build")
        args = build.get("args") if isinstance(build, dict) else None
        where = f"service '{name}':"
        errors += _kek_value_problems(f"{where} environment", _environment(service).items())
        errors += _kek_value_problems(f"{where} label", _pairs(service.get("labels")).items())
        errors += _kek_value_problems(f"{where} build arg", _pairs(args).items())
        for key in [key for key in service if str(key).startswith("x-")]:
            errors += _kek_value_problems(f"{where} {key}", _extension_pairs(service[key], key))
    for key in [key for key in compose if str(key).startswith("x-")]:
        errors += _kek_value_problems(f"top-level {key}:", _extension_pairs(compose[key], key))
    errors += _kek_secret_sources(compose)
    return errors + _env_file_problems(compose) + _owner_dsn_reach(compose)


def _kek_value_problems(where: str, pairs: Iterable[tuple[str, str]]) -> list[str]:
    """Rule 5 over named values, by `where` and name."""
    errors: list[str] = []
    for key, value in pairs:
        setting = _KEK_SETTINGS.get(key.upper())
        if "KEK" in key.upper() and setting is None:
            allowed = ", ".join(_KEK_SETTINGS)
            errors.append(
                f"{where} {key} names a KEK; only {allowed} may, and never with the key itself "
                "(docs/plan/spikes/e27-kek.md §3)"
            )
        elif setting is not None and not setting[0].fullmatch(value):
            errors.append(f"{where} {key} is not {setting[1]}")
        if _KEY_MATERIAL.search(value):
            errors.append(f"{where} {key} holds inline key material")
    return errors


def _kek_secret_sources(compose: dict[str, Any]) -> list[str]:
    """Rule 5's secrets and configs: a KEK from a host file this file declares, never from the
    environment or a config's content (M1, D-2: that puts the key back in `.env` or the
    repository); the owner DSN never from either."""
    declared = {kind: compose.get(f"{kind}s") or {} for kind in _MOUNT_DIRS}
    errors = [
        error
        for kind, entries in declared.items()
        for name, entry in entries.items()
        for error in _declared_problems(kind, str(name), entry)
    ]
    for name, service in _services(compose).items():
        service = service or {}
        env = _environment(service)
        handles = {
            key: env[key] for key in _KEK_HANDLES if env.get(key, "").startswith(_SECRETS_DIR)
        }
        mounts = [
            (kind, *_mount_path(entry, base))
            for kind, base in _MOUNT_DIRS.items()
            for entry in service.get(f"{kind}s") or []
        ]
        errors += [
            f"service '{name}': {key} names a /run/secrets/ file this file does not mount on it "
            "from a file secret or config it declares"
            for key, path in handles.items()
            if path not in {mounted for _, _, mounted in mounts}
        ]
        reads = {*handles.values(), _SECRETS_DIR + _DEFAULT_KEK_TARGET}
        for kind, source, path in mounts:
            kek = path in reads or "KEK" in f"{source} {path}".upper()
            if kek and not _from_a_file(declared[kind].get(source)):
                errors.append(
                    f"service '{name}': mounts its KEK from {kind} '{source}', which this file "
                    f"does not declare as a file {kind} (file: alone)"
                )
    return errors


def _declared_problems(kind: str, name: str, entry: Any) -> list[str]:
    """A top-level secret or config: one named for a KEK or the owner DSN, or read from a variable
    that is (its `environment:`, or one its `content:` interpolates), is a host file; no content
    holds key material."""
    entry = entry if isinstance(entry, dict) else {}
    content = str(entry.get("content") or "")
    said = " ".join([name, str(entry.get("environment") or ""), *_VARIABLE.findall(content)])
    errors: list[str] = []
    if not _from_a_file(entry) and "KEK" in said.upper():
        errors.append(
            f"{kind} '{name}': is named for a KEK, or reads a KEK variable, and is not a file "
            f"{kind} (file: alone); a KEK only ever comes from a host file "
            "(docs/plan/spikes/e27-kek.md §3)"
        )
    if not _from_a_file(entry) and "OWNER_DSN" in said.upper():
        errors.append(
            f"{kind} '{name}': carries the owner role's DSN, which reaches migrate alone, as its "
            "CV_PG_DSN"
        )
    if _KEY_MATERIAL.search(content):
        errors.append(f"{kind} '{name}': content holds inline key material")
    return errors


def _from_a_file(entry: Any) -> bool:
    """A top-level secret or config whose one source is a host file: `file:` alone."""
    return isinstance(entry, dict) and set(entry) == {"file"}


def _mount_path(entry: Any, base: str) -> tuple[str, str]:
    """A service's `secrets:` or `configs:` entry, short or long form, as (source, the path it is
    mounted at): with no target, or a relative one, under `base`, as compose mounts it."""
    if not isinstance(entry, dict):
        return str(entry), base + str(entry)
    source = str(entry.get("source", ""))
    target = str(entry.get("target") or source)
    return source, target if target.startswith("/") else base + target


def _env_file_problems(compose: dict[str, Any]) -> list[str]:
    """Rule 5's env files (D-2): api, migrate and bootstrap-owner take none, and no service takes
    the operator's `.env`, which holds the owner DSN and every secret. Messages name no path."""
    errors: list[str] = []
    for name, service in _services(compose).items():
        raw = (service or {}).get("env_file")
        if not raw:
            continue
        items = raw if isinstance(raw, list) else [raw]
        paths = [str(i.get("path", "")) if isinstance(i, dict) else str(i) for i in items]
        if name in _NO_ENV_FILE:
            errors.append(
                f"service '{name}': takes an env_file; api, migrate and {BOOTSTRAP_OWNER} take "
                "each setting by name, in environment:, where rule 5 reads it"
            )
        elif any(PurePosixPath(path).name == ".env" for path in paths):
            errors.append(
                f"service '{name}': takes the operator's .env as its env_file, and with it "
                f"{_OWNER_DSN_NAME} and every secret it holds"
            )
    return errors


def _owner_dsn_reach(compose: dict[str, Any]) -> list[str]:
    """Rule 5 (D-2): the owner role's DSN reaches migrate alone, as its CV_PG_DSN: no other
    environment entry, and no other field of any service, names it."""
    errors: list[str] = []
    for name, service in _services(compose).items():
        service = service or {}
        places = [
            f"environment {key}"
            for key, value in _environment(service).items()
            if _OWNER_DSN_NAME in f"{key}={value}" and (name, key) != ("migrate", "CV_PG_DSN")
        ]
        places += [
            str(key)
            for key, node in service.items()
            if key != "environment" and _OWNER_DSN_NAME in _scalars(node)
        ]
        errors += [
            f"service '{name}': {place} takes {_OWNER_DSN_NAME}; only migrate's CV_PG_DSN may"
            for place in places
        ]
    return errors


def _scalars(node: Any) -> str:
    """Every key and scalar under a node, joined: what a name check reads."""
    if isinstance(node, dict):
        return " ".join(f"{key} {_scalars(value)}" for key, value in node.items())
    if isinstance(node, list):
        return " ".join(_scalars(item) for item in node)
    return "" if node is None else str(node)


def check_demo_host_overlay(compose: dict[str, Any]) -> list[str]:
    """Rule 6 (module docstring): the demo-host overlay's shape."""
    compose = compose or {}
    services = _services(compose)
    errors = [
        f"top-level '{key}': the demo-host overlay sets only {', '.join(_DEMO_TOP_LEVEL)}"
        for key in compose
        if key not in _DEMO_TOP_LEVEL
    ]
    for name, service in services.items():
        allowed = _DEMO_SERVICE_KEYS.get(name)
        if allowed is None:
            errors.append(
                f"service '{name}': the demo-host overlay touches only api, migrate and "
                f"{BOOTSTRAP_OWNER}"
            )
            continue
        errors += [
            f"service '{name}': {key} is not set by the demo-host overlay"
            for key in sorted(set(service or {}) - allowed)
        ]
        errors += _environment_problems(name, _environment(service or {}))
    errors += check_port_bindings(compose)
    api = services.get("api") or {}
    errors += _kek_secret_problems(compose, api)
    core = (api.get("ulimits") or {}).get("core")
    if core != 0 and core != {"soft": 0, "hard": 0}:
        errors.append(f"service 'api': ulimits.core is {core!r}, not 0 (SR-009: no core dumps)")
    errors += _data_volume_problems(compose, api)
    bootstrap = services.get(BOOTSTRAP_OWNER)
    if bootstrap is None:
        errors.append(
            f"service '{BOOTSTRAP_OWNER}' is missing: #4479's CLI runs there, never in api, "
            "whose logging driver would keep the token it prints (DC-4479-02)"
        )
    else:
        errors += _bootstrap_owner_problems(bootstrap or {})
    return errors + _owner_dsn_problems(services)


def _environment_problems(name: str, env: dict[str, str]) -> list[str]:
    """The committed values as they are, and every other one the operator's own variable."""
    fixed = _DEMO_FIXED.get(name, {})
    errors: list[str] = []
    for key, value in fixed.items():
        if env.get(key) != value:
            what = "cv-api's " if key == "CV_AUDIT_WAL_PATH" else ""
            errors.append(f"service '{name}': {key} is not {what}{value}")
    for key, value in env.items():
        source = _SOURCES.get((name, key), key)
        required = re.fullmatch(rf"\$\{{{re.escape(source)}:\?[^}}]*\}}", value)
        empty = key in _MAY_BE_EMPTY and value == f"${{{key}:-}}"
        if key not in fixed and not (required or empty):
            maybe = f" or ${{{key}:-}}" if key in _MAY_BE_EMPTY else ""
            errors.append(
                f"service '{name}': environment {key} is committed here, not taken from the "
                f"operator's env file as ${{{source}:?...}}{maybe}"
            )
    return errors


def _secret_mount(entry: Any) -> dict[str, object]:
    """A `secrets:` entry in the api's long form; a bare name keeps compose's defaults."""
    if not isinstance(entry, dict):
        return {"source": str(entry)}
    shown: dict[str, object] = {k: str(entry.get(k)) for k in ("source", "target", "uid", "gid")}
    return shown | {"mode": entry.get("mode")}


def _bootstrap_owner_problems(service: dict[str, Any]) -> list[str]:
    """The one-shot #4479's CLI runs in (DC-4479-02), with what the CLI reads and nothing else."""
    name = f"service '{BOOTSTRAP_OWNER}'"
    errors: list[str] = []
    if service.get("logging") != {"driver": "none"}:
        errors.append(
            f"{name}: logging is not {{driver: none}}: a logging driver would keep the "
            "Owner's invite token the CLI prints once (DC-4479-02)"
        )
    if service.get("profiles") != [BOOTSTRAP_OWNER]:
        errors.append(f"{name}: profiles is not [{BOOTSTRAP_OWNER}], so `up` could start it")
    if service.get("entrypoint") != _BOOTSTRAP_CLI:
        errors.append(f"{name}: entrypoint is not {' '.join(_BOOTSTRAP_CLI)}")
    if service.get("build") != _API_BUILD or service.get("pull_policy") != "build":
        errors.append(f"{name}: does not build the api's image from this checkout")
    if [_secret_mount(entry) for entry in service.get("secrets") or []] != [_API_MOUNTS["cv_kek"]]:
        errors.append(
            f"{name}: mounts a secret that is not cv_kek as the api mounts it, or none: the CLI "
            "reads the KEK alone (no lane key)"
        )
    names = set(_environment(service))
    if names != _BOOTSTRAP_ENV:
        errors.append(
            f"{name}: environment is not exactly what the CLI reads (it adds "
            f"{sorted(names - _BOOTSTRAP_ENV)} and lacks {sorted(_BOOTSTRAP_ENV - names)}): no "
            "lane key, egress address or auth key"
        )
    if service.get("read_only") is not True:
        errors.append(f"{name}: read_only is not true")
    core = (service.get("ulimits") or {}).get("core")
    if core != 0 and core != {"soft": 0, "hard": 0}:
        errors.append(f"{name}: ulimits.core is {core!r}, not 0 (SR-009: it loads the KEK)")
    volumes = [_mount(entry) for entry in service.get("volumes") or []]
    if volumes != [("volume", AUDIT_VOLUME, AUDIT_DIR)]:
        errors.append(
            f"{name}: does not mount the audit volume alone, {AUDIT_VOLUME} at {AUDIT_DIR} (its "
            "journal and the run lock it shares with cv-api), or mounts a bind"
        )
    return errors


def _kek_secret_problems(compose: dict[str, Any], api: dict[str, Any]) -> list[str]:
    """The overlay's two file secrets, and api's mounts: `cv_kek` once, at most the lane key."""
    declared = compose.get("secrets") or {}
    errors = [
        f"secret '{extra}': the demo-host overlay declares only cv_kek and cv_audit_lane_key, "
        "each a file secret"
        for extra in sorted(set(declared) - set(_DEMO_SECRETS))
    ]
    for name, variable in _DEMO_SECRETS.items():
        secret = declared.get(name)
        source = str(secret["file"]) if isinstance(secret, dict) and set(secret) == {"file"} else ""
        if not re.fullmatch(rf"\$\{{{variable}:\?[^}}]*\}}", source):
            errors.append(
                f"secret '{name}' is not file: ${{{variable}:?...}} (the host file the "
                "operator's env file names, with no default, so an unset name fails loudly)"
            )
    mounts = [_secret_mount(entry) for entry in api.get("secrets") or []]
    if [m for m in mounts if m["source"] == "cv_kek"] != [_API_MOUNTS["cv_kek"]]:
        errors.append(
            f"service 'api': does not mount cv_kek once at {KEK_HANDLE}, uid and gid "
            f"{_RUNTIME_ID}, mode 0400"
        )
    targets = [_secret_ends(entry)[1] for entry in api.get("secrets") or []]
    foreign = [m for m in mounts if _API_MOUNTS.get(str(m["source"])) != m]
    if foreign or len(set(targets)) < len(targets):
        errors.append(
            "service 'api': mounts a secret that is not cv_kek or the base file's lane key as "
            "the base file mounts it, or two at one target"
        )
    return errors


def _data_volume_problems(compose: dict[str, Any], api: dict[str, Any]) -> list[str]:
    """api mounts one thing here, /data: cv-api-data, the one volume this file declares (L3)."""
    errors: list[str] = []
    declared = compose.get("volumes") or {}
    if set(declared) != {DATA_VOLUME} or declared[DATA_VOLUME] not in (None, {}):
        errors.append(
            f"top-level volumes: declares {sorted(declared)}, not {DATA_VOLUME} alone with no "
            "option (a driver, driver_opts or external makes it a host bind or another volume)"
        )
    mounts = [_mount(entry) for entry in api.get("volumes") or []]
    if mounts != [("volume", DATA_VOLUME, DATA_DIR)]:
        targets = [target for _, _, target in mounts]
        errors.append(
            f"service 'api': mounts {targets}, not {DATA_DIR} alone as {DATA_VOLUME}, the named "
            "volume this file declares (never a bind mount)"
        )
    return errors


def _owner_dsn_problems(services: dict[str, dict[str, Any]]) -> list[str]:
    """The owner role's DSN reaches migrate, as its CV_PG_DSN, and no other service."""
    errors: list[str] = []
    dsn = _environment(services.get("migrate") or {}).get("CV_PG_DSN", "")
    if not _OWNER_DSN.fullmatch(dsn):
        errors.append("service 'migrate': CV_PG_DSN is not ${CV_PG_OWNER_DSN:?...}")
    for name in ("api", BOOTSTRAP_OWNER):
        env = _environment(services.get(name) or {})
        if any("CV_PG_OWNER_DSN" in f"{key}={value}" for key, value in env.items()):
            errors.append(f"service '{name}': takes CV_PG_OWNER_DSN; only migrate may")
    return errors


def lint(
    compose_path: Path, *, deploy_overlay: bool = False, demo_host_overlay: bool = False
) -> list[str]:
    """Rules 1-3 (rule 4 for the deploy overlay, rule 6 for the demo host's), then rule 5."""
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    if deploy_overlay:
        errors = check_deploy_overlay(compose)
    elif demo_host_overlay:
        errors = check_demo_host_overlay(compose)
    else:
        errors = check_port_bindings(compose)
        errors += check_image_digests(compose)
        errors += check_healthchecks(compose)
    return errors + check_no_kek_in_environment(compose)


def main(argv: list[str] | None = None) -> int:
    """Lint `argv[0]` with rules 1-3 and 5, or with an overlay's own rule and 5 when it has the
    overlay's file name (N1); with no argument, the base file and both overlays, and rule 5 over
    every other compose file."""
    files: list[tuple[Path, dict[str, bool]]] = [(BASE_FILE, {})]
    if argv:
        files = [(Path(argv[0]), _RULES_BY_NAME.get(Path(argv[0]).name, {}))]
    else:
        files += [(DEPLOY_OVERLAY, {"deploy_overlay": True})]
        files += [(DEMO_HOST_OVERLAY, {"demo_host_overlay": True})]
    errors = [f"{p.name}: {e}" for p, kind in files for e in lint(p, **kind)]
    linted = {p.resolve() for p, _ in files}
    for path in [] if argv else sorted(COMPOSE_DIR.glob("docker-compose*.yml")):
        if path.resolve() not in linted:
            compose = yaml.safe_load(path.read_text(encoding="utf-8"))
            errors += [f"{path.name}: {e}" for e in check_no_kek_in_environment(compose)]
    if errors:
        for error in errors:
            print(f"lint_compose: {error}", file=sys.stderr)
        return 1
    print("lint_compose: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
