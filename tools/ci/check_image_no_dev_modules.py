#!/usr/bin/env python3
"""#2893 S3: a release image carries no dev-only package (CI-IMG-006, ADR-0036 Enforcement).

The account fixture transport lives in `cvdev`, a sibling of `candleviewer` that no wheel and no
`infra/images/Dockerfile.api` stage carries. `candleviewer.account_fixture_wiring` imports it
lazily, only when `CV_ACCOUNT_FIXTURE` is set, and refuses boot when it is absent. This checks a
built image, run the way the trivy job's boot smoke runs it (`--pull never --network none
--read-only --tmpfs /tmp`, `python` in `WORKDIR /app`), twice:

1. `importlib.util.find_spec("cvdev")` is None: the package cannot be imported.
2. A boot (`import candleviewer.server, candleviewer.main`, which runs `Settings()` and
   `create_app()`) with the dev/test values (`CV_ENVIRONMENT=demo`, `CV_FEED=synthetic`, no
   `CV_BYBIT_API_*`) and `CV_ACCOUNT_FIXTURE=compliant` exits non-zero, and the last line of its
   stderr is exactly the package-absent refusal. Anything else fails: a boot that succeeds, and
   any other refusal, a `Settings` one included, since then the fence was never reached.

Only the variables named here reach the container, each as `NAME=value`, never a host value.
`.github/workflows/main.yml` builds the image and passes its local tag with `--image`.

Exit codes: 0 both hold, 1 otherwise (a docker failure included). Stdlib only; runs `docker`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

DEV_PACKAGE = "cvdev"
#: The last traceback line of `AccountFixtureRefused(NO_FIXTURE_TRANSPORT)`, raised by
#: `services/api/candleviewer/account_fixture_wiring.py` when the package is absent.
REFUSAL = (
    "candleviewer.account_fixture_wiring.AccountFixtureRefused: "
    "CV_ACCOUNT_FIXTURE is set but this build carries no fixture transport"
)
FIND_SPEC = f"import importlib.util; print('find_spec:', importlib.util.find_spec('{DEV_PACKAGE}'))"
ABSENT = "find_spec: None"
#: What the boot smoke imports: the ENTRYPOINT module and the ASGI app it serves.
BOOT = "import candleviewer.server, candleviewer.main"
#: #2893 ruling 2's structural dev/test values, and the switch.
BOOT_ENV = ("CV_ENVIRONMENT=demo", "CV_FEED=synthetic", "CV_ACCOUNT_FIXTURE=compliant")
TIMEOUT_S = 120


def _python(image: str, code: str, env: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
    """`python -c code` in a throwaway container of `image`, offline, on a read-only root."""
    cmd = ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only"]
    cmd += ["--tmpfs", "/tmp", "--entrypoint", "python"]
    for pair in env:
        cmd += ["-e", pair]
    return subprocess.run(
        [*cmd, image, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_S,
        check=False,
    )


def _tail(text: str) -> str:
    return "\n".join(text.strip().splitlines()[-12:])


def check(image: str) -> list[str]:
    """What is wrong with `image`: empty when both runs hold."""
    problems: list[str] = []
    spec = _python(image, FIND_SPEC)
    if spec.returncode != 0 or ABSENT not in spec.stdout.splitlines():
        problems.append(
            f"`{DEV_PACKAGE}` must not be importable in the image; the probe exited "
            f"{spec.returncode}:\n{_tail(spec.stdout + spec.stderr)}"
        )
    boot = _python(image, BOOT, BOOT_ENV)
    if boot.returncode == 0 or boot.stderr.strip().splitlines()[-1:] != [REFUSAL]:
        problems.append(
            f"a boot with {' '.join(BOOT_ENV)} must stop with {REFUSAL!r}; it exited "
            f"{boot.returncode}:\n{_tail(boot.stderr)}"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="local tag of the built image")
    args = parser.parse_args(argv)
    try:
        problems = check(args.image)
    except (OSError, subprocess.TimeoutExpired) as exc:
        problems = [f"could not run the image: {exc}"]
    for problem in problems:
        print(f"CI-IMG-006: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"{args.image}: `{DEV_PACKAGE}` is absent, and CV_ACCOUNT_FIXTURE refuses boot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
