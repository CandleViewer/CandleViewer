"""#3319 B1b (24 §15.8; AD-SC01, AD-SC07): the sidecar's socket. A Unix socket only, 0660 in a
0750 directory; a peer whose uid is not the API's is closed before a byte is read; one request per
connection, bounded in time and size; the peer's EOF cancels the job; progress frames are
non-decreasing and rate-limited; the log names the request, never a location."""

from __future__ import annotations

import ast
import asyncio
import logging
import os
import socket
import stat
import struct
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

import cvbackup
from cvbackup import protocol, server
from cvbackup.ops import OpError
from tests.unit.backup_sidecar._sidecar import (
    config,
    exchange,
    families,
    mode,
    request_frame,
    serving,
    write,
)


class _Hanging:
    """Ops whose every request waits until cancelled, recording that it was."""

    def __init__(self) -> None:
        self.started, self.cancelled = asyncio.Event(), asyncio.Event()

    async def handle(self, request: protocol.Request, progress: Any) -> dict[str, object]:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return {}


async def _serve_ops(sock: str, ops: Any, **kwargs: Any) -> asyncio.Server:
    return await server.Server(ops, api_uid=os.getuid(), **kwargs).start(sock)


async def test_server_socket_mode_is_0660_in_a_0750_dir(tmp_path: Path, sock: str) -> None:
    async with serving(config(tmp_path, sock)):
        assert stat.S_ISSOCK(os.lstat(sock).st_mode) and mode(sock) == 0o660
        assert mode(os.path.dirname(sock)) == 0o750


async def test_server_has_no_inet_listener(tmp_path: Path, sock: str) -> None:
    async with serving(config(tmp_path, sock)) as sidecar:
        assert sidecar.server is not None and families(sidecar.server) == {socket.AF_UNIX}
    names = {"AF_INET", "AF_INET6", "SOCK_DGRAM", "start_server", "create_server", "bind"}
    found = []
    for path in Path(cvbackup.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in names:
                found.append(f"{path.name}:{node.lineno}:{node.attr}")
    assert found == ["server.py:{}:bind".format(_line_of("sock.bind(path)"))]


def _line_of(text: str) -> int:
    source = Path(server.__file__).read_text("utf-8").splitlines()
    return next(n for n, line in enumerate(source, 1) if text in line)


async def test_server_peer_with_other_uid_is_closed_before_read(
    tmp_path: Path, sock: str, caplog: pytest.LogCaptureFixture
) -> None:
    ops = _Hanging()
    listening = await _serve_ops(sock, ops, peer=lambda _: os.getuid() + 1)
    async with listening:
        frames = await exchange(sock, request_frame("plan", {"kind": "pg_dump"}))
    assert frames == [] and not ops.started.is_set()
    assert "cvbackup.peer_refused" in caplog.text


async def test_server_the_real_peer_check_reads_the_kernels_uid(tmp_path: Path, sock: str) -> None:
    left, right = socket.socketpair(socket.AF_UNIX)
    with left, right:
        assert server.peer_uid(left) == os.getuid()

    class _Creds:  # struct ucred: pid_t (signed), uid_t and gid_t (unsigned)
        def getsockopt(self, *_: int) -> bytes:
            return struct.pack("iII", -1, 2**32 - 2, 2**32 - 2)

    assert server.peer_uid(_Creds()) == 2**32 - 2  # type: ignore[arg-type]  # a fake socket
    async with serving(config(tmp_path, sock, api_uid=os.getuid() + 1)):
        assert await exchange(sock, request_frame("plan", {"kind": "pg_dump"})) == []


async def test_server_answers_one_request_then_closes(tmp_path: Path, sock: str) -> None:
    async with serving(config(tmp_path, sock)):
        two = request_frame("plan", {"kind": "pg_dump"}) * 2
        frames = await exchange(sock, two)
    # `plan` never suspends, so it ends in the same turn the peer watch reads the byte behind it:
    # the job's answer wins, a byte past the request cancels only a job still running (below)
    assert [f["t"] for f in frames] == ["ok"]  # the second request is never read


async def test_server_a_pipelined_second_frame_trips_the_peer_watch_and_cancels(sock: str) -> None:
    ops = _Hanging()
    args = {"backup_id": str(uuid.uuid4()), "location": _location()}
    async with await _serve_ops(sock, ops):
        async with asyncio.timeout(5):
            frames = await exchange(sock, request_frame("verify", args) * 2)
            await ops.cancelled.wait()
    assert frames == [] and ops.started.is_set()


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"5\nhello\n", "bad_frame"),
        (b"00012\n", "bad_frame"),
        (b"999999\n", "bad_frame"),
        (b"2\n{}X", "bad_frame"),
    ],
)
async def test_server_a_bad_frame_is_answered_bad_frame_with_the_nil_id(
    tmp_path: Path, sock: str, data: bytes, code: str
) -> None:
    async with serving(config(tmp_path, sock)):
        frames = await exchange(sock, data)
    assert frames == [{"v": 1, "id": protocol.NIL_ID, "t": "error", "code": code}]


async def test_server_version_2_is_refused_with_its_id(tmp_path: Path, sock: str) -> None:
    async with serving(config(tmp_path, sock)):
        frames = await exchange(sock, request_frame("plan", {"kind": "pg_dump"}, v=2))
    assert frames[0]["code"] == "unsupported_version" and frames[0]["id"] != protocol.NIL_ID


async def test_server_slow_header_is_closed_within_budget(
    sock: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(server, "REQUEST_READ_S", 0.05)
    ops = _Hanging()
    async with await _serve_ops(sock, ops):
        reader, writer = await asyncio.open_unix_connection(sock)
        writer.write(b"12")  # and nothing more
        async with asyncio.timeout(5):
            assert await reader.read() == b""
        writer.close()
    assert not ops.started.is_set() and "cvbackup.request_unread" in caplog.text


async def test_server_client_eof_mid_job_cancels_it(sock: str) -> None:
    ops = _Hanging()
    async with await _serve_ops(sock, ops):
        _, writer = await asyncio.open_unix_connection(sock)
        writer.write(request_frame("verify", {"backup_id": str(uuid.uuid4()),
                                              "location": _location()}))  # fmt: skip
        async with asyncio.timeout(5):
            await ops.started.wait()
            writer.close()  # the API restarted, or gave up: the job must stop
            await ops.cancelled.wait()


def _location() -> str:
    return f"/srv/cv/backups/pg_dump/{uuid.uuid4()}.age"


async def test_server_job_past_its_bound_is_deadline(
    sock: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(server.OP_MAX_S, "plan", 0.05)
    ops = _Hanging()
    async with await _serve_ops(sock, ops):
        async with asyncio.timeout(5):
            frames = await exchange(sock, request_frame("plan", {"kind": "pg_dump"}))
    assert frames[-1]["code"] == "deadline" and ops.cancelled.is_set()


async def test_server_an_op_failure_is_its_code_and_a_bug_is_internal_error(
    sock: str, caplog: pytest.LogCaptureFixture
) -> None:
    class Failing:
        async def handle(self, request: protocol.Request, progress: Any) -> dict[str, object]:
            if request.op == "plan":
                raise OpError("runs_capped")
            raise KeyError("/srv/cv/secret-looking-path")

    async with await _serve_ops(sock, Failing()):
        capped = await exchange(sock, request_frame("plan", {"kind": "pg_dump"}))
        args = {"backup_id": str(uuid.uuid4()), "location": _location()}
        broken = await exchange(sock, request_frame("remove", args))
    assert capped[-1]["code"] == "runs_capped" and broken[-1]["code"] == "internal_error"
    assert "KeyError" in caplog.text and "secret-looking-path" not in caplog.text


async def test_server_connections_past_the_bound_are_closed_unread(
    sock: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "MAX_CONNECTIONS", 0)
    ops = _Hanging()
    async with await _serve_ops(sock, ops):
        assert await exchange(sock, request_frame("plan", {"kind": "pg_dump"})) == []
    assert not ops.started.is_set()


async def test_server_logs_the_request_never_its_location(
    tmp_path: Path, sock: str, caplog: pytest.LogCaptureFixture
) -> None:
    async with serving(config(tmp_path, sock)) as sidecar:
        older, location, _ = await sidecar.finished()
        await sidecar.finished()
        with caplog.at_level(logging.INFO, logger="cvbackup"):
            args = {"backup_id": older, "location": location}
            frames = await exchange(sock, request_frame("remove", args))
    assert frames[-1]["t"] == "ok"
    assert f"op=remove backup_id={older} outcome=ok" in caplog.text
    assert location not in caplog.text and sidecar.root.path not in caplog.text


async def test_server_progress_is_non_decreasing_and_at_most_once_a_second() -> None:
    sent: list[bytes] = []
    now = [0.0]

    class Writer:
        def write(self, frame: bytes) -> None:
            sent.append(frame)

    progress = server._Progress(Writer(), str(uuid.uuid4()), lambda: now[0])  # type: ignore[arg-type]
    for at, pct in [(0.0, 10.0), (0.5, 20.0), (1.0, 5.0), (1.0, 30.0), (2.5, 250.0)]:
        now[0] = at
        progress(pct)
    values = [protocol.loads(f.split(b"\n")[1], floats=True) for f in sent]
    assert [v["pct"] for v in values if isinstance(v, dict)] == [10.0, 30.0, 100.0]


async def test_server_refuses_a_non_socket_at_its_path(tmp_path: Path, sock: str) -> None:
    write(sock, b"")
    with pytest.raises(ValueError, match="other than a socket"):
        server.listen(sock)
    os.unlink(sock)
    stale = socket.socket(socket.AF_UNIX)
    stale.bind(sock)
    stale.close()  # a socket file left by an earlier process: replaced
    server.listen(sock).close()


def test_server_never_re_modes_a_directory_another_user_owns(
    sock: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = os.path.dirname(sock)
    os.chmod(directory, 0o700)
    uid = os.getuid()
    monkeypatch.setattr(os, "geteuid", lambda: uid + 1)
    with pytest.raises(ValueError, match="owned by the sidecar's user"):
        server.listen(sock)
    assert mode(directory) == 0o700 and not os.path.lexists(sock)


def _filtered(msg: object, *args: object, exc: bool = False) -> logging.LogRecord:
    info = None
    if exc:
        try:
            raise KeyError("/srv/cv/secret-looking-path")
        except KeyError:
            info = sys.exc_info()
    record = logging.LogRecord("cvbackup", logging.ERROR, __file__, 1, msg, args, info)
    assert server.Structural().filter(record)  # admitted, as it is or as its event name alone
    return record


def test_server_log_filter_passes_only_codes_ids_and_ints() -> None:
    rid = str(uuid.uuid4())
    kept = _filtered("cvbackup.request id=%s op=%s outcome=%s ms=%d", rid, "verify",
                     "digest_mismatch", 12)  # fmt: skip
    assert kept.getMessage() == f"cvbackup.request id={rid} op=verify outcome=digest_mismatch ms=12"
    for arg in ("/srv/cv/pg_dump/x.age", "two words", "x" * 65, b"bytes", 1.5, None):
        assert _filtered("cvbackup.op_failed error=%s", arg).getMessage() == (
            "cvbackup.op_failed redacted=args"
        )
    assert _filtered("/srv/cv/a path %d", 1).getMessage() == "cvbackup.log_redacted"
    assert _filtered(KeyError("/srv/cv")).getMessage() == "cvbackup.log_redacted"
    traced = _filtered("cvbackup.connection_failed error=%s", "KeyError", exc=True)
    assert traced.exc_info is None and traced.exc_text is None
