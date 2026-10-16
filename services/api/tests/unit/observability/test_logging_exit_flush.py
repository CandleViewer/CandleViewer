"""`configure_logging()` writes the queued records out when the process exits (SR-121 module).

The `QueueListener` thread is a daemon, and `configure_logging()` registers an `atexit` hook that
stops it, which first writes everything still queued. Without the hook a line logged just before
the interpreter exits can still be on the queue and is lost: uvicorn's
`Application startup failed. Exiting.`, the last line before exit code 3, went missing in some
failed starts. The loss is a race at interpreter exit, so it cannot be shown in-process: each run
is a fresh interpreter, 20 of them, with no network and no sleep. Without the hook the line was
lost in every run.

A process ended by a signal (uvicorn re-raises a captured SIGTERM after its graceful shutdown)
does not run `atexit` hooks; that case is not covered here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

#: `services/api`: the child imports `candleviewer` from here, as the other subprocess tests do.
_API_ROOT = Path(__file__).resolve().parents[3]
_RUNS = 20
_LINE = "Application startup failed. Exiting."
#: What a failed start does (`uvicorn/lifespan/on.py`, then the exit code of `candleviewer.server`).
_CHILD = f"""
import logging, sys

from candleviewer.observability.logging import configure_logging

configure_logging(env="ci", level="info", fmt="json")
logging.getLogger("uvicorn.error").error({_LINE!r})
sys.exit(3)
"""


def test_last_line_before_a_non_zero_exit_reaches_stdout() -> None:
    wrong: list[str] = []
    for run in range(_RUNS):
        done = subprocess.run(  # noqa: S603 - fixed argv: this interpreter and a literal script
            [sys.executable, "-c", _CHILD],
            cwd=_API_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        events = [json.loads(line)["event"] for line in done.stdout.splitlines()]
        if (done.returncode, events, done.stderr) != (3, [_LINE], ""):
            wrong.append(f"run {run}: exit {done.returncode}, {events}, stderr {done.stderr!r}")
    assert not wrong, f"{len(wrong)} of {_RUNS} runs lost the line: {wrong[:3]}"
