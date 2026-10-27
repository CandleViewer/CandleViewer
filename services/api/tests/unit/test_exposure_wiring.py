"""The exposure read's composition-root wiring (E27-S04 B2a, #898).

`PortReader` over the real trading port and the adapter's own `exposure_probe_error`, behind a
scripted `httpx.MockTransport` (no network, C-13.5): each failure is named as 22 says, which the
stripped error alone could not do (a timeout, a reset, an M2 refusal); one key's two calls
combine with the failed read first; every key gets its own port, closed also on cancel; no
exchange text reaches an error or a log line (SR-E27-08, C-12.6); another environment is refused
before any port exists (C-2.11).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer import exposure_wiring as wiring
from candleviewer.accounts.consequences import ConsequenceRead, ConsequenceStores
from candleviewer.accounts.exposure import ExposureKnown, ExposureRead, KeyReadFailed
from candleviewer.accounts.models import (
    AccountKind,
    ApiKeyMetadata,
    AssignedUser,
    ExchangeAccount,
    ExchangeEnv,
    KeyStatus,
    PermissionSnapshot,
)
from candleviewer.accounts.profile_repository import ArmedRule, ArmedRules
from candleviewer.exchange.base.errors import TransportError
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.exchange.bybit.trading import BybitTradingPort
from candleviewer.secrets import (
    CredentialBorrower,
    CredentialUnavailable,
    KekUnavailable,
    RequestSignature,
    SecretsError,
)
from candleviewer.storage.repositories.accounts import AccountScope, OwnerScope
from tests._corpus import rest
from tests._signing import fake_capability
from tests.unit.exchange.bybit._trading import RecordingGovernor

NOW = datetime(2026, 10, 27, tzinfo=UTC)
ACCOUNT = ExchangeAccount(
    id=UUID(int=500), env=ExchangeEnv.DEMO, kind=AccountKind.MAIN, exchange_uid="1000001",
    label="fx-demo", created_at=NOW, updated_at=NOW,
)  # fmt: skip
K1, K2 = UUID(int=1), UUID(int=2)
TEXT = "exchange text that must never be echoed"
POSITIONS, ORDERS = "/v5/position/list", "/v5/order/realtime"
Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]


def _row(**over: str) -> dict[str, Any]:
    row = {**rest("rest/trading-position-list.json")["result"]["list"][0], "symbol": "BTCUSDT"}
    return row | over


def _page(*rows: dict[str, Any]) -> dict[str, Any]:
    return {
        "retCode": 0,
        "result": {"category": "linear", "nextPageCursor": "", "list": list(rows)},
    }


def _orders() -> dict[str, Any]:
    body = rest("rest/trading-order-realtime.json")
    return {**body, "result": {**body["result"], "nextPageCursor": ""}}


def _refused(code: int) -> dict[str, Any]:
    return {"retCode": code, "retMsg": TEXT, "result": {}, "time": 1}


def _venue(**paths: Any) -> Handler:
    """Answers each path: a body, an httpx error to raise, `"hang"` or `(status, body)`."""

    async def handle(request: httpx.Request) -> httpx.Response:
        answer = paths[request.url.path.rsplit("/", 2)[-2]]
        if answer == "hang":
            await asyncio.Event().wait()
        if isinstance(answer, type) and issubclass(answer, httpx.TransportError):
            raise answer(TEXT, request=request)
        if isinstance(answer, tuple):
            return httpx.Response(answer[0], content=answer[1])
        return httpx.Response(200, json=answer)

    return handle


class Venue:
    """The adapter surface: one real port per `exposure_port` call, each over the next handler."""

    exposure_probe_error = staticmethod(ExchangeBybitService.exposure_probe_error)

    def __init__(self, *handlers: Handler, signer: CredentialBorrower | None = None) -> None:
        self.handlers, self.signer = list(handlers), signer or fake_capability("fixture-signer-id")
        self.ports: list[BybitTradingPort] = []
        self.closed: list[BybitTradingPort] = []

    def exposure_port(
        self,
        env: str,
        *,
        on_failure: Callable[[Exception], None],
        clock_offset_ms: Callable[[], int | None] | None = None,
    ) -> BybitTradingPort:
        port = BybitTradingPort(
            environment=env, credentials=self.signer, governor=RecordingGovernor(),
            transport=httpx.MockTransport(self.handlers.pop(0)), max_retries=0,
            clock_offset_ms=clock_offset_ms, on_failure=on_failure,
        )  # fmt: skip
        close = port.aclose

        async def aclose() -> None:
            self.closed.append(port)
            await close()

        port.aclose = aclose  # type: ignore[method-assign]
        self.ports.append(port)
        return port


def _refusing(refusal: SecretsError) -> CredentialBorrower:
    async def sign(_key: UUID, _message: Sequence[object], purpose: str) -> RequestSignature:
        raise refusal

    return CredentialBorrower(sign)


def _reader(venue: Venue) -> wiring.PortReader:
    return wiring.PortReader(venue, "demo", lambda: None)


async def _failure(venue: Venue) -> KeyReadFailed:
    with pytest.raises(KeyReadFailed) as caught:
        await _reader(venue).read(ACCOUNT, K1)
    return caught.value


async def test_port_reader_both_calls_read_positions_and_working_orders() -> None:
    page = _page(_row(stopLoss="58000"), _row(symbol="ETHUSDT", side="Buy", takeProfit="3000"))
    venue = Venue(_venue(position=page, order=_orders()))
    got = await _reader(venue).read(ACCOUNT, K1)
    assert got.working_orders == 1
    assert [(p.symbol, p.side, p.size, p.native_stop_present) for p in got.positions] == [
        ("BTCUSDT", "short", Decimal("300"), True),
        ("ETHUSDT", "long", Decimal("300"), False),
    ]
    assert venue.closed == venue.ports and len(venue.ports) == 1


@pytest.mark.parametrize(
    ("positions", "word", "code"),
    [
        (httpx.ReadTimeout, "timeout", None),
        (httpx.ConnectError, "transport_error", None),
        ((503, b"{}"), "service_unavailable", None),
        (rest("rest/error_10002.json"), "clock_drift", 10002),
        (_refused(10006), "rate_limited", 10006),
        (_refused(33004), "exchange_unknown", 33004),
        (_refused(10003), "auth_error", None),
        (_refused(10010), "ip_not_allowed", None),
        (_refused(10005), "permission_denied", None),
        ((200, b"not json"), "transport_error", None),
    ],
    ids=["timeout", "reset", "http5xx", "10002", "10006", "33004", "10003", "10010", "10005",
         "undecodable"],
)  # fmt: skip
async def test_port_reader_failure_named_as_22(positions: Any, word: str, code: int | None) -> None:
    failed = await _failure(Venue(_venue(position=positions, order=_orders())))
    assert (failed.probe_error, failed.ret_code) == (word, code)
    assert failed.__cause__ is None and failed.__context__ is None


@pytest.mark.parametrize("refusal", [CredentialUnavailable("revoked"), KekUnavailable("down")])
async def test_port_reader_m2_refusal_vault_refused_nothing_sent(refusal: SecretsError) -> None:
    sent: list[httpx.Request] = []

    async def record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=_orders())

    failed = await _failure(Venue(record, signer=_refusing(refusal)))
    assert (failed.probe_error, failed.ret_code, sent) == ("vault_refused", None, [])


async def test_port_reader_one_key_refused_and_timed_out_failed_read_wins() -> None:
    failed = await _failure(Venue(_venue(position=_refused(10003), order=httpx.ReadTimeout)))
    assert failed.probe_error == "timeout"


async def test_port_reader_unreadable_rows_exchange_unknown() -> None:
    bad = {"retCode": 0, "result": {"list": "rows", "nextPageCursor": ""}}
    failed = await _failure(Venue(_venue(position=bad, order=_orders())))
    assert failed.probe_error == "exchange_unknown"


async def test_port_reader_no_exchange_text_in_logs_or_error() -> None:
    with capture_logs() as logs:
        failed = await _failure(Venue(_venue(position=_refused(10006), order=httpx.ConnectError)))
    assert TEXT not in repr(logs) and TEXT not in str(failed) and TEXT not in repr(failed)
    [line] = [e for e in logs if e["event"] == "exposure_key_read_failed"]
    assert line == {
        "event": "exposure_key_read_failed", "log_level": "info", "key_id": str(K1),
        "probe_error": "transport_error",
    }  # fmt: skip


async def test_port_reader_two_keys_of_one_account_never_share_a_port() -> None:
    ok = _venue(position=_page(), order=_orders())
    venue = Venue(ok, ok)
    reader = _reader(venue)
    await asyncio.gather(reader.read(ACCOUNT, K1), reader.read(ACCOUNT, K2))
    assert len(venue.ports) == 2 and venue.ports[0] is not venue.ports[1]
    assert sorted(map(id, venue.closed)) == sorted(map(id, venue.ports))


async def test_port_reader_cancelled_read_closes_its_port() -> None:
    venue = Venue(_venue(position="hang", order="hang"))
    task = asyncio.create_task(_reader(venue).read(ACCOUNT, K1))
    for _ in range(20):
        await asyncio.sleep(0)
    assert venue.ports and not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert venue.closed == venue.ports


async def test_port_reader_first_key_wins_through_exposure_read() -> None:
    venue = Venue(_venue(position="hang", order="hang"), _venue(position=_page(), order=_orders()))
    read = ExposureRead(_reader(venue), env="demo", deadline=lambda _s: contextlib.nullcontext())
    keys = [_key(K1), _key(K2)]
    got = await read.read(ACCOUNT, keys)
    assert got == ExposureKnown(K2, (), 1) and venue.closed and len(venue.closed) == 2


async def test_port_reader_other_environment_refused_before_any_port() -> None:
    venue = Venue()
    with pytest.raises(ValueError, match="environment"):
        await wiring.PortReader(venue, "live", lambda: None).read(ACCOUNT, K1)
    assert venue.ports == []


def _ctx(backend: str) -> Any:
    service = ExchangeBybitService(fake_capability("fixture-signer-id"), environment="demo")
    return SimpleNamespace(
        settings=SimpleNamespace(storage_backend=backend, environment=ExchangeEnv.DEMO),
        exchange_bybit=service,
        ingestion=SimpleNamespace(clock_offset_ms=lambda: 25),
    )


def test_wire_exposure_read_fake_backend_none_real_backend_read() -> None:
    assert wiring.wire_exposure_read(_ctx("fake")) is None
    assert isinstance(wiring.wire_exposure_read(_ctx("real")), ExposureRead)


def _key(key_id: UUID) -> ApiKeyMetadata:
    snapshot = PermissionSnapshot.model_validate({"fetched_at": NOW, "uid": "1", "permissions": {}})
    return ApiKeyMetadata(
        id=key_id, exchange_account_id=ACCOUNT.id, label="k", key_id_last4="AbC1",
        permission_snapshot=snapshot, permission_snapshot_at=NOW, created_at=NOW,
        status=KeyStatus.ACTIVE,
    )  # fmt: skip


async def test_port_reader_slow_close_bounded_and_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiring, "CLOSE_BOUND_S", 0)
    venue = Venue(_venue(position=_page(), order=_orders()))

    def hanging_close(_env: str, **kw: Any) -> BybitTradingPort:
        port = Venue.exposure_port(venue, "demo", **kw)

        async def aclose() -> None:
            await asyncio.Event().wait()

        port.aclose = aclose  # type: ignore[method-assign]
        return port

    monkeypatch.setattr(venue, "exposure_port", hanging_close)
    with capture_logs() as logs:
        got = await _reader(venue).read(ACCOUNT, K1)
    assert got.working_orders == 1
    assert [e for e in logs if e["event"] == "exposure_port_close_slow"] == [
        {"event": "exposure_port_close_slow", "log_level": "warning", "key_id": str(K1)}
    ]


def _with_close(venue: Venue, close: Callable[[], Awaitable[None]]) -> None:
    def make(_env: str, **kw: Any) -> BybitTradingPort:
        port = Venue.exposure_port(venue, "demo", **kw)
        port.aclose = close  # type: ignore[method-assign]
        return port

    venue.exposure_port = make  # type: ignore[method-assign]


async def test_port_reader_close_fault_logged_by_type_and_never_replaces_the_result() -> None:
    venue = Venue(_venue(position=_page(), order=_orders()))

    async def broken() -> None:
        raise RuntimeError(TEXT)

    _with_close(venue, broken)
    with capture_logs() as logs:
        got = await _reader(venue).read(ACCOUNT, K1)
    assert got.working_orders == 1
    assert [e for e in logs if e["event"] == "exposure_port_close_failed"] == [
        {
            "event": "exposure_port_close_failed", "log_level": "warning", "key_id": str(K1),
            "fault": "RuntimeError",
        }
    ]  # fmt: skip
    assert TEXT not in repr(logs)


async def test_port_reader_close_fault_does_not_replace_a_pending_cancel() -> None:
    venue = Venue(_venue(position="hang", order="hang"))

    async def broken() -> None:
        raise RuntimeError(TEXT)

    _with_close(venue, broken)
    task = asyncio.create_task(_reader(venue).read(ACCOUNT, K1))
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_port_reader_double_cancel_still_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wiring, "CLOSE_BOUND_S", 60)
    venue = Venue(_venue(position="hang", order="hang"))
    gate, closed = asyncio.Event(), asyncio.Event()

    async def slow() -> None:
        await gate.wait()
        closed.set()

    _with_close(venue, slow)
    task = asyncio.create_task(_reader(venue).read(ACCOUNT, K1))
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()  # a second cancel lands while the close is still running
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not closed.is_set()
    gate.set()
    await closed.wait()


def test_port_reader_hook_outside_a_call_or_unnamed_failure_records_nothing() -> None:
    reader = _reader(Venue())
    reader._hook(TransportError("outside any call"))
    reader._hook(ValueError("not an adapter failure"))
    assert wiring._NAMED.get() is None


def test_wire_exposure_read_reads_measured_clock_offset() -> None:
    read = wiring.wire_exposure_read(_ctx("real"))
    assert read is not None and read._reader._offset() == 25  # type: ignore[attr-defined]


class _ProfilePorts:
    """A typed `ConsequencePorts`: the store and the armed-rule read in one object, none of
    whose reads the wiring makes."""

    @property
    def accounts(self) -> ConsequenceStores:
        return self

    @property
    def rules(self) -> ArmedRules:
        return self

    async def get_account(self, scope: AccountScope, account_id: UUID) -> ExchangeAccount:
        raise AssertionError("wiring reads nothing")

    async def list_keys(self, scope: OwnerScope, account_id: UUID) -> tuple[ApiKeyMetadata, ...]:
        raise AssertionError("wiring reads nothing")

    async def list_grantees(self, scope: OwnerScope, account_id: UUID) -> tuple[AssignedUser, ...]:
        raise AssertionError("wiring reads nothing")

    async def armed_on(self, account_id: UUID) -> tuple[ArmedRule, ...]:
        raise AssertionError("wiring reads nothing")

    async def covering(self, account_id: UUID, *, limit: int) -> tuple[ArmedRule, ...]:
        raise AssertionError("wiring reads nothing")


async def test_wire_consequence_read_needs_both_wirings_and_no_algo_runs() -> None:
    """#898 B2b: the read exists only with the exposure read and the profile wiring (the fake
    backend has neither: the route answers 503); until E33 no emulated algo runs."""
    read, ports = wiring.wire_exposure_read(_ctx("real")), _ProfilePorts()
    assert wiring.wire_consequence_read(None, ports, env="demo") is None
    assert wiring.wire_consequence_read(read, None, env="demo") is None
    wired = wiring.wire_consequence_read(read, ports, env="demo")
    assert isinstance(wired, ConsequenceRead)
    assert await wiring.NoRunningAlgos().running(UUID(int=1)) == 0
