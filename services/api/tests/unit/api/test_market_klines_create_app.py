"""#2087 security follow-up: `/market/klines` through the REAL app factory (`create_app`, fake
storage backend), so the app-wide `install_error_redaction` handler is in the path. The S1 leak
slipped past tests built on a bare `FastAPI()`; this pins the production behaviour.

Out-of-range `limit` fires in FastAPI before the handler -> the redaction handler's 422 Problem.
The garbage cursor: the fake backend has no identity provider, so `create_app` composes no
session resolver and the route fails closed (501 Problem) before `decode_cursor`; either way no
response may echo the value. The 400 `invalid_cursor` decode path is pinned in
`tests/contract/test_market_klines_contract.py`.

#2092: the deployed routes authorise through the session-backed resolver, the same one
`/market/bars` and the sibling market routers use (C-12.4). `x-rbac` is `marketdata:read` with
scope `none`: market data is public, not account-scoped, so there is no cross-account (IDOR)
surface to pin; two holders of the permission are served the same candles. Authorisation comes
first: a caller the route refuses reaches no catalogue lookup, read service (which can start
an exchange backfill) or store read, and is never told a symbol is unlisted (422).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from candleviewer import app as app_module
from candleviewer.api._generated.openapi_models import KlineResponse, Problem
from candleviewer.app import create_app
from candleviewer.auth.errors import SessionNotFound
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.kline_read import KlineRead, KlineRowLike
from candleviewer.settings import Settings
from candleviewer.storage.models import TimeRange
from candleviewer.storage.repositories.rows import KlineRow
from tests._corpus import rest
from tests.unit.auth.auth_fakes import MFA_PROVED_AT, FullUsers

_LIMIT = "987654321"
_CURSOR = "GARBAGE-cursor-" + "Z" * 140


def test_out_of_range_limit_and_garbage_cursor_are_problems_without_echo() -> None:
    app = create_app(Settings(git_sha="test", version="0.0.0-test"))
    client = TestClient(app, client=("127.0.0.1", 50000))  # on-mesh peer (MeshOnlyMiddleware)
    base = {"symbol": "BTCUSDT", "interval": "1", "from": "2023-11-14T22:00:00Z",
            "to": "2023-11-15T06:00:00Z"}  # fmt: skip
    for params, needle in (
        ({**base, "limit": _LIMIT}, _LIMIT),
        ({**base, "cursor": _CURSOR}, _CURSOR),
    ):
        resp = client.get("/market/klines", params=params)
        assert 400 <= resp.status_code < 600, resp.text
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        Problem.model_validate(body)
        assert "input" not in resp.text and needle not in resp.text, resp.text


# -- #2092: the session resolver is composed for the route --------------------------------------

_SYMBOL = "BTCUSDT"
_READER = "tok-marketdata-reader"  # an active session holding marketdata:read
_PEER_READER = "tok-marketdata-peer"  # another user with the same permission
_ORDERS_ONLY = "tok-orders-only"  # an active session, but no marketdata:read
_READER_ID = uuid.UUID(int=0x2092A)
_USER_OF = {
    _READER: _READER_ID,
    _PEER_READER: uuid.UUID(int=0x2092B),
    _ORDERS_ONLY: uuid.UUID(int=0x2092C),
    # The empty token is a reader too: a resolver that stops refusing it then shows as a 200.
    "": _READER_ID,
}
_PERMISSIONS_OF = {
    str(_USER_OF[_READER]): ["marketdata:read"],
    str(_USER_OF[_PEER_READER]): ["marketdata:read"],
    str(_USER_OF[_ORDERS_ONLY]): ["orders:read"],
}
#: The window holds exactly the three recorded bars 02:23, 02:24 and 02:25 UTC.
_FROM, _TO = "2023-11-15T02:23:00Z", "2023-11-15T02:26:00Z"
_KLINES = {"symbol": _SYMBOL, "interval": "1", "from": _FROM, "to": _TO}
_UNLISTED = "NOPEUSDT"  # a well-formed symbol that is not in the catalogue
_BARS = {"symbol": _SYMBOL, "bar_type": "time", "param": "1", "from": _FROM, "to": _TO}
_ROUTES = [("/market/klines", _KLINES), ("/market/bars", _BARS)]


class _Sessions:
    """`ctx.auth` session seam: a known bearer is a live session, anything else is not."""

    async def authenticate_access_token(self, token: str, **_kw: Any) -> Any:
        user_id = _USER_OF.get(token)
        if user_id is None:
            raise SessionNotFound("unknown token")
        return SimpleNamespace(id=user_id, user_id=user_id, mfa_satisfied_at=MFA_PROVED_AT)


class _Identity:
    """`build_identity_provider` seam: an active user holding the permissions of its token."""

    async def user(self, user_id: str) -> dict[str, Any]:
        return {"username": "reader", "status": "active", "roles": ["viewer"]}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": _PERMISSIONS_OF[user_id]}


@dataclass
class _Reached:
    """What a request got to: the symbols asked of the catalogue, read service and hot store."""

    catalogue: list[str] = field(default_factory=list)
    service: list[str] = field(default_factory=list)
    store: list[str] = field(default_factory=list)


class _Catalogue:
    """The catalogue `_catalogue_listed` consults per request; records each symbol it is asked."""

    def __init__(self, asked: list[str]) -> None:
        self._asked = asked

    def snapshot(self) -> _Catalogue:
        return self

    def get(self, symbol: str) -> SimpleNamespace | None:
        self._asked.append(symbol)
        return SimpleNamespace(status="trading") if symbol == _SYMBOL else None


class _Service:
    """`ctx.ingestion.klines` (it can start a backfill): records each read, serves the store."""

    def __init__(self, reached: _Reached, store: Any) -> None:
        self._reached = reached
        self._store = store

    async def read(
        self, symbol: str, interval: str, rng: Range, limit: int | None = None
    ) -> KlineRead:
        self._reached.service.append(symbol)
        window = TimeRange(start_us=rng.start_us, end_us=rng.end_us)
        rows = list[KlineRowLike](
            await self._store.read_klines(symbol, interval, window, limit=limit)
        )
        return KlineRead(rows, ["questdb"], None, [], False)


def _recorded() -> list[list[str]]:
    """Page 0 of the recorded BTCUSDT 1m klines, oldest first.

    Each row is `[startMs, open, high, low, close, volume, turnover]`, as Bybit sends it.
    """
    wire: list[list[str]] = rest("rest/kline_BTCUSDT_1_page0.json")["result"]["list"]
    return sorted(wire, key=lambda r: int(r[0]))


def _stored(wire: list[list[str]]) -> list[KlineRow]:
    return [
        KlineRow(
            ts_us=int(r[0]) * 1000, symbol=_SYMBOL, interval="1",
            open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5], turnover=r[6],
            confirmed=True, source="ws",
        )
        for r in wire
    ]  # fmt: skip


def _deployed_client(
    monkeypatch: pytest.MonkeyPatch, reached: _Reached | None = None
) -> TestClient:
    """The deployed factory over a session-shaped fake identity layer (no Postgres, no network),
    in-memory storage started (no lifespan) and the recorded klines stored for a listed symbol.
    With `reached`, a read service is composed and what each request got to is recorded."""
    monkeypatch.setattr(app_module, "build_identity_provider", lambda _settings: _Identity())
    app = create_app(Settings(git_sha="test", version="0.0.0-test"))
    ctx = app.state.app_context
    ctx.auth._sessions = _Sessions()
    ctx.auth._repository = FullUsers()  # #2295: each session is classified as a full one
    asyncio.run(ctx.storage.start(ctx))
    store = ctx.storage.market_data
    asyncio.run(store.write_klines(_stored(_recorded())))
    monkeypatch.setattr(
        ctx.ingestion, "instruments", _Catalogue([] if reached is None else reached.catalogue)
    )
    if reached is not None:
        read_klines = store.read_klines

        async def spy(
            sym: str, interval: str, rng: Any, tier: str = "auto", limit: int | None = None
        ) -> Any:
            reached.store.append(sym)
            return await read_klines(sym, interval, rng, tier, limit=limit)

        monkeypatch.setattr(store, "read_klines", spy)
        monkeypatch.setattr(ctx.ingestion, "klines", _Service(reached, store))
    return TestClient(app, client=("127.0.0.1", 50000))  # on-mesh peer (MeshOnlyMiddleware)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _epoch_ms(rfc3339: str) -> int:
    return int(datetime.fromisoformat(rfc3339).timestamp() * 1000)


def _refusal(resp: Any, status: int, code: str) -> None:
    """A refusal is a catalogued Problem that discloses no market data."""
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    Problem.model_validate(body)
    assert body["code"] == code
    assert "bars" not in body and "meta" not in body, resp.text


def test_klines_marketdata_reader_gets_200_with_the_stored_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _deployed_client(monkeypatch)
    resp = client.get("/market/klines", params=_KLINES, headers=_bearer(_READER))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    KlineResponse.model_validate(body)
    oracle = [r for r in _recorded() if _epoch_ms(_FROM) <= int(r[0]) < _epoch_ms(_TO)]
    assert len(oracle) == 3  # the three recorded 1m bars of the window
    got = [(b["o"], b["h"], b["l"], b["c"], b["v"], b["turnover"]) for b in body["bars"]]
    assert got == [tuple(r[1:7]) for r in oracle]
    opened = [_epoch_ms(b["t"]) for b in body["bars"]]
    assert opened == [int(r[0]) for r in oracle]
    assert body["meta"]["count"] == 3 and body["meta"]["sources"] == ["questdb"]


def test_klines_are_not_account_scoped_two_readers_get_the_same_candles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`x-rbac` scope is `none` (public market data): the permission alone decides, so a second
    user is served the identical body; there is no per-user or per-account slice to leak."""
    client = _deployed_client(monkeypatch)
    first = client.get("/market/klines", params=_KLINES, headers=_bearer(_READER))
    second = client.get("/market/klines", params=_KLINES, headers=_bearer(_PEER_READER))
    assert first.status_code == second.status_code == 200
    assert len(first.json()["bars"]) == 3
    assert first.json()["bars"] == second.json()["bars"]


@pytest.mark.parametrize(("path", "params"), _ROUTES, ids=["klines", "bars"])
def test_session_without_marketdata_read_is_403_and_nothing_is_disclosed(
    monkeypatch: pytest.MonkeyPatch, path: str, params: dict[str, str]
) -> None:
    client = _deployed_client(monkeypatch)
    resp = client.get(path, params=params, headers=_bearer(_ORDERS_ONLY))
    _refusal(resp, 403, "forbidden")


@pytest.mark.parametrize(("path", "params"), _ROUTES, ids=["klines", "bars"])
@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-credentials"),
        pytest.param({"Authorization": f"Basic {_READER}"}, id="valid-token-wrong-scheme"),
        pytest.param({"Authorization": "Bearer "}, id="empty-bearer"),
        pytest.param(_bearer("tok-unknown-session"), id="unknown-session"),
    ],
)
def test_unauthenticated_caller_is_401_and_nothing_is_disclosed(
    monkeypatch: pytest.MonkeyPatch, path: str, params: dict[str, str], headers: dict[str, str]
) -> None:
    client = _deployed_client(monkeypatch)
    _refusal(client.get(path, params=params, headers=headers), 401, "unauthenticated")


def test_bars_authorise_a_marketdata_reader_past_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """`/market/bars` shares the resolver: a reader is past authorisation. The fake backend
    composes no bars reader, so what answers is the 503 `store_unavailable` Problem for that."""
    client = _deployed_client(monkeypatch)
    resp = client.get("/market/bars", params=_BARS, headers=_bearer(_READER))
    assert resp.status_code == 503, resp.text
    body = resp.json()
    Problem.model_validate(body)
    assert body["code"] == "store_unavailable"
    assert body["detail"] == "Bar storage is not ready yet."


#: The callers `/market/klines` refuses, with their refusal (an unknown token is no session).
_REFUSED = [
    pytest.param(None, 401, id="anonymous"),
    pytest.param("tok-unknown-session", 401, id="unknown-token"),
    pytest.param(_ORDERS_ONLY, 403, id="orders-only"),
]


def _klines(client: TestClient, token: str | None, **params: str) -> Any:
    headers = {} if token is None else _bearer(token)
    return client.get("/market/klines", params={**_KLINES, **params}, headers=headers)


@pytest.mark.parametrize(("token", "status"), _REFUSED)
def test_klines_refused_caller_reaches_no_catalogue_lookup_service_or_store_read(
    monkeypatch: pytest.MonkeyPatch, token: str | None, status: int
) -> None:
    """Authorisation runs before the catalogue check, the read service and any store read."""
    reached = _Reached()
    client = _deployed_client(monkeypatch, reached)
    assert _klines(client, token).status_code == status
    assert reached == _Reached()


def test_klines_reader_does_reach_the_catalogue_service_and_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control for the test above: the stand-ins do record an authorised read."""
    reached = _Reached()
    client = _deployed_client(monkeypatch, reached)
    resp = _klines(client, _READER)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["bars"]) == 3
    assert reached.catalogue and reached.service and reached.store


@pytest.mark.parametrize(
    ("token", "status", "asked"),
    [
        pytest.param(None, 401, [], id="anonymous"),
        pytest.param("tok-unknown-session", 401, [], id="unknown-token"),
        pytest.param(_ORDERS_ONLY, 403, [], id="orders-only"),
        pytest.param(_READER, 422, [_UNLISTED], id="reader"),
    ],
)
def test_klines_unlisted_symbol_is_refused_before_it_is_looked_up(
    monkeypatch: pytest.MonkeyPatch, token: str | None, status: int, asked: list[str]
) -> None:
    """Only a reader is told a symbol is not listed (422). Anyone else is refused first, and
    the catalogue is never asked, so it cannot be probed without a `marketdata:read` session."""
    reached = _Reached()
    client = _deployed_client(monkeypatch, reached)
    assert _klines(client, token, symbol=_UNLISTED).status_code == status
    assert reached == _Reached(catalogue=asked)


@pytest.mark.parametrize(("path", "params"), _ROUTES, ids=["klines", "bars"])
@pytest.mark.parametrize("token", [None, _READER], ids=["anonymous", "bearer"])
def test_without_an_identity_provider_every_caller_gets_501_never_the_data(
    path: str, params: dict[str, str], token: str | None
) -> None:
    """The fake backend has no identity provider, so no session can be verified: the route fails
    closed for every caller (deny by default), exactly as `/market/bars` does."""
    app = create_app(Settings(git_sha="test", version="0.0.0-test"))
    client = TestClient(app, client=("127.0.0.1", 50000))
    headers = {} if token is None else _bearer(token)
    _refusal(client.get(path, params=params, headers=headers), 501, "internal_error")
