"""The `integration` job's repeat step stops at its first failing pass (GH-3167).

The step is the GH-3087 regression check: S2 -> S3b -> S8, five passes against one stack. A
failing pass is only fatal because the runner's default shell is `bash -e {0}`; if that default
ever changed, the step would pass whenever the last pass did. Here the step's own script runs in a
plain `bash` (no `-e`, no profile) with `uv` stubbed, so the script has to say it itself. No
Docker, no network: pytest and the stack are never started.
"""

from __future__ import annotations

import re
import subprocess

import pytest
import yaml

from tests.chaos.storage import _stack as st

pytestmark = pytest.mark.chaos

WORKFLOW = st.REPO / ".github" / "workflows" / "_job-integration.yml"
STEP = "Storage chaos S2, S3b and S8 repeated x5 (GH-3087 regression check)"


def _script() -> str:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    scripts = [s["run"] for job in jobs.values() for s in job["steps"] if s.get("name") == STEP]
    assert len(scripts) == 1, f"expected exactly one step named {STEP!r}, found {len(scripts)}"
    return str(scripts[0])


def _run_step(failing_pass: int) -> subprocess.CompletedProcess[str]:
    """The step's script in a bare `bash`, with `uv` stubbed so its `failing_pass`-th call fails.

    The environment is nothing but a `PATH` that leads nowhere, on purpose. `BASH_ENV` or
    `SHELLOPTS=errexit` inherited from the caller would put `-e` back and let the script pass
    without saying it. With no `PATH` at all bash falls back to a default one and would find the
    real `uv`, or any other real command, without a sound; an empty `PATH` makes it look in the
    current directory. Here a real command is "command not found" and fails the pass, and the
    test with it. The script is builtins and the stub only, so it needs no `PATH`."""
    stub = f'calls=0\nuv() {{ calls=$((calls + 1)); [ "$calls" -ne {failing_pass} ]; }}\n'
    return subprocess.run(
        ["/bin/bash", "--noprofile", "--norc"],
        input=stub + _script(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={"PATH": "/nonexistent"},
    )


@pytest.mark.parametrize(
    ("failing_pass", "ran", "succeeds"),
    [(0, 5, True), (1, 1, False), (3, 3, False), (5, 5, False)],
    ids=["all-pass", "first-fails", "middle-fails", "last-fails"],
)
def test_repeat_step_stops_at_its_first_failing_pass_whatever_the_runners_shell_flags(
    failing_pass: int, ran: int, succeeds: bool
) -> None:
    done = _run_step(failing_pass)
    assert re.findall(r"pass (\d) of 5", done.stdout) == [str(n) for n in range(1, ran + 1)]
    assert (done.returncode == 0) is succeeds, done.stderr
