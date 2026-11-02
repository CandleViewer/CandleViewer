"""E29-S07 (#1028, BQ-9; 22 `getReconciliationDigest`, 24-internal-schemas.md Sec.8.5 "The digest"):
the account's latest reconciliation pass as a digest, read under `orders:read` and
`positions:read` in the caller's grants, a foreign, absent or undigested account the same `404`
(SR-E29-13), the Owner's view-as answering as the target with the viewer recorded. The real router
over the real `ReconcileDigests`, its records written by `audit_state` from real reports; the
principals and the audit writer are `oms_reads_world`'s fakes. No network, no clock."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient, Response
from structlog.testing import capture_logs

from candleviewer import app as app_module
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.reconciliation_digest import make_reconciliation_digest_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.view_as import ViewAsRequestContext, bound_view_as
from candleviewer.domain.primitives import AccountId
from candleviewer.oms.reconcile_digest import ReconcileDigests
from candleviewer.oms.reconcile_report import (
    NO_RECORD_IN_FORCE,
    PassError,
    ReconcileReport,
    audit_state,
)
from candleviewer.oms_wiring import build_oms_runtime
from tests.unit.api.oms_reads_world import (
    ACCOUNT_A,
    ACCOUNT_B,
    MISSING,
    SESSION,
    USERS,
    Audit,
    Principals,
    bearer,
    viewing_as,
)

RUN_ID = "a3000000-0000-4000-8000-000000000001"
#: The read's path for an account.
PATH = "/exchange-accounts/{}/reconciliation/latest"
#: Both permissions the read needs, and a grant on A that can view it (live, not frozen).
BOTH = frozenset({Permission.ORDERS_READ, Permission.POSITIONS_READ})
WINDOW = (1_793_613_480_000_000, 1_793_613_600_000_000)  # 2026-11-02 09:58Z to 10:00Z
#: The order a fill landed on while the private stream was down, as the pass names it.
LINK = "cvl-0MduI3fiqJ6h0wkltsuR4T-Jel1-00en"


def _state(account: uuid.UUID, trigger: Any = "reconnect", **lists: Any) -> dict[str, object]:
    report = ReconcileReport(AccountId(account), RUN_ID, trigger, WINDOW, duration_ms=900, **lists)
    return audit_state(report)


@dataclass
class _World:
    principals: Principals = field(default_factory=Principals)
    audit: Audit = field(default_factory=Audit)
    digests: ReconcileDigests = field(default_factory=ReconcileDigests)
    viewing: ViewAsRequestContext | None = None
    #: False: no principal source is composed, as on the fake backend (`501`).
    composed: bool = True

    def app(self) -> FastAPI:
        app = FastAPI()
        principals = self.principals if self.composed else None
        app.include_router(
            make_reconciliation_digest_router(principals, self.digests, audit=self.audit)
        )
        if self.viewing is not None:
            context = self.viewing

            @app.middleware("http")
            async def bound(request: Request, call_next: Any) -> Any:
                with bound_view_as(context):
                    return await call_next(request)

        return app

    @asynccontextmanager
    async def client(self) -> AsyncIterator[AsyncClient]:
        transport = ASGITransport(app=self.app())
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            yield client

    async def get(self, account: uuid.UUID | str, who: str = "manager") -> Response:
        async with self.client() as client:
            return await client.get(PATH.format(account), headers=bearer(who))

    def hold(self, who: str, permissions: frozenset[Permission], *grants: AccountGrant) -> None:
        """A principal `who` holding `permissions` and `grants`, its user id a fixed one."""
        user = uuid.UUID(int=len(self.principals.tokens) + 0xD1)
        snapshot = PrincipalSnapshot(user, frozenset({"manager"}), permissions, grants)
        self.principals.tokens[who] = TradingPrincipal(SESSION, snapshot)


def _seeded() -> _World:
    world = _World()
    world.digests.keep(ACCOUNT_A, _state(ACCOUNT_A, corrected=(LINK,)))
    world.digests.keep(ACCOUNT_B, _state(ACCOUNT_B, sl_repaired=("ETHUSDT",)))
    return world


async def test_scenario_reconnect_with_a_correction_the_digest_lists_the_offline_fill() -> None:
    """The reconnect pass sent the fill the stream missed to its order (a correction, BQ-6): the
    digest a reconnecting client reads names that order, for its summary's link to the row."""
    world = _seeded()
    answer = await world.get(ACCOUNT_A)
    assert answer.status_code == 200 and answer.headers["cache-control"] == "no-store"
    body = answer.json()
    assert (body["exchange_account_id"], body["pass_id"]) == (str(ACCOUNT_A), RUN_ID)
    assert (body["trigger"], body["result"], body["corrected"]) == (
        "reconnect",
        "corrected",
        [LINK],
    )
    assert body["counts"]["corrected"] == 1 and body["sl_repaired"] == []
    assert body["confirmed_at"] == body["gap_window"]["to"] == "2026-11-02T10:00:00.000000Z"
    assert world.audit.emitted == []  # a read writes no record of its own


async def test_scenario_the_reassurance_must_be_true_the_digest_lists_the_repaired_stop() -> None:
    """A pass that found an open position with no native stop: the one it attached a recorded stop
    to is listed `sl_repaired`, the one with no record in force `unprotected`, so a client never
    shows that the exchange-side stops are unaffected and names the repaired stop instead."""
    world = _World()
    naked = PassError("5", NO_RECORD_IN_FORCE, "SOLUSDT")
    world.digests.keep(ACCOUNT_A, _state(ACCOUNT_A, sl_repaired=("BTCUSDT",), errors=(naked,)))
    body = (await world.get(ACCOUNT_A, "viewer")).json()
    assert (body["sl_repaired"], body["unprotected"]) == (["BTCUSDT"], ["SOLUSDT"])
    assert (body["counts"]["sl_repaired"], body["counts"]["unprotected"]) == (1, 1)


async def test_a_read_without_a_session_is_401_and_without_either_permission_403_audited() -> None:
    """Both permissions are needed: holding either alone, or neither, is the same `403`, audited."""
    world = _seeded()
    grant = AccountGrant(ACCOUNT_A, True, False, False)
    world.hold("orders-only", frozenset({Permission.ORDERS_READ}), grant)
    world.hold("positions-only", frozenset({Permission.POSITIONS_READ}), grant)
    assert (await world.get(ACCOUNT_A, "nobody")).status_code == 401
    for who in ("bare", "orders-only", "positions-only"):
        refused = await world.get(ACCOUNT_A, who)
        assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
        assert refused.json()["required_permissions"] == ["orders:read", "positions:read"]
    assert world.audit.actions() == ["rbac.denied"] * 3
    assert all(str(ACCOUNT_A) not in repr(record) for record in world.audit.emitted)


async def test_a_refusal_whose_record_cannot_be_written_stands_and_is_logged() -> None:
    """The audit writer down: a permission refusal is still `403` and an out-of-grant read still
    the same `404`, each logged by the error's class and never turned into a `500`."""
    world = _seeded()
    world.audit.fail = True
    with capture_logs() as logs:
        forbidden = await world.get(ACCOUNT_A, "bare")
        foreign = await world.get(ACCOUNT_B)
    assert (forbidden.status_code, forbidden.json()["code"]) == (403, "forbidden")
    assert (foreign.status_code, foreign.json()["code"]) == (404, "not_found")
    assert [(log["event"], log["error"]) for log in logs] == [
        ("reconcile_digest_denial_unaudited", "RuntimeError")
    ] * 2


async def test_a_read_with_no_principal_source_is_501() -> None:
    """The fake backend composes no identity, so no principal source: nothing is read."""
    world = _seeded()
    world.composed = False
    answer = await world.get(ACCOUNT_A, "owner")
    assert (answer.status_code, answer.json()["code"]) == (501, "not_implemented")
    assert world.audit.emitted == []


@pytest.mark.parametrize(
    "grant",
    [AccountGrant(ACCOUNT_A, True, True, True), AccountGrant(ACCOUNT_A, False, True, False)],
    ids=["frozen", "not-viewing"],
)
async def test_a_grant_that_cannot_view_the_account_gets_the_same_404_audited(
    grant: AccountGrant,
) -> None:
    """C-12.4, C-12.5: a frozen grant on A, and one that cannot view A, are no scope over it: the
    answer is the absent account's, byte for byte, with one `rbac.denied` naming A."""
    world = _seeded()
    world.hold("held", BOTH, grant)
    answer = await world.get(ACCOUNT_A, "held")
    [record] = world.audit.emitted
    absent = await world.get(MISSING, "held")
    assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
    assert (answer.content, answer.headers) == (absent.content, absent.headers)
    assert (record["action"], record["object_id"]) == ("rbac.denied", str(ACCOUNT_A))


async def test_a_foreign_account_is_the_same_404_as_an_absent_one_and_both_are_audited() -> None:
    """Cross-account (IDOR, SR-E29-13; KV-I13): B holds a digest the Manager granted A may not read;
    it is answered as the account nothing knows, byte for byte, and each refusal is one
    `rbac.denied` naming the account asked for, the two records alike but for it."""
    world = _seeded()
    foreign = await world.get(ACCOUNT_B)
    absent = await world.get(MISSING)
    assert (foreign.status_code, foreign.json()["code"]) == (404, "not_found")
    assert (foreign.content, foreign.headers) == (absent.content, absent.headers)
    assert "ETHUSDT" not in foreign.text and str(ACCOUNT_B) not in foreign.text
    named = [(record["action"], record["object_id"]) for record in world.audit.emitted]
    assert named == [("rbac.denied", str(ACCOUNT_B)), ("rbac.denied", str(MISSING))]
    assert world.audit.emitted[0]["reason"] == "account_not_granted:orders:read:granted_accounts"
    strip = {"object_id", "request_id"}
    b, missing = ({k: v for k, v in r.items() if k not in strip} for r in world.audit.emitted)
    assert b == missing


async def test_a_granted_account_with_no_digest_is_404_unaudited() -> None:
    """Nothing reported since the process started (or a restart): the same 404, and no record."""
    world = _World()
    answer = await world.get(ACCOUNT_A)
    assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
    assert world.audit.emitted == []


async def test_the_owner_reads_every_account_and_a_viewer_only_its_own() -> None:
    world = _seeded()
    assert (await world.get(ACCOUNT_B, "owner")).json()["sl_repaired"] == ["ETHUSDT"]
    assert (await world.get(ACCOUNT_A, "viewer")).json()["corrected"] == [LINK]
    assert (await world.get(ACCOUNT_B, "viewer")).status_code == 404


@pytest.mark.parametrize(("account", "status"), [(ACCOUNT_A, 200), (ACCOUNT_B, 404)])
async def test_view_as_reads_in_the_targets_grants_and_records_the_viewer(
    account: uuid.UUID, status: int
) -> None:
    """The Owner viewing as the Manager reads as the Manager: A, never B, and B's refusal names
    the viewer, never the target (#3085)."""
    world = _seeded()
    world.viewing = viewing_as("manager")
    assert (await world.get(account, "manager")).status_code == status
    if status == 404:
        [record] = world.audit.emitted
        assert record["actor_user_id"] == USERS["owner"] and record["actor_label"] == "user:owner"


async def test_a_malformed_id_is_400_and_a_session_store_outage_503() -> None:
    world = _seeded()
    malformed = await world.get("not-an-id")
    assert (malformed.status_code, malformed.json()["code"]) == (400, "validation_failed")
    world.principals.fail = True
    down = await world.get(ACCOUNT_A)
    assert (down.status_code, down.json()["code"]) == (503, "store_unavailable")


def test_create_app_hands_the_runtime_the_digests_the_route_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The composition root (E29-S07): the OMS runtime is handed the very store the read serves
    (`app.state.reconcile_digests`), so a pass the runtime keeps is the one the Owner reads."""
    handed: dict[str, Any] = {}
    build = build_oms_runtime

    def runtime(*args: Any, **kwargs: Any) -> Any:
        handed.update(kwargs)
        return build(*args, **kwargs)

    monkeypatch.setattr(app_module, "build_oms_runtime", runtime)
    # The order principals' resolver, which `create_app` hands its OMS reads as `order_principals`.
    app = app_module.create_app(principal_resolver=cast(Any, Principals()))
    store = app.state.reconcile_digests
    assert isinstance(store, ReconcileDigests) and handed["digests"] is store
    store.keep(ACCOUNT_A, _state(ACCOUNT_A, corrected=(LINK,)))  # as the runtime's jobs keep it
    client = TestClient(app, client=("127.0.0.1", 50000))
    answer = client.get(PATH.format(ACCOUNT_A), headers=bearer("owner"))
    assert (answer.status_code, answer.json()["corrected"]) == (200, [LINK])
