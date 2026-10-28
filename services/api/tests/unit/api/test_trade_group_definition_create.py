"""E28-T05 S2c (#909): `createTradeGroupDefinition` over the reads' store, written as Postgres
writes it, with the E28 seed's accounts (A, B and C demo, B's key failing; L live; D deleted), their
bound profiles, the recorded listing (C-13.5), the `risk_caps` step-up and the flag; and the gate,
the write-ahead hook's membership change and the challenge's restatement."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.accounts.errors import AccountNotFoundError
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.profile_validator import InstrumentLimitsUnavailable
from candleviewer.accounts.trade_group_definitions import NO_COMMON_SYMBOL
from candleviewer.api import trade_group_definition_writes as writes
from candleviewer.api.step_up_challenge import ChallengeText, definition_write_text
from candleviewer.api.trade_group_definitions import make_trade_group_definitions_router
from candleviewer.api.trade_groups_gate import TradeGroupsGate
from candleviewer.audit.actions import validate_action
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.domain.primitives import Environment
from candleviewer.storage.errors import StorageQueryFailed, WriteAheadTimeout
from candleviewer.storage.repositories import trade_group_definitions as port
from candleviewer.storage.repositories.trade_groups import ACCOUNT_NOT_LIVE
from tests.unit.accounts._override_world import profile
from tests.unit.accounts.test_trade_group_definitions import LISTED
from tests.unit.api import test_trade_group_definition_reads as reads

A, B, C, L, D, PAIR = reads.A, reads.B, reads.C, UUID(int=11), UUID(int=12), reads.PAIR
OWNER, NEW = reads.OWNER_ID, UUID("e28f0000-0000-4000-8000-0000000000c3")
LABELS = {A: "E28-A", B: "E28-B", C: "E28-C", L: "E28-LIVE-MAIN"}  # D: soft-deleted
PATH, MIXED = "/trade-group-definitions", "A trade group cannot mix Demo and Live accounts."


def caller(role: str, user: UUID = OWNER) -> PrincipalSnapshot:
    """`accounts:write` is the Owner's alone (SR-E28-31); the others hold A, B and C."""
    owner, read = role == "owner", Permission.ACCOUNTS_READ
    held = frozenset({read, Permission.ACCOUNTS_WRITE} if owner else {read})
    grants = () if owner else tuple(AccountGrant(a, True, True, False) for a in (A, B, C))
    return PrincipalSnapshot(user if owner else reads.MANAGER_ID, frozenset({role}), held, grants)


def denied() -> float:
    """`authz_denied_total` for `accounts:write`, process-wide: admission counts a refused role and
    the stores' live-owner gate a lapsed Owner (SR-125)."""
    return REGISTRY.get_sample_value("authz_denied_total", {"permission": "accounts:write"}) or 0.0


def state_of(*members: tuple[UUID, bool]) -> dict[str, Any]:
    """Core3 as a record holds it: the name, the environment and each member's `(id, enabled)`."""
    named = [{"exchange_account_id": str(a), "enabled": on} for a, on in members]
    return {"name": "Core3", "environment": "demo", "members": named}


def payload(*members: UUID, name: str = "Core3", env: str = "demo") -> dict[str, Any]:
    named = [{"exchange_account_id": str(m)} for m in members or (A, B, C)]
    return {"name": name, "environment": env, "members": named}


class World(reads.Store):
    """Both routers over the reads' store (Pair), writing as Postgres does, and every port the
    create reads; `faults` fails `audit` or `listing`."""

    environment: Environment = "demo"  # the listing's: this process's (C-2.11)

    def __init__(self, unwired: str = "") -> None:  # "writes" or "resolver"
        super().__init__(reads.record(PAIR, "Pair", A, C))
        self.flag, self.elevated, self.live = True, True, {A, B, C, L}
        self.principal: PrincipalSnapshot | None = caller("owner")
        self.symbols = {A: ("BTCUSDT", "ETHUSDT"), B: ("BTCUSDT",), C: ("BTCUSDT", "SOLUSDT")}
        self.audited, self.texts = list[dict[str, Any]](), list[str]()
        self.faults: dict[str, Exception] = {}
        held = writes.DefinitionWrites(cast(Any, self), self, self, cast(Any, self), self)
        app, gate = FastAPI(), TradeGroupsGate(lambda: self.flag)
        app.include_router(make_trade_group_definitions_router(self, self, self, self))
        app.include_router(writes.make_trade_group_definition_writes_router(
            None if unwired == "writes" else held, gate, self,
            None if unwired == "resolver" else self, elevation=self.elevate, new_id=lambda: NEW,
        ))  # fmt: skip
        self.client = TestClient(app, raise_server_exceptions=False)

    async def create(
        self, scope: Any, new: port.NewDefinition, *, write_ahead: port.DefinitionWriteAhead
    ) -> port.DefinitionRecord:
        if new.name.lower() in {r.definition.name.lower() for r in self._seen(scope)}:
            raise port.DefinitionConflictError("ux_tgd_name")
        if not {m.exchange_account_id for m in new.members} <= self.live:
            raise port.DefinitionRuleError(ACCOUNT_NOT_LIVE)
        row = port.DefinitionRow(new.id, new.name, new.env, None, None, reads.NOW, reads.NOW)
        made = port.DefinitionRecord(row, tuple(
            port.MemberRow(m.exchange_account_id, m.enabled, new.env, True) for m in new.members
        ))  # fmt: skip
        await write_ahead(None, made)
        self.records[new.id] = made
        return made

    def reason(self, account_id: UUID, environment: Any, *, account_enabled: bool) -> Any:
        return "key_invalid" if account_id == B else None  # B's key fails its self-check

    async def emit(self, action: str, **kwargs: Any) -> None:
        if (fault := self.faults.get("audit")) is not None:
            raise fault
        self.audited.append({"action": action, "committed": NEW in self.records, **kwargs})

    def resolve(self, _request: Any) -> PrincipalSnapshot | None:
        return self.principal

    async def get_account(self, scope: Any, account_id: UUID) -> ExchangeAccount:
        if account_id not in LABELS:  # missing or soft-deleted: M13's one answer
            raise AccountNotFoundError("account")
        row: dict[str, Any] = {"id": account_id, "env": "live" if account_id == L else "demo"}
        row |= {"exchange_uid": "1001", "label": LABELS[account_id], "created_at": reads.NOW}
        return ExchangeAccount.model_validate(row | {"kind": "main", "updated_at": reads.NOW})

    async def get_effective_profile(self, account_id: UUID, profile_id: UUID | None = None) -> Any:
        if account_id not in self.symbols:  # no bound profile
            raise AccountNotFoundError("profile")
        allowed = list(self.symbols[account_id])
        return profile(account_id=str(account_id), all_symbols=False, allowed_symbols=allowed)

    async def listed(self, *, max_age_s: float, deadline_s: float) -> Mapping[str, Any]:
        if (fault := self.faults.get("listing")) is not None:
            raise fault
        return {instrument.symbol: instrument for instrument in LISTED}

    async def elevate(self, _request: Any, text: ChallengeText) -> JSONResponse | None:
        self.texts.append(text.action_summary)
        return None if self.elevated else JSONResponse({"code": "step_up_required"}, 403)

    def post(self, sent: dict[str, Any] | None = None) -> Any:
        return self.client.post(PATH, json=payload() if sent is None else sent)


@pytest.fixture
def world() -> World:
    return World()


def test_the_owner_creates_core3_and_its_record_is_written_ahead(world: World) -> None:
    """AC 1: read back with three members, 2 of 3 ready, the read's `ETag`; `.created` written
    before the commit with the membership it adds (SR-E28-20, C-2.9)."""
    got, read = world.post(), world.client.get(f"{PATH}/{NEW}")
    assert (got.status_code, got.json(), got.headers["etag"]) == (
        201, read.json(), read.headers["etag"]
    )  # fmt: skip
    assert got.json()["readiness"]["ready"] == 2 and len(read.json()["definition"]["members"]) == 3
    assert [i["id"] for i in world.client.get(PATH).json()["items"]] == [str(NEW), str(PAIR)]
    members = [{"exchange_account_id": str(a), "enabled": True} for a in (A, B, C)]
    added = {"added": [str(A), str(B), str(C)], "removed": [], "toggled": []}
    assert world.audited == [{
        "action": "trade_group_definition.created", "committed": False, "actor_label": str(OWNER),
        "actor_user_id": OWNER, "actor_ip": "testclient", "session_id": None, "env": "demo",
        "object_kind": "trade_group_definition", "object_id": str(NEW), "request_id": None,
        "outcome": "success", "severity": "info", "before_state": None, "after_state": {
            "name": "Core3", "environment": "demo", "members": members, "membership_change": added,
        },
    }]  # fmt: skip


def test_mixed_environments_are_refused_naming_the_accounts(world: World) -> None:
    """AC 2 (SR-E28-16, C-2.11): an entry per member outside, the accounts named by label."""
    got = world.post(payload(A, L))
    entry = {"field": "members[1].exchange_account_id", "rule": "environment_mismatch"}
    entry["message"] = "This account is not in the definition's environment."
    detail = f"{MIXED} 'E28-A' (demo), 'E28-LIVE-MAIN' (live)."
    assert (got.status_code, got.json()["detail"], got.json()["errors"]) == (400, detail, [entry])
    assert NEW not in world.records and world.texts == [] and world.audited == []


def test_no_common_symbol_is_refused_with_scr_062s_sentence(world: World) -> None:
    """AC 3: A allows only BTCUSDT and B only ETHUSDT; one with no bound profile allows none."""
    world.symbols |= {A: ("BTCUSDT",), B: ("ETHUSDT",)}
    entry = {"field": "members", "rule": "no_common_symbol", "message": NO_COMMON_SYMBOL}
    got = world.post(payload(A, B))
    assert (got.status_code, got.json()["detail"], got.json()["errors"]) == (
        400, NO_COMMON_SYMBOL, [entry]
    )  # fmt: skip
    del world.symbols[C]
    assert world.post(payload(A, C)).json()["errors"] == [entry] and world.texts == []


def test_a_repeated_member_is_422(world: World) -> None:
    got, field = world.post(payload(A, B, A)), "members[2].exchange_account_id"
    entry = {"field": field, "rule": "duplicate_account", "message": "This account is a member."}
    assert (got.status_code, got.json()["errors"]) == (422, [entry])


def test_an_unknown_member_is_refused_as_an_ungranted_one(world: World) -> None:
    """SR-E29-13: missing, deleted, deleted since (`ACCOUNT_NOT_LIVE`) or of another process
    (C-2.11): one 403, before any environment is judged, never the profile writes' 404."""
    sent = [payload(A, reads.MISSING), payload(L, D), payload(D, A), payload(L, env="live")]
    answers, texts = [world.post(body) for body in sent], list(world.texts)
    world.live = {A, B}
    answers.append(world.post(payload(A, C)))
    assert {(r.status_code, r.text) for r in answers} == {(403, answers[0].text)} and texts == []
    assert answers[0].json()["code"] == "account_scope_denied"
    assert str(reads.MISSING) not in answers[0].text and world.audited == []


def test_a_taken_name_is_409_in_any_letter_case(world: World) -> None:
    got = world.post(payload(A, C, name="pAIR"))
    assert (got.status_code, got.json()["code"], world.audited) == (409, "conflict", [])


def test_without_a_risk_caps_step_up_nothing_is_written(world: World) -> None:
    """PF-S02: the challenge restates the environment and the member count, never the name."""
    world.elevated = False
    assert world.post().json()["code"] == "step_up_required" and world.audited == []
    assert world.texts == ["Create a demo trade-group definition of 3 members"]


def test_a_refused_body_is_never_challenged(world: World) -> None:
    """Nor one the flag refuses: an Owner's `403 trading_disabled`, with no `reason`."""
    world.symbols[B] = ("ETHUSDT",)  # B and C share none
    sent = [{"name": "Core3"}, payload(A, A), payload(A, reads.MISSING), payload(A, L)]
    answers = [world.post(body) for body in [*sent, payload(B, C)]]
    world.flag = False
    answers.append(world.post())
    assert [r.status_code for r in answers] == [422, 422, 403, 400, 400, 403] and world.texts == []
    last = answers[-1].json()
    assert (last["code"], "reason" in last) == ("trading_disabled", False)


@pytest.mark.parametrize("role", ["manager", "viewer"])
def test_a_manager_and_a_viewer_get_403(world: World, role: str) -> None:
    """SR-E28-31: audited, whatever the flag says (RBAC first); unaudited, 503."""
    world.principal, before = caller(role), denied()
    answers = [world.post()]
    world.flag = False
    answers.append(world.post(payload(A, A)))
    assert [(r.status_code, r.json()["code"]) for r in answers] == [(403, "forbidden")] * 2
    assert [r["action"] for r in world.audited] == ["rbac.denied"] * 2 and world.texts == []
    world.faults["audit"] = AuditUnavailable("down")
    assert world.post().json()["code"] == "audit_unavailable" and world.records.keys() == {PAIR}
    assert denied() - before == 3  # counted before the record is written, so the unwritten one too


@pytest.mark.parametrize("fault", [AuditUnavailable("down"), RuntimeError("off"), TimeoutError()])
def test_an_unwritable_record_writes_no_definition(world: World, fault: Exception) -> None:
    """C-2.9: the record goes first; unwritten, or the hook past the store's bound, nothing."""
    world.faults["audit"] = fault
    unwritten = world.post()
    world.faults, world.fails = {}, WriteAheadTimeout("past its bound")
    statuses = [(r.status_code, r.json()["code"]) for r in (unwritten, world.post())]
    assert statuses == [(503, "audit_unavailable")] * 2 and world.audited == []
    assert NEW not in world.records


def test_faults_are_refused_or_503_logged_by_class_and_never_the_name(world: World) -> None:
    """The live-owner gate audited (unwritten, 503); logs by class, SQLSTATE or rule (C-12.6)."""
    faults: list[tuple[Exception | None, dict[str, Exception]]] = [
        (port.DefinitionScopeDeniedError(), {}),
        (port.DefinitionScopeDeniedError(), {"audit": RuntimeError("not started")}),
        (StorageQueryFailed("57014"), {}), (port.DefinitionRuleError("trg_tgdm_env"), {}),
        (None, {"listing": InstrumentLimitsUnavailable("down")}), (TypeError(), {}),
    ]  # fmt: skip
    before = denied()
    with capture_logs() as logs:
        answers = []
        for world.fails, world.faults in faults:
            answers.append(world.post())
    assert denied() - before == 2  # the live-owner gate counts its two refusals, audited or not
    assert [(r.status_code, r.json()["code"] if r.status_code != 500 else "") for r in answers] == [
        (403, "forbidden"), (503, "audit_unavailable"), (503, "store_unavailable"),
        (400, "validation_failed"), (503, "instrument_cache_unavailable"), (500, ""),
    ]  # fmt: skip
    assert [r["reason"] for r in world.audited] == ["not_owner:accounts:write:granted_accounts"]
    assert [(e["event"], e.get("sqlstate"), e.get("error"), e.get("rule")) for e in logs] == [
        ("trade_group_definition_write_unavailable", "57014", "StorageQueryFailed", None),
        ("trade_group_definition_refused_by_constraint", None, None, "environment_mismatch"),
    ]  # fmt: skip
    assert "Core3" not in repr(logs) and NEW not in world.records


def test_no_resolver_is_501_and_a_body_past_its_cap_422(world: World) -> None:
    big = world.client.post(PATH, content=b" " * (writes.MAX_DEFINITION_BODY_BYTES + 1))
    assert (big.status_code, big.json()["errors"][0]["rule"]) == (422, "body_too_large")
    assert World("resolver").post().status_code == 501


async def test_the_hook_names_created_updated_and_deleted_with_their_states(world: World) -> None:
    """S2d's replace and delete hand the store this hook. Its one f-string names the three actions,
    which the literal-action guard cannot see: each is registered, and carries the states as the
    store read them and the change, a delete's `after` the change alone."""
    was = reads.record(reads.CORE3, "Core3", A, B, C, paused=C)
    now = reads.record(reads.CORE3, "Core3", A, C, L)
    hook = writes.audit_definition_write(world, OWNER, None, None)
    for pair in ((None, now), (was, now), (was, None)):
        await hook(*pair)
    old = state_of((A, True), (B, True), (C, False))
    new = state_of((A, True), (C, True), (L, True))
    created = {"added": [str(A), str(C), str(L)], "removed": [], "toggled": []}
    updated = {"added": [str(L)], "removed": [str(B)], "toggled": [str(C)]}
    deleted = {"added": [], "removed": [str(A), str(B), str(C)], "toggled": []}
    rows = world.audited
    assert [(validate_action(r["action"]), r["before_state"], r["after_state"]) for r in rows] == [
        ("trade_group_definition.created", None, new | {"membership_change": created}),
        ("trade_group_definition.updated", old, new | {"membership_change": updated}),
        ("trade_group_definition.deleted", old, {"membership_change": deleted}),
    ]
    who = (OWNER, "demo", "trade_group_definition", str(reads.CORE3), "success")
    keys = ("actor_user_id", "env", "object_kind", "object_id", "outcome")
    assert {tuple(r[k] for k in keys) for r in rows} == {who}


def test_the_membership_change_names_members_added_removed_and_toggled() -> None:
    """S2d's replace and delete hand the store the same hook, before and after as it read them."""
    before = reads.record(reads.CORE3, "Core3", A, B, C, paused=C)
    after = reads.record(reads.CORE3, "Core3", A, C, L)
    assert [writes.membership_change(*pair) for pair in ((before, after), (after, None))] == [
        {"added": [str(L)], "removed": [str(B)], "toggled": [str(C)]},
        {"added": [], "removed": [str(A), str(C), str(L)], "toggled": []},
    ]


def test_the_challenge_names_a_definition_by_its_id_or_a_create_by_its_size() -> None:
    core3, sent = reads.CORE3, [("create", "live", 1), ("replace", "demo", 2)]
    sent.append(("delete", "demo", 3))
    assert [definition_write_text(*s, core3).action_summary for s in sent] == [
        "Create a live trade-group definition of 1 member",
        f"Replace trade-group definition {core3} with 2 members (demo)",
        f"Delete trade-group definition {core3}",
    ]
    with pytest.raises(ValueError, match="environment"):
        definition_write_text("create", "paper", 1)


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_the_trade_groups_gate_refuses_unless_the_flag_reads_true(value: object) -> None:
    refusal = TradeGroupsGate(cast(Callable[[], bool], lambda: value)).refusal()  # any value
    body = json.loads(bytes(refusal.body)) if refusal is not None else {}
    assert (body["code"], body["status"], "reason" in body) == ("trading_disabled", 403, False)
    assert TradeGroupsGate(lambda: True).refusal() is None


@pytest.mark.parametrize(
    ("ready", "flag"), [(False, True), (False, False), (True, False), (True, True)]
)
def test_the_preview_is_refused_outright_until_the_gate_is_built_preview_ready(
    ready: bool, flag: bool
) -> None:
    """The coordinator's 20:23Z rider: refused until S3c's refusals exist, then the flag's."""
    answer = TradeGroupsGate(lambda: flag, preview_ready=ready).preview_refusal()
    shown = {} if answer is None else json.loads(bytes(answer.body))
    code = "trading_disabled" if not (ready and flag) else None
    assert (shown.get("code"), "reason" in shown, answer is None) == (code, False, code is None)
