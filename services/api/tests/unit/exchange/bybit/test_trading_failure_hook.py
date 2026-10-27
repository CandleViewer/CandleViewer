"""The trading port's failure hook and the exposure read's adapter surface (E27-S04 B2a, #898).

The hook sees each call's raw failure while its cause is intact (a timeout chains its httpx
timeout; an M2 refusal is still M2's), so the exposure read names it as 22 does; the error that
leaves the port is still stripped of cause, context and the client's frames (SR-E29-08). Without
a hook the port behaves as before. Replies are the corpus's; no network (C-13.5).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import (
    AuthError,
    ExchangeError,
    ServiceUnavailableError,
    TransportError,
)
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.exchange.bybit.trading import BybitTradingPort
from candleviewer.secrets import (
    CredentialBorrower,
    CredentialUnavailable,
    KekUnavailable,
    RequestSignature,
    SecretsError,
    WithdrawPermissionRejected,
)
from tests._corpus import rest
from tests._signing import fake_capability
from tests.unit.exchange.bybit._trading import RecordingGovernor, Venue, account

Seen = list[tuple[type[BaseException], type[BaseException] | None]]


def _port(
    handler: httpx.MockTransport, seen: Seen | None, signer: CredentialBorrower
) -> BybitTradingPort:
    hook = None if seen is None else (lambda raw: seen.append((type(raw), type(raw.__cause__))))
    return BybitTradingPort(
        environment="demo",
        credentials=signer,
        governor=RecordingGovernor(),
        transport=handler,
        max_retries=0,
        on_failure=hook,
    )


def _timing_out(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


def _refusing(refusal: SecretsError) -> CredentialBorrower:
    async def sign(_key: UUID, _message: Sequence[object], purpose: str) -> RequestSignature:
        raise refusal

    return CredentialBorrower(sign)


def _bare(error: BaseException) -> bool:
    return error.__cause__ is None and error.__context__ is None


async def test_failure_hook_timeout_sees_cause_while_raised_error_is_bare() -> None:
    seen: Seen = []
    port = _port(httpx.MockTransport(_timing_out), seen, fake_capability("fixture-signer-id"))
    with pytest.raises(TransportError) as caught:
        await port.positions(account())
    assert seen == [(TransportError, httpx.ReadTimeout)]
    assert _bare(caught.value)


async def test_failure_hook_m2_refusal_sees_m2_error_while_port_raises_taxonomy() -> None:
    seen: Seen = []
    venue = Venue()
    port = _port(httpx.MockTransport(venue.handler), seen, _refusing(KekUnavailable("down")))
    with pytest.raises(TransportError) as caught:
        await port.open_orders(account())
    assert seen == [(KekUnavailable, type(None))] and venue.sent == []
    assert _bare(caught.value)


async def test_failure_hook_absent_port_behaves_as_before() -> None:
    port = _port(httpx.MockTransport(_timing_out), None, fake_capability("fixture-signer-id"))
    with pytest.raises(TransportError) as caught:
        await port.positions(account())
    assert _bare(caught.value)


async def test_failure_hook_fault_logged_by_type_port_still_raises_stripped_error() -> None:
    def hook(raw: Exception) -> None:
        raise RuntimeError("hook message with a secret-looking frame")

    port = BybitTradingPort(
        environment="demo",
        credentials=fake_capability("fixture-signer-id"),
        governor=RecordingGovernor(),
        transport=httpx.MockTransport(_timing_out),
        max_retries=0,
        on_failure=hook,
    )
    with capture_logs() as logs:
        with pytest.raises(TransportError) as caught:
            await port.positions(account())
    assert _bare(caught.value)
    [line] = [e for e in logs if e["event"] == "trading_failure_hook_faulted"]
    assert line == {
        "event": "trading_failure_hook_faulted",
        "log_level": "warning",
        "fault": "RuntimeError",
    }
    assert "secret-looking" not in repr(logs)


async def test_failure_hook_success_is_never_called() -> None:
    seen: Seen = []
    row = {**rest("rest/trading-position-list.json")["result"]["list"][0], "symbol": "BTCUSDT"}
    page = {"retCode": 0, "result": {"category": "linear", "nextPageCursor": "", "list": [row]}}
    venue = Venue().on("/v5/position/list", page)
    port = _port(httpx.MockTransport(venue.handler), seen, fake_capability("fixture-signer-id"))
    assert len(await port.positions(account())) == 1 and seen == []


def _timeout() -> TransportError:
    error = TransportError("t")
    error.__cause__ = httpx.ReadTimeout("slow")
    return error


def _reset() -> TransportError:
    error = TransportError("r")
    error.__cause__ = httpx.ConnectError("reset")
    return error


@pytest.mark.parametrize(
    ("raw", "word"),
    [
        (_timeout(), "timeout"),
        (_reset(), "transport_error"),
        (TransportError("5xx"), "service_unavailable"),
        (ServiceUnavailableError("busy", exchange_ret_code=10016), "service_unavailable"),
        (AuthError("refused", exchange_ret_code=10003), "auth_error"),
        (CredentialUnavailable("revoked"), "vault_refused"),
        (WithdrawPermissionRejected("withdraw"), "vault_refused"),
        (KekUnavailable("down"), "vault_refused"),
        (ValueError("not an adapter failure"), None),
    ],
)
def test_exposure_probe_error_raw_failure_named_as_22(raw: Exception, word: str | None) -> None:
    assert ExchangeBybitService.exposure_probe_error(raw) == word


async def test_exposure_port_each_call_a_new_hooked_port_on_own_environment_only() -> None:
    seen: Seen = []
    service = ExchangeBybitService(
        fake_capability("fixture-signer-id"),
        rest_transport=httpx.MockTransport(_timing_out),
        environment="demo",
    )

    def hook(raw: Exception) -> None:
        seen.append((type(raw), type(raw.__cause__)))

    first, second = (service.exposure_port("demo", on_failure=hook) for _ in range(2))
    assert first is not second
    with pytest.raises(ExchangeError):
        await first.positions(account())
    assert seen == [(TransportError, httpx.ReadTimeout)]
    with pytest.raises(ValueError, match="environment"):
        service.exposure_port("live", on_failure=hook)
    await first.aclose()
    await second.aclose()
