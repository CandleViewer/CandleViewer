"""Contract, provider side (#906 slices D2-4 to D2-6): the profile writes behind the write edge, in
`_profile_writes_world`'s world until D2-m mounts them. Every answer validates against what its
operation declares. The shared tests run over `_WRITES`, the default binding's move among them.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

import candleviewer
from candleviewer.accounts.models import ExchangeEnv
from candleviewer.accounts.override_comparator import AccountFigures
from candleviewer.accounts.profile_caps import PROFILE_CAPS
from candleviewer.accounts.profile_repository import ARMED_SHOWN, ArmedRule
from candleviewer.accounts.profile_validator import (
    InstrumentLimitsUnavailable,
    SaveFigures,
    SymbolFigures,
)
from candleviewer.accounts.profiles import profile_from_row, to_us
from candleviewer.accounts.sizer import SizingMarket
from candleviewer.api import profile_body as edge
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.idempotency import IDEMPOTENCY_TTL_S
from candleviewer.api.profile_audit import profile_state
from candleviewer.api.profile_body import MAX_BINDING_BODY_BYTES, MAX_PROFILE_BODY_BYTES
from candleviewer.api.profile_projection import profile_body, profile_document
from candleviewer.api.profile_writes import make_profile_writes_router
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.rules.ir.schema import to_json_schema
from candleviewer.rules.vocabulary.catalogue import ACTIONS
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories import account_profiles as port
from candleviewer.storage.repositories.accounts import AccountsStoreError, OwnerScope
from tests.contract._admin_support import SPEC, validate_example
from tests.contract._profile_writes_world import WRITTEN, Row, Writes, build
from tests.contract.rbac import rbac_harness as rbac
from tests.contract.test_account_profile_reads_provider import EMPTIED, ENV, Store
from tests.unit.accounts.test_profile_validator import _LISTED

LIST = "/exchange-accounts/{accountId}/profiles"
ITEM = LIST + "/{profileId}"
BINDING = "/exchange-accounts/{accountId}/default-profile"
#: 22's `riskBased` example: trading-enabled, every cap bounded, BTC and ETH allowed.
_EXAMPLES = SPEC["paths"][LIST]["post"]["requestBody"]["content"]["application/json"]["examples"]
_RISK: dict[str, Any] = _EXAMPLES["riskBased"]["value"]
_NO_OFF = "Every order carries a native stop-loss, so it cannot be turned off."
_NATIVE = {"field": "require_native_stop", "rule": "native_stop_mandatory", "message": _NO_OFF}
_NAME_TAKEN = "A profile of this account already uses that name, in any letter case."
_SAVE_REFUSED, _CREATED, _REUSE = "profile.save_refused", "profile.created", "idempotency_key_reuse"
_UNAUDITED, _DOWN = "audit_unavailable", "store_unavailable"
GRANTED, FOREIGN = rbac.GRANTED, rbac.FOREIGN  # FOREIGN is a `live` account, EMPTIED `testnet`
#: GRANTED's default ("Risk 1%", version 3) and "Alt" (version 2: it can trade, and allows every
#: symbol but DOGEUSDT), which `_ALT` reads and sends back whole.
DEFAULT, ALT = uuid.UUID(int=1), uuid.UUID(int=2)
_ALT: dict[str, Any] = profile_body(profile_from_row(Store().rows[GRANTED][1]))
_ALT_3 = f'W/"{ALT}:3"'  # Alt replaced once
_BOUND_1 = f'W/"{GRANTED}:default:1"'  # GRANTED's binding, on DEFAULT since the account began
_STALE = "If-Match does not name this profile's current version. Nothing was changed."
_STALE_BINDING = (
    "If-Match does not name this account's current default binding. Nothing was changed."
)


@dataclass(frozen=True)
class Write:
    """A profile write: its operation, method, path template, a body it stores (`None`: none is
    read), the records it writes and the `If-Match` it sends."""

    name: str
    method: str
    template: str
    body: dict[str, Any] | None
    actions: tuple[str, ...] = (_CREATED,)
    if_match: str | None = None


_WRITES = [
    Write("createAccountProfile", "POST", LIST, _RISK),
    Write("updateAccountProfile", "PUT", ITEM, _ALT, ("profile.updated",), f'W/"{ALT}:2"'),
    Write("deleteAccountProfile", "DELETE", ITEM, None, ("profile.deleted",), f'W/"{ALT}:2"'),
    Write(
        "setAccountDefaultProfile", "PUT", BINDING, {"profile_id": str(ALT)},
        ("profile.unbound", "profile.bound"), _BOUND_1,
    ),
]  # fmt: skip
CREATE, REPLACE, DELETE, MOVE = _WRITES
_BODIED = pytest.mark.parametrize("write", [CREATE, REPLACE], ids=["create", "replace"])
_EACH = pytest.mark.parametrize("write", _WRITES, ids=[write.name for write in _WRITES])


@pytest.fixture(scope="module")
def _world() -> Iterator[Writes]:
    with pytest.MonkeyPatch.context() as mp:  # undone however the module ends
        yield build(mp)


@pytest.fixture
def w(_world: Writes) -> Iterator[Writes]:
    _world.reset()
    yield _world
    assert None not in _world.rows.hooks  # no write without its record (D2-2 R1S-02)


def send(
    w: Writes, write: Write, actor: str = "owner", at: object = GRANTED, *, body: object = None,
    key: str | None = None, raw: bytes | None = None, headers: dict[str, str] | None = None,
    profile: object = ALT, tags: list[str] | None = None,
) -> Any:  # fmt: skip
    """`write` by `actor`'s session on account `at` (and `profile`): `raw`, else `body` (the
    write's) as JSON; `If-Match` the write's own, or one header per tag of `tags`."""
    sent = {**(headers or rbac.bearer(actor)), "content-type": "application/json"}
    sent |= {} if key is None else {"idempotency-key": key}
    payload = write.body if body is None else body
    content = raw or (None if payload is None else json.dumps(payload).encode())
    path = write.template.format(accountId=at, profileId=profile)
    tags = ([] if write.if_match is None else [write.if_match]) if tags is None else tags
    pairs = [*sent.items(), *(("if-match", tag) for tag in tags)]
    return w.world.client.request(write.method, path, content=content, headers=pairs)


def create(w: Writes, body: object, **kw: Any) -> Any:
    return send(w, _WRITES[0], body=body, **kw)


def answered(resp: Any, write: Write = _WRITES[0]) -> Any:
    """The body, once it validates against what the operation declares for its status."""
    status, method = resp.status_code, write.method.lower()
    declared = SPEC["paths"][write.template][method]["responses"][str(status)]
    own = f"#/paths/{write.template.replace('/', '~1')}/{method}/responses/{status}"
    media = "application~1json" if status < 300 else "application~1problem+json"
    validate_example(f"{declared.get('$ref', own)[1:]}/content/{media}/schema", resp.json())
    return resp.json()


def _new(w: Writes) -> list[port.AccountProfileRow]:
    """The rows the writes stored (created, replaced or deleted), on any account."""
    stored = [row for rows in w.rows.rows.values() for row in rows if row.updated_at == WRITTEN]
    return stored + w.rows.deleted


def _names(record: dict[str, Any], resp: Any, actor: str = "owner", on: object = GRANTED) -> None:
    """A refusal's record names its actor and address, the account (or the profile a replace
    names), the session (#4174) and the request (D2-4 R1C-03)."""
    ids = [rbac.user_id_of(actor), rbac.session_id_of(actor), str(on), "127.0.0.1"]
    assert [record[k] for k in ("actor_user_id", "session_id", "object_id", "actor_ip")] == ids
    assert record["object_kind"] == ("exchange_account" if on == GRANTED else "account_profile")
    assert str(record["request_id"]) == resp.headers["x-correlation-id"]  # D2-2 R1C-02


async def _never(*_args: Any, **_kwargs: Any) -> None:
    """A writer that never answers: only a bound ends it."""
    await asyncio.Event().wait()


def _refused_save(
    w: Writes, resp: Any, reason: str, entries: list[dict[str, str]], on: object = GRANTED
) -> None:
    """A 422 recorded as one `profile.save_refused` of `reason`, holding `entries`; no row."""
    (record,) = w.world.audit.records
    _names(record, resp, on=on)
    assert (resp.status_code, record["action"], record["reason"]) == (422, _SAVE_REFUSED, reason)
    after = {"exchange_account_id": str(GRANTED), "count": len(entries), "errors": entries}
    assert (record["after_state"], _new(w)) == (after, [])


def test_ac1_a_risk_based_create_is_201_version_1_with_its_etag_and_record(w: Writes) -> None:
    """AC-1; `profile.created` from the hook the store got (D2-2 R1S-02); every store call the
    Owner's (SR-051); the account's effective profiles invalidated (SR-E28-15)."""
    w.minted.append(minted := uuid.uuid4())  # the router's id factory (D2-4 R1C-04)
    resp = create(w, _RISK)
    (row,) = _new(w)
    assert row.id == minted
    env, created = ExchangeEnv.DEMO, to_us(WRITTEN)
    doc = profile_document(profile_from_row(row), created_at=created, environment=env, warnings=())
    got = answered(resp)
    assert (resp.status_code, got, resp.headers["etag"]) == (201, doc, f'W/"{row.id}:1"')
    assert (got["version"], got["profile"]["name"]) == (1, _RISK["name"])
    (record,) = w.world.audit.records
    keys = ("action", "object_id", "outcome", "after_state", "session_id", "actor_ip")
    assert [record[k] for k in keys] == [
        "profile.created", str(row.id), "success", profile_state(row), None, "127.0.0.1",
    ]  # fmt: skip
    assert str(record["request_id"]) == resp.headers["x-correlation-id"]
    assert (w.invalidated, len(w.rows.hooks)) == ([GRANTED], 1)
    owner = OwnerScope(rbac.user_id_of("owner"))
    assert w.rows.seen == [("account", owner), ("profiles", owner)]


_STOPLESS = {key: value for key, value in _RISK.items() if key != "stop_loss"}
_IN_R = {"unit": "r_multiple", "value": "1"}
_INFINITE = json.dumps(_RISK)[:-1].encode() + b', "slippage_tolerance_bps": 1e400}'  # D2-3 R1S-03


@pytest.mark.parametrize(
    ("body", "entry"),
    [
        (_STOPLESS, ("stop_loss", "required")),
        ({**_RISK, "stop_loss": _IN_R}, ("stop_loss.unit", "stop_defines_r")),
        ({**_RISK, "is_default": True}, ("is_default", "default_has_own_operation")),
        ({**_RISK, "name": "Alice\x00"}, ("name", "string_pattern_mismatch")),
        ({**_RISK, "name": "Al\u200bice"}, ("name", "not_allowed")),  # Cf (D2-3 R1S-04)
        ({**_RISK, "colour": "red"}, ("", "extra_forbidden")),
        (_INFINITE, ("slippage_tolerance_bps", "int_type")),
    ],
    ids=["stopless-risk", "r-multiple-stop", "is-default", "c0-name", "cf-name", "extra", "1e400"],
)  # fmt: skip
def test_a_create_refused_by_its_shape_is_an_unaudited_422_and_stores_nothing(
    w: Writes, body: object, entry: tuple[str, str]
) -> None:
    resp = create(w, body, raw=body if isinstance(body, bytes) else None)
    got = answered(resp)
    assert (resp.status_code, got["detail"]) == (422, "1 member failed validation.")
    assert [(e["field"], e["rule"]) for e in got["errors"]] == [entry]
    assert (w.world.audit.records, _new(w), w.limits.calls) == ([], [], 0)


@_BODIED
@pytest.mark.parametrize("path", ["schema", "combined", "store"])
def test_native_sl_false_refused_by_every_path(w: Writes, path: str, write: Write) -> None:
    """SR-E28-08, AC-01: refused and audited alone, among 30 other failures (B1's entry follows the
    model's 20: #4087 R3-02's combined case), and as the store's `ap_native_sl` CHECK; on a create
    and on a replace (D2-5), whose record names its profile."""
    body = {**(write.body or {}), "require_native_stop": False}
    if path == "combined":
        body |= {"colour": "red", "allowed_symbols": ["x"] * 30}
    if path == "store":
        rule = port.AccountProfileStoreRuleError("ap_native_sl")
        body, w.rows.fails["profiles" if write is CREATE else "update"] = write.body or {}, rule
    resp = send(w, write, body=body)
    errors = answered(resp, write)["errors"]
    assert (len(errors), errors[-1]) == ({"combined": 21}.get(path, 1), _NATIVE)
    _refused_save(w, resp, "native_stop_mandatory", [_NATIVE], GRANTED if write is CREATE else ALT)


def test_trading_enabled_profile_requires_loss_caps(w: Writes) -> None:
    """SR-E28-01, R1C-08: no `risk_caps` on a trading-enabled profile leaves its five loss bounds
    open: five `cap_unbounded` entries, one record (PF-T02)."""
    resp = create(w, {key: value for key, value in _RISK.items() if key != "risk_caps"})
    errors = answered(resp)["errors"]
    caps = "position_notional_usd daily_loss_usd open_positions concurrent_orders leverage_cap"
    want = [(f"risk_caps.max_{cap}", "cap_unbounded") for cap in caps.split()]
    assert [(e["field"], e["rule"]) for e in errors] == want
    _refused_save(w, resp, "cap_unbounded", errors)


def test_ac4_leverage_above_an_allowed_symbols_maximum_names_it_and_is_audited(w: Writes) -> None:
    """AC-4: the listing caps SOLUSDT at 20x, so 25x is refused with 22's own example, audited."""
    rejected = SPEC["components"]["responses"]["ProfileRejected"]["content"]
    example = rejected["application/problem+json"]["examples"]["leverageAboveExchangeMax"]["value"]
    caps = {**_RISK["risk_caps"], "max_leverage_cap": "25"}
    resp = create(w, {**_RISK, "leverage": "25", "risk_caps": caps, "allowed_symbols": ["SOLUSDT"]})
    got = answered(resp)
    assert (got["detail"], got["errors"]) == (example["detail"], example["errors"])
    assert w.limits.calls == 1
    _refused_save(w, resp, "max_leverage", example["errors"])


def test_a_stale_catalogue_is_503_retry_after_2_and_its_retry_is_a_first_submission(
    w: Writes,
) -> None:
    """PF-D04: never audited, stored or kept for replay, so its retry is a first submission."""
    w.limits.fails, key = InstrumentLimitsUnavailable("no listing in time"), str(uuid.uuid4())
    resp = create(w, _RISK, key=key)
    got = answered(resp)
    assert (got["code"], got["retry_after_seconds"], resp.headers["retry-after"]) == (
        "instrument_cache_unavailable", 2, "2",
    )  # fmt: skip
    assert (resp.status_code, w.world.audit.records, _new(w)) == (503, [], [])
    w.limits.fails = None
    retried = create(w, _RISK, key=key)
    assert (retried.status_code, "idempotency-replayed" in retried.headers) == (201, False)


@_BODIED
def test_a_writes_answer_carries_the_second_passes_warnings(w: Writes, write: Write) -> None:
    """The patterns admit every listed, trading perpetual (BTC, ETH, SOL), as no read can see; a
    replace answers them as a create does (D2-5 R1C-01)."""
    patterns = {"all_symbols": False, "allowed_symbols": ["*CUSDT", "*HUSDT", "*LUSDT"]}
    resp = send(w, write, body={**(write.body or {}), **patterns})
    message = "Allows every listed symbol — consider restricting."
    warning = {"code": "all_symbols", "message": message, "field": "allowed_symbols"}
    assert (resp.is_success, answered(resp, write)["warnings"]) == (True, [warning])


def test_a_writes_answer_carries_the_sizing_warnings_of_its_port(w: Writes) -> None:
    """E28-T03: the profile routes' `warnings` port feeds the second pass (SR-E28-26); a rate of
    0.5 puts the estimated liquidation past entry, so the 2 % fallback stop lies beyond it."""
    figures = AccountFigures.model_validate(dict.fromkeys(AccountFigures.model_fields))
    one = SymbolFigures(_LISTED["BTCUSDT"], SizingMarket(mid=Decimal(64000)), Decimal("0.5"))
    port = AsyncMock()
    port.open_symbols.return_value = ()
    port.figures.return_value = SaveFigures(figures, False, {"BTCUSDT": one})
    object.__setattr__(w.writes, "warnings", port)  # the frozen wiring, for this test alone
    try:
        resp = create(w, _RISK)
    finally:
        object.__setattr__(w.writes, "warnings", None)
    got = answered(resp)["warnings"]
    assert (resp.status_code, [(x["code"], x.get("symbol"), x.get("estimated")) for x in got]) == (
        201, [("stop_beyond_liquidation", "BTCUSDT", True)],
    )  # fmt: skip
    port.figures.assert_awaited_once()
    assert port.figures.await_args.args[1] == ("BTCUSDT", "ETHUSDT")


def test_a_create_replays_its_201_and_refuses_the_key_for_another_body(
    w: Writes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SR-E28-17; the account is read first, so a replay on one deleted since is 404 (#4157
    R1S-02). The replay comes before the passes, and another Owner's same request runs."""
    key = str(uuid.uuid4())
    first, again = create(w, _RISK, key=key), create(w, _RISK, key=key)
    assert (again.status_code, again.content) == (201, first.content)
    replayed = (again.headers["etag"], again.headers["idempotency-replayed"])
    assert replayed == (first.headers["etag"], "true") and len(w.world.audit.records) == 1
    assert w.limits.calls == 1  # D2-4's combined re-check, R2-01
    monkeypatch.setitem(ENV, EMPTIED, "demo")  # a second account of this environment
    reused = [create(w, {**_RISK, "name": "Bob"}, key=key), create(w, _RISK, key=key, at=EMPTIED)]
    assert {(r.status_code, answered(r)["code"]) for r in reused} == {(409, _REUSE)}
    malformed = answered(create(w, _RISK, key="not-a-uuid"))["errors"]
    assert [(e["field"], e["rule"]) for e in malformed] == [("Idempotency-Key", "uuid_parsing")]
    other = PrincipalSnapshot(uuid.uuid4(), frozenset({"owner"}), frozenset(Permission))
    with monkeypatch.context() as patched:
        patched.setattr(w.world.resolver, "snapshot", lambda _actor: other)
        theirs = create(w, _RISK, key=key)
    assert answered(theirs)["detail"] == _NAME_TAKEN
    assert "idempotency-replayed" not in theirs.headers
    monkeypatch.delitem(w.rows.rows, GRANTED)
    assert answered(create(w, _RISK, key=key))["code"] == "not_found"
    assert (len(w.rows.hooks), [r["action"] for r in w.world.audit.records]) == (2, [_CREATED])


def test_a_lost_answer_older_than_24_hours_re_runs_and_meets_its_own_name(w: Writes) -> None:
    """SR-E28-17: replayed for 24 h on the cache's monotonic clock, then run again (409)."""
    key = str(uuid.uuid4())
    assert create(w, _RISK, key=key).status_code == 201
    w.clock[0] += IDEMPOTENCY_TTL_S - 1
    assert create(w, _RISK, key=key).headers["idempotency-replayed"] == "true"
    w.clock[0] += 1
    late = create(w, _RISK, key=key)
    assert (late.status_code, answered(late)["detail"], len(_new(w))) == (409, _NAME_TAKEN, 1)


@_EACH
def test_a_write_on_a_missing_deleted_or_other_environment_account_is_404_alike(
    w: Writes, write: Write
) -> None:
    """C-2.11: missing or deleted (both read as none), `live`, `testnet`, or gone by the write
    (a 404 of its profile, on a profile's route)."""
    sent = [send(w, write, at=account) for account in (uuid.uuid4(), FOREIGN, EMPTIED)]
    w.rows.gone.add(GRANTED)
    gone = send(w, write)
    sent += [gone] if write is CREATE else []
    assert {(r.status_code, r.text) for r in sent} == {(404, sent[0].text)}
    assert answered(sent[0], write)["detail"] == "No such exchange account."
    assert (gone.status_code, w.world.audit.records, _new(w)) == (404, [], [])


@_BODIED
def test_a_body_over_its_cap_is_413_before_it_is_parsed(
    w: Writes, write: Write, monkeypatch: pytest.MonkeyPatch
) -> None:
    """22: over 64 KiB is `413 payload_too_large`, refused by `read_capped`, the body's one reader
    (D2-4 R1S-03), before it is decoded (it would nest too deep); one past 1 KiB is read whole
    (D2-4 R1C-03 c): 120 unlisted symbols, each refused by the second pass."""
    caps, reader = list[int](), edge.read_capped

    async def spy(request: Any, cap: int) -> bytes:
        caps.append(cap)
        return await reader(request, cap)

    monkeypatch.setattr(edge, "read_capped", spy)
    resp = send(w, write, raw=b"[" * (MAX_PROFILE_BODY_BYTES + 1))
    assert (resp.status_code, answered(resp, write)["code"]) == (413, "payload_too_large")
    assert (w.world.audit.records, _new(w), w.limits.calls) == ([], [], 0)
    unlisted = [f"Q{i:03}USDT" for i in range(120)]
    body = {**(write.body or {}), "all_symbols": False, "allowed_symbols": unlisted}
    rules = [e["rule"] for e in answered(send(w, write, body=body), write)["errors"]]
    assert len(json.dumps(body)) > MAX_BINDING_BODY_BYTES and rules == ["symbol_not_listed"] * 120
    assert caps == [MAX_PROFILE_BODY_BYTES] * 2


@_EACH
def test_profile_write_without_step_up_is_403_and_changes_nothing(w: Writes, write: Write) -> None:
    """SR-E28-02, the route's half: never the handler. The guard's (B16's `auth.step_up_required`
    record) is `test_profile_step_up_gate.py`'s; the pack's step-up stand-in records nothing."""
    w.world.step_up.elevated = False
    try:
        sent = [send(w, write, actor) for actor in ("owner", "manager_with_grant")]
    finally:
        w.world.step_up.elevated = True
    want = (403, "step_up_required", "risk_caps")
    for resp in sent:
        got = answered(resp, write)
        assert (resp.status_code, got["code"], got["action_class"]) == want
    assert (w.rows.seen, w.world.audit.records, _new(w)) == ([], [], [])


@_EACH
def test_a_manager_with_a_live_grace_is_403_audited_and_changes_nothing(
    w: Writes, write: Write, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#4087 R1S-04, Gherkin 8: `accounts:write` before any store read; no principal is 401, and a
    viewing session meets the view-as guard, never the handler (D1c R2-03)."""
    for actor in ("manager_with_grant", "manager_without_grant", "viewer"):
        resp = send(w, write, actor)
        assert answered(resp, write)["required_permissions"] == ["accounts:write"]
        (record,) = w.world.audit.records
        _names(record, resp, actor)
        assert record["reason"] == "missing_permission:accounts:write:none"
        w.world.audit.records.clear()
    viewing = send(w, write, headers=rbac.bearer_viewing("manager_with_grant"))
    assert (viewing.status_code, viewing.json()["code"]) == (403, "view_as_read_only")
    monkeypatch.setattr(w.world.resolver, "resolve", lambda _request: None)
    assert answered(send(w, write), write)["code"] == "unauthenticated"
    actions = {r["action"] for r in w.world.audit.records} & {"rbac.denied", *write.actions}
    assert (w.rows.seen, _new(w), actions) == ([], [], set())


@_EACH
@pytest.mark.parametrize(
    ("case", "error"),
    [("hook", AuditUnavailable("full")), ("rbac", AuditUnavailable("full")),
     ("rbac", RuntimeError("not started")), ("save", AuditUnavailable("full")), ("timeout", None)],
)  # fmt: skip
def test_a_write_whose_audit_record_cannot_be_written_changes_nothing(
    w: Writes, monkeypatch: pytest.MonkeyPatch, write: Write, case: str, error: Exception | None
) -> None:
    """C-2.9, the ruling of 2026-10-22 17:25Z (3): the hook's, `rbac.denied`'s or a refusal's
    record unwritten, or a hook past the store's bound (forced with 0)."""
    monkeypatch.setattr(w.world.audit, "emit", AsyncMock(side_effect=error or _never))
    monkeypatch.setattr(w.rows, "timeout_s", 0 if error is None else w.rows.timeout_s)
    saves = case == "save" and write in (CREATE, REPLACE)  # a delete or a move records no refusal
    body = {**(write.body or {}), "require_native_stop": False} if saves else None
    resp = send(w, write, "manager_with_grant" if case == "rbac" else "owner", body=body)
    got = answered(resp, write)
    assert (resp.status_code, got["code"], resp.headers["retry-after"]) == (503, _UNAUDITED, "5")
    hooked = case in {"hook", "timeout"} or (case == "save" and not saves)  # its hook's record
    assert (len(w.rows.hooks), _new(w)) == (hooked, [])


@_EACH
@pytest.mark.parametrize(
    ("where", "error", "logged"),
    [
        ("account", AccountsStoreError(), ("AccountsError", None)),
        ("account", ConnectionRefusedError(), ("ConnectionRefusedError", None)),  # the driver's
        ("profiles", StorageTierUnavailable("down"), ("StorageTierUnavailable", None)),
        ("profiles", StorageQueryFailed("57014"), ("StorageQueryFailed", "57014")),  # a timeout
        ("profiles", port.AccountProfileStoreConflictError("account_profiles_pkey"),
         ("AccountConflictError", None)),  # a conflict that is not the name's
        ("commit", StorageTierUnavailable("the commit"), ("StorageTierUnavailable", None)),
    ],
)  # fmt: skip
def test_a_store_that_cannot_answer_is_503_and_a_failed_commit_keeps_its_record(
    w: Writes, write: Write, where: str, error: Exception, logged: tuple[str, str | None]
) -> None:
    """Logged by class and SQLSTATE alone (C-12.6); a commit failing after its hook keeps the
    record written ahead: write-ahead over-reports, never under-reports."""
    w.rows.fails[where] = error
    w.rows.fail_commit = where == "commit"
    with capture_logs() as logs:
        resp = send(w, write)
    got = answered(resp, write)
    assert (resp.status_code, got["code"], resp.headers["retry-after"]) == (503, _DOWN, "5")
    unavailable = [log for log in logs if log["event"] == "profile_write_unavailable"]
    assert [(log["error"], log["sqlstate"]) for log in unavailable] == [logged] and _new(w) == []
    created = list(write.actions) if where == "commit" else []
    assert [record["action"] for record in w.world.audit.records] == created


def test_without_a_store_the_writes_are_503_after_rbac(w: Writes) -> None:
    """The fake backend: an Owner's 503 comes after `enforce`; no resolver wired is 501."""

    def client(resolver: Any) -> TestClient:
        app = FastAPI()
        app.include_router(make_profile_writes_router(None, w.world.audit, resolver))
        return TestClient(app)

    for write in _WRITES:
        path = write.template.format(accountId=GRANTED, profileId=ALT)
        storeless = client(w.world.resolver)
        owner = storeless.request(write.method, path, headers=rbac.bearer("owner"))
        manager = storeless.request(write.method, path, headers=rbac.bearer("manager_with_grant"))
        unwired = client(None).request(write.method, path)
        assert answered(owner, write)["detail"] == "Profiles are not available on this backend."
        assert (manager.status_code, unwired.status_code) == (403, 501)


@_EACH
@pytest.mark.parametrize("gate", ["account", "profiles"])
def test_the_stores_owner_gate_refusing_an_owner_is_403_and_audited(
    w: Writes, write: Write, gate: str
) -> None:
    """SR-051, `enforce`'s reason shape; recorded, so never logged as unaudited (D1c R3-02)."""
    w.rows.gated.add(gate)
    with capture_logs() as logs:
        resp = send(w, write)
    assert answered(resp, write)["required_permissions"] == ["accounts:write"]
    (record,) = w.world.audit.records
    _names(record, resp)
    assert (record["reason"], _new(w)) == ("not_owner:accounts:write:granted_accounts", [])
    assert not [log for log in logs if log["event"] == "profile_read_denial_unaudited"]


def test_a_stored_rule_the_passes_missed_is_an_unaudited_422_logged_by_its_name(w: Writes) -> None:
    """A CHECK other than `ap_native_sl` names its rule, logged at error by name, never audited."""
    w.rows.fails["profiles"] = port.AccountProfileStoreRuleError("ap_trading_caps")
    with capture_logs() as logs:
        resp = create(w, _RISK)
    entry = {"field": "", "rule": "ap_trading_caps", "message": "The profile breaks a stored rule."}
    assert (resp.status_code, answered(resp)["errors"], w.world.audit.records) == (422, [entry], [])
    event = "profile_write_refused_by_constraint"
    logged = [log for log in logs if log["event"] == event]
    assert logged == [{"event": event, "log_level": "error", "rule": "ap_trading_caps"}]


def test_an_error_that_is_no_outage_is_a_500(w: Writes) -> None:
    """A defect fails visibly, never a 404 or a retryable 503, and echoes nothing."""
    w.rows.fails["account"] = TypeError("a defect")
    resp = create(w, _RISK)
    assert (resp.status_code, resp.json()["code"]) == (500, "internal_error")
    assert "defect" not in resp.text


def test_the_writes_are_served_on_the_literal_contract_templates(w: Writes) -> None:
    """#4087 R1S-01: no path convertor under the prefix lets an `a/b` id slip the step-up's rows."""
    ops = served_operations(w.world.app)
    assert {(write.method, write.template) for write in _WRITES} <= ops
    assert not [path for _, path in ops if path.startswith("/exchange-accounts/") and ":" in path]


def _row(w: Writes, profile: uuid.UUID = ALT) -> Row:
    return next(row for row in w.rows.rows[GRANTED] if row.id == profile)


def _bumped(row: Row) -> Row:
    """`race`: another session's write landed on the row since the router read it."""
    return dataclasses.replace(row, version=row.version + 1)


def _made_default(row: Row) -> Row:
    """`race`: the default moved onto the row since the read, with no version bump."""
    return dataclasses.replace(row, values=dataclasses.replace(row.values, is_default=True))


def test_a_replace_is_200_at_the_next_version_and_records_before_and_after(w: Writes) -> None:
    """The document at version 3 with its `ETag`; `profile.updated` from the store's hook, before
    and after, not relaxing; the account's effective profiles invalidated (SR-E28-15)."""
    before, body = _row(w), {**_ALT, "name": "Alt 2", "leverage": "2"}
    resp = send(w, REPLACE, body=body)
    (after,) = _new(w)
    profile, at = profile_from_row(after), to_us(after.created_at)
    doc = profile_document(profile, created_at=at, environment=ExchangeEnv.DEMO)
    assert (resp.status_code, answered(resp, REPLACE), resp.headers["etag"]) == (200, doc, _ALT_3)
    (record,) = w.world.audit.records
    labels = {"relaxing": False, "looser_caps": [], "widened_symbols": False}
    keys = ("action", "object_id", "severity", "before_state", "after_state", "session_id")
    assert [record[k] for k in keys] == [
        "profile.updated", str(ALT), "info", profile_state(before), profile_state(after) | labels,
        None,
    ]  # fmt: skip
    assert str(record["request_id"]) == resp.headers["x-correlation-id"]
    assert (w.invalidated, w.rows.notices) == ([GRANTED], [])


def test_r1c08_a_trading_disabled_replace_without_risk_caps_clears_them_in_the_record(
    w: Writes,
) -> None:
    """R1C-08: a member left out takes its default, so turning trading off without `risk_caps`
    clears every cap (`max_orders_per_minute` back to 30), shown before and after; a profile that
    cannot trade bounds every cap at zero, so it is never relaxing."""
    body = {key: value for key, value in _ALT.items() if key != "risk_caps"}
    resp = send(w, REPLACE, body=body | {"trading_enabled": False})
    (record,) = w.world.audit.records
    caps = {cap.column: None for cap in PROFILE_CAPS} | {"max_orders_per_minute": 30}
    assert (resp.status_code, {c: record["after_state"][c] for c in caps}) == (200, caps)
    said = (record["before_state"]["max_leverage_cap"], record["after_state"]["relaxing"])
    assert (said, record["severity"], w.rows.notices) == (("5", False), "info", [])


_CAPS = _ALT["risk_caps"]


@pytest.mark.parametrize(
    ("change", "looser", "widened"),
    [
        ({"risk_caps": {**_CAPS, "max_leverage_cap": "8"}}, ["max_leverage_cap"], False),
        ({"risk_caps": {**_CAPS, "max_position_notional_usd": "100000",
                        "max_position_pct_equity": None}}, ["max_position_pct_equity"], False),
        ({"blocked_symbols": []}, [], True),
        ({"risk_caps": {**_CAPS, "max_leverage_cap": "4"}}, [], False),
    ],
    ids=["raised", "removed", "unblocked", "narrowed"],
)  # fmt: skip
def test_a_relaxing_replace_is_labelled_and_notifies_the_owner(
    w: Writes, change: dict[str, Any], looser: list[str], widened: bool
) -> None:
    """SR-E28-01, the 2026-10-22 17:25Z ruling (1): a cap raised or removed, or a block entry
    removed, labels the record `relaxing`, a warning, and commits one notice with the change; a
    narrowing does neither."""
    resp = send(w, REPLACE, body={**_ALT, **change})
    (record,) = w.world.audit.records
    relaxing = bool(looser) or widened
    labels = {"relaxing": relaxing, "looser_caps": looser, "widened_symbols": widened}
    assert (resp.status_code, {key: record["after_state"][key] for key in labels}) == (200, labels)
    assert record["severity"] == ("warning" if relaxing else "info")
    request_id = uuid.UUID(resp.headers["x-correlation-id"])
    notice = port.RelaxedNotice(ALT, None, (*looser,), widened, request_id)
    assert w.rows.notices == ([notice] if relaxing else [])


def test_a_replace_needs_the_current_etag(w: Writes) -> None:
    """The 07:10Z ruling: `If-Match` is required (428, the contract's detail), one weak tag of this
    profile (any other form is 412); a stale one, even past an int4 (D2-3 R1S-02), is 412 in the
    router, the store's write (failing here) never called. The store's own compare is T48's."""
    w.rows.fails["update"] = StorageTierUnavailable("never reached")
    forms = [
        "*", f'W/"{ALT}:2", W/"{ALT}:3"', f'"{ALT}:2"', f'w/"{ALT}:2"', f'W/"{DEFAULT}:3"',
        f'W/"{GRANTED}:default:1"', f'W/"{ALT}:0"', f'W/"{ALT}:{"9" * 20}"', f'W/"{ALT}:1"',
        f'W/"{ALT}:{2**31}"',
    ]  # fmt: skip
    tagged = [[], *([form] for form in forms), [f'W/"{ALT}:2"'] * 2]  # none, each form, two
    sent = [send(w, REPLACE, tags=tags) for tags in tagged]
    (status, problem), *refused = [(resp.status_code, answered(resp, REPLACE)) for resp in sent]
    detail = "This write needs the current ETag; send it as If-Match. Nothing was changed."
    assert (status, problem["code"], problem["detail"]) == (428, "precondition_required", detail)
    said = {(status, problem["code"], problem["detail"]) for status, problem in refused}
    assert said == {(412, "version_conflict", _STALE)}  # one detail, form or version (R2M-4)
    kinds = {kind for kind, _ in w.rows.seen}
    assert ("update" in kinds, w.world.audit.records, w.rows.hooks) == (False, [], [])


@pytest.mark.parametrize(
    ("tags", "status", "recorded"),
    [([], 428, 0), (["*"], 412, 0), ([f'W/"{ALT}:1"'], 422, 1)],
    ids=["no-tag", "star", "stale"],
)
def test_a_replaces_body_is_read_only_past_a_well_formed_if_match(
    w: Writes, tags: list[str], status: int, recorded: int
) -> None:
    """Sec.3.2 (D2-5 R1C-01): no body is evaluated on U1's 428 or 412, so nothing in it is
    audited; a stale but well-formed tag passes U1, and the schema phase, which comes before the
    profile is read and compared, refuses the native stop off and records it (U3 before U5)."""
    resp = send(w, REPLACE, body={**_ALT, "require_native_stop": False}, tags=tags)
    assert (resp.status_code, len(w.world.audit.records)) == (status, recorded)


def test_a_replace_refuses_a_hidden_code_point_in_its_name_unaudited(w: Writes) -> None:
    """D2-5 R1C-01: a replace runs the name check as a create does (D2-c R1S-06)."""
    resp = send(w, REPLACE, body={**_ALT, "name": "Al\u200bt"})
    entries = [(e["field"], e["rule"]) for e in answered(resp, REPLACE)["errors"]]
    assert (resp.status_code, entries) == (422, [("name", "not_allowed")])
    assert w.world.audit.records == []


def test_a_replaces_limit_refusal_says_so_and_records_its_profile(w: Writes) -> None:
    """D2-5 R1C-01: an unlisted symbol is refused as a limit, its detail saying so, and recorded
    once, naming the profile."""
    resp = send(w, REPLACE, body={**_ALT, "all_symbols": False, "allowed_symbols": ["QQQUSDT"]})
    got = answered(resp, REPLACE)
    assert got["detail"] == "1 member breaks an exchange limit."
    _refused_save(w, resp, "symbol_not_listed", got["errors"], ALT)


@pytest.mark.parametrize(
    ("profile", "body", "tags", "race"),
    [
        (ALT, {**_ALT, "is_default": True}, None, None),
        (DEFAULT, _RISK, [f'W/"{DEFAULT}:3"'], None),  # the default, `is_default` left out: false
        (ALT, _ALT, None, _made_default),
    ],
    ids=["made-default", "unmade", "moved-since"],
)
def test_a_replace_that_moves_the_default_is_an_unaudited_422(
    w: Writes, profile: uuid.UUID, body: dict[str, Any], tags: list[str] | None,
    race: Callable[[Row], Row] | None,
) -> None:  # fmt: skip
    """Only `setAccountDefaultProfile` moves the binding: the first pass refuses an `is_default`
    other than the stored one before any write or listing read, and the store a default moved
    since the read with no version bump (`default_moves_alone`), with the same entry, unaudited."""
    w.rows.race = race
    resp = send(w, REPLACE, body=body, profile=profile, tags=tags)
    own = "The default binding has its own operation."
    entry = {"field": "is_default", "rule": "default_has_own_operation", "message": own}
    assert (resp.status_code, answered(resp, REPLACE)["errors"]) == (422, [entry])
    assert (w.world.audit.records, w.limits.calls, _new(w)) == ([], 0, [])
    assert len(w.rows.hooks) == (race is not None)


def test_a_replace_that_only_narrows_saves_while_the_catalogue_is_down(w: Writes) -> None:
    """Q4 (the ruling of 2026-10-22 14:39Z): a replace that allows nothing new and moves no judged
    figure toward a limit reads no listing, so a listing outage cannot refuse it."""
    w.limits.fails = InstrumentLimitsUnavailable("no listing in time")
    narrowed = {**_ALT, "leverage": "2", "blocked_symbols": ["DOGEUSDT", "XRPUSDT"]}
    resp = send(w, REPLACE, body=narrowed)
    assert (resp.status_code, w.limits.calls, _row(w).version) == (200, 0, 3)


def test_a_replace_replays_its_200_before_if_match_is_read(w: Writes) -> None:
    """The 2026-10-22 17:25Z ruling (2): a lost answer's retry is the stored 200, whatever
    `If-Match` it carries now: stale (the first moved the profile on), or none. One record."""
    key, body = str(uuid.uuid4()), {**_ALT, "name": "Alt 2"}
    first = send(w, REPLACE, body=body, key=key)
    for tags in (None, list[str]()):  # stale now, or none
        again = send(w, REPLACE, body=body, key=key, tags=tags)
        replayed = (again.status_code, again.content, again.headers["etag"])
        assert replayed == (200, first.content, _ALT_3)
        assert again.headers["idempotency-replayed"] == "true"
    elsewhere = send(w, REPLACE, body=body, key=key, profile=DEFAULT, tags=[f'W/"{DEFAULT}:3"'])
    assert (elsewhere.status_code, answered(elsewhere, REPLACE)["code"]) == (409, _REUSE)  # R2-02
    assert (len(w.world.audit.records), _row(w).version) == (1, 3)


def test_ac5_a_concurrent_edit_loses_safely(w: Writes) -> None:
    """AC-5: two sessions edit version 2; the first lands, the second is 412: in the router, or at
    the store (handed the client's version) when a write lands between the read and the write."""
    mine, theirs = [send(w, REPLACE, body={**_ALT, "name": name}) for name in ("Mine", "Theirs")]
    assert (mine.status_code, theirs.status_code, answered(theirs, REPLACE)["code"]) == (
        200, 412, "version_conflict",
    )  # fmt: skip
    w.rows.race = _bumped
    raced = send(w, REPLACE, body={**_ALT, "name": "Theirs"}, tags=[_ALT_3])
    assert (raced.status_code, answered(raced, REPLACE)["code"]) == (412, "version_conflict")
    actions = [record["action"] for record in w.world.audit.records]
    assert (_row(w).values.name, _row(w).version, actions) == ("Mine", 3, ["profile.updated"])
    assert len(w.rows.hooks) == 2  # the raced write was handed its hook, never run


def test_a_name_another_profile_uses_is_409(w: Writes) -> None:
    """`ux_ap_name` in any letter case, on a create and on a replace, unrecorded; a profile keeps
    its own name in another case."""
    named = {**_ALT, "name": "risk 1%"}  # the default's, in another case
    taken = [create(w, {**_RISK, "name": "ALT"}), send(w, REPLACE, body=named)]
    details = [answered(taken[0])["detail"], answered(taken[1], REPLACE)["detail"]]
    assert ([r.status_code for r in taken], details) == ([409, 409], [_NAME_TAKEN] * 2)
    assert (w.world.audit.records, _new(w)) == ([], [])
    assert send(w, REPLACE, body={**_ALT, "name": "ALT"}).status_code == 200


def test_a_delete_is_204_and_records_the_profile_as_it_stood(w: Writes) -> None:
    """`profile.deleted` names the profile as it stood; the profile leaves every read; a lost
    answer's retry is the stored 204, still bodiless, before `If-Match` is read (none here); the
    key on another profile's delete is 409, the path being all its fingerprint tells apart."""
    key, stood = str(uuid.uuid4()), _row(w)
    done, again = send(w, DELETE, key=key), send(w, DELETE, key=key, tags=[])
    assert [(r.status_code, r.content) for r in (done, again)] == [(204, b"")] * 2
    assert again.headers["idempotency-replayed"] == "true" and "content-type" not in again.headers
    elsewhere = send(w, DELETE, key=key, profile=DEFAULT, tags=[f'W/"{DEFAULT}:3"'])
    assert (elsewhere.status_code, answered(elsewhere, DELETE)["code"]) == (409, _REUSE)  # R2-02
    (record,) = w.world.audit.records
    keys = ("action", "object_id", "severity", "before_state", "session_id")
    want = ["profile.deleted", str(ALT), "info", profile_state(stood), None]
    assert [record[k] for k in keys] == want
    assert str(record["request_id"]) == done.headers["x-correlation-id"]
    assert ([row.id for row in w.rows.rows[GRANTED]], w.invalidated) == ([DEFAULT], [GRANTED])


_RULES = [ArmedRule(uuid.UUID(int=100 + i), f"Rule {i:02}") for i in range(ARMED_SHOWN + 1)]
_ODD = [  # one name redacted, one cut to 80 characters, one redacted before it is cut
    ArmedRule(uuid.UUID(int=200), "secret: open-sesame"), ArmedRule(uuid.UUID(int=201), "L" * 99),
    ArmedRule(uuid.UUID(int=202), "x" * 70 + " secret: open-sesame"),
]  # fmt: skip
_NOT_DELETED = "The profile was not deleted."
_IS_DEFAULT = f"{_NOT_DELETED} It is the account's default profile: make another profile the"
_IS_DEFAULT += " default first (setAccountDefaultProfile)."


def _armed(*named: str, more: bool = False) -> str:
    listed = ", ".join(named) + (", and more" if more else "")
    return f"Rules scoped to the account are armed: {listed}. Disarm them first."


_TEN = [f'{rule.rule_id} "{rule.name}"' for rule in _RULES[:ARMED_SHOWN]]
_ODDS = _armed(
    f'{_ODD[0].rule_id} "secret: [redacted:key-name]"', f'{_ODD[1].rule_id} "{"L" * 80}"',
    f'{_ODD[2].rule_id} "{"x" * 70} secret: ["',
)  # fmt: skip


@pytest.mark.parametrize(
    ("profile", "armed", "fails", "race", "status", "detail"),
    [
        (DEFAULT, [], None, None, 409, _IS_DEFAULT),
        (ALT, _RULES[:ARMED_SHOWN], None, None, 409, f"{_NOT_DELETED} {_armed(*_TEN)}"),
        (ALT, _RULES, None, None, 409, f"{_NOT_DELETED} {_armed(*_TEN, more=True)}"),
        (DEFAULT, _ODD, None, None, 409, f"{_IS_DEFAULT} {_ODDS}"),
        (ALT, [], None, _made_default, 409, _IS_DEFAULT),
        (ALT, [], StorageTierUnavailable("down"), None, 503, "The profile store is unavailable."),
    ],
    ids=["default", "ten-rules", "eleven-rules", "both", "moved-since", "lookup-failed"],
)
def test_ac9_a_delete_is_refused_naming_each_blocker(
    w: Writes, profile: uuid.UUID, armed: list[ArmedRule], fails: Exception | None,
    race: Callable[[Row], Row] | None, status: int, detail: str,
) -> None:  # fmt: skip
    """AC-9, ruling B6: the default and the account's armed rules (at most `ARMED_SHOWN`, then "and
    more"; each name redacted, then cut to 80 characters) are named in one 409 before any write;
    the store's `default_profile` (a move landed since the read) is the same 409; a failed lookup
    is 503, never a delete while unsure. Nothing changes, nothing is recorded."""
    w.rules.armed[GRANTED], w.rules.fails, w.rows.race = armed, fails, race
    resp = send(w, DELETE, profile=profile, tags=[f'W/"{profile}:{_row(w, profile).version}"'])
    assert (resp.status_code, answered(resp, DELETE)["detail"]) == (status, detail)
    written = len(w.rows.hooks)  # the store is asked only past the router's blockers
    assert (w.world.audit.records, _new(w), written) == ([], [], race is not None)


def test_a_delete_needs_the_current_etag_and_checks_it_before_the_blockers(w: Writes) -> None:
    """The 07:10Z ruling: `If-Match` is required (428) and is one weak tag of this profile (412
    otherwise); the stored version is compared first, so a stale delete of the default with a
    rule armed, even past an int4 (D2-3 R1S-02), is 412, the rules unread and no write; stale at
    the store (a write landed since the read) is 412 too."""
    w.rules.armed[GRANTED] = _RULES[:1]
    forms = [[], ["*"], [f'W/"{ALT}:3"'], [f'W/"{DEFAULT}:2"'], [f'W/"{DEFAULT}:{2**31}"']]
    sent = [send(w, DELETE, profile=DEFAULT, tags=tags) for tags in forms]
    codes = [(resp.status_code, answered(resp, DELETE)["code"]) for resp in sent]
    assert codes == [(428, "precondition_required")] + [(412, "version_conflict")] * 4
    assert (w.rules.calls, w.world.audit.records, w.rows.hooks) == (0, [], [])
    w.rules.armed, w.rows.race = {}, _bumped
    raced = send(w, DELETE)
    assert (raced.status_code, answered(raced, DELETE)["code"]) == (412, "version_conflict")
    assert (w.world.audit.records, _new(w), len(w.rows.hooks)) == ([], [], 1)


@pytest.mark.parametrize("write", [REPLACE, DELETE], ids=["replace", "delete"])
def test_a_profile_of_another_account_is_404_on_its_writes(w: Writes, write: Write) -> None:
    """SR-E28-03 (IDOR): another account's profile, named under this account, answers as a
    missing profile: one 404, no write, nothing recorded."""
    theirs = w.rows.rows[FOREIGN][0]
    named = [(theirs.id, theirs.version), (uuid.uuid4(), 1)]
    sent = [send(w, write, profile=p, tags=[f'W/"{p}:{v}"']) for p, v in named]
    assert {(r.status_code, r.text) for r in sent} == {(404, sent[0].text)}
    detail = answered(sent[0], write)["detail"]
    assert (detail, w.world.audit.records, w.rows.hooks) == ("No such profile.", [], [])


def test_a_delete_whose_key_or_profile_id_is_no_uuid_is_an_unaudited_422(w: Writes) -> None:
    """#4495 R1C-03, R2-04: 22 declares the delete's `422`. A malformed `Idempotency-Key` answers
    the contract's example, and a `profileId` that is no UUID the same rule at its path; nothing
    is deleted or recorded."""
    declared = SPEC["paths"][ITEM]["delete"]["responses"]["422"]["content"]
    example = declared["application/problem+json"]["examples"]["notAKey"]["value"]
    keyed, pathed = send(w, DELETE, key="not-a-uuid"), send(w, DELETE, profile="Swing")
    assert answered(keyed, DELETE)["errors"] == example["errors"]
    # The path case's message is not pinned: the shared handler still quotes a character there
    # (R1S-01's twin, owed separately).
    named = [(e["field"], e["rule"]) for e in answered(pathed, DELETE)["errors"]]
    assert named == [("path.profileId", "uuid_parsing")]
    assert (w.world.audit.records, _new(w), w.rows.hooks) == ([], [], [])


#: ALT's caps above DEFAULT's: its notional and daily-loss amounts unbounded, more positions and
#: more orders at once (`PROFILE_CAPS` order).
_LOOSER = [
    "max_position_notional_usd", "max_daily_loss_usd", "max_open_positions",
    "max_concurrent_orders",
]  # fmt: skip
_PUT_422 = SPEC["paths"][BINDING]["put"]["responses"]["422"]["content"]["application/problem+json"]
_NOT_A_PROFILE = _PUT_422["examples"]["notAProfileId"]["value"]
_EXAMPLE = tuple(_NOT_A_PROFILE["errors"][0][key] for key in ("field", "rule"))  # 22's own entry
_PLANTED = json.dumps({"profile_id": str(ALT), "planted-member": 1}).encode()


def _bound(profile: uuid.UUID, version: int) -> dict[str, object]:
    """GRANTED's `AccountDefaultBinding`: a `demo` account's."""
    on = {"exchange_account_id": str(GRANTED), "environment": "demo"}
    return on | {"profile_id": str(profile), "version": version}


def _binding_read(w: Writes) -> Any:
    return w.world.client.get(BINDING.format(accountId=GRANTED), headers=rbac.bearer("owner"))


def test_a_move_is_200_at_the_next_binding_version_unbound_then_bound(w: Writes) -> None:
    """0d-3's move behind the edge: the binding one version on, its weak tag naming the version;
    `profile.unbound` for the demoted default, then `profile.bound`, written ahead in that order
    and naming the request (D2-2 R1C-02); both rows one version on; the account's effective
    profiles invalidated (SR-E28-15); the served `GET` reads the new default. A second move, at
    the `GET`'s tag, records the binding from version 2 to 3 (D2-6 R1C-04)."""
    resp, tag = send(w, MOVE), f'W/"{GRANTED}:default:2"'
    answer = (resp.status_code, answered(resp, MOVE), resp.headers["etag"])
    assert answer == (200, _bound(ALT, 2), tag)
    unbound, bound = w.world.audit.records
    before = {"default_profile_id": str(DEFAULT), "binding_version": 1}
    after = {"default_profile_id": str(ALT), "binding_version": 2}
    keys = ("action", "object_id", "before_state", "after_state", "severity")
    assert [unbound[k] for k in keys] == ["profile.unbound", str(DEFAULT), before, after, "info"]
    relaxed = after | {"relaxing": True, "looser_caps": _LOOSER}
    assert [bound[k] for k in keys] == ["profile.bound", str(ALT), before, relaxed, "warning"]
    assert {str(r["request_id"]) for r in (unbound, bound)} == {resp.headers["x-correlation-id"]}
    flags = [(row.id, row.version, row.values.is_default) for row in w.rows.rows[GRANTED]]
    assert (flags, w.invalidated) == ([(DEFAULT, 4, False), (ALT, 3, True)], [GRANTED])
    read = _binding_read(w)
    assert (read.status_code, read.json(), read.headers["etag"]) == (200, _bound(ALT, 2), tag)
    back = send(w, MOVE, body={"profile_id": str(DEFAULT)}, tags=[read.headers["etag"]])
    moved = [
        (r["action"], r["before_state"]["binding_version"], r["after_state"]["binding_version"])
        for r in w.world.audit.records[2:]
    ]
    assert (back.status_code, moved) == (200, [("profile.unbound", 2, 3), ("profile.bound", 2, 3)])


@pytest.mark.parametrize(
    ("trades", "looser"),
    [
        ((True, True), _LOOSER),
        ((True, False), []),  # ALT cannot trade: every cap of it counts as zero
        ((False, True), [cap.column for cap in PROFILE_CAPS]),  # DEFAULT cannot: trading turned on
    ],
    ids=["looser", "inert-target", "trading-turned-on"],
)
def test_a_relaxing_move_notifies_the_owner_and_the_zero_rule_holds(
    w: Writes, trades: tuple[bool, bool], looser: list[str]
) -> None:
    """SR-E28-01, the 17:25Z ruling (1): a move is judged on its caps alone, each cap of a profile
    that cannot trade counting as zero; a looser one labels `profile.bound` relaxing, a warning,
    and commits one notice naming both profiles with the move; any other move neither."""
    w.rows.rows[GRANTED] = tuple(
        dataclasses.replace(row, values=dataclasses.replace(row.values, trading_enabled=on))
        for row, on in zip(w.rows.rows[GRANTED], trades, strict=True)
    )
    resp = send(w, MOVE)
    bound = w.world.audit.records[-1]
    relaxing, request_id = bool(looser), uuid.UUID(resp.headers["x-correlation-id"])
    labels = [bound["after_state"][key] for key in ("relaxing", "looser_caps")]
    assert (resp.status_code, labels) == (200, [relaxing, looser])
    assert bound["severity"] == ("warning" if relaxing else "info")
    notice = port.RelaxedNotice(ALT, DEFAULT, (*looser,), False, request_id)
    assert w.rows.notices == ([notice] if relaxing else [])


def test_binding_the_current_default_changes_nothing_and_answers_its_tag(w: Writes) -> None:
    """B4: the default bound again commits nothing and writes no record (0d-3 returns before any
    hook), and answers the binding at its current version, with its current tag."""
    resp = send(w, MOVE, body={"profile_id": str(DEFAULT)})
    answer = (resp.status_code, answered(resp, MOVE), resp.headers["etag"])
    assert answer == (200, _bound(DEFAULT, 1), _BOUND_1)
    assert (w.world.audit.records, w.rows.notices, _new(w)) == ([], [], [])


def test_a_move_needs_the_bindings_current_tag(w: Writes) -> None:
    """The 07:10Z ruling, B1: 428 without `If-Match`; 412 for anything but one weak tag of this
    binding (`*`, a list, two headers, the strong form, `w/`, a profile's tag, another account's
    binding tag, version 0, past 19 digits), refused before the store is asked, and for a stale
    version, which the store finds under the account's lock before it reads the profile (0d-3):
    a stale tag naming a missing profile is 412, and after A to B to A the first tag is still
    stale. B1 comes before B2: a refused body is 428 with no tag and 412 with `*` (D2-6 R1C-03).
    A refusal changes nothing and records nothing."""
    g = f"{GRANTED}:default"
    forms = [
        "*", f'W/"{g}:1", W/"{g}:2"', f'"{g}:1"', f'w/"{g}:1"', f'W/"{ALT}:1"',
        f'W/"{FOREIGN}:default:1"', f'W/"{g}:0"', f'W/"{g}:{"9" * 20}"',
    ]  # fmt: skip
    sent = [send(w, MOVE, tags=tags) for tags in [[], *([form] for form in forms), [_BOUND_1] * 2]]
    unread = [send(w, MOVE, raw=b"[]", tags=tags) for tags in ([], ["*"])]  # never the body's 422
    stale = [send(w, MOVE, tags=[f'W/"{g}:{n}"']) for n in (2, 2**31)]
    stale.append(send(w, MOVE, body={"profile_id": str(uuid.uuid4())}, tags=[f'W/"{g}:2"']))
    (status, problem), *refused = [(r.status_code, answered(r, MOVE)) for r in sent + stale]
    assert (status, problem["code"]) == (428, "precondition_required")
    said = {(status, problem["code"], problem["detail"]) for status, problem in refused}
    assert said == {(412, "version_conflict", _STALE_BINDING)}
    assert [r.status_code for r in unread] == [428, 412]
    assert (len(w.rows.hooks), w.world.audit.records, _new(w)) == (len(stale), [], [])
    there, read = send(w, MOVE), _binding_read(w)
    back = send(w, MOVE, body={"profile_id": str(DEFAULT)}, tags=[read.headers["etag"]])
    again = send(w, MOVE, body={"profile_id": str(DEFAULT)})  # the first tag, `:1`
    assert [r.status_code for r in (there, back, again)] == [200, 200, 412]


def test_a_move_naming_another_accounts_or_a_missing_profile_is_404(w: Writes) -> None:
    """SR-E28-03 (IDOR): another account's profile, a missing one and one deleted since are a
    profile's one 404, read after the binding's version (0d-3); nothing moves or is recorded."""
    assert send(w, DELETE).status_code == 204  # ALT, deleted
    w.world.audit.records.clear()
    named = (w.rows.rows[FOREIGN][0].id, uuid.uuid4(), ALT)
    sent = [send(w, MOVE, body={"profile_id": str(profile)}) for profile in named]
    assert {(r.status_code, r.text) for r in sent} == {(404, sent[0].text)}
    detail = answered(sent[0], MOVE)["detail"]
    assert (detail, w.world.audit.records, w.rows.bindings[GRANTED]) == ("No such profile.", [], 1)


@pytest.mark.parametrize(
    ("raw", "entry"),
    [
        (b'{"profile_id": "Swing"}', _EXAMPLE),
        (b"{}", ("body.profile_id", "missing")),
        (b'{"profile_id": 5}', ("body.profile_id", "uuid_type")),
        (_PLANTED, ("body", "extra_forbidden")),
        (b"[]", ("body", "model_type")),
        (b"null", ("body", "model_type")),
        (b'{"profile_id": NaN}', ("body", "json_invalid")),
        (b"[" * 9 + b"]" * 9, ("body", "json_too_deep")),
    ],
    ids=["22s-example", "missing", "number", "another-member", "list", "null", "nan", "deep"],
)  # fmt: skip
def test_a_moves_refused_body_is_an_unaudited_422_naming_body_fields(
    w: Writes, raw: bytes, entry: tuple[str, str]
) -> None:
    """B2: the body names a profile and nothing else; a refusal is one entry at `body` or below
    it, as 22's example, counted as a field, never audited and echoing nothing sent (C-12.6)."""
    resp = send(w, MOVE, raw=raw)
    got = answered(resp, MOVE)
    assert (resp.status_code, got["detail"]) == (422, _NOT_A_PROFILE["detail"])
    assert [(e["field"], e["rule"]) for e in got["errors"]] == [entry]
    assert ("Swing" in resp.text, "planted" in resp.text) == (False, False)
    assert (w.world.audit.records, w.rows.hooks) == ([], [])


def test_a_move_over_1_kib_is_413_before_it_is_parsed(w: Writes) -> None:
    """22: a binding body over 1 KiB is `413 payload_too_large`, before it is decoded (it would
    nest too deep); one of exactly 1 KiB is read whole."""
    resp = send(w, MOVE, raw=b"[" * (MAX_BINDING_BODY_BYTES + 1))
    assert (resp.status_code, answered(resp, MOVE)["code"]) == (413, "payload_too_large")
    assert (w.world.audit.records, w.rows.hooks) == ([], [])
    padded = json.dumps(MOVE.body).encode().ljust(MAX_BINDING_BODY_BYTES)  # JSON, then blanks
    assert send(w, MOVE, raw=padded).status_code == 200


def test_a_lost_moves_answer_replays_before_if_match(
    w: Writes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 17:25Z ruling (2): a retry with the key and the body is the stored 200, read before
    `If-Match`, stale since the move or missing; one move, two records. The key with another
    body, or on another account's path, is 409 `idempotency_key_reuse` (D2-5's R2-02). Another
    Owner's same request is no replay: it runs, and its tag is stale (D2-6 R1C-02)."""
    key = str(uuid.uuid4())
    first = send(w, MOVE, key=key)
    for tags in (None, list[str]()):  # stale now, or none
        again = send(w, MOVE, key=key, tags=tags)
        replayed = (again.status_code, again.content, again.headers["etag"])
        assert replayed == (200, first.content, first.headers["etag"])
        assert again.headers["idempotency-replayed"] == "true"
    monkeypatch.setitem(ENV, EMPTIED, "demo")  # a second account of this environment
    reused = [send(w, MOVE, key=key, body={"profile_id": str(DEFAULT)})]
    reused.append(send(w, MOVE, key=key, at=EMPTIED))
    assert {(r.status_code, answered(r, MOVE)["code"]) for r in reused} == {(409, _REUSE)}
    other = PrincipalSnapshot(uuid.uuid4(), frozenset({"owner"}), frozenset(Permission))
    with monkeypatch.context() as patched:
        patched.setattr(w.world.resolver, "snapshot", lambda _actor: other)
        theirs = send(w, MOVE, key=key)
    assert (theirs.status_code, "idempotency-replayed" in theirs.headers) == (412, False)
    assert (len(w.world.audit.records), w.rows.bindings[GRANTED]) == (2, 2)


def _profile_members(node: object, at: str) -> set[str]:
    """Each member a JSON Schema declares, at any depth, whose name holds `profile`."""
    if isinstance(node, list):
        return set().union(*(_profile_members(item, at) for item in node))
    if not isinstance(node, dict):
        return set()
    found = {f"{at}.{key}" for key in node.get("properties", {}) if "profile" in key.lower()}
    return found.union(*(_profile_members(item, at) for item in node.values()))


def test_no_rule_names_a_profile_yet() -> None:
    """Ruling B6's tripwire (the 2026-10-22 17:25Z ruling (5)): a delete reads the armed rules
    outside its transaction, safe only while no rule can name a profile. The rule IR's schema (its
    models') names none; the action vocabulary declares one, `place_order`'s `profile`, which
    nothing resolves yet. A new one owes the delete guard #951's C-row."""
    named = _profile_members(to_json_schema(), "rule-ir")
    for action in ACTIONS:  # the vocabulary's action params
        named |= _profile_members(action.params_schema, action.type)
    assert named == {"place_order.profile"}, "a rule can name a profile: #951's C-row, ruling B6"


#: The order path's own profile id and its resolve (22 `PlaceOrderRequest.profile_id`); the size
#: step names the resolved profile's id for the comparator and resolves none (#913 S4-S).
_ORDER_PATH = {"oms/exits.py", "oms/ports.py", "oms/sizing.py", "oms/submit.py"}


def _named(node: ast.AST) -> str:
    for field in ("id", "attr", "arg", "name", "value"):  # a name, a binding, a string key
        if isinstance(value := getattr(node, field, None), str):
            return value
    return ""


def _resolves(node: ast.AST) -> bool:
    """One node that names a profile id, a profile getter, the profile cache or a read of it."""
    if isinstance(node, ast.ImportFrom):  # `from ...profile_cache import ...`
        return (node.module or "").endswith("profile_cache")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        # `cache.peek(...)`: the cache's read, on a receiver that names a cache or a profile
        receiver = ast.unparse(node.func.value).lower()
        if node.func.attr == "peek" and ("cache" in receiver or "profile" in receiver):
            return True
    name = _named(node)
    is_getter = name.startswith("get_") and name.endswith("_profile")
    return name in {"profile_id", "EffectiveProfiles"} or is_getter


def _resolvers(root: Path, *packages: str) -> set[str]:
    """Each module under `packages` of `root` naming a profile id (`profile_id`, as a name, an
    argument or a string key), a profile getter (`get_..._profile`, defined, bound or called), the
    `EffectiveProfiles` cache, an import from `profile_cache`, or a `peek` on a cache. A tripwire
    for these known spellings, not a proof: the vocabulary arm above is the primary guard."""
    found = set()
    for path in (path for package in packages for path in (root / package).rglob("*.py")):
        if any(map(_resolves, ast.walk(ast.parse(path.read_text(encoding="utf-8"))))):
            found.add(path.relative_to(root).as_posix())
    return found


def test_no_rule_or_order_module_gains_a_profile_resolver() -> None:
    """#4495 R1C-06: the tripwire's source-scan arm, which sees what the vocabulary cannot, a
    resolver: no module under `rules/` names a profile id or getter, and under `oms/` only the
    order path's own. A new one owes the delete guard #951's C-row (ruling B6)."""
    root = Path(candleviewer.__file__).parent
    assert _resolvers(root, "rules", "oms") == _ORDER_PATH, "#951's C-row, ruling B6"


@pytest.mark.parametrize(
    ("source", "seen"),
    [("def f(p):\n    return p['profile_id']\n", True), ("x = cache.get_rule_profile\n", True),
     ("async def get_live_profile():\n    pass\n", True), ("def f(profile_id): ...\n", True),
     ("def f(cache, a):\n    return cache.peek(a)\n", True),
     ("from candleviewer.accounts.profile_cache import Anything\n", True),
     ("ok = 'profile_ids', get_profiles, profile\n", False)],
    ids=["string-key", "bound-getter", "defined-getter", "argument", "peek", "import", "near-miss"],
)  # fmt: skip
def test_the_resolver_scan_sees_a_planted_name(tmp_path: Path, source: str, seen: bool) -> None:
    """The arm's self-test (R1C-06): a planted id or getter under `rules/` is seen; a near miss
    is not."""
    (tmp_path / "rules" / "engine").mkdir(parents=True)
    (tmp_path / "rules" / "engine" / "planted.py").write_text(source, encoding="utf-8")
    assert _resolvers(tmp_path, "rules", "oms") == ({"rules/engine/planted.py"} if seen else set())
