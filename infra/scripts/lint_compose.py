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

Run as a script (``python infra/scripts/lint_compose.py``, which checks both
files) or imported by ``infra/scripts/tests/test_lint_compose.py``.
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


class ComposeLintError(Exception):
    """Raised with every violation found, joined into one message."""


def _services(compose: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return compose.get("services", {}) or {}


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


def lint(compose_path: Path, *, deploy_overlay: bool = False) -> list[str]:
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    if deploy_overlay:
        return check_deploy_overlay(compose)
    errors: list[str] = []
    errors += check_port_bindings(compose)
    errors += check_image_digests(compose)
    errors += check_healthchecks(compose)
    return errors


def main(argv: list[str] | None = None) -> int:
    """Lint `argv[0]` with rules 1-3; with no argument, the base file and the deploy overlay."""
    files = [(Path(argv[0]), False)] if argv else [(BASE_FILE, False), (DEPLOY_OVERLAY, True)]
    errors = [f"{p.name}: {e}" for p, overlay in files for e in lint(p, deploy_overlay=overlay)]
    if errors:
        for error in errors:
            print(f"lint_compose: {error}", file=sys.stderr)
        return 1
    print("lint_compose: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
