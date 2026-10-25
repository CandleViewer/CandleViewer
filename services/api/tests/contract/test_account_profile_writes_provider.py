"""Contract, provider side (#906 slice D2-4): `createAccountProfile` behind the profile write edge,
in `_profile_writes_world`'s world until D2-m mounts it. Every answer validates against what its
operation declares. The shared tests run over `_WRITES`, which D2-5 and D2-6 extend.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.accounts.models import ExchangeEnv
from candleviewer.accounts.profile_validator import InstrumentLimitsUnavailable
from candleviewer.accounts.profiles import profile_from_row, to_us
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.idempotency import IDEMPOTENCY_TTL_S
from candleviewer.api.profile_audit import profile_state
from candleviewer.api.profile_body import MAX_PROFILE_BODY_BYTES
from candleviewer.api.profile_projection import profile_document
from candleviewer.api.profile_writes import make_profile_writes_router
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories import account_profiles as port
from candleviewer.storage.repositories.accounts import AccountsStoreError, OwnerScope
from tests.contract._admin_support import SPEC, validate_example
from tests.contract._profile_writes_world import WRITTEN, Writes, build
from tests.contract.rbac import rbac_harness as rbac
from tests.contract.test_account_profile_reads_provider import EMPTIED, ENV

LIST = "/exchange-accounts/{accountId}/profiles"
#: 22's `riskBased` example: trading-enabled, every cap bounded, BTC and ETH allowed.
_EXAMPLES = SPEC["paths"][LIST]["post"]["requestBody"]["content"]["application/json"]["examples"]
_RISK: dict[str, Any] = _EXAMPLES["riskBased"]["value"]
_NO_OFF = "Every order carries a native stop-loss, so it cannot be turned off."
_NATIVE = {"field": "require_native_stop", "rule": "native_stop_mandatory", "message": _NO_OFF}
_NAME_TAKEN = "A profile of this account already uses that name, in any letter case."
_SAVE_REFUSED, _CREATED, _REUSE = "profile.save_refused", "profile.created", "idempotency_key_reuse"
_UNAUDITED, _DOWN = "audit_unavailable", "store_unavailable"
GRANTED, FOREIGN = rbac.GRANTED, rbac.FOREIGN  # FOREIGN is a `live` account, EMPTIED `testnet`


@dataclass(frozen=True)
class Write:
    """A profile write: its operation, method, path template and a body it stores."""

    name: str
    method: str
    template: str
    body: dict[str, Any]


_WRITES = [Write("createAccountProfile", "POST", LIST, _RISK)]
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
) -> Any:  # fmt: skip
    """`write` by `actor`'s session on account `at`: `raw`, else `body` (the write's) as JSON."""
    sent = {**(headers or rbac.bearer(actor)), "content-type": "application/json"}
    sent |= {} if key is None else {"idempotency-key": key}
    content = raw or json.dumps(write.body if body is None else body).encode()
    path = write.template.format(accountId=at)
    return w.world.client.request(write.method, path, content=content, headers=sent)


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
    """The rows the writes stored, on any account."""
    return [row for rows in w.rows.rows.values() for row in rows if row.created_at == WRITTEN]


def _names(record: dict[str, Any], resp: Any, actor: str = "owner") -> None:
    """A refusal's record names its actor and address, the account, the session (#4174) and the
    request (D2-4 R1C-03)."""
    ids = [rbac.user_id_of(actor), rbac.session_id_of(actor), str(GRANTED), "127.0.0.1"]
    assert [record[k] for k in ("actor_user_id", "session_id", "object_id", "actor_ip")] == ids
    assert record["object_kind"] == "exchange_account"
    assert str(record["request_id"]) == resp.headers["x-correlation-id"]  # D2-2 R1C-02


async def _never(*_args: Any, **_kwargs: Any) -> None:
    """A writer that never answers: only a bound ends it."""
    await asyncio.Event().wait()


def _refused_save(w: Writes, resp: Any, reason: str, entries: list[dict[str, str]]) -> None:
    """A 422 recorded as one `profile.save_refused` of `reason`, holding `entries`; no row."""
    (record,) = w.world.audit.records
    _names(record, resp)
    assert (resp.status_code, record["action"], record["reason"]) == (422, _SAVE_REFUSED, reason)
    after = {"exchange_account_id": str(GRANTED), "count": len(entries), "errors": entries}
    assert (record["after_state"], _new(w)) == (after, [])


def test_ac1_a_risk_based_create_is_201_version_1_with_its_etag_and_record(w: Writes) -> None:
    """AC-1; `profile.created` from the hook the store got (D2-2 R1S-02); every store call the
    Owner's (SR-051); the account's effective profiles invalidated (SR-E28-15)."""
    resp = create(w, _RISK)
    (row,) = _new(w)
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


@pytest.mark.parametrize("path", ["schema", "combined", "store"])
def test_native_sl_false_refused_by_every_path(w: Writes, path: str) -> None:
    """SR-E28-08, AC-01: refused and audited alone, among 30 other failures (B1's entry follows the
    model's 20: #4087 R3-02's combined case), and as the store's `ap_native_sl` CHECK."""
    body = {**_RISK, "require_native_stop": False}
    if path == "combined":
        body |= {"colour": "red", "allowed_symbols": ["x"] * 30}
    if path == "store":
        body, w.rows.fails["profiles"] = _RISK, port.AccountProfileStoreRuleError("ap_native_sl")
    resp = create(w, body)
    errors = answered(resp)["errors"]
    assert (len(errors), errors[-1]) == ({"combined": 21}.get(path, 1), _NATIVE)
    _refused_save(w, resp, "native_stop_mandatory", [_NATIVE])


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


def test_a_stale_catalogue_is_503_retry_after_2(w: Writes) -> None:
    """PF-D04: never audited or stored. Its retry, a first submission, is D2-5's."""
    w.limits.fails = InstrumentLimitsUnavailable("no listing in time")
    resp = create(w, _RISK, key=str(uuid.uuid4()))
    got = answered(resp)
    assert (got["code"], got["retry_after_seconds"], resp.headers["retry-after"]) == (
        "instrument_cache_unavailable", 2, "2",
    )  # fmt: skip
    assert (resp.status_code, w.world.audit.records, _new(w)) == (503, [], [])


def test_a_writes_answer_carries_the_second_passes_warnings(w: Writes) -> None:
    """The patterns admit every listed, trading perpetual (BTC, ETH, SOL), as no read can see."""
    resp = create(w, {**_RISK, "allowed_symbols": ["*CUSDT", "*HUSDT", "*LUSDT"]})
    message = "Allows every listed symbol — consider restricting."
    warning = {"code": "all_symbols", "message": message, "field": "allowed_symbols"}
    assert (resp.status_code, answered(resp)["warnings"]) == (201, [warning])


def test_a_create_replays_its_201_and_refuses_the_key_for_another_body(
    w: Writes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SR-E28-17; the account is read first, so a replay on one deleted since is 404 (#4157
    R1S-02). Another Owner's same request (not a replay) is D2-5's."""
    key = str(uuid.uuid4())
    first, again = create(w, _RISK, key=key), create(w, _RISK, key=key)
    assert (again.status_code, again.content) == (201, first.content)
    replayed = (again.headers["etag"], again.headers["idempotency-replayed"])
    assert replayed == (first.headers["etag"], "true") and len(w.world.audit.records) == 1
    monkeypatch.setitem(ENV, EMPTIED, "demo")  # a second account of this environment
    reused = [create(w, {**_RISK, "name": "Bob"}, key=key), create(w, _RISK, key=key, at=EMPTIED)]
    assert {(r.status_code, answered(r)["code"]) for r in reused} == {(409, _REUSE)}
    malformed = answered(create(w, _RISK, key="not-a-uuid"))["errors"]
    assert [(e["field"], e["rule"]) for e in malformed] == [("Idempotency-Key", "uuid_parsing")]
    monkeypatch.delitem(w.rows.rows, GRANTED)
    assert answered(create(w, _RISK, key=key))["code"] == "not_found"
    assert (len(w.rows.hooks), [r["action"] for r in w.world.audit.records]) == (1, [_CREATED])


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
    """C-2.11: missing or deleted (both read as none), `live`, `testnet`, or gone by the write."""
    sent = [send(w, write, at=account) for account in (uuid.uuid4(), FOREIGN, EMPTIED)]
    w.rows.gone.add(GRANTED)
    sent.append(send(w, write))
    assert {(r.status_code, r.text) for r in sent} == {(404, sent[0].text)}
    assert answered(sent[0], write)["detail"] == "No such exchange account."
    assert (w.world.audit.records, _new(w)) == ([], [])


@_EACH
def test_a_body_over_its_cap_is_413_before_it_is_parsed(w: Writes, write: Write) -> None:
    """22: over 64 KiB is `413 payload_too_large`, before it is decoded (it would nest too deep)."""
    resp = send(w, write, raw=b"[" * (MAX_PROFILE_BODY_BYTES + 1))
    assert (resp.status_code, answered(resp, write)["code"]) == (413, "payload_too_large")
    assert (w.world.audit.records, _new(w), w.limits.calls) == ([], [], 0)


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
    actions = {r["action"] for r in w.world.audit.records} & {"rbac.denied", "profile.created"}
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
    body = {**write.body, "require_native_stop": False} if case == "save" else None
    resp = send(w, write, "manager_with_grant" if case == "rbac" else "owner", body=body)
    got = answered(resp, write)
    assert (resp.status_code, got["code"], resp.headers["retry-after"]) == (503, _UNAUDITED, "5")
    assert (len(w.rows.hooks), _new(w)) == (case in {"hook", "timeout"}, [])


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
    created = ["profile.created"] if where == "commit" else []
    assert [record["action"] for record in w.world.audit.records] == created


def test_without_a_store_the_writes_are_503_after_rbac(w: Writes) -> None:
    """The fake backend: an Owner's 503 comes after `enforce`; no resolver wired is 501."""

    def client(resolver: Any) -> TestClient:
        app = FastAPI()
        app.include_router(make_profile_writes_router(None, w.world.audit, resolver))
        return TestClient(app)

    for write in _WRITES:
        path, storeless = write.template.format(accountId=GRANTED), client(w.world.resolver)
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
