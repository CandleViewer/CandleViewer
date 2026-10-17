"""Compose-stack helpers for the docker chaos scenarios (E07-Q04, C-13.6).

The CI `integration` job brings up `postgres` + `questdb` from
`infra/compose/docker-compose.yml`, mounts a fixed-size loopback image on
the runner for scenario 3b, and runs Alembic before selecting
`-m "chaos and integration"`. Faults are injected with `docker compose
stop/start`; every wait is bounded and polls a condition (no bare sleeps).
The app side runs in-process with the production wiring: the E04-T04
`HealthRegistry` + `register_real_probes` + `PgSystemEventWriter`, and the
E07-T03 `IlpWriter` over a real TCP socket.

`docker compose start` is never trusted to have started anything (GH-3087):
`start_and_wait` re-issues it until the service answers, `stopped` does that on
every exit path, and `ensure_up` lets a scenario refuse to run on a stack that a
predecessor left broken.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import asyncpg

REPO = Path(__file__).resolve().parents[5]
COMPOSE_FILES = (REPO / "infra" / "compose" / "docker-compose.yml",)
QDB_DDL = REPO / "backend" / "db" / "questdb"
HOST = "127.0.0.1"
PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
QDB_PG_PORT = int(os.environ.get("QUESTDB_PG_PORT", "8812"))
QDB_ILP_PORT = int(os.environ.get("QUESTDB_ILP_PORT", "9009"))
#: Loopback-image mount for scenario 3b (created by the CI step, never a real volume).
LOOP_DIR = Path(os.environ.get("CV_CHAOS_LOOPBACK_DIR", "/mnt/cv-chaos-cold"))
LOOP_MAX_BYTES = 128 * 1024 * 1024
#: A `docker compose` call that has not exited within this long is killed and fails loudly.
COMPOSE_TIMEOUT_S = 180.0
#: Poll interval of the restart wait (the same cadence as `until`).
POLL_S = 0.5
#: `start_and_wait` re-issues `compose start` this often until the service answers.
START_RETRY_S = 10.0
#: A whole `pg_up` probe (connect, query and close) is over within this long, whatever the
#: server does.
PG_PROBE_TIMEOUT_S = 5.0

Ready = Callable[[], Awaitable[bool]]


def pg_dsn() -> str:
    pw = os.environ.get("POSTGRES_PASSWORD", "cv")
    return f"postgresql+asyncpg://cv:{pw}@{HOST}:{PG_PORT}/candleviewer"


class ComposeError(RuntimeError):
    """`docker compose` exited non-zero or timed out; the message carries its output."""


@dataclass(frozen=True)
class ComposeResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return (self.stdout + self.stderr).strip()


def _run(argv: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    """The one subprocess call (the seam the unit tests replace with a fake `docker`).

    `errors="replace"`: a stray non-UTF-8 byte in compose's output must not raise a
    `UnicodeDecodeError` (a `ValueError`): it would escape `_diagnostics` and hide the failure."""
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv, capture_output=True, text=True, errors="replace", timeout=timeout_s, check=False
    )


def _text(raw: str | bytes | None) -> str:
    """`TimeoutExpired` hands back bytes even under `text=True`."""
    return raw.decode(errors="replace") if isinstance(raw, bytes) else (raw or "")


def _failure(args: tuple[str, ...], what: str, stdout: str, stderr: str) -> str:
    detail = "\n".join(s.strip()[-2000:] for s in (stderr, stdout) if s.strip())
    return f"docker compose {' '.join(args)}: {what}\n{detail or '<no output>'}"


def _compose(args: tuple[str, ...], timeout_s: float) -> ComposeResult:
    argv = ["docker", "compose", "--profile", "core"]
    for f in COMPOSE_FILES:
        argv += ["-f", str(f)]
    try:
        done = _run([*argv, *args], timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise ComposeError(
            _failure(
                args, f"timed out after {timeout_s:.0f}s", _text(exc.stdout), _text(exc.stderr)
            )
        ) from exc
    result = ComposeResult(args, done.returncode, _text(done.stdout), _text(done.stderr))
    # Re-emit what compose said: its Stopping/Stopped/Starting/Started lines are the only record
    # of what it did, and pytest shows them for a failing test (GH-3087 was diagnosed from them).
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise ComposeError(
            _failure(args, f"exit {result.returncode}", result.stdout, result.stderr)
        )
    return result


async def compose(*args: str, timeout_s: float = COMPOSE_TIMEOUT_S) -> ComposeResult:
    """Run `docker compose <args>`; a non-zero exit or a timeout raises `ComposeError`."""
    return await asyncio.to_thread(_compose, args, timeout_s)


async def until(pred: Callable[[], Awaitable[bool]], what: str, timeout_s: float = 90.0) -> None:
    """Poll `pred` until true; bounded, raises with `what` on timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not await pred():
        if loop.time() >= deadline:
            raise AssertionError(f"timed out after {timeout_s}s waiting for: {what}")
        await asyncio.sleep(0.5)


async def _diagnostics(service: str) -> str:
    """Best-effort `ps -a` and the service's log tail for a failure message; never raises."""
    parts: list[str] = []
    for args in (("ps", "-a"), ("logs", "--no-color", "--tail", "20", service)):
        try:
            res = await compose(*args, timeout_s=30)
        except (ComposeError, OSError) as exc:
            parts.append(f"$ docker compose {' '.join(args)} -> {exc}")
        else:
            parts.append(f"$ docker compose {' '.join(args)}\n{res.output or '<no output>'}")
    return "\n".join(parts)


async def start_and_wait(
    service: str,
    ready: Ready,
    *,
    timeout_s: float = 120.0,
    retry_every_s: float = START_RETRY_S,
    now: Callable[[], float] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Start `service` and block until `ready()` holds; a start that did nothing is re-issued.

    `docker compose start` exits 0 without starting anything when its single up-front container
    listing shows the service as running, or shows no container for it (compose v2.38.2
    `startService` skips both silently). GH-3087: S2 logged `Stopped`, never `Starting`, and
    Postgres stayed down for the rest of the run. A listing that trails a `stop` which has just
    returned fits (Moby publishes the new state to `ContainerList` after `docker stop` returns),
    but that was not captured. Either way the exit status proves nothing, so this polls `ready()`
    and re-issues the idempotent `start` every `retry_every_s` until the service answers or
    `timeout_s` runs out.

    A non-zero exit raises `ComposeError` at once. Running out of time raises `AssertionError`
    carrying `compose ps -a` and the service's log tail. Needing more than one start recovers but
    warns (`RuntimeWarning`): a second call means no answer within `retry_every_s` of the first,
    which a slow start looks like too, so the CI warnings summary is an upper bound on how often
    the quirk fires, not a count of it. A start gets the time left but never less than
    `retry_every_s`, so the one issued at the deadline can finish: with a 1 s floor a slow `start`
    there died as "timed out after 1s" and the failure lost its diagnostics (GH-3167). The deadline
    is only checked once per poll, so the last start can be issued up to `POLL_S` after it and then
    runs for up to `retry_every_s`: it can end at most `retry_every_s + POLL_S` after `timeout_s`
    (10.5 s at the defaults). `now` and `sleep` are injectable so the unit tests drive this on a
    fake clock.
    """
    clock = now or asyncio.get_running_loop().time
    deadline = clock() + timeout_s
    next_start = clock()
    starts = 0
    last: ComposeResult | None = None
    while True:
        if clock() >= next_start:
            budget = max(retry_every_s, deadline - clock())  # the time left, but enough to finish
            last = await compose("start", service, timeout_s=budget)
            starts += 1
            next_start = clock() + retry_every_s
        if await ready():
            if starts > 1:  # recovered, but not for free: show it in the CI warnings summary
                warnings.warn(
                    f"{service} needed {starts} `compose start` calls; no answer within "
                    f"{retry_every_s:.0f}s of an earlier one (GH-3087)",
                    RuntimeWarning,
                    stacklevel=2,
                )
            return
        if clock() >= deadline:
            seen = f"exit {last.returncode}, output {last.output!r}" if last else "never ran"
            raise AssertionError(
                f"{service} not ready {timeout_s:.0f}s after `compose start` ({starts} start(s), "
                f"one every {retry_every_s:.0f}s; last start: {seen})\n"
                f"{await _diagnostics(service)}"
            )
        await sleep(POLL_S)


async def ensure_up(service: str, ready: Ready, *, timeout_s: float = 60.0) -> None:
    """Scenario precondition: `service` answers now, or is started and awaited; never assumed.

    A scenario that died without restarting what it stopped must not hand the next one a dead
    stack (GH-3087: S3b and S8 failed on S2's leftovers). Healing is reported with a warning so a
    leaked fault stays visible; a service that cannot be brought back fails loudly here."""
    if await ready():
        return
    warnings.warn(
        f"{service} was down before the scenario; restarting it", RuntimeWarning, stacklevel=2
    )
    await start_and_wait(service, ready, timeout_s=timeout_s)


@contextlib.asynccontextmanager
async def stopped(service: str, ready: Ready, *, timeout_s: float = 120.0) -> AsyncIterator[None]:
    """Stop `service` for the body, then start it and wait until `ready()` on every exit path."""
    try:
        await compose("stop", service)
        yield
    finally:
        await start_and_wait(service, ready, timeout_s=timeout_s)


async def qdb_connect() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=HOST,
        port=QDB_PG_PORT,
        user="admin",
        password="quest",  # noqa: S106 - QuestDB OSS default, ephemeral CI container
        database="qdb",
    )


async def qdb_up() -> bool:
    with contextlib.suppress(OSError, asyncpg.PostgresError):
        conn = await asyncio.wait_for(qdb_connect(), timeout=3)
        await conn.close()
        return True
    return False


async def pg_up() -> bool:
    """True once Postgres answers a query (an open port alone is only docker-proxy).

    The whole probe, connect to close, is over within `PG_PROBE_TIMEOUT_S` whatever the server does
    (the connect and the query also have 3 s each): one that takes the connection and then stalls
    would otherwise hold this, and so `start_and_wait`'s deadline check, for as long as it likes. A
    probe that does not finish in time is not ready. The close needs the bound too: after a query
    that timed out, asyncpg's `close()` first waits for the server to answer the cancel, which a
    stalled server never does (`close(timeout=)` only bounds what comes after that). The
    `asyncio.timeout` cancels the task once, so nothing is awaited after a failure: the connection
    is dropped with `terminate()`. A `finally: await conn.close()` would run unbounded when the
    deadline lands inside the query, after a slow connect."""
    with contextlib.suppress(OSError, asyncpg.PostgresError, TimeoutError):
        async with asyncio.timeout(PG_PROBE_TIMEOUT_S):
            conn = await asyncpg.connect(pg_dsn().replace("+asyncpg", "", 1), timeout=3)
            try:
                await conn.execute("SELECT 1", timeout=3)
                await conn.close()  # a clean Terminate while the server is behaving
            except BaseException:
                conn.terminate()  # failed, timed out or cancelled: drop it, never await it
                raise
        return True
    return False


class TcpIlpTransport:
    """ILP-over-TCP transport that notices a peer close before writing.

    ILP/TCP has no acks; a write into a socket whose peer already sent FIN
    is silently lost. Checking `at_eof()` first turns that into an error, so
    the writer keeps the batch buffered (exactly-once on reconnect)."""

    def __init__(self) -> None:
        self._r: asyncio.StreamReader | None = None
        self._w: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        # docker-proxy accepts TCP on the published port before QuestDB is
        # listening, and ILP/TCP has no acks, so a bare connect can "succeed"
        # into a void and lose the batch. Require an end-to-end PGWire answer
        # first (finding for the production ILP transport, see #275).
        if not await qdb_up():
            raise ConnectionError("questdb not serving yet")
        self._r, self._w = await asyncio.wait_for(
            asyncio.open_connection(HOST, QDB_ILP_PORT), timeout=3
        )

    async def write(self, data: bytes) -> None:
        if self._r is None or self._w is None or self._r.at_eof() or self._w.is_closing():
            raise ConnectionError("ILP peer closed")
        self._w.write(data)
        await asyncio.wait_for(self._w.drain(), timeout=5)

    async def close(self) -> None:
        if self._w is not None:
            self._w.close()
            with contextlib.suppress(Exception):
                await self._w.wait_closed()
        self._r = self._w = None
