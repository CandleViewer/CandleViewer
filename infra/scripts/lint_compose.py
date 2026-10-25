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

5. No ``environment:`` carries a KEK (``docs/plan/spikes/e27-kek.md`` §3, C5
   rejected). A name holding ``KEK`` must be one of §4's settings, each with a
   value that cannot be key material: ``CV_KEK_SOURCE`` ``file`` or ``handle``,
   ``CV_KEK_HANDLE`` a ``/run/secrets/`` path, ``CV_KEK_VERSION`` an integer or
   its own variable. No value holds a run of 32 hex digits or 43 base64
   characters. No message repeats a value.

Rule 6 applies to the demo-host overlay, ``docker-compose.demo-host.yml``,
which ``docs/ops/runbooks/demo-host.md`` applies after the base and VPS files:

6. It touches only ``api``, ``migrate`` and ``bootstrap-owner`` (api:
   ``environment``, ``secrets``, ``volumes``, ``ulimits``, ``ports``; migrate:
   ``environment``) and the top-level ``secrets`` and ``volumes``; a port is
   bound to ``127.0.0.1`` (rule 1). Every environment value is the operator's
   variable (``${NAME:?...}``, or ``${NAME:-}``), never a value committed here,
   except ``CV_KEK_SOURCE=file``, ``CV_KEK_HANDLE=/run/secrets/cv_kek`` and the
   bootstrap's ``CV_AUDIT_WAL_PATH``. The ``cv_kek`` secret is
   ``file: ${CV_KEK_FILE:?...}`` with no default, mounted on api as ``cv_kek``
   (uid and gid 10001, mode 0400). ``ulimits.core`` is 0. ``/data`` is one
   named volume this file declares, never a bind mount. ``migrate``'s
   ``CV_PG_DSN`` is ``${CV_PG_OWNER_DSN:?...}``, and no other service takes
   ``CV_PG_OWNER_DSN``. ``bootstrap-owner``, the one-shot #4479's CLI runs in
   (DC-4479-02: it prints the Owner's invite token once, which a logging driver
   would keep), has ``logging: {driver: none}``, the profile
   ``bootstrap-owner`` alone (``up`` never starts it), no port, the CLI as its
   entrypoint, the api's image built from this checkout, a read-only root, no
   core dumps, the audit volume alone, and secrets that are the api's alone,
   ``cv_kek`` among them.

Run as a script (``python infra/scripts/lint_compose.py``, which checks the base
file, both overlays and rule 5 over every compose file) or imported by
``infra/scripts/tests/test_lint_compose.py``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
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
#: Rule 6: what the demo-host overlay may set.
_DEMO_TOP_LEVEL = ("services", "secrets", "volumes")
BOOTSTRAP_OWNER = "bootstrap-owner"
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
AUDIT_DIR = "/var/lib/candleviewer/audit"  # the base file's audit volume, and CV_AUDIT_WAL_PATH's
_RUNTIME_ID = "10001"  # infra/images/Dockerfile.api's USER
_KEK_FIXED = {"CV_KEK_SOURCE": "file", "CV_KEK_HANDLE": KEK_HANDLE}
#: The only values the overlay commits, by service; every other one is the operator's variable.
_DEMO_FIXED = {
    "api": _KEK_FIXED,
    BOOTSTRAP_OWNER: _KEK_FIXED | {"CV_AUDIT_WAL_PATH": f"{AUDIT_DIR}/audit.wal"},
}
#: #4479's CLI, and the api's image as the base file builds it.
_BOOTSTRAP_CLI = ["python", "-m", "candleviewer.bootstrap_owner"]
_API_BUILD = {"context": "../..", "dockerfile": "infra/images/Dockerfile.api"}
#: `${NAME:?...}` (compose refuses to run while it is unset or empty) or `${NAME:-}`.
_OPERATOR_VALUE = re.compile(r"\$\{[A-Z][A-Z0-9_]*(?::\?[^}]*|:-)\}")
_KEK_FILE = re.compile(r"\$\{CV_KEK_FILE:\?[^}]*\}")
_OWNER_DSN = re.compile(r"\$\{CV_PG_OWNER_DSN:\?[^}]*\}")
#: The api's secret mounts: this file's `cv_kek` and the base file's audit lane key.
_API_MOUNTS: dict[str, dict[str, object]] = {
    name: {"source": name, "target": name, "uid": _RUNTIME_ID, "gid": _RUNTIME_ID, "mode": 0o400}
    for name in ("cv_kek", "cv_audit_lane_key")
}


class ComposeLintError(Exception):
    """Raised with every violation found, joined into one message."""


def _services(compose: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return compose.get("services", {}) or {}


def _environment(service: dict[str, Any]) -> dict[str, str]:
    """A service's `environment:`, mapping or list form, as names to strings."""
    raw = service.get("environment") or {}
    if isinstance(raw, dict):
        return {str(k): "" if v is None else str(v) for k, v in raw.items()}
    return {k: v for k, _, v in (str(item).partition("=") for item in raw)}


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
    """Rule 5: no environment carries a KEK. Messages name settings, never a value."""
    errors: list[str] = []
    for name, service in _services(compose or {}).items():
        for key, value in _environment(service or {}).items():
            setting = _KEK_SETTINGS.get(key.upper())
            if "KEK" in key.upper() and setting is None:
                allowed = ", ".join(_KEK_SETTINGS)
                errors.append(
                    f"service '{name}': environment {key} names a KEK; only {allowed} may, and "
                    "never with the key itself (docs/plan/spikes/e27-kek.md §3)"
                )
            elif setting is not None and not setting[0].fullmatch(value):
                errors.append(f"service '{name}': environment {key} is not {setting[1]}")
            if _KEY_MATERIAL.search(value):
                errors.append(f"service '{name}': environment {key} holds inline key material")
    return errors


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
        for key, value in _environment(service or {}).items():
            fixed = _DEMO_FIXED.get(name, {}).get(key)
            if value != fixed and not _OPERATOR_VALUE.fullmatch(value):
                errors.append(
                    f"service '{name}': environment {key} is committed here, not taken from "
                    "the operator's env file (${NAME:?...} or ${NAME:-})"
                )
    errors += check_port_bindings(compose)
    api = services.get("api") or {}
    if _environment(api).get("CV_KEK_HANDLE") != KEK_HANDLE:
        errors.append(f"service 'api': CV_KEK_HANDLE is not {KEK_HANDLE}, the cv_kek mount")
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


def _secret_mount(entry: Any) -> dict[str, object]:
    """A `secrets:` entry in the api's long form; a bare name keeps compose's defaults."""
    if not isinstance(entry, dict):
        return {"source": str(entry)}
    shown: dict[str, object] = {k: str(entry.get(k)) for k in ("source", "target", "uid", "gid")}
    return shown | {"mode": entry.get("mode")}


def _bootstrap_owner_problems(service: dict[str, Any]) -> list[str]:
    """The one-shot #4479's CLI runs in (DC-4479-02)."""
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
    mounts = [_secret_mount(entry) for entry in service.get("secrets") or []]
    sources = [mount["source"] for mount in mounts]
    foreign = [m for m in mounts if _API_MOUNTS.get(str(m["source"])) != m]
    if foreign or "cv_kek" not in sources or len(set(sources)) != len(sources):
        errors.append(
            f"{name}: mounts a secret that is not one of the api's, or not as the api does, "
            "or lacks cv_kek"
        )
    if service.get("read_only") is not True:
        errors.append(f"{name}: read_only is not true")
    core = (service.get("ulimits") or {}).get("core")
    if core != 0 and core != {"soft": 0, "hard": 0}:
        errors.append(f"{name}: ulimits.core is {core!r}, not 0 (SR-009: it loads the KEK)")
    volumes = [_mount(entry) for entry in service.get("volumes") or []]
    if [(kind, target) for kind, _, target in volumes] != [("volume", AUDIT_DIR)]:
        errors.append(
            f"{name}: does not mount the audit volume alone at {AUDIT_DIR} (its journal and "
            "the run lock it shares with cv-api), or mounts a bind"
        )
    return errors


def _kek_secret_problems(compose: dict[str, Any], api: dict[str, Any]) -> list[str]:
    """`cv_kek` is the host file CV_KEK_FILE names (no default), mounted once on api."""
    errors: list[str] = []
    secret = (compose.get("secrets") or {}).get("cv_kek")
    source = secret.get("file") if isinstance(secret, dict) and set(secret) == {"file"} else None
    if not isinstance(source, str) or not _KEK_FILE.fullmatch(source):
        errors.append(
            "secret 'cv_kek' is not file: ${CV_KEK_FILE:?...} (the host file the operator's "
            "env file names, with no default, so an unset name fails loudly)"
        )
    mounts = [_secret_mount(entry) for entry in api.get("secrets") or []]
    if [m for m in mounts if m["source"] == "cv_kek"] != [_API_MOUNTS["cv_kek"]]:
        errors.append(
            f"service 'api': does not mount cv_kek once at {KEK_HANDLE}, uid and gid "
            f"{_RUNTIME_ID}, mode 0400"
        )
    return errors


def _data_volume_problems(compose: dict[str, Any], api: dict[str, Any]) -> list[str]:
    """api mounts one thing here: /data, a named volume this file declares."""
    mounts = [_mount(entry) for entry in api.get("volumes") or []]
    declared = compose.get("volumes") or {}
    shape = [(kind, target) for kind, _, target in mounts]
    if shape == [("volume", DATA_DIR)] and mounts[0][1] in declared:
        return []
    targets = [target for _, _, target in mounts]
    return [
        (
            f"service 'api': mounts {targets}, not {DATA_DIR} alone as a named volume this file "
            "declares (never a bind mount)"
        )
    ]


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
    """Lint `argv[0]` with rules 1-3 and 5; with no argument, the base file and both overlays,
    and rule 5 over every other compose file."""
    files: list[tuple[Path, dict[str, bool]]] = [(BASE_FILE, {})]
    if argv:
        files = [(Path(argv[0]), {})]
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
