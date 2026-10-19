"""Contract, provider side (#836 slice 2b6): each `testApiKey` answer of the mounted route meets its
`22-api-openapi.yaml` schema (2020-12, format checker), every declared status included. The route
runs the real flow over `test_key_selfcheck.World`'s job; ACs 6 and 7 run the real adapter too,
built by the wiring, on a `MockTransport` and a fake private stream. No network.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
import respx
from fastapi import FastAPI
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.accounts.key_age import KeyRotationPolicy
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.selfcheck import FAILED, UNAVAILABLE, KeySelfCheck
from candleviewer.accounts.verification import VerificationInconclusive, VerificationPolicy
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.api.exchange_keys import make_exchange_keys_router
from candleviewer.exchange.bybit import key_ws_probe
from candleviewer.exchange.bybit.key_info import KEY_INFO_PATH, PROBE_PATH
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.key_selfcheck_wiring import JudgedCalls
from candleviewer.key_test_wiring import wire_key_test
from candleviewer.settings import Environment
from candleviewer.storage.repositories.accounts import (
    AccountsStoreScopeDeniedError,
    SelfCheckTargetRow,
)
from tests._signing import fake_capability
from tests.contract._admin_support import SPEC, validate_example
from tests.contract.test_create_api_key_provider import Resolver
from tests.unit.accounts.test_key_import import ACCT, KEY, OTHER, OWNER
from tests.unit.accounts.test_key_selfcheck import EGRESS, NOW, World, facts, target
from tests.unit.accounts.test_key_test import Reads, flow_of
from tests.unit.exchange.bybit.test_key_ws_probe import Stream
from tests.unit.test_key_import_wiring import Rig

_TEST = f"/exchange-accounts/{ACCT}/keys/{KEY}/test"
_RESULT, _PROBLEM, _EXCHANGE = "KeyTestResult", "Problem", "KeyExchangeProblem"
_THROTTLED = "/components/responses/KeyTestThrottled/content/application~1problem+json/schema"
_DEMO = "wss://stream-demo.bybit.com/v5/private"
_OK = SPEC["paths"]["/exchange-accounts/{accountId}/keys/{keyId}/test"]["post"]["responses"]["200"]
#: The contract's `wsBudgetSpent` example (SR-E27-05).
_SPENT: dict[str, Any] = _OK["content"]["application/json"]["examples"]["wsBudgetSpent"]["value"]
#: The store gate's refusal whose `rbac.denied` the sink refused (`World`: a `RuntimeError`).
_UNAUDITED = {"event": "key_test_denial_unaudited", "error": "RuntimeError", "log_level": "warning"}


class OwnerOnly(Reads):
    """The store's live-owner gate (SR-051): a non-owner reads no account in owner scope."""

    async def get_account(self, scope: Any, account_id: UUID) -> Any:
        if scope.user_id != OWNER:
            raise AccountsStoreScopeDeniedError
        return await super().get_account(scope, account_id)


class Route:
    """The router over `flow` (`None`: the fake backend), `w` its audit sink."""

    def __init__(self, w: World | None = None, flow: Any = ..., resolved: bool = True) -> None:
        self.w = World(target()) if w is None else w
        self.flow = flow_of(self.w, OwnerOnly()) if flow is ... else flow
        app = FastAPI()
        install_error_redaction(app)
        app.include_router(
            make_exchange_keys_router(
                None, self.w, Resolver() if resolved else None, egress_ip=EGRESS,
                rotation=KeyRotationPolicy(), tests=self.flow,
            )
        )  # fmt: skip
        transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://cv")

    async def post(self, who: str = "owner", path: str = _TEST, **body: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {who}"}
        with respx.mock():  # nothing but the injected transports answers
            return await self.client.post(path, headers=headers, json=body or None)


def answer(response: httpx.Response, status: int, schema: str) -> dict[str, Any]:
    """The body, once it is the status and matches its contract schema."""
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    validate_example(schema if schema.startswith("/") else f"/components/schemas/{schema}", body)
    return body


def keys_read_denials() -> float:
    """`authz_denied_total{permission="keys:read"}` (SR-125): a test asserts its delta."""
    return REGISTRY.get_sample_value("authz_denied_total", {"permission": "keys:read"}) or 0.0


def adapter_route(stream: Stream) -> tuple[Route, Rig, ExchangeBybitService]:
    """The route over the wiring's flow: the job's calls and the socket half on the real adapter,
    signed by a fake M2, its REST on a recording `MockTransport` (`Rig`), its stream `stream`."""
    w, rig = World(target()), Rig()
    exchange = ExchangeBybitService(
        credentials=fake_capability(), rest_transport=httpx.MockTransport(rig.answer),
        private_ws_connect=stream.connect, environment="demo",
    )  # fmt: skip

    def calls(key_id: UUID, uid: str) -> JudgedCalls:
        venue = exchange.key_verification_calls("demo", key_id, uid=uid, recv_window_ms=5000)
        return JudgedCalls(exchange, venue)

    job = KeySelfCheck(
        w, calls, gate=w.gate, audit=w, policy=VerificationPolicy(egress_ip=EGRESS), env="demo",
        clock=lambda: NOW, metrics=w.metrics,
    )  # fmt: skip
    ctx = SimpleNamespace(
        settings=SimpleNamespace(environment=Environment.DEMO), exchange_bybit=exchange,
        ingestion=SimpleNamespace(clock_offset_ms=lambda: None),
    )  # fmt: skip
    reads = AccountsRepository(Reads())  # type: ignore[arg-type]  # the two reads a test makes
    imports = SimpleNamespace(flow=SimpleNamespace(accounts=reads))
    flow = wire_key_test(ctx, job, imports)  # type: ignore[arg-type]  # the context's doubles
    return Route(w, flow), rig, exchange


async def test_a_passing_test_is_a_200_with_both_halves_and_its_verification() -> None:
    body = answer(await Route().post(), 200, _RESULT)
    assert body["passed"] and body["websocket"] == {"ok": True, "latency_ms": 42, "error": None}
    assert (body["rest"]["ok"], body["rest"]["ret_code"], body["rest"]["error"]) == (True, 0, None)
    shown = body["verification"]
    assert (shown["passed"], shown["egress_ip"], shown["ip_whitelist_matches_egress"]) == (
        True, EGRESS, True,
    )  # fmt: skip


async def test_ac4_a_whitelist_without_the_egress_ip_shows_it_and_blocks_trading() -> None:
    route = Route(World(target(), info=facts(ips=["198.51.100.9"])))
    body = answer(await route.post(), 200, _RESULT)
    shown = body["verification"]
    assert (body["passed"], shown["ip_whitelist_matches_egress"], shown["egress_ip"]) == (
        False, False, EGRESS,
    )  # fmt: skip
    assert route.w.armed[ACCT] is False and route.w.gate.latched_reason_code == FAILED
    assert "websocket" not in body  # a key a verdict refused is not signed with again


async def test_ac6_an_unreachable_demo_stream_is_a_websocket_failure_on_demo_hosts_only() -> None:
    stream = Stream(dial=OSError("unreachable"))
    route, rig, _ = adapter_route(stream)
    body = answer(await route.post(), 200, _RESULT)
    assert body["websocket"] == {"ok": False, "latency_ms": None, "error": "transport_error"}
    assert (body["passed"], body["rest"]["ok"]) == (False, True)
    assert [(r.url.host, r.url.path) for r in rig.sent] == [
        ("api-demo.bybit.com", KEY_INFO_PATH), ("api-demo.bybit.com", PROBE_PATH),
    ]  # fmt: skip
    assert stream.dialled == [_DEMO]  # no live host, no fallback (C-2.11)


async def test_ac7_an_auth_that_times_out_is_a_200_with_rest_ok_and_websocket_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(key_ws_probe, "timeout", lambda _delay: asyncio.timeout(0))
    stream = Stream(None)  # the stream never answers `auth`
    route, _, _ = adapter_route(stream)
    body = answer(await route.post(), 200, _RESULT)
    assert (body["passed"], body["rest"]["ok"]) == (False, True)
    assert body["websocket"] == {"ok": False, "latency_ms": None, "error": "timeout"}
    assert route.w.gate.latched_reason_code is None and route.w.armed[ACCT] is True


async def test_a_spent_ws_budget_is_the_contracts_ws_budget_spent_answer() -> None:
    """SR-E27-05: the deployment's opens are spent by other tests, so the WebSocket half is
    `rate_limited` with no connection opened, as `wsBudgetSpent` shows; the REST verdict stands."""
    stream = Stream()  # it would grant `auth`
    route, _, exchange = adapter_route(stream)
    for _ in range(key_ws_probe.OPENS_PER_WINDOW):  # tests of another key spend the budget
        await exchange.key_ws_probe("demo", OTHER)
    body = answer(await route.post(), 200, _RESULT)
    assert body["websocket"] == _SPENT["websocket"] == {
        "ok": False, "latency_ms": None, "error": "rate_limited",
    }  # fmt: skip
    assert (body["passed"], body["rest"]["ok"], body["verification"]["passed"]) == (
        False, True, True,
    )  # fmt: skip
    assert stream.dialled == [_DEMO] * key_ws_probe.OPENS_PER_WINDOW  # none for this test


async def test_without_include_ws_the_answer_has_no_websocket_member() -> None:
    body = answer(await Route().post(include_ws=False), 200, _RESULT)
    assert body["passed"] and "websocket" not in body


async def test_no_verdict_is_a_200_with_the_rest_error_and_no_verification() -> None:
    route = Route(World(target(), info=VerificationInconclusive("transport_error")))
    body = answer(await route.post(), 200, _RESULT)
    assert body["rest"] | {"latency_ms": 0} == {
        "ok": False, "latency_ms": 0, "ret_code": None, "error": "transport_error",
    }  # fmt: skip
    assert "verification" not in body and not body["passed"]


@pytest.mark.parametrize(
    ("who", "path", "denied"),
    [
        ("manager", _TEST, ACCT),  # no keys:read
        ("viewer", _TEST, ACCT),
        ("reader", f"/exchange-accounts/{OTHER}/keys/{KEY}/test", OTHER),  # IDOR: no grant there
        ("reader", _TEST, ACCT),  # granted, yet keys are the Owner's: the store's gate refuses
    ],
    ids=["manager", "viewer", "cross-account", "store-gate"],
)
async def test_only_the_owner_may_test_a_key(who: str, path: str, denied: UUID) -> None:
    route, counted = Route(), keys_read_denials()
    body = answer(await route.post(who, path), 403, _PROBLEM)
    records = [(e[1], e[2]["object_id"]) for e in route.w.of("audit")]
    assert records == [("rbac.denied", str(denied))]  # every refusal names the account (C-2.9)
    assert body["code"] == "forbidden" and route.w.built == []
    assert keys_read_denials() == counted + 1  # and is counted once, by the layer refusing it


async def test_the_store_gates_refusal_is_audited_as_enforce_audits_its_own() -> None:
    """SR-051's gate refuses a caller `enforce` let through: the same caller's two records, one
    per layer, differ only in the account each names and the reason, of the same shape."""
    route = Route()
    answer(await route.post("reader", f"/exchange-accounts/{OTHER}/keys/{KEY}/test"), 403, _PROBLEM)
    answer(await route.post("reader"), 403, _PROBLEM)
    by_enforce, by_store = (e[2] for e in route.w.of("audit"))
    named = {"object_id": str(OTHER), "reason": "account_not_granted:keys:read:granted_accounts"}
    assert by_enforce == by_store | named and by_store["actor_user_id"] == UUID(int=96)
    assert (by_store["object_id"], by_store["reason"]) == (
        str(ACCT), "not_owner:keys:read:granted_accounts",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("who", "logged"), [("manager", []), ("reader", [_UNAUDITED])], ids=["enforce", "store-gate"]
)
async def test_a_refusal_that_cannot_be_audited_is_still_a_403(who: str, logged: list[Any]) -> None:
    """Each layer counts its denial before the record (SR-125); the store gate's lost record is a
    warning naming the error's class alone (C-12.6)."""
    route, counted = Route(), keys_read_denials()
    route.w.fail_audit = True  # a test never answers on an audit record
    with capture_logs() as logs:
        body = answer(await route.post(who), 403, _PROBLEM)
    assert (body["code"], route.w.built) == ("forbidden", [])
    assert (keys_read_denials(), logs) == (counted + 1, logged)


async def test_no_session_is_a_401_and_no_resolver_a_501() -> None:
    assert answer(await Route().post("nobody"), 401, _PROBLEM)["code"] == "unauthenticated"
    unwired = answer(await Route(resolved=False).post(), 501, _PROBLEM)
    assert unwired["code"] == "not_implemented"


async def test_a_missing_or_foreign_account_or_key_is_the_same_404() -> None:
    other_env = Route(flow=flow_of(World(target()), OwnerOnly(env="live")))
    elsewhere = f"/exchange-accounts/{OTHER}/keys/{KEY}/test"
    other_key = f"/exchange-accounts/{ACCT}/keys/{OTHER}/test"
    bodies = [
        answer(await Route().post(path=elsewhere), 404, _PROBLEM),
        answer(await Route().post(path=other_key), 404, _PROBLEM),
        answer(await other_env.post(), 404, _PROBLEM),
    ]
    assert bodies[0] == bodies[1] == bodies[2] and bodies[0]["code"] == "not_found"


async def test_a_key_that_is_not_signable_is_a_409_and_nothing_is_probed() -> None:
    route = Route(flow=flow_of(w := World(target()), OwnerOnly("revoked")))
    body = answer(await route.post(), 409, _PROBLEM)
    assert (body["code"], body["detail"], w.built) == (
        "conflict", "The key is revoked, so it cannot be tested.", [],
    )  # fmt: skip


@pytest.mark.parametrize(
    ("body", "rule"),
    [({"include_ws": "maybe"}, "bool_parsing"), ({"note": "x"}, "extra_forbidden")],
)
async def test_a_body_that_fails_its_schema_is_a_422(body: dict[str, Any], rule: str) -> None:
    route = Route()
    problem = answer(await route.post(**body), 422, _PROBLEM)
    assert [e["rule"] for e in problem["errors"]] == [rule] and route.w.built == []


async def test_a_second_test_inside_the_minute_is_a_429_with_retry_after() -> None:
    route = Route()
    answer(await route.post(), 200, _RESULT)
    again = await route.post()
    body = answer(again, 429, _THROTTLED)
    assert (body["code"], body["retry_after_seconds"], again.headers["retry-after"]) == (
        "rate_limited", 60, "60",
    )  # fmt: skip
    assert len(route.w.built) == 1  # nothing was probed the second time


class Held(World):
    """Its key-info call waits until `released`: a test still at the exchange."""

    def __init__(self, *rows: SelfCheckTargetRow) -> None:
        super().__init__(*rows)
        self.reached, self.released = asyncio.Event(), asyncio.Event()

    async def key_info(self) -> Any:
        self.reached.set()
        await self.released.wait()
        return await super().key_info()


async def test_a_test_racing_one_still_at_the_exchange_is_a_429_and_probes_nothing() -> None:
    """The ticket's denial-of-service threat is simultaneous tests: a key's minute is taken before
    the first await that reaches the exchange, so a second request is refused at once, never
    queued behind a hung first one."""
    route = Route(w := Held(target()))
    async with asyncio.timeout(1.0):
        first = asyncio.create_task(route.post())
        await w.reached.wait()  # the first test is at the exchange, its answer held
        again = await route.post()
        w.released.set()
        answer(await first, 200, _RESULT)
    body = answer(again, 429, _THROTTLED)
    assert (body["code"], again.headers["retry-after"]) == ("rate_limited", "60")
    assert len(w.built) == 1  # the second request built no client and signed nothing


@pytest.mark.parametrize(
    ("code", "status", "schema"),
    [("kek_unavailable", 403, _PROBLEM), ("credential_unavailable", 503, _EXCHANGE)],
)
async def test_signing_that_m2_refuses_is_its_403_or_503(
    code: str, status: int, schema: str
) -> None:
    refusal = type("Refusal", (Exception,), {"code": code})("refused")
    body = answer(await Route(World(target(), info=refusal)).post(), status, schema)
    assert body["code"] == {403: "kek_unavailable", 503: "exchange_unavailable"}[status]


@pytest.mark.parametrize("down", [False, True], ids=["fake-backend", "store-down"])
async def test_a_store_that_is_absent_or_down_is_a_503_with_retry_after(down: bool) -> None:
    flow = flow_of(World(), Reads(error=RuntimeError("down"))) if down else None
    response = await Route(flow=flow).post()
    body = answer(response, 503, _EXCHANGE)
    assert (body["code"], response.headers["retry-after"]) == ("store_unavailable", "5")


async def test_with_no_egress_ip_a_test_is_a_503_that_probed_signed_and_disarmed_nothing() -> None:
    """As the hourly pass with no egress IP: the job latches `UNAVAILABLE` and judges no key."""
    route = Route(World(target(), egress=None))
    response = await route.post()
    body = answer(response, 503, _EXCHANGE)
    assert (body["code"], response.headers["retry-after"]) == ("exchange_unavailable", "5")
    assert body["detail"] == "No egress IP is configured, so the key could not be tested."
    assert (route.w.events, route.w.built, route.w.armed[ACCT]) == (
        [("latch", UNAVAILABLE)], [], True,
    )  # fmt: skip


def test_without_a_self_check_or_an_import_no_test_is_wired() -> None:
    ctx, wired = cast(Any, SimpleNamespace()), cast(Any, object())
    assert wire_key_test(ctx, None, wired) is None and wire_key_test(ctx, wired, None) is None
