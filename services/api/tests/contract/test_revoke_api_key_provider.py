"""Contract, provider side (E27-S04 B3d, #898): `revokeApiKey` as the app serves it, over the world
of `_teardown_world`. Every answer is checked against 22.

Covered: RBAC and IDOR (only the Owner, never a challenge for anyone else; one byte-equal `404` for
an absent key, another account's key and an absent account), the `422` before the gate, both
step-up classes (`keys`, and `accounts` for every `flatten_first`, a no-op included; the grant
binding the query), the ahead record and the completion record, the ruled effect order (hold, WS
revoke, disarm, then the close; the WS revoke and the disarm only for the last signable key), the
exposure refusals (recorded denied, the grant spent, replayed), the repeats (completed, after an
overrun that then completes, after an overrun that overruns again, after a restart that lost the
memo: one completion record each, the same payload), two concurrent first revokes destroying the
key once, a revoke against a delete, F-01's WS refusal once the last key goes, and no key material
or exchange text anywhere.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest

from candleviewer.accounts.exposure import KeyExposure, KeyReadFailed
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.step_up_challenge import request_fingerprint
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.errors import AuditError
from candleviewer.audit.writer import KEYED_ACTIONS, keyed_record_id
from candleviewer.auth.errors import StepUpMismatch
from tests.contract._teardown_world import (
    KEY,
    SECOND,
    THEIRS,
    Served,
    _teardown,
    answer,
    records,
    send,
    served,
)
from tests.contract.rbac.rbac_harness import ABSENT, FOREIGN, GRANTED, WS_ORIGIN, bearer, user_id_of
from tests.contract.rbac.test_scope_and_ws import _auth, _sub
from tests.unit.accounts._fakes import key_row
from tests.unit.accounts.test_exposure_decision import _position

__all__ = ["_teardown", "served"]

PATH = "/exchange-accounts/{accountId}/keys/{keyId}"
#: Ruling item 4's order for the last signable key: destroy, hold, WS revoke, disarm, then close.
LAST = ["destroy", "standing_revoke", "ws", "disarm", "close"]
#: Another key remains signable: no WS revoke, no disarm.
NOT_LAST = ["destroy", "standing_revoke", "close"]
#: A repeat: no destroy; the pending effects again, the close awaited again.
REPEAT_LAST = LAST[1:]
PROTECTED = _position(stop_loss=Decimal("58000"))
BARE = _position(symbol="ETHUSDT", side="short")


def revoke(s: Served, **kw: Any) -> httpx.Response:
    account, key_id = kw.pop("account", GRANTED), kw.pop("key_id", KEY)
    return send(s, "DELETE", PATH.format(accountId=account, keyId=key_id), **kw)


def checked(resp: httpx.Response) -> Any:
    return answer(resp, PATH)


def completions(s: Served) -> list[dict[str, Any]]:
    return records(s, "api_key.revoked")


@pytest.fixture
def two_keys(served: Served) -> Served:
    served.store.keys[GRANTED][SECOND] = "rotating"  # a rotating key still signs (22)
    return served


def test_the_operation_is_served_and_its_completion_record_registered_and_keyed(
    served: Served,
) -> None:
    assert ("DELETE", PATH) in served_operations(served.world.app)
    assert {"api_key.revoke", "api_key.revoked"} <= AUDIT_ACTIONS
    assert "api_key.revoked" in KEYED_ACTIONS


def test_the_owner_revokes_the_last_signable_key_recorded_ahead_and_completed_once(
    served: Served,
) -> None:
    resp = revoke(served)
    assert (resp.status_code, checked(resp)) == (204, None)
    (ahead,) = records(served, "api_key.revoke")
    assert (ahead["outcome"], ahead["object_kind"], ahead["object_id"]) == (
        "success", "api_key", str(KEY),
    )  # fmt: skip
    assert ahead["after_state"] == {
        "exchange_account_id": str(GRANTED), "open_exposure": None, "last_signable": True,
    }  # fmt: skip
    (done,) = completions(served)
    assert done["record_id"] == keyed_record_id("api_key.revoked", str(KEY))
    assert (done["outcome"], done["severity"]) == ("success", "warning")
    assert done["after_state"] == {
        "exchange_account_id": str(GRANTED), "flattened": False,
        "accounts_closed": [str(GRANTED)],
    }  # fmt: skip
    assert done["request_id"] == ahead["request_id"]
    assert served.fx.log == LAST and served.spends == []  # a `keys` window, not a code
    assert served.fx.revoked_ws == ["key_revoked"]
    assert served.fx.disarmed[0]["lifecycle"] == "key_revoked"
    assert served.fx.closed == [(str(KEY), "key_revoked")]
    assert served.store.keys[GRANTED][KEY] == "revoked"
    assert served.store.rows[GRANTED].is_enabled is True  # ruling 11: never the account's flag


def test_a_key_that_is_not_the_last_signable_reads_no_exposure_and_ends_no_subscription(
    two_keys: Served,
) -> None:
    s = two_keys
    s.ports.answer = KeyExposure((PROTECTED,), 3)  # would refuse, were it read
    assert revoke(s).status_code == 204
    assert s.ports.reads == 0 and s.fx.log == NOT_LAST and s.fx.revoked_ws == []
    assert records(s, "api_key.revoke")[0]["after_state"]["last_signable"] is False


def test_a_flatten_first_on_another_signable_key_is_a_recorded_no_op_that_spends_the_code(
    two_keys: Served,
) -> None:
    s = two_keys
    resp = revoke(s, choice="flatten_first")
    assert resp.status_code == 204 and s.spends == ["accounts"] and s.ports.reads == 0
    (ahead,) = records(s, "api_key.revoke")
    assert ahead["after_state"]["challenge_id"]  # the `accounts` grant it spent
    (done,) = completions(s)
    assert (done["after_state"]["flattened"], done["after_state"]["reason"]) == (
        False, "other_key_signable",
    )  # fmt: skip


@pytest.mark.parametrize("actor", ["manager_with_grant", "manager_without_grant", "viewer"])
@pytest.mark.parametrize("account", [GRANTED, FOREIGN, ABSENT])
@pytest.mark.parametrize("choice", [None, "flatten_first"])
def test_no_role_but_the_owner_revokes_403_audited_never_challenged_nothing_destroyed(
    served: Served, actor: str, account: uuid.UUID, choice: str | None
) -> None:
    served.world.step_up.elevated = False
    resp = revoke(served, actor=actor, account=account, choice=choice)
    assert (resp.status_code, checked(resp)["code"]) == (403, "forbidden")
    (record,) = served.world.audit.records
    assert (record["action"], record["object_id"]) == ("rbac.denied", str(account))
    assert (served.store.calls, served.spends, served.fx.log) == (0, [], [])


def test_an_absent_key_another_accounts_key_and_an_absent_account_are_one_404(
    served: Served,
) -> None:
    served.world.step_up.elevated = False
    absent = revoke(served, key_id=uuid.uuid4())
    assert (absent.status_code, checked(absent)["code"]) == (404, "not_found")
    assert absent.content == revoke(served, key_id=THEIRS).content  # FOREIGN's key, on A
    assert absent.content == revoke(served, account=ABSENT).content
    served.store.deleted.add(GRANTED)
    assert absent.content == revoke(served).content  # a deleted account's key
    assert served.spends == [] and served.fx.log == []


def test_an_open_exposure_outside_its_enum_is_422_before_the_gate(served: Served) -> None:
    served.world.step_up.elevated = False
    resp = revoke(served, choice="close_all")
    assert (resp.status_code, checked(resp)["code"]) == (422, "validation_failed")
    assert served.spends == [] and served.store.calls == 0


@pytest.mark.parametrize(
    ("choice", "cls", "tail"),
    [(None, "keys", ""), ("leave_positions", "keys", ", open_exposure=leave_positions"),
     ("flatten_first", "accounts", ", open_exposure=flatten_first")],
)  # fmt: skip
def test_the_challenge_restates_the_key_and_account_in_its_class_with_no_target(
    served: Served, choice: str | None, cls: str, tail: str
) -> None:
    served.world.step_up.elevated = False
    got = checked(revoke(served, choice=choice))
    assert (got["code"], got["action_class"]) == ("step_up_required", cls)
    summary = f"Revoke key '{KEY}' of account 'Granted' (demo, UID 1000001){tail}"
    assert got["action_summary"] == summary and got.get("target") is None
    assert served.fx.log == [] and served.ports.reads == 0


def test_a_keys_grant_never_admits_a_flatten_first_revoke(served: Served) -> None:
    served.world.step_up.classes = frozenset({"keys"})
    resp = revoke(served, choice="flatten_first")
    assert (resp.status_code, checked(resp)["action_class"]) == (403, "accounts")
    assert served.fx.log == []
    served.world.step_up.classes = frozenset({"accounts"})  # and an `accounts` one no plain one
    plain = revoke(served)
    assert (plain.status_code, checked(plain)["action_class"]) == (403, "keys")


def test_an_accounts_grant_bound_to_one_revoke_admits_no_other_query(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The harness's grant ignores the fingerprint, so this one binds it as the real service
    does: the raw target with its query. Another key's target is refused, the bound one admitted."""
    target = PATH.format(accountId=GRANTED, keyId=KEY) + "?open_exposure=flatten_first"
    bound = request_fingerprint("DELETE", target.encode(), None)
    seen: list[str] = []
    pending = served.world.step_up.record_pending

    async def bound_grant(session_id: str, action_class: str, *, fingerprint: str) -> Any:
        seen.append(fingerprint)
        if fingerprint != bound:
            who, challenge = str(user_id_of("owner")), str(uuid.uuid4())
            raise StepUpMismatch(
                action_class, user_id=who, challenge_id=challenge, bound=bound, refused=fingerprint
            )
        return await pending(session_id, action_class, fingerprint=fingerprint)

    monkeypatch.setattr(served.world.step_up, "consume_single_use", bound_grant)
    served.store.keys[GRANTED][SECOND] = "active"
    refused = revoke(served, key_id=SECOND, choice="flatten_first")
    assert (refused.status_code, checked(refused)["code"]) == (403, "step_up_required")
    assert seen[0] != bound and served.fx.log == []
    assert revoke(served, choice="flatten_first").status_code == 204 and seen[-1] == bound


@pytest.mark.parametrize("choice", [None, "flatten_first"])
def test_the_last_key_of_a_non_flat_account_is_409_recorded_denied_and_replayed(
    served: Served, choice: str | None
) -> None:
    served.ports.answer = KeyExposure((PROTECTED,), 1)
    once = str(uuid.uuid4())
    first = revoke(served, choice=choice, key=once)
    got = checked(first)
    assert (first.status_code, got["code"]) == (409, "open_exposure")
    (record,) = records(served, "api_key.revoke")
    assert (record["outcome"], record["reason"]) == ("denied", "open_exposure")
    assert record["after_state"]["why"] == ("still_not_flat" if choice else "no_choice")
    assert served.fx.log == [] and served.store.keys[GRANTED][KEY] == "active"
    again = revoke(served, choice=choice, key=once)
    assert (again.status_code, again.content) == (409, first.content)
    assert again.headers["idempotency-replayed"] == "true" and served.ports.reads == 1


def test_leave_positions_with_a_position_lacking_a_native_stop_is_409_c_2_6(
    served: Served,
) -> None:
    served.ports.answer = KeyExposure((PROTECTED, BARE), 0)
    resp = revoke(served, choice="leave_positions")
    assert (resp.status_code, checked(resp)["code"]) == (409, "open_exposure")
    assert records(served, "api_key.revoke")[0]["after_state"]["why"] == "native_stop_missing"
    assert served.fx.log == []


def test_leave_positions_with_every_position_stopped_revokes_the_last_key(served: Served) -> None:
    served.ports.answer = KeyExposure((PROTECTED,), 1)
    assert revoke(served, choice="leave_positions").status_code == 204
    assert served.fx.log == LAST


def test_a_dead_account_revokes_its_last_key_only_with_leave_positions_saying_why(
    served: Served,
) -> None:
    served.ports.answer = KeyReadFailed("auth_error")
    refused = revoke(served)
    assert (refused.status_code, checked(refused)["remedy"]) == (409, "leave_positions")
    served.world.audit.records.clear()
    assert revoke(served, choice="leave_positions").status_code == 204
    after = records(served, "api_key.revoke")[0]["after_state"]
    assert (after["code"], after["lifted"]) == ("exposure_unknown", True)
    assert after["key_errors"] == [{"key_id": str(KEY), "error": "auth_error"}]


def test_an_unwritable_ahead_record_is_503_and_nothing_is_destroyed(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = served.world.audit
    emit = sink.emit

    async def refusing(action: str, **kw: Any) -> None:
        if action == "api_key.revoke":
            raise AuditError("the audit writer is down")
        await emit(action, **kw)

    monkeypatch.setattr(sink, "emit", refusing)
    resp = revoke(served)
    assert (resp.status_code, checked(resp)["code"]) == (503, "audit_unavailable")
    assert served.fx.log == [] and served.store.keys[GRANTED][KEY] == "active"


def test_an_unwritable_denied_record_is_503_audit_unavailable(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = served.world.audit
    emit = sink.emit

    async def refusing(action: str, **kw: Any) -> None:
        if kw.get("outcome") == "denied":
            raise AuditError("the audit writer is down")
        await emit(action, **kw)

    monkeypatch.setattr(sink, "emit", refusing)
    served.ports.answer = KeyExposure((PROTECTED,), 0)
    resp = revoke(served, choice="flatten_first")
    assert (resp.status_code, checked(resp)["code"]) == (503, "audit_unavailable")
    assert served.spends == ["accounts"] and served.fx.log == []


def test_a_key_m2_does_not_destroy_is_503_and_nothing_after_runs(served: Served) -> None:
    served.fx.destroy_fails = {KEY}
    resp = revoke(served)
    assert (resp.status_code, checked(resp)["code"]) == (503, "store_unavailable")
    assert "credential" not in resp.text and served.fx.log == ["destroy"]
    assert completions(served) == []


# -- the repeats (R7) ---------------------------------------------------------------------------


def test_a_repeat_of_a_completed_revoke_destroys_nothing_and_writes_no_second_record(
    served: Served,
) -> None:
    assert revoke(served).status_code == 204
    served.fx.log.clear()
    again = revoke(served)
    assert again.status_code == 204 and served.fx.log == REPEAT_LAST
    assert len(records(served, "api_key.revoke")) == 1 and len(completions(served)) == 1


def test_a_second_revoke_of_a_key_derives_the_same_record_id_in_the_revoke_actions_own_namespace(
    served: Served,
) -> None:
    """R7 (coordinator ruling 2026-10-29 02:59Z): the completion record's id is `uuid5` of the
    revoke action's own namespace and the key id alone, since revocation is terminal. A second
    revoke of the same key derives the same id and lands as a repeat with one record, and no other
    keyed action can collide with it on the same key id."""
    assert revoke(served).status_code == 204
    first = completions(served)[0]["record_id"]
    assert revoke(served).status_code == 204
    assert [r["record_id"] for r in completions(served)] == [first]
    assert first == keyed_record_id("api_key.revoked", str(KEY))
    others = {a: ns for a, ns in KEYED_ACTIONS.items() if a != "api_key.revoked"}
    assert KEYED_ACTIONS["api_key.revoked"] not in set(others.values())
    assert first not in {keyed_record_id(a, str(KEY)) for a in others}


@pytest.mark.parametrize(("choice", "cls"), [(None, "keys"), ("flatten_first", "accounts")])
def test_a_repeat_is_decided_after_the_gate_so_an_unelevated_one_is_challenged(
    served: Served, choice: str | None, cls: str
) -> None:
    """22: the repeat is the caller's cost, decided after the gate: a revoked key's repeat without
    a live window (or a fresh `accounts` code) is challenged and completes nothing."""
    served.fx.overrun = 1
    assert revoke(served).status_code == 503  # revoked, the close still pending
    served.fx.log.clear()
    served.world.step_up.elevated = False
    got = checked(revoke(served, choice=choice))
    assert (got["code"], got["action_class"]) == ("step_up_required", cls)
    assert served.fx.log == [] and completions(served) == []


def test_an_overrun_is_503_with_no_completion_then_the_repeat_completes_it_once(
    served: Served,
) -> None:
    served.fx.overrun = 1
    once = str(uuid.uuid4())
    first = revoke(served, key=once)
    assert (first.status_code, checked(first)["code"]) == (503, "exchange_unavailable")
    assert first.headers["retry-after"] and completions(served) == []
    assert served.fx.log == LAST and served.store.keys[GRANTED][KEY] == "revoked"
    served.fx.log.clear()
    again = revoke(served, key=once)  # never kept: a first submission, now a repeat
    assert again.status_code == 204 and "idempotency-replayed" not in again.headers
    assert served.fx.log == REPEAT_LAST and len(completions(served)) == 1
    assert len(records(served, "api_key.revoke")) == 1 and served.fx.log.count("destroy") == 0


def test_a_repeat_that_overruns_again_is_503_with_no_record(served: Served) -> None:
    served.fx.overrun = 2
    assert revoke(served).status_code == 503
    again = revoke(served)
    assert (again.status_code, checked(again)["code"]) == (503, "exchange_unavailable")
    assert completions(served) == []
    assert revoke(served).status_code == 204 and len(completions(served)) == 1


def test_a_repeat_after_a_restart_that_lost_the_memo_writes_the_same_record_once(
    two_keys: Served,
) -> None:
    """R7: the first call's payload is kept per key; once the memo is gone the repeat derives it
    from the same inputs, so the record it would write is the first's (only the call's own
    `request_id` differs), and the keyed write lands once."""
    s = two_keys
    s.fx.overrun = 1
    assert revoke(s, choice="flatten_first").status_code == 503  # no completion yet
    s.revoker[-1]._memo.clear()  # a restart: the memo is in-process
    assert revoke(s, choice="flatten_first").status_code == 204
    (done,) = completions(s)
    assert done["after_state"] == {
        "exchange_account_id": str(GRANTED), "flattened": False,
        "accounts_closed": [str(GRANTED)], "reason": "other_key_signable",
    }  # fmt: skip
    assert revoke(s, choice="flatten_first").status_code == 204 and len(completions(s)) == 1


def test_the_memo_and_the_derivation_give_the_first_calls_payload(two_keys: Served) -> None:
    """The ruling's pin: the payload a repeat would write is the first's, memo or not."""
    s = two_keys
    s.fx.overrun = 2
    revoke(s, choice="flatten_first")
    memo = s.revoker[-1]._memo[KEY]
    s.revoker[-1]._memo.clear()
    revoke(s, choice="flatten_first")  # overruns again: derives, writes nothing
    assert revoke(s, choice="flatten_first").status_code == 204
    (done,) = completions(s)
    assert done["after_state"] == memo.state(GRANTED)


def test_a_crash_between_the_completion_record_and_the_204_replays_to_one_row(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ruling's kill test, in-process: the record lands, then the call dies before its `204`;
    the retry is a repeat whose keyed write lands on the same id, one row and one `204`."""
    sink = served.world.audit
    keyed = sink.emit_keyed
    died = False

    async def landing_then_dying(action: str, name: str, **kw: Any) -> None:
        nonlocal died
        await keyed(action, name, **kw)
        if not died:
            died = True
            raise RuntimeError("SIGKILL after the record, before the 204")

    monkeypatch.setattr(sink, "emit_keyed", landing_then_dying)
    first = revoke(served)
    assert first.status_code == 503 and len(completions(served)) == 1  # landed, then died
    assert revoke(served).status_code == 204 and len(completions(served)) == 1


def test_an_unwritable_completion_record_is_503_and_the_repeat_writes_it(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = served.world.audit
    keyed = sink.emit_keyed
    calls = 0

    async def once_down(action: str, name: str, **kw: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AuditError("the audit writer is down")
        await keyed(action, name, **kw)

    monkeypatch.setattr(sink, "emit_keyed", once_down)
    first = revoke(served)
    assert (first.status_code, checked(first)["code"]) == (503, "audit_unavailable")
    assert revoke(served).status_code == 204 and len(completions(served)) == 1


# -- races and the WS ----------------------------------------------------------------------------


def _concurrently(s: Served, *paths: str) -> list[httpx.Response]:
    async def all_of() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=s.world.app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            sent = [c.delete(p, headers=bearer("owner") | {"origin": WS_ORIGIN}) for p in paths]
            return list(await asyncio.gather(*sent))

    return asyncio.run(all_of())


def test_two_concurrent_first_revokes_destroy_the_key_once(served: Served) -> None:
    target = PATH.format(accountId=GRANTED, keyId=KEY)
    answers = _concurrently(served, target, target)
    assert [r.status_code for r in answers] == [204, 204]
    assert served.fx.log.count("destroy") == 1 and len(records(served, "api_key.revoke")) == 1
    assert len(completions(served)) == 1


def test_two_concurrent_revokes_of_the_last_two_keys_read_the_exposure_for_the_second(
    two_keys: Served,
) -> None:
    """The account's lock: the second revoke reads the first's key revoked, so it is the last
    signable key and its exposure decides; both never pass as `other_key_signable`."""
    s = two_keys
    s.ports.answer = KeyExposure((PROTECTED,), 0)
    paths = [PATH.format(accountId=GRANTED, keyId=k) for k in (KEY, SECOND)]
    answers = _concurrently(s, *paths)
    assert sorted(r.status_code for r in answers) == [204, 409]
    assert list(s.store.keys[GRANTED].values()).count("revoked") == 1


def test_a_revoke_against_a_delete_finds_the_account_gone(served: Served) -> None:
    answers = _concurrently(
        served, f"/exchange-accounts/{GRANTED}", PATH.format(accountId=GRANTED, keyId=KEY)
    )
    assert [r.status_code for r in answers] == [204, 404]
    assert served.fx.log.count("destroy") == 1 and completions(served) == []


def test_after_the_last_key_goes_the_account_is_closed_to_a_new_sub(served: Served) -> None:
    """F-01: `KeyStandings.closed` holds once the last signable key is revoked, and a WS `sub`
    naming the account is refused `account_scope_denied`."""
    world = served.world

    def subscribed() -> str:
        with world.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            assert _auth(ws, "owner")["t"] == "auth_ok"
            result = _sub(ws, "orders", GRANTED)
        return "sub_ok" if result["ok"] else str(result["error"]["code"])

    world.app.state.account_health.standings.observe([], began=None)  # no read lists it yet
    assert subscribed() == "sub_ok"
    _list_granted(served)
    assert revoke(served).status_code == 204
    assert served.fx.standings.closed(GRANTED) is True
    assert subscribed() == "account_scope_denied"


def _list_granted(s: Served) -> None:
    """One tracking read listing the granted account with its key (the standing's `observe`)."""
    standings = s.fx.standings
    standings.observe([key_row(GRANTED, key=KEY)], began=standings.read_begins())


def test_the_revoked_frame_reaches_a_live_subscription_with_its_shape(served: Served) -> None:
    """23 §9.5: the account's subscription ends with a `revoked` frame, reason `key_revoked`,
    `resubscribe_allowed: false`, after its `permission_change`."""
    world = served.world
    with world.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        assert _auth(ws, "owner")["t"] == "auth_ok"
        assert _sub(ws, "orders", GRANTED)["ok"]
        assert revoke(served).status_code == 204
        frames = [ws.receive_json() for _ in range(2)]
    kinds = [f["t"] for f in frames]
    assert kinds == ["permission_change", "revoked"], frames
    revoked = frames[1]["p"]
    assert revoked["reason"] == "key_revoked" and revoked["resubscribe_allowed"] is False


def test_no_answer_and_no_record_carries_key_material_or_exchange_text(served: Served) -> None:
    served.ports.answer = KeyReadFailed("auth_error")
    shown = [revoke(served).text, revoke(served, choice="leave_positions").text]
    shown.append(json.dumps(served.world.audit.records, default=str))
    for text in shown:
        assert "A1b2" not in text and "AbC1" not in text  # the keys' last four
        assert "ret_msg" not in text and "permission_snapshot" not in text
