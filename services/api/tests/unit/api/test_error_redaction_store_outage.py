"""An outage that reaches the global handler is 503 `store_unavailable`, not 500 (#2432)."""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy.exc as sa_exc
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.storage.errors import StorageTierUnavailable

_BOUND = "hunter2-bound-parameter"


class _Orig(Exception):
    def __init__(self, sqlstate: str | None) -> None:
        super().__init__(f"driver says {_BOUND}")
        self.sqlstate = sqlstate


def _client(exc: Exception) -> TestClient:
    app = FastAPI()
    install_error_redaction(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    return TestClient(app, raise_server_exceptions=False)


def _db(cls: type[sa_exc.DBAPIError], state: str | None) -> Exception:
    return cls(f"SELECT {_BOUND}", {"p": _BOUND}, _Orig(state))


@pytest.mark.parametrize("state", ["08006", "57P01"])
@pytest.mark.parametrize("cls", [sa_exc.OperationalError, sa_exc.InterfaceError, sa_exc.DBAPIError])
def test_outage_reaching_global_handler_answers_503(
    cls: type[sa_exc.DBAPIError], state: str
) -> None:
    with capture_logs() as logs:
        r = _client(_db(cls, state)).get("/boom")
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "5"
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    assert body["code"] == "store_unavailable"
    assert body["status"] == 503
    assert body["retry_after_seconds"] == 5
    assert _BOUND not in r.text
    assert [lg["event"] for lg in logs] == ["store_unavailable_unhandled"]
    assert logs[0]["error"] == cls.__name__
    assert logs[0]["sqlstate"] == state
    assert _BOUND not in repr(logs)
    assert "exc_info" not in logs[0]


@pytest.mark.parametrize(
    "exc",
    [
        _db(sa_exc.ProgrammingError, "42601"),
        _db(sa_exc.DataError, "22001"),
        _db(sa_exc.IntegrityError, "23505"),
        _db(sa_exc.DBAPIError, "42601"),
        _db(sa_exc.DBAPIError, None),
        RuntimeError("boom"),
        PermissionError("key file"),
        FileNotFoundError("export dir"),
        TimeoutError(),
    ],
    ids=lambda e: f"{type(e).__name__}-{getattr(getattr(e, 'orig', None), 'sqlstate', '')}",
)
def test_non_outage_error_stays_500(exc: Exception) -> None:
    r = _client(exc).get("/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "internal_error"
    assert "Retry-After" not in r.headers
    assert _BOUND not in r.text


def test_bare_os_error_keeps_its_traceback_on_the_500() -> None:
    with capture_logs() as logs:
        r = _client(PermissionError("key file")).get("/boom")
    assert r.status_code == 500
    assert [lg["event"] for lg in logs] == ["unhandled_exception"]
    assert "exc_info" in logs[0]


def test_storage_tier_unavailable_reaching_global_handler_answers_503() -> None:
    r = _client(StorageTierUnavailable("postgres")).get("/boom")
    assert r.status_code == 503
    assert r.json()["code"] == "store_unavailable"


def test_sqlstate_not_shaped_like_a_code_is_logged_as_none() -> None:
    with capture_logs() as logs:
        r = _client(_db(sa_exc.OperationalError, "08a;x")).get("/boom")
    assert r.status_code == 503  # an OperationalError is an outage by its class
    assert logs[0]["sqlstate"] is None


@pytest.mark.parametrize("exc", [ConnectionRefusedError(), ConnectionResetError()], ids=repr)
def test_a_refused_or_reset_socket_reaching_global_handler_answers_503(exc: Exception) -> None:
    # The unit of work lets the driver's raw socket error through while Postgres is down.
    r = _client(exc).get("/boom")
    assert r.status_code == 503
    assert r.json()["code"] == "store_unavailable"
