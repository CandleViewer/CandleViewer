"""#2893 S7: the fixture transport's guards run before anything is answered (ADR-0036 decision 4).

Requests are signed here as `BybitSigner` has M2 sign them (HMAC-SHA256 over timestamp + key id +
recv window + payload, with the pack's derived secret), against the checkout's pack, a request log
under `tmp_path` and the real read-only gate. Fund paths are built from the guard's prefix or are
malformed variants, so no literal here is a withdraw or transfer endpoint (ADR-0036, Enforcement).
No socket opens and nothing sleeps: the REST client's retry sleep is a no-op.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final, NoReturn
from uuid import UUID

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.verification import VerificationInconclusive, VerificationPolicy, verify
from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.bybit.config import ALLOWED_REST_HOSTS, EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.key_info import (
    KEY_INFO_PATH,
    PROBE_PATH,
    ApiKeyFacts,
    parse_key_info,
)
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.secrets import CredentialBorrower, RequestSignature, Secret
from candleviewer.secrets.signing import check_message
from candleviewer.settings import Environment
from cvdev.account_fixture.guards import (
    DEMO_REST_HOST,
    FUND_PATH_PREFIX,
    GUARD_REASON_CODE,
    Admission,
    stored_under,
)
from cvdev.account_fixture.pack import Pack, fixture_key_ids
from cvdev.account_fixture.requestlog import FILE_NAME, RequestLog
from cvdev.account_fixture.transport import MAX_BODY_BYTES, Answer, FixtureTransport
from tests._account_fixtures import EGRESS_IP, PACK, _payload, manifest
from tests._signing import CREDENTIAL_ID, assemble
from tests.unit.exchange.bybit.test_account_fixture_pack import (
    NOW,
    NOW_MS,
    ORDER_BODY,
    _account,
    _governor,
    _judge,
    _no_sleep,
)

KEY_IDS: Final = fixture_key_ids(PACK)
TS, RECV = str(NOW_MS), "5000"
#: Key-shaped and derived here, never a credential: a key outside the pack.
NON_FIXTURE_KEY: Final = "".join(chr(65 + b % 26) for b in hashlib.sha256(b"cv-2893-s7").digest())
DEMO: Final = f"https://{DEMO_REST_HOST}"
#: The stack default, `CV_ACCOUNT_FIXTURE`.
STACK: Final = "compliant"
ORDER: Final = f"{DEMO}/v5/order/create"
#: Every other origin, with the host and environment the log names: the adapter's other hosts,
#: then the demo host on plain http and on another port, then a host outside the table.
_OTHER_HOSTS: Final = sorted(ALLOWED_REST_HOSTS - {DEMO_REST_HOST})
OTHER_ORIGINS: Final = [
    *((f"https://{h}", h, "testnet" if "testnet" in h else "live") for h in _OTHER_HOSTS),
    (f"http://{DEMO_REST_HOST}", DEMO_REST_HOST, "demo"),
    (f"{DEMO}:8443", DEMO_REST_HOST, "demo"),
    ("https://example.invalid", None, None),
]


def _key(scenario: str) -> str:
    return str(manifest(scenario)["tester_inputs"]["key_id"])


def _secret(scenario: str) -> str:
    """The pack README's derived secret, computed here and never stored in a file."""
    return f"fixture-{scenario}-secret-not-real"


def _get(
    scenario: str = "compliant",
    *,
    origin: str = DEMO,
    path: str = KEY_INFO_PATH,
    key: str | None = None,
    signed_as: str | None = None,
    headers: Sequence[tuple[str, str]] = (),
    payload: bytes = b"",
) -> httpx.Request:
    """A signed GET: `scenario`'s key id (or `key`), with `signed_as`'s secret over `payload`."""
    key = key or _key(scenario)
    message = f"{TS}{key}{RECV}".encode() + payload
    mac = hmac.new(_secret(signed_as or scenario).encode(), message, hashlib.sha256).hexdigest()
    auth = [("X-BAPI-API-KEY", key), ("X-BAPI-TIMESTAMP", TS), ("X-BAPI-RECV-WINDOW", RECV)]
    return httpx.Request("GET", origin + path, headers=headers or [*auth, ("X-BAPI-SIGN", mac)])


def _of(line: Mapping[str, Any], *names: str) -> tuple[Any, ...]:
    return tuple(line[name] for name in names)


def _p0(events: Sequence[Mapping[str, Any]], outcome: str) -> bool:
    return [_of(e, "log_level", "outcome", "priority") for e in events] == [
        ("critical", outcome, "p0-critical")
    ]


@dataclass
class Rig:
    transport: FixtureTransport
    gate: ReadOnlyGate
    log: RequestLog
    log_dir: Path

    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in (self.log_dir / FILE_NAME).read_text().splitlines()]

    async def refused(self, request: httpx.Request) -> tuple[str, Sequence[Mapping[str, Any]]]:
        """The refusal's message and the log events; never an answer."""
        with capture_logs() as events, pytest.raises(httpx.ConnectError) as refused:
            await self.transport.handle_async_request(request)
        return str(refused.value), events


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    with RequestLog(
        tmp_path, process_env=Environment.DEMO, clock=lambda: NOW, pack_key_ids=KEY_IDS
    ) as log:
        gate = ReadOnlyGate()
        transport = FixtureTransport(PACK, log=log, gate=gate, clock=lambda: NOW, default=STACK)
        yield Rig(transport, gate, log, tmp_path)


class _Seam(FixtureTransport):
    """S9's seam as it sees a request: `_serve` is handed the bytes guard 4 verified."""

    body: bytes | None = None

    async def _serve(self, request: httpx.Request, seen: Admission, body: bytes | None) -> Answer:
        self.body = body
        return await super()._serve(request, seen, body)


async def _host_refused(rig: Rig, origin: str, host: str | None, env: str | None) -> None:
    text, events = await rig.refused(_get(origin=origin))
    [line] = rig.lines()
    assert _of(line, "outcome", "host", "host_env") == ("refused_host", host, env)
    assert _of(line, "signing_key_id", "verified") == (_key("compliant"), None)
    assert _p0(events, "refused_host")
    assert text == "the account fixture transport refused the request: refused_host"
    assert not rig.transport.latched and not rig.gate.is_read_only


async def test_live_host_refused_and_logged_p0(rig: Rig) -> None:
    await _host_refused(rig, "https://api.bybit.com", "api.bybit.com", "live")


async def test_testnet_host_refused_and_logged_p0(rig: Rig) -> None:
    await _host_refused(rig, "https://api-testnet.bybit.com", "api-testnet.bybit.com", "testnet")


@pytest.mark.parametrize(("origin", "host", "env"), OTHER_ORIGINS)
async def test_every_non_demo_allowed_host_refused(
    rig: Rig, origin: str, host: str | None, env: str | None
) -> None:
    assert DEMO_REST_HOST in ALLOWED_REST_HOSTS
    await _host_refused(rig, origin, host, env)


async def test_non_fixture_key_never_answered_and_latches(rig: Rig) -> None:
    request = _get(key=NON_FIXTURE_KEY)
    text, events = await rig.refused(request)
    assert rig.transport.latched and rig.gate.is_read_only
    assert rig.gate.latched_reason_code == GUARD_REASON_CODE == "account_fixture_guard"
    [line] = rig.lines()
    assert _of(line, "outcome", "key_class", "signing_key_id") == (
        "refused_key",
        "non_fixture",
        None,
    )
    assert _p0(events, "refused_key")
    # FX-I01: the client copies the message into its TransportError; nothing holds a header.
    seen = text + repr(events) + (rig.log_dir / FILE_NAME).read_text() + str(rig.gate.reason_text)
    for value in (NON_FIXTURE_KEY[:8], NON_FIXTURE_KEY[-4:], request.headers["X-BAPI-SIGN"]):
        assert value not in seen


@pytest.mark.parametrize(
    ("origin", "path", "outcome"),
    [
        ("https://api.bybit.com", KEY_INFO_PATH, "refused_host"),
        (DEMO, f"{FUND_PATH_PREFIX}withdraw/create", "refused_fund_path"),
    ],
    ids=["live-host", "fund-path"],
)
async def test_a_non_fixture_key_trips_whichever_guard_refuses_first(
    rig: Rig, origin: str, path: str, outcome: str
) -> None:
    _, events = await rig.refused(_get(origin=origin, path=path, key=NON_FIXTURE_KEY))
    [line] = rig.lines()
    assert _of(line, "outcome", "key_class") == (outcome, "non_fixture")
    assert _p0(events, outcome) and events[0]["latched"] is True
    assert rig.transport.latched and rig.gate.latched_reason_code == GUARD_REASON_CODE


async def test_latched_transport_refuses_later_calls_and_latches_the_gate(rig: Rig) -> None:
    await rig.refused(_get(key=NON_FIXTURE_KEY))
    _, events = await rig.refused(_get("compliant"))
    assert _of(rig.lines()[-1], "outcome", "key_class") == ("refused_key", "fixture")
    assert [_of(e, "log_level", "latched") for e in events] == [("error", True)]
    assert rig.gate.is_read_only and rig.gate.latched_reason_code == GUARD_REASON_CODE


async def test_a_trip_keeps_the_gates_existing_latch(rig: Rig) -> None:
    rig.gate.latch(reason_code="secrets.kek_unavailable", reason_text="kek")
    await rig.refused(_get(key=NON_FIXTURE_KEY))
    assert rig.transport.latched and rig.gate.latched_reason_code == "secrets.kek_unavailable"


@pytest.mark.parametrize("held", [None, "secrets.kek_unavailable"])
async def test_a_trip_refuses_through_every_transport_in_the_process(
    rig: Rig, held: str | None
) -> None:
    """Whatever latch the gate holds already, which the trip keeps (ADR-0036 decision 4)."""
    if held:
        rig.gate.latch(reason_code=held, reason_text="kek")
    seam = _Seam(PACK, log=rig.log, gate=rig.gate, clock=lambda: NOW, default=STACK)
    other = replace(rig, transport=seam)

    async def body() -> AsyncIterator[bytes]:
        await rig.refused(_get(key=NON_FIXTURE_KEY))  # trips while `other` reads this order
        yield b"{}"

    order = httpx.Request("POST", ORDER, headers=_get(payload=b"{}").headers, content=body())
    await other.refused(order)
    _, events = await other.refused(_get("compliant"))
    assert [_of(e, "log_level", "latched") for e in events] == [("error", True)]
    assert seam.latched and seam.body == b"{}"  # only the order in flight reached _serve
    assert [line["outcome"] for line in rig.lines()] == ["refused_key"] * 3
    assert rig.gate.latched_reason_code == (held or GUARD_REASON_CODE)


async def test_another_latch_on_the_gate_leaves_the_transport_answering(rig: Rig) -> None:
    rig.gate.latch(reason_code="secrets.kek_unavailable", reason_text="kek")
    assert (await rig.transport.handle_async_request(_get())).status_code == 200
    assert not rig.transport.latched


async def test_a_trip_refuses_a_request_already_in_flight(rig: Rig) -> None:
    async def body() -> AsyncIterator[bytes]:
        await rig.refused(_get(key=NON_FIXTURE_KEY))  # trips while the order is being read
        yield b"{}"

    order = httpx.Request("POST", ORDER, headers=_get().headers, content=body())
    await rig.refused(order)
    assert [line["outcome"] for line in rig.lines()] == ["refused_key", "refused_key"]


@pytest.mark.parametrize(
    "auth",
    [
        [("X-BAPI-API-KEY", "fixture-compliant-9999")],
        [("X-BAPI-API-KEY", "fixture-not_in_the_pack-0001")],
        [("X-BAPI-API-KEY", _key("compliant")), ("X-BAPI-API-KEY", _key("compliant"))],
        [("X-BAPI-TIMESTAMP", TS), ("X-BAPI-SIGN", "0" * 64)],
    ],
    ids=["unknown-tail", "unknown-scenario", "key-twice", "no-key"],
)
async def test_fixture_shape_outside_the_pack_is_refused(rig: Rig, auth: list[Any]) -> None:
    await rig.refused(_get(headers=auth))
    assert rig.transport.latched and rig.gate.latched_reason_code == GUARD_REASON_CODE
    [line] = rig.lines()
    assert _of(line, "outcome", "key_class", "signing_key_id") == (
        "refused_key",
        "non_fixture",
        None,
    )


@pytest.mark.parametrize(
    "request_",
    [
        _get(signed_as="compliant_alt"),
        _get(path=f"{PROBE_PATH}?accountType=UNIFIED"),
        _get(headers=[("X-BAPI-API-KEY", _key("compliant")), ("X-BAPI-TIMESTAMP", TS)]),
        httpx.Request("POST", ORDER, headers=_get().headers, content=b"{" * (MAX_BODY_BYTES + 1)),
        httpx.Request("POST", ORDER, headers=_get().headers, content=iter([b"{}"])),
    ],
    ids=["other-secret", "other-payload", "unsigned-key", "body-too-large", "blocking-body"],
)
async def test_signature_mismatch_answers_10004_verified_false(
    rig: Rig, request_: httpx.Request
) -> None:
    with capture_logs() as events:
        response = await rig.transport.handle_async_request(request_)
    assert response.status_code == 200
    assert json.loads(await response.aread()) == _payload("_base/error_10004.json")
    [line] = rig.lines()
    assert _of(line, "outcome", "verified", "signing_key_id", "stored_under") == (
        "signature_mismatch",
        False,
        _key("compliant"),
        "compliant",
    )
    assert _of(line, "status", "ret_code") == (200, 10004)
    assert [_of(e, "log_level", "event") for e in events] == [
        ("warning", "exchange.account_fixture_signature_mismatch")
    ]
    assert not rig.transport.latched and not rig.gate.is_read_only


async def test_signature_uses_the_stored_under_scenario_after_a_switch(rig: Rig) -> None:
    target = manifest("stored_key_rejected")["switch_to"]
    assert target == "live_key_on_demo"
    mismatch = await rig.transport.handle_async_request(
        _get("stored_key_rejected", signed_as=target)
    )
    own = await rig.transport.handle_async_request(_get("stored_key_rejected"))
    assert json.loads(await mismatch.aread())["retCode"] == 10004
    assert json.loads(await own.aread())["retCode"] == 0
    lines = rig.lines()
    assert [_of(line, "outcome", "verified", "stored_under") for line in lines] == [
        ("signature_mismatch", False, "stored_key_rejected"),
        ("served", True, "stored_key_rejected"),
    ]
    assert KEY_IDS and all(_key(stored_under(key)) == key for key in KEY_IDS)


async def test_an_unsigned_call_meets_no_key_guard(rig: Rig) -> None:
    request = httpx.Request("GET", DEMO + "/v5/market/time")
    assert (await rig.transport.handle_async_request(request)).status_code == 200
    [line] = rig.lines()
    assert _of(line, "outcome", "key_class", "verified") == ("served", "unsigned", None)
    assert not rig.transport.latched


async def test_serve_is_handed_the_verified_body_of_a_one_shot_stream(rig: Rig) -> None:
    order = b'{"symbol":"BTCUSDT"}'

    async def once() -> AsyncIterator[bytes]:  # httpx raises StreamConsumed on a second read
        yield order

    seam = _Seam(PACK, log=rig.log, gate=rig.gate, clock=lambda: NOW, default=STACK)
    request = httpx.Request("POST", ORDER, headers=_get(payload=order).headers, content=once())
    assert (await seam.handle_async_request(request)).status_code == 200
    assert seam.body == order
    assert _of(rig.lines()[0], "outcome", "verified") == ("served", True)


def test_a_pack_without_fixture_keys_is_refused(rig: Rig, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no fixture key id"):
        FixtureTransport(
            Pack(tmp_path / "empty"), log=rig.log, gate=rig.gate, clock=lambda: NOW, default=STACK
        )


@pytest.mark.parametrize(
    "path",
    [
        f"{FUND_PATH_PREFIX}withdraw/create",
        f"{FUND_PATH_PREFIX}transfer/inter-transfer",
        f"{FUND_PATH_PREFIX}transfer/universal-transfer",
        f"{FUND_PATH_PREFIX.upper()}withdraw/create",
        "/v5//asset/transfer/inter-transfer",
        "/v5/order/%2e%2e/asset/withdraw/create",
    ],
)
async def test_fund_paths_refused_p0(rig: Rig, path: str) -> None:
    _, events = await rig.refused(_get(path=path))
    [line] = rig.lines()
    assert line["outcome"] == "refused_fund_path" and _p0(events, "refused_fund_path")
    assert not rig.transport.latched and not rig.gate.is_read_only


@pytest.mark.parametrize("origin", [DEMO, "https://api.bybit.com"])
async def test_a_log_that_cannot_be_written_refuses_and_withholds_answers(
    rig: Rig, origin: str
) -> None:
    rig.log.close()
    text, events = await rig.refused(_get(origin=origin))
    assert text.endswith("request_log_failed" if origin == DEMO else "refused_host")
    assert events[-1]["event"] == "exchange.account_fixture_log_failed"


def _client(transport: FixtureTransport, origin: str, key: str, secret: str) -> BybitRestClient:
    """The adapter's REST client, its signer's M2 stand-in computing the real HMAC."""

    async def sign(
        credential_id: UUID, message: Sequence[object], purpose: str
    ) -> RequestSignature:
        mac = hmac.new(secret.encode(), assemble(key, check_message(message)), hashlib.sha256)
        return RequestSignature(Secret(key), mac.hexdigest())

    return BybitRestClient(
        RestClientConfig(base_url=origin),
        signer=BybitSigner(CredentialBorrower(sign), CREDENTIAL_ID),
        governor=_governor(),
        transport=transport,
        sleep=_no_sleep,
        wall_clock=lambda: NOW_MS / 1000,
        clock_offset_ms_provider=lambda: 0,
    )


@pytest.mark.parametrize(
    "call",
    [
        {"method": "GET", "path": PROBE_PATH, "params": {"accountType": "UNIFIED"}},
        {"method": "POST", "path": "/v5/order/create", "body": ORDER_BODY},
    ],
)
async def test_the_rest_clients_signature_verifies(rig: Rig, call: dict[str, Any]) -> None:
    endpoint = EndpointClass.ORDER if call["method"] == "POST" else EndpointClass.ACCOUNT
    async with _client(rig.transport, DEMO, _key("compliant"), _secret("compliant")) as client:
        assert (await client.signed_request(**call, endpoint_class=endpoint))["retCode"] == 0
    [line] = rig.lines()
    assert _of(line, "outcome", "verified", "status") == ("served", True, 200)


@pytest.mark.parametrize(
    ("origin", "key", "outcome"),
    [("https://api.bybit.com", None, "refused_host"), (DEMO, NON_FIXTURE_KEY, "refused_key")],
    ids=["live-host", "non-fixture-key"],
)
async def test_refusal_is_inconclusive_through_the_rest_client(
    rig: Rig, origin: str, key: str | None, outcome: str
) -> None:
    client = _client(rig.transport, origin, key or _key("compliant"), _secret("compliant"))

    async def key_info() -> ApiKeyFacts:
        try:
            return parse_key_info(await client.signed_request("GET", KEY_INFO_PATH))
        except ExchangeError as error:
            _judge(error)

    async def probe() -> NoReturn:
        raise AssertionError("verify() never probes after an inconclusive key-info call")

    policy = VerificationPolicy(egress_ip=EGRESS_IP)
    async with client:
        with pytest.raises(VerificationInconclusive, match="TransportError"):
            await verify(
                _account("90000001"),
                read_only=False,
                key_info=key_info,
                probe=probe,
                policy=policy,
                now=NOW,
            )
    # The client retries a transport error: every attempt is refused, none answered.
    assert [line["outcome"] for line in rig.lines()] == [outcome] * 4
    assert rig.gate.is_read_only is (outcome == "refused_key")
