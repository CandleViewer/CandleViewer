"""Contract, provider side (#836 slice 2b4): each `createApiKey` answer of the mounted route meets
its `22-api-openapi.yaml` schema (2020-12, format checker), the `502` and `503` included. The route
runs the real flow, M2 capability and adapter (`Rig`: a `MockTransport`; `respx` answers nothing).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from fastapi import FastAPI, Request

from candleviewer.accounts.key_age import KeyRotationPolicy
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.api.exchange_keys import make_exchange_keys_router
from candleviewer.api.idempotency import IdempotencyCache
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.exchange.bybit.key_info import KEY_INFO_PATH, PROBE_PATH
from candleviewer.secrets import CredentialUnavailable, KekUnavailable
from tests.contract._admin_support import validate_example
from tests.unit.accounts.test_key_import import ACCT, OWNER, World, account_row
from tests.unit.accounts.test_key_selfcheck import EGRESS
from tests.unit.credentials_m2._vectors import API_KEY, API_SECRET
from tests.unit.test_key_import_wiring import Refusing, Rig

_KEYS = f"/exchange-accounts/{ACCT}/keys"
_BODY = {"api_key": API_KEY, "api_secret": API_SECRET, "label": "main-trade"}
_ONCE = "00000000-0000-4000-8000-0000000000c1"
_HOST = "api-demo.bybit.com"
_SHORT = "s3cr"  # shorter than the schema's 8 characters
_GRANT = (AccountGrant(ACCT, True, True, False),)  # the manager's: still no `keys:manage`
_TWO, _CREATED, _REJECTED = str(UUID(int=2)), "ApiKeyWithVerification", "KeyRejectedProblem"
_ELSEWHERE = f"/exchange-accounts/{UUID(int=5)}/keys"
PEOPLE = {
    "owner": PrincipalSnapshot(OWNER, frozenset({"owner"}), frozenset(Permission)),
    "manager": PrincipalSnapshot(UUID(int=98), frozenset({"manager"}), frozenset(), _GRANT),
    "viewer": PrincipalSnapshot(UUID(int=97), frozenset({"viewer"}), frozenset()),
}


class Resolver:
    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        return PEOPLE.get(request.headers.get("authorization", "").removeprefix("Bearer "))


class Route:
    """The router over `world`'s flow (`None`: the fake backend), with `world` as audit sink."""

    def __init__(self, world: Any, *, wired: bool = True, raises: bool = False) -> None:
        self.world, self.replays, app = world, IdempotencyCache(), FastAPI()
        install_error_redaction(app)
        app.include_router(
            make_exchange_keys_router(
                world.flow if wired else None, world, Resolver(), egress_ip=EGRESS,
                rotation=KeyRotationPolicy(), replays=self.replays,
            )
        )  # fmt: skip
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=raises)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://cv")

    async def post(
        self, who: str = "owner", once: str | None = _ONCE, path: str = _KEYS, **body: Any
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {who}"} | ({"Idempotency-Key": once} if once else {})
        with respx.mock():  # nothing but the injected transport answers
            return await self.client.post(path, json=_BODY | body, headers=headers)


async def booted(**rig: Any) -> Route:
    await (world := Rig(**rig)).boot()
    world.flow = world.importer()
    return Route(world)


def answer(response: httpx.Response, status: int, schema: str) -> dict[str, Any]:
    """The body, once it is the status and matches its contract schema; no key material."""
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    validate_example("/components/schemas/" + schema, body)
    assert API_KEY not in response.text and API_SECRET not in response.text
    return body


async def test_ac1_ac9_a_compliant_key_is_201_with_its_verification_and_clock_skew() -> None:
    route = await booted(skew_ms=12_000)  # the exchange's clock 12 s ahead of the host's
    body, rig = answer(await route.post(), 201, "ApiKeyWithVerification"), route.world
    assert (body["key"]["status"], body["key"]["rotation_state"]) == ("active", "ok")
    shown = body["verification"]
    assert 11_000 < shown.pop("clock_offset_ms") < 13_000 and shown.pop("warnings") == [
        "clock_skew"
    ]
    held = {group: rights for group, rights in shown.pop("permissions").items() if rights}
    assert shown == {
        "passed": True, "uid": "1000001", "uta": True, "read_only": False, "probe_ret_code": 0,
        "withdraw_enabled": False, "ip_whitelist": [EGRESS], "ip_whitelist_matches_egress": True,
        "egress_ip": EGRESS,
    }  # fmt: skip
    assert held == {"ContractTrade": ["Order", "Position"], "Derivatives": ["DerivativesTrade"]}
    # Signed with the pasted key, on its own environment's host only (C-2.11).
    assert [(r.url.host, r.url.path, r.headers["X-BAPI-API-KEY"]) for r in rig.sent] == [
        (_HOST, KEY_INFO_PATH, API_KEY), (_HOST, PROBE_PATH, API_KEY),
    ]  # fmt: skip
    (key_id,) = rig.m2.rows  # sealed by M2 as `pending`, then promoted by the flow (AC-34)
    assert rig.m2_audit.actions()[-1] == "security.credential_stored"
    assert rig.events[-1][1:4] == (key_id, "pending", "active")
    assert {f["actor_user_id"] for _, f in rig.m2_audit.records} == {str(OWNER)}  # SR-E27-09
    assert rig.audit()[0]["after_state"]["key_id"] == str(key_id)  # one id for every record


@pytest.mark.perf  # a wall-clock budget (C-13.9): SCR-126's 3 s import round trip
async def test_an_import_round_trip_on_the_fake_transport_is_under_three_seconds() -> None:
    route = await booted()
    started = time.perf_counter()
    assert (await route.post()).status_code == 201
    assert time.perf_counter() - started < 3.0


async def test_ac2_a_withdraw_right_is_a_422_with_its_rule_and_nothing_is_persisted() -> None:
    route = await booted(withdraw=True)
    body = answer(await route.post(), 422, "KeyRejectedProblem")
    assert body["errors"] == [
        {"field": "api_key", "rule": "key_withdraw_permission",
         "message": "permissions.Wallet contains 'Withdraw'"},
    ]  # fmt: skip
    shown = body["verification"]
    assert (shown["passed"], shown["withdraw_enabled"]) == (False, True)
    assert "ip_whitelist_matches_egress" not in shown and "probe_ret_code" not in shown
    assert route.world.m2.rows == {} and route.world.stored is None


async def test_ac5_a_key_the_host_does_not_know_is_a_422_with_no_check_shown() -> None:
    route = await booted(swap={KEY_INFO_PATH: "error_10003.json"})
    body = answer(await route.post(), 422, "KeyRejectedProblem")
    assert body["verification"] == {"passed": False, "egress_ip": EGRESS}  # never withdraw_enabled
    assert body["errors"][0]["message"] == "key does not belong to this environment"
    assert route.world.m2.rows == {}


async def test_an_error_answer_is_a_502_with_its_return_code_alone_and_is_never_replayed() -> None:
    route = await booted(swap={KEY_INFO_PATH: "error_10004.json"})
    first = await route.post()
    body = answer(first, 502, "KeyExchangeProblem")
    assert body["exchange"] == {"ret_code": 10004} and "retry-after" not in first.headers
    again = await route.post()  # the same key and body: a first submission, verified again
    assert again.status_code == 502 and "idempotency-replayed" not in again.headers
    assert [r.url.path for r in route.world.sent] == [KEY_INFO_PATH, KEY_INFO_PATH]


async def test_no_answer_in_time_is_a_503_with_retry_after_and_no_exchange_member() -> None:
    world = Rig()
    world.flow = world.importer(Refusing(CredentialUnavailable("candidate_timeout")))
    response = await Route(world).post()
    body = answer(response, 503, "KeyExchangeProblem")
    assert (body["code"], response.headers["retry-after"]) == ("exchange_unavailable", "5")
    assert "exchange" not in body


@pytest.mark.parametrize(("who", "status"), [("manager", 403), ("viewer", 403), ("nobody", 401)])
async def test_only_the_owner_may_import_even_a_manager_granted_on_the_account(
    who: str, status: int
) -> None:
    route = await booted()
    body = answer(await route.post(who), status, "Problem")
    denied = [("rbac.denied", "exchange_account", str(ACCT))] if status == 403 else []
    shown = [(r["action"], r["object_kind"], r["object_id"]) for r in route.world.audit()]
    assert shown == denied and route.world.sent == []  # the refusal names the account (C-2.9)
    assert body.get("required_permissions", ["keys:manage"]) == ["keys:manage"]


async def test_an_account_of_another_environment_answers_as_a_missing_one() -> None:
    route = await booted()
    route.world.account = account_row("live")
    other = answer(await route.post(), 404, "Problem")
    elsewhere = {"path": _ELSEWHERE, "once": str(UUID(int=6))}
    assert answer(await route.post(**elsewhere), 404, "Problem") == other  # no oracle
    assert route.world.sent == []


async def test_the_idempotency_key_is_required_replayed_and_bound_to_its_request() -> None:
    route = await booted()
    answer(await route.post(once=None), 400, "Problem")
    first = await route.post()
    replay = await route.post(api_secret="another-secret-" + "y" * 20)  # no secret in its print
    assert (replay.status_code, replay.headers["idempotency-replayed"]) == (201, "true")
    assert replay.content == first.content
    reuse = answer(await route.post(api_key="another-key-0000"), 409, "Problem")
    assert reuse["code"] == "idempotency_key_reuse" and len(route.world.sent) == 2  # verified once
    kept = repr(route.replays._lru)
    assert _ONCE in kept and API_KEY not in kept and API_SECRET not in kept  # AC-33


async def test_a_request_still_running_is_in_flight() -> None:
    world = World()
    world.gate.clear()
    route = Route(world)
    first = asyncio.create_task(route.post())
    async with asyncio.timeout(5):  # a lost request fails the test instead of hanging it
        await world.entered.wait()
    busy = answer(await route.post(), 409, "Problem")
    world.gate.set()
    assert busy["code"] == "idempotency_in_flight" and (await first).status_code == 201


async def test_a_body_that_fails_its_schema_is_a_422_that_echoes_no_value() -> None:
    route = await booted()
    short = answer(await route.post(api_secret=_SHORT), 422, "KeyRejectedProblem")
    assert [(e["field"], e["rule"]) for e in short["errors"]] == [("body.api_secret", "too_short")]
    extra = answer(await route.post(note="free text"), 422, "KeyRejectedProblem")
    assert extra["errors"][0]["rule"] == "extra_forbidden" and "free text" not in json.dumps(extra)
    assert _SHORT not in json.dumps(short) and route.world.sent == []


async def test_the_fake_backend_answers_503_once_the_admission_checks_pass() -> None:
    route = Route(World(), wired=False)
    assert answer(await route.post(), 503, "Problem")["code"] == "store_unavailable"
    assert (await route.post("viewer")).status_code == 403


async def test_the_route_hands_the_flow_the_label_read_only_expected_uid_and_actor() -> None:
    route = await booted()
    named = answer(await route.post(label="watch-1", expected_uid="1000001"), 201, _CREATED)
    (passed,) = route.world.audit()  # the import's record: the Owner's role and address
    shown = (named["key"]["label"], passed["actor_label"], passed["actor_ip"])
    assert shown == ("watch-1", "user:owner", "127.0.0.1")
    other = answer(await route.post(once=_TWO, expected_uid="2000002"), 422, _REJECTED)
    assert other["errors"][0]["rule"] == "expected_uid_mismatch"
    watch = answer(await (await booted()).post(read_only=True), 422, _REJECTED)
    assert watch["errors"][0]["rule"] == "key_not_read_only"  # a trade key sent as read-only


async def test_a_conflict_a_missing_kek_and_a_lost_record_answer_as_the_contract_says() -> None:
    route, no_kek, lost = await booted(), Rig(), await booted()
    assert (await route.post()).status_code == 201
    conflict = answer(await route.post(once=_TWO), 409, "Problem")  # the account's active key
    no_kek.flow = no_kek.importer(Refusing(KekUnavailable("kek_unavailable")))
    kek = answer(await Route(no_kek).post(), 403, "Problem")
    lost.world.audit_down = True  # the pass's record cannot be written: nothing is stored
    down = await lost.post()
    audit = answer(down, 503, "KeyExchangeProblem")
    codes = [conflict["code"], kek["code"], audit["code"]]
    assert codes == ["conflict", "kek_unavailable", "audit_unavailable"]
    assert (down.headers["retry-after"], lost.world.m2.rows) == ("5", {})


async def test_a_refused_key_is_kept_for_replay_like_any_other_answer() -> None:
    route = await booted(withdraw=True)
    first, again = await route.post(), await route.post()
    assert (again.status_code, again.headers["idempotency-replayed"]) == (422, "true")
    assert again.content == first.content and len(route.world.sent) == 1  # verified once


@pytest.mark.parametrize(
    "change",
    [{"label": "x"}, {"read_only": True}, {"expected_uid": "1"}, {"path": _ELSEWHERE}],
    ids=["label", "read_only", "expected_uid", "path"],
)
async def test_each_field_but_the_pair_binds_the_idempotency_key(change: dict[str, Any]) -> None:
    route = await booted()
    assert (await route.post()).status_code == 201
    assert answer(await route.post(**change), 409, "Problem")["code"] == "idempotency_key_reuse"


async def test_a_cancelled_request_leaves_its_import_to_end_and_to_be_replayed() -> None:
    route, stall, entered = await booted(), asyncio.Event(), asyncio.Event()
    record_pass = route.world.record_pass

    async def held(key_id: Any, verified: Any) -> bool:  # after M2's store, before the promotion
        entered.set()
        await stall.wait()
        return bool(await record_pass(key_id, verified))

    route.world.record_pass = held
    first = asyncio.create_task(route.post())
    async with asyncio.timeout(5):  # a lost request fails the test instead of hanging it
        await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    busy = answer(await route.post(), 409, "Problem")  # still importing, under the same key
    stall.set()
    (work,) = [task for task in asyncio.all_tasks() if task.get_name() == "create-api-key"]
    assert busy["code"] == "idempotency_in_flight" and (await work).status_code == 201
    replay = await route.post()
    assert (replay.status_code, replay.headers["idempotency-replayed"]) == (201, "true")


async def test_no_frame_of_a_failing_import_holds_the_pasted_pair_in_clear() -> None:
    broken = Rig()  # an unmapped error inside the import, rendered with every local (C-12.6)
    broken.flow = broken.importer(Refusing(RuntimeError("a defect")))
    with pytest.raises(RuntimeError) as raised:
        await Route(broken, raises=True).post()
    stack = traceback.TracebackException.from_exception(raised.value, capture_locals=True).stack
    ours = [frame for frame in stack if f"{os.sep}candleviewer{os.sep}" in frame.filename]
    shown = repr([frame.locals for frame in ours])
    assert "create_api_key" in {frame.name for frame in ours}
    assert API_KEY not in shown and API_SECRET not in shown
