"""Unit (E42-T05 #966 BK-11): `GET /admin/backups/{backupId}/download/{token}` over HTTP. No bearer
is needed; a sent one must resolve (401, nothing spent) and names the only user who can match. A
malformed `backupId` or token is 404, never 422, never echoed. Each refusal is its registered
problem, every 410 the contract's `used` body. The artefact goes once, as an attachment named
after the backup, closed whether or not its stream starts, cut when it stalls, closes under a read
or changes size. Every answer to the path is no-store and no-referrer."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, Request
from starlette.types import ASGIApp, Receive, Scope, Send
from structlog.testing import capture_logs

from candleviewer.admin.backups import limits
from candleviewer.admin.backups.downloads import Fetched
from candleviewer.api import admin_backup_download as route
from candleviewer.audit.access import AuditPrincipal
from candleviewer.net import RESOLVED_SOURCE_KEY
from candleviewer.storage.backup_artefacts import ArtefactUnreadable, LocalArtefactStore
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.admin._admin_fakes import principal
from tests.unit.admin._backup_fakes import row
from tests.unit.admin._link_fakes import Reader
from tests.unit.admin.test_backup_fetch import BID, Fx, _fx

_OPERATION = SPEC["paths"]["/admin/backups/{backupId}/download/{token}"]["get"]
_USED = _OPERATION["responses"]["410"]["content"]["application/problem+json"]["examples"]["used"]
_CONTENT = b"age-encrypted artefact"


class _Bearers:  # `Bearer <role>` resolves to that role's principal; anything else to none
    async def resolve(self, request: Request) -> AuditPrincipal | None:
        role = request.headers.get("authorization", "").removeprefix("Bearer ")
        return principal(role) if role in ("owner", "manager") else None


class _Artefact:  # an open artefact streaming `chunks` against its resolved `size`
    def __init__(self, size: int, *chunks: bytes | Exception) -> None:
        self.size, self.chunks, self.closed = size, chunks, 0

    async def stream(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            if chunk == b"stall":
                await asyncio.Event().wait()
            yield chunk

    def close(self) -> None:
        self.closed += 1


class _Fixed:  # the reader resolving every location to one artefact
    def __init__(self, artefact: _Artefact) -> None:
        self.artefact = artefact

    async def resolve(self, location: str) -> _Artefact:
        return self.artefact


async def _mount(
    tmp_path: Path, reader: Any = None, *, wired: bool = True, bearers: bool = True, **kw: Any
) -> tuple[Fx, FastAPI]:
    (tmp_path / "1.age").write_bytes(_CONTENT)
    reader = LocalArtefactStore(str(tmp_path)) if reader is None else reader
    fx = await _fx(rows=[row(1, target_path=f"{tmp_path}/1.age")], reader=reader, **kw)
    app = FastAPI()
    served, resolver = fx.w.downloads if wired else None, _Bearers() if bearers else None
    app.include_router(route.make_admin_backup_download_router(served, resolver=resolver))
    app.add_middleware(route.NoStoreNoReferrer)
    return fx, app


async def _get(app: FastAPI, token: str, backup: object = BID, **headers: str) -> httpx.Response:
    async with (
        asyncio.timeout(2.0),  # a safety net only: no test waits on it when the route is right
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c,
    ):
        return await c.get(f"/admin/backups/{backup}/download/{token}", headers=headers)


def _refused(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    body: dict[str, Any] = response.json()
    assert (response.status_code, body["code"]) == (status, code), body
    assert response.headers["content-type"] == "application/problem+json"
    assert str(status) in _OPERATION["responses"] and "/download/" not in body["detail"]
    stamps = response.headers["cache-control"], response.headers["referrer-policy"]
    assert stamps == ("no-store", "no-referrer")
    validate_example("/components/schemas/Problem", body)
    return body


async def test_a_link_serves_the_artefact_once_as_an_attachment_then_is_410(tmp_path: Path) -> None:
    fx, app = await _mount(tmp_path)
    token, _ = await fx.issue()
    served = await _get(app, token)
    assert (served.status_code, served.content) == (200, _CONTENT)
    assert dict(served.headers) == {
        "content-disposition": f'attachment; filename="cv-backup-pg_dump-{BID}.age"',
        "content-type": "application/octet-stream", "content-length": str(len(_CONTENT)),
        "x-content-type-options": "nosniff", "cache-control": "no-store",
        "referrer-policy": "no-referrer",
    }  # fmt: skip
    assert _refused(await _get(app, token), 410, "gone") == _USED["value"]
    assert [r["reason"] for r in fx.served()] == [None, "link_reused"]


@pytest.mark.parametrize(
    ("backup", "token"),
    [("not-a-uuid", "A" * 43), (BID, "A" * 21), (BID, "A" * 65), (BID, "A" * 42 + "!"),
     (str(BID).replace("-", ""), "A" * 43), (f"{BID}0", "A" * 43)],
    ids=["backup", "short", "long", "charset", "unhyphenated", "trailing"],
)  # fmt: skip
async def test_a_malformed_backup_id_or_token_is_404_not_422_and_never_echoed(
    tmp_path: Path, backup: object, token: str
) -> None:
    fx, app = await _mount(tmp_path)
    issued, _ = await fx.issue()
    body = _refused(await _get(app, token, backup), 404, "not_found")
    assert token not in str(body) and str(backup) not in str(body)
    assert not fx.spent(issued) and fx.served() == []


async def test_a_bearer_is_optional_but_one_sent_must_resolve_and_names_its_user(
    tmp_path: Path,
) -> None:
    fx, app = await _mount(tmp_path)
    token, _ = await fx.issue()
    _refused(await _get(app, token, Authorization="Bearer stale"), 401, "unauthenticated")
    _refused(await _get(app, token, Authorization="Bearer manager"), 404, "not_found")
    assert not fx.spent(token)
    rid = "00000000-0000-4000-8000-0000000000aa"
    served = await _get(app, token, Authorization="Bearer owner", **{"x-request-id": rid})
    (record,) = fx.served()
    assert (served.status_code, record["after_state"]["bearer"]) == (200, "matched")
    assert (record["actor_ip"], str(record["request_id"])) == ("127.0.0.1", rid)


async def test_a_sent_bearer_with_no_resolver_wired_is_401_and_spends_nothing(
    tmp_path: Path,
) -> None:
    fx, app = await _mount(tmp_path, bearers=False)
    token, _ = await fx.issue()
    _refused(await _get(app, token, Authorization="Bearer owner"), 401, "unauthenticated")
    assert not fx.spent(token) and fx.served() == []


class _Admitted:  # MeshOnly's admitted address (a trusted proxy's client), not the socket peer
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope.setdefault("state", {})[RESOLVED_SOURCE_KEY] = "100.64.0.7"
        await self.app(scope, receive, send)


async def test_the_records_name_the_address_mesh_only_admitted_not_the_socket_peer(
    tmp_path: Path,
) -> None:
    fx, app = await _mount(tmp_path)
    app.add_middleware(_Admitted)
    token, _ = await fx.issue()
    assert (await _get(app, token)).status_code == 200
    assert [r["actor_ip"] for r in fx.served()] == ["100.64.0.7"]


@pytest.mark.parametrize(
    ("setup", "status", "code"),
    [("unmounted", 501, "not_implemented"), ("unwired", 501, "not_implemented"),
     ("hour", 429, "rate_limited"), ("misses", 429, "rate_limited"),
     ("forbidden", 403, "forbidden"), ("deleted", 409, "conflict"),
     ("volume", 503, "store_unavailable"), ("audit", 503, "audit_unavailable")],
)  # fmt: skip
async def test_each_refusal_is_its_registered_problem(
    tmp_path: Path, setup: str, status: int, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = Reader() if setup == "volume" else None
    fx, app = await _mount(tmp_path, reader, wired=setup != "unmounted",
                           permissions=() if setup == "forbidden" else ("backups:read",),
                           fetched=10 if setup == "hour" else 0)  # fmt: skip
    token, _ = await fx.issue()
    if setup == "unwired":
        monkeypatch.setattr(fx.w.downloads, "_fetch", None)
    elif setup == "deleted":
        fx.w.store.rows = [row(1, target_path=f"{tmp_path}/1.age", deleted_at=row(1).started_at)]
    elif setup == "volume":
        fx.w.reader.error = ArtefactUnreadable()
    elif setup == "audit":
        monkeypatch.setattr(fx.w.downloads, "audit_serve", _unwritten)
    for _ in range(11 if setup == "misses" else 0):
        await _get(app, "B" * 43)
    response = await _get(app, "B" * 43 if setup == "misses" else token)
    body = _refused(response, status, code)
    retry = {"hour": 3600, "misses": 60, "volume": 5, "audit": 5}.get(setup)
    assert body.get("retry_after_seconds") == retry
    assert response.headers.get("retry-after") == (None if retry is None else str(retry))
    rule = {"field": "", "rule": "backup_not_usable", "message": body["detail"]}
    assert body.get("errors") == ([rule] if status == 409 else None)


async def _unwritten(record: Any) -> None:
    raise OSError("WAL unwritable")


async def test_every_answer_to_the_path_is_no_store_and_no_referrer(tmp_path: Path) -> None:
    """The route's (a decoded newline in the token too: Starlette routes `[^/]+`), the router's
    `405` and its trailing-slash `307` (its `Location` holds the token), its `404` for an empty
    `backupId` (SEC-BK11-R3-01), and under `/api/v1`; not a path the route never serves, nor any
    other path."""
    _, app = await _mount(tmp_path)
    path, token = f"/admin/backups/{BID}/download/{'A' * 43}", "A" * 43
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        answers = [await c.post(path), await c.get(f"{path}%0A"), await c.get(f"/api/v1{path}"),
                   await c.get(f"{path}/"), await c.get(f"/admin/backups//download/{token}"),
                   await c.get(f"{path}/more"), await c.get("/admin/backups")]  # fmt: skip
    stamped = [(a.status_code, a.headers.get("cache-control"), a.headers.get("referrer-policy"))
               for a in answers]  # fmt: skip
    assert stamped == [(405, "no-store", "no-referrer"), (404, "no-store", "no-referrer"),
                       (404, "no-store", "no-referrer"), (307, "no-store", "no-referrer"),
                       (404, "no-store", "no-referrer"), (404, None, None),
                       (404, None, None)]  # fmt: skip


@pytest.mark.parametrize(
    ("chunks", "error"),
    [((b"stall",), "TimeoutError"), ((ValueError("closed under a read"),), "ValueError"),
     ((ArtefactUnreadable(),), "ArtefactUnreadable"), ((b"short",), "size_changed"),
     ((b"long", b"bytes"), "size_changed")],
    ids=["stalls", "closed", "unreadable", "short", "long"],
)  # fmt: skip
async def test_a_stream_that_stalls_closes_fails_or_changes_size_is_cut_and_closed(
    tmp_path: Path, chunks: tuple[Any, ...], error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(route, "STREAM_READ_BUDGET_S", 0.05)
    artefact = _Artefact(8, *chunks)  # 8 bytes when it was resolved
    fx, app = await _mount(tmp_path, _Fixed(artefact))
    token, _ = await fx.issue()  # the issue resolves it too, and closes it at once
    with capture_logs() as logs, pytest.raises(route.DownloadAborted):
        await _get(app, token)
    assert artefact.closed == 2 and [r["reason"] for r in fx.served()] == [None]
    aborted = [log for log in logs if log["event"] == "admin_backups.download_aborted"]
    assert [log["error"] for log in aborted] == [error]


class _Budgets:  # `asyncio` as the route module sees it, counting each read's budget
    def __init__(self) -> None:
        self.delays: list[float | None] = []

    def timeout(self, delay: float | None) -> Any:
        self.delays.append(delay)
        return asyncio.timeout(delay)

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)


async def test_each_read_of_the_stream_has_its_own_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not one budget for the whole download: a large backup streams for as long as its reads
    keep coming, each within `STREAM_READ_BUDGET_S`."""
    budgets = _Budgets()
    monkeypatch.setattr(route, "asyncio", budgets)
    fx, app = await _mount(tmp_path, _Fixed(_Artefact(6, b"ab", b"cd", b"ef")))
    token, _ = await fx.issue()
    assert (await _get(app, token)).content == b"abcdef"
    assert budgets.delays == [limits.STREAM_READ_BUDGET_S] * 4  # three chunks, then the end


async def test_an_artefact_whose_stream_never_starts_is_closed() -> None:
    artefact = _Artefact(1, b"x")
    response = route._ArtefactResponse(Fetched(BID, "pg_dump", cast(Any, artefact)))

    async def gone(message: Any) -> None:  # the client went before the first byte
        raise RuntimeError("client gone")

    async def never() -> Any:
        await asyncio.Event().wait()

    with pytest.raises(RuntimeError):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, never, gone)
    assert artefact.closed == 1 and limits.STREAM_READ_BUDGET_S == 30.0
