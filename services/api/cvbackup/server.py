"""The sidecar's socket server (§15.8 transport and exchange; e42-admin.md §6a AD-SC01, AD-SC07).

A Unix stream socket only: no TCP or UDP listener exists in this package. The socket is created
mode 0660 in a 0750 directory; before reading a byte of a connection the server reads the peer's
credentials (`SO_PEERCRED`) and closes a peer whose uid is not the API's. At most
`MAX_CONNECTIONS` connections are served at once; a further one is closed unread.

One request per connection: the whole request frame within `REQUEST_READ_S`, then zero or more
`progress` frames (non-decreasing, at most one a second), one terminal frame, and the close. The
job runs under `min(deadline_s, OP_MAX_S[op])` (`deadline`). The peer closing its side before the
terminal frame, or writing past its one request, cancels the job: its work stops and, for a run,
its process group ends and its temporary file goes (B1c). Each request is logged with its id, op,
backup id, outcome code and duration only: never a location, other arguments or a child's output.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import stat
import struct
import time
from collections.abc import Callable, Mapping
from typing import Final

from cvbackup import protocol
from cvbackup.ops import OpError, Ops
from cvbackup.tasks import TaskLimit, spawn

OP_MAX_S: Final = {"plan": 2, "remove": 10, "verify": 12 * 3600, "run": 24 * 3600, "restore": 2}
REQUEST_READ_S: Final = 2.0
WRITE_S: Final = 2.0
MAX_CONNECTIONS: Final = 4
PROGRESS_EVERY_S: Final = 1.0
_PEERCRED: Final = struct.Struct("3i")  # pid, uid, gid


def _log() -> logging.Logger:
    return logging.getLogger("cvbackup")


def peer_uid(sock: socket.socket) -> int:
    """The uid of the process at the other end of `sock`, from the kernel (`SO_PEERCRED`)."""
    _, uid, _ = _PEERCRED.unpack(
        sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _PEERCRED.size)
    )
    return int(uid)


def listen(path: str) -> socket.socket:
    """The bound, listening socket at `path`: its directory 0750 and not a link, a stale socket
    replaced, anything else there refused; the socket 0660."""
    directory = os.path.dirname(path)
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("the socket's directory must be a directory, not a link")
    os.chmod(directory, 0o750)  # noqa: S103 - §15.8: the API's group may enter, never write
    with contextlib.suppress(FileNotFoundError):
        if not stat.S_ISSOCK(os.lstat(path).st_mode):
            raise ValueError("something other than a socket is at the socket's path")
        os.unlink(path)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        previous = os.umask(0o177)
        try:
            sock.bind(path)
        finally:
            os.umask(previous)
        os.chmod(path, 0o660)
        sock.listen(MAX_CONNECTIONS)
        sock.setblocking(False)
    except BaseException:
        sock.close()
        raise
    return sock


async def read_frame(reader: asyncio.StreamReader) -> bytes:
    """One frame's body; `ProtocolError` (`bad_frame`) for anything else."""
    header = b""
    while (byte := await reader.readexactly(1)) != b"\n":
        header += byte
        if len(header) > protocol.MAX_HEADER:
            raise protocol.ProtocolError("bad_frame")
    body = await reader.readexactly(protocol.parse_length(header) + 1)
    if body[-1:] != b"\n":
        raise protocol.ProtocolError("bad_frame")
    return body[:-1]


class _Progress:
    """The op's progress callback: non-decreasing, at most one frame per `PROGRESS_EVERY_S`."""

    def __init__(self, writer: asyncio.StreamWriter, request_id: str, clock: Callable[[], float]):
        self._writer, self._id, self._clock = writer, request_id, clock
        self._pct, self._sent_at = 0.0, float("-inf")

    def __call__(self, pct: float) -> None:
        pct = round(min(100.0, max(self._pct, float(pct))), 2)
        now = self._clock()
        if pct > self._pct and now - self._sent_at >= PROGRESS_EVERY_S:
            self._pct, self._sent_at = pct, now
            self._writer.write(protocol.progress(self._id, pct))


class Server:
    def __init__(
        self, ops: Ops, *, api_uid: int, peer: Callable[[socket.socket], int] = peer_uid,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:  # fmt: skip
        self._ops, self._api_uid, self._peer, self._clock = ops, api_uid, peer, clock
        self._active = 0
        self._server: asyncio.Server | None = None

    async def start(self, path: str) -> asyncio.Server:
        self._server = await asyncio.start_unix_server(
            self._connected, sock=listen(path), limit=protocol.MAX_FRAME + 16
        )
        return self._server

    async def _connected(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        admitted = False
        try:
            uid = self._peer(writer.get_extra_info("socket"))
            if uid != self._api_uid:
                _log().warning("cvbackup.peer_refused uid=%d", uid)
                return
            if self._active >= MAX_CONNECTIONS:
                _log().warning("cvbackup.connection_refused active=%d", self._active)
                return
            self._active, admitted = self._active + 1, True
            await self._serve(reader, writer)
        except (OSError, asyncio.IncompleteReadError):
            pass  # the peer is gone: nothing to answer
        except Exception as exc:  # a bug here never takes the server down; its class only
            _log().error("cvbackup.connection_failed error=%s", type(exc).__name__)
        finally:
            self._active -= 1 if admitted else 0
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        started = self._clock()
        try:
            async with asyncio.timeout(REQUEST_READ_S):
                body = await read_frame(reader)
            request = protocol.parse_request(body)
        except TimeoutError:
            _log().warning("cvbackup.request_unread")
            return
        except protocol.ProtocolError as refused:
            self._done(refused.request_id, "-", None, refused.code, started)
            await self._write(writer, protocol.error(refused.request_id or protocol.NIL_ID,
                                                     refused.code))  # fmt: skip
            return
        code, result = await self._dispatch(request, reader, writer)
        self._done(request.id, request.op, request.args.get("backup_id"), code, started)
        if code == "cancelled":
            return
        answer = protocol.ok(request.id, result) if code == "ok" else None
        await self._write(writer, answer or protocol.error(request.id, code))

    async def _dispatch(
        self, request: protocol.Request, reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> tuple[str, Mapping[str, object]]:  # fmt: skip
        progress = _Progress(writer, request.id, self._clock)
        job = spawn(self._job(request, progress), name=f"cvbackup.{request.op}")
        try:  # EOF, or a byte past the one request; a reset is read below, never logged
            peer = spawn(reader.read(1), name="cvbackup.peer", quiet=True)
        except TaskLimit:  # the bound: the job never runs unwatched, the peer gets no answer
            job.cancel()
            raise
        try:
            await asyncio.wait({job, peer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for pending in (job, peer):
                if not pending.done():
                    pending.cancel()
            await asyncio.wait({job, peer})
        if not peer.cancelled():
            peer.exception()  # retrieved: a reset peer is a cancel like any other
        if job.cancelled():
            return "cancelled", {}
        return job.result()

    async def _job(
        self, request: protocol.Request, progress: _Progress
    ) -> tuple[str, Mapping[str, object]]:
        limit = min(request.deadline_s, OP_MAX_S[request.op])
        try:
            async with asyncio.timeout(limit):
                return "ok", await self._ops.handle(request, progress)
        except TimeoutError:
            return "deadline", {}
        except OpError as refused:
            return refused.code, {}
        except Exception as exc:  # its class only, never its text
            _log().error("cvbackup.op_failed op=%s error=%s", request.op, type(exc).__name__)
            return "internal_error", {}

    async def _write(self, writer: asyncio.StreamWriter, frame: bytes) -> None:
        with contextlib.suppress(OSError, TimeoutError):
            writer.write(frame)
            async with asyncio.timeout(WRITE_S):
                await writer.drain()

    def _done(
        self, request_id: str | None, op: str, backup_id: str | None, code: str, started: float
    ) -> None:
        elapsed_ms = int((self._clock() - started) * 1000)
        _log().info(
            "cvbackup.request id=%s op=%s backup_id=%s outcome=%s duration_ms=%d",
            request_id or "-", op, backup_id or "-", code, elapsed_ms,
        )  # fmt: skip
