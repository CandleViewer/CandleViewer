#!/usr/bin/env python3
"""E03-T09: dev deploy — verify, apply, smoke-test, ledger, auto-rollback.

Deploys a signed, digest-pinned image to the dev docker-compose stack on the
self-hosted dev-host runner (ADR-0013 rule 8: deployment is image-based and
by digest; production stays a checklisted human action, out of scope here).

Flow (ticket "Scope / Deliverables" + acceptance scenarios):
  1. `cosign verify` the image digest *before* touching any container
     (CI-DEP-001 on failure — deployment aborts, ledger records the
     failure, nothing is replaced).
  2. Render `infra/compose/.env` with `CV_API_IMAGE_REF`/`CV_IMAGE_DIGEST`/
     `CV_GIT_SHA` set to the just-verified build and run
     `docker compose ... up -d --wait --no-build` over the base file and the
     deploy overlay `infra/compose/docker-compose.deploy.yml`: the `api`
     service runs the verified `<ref>@<digest>`, which compose also gets in
     its own environment (`--wait` waits on the `api` healthcheck, which is
     only `/healthz`; step 3 checks the image).
  3. Smoke test: poll `GET /healthz` and `GET /readyz` until both report
     `status: ok`, then check that the running `api` container's image id
     equals the verified image's id (`check_running_image`; CI-DEP-003
     naming both ids if they differ, CI-DEP-002 if either cannot be read).
  4. Append a `deployments/ledger.jsonl` record (success or failure).
  5. Dev-only: on smoke failure, automatically redeploy the previous digest
     (recorded in the ledger) through steps 1-3 with the same compose files,
     and record that as its own entry — staging never auto-rolls-back
     (ticket "Technical notes"); a staging rollback is a deploy of the
     previous digest.

Stdlib + `urllib.request` only; no third-party HTTP client needed for a
handful of polling GETs from a CI/runner context.

Error codes: CI-DEP-001 signature verification failed, CI-DEP-002 smoke
failed, CI-DEP-003 image mismatch after deploy, CI-DEP-004 migration lock
timeout (surfaced by the migration job itself; this script only waits on
the compose healthcheck, which stays unhealthy while the boot-time
migration/advisory-lock step is in progress).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_LEDGER = Path("deployments/ledger.jsonl")
DEFAULT_COMPOSE_FILES = (
    "infra/compose/docker-compose.yml",
    "infra/compose/docker-compose.deploy.yml",
)
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


class DeployError(RuntimeError):
    """Raised with a `CI-DEP-NNN` code so the CLI can exit non-zero cleanly."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class LedgerEntry:
    sha: str
    digest: str
    environment: str
    actor: str
    timestamp: str
    outcome: Literal[
        "success",
        "signature-verification-failed",
        "smoke-failed",
        "sha-mismatch",
        "rolled-back",
    ]
    duration_s: float = 0.0
    detail: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "sha": self.sha,
                "digest": self.digest,
                "environment": self.environment,
                "actor": self.actor,
                "timestamp": self.timestamp,
                "outcome": self.outcome,
                "duration_s": round(self.duration_s, 3),
                "detail": self.detail,
            },
            sort_keys=True,
        )


def append_ledger(entry: LedgerEntry, ledger_path: Path = DEFAULT_LEDGER) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(entry.to_json() + "\n")


def read_last_success_digest(
    environment: str, ledger_path: Path = DEFAULT_LEDGER, before_line: int | None = None
) -> str | None:
    """Return the digest of the most recent `success` ledger entry for `environment`.

    Used by rollback (previous-digest lookup) and by the dev auto-rollback
    path (the "known good" digest to restore on a failed smoke test).
    `before_line` restricts the scan to entries written before the current
    deploy's own line, so a deploy never finds *itself* as "previous".
    """
    if not ledger_path.exists():
        return None
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    if before_line is not None:
        lines = lines[:before_line]
    for line in reversed(lines):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("actor") == "seed":
            continue
        if row.get("environment") == environment and row.get("outcome") == "success":
            digest = row.get("digest")
            return digest if isinstance(digest, str) else None
    return None


# Only `main.yml`'s `build-scan-sign` job ever signs a fit-for-deploy image
# (E03-T08). The identity regexp must therefore pin both the *workflow file*
# and the *ref* it ran on — a bare `^https://github.com/{repo}/` prefix also
# matches every other workflow in the repo (including one running on an
# untrusted PR branch), since cosign's keyless SAN embeds
# `https://github.com/{repo}/{workflow_path}@{ref}` and a regexp with no
# anchor after `{repo}/` treats the workflow path as free text. Dev only
# ever deploys what was built on `main`; staging additionally accepts a
# `release/*` branch build (release promotion, `01-sdlc-and-branching.md`
# §9) since `deploy-staging.yml`'s `push: branches: ["release/*"]` trigger
# needs a matching signer identity.
_SIGNER_WORKFLOW_PATH = ".github/workflows/main.yml"
_ALLOWED_REF_PATTERNS: dict[str, str] = {
    "dev": r"refs/heads/main",
    "staging": r"refs/heads/main|refs/heads/release/[^@]+",
}


def verify_signature(
    image_ref: str, digest: str, *, repository: str, environment: str = "dev"
) -> None:
    """`cosign verify` the pushed image; raises CI-DEP-001 on any failure.

    Pins the keyless-OIDC identity to `main.yml`'s `build-scan-sign` job
    running on an allowed ref for `environment` (never a PR branch or an
    arbitrary workflow in this repo) so a deploy never accepts an image
    that workflow itself would not have signed for this target.
    """
    full_ref = f"{image_ref}@{digest}"
    ref_pattern = _ALLOWED_REF_PATTERNS.get(environment, _ALLOWED_REF_PATTERNS["dev"])
    identity_regexp = (
        rf"^https://github\.com/{re.escape(repository)}/{re.escape(_SIGNER_WORKFLOW_PATH)}"
        rf"@(?:{ref_pattern})$"
    )
    result = subprocess.run(
        [
            "cosign",
            "verify",
            "--certificate-identity-regexp",
            identity_regexp,
            "--certificate-oidc-issuer",
            "https://token.actions.githubusercontent.com",
            full_ref,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DeployError(
            "CI-DEP-001",
            f"cosign verify failed for {full_ref}: {result.stderr.strip()[:500]}",
        )


def render_env_file(
    env_example_path: Path,
    env_out_path: Path,
    *,
    image_ref: str,
    image_digest: str,
    git_sha: str,
) -> None:
    """Render `.env` from `.env.example` plus the image and sha for this deploy.

    Never invents new secret-like values (SR-140/SR-144): every CV_* value
    besides the build-metadata values below comes verbatim from the
    committed `.env.example` (demo/fixture defaults only, per that file's
    own header) so a rendered dev deploy never introduces a value CI itself
    fabricated.
    """
    lines = env_example_path.read_text(encoding="utf-8").splitlines()
    rendered: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            rendered.append(line)
            continue
        key = stripped.split("=", 1)[0]
        if key == "CV_GIT_SHA":
            rendered.append(f"CV_GIT_SHA={git_sha}")
            seen.add(key)
            continue
        rendered.append(line)
        seen.add(key)
    rendered.append(f"CV_API_IMAGE_REF={image_ref}")
    rendered.append(f"CV_IMAGE_DIGEST={image_digest}")
    env_out_path.write_text("\n".join(rendered) + "\n", encoding="utf-8")


def _compose_args(compose_files: tuple[str, ...], profile: str) -> list[str]:
    """The `docker compose` argv prefix `up` and `ps` share, so both address one project."""
    args = ["docker", "compose"]
    for f in compose_files:
        args += ["-f", f]
    return [*args, "--profile", profile]


def compose_up(
    compose_files: tuple[str, ...], *, image_ref: str, digest: str, profile: str = "core"
) -> None:
    """`up -d --wait --no-build`, so nothing is built, with the verified ref and digest set in
    compose's own environment: they win over `.env` and the runner's environment when compose
    interpolates the deploy overlay's `image:`. CI-DEP-002 if `up` fails."""
    args = [*_compose_args(compose_files, profile), "up", "-d", "--wait", "--no-build"]
    env = {**os.environ, "CV_API_IMAGE_REF": image_ref, "CV_IMAGE_DIGEST": digest}
    result = subprocess.run(args, capture_output=True, text=True, check=False, env=env)
    if result.returncode != 0:
        raise DeployError(
            "CI-DEP-002",
            f"docker compose up --wait failed: {result.stderr.strip()[:1000]}",
        )


def _get_json(url: str, timeout_s: float = 3.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


# Each query prints one field (`{{.Image}}`, `{{.Id}}`), checked before use: no other part of the
# container's configuration (its environment holds credentials, C-12.2, C-12.6) is ever read.
_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{12,64}")
_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
_DOCKER_QUERY_TIMEOUT_S = 20.0


def _docker_query(args: list[str], what: str) -> str:
    """Run one read-only docker query; CI-DEP-002 (never echoing stdout) if it cannot complete."""
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=_DOCKER_QUERY_TIMEOUT_S
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError) as exc:
        raise DeployError("CI-DEP-002", f"{what} did not complete: {type(exc).__name__}") from exc
    if result.returncode != 0:
        raise DeployError(
            "CI-DEP-002",
            f"{what} failed (exit {result.returncode}): {result.stderr.strip()[:300]}",
        )
    return result.stdout


def _one_image_id(answer: str, what: str) -> str:
    """The one `sha256:<64 hex>` line `what` printed, else CI-DEP-002 (never repeating it)."""
    lines = [line for line in answer.splitlines() if line.strip()]
    if len(lines) != 1 or not _IMAGE_ID_RE.fullmatch(lines[0]):
        raise DeployError(
            "CI-DEP-002", f"{what} did not print exactly one image id ({len(lines)} line(s))"
        )
    return lines[0]


def image_id_of(image: str) -> str:
    """The docker daemon's image id for `image`; `docker image inspect` reads images only."""
    what = f"docker image inspect {image}"
    answer = _docker_query(["docker", "image", "inspect", "--format", "{{.Id}}", image], what)
    return _one_image_id(answer, what)


def running_image_id(compose_files: tuple[str, ...], *, profile: str = "core") -> str:
    """The image id of the one running `api` container, else CI-DEP-002 (fail closed)."""
    ids = _docker_query(
        [*_compose_args(compose_files, profile), "ps", "-q", "api"], "docker compose ps -q api"
    ).split()
    if len(ids) != 1 or not _CONTAINER_ID_RE.fullmatch(ids[0]):
        raise DeployError(
            "CI-DEP-002",
            f"no single running api container: docker compose ps -q api printed {len(ids)} "
            "value(s), not exactly one container id",
        )
    what = "docker inspect --type container"
    answer = _docker_query(
        ["docker", "inspect", "--type", "container", "--format", "{{.Image}}", ids[0]], what
    )
    return _one_image_id(answer, what)


def check_running_image(
    compose_files: tuple[str, ...], image: str, *, profile: str = "core"
) -> str:
    """Check that the running `api` container runs `image`, and return its image id.

    Both ids are the docker daemon's (the image config digest on the classic image store, the
    manifest or index digest on the containerd image store), so they are compared with each
    other, never with the registry digest. CI-DEP-003 names both when they differ.
    """
    running = running_image_id(compose_files, profile=profile)
    expected = image_id_of(image)
    if running != expected:
        raise DeployError(
            "CI-DEP-003",
            f"image mismatch after deploy: the running api container's image id is {running}, "
            f"the image id of {image} is {expected}",
        )
    print(f"smoke: the api container runs {image} (image id {running})")
    return running


def smoke_test(
    base_url: str,
    image: str,
    compose_files: tuple[str, ...],
    *,
    timeout_s: float = 60.0,
) -> None:
    """Poll `/healthz` + `/readyz` until both are ok, then check the running `api` container.

    `check_running_image` must find that it runs `image`, the verified `<ref>@<digest>`. A
    mismatch raises CI-DEP-003 at once: a container's image changes only when it is recreated,
    and `up --wait` has finished. Probes that are not ok and ids that cannot be read (each docker
    query is bounded at 20 s) are retried every 2 s until `timeout_s`, then CI-DEP-002.
    """
    deadline = time.monotonic() + timeout_s
    last_error: str = "no attempt made"  # only ever reported when the loop never ran
    while time.monotonic() < deadline:
        try:
            live = _get_json(f"{base_url}/healthz")
            ready = _get_json(f"{base_url}/readyz")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            time.sleep(2.0)
            continue
        if live.get("status") != "ok" or ready.get("status") != "ok":
            last_error = f"not ready: healthz={live}, readyz={ready}"
            time.sleep(2.0)
            continue
        try:
            check_running_image(compose_files, image)
        except DeployError as exc:
            if exc.code == "CI-DEP-003":
                raise
            last_error = str(exc).removeprefix(f"{exc.code}: ")
            time.sleep(2.0)
            continue
        return
    raise DeployError("CI-DEP-002", f"smoke test timed out after {timeout_s}s: {last_error}")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def deploy(
    *,
    image_ref: str,
    digest: str,
    sha: str,
    environment: str,
    actor: str,
    repository: str,
    env_example: Path,
    env_out: Path,
    compose_files: tuple[str, ...],
    base_url: str,
    ledger_path: Path,
    smoke_timeout_s: float,
    auto_rollback: bool,
) -> int:
    """Run one full deploy attempt; returns a process exit code.

    `auto_rollback` is only ever true for `environment == "dev"` (the
    ticket's "Technical notes": staging failures alert and stop rather than
    auto-recover). Every branch appends exactly one ledger entry for the
    forward attempt, plus one more if a rollback is triggered.
    """
    start = time.monotonic()
    try:
        verify_signature(image_ref, digest, repository=repository, environment=environment)
    except DeployError as exc:
        append_ledger(
            LedgerEntry(
                sha=sha,
                digest=digest,
                environment=environment,
                actor=actor,
                timestamp=_now_iso(),
                outcome="signature-verification-failed",
                duration_s=time.monotonic() - start,
                detail=str(exc),
            ),
            ledger_path,
        )
        print(str(exc), file=sys.stderr)
        return 1

    image = f"{image_ref}@{digest}"
    render_env_file(env_example, env_out, image_ref=image_ref, image_digest=digest, git_sha=sha)

    try:
        compose_up(compose_files, image_ref=image_ref, digest=digest)
        smoke_test(base_url, image, compose_files, timeout_s=smoke_timeout_s)
    except DeployError as exc:
        outcome: Literal["smoke-failed", "sha-mismatch"] = (
            "sha-mismatch" if exc.code == "CI-DEP-003" else "smoke-failed"
        )
        append_ledger(
            LedgerEntry(
                sha=sha,
                digest=digest,
                environment=environment,
                actor=actor,
                timestamp=_now_iso(),
                outcome=outcome,
                duration_s=time.monotonic() - start,
                detail=str(exc),
            ),
            ledger_path,
        )
        print(str(exc), file=sys.stderr)
        if auto_rollback:
            _auto_rollback(
                environment=environment,
                actor=actor,
                repository=repository,
                image_ref=image_ref,
                env_example=env_example,
                env_out=env_out,
                compose_files=compose_files,
                base_url=base_url,
                ledger_path=ledger_path,
                smoke_timeout_s=smoke_timeout_s,
                failed_digest=digest,
            )
        return 1

    append_ledger(
        LedgerEntry(
            sha=sha,
            digest=digest,
            environment=environment,
            actor=actor,
            timestamp=_now_iso(),
            outcome="success",
            duration_s=time.monotonic() - start,
        ),
        ledger_path,
    )
    return 0


def _auto_rollback(
    *,
    environment: str,
    actor: str,
    repository: str,
    image_ref: str,
    env_example: Path,
    env_out: Path,
    compose_files: tuple[str, ...],
    base_url: str,
    ledger_path: Path,
    smoke_timeout_s: float,
    failed_digest: str,
) -> None:
    """Dev-only: restore the last known-good digest after a smoke failure.

    Looks up the previous `success` entry *excluding* the failed attempt we
    just wrote (which itself is not a success), so this never loops back to
    the digest that just failed. The previous digest then goes through what a
    forward deploy does: `cosign verify`, `compose_up` with the same compose
    files and the full smoke test, image-id check included.
    """
    previous_digest = read_last_success_digest(environment, ledger_path)
    if previous_digest is None or previous_digest == failed_digest:
        print(
            "CI-DEP-002: no previous known-good digest to auto-rollback to; "
            "manual intervention required",
            file=sys.stderr,
        )
        return
    start = time.monotonic()
    try:
        verify_signature(image_ref, previous_digest, repository=repository, environment=environment)
        render_env_file(
            env_example,
            env_out,
            image_ref=image_ref,
            image_digest=previous_digest,
            git_sha="rollback",
        )
        compose_up(compose_files, image_ref=image_ref, digest=previous_digest)
        smoke_test(
            base_url, f"{image_ref}@{previous_digest}", compose_files, timeout_s=smoke_timeout_s
        )
    except DeployError as exc:
        append_ledger(
            LedgerEntry(
                sha="unknown",
                digest=previous_digest,
                environment=environment,
                actor=actor,
                timestamp=_now_iso(),
                outcome="smoke-failed",
                duration_s=time.monotonic() - start,
                detail=f"auto-rollback failed: {exc}",
            ),
            ledger_path,
        )
        print(f"auto-rollback failed: {exc}", file=sys.stderr)
        return

    append_ledger(
        LedgerEntry(
            sha="unknown",
            digest=previous_digest,
            environment=environment,
            actor=actor,
            timestamp=_now_iso(),
            outcome="rolled-back",
            duration_s=time.monotonic() - start,
            detail=f"auto-rollback from failed digest {failed_digest}",
        ),
        ledger_path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-ref", required=True, help="e.g. ghcr.io/owner/candleviewer-api")
    parser.add_argument("--digest", required=True, help="sha256:... digest to deploy")
    parser.add_argument("--sha", required=True, help="git sha the digest was built from")
    parser.add_argument("--environment", default="dev", choices=["dev", "staging"])
    parser.add_argument("--actor", required=True)
    parser.add_argument(
        "--repository", required=True, help="owner/repo, for cosign identity regexp"
    )
    parser.add_argument("--env-example", type=Path, default=Path("infra/compose/.env.example"))
    parser.add_argument("--env-out", type=Path, default=Path("infra/compose/.env"))
    parser.add_argument("--compose-file", action="append", dest="compose_files", default=None)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--smoke-timeout-s", type=float, default=60.0)
    parser.add_argument(
        "--no-auto-rollback",
        action="store_true",
        help="disable dev auto-rollback (always disabled for staging regardless of this flag)",
    )
    args = parser.parse_args(argv)

    compose_files = tuple(args.compose_files) if args.compose_files else DEFAULT_COMPOSE_FILES
    auto_rollback = args.environment == "dev" and not args.no_auto_rollback

    return deploy(
        image_ref=args.image_ref,
        digest=args.digest,
        sha=args.sha,
        environment=args.environment,
        actor=args.actor,
        repository=args.repository,
        env_example=args.env_example,
        env_out=args.env_out,
        compose_files=compose_files,
        base_url=args.base_url,
        ledger_path=args.ledger,
        smoke_timeout_s=args.smoke_timeout_s,
        auto_rollback=auto_rollback,
    )


if __name__ == "__main__":
    sys.exit(main())
