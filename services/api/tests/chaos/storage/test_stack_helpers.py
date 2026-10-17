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


class _Conn:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.closed = False

    async def execute(self, sql: str) -> str:
        self.queries.append(sql)
        return "SELECT 1"

    async def close(self) -> None:
        self.closed = True


async def test_pg_up_is_true_once_a_query_is_answered_and_closes_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, dsns = _Conn(), []

    async def connect(dsn: str, **kwargs: object) -> _Conn:
        dsns.append(dsn)
        return conn

    monkeypatch.setattr(asyncpg, "connect", connect)
    assert await st.pg_up() is True
    assert conn.queries == ["SELECT 1"]
    assert conn.closed
    assert dsns[0].startswith("postgresql://")  # asyncpg takes the bare scheme, not +asyncpg


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
