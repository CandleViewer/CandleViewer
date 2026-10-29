"""Contract, provider side (E27-S04 B3c, #898): `deleteExchangeAccount` as the app serves it, over
the world of `_teardown_world` (the real app, lifecycle and consequence read; recording stand-ins
for M2's destroyer, the disarm and the close). Every answer is checked against 22.

Covered: RBAC and IDOR (only the Owner, never a challenge for anyone else, one byte-equal `404`),
the `422` before the gate spending no code, the `accounts` challenge and its text, a `keys` grant
refused, the fingerprint binding the query, the delete's write-ahead record and its effects in the
ruled order (R6: every key destroyed before the soft delete; ruling 4: the close last), a fault
after each step leaving the account held, switched off and keyless, the exposure refusals (each
`409` recorded denied, the grant spent, replayed under its key), the overrun's `503` and the
retry's `404`, two concurrent deletes writing one record and destroying each key once, and no key
material or exchange text in any answer or record.
"""

from __future__ import annotations

import asyncio
import dataclasses
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
from candleviewer.auth.errors import StepUpMismatch
from tests.contract._teardown_world import (
    KEY,
    SECOND,
    Served,
    _teardown,
    answer,
    records,
    send,
    served,
)
from tests.contract.rbac.rbac_harness import ABSENT, FOREIGN, GRANTED, WS_ORIGIN, bearer, user_id_of
from tests.contract.test_update_exchange_account_provider import OTHER_ENV
from tests.unit.accounts.test_exposure_decision import _position

__all__ = ["_teardown", "served"]

PATH = "/exchange-accounts/{accountId}"
#: The ruled order (R6 and ruling item 4): the switch-off's hold in its hook, the delete's hold,
#: each key destroyed, the soft delete, then the WS revoke, the disarm and the close.
EFFECTS = [
    "hold:account_disabled", "hold:account_deleted", "destroy", "destroy", "ws", "disarm",
    "close", "close",
]  # fmt: skip
PROTECTED = _position(stop_loss=Decimal("58000"))


def delete(s: Served, **kw: Any) -> httpx.Response:
    account = kw.pop("account", GRANTED)
    return send(s, "DELETE", PATH.format(accountId=account), **kw)


def checked(resp: httpx.Response) -> Any:
    return answer(resp, PATH)


@pytest.fixture
def two_keys(served: Served) -> Served:
    served.store.keys[GRANTED][SECOND] = "rotating"
    return served


def test_the_operation_is_served_and_its_record_registered(served: Served) -> None:
    assert ("DELETE", PATH) in served_operations(served.world.app)
    assert "account.deleted" in AUDIT_ACTIONS


def test_the_owner_deletes_a_flat_account_recorded_ahead_then_every_effect_in_order(
    two_keys: Served,
) -> None:
    s = two_keys
    resp = delete(s, choice="flatten_first")
    assert (resp.status_code, checked(resp)) == (204, None)
    (record,) = records(s, "account.deleted")
    assert (record["outcome"], record["object_id"]) == ("success", str(GRANTED))
    after = record["after_state"]
    assert (after["enabled"], after["deleted"], after["flattened"]) == (False, True, False)
    assert after["open_exposure"] == "flatten_first" and after["challenge_id"]
    assert record["before_state"] == {"label": "Granted", "enabled": True}
    assert s.fx.log == EFFECTS and s.spends == ["accounts"]
    assert s.store.deleted == {GRANTED} and s.store.soft_deletes == 1
    assert s.store.keys[GRANTED] == {KEY: "revoked", SECOND: "revoked"}
    assert s.fx.closed == [(str(KEY), "key_revoked"), (str(SECOND), "key_revoked")]
    assert s.fx.disarmed[0]["lifecycle"] == "account_deleted"
    assert s.fx.revoked_ws == ["account_disabled"] and s.fx.counted == ["deleted:flat"]
    assert s.fx.standings.closed(GRANTED) is True


def test_a_key_already_revoked_is_neither_destroyed_again_nor_closed(served: Served) -> None:
    served.store.keys[GRANTED][SECOND] = "revoked"
    assert delete(served).status_code == 204
    assert served.fx.log.count("destroy") == 1 and served.fx.closed == [(str(KEY), "key_revoked")]


@pytest.mark.parametrize("actor", ["manager_with_grant", "manager_without_grant", "viewer"])
@pytest.mark.parametrize("account", [GRANTED, FOREIGN, ABSENT])
def test_no_role_but_the_owner_deletes_403_audited_never_challenged(
    served: Served, actor: str, account: uuid.UUID
) -> None:
    served.world.step_up.elevated = False
    resp = delete(served, actor=actor, account=account)
    assert (resp.status_code, checked(resp)["code"]) == (403, "forbidden")
    (record,) = served.world.audit.records
    assert (record["action"], record["object_id"]) == ("rbac.denied", str(account))
    assert (served.store.calls, served.ports.reads, served.spends, served.fx.log) == (0, 0, [], [])


def test_a_managers_foreign_and_absent_answers_are_byte_equal(served: Served) -> None:
    foreign = delete(served, actor="manager_with_grant", account=FOREIGN)
    assert foreign.content == delete(served, actor="manager_with_grant", account=ABSENT).content


def test_absent_other_environment_and_deleted_accounts_are_one_404_before_the_gate(
    served: Served,
) -> None:
    served.world.step_up.elevated = False
    absent = delete(served, account=ABSENT)
    assert (absent.status_code, checked(absent)["code"]) == (404, "not_found")
    assert absent.content == delete(served, account=OTHER_ENV).content
    served.store.deleted.add(FOREIGN)
    assert absent.content == delete(served, account=FOREIGN).content
    assert served.spends == [] and served.fx.log == []


@pytest.mark.parametrize("choice", ["leave_positions", "close_all"])
def test_any_choice_but_flatten_first_is_422_before_the_gate_spending_no_code(
    served: Served, choice: str
) -> None:
    served.world.step_up.elevated = False
    resp = delete(served, choice=choice)
    assert (resp.status_code, checked(resp)["code"]) == (422, "validation_failed")
    assert (served.spends, served.store.writes, served.ports.reads) == ([], 0, 0)


def test_an_unelevated_delete_is_challenged_restating_it_with_the_typed_label(
    served: Served,
) -> None:
    served.world.step_up.elevated = False
    got = checked(delete(served, choice="flatten_first"))
    assert (got["code"], got["action_class"]) == ("step_up_required", "accounts")
    summary = "Delete account 'Granted' (demo, UID 1000001), open_exposure=flatten_first"
    assert (got["action_summary"], got["target"]) == (summary, "Granted")
    assert got_plain(served)["action_summary"] == "Delete account 'Granted' (demo, UID 1000001)"
    assert served.ports.reads == 0 and served.store.writes == 0 and served.fx.log == []
    twin = dataclasses.replace(served.store.rows[FOREIGN], label="granted")  # not unique
    served.store.rows[FOREIGN] = twin
    assert checked(delete(served))["target"] == str(GRANTED)


def got_plain(s: Served) -> Any:
    return checked(delete(s))


@pytest.mark.parametrize("other", ["keys", "risk_caps"])
def test_another_class_grant_never_admits_a_delete(served: Served, other: str) -> None:
    served.world.step_up.classes = frozenset({other})
    resp = delete(served)
    assert (resp.status_code, checked(resp)["action_class"]) == (403, "accounts")
    assert served.store.writes == 0 and served.fx.log == []


@pytest.mark.parametrize("choice", [None, "flatten_first"])
def test_a_grant_bound_to_one_delete_admits_no_other_query(
    served: Served, monkeypatch: pytest.MonkeyPatch, choice: str | None
) -> None:
    """The harness's grant ignores the fingerprint, so this one binds it as the real service
    does: the grant is for `DELETE` of the raw target with its query; the other query (or none)
    is a mismatch, never admitted, and the bound request is."""
    path = PATH.format(accountId=GRANTED).encode()
    query = b"" if choice == "flatten_first" else b"?open_exposure=flatten_first"
    bound = request_fingerprint("DELETE", path + query, None)
    assert bound != request_fingerprint("DELETE", path + b"?x", None)
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
    refused = delete(served, choice=choice)
    assert (refused.status_code, checked(refused)["code"]) == (403, "step_up_required")
    assert seen[0] != bound and (served.store.writes, served.fx.log) == (0, [])
    admitted = delete(served, choice=None if choice == "flatten_first" else "flatten_first")
    assert admitted.status_code == 204 and seen[-1] == bound


@pytest.mark.parametrize("choice", [None, "flatten_first"])
def test_a_non_flat_account_is_409_recorded_denied_the_grant_spent_and_replayed(
    served: Served, choice: str | None
) -> None:
    served.ports.answer = KeyExposure((PROTECTED,), 2)
    once = str(uuid.uuid4())
    first = delete(served, choice=choice, key=once)
    got = checked(first)
    assert (first.status_code, got["code"]) == (409, "open_exposure")
    assert got["consequences"]["exchange_account_id"] == str(GRANTED)
    (record,) = records(served, "account.deleted")
    assert (record["outcome"], record["reason"]) == ("denied", "open_exposure")
    why = "still_not_flat" if choice else "no_choice"
    assert record["after_state"]["why"] == why and record["after_state"]["challenge_id"]
    assert served.store.writes == 0 and served.fx.log == [] and served.spends == ["accounts"]
    again = delete(served, choice=choice, key=once)
    assert (again.status_code, again.content) == (409, first.content)
    assert again.headers["idempotency-replayed"] == "true" and served.ports.reads == 1
    reuse = delete(served, choice=None if choice else "flatten_first", key=once)
    assert (reuse.status_code, checked(reuse)["code"]) == (409, "idempotency_key_reuse")


@pytest.mark.parametrize("failure", ["auth_error", "ip_not_allowed"])
def test_unknown_exposure_is_always_409_exposure_unknown_and_kept(
    served: Served, failure: str
) -> None:
    """22: an account whose exposure is unknown is never deleted, dead or fixable; `flatten_first`
    changes nothing. The R6 residual's dead account (keys destroyed, never soft-deleted) is one."""
    served.ports.answer = KeyReadFailed(failure)
    once = str(uuid.uuid4())
    first = delete(served, choice="flatten_first", key=once)
    got = checked(first)
    assert (first.status_code, got["code"]) == (409, "exposure_unknown")
    assert got["remedy"] == ("leave_positions" if failure == "auth_error" else "fix_key")
    assert records(served, "account.deleted")[0]["reason"] == "exposure_unknown"
    assert delete(served, choice="flatten_first", key=once).content == first.content
    assert served.store.writes == 0 and served.ports.reads == 1


def test_a_dead_account_left_by_an_interrupted_delete_answers_409_exposure_unknown(
    served: Served,
) -> None:
    """R6's residual: a crash after the destroys and before the soft delete leaves the account
    switched off with no signable key; its retry is `409 exposure_unknown` (22:15074), safe."""
    served.store.keys[GRANTED][KEY] = "revoked"
    served.store.rows[GRANTED] = dataclasses.replace(served.store.rows[GRANTED], is_enabled=False)
    resp = delete(served)
    assert (resp.status_code, checked(resp)["code"]) == (409, "exposure_unknown")
    assert served.store.deleted == set() and served.fx.log == []


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [("timeout", 503, "exchange_unavailable"), ("rate_limited", 502, "exchange_error")],
)
def test_a_failed_read_fails_closed_unrecorded_and_never_kept(
    served: Served, failure: str, status: int, code: str
) -> None:
    served.ports.answer = KeyReadFailed(failure, 10006 if status == 502 else None)
    once = str(uuid.uuid4())
    first = delete(served, key=once)
    assert (first.status_code, checked(first)["code"]) == (status, code)
    assert records(served, "account.deleted") == [] and served.store.writes == 0
    served.ports.answer = KeyExposure((), 0)
    again = delete(served, key=once)  # a first submission: read again, then deleted
    assert again.status_code == 204 and "idempotency-replayed" not in again.headers


def test_a_retry_after_the_204_is_the_byte_equal_404_spending_nothing(served: Served) -> None:
    """The kept `204` is never read back: the replay is behind the gate, and the gate's challenge
    names an account the retry no longer finds, so it is the one `404` of an absent account."""
    once = str(uuid.uuid4())
    assert delete(served, key=once).status_code == 204
    again = delete(served, key=once)
    assert (again.status_code, checked(again)["code"]) == (404, "not_found")
    assert again.content == delete(served, account=uuid.uuid4()).content
    assert served.spends == ["accounts"] and len(records(served, "account.deleted")) == 1
    assert served.fx.log.count("destroy") == 1


def test_an_overrun_close_is_503_never_kept_and_the_retry_is_a_404(two_keys: Served) -> None:
    """The account is deleted by the time the close overruns: the 503 says the close runs on, and
    the retry, a first submission, finds the account gone (the residual the PR states). The first
    key's overrun never skips the later keys' closes: every key is closed (and so tombstoned)
    before the overrun is raised, since no retry would ever reach them (round-1 F1)."""
    s = two_keys
    s.fx.overrun = 1
    once = str(uuid.uuid4())
    resp = delete(s, key=once)
    got = checked(resp)
    assert (resp.status_code, got["code"]) == (503, "exchange_unavailable")
    assert resp.headers["retry-after"] and s.store.deleted == {GRANTED}
    assert s.fx.log == EFFECTS
    assert s.fx.closed == [(str(KEY), "key_revoked"), (str(SECOND), "key_revoked")]
    again = delete(s, key=once)
    assert (again.status_code, checked(again)["code"]) == (404, "not_found")
    assert len(records(s, "account.deleted")) == 1


def test_a_key_m2_does_not_destroy_stops_the_delete_held_switched_off_and_not_deleted(
    two_keys: Served,
) -> None:
    s = two_keys
    s.fx.destroy_fails = {SECOND}
    resp = delete(s)
    got = checked(resp)
    assert (resp.status_code, got["code"]) == (503, "store_unavailable")
    assert "credential" not in resp.text  # M2's text never leaves the destroy
    assert s.store.deleted == set() and s.store.rows[GRANTED].is_enabled is False
    assert s.fx.log == ["hold:account_disabled", "hold:account_deleted", "destroy", "destroy"]
    assert s.fx.standings.closed(GRANTED) is True and s.fx.closed == []


def test_an_unwritable_ahead_record_is_503_and_nothing_changes(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = served.world.audit
    emit = sink.emit

    async def refusing(action: str, **kw: Any) -> None:
        if action == "account.deleted":
            raise AuditError("the audit writer is down")
        await emit(action, **kw)

    monkeypatch.setattr(sink, "emit", refusing)
    resp = delete(served)
    assert (resp.status_code, checked(resp)["code"]) == (503, "audit_unavailable")
    assert served.store.writes == 0 and served.store.rows[GRANTED].is_enabled is True
    assert served.fx.log == ["hold:account_disabled", "release"]  # its hold released
    assert served.fx.standings.closed(GRANTED) is False


def test_an_unwritable_denied_record_is_503_audit_unavailable(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = served.world.audit
    emit = sink.emit

    async def refusing(action: str, **kw: Any) -> None:
        if kw.get("outcome") == "denied" and action == "account.deleted":
            raise AuditError("the audit writer is down")
        await emit(action, **kw)

    monkeypatch.setattr(sink, "emit", refusing)
    served.ports.answer = KeyExposure((PROTECTED,), 0)
    resp = delete(served)
    assert (resp.status_code, checked(resp)["code"]) == (503, "audit_unavailable")
    assert served.spends == ["accounts"] and served.store.writes == 0


def test_two_concurrent_deletes_record_once_and_destroy_each_key_once(two_keys: Served) -> None:
    """The account's lock: the second delete reads the account after the first deleted it, a
    `404` with its grant spent (22 declares no `412` here)."""
    s = two_keys

    async def both() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=s.world.app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            sent = [
                c.delete(PATH.format(accountId=GRANTED),
                         headers=bearer("owner") | {"origin": WS_ORIGIN})
                for _ in range(2)
            ]  # fmt: skip
            return list(await asyncio.gather(*sent))

    answers = asyncio.run(both())
    assert sorted(r.status_code for r in answers) == [204, 404]
    assert len(records(s, "account.deleted")) == 1 and s.fx.log.count("destroy") == 2
    assert s.spends == ["accounts"] * 2 and s.fx.counted == ["deleted:flat"]
    assert len(s.lifecycle[-1].locks) == 0  # the table holds nothing once both answered


def test_no_answer_and_no_record_carries_key_material_or_exchange_text(served: Served) -> None:
    served.ports.answer = KeyReadFailed("auth_error")
    shown = [delete(served).text]
    served.ports.answer = KeyExposure((), 0)
    shown += [delete(served).text, json.dumps(served.world.audit.records, default=str)]
    for text in shown:
        assert "A1b2" not in text and "AbC1" not in text  # the keys' last four
        assert "ret_msg" not in text and "permission_snapshot" not in text
