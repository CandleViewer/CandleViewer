"""`configure_logging()` writes the queued records out when the process exits (SR-121 module).

The `QueueListener` thread is a daemon, and `configure_logging()` registers an `atexit` hook that
stops it, which first writes everything still queued. Without the hook a line logged just before
the interpreter exits can still be on the queue and is lost: uvicorn's
`Application startup failed. Exiting.`, the last line before exit code 3, went missing in some
failed starts. The loss is a race at interpreter exit, so it cannot be shown in-process: each run
is a fresh interpreter, 20 of them, with no network and no sleep. Without the hook the line was
lost in every run.

A process ended by a signal (uvicorn re-raises a captured SIGTERM after its graceful shutdown)
does not run `atexit` hooks; that case is not covered here. The hook function itself is also
called directly, in-process, for what the subprocess runs cannot show.
"""

from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

from candleviewer.observability import logging as logging_mod
from candleviewer.observability.logging import configure_logging

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


def test_exit_hook_drops_the_listener_first_and_never_raises() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        configure_logging(env="ci", level="info", fmt="json")
        logging.getLogger("t").info("queued before the hook")
        logging_mod._stop_listener_at_exit()
        assert logging_mod._listener is None  # dropped first: the hook stops each listener once
        logging_mod._stop_listener_at_exit()  # nothing left to stop

        configure_logging(env="ci", level="info", fmt="json")
        assert logging_mod._listener is not None
        logging_mod._listener.stop()  # stopped by hand: `_listener` still names it
        logging_mod._stop_listener_at_exit()  # stopping it again must not raise at exit
        assert logging_mod._listener is None
    events = [json.loads(line)["event"] for line in buf.getvalue().splitlines()]
    assert events == ["queued before the hook"]
