"""Contract, provider side (E27-S04 B2b, #898): `getAccountConsequences` as the app serves it.

The world is the RBAC pack's real `create_app()` (no network, C-13.5) with the consequence read
wired over fakes: the real `ConsequenceRead` and `ExposureRead`, a fake store scoped as Postgres
scopes it (an `OwnerScope` passes the live-owner gate only for the Owner, a `GrantScope` sees
only its accounts) and a fake key reader. Every answer is checked against the response 22
declares for its status (2020-12, format checker): the summary, `409 exposure_unknown` with its
`remedy` and no `consequences`, a failed read's `503`/`502` (`ret_code` only, SR-E27-08), the
store's `503`; RBAC for every role, one `404` for an absent and an other-environment account, a
refusal whose record cannot be written `503 audit_unavailable` (ruling 3), and no record of the
route's own on any answer but a refusal (CR-04).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

import candleviewer.app as appmod
from candleviewer.accounts.consequences import ConsequenceRead, StoreReadFailed
from candleviewer.accounts.errors import AccountNotFoundError, AccountScopeDeniedError
from candleviewer.accounts.exposure import ExposureRead, KeyExposure, KeyReadFailed
from candleviewer.accounts.models import (
    ApiKeyMetadata,
    AssignedUser,
    ExchangeAccount,
    ExchangeEnv,
)
from candleviewer.accounts.profile_repository import ArmedRule
from candleviewer.api.deny_by_default import served_operations
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from tests.contract._admin_support import SPEC, validate_example
from tests.contract.rbac.rbac_harness import (
    ABSENT,
    FOREIGN,
    GRANTED,
    World,
    bearer,
    build_world,
    user_id_of,
)
from tests.unit.accounts.test_exposure_decision import _position
from tests.unit.accounts.test_exposure_read import ACCOUNT, key

PATH = "/exchange-accounts/{accountId}/consequences"
OTHER_ENV = uuid.UUID("00000000-0000-4000-8000-0000000000e1")  # a live account on a demo server
KEY = uuid.UUID("00000000-0000-4000-8000-0000000000f1")
USERS = (
    AssignedUser(uuid.UUID(int=7), "ann", "trade"),
    AssignedUser(uuid.UUID(int=8), "bob", "read"),
)
RULES = (ArmedRule(uuid.UUID(int=9), "breakout"),)
PROTECTED = _position(stop_loss=Decimal("58000"), mark_price=Decimal("1E+4"))
TP_ONLY = _position(symbol="ETHUSDT", side="short", take_profit=Decimal("2000"))  # CR-03
FLAT = _position(symbol="SOLUSDT", side="flat", size=Decimal("0"))


class Ports:
    """The consequence read's ports. `answer` is the key's read; `gated` closes the owner gate
    for the Owner too; `down` fails the grantee read; `calls` counts every port call, `reads`
    the exchange reads (`read`) alone."""

    def __init__(self) -> None:
        self.rows = {i: ACCOUNT.model_copy(update={"id": i}) for i in (GRANTED, FOREIGN)} | {
            OTHER_ENV: ACCOUNT.model_copy(update={"id": OTHER_ENV, "env": ExchangeEnv.LIVE})
        }
        self.reset()

    def reset(self) -> None:
        self.answer: KeyExposure | KeyReadFailed = KeyExposure((PROTECTED, TP_ONLY, FLAT), 4)
        self.gated, self.down, self.keyless, self.calls, self.reads = False, False, False, 0, 0

    def _owner(self, scope: OwnerScope) -> None:
        self.calls += 1
        if self.gated or scope.user_id != user_id_of("owner"):
            raise AccountScopeDeniedError

    async def get_account(self, scope: Any, account_id: uuid.UUID) -> ExchangeAccount:
        self.calls += 1
        if isinstance(scope, GrantScope) and account_id not in scope.account_ids:
            raise AccountNotFoundError("account")
        if isinstance(scope, OwnerScope) and self.gated:
            raise AccountScopeDeniedError
        if account_id not in self.rows:
            raise AccountNotFoundError("account")
        return self.rows[account_id]

    async def list_keys(
        self, scope: OwnerScope, account_id: uuid.UUID
    ) -> tuple[ApiKeyMetadata, ...]:
        self._owner(scope)
        return () if self.keyless else (key(KEY, account=account_id),)

    async def list_grantees(
        self, scope: OwnerScope, account_id: uuid.UUID
    ) -> tuple[AssignedUser, ...]:
        self._owner(scope)
        if self.down:
            raise StoreReadFailed("a store read hit its bound")
        return USERS

    async def armed_on(self, account_id: uuid.UUID) -> tuple[ArmedRule, ...]:
        raise AssertionError("the summary lists through `covering`")

    async def covering(self, account_id: uuid.UUID, *, limit: int) -> tuple[ArmedRule, ...]:
        self.calls += 1
        return RULES

    async def running(self, account_id: uuid.UUID) -> int:
        return 1

    async def read(self, account: ExchangeAccount, key_id: uuid.UUID) -> KeyExposure:
        self.calls += 1
        self.reads += 1
        if isinstance(self.answer, KeyReadFailed):
            raise self.answer
        return self.answer


Served = tuple[World, Ports]


@pytest.fixture(scope="module")
def _served() -> Iterator[Served]:
    ports, mp = Ports(), pytest.MonkeyPatch()

    def wired(*_args: Any, env: str) -> ConsequenceRead:
        exposure = ExposureRead(ports, env=env)
        return ConsequenceRead(ports, exposure, ports, ports, env=env)

    try:
        mp.setattr(appmod, "wire_consequence_read", wired)
        yield build_world(mp), ports
    finally:
        mp.undo()


@pytest.fixture
def served(_served: Served) -> Iterator[Served]:
    world, ports = _served
    world.audit.records.clear()
    ports.reset()
    yield world, ports


def get(world: World, account: uuid.UUID, actor: str = "owner") -> Any:
    return world.client.get(PATH.format(accountId=account), headers=bearer(actor))


def answer(resp: Any) -> Any:
    """The body, once it validates against what the operation declares for its status."""
    status = resp.status_code
    declared = SPEC["paths"][PATH]["get"]["responses"][str(status)]
    own = "#/paths/" + PATH.replace("/", "~1") + f"/get/responses/{status}"
    pointer = declared.get("$ref", own)
    media = "application~1json" if status < 400 else "application~1problem+json"
    validate_example(f"{pointer.removeprefix('#')}/content/{media}/schema", resp.json())
    assert status == 200 or "consequences" not in resp.json()
    return resp.json()


def test_the_operation_is_served_on_its_literal_path(served: Served) -> None:
    assert ("GET", PATH) in served_operations(served[0].app)


def test_owner_reads_the_summary_open_positions_with_their_stop_state(served: Served) -> None:
    world, _ = served
    resp = get(world, GRANTED)
    body = answer(resp)
    assert resp.status_code == 200
    assert [(p["symbol"], p["native_stop_present"]) for p in body["open_positions"]] == [
        ("BTCUSDT", True), ("ETHUSDT", False),  # the take-profit alone is no stop (CR-03)
    ]  # fmt: skip
    first = body["open_positions"][0]
    assert (first["mark_price"], first["stop_loss"], first["take_profit"]) == (
        "10000",
        "58000",
        None,
    )
    assert first["exchange_account_id"] == str(GRANTED) and "trailing_stop" not in first
    assert (body["working_orders"], body["running_algos"]) == (4, 1)
    assert body["assigned_users"] == [
        {"user_id": str(u.user_id), "username": u.username, "level": u.level} for u in USERS
    ]
    assert body["armed_rules"] == [{"rule_id": str(RULES[0].rule_id), "name": "breakout"}]
    assert get(world, GRANTED).json() == body  # `Position.id` is derived: stable across reads
    assert world.audit.records == []  # no record of the route's own (CR-04)


@pytest.mark.parametrize("actor", ["manager_with_grant", "manager_without_grant", "viewer"])
@pytest.mark.parametrize("account", [GRANTED, FOREIGN, ABSENT])
def test_no_role_but_the_owner_reads_it_403_audited_naming_the_account(
    served: Served, actor: str, account: uuid.UUID
) -> None:
    world, ports = served
    resp = get(world, account, actor)
    assert (resp.status_code, answer(resp)["required_permissions"]) == (403, ["accounts:write"])
    (record,) = world.audit.records
    assert (record["action"], record["object_id"]) == ("rbac.denied", str(account))
    assert (ports.calls, ports.reads) == (0, 0)  # no store, no exchange call


def test_a_manager_foreign_and_absent_answers_are_byte_equal(served: Served) -> None:
    world, _ = served
    assert (
        get(world, FOREIGN, "manager_with_grant").content
        == get(world, ABSENT, "manager_with_grant").content
    )


def test_unauthenticated_is_401_and_reaches_nothing(served: Served) -> None:
    world, ports = served
    resp = get(world, GRANTED, "unauthenticated")
    assert (resp.status_code, answer(resp)["code"]) == (401, "unauthenticated")
    assert ports.calls == 0 and world.audit.records == []


def test_absent_and_other_environment_accounts_are_one_404(served: Served) -> None:
    world, _ = served
    absent, other = get(world, ABSENT), get(world, OTHER_ENV)
    assert (absent.status_code, answer(absent)["code"]) == (404, "not_found")
    assert absent.content == other.content  # byte for byte: no existence oracle (C-2.11)


def test_a_scoped_holder_of_accounts_write_reaches_only_its_granted_account(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    """vw2 decision 4: a non-Owner holding the permission (none does today, KV-E02) passes RBAC
    on its granted account only, and the store's owner gate refuses its owner-only reads."""
    world, ports = served
    grant = (AccountGrant(GRANTED, True, True, False),)
    holder = PrincipalSnapshot(
        user_id_of("manager_with_grant"), frozenset({"manager"}),
        frozenset({Permission.ACCOUNTS_WRITE}), grant,
    )  # fmt: skip
    monkeypatch.setattr(world.resolver, "snapshot", lambda _actor: holder)
    resp = get(world, GRANTED, "manager_with_grant")
    assert (resp.status_code, answer(resp)["code"]) == (403, "forbidden")
    (record,) = world.audit.records
    assert record["reason"] == "not_owner:accounts:write:granted_accounts"
    assert record["object_id"] == str(GRANTED)
    assert ports.reads == 0  # the owner gate refused before any exchange call
    foreign = get(world, FOREIGN, "manager_with_grant")
    assert (foreign.status_code, foreign.content) == (
        403,
        get(world, ABSENT, "manager_with_grant").content,
    )


def test_the_stores_owner_gate_refusing_the_owner_is_403_audited(served: Served) -> None:
    world, ports = served
    ports.gated = True
    resp = get(world, GRANTED)
    assert (resp.status_code, answer(resp)["code"]) == (403, "forbidden")
    (record,) = world.audit.records
    assert (record["reason"], record["object_id"]) == (
        "not_owner:accounts:write:granted_accounts", str(GRANTED),
    )  # fmt: skip


@pytest.mark.parametrize("error", [AuditError("down"), RuntimeError("writer not started")])
@pytest.mark.parametrize("gated", [False, True])
def test_a_refusal_whose_record_cannot_be_written_is_503_audit_unavailable(
    served: Served, monkeypatch: pytest.MonkeyPatch, error: Exception, gated: bool
) -> None:
    """Ruling 3 (C-2.9): RBAC's refusal (a Manager) and the store's owner gate (the Owner)."""
    world, ports = served
    ports.gated = gated

    async def refuse(action: str, **_kw: Any) -> None:
        raise error

    monkeypatch.setattr(world.audit, "emit", refuse)
    resp = get(world, GRANTED, "owner" if gated else "manager_with_grant")
    assert (resp.status_code, answer(resp)["code"]) == (503, "audit_unavailable")
    assert "Retry-After" in resp.headers


@pytest.mark.parametrize(
    ("failure", "remedy"),
    [("auth_error", "leave_positions"), ("ip_not_allowed", "fix_key"),
     ("permission_denied", "fix_key"), (None, "leave_positions")],
)  # fmt: skip
def test_an_exposure_that_cannot_be_read_is_409_with_its_remedy(
    served: Served, failure: str | None, remedy: str
) -> None:
    world, ports = served
    if failure is None:
        ports.keyless = True  # no signable key: dead, never "no exposure"
    else:
        ports.answer = KeyReadFailed(failure)
    resp = get(world, GRANTED)
    body = answer(resp)
    assert (resp.status_code, body["code"], body["remedy"]) == (409, "exposure_unknown", remedy)
    assert world.audit.records == []


@pytest.mark.parametrize("failure", ["timeout", "transport_error", "vault_refused"])
def test_a_failed_read_without_an_answer_is_503_exchange_unavailable(
    served: Served, failure: str
) -> None:
    world, ports = served
    ports.answer = KeyReadFailed(failure)
    resp = get(world, GRANTED)
    body = answer(resp)
    assert (resp.status_code, body["code"], "remedy" in body) == (
        503,
        "exchange_unavailable",
        False,
    )
    assert "Retry-After" in resp.headers and "exchange" not in body


@pytest.mark.parametrize(("code", "member"), [(10006, {"ret_code": 10006}), (None, None)])
def test_a_failed_read_the_exchange_answered_is_502_with_its_code_only(
    served: Served, code: int | None, member: dict[str, int] | None
) -> None:
    world, ports = served
    ports.answer = KeyReadFailed("rate_limited" if code else "exchange_unknown", code)
    resp = get(world, GRANTED)
    body = answer(resp)
    assert (resp.status_code, body["code"], body.get("exchange")) == (502, "exchange_error", member)
    assert world.audit.records == []


def test_a_store_read_that_fails_is_503_store_unavailable(served: Served) -> None:
    world, ports = served
    ports.down = True
    resp = get(world, GRANTED)
    assert (resp.status_code, answer(resp)["code"]) == (503, "store_unavailable")
    assert "Retry-After" in resp.headers and world.audit.records == []


def test_a_store_read_that_fails_beats_an_unknown_exposure(served: Served) -> None:
    """Q2: with the exposure unknown (a dead key) and the grantee read down, the answer is the
    store's 503, never a 409 whose `remedy` rests on a partial picture."""
    world, ports = served
    ports.answer, ports.down = KeyReadFailed("auth_error"), True
    resp = get(world, GRANTED)
    assert (resp.status_code, answer(resp)["code"]) == (503, "store_unavailable")
    assert "remedy" not in resp.json() and world.audit.records == []
