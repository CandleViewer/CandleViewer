#!/usr/bin/env python3
"""#5113 (E03-T14), CI-INFRA-002/003: run a registry-fetching install with bounded retries.

    python3 tools/ci/registry_retry.py --registry {pypi,npm,ghcr} [--attempts N] [--timeout S]
        [--backoff "S S ..."] -- COMMAND [ARG...]

Runs COMMAND up to N times (default 3). Each attempt is bounded to S seconds (default 300): on
expiry its whole process group is killed and CI-INFRA-003 names the registry and the attempt.
Between attempts it waits the next --backoff value (default "10 30"; the last one repeats). When
every attempt fails, CI-INFRA-002 names the registry, the attempt count and the last cause, and
the exit status is 1; so a registry outage fails the step within N*S seconds plus the waits, with
a clear message, instead of hanging until the job's timeout. A success on a later attempt writes
a `::warning::` and a step-summary line, so a flaky registry is visible on a green run.

REGISTRY_RETRY_ATTEMPTS, REGISTRY_RETRY_TIMEOUT and REGISTRY_RETRY_BACKOFF override the defaults
(the flags win over them); the tests set them to fail fast. The native clients retry single
requests underneath (UV_HTTP_RETRIES / UV_HTTP_TIMEOUT in the workflows, pnpm's fetchRetries /
fetchTimeout in pnpm-workspace.yaml); this wrapper retries the whole install. Why retry rather
than a registry mirror: docs/ci-runbook.md, CI-INFRA-*. Stdlib only; no network of its own.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TextIO

REGISTRIES: Mapping[str, str] = {
    "pypi": "PyPI (pypi.org)",
    "npm": "npm (registry.npmjs.org)",
    "ghcr": "GHCR (ghcr.io)",
}
DEFAULT_ATTEMPTS = 3
DEFAULT_TIMEOUT = 300.0
DEFAULT_BACKOFF = "10 30"
TIMED_OUT = -1


@dataclass(frozen=True)
class Policy:
    attempts: int
    timeout: float
    backoff: tuple[float, ...]


Runner = Callable[[Sequence[str], float], int]


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def run_bounded(cmd: Sequence[str], timeout: float) -> int:
    """Run cmd in its own process group; TIMED_OUT (after killing the group) if it overruns.

    Its own session takes the install out of the runner's signal group, so a cancel or a step
    timeout that stops this wrapper (SIGINT, or SIGTERM through main's handler) kills the group
    too rather than leave it running until the job ends.
    """
    proc = subprocess.Popen(list(cmd), start_new_session=True)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        return TIMED_OUT
    except BaseException:
        _kill_group(proc)
        raise


def _raise_on_term(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


def _number(text: str, what: str, *, whole: bool = False) -> float:
    try:
        value = int(text) if whole else float(text)
    except ValueError:
        raise ValueError(f"{what} must be a number, got {text!r}") from None
    if value < 0 or (whole and value < 1) or (what == "--timeout" and value == 0):
        raise ValueError(f"{what} is out of range: {text!r}")
    return value


def parse_policy(
    attempts: str | None,
    timeout: str | None,
    backoff: str | None,
    env: Mapping[str, str],
) -> Policy:
    a = attempts or env.get("REGISTRY_RETRY_ATTEMPTS") or str(DEFAULT_ATTEMPTS)
    t = timeout or env.get("REGISTRY_RETRY_TIMEOUT") or str(DEFAULT_TIMEOUT)
    b = (
        backoff
        if backoff is not None
        else env.get("REGISTRY_RETRY_BACKOFF", DEFAULT_BACKOFF)
    )
    waits = tuple(_number(w, "--backoff") for w in b.split()) or (0.0,)
    return Policy(
        int(_number(a, "--attempts", whole=True)), _number(t, "--timeout"), waits
    )


def retry(
    registry: str,
    cmd: Sequence[str],
    policy: Policy,
    *,
    runner: Runner = run_bounded,
    sleep: Callable[[float], None] = time.sleep,
    err: TextIO = sys.stderr,
    summary: str | None = None,
) -> int:
    """Run cmd under policy; 0 on the first success, 1 after the last failed attempt."""
    name = REGISTRIES[registry]
    shown = " ".join(cmd)
    cause = ""
    for attempt in range(1, policy.attempts + 1):
        status = runner(cmd, policy.timeout)
        if status == 0:
            if attempt > 1:
                note = f"{name}: `{shown}` succeeded on attempt {attempt} of {policy.attempts}"
                print(f"::warning::{note}", file=err)
                if summary:
                    with open(summary, "a", encoding="utf-8") as fh:
                        fh.write(f"- registry retry: {note}\n")
            return 0
        if status == TIMED_OUT:
            cause = f"timed out after {policy.timeout:g} s"
            print(
                f"CI-INFRA-003: {name}: attempt {attempt} of {policy.attempts} of `{shown}` "
                f"{cause}; its processes were killed",
                file=err,
            )
        else:
            cause = f"exit status {status}"
            print(
                f"{name}: attempt {attempt} of {policy.attempts} of `{shown}` failed ({cause})",
                file=err,
            )
        if attempt < policy.attempts:
            sleep(policy.backoff[min(attempt - 1, len(policy.backoff) - 1)])
    print(
        f"CI-INFRA-002: install from {name} failed after {policy.attempts} attempts "
        f"(last: {cause}): `{shown}`. A registry outage on the runner's side: re-run the job; "
        "never raise a timeout or the attempt budget for it (docs/ci-runbook.md, CI-INFRA-*)",
        file=err,
    )
    return 1


def main(
    argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None
) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", required=True, choices=sorted(REGISTRIES))
    parser.add_argument("--attempts")
    parser.add_argument("--timeout")
    parser.add_argument("--backoff")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    cmd = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not cmd:
        parser.error("no command given after --")
    try:
        policy = parse_policy(args.attempts, args.timeout, args.backoff, env)
    except ValueError as exc:
        parser.error(str(exc))
    previous = signal.signal(signal.SIGTERM, _raise_on_term)
    try:
        return retry(args.registry, cmd, policy, summary=env.get("GITHUB_STEP_SUMMARY"))
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
