"""Unit (E42-T05 #966 BK-11): the fetch's token is a credential in its path, so no access log line,
off-mesh record or metric label carries it (`downloadBackup`; AD-I04). The access line goes
through the real `configure_logging()`; the redaction's download-path rule takes it whatever the
token's shape; the off-mesh record keeps the route template, a decoded newline in the token too;
the duration metric the template."""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx
from fastapi import FastAPI

from candleviewer.api.admin_backup_download import make_admin_backup_download_router
from candleviewer.net import MeshOnlyMiddleware
from candleviewer.net.cidr import CidrAllowList
from candleviewer.observability.http_duration import HttpDurationMiddleware
from candleviewer.observability.redaction import redact_text
from tests.unit.observability.test_uvicorn_log_routing import (
    _ACCESS,
    _fresh_uvicorn_loggers,  # noqa: F401
    _replay_boot,
)

_BID = "00000000-0000-4000-8000-000000000001"
#: Assembled at runtime: one of the issued shape (43), one short enough for no other rule (22).
TOKENS = ("".join(("Qx7", "-L" * 20)), "".join(("b9Z", "_k" * 9, "w")))


def test_access_log_line_never_carries_the_token() -> None:
    def emit() -> None:
        access = logging.getLogger("uvicorn.access")
        for backup, token in [(_BID, TOKENS[0]), (_BID, TOKENS[1]), ("", TOKENS[1])]:
            path = f"/api/v1/admin/backups/{backup}/download/{token}"  # an empty id too
            access.info(_ACCESS, "127.0.0.1:50000", "GET", path, "1.1", 410)

    got = _replay_boot(emit)
    assert got.err == "" and len(got.lines()) == 3
    assert not any(token in got.out for token in TOKENS) and _BID not in got.out
    for backup in (_BID, ""):  # SEC-BK11-R3-01: an empty backupId segment is redacted too
        path = f"/admin/backups/{backup}/download/{TOKENS[1]}"
        assert redact_text(path) == "[redacted:download-path]"


class _Sink:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def emit(self, event: str, **fields: Any) -> None:
        self.records.append({"event": event, **fields})


class _Histogram:
    def __init__(self) -> None:
        self.labelled: list[tuple[str, ...]] = []

    def labels(self, *values: str) -> Any:
        self.labelled.append(values)
        return self

    def observe(self, _value: float) -> None: ...


async def test_off_mesh_record_and_metric_label_carry_the_route_template() -> None:
    sink, histogram = _Sink(), _Histogram()
    app = FastAPI()
    app.include_router(make_admin_backup_download_router(None, resolver=None))
    app.add_middleware(
        MeshOnlyMiddleware, allow_list=CidrAllowList(["10.0.0.0/8"]), audit_sink=sink
    )
    app.add_middleware(HttpDurationMiddleware, histogram=cast(Any, histogram))  # a recording fake
    off = ("203.0.113.9", 1)
    calls = [(("10.0.0.9", 1), _BID, ""), (off, _BID, ""), (off, _BID, "%0A"), (off, _BID, "/"),
             (off, "", "")]  # fmt: skip
    for client, backup, tail in calls:  # on the mesh, then off it: plain, a decoded newline, a
        transport = httpx.ASGITransport(app=app, client=client)  # slash, an empty backupId
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            await c.get(f"/admin/backups/{backup}/download/{TOKENS[0]}{tail}")
    template = "/admin/backups/{backupId}/download/{token}"
    records = [record["path"] for record in sink.records]
    assert records == [template, template, f"{template}/", template]
    assert histogram.labelled == [(template, "GET", "5xx")] + [("unmatched", "GET", "4xx")] * 4
    assert TOKENS[0] not in f"{sink.records}{histogram.labelled}"
