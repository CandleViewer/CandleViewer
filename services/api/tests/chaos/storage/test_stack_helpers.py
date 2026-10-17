"""Unit tests of the chaos stack helpers (GH-3087): no Docker, no network, no real sleeping.

S2 stopped Postgres; `docker compose start postgres` then exited 0 without starting it (compose
v2.38.2 `startService` skips, silently, a container its listing shows as running), nothing
re-issued it, and S3b and S8 failed on the dead stack. The fake `docker` below reproduces that
quirk on demand and a fake clock drives the retry loop, so the regression tests fail on the old
helper (one unchecked `compose start`) and pass on `start_and_wait`, `stopped` and `ensure_up`.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import warnings
from typing import Any

import asyncpg
import pytest

from tests.chaos.storage import _stack as st

pytestmark = pytest.mark.chaos


class FakeDocker:
    """Just enough `docker compose`: a set of running services plus the GH-3087 quirk."""

    def __init__(self, running: set[str]) -> None:
        self.running = set(running)
        self.silent_starts = 0  # the next N `start` calls exit 0, print nothing, start nothing
        self.start_exit = 0  # non-zero: every `start` fails with this exit status
        self.start_takes_s = 0.0  # a `start` given less than this is killed, as subprocess does
        self.start_timeouts: list[float] = []  # the `timeout_s` each `start` was given
        self.calls: list[tuple[str, ...]] = []

    def starts(self) -> list[tuple[str, ...]]:
        return [c for c in self.calls if c[0] == "start"]

    def run(self, argv: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        assert argv[:4] == ["docker", "compose", "--profile", "core"]
        rest = argv[4:]
        while rest[0] == "-f":
            rest = rest[2:]
        args = tuple(rest)
        self.calls.append(args)
        verb, service = args[0], args[-1]
        label = f" Container compose-{service}-1  "

        def done(code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, code, out, err)

        if verb == "stop":
            self.running.discard(service)
            return done(0, err=f"{label}Stopping\n{label}Stopped\n")
        if verb == "start":
            self.start_timeouts.append(timeout_s)
            if timeout_s < self.start_takes_s:
                raise subprocess.TimeoutExpired(argv, timeout_s)
            if self.start_exit:
                return done(
                    self.start_exit, err="Error response from daemon: port is already allocated\n"
                )
            if self.silent_starts > 0:
                self.silent_starts -= 1
                return done(0)
            self.running.add(service)
            return done(0, err=f"{label}Starting\n{label}Started\n")
        if verb == "ps":
            return done(
                0,
                out="NAME STATE\n"
                + "".join(f"compose-{s}-1 running\n" for s in sorted(self.running)),
            )
        if verb == "logs":
            return done(0, out=f"postgres-1  | database system is shut down ({service})\n")
        raise AssertionError(f"unexpected docker compose call: {args}")


class FakeClock:
    """Time that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds
        await asyncio.sleep(0)  # yield to the loop; no real delay


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    fake = FakeDocker({"postgres", "questdb"})
    monkeypatch.setattr(st, "_run", fake.run)
    return fake


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def answers(docker: FakeDocker, service: str) -> st.Ready:
    async def ready() -> bool:
        return service in docker.running

    return ready


# --- compose(): the exit status and the output are never swallowed --------


async def test_compose_non_zero_exit_raises_with_the_subcommand_and_stderr(
    docker: FakeDocker,
) -> None:
    docker.start_exit = 1
    with pytest.raises(st.ComposeError) as exc:
        await st.compose("start", "postgres")
    assert "start postgres" in str(exc.value)
    assert "exit 1" in str(exc.value)
    assert "port is already allocated" in str(exc.value)


async def test_compose_timeout_raises_with_the_partial_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def hang(argv: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        # Python hands the partial output of a timed-out child back as bytes, even with text=True.
        raise subprocess.TimeoutExpired(
            argv, timeout_s, stderr=b" Container compose-postgres-1  Stopping\n"
        )

    monkeypatch.setattr(st, "_run", hang)
    with pytest.raises(
        st.ComposeError, match=r"stop postgres: timed out after 7s\s+Container .*Stopping"
    ):
        await st.compose("stop", "postgres", timeout_s=7)


async def test_compose_re_emits_the_progress_lines_for_pytest_to_keep(
    docker: FakeDocker, capsys: pytest.CaptureFixture[str]
) -> None:
    await st.compose("stop", "postgres")
    assert "Container compose-postgres-1  Stopped" in capsys.readouterr().err


async def test_compose_stop_and_start_target_the_same_project_profile_and_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def record(argv: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(st, "_run", record)
    await st.compose("stop", "postgres")
    await st.compose("start", "postgres")
    stop, start = seen
    assert stop[:-2] == start[:-2]
    assert (stop[-2:], start[-2:]) == (["stop", "postgres"], ["start", "postgres"])


# --- start_and_wait(): a start is verified, never trusted --------


async def test_start_and_wait_starts_once_and_returns_when_the_service_answers(
    docker: FakeDocker, clock: FakeClock
) -> None:
    docker.running.discard("postgres")
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # one start is the normal path and must not warn
        await st.start_and_wait(
            "postgres", answers(docker, "postgres"), now=clock.now, sleep=clock.sleep
        )
    assert docker.starts() == [("start", "postgres")]
    assert clock.t == 0.0


async def test_start_and_wait_does_not_start_again_while_the_first_start_is_settling(
    docker: FakeDocker, clock: FakeClock
) -> None:
    docker.running.discard("postgres")
    polls = 0

    async def ready() -> bool:  # a real Postgres takes a few polls to accept connections
        nonlocal polls
        polls += 1
        return polls > 5 and "postgres" in docker.running

    await st.start_and_wait("postgres", ready, now=clock.now, sleep=clock.sleep)
    assert len(docker.starts()) == 1
    assert clock.t == pytest.approx(2.5)


async def test_start_and_wait_reissues_a_start_that_exited_zero_but_started_nothing(
    docker: FakeDocker, clock: FakeClock
) -> None:
    # GH-3087, attempt 1: `Stopped`, then `start` exit 0 with no `Starting`, Postgres down for good.
    docker.running.discard("postgres")
    docker.silent_starts = 1
    with pytest.warns(RuntimeWarning, match="postgres needed 2 `compose start` calls"):
        await st.start_and_wait(
            "postgres",
            answers(docker, "postgres"),
            retry_every_s=10,
            now=clock.now,
            sleep=clock.sleep,
        )
    assert len(docker.starts()) == 2
    assert clock.t == pytest.approx(10.0)  # re-issued after one retry interval, not in a hot loop


async def test_start_and_wait_gives_up_at_the_bound_and_says_what_it_saw(
    docker: FakeDocker, clock: FakeClock
) -> None:
    docker.running.discard("postgres")
    docker.silent_starts = 10_000
    with pytest.raises(AssertionError) as exc:
        await st.start_and_wait(
            "postgres",
            answers(docker, "postgres"),
            timeout_s=30,
            retry_every_s=10,
            now=clock.now,
            sleep=clock.sleep,
        )
    msg = str(exc.value)
    assert "postgres not ready 30s after `compose start`" in msg
    assert "last start: exit 0, output ''" in msg  # compose reported success and printed nothing
    assert "$ docker compose ps -a" in msg
    assert "$ docker compose logs --no-color --tail 20 postgres" in msg
    assert len(docker.starts()) == 4  # t = 0, 10, 20, 30: bounded, not a hot loop
    assert clock.t == pytest.approx(30.0)


async def test_start_and_wait_raises_at_once_when_compose_start_fails(
    docker: FakeDocker, clock: FakeClock
) -> None:
    docker.running.discard("postgres")
    docker.start_exit = 125
    with pytest.raises(st.ComposeError, match="exit 125"):
        await st.start_and_wait(
            "postgres", answers(docker, "postgres"), now=clock.now, sleep=clock.sleep
        )
    assert len(docker.starts()) == 1
    assert clock.t == 0.0


async def test_start_and_wait_warns_without_naming_a_cause_when_a_slow_start_needs_a_second_call(
    docker: FakeDocker, clock: FakeClock
) -> None:
    # GH-3167: the first start worked, Postgres only answers after 9 s. The 7 s re-issue fires all
    # the same, so the warning cannot say the earlier start "exited 0 without starting it". The
    # interval is not the default (10 s) on purpose: a message built from `START_RETRY_S` instead
    # of the interval the call was given fails here.
    docker.running.discard("postgres")

    async def ready() -> bool:
        return "postgres" in docker.running and clock.t >= 9

    with pytest.warns(RuntimeWarning) as caught:
        await st.start_and_wait(
            "postgres", ready, retry_every_s=7, now=clock.now, sleep=clock.sleep
        )
    assert len(docker.starts()) == 2
    (message,) = [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)]
    assert message.startswith("postgres needed 2 `compose start` calls")
    assert "no answer within 7s of an earlier one" in message
    assert "without starting" not in message  # not known: a slow start trips this warning too


@pytest.mark.parametrize(
    ("timeout_s", "expected"),
    [(30, [30, 20, 10, 10]), (5, [10])],
    ids=["bound-above-a-retry-interval", "bound-below-a-retry-interval"],
)
async def test_start_and_wait_gives_each_start_the_time_left_but_never_less_than_a_retry_interval(
    docker: FakeDocker, clock: FakeClock, timeout_s: float, expected: list[float]
) -> None:
    # GH-3167: the floor was 1 s, so the start at the deadline (t = 30, nothing left) got 1 s.
    docker.running.discard("postgres")
    docker.silent_starts = 10_000
    with pytest.raises(AssertionError):
        await st.start_and_wait(
            "postgres",
            answers(docker, "postgres"),
            timeout_s=timeout_s,
            retry_every_s=10,
            now=clock.now,
            sleep=clock.sleep,
        )
    assert docker.start_timeouts == expected


async def test_start_and_wait_with_a_start_at_the_deadline_still_raises_the_diagnostics(
    docker: FakeDocker, clock: FakeClock
) -> None:
    # GH-3167: with the old 1 s floor, a `compose start` that takes 1.5 s (a slow daemon: modelled
    # here, not observed) died at the deadline as "timed out after 1s", and the failure carried
    # no `ps -a` and no log tail.
    docker.running.discard("postgres")
    docker.silent_starts = 10_000
    docker.start_takes_s = 1.5
    with pytest.raises(AssertionError, match="postgres not ready 30s") as exc:
        await st.start_and_wait(
            "postgres",
            answers(docker, "postgres"),
            timeout_s=30,
            retry_every_s=10,
            now=clock.now,
            sleep=clock.sleep,
        )
    assert len(docker.starts()) == 4  # t = 0, 10, 20 and the one at the deadline, which finished
    assert "$ docker compose ps -a" in str(exc.value)


# --- _diagnostics(): collecting evidence never replaces the failure it describes --------


async def test_diagnostics_report_a_failing_command_and_carry_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(argv: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        if "ps" in argv:  # compose ran and refused: ComposeError
            return subprocess.CompletedProcess(argv, 1, "", "Cannot connect to the Docker daemon\n")
        raise FileNotFoundError(2, "No such file or directory", "docker")  # `logs`: OSError

    monkeypatch.setattr(st, "_run", run)
    text = await st._diagnostics("postgres")
    assert "$ docker compose ps -a -> docker compose ps -a: exit 1" in text
    assert "Cannot connect to the Docker daemon" in text
    assert "$ docker compose logs --no-color --tail 20 postgres -> " in text
    assert "No such file or directory" in text


async def test_diagnostics_never_raise_on_a_non_utf8_byte_in_the_compose_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GH-3167: `text=True` alone raises UnicodeDecodeError, a ValueError that `_diagnostics` does
    # not catch, so a stray byte in a log tail replaced the real failure message. A real child
    # process writes the bytes, so the decode under test is the one `subprocess.run` does in `_run`.
    real_run = st._run
    child = (
        "import sys; sys.stdout.buffer.write(b'ps \\xff\\xfe'); "
        "sys.stderr.buffer.write(b'log \\x80')"
    )

    def run(argv: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        return real_run([sys.executable, "-I", "-c", child], timeout_s)

    monkeypatch.setattr(st, "_run", run)
    text = await st._diagnostics("postgres")
    assert "$ docker compose ps -a\nps \ufffd\ufffdlog \ufffd" in text
    assert "$ docker compose logs --no-color --tail 20 postgres\nps \ufffd\ufffdlog \ufffd" in text


# --- stopped(): the restart happens on every exit path --------


async def test_stopped_runs_the_body_with_the_service_down_then_restarts_it(
    docker: FakeDocker,
) -> None:
    async with st.stopped("postgres", answers(docker, "postgres")):
        assert "postgres" not in docker.running
    assert "postgres" in docker.running
    assert [c[0] for c in docker.calls] == ["stop", "start"]


async def test_stopped_restarts_when_the_body_raises_and_keeps_the_original_error(
    docker: FakeDocker,
) -> None:
    with pytest.raises(ZeroDivisionError):
        async with st.stopped("postgres", answers(docker, "postgres")):
            1 / 0  # noqa: B018 - the body failing is the point
    assert "postgres" in docker.running


async def test_stopped_still_waits_for_the_restart_when_stop_itself_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waited: list[str] = []

    async def stop_fails(*args: str, **kw: Any) -> st.ComposeResult:
        raise st.ComposeError("docker compose stop postgres: timed out after 180s")

    async def record_wait(service: str, ready: st.Ready, **kw: Any) -> None:
        waited.append(service)

    monkeypatch.setattr(st, "compose", stop_fails)
    monkeypatch.setattr(st, "start_and_wait", record_wait)
    with pytest.raises(st.ComposeError, match="timed out"):
        async with st.stopped("postgres", answers(FakeDocker(set()), "postgres")):
            raise AssertionError("the body must not run when stop failed")
    assert waited == ["postgres"]


# --- ensure_up(): no scenario starts on a stack a predecessor left broken --------


async def test_ensure_up_does_nothing_when_the_service_already_answers(docker: FakeDocker) -> None:
    await st.ensure_up("postgres", answers(docker, "postgres"))
    assert docker.calls == []


async def test_ensure_up_restarts_a_service_a_predecessor_left_stopped_and_warns(
    docker: FakeDocker,
) -> None:
    docker.running.discard("postgres")  # what S2 left behind
    with pytest.warns(RuntimeWarning, match="postgres was down before the scenario"):
        await st.ensure_up("postgres", answers(docker, "postgres"))
    assert "postgres" in docker.running


async def test_ensure_up_fails_loudly_when_the_service_cannot_be_started(
    docker: FakeDocker,
) -> None:
    docker.running.discard("postgres")
    docker.start_exit = 1
    with pytest.warns(RuntimeWarning), pytest.raises(st.ComposeError, match="exit 1"):
        await st.ensure_up("postgres", answers(docker, "postgres"))


# --- pg_up(): ready means "answers a query", not "the port is open" --------


async def _no_answer() -> None:
    """Wait for an answer that never comes, but not for ever. A task is cancelled once, so code
    that awaits this again after its own cancel was spent would never leave, and no outer
    timeout could end it: the run would hang with it. Fail loudly instead, as whoever awaits
    this had no bound of its own."""
    try:
        async with asyncio.timeout(1):
            await asyncio.Event().wait()
    except TimeoutError:
        raise AssertionError(
            "awaited an answer that never comes, with no bound of its own"
        ) from None


class _Conn:
    """The slice of an asyncpg connection `pg_up` uses."""

    def __init__(
        self, *, stalls: bool = False, hangs: bool = False, close_hangs: bool = False
    ) -> None:
        self.queries: list[str] = []
        self.timeouts: list[float | None] = []
        self.closed = False
        self.terminated = False
        self.stalls = stalls  # the server took the connection, then never answers the query
        self.hangs = hangs  # ... and the query's own bound is further off than the probe's
        self.close_hangs = close_hangs  # ... and never answers the cancel or the Terminate either

    async def execute(self, sql: str, **kwargs: float | None) -> str:
        timeout = kwargs.get("timeout")  # asyncpg: `Connection.execute(query, *args, timeout=None)`
        self.queries.append(sql)
        self.timeouts.append(timeout)
        if self.hangs:
            await _no_answer()
        if self.stalls:
            # asyncpg raises TimeoutError at its deadline; given none it waits indefinitely.
            assert timeout is not None, "an unbounded query would hang pg_up"
            raise TimeoutError
        return "SELECT 1"

    async def close(self) -> None:
        if self.close_hangs:
            # asyncpg's `close()` first waits for the server to answer the cancel of a timed-out
            # query, which a stalled server never does; after a good one it waits for the server
            # to drop the connection once the Terminate is sent.
            await _no_answer()
        self.closed = True

    def terminate(self) -> None:
        self.terminated = True


def _serve(monkeypatch: pytest.MonkeyPatch, conn: _Conn) -> list[tuple[str, dict[str, object]]]:
    """Make `asyncpg.connect` hand out `conn`; returns the (dsn, kwargs) of every connect."""
    calls: list[tuple[str, dict[str, object]]] = []

    async def connect(dsn: str, **kwargs: object) -> _Conn:
        calls.append((dsn, kwargs))
        return conn

    monkeypatch.setattr(asyncpg, "connect", connect)
    return calls


async def test_pg_up_is_true_once_a_query_is_answered_and_closes_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _Conn()
    calls = _serve(monkeypatch, conn)
    assert await st.pg_up() is True
    assert conn.queries == ["SELECT 1"]
    assert conn.closed
    assert calls[0][0].startswith("postgresql://")  # asyncpg takes the bare scheme, not +asyncpg


async def test_pg_up_bounds_both_the_connect_and_the_query(monkeypatch: pytest.MonkeyPatch) -> None:
    # GH-3167: only the connect had a timeout; a server that took the connection and then stalled
    # would have held `pg_up`, and so `start_and_wait`'s deadline check, for as long as it liked.
    conn = _Conn()
    calls = _serve(monkeypatch, conn)
    assert await st.pg_up() is True
    assert calls[0][1].get("timeout") == 3
    assert conn.timeouts == [3]


async def test_pg_up_is_false_and_drops_the_connection_when_the_query_stalls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _Conn(stalls=True)
    _serve(monkeypatch, conn)
    assert await st.pg_up() is False
    assert conn.terminated  # abandoned, not closed: a stalled server would not answer a close


@pytest.mark.parametrize(
    "conn_kwargs",
    [
        {"stalls": True, "close_hangs": True},
        {"hangs": True, "close_hangs": True},
        {"close_hangs": True},
    ],
    ids=["query-timed-out", "query-outlasts-the-bound", "query-answered"],
)
async def test_pg_up_is_false_within_its_bound_when_the_close_never_returns(
    monkeypatch: pytest.MonkeyPatch, conn_kwargs: dict[str, bool]
) -> None:
    # GH-3167: a server that takes the connection and then stalls never answers the cancel of a
    # timed-out query, so asyncpg's `close()` never returns and `pg_up`, and `start_and_wait`'s
    # deadline check with it, hung. The probe's own bound has to end it, whichever await it is in.
    # `query-outlasts-the-bound`: a slow connect used up the time, so the bound lands inside the
    # query and cancels it, once. Nothing may be awaited after that. A regression fails here
    # through `_no_answer` (an `AssertionError` after 1 s), not by hanging.
    monkeypatch.setattr(st, "PG_PROBE_TIMEOUT_S", 0.05)
    conn = _Conn(**conn_kwargs)
    _serve(monkeypatch, conn)
    assert await st.pg_up() is False
    assert conn.terminated  # dropped, not left open


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError(),
        TimeoutError(),
        asyncpg.PostgresError("the database system is starting up"),
    ],
    ids=["refused", "timeout", "starting-up"],
)
async def test_pg_up_is_false_while_postgres_refuses_or_is_still_starting(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    async def connect(dsn: str, **kwargs: object) -> _Conn:
        raise error

    monkeypatch.setattr(asyncpg, "connect", connect)
    assert await st.pg_up() is False
