"""#898 (E27-S04 B3c): M2's destroyer of one stored key of one account (fence, record, revoke),
and the seeded mutations its oracles kill (AGENTS §6). Fixed low-entropy vectors, no network."""

from __future__ import annotations

import traceback
from typing import Any
from uuid import UUID, uuid4

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.wiring import build_secrets_service, secrets_bundle
from candleviewer.observability.logging import reset_logging
from candleviewer.secrets import (
    CredentialUnavailable,
    KekUnavailable,
    KeyDestroyer,
    SecretsService,
    mint_key_destroyer,
)
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._helpers import _borrow
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import (
    ACCOUNT,
    API_KEY,
    API_SECRET,
    KEK_V1,
    SNAPSHOT,
    AuditLog,
)
from tests.unit.credentials_m2.test_broker_two_loops import _Rig

OWNER = "00000000-0000-4000-8000-0000000000aa"
OTHER = UUID("00000000-0000-4000-8000-000000000002")
DESTROYED = "security.credential_destroyed"
PAIR = (API_KEY, API_SECRET)
#: Distinct low-entropy markers for the leak check (never a real credential).
MARK_ID, MARK_PRIVATE = "destroyed" + "0" * 9 + "LMNO", "destroyed-" + "y" * 26
_KILLED = (AssertionError, pytest.fail.Exception)
Rig = tuple[SecretsService, InMemoryCredentialStore, AuditLog]


async def _rig() -> Rig:
    store, audit = InMemoryCredentialStore(), AuditLog()
    svc = _svc(_Src(KEK_V1, 1), store=store, audit=audit)
    await svc.start(_ctx())
    return svc, store, audit


@pytest.fixture
async def rig() -> Rig:
    return await _rig()


async def _key(rig: Rig, account: UUID = ACCOUNT, pair: tuple[str, str] = PAIR) -> UUID:
    """Stored and activated on `account`, its DEK cached by one borrow, the records cleared."""
    broker = rig[0]._require()
    meta = await broker.store("demo", account, "main", Secret(pair[0]), Secret(pair[1]), SNAPSHOT)
    rig[1].activate(meta.key_id)
    assert await _borrow(broker, meta.key_id) == pair
    rig[2].records.clear()
    return meta.key_id


async def _destroy(rig: Rig, account: UUID, key_id: UUID, **actor: str) -> None:
    who = {"actor_user_id": OWNER, "actor_role": "owner", **actor}
    await mint_key_destroyer(rig[0]).destroy(account, key_id, **who)


async def test_it_destroys_exactly_the_one_key_and_records_the_owner(rig: Rig) -> None:
    svc, store, audit = rig
    doomed, kept, theirs = await _key(rig), await _key(rig), await _key(rig, OTHER)
    destroyer = secrets_bundle(svc).key_destroyer  # as wiring mints it
    await destroyer.destroy(ACCOUNT, doomed, actor_user_id=OWNER, actor_role="owner")
    assert [store.rows[k]["revoked"] for k in (doomed, kept, theirs)] == [True, False, False]
    assert audit.records == [(DESTROYED, {
        "key_id": str(doomed), "exchange_account_id": str(ACCOUNT), "env": "demo",
        "kek_version": "1", "actor_kind": "user", "actor_role": "owner", "actor_user_id": OWNER,
    })]  # fmt: skip
    broker = svc._require()
    assert broker._cache.get(doomed) is None and broker._cache.get(kept) is not None
    with pytest.raises(CredentialUnavailable, match="credential_unavailable"):
        await _borrow(broker, doomed)
    assert await _borrow(broker, kept) == await _borrow(broker, theirs) == PAIR


async def test_it_fences_the_key_then_writes_its_record_then_revokes_it(rig: Rig) -> None:
    """C-2.9 and the fence: when the record is written, a borrow of the key is refused already and
    the row is not revoked yet."""
    svc, store, audit = rig
    key_id, seen = await _key(rig), list[object]()

    async def sink(action: str, fields: dict[str, str]) -> None:
        if action == DESTROYED:
            try:
                seen.append(await _borrow(svc._require(), key_id))
            except CredentialUnavailable:
                seen.append("fenced")
            seen.append("revoked" if store.rows[key_id]["revoked"] else "live")
        await audit(action, fields)

    svc._require()._audit_sink = sink
    await _destroy(rig, ACCOUNT, key_id)
    assert seen == ["fenced", "live"] and store.rows[key_id]["revoked"]


@pytest.mark.parametrize("case", ["their_key", "our_key_their_account", "unknown", "live_key"])
async def test_a_key_not_the_accounts_is_refused_with_nothing_touched(rig: Rig, case: str) -> None:
    svc, store, audit = rig
    key_id = await _key(rig, OTHER if case == "their_key" else ACCOUNT)
    if case == "live_key":
        store.rows[key_id]["env"] = "live"  # M2 reads its own environment only (C-2.11)
    account = OTHER if case == "our_key_their_account" else ACCOUNT
    with pytest.raises(CredentialUnavailable, match=r"^credential_unavailable$"):
        await _destroy(rig, account, uuid4() if case == "unknown" else key_id)
    assert not store.rows[key_id]["revoked"] and audit.records == []  # no record
    if case != "live_key":
        assert svc._require()._cache.get(key_id) is not None  # its DEK not even flushed
        assert await _borrow(svc._require(), key_id) == PAIR  # not fenced


@pytest.mark.parametrize(
    "actor",
    [{"actor_user_id": ""}, {"actor_role": ""}, {"actor_user_id": "owner-1"}],
    ids=["no_user", "no_role", "not_a_user_id"],
)
async def test_the_acting_owner_is_required_first(rig: Rig, actor: dict[str, str]) -> None:
    key_id = await _key(rig)
    with pytest.raises(ValueError, match=r"acting user|hexadecimal"):
        await _destroy(rig, ACCOUNT, key_id, **actor)
    assert not rig[1].rows[key_id]["revoked"] and rig[2].records == []
    assert await _borrow(rig[0]._require(), key_id) == PAIR


async def test_without_a_kek_the_destroyer_fails_closed() -> None:
    for destroyer in (mint_key_destroyer(SecretsService()), build_secrets_service().key_destroyer):
        with pytest.raises(KekUnavailable):
            await destroyer.destroy(ACCOUNT, uuid4(), actor_user_id=OWNER, actor_role="owner")


async def test_no_key_material_reaches_a_repr_log_record_or_traceback(rig: Rig) -> None:
    destroyer = mint_key_destroyer(rig[0])
    mine, theirs = await _key(rig, pair=(MARK_ID, MARK_PRIVATE)), await _key(rig, OTHER)
    reset_logging()  # structlog's defaults: every level reaches the capture
    with capture_logs() as logs:
        await destroyer.destroy(ACCOUNT, mine, actor_user_id=OWNER, actor_role="owner")
        with pytest.raises(CredentialUnavailable) as refused:
            await destroyer.destroy(ACCOUNT, theirs, actor_user_id=OWNER, actor_role="owner")
    rendered = traceback.TracebackException.from_exception(refused.value, capture_locals=True)
    shown = [repr(destroyer), repr(logs), repr(rig[2].records), "".join(rendered.format())]
    assert [s for s in shown if MARK_ID in s or MARK_PRIVATE in s] == []
    assert "row = " in shown[-1] and rig[1].rows[mine]["revoked"]  # M2's frames did render


def test_a_lane_bound_borrow_refuses_a_key_the_destroyer_destroyed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#913 L3b's lane signing (its own loop, store and sink) joins the destroyer's fence: a key
    destroyed on the serving loop is refused there, as M2's own `destroy` refuses it."""
    with _Rig(monkeypatch) as lanes:
        assert lanes.sign("lane")  # the lane signs with the key first
        destroy = mint_key_destroyer(lanes.svc).destroy
        lanes.serving.run(destroy(ACCOUNT, lanes.key_id, actor_user_id=OWNER, actor_role="owner"))
        with pytest.raises(CredentialUnavailable, match=r"^credential_unavailable$"):
            lanes.sign("lane")
        assert lanes.misses == []


def test_it_exposes_only_its_member_and_stays_an_m2_class() -> None:
    destroyer = mint_key_destroyer(SecretsService())
    assert {n for n in dir(destroyer) if not n.startswith("__")} == {
        "destroy", "_KeyDestroyer__destroy",
    }  # fmt: skip
    with pytest.raises(TypeError, match="may not be subclassed"):
        type("Evil", (KeyDestroyer,), {"__module__": "candleviewer.accounts.evil"})
    assert type("Inside", (KeyDestroyer,), {"__module__": "candleviewer.secrets.inside"})


# --- Seeded mutations (AGENTS §6: safety-critical M2), each killed by its oracle above --------


async def test_mutant_without_the_fence_is_killed() -> None:
    rig = await _rig()
    rig[0]._require()._destroyed = type("Unfenced", (set,), {"add": lambda _s, _k: None})()
    with pytest.raises(_KILLED):
        await test_it_fences_the_key_then_writes_its_record_then_revokes_it(rig)


async def test_mutant_revoking_before_the_record_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    real = CredentialBroker._audit

    async def revoke_first(self: CredentialBroker, action: str, fields: Any, **kw: Any) -> None:
        if action == DESTROYED:
            await self._store.mark_revoked(UUID(fields["key_id"]))
        await real(self, action, fields, **kw)

    monkeypatch.setattr(CredentialBroker, "_audit", revoke_first)
    with pytest.raises(_KILLED):
        await test_it_fences_the_key_then_writes_its_record_then_revokes_it(await _rig())


async def test_mutant_without_the_account_check_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    real = CredentialBroker.destroy

    async def unchecked(self: CredentialBroker, key_id: UUID, **kw: Any) -> None:
        kw.pop("account_id", None)
        await real(self, key_id, **kw)

    monkeypatch.setattr(CredentialBroker, "destroy", unchecked)
    with pytest.raises(_KILLED):
        await test_a_key_not_the_accounts_is_refused_with_nothing_touched(await _rig(), "their_key")
