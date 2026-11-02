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
from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient, Response

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

    def app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(
            make_reconciliation_digest_router(self.principals, self.digests, audit=self.audit)
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
            path = f"/exchange-accounts/{account}/reconciliation/latest"
            return await client.get(path, headers=bearer(who))


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
    world = _seeded()
    only_orders = PrincipalSnapshot(
        uuid.uuid4(), frozenset({"viewer"}), frozenset({Permission.ORDERS_READ}),
        (AccountGrant(ACCOUNT_A, True, False, False),),
    )  # fmt: skip
    world.principals.tokens["orders-only"] = TradingPrincipal(SESSION, only_orders)
    assert (await world.get(ACCOUNT_A, "nobody")).status_code == 401
    for who in ("bare", "orders-only"):
        refused = await world.get(ACCOUNT_A, who)
        assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
        assert refused.json()["required_permissions"] == ["orders:read", "positions:read"]
    assert world.audit.actions() == ["rbac.denied", "rbac.denied"]
    assert all(str(ACCOUNT_A) not in repr(record) for record in world.audit.emitted)


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
